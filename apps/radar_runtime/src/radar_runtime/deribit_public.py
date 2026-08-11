from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

PRODUCTION_PUBLIC_ENDPOINT = "wss://www.deribit.com/ws/api/v2"
MAX_PENDING_INBOUND_FRAMES = 10_000
PUBLIC_TRANSPORT_CLOSE_TIMEOUT_SECONDS = 5.0
TRANSPORT_HEARTBEAT_REQUEST_ID_PREFIX = "optimatrix.transport-heartbeat"
PUBLIC_METHODS = frozenset(
    {
        "public/subscribe",
        "public/unsubscribe",
        "public/get_instruments",
        "public/get_index_chart_data",
        "public/get_delivery_prices",
        "public/get_instrument",
        "public/get_combos",
        "public/get_order_book",
        "public/status",
        "public/get_time",
        "public/set_heartbeat",
    }
)
TRANSPORT_CLOSE_CODE_ALLOWLIST = frozenset(
    {
        "1000",
        "1001",
        "1002",
        "1003",
        "1006",
        "1007",
        "1008",
        "1009",
        "1010",
        "1011",
        "1012",
        "1013",
        "1014",
        "1015",
        "NOT_AVAILABLE",
        "OTHER",
    }
)
TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST = frozenset({"CLEAN", "ABNORMAL"})
TRANSPORT_EXCEPTION_CLASS_ALLOWLIST = frozenset(
    {
        "NONE",
        "PublicProtocolIncompatibility",
        "PublicProtocolError",
        "ConnectionClosedOK",
        "ConnectionClosedError",
        "OSError",
        "SSLError",
        "TimeoutError",
        "EOFError",
        "WebSocketException",
        "OTHER",
    }
)


class PublicProtocolError(RuntimeError):
    """The production-public JSON-RPC session violated the consumed contract."""


class PublicSessionError(PublicProtocolError):
    """The transport session is unusable and requires a full reconnect."""


class PublicProtocolIncompatibility(PublicProtocolError):
    """The consumed official protocol shape is incompatible with this runtime."""


class SendControlKind(StrEnum):
    SEND_COMPLETED = "SEND_COMPLETED"
    SEND_FAILED = "SEND_FAILED"


class SendFailureKind(StrEnum):
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class ConnectionControlReason(StrEnum):
    REMOTE_CONNECTION_CLOSED = "REMOTE_CONNECTION_CLOSED"
    TRANSPORT_READ_FAILURE = "TRANSPORT_READ_FAILURE"
    PROTOCOL_INCOMPATIBILITY = "PROTOCOL_INCOMPATIBILITY"


@dataclass(frozen=True)
class SendControlEvent:
    kind: SendControlKind
    request_id: int
    boundary_monotonic_ms: int
    failure: SendFailureKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SendControlKind):
            raise TypeError("send control kind must be a SendControlKind")
        if self.failure is not None and not isinstance(self.failure, SendFailureKind):
            raise TypeError("send control failure must be a SendFailureKind")
        if isinstance(self.request_id, bool) or not isinstance(self.request_id, int):
            raise TypeError("send control request id must be an integer")
        if self.request_id <= 0:
            raise ValueError("send control request id must be positive")
        if isinstance(self.boundary_monotonic_ms, bool) or not isinstance(
            self.boundary_monotonic_ms, int
        ):
            raise TypeError("send control boundary must be an integer")
        if self.boundary_monotonic_ms < 0:
            raise ValueError("send control boundary must be non-negative")
        if self.kind is SendControlKind.SEND_COMPLETED and self.failure is not None:
            raise ValueError("successful send control cannot carry a failure")
        if self.kind is SendControlKind.SEND_FAILED and self.failure is None:
            raise ValueError("failed send control requires a failure kind")


class InboundEnvelope(dict[str, object]):
    """One wire or control event in the unique application sequence."""

    def __init__(
        self,
        message: dict[str, object],
        *,
        session_epoch: int,
        ingress_seq: int,
        received_monotonic_ms: int,
        control_event: SendControlEvent | None = None,
    ) -> None:
        if session_epoch <= 0 or ingress_seq <= 0 or received_monotonic_ms < 0:
            raise ValueError("inbound envelope identity must be positive")
        if control_event is not None and not isinstance(control_event, SendControlEvent):
            raise TypeError("inbound control event must be immutable")
        if control_event is not None and message:
            raise ValueError("inbound control event cannot also carry a wire message")
        super().__init__(message)
        self.session_epoch = session_epoch
        self.ingress_seq = ingress_seq
        self.received_monotonic_ms = received_monotonic_ms
        self.control_event = control_event


class DeribitPublicClient:
    """Thin production-public transport with one inbound queue and no fact ownership."""

    def __init__(
        self,
        endpoint: str = PRODUCTION_PUBLIC_ENDPOINT,
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> None:
        if endpoint != PRODUCTION_PUBLIC_ENDPOINT:
            raise ValueError("only the Deribit production-public endpoint is authorized")
        if session_epoch <= 0:
            raise ValueError("session_epoch must be positive")
        if (
            isinstance(rpc_deadline_ms, bool)
            or not isinstance(rpc_deadline_ms, int)
            or rpc_deadline_ms <= 0
        ):
            raise ValueError("rpc_deadline_ms must be a positive integer")
        self.endpoint = endpoint
        self.session_epoch = session_epoch
        self.connection_timeout_seconds = rpc_deadline_ms / 1_000
        self.close_timeout_seconds = min(
            self.connection_timeout_seconds,
            PUBLIC_TRANSPORT_CLOSE_TIMEOUT_SECONDS,
        )
        self._connection: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._inbound: asyncio.Queue[InboundEnvelope] = asyncio.Queue(
            maxsize=MAX_PENDING_INBOUND_FRAMES
        )
        self._next_application_seq = 1
        self._next_transport_heartbeat_seq = 1
        self._pending_transport_heartbeat_id: str | None = None
        self._reader_error: PublicProtocolError | None = None
        self.last_inbound_monotonic = time.monotonic()
        self.queue_high_water_frames = 0
        self.overflow_count = 0
        self.received_frame_count = 0
        self.enqueued_envelope_count = 0
        self.send_control_event_count = 0
        self.connection_error_event_count = 0

    async def __aenter__(self) -> DeribitPublicClient:
        self._connection = await connect(
            self.endpoint,
            open_timeout=self.connection_timeout_seconds,
            close_timeout=self.close_timeout_seconds,
            ping_interval=None,
            max_size=2**24,
            proxy=None,
        )
        self._reader_task = asyncio.create_task(self._reader(), name="deribit-public-reader")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._connection is not None:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self.close_timeout_seconds):
                    await self._connection.close()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

    async def send_request(
        self,
        *,
        request_id: int,
        method: str,
        params: dict[str, object],
    ) -> None:
        if method not in PUBLIC_METHODS:
            raise PublicProtocolError(f"method is outside production-public allowlist: {method}")
        if request_id <= 0:
            raise PublicProtocolError("request id must be positive")
        await self._send_json_rpc(request_id=request_id, method=method, params=params)

    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope:
        if self._reader_error is not None and self._inbound.empty():
            raise self._reader_error
        if timeout_seconds is None:
            envelope = await self._inbound.get()
        else:
            envelope = await asyncio.wait_for(self._inbound.get(), timeout_seconds)
        return envelope

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        values: list[InboundEnvelope] = []
        while True:
            try:
                values.append(self._inbound.get_nowait())
            except asyncio.QueueEmpty:
                return tuple(values)

    def enqueue_send_control(self, event: SendControlEvent) -> None:
        if not isinstance(event, SendControlEvent):
            raise TypeError("transport send control must be immutable")
        self._enqueue_application_event(
            {},
            received_monotonic_ms=event.boundary_monotonic_ms,
            control_event=event,
        )
        self.send_control_event_count += 1

    async def stop_intake(self) -> None:
        if self._reader_task is None:
            return
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        self._reader_task = None

    async def _reader(self) -> None:
        if self._connection is None:
            raise RuntimeError("reader started without connection")
        try:
            async for raw_message in self._connection:
                self.last_inbound_monotonic = time.monotonic()
                message = _decode_message(raw_message)
                received_monotonic_ms = time.monotonic_ns() // 1_000_000
                self.received_frame_count += 1
                if _is_heartbeat_test_request(message):
                    await self._respond_to_heartbeat_test_request()
                if self._consume_transport_heartbeat_response(message):
                    continue
                self._enqueue_application_event(
                    message,
                    received_monotonic_ms=received_monotonic_ms,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, PublicProtocolError)
                else PublicSessionError(f"production-public reader failed: {exc}")
            )
            reason = (
                ConnectionControlReason.PROTOCOL_INCOMPATIBILITY
                if isinstance(error, PublicProtocolIncompatibility)
                else ConnectionControlReason.TRANSPORT_READ_FAILURE
            )
            close_code = _bounded_close_code(_exception_close_code(exc))
            exception_class = _bounded_exception_class(exc)
        else:
            error = PublicSessionError("production-public connection closed")
            reason = ConnectionControlReason.REMOTE_CONNECTION_CLOSED
            close_code = _bounded_close_code(getattr(self._connection, "close_code", None))
            exception_class = "NONE"
        self._reader_error = error
        self._enqueue_connection_error(
            error,
            reason=reason,
            close_code=close_code,
            exception_class=exception_class,
        )

    def _enqueue_wire_message(
        self,
        message: dict[str, object],
        *,
        received_monotonic_ms: int,
    ) -> None:
        self.received_frame_count += 1
        self._enqueue_application_event(
            message,
            received_monotonic_ms=received_monotonic_ms,
        )

    async def _respond_to_heartbeat_test_request(self) -> None:
        if self._pending_transport_heartbeat_id is not None:
            raise PublicProtocolIncompatibility(
                "received another heartbeat test_request before public/test completed"
            )
        request_id = (
            f"{TRANSPORT_HEARTBEAT_REQUEST_ID_PREFIX}:"
            f"{self.session_epoch}:{self._next_transport_heartbeat_seq}"
        )
        self._next_transport_heartbeat_seq += 1
        self._pending_transport_heartbeat_id = request_id
        await self._send_json_rpc(
            request_id=request_id,
            method="public/test",
            params={},
        )

    def _consume_transport_heartbeat_response(self, message: dict[str, object]) -> bool:
        request_id = message.get("id")
        pending_request_id = self._pending_transport_heartbeat_id
        if request_id != pending_request_id:
            if isinstance(request_id, str) and request_id.startswith(
                f"{TRANSPORT_HEARTBEAT_REQUEST_ID_PREFIX}:"
            ):
                raise PublicProtocolIncompatibility(
                    "public/test response does not match the pending transport heartbeat"
                )
            return False
        if pending_request_id is None:
            return False
        self._pending_transport_heartbeat_id = None
        result = message.get("result")
        if (
            "error" in message
            or not isinstance(result, dict)
            or not isinstance(result.get("version"), str)
            or not result["version"]
        ):
            raise PublicProtocolIncompatibility("public/test result lacks a valid version")
        return True

    async def _send_json_rpc(
        self,
        *,
        request_id: int | str,
        method: str,
        params: dict[str, object],
    ) -> None:
        if self._connection is None:
            raise PublicSessionError("public connection is not open")
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        async with self._send_lock:
            await self._connection.send(json.dumps(message, separators=(",", ":"), allow_nan=False))

    def _enqueue_connection_error(
        self,
        error: PublicProtocolError,
        *,
        reason: ConnectionControlReason,
        close_code: str | None = None,
        exception_class: str | None = None,
    ) -> None:
        kind = (
            "PROTOCOL_INCOMPATIBILITY"
            if reason is ConnectionControlReason.PROTOCOL_INCOMPATIBILITY
            else "SESSION_FAILURE"
        )
        try:
            bounded_close_code = _bounded_close_code(None) if close_code is None else close_code
            bounded_exception_class = (
                _bounded_exception_class(error) if exception_class is None else exception_class
            )
            if bounded_close_code not in TRANSPORT_CLOSE_CODE_ALLOWLIST:
                raise ValueError("transport close code is outside the bounded allowlist")
            if bounded_exception_class not in TRANSPORT_EXCEPTION_CLASS_ALLOWLIST:
                raise ValueError("transport exception class is outside the bounded allowlist")
            close_disposition = "CLEAN" if bounded_close_code in {"1000", "1001"} else "ABNORMAL"
            self._enqueue_application_event(
                {
                    "jsonrpc": "2.0",
                    "method": "connection_error",
                    "params": {
                        "kind": kind,
                        "reason": reason.value,
                        "close_code": bounded_close_code,
                        "close_disposition": close_disposition,
                        "exception_class": bounded_exception_class,
                    },
                },
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )
        except PublicSessionError:
            return
        self.connection_error_event_count += 1

    def _enqueue_application_event(
        self,
        message: dict[str, object],
        *,
        received_monotonic_ms: int,
        control_event: SendControlEvent | None = None,
    ) -> None:
        envelope = InboundEnvelope(
            message,
            session_epoch=self.session_epoch,
            ingress_seq=self._next_application_seq,
            received_monotonic_ms=received_monotonic_ms,
            control_event=control_event,
        )
        try:
            self._inbound.put_nowait(envelope)
        except asyncio.QueueFull as exc:
            self.overflow_count += 1
            raise PublicSessionError("inbound queue overflow") from exc
        self._next_application_seq += 1
        self.enqueued_envelope_count += 1
        self.queue_high_water_frames = max(
            self.queue_high_water_frames,
            self._inbound.qsize(),
        )


def _exception_close_code(exc: Exception) -> object:
    received = getattr(exc, "rcvd", None)
    if received is not None:
        code = getattr(received, "code", None)
        if code is not None:
            return code
    return getattr(exc, "code", None)


def _bounded_close_code(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "NOT_AVAILABLE"
    serialized = str(value)
    return serialized if serialized in TRANSPORT_CLOSE_CODE_ALLOWLIST else "OTHER"


def _bounded_exception_class(exc: Exception) -> str:
    name = type(exc).__name__
    if name in TRANSPORT_EXCEPTION_CLASS_ALLOWLIST:
        return name
    if isinstance(exc, PublicProtocolIncompatibility):
        return "PublicProtocolIncompatibility"
    if isinstance(exc, PublicProtocolError):
        return "PublicProtocolError"
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if isinstance(exc, OSError):
        return "OSError"
    return "OTHER"


def _decode_message(raw_message: str | bytes) -> dict[str, object]:
    try:
        decoded: Any = json.loads(raw_message, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PublicProtocolIncompatibility("invalid JSON-RPC message") from exc
    if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
        raise PublicProtocolIncompatibility("message is not a JSON-RPC 2.0 object")
    return decoded


def _is_heartbeat_test_request(message: dict[str, object]) -> bool:
    if message.get("method") != "heartbeat":
        return False
    params = message.get("params")
    return isinstance(params, dict) and params.get("type") == "test_request"

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
PUBLIC_METHODS = frozenset(
    {
        "public/subscribe",
        "public/unsubscribe",
        "public/get_instruments",
        "public/get_instrument",
        "public/get_combos",
        "public/status",
        "public/get_time",
        "public/set_heartbeat",
        "public/test",
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
        self._connection: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._inbound: asyncio.Queue[InboundEnvelope] = asyncio.Queue(
            maxsize=MAX_PENDING_INBOUND_FRAMES
        )
        self._next_application_seq = 1
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
            close_timeout=self.connection_timeout_seconds,
            ping_interval=None,
            max_size=2**24,
            proxy=None,
        )
        self._reader_task = asyncio.create_task(self._reader(), name="deribit-public-reader")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._connection is not None:
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
        responding_to_test_request: bool = False,
    ) -> None:
        if method not in PUBLIC_METHODS:
            raise PublicProtocolError(f"method is outside production-public allowlist: {method}")
        if method == "public/test" and not responding_to_test_request:
            raise PublicProtocolError("public/test is allowed only as a heartbeat response")
        if request_id <= 0:
            raise PublicProtocolError("request id must be positive")
        if self._connection is None:
            raise PublicSessionError("public connection is not open")
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        await self._connection.send(json.dumps(message, separators=(",", ":"), allow_nan=False))

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
                self._enqueue_wire_message(
                    _decode_message(raw_message),
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
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
        else:
            error = PublicSessionError("production-public connection closed")
            reason = ConnectionControlReason.REMOTE_CONNECTION_CLOSED
        self._reader_error = error
        self._enqueue_connection_error(error, reason=reason)

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

    def _enqueue_connection_error(
        self,
        error: PublicProtocolError,
        *,
        reason: ConnectionControlReason,
    ) -> None:
        kind = (
            "PROTOCOL_INCOMPATIBILITY"
            if reason is ConnectionControlReason.PROTOCOL_INCOMPATIBILITY
            else "SESSION_FAILURE"
        )
        try:
            self._enqueue_application_event(
                {
                    "jsonrpc": "2.0",
                    "method": "connection_error",
                    "params": {
                        "error": str(error),
                        "kind": kind,
                        "reason": reason.value,
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


def _decode_message(raw_message: str | bytes) -> dict[str, object]:
    try:
        decoded: Any = json.loads(raw_message, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PublicProtocolIncompatibility("invalid JSON-RPC message") from exc
    if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
        raise PublicProtocolIncompatibility("message is not a JSON-RPC 2.0 object")
    return decoded

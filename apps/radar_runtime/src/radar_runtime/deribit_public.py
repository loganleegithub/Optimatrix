from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from market_monitor.deribit import subscription_batches, validate_subscription_ack
from websockets.asyncio.client import ClientConnection, connect

PRODUCTION_PUBLIC_ENDPOINT = "wss://www.deribit.com/ws/api/v2"
MAX_PENDING_NOTIFICATIONS = 10_000
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


class PublicProtocolIncompatibility(PublicProtocolError):
    """The consumed official protocol shape is incompatible with this runtime."""


@dataclass(frozen=True)
class _NotificationEnvelope:
    message: dict[str, object]
    received_monotonic_ms: int
    channel: str | None
    subscription_generation: int | None


class ReceivedNotification(dict[str, object]):
    def __init__(self, envelope: _NotificationEnvelope) -> None:
        super().__init__(envelope.message)
        self.received_monotonic_ms = envelope.received_monotonic_ms


class DeribitPublicClient:
    def __init__(self, endpoint: str = PRODUCTION_PUBLIC_ENDPOINT) -> None:
        if endpoint != PRODUCTION_PUBLIC_ENDPOINT:
            raise ValueError("only the Deribit production-public endpoint is authorized")
        self.endpoint = endpoint
        self._connection: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._next_request_id = 1
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._notifications: asyncio.Queue[_NotificationEnvelope] = asyncio.Queue(
            maxsize=MAX_PENDING_NOTIFICATIONS
        )
        self._next_subscription_generation = 1
        self._active_subscription_generations: dict[str, int] = {}
        self._reader_error: PublicProtocolError | None = None
        self.last_inbound_monotonic = time.monotonic()

    async def __aenter__(self) -> DeribitPublicClient:
        self._connection = await connect(
            self.endpoint,
            open_timeout=20,
            close_timeout=10,
            ping_interval=None,
            max_size=2**24,
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
        for future in self._pending.values():
            if not future.done():
                future.set_exception(PublicProtocolError("public connection closed"))

    async def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        if method not in PUBLIC_METHODS:
            raise PublicProtocolError(f"method is outside production-public allowlist: {method}")
        if method == "public/test" and not responding_to_test_request:
            raise PublicProtocolError("public/test is allowed only as a heartbeat response")
        if self._connection is None:
            raise PublicProtocolError("public connection is not open")
        request_id = self._next_request_id
        self._next_request_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()
        self._pending[request_id] = future
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        await self._connection.send(json.dumps(message, separators=(",", ":"), allow_nan=False))
        try:
            return await asyncio.wait_for(future, timeout=30)
        finally:
            self._pending.pop(request_id, None)

    async def subscribe(self, channels: Sequence[str]) -> None:
        for batch in subscription_batches(channels):
            previous = {
                channel: self._active_subscription_generations.get(channel) for channel in batch
            }
            for channel in batch:
                self._active_subscription_generations[channel] = self._next_subscription_generation
                self._next_subscription_generation += 1
            try:
                result = await self.request("public/subscribe", {"channels": list(batch)})
                validate_subscription_ack(batch, result)
            except Exception:
                for channel, generation in previous.items():
                    if generation is None:
                        self._active_subscription_generations.pop(channel, None)
                    else:
                        self._active_subscription_generations[channel] = generation
                raise

    async def unsubscribe(self, channels: Sequence[str]) -> None:
        for batch in subscription_batches(channels):
            result = await self.request("public/unsubscribe", {"channels": list(batch)})
            validate_subscription_ack(batch, result)
            for channel in batch:
                self._active_subscription_generations.pop(channel, None)

    async def next_notification(self, timeout_seconds: float | None = None) -> dict[str, object]:
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        while True:
            if self._reader_error is not None:
                raise self._reader_error
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining is None:
                envelope = await self._notifications.get()
            else:
                envelope = await asyncio.wait_for(self._notifications.get(), remaining)
            if self._is_current(envelope):
                return ReceivedNotification(envelope)

    def drain_notifications(self) -> tuple[dict[str, object], ...]:
        values: list[dict[str, object]] = []
        while True:
            try:
                envelope = self._notifications.get_nowait()
            except asyncio.QueueEmpty:
                return tuple(values)
            if self._is_current(envelope):
                values.append(ReceivedNotification(envelope))

    def _is_current(self, envelope: _NotificationEnvelope) -> bool:
        if envelope.channel is None:
            return True
        return (
            self._active_subscription_generations.get(envelope.channel)
            == envelope.subscription_generation
        )

    async def _reader(self) -> None:
        if self._connection is None:
            raise RuntimeError("reader started without connection")
        try:
            async for raw_message in self._connection:
                self.last_inbound_monotonic = time.monotonic()
                message = _decode_message(raw_message)
                request_id = message.get("id")
                if isinstance(request_id, int):
                    if request_id in self._pending:
                        future = self._pending[request_id]
                        if "error" in message:
                            future.set_exception(
                                PublicProtocolError(f"Deribit JSON-RPC error: {message['error']!r}")
                            )
                        elif "result" not in message:
                            future.set_exception(
                                PublicProtocolError("JSON-RPC response lacks result")
                            )
                        else:
                            future.set_result(message["result"])
                    continue
                else:
                    channel: str | None = None
                    generation: int | None = None
                    if message.get("method") == "subscription":
                        params = message.get("params")
                        if isinstance(params, dict) and isinstance(params.get("channel"), str):
                            channel = params["channel"]
                            generation = self._active_subscription_generations.get(channel)
                    try:
                        self._notifications.put_nowait(
                            _NotificationEnvelope(
                                message=message,
                                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                                channel=channel,
                                subscription_generation=generation,
                            )
                        )
                    except asyncio.QueueFull as exc:
                        raise PublicProtocolError("notification queue overflow") from exc
            raise PublicProtocolError("production-public connection closed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, PublicProtocolError)
                else PublicProtocolError(f"production-public reader failed: {exc}")
            )
            self._reader_error = error
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            with contextlib.suppress(asyncio.QueueFull):
                self._notifications.put_nowait(
                    _NotificationEnvelope(
                        message={
                            "jsonrpc": "2.0",
                            "method": "connection_error",
                            "params": {"error": str(exc)},
                        },
                        received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                        channel=None,
                        subscription_generation=None,
                    )
                )


def _decode_message(raw_message: str | bytes) -> dict[str, object]:
    try:
        decoded: Any = json.loads(raw_message, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PublicProtocolError("invalid JSON-RPC message") from exc
    if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
        raise PublicProtocolError("message is not a JSON-RPC 2.0 object")
    return decoded

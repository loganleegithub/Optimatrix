from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
import radar_runtime.deribit_public as deribit_public
from radar_runtime.deribit_public import (
    DeribitPublicClient,
    InboundEnvelope,
    PublicProtocolError,
)


class IncomingConnection:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)
        self.sent: list[str] = []

    def __aiter__(self) -> IncomingConnection:
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        return None


def test_reader_enqueues_every_inbound_frame_once_in_one_continuous_sequence() -> None:
    async def scenario() -> tuple[InboundEnvelope, ...]:
        client = DeribitPublicClient(session_epoch=7, rpc_deadline_ms=30_000)
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {"channel": "book.X.100ms", "data": {"change_id": 1}},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 10, "result": ["book.X.100ms"]}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 11,
                        "error": {"code": 10_028, "message": "too_many_requests"},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 999, "result": "late"}),
                json.dumps({"jsonrpc": "2.0", "id": 12, "result": {"version": "2.1.1"}}),
            ]
        )

        await client._reader()
        return client.drain_envelopes()

    frames = asyncio.run(scenario())
    wire_frames = tuple(frame for frame in frames if frame.get("method") != "connection_error")

    assert [frame.ingress_seq for frame in wire_frames] == [1, 2, 3, 4, 5]
    assert {frame.session_epoch for frame in wire_frames} == {7}
    assert len({(frame.session_epoch, frame.ingress_seq) for frame in wire_frames}) == 5
    assert all(isinstance(frame.received_monotonic_ms, int) for frame in wire_frames)
    assert [frame.get("id") for frame in wire_frames[1:]] == [10, 11, 999, 12]
    assert frames[-1].get("method") == "connection_error"


def test_reader_preserves_fatal_protocol_failure_identity_in_ingress() -> None:
    async def scenario() -> InboundEnvelope:
        client = DeribitPublicClient(session_epoch=7, rpc_deadline_ms=30_000)
        client._connection = IncomingConnection(["not-json"])  # type: ignore[assignment]

        await client._reader()
        return client.drain_envelopes()[-1]

    frame = asyncio.run(scenario())
    params = frame.get("params")

    assert frame.get("method") == "connection_error"
    assert isinstance(params, dict)
    assert params["kind"] == "PROTOCOL_INCOMPATIBILITY"


def test_client_sends_without_response_future_or_client_subscription_generation() -> None:
    async def scenario() -> dict[str, object]:
        client = DeribitPublicClient(session_epoch=3, rpc_deadline_ms=30_000)
        connection = IncomingConnection([])
        client._connection = connection  # type: ignore[assignment]

        await client.send_request(
            request_id=41,
            method="public/get_time",
            params={},
        )

        assert not hasattr(client, "_pending")
        assert not hasattr(client, "_notifications")
        assert not hasattr(client, "_active_subscription_generations")
        assert len(connection.sent) == 1
        return cast(dict[str, object], json.loads(connection.sent[0]))

    assert asyncio.run(scenario()) == {
        "jsonrpc": "2.0",
        "id": 41,
        "method": "public/get_time",
        "params": {},
    }


def test_public_test_remains_a_guarded_control_response() -> None:
    async def scenario() -> None:
        client = DeribitPublicClient(session_epoch=1, rpc_deadline_ms=30_000)
        client._connection = IncomingConnection([])  # type: ignore[assignment]

        with pytest.raises(PublicProtocolError, match="heartbeat response"):
            await client.send_request(
                request_id=1,
                method="public/test",
                params={},
            )

        await client.send_request(
            request_id=2,
            method="public/test",
            params={},
            responding_to_test_request=True,
        )

    asyncio.run(scenario())


def test_transport_rejects_nonproduction_endpoint_and_private_method() -> None:
    with pytest.raises(ValueError, match="production-public"):
        DeribitPublicClient(
            "wss://test.deribit.com/ws/api/" + "v" + "2",
            session_epoch=1,
            rpc_deadline_ms=30_000,
        )

    async def scenario() -> None:
        client = DeribitPublicClient(session_epoch=1, rpc_deadline_ms=30_000)
        with pytest.raises(PublicProtocolError, match="allowlist"):
            await client.send_request(
                request_id=1,
                method="private/get_positions",
                params={},
            )

    asyncio.run(scenario())


def test_transport_connection_deadline_has_no_implementation_default() -> None:
    client = DeribitPublicClient(
        session_epoch=1,
        rpc_deadline_ms=1_234,
    )

    assert client.connection_timeout_seconds == 1.234


def test_transport_ignores_ambient_system_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    async def fake_connect(uri: str, **kwargs: object) -> IncomingConnection:
        observed["uri"] = uri
        observed.update(kwargs)
        return IncomingConnection([])

    monkeypatch.setattr(deribit_public, "connect", fake_connect)

    async def scenario() -> None:
        async with DeribitPublicClient(session_epoch=1, rpc_deadline_ms=1_234):
            pass

    asyncio.run(scenario())

    assert observed["uri"] == deribit_public.PRODUCTION_PUBLIC_ENDPOINT
    assert observed["open_timeout"] == 1.234
    assert observed["close_timeout"] == 1.234
    assert observed["proxy"] is None


def test_transport_records_real_queue_high_water_and_overflow() -> None:
    client = DeribitPublicClient(session_epoch=1, rpc_deadline_ms=30_000)
    client._inbound = asyncio.Queue(maxsize=1)
    client._enqueue_wire_message(
        {"jsonrpc": "2.0", "id": 1, "result": "ok"},
        received_monotonic_ms=1_000,
    )

    with pytest.raises(PublicProtocolError, match="overflow"):
        client._enqueue_wire_message(
            {"jsonrpc": "2.0", "id": 2, "result": "late"},
            received_monotonic_ms=1_001,
        )

    assert client.queue_high_water_frames == 1
    assert client.overflow_count == 1


def test_send_receipt_is_an_immutable_control_event_in_the_same_ordered_queue() -> None:
    client = DeribitPublicClient(session_epoch=7, rpc_deadline_ms=30_000)
    event = deribit_public.SendControlEvent(
        kind=deribit_public.SendControlKind.SEND_COMPLETED,
        request_id=41,
        boundary_monotonic_ms=1_001,
    )

    client.enqueue_send_control(event)
    client._enqueue_wire_message(
        {"jsonrpc": "2.0", "id": 41, "result": "ok"},
        received_monotonic_ms=1_002,
    )

    control, response = client.drain_envelopes()
    assert control.control_event is event
    assert response.control_event is None
    assert control.ingress_seq == response.ingress_seq == 1
    with pytest.raises(FrozenInstanceError):
        event.boundary_monotonic_ms = 1_003  # type: ignore[misc]

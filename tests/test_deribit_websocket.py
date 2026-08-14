from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from optimatrix.decision import MarketObservation, schedule_decision_windows
from optimatrix.deribit_snapshot import evaluate_live_btc_snapshot
from optimatrix.deribit_websocket import (
    DEFAULT_DERIBIT_WEBSOCKET_API,
    BtcWebSocketCache,
    DeribitPublicWebSocketFeed,
    ForwardObservationGap,
    RestBookSnapshot,
    WebSocketConnection,
    WebSocketSequenceGap,
)
from optimatrix.market import EventState, MarketDataSource
from optimatrix.runtime import DeribitPublicRuntimeSource
from optimatrix.session import current_deribit_session

NOW = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
NAMES = (
    "BTC-13AUG26-93000-P",
    "BTC-13AUG26-95000-P",
    "BTC-13AUG26-105000-C",
    "BTC-13AUG26-107000-C",
)


def test_initial_snapshots_and_increment_publish_one_immutable_watermark(policy) -> None:
    cache, metadata, boundary_ms = _ready_cache()

    first = _cut(cache, boundary_ms + 1_000)
    first_client = first.client(instrument_metadata=metadata, depth=20)
    first_book = cast(
        object,
        first_client.call(
            "public/get_order_book",
            {"instrument_name": NAMES[0], "depth": 20},
        ),
    )

    _book_change(
        cache,
        NAMES[0],
        change_id=1_001,
        previous_change_id=1_000,
        source_timestamp_ms=boundary_ms + 500,
        received_timestamp_ms=boundary_ms + 550,
        bid="0.0011",
    )
    second = _cut(cache, boundary_ms + 1_000)
    second_book = second.client(instrument_metadata=metadata, depth=20).call(
        "public/get_order_book",
        {"instrument_name": NAMES[0], "depth": 20},
    )

    assert first.continuity_epoch == second.continuity_epoch == 1
    assert first.source_floor_ms == boundary_ms + 100
    assert first.source_watermark_ms == boundary_ms + 370
    assert second.source_watermark_ms == boundary_ms + 500
    assert first_book != second_book

    evaluation = evaluate_live_btc_snapshot(
        client=second.client(instrument_metadata=metadata, depth=20),
        policy=policy,
        now=NOW,
        event_state=EventState.NONE,
        maximum_books=32,
        depth=20,
        market_data_source=MarketDataSource.DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1,
    )

    assert not evaluation.observation.data_health_blockers
    assert evaluation.context.evidence.market_data_source is (
        MarketDataSource.DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1
    )
    assert evaluation.context.evidence.market_source_min_ms == boundary_ms + 100
    assert evaluation.context.evidence.market_source_max_ms == boundary_ms + 500
    assert {quote.continuity_epoch for quote in evaluation.quotes} == {1}
    assert evaluation.methodology.book_fetch_mode == (
        "PUBLIC_WEBSOCKET_BOOK_TICKER_100MS_INCREMENTAL"
    )
    recovered = MarketObservation.from_object(evaluation.observation.as_object())
    assert recovered.identity == evaluation.observation.identity


def test_sequence_gap_requires_one_rest_seed_and_later_websocket_continuation() -> None:
    cache, metadata, boundary_ms = _ready_cache()
    rest_calls: list[str] = []

    def rest_resync(instrument_name: str) -> RestBookSnapshot:
        rest_calls.append(instrument_name)
        return RestBookSnapshot(
            instrument_name=instrument_name,
            result={
                "instrument_name": instrument_name,
                "state": "open",
                "timestamp": boundary_ms + 600,
                "change_id": 2_000,
                "bids": [["0.0012", "2"]],
                "asks": [["0.0014", "2"]],
            },
            source_timestamp_ms=boundary_ms + 600,
            received_timestamp_ms=boundary_ms + 650,
        )

    feed = DeribitPublicWebSocketFeed(
        cache=cache,
        received_timestamp_ms=lambda: boundary_ms + 550,
        rest_resync=rest_resync,
    )
    frame = _subscription_frame(
        f"book.{NAMES[0]}.100ms",
        _book_payload(
            NAMES[0],
            change_id=1_100,
            source_timestamp_ms=boundary_ms + 500,
            update_type="change",
            previous_change_id=999,
            bid="0.0011",
        ),
    )
    feed._accept_frame(_NoopConnection(), frame)

    assert rest_calls == [NAMES[0]]
    _book_change(
        cache,
        NAMES[0],
        change_id=2_001,
        previous_change_id=2_000,
        source_timestamp_ms=boundary_ms + 700,
        received_timestamp_ms=boundary_ms + 750,
        bid="0.0013",
    )
    with pytest.raises(ForwardObservationGap, match="WEBSOCKET_BOOK_SEQUENCE_GAP"):
        _cut(cache, boundary_ms + 1_000)

    recovered = _cut(cache, boundary_ms + 1_000)
    response = recovered.client(instrument_metadata=metadata, depth=20).call(
        "public/get_order_book",
        {"instrument_name": NAMES[0], "depth": 20},
    )
    result = cast(Mapping[str, object], response.result)  # type: ignore[union-attr]
    assert result["change_id"] == 2_001
    assert result["bids"] == [["0.0013", "1"], ["0.0012", "2"]]


def test_direct_sequence_mismatch_exposes_expected_and_actual_change_ids() -> None:
    cache, _metadata, boundary_ms = _ready_cache()

    with pytest.raises(WebSocketSequenceGap) as raised:
        _book_change(
            cache,
            NAMES[1],
            change_id=9_999,
            previous_change_id=7,
            source_timestamp_ms=boundary_ms + 500,
            received_timestamp_ms=boundary_ms + 550,
            bid="0.0029",
        )

    assert raised.value.instrument_name == NAMES[1]
    assert raised.value.expected_change_id == 1_001
    assert raised.value.actual_previous_change_id == 7


def test_disconnect_is_a_gap_and_reconnect_requires_fresh_full_snapshots(policy) -> None:
    cache, metadata, boundary_ms = _ready_cache()
    cache.disconnect(reason="EOF")
    assert cache.begin_connection() == 2
    _populate_connection(cache, boundary_ms=boundary_ms + 1_000, change_id_base=3_000)

    with pytest.raises(ForwardObservationGap, match="WEBSOCKET_DISCONNECTED:epoch=1"):
        _cut(cache, boundary_ms + 2_000)

    recovered = _cut(cache, boundary_ms + 2_000)
    assert recovered.continuity_epoch == 2
    evaluation = evaluate_live_btc_snapshot(
        client=recovered.client(instrument_metadata=metadata, depth=20),
        policy=policy,
        now=NOW + timedelta(seconds=1),
        event_state=EventState.NONE,
        maximum_books=32,
        depth=20,
        market_data_source=MarketDataSource.DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1,
    )
    assert {quote.continuity_epoch for quote in evaluation.quotes} == {2}


def test_incomplete_and_stale_stream_cuts_fail_closed() -> None:
    boundary_ms = int(NOW.timestamp() * 1_000)
    cache = BtcWebSocketCache()
    cache.seed_index_history(
        _history(boundary_ms),
        received_timestamp_ms=boundary_ms,
    )
    cache.configure_instruments(NAMES)
    cache.begin_connection()
    cache.accept_subscription(
        channel="deribit_price_index.btc_usd",
        data={"index_name": "btc_usd", "price": "100000", "timestamp": boundary_ms + 100},
        received_timestamp_ms=boundary_ms + 150,
    )
    for index, name in enumerate(NAMES):
        source_ms = boundary_ms + 200 + index * 50
        cache.accept_subscription(
            channel=f"book.{name}.100ms",
            data=_book_payload(name, change_id=1_000 + index, source_timestamp_ms=source_ms),
            received_timestamp_ms=source_ms + 50,
        )
    with pytest.raises(ForwardObservationGap, match="WEBSOCKET_TICKER_SNAPSHOT_PENDING"):
        _cut(cache, boundary_ms + 1_000)

    for index, name in enumerate(NAMES):
        source_ms = boundary_ms + 220 + index * 50
        cache.accept_subscription(
            channel=f"ticker.{name}.100ms",
            data=_ticker_payload(name, source_timestamp_ms=source_ms),
            received_timestamp_ms=source_ms + 50,
        )
    with pytest.raises(ForwardObservationGap, match="WEBSOCKET_CUT_SOURCE_STALE"):
        _cut(cache, boundary_ms + 20_000)


def test_transport_subscribes_only_public_aggregated_btc_channels() -> None:
    boundary_ms = int(NOW.timestamp() * 1_000)
    cache = BtcWebSocketCache()
    cache.seed_index_history(_history(boundary_ms), received_timestamp_ms=boundary_ms)
    cache.configure_instruments(NAMES)
    connection = _IdleConnection()
    opened: list[tuple[str, float]] = []
    audit: list[str] = []

    def factory(url: str, timeout_seconds: float) -> WebSocketConnection:
        opened.append((url, timeout_seconds))
        return connection

    feed = DeribitPublicWebSocketFeed(
        cache=cache,
        received_timestamp_ms=lambda: boundary_ms,
        rest_resync=lambda _name: pytest.fail("REST resync is not expected"),
        connection_factory=factory,
        audit_callback=lambda method, _params, _timeout: audit.append(method),
    )
    feed.start()
    assert connection.sent_two.wait(timeout=2)
    feed.close()

    messages = [json.loads(message) for message in connection.sent]
    assert opened == [(DEFAULT_DERIBIT_WEBSOCKET_API, 10.0)]
    assert [message["method"] for message in messages] == [
        "public/set_heartbeat",
        "public/subscribe",
    ]
    channels = messages[1]["params"]["channels"]
    assert len(channels) == 9
    assert all("raw" not in channel for channel in channels)
    assert all(
        channel == "deribit_price_index.btc_usd" or channel.endswith(".100ms")
        for channel in channels
    )
    assert audit == ["public/set_heartbeat", "public/subscribe"]


def test_runtime_source_consumes_cache_without_http_market_polling(policy, monkeypatch) -> None:
    cache, metadata, boundary_ms = _ready_cache()
    monkeypatch.setattr("optimatrix.runtime.AUTHORIZED_RUNTIME_POLICY_IDENTITY", policy.identity)
    source = DeribitPublicRuntimeSource(policy=policy, event_state=EventState.NONE)
    fake_feed = _PreparedFeed(cache, known_at_ms=boundary_ms + 1_000)
    session = current_deribit_session(NOW, phase_policy=policy.session)
    source._cache = cache
    source._feed = fake_feed  # type: ignore[assignment]
    source._feed_session_id = session.session_id
    source._instrument_metadata = metadata

    def forbidden_http(_method: str, _params: Mapping[str, object]) -> object:
        raise AssertionError("a WebSocket market cut must not poll HTTP market methods")

    source.client.call = forbidden_http  # type: ignore[method-assign]
    window = next(
        item
        for item in schedule_decision_windows(
            session=session,
            channel_id=policy.channel_id,
            policy=policy.window,
        )
        if item.starts_at <= NOW < item.ends_at
    )
    try:
        evaluation = source.snapshot(
            now=NOW,
            target_window=window,
            required_instrument_names=(),
        )
    finally:
        source.close()

    assert fake_feed.configure_calls == [tuple(sorted(NAMES))]
    assert evaluation.context.evidence.market_data_source is (
        MarketDataSource.DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1
    )
    assert evaluation.methodology.book_fetch_mode == (
        "PUBLIC_WEBSOCKET_BOOK_TICKER_100MS_INCREMENTAL"
    )


def _ready_cache() -> tuple[BtcWebSocketCache, tuple[dict[str, object], ...], int]:
    boundary_ms = int(NOW.timestamp() * 1_000)
    cache = BtcWebSocketCache()
    cache.seed_index_history(_history(boundary_ms), received_timestamp_ms=boundary_ms)
    cache.configure_instruments(NAMES)
    cache.begin_connection()
    _populate_connection(cache, boundary_ms=boundary_ms, change_id_base=1_000)
    return cache, _metadata(), boundary_ms


def _populate_connection(
    cache: BtcWebSocketCache,
    *,
    boundary_ms: int,
    change_id_base: int,
) -> None:
    cache.accept_subscription(
        channel="deribit_price_index.btc_usd",
        data={"index_name": "btc_usd", "price": "100000", "timestamp": boundary_ms + 100},
        received_timestamp_ms=boundary_ms + 150,
    )
    for index, name in enumerate(NAMES):
        book_source_ms = boundary_ms + 200 + index * 50
        ticker_source_ms = boundary_ms + 220 + index * 50
        cache.accept_subscription(
            channel=f"book.{name}.100ms",
            data=_book_payload(
                name,
                change_id=change_id_base + index,
                source_timestamp_ms=book_source_ms,
            ),
            received_timestamp_ms=book_source_ms + 50,
        )
        cache.accept_subscription(
            channel=f"ticker.{name}.100ms",
            data=_ticker_payload(name, source_timestamp_ms=ticker_source_ms),
            received_timestamp_ms=ticker_source_ms + 50,
        )


def _cut(cache: BtcWebSocketCache, known_at_ms: int):
    return cache.cut(
        instrument_names=NAMES,
        known_at_ms=known_at_ms,
        maximum_age_ms=8_000,
        maximum_source_span_ms=6_000,
        maximum_receive_span_ms=8_000,
    )


def _book_change(
    cache: BtcWebSocketCache,
    name: str,
    *,
    change_id: int,
    previous_change_id: int,
    source_timestamp_ms: int,
    received_timestamp_ms: int,
    bid: str,
) -> None:
    cache.accept_subscription(
        channel=f"book.{name}.100ms",
        data=_book_payload(
            name,
            change_id=change_id,
            source_timestamp_ms=source_timestamp_ms,
            update_type="change",
            previous_change_id=previous_change_id,
            bid=bid,
        ),
        received_timestamp_ms=received_timestamp_ms,
    )


def _book_payload(
    name: str,
    *,
    change_id: int,
    source_timestamp_ms: int,
    update_type: str = "snapshot",
    previous_change_id: int | None = None,
    bid: str = "0.0010",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": update_type,
        "instrument_name": name,
        "timestamp": source_timestamp_ms,
        "change_id": change_id,
        "bids": [["change" if update_type == "change" else "new", bid, "1"]],
        "asks": [["new", "0.0015", "1"]] if update_type == "snapshot" else [],
    }
    if previous_change_id is not None:
        payload["prev_change_id"] = previous_change_id
    return payload


def _ticker_payload(name: str, *, source_timestamp_ms: int) -> dict[str, object]:
    delta = "-0.15" if name.endswith("P") else "0.15"
    return {
        "instrument_name": name,
        "timestamp": source_timestamp_ms,
        "underlying_price": "100000",
        "mark_iv": "55",
        "open_interest": "1000",
        "greeks": {"delta": delta, "gamma": "0.0001"},
    }


def _history(boundary_ms: int) -> tuple[tuple[int, Decimal], ...]:
    cadence_ms = 5 * 60_000
    start = boundary_ms - 2 * 24 * 60 * 60 * 1_000 - 1_000
    points: list[tuple[int, Decimal]] = []
    for index, timestamp_ms in enumerate(range(start, boundary_ms, cadence_ms)):
        factor = Decimal("1.001") if index % 2 else Decimal(1)
        points.append((timestamp_ms, Decimal("100000") * factor))
    return tuple(points)


def _metadata() -> tuple[dict[str, object], ...]:
    expiry_ms = int(current_deribit_session(NOW).end.timestamp() * 1_000)
    specifications = (
        (NAMES[0], 93_000, "put"),
        (NAMES[1], 95_000, "put"),
        (NAMES[2], 105_000, "call"),
        (NAMES[3], 107_000, "call"),
    )
    return tuple(
        {
            "instrument_name": name,
            "kind": "option",
            "is_active": True,
            "expiration_timestamp": expiry_ms,
            "base_currency": "BTC",
            "settlement_currency": "BTC",
            "price_index": "btc_usd",
            "contract_size": 1,
            "min_trade_amount": 0.1,
            "strike": strike,
            "option_type": option_type,
            "tick_size": 0.0001,
            "tick_size_steps": [{"above_price": 0.005, "tick_size": 0.0005}],
            "settlement_period": "day",
        }
        for name, strike, option_type in specifications
    )


def _subscription_frame(channel: str, data: object) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": channel, "data": data},
        }
    )


class _NoopConnection:
    def send(self, _message: str) -> None:
        pass

    def recv(self, timeout: float | None = None) -> str | bytes:
        del timeout
        raise TimeoutError

    def close(self) -> None:
        pass


class _IdleConnection:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.sent_two = threading.Event()
        self.closed = threading.Event()

    def send(self, message: str) -> None:
        self.sent.append(message)
        if len(self.sent) >= 2:
            self.sent_two.set()

    def recv(self, timeout: float | None = None) -> str | bytes:
        self.closed.wait(timeout=timeout)
        if self.closed.is_set():
            raise OSError("closed")
        raise TimeoutError

    def close(self) -> None:
        self.closed.set()


class _PreparedFeed:
    def __init__(self, cache: BtcWebSocketCache, *, known_at_ms: int) -> None:
        self.cache = cache
        self.known_at_ms = known_at_ms
        self.configure_calls: list[tuple[str, ...]] = []

    def configure_instruments(self, instrument_names: Sequence[str]) -> None:
        names = tuple(sorted(instrument_names))
        self.configure_calls.append(names)
        self.cache.configure_instruments(names)

    def wait_for_cut(
        self,
        *,
        instrument_names: Sequence[str],
        maximum_age_ms: int,
        maximum_source_span_ms: int,
        maximum_receive_span_ms: int,
    ):
        return self.cache.cut(
            instrument_names=instrument_names,
            known_at_ms=self.known_at_ms,
            maximum_age_ms=maximum_age_ms,
            maximum_source_span_ms=maximum_source_span_ms,
            maximum_receive_span_ms=maximum_receive_span_ms,
        )

    def close(self) -> None:
        pass

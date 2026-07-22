from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from market_tape import CanonicalEvent, CaptureManifest, EventKind, write_capture
from options_domain import enumerate_verticals
from radar_runtime.cli import main as runtime_main
from radar_runtime.deribit_public import (
    REFERENCE,
    RadarProjection,
    _canonical_instrument,
    _deribit_server_at_ms,
    _LiveSession,
    _rpc,
    _subscribe,
    _wait_result,
    capture_evidence_metadata,
    inspect_payload,
    project_events,
    projection_payload,
    replay_payload,
    select_btc_usdc_catalog,
)
from radar_runtime.fixture import build_fixture_events
from short_vol_radar import RadarAction, RadarPolicy, RadarProjector, evaluate_radar
from websockets.sync.connection import Connection


def _option(name: str, expiry: int) -> dict[str, object]:
    return {
        "instrument_name": name,
        "kind": "option",
        "base_currency": "BTC",
        "counter_currency": "USDC",
        "instrument_type": "linear",
        "is_active": True,
        "expiration_timestamp": expiry,
        "option_type": "call",
        "strike": 100_000,
    }


def _event_payload(event: CanonicalEvent) -> dict[str, object]:
    value: object = json.loads(event.raw_payload)
    assert isinstance(value, dict)
    return value


class _FakeConnection:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.sent: list[dict[str, object]] = []

    def send(self, raw: str) -> None:
        value: object = json.loads(raw)
        assert isinstance(value, dict)
        self.sent.append(value)

    def recv(self, *, timeout: float) -> str:
        assert timeout > 0
        return json.dumps(self.messages.pop(0))


def _append_event(
    events: tuple[CanonicalEvent, ...],
    event_kind: EventKind,
    payload: dict[str, object],
    *,
    instrument_name: str | None = None,
    channel: str = "control",
    at_ms: int | None = None,
    elapsed_ms: int | None = None,
    exchange_at_ms: int | None = None,
) -> tuple[CanonicalEvent, ...]:
    event_at_ms = events[-1].collector_received_at_ms + 1 if at_ms is None else at_ms
    event_elapsed_ms = events[-1].collector_elapsed_ms + 1 if elapsed_ms is None else elapsed_ms
    return (
        *events,
        CanonicalEvent(
            capture_seq=events[-1].capture_seq + 1,
            collector_received_at_ms=event_at_ms,
            collector_elapsed_ms=event_elapsed_ms,
            exchange_timestamp_ms=(event_at_ms if exchange_at_ms is None else exchange_at_ms),
            channel=channel,
            event_kind=event_kind,
            instrument_name=instrument_name,
            raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ),
    )


def _reconnected_fixture(fresh_platform_locked: bool | None) -> tuple[CanonicalEvent, ...]:
    baseline = build_fixture_events()
    market_start = next(
        index
        for index, event in enumerate(baseline)
        if event.event_kind is EventKind.TICKER and event.instrument_name == REFERENCE
    )
    events = baseline[:market_start]
    at_ms = baseline[market_start].collector_received_at_ms
    events = _append_event(
        events,
        EventKind.RECONNECT,
        {"reason": "test"},
        at_ms=at_ms,
    )
    events = _append_event(
        events,
        EventKind.SUBSCRIPTION_START,
        {"stream": "platform_state", "channel": "platform_state"},
        at_ms=at_ms,
    )
    if fresh_platform_locked is not None:
        status_capture_seq = events[-1].capture_seq + 1
        events = _append_event(
            events,
            EventKind.PLATFORM_STATE,
            {
                "state": "LOCKED" if fresh_platform_locked else "OPEN",
                "locked": fresh_platform_locked,
                "price_index": "btc_usdc",
                "status_capture_seq": status_capture_seq,
            },
            at_ms=at_ms,
            channel="public/status",
        )
    events = _append_event(
        events,
        EventKind.SUBSCRIPTION_START,
        {"stream": "reference_price"},
        at_ms=at_ms,
    )
    events = _append_event(
        events,
        EventKind.SUBSCRIPTION_START,
        {"stream": "reference_trade"},
        at_ms=at_ms,
    )
    suffix_origin_ms = baseline[market_start].collector_elapsed_ms
    suffix_start_ms = events[-1].collector_elapsed_ms + 1
    suffix = tuple(
        replace(
            event,
            capture_seq=len(events) + offset,
            collector_elapsed_ms=(suffix_start_ms + event.collector_elapsed_ms - suffix_origin_ms),
        )
        for offset, event in enumerate(baseline[market_start:], start=1)
    )
    return (*events, *suffix)


def _assert_live_replay_equal(events: tuple[CanonicalEvent, ...]) -> RadarProjection:
    projector = RadarProjector()
    ever_observed_complete_60m = False
    for event in events:
        frame = projector.ingest(event)
        window = frame.window(3_600) if frame is not None else None
        ever_observed_complete_60m = ever_observed_complete_60m or bool(
            window is not None
            and window.coverage.price_complete
            and window.coverage.trade_complete
            and window.path is not None
            and window.flow is not None
        )
    live_frame = projector.finalize()
    live_decision = evaluate_radar(live_frame)
    replay = project_events(events)

    assert live_frame.as_of_capture_seq == events[-1].capture_seq
    assert replay.final_event_capture_seq == events[-1].capture_seq
    assert replay.frame.as_of_capture_seq == events[-1].capture_seq
    assert replay.ever_observed_complete_60m is ever_observed_complete_60m
    assert all(
        set(window.source_capture_seqs).issubset(live_frame.source_capture_seqs)
        for window in live_frame.windows
    )
    assert live_frame.digest == replay.frame.digest
    assert live_decision.digest == replay.decision.digest
    return replay


def _compress_market_source_time(
    events: tuple[CanonicalEvent, ...],
) -> tuple[CanonicalEvent, ...]:
    origin_ms = min(
        event.exchange_timestamp_ms for event in events if event.exchange_timestamp_ms is not None
    )
    compressed: list[CanonicalEvent] = []
    for event in events:
        if event.event_kind is EventKind.TICKER:
            payload = _event_payload(event)
            source_at_ms = int(str(payload["timestamp"]))
            compressed_source_ms = origin_ms + (source_at_ms - origin_ms) // 1_000
            payload["timestamp"] = compressed_source_ms
            compressed.append(
                replace(
                    event,
                    exchange_timestamp_ms=compressed_source_ms,
                    raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
            continue
        if event.event_kind is EventKind.TRADE:
            payload = _event_payload(event)
            raw_trades = payload["trades"]
            assert isinstance(raw_trades, list)
            trades: list[dict[str, object]] = []
            for raw_trade in raw_trades:
                assert isinstance(raw_trade, dict)
                trade = dict(raw_trade)
                source_at_ms = int(str(trade["timestamp"]))
                trade["timestamp"] = origin_ms + (source_at_ms - origin_ms) // 1_000
                trades.append(trade)
            payload["trades"] = trades
            exchange_at_ms = max(int(str(trade["timestamp"])) for trade in trades)
            compressed.append(
                replace(
                    event,
                    exchange_timestamp_ms=exchange_at_ms,
                    raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
            continue
        compressed.append(event)
    return tuple(compressed)


def test_catalog_is_strictly_btc_usdc_zero_to_72_hours() -> None:
    as_of_ms = 1_000_000
    seventy_two_hours_ms = 72 * 3_600 * 1_000
    reference = {
        "instrument_name": REFERENCE,
        "base_currency": "BTC",
        "counter_currency": "USDC",
        "is_active": True,
    }
    selected = select_btc_usdc_catalog(
        (
            _option("BTC_USDC-IN", as_of_ms + seventy_two_hours_ms),
            _option("BTC_USDC-OUT", as_of_ms + seventy_two_hours_ms + 1),
            {
                **_option("BTC-INVERSE", as_of_ms + 1),
                "counter_currency": "USD",
            },
        ),
        (reference,),
        as_of_ms=as_of_ms,
    )

    assert tuple(item["instrument_name"] for item in selected) == (REFERENCE, "BTC_USDC-IN")


def test_catalog_clock_uses_deribit_response_timestamp_and_fails_closed() -> None:
    assert _deribit_server_at_ms({"usOut": 1_234_567}) == 1_234
    with pytest.raises(RuntimeError, match="usOut"):
        _deribit_server_at_ms({})
    with pytest.raises(RuntimeError, match="usOut"):
        _deribit_server_at_ms({"usOut": "1234567"})


def test_deribit_quantity_step_uses_min_trade_amount_not_lot_size() -> None:
    payload = _canonical_instrument(
        {
            **_option("BTC_USDC-OPTION", 2_000_000),
            "contract_size": 1,
            "min_trade_amount": 0.01,
            "lot_size": 1,
            "taker_commission": 0.0003,
        }
    )

    assert payload["min_trade_amount"] == 0.01
    assert payload["amount_step"] == 0.01
    assert payload["amount_step"] != 1
    assert "qty_tick_size" not in payload


@pytest.mark.parametrize(
    "field,value",
    (
        ("is_active", None),
        ("contract_size", None),
        ("min_trade_amount", None),
        ("min_trade_amount", 0),
        ("taker_commission", None),
        ("taker_commission", -0.1),
    ),
)
def test_deribit_instrument_metadata_fails_closed(field: str, value: object) -> None:
    row = {
        **_option("BTC_USDC-OPTION", 2_000_000),
        "contract_size": 1,
        "min_trade_amount": 0.01,
        "lot_size": 1,
        "taker_commission": 0.0003,
    }
    if value is None:
        del row[field]
    else:
        row[field] = value

    with pytest.raises(ValueError, match=field):
        _canonical_instrument(row)


@pytest.mark.parametrize("timestamp", (None, 0, -1, True))
def test_live_collector_rejects_invalid_ticker_timestamp(timestamp: object) -> None:
    session = _LiveSession()
    ticker: dict[str, object] = {
        "instrument_name": REFERENCE,
        "state": "open",
    }
    if timestamp is not None:
        ticker["timestamp"] = timestamp

    with pytest.raises(ValueError, match="positive timestamp"):
        session.record_ticker(
            f"ticker.{REFERENCE}.agg2",
            ticker,
            received_at_ms=2_000,
            elapsed_ms=0,
        )

    assert session.events == []


def test_live_collector_validates_entire_trade_batch_before_recording() -> None:
    session = _LiveSession()

    with pytest.raises(ValueError, match="positive timestamp"):
        session.record_trades(
            f"trades.{REFERENCE}.agg2",
            [
                {
                    "instrument_name": REFERENCE,
                    "trade_seq": 1,
                    "timestamp": 2_000,
                    "price": 100_000,
                    "amount": 1,
                    "direction": "buy",
                },
                {
                    "instrument_name": REFERENCE,
                    "trade_seq": 2,
                    "price": 100_001,
                    "amount": 1,
                    "direction": "sell",
                },
            ],
            received_at_ms=2_001,
            elapsed_ms=0,
        )

    assert session.events == []


def test_live_collector_rejects_ticker_channel_instrument_mismatch() -> None:
    session = _LiveSession()

    with pytest.raises(ValueError, match="channel and instrument_name"):
        session.record_ticker(
            "ticker.BTC_USDC-22JUL26-100000-C.agg2",
            {
                "instrument_name": REFERENCE,
                "timestamp": 1_700_000_000_000,
            },
            received_at_ms=1_700_000_000_001,
        )

    assert session.events == []


def test_trade_gap_and_heartbeat_are_canonical_events() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000
    session.record_heartbeat({"type": "heartbeat"}, received_at_ms=at_ms)
    session.record_trades(
        f"trades.{REFERENCE}.agg2",
        [
            {
                "instrument_name": REFERENCE,
                "trade_seq": 10,
                "timestamp": at_ms,
                "price": 100_000,
                "amount": 1,
                "direction": "buy",
            }
        ],
        received_at_ms=at_ms + 1,
    )
    session.record_trades(
        f"trades.{REFERENCE}.agg2",
        [
            {
                "instrument_name": REFERENCE,
                "trade_seq": 12,
                "timestamp": at_ms + 2,
                "price": 100_001,
                "amount": 1,
                "direction": "sell",
            }
        ],
        received_at_ms=at_ms + 1,
    )

    assert tuple(event.event_kind for event in session.events) == (
        EventKind.HEARTBEAT,
        EventKind.TRADE,
        EventKind.TRADE_GAP,
    )
    snapshot = session.projector.reducer.snapshot()
    assert len(snapshot.trade_gaps) == 1
    assert snapshot.trade_gaps[0].expected_sequence == 11
    assert snapshot.trade_gaps[0].observed_sequence == 12
    assert session.events[-1].exchange_timestamp_ms == at_ms + 2
    assert session.events[-1].collector_received_at_ms == at_ms + 1


@pytest.mark.parametrize("status", ({}, {"locked": "unknown"}))
def test_public_status_requires_recognized_lock_state(status: dict[str, object]) -> None:
    session = _LiveSession()

    with pytest.raises(ValueError, match="status"):
        session.record_platform(
            status,
            channel="public/status",
            received_at_ms=1_700_000_000_000,
        )

    assert session.events == []


@pytest.mark.parametrize(
    "status,expected",
    (
        ({"locked": "partial", "locked_indices": ["btc_usdc"]}, True),
        ({"locked": "partial", "locked_indices": ["eth_usdc"]}, False),
        ({"locked": "partial", "locked_currencies": ["USDC"]}, True),
    ),
)
def test_partial_public_status_is_scoped_or_conservatively_locked(
    status: dict[str, object],
    expected: bool,
) -> None:
    session = _LiveSession()
    session.record_subscription_start(received_at_ms=1_700_000_000_000)
    session.record_platform(
        status,
        channel="public/status",
        received_at_ms=1_700_000_000_000,
    )

    platform = session.projector.reducer.snapshot().platform_state
    assert platform is not None and platform.locked is expected


@pytest.mark.parametrize(
    "status",
    (
        {"locked": "partial"},
        {"locked": "partial", "locked_indices": []},
        {"locked": "partial", "locked_currencies": []},
    ),
)
def test_partial_public_status_rejects_empty_lock_scope_atomically(
    status: dict[str, object],
) -> None:
    session = _LiveSession()

    with pytest.raises(ValueError, match="lock scope"):
        session.record_platform(
            status,
            channel="public/status",
            received_at_ms=1_700_000_000_000,
        )

    assert session.events == []


def test_platform_maintenance_and_index_lock_are_combined_fail_closed() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000
    session.record_subscription_start(received_at_ms=at_ms)
    session.record_platform(
        {"locked": "false"},
        channel="public/status",
        received_at_ms=at_ms,
    )
    session.record_platform(
        {"maintenance": True},
        channel="platform_state",
        received_at_ms=at_ms + 1,
    )
    maintenance = session.projector.reducer.snapshot().platform_state
    assert maintenance is not None and maintenance.state == "LOCKED" and maintenance.locked

    session.record_platform(
        {"price_index": "btc_usdc", "locked": True},
        channel="platform_state",
        received_at_ms=at_ms + 2,
    )
    session.record_platform(
        {"maintenance": False},
        channel="platform_state",
        received_at_ms=at_ms + 3,
    )
    still_index_locked = session.projector.reducer.snapshot().platform_state
    assert (
        still_index_locked is not None
        and still_index_locked.state == "LOCKED"
        and still_index_locked.locked
    )

    session.record_platform(
        {"price_index": "btc_usdc", "locked": False},
        channel="platform_state",
        received_at_ms=at_ms + 4,
    )
    recovered = session.projector.reducer.snapshot().platform_state
    assert recovered is not None and recovered.state == "OPEN" and not recovered.locked

    replay = project_events(tuple(session.events))
    live = session.live_projection()
    assert replay.frame.digest == live.frame.digest
    assert replay.decision.digest == live.decision.digest


def test_platform_subscription_ack_precedes_fresh_status_and_allows_open() -> None:
    session = _LiveSession()
    fake = _FakeConnection(
        [
            {"jsonrpc": "2.0", "id": 1, "result": "ok"},
            {"jsonrpc": "2.0", "id": 2, "result": ["platform_state"]},
            {"jsonrpc": "2.0", "id": 3, "result": {"locked": "false"}},
        ]
    )
    connection = cast(Connection, fake)

    test_request_id = _subscribe(connection, session, ("platform_state",))
    platform_subscription = next(
        event
        for event in session.events
        if event.event_kind is EventKind.SUBSCRIPTION_START
        and _event_payload(event).get("stream") == "platform_state"
    )
    _rpc(connection, 3, "public/status", {})
    status, _, clock = _wait_result(
        connection,
        session,
        3,
        test_request_id=test_request_id,
    )
    session.record_platform(
        cast(dict[str, object], status),
        channel="public/status",
        received_at_ms=clock.received_at_ms,
        elapsed_ms=clock.elapsed_ms,
    )

    assert [item["method"] for item in fake.sent] == [
        "public/set_heartbeat",
        "public/subscribe",
        "public/status",
    ]
    state = session.projector.reducer.snapshot().platform_state
    assert state is not None and state.state == "OPEN" and state.locked is False
    assert platform_subscription.capture_seq in state.source_capture_seqs
    assert _event_payload(session.events[-1])["maintenance"] is None


def test_positive_platform_notification_interleaved_before_status_stays_locked() -> None:
    session = _LiveSession()
    fake = _FakeConnection(
        [
            {"jsonrpc": "2.0", "id": 1, "result": "ok"},
            {
                "jsonrpc": "2.0",
                "method": "subscription",
                "params": {
                    "channel": "platform_state",
                    "data": {"maintenance": True},
                },
            },
            {"jsonrpc": "2.0", "id": 2, "result": ["platform_state"]},
            {"jsonrpc": "2.0", "id": 3, "result": {"locked": "false"}},
        ]
    )
    connection = cast(Connection, fake)

    test_request_id = _subscribe(connection, session, ("platform_state",))
    maintenance_seq = next(
        event.capture_seq
        for event in session.events
        if event.event_kind is EventKind.PLATFORM_STATE
    )
    _rpc(connection, 3, "public/status", {})
    status, _, clock = _wait_result(
        connection,
        session,
        3,
        test_request_id=test_request_id,
    )
    session.record_platform(
        cast(dict[str, object], status),
        channel="public/status",
        received_at_ms=clock.received_at_ms,
        elapsed_ms=clock.elapsed_ms,
    )

    state = session.projector.reducer.snapshot().platform_state
    assert state is not None and state.state == "LOCKED" and state.locked is True
    assert maintenance_seq in state.source_capture_seqs
    replay = project_events(tuple(session.events))
    live = session.live_projection()
    assert replay.frame.digest == live.frame.digest
    assert replay.decision.digest == live.decision.digest


def test_reconnect_requires_new_platform_subscription_before_unlocked_status_can_open() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000
    session.record_subscription_start(received_at_ms=at_ms)
    session.record_platform(
        {"locked": "false"},
        channel="public/status",
        received_at_ms=at_ms + 1,
    )
    session.record_reconnect("test", received_at_ms=at_ms + 2)
    session.record_platform(
        {"locked": "false"},
        channel="public/status",
        received_at_ms=at_ms + 3,
    )

    state = session.projector.reducer.snapshot().platform_state
    assert state is not None and state.state == "UNKNOWN" and state.locked is None
    projection = session.live_projection()
    assert projection.frame.platform_locked is None
    assert "PLATFORM_STATE_UNKNOWN" in projection.frame.completeness_reasons


def test_status_before_platform_subscription_cannot_become_open_later() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000
    session.record_platform(
        {"locked": "false"},
        channel="public/status",
        received_at_ms=at_ms,
    )
    session.record_subscription_start(received_at_ms=at_ms + 1)
    session.record_platform(
        {"maintenance": False},
        channel="platform_state",
        received_at_ms=at_ms + 2,
    )

    state = session.projector.reducer.snapshot().platform_state
    assert state is not None and state.state == "UNKNOWN" and state.locked is None
    replay = project_events(tuple(session.events))
    live = session.live_projection()
    assert "PLATFORM_STATE_UNKNOWN" in live.frame.completeness_reasons
    assert live.frame.platform_state == "UNKNOWN"
    assert live.frame.platform_locked is None
    assert replay.frame.digest == live.frame.digest
    assert replay.decision.digest == live.decision.digest


def test_new_platform_subscription_invalidates_prior_open_until_fresh_status() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000
    session.record_subscription_start(received_at_ms=at_ms)
    session.record_platform(
        {"locked": "false"},
        channel="public/status",
        received_at_ms=at_ms + 1,
    )
    session.record_subscription_start(received_at_ms=at_ms + 2)

    projection = session.live_projection()

    assert projection.frame.platform_state == "UNKNOWN"
    assert projection.frame.platform_locked is None
    assert "PLATFORM_STATE_UNKNOWN" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_open_without_fresh_status_marker_is_effectively_unknown() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.SUBSCRIPTION_START,
        {"stream": "platform_state", "channel": "platform_state"},
    )
    events = _append_event(
        events,
        EventKind.PLATFORM_STATE,
        {"state": "OPEN", "locked": False, "price_index": "btc_usdc"},
        channel="public/status",
    )

    projection = _assert_live_replay_equal(events)

    assert projection.frame.platform_state == "UNKNOWN"
    assert projection.frame.platform_locked is None
    assert "PLATFORM_STATE_UNKNOWN" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_duplicate_old_trade_batch_does_not_regress_sequence_or_create_false_gap() -> None:
    session = _LiveSession()
    at_ms = 1_700_000_000_000

    def trade(sequence: int, timestamp: int) -> dict[str, object]:
        return {
            "instrument_name": REFERENCE,
            "trade_seq": sequence,
            "timestamp": timestamp,
            "price": 100_000,
            "amount": 1,
            "direction": "buy",
        }

    session.record_trades(
        f"trades.{REFERENCE}.agg2",
        [trade(10, at_ms)],
        received_at_ms=at_ms,
    )
    session.record_trades(
        f"trades.{REFERENCE}.agg2",
        [trade(9, at_ms - 1)],
        received_at_ms=at_ms + 1,
    )
    session.record_trades(
        f"trades.{REFERENCE}.agg2",
        [trade(11, at_ms + 2)],
        received_at_ms=at_ms + 2,
    )

    assert session.last_trade_seq == 11
    assert all(event.event_kind is EventKind.TRADE for event in session.events)
    assert session.projector.reducer.snapshot().trade_gaps == ()


def test_zero_candidate_live_and_independent_replay_digests_match() -> None:
    reference_only = tuple(
        replace(event, capture_seq=sequence)
        for sequence, event in enumerate(
            (
                event
                for event in build_fixture_events()
                if event.instrument_name in {None, REFERENCE}
            ),
            start=1,
        )
    )

    live = _assert_live_replay_equal(reference_only)
    replay = project_events(reference_only)

    assert live.current_complete_60m
    assert live.decision.action is RadarAction.ABSTAIN
    assert live.decision.selected_candidate_id is None
    payload = projection_payload(live)
    assert payload["evaluated_structure_id"] is None
    assert payload["research_candidate_emitted"] is False
    assert payload["research_candidate_count"] == 0
    assert live.frame.digest == replay.frame.digest
    assert live.decision.digest == replay.decision.digest


def test_projection_payload_distinguishes_watch_from_emitted_candidate() -> None:
    candidate = project_events(build_fixture_events())
    candidate_payload = projection_payload(candidate)

    assert candidate.decision.action is RadarAction.RESEARCH_CANDIDATE
    assert candidate_payload["evaluated_structure_id"] == (candidate.decision.selected_candidate_id)
    assert candidate_payload["research_candidate_emitted"] is True
    assert candidate_payload["research_candidate_count"] == 1

    strict_policy = replace(
        RadarPolicy(),
        minimum_credit_to_friction=(RadarPolicy().minimum_credit_to_friction * 1_000),
    )
    watch_decision = evaluate_radar(candidate.frame, policy=strict_policy)
    watch = replace(candidate, decision=watch_decision)
    watch_payload = projection_payload(watch)

    assert watch_decision.action is RadarAction.WATCH
    assert watch_payload["evaluated_structure_id"] == watch_decision.selected_candidate_id
    assert watch_payload["research_candidate_emitted"] is False
    assert watch_payload["research_candidate_count"] == 0
    assert "candidate_id" not in watch_payload
    assert "candidate_count" not in watch_payload


def test_full_elapsed_with_compressed_market_time_abstains_live_and_replay() -> None:
    events = _compress_market_source_time(build_fixture_events())

    projection = _assert_live_replay_equal(events)
    window = projection.frame.window(3_600)
    evidence = projection_payload(projection)

    assert window is not None
    assert window.coverage.price_subscription_elapsed_seconds == 3_600
    assert window.coverage.price_market_lookback_seconds < 3_600
    assert not window.coverage.price_complete
    assert window.path is None
    assert "PRICE_MARKET_LOOKBACK_INCOMPLETE" in window.coverage.incomplete_reasons
    assert not projection.current_complete_60m
    assert projection.decision.action is RadarAction.ABSTAIN
    assert evidence["price_subscription_elapsed_seconds"] == 3_600
    market_lookback_seconds = evidence["price_market_lookback_seconds"]
    assert isinstance(market_lookback_seconds, int)
    assert market_lookback_seconds < 3_600


def test_frozen_market_watermark_abstains_live_and_replay() -> None:
    events = build_fixture_events()
    payload = _event_payload(events[-1])
    source_at_ms = events[-1].exchange_timestamp_ms
    assert source_at_ms is not None
    events = _append_event(
        events,
        EventKind.TICKER,
        payload,
        instrument_name=REFERENCE,
        channel=f"ticker.{REFERENCE}.100ms",
        elapsed_ms=events[-1].collector_elapsed_ms + 3_000,
        exchange_at_ms=source_at_ms,
    )

    projection = _assert_live_replay_equal(events)
    window = projection.frame.window(3_600)

    assert window is not None
    assert window.coverage.price_market_lookback_seconds == 3_600
    assert window.coverage.price_watermark_progress_age_ms == 3_000
    assert not window.coverage.price_complete
    assert window.path is None
    assert "PRICE_MARKET_WATERMARK_STALE" in window.coverage.incomplete_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_complete_60m_then_final_trade_gap_uses_gap_frame() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.TRADE_GAP,
        {"trades": []},
        instrument_name=REFERENCE,
        channel=f"trades.{REFERENCE}.agg2",
    )

    projection = _assert_live_replay_equal(events)

    assert projection.ever_observed_complete_60m
    assert not projection.current_complete_60m
    assert projection.decision.action is RadarAction.ABSTAIN
    window = projection.frame.window(3_600)
    assert window is not None and window.coverage.gap_contaminated


def test_complete_60m_then_reconnect_and_one_ticker_is_not_warm() -> None:
    events = _append_event(build_fixture_events(), EventKind.RECONNECT, {"reason": "test"})
    reconnect_seq = events[-1].capture_seq
    events = _append_event(
        events,
        EventKind.SUBSCRIPTION_START,
        {"stream": "reference_price"},
    )
    price_subscription_seq = events[-1].capture_seq
    events = _append_event(
        events,
        EventKind.SUBSCRIPTION_START,
        {"stream": "reference_trade"},
    )
    trade_subscription_seq = events[-1].capture_seq
    ticker = _event_payload(build_fixture_events()[-1])
    ticker["timestamp"] = events[-1].collector_received_at_ms + 1
    events = _append_event(
        events,
        EventKind.TICKER,
        ticker,
        instrument_name=REFERENCE,
        channel=f"ticker.{REFERENCE}.agg2",
    )

    projection = _assert_live_replay_equal(events)

    assert projection.ever_observed_complete_60m
    assert not projection.current_complete_60m
    assert projection.decision.action is RadarAction.ABSTAIN
    window = projection.frame.window(3_600)
    assert window is not None and window.coverage.reconnect_contaminated
    assert {reconnect_seq, price_subscription_seq, trade_subscription_seq}.issubset(
        window.source_capture_seqs
    )
    assert set(window.source_capture_seqs).issubset(projection.frame.source_capture_seqs)


def test_reconnect_full_warmup_without_fresh_platform_status_abstains() -> None:
    events = _reconnected_fixture(None)
    projection = _assert_live_replay_equal(events)
    reconnect_seq = next(
        event.capture_seq for event in events if event.event_kind is EventKind.RECONNECT
    )

    assert projection.current_complete_60m
    assert projection.frame.platform_state == "UNKNOWN"
    assert projection.frame.platform_locked is None
    assert "PLATFORM_STATE_UNKNOWN" in projection.frame.completeness_reasons
    assert reconnect_seq in projection.frame.source_capture_seqs
    assert projection.decision.action is RadarAction.ABSTAIN


def test_reconnect_fresh_open_platform_status_recovers() -> None:
    events = _reconnected_fixture(False)
    projection = _assert_live_replay_equal(events)
    reconnect_seq = next(
        event.capture_seq for event in events if event.event_kind is EventKind.RECONNECT
    )
    platform_seq = next(
        event.capture_seq
        for event in events
        if event.capture_seq > reconnect_seq and event.event_kind is EventKind.PLATFORM_STATE
    )

    assert projection.current_complete_60m
    assert projection.frame.platform_state == "OPEN"
    assert not projection.frame.platform_locked
    assert "PLATFORM_STATE_UNKNOWN" not in projection.frame.completeness_reasons
    assert projection.frame.complete
    assert platform_seq in projection.frame.source_capture_seqs
    assert projection.decision.action is RadarAction.RESEARCH_CANDIDATE


def test_reconnect_fresh_locked_platform_status_abstains() -> None:
    projection = _assert_live_replay_equal(_reconnected_fixture(True))

    assert projection.current_complete_60m
    assert projection.frame.platform_state == "LOCKED"
    assert projection.frame.platform_locked
    assert "PLATFORM_LOCKED" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_complete_60m_then_final_platform_lock_is_current() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.PLATFORM_STATE,
        {"state": "LOCKED", "locked": True, "price_index": "btc_usdc"},
    )

    projection = _assert_live_replay_equal(events)

    assert projection.ever_observed_complete_60m
    assert projection.current_complete_60m
    assert projection.frame.platform_locked
    assert "PLATFORM_LOCKED" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_inconsistent_platform_state_is_rejected() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.PLATFORM_STATE,
        {"state": "LOCKED", "locked": False, "price_index": "btc_usdc"},
    )

    with pytest.raises(ValueError, match="inconsistent"):
        project_events(events)


def test_trade_gap_then_heartbeat_preserves_gap_lineage() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.TRADE_GAP,
        {"trades": []},
        instrument_name=REFERENCE,
        channel=f"trades.{REFERENCE}.agg2",
    )
    gap_seq = events[-1].capture_seq
    events = _append_event(
        events,
        EventKind.HEARTBEAT,
        {"type": "heartbeat"},
        at_ms=events[-1].collector_received_at_ms - 2_000,
    )

    projection = _assert_live_replay_equal(events)

    window = projection.frame.window(3_600)
    assert window is not None and window.coverage.gap_contaminated
    assert gap_seq in window.source_capture_seqs
    assert gap_seq in projection.frame.source_capture_seqs
    assert projection.decision.action is RadarAction.ABSTAIN


def test_platform_lock_then_heartbeat_preserves_platform_lineage() -> None:
    events = _append_event(
        build_fixture_events(),
        EventKind.PLATFORM_STATE,
        {"state": "LOCKED", "locked": True, "price_index": "btc_usdc"},
    )
    platform_seq = events[-1].capture_seq
    events = _append_event(
        events,
        EventKind.HEARTBEAT,
        {"type": "heartbeat"},
        at_ms=events[-1].collector_received_at_ms - 2_000,
    )

    projection = _assert_live_replay_equal(events)

    assert projection.frame.platform_locked
    assert platform_seq in projection.frame.source_capture_seqs
    assert projection.decision.action is RadarAction.ABSTAIN


@pytest.mark.parametrize("state", ("locked", "halted", "settlement"))
def test_reference_not_open_abstains(state: str) -> None:
    events = build_fixture_events()
    payload = _event_payload(events[-1])
    payload["state"] = state
    events = (*events[:-1], replace(events[-1], raw_payload=json.dumps(payload, sort_keys=True)))

    projection = _assert_live_replay_equal(events)

    assert "REFERENCE_NOT_OPEN" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_non_open_option_leg_cannot_form_an_executable_vertical() -> None:
    events = build_fixture_events()
    baseline = project_events(events)
    assert baseline.decision.action is RadarAction.RESEARCH_CANDIDATE
    assert baseline.decision.assessment is not None
    candidate = baseline.decision.assessment.candidate
    policy = RadarPolicy()

    for leg in (candidate.short_leg, candidate.long_leg):
        original = next(
            event
            for event in reversed(events)
            if event.event_kind is EventKind.TICKER and event.instrument_name == leg.instrument_name
        )
        payload = _event_payload(original)
        payload["state"] = "locked"
        payload["timestamp"] = events[-1].collector_received_at_ms + 1
        blocked_events = _append_event(
            events,
            EventKind.TICKER,
            payload,
            instrument_name=leg.instrument_name,
            channel=f"ticker.{leg.instrument_name}.agg2",
        )

        projection = _assert_live_replay_equal(blocked_events)
        assert leg.instrument_name not in {
            quote.instrument_name for quote in projection.frame.option_quotes
        }
        assert projection.frame.reference_price is not None
        assert projection.frame.index_price is not None
        verticals = enumerate_verticals(
            frame_capture_seq=projection.frame.as_of_capture_seq,
            reference_price=projection.frame.reference_price,
            index_price=projection.frame.index_price,
            option_quotes=projection.frame.option_quotes,
            combo_quotes=projection.frame.combo_quotes,
            quantity=policy.quantity,
            minimum_tte_seconds=policy.minimum_tte_seconds,
            maximum_tte_seconds=policy.maximum_tte_seconds,
        )
        assert all(
            leg.instrument_name
            not in {vertical.short_leg.instrument_name, vertical.long_leg.instrument_name}
            for vertical in verticals
        )


def test_capture_sequence_keeps_known_facts_when_collector_wall_clock_rolls_back() -> None:
    events = build_fixture_events()
    baseline = project_events(events)
    current_at_ms = events[-1].collector_received_at_ms - 2_000
    latest_reference_seq = events[-1].capture_seq
    latest_option_seqs = {
        event.capture_seq
        for event in events
        if event.event_kind is EventKind.TICKER and event.instrument_name != REFERENCE
    }
    events = (
        *events,
        CanonicalEvent(
            capture_seq=events[-1].capture_seq + 1,
            collector_received_at_ms=current_at_ms,
            collector_elapsed_ms=events[-1].collector_elapsed_ms + 1,
            exchange_timestamp_ms=None,
            channel="heartbeat",
            event_kind=EventKind.HEARTBEAT,
            instrument_name=None,
            raw_payload='{"type":"heartbeat"}',
        ),
    )

    projection = _assert_live_replay_equal(events)

    assert int(projection.frame.collector_as_of.timestamp() * 1_000) == current_at_ms
    assert projection.frame.reference_price == baseline.frame.reference_price
    assert projection.frame.index_price == baseline.frame.index_price
    assert projection.frame.reference_dynamics == baseline.frame.reference_dynamics
    assert latest_reference_seq in projection.frame.source_capture_seqs
    assert latest_option_seqs.issubset(projection.frame.source_capture_seqs)
    assert projection.current_complete_60m
    assert projection.decision.action is RadarAction.RESEARCH_CANDIDATE


def test_exchange_clock_ahead_of_collector_preserves_complete_live_replay() -> None:
    baseline = build_fixture_events()
    baseline_projection = project_events(baseline)
    elapsed_origin_ms = baseline[0].collector_elapsed_ms
    events = tuple(
        replace(
            event,
            collector_received_at_ms=event.collector_received_at_ms - 2_000,
            collector_elapsed_ms=event.collector_elapsed_ms - elapsed_origin_ms,
        )
        for event in baseline
    )

    projection = _assert_live_replay_equal(events)

    assert all(
        event.exchange_timestamp_ms is None
        or event.exchange_timestamp_ms - event.collector_received_at_ms == 2_000
        for event in events
    )
    assert projection.current_complete_60m
    assert projection.decision.action is RadarAction.RESEARCH_CANDIDATE
    assert projection.frame.window(3_600) == baseline_projection.frame.window(3_600)
    assert tuple(quote.tte_seconds for quote in projection.frame.option_quotes) == tuple(
        quote.tte_seconds for quote in baseline_projection.frame.option_quotes
    )
    assert int(projection.frame.collector_as_of.timestamp() * 1_000) == (
        int(baseline_projection.frame.collector_as_of.timestamp() * 1_000) - 2_000
    )


def test_option_source_after_reference_market_watermark_is_excluded() -> None:
    events = list(build_fixture_events())
    reference_market_ms = events[-1].exchange_timestamp_ms
    assert reference_market_ms is not None
    target_index = next(
        index
        for index, event in enumerate(events)
        if event.event_kind is EventKind.TICKER and event.instrument_name != REFERENCE
    )
    target = events[target_index]
    target_name = target.instrument_name
    payload = _event_payload(target)
    payload["timestamp"] = reference_market_ms + 1
    events[target_index] = replace(
        target,
        exchange_timestamp_ms=reference_market_ms + 1,
        raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )

    projection = _assert_live_replay_equal(tuple(events))

    assert target_name not in {quote.instrument_name for quote in projection.frame.option_quotes}
    assert target.capture_seq not in projection.frame.source_capture_seqs


def test_regressing_reference_ticker_does_not_change_fact_or_window() -> None:
    events = build_fixture_events()
    baseline = project_events(events)
    latest_reference = events[-1]
    payload = _event_payload(latest_reference)
    assert latest_reference.exchange_timestamp_ms is not None
    payload["timestamp"] = latest_reference.exchange_timestamp_ms - 1
    payload["last_price"] = "1"
    events = _append_event(
        events,
        EventKind.TICKER,
        payload,
        instrument_name=REFERENCE,
        channel=f"ticker.{REFERENCE}.agg2",
        exchange_at_ms=latest_reference.exchange_timestamp_ms - 1,
    )
    stale_seq = events[-1].capture_seq

    projection = _assert_live_replay_equal(events)

    assert projection.frame.as_of_capture_seq == stale_seq
    assert projection.frame.reference_source_capture_seq == latest_reference.capture_seq
    assert projection.frame.market_as_of_capture_seq == latest_reference.capture_seq
    assert projection.frame.reference_price == baseline.frame.reference_price
    current_window = projection.frame.window(3_600)
    baseline_window = baseline.frame.window(3_600)
    assert current_window is not None and baseline_window is not None
    assert current_window.path == baseline_window.path
    assert current_window.coverage.price_market_anchor_at == (
        baseline_window.coverage.price_market_anchor_at
    )
    assert current_window.coverage.price_market_endpoint_at == (
        baseline_window.coverage.price_market_endpoint_at
    )
    assert current_window.coverage.price_watermark_progress_age_ms == 1
    assert current_window.coverage.price_complete
    assert stale_seq not in {
        seq for window in projection.frame.windows for seq in window.source_capture_seqs
    }


def test_delayed_old_option_is_not_fresh_even_when_arrival_is_fresh() -> None:
    events = list(build_fixture_events())
    market_now_ms = events[-1].exchange_timestamp_ms
    assert market_now_ms is not None
    target_index = next(
        index
        for index in range(len(events) - 1, -1, -1)
        if events[index].event_kind is EventKind.TICKER
        and events[index].instrument_name != REFERENCE
    )
    target = events[target_index]
    payload = _event_payload(target)
    payload["timestamp"] = market_now_ms - 6_000
    events[target_index] = replace(
        target,
        exchange_timestamp_ms=market_now_ms - 6_000,
        raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )

    projection = _assert_live_replay_equal(tuple(events))
    quote = next(
        item
        for item in projection.frame.option_quotes
        if item.instrument_name == target.instrument_name
    )

    assert events[-1].collector_elapsed_ms - target.collector_elapsed_ms == 0
    assert quote.quote_age_ms == 6_000
    assert not quote.fresh


def test_delayed_old_reference_is_stale_against_trade_watermark() -> None:
    events = build_fixture_events()
    last_trade_event = next(
        event for event in reversed(events) if event.event_kind is EventKind.TRADE
    )
    last_trade_payload = _event_payload(last_trade_event)
    last_trade = last_trade_payload["trades"]
    assert isinstance(last_trade, list)
    trade = dict(last_trade[0])
    market_now_ms = events[-1].exchange_timestamp_ms
    assert market_now_ms is not None
    trade["trade_seq"] = int(str(trade["trade_seq"])) + 1
    trade["timestamp"] = market_now_ms + 3_000
    events = _append_event(
        events,
        EventKind.TRADE,
        {"trades": [trade]},
        instrument_name=REFERENCE,
        channel=f"trades.{REFERENCE}.agg2",
        exchange_at_ms=market_now_ms + 3_000,
    )

    projection = _assert_live_replay_equal(events)

    assert projection.frame.market_as_of_capture_seq == events[-1].capture_seq
    assert projection.frame.reference_source_capture_seq == events[-2].capture_seq
    assert "REFERENCE_STALE" in projection.frame.completeness_reasons
    assert projection.decision.action is RadarAction.ABSTAIN


def test_frame_provenance_includes_catalog_tickers_prior_reference_and_watermark() -> None:
    events = build_fixture_events()
    prior_reference_seq = events[-1].capture_seq
    payload = _event_payload(events[-1])
    assert events[-1].exchange_timestamp_ms is not None
    payload["timestamp"] = events[-1].exchange_timestamp_ms + 1
    events = _append_event(
        events,
        EventKind.TICKER,
        payload,
        instrument_name=REFERENCE,
        channel=f"ticker.{REFERENCE}.agg2",
        exchange_at_ms=events[-1].exchange_timestamp_ms + 1,
    )

    projection = _assert_live_replay_equal(events)
    frame = projection.frame

    assert frame.reference_source_capture_seq == events[-1].capture_seq
    assert frame.market_as_of_capture_seq == events[-1].capture_seq
    assert frame.reference_dynamics.prior_reference_capture_seq == prior_reference_seq
    assert prior_reference_seq in frame.source_capture_seqs
    for quote in frame.option_quotes:
        assert set(quote.source_capture_seqs).issubset(frame.source_capture_seqs)
        assert set(quote.source_capture_seqs).issubset(frame.surface.source_capture_seqs)


def test_inspect_reports_clock_skew_without_cross_clock_violation(
    tmp_path: Path,
) -> None:
    baseline = build_fixture_events()
    elapsed_origin_ms = baseline[0].collector_elapsed_ms
    events = tuple(
        replace(
            event,
            collector_received_at_ms=event.collector_received_at_ms - 2_000,
            collector_elapsed_ms=event.collector_elapsed_ms - elapsed_origin_ms,
        )
        for event in baseline
    )
    events = _append_event(
        events,
        EventKind.HEARTBEAT,
        {"type": "heartbeat"},
        at_ms=events[-1].collector_received_at_ms - 3_000,
    )
    manifest = write_capture(tmp_path / "capture", events, complete=True)

    payload = inspect_payload(manifest, events)

    assert payload["timestamp_contract"] == "CAPTURE_SEQUENCE_WITH_PERSISTED_ELAPSED"
    assert payload["collector_elapsed_source"] == "PERSISTED_MONOTONIC"
    assert payload["collector_elapsed_order"] == "VERIFIED"
    assert payload["collector_elapsed_regressions"] == 0
    assert payload["collector_wall_regressions"] == 1
    assert payload["exchange_ahead_records"] == len(baseline)
    assert payload["book_stream_observed"] is False
    assert payload["book_gap_records"] is None
    assert "source_time_violations" not in payload
    assert payload["current_frame_is_final_event"] is True


def test_inspect_counts_book_gaps_only_when_book_facts_are_observed(
    tmp_path: Path,
) -> None:
    events = build_fixture_events()
    option = next(
        event.instrument_name
        for event in events
        if event.event_kind is EventKind.INSTRUMENT
        and event.instrument_name is not None
        and event.instrument_name != REFERENCE
    )
    events = _append_event(
        events,
        EventKind.BOOK_GAP,
        {},
        instrument_name=option,
        channel=f"book.{option}.raw",
    )
    manifest = write_capture(tmp_path / "capture", events, complete=True)

    payload = inspect_payload(manifest, events)

    assert payload["book_stream_observed"] is True
    assert payload["book_gap_records"] == 1


def _live_capture_payload(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
) -> dict[str, object]:
    return {
        **inspect_payload(manifest, events),
        "receipt_type": "DERIBIT_PUBLIC_RADAR_CAPTURE",
        "environment": "production_public",
        "duration_seconds": 1,
        "evidence_class": "BOUNDED_PRODUCTION_PUBLIC_CAPTURE",
    }


def test_replay_output_uses_semantic_identities_and_exact_live_capture_binding(
    tmp_path: Path,
) -> None:
    events = build_fixture_events()
    capture_root = tmp_path / "capture"
    manifest = write_capture(capture_root, events, complete=True)
    live = _live_capture_payload(manifest, events)

    plain_replay = replay_payload(manifest, events)
    replay = replay_payload(manifest, events, live=live)

    assert plain_replay["evidence_class"] == "CANONICAL_CAPTURE_REPLAY"
    assert plain_replay["platform_state_contract"] == "CONNECTION_GENERATION_SCOPED_STATUS"
    assert replay["capture_format"] == "CANONICAL_MARKET_TAPE_WITH_PERSISTED_ELAPSED"
    assert replay["timestamp_contract"] == "CAPTURE_SEQUENCE_WITH_PERSISTED_ELAPSED"
    assert replay["collector_elapsed_source"] == "PERSISTED_MONOTONIC"
    assert replay["capture_digest"] == manifest.content_sha256
    assert replay["live_binding_verified"] is True
    assert replay["live_frame_digest_match"] is True
    assert replay["live_decision_digest_match"] is True
    assert replay["evidence_class"] == "BOUNDED_PRODUCTION_PUBLIC_LIVE_REPLAY"

    live_path = tmp_path / "live.json"
    live_path.write_text(json.dumps(live), encoding="utf-8")
    replay_root = tmp_path / "replay"
    assert (
        runtime_main(
            [
                "replay",
                str(capture_root),
                "--output",
                str(replay_root),
                "--live",
                str(live_path),
            ]
        )
        == 0
    )
    saved: object = json.loads((replay_root / "replay.json").read_text(encoding="utf-8"))
    assert isinstance(saved, dict)
    assert saved["evidence_class"] == "BOUNDED_PRODUCTION_PUBLIC_LIVE_REPLAY"


@pytest.mark.parametrize(
    "field,wrong_value",
    (
        ("capture_format", "REMOVED_FORMAT"),
        ("capture_complete", False),
        ("capture_digest", "wrong"),
        ("receipt_type", "wrong"),
        ("environment", "wrong"),
        ("evidence_class", "CANONICAL_CAPTURE_REPLAY"),
        ("duration_seconds", 0),
        ("duration_seconds", -1),
        ("duration_seconds", True),
        ("duration_seconds", "1"),
        ("records", -1),
        ("final_event_capture_seq", -1),
        ("frame_capture_seq", -1),
        ("current_frame_is_final_event", False),
        ("timestamp_contract", "wrong"),
        ("collector_elapsed_source", "wrong"),
        ("platform_state_contract", "wrong"),
    ),
)
def test_replay_rejects_live_result_from_a_different_capture(
    tmp_path: Path,
    field: str,
    wrong_value: object,
) -> None:
    events = build_fixture_events()
    manifest = write_capture(tmp_path / "capture", events, complete=True)
    live = _live_capture_payload(manifest, events)
    live[field] = wrong_value

    with pytest.raises(ValueError, match="capture binding"):
        replay_payload(manifest, events, live=live)


@pytest.mark.parametrize(
    "field",
    (
        "capture_complete",
        "current_frame_is_final_event",
        "records",
        "decision_action",
        "decision_reason",
        "evaluated_structure_id",
    ),
)
def test_replay_live_binding_requires_exact_types_and_projection_fields(
    tmp_path: Path,
    field: str,
) -> None:
    events = build_fixture_events()
    manifest = write_capture(tmp_path / "capture", events, complete=True)
    live = _live_capture_payload(manifest, events)
    if field in {"capture_complete", "current_frame_is_final_event"}:
        live[field] = 1
    elif field == "records":
        live[field] = float(manifest.record_count)
    elif field == "decision_action":
        live[field] = "ABSTAIN" if live[field] != "ABSTAIN" else "WATCH"
    elif field == "decision_reason":
        live[field] = f"{live[field]}_TAMPERED"
    else:
        live[field] = "TAMPERED_STRUCTURE"

    with pytest.raises(ValueError, match="capture binding"):
        replay_payload(manifest, events, live=live)


def test_inspect_and_replay_reject_manifest_from_different_events(
    tmp_path: Path,
) -> None:
    events = build_fixture_events()
    manifest = write_capture(tmp_path / "capture", events, complete=True)
    tampered_events = (
        *events[:-1],
        replace(events[-1], raw_payload='{"tampered":true}'),
    )

    with pytest.raises(ValueError, match="canonical events digest"):
        inspect_payload(manifest, tampered_events)
    with pytest.raises(ValueError, match="canonical events digest"):
        replay_payload(manifest, tampered_events)


def test_replay_rejects_inspect_payload_as_live_evidence(tmp_path: Path) -> None:
    events = build_fixture_events()
    manifest = write_capture(tmp_path / "capture", events, complete=True)

    with pytest.raises(ValueError, match="capture binding"):
        replay_payload(manifest, events, live=inspect_payload(manifest, events))


def test_capture_without_platform_generation_marker_is_regression_replay_only(
    tmp_path: Path,
) -> None:
    events = tuple(
        replace(
            event,
            raw_payload=json.dumps(
                {"stream": "unscoped_platform_state"},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if event.event_kind is EventKind.SUBSCRIPTION_START
        and _event_payload(event).get("stream") == "platform_state"
        else event
        for event in build_fixture_events()
    )
    manifest = write_capture(tmp_path / "capture", events, complete=True)

    replay = replay_payload(manifest, events)

    assert replay["platform_state_contract"] == "PLATFORM_STATUS_BARRIER_UNPROVEN"
    assert replay["evidence_class"] == "PLATFORM_STATUS_BARRIER_REPLAY_ONLY"
    assert replay["live_comparison_eligible"] is False
    with pytest.raises(ValueError, match="unscoped"):
        replay_payload(manifest, events, live=_live_capture_payload(manifest, events))


def test_heartbeat_cannot_impersonate_generation_scoped_platform_status(
    tmp_path: Path,
) -> None:
    at_ms = 1_700_000_000_000
    events = (
        CanonicalEvent(
            capture_seq=1,
            collector_received_at_ms=at_ms,
            collector_elapsed_ms=0,
            exchange_timestamp_ms=None,
            channel="control",
            event_kind=EventKind.SUBSCRIPTION_START,
            instrument_name=None,
            raw_payload=json.dumps(
                {"stream": "platform_state", "channel": "platform_state"},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
        CanonicalEvent(
            capture_seq=2,
            collector_received_at_ms=at_ms + 1,
            collector_elapsed_ms=1,
            exchange_timestamp_ms=None,
            channel="heartbeat",
            event_kind=EventKind.HEARTBEAT,
            instrument_name=None,
            raw_payload="{}",
        ),
        CanonicalEvent(
            capture_seq=3,
            collector_received_at_ms=at_ms + 2,
            collector_elapsed_ms=2,
            exchange_timestamp_ms=None,
            channel="platform_state",
            event_kind=EventKind.PLATFORM_STATE,
            instrument_name=None,
            raw_payload=json.dumps(
                {"state": "OPEN", "locked": False, "status_capture_seq": 2},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    manifest = write_capture(tmp_path / "capture", events, complete=True)

    metadata = capture_evidence_metadata(manifest, events)

    assert metadata["platform_state_contract"] == "PLATFORM_STATUS_BARRIER_UNPROVEN"
    assert metadata["evidence_class"] == "PLATFORM_STATUS_BARRIER_REPLAY_ONLY"
    assert metadata["live_comparison_eligible"] is False


def test_live_collector_does_not_clamp_future_exchange_timestamp() -> None:
    session = _LiveSession()
    session.record_ticker(
        f"ticker.{REFERENCE}.agg2",
        {
            "instrument_name": REFERENCE,
            "timestamp": 1_001,
            "state": "open",
        },
        received_at_ms=1_000,
        elapsed_ms=0,
    )

    assert len(session.events) == 1
    assert session.events[0].collector_received_at_ms == 1_000
    assert session.events[0].exchange_timestamp_ms == 1_001

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from market_tape import (
    CAPTURE_FORMAT_ID,
    CanonicalEvent,
    EventKind,
    MarketTapeReducer,
    TapeContractError,
    read_capture,
    validate_capture,
    write_capture,
)
from radar_runtime.fixture import build_fixture_events

from tests.conftest import EventFactory


def test_event_preserves_independent_exchange_and_collector_clocks(
    tmp_path: Path,
) -> None:
    event = CanonicalEvent(
        capture_seq=1,
        collector_received_at_ms=1_000,
        collector_elapsed_ms=0,
        exchange_timestamp_ms=1_001,
        channel="ticker.BTC_USDC-PERPETUAL.agg2",
        event_kind=EventKind.TICKER,
        instrument_name="BTC_USDC-PERPETUAL",
        raw_payload='{"timestamp":1001}',
    )

    assert event.collector_received_at_ms == 1_000
    assert event.collector_elapsed_ms == 0
    assert event.exchange_timestamp_ms == 1_001

    write_capture(tmp_path / "capture", (event,), complete=True)
    _, replay = read_capture(tmp_path / "capture")
    assert replay == (event,)


@pytest.mark.parametrize("timestamp", [None, 0, -1, True])
def test_market_event_requires_positive_exchange_timestamp(timestamp: object) -> None:
    with pytest.raises(ValueError, match="exchange timestamp"):
        CanonicalEvent(
            capture_seq=1,
            collector_received_at_ms=1_000,
            collector_elapsed_ms=0,
            exchange_timestamp_ms=cast(int | None, timestamp),
            channel="ticker.BTC_USDC-PERPETUAL.agg2",
            event_kind=EventKind.TICKER,
            instrument_name="BTC_USDC-PERPETUAL",
            raw_payload='{"timestamp":1000}',
        )


def test_reducer_requires_nondecreasing_collector_elapsed_time(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, at_ms=1_000, elapsed_ms=10))
    reducer.ingest(event_factory(2, EventKind.HEARTBEAT, at_ms=900, elapsed_ms=10))

    with pytest.raises(TapeContractError, match="elapsed"):
        reducer.ingest(event_factory(3, EventKind.HEARTBEAT, at_ms=800, elapsed_ms=9))


def test_snapshot_preserves_latest_raw_collector_wall_time(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, at_ms=1_000, elapsed_ms=10))
    reducer.ingest(event_factory(2, EventKind.HEARTBEAT, at_ms=900, elapsed_ms=11))

    snapshot = reducer.snapshot()

    assert snapshot.as_of_capture_seq == 2
    assert snapshot.collector_as_of_ms == 900


def test_reducer_requires_contiguous_capture_sequence(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.RECONNECT))
    with pytest.raises(TapeContractError, match="contiguous"):
        reducer.ingest(event_factory(3, EventKind.RECONNECT))


def test_invalid_payload_does_not_advance_reducer_sequence_or_elapsed_time(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, at_ms=2_000, elapsed_ms=0))
    malformed = replace(
        event_factory(2, EventKind.HEARTBEAT, at_ms=3_000, elapsed_ms=10),
        raw_payload="{",
    )

    with pytest.raises(TapeContractError, match="valid JSON"):
        reducer.ingest(malformed)

    assert reducer.last_capture_seq == 1
    assert reducer.snapshot().collector_as_of_ms == 2_000
    reducer.ingest(event_factory(2, EventKind.HEARTBEAT, at_ms=2_001, elapsed_ms=1))
    assert reducer.snapshot().as_of_capture_seq == 2


@pytest.mark.parametrize("timestamp", [None, 0, -1, True])
def test_ticker_requires_positive_deribit_timestamp_without_wall_fallback(
    event_factory: EventFactory,
    timestamp: object,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, at_ms=2_000, elapsed_ms=0))
    event = replace(
        event_factory(
            2,
            EventKind.TICKER,
            at_ms=2_001,
            elapsed_ms=1,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={"timestamp": timestamp, "index_price": "100000"},
        ),
        exchange_timestamp_ms=2_001,
    )

    with pytest.raises(TapeContractError, match="positive integer field: timestamp"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 1
    assert reducer.snapshot().tickers == ()


def test_ticker_payload_timestamp_must_match_canonical_envelope(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    event = replace(
        event_factory(
            1,
            EventKind.TICKER,
            at_ms=2_000,
            elapsed_ms=0,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={"timestamp": 1_999, "index_price": "100000"},
        ),
        exchange_timestamp_ms=2_000,
    )

    with pytest.raises(TapeContractError, match="envelope"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 0


def test_regressing_ticker_does_not_overwrite_and_equal_timestamp_can_update(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    instrument = "BTC_USDC-PERPETUAL"
    first = replace(
        event_factory(
            1,
            EventKind.TICKER,
            at_ms=2_000,
            elapsed_ms=0,
            instrument_name=instrument,
            payload={"timestamp": 2_000, "index_price": "100000"},
        ),
        exchange_timestamp_ms=2_000,
    )
    stale = replace(
        event_factory(
            2,
            EventKind.TICKER,
            at_ms=3_000,
            elapsed_ms=1,
            instrument_name=instrument,
            payload={"timestamp": 1_999, "index_price": "90000"},
        ),
        exchange_timestamp_ms=1_999,
    )
    equal = replace(
        event_factory(
            3,
            EventKind.TICKER,
            at_ms=4_000,
            elapsed_ms=2,
            instrument_name=instrument,
            payload={"timestamp": 2_000, "index_price": "100001"},
        ),
        exchange_timestamp_ms=2_000,
    )

    reducer.ingest(first)
    reducer.ingest(stale)
    after_stale = reducer.snapshot()
    assert after_stale.as_of_capture_seq == 2
    assert after_stale.tickers[0].capture_seq == 1
    assert after_stale.tickers[0].payload["index_price"] == "100000"

    reducer.ingest(equal)
    after_equal = reducer.snapshot()
    assert after_equal.tickers[0].capture_seq == 3
    assert after_equal.tickers[0].payload["index_price"] == "100001"


@pytest.mark.parametrize("timestamp", [None, 0, -1, True])
def test_each_trade_requires_positive_deribit_timestamp(
    event_factory: EventFactory,
    timestamp: object,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, at_ms=2_000, elapsed_ms=0))
    event = replace(
        event_factory(
            2,
            EventKind.TRADE,
            at_ms=2_001,
            elapsed_ms=1,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={
                "trades": [
                    {
                        "trade_seq": 1,
                        "timestamp": timestamp,
                        "price": "100000",
                        "amount": "1",
                        "direction": "buy",
                    }
                ]
            },
        ),
        exchange_timestamp_ms=2_001,
    )

    with pytest.raises(TapeContractError, match="positive integer field: timestamp"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 1
    assert reducer.snapshot().trades == ()


def test_trade_source_regression_is_atomic_and_corrected_event_can_retry(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    instrument = "BTC_USDC-PERPETUAL"

    def trade_event(
        capture_seq: int,
        trade_seq: int,
        source_at_ms: int,
        *,
        elapsed_ms: int,
    ) -> CanonicalEvent:
        return replace(
            event_factory(
                capture_seq,
                EventKind.TRADE,
                at_ms=3_000 + capture_seq,
                elapsed_ms=elapsed_ms,
                instrument_name=instrument,
                payload={
                    "trades": [
                        {
                            "trade_seq": trade_seq,
                            "timestamp": source_at_ms,
                            "price": "100000",
                            "amount": "1",
                            "direction": "buy",
                        }
                    ]
                },
            ),
            exchange_timestamp_ms=source_at_ms,
        )

    reducer.ingest(trade_event(1, 10, 2_000, elapsed_ms=0))
    with pytest.raises(TapeContractError, match="source time regressed"):
        reducer.ingest(trade_event(2, 11, 1_999, elapsed_ms=1))

    failed = reducer.snapshot()
    assert reducer.last_capture_seq == 1
    assert tuple(item.trade_seq for item in failed.trades) == (10,)
    assert failed.trade_gaps == ()

    reducer.ingest(trade_event(2, 11, 2_001, elapsed_ms=1))
    assert tuple(item.trade_seq for item in reducer.snapshot().trades) == (10, 11)


def test_trade_batch_validates_every_item_before_committing(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    instrument = "BTC_USDC-PERPETUAL"
    event = replace(
        event_factory(
            1,
            EventKind.TRADE,
            at_ms=3_000,
            elapsed_ms=0,
            instrument_name=instrument,
            payload={
                "trades": [
                    {
                        "trade_seq": 1,
                        "timestamp": 2_000,
                        "price": "100000",
                        "amount": "1",
                        "direction": "buy",
                    },
                    {
                        "trade_seq": 3,
                        "timestamp": 2_001,
                        "price": "100001",
                        "amount": "0",
                        "direction": "sell",
                    },
                ]
            },
        ),
        exchange_timestamp_ms=2_001,
    )

    with pytest.raises(TapeContractError, match="trade price and amount"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 0
    with pytest.raises(TapeContractError, match="empty tape"):
        reducer.snapshot()


def test_trade_envelope_timestamp_is_maximum_batch_timestamp(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    event = replace(
        event_factory(
            1,
            EventKind.TRADE,
            at_ms=3_000,
            elapsed_ms=0,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={
                "trades": [
                    {
                        "trade_seq": 1,
                        "timestamp": 2_000,
                        "price": "100000",
                        "amount": "1",
                        "direction": "buy",
                    },
                    {
                        "trade_seq": 2,
                        "timestamp": 2_001,
                        "price": "100001",
                        "amount": "1",
                        "direction": "sell",
                    },
                ]
            },
        ),
        exchange_timestamp_ms=2_000,
    )

    with pytest.raises(TapeContractError, match="envelope"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 0


def test_trade_batch_sequences_must_be_strictly_increasing(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    event = replace(
        event_factory(
            1,
            EventKind.TRADE,
            at_ms=3_000,
            elapsed_ms=0,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={
                "trades": [
                    {
                        "trade_seq": 2,
                        "timestamp": 2_001,
                        "price": "100001",
                        "amount": "1",
                        "direction": "sell",
                    },
                    {
                        "trade_seq": 1,
                        "timestamp": 2_000,
                        "price": "100000",
                        "amount": "1",
                        "direction": "buy",
                    },
                ]
            },
        ),
        exchange_timestamp_ms=2_001,
    )

    with pytest.raises(TapeContractError, match="strictly increasing"):
        reducer.ingest(event)

    assert reducer.last_capture_seq == 0


def test_instrument_requires_explicit_quantity_and_commission_metadata(
    event_factory: EventFactory,
) -> None:
    complete = {
        "instrument_name": "BTC_USDC-PERPETUAL",
        "kind": "perpetual",
        "active": True,
        "contract_size": "1",
        "min_trade_amount": "0.01",
        "amount_step": "0.001",
        "taker_commission": "0",
    }
    for field, invalid in (
        ("contract_size", None),
        ("min_trade_amount", None),
        ("amount_step", None),
        ("taker_commission", None),
        ("contract_size", "0"),
        ("min_trade_amount", "-1"),
        ("amount_step", "0"),
        ("taker_commission", "-0.1"),
    ):
        reducer = MarketTapeReducer()
        payload = dict(complete)
        if invalid is None:
            del payload[field]
        else:
            payload[field] = invalid

        with pytest.raises(TapeContractError):
            reducer.ingest(
                event_factory(
                    1,
                    EventKind.INSTRUMENT,
                    instrument_name="BTC_USDC-PERPETUAL",
                    payload=payload,
                )
            )

        assert reducer.last_capture_seq == 0


def test_instrument_preserves_distinct_quantity_metadata_and_catalog_lineage(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(
        event_factory(
            1,
            EventKind.INSTRUMENT,
            instrument_name="BTC_USDC-PERPETUAL",
            payload={
                "instrument_name": "BTC_USDC-PERPETUAL",
                "kind": "perpetual",
                "active": True,
                "contract_size": "1",
                "min_trade_amount": "0.01",
                "amount_step": "0.001",
                "taker_commission": "0",
            },
        )
    )

    instrument = reducer.snapshot().instruments[0]
    assert instrument.source_capture_seq == 1
    assert instrument.min_trade_amount == Decimal("0.01")
    assert instrument.amount_step == Decimal("0.001")
    assert instrument.taker_commission == Decimal("0")


def test_reconnect_invalidates_platform_state(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(
        event_factory(
            1,
            EventKind.PLATFORM_STATE,
            payload={"state": "OPEN", "locked": False},
        )
    )
    assert reducer.snapshot().platform_state is not None

    reducer.ingest(event_factory(2, EventKind.RECONNECT))

    assert reducer.snapshot().platform_state is None


@pytest.mark.parametrize(
    "payload",
    (
        {"state": "OPEN"},
        {"state": "OPEN", "locked": True},
        {"state": "LOCKED", "locked": False},
        {"state": "UNKNOWN", "locked": False},
        {"state": "unknown", "locked": None},
        {"state": "OPEN", "locked": "false"},
        {"state": "OPEN", "locked": False, "source_capture_seqs": [2]},
        {"state": "OPEN", "locked": False, "status_capture_seq": 3},
    ),
)
def test_platform_state_contract_rejects_invalid_payload_atomically(
    event_factory: EventFactory,
    payload: dict[str, object],
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(event_factory(1, EventKind.HEARTBEAT, elapsed_ms=0))

    with pytest.raises(TapeContractError, match="platform"):
        reducer.ingest(
            event_factory(
                2,
                EventKind.PLATFORM_STATE,
                elapsed_ms=1,
                payload=payload,
            )
        )

    assert reducer.last_capture_seq == 1
    assert reducer.snapshot().platform_state is None
    reducer.ingest(event_factory(2, EventKind.HEARTBEAT, elapsed_ms=1))


def test_platform_open_rejects_status_sequence_that_points_to_heartbeat(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(
        event_factory(
            1,
            EventKind.SUBSCRIPTION_START,
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
    )
    reducer.ingest(event_factory(2, EventKind.HEARTBEAT))

    with pytest.raises(TapeContractError, match="observed public status"):
        reducer.ingest(
            event_factory(
                3,
                EventKind.PLATFORM_STATE,
                payload={"state": "OPEN", "locked": False, "status_capture_seq": 2},
            )
        )

    assert reducer.last_capture_seq == 2
    assert reducer.snapshot().platform_state is None


def test_platform_unknown_preserves_null_lock_and_subscription_lineage(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(
        event_factory(
            1,
            EventKind.SUBSCRIPTION_START,
            elapsed_ms=0,
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
    )
    reducer.ingest(
        event_factory(
            2,
            EventKind.PLATFORM_STATE,
            elapsed_ms=1,
            payload={"state": "UNKNOWN", "locked": None},
        )
    )

    state = reducer.snapshot().platform_state
    assert state is not None
    assert state.locked is None
    assert state.source_capture_seqs == (1, 2)


def test_new_platform_subscription_invalidates_prior_open_state(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    reducer.ingest(
        event_factory(
            1,
            EventKind.SUBSCRIPTION_START,
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
    )
    reducer.ingest(
        event_factory(
            2,
            EventKind.PLATFORM_STATE,
            payload={"state": "OPEN", "locked": False, "status_capture_seq": 2},
            channel="public/status",
        )
    )
    assert reducer.snapshot().platform_state is not None

    reducer.ingest(
        event_factory(
            3,
            EventKind.SUBSCRIPTION_START,
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
    )

    assert reducer.snapshot().platform_state is None


def test_book_gap_and_reconnect_invalidate_visible_book(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    instrument = "BTC_USDC-20JUL26-100000-C"
    reducer.ingest(
        event_factory(
            1,
            EventKind.BOOK_SNAPSHOT,
            instrument_name=instrument,
            payload={
                "change_id": 10,
                "bids": [["500", "1"]],
                "asks": [["510", "2"]],
            },
        )
    )
    snapshot = reducer.snapshot()
    assert snapshot.books[0].valid
    assert snapshot.books[0].best_bid() is not None

    reducer.ingest(
        event_factory(
            2,
            EventKind.BOOK_CHANGE,
            instrument_name=instrument,
            payload={
                "change_id": 12,
                "prev_change_id": 9,
                "bids": [],
                "asks": [],
            },
        )
    )
    assert not reducer.snapshot().books[0].valid
    assert len(reducer.snapshot().book_gaps) == 1

    reducer.ingest(
        event_factory(
            3,
            EventKind.BOOK_SNAPSHOT,
            instrument_name=instrument,
            payload={
                "change_id": 13,
                "bids": [["501", "1"]],
                "asks": [["511", "2"]],
            },
        )
    )
    assert reducer.snapshot().books[0].valid
    reducer.ingest(event_factory(4, EventKind.RECONNECT))
    assert not reducer.snapshot().books[0].valid


def test_invalid_book_snapshot_is_atomic_and_same_sequence_can_retry(
    event_factory: EventFactory,
) -> None:
    reducer = MarketTapeReducer()
    instrument = "BTC_USDC-20JUL26-100000-C"
    reducer.ingest(
        event_factory(
            1,
            EventKind.BOOK_SNAPSHOT,
            instrument_name=instrument,
            payload={
                "change_id": 10,
                "bids": [["500", "1"]],
                "asks": [["510", "2"]],
            },
        )
    )
    before = reducer.snapshot().books[0]
    invalid = event_factory(
        2,
        EventKind.BOOK_SNAPSHOT,
        instrument_name=instrument,
        payload={
            "change_id": 11,
            "bids": [["501", "3"], ["invalid"]],
            "asks": [["511", "4"]],
        },
    )

    with pytest.raises(TapeContractError, match="invalid shape"):
        reducer.ingest(invalid)

    assert reducer.last_capture_seq == 1
    assert reducer.snapshot().books[0] == before
    reducer.ingest(
        event_factory(
            2,
            EventKind.BOOK_SNAPSHOT,
            instrument_name=instrument,
            payload={
                "change_id": 11,
                "bids": [["501", "3"]],
                "asks": [["511", "4"]],
            },
        )
    )
    after = reducer.snapshot().books[0]
    assert after.change_id == 11
    best_bid = after.best_bid()
    assert best_bid is not None and best_bid[0] == Decimal("501")


def test_capture_roundtrip_is_deterministic_and_tamper_checked(
    tmp_path: Path,
) -> None:
    events = build_fixture_events()
    written = write_capture(tmp_path / "capture", events, complete=True)
    manifest, replay = read_capture(tmp_path / "capture")

    assert manifest == written
    assert manifest.format_id == CAPTURE_FORMAT_ID
    assert replay == events
    assert manifest.first_capture_seq == 1
    assert manifest.last_capture_seq == len(events)

    data = tmp_path / "capture" / "capture.jsonl"
    data.write_bytes(data.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="digest changed"):
        read_capture(tmp_path / "capture")


def test_capture_manifest_is_bound_to_exact_canonical_events(tmp_path: Path) -> None:
    events = build_fixture_events()
    manifest = write_capture(tmp_path / "capture", events, complete=True)
    tampered_events = (
        *events[:-1],
        replace(events[-1], raw_payload='{"tampered":true}'),
    )

    with pytest.raises(ValueError, match="canonical events digest"):
        validate_capture(manifest, tampered_events)


def test_capture_manifest_complete_must_be_boolean(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    write_capture(root, build_fixture_events(), complete=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["complete"] = "false"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="complete must be boolean"):
        read_capture(root)


def test_capture_reader_rejects_unknown_format_identity(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    write_capture(root, build_fixture_events(), complete=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_id"] = "REMOVED_FORMAT"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported capture format"):
        read_capture(root)


def test_capture_writer_rejects_collector_elapsed_regression(
    tmp_path: Path,
    event_factory: EventFactory,
) -> None:
    events = (
        event_factory(1, EventKind.HEARTBEAT, elapsed_ms=2),
        event_factory(2, EventKind.HEARTBEAT, elapsed_ms=1),
    )

    with pytest.raises(ValueError, match="elapsed"):
        write_capture(tmp_path / "capture", events, complete=True)


def test_capture_reader_rejects_missing_elapsed_time(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    written = write_capture(root, build_fixture_events(), complete=True)
    data_path = root / written.data_path
    rows = tuple(json.loads(line) for line in data_path.read_text().splitlines())
    del rows[0]["collector_elapsed_ms"]
    data_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content_sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="no collector elapsed time"):
        read_capture(root)

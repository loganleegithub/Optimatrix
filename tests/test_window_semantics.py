from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from market_tape import CanonicalEvent, EventKind
from short_vol_radar import RadarPolicy, RadarProjector, WindowCoverage

from tests.conftest import EventFactory

REFERENCE = "BTC_USDC-PERPETUAL"
START_MS = int(datetime(2026, 7, 20, tzinfo=UTC).timestamp() * 1_000)


def _subscription(
    event_factory: EventFactory,
    capture_seq: int,
    stream: str,
    *,
    elapsed_ms: int | None = None,
) -> CanonicalEvent:
    return event_factory(
        capture_seq,
        EventKind.SUBSCRIPTION_START,
        at_ms=START_MS,
        elapsed_ms=elapsed_ms,
        payload={"stream": stream},
    )


def _ticker(
    event_factory: EventFactory,
    capture_seq: int,
    minute: int,
    price: str,
    *,
    elapsed_ms: int | None = None,
) -> CanonicalEvent:
    at_ms = START_MS + minute * 60_000
    return event_factory(
        capture_seq,
        EventKind.TICKER,
        at_ms=at_ms,
        elapsed_ms=elapsed_ms,
        instrument_name=REFERENCE,
        payload={
            "timestamp": at_ms,
            "state": "open",
            "last_price": price,
            "index_price": price,
            "mark_price": price,
            "best_bid_price": price,
            "best_ask_price": price,
            "funding_8h": "0",
            "open_interest": "100",
        },
    )


def _started_projector(event_factory: EventFactory) -> tuple[RadarProjector, int]:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(60, 300),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price"))
    projector.ingest(_subscription(event_factory, 2, "reference_trade"))
    return projector, 2


def test_warmup_is_unknown_not_observed_zero(
    event_factory: EventFactory,
) -> None:
    projector, sequence = _started_projector(event_factory)
    frame = projector.ingest(_ticker(event_factory, sequence + 1, 0, "100000"))
    assert frame is not None

    one_minute = frame.window(60)
    assert one_minute is not None
    assert not one_minute.coverage.price_complete
    assert one_minute.path is None
    assert "PRICE_SUBSCRIPTION_LOOKBACK_INCOMPLETE" in (one_minute.coverage.incomplete_reasons)
    assert "PRICE_MARKET_LOOKBACK_INCOMPLETE" in one_minute.coverage.incomplete_reasons


def test_collector_wall_jump_cannot_complete_elapsed_warmup(
    event_factory: EventFactory,
) -> None:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(60,),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price", elapsed_ms=0))
    projector.ingest(_subscription(event_factory, 2, "reference_trade", elapsed_ms=0))
    frame = projector.ingest(_ticker(event_factory, 3, 60, "100000", elapsed_ms=1_000))
    assert frame is not None

    one_minute = frame.window(60)
    assert one_minute is not None
    assert one_minute.coverage.price_subscription_elapsed_seconds == 1
    assert one_minute.coverage.trade_subscription_elapsed_seconds == 1
    assert one_minute.coverage.price_market_lookback_seconds == 0
    assert one_minute.coverage.price_market_anchor_at is None
    assert not one_minute.coverage.price_complete
    assert not one_minute.coverage.trade_complete


def test_complete_flat_path_and_empty_flow_are_observed_zero(
    event_factory: EventFactory,
) -> None:
    projector, sequence = _started_projector(event_factory)
    frame = None
    for minute in range(7):
        sequence += 1
        frame = projector.ingest(_ticker(event_factory, sequence, minute, "100000"))
    assert frame is not None

    one_minute = frame.window(60)
    five_minutes = frame.window(300)
    assert one_minute is not None and five_minutes is not None
    assert one_minute.coverage.price_complete
    assert one_minute.path is not None
    assert one_minute.path.return_fraction == Decimal("0")
    assert one_minute.path.range_fraction == Decimal("0")
    assert one_minute.path.realized_variation == Decimal("0")
    assert one_minute.coverage.trade_complete
    assert one_minute.flow is not None
    assert one_minute.flow.trade_volume == Decimal("0")
    assert five_minutes.coverage.price_market_lookback_seconds == 300
    assert five_minutes.coverage.price_subscription_elapsed_seconds == 300
    assert five_minutes.coverage.trade_subscription_elapsed_seconds == 300
    assert five_minutes.coverage.price_market_anchor_at == (
        five_minutes.coverage.requested_market_start_at
    )
    assert five_minutes.coverage.price_market_endpoint_at == five_minutes.coverage.market_as_of


def test_reconnect_forces_explicit_resubscription_and_new_warmup(
    event_factory: EventFactory,
) -> None:
    projector, sequence = _started_projector(event_factory)
    for minute in range(7):
        sequence += 1
        projector.ingest(_ticker(event_factory, sequence, minute, "100000"))
    sequence += 1
    reconnect_at = START_MS + 7 * 60_000
    projector.ingest(event_factory(sequence, EventKind.RECONNECT, at_ms=reconnect_at))
    sequence += 1
    frame = projector.ingest(_ticker(event_factory, sequence, 8, "100000"))
    assert frame is not None
    observation = frame.window(60)
    assert observation is not None
    assert not observation.coverage.price_complete
    assert observation.coverage.reconnect_contaminated


def test_trade_gap_contaminates_only_windows_that_cover_it(
    event_factory: EventFactory,
) -> None:
    projector, sequence = _started_projector(event_factory)
    for minute in range(7):
        sequence += 1
        projector.ingest(_ticker(event_factory, sequence, minute, "100000"))
    sequence += 1
    gap_at = START_MS + 7 * 60_000
    projector.ingest(
        event_factory(
            sequence,
            EventKind.TRADE_GAP,
            at_ms=gap_at,
            instrument_name=REFERENCE,
            payload={"trades": []},
        )
    )
    sequence += 1
    frame = projector.ingest(_ticker(event_factory, sequence, 8, "100000"))
    assert frame is not None
    contaminated = frame.window(300)
    assert contaminated is not None
    assert not contaminated.coverage.trade_complete
    assert contaminated.coverage.gap_contaminated

    sequence += 1
    later = projector.ingest(_ticker(event_factory, sequence, 14, "100000"))
    assert later is not None
    recovered = later.window(300)
    assert recovered is not None
    assert recovered.coverage.trade_complete
    assert not recovered.coverage.gap_contaminated


def test_full_elapsed_with_compressed_market_span_is_incomplete(
    event_factory: EventFactory,
) -> None:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(60,),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price", elapsed_ms=0))
    projector.ingest(_subscription(event_factory, 2, "reference_trade", elapsed_ms=0))
    projector.ingest(_ticker(event_factory, 3, 0, "100000", elapsed_ms=0))
    frame = projector.ingest(
        event_factory(
            4,
            EventKind.TICKER,
            at_ms=START_MS + 1_000,
            elapsed_ms=60_000,
            instrument_name=REFERENCE,
            payload={
                "timestamp": START_MS + 1_000,
                "state": "open",
                "last_price": "100000",
                "index_price": "100000",
                "mark_price": "100000",
                "best_bid_price": "100000",
                "best_ask_price": "100000",
                "funding_8h": "0",
                "open_interest": "100",
            },
        )
    )
    assert frame is not None

    window = frame.window(60)
    assert window is not None
    assert window.coverage.price_subscription_elapsed_seconds == 60
    assert window.coverage.price_market_lookback_seconds == 0
    assert not window.coverage.price_complete
    assert window.path is None
    assert "PRICE_MARKET_LOOKBACK_INCOMPLETE" in window.coverage.incomplete_reasons


def test_missing_market_anchor_is_incomplete_after_full_elapsed(
    event_factory: EventFactory,
) -> None:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(3_600,),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price", elapsed_ms=0))
    projector.ingest(_subscription(event_factory, 2, "reference_trade", elapsed_ms=0))
    projector.ingest(_ticker(event_factory, 3, 2, "100000", elapsed_ms=0))
    frame = projector.ingest(_ticker(event_factory, 4, 61, "100000", elapsed_ms=3_600_000))
    assert frame is not None

    window = frame.window(3_600)
    assert window is not None
    assert window.coverage.price_subscription_elapsed_seconds == 3_600
    assert window.coverage.price_market_lookback_seconds == 0
    assert window.coverage.price_market_anchor_at is None
    assert not window.coverage.price_complete
    assert window.path is None


def test_exact_market_bracket_preserves_flat_path_and_zero_trade_flow(
    event_factory: EventFactory,
) -> None:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(60,),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price", elapsed_ms=0))
    projector.ingest(_subscription(event_factory, 2, "reference_trade", elapsed_ms=0))
    projector.ingest(_ticker(event_factory, 3, 0, "100000", elapsed_ms=0))
    frame = projector.ingest(_ticker(event_factory, 4, 1, "100000", elapsed_ms=60_000))
    assert frame is not None

    window = frame.window(60)
    assert window is not None
    assert window.coverage.price_complete
    assert window.coverage.trade_complete
    assert window.coverage.price_market_anchor_at == window.coverage.requested_market_start_at
    assert window.coverage.price_market_endpoint_at == window.coverage.market_as_of
    assert window.path is not None and window.path.realized_variation == Decimal("0")
    assert window.flow is not None and window.flow.trade_volume == Decimal("0")


def test_same_timestamp_arrivals_do_not_refresh_market_watermark_progress(
    event_factory: EventFactory,
) -> None:
    projector = RadarProjector(
        policy=RadarPolicy(
            required_windows_seconds=(60,),
            minimum_fresh_option_quotes=0,
        )
    )
    projector.ingest(_subscription(event_factory, 1, "reference_price", elapsed_ms=0))
    projector.ingest(_subscription(event_factory, 2, "reference_trade", elapsed_ms=0))
    projector.ingest(_ticker(event_factory, 3, 0, "100000", elapsed_ms=0))
    projector.ingest(_ticker(event_factory, 4, 1, "100000", elapsed_ms=60_000))
    frame = projector.ingest(_ticker(event_factory, 5, 1, "100000", elapsed_ms=63_000))
    assert frame is not None

    window = frame.window(60)
    assert window is not None
    assert window.coverage.price_market_lookback_seconds == 60
    assert window.coverage.price_watermark_progress_age_ms == 3_000
    assert not window.coverage.price_complete
    assert window.path is None
    assert "PRICE_MARKET_WATERMARK_STALE" in window.coverage.incomplete_reasons


def test_window_contract_rejects_false_complete_market_coverage() -> None:
    coverage = WindowCoverage(
        requested_seconds=60,
        requested_market_start_at=None,
        market_as_of=None,
        price_market_anchor_at=None,
        price_market_endpoint_at=None,
        price_market_lookback_seconds=0,
        price_subscription_elapsed_seconds=60,
        trade_subscription_elapsed_seconds=60,
        price_watermark_progress_age_ms=0,
        price_complete=False,
        trade_complete=False,
        gap_contaminated=False,
        reconnect_contaminated=False,
        incomplete_reasons=("PRICE_MARKET_LOOKBACK_INCOMPLETE",),
    )

    with pytest.raises(ValueError, match="exact coverage"):
        replace(coverage, price_complete=True)

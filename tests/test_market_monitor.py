from __future__ import annotations

from decimal import Decimal

import pytest
from market_monitor import BookState, ContinuityGap, ContinuousOrderBook, TimeInterval, TrustedClock
from market_monitor.clock import CLOCK_EXPIRY_MS
from market_monitor.deribit import (
    INDEX_CHANNEL,
    CatalogBootstrap,
    PlatformReadiness,
    book_channel,
    subscription_batches,
    ticker_channel,
    validate_subscription_ack,
)
from market_monitor.index import IndexMinuteReducer
from market_monitor.types import SourceDataError


def snapshot(
    *,
    change_id: int = 1,
    bids: list[list[object]] | None = None,
    asks: list[list[object]] | None = None,
) -> dict[str, object]:
    return {
        "type": "snapshot",
        "timestamp": 1_000,
        "instrument_name": "OPTION",
        "change_id": change_id,
        "bids": bids if bids is not None else [["new", 10, 2]],
        "asks": asks if asks is not None else [["new", 11, 3]],
        "new_exchange_field": "ignored",
    }


def test_trusted_clock_outward_rounding_refresh_and_expiry() -> None:
    clock = TrustedClock.from_response(10_000, 1_000, 1_010)
    assert clock.interval_at(1_010) == TimeInterval(10_000, 10_011)
    advanced = clock.interval_at(2_011)
    assert advanced.lower_ms == 10_999
    assert advanced.upper_ms == 11_014

    refreshed = clock.refresh(11_002, 2_000, 2_010)
    assert refreshed.base == TimeInterval(11_002, 11_012)
    with pytest.raises(ContinuityGap, match="expired"):
        refreshed.interval_at(2_010 + CLOCK_EXPIRY_MS)


def test_trusted_clock_rejects_disjoint_refresh_and_backward_monotonic() -> None:
    clock = TrustedClock.from_response(10_000, 1_000, 1_010)
    with pytest.raises(ContinuityGap, match="do not intersect"):
        clock.refresh(50_000, 2_000, 2_010)
    with pytest.raises(ValueError, match="backward"):
        clock.interval_at(1_009)


def test_order_book_requires_snapshot_and_exact_change_continuity() -> None:
    book = ContinuousOrderBook("OPTION")
    with pytest.raises(ContinuityGap, match="before usable snapshot"):
        book.apply(
            {
                **snapshot(),
                "type": "change",
                "prev_change_id": 0,
            },
            1,
        )
    assert book.state is BookState.UNKNOWN

    assert book.apply(snapshot(), 100)
    assert book.state.value == BookState.USABLE.value
    assert book.levels("bid")[0].price == Decimal(10)
    assert book.apply(
        {
            **snapshot(change_id=2),
            "type": "change",
            "prev_change_id": 1,
            "bids": [["change", 10, 4], ["new", 9, 1]],
            "asks": [],
        },
        200,
    )
    assert [level.amount for level in book.levels("bid")] == [Decimal(4), Decimal(1)]

    with pytest.raises(ContinuityGap, match="continuity gap"):
        book.apply(
            {
                **snapshot(change_id=4),
                "type": "change",
                "prev_change_id": 999,
                "bids": [],
                "asks": [],
            },
            300,
        )
    assert book.state is BookState.UNKNOWN

    book.apply(snapshot(), 400)
    with pytest.raises(ContinuityGap, match="timestamp regressed"):
        book.apply(
            {
                **snapshot(change_id=2),
                "type": "change",
                "timestamp": 999,
                "prev_change_id": 1,
                "bids": [],
                "asks": [],
            },
            500,
        )


def test_quiet_book_stays_usable_without_artificial_mutation_refresh() -> None:
    book = ContinuousOrderBook("OPTION")
    book.apply(snapshot(), 100)
    assert book.last_mutation_monotonic_ms == 100
    changed = book.apply(
        {
            **snapshot(change_id=2),
            "type": "change",
            "prev_change_id": 1,
            "bids": [],
            "asks": [],
        },
        50_000,
    )
    assert not changed
    assert book.state is BookState.USABLE
    assert book.last_mutation_monotonic_ms == 100


def test_empty_book_is_known_and_crossed_book_fails_closed() -> None:
    empty = ContinuousOrderBook("OPTION")
    assert empty.apply(snapshot(bids=[], asks=[]), 1)
    assert empty.state is BookState.USABLE
    assert empty.economic_revision == 1
    assert empty.levels("bid") == ()

    crossed = ContinuousOrderBook("OPTION")
    with pytest.raises(SourceDataError, match="crossed"):
        crossed.apply(snapshot(bids=[["new", 11, 1]], asks=[["new", 10, 1]]), 1)


def test_index_minutes_require_full_coverage_and_reject_late_or_regressed_ticks() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(60_500)
    reducer.accept_tick(source_timestamp_ms=61_000, price="100", causal_seq=1)
    reducer.accept_tick(source_timestamp_ms=120_000, price="101", causal_seq=2)
    assert reducer.seal_ready(120_000) == ()
    reducer.accept_tick(source_timestamp_ms=121_000, price="102", causal_seq=3)
    reducer.accept_tick(source_timestamp_ms=180_000, price="103", causal_seq=4)
    sealed = reducer.seal_ready(180_000)
    assert [item.minute_start_ms for item in sealed] == [120_000]

    with pytest.raises(ContinuityGap, match=r"regressed|sealed"):
        reducer.accept_tick(source_timestamp_ms=179_000, price="99", causal_seq=5)
    assert reducer.sealed == ()

    reducer.start_continuous_coverage(240_000)
    reducer.accept_tick(source_timestamp_ms=250_000, price="100", causal_seq=6)
    with pytest.raises(ContinuityGap, match="regressed"):
        reducer.accept_tick(source_timestamp_ms=249_999, price="100", causal_seq=7)


def test_index_consecutive_prices_detect_missing_minute() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        reducer.accept_tick(
            source_timestamp_ms=timestamp, price=100 + sequence, causal_seq=sequence
        )
        reducer.seal_ready(timestamp)
    assert reducer.consecutive_prices(2) == (Decimal(101), Decimal(102), Decimal(103))


def test_exact_channels_bounded_subscriptions_and_acknowledgements() -> None:
    assert INDEX_CHANNEL == "deribit_price_index.btc_usdc"
    assert ticker_channel("X") == "ticker.X.100ms"
    assert book_channel("X") == "book.X.100ms"
    assert subscription_batches(["a", "b", "a", "c"], maximum_size=2) == (
        ("a", "b"),
        ("c",),
    )
    validate_subscription_ack(("a", "b"), ["a", "b"])
    with pytest.raises(SourceDataError, match="exactly"):
        validate_subscription_ack(("a", "b"), ["b", "a"])


def test_catalog_bootstrap_buffers_lifecycle_until_snapshot_reconciliation() -> None:
    catalog = CatalogBootstrap()
    catalog.acknowledge_lifecycle()
    assert catalog.accept_lifecycle({"instrument_name": "NEW", "state": "open", "extra": 1}) is None
    assert not catalog.complete
    assert catalog.reconcile() == ({"instrument_name": "NEW", "state": "open", "extra": 1},)
    assert catalog.complete
    assert catalog.accept_lifecycle({"instrument_name": "OLD", "state": "closed"}) == {
        "instrument_name": "OLD",
        "state": "closed",
    }

    catalog = CatalogBootstrap()
    catalog.acknowledge_lifecycle()
    catalog.mark_incomplete()
    assert catalog.reconcile() == ()
    assert not catalog.complete


def test_platform_readiness_never_defaults_unseen_maintenance_or_recovery() -> None:
    platform = PlatformReadiness()
    platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    platform.apply_status(
        {"locked": False, "locked_indices": [], "locked_currencies": [], "extra": "ok"}
    )
    platform.public_methods_allowed = True
    assert platform.maintenance is None
    assert not platform.usable
    platform.prove_operational_from_post_status_public_success()
    platform.complete_post_status_bootstrap()
    assert platform.usable

    platform.apply_platform_notification({"maintenance": True, "extra": "tolerated"})
    assert not platform.usable
    platform.apply_platform_notification({"maintenance": False})
    assert not platform.usable
    with pytest.raises(RuntimeError, match="status"):
        platform.complete_post_status_bootstrap()


def test_relevant_status_locks_and_public_method_denial_fail_closed() -> None:
    platform = PlatformReadiness()
    platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    platform.apply_status(
        {"locked": "partial", "locked_indices": ["btc_usdc"], "locked_currencies": []}
    )
    assert not platform.status_usable
    platform.apply_public_methods_notification({"allow_unauthenticated_public_requests": False})
    assert platform.reason == "PUBLIC_METHODS_DENIED"

    with pytest.raises(SourceDataError, match="locked"):
        PlatformReadiness().apply_status(
            {"locked": "unexpected", "locked_indices": [], "locked_currencies": []}
        )

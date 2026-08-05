from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

import pytest
from market_monitor import (
    BookState,
    ContinuityGap,
    ContinuousOrderBook,
    IndexHistoryReducer,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import (
    INDEX_CHANNEL,
    CatalogBootstrap,
    PlatformReadiness,
    book_channel,
    subscription_batches,
    ticker_channel,
    validate_subscription_ack,
)
from market_monitor.index import (
    BaselinePublicationPhase,
    IndexAvailabilityState,
    IndexMinuteReducer,
    IndexPublicationBoundary,
)
from market_monitor.types import SourceDataError


def test_index_history_selects_a_causal_five_minute_suffix_from_finer_chart_points() -> None:
    reducer = IndexHistoryReducer(
        maximum_lookback_minutes=360,
        return_interval_minutes=5,
    )
    rows = [[minute * 60_000, 100 + minute / 100] for minute in range(400)]

    assert reducer.apply_chart_result(rows)
    tail = reducer.current_tail(
        360,
        trusted_time=TimeInterval(400 * 60_000, 400 * 60_000),
        source_stale_deadline_ms=900_000,
    )

    assert tail.availability is IndexAvailabilityState.AVAILABLE
    assert len(tail.points) == 73
    assert tail.points[-1].timestamp_ms == 395 * 60_000
    assert all(
        later.timestamp_ms - earlier.timestamp_ms == 5 * 60_000
        for earlier, later in pairwise(tail.points)
    )
    assert tail.contract is not None
    assert tail.contract.modal_interval_ms == 60_000
    assert tail.contract.exact_suffix_point_count == 80
    assert tail.contract.exact_suffix_minutes == 395


def test_index_history_fails_closed_for_gap_staleness_and_invalid_shape() -> None:
    reducer = IndexHistoryReducer(
        maximum_lookback_minutes=30,
        return_interval_minutes=5,
    )
    rows = [[minute * 60_000, 100] for minute in range(40) if minute != 20]
    reducer.apply_chart_result(rows)

    gap = reducer.current_tail(
        30,
        trusted_time=TimeInterval(40 * 60_000, 40 * 60_000),
        source_stale_deadline_ms=900_000,
    )
    assert gap.availability is IndexAvailabilityState.WINDOW_GAP
    assert gap.reason == "INDEX_HISTORY_WINDOW_GAP"

    stale = reducer.current_tail(
        30,
        trusted_time=TimeInterval(60 * 60_000, 60 * 60_000),
        source_stale_deadline_ms=900_000,
    )
    assert stale.availability is IndexAvailabilityState.SOURCE_STALE
    assert stale.reason == "INDEX_HISTORY_SOURCE_STALE"

    with pytest.raises(SourceDataError, match="strictly increasing"):
        reducer.apply_chart_result([[0, 100], [0, 101]])


def test_index_history_contract_reports_cadence_suffix_age_and_revision_confirmation() -> None:
    reducer = IndexHistoryReducer(
        maximum_lookback_minutes=30,
        return_interval_minutes=5,
    )
    initial = [[minute * 300_000, 100 + minute] for minute in range(9)]
    assert reducer.apply_chart_result(initial)
    state = reducer.current_tail(
        30,
        trusted_time=TimeInterval(9 * 300_000, 9 * 300_000),
        source_stale_deadline_ms=900_000,
    )
    assert state.availability is IndexAvailabilityState.AVAILABLE
    assert state.contract is not None
    assert state.contract.interval_counts == ((300_000, 8),)
    assert state.contract.modal_interval_ms == 300_000
    assert state.contract.newest_response_timestamp_ms == 8 * 300_000
    assert state.contract.newest_response_age_ms == 300_000
    assert state.contract.newest_response_point_excluded_by_completion_cutoff is False
    assert state.contract.exact_suffix_point_count == 9
    assert state.contract.exact_suffix_minutes == 40
    assert state.contract.latest_source_age_ms == 300_000

    revised = [list(row) for row in initial]
    revised[4][1] = 999
    assert reducer.apply_chart_result(revised)
    pending = reducer.current_tail(
        30,
        trusted_time=TimeInterval(9 * 300_000, 9 * 300_000),
        source_stale_deadline_ms=900_000,
    )
    assert pending.availability is IndexAvailabilityState.REVISION
    assert pending.reason == "INDEX_HISTORY_REVISION"
    assert pending.contract is not None
    assert pending.contract.revision_pending
    assert pending.contract.revised_timestamps_ms == (4 * 300_000,)

    confirmed_with_append = [*revised, [9 * 300_000, 110]]
    assert reducer.apply_chart_result(confirmed_with_append)
    confirmed = reducer.current_tail(
        30,
        trusted_time=TimeInterval(10 * 300_000, 10 * 300_000),
        source_stale_deadline_ms=900_000,
    )
    assert confirmed.availability is IndexAvailabilityState.AVAILABLE
    assert confirmed.contract is not None
    assert not confirmed.contract.revision_pending
    assert confirmed.contract.revision_count == 1


def test_index_history_open_provider_bucket_may_change_without_revision() -> None:
    reducer = IndexHistoryReducer(
        maximum_lookback_minutes=5,
        return_interval_minutes=5,
    )
    assert reducer.apply_chart_result([[0, 100], [300_000, 101], [600_000, 102]])
    assert reducer.apply_chart_result([[0, 100], [300_000, 101], [600_000, 103]])
    state = reducer.current_tail(
        5,
        trusted_time=TimeInterval(900_000, 900_000),
        source_stale_deadline_ms=900_000,
    )
    assert state.availability is IndexAvailabilityState.AVAILABLE
    assert state.contract is not None
    assert state.contract.revision_count == 0
    assert not state.contract.revision_pending


def test_index_history_distinguishes_no_response_from_a_valid_empty_response() -> None:
    reducer = IndexHistoryReducer(
        maximum_lookback_minutes=30,
        return_interval_minutes=5,
    )
    trusted = TimeInterval(1_000_000, 1_000_000)

    bootstrap = reducer.current_tail(
        30,
        trusted_time=trusted,
        source_stale_deadline_ms=900_000,
    )
    assert bootstrap.reason == "INDEX_HISTORY_BOOTSTRAP_REQUIRED"
    assert reducer.apply_chart_result([])
    warmup = reducer.current_tail(
        30,
        trusted_time=trusted,
        source_stale_deadline_ms=900_000,
    )
    assert warmup.reason == "INDEX_HISTORY_WARMUP"
    assert not reducer.apply_chart_result([])


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
    clock = TrustedClock.from_response(
        10_000,
        1_000,
        1_010,
        stale_deadline_ms=73_000,
    )
    assert clock.interval_at(1_010) == TimeInterval(10_000, 10_011)
    advanced = clock.interval_at(2_011)
    assert advanced.lower_ms == 10_999
    assert advanced.upper_ms == 11_014

    refreshed = clock.refresh(11_002, 2_000, 2_010)
    assert refreshed.base == TimeInterval(11_002, 11_012)
    with pytest.raises(ContinuityGap, match="expired"):
        refreshed.interval_at(2_010 + 73_000)


def test_trusted_clock_rejects_disjoint_refresh_and_backward_monotonic() -> None:
    clock = TrustedClock.from_response(
        10_000,
        1_000,
        1_010,
        stale_deadline_ms=73_000,
    )
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


def test_index_tail_rollover_pending_preserves_history_and_requires_exact_alignment() -> None:
    minute_ms = 60_000
    reducer = IndexMinuteReducer(60)
    reducer.start_continuous_coverage(0)
    for sequence in range(1, 63):
        timestamp = 1 if sequence == 1 else (sequence - 1) * minute_ms
        reducer.accept_tick(
            source_timestamp_ms=timestamp,
            price=100 + sequence,
            causal_seq=sequence,
        )
        reducer.seal_ready(timestamp)

    reducer.publish_ready(
        trusted_time=TimeInterval(61 * minute_ms + 1, 61 * minute_ms + 2),
        source_stale_deadline_ms=90_000,
        generation=1,
        global_continuity_epoch=1,
        boundary=IndexPublicationBoundary(1, 1, 1, 1),
    )
    current = reducer.current_tail(
        60,
        trusted_time=TimeInterval(61 * minute_ms + 1, 61 * minute_ms + 2),
        source_stale_deadline_ms=90_000,
    )
    assert current.availability is IndexAvailabilityState.AVAILABLE
    assert current.publication_phase is BaselinePublicationPhase.CURRENT
    assert current.prices is not None
    assert len(current.prices) == 61

    reducer.publish_ready(
        trusted_time=TimeInterval(62 * minute_ms - 1, 62 * minute_ms + 1),
        source_stale_deadline_ms=90_000,
        generation=1,
        global_continuity_epoch=1,
        boundary=IndexPublicationBoundary(1, 2, 2, 2),
    )
    across_boundary = reducer.current_tail(
        60,
        trusted_time=TimeInterval(62 * minute_ms - 1, 62 * minute_ms + 1),
        source_stale_deadline_ms=90_000,
    )
    assert across_boundary.availability is IndexAvailabilityState.AVAILABLE
    assert across_boundary.publication_phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
    assert reducer.sealed == current.closes

    reducer.publish_ready(
        trusted_time=TimeInterval(62 * minute_ms + 1, 62 * minute_ms + 2),
        source_stale_deadline_ms=90_000,
        generation=1,
        global_continuity_epoch=1,
        boundary=IndexPublicationBoundary(1, 3, 3, 3),
    )
    rollover = reducer.current_tail(
        60,
        trusted_time=TimeInterval(62 * minute_ms + 1, 62 * minute_ms + 2),
        source_stale_deadline_ms=90_000,
    )
    assert rollover.availability is IndexAvailabilityState.AVAILABLE
    assert rollover.publication_phase is BaselinePublicationPhase.WATERMARK_PENDING
    assert reducer.sealed == current.closes


def test_index_window_gap_isolated_by_requested_lookback_without_resubscription() -> None:
    reducer = IndexMinuteReducer(5)
    reducer.start_continuous_coverage(0)
    for sequence, timestamp in enumerate(
        (1, 60_000, 120_000, 240_000, 300_000, 360_000, 420_000, 480_000),
        start=1,
    ):
        reducer.accept_tick(
            source_timestamp_ms=timestamp,
            price=100 + sequence,
            causal_seq=sequence,
        )
        reducer.seal_ready(timestamp)

    trusted = TimeInterval(480_001, 480_002)
    reducer.publish_ready(
        trusted_time=trusted,
        source_stale_deadline_ms=90_000,
        generation=1,
        global_continuity_epoch=1,
        boundary=IndexPublicationBoundary(1, 1, 1, 1),
    )
    short = reducer.current_tail(
        2,
        trusted_time=trusted,
        source_stale_deadline_ms=90_000,
    )
    long = reducer.current_tail(
        5,
        trusted_time=trusted,
        source_stale_deadline_ms=90_000,
    )

    assert short.availability is IndexAvailabilityState.AVAILABLE
    assert long.availability is IndexAvailabilityState.WINDOW_GAP


def test_index_tail_distinguishes_warmup_source_stale_and_continuity_gap() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0)
    reducer.accept_tick(source_timestamp_ms=1, price=100, causal_seq=1)

    warmup = reducer.current_tail(
        2,
        trusted_time=TimeInterval(30_000, 30_001),
        source_stale_deadline_ms=90_000,
    )
    assert warmup.availability is IndexAvailabilityState.WARMUP

    stale = reducer.current_tail(
        2,
        trusted_time=TimeInterval(100_002, 100_003),
        source_stale_deadline_ms=90_000,
    )
    assert stale.availability is IndexAvailabilityState.SOURCE_STALE

    reducer.gap()
    gap = reducer.current_tail(
        2,
        trusted_time=TimeInterval(100_002, 100_003),
        source_stale_deadline_ms=90_000,
    )
    assert gap.availability is IndexAvailabilityState.CONTINUITY_GAP


def test_index_tail_treats_unstarted_bootstrap_as_warmup_not_continuity_gap() -> None:
    reducer = IndexMinuteReducer(2)

    bootstrap = reducer.current_tail(
        2,
        trusted_time=TimeInterval(30_000, 30_001),
        source_stale_deadline_ms=90_000,
    )
    assert bootstrap.availability is IndexAvailabilityState.WARMUP

    reducer.gap()
    real_gap = reducer.current_tail(
        2,
        trusted_time=TimeInterval(30_000, 30_001),
        source_stale_deadline_ms=90_000,
    )
    assert real_gap.availability is IndexAvailabilityState.CONTINUITY_GAP


def test_exact_channels_bounded_subscriptions_and_acknowledgements() -> None:
    assert INDEX_CHANNEL == "deribit_price_index.btc_usdc"
    assert ticker_channel("X") == "ticker.X.100ms"
    assert book_channel("X") == "book.X.100ms"
    assert subscription_batches(["a", "b", "a", "c"], maximum_size=2) == (
        ("a", "b"),
        ("c",),
    )
    assert validate_subscription_ack(("a", "b"), ["a", "b"]) == ("a", "b")
    assert validate_subscription_ack(("a", "b"), ["b", "a"]) == ("a", "b")
    assert validate_subscription_ack(("a", "b"), ["a"]) == ("a",)
    for invalid in (["a", "b", "c"], ["a", "a"], ["a", 1]):
        with pytest.raises(SourceDataError):
            validate_subscription_ack(("a", "b"), invalid)


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
    platform.start_epoch(1)
    platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    platform.apply_status({"locked": "false", "extra": "ok"})
    platform.apply_public_methods_notification({"allow_unauthenticated_public_requests": True})
    assert platform.maintenance is None
    assert not platform.usable
    platform.prove_operational_from_post_status_public_success()
    assert not platform.usable
    platform.note_fresh_index_coverage()
    platform.complete_post_status_bootstrap()
    assert platform.usable

    platform.apply_platform_notification({"maintenance": True, "extra": "tolerated"})
    assert not platform.usable
    platform.apply_platform_notification({"maintenance": False})
    assert not platform.usable
    with pytest.raises(RuntimeError, match="facts"):
        platform.complete_post_status_bootstrap()


def test_platform_readiness_accepts_official_lock_notification_union() -> None:
    platform = PlatformReadiness()
    platform.start_epoch(1)
    platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    platform.apply_status({"locked": "false"})
    platform.apply_public_methods_notification({"allow_unauthenticated_public_requests": True})
    platform.prove_operational_from_post_status_public_success()
    platform.note_fresh_index_coverage()
    platform.complete_post_status_bootstrap()
    assert platform.usable

    platform.apply_platform_notification({"price_index": "eth_usdc", "locked": True})
    assert platform.usable

    platform.apply_platform_notification({"price_index": "btc_usdc", "locked": True})
    assert not platform.usable
    assert platform.reason == "RELEVANT_PLATFORM_LOCK"

    platform.apply_platform_notification({"price_index": "btc_usdc", "locked": False})
    assert not platform.usable
    platform.apply_status({"locked": "false"})
    assert not platform.usable
    assert platform.reason == "RELEVANT_PLATFORM_LOCK"


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
    with pytest.raises(SourceDataError, match="locked_indices"):
        PlatformReadiness().apply_status({"locked": "partial"})

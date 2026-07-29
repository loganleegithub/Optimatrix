from __future__ import annotations

from decimal import Decimal

import pytest
from market_monitor import (
    BaselinePublicationPhase,
    ContinuityGap,
    IndexAvailabilityState,
    IndexMinuteReducer,
    IndexPublicationBoundary,
    IndexPublicationUpdate,
    TimeInterval,
)

MINUTE_MS = 60_000


def boundary(sequence: int, monotonic_ms: int) -> IndexPublicationBoundary:
    return IndexPublicationBoundary(
        session_epoch=1,
        ingress_seq=sequence,
        received_monotonic_ms=monotonic_ms,
        causal_seq=sequence,
    )


def tick(
    reducer: IndexMinuteReducer,
    timestamp_ms: int,
    sequence: int,
    *,
    price: int | str = 100,
) -> None:
    reducer.accept_tick(
        source_timestamp_ms=timestamp_ms,
        price=price,
        causal_seq=sequence,
    )


def publish(
    reducer: IndexMinuteReducer,
    *,
    lower_ms: int,
    upper_ms: int | None = None,
    sequence: int,
    generation: int = 7,
    epoch: int = 1,
    stale_deadline_ms: int = 600_000,
) -> IndexPublicationUpdate:
    reducer.seal_ready(lower_ms)
    return reducer.publish_ready(
        trusted_time=TimeInterval(lower_ms, lower_ms if upper_ms is None else upper_ms),
        source_stale_deadline_ms=stale_deadline_ms,
        generation=generation,
        global_continuity_epoch=epoch,
        boundary=boundary(sequence, sequence * 10),
    )


def test_per_band_windows_use_exact_n_plus_one_and_pending_keeps_old_tuple() -> None:
    reducer = IndexMinuteReducer(5)
    reducer.start_continuous_coverage(0, generation=7)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence, price=100 + sequence)
        reducer.seal_ready(timestamp)

    first = publish(reducer, lower_ms=180_001, sequence=10)
    assert first.published_advanced
    short = reducer.current_tail(
        2,
        trusted_time=TimeInterval(180_001, 180_002),
        source_stale_deadline_ms=600_000,
    )
    long = reducer.current_tail(
        3,
        trusted_time=TimeInterval(180_001, 180_002),
        source_stale_deadline_ms=600_000,
    )
    assert short.availability is IndexAvailabilityState.AVAILABLE
    assert len(short.closes) == 3
    assert short.prices == (Decimal(101), Decimal(102), Decimal(103))
    assert long.availability is IndexAvailabilityState.WARMUP

    tick(reducer, 240_000, 11)
    reducer.seal_ready(239_999)
    pending = reducer.publish_ready(
        trusted_time=TimeInterval(239_999, 240_001),
        source_stale_deadline_ms=600_000,
        generation=7,
        global_continuity_epoch=1,
        boundary=boundary(11, 110),
    )
    assert pending.phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
    during_pending = reducer.current_tail(
        2,
        trusted_time=TimeInterval(239_999, 240_001),
        source_stale_deadline_ms=600_000,
    )
    assert during_pending.availability is IndexAvailabilityState.AVAILABLE
    assert during_pending.publication_phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
    assert during_pending.closes == short.closes
    assert during_pending.prices == short.prices


def test_time_boundary_phase_is_latched_when_clock_refresh_tightens_upper_before_target() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0, generation=7)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    publish(reducer, lower_ms=180_001, sequence=10)

    pending = reducer.publish_ready(
        trusted_time=TimeInterval(239_999, 240_001),
        source_stale_deadline_ms=600_000,
        generation=7,
        global_continuity_epoch=1,
        boundary=boundary(11, 110),
    )
    narrowed = reducer.publish_ready(
        trusted_time=TimeInterval(239_999, 239_999),
        source_stale_deadline_ms=600_000,
        generation=7,
        global_continuity_epoch=1,
        boundary=boundary(12, 120),
    )

    assert pending.phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
    assert narrowed.phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
    assert narrowed.published_tail == pending.published_tail
    assert not narrowed.published_advanced


def test_proof_cutoff_does_not_publish_a_minute_before_both_proofs_cross_its_end() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(480_000, generation=3)
    for sequence, timestamp in enumerate((480_001, 540_000, 600_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)

    update = reducer.publish_ready(
        trusted_time=TimeInterval(630_000, 690_000),
        source_stale_deadline_ms=600_000,
        generation=3,
        global_continuity_epoch=1,
        boundary=boundary(4, 40),
    )
    assert update.expected_latest_close_start_ms == 540_000
    assert update.published_tail is not None
    assert update.published_tail.published_tail_last_minute_start_ms == 540_000
    assert all(close.minute_start_ms <= 540_000 for close in update.published_tail.closes)


def test_coverage_start_equality_is_usable_but_later_start_is_warmup() -> None:
    exact = IndexMinuteReducer(2)
    exact.start_continuous_coverage(0, generation=1)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(exact, timestamp, sequence)
        exact.seal_ready(timestamp)
    publish(exact, lower_ms=180_001, sequence=10, generation=1)
    assert (
        exact.current_tail(
            2,
            trusted_time=TimeInterval(180_001, 180_002),
            source_stale_deadline_ms=600_000,
        ).availability
        is IndexAvailabilityState.AVAILABLE
    )

    late = IndexMinuteReducer(2)
    late.start_continuous_coverage(1, generation=1)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(late, timestamp, sequence)
        late.seal_ready(timestamp)
    publish(late, lower_ms=180_001, sequence=10, generation=1)
    assert (
        late.current_tail(
            2,
            trusted_time=TimeInterval(180_001, 180_002),
            source_stale_deadline_ms=600_000,
        ).availability
        is IndexAvailabilityState.WARMUP
    )


def test_short_and_long_band_availability_are_independent_of_generation_publication() -> None:
    reducer = IndexMinuteReducer(5)
    reducer.start_continuous_coverage(0, generation=9)
    for sequence, timestamp in enumerate(
        (1, 60_000, 180_000, 240_000, 300_000, 360_000, 420_000),
        start=1,
    ):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    update = publish(reducer, lower_ms=420_001, sequence=20, generation=9)
    assert update.published_tail is not None
    assert update.published_tail.published_tail_last_minute_start_ms == 360_000

    short = reducer.current_tail(
        2,
        trusted_time=TimeInterval(420_001, 420_002),
        source_stale_deadline_ms=600_000,
    )
    long = reducer.current_tail(
        5,
        trusted_time=TimeInterval(420_001, 420_002),
        source_stale_deadline_ms=600_000,
    )
    assert short.availability is IndexAvailabilityState.AVAILABLE
    assert long.availability is IndexAvailabilityState.WINDOW_GAP


def test_direct_watermark_time_to_published_and_immediate_publish_have_exact_transitions() -> None:
    reducer = IndexMinuteReducer(3)
    reducer.start_continuous_coverage(0, generation=4)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    first = publish(reducer, lower_ms=180_001, sequence=10, generation=4)
    assert first.published_tail is not None
    assert first.phase is BaselinePublicationPhase.CURRENT

    watermark = reducer.publish_ready(
        trusted_time=TimeInterval(240_001, 240_002),
        source_stale_deadline_ms=600_000,
        generation=4,
        global_continuity_epoch=1,
        boundary=boundary(11, 110),
    )
    assert watermark.phase is BaselinePublicationPhase.WATERMARK_PENDING
    assert not watermark.published_advanced

    tick(reducer, 240_000, 12)
    reducer.seal_ready(240_001)
    sealed = reducer.publish_ready(
        trusted_time=TimeInterval(240_001, 240_002),
        source_stale_deadline_ms=600_000,
        generation=4,
        global_continuity_epoch=1,
        boundary=boundary(12, 120),
    )
    assert sealed.published_advanced
    assert sealed.previous_phase is BaselinePublicationPhase.WATERMARK_PENDING
    assert sealed.phase is BaselinePublicationPhase.CURRENT
    assert sealed.published_tail is not None
    assert sealed.published_tail.published_tail_last_minute_start_ms == 180_000

    immediate = IndexMinuteReducer(2)
    immediate.start_continuous_coverage(0, generation=5)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(immediate, timestamp, sequence)
        immediate.seal_ready(timestamp)
    direct = publish(immediate, lower_ms=180_001, sequence=10, generation=5)
    assert direct.published_advanced
    assert direct.previous_phase is BaselinePublicationPhase.CURRENT
    assert direct.phase is BaselinePublicationPhase.CURRENT


def test_both_proofs_crossing_a_missing_successor_is_window_gap_not_sticky_pending() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0, generation=6)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    first = publish(reducer, lower_ms=180_001, sequence=10, generation=6)
    assert first.published_tail is not None
    assert first.published_tail.published_tail_last_minute_start_ms == 120_000

    pending = reducer.publish_ready(
        trusted_time=TimeInterval(239_999, 240_001),
        source_stale_deadline_ms=600_000,
        generation=6,
        global_continuity_epoch=1,
        boundary=boundary(11, 110),
    )
    assert pending.phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING

    # Model a proven source minute hole after the prior immutable publication.
    reducer._working.pop(180_000)
    tick(reducer, 240_000, 12)
    reducer.seal_ready(240_001)
    missing = reducer.publish_ready(
        trusted_time=TimeInterval(240_001, 240_002),
        source_stale_deadline_ms=600_000,
        generation=6,
        global_continuity_epoch=1,
        boundary=boundary(12, 120),
    )
    state = reducer.current_tail(
        2,
        trusted_time=TimeInterval(240_001, 240_002),
        source_stale_deadline_ms=600_000,
    )

    assert missing.phase is BaselinePublicationPhase.CURRENT
    assert not missing.published_advanced
    assert state.availability is IndexAvailabilityState.WINDOW_GAP
    assert state.reason == "INDEX_WINDOW_GAP"


def test_detector_baseline_identity_is_only_the_exact_selected_close_tuple() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0, generation=8)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    publish(reducer, lower_ms=180_001, sequence=10, generation=8, epoch=1)
    first = reducer.current_tail(
        2,
        trusted_time=TimeInterval(180_001, 180_002),
        source_stale_deadline_ms=600_000,
    )

    reducer.invalidate_publication()
    publish(reducer, lower_ms=180_001, sequence=11, generation=8, epoch=2)
    rebound = reducer.current_tail(
        2,
        trusted_time=TimeInterval(180_001, 180_002),
        source_stale_deadline_ms=600_000,
    )

    assert first.published_tail is not None
    assert rebound.published_tail is not None
    assert first.published_tail.global_continuity_epoch == 1
    assert rebound.published_tail.global_continuity_epoch == 2
    assert first.closes == rebound.closes
    assert first.economic_identity == first.closes
    assert rebound.economic_identity == rebound.closes
    assert first.economic_identity == rebound.economic_identity


def test_multi_minute_catch_up_publishes_only_latest_exact_window_once() -> None:
    reducer = IndexMinuteReducer(3)
    reducer.start_continuous_coverage(0, generation=2)
    for sequence, timestamp in enumerate((1, 60_000, 120_000, 180_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    publish(reducer, lower_ms=180_001, sequence=10, generation=2)

    for sequence, timestamp in enumerate((240_000, 300_000, 360_000), start=11):
        tick(reducer, timestamp, sequence, price=100)
    update = publish(reducer, lower_ms=360_001, sequence=20, generation=2)
    assert update.published_advanced
    assert update.published_tail is not None
    assert update.published_tail.published_tail_last_minute_start_ms == 300_000
    assert update.published_minute_count == 3
    assert update.published_tail.closes[-1].price == Decimal(100)


def test_late_tick_and_timestamp_regression_clear_history_as_continuity_gap() -> None:
    reducer = IndexMinuteReducer(2)
    reducer.start_continuous_coverage(0, generation=1)
    for sequence, timestamp in enumerate((1, 60_000, 120_000), start=1):
        tick(reducer, timestamp, sequence)
        reducer.seal_ready(timestamp)
    with pytest.raises(ContinuityGap, match=r"regressed|sealed"):
        tick(reducer, 59_999, 4)
    assert reducer.sealed == ()
    assert (
        reducer.current_tail(
            1,
            trusted_time=TimeInterval(120_001, 120_002),
            source_stale_deadline_ms=600_000,
        ).availability
        is IndexAvailabilityState.CONTINUITY_GAP
    )

    reducer.start_continuous_coverage(180_000, generation=2)
    tick(reducer, 180_010, 5)
    with pytest.raises(ContinuityGap, match="regressed"):
        tick(reducer, 180_009, 6)
    assert reducer.sealed == ()

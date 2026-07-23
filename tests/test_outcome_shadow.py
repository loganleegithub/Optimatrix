from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from market_tape import CanonicalEvent, PlatformState, write_capture
from options_domain import ComboQuote
from radar_runtime.deribit_public import RadarProjection, build_decision_receipt, project_events
from radar_runtime.fixture import build_fixture_events
from radar_runtime.runtime_identity import runtime_source_identity
from shadow_engine import (
    CloseObservationStatus,
    ExitReason,
    OutcomeObservation,
    OutcomePathRole,
    OutcomeReceipt,
    ShadowAdmission,
    ShadowEntryReceipt,
    admit_shadow,
    evaluate_outcome,
)
from shadow_engine.truth import OutcomeStatus
from short_vol_radar import DecisionFrame, DecisionReceipt, RadarAction, RadarProjector


def _admission(
    tmp_path: Path, *, name: str = "entry"
) -> tuple[
    tuple[CanonicalEvent, ...],
    RadarProjection,
    PlatformState,
    DecisionReceipt,
    ShadowEntryReceipt,
]:
    events = build_fixture_events()
    projection = project_events(events)
    projector = RadarProjector()
    for event in events:
        projector.ingest(event)
    platform = projector.reducer.snapshot().platform_state
    assert platform is not None
    manifest = write_capture(tmp_path / name, events, complete=True)
    receipt = build_decision_receipt(
        manifest,
        projection,
        source_identity=runtime_source_identity(require_clean=False),
    )
    admission = admit_shadow(
        receipt,
        decision_receipt_digest=receipt.digest,
        frame=projection.frame,
        entry_platform_state=platform,
        fact_provenance="synthetic",
        outcome_runtime_git_commit_sha="a" * 40,
        outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
        outcome_runtime_source_digest="b" * 64,
    )
    assert admission.status is ShadowAdmission.ADMITTED
    assert admission.entry_receipt is not None
    return events, projection, platform, receipt, admission.entry_receipt


def _frame(
    entry: ShadowEntryReceipt,
    *,
    capture_seq: int,
    seconds: int,
    reference_price: Decimal | None = Decimal("100000"),
    close_debit: Decimal | None = Decimal("615"),
    depth: Decimal | None = Decimal("1"),
    wall_seconds: int | None = None,
    reference_future: bool = True,
) -> DecisionFrame:
    base = entry.frame
    market_at = (
        base.market_as_of + timedelta(seconds=seconds) if base.market_as_of is not None else None
    )
    short_name = entry.position.structure.short_leg.instrument_name
    long_name = entry.position.structure.long_leg.instrument_name
    long_bid = Decimal("100")
    short_ask = None if close_debit is None else long_bid + close_debit
    quotes = tuple(
        replace(
            quote,
            ask=(short_ask if quote.instrument_name == short_name else quote.ask),
            ask_amount=(depth if quote.instrument_name == short_name else quote.ask_amount),
            bid=(long_bid if quote.instrument_name == long_name else quote.bid),
            bid_amount=(depth if quote.instrument_name == long_name else quote.bid_amount),
            fresh=True,
            quote_age_ms=0,
            ticker_source_capture_seq=capture_seq,
            source_at=market_at or quote.source_at,
        )
        for quote in base.option_quotes
    )
    return replace(
        base,
        as_of_capture_seq=capture_seq,
        collector_as_of=base.collector_as_of
        + timedelta(seconds=seconds if wall_seconds is None else wall_seconds),
        collector_elapsed_ms=base.collector_elapsed_ms + seconds * 1_000,
        market_as_of=market_at,
        market_as_of_capture_seq=(capture_seq if market_at is not None else None),
        reference_source_capture_seq=(
            capture_seq if reference_future else base.reference_source_capture_seq
        ),
        reference_price=reference_price,
        index_price=reference_price,
        option_quotes=quotes,
        complete=True,
        completeness_reasons=(),
        source_capture_seqs=tuple(sorted({*base.source_capture_seqs, capture_seq})),
    )


def _platform(
    entry: ShadowEntryReceipt,
    *,
    frame_capture_seq: int,
    state: str = "OPEN",
    reconnect_capture_seq: int | None = None,
    stale_before_reconnect: bool = False,
) -> PlatformState:
    status_seq = frame_capture_seq - 1
    subscription_seq = frame_capture_seq - 2
    if stale_before_reconnect and reconnect_capture_seq is not None:
        status_seq = reconnect_capture_seq - 1
        subscription_seq = reconnect_capture_seq - 2
    locked = {"OPEN": False, "LOCKED": True, "UNKNOWN": None}[state]
    source_capture_seqs: tuple[int, ...] = (subscription_seq, status_seq)
    if state == "LOCKED":
        assert entry.entry_platform_state.status_capture_seq is not None
        status_capture_seq = entry.entry_platform_state.status_capture_seq
        source_capture_seqs = tuple(
            sorted({*entry.entry_platform_control_capture_seqs, status_seq})
        )
    else:
        status_capture_seq = status_seq
    return PlatformState(
        capture_seq=status_seq,
        source_at_ms=int(entry.frame.collector_as_of.timestamp() * 1_000),
        observed_elapsed_ms=entry.position.entry_elapsed_ms + 1,
        state=state,
        locked=locked,
        status_capture_seq=status_capture_seq,
        source_capture_seqs=source_capture_seqs,
    )


def _observation(
    entry: ShadowEntryReceipt,
    *,
    capture_seq: int,
    seconds: int,
    reference_price: Decimal | None = Decimal("100000"),
    close_debit: Decimal | None = Decimal("615"),
    depth: Decimal | None = Decimal("1"),
    platform_state: PlatformState | None = None,
    reconnect_capture_seq: int | None = None,
    reference_future: bool = True,
    wall_seconds: int | None = None,
) -> OutcomeObservation:
    frame = _frame(
        entry,
        capture_seq=capture_seq,
        seconds=seconds,
        reference_price=reference_price,
        close_debit=close_debit,
        depth=depth,
        wall_seconds=wall_seconds,
        reference_future=reference_future,
    )
    active_platform = (
        platform_state
        if platform_state is not None
        else _platform(entry, frame_capture_seq=capture_seq)
    )
    frame = replace(
        frame,
        platform_state=active_platform.state,
        platform_locked=active_platform.locked,
        source_capture_seqs=tuple(
            sorted(
                {
                    *frame.source_capture_seqs,
                    *active_platform.source_capture_seqs,
                    *((reconnect_capture_seq,) if reconnect_capture_seq is not None else ()),
                }
            )
        ),
    )
    return OutcomeObservation(
        frame=frame,
        platform_state=active_platform,
        reconnect_capture_seq=reconnect_capture_seq,
    )


def _evaluate(
    entry: ShadowEntryReceipt, observations: tuple[OutcomeObservation, ...]
) -> OutcomeReceipt:
    final_capture_seq = max(
        (item.frame.as_of_capture_seq for item in observations),
        default=entry.position.entry_capture_seq + 1,
    )
    return evaluate_outcome(
        entry,
        observations,
        entry_receipt_digest=entry.digest,
        fact_seal_digest="c" * 64,
        full_capture_digest="d" * 64,
        full_capture_manifest_digest="e" * 64,
        final_capture_seq=final_capture_seq,
    )


def test_admission_binds_exact_receipt_frame_policy_assessment_and_platform(
    tmp_path: Path,
) -> None:
    _events, projection, platform, receipt, entry = _admission(tmp_path)

    assert entry.decision_receipt_digest == receipt.digest
    assert entry.frame == projection.frame
    assert entry.assessment == receipt.evaluation.decision.assessment
    assert entry.position.structure.max_loss_usdc == entry.assessment.candidate.max_loss_usdc
    assert entry.entry_platform_control_capture_seqs == platform.source_capture_seqs
    assert entry.execution_evidence_class == "VISIBLE_EXECUTABLE_QUOTE_NOT_FILL"

    tampered = replace(receipt, capture_digest="0" * 64)
    with pytest.raises(ValueError, match="digest changed"):
        admit_shadow(
            tampered,
            decision_receipt_digest=receipt.digest,
            frame=projection.frame,
            entry_platform_state=platform,
            fact_provenance="synthetic",
            outcome_runtime_git_commit_sha="a" * 40,
            outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
            outcome_runtime_source_digest="b" * 64,
        )
    with pytest.raises(ValueError, match="frame, or Policy"):
        admit_shadow(
            receipt,
            decision_receipt_digest=receipt.digest,
            frame=replace(projection.frame, reference_price=Decimal("99999")),
            entry_platform_state=platform,
            fact_provenance="synthetic",
            outcome_runtime_git_commit_sha="a" * 40,
            outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
            outcome_runtime_source_digest="b" * 64,
        )

    unproved_open = replace(platform, status_capture_seq=None)
    with pytest.raises(ValueError, match="platform anchors"):
        admit_shadow(
            receipt,
            decision_receipt_digest=receipt.digest,
            frame=projection.frame,
            entry_platform_state=unproved_open,
            fact_provenance="synthetic",
            outcome_runtime_git_commit_sha="a" * 40,
            outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
            outcome_runtime_source_digest="b" * 64,
        )

    assert platform.status_capture_seq is not None
    status_without_subscription = replace(
        platform,
        source_capture_seqs=(platform.status_capture_seq,),
    )
    with pytest.raises(ValueError, match="platform anchors"):
        admit_shadow(
            receipt,
            decision_receipt_digest=receipt.digest,
            frame=projection.frame,
            entry_platform_state=status_without_subscription,
            fact_provenance="synthetic",
            outcome_runtime_git_commit_sha="a" * 40,
            outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
            outcome_runtime_source_digest="b" * 64,
        )

    unrelated_open = replace(
        platform,
        capture_seq=10,
        status_capture_seq=10,
        source_capture_seqs=(5, 10),
    )
    with pytest.raises(ValueError, match="platform anchors"):
        admit_shadow(
            receipt,
            decision_receipt_digest=receipt.digest,
            frame=projection.frame,
            entry_platform_state=unrelated_open,
            fact_provenance="synthetic",
            outcome_runtime_git_commit_sha="a" * 40,
            outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
            outcome_runtime_source_digest="b" * 64,
        )


def test_complete_non_candidate_is_no_entry_and_incomplete_is_unknown(tmp_path: Path) -> None:
    events, projection, platform, receipt, _entry = _admission(tmp_path)
    watch = replace(
        receipt.evaluation.decision,
        action=RadarAction.WATCH,
        selected_candidate_id=None,
        horizon_seconds=None,
        assessment=None,
        reason="COMPLETE_NO_CANDIDATE",
    )
    watch_receipt = replace(receipt, evaluation=replace(receipt.evaluation, decision=watch))
    no_entry = admit_shadow(
        watch_receipt,
        decision_receipt_digest=watch_receipt.digest,
        frame=projection.frame,
        entry_platform_state=platform,
        fact_provenance="synthetic",
        outcome_runtime_git_commit_sha="a" * 40,
        outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
        outcome_runtime_source_digest="b" * 64,
    )
    assert no_entry.status is ShadowAdmission.NO_ENTRY
    assert no_entry.entry_receipt is None

    incomplete_events = events[:132]
    incomplete_projection = project_events(incomplete_events)
    incomplete_manifest = write_capture(tmp_path / "incomplete", incomplete_events, complete=True)
    incomplete_receipt = build_decision_receipt(
        incomplete_manifest,
        incomplete_projection,
        source_identity=runtime_source_identity(require_clean=False),
    )
    unknown = admit_shadow(
        incomplete_receipt,
        decision_receipt_digest=incomplete_receipt.digest,
        frame=incomplete_projection.frame,
        entry_platform_state=platform,
        fact_provenance="synthetic",
        outcome_runtime_git_commit_sha="a" * 40,
        outcome_runtime_source_id="OPTIMATRIX_OUTCOME_RUNTIME_SOURCE",
        outcome_runtime_source_digest="b" * 64,
    )
    assert unknown.status is ShadowAdmission.UNKNOWN
    assert unknown.entry_receipt is None
    assert unknown.reasons == incomplete_projection.frame.completeness_reasons


@pytest.mark.parametrize(
    ("prices", "maximum_up", "maximum_down"),
    (
        ((Decimal("101000"), Decimal("102000")), Decimal("0.02"), Decimal("0")),
        ((Decimal("99000"), Decimal("98000")), Decimal("0"), Decimal("-0.02")),
        ((Decimal("100000"),), Decimal("0"), Decimal("0")),
    ),
)
def test_excursion_uses_entry_zero_baseline(
    tmp_path: Path,
    prices: tuple[Decimal, ...],
    maximum_up: Decimal,
    maximum_down: Decimal,
) -> None:
    *_unused, entry = _admission(tmp_path)
    observations = tuple(
        _observation(
            entry,
            capture_seq=entry.position.entry_capture_seq + 3 + index * 3,
            seconds=60 * (index + 1),
            reference_price=price,
            close_debit=None,
        )
        for index, price in enumerate(prices)
    )
    receipt = _evaluate(entry, observations)

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.observed_outcome.maximum_up_fraction == maximum_up
    assert receipt.observed_outcome.maximum_down_fraction == maximum_down
    assert receipt.observed_outcome.observed_executable_pnl_usdc is None


def test_no_future_reference_keeps_excursion_unknown(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=60,
        reference_future=False,
        close_debit=None,
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.observed_outcome.maximum_up_fraction is None
    assert receipt.observed_outcome.maximum_down_fraction is None
    assert receipt.actual_path.points[0].reference_price is None


@pytest.mark.parametrize(
    "invalid_reference",
    (Decimal("0"), Decimal("NaN"), Decimal("Infinity")),
)
def test_invalid_future_reference_cannot_drive_outcome_metrics(
    tmp_path: Path,
    invalid_reference: Decimal,
) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=entry.position.horizon_seconds,
        reference_price=invalid_reference,
        close_debit=Decimal("100"),
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.actual_path.points[0].reference_price is None
    assert receipt.observed_outcome.maximum_up_fraction is None
    assert receipt.observed_outcome.maximum_down_fraction is None
    assert receipt.observed_outcome.first_touch_capture_seq is None
    assert receipt.observed_outcome.max_loss_region is None


def test_executable_exit_ends_actual_path_and_quarantines_later_touch(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    profit = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=60,
        reference_price=Decimal("100000"),
        close_debit=Decimal("100"),
    )
    polluted = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 6,
        seconds=120,
        reference_price=Decimal("95000"),
        close_debit=Decimal("615"),
    )
    receipt = _evaluate(entry, (polluted, profit))

    assert receipt.outcome_status is OutcomeStatus.CLOSED
    assert receipt.observed_outcome.exit_reason is ExitReason.PROFIT_TARGET
    assert len(receipt.actual_path.points) == 1
    assert receipt.counterfactual_path is not None
    assert receipt.counterfactual_path.role is OutcomePathRole.POST_EXIT_COUNTERFACTUAL
    assert receipt.counterfactual_path.points == (receipt.counterfactual_path.points[0],)
    assert receipt.observed_outcome.first_touch_capture_seq is None
    assert receipt.observed_outcome.max_loss_region is False
    assert receipt.observed_outcome.maximum_down_fraction == Decimal("0")


def test_horizon_uses_monotonic_elapsed_not_wall_clock(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=entry.position.horizon_seconds,
        wall_seconds=-86_400,
        reference_price=Decimal("100000"),
        close_debit=Decimal("615"),
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.CLOSED
    assert receipt.observed_outcome.exit_reason is ExitReason.HORIZON
    assert receipt.observed_outcome.observed_exposure_seconds == entry.position.horizon_seconds
    assert receipt.actual_path.points[0].collector_as_of < entry.frame.collector_as_of


def test_same_point_exit_priority_is_profit_then_touch_then_horizon(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=entry.position.horizon_seconds,
        reference_price=Decimal("95000"),
        close_debit=Decimal("100"),
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.CLOSED
    assert receipt.observed_outcome.exit_reason is ExitReason.PROFIT_TARGET
    assert receipt.observed_outcome.first_touch_capture_seq == observation.frame.as_of_capture_seq


def test_entry_open_cannot_be_reused_but_future_barrier_can_close(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    frame = _frame(entry, capture_seq=frame_seq, seconds=60, close_debit=Decimal("100"))
    old_open = OutcomeObservation(
        frame=frame,
        platform_state=entry.entry_platform_state,
        reconnect_capture_seq=None,
    )
    unknown = _evaluate(entry, (old_open,))
    assert unknown.outcome_status is OutcomeStatus.UNKNOWN
    assert unknown.actual_path.points[0].close_observation_status is CloseObservationStatus.UNKNOWN
    assert (
        "FUTURE_PLATFORM_BARRIER_MISSING" in unknown.actual_path.points[0].close_observation_reasons
    )

    status_seq = frame_seq - 1
    status_without_subscription = PlatformState(
        capture_seq=status_seq,
        source_at_ms=int(frame.collector_as_of.timestamp() * 1_000),
        observed_elapsed_ms=frame.collector_elapsed_ms,
        state="OPEN",
        locked=False,
        status_capture_seq=status_seq,
        source_capture_seqs=(status_seq,),
    )
    unproved = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=60,
        close_debit=Decimal("100"),
        platform_state=status_without_subscription,
    )
    unproved_receipt = _evaluate(entry, (unproved,))
    assert unproved_receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert unproved_receipt.actual_path.points[0].close_observation_reasons == (
        "FUTURE_PLATFORM_BARRIER_MISSING",
    )

    future = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=60,
        close_debit=Decimal("100"),
    )
    closed = _evaluate(entry, (future,))
    assert closed.outcome_status is OutcomeStatus.CLOSED
    assert (
        closed.actual_path.points[0].close_observation_status is CloseObservationStatus.EXECUTABLE
    )
    assert all(
        item > entry.position.entry_capture_seq
        for item in closed.actual_path.points[0].platform_control_source_capture_seqs
    )

    assert future.platform_state is not None
    mismatched_platform = replace(future.platform_state, state="LOCKED", locked=True)
    with pytest.raises(ValueError, match="platform fact and Decision frame disagree"):
        replace(future, platform_state=mismatched_platform)


def test_future_explicit_reference_closure_is_known_unexitable(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    closed_reference_frame = replace(
        _frame(
            entry,
            capture_seq=frame_seq,
            seconds=entry.position.horizon_seconds,
            close_debit=None,
        ),
        reference_price=None,
        index_price=None,
        complete=False,
        completeness_reasons=("REFERENCE_NOT_OPEN",),
    )
    observation = OutcomeObservation(
        frame=closed_reference_frame,
        platform_state=entry.entry_platform_state,
        reconnect_capture_seq=None,
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.UNEXITABLE
    assert receipt.actual_path.points[0].close_observation_reasons == ("REFERENCE_NOT_OPEN",)
    assert receipt.actual_path.points[0].reference_source_capture_seq == frame_seq
    assert receipt.observed_outcome.exit_capture_seq is None
    assert receipt.observed_outcome.observed_executable_pnl_usdc is None


def test_reconnect_requires_new_future_subscription_status_barrier(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 8
    reconnect_seq = entry.position.entry_capture_seq + 5
    stale = _platform(
        entry,
        frame_capture_seq=frame_seq,
        reconnect_capture_seq=reconnect_seq,
        stale_before_reconnect=True,
    )
    observation = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=60,
        close_debit=Decimal("100"),
        platform_state=stale,
        reconnect_capture_seq=reconnect_seq,
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.actual_path.points[0].close_observation_reasons == (
        "POST_RECONNECT_PLATFORM_BARRIER_MISSING",
    )

    recovered_frame_seq = frame_seq + 5
    recovered = _observation(
        entry,
        capture_seq=recovered_frame_seq,
        seconds=120,
        close_debit=Decimal("100"),
        reconnect_capture_seq=reconnect_seq,
    )
    closed = _evaluate(entry, (recovered,))
    assert closed.outcome_status is OutcomeStatus.CLOSED
    assert all(
        item > reconnect_seq
        for item in closed.actual_path.points[0].platform_control_source_capture_seqs
    )


def test_nonclosed_suffix_remains_actual_after_horizon_without_counterfactual(
    tmp_path: Path,
) -> None:
    *_unused, entry = _admission(tmp_path)
    horizon = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=entry.position.horizon_seconds,
        close_debit=None,
    )
    later_actual = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 6,
        seconds=entry.position.horizon_seconds + 60,
        reference_price=Decimal("95000"),
        close_debit=Decimal("100"),
    )
    receipt = _evaluate(entry, (horizon, later_actual))

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert len(receipt.actual_path.points) == 2
    assert receipt.counterfactual_path is None
    assert receipt.observed_outcome.exit_capture_seq is None
    assert receipt.observed_outcome.first_touch_capture_seq == (
        later_actual.frame.as_of_capture_seq
    )

    forged = replace(
        receipt.observed_outcome,
        status=OutcomeStatus.CLOSED,
        exit_reason=ExitReason.PROFIT_TARGET,
        exit_capture_seq=later_actual.frame.as_of_capture_seq,
        evaluation_capture_seq=later_actual.frame.as_of_capture_seq,
        observed_exposure_seconds=entry.position.horizon_seconds + 60,
        observed_executable_close_cost_usdc=Decimal("1"),
        observed_close_fee_usdc=Decimal("1"),
        observed_executable_pnl_usdc=Decimal("999999"),
        unknown_reasons=(),
    )
    with pytest.raises(ValueError, match="derived semantics"):
        replace(receipt, observed_outcome=forged)


def test_locked_and_depth_shortfall_are_unexitable_with_null_pnl(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    locked = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        platform_state=_platform(entry, frame_capture_seq=frame_seq, state="LOCKED"),
    )
    locked_receipt = _evaluate(entry, (locked,))
    assert locked_receipt.outcome_status is OutcomeStatus.UNEXITABLE
    assert locked_receipt.observed_outcome.exit_capture_seq is None
    assert locked_receipt.observed_outcome.observed_executable_pnl_usdc is None
    assert locked.platform_state is not None
    assert locked_receipt.actual_path.points[0].platform_control_source_capture_seqs == (
        locked.platform_state.capture_seq,
    )

    depth = _observation(
        entry,
        capture_seq=frame_seq + 3,
        seconds=entry.position.horizon_seconds,
        depth=Decimal("0.01"),
    )
    depth_receipt = _evaluate(entry, (depth,))
    assert depth_receipt.outcome_status is OutcomeStatus.UNEXITABLE
    assert depth_receipt.actual_path.points[0].close_observation_reasons == (
        "VISIBLE_CLOSE_DEPTH_INSUFFICIENT",
    )
    assert depth_receipt.observed_outcome.observed_executable_pnl_usdc is None


def test_reconnect_invalidates_stale_lock_but_accepts_new_lock(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    reconnect_seq = entry.position.entry_capture_seq + 5
    frame_seq = entry.position.entry_capture_seq + 8
    stale_lock = _platform(
        entry,
        frame_capture_seq=entry.position.entry_capture_seq + 3,
        state="LOCKED",
    )
    stale = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        platform_state=stale_lock,
        reconnect_capture_seq=reconnect_seq,
    )
    stale_receipt = _evaluate(entry, (stale,))
    assert stale_receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert stale_receipt.actual_path.points[0].close_observation_reasons == (
        "POST_RECONNECT_PLATFORM_BARRIER_MISSING",
    )

    new_lock = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        platform_state=_platform(entry, frame_capture_seq=frame_seq, state="LOCKED"),
        reconnect_capture_seq=reconnect_seq,
    )
    new_lock_receipt = _evaluate(entry, (new_lock,))
    assert new_lock_receipt.outcome_status is OutcomeStatus.UNEXITABLE
    assert new_lock_receipt.actual_path.points[0].close_observation_reasons == ("PLATFORM_LOCKED",)


@pytest.mark.parametrize(
    "invalid_price",
    (Decimal("-1"), Decimal("NaN"), Decimal("Infinity")),
)
def test_invalid_leg_price_is_unknown_not_depth_unexitable(
    tmp_path: Path,
    invalid_price: Decimal,
) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    base = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        depth=Decimal("0.01"),
    )
    short_name = entry.position.structure.short_leg.instrument_name
    quotes = tuple(
        replace(quote, ask=invalid_price) if quote.instrument_name == short_name else quote
        for quote in base.frame.option_quotes
    )
    receipt = _evaluate(entry, (replace(base, frame=replace(base.frame, option_quotes=quotes)),))

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.actual_path.points[0].close_observation_reasons == (
        "EXECUTABLE_CLOSE_EVIDENCE_INCOMPLETE",
    )
    assert receipt.observed_outcome.observed_executable_pnl_usdc is None


def test_missing_quote_is_unknown_and_only_closed_has_observed_pnl(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    missing = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        close_debit=None,
    )
    unknown = _evaluate(entry, (missing,))
    assert unknown.outcome_status is OutcomeStatus.UNKNOWN
    assert unknown.observed_outcome.exit_capture_seq is None
    assert unknown.observed_outcome.observed_close_fee_usdc is None
    assert unknown.observed_outcome.observed_executable_pnl_usdc is None
    assert (
        unknown.observed_outcome.observed_executable_pnl_usdc
        != -entry.position.structure.max_loss_usdc
    )

    executable = _observation(
        entry,
        capture_seq=frame_seq + 3,
        seconds=60,
        close_debit=Decimal("100"),
    )
    closed = _evaluate(entry, (executable,))
    assert closed.outcome_status is OutcomeStatus.CLOSED
    assert closed.observed_outcome.observed_executable_close_cost_usdc is not None
    assert closed.observed_outcome.observed_close_fee_usdc is not None
    assert closed.observed_outcome.observed_executable_pnl_usdc is not None


def test_missing_combo_close_side_overrides_visible_leg_depth_shortfall(
    tmp_path: Path,
) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    base = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        depth=Decimal("0.01"),
    )
    combo = ComboQuote(
        combo_id="future-combo",
        short_instrument=entry.position.structure.short_leg.instrument_name,
        long_instrument=entry.position.structure.long_leg.instrument_name,
        bid=None,
        ask=None,
        bid_amount=Decimal("1"),
        ask_amount=Decimal("1"),
        quote_age_ms=0,
        fresh=True,
        valid=True,
        source_capture_seq=frame_seq,
    )
    observation = replace(
        base,
        frame=replace(base.frame, combo_quotes=(combo,)),
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.actual_path.points[0].close_observation_reasons == (
        "FUTURE_COMBO_CLOSE_SIDE_UNKNOWN",
    )
    assert receipt.observed_outcome.observed_executable_pnl_usdc is None


@pytest.mark.parametrize(
    ("quote_age_ms", "ask_amount"),
    ((-1, Decimal("1")), (0, Decimal("-1")), (0, Decimal("NaN"))),
)
def test_invalid_combo_evidence_is_unknown_not_error_or_unexitable(
    tmp_path: Path,
    quote_age_ms: int,
    ask_amount: Decimal,
) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    base = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=entry.position.horizon_seconds,
        depth=Decimal("0.01"),
    )
    combo = ComboQuote(
        combo_id="invalid-future-combo",
        short_instrument=entry.position.structure.short_leg.instrument_name,
        long_instrument=entry.position.structure.long_leg.instrument_name,
        bid=None,
        ask=Decimal("100"),
        bid_amount=Decimal("1"),
        ask_amount=ask_amount,
        quote_age_ms=quote_age_ms,
        fresh=True,
        valid=True,
        source_capture_seq=frame_seq,
    )
    receipt = _evaluate(
        entry,
        (replace(base, frame=replace(base.frame, combo_quotes=(combo,))),),
    )

    assert receipt.outcome_status is OutcomeStatus.UNKNOWN
    assert receipt.actual_path.points[0].close_observation_reasons == (
        "FUTURE_COMBO_EVIDENCE_INVALID",
    )
    assert receipt.observed_outcome.observed_executable_pnl_usdc is None


def test_standalone_future_combo_can_close_without_future_leg_ticks(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    frame_seq = entry.position.entry_capture_seq + 3
    base = _observation(
        entry,
        capture_seq=frame_seq,
        seconds=60,
        close_debit=None,
    )
    combo = ComboQuote(
        combo_id="future-combo",
        short_instrument=entry.position.structure.short_leg.instrument_name,
        long_instrument=entry.position.structure.long_leg.instrument_name,
        bid=None,
        ask=Decimal("100"),
        bid_amount=Decimal("1"),
        ask_amount=Decimal("1"),
        quote_age_ms=0,
        fresh=True,
        valid=True,
        source_capture_seq=frame_seq,
    )
    observation = replace(
        base,
        frame=replace(
            base.frame,
            option_quotes=entry.frame.option_quotes,
            combo_quotes=(combo,),
        ),
    )
    receipt = _evaluate(entry, (observation,))

    assert receipt.outcome_status is OutcomeStatus.CLOSED
    assert receipt.actual_path.points[0].close_execution_source == "ACTIVE_COMBO"
    assert receipt.actual_path.points[0].close_combo_id == combo.combo_id
    assert receipt.actual_path.points[0].quote_source_capture_seqs == (frame_seq,)
    assert receipt.actual_path.points[0].short_delta is None


def test_entry_digest_tamper_is_rejected_before_outcome(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=60,
    )
    with pytest.raises(ValueError, match="Entry receipt digest changed"):
        evaluate_outcome(
            replace(entry, outcome_runtime_source_digest="f" * 64),
            (observation,),
            entry_receipt_digest=entry.digest,
            fact_seal_digest="c" * 64,
            full_capture_digest="d" * 64,
            full_capture_manifest_digest="e" * 64,
            final_capture_seq=observation.frame.as_of_capture_seq,
        )

    with pytest.raises(ValueError, match="final sequence precedes Entry"):
        evaluate_outcome(
            entry,
            (),
            entry_receipt_digest=entry.digest,
            fact_seal_digest="c" * 64,
            full_capture_digest="d" * 64,
            full_capture_manifest_digest="e" * 64,
            final_capture_seq=-7,
        )


def test_point_and_receipt_aggregate_lineage_tamper_is_rejected(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    observation = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=60,
        close_debit=Decimal("100"),
    )
    receipt = _evaluate(entry, (observation,))

    with pytest.raises(ValueError, match="point aggregate lineage"):
        replace(receipt.actual_path.points[0], source_capture_seqs=())
    with pytest.raises(ValueError, match="receipt aggregate lineage"):
        replace(receipt, outcome_source_capture_seqs=())

    moved_path = replace(
        receipt.actual_path,
        entry_capture_seq=entry.position.entry_capture_seq - 1,
    )
    moved_observed = replace(
        receipt.observed_outcome,
        actual_path_digest=moved_path.digest,
    )
    with pytest.raises(ValueError, match="actual path identity"):
        replace(receipt, actual_path=moved_path, observed_outcome=moved_observed)


def test_exit_and_counterfactual_path_boundary_tamper_is_rejected(tmp_path: Path) -> None:
    *_unused, entry = _admission(tmp_path)
    executable = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 3,
        seconds=60,
        close_debit=Decimal("100"),
    )
    later = _observation(
        entry,
        capture_seq=entry.position.entry_capture_seq + 6,
        seconds=120,
        close_debit=Decimal("615"),
    )
    receipt = _evaluate(entry, (executable, later))
    assert receipt.counterfactual_path is not None
    exit_capture_seq = receipt.observed_outcome.exit_capture_seq
    assert exit_capture_seq is not None

    shortened_actual = replace(receipt.actual_path, points=())
    shortened_observed = replace(
        receipt.observed_outcome,
        actual_path_digest=shortened_actual.digest,
    )
    with pytest.raises(ValueError, match="exit and path boundary"):
        replace(
            receipt,
            actual_path=shortened_actual,
            observed_outcome=shortened_observed,
            outcome_source_capture_seqs=tuple(
                source
                for source in receipt.outcome_source_capture_seqs
                if source > exit_capture_seq
            ),
        )

    counter_at_exit = replace(
        receipt.counterfactual_path,
        points=(receipt.actual_path.points[-1],),
    )
    with pytest.raises(ValueError, match="exit and path boundary"):
        replace(
            receipt,
            counterfactual_path=counter_at_exit,
            counterfactual_path_digest=counter_at_exit.digest,
        )

    regressed_point = replace(
        receipt.counterfactual_path.points[0],
        observed_elapsed_ms=receipt.actual_path.points[-1].observed_elapsed_ms - 1,
    )
    regressed_counter = replace(receipt.counterfactual_path, points=(regressed_point,))
    with pytest.raises(ValueError, match="not causally ordered"):
        replace(
            receipt,
            counterfactual_path=regressed_counter,
            counterfactual_path_digest=regressed_counter.digest,
        )

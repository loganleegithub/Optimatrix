from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import cast

from radar_runtime.funnel import FunnelSnapshot, FunnelTracker
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    RadarFunnelEvaluation,
    RadarReducer,
)
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.detector import DetectorState


def _commit(causal_seq: int) -> CausalCommit:
    return CausalCommit(
        boundary=FactBoundary(1, causal_seq, 1_000 + causal_seq, causal_seq),
        cause=CausalCause.TIME_BOUNDARY,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )


def _reducer(
    *,
    causal_seq: int,
    evaluations: tuple[RadarFunnelEvaluation, ...] = (),
    episode: str | None = None,
    atomic_state: PublicAtomicQuoteState | None = None,
) -> RadarReducer:
    trackers: dict[str, object] = {}
    atomic_states: dict[str, PublicAtomicQuoteState] = {}
    if episode is not None:
        trackers["BTC-TEST"] = SimpleNamespace(
            episode_id=episode,
            detector_state=DetectorState.ANOMALY_ACTIVE,
        )
        if atomic_state is not None:
            atomic_states[episode] = atomic_state
    return cast(
        RadarReducer,
        SimpleNamespace(
            latest_funnel_causal_seq=causal_seq,
            latest_funnel_evaluations=evaluations,
            trackers=trackers,
            atomic_states=atomic_states,
        ),
    )


def _record(
    kind: str,
    *,
    episode: str | None = None,
    identity: str | None = None,
    payload: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    value: dict[str, object] = {
        "object_kind": kind,
        "payload": {
            **({"active_episode_identity": episode} if episode is not None else {}),
            **dict(payload or {}),
        },
    }
    if identity is not None:
        value["object_identity"] = identity
    return value


def _observe(
    tracker: FunnelTracker,
    *,
    causal_seq: int,
    evaluations: tuple[RadarFunnelEvaluation, ...] = (),
    episode: str | None = None,
    atomic_state: PublicAtomicQuoteState | None = None,
    records: Sequence[Mapping[str, object]] = (),
) -> FunnelSnapshot:
    commit = _commit(causal_seq)
    resolved_evaluations = (
        evaluations
        if evaluations or episode is None
        else (RadarFunnelEvaluation("BTC-TEST", True, None),)
    )
    tracker.observe(
        reducer=_reducer(
            causal_seq=causal_seq,
            evaluations=resolved_evaluations,
            episode=episode,
            atomic_state=atomic_state,
        ),
        commit=commit,
        new_shadow_records=records,
    )
    return tracker.snapshot()


def _stage(snapshot: FunnelSnapshot, name: str) -> Mapping[str, object]:
    return next(stage.as_object() for stage in snapshot.stages if stage.stage == name)


def test_funnel_reports_no_scope_without_inventing_a_later_blocker() -> None:
    snapshot = FunnelTracker().snapshot()

    assert snapshot.primary_blocker.stage == "APPLICABLE_MARKET_SCOPE"
    assert snapshot.primary_blocker.reason == "NO_APPLICABLE_MARKET_SCOPE_OBSERVED"


def test_funnel_counts_exact_radar_unknown_and_deduplicates_one_transaction() -> None:
    tracker = FunnelTracker()
    evaluations = (
        RadarFunnelEvaluation("KNOWN", True, None),
        RadarFunnelEvaluation("UNKNOWN", False, "OPTION_BOOK_UNKNOWN"),
    )
    snapshot = _observe(tracker, causal_seq=1, evaluations=evaluations)
    duplicate = _observe(tracker, causal_seq=1, evaluations=evaluations)

    assert _stage(snapshot, "APPLICABLE_MARKET_SCOPE")["observed_count"] == 2
    assert _stage(snapshot, "RADAR_KNOWN")["observed_count"] == 1
    assert _stage(snapshot, "RADAR_KNOWN")["blocker_counts"] == {"OPTION_BOOK_UNKNOWN": 1}
    assert duplicate == snapshot
    assert snapshot.primary_blocker.stage == "RADAR_KNOWN"
    assert snapshot.primary_blocker.reason == "OPTION_BOOK_UNKNOWN"


def test_funnel_reports_natural_no_anomaly_only_after_known_radar_evaluation() -> None:
    snapshot = _observe(
        FunnelTracker(),
        causal_seq=1,
        evaluations=(RadarFunnelEvaluation("KNOWN", True, None),),
    )

    assert snapshot.primary_blocker.stage == "ANOMALY_ACTIVE"
    assert snapshot.primary_blocker.reason == "NO_ANOMALY_ACTIVATION_OBSERVED"


def test_funnel_attributes_atomic_unknown_and_known_negative_states() -> None:
    episode = "episode-1"
    unknown = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.UNKNOWN,
    )
    known_negative = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.NO_ACTIVE_COMBO,
    )

    assert unknown.primary_blocker.stage == "STRUCTURE_REVIEWABLE"
    assert unknown.primary_blocker.reason == "ATOMIC_AVAILABILITY_UNKNOWN"
    assert known_negative.primary_blocker.stage == "PUBLIC_ATOMIC_QUOTE_AVAILABLE"
    assert known_negative.primary_blocker.reason == "NO_ACTIVE_COMBO"


def test_funnel_reports_the_earliest_material_loss_not_the_largest_later_fraction() -> None:
    tracker = FunnelTracker()
    snapshot = _observe(
        tracker,
        causal_seq=1,
        evaluations=(
            RadarFunnelEvaluation("KNOWN", True, None),
            RadarFunnelEvaluation("UNKNOWN", False, "OPTION_BOOK_UNKNOWN"),
        ),
        episode="episode-1",
        atomic_state=PublicAtomicQuoteState.UNKNOWN,
    )

    assert snapshot.primary_blocker.stage == "RADAR_KNOWN"
    assert snapshot.primary_blocker.reason == "OPTION_BOOK_UNKNOWN"


def test_funnel_attributes_underwriting_and_candidate_losses() -> None:
    episode = "episode-1"
    underwriting_unknown = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={
                    "availability": "UNKNOWN",
                    "unknown_reasons": ["COMBO_QUOTE_RECEIPT_UNKNOWN"],
                },
            ),
        ),
    )
    watch = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={"availability": "EVALUABLE", "unknown_reasons": []},
            ),
            _record(
                "UNDERWRITING_ACTION",
                episode=episode,
                payload={
                    "economic_action": "WATCH",
                    "decision_blockers": ["MINIMUM_NET_ENTRY_CREDIT"],
                },
            ),
        ),
    )

    assert underwriting_unknown.primary_blocker.stage == "UNDERWRITING_EVALUABLE"
    assert underwriting_unknown.primary_blocker.reason == "COMBO_QUOTE_RECEIPT_UNKNOWN"
    assert watch.primary_blocker.stage == "CANDIDATE"
    assert watch.primary_blocker.reason == "MINIMUM_NET_ENTRY_CREDIT"


def test_funnel_attributes_admission_and_pending_outcome() -> None:
    episode = "episode-1"
    candidate = "candidate-1"
    entry = "entry-1"
    admission = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={"availability": "EVALUABLE", "unknown_reasons": []},
            ),
            _record(
                "UNDERWRITING_ACTION",
                episode=episode,
                payload={"economic_action": "CANDIDATE", "decision_blockers": []},
            ),
            _record("CANDIDATE_ACTIVATION", episode=episode, identity=candidate),
            _record(
                "ADMISSION_ATTEMPT_TERMINAL",
                episode=episode,
                payload={
                    "candidate_identity": candidate,
                    "terminal_outcome": "UNKNOWN_CONSUMED",
                },
            ),
        ),
    )
    pending_outcome = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={"availability": "EVALUABLE", "unknown_reasons": []},
            ),
            _record(
                "UNDERWRITING_ACTION",
                episode=episode,
                payload={"economic_action": "CANDIDATE", "decision_blockers": []},
            ),
            _record("CANDIDATE_ACTIVATION", episode=episode, identity=candidate),
            _record("SHADOW_ENTRY", episode=episode, identity=entry),
        ),
    )

    assert admission.primary_blocker.stage == "SHADOW_CASE_OPENED"
    assert admission.primary_blocker.reason == "ADMISSION_UNKNOWN_CONSUMED"
    assert pending_outcome.primary_blocker.stage == "SHADOW_CASE_OUTCOME"
    assert pending_outcome.primary_blocker.reason == "OUTCOME_PENDING"


def test_funnel_complete_chain_has_no_material_blocker() -> None:
    episode = "episode-1"
    candidate = "candidate-1"
    entry = "entry-1"
    snapshot = _observe(
        FunnelTracker(),
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={"availability": "EVALUABLE", "unknown_reasons": []},
            ),
            _record(
                "UNDERWRITING_ACTION",
                episode=episode,
                payload={"economic_action": "CANDIDATE", "decision_blockers": []},
            ),
            _record("CANDIDATE_ACTIVATION", episode=episode, identity=candidate),
            _record("SHADOW_ENTRY", episode=episode, identity=entry),
            _record(
                "SHADOW_OUTCOME",
                payload={"shadow_entry_identity": entry},
            ),
        ),
    )

    assert snapshot.primary_blocker.stage == "NONE"
    assert snapshot.primary_blocker.reason == "NO_MATERIAL_BLOCKER_OBSERVED"

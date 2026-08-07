from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import cast

from market_monitor import IndexAvailabilityState
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
    index_availability: IndexAvailabilityState = IndexAvailabilityState.AVAILABLE,
    band_id: str = "band",
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
    results = {
        evaluation.instrument_name: SimpleNamespace(band_id=band_id) for evaluation in evaluations
    }
    return cast(
        RadarReducer,
        SimpleNamespace(
            latest_funnel_causal_seq=causal_seq,
            latest_funnel_evaluations=evaluations,
            trackers=trackers,
            atomic_states=atomic_states,
            results=results,
            policy=SimpleNamespace(
                tte_bands=(SimpleNamespace(band_id=band_id, lookbacks_minutes=(1,)),),
                runtime_limits=SimpleNamespace(index_history_source_stale_deadline_ms=900_000),
            ),
            clock=SimpleNamespace(interval_at=lambda _monotonic_ms: object()),
            index_history=SimpleNamespace(
                current_tail=lambda _return_count, **_kwargs: SimpleNamespace(
                    availability=index_availability
                )
            ),
        ),
    )


def _record(
    kind: str,
    *,
    episode: str | None = None,
    identity: str | None = None,
    payload: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    resolved_payload = dict(payload or {})
    if kind == "UNDERWRITING_AVAILABILITY_EVALUATION":
        resolved_payload = {
            "structure_reviewable": True,
            "component_state": "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
            "component_blockers": [],
            "component_book_counterfactual_evaluable": True,
            **resolved_payload,
        }
    value: dict[str, object] = {
        "object_kind": kind,
        "payload": {
            **({"active_episode_identity": episode} if episode is not None else {}),
            **resolved_payload,
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
    index_availability: IndexAvailabilityState = IndexAvailabilityState.AVAILABLE,
    band_id: str = "band",
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
            index_availability=index_availability,
            band_id=band_id,
        ),
        commit=commit,
        new_shadow_records=records,
    )
    return tracker.snapshot()


def _stage(snapshot: FunnelSnapshot, name: str) -> Mapping[str, object]:
    return next(stage.as_object() for stage in snapshot.stages if stage.stage == name)


def test_funnel_reports_no_post_warmup_scope_without_inventing_a_later_blocker() -> None:
    snapshot = FunnelTracker().snapshot()

    assert snapshot.primary_blocker.stage == "APPLICABLE_MARKET_SCOPE"
    assert snapshot.primary_blocker.reason == "NO_APPLICABLE_MARKET_SCOPE_OBSERVED"
    assert snapshot.radar_knownness.post_warmup.as_object()["radar_known_over_applicable"] == {
        "numerator": 0,
        "denominator": 0,
        "ratio": None,
    }


def test_selected_decision_research_funnel_is_separate_from_canonical_candidate_counts() -> None:
    tracker = FunnelTracker()
    selection = "selection-1"
    enrollment = "control-1"
    opened = _observe(
        tracker,
        causal_seq=1,
        records=(
            _record("UNDERWRITING_DECISION_BATCH_DESIGNATION"),
            _record(
                "SELECTED_UNDERWRITING_DECISION",
                identity=selection,
                payload={"economic_action": "ABSTAIN"},
            ),
            _record(
                "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
                payload={"terminal_outcome": "CONTROL_OPENED"},
            ),
            _record(
                "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
                identity=enrollment,
                payload={"selected_underwriting_decision_identity": selection},
            ),
        ),
    )

    assert _stage(opened, "CANDIDATE")["observed_count"] == 0
    assert _stage(opened, "SHADOW_CASE_OPENED")["observed_count"] == 0
    assert opened.decision_control_research.as_object() == {
        "unit": "PRE_OUTCOME_SELECTED_UNDERWRITING_DECISION",
        "activation_batch_count": 1,
        "selected_decision_count": 1,
        "decision_case_opened_count": 1,
        "decision_outcome_count": 0,
        "selected_action_counts": {"ABSTAIN": 1},
        "attempt_terminal_counts": {"CONTROL_OPENED": 1},
        "pending_counts": {
            "batch_without_selected_evaluable_decision": 0,
            "selected_without_case": 0,
            "case_without_outcome": 1,
        },
        "non_claims": [
            "NOT_THE_CANONICAL_CANDIDATE_FUNNEL",
            "NON_CANDIDATE_CASE_IS_NOT_A_TRADE",
            "DESCRIPTIVE_OUTCOME_NOT_CAUSAL_EFFECT",
        ],
    }

    complete = _observe(
        tracker,
        causal_seq=2,
        records=(
            _record(
                "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME",
                payload={"shadow_entry_identity": enrollment},
            ),
        ),
    )
    research = complete.decision_control_research.as_object()
    assert research["decision_outcome_count"] == 1
    assert research["pending_counts"] == {
        "batch_without_selected_evaluable_decision": 0,
        "selected_without_case": 0,
        "case_without_outcome": 0,
    }


def test_selected_candidate_reuses_admission_terminal_in_research_funnel() -> None:
    tracker = FunnelTracker()
    snapshot = _observe(
        tracker,
        causal_seq=1,
        records=(
            _record("UNDERWRITING_DECISION_BATCH_DESIGNATION"),
            _record(
                "SELECTED_UNDERWRITING_DECISION",
                identity="selection-1",
                payload={
                    "economic_action": "CANDIDATE",
                    "entry_refresh_attempt_kind": "CANDIDATE_ADMISSION",
                    "entry_refresh_owner_identity": "candidate-1",
                },
            ),
            _record(
                "ADMISSION_ATTEMPT_TERMINAL",
                payload={
                    "candidate_identity": "candidate-1",
                    "terminal_outcome": "ENTRY_EMITTED",
                },
            ),
        ),
    )

    assert snapshot.decision_control_research.attempt_terminal_counts == {"ENTRY_EMITTED": 1}
    assert tracker.retained_state_counts["selected_candidate_identities"] == 0


def test_funnel_separates_startup_warmup_from_steady_state_knownness() -> None:
    tracker = FunnelTracker()
    startup = _observe(
        tracker,
        causal_seq=1,
        evaluations=(
            RadarFunnelEvaluation("WARMUP", False, "INDEX_WARMUP"),
            RadarFunnelEvaluation("BOOK", False, "OPTION_BOOK_UNKNOWN"),
        ),
        index_availability=IndexAvailabilityState.WARMUP,
    )

    assert startup.primary_blocker.stage == "APPLICABLE_MARKET_SCOPE"
    startup_knownness = startup.radar_knownness.startup_warmup.as_object()
    assert startup_knownness["applicable_market_scope_count"] == 2
    assert startup_knownness["blocker_counts"] == {
        "INDEX_WARMUP": 1,
        "OPTION_BOOK_UNKNOWN": 1,
    }
    assert startup.radar_knownness.post_warmup.as_object()["applicable_market_scope_count"] == 0

    steady = _observe(
        tracker,
        causal_seq=2,
        evaluations=(
            RadarFunnelEvaluation("KNOWN", True, None),
            RadarFunnelEvaluation("BOOK", False, "OPTION_BOOK_UNKNOWN"),
        ),
        index_availability=IndexAvailabilityState.AVAILABLE,
    )

    post = steady.radar_knownness.post_warmup.as_object()
    assert post["radar_known_over_applicable"] == {
        "numerator": 1,
        "denominator": 2,
        "ratio": "0.5",
    }
    assert post["blocker_counts"] == {"OPTION_BOOK_UNKNOWN": 1}
    assert steady.primary_blocker.stage == "RADAR_KNOWN"
    assert steady.primary_blocker.reason == "OPTION_BOOK_UNKNOWN"
    assert steady.radar_knownness.warmed_band_ids == ("band",)


def test_funnel_counts_post_warmup_index_loss_as_a_steady_state_blocker() -> None:
    tracker = FunnelTracker()
    _observe(
        tracker,
        causal_seq=1,
        evaluations=(RadarFunnelEvaluation("KNOWN", True, None),),
        index_availability=IndexAvailabilityState.AVAILABLE,
    )
    snapshot = _observe(
        tracker,
        causal_seq=2,
        evaluations=(RadarFunnelEvaluation("STALE", False, "INDEX_SOURCE_STALE"),),
        index_availability=IndexAvailabilityState.SOURCE_STALE,
    )

    post = snapshot.radar_knownness.post_warmup.as_object()
    assert post["radar_known_over_applicable"] == {
        "numerator": 1,
        "denominator": 2,
        "ratio": "0.5",
    }
    assert post["blocker_counts"] == {"INDEX_SOURCE_STALE": 1}
    assert snapshot.primary_blocker.reason == "INDEX_SOURCE_STALE"


def test_funnel_keeps_rewarmup_visible_but_out_of_the_steady_denominator() -> None:
    tracker = FunnelTracker()
    _observe(
        tracker,
        causal_seq=1,
        evaluations=(RadarFunnelEvaluation("KNOWN", True, None),),
        index_availability=IndexAvailabilityState.AVAILABLE,
    )
    snapshot = _observe(
        tracker,
        causal_seq=2,
        evaluations=(RadarFunnelEvaluation("REWARM", False, "INDEX_WARMUP"),),
        index_availability=IndexAvailabilityState.WARMUP,
    )

    assert snapshot.radar_knownness.startup_warmup.as_object()["blocker_counts"] == {
        "INDEX_WARMUP": 1
    }
    assert snapshot.radar_knownness.post_warmup.as_object()["radar_known_over_applicable"] == {
        "numerator": 1,
        "denominator": 1,
        "ratio": "1",
    }
    assert snapshot.primary_blocker.stage == "ANOMALY_ACTIVE"
    assert snapshot.primary_blocker.reason == "NO_ANOMALY_ACTIVATION_OBSERVED"


def test_funnel_bounds_every_unrecognized_radar_unknown_reason() -> None:
    snapshot = _observe(
        FunnelTracker(),
        causal_seq=1,
        evaluations=(RadarFunnelEvaluation("UNKNOWN", False, "DYNAMIC_INSTRUMENT_12345"),),
    )

    assert snapshot.radar_knownness.post_warmup.as_object()["blocker_counts"] == {
        "OTHER_RADAR_UNKNOWN": 1
    }
    assert snapshot.primary_blocker.reason == "OTHER_RADAR_UNKNOWN"


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


def test_funnel_keeps_atomic_combo_state_as_a_parallel_diagnostic() -> None:
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

    assert unknown.primary_blocker.stage == "STRUCTURE_REVIEWABLE"
    assert unknown.primary_blocker.reason == "STRUCTURE_NOT_EVALUATED"
    assert unknown.atomic_combo_diagnostic_counts == {"UNKNOWN": 1}
    assert known_negative.primary_blocker.stage == "CANDIDATE"
    assert known_negative.primary_blocker.reason == "MINIMUM_NET_ENTRY_CREDIT"
    assert known_negative.atomic_combo_diagnostic_counts == {"NO_ACTIVE_COMBO": 1}


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
                    "unknown_reasons": ["COMPONENT_BOOK_SOURCE_UNKNOWN"],
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
    assert underwriting_unknown.primary_blocker.reason == "COMPONENT_BOOK_SOURCE_UNKNOWN"
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


def test_funnel_retires_completed_identity_state_across_many_cases() -> None:
    tracker = FunnelTracker()
    case_count = 1_000

    for index in range(1, case_count + 1):
        episode = f"episode-{index}"
        candidate = f"candidate-{index}"
        entry = f"entry-{index}"
        _observe(
            tracker,
            causal_seq=index,
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
                        "terminal_outcome": "ENTRY_EMITTED",
                    },
                ),
                _record("SHADOW_ENTRY", episode=episode, identity=entry),
                _record(
                    "SHADOW_OUTCOME",
                    payload={"shadow_entry_identity": entry},
                ),
            ),
        )

    snapshot = tracker.snapshot()
    assert tracker.retained_state_counts == {
        "episodes": 0,
        "candidate_identities": 0,
        "entry_identities": 0,
        "decision_case_identities": 0,
        "selected_candidate_identities": 0,
    }
    assert _stage(snapshot, "ANOMALY_ACTIVE")["observed_count"] == case_count
    assert _stage(snapshot, "SHADOW_CASE_OPENED")["observed_count"] == case_count
    assert _stage(snapshot, "SHADOW_CASE_OUTCOME")["observed_count"] == case_count
    assert snapshot.primary_blocker.stage == "NONE"


def test_funnel_normalizes_instrument_specific_blockers_to_bounded_categories() -> None:
    tracker = FunnelTracker()
    episode_count = 500

    for index in range(1, episode_count + 1):
        episode = f"episode-{index}"
        _observe(
            tracker,
            causal_seq=index * 2 - 1,
            episode=episode,
            atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
            records=(
                _record(
                    "UNDERWRITING_AVAILABILITY_EVALUATION",
                    episode=episode,
                    payload={
                        "availability": "UNKNOWN",
                        "unknown_reasons": [f"BTC-COMBO-{index}:BOOK_UNKNOWN"],
                    },
                ),
            ),
        )
        _observe(tracker, causal_seq=index * 2)

    snapshot = tracker.snapshot()
    blockers = _stage(snapshot, "UNDERWRITING_EVALUABLE")["blocker_counts"]
    assert blockers == {"BOOK_UNKNOWN": episode_count}
    assert tracker.retained_state_counts == {
        "episodes": 0,
        "candidate_identities": 0,
        "entry_identities": 0,
        "decision_case_identities": 0,
        "selected_candidate_identities": 0,
    }


def test_funnel_preserves_internal_symbolic_blocker_without_an_exhaustive_allowlist() -> None:
    tracker = FunnelTracker()
    episode = "episode-protective-leg"

    _observe(
        tracker,
        causal_seq=1,
        episode=episode,
        atomic_state=PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
        records=(
            _record(
                "UNDERWRITING_AVAILABILITY_EVALUATION",
                episode=episode,
                payload={
                    "availability": "UNKNOWN",
                    "unknown_reasons": ["PROTECTIVE_LEG_UNRESOLVED"],
                },
            ),
        ),
    )
    snapshot = _observe(tracker, causal_seq=2)

    assert _stage(snapshot, "UNDERWRITING_EVALUABLE")["blocker_counts"] == {
        "PROTECTIVE_LEG_UNRESOLVED": 1
    }

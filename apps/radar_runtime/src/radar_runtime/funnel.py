from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.detector import DetectorState

if TYPE_CHECKING:
    from radar_runtime.runtime import CausalCommit, RadarFunnelEvaluation, RadarReducer

FUNNEL_STAGE_ORDER = (
    "APPLICABLE_MARKET_SCOPE",
    "RADAR_KNOWN",
    "ANOMALY_ACTIVE",
    "STRUCTURE_REVIEWABLE",
    "PUBLIC_ATOMIC_QUOTE_AVAILABLE",
    "UNDERWRITING_EVALUABLE",
    "CANDIDATE",
    "SHADOW_CASE_OPENED",
    "SHADOW_CASE_OUTCOME",
)

_KNOWN_STRUCTURE_STATES = frozenset(
    {
        PublicAtomicQuoteState.NO_ACTIVE_COMBO.value,
        PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE.value,
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value,
    }
)


@dataclass(frozen=True)
class FunnelStageSnapshot:
    stage: str
    observed_count: int
    unit: str
    upstream_count: int | None
    upstream_unit: str | None
    blocker_counts: Mapping[str, int]

    def as_object(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "observed_count": self.observed_count,
            "unit": self.unit,
            "upstream_count": self.upstream_count,
            "upstream_unit": self.upstream_unit,
            "blocker_counts": dict(sorted(self.blocker_counts.items())),
        }


@dataclass(frozen=True)
class PrimaryFunnelBlocker:
    stage: str
    reason: str
    blocked_count: int
    upstream_count: int
    observed_count: int

    def as_object(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "reason": self.reason,
            "blocked_count": self.blocked_count,
            "upstream_count": self.upstream_count,
            "observed_count": self.observed_count,
        }


@dataclass(frozen=True)
class FunnelSnapshot:
    stages: tuple[FunnelStageSnapshot, ...]
    primary_blocker: PrimaryFunnelBlocker

    def as_object(self) -> dict[str, object]:
        return {
            "stages": [stage.as_object() for stage in self.stages],
            "primary_blocker": self.primary_blocker.as_object(),
            "non_claims": [
                "NON_DURABLE_RUNTIME_DIAGNOSTIC",
                "NO_POLICY_QUALITY_OR_PROFITABILITY_CLAIM",
                "NO_MARKET_FREQUENCY_CLAIM_OUTSIDE_THIS_RUNTIME",
            ],
        }


class FunnelTracker:
    """Bounded in-memory conversion tracker; no files, manifests, or acceptance state."""

    def __init__(self) -> None:
        self._last_radar_causal_seq = 0
        self._applicable_evaluation_count = 0
        self._radar_known_evaluation_count = 0
        self._radar_blockers: Counter[str] = Counter()
        self._anomaly_episodes: set[str] = set()
        self._atomic_states_by_episode: dict[str, set[str]] = {}
        self._latest_availability_by_episode: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._latest_action_by_episode: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._evaluable_episodes: set[str] = set()
        self._candidate_episodes: set[str] = set()
        self._candidate_episode_by_identity: dict[str, str] = {}
        self._admission_terminal_by_episode: dict[str, str] = {}
        self._entry_episode_by_identity: dict[str, str] = {}
        self._entry_episodes: set[str] = set()
        self._outcome_episodes: set[str] = set()

    def observe(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
        new_shadow_records: Sequence[Mapping[str, object]],
    ) -> None:
        self._observe_radar(reducer, commit)
        self._observe_shadow_records(new_shadow_records)

    def snapshot(self) -> FunnelSnapshot:
        anomaly_count = len(self._anomaly_episodes)
        structure_episodes = {
            episode
            for episode, states in self._atomic_states_by_episode.items()
            if states & _KNOWN_STRUCTURE_STATES
        }
        atomic_episodes = {
            episode
            for episode, states in self._atomic_states_by_episode.items()
            if PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value in states
        }
        structure_blockers = self._structure_blockers(structure_episodes)
        atomic_blockers = self._atomic_blockers(structure_episodes, atomic_episodes)
        underwriting_blockers = self._underwriting_blockers(atomic_episodes)
        candidate_blockers = self._candidate_blockers()
        case_blockers = self._case_blockers()
        outcome_blockers = Counter(
            {"OUTCOME_PENDING": len(self._entry_episodes - self._outcome_episodes)}
        )
        if outcome_blockers["OUTCOME_PENDING"] == 0:
            del outcome_blockers["OUTCOME_PENDING"]

        stages = (
            FunnelStageSnapshot(
                "APPLICABLE_MARKET_SCOPE",
                self._applicable_evaluation_count,
                "COUNTABLE_INSTRUMENT_EVALUATION",
                None,
                None,
                {},
            ),
            FunnelStageSnapshot(
                "RADAR_KNOWN",
                self._radar_known_evaluation_count,
                "KNOWN_INSTRUMENT_EVALUATION",
                self._applicable_evaluation_count,
                "COUNTABLE_INSTRUMENT_EVALUATION",
                self._radar_blockers,
            ),
            FunnelStageSnapshot(
                "ANOMALY_ACTIVE",
                anomaly_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._radar_known_evaluation_count,
                "KNOWN_INSTRUMENT_EVALUATION",
                (
                    {"NO_ANOMALY_ACTIVATION_OBSERVED": self._radar_known_evaluation_count}
                    if self._radar_known_evaluation_count > 0 and anomaly_count == 0
                    else {}
                ),
            ),
            FunnelStageSnapshot(
                "STRUCTURE_REVIEWABLE",
                len(structure_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                anomaly_count,
                "DISTINCT_ANOMALY_EPISODE",
                structure_blockers,
            ),
            FunnelStageSnapshot(
                "PUBLIC_ATOMIC_QUOTE_AVAILABLE",
                len(atomic_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                len(structure_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                atomic_blockers,
            ),
            FunnelStageSnapshot(
                "UNDERWRITING_EVALUABLE",
                len(self._evaluable_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                len(atomic_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                underwriting_blockers,
            ),
            FunnelStageSnapshot(
                "CANDIDATE",
                len(self._candidate_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                len(self._evaluable_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                candidate_blockers,
            ),
            FunnelStageSnapshot(
                "SHADOW_CASE_OPENED",
                len(self._entry_episodes),
                "DISTINCT_SHADOW_CASE",
                len(self._candidate_episodes),
                "DISTINCT_ANOMALY_EPISODE",
                case_blockers,
            ),
            FunnelStageSnapshot(
                "SHADOW_CASE_OUTCOME",
                len(self._outcome_episodes),
                "DISTINCT_SHADOW_CASE",
                len(self._entry_episodes),
                "DISTINCT_SHADOW_CASE",
                outcome_blockers,
            ),
        )
        return FunnelSnapshot(stages, self._primary_blocker(stages))

    def _observe_radar(self, reducer: RadarReducer, commit: CausalCommit) -> None:
        causal_seq = reducer.latest_funnel_causal_seq
        evaluations: tuple[RadarFunnelEvaluation, ...]
        if causal_seq <= self._last_radar_causal_seq:
            evaluations = ()
        elif causal_seq == commit.boundary.causal_seq:
            self._last_radar_causal_seq = causal_seq
            evaluations = reducer.latest_funnel_evaluations
        else:
            evaluations = ()
        for evaluation in evaluations:
            self._applicable_evaluation_count += 1
            if evaluation.known_evaluation:
                self._radar_known_evaluation_count += 1
            else:
                self._radar_blockers[evaluation.reason or "RADAR_UNKNOWN"] += 1

        for tracker in reducer.trackers.values():
            episode = tracker.episode_id
            if tracker.detector_state is not DetectorState.ANOMALY_ACTIVE or episode is None:
                continue
            self._anomaly_episodes.add(episode)
            state = reducer.atomic_states.get(episode)
            if state is not None:
                self._atomic_states_by_episode.setdefault(episode, set()).add(state.value)

    def _observe_shadow_records(
        self,
        records: Sequence[Mapping[str, object]],
    ) -> None:
        for value in records:
            kind = value.get("object_kind")
            payload = value.get("payload")
            if not isinstance(kind, str) or not isinstance(payload, Mapping):
                continue
            episode = _optional_string(payload.get("active_episode_identity"))
            if kind == "UNDERWRITING_AVAILABILITY_EVALUATION" and episode is not None:
                availability = _string_or(payload.get("availability"), "UNKNOWN")
                reasons = _string_tuple(payload.get("unknown_reasons"))
                self._latest_availability_by_episode[episode] = (availability, reasons)
                if availability == "EVALUABLE":
                    self._evaluable_episodes.add(episode)
            elif kind == "UNDERWRITING_ACTION" and episode is not None:
                action = _string_or(payload.get("economic_action"), "UNKNOWN")
                blockers = _string_tuple(payload.get("decision_blockers"))
                self._latest_action_by_episode[episode] = (action, blockers)
            elif kind == "CANDIDATE_ACTIVATION" and episode is not None:
                candidate = _optional_string(value.get("object_identity"))
                if candidate is not None:
                    self._candidate_episodes.add(episode)
                    self._candidate_episode_by_identity[candidate] = episode
            elif kind == "ADMISSION_ATTEMPT_TERMINAL":
                candidate = _optional_string(payload.get("candidate_identity"))
                outcome = _string_or(payload.get("terminal_outcome"), "UNKNOWN")
                terminal_episode = (
                    episode
                    if episode is not None
                    else self._candidate_episode_by_identity.get(candidate or "")
                )
                if terminal_episode is not None:
                    self._admission_terminal_by_episode[terminal_episode] = outcome
            elif kind == "SHADOW_ENTRY" and episode is not None:
                entry = _optional_string(value.get("object_identity"))
                if entry is not None:
                    self._entry_episodes.add(episode)
                    self._entry_episode_by_identity[entry] = episode
            elif kind == "SHADOW_OUTCOME":
                entry = _optional_string(payload.get("shadow_entry_identity"))
                outcome_episode = self._entry_episode_by_identity.get(entry or "")
                if outcome_episode is not None:
                    self._outcome_episodes.add(outcome_episode)

    def _structure_blockers(self, structure_episodes: set[str]) -> Counter[str]:
        blockers: Counter[str] = Counter()
        for episode in self._anomaly_episodes - structure_episodes:
            states = self._atomic_states_by_episode.get(episode, set())
            reason = (
                "ATOMIC_AVAILABILITY_UNKNOWN"
                if PublicAtomicQuoteState.UNKNOWN.value in states
                else "ATOMIC_AVAILABILITY_NOT_SETTLED"
            )
            blockers[reason] += 1
        return blockers

    def _atomic_blockers(
        self,
        structure_episodes: set[str],
        atomic_episodes: set[str],
    ) -> Counter[str]:
        blockers: Counter[str] = Counter()
        for episode in structure_episodes - atomic_episodes:
            states = self._atomic_states_by_episode.get(episode, set())
            if PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE.value in states:
                reason = PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE.value
            elif PublicAtomicQuoteState.NO_ACTIVE_COMBO.value in states:
                reason = PublicAtomicQuoteState.NO_ACTIVE_COMBO.value
            else:
                reason = "PUBLIC_ATOMIC_QUOTE_NOT_OBSERVED"
            blockers[reason] += 1
        return blockers

    def _underwriting_blockers(self, atomic_episodes: set[str]) -> Counter[str]:
        blockers: Counter[str] = Counter()
        for episode in atomic_episodes - self._evaluable_episodes:
            availability, reasons = self._latest_availability_by_episode.get(
                episode,
                ("NOT_EVALUATED", ()),
            )
            if reasons:
                blockers.update(reasons)
            else:
                blockers[f"UNDERWRITING_{availability}"] += 1
        return blockers

    def _candidate_blockers(self) -> Counter[str]:
        blockers: Counter[str] = Counter()
        for episode in self._evaluable_episodes - self._candidate_episodes:
            action, reasons = self._latest_action_by_episode.get(
                episode,
                ("NOT_EMITTED", ()),
            )
            if reasons:
                blockers.update(reasons)
            else:
                blockers[f"UNDERWRITING_ACTION_{action}"] += 1
        return blockers

    def _case_blockers(self) -> Counter[str]:
        blockers: Counter[str] = Counter()
        for episode in self._candidate_episodes - self._entry_episodes:
            outcome = self._admission_terminal_by_episode.get(episode)
            blockers[
                f"ADMISSION_{outcome}"
                if outcome is not None
                else "ADMISSION_PENDING_OR_NOT_REFRESHED"
            ] += 1
        return blockers

    @staticmethod
    def _primary_blocker(
        stages: tuple[FunnelStageSnapshot, ...],
    ) -> PrimaryFunnelBlocker:
        if stages[0].observed_count == 0:
            return PrimaryFunnelBlocker(
                "APPLICABLE_MARKET_SCOPE",
                "NO_APPLICABLE_MARKET_SCOPE_OBSERVED",
                0,
                0,
                0,
            )
        for stage in stages[1:]:
            upstream = stage.upstream_count
            if upstream is None or upstream <= 0:
                continue
            if stage.stage == "ANOMALY_ACTIVE":
                if stage.observed_count == 0:
                    return PrimaryFunnelBlocker(
                        stage.stage,
                        "NO_ANOMALY_ACTIVATION_OBSERVED",
                        upstream,
                        upstream,
                        0,
                    )
                continue
            blocked = max(0, upstream - stage.observed_count)
            if blocked <= 0:
                continue
            return PrimaryFunnelBlocker(
                stage.stage,
                _largest_reason(stage.blocker_counts),
                blocked,
                upstream,
                stage.observed_count,
            )
        return PrimaryFunnelBlocker("NONE", "NO_MATERIAL_BLOCKER_OBSERVED", 0, 0, 0)


def _largest_reason(values: Mapping[str, int]) -> str:
    positive = ((count, reason) for reason, count in values.items() if count > 0)
    try:
        _count, reason = max(positive, key=lambda item: (item[0], item[1]))
    except ValueError:
        return "UNATTRIBUTED_FUNNEL_LOSS"
    return reason


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)

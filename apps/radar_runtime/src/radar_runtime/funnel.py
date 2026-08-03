from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from market_monitor import ContinuityGap, IndexAvailabilityState
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.detector import DetectorState
from short_vol_radar.evidence import CoverageBlockingReason

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

_BOUNDED_INSTRUMENT_REASON_SUFFIXES = frozenset(
    {
        "AMOUNT_METADATA_UNKNOWN",
        "BOOK_UNKNOWN",
    }
)

_RADAR_UNKNOWN_REASON_ALIASES = {
    "INDEX_BASELINE_WARMUP": "INDEX_WARMUP",
    "INDEX_BASELINE_STALE": "INDEX_SOURCE_STALE",
    "INDEX_BASELINE_GAP": "INDEX_WINDOW_GAP",
}

_RADAR_UNKNOWN_REASON_CATEGORIES = frozenset(
    {
        *(item.value for item in CoverageBlockingReason if item is not CoverageBlockingReason.NONE),
        "OPTION_BOOK_UNKNOWN",
        "OPTION_AMOUNT_METADATA_UNKNOWN",
        "FORWARD_TICKER_UNKNOWN",
        "INVALID_FORWARD",
        "NUMERICAL_BOUNDARY_UNRESOLVED",
    }
)

_NUMERICAL_UNKNOWN_REASONS = frozenset(
    {
        "forward and strike must be finite and positive",
        "total volatility must be finite and non-negative",
        "price, forward, and strike must be finite and positive",
        "target option price is outside the finite formula domain",
        "total-volatility bracket overflowed",
        "target option price was not bracketed",
        "invalid total-volatility interval",
        "time interval must be strictly positive",
        "implied-volatility interval is not finite",
        "ratio denominator must be finite and positive",
        "binary64 model result is not finite",
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
class RadarKnownnessSlice:
    phase: str
    applicable_market_scope_count: int
    radar_known_count: int
    blocker_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.phase not in {"STARTUP_WARMUP", "POST_WARMUP"}:
            raise ValueError("Radar knownness phase is unsupported")
        if self.applicable_market_scope_count < 0 or self.radar_known_count < 0:
            raise ValueError("Radar knownness counts must be non-negative")
        if self.radar_known_count > self.applicable_market_scope_count:
            raise ValueError("Radar known count cannot exceed applicable scope")
        invalid_blocker = any(
            not isinstance(reason, str)
            or not reason
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            for reason, count in self.blocker_counts.items()
        )
        if invalid_blocker:
            raise ValueError("Radar blocker counts must have positive bounded members")
        unknown_count = self.applicable_market_scope_count - self.radar_known_count
        if sum(self.blocker_counts.values()) != unknown_count:
            raise ValueError("Every Radar UNKNOWN must have exactly one bounded blocker reason")

    def as_object(self) -> dict[str, object]:
        denominator = self.applicable_market_scope_count
        ratio = (
            None
            if denominator == 0
            else format(Decimal(self.radar_known_count) / Decimal(denominator), "f")
        )
        return {
            "phase": self.phase,
            "applicable_market_scope_count": denominator,
            "radar_known_count": self.radar_known_count,
            "radar_unknown_count": denominator - self.radar_known_count,
            "radar_known_over_applicable": {
                "numerator": self.radar_known_count,
                "denominator": denominator,
                "ratio": ratio,
            },
            "blocker_counts": dict(sorted(self.blocker_counts.items())),
        }


@dataclass(frozen=True)
class RadarKnownnessSnapshot:
    startup_warmup: RadarKnownnessSlice
    post_warmup: RadarKnownnessSlice
    warmed_band_ids: tuple[str, ...]

    def as_object(self) -> dict[str, object]:
        return {
            "warmup_gate": "PER_POLICY_TTE_BAND_INDEX_TAIL_AVAILABLE",
            "startup_warmup": self.startup_warmup.as_object(),
            "post_warmup": self.post_warmup.as_object(),
            "warmed_band_ids": list(self.warmed_band_ids),
        }


@dataclass(frozen=True)
class FunnelSnapshot:
    stages: tuple[FunnelStageSnapshot, ...]
    primary_blocker: PrimaryFunnelBlocker
    radar_knownness: RadarKnownnessSnapshot

    def as_object(self) -> dict[str, object]:
        return {
            "stages": [stage.as_object() for stage in self.stages],
            "primary_blocker": self.primary_blocker.as_object(),
            "radar_knownness": self.radar_knownness.as_object(),
            "non_claims": [
                "NON_DURABLE_RUNTIME_DIAGNOSTIC",
                "NO_POLICY_QUALITY_OR_PROFITABILITY_CLAIM",
                "NO_MARKET_FREQUENCY_CLAIM_OUTSIDE_THIS_RUNTIME",
            ],
        }


@dataclass
class _EpisodeState:
    atomic_states: set[str] = field(default_factory=set)
    availability: tuple[str, tuple[str, ...]] = ("NOT_EVALUATED", ())
    action: tuple[str, tuple[str, ...]] = ("NOT_EMITTED", ())
    structure_reviewable: bool = False
    atomic_available: bool = False
    underwriting_evaluable: bool = False
    candidate: bool = False
    case_opened: bool = False
    outcome: bool = False
    admission_terminal: str | None = None
    entry_identity: str | None = None


class FunnelTracker:
    """Cumulative scalar funnel counts plus only live/pending episode identities."""

    def __init__(self) -> None:
        self._last_radar_causal_seq = 0
        self._startup_applicable_evaluation_count = 0
        self._startup_radar_known_evaluation_count = 0
        self._startup_radar_blockers: Counter[str] = Counter()
        self._post_warmup_applicable_evaluation_count = 0
        self._post_warmup_radar_known_evaluation_count = 0
        self._post_warmup_radar_blockers: Counter[str] = Counter()
        self._warmed_band_ids: set[str] = set()

        self._anomaly_episode_count = 0
        self._structure_episode_count = 0
        self._atomic_episode_count = 0
        self._evaluable_episode_count = 0
        self._candidate_episode_count = 0
        self._case_opened_count = 0
        self._outcome_count = 0

        self._episodes: dict[str, _EpisodeState] = {}
        self._candidate_episode_by_identity: dict[str, str] = {}
        self._entry_episode_by_identity: dict[str, str] = {}
        self._finalized_blockers: dict[str, Counter[str]] = {
            stage: Counter() for stage in FUNNEL_STAGE_ORDER[3:]
        }

    @property
    def retained_state_counts(self) -> Mapping[str, int]:
        return {
            "episodes": len(self._episodes),
            "candidate_identities": len(self._candidate_episode_by_identity),
            "entry_identities": len(self._entry_episode_by_identity),
        }

    def observe(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
        new_shadow_records: Sequence[Mapping[str, object]],
    ) -> None:
        active_episodes = self._observe_radar(reducer, commit)
        self._observe_shadow_records(new_shadow_records)
        self._retire_inactive_episodes(active_episodes)

    def snapshot(self) -> FunnelSnapshot:
        blockers = {stage: Counter(values) for stage, values in self._finalized_blockers.items()}
        for state in self._episodes.values():
            stage, reason = self._current_loss(state)
            if stage is not None and reason is not None:
                blockers[stage][reason] += 1

        outcome_pending = self._case_opened_count - self._outcome_count
        if outcome_pending > 0:
            blockers["SHADOW_CASE_OUTCOME"]["OUTCOME_PENDING"] = outcome_pending

        stages = (
            FunnelStageSnapshot(
                "APPLICABLE_MARKET_SCOPE",
                self._post_warmup_applicable_evaluation_count,
                "POST_WARMUP_COUNTABLE_INSTRUMENT_EVALUATION",
                None,
                None,
                {},
            ),
            FunnelStageSnapshot(
                "RADAR_KNOWN",
                self._post_warmup_radar_known_evaluation_count,
                "POST_WARMUP_KNOWN_INSTRUMENT_EVALUATION",
                self._post_warmup_applicable_evaluation_count,
                "POST_WARMUP_COUNTABLE_INSTRUMENT_EVALUATION",
                self._post_warmup_radar_blockers,
            ),
            FunnelStageSnapshot(
                "ANOMALY_ACTIVE",
                self._anomaly_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._post_warmup_radar_known_evaluation_count,
                "POST_WARMUP_KNOWN_INSTRUMENT_EVALUATION",
                (
                    {
                        "NO_ANOMALY_ACTIVATION_OBSERVED": (
                            self._post_warmup_radar_known_evaluation_count
                        )
                    }
                    if self._post_warmup_radar_known_evaluation_count > 0
                    and self._anomaly_episode_count == 0
                    else {}
                ),
            ),
            FunnelStageSnapshot(
                "STRUCTURE_REVIEWABLE",
                self._structure_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._anomaly_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                blockers["STRUCTURE_REVIEWABLE"],
            ),
            FunnelStageSnapshot(
                "PUBLIC_ATOMIC_QUOTE_AVAILABLE",
                self._atomic_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._structure_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                blockers["PUBLIC_ATOMIC_QUOTE_AVAILABLE"],
            ),
            FunnelStageSnapshot(
                "UNDERWRITING_EVALUABLE",
                self._evaluable_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._atomic_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                blockers["UNDERWRITING_EVALUABLE"],
            ),
            FunnelStageSnapshot(
                "CANDIDATE",
                self._candidate_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                self._evaluable_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                blockers["CANDIDATE"],
            ),
            FunnelStageSnapshot(
                "SHADOW_CASE_OPENED",
                self._case_opened_count,
                "DISTINCT_SHADOW_CASE",
                self._candidate_episode_count,
                "DISTINCT_ANOMALY_EPISODE",
                blockers["SHADOW_CASE_OPENED"],
            ),
            FunnelStageSnapshot(
                "SHADOW_CASE_OUTCOME",
                self._outcome_count,
                "DISTINCT_SHADOW_CASE",
                self._case_opened_count,
                "DISTINCT_SHADOW_CASE",
                blockers["SHADOW_CASE_OUTCOME"],
            ),
        )
        knownness = RadarKnownnessSnapshot(
            startup_warmup=RadarKnownnessSlice(
                "STARTUP_WARMUP",
                self._startup_applicable_evaluation_count,
                self._startup_radar_known_evaluation_count,
                self._startup_radar_blockers,
            ),
            post_warmup=RadarKnownnessSlice(
                "POST_WARMUP",
                self._post_warmup_applicable_evaluation_count,
                self._post_warmup_radar_known_evaluation_count,
                self._post_warmup_radar_blockers,
            ),
            warmed_band_ids=tuple(sorted(self._warmed_band_ids)),
        )
        return FunnelSnapshot(stages, self._primary_blocker(stages), knownness)

    def _observe_radar(self, reducer: RadarReducer, commit: CausalCommit) -> set[str]:
        causal_seq = reducer.latest_funnel_causal_seq
        evaluations: tuple[RadarFunnelEvaluation, ...]
        if causal_seq <= self._last_radar_causal_seq:
            evaluations = ()
        elif causal_seq == commit.boundary.causal_seq:
            self._last_radar_causal_seq = causal_seq
            evaluations = reducer.latest_funnel_evaluations
        else:
            evaluations = ()

        availability_by_band: dict[str, IndexAvailabilityState] = {}
        for evaluation in evaluations:
            band_id, availability = _radar_baseline_availability(
                reducer,
                commit,
                evaluation,
                availability_by_band=availability_by_band,
            )
            post_warmup = self._is_post_warmup(band_id, availability)
            if post_warmup:
                self._post_warmup_applicable_evaluation_count += 1
                if evaluation.known_evaluation:
                    self._post_warmup_radar_known_evaluation_count += 1
                else:
                    self._post_warmup_radar_blockers[
                        _bounded_radar_unknown_reason(evaluation.reason)
                    ] += 1
            else:
                self._startup_applicable_evaluation_count += 1
                if evaluation.known_evaluation:
                    self._startup_radar_known_evaluation_count += 1
                else:
                    self._startup_radar_blockers[
                        _bounded_radar_unknown_reason(evaluation.reason)
                    ] += 1

        active: set[str] = set()
        for tracker in reducer.trackers.values():
            episode = tracker.episode_id
            if tracker.detector_state is not DetectorState.ANOMALY_ACTIVE or episode is None:
                continue
            active.add(episode)
            state = self._episodes.get(episode)
            if state is None:
                state = _EpisodeState()
                self._episodes[episode] = state
                self._anomaly_episode_count += 1
            atomic_state = reducer.atomic_states.get(episode)
            if atomic_state is None:
                continue
            state.atomic_states.add(atomic_state.value)
            if not state.structure_reviewable and state.atomic_states & _KNOWN_STRUCTURE_STATES:
                state.structure_reviewable = True
                self._structure_episode_count += 1
            if (
                not state.atomic_available
                and PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
                in state.atomic_states
            ):
                state.atomic_available = True
                self._atomic_episode_count += 1
        return active

    def _is_post_warmup(
        self,
        band_id: str,
        availability: IndexAvailabilityState,
    ) -> bool:
        if availability is IndexAvailabilityState.WARMUP:
            return False
        if availability is IndexAvailabilityState.AVAILABLE:
            self._warmed_band_ids.add(band_id)
            return True
        return band_id in self._warmed_band_ids

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
            if episode is not None:
                state = self._episodes.get(episode)
                if state is None:
                    state = _EpisodeState()
                    self._episodes[episode] = state
                    self._anomaly_episode_count += 1
            else:
                state = None

            if kind == "UNDERWRITING_AVAILABILITY_EVALUATION" and state is not None:
                availability = _string_or(payload.get("availability"), "UNKNOWN")
                reasons = _string_tuple(payload.get("unknown_reasons"))
                state.availability = (availability, reasons)
                if availability == "EVALUABLE" and not state.underwriting_evaluable:
                    state.underwriting_evaluable = True
                    self._evaluable_episode_count += 1
            elif kind == "UNDERWRITING_ACTION" and state is not None:
                state.action = (
                    _string_or(payload.get("economic_action"), "UNKNOWN"),
                    _string_tuple(payload.get("decision_blockers")),
                )
            elif kind == "CANDIDATE_ACTIVATION" and state is not None and episode is not None:
                candidate = _optional_string(value.get("object_identity"))
                if candidate is not None:
                    if not state.candidate:
                        state.candidate = True
                        self._candidate_episode_count += 1
                    self._candidate_episode_by_identity[candidate] = episode
            elif kind == "ADMISSION_ATTEMPT_TERMINAL":
                candidate = _optional_string(payload.get("candidate_identity"))
                terminal_episode = (
                    episode
                    if episode is not None
                    else self._candidate_episode_by_identity.get(candidate or "")
                )
                terminal_state = (
                    self._episodes.get(terminal_episode) if terminal_episode is not None else None
                )
                if terminal_state is not None:
                    terminal_state.admission_terminal = _string_or(
                        payload.get("terminal_outcome"),
                        "UNKNOWN",
                    )
                if candidate is not None:
                    self._candidate_episode_by_identity.pop(candidate, None)
            elif kind == "SHADOW_ENTRY" and state is not None and episode is not None:
                entry = _optional_string(value.get("object_identity"))
                if entry is not None:
                    if not state.case_opened:
                        state.case_opened = True
                        self._case_opened_count += 1
                    state.entry_identity = entry
                    self._entry_episode_by_identity[entry] = episode
            elif kind == "SHADOW_OUTCOME":
                entry = _optional_string(payload.get("shadow_entry_identity"))
                outcome_episode = self._entry_episode_by_identity.pop(entry or "", None)
                outcome_state = (
                    self._episodes.get(outcome_episode) if outcome_episode is not None else None
                )
                if (
                    outcome_episode is not None
                    and outcome_state is not None
                    and not outcome_state.outcome
                ):
                    outcome_state.outcome = True
                    self._outcome_count += 1
                    self._episodes.pop(outcome_episode, None)

    def _retire_inactive_episodes(self, active_episodes: set[str]) -> None:
        for episode, state in tuple(self._episodes.items()):
            if episode in active_episodes or (state.case_opened and not state.outcome):
                continue
            stage, reason = self._current_loss(state)
            if stage is not None and reason is not None:
                self._finalized_blockers[stage][reason] += 1
            self._episodes.pop(episode, None)
            for candidate, owning_episode in tuple(self._candidate_episode_by_identity.items()):
                if owning_episode == episode:
                    self._candidate_episode_by_identity.pop(candidate, None)
            if state.entry_identity is not None:
                self._entry_episode_by_identity.pop(state.entry_identity, None)

    @staticmethod
    def _current_loss(state: _EpisodeState) -> tuple[str | None, str | None]:
        if not state.structure_reviewable:
            reason = (
                "ATOMIC_AVAILABILITY_UNKNOWN"
                if PublicAtomicQuoteState.UNKNOWN.value in state.atomic_states
                else "ATOMIC_AVAILABILITY_NOT_SETTLED"
            )
            return "STRUCTURE_REVIEWABLE", reason
        if not state.atomic_available:
            if PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE.value in state.atomic_states:
                reason = PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE.value
            elif PublicAtomicQuoteState.NO_ACTIVE_COMBO.value in state.atomic_states:
                reason = PublicAtomicQuoteState.NO_ACTIVE_COMBO.value
            else:
                reason = "PUBLIC_ATOMIC_QUOTE_NOT_OBSERVED"
            return "PUBLIC_ATOMIC_QUOTE_AVAILABLE", reason
        if not state.underwriting_evaluable:
            availability, reasons = state.availability
            return (
                "UNDERWRITING_EVALUABLE",
                (
                    _bounded_blocker_reason(
                        reasons[0],
                        fallback="OTHER_UNDERWRITING_UNKNOWN",
                    )
                    if reasons
                    else f"UNDERWRITING_{availability}"
                ),
            )
        if not state.candidate:
            action, reasons = state.action
            return (
                "CANDIDATE",
                (
                    _bounded_blocker_reason(
                        reasons[0],
                        fallback="OTHER_UNDERWRITING_ACTION_BLOCKER",
                    )
                    if reasons
                    else f"UNDERWRITING_ACTION_{action}"
                ),
            )
        if not state.case_opened:
            outcome = state.admission_terminal
            return (
                "SHADOW_CASE_OPENED",
                f"ADMISSION_{outcome}"
                if outcome is not None
                else "ADMISSION_PENDING_OR_NOT_REFRESHED",
            )
        return None, None

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


def _radar_baseline_availability(
    reducer: RadarReducer,
    commit: CausalCommit,
    evaluation: RadarFunnelEvaluation,
    *,
    availability_by_band: dict[str, IndexAvailabilityState],
) -> tuple[str, IndexAvailabilityState]:
    result = reducer.results.get(evaluation.instrument_name)
    band_id = result.band_id if result is not None else None
    if not isinstance(band_id, str) or not band_id:
        raise RuntimeError("countable Radar funnel evaluation lacks its Policy band")
    cached = availability_by_band.get(band_id)
    if cached is not None:
        return band_id, cached
    band = next((item for item in reducer.policy.tte_bands if item.band_id == band_id), None)
    if band is None:
        raise RuntimeError("Radar funnel evaluation references an unknown Policy band")
    clock = reducer.clock
    if clock is None:
        raise RuntimeError("countable Radar funnel evaluation lacks trusted time")
    try:
        trusted_time = clock.interval_at(commit.boundary.received_monotonic_ms)
    except (ContinuityGap, ValueError) as exc:
        raise RuntimeError("countable Radar funnel evaluation cannot recover trusted time") from exc
    baseline = reducer.index.current_tail(
        max(band.lookbacks_minutes),
        trusted_time=trusted_time,
        source_stale_deadline_ms=reducer.policy.runtime_limits.index_source_stale_deadline_ms,
    )
    availability_by_band[band_id] = baseline.availability
    return band_id, baseline.availability


def _largest_reason(values: Mapping[str, int]) -> str:
    positive = ((count, reason) for reason, count in values.items() if count > 0)
    try:
        _count, reason = max(positive, key=lambda item: (item[0], item[1]))
    except ValueError:
        return "UNATTRIBUTED_FUNNEL_LOSS"
    return reason


def _bounded_radar_unknown_reason(value: str | None) -> str:
    if value is None:
        return "OTHER_RADAR_UNKNOWN"
    normalized = _RADAR_UNKNOWN_REASON_ALIASES.get(value, value)
    if normalized in _RADAR_UNKNOWN_REASON_CATEGORIES:
        return normalized
    if normalized in _NUMERICAL_UNKNOWN_REASONS:
        return "NUMERICAL_UNKNOWN"
    suffix = normalized.rsplit(":", 1)[-1]
    if suffix == "BOOK_UNKNOWN":
        return "OPTION_BOOK_UNKNOWN"
    if suffix == "AMOUNT_METADATA_UNKNOWN":
        return "OPTION_AMOUNT_METADATA_UNKNOWN"
    if normalized.startswith("INDEX_"):
        return "OTHER_INDEX_UNKNOWN"
    if normalized.startswith(("TICKER_", "FORWARD_")):
        return "OTHER_TICKER_UNKNOWN"
    if normalized.startswith(("OPTION_LIFECYCLE_", "OPTION_METADATA_", "OPTION_SNAPSHOT_")):
        return CoverageBlockingReason.OPTION_LIFECYCLE_UNAVAILABLE.value
    if normalized.startswith("OPTION_"):
        return "OTHER_OPTION_UNKNOWN"
    if normalized.startswith(
        (
            "CLOCK_",
            "SESSION_",
            "REMOTE_",
            "TRANSPORT_",
            "PLATFORM_",
            "PROTOCOL_",
            "INGRESS_",
            "QUEUE_",
        )
    ):
        return "OTHER_RUNTIME_UNKNOWN"
    return "OTHER_RADAR_UNKNOWN"


def _bounded_blocker_reason(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    if value.isascii() and value.isidentifier() and value == value.upper():
        return value
    suffix = value.rsplit(":", 1)[-1]
    if suffix in _BOUNDED_INSTRUMENT_REASON_SUFFIXES:
        return suffix
    return fallback


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from market_monitor import TimeInterval

from short_vol_radar.black import DecimalInterval
from short_vol_radar.policy import OptionRule


class DetectorState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NO_ANOMALY = "NO_ANOMALY"
    ANOMALY_ACTIVE = "ANOMALY_ACTIVE"


class TrackerState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ARMED = "ARMED"
    ACTIVE = "ACTIVE"
    CLEARING = "CLEARING"
    BAND_SUSPENDED = "BAND_SUSPENDED"


class DetectorCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class AggregateApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"


class EpisodeEndReason(StrEnum):
    CLEAR = "CLEAR"
    KNOWN_INELIGIBLE = "KNOWN_INELIGIBLE"
    OUT_OF_BASELINE_SCOPE = "OUT_OF_BASELINE_SCOPE"
    MEMBERSHIP_LOSS = "MEMBERSHIP_LOSS"
    UNKNOWN_DETECTOR = "UNKNOWN_DETECTOR"
    UNKNOWN_AT_GAP = "UNKNOWN_AT_GAP"
    CENSORED_AT_STOP = "CENSORED_AT_STOP"


class ObservationSignal(StrEnum):
    ACTIVATE = "ACTIVATE"
    CLEAR = "CLEAR"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class DetectorObservation:
    causal_seq: int
    trusted_time: TimeInterval
    band_id: str
    richness: DecimalInterval


@dataclass(frozen=True)
class EpisodeEnd:
    episode_id: str
    reason: EpisodeEndReason
    detail: str | None
    end_causal_seq: int
    activation_band_id: str


@dataclass(frozen=True)
class TrackerTransition:
    activated_episode_id: str | None = None
    ended_episode: EpisodeEnd | None = None
    state_changed: bool = False


@dataclass(frozen=True)
class AggregateDetectorResult:
    applicability: AggregateApplicability
    state: DetectorState | None
    coverage: DetectorCoverage | None
    instrument_count: int
    unknown_instrument_count: int


class NumericalBoundaryUnresolved(ValueError):
    """A conservative interval spans a configured decision boundary."""


class EpisodeTracker:
    def __init__(
        self, *, runtime_identity: str, policy_identity: str, instrument_name: str
    ) -> None:
        self.runtime_identity = runtime_identity
        self.policy_identity = policy_identity
        self.instrument_name = instrument_name
        self.state = TrackerState.UNKNOWN
        self.episode_id: str | None = None
        self.activation_band_id: str | None = None
        self.activation_causal_seq: int | None = None
        self._activation_count = 0
        self._clear_count = 0
        self._last_activation_interval: TimeInterval | None = None
        self._last_clear_interval: TimeInterval | None = None

    @property
    def detector_state(self) -> DetectorState:
        if self.state in {TrackerState.ACTIVE, TrackerState.CLEARING}:
            return DetectorState.ANOMALY_ACTIVE
        if self.state is TrackerState.ARMED:
            return DetectorState.NO_ANOMALY
        return DetectorState.UNKNOWN

    def observe(self, observation: DetectorObservation, rule: OptionRule) -> TrackerTransition:
        signal = classify_observation(observation.richness, rule)
        previous_state = self.state
        if self.state is TrackerState.UNKNOWN:
            self.state = TrackerState.ARMED
        elif self.state is TrackerState.BAND_SUSPENDED:
            self.state = TrackerState.ACTIVE if self.episode_id is not None else TrackerState.ARMED
        if self.state is TrackerState.ARMED:
            if signal is ObservationSignal.ACTIVATE:
                if _separated(
                    self._last_activation_interval,
                    observation.trusted_time,
                    rule.minimum_separation_ms,
                ):
                    self._activation_count += 1
                    self._last_activation_interval = observation.trusted_time
                if self._activation_count >= rule.activation_observation_count:
                    episode_id = self._activate(observation)
                    return TrackerTransition(
                        activated_episode_id=episode_id,
                        state_changed=True,
                    )
            else:
                self._reset_activation()
        else:
            if signal is ObservationSignal.CLEAR:
                if _separated(
                    self._last_clear_interval,
                    observation.trusted_time,
                    rule.minimum_separation_ms,
                ):
                    self._clear_count += 1
                    self._last_clear_interval = observation.trusted_time
                self.state = TrackerState.CLEARING
                if self._clear_count >= rule.clear_observation_count:
                    ended = self._end(
                        reason=EpisodeEndReason.CLEAR,
                        detail=None,
                        causal_seq=observation.causal_seq,
                        next_state=TrackerState.ARMED,
                    )
                    return TrackerTransition(ended_episode=ended, state_changed=True)
            else:
                self._reset_clear()
                self.state = TrackerState.ACTIVE
        return TrackerTransition(state_changed=self.state is not previous_state)

    def unknown(
        self, *, reason: str, causal_seq: int, continuity_gap: bool = False
    ) -> TrackerTransition:
        previous_state = self.state
        ended = None
        if self.episode_id is not None:
            ended = self._end(
                reason=(
                    EpisodeEndReason.UNKNOWN_AT_GAP
                    if continuity_gap
                    else EpisodeEndReason.UNKNOWN_DETECTOR
                ),
                detail=reason,
                causal_seq=causal_seq,
                next_state=TrackerState.UNKNOWN,
            )
        else:
            self.state = TrackerState.UNKNOWN
            self._reset_counts()
        return TrackerTransition(
            ended_episode=ended, state_changed=self.state is not previous_state
        )

    def known_ineligible(self, *, reason: str, causal_seq: int) -> TrackerTransition:
        previous_state = self.state
        ended = None
        if self.episode_id is not None:
            ended = self._end(
                EpisodeEndReason.KNOWN_INELIGIBLE,
                reason,
                causal_seq,
                TrackerState.ARMED,
            )
        else:
            self.state = TrackerState.ARMED
            self._reset_counts()
        return TrackerTransition(
            ended_episode=ended, state_changed=self.state is not previous_state
        )

    def suspend_for_band_boundary(self) -> TrackerTransition:
        previous_state = self.state
        self.state = TrackerState.BAND_SUSPENDED
        self._reset_counts()
        return TrackerTransition(state_changed=self.state is not previous_state)

    def resume_after_band_boundary(self) -> TrackerTransition:
        previous_state = self.state
        self.state = TrackerState.ACTIVE if self.episode_id is not None else TrackerState.ARMED
        self._reset_counts()
        return TrackerTransition(state_changed=self.state is not previous_state)

    def out_of_baseline_scope(self, *, causal_seq: int) -> TrackerTransition:
        previous_state = self.state
        ended = None
        if self.episode_id is not None:
            ended = self._end(
                EpisodeEndReason.OUT_OF_BASELINE_SCOPE,
                None,
                causal_seq,
                TrackerState.UNKNOWN,
            )
        else:
            self.state = TrackerState.UNKNOWN
            self._reset_counts()
        return TrackerTransition(
            ended_episode=ended, state_changed=self.state is not previous_state
        )

    def membership_loss(self, *, causal_seq: int) -> TrackerTransition:
        previous_state = self.state
        ended = None
        if self.episode_id is not None:
            ended = self._end(
                EpisodeEndReason.MEMBERSHIP_LOSS,
                None,
                causal_seq,
                TrackerState.UNKNOWN,
            )
        else:
            self.state = TrackerState.UNKNOWN
            self._reset_counts()
        return TrackerTransition(
            ended_episode=ended, state_changed=self.state is not previous_state
        )

    def stop(self, *, causal_seq: int) -> TrackerTransition:
        if self.episode_id is None:
            return TrackerTransition()
        return TrackerTransition(
            ended_episode=self._end(
                EpisodeEndReason.CENSORED_AT_STOP,
                None,
                causal_seq,
                TrackerState.UNKNOWN,
            ),
            state_changed=True,
        )

    def _activate(self, observation: DetectorObservation) -> str:
        self.activation_causal_seq = observation.causal_seq
        self.activation_band_id = observation.band_id
        self.episode_id = (
            f"{self.runtime_identity}:{self.policy_identity}:"
            f"{self.instrument_name}:{observation.causal_seq}"
        )
        self.state = TrackerState.ACTIVE
        self._reset_counts()
        return self.episode_id

    def _end(
        self,
        reason: EpisodeEndReason,
        detail: str | None,
        causal_seq: int,
        next_state: TrackerState,
    ) -> EpisodeEnd:
        if self.episode_id is None or self.activation_band_id is None:
            raise RuntimeError("cannot end a missing episode")
        ended = EpisodeEnd(
            episode_id=self.episode_id,
            reason=reason,
            detail=detail,
            end_causal_seq=causal_seq,
            activation_band_id=self.activation_band_id,
        )
        self.episode_id = None
        self.activation_band_id = None
        self.activation_causal_seq = None
        self.state = next_state
        self._reset_counts()
        return ended

    def _reset_activation(self) -> None:
        self._activation_count = 0
        self._last_activation_interval = None

    def _reset_clear(self) -> None:
        self._clear_count = 0
        self._last_clear_interval = None

    def _reset_counts(self) -> None:
        self._reset_activation()
        self._reset_clear()


def classify_observation(interval: DecimalInterval, rule: OptionRule) -> ObservationSignal:
    if interval.lower >= rule.activation_ratio:
        return ObservationSignal.ACTIVATE
    if interval.upper <= rule.clear_ratio:
        return ObservationSignal.CLEAR
    if interval.lower > rule.clear_ratio and interval.upper < rule.activation_ratio:
        return ObservationSignal.NEUTRAL
    raise NumericalBoundaryUnresolved("richness interval spans activation or clear boundary")


def delta_is_eligible(interval: DecimalInterval, rule: OptionRule) -> bool:
    absolute_candidates = tuple(abs(value) for value in (interval.lower, interval.upper))
    absolute = DecimalInterval(min(absolute_candidates), max(absolute_candidates))
    if absolute.lower >= rule.abs_delta_min and absolute.upper <= rule.abs_delta_max:
        return True
    if absolute.upper < rule.abs_delta_min or absolute.lower > rule.abs_delta_max:
        return False
    raise NumericalBoundaryUnresolved("Delta interval spans an eligibility boundary")


def aggregate_detector(
    states: tuple[DetectorState, ...],
    *,
    catalog_complete: bool,
    has_applicable_scope: bool,
) -> AggregateDetectorResult:
    if not has_applicable_scope:
        return AggregateDetectorResult(
            applicability=AggregateApplicability.NO_APPLICABLE_SCOPE,
            state=None,
            coverage=None,
            instrument_count=0,
            unknown_instrument_count=0,
        )
    unknown_count = states.count(DetectorState.UNKNOWN)
    if DetectorState.ANOMALY_ACTIVE in states:
        return AggregateDetectorResult(
            AggregateApplicability.APPLICABLE,
            DetectorState.ANOMALY_ACTIVE,
            DetectorCoverage.DEGRADED
            if unknown_count or not catalog_complete
            else DetectorCoverage.COMPLETE,
            len(states),
            unknown_count,
        )
    if catalog_complete and states and unknown_count == 0:
        return AggregateDetectorResult(
            AggregateApplicability.APPLICABLE,
            DetectorState.NO_ANOMALY,
            DetectorCoverage.COMPLETE,
            len(states),
            0,
        )
    return AggregateDetectorResult(
        AggregateApplicability.APPLICABLE,
        DetectorState.UNKNOWN,
        DetectorCoverage.UNKNOWN,
        len(states),
        unknown_count,
    )


def _separated(
    previous: TimeInterval | None,
    current: TimeInterval,
    minimum_separation_ms: int,
) -> bool:
    if previous is None:
        return True
    return current.lower_ms - previous.upper_ms >= minimum_separation_ms

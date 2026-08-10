from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from market_monitor import TimeInterval

from short_vol_radar.black import DecimalInterval
from short_vol_radar.policy import OptionRule, ScoreModel
from short_vol_radar.score import (
    LeaderCoverage,
    RadarBucketKey,
    RadarScorePacket,
    RadarScoreResult,
    ScoreBand,
)


class BucketEpisodeState(StrEnum):
    IDLE = "IDLE"
    CONFIRMING = "CONFIRMING"
    ACTIVE = "ACTIVE"


class BucketEpisodeEndReason(StrEnum):
    LEADER_CHANGE = "LEADER_CHANGE"
    SCORE_BAND_CHANGE = "SCORE_BAND_CHANGE"
    CORE_UNKNOWN = "CORE_UNKNOWN"
    SCOPE_LOSS = "SCOPE_LOSS"
    STOP = "STOP"


class BucketConfirmationResetReason(StrEnum):
    LEADER_CHANGE = "LEADER_CHANGE"
    SCORE_BAND_CHANGE = "SCORE_BAND_CHANGE"
    CORE_UNKNOWN = "CORE_UNKNOWN"
    SCOPE_LOSS = "SCOPE_LOSS"
    CLUE_INELIGIBLE = "CLUE_INELIGIBLE"
    STOP = "STOP"


@dataclass(frozen=True)
class BucketLeaderCandidate:
    bucket_key: RadarBucketKey
    instrument_name: str
    strike: Decimal
    score_result: RadarScoreResult | None
    stressed_richness: DecimalInterval | None
    target_spread_ticks: Decimal | None
    total_consumed_level_count: int | None
    unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_name:
            raise ValueError("bucket leader candidate instrument must be non-empty")
        if not self.strike.is_finite() or self.strike <= 0:
            raise ValueError("bucket leader candidate strike must be finite and positive")
        known_values = (
            self.score_result,
            self.stressed_richness,
            self.target_spread_ticks,
            self.total_consumed_level_count,
        )
        if self.score_result is None:
            if not self.unknown_reason:
                raise ValueError("unknown bucket candidate requires a reason")
            if any(value is not None for value in known_values):
                raise ValueError("unknown bucket candidate cannot carry partial rank values")
            return
        if any(value is None for value in known_values[1:]) or self.unknown_reason is not None:
            raise ValueError("known bucket candidate requires every rank value")
        assert self.stressed_richness is not None
        assert self.target_spread_ticks is not None
        assert self.total_consumed_level_count is not None
        if (
            not self.stressed_richness.lower.is_finite()
            or not self.stressed_richness.upper.is_finite()
            or self.stressed_richness.lower < 0
        ):
            raise ValueError("bucket candidate richness must be finite and non-negative")
        if not self.target_spread_ticks.is_finite() or self.target_spread_ticks < 0:
            raise ValueError("bucket candidate spread must be finite and non-negative")
        if self.total_consumed_level_count <= 0:
            raise ValueError("bucket candidate consumed level count must be positive")

    @property
    def known(self) -> bool:
        return self.score_result is not None


@dataclass(frozen=True)
class BucketLeaderSelection:
    bucket_key: RadarBucketKey | None
    leader: BucketLeaderCandidate | None
    coverage: LeaderCoverage
    candidate_count: int
    unknown_candidate_count: int
    reason: str | None = None


@dataclass(frozen=True)
class RadarBucketEpisode:
    episode_identity: str
    bucket_key: RadarBucketKey
    leader_instrument_name: str
    score_band: ScoreBand
    activation_causal_seq: int
    activation_observation_identity: tuple[object, ...]
    activation_packet: RadarScorePacket
    designation_consumed: bool = False


@dataclass(frozen=True)
class RadarBucketEpisodeEnd:
    episode: RadarBucketEpisode
    reason: BucketEpisodeEndReason
    end_causal_seq: int
    detail: str | None = None


@dataclass(frozen=True)
class RadarBucketTrackerTransition:
    newly_confirmed: RadarBucketEpisode | None = None
    ended: RadarBucketEpisodeEnd | None = None
    state_changed: bool = False
    observation_counted: bool = False
    confirmation_reset_reason: BucketConfirmationResetReason | None = None


@dataclass(frozen=True)
class RadarBucketTrackerProjection:
    state: BucketEpisodeState
    episode_identity: str | None
    leader_instrument_name: str | None
    score_band: ScoreBand | None
    confirmation_observation_count: int
    required_confirmation_observation_count: int
    end_confirmation_observation_count: int
    required_end_confirmation_observation_count: int


def bucket_leader_rank_key(candidate: BucketLeaderCandidate) -> tuple[object, ...]:
    if not candidate.known:
        raise ValueError("unknown candidate has no leader rank")
    assert candidate.score_result is not None
    assert candidate.stressed_richness is not None
    assert candidate.target_spread_ticks is not None
    assert candidate.total_consumed_level_count is not None
    return (
        -candidate.score_result.score.lower,
        -candidate.stressed_richness.lower,
        candidate.target_spread_ticks,
        candidate.total_consumed_level_count,
        candidate.strike,
        candidate.instrument_name,
    )


def select_bucket_leader(
    candidates: tuple[BucketLeaderCandidate, ...],
    *,
    frozen_instrument_name: str | None = None,
) -> BucketLeaderSelection:
    if not candidates:
        return BucketLeaderSelection(None, None, LeaderCoverage.UNKNOWN, 0, 0, "EMPTY_BUCKET")
    bucket_key = candidates[0].bucket_key
    if any(candidate.bucket_key != bucket_key for candidate in candidates):
        raise ValueError("bucket leader selection received mixed bucket keys")
    unknown_count = sum(not candidate.known for candidate in candidates)
    coverage = LeaderCoverage.DEGRADED if unknown_count else LeaderCoverage.COMPLETE
    if frozen_instrument_name is not None:
        frozen = next(
            (
                candidate
                for candidate in candidates
                if candidate.instrument_name == frozen_instrument_name
            ),
            None,
        )
        if frozen is None:
            return BucketLeaderSelection(
                bucket_key,
                None,
                LeaderCoverage.UNKNOWN,
                len(candidates),
                unknown_count,
                "FROZEN_LEADER_SCOPE_LOSS",
            )
        if not frozen.known:
            return BucketLeaderSelection(
                bucket_key,
                None,
                LeaderCoverage.UNKNOWN,
                len(candidates),
                unknown_count,
                frozen.unknown_reason or "FROZEN_LEADER_CORE_UNKNOWN",
            )
        return BucketLeaderSelection(
            bucket_key,
            frozen,
            coverage,
            len(candidates),
            unknown_count,
        )
    known = tuple(candidate for candidate in candidates if candidate.known)
    if not known:
        return BucketLeaderSelection(
            bucket_key,
            None,
            LeaderCoverage.UNKNOWN,
            len(candidates),
            unknown_count,
            "BUCKET_CORE_UNKNOWN",
        )
    return BucketLeaderSelection(
        bucket_key,
        min(known, key=bucket_leader_rank_key),
        coverage,
        len(candidates),
        unknown_count,
    )


class RadarBucketEpisodeTracker:
    """In-memory confirmation owner for one bucket leader and score band."""

    def __init__(
        self,
        *,
        runtime_identity: str,
        policy_identity: str,
        bucket_key: RadarBucketKey,
        score_model: ScoreModel,
        clue_eligible: bool,
    ):
        if not runtime_identity or not policy_identity:
            raise ValueError("bucket tracker identities must be non-empty")
        self.runtime_identity = runtime_identity
        self.policy_identity = policy_identity
        self.bucket_key = bucket_key
        self.score_model = score_model
        self.clue_eligible = clue_eligible
        self.state = BucketEpisodeState.IDLE
        self.episode: RadarBucketEpisode | None = None
        self._confirming_leader: str | None = None
        self._confirming_band: ScoreBand | None = None
        self._observation_count = 0
        self._last_interval: TimeInterval | None = None
        self._seen_observation_identities: set[tuple[object, ...]] = set()
        self._end_confirmation_count = 0
        self._last_end_interval: TimeInterval | None = None
        self._seen_end_observation_identities: set[tuple[object, ...]] = set()

    @property
    def frozen_instrument_name(self) -> str | None:
        return self.episode.leader_instrument_name if self.episode is not None else None

    @property
    def confirmation_observation_count(self) -> int:
        return self._observation_count

    def projection(self, rule: OptionRule) -> RadarBucketTrackerProjection:
        return RadarBucketTrackerProjection(
            state=self.state,
            episode_identity=(self.episode.episode_identity if self.episode is not None else None),
            leader_instrument_name=(
                self.episode.leader_instrument_name
                if self.episode is not None
                else self._confirming_leader
            ),
            score_band=(
                self.episode.score_band if self.episode is not None else self._confirming_band
            ),
            confirmation_observation_count=self._observation_count,
            required_confirmation_observation_count=rule.activation_observation_count,
            end_confirmation_observation_count=self._end_confirmation_count,
            required_end_confirmation_observation_count=rule.clear_observation_count,
        )

    def observe(
        self,
        *,
        packet: RadarScorePacket,
        observation_identity: tuple[object, ...],
        causal_seq: int,
        trusted_time: TimeInterval,
        rule: OptionRule,
    ) -> RadarBucketTrackerTransition:
        if packet.bucket_key != self.bucket_key:
            raise ValueError("bucket tracker packet key mismatch")
        if not self.clue_eligible:
            changed = self.state is not BucketEpisodeState.IDLE
            reset_reason = self._preconfirmation_reset_reason(
                BucketConfirmationResetReason.CLUE_INELIGIBLE
            )
            self.episode = None
            self._reset_confirmation()
            self._reset_end_confirmation()
            return RadarBucketTrackerTransition(
                state_changed=changed,
                confirmation_reset_reason=reset_reason,
            )
        band = packet.result.band
        if self.episode is not None:
            if packet.leader_instrument_name != self.episode.leader_instrument_name:
                return self._end(BucketEpisodeEndReason.LEADER_CHANGE, causal_seq)
            if band is self.episode.score_band:
                self._reset_end_confirmation()
                return RadarBucketTrackerTransition()
            if (
                self.episode.score_band is ScoreBand.HIGH
                and packet.result.score.upper > self.score_model.clear_score_upper
            ):
                self._reset_end_confirmation()
                return RadarBucketTrackerTransition()
            return self._confirm_episode_end(
                observation_identity=observation_identity,
                trusted_time=trusted_time,
                rule=rule,
                causal_seq=causal_seq,
            )
        if band is ScoreBand.REVIEW:
            changed = self.state is not BucketEpisodeState.IDLE
            reset_reason = self._preconfirmation_reset_reason(
                BucketConfirmationResetReason.SCORE_BAND_CHANGE
            )
            self._reset_confirmation()
            return RadarBucketTrackerTransition(
                state_changed=changed,
                confirmation_reset_reason=reset_reason,
            )

        leader_or_band_changed = (
            self._confirming_leader != packet.leader_instrument_name
            or self._confirming_band is not band
        )
        reset_reason = (
            self._leader_or_band_reset_reason(packet.leader_instrument_name, band)
            if leader_or_band_changed
            else None
        )
        if leader_or_band_changed:
            self._reset_confirmation()
            self._confirming_leader = packet.leader_instrument_name
            self._confirming_band = band
            self.state = BucketEpisodeState.CONFIRMING
        if observation_identity in self._seen_observation_identities:
            return RadarBucketTrackerTransition(
                state_changed=leader_or_band_changed,
                confirmation_reset_reason=reset_reason,
            )
        if not _separated(self._last_interval, trusted_time, rule.minimum_separation_ms):
            return RadarBucketTrackerTransition(
                state_changed=leader_or_band_changed,
                confirmation_reset_reason=reset_reason,
            )
        self._seen_observation_identities.add(observation_identity)
        self._last_interval = trusted_time
        self._observation_count += 1
        if self._observation_count < rule.activation_observation_count:
            return RadarBucketTrackerTransition(
                state_changed=leader_or_band_changed,
                observation_counted=True,
                confirmation_reset_reason=reset_reason,
            )

        episode = RadarBucketEpisode(
            episode_identity=radar_bucket_episode_identity(
                runtime_identity=self.runtime_identity,
                policy_identity=self.policy_identity,
                bucket_key=self.bucket_key,
                leader_instrument_name=packet.leader_instrument_name,
                score_band=band,
                activation_causal_seq=causal_seq,
            ),
            bucket_key=self.bucket_key,
            leader_instrument_name=packet.leader_instrument_name,
            score_band=band,
            activation_causal_seq=causal_seq,
            activation_observation_identity=observation_identity,
            activation_packet=packet,
        )
        self.episode = episode
        self.state = BucketEpisodeState.ACTIVE
        self._reset_confirmation(keep_state=True)
        self._reset_end_confirmation()
        return RadarBucketTrackerTransition(
            newly_confirmed=episode,
            state_changed=True,
            observation_counted=True,
            confirmation_reset_reason=reset_reason,
        )

    def consume_designation(self) -> RadarBucketEpisode:
        if self.episode is None:
            raise RuntimeError("cannot designate a missing bucket episode")
        if self.episode.designation_consumed:
            raise RuntimeError("bucket episode designation was already consumed")
        self.episode = replace(self.episode, designation_consumed=True)
        return self.episode

    def align_leader(
        self,
        *,
        instrument_name: str,
        score_band: ScoreBand,
    ) -> RadarBucketTrackerTransition:
        """Reset pre-confirmation without counting an unchanged leader observation."""
        if not instrument_name:
            raise ValueError("aligned bucket leader must be non-empty")
        if self.episode is not None:
            if (
                self.episode.leader_instrument_name != instrument_name
                or self.episode.score_band is not score_band
            ):
                raise RuntimeError("cannot align away from one active frozen bucket episode")
            return RadarBucketTrackerTransition()
        if not self.clue_eligible:
            changed = self.state is not BucketEpisodeState.IDLE
            reset_reason = self._preconfirmation_reset_reason(
                BucketConfirmationResetReason.CLUE_INELIGIBLE
            )
            self._reset_confirmation()
            return RadarBucketTrackerTransition(
                state_changed=changed,
                confirmation_reset_reason=reset_reason,
            )
        if score_band is ScoreBand.REVIEW:
            changed = self.state is not BucketEpisodeState.IDLE
            reset_reason = self._preconfirmation_reset_reason(
                BucketConfirmationResetReason.SCORE_BAND_CHANGE
            )
            self._reset_confirmation()
            return RadarBucketTrackerTransition(
                state_changed=changed,
                confirmation_reset_reason=reset_reason,
            )
        changed = (
            self._confirming_leader != instrument_name or self._confirming_band is not score_band
        )
        reset_reason = (
            self._leader_or_band_reset_reason(instrument_name, score_band) if changed else None
        )
        if changed:
            self._reset_confirmation()
            self._confirming_leader = instrument_name
            self._confirming_band = score_band
            self.state = BucketEpisodeState.CONFIRMING
        return RadarBucketTrackerTransition(
            state_changed=changed,
            confirmation_reset_reason=reset_reason,
        )

    def core_unknown(self, *, causal_seq: int, reason: str) -> RadarBucketTrackerTransition:
        if self.episode is not None:
            return self._end(BucketEpisodeEndReason.CORE_UNKNOWN, causal_seq, reason)
        changed = self.state is not BucketEpisodeState.IDLE
        reset_reason = self._preconfirmation_reset_reason(
            BucketConfirmationResetReason.CORE_UNKNOWN
        )
        self._reset_confirmation()
        return RadarBucketTrackerTransition(
            state_changed=changed,
            confirmation_reset_reason=reset_reason,
        )

    def scope_loss(self, *, causal_seq: int) -> RadarBucketTrackerTransition:
        if self.episode is not None:
            return self._end(BucketEpisodeEndReason.SCOPE_LOSS, causal_seq)
        changed = self.state is not BucketEpisodeState.IDLE
        reset_reason = self._preconfirmation_reset_reason(BucketConfirmationResetReason.SCOPE_LOSS)
        self._reset_confirmation()
        return RadarBucketTrackerTransition(
            state_changed=changed,
            confirmation_reset_reason=reset_reason,
        )

    def stop(self, *, causal_seq: int) -> RadarBucketTrackerTransition:
        if self.episode is not None:
            return self._end(BucketEpisodeEndReason.STOP, causal_seq)
        changed = self.state is not BucketEpisodeState.IDLE
        reset_reason = self._preconfirmation_reset_reason(BucketConfirmationResetReason.STOP)
        self._reset_confirmation()
        return RadarBucketTrackerTransition(
            state_changed=changed,
            confirmation_reset_reason=reset_reason,
        )

    def _end(
        self,
        reason: BucketEpisodeEndReason,
        causal_seq: int,
        detail: str | None = None,
    ) -> RadarBucketTrackerTransition:
        if self.episode is None:
            raise RuntimeError("cannot end a missing bucket episode")
        ended = RadarBucketEpisodeEnd(self.episode, reason, causal_seq, detail)
        self.episode = None
        self._reset_confirmation()
        self._reset_end_confirmation()
        return RadarBucketTrackerTransition(ended=ended, state_changed=True)

    def _confirm_episode_end(
        self,
        *,
        observation_identity: tuple[object, ...],
        trusted_time: TimeInterval,
        rule: OptionRule,
        causal_seq: int,
    ) -> RadarBucketTrackerTransition:
        if observation_identity in self._seen_end_observation_identities:
            return RadarBucketTrackerTransition()
        if not _separated(
            self._last_end_interval,
            trusted_time,
            rule.minimum_separation_ms,
        ):
            return RadarBucketTrackerTransition()
        self._seen_end_observation_identities.add(observation_identity)
        self._last_end_interval = trusted_time
        self._end_confirmation_count += 1
        if self._end_confirmation_count < rule.clear_observation_count:
            return RadarBucketTrackerTransition(observation_counted=True)
        ended = self._end(BucketEpisodeEndReason.SCORE_BAND_CHANGE, causal_seq)
        return RadarBucketTrackerTransition(
            ended=ended.ended,
            state_changed=True,
            observation_counted=True,
        )

    def _reset_confirmation(self, *, keep_state: bool = False) -> None:
        self._confirming_leader = None
        self._confirming_band = None
        self._observation_count = 0
        self._last_interval = None
        self._seen_observation_identities.clear()
        if not keep_state:
            self.state = BucketEpisodeState.IDLE

    def _reset_end_confirmation(self) -> None:
        self._end_confirmation_count = 0
        self._last_end_interval = None
        self._seen_end_observation_identities.clear()

    def _preconfirmation_reset_reason(
        self,
        reason: BucketConfirmationResetReason,
    ) -> BucketConfirmationResetReason | None:
        return reason if self._observation_count > 0 else None

    def _leader_or_band_reset_reason(
        self,
        instrument_name: str,
        score_band: ScoreBand,
    ) -> BucketConfirmationResetReason | None:
        if self._observation_count == 0:
            return None
        if self._confirming_leader != instrument_name:
            return BucketConfirmationResetReason.LEADER_CHANGE
        if self._confirming_band is not score_band:
            return BucketConfirmationResetReason.SCORE_BAND_CHANGE
        return None


def _separated(previous: TimeInterval | None, current: TimeInterval, minimum_ms: int) -> bool:
    if previous is None:
        return True
    return current.lower_ms - previous.upper_ms >= minimum_ms


def radar_bucket_episode_identity(
    *,
    runtime_identity: str,
    policy_identity: str,
    bucket_key: RadarBucketKey,
    leader_instrument_name: str,
    score_band: ScoreBand,
    activation_causal_seq: int,
) -> str:
    preimage = json.dumps(
        {
            "runtime_identity": runtime_identity,
            "policy_identity": policy_identity,
            "bucket_key": bucket_key.as_object(),
            "leader_instrument_name": leader_instrument_name,
            "score_band": score_band.value,
            "activation_causal_seq": activation_causal_seq,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(preimage).hexdigest()}"


__all__ = [
    "BucketConfirmationResetReason",
    "BucketEpisodeEndReason",
    "BucketEpisodeState",
    "BucketLeaderCandidate",
    "BucketLeaderSelection",
    "LeaderCoverage",
    "RadarBucketEpisode",
    "RadarBucketEpisodeEnd",
    "RadarBucketEpisodeTracker",
    "RadarBucketTrackerProjection",
    "RadarBucketTrackerTransition",
    "bucket_leader_rank_key",
    "radar_bucket_episode_identity",
    "select_bucket_leader",
]

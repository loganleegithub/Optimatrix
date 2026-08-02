from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor import PriceLevel, TimeInterval

from short_vol_radar.atomic import AtomicQuote
from short_vol_radar.baseline import BaselineResult
from short_vol_radar.black import DecimalInterval, TotalVolatilityInterval
from short_vol_radar.detector import DetectorCoverage, EpisodeEndReason
from short_vol_radar.policy import OptionRule

ANOMALY_NON_CLAIMS = (
    "NOT_A_DELIVERY_TWAP_DISTRIBUTION_FORECAST",
    "NOT_VALIDATED_FORECAST",
)
ATOMIC_NON_CLAIMS = (
    "PUBLIC_QUOTE_NOT_FILL",
    "NO_BEST_PRICE_OR_COMPLETE_MARKET_CLAIM",
)
SUMMARY_NON_CLAIMS = (
    "NO_FORECAST_ACCURACY_CLAIM",
    "NO_EDGE_OR_PROFITABILITY_CLAIM",
    "NO_FILL_OR_EXECUTION_PERMISSION",
)


class EvidenceError(ValueError):
    """A business object cannot be projected or published."""


class CoverageState(StrEnum):
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"
    KNOWN_COMPLETE = "KNOWN_COMPLETE"
    KNOWN_DEGRADED = "KNOWN_DEGRADED"
    UNKNOWN = "UNKNOWN"


class CoverageBlockingReason(StrEnum):
    NONE = "NONE"
    RUNTIME_START_PENDING = "RUNTIME_START_PENDING"
    CLOCK_UNAVAILABLE = "CLOCK_UNAVAILABLE"
    CLOCK_GAP = "CLOCK_GAP"
    SESSION_GAP = "SESSION_GAP"
    REMOTE_CONNECTION_CLOSED = "REMOTE_CONNECTION_CLOSED"
    TRANSPORT_READ_FAILURE = "TRANSPORT_READ_FAILURE"
    SESSION_LIVENESS_DEADLINE = "SESSION_LIVENESS_DEADLINE"
    SESSION_RPC_FAILURE = "SESSION_RPC_FAILURE"
    RUNTIME_SESSION_FAILURE = "RUNTIME_SESSION_FAILURE"
    PROTOCOL_INCOMPATIBILITY = "PROTOCOL_INCOMPATIBILITY"
    INGRESS_GAP_OR_DUPLICATE = "INGRESS_GAP_OR_DUPLICATE"
    QUEUE_OVERFLOW = "QUEUE_OVERFLOW"
    PLATFORM_UNESTABLISHED = "PLATFORM_UNESTABLISHED"
    POST_STATUS_BOOTSTRAP_REQUIRED = "POST_STATUS_BOOTSTRAP_REQUIRED"
    PLATFORM_MAINTENANCE = "PLATFORM_MAINTENANCE"
    PUBLIC_METHODS_DENIED = "PUBLIC_METHODS_DENIED"
    RELEVANT_PLATFORM_LOCK = "RELEVANT_PLATFORM_LOCK"
    OPTION_CATALOG_INCOMPLETE = "OPTION_CATALOG_INCOMPLETE"
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"
    TIME_APPLICABILITY_UNRESOLVED = "TIME_APPLICABILITY_UNRESOLVED"
    INDEX_WARMUP = "INDEX_WARMUP"
    INDEX_WINDOW_GAP = "INDEX_WINDOW_GAP"
    INDEX_SOURCE_STALE = "INDEX_SOURCE_STALE"
    INDEX_CONTINUITY_GAP = "INDEX_CONTINUITY_GAP"
    TICKER_SOURCE_STALE = "TICKER_SOURCE_STALE"
    TICKER_TIMESTAMP_AHEAD = "TICKER_TIMESTAMP_AHEAD"
    OPTION_LIFECYCLE_UNAVAILABLE = "OPTION_LIFECYCLE_UNAVAILABLE"
    OPTION_BOOK_UNAVAILABLE = "OPTION_BOOK_UNAVAILABLE"
    CURRENT_SCOPE_INCOMPLETE = "CURRENT_SCOPE_INCOMPLETE"
    QUEUE_LAG_CURRENTNESS = "QUEUE_LAG_CURRENTNESS"


class CausalCause(StrEnum):
    RUNTIME_START = "RUNTIME_START"
    BOOTSTRAP = "BOOTSTRAP"
    PLATFORM_READY = "PLATFORM_READY"
    PLATFORM_FACT = "PLATFORM_FACT"
    PLATFORM_MAINTENANCE = "PLATFORM_MAINTENANCE"
    PUBLIC_METHODS_DENIED = "PUBLIC_METHODS_DENIED"
    RELEVANT_PLATFORM_LOCK = "RELEVANT_PLATFORM_LOCK"
    CLOCK_FACT = "CLOCK_FACT"
    CLOCK_GAP = "CLOCK_GAP"
    TIME_BOUNDARY = "TIME_BOUNDARY"
    CLEAN_STOP = "CLEAN_STOP"
    INDEX_TICK = "INDEX_TICK"
    INDEX_CONTINUITY_GAP = "INDEX_CONTINUITY_GAP"
    INDEX_SOURCE_STALE = "INDEX_SOURCE_STALE"
    INDEX_WINDOW_GAP = "INDEX_WINDOW_GAP"
    OPTION_CATALOG = "OPTION_CATALOG"
    OPTION_LIFECYCLE = "OPTION_LIFECYCLE"
    OPTION_METADATA = "OPTION_METADATA"
    OPTION_METADATA_PENDING = "OPTION_METADATA_PENDING"
    OPTION_METADATA_ABSENT = "OPTION_METADATA_ABSENT"
    OPTION_METADATA_INVALID = "OPTION_METADATA_INVALID"
    OPTION_METADATA_REQUEST_FAILED = "OPTION_METADATA_REQUEST_FAILED"
    OPTION_SNAPSHOT_INVALID = "OPTION_SNAPSHOT_INVALID"
    OPTION_CHANNEL_FAILURE = "OPTION_CHANNEL_FAILURE"
    OPTION_BOOK_GAP = "OPTION_BOOK_GAP"
    OPTION_BOOK_FACT = "OPTION_BOOK_FACT"
    OPTION_BOOK_CHANGED = "OPTION_BOOK_CHANGED"
    TICKER_APPLIED = "TICKER_APPLIED"
    TICKER_LATE_IGNORED = "TICKER_LATE_IGNORED"
    TICKER_AHEAD_IGNORED = "TICKER_AHEAD_IGNORED"
    TICKER_STALE_GENERATION_IGNORED = "TICKER_STALE_GENERATION_IGNORED"
    TICKER_SHAPE_REJECTED = "TICKER_SHAPE_REJECTED"
    TICKER_SOURCE_STALE = "TICKER_SOURCE_STALE"
    COMBO_CATALOG = "COMBO_CATALOG"
    COMBO_LIFECYCLE = "COMBO_LIFECYCLE"
    COMBO_METADATA = "COMBO_METADATA"
    COMBO_BOOK_FACT = "COMBO_BOOK_FACT"
    COMBO_BOOK_CHANGED = "COMBO_BOOK_CHANGED"
    COMBO_BOOK_GAP = "COMBO_BOOK_GAP"
    SESSION_GAP = "SESSION_GAP"
    REMOTE_CONNECTION_CLOSED = "REMOTE_CONNECTION_CLOSED"
    TRANSPORT_READ_FAILURE = "TRANSPORT_READ_FAILURE"
    SESSION_LIVENESS_DEADLINE = "SESSION_LIVENESS_DEADLINE"
    SESSION_RPC_FAILURE = "SESSION_RPC_FAILURE"
    RUNTIME_SESSION_FAILURE = "RUNTIME_SESSION_FAILURE"
    PROTOCOL_INCOMPATIBILITY = "PROTOCOL_INCOMPATIBILITY"
    QUEUE_LAG_DEADLINE = "QUEUE_LAG_DEADLINE"
    INGRESS_GAP_OR_DUPLICATE = "INGRESS_GAP_OR_DUPLICATE"
    QUEUE_OVERFLOW = "QUEUE_OVERFLOW"


@dataclass(frozen=True)
class CoverageBlockingGroup:
    blocking_reason: str
    affected_scopes: tuple[str, ...]


@dataclass(frozen=True)
class CoverageSegment:
    start_monotonic_ms: int
    end_monotonic_ms: int
    state: CoverageState
    reason: str
    blocking_reason: str
    affected_scopes: tuple[str, ...]
    global_continuity_epoch: int
    blocking_groups: tuple[CoverageBlockingGroup, ...] = ()

    def __post_init__(self) -> None:
        if not self.blocking_groups and self.state is not CoverageState.KNOWN_COMPLETE:
            object.__setattr__(
                self,
                "blocking_groups",
                (CoverageBlockingGroup(self.blocking_reason, self.affected_scopes),),
            )


@dataclass(frozen=True)
class AnomalyEvidence:
    code_identity: str
    runtime_identity: str
    policy_identity: str
    episode_identity: str
    causal_seq: int
    instrument_name: str
    expiration_timestamp_ms: int
    option_type: str
    activation_band_id: str
    aggregate_coverage: DetectorCoverage
    target_base_quantity_btc: Decimal
    rule: OptionRule
    baseline: BaselineResult
    trusted_time: TimeInterval
    remaining_life_years: DecimalInterval
    consumed_bid_levels: tuple[PriceLevel, ...]
    forward_usdc: Decimal
    strike_usdc: Decimal
    executable_sell_price_usdc: Decimal
    total_volatility: TotalVolatilityInterval
    executable_bid_iv: DecimalInterval
    delta: DecimalInterval
    implied_total_variance: DecimalInterval
    richness: DecimalInterval


@dataclass(frozen=True)
class AtomicEvidence:
    code_identity: str
    runtime_identity: str
    policy_identity: str
    episode_identity: str
    anomaly_activation_seq: int
    detector_causal_seq: int
    quote_causal_seq: int
    short_instrument_name: str
    combo_legs: tuple[tuple[str, Decimal], tuple[str, Decimal]]
    quote: AtomicQuote
    target_base_quantity_btc: Decimal
    source_timestamp_ms: int


def project_anomaly_event(value: AnomalyEvidence) -> dict[str, object]:
    return {
        "object_kind": "SHORT_VOL_ANOMALY_EVENT",
        "code_identity": value.code_identity,
        "runtime_identity": value.runtime_identity,
        "policy_identity": value.policy_identity,
        "episode_identity": value.episode_identity,
        "causal_seq": value.causal_seq,
        "instrument": {
            "instrument_name": value.instrument_name,
            "expiration_timestamp_ms": value.expiration_timestamp_ms,
            "option_type": value.option_type,
            "strike_usdc": decimal_text(value.strike_usdc),
        },
        "activation_band_id": value.activation_band_id,
        "aggregate_coverage": value.aggregate_coverage.value,
        "target_base_quantity_btc": decimal_text(value.target_base_quantity_btc),
        "detector_boundaries": _rule_object(value.rule),
        "baseline": {
            "window_variances": [
                {"lookback_minutes": lookback, "variance": decimal_text(variance)}
                for lookback, variance in value.baseline.window_variances
            ],
            "variance_rate_per_minute": decimal_text(value.baseline.variance_rate_per_minute),
            "annualized_volatility": decimal_text(value.baseline.annualized_volatility),
            "total_variance_interval": _decimal_interval(
                DecimalInterval(
                    value.baseline.total_variance_low,
                    value.baseline.total_variance_high,
                )
            ),
        },
        "trusted_time_ms": _time_interval(value.trusted_time),
        "remaining_life_years": _decimal_interval(value.remaining_life_years),
        "executable": {
            "consumed_bid_levels": _levels(value.consumed_bid_levels),
            "forward_usdc": decimal_text(value.forward_usdc),
            "sell_price_usdc": decimal_text(value.executable_sell_price_usdc),
            "total_volatility_interval": {
                "lower": decimal_text(value.total_volatility.lower),
                "upper": decimal_text(value.total_volatility.upper),
            },
            "iv_interval": _decimal_interval(value.executable_bid_iv),
            "delta_interval": _decimal_interval(value.delta),
            "implied_total_variance_interval": _decimal_interval(value.implied_total_variance),
            "richness_interval": _decimal_interval(value.richness),
        },
        "classification": "ANOMALY_ACTIVE",
        "non_claims": list(ANOMALY_NON_CLAIMS),
    }


def project_atomic_event(value: AtomicEvidence) -> dict[str, object]:
    validate_atomic_causal_invariant(
        anomaly_activation_seq=value.anomaly_activation_seq,
        detector_causal_seq=value.detector_causal_seq,
        quote_causal_seq=value.quote_causal_seq,
    )
    return {
        "object_kind": "PUBLIC_ATOMIC_QUOTE_EVENT",
        "code_identity": value.code_identity,
        "runtime_identity": value.runtime_identity,
        "policy_identity": value.policy_identity,
        "episode_identity": value.episode_identity,
        "detector_causal_seq": value.detector_causal_seq,
        "quote_causal_seq": value.quote_causal_seq,
        "short_instrument_name": value.short_instrument_name,
        "combo_instrument_name": value.quote.match.combo_instrument_name,
        "combo_legs": [
            {"instrument_name": name, "amount": decimal_text(amount)}
            for name, amount in value.combo_legs
        ],
        "required_combo_order_direction": value.quote.match.direction.value,
        "signed_order_amount_btc": decimal_text(value.quote.match.signed_order_amount_btc),
        "target_base_quantity_btc": decimal_text(value.target_base_quantity_btc),
        "consumed_required_side_levels": _levels(value.quote.consumed_levels),
        "required_side_vwap_usdc_per_btc": decimal_text(
            value.quote.required_side_vwap_usdc_per_btc
        ),
        "gross_entry_credit_usdc": decimal_text(value.quote.gross_entry_credit_usdc),
        "source_timestamp_ms": value.source_timestamp_ms,
        "non_claims": list(ATOMIC_NON_CLAIMS),
    }


def project_run_summary(
    *,
    code_identity: str,
    runtime_identity: str,
    policy_identity: str,
    coverage_segments: Sequence[CoverageSegment],
    band_suspended_duration_ms: int,
    counts_by_scope: Sequence[Mapping[str, object]],
    detector_unknown_transition_count_by_reason: Mapping[str, int],
    anomaly_end_count_by_reason: Mapping[EpisodeEndReason | str, int],
    known_active_duration_ms_sum_by_end_reason: Mapping[EpisodeEndReason | str, int],
    public_atomic_quote_state_transition_count: Mapping[str, int],
) -> dict[str, object]:
    if not coverage_segments:
        raise EvidenceError("run summary requires at least one coverage segment")
    rows = [
        {
            "start_monotonic_ms": segment.start_monotonic_ms,
            "end_monotonic_ms": segment.end_monotonic_ms,
            "state": segment.state.value,
            "trigger_cause": segment.reason,
            "blocking_reason": segment.blocking_reason,
            "affected_scopes": list(segment.affected_scopes),
            "blocking_groups": [
                {
                    "blocking_reason": group.blocking_reason,
                    "affected_scopes": list(group.affected_scopes),
                }
                for group in segment.blocking_groups
            ],
            "global_continuity_epoch": segment.global_continuity_epoch,
        }
        for segment in coverage_segments
    ]
    return {
        "object_kind": "RADAR_RUN_SUMMARY",
        "code_identity": code_identity,
        "runtime_identity": runtime_identity,
        "policy_identity": policy_identity,
        "runtime_started_monotonic_ms": coverage_segments[0].start_monotonic_ms,
        "clean_stop_monotonic_ms": coverage_segments[-1].end_monotonic_ms,
        "coverage_segments": rows,
        "coverage": _coverage_object(tuple(coverage_segments)),
        "band_suspended_duration_ms": band_suspended_duration_ms,
        "counts_by_scope": [dict(item) for item in counts_by_scope],
        "detector_unknown_transition_count_by_reason": dict(
            detector_unknown_transition_count_by_reason
        ),
        "anomaly_end_count_by_reason": _enum_keyed_counts(anomaly_end_count_by_reason),
        "known_active_duration_ms_sum_by_end_reason": _enum_keyed_counts(
            known_active_duration_ms_sum_by_end_reason
        ),
        "public_atomic_quote_state_transition_count": dict(
            public_atomic_quote_state_transition_count
        ),
        "non_claims": list(SUMMARY_NON_CLAIMS),
    }


class RadarEventSink:
    """Non-durable current Radar transitions and clean-stop summary."""

    def __init__(
        self,
        *,
        code_identity: str,
        runtime_identity: str,
        policy_identity: str,
    ) -> None:
        self.code_identity = code_identity
        self.runtime_identity = runtime_identity
        self.policy_identity = policy_identity
        self._anomalies: dict[str, dict[str, object]] = {}
        self._atomics: dict[tuple[str, str], dict[str, object]] = {}
        self._summary: dict[str, object] | None = None

    @property
    def anomalies(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._anomalies[key] for key in sorted(self._anomalies))

    @property
    def atomics(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._atomics[key] for key in sorted(self._atomics))

    @property
    def summary(self) -> Mapping[str, object] | None:
        return self._summary

    def record_anomaly(self, event: Mapping[str, object]) -> bool:
        self._require_identity(event)
        episode = _required_string(event, "episode_identity")
        return self._record(self._anomalies, episode, event)

    def record_atomic(self, event: Mapping[str, object]) -> bool:
        self._require_identity(event)
        key = (
            _required_string(event, "episode_identity"),
            _required_string(event, "combo_instrument_name"),
        )
        return self._record(self._atomics, key, event)

    def record_summary(self, summary: Mapping[str, object]) -> Mapping[str, object]:
        self._require_identity(summary)
        normalized = dict(summary)
        if self._summary is not None and self._summary != normalized:
            raise EvidenceError("conflicting in-memory Radar summary")
        self._summary = normalized
        return normalized

    def _require_identity(self, value: Mapping[str, object]) -> None:
        for field, expected in (
            ("code_identity", self.code_identity),
            ("runtime_identity", self.runtime_identity),
            ("policy_identity", self.policy_identity),
        ):
            if value.get(field) != expected:
                raise EvidenceError(f"{field} does not match the Radar sink")

    @staticmethod
    def _record(
        values: dict[object, dict[str, object]],
        key: object,
        event: Mapping[str, object],
    ) -> bool:
        normalized = dict(event)
        previous = values.get(key)
        if previous is not None and previous != normalized:
            raise EvidenceError("conflicting in-memory Radar transition")
        if previous == normalized:
            return False
        values[key] = normalized
        return True


def validate_atomic_causal_invariant(
    *,
    anomaly_activation_seq: int | None,
    detector_causal_seq: int,
    quote_causal_seq: int,
) -> None:
    if detector_causal_seq != quote_causal_seq:
        raise EvidenceError("atomic detector and quote must share one causal boundary")
    if anomaly_activation_seq is not None and anomaly_activation_seq > detector_causal_seq:
        raise EvidenceError("atomic causal boundary precedes anomaly activation")


def ratio_or_none(numerator: int, denominator: int | None) -> Decimal | None:
    if denominator in {None, 0}:
        return None
    if numerator < 0 or denominator < 0:
        raise ValueError("rate counts must be non-negative")
    return Decimal(numerator) / Decimal(denominator)


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise EvidenceError("business Decimal must be finite")
    return format(value, "f")


def _coverage_object(segments: tuple[CoverageSegment, ...]) -> dict[str, int]:
    counts: Counter[CoverageState] = Counter()
    cursor = segments[0].start_monotonic_ms
    for segment in segments:
        if segment.start_monotonic_ms != cursor:
            raise EvidenceError("coverage segments overlap or contain a gap")
        if segment.end_monotonic_ms < segment.start_monotonic_ms:
            raise EvidenceError("coverage segment duration cannot be negative")
        if segment.end_monotonic_ms == segment.start_monotonic_ms and len(segments) != 1:
            raise EvidenceError("zero-duration coverage is valid only for a zero-length run")
        counts[segment.state] += segment.end_monotonic_ms - segment.start_monotonic_ms
        cursor = segment.end_monotonic_ms
    observation = segments[-1].end_monotonic_ms - segments[0].start_monotonic_ms
    return {
        "observation_interval_ms": observation,
        "known_complete_ms": counts[CoverageState.KNOWN_COMPLETE],
        "known_degraded_ms": counts[CoverageState.KNOWN_DEGRADED],
        "unknown_ms": counts[CoverageState.UNKNOWN],
        "no_applicable_scope_ms": counts[CoverageState.NO_APPLICABLE_SCOPE],
        "coverage_partition_error_ms": observation - sum(counts.values()),
    }


def _required_string(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise EvidenceError(f"{field} must be a non-empty string")
    return member


def _enum_keyed_counts(
    values: Mapping[EpisodeEndReason | str, int],
) -> dict[str, int]:
    return {
        (key.value if isinstance(key, EpisodeEndReason) else key): count
        for key, count in values.items()
    }


def _rule_object(rule: OptionRule) -> dict[str, object]:
    return {
        "abs_delta_min": decimal_text(rule.abs_delta_min),
        "abs_delta_max": decimal_text(rule.abs_delta_max),
        "activation_ratio": decimal_text(rule.activation_ratio),
        "clear_ratio": decimal_text(rule.clear_ratio),
        "activation_observation_count": rule.activation_observation_count,
        "clear_observation_count": rule.clear_observation_count,
        "minimum_separation_ms": rule.minimum_separation_ms,
    }


def _time_interval(value: TimeInterval) -> dict[str, int]:
    return {"lower": value.lower_ms, "upper": value.upper_ms}


def _decimal_interval(value: DecimalInterval) -> dict[str, str]:
    return {"lower": decimal_text(value.lower), "upper": decimal_text(value.upper)}


def _levels(values: tuple[PriceLevel, ...]) -> list[dict[str, str]]:
    return [
        {"price": decimal_text(level.price), "amount": decimal_text(level.amount)}
        for level in values
    ]

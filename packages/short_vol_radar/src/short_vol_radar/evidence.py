from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

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
OPTION_LOCAL_ACCEPTANCE_WINDOW_MS = 3_600_000
OPTION_LOCAL_RETAINED_INTERVAL_LIMIT = 10_000
TRANSPORT_CLOSE_CODE_ALLOWLIST = frozenset(
    {
        "1000",
        "1001",
        "1002",
        "1003",
        "1006",
        "1007",
        "1008",
        "1009",
        "1010",
        "1011",
        "1012",
        "1013",
        "1014",
        "1015",
        "NOT_AVAILABLE",
        "OTHER",
    }
)
TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST = frozenset({"CLEAN", "ABNORMAL"})
TRANSPORT_EXCEPTION_CLASS_ALLOWLIST = frozenset(
    {
        "NONE",
        "PublicProtocolIncompatibility",
        "PublicProtocolError",
        "ConnectionClosedOK",
        "ConnectionClosedError",
        "OSError",
        "SSLError",
        "TimeoutError",
        "EOFError",
        "WebSocketException",
        "OTHER",
    }
)
CHANNEL_CLASSES = tuple(
    sorted(
        (
            "PLATFORM",
            "OPTION_LIFECYCLE",
            "COMBO_LIFECYCLE",
            "INDEX",
            "OPTION_TICKER",
            "OPTION_BOOK",
            "COMBO_BOOK",
            "HEARTBEAT",
            "CONNECTION_CONTROL",
            "INVALID",
        )
    )
)
_STRING_FIELD_TYPES = frozenset({"string"})
_BOOLEAN_FIELD_TYPES = frozenset({"boolean"})
_INTEGER_FIELD_TYPES = frozenset({"integer"})
_NUMERIC_FIELD_TYPES = frozenset({"integer", "number", "string"})
_ARRAY_FIELD_TYPES = frozenset({"array"})
_BOOK_SOURCE_FIELDS: Mapping[str, frozenset[str]] = {
    "type": _STRING_FIELD_TYPES,
    "timestamp": _INTEGER_FIELD_TYPES,
    "instrument_name": _STRING_FIELD_TYPES,
    "change_id": _INTEGER_FIELD_TYPES,
    "prev_change_id": frozenset({"integer", "null"}),
    "bids": _ARRAY_FIELD_TYPES,
    "asks": _ARRAY_FIELD_TYPES,
}
_INSTRUMENT_SOURCE_FIELDS: Mapping[str, frozenset[str]] = {
    "instrument_name": _STRING_FIELD_TYPES,
    "kind": _STRING_FIELD_TYPES,
    "base_currency": _STRING_FIELD_TYPES,
    "quote_currency": _STRING_FIELD_TYPES,
    "settlement_currency": _STRING_FIELD_TYPES,
    "counter_currency": _STRING_FIELD_TYPES,
    "price_index": _STRING_FIELD_TYPES,
    "instrument_type": _STRING_FIELD_TYPES,
    "is_active": _BOOLEAN_FIELD_TYPES,
    "state": _STRING_FIELD_TYPES,
    "option_type": _STRING_FIELD_TYPES,
    "expiration_timestamp": _INTEGER_FIELD_TYPES,
    "strike": _NUMERIC_FIELD_TYPES,
    "contract_size": _NUMERIC_FIELD_TYPES,
    "min_trade_amount": _NUMERIC_FIELD_TYPES,
    "qty_tick_size": _NUMERIC_FIELD_TYPES,
}
SOURCE_CONSUMED_FIELD_TYPES: Mapping[
    str,
    Mapping[str, frozenset[str]],
] = {
    "combo_book": _BOOK_SOURCE_FIELDS,
    "combo_lifecycle": {
        "instrument_name": _STRING_FIELD_TYPES,
        "state": _STRING_FIELD_TYPES,
    },
    "heartbeat": {"type": _STRING_FIELD_TYPES},
    "index": {
        "timestamp": _INTEGER_FIELD_TYPES,
        "index_name": _STRING_FIELD_TYPES,
        "price": _NUMERIC_FIELD_TYPES,
    },
    "option_book": _BOOK_SOURCE_FIELDS,
    "option_lifecycle": {
        "instrument_name": _STRING_FIELD_TYPES,
        "state": _STRING_FIELD_TYPES,
    },
    "option_ticker": {
        "instrument_name": _STRING_FIELD_TYPES,
        "timestamp": _INTEGER_FIELD_TYPES,
        "underlying_price": _NUMERIC_FIELD_TYPES,
        "underlying_index": _STRING_FIELD_TYPES,
    },
    "platform_state": {
        "maintenance": _BOOLEAN_FIELD_TYPES,
        "price_index": _STRING_FIELD_TYPES,
        "locked": _BOOLEAN_FIELD_TYPES,
    },
    "platform_state.public_methods_state": {
        "allow_unauthenticated_public_requests": _BOOLEAN_FIELD_TYPES,
    },
    "public/get_combos": {
        "id": _STRING_FIELD_TYPES,
        "state": _STRING_FIELD_TYPES,
        "legs": _ARRAY_FIELD_TYPES,
    },
    "public/get_instrument": _INSTRUMENT_SOURCE_FIELDS,
    "public/get_instruments": _INSTRUMENT_SOURCE_FIELDS,
    "public/get_time": {},
    "public/set_heartbeat": {},
    "public/status": {
        "locked": frozenset({"boolean", "string"}),
        "locked_indices": _ARRAY_FIELD_TYPES,
    },
    "public/subscribe": {},
    "public/test": dict(version=_STRING_FIELD_TYPES),
    "public/unsubscribe": {},
}
CORE_SOURCE_NAMES = tuple(sorted(SOURCE_CONSUMED_FIELD_TYPES))


class EvidenceError(ValueError):
    """Repository-owned evidence is invalid or mixed."""


class CoverageState(StrEnum):
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"
    KNOWN_COMPLETE = "KNOWN_COMPLETE"
    KNOWN_DEGRADED = "KNOWN_DEGRADED"
    UNKNOWN = "UNKNOWN"


class CoverageBlockingReason(StrEnum):
    NONE = "NONE"
    LEGACY_UNATTRIBUTED = "LEGACY_UNATTRIBUTED"
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
    INDEX_TIME_BOUNDARY_PENDING = "INDEX_TIME_BOUNDARY_PENDING"
    INDEX_WATERMARK_PENDING = "INDEX_WATERMARK_PENDING"
    INDEX_WINDOW_GAP = "INDEX_WINDOW_GAP"
    INDEX_SOURCE_STALE = "INDEX_SOURCE_STALE"
    INDEX_CONTINUITY_GAP = "INDEX_CONTINUITY_GAP"
    TICKER_SOURCE_STALE = "TICKER_SOURCE_STALE"
    TICKER_TIMESTAMP_AHEAD = "TICKER_TIMESTAMP_AHEAD"
    OPTION_LIFECYCLE_UNAVAILABLE = "OPTION_LIFECYCLE_UNAVAILABLE"
    OPTION_BOOK_UNAVAILABLE = "OPTION_BOOK_UNAVAILABLE"
    CURRENT_SCOPE_INCOMPLETE = "CURRENT_SCOPE_INCOMPLETE"
    ACTIVE_POSITIVE_SCOPE_INCOMPLETE = "ACTIVE_POSITIVE_SCOPE_INCOMPLETE"
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


FAILURE_DOMAINS = frozenset(
    {
        "SESSION",
        "CLOCK_INDEX",
        "OPTION",
        "OPTION_CATALOG",
        "COMBO_LAYER",
        "FATAL_PROTOCOL",
    }
)
RPC_METHOD_ALLOWLIST = frozenset(
    {
        "public/get_combos",
        "public/get_instrument",
        "public/get_instruments",
        "public/get_time",
        "public/set_heartbeat",
        "public/status",
        "public/subscribe",
        "public/test",
        "public/unsubscribe",
    }
)
GLOBAL_CONTINUITY_RESTART_ALLOWLIST: Mapping[
    str,
    tuple[str, str],
] = {
    CausalCause.SESSION_GAP.value: ("SESSION", "GLOBAL"),
    CausalCause.REMOTE_CONNECTION_CLOSED.value: ("SESSION", "GLOBAL"),
    CausalCause.TRANSPORT_READ_FAILURE.value: ("SESSION", "GLOBAL"),
    CausalCause.SESSION_LIVENESS_DEADLINE.value: ("SESSION", "GLOBAL"),
    CausalCause.SESSION_RPC_FAILURE.value: ("SESSION", "GLOBAL"),
    CausalCause.RUNTIME_SESSION_FAILURE.value: ("SESSION", "GLOBAL"),
    CausalCause.PROTOCOL_INCOMPATIBILITY.value: ("SESSION", "GLOBAL"),
    CausalCause.INGRESS_GAP_OR_DUPLICATE.value: ("SESSION", "GLOBAL"),
    CausalCause.QUEUE_OVERFLOW.value: ("SESSION", "GLOBAL"),
    CausalCause.PLATFORM_MAINTENANCE.value: ("SESSION", "GLOBAL"),
    CausalCause.PUBLIC_METHODS_DENIED.value: ("SESSION", "GLOBAL"),
    CausalCause.RELEVANT_PLATFORM_LOCK.value: ("SESSION", "GLOBAL"),
    CausalCause.CLOCK_GAP.value: ("CLOCK_INDEX", "GLOBAL"),
    CausalCause.INDEX_CONTINUITY_GAP.value: ("CLOCK_INDEX", "GLOBAL"),
    CausalCause.INDEX_SOURCE_STALE.value: ("CLOCK_INDEX", "GLOBAL"),
    CausalCause.INDEX_WINDOW_GAP.value: ("CLOCK_INDEX", "SCOPE"),
}
SEALED_GLOBAL_CONTINUITY_RESTART_ALLOWLIST: Mapping[
    str,
    tuple[str, str],
] = {
    **GLOBAL_CONTINUITY_RESTART_ALLOWLIST,
    CausalCause.QUEUE_LAG_DEADLINE.value: ("SESSION", "GLOBAL"),
}
OPTION_LOCAL_REASONS = frozenset(
    {
        "FORWARD_TICKER_UNKNOWN",
        "OPTION_CHANNEL_FAILURE",
        "TICKER_SOURCE_STALE",
        "TICKER_TIMESTAMP_AHEAD",
    }
)
SOAK_PENDING_REASONS = frozenset(
    {
        CoverageBlockingReason.INDEX_TIME_BOUNDARY_PENDING.value,
        CoverageBlockingReason.INDEX_WATERMARK_PENDING.value,
    }
)
SOAK_GLOBAL_CURRENTNESS_REASONS = frozenset(
    {
        CoverageBlockingReason.CLOCK_UNAVAILABLE.value,
        CoverageBlockingReason.CLOCK_GAP.value,
        CoverageBlockingReason.SESSION_GAP.value,
        CoverageBlockingReason.REMOTE_CONNECTION_CLOSED.value,
        CoverageBlockingReason.TRANSPORT_READ_FAILURE.value,
        CoverageBlockingReason.SESSION_LIVENESS_DEADLINE.value,
        CoverageBlockingReason.SESSION_RPC_FAILURE.value,
        CoverageBlockingReason.RUNTIME_SESSION_FAILURE.value,
        CoverageBlockingReason.PROTOCOL_INCOMPATIBILITY.value,
        CoverageBlockingReason.INGRESS_GAP_OR_DUPLICATE.value,
        CoverageBlockingReason.QUEUE_OVERFLOW.value,
        CoverageBlockingReason.PLATFORM_UNESTABLISHED.value,
        CoverageBlockingReason.POST_STATUS_BOOTSTRAP_REQUIRED.value,
        CoverageBlockingReason.PLATFORM_MAINTENANCE.value,
        CoverageBlockingReason.PUBLIC_METHODS_DENIED.value,
        CoverageBlockingReason.RELEVANT_PLATFORM_LOCK.value,
        CoverageBlockingReason.OPTION_CATALOG_INCOMPLETE.value,
        CoverageBlockingReason.INDEX_WARMUP.value,
        CoverageBlockingReason.INDEX_WINDOW_GAP.value,
        CoverageBlockingReason.INDEX_SOURCE_STALE.value,
        CoverageBlockingReason.INDEX_CONTINUITY_GAP.value,
        CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value,
    }
)


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
    event: dict[str, object] = {
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
    validate_anomaly_event(event)
    return event


def project_atomic_event(value: AtomicEvidence) -> dict[str, object]:
    validate_atomic_causal_invariant(
        anomaly_activation_seq=value.anomaly_activation_seq,
        detector_causal_seq=value.detector_causal_seq,
        quote_causal_seq=value.quote_causal_seq,
    )
    event: dict[str, object] = {
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
    validate_atomic_event(event)
    return event


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
    operational_diagnostics: Mapping[str, object],
) -> dict[str, object]:
    if not coverage_segments:
        raise EvidenceError("run summary requires at least one coverage segment")
    coverage = _coverage_object(tuple(coverage_segments))
    diagnostics_version = operational_diagnostics.get("operational_diagnostics_schema_version")
    if type(diagnostics_version) is not int or diagnostics_version != 5:
        raise EvidenceError(
            "current run-summary writer requires integer diagnostics schema version 5"
        )
    coverage_rows: list[dict[str, object]] = []
    for segment in coverage_segments:
        coverage_rows.append(
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
        )
    summary: dict[str, object] = {
        "object_kind": "RADAR_RUN_SUMMARY",
        "code_identity": code_identity,
        "runtime_identity": runtime_identity,
        "policy_identity": policy_identity,
        "runtime_started_monotonic_ms": coverage_segments[0].start_monotonic_ms,
        "clean_stop_monotonic_ms": coverage_segments[-1].end_monotonic_ms,
        "operational_diagnostics": dict(operational_diagnostics),
        "coverage_segments": coverage_rows,
        "coverage": coverage,
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
    validate_run_summary(summary)
    return summary


class EvidenceWriter:
    def __init__(
        self,
        directory: Path,
        *,
        code_identity: str,
        runtime_identity: str,
        policy_identity: str,
    ) -> None:
        self.directory = directory
        self.code_identity = code_identity
        self.runtime_identity = runtime_identity
        self.policy_identity = policy_identity

    def write_anomaly(self, event: Mapping[str, object]) -> Path | None:
        validate_anomaly_event(event)
        self._validate_identity(event)
        episode_id = _required_string(event, "episode_identity")
        return self._write_exclusive(
            f"short-vol-anomaly-{_safe_name(episode_id)}.json",
            event,
            duplicate_is_noop=True,
        )

    def write_atomic(self, event: Mapping[str, object]) -> Path | None:
        validate_atomic_event(event)
        self._validate_identity(event)
        identity = (
            _required_string(event, "episode_identity"),
            _required_string(event, "combo_instrument_name"),
        )
        return self._write_exclusive(
            f"public-atomic-quote-{_safe_name(identity[0])}-{_safe_name(identity[1])}.json",
            event,
            duplicate_is_noop=True,
        )

    def write_summary(self, summary: Mapping[str, object]) -> Path:
        validate_run_summary(summary)
        self._validate_identity(summary)
        path = self._write_exclusive("radar-run-summary.json", summary)
        if path is None:
            raise RuntimeError("exclusive summary write unexpectedly returned no path")
        return path

    def _validate_identity(self, value: Mapping[str, object]) -> None:
        expected = {
            "code_identity": self.code_identity,
            "runtime_identity": self.runtime_identity,
            "policy_identity": self.policy_identity,
        }
        for field, identity in expected.items():
            if value.get(field) != identity:
                raise EvidenceError(f"{field} does not match evidence directory identity")

    def _write_exclusive(
        self,
        name: str,
        value: Mapping[str, object],
        *,
        duplicate_is_noop: bool = False,
    ) -> Path | None:
        path = self.directory / name
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        temporary = self.directory / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        except FileExistsError as exc:
            if duplicate_is_noop:
                try:
                    existing = path.read_text(encoding="utf-8")
                except OSError as read_exc:
                    raise EvidenceError(
                        f"existing evidence cannot be verified: {path}"
                    ) from read_exc
                if existing == serialized + "\n":
                    return None
                raise EvidenceError(
                    f"conflicting evidence already exists for the same identity: {path}"
                ) from exc
            raise EvidenceError(f"evidence path already exists: {path}") from exc
        except OSError as exc:
            raise EvidenceError(f"evidence publish failed: {path}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise EvidenceError(f"evidence temporary cleanup failed: {temporary}") from exc
        try:
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise EvidenceError(f"evidence directory sync failed: {self.directory}") from exc
        return path


def validate_anomaly_event(value: Mapping[str, object]) -> None:
    _exact_keys(
        value,
        {
            "object_kind",
            "code_identity",
            "runtime_identity",
            "policy_identity",
            "episode_identity",
            "causal_seq",
            "instrument",
            "activation_band_id",
            "aggregate_coverage",
            "target_base_quantity_btc",
            "detector_boundaries",
            "baseline",
            "trusted_time_ms",
            "remaining_life_years",
            "executable",
            "classification",
            "non_claims",
        },
        "SHORT_VOL_ANOMALY_EVENT",
    )
    if value["object_kind"] != "SHORT_VOL_ANOMALY_EVENT":
        raise EvidenceError("wrong anomaly object_kind")
    _validate_non_claims(value["non_claims"], ANOMALY_NON_CLAIMS, "anomaly")
    _validate_identity_fields(value)
    _required_string(value, "episode_identity")
    _required_string(value, "activation_band_id")
    _non_negative_integer(value["causal_seq"], "causal_seq")
    raw_coverage = value["aggregate_coverage"]
    if not isinstance(raw_coverage, str):
        raise EvidenceError("aggregate_coverage is invalid")
    try:
        coverage = DetectorCoverage(raw_coverage)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("aggregate_coverage is invalid") from exc
    if coverage is DetectorCoverage.UNKNOWN:
        raise EvidenceError("anomaly aggregate coverage cannot be UNKNOWN")
    target = _positive_decimal_text(value["target_base_quantity_btc"], "target_base_quantity_btc")
    _validate_instrument(value["instrument"])
    _validate_rule(value["detector_boundaries"])
    _validate_baseline(value["baseline"])
    _validate_integer_interval(value["trusted_time_ms"], "trusted_time_ms")
    _validate_decimal_interval(value["remaining_life_years"], "remaining_life_years")
    _validate_executable(
        value["executable"],
        target=target,
        detector_boundaries=_mapping(value["detector_boundaries"], "detector_boundaries"),
    )
    if value["classification"] != "ANOMALY_ACTIVE":
        raise EvidenceError("anomaly classification must be ANOMALY_ACTIVE")


def validate_atomic_event(value: Mapping[str, object]) -> None:
    _exact_keys(
        value,
        {
            "object_kind",
            "code_identity",
            "runtime_identity",
            "policy_identity",
            "episode_identity",
            "detector_causal_seq",
            "quote_causal_seq",
            "short_instrument_name",
            "combo_instrument_name",
            "combo_legs",
            "required_combo_order_direction",
            "signed_order_amount_btc",
            "target_base_quantity_btc",
            "consumed_required_side_levels",
            "required_side_vwap_usdc_per_btc",
            "gross_entry_credit_usdc",
            "source_timestamp_ms",
            "non_claims",
        },
        "PUBLIC_ATOMIC_QUOTE_EVENT",
    )
    if value["object_kind"] != "PUBLIC_ATOMIC_QUOTE_EVENT":
        raise EvidenceError("wrong atomic object_kind")
    _validate_non_claims(value["non_claims"], ATOMIC_NON_CLAIMS, "atomic")
    _validate_identity_fields(value)
    for field in (
        "episode_identity",
        "short_instrument_name",
        "combo_instrument_name",
    ):
        _required_string(value, field)
    detector_causal_seq = _non_negative_integer(value["detector_causal_seq"], "detector_causal_seq")
    quote_causal_seq = _non_negative_integer(value["quote_causal_seq"], "quote_causal_seq")
    validate_atomic_causal_invariant(
        anomaly_activation_seq=None,
        detector_causal_seq=detector_causal_seq,
        quote_causal_seq=quote_causal_seq,
    )
    if value["required_combo_order_direction"] not in {"BUY", "SELL"}:
        raise EvidenceError("required_combo_order_direction is invalid")
    signed_amount = _decimal_text_value(value["signed_order_amount_btc"], "signed_order_amount_btc")
    if signed_amount == 0:
        raise EvidenceError("signed_order_amount_btc must be non-zero")
    target = _positive_decimal_text(value["target_base_quantity_btc"], "target_base_quantity_btc")
    if abs(signed_amount) != target:
        raise EvidenceError("signed combo amount must equal the target magnitude")
    direction = value["required_combo_order_direction"]
    if (signed_amount > 0) != (direction == "BUY"):
        raise EvidenceError("signed combo amount conflicts with order direction")
    legs = _validate_combo_legs(value["combo_legs"])
    short_instrument_name = _required_string(value, "short_instrument_name")
    if short_instrument_name not in {name for name, _ in legs}:
        raise EvidenceError("atomic combo legs omit the short instrument")
    short_leg_amount = next(amount for name, amount in legs if name == short_instrument_name)
    if signed_amount * short_leg_amount != -target:
        raise EvidenceError("atomic short leg does not express the target short exposure")
    levels = _validate_levels(
        value["consumed_required_side_levels"], "consumed_required_side_levels"
    )
    if sum((amount for _, amount in levels), Decimal(0)) != target:
        raise EvidenceError("atomic consumed depth does not equal target quantity")
    vwap = _decimal_text_value(
        value["required_side_vwap_usdc_per_btc"],
        "required_side_vwap_usdc_per_btc",
    )
    if sum((price * amount for price, amount in levels), Decimal(0)) / target != vwap:
        raise EvidenceError("atomic VWAP does not match consumed levels")
    gross_credit = _positive_decimal_text(
        value["gross_entry_credit_usdc"], "gross_entry_credit_usdc"
    )
    if -signed_amount * vwap != gross_credit:
        raise EvidenceError("atomic gross credit does not match signed quote economics")
    _non_negative_integer(value["source_timestamp_ms"], "source_timestamp_ms")


def validate_atomic_causal_invariant(
    *,
    anomaly_activation_seq: int | None,
    detector_causal_seq: int,
    quote_causal_seq: int,
) -> None:
    detector_seq = _non_negative_integer(
        detector_causal_seq,
        "atomic detector_causal_seq",
    )
    quote_seq = _non_negative_integer(
        quote_causal_seq,
        "atomic quote_causal_seq",
    )
    if detector_seq != quote_seq:
        raise EvidenceError("atomic detector and quote must share one causal boundary")
    if anomaly_activation_seq is None:
        return
    activation_seq = _non_negative_integer(
        anomaly_activation_seq,
        "atomic anomaly_activation_seq",
    )
    if activation_seq > detector_seq:
        raise EvidenceError("atomic causal boundary precedes anomaly activation")


def validate_run_summary(value: Mapping[str, object]) -> None:
    _validate_run_summary(value, required_diagnostics_version=5)


def validate_sealed_version_four_run_summary(value: Mapping[str, object]) -> None:
    """Validate immutable version-4 evidence through the explicit sealed path."""
    _validate_run_summary(value, required_diagnostics_version=4)


def validate_sealed_operational_run_summary(value: Mapping[str, object]) -> None:
    """Validate immutable version-3 evidence through the explicit sealed path."""
    _validate_run_summary(value, required_diagnostics_version=3)


def validate_legacy_run_summary(value: Mapping[str, object]) -> None:
    """Validate immutable version-2 evidence through the explicit legacy path."""
    _validate_run_summary(value, required_diagnostics_version=2)


def _validate_run_summary(
    value: Mapping[str, object],
    *,
    required_diagnostics_version: int,
) -> None:
    _exact_keys(
        value,
        {
            "object_kind",
            "code_identity",
            "runtime_identity",
            "policy_identity",
            "runtime_started_monotonic_ms",
            "clean_stop_monotonic_ms",
            "operational_diagnostics",
            "coverage_segments",
            "coverage",
            "band_suspended_duration_ms",
            "counts_by_scope",
            "detector_unknown_transition_count_by_reason",
            "anomaly_end_count_by_reason",
            "known_active_duration_ms_sum_by_end_reason",
            "public_atomic_quote_state_transition_count",
            "non_claims",
        },
        "RADAR_RUN_SUMMARY",
    )
    if value["object_kind"] != "RADAR_RUN_SUMMARY":
        raise EvidenceError("wrong summary object_kind")
    _validate_non_claims(value["non_claims"], SUMMARY_NON_CLAIMS, "summary")
    _validate_identity_fields(value)
    diagnostics = _mapping(value["operational_diagnostics"], "operational_diagnostics")
    diagnostics_version = diagnostics.get("operational_diagnostics_schema_version")
    current_version_invalid = required_diagnostics_version == 5 and (
        type(diagnostics_version) is not int or diagnostics_version != 5
    )
    if current_version_invalid or diagnostics_version != required_diagnostics_version:
        if required_diagnostics_version == 5:
            raise EvidenceError(
                "current run-summary validator requires integer diagnostics schema version 5"
            )
        if required_diagnostics_version == 4:
            raise EvidenceError(
                "sealed operational run-summary validator requires diagnostics schema version 4"
            )
        if required_diagnostics_version == 3:
            raise EvidenceError(
                "sealed operational run-summary validator requires diagnostics schema version 3"
            )
        raise EvidenceError("legacy run-summary validator requires diagnostics schema version 2")
    raw_segments = value["coverage_segments"]
    if not isinstance(raw_segments, list) or not raw_segments:
        raise EvidenceError("coverage_segments must be non-empty")
    segments = tuple(
        _parse_segment(item, diagnostics_version=diagnostics_version) for item in raw_segments
    )
    expected = _coverage_object(segments)
    if value["coverage"] != expected:
        raise EvidenceError("coverage totals do not match exact segments")
    if value["runtime_started_monotonic_ms"] != segments[0].start_monotonic_ms:
        raise EvidenceError("summary start does not match coverage")
    if value["clean_stop_monotonic_ms"] != segments[-1].end_monotonic_ms:
        raise EvidenceError("summary stop does not match coverage")
    _validate_scope_counts(value["counts_by_scope"])
    _validate_operational_diagnostics(
        diagnostics,
        observation_interval_ms=expected["observation_interval_ms"],
        runtime_started_monotonic_ms=segments[0].start_monotonic_ms,
        clean_stop_monotonic_ms=segments[-1].end_monotonic_ms,
        coverage_segments=segments,
        counts_by_scope=_array(value["counts_by_scope"], "counts_by_scope"),
        policy_identity=_required_string(value, "policy_identity"),
    )
    _non_negative_integer(value["band_suspended_duration_ms"], "band_suspended_duration_ms")
    for field in (
        "detector_unknown_transition_count_by_reason",
        "anomaly_end_count_by_reason",
        "known_active_duration_ms_sum_by_end_reason",
        "public_atomic_quote_state_transition_count",
    ):
        _validate_count_mapping(value[field], field)
    scopes = _array(value["counts_by_scope"], "counts_by_scope")
    scope_ends: Counter[str] = Counter()
    scope_durations: Counter[str] = Counter()
    scope_atomic: Counter[str] = Counter()
    for raw_scope in scopes:
        scope = _mapping(raw_scope, "scope count")
        if scope["policy_identity"] != value["policy_identity"]:
            raise EvidenceError("scope Policy identity does not match summary")
        _merge_counts(scope_ends, scope["anomaly_end_count_by_reason"], "scope episode ends")
        _merge_counts(
            scope_durations,
            scope["known_active_duration_ms_sum_by_end_reason"],
            "scope active durations",
        )
        _merge_counts(
            scope_atomic,
            scope["public_atomic_quote_state_transition_count"],
            "scope atomic transitions",
        )
    global_ends: Counter[str] = Counter()
    global_durations: Counter[str] = Counter()
    global_atomic: Counter[str] = Counter()
    _merge_counts(
        global_ends,
        value["anomaly_end_count_by_reason"],
        "anomaly_end_count_by_reason",
    )
    _merge_counts(
        global_durations,
        value["known_active_duration_ms_sum_by_end_reason"],
        "known_active_duration_ms_sum_by_end_reason",
    )
    _merge_counts(
        global_atomic,
        value["public_atomic_quote_state_transition_count"],
        "public_atomic_quote_state_transition_count",
    )
    if scope_ends != global_ends:
        raise EvidenceError("global episode ends do not match scope totals")
    if scope_durations != global_durations:
        raise EvidenceError("global active durations do not match scope totals")
    if scope_atomic != global_atomic:
        raise EvidenceError("global atomic transitions do not match scope totals")


def validate_evidence_directory(directory: Path) -> tuple[dict[str, object], ...]:
    return _validate_evidence_directory(directory, diagnostics_version=5)


def validate_sealed_version_four_evidence_directory(
    directory: Path,
) -> tuple[dict[str, object], ...]:
    """Validate a sealed version-4 directory without rewriting or migrating it."""
    return _validate_evidence_directory(directory, diagnostics_version=4)


def validate_sealed_operational_evidence_directory(
    directory: Path,
) -> tuple[dict[str, object], ...]:
    """Validate a sealed version-3 directory without rewriting or migrating it."""
    return _validate_evidence_directory(directory, diagnostics_version=3)


def validate_legacy_evidence_directory(
    directory: Path,
) -> tuple[dict[str, object], ...]:
    """Validate a sealed version-2 directory without rewriting or migrating it."""
    return _validate_evidence_directory(directory, diagnostics_version=2)


def operational_soak_window_accounting(
    summary: Mapping[str, object],
) -> dict[str, int]:
    """Project the frozen final-hour K/P/G/E/U ledgers from strict version-5 evidence."""
    validate_run_summary(summary)
    clean_stop_ms = _non_negative_integer(
        summary["clean_stop_monotonic_ms"],
        "clean_stop_monotonic_ms",
    )
    runtime_start_ms = _non_negative_integer(
        summary["runtime_started_monotonic_ms"],
        "runtime_started_monotonic_ms",
    )
    window_start_ms = clean_stop_ms - OPTION_LOCAL_ACCEPTANCE_WINDOW_MS
    if window_start_ms < 0 or runtime_start_ms > window_start_ms:
        raise EvidenceError("operational Soak runtime must cover the complete final hour")
    segments = tuple(
        _parse_segment(item, diagnostics_version=5)
        for item in _array(summary["coverage_segments"], "coverage_segments")
    )
    known_complete_ms = 0
    pending_ms = 0
    global_incident_ms = 0
    effective_intervals: list[tuple[int, int]] = []
    for segment in segments:
        start = max(window_start_ms, segment.start_monotonic_ms)
        end = min(clean_stop_ms, segment.end_monotonic_ms)
        if end <= start:
            continue
        duration = end - start
        reasons = {group.blocking_reason for group in segment.blocking_groups}
        is_pending = bool(reasons & SOAK_PENDING_REASONS)
        is_global_incident = bool(reasons & SOAK_GLOBAL_CURRENTNESS_REASONS)
        if segment.state is CoverageState.KNOWN_COMPLETE:
            known_complete_ms += duration
        if is_pending:
            pending_ms += duration
        if is_global_incident:
            global_incident_ms += duration
        if not is_pending and not is_global_incident:
            effective_intervals.append((start, end))

    diagnostics = _mapping(summary["operational_diagnostics"], "operational_diagnostics")
    availability = _mapping(
        diagnostics["option_local_availability"],
        "operational_diagnostics.option_local_availability",
    )
    if _non_negative_integer(
        availability["omitted_interval_count"],
        "option_local_availability.omitted_interval_count",
    ):
        raise EvidenceError("operational Soak accounting requires zero omitted local intervals")
    unavailable_intersections: list[tuple[int, int]] = []
    for raw_interval in _array(
        availability["intervals"],
        "option_local_availability.intervals",
    ):
        interval = _mapping(raw_interval, "option-local availability interval")
        interval_start = _non_negative_integer(
            interval["start_monotonic_ms"],
            "option-local interval start",
        )
        interval_end = _non_negative_integer(
            interval["end_monotonic_ms"],
            "option-local interval end",
        )
        for effective_start, effective_end in effective_intervals:
            start = max(interval_start, effective_start)
            end = min(interval_end, effective_end)
            if end > start:
                unavailable_intersections.append((start, end))

    return {
        "window_start_monotonic_ms": window_start_ms,
        "window_end_monotonic_ms": clean_stop_ms,
        "known_complete_ms": known_complete_ms,
        "normal_boundary_pending_ms": pending_ms,
        "global_currentness_incident_ms": global_incident_ms,
        "effective_option_local_denominator_ms": _interval_union_duration(effective_intervals),
        "option_local_unavailable_union_ms": _interval_union_duration(unavailable_intersections),
    }


def _validate_evidence_directory(
    directory: Path,
    *,
    diagnostics_version: int,
) -> tuple[dict[str, object], ...]:
    objects: list[dict[str, object]] = []
    identities: set[tuple[object, object, object]] = set()
    anomalies_by_episode: dict[str, dict[str, object]] = {}
    atomic_events: list[dict[str, object]] = []
    atomic_identities: set[tuple[str, str]] = set()
    summaries: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_strict_evidence_object,
                parse_constant=_reject_evidence_constant,
            )
        except (OSError, json.JSONDecodeError, EvidenceError) as exc:
            raise EvidenceError(f"invalid evidence file: {path}") from exc
        if not isinstance(value, dict):
            raise EvidenceError(f"evidence file must contain an object: {path}")
        kind = value.get("object_kind")
        if kind == "SHORT_VOL_ANOMALY_EVENT":
            validate_anomaly_event(value)
            episode_identity = _required_string(value, "episode_identity")
            if episode_identity in anomalies_by_episode:
                raise EvidenceError("evidence directory duplicates an anomaly episode identity")
            anomalies_by_episode[episode_identity] = value
        elif kind == "PUBLIC_ATOMIC_QUOTE_EVENT":
            validate_atomic_event(value)
            atomic_identity = (
                _required_string(value, "episode_identity"),
                _required_string(value, "combo_instrument_name"),
            )
            if atomic_identity in atomic_identities:
                raise EvidenceError("evidence directory duplicates an atomic quote identity")
            atomic_identities.add(atomic_identity)
            atomic_events.append(value)
        elif kind == "RADAR_RUN_SUMMARY":
            if diagnostics_version == 2:
                validate_legacy_run_summary(value)
            elif diagnostics_version == 3:
                validate_sealed_operational_run_summary(value)
            elif diagnostics_version == 4:
                validate_sealed_version_four_run_summary(value)
            else:
                validate_run_summary(value)
            summaries.append(value)
        else:
            raise EvidenceError(f"unknown evidence object_kind in {path}")
        identities.add(
            (
                value.get("code_identity"),
                value.get("runtime_identity"),
                value.get("policy_identity"),
            )
        )
        objects.append(value)
    if len(identities) > 1:
        raise EvidenceError("evidence directory mixes code, runtime, or Policy identities")
    if len(summaries) > 1:
        raise EvidenceError("evidence directory contains more than one run summary")
    for atomic in atomic_events:
        episode_identity = _required_string(atomic, "episode_identity")
        anomaly = anomalies_by_episode.get(episode_identity)
        if anomaly is None:
            raise EvidenceError("atomic evidence references an absent anomaly episode")
        if any(
            atomic[field] != anomaly[field]
            for field in (
                "code_identity",
                "runtime_identity",
                "policy_identity",
                "target_base_quantity_btc",
            )
        ):
            raise EvidenceError(
                "atomic and anomaly evidence identity, Policy, runtime, or target mismatch"
            )
        anomaly_instrument = _mapping(
            anomaly["instrument"],
            "anomaly instrument",
        )
        if atomic["short_instrument_name"] != anomaly_instrument["instrument_name"]:
            raise EvidenceError("atomic short leg does not match its anomaly instrument")
        detector_causal_seq = _non_negative_integer(
            atomic["detector_causal_seq"],
            "atomic detector_causal_seq",
        )
        anomaly_causal_seq = _non_negative_integer(
            anomaly["causal_seq"],
            "anomaly causal_seq",
        )
        quote_causal_seq = _non_negative_integer(
            atomic["quote_causal_seq"],
            "atomic quote_causal_seq",
        )
        validate_atomic_causal_invariant(
            anomaly_activation_seq=anomaly_causal_seq,
            detector_causal_seq=detector_causal_seq,
            quote_causal_seq=quote_causal_seq,
        )
    if summaries:
        counts = _array(summaries[0]["counts_by_scope"], "counts_by_scope")
        declared_by_scope: Counter[tuple[str, str, str]] = Counter()
        atomic_available_by_scope: Counter[tuple[str, str, str]] = Counter()
        for item in counts:
            row = _mapping(item, "scope count")
            identity = (
                _required_string(row, "policy_identity"),
                _required_string(row, "option_type"),
                _required_string(row, "tte_band_id"),
            )
            declared_by_scope[identity] = _non_negative_integer(
                row["distinct_anomaly_episode_count"],
                "scope distinct_anomaly_episode_count",
            )
            scope_atomic_transitions = _mapping(
                row["public_atomic_quote_state_transition_count"],
                "scope public atomic quote transitions",
            )
            atomic_available_by_scope[identity] = _non_negative_integer(
                scope_atomic_transitions.get("PUBLIC_ATOMIC_QUOTE_AVAILABLE", 0),
                "scope PUBLIC_ATOMIC_QUOTE_AVAILABLE transition count",
            )
        actual_by_scope: Counter[tuple[str, str, str]] = Counter()
        for anomaly in anomalies_by_episode.values():
            instrument = _mapping(anomaly["instrument"], "anomaly instrument")
            actual_by_scope[
                (
                    _required_string(anomaly, "policy_identity"),
                    _required_string(instrument, "option_type"),
                    _required_string(anomaly, "activation_band_id"),
                )
            ] += 1
        if diagnostics_version == 2:
            if sum(declared_by_scope.values()) != len(anomalies_by_episode):
                raise EvidenceError("summary episode count does not match anomaly evidence")
        elif declared_by_scope != actual_by_scope:
            raise EvidenceError(
                "summary scope episode counts do not match anomaly option_type and band"
            )
        if diagnostics_version >= 3:
            for atomic in atomic_events:
                anomaly = anomalies_by_episode[_required_string(atomic, "episode_identity")]
                instrument = _mapping(anomaly["instrument"], "anomaly instrument")
                owning_scope = (
                    _required_string(anomaly, "policy_identity"),
                    _required_string(instrument, "option_type"),
                    _required_string(anomaly, "activation_band_id"),
                )
                if atomic_available_by_scope[owning_scope] <= 0:
                    raise EvidenceError(
                        "atomic event lacks a PUBLIC_ATOMIC_QUOTE_AVAILABLE transition "
                        "in its owning summary scope"
                    )
    return tuple(objects)


def _interval_union_duration(intervals: Sequence[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    return total + current_end - current_start


def ratio_or_none(numerator: int, denominator: int | None) -> Decimal | None:
    if denominator in {None, 0}:
        return None
    if numerator < 0 or denominator < 0:
        raise ValueError("rate counts must be non-negative")
    return Decimal(numerator) / Decimal(denominator)


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise EvidenceError("evidence Decimal must be finite")
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
    total = sum(counts.values())
    return {
        "observation_interval_ms": observation,
        "known_complete_ms": counts[CoverageState.KNOWN_COMPLETE],
        "known_degraded_ms": counts[CoverageState.KNOWN_DEGRADED],
        "unknown_ms": counts[CoverageState.UNKNOWN],
        "no_applicable_scope_ms": counts[CoverageState.NO_APPLICABLE_SCOPE],
        "coverage_partition_error_ms": observation - total,
    }


def _parse_segment(value: object, *, diagnostics_version: int) -> CoverageSegment:
    if not isinstance(value, dict):
        raise EvidenceError("coverage segment must be an object")
    fields = {"start_monotonic_ms", "end_monotonic_ms", "state"}
    if diagnostics_version == 3:
        fields.update({"reason", "affected_scopes", "global_continuity_epoch"})
    elif diagnostics_version in {4, 5}:
        fields.update(
            {
                "trigger_cause",
                "blocking_reason",
                "affected_scopes",
                "global_continuity_epoch",
            }
        )
        if diagnostics_version == 5:
            fields.add("blocking_groups")
    _exact_keys(value, fields, "coverage segment")
    try:
        state = CoverageState(value["state"])
    except (ValueError, TypeError) as exc:
        raise EvidenceError("invalid coverage state") from exc
    start = value["start_monotonic_ms"]
    end = value["end_monotonic_ms"]
    if isinstance(start, bool) or not isinstance(start, int):
        raise EvidenceError("coverage start must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise EvidenceError("coverage end must be an integer")
    if diagnostics_version == 2:
        return CoverageSegment(
            start,
            end,
            state,
            reason=CausalCause.RUNTIME_START.value,
            blocking_reason=CoverageBlockingReason.LEGACY_UNATTRIBUTED.value,
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        )
    reason = _required_string(
        value,
        "reason" if diagnostics_version == 3 else "trigger_cause",
    )
    try:
        CausalCause(reason)
    except ValueError as exc:
        raise EvidenceError("coverage reason is outside the causal cause whitelist") from exc
    affected_scopes = _validate_affected_scopes(value["affected_scopes"])
    blocking_reason = (
        CoverageBlockingReason.LEGACY_UNATTRIBUTED.value
        if diagnostics_version == 3
        else _required_string(value, "blocking_reason")
    )
    try:
        CoverageBlockingReason(blocking_reason)
    except ValueError as exc:
        raise EvidenceError("coverage blocking_reason is outside the bounded allowlist") from exc
    if diagnostics_version >= 4:
        if state is CoverageState.KNOWN_COMPLETE:
            if blocking_reason != CoverageBlockingReason.NONE.value:
                raise EvidenceError("KNOWN_COMPLETE coverage must have no blocking reason")
        elif blocking_reason == CoverageBlockingReason.NONE.value:
            raise EvidenceError("incomplete coverage must identify its blocking reason")
        if (
            state is CoverageState.NO_APPLICABLE_SCOPE
            and blocking_reason != CoverageBlockingReason.NO_APPLICABLE_SCOPE.value
        ):
            raise EvidenceError(
                "NO_APPLICABLE_SCOPE coverage must identify the matching blocking reason"
            )
    blocking_groups: tuple[CoverageBlockingGroup, ...] = ()
    if diagnostics_version == 5:
        blocking_groups = _parse_coverage_blocking_groups(
            value["blocking_groups"],
            state=state,
        )
        if state is CoverageState.KNOWN_COMPLETE:
            if blocking_groups:
                raise EvidenceError("KNOWN_COMPLETE coverage must have no blocking groups")
        else:
            expected_reason = (
                blocking_groups[0].blocking_reason
                if len(blocking_groups) == 1
                else CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value
            )
            if blocking_reason != expected_reason:
                raise EvidenceError("coverage blocking_reason does not summarize blocking groups")
            expected_scopes = _summarize_blocking_group_scopes(blocking_groups)
            if affected_scopes != expected_scopes:
                raise EvidenceError("coverage affected_scopes do not summarize blocking groups")
        if state is CoverageState.NO_APPLICABLE_SCOPE and (
            len(blocking_groups) != 1
            or blocking_groups[0].blocking_reason
            != CoverageBlockingReason.NO_APPLICABLE_SCOPE.value
        ):
            raise EvidenceError(
                "NO_APPLICABLE_SCOPE coverage must have one matching blocking group"
            )
    epoch = _positive_integer(
        value["global_continuity_epoch"],
        "coverage segment global_continuity_epoch",
    )
    return CoverageSegment(
        start,
        end,
        state,
        reason=reason,
        blocking_reason=blocking_reason,
        affected_scopes=affected_scopes,
        global_continuity_epoch=epoch,
        blocking_groups=blocking_groups,
    )


def _validate_scope_counts(value: object) -> None:
    if not isinstance(value, list):
        raise EvidenceError("counts_by_scope must be an array")
    required = {
        "policy_identity",
        "option_type",
        "tte_band_id",
        "applicable_instrument_count",
        "known_per_instrument_detector_evaluation_count",
        "known_full_detector_formula_evaluation_count",
        "complete_aggregate_detector_evaluation_count",
        "complete_aggregate_with_full_formula_evaluation_count",
        "known_full_formula_rate_given_known_per_instrument",
        "complete_aggregate_with_full_formula_rate_given_complete_aggregate",
        "distinct_anomaly_episode_count",
        "anomaly_activation_transition_count",
        "anomaly_end_count_by_reason",
        "known_active_duration_ms_sum_by_end_reason",
        "public_atomic_quote_state_transition_count",
    }
    identities: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise EvidenceError("scope count must be an object")
        _exact_keys(item, required, "scope count")
        rate_fields = {
            "known_full_formula_rate_given_known_per_instrument",
            "complete_aggregate_with_full_formula_rate_given_complete_aggregate",
        }
        for key in required - {
            "policy_identity",
            "option_type",
            "tte_band_id",
            *rate_fields,
            "anomaly_end_count_by_reason",
            "known_active_duration_ms_sum_by_end_reason",
            "public_atomic_quote_state_transition_count",
        }:
            number = item[key]
            if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                raise EvidenceError(f"scope count {key} must be a non-negative integer")
        for key in rate_fields:
            rate = item[key]
            if rate is not None and _decimal_text_value(rate, f"scope count {key}") < 0:
                raise EvidenceError(f"scope count {key} must be non-negative or null")
        expected_rates = {
            "known_full_formula_rate_given_known_per_instrument": ratio_or_none(
                item["known_full_detector_formula_evaluation_count"],
                item["known_per_instrument_detector_evaluation_count"],
            ),
            "complete_aggregate_with_full_formula_rate_given_complete_aggregate": ratio_or_none(
                item["complete_aggregate_with_full_formula_evaluation_count"],
                item["complete_aggregate_detector_evaluation_count"],
            ),
        }
        if (
            item["known_full_detector_formula_evaluation_count"]
            > item["known_per_instrument_detector_evaluation_count"]
        ):
            raise EvidenceError("scope full-formula count exceeds known evaluations")
        if (
            item["complete_aggregate_with_full_formula_evaluation_count"]
            > item["complete_aggregate_detector_evaluation_count"]
        ):
            raise EvidenceError("scope aggregate full-formula count exceeds complete aggregates")
        if item["distinct_anomaly_episode_count"] != item["anomaly_activation_transition_count"]:
            raise EvidenceError("scope episode and activation counts differ")
        end_counts = _mapping(
            item["anomaly_end_count_by_reason"],
            "scope count anomaly_end_count_by_reason",
        )
        if (
            sum(
                _non_negative_integer(count, "scope episode end count")
                for count in end_counts.values()
            )
            != item["distinct_anomaly_episode_count"]
        ):
            raise EvidenceError("scope episode ends do not match distinct episodes")
        for key, expected_rate in expected_rates.items():
            expected_serialized = decimal_text(expected_rate) if expected_rate is not None else None
            if item[key] != expected_serialized:
                raise EvidenceError(f"scope count {key} does not match its counts")
        for key in (
            "anomaly_end_count_by_reason",
            "known_active_duration_ms_sum_by_end_reason",
            "public_atomic_quote_state_transition_count",
        ):
            _validate_count_mapping(item[key], f"scope count {key}")
        for key in ("policy_identity", "option_type", "tte_band_id"):
            if not isinstance(item[key], str) or not item[key]:
                raise EvidenceError(f"scope count {key} must be a non-empty string")
        identity = (
            item["policy_identity"],
            item["option_type"],
            item["tte_band_id"],
        )
        if identity in identities:
            raise EvidenceError("counts_by_scope identities must be unique")
        identities.add(identity)


def _validate_operational_diagnostics(
    value: object,
    *,
    observation_interval_ms: int,
    runtime_started_monotonic_ms: int,
    clean_stop_monotonic_ms: int,
    coverage_segments: tuple[CoverageSegment, ...],
    counts_by_scope: list[object],
    policy_identity: str,
) -> None:
    diagnostics = _mapping(value, "operational_diagnostics")
    version = diagnostics.get("operational_diagnostics_schema_version")
    if version == 5 and type(version) is not int:
        raise EvidenceError("current operational diagnostics schema version must be integer 5")
    if version not in {2, 3, 4, 5}:
        raise EvidenceError("operational diagnostics schema version must be 2, 3, 4, or 5")
    fields = {
        "operational_diagnostics_schema_version",
        "runtime_limits",
        "ingress",
        "rpc_by_method",
        "channel_by_class",
        "subscriptions",
        "heartbeat",
        "recovery",
        "source_shapes",
        "witness",
    }
    if version >= 3:
        fields.update(
            {
                "global_continuity",
                "ticker_application",
                "ticker_currentness",
                "option_local_availability",
                "rpc_orphan_late_wire_count",
            }
        )
    if version >= 4:
        fields.add("transport_terminal_attribution")
    _exact_keys(
        diagnostics,
        fields,
        "operational_diagnostics",
    )
    _validate_runtime_limits(diagnostics["runtime_limits"])
    _validate_ingress_diagnostics(
        diagnostics["ingress"],
        diagnostics_version=version,
    )
    _validate_rpc_diagnostics(diagnostics["rpc_by_method"], diagnostics_version=version)
    if version >= 3:
        _non_negative_integer(
            diagnostics["rpc_orphan_late_wire_count"],
            "rpc_orphan_late_wire_count",
        )
    _validate_channel_diagnostics(
        diagnostics["channel_by_class"],
        observation_interval_ms=observation_interval_ms,
    )
    _validate_named_non_negative_counts(
        diagnostics["subscriptions"],
        {
            "current_subscribed_instrument_count",
            "peak_subscribed_instrument_count",
            "current_subscribed_channel_count",
            "peak_subscribed_channel_count",
        },
        "operational_diagnostics.subscriptions",
    )
    subscriptions = _mapping(
        diagnostics["subscriptions"],
        "operational_diagnostics.subscriptions",
    )
    current_instruments = _non_negative_integer(
        subscriptions["current_subscribed_instrument_count"],
        "current_subscribed_instrument_count",
    )
    peak_instruments = _non_negative_integer(
        subscriptions["peak_subscribed_instrument_count"],
        "peak_subscribed_instrument_count",
    )
    current_channels = _non_negative_integer(
        subscriptions["current_subscribed_channel_count"],
        "current_subscribed_channel_count",
    )
    peak_channels = _non_negative_integer(
        subscriptions["peak_subscribed_channel_count"],
        "peak_subscribed_channel_count",
    )
    if current_instruments > peak_instruments or current_channels > peak_channels:
        raise EvidenceError("current subscriptions exceed peak subscriptions")
    _validate_named_non_negative_counts(
        diagnostics["heartbeat"],
        {
            "test_request_count",
            "public_test_success_count",
            "public_test_error_count",
            "latency_observation_count",
            "latency_ms_sum",
            "latency_ms_max",
        },
        "operational_diagnostics.heartbeat",
    )
    _validate_latency_totals(
        _mapping(diagnostics["heartbeat"], "operational_diagnostics.heartbeat"),
        "operational_diagnostics.heartbeat",
    )
    _validate_named_non_negative_counts(
        diagnostics["recovery"],
        {
            "reconnect_count",
            "session_gap_count",
            "index_gap_count",
            "index_resubscribe_count",
            "option_channel_resync_count",
            "clock_refresh_attempt_count",
            "clock_refresh_success_count",
            "clock_refresh_failure_count",
            "option_catalog_refresh_attempt_count",
            "option_catalog_refresh_success_count",
            "option_catalog_refresh_failure_count",
            "combo_authoritative_refresh_attempt_count",
            "combo_authoritative_refresh_success_count",
            "combo_authoritative_refresh_failure_count",
        },
        "operational_diagnostics.recovery",
    )
    source_shape_counts = _validate_source_shapes(diagnostics["source_shapes"])
    current_epoch = 1
    restart_edges: tuple[Mapping[str, object], ...] = ()
    recovery_edges: Mapping[int, Mapping[str, object]] = {}
    current_epoch_joint_counts: Mapping[
        tuple[str, int, str, str, str],
        tuple[int, Mapping[str, object] | None],
    ] = {}
    if version >= 3:
        _validate_cross_ledger_conservation(
            diagnostics,
            source_shape_counts=source_shape_counts,
        )
        (
            current_epoch,
            restart_edges,
            recovery_edges,
            current_epoch_joint_counts,
        ) = _validate_global_continuity(
            diagnostics["global_continuity"],
            runtime_started_monotonic_ms=runtime_started_monotonic_ms,
            clean_stop_monotonic_ms=clean_stop_monotonic_ms,
            diagnostics_version=version,
        )
        ticker_application = _validate_ticker_application(diagnostics["ticker_application"])
        ticker_currentness = _validate_ticker_currentness(diagnostics["ticker_currentness"])
        ticker_observed, ticker_valid, ticker_invalid = source_shape_counts["option_ticker"]
        if ticker_observed != sum(ticker_application.values()):
            raise EvidenceError(
                "ticker conservation does not reconcile received shapes and dispositions"
            )
        if ticker_invalid != ticker_application["SHAPE_REJECTED"]:
            raise EvidenceError(
                "ticker conservation does not reconcile shape rejects and dispositions"
            )
        if ticker_valid != sum(ticker_currentness.values()):
            raise EvidenceError(
                "ticker conservation does not reconcile valid shapes and currentness"
            )
        _validate_option_local_availability(
            diagnostics["option_local_availability"],
            runtime_started_monotonic_ms=runtime_started_monotonic_ms,
            clean_stop_monotonic_ms=clean_stop_monotonic_ms,
            current_epoch=current_epoch,
            diagnostics_version=version,
        )
        _validate_version_three_coverage(
            coverage_segments,
            current_epoch=current_epoch,
            restart_edges=restart_edges,
            recovery_edges=recovery_edges,
            diagnostics_version=version,
        )
    if version >= 4:
        ingress = _mapping(
            diagnostics["ingress"],
            "operational_diagnostics.ingress",
        )
        _validate_transport_terminal_attribution(
            diagnostics["transport_terminal_attribution"],
            connection_error_event_count=_non_negative_integer(
                ingress["connection_error_event_count"],
                "ingress.connection_error_event_count",
            ),
        )
    witness = _mapping(diagnostics["witness"], "operational_diagnostics.witness")
    witness_fields = {
        "first_joint_witness_monotonic_ms",
        (
            "continuous_covered_after_witness_ms"
            if version == 2
            else "continuous_global_continuity_after_witness_ms"
        ),
    }
    if version >= 3:
        witness_fields.update(
            {
                "global_continuity_epoch",
                "scope",
                "boundary",
                "formula_instrument",
            }
        )
    _exact_keys(witness, witness_fields, "operational_diagnostics.witness")
    if version >= 3:
        witness_epoch = _positive_integer(
            witness["global_continuity_epoch"],
            "witness.global_continuity_epoch",
        )
        if witness_epoch != current_epoch:
            raise EvidenceError("witness continuity epoch does not match current epoch")
    first = witness["first_joint_witness_monotonic_ms"]
    duration = witness[
        (
            "continuous_covered_after_witness_ms"
            if version == 2
            else "continuous_global_continuity_after_witness_ms"
        )
    ]
    if (first is None) != (duration is None):
        raise EvidenceError("joint witness time and continuous duration must both be null or known")
    if version >= 3:
        identities = (
            witness["scope"],
            witness["boundary"],
            witness["formula_instrument"],
        )
        if first is None and any(identity is not None for identity in identities):
            raise EvidenceError("null joint witness must not carry witness identity")
        if first is not None and any(identity is None for identity in identities):
            raise EvidenceError("known joint witness is missing its witness identity")
    if first is not None and duration is not None:
        if version == 2:
            ingress = _mapping(
                diagnostics["ingress"],
                "operational_diagnostics.ingress",
            )
            if ingress["ingress_gap_or_duplicate_count"] != 0 or ingress["overflow_count"] != 0:
                raise EvidenceError("joint witness cannot cross an ingress gap or queue overflow")
        first_ms = _non_negative_integer(first, "first_joint_witness_monotonic_ms")
        duration_ms = _non_negative_integer(duration, "continuous_covered_after_witness_ms")
        if not runtime_started_monotonic_ms <= first_ms <= clean_stop_monotonic_ms:
            raise EvidenceError("joint witness time must be within the runtime interval")
        if duration_ms != clean_stop_monotonic_ms - first_ms:
            raise EvidenceError("joint witness continuous duration must equal stop minus first")
        if version >= 3:
            current_epoch_start = next(
                segment.start_monotonic_ms
                for segment in coverage_segments
                if segment.global_continuity_epoch == current_epoch
            )
            if first_ms <= current_epoch_start:
                raise EvidenceError(
                    "joint witness boundary must be strictly later than the current epoch start"
                )
            witness_segments = tuple(
                segment
                for segment in coverage_segments
                if (
                    segment.global_continuity_epoch == current_epoch
                    and segment.start_monotonic_ms <= first_ms < segment.end_monotonic_ms
                )
            )
            if (
                len(witness_segments) != 1
                or witness_segments[0].state is not CoverageState.KNOWN_COMPLETE
            ):
                raise EvidenceError(
                    "joint witness must fall inside a current-epoch KNOWN_COMPLETE segment"
                )
            boundary = _validate_fact_boundary(
                witness["boundary"],
                "witness.boundary",
            )
            if boundary["received_monotonic_ms"] != first_ms:
                raise EvidenceError("witness identity boundary does not match witness time")
            scope = _validate_witness_scope(witness["scope"])
            instrument = _validate_witness_formula_instrument(witness["formula_instrument"])
            if any(
                scope[field] != instrument[field]
                for field in (
                    "expiration_timestamp_ms",
                    "option_type",
                    "tte_band_id",
                )
            ):
                raise EvidenceError("witness identity scope and formula instrument do not match")
            scope_option_type = _required_string(scope, "option_type")
            scope_band_id = _required_string(scope, "tte_band_id")
            matching_counts = tuple(
                _mapping(raw_scope, "scope count")
                for raw_scope in counts_by_scope
                if (
                    isinstance(raw_scope, dict)
                    and raw_scope.get("policy_identity") == policy_identity
                    and raw_scope.get("option_type") == scope_option_type
                    and raw_scope.get("tte_band_id") == scope_band_id
                )
            )
            if len(matching_counts) != 1:
                raise EvidenceError("joint witness must bind exactly one real counts_by_scope row")
            joint_count = _positive_integer(
                matching_counts[0]["complete_aggregate_with_full_formula_evaluation_count"],
                "joint witness full-formula count",
            )
            if joint_count <= 0:
                raise EvidenceError("joint witness full-formula count must be positive")
            current_joint_evaluation = current_epoch_joint_counts.get(
                (
                    policy_identity,
                    _positive_integer(
                        scope["expiration_timestamp_ms"],
                        "witness scope expiration_timestamp_ms",
                    ),
                    scope_option_type,
                    scope_band_id,
                    _required_string(instrument, "instrument_name"),
                ),
            )
            if current_joint_evaluation is None or current_joint_evaluation[0] <= 0:
                raise EvidenceError(
                    "joint witness must bind a current-epoch joint scope evaluation"
                )
            current_joint_count, first_joint_boundary = current_joint_evaluation
            if current_joint_count > joint_count:
                raise EvidenceError(
                    "current-epoch joint scope count exceeds its cumulative counts_by_scope row"
                )
            if first_joint_boundary is None or _fact_boundary_order(
                first_joint_boundary
            ) != _fact_boundary_order(boundary):
                raise EvidenceError(
                    "joint witness boundary does not match its current-epoch joint evaluation"
                )
            if restart_edges:
                latest_incident_id = len(restart_edges)
                recovery = recovery_edges.get(latest_incident_id)
                if recovery is None:
                    raise EvidenceError(
                        "known witness requires strict recovery of the latest incident"
                    )
                recovery_boundary = _mapping(
                    recovery["boundary"],
                    "global continuity recovery boundary",
                )
                if _fact_boundary_order(recovery_boundary) >= _fact_boundary_order(boundary):
                    raise EvidenceError(
                        "latest incident recovery must be strictly before the known witness"
                    )


def _validate_runtime_limits(value: object) -> None:
    limits = _mapping(value, "operational_diagnostics.runtime_limits")
    fields = {
        "heartbeat_interval_seconds",
        "session_liveness_deadline_ms",
        "rpc_deadline_ms",
        "clock_refresh_interval_ms",
        "clock_stale_deadline_ms",
        "index_source_stale_deadline_ms",
        "ticker_source_stale_deadline_ms",
        "notification_queue_lag_deadline_ms",
        "time_boundary_poll_interval_ms",
    }
    _exact_keys(limits, fields, "operational_diagnostics.runtime_limits")
    parsed = {
        field: _positive_integer(limits[field], f"runtime_limits.{field}") for field in fields
    }
    if parsed["time_boundary_poll_interval_ms"] > 1_000:
        raise EvidenceError("time boundary poll interval exceeds one second")
    if parsed["time_boundary_poll_interval_ms"] > parsed["ticker_source_stale_deadline_ms"]:
        raise EvidenceError("ticker source stale deadline does not cover poll interval")
    if parsed["rpc_deadline_ms"] < parsed["time_boundary_poll_interval_ms"]:
        raise EvidenceError("RPC deadline does not cover time-boundary poll interval")
    if parsed["session_liveness_deadline_ms"] <= parsed["heartbeat_interval_seconds"] * 1_000:
        raise EvidenceError("session liveness deadline does not exceed heartbeat interval")
    if parsed["clock_stale_deadline_ms"] <= parsed["clock_refresh_interval_ms"]:
        raise EvidenceError("clock stale deadline does not exceed refresh interval")


def _validate_ingress_diagnostics(
    value: object,
    *,
    diagnostics_version: int,
) -> None:
    ingress = _mapping(value, "operational_diagnostics.ingress")
    fields = {
        "received_envelope_count",
        "reduced_envelope_count",
        "ingress_gap_or_duplicate_count",
        "queue_high_water_frames",
        "max_receive_to_reduce_lag_ms",
        "overflow_count",
    }
    if diagnostics_version >= 3:
        fields.update(
            {
                "send_control_event_count",
                "connection_error_event_count",
            }
        )
    _validate_named_non_negative_counts(
        ingress,
        fields,
        "operational_diagnostics.ingress",
    )
    reduced = _non_negative_integer(
        ingress["reduced_envelope_count"],
        "reduced_envelope_count",
    )
    received = _non_negative_integer(
        ingress["received_envelope_count"],
        "received_envelope_count",
    )
    if reduced != received:
        raise EvidenceError("clean-stop envelope counts must match exactly")


def _validate_rpc_diagnostics(value: object, *, diagnostics_version: int) -> None:
    rows = _array(value, "operational_diagnostics.rpc_by_method")
    methods: list[str] = []
    for raw in rows:
        row = _mapping(raw, "operational_diagnostics RPC row")
        fields = (
            {
                "method",
                "scheduled_count",
                "sent_count",
                "success_count",
                "error_count",
                "deadline_late_count",
                "retired_count",
                "censored_count",
                "pre_send_error_count",
                "pre_send_deadline_late_count",
                "pre_send_retired_count",
                "pre_send_censored_count",
                "post_send_success_count",
                "post_send_error_count",
                "post_send_deadline_late_count",
                "post_send_retired_count",
                "post_send_censored_count",
                "rate_limit_count",
                "latency_observation_count",
                "latency_ms_sum",
                "latency_ms_max",
            }
            if diagnostics_version >= 3
            else {
                "method",
                "request_count",
                "success_count",
                "error_count",
                "late_response_count",
                "rate_limit_count",
                "latency_observation_count",
                "latency_ms_sum",
                "latency_ms_max",
            }
        )
        _exact_keys(row, fields, "operational_diagnostics RPC row")
        method = _required_string(row, "method")
        if diagnostics_version >= 3 and method not in RPC_METHOD_ALLOWLIST:
            raise EvidenceError("operational RPC method is outside the exact allowlist")
        if diagnostics_version == 2 and not method.startswith("public/"):
            raise EvidenceError("operational RPC method is not public")
        methods.append(method)
        for field in set(row) - {"method"}:
            _non_negative_integer(row[field], f"RPC row {field}")
        _validate_latency_totals(row, f"RPC row {method}")
        rate_limits = _non_negative_integer(
            row["rate_limit_count"],
            "rate_limit_count",
        )
        errors = _non_negative_integer(row["error_count"], "error_count")
        if rate_limits > errors:
            raise EvidenceError("RPC rate-limit count exceeds errors")

        if diagnostics_version >= 3:
            scheduled_count = _non_negative_integer(
                row["scheduled_count"],
                "scheduled_count",
            )
            sent_count = _non_negative_integer(row["sent_count"], "sent_count")
            pre_send_terminal_count = sum(
                _non_negative_integer(row[field], f"RPC row {field}")
                for field in (
                    "pre_send_error_count",
                    "pre_send_deadline_late_count",
                    "pre_send_retired_count",
                    "pre_send_censored_count",
                )
            )
            post_send_terminal_count = sum(
                _non_negative_integer(row[field], f"RPC row {field}")
                for field in (
                    "post_send_success_count",
                    "post_send_error_count",
                    "post_send_deadline_late_count",
                    "post_send_retired_count",
                    "post_send_censored_count",
                )
            )
            if scheduled_count != sent_count + pre_send_terminal_count:
                raise EvidenceError(
                    "RPC scheduled count does not reconcile sent and pre-send terminals"
                )
            if sent_count != post_send_terminal_count:
                raise EvidenceError("RPC sent count does not reconcile post-send terminals")
            terminal_reconciliations = {
                "success_count": _non_negative_integer(
                    row["post_send_success_count"],
                    "post_send_success_count",
                ),
                "error_count": _non_negative_integer(
                    row["pre_send_error_count"],
                    "pre_send_error_count",
                )
                + _non_negative_integer(
                    row["post_send_error_count"],
                    "post_send_error_count",
                ),
                "deadline_late_count": _non_negative_integer(
                    row["pre_send_deadline_late_count"],
                    "pre_send_deadline_late_count",
                )
                + _non_negative_integer(
                    row["post_send_deadline_late_count"],
                    "post_send_deadline_late_count",
                ),
                "retired_count": _non_negative_integer(
                    row["pre_send_retired_count"],
                    "pre_send_retired_count",
                )
                + _non_negative_integer(
                    row["post_send_retired_count"],
                    "post_send_retired_count",
                ),
                "censored_count": _non_negative_integer(
                    row["pre_send_censored_count"],
                    "pre_send_censored_count",
                )
                + _non_negative_integer(
                    row["post_send_censored_count"],
                    "post_send_censored_count",
                ),
            }
            for total_field, expected_total in terminal_reconciliations.items():
                if row[total_field] != expected_total:
                    raise EvidenceError(f"RPC {total_field} does not match terminal provenance")
            post_send_errors = _non_negative_integer(
                row["post_send_error_count"],
                "post_send_error_count",
            )
            if rate_limits > post_send_errors:
                raise EvidenceError("RPC rate-limit count exceeds post-send errors")
            response_terminal_count = sum(
                _non_negative_integer(row[field], f"RPC row {field}")
                for field in (
                    "post_send_success_count",
                    "post_send_error_count",
                    "post_send_deadline_late_count",
                )
            )
            latency_count = _non_negative_integer(
                row["latency_observation_count"],
                "latency_observation_count",
            )
            required_response_latency_count = (
                _non_negative_integer(
                    row["post_send_success_count"],
                    "post_send_success_count",
                )
                + post_send_errors
            )
            if latency_count < required_response_latency_count:
                raise EvidenceError(
                    "RPC success/error response terminals require latency observations"
                )
            if latency_count > response_terminal_count:
                raise EvidenceError("RPC latency observations exceed wire terminal states")
    if methods != sorted(set(methods)):
        raise EvidenceError("operational RPC rows must be unique and sorted")


def _validate_channel_diagnostics(
    value: object,
    *,
    observation_interval_ms: int,
) -> None:
    rows = _array(value, "operational_diagnostics.channel_by_class")
    classes: list[str] = []
    for raw in rows:
        row = _mapping(raw, "operational channel row")
        _exact_keys(
            row,
            {
                "channel_class",
                "received_count",
                "processed_count",
                "received_rate_per_second",
                "processed_rate_per_second",
            },
            "operational channel row",
        )
        channel_class = _required_string(row, "channel_class")
        classes.append(channel_class)
        received_count = _non_negative_integer(
            row["received_count"],
            f"{channel_class}.received_count",
        )
        processed_count = _non_negative_integer(
            row["processed_count"],
            f"{channel_class}.processed_count",
        )
        if processed_count > received_count:
            raise EvidenceError("processed channel count exceeds received count")
        for count_field, rate_field in (
            ("received_count", "received_rate_per_second"),
            ("processed_count", "processed_rate_per_second"),
        ):
            count = _non_negative_integer(
                row[count_field],
                f"{channel_class}.{count_field}",
            )
            expected = (
                None
                if observation_interval_ms == 0
                else decimal_text(
                    Decimal(count) / (Decimal(observation_interval_ms) / Decimal(1_000))
                )
            )
            if row[rate_field] != expected:
                raise EvidenceError(f"{channel_class}.{rate_field} does not match duration")
    if tuple(classes) != CHANNEL_CLASSES:
        raise EvidenceError("operational channel classes are incomplete or unsorted")


def _validate_named_non_negative_counts(
    value: object,
    fields: set[str],
    name: str,
) -> None:
    mapping = _mapping(value, name)
    _exact_keys(mapping, fields, name)
    for field in fields:
        _non_negative_integer(mapping[field], f"{name}.{field}")


def _validate_latency_totals(value: Mapping[str, object], name: str) -> None:
    count = value["latency_observation_count"]
    total = value["latency_ms_sum"]
    maximum = value["latency_ms_max"]
    if not isinstance(count, int) or not isinstance(total, int) or not isinstance(maximum, int):
        return
    if count == 0 and (total != 0 or maximum != 0):
        raise EvidenceError(f"{name} has latency totals without observations")
    if count > 0 and (maximum > total):
        raise EvidenceError(f"{name} latency maximum exceeds sum")


def _validate_source_shapes(value: object) -> dict[str, tuple[int, int, int]]:
    rows = _array(value, "operational_diagnostics.source_shapes")
    sources: list[str] = []
    counts: dict[str, tuple[int, int, int]] = {}
    for raw in rows:
        row = _mapping(raw, "operational source-shape row")
        _exact_keys(
            row,
            {
                "source",
                "observed_count",
                "valid_count",
                "invalid_count",
                "validation",
                "consumed_fields",
            },
            "operational source-shape row",
        )
        source = _required_string(row, "source")
        sources.append(source)
        observed = _non_negative_integer(row["observed_count"], f"{source}.observed_count")
        valid = _non_negative_integer(row["valid_count"], f"{source}.valid_count")
        invalid = _non_negative_integer(row["invalid_count"], f"{source}.invalid_count")
        if valid + invalid != observed:
            raise EvidenceError("source-shape valid/invalid counts do not match observed")
        counts[source] = (observed, valid, invalid)
        expected_validation = "NOT_OBSERVED" if observed == 0 else "INVALID" if invalid else "VALID"
        if row["validation"] != expected_validation:
            raise EvidenceError("source-shape final validation does not match counts")
        fields = _array(row["consumed_fields"], f"{source}.consumed_fields")
        source_field_spec = SOURCE_CONSUMED_FIELD_TYPES.get(source)
        if source_field_spec is None:
            raise EvidenceError("source-shape source is outside the exact field specification")
        if observed == 0 and fields:
            raise EvidenceError("unobserved source cannot claim consumed fields")
        keys: list[str] = []
        for raw_field in fields:
            field = _mapping(raw_field, f"{source} consumed field")
            _exact_keys(field, {"key", "type"}, f"{source} consumed field")
            key = _required_string(field, "key")
            field_type = _required_string(field, "type")
            allowed_types = source_field_spec.get(key)
            if allowed_types is None or field_type not in allowed_types:
                raise EvidenceError(
                    f"source-shape consumed field {source}.{key}:{field_type} is outside "
                    "the shared field specification"
                )
            keys.append(key)
        if keys != sorted(set(keys)):
            raise EvidenceError("source-shape consumed fields must be unique and sorted")
    if tuple(sources) != CORE_SOURCE_NAMES:
        raise EvidenceError("operational source-shape rows are incomplete or unsorted")
    return counts


def _validate_cross_ledger_conservation(
    diagnostics: Mapping[str, object],
    *,
    source_shape_counts: Mapping[str, tuple[int, int, int]],
) -> None:
    ingress = _mapping(
        diagnostics["ingress"],
        "operational_diagnostics.ingress",
    )
    channel_rows = _array(
        diagnostics["channel_by_class"],
        "operational_diagnostics.channel_by_class",
    )
    channels = {
        _required_string(
            _mapping(raw, "operational channel row"),
            "channel_class",
        ): _mapping(raw, "operational channel row")
        for raw in channel_rows
    }
    for ingress_field, channel_field in (
        ("received_envelope_count", "received_count"),
        ("reduced_envelope_count", "processed_count"),
    ):
        ingress_count = _non_negative_integer(
            ingress[ingress_field],
            f"operational_diagnostics.ingress.{ingress_field}",
        )
        channel_count = sum(
            _non_negative_integer(
                row[channel_field],
                f"{channel_class}.{channel_field}",
            )
            for channel_class, row in channels.items()
        )
        if ingress_count != channel_count:
            raise EvidenceError("cross-ledger ingress/channel conservation does not reconcile")

    rpc_rows = _array(
        diagnostics["rpc_by_method"],
        "operational_diagnostics.rpc_by_method",
    )
    rpc_by_method = {
        _required_string(_mapping(raw, "operational RPC row"), "method"): _mapping(
            raw,
            "operational RPC row",
        )
        for raw in rpc_rows
    }
    rpc_latency_count = 0
    for method in RPC_METHOD_ALLOWLIST:
        row = rpc_by_method.get(method)
        latency_count = (
            0
            if row is None
            else _non_negative_integer(
                row["latency_observation_count"],
                f"RPC row {method}.latency_observation_count",
            )
        )
        rpc_latency_count += latency_count
        if source_shape_counts[method][0] != latency_count:
            raise EvidenceError(
                "cross-ledger RPC latency/source-shape conservation does not reconcile"
            )

    orphan_count = _non_negative_integer(
        diagnostics["rpc_orphan_late_wire_count"],
        "rpc_orphan_late_wire_count",
    )
    expected_connection_control_count = (
        _non_negative_integer(
            ingress["send_control_event_count"],
            "ingress.send_control_event_count",
        )
        + _non_negative_integer(
            ingress["connection_error_event_count"],
            "ingress.connection_error_event_count",
        )
        + rpc_latency_count
        + orphan_count
    )
    connection_control = channels["CONNECTION_CONTROL"]
    for field in ("received_count", "processed_count"):
        if (
            _non_negative_integer(
                connection_control[field],
                f"CONNECTION_CONTROL.{field}",
            )
            != expected_connection_control_count
        ):
            raise EvidenceError("cross-ledger connection-control conservation does not reconcile")

    heartbeat_source_count = source_shape_counts["heartbeat"][0]
    heartbeat_channel = channels["HEARTBEAT"]
    for field in ("received_count", "processed_count"):
        if (
            _non_negative_integer(
                heartbeat_channel[field],
                f"HEARTBEAT.{field}",
            )
            != heartbeat_source_count
        ):
            raise EvidenceError(
                "cross-ledger heartbeat channel/source conservation does not reconcile"
            )

    heartbeat = _mapping(
        diagnostics["heartbeat"],
        "operational_diagnostics.heartbeat",
    )
    public_test = rpc_by_method.get("public/test")
    rpc_public_test = {
        field: (
            0
            if public_test is None
            else _non_negative_integer(
                public_test[field],
                f"RPC row public/test.{field}",
            )
        )
        for field in (
            "scheduled_count",
            "success_count",
            "latency_observation_count",
            "latency_ms_sum",
            "latency_ms_max",
        )
    }
    heartbeat_counts = {
        field: _non_negative_integer(
            heartbeat[field],
            f"operational_diagnostics.heartbeat.{field}",
        )
        for field in (
            "test_request_count",
            "public_test_success_count",
            "public_test_error_count",
            "latency_observation_count",
            "latency_ms_sum",
            "latency_ms_max",
        )
    }
    if heartbeat_counts["test_request_count"] != rpc_public_test["scheduled_count"]:
        raise EvidenceError(
            "cross-ledger heartbeat/public-test scheduling conservation does not reconcile"
        )
    if heartbeat_counts["test_request_count"] > source_shape_counts["heartbeat"][1]:
        raise EvidenceError(
            "cross-ledger heartbeat test-request/source conservation does not reconcile"
        )
    for heartbeat_field, rpc_field in (
        ("public_test_success_count", "success_count"),
        ("latency_observation_count", "latency_observation_count"),
        ("latency_ms_sum", "latency_ms_sum"),
        ("latency_ms_max", "latency_ms_max"),
    ):
        if heartbeat_counts[heartbeat_field] != rpc_public_test[rpc_field]:
            raise EvidenceError(
                "cross-ledger heartbeat/public-test latency conservation does not reconcile"
            )
    public_test_observed, public_test_valid, public_test_invalid = source_shape_counts[
        "public/test"
    ]
    if (
        public_test_observed != rpc_public_test["latency_observation_count"]
        or public_test_valid != rpc_public_test["success_count"]
        or public_test_invalid != heartbeat_counts["public_test_error_count"]
        or public_test_observed
        != (
            heartbeat_counts["public_test_success_count"]
            + heartbeat_counts["public_test_error_count"]
        )
    ):
        raise EvidenceError(
            "cross-ledger heartbeat/public-test source conservation does not reconcile"
        )


def _validate_transport_terminal_attribution(
    value: object,
    *,
    connection_error_event_count: int,
) -> None:
    rows = _array(value, "operational_diagnostics.transport_terminal_attribution")
    identities: set[tuple[str, str, str]] = set()
    total = 0
    maximum_rows = (
        len(TRANSPORT_CLOSE_CODE_ALLOWLIST)
        * len(TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST)
        * len(TRANSPORT_EXCEPTION_CLASS_ALLOWLIST)
    )
    if len(rows) > maximum_rows:
        raise EvidenceError("transport terminal attribution exceeds its bounded row space")
    for raw in rows:
        row = _mapping(raw, "transport terminal attribution row")
        _exact_keys(
            row,
            {
                "close_code",
                "close_disposition",
                "exception_class",
                "count",
            },
            "transport terminal attribution row",
        )
        close_code = _required_string(row, "close_code")
        close_disposition = _required_string(row, "close_disposition")
        exception_class = _required_string(row, "exception_class")
        if close_code not in TRANSPORT_CLOSE_CODE_ALLOWLIST:
            raise EvidenceError("transport close code is outside the bounded allowlist")
        if close_disposition not in TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST:
            raise EvidenceError("transport close disposition is outside the bounded allowlist")
        if exception_class not in TRANSPORT_EXCEPTION_CLASS_ALLOWLIST:
            raise EvidenceError("transport exception class is outside the bounded allowlist")
        expected_disposition = "CLEAN" if close_code in {"1000", "1001"} else "ABNORMAL"
        if close_disposition != expected_disposition:
            raise EvidenceError("transport close disposition conflicts with its close code")
        identity = (close_code, close_disposition, exception_class)
        if identity in identities:
            raise EvidenceError("transport terminal attribution rows must be unique")
        identities.add(identity)
        total += _positive_integer(row["count"], "transport terminal attribution count")
    if total != connection_error_event_count:
        raise EvidenceError(
            "transport terminal attribution does not reconcile connection error controls"
        )


def _validate_global_continuity(
    value: object,
    *,
    runtime_started_monotonic_ms: int,
    clean_stop_monotonic_ms: int,
    diagnostics_version: int,
) -> tuple[
    int,
    tuple[Mapping[str, object], ...],
    Mapping[int, Mapping[str, object]],
    Mapping[
        tuple[str, int, str, str, str],
        tuple[int, Mapping[str, object] | None],
    ],
]:
    continuity = _mapping(value, "operational_diagnostics.global_continuity")
    _exact_keys(
        continuity,
        {
            "current_epoch",
            "restart_count",
            "restart_count_by_reason",
            "restart_edges",
            "recovery_edges",
            "current_epoch_joint_evaluation_count_by_scope",
        },
        "operational_diagnostics.global_continuity",
    )
    current_epoch = _positive_integer(continuity["current_epoch"], "current_epoch")
    restart_count = _non_negative_integer(continuity["restart_count"], "restart_count")
    restart_by_reason = _mapping(
        continuity["restart_count_by_reason"],
        "restart_count_by_reason",
    )
    parsed_restart_count = 0
    for reason, count in restart_by_reason.items():
        try:
            CausalCause(reason)
        except (TypeError, ValueError) as exc:
            raise EvidenceError(
                "global continuity restart reason is outside the causal cause whitelist"
            ) from exc
        parsed_restart_count += _positive_integer(
            count,
            f"global continuity restart count {reason}",
        )
    if parsed_restart_count != restart_count:
        raise EvidenceError("global continuity restart reason counts do not match total")
    if current_epoch != restart_count + 1:
        raise EvidenceError("global continuity epoch does not match restart count")
    raw_edges = _array(continuity["restart_edges"], "global continuity restart_edges")
    if len(raw_edges) != restart_count:
        raise EvidenceError("global continuity restart edges do not match restart count")
    edges: list[Mapping[str, object]] = []
    edge_reasons: Counter[str] = Counter()
    for expected_id, raw_edge in enumerate(raw_edges, start=1):
        edge = _mapping(raw_edge, "global continuity restart edge")
        restart_edge_fields = {
            "incident_id",
            "from_epoch",
            "to_epoch",
            "reason",
            "failure_domain",
            "affected_scopes",
            "boundary",
        }
        if diagnostics_version >= 4:
            restart_edge_fields.add("trigger_cause")
        _exact_keys(
            edge,
            restart_edge_fields,
            "global continuity restart edge",
        )
        if _positive_integer(edge["incident_id"], "continuity incident_id") != expected_id:
            raise EvidenceError("global continuity incident ids must be unique and ordered")
        from_epoch = _positive_integer(edge["from_epoch"], "continuity from_epoch")
        to_epoch = _positive_integer(edge["to_epoch"], "continuity to_epoch")
        if from_epoch != expected_id or to_epoch != expected_id + 1:
            raise EvidenceError("global continuity restart edge does not advance exactly one epoch")
        if diagnostics_version >= 4:
            trigger_cause = _required_string(edge, "trigger_cause")
            try:
                CausalCause(trigger_cause)
            except ValueError as exc:
                raise EvidenceError(
                    "global continuity restart trigger is outside the causal cause whitelist"
                ) from exc
        reason = _required_string(edge, "reason")
        restart_allowlist = (
            SEALED_GLOBAL_CONTINUITY_RESTART_ALLOWLIST
            if diagnostics_version == 3
            else GLOBAL_CONTINUITY_RESTART_ALLOWLIST
        )
        allowed = restart_allowlist.get(reason)
        if allowed is None:
            raise EvidenceError(
                "global continuity restart cause-domain-scope tuple is outside the allowlist"
            )
        failure_domain = edge["failure_domain"]
        if failure_domain not in FAILURE_DOMAINS:
            raise EvidenceError("global continuity failure domain is outside the whitelist")
        affected_scopes = _validate_affected_scopes(edge["affected_scopes"])
        expected_domain, scope_kind = allowed
        expected_scope = (
            affected_scopes == ("GLOBAL",)
            if scope_kind == "GLOBAL"
            else all(scope.startswith("SCOPE:") for scope in affected_scopes)
        )
        if failure_domain != expected_domain or not expected_scope:
            raise EvidenceError(
                "global continuity restart cause-domain-scope tuple is outside the allowlist"
            )
        _validate_fact_boundary(edge["boundary"], "global continuity restart boundary")
        edge_reasons[reason] += 1
        edges.append(edge)
    if dict(edge_reasons) != dict(restart_by_reason):
        raise EvidenceError("global continuity restart edges do not match reason totals")
    raw_recoveries = _array(
        continuity["recovery_edges"],
        "global continuity recovery_edges",
    )
    recoveries: dict[int, Mapping[str, object]] = {}
    for raw_recovery in raw_recoveries:
        recovery = _mapping(raw_recovery, "global continuity recovery edge")
        _exact_keys(
            recovery,
            {"incident_id", "boundary"},
            "global continuity recovery edge",
        )
        incident_id = _positive_integer(
            recovery["incident_id"],
            "continuity recovery incident_id",
        )
        if incident_id in recoveries or incident_id > restart_count:
            raise EvidenceError("global continuity recovery incident is duplicate or unknown")
        boundary = _validate_fact_boundary(
            recovery["boundary"],
            "global continuity recovery boundary",
        )
        restart_boundary = _mapping(
            edges[incident_id - 1]["boundary"],
            "global continuity restart boundary",
        )
        if _fact_boundary_order(boundary) <= _fact_boundary_order(restart_boundary):
            raise EvidenceError(
                "global continuity recovery must be strictly later than its restart"
            )
        recovery_ms = _non_negative_integer(
            boundary["received_monotonic_ms"],
            "global continuity recovery monotonic boundary",
        )
        if not runtime_started_monotonic_ms <= recovery_ms <= clean_stop_monotonic_ms:
            raise EvidenceError("global continuity recovery is outside the runtime interval")
        recoveries[incident_id] = recovery
    for incident_id in range(1, restart_count):
        recovered_edge = recoveries.get(incident_id)
        if recovered_edge is None:
            raise EvidenceError("global continuity incident restarted again before recovery")
        recovery_boundary = _mapping(
            recovered_edge["boundary"],
            "global continuity recovery boundary",
        )
        next_restart_boundary = _mapping(
            edges[incident_id]["boundary"],
            "global continuity restart boundary",
        )
        if _fact_boundary_order(recovery_boundary) >= _fact_boundary_order(next_restart_boundary):
            raise EvidenceError("global continuity incident restarted again before recovery")
    current_joint_rows = _array(
        continuity["current_epoch_joint_evaluation_count_by_scope"],
        "global continuity current-epoch joint scope counts",
    )
    current_joint_counts: dict[
        tuple[str, int, str, str, str],
        tuple[int, Mapping[str, object] | None],
    ] = {}
    identities: list[tuple[str, int, str, str, str]] = []
    for raw_row in current_joint_rows:
        row = _mapping(raw_row, "current-epoch joint scope count")
        _exact_keys(
            row,
            {
                "policy_identity",
                "expiration_timestamp_ms",
                "option_type",
                "tte_band_id",
                "formula_instrument_name",
                "count",
                "first_joint_evaluation_boundary",
            },
            "current-epoch joint scope count",
        )
        identity = (
            _required_string(row, "policy_identity"),
            _positive_integer(
                row["expiration_timestamp_ms"],
                "current-epoch joint scope expiration_timestamp_ms",
            ),
            _required_string(row, "option_type"),
            _required_string(row, "tte_band_id"),
            _required_string(row, "formula_instrument_name"),
        )
        if identity[2] not in {"call", "put"}:
            raise EvidenceError("current-epoch joint scope option_type is invalid")
        count = _positive_integer(
            row["count"],
            "current-epoch joint scope count",
        )
        raw_first_boundary = row["first_joint_evaluation_boundary"]
        first_boundary = (
            None
            if raw_first_boundary is None
            else _validate_fact_boundary(
                raw_first_boundary,
                "current-epoch first joint evaluation boundary",
            )
        )
        if first_boundary is not None:
            first_ms = _non_negative_integer(
                first_boundary["received_monotonic_ms"],
                "current-epoch first joint evaluation monotonic boundary",
            )
            if not runtime_started_monotonic_ms <= first_ms <= clean_stop_monotonic_ms:
                raise EvidenceError(
                    "current-epoch first joint evaluation is outside the runtime interval"
                )
            if current_epoch == 1:
                if first_ms <= runtime_started_monotonic_ms:
                    raise EvidenceError(
                        "current-epoch first joint evaluation must be after runtime start"
                    )
            else:
                current_epoch_restart = _mapping(
                    edges[-1]["boundary"],
                    "current epoch restart boundary",
                )
                if _fact_boundary_order(first_boundary) <= _fact_boundary_order(
                    current_epoch_restart
                ):
                    raise EvidenceError(
                        "current-epoch first joint evaluation must follow its restart"
                    )
                current_epoch_recovery = recoveries.get(restart_count)
                if current_epoch_recovery is None:
                    raise EvidenceError("current-epoch joint evaluation requires incident recovery")
                recovery_boundary = _mapping(
                    current_epoch_recovery["boundary"],
                    "current epoch recovery boundary",
                )
                if _fact_boundary_order(first_boundary) <= _fact_boundary_order(recovery_boundary):
                    raise EvidenceError("current-epoch first joint evaluation must follow recovery")
        if identity in current_joint_counts:
            raise EvidenceError("current-epoch joint scope identities must be unique")
        identities.append(identity)
        current_joint_counts[identity] = (count, first_boundary)
    if identities != sorted(identities):
        raise EvidenceError("current-epoch joint scope rows must be sorted")
    return current_epoch, tuple(edges), recoveries, current_joint_counts


def _validate_ticker_application(value: object) -> dict[str, int]:
    application = _mapping(value, "operational_diagnostics.ticker_application")
    _exact_keys(
        application,
        {
            "disposition_count",
            "late_ignored_diagnostic_limit",
            "omitted_late_ignored_diagnostic_count",
            "late_ignored_diagnostics",
        },
        "operational_diagnostics.ticker_application",
    )
    _validate_named_non_negative_counts(
        application["disposition_count"],
        {
            "APPLIED",
            "LATE_IGNORED",
            "AHEAD_IGNORED",
            "STALE_GENERATION_IGNORED",
            "SHAPE_REJECTED",
        },
        "ticker_application.disposition_count",
    )
    limit = application["late_ignored_diagnostic_limit"]
    if limit != 256:
        raise EvidenceError("late ticker diagnostic limit must be 256")
    omitted = _non_negative_integer(
        application["omitted_late_ignored_diagnostic_count"],
        "omitted_late_ignored_diagnostic_count",
    )
    rows = _array(
        application["late_ignored_diagnostics"],
        "ticker_application.late_ignored_diagnostics",
    )
    if len(rows) > limit:
        raise EvidenceError("late ticker diagnostics exceed bounded 256 rows")
    for raw in rows:
        row = _mapping(raw, "late ticker diagnostic")
        _exact_keys(
            row,
            {
                "instrument_name",
                "generation",
                "ingress_seq",
                "previous_source_timestamp_ms",
                "candidate_source_timestamp_ms",
                "timestamp_delta_ms",
                "received_monotonic_ms",
                "disposition",
            },
            "late ticker diagnostic",
        )
        _required_string(row, "instrument_name")
        _non_negative_integer(row["generation"], "late ticker generation")
        _positive_integer(row["ingress_seq"], "late ticker ingress_seq")
        previous = _non_negative_integer(
            row["previous_source_timestamp_ms"],
            "previous_source_timestamp_ms",
        )
        candidate = _non_negative_integer(
            row["candidate_source_timestamp_ms"],
            "candidate_source_timestamp_ms",
        )
        delta = row["timestamp_delta_ms"]
        if isinstance(delta, bool) or not isinstance(delta, int) or delta >= 0:
            raise EvidenceError("late ticker timestamp delta must be a negative integer")
        if delta != candidate - previous:
            raise EvidenceError("late ticker timestamp delta does not match timestamps")
        _non_negative_integer(
            row["received_monotonic_ms"],
            "late ticker received_monotonic_ms",
        )
        if row["disposition"] != "LATE_IGNORED":
            raise EvidenceError("late ticker diagnostic disposition must be LATE_IGNORED")
    disposition_count = _mapping(
        application["disposition_count"],
        "ticker_application.disposition_count",
    )
    late_count = _non_negative_integer(
        disposition_count["LATE_IGNORED"],
        "ticker_application LATE_IGNORED count",
    )
    if late_count != len(rows) + omitted:
        raise EvidenceError(
            "late ticker retained and omitted diagnostics do not match LATE_IGNORED total"
        )
    return {
        disposition: _non_negative_integer(
            disposition_count[disposition],
            f"ticker_application {disposition} count",
        )
        for disposition in (
            "APPLIED",
            "LATE_IGNORED",
            "AHEAD_IGNORED",
            "STALE_GENERATION_IGNORED",
            "SHAPE_REJECTED",
        )
    }


def _validate_ticker_currentness(value: object) -> dict[str, int]:
    currentness = _mapping(value, "operational_diagnostics.ticker_currentness")
    _exact_keys(
        currentness,
        {
            "candidate_count_by_classification",
            "accepted_transition_count_by_state",
        },
        "operational_diagnostics.ticker_currentness",
    )
    _validate_named_non_negative_counts(
        currentness["candidate_count_by_classification"],
        {
            "CURRENT",
            "SOURCE_STALE",
            "TIMESTAMP_AHEAD",
            "TRUSTED_TIME_UNKNOWN",
        },
        "ticker_currentness.candidate_count_by_classification",
    )
    _validate_named_non_negative_counts(
        currentness["accepted_transition_count_by_state"],
        {"MISSING", "CURRENT", "SOURCE_STALE"},
        "ticker_currentness.accepted_transition_count_by_state",
    )
    candidate_counts = _mapping(
        currentness["candidate_count_by_classification"],
        "ticker_currentness.candidate_count_by_classification",
    )
    return {
        classification: _non_negative_integer(
            candidate_counts[classification],
            f"ticker currentness {classification} count",
        )
        for classification in (
            "CURRENT",
            "SOURCE_STALE",
            "TIMESTAMP_AHEAD",
            "TRUSTED_TIME_UNKNOWN",
        )
    }


def _validate_option_local_availability(
    value: object,
    *,
    runtime_started_monotonic_ms: int,
    clean_stop_monotonic_ms: int,
    current_epoch: int,
    diagnostics_version: int,
) -> None:
    availability = _mapping(value, "operational_diagnostics.option_local_availability")
    compacted_fields = {
        "unavailable_count_by_reason",
        "recovery_count_by_reason",
        "end_count_by_disposition",
        "retained_interval_limit",
        "omitted_interval_count",
        "omitted_interval_count_by_reason",
        "intervals",
    }
    final_window_fields = {
        *compacted_fields,
        "acceptance_window_ms",
        "outside_window_interval_count",
        "outside_window_latest_end_monotonic_ms",
        "outside_window_interval_count_by_reason",
    }
    sealed_compacted = diagnostics_version == 3 and set(availability) == compacted_fields
    _exact_keys(
        availability,
        compacted_fields if sealed_compacted else final_window_fields,
        "operational_diagnostics.option_local_availability",
    )
    unavailable = _mapping(
        availability["unavailable_count_by_reason"],
        "option_local_availability.unavailable_count_by_reason",
    )
    recovered = _mapping(
        availability["recovery_count_by_reason"],
        "option_local_availability.recovery_count_by_reason",
    )
    parsed_counts: dict[str, dict[str, int]] = {
        "unavailable": {},
        "recovery": {},
    }
    for name, counts in (("unavailable", unavailable), ("recovery", recovered)):
        for reason, count in counts.items():
            if not isinstance(reason, str) or not reason:
                raise EvidenceError(f"option-local {name} reason must be non-empty")
            if reason not in OPTION_LOCAL_REASONS:
                raise EvidenceError("option-local reason whitelist rejected a count reason")
            parsed_counts[name][reason] = _positive_integer(
                count,
                f"option-local {name} count {reason}",
            )
    unavailable_counts = parsed_counts["unavailable"]
    recovery_counts = parsed_counts["recovery"]
    end_counts_raw = _mapping(
        availability["end_count_by_disposition"],
        "option_local_availability.end_count_by_disposition",
    )
    _validate_named_non_negative_counts(
        end_counts_raw,
        {"RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"},
        "option_local_availability.end_count_by_disposition",
    )
    end_counts = {
        disposition: _non_negative_integer(
            end_counts_raw[disposition],
            f"option-local {disposition} end count",
        )
        for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP")
    }
    limit = availability["retained_interval_limit"]
    expected_limit = 256 if sealed_compacted else OPTION_LOCAL_RETAINED_INTERVAL_LIMIT
    if limit != expected_limit:
        raise EvidenceError(
            f"option-local retained interval limit must be exactly {expected_limit}"
        )
    acceptance_start_ms: int | None = None
    outside = 0
    if not sealed_compacted:
        window_ms = availability["acceptance_window_ms"]
        if window_ms != OPTION_LOCAL_ACCEPTANCE_WINDOW_MS:
            raise EvidenceError("option-local acceptance window must be exactly 3600000 ms")
        acceptance_start_ms = clean_stop_monotonic_ms - window_ms
        outside = _non_negative_integer(
            availability["outside_window_interval_count"],
            "option-local outside_window_interval_count",
        )
    omitted = _non_negative_integer(
        availability["omitted_interval_count"],
        "option-local omitted_interval_count",
    )
    rows = _array(availability["intervals"], "option_local_availability.intervals")
    if len(rows) > limit:
        raise EvidenceError(f"option-local intervals exceed bounded {expected_limit} rows")
    retained_by_reason: Counter[str] = Counter()
    retained_by_reason_and_disposition: Counter[tuple[str, str]] = Counter()
    for raw in rows:
        row = _mapping(raw, "option-local availability interval")
        _exact_keys(
            row,
            {
                "instrument_name",
                "generation",
                "reason",
                "start_monotonic_ms",
                "end_monotonic_ms",
                "duration_ms",
                "end_disposition",
                "global_continuity_epoch",
            },
            "option-local availability interval",
        )
        _required_string(row, "instrument_name")
        _non_negative_integer(row["generation"], "option-local ticker generation")
        reason = _required_string(row, "reason")
        if reason not in OPTION_LOCAL_REASONS:
            raise EvidenceError("option-local reason whitelist rejected an interval reason")
        start = _non_negative_integer(row["start_monotonic_ms"], "option-local interval start")
        end = _non_negative_integer(row["end_monotonic_ms"], "option-local interval end")
        duration = _non_negative_integer(row["duration_ms"], "option-local interval duration")
        if not runtime_started_monotonic_ms <= start <= end <= clean_stop_monotonic_ms:
            raise EvidenceError("option-local interval is outside runtime interval")
        if duration != end - start:
            raise EvidenceError("option-local interval duration does not match boundaries")
        if acceptance_start_ms is not None and end <= acceptance_start_ms:
            raise EvidenceError(
                "retained option-local interval does not intersect the final acceptance window"
            )
        disposition = row["end_disposition"]
        if disposition not in {"RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"}:
            raise EvidenceError("option-local interval end disposition is invalid")
        if disposition == "CENSORED_AT_STOP" and end != clean_stop_monotonic_ms:
            raise EvidenceError("CENSORED_AT_STOP interval must end exactly at clean stop")
        epoch = _positive_integer(
            row["global_continuity_epoch"],
            "option-local interval continuity epoch",
        )
        if epoch > current_epoch:
            raise EvidenceError("option-local interval continuity epoch is in the future")
        retained_by_reason[reason] += 1
        retained_by_reason_and_disposition[(reason, disposition)] += 1

    def aggregate_counts(
        raw_value: object,
        *,
        label: str,
    ) -> Counter[tuple[str, str]]:
        raw_by_reason = _mapping(raw_value, f"option_local_availability.{label}")
        parsed: Counter[tuple[str, str]] = Counter()
        for reason, raw_counts in raw_by_reason.items():
            if not isinstance(reason, str) or not reason:
                raise EvidenceError(f"option-local {label} reason must be non-empty")
            if reason not in OPTION_LOCAL_REASONS:
                raise EvidenceError(f"option-local reason whitelist rejected a {label} reason")
            counts = _mapping(raw_counts, f"option-local {label} counts {reason}")
            _validate_named_non_negative_counts(
                counts,
                {"RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"},
                f"option-local {label} counts {reason}",
            )
            for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"):
                count = _non_negative_integer(
                    counts[disposition],
                    f"option-local {label} {reason} {disposition}",
                )
                if count:
                    parsed[(reason, disposition)] = count
        return parsed

    outside_by_reason_and_disposition: Counter[tuple[str, str]] = Counter()
    if not sealed_compacted:
        outside_by_reason_and_disposition = aggregate_counts(
            availability["outside_window_interval_count_by_reason"],
            label="outside-window",
        )
        if sum(outside_by_reason_and_disposition.values()) != outside:
            raise EvidenceError(
                "option-local conservation does not reconcile outside-window intervals"
            )
        outside_latest_end = availability["outside_window_latest_end_monotonic_ms"]
        if outside == 0:
            if outside_latest_end is not None:
                raise EvidenceError("empty outside-window ledger must have a null latest end")
        else:
            latest_end = _non_negative_integer(
                outside_latest_end,
                "option-local outside-window latest end",
            )
            if not runtime_started_monotonic_ms <= latest_end <= clean_stop_monotonic_ms:
                raise EvidenceError("option-local outside-window latest end is outside runtime")
            if acceptance_start_ms is None or latest_end > acceptance_start_ms:
                raise EvidenceError(
                    "option-local outside-window latest end enters the final acceptance window"
                )

    omitted_by_reason_and_disposition = aggregate_counts(
        availability["omitted_interval_count_by_reason"],
        label="omitted",
    )
    if sum(omitted_by_reason_and_disposition.values()) != omitted:
        raise EvidenceError("option-local conservation does not reconcile omitted intervals")
    total_starts = sum(unavailable_counts.values())
    if total_starts != len(rows) + outside + omitted or total_starts != sum(end_counts.values()):
        raise EvidenceError("option-local conservation does not reconcile starts and ends")
    for reason, start_count in unavailable_counts.items():
        retained_count = retained_by_reason[reason]
        outside_count = sum(
            outside_by_reason_and_disposition[(reason, disposition)]
            for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP")
        )
        omitted_count = sum(
            omitted_by_reason_and_disposition[(reason, disposition)]
            for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP")
        )
        if start_count != retained_count + outside_count + omitted_count:
            raise EvidenceError("option-local conservation does not reconcile reason totals")
    if set(retained_by_reason) - set(unavailable_counts):
        raise EvidenceError("option-local conservation has an orphan retained reason")
    if {reason for reason, _ in outside_by_reason_and_disposition} - set(unavailable_counts):
        raise EvidenceError("option-local conservation has an orphan outside-window reason")
    if {reason for reason, _ in omitted_by_reason_and_disposition} - set(unavailable_counts):
        raise EvidenceError("option-local conservation has an orphan omitted reason")
    for disposition, declared_count in end_counts.items():
        actual_count = sum(
            count
            for (reason, candidate), count in (
                retained_by_reason_and_disposition
                + outside_by_reason_and_disposition
                + omitted_by_reason_and_disposition
            ).items()
            if candidate == disposition
        )
        if declared_count != actual_count:
            raise EvidenceError("option-local conservation does not reconcile end dispositions")
    all_reasons = set(unavailable_counts) | set(recovery_counts)
    for reason in all_reasons:
        actual_recovered = (
            retained_by_reason_and_disposition[(reason, "RECOVERED")]
            + outside_by_reason_and_disposition[(reason, "RECOVERED")]
            + omitted_by_reason_and_disposition[(reason, "RECOVERED")]
        )
        if recovery_counts.get(reason, 0) != actual_recovered:
            raise EvidenceError("option-local conservation does not reconcile recoveries")


def _validate_version_three_coverage(
    segments: tuple[CoverageSegment, ...],
    *,
    current_epoch: int,
    restart_edges: tuple[Mapping[str, object], ...],
    recovery_edges: Mapping[int, Mapping[str, object]],
    diagnostics_version: int,
) -> None:
    epochs = [segment.global_continuity_epoch for segment in segments]
    if epochs[0] != 1 or epochs[-1] != current_epoch:
        raise EvidenceError("coverage continuity epoch does not match global continuity")
    if epochs != sorted(epochs):
        raise EvidenceError("coverage continuity epoch moved backward")
    if any(after - before > 1 for before, after in pairwise(epochs)):
        raise EvidenceError("coverage continuity epoch skipped a restart boundary")
    restart_reasons = frozenset(
        SEALED_GLOBAL_CONTINUITY_RESTART_ALLOWLIST
        if diagnostics_version == 3
        else GLOBAL_CONTINUITY_RESTART_ALLOWLIST
    )
    if diagnostics_version <= 4:
        for index, segment in enumerate(segments):
            attributed_restart_reason = (
                segment.reason if diagnostics_version == 3 else segment.blocking_reason
            )
            if attributed_restart_reason not in restart_reasons:
                continue
            if index == 0 or (
                segments[index - 1].global_continuity_epoch == segment.global_continuity_epoch
            ):
                raise EvidenceError(
                    "global continuity restart cause requires a matching coverage epoch edge"
                )
    epoch_edges = tuple(
        (before, after)
        for before, after in pairwise(segments)
        if after.global_continuity_epoch != before.global_continuity_epoch
    )
    if len(epoch_edges) != len(restart_edges):
        raise EvidenceError("coverage epoch edges and continuity restart edges are not one-to-one")
    for (before, after), restart in zip(epoch_edges, restart_edges, strict=True):
        boundary = _mapping(restart["boundary"], "global continuity restart boundary")
        restart_scopes = _validate_affected_scopes(restart["affected_scopes"])
        if diagnostics_version == 3:
            restart_identity_matches = after.reason == restart["reason"]
        elif diagnostics_version == 4:
            restart_identity_matches = (
                after.reason == restart["trigger_cause"]
                and after.blocking_reason == restart["reason"]
            )
        else:
            restart_identity_matches = after.reason == restart["trigger_cause"] and any(
                group.blocking_reason == restart["reason"]
                and group.affected_scopes == restart_scopes
                for group in after.blocking_groups
            )
        if (
            before.global_continuity_epoch != restart["from_epoch"]
            or after.global_continuity_epoch != restart["to_epoch"]
            or after.start_monotonic_ms != boundary["received_monotonic_ms"]
            or not restart_identity_matches
            or (diagnostics_version <= 4 and after.affected_scopes != restart_scopes)
        ):
            raise EvidenceError(
                "coverage epoch edge does not match its continuity restart trigger and effect"
            )
    if diagnostics_version != 5:
        return
    for index, segment in enumerate(segments):
        restart_groups = tuple(
            group for group in segment.blocking_groups if group.blocking_reason in restart_reasons
        )
        if not restart_groups:
            continue
        if index == 0 or segment.global_continuity_epoch == 1:
            raise EvidenceError(
                "global continuity restart group requires an earlier matching epoch edge"
            )
        incident_id = segment.global_continuity_epoch - 1
        restart = restart_edges[incident_id - 1]
        if any(group.blocking_reason != restart["reason"] for group in restart_groups):
            raise EvidenceError(
                "coverage restart group does not match the active continuity incident"
            )
        recovery = recovery_edges.get(incident_id)
        if recovery is not None:
            recovery_boundary = _mapping(
                recovery["boundary"],
                "global continuity recovery boundary",
            )
            recovery_ms = _non_negative_integer(
                recovery_boundary["received_monotonic_ms"],
                "global continuity recovery monotonic boundary",
            )
            if segment.end_monotonic_ms > recovery_ms:
                raise EvidenceError("coverage restart group extends beyond incident recovery")


def _validate_affected_scopes(value: object) -> tuple[str, ...]:
    raw_scopes = _array(value, "coverage affected_scopes")
    if not raw_scopes or len(raw_scopes) > 256:
        raise EvidenceError("coverage affected scopes must contain 1 to 256 labels")
    scopes: list[str] = []
    scope_pattern = re.compile(r"SCOPE:[0-9]+:(?:call|put):[^:]+$")
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, str) or not raw_scope:
            raise EvidenceError("coverage affected scope must be a non-empty string")
        valid = (
            raw_scope in {"GLOBAL", "OPTION_LOCAL"}
            or (raw_scope.startswith("OPTION:") and len(raw_scope) > len("OPTION:"))
            or scope_pattern.fullmatch(raw_scope) is not None
        )
        if not valid:
            raise EvidenceError("coverage affected scope label is invalid")
        scopes.append(raw_scope)
    if scopes != sorted(set(scopes)):
        raise EvidenceError("coverage affected scopes must be unique and sorted")
    if "GLOBAL" in scopes and len(scopes) != 1:
        raise EvidenceError("GLOBAL coverage affected scope must stand alone")
    if "OPTION_LOCAL" in scopes and len(scopes) != 1:
        raise EvidenceError("OPTION_LOCAL coverage affected scope must stand alone")
    return tuple(scopes)


def _parse_coverage_blocking_groups(
    value: object,
    *,
    state: CoverageState,
) -> tuple[CoverageBlockingGroup, ...]:
    rows = _array(value, "coverage blocking_groups")
    if state is CoverageState.KNOWN_COMPLETE:
        if rows:
            raise EvidenceError("KNOWN_COMPLETE coverage must have empty blocking_groups")
        return ()
    if not rows or len(rows) > 256:
        raise EvidenceError("incomplete coverage must have 1 to 256 blocking groups")
    groups: list[CoverageBlockingGroup] = []
    forbidden = {
        CoverageBlockingReason.NONE.value,
        CoverageBlockingReason.LEGACY_UNATTRIBUTED.value,
        CoverageBlockingReason.ACTIVE_POSITIVE_SCOPE_INCOMPLETE.value,
    }
    for raw_group in rows:
        group = _mapping(raw_group, "coverage blocking group")
        _exact_keys(
            group,
            {"blocking_reason", "affected_scopes"},
            "coverage blocking group",
        )
        reason = _required_string(group, "blocking_reason")
        try:
            CoverageBlockingReason(reason)
        except ValueError as exc:
            raise EvidenceError(
                "coverage blocking group reason is outside the bounded allowlist"
            ) from exc
        if reason in forbidden:
            raise EvidenceError("coverage blocking group uses a synthetic or empty reason")
        groups.append(
            CoverageBlockingGroup(
                blocking_reason=reason,
                affected_scopes=_validate_affected_scopes(group["affected_scopes"]),
            )
        )
    identities = [(group.blocking_reason, group.affected_scopes) for group in groups]
    if identities != sorted(identities):
        raise EvidenceError("coverage blocking groups must be sorted")
    if len({group.blocking_reason for group in groups}) != len(groups):
        raise EvidenceError("coverage blocking group reasons must be unique")
    return tuple(groups)


def _summarize_blocking_group_scopes(
    groups: tuple[CoverageBlockingGroup, ...],
) -> tuple[str, ...]:
    scopes = {scope for group in groups for scope in group.affected_scopes}
    if "GLOBAL" in scopes:
        return ("GLOBAL",)
    if "OPTION_LOCAL" in scopes:
        if all(scope == "OPTION_LOCAL" or scope.startswith("OPTION:") for scope in scopes):
            return ("OPTION_LOCAL",)
        return ("GLOBAL",)
    ordered = tuple(sorted(scopes))
    if len(ordered) <= 256:
        return ordered
    if all(scope.startswith("OPTION:") for scope in ordered):
        return ("OPTION_LOCAL",)
    return ("GLOBAL",)


def _validate_fact_boundary(value: object, field: str) -> Mapping[str, object]:
    boundary = _mapping(value, field)
    _exact_keys(
        boundary,
        {
            "session_epoch",
            "ingress_seq",
            "received_monotonic_ms",
            "causal_seq",
        },
        field,
    )
    _positive_integer(boundary["session_epoch"], f"{field}.session_epoch")
    _non_negative_integer(boundary["ingress_seq"], f"{field}.ingress_seq")
    _non_negative_integer(
        boundary["received_monotonic_ms"],
        f"{field}.received_monotonic_ms",
    )
    _non_negative_integer(boundary["causal_seq"], f"{field}.causal_seq")
    return boundary


def _fact_boundary_order(boundary: Mapping[str, object]) -> tuple[int, int, int, int]:
    return (
        _non_negative_integer(
            boundary["received_monotonic_ms"],
            "fact boundary received_monotonic_ms",
        ),
        _positive_integer(boundary["session_epoch"], "fact boundary session_epoch"),
        _non_negative_integer(boundary["ingress_seq"], "fact boundary ingress_seq"),
        _non_negative_integer(boundary["causal_seq"], "fact boundary causal_seq"),
    )


def _validate_witness_scope(value: object) -> Mapping[str, object]:
    scope = _mapping(value, "witness.scope")
    _exact_keys(
        scope,
        {"expiration_timestamp_ms", "option_type", "tte_band_id"},
        "witness.scope",
    )
    _positive_integer(
        scope["expiration_timestamp_ms"],
        "witness.scope.expiration_timestamp_ms",
    )
    if scope["option_type"] not in {"call", "put"}:
        raise EvidenceError("witness scope option_type is invalid")
    _required_string(scope, "tte_band_id")
    return scope


def _validate_witness_formula_instrument(value: object) -> Mapping[str, object]:
    instrument = _mapping(value, "witness.formula_instrument")
    _exact_keys(
        instrument,
        {
            "instrument_name",
            "expiration_timestamp_ms",
            "option_type",
            "tte_band_id",
        },
        "witness.formula_instrument",
    )
    _required_string(instrument, "instrument_name")
    _positive_integer(
        instrument["expiration_timestamp_ms"],
        "witness.formula_instrument.expiration_timestamp_ms",
    )
    if instrument["option_type"] not in {"call", "put"}:
        raise EvidenceError("witness formula instrument option_type is invalid")
    _required_string(instrument, "tte_band_id")
    return instrument


def _validate_identity_fields(value: Mapping[str, object]) -> None:
    for field in ("code_identity", "runtime_identity", "policy_identity"):
        _required_string(value, field)
    if re.fullmatch(r"[0-9a-f]{40}", _required_string(value, "code_identity")) is None:
        raise EvidenceError("code_identity must be one full lowercase Git commit")
    if (
        re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            _required_string(value, "policy_identity"),
        )
        is None
    ):
        raise EvidenceError("policy_identity must be one lowercase SHA-256 digest")


def _required_string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise EvidenceError(f"{field} must be a non-empty string")
    return item


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise EvidenceError(f"{field} must be an array")
    return value


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    number = _non_negative_integer(value, field)
    if number == 0:
        raise EvidenceError(f"{field} must be positive")
    return number


def _decimal_text_value(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise EvidenceError(f"{field} must be a decimal string")
    try:
        number = Decimal(value)
    except Exception as exc:
        raise EvidenceError(f"{field} must be a decimal string") from exc
    if not number.is_finite():
        raise EvidenceError(f"{field} must be finite")
    return number


def _positive_decimal_text(value: object, field: str) -> Decimal:
    number = _decimal_text_value(value, field)
    if number <= 0:
        raise EvidenceError(f"{field} must be positive")
    return number


def _validate_non_claims(value: object, expected: tuple[str, ...], field: str) -> None:
    items = _array(value, f"{field}.non_claims")
    if tuple(items) != expected:
        raise EvidenceError(f"{field} non-claims are incomplete")


def _validate_instrument(value: object) -> None:
    instrument = _mapping(value, "instrument")
    _exact_keys(
        instrument,
        {
            "instrument_name",
            "expiration_timestamp_ms",
            "option_type",
            "strike_usdc",
        },
        "instrument",
    )
    _required_string(instrument, "instrument_name")
    _positive_integer(instrument["expiration_timestamp_ms"], "instrument.expiration_timestamp_ms")
    if instrument["option_type"] not in {"call", "put"}:
        raise EvidenceError("instrument.option_type is invalid")
    _positive_decimal_text(instrument["strike_usdc"], "instrument.strike_usdc")


def _validate_rule(value: object) -> None:
    rule = _mapping(value, "detector_boundaries")
    _exact_keys(
        rule,
        {
            "abs_delta_min",
            "abs_delta_max",
            "activation_ratio",
            "clear_ratio",
            "activation_observation_count",
            "clear_observation_count",
            "minimum_separation_ms",
        },
        "detector_boundaries",
    )
    for field in ("abs_delta_min", "abs_delta_max", "activation_ratio", "clear_ratio"):
        _decimal_text_value(rule[field], f"detector_boundaries.{field}")
    for field in ("activation_observation_count", "clear_observation_count"):
        _positive_integer(rule[field], f"detector_boundaries.{field}")
    _non_negative_integer(
        rule["minimum_separation_ms"],
        "detector_boundaries.minimum_separation_ms",
    )


def _validate_baseline(value: object) -> None:
    baseline = _mapping(value, "baseline")
    _exact_keys(
        baseline,
        {
            "window_variances",
            "variance_rate_per_minute",
            "annualized_volatility",
            "total_variance_interval",
        },
        "baseline",
    )
    windows = _array(baseline["window_variances"], "baseline.window_variances")
    if not windows:
        raise EvidenceError("baseline.window_variances must be non-empty")
    for index, value_item in enumerate(windows):
        item = _mapping(value_item, f"baseline.window_variances[{index}]")
        _exact_keys(item, {"lookback_minutes", "variance"}, "baseline window")
        _positive_integer(
            item["lookback_minutes"],
            f"baseline.window_variances[{index}].lookback_minutes",
        )
        _decimal_text_value(
            item["variance"],
            f"baseline.window_variances[{index}].variance",
        )
    _decimal_text_value(
        baseline["variance_rate_per_minute"],
        "baseline.variance_rate_per_minute",
    )
    _positive_decimal_text(
        baseline["annualized_volatility"],
        "baseline.annualized_volatility",
    )
    _validate_decimal_interval(
        baseline["total_variance_interval"],
        "baseline.total_variance_interval",
    )


def _validate_integer_interval(value: object, field: str) -> None:
    interval = _mapping(value, field)
    _exact_keys(interval, {"lower", "upper"}, field)
    lower = _non_negative_integer(interval["lower"], f"{field}.lower")
    upper = _non_negative_integer(interval["upper"], f"{field}.upper")
    if lower > upper:
        raise EvidenceError(f"{field} bounds are reversed")


def _validate_decimal_interval(value: object, field: str) -> None:
    interval = _mapping(value, field)
    _exact_keys(interval, {"lower", "upper"}, field)
    lower = _decimal_text_value(interval["lower"], f"{field}.lower")
    upper = _decimal_text_value(interval["upper"], f"{field}.upper")
    if lower > upper:
        raise EvidenceError(f"{field} bounds are reversed")


def _validate_levels(value: object, field: str) -> tuple[tuple[Decimal, Decimal], ...]:
    levels = _array(value, field)
    parsed: list[tuple[Decimal, Decimal]] = []
    for index, value_item in enumerate(levels):
        item = _mapping(value_item, f"{field}[{index}]")
        _exact_keys(item, {"price", "amount"}, f"{field}[{index}]")
        price = _decimal_text_value(item["price"], f"{field}[{index}].price")
        amount = _positive_decimal_text(item["amount"], f"{field}[{index}].amount")
        parsed.append((price, amount))
    return tuple(parsed)


def _validate_executable(
    value: object,
    *,
    target: Decimal,
    detector_boundaries: Mapping[str, object],
) -> None:
    executable = _mapping(value, "executable")
    _exact_keys(
        executable,
        {
            "consumed_bid_levels",
            "forward_usdc",
            "sell_price_usdc",
            "total_volatility_interval",
            "iv_interval",
            "delta_interval",
            "implied_total_variance_interval",
            "richness_interval",
        },
        "executable",
    )
    levels = _validate_levels(executable["consumed_bid_levels"], "executable.consumed_bid_levels")
    if not levels or any(price <= 0 for price, _ in levels):
        raise EvidenceError("anomaly consumed bid prices must be positive")
    if sum((amount for _, amount in levels), Decimal(0)) != target:
        raise EvidenceError("anomaly consumed depth does not equal target quantity")
    _positive_decimal_text(executable["forward_usdc"], "executable.forward_usdc")
    sell_price = _positive_decimal_text(executable["sell_price_usdc"], "executable.sell_price_usdc")
    if sum((price * amount for price, amount in levels), Decimal(0)) / target != sell_price:
        raise EvidenceError("anomaly sell price does not match consumed levels")
    for field in (
        "total_volatility_interval",
        "iv_interval",
        "delta_interval",
        "implied_total_variance_interval",
        "richness_interval",
    ):
        _validate_decimal_interval(executable[field], f"executable.{field}")
    delta = _mapping(executable["delta_interval"], "executable.delta_interval")
    absolute_delta_endpoints = (
        abs(_decimal_text_value(delta["lower"], "executable.delta_interval.lower")),
        abs(_decimal_text_value(delta["upper"], "executable.delta_interval.upper")),
    )
    delta_min = _decimal_text_value(
        detector_boundaries["abs_delta_min"],
        "detector_boundaries.abs_delta_min",
    )
    delta_max = _decimal_text_value(
        detector_boundaries["abs_delta_max"],
        "detector_boundaries.abs_delta_max",
    )
    if not (
        min(absolute_delta_endpoints) >= delta_min and max(absolute_delta_endpoints) <= delta_max
    ):
        raise EvidenceError("anomaly Delta lies outside detector boundaries")
    richness = _mapping(executable["richness_interval"], "executable.richness_interval")
    richness_lower = _decimal_text_value(richness["lower"], "executable.richness_interval.lower")
    activation = _decimal_text_value(
        detector_boundaries["activation_ratio"],
        "detector_boundaries.activation_ratio",
    )
    if richness_lower < activation:
        raise EvidenceError("anomaly richness does not satisfy activation boundary")


def _validate_combo_legs(
    value: object,
) -> tuple[tuple[str, Decimal], tuple[str, Decimal]]:
    legs = _array(value, "combo_legs")
    if len(legs) != 2:
        raise EvidenceError("combo_legs must contain exactly two legs")
    parsed: list[tuple[str, Decimal]] = []
    for index, value_item in enumerate(legs):
        leg = _mapping(value_item, f"combo_legs[{index}]")
        _exact_keys(leg, {"instrument_name", "amount"}, f"combo_legs[{index}]")
        name = _required_string(leg, "instrument_name")
        amount = _decimal_text_value(leg["amount"], f"combo_legs[{index}].amount")
        if amount == 0:
            raise EvidenceError("combo leg amount must be non-zero")
        parsed.append((name, amount))
    if len({name for name, _ in parsed}) != 2:
        raise EvidenceError("combo leg instruments must be distinct")
    if {amount for _, amount in parsed} not in ({Decimal(-1), Decimal(1)},):
        raise EvidenceError("combo leg amounts must be the exact signed 1:1 vector")
    return (parsed[0], parsed[1])


def _validate_count_mapping(value: object, field: str) -> None:
    counts = _mapping(value, field)
    for key, count in counts.items():
        if not isinstance(key, str) or not key:
            raise EvidenceError(f"{field} keys must be non-empty strings")
        _non_negative_integer(count, f"{field}.{key}")


def _merge_counts(target: Counter[str], value: object, field: str) -> None:
    counts = _mapping(value, field)
    for key, count in counts.items():
        if not isinstance(key, str) or not key:
            raise EvidenceError(f"{field} keys must be non-empty strings")
        target[key] += _non_negative_integer(count, f"{field}.{key}")


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise EvidenceError(f"{field} fields are not the exact repository-owned schema")


def _strict_evidence_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate evidence key: {key}")
        result[key] = value
    return result


def _reject_evidence_constant(value: str) -> None:
    raise EvidenceError(f"non-finite evidence number: {value}")


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


def _safe_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_" else "_" for character in value
    )

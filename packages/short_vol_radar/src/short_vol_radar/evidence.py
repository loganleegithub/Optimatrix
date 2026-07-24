from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
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


class EvidenceError(ValueError):
    """Repository-owned evidence is invalid or mixed."""


class CoverageState(StrEnum):
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"
    KNOWN_COMPLETE = "KNOWN_COMPLETE"
    KNOWN_DEGRADED = "KNOWN_DEGRADED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CoverageSegment:
    start_monotonic_ms: int
    end_monotonic_ms: int
    state: CoverageState


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
    heartbeat_interval_seconds: int,
    liveness_deadline_seconds: int,
    clock_drift_ppm: int,
) -> dict[str, object]:
    if not coverage_segments:
        raise EvidenceError("run summary requires at least one coverage segment")
    coverage = _coverage_object(tuple(coverage_segments))
    summary: dict[str, object] = {
        "object_kind": "RADAR_RUN_SUMMARY",
        "code_identity": code_identity,
        "runtime_identity": runtime_identity,
        "policy_identity": policy_identity,
        "runtime_started_monotonic_ms": coverage_segments[0].start_monotonic_ms,
        "clean_stop_monotonic_ms": coverage_segments[-1].end_monotonic_ms,
        "operational_constants": {
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
            "liveness_deadline_seconds": liveness_deadline_seconds,
            "clock_drift_ppm": clock_drift_ppm,
        },
        "coverage_segments": [
            {
                "start_monotonic_ms": segment.start_monotonic_ms,
                "end_monotonic_ms": segment.end_monotonic_ms,
                "state": segment.state.value,
            }
            for segment in coverage_segments
        ],
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
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
        except FileExistsError as exc:
            if duplicate_is_noop:
                return None
            raise EvidenceError(f"evidence path already exists: {path}") from exc
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
    if quote_causal_seq < detector_causal_seq:
        raise EvidenceError("atomic quote causal sequence precedes detector activation")
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
    if _required_string(value, "short_instrument_name") not in {name for name, _ in legs}:
        raise EvidenceError("atomic combo legs omit the short instrument")
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


def validate_run_summary(value: Mapping[str, object]) -> None:
    _exact_keys(
        value,
        {
            "object_kind",
            "code_identity",
            "runtime_identity",
            "policy_identity",
            "runtime_started_monotonic_ms",
            "clean_stop_monotonic_ms",
            "operational_constants",
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
    operational = _mapping(value["operational_constants"], "operational_constants")
    _exact_keys(
        operational,
        {
            "heartbeat_interval_seconds",
            "liveness_deadline_seconds",
            "clock_drift_ppm",
        },
        "operational_constants",
    )
    for field in operational:
        _positive_integer(operational[field], f"operational_constants.{field}")
    raw_segments = value["coverage_segments"]
    if not isinstance(raw_segments, list) or not raw_segments:
        raise EvidenceError("coverage_segments must be non-empty")
    segments = tuple(_parse_segment(item) for item in raw_segments)
    expected = _coverage_object(segments)
    if value["coverage"] != expected:
        raise EvidenceError("coverage totals do not match exact segments")
    if value["runtime_started_monotonic_ms"] != segments[0].start_monotonic_ms:
        raise EvidenceError("summary start does not match coverage")
    if value["clean_stop_monotonic_ms"] != segments[-1].end_monotonic_ms:
        raise EvidenceError("summary stop does not match coverage")
    _non_negative_integer(value["band_suspended_duration_ms"], "band_suspended_duration_ms")
    _validate_scope_counts(value["counts_by_scope"])
    for field in (
        "detector_unknown_transition_count_by_reason",
        "anomaly_end_count_by_reason",
        "known_active_duration_ms_sum_by_end_reason",
        "public_atomic_quote_state_transition_count",
    ):
        _validate_count_mapping(value[field], field)


def validate_evidence_directory(directory: Path) -> tuple[dict[str, object], ...]:
    objects: list[dict[str, object]] = []
    identities: set[tuple[object, object, object]] = set()
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
        elif kind == "PUBLIC_ATOMIC_QUOTE_EVENT":
            validate_atomic_event(value)
        elif kind == "RADAR_RUN_SUMMARY":
            validate_run_summary(value)
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
    return tuple(objects)


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
        if segment.end_monotonic_ms <= segment.start_monotonic_ms:
            raise EvidenceError("coverage segment must have positive duration")
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


def _parse_segment(value: object) -> CoverageSegment:
    if not isinstance(value, dict):
        raise EvidenceError("coverage segment must be an object")
    _exact_keys(value, {"start_monotonic_ms", "end_monotonic_ms", "state"}, "coverage segment")
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
    return CoverageSegment(start, end, state)


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

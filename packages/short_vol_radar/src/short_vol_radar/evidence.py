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
CORE_SOURCE_NAMES = tuple(
    sorted(
        (
            "combo_book",
            "combo_lifecycle",
            "heartbeat",
            "index",
            "option_book",
            "option_lifecycle",
            "option_ticker",
            "platform_state",
            "platform_state.public_methods_state",
            "public/get_combos",
            "public/get_instrument",
            "public/get_instruments",
            "public/get_time",
            "public/set_heartbeat",
            "public/status",
            "public/subscribe",
            "public/test",
            "public/unsubscribe",
        )
    )
)


class EvidenceError(ValueError):
    """Repository-owned evidence is invalid or mixed."""


class CoverageState(StrEnum):
    NO_APPLICABLE_SCOPE = "NO_APPLICABLE_SCOPE"
    KNOWN_COMPLETE = "KNOWN_COMPLETE"
    KNOWN_DEGRADED = "KNOWN_DEGRADED"
    UNKNOWN = "UNKNOWN"


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
    TICKER_SOURCE_STALE = "TICKER_SOURCE_STALE"
    SESSION_GAP = "SESSION_GAP"
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
OPTION_LOCAL_REASONS = frozenset(
    {
        "FORWARD_TICKER_UNKNOWN",
        "OPTION_CHANNEL_FAILURE",
        "TICKER_SOURCE_STALE",
        "TICKER_TIMESTAMP_AHEAD",
    }
)


@dataclass(frozen=True)
class CoverageSegment:
    start_monotonic_ms: int
    end_monotonic_ms: int
    state: CoverageState
    reason: str
    affected_scopes: tuple[str, ...]
    global_continuity_epoch: int


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
    operational_diagnostics: Mapping[str, object],
) -> dict[str, object]:
    if not coverage_segments:
        raise EvidenceError("run summary requires at least one coverage segment")
    coverage = _coverage_object(tuple(coverage_segments))
    diagnostics_version = operational_diagnostics.get("operational_diagnostics_schema_version")
    if diagnostics_version != 3:
        raise EvidenceError("current run-summary writer requires diagnostics schema version 3")
    coverage_rows: list[dict[str, object]] = []
    for segment in coverage_segments:
        coverage_rows.append(
            {
                "start_monotonic_ms": segment.start_monotonic_ms,
                "end_monotonic_ms": segment.end_monotonic_ms,
                "state": segment.state.value,
                "reason": segment.reason,
                "affected_scopes": list(segment.affected_scopes),
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
    if diagnostics_version != required_diagnostics_version:
        if required_diagnostics_version == 3:
            raise EvidenceError(
                "current run-summary validator requires diagnostics schema version 3"
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
    _validate_operational_diagnostics(
        diagnostics,
        observation_interval_ms=expected["observation_interval_ms"],
        runtime_started_monotonic_ms=segments[0].start_monotonic_ms,
        clean_stop_monotonic_ms=segments[-1].end_monotonic_ms,
        coverage_segments=segments,
    )
    _non_negative_integer(value["band_suspended_duration_ms"], "band_suspended_duration_ms")
    _validate_scope_counts(value["counts_by_scope"])
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
    return _validate_evidence_directory(directory, legacy_schema=False)


def validate_legacy_evidence_directory(
    directory: Path,
) -> tuple[dict[str, object], ...]:
    """Validate a sealed version-2 directory without rewriting or migrating it."""
    return _validate_evidence_directory(directory, legacy_schema=True)


def _validate_evidence_directory(
    directory: Path,
    *,
    legacy_schema: bool,
) -> tuple[dict[str, object], ...]:
    objects: list[dict[str, object]] = []
    identities: set[tuple[object, object, object]] = set()
    anomaly_episode_ids: set[str] = set()
    atomic_episode_ids: set[str] = set()
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
            anomaly_episode_ids.add(_required_string(value, "episode_identity"))
        elif kind == "PUBLIC_ATOMIC_QUOTE_EVENT":
            validate_atomic_event(value)
            atomic_episode_ids.add(_required_string(value, "episode_identity"))
        elif kind == "RADAR_RUN_SUMMARY":
            if legacy_schema:
                validate_legacy_run_summary(value)
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
    if not atomic_episode_ids <= anomaly_episode_ids:
        raise EvidenceError("atomic evidence references an absent anomaly episode")
    if summaries:
        counts = _array(summaries[0]["counts_by_scope"], "counts_by_scope")
        declared_episodes = sum(
            _non_negative_integer(
                _mapping(item, "scope count")["distinct_anomaly_episode_count"],
                "scope distinct_anomaly_episode_count",
            )
            for item in counts
        )
        if declared_episodes != len(anomaly_episode_ids):
            raise EvidenceError("summary episode count does not match anomaly evidence")
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
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        )
    reason = _required_string(value, "reason")
    try:
        CausalCause(reason)
    except ValueError as exc:
        raise EvidenceError("coverage reason is outside the causal cause whitelist") from exc
    affected_scopes = _validate_affected_scopes(value["affected_scopes"])
    epoch = _positive_integer(
        value["global_continuity_epoch"],
        "coverage segment global_continuity_epoch",
    )
    return CoverageSegment(
        start,
        end,
        state,
        reason=reason,
        affected_scopes=affected_scopes,
        global_continuity_epoch=epoch,
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


def _validate_operational_diagnostics(
    value: object,
    *,
    observation_interval_ms: int,
    runtime_started_monotonic_ms: int,
    clean_stop_monotonic_ms: int,
    coverage_segments: tuple[CoverageSegment, ...],
) -> None:
    diagnostics = _mapping(value, "operational_diagnostics")
    version = diagnostics.get("operational_diagnostics_schema_version")
    if version not in {2, 3}:
        raise EvidenceError("operational diagnostics schema version must be 2 or 3")
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
    if version == 3:
        fields.update(
            {
                "global_continuity",
                "ticker_application",
                "ticker_currentness",
                "option_local_availability",
            }
        )
    _exact_keys(
        diagnostics,
        fields,
        "operational_diagnostics",
    )
    _validate_runtime_limits(diagnostics["runtime_limits"])
    _validate_ingress_diagnostics(diagnostics["ingress"])
    _validate_rpc_diagnostics(diagnostics["rpc_by_method"], diagnostics_version=version)
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
    if version == 3:
        current_epoch, restart_edges = _validate_global_continuity(diagnostics["global_continuity"])
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
        )
        _validate_version_three_coverage(
            coverage_segments,
            current_epoch=current_epoch,
            restart_edges=restart_edges,
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
    if version == 3:
        witness_fields.update(
            {
                "global_continuity_epoch",
                "scope",
                "boundary",
                "formula_instrument",
            }
        )
    _exact_keys(witness, witness_fields, "operational_diagnostics.witness")
    if version == 3:
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
    if version == 3:
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
        if version == 3:
            current_epoch_start = next(
                segment.start_monotonic_ms
                for segment in coverage_segments
                if segment.global_continuity_epoch == current_epoch
            )
            if first_ms <= current_epoch_start:
                raise EvidenceError(
                    "joint witness boundary must be strictly later than the current epoch start"
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


def _validate_ingress_diagnostics(value: object) -> None:
    ingress = _mapping(value, "operational_diagnostics.ingress")
    fields = {
        "received_envelope_count",
        "reduced_envelope_count",
        "ingress_gap_or_duplicate_count",
        "queue_high_water_frames",
        "max_receive_to_reduce_lag_ms",
        "overflow_count",
    }
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
        fields = {
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
        if diagnostics_version == 3:
            fields.add("retired_or_censored_count")
        _exact_keys(row, fields, "operational_diagnostics RPC row")
        method = _required_string(row, "method")
        if not method.startswith("public/"):
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
        if diagnostics_version == 3:
            request_count = _non_negative_integer(row["request_count"], "request_count")
            terminal_count = sum(
                _non_negative_integer(row[field], f"RPC row {field}")
                for field in (
                    "success_count",
                    "error_count",
                    "late_response_count",
                    "retired_or_censored_count",
                )
            )
            if request_count != terminal_count:
                raise EvidenceError("RPC conservation does not reconcile requests and outcomes")
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
        keys: list[str] = []
        for raw_field in fields:
            field = _mapping(raw_field, f"{source} consumed field")
            _exact_keys(field, {"key", "type"}, f"{source} consumed field")
            key = _required_string(field, "key")
            field_type = _required_string(field, "type")
            if field_type not in {
                "array",
                "boolean",
                "integer",
                "null",
                "number",
                "object",
                "string",
            }:
                raise EvidenceError("source-shape field type is invalid")
            keys.append(key)
        if keys != sorted(set(keys)):
            raise EvidenceError("source-shape consumed fields must be unique and sorted")
    if tuple(sources) != CORE_SOURCE_NAMES:
        raise EvidenceError("operational source-shape rows are incomplete or unsorted")
    return counts


def _validate_global_continuity(
    value: object,
) -> tuple[int, tuple[Mapping[str, object], ...]]:
    continuity = _mapping(value, "operational_diagnostics.global_continuity")
    _exact_keys(
        continuity,
        {
            "current_epoch",
            "restart_count",
            "restart_count_by_reason",
            "restart_edges",
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
        _exact_keys(
            edge,
            {
                "incident_id",
                "from_epoch",
                "to_epoch",
                "reason",
                "failure_domain",
                "affected_scopes",
                "boundary",
            },
            "global continuity restart edge",
        )
        if _positive_integer(edge["incident_id"], "continuity incident_id") != expected_id:
            raise EvidenceError("global continuity incident ids must be unique and ordered")
        from_epoch = _positive_integer(edge["from_epoch"], "continuity from_epoch")
        to_epoch = _positive_integer(edge["to_epoch"], "continuity to_epoch")
        if from_epoch != expected_id or to_epoch != expected_id + 1:
            raise EvidenceError("global continuity restart edge does not advance exactly one epoch")
        reason = _required_string(edge, "reason")
        try:
            CausalCause(reason)
        except ValueError as exc:
            raise EvidenceError(
                "global continuity restart reason is outside the causal cause whitelist"
            ) from exc
        if edge["failure_domain"] not in FAILURE_DOMAINS:
            raise EvidenceError("global continuity failure domain is outside the whitelist")
        _validate_affected_scopes(edge["affected_scopes"])
        _validate_fact_boundary(edge["boundary"], "global continuity restart boundary")
        edge_reasons[reason] += 1
        edges.append(edge)
    if dict(edge_reasons) != dict(restart_by_reason):
        raise EvidenceError("global continuity restart edges do not match reason totals")
    return current_epoch, tuple(edges)


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
) -> None:
    availability = _mapping(value, "operational_diagnostics.option_local_availability")
    _exact_keys(
        availability,
        {
            "unavailable_count_by_reason",
            "recovery_count_by_reason",
            "end_count_by_disposition",
            "retained_interval_limit",
            "omitted_interval_count",
            "omitted_interval_count_by_reason",
            "intervals",
        },
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
    if limit != 256:
        raise EvidenceError("option-local retained interval limit must be 256")
    omitted = _non_negative_integer(
        availability["omitted_interval_count"],
        "option-local omitted_interval_count",
    )
    rows = _array(availability["intervals"], "option_local_availability.intervals")
    if len(rows) > limit:
        raise EvidenceError("option-local intervals exceed bounded 256 rows")
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
        disposition = row["end_disposition"]
        if disposition not in {"RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"}:
            raise EvidenceError("option-local interval end disposition is invalid")
        epoch = _positive_integer(
            row["global_continuity_epoch"],
            "option-local interval continuity epoch",
        )
        if epoch > current_epoch:
            raise EvidenceError("option-local interval continuity epoch is in the future")
        retained_by_reason[reason] += 1
        retained_by_reason_and_disposition[(reason, disposition)] += 1
    raw_omitted_by_reason = _mapping(
        availability["omitted_interval_count_by_reason"],
        "option_local_availability.omitted_interval_count_by_reason",
    )
    omitted_by_reason_and_disposition: Counter[tuple[str, str]] = Counter()
    for reason, raw_counts in raw_omitted_by_reason.items():
        if not isinstance(reason, str) or not reason:
            raise EvidenceError("option-local omitted reason must be non-empty")
        if reason not in OPTION_LOCAL_REASONS:
            raise EvidenceError("option-local reason whitelist rejected an omitted reason")
        counts = _mapping(raw_counts, f"option-local omitted counts {reason}")
        _validate_named_non_negative_counts(
            counts,
            {"RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"},
            f"option-local omitted counts {reason}",
        )
        for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP"):
            count = _non_negative_integer(
                counts[disposition],
                f"option-local omitted {reason} {disposition}",
            )
            if count:
                omitted_by_reason_and_disposition[(reason, disposition)] = count
    if sum(omitted_by_reason_and_disposition.values()) != omitted:
        raise EvidenceError("option-local conservation does not reconcile omitted intervals")
    total_starts = sum(unavailable_counts.values())
    if total_starts != len(rows) + omitted or total_starts != sum(end_counts.values()):
        raise EvidenceError("option-local conservation does not reconcile starts and ends")
    for reason, start_count in unavailable_counts.items():
        retained_count = retained_by_reason[reason]
        omitted_count = sum(
            omitted_by_reason_and_disposition[(reason, disposition)]
            for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP")
        )
        if start_count != retained_count + omitted_count:
            raise EvidenceError("option-local conservation does not reconcile reason totals")
    if set(retained_by_reason) - set(unavailable_counts):
        raise EvidenceError("option-local conservation has an orphan retained reason")
    if {reason for reason, _ in omitted_by_reason_and_disposition} - set(unavailable_counts):
        raise EvidenceError("option-local conservation has an orphan omitted reason")
    for disposition, declared_count in end_counts.items():
        actual_count = sum(
            count
            for (reason, candidate), count in (
                retained_by_reason_and_disposition + omitted_by_reason_and_disposition
            ).items()
            if candidate == disposition
        )
        if declared_count != actual_count:
            raise EvidenceError("option-local conservation does not reconcile end dispositions")
    all_reasons = set(unavailable_counts) | set(recovery_counts)
    for reason in all_reasons:
        actual_recovered = (
            retained_by_reason_and_disposition[(reason, "RECOVERED")]
            + omitted_by_reason_and_disposition[(reason, "RECOVERED")]
        )
        if recovery_counts.get(reason, 0) != actual_recovered:
            raise EvidenceError("option-local conservation does not reconcile recoveries")


def _validate_version_three_coverage(
    segments: tuple[CoverageSegment, ...],
    *,
    current_epoch: int,
    restart_edges: tuple[Mapping[str, object], ...],
) -> None:
    epochs = [segment.global_continuity_epoch for segment in segments]
    if epochs[0] != 1 or epochs[-1] != current_epoch:
        raise EvidenceError("coverage continuity epoch does not match global continuity")
    if epochs != sorted(epochs):
        raise EvidenceError("coverage continuity epoch moved backward")
    if any(after - before > 1 for before, after in pairwise(epochs)):
        raise EvidenceError("coverage continuity epoch skipped a restart boundary")
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
        if (
            before.global_continuity_epoch != restart["from_epoch"]
            or after.global_continuity_epoch != restart["to_epoch"]
            or after.start_monotonic_ms != boundary["received_monotonic_ms"]
            or after.reason != restart["reason"]
            or after.affected_scopes != restart_scopes
        ):
            raise EvidenceError("coverage epoch edge does not match its continuity restart edge")


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

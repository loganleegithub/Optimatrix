from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any

from market_monitor.types import SourceDataError, TimeInterval
from options_domain import OptionType
from options_domain.instruments import MAX_TTE_MS, SETTLEMENT_WINDOW_MS

POLICY_FAMILY = "CONSERVATIVE_MULTI_HORIZON_EXECUTABLE_IV_RICHNESS"
MINIMUM_TTE_MINUTES = 30
MAXIMUM_TTE_MINUTES = 72 * 60
EXPECTED_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class PolicyError(ValueError):
    """A repository-owned Radar Policy is invalid."""


@dataclass(frozen=True)
class OptionRule:
    abs_delta_min: Decimal
    abs_delta_max: Decimal
    activation_ratio: Decimal
    clear_ratio: Decimal
    activation_observation_count: int
    clear_observation_count: int
    minimum_separation_ms: int


@dataclass(frozen=True)
class TteBand:
    band_id: str
    lower_bound_minutes: int
    upper_bound_minutes: int
    return_interval_minutes: int
    lookbacks_minutes: tuple[int, ...]
    annualized_variance_floor: Decimal
    option_rules: Mapping[OptionType, OptionRule]

    @property
    def lower_bound_ms(self) -> int:
        return self.lower_bound_minutes * 60_000

    @property
    def upper_bound_ms(self) -> int:
        return self.upper_bound_minutes * 60_000


@dataclass(frozen=True)
class RuntimeLimits:
    heartbeat_interval_seconds: int
    session_liveness_deadline_ms: int
    rpc_deadline_ms: int
    clock_refresh_interval_ms: int
    clock_stale_deadline_ms: int
    index_source_stale_deadline_ms: int
    index_history_refresh_interval_ms: int
    index_history_source_stale_deadline_ms: int
    ticker_source_stale_deadline_ms: int
    notification_queue_lag_deadline_ms: int
    time_boundary_poll_interval_ms: int

    def as_object(self) -> dict[str, int]:
        return {
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "session_liveness_deadline_ms": self.session_liveness_deadline_ms,
            "rpc_deadline_ms": self.rpc_deadline_ms,
            "clock_refresh_interval_ms": self.clock_refresh_interval_ms,
            "clock_stale_deadline_ms": self.clock_stale_deadline_ms,
            "index_source_stale_deadline_ms": self.index_source_stale_deadline_ms,
            "index_history_refresh_interval_ms": self.index_history_refresh_interval_ms,
            "index_history_source_stale_deadline_ms": self.index_history_source_stale_deadline_ms,
            "ticker_source_stale_deadline_ms": self.ticker_source_stale_deadline_ms,
            "notification_queue_lag_deadline_ms": self.notification_queue_lag_deadline_ms,
            "time_boundary_poll_interval_ms": self.time_boundary_poll_interval_ms,
        }


@dataclass(frozen=True)
class RadarPolicy:
    identity: str
    schema_version: int
    family: str
    target_base_quantity_btc: Decimal
    runtime_limits: RuntimeLimits
    tte_bands: tuple[TteBand, ...]

    @property
    def largest_lookback_minutes(self) -> int:
        return max(max(band.lookbacks_minutes) for band in self.tte_bands)

    @property
    def return_interval_minutes(self) -> int:
        intervals = {band.return_interval_minutes for band in self.tte_bands}
        if len(intervals) != 1:
            raise RuntimeError("Radar Policy has inconsistent return intervals")
        return next(iter(intervals))


class TimeApplicability(StrEnum):
    IN_BAND = "IN_BAND"
    ADJACENT_BAND_BOUNDARY = "ADJACENT_BAND_BOUNDARY"
    POLICY_GAP = "POLICY_GAP"
    FINAL_WINDOW = "FINAL_WINDOW"
    MONITOR_BOUNDARY = "MONITOR_BOUNDARY"
    OUT_OF_MONITOR_SCOPE = "OUT_OF_MONITOR_SCOPE"


@dataclass(frozen=True)
class TimeApplicabilityResult:
    classification: TimeApplicability
    band: TteBand | None = None


def classify_time_applicability(
    policy: RadarPolicy,
    *,
    expiration_timestamp_ms: int,
    trusted_time: TimeInterval,
    option_type: OptionType,
) -> TimeApplicabilityResult:
    lower_tte_ms = expiration_timestamp_ms - trusted_time.upper_ms
    upper_tte_ms = expiration_timestamp_ms - trusted_time.lower_ms
    if upper_tte_ms <= 0 or lower_tte_ms > MAX_TTE_MS:
        return TimeApplicabilityResult(TimeApplicability.OUT_OF_MONITOR_SCOPE)
    if lower_tte_ms <= 0 or upper_tte_ms > MAX_TTE_MS:
        return TimeApplicabilityResult(TimeApplicability.MONITOR_BOUNDARY)
    if lower_tte_ms <= SETTLEMENT_WINDOW_MS:
        return TimeApplicabilityResult(TimeApplicability.FINAL_WINDOW)
    band = band_for_tte(
        policy,
        lower_tte_ms=lower_tte_ms,
        upper_tte_ms=upper_tte_ms,
        option_type=option_type,
    )
    if band is not None:
        return TimeApplicabilityResult(TimeApplicability.IN_BAND, band)
    touched = bands_touched_by_tte(
        policy,
        lower_tte_ms=lower_tte_ms,
        upper_tte_ms=upper_tte_ms,
        option_type=option_type,
    )
    if _bands_are_adjacent(touched):
        return TimeApplicabilityResult(TimeApplicability.ADJACENT_BAND_BOUNDARY)
    return TimeApplicabilityResult(TimeApplicability.POLICY_GAP)


def load_policy(path: Path, expected_digest: str) -> RadarPolicy:
    try:
        exact_bytes = path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"cannot read Policy: {path}") from exc
    return load_policy_bytes(exact_bytes, expected_digest)


def load_policy_bytes(exact_bytes: bytes, expected_digest: str) -> RadarPolicy:
    if EXPECTED_DIGEST_PATTERN.fullmatch(expected_digest) is None:
        raise PolicyError("expected Policy digest must be sha256:<64 lowercase hex>")
    actual_digest = f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"
    if actual_digest != expected_digest:
        raise PolicyError("Policy digest mismatch")
    if exact_bytes.startswith(b"\xef\xbb\xbf"):
        raise PolicyError("Policy must not contain a UTF-8 BOM")
    try:
        text = exact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyError("Policy must be UTF-8") from exc
    try:
        raw = json.loads(
            text,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_non_finite,
            object_pairs_hook=_strict_object,
        )
    except (json.JSONDecodeError, SourceDataError) as exc:
        raise PolicyError(f"invalid Policy JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError("Policy top level must be one object")
    return _parse_policy(raw, actual_digest)


def digest_policy_bytes(exact_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"


def band_for_tte(
    policy: RadarPolicy,
    *,
    lower_tte_ms: int,
    upper_tte_ms: int,
    option_type: OptionType,
) -> TteBand | None:
    for band in policy.tte_bands:
        if (
            lower_tte_ms > band.lower_bound_ms
            and upper_tte_ms <= band.upper_bound_ms
            and option_type in band.option_rules
        ):
            return band
    return None


def bands_touched_by_tte(
    policy: RadarPolicy,
    *,
    lower_tte_ms: int,
    upper_tte_ms: int,
    option_type: OptionType,
) -> tuple[TteBand, ...]:
    return tuple(
        band
        for band in policy.tte_bands
        if option_type in band.option_rules
        and upper_tte_ms > band.lower_bound_ms
        and lower_tte_ms <= band.upper_bound_ms
    )


def _bands_are_adjacent(touched: tuple[TteBand, ...]) -> bool:
    if len(touched) != 2:
        return False
    earlier, later = sorted(touched, key=lambda item: item.lower_bound_minutes)
    return earlier.upper_bound_minutes == later.lower_bound_minutes


def _parse_policy(raw: dict[str, object], identity: str) -> RadarPolicy:
    _require_exact_keys(
        raw,
        {
            "policy_schema_version",
            "policy_family",
            "target_base_quantity_btc",
            "runtime_limits",
            "tte_bands",
        },
        "Policy",
    )
    schema_version = _positive_int(raw["policy_schema_version"], "policy_schema_version")
    if schema_version != 5:
        raise PolicyError("policy_schema_version must be exactly 5")
    family = raw["policy_family"]
    if family != POLICY_FAMILY:
        raise PolicyError(f"policy_family must be {POLICY_FAMILY}")
    target = _positive_decimal(raw["target_base_quantity_btc"], "target_base_quantity_btc")
    runtime_limits = _parse_runtime_limits(raw["runtime_limits"])
    bands_raw = raw["tte_bands"]
    if not isinstance(bands_raw, list) or not bands_raw:
        raise PolicyError("tte_bands must be a non-empty array")
    bands = tuple(_parse_band(item, index) for index, item in enumerate(bands_raw))
    band_ids = [band.band_id for band in bands]
    if len(set(band_ids)) != len(band_ids):
        raise PolicyError("tte_bands band_id values must be unique")
    ordered = tuple(sorted(bands, key=lambda item: (item.lower_bound_minutes, item.band_id)))
    if len({band.return_interval_minutes for band in ordered}) != 1:
        raise PolicyError("tte_bands must share one return_interval_minutes owner")
    for previous, current in pairwise(ordered):
        if current.lower_bound_minutes < previous.upper_bound_minutes:
            raise PolicyError("tte_bands must not overlap")
    return RadarPolicy(
        identity=identity,
        schema_version=schema_version,
        family=family,
        target_base_quantity_btc=target,
        runtime_limits=runtime_limits,
        tte_bands=ordered,
    )


def _parse_runtime_limits(value: object) -> RuntimeLimits:
    if not isinstance(value, dict):
        raise PolicyError("runtime_limits must be an object")
    fields = {
        "heartbeat_interval_seconds",
        "session_liveness_deadline_ms",
        "rpc_deadline_ms",
        "clock_refresh_interval_ms",
        "clock_stale_deadline_ms",
        "index_source_stale_deadline_ms",
        "index_history_refresh_interval_ms",
        "index_history_source_stale_deadline_ms",
        "ticker_source_stale_deadline_ms",
        "notification_queue_lag_deadline_ms",
        "time_boundary_poll_interval_ms",
    }
    _require_exact_keys(value, fields, "runtime_limits")
    parsed = {field: _positive_int(value[field], f"runtime_limits.{field}") for field in fields}
    if parsed["time_boundary_poll_interval_ms"] > 1_000:
        raise PolicyError("runtime_limits.time_boundary_poll_interval_ms must be <= 1000")
    if parsed["time_boundary_poll_interval_ms"] > parsed["ticker_source_stale_deadline_ms"]:
        raise PolicyError(
            "runtime_limits.ticker_source_stale_deadline_ms must cover "
            "the time-boundary poll interval"
        )
    if parsed["rpc_deadline_ms"] < parsed["time_boundary_poll_interval_ms"]:
        raise PolicyError(
            "runtime_limits.rpc_deadline_ms must cover the time-boundary poll interval"
        )
    if parsed["session_liveness_deadline_ms"] <= parsed["heartbeat_interval_seconds"] * 1_000:
        raise PolicyError(
            "runtime_limits.session_liveness_deadline_ms must exceed heartbeat interval"
        )
    if parsed["clock_stale_deadline_ms"] <= parsed["clock_refresh_interval_ms"]:
        raise PolicyError(
            "runtime_limits.clock_stale_deadline_ms must exceed clock refresh interval"
        )
    if (
        parsed["index_history_source_stale_deadline_ms"]
        <= parsed["index_history_refresh_interval_ms"]
    ):
        raise PolicyError(
            "runtime_limits.index_history_source_stale_deadline_ms must exceed "
            "the index history refresh interval"
        )
    return RuntimeLimits(**parsed)


def _parse_band(value: object, index: int) -> TteBand:
    if not isinstance(value, dict):
        raise PolicyError(f"tte_bands[{index}] must be an object")
    _require_exact_keys(
        value,
        {
            "band_id",
            "lower_bound_minutes",
            "upper_bound_minutes",
            "return_interval_minutes",
            "lookbacks_minutes",
            "annualized_variance_floor",
            "option_rules",
        },
        f"tte_bands[{index}]",
    )
    band_id = value["band_id"]
    if not isinstance(band_id, str) or not band_id.strip():
        raise PolicyError(f"tte_bands[{index}].band_id must be a non-empty string")
    lower = _non_negative_int(value["lower_bound_minutes"], f"{band_id}.lower_bound_minutes")
    upper = _positive_int(value["upper_bound_minutes"], f"{band_id}.upper_bound_minutes")
    if lower < MINIMUM_TTE_MINUTES or upper > MAXIMUM_TTE_MINUTES or lower >= upper:
        raise PolicyError(f"{band_id} bounds must satisfy 30 <= lower < upper <= 4320")
    return_interval = _positive_int(
        value["return_interval_minutes"],
        f"{band_id}.return_interval_minutes",
    )
    lookbacks_raw = value["lookbacks_minutes"]
    if not isinstance(lookbacks_raw, list) or not lookbacks_raw:
        raise PolicyError(f"{band_id}.lookbacks_minutes must be non-empty")
    lookbacks = tuple(_positive_int(item, f"{band_id}.lookbacks_minutes") for item in lookbacks_raw)
    if len(set(lookbacks)) != len(lookbacks):
        raise PolicyError(f"{band_id}.lookbacks_minutes must be unique")
    if any(lookback % return_interval != 0 for lookback in lookbacks):
        raise PolicyError(
            f"{band_id}.lookbacks_minutes must be divisible by return_interval_minutes"
        )
    rules_raw = value["option_rules"]
    if not isinstance(rules_raw, dict) or not rules_raw:
        raise PolicyError(f"{band_id}.option_rules must be a non-empty object")
    if not set(rules_raw) <= {item.value for item in OptionType}:
        raise PolicyError(f"{band_id}.option_rules contains an unsupported option type")
    rules = {
        OptionType(key): _parse_rule(rule, f"{band_id}.option_rules.{key}")
        for key, rule in rules_raw.items()
    }
    return TteBand(
        band_id=band_id,
        lower_bound_minutes=lower,
        upper_bound_minutes=upper,
        return_interval_minutes=return_interval,
        lookbacks_minutes=lookbacks,
        annualized_variance_floor=_positive_decimal(
            value["annualized_variance_floor"],
            f"{band_id}.annualized_variance_floor",
        ),
        option_rules=MappingProxyType(rules),
    )


def _parse_rule(value: object, field: str) -> OptionRule:
    if not isinstance(value, dict):
        raise PolicyError(f"{field} must be an object")
    _require_exact_keys(
        value,
        {
            "abs_delta_min",
            "abs_delta_max",
            "activation_ratio",
            "clear_ratio",
            "activation_observation_count",
            "clear_observation_count",
            "minimum_separation_ms",
        },
        field,
    )
    delta_min = _non_negative_decimal(value["abs_delta_min"], f"{field}.abs_delta_min")
    delta_max = _positive_decimal(value["abs_delta_max"], f"{field}.abs_delta_max")
    if not (Decimal(0) <= delta_min < delta_max <= Decimal(1)):
        raise PolicyError(f"{field} Delta bounds are invalid")
    activation = _positive_decimal(value["activation_ratio"], f"{field}.activation_ratio")
    clear = _positive_decimal(value["clear_ratio"], f"{field}.clear_ratio")
    if not (activation > 1 and clear < activation):
        raise PolicyError(f"{field} requires activation > 1 and 0 < clear < activation")
    return OptionRule(
        abs_delta_min=delta_min,
        abs_delta_max=delta_max,
        activation_ratio=activation,
        clear_ratio=clear,
        activation_observation_count=_positive_int(
            value["activation_observation_count"],
            f"{field}.activation_observation_count",
        ),
        clear_observation_count=_positive_int(
            value["clear_observation_count"],
            f"{field}.clear_observation_count",
        ),
        minimum_separation_ms=_non_negative_int(
            value["minimum_separation_ms"],
            f"{field}.minimum_separation_ms",
        ),
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceDataError(f"duplicate Policy key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise SourceDataError(f"non-finite Policy number: {value}")


def _require_exact_keys(value: dict[str, object], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise PolicyError(f"{field} keys mismatch; missing={missing}, unknown={unknown}")


def _positive_decimal(value: object, field: str) -> Decimal:
    number = _decimal(value, field)
    if number <= 0:
        raise PolicyError(f"{field} must be positive")
    return number


def _non_negative_decimal(value: object, field: str) -> Decimal:
    number = _decimal(value, field)
    if number < 0:
        raise PolicyError(f"{field} must be non-negative")
    return number


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PolicyError(f"{field} must be a finite JSON numeric token")
    return value


def _positive_int(value: object, field: str) -> int:
    number = _non_negative_int(value, field)
    if number == 0:
        raise PolicyError(f"{field} must be positive")
    return number


def _non_negative_int(value: object, field: str) -> int:
    number = _decimal(value, field)
    if number != number.to_integral_value() or number < 0:
        raise PolicyError(f"{field} must be a non-negative integer")
    return int(number)

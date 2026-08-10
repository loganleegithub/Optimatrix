from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import pairwise

from options_domain import OptionType

from short_vol_radar.black import DecimalInterval
from short_vol_radar.policy import RadarPolicy, ScoreModel

IDENTITY_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
CODE_IDENTITY_PATTERN = re.compile(r"[0-9a-f]{40}")


class ScoreUnavailable(ValueError):
    """Required causal inputs cannot produce one V2 score."""


class ScoreFactorName(StrEnum):
    PREMIUM_RICHNESS = "A"
    SURFACE_RESIDUAL = "S"
    TERM_RESIDUAL = "T"
    PATH_QUALITY = "D"
    LIQUIDITY_QUALITY = "E"


class ScoreBand(StrEnum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"
    REVIEW = "REVIEW"


class ScoreCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class LeaderCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ScoreObservationSignal(StrEnum):
    ACTIVATE = "ACTIVATE"
    CLEAR = "CLEAR"
    NEUTRAL = "NEUTRAL"


class DiagnosticKnownness(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class SamplingKind(StrEnum):
    CANONICAL_HIGH = "CANONICAL_HIGH"
    DETERMINISTIC_BAND_CONTROL = "DETERMINISTIC_BAND_CONTROL"


@dataclass(frozen=True)
class FactorRawInput:
    name: str
    interval: DecimalInterval | None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("factor raw-input name must be non-empty")
        if self.interval is not None:
            _require_finite_interval(self.interval, self.name)

    def as_object(self) -> dict[str, object]:
        return {"name": self.name, "interval": _interval_object(self.interval)}

    @classmethod
    def from_object(cls, value: object) -> FactorRawInput:
        raw = _mapping(value, "factor raw input")
        _exact_keys(raw, {"name", "interval"}, "factor raw input")
        name = _non_empty_string(raw["name"], "factor raw input.name")
        return cls(name=name, interval=_interval_from_object(raw["interval"], allow_none=True))


@dataclass(frozen=True)
class ScoreFactor:
    name: ScoreFactorName
    raw_inputs: tuple[FactorRawInput, ...]
    normalized: DecimalInterval | None
    weighted_contribution: DecimalInterval | None
    unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.raw_inputs:
            raise ValueError(f"score factor {self.name.value} requires raw inputs")
        if (self.normalized is None) != (self.weighted_contribution is None):
            raise ValueError("normalized and weighted contribution knownness must match")
        if self.normalized is None:
            if not self.unknown_reason:
                raise ValueError("unknown score factor requires a reason")
        elif self.unknown_reason is not None:
            raise ValueError("known score factor cannot carry an unknown reason")
        if self.normalized is not None:
            assert self.weighted_contribution is not None
            normalized_lower = (
                Decimal(-1)
                if self.name in {ScoreFactorName.SURFACE_RESIDUAL, ScoreFactorName.TERM_RESIDUAL}
                else Decimal(0)
            )
            _require_interval_range(
                self.normalized,
                normalized_lower,
                Decimal(1),
                f"factor {self.name.value} normalized",
            )
            _require_interval_range(
                self.weighted_contribution,
                Decimal(-1),
                Decimal(1),
                f"factor {self.name.value} weighted contribution",
            )

    def as_object(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "raw_inputs": [value.as_object() for value in self.raw_inputs],
            "normalized": _interval_object(self.normalized),
            "weighted_contribution": _interval_object(self.weighted_contribution),
            "unknown_reason": self.unknown_reason,
        }

    @classmethod
    def from_object(cls, value: object) -> ScoreFactor:
        raw = _mapping(value, "score factor")
        _exact_keys(
            raw,
            {"name", "raw_inputs", "normalized", "weighted_contribution", "unknown_reason"},
            "score factor",
        )
        raw_inputs = raw["raw_inputs"]
        if not isinstance(raw_inputs, list):
            raise ValueError("score factor.raw_inputs must be an array")
        return cls(
            name=ScoreFactorName(_non_empty_string(raw["name"], "score factor.name")),
            raw_inputs=tuple(FactorRawInput.from_object(member) for member in raw_inputs),
            normalized=_interval_from_object(raw["normalized"], allow_none=True),
            weighted_contribution=_interval_from_object(
                raw["weighted_contribution"], allow_none=True
            ),
            unknown_reason=_optional_string(raw["unknown_reason"], "score factor.unknown_reason"),
        )


@dataclass(frozen=True)
class RadarScoreInputs:
    stressed_richness: DecimalInterval
    stressed_executable_bid_iv: DecimalInterval
    local_same_type_mark_iv: Decimal | None
    current_expiry_atm_mark_iv: Decimal | None
    adjacent_expiry_atm_mark_iv: Decimal | None
    adverse_semivariance_share: DecimalInterval
    jump_share: DecimalInterval
    target_spread_ticks: DecimalInterval
    bid_consumed_level_count: int
    ask_consumed_level_count: int


@dataclass(frozen=True)
class RadarScoreResult:
    premium_evidence: DecimalInterval
    risk_quality: DecimalInterval
    score: DecimalInterval
    band: ScoreBand
    coverage: ScoreCoverage
    missing_factors: tuple[ScoreFactorName, ...]
    factors: tuple[ScoreFactor, ...]

    def __post_init__(self) -> None:
        names = tuple(factor.name for factor in self.factors)
        if names != tuple(ScoreFactorName):
            raise ValueError("score result requires exactly ordered A/S/T/D/E factors")
        if tuple(sorted(set(self.missing_factors), key=lambda item: item.value)) != tuple(
            sorted(self.missing_factors, key=lambda item: item.value)
        ):
            raise ValueError("score result missing factors must be unique")
        actual_missing = tuple(factor.name for factor in self.factors if factor.normalized is None)
        if self.missing_factors != actual_missing:
            raise ValueError("score result missing factors disagree with factor knownness")
        if any(
            factor in self.missing_factors
            for factor in (
                ScoreFactorName.PREMIUM_RICHNESS,
                ScoreFactorName.PATH_QUALITY,
                ScoreFactorName.LIQUIDITY_QUALITY,
            )
        ):
            raise ValueError("required A/D/E score factors cannot be unknown")
        expected_coverage = (
            ScoreCoverage.PARTIAL if self.missing_factors else ScoreCoverage.COMPLETE
        )
        if self.coverage is not expected_coverage:
            raise ValueError("score result coverage disagrees with missing factors")
        _require_interval_range(self.premium_evidence, Decimal(0), Decimal(1), "premium evidence")
        _require_interval_range(self.risk_quality, Decimal(0), Decimal(1), "risk quality")
        _require_interval_range(self.score, Decimal(0), Decimal(100), "score")

    def as_object(self) -> dict[str, object]:
        return {
            "premium_evidence": _interval_object(self.premium_evidence),
            "risk_quality": _interval_object(self.risk_quality),
            "score": _interval_object(self.score),
            "band": self.band.value,
            "coverage": self.coverage.value,
            "missing_factors": [factor.value for factor in self.missing_factors],
            "factors": [factor.as_object() for factor in self.factors],
        }

    @classmethod
    def from_object(cls, value: object) -> RadarScoreResult:
        raw = _mapping(value, "radar score result")
        _exact_keys(
            raw,
            {
                "premium_evidence",
                "risk_quality",
                "score",
                "band",
                "coverage",
                "missing_factors",
                "factors",
            },
            "radar score result",
        )
        missing = raw["missing_factors"]
        factors = raw["factors"]
        if not isinstance(missing, list) or not isinstance(factors, list):
            raise ValueError("score result missing_factors and factors must be arrays")
        return cls(
            premium_evidence=_required_interval(raw["premium_evidence"]),
            risk_quality=_required_interval(raw["risk_quality"]),
            score=_required_interval(raw["score"]),
            band=ScoreBand(_non_empty_string(raw["band"], "score result.band")),
            coverage=ScoreCoverage(_non_empty_string(raw["coverage"], "score result.coverage")),
            missing_factors=tuple(ScoreFactorName(str(member)) for member in missing),
            factors=tuple(ScoreFactor.from_object(member) for member in factors),
        )


@dataclass(frozen=True)
class RadarBucketKey:
    tte_band_id: str
    expiry_ms: int
    option_type: OptionType
    delta_bucket: str

    def __post_init__(self) -> None:
        if not self.tte_band_id or not self.delta_bucket:
            raise ValueError("Radar bucket strings must be non-empty")
        _non_negative_int(self.expiry_ms, "Radar bucket expiry_ms")

    def as_object(self) -> dict[str, object]:
        return {
            "tte_band_id": self.tte_band_id,
            "expiry_ms": self.expiry_ms,
            "option_type": self.option_type.value,
            "delta_bucket": self.delta_bucket,
        }

    @classmethod
    def from_object(cls, value: object) -> RadarBucketKey:
        raw = _mapping(value, "Radar bucket key")
        _exact_keys(
            raw,
            {"tte_band_id", "expiry_ms", "option_type", "delta_bucket"},
            "Radar bucket key",
        )
        return cls(
            tte_band_id=_non_empty_string(raw["tte_band_id"], "tte_band_id"),
            expiry_ms=_non_negative_int(raw["expiry_ms"], "expiry_ms"),
            option_type=OptionType(_non_empty_string(raw["option_type"], "option_type")),
            delta_bucket=_non_empty_string(raw["delta_bucket"], "delta_bucket"),
        )


@dataclass(frozen=True)
class UnsignedOiConcentrationDiagnostic:
    state: DiagnosticKnownness
    open_interest: Decimal | None
    option_gamma: Decimal | None
    unsigned_gamma_weight: Decimal | None
    bucket_total_unsigned_gamma_weight: Decimal | None
    concentration_share: Decimal | None
    missing_reason: str | None
    dealer_gamma_sign: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.dealer_gamma_sign != "UNKNOWN":
            raise ValueError("dealer_gamma_sign must remain UNKNOWN")
        values = (
            self.open_interest,
            self.option_gamma,
            self.unsigned_gamma_weight,
            self.bucket_total_unsigned_gamma_weight,
            self.concentration_share,
        )
        if self.state is DiagnosticKnownness.KNOWN:
            if any(value is None for value in values) or self.missing_reason is not None:
                raise ValueError("known OI diagnostic requires all values and no missing reason")
            if (
                self.concentration_share is not None
                and not Decimal(0) <= self.concentration_share <= 1
            ):
                raise ValueError("OI concentration share must be within [0, 1]")
        elif not self.missing_reason:
            raise ValueError("unknown OI diagnostic requires a missing reason")
        if self.option_gamma is not None and not self.option_gamma.is_finite():
            raise ValueError("OI diagnostic raw gamma must be finite")
        for value in (
            self.open_interest,
            self.unsigned_gamma_weight,
            self.bucket_total_unsigned_gamma_weight,
            self.concentration_share,
        ):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("OI diagnostic magnitudes must be finite and non-negative")

    def as_object(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "open_interest": _decimal_text(self.open_interest),
            "option_gamma": _decimal_text(self.option_gamma),
            "unsigned_gamma_weight": _decimal_text(self.unsigned_gamma_weight),
            "bucket_total_unsigned_gamma_weight": _decimal_text(
                self.bucket_total_unsigned_gamma_weight
            ),
            "concentration_share": _decimal_text(self.concentration_share),
            "missing_reason": self.missing_reason,
            "dealer_gamma_sign": self.dealer_gamma_sign,
        }

    @classmethod
    def from_object(cls, value: object) -> UnsignedOiConcentrationDiagnostic:
        raw = _mapping(value, "unsigned OI diagnostic")
        _exact_keys(
            raw,
            {
                "state",
                "open_interest",
                "option_gamma",
                "unsigned_gamma_weight",
                "bucket_total_unsigned_gamma_weight",
                "concentration_share",
                "missing_reason",
                "dealer_gamma_sign",
            },
            "unsigned OI diagnostic",
        )
        return cls(
            state=DiagnosticKnownness(_non_empty_string(raw["state"], "OI state")),
            open_interest=_optional_decimal(raw["open_interest"], "open_interest"),
            option_gamma=_optional_decimal(raw["option_gamma"], "option_gamma"),
            unsigned_gamma_weight=_optional_decimal(
                raw["unsigned_gamma_weight"], "unsigned_gamma_weight"
            ),
            bucket_total_unsigned_gamma_weight=_optional_decimal(
                raw["bucket_total_unsigned_gamma_weight"],
                "bucket_total_unsigned_gamma_weight",
            ),
            concentration_share=_optional_decimal(
                raw["concentration_share"], "concentration_share"
            ),
            missing_reason=_optional_string(raw["missing_reason"], "missing_reason"),
            dealer_gamma_sign=_non_empty_string(raw["dealer_gamma_sign"], "dealer_gamma_sign"),
        )


@dataclass(frozen=True)
class RadarSamplingMetadata:
    kind: SamplingKind
    causal_batch_identity: str
    designation_identity: str
    control_band: ScoreBand | None = None
    eligible_count: int | None = None
    stratum_count: int | None = None
    selected_ordinal: int | None = None
    inclusion_numerator: int | None = None
    inclusion_denominator: int | None = None
    low_eligible_count: int | None = None
    mid_eligible_count: int | None = None

    def __post_init__(self) -> None:
        _require_identity(self.causal_batch_identity, "causal_batch_identity")
        _require_identity(self.designation_identity, "designation_identity")
        control_values = (
            self.eligible_count,
            self.stratum_count,
            self.selected_ordinal,
            self.inclusion_numerator,
            self.inclusion_denominator,
            self.low_eligible_count,
            self.mid_eligible_count,
        )
        if self.kind is SamplingKind.CANONICAL_HIGH:
            if self.control_band is not None or any(value is not None for value in control_values):
                raise ValueError("canonical HIGH metadata cannot carry control sampling values")
            return
        if self.control_band not in {ScoreBand.LOW, ScoreBand.MID}:
            raise ValueError("control sampling requires a LOW or MID stratum")
        if any(value is None for value in control_values):
            raise ValueError("control sampling requires exact counts and rational probability")
        assert self.eligible_count is not None
        assert self.stratum_count is not None
        assert self.selected_ordinal is not None
        assert self.inclusion_numerator is not None
        assert self.inclusion_denominator is not None
        assert self.low_eligible_count is not None
        assert self.mid_eligible_count is not None
        if self.eligible_count <= 0 or self.stratum_count not in {1, 2}:
            raise ValueError("control sampling eligible and stratum counts are invalid")
        if not 0 <= self.selected_ordinal < self.eligible_count:
            raise ValueError("selected_ordinal must be zero-based within the selected stratum")
        if self.inclusion_numerator != 1 or self.inclusion_denominator != (
            self.eligible_count * self.stratum_count
        ):
            raise ValueError("control sampling probability must be 1/(eligible_count*strata)")
        expected_strata = int(self.low_eligible_count > 0) + int(self.mid_eligible_count > 0)
        if expected_strata != self.stratum_count:
            raise ValueError("control sampling stratum_count disagrees with exact band counts")
        selected_count = (
            self.low_eligible_count
            if self.control_band is ScoreBand.LOW
            else self.mid_eligible_count
        )
        if selected_count != self.eligible_count:
            raise ValueError("eligible_count must equal the selected stratum count")

    def as_object(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "causal_batch_identity": self.causal_batch_identity,
            "designation_identity": self.designation_identity,
            "control_band": self.control_band.value if self.control_band is not None else None,
            "eligible_count": self.eligible_count,
            "stratum_count": self.stratum_count,
            "selected_ordinal": self.selected_ordinal,
            "inclusion_numerator": self.inclusion_numerator,
            "inclusion_denominator": self.inclusion_denominator,
            "low_eligible_count": self.low_eligible_count,
            "mid_eligible_count": self.mid_eligible_count,
        }

    @classmethod
    def from_object(cls, value: object) -> RadarSamplingMetadata:
        raw = _mapping(value, "Radar sampling metadata")
        expected = {
            "kind",
            "causal_batch_identity",
            "designation_identity",
            "control_band",
            "eligible_count",
            "stratum_count",
            "selected_ordinal",
            "inclusion_numerator",
            "inclusion_denominator",
            "low_eligible_count",
            "mid_eligible_count",
        }
        _exact_keys(raw, expected, "Radar sampling metadata")
        control_band = raw["control_band"]
        return cls(
            kind=SamplingKind(_non_empty_string(raw["kind"], "sampling kind")),
            causal_batch_identity=_non_empty_string(
                raw["causal_batch_identity"], "causal_batch_identity"
            ),
            designation_identity=_non_empty_string(
                raw["designation_identity"], "designation_identity"
            ),
            control_band=(
                ScoreBand(_non_empty_string(control_band, "control_band"))
                if control_band is not None
                else None
            ),
            eligible_count=_optional_int(raw["eligible_count"], "eligible_count"),
            stratum_count=_optional_int(raw["stratum_count"], "stratum_count"),
            selected_ordinal=_optional_int(raw["selected_ordinal"], "selected_ordinal"),
            inclusion_numerator=_optional_int(raw["inclusion_numerator"], "inclusion_numerator"),
            inclusion_denominator=_optional_int(
                raw["inclusion_denominator"], "inclusion_denominator"
            ),
            low_eligible_count=_optional_int(raw["low_eligible_count"], "low_eligible_count"),
            mid_eligible_count=_optional_int(raw["mid_eligible_count"], "mid_eligible_count"),
        )


@dataclass(frozen=True)
class RadarScorePacket:
    policy_identity: str
    fact_boundary: Mapping[str, object]
    bucket_key: RadarBucketKey
    leader_instrument_name: str
    result: RadarScoreResult
    oi_diagnostic: UnsignedOiConcentrationDiagnostic
    sampling_metadata: RadarSamplingMetadata | None
    legacy_v1_threshold_pass: bool | None
    leader_coverage: LeaderCoverage = LeaderCoverage.COMPLETE
    packet_schema_version: int = 1

    def __post_init__(self) -> None:
        if self.packet_schema_version != 1:
            raise ValueError("Radar score packet schema must be exactly 1")
        _require_identity(self.policy_identity, "Radar score packet policy_identity")
        if not self.leader_instrument_name:
            raise ValueError("Radar score packet leader must be non-empty")
        object.__setattr__(self, "fact_boundary", _validated_fact_boundary(self.fact_boundary))
        if self.legacy_v1_threshold_pass is not None and not isinstance(
            self.legacy_v1_threshold_pass, bool
        ):
            raise ValueError("legacy_v1_threshold_pass must be boolean or null")

    def as_object(self) -> dict[str, object]:
        return {
            "packet_schema_version": self.packet_schema_version,
            "policy_identity": self.policy_identity,
            "fact_boundary": dict(self.fact_boundary),
            "bucket_key": self.bucket_key.as_object(),
            "leader_instrument_name": self.leader_instrument_name,
            "result": self.result.as_object(),
            "oi_diagnostic": self.oi_diagnostic.as_object(),
            "sampling_metadata": (
                self.sampling_metadata.as_object() if self.sampling_metadata is not None else None
            ),
            "legacy_v1_threshold_pass": self.legacy_v1_threshold_pass,
            "leader_coverage": self.leader_coverage.value,
        }

    @classmethod
    def from_object(cls, value: object) -> RadarScorePacket:
        raw = _mapping(value, "Radar score packet")
        expected = {
            "packet_schema_version",
            "policy_identity",
            "fact_boundary",
            "bucket_key",
            "leader_instrument_name",
            "result",
            "oi_diagnostic",
            "sampling_metadata",
            "legacy_v1_threshold_pass",
            "leader_coverage",
        }
        _exact_keys(raw, expected, "Radar score packet")
        boundary = _mapping(raw["fact_boundary"], "Radar score packet fact_boundary")
        sampling = raw["sampling_metadata"]
        legacy = raw["legacy_v1_threshold_pass"]
        if legacy is not None and not isinstance(legacy, bool):
            raise ValueError("legacy_v1_threshold_pass must be boolean or null")
        return cls(
            packet_schema_version=_non_negative_int(
                raw["packet_schema_version"], "packet_schema_version"
            ),
            policy_identity=_non_empty_string(raw["policy_identity"], "policy_identity"),
            fact_boundary=boundary,
            bucket_key=RadarBucketKey.from_object(raw["bucket_key"]),
            leader_instrument_name=_non_empty_string(
                raw["leader_instrument_name"], "leader_instrument_name"
            ),
            result=RadarScoreResult.from_object(raw["result"]),
            oi_diagnostic=UnsignedOiConcentrationDiagnostic.from_object(raw["oi_diagnostic"]),
            sampling_metadata=(
                RadarSamplingMetadata.from_object(sampling) if sampling is not None else None
            ),
            legacy_v1_threshold_pass=legacy,
            leader_coverage=LeaderCoverage(
                _non_empty_string(raw["leader_coverage"], "leader_coverage")
            ),
        )


def compute_radar_score(model: ScoreModel, inputs: RadarScoreInputs) -> RadarScoreResult:
    _require_interval_range(inputs.stressed_richness, Decimal(0), None, "stressed richness")
    _require_interval_range(
        inputs.stressed_executable_bid_iv,
        Decimal(0),
        None,
        "stressed executable-bid IV",
    )
    _require_interval_range(
        inputs.adverse_semivariance_share,
        Decimal(0),
        Decimal(1),
        "adverse semivariance share",
    )
    _require_interval_range(inputs.jump_share, Decimal(0), Decimal(1), "jump share")
    _require_interval_range(inputs.target_spread_ticks, Decimal(0), None, "target spread ticks")
    bid_count = _positive_int(inputs.bid_consumed_level_count, "bid consumed level count")
    ask_count = _positive_int(inputs.ask_consumed_level_count, "ask consumed level count")

    richness_normalized = _map_richness_interval(inputs.stressed_richness, model)
    factor_a = _known_factor(
        ScoreFactorName.PREMIUM_RICHNESS,
        (FactorRawInput("stressed_iv_rv_ratio", inputs.stressed_richness),),
        richness_normalized,
        richness_normalized,
    )

    stressed_iv_midpoint = _midpoint(inputs.stressed_executable_bid_iv)
    factor_s = _optional_signed_residual_factor(
        name=ScoreFactorName.SURFACE_RESIDUAL,
        left_name="stressed_executable_bid_iv_midpoint",
        left_value=stressed_iv_midpoint,
        right_name="local_same_type_mark_iv",
        right_value=inputs.local_same_type_mark_iv,
        saturation=model.surface_residual_saturation_iv_fraction,
        weight=model.surface_adjustment_weight,
        missing_reason="SURFACE_RESIDUAL_UNKNOWN",
    )
    factor_t = _optional_signed_residual_factor(
        name=ScoreFactorName.TERM_RESIDUAL,
        left_name="current_expiry_atm_mark_iv",
        left_value=inputs.current_expiry_atm_mark_iv,
        right_name="adjacent_expiry_atm_mark_iv",
        right_value=inputs.adjacent_expiry_atm_mark_iv,
        saturation=model.term_residual_saturation_iv_fraction,
        weight=model.term_adjustment_weight,
        missing_reason="TERM_RESIDUAL_UNKNOWN",
    )

    path_quality = _clamp_interval(
        DecimalInterval(
            Decimal(1)
            - model.path_adverse_semivariance_weight * inputs.adverse_semivariance_share.upper
            - model.path_jump_weight * inputs.jump_share.upper,
            Decimal(1)
            - model.path_adverse_semivariance_weight * inputs.adverse_semivariance_share.lower
            - model.path_jump_weight * inputs.jump_share.lower,
        ),
        Decimal(0),
        Decimal(1),
    )
    factor_d = _known_factor(
        ScoreFactorName.PATH_QUALITY,
        (
            FactorRawInput("adverse_semivariance_share", inputs.adverse_semivariance_share),
            FactorRawInput("jump_share", inputs.jump_share),
        ),
        path_quality,
        _scale_interval(path_quality, model.path_quality_weight),
    )

    spread_quality = _decreasing_quality_interval(
        inputs.target_spread_ticks,
        full=model.liquidity_spread_full_quality_ticks,
        zero=model.liquidity_spread_zero_quality_ticks,
    )
    total_levels = bid_count + ask_count
    depth_quality_scalar = _decreasing_quality(
        Decimal(total_levels),
        full=Decimal(model.liquidity_depth_full_quality_levels),
        zero=Decimal(model.liquidity_depth_zero_quality_levels),
    )
    depth_quality = DecimalInterval(depth_quality_scalar, depth_quality_scalar)
    liquidity_quality = _add_intervals(
        _scale_interval(spread_quality, model.liquidity_spread_weight),
        _scale_interval(depth_quality, model.liquidity_depth_weight),
    )
    factor_e = _known_factor(
        ScoreFactorName.LIQUIDITY_QUALITY,
        (
            FactorRawInput("target_spread_ticks", inputs.target_spread_ticks),
            FactorRawInput("bid_consumed_level_count", _point_interval(Decimal(bid_count))),
            FactorRawInput("ask_consumed_level_count", _point_interval(Decimal(ask_count))),
        ),
        liquidity_quality,
        _scale_interval(liquidity_quality, model.liquidity_quality_weight),
    )

    premium_evidence = richness_normalized
    for optional in (factor_s, factor_t):
        if optional.weighted_contribution is not None:
            premium_evidence = _add_intervals(premium_evidence, optional.weighted_contribution)
    premium_evidence = _clamp_interval(premium_evidence, Decimal(0), Decimal(1))
    risk_quality = _add_intervals(
        _known_contribution(factor_d),
        _known_contribution(factor_e),
    )
    risk_multiplier = _add_intervals(
        _point_interval(model.risk_floor),
        _scale_interval(risk_quality, model.risk_multiplier),
    )
    score = _scale_interval(
        _multiply_non_negative_intervals(premium_evidence, risk_multiplier),
        Decimal(100),
    )
    missing = tuple(factor.name for factor in (factor_s, factor_t) if factor.normalized is None)
    return RadarScoreResult(
        premium_evidence=premium_evidence,
        risk_quality=risk_quality,
        score=score,
        band=classify_score_band(score, model),
        coverage=ScoreCoverage.PARTIAL if missing else ScoreCoverage.COMPLETE,
        missing_factors=missing,
        factors=(factor_a, factor_s, factor_t, factor_d, factor_e),
    )


def classify_score_band(interval: DecimalInterval, model: ScoreModel) -> ScoreBand:
    _require_interval_range(interval, Decimal(0), Decimal(100), "score")
    if interval.lower >= model.activation_score_lower:
        return ScoreBand.HIGH
    if interval.upper < model.clear_score_upper:
        return ScoreBand.LOW
    if interval.lower >= model.clear_score_upper and interval.upper < model.activation_score_lower:
        return ScoreBand.MID
    return ScoreBand.REVIEW


def classify_score_observation(
    interval: DecimalInterval,
    model: ScoreModel,
) -> ScoreObservationSignal:
    _require_interval_range(interval, Decimal(0), Decimal(100), "score")
    if interval.lower >= model.activation_score_lower:
        return ScoreObservationSignal.ACTIVATE
    if interval.upper <= model.clear_score_upper:
        return ScoreObservationSignal.CLEAR
    return ScoreObservationSignal.NEUTRAL


def radar_score_observation_identity(
    *,
    core_identity: tuple[object, ...],
    result: RadarScoreResult,
) -> tuple[object, ...]:
    """Bind one core observation to the final A/S/T/D/E result used by the tracker.

    Surface and term inputs can change while the target instrument book remains unchanged.  The
    final result therefore has to participate in the distinct-observation identity instead of
    letting runtime count a core-only identity as a fresh V2 score observation.
    """
    if not core_identity:
        raise ValueError("score observation core identity must be non-empty")
    try:
        hash(core_identity)
    except TypeError as exc:
        raise ValueError("score observation core identity must be hashable") from exc
    canonical_result = json.dumps(
        result.as_object(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return ("RADAR_SCORE_OBSERVATION_V2", core_identity, canonical_result)


def legacy_v1_threshold_diagnostic(
    stressed_richness: DecimalInterval,
    *,
    threshold: Decimal = Decimal("1.2"),
) -> bool | None:
    _require_interval_range(stressed_richness, Decimal(0), None, "stressed richness")
    if stressed_richness.lower >= threshold:
        return True
    if stressed_richness.upper < threshold:
        return False
    return None


def build_radar_score_packet(
    *,
    policy_identity: str,
    fact_boundary: Mapping[str, object],
    bucket_key: RadarBucketKey,
    leader_instrument_name: str,
    result: RadarScoreResult,
    oi_diagnostic: UnsignedOiConcentrationDiagnostic,
    stressed_richness: DecimalInterval,
    leader_coverage: LeaderCoverage,
    sampling_metadata: RadarSamplingMetadata | None = None,
) -> RadarScorePacket:
    return RadarScorePacket(
        policy_identity=policy_identity,
        fact_boundary=fact_boundary,
        bucket_key=bucket_key,
        leader_instrument_name=leader_instrument_name,
        result=result,
        oi_diagnostic=oi_diagnostic,
        sampling_metadata=sampling_metadata,
        legacy_v1_threshold_pass=legacy_v1_threshold_diagnostic(stressed_richness),
        leader_coverage=leader_coverage,
    )


def validate_radar_score_packet(
    value: object,
    *,
    policy: RadarPolicy,
) -> RadarScorePacket:
    """Parse and policy-recompute one durable V2 packet.

    ``RadarScorePacket.from_object`` owns the detached value-shape boundary.  This policy-aware
    validator additionally proves that every derived factor contribution, aggregate, score, band,
    coverage value, and diagnostic agrees with the packet's frozen raw inputs.
    """
    packet = value if isinstance(value, RadarScorePacket) else RadarScorePacket.from_object(value)
    if packet.policy_identity != policy.identity:
        raise ValueError("Radar score packet policy identity mismatch")
    inputs = _score_inputs_from_frozen_factors(packet.result.factors)
    recomputed = compute_radar_score(policy.score_model, inputs)
    if recomputed != packet.result:
        raise ValueError("Radar score packet result disagrees with its policy and raw inputs")
    expected_legacy = legacy_v1_threshold_diagnostic(inputs.stressed_richness)
    if packet.legacy_v1_threshold_pass is not expected_legacy:
        raise ValueError("Radar score packet legacy diagnostic disagrees with raw richness")
    recomputed_oi = compute_unsigned_oi_concentration(
        open_interest=packet.oi_diagnostic.open_interest,
        option_gamma=packet.oi_diagnostic.option_gamma,
        bucket_total_unsigned_gamma_weight=(
            packet.oi_diagnostic.bucket_total_unsigned_gamma_weight
        ),
    )
    if recomputed_oi != packet.oi_diagnostic:
        raise ValueError("Radar score packet OI diagnostic disagrees with its raw inputs")
    return packet


def compute_unsigned_oi_concentration(
    *,
    open_interest: Decimal | None,
    option_gamma: Decimal | None,
    bucket_total_unsigned_gamma_weight: Decimal | None,
) -> UnsignedOiConcentrationDiagnostic:
    if open_interest is None or option_gamma is None:
        return UnsignedOiConcentrationDiagnostic(
            state=DiagnosticKnownness.UNKNOWN,
            open_interest=open_interest,
            option_gamma=option_gamma,
            unsigned_gamma_weight=None,
            bucket_total_unsigned_gamma_weight=bucket_total_unsigned_gamma_weight,
            concentration_share=None,
            missing_reason="OPTION_OI_OR_GAMMA_UNKNOWN",
        )
    if not open_interest.is_finite() or open_interest < 0 or not option_gamma.is_finite():
        raise ValueError("option OI must be non-negative and raw gamma must be finite")
    unsigned_weight = open_interest * abs(option_gamma)
    if (
        bucket_total_unsigned_gamma_weight is None
        or not bucket_total_unsigned_gamma_weight.is_finite()
        or bucket_total_unsigned_gamma_weight <= 0
    ):
        return UnsignedOiConcentrationDiagnostic(
            state=DiagnosticKnownness.UNKNOWN,
            open_interest=open_interest,
            option_gamma=option_gamma,
            unsigned_gamma_weight=unsigned_weight,
            bucket_total_unsigned_gamma_weight=bucket_total_unsigned_gamma_weight,
            concentration_share=None,
            missing_reason="BUCKET_UNSIGNED_GAMMA_WEIGHT_UNKNOWN",
        )
    if unsigned_weight > bucket_total_unsigned_gamma_weight:
        raise ValueError("instrument unsigned gamma weight exceeds its bucket total")
    return UnsignedOiConcentrationDiagnostic(
        state=DiagnosticKnownness.KNOWN,
        open_interest=open_interest,
        option_gamma=option_gamma,
        unsigned_gamma_weight=unsigned_weight,
        bucket_total_unsigned_gamma_weight=bucket_total_unsigned_gamma_weight,
        concentration_share=unsigned_weight / bucket_total_unsigned_gamma_weight,
        missing_reason=None,
    )


def _score_inputs_from_frozen_factors(
    factors: tuple[ScoreFactor, ...],
) -> RadarScoreInputs:
    by_name = {factor.name: factor for factor in factors}
    factor_a = by_name[ScoreFactorName.PREMIUM_RICHNESS]
    factor_s = by_name[ScoreFactorName.SURFACE_RESIDUAL]
    factor_t = by_name[ScoreFactorName.TERM_RESIDUAL]
    factor_d = by_name[ScoreFactorName.PATH_QUALITY]
    factor_e = by_name[ScoreFactorName.LIQUIDITY_QUALITY]
    _require_raw_input_layout(factor_a, ("stressed_iv_rv_ratio",))
    _require_raw_input_layout(
        factor_s,
        ("stressed_executable_bid_iv_midpoint", "local_same_type_mark_iv"),
    )
    _require_raw_input_layout(
        factor_t,
        ("current_expiry_atm_mark_iv", "adjacent_expiry_atm_mark_iv"),
    )
    _require_raw_input_layout(
        factor_d,
        ("adverse_semivariance_share", "jump_share"),
    )
    _require_raw_input_layout(
        factor_e,
        (
            "target_spread_ticks",
            "bid_consumed_level_count",
            "ask_consumed_level_count",
        ),
    )
    stressed_richness = _required_raw_interval(factor_a.raw_inputs[0])
    stressed_iv_midpoint = _required_raw_point(factor_s.raw_inputs[0])
    return RadarScoreInputs(
        stressed_richness=stressed_richness,
        stressed_executable_bid_iv=DecimalInterval(
            stressed_iv_midpoint,
            stressed_iv_midpoint,
        ),
        local_same_type_mark_iv=_optional_raw_point(factor_s.raw_inputs[1]),
        current_expiry_atm_mark_iv=_optional_raw_point(factor_t.raw_inputs[0]),
        adjacent_expiry_atm_mark_iv=_optional_raw_point(factor_t.raw_inputs[1]),
        adverse_semivariance_share=_required_raw_interval(factor_d.raw_inputs[0]),
        jump_share=_required_raw_interval(factor_d.raw_inputs[1]),
        target_spread_ticks=_required_raw_interval(factor_e.raw_inputs[0]),
        bid_consumed_level_count=_required_raw_positive_int(factor_e.raw_inputs[1]),
        ask_consumed_level_count=_required_raw_positive_int(factor_e.raw_inputs[2]),
    )


def _require_raw_input_layout(
    factor: ScoreFactor,
    names: tuple[str, ...],
) -> None:
    if tuple(raw.name for raw in factor.raw_inputs) != names:
        raise ValueError(f"Radar score factor {factor.name.value} raw-input layout is invalid")


def _required_raw_interval(raw: FactorRawInput) -> DecimalInterval:
    if raw.interval is None:
        raise ValueError(f"Radar score raw input {raw.name} is required")
    return raw.interval


def _optional_raw_point(raw: FactorRawInput) -> Decimal | None:
    if raw.interval is None:
        return None
    if raw.interval.lower != raw.interval.upper:
        raise ValueError(f"Radar score raw input {raw.name} must be a point")
    return raw.interval.lower


def _required_raw_point(raw: FactorRawInput) -> Decimal:
    value = _optional_raw_point(raw)
    if value is None:
        raise ValueError(f"Radar score raw input {raw.name} is required")
    return value


def _required_raw_positive_int(raw: FactorRawInput) -> int:
    value = _required_raw_point(raw)
    if value != value.to_integral_value() or value <= 0:
        raise ValueError(f"Radar score raw input {raw.name} must be a positive integer")
    return int(value)


def _map_richness_interval(interval: DecimalInterval, model: ScoreModel) -> DecimalInterval:
    return DecimalInterval(
        _map_richness_value(interval.lower, model),
        _map_richness_value(interval.upper, model),
    )


def _map_richness_value(value: Decimal, model: ScoreModel) -> Decimal:
    knots = model.richness_knots
    if value <= knots[0].ratio:
        return knots[0].normalized_value
    if value >= knots[-1].ratio:
        return knots[-1].normalized_value
    for left, right in pairwise(knots):
        if value <= right.ratio:
            fraction = (value - left.ratio) / (right.ratio - left.ratio)
            return left.normalized_value + fraction * (
                right.normalized_value - left.normalized_value
            )
    raise RuntimeError("richness knots did not cover a finite value")


def _optional_signed_residual_factor(
    *,
    name: ScoreFactorName,
    left_name: str,
    left_value: Decimal | None,
    right_name: str,
    right_value: Decimal | None,
    saturation: Decimal,
    weight: Decimal,
    missing_reason: str,
) -> ScoreFactor:
    raw_inputs = (
        FactorRawInput(left_name, _optional_point_interval(left_value)),
        FactorRawInput(right_name, _optional_point_interval(right_value)),
    )
    if left_value is None or right_value is None:
        return ScoreFactor(
            name=name,
            raw_inputs=raw_inputs,
            normalized=None,
            weighted_contribution=None,
            unknown_reason=missing_reason,
        )
    for value, field in ((left_value, left_name), (right_value, right_name)):
        if not value.is_finite() or value < 0:
            raise ScoreUnavailable(f"{field} must be finite and non-negative")
    residual = left_value - right_value
    normalized_value = min(Decimal(1), max(Decimal(-1), residual / saturation))
    normalized = _point_interval(normalized_value)
    return _known_factor(name, raw_inputs, normalized, _scale_interval(normalized, weight))


def _known_factor(
    name: ScoreFactorName,
    raw_inputs: tuple[FactorRawInput, ...],
    normalized: DecimalInterval,
    weighted_contribution: DecimalInterval,
) -> ScoreFactor:
    return ScoreFactor(
        name=name,
        raw_inputs=raw_inputs,
        normalized=normalized,
        weighted_contribution=weighted_contribution,
    )


def _known_contribution(factor: ScoreFactor) -> DecimalInterval:
    if factor.weighted_contribution is None:
        raise RuntimeError(f"required score factor {factor.name.value} is unknown")
    return factor.weighted_contribution


def _decreasing_quality_interval(
    interval: DecimalInterval,
    *,
    full: Decimal,
    zero: Decimal,
) -> DecimalInterval:
    return DecimalInterval(
        _decreasing_quality(interval.upper, full=full, zero=zero),
        _decreasing_quality(interval.lower, full=full, zero=zero),
    )


def _decreasing_quality(value: Decimal, *, full: Decimal, zero: Decimal) -> Decimal:
    if value <= full:
        return Decimal(1)
    if value >= zero:
        return Decimal(0)
    return (zero - value) / (zero - full)


def _midpoint(interval: DecimalInterval) -> Decimal:
    return (interval.lower + interval.upper) / Decimal(2)


def _add_intervals(first: DecimalInterval, second: DecimalInterval) -> DecimalInterval:
    return DecimalInterval(first.lower + second.lower, first.upper + second.upper)


def _scale_interval(interval: DecimalInterval, factor: Decimal) -> DecimalInterval:
    if factor >= 0:
        return DecimalInterval(interval.lower * factor, interval.upper * factor)
    return DecimalInterval(interval.upper * factor, interval.lower * factor)


def _multiply_non_negative_intervals(
    first: DecimalInterval,
    second: DecimalInterval,
) -> DecimalInterval:
    if first.lower < 0 or second.lower < 0:
        raise ValueError("non-negative interval multiplication received a negative bound")
    return DecimalInterval(first.lower * second.lower, first.upper * second.upper)


def _clamp_interval(
    interval: DecimalInterval,
    lower: Decimal,
    upper: Decimal,
) -> DecimalInterval:
    return DecimalInterval(
        min(upper, max(lower, interval.lower)),
        min(upper, max(lower, interval.upper)),
    )


def _point_interval(value: Decimal) -> DecimalInterval:
    return DecimalInterval(value, value)


def _optional_point_interval(value: Decimal | None) -> DecimalInterval | None:
    return None if value is None else _point_interval(value)


def _require_interval_range(
    interval: DecimalInterval,
    lower: Decimal | None,
    upper: Decimal | None,
    field: str,
) -> None:
    _require_finite_interval(interval, field)
    if lower is not None and interval.lower < lower:
        raise ScoreUnavailable(f"{field} is below its valid range")
    if upper is not None and interval.upper > upper:
        raise ScoreUnavailable(f"{field} is above its valid range")


def _require_finite_interval(interval: DecimalInterval | None, field: str) -> None:
    if interval is None or not interval.lower.is_finite() or not interval.upper.is_finite():
        raise ValueError(f"{field} interval must be finite")


def _interval_object(interval: DecimalInterval | None) -> dict[str, str] | None:
    if interval is None:
        return None
    return {
        "lower": _required_decimal_text(interval.lower),
        "upper": _required_decimal_text(interval.upper),
    }


def _required_interval(value: object) -> DecimalInterval:
    interval = _interval_from_object(value, allow_none=False)
    if interval is None:
        raise ValueError("interval is required")
    return interval


def _interval_from_object(value: object, *, allow_none: bool) -> DecimalInterval | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError("interval is required")
    raw = _mapping(value, "interval")
    _exact_keys(raw, {"lower", "upper"}, "interval")
    return DecimalInterval(
        _decimal(raw["lower"], "interval.lower"),
        _decimal(raw["upper"], "interval.upper"),
    )


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("Decimal must be finite")
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _required_decimal_text(value: Decimal) -> str:
    text = _decimal_text(value)
    if text is None:
        raise RuntimeError("required Decimal text is missing")
    return text


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _validated_fact_boundary(value: object) -> dict[str, object]:
    raw = _mapping(value, "Radar score packet fact_boundary")
    expected = {
        "code_identity",
        "runtime_identity",
        "session_epoch",
        "ingress_seq",
        "received_monotonic_ms",
        "causal_seq",
    }
    _exact_keys(raw, expected, "Radar score packet fact_boundary")
    code_identity = raw["code_identity"]
    if not isinstance(code_identity, str) or CODE_IDENTITY_PATTERN.fullmatch(code_identity) is None:
        raise ValueError("fact_boundary.code_identity must be one lowercase 40-hex commit")
    return {
        "code_identity": code_identity,
        "runtime_identity": _require_identity(
            raw["runtime_identity"], "fact_boundary.runtime_identity"
        ),
        "session_epoch": _non_negative_int(raw["session_epoch"], "fact_boundary.session_epoch"),
        "ingress_seq": _non_negative_int(raw["ingress_seq"], "fact_boundary.ingress_seq"),
        "received_monotonic_ms": _non_negative_int(
            raw["received_monotonic_ms"], "fact_boundary.received_monotonic_ms"
        ),
        "causal_seq": _non_negative_int(raw["causal_seq"], "fact_boundary.causal_seq"),
    }


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{field} requires exact keys")


def _decimal(value: object, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} must be a Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a Decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _optional_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else _decimal(value, field)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    parsed = _non_negative_int(value, field)
    if parsed == 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _optional_int(value: object, field: str) -> int | None:
    return None if value is None else _non_negative_int(value, field)


def _require_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be sha256:<64 lowercase hex>")
    return value


__all__ = [
    "DiagnosticKnownness",
    "FactorRawInput",
    "LeaderCoverage",
    "RadarBucketKey",
    "RadarSamplingMetadata",
    "RadarScoreInputs",
    "RadarScorePacket",
    "RadarScoreResult",
    "SamplingKind",
    "ScoreBand",
    "ScoreCoverage",
    "ScoreFactor",
    "ScoreFactorName",
    "ScoreObservationSignal",
    "ScoreUnavailable",
    "UnsignedOiConcentrationDiagnostic",
    "build_radar_score_packet",
    "classify_score_band",
    "classify_score_observation",
    "compute_radar_score",
    "compute_unsigned_oi_concentration",
    "legacy_v1_threshold_diagnostic",
    "validate_radar_score_packet",
]

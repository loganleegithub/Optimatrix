from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
from market_monitor import TimeInterval
from options_domain import OptionType
from short_vol_radar.baseline import PI_OVER_TWO, compute_baseline
from short_vol_radar.black import DecimalInterval
from short_vol_radar.bucket import (
    BucketConfirmationResetReason,
    BucketEpisodeEndReason,
    BucketEpisodeState,
    BucketLeaderCandidate,
    LeaderCoverage,
    RadarBucketEpisodeTracker,
    radar_bucket_episode_identity,
    select_bucket_leader,
)
from short_vol_radar.policy import RadarPolicy, ScoreModel, digest_policy_bytes, load_policy_bytes
from short_vol_radar.score import (
    DiagnosticKnownness,
    RadarBucketKey,
    RadarSamplingMetadata,
    RadarScoreInputs,
    RadarScorePacket,
    SamplingKind,
    ScoreBand,
    ScoreCoverage,
    ScoreFactorName,
    ScoreObservationSignal,
    ScoreUnavailable,
    classify_score_observation,
    compute_radar_score,
    compute_unsigned_oi_concentration,
    legacy_v1_threshold_diagnostic,
    radar_score_observation_identity,
    validate_radar_score_packet,
)

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = "sha256:" + "1" * 64


def _model() -> ScoreModel:
    exact = (ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json").read_bytes()
    return load_policy_bytes(exact, digest_policy_bytes(exact)).score_model


def _policy() -> RadarPolicy:
    exact = (ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json").read_bytes()
    return load_policy_bytes(exact, digest_policy_bytes(exact))


def _interval(lower: str, upper: str | None = None) -> DecimalInterval:
    return DecimalInterval(Decimal(lower), Decimal(lower if upper is None else upper))


def _boundary(causal_seq: int = 1) -> dict[str, object]:
    return {
        "code_identity": "a" * 40,
        "runtime_identity": "sha256:" + "4" * 64,
        "session_epoch": 1,
        "ingress_seq": causal_seq,
        "received_monotonic_ms": causal_seq * 1_000,
        "causal_seq": causal_seq,
    }


def _inputs(**overrides: object) -> RadarScoreInputs:
    values: dict[str, object] = {
        "stressed_richness": _interval("1.2"),
        "stressed_executable_bid_iv": _interval("0.30", "0.32"),
        "local_same_type_mark_iv": Decimal("0.30"),
        "surface_source_skew_ms": 0,
        "current_expiry_atm_mark_iv": Decimal("0.32"),
        "adjacent_expiry_atm_mark_iv": Decimal("0.31"),
        "term_source_skew_ms": 0,
        "adverse_semivariance_share": _interval("0.5"),
        "jump_share": _interval("0.1"),
        "target_spread_ticks": _interval("5"),
        "bid_consumed_level_count": 1,
        "ask_consumed_level_count": 1,
    }
    values.update(overrides)
    return RadarScoreInputs(**values)  # type: ignore[arg-type]


def test_v2_launch_formula_uses_transparent_a_s_t_d_e_normalization() -> None:
    result = compute_radar_score(_model(), _inputs())
    factors = {factor.name: factor for factor in result.factors}

    assert factors[ScoreFactorName.PREMIUM_RICHNESS].normalized == _interval("0.8")
    assert factors[ScoreFactorName.SURFACE_RESIDUAL].normalized == _interval("0.1")
    assert factors[ScoreFactorName.SURFACE_RESIDUAL].weighted_contribution == _interval("0.01")
    assert factors[ScoreFactorName.TERM_RESIDUAL].normalized == _interval("0.1")
    assert factors[ScoreFactorName.TERM_RESIDUAL].weighted_contribution == _interval("0.005")
    assert factors[ScoreFactorName.PATH_QUALITY].normalized == _interval("0.70")
    assert factors[ScoreFactorName.LIQUIDITY_QUALITY].normalized == _interval(
        "0.6888888888888888888888888889"
    )
    assert result.premium_evidence == _interval("0.815")
    assert result.risk_quality.lower == result.risk_quality.upper
    expected = (
        Decimal(100)
        * result.premium_evidence.lower
        * (Decimal("0.4") + Decimal("0.6") * result.risk_quality.lower)
    )
    assert result.score == _interval(str(expected))
    assert result.band is ScoreBand.HIGH
    assert result.coverage is ScoreCoverage.COMPLETE


def test_bipower_variation_applies_finite_sample_correction_without_mechanical_jump() -> None:
    step = Decimal("0.01")
    prices = tuple((step * Decimal(index)).exp() for index in range(7))
    result = compute_baseline(
        sampled_prices=prices,
        lookbacks=(30,),
        return_interval_minutes=5,
        annualized_variance_floor=Decimal("0.000001"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(60),
    )
    diagnostic = result.diagnostics_for(30)
    returns = tuple(later.ln() - earlier.ln() for earlier, later in pairwise(prices))
    uncorrected = PI_OVER_TWO * sum(
        (abs(first) * abs(second) for first, second in pairwise(returns)),
        Decimal(0),
    )
    expected_corrected_rate = uncorrected * Decimal(6) / Decimal(5) / Decimal(30)
    assert abs(diagnostic.bipower_variation_rate_per_minute - expected_corrected_rate) < Decimal(
        "1e-30"
    )
    assert diagnostic.jump_variation_rate_per_minute == 0
    assert diagnostic.jump_share == 0


@pytest.mark.parametrize(
    ("ratio", "normalized"),
    [
        ("0.9", "0"),
        ("1", "0"),
        ("1.1", "0.4"),
        ("1.2", "0.8"),
        ("1.25", "0.9"),
        ("1.3", "1"),
        ("2", "1"),
    ],
)
def test_richness_anchor_uses_policy_piecewise_knots(ratio: str, normalized: str) -> None:
    result = compute_radar_score(_model(), _inputs(stressed_richness=_interval(ratio)))
    assert result.factors[0].normalized == _interval(normalized)


def test_optional_surface_and_term_are_missing_not_fabricated_neutral_values() -> None:
    result = compute_radar_score(
        _model(),
        _inputs(
            local_same_type_mark_iv=None,
            current_expiry_atm_mark_iv=None,
            adjacent_expiry_atm_mark_iv=None,
        ),
    )

    assert result.coverage is ScoreCoverage.PARTIAL
    assert result.missing_factors == (
        ScoreFactorName.SURFACE_RESIDUAL,
        ScoreFactorName.TERM_RESIDUAL,
    )
    for factor in result.factors[1:3]:
        assert factor.normalized is None
        assert factor.weighted_contribution is None
        assert factor.unknown_reason is not None
    assert result.premium_evidence == _interval("0.8")


@pytest.mark.parametrize(
    ("surface_skew_ms", "expected_coverage", "expected_reason"),
    [
        (6_000, ScoreCoverage.COMPLETE, None),
        (6_001, ScoreCoverage.PARTIAL, "SURFACE_SOURCE_SKEW_EXCEEDED"),
        (None, ScoreCoverage.PARTIAL, "SURFACE_SOURCE_TIME_UNKNOWN"),
    ],
)
def test_surface_factor_enforces_policy_source_skew_without_blocking_core_score(
    surface_skew_ms: int | None,
    expected_coverage: ScoreCoverage,
    expected_reason: str | None,
) -> None:
    result = compute_radar_score(
        _model(),
        _inputs(surface_source_skew_ms=surface_skew_ms),
    )
    surface = next(
        factor for factor in result.factors if factor.name is ScoreFactorName.SURFACE_RESIDUAL
    )

    assert result.coverage is expected_coverage
    assert surface.unknown_reason == expected_reason
    if expected_reason is None:
        assert surface.weighted_contribution is not None
    else:
        assert surface.weighted_contribution is None
        assert result.score is not None


@pytest.mark.parametrize(
    ("term_skew_ms", "expected_reason"),
    [
        (6_000, None),
        (6_001, "TERM_SOURCE_SKEW_EXCEEDED"),
        (None, "TERM_SOURCE_TIME_UNKNOWN"),
    ],
)
def test_term_factor_enforces_same_policy_source_skew_boundary(
    term_skew_ms: int | None,
    expected_reason: str | None,
) -> None:
    result = compute_radar_score(_model(), _inputs(term_source_skew_ms=term_skew_ms))
    term = next(factor for factor in result.factors if factor.name is ScoreFactorName.TERM_RESIDUAL)

    assert term.unknown_reason == expected_reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"adverse_semivariance_share": _interval("0", "1.1")},
        {"jump_share": _interval("-0.1", "0")},
        {"target_spread_ticks": _interval("-1", "0")},
        {"bid_consumed_level_count": 0},
    ],
)
def test_missing_or_invalid_core_path_liquidity_inputs_do_not_produce_score(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((ScoreUnavailable, ValueError)):
        compute_radar_score(_model(), _inputs(**overrides))


def test_score_interval_crossing_threshold_is_review_not_unknown() -> None:
    model = _model()
    result = compute_radar_score(
        model,
        _inputs(stressed_richness=_interval("1.15", "1.25")),
    )
    assert result.band is ScoreBand.REVIEW
    assert classify_score_observation(result.score, model) is ScoreObservationSignal.NEUTRAL

    assert classify_score_observation(_interval("65", "70"), model) is (
        ScoreObservationSignal.ACTIVATE
    )
    assert classify_score_observation(_interval("45", "50"), model) is (
        ScoreObservationSignal.CLEAR
    )
    assert classify_score_observation(_interval("49", "51"), model) is (
        ScoreObservationSignal.NEUTRAL
    )


def test_unsigned_oi_gamma_diagnostic_never_infers_dealer_sign() -> None:
    known = compute_unsigned_oi_concentration(
        open_interest=Decimal(100),
        option_gamma=Decimal("-0.02"),
        bucket_total_unsigned_gamma_weight=Decimal(5),
    )
    assert known.state is DiagnosticKnownness.KNOWN
    assert known.option_gamma == Decimal("-0.02")
    assert known.unsigned_gamma_weight == Decimal(2)
    assert known.concentration_share == Decimal("0.4")
    assert known.dealer_gamma_sign == "UNKNOWN"

    unknown = compute_unsigned_oi_concentration(
        open_interest=Decimal(100),
        option_gamma=None,
        bucket_total_unsigned_gamma_weight=None,
    )
    assert unknown.state is DiagnosticKnownness.UNKNOWN
    assert unknown.concentration_share is None
    assert unknown.dealer_gamma_sign == "UNKNOWN"


def test_packet_round_trip_is_one_typed_schema_for_selection_and_refresh() -> None:
    result = compute_radar_score(_model(), _inputs())
    oi = compute_unsigned_oi_concentration(
        open_interest=Decimal(100),
        option_gamma=Decimal("0.02"),
        bucket_total_unsigned_gamma_weight=Decimal(5),
    )
    packet = RadarScorePacket(
        policy_identity=IDENTITY,
        fact_boundary=_boundary(7),
        bucket_key=RadarBucketKey(
            "ultra-short-45m-to-6h",
            10_000,
            OptionType.CALL,
            "TAIL_05_15",
        ),
        leader_instrument_name="BTC-TEST-C",
        result=result,
        oi_diagnostic=oi,
        sampling_metadata=None,
        legacy_v1_threshold_pass=legacy_v1_threshold_diagnostic(_interval("1.2")),
    )
    sampling = RadarSamplingMetadata(
        kind=SamplingKind.CANONICAL_HIGH,
        causal_batch_identity=IDENTITY,
        designation_identity="sha256:" + "2" * 64,
    )
    frozen = replace(packet, sampling_metadata=sampling)
    restored = RadarScorePacket.from_object(frozen.as_object())

    assert restored == frozen
    assert restored.as_object() == frozen.as_object()
    assert restored.legacy_v1_threshold_pass is True
    original_boundary = _boundary(7)
    detached = replace(packet, fact_boundary=original_boundary)
    original_boundary["causal_seq"] = 8
    assert detached.fact_boundary == _boundary(7)


@pytest.mark.parametrize(
    "tampered_boundary",
    [
        {**_boundary(), "unexpected": 1},
        {**_boundary(), "session_epoch": -1},
        {**_boundary(), "causal_seq": -1},
        {**_boundary(), "ingress_seq": True},
        {**_boundary(), "code_identity": "A" * 40},
        {**_boundary(), "runtime_identity": "sha256:bad"},
    ],
)
def test_packet_rejects_tampered_fact_boundary_on_construct_and_restore(
    tampered_boundary: dict[str, object],
) -> None:
    packet = _packet()
    with pytest.raises(ValueError):
        replace(packet, fact_boundary=tampered_boundary)

    payload = packet.as_object()
    payload["fact_boundary"] = tampered_boundary
    with pytest.raises(ValueError):
        RadarScorePacket.from_object(payload)


def test_score_packet_rejects_inconsistent_missing_factor_knownness_and_ranges() -> None:
    result = compute_radar_score(_model(), _inputs())
    payload = result.as_object()
    payload["missing_factors"] = [ScoreFactorName.SURFACE_RESIDUAL.value]
    with pytest.raises(ValueError, match="knownness"):
        type(result).from_object(payload)

    with pytest.raises(ValueError, match="score"):
        replace(result, score=_interval("101"))


def test_score_observation_identity_changes_when_optional_score_evidence_changes() -> None:
    core_identity = ("book", Decimal("1.2"), ("baseline", 7))
    first = compute_radar_score(_model(), _inputs())
    same = compute_radar_score(_model(), _inputs())
    changed = compute_radar_score(
        _model(),
        _inputs(local_same_type_mark_iv=Decimal("0.31")),
    )

    assert radar_score_observation_identity(
        core_identity=core_identity, result=first
    ) == radar_score_observation_identity(core_identity=core_identity, result=same)
    assert radar_score_observation_identity(
        core_identity=core_identity, result=first
    ) != radar_score_observation_identity(core_identity=core_identity, result=changed)


def test_control_sampling_metadata_freezes_actual_stratified_probability() -> None:
    metadata = RadarSamplingMetadata(
        kind=SamplingKind.DETERMINISTIC_BAND_CONTROL,
        causal_batch_identity=IDENTITY,
        designation_identity="sha256:" + "3" * 64,
        control_band=ScoreBand.MID,
        eligible_count=3,
        stratum_count=2,
        selected_ordinal=2,
        inclusion_numerator=1,
        inclusion_denominator=6,
        low_eligible_count=4,
        mid_eligible_count=3,
    )
    assert RadarSamplingMetadata.from_object(metadata.as_object()) == metadata

    with pytest.raises(ValueError, match="probability"):
        replace(metadata, inclusion_denominator=3)


def _packet(
    *, instrument: str = "BTC-TEST-C", band: ScoreBand = ScoreBand.HIGH
) -> RadarScorePacket:
    result = compute_radar_score(_model(), _inputs())
    if band is not result.band:
        score = {
            ScoreBand.LOW: _interval("40"),
            ScoreBand.MID: _interval("55"),
            ScoreBand.REVIEW: _interval("49", "51"),
        }[band]
        result = replace(result, score=score, band=band)
    return RadarScorePacket(
        policy_identity=IDENTITY,
        fact_boundary=_boundary(),
        bucket_key=RadarBucketKey("ultra-short-45m-to-6h", 10_000, OptionType.CALL, "TAIL_05_15"),
        leader_instrument_name=instrument,
        result=result,
        oi_diagnostic=compute_unsigned_oi_concentration(
            open_interest=None,
            option_gamma=None,
            bucket_total_unsigned_gamma_weight=None,
        ),
        sampling_metadata=None,
        legacy_v1_threshold_pass=True,
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "score_vs_band",
        "band_vs_score",
        "aggregate_vs_factors",
        "factor_contribution",
        "surface_source_skew",
        "legacy_diagnostic",
        "oi_diagnostic",
    ),
)
def test_policy_aware_packet_validator_rejects_derived_truth_tampering(
    tamper: str,
) -> None:
    policy = _policy()
    packet = replace(_packet(), policy_identity=policy.identity)
    assert validate_radar_score_packet(packet.as_object(), policy=policy) == packet
    value = deepcopy(packet.as_object())
    result = value["result"]
    assert isinstance(result, dict)
    if tamper == "score_vs_band":
        result["score"] = {"lower": "1", "upper": "1"}
    elif tamper == "band_vs_score":
        result["band"] = ScoreBand.LOW.value
    elif tamper == "aggregate_vs_factors":
        result["premium_evidence"] = {"lower": "0.1", "upper": "0.1"}
        result["risk_quality"] = {"lower": "0.1", "upper": "0.1"}
    elif tamper == "factor_contribution":
        factors = result["factors"]
        assert isinstance(factors, list) and isinstance(factors[0], dict)
        factors[0]["weighted_contribution"] = {"lower": "0.1", "upper": "0.1"}
    elif tamper == "surface_source_skew":
        factors = result["factors"]
        assert isinstance(factors, list) and isinstance(factors[1], dict)
        raw_inputs = factors[1]["raw_inputs"]
        assert isinstance(raw_inputs, list) and isinstance(raw_inputs[2], dict)
        raw_inputs[2]["interval"] = {"lower": "6001", "upper": "6001"}
    elif tamper == "legacy_diagnostic":
        value["legacy_v1_threshold_pass"] = False
    elif tamper == "oi_diagnostic":
        diagnostic = value["oi_diagnostic"]
        assert isinstance(diagnostic, dict)
        diagnostic["missing_reason"] = "TAMPERED_UNKNOWN_REASON"
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(tamper)

    with pytest.raises(ValueError, match="disagrees"):
        validate_radar_score_packet(value, policy=policy)


def test_packet_serialization_preserves_high_precision_factor_inputs() -> None:
    policy = _policy()
    adverse_share = Decimal("0.72208817542761025957486936731234567890123456789012")
    result = compute_radar_score(
        policy.score_model,
        _inputs(adverse_semivariance_share=_interval(str(adverse_share))),
    )
    packet = replace(
        _packet(),
        policy_identity=policy.identity,
        result=result,
    )

    serialized = packet.as_object()
    restored = validate_radar_score_packet(serialized, policy=policy)

    assert restored == packet
    serialized_result = serialized["result"]
    assert isinstance(serialized_result, dict)
    factors = serialized_result["factors"]
    assert isinstance(factors, list)
    factor_d = factors[3]
    assert isinstance(factor_d, dict)
    raw_inputs = factor_d["raw_inputs"]
    assert isinstance(raw_inputs, list)
    raw_adverse = raw_inputs[0]
    assert isinstance(raw_adverse, dict)
    adverse_interval = raw_adverse["interval"]
    assert isinstance(adverse_interval, dict)
    assert adverse_interval["lower"] == str(adverse_share)


def _leader_candidate(
    *,
    instrument: str,
    score_lower: str,
    richness_lower: str,
    spread_ticks: str,
    levels: int,
    strike: str,
) -> BucketLeaderCandidate:
    result = replace(
        _packet(instrument=instrument).result,
        score=_interval(score_lower),
    )
    return BucketLeaderCandidate(
        bucket_key=_packet().bucket_key,
        instrument_name=instrument,
        strike=Decimal(strike),
        score_result=result,
        stressed_richness=_interval(richness_lower),
        target_spread_ticks=Decimal(spread_ticks),
        total_consumed_level_count=levels,
    )


def test_bucket_leader_uses_one_radar_owned_lexicographic_rank_and_freeze() -> None:
    high_score = _leader_candidate(
        instrument="HIGH",
        score_lower="70",
        richness_lower="1.2",
        spread_ticks="8",
        levels=4,
        strike="110",
    )
    liquid = _leader_candidate(
        instrument="LIQUID",
        score_lower="69",
        richness_lower="1.4",
        spread_ticks="1",
        levels=2,
        strike="105",
    )
    unknown = BucketLeaderCandidate(
        bucket_key=high_score.bucket_key,
        instrument_name="UNKNOWN",
        strike=Decimal(120),
        score_result=None,
        stressed_richness=None,
        target_spread_ticks=None,
        total_consumed_level_count=None,
        unknown_reason="CORE_UNKNOWN",
    )

    selected = select_bucket_leader((liquid, unknown, high_score))
    assert selected.leader == high_score
    assert selected.coverage is LeaderCoverage.DEGRADED
    assert selected.unknown_candidate_count == 1

    frozen = select_bucket_leader((liquid, unknown, high_score), frozen_instrument_name="LIQUID")
    assert frozen.leader == liquid


def test_bucket_tracker_counts_distinct_separated_observations_and_freezes_episode() -> None:
    packet = _packet(band=ScoreBand.MID)
    policy = _policy()
    rule = policy.tte_bands[1].option_rules[OptionType.CALL]
    tracker = RadarBucketEpisodeTracker(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=packet.bucket_key,
        score_model=policy.score_model,
        clue_eligible=True,
    )

    first = tracker.observe(
        packet=packet,
        observation_identity=("book", 1),
        causal_seq=1,
        trusted_time=TimeInterval(0, 0),
        rule=rule,
    )
    duplicate = tracker.observe(
        packet=packet,
        observation_identity=("book", 1),
        causal_seq=2,
        trusted_time=TimeInterval(60_000, 60_000),
        rule=rule,
    )
    second = tracker.observe(
        packet=packet,
        observation_identity=("book", 2),
        causal_seq=3,
        trusted_time=TimeInterval(60_000, 60_000),
        rule=rule,
    )
    confirmed = tracker.observe(
        packet=packet,
        observation_identity=("book", 3),
        causal_seq=4,
        trusted_time=TimeInterval(120_000, 120_000),
        rule=rule,
    )

    assert first.observation_counted
    assert not duplicate.observation_counted
    assert second.observation_counted
    assert confirmed.newly_confirmed is not None
    assert tracker.frozen_instrument_name == packet.leader_instrument_name
    designated = tracker.consume_designation()
    assert designated.designation_consumed
    with pytest.raises(RuntimeError, match="already consumed"):
        tracker.consume_designation()

    changed_band_first = tracker.observe(
        packet=_packet(band=ScoreBand.LOW),
        observation_identity=("book", 4),
        causal_seq=5,
        trusted_time=TimeInterval(180_000, 180_000),
        rule=rule,
    )
    assert changed_band_first.ended is None
    changed_band = tracker.observe(
        packet=_packet(band=ScoreBand.LOW),
        observation_identity=("book", 5),
        causal_seq=6,
        trusted_time=TimeInterval(240_000, 240_000),
        rule=rule,
    )
    assert changed_band.ended is not None
    assert changed_band.ended.reason is BucketEpisodeEndReason.SCORE_BAND_CHANGE


def test_bucket_tracker_leader_change_resets_preconfirmation() -> None:
    first_packet = _packet(instrument="FIRST", band=ScoreBand.LOW)
    second_packet = _packet(instrument="SECOND", band=ScoreBand.LOW)
    rule = _policy().tte_bands[1].option_rules[OptionType.CALL]
    tracker = RadarBucketEpisodeTracker(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=first_packet.bucket_key,
        score_model=_policy().score_model,
        clue_eligible=True,
    )
    tracker.observe(
        packet=first_packet,
        observation_identity=(1,),
        causal_seq=1,
        trusted_time=TimeInterval(0, 0),
        rule=rule,
    )
    tracker.observe(
        packet=first_packet,
        observation_identity=(2,),
        causal_seq=2,
        trusted_time=TimeInterval(60_000, 60_000),
        rule=rule,
    )
    reset = tracker.observe(
        packet=second_packet,
        observation_identity=(3,),
        causal_seq=3,
        trusted_time=TimeInterval(120_000, 120_000),
        rule=rule,
    )
    assert reset.newly_confirmed is None
    assert reset.observation_counted
    assert reset.confirmation_reset_reason is BucketConfirmationResetReason.LEADER_CHANGE

    alignment = tracker.align_leader(instrument_name="THIRD", score_band=ScoreBand.LOW)
    assert alignment.state_changed
    assert alignment.confirmation_reset_reason is BucketConfirmationResetReason.LEADER_CHANGE
    aligned = tracker.observe(
        packet=_packet(instrument="THIRD", band=ScoreBand.LOW),
        observation_identity=(4,),
        causal_seq=4,
        trusted_time=TimeInterval(180_000, 180_000),
        rule=rule,
    )
    assert aligned.observation_counted
    assert aligned.newly_confirmed is None


def test_bucket_episode_identity_is_public_and_binds_every_decision_axis() -> None:
    packet = _packet()
    identity = radar_bucket_episode_identity(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=packet.bucket_key,
        leader_instrument_name=packet.leader_instrument_name,
        score_band=ScoreBand.HIGH,
        activation_causal_seq=7,
    )
    assert identity.startswith("sha256:") and len(identity) == 71
    assert (
        radar_bucket_episode_identity(
            runtime_identity="sha256:" + "4" * 64,
            policy_identity=IDENTITY,
            bucket_key=packet.bucket_key,
            leader_instrument_name=packet.leader_instrument_name,
            score_band=ScoreBand.MID,
            activation_causal_seq=7,
        )
        != identity
    )


def test_high_episode_holds_mid_and_requires_two_distinct_separated_clear_observations() -> None:
    high = _packet(band=ScoreBand.HIGH)
    policy = _policy()
    rule = policy.tte_bands[1].option_rules[OptionType.CALL]
    tracker = RadarBucketEpisodeTracker(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=high.bucket_key,
        score_model=policy.score_model,
        clue_eligible=True,
    )
    for index, timestamp in enumerate((0, 60_000, 120_000), start=1):
        confirmed = tracker.observe(
            packet=high,
            observation_identity=("high", index),
            causal_seq=index,
            trusted_time=TimeInterval(timestamp, timestamp),
            rule=rule,
        )
    assert confirmed.newly_confirmed is not None

    mid = _packet(band=ScoreBand.MID)
    hold = tracker.observe(
        packet=mid,
        observation_identity=("mid", 1),
        causal_seq=4,
        trusted_time=TimeInterval(180_000, 180_000),
        rule=rule,
    )
    assert hold.ended is None

    low = _packet(band=ScoreBand.LOW)
    clear_crossing = replace(
        low,
        result=replace(low.result, score=_interval("49", "50"), band=ScoreBand.REVIEW),
    )
    first_clear = tracker.observe(
        packet=clear_crossing,
        observation_identity=("clear", 1),
        causal_seq=5,
        trusted_time=TimeInterval(240_000, 240_000),
        rule=rule,
    )
    duplicate = tracker.observe(
        packet=clear_crossing,
        observation_identity=("clear", 1),
        causal_seq=6,
        trusted_time=TimeInterval(300_000, 300_000),
        rule=rule,
    )
    too_close = tracker.observe(
        packet=clear_crossing,
        observation_identity=("clear", 2),
        causal_seq=7,
        trusted_time=TimeInterval(299_999, 299_999),
        rule=rule,
    )
    cleared = tracker.observe(
        packet=clear_crossing,
        observation_identity=("clear", 2),
        causal_seq=8,
        trusted_time=TimeInterval(300_000, 300_000),
        rule=rule,
    )
    assert first_clear.ended is None and first_clear.observation_counted
    assert duplicate.ended is None and not duplicate.observation_counted
    assert too_close.ended is None and not too_close.observation_counted
    assert cleared.ended is not None


def test_review_only_tte_bucket_never_forms_research_episode() -> None:
    policy = _policy()
    review_band = policy.tte_bands[0]
    packet = _packet(band=ScoreBand.MID)
    review_key = replace(packet.bucket_key, tte_band_id=review_band.band_id)
    packet = replace(packet, bucket_key=review_key)
    tracker = RadarBucketEpisodeTracker(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=review_key,
        score_model=policy.score_model,
        clue_eligible=review_band.clue_eligible,
    )
    alignment = tracker.align_leader(
        instrument_name=packet.leader_instrument_name,
        score_band=packet.result.band,
    )
    assert not alignment.state_changed
    assert alignment.confirmation_reset_reason is None
    assert (
        tracker.projection(review_band.option_rules[OptionType.CALL]).state
        is BucketEpisodeState.IDLE
    )
    for index, timestamp in enumerate((0, 60_000, 120_000), start=1):
        transition = tracker.observe(
            packet=packet,
            observation_identity=(index,),
            causal_seq=index,
            trusted_time=TimeInterval(timestamp, timestamp),
            rule=review_band.option_rules[OptionType.CALL],
        )
    assert transition.newly_confirmed is None
    assert tracker.episode is None
    assert tracker.confirmation_observation_count == 0
    assert (
        tracker.projection(review_band.option_rules[OptionType.CALL]).state
        is BucketEpisodeState.IDLE
    )


def test_bucket_tracker_attributes_score_band_and_core_unknown_confirmation_resets() -> None:
    policy = _policy()
    rule = policy.tte_bands[1].option_rules[OptionType.CALL]
    packet = _packet(band=ScoreBand.MID)
    tracker = RadarBucketEpisodeTracker(
        runtime_identity="sha256:" + "4" * 64,
        policy_identity=IDENTITY,
        bucket_key=packet.bucket_key,
        score_model=policy.score_model,
        clue_eligible=True,
    )
    tracker.observe(
        packet=packet,
        observation_identity=(1,),
        causal_seq=1,
        trusted_time=TimeInterval(0, 0),
        rule=rule,
    )

    band_reset = tracker.align_leader(
        instrument_name=packet.leader_instrument_name,
        score_band=ScoreBand.LOW,
    )
    assert band_reset.confirmation_reset_reason is BucketConfirmationResetReason.SCORE_BAND_CHANGE
    assert tracker.confirmation_observation_count == 0

    tracker.observe(
        packet=_packet(band=ScoreBand.LOW),
        observation_identity=(2,),
        causal_seq=2,
        trusted_time=TimeInterval(60_000, 60_000),
        rule=rule,
    )
    unknown_reset = tracker.core_unknown(causal_seq=3, reason="OPTION_BOOK_UNKNOWN")
    assert unknown_reset.confirmation_reset_reason is BucketConfirmationResetReason.CORE_UNKNOWN
    assert tracker.projection(rule).state is BucketEpisodeState.IDLE

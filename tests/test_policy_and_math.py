from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import short_vol_radar.policy as policy_module
from conftest import PolicyFactory
from market_monitor import TimeInterval
from options_domain import OptionType
from short_vol_radar.baseline import BaselineUnavailable, compute_baseline
from short_vol_radar.black import (
    DecimalInterval,
    NumericalUnknown,
    black_price,
    delta_interval,
    executable_iv_interval,
    invert_total_volatility,
)
from short_vol_radar.policy import (
    PolicyError,
    band_for_tte,
    digest_policy_bytes,
    load_policy,
    load_policy_bytes,
)


def test_policy_loads_exact_bytes_once_and_binds_digest(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory()
    path = tmp_path / "policy.json"
    path.write_bytes(exact)
    policy = load_policy(path, digest)
    assert policy.identity == digest
    assert policy.target_base_quantity_btc == Decimal("0.1")
    assert policy.largest_lookback_minutes == 5

    path.write_text("{}", encoding="utf-8")
    assert policy.target_base_quantity_btc == Decimal("0.1")
    assert policy.tte_bands[0].option_rules[OptionType.CALL].activation_ratio == Decimal("1.2")


def test_two_materially_different_policy_fixtures_change_runtime_values(
    policy_factory: PolicyFactory,
) -> None:
    first_bytes, first_digest = policy_factory(target=0.1, activation=1.2)
    second_bytes, second_digest = policy_factory(target=0.3, activation=1.5)
    first = load_policy_bytes(first_bytes, first_digest)
    second = load_policy_bytes(second_bytes, second_digest)
    assert first.identity != second.identity
    assert first.target_base_quantity_btc != second.target_base_quantity_btc
    assert (
        first.tte_bands[0].option_rules[OptionType.CALL].activation_ratio
        != second.tte_bands[0].option_rules[OptionType.CALL].activation_ratio
    )


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"\xef\xbb\xbf{}", "BOM"),
        (b'{"a":1,"a":2}', "duplicate"),
        (
            b'{"policy_family":"POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE",'
            b'"target_base_quantity_btc":NaN,"tte_bands":[]}',
            "non-finite",
        ),
    ],
)
def test_policy_rejects_bom_duplicates_and_non_finite(payload: bytes, error: str) -> None:
    digest = digest_policy_bytes(payload)
    with pytest.raises(PolicyError, match=error):
        load_policy_bytes(payload, digest)


def test_policy_rejects_digest_mismatch_unknown_keys_and_relationships(
    policy_factory: PolicyFactory,
) -> None:
    exact, _digest = policy_factory()
    with pytest.raises(PolicyError, match="mismatch"):
        load_policy_bytes(exact, "sha256:" + "0" * 64)

    document: dict[str, Any] = json.loads(exact)
    document["unknown"] = True
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="unknown"):
        load_policy_bytes(changed, digest_policy_bytes(changed))

    document = json.loads(exact)
    document["tte_bands"][0]["option_rules"]["call"]["activation_ratio"] = 1
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="activation > 1"):
        load_policy_bytes(changed, digest_policy_bytes(changed))

    document = json.loads(exact)
    document["tte_bands"][0]["lookback_weights"] = [0.2, 0.7]
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="sum exactly"):
        load_policy_bytes(changed, digest_policy_bytes(changed))


def test_policy_rejects_invalid_steps_counts_bands_and_empty_rules(
    policy_factory: PolicyFactory,
) -> None:
    exact, _ = policy_factory()
    document: dict[str, Any] = json.loads(exact)
    document["tte_bands"][0]["lower_bound_minutes"] = 20
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="bounds"):
        load_policy_bytes(changed, digest_policy_bytes(changed))

    document = json.loads(exact)
    document["tte_bands"][0]["option_rules"] = {}
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="non-empty"):
        load_policy_bytes(changed, digest_policy_bytes(changed))

    document = json.loads(exact)
    document["tte_bands"][0]["option_rules"]["call"]["minimum_separation_ms"] = -1
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="non-negative integer"):
        load_policy_bytes(changed, digest_policy_bytes(changed))

    document = json.loads(exact)
    document["target_base_quantity_btc"] = "0.1"
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="JSON numeric token"):
        load_policy_bytes(changed, digest_policy_bytes(changed))


def test_band_selection_uses_full_uncertainty_interval(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    selected = band_for_tte(
        policy,
        lower_tte_ms=30 * 60_000 + 1,
        upper_tte_ms=360 * 60_000,
        option_type=OptionType.CALL,
    )
    assert selected is not None
    assert selected.band_id == "settlement-clear-to-six-hours"
    assert (
        band_for_tte(
            policy,
            lower_tte_ms=360 * 60_000 - 1,
            upper_tte_ms=360 * 60_000 + 1,
            option_type=OptionType.CALL,
        )
        is None
    )


def test_time_applicability_classifies_every_business_boundary(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    expiry = 100 * 60_000

    def classify(lower_tte: int, upper_tte: int) -> str:
        result = policy_module.classify_time_applicability(
            policy,
            expiration_timestamp_ms=expiry,
            trusted_time=TimeInterval(expiry - upper_tte, expiry - lower_tte),
            option_type=OptionType.CALL,
        )
        return result.classification.value

    assert classify(60 * 60_000, 60 * 60_000) == "IN_BAND"
    assert classify(360 * 60_000 - 1, 360 * 60_000 + 1) == "ADJACENT_BAND_BOUNDARY"
    assert classify(30 * 60_000, 30 * 60_000) == "FINAL_WINDOW"
    assert classify(72 * 60 * 60_000 - 1, 72 * 60 * 60_000 + 1) == "MONITOR_BOUNDARY"
    assert classify(-1, -1) == "OUT_OF_MONITOR_SCOPE"

    document = json.loads(exact)
    document["tte_bands"][0]["upper_bound_minutes"] = 300
    document["tte_bands"][1]["lower_bound_minutes"] = 420
    changed = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    gap_policy = load_policy_bytes(changed, digest_policy_bytes(changed))
    gap = policy_module.classify_time_applicability(
        gap_policy,
        expiration_timestamp_ms=expiry,
        trusted_time=TimeInterval(expiry - 390 * 60_000, expiry - 390 * 60_000),
        option_type=OptionType.CALL,
    )
    assert gap.classification.value == "POLICY_GAP"


def test_baseline_uses_causal_log_returns_configured_weights_and_floor() -> None:
    closes = tuple(Decimal(item) for item in ("100", "101", "100", "102", "103", "104"))
    result = compute_baseline(
        closes=closes,
        lookbacks=(2, 5),
        weights=(Decimal("0.25"), Decimal("0.75")),
        annualized_variance_floor=Decimal("0.01"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(61),
    )
    assert tuple(item[0] for item in result.window_variances) == (2, 5)
    assert result.variance_rate_per_minute > 0
    assert result.total_variance_high > result.total_variance_low
    assert result.annualized_volatility > 0

    floored = compute_baseline(
        closes=(Decimal(100),) * 6,
        lookbacks=(5,),
        weights=(Decimal(1),),
        annualized_variance_floor=Decimal("0.04"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(60),
    )
    assert floored.annualized_volatility == Decimal("0.2")


def test_baseline_warmup_and_invalid_inputs_fail_closed() -> None:
    with pytest.raises(BaselineUnavailable, match="warm-up"):
        compute_baseline(
            closes=(Decimal(100), Decimal(101)),
            lookbacks=(5,),
            weights=(Decimal(1),),
            annualized_variance_floor=Decimal("0.01"),
            remaining_life_minutes_low=Decimal(60),
            remaining_life_minutes_high=Decimal(60),
        )
    with pytest.raises(BaselineUnavailable, match="invalid price"):
        compute_baseline(
            closes=(Decimal(100), Decimal(0)),
            lookbacks=(1,),
            weights=(Decimal(1),),
            annualized_variance_floor=Decimal("0.01"),
            remaining_life_minutes_low=Decimal(60),
            remaining_life_minutes_high=Decimal(60),
        )


@pytest.mark.parametrize("option_type", [OptionType.CALL, OptionType.PUT])
def test_total_volatility_solver_fixed_vector(option_type: OptionType) -> None:
    forward = Decimal(100)
    strike = Decimal(110 if option_type is OptionType.CALL else 90)
    expected_x = 0.35
    target = Decimal(str(black_price(float(forward), float(strike), expected_x, option_type)))
    interval = invert_total_volatility(
        target_price=target,
        forward=forward,
        strike=strike,
        option_type=option_type,
    )
    midpoint = (interval.lower + interval.upper) / 2
    assert abs(midpoint - Decimal(str(expected_x))) < Decimal("1e-14")
    assert (
        black_price(float(forward), float(strike), float(interval.lower), option_type)
        <= float(target)
        <= black_price(float(forward), float(strike), float(interval.upper), option_type)
    )
    assert interval.upper - interval.lower < Decimal("1e-15")
    delta = delta_interval(
        forward=forward,
        strike=strike,
        total_volatility=interval,
        option_type=option_type,
    )
    assert Decimal(-1) <= delta.lower <= delta.upper <= Decimal(1)


def test_total_volatility_solver_domain_and_iv_interval_fail_closed() -> None:
    with pytest.raises(NumericalUnknown, match="domain"):
        invert_total_volatility(
            target_price=Decimal(100),
            forward=Decimal(100),
            strike=Decimal(110),
            option_type=OptionType.CALL,
        )
    with pytest.raises(NumericalUnknown, match="strictly positive"):
        executable_iv_interval(
            total_volatility=invert_total_volatility(
                target_price=Decimal(str(black_price(100, 110, 0.3, OptionType.CALL))),
                forward=Decimal(100),
                strike=Decimal(110),
                option_type=OptionType.CALL,
            ),
            time_years=DecimalInterval(Decimal(0), Decimal("0.1")),
        )


def test_policy_digest_is_exact_bytes_not_semantic_json(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    pretty = json.dumps(json.loads(exact), indent=2).encode()
    assert hashlib.sha256(exact).digest() != hashlib.sha256(pretty).digest()
    assert digest != digest_policy_bytes(pretty)

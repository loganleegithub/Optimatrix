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
from short_vol_radar.baseline import BaselineResult, BaselineUnavailable, compute_baseline
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

ROOT = Path(__file__).resolve().parents[1]


def _policy_with_ticker_stale_deadline(
    policy_factory: PolicyFactory,
    *,
    deadline_ms: object = 5_000,
) -> tuple[bytes, str]:
    exact, _ = policy_factory()
    document: dict[str, Any] = json.loads(exact)
    document["policy_schema_version"] = 6
    runtime_limits = document["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    runtime_limits["ticker_source_stale_deadline_ms"] = deadline_ms
    changed = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    return changed, digest_policy_bytes(changed)


def test_policy_requires_and_binds_ticker_source_stale_deadline(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = _policy_with_ticker_stale_deadline(policy_factory)

    policy = load_policy_bytes(exact, digest)

    assert policy.schema_version == 6
    assert policy.runtime_limits.ticker_source_stale_deadline_ms == 5_000
    assert policy.runtime_limits.as_object()["ticker_source_stale_deadline_ms"] == 5_000


def test_ticker_source_stale_deadline_changes_policy_identity(
    policy_factory: PolicyFactory,
) -> None:
    first_bytes, first_digest = _policy_with_ticker_stale_deadline(
        policy_factory,
        deadline_ms=5_000,
    )
    second_bytes, second_digest = _policy_with_ticker_stale_deadline(
        policy_factory,
        deadline_ms=10_000,
    )

    first = load_policy_bytes(first_bytes, first_digest)
    second = load_policy_bytes(second_bytes, second_digest)

    assert first.identity != second.identity
    assert (
        first.runtime_limits.ticker_source_stale_deadline_ms
        != second.runtime_limits.ticker_source_stale_deadline_ms
    )


def test_policy_loads_exact_bytes_once_and_binds_digest(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory()
    path = tmp_path / "policy.json"
    path.write_bytes(exact)
    policy = load_policy(path, digest)
    assert policy.identity == digest
    assert policy.schema_version == 6
    assert policy.target_base_quantity_btc == Decimal("0.1")
    assert policy.runtime_limits.index_history_refresh_interval_ms == 300_000
    assert policy.runtime_limits.index_history_source_stale_deadline_ms == 900_000
    assert policy.largest_lookback_minutes == 5
    assert policy.tte_bands[0].return_interval_minutes == 5
    assert policy.runtime_limits.notification_queue_lag_deadline_ms == 1_000
    assert policy.runtime_limits.ticker_source_stale_deadline_ms == 5_000
    assert policy.runtime_limits.time_boundary_poll_interval_ms == 1_000

    path.write_text("{}", encoding="utf-8")
    assert policy.target_base_quantity_btc == Decimal("0.1")
    assert policy.tte_bands[0].option_rules[OptionType.CALL].activation_ratio == Decimal("1.2")


def test_production_radar_policy_is_the_exact_credible_clue_screen() -> None:
    path = ROOT / "policies/short-vol-fixed-public-shadow-radar.json"
    exact = path.read_bytes()
    policy = load_policy_bytes(exact, digest_policy_bytes(exact))

    assert policy.schema_version == 6
    assert policy.family == "CONSERVATIVE_MULTI_HORIZON_EXECUTABLE_IV_RICHNESS"
    assert policy.target_base_quantity_btc == Decimal("0.1")
    assert policy.runtime_limits.index_history_refresh_interval_ms == 300_000
    assert policy.runtime_limits.index_history_source_stale_deadline_ms == 900_000
    assert [
        (band.band_id, band.lower_bound_minutes, band.upper_bound_minutes, band.clue_eligible)
        for band in policy.tte_bands
    ] == [
        ("review-only-30-to-45m", 30, 45, False),
        ("ultra-short-45m-to-6h", 45, 360, True),
        ("intraday-6h-to-24h", 360, 1_440, True),
        ("multiday-24h-to-72h", 1_440, 4_320, True),
    ]
    for band in policy.tte_bands:
        assert band.return_interval_minutes == 5
        assert band.lookbacks_minutes == (30, 120, 360)
        assert band.annualized_variance_floor == Decimal("0.01")
        for option_type in (OptionType.CALL, OptionType.PUT):
            rule = band.option_rules[option_type]
            assert (rule.abs_delta_min, rule.abs_delta_max) == (
                Decimal("0.05"),
                Decimal("0.4"),
            )
            assert (rule.activation_ratio, rule.clear_ratio) == (
                Decimal("1.2"),
                Decimal("1.05"),
            )
            assert rule.activation_observation_count == 3
            assert rule.clear_observation_count == 2
            assert rule.minimum_separation_ms == 300_000


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
            b'{"policy_family":"CONSERVATIVE_MULTI_HORIZON_EXECUTABLE_IV_RICHNESS",'
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
    document["tte_bands"][0]["lookbacks_minutes"] = [6]
    changed = json.dumps(document).encode()
    with pytest.raises(PolicyError, match="divisible"):
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


def test_policy_rejects_missing_ticker_source_stale_deadline_without_default(
    policy_factory: PolicyFactory,
) -> None:
    exact, _ = policy_factory()
    document: dict[str, Any] = json.loads(exact)
    runtime_limits = document["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    del runtime_limits["ticker_source_stale_deadline_ms"]
    changed = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises(PolicyError, match="ticker_source_stale_deadline_ms"):
        load_policy_bytes(changed, digest_policy_bytes(changed))


@pytest.mark.parametrize("deadline_ms", [0, -1, 1.5, "5000"])
def test_policy_rejects_invalid_ticker_source_stale_deadline(
    policy_factory: PolicyFactory,
    deadline_ms: object,
) -> None:
    changed, digest = _policy_with_ticker_stale_deadline(
        policy_factory,
        deadline_ms=deadline_ms,
    )

    with pytest.raises(PolicyError, match="ticker_source_stale_deadline_ms"):
        load_policy_bytes(changed, digest)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda document: document.update(policy_schema_version=2),
            "policy_schema_version",
        ),
        (
            lambda document: document["runtime_limits"].update(
                notification_queue_lag_deadline_ms=0
            ),
            "notification_queue_lag_deadline_ms",
        ),
        (
            lambda document: document["runtime_limits"].update(
                time_boundary_poll_interval_ms=1_001
            ),
            "time_boundary_poll_interval_ms",
        ),
        (
            lambda document: document["runtime_limits"].update(ticker_source_stale_deadline_ms=999),
            "ticker_source_stale_deadline_ms",
        ),
        (
            lambda document: document["runtime_limits"].update(session_liveness_deadline_ms=30_000),
            "session_liveness_deadline_ms",
        ),
        (
            lambda document: document["runtime_limits"].update(clock_stale_deadline_ms=30_000),
            "clock_stale_deadline_ms",
        ),
        (
            lambda document: document["runtime_limits"].update(
                index_history_source_stale_deadline_ms=300_000
            ),
            "index_history_source_stale_deadline_ms",
        ),
    ],
)
def test_policy_owns_and_validates_all_runtime_deadlines(
    policy_factory: PolicyFactory,
    mutate: Any,
    error: str,
) -> None:
    exact, _ = policy_factory()
    document: dict[str, Any] = json.loads(exact)
    mutate(document)
    changed = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises(PolicyError, match=error):
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


def test_policy_rejects_multiple_owners_for_the_history_sampling_interval(
    policy_factory: PolicyFactory,
) -> None:
    exact, _digest = policy_factory()
    document: dict[str, Any] = json.loads(exact)
    bands = document["tte_bands"]
    assert isinstance(bands, list)
    assert isinstance(bands[1], dict)
    bands[1]["return_interval_minutes"] = 1
    changed = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises(PolicyError, match="share one return_interval_minutes owner"):
        load_policy_bytes(changed, digest_policy_bytes(changed))


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


def test_baseline_uses_non_overlapping_five_minute_returns_and_conservative_max() -> None:
    closes = tuple(
        Decimal(item)
        for item in ("100", "100", "100", "100", "100", "101", "101", "101", "101", "101", "110")
    )
    result = compute_baseline(
        sampled_prices=(closes[0], closes[5], closes[10]),
        lookbacks=(5, 10),
        return_interval_minutes=5,
        annualized_variance_floor=Decimal("0.01"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(61),
    )
    assert tuple(item[0] for item in result.window_variances) == (5, 10)
    assert result.return_interval_minutes == 5
    assert result.selected_lookback_minutes == 5
    assert result.variance_rate_per_minute == max(
        variance for _lookback, variance in result.window_variances
    )
    assert result.total_variance_high > result.total_variance_low
    assert result.annualized_volatility > 0

    floored = compute_baseline(
        sampled_prices=(Decimal(100),) * 2,
        lookbacks=(5,),
        return_interval_minutes=5,
        annualized_variance_floor=Decimal("0.04"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(60),
    )
    assert floored.annualized_volatility == Decimal("0.2")
    assert floored.selected_lookback_minutes is None


def test_baseline_exposes_directional_semivariance_and_jump_diagnostics_without_gating() -> None:
    result = compute_baseline(
        sampled_prices=(
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("104"),
            Decimal("103"),
        ),
        lookbacks=(20,),
        return_interval_minutes=5,
        annualized_variance_floor=Decimal("0.000001"),
        remaining_life_minutes_low=Decimal(60),
        remaining_life_minutes_high=Decimal(60),
    )
    diagnostic = result.diagnostics_for(20)
    assert diagnostic.return_count == 4
    assert diagnostic.positive_semivariance_share > 0
    assert diagnostic.negative_semivariance_share > 0
    assert (
        diagnostic.positive_semivariance_share + diagnostic.negative_semivariance_share
        == Decimal(1)
    )
    assert diagnostic.jump_variation_rate_per_minute >= 0
    assert Decimal(0) <= diagnostic.jump_share <= Decimal(1)
    assert diagnostic.maximum_absolute_return > 0
    expected_net_return = Decimal(103).ln() - Decimal(100).ln()
    assert abs(diagnostic.net_return - expected_net_return) < Decimal("1e-27")


def test_baseline_consumes_only_the_owning_five_minute_samples() -> None:
    def baseline(sampled_prices: tuple[Decimal, ...]) -> BaselineResult:
        return compute_baseline(
            sampled_prices=sampled_prices,
            lookbacks=(10,),
            return_interval_minutes=5,
            annualized_variance_floor=Decimal("0.000001"),
            remaining_life_minutes_low=Decimal(60),
            remaining_life_minutes_high=Decimal(60),
        )

    result = baseline((Decimal("100"), Decimal("101"), Decimal("102")))
    assert result.return_interval_minutes == 5
    assert result.selected_lookback_minutes == 10


def test_baseline_warmup_and_invalid_inputs_fail_closed() -> None:
    with pytest.raises(BaselineUnavailable, match="warm-up"):
        compute_baseline(
            sampled_prices=(Decimal(100),),
            lookbacks=(5,),
            return_interval_minutes=5,
            annualized_variance_floor=Decimal("0.01"),
            remaining_life_minutes_low=Decimal(60),
            remaining_life_minutes_high=Decimal(60),
        )
    with pytest.raises(BaselineUnavailable, match="invalid price"):
        compute_baseline(
            sampled_prices=(Decimal(100), Decimal(0)),
            lookbacks=(1,),
            return_interval_minutes=1,
            annualized_variance_floor=Decimal("0.01"),
            remaining_life_minutes_low=Decimal(60),
            remaining_life_minutes_high=Decimal(60),
        )

    with pytest.raises(ValueError, match="divisible"):
        compute_baseline(
            sampled_prices=(Decimal(100),) * 7,
            lookbacks=(6,),
            return_interval_minutes=5,
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

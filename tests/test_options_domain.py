from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import OptionPayloadFactory
from market_monitor import PriceLevel, TimeInterval
from market_monitor.types import SourceDataError
from options_domain import (
    AmountMetadata,
    AmountState,
    Applicability,
    InstrumentLifecycleState,
    OptionType,
    PriceTickMetadata,
    PriceTickStep,
    check_target_amount,
    monitor_applicability,
    parse_combo_instrument,
    parse_option_instrument,
)
from options_domain.quotes import (
    stress_depth_walk_down_one_tick,
    stress_depth_walk_up_one_tick,
    walk_target_depth,
)


def test_option_filter_uses_official_usdc_product_fields(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    instrument = parse_option_instrument(payload)
    assert instrument is not None
    assert instrument.option_type is OptionType.CALL
    assert instrument.amount is not None
    assert instrument.amount.qty_tick_size == Decimal("0.1")
    assert instrument.price_tick == PriceTickMetadata(Decimal("0.01"))

    for field, wrong in (
        ("kind", "future"),
        ("base_currency", "ETH"),
        ("quote_currency", "USD"),
        ("settlement_currency", "BTC"),
        ("counter_currency", "USD"),
        ("price_index", "btc_usd"),
        ("instrument_type", "reversed"),
    ):
        changed = dict(payload)
        changed[field] = wrong
        assert parse_option_instrument(changed) is None


def test_option_parser_tolerates_extra_but_rejects_missing_consumed_field(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory(step=None)
    assert parse_option_instrument(payload) is not None
    payload.pop("strike")
    with pytest.raises(SourceDataError, match="strike"):
        parse_option_instrument(payload)

    payload = option_payload_factory()
    payload.pop("min_trade_amount")
    amount_unknown = parse_option_instrument(payload)
    assert amount_unknown is not None
    assert amount_unknown.amount is None


def test_option_parser_preserves_public_taker_commission_without_defaulting(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    without_commission = parse_option_instrument(payload)
    assert without_commission is not None
    assert without_commission.taker_commission is None

    payload["taker_commission"] = "0.0003"
    with_commission = parse_option_instrument(payload)
    assert with_commission is not None
    assert with_commission.taker_commission == Decimal("0.0003")

    payload["taker_commission"] = -0.0001
    with pytest.raises(SourceDataError, match="taker_commission"):
        parse_option_instrument(payload)


@pytest.mark.parametrize(
    "state",
    [
        InstrumentLifecycleState.SETTLEMENT,
        InstrumentLifecycleState.LOCKED,
        InstrumentLifecycleState.HALTED,
    ],
)
def test_option_parser_preserves_temporary_lifecycle_identity(
    option_payload_factory: OptionPayloadFactory,
    state: InstrumentLifecycleState,
) -> None:
    payload = option_payload_factory()
    payload["state"] = state.value
    payload["is_active"] = False

    instrument = parse_option_instrument(payload)

    assert instrument is not None
    assert instrument.lifecycle_state is state
    assert not instrument.is_active


def test_option_parser_preserves_open_but_inactive_identity(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    payload["is_active"] = False

    instrument = parse_option_instrument(payload)

    assert instrument is not None
    assert instrument.lifecycle_state is InstrumentLifecycleState.OPEN
    assert not instrument.is_active


@pytest.mark.parametrize(
    "state",
    [
        InstrumentLifecycleState.DELIVERED,
        InstrumentLifecycleState.INACTIVE,
        InstrumentLifecycleState.ARCHIVIZED,
    ],
)
def test_option_parser_excludes_final_lifecycle_states(
    option_payload_factory: OptionPayloadFactory,
    state: InstrumentLifecycleState,
) -> None:
    payload = option_payload_factory()
    payload["state"] = state.value

    assert parse_option_instrument(payload) is None


def test_option_parser_rejects_unknown_lifecycle_state(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    payload["state"] = "closed"

    with pytest.raises(SourceDataError, match="state"):
        parse_option_instrument(payload)


def test_combo_parser_requires_open_active_metadata() -> None:
    summary = {
        "id": "COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": "SHORT", "amount": -1},
            {"instrument_name": "LONG", "amount": 1},
        ],
    }
    metadata = {
        "instrument_name": "COMBO",
        "kind": "option_combo",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "counter_currency": "USDC",
        "instrument_type": "linear",
        "state": "open",
        "is_active": True,
        "contract_size": 1,
        "min_trade_amount": 0.1,
        "qty_tick_size": 0.1,
    }

    assert parse_combo_instrument(summary, metadata) is not None
    for state, is_active in (
        ("locked", True),
        ("halted", True),
        ("inactive", False),
        ("open", False),
    ):
        changed = {**metadata, "state": state, "is_active": is_active}
        assert parse_combo_instrument(summary, changed) is None

    with pytest.raises(SourceDataError, match="state"):
        parse_combo_instrument(summary, {**metadata, "state": "closed"})


@pytest.mark.parametrize(
    ("lower", "upper", "expected"),
    [
        (0, 0, Applicability.OUT_OF_MONITOR_SCOPE),
        (-1, -1, Applicability.APPLICABLE),
        (-1, 1, Applicability.TIME_BOUNDARY_UNKNOWN),
        (-(72 * 60 * 60 * 1_000), -(72 * 60 * 60 * 1_000), Applicability.APPLICABLE),
        (
            -(72 * 60 * 60 * 1_000 + 1),
            -(72 * 60 * 60 * 1_000 + 1),
            Applicability.OUT_OF_MONITOR_SCOPE,
        ),
    ],
)
def test_monitor_tte_boundaries(lower: int, upper: int, expected: Applicability) -> None:
    expiry = 1_000
    trusted = TimeInterval(expiry + lower, expiry + upper)
    assert monitor_applicability(expiry, trusted) is expected


def test_target_amount_uses_minimum_and_optional_published_grid_without_rounding() -> None:
    without_step = AmountMetadata(Decimal(1), Decimal("0.1"), None)
    assert check_target_amount(Decimal("0.15"), without_step).state is AmountState.ELIGIBLE
    with_step = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    assert check_target_amount(Decimal("0.15"), with_step).state is AmountState.INELIGIBLE
    assert check_target_amount(Decimal("0.2"), with_step).state is AmountState.ELIGIBLE
    assert check_target_amount(Decimal("0.05"), without_step).reason == "BELOW_MIN_TRADE_AMOUNT"


def test_target_depth_walk_uses_visible_levels_and_known_insufficiency() -> None:
    levels = (
        PriceLevel(Decimal("10"), Decimal("0.1")),
        PriceLevel(Decimal("9"), Decimal("0.2")),
    )
    walk = walk_target_depth(levels, Decimal("0.2"))
    assert walk is not None
    assert walk.consumed == (
        PriceLevel(Decimal("10"), Decimal("0.1")),
        PriceLevel(Decimal("9"), Decimal("0.1")),
    )
    assert walk.vwap == Decimal("9.5")
    assert walk_target_depth(levels, Decimal("0.4")) is None
    assert walk_target_depth((), Decimal("0.1")) is None


def test_option_tick_ladder_and_one_legal_tick_stress_are_exact() -> None:
    metadata = PriceTickMetadata(
        Decimal("0.0001"),
        (PriceTickStep(Decimal("0.005"), Decimal("0.0005")),),
    )
    assert metadata.tick_size_for_price(Decimal("0.005")) == Decimal("0.0005")
    assert metadata.tick_size_for_price(Decimal("0.0055")) == Decimal("0.0005")
    assert metadata.previous_legal_price(Decimal("0.005")) == Decimal("0.0049")
    assert metadata.previous_legal_price(Decimal("0.0055")) == Decimal("0.0050")
    assert metadata.next_legal_price(Decimal("0.0049")) == Decimal("0.005")
    assert metadata.next_legal_price(Decimal("0.005")) == Decimal("0.0055")

    walk = walk_target_depth(
        (
            PriceLevel(Decimal("0.0055"), Decimal("0.1")),
            PriceLevel(Decimal("0.0050"), Decimal("0.1")),
        ),
        Decimal("0.2"),
    )
    assert walk is not None
    stressed = stress_depth_walk_down_one_tick(walk, metadata)
    assert stressed is not None
    assert stressed.consumed == (
        PriceLevel(Decimal("0.0050"), Decimal("0.1")),
        PriceLevel(Decimal("0.0049"), Decimal("0.1")),
    )
    assert stressed.vwap == Decimal("0.00495")
    stressed_ask = stress_depth_walk_up_one_tick(walk, metadata)
    assert stressed_ask.consumed == (
        PriceLevel(Decimal("0.0060"), Decimal("0.1")),
        PriceLevel(Decimal("0.0055"), Decimal("0.1")),
    )
    assert stressed_ask.vwap == Decimal("0.00575")


def test_invalid_tick_metadata_is_local_unknown_not_an_instrument_rejection(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    payload["tick_size_steps"] = [
        {"above_price": "0.01", "tick_size": "0.001"},
        {"above_price": "0.005", "tick_size": "0.0005"},
    ]
    instrument = parse_option_instrument(payload)
    assert instrument is not None
    assert instrument.price_tick is None
    assert instrument.amount is not None


def test_tick_step_must_increase_and_remain_a_multiple_of_base_tick(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    payload["tick_size"] = "0.0002"
    payload["tick_size_steps"] = [
        {"above_price": "0.005", "tick_size": "0.0005"},
    ]
    instrument = parse_option_instrument(payload)
    assert instrument is not None
    assert instrument.price_tick is None

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
    check_target_amount,
    detector_window_applicability,
    monitor_applicability,
    parse_combo_instrument,
    parse_option_instrument,
    parse_option_instrument_fact,
)
from options_domain.quotes import walk_target_depth


def test_option_filter_uses_official_usdc_product_fields(
    option_payload_factory: OptionPayloadFactory,
) -> None:
    payload = option_payload_factory()
    instrument = parse_option_instrument(payload)
    assert instrument is not None
    assert instrument.option_type is OptionType.CALL
    assert instrument.amount is not None
    assert instrument.amount.qty_tick_size == Decimal("0.1")

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


@pytest.mark.parametrize(
    "state",
    [
        InstrumentLifecycleState.DELIVERED,
        InstrumentLifecycleState.ARCHIVIZED,
    ],
)
def test_downstream_option_fact_parser_preserves_natural_terminal_witness(
    option_payload_factory: OptionPayloadFactory,
    state: InstrumentLifecycleState,
) -> None:
    payload = option_payload_factory()
    payload["state"] = state.value
    payload["is_active"] = False
    payload["taker_commission"] = "0.0003"

    witness = parse_option_instrument_fact(payload)

    assert witness is not None
    assert witness.lifecycle_state is state
    assert not witness.is_active
    assert witness.taker_commission == Decimal("0.0003")


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


def test_detector_final_delivery_window_is_explicitly_out_of_scope() -> None:
    expiry = 10_000_000
    thirty_minutes = 30 * 60 * 1_000
    assert (
        detector_window_applicability(
            expiry,
            TimeInterval(expiry - thirty_minutes, expiry - thirty_minutes),
        )
        is Applicability.OUT_OF_BASELINE_SCOPE
    )
    assert (
        detector_window_applicability(
            expiry,
            TimeInterval(expiry - thirty_minutes - 1, expiry - thirty_minutes - 1),
        )
        is Applicability.APPLICABLE
    )
    assert (
        detector_window_applicability(
            expiry,
            TimeInterval(expiry - thirty_minutes - 1, expiry - thirty_minutes + 1),
        )
        is Applicability.TIME_BOUNDARY_UNKNOWN
    )


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

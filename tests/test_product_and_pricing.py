from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from optimatrix.market import OptionQuote, OptionType, PriceLevel, TickSchedule, TickStep
from optimatrix.pricing import Action, execute_leg, price_credit_vertical, settle_option_leg
from optimatrix.products import BTC, ETH


def _quote(name: str, strike: str, option_type: OptionType, bid: str, ask: str) -> OptionQuote:
    return OptionQuote(
        instrument_name=name,
        product=BTC,
        expiry=datetime(2026, 8, 13, 8, 0, tzinfo=UTC),
        strike=Decimal(strike),
        option_type=option_type,
        signed_delta=Decimal("-0.15") if option_type is OptionType.PUT else Decimal("0.15"),
        mark_iv=Decimal("0.55"),
        bid=(PriceLevel(Decimal(bid), Decimal("1")),),
        ask=(PriceLevel(Decimal(ask), Decimal("1")),),
        tick_schedule=TickSchedule(
            Decimal("0.0001"),
            (TickStep(Decimal("0.005"), Decimal("0.0005")),),
        ),
        source_timestamp_ms=1,
        received_timestamp_ms=2,
        continuity_epoch=1,
        delivery_fee_exempt=True,
    )


def test_product_registry_reserves_eth_without_implementing_channel_logic() -> None:
    assert BTC.minimum_quantity == Decimal("0.1")
    assert ETH.minimum_quantity == Decimal("1")


def test_entry_pricing_stresses_the_sell_down_and_buy_up() -> None:
    short = _quote("BTC-X-95000-P", "95000", OptionType.PUT, "0.0028", "0.0029")
    long = _quote("BTC-X-93000-P", "93000", OptionType.PUT, "0.0008", "0.0009")
    execution = price_credit_vertical(
        short_quote=short,
        long_quote=long,
        quantity=Decimal("0.1"),
        index_price=Decimal("100000"),
    )
    assert execution is not None
    assert execution.short_leg.action is Action.SELL
    assert execution.short_leg.raw.native_vwap == Decimal("0.0028")
    assert execution.short_leg.stressed.native_vwap == Decimal("0.0027")
    assert execution.long_leg.raw.native_vwap == Decimal("0.0009")
    assert execution.long_leg.stressed.native_vwap == Decimal("0.0010")
    assert execution.usd_net_credit > 0


def test_short_only_exit_can_execute_when_wing_bid_is_missing() -> None:
    short = _quote("BTC-X-95000-P", "95000", OptionType.PUT, "0.0028", "0.0030")
    execution = execute_leg(
        short,
        action=Action.BUY,
        quantity=Decimal("0.1"),
        index_price=Decimal("100000"),
    )
    assert execution is not None
    assert execution.action is Action.BUY


def test_daily_option_settlement_fee_is_exempt() -> None:
    settled = settle_option_leg(
        product=BTC,
        option_type="CALL",
        strike=Decimal("100000"),
        delivery_price=Decimal("120000"),
        quantity=Decimal("0.1"),
        action=Action.BUY,
        delivery_fee_exempt=True,
    )
    assert settled.delivery_fee_native == 0
    assert settled.net_cashflow_native == settled.contractual_cashflow_native


def test_standard_option_settlement_fee_is_reserved_and_capped() -> None:
    settled = settle_option_leg(
        product=BTC,
        option_type="CALL",
        strike=Decimal("100000"),
        delivery_price=Decimal("120000"),
        quantity=Decimal("0.1"),
        action=Action.BUY,
        delivery_fee_exempt=False,
    )
    assert settled.delivery_fee_native == Decimal("0.000015")
    assert settled.net_cashflow_native == (
        settled.contractual_cashflow_native - settled.delivery_fee_native
    )

    capped = settle_option_leg(
        product=BTC,
        option_type="CALL",
        strike=Decimal("119990"),
        delivery_price=Decimal("120000"),
        quantity=Decimal("0.1"),
        action=Action.BUY,
        delivery_fee_exempt=False,
    )
    assert capped.delivery_fee_native == Decimal("0.125") * capped.contractual_cashflow_native


def test_tick_stress_crosses_published_regime_boundary_legally() -> None:
    schedule = TickSchedule(
        Decimal("0.0001"),
        (TickStep(Decimal("0.005"), Decimal("0.0005")),),
    )
    assert schedule.previous_price(Decimal("0.005")) == Decimal("0.0049")
    assert schedule.next_price(Decimal("0.0049")) == Decimal("0.005")
    assert schedule.next_price(Decimal("0.005")) == Decimal("0.0055")
    assert schedule.tick_distance(Decimal("0.0049"), Decimal("0.0055")) == 2


def test_option_quote_rejects_crossed_or_unsorted_books() -> None:
    import pytest

    base = _quote("BTC-X-95000-P", "95000", OptionType.PUT, "0.0028", "0.0029")
    with pytest.raises(ValueError, match="uncrossed"):
        OptionQuote(
            **{
                **base.__dict__,
                "bid": (PriceLevel(Decimal("0.0030"), Decimal("1")),),
                "ask": (PriceLevel(Decimal("0.0029"), Decimal("1")),),
            }
        )
    with pytest.raises(ValueError, match="highest to lowest"):
        OptionQuote(
            **{
                **base.__dict__,
                "bid": (
                    PriceLevel(Decimal("0.0027"), Decimal("0.5")),
                    PriceLevel(Decimal("0.0028"), Decimal("0.5")),
                ),
            }
        )

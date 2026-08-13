from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from optimatrix.pricing import (
    price_btc_0dte_condor,
    standard_option_combo_fee_native,
)
from optimatrix.products import BTC, ETH
from optimatrix.scenarios import base_chain, current_expiry


def test_product_registry_reserves_eth_without_implementing_strategy_logic() -> None:
    assert BTC.minimum_quantity == Decimal("0.1")
    assert ETH.minimum_quantity == Decimal("1")


def test_whole_condor_pricing_uses_combo_directional_fee_discount() -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    long_put, short_put, short_call, long_call = base_chain(
        expiry=current_expiry(at),
        observed_at=at,
    )
    pricing = price_btc_0dte_condor(
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        amount=Decimal("0.1"),
        boundary_index_price=Decimal("100000"),
    )
    assert pricing is not None
    entry_legs = (
        pricing.long_put,
        pricing.short_put,
        pricing.short_call,
        pricing.long_call,
    )
    assert pricing.combo_standard_fee_native == standard_option_combo_fee_native(entry_legs)
    assert pricing.combo_standard_fee_native < pricing.component_leg_stress_fee_native
    assert pricing.native_net_credit == (
        pricing.native_gross_credit - pricing.combo_standard_fee_native
    )
    assert pricing.maximum_contractual_payoff_cap_usd == Decimal("200")
    assert pricing.boundary_index_price_usd == Decimal("100000")
    assert not hasattr(pricing, "maximum_loss_btc")

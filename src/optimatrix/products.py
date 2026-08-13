from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity

PREMIUM_FEE_CAP_FRACTION = Decimal("0.125")


class ProductId(StrEnum):
    INVERSE_BTC = "INVERSE_BTC"
    INVERSE_ETH = "INVERSE_ETH"


@dataclass(frozen=True)
class ProductSpec:
    product_id: ProductId
    public_currency: str
    base_currency: str
    settlement_currency: str
    price_index: str
    instrument_prefix: str
    minimum_quantity: Decimal
    quantity_tick: Decimal
    standard_option_fee_rate: Decimal
    standard_delivery_fee_rate: Decimal
    native_premium_currency: str

    def __post_init__(self) -> None:
        for field_name in (
            "public_currency",
            "base_currency",
            "settlement_currency",
            "price_index",
            "instrument_prefix",
            "native_premium_currency",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must be non-empty")
        for value, field_name in (
            (self.minimum_quantity, "minimum_quantity"),
            (self.quantity_tick, "quantity_tick"),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")
        for value, field_name in (
            (self.standard_option_fee_rate, "standard_option_fee_rate"),
            (self.standard_delivery_fee_rate, "standard_delivery_fee_rate"),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "ProductSpecV1",
            self.product_id,
            self.public_currency,
            self.base_currency,
            self.settlement_currency,
            self.price_index,
            self.instrument_prefix,
            self.minimum_quantity,
            self.quantity_tick,
            self.standard_option_fee_rate,
            self.standard_delivery_fee_rate,
            self.native_premium_currency,
        )

    def check_quantity(self, quantity: Decimal) -> None:
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("quantity must be finite and positive")
        if quantity < self.minimum_quantity:
            raise ValueError("quantity is below the published minimum")
        if quantity % self.quantity_tick != 0:
            raise ValueError("quantity is off the published grid")

    def value_native(self, native_amount: Decimal, *, index_price: Decimal) -> Decimal:
        _require_finite(native_amount, "native_amount")
        _require_positive(index_price, "index_price")
        return native_amount * index_price

    def native_option_fee(
        self,
        *,
        native_option_price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        _require_positive(native_option_price, "native_option_price")
        self.check_quantity(quantity)
        uncapped = self.standard_option_fee_rate * quantity
        premium_cap = PREMIUM_FEE_CAP_FRACTION * native_option_price * quantity
        return min(uncapped, premium_cap)

    def native_payoff(self, payoff_usd: Decimal, *, delivery_price: Decimal) -> Decimal:
        _require_non_negative(payoff_usd, "payoff_usd")
        _require_positive(delivery_price, "delivery_price")
        return payoff_usd / delivery_price


BTC = ProductSpec(
    product_id=ProductId.INVERSE_BTC,
    public_currency="BTC",
    base_currency="BTC",
    settlement_currency="BTC",
    price_index="btc_usd",
    instrument_prefix="BTC-",
    minimum_quantity=Decimal("0.1"),
    quantity_tick=Decimal("0.1"),
    standard_option_fee_rate=Decimal("0.0003"),
    standard_delivery_fee_rate=Decimal("0.00015"),
    native_premium_currency="BTC",
)

ETH = ProductSpec(
    product_id=ProductId.INVERSE_ETH,
    public_currency="ETH",
    base_currency="ETH",
    settlement_currency="ETH",
    price_index="eth_usd",
    instrument_prefix="ETH-",
    minimum_quantity=Decimal("1"),
    quantity_tick=Decimal("1"),
    standard_option_fee_rate=Decimal("0.0003"),
    standard_delivery_fee_rate=Decimal("0.00015"),
    native_premium_currency="ETH",
)

PRODUCTS = {BTC.product_id: BTC, ETH.product_id: ETH}


def _require_finite(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")


def _require_positive(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value <= 0:
        raise ValueError(f"{field} must be positive")


def _require_non_negative(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value < 0:
        raise ValueError(f"{field} must be non-negative")

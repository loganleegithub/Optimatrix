from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

PREMIUM_FEE_CAP_FRACTION = Decimal("0.125")


class OptionProductName(StrEnum):
    INVERSE_BTC = "inverse-btc"


@dataclass(frozen=True)
class OptionProductSpec:
    """Exact public-market and monetary semantics for one BTC option product."""

    name: OptionProductName
    public_currency: str
    base_currency: str
    quote_currency: str
    settlement_currency: str
    counter_currency: str
    price_index: str
    instrument_type: str
    instrument_prefix: str
    native_premium_currency: str
    valuation_currency: str = "USD_EQUIVALENT"
    strike_currency: str = "USD"

    def __post_init__(self) -> None:
        members = (
            self.public_currency,
            self.base_currency,
            self.quote_currency,
            self.settlement_currency,
            self.counter_currency,
            self.price_index,
            self.instrument_type,
            self.instrument_prefix,
            self.native_premium_currency,
            self.valuation_currency,
            self.strike_currency,
        )
        if any(not value for value in members):
            raise ValueError("option product specification members must be non-empty")
        if self.instrument_type not in {"linear", "reversed"}:
            raise ValueError("option product instrument_type must be linear or reversed")

    @property
    def identity(self) -> str:
        payload = json.dumps(
            {
                "base_currency": self.base_currency,
                "case_schema_version": self.case_schema_version,
                "counter_currency": self.counter_currency,
                "economic_semantics_version": self.economic_semantics_version,
                "fee_rule": self.fee_rule,
                "instrument_prefix": self.instrument_prefix,
                "instrument_type": self.instrument_type,
                "market_family": self.market_family,
                "model_premium_rule": self.model_premium_rule,
                "name": self.name.value,
                "native_premium_currency": self.native_premium_currency,
                "native_settlement_payoff_rule": self.native_settlement_payoff_rule,
                "price_index": self.price_index,
                "public_currency": self.public_currency,
                "quote_currency": self.quote_currency,
                "settlement_currency": self.settlement_currency,
                "strike_currency": self.strike_currency,
                "valuation_currency": self.valuation_currency,
                "valuation_rule": self.valuation_rule,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    @property
    def option_lifecycle_channel(self) -> str:
        return f"instrument.state.option.{self.public_currency}"

    @property
    def combo_lifecycle_channel(self) -> str:
        return f"instrument.state.option_combo.{self.public_currency}"

    @property
    def index_channel(self) -> str:
        return f"deribit_price_index.{self.price_index}"

    @property
    def is_inverse(self) -> bool:
        return self.instrument_type == "reversed"

    @property
    def market_family(self) -> str:
        return "DERIBIT_BTC_OPTIONS"

    @property
    def economic_semantics_version(self) -> str:
        if self.is_inverse:
            return "INVERSE_BTC_V1"
        return f"{self.name.value.upper().replace('-', '_')}_V1"

    @property
    def case_schema_version(self) -> int:
        return 5

    @property
    def model_premium_rule(self) -> str:
        if self.is_inverse:
            return "NATIVE_BTC_PREMIUM_TIMES_FORWARD"
        return "NATIVE_PREMIUM_ONE_FOR_ONE"

    @property
    def valuation_rule(self) -> str:
        if self.is_inverse:
            return "NATIVE_BTC_AMOUNT_TIMES_CAUSAL_BTC_USD_INDEX"
        return "NATIVE_AMOUNT_ONE_FOR_ONE"

    @property
    def fee_rule(self) -> str:
        if self.is_inverse:
            return "MIN_BASE_RATE_OR_12_5_PERCENT_NATIVE_PREMIUM_IN_BTC"
        return "MIN_INDEX_RATE_OR_12_5_PERCENT_NATIVE_PREMIUM"

    @property
    def native_settlement_payoff_rule(self) -> str:
        if self.is_inverse:
            return "USD_STRIKE_PAYOFF_DIVIDED_BY_EXPIRY_DELIVERY_PRICE"
        return "STRIKE_CURRENCY_PAYOFF_SETTLED_ONE_FOR_ONE"

    @property
    def native_settlement_liability_profile(self) -> str:
        if self.is_inverse:
            return "SETTLEMENT_PRICE_DEPENDENT_RECIPROCAL_BTC_LIABILITY"
        return "FIXED_IN_NATIVE_SETTLEMENT_CURRENCY"

    @property
    def actual_account_margin_availability(self) -> str:
        return "UNKNOWN"

    @property
    def actual_account_margin_reason(self) -> str:
        return "ACCOUNT_MARGIN_UNKNOWN"

    def matches_component_contract(
        self,
        *,
        product_spec_identity: str,
        product_name: str,
        native_premium_currency: str,
        settlement_currency: str,
        price_index: str,
        valuation_currency: str,
    ) -> bool:
        """Validate the complete product projection consumed by downstream owners."""
        return (
            product_spec_identity == self.identity
            and product_name == self.name.value
            and native_premium_currency == self.native_premium_currency
            and settlement_currency == self.settlement_currency
            and price_index == self.price_index
            and valuation_currency == self.valuation_currency
        )

    def product_fields(self, *, kind: str) -> dict[str, str]:
        if kind not in {"option", "option_combo"}:
            raise ValueError("option product kind must be option or option_combo")
        return {
            "kind": kind,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "settlement_currency": self.settlement_currency,
            "counter_currency": self.counter_currency,
            "price_index": self.price_index,
            "instrument_type": self.instrument_type,
        }

    def combo_product_fields(self) -> dict[str, str]:
        fields = self.product_fields(kind="option_combo")
        fields.pop("price_index")
        return fields

    def matches_instrument_name(self, instrument_name: str) -> bool:
        return instrument_name.startswith(self.instrument_prefix)

    def model_premium(self, native_premium: Decimal, *, forward_price: Decimal) -> Decimal:
        """Convert a native premium to the strike-currency Black formula domain."""
        _require_non_negative(native_premium, "native_premium")
        _require_positive(forward_price, "forward_price")
        if self.is_inverse:
            return native_premium * forward_price
        return native_premium

    def valuation(self, native_amount: Decimal, *, index_price: Decimal) -> Decimal:
        """Value a native cash amount at one causal BTC index boundary."""
        _require_finite(native_amount, "native_amount")
        _require_positive(index_price, "index_price")
        if self.native_premium_currency == self.base_currency:
            return native_amount * index_price
        return native_amount

    def native_option_fee(
        self,
        *,
        native_option_price: Decimal,
        index_price: Decimal,
        quantity_btc: Decimal,
        fee_rate: Decimal,
    ) -> Decimal:
        """Return the standard taker fee in the product's native settlement currency."""
        _require_positive(native_option_price, "native_option_price")
        _require_positive(index_price, "index_price")
        _require_positive(quantity_btc, "quantity_btc")
        _require_non_negative(fee_rate, "fee_rate")
        if self.is_inverse:
            index_fee = fee_rate * quantity_btc
        else:
            index_fee = fee_rate * index_price * quantity_btc
        premium_cap = PREMIUM_FEE_CAP_FRACTION * native_option_price * quantity_btc
        return min(index_fee, premium_cap)

    def native_payoff_from_strike_value(
        self,
        payoff_in_strike_currency: Decimal,
        *,
        settlement_price: Decimal,
    ) -> Decimal:
        """Convert contractual USD payoff to native settlement currency at expiry."""
        _require_non_negative(payoff_in_strike_currency, "payoff_in_strike_currency")
        _require_positive(settlement_price, "settlement_price")
        if self.is_inverse:
            return payoff_in_strike_currency / settlement_price
        return payoff_in_strike_currency


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


INVERSE_BTC = OptionProductSpec(
    name=OptionProductName.INVERSE_BTC,
    public_currency="BTC",
    base_currency="BTC",
    quote_currency="BTC",
    settlement_currency="BTC",
    counter_currency="USD",
    price_index="btc_usd",
    instrument_type="reversed",
    instrument_prefix="BTC-",
    native_premium_currency="BTC",
)

PRODUCT_SPECS = {
    INVERSE_BTC.name: INVERSE_BTC,
}


def product_for_name(value: OptionProductName | str) -> OptionProductSpec:
    try:
        name = value if isinstance(value, OptionProductName) else OptionProductName(value)
    except ValueError as exc:
        raise ValueError(f"unsupported option product: {value}") from exc
    return PRODUCT_SPECS[name]


def product_for_identity(identity: str) -> OptionProductSpec:
    for product in PRODUCT_SPECS.values():
        if product.identity == identity:
            return product
    raise ValueError(f"unsupported option product identity: {identity}")

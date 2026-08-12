from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from short_vol_underwriting.admission import RpcRequestIntent
from short_vol_underwriting.domain import DELIVERY_FEE_PAYOFF_CAP_FRACTION
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary

DELIVERY_PRICE_INDEX_NAME = "btc_usd"
DELIVERY_PRICE_REQUEST_PARAMS = MappingProxyType(
    {"index_name": DELIVERY_PRICE_INDEX_NAME, "offset": 0, "count": 1000}
)
DAILY_OPTION_DELIVERY_FEE_RATE = Decimal(0)
STANDARD_OPTION_DELIVERY_FEE_RATE = Decimal("0.00015")
SETTLEMENT_PRICE_RETRY_INTERVAL_MS = 30_000


def delivery_date_for_expiry(expiry_ms: int) -> str:
    if isinstance(expiry_ms, bool) or not isinstance(expiry_ms, int) or expiry_ms <= 0:
        raise ValueError("expiry_ms must be a positive integer")
    return datetime.fromtimestamp(expiry_ms / 1000, tz=UTC).date().isoformat()


def deribit_option_delivery_fee_rate(expiry_ms: int) -> Decimal:
    """Return the public standard fee rate for the expiry class.

    The monitored 0-3 DTE surface has one BTC option series per date. Non-Friday
    dates are daily expiries and fee-exempt; Friday series are weekly/monthly/
    quarterly options and use the standard option delivery rate.
    """

    expiry = datetime.fromtimestamp(expiry_ms / 1000, tz=UTC)
    return (
        STANDARD_OPTION_DELIVERY_FEE_RATE
        if expiry.weekday() == 4
        else DAILY_OPTION_DELIVERY_FEE_RATE
    )


def contract_settlement_rule_identity(
    *,
    product_spec_identity: str,
    expiry_ms: int,
) -> str:
    """Bind the exact public Inverse payoff and delivery-fee convention."""

    require_identity(product_spec_identity, "product_spec_identity")
    fee_rate = deribit_option_delivery_fee_rate(expiry_ms)
    fee_class = "STANDARD_FRIDAY_EXPIRY" if fee_rate else "DAILY_FEE_EXEMPT_EXPIRY"
    return canonical_identity(
        "ContractSettlementRuleIdentityV1",
        product_spec_identity,
        DELIVERY_PRICE_INDEX_NAME,
        "EUROPEAN_AUTOMATIC_CASH_SETTLEMENT",
        "USD_INTRINSIC_DIVIDED_BY_DELIVERY_PRICE_TO_NATIVE_BTC",
        "SIGNED_SHORT_LONG_VERTICAL_PAYOFF",
        fee_class,
        fee_rate,
        DELIVERY_FEE_PAYOFF_CAP_FRACTION,
    )


@dataclass(frozen=True)
class DeliveryPriceWitness:
    """One validated date/price member of an official history response."""

    source_identity: str
    response_source_identity: str
    boundary: FactBoundary
    index_name: str
    delivery_date: str
    delivery_price_usdc_per_btc: Decimal
    request_id: int
    owner_origin_boundary: FactBoundary
    sent_boundary: FactBoundary
    records_total: int

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")
        require_identity(self.response_source_identity, "response_source_identity")
        _validate_delivery_response_boundaries(
            owner_origin_boundary=self.owner_origin_boundary,
            sent_boundary=self.sent_boundary,
            receipt_boundary=self.boundary,
        )
        if self.index_name != DELIVERY_PRICE_INDEX_NAME:
            raise ValueError("delivery price index_name is outside the fixed product")
        try:
            parsed_date = datetime.strptime(self.delivery_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("delivery_date must be YYYY-MM-DD") from exc
        if parsed_date.isoformat() != self.delivery_date:
            raise ValueError("delivery_date must be canonical YYYY-MM-DD")
        if (
            not isinstance(self.delivery_price_usdc_per_btc, Decimal)
            or not self.delivery_price_usdc_per_btc.is_finite()
            or self.delivery_price_usdc_per_btc <= 0
        ):
            raise ValueError("delivery price must be a finite positive Decimal")
        for value, field in (
            (self.request_id, "request_id"),
            (self.records_total, "records_total"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.request_id == 0:
            raise ValueError("request_id must be positive")
        if self.records_total == 0:
            raise ValueError("a delivery member requires a positive records_total")
        expected_response = canonical_identity(
            "OfficialDeliveryPriceResponseSourceIdentity",
            self.boundary.runtime_identity,
            self.request_id,
            "public/get_delivery_prices",
            dict(DELIVERY_PRICE_REQUEST_PARAMS),
            self.index_name,
            self.records_total,
            self.owner_origin_boundary.as_object(),
            self.sent_boundary.as_object(),
            self.boundary.as_object(),
        )
        if self.response_source_identity != expected_response:
            raise ValueError("official delivery-price response identity mismatch")
        expected = canonical_identity(
            "OfficialDeliveryPriceMemberSourceIdentity",
            self.response_source_identity,
            self.delivery_date,
            self.delivery_price_usdc_per_btc,
        )
        if self.source_identity != expected:
            raise ValueError("official delivery-price member identity mismatch")

    def as_ref(self) -> dict[str, object]:
        return {
            "source_identity": self.source_identity,
            "response_source_identity": self.response_source_identity,
            "receipt_fact_boundary": self.boundary.as_object(),
            "request_id": self.request_id,
            "index_name": self.index_name,
            "delivery_date": self.delivery_date,
            "records_total": self.records_total,
            "owner_origin_boundary": self.owner_origin_boundary.as_object(),
            "sent_boundary": self.sent_boundary.as_object(),
        }


@dataclass(frozen=True)
class DeliveryPriceResponseWitness:
    """One accepted response envelope, independent of any request-owner expiry date."""

    source_identity: str
    boundary: FactBoundary
    index_name: str
    request_id: int
    owner_origin_boundary: FactBoundary
    sent_boundary: FactBoundary
    records_total: int
    members: tuple[DeliveryPriceWitness, ...]

    @classmethod
    def create(
        cls,
        *,
        boundary: FactBoundary,
        request_id: int,
        owner_origin_boundary: FactBoundary,
        sent_boundary: FactBoundary,
        records_total: int,
        members: tuple[tuple[str, Decimal], ...],
    ) -> DeliveryPriceResponseWitness:
        response_identity = canonical_identity(
            "OfficialDeliveryPriceResponseSourceIdentity",
            boundary.runtime_identity,
            request_id,
            "public/get_delivery_prices",
            dict(DELIVERY_PRICE_REQUEST_PARAMS),
            DELIVERY_PRICE_INDEX_NAME,
            records_total,
            owner_origin_boundary.as_object(),
            sent_boundary.as_object(),
            boundary.as_object(),
        )
        witnesses = tuple(
            DeliveryPriceWitness(
                source_identity=canonical_identity(
                    "OfficialDeliveryPriceMemberSourceIdentity",
                    response_identity,
                    delivery_date,
                    delivery_price,
                ),
                response_source_identity=response_identity,
                boundary=boundary,
                index_name=DELIVERY_PRICE_INDEX_NAME,
                delivery_date=delivery_date,
                delivery_price_usdc_per_btc=delivery_price,
                request_id=request_id,
                owner_origin_boundary=owner_origin_boundary,
                sent_boundary=sent_boundary,
                records_total=records_total,
            )
            for delivery_date, delivery_price in members
        )
        return cls(
            source_identity=response_identity,
            boundary=boundary,
            index_name=DELIVERY_PRICE_INDEX_NAME,
            request_id=request_id,
            owner_origin_boundary=owner_origin_boundary,
            sent_boundary=sent_boundary,
            records_total=records_total,
            members=witnesses,
        )

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")
        _validate_delivery_response_boundaries(
            owner_origin_boundary=self.owner_origin_boundary,
            sent_boundary=self.sent_boundary,
            receipt_boundary=self.boundary,
        )
        if self.index_name != DELIVERY_PRICE_INDEX_NAME:
            raise ValueError("delivery response index_name is outside the fixed product")
        for value, field in (
            (self.request_id, "request_id"),
            (self.records_total, "records_total"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.request_id == 0:
            raise ValueError("request_id must be positive")
        expected = canonical_identity(
            "OfficialDeliveryPriceResponseSourceIdentity",
            self.boundary.runtime_identity,
            self.request_id,
            "public/get_delivery_prices",
            dict(DELIVERY_PRICE_REQUEST_PARAMS),
            self.index_name,
            self.records_total,
            self.owner_origin_boundary.as_object(),
            self.sent_boundary.as_object(),
            self.boundary.as_object(),
        )
        if self.source_identity != expected:
            raise ValueError("official delivery response source identity mismatch")
        dates = tuple(member.delivery_date for member in self.members)
        if len(dates) != len(set(dates)):
            raise ValueError("official delivery response contains duplicate dates")
        if self.records_total < len(self.members):
            raise ValueError("official delivery response member count exceeds records_total")
        for member in self.members:
            if (
                member.response_source_identity != self.source_identity
                or member.boundary != self.boundary
                or member.index_name != self.index_name
                or member.request_id != self.request_id
                or member.owner_origin_boundary != self.owner_origin_boundary
                or member.sent_boundary != self.sent_boundary
                or member.records_total != self.records_total
            ):
                raise ValueError("delivery response member does not share its envelope")


def _validate_delivery_response_boundaries(
    *,
    owner_origin_boundary: FactBoundary,
    sent_boundary: FactBoundary,
    receipt_boundary: FactBoundary,
) -> None:
    if not (
        owner_origin_boundary.session_epoch
        == sent_boundary.session_epoch
        == receipt_boundary.session_epoch
    ):
        raise ValueError("delivery response crosses a session boundary")
    try:
        sent_after_origin = sent_boundary.is_strictly_after(owner_origin_boundary)
        receipt_after_sent = receipt_boundary.is_strictly_after(sent_boundary)
    except ValueError as exc:
        raise ValueError("delivery response boundary binding mismatch") from exc
    if not sent_after_origin or not receipt_after_sent:
        raise ValueError("delivery response boundaries are not strictly causal")


@dataclass
class SettlementPriceAttempt:
    anchor_identity: str
    expected_delivery_date: str
    request_id: int
    origin_boundary: FactBoundary
    scheduled_identity: str
    _intent_taken: bool = False
    sent_boundary: FactBoundary | None = None

    @classmethod
    def schedule(
        cls,
        *,
        anchor_identity: str,
        expiry_ms: int,
        request_id: int,
        boundary: FactBoundary,
    ) -> SettlementPriceAttempt:
        require_identity(anchor_identity, "anchor_identity")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id <= 0:
            raise ValueError("request_id must be positive")
        delivery_date = delivery_date_for_expiry(expiry_ms)
        scheduled = canonical_identity(
            "ScheduledSettlementPriceAttemptIdentity",
            anchor_identity,
            delivery_date,
            request_id,
            "public/get_delivery_prices",
            dict(DELIVERY_PRICE_REQUEST_PARAMS),
            boundary.as_object(),
        )
        return cls(
            anchor_identity=anchor_identity,
            expected_delivery_date=delivery_date,
            request_id=request_id,
            origin_boundary=boundary,
            scheduled_identity=scheduled,
        )

    def take_request_intent(self) -> RpcRequestIntent | None:
        if self._intent_taken:
            return None
        self._intent_taken = True
        return RpcRequestIntent(
            request_id=self.request_id,
            purpose="SETTLEMENT_PRICE",
            method="public/get_delivery_prices",
            params=DELIVERY_PRICE_REQUEST_PARAMS,
            scheduled_identity=self.scheduled_identity,
            origin_boundary=self.origin_boundary,
            owner_identity=self.anchor_identity,
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        if request_id != self.request_id or self.sent_boundary is not None:
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("settlement request send must be strictly after schedule")
        if boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms > (
            send_budget_ms
        ):
            return False
        self.sent_boundary = boundary
        return True

    def accepts_response(
        self,
        witness: DeliveryPriceResponseWitness,
        *,
        response_budget_ms: int,
    ) -> bool:
        if not self.owns_response(witness):
            return False
        sent = self.sent_boundary
        assert sent is not None
        return (
            witness.boundary.received_monotonic_ms - sent.received_monotonic_ms
            <= response_budget_ms
        )

    def owns_response(self, witness: DeliveryPriceResponseWitness) -> bool:
        sent = self.sent_boundary
        return (
            sent is not None
            and witness.request_id == self.request_id
            and witness.owner_origin_boundary == self.origin_boundary
            and witness.sent_boundary == sent
            and witness.boundary.is_strictly_after(sent)
        )

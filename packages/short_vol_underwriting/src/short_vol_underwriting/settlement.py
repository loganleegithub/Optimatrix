from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from short_vol_underwriting.admission import RpcRequestIntent
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary

DELIVERY_PRICE_INDEX_NAME = "btc_usd"
DELIVERY_PRICE_REQUEST_PARAMS = MappingProxyType(
    {"index_name": DELIVERY_PRICE_INDEX_NAME, "offset": 0, "count": 1000}
)
DAILY_OPTION_DELIVERY_FEE_RATE = Decimal(0)
STANDARD_OPTION_DELIVERY_FEE_RATE = Decimal("0.00015")


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


@dataclass(frozen=True)
class DeliveryPriceWitness:
    source_identity: str
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
        expected = canonical_identity(
            "OfficialDeliveryPriceSourceIdentity",
            self.boundary.runtime_identity,
            self.request_id,
            "public/get_delivery_prices",
            dict(DELIVERY_PRICE_REQUEST_PARAMS),
            self.index_name,
            self.delivery_date,
            self.delivery_price_usdc_per_btc,
            self.records_total,
            self.owner_origin_boundary.as_object(),
            self.sent_boundary.as_object(),
            self.boundary.as_object(),
        )
        if self.source_identity != expected:
            raise ValueError("official delivery-price source identity mismatch")

    def as_ref(self) -> dict[str, object]:
        return {
            "source_identity": self.source_identity,
            "receipt_fact_boundary": self.boundary.as_object(),
            "request_id": self.request_id,
            "index_name": self.index_name,
            "delivery_date": self.delivery_date,
            "records_total": self.records_total,
        }


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

    def accepts(
        self,
        witness: DeliveryPriceWitness,
        *,
        response_budget_ms: int,
    ) -> bool:
        sent = self.sent_boundary
        if (
            sent is None
            or witness.request_id != self.request_id
            or witness.owner_origin_boundary != self.origin_boundary
            or witness.sent_boundary != sent
            or witness.delivery_date != self.expected_delivery_date
            or not witness.boundary.is_strictly_after(sent)
        ):
            return False
        return (
            witness.boundary.received_monotonic_ms - sent.received_monotonic_ms
            <= response_budget_ms
        )

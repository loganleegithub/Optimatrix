from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from optimatrix.identity import canonical_identity, canonical_value, require_identity
from optimatrix.market import OptionQuote
from optimatrix.pricing import Action, Btc0DteCondorPricing

COMPONENT_SYNTHETIC_MODEL_ID = "SYNTHETIC_FOUR_LEG_COMPONENT_BOOK_ESTIMATE_V1"


class RouteEvidenceKind(StrEnum):
    COMPONENT_SYNTHETIC_ESTIMATE = "COMPONENT_SYNTHETIC_ESTIMATE"
    COMBO_BOOK_QUOTE = "COMBO_BOOK_QUOTE"
    RFQ = "RFQ"
    ACTUAL_FILL = "ACTUAL_FILL"


class RouteEvidenceStatus(StrEnum):
    EVALUABLE = "EVALUABLE"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    UNKNOWN = "UNKNOWN"


class RouteLegRole(StrEnum):
    LONG_PUT = "LONG_PUT"
    SHORT_PUT = "SHORT_PUT"
    SHORT_CALL = "SHORT_CALL"
    LONG_CALL = "LONG_CALL"


@dataclass(frozen=True)
class ShadowRouteLeg:
    role: RouteLegRole
    instrument_name: str
    action: Action
    ratio: Decimal
    requested_amount: Decimal
    available_amount: Decimal | None
    depth_coverage: Decimal | None

    def __post_init__(self) -> None:
        if not self.instrument_name:
            raise ValueError("route leg instrument must be non-empty")
        for value, field in (
            (self.ratio, "ratio"),
            (self.requested_amount, "requested_amount"),
        ):
            if not value.is_finite() or value == 0:
                raise ValueError(f"route leg {field} must be finite and nonzero")
        if self.requested_amount <= 0:
            raise ValueError("route leg requested amount must be positive")
        if (self.available_amount is None) != (self.depth_coverage is None):
            raise ValueError("route leg availability and coverage must appear together")
        if self.available_amount is not None:
            if not self.available_amount.is_finite() or self.available_amount < 0:
                raise ValueError("route leg available amount must be finite and non-negative")
            assert self.depth_coverage is not None
            expected_coverage = min(Decimal(1), self.available_amount / self.requested_amount)
            if self.depth_coverage != expected_coverage:
                raise ValueError("route leg depth coverage is incoherent")

    def as_object(self) -> dict[str, object]:
        value = canonical_value(self)
        if not isinstance(value, dict):
            raise TypeError("canonical route leg must be an object")
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "route_leg")
        _require_exact_fields(
            item,
            {
                "role",
                "instrument_name",
                "action",
                "ratio",
                "requested_amount",
                "available_amount",
                "depth_coverage",
            },
            "route_leg",
        )
        return cls(
            role=RouteLegRole(_text(item, "role")),
            instrument_name=_text(item, "instrument_name"),
            action=Action(_text(item, "action")),
            ratio=_decimal(item, "ratio"),
            requested_amount=_decimal(item, "requested_amount"),
            available_amount=_optional_decimal(item, "available_amount"),
            depth_coverage=_optional_decimal(item, "depth_coverage"),
        )


@dataclass(frozen=True)
class ShadowRouteEvidence:
    kind: RouteEvidenceKind
    status: RouteEvidenceStatus
    reason: str | None
    policy_id: str
    selected_structure_id: str
    observation_id: str | None
    observed_at: datetime | None
    observation_known_at: datetime | None
    evaluated_at: datetime
    model_id: str
    target_amount: Decimal
    legs: tuple[ShadowRouteLeg, ShadowRouteLeg, ShadowRouteLeg, ShadowRouteLeg]
    fee_model_id: str | None
    native_gross_credit: Decimal | None
    standard_combo_fee_projection_native: Decimal | None
    native_net_credit: Decimal | None
    boundary_index_price_usd: Decimal | None
    boundary_net_credit_usd: Decimal | None

    def __post_init__(self) -> None:
        if self.kind is not RouteEvidenceKind.COMPONENT_SYNTHETIC_ESTIMATE:
            raise ValueError("B3 Public Shadow only accepts component synthetic route evidence")
        if self.model_id != COMPONENT_SYNTHETIC_MODEL_ID:
            raise ValueError("B3 route evidence has an unsupported component model")
        require_identity(self.policy_id, "policy_id")
        require_identity(self.selected_structure_id, "selected_structure_id")
        evaluated_at = _utc(self.evaluated_at, "evaluated_at")
        if not self.target_amount.is_finite() or self.target_amount <= 0:
            raise ValueError("route target amount must be finite and positive")
        if len({leg.instrument_name for leg in self.legs}) != 4:
            raise ValueError("route evidence requires four distinct instruments")
        expected_legs = (
            (RouteLegRole.LONG_PUT, Action.BUY, Decimal(1)),
            (RouteLegRole.SHORT_PUT, Action.SELL, Decimal(-1)),
            (RouteLegRole.SHORT_CALL, Action.SELL, Decimal(-1)),
            (RouteLegRole.LONG_CALL, Action.BUY, Decimal(1)),
        )
        for leg, (role, action, ratio) in zip(self.legs, expected_legs, strict=True):
            if (leg.role, leg.action, leg.ratio) != (role, action, ratio):
                raise ValueError("route evidence leg roles, actions, and ratios are invalid")
            if leg.requested_amount != self.target_amount * abs(leg.ratio):
                raise ValueError("route evidence leg amount does not match the full target ratio")

        boundaries = (self.observation_id, self.observed_at, self.observation_known_at)
        if any(value is None for value in boundaries) and any(
            value is not None for value in boundaries
        ):
            raise ValueError("route observation identity and boundaries must appear together")
        if self.observation_id is not None:
            require_identity(self.observation_id, "observation_id")
            assert self.observed_at is not None and self.observation_known_at is not None
            observed_at = _utc(self.observed_at, "observed_at")
            observation_known_at = _utc(self.observation_known_at, "observation_known_at")
            if observed_at > observation_known_at or observation_known_at > evaluated_at:
                raise ValueError("route evidence causal boundaries are invalid")

        economics = (
            self.fee_model_id,
            self.native_gross_credit,
            self.standard_combo_fee_projection_native,
            self.native_net_credit,
            self.boundary_index_price_usd,
            self.boundary_net_credit_usd,
        )
        availability_known = all(leg.available_amount is not None for leg in self.legs)
        if self.status is RouteEvidenceStatus.UNKNOWN:
            if not self.reason:
                raise ValueError("unknown route evidence requires a reason")
            if availability_known or any(value is not None for value in economics):
                raise ValueError("unknown route evidence cannot invent depth or economics")
        elif self.status is RouteEvidenceStatus.NOT_EVALUABLE:
            if self.observation_id is None or not self.reason or not availability_known:
                raise ValueError("not-evaluable route requires complete causal depth and a reason")
            if any(value is not None for value in economics):
                raise ValueError("not-evaluable route cannot invent whole-product economics")
        else:
            if self.observation_id is None or self.reason is not None or not availability_known:
                raise ValueError("evaluable route requires complete causal blocker-free depth")
            if any(leg.depth_coverage != 1 for leg in self.legs):
                raise ValueError("evaluable route requires full target amount on every component")
            if any(value is None for value in economics):
                raise ValueError("evaluable route requires complete synthetic economics")
            assert self.fee_model_id is not None
            assert self.native_gross_credit is not None
            assert self.standard_combo_fee_projection_native is not None
            assert self.native_net_credit is not None
            assert self.boundary_index_price_usd is not None
            assert self.boundary_net_credit_usd is not None
            require_identity(self.fee_model_id, "fee_model_id")
            numeric = (
                self.native_gross_credit,
                self.standard_combo_fee_projection_native,
                self.native_net_credit,
                self.boundary_index_price_usd,
                self.boundary_net_credit_usd,
            )
            if any(not value.is_finite() or value < 0 for value in numeric):
                raise ValueError("route evidence economics must be finite and non-negative")
            if self.native_gross_credit <= 0 or self.native_net_credit <= 0:
                raise ValueError("evaluable route requires positive gross and net credit")
            if self.boundary_index_price_usd <= 0:
                raise ValueError("evaluable route requires a positive boundary index")
            if (
                self.native_gross_credit - self.standard_combo_fee_projection_native
                != self.native_net_credit
            ):
                raise ValueError("route evidence fee projection is incoherent")
            if (
                self.native_net_credit * self.boundary_index_price_usd
                != self.boundary_net_credit_usd
            ):
                raise ValueError("route evidence boundary conversion is incoherent")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowRouteEvidenceV1", self)

    def as_object(self) -> dict[str, object]:
        value = canonical_value(self)
        if not isinstance(value, dict):
            raise TypeError("canonical route evidence must be an object")
        value["route_evidence_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "route_evidence")
        _require_exact_fields(
            item,
            {
                "route_evidence_id",
                "kind",
                "status",
                "reason",
                "policy_id",
                "selected_structure_id",
                "observation_id",
                "observed_at",
                "observation_known_at",
                "evaluated_at",
                "model_id",
                "target_amount",
                "legs",
                "fee_model_id",
                "native_gross_credit",
                "standard_combo_fee_projection_native",
                "native_net_credit",
                "boundary_index_price_usd",
                "boundary_net_credit_usd",
            },
            "route_evidence",
        )
        encoded_legs = item.get("legs")
        if not isinstance(encoded_legs, list) or len(encoded_legs) != 4:
            raise ValueError("route_evidence.legs must contain exactly four legs")
        result = cls(
            kind=RouteEvidenceKind(_text(item, "kind")),
            status=RouteEvidenceStatus(_text(item, "status")),
            reason=_optional_text(item, "reason"),
            policy_id=_text(item, "policy_id"),
            selected_structure_id=_text(item, "selected_structure_id"),
            observation_id=_optional_text(item, "observation_id"),
            observed_at=_optional_datetime(item, "observed_at"),
            observation_known_at=_optional_datetime(item, "observation_known_at"),
            evaluated_at=_datetime(item, "evaluated_at"),
            model_id=_text(item, "model_id"),
            target_amount=_decimal(item, "target_amount"),
            legs=tuple(ShadowRouteLeg.from_object(member) for member in encoded_legs),  # type: ignore[arg-type]
            fee_model_id=_optional_text(item, "fee_model_id"),
            native_gross_credit=_optional_decimal(item, "native_gross_credit"),
            standard_combo_fee_projection_native=_optional_decimal(
                item,
                "standard_combo_fee_projection_native",
            ),
            native_net_credit=_optional_decimal(item, "native_net_credit"),
            boundary_index_price_usd=_optional_decimal(item, "boundary_index_price_usd"),
            boundary_net_credit_usd=_optional_decimal(item, "boundary_net_credit_usd"),
        )
        if _text(item, "route_evidence_id") != result.identity:
            raise ValueError("route evidence identity mismatch")
        return result


def component_synthetic_route_evidence(
    *,
    policy_id: str,
    selected_structure_id: str,
    evaluated_at: datetime,
    target_amount: Decimal,
    instrument_names: tuple[str, str, str, str],
    observation_id: str | None,
    observed_at: datetime | None,
    observation_known_at: datetime | None,
    quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None,
    pricing: Btc0DteCondorPricing | None,
    unknown_reason: str | None = None,
) -> ShadowRouteEvidence:
    reason: str | None
    if unknown_reason is not None:
        status = RouteEvidenceStatus.UNKNOWN
        reason = unknown_reason
        availability: tuple[tuple[Decimal | None, Decimal | None], ...] = ((None, None),) * 4
    else:
        if quotes is None:
            raise ValueError("known component route evidence requires four quotes")
        if tuple(quote.instrument_name for quote in quotes) != instrument_names:
            raise ValueError("component route quotes do not match the frozen instruments")
        availability = tuple(
            _availability(quote, action=action, requested_amount=target_amount)
            for quote, action in zip(
                quotes,
                (Action.BUY, Action.SELL, Action.SELL, Action.BUY),
                strict=True,
            )
        )
        status = (
            RouteEvidenceStatus.EVALUABLE
            if pricing is not None
            else RouteEvidenceStatus.NOT_EVALUABLE
        )
        reason = None if pricing is not None else "FULL_TARGET_COMPONENT_ESTIMATE_UNAVAILABLE"
    roles = (
        RouteLegRole.LONG_PUT,
        RouteLegRole.SHORT_PUT,
        RouteLegRole.SHORT_CALL,
        RouteLegRole.LONG_CALL,
    )
    actions = (Action.BUY, Action.SELL, Action.SELL, Action.BUY)
    ratios = (Decimal(1), Decimal(-1), Decimal(-1), Decimal(1))
    legs = tuple(
        ShadowRouteLeg(
            role=role,
            instrument_name=instrument_name,
            action=action,
            ratio=ratio,
            requested_amount=target_amount,
            available_amount=available,
            depth_coverage=coverage,
        )
        for role, instrument_name, action, ratio, (available, coverage) in zip(
            roles,
            instrument_names,
            actions,
            ratios,
            availability,
            strict=True,
        )
    )
    return ShadowRouteEvidence(
        kind=RouteEvidenceKind.COMPONENT_SYNTHETIC_ESTIMATE,
        status=status,
        reason=reason,
        policy_id=policy_id,
        selected_structure_id=selected_structure_id,
        observation_id=observation_id,
        observed_at=observed_at,
        observation_known_at=observation_known_at,
        evaluated_at=evaluated_at,
        model_id=COMPONENT_SYNTHETIC_MODEL_ID,
        target_amount=target_amount,
        legs=legs,  # type: ignore[arg-type]
        fee_model_id=pricing.fee_model_id if pricing is not None else None,
        native_gross_credit=pricing.native_gross_credit if pricing is not None else None,
        standard_combo_fee_projection_native=(
            pricing.combo_standard_fee_native if pricing is not None else None
        ),
        native_net_credit=pricing.native_net_credit if pricing is not None else None,
        boundary_index_price_usd=(
            pricing.boundary_index_price_usd if pricing is not None else None
        ),
        boundary_net_credit_usd=(pricing.boundary_net_credit_usd if pricing is not None else None),
    )


def _availability(
    quote: OptionQuote,
    *,
    action: Action,
    requested_amount: Decimal,
) -> tuple[Decimal, Decimal]:
    levels = quote.ask if action is Action.BUY else quote.bid
    available = sum((level.quantity for level in levels), Decimal(0))
    return available, min(Decimal(1), available / requested_amount)


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _require_exact_fields(
    item: dict[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(item) != expected:
        raise ValueError(f"{field} fields do not match the B3 component route schema")


def _text(item: dict[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text")
    return value


def _optional_text(item: dict[str, object], field: str) -> str | None:
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be non-empty text or null")
    return value


def _decimal(item: dict[str, object], field: str) -> Decimal:
    value = item.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be decimal text")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be decimal text") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _optional_decimal(item: dict[str, object], field: str) -> Decimal | None:
    return None if item.get(field) is None else _decimal(item, field)


def _datetime(item: dict[str, object], field: str) -> datetime:
    value = _text(item, field)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO datetime") from exc
    return _utc(result, field)


def _optional_datetime(item: dict[str, object], field: str) -> datetime | None:
    return None if item.get(field) is None else _datetime(item, field)


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)

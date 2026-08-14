from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.channels import ChannelId
from optimatrix.identity import canonical_identity
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import intrinsic_payoff_usd
from optimatrix.structure import Btc0DteCondorCandidate

SHADOW_STRESS_BUDGET_METRIC = "MAX_OF_CONTRACTUAL_PAYOFF_EXIT_AND_DELIVERY_STRESS_USD_SUM"


class AllocationResult(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ShadowCapacity:
    channel_id: ChannelId
    market_session_id: str
    stress_reserve_used_usd: Decimal
    open_position_count: int
    known_at: datetime

    @classmethod
    def empty(
        cls,
        *,
        channel_id: ChannelId,
        market_session_id: str,
        known_at: datetime,
    ) -> ShadowCapacity:
        return cls(channel_id, market_session_id, Decimal(0), 0, known_at)

    def __post_init__(self) -> None:
        if not self.market_session_id:
            raise ValueError("market_session_id must be non-empty")
        if not self.stress_reserve_used_usd.is_finite() or self.stress_reserve_used_usd < 0:
            raise ValueError("used Shadow stress reserve must be finite and non-negative")
        if self.open_position_count < 0:
            raise ValueError("open_position_count must be non-negative")
        if self.known_at.tzinfo is None:
            raise ValueError("ShadowCapacity known_at must be timezone-aware")


@dataclass(frozen=True)
class DeliveryStress:
    delivery_price_usd: Decimal
    contractual_payoff_usd: Decimal
    contractual_payoff_native: Decimal
    projected_loss_native: Decimal
    delivery_valued_loss_usd: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.delivery_price_usd,
            self.contractual_payoff_usd,
            self.contractual_payoff_native,
            self.projected_loss_native,
            self.delivery_valued_loss_usd,
        ):
            if not value.is_finite() or value < 0:
                raise ValueError("delivery stress values must be finite and non-negative")
        if self.delivery_price_usd == 0:
            raise ValueError("delivery stress price must be positive")


@dataclass(frozen=True)
class ShadowRiskAllocation:
    result: AllocationResult
    channel_id: ChannelId
    market_session_id: str
    policy_id: str
    candidate_id: str
    known_at: datetime
    budget_metric: str
    option_amount: Decimal
    maximum_contractual_payoff_usd: Decimal
    entry_premium_native: Decimal
    combo_fee_native: Decimal
    boundary_index_price_usd: Decimal
    exit_cost_stress_native: Decimal
    exit_cost_stress_usd: Decimal
    delivery_stress: tuple[DeliveryStress, ...]
    maximum_delivery_stress_usd: Decimal
    stress_reserve_usd: Decimal
    session_budget_usd: Decimal
    session_used_before_usd: Decimal | None
    session_remaining_after_usd: Decimal | None
    concurrent_position_limit: int
    open_position_count_before: int | None
    expires_at: datetime
    release_condition: str
    reason: str | None

    def __post_init__(self) -> None:
        if not self.market_session_id or not self.budget_metric or not self.release_condition:
            raise ValueError("risk allocation text fields must be non-empty")
        if self.known_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("risk allocation boundaries must be timezone-aware")
        if self.known_at >= self.expires_at:
            raise ValueError("risk allocation must expire after its known-at boundary")
        if self.result is AllocationResult.AVAILABLE and self.reason is not None:
            raise ValueError("available risk allocation cannot have a blocker")
        if self.result is not AllocationResult.AVAILABLE and not self.reason:
            raise ValueError("unavailable or unknown risk allocation requires a blocker")
        for value in (
            self.option_amount,
            self.maximum_contractual_payoff_usd,
            self.entry_premium_native,
            self.combo_fee_native,
            self.boundary_index_price_usd,
            self.exit_cost_stress_native,
            self.exit_cost_stress_usd,
            self.maximum_delivery_stress_usd,
            self.stress_reserve_usd,
            self.session_budget_usd,
        ):
            if not value.is_finite() or value < 0:
                raise ValueError("risk allocation values must be finite and non-negative")
        if (
            self.option_amount == 0
            or self.maximum_contractual_payoff_usd == 0
            or self.stress_reserve_usd == 0
        ):
            raise ValueError("risk allocation amount, payoff cap, and reserve must be positive")
        if self.concurrent_position_limit <= 0:
            raise ValueError("concurrent position limit must be positive")
        if not self.delivery_stress:
            raise ValueError("risk allocation requires at least one delivery stress")
        if self.budget_metric != SHADOW_STRESS_BUDGET_METRIC:
            raise ValueError("risk allocation has an unsupported stress budget metric")
        if self.exit_cost_stress_usd != (
            self.exit_cost_stress_native * self.boundary_index_price_usd
        ):
            raise ValueError("risk allocation exit stress units are incoherent")
        expected_delivery_stress = max(
            (stress.delivery_valued_loss_usd for stress in self.delivery_stress),
            default=Decimal(0),
        )
        if self.maximum_delivery_stress_usd != expected_delivery_stress:
            raise ValueError("risk allocation maximum delivery stress is incoherent")
        if self.stress_reserve_usd != max(
            self.maximum_contractual_payoff_usd,
            self.exit_cost_stress_usd,
            self.maximum_delivery_stress_usd,
        ):
            raise ValueError("risk allocation reserve does not own the conservative maximum")
        capacity_values = (
            self.session_used_before_usd,
            self.session_remaining_after_usd,
            self.open_position_count_before,
        )
        if self.result is AllocationResult.UNKNOWN:
            if any(value is not None for value in capacity_values):
                raise ValueError("unknown allocation cannot invent capacity values")
        elif any(value is None for value in capacity_values):
            raise ValueError("known allocation requires complete capacity values")
        if self.session_used_before_usd is not None:
            if not self.session_used_before_usd.is_finite() or self.session_used_before_usd < 0:
                raise ValueError("used stress capacity must be finite and non-negative")
            expected_remaining = max(
                Decimal(0),
                self.session_budget_usd - self.session_used_before_usd - self.stress_reserve_usd,
            )
            if self.session_remaining_after_usd != expected_remaining:
                raise ValueError("risk allocation remaining stress capacity is incoherent")
        if self.open_position_count_before is not None and self.open_position_count_before < 0:
            raise ValueError("risk allocation open Position count must be non-negative")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowRiskAllocationV2", self)


def allocate_btc_condor_shadow_risk(
    *,
    candidate: Btc0DteCondorCandidate,
    market_session_id: str,
    policy: BtcShortVolPolicy,
    capacity: ShadowCapacity | None,
    known_at: datetime,
) -> ShadowRiskAllocation:
    pricing = candidate.pricing
    stress_exit = max(
        pricing.observed_close_native_debit or Decimal(0),
        pricing.native_gross_credit * policy.risk.exit_cost_stress_fraction,
    )
    delivery_stress = tuple(
        _delivery_stress(
            factor=factor,
            boundary_index=pricing.boundary_index_price_usd,
            candidate=candidate,
            native_credit=pricing.native_net_credit,
        )
        for factor in policy.risk.delivery_price_stress_factors
    )
    exit_stress_usd = stress_exit * pricing.boundary_index_price_usd
    maximum_delivery_stress_usd = max(
        (stress.delivery_valued_loss_usd for stress in delivery_stress),
        default=Decimal(0),
    )
    stress_reserve_usd = max(
        pricing.maximum_contractual_payoff_cap_usd,
        exit_stress_usd,
        maximum_delivery_stress_usd,
    )
    if capacity is None:
        return _allocation(
            result=AllocationResult.UNKNOWN,
            candidate=candidate,
            market_session_id=market_session_id,
            policy=policy,
            known_at=known_at,
            exit_cost_stress_native=stress_exit,
            exit_cost_stress_usd=exit_stress_usd,
            delivery_stress=delivery_stress,
            maximum_delivery_stress_usd=maximum_delivery_stress_usd,
            stress_reserve_usd=stress_reserve_usd,
            session_used_before_usd=None,
            session_remaining_after_usd=None,
            open_position_count_before=None,
            reason="SHADOW_CAPACITY_UNKNOWN",
        )
    if (
        capacity.channel_id is not policy.channel_id
        or capacity.market_session_id != market_session_id
    ):
        return _allocation(
            result=AllocationResult.UNKNOWN,
            candidate=candidate,
            market_session_id=market_session_id,
            policy=policy,
            known_at=known_at,
            exit_cost_stress_native=stress_exit,
            exit_cost_stress_usd=exit_stress_usd,
            delivery_stress=delivery_stress,
            maximum_delivery_stress_usd=maximum_delivery_stress_usd,
            stress_reserve_usd=stress_reserve_usd,
            session_used_before_usd=None,
            session_remaining_after_usd=None,
            open_position_count_before=None,
            reason="SHADOW_CAPACITY_SCOPE_MISMATCH",
        )
    if capacity.known_at > known_at:
        return _allocation(
            result=AllocationResult.UNKNOWN,
            candidate=candidate,
            market_session_id=market_session_id,
            policy=policy,
            known_at=known_at,
            exit_cost_stress_native=stress_exit,
            exit_cost_stress_usd=exit_stress_usd,
            delivery_stress=delivery_stress,
            maximum_delivery_stress_usd=maximum_delivery_stress_usd,
            stress_reserve_usd=stress_reserve_usd,
            session_used_before_usd=None,
            session_remaining_after_usd=None,
            open_position_count_before=None,
            reason="SHADOW_CAPACITY_NOT_KNOWN_AT_DECISION",
        )
    used_after = capacity.stress_reserve_used_usd + stress_reserve_usd
    remaining = policy.risk.maximum_session_stress_reserve_usd - used_after
    reason: str | None = None
    if remaining < 0:
        reason = "SESSION_SHADOW_STRESS_BUDGET_EXCEEDED"
    elif capacity.open_position_count >= policy.risk.maximum_concurrent_positions:
        reason = "SHADOW_CONCURRENT_POSITION_LIMIT_REACHED"
    return _allocation(
        result=AllocationResult.UNAVAILABLE if reason is not None else AllocationResult.AVAILABLE,
        candidate=candidate,
        market_session_id=market_session_id,
        policy=policy,
        known_at=known_at,
        exit_cost_stress_native=stress_exit,
        exit_cost_stress_usd=exit_stress_usd,
        delivery_stress=delivery_stress,
        maximum_delivery_stress_usd=maximum_delivery_stress_usd,
        stress_reserve_usd=stress_reserve_usd,
        session_used_before_usd=capacity.stress_reserve_used_usd,
        session_remaining_after_usd=max(Decimal(0), remaining),
        open_position_count_before=capacity.open_position_count,
        reason=reason,
    )


def _allocation(
    *,
    result: AllocationResult,
    candidate: Btc0DteCondorCandidate,
    market_session_id: str,
    policy: BtcShortVolPolicy,
    known_at: datetime,
    exit_cost_stress_native: Decimal,
    exit_cost_stress_usd: Decimal,
    delivery_stress: tuple[DeliveryStress, ...],
    maximum_delivery_stress_usd: Decimal,
    stress_reserve_usd: Decimal,
    session_used_before_usd: Decimal | None,
    session_remaining_after_usd: Decimal | None,
    open_position_count_before: int | None,
    reason: str | None,
) -> ShadowRiskAllocation:
    pricing = candidate.pricing
    return ShadowRiskAllocation(
        result=result,
        channel_id=policy.channel_id,
        market_session_id=market_session_id,
        policy_id=policy.identity,
        candidate_id=candidate.identity,
        known_at=known_at,
        budget_metric=SHADOW_STRESS_BUDGET_METRIC,
        option_amount=candidate.option_amount,
        maximum_contractual_payoff_usd=pricing.maximum_contractual_payoff_cap_usd,
        entry_premium_native=pricing.native_gross_credit,
        combo_fee_native=pricing.combo_standard_fee_native,
        boundary_index_price_usd=pricing.boundary_index_price_usd,
        exit_cost_stress_native=exit_cost_stress_native,
        exit_cost_stress_usd=exit_cost_stress_usd,
        delivery_stress=delivery_stress,
        maximum_delivery_stress_usd=maximum_delivery_stress_usd,
        stress_reserve_usd=stress_reserve_usd,
        session_budget_usd=policy.risk.maximum_session_stress_reserve_usd,
        session_used_before_usd=session_used_before_usd,
        session_remaining_after_usd=session_remaining_after_usd,
        concurrent_position_limit=policy.risk.maximum_concurrent_positions,
        open_position_count_before=open_position_count_before,
        expires_at=candidate.expiry,
        release_condition="CASE_ENTRY_TERMINAL_OR_POSITION_TERMINAL",
        reason=reason,
    )


def stress_reserve_from_allocation_record(
    value: Mapping[str, object],
    *,
    allocation_id: str,
) -> Decimal:
    """Recover the exact current-Policy reserve without inventing a fallback amount."""

    if value.get("allocation_id") != allocation_id:
        raise ValueError("Shadow allocation record identity does not match its Case")
    payload = dict(value)
    payload.pop("allocation_id", None)
    if canonical_identity("ShadowRiskAllocationV2", payload) != allocation_id:
        raise ValueError("Shadow allocation record content identity is invalid")
    if value.get("budget_metric") != SHADOW_STRESS_BUDGET_METRIC:
        raise ValueError("Shadow allocation record uses an obsolete budget metric")
    contractual = _record_decimal(value, "maximum_contractual_payoff_usd")
    boundary_index = _record_decimal(value, "boundary_index_price_usd")
    exit_native = _record_decimal(value, "exit_cost_stress_native")
    exit_usd = _record_decimal(value, "exit_cost_stress_usd")
    maximum_delivery = _record_decimal(value, "maximum_delivery_stress_usd")
    reserve = _record_decimal(value, "stress_reserve_usd")
    if exit_usd != exit_native * boundary_index:
        raise ValueError("Shadow allocation record exit stress units are incoherent")
    delivery_stress = value.get("delivery_stress")
    if not isinstance(delivery_stress, list):
        raise ValueError("Shadow allocation record delivery stress must be an array")
    recovered_delivery_maximum = max(
        (
            _record_decimal(item, "delivery_valued_loss_usd")
            for item in delivery_stress
            if isinstance(item, dict)
        ),
        default=Decimal(0),
    )
    if len(delivery_stress) != sum(isinstance(item, dict) for item in delivery_stress):
        raise ValueError("Shadow allocation record delivery stress contains a foreign value")
    if maximum_delivery != recovered_delivery_maximum:
        raise ValueError("Shadow allocation record maximum delivery stress is incoherent")
    if reserve != max(contractual, exit_usd, maximum_delivery):
        raise ValueError("Shadow allocation record reserve is not the conservative maximum")
    return reserve


def _record_decimal(value: Mapping[str, object], field: str) -> Decimal:
    member = value.get(field)
    if isinstance(member, bool) or member is None:
        raise ValueError(f"Shadow allocation record {field} is invalid")
    try:
        parsed = Decimal(str(member))
    except ArithmeticError as exc:
        raise ValueError(f"Shadow allocation record {field} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"Shadow allocation record {field} is invalid")
    return parsed


def _delivery_stress(
    *,
    factor: Decimal,
    boundary_index: Decimal,
    candidate: Btc0DteCondorCandidate,
    native_credit: Decimal,
) -> DeliveryStress:
    delivery_price = boundary_index * factor
    amount = candidate.option_amount
    payoff_usd = (
        intrinsic_payoff_usd(
            option_type="PUT",
            strike=candidate.short_put.strike,
            delivery_price=delivery_price,
            quantity=amount,
        )
        - intrinsic_payoff_usd(
            option_type="PUT",
            strike=candidate.long_put.strike,
            delivery_price=delivery_price,
            quantity=amount,
        )
        + intrinsic_payoff_usd(
            option_type="CALL",
            strike=candidate.short_call.strike,
            delivery_price=delivery_price,
            quantity=amount,
        )
        - intrinsic_payoff_usd(
            option_type="CALL",
            strike=candidate.long_call.strike,
            delivery_price=delivery_price,
            quantity=amount,
        )
    )
    native_payoff = payoff_usd / delivery_price
    loss_native = max(Decimal(0), native_payoff - native_credit)
    return DeliveryStress(
        delivery_price_usd=delivery_price,
        contractual_payoff_usd=payoff_usd,
        contractual_payoff_native=native_payoff,
        projected_loss_native=loss_native,
        delivery_valued_loss_usd=loss_native * delivery_price,
    )

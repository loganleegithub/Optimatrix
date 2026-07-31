from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from short_vol_underwriting.constants import (
    CANDIDATE_INVALIDATION_REASONS,
    POSITION_CLOSE_REASONS,
)
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import (
    FactBoundary,
    OutcomeState,
    PredicateTruth,
    TerminalSource,
)


class UnderwritingAvailability(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"
    EVALUABLE = "EVALUABLE"


class UnderwritingAction(StrEnum):
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class CandidateLifecycle(StrEnum):
    VALID = "VALID"
    ADMITTED = "ADMITTED"
    INVALIDATED = "INVALIDATED"


class AdmissionTerminalOutcome(StrEnum):
    ENTRY_EMITTED = "ENTRY_EMITTED"
    KNOWN_COMPLETE_NO_ENTRY = "KNOWN_COMPLETE_NO_ENTRY"
    KNOWN_INVALIDATED_BEFORE_REFRESH = "KNOWN_INVALIDATED_BEFORE_REFRESH"
    UNKNOWN_CONSUMED = "UNKNOWN_CONSUMED"


@dataclass(frozen=True)
class EntryEconomics:
    full_quantity_btc: Decimal
    required_side_total_quote_usdc: Decimal
    gross_entry_credit_usdc: Decimal
    entry_fee_reserve_usdc: Decimal
    net_entry_credit_usdc: Decimal
    width_usdc_per_btc: Decimal
    payoff_cap_usdc: Decimal
    contractual_payoff_max_loss_ex_fees_usdc: Decimal
    entry_fee_reserved_payoff_loss_usdc: Decimal
    future_cost_reserve_usdc: Decimal
    underwriting_reserved_loss_usdc: Decimal
    actual_all_in_max_loss_usdc: None = None
    actual_all_in_max_loss_availability: str = "UNKNOWN"


@dataclass(frozen=True)
class CloseEconomics:
    full_quantity_btc: Decimal
    required_close_side_total_quote_usdc: Decimal
    gross_close_cashflow_usdc: Decimal
    close_fee_reserve_usdc: Decimal
    net_close_cashflow_usdc: Decimal
    net_close_debit_usdc: Decimal
    projected_shadow_net_pnl_usdc: Decimal
    projected_net_loss_usdc: Decimal


@dataclass(frozen=True)
class ShadowOutcomeEconomics:
    gross_pnl_usdc: Decimal
    total_public_fee_reserve_usdc: Decimal
    net_pnl_after_public_standard_fee_reserve_usdc: Decimal
    net_loss_usdc: Decimal


@dataclass(frozen=True)
class PositionDecision:
    position_evaluation_identity: str
    position_action_identity: str
    serialized_action: str
    ordered_predicate_truth_vector: tuple[str, ...]
    ordered_latched_close_reason_vector: tuple[str, ...]
    primary_close_reason: str | None
    secondary_close_reasons: tuple[str, ...]
    first_latched_close_action_identity: str | None
    action_fact_boundary: FactBoundary


@dataclass
class CandidateState:
    candidate_identity: str
    lifecycle: CandidateLifecycle = CandidateLifecycle.VALID
    terminal_identity: str | None = None
    terminal_boundary: FactBoundary | None = None

    def __post_init__(self) -> None:
        require_identity(self.candidate_identity, "candidate_identity")

    def admit(self, boundary: FactBoundary) -> None:
        self._require_valid()
        self.lifecycle = CandidateLifecycle.ADMITTED
        self.terminal_boundary = boundary

    def invalidate(self, ordered_reasons: tuple[str, ...], boundary: FactBoundary) -> str:
        self._require_valid()
        primary, normalized = ordered_candidate_invalidation(ordered_reasons)
        self.terminal_identity = canonical_identity(
            "CANDIDATE_INVALIDATION",
            self.candidate_identity,
            primary,
            normalized,
            boundary.as_object(),
        )
        self.lifecycle = CandidateLifecycle.INVALIDATED
        self.terminal_boundary = boundary
        return self.terminal_identity

    def _require_valid(self) -> None:
        if self.lifecycle is not CandidateLifecycle.VALID:
            raise ValueError("Candidate is terminal")


@dataclass
class PositionDecisionState:
    shadow_entry_identity: str
    position_policy_identity: str
    entry_boundary: FactBoundary
    rejected: bool = False
    first_latched_close_action_identity: str | None = None
    _latched_reasons: set[str] | None = None

    def __post_init__(self) -> None:
        require_identity(self.shadow_entry_identity, "shadow_entry_identity")
        require_identity(self.position_policy_identity, "position_policy_identity")
        if self._latched_reasons is None:
            self._latched_reasons = set()

    def evaluate(
        self,
        predicate_truth: dict[str, PredicateTruth],
        boundary: FactBoundary,
        *,
        consumed_position_fact_fingerprint: str,
    ) -> PositionDecision:
        require_identity(
            consumed_position_fact_fingerprint,
            "consumed_position_fact_fingerprint",
        )
        if not boundary.is_strictly_after(self.entry_boundary):
            raise ValueError("Position evaluation must be strictly post-entry")
        if set(predicate_truth) != set(POSITION_CLOSE_REASONS):
            raise ValueError("Position evaluation requires the exact nine predicates")
        vector = tuple(predicate_truth[reason].value for reason in POSITION_CLOSE_REASONS)
        assert self._latched_reasons is not None
        self._latched_reasons.update(
            reason
            for reason in POSITION_CLOSE_REASONS
            if predicate_truth[reason] is PredicateTruth.TRUE
        )
        ordered_latched = tuple(
            reason for reason in POSITION_CLOSE_REASONS if reason in self._latched_reasons
        )
        if self.first_latched_close_action_identity is not None or ordered_latched:
            action = "CLOSE"
        elif PredicateTruth.UNKNOWN in predicate_truth.values():
            action = "UNKNOWN"
        else:
            action = "HOLD"
        evaluation_identity = canonical_identity(
            (
                "RejectedCounterfactualPositionEvaluationIdentity"
                if self.rejected
                else "PositionEvaluationIdentity"
            ),
            self.shadow_entry_identity,
            self.position_policy_identity,
            consumed_position_fact_fingerprint,
            boundary.as_object(),
        )
        action_identity = canonical_identity(
            (
                "RejectedCounterfactualPositionActionIdentity"
                if self.rejected
                else "PositionActionIdentity"
            ),
            evaluation_identity,
            action,
            vector,
            ordered_latched,
        )
        if self.first_latched_close_action_identity is None and action == "CLOSE":
            self.first_latched_close_action_identity = action_identity
        return PositionDecision(
            position_evaluation_identity=evaluation_identity,
            position_action_identity=action_identity,
            serialized_action=action,
            ordered_predicate_truth_vector=vector,
            ordered_latched_close_reason_vector=ordered_latched,
            primary_close_reason=ordered_latched[0] if ordered_latched else None,
            secondary_close_reasons=ordered_latched[1:],
            first_latched_close_action_identity=self.first_latched_close_action_identity,
            action_fact_boundary=boundary,
        )


@dataclass
class OutcomeReducer:
    entry_boundary: FactBoundary
    state: OutcomeState = OutcomeState.PENDING
    first_close_identity: str | None = None
    first_close_boundary: FactBoundary | None = None
    selected_exit_identity: str | None = None
    terminal_boundary: FactBoundary | None = None

    def latch_close(self, action_identity: str, boundary: FactBoundary) -> None:
        require_identity(action_identity, "first_close_action_identity")
        if not boundary.is_strictly_after(self.entry_boundary):
            raise ValueError("first CLOSE must be strictly post-entry")
        if self.first_close_identity is None:
            self.first_close_identity = action_identity
            self.first_close_boundary = boundary

    def settle(
        self,
        *,
        boundary: FactBoundary,
        eligible_exit_identity: str | None = None,
        ordinary_attempt_terminal: bool = False,
        lifecycle_ready: bool = False,
        terminal_source: TerminalSource | None = None,
    ) -> OutcomeState:
        if self.state is not OutcomeState.PENDING:
            return self.state
        if not boundary.is_strictly_after(self.entry_boundary):
            raise ValueError("Outcome facts must be strictly post-entry")
        close_is_earlier = self.first_close_boundary is not None and boundary.is_strictly_after(
            self.first_close_boundary
        )
        if eligible_exit_identity is not None:
            require_identity(eligible_exit_identity, "eligible_exit_identity")
            if not close_is_earlier:
                raise ValueError("eligible exit must be strictly after first CLOSE")
            self.selected_exit_identity = eligible_exit_identity
            self.state = OutcomeState.MATURE_KNOWN
        elif close_is_earlier and ordinary_attempt_terminal and lifecycle_ready:
            self.state = OutcomeState.MATURE_UNKNOWN
        elif terminal_source is TerminalSource.STOP:
            self.state = OutcomeState.CENSORED_AT_STOP
        elif terminal_source is TerminalSource.FAILURE:
            self.state = OutcomeState.CENSORED_AT_FAILURE
        else:
            return self.state
        self.terminal_boundary = boundary
        return self.state


def ordered_candidate_invalidation(reasons: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    values = tuple(reasons)
    if not values:
        raise ValueError("Candidate invalidation requires at least one reason")
    unknown = set(values) - set(CANDIDATE_INVALIDATION_REASONS)
    if unknown:
        raise ValueError(f"unknown Candidate invalidation reason: {sorted(unknown)}")
    if len(values) != len(set(values)):
        raise ValueError("Candidate invalidation reasons must not contain duplicates")
    ordered = tuple(reason for reason in CANDIDATE_INVALIDATION_REASONS if reason in set(values))
    return ordered[0], ordered


def classify_underwriting_action(
    *,
    availability: UnderwritingAvailability,
    net_entry_credit_usdc: Decimal | None,
    future_cost_reserve_usdc: Decimal | None,
    underwriting_reserved_loss_usdc: Decimal | None,
    maximum_underwriting_reserved_loss_usdc: Decimal,
    minimum_net_entry_credit_usdc: Decimal,
    payoff_cap_usdc: Decimal | None,
    minimum_net_credit_to_payoff_cap_fraction: Decimal,
    consumed_level_count: int | None,
    maximum_entry_consumed_level_count: int,
) -> UnderwritingAction | None:
    if availability is not UnderwritingAvailability.EVALUABLE:
        return None
    required = (
        net_entry_credit_usdc,
        future_cost_reserve_usdc,
        underwriting_reserved_loss_usdc,
        payoff_cap_usdc,
    )
    if any(value is None for value in required) or consumed_level_count is None:
        raise ValueError("EVALUABLE Underwriting requires complete economics")
    assert net_entry_credit_usdc is not None
    assert future_cost_reserve_usdc is not None
    assert underwriting_reserved_loss_usdc is not None
    assert payoff_cap_usdc is not None
    if (
        net_entry_credit_usdc <= 0
        or net_entry_credit_usdc <= future_cost_reserve_usdc
        or underwriting_reserved_loss_usdc > maximum_underwriting_reserved_loss_usdc
    ):
        return UnderwritingAction.ABSTAIN
    if (
        net_entry_credit_usdc < minimum_net_entry_credit_usdc
        or net_entry_credit_usdc < minimum_net_credit_to_payoff_cap_fraction * payoff_cap_usdc
        or consumed_level_count > maximum_entry_consumed_level_count
    ):
        return UnderwritingAction.WATCH
    return UnderwritingAction.CANDIDATE


def compute_entry_economics(
    *,
    direction: str,
    full_quantity_btc: Decimal,
    consumed_levels: tuple[tuple[Decimal, Decimal], ...],
    index_usdc_per_btc: Decimal,
    short_strike_usdc_per_btc: Decimal,
    long_strike_usdc_per_btc: Decimal,
    fee_rate_index_fraction: Decimal,
    future_cost_reserve_usdc: Decimal,
) -> EntryEconomics:
    total = _consumed_total(full_quantity_btc, consumed_levels)
    sign = _direction_sign(direction)
    gross_credit = -sign * total
    if gross_credit <= 0:
        raise ValueError("entry must be a positive gross credit")
    _require_positive(index_usdc_per_btc, "index_usdc_per_btc")
    _require_non_negative(fee_rate_index_fraction, "fee_rate_index_fraction")
    _require_non_negative(future_cost_reserve_usdc, "future_cost_reserve_usdc")
    entry_fee = fee_rate_index_fraction * index_usdc_per_btc * full_quantity_btc
    net_credit = gross_credit - entry_fee
    width = abs(long_strike_usdc_per_btc - short_strike_usdc_per_btc)
    _require_positive(width, "protective vertical width")
    payoff_cap = width * full_quantity_btc
    contractual = max(Decimal(0), payoff_cap - gross_credit)
    fee_reserved = max(Decimal(0), payoff_cap - net_credit)
    underwriting_reserved = max(
        Decimal(0),
        payoff_cap - net_credit + future_cost_reserve_usdc,
    )
    return EntryEconomics(
        full_quantity_btc=full_quantity_btc,
        required_side_total_quote_usdc=total,
        gross_entry_credit_usdc=gross_credit,
        entry_fee_reserve_usdc=entry_fee,
        net_entry_credit_usdc=net_credit,
        width_usdc_per_btc=width,
        payoff_cap_usdc=payoff_cap,
        contractual_payoff_max_loss_ex_fees_usdc=contractual,
        entry_fee_reserved_payoff_loss_usdc=fee_reserved,
        future_cost_reserve_usdc=future_cost_reserve_usdc,
        underwriting_reserved_loss_usdc=underwriting_reserved,
    )


def compute_close_economics(
    *,
    direction: str,
    full_quantity_btc: Decimal,
    consumed_levels: tuple[tuple[Decimal, Decimal], ...],
    index_usdc_per_btc: Decimal,
    fee_rate_index_fraction: Decimal,
    net_entry_credit_usdc: Decimal,
) -> CloseEconomics:
    total = _consumed_total(full_quantity_btc, consumed_levels)
    sign = _direction_sign(direction)
    gross_cashflow = -sign * total
    _require_positive(index_usdc_per_btc, "index_usdc_per_btc")
    _require_non_negative(fee_rate_index_fraction, "fee_rate_index_fraction")
    close_fee = fee_rate_index_fraction * index_usdc_per_btc * full_quantity_btc
    net_cashflow = gross_cashflow - close_fee
    net_debit = max(Decimal(0), -net_cashflow)
    projected_pnl = net_entry_credit_usdc + net_cashflow
    projected_loss = max(Decimal(0), -projected_pnl)
    return CloseEconomics(
        full_quantity_btc=full_quantity_btc,
        required_close_side_total_quote_usdc=total,
        gross_close_cashflow_usdc=gross_cashflow,
        close_fee_reserve_usdc=close_fee,
        net_close_cashflow_usdc=net_cashflow,
        net_close_debit_usdc=net_debit,
        projected_shadow_net_pnl_usdc=projected_pnl,
        projected_net_loss_usdc=projected_loss,
    )


def compute_shadow_outcome_economics(
    *,
    gross_entry_credit_usdc: Decimal,
    entry_fee_reserve_usdc: Decimal,
    gross_close_cashflow_usdc: Decimal,
    close_fee_reserve_usdc: Decimal,
) -> ShadowOutcomeEconomics:
    gross_pnl = gross_entry_credit_usdc + gross_close_cashflow_usdc
    fees = entry_fee_reserve_usdc + close_fee_reserve_usdc
    net_pnl = gross_pnl - fees
    return ShadowOutcomeEconomics(
        gross_pnl_usdc=gross_pnl,
        total_public_fee_reserve_usdc=fees,
        net_pnl_after_public_standard_fee_reserve_usdc=net_pnl,
        net_loss_usdc=max(Decimal(0), -net_pnl),
    )


def _consumed_total(
    full_quantity_btc: Decimal,
    consumed_levels: tuple[tuple[Decimal, Decimal], ...],
) -> Decimal:
    _require_positive(full_quantity_btc, "full_quantity_btc")
    if not consumed_levels:
        raise ValueError("consumed_levels must be non-empty")
    amount_sum = Decimal(0)
    total = Decimal(0)
    for price, amount in consumed_levels:
        if not price.is_finite():
            raise ValueError("level price must be finite")
        _require_positive(amount, "level amount")
        amount_sum += amount
        total += price * amount
    if amount_sum != full_quantity_btc:
        raise ValueError("consumed level amounts must sum exactly to full quantity")
    return total


def _direction_sign(direction: str) -> Decimal:
    if direction == "BUY":
        return Decimal(1)
    if direction == "SELL":
        return Decimal(-1)
    raise ValueError("direction must be BUY or SELL")


def _require_positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be finite and positive")


def _require_non_negative(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field} must be finite and non-negative")

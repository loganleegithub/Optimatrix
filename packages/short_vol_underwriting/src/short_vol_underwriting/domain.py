from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from options_domain import (
    ComponentBookQuoteKind,
    ComponentBookVerticalQuote,
    OptionProductSpec,
    OptionType,
    product_for_identity,
)

from short_vol_underwriting.constants import (
    CANDIDATE_INVALIDATION_REASONS,
    POSITION_CLOSE_REASONS,
)
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import (
    CaseFactBoundary,
    FactBoundary,
    OutcomeState,
    PositionDecisionRecoverySeed,
    PredicateTruth,
    TerminalSource,
)


@dataclass(frozen=True)
class SourceFact:
    source_identity: str
    boundary: FactBoundary

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")

    def as_ref(self) -> dict[str, object]:
        return {
            "source_identity": self.source_identity,
            "receipt_fact_boundary": self.boundary.as_object(),
        }


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
class EntryTerms:
    """Frozen Entry fields consumed by Position, Outcome, and recovery."""

    short_leg_identity: str
    long_leg_identity: str
    short_leg_instrument_name: str
    long_leg_instrument_name: str
    canonical_combo_identity: str | None
    combo_instrument_name: str | None
    option_type: str
    short_strike_usdc_per_btc: Decimal
    long_strike_usdc_per_btc: Decimal
    expiry_ms: int
    target_quantity_btc: Decimal
    entry_direction: str
    index_usdc_per_btc: Decimal | None
    index_source: SourceFact | None
    short_mark_iv_fraction: Decimal | None
    ticker_source: SourceFact | None
    short_leg_taker_commission_fraction: Decimal
    long_leg_taker_commission_fraction: Decimal
    execution_model: str
    product_spec_identity: str | None
    product_name: str | None
    native_premium_currency: str | None
    settlement_currency: str | None
    valuation_currency: str | None
    price_index: str | None
    native_gross_entry_credit: Decimal | None
    native_entry_fee_reserve: Decimal | None
    native_net_entry_credit: Decimal | None
    entry_valuation_index_price: Decimal | None
    width_usdc_per_btc: Decimal
    entry_component_legs: tuple[Mapping[str, object], ...]

    @property
    def uses_component_books(self) -> bool:
        return bool(self.entry_component_legs)


@dataclass(frozen=True)
class UnderwritingThresholdMargins:
    """Signed distance to every ordered Underwriting action predicate."""

    positive_net_credit_usdc: Decimal
    credit_above_future_cost_reserve_usdc: Decimal
    reserved_loss_limit_headroom_usdc: Decimal
    minimum_net_credit_headroom_usdc: Decimal
    minimum_credit_ratio_headroom: Decimal
    entry_consumed_level_headroom: int

    @property
    def failed_predicates(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.positive_net_credit_usdc <= 0:
            failures.append("NON_POSITIVE_NET_ENTRY_CREDIT")
        if self.credit_above_future_cost_reserve_usdc <= 0:
            failures.append("CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE")
        if self.reserved_loss_limit_headroom_usdc < 0:
            failures.append("UNDERWRITING_RESERVED_LOSS_LIMIT")
        if self.minimum_net_credit_headroom_usdc < 0:
            failures.append("MINIMUM_NET_ENTRY_CREDIT")
        if self.minimum_credit_ratio_headroom < 0:
            failures.append("MINIMUM_NET_CREDIT_TO_PAYOFF_CAP")
        if self.entry_consumed_level_headroom < 0:
            failures.append("ENTRY_CONSUMED_LEVEL_LIMIT")
        return tuple(failures)

    def as_vector(
        self,
        valuation_unit: str = "USDC",
    ) -> tuple[dict[str, object], ...]:
        if not valuation_unit:
            raise ValueError("valuation_unit must be non-empty")
        return (
            {
                "predicate": "POSITIVE_NET_ENTRY_CREDIT",
                "signed_margin": str(self.positive_net_credit_usdc),
                "unit": valuation_unit,
                "passes": self.positive_net_credit_usdc > 0,
            },
            {
                "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
                "signed_margin": str(self.credit_above_future_cost_reserve_usdc),
                "unit": valuation_unit,
                "passes": self.credit_above_future_cost_reserve_usdc > 0,
            },
            {
                "predicate": "UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT",
                "signed_margin": str(self.reserved_loss_limit_headroom_usdc),
                "unit": valuation_unit,
                "passes": self.reserved_loss_limit_headroom_usdc >= 0,
            },
            {
                "predicate": "MINIMUM_NET_ENTRY_CREDIT",
                "signed_margin": str(self.minimum_net_credit_headroom_usdc),
                "unit": valuation_unit,
                "passes": self.minimum_net_credit_headroom_usdc >= 0,
            },
            {
                "predicate": "MINIMUM_NET_CREDIT_TO_PAYOFF_CAP",
                "signed_margin": str(self.minimum_credit_ratio_headroom),
                "unit": "FRACTION",
                "passes": self.minimum_credit_ratio_headroom >= 0,
            },
            {
                "predicate": "ENTRY_CONSUMED_LEVEL_LIMIT",
                "signed_margin": self.entry_consumed_level_headroom,
                "unit": "LEVEL_COUNT",
                "passes": self.entry_consumed_level_headroom >= 0,
            },
        )


@dataclass(frozen=True)
class UnderwritingComponentCandidate:
    long_instrument_name: str
    economics: EntryEconomics
    consumed_level_count: int

    def __post_init__(self) -> None:
        if not self.long_instrument_name:
            raise ValueError("component Candidate instrument name must be non-empty")
        if (
            isinstance(self.consumed_level_count, bool)
            or not isinstance(self.consumed_level_count, int)
            or self.consumed_level_count < 0
        ):
            raise ValueError("component Candidate consumed level count must be non-negative")


@dataclass(frozen=True)
class UnderwritingComponentSelection:
    candidate: UnderwritingComponentCandidate
    action: UnderwritingAction
    margins: UnderwritingThresholdMargins
    selection_rule_identity: str
    candidate_protective_leg_count: int

    def __post_init__(self) -> None:
        require_identity(self.selection_rule_identity, "selection_rule_identity")
        if (
            isinstance(self.candidate_protective_leg_count, bool)
            or not isinstance(self.candidate_protective_leg_count, int)
            or self.candidate_protective_leg_count < 0
        ):
            raise ValueError("candidate protective-leg count must be non-negative")
        if self.action is UnderwritingAction.CANDIDATE and self.candidate_protective_leg_count == 0:
            raise ValueError("Candidate selection must count its selected protective leg")


UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY = canonical_identity(
    "UnderwritingComponentSelectionRuleIdentity",
    ("CANDIDATE", "WATCH", "ABSTAIN"),
    (
        "POSITIVE_NET_ENTRY_CREDIT",
        "CREDIT_ABOVE_FUTURE_COST_RESERVE",
        "UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT",
        "MINIMUM_NET_ENTRY_CREDIT",
        "MINIMUM_NET_CREDIT_TO_PAYOFF_CAP",
        "ENTRY_CONSUMED_LEVEL_LIMIT",
    ),
    "NARROWER_WIDTH",
    "PROTECTIVE_INSTRUMENT_NAME",
)


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
class ContractSettlementEconomics:
    """Public counterfactual economics of carrying one frozen vertical to delivery."""

    delivery_price_usdc_per_btc: Decimal
    native_short_contractual_payoff: Decimal
    native_long_contractual_payoff: Decimal
    native_gross_settlement_cashflow: Decimal
    native_delivery_fee_reserve: Decimal
    native_net_settlement_cashflow: Decimal
    native_gross_pnl: Decimal
    native_total_fee_reserve: Decimal
    native_net_pnl: Decimal
    delivery_valued_gross_settlement_cashflow_usdc: Decimal
    delivery_valued_delivery_fee_reserve_usdc: Decimal
    delivery_valued_net_settlement_cashflow_usdc: Decimal
    delivery_valued_gross_pnl_usdc: Decimal
    delivery_valued_total_fee_reserve_usdc: Decimal
    delivery_valued_net_pnl_usdc: Decimal
    delivery_valued_net_loss_usdc: Decimal


def compute_contract_settlement_economics(
    *,
    product: OptionProductSpec,
    option_type: OptionType | str,
    short_strike_usdc_per_btc: Decimal,
    long_strike_usdc_per_btc: Decimal,
    full_quantity_btc: Decimal,
    delivery_price_usdc_per_btc: Decimal,
    delivery_fee_rate_fraction: Decimal,
    native_gross_entry_credit: Decimal,
    native_entry_fee_reserve: Decimal,
) -> ContractSettlementEconomics:
    """Settle a short-option/long-protection vertical from one official delivery price."""

    try:
        normalized_type = (
            option_type if isinstance(option_type, OptionType) else OptionType(option_type)
        )
    except ValueError as exc:
        raise ValueError("option_type must be call or put") from exc
    for member, field in (
        (short_strike_usdc_per_btc, "short_strike_usdc_per_btc"),
        (long_strike_usdc_per_btc, "long_strike_usdc_per_btc"),
        (full_quantity_btc, "full_quantity_btc"),
        (delivery_price_usdc_per_btc, "delivery_price_usdc_per_btc"),
    ):
        if not isinstance(member, Decimal) or not member.is_finite() or member <= 0:
            raise ValueError(f"{field} must be a finite positive Decimal")
    for member, field in (
        (delivery_fee_rate_fraction, "delivery_fee_rate_fraction"),
        (native_gross_entry_credit, "native_gross_entry_credit"),
        (native_entry_fee_reserve, "native_entry_fee_reserve"),
    ):
        if not isinstance(member, Decimal) or not member.is_finite() or member < 0:
            raise ValueError(f"{field} must be a finite non-negative Decimal")

    def intrinsic(strike: Decimal) -> Decimal:
        if normalized_type is OptionType.CALL:
            return max(Decimal(0), delivery_price_usdc_per_btc - strike)
        return max(Decimal(0), strike - delivery_price_usdc_per_btc)

    short_native = product.native_payoff_from_strike_value(
        intrinsic(short_strike_usdc_per_btc) * full_quantity_btc,
        settlement_price=delivery_price_usdc_per_btc,
    )
    long_native = product.native_payoff_from_strike_value(
        intrinsic(long_strike_usdc_per_btc) * full_quantity_btc,
        settlement_price=delivery_price_usdc_per_btc,
    )
    gross_settlement = long_native - short_native
    delivery_fee = sum(
        (
            min(
                delivery_fee_rate_fraction * full_quantity_btc,
                Decimal("0.125") * payoff,
            )
            for payoff in (short_native, long_native)
            if payoff > 0
        ),
        Decimal(0),
    )
    net_settlement = gross_settlement - delivery_fee
    gross_pnl = native_gross_entry_credit + gross_settlement
    total_fee = native_entry_fee_reserve + delivery_fee
    net_pnl = gross_pnl - total_fee

    def delivery_value(native_amount: Decimal) -> Decimal:
        return product.valuation(native_amount, index_price=delivery_price_usdc_per_btc)

    valued_net_pnl = delivery_value(net_pnl)
    return ContractSettlementEconomics(
        delivery_price_usdc_per_btc=delivery_price_usdc_per_btc,
        native_short_contractual_payoff=short_native,
        native_long_contractual_payoff=long_native,
        native_gross_settlement_cashflow=gross_settlement,
        native_delivery_fee_reserve=delivery_fee,
        native_net_settlement_cashflow=net_settlement,
        native_gross_pnl=gross_pnl,
        native_total_fee_reserve=total_fee,
        native_net_pnl=net_pnl,
        delivery_valued_gross_settlement_cashflow_usdc=delivery_value(gross_settlement),
        delivery_valued_delivery_fee_reserve_usdc=delivery_value(delivery_fee),
        delivery_valued_net_settlement_cashflow_usdc=delivery_value(net_settlement),
        delivery_valued_gross_pnl_usdc=delivery_value(gross_pnl),
        delivery_valued_total_fee_reserve_usdc=delivery_value(total_fee),
        delivery_valued_net_pnl_usdc=valued_net_pnl,
        delivery_valued_net_loss_usdc=max(Decimal(0), -valued_net_pnl),
    )


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
    action_case_boundary: CaseFactBoundary

    @property
    def action_fact_boundary(self) -> FactBoundary:
        """Runtime-local compatibility view for the current owner emission path."""
        return self.action_case_boundary.fact_boundary


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
    entry_boundary: CaseFactBoundary | FactBoundary
    segment_baseline_boundary: CaseFactBoundary | None = None
    first_latched_close_action_identity: str | None = None
    _latched_reasons: set[str] | None = None
    _first_latched_close_reasons: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        require_identity(self.shadow_entry_identity, "shadow_entry_identity")
        require_identity(self.position_policy_identity, "position_policy_identity")
        if isinstance(self.entry_boundary, FactBoundary):
            self.entry_boundary = CaseFactBoundary(0, self.entry_boundary)
        elif not isinstance(self.entry_boundary, CaseFactBoundary):
            raise ValueError("entry_boundary must be a CaseFactBoundary or FactBoundary")
        if self.segment_baseline_boundary is not None:
            if not isinstance(self.segment_baseline_boundary, CaseFactBoundary):
                raise ValueError("segment_baseline_boundary must be a CaseFactBoundary")
            if (
                self.segment_baseline_boundary.segment_sequence
                <= self.entry_boundary.segment_sequence
            ):
                raise ValueError("recovery baseline must belong to a later Case segment")
        if self._latched_reasons is None:
            self._latched_reasons = set()

    @classmethod
    def recovered(
        cls,
        *,
        shadow_entry_identity: str,
        position_policy_identity: str,
        entry_boundary: CaseFactBoundary,
        segment_baseline_boundary: CaseFactBoundary,
        recovery_seed: PositionDecisionRecoverySeed,
    ) -> PositionDecisionState:
        """Continue one durable Position Policy in a later, gapped Segment."""
        return cls(
            shadow_entry_identity=shadow_entry_identity,
            position_policy_identity=position_policy_identity,
            entry_boundary=entry_boundary,
            segment_baseline_boundary=segment_baseline_boundary,
            first_latched_close_action_identity=(recovery_seed.first_latched_close_action_identity),
            _latched_reasons=set(recovery_seed.ordered_latched_close_reason_vector),
            _first_latched_close_reasons=(recovery_seed.ordered_latched_close_reason_vector),
        )

    def recovery_seed(self) -> PositionDecisionRecoverySeed:
        reasons = self._first_latched_close_reasons or ()
        return PositionDecisionRecoverySeed(
            first_latched_close_action_identity=self.first_latched_close_action_identity,
            ordered_latched_close_reason_vector=reasons,
        )

    def evaluate(
        self,
        predicate_truth: dict[str, PredicateTruth],
        boundary: CaseFactBoundary | FactBoundary,
        *,
        consumed_position_fact_fingerprint: str,
    ) -> PositionDecision:
        require_identity(
            consumed_position_fact_fingerprint,
            "consumed_position_fact_fingerprint",
        )
        assert isinstance(self.entry_boundary, CaseFactBoundary)
        evaluation_floor = self.segment_baseline_boundary or self.entry_boundary
        if isinstance(boundary, FactBoundary):
            case_boundary = CaseFactBoundary(
                evaluation_floor.segment_sequence,
                boundary,
            )
        elif isinstance(boundary, CaseFactBoundary):
            case_boundary = boundary
        else:
            raise ValueError("boundary must be a CaseFactBoundary or FactBoundary")
        if case_boundary.segment_sequence != evaluation_floor.segment_sequence:
            raise ValueError("Position evaluation must belong to the active Segment")
        if not case_boundary.is_strictly_after(evaluation_floor):
            if self.segment_baseline_boundary is not None:
                raise ValueError(
                    "Position evaluation must be strictly after the recovery segment baseline"
                )
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
            "PositionEvaluationIdentity",
            self.shadow_entry_identity,
            self.position_policy_identity,
            consumed_position_fact_fingerprint,
            case_boundary.fact_boundary.as_object(),
        )
        action_identity = canonical_identity(
            "PositionActionIdentity",
            evaluation_identity,
            action,
            vector,
            ordered_latched,
        )
        if self.first_latched_close_action_identity is None and action == "CLOSE":
            self.first_latched_close_action_identity = action_identity
            self._first_latched_close_reasons = ordered_latched
        return PositionDecision(
            position_evaluation_identity=evaluation_identity,
            position_action_identity=action_identity,
            serialized_action=action,
            ordered_predicate_truth_vector=vector,
            ordered_latched_close_reason_vector=ordered_latched,
            primary_close_reason=ordered_latched[0] if ordered_latched else None,
            secondary_close_reasons=ordered_latched[1:],
            first_latched_close_action_identity=self.first_latched_close_action_identity,
            action_case_boundary=case_boundary,
        )


@dataclass
class OutcomeReducer:
    entry_boundary: CaseFactBoundary
    state: OutcomeState = OutcomeState.PENDING
    first_close_identity: str | None = None
    first_close_boundary: CaseFactBoundary | None = None
    selected_exit_identity: str | None = None
    terminal_case_boundary: CaseFactBoundary | None = None

    @property
    def terminal_boundary(self) -> FactBoundary | None:
        """Runtime-local compatibility view for the current owner emission path."""
        return (
            self.terminal_case_boundary.fact_boundary
            if self.terminal_case_boundary is not None
            else None
        )

    def latch_close(self, action_identity: str, boundary: CaseFactBoundary) -> None:
        require_identity(action_identity, "first_close_action_identity")
        if not boundary.is_strictly_after(self.entry_boundary):
            raise ValueError("first CLOSE must be strictly post-entry")
        if self.first_close_identity is None:
            self.first_close_identity = action_identity
            self.first_close_boundary = boundary

    def settle(
        self,
        *,
        boundary: CaseFactBoundary,
        eligible_exit_identity: str | None = None,
        settlement_fact_identity: str | None = None,
        terminal_unknown_final: bool = False,
        ordinary_attempt_terminal: bool = False,
        lifecycle_ready: bool = False,
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
            self.state = OutcomeState.EXITED_KNOWN
        elif settlement_fact_identity is not None:
            require_identity(settlement_fact_identity, "settlement_fact_identity")
            if not close_is_earlier:
                raise ValueError("contract settlement must be strictly after first CLOSE")
            self.state = OutcomeState.SETTLED_KNOWN
        elif close_is_earlier and terminal_unknown_final:
            self.state = OutcomeState.TERMINAL_UNKNOWN
        else:
            del ordinary_attempt_terminal, lifecycle_ready
            return self.state
        self.terminal_case_boundary = boundary
        return self.state

    def censor_control_at_process_end(
        self,
        *,
        boundary: CaseFactBoundary,
        terminal_source: TerminalSource,
    ) -> OutcomeState:
        """Preserve the bounded lifecycle of a selected no-trade Control only."""
        if self.state is not OutcomeState.PENDING:
            return self.state
        if not boundary.is_strictly_after(self.entry_boundary):
            raise ValueError("Control terminal facts must be strictly post-entry")
        self.state = (
            OutcomeState.CENSORED_AT_STOP
            if terminal_source is TerminalSource.STOP
            else OutcomeState.CENSORED_AT_FAILURE
        )
        self.terminal_case_boundary = boundary
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


def underwriting_threshold_margins(
    *,
    economics: EntryEconomics,
    consumed_level_count: int,
    maximum_underwriting_reserved_loss_usdc: Decimal,
    minimum_net_entry_credit_usdc: Decimal,
    minimum_net_credit_to_payoff_cap_fraction: Decimal,
    maximum_entry_consumed_level_count: int,
) -> UnderwritingThresholdMargins:
    """Return the complete signed predicate-distance vector without changing action order."""
    if economics.payoff_cap_usdc <= 0:
        raise ValueError("Underwriting margin vector requires a positive payoff cap")
    for value, field_name in (
        (consumed_level_count, "consumed_level_count"),
        (maximum_entry_consumed_level_count, "maximum_entry_consumed_level_count"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
    return UnderwritingThresholdMargins(
        positive_net_credit_usdc=economics.net_entry_credit_usdc,
        credit_above_future_cost_reserve_usdc=(
            economics.net_entry_credit_usdc - economics.future_cost_reserve_usdc
        ),
        reserved_loss_limit_headroom_usdc=(
            maximum_underwriting_reserved_loss_usdc - economics.underwriting_reserved_loss_usdc
        ),
        minimum_net_credit_headroom_usdc=(
            economics.net_entry_credit_usdc - minimum_net_entry_credit_usdc
        ),
        minimum_credit_ratio_headroom=(
            economics.net_entry_credit_usdc / economics.payoff_cap_usdc
            - minimum_net_credit_to_payoff_cap_fraction
        ),
        entry_consumed_level_headroom=(maximum_entry_consumed_level_count - consumed_level_count),
    )


def select_underwriting_component(
    candidates: Iterable[UnderwritingComponentCandidate],
    *,
    maximum_underwriting_reserved_loss_usdc: Decimal,
    minimum_net_entry_credit_usdc: Decimal,
    minimum_net_credit_to_payoff_cap_fraction: Decimal,
    maximum_entry_consumed_level_count: int,
) -> UnderwritingComponentSelection | None:
    """Select one legal leg by action class, ordered margins, then stable identity."""
    selections: list[
        tuple[
            UnderwritingComponentCandidate,
            UnderwritingAction,
            UnderwritingThresholdMargins,
        ]
    ] = []
    for candidate in candidates:
        economics = candidate.economics
        margins = underwriting_threshold_margins(
            economics=economics,
            consumed_level_count=candidate.consumed_level_count,
            maximum_underwriting_reserved_loss_usdc=(maximum_underwriting_reserved_loss_usdc),
            minimum_net_entry_credit_usdc=minimum_net_entry_credit_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(minimum_net_credit_to_payoff_cap_fraction),
            maximum_entry_consumed_level_count=maximum_entry_consumed_level_count,
        )
        action = classify_underwriting_action(
            availability=UnderwritingAvailability.EVALUABLE,
            net_entry_credit_usdc=economics.net_entry_credit_usdc,
            future_cost_reserve_usdc=economics.future_cost_reserve_usdc,
            underwriting_reserved_loss_usdc=economics.underwriting_reserved_loss_usdc,
            maximum_underwriting_reserved_loss_usdc=(maximum_underwriting_reserved_loss_usdc),
            minimum_net_entry_credit_usdc=minimum_net_entry_credit_usdc,
            payoff_cap_usdc=economics.payoff_cap_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(minimum_net_credit_to_payoff_cap_fraction),
            consumed_level_count=candidate.consumed_level_count,
            maximum_entry_consumed_level_count=maximum_entry_consumed_level_count,
        )
        if action is None:
            raise RuntimeError("evaluable component selection produced no action")
        selections.append((candidate, action, margins))
    if not selections:
        return None
    action_rank = {
        UnderwritingAction.CANDIDATE: 2,
        UnderwritingAction.WATCH: 1,
        UnderwritingAction.ABSTAIN: 0,
    }

    def selection_key(
        value: tuple[
            UnderwritingComponentCandidate,
            UnderwritingAction,
            UnderwritingThresholdMargins,
        ],
    ) -> tuple[object, ...]:
        candidate, action, margins = value
        return (
            -action_rank[action],
            -margins.positive_net_credit_usdc,
            -margins.credit_above_future_cost_reserve_usdc,
            -margins.reserved_loss_limit_headroom_usdc,
            -margins.minimum_net_credit_headroom_usdc,
            -margins.minimum_credit_ratio_headroom,
            -margins.entry_consumed_level_headroom,
            candidate.economics.width_usdc_per_btc,
            candidate.long_instrument_name,
        )

    candidate_protective_leg_count = sum(
        action is UnderwritingAction.CANDIDATE for _candidate, action, _margins in selections
    )
    selected_candidate, selected_action, selected_margins = min(selections, key=selection_key)
    return UnderwritingComponentSelection(
        candidate=selected_candidate,
        action=selected_action,
        margins=selected_margins,
        selection_rule_identity=UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
        candidate_protective_leg_count=candidate_protective_leg_count,
    )


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


def compute_component_entry_economics(
    *,
    quote: ComponentBookVerticalQuote,
    future_cost_reserve_usdc: Decimal,
) -> EntryEconomics:
    """Project the component-book calculator result into frozen Underwriting reserves."""
    if quote.kind is not ComponentBookQuoteKind.ENTRY:
        raise ValueError("component entry economics requires an ENTRY quote")
    _require_non_negative(future_cost_reserve_usdc, "future_cost_reserve_usdc")
    product = product_for_identity(quote.product_spec_identity)
    contractual = max(Decimal(0), quote.payoff_cap_usdc - quote.gross_cashflow_usdc)
    fee_reserved = max(Decimal(0), quote.payoff_cap_usdc - quote.net_cashflow_usdc)
    underwriting_reserved = max(
        Decimal(0),
        quote.payoff_cap_usdc - quote.net_cashflow_usdc + future_cost_reserve_usdc,
    )
    return EntryEconomics(
        full_quantity_btc=quote.full_quantity_btc,
        required_side_total_quote_usdc=product.valuation(
            quote.short_leg.stressed.total_value + quote.long_leg.stressed.total_value,
            index_price=quote.valuation_index_price,
        ),
        gross_entry_credit_usdc=quote.gross_cashflow_usdc,
        entry_fee_reserve_usdc=quote.total_fee_reserve_usdc,
        net_entry_credit_usdc=quote.net_cashflow_usdc,
        width_usdc_per_btc=quote.width_usdc_per_btc,
        payoff_cap_usdc=quote.payoff_cap_usdc,
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


def compute_component_close_economics(
    *,
    quote: ComponentBookVerticalQuote,
    net_entry_credit_usdc: Decimal,
) -> CloseEconomics:
    """Project a CLOSE component-book quote without recalculating price or fees."""
    if quote.kind is not ComponentBookQuoteKind.CLOSE:
        raise ValueError("component close economics requires a CLOSE quote")
    product = product_for_identity(quote.product_spec_identity)
    projected_pnl = net_entry_credit_usdc + quote.net_cashflow_usdc
    return CloseEconomics(
        full_quantity_btc=quote.full_quantity_btc,
        required_close_side_total_quote_usdc=product.valuation(
            quote.short_leg.stressed.total_value + quote.long_leg.stressed.total_value,
            index_price=quote.valuation_index_price,
        ),
        gross_close_cashflow_usdc=quote.gross_cashflow_usdc,
        close_fee_reserve_usdc=quote.total_fee_reserve_usdc,
        net_close_cashflow_usdc=quote.net_cashflow_usdc,
        net_close_debit_usdc=max(Decimal(0), -quote.net_cashflow_usdc),
        projected_shadow_net_pnl_usdc=projected_pnl,
        projected_net_loss_usdc=max(Decimal(0), -projected_pnl),
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

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from short_vol_underwriting.domain import OutcomeReducer
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary, OutcomeState, TerminalSource


@dataclass(frozen=True)
class RejectedAnchor:
    slot_identity: str
    underwriting_action_identity: str
    action: str
    boundary: FactBoundary

    def __post_init__(self) -> None:
        require_identity(self.slot_identity, "slot_identity")
        require_identity(self.underwriting_action_identity, "underwriting_action_identity")
        if self.action not in {"WATCH", "ABSTAIN"}:
            raise ValueError("rejected anchor must be an EVALUABLE WATCH or ABSTAIN action")


class RejectedAnchorSelector:
    """Select one immutable causal-first rejected anchor per slot."""

    def __init__(self) -> None:
        self._selected: dict[str, RejectedAnchor] = {}

    def select_boundary(self, anchors: tuple[RejectedAnchor, ...]) -> RejectedAnchor | None:
        if not anchors:
            return None
        slots = {anchor.slot_identity for anchor in anchors}
        boundaries = {anchor.boundary for anchor in anchors}
        if len(slots) != 1 or len(boundaries) != 1:
            raise ValueError("rejected tie-break batch must share one slot and boundary")
        slot = anchors[0].slot_identity
        selected = self._selected.get(slot)
        if selected is not None:
            return selected
        selected = min(anchors, key=lambda anchor: anchor.underwriting_action_identity)
        self._selected[slot] = selected
        return selected


@dataclass
class Observation:
    outcome_contract_identity: str
    anchor_identity: str
    observation_identity: str
    entry_boundary: FactBoundary
    rejected: bool
    cohort_enrolled: bool
    reducer: OutcomeReducer
    selected_exit_identity: str | None = None
    terminal_outcome_identity: str | None = None

    @classmethod
    def admitted(
        cls,
        *,
        outcome_contract_identity: str,
        shadow_entry_identity: str,
        entry_boundary: FactBoundary,
        cohort_enrolled: bool,
    ) -> Observation:
        require_identity(outcome_contract_identity, "outcome_contract_identity")
        require_identity(shadow_entry_identity, "shadow_entry_identity")
        identity = canonical_identity(
            "ShadowObservationIdentity",
            outcome_contract_identity,
            shadow_entry_identity,
        )
        return cls(
            outcome_contract_identity=outcome_contract_identity,
            anchor_identity=shadow_entry_identity,
            observation_identity=identity,
            entry_boundary=entry_boundary,
            rejected=False,
            cohort_enrolled=cohort_enrolled,
            reducer=OutcomeReducer(entry_boundary),
        )

    @classmethod
    def rejected_counterfactual(
        cls,
        *,
        outcome_contract_identity: str,
        rejected_anchor_identity: str,
        entry_boundary: FactBoundary,
        cohort_enrolled: bool,
    ) -> Observation:
        require_identity(outcome_contract_identity, "outcome_contract_identity")
        require_identity(rejected_anchor_identity, "rejected_anchor_identity")
        identity = canonical_identity(
            "RejectedCounterfactualObservationIdentity",
            rejected_anchor_identity,
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
        )
        return cls(
            outcome_contract_identity=outcome_contract_identity,
            anchor_identity=rejected_anchor_identity,
            observation_identity=identity,
            entry_boundary=entry_boundary,
            rejected=True,
            cohort_enrolled=cohort_enrolled,
            reducer=OutcomeReducer(entry_boundary),
        )

    @property
    def state(self) -> OutcomeState:
        return self.reducer.state

    def latch_close(self, action_identity: str, boundary: FactBoundary) -> None:
        self.reducer.latch_close(action_identity, boundary)

    def accept_eligible_exit(
        self,
        *,
        close_opportunity_evaluation_identity: str,
        boundary: FactBoundary,
    ) -> str | None:
        if self.state is not OutcomeState.PENDING:
            return None
        require_identity(
            close_opportunity_evaluation_identity,
            "close_opportunity_evaluation_identity",
        )
        first_close = self.reducer.first_close_identity
        if first_close is None:
            raise ValueError("eligible exit requires a first CLOSE")
        label = (
            "RejectedCounterfactualExitIdentity"
            if self.rejected
            else "ShadowCounterfactualExitIdentity"
        )
        exit_identity = canonical_identity(
            label,
            self.observation_identity,
            first_close,
            close_opportunity_evaluation_identity,
        )
        state = self.reducer.settle(
            boundary=boundary,
            eligible_exit_identity=exit_identity,
        )
        if state is not OutcomeState.MATURE_KNOWN:
            raise RuntimeError("eligible exit did not mature observation")
        self.selected_exit_identity = exit_identity
        self._freeze_terminal_identity(boundary)
        return exit_identity

    def settle_without_exit(
        self,
        *,
        boundary: FactBoundary,
        ordinary_attempt_terminal: bool,
        lifecycle_ready: bool,
        terminal_source: TerminalSource | None = None,
    ) -> OutcomeState:
        previous = self.state
        state = self.reducer.settle(
            boundary=boundary,
            ordinary_attempt_terminal=ordinary_attempt_terminal,
            lifecycle_ready=lifecycle_ready,
            terminal_source=terminal_source,
        )
        if previous is OutcomeState.PENDING and state is not OutcomeState.PENDING:
            self._freeze_terminal_identity(boundary)
        return state

    def _freeze_terminal_identity(self, boundary: FactBoundary) -> None:
        label = (
            "RejectedCounterfactualOutcomeIdentity" if self.rejected else "ShadowOutcomeIdentity"
        )
        self.terminal_outcome_identity = canonical_identity(
            label,
            self.observation_identity,
            self.state.value,
            boundary.as_object(),
        )


@dataclass
class AlignedPair:
    pair_identity: str
    pair_anchor_identity: str
    policy_arm: str
    alternative_arm: str
    cohort_enrolled: bool
    terminal_state: OutcomeState | None = None
    terminal_boundary: FactBoundary | None = None
    trade_outcome_identity: str | None = None
    trade_net_pnl_usdc: Decimal | None = None
    policy_advantage_usdc: Decimal | None = None

    @classmethod
    def for_admitted(
        cls,
        *,
        outcome_contract_identity: str,
        shadow_entry_identity: str,
        cohort_enrolled: bool,
    ) -> AlignedPair:
        return cls._new(
            outcome_contract_identity=outcome_contract_identity,
            anchor_identity=shadow_entry_identity,
            policy_arm="SHADOW_TRADE",
            alternative_arm="NO_TRADE",
            cohort_enrolled=cohort_enrolled,
        )

    @classmethod
    def for_rejected(
        cls,
        *,
        outcome_contract_identity: str,
        rejected_anchor_identity: str,
        cohort_enrolled: bool,
    ) -> AlignedPair:
        return cls._new(
            outcome_contract_identity=outcome_contract_identity,
            anchor_identity=rejected_anchor_identity,
            policy_arm="NO_TRADE",
            alternative_arm="REJECTED_COUNTERFACTUAL_TRADE",
            cohort_enrolled=cohort_enrolled,
        )

    @classmethod
    def _new(
        cls,
        *,
        outcome_contract_identity: str,
        anchor_identity: str,
        policy_arm: str,
        alternative_arm: str,
        cohort_enrolled: bool,
    ) -> AlignedPair:
        require_identity(outcome_contract_identity, "outcome_contract_identity")
        require_identity(anchor_identity, "pair_anchor_identity")
        identity = canonical_identity(
            "AlignedPolicyNoTradePairIdentity",
            outcome_contract_identity,
            anchor_identity,
            policy_arm,
            alternative_arm,
        )
        return cls(
            pair_identity=identity,
            pair_anchor_identity=anchor_identity,
            policy_arm=policy_arm,
            alternative_arm=alternative_arm,
            cohort_enrolled=cohort_enrolled,
        )

    def terminalize(
        self,
        *,
        state: OutcomeState,
        terminal_boundary: FactBoundary,
        trade_outcome_identity: str,
        trade_net_pnl_usdc: Decimal | None,
    ) -> None:
        if self.terminal_state is not None:
            raise ValueError("aligned pair is terminal")
        if state is OutcomeState.PENDING:
            raise ValueError("aligned pair cannot durably terminalize as PENDING")
        require_identity(trade_outcome_identity, "trade_outcome_identity")
        if state is OutcomeState.MATURE_KNOWN:
            if trade_net_pnl_usdc is None or not trade_net_pnl_usdc.is_finite():
                raise ValueError("MATURE_KNOWN pair requires finite trade PnL")
            self.policy_advantage_usdc = (
                trade_net_pnl_usdc if self.policy_arm == "SHADOW_TRADE" else -trade_net_pnl_usdc
            )
        elif trade_net_pnl_usdc is not None:
            raise ValueError("unknown/censored pair cannot carry comparable trade PnL")
        self.terminal_state = state
        self.terminal_boundary = terminal_boundary
        self.trade_outcome_identity = trade_outcome_identity
        self.trade_net_pnl_usdc = trade_net_pnl_usdc

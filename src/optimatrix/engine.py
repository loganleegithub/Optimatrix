from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from optimatrix.lifecycle import (
    DecisionCase,
    EntryResult,
    PositionOutcome,
    PositionRiskAction,
    PositionRiskObservation,
    ShadowPosition,
    acquire_entry,
    arm_exit_instruction,
    dispose_residual_wings,
    evaluate_position,
    finalize_if_terminal,
    project_exit_instruction,
    settle_position,
)
from optimatrix.market import MarketContext, OptionQuote
from optimatrix.persistence import (
    CaseJournal,
    decision_case_to_object,
    entry_result_to_object,
    position_to_object,
)
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.radar import (
    Decision,
    RadarDecision,
    evaluate_radar_unit,
    require_radar_decision_identity,
)
from optimatrix.session import current_deribit_session, expiry_is_current_session


class ShadowEngine:
    """One direct BTC 0DTE two-sided Shadow business owner.

    It owns decisions and position state only. A live adapter may translate Deribit
    public facts into OptionQuote/MarketContext objects and call these methods.
    """

    def __init__(self, *, policy: BtcShortVolPolicy, case_root: Path) -> None:
        self.policy = policy
        self.case_root = case_root

    def evaluate(self, *, quotes: tuple[OptionQuote, ...], context: MarketContext) -> RadarDecision:
        session = current_deribit_session(context.now, phase_policy=self.policy.session)
        current_expiry_quotes = tuple(
            quote for quote in quotes if expiry_is_current_session(quote.expiry, session)
        )
        decision, _selection = evaluate_radar_unit(
            session=session,
            context=context,
            quotes=current_expiry_quotes,
            policy=self.policy,
        )
        return decision

    def open_decision_case(
        self,
        *,
        decision: RadarDecision,
        opened_at: datetime,
    ) -> DecisionCase:
        if decision.decision is not Decision.CANDIDATE:
            raise ValueError("only a CANDIDATE opens an entry-attempt Case")
        require_radar_decision_identity(decision, policy_identity=self.policy.identity)
        case = DecisionCase.open(opened_at=opened_at, radar_decision=decision)
        journal = CaseJournal(self.case_root, case.case_identity)
        if journal.read():
            raise ValueError("Decision Case already exists")
        journal.append(
            "DECISION_OPENED",
            {
                "decision_case": decision_case_to_object(case),
                "policy_identity": self.policy.identity,
            },
        )
        return case

    def attempt_entry(
        self,
        *,
        case: DecisionCase,
        quotes: tuple[OptionQuote, ...],
        context: MarketContext,
        attempted_at: datetime,
        public_combo_observed: bool = False,
        allow_wings_only_fallback: bool = False,
    ) -> tuple[EntryResult, ShadowPosition | None]:
        if attempted_at <= case.opened_at:
            raise ValueError("entry attempt must be strictly after the decision")
        journal = CaseJournal(self.case_root, case.case_identity)
        events = journal.read()
        if not events or events[0].get("kind") != "DECISION_OPENED":
            raise ValueError("entry attempt requires the persisted Decision Case")
        persisted_case = journal.latest_decision_case()
        if persisted_case != case:
            raise ValueError("entry attempt does not match the persisted Decision Case")
        require_radar_decision_identity(
            case.radar_decision,
            policy_identity=self.policy.identity,
        )
        if any(event.get("kind") == "ENTRY_TERMINAL" for event in events):
            raise ValueError("Decision Case already has a terminal entry result")
        result, position = acquire_entry(
            case=case,
            quotes=quotes,
            context=context,
            policy=self.policy,
            attempted_at=attempted_at,
            public_combo_observed=public_combo_observed,
            allow_wings_only_fallback=allow_wings_only_fallback,
        )
        journal.append(
            "ENTRY_TERMINAL",
            {
                "entry_result": entry_result_to_object(result),
                "position_identity": position.position_identity if position is not None else None,
            },
        )
        if position is not None:
            journal.append("POSITION_CHECKPOINT", position_to_object(position))
        return result, position

    def observe_position(
        self,
        *,
        position: ShadowPosition,
        quotes: tuple[OptionQuote, ...],
        context: MarketContext,
    ) -> PositionRiskObservation:
        session = current_deribit_session(context.now, phase_policy=self.policy.session)
        observation = evaluate_position(
            position=position,
            session=session,
            context=context,
            quotes=quotes,
            policy=self.policy,
        )
        instruction = observation.instruction
        if observation.action is PositionRiskAction.MONITORING or instruction is None:
            return observation
        if observation.action is PositionRiskAction.EXIT_DUTY_ARMED:
            position.last_risk_observed_at = observation.observed_at
            position.last_risk_context_known = observation.risk_context_known
            position.last_risk_blockers = observation.blockers
            if arm_exit_instruction(position=position, instruction=instruction):
                CaseJournal(self.case_root, position.case_identity).append(
                    "POSITION_CHECKPOINT",
                    position_to_object(position),
                )
            return observation
        projection_changed, attempt_changed, blockers = project_exit_instruction(
            position=position,
            instruction=instruction,
            quotes=quotes,
            context=context,
            policy=self.policy,
        )
        if not projection_changed and not attempt_changed:
            return PositionRiskObservation(
                observed_at=context.now,
                action=PositionRiskAction.EXIT_DUTY_PENDING,
                risk_context_known=not blockers,
                blockers=blockers,
                instruction=instruction,
            )
        journal = CaseJournal(self.case_root, position.case_identity)
        outcome = finalize_if_terminal(
            position=position,
            at=context.now,
            valuation_index=context.index_price,
        )
        journal.append("POSITION_CHECKPOINT", position_to_object(position))
        if outcome is not None:
            journal.append("OUTCOME", _outcome_projection(outcome))
        action = (
            PositionRiskAction.PORTFOLIO_TERMINAL
            if outcome is not None
            else PositionRiskAction.SHORT_RISK_FLAT
            if not position.has_short_risk
            else PositionRiskAction.SHORT_RISK_REDUCED
            if projection_changed
            else PositionRiskAction.EXIT_DUTY_PENDING
        )
        return PositionRiskObservation(
            observed_at=context.now,
            action=action,
            risk_context_known=not blockers,
            blockers=blockers,
            instruction=instruction,
        )

    def dispose_wings(
        self,
        *,
        position: ShadowPosition,
        quotes: tuple[OptionQuote, ...],
        context: MarketContext,
    ) -> PositionOutcome | None:
        changed = dispose_residual_wings(position=position, quotes=quotes, context=context)
        if not changed:
            return None
        outcome = finalize_if_terminal(
            position=position,
            at=context.now,
            valuation_index=context.index_price,
        )
        journal = CaseJournal(self.case_root, position.case_identity)
        journal.append("POSITION_CHECKPOINT", position_to_object(position))
        if outcome is not None:
            journal.append("OUTCOME", _outcome_projection(outcome))
        return outcome

    def settle(
        self,
        *,
        position: ShadowPosition,
        delivery_price: Decimal,
        settled_at: datetime,
    ) -> PositionOutcome:
        if position.outcome is not None:
            return position.outcome
        outcome = settle_position(
            position=position,
            delivery_price=delivery_price,
            settled_at=settled_at,
        )
        journal = CaseJournal(self.case_root, position.case_identity)
        journal.append("POSITION_CHECKPOINT", position_to_object(position))
        journal.append("OUTCOME", _outcome_projection(outcome))
        return outcome

    def recover_decision_case(self, case_identity: str) -> DecisionCase | None:
        case = CaseJournal(self.case_root, case_identity).latest_decision_case()
        if case is not None:
            require_radar_decision_identity(
                case.radar_decision,
                policy_identity=self.policy.identity,
            )
        return case

    def recover_position(self, case_identity: str) -> ShadowPosition | None:
        journal = CaseJournal(self.case_root, case_identity)
        position = journal.latest_position()
        if position is not None:
            if self.recover_decision_case(case_identity) is None:
                raise ValueError("Position recovery lacks its persisted Decision Case")
            if position.case_identity != case_identity:
                raise ValueError("Position recovery Case identity mismatch")
        return position


def _outcome_projection(outcome: PositionOutcome) -> dict[str, object]:
    return {
        "outcome_identity": outcome.outcome_identity,
        "terminal_at": outcome.terminal_at.isoformat(),
        "terminal_method": outcome.terminal_method,
        "entry_status": outcome.entry_status.value,
        "strategy_outcome_eligible": outcome.strategy_outcome_eligible,
        "outcome_population": outcome.outcome_population,
        "strategy_ineligibility_reason": outcome.strategy_ineligibility_reason,
        "first_exit_reason": (
            outcome.first_exit_reason.value if outcome.first_exit_reason is not None else None
        ),
        "short_risk_flat_at": (
            outcome.short_risk_flat_at.isoformat()
            if outcome.short_risk_flat_at is not None
            else None
        ),
        "put_side_native_pnl": str(outcome.put_side_native_pnl),
        "call_side_native_pnl": str(outcome.call_side_native_pnl),
        "total_native_pnl": str(outcome.total_native_pnl),
        "put_side_boundary_valued_pnl_usd": str(outcome.put_side_boundary_valued_pnl_usd),
        "call_side_boundary_valued_pnl_usd": str(outcome.call_side_boundary_valued_pnl_usd),
        "boundary_valued_total_usd_pnl": str(outcome.boundary_valued_total_usd_pnl),
        "terminal_valued_total_usd_pnl": str(outcome.terminal_valued_total_usd_pnl),
        "double_side_stop": outcome.double_side_stop,
        "put_side_delivery_fee_native": str(outcome.put_side_delivery_fee_native),
        "call_side_delivery_fee_native": str(outcome.call_side_delivery_fee_native),
        "total_delivery_fee_native": str(outcome.total_delivery_fee_native),
        "residual_wings_settled": outcome.residual_wings_settled,
        "residual_wing_count": outcome.residual_wing_count,
        "put_exit_attempt_count": outcome.put_exit_attempt_count,
        "call_exit_attempt_count": outcome.call_exit_attempt_count,
        "exit_quote_missing_block_count": outcome.exit_quote_missing_block_count,
        "exit_quote_not_future_block_count": outcome.exit_quote_not_future_block_count,
        "exit_quote_stale_block_count": outcome.exit_quote_stale_block_count,
        "exit_pair_incoherent_block_count": outcome.exit_pair_incoherent_block_count,
        "exit_pair_unexecutable_block_count": outcome.exit_pair_unexecutable_block_count,
        "short_only_exit_side_count": outcome.short_only_exit_side_count,
        "first_exit_to_short_risk_flat_ms": outcome.first_exit_to_short_risk_flat_ms,
    }

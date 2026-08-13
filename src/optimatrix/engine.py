from __future__ import annotations

from datetime import datetime

from optimatrix.case_journal import CaseJournal
from optimatrix.decision import (
    DecisionRecord,
    DecisionWindow,
    MarketObservation,
    schedule_decision_windows,
)
from optimatrix.lifecycle import (
    ShadowEntryEvaluation,
    ShadowExitEvaluation,
    ShadowMonitorEvaluation,
    TradeCase,
    evaluate_shadow_entry,
    evaluate_shadow_exit,
    monitor_shadow_position,
    open_trade_case,
    settle_shadow_position,
)
from optimatrix.market import ExpirySettlementFact, MarketContext, OptionQuote
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.radar import BtcWindowAssessment, evaluate_btc_short_vol_window
from optimatrix.risk import ShadowCapacity
from optimatrix.session import current_deribit_session


class Btc0DteShortVolEngine:
    """Direct composer for the implemented BTC 0DTE public Shadow path."""

    def __init__(self, *, policy: BtcShortVolPolicy) -> None:
        self.policy = policy

    def decision_windows(self, *, at: datetime) -> tuple[DecisionWindow, ...]:
        session = current_deribit_session(at, phase_policy=self.policy.session)
        return schedule_decision_windows(
            session=session,
            channel_id=self.policy.channel_id,
            policy=self.policy.window,
        )

    def capture_observation(
        self,
        *,
        quotes: tuple[OptionQuote, ...],
        context: MarketContext,
    ) -> MarketObservation:
        return MarketObservation.capture(
            channel_id=self.policy.channel_id,
            policy=self.policy.observation,
            context=context,
            quotes=quotes,
        )

    def assess_window(
        self,
        *,
        ledger: ObservationLedger,
        window: DecisionWindow,
        observation: MarketObservation | None,
        capacity: ShadowCapacity | None,
        known_at: datetime,
    ) -> BtcWindowAssessment:
        expected = {item.identity for item in self.decision_windows(at=window.starts_at)}
        if window.identity not in expected:
            raise ValueError("DecisionWindow does not belong to the current Policy schedule")
        assessment = evaluate_btc_short_vol_window(
            window=window,
            observation=observation,
            capacity=capacity,
            policy=self.policy,
            known_at=known_at,
        )
        ledger.append(assessment.record)
        return assessment

    def open_case(self, *, journal: CaseJournal, record: DecisionRecord) -> TradeCase:
        case = open_trade_case(record, self.policy)
        journal.append(case)
        return case

    def evaluate_entry(
        self,
        *,
        journal: CaseJournal,
        case: TradeCase,
        observation: MarketObservation | None,
        known_at: datetime,
    ) -> tuple[TradeCase, ShadowEntryEvaluation]:
        updated, evaluation = evaluate_shadow_entry(
            case,
            observation=observation,
            policy=self.policy,
            known_at=known_at,
        )
        journal.append(updated)
        return updated, evaluation

    def monitor_position(
        self,
        *,
        journal: CaseJournal,
        case: TradeCase,
        observation: MarketObservation,
    ) -> tuple[TradeCase, ShadowMonitorEvaluation]:
        updated, evaluation = monitor_shadow_position(
            case,
            observation=observation,
            policy=self.policy,
        )
        journal.append(updated)
        return updated, evaluation

    def evaluate_exit(
        self,
        *,
        journal: CaseJournal,
        case: TradeCase,
        observation: MarketObservation,
    ) -> tuple[TradeCase, ShadowExitEvaluation]:
        updated, evaluation = evaluate_shadow_exit(
            case,
            observation=observation,
            policy=self.policy,
        )
        journal.append(updated)
        return updated, evaluation

    def settle_position(
        self,
        *,
        journal: CaseJournal,
        case: TradeCase,
        settlement: ExpirySettlementFact,
    ) -> TradeCase:
        updated = settle_shadow_position(
            case,
            settlement=settlement,
            policy=self.policy,
        )
        journal.append(updated)
        return updated

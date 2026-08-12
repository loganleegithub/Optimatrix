from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity, require_identity
from optimatrix.market import BreakoutState, EventState, MarketContext, OptionQuote
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import (
    Action,
    LegExecution,
    VerticalExecution,
    execute_leg,
    price_close_vertical,
    price_credit_vertical,
    settle_option_leg,
)
from optimatrix.radar import RadarDecision
from optimatrix.session import DeribitSession, SessionPhase
from optimatrix.structure import IronCondorCandidate


class EntryRoute(StrEnum):
    TWO_VERTICALS = "TWO_VERTICALS"
    WINGS_ONLY_FALLBACK = "WINGS_ONLY_FALLBACK"


class EntryStatus(StrEnum):
    FULL_ENTRY = "FULL_ENTRY"
    PUT_SIDE_ONLY = "PUT_SIDE_ONLY"
    CALL_SIDE_ONLY = "CALL_SIDE_ONLY"
    TWO_SIDES_INCOHERENT = "TWO_SIDES_INCOHERENT"
    WINGS_ONLY = "WINGS_ONLY"
    NO_ENTRY = "NO_ENTRY"


class Side(StrEnum):
    PUT = "PUT"
    CALL = "CALL"


class SideState(StrEnum):
    NOT_OPEN = "NOT_OPEN"
    CREDIT_VERTICAL_OPEN = "CREDIT_VERTICAL_OPEN"
    SHORT_FLAT_LONG_WING = "SHORT_FLAT_LONG_WING"
    TERMINAL = "TERMINAL"


class PositionState(StrEnum):
    MONITORING = "MONITORING"
    EXIT_REQUIRED = "EXIT_REQUIRED"
    SHORT_RISK_FLAT = "SHORT_RISK_FLAT"
    TERMINAL = "TERMINAL"


class ExitReason(StrEnum):
    ENTRY_ACQUISITION_INCOMPLETE = "ENTRY_ACQUISITION_INCOMPLETE"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAXIMUM_LOSS = "MAXIMUM_LOSS"
    PUT_SIDE_DELTA = "PUT_SIDE_DELTA"
    CALL_SIDE_DELTA = "CALL_SIDE_DELTA"
    PUT_SIDE_ADVERSE_MOVE = "PUT_SIDE_ADVERSE_MOVE"
    CALL_SIDE_ADVERSE_MOVE = "CALL_SIDE_ADVERSE_MOVE"
    GAMMA_EXPANSION = "GAMMA_EXPANSION"
    EVENT_OR_SHOCK = "EVENT_OR_SHOCK"
    CONCENTRATED_STRIKE_BREAKOUT = "CONCENTRATED_STRIKE_BREAKOUT"
    LATEST_SHORT_RISK_EXIT = "LATEST_SHORT_RISK_EXIT"
    DELIVERY_TWAP = "DELIVERY_TWAP"


class ExitScope(StrEnum):
    PUT_SIDE = "PUT_SIDE"
    CALL_SIDE = "CALL_SIDE"
    BOTH_SIDES = "BOTH_SIDES"


@dataclass(frozen=True)
class DecisionCase:
    case_identity: str
    opened_at: datetime
    radar_decision: RadarDecision
    structure: IronCondorCandidate

    @classmethod
    def open(cls, *, opened_at: datetime, radar_decision: RadarDecision) -> DecisionCase:
        if opened_at.tzinfo is None:
            raise ValueError("Decision Case boundary must be timezone-aware")
        if radar_decision.structure is None:
            raise ValueError("Decision Case requires one selected structure")
        identity = canonical_identity(
            "TwoSidedShadowDecisionCaseV1",
            radar_decision.decision_identity,
            opened_at.isoformat(),
        )
        return cls(identity, opened_at, radar_decision, radar_decision.structure)


@dataclass(frozen=True)
class EntryResult:
    entry_identity: str
    attempted_at: datetime
    route: EntryRoute
    public_combo_observed: bool
    status: EntryStatus
    put_vertical_execution: VerticalExecution | None
    call_vertical_execution: VerticalExecution | None
    wing_executions: tuple[LegExecution, ...]
    blockers: tuple[str, ...]


@dataclass
class SidePosition:
    side: Side
    short_quote: OptionQuote
    long_quote: OptionQuote
    quantity: Decimal
    state: SideState
    native_cashflow_after_fees: Decimal
    boundary_valued_cashflow_usd: Decimal
    short_open: bool
    long_open: bool
    delivery_fee_native: Decimal = Decimal(0)
    exit_requested_at: datetime | None = None
    exit_requested_reason: ExitReason | None = None
    short_risk_exit_at: datetime | None = None
    terminal_at: datetime | None = None
    exit_reason: ExitReason | None = None
    short_exit_execution: LegExecution | None = None
    long_exit_execution: LegExecution | None = None
    last_exit_attempt_at: datetime | None = None
    exit_attempt_count: int = 0
    quote_missing_block_count: int = 0
    pair_incoherent_block_count: int = 0
    pair_unexecutable_block_count: int = 0
    short_only_exit_used: bool = False


@dataclass(frozen=True)
class PositionInstruction:
    instruction_identity: str
    at: datetime
    scope: ExitScope
    reason: ExitReason


@dataclass(frozen=True)
class PositionOutcome:
    outcome_identity: str
    terminal_at: datetime
    terminal_method: str
    entry_status: EntryStatus
    first_exit_reason: ExitReason | None
    first_exit_at: datetime | None
    short_risk_flat_at: datetime | None
    put_side_exit_at: datetime | None
    call_side_exit_at: datetime | None
    put_side_native_pnl: Decimal
    call_side_native_pnl: Decimal
    total_native_pnl: Decimal
    put_side_boundary_valued_pnl_usd: Decimal
    call_side_boundary_valued_pnl_usd: Decimal
    boundary_valued_total_usd_pnl: Decimal
    terminal_valued_total_usd_pnl: Decimal
    double_side_stop: bool
    put_side_delivery_fee_native: Decimal
    call_side_delivery_fee_native: Decimal
    total_delivery_fee_native: Decimal
    residual_wings_settled: int
    residual_wing_count: int
    put_exit_attempt_count: int
    call_exit_attempt_count: int
    exit_quote_missing_block_count: int
    exit_pair_incoherent_block_count: int
    exit_pair_unexecutable_block_count: int
    short_only_exit_side_count: int
    first_exit_to_short_risk_flat_ms: int | None

    @property
    def strategy_outcome_eligible(self) -> bool:
        """Only a coherent four-leg acquisition belongs to strategy economics."""

        return self.entry_status is EntryStatus.FULL_ENTRY

    @property
    def outcome_population(self) -> str:
        return (
            "IRON_CONDOR_STRATEGY"
            if self.strategy_outcome_eligible
            else "ENTRY_ACQUISITION_OPERATIONAL"
        )

    @property
    def strategy_ineligibility_reason(self) -> str | None:
        if self.strategy_outcome_eligible:
            return None
        return f"ENTRY_STATUS_{self.entry_status.value}"


@dataclass
class ShadowPosition:
    position_identity: str
    case_identity: str
    entry_identity: str
    opened_at: datetime
    entry_status: EntryStatus
    product_index_at_entry: Decimal
    initial_net_credit_native: Decimal
    initial_net_credit_usd: Decimal
    put_side: SidePosition
    call_side: SidePosition
    state: PositionState = PositionState.MONITORING
    first_instruction: PositionInstruction | None = None
    instructions: list[PositionInstruction] = field(default_factory=list)
    short_risk_flat_at: datetime | None = None
    terminal_at: datetime | None = None
    outcome: PositionOutcome | None = None

    @property
    def has_short_risk(self) -> bool:
        return self.put_side.short_open or self.call_side.short_open

    @property
    def residual_wing_count(self) -> int:
        return int(self.put_side.long_open) + int(self.call_side.long_open)

    @property
    def has_pending_exit(self) -> bool:
        return any(
            side.short_open and side.exit_requested_reason is not None
            for side in (self.put_side, self.call_side)
        )


def acquire_entry(
    *,
    case: DecisionCase,
    quotes: tuple[OptionQuote, ...],
    context: MarketContext,
    policy: BtcShortVolPolicy,
    attempted_at: datetime,
    public_combo_observed: bool = False,
    allow_wings_only_fallback: bool = False,
) -> tuple[EntryResult, ShadowPosition | None]:
    if attempted_at.tzinfo is None or context.now.tzinfo is None:
        raise ValueError("entry boundaries must be timezone-aware")
    if attempted_at <= case.opened_at:
        raise ValueError("entry attempt must be strictly after the decision")
    if context.now != attempted_at:
        raise ValueError("entry pricing context must belong to the attempt boundary")
    decision_received_ms = int(case.opened_at.timestamp() * 1000)
    attempted_received_ms = int(attempted_at.timestamp() * 1000)
    if attempted_received_ms - decision_received_ms > policy.shadow.entry_acquisition_window_ms:
        result = _entry_result(
            case=case,
            attempted_at=attempted_at,
            route=EntryRoute.TWO_VERTICALS,
            status=EntryStatus.NO_ENTRY,
            public_combo_observed=public_combo_observed,
            blockers=("ENTRY_ACQUISITION_DEADLINE_EXCEEDED",),
        )
        return result, None

    selected = case.structure
    by_name = {quote.instrument_name: quote for quote in quotes}
    required_names = (
        selected.long_put.instrument_name,
        selected.short_put.instrument_name,
        selected.short_call.instrument_name,
        selected.long_call.instrument_name,
    )
    missing = tuple(name for name in required_names if name not in by_name)
    if missing:
        result = _entry_result(
            case=case,
            attempted_at=attempted_at,
            route=EntryRoute.TWO_VERTICALS,
            status=EntryStatus.NO_ENTRY,
            public_combo_observed=public_combo_observed,
            blockers=tuple(f"MISSING_QUOTE:{name}" for name in missing),
        )
        return result, None
    long_put, short_put, short_call, long_call = (by_name[name] for name in required_names)
    put_pair_eligible = _entry_pair_eligible(
        short_put,
        long_put,
        decision_received_ms=decision_received_ms,
        attempted_received_ms=attempted_received_ms,
        maximum_source_skew_ms=policy.shadow.maximum_pair_source_skew_ms,
        maximum_receive_skew_ms=policy.shadow.maximum_pair_receive_skew_ms,
    )
    call_pair_eligible = _entry_pair_eligible(
        short_call,
        long_call,
        decision_received_ms=decision_received_ms,
        attempted_received_ms=attempted_received_ms,
        maximum_source_skew_ms=policy.shadow.maximum_pair_source_skew_ms,
        maximum_receive_skew_ms=policy.shadow.maximum_pair_receive_skew_ms,
    )
    four_leg_eligible = _four_leg_entry_eligible(
        (long_put, short_put, short_call, long_call),
        decision_received_ms=decision_received_ms,
        attempted_received_ms=attempted_received_ms,
        maximum_source_skew_ms=policy.shadow.maximum_pair_source_skew_ms,
        maximum_receive_skew_ms=policy.shadow.maximum_pair_receive_skew_ms,
    )
    put_execution = (
        price_credit_vertical(
            short_quote=short_put,
            long_quote=long_put,
            quantity=policy.structure.target_quantity,
            index_price=context.index_price,
        )
        if put_pair_eligible
        else None
    )
    call_execution = (
        price_credit_vertical(
            short_quote=short_call,
            long_quote=long_call,
            quantity=policy.structure.target_quantity,
            index_price=context.index_price,
        )
        if call_pair_eligible
        else None
    )
    route = (
        EntryRoute.WINGS_ONLY_FALLBACK if allow_wings_only_fallback else EntryRoute.TWO_VERTICALS
    )
    wing_executions: tuple[LegExecution, ...] = ()
    blockers: list[str] = []
    if not put_pair_eligible:
        blockers.append("PUT_ENTRY_PAIR_NOT_STRICTLY_FUTURE_OR_COHERENT")
    if not call_pair_eligible:
        blockers.append("CALL_ENTRY_PAIR_NOT_STRICTLY_FUTURE_OR_COHERENT")
    if put_execution is not None and call_execution is not None and four_leg_eligible:
        status = EntryStatus.FULL_ENTRY
    elif put_execution is not None and call_execution is not None:
        status = EntryStatus.TWO_SIDES_INCOHERENT
        blockers.append("FOUR_LEG_ENTRY_NOT_COHERENT")
    elif put_execution is not None:
        status = EntryStatus.PUT_SIDE_ONLY
        blockers.append("CALL_VERTICAL_NOT_EXECUTABLE")
    elif call_execution is not None:
        status = EntryStatus.CALL_SIDE_ONLY
        blockers.append("PUT_VERTICAL_NOT_EXECUTABLE")
    elif allow_wings_only_fallback:
        wings_eligible = _entry_pair_eligible(
            long_put,
            long_call,
            decision_received_ms=decision_received_ms,
            attempted_received_ms=attempted_received_ms,
            maximum_source_skew_ms=policy.shadow.maximum_pair_source_skew_ms,
            maximum_receive_skew_ms=policy.shadow.maximum_pair_receive_skew_ms,
        )
        put_wing = (
            execute_leg(
                long_put,
                action=Action.BUY,
                quantity=policy.structure.target_quantity,
                index_price=context.index_price,
            )
            if wings_eligible
            else None
        )
        call_wing = (
            execute_leg(
                long_call,
                action=Action.BUY,
                quantity=policy.structure.target_quantity,
                index_price=context.index_price,
            )
            if wings_eligible
            else None
        )
        if put_wing is not None and call_wing is not None:
            status = EntryStatus.WINGS_ONLY
            wing_executions = (put_wing, call_wing)
            blockers.extend(("PUT_SHORT_NOT_EXECUTABLE", "CALL_SHORT_NOT_EXECUTABLE"))
        else:
            status = EntryStatus.NO_ENTRY
            blockers.append("WINGS_ONLY_FALLBACK_NOT_EXECUTABLE")
    else:
        status = EntryStatus.NO_ENTRY
        blockers.extend(("PUT_VERTICAL_NOT_EXECUTABLE", "CALL_VERTICAL_NOT_EXECUTABLE"))

    result = _entry_result(
        case=case,
        attempted_at=attempted_at,
        route=route,
        public_combo_observed=public_combo_observed,
        status=status,
        put_vertical_execution=put_execution,
        call_vertical_execution=call_execution,
        wing_executions=wing_executions,
        blockers=tuple(blockers),
    )
    if status is EntryStatus.NO_ENTRY:
        return result, None
    position = _position_from_entry(
        case=case,
        result=result,
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        index_price=context.index_price,
        quantity=policy.structure.target_quantity,
    )
    return result, position


def evaluate_position(
    *,
    position: ShadowPosition,
    session: DeribitSession,
    context: MarketContext,
    quotes: tuple[OptionQuote, ...],
    policy: BtcShortVolPolicy,
) -> PositionInstruction | None:
    if position.state is PositionState.TERMINAL or not position.has_short_risk:
        return None
    pending = _pending_exit_instruction(position, context.now)
    if pending is not None:
        return pending
    by_name = {quote.instrument_name: quote for quote in quotes}
    estimated_pnl = _estimated_position_native_pnl(
        position=position,
        quotes=by_name,
        index_price=context.index_price,
    )
    credit = position.initial_net_credit_native
    if estimated_pnl is not None:
        if estimated_pnl >= credit * policy.position.take_profit_fraction_of_credit:
            return _instruction(position, context.now, ExitScope.BOTH_SIDES, ExitReason.TAKE_PROFIT)
        if estimated_pnl <= -(credit * policy.position.maximum_loss_multiple_of_credit):
            return _instruction(
                position,
                context.now,
                ExitScope.BOTH_SIDES,
                ExitReason.MAXIMUM_LOSS,
            )
    if session.phase is SessionPhase.DELIVERY_TWAP:
        return _instruction(position, context.now, ExitScope.BOTH_SIDES, ExitReason.DELIVERY_TWAP)
    if session.minutes_to_expiry <= policy.position.latest_short_risk_exit_minutes_to_expiry:
        return _instruction(
            position,
            context.now,
            ExitScope.BOTH_SIDES,
            ExitReason.LATEST_SHORT_RISK_EXIT,
        )
    put_threat = _side_threatened(
        side=position.put_side,
        current_quote=by_name.get(position.put_side.short_quote.instrument_name),
        context=context,
        entry_index=position.product_index_at_entry,
        policy=policy,
    )
    call_threat = _side_threatened(
        side=position.call_side,
        current_quote=by_name.get(position.call_side.short_quote.instrument_name),
        context=context,
        entry_index=position.product_index_at_entry,
        policy=policy,
    )
    if context.event_state in {EventState.LIVE_EVENT, EventState.UNSCHEDULED_SHOCK}:
        return _instruction(position, context.now, ExitScope.BOTH_SIDES, ExitReason.EVENT_OR_SHOCK)
    if context.breakout_state is BreakoutState.BREAKING_CONCENTRATED_STRIKE:
        return _instruction(
            position,
            context.now,
            ExitScope.BOTH_SIDES,
            ExitReason.CONCENTRATED_STRIKE_BREAKOUT,
        )
    if (
        context.rv_acceleration >= policy.position.maximum_rv_acceleration
        and position.has_short_risk
    ):
        return _instruction(position, context.now, ExitScope.BOTH_SIDES, ExitReason.GAMMA_EXPANSION)
    if put_threat is not None and call_threat is not None:
        return _instruction(position, context.now, ExitScope.BOTH_SIDES, ExitReason.GAMMA_EXPANSION)
    if put_threat is not None:
        return _instruction(position, context.now, ExitScope.PUT_SIDE, put_threat)
    if call_threat is not None:
        return _instruction(position, context.now, ExitScope.CALL_SIDE, call_threat)
    return None


def apply_exit_instruction(
    *,
    position: ShadowPosition,
    instruction: PositionInstruction,
    quotes: tuple[OptionQuote, ...],
    context: MarketContext,
    policy: BtcShortVolPolicy,
) -> bool:
    if position.state is PositionState.TERMINAL:
        return False
    position.state = PositionState.EXIT_REQUIRED
    by_name = {quote.instrument_name: quote for quote in quotes}
    sides = (
        (position.put_side,)
        if instruction.scope is ExitScope.PUT_SIDE
        else (position.call_side,)
        if instruction.scope is ExitScope.CALL_SIDE
        else (position.put_side, position.call_side)
    )
    new_intent = False
    for side in sides:
        if side.short_open and side.exit_requested_reason is None:
            side.exit_requested_at = instruction.at
            side.exit_requested_reason = instruction.reason
            new_intent = True
    if new_intent:
        if position.first_instruction is None:
            position.first_instruction = instruction
        position.instructions.append(instruction)
    execution_changed = False
    attempt_changed = False
    for side in sides:
        reason = side.exit_requested_reason or instruction.reason
        prior_attempt_count = side.exit_attempt_count
        execution_changed = (
            _exit_side(
                side=side,
                by_name=by_name,
                context=context,
                reason=reason,
                allow_short_only=policy.position.allow_short_only_risk_exit,
                maximum_source_skew_ms=policy.shadow.maximum_pair_source_skew_ms,
                maximum_receive_skew_ms=policy.shadow.maximum_pair_receive_skew_ms,
                retry_interval_ms=policy.position.acquisition_retry_interval_ms,
            )
            or execution_changed
        )
        attempt_changed = side.exit_attempt_count > prior_attempt_count or attempt_changed
    _refresh_position_state(position, context.now)
    return new_intent or execution_changed or attempt_changed


def dispose_residual_wings(
    *,
    position: ShadowPosition,
    quotes: tuple[OptionQuote, ...],
    context: MarketContext,
) -> bool:
    if position.state is PositionState.TERMINAL:
        return False
    by_name = {quote.instrument_name: quote for quote in quotes}
    changed = False
    for side in (position.put_side, position.call_side):
        if not side.long_open:
            continue
        quote = by_name.get(side.long_quote.instrument_name)
        if quote is None:
            continue
        execution = execute_leg(
            quote,
            action=Action.SELL,
            quantity=side.quantity,
            index_price=context.index_price,
        )
        if execution is None:
            continue
        side.native_cashflow_after_fees += execution.native_cashflow - execution.native_fee
        side.boundary_valued_cashflow_usd += execution.usd_cashflow - execution.usd_fee
        side.long_open = False
        side.long_exit_execution = execution
        side.terminal_at = context.now
        side.state = SideState.TERMINAL
        changed = True
    _refresh_position_state(position, context.now)
    return changed


def settle_position(
    *,
    position: ShadowPosition,
    delivery_price: Decimal,
    settled_at: datetime,
) -> PositionOutcome:
    if position.outcome is not None:
        return position.outcome
    residual_wings_settled = position.residual_wing_count
    for side in (position.put_side, position.call_side):
        for quote, action, is_open in (
            (side.short_quote, Action.SELL, side.short_open),
            (side.long_quote, Action.BUY, side.long_open),
        ):
            if not is_open:
                continue
            settlement = settle_option_leg(
                product=quote.product,
                option_type=quote.option_type.value,
                strike=quote.strike,
                delivery_price=delivery_price,
                quantity=side.quantity,
                action=action,
                delivery_fee_exempt=quote.delivery_fee_exempt,
            )
            side.native_cashflow_after_fees += settlement.net_cashflow_native
            side.boundary_valued_cashflow_usd += settlement.net_cashflow_native * delivery_price
            side.delivery_fee_native += settlement.delivery_fee_native
        side.short_open = False
        side.long_open = False
        side.state = SideState.TERMINAL
        side.terminal_at = settled_at
    return _finalize_outcome(
        position=position,
        terminal_at=settled_at,
        terminal_method="CONTRACT_SETTLEMENT",
        valuation_index=delivery_price,
        residual_wings_settled=residual_wings_settled,
    )


def finalize_if_terminal(
    *,
    position: ShadowPosition,
    at: datetime,
    valuation_index: Decimal,
) -> PositionOutcome | None:
    if position.outcome is not None:
        return position.outcome
    terminal_side_states = {SideState.NOT_OPEN, SideState.TERMINAL}
    if position.put_side.state not in terminal_side_states or (
        position.call_side.state not in terminal_side_states
    ):
        return None
    return _finalize_outcome(
        position=position,
        terminal_at=at,
        terminal_method="MARKET_EXIT",
        valuation_index=valuation_index,
    )


def entry_result_identity(
    *,
    case_identity: str,
    attempted_at: datetime,
    route: EntryRoute,
    status: EntryStatus,
    public_combo_observed: bool,
    put_vertical_execution: VerticalExecution | None,
    call_vertical_execution: VerticalExecution | None,
    wing_executions: tuple[LegExecution, ...],
    blockers: tuple[str, ...],
) -> str:
    require_identity(case_identity, "case_identity")
    return canonical_identity(
        "TwoSidedEntryResultV1",
        case_identity,
        attempted_at.isoformat(),
        route,
        status,
        public_combo_observed,
        put_vertical_execution,
        call_vertical_execution,
        wing_executions,
        blockers,
    )


def shadow_position_identity(*, case_identity: str, entry_identity: str) -> str:
    require_identity(case_identity, "case_identity")
    require_identity(entry_identity, "entry_identity")
    return canonical_identity(
        "TwoSidedShadowPositionV1",
        case_identity,
        entry_identity,
    )


def position_outcome_identity(
    *,
    position_identity: str,
    terminal_at: datetime,
    terminal_method: str,
    put_side_native_pnl: Decimal,
    call_side_native_pnl: Decimal,
    total_native_pnl: Decimal,
    boundary_valued_total_usd_pnl: Decimal,
    terminal_valued_total_usd_pnl: Decimal,
    put_side_delivery_fee_native: Decimal,
    call_side_delivery_fee_native: Decimal,
    residual_wings_settled: int,
) -> str:
    require_identity(position_identity, "position_identity")
    return canonical_identity(
        "TwoSidedPositionOutcomeV1",
        position_identity,
        terminal_at.isoformat(),
        terminal_method,
        put_side_native_pnl,
        call_side_native_pnl,
        total_native_pnl,
        boundary_valued_total_usd_pnl,
        terminal_valued_total_usd_pnl,
        put_side_delivery_fee_native,
        call_side_delivery_fee_native,
        residual_wings_settled,
    )


def _entry_result(
    *,
    case: DecisionCase,
    attempted_at: datetime,
    route: EntryRoute,
    status: EntryStatus,
    public_combo_observed: bool = False,
    put_vertical_execution: VerticalExecution | None = None,
    call_vertical_execution: VerticalExecution | None = None,
    wing_executions: tuple[LegExecution, ...] = (),
    blockers: tuple[str, ...] = (),
) -> EntryResult:
    identity = entry_result_identity(
        case_identity=case.case_identity,
        attempted_at=attempted_at,
        route=route,
        status=status,
        public_combo_observed=public_combo_observed,
        put_vertical_execution=put_vertical_execution,
        call_vertical_execution=call_vertical_execution,
        wing_executions=wing_executions,
        blockers=blockers,
    )
    return EntryResult(
        entry_identity=identity,
        attempted_at=attempted_at,
        route=route,
        public_combo_observed=public_combo_observed,
        status=status,
        put_vertical_execution=put_vertical_execution,
        call_vertical_execution=call_vertical_execution,
        wing_executions=wing_executions,
        blockers=blockers,
    )


def _position_from_entry(
    *,
    case: DecisionCase,
    result: EntryResult,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    index_price: Decimal,
    quantity: Decimal,
) -> ShadowPosition:
    put_execution = result.put_vertical_execution
    call_execution = result.call_vertical_execution
    put_side = _side_from_execution(
        side=Side.PUT,
        short_quote=short_put,
        long_quote=long_put,
        quantity=quantity,
        execution=put_execution,
        wing_execution=_wing_execution(result.wing_executions, long_put.instrument_name),
    )
    call_side = _side_from_execution(
        side=Side.CALL,
        short_quote=short_call,
        long_quote=long_call,
        quantity=quantity,
        execution=call_execution,
        wing_execution=_wing_execution(result.wing_executions, long_call.instrument_name),
    )
    native_credit = put_side.native_cashflow_after_fees + call_side.native_cashflow_after_fees
    position_identity = shadow_position_identity(
        case_identity=case.case_identity,
        entry_identity=result.entry_identity,
    )
    position = ShadowPosition(
        position_identity=position_identity,
        case_identity=case.case_identity,
        entry_identity=result.entry_identity,
        opened_at=result.attempted_at,
        entry_status=result.status,
        product_index_at_entry=index_price,
        initial_net_credit_native=native_credit,
        initial_net_credit_usd=(native_credit * index_price),
        put_side=put_side,
        call_side=call_side,
    )
    _arm_entry_remediation(position, result.attempted_at)
    _refresh_position_state(position, result.attempted_at)
    return position


def _arm_entry_remediation(position: ShadowPosition, at: datetime) -> None:
    sides: tuple[SidePosition, ...]
    if position.entry_status is EntryStatus.PUT_SIDE_ONLY:
        scope = ExitScope.PUT_SIDE
        sides = (position.put_side,)
    elif position.entry_status is EntryStatus.CALL_SIDE_ONLY:
        scope = ExitScope.CALL_SIDE
        sides = (position.call_side,)
    elif position.entry_status is EntryStatus.TWO_SIDES_INCOHERENT:
        scope = ExitScope.BOTH_SIDES
        sides = (position.put_side, position.call_side)
    else:
        return
    instruction = _instruction(
        position,
        at,
        scope,
        ExitReason.ENTRY_ACQUISITION_INCOMPLETE,
    )
    position.first_instruction = instruction
    position.instructions.append(instruction)
    for side in sides:
        if side.short_open:
            side.exit_requested_at = at
            side.exit_requested_reason = ExitReason.ENTRY_ACQUISITION_INCOMPLETE


def _side_from_execution(
    *,
    side: Side,
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    quantity: Decimal,
    execution: VerticalExecution | None,
    wing_execution: LegExecution | None,
) -> SidePosition:
    if isinstance(execution, VerticalExecution):
        return SidePosition(
            side=side,
            short_quote=short_quote,
            long_quote=long_quote,
            quantity=quantity,
            state=SideState.CREDIT_VERTICAL_OPEN,
            native_cashflow_after_fees=execution.native_net_credit,
            boundary_valued_cashflow_usd=execution.usd_net_credit,
            short_open=True,
            long_open=True,
        )
    if wing_execution is not None:
        return SidePosition(
            side=side,
            short_quote=short_quote,
            long_quote=long_quote,
            quantity=quantity,
            state=SideState.SHORT_FLAT_LONG_WING,
            native_cashflow_after_fees=(wing_execution.native_cashflow - wing_execution.native_fee),
            boundary_valued_cashflow_usd=(wing_execution.usd_cashflow - wing_execution.usd_fee),
            short_open=False,
            long_open=True,
        )
    return SidePosition(
        side=side,
        short_quote=short_quote,
        long_quote=long_quote,
        quantity=quantity,
        state=SideState.NOT_OPEN,
        native_cashflow_after_fees=Decimal(0),
        boundary_valued_cashflow_usd=Decimal(0),
        short_open=False,
        long_open=False,
    )


def _wing_execution(
    executions: tuple[LegExecution, ...],
    instrument_name: str,
) -> LegExecution | None:
    return next(
        (execution for execution in executions if execution.instrument_name == instrument_name),
        None,
    )


def _pending_exit_instruction(
    position: ShadowPosition,
    at: datetime,
) -> PositionInstruction | None:
    pending = tuple(
        side
        for side in (position.put_side, position.call_side)
        if side.short_open and side.exit_requested_reason is not None
    )
    if not pending:
        return None
    if len(pending) == 2:
        scope = ExitScope.BOTH_SIDES
        reason = min(
            pending,
            key=lambda side: side.exit_requested_at or position.opened_at,
        ).exit_requested_reason
    else:
        side = pending[0]
        scope = ExitScope.PUT_SIDE if side.side is Side.PUT else ExitScope.CALL_SIDE
        reason = side.exit_requested_reason
    assert reason is not None
    return _instruction(position, at, scope, reason)


def _instruction(
    position: ShadowPosition,
    at: datetime,
    scope: ExitScope,
    reason: ExitReason,
) -> PositionInstruction:
    identity = canonical_identity(
        "TwoSidedPositionInstructionV1",
        position.position_identity,
        at.isoformat(),
        scope,
        reason,
    )
    return PositionInstruction(identity, at, scope, reason)


def _side_threatened(
    *,
    side: SidePosition,
    current_quote: OptionQuote | None,
    context: MarketContext,
    entry_index: Decimal,
    policy: BtcShortVolPolicy,
) -> ExitReason | None:
    if not side.short_open:
        return None
    delta = abs(current_quote.signed_delta) if current_quote is not None else Decimal(0)
    if delta >= policy.position.maximum_short_abs_delta:
        return ExitReason.PUT_SIDE_DELTA if side.side is Side.PUT else ExitReason.CALL_SIDE_DELTA
    if side.side is Side.PUT:
        adverse = max(Decimal(0), Decimal(1) - context.index_price / entry_index)
        if adverse >= policy.position.maximum_adverse_move_fraction:
            return ExitReason.PUT_SIDE_ADVERSE_MOVE
    else:
        adverse = max(Decimal(0), context.index_price / entry_index - Decimal(1))
        if adverse >= policy.position.maximum_adverse_move_fraction:
            return ExitReason.CALL_SIDE_ADVERSE_MOVE
    return None


def _estimated_position_native_pnl(
    *,
    position: ShadowPosition,
    quotes: dict[str, OptionQuote],
    index_price: Decimal,
) -> Decimal | None:
    total = Decimal(0)
    for side in (position.put_side, position.call_side):
        total += side.native_cashflow_after_fees
        if side.short_open and side.long_open:
            short = quotes.get(side.short_quote.instrument_name)
            long = quotes.get(side.long_quote.instrument_name)
            if short is None or long is None:
                return None
            close = price_close_vertical(
                short_quote=short,
                long_quote=long,
                quantity=side.quantity,
                index_price=index_price,
            )
            if close is None:
                return None
            short_execution, long_execution = close
            total += (
                short_execution.native_cashflow
                - short_execution.native_fee
                + long_execution.native_cashflow
                - long_execution.native_fee
            )
        elif side.short_open:
            short = quotes.get(side.short_quote.instrument_name)
            if short is None:
                return None
            execution = execute_leg(
                short,
                action=Action.BUY,
                quantity=side.quantity,
                index_price=index_price,
            )
            if execution is None:
                return None
            total += execution.native_cashflow - execution.native_fee
        if side.long_open and not side.short_open:
            long = quotes.get(side.long_quote.instrument_name)
            if long is None:
                continue
            execution = execute_leg(
                long,
                action=Action.SELL,
                quantity=side.quantity,
                index_price=index_price,
            )
            if execution is not None:
                total += execution.native_cashflow - execution.native_fee
    return total


def _exit_side(
    *,
    side: SidePosition,
    by_name: dict[str, OptionQuote],
    context: MarketContext,
    reason: ExitReason,
    allow_short_only: bool,
    maximum_source_skew_ms: int,
    maximum_receive_skew_ms: int,
    retry_interval_ms: int,
) -> bool:
    if not side.short_open and not side.long_open:
        return False
    if side.last_exit_attempt_at is not None:
        elapsed_ms = int((context.now - side.last_exit_attempt_at).total_seconds() * 1000)
        if elapsed_ms < retry_interval_ms:
            return False
    side.last_exit_attempt_at = context.now
    side.exit_attempt_count += 1
    short = by_name.get(side.short_quote.instrument_name)
    long = by_name.get(side.long_quote.instrument_name)
    pair_coherent = False
    if side.short_open and side.long_open:
        if short is None or long is None:
            side.quote_missing_block_count += 1
        else:
            pair_coherent = _pair_coherent(
                short,
                long,
                maximum_source_skew_ms=maximum_source_skew_ms,
                maximum_receive_skew_ms=maximum_receive_skew_ms,
            )
            if not pair_coherent:
                side.pair_incoherent_block_count += 1
    if side.short_open and side.long_open and pair_coherent:
        assert short is not None and long is not None
        close = price_close_vertical(
            short_quote=short,
            long_quote=long,
            quantity=side.quantity,
            index_price=context.index_price,
        )
        if close is not None:
            short_execution, long_execution = close
            side.native_cashflow_after_fees += (
                short_execution.native_cashflow
                - short_execution.native_fee
                + long_execution.native_cashflow
                - long_execution.native_fee
            )
            side.boundary_valued_cashflow_usd += (
                short_execution.usd_cashflow
                - short_execution.usd_fee
                + long_execution.usd_cashflow
                - long_execution.usd_fee
            )
            side.short_open = False
            side.long_open = False
            side.short_exit_execution = short_execution
            side.long_exit_execution = long_execution
            side.short_risk_exit_at = context.now
            side.terminal_at = context.now
            side.exit_reason = reason
            side.state = SideState.TERMINAL
            return True
        side.pair_unexecutable_block_count += 1
    if side.short_open and allow_short_only and short is not None:
        short_only_execution = execute_leg(
            short,
            action=Action.BUY,
            quantity=side.quantity,
            index_price=context.index_price,
        )
        if short_only_execution is not None:
            side.native_cashflow_after_fees += (
                short_only_execution.native_cashflow - short_only_execution.native_fee
            )
            side.boundary_valued_cashflow_usd += (
                short_only_execution.usd_cashflow - short_only_execution.usd_fee
            )
            side.short_open = False
            side.short_only_exit_used = True
            side.short_exit_execution = short_only_execution
            side.short_risk_exit_at = context.now
            side.exit_reason = reason
            side.state = SideState.SHORT_FLAT_LONG_WING if side.long_open else SideState.TERMINAL
            if not side.long_open:
                side.terminal_at = context.now
            return True
    return False


def _refresh_position_state(position: ShadowPosition, at: datetime) -> None:
    if not position.has_short_risk and position.short_risk_flat_at is None:
        position.short_risk_flat_at = at
    if not position.has_short_risk and position.residual_wing_count > 0:
        position.state = PositionState.SHORT_RISK_FLAT
    elif not position.has_short_risk and position.residual_wing_count == 0:
        position.state = PositionState.TERMINAL
        position.terminal_at = at
    elif position.first_instruction is not None:
        position.state = PositionState.EXIT_REQUIRED
    else:
        position.state = PositionState.MONITORING


def _finalize_outcome(
    *,
    position: ShadowPosition,
    terminal_at: datetime,
    terminal_method: str,
    valuation_index: Decimal,
    residual_wings_settled: int = 0,
) -> PositionOutcome:
    put_pnl = position.put_side.native_cashflow_after_fees
    call_pnl = position.call_side.native_cashflow_after_fees
    total = put_pnl + call_pnl
    put_boundary = position.put_side.boundary_valued_cashflow_usd
    call_boundary = position.call_side.boundary_valued_cashflow_usd
    boundary_total = put_boundary + call_boundary
    terminal_valued_total = total * valuation_index
    exit_sides = {
        instruction.scope
        for instruction in position.instructions
        if instruction.scope in {ExitScope.PUT_SIDE, ExitScope.CALL_SIDE}
    }
    double_stop = ExitScope.PUT_SIDE in exit_sides and ExitScope.CALL_SIDE in exit_sides
    outcome_identity = position_outcome_identity(
        position_identity=position.position_identity,
        terminal_at=terminal_at,
        terminal_method=terminal_method,
        put_side_native_pnl=put_pnl,
        call_side_native_pnl=call_pnl,
        total_native_pnl=total,
        boundary_valued_total_usd_pnl=boundary_total,
        terminal_valued_total_usd_pnl=terminal_valued_total,
        put_side_delivery_fee_native=position.put_side.delivery_fee_native,
        call_side_delivery_fee_native=position.call_side.delivery_fee_native,
        residual_wings_settled=residual_wings_settled,
    )
    first_exit_to_flat_ms = (
        int((position.short_risk_flat_at - position.first_instruction.at).total_seconds() * 1000)
        if position.short_risk_flat_at is not None and position.first_instruction is not None
        else None
    )
    outcome = PositionOutcome(
        outcome_identity=outcome_identity,
        terminal_at=terminal_at,
        terminal_method=terminal_method,
        entry_status=position.entry_status,
        first_exit_reason=(
            position.first_instruction.reason if position.first_instruction is not None else None
        ),
        first_exit_at=(
            position.first_instruction.at if position.first_instruction is not None else None
        ),
        short_risk_flat_at=position.short_risk_flat_at,
        put_side_exit_at=position.put_side.short_risk_exit_at,
        call_side_exit_at=position.call_side.short_risk_exit_at,
        put_side_native_pnl=put_pnl,
        call_side_native_pnl=call_pnl,
        total_native_pnl=total,
        put_side_boundary_valued_pnl_usd=put_boundary,
        call_side_boundary_valued_pnl_usd=call_boundary,
        boundary_valued_total_usd_pnl=boundary_total,
        terminal_valued_total_usd_pnl=terminal_valued_total,
        double_side_stop=double_stop,
        put_side_delivery_fee_native=position.put_side.delivery_fee_native,
        call_side_delivery_fee_native=position.call_side.delivery_fee_native,
        total_delivery_fee_native=(
            position.put_side.delivery_fee_native + position.call_side.delivery_fee_native
        ),
        residual_wings_settled=residual_wings_settled,
        residual_wing_count=position.residual_wing_count,
        put_exit_attempt_count=position.put_side.exit_attempt_count,
        call_exit_attempt_count=position.call_side.exit_attempt_count,
        exit_quote_missing_block_count=(
            position.put_side.quote_missing_block_count
            + position.call_side.quote_missing_block_count
        ),
        exit_pair_incoherent_block_count=(
            position.put_side.pair_incoherent_block_count
            + position.call_side.pair_incoherent_block_count
        ),
        exit_pair_unexecutable_block_count=(
            position.put_side.pair_unexecutable_block_count
            + position.call_side.pair_unexecutable_block_count
        ),
        short_only_exit_side_count=(
            int(position.put_side.short_only_exit_used)
            + int(position.call_side.short_only_exit_used)
        ),
        first_exit_to_short_risk_flat_ms=first_exit_to_flat_ms,
    )
    require_identity(outcome_identity, "outcome_identity")
    position.state = PositionState.TERMINAL
    position.terminal_at = terminal_at
    position.outcome = outcome
    return outcome


def _entry_pair_eligible(
    short: OptionQuote,
    long: OptionQuote,
    *,
    decision_received_ms: int,
    attempted_received_ms: int,
    maximum_source_skew_ms: int,
    maximum_receive_skew_ms: int,
) -> bool:
    return (
        decision_received_ms < short.received_timestamp_ms <= attempted_received_ms
        and decision_received_ms < long.received_timestamp_ms <= attempted_received_ms
        and _pair_coherent(
            short,
            long,
            maximum_source_skew_ms=maximum_source_skew_ms,
            maximum_receive_skew_ms=maximum_receive_skew_ms,
        )
    )


def _four_leg_entry_eligible(
    quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote],
    *,
    decision_received_ms: int,
    attempted_received_ms: int,
    maximum_source_skew_ms: int,
    maximum_receive_skew_ms: int,
) -> bool:
    received = tuple(quote.received_timestamp_ms for quote in quotes)
    source = tuple(quote.source_timestamp_ms for quote in quotes)
    epochs = {quote.continuity_epoch for quote in quotes}
    return (
        all(decision_received_ms < timestamp <= attempted_received_ms for timestamp in received)
        and len(epochs) == 1
        and max(source) - min(source) <= maximum_source_skew_ms
        and max(received) - min(received) <= maximum_receive_skew_ms
    )


def _pair_coherent(
    first: OptionQuote,
    second: OptionQuote,
    *,
    maximum_source_skew_ms: int,
    maximum_receive_skew_ms: int,
) -> bool:
    return (
        first.continuity_epoch == second.continuity_epoch
        and abs(first.source_timestamp_ms - second.source_timestamp_ms) <= maximum_source_skew_ms
        and abs(first.received_timestamp_ms - second.received_timestamp_ms)
        <= maximum_receive_skew_ms
    )

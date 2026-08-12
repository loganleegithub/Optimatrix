from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from optimatrix.identity import canonical_value, require_identity
from optimatrix.lifecycle import (
    DecisionCase,
    EntryResult,
    EntryRoute,
    EntryStatus,
    ExitReason,
    ExitScope,
    PositionInstruction,
    PositionOutcome,
    PositionState,
    ShadowPosition,
    Side,
    SidePosition,
    SideState,
    entry_result_identity,
    position_outcome_identity,
    shadow_position_identity,
)
from optimatrix.market import OptionQuote, OptionType, PriceLevel, TickSchedule, TickStep
from optimatrix.pricing import (
    Action,
    DepthWalk,
    IronCondorExecution,
    LegExecution,
    VerticalExecution,
)
from optimatrix.products import PRODUCTS, ProductId
from optimatrix.radar import Decision, RadarDecision, ScoreBreakdown
from optimatrix.session import SessionPhase
from optimatrix.structure import IronCondorCandidate


class JournalError(ValueError):
    pass


class CaseJournal:
    def __init__(self, root: Path, case_identity: str) -> None:
        require_identity(case_identity, "case_identity")
        if root.exists() and root.is_symlink():
            raise JournalError("journal root cannot be a symlink")
        self.root = root
        self.path = root / f"{case_identity.removeprefix('sha256:')}.jsonl"
        self.case_identity = case_identity

    def append(self, kind: str, payload: Mapping[str, object]) -> int:
        if not kind:
            raise JournalError("journal event kind must be non-empty")
        events = self.read()
        sequence = len(events)
        record = {
            "sequence": sequence,
            "case_identity": self.case_identity,
            "kind": kind,
            "payload": canonical_value(payload),
        }
        encoded = (
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        existed_before = self.path.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise JournalError("journal root cannot be a symlink")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self.path, flags, 0o600)
        try:
            view = memoryview(encoded)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("journal append made no progress")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if not existed_before:
            directory_descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        return sequence

    def read(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        if self.path.is_symlink() or not self.path.is_file():
            raise JournalError("journal path is invalid")
        records: list[dict[str, object]] = []
        for expected, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalError("journal contains invalid JSON") from exc
            if not isinstance(value, dict):
                raise JournalError("journal record must be an object")
            if set(value) != {"sequence", "case_identity", "kind", "payload"}:
                raise JournalError("journal record shape is invalid")
            if (
                value.get("sequence") != expected
                or value.get("case_identity") != self.case_identity
            ):
                raise JournalError("journal sequence or identity mismatch")
            if not isinstance(value.get("kind"), str) or not isinstance(value.get("payload"), dict):
                raise JournalError("journal kind/payload is invalid")
            records.append(value)
        return tuple(records)

    def latest_decision_case(self) -> DecisionCase | None:
        for record in self.read():
            if record["kind"] == "DECISION_OPENED":
                payload = _mapping(record["payload"], "payload")
                return decision_case_from_object(
                    _mapping(payload.get("decision_case"), "decision_case")
                )
        return None

    def latest_entry_result(self) -> EntryResult | None:
        for record in reversed(self.read()):
            if record["kind"] == "ENTRY_TERMINAL":
                payload = _mapping(record["payload"], "payload")
                return entry_result_from_object(
                    _mapping(payload.get("entry_result"), "entry_result"),
                    case_identity=self.case_identity,
                )
        return None

    def latest_position(self) -> ShadowPosition | None:
        for record in reversed(self.read()):
            if record["kind"] == "POSITION_CHECKPOINT":
                return position_from_object(_mapping(record["payload"], "payload"))
        return None


def decision_case_to_object(case: DecisionCase) -> dict[str, object]:
    return {
        "case_identity": case.case_identity,
        "opened_at": case.opened_at.isoformat(),
        "radar_decision": _radar_decision_to_object(case.radar_decision),
    }


def decision_case_from_object(value: Mapping[str, object]) -> DecisionCase:
    _exact_keys(value, {"case_identity", "opened_at", "radar_decision"}, "decision_case")
    radar = _radar_decision_from_object(_mapping(value.get("radar_decision"), "radar_decision"))
    case = DecisionCase.open(
        opened_at=_datetime(_text(value, "opened_at")),
        radar_decision=radar,
    )
    if value.get("case_identity") != case.case_identity:
        raise JournalError("Decision Case identity mismatch")
    return case


def entry_result_to_object(value: EntryResult) -> dict[str, object]:
    return {
        "entry_identity": value.entry_identity,
        "attempted_at": value.attempted_at.isoformat(),
        "route": value.route.value,
        "public_combo_observed": value.public_combo_observed,
        "status": value.status.value,
        "put_vertical_execution": (
            _vertical_execution_to_object(value.put_vertical_execution)
            if value.put_vertical_execution is not None
            else None
        ),
        "call_vertical_execution": (
            _vertical_execution_to_object(value.call_vertical_execution)
            if value.call_vertical_execution is not None
            else None
        ),
        "wing_executions": [
            _leg_execution_to_object(execution) for execution in value.wing_executions
        ],
        "blockers": list(value.blockers),
    }


def entry_result_from_object(
    value: Mapping[str, object],
    *,
    case_identity: str | None = None,
) -> EntryResult:
    expected = {
        "entry_identity",
        "attempted_at",
        "route",
        "public_combo_observed",
        "status",
        "put_vertical_execution",
        "call_vertical_execution",
        "wing_executions",
        "blockers",
    }
    _exact_keys(value, expected, "entry_result")
    wings = value.get("wing_executions")
    blockers = value.get("blockers")
    if (
        not isinstance(wings, list)
        or not isinstance(blockers, list)
        or not all(isinstance(member, str) and member for member in blockers)
    ):
        raise JournalError("entry-result arrays are invalid")
    put_raw = value.get("put_vertical_execution")
    call_raw = value.get("call_vertical_execution")
    result = EntryResult(
        entry_identity=require_identity(_text(value, "entry_identity"), "entry_identity"),
        attempted_at=_datetime(_text(value, "attempted_at")),
        route=EntryRoute(_text(value, "route")),
        public_combo_observed=_bool(value, "public_combo_observed"),
        status=EntryStatus(_text(value, "status")),
        put_vertical_execution=(
            _vertical_execution_from_object(_mapping(put_raw, "put_vertical_execution"))
            if put_raw is not None
            else None
        ),
        call_vertical_execution=(
            _vertical_execution_from_object(_mapping(call_raw, "call_vertical_execution"))
            if call_raw is not None
            else None
        ),
        wing_executions=tuple(
            _leg_execution_from_object(_mapping(member, "wing_execution")) for member in wings
        ),
        blockers=tuple(blockers),
    )
    if case_identity is not None:
        expected_identity = entry_result_identity(
            case_identity=case_identity,
            attempted_at=result.attempted_at,
            route=result.route,
            status=result.status,
            public_combo_observed=result.public_combo_observed,
            put_vertical_execution=result.put_vertical_execution,
            call_vertical_execution=result.call_vertical_execution,
            wing_executions=result.wing_executions,
            blockers=result.blockers,
        )
        if result.entry_identity != expected_identity:
            raise JournalError("Entry result identity mismatch")
    return result


def _radar_decision_to_object(value: RadarDecision) -> dict[str, object]:
    return {
        "decision_identity": value.decision_identity,
        "decision": value.decision.value,
        "session_id": value.session_id,
        "session_minute": value.session_minute,
        "phase": value.phase.value,
        "structure": (
            _condor_candidate_to_object(value.structure) if value.structure is not None else None
        ),
        "score": _score_to_object(value.score) if value.score is not None else None,
        "blockers": list(value.blockers),
    }


def _radar_decision_from_object(value: Mapping[str, object]) -> RadarDecision:
    expected = {
        "decision_identity",
        "decision",
        "session_id",
        "session_minute",
        "phase",
        "structure",
        "score",
        "blockers",
    }
    _exact_keys(value, expected, "radar_decision")
    blockers = value.get("blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(member, str) and member for member in blockers
    ):
        raise JournalError("radar blockers must be non-empty strings")
    structure_raw = value.get("structure")
    score_raw = value.get("score")
    return RadarDecision(
        decision_identity=require_identity(_text(value, "decision_identity"), "decision_identity"),
        decision=Decision(_text(value, "decision")),
        session_id=_text(value, "session_id"),
        session_minute=_non_negative_int(value, "session_minute"),
        phase=SessionPhase(_text(value, "phase")),
        structure=(
            _condor_candidate_from_object(_mapping(structure_raw, "structure"))
            if structure_raw is not None
            else None
        ),
        score=(_score_from_object(_mapping(score_raw, "score")) if score_raw is not None else None),
        blockers=tuple(blockers),
    )


def _score_to_object(value: ScoreBreakdown) -> dict[str, str]:
    return {
        "vrp_ratio": str(value.vrp_ratio),
        "theta_capture_proxy": str(value.theta_capture_proxy),
        "premium_edge": str(value.premium_edge),
        "gamma_safety": str(value.gamma_safety),
        "range_quality": str(value.range_quality),
        "execution_quality": str(value.execution_quality),
        "final_score": str(value.final_score),
    }


def _score_from_object(value: Mapping[str, object]) -> ScoreBreakdown:
    fields = {
        "vrp_ratio",
        "theta_capture_proxy",
        "premium_edge",
        "gamma_safety",
        "range_quality",
        "execution_quality",
        "final_score",
    }
    _exact_keys(value, fields, "score")
    return ScoreBreakdown(**{field: _decimal(value[field], field) for field in fields})


def _condor_candidate_to_object(value: IronCondorCandidate) -> dict[str, object]:
    return {
        "long_put": _quote_to_object(value.long_put),
        "short_put": _quote_to_object(value.short_put),
        "short_call": _quote_to_object(value.short_call),
        "long_call": _quote_to_object(value.long_call),
        "execution": _condor_execution_to_object(value.execution),
        "net_delta": str(value.net_delta),
        "put_body_distance_sigma": str(value.put_body_distance_sigma),
        "call_body_distance_sigma": str(value.call_body_distance_sigma),
        "minimum_body_distance_sigma": str(value.minimum_body_distance_sigma),
        "average_spread_quality": str(value.average_spread_quality),
        "depth_quality": str(value.depth_quality),
    }


def _condor_candidate_from_object(value: Mapping[str, object]) -> IronCondorCandidate:
    expected = {
        "long_put",
        "short_put",
        "short_call",
        "long_call",
        "execution",
        "net_delta",
        "put_body_distance_sigma",
        "call_body_distance_sigma",
        "minimum_body_distance_sigma",
        "average_spread_quality",
        "depth_quality",
    }
    _exact_keys(value, expected, "condor_candidate")
    return IronCondorCandidate(
        long_put=_quote_from_object(_mapping(value["long_put"], "long_put")),
        short_put=_quote_from_object(_mapping(value["short_put"], "short_put")),
        short_call=_quote_from_object(_mapping(value["short_call"], "short_call")),
        long_call=_quote_from_object(_mapping(value["long_call"], "long_call")),
        execution=_condor_execution_from_object(_mapping(value["execution"], "execution")),
        net_delta=_decimal(value["net_delta"], "net_delta"),
        put_body_distance_sigma=_decimal(
            value["put_body_distance_sigma"], "put_body_distance_sigma"
        ),
        call_body_distance_sigma=_decimal(
            value["call_body_distance_sigma"], "call_body_distance_sigma"
        ),
        minimum_body_distance_sigma=_decimal(
            value["minimum_body_distance_sigma"], "minimum_body_distance_sigma"
        ),
        average_spread_quality=_decimal(value["average_spread_quality"], "average_spread_quality"),
        depth_quality=_decimal(value["depth_quality"], "depth_quality"),
    )


def _condor_execution_to_object(value: IronCondorExecution) -> dict[str, object]:
    return {
        "put_vertical": _vertical_execution_to_object(value.put_vertical),
        "call_vertical": _vertical_execution_to_object(value.call_vertical),
        "native_gross_credit": str(value.native_gross_credit),
        "native_total_fee": str(value.native_total_fee),
        "native_net_credit": str(value.native_net_credit),
        "usd_gross_credit": str(value.usd_gross_credit),
        "usd_total_fee": str(value.usd_total_fee),
        "usd_net_credit": str(value.usd_net_credit),
        "put_payoff_cap_usd": str(value.put_payoff_cap_usd),
        "call_payoff_cap_usd": str(value.call_payoff_cap_usd),
        "maximum_side_payoff_cap_usd": str(value.maximum_side_payoff_cap_usd),
        "entry_boundary_max_loss_usd": str(value.entry_boundary_max_loss_usd),
    }


def _condor_execution_from_object(value: Mapping[str, object]) -> IronCondorExecution:
    fields = {
        "put_vertical",
        "call_vertical",
        "native_gross_credit",
        "native_total_fee",
        "native_net_credit",
        "usd_gross_credit",
        "usd_total_fee",
        "usd_net_credit",
        "put_payoff_cap_usd",
        "call_payoff_cap_usd",
        "maximum_side_payoff_cap_usd",
        "entry_boundary_max_loss_usd",
    }
    _exact_keys(value, fields, "condor_execution")
    return IronCondorExecution(
        put_vertical=_vertical_execution_from_object(
            _mapping(value["put_vertical"], "put_vertical")
        ),
        call_vertical=_vertical_execution_from_object(
            _mapping(value["call_vertical"], "call_vertical")
        ),
        **{
            field: _decimal(value[field], field)
            for field in fields - {"put_vertical", "call_vertical"}
        },
    )


def _vertical_execution_to_object(value: VerticalExecution) -> dict[str, object]:
    return {
        "short_leg": _leg_execution_to_object(value.short_leg),
        "long_leg": _leg_execution_to_object(value.long_leg),
        "native_gross_credit": str(value.native_gross_credit),
        "native_total_fee": str(value.native_total_fee),
        "native_net_credit": str(value.native_net_credit),
        "usd_gross_credit": str(value.usd_gross_credit),
        "usd_total_fee": str(value.usd_total_fee),
        "usd_net_credit": str(value.usd_net_credit),
        "width_usd_per_unit": str(value.width_usd_per_unit),
        "payoff_cap_usd": str(value.payoff_cap_usd),
    }


def _vertical_execution_from_object(value: Mapping[str, object]) -> VerticalExecution:
    fields = {
        "short_leg",
        "long_leg",
        "native_gross_credit",
        "native_total_fee",
        "native_net_credit",
        "usd_gross_credit",
        "usd_total_fee",
        "usd_net_credit",
        "width_usd_per_unit",
        "payoff_cap_usd",
    }
    _exact_keys(value, fields, "vertical_execution")
    return VerticalExecution(
        short_leg=_leg_execution_from_object(_mapping(value["short_leg"], "short_leg")),
        long_leg=_leg_execution_from_object(_mapping(value["long_leg"], "long_leg")),
        **{field: _decimal(value[field], field) for field in fields - {"short_leg", "long_leg"}},
    )


def _leg_execution_to_object(value: LegExecution) -> dict[str, object]:
    return {
        "instrument_name": value.instrument_name,
        "action": value.action.value,
        "quantity": str(value.quantity),
        "raw": _depth_walk_to_object(value.raw),
        "stressed": _depth_walk_to_object(value.stressed),
        "native_fee": str(value.native_fee),
        "native_cashflow": str(value.native_cashflow),
        "usd_cashflow": str(value.usd_cashflow),
        "usd_fee": str(value.usd_fee),
    }


def _leg_execution_from_object(value: Mapping[str, object]) -> LegExecution:
    expected = {
        "instrument_name",
        "action",
        "quantity",
        "raw",
        "stressed",
        "native_fee",
        "native_cashflow",
        "usd_cashflow",
        "usd_fee",
    }
    _exact_keys(value, expected, "leg_execution")
    return LegExecution(
        instrument_name=_text(value, "instrument_name"),
        action=Action(_text(value, "action")),
        quantity=_decimal(value["quantity"], "quantity"),
        raw=_depth_walk_from_object(_mapping(value["raw"], "raw")),
        stressed=_depth_walk_from_object(_mapping(value["stressed"], "stressed")),
        native_fee=_decimal(value["native_fee"], "native_fee"),
        native_cashflow=_decimal(value["native_cashflow"], "native_cashflow"),
        usd_cashflow=_decimal(value["usd_cashflow"], "usd_cashflow"),
        usd_fee=_decimal(value["usd_fee"], "usd_fee"),
    )


def _depth_walk_to_object(value: DepthWalk) -> dict[str, object]:
    return {
        "levels": [_level_to_object(level) for level in value.levels],
        "quantity": str(value.quantity),
        "native_total": str(value.native_total),
        "native_vwap": str(value.native_vwap),
    }


def _depth_walk_from_object(value: Mapping[str, object]) -> DepthWalk:
    _exact_keys(value, {"levels", "quantity", "native_total", "native_vwap"}, "depth_walk")
    levels = value.get("levels")
    if not isinstance(levels, list):
        raise JournalError("depth-walk levels must be an array")
    return DepthWalk(
        levels=tuple(_level_from_object(_mapping(member, "depth level")) for member in levels),
        quantity=_decimal(value["quantity"], "quantity"),
        native_total=_decimal(value["native_total"], "native_total"),
        native_vwap=_decimal(value["native_vwap"], "native_vwap"),
    )


def position_to_object(position: ShadowPosition) -> dict[str, object]:
    return {
        "position_identity": position.position_identity,
        "case_identity": position.case_identity,
        "entry_identity": position.entry_identity,
        "opened_at": position.opened_at.isoformat(),
        "entry_status": position.entry_status.value,
        "product_index_at_entry": str(position.product_index_at_entry),
        "initial_net_credit_native": str(position.initial_net_credit_native),
        "initial_net_credit_usd": str(position.initial_net_credit_usd),
        "put_side": _side_to_object(position.put_side),
        "call_side": _side_to_object(position.call_side),
        "state": position.state.value,
        "first_instruction": (
            _instruction_to_object(position.first_instruction)
            if position.first_instruction is not None
            else None
        ),
        "instructions": [_instruction_to_object(value) for value in position.instructions],
        "short_risk_flat_at": _datetime_text(position.short_risk_flat_at),
        "terminal_at": _datetime_text(position.terminal_at),
        "outcome": _outcome_to_object(position.outcome) if position.outcome is not None else None,
        "last_risk_observed_at": _datetime_text(position.last_risk_observed_at),
        "last_risk_context_known": position.last_risk_context_known,
        "last_risk_blockers": list(position.last_risk_blockers),
    }


def position_from_object(value: Mapping[str, object]) -> ShadowPosition:
    required = {
        "position_identity",
        "case_identity",
        "entry_identity",
        "opened_at",
        "entry_status",
        "product_index_at_entry",
        "initial_net_credit_native",
        "initial_net_credit_usd",
        "put_side",
        "call_side",
        "state",
        "first_instruction",
        "instructions",
        "short_risk_flat_at",
        "terminal_at",
        "outcome",
        "last_risk_observed_at",
        "last_risk_context_known",
        "last_risk_blockers",
    }
    if set(value) != required:
        raise JournalError("position checkpoint shape is invalid")
    instructions_raw = value["instructions"]
    if not isinstance(instructions_raw, list):
        raise JournalError("instructions must be an array")
    first_raw = value["first_instruction"]
    outcome_raw = value["outcome"]
    last_risk_blockers_raw = value["last_risk_blockers"]
    if not isinstance(last_risk_blockers_raw, list) or not all(
        isinstance(member, str) for member in last_risk_blockers_raw
    ):
        raise JournalError("last_risk_blockers must be an array of text")
    last_risk_context_known_raw = value["last_risk_context_known"]
    if last_risk_context_known_raw is not None and not isinstance(
        last_risk_context_known_raw, bool
    ):
        raise JournalError("last_risk_context_known must be boolean or null")
    position = ShadowPosition(
        position_identity=require_identity(_text(value, "position_identity"), "position_identity"),
        case_identity=require_identity(_text(value, "case_identity"), "case_identity"),
        entry_identity=require_identity(_text(value, "entry_identity"), "entry_identity"),
        opened_at=_datetime(_text(value, "opened_at")),
        entry_status=EntryStatus(_text(value, "entry_status")),
        product_index_at_entry=_decimal(value["product_index_at_entry"], "product_index_at_entry"),
        initial_net_credit_native=_decimal(
            value["initial_net_credit_native"], "initial_net_credit_native"
        ),
        initial_net_credit_usd=_decimal(value["initial_net_credit_usd"], "initial_net_credit_usd"),
        put_side=_side_from_object(_mapping(value["put_side"], "put_side")),
        call_side=_side_from_object(_mapping(value["call_side"], "call_side")),
        state=PositionState(_text(value, "state")),
        first_instruction=(
            _instruction_from_object(_mapping(first_raw, "first_instruction"))
            if first_raw is not None
            else None
        ),
        instructions=[
            _instruction_from_object(_mapping(member, "instruction")) for member in instructions_raw
        ],
        short_risk_flat_at=_optional_datetime(value["short_risk_flat_at"]),
        terminal_at=_optional_datetime(value["terminal_at"]),
        outcome=(
            _outcome_from_object(_mapping(outcome_raw, "outcome"))
            if outcome_raw is not None
            else None
        ),
        last_risk_observed_at=_optional_datetime(value["last_risk_observed_at"]),
        last_risk_context_known=last_risk_context_known_raw,
        last_risk_blockers=tuple(last_risk_blockers_raw),
    )
    expected_position_identity = shadow_position_identity(
        case_identity=position.case_identity,
        entry_identity=position.entry_identity,
    )
    if position.position_identity != expected_position_identity:
        raise JournalError("Position identity mismatch")
    if position.has_pending_exit and position.state is not PositionState.EXIT_REQUIRED:
        raise JournalError("pending short-risk duty must remain EXIT_REQUIRED")
    if position.state is PositionState.EXIT_REQUIRED and position.has_short_risk:
        if position.first_instruction is None:
            raise JournalError("short-risk duty lacks frozen instruction")
        for side in (position.put_side, position.call_side):
            if side.short_open and side.exit_requested_reason is None:
                raise JournalError("open short lacks pending exit duty")
    if (
        position.entry_status
        in {
            EntryStatus.PUT_SIDE_ONLY,
            EntryStatus.CALL_SIDE_ONLY,
            EntryStatus.TWO_SIDES_INCOHERENT,
        }
        and position.has_short_risk
    ):
        if position.state is not PositionState.EXIT_REQUIRED:
            raise JournalError("incomplete entry with short risk must remain EXIT_REQUIRED")
        if (
            position.first_instruction is None
            or position.first_instruction.reason is not ExitReason.ENTRY_ACQUISITION_INCOMPLETE
        ):
            raise JournalError("incomplete entry lacks frozen remediation instruction")
        for side in (position.put_side, position.call_side):
            if side.short_open and (
                side.exit_requested_reason is not ExitReason.ENTRY_ACQUISITION_INCOMPLETE
            ):
                raise JournalError("open short lacks acquisition-remediation duty")
    if position.outcome is not None:
        expected_outcome_identity = position_outcome_identity(
            position_identity=position.position_identity,
            terminal_at=position.outcome.terminal_at,
            terminal_method=position.outcome.terminal_method,
            put_side_native_pnl=position.outcome.put_side_native_pnl,
            call_side_native_pnl=position.outcome.call_side_native_pnl,
            total_native_pnl=position.outcome.total_native_pnl,
            boundary_valued_total_usd_pnl=(position.outcome.boundary_valued_total_usd_pnl),
            terminal_valued_total_usd_pnl=(position.outcome.terminal_valued_total_usd_pnl),
            put_side_delivery_fee_native=(position.outcome.put_side_delivery_fee_native),
            call_side_delivery_fee_native=(position.outcome.call_side_delivery_fee_native),
            residual_wings_settled=position.outcome.residual_wings_settled,
        )
        if position.outcome.outcome_identity != expected_outcome_identity:
            raise JournalError("Position outcome identity mismatch")
    return position


def _side_to_object(side: SidePosition) -> dict[str, object]:
    return {
        "side": side.side.value,
        "short_quote": _quote_to_object(side.short_quote),
        "long_quote": _quote_to_object(side.long_quote),
        "quantity": str(side.quantity),
        "state": side.state.value,
        "native_cashflow_after_fees": str(side.native_cashflow_after_fees),
        "boundary_valued_cashflow_usd": str(side.boundary_valued_cashflow_usd),
        "short_open": side.short_open,
        "long_open": side.long_open,
        "delivery_fee_native": str(side.delivery_fee_native),
        "exit_requested_at": _datetime_text(side.exit_requested_at),
        "exit_requested_reason": (
            side.exit_requested_reason.value if side.exit_requested_reason is not None else None
        ),
        "short_risk_exit_at": _datetime_text(side.short_risk_exit_at),
        "terminal_at": _datetime_text(side.terminal_at),
        "exit_reason": side.exit_reason.value if side.exit_reason is not None else None,
        "exit_attempt_count": side.exit_attempt_count,
        "quote_missing_block_count": side.quote_missing_block_count,
        "quote_not_future_block_count": side.quote_not_future_block_count,
        "quote_stale_block_count": side.quote_stale_block_count,
        "pair_incoherent_block_count": side.pair_incoherent_block_count,
        "pair_unexecutable_block_count": side.pair_unexecutable_block_count,
        "short_only_exit_used": side.short_only_exit_used,
        "last_exit_attempt_at": _datetime_text(side.last_exit_attempt_at),
        "short_exit_execution": (
            _leg_execution_to_object(side.short_exit_execution)
            if side.short_exit_execution is not None
            else None
        ),
        "long_exit_execution": (
            _leg_execution_to_object(side.long_exit_execution)
            if side.long_exit_execution is not None
            else None
        ),
        "last_exit_blockers": list(side.last_exit_blockers),
    }


def _side_from_object(value: Mapping[str, object]) -> SidePosition:
    last_exit_blockers = value.get("last_exit_blockers")
    if not isinstance(last_exit_blockers, list) or not all(
        isinstance(member, str) for member in last_exit_blockers
    ):
        raise JournalError("last_exit_blockers must be an array of text")
    short_exit_execution = value.get("short_exit_execution")
    long_exit_execution = value.get("long_exit_execution")
    return SidePosition(
        side=Side(_text(value, "side")),
        short_quote=_quote_from_object(_mapping(value["short_quote"], "short_quote")),
        long_quote=_quote_from_object(_mapping(value["long_quote"], "long_quote")),
        quantity=_decimal(value["quantity"], "quantity"),
        state=SideState(_text(value, "state")),
        native_cashflow_after_fees=_decimal(
            value["native_cashflow_after_fees"], "native_cashflow_after_fees"
        ),
        boundary_valued_cashflow_usd=_decimal(
            value["boundary_valued_cashflow_usd"], "boundary_valued_cashflow_usd"
        ),
        short_open=_bool(value, "short_open"),
        long_open=_bool(value, "long_open"),
        delivery_fee_native=_decimal(value["delivery_fee_native"], "delivery_fee_native"),
        exit_requested_at=_optional_datetime(value.get("exit_requested_at")),
        exit_requested_reason=(
            ExitReason(str(value["exit_requested_reason"]))
            if value.get("exit_requested_reason") is not None
            else None
        ),
        short_risk_exit_at=_optional_datetime(value.get("short_risk_exit_at")),
        terminal_at=_optional_datetime(value.get("terminal_at")),
        exit_reason=(
            ExitReason(str(value["exit_reason"])) if value.get("exit_reason") is not None else None
        ),
        exit_attempt_count=_non_negative_int(value, "exit_attempt_count"),
        quote_missing_block_count=_non_negative_int(value, "quote_missing_block_count"),
        quote_not_future_block_count=_non_negative_int(value, "quote_not_future_block_count"),
        quote_stale_block_count=_non_negative_int(value, "quote_stale_block_count"),
        pair_incoherent_block_count=_non_negative_int(value, "pair_incoherent_block_count"),
        pair_unexecutable_block_count=_non_negative_int(value, "pair_unexecutable_block_count"),
        short_only_exit_used=_bool(value, "short_only_exit_used"),
        last_exit_attempt_at=_optional_datetime(value.get("last_exit_attempt_at")),
        short_exit_execution=(
            _leg_execution_from_object(_mapping(short_exit_execution, "short_exit_execution"))
            if short_exit_execution is not None
            else None
        ),
        long_exit_execution=(
            _leg_execution_from_object(_mapping(long_exit_execution, "long_exit_execution"))
            if long_exit_execution is not None
            else None
        ),
        last_exit_blockers=tuple(last_exit_blockers),
    )


def _quote_to_object(quote: OptionQuote) -> dict[str, object]:
    return {
        "instrument_name": quote.instrument_name,
        "product_id": quote.product.product_id.value,
        "expiry": quote.expiry.isoformat(),
        "strike": str(quote.strike),
        "option_type": quote.option_type.value,
        "signed_delta": str(quote.signed_delta),
        "mark_iv": str(quote.mark_iv),
        "bid": [_level_to_object(level) for level in quote.bid],
        "ask": [_level_to_object(level) for level in quote.ask],
        "tick_schedule": {
            "base_tick": str(quote.tick_schedule.base_tick),
            "steps": [
                {"above_price": str(step.above_price), "tick_size": str(step.tick_size)}
                for step in quote.tick_schedule.steps
            ],
        },
        "open_interest": str(quote.open_interest),
        "gamma": str(quote.gamma),
        "source_timestamp_ms": quote.source_timestamp_ms,
        "received_timestamp_ms": quote.received_timestamp_ms,
        "continuity_epoch": quote.continuity_epoch,
        "delivery_fee_exempt": quote.delivery_fee_exempt,
    }


def _quote_from_object(value: Mapping[str, object]) -> OptionQuote:
    bid_raw = value.get("bid")
    ask_raw = value.get("ask")
    tick_raw = _mapping(value.get("tick_schedule"), "tick_schedule")
    steps_raw = tick_raw.get("steps")
    if (
        not isinstance(bid_raw, list)
        or not isinstance(ask_raw, list)
        or not isinstance(steps_raw, list)
    ):
        raise JournalError("quote book/tick arrays are invalid")
    product = PRODUCTS[ProductId(_text(value, "product_id"))]
    return OptionQuote(
        instrument_name=_text(value, "instrument_name"),
        product=product,
        expiry=_datetime(_text(value, "expiry")),
        strike=_decimal(value["strike"], "strike"),
        option_type=OptionType(_text(value, "option_type")),
        signed_delta=_decimal(value["signed_delta"], "signed_delta"),
        mark_iv=_decimal(value["mark_iv"], "mark_iv"),
        bid=tuple(_level_from_object(_mapping(member, "bid level")) for member in bid_raw),
        ask=tuple(_level_from_object(_mapping(member, "ask level")) for member in ask_raw),
        tick_schedule=TickSchedule(
            base_tick=_decimal(tick_raw["base_tick"], "base_tick"),
            steps=tuple(
                TickStep(
                    above_price=_decimal(
                        _mapping(member, "tick step")["above_price"],
                        "above_price",
                    ),
                    tick_size=_decimal(_mapping(member, "tick step")["tick_size"], "tick_size"),
                )
                for member in steps_raw
            ),
        ),
        open_interest=_decimal(value["open_interest"], "open_interest"),
        gamma=_decimal(value["gamma"], "gamma"),
        source_timestamp_ms=_non_negative_int(value, "source_timestamp_ms"),
        received_timestamp_ms=_non_negative_int(value, "received_timestamp_ms"),
        continuity_epoch=_non_negative_int(value, "continuity_epoch"),
        delivery_fee_exempt=_bool(value, "delivery_fee_exempt"),
    )


def _level_to_object(level: PriceLevel) -> dict[str, str]:
    return {"price": str(level.price), "quantity": str(level.quantity)}


def _level_from_object(value: Mapping[str, object]) -> PriceLevel:
    return PriceLevel(
        price=_decimal(value["price"], "level.price"),
        quantity=_decimal(value["quantity"], "level.quantity"),
    )


def _instruction_to_object(value: PositionInstruction) -> dict[str, object]:
    return {
        "instruction_identity": value.instruction_identity,
        "at": value.at.isoformat(),
        "scope": value.scope.value,
        "reason": value.reason.value,
    }


def _instruction_from_object(value: Mapping[str, object]) -> PositionInstruction:
    return PositionInstruction(
        instruction_identity=require_identity(
            _text(value, "instruction_identity"), "instruction_identity"
        ),
        at=_datetime(_text(value, "at")),
        scope=ExitScope(_text(value, "scope")),
        reason=ExitReason(_text(value, "reason")),
    )


def _outcome_to_object(value: PositionOutcome) -> dict[str, object]:
    return {
        "outcome_identity": value.outcome_identity,
        "terminal_at": value.terminal_at.isoformat(),
        "terminal_method": value.terminal_method,
        "entry_status": value.entry_status.value,
        "first_exit_reason": value.first_exit_reason.value if value.first_exit_reason else None,
        "first_exit_at": _datetime_text(value.first_exit_at),
        "short_risk_flat_at": _datetime_text(value.short_risk_flat_at),
        "put_side_exit_at": _datetime_text(value.put_side_exit_at),
        "call_side_exit_at": _datetime_text(value.call_side_exit_at),
        "put_side_native_pnl": str(value.put_side_native_pnl),
        "call_side_native_pnl": str(value.call_side_native_pnl),
        "total_native_pnl": str(value.total_native_pnl),
        "put_side_boundary_valued_pnl_usd": str(value.put_side_boundary_valued_pnl_usd),
        "call_side_boundary_valued_pnl_usd": str(value.call_side_boundary_valued_pnl_usd),
        "boundary_valued_total_usd_pnl": str(value.boundary_valued_total_usd_pnl),
        "terminal_valued_total_usd_pnl": str(value.terminal_valued_total_usd_pnl),
        "double_side_stop": value.double_side_stop,
        "put_side_delivery_fee_native": str(value.put_side_delivery_fee_native),
        "call_side_delivery_fee_native": str(value.call_side_delivery_fee_native),
        "total_delivery_fee_native": str(value.total_delivery_fee_native),
        "residual_wings_settled": value.residual_wings_settled,
        "residual_wing_count": value.residual_wing_count,
        "put_exit_attempt_count": value.put_exit_attempt_count,
        "call_exit_attempt_count": value.call_exit_attempt_count,
        "exit_quote_missing_block_count": value.exit_quote_missing_block_count,
        "exit_quote_not_future_block_count": value.exit_quote_not_future_block_count,
        "exit_quote_stale_block_count": value.exit_quote_stale_block_count,
        "exit_pair_incoherent_block_count": value.exit_pair_incoherent_block_count,
        "exit_pair_unexecutable_block_count": value.exit_pair_unexecutable_block_count,
        "short_only_exit_side_count": value.short_only_exit_side_count,
        "first_exit_to_short_risk_flat_ms": value.first_exit_to_short_risk_flat_ms,
    }


def _outcome_from_object(value: Mapping[str, object]) -> PositionOutcome:
    return PositionOutcome(
        outcome_identity=require_identity(_text(value, "outcome_identity"), "outcome_identity"),
        terminal_at=_datetime(_text(value, "terminal_at")),
        terminal_method=_text(value, "terminal_method"),
        entry_status=EntryStatus(_text(value, "entry_status")),
        first_exit_reason=(
            ExitReason(str(value["first_exit_reason"]))
            if value.get("first_exit_reason") is not None
            else None
        ),
        first_exit_at=_optional_datetime(value.get("first_exit_at")),
        short_risk_flat_at=_optional_datetime(value.get("short_risk_flat_at")),
        put_side_exit_at=_optional_datetime(value.get("put_side_exit_at")),
        call_side_exit_at=_optional_datetime(value.get("call_side_exit_at")),
        put_side_native_pnl=_decimal(value["put_side_native_pnl"], "put_side_native_pnl"),
        call_side_native_pnl=_decimal(value["call_side_native_pnl"], "call_side_native_pnl"),
        total_native_pnl=_decimal(value["total_native_pnl"], "total_native_pnl"),
        put_side_boundary_valued_pnl_usd=_decimal(
            value["put_side_boundary_valued_pnl_usd"],
            "put_side_boundary_valued_pnl_usd",
        ),
        call_side_boundary_valued_pnl_usd=_decimal(
            value["call_side_boundary_valued_pnl_usd"],
            "call_side_boundary_valued_pnl_usd",
        ),
        boundary_valued_total_usd_pnl=_decimal(
            value["boundary_valued_total_usd_pnl"],
            "boundary_valued_total_usd_pnl",
        ),
        terminal_valued_total_usd_pnl=_decimal(
            value["terminal_valued_total_usd_pnl"],
            "terminal_valued_total_usd_pnl",
        ),
        double_side_stop=_bool(value, "double_side_stop"),
        put_side_delivery_fee_native=_decimal(
            value["put_side_delivery_fee_native"], "put_side_delivery_fee_native"
        ),
        call_side_delivery_fee_native=_decimal(
            value["call_side_delivery_fee_native"], "call_side_delivery_fee_native"
        ),
        total_delivery_fee_native=_decimal(
            value["total_delivery_fee_native"], "total_delivery_fee_native"
        ),
        residual_wings_settled=_non_negative_int(value, "residual_wings_settled"),
        residual_wing_count=_non_negative_int(value, "residual_wing_count"),
        put_exit_attempt_count=_non_negative_int(value, "put_exit_attempt_count"),
        call_exit_attempt_count=_non_negative_int(value, "call_exit_attempt_count"),
        exit_quote_missing_block_count=_non_negative_int(value, "exit_quote_missing_block_count"),
        exit_quote_not_future_block_count=_non_negative_int(
            value, "exit_quote_not_future_block_count"
        ),
        exit_quote_stale_block_count=_non_negative_int(value, "exit_quote_stale_block_count"),
        exit_pair_incoherent_block_count=_non_negative_int(
            value, "exit_pair_incoherent_block_count"
        ),
        exit_pair_unexecutable_block_count=_non_negative_int(
            value, "exit_pair_unexecutable_block_count"
        ),
        short_only_exit_side_count=_non_negative_int(value, "short_only_exit_side_count"),
        first_exit_to_short_risk_flat_ms=(
            _non_negative_int(value, "first_exit_to_short_risk_flat_ms")
            if value.get("first_exit_to_short_risk_flat_ms") is not None
            else None
        ),
    )


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_datetime(value: object) -> datetime | None:
    return _datetime(str(value)) if value is not None else None


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise JournalError("journal datetime must be timezone-aware")
    return parsed


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise JournalError(f"{field} shape is invalid")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JournalError(f"{field} must be an object")
    return value


def _text(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise JournalError(f"{field} must be non-empty text")
    return member


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise JournalError(f"{field} must be decimal-compatible")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise JournalError(f"{field} must be finite")
    return parsed


def _bool(value: Mapping[str, object], field: str) -> bool:
    member = value.get(field)
    if not isinstance(member, bool):
        raise JournalError(f"{field} must be boolean")
    return member


def _non_negative_int(value: Mapping[str, object], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int) or member < 0:
        raise JournalError(f"{field} must be a non-negative integer")
    return member

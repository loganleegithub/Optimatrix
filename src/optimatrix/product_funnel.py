from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from optimatrix.identity import canonical_identity
from optimatrix.radar import Decision, RadarDecision


class FunnelStageName(StrEnum):
    APPLICABLE_SESSION_DECISION = "APPLICABLE_SESSION_DECISION"
    MARKET_CONTEXT_KNOWN = "MARKET_CONTEXT_KNOWN"
    VRP_THETA_QUALIFIED = "VRP_THETA_QUALIFIED"
    GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE = "GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE"
    TWO_SIDED_STRUCTURE_EVALUABLE = "TWO_SIDED_STRUCTURE_EVALUABLE"
    ENTRY_ROUTE_EVALUABLE = "ENTRY_ROUTE_EVALUABLE"
    ENTRY_ATTEMPT_SELECTED = "ENTRY_ATTEMPT_SELECTED"
    DECISION_CASE_OPENED = "DECISION_CASE_OPENED"
    ENTRY_RESULT_KNOWN = "ENTRY_RESULT_KNOWN"
    DECISION_CASE_OUTCOME_KNOWN = "DECISION_CASE_OUTCOME_KNOWN"


class FunnelStageStatus(StrEnum):
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_REACHED = "NOT_REACHED"


@dataclass(frozen=True)
class FunnelStage:
    name: FunnelStageName
    status: FunnelStageStatus
    denominator: int
    numerator: int
    blockers: tuple[str, ...]

    def as_object(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "denominator": self.denominator,
            "numerator": self.numerator,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ProductFunnelSnapshot:
    unit_identity: str
    session_id: str
    decision_window_identity: str
    policy_identity: str
    stages: tuple[FunnelStage, ...]
    current_node: FunnelStageName
    primary_blocker: str | None

    def as_object(self) -> dict[str, object]:
        return {
            "unit_identity": self.unit_identity,
            "session_id": self.session_id,
            "decision_window_identity": self.decision_window_identity,
            "policy_identity": self.policy_identity,
            "current_node": self.current_node.value,
            "primary_blocker": self.primary_blocker,
            "stages": [stage.as_object() for stage in self.stages],
        }


_VRP_THETA_BLOCKERS = {
    "SESSION_VRP_BELOW_THRESHOLD",
    "THETA_CAPTURE_TOO_SMALL",
}
_PATH_RISK_BLOCKERS = {
    "RV_ACCELERATION_TOO_HIGH",
    "JUMP_SHARE_TOO_HIGH",
    "DIRECTIONAL_PERSISTENCE_TOO_HIGH",
    "EVENT_OR_SHOCK_IN_PROGRESS",
    "CONCENTRATED_STRIKE_BREAKOUT",
}
_ROUTE_BLOCKERS = {
    "BODY_DISTANCE_TOO_SMALL",
    "NET_DELTA_TOO_DIRECTIONAL",
    "COMBINED_NET_CREDIT_TOO_SMALL",
    "CREDIT_TO_MAX_SIDE_PAYOFF_TOO_SMALL",
    "ENTRY_BOUNDARY_MAX_LOSS_TOO_HIGH",
    "FOUR_LEG_FEE_BURDEN_TOO_HIGH",
}


def project_product_funnel(
    decision: RadarDecision,
    *,
    policy_identity: str,
    decision_case_opened: bool | None = None,
    entry_result_known: bool | None = None,
    decision_case_outcome_known: bool | None = None,
) -> ProductFunnelSnapshot:
    """Project one causal SessionDecisionUnit without counting strike candidates."""

    decision_window_identity = f"{decision.session_id}:{decision.session_minute}"
    unit_identity = canonical_identity(
        "Btc0DteSessionDecisionUnitV1",
        "INVERSE_BTC",
        decision.session_id,
        decision_window_identity,
        policy_identity,
    )
    decision_blockers = set(decision.blockers)
    market_context_unknown = decision.decision is Decision.UNKNOWN
    if decision_case_opened is True and decision.decision is not Decision.CANDIDATE:
        raise ValueError("only a CANDIDATE can open a Decision Case")
    if entry_result_known is True and decision_case_opened is not True:
        raise ValueError("known entry result requires an opened Decision Case")
    if decision_case_outcome_known is True and entry_result_known is not True:
        raise ValueError("known Decision Outcome requires a known entry result")
    checks: tuple[tuple[FunnelStageName, bool | None, tuple[str, ...]], ...] = (
        (FunnelStageName.APPLICABLE_SESSION_DECISION, True, ()),
        (
            FunnelStageName.MARKET_CONTEXT_KNOWN,
            not market_context_unknown,
            decision.blockers if market_context_unknown else (),
        ),
        (
            FunnelStageName.VRP_THETA_QUALIFIED,
            not bool(decision_blockers & _VRP_THETA_BLOCKERS),
            _ordered_members(decision.blockers, _VRP_THETA_BLOCKERS),
        ),
        (
            FunnelStageName.GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE,
            not bool(decision_blockers & _PATH_RISK_BLOCKERS),
            _ordered_members(decision.blockers, _PATH_RISK_BLOCKERS),
        ),
        (
            FunnelStageName.TWO_SIDED_STRUCTURE_EVALUABLE,
            decision.structure is not None,
            (
                ()
                if decision.structure is not None
                else tuple(
                    blocker
                    for blocker in decision.blockers
                    if blocker.startswith("NO_") or blocker == "MIXED_EXPIRY_INPUT"
                )
            ),
        ),
        (
            FunnelStageName.ENTRY_ROUTE_EVALUABLE,
            not bool(decision_blockers & _ROUTE_BLOCKERS),
            _ordered_members(decision.blockers, _ROUTE_BLOCKERS),
        ),
        (
            FunnelStageName.ENTRY_ATTEMPT_SELECTED,
            decision.decision is Decision.CANDIDATE,
            (
                ()
                if decision.decision is Decision.CANDIDATE
                else tuple(
                    blocker
                    for blocker in decision.blockers
                    if blocker not in _VRP_THETA_BLOCKERS | _PATH_RISK_BLOCKERS | _ROUTE_BLOCKERS
                    and not blocker.startswith("NO_")
                    and blocker != "MIXED_EXPIRY_INPUT"
                )
            ),
        ),
        (
            FunnelStageName.DECISION_CASE_OPENED,
            decision_case_opened,
            ("DECISION_CASE_NOT_OPENED",),
        ),
        (
            FunnelStageName.ENTRY_RESULT_KNOWN,
            entry_result_known,
            ("ENTRY_RESULT_NOT_KNOWN",),
        ),
        (
            FunnelStageName.DECISION_CASE_OUTCOME_KNOWN,
            decision_case_outcome_known,
            ("DECISION_CASE_OUTCOME_NOT_KNOWN",),
        ),
    )
    stages: list[FunnelStage] = []
    reached = True
    primary_blocker: str | None = None
    current_node = FunnelStageName.APPLICABLE_SESSION_DECISION
    prior_numerator = 1
    for name, passed, blockers in checks:
        denominator = prior_numerator
        if not reached:
            stage = FunnelStage(name, FunnelStageStatus.NOT_REACHED, 0, 0, ())
        elif passed is None:
            stage = FunnelStage(name, FunnelStageStatus.NOT_REACHED, denominator, 0, ())
            reached = False
        elif passed:
            stage = FunnelStage(name, FunnelStageStatus.PASSED, denominator, 1, ())
        else:
            effective_blockers = blockers or (f"{name.value}_BLOCKED",)
            stage = FunnelStage(
                name,
                (
                    FunnelStageStatus.UNKNOWN
                    if name is FunnelStageName.MARKET_CONTEXT_KNOWN and market_context_unknown
                    else FunnelStageStatus.BLOCKED
                ),
                denominator,
                0,
                effective_blockers,
            )
            reached = False
            current_node = name
            primary_blocker = effective_blockers[0]
        stages.append(stage)
        prior_numerator = stage.numerator
        if reached:
            current_node = name
    return ProductFunnelSnapshot(
        unit_identity=unit_identity,
        session_id=decision.session_id,
        decision_window_identity=decision_window_identity,
        policy_identity=policy_identity,
        stages=tuple(stages),
        current_node=current_node,
        primary_blocker=primary_blocker,
    )


def _ordered_members(values: tuple[str, ...], members: set[str]) -> tuple[str, ...]:
    return tuple(value for value in values if value in members)

from __future__ import annotations

from datetime import datetime

from optimatrix.ai_lab.approval import HumanApproval, HumanDecision
from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    parse_utc,
    require_content_id,
    seal_object,
    utc_text,
    verify_seal,
)
from optimatrix.ai_lab.evaluation import RESULT_NAMESPACE
from optimatrix.ai_lab.store import AuditStore

PROMOTION_DECISION_SCHEMA = "optimatrix.ai-lab.promotion-decision.v1"
PROMOTION_DECISION_NAMESPACE = "OptimatrixAiLabPromotionDecisionV1"


def record_promotion_decision(
    *,
    store: AuditStore,
    result_id: str,
    decided_at: datetime,
    sealed_approval: object | None = None,
    automatic: bool = False,
) -> JsonObject:
    if automatic and sealed_approval is not None:
        raise ValidationError("automatic request cannot carry a human approval")
    if not automatic and sealed_approval is None:
        raise ValidationError("human promotion review requires an explicit approval record")
    result = store.find_result(result_id)
    if result is None:
        raise ValidationError("promotion review result does not exist")
    verify_seal(result, id_field="result_id", namespace=RESULT_NAMESPACE)
    experiment_id = require_content_id(result.get("experiment_id"), "result.experiment_id")
    result_recorded_at = parse_utc(result.get("recorded_at"), "result.recorded_at")
    if decided_at < result_recorded_at:
        raise ValidationError("promotion decision cannot predate its experiment result")

    reasons: list[str] = []
    approval_id: str | None = None
    approval_event_id: str | None = None
    approval_event_sequence: int | None = None
    requested_mode: str
    if automatic:
        requested_mode = "AUTOMATIC"
        outcome = "DENIED_AUTOMATIC_PROMOTION_FORBIDDEN"
        reasons.append("AUTOMATIC_PROMOTION_HAS_NO_AUTHORITY")
    else:
        requested_mode = "HUMAN"
        approval = HumanApproval.from_object(sealed_approval)
        approval_id = approval.approval_id
        if approval.result_id != result_id or approval.experiment_id != experiment_id:
            raise ValidationError("human approval does not bind the selected experiment result")
        if approval.decided_at != decided_at:
            raise ValidationError("promotion event boundary must match human approval")
        approval_event, _appended = store.append_approval(sealed_approval)
        approval_event_id = require_content_id(
            approval_event.get("event_id"), "approval_event.event_id"
        )
        approval_event_sequence = approval_event.get("sequence")
        if not isinstance(approval_event_sequence, int):
            raise ValidationError("approval event sequence is invalid")
        if approval.decision is HumanDecision.REJECT:
            outcome = "HUMAN_REJECTED"
            reasons.append("HUMAN_REJECTION")
        else:
            gate = result.get("promotion_gate")
            if not isinstance(gate, dict):
                raise ValidationError("experiment result promotion gate is malformed")
            if gate.get("human_review_status") == "ELIGIBLE_FOR_HUMAN_REVIEW":
                outcome = "APPROVED_FOR_SEPARATE_AUTHORITY_TASK"
                reasons.append("HUMAN_APPROVAL_RECORDED")
            else:
                outcome = "DENIED_FAIL_CLOSED"
                reasons.extend(str(reason) for reason in gate.get("reasons", ()))
                reasons.append("EXPERIMENT_NOT_ELIGIBLE_FOR_HUMAN_REVIEW")

    draft: JsonObject = {
        "schema_version": PROMOTION_DECISION_SCHEMA,
        "experiment_id": experiment_id,
        "result_id": result_id,
        "decided_at": utc_text(decided_at),
        "requested_mode": requested_mode,
        "approval_id": approval_id,
        "approval_event_id": approval_event_id,
        "approval_event_sequence": approval_event_sequence,
        "outcome": outcome,
        "reasons": reasons,
        "production_policy_mutated": False,
        "production_authority_activated": False,
        "boundary": "RESEARCH_RECOMMENDATION_ONLY_REQUIRES_SEPARATE_AUTHORITY_TASK",
    }
    decision = seal_object(
        draft,
        id_field="promotion_decision_id",
        namespace=PROMOTION_DECISION_NAMESPACE,
    )
    store.append_promotion_decision(decision)
    return decision

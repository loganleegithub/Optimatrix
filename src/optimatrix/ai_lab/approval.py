from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    parse_utc,
    require_content_id,
    require_text,
    seal_object,
    strict_fields,
    verify_seal,
)

APPROVAL_SCHEMA = "optimatrix.ai-lab.human-approval.v1"
APPROVAL_NAMESPACE = "OptimatrixAiLabHumanApprovalV1"


class HumanDecision(StrEnum):
    APPROVE_RESEARCH_RECOMMENDATION = "APPROVE_RESEARCH_RECOMMENDATION"
    REJECT = "REJECT"


@dataclass(frozen=True)
class HumanApproval:
    approval_id: str
    experiment_id: str
    result_id: str
    decision: HumanDecision
    decided_at: datetime
    approver: str
    rationale: str

    @classmethod
    def seal(cls, draft: Mapping[str, object]) -> JsonObject:
        value = seal_object(draft, id_field="approval_id", namespace=APPROVAL_NAMESPACE)
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "approval_id",
                "experiment_id",
                "result_id",
                "decision",
                "decided_at",
                "approver",
                "rationale",
            },
            "human_approval",
        )
        if item["schema_version"] != APPROVAL_SCHEMA:
            raise ValidationError("unsupported human approval schema")
        verify_seal(item, id_field="approval_id", namespace=APPROVAL_NAMESPACE)
        return cls(
            approval_id=require_content_id(item["approval_id"], "human_approval.approval_id"),
            experiment_id=require_content_id(item["experiment_id"], "human_approval.experiment_id"),
            result_id=require_content_id(item["result_id"], "human_approval.result_id"),
            decision=HumanDecision(require_text(item["decision"], "human_approval.decision")),
            decided_at=parse_utc(item["decided_at"], "human_approval.decided_at"),
            approver=require_text(item["approver"], "human_approval.approver"),
            rationale=require_text(item["rationale"], "human_approval.rationale"),
        )

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from optimatrix.ai_lab.approval import HumanApproval, HumanDecision
from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    canonical_bytes,
    isolated_path,
    parse_utc,
    reject_duplicate_keys,
    require_content_id,
    require_int,
    require_text,
    seal_object,
    strict_fields,
    verify_seal,
)
from optimatrix.ai_lab.models import ExperimentPlan, FrozenSpec
from optimatrix.ai_lab.registration import (
    APPEND_ORDER_SCOPE,
    LOCAL_TIME_AUTHORITY,
    ExperimentRegistration,
    SpecRegistrationReference,
)

EVENT_SCHEMA = "optimatrix.ai-lab.hash-chain-event.v1"
EVENT_NAMESPACE = "OptimatrixAiLabHashChainEventV1"


class HashChainLog:
    """Append-only JSONL with an fsynced, validated content-hash chain."""

    def __init__(self, root: Path, name: str, log_kind: str) -> None:
        if root.expanduser().is_symlink():
            raise ValidationError("audit-store root cannot be a symlink")
        resolved_root = isolated_path(root)
        self.path = resolved_root / name
        self.log_kind = log_kind

    def read(self) -> tuple[JsonObject, ...]:
        if not self.path.exists():
            return ()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValidationError(f"audit log must be a regular file: {self.path}")
        with self.path.open(encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                return self._decode(handle.read())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        payload: Mapping[str, object],
        *,
        identity_field: str,
    ) -> tuple[JsonObject, bool]:
        identifier = require_content_id(payload.get(identity_field), identity_field)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValidationError(f"audit log cannot be a symlink: {self.path}")
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                events = self._decode(handle.read())
                for event in events:
                    prior = event["payload"]
                    if isinstance(prior, dict) and prior.get(identity_field) == identifier:
                        if prior != dict(payload):
                            raise ValidationError(
                                f"{identity_field} already owns a different append-only payload"
                            )
                        return event, False
                draft: JsonObject = {
                    "schema_version": EVENT_SCHEMA,
                    "log_kind": self.log_kind,
                    "sequence": len(events) + 1,
                    "previous_event_id": events[-1]["event_id"] if events else None,
                    "payload": dict(payload),
                }
                event = seal_object(draft, id_field="event_id", namespace=EVENT_NAMESPACE)
                handle.seek(0, os.SEEK_END)
                handle.write(canonical_bytes(event).decode("utf-8") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return event, True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _decode(self, text: str) -> tuple[JsonObject, ...]:
        if text and not text.endswith("\n"):
            raise ValidationError(f"unterminated append-only log write: {self.path}")
        events: list[JsonObject] = []
        previous: str | None = None
        for line_number, line in enumerate(text.splitlines(), start=1):
            try:
                value: Any = json.loads(
                    line,
                    object_pairs_hook=reject_duplicate_keys,
                    parse_constant=lambda constant: (_ for _ in ()).throw(
                        ValidationError(f"non-finite JSON constant: {constant}")
                    ),
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValidationError(f"invalid append-only log line {line_number}: {exc}") from exc
            item = strict_fields(
                value,
                {
                    "schema_version",
                    "event_id",
                    "log_kind",
                    "sequence",
                    "previous_event_id",
                    "payload",
                },
                f"audit_event line {line_number}",
            )
            if item["schema_version"] != EVENT_SCHEMA or item["log_kind"] != self.log_kind:
                raise ValidationError(f"audit log identity mismatch at line {line_number}")
            verify_seal(item, id_field="event_id", namespace=EVENT_NAMESPACE)
            sequence = require_int(item["sequence"], "audit_event.sequence", minimum=1)
            if sequence != line_number:
                raise ValidationError(f"audit log sequence mismatch at line {line_number}")
            if item["previous_event_id"] != previous:
                raise ValidationError(f"audit log hash chain mismatch at line {line_number}")
            if not isinstance(item["payload"], dict):
                raise ValidationError(
                    f"audit event payload must be an object at line {line_number}"
                )
            previous = require_content_id(item["event_id"], "audit_event.event_id")
            events.append(item)
        return tuple(events)


class AuditStore:
    def __init__(self, root: Path) -> None:
        self.root = isolated_path(root)
        self.registrations = HashChainLog(
            self.root,
            "experiment-registrations.jsonl",
            "REGISTRATION",
        )
        self.manifests = HashChainLog(self.root, "experiment-manifests.jsonl", "MANIFEST")
        self.results = HashChainLog(self.root, "experiment-results.jsonl", "RESULT")
        self.approvals = HashChainLog(self.root, "human-approvals.jsonl", "HUMAN_APPROVAL")
        self.promotions = HashChainLog(
            self.root,
            "promotion-decisions.jsonl",
            "PROMOTION_DECISION",
        )

    def append_registration(self, registration: Mapping[str, object]) -> tuple[JsonObject, bool]:
        ExperimentRegistration.from_object(registration)
        return self.registrations.append(registration, identity_field="registration_id")

    def register_experiment(
        self,
        *,
        base: FrozenSpec,
        challenger: FrozenSpec,
        plan: ExperimentPlan,
        recorded_at: datetime,
    ) -> tuple[JsonObject, JsonObject, bool]:
        """Append once per exact spec/plan identity, returning the first local anchor."""
        for event in self.registrations.read():
            payload = event["payload"]
            parsed_registration = ExperimentRegistration.from_object(payload)
            if parsed_registration.matches(base=base, challenger=challenger, plan=plan):
                return payload, event, False
        registration_payload = ExperimentRegistration.create(
            base=base,
            challenger=challenger,
            plan=plan,
            recorded_at=recorded_at,
        )
        event, appended = self.append_registration(registration_payload)
        return registration_payload, event, appended

    def require_registration(
        self,
        *,
        registration_id: str,
        base: FrozenSpec,
        challenger: FrozenSpec,
        plan: ExperimentPlan,
    ) -> tuple[ExperimentRegistration, JsonObject]:
        identifier = require_content_id(registration_id, "registration_id")
        for event in self.registrations.read():
            payload = event["payload"]
            if isinstance(payload, dict) and payload.get("registration_id") == identifier:
                registration = ExperimentRegistration.from_object(payload)
                if not registration.matches(base=base, challenger=challenger, plan=plan):
                    raise ValidationError(
                        "registration does not exactly bind the supplied Base, Challenger, and plan"
                    )
                return registration, event
        raise ValidationError("matching experiment registration does not exist in this store")

    def append_manifest(self, manifest: Mapping[str, object]) -> bool:
        from optimatrix.ai_lab.evaluation import MANIFEST_NAMESPACE

        verify_seal(manifest, id_field="experiment_id", namespace=MANIFEST_NAMESPACE)
        self._validate_manifest_registration(manifest, self.registrations.read())
        _event, appended = self.manifests.append(
            manifest,
            identity_field="experiment_id",
        )
        return appended

    def append_result(self, result: Mapping[str, object]) -> bool:
        from optimatrix.ai_lab.evaluation import RESULT_NAMESPACE

        verify_seal(result, id_field="result_id", namespace=RESULT_NAMESPACE)
        experiment_id = require_content_id(result.get("experiment_id"), "result.experiment_id")
        manifest_ids = {event["payload"].get("experiment_id") for event in self.manifests.read()}
        if experiment_id not in manifest_ids:
            raise ValidationError("experiment result requires an existing manifest")
        _event, appended = self.results.append(result, identity_field="result_id")
        return appended

    def append_approval(self, approval: object) -> tuple[JsonObject, bool]:
        if not isinstance(approval, Mapping):
            raise ValidationError("human approval must be a sealed mapping")
        parsed = HumanApproval.from_object(approval)
        result = self.find_result(parsed.result_id)
        if result is None:
            raise ValidationError("human approval requires an existing result")
        if result.get("experiment_id") != parsed.experiment_id:
            raise ValidationError("human approval experiment does not match its result")
        if parsed.decided_at < parse_utc(result.get("recorded_at"), "result.recorded_at"):
            raise ValidationError("human approval cannot predate its result")
        return self.approvals.append(approval, identity_field="approval_id")

    def append_promotion_decision(self, decision: Mapping[str, object]) -> bool:
        from optimatrix.ai_lab.promotion import PROMOTION_DECISION_NAMESPACE

        verify_seal(
            decision,
            id_field="promotion_decision_id",
            namespace=PROMOTION_DECISION_NAMESPACE,
        )
        result_id = require_content_id(decision.get("result_id"), "promotion_decision.result_id")
        result = self.find_result(result_id)
        if result is None:
            raise ValidationError("promotion decision requires an existing result")
        self._validate_promotion_references(decision, result, self.approvals.read())
        _event, appended = self.promotions.append(
            decision,
            identity_field="promotion_decision_id",
        )
        return appended

    def find_result(self, result_id: str) -> JsonObject | None:
        from optimatrix.ai_lab.evaluation import RESULT_NAMESPACE

        require_content_id(result_id, "result_id")
        for event in self.results.read():
            payload = event["payload"]
            if isinstance(payload, dict) and payload.get("result_id") == result_id:
                verify_seal(payload, id_field="result_id", namespace=RESULT_NAMESPACE)
                return payload
        return None

    def find_approval(self, approval_id: str) -> JsonObject | None:
        identifier = require_content_id(approval_id, "approval_id")
        for event in self.approvals.read():
            payload = event["payload"]
            if isinstance(payload, dict) and payload.get("approval_id") == identifier:
                HumanApproval.from_object(payload)
                return payload
        return None

    def verify(self) -> JsonObject:
        from optimatrix.ai_lab.evaluation import (
            MANIFEST_NAMESPACE,
            RESULT_NAMESPACE,
        )
        from optimatrix.ai_lab.promotion import PROMOTION_DECISION_NAMESPACE

        registrations = self.registrations.read()
        manifests = self.manifests.read()
        results = self.results.read()
        approvals = self.approvals.read()
        promotions = self.promotions.read()
        for event in registrations:
            ExperimentRegistration.from_object(event["payload"])
        for event in manifests:
            verify_seal(
                event["payload"],
                id_field="experiment_id",
                namespace=MANIFEST_NAMESPACE,
            )
            self._validate_manifest_registration(event["payload"], registrations)
        manifest_ids = {event["payload"].get("experiment_id") for event in manifests}
        result_ids = {event["payload"].get("result_id") for event in results}
        for event in results:
            verify_seal(event["payload"], id_field="result_id", namespace=RESULT_NAMESPACE)
            if event["payload"].get("experiment_id") not in manifest_ids:
                raise ValidationError("audit store contains an orphan result")
        for event in approvals:
            approval = HumanApproval.from_object(event["payload"])
            result = next(
                (
                    member["payload"]
                    for member in results
                    if member["payload"].get("result_id") == approval.result_id
                ),
                None,
            )
            if result is None or result.get("experiment_id") != approval.experiment_id:
                raise ValidationError("audit store contains an orphan human approval")
            if approval.decided_at < parse_utc(result.get("recorded_at"), "result.recorded_at"):
                raise ValidationError("audit store contains an approval that predates its result")
        for event in promotions:
            decision = event["payload"]
            verify_seal(
                decision,
                id_field="promotion_decision_id",
                namespace=PROMOTION_DECISION_NAMESPACE,
            )
            result = next(
                (
                    member["payload"]
                    for member in results
                    if member["payload"].get("result_id") == decision.get("result_id")
                ),
                None,
            )
            if result is None or decision.get("result_id") not in result_ids:
                raise ValidationError("audit store contains an orphan promotion decision")
            self._validate_promotion_references(decision, result, approvals)
        return {
            "status": "VALID_HASH_CHAINS",
            "registration_count": len(registrations),
            "manifest_count": len(manifests),
            "result_count": len(results),
            "approval_count": len(approvals),
            "promotion_decision_count": len(promotions),
        }

    def _validate_manifest_registration(
        self,
        manifest: Mapping[str, object],
        registration_events: tuple[JsonObject, ...],
    ) -> None:
        reference = strict_fields(
            manifest.get("registration"),
            {
                "registration_id",
                "registration_event_id",
                "registration_event_sequence",
                "recorded_at",
                "local_time_authority",
                "append_order_scope",
            },
            "manifest.registration",
        )
        registration_id = require_content_id(
            reference["registration_id"], "manifest.registration.registration_id"
        )
        event_id = require_content_id(
            reference["registration_event_id"],
            "manifest.registration.registration_event_id",
        )
        event_sequence = require_int(
            reference["registration_event_sequence"],
            "manifest.registration.registration_event_sequence",
            minimum=1,
        )
        event = next(
            (
                member
                for member in registration_events
                if member.get("event_id") == event_id
                and member.get("sequence") == event_sequence
                and member["payload"].get("registration_id") == registration_id
            ),
            None,
        )
        if event is None:
            raise ValidationError("manifest does not anchor an earlier registration event")
        registration = ExperimentRegistration.from_object(event["payload"])
        if (
            reference["recorded_at"] != event["payload"].get("recorded_at")
            or reference["local_time_authority"] != LOCAL_TIME_AUTHORITY
            or reference["append_order_scope"] != APPEND_ORDER_SCOPE
        ):
            raise ValidationError("manifest registration boundary does not match its event")
        if parse_utc(reference["recorded_at"], "manifest.registration.recorded_at") > parse_utc(
            manifest.get("recorded_at"), "manifest.recorded_at"
        ):
            raise ValidationError("manifest cannot predate its local registration event")
        specs = manifest.get("specs")
        split = manifest.get("split")
        evaluation = manifest.get("evaluation")
        if (
            not isinstance(specs, dict)
            or not isinstance(split, dict)
            or not isinstance(evaluation, dict)
        ):
            raise ValidationError("manifest registration owners are malformed")
        if not _spec_reference_matches(specs.get("base"), registration.base_spec):
            raise ValidationError("manifest Base does not match its registration")
        if not _spec_reference_matches(specs.get("challenger"), registration.challenger_spec):
            raise ValidationError("manifest Challenger does not match its registration")
        if (
            split.get("plan_id") != registration.plan.plan_id
            or split.get("mode") != registration.plan.mode
            or evaluation.get("evaluator_id") != registration.plan.evaluator_id
        ):
            raise ValidationError("manifest plan does not match its registration")

    def _validate_promotion_references(
        self,
        decision: Mapping[str, object],
        result: Mapping[str, object],
        approval_events: tuple[JsonObject, ...],
    ) -> None:
        if decision.get("schema_version") != "optimatrix.ai-lab.promotion-decision.v1":
            raise ValidationError("unsupported promotion decision schema")
        if decision.get("experiment_id") != result.get("experiment_id"):
            raise ValidationError("promotion experiment does not match its result")
        decided_at = parse_utc(decision.get("decided_at"), "promotion.decided_at")
        if decided_at < parse_utc(result.get("recorded_at"), "result.recorded_at"):
            raise ValidationError("promotion decision cannot predate its result")
        if (
            decision.get("production_policy_mutated") is not False
            or decision.get("production_authority_activated") is not False
            or decision.get("boundary")
            != "RESEARCH_RECOMMENDATION_ONLY_REQUIRES_SEPARATE_AUTHORITY_TASK"
        ):
            raise ValidationError("promotion decision exceeds the research-only authority boundary")
        mode = require_text(decision.get("requested_mode"), "promotion.requested_mode")
        approval_id = decision.get("approval_id")
        approval_event_id = decision.get("approval_event_id")
        approval_sequence = decision.get("approval_event_sequence")
        if mode == "AUTOMATIC":
            if any(
                value is not None for value in (approval_id, approval_event_id, approval_sequence)
            ):
                raise ValidationError("automatic promotion cannot bind a human approval")
            if decision.get("outcome") != "DENIED_AUTOMATIC_PROMOTION_FORBIDDEN":
                raise ValidationError("automatic promotion must remain permanently denied")
            return
        if mode != "HUMAN":
            raise ValidationError("promotion requested_mode is invalid")
        identifier = require_content_id(approval_id, "promotion.approval_id")
        event_identifier = require_content_id(approval_event_id, "promotion.approval_event_id")
        sequence = require_int(
            approval_sequence,
            "promotion.approval_event_sequence",
            minimum=1,
        )
        event = next(
            (
                member
                for member in approval_events
                if member.get("event_id") == event_identifier
                and member.get("sequence") == sequence
                and member["payload"].get("approval_id") == identifier
            ),
            None,
        )
        if event is None:
            raise ValidationError("promotion does not anchor an earlier human approval event")
        approval = HumanApproval.from_object(event["payload"])
        if approval.result_id != result.get("result_id") or approval.experiment_id != result.get(
            "experiment_id"
        ):
            raise ValidationError("promotion approval does not match its result")
        if approval.decided_at != decided_at:
            raise ValidationError("promotion boundary does not match its human approval")
        promotion_gate = result.get("promotion_gate")
        expected_outcome = (
            "HUMAN_REJECTED"
            if approval.decision is HumanDecision.REJECT
            else "APPROVED_FOR_SEPARATE_AUTHORITY_TASK"
            if isinstance(promotion_gate, dict)
            and promotion_gate.get("human_review_status") == "ELIGIBLE_FOR_HUMAN_REVIEW"
            else "DENIED_FAIL_CLOSED"
        )
        if decision.get("outcome") != expected_outcome:
            raise ValidationError("promotion outcome does not match its sealed human approval")


def _spec_reference_matches(value: object, registered: SpecRegistrationReference) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("spec_id") == registered.spec_id
        and value.get("role") == registered.role.value
        and value.get("version") == registered.version
        and value.get("external_policy_id") == registered.external_policy_id
        and value.get("implementation_id") == registered.implementation_id
    )

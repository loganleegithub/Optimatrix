from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from optimatrix.ai_lab.approval import (
    APPROVAL_SCHEMA,
    HumanApproval,
    HumanDecision,
)
from optimatrix.ai_lab.canonical import ValidationError, content_id
from optimatrix.ai_lab.demo import build_demo_documents
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.models import DecisionWindowExport, ExperimentPlan, FrozenSpec
from optimatrix.ai_lab.promotion import record_promotion_decision
from optimatrix.ai_lab.registration import ExperimentRegistration
from optimatrix.ai_lab.store import AuditStore


def _run(store: AuditStore):
    base_value, challenger_value, plan_value, dataset_value = build_demo_documents()
    base = FrozenSpec.from_object(base_value)
    challenger = FrozenSpec.from_object(challenger_value)
    plan = ExperimentPlan.from_object(plan_value)
    registration = ExperimentRegistration.create(
        base=base,
        challenger=challenger,
        plan=plan,
        recorded_at=datetime(2026, 1, 2, 2, 4, tzinfo=UTC),
    )
    store.append_registration(registration)
    return ExperimentRunner().run(
        base=base,
        challenger=challenger,
        dataset=DecisionWindowExport.from_object(dataset_value),
        plan=plan,
        store=store,
        registration_id=str(registration["registration_id"]),
        recorded_at=datetime(2026, 1, 2, 2, 5, tzinfo=UTC),
    )


def _sealed_approval(result, *, rationale: str = "exercise the explicit human gate only"):
    return HumanApproval.seal(
        {
            "schema_version": APPROVAL_SCHEMA,
            "experiment_id": result["experiment_id"],
            "result_id": result["result_id"],
            "decision": "APPROVE_RESEARCH_RECOMMENDATION",
            "decided_at": "2026-01-02T02:07:00Z",
            "approver": "synthetic-human-fixture",
            "rationale": rationale,
        }
    )


class StoreAndPromotionTests(unittest.TestCase):
    def test_manifest_and_result_appends_are_idempotent_and_hash_chained(self) -> None:
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            first = _run(store)
            second = _run(store)
            self.assertEqual(first["result_id"], second["result_id"])
            self.assertEqual(
                store.verify(),
                {
                    "status": "VALID_HASH_CHAINS",
                    "registration_count": 1,
                    "manifest_count": 1,
                    "result_count": 1,
                    "approval_count": 0,
                    "promotion_decision_count": 0,
                },
            )

    def test_hash_chain_detects_result_tampering(self) -> None:
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            _run(store)
            text = store.results.path.read_text(encoding="utf-8")
            store.results.path.write_text(
                text.replace("PARTIAL_INCOMPARABLE", "TAMPERED_RESULT", 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValidationError, "content identity mismatch"):
                store.verify()

    def test_automatic_promotion_and_ineligible_human_approval_fail_closed(self) -> None:
        rationale = "full rationale remains recoverable from the sealed audit chain"
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            result = _run(store)
            automatic = record_promotion_decision(
                store=store,
                result_id=result["result_id"],
                decided_at=datetime(2026, 1, 2, 2, 6, tzinfo=UTC),
                automatic=True,
            )
            self.assertEqual(
                automatic["outcome"],
                "DENIED_AUTOMATIC_PROMOTION_FORBIDDEN",
            )
            self.assertIsNone(automatic["approval_id"])
            self.assertFalse(automatic["production_policy_mutated"])

            approval_value = _sealed_approval(result, rationale=rationale)
            human = record_promotion_decision(
                store=store,
                result_id=result["result_id"],
                decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                sealed_approval=approval_value,
            )
            self.assertEqual(human["outcome"], "DENIED_FAIL_CLOSED")
            self.assertIn(
                "STRATEGY_QUALIFICATION_EVALUATOR_UNVERIFIED",
                human["reasons"],
            )
            recovered = store.find_approval(str(approval_value["approval_id"]))
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered["rationale"], rationale)
            verified = store.verify()
            self.assertEqual(verified["approval_count"], 1)
            self.assertEqual(verified["promotion_decision_count"], 2)

    def test_approval_hash_chain_detects_tampering(self) -> None:
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            result = _run(store)
            record_promotion_decision(
                store=store,
                result_id=result["result_id"],
                decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                sealed_approval=_sealed_approval(result),
            )
            text = store.approvals.path.read_text(encoding="utf-8")
            store.approvals.path.write_text(
                text.replace("explicit human gate", "tampered human gate", 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValidationError, "content identity mismatch"):
                store.verify()

    def test_orphan_approval_is_rejected_by_verify(self) -> None:
        orphan = HumanApproval.seal(
            {
                "schema_version": APPROVAL_SCHEMA,
                "experiment_id": content_id("test", {"experiment": "missing"}),
                "result_id": content_id("test", {"result": "missing"}),
                "decision": "REJECT",
                "decided_at": "2026-01-02T02:07:00Z",
                "approver": "synthetic-human-fixture",
                "rationale": "orphan fixture must fail verification",
            }
        )
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            store.approvals.append(orphan, identity_field="approval_id")

            with self.assertRaisesRegex(ValidationError, "orphan human approval"):
                store.verify()

    def test_forged_dataclass_and_unsealed_approval_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            result = _run(store)
            forged = HumanApproval(
                approval_id=content_id("test", {"forged": "approval"}),
                experiment_id=str(result["experiment_id"]),
                result_id=str(result["result_id"]),
                decision=HumanDecision.APPROVE_RESEARCH_RECOMMENDATION,
                decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                approver="forged-dataclass",
                rationale="not derived from a verified sealed mapping",
            )
            with self.assertRaisesRegex(ValidationError, "must be an object"):
                record_promotion_decision(
                    store=store,
                    result_id=result["result_id"],
                    decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                    sealed_approval=forged,
                )
            with self.assertRaisesRegex(ValidationError, "sealed mapping"):
                store.append_approval(forged)

            unsealed = dict(_sealed_approval(result))
            del unsealed["approval_id"]
            with self.assertRaisesRegex(ValidationError, "approval_id"):
                record_promotion_decision(
                    store=store,
                    result_id=result["result_id"],
                    decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                    sealed_approval=unsealed,
                )

    def test_promotion_requires_its_anchored_approval_to_remain_present(self) -> None:
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            result = _run(store)
            record_promotion_decision(
                store=store,
                result_id=result["result_id"],
                decided_at=datetime(2026, 1, 2, 2, 7, tzinfo=UTC),
                sealed_approval=_sealed_approval(result),
            )
            store.approvals.path.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "earlier human approval event"):
                store.verify()


if __name__ == "__main__":
    unittest.main()

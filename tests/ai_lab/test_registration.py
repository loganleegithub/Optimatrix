from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from optimatrix.ai_lab.canonical import ValidationError, content_id
from optimatrix.ai_lab.demo import build_demo_documents
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.models import DecisionWindowExport, ExperimentPlan, FrozenSpec
from optimatrix.ai_lab.registration import ExperimentRegistration
from optimatrix.ai_lab.store import AuditStore


def _documents():
    base_value, challenger_value, plan_value, dataset_value = build_demo_documents()
    return (
        FrozenSpec.from_object(base_value),
        FrozenSpec.from_object(challenger_value),
        ExperimentPlan.from_object(plan_value),
        DecisionWindowExport.from_object(dataset_value),
    )


def _registration(base, challenger, plan):
    return ExperimentRegistration.create(
        base=base,
        challenger=challenger,
        plan=plan,
        recorded_at=datetime(2026, 1, 2, 2, 4, tzinfo=UTC),
    )


class RegistrationTests(unittest.TestCase):
    def test_run_without_registration_is_rejected(self) -> None:
        base, challenger, plan, dataset = _documents()
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            with self.assertRaisesRegex(ValidationError, "registration does not exist"):
                ExperimentRunner().run(
                    base=base,
                    challenger=challenger,
                    dataset=dataset,
                    plan=plan,
                    store=store,
                    registration_id=content_id("missing", {"registration": 1}),
                    recorded_at=datetime(2026, 1, 2, 2, 5, tzinfo=UTC),
                )

    def test_registration_identity_mismatch_is_rejected(self) -> None:
        base, challenger, plan, dataset = _documents()
        _base_value, _challenger_value, plan_value, _dataset_value = build_demo_documents()
        alternative_draft = deepcopy(plan_value)
        del alternative_draft["plan_id"]
        alternative_draft["metric_ids"] = ["NO_TRADE_AGREEMENT_COUNT"]
        alternative = ExperimentPlan.from_object(ExperimentPlan.seal(alternative_draft))
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            registration = _registration(base, challenger, plan)
            store.append_registration(registration)

            with self.assertRaisesRegex(ValidationError, "does not exactly bind"):
                ExperimentRunner().run(
                    base=base,
                    challenger=challenger,
                    dataset=dataset,
                    plan=alternative,
                    store=store,
                    registration_id=str(registration["registration_id"]),
                    recorded_at=datetime(2026, 1, 2, 2, 5, tzinfo=UTC),
                )

    def test_registration_is_earlier_anchor_and_duplicate_is_idempotent(self) -> None:
        base, challenger, plan, dataset = _documents()
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            registration = _registration(base, challenger, plan)
            event, appended = store.append_registration(registration)
            duplicate_event, duplicate_appended = store.append_registration(registration)
            self.assertTrue(appended)
            self.assertFalse(duplicate_appended)
            self.assertEqual(event, duplicate_event)
            existing, existing_event, existing_appended = store.register_experiment(
                base=base,
                challenger=challenger,
                plan=plan,
                recorded_at=datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
            )
            self.assertFalse(existing_appended)
            self.assertEqual(existing, registration)
            self.assertEqual(existing_event, event)

            result = ExperimentRunner().run(
                base=base,
                challenger=challenger,
                dataset=dataset,
                plan=plan,
                store=store,
                registration_id=str(registration["registration_id"]),
                recorded_at=datetime(2026, 1, 2, 2, 5, tzinfo=UTC),
            )
            manifest = store.manifests.read()[0]["payload"]
            self.assertEqual(manifest["registration"]["registration_event_id"], event["event_id"])
            self.assertEqual(manifest["registration"]["registration_event_sequence"], 1)
            self.assertEqual(
                result["claim_boundary"]["registration_assurance"], "SAME_STORE_APPEND_ORDER_ONLY"
            )
            self.assertEqual(store.verify()["registration_count"], 1)

    def test_registration_hash_chain_detects_tampering(self) -> None:
        base, challenger, plan, _dataset = _documents()
        with TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit")
            store.append_registration(_registration(base, challenger, plan))
            text = store.registrations.path.read_text(encoding="utf-8")
            store.registrations.path.write_text(
                text.replace("demo-base-v1", "demo-base-v2", 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValidationError, "content identity mismatch"):
                store.verify()


if __name__ == "__main__":
    unittest.main()

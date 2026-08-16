from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from optimatrix.ai_lab.demo import build_demo_documents
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.models import DecisionWindowExport, ExperimentPlan, FrozenSpec
from optimatrix.ai_lab.registration import ExperimentRegistration
from optimatrix.ai_lab.store import AuditStore


def _run(directory: str):
    base_value, challenger_value, plan_value, dataset_value = build_demo_documents()
    base = FrozenSpec.from_object(base_value)
    challenger = FrozenSpec.from_object(challenger_value)
    plan = ExperimentPlan.from_object(plan_value)
    store = AuditStore(Path(directory) / "audit")
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


class EvaluationTests(unittest.TestCase):
    def test_no_trade_is_comparable_and_summary_is_not_replayable(self) -> None:
        with TemporaryDirectory() as directory:
            result = _run(directory)

        population = result["comparison_population"]
        self.assertEqual(population["decision_windows"], 4)
        self.assertEqual(population["comparable_windows"], 3)
        self.assertEqual(population["known_no_trade_base_windows"], 2)
        self.assertEqual(population["known_no_trade_challenger_windows"], 2)
        self.assertTrue(population["no_trade_windows_are_comparable"])
        self.assertEqual(result["incomparable_reason_counts"], {"FUTURE_PATH_SUMMARY_ONLY": 1})

    def test_synthetic_mechanism_cannot_become_edge_or_auto_promotion(self) -> None:
        with TemporaryDirectory() as directory:
            result = _run(directory)

        self.assertEqual(result["evidence_scope"], "SYNTHETIC_MECHANISM_ONLY")
        self.assertEqual(result["claim_boundary"]["market_edge"], "UNVERIFIED")
        self.assertEqual(result["claim_boundary"]["b3_natural_forward_chain"], "UNVERIFIED")
        gate = result["promotion_gate"]
        self.assertEqual(gate["automatic_promotion"], "DENIED_FAIL_CLOSED")
        self.assertFalse(gate["candidate_count_used"])
        self.assertFalse(gate["trade_frequency_used"])
        candidate_metrics = {
            metric["metric_id"]: metric["promotion_use"]
            for metric in result["metrics"]
            if "CANDIDATE" in metric["metric_id"]
        }
        self.assertEqual(set(candidate_metrics.values()), {"FORBIDDEN"})

    def test_economic_metrics_are_explicitly_unverified(self) -> None:
        with TemporaryDirectory() as directory:
            result = _run(directory)

        unavailable = {
            metric["metric_id"]: metric["reason"]
            for metric in result["unavailable_strategy_metrics"]
        }
        self.assertEqual(
            unavailable["EXPECTED_SHORTFALL_CVAR"],
            "STRATEGY_VALUATION_INTERFACE_UNVERIFIED",
        )
        self.assertEqual(
            unavailable["POLICY_QUALIFICATION"],
            "STRATEGY_VALUATION_INTERFACE_UNVERIFIED",
        )


if __name__ == "__main__":
    unittest.main()

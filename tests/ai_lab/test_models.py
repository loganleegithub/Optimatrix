from __future__ import annotations

import random
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from optimatrix.ai_lab.canonical import ValidationError, content_id, utc_text
from optimatrix.ai_lab.demo import build_demo_documents
from optimatrix.ai_lab.models import (
    PLAN_SCHEMA,
    DecisionWindowExport,
    ExperimentPlan,
    FrozenSpec,
    FullFuturePath,
)


class FrozenModelTests(unittest.TestCase):
    def test_frozen_spec_is_content_addressed(self) -> None:
        base_value, _challenger, _plan, _dataset = build_demo_documents()
        self.assertEqual(FrozenSpec.from_object(base_value).version, "demo-base-v1")

        tampered = deepcopy(base_value)
        tampered["version"] = "silently-rewritten"
        with self.assertRaisesRegex(ValidationError, "content identity mismatch"):
            FrozenSpec.from_object(tampered)

    def test_future_path_cannot_begin_before_both_decisions(self) -> None:
        _base, _challenger, _plan, dataset_value = build_demo_documents()
        draft = deepcopy(dataset_value)
        del draft["export_id"]
        window = draft["windows"][0]
        decision_known_at = window["base_decision"]["known_at"]
        path = window["future_path"]
        path["starts_at"] = decision_known_at
        path["points"][0]["observed_at"] = decision_known_at

        with self.assertRaisesRegex(ValidationError, "strictly after both frozen decisions"):
            DecisionWindowExport.seal(draft)

    def test_property_all_adjacent_path_reversals_fail_closed(self) -> None:
        _base, _challenger, _plan, dataset_value = build_demo_documents()
        path = dataset_value["windows"][0]["future_path"]
        self.assertIsInstance(FullFuturePath.from_object(path), FullFuturePath)
        points = path["points"]
        for index in range(len(points) - 1):
            malformed = deepcopy(path)
            malformed["points"][index], malformed["points"][index + 1] = (
                malformed["points"][index + 1],
                malformed["points"][index],
            )
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValidationError, "boundaries|strictly chronological"):
                    FullFuturePath.from_object(malformed)

    def test_property_strictly_chronological_positive_paths_are_accepted(self) -> None:
        generator = random.Random(20260815)
        for sample in range(50):
            start = datetime(2026, 1, 3, tzinfo=UTC) + timedelta(hours=sample)
            values = [str(90_000 + generator.randint(1, 10_000)) for _ in range(5)]
            path = {
                "kind": "FULL_PATH",
                "actuality": "SYNTHETIC_FIXTURE",
                "source_id": "PROPERTY_FIXTURE",
                "method_id": "FIVE_POINT_PATH_V1",
                "starts_at": utc_text(start),
                "ends_at": utc_text(start + timedelta(minutes=4)),
                "known_at": utc_text(start + timedelta(minutes=4, seconds=1)),
                "continuous": True,
                "points": [
                    {
                        "observed_at": utc_text(start + timedelta(minutes=index)),
                        "known_at": utc_text(start + timedelta(minutes=index, seconds=1)),
                        "index_price_usd": value,
                    }
                    for index, value in enumerate(values)
                ],
            }
            with self.subTest(sample=sample):
                restored = FullFuturePath.from_object(path)
                self.assertEqual(len(restored.points), 5)

    def test_walk_forward_rejects_training_cutoff_leakage(self) -> None:
        base_value, challenger_value, _plan, _dataset = build_demo_documents()
        base = FrozenSpec.from_object(base_value)
        challenger = FrozenSpec.from_object(challenger_value)
        plan_value = ExperimentPlan.seal(
            {
                "schema_version": PLAN_SCHEMA,
                "status": "FROZEN",
                "mode": "WALK_FORWARD",
                "registered_at": "2026-01-01T01:30:00Z",
                "folds": [
                    {
                        "fold_id": "wf-1",
                        "training_ends_at": "2025-12-31T23:59:59Z",
                        "evaluation_starts_at": "2026-01-02T00:00:00Z",
                        "evaluation_ends_at": "2026-01-02T00:30:00Z",
                    },
                    {
                        "fold_id": "wf-2",
                        "training_ends_at": "2026-01-02T00:30:00Z",
                        "evaluation_starts_at": "2026-01-02T00:30:01Z",
                        "evaluation_ends_at": "2026-01-02T01:00:01Z",
                    },
                ],
                "evaluator_id": "INDEX_PATH_DIAGNOSTICS_V1",
                "metric_ids": ["DECISION_AGREEMENT_RATE"],
                "promotion_gate": {
                    "min_comparable_windows": 1,
                    "max_incomparable_fraction": "1",
                    "require_actual_paths": False,
                },
            }
        )
        plan = ExperimentPlan.from_object(plan_value)

        with self.assertRaisesRegex(ValidationError, "training boundary leaks"):
            plan.validate_specs(base, challenger)

    def test_walk_forward_assigns_only_later_non_overlapping_windows(self) -> None:
        base_value, challenger_value, _plan, dataset_value = build_demo_documents()
        base = FrozenSpec.from_object(base_value)
        challenger = FrozenSpec.from_object(challenger_value)
        dataset = DecisionWindowExport.from_object(dataset_value)
        plan_value = ExperimentPlan.seal(
            {
                "schema_version": PLAN_SCHEMA,
                "status": "FROZEN",
                "mode": "WALK_FORWARD",
                "registered_at": "2026-01-01T01:30:00Z",
                "folds": [
                    {
                        "fold_id": "wf-1",
                        "training_ends_at": "2026-01-01T00:30:00Z",
                        "evaluation_starts_at": "2026-01-02T00:00:00Z",
                        "evaluation_ends_at": "2026-01-02T00:30:00Z",
                    },
                    {
                        "fold_id": "wf-2",
                        "training_ends_at": "2026-01-02T00:29:59Z",
                        "evaluation_starts_at": "2026-01-02T00:30:00Z",
                        "evaluation_ends_at": "2026-01-02T01:00:00Z",
                    },
                ],
                "evaluator_id": "INDEX_PATH_DIAGNOSTICS_V1",
                "metric_ids": ["DECISION_AGREEMENT_RATE"],
                "promotion_gate": {
                    "min_comparable_windows": 1,
                    "max_incomparable_fraction": "1",
                    "require_actual_paths": False,
                },
            }
        )
        plan = ExperimentPlan.from_object(plan_value)
        plan.validate_specs(base, challenger)

        self.assertEqual(
            [plan.fold_for(window).fold_id for window in dataset.windows],
            ["wf-1", "wf-1", "wf-2", "wf-2"],
        )

    def test_window_identity_is_external_and_versioned_export_is_sealed(self) -> None:
        _base, _challenger, _plan, dataset_value = build_demo_documents()
        dataset = DecisionWindowExport.from_object(dataset_value)
        self.assertEqual(len(dataset.windows), 4)
        self.assertTrue(dataset.export_id.startswith("sha256:"))
        self.assertTrue(
            all(window.decision_window_id.startswith("sha256:") for window in dataset.windows)
        )
        self.assertNotEqual(
            dataset.windows[0].decision_window_id,
            content_id("unrelated", {"value": 1}),
        )


if __name__ == "__main__":
    unittest.main()

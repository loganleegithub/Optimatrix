from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from optimatrix.ai_lab.canonical import JsonObject, content_id, utc_text, write_new_json
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.models import (
    EXPORT_SCHEMA,
    PLAN_SCHEMA,
    SPEC_SCHEMA,
    DecisionWindowExport,
    ExperimentPlan,
    FrozenSpec,
)
from optimatrix.ai_lab.store import AuditStore


def build_demo_documents() -> tuple[JsonObject, JsonObject, JsonObject, JsonObject]:
    base_policy_id = content_id("SyntheticExternalPolicy", {"name": "base"})
    challenger_policy_id = content_id("SyntheticExternalPolicy", {"name": "challenger"})
    trained_through = "2026-01-01T00:00:00Z"
    base = FrozenSpec.seal(
        {
            "schema_version": SPEC_SCHEMA,
            "status": "FROZEN",
            "role": "BASE",
            "version": "demo-base-v1",
            "name": "Synthetic mechanism Base",
            "frozen_at": "2026-01-01T01:00:00Z",
            "trained_through": trained_through,
            "external_policy_id": base_policy_id,
            "implementation_id": "EXTERNAL_SYNTHETIC_DECISIONS_V1",
            "limitations": ["SYNTHETIC_FIXTURE_MECHANISM_ONLY"],
        }
    )
    challenger = FrozenSpec.seal(
        {
            "schema_version": SPEC_SCHEMA,
            "status": "FROZEN",
            "role": "CHALLENGER",
            "version": "demo-challenger-v1",
            "name": "Synthetic mechanism Challenger",
            "frozen_at": "2026-01-01T01:05:00Z",
            "trained_through": trained_through,
            "external_policy_id": challenger_policy_id,
            "implementation_id": "EXTERNAL_SYNTHETIC_DECISIONS_V1",
            "limitations": ["SYNTHETIC_FIXTURE_MECHANISM_ONLY"],
        }
    )
    plan = ExperimentPlan.seal(
        {
            "schema_version": PLAN_SCHEMA,
            "status": "FROZEN",
            "mode": "CHRONOLOGICAL",
            "registered_at": "2026-01-01T01:30:00Z",
            "folds": [
                {
                    "fold_id": "forward-1",
                    "training_ends_at": "2026-01-01T00:30:00Z",
                    "evaluation_starts_at": "2026-01-02T00:00:00Z",
                    "evaluation_ends_at": "2026-01-02T01:00:00Z",
                }
            ],
            "evaluator_id": "INDEX_PATH_DIAGNOSTICS_V1",
            "metric_ids": [
                "DECISION_AGREEMENT_RATE",
                "BASE_CANDIDATE_RATE",
                "CHALLENGER_CANDIDATE_RATE",
                "CANDIDATE_COUNT_DELTA",
                "NO_TRADE_AGREEMENT_COUNT",
                "BASE_SELECTED_MEAN_TERMINAL_INDEX_CHANGE_BPS",
                "CHALLENGER_SELECTED_MEAN_TERMINAL_INDEX_CHANGE_BPS",
            ],
            "promotion_gate": {
                "min_comparable_windows": 3,
                "max_incomparable_fraction": "0.25",
                "require_actual_paths": True,
            },
        }
    )
    start = datetime(2026, 1, 2, tzinfo=UTC)
    base_results = ("ABSTAIN", "ABSTAIN", "CANDIDATE", "ABSTAIN")
    challenger_results = ("ABSTAIN", "CANDIDATE", "ABSTAIN", "ABSTAIN")
    prices = (
        ("100000", "100500", "100200"),
        ("100200", "99500", "99800"),
        ("99800", "101000", "100700"),
        ("100700", "100900", "100800"),
    )
    windows: list[JsonObject] = []
    for index in range(4):
        starts_at = start + timedelta(minutes=15 * index)
        ends_at = starts_at + timedelta(minutes=15)
        deadline = ends_at + timedelta(minutes=1)
        known_at = ends_at + timedelta(seconds=30)
        window_id = content_id(
            "SyntheticDecisionWindowV1",
            {
                "starts_at": utc_text(starts_at),
                "ends_at": utc_text(ends_at),
                "index": index,
            },
        )
        decisions = []
        for spec, policy_id, result in (
            (base, base_policy_id, base_results[index]),
            (challenger, challenger_policy_id, challenger_results[index]),
        ):
            decisions.append(
                {
                    "spec_id": spec["spec_id"],
                    "decision_policy_id": policy_id,
                    "known_at": utc_text(known_at),
                    "causal_input_ends_at": utc_text(ends_at - timedelta(seconds=1)),
                    "result": result,
                    "blockers": [] if result == "CANDIDATE" else ["SYNTHETIC_NO_OPPORTUNITY"],
                }
            )
        path_start = deadline
        path_end = deadline + timedelta(minutes=30)
        if index == 3:
            future_path: JsonObject = {
                "kind": "SUMMARY_ONLY",
                "actuality": "SYNTHETIC_FIXTURE",
                "source_id": "SYNTHETIC_SUMMARY_FIXTURE",
                "method_id": "SUMMARY_ONLY_V1",
                "starts_at": utc_text(path_start),
                "ends_at": utc_text(path_end),
                "known_at": utc_text(path_end + timedelta(seconds=1)),
                "observation_count": 3,
                "summary": {
                    "start_index_price_usd": prices[index][0],
                    "end_index_price_usd": prices[index][2],
                    "minimum_index_price_usd": prices[index][0],
                    "maximum_index_price_usd": prices[index][1],
                },
            }
        else:
            future_path = {
                "kind": "FULL_PATH",
                "actuality": "SYNTHETIC_FIXTURE",
                "source_id": "SYNTHETIC_POINT_FIXTURE",
                "method_id": "THREE_POINT_PATH_V1",
                "starts_at": utc_text(path_start),
                "ends_at": utc_text(path_end),
                "known_at": utc_text(path_end + timedelta(seconds=1)),
                "continuous": True,
                "points": [
                    {
                        "observed_at": utc_text(path_start + timedelta(minutes=15 * point_index)),
                        "known_at": utc_text(
                            path_start + timedelta(minutes=15 * point_index) + timedelta(seconds=1)
                        ),
                        "index_price_usd": price,
                    }
                    for point_index, price in enumerate(prices[index])
                ],
            }
        windows.append(
            {
                "decision_window_id": window_id,
                "market_session_id": "SYNTHETIC_SESSION_2026_01_02",
                "starts_at": utc_text(starts_at),
                "ends_at": utc_text(ends_at),
                "input_deadline": utc_text(deadline),
                "base_decision": decisions[0],
                "challenger_decision": decisions[1],
                "future_path": future_path,
            }
        )
    dataset = DecisionWindowExport.seal(
        {
            "schema_version": EXPORT_SCHEMA,
            "exported_at": "2026-01-02T02:00:00Z",
            "producer_id": "SYNTHETIC_DEMO_EXPORTER_V1",
            "source_repository_commit": "SYNTHETIC_FIXTURE_NO_REPOSITORY",
            "source_contracts": [
                "MECHANISM_FIXTURE_NOT_PRODUCTION_DECISIONWINDOW",
                "MECHANISM_FIXTURE_NOT_PRODUCTION_WINDOWOUTCOME",
            ],
            "windows": windows,
        }
    )
    return base, challenger, plan, dataset


def run_demo(output: Path) -> JsonObject:
    base_value, challenger_value, plan_value, dataset_value = build_demo_documents()
    write_new_json(output / "base-spec.json", base_value)
    write_new_json(output / "challenger-spec.json", challenger_value)
    write_new_json(output / "experiment-plan.json", plan_value)
    write_new_json(output / "decision-window-export.json", dataset_value)
    base = FrozenSpec.from_object(base_value)
    challenger = FrozenSpec.from_object(challenger_value)
    plan = ExperimentPlan.from_object(plan_value)
    store = AuditStore(output / "audit")
    registration_value, _registration_event, _appended = store.register_experiment(
        base=base,
        challenger=challenger,
        plan=plan,
        recorded_at=datetime(2026, 1, 2, 2, 4, tzinfo=UTC),
    )
    write_new_json(output / "experiment-registration.json", registration_value)
    result = ExperimentRunner().run(
        base=base,
        challenger=challenger,
        dataset=DecisionWindowExport.from_object(dataset_value),
        plan=plan,
        store=store,
        registration_id=str(registration_value["registration_id"]),
        recorded_at=datetime(2026, 1, 2, 2, 5, tzinfo=UTC),
    )
    write_new_json(output / "result-copy.json", result)
    return result

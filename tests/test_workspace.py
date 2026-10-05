"""Offline business-state checks; fixtures never stand in for live balances."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import create_app
from research import ResearchService


def task_fixture(number, *, status="completed", model="historical-model", verdict="值得继续"):
    research_id = f"{number:032x}"
    run_id = f"{number + 100:032x}"
    configuration = {
        "role": "researcher", "model": model, "reasoning_effort": "high",
        "prompt_version": "saved-prompt", "output_schema_version": "research-action-v2",
    }
    return {
        "research_id": research_id, "status": status,
        "question": "fixture original research question",
        "created_at": f"2026-09-{number:02d}T00:00:00Z",
        "updated_at": f"2026-09-{number:02d}T01:00:00Z",
        "configuration_snapshot": configuration, "schema_snapshot": {},
        "budget": {"model_calls_used": 2, "model_calls_limit": 6,
                   "backtest_creations_used": 1, "backtest_creations_limit": 2},
        "available_run_ids": [run_id, "available-but-not-read"],
        "input_references": ["call-1/input.json", "call-2/input.json"],
        "events": [], "error": None,
        "actions": [{"step": 1, "action": "read_result", "status": "done",
                     "run_id": run_id, "created_at": "2026-09-01T00:30:00Z"}],
        "evidence": [{"run_id": run_id, "accounting": {"btc_net_pnl": "0"}}],
        "final": ({
            "question": "fixture question", "hypothesis": "fixture hypothesis",
            "verdict": verdict, "conclusion": "fixture interpretation",
            "counterexamples": [], "unknowns": ["executable prices unknown"],
            "next_step": "fixture future proposal", "suggested_experiments": [],
            "claims": [{"run_id": run_id, "field": "accounting.btc_net_pnl", "text": "净模型损益为 0 BTC"}],
            "experiments": [{"run_id": run_id, "role": "fixture experiment"}],
            "comparisons": [],
        } if status == "completed" else None),
    }


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "researcher").mkdir()
        (self.root / "researcher/config.json").write_text(json.dumps({
            "role": "researcher", "model": "configured-next-model", "reasoning_effort": "high"
        }))
        (self.root / "researcher/prompt.md").write_text("fixture prompt")
        (self.root / "researcher/output.schema.json").write_text("{}")
        self.backtests = Mock()
        self.market = Mock()
        self.runner = Mock()

    def service(self, tasks):
        for task in tasks:
            directory = self.root / "local/research" / task["research_id"]
            directory.mkdir(parents=True)
            (directory / "research.json").write_text(json.dumps(task))
        return ResearchService(self.root, self.backtests, runner=self.runner,
                               availability={"ready": True, "reason": "fixture checked availability"})

    def test_missing_account_is_unknown_and_read_only_polling_preserves_history(self):
        research = self.service([task_fixture(1)])
        saved = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        previous = copy.deepcopy(research.tasks)
        client = create_app(self.market, self.backtests, research).test_client()
        with patch("app.codex_status", side_effect=AssertionError("CLI must not run")):
            for _ in range(3):
                response = client.get("/api/workspace")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                account = response.json["account"]
                self.assertEqual(account["status"], "not_connected")
                for field in ("net_equity_btc", "realized_pnl_btc", "open_risk_btc", "premium_budget_remaining_btc", "source_at"):
                    self.assertIsNone(account[field])
        self.assertEqual(research.tasks, previous)
        self.assertEqual(saved, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertEqual(self.market.mock_calls, [])
        self.assertEqual(self.backtests.mock_calls, [])
        self.assertEqual(self.runner.mock_calls, [])

    def test_active_history_identities_inputs_failure_and_budget_are_task_bound(self):
        completed = task_fixture(1)
        failed = task_fixture(2, status="submission_unknown", model="failed-task-model")
        failed["error"] = "提交结果未知；需核对，不得重发"
        active = task_fixture(3, status="paused", model="active-task-model")
        active["configuration_snapshot"]["role"] = "offline-other-role"
        research = self.service([completed, failed, active])
        research.tasks[active["research_id"]]["status"] = "model_running"
        research.active_id = active["research_id"]
        data = create_app(self.market, self.backtests, research).test_client().get("/api/workspace").json
        self.assertEqual(data["agents"]["configured"]["model"], "configured-next-model")
        self.assertEqual([a["model"] for a in data["agents"]["active"]], ["active-task-model"])
        self.assertEqual([a["model"] for a in data["agents"]["history"]], ["failed-task-model", "historical-model"])
        self.assertEqual(data["agents"]["history"][0]["failure"], failed["error"])
        agent = data["agents"]["active"][0]
        self.assertEqual(agent["role"], "offline-other-role")
        self.assertEqual(agent["agent_id"], "offline-other-role:" + active["research_id"])
        self.assertEqual(agent["budget"], active["budget"])
        self.assertEqual(agent["inputs"]["read_run_ids"], [active["actions"][0]["run_id"]])
        self.assertNotIn("available-but-not-read", agent["inputs"]["read_run_ids"])
        self.assertEqual(agent["inputs"]["references"], active["input_references"])
        self.assertEqual(agent["prompt_version"], "saved-prompt")

    def test_candidate_validation_never_creates_strategy_or_trade_approval(self):
        valid = task_fixture(1)
        gaps = task_fixture(2)
        gaps["final"]["conclusion"] = "收益为 999 BTC"  # unbound text, deliberately invalid
        research = self.service([valid, gaps])
        data = create_app(self.market, self.backtests, research).test_client().get("/api/workspace").json
        self.assertEqual(data["strategy"]["latest_candidate"]["status"], "validation_gaps")
        self.assertEqual(data["strategy"]["candidate_count"], 1)
        self.assertEqual(data["strategy"]["status"], "not_authorized")
        for field in ("version", "positions", "exit_schedule"):
            self.assertIsNone(data["strategy"][field])
        self.assertEqual(data["approvals"]["pending"], [])
        self.assertEqual(data["approvals"]["strategy_approval_status"], "requires_s4_authorization")
        self.assertEqual(data["approvals"]["research_start_endpoint"], "/api/research/start")

    def test_saved_state_failure_is_visible_and_routes_preserve_stage_pages(self):
        research = self.service([])
        research.storage_error = "fixture damaged history"
        client = create_app(self.market, self.backtests, research).test_client()
        self.assertEqual(client.get("/api/workspace").json["agents"]["storage_error"], research.storage_error)
        for url, name in (("/", "strategies.html"), ("/research", "research.html"), ("/market", "index.html"), ("/backtest", "backtest.html")):
            with client.get(url) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, (Path(__file__).parents[1] / "static" / name).read_bytes())
        with patch.object(research, "list_runs", side_effect=OSError("fixture local read failed")):
            with self.assertLogs(level="ERROR"):
                response = client.get("/api/workspace")
            self.assertEqual(response.status_code, 500)
            self.assertIn("error", response.json)
            self.assertNotIn("agents", response.json)


if __name__ == "__main__":
    unittest.main()

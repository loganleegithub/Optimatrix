"""S2 offline end-to-end checks, specified before backend implementation.

Failure inventory (all fixtures below are synthetic, never research results):
- A missing local configuration may look connected or read a real credential.
- HTTP 401, remote failure or ambiguous POST timeout may look successful.
- Retrying a timed-out POST or browser refresh may submit duplicate paid jobs.
- A backtest may block the market endpoint or disappear after process restart.
- Unreadable saved history may be silently skipped and permit duplicate jobs.
- Empty/truncated records may be labelled reconciled BTC profit.
- Requests, logs or public API responses may leak authentication material.
- A cross-origin/missing-CSRF request may submit an unintended job.
- BTC accounting may mix currencies, conceal unknown fees, deduct fees twice,
  divide by zero, lose decimal precision, or present 0.2 BTC as real funds.
- An offline check may accidentally contact a live service or launch Codex.

Evidence-driven model-ledger extension, specified before parser implementation:
- A model-valued BTC ledger may be mistaken for live Deribit fills or cash.
- A different engine/schema, strategy, hedge mode, or request may be accepted
  by a parser intended only for fixed S2 backtest_v20 BTC long-call evidence.
- A missing/truncated CSV, duplicate/extra row, mixed currency, different lot
  or leg, inconsistent quantity, or reversed timestamps may look complete.
- option_value may be mistaken for a per-contract quote instead of a total.
- Open/close fees, row PnL, daily closing values, or service KPIs may disagree
  with reconstructed proceeds minus premium minus fees without being rejected.
- USD results may be converted using the final spot instead of being rejected.
- Decimal/CSV rounding tolerance may hide a material discrepancy.
- Verified model arithmetic may erase remaining actual-contract/fill gaps.

Run with .venv/bin/python tests/s2_e2e.py. A successful run writes a small,
reproducible local/s2-e2e/evidence.json artifact. No real .env is read.
"""

from contextlib import contextmanager
import csv
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import time

import requests
from waitress import create_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from backtest import BacktestService, GreeksClient  # noqa: E402
from btc_accounting import summarize_cashflows  # noqa: E402
from market import MarketService  # noqa: E402

FIXTURE_TOKEN = "offline-fixture"
EXPERIMENT = "S2_BTC_LONG_CALL_V1"
TERMINAL = {"completed_with_gaps", "completed", "failed", "submission_unknown"}


@contextmanager
def offline_only():
    """Fail closed if any code tries external networking or a subprocess."""
    original_connect = socket.socket.connect
    original_popen = subprocess.Popen

    def local_connect(sock, address):
        assert isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}, (
            "Offline E2E attempted a non-loopback socket connection"
        )
        return original_connect(sock, address)

    def no_subprocess(*args, **kwargs):
        raise AssertionError("Offline E2E attempted a subprocess / CLI invocation")

    socket.socket.connect = local_connect
    subprocess.Popen = no_subprocess
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        subprocess.Popen = original_popen


class FixtureService:
    """Real local HTTP server with synthetic Greeks protocol responses."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.sample = None
        if scenario.startswith("model_ledger"):
            # Sanitized real historical response replayed over local HTTP; no new live call.
            self.sample = json.loads((ROOT / "docs/samples/greeks-live-s2.json").read_text())
            if scenario == "model_ledger_mixed_currency":
                self.sample["detail_rows"][-1]["numeraire"] = "USDC"
            elif scenario == "model_ledger_truncated":
                self.sample["detail_rows"] = self.sample["detail_rows"][:1]
        self.calls = []
        self.submissions = []
        self.lock = Lock()
        self.submitted_at = None
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Never emit authentication headers or complete responses.

            def respond(self, status, body):
                payload = json.dumps(body).encode()
                return self.respond_bytes(status, payload, "application/json")

            def respond_bytes(self, status, payload, content_type):
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected for the deliberately ambiguous timeout case.

            def record(self, method):
                with fixture.lock:
                    fixture.calls.append((method, self.path))

            def do_GET(self):
                self.record("GET")
                if fixture.scenario == "offline_reopen":
                    return self.respond(503, {"error": "fixture network disabled"})
                if self.path == "/api/metadata":
                    return self.respond(200, {
                        "asset_status": {"BTC": {
                            "available_start_date": "2026-01-01",
                            "available_end_date": "2026-09-01",
                        }},
                    })
                if self.path == "/api/account":
                    return self.respond(200, {"quotas": {
                        "backtests_used": 0, "backtests_per_hour": 20,
                    }})
                if self.path == "/api/backtests/fixture-task":
                    if fixture.scenario == "remote_failure":
                        return self.respond(200, {
                            "id": "fixture-task", "status": "failed",
                            "error": "synthetic remote failure",
                        })
                    if time.monotonic() - fixture.submitted_at < 0.3:
                        return self.respond(200, {"id": "fixture-task", "status": "running"})
                    if fixture.sample is not None:
                        return self.respond(200, {
                            "id": "fixture-task", "status": "completed",
                            "request": fixture.sample["request"], "kpis": fixture.sample["kpis"],
                            "artifacts": {"csv": "details.csv", "daily_csv": "daily.csv"},
                        })
                    return self.respond(200, {
                        "id": "fixture-task", "status": "completed",
                        "kpis": {"numeraire": "BTC", "total_pnl": 0.0003},
                        "artifacts": {},
                    })
                if self.path == "/api/backtests/fixture-task/report-data":
                    if fixture.sample is not None:
                        return self.respond(200, {"kpis": fixture.sample["kpis"],
                                                  "preview_rows": [], "daily_preview_rows": []})
                    return self.respond(200, {
                        "kpis": {"numeraire": "BTC", "total_pnl": 0.0003},
                        "preview_rows": [], "daily_preview_rows": [],
                    })
                if fixture.sample is not None and self.path in {
                    "/api/backtests/fixture-task/artifact/details.csv",
                    "/api/backtests/fixture-task/artifact/daily.csv",
                }:
                    key = "detail_rows" if self.path.endswith("details.csv") else "daily_rows"
                    rows = fixture.sample[key]
                    buffer = io.StringIO(newline="")
                    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
                    return self.respond_bytes(200, buffer.getvalue().encode(), "text/csv")
                return self.respond(404, {"error": "unknown fixture route"})

            def do_POST(self):
                self.record("POST")
                if self.path != "/api/backtests":
                    return self.respond(404, {"error": "unknown fixture route"})
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                with fixture.lock:
                    fixture.submissions.append(body)
                    fixture.submitted_at = time.monotonic()
                if fixture.scenario == "auth401":
                    return self.respond(401, {"error": "synthetic expired authentication"})
                if fixture.scenario == "post_timeout":
                    time.sleep(0.7)
                return self.respond(200, {"id": "fixture-task", "status": "queued"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def factory(self, token):
        assert token == FIXTURE_TOKEN, "The backend did not use this test's isolated configuration"
        return GreeksClient(token, base_url=self.url, timeout_seconds=0.15)


class NeverMarketClient:
    def get(self, *_args, **_kwargs):
        raise AssertionError("This HTTP E2E must not start a live market collector")

    def close(self):
        pass


@contextmanager
def local_app(manager):
    market = MarketService(client=NeverMarketClient())
    server = create_server(create_app(market, backtests=manager), host="127.0.0.1", port=0, threads=4)
    stopped = Event()
    server_errors = []

    def serve():
        try:
            # Close sockets on their loop thread, not while another thread is in select().
            while not stopped.is_set():
                server.asyncore.loop(timeout=0.05, map=server._map, count=1,
                                     use_poll=server.adj.asyncore_use_poll)
        except Exception as error:
            server_errors.append(type(error).__name__)
        finally:
            server.task_dispatcher.shutdown()
            server.asyncore.close_all(map=server._map)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    base = f"http://127.0.0.1:{server.effective_port}"
    try:
        yield session, base
    finally:
        session.close()
        stopped.set()
        if thread.is_alive():
            server.pull_trigger()
        thread.join(timeout=2)
        assert not thread.is_alive(), "Local HTTP test server did not stop"
        assert not server_errors, "Local HTTP test server failed"


def api(session, base):
    response = session.get(base + "/api/backtests", timeout=2)
    assert response.status_code == 200
    assert FIXTURE_TOKEN not in response.text, "The public API leaked an authentication value"
    body = response.json()
    assert {"csrf_token", "configuration", "capabilities", "experiment", "runs"} <= body.keys()
    return body


def headers(state, base):
    return {"X-CSRF-Token": state["csrf_token"], "Origin": base}


def submit(session, base, state, expected=(200, 202)):
    response = session.post(base + "/api/backtests", json={"experiment_id": EXPERIMENT},
                            headers=headers(state, base), timeout=2)
    assert response.status_code in expected, f"Unexpected submission HTTP status {response.status_code}"
    assert FIXTURE_TOKEN not in response.text
    return response.json()


def wait_terminal(session, base, run_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        state = api(session, base)
        run = next((item for item in state["runs"] if item["run_id"] == run_id), None)
        if run is not None and run["status"] in TERMINAL:
            return run
        time.sleep(0.03)
    raise AssertionError("Backtest did not reach an explicit terminal state")


def wait_ready(session, base):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = api(session, base)
        if state["capabilities"]["status"] == "ready":
            return state
        assert state["capabilities"]["status"] != "failed", "Fixture capability check failed"
        time.sleep(0.03)
    raise AssertionError("Capability verification did not reach ready")


def check_accounting():
    """Exercise the pre-specified deterministic accounting failure inventory."""
    ordinary = summarize_cashflows("0.001", "0.0015", "0.0001")
    assert Decimal(str(ordinary["btc_net_pnl"])) == Decimal("0.0004")
    assert Decimal(str(ordinary["premium_return_pct"])) == Decimal("40")
    assert Decimal(str(ordinary["hypothetical_account_return_pct"])) == Decimal("0.2")
    assert Decimal(str(ordinary["hypothetical_capital_btc"])) == Decimal("0.2")
    included = summarize_cashflows("0.001", "0.0015", "0.0001", fees_included=True)
    assert Decimal(str(included["btc_net_pnl"])) == Decimal("0.0005")
    exact = summarize_cashflows("0.00000003", "0.00000005", "0.00000001")
    assert Decimal(str(exact["btc_net_pnl"])) == Decimal("0.00000001")
    for premium, exit_value, fee in [
        ("0.001", "0.0015", None), ("0", "0.0015", "0.0001"),
        ("-0.001", "0.0015", "0.0001"), ("NaN", "0.0015", "0.0001"),
        ("0.001", "Infinity", "0.0001"), ("0.001", "0.0015", "-0.0001"),
    ]:
        try:
            summarize_cashflows(premium, exit_value, fee)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("BTC calculator accepted unknown/invalid cashflows")
    return {
        "name": "btc_decimal_cashflows", "passed": True,
        "synthetic_example": {"premium_btc": "0.001", "exit_btc": "0.0015",
                              "fees_btc": "0.0001", "net_btc": "0.0004",
                              "premium_return_pct": "40", "hypothetical_account_return_pct": "0.2"},
        "checks": ["decimal_precision", "fees_included_no_double_deduction",
                   "unknown_fees_rejected", "nonfinite_negative_zero_input_rejected"],
    }


def check_unconfigured():
    with TemporaryDirectory(prefix="optimatrix-s2-missing-") as directory:
        manager = BacktestService(Path(directory), poll_seconds=0.05)
        try:
            with local_app(manager) as (session, base):
                state = api(session, base)
                assert state["configuration"]["configured"] is False
                assert state["runs"] == []
                response = session.post(base + "/api/backtests", json={"experiment_id": EXPERIMENT},
                                        headers=headers(state, base), timeout=2)
                assert response.status_code in {400, 409, 503}
                assert response.json().get("error"), "Missing configuration must have a visible reason"
        finally:
            manager.stop()
    return {"name": "missing_configuration", "passed": True}


def check_corrupt_history():
    with TemporaryDirectory(prefix="optimatrix-s2-corrupt-") as directory, FixtureService("success_with_gaps") as fixture:
        root = Path(directory)
        (root / ".env").write_text("GREEKS_LIVE_AUTH_TOKEN=" + FIXTURE_TOKEN + "\n", encoding="utf-8")
        history = root / "local" / "backtests" / "corrupted-run" / "run.json"
        history.parent.mkdir(parents=True)
        history.write_text('{"run_id":"interrupted-write",', encoding="utf-8")
        manager = BacktestService(root, client_factory=fixture.factory, poll_seconds=0.05)
        try:
            with local_app(manager) as (session, base):
                state = api(session, base)
                assert state.get("storage_error"), "Unreadable history must be visible"
                checked = session.post(base + "/api/backtests/check-connection", json={},
                                       headers=headers(state, base), timeout=2)
                assert checked.status_code == 200
                state = wait_ready(session, base)
                response = session.post(base + "/api/backtests", json={"experiment_id": EXPERIMENT},
                                        headers=headers(state, base), timeout=2)
                assert response.status_code == 409
                assert response.json().get("error")
                assert fixture.submissions == [], "Corrupted saved history bypassed submission deduplication"
                assert history.read_text() == '{"run_id":"interrupted-write",'
        finally:
            manager.stop()
    return {"name": "corrupt_saved_history_blocks_submission", "passed": True,
            "remote_submissions": 0, "corrupt_history_preserved": True}


def check_scenario(scenario):
    with TemporaryDirectory(prefix="optimatrix-s2-run-") as directory, FixtureService(scenario) as fixture:
        root = Path(directory)
        (root / ".env").write_text("GREEKS_LIVE_AUTH_TOKEN=" + FIXTURE_TOKEN + "\n", encoding="utf-8")
        manager = BacktestService(root, client_factory=fixture.factory, poll_seconds=0.05)
        try:
            with local_app(manager) as (session, base):
                state = api(session, base)
                assert state["configuration"]["configured"] is True
                for bad_headers in [{"Origin": base},
                                    {"X-CSRF-Token": state["csrf_token"], "Origin": "https://example.invalid"}]:
                    rejected = session.post(base + "/api/backtests", json={"experiment_id": EXPERIMENT},
                                            headers=bad_headers, timeout=2)
                    assert rejected.status_code in {400, 403}
                assert fixture.submissions == [], "Rejected POST reached the remote service"
                checked = session.post(base + "/api/backtests/check-connection", json={},
                                       headers=headers(state, base), timeout=2)
                assert checked.status_code == 200
                state = wait_ready(session, base)
                submitted = submit(session, base, state, expected=(202,))
                run_id = submitted["run_id"]
                assert run_id and run_id != "fixture-task", "A separate local run_id is required"
                repeated = submit(session, base, state)
                assert repeated["run_id"] == run_id
                market_start = time.monotonic()
                market_response = session.get(base + "/api/state", timeout=1)
                assert market_response.status_code == 200
                market_elapsed = time.monotonic() - market_start
                assert market_elapsed < 0.5, "Backtest work blocked the public market endpoint"
                for _ in range(3):
                    assert api(session, base)["runs"]
                run = wait_terminal(session, base, run_id)
                assert len(fixture.submissions) == 1, "Repeated/refresh requests submitted duplicate remote jobs"
                expected_status = "completed_with_gaps" if scenario.startswith("model_ledger") else {
                    "success_with_gaps": "completed_with_gaps", "auth401": "failed",
                    "remote_failure": "failed", "post_timeout": "submission_unknown",
                }[scenario]
                assert run["status"] == expected_status, f"Expected {expected_status}, got {run['status']}"
                if scenario == "success_with_gaps":
                    analysis = run["analysis"]
                    assert analysis["btc_net_pnl"] is None
                    assert analysis["reported_pnl"] is not None
                    assert "0.0003" in json.dumps(analysis["reported_pnl"])
                    assert analysis.get("gaps"), "Insufficient records need explicit missing evidence"
                elif scenario.startswith("model_ledger"):
                    analysis = run["analysis"]
                    assert analysis.get("gaps"), "Model arithmetic must retain actual-contract and execution limits"
                    assert "模型" in analysis["price_source"]
                    if scenario == "model_ledger_verified":
                        assert analysis["status"] == "model_ledger_verified", analysis.get("gaps")
                        assert analysis["model_ledger_verified"] is True
                        for field, expected in {
                            "premium_paid_btc": "0.00019309228337764038",
                            "exit_income_btc": "0.0002615305630156567",
                            "fees_btc": "0.000002",
                            "btc_net_pnl": "0.00006643827963801632",
                            "hypothetical_capital_btc": "0.2",
                            "hypothetical_account_return_pct": "0.03321913981900816",
                        }.items():
                            assert Decimal(str(analysis[field])) == Decimal(expected), field
                        assert abs(Decimal(str(analysis["premium_return_pct"])) - Decimal("34.4075270517567")) < Decimal("1e-12")
                        assert analysis["capital_is_hypothetical"] is True
                        assert analysis.get("audit"), "Verified model cashflows need inspectable reconciliation evidence"
                        assert len(analysis["rows"]) == 4, "Premium, entry fee, exit proceeds and exit fee need separate rows"
                    else:
                        assert analysis["btc_net_pnl"] is None
                        assert not analysis.get("model_ledger_verified")
                        assert analysis["status"] != "model_ledger_verified"
                else:
                    assert run.get("error"), "A failed/unknown submission needs a visible explanation"
        finally:
            manager.stop()
        reopens = scenario in {"success_with_gaps", "model_ledger_verified"}
        if reopens:
            assert any(root.rglob("*.json")), "No run/result was persisted to disk"
            fixture.scenario = "offline_reopen"
            before_reopen = len(fixture.calls)
            reopened = BacktestService(root, client_factory=fixture.factory, poll_seconds=0.05)
            try:
                with local_app(reopened) as (session, base):
                    restored_state = api(session, base)
                    restored = next(item for item in restored_state["runs"] if item["run_id"] == run_id)
                    assert restored["status"] == "completed_with_gaps"
                    assert restored["analysis"] == run["analysis"]
                    assert len(fixture.calls) == before_reopen, "Reopening saved history called the remote service"
            finally:
                reopened.stop()
        return {
            "name": scenario, "passed": True, "remote_submissions": len(fixture.submissions),
            "terminal_status": run["status"], "market_endpoint_responsive": True,
            "csrf_and_origin_rejection": True,
            "saved_result_reopened_without_network": reopens,
            "fixture_source": "sanitized real service excerpt replay" if fixture.sample is not None else "synthetic fixture",
        }


def main():
    with offline_only():
        checks = [check_accounting(), check_unconfigured()]
        checks.extend(check_scenario(name) for name in (
            "success_with_gaps", "auth401", "remote_failure", "post_timeout",
            "model_ledger_verified", "model_ledger_mixed_currency", "model_ledger_truncated",
        ))
        checks.append(check_corrupt_history())
    evidence = {
        "schema": "optimatrix-s2-offline-e2e-v1",
        "classification": "SYNTHETIC_OFFLINE_TEST_NOT_A_BACKTEST_RESULT",
        "command": ".venv/bin/python tests/s2_e2e.py",
        "external_network_allowed": False, "real_env_read": False,
        "real_accounts_or_cli_used": False, "checks": checks,
    }
    output = ROOT / "local" / "s2-e2e" / "evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(checks)} offline S2 scenarios; synthetic evidence: {output}")


if __name__ == "__main__":
    main()

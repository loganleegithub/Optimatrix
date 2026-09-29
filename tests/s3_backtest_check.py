"""Small offline checks for S3 submission identity and GET-only recovery.

Failures covered: arbitrary parameter escape, S2 swallowing new experiments,
logical-step mutation, ambiguous submit replay, known-ID download retry,
restart lying about an active worker, and explicit linked local-failure retry.
The fixture service is synthetic; its outputs are never research evidence.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest import BacktestError, BacktestService, EXPERIMENT_ID, save_json, validate_experiment

PARAMS = dict(start_date="2026-06-01", end_date="2026-06-02", session_bucket="09:00:00",
              entry_weekdays=[0], option_type="put", delta=0.4, expiry=14, quantity=0.01,
              option_transaction_cost_bp=1)

class FixtureClient:
    def __init__(self):
        self.calls = []
        self.fail_report = False
        self.ambiguous = False
        self.fail_verify = False
    def close(self): pass
    def request(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path))
        if path == "/api/metadata":
            if self.fail_verify: raise BacktestError("fixture unavailable before POST")
            return {"asset_status": {"BTC": {"available_start_date": "2026-01-01", "available_end_date": "2026-09-28"}}}
        if path == "/api/account": return {"quotas": {"backtests_per_hour": 20, "backtests_used": 0}}
        if method == "POST":
            if self.ambiguous: raise BacktestError("fixture unknown", uncertain=True)
            return {"id": "fixture-task", "status": "completed"}
        if path.endswith("/report-data"):
            if self.fail_report: raise BacktestError("fixture download failed")
            return {"kpis": {"numeraire": "BTC", "total_pnl": 0.0003}, "artifacts": {}}
        return {"id": "fixture-task", "status": "completed", "artifacts": {}}

def wait(service):
    deadline=time.monotonic()+3
    while service.active and time.monotonic()<deadline: time.sleep(.01)
    assert not service.active

def expect_error(fn):
    try: fn()
    except BacktestError: return
    raise AssertionError("Unsafe action accepted")

def main():
    checked=[]
    for key,value in [("url","https://evil.invalid"),("quantity",-1),("delta",float("nan")),("expiry",True),
                      ("option_type","short"),("entry_weekdays",[0,0]),("session_bucket","25:00:00")]:
        p=copy.deepcopy(PARAMS);p[key]=value;expect_error(lambda:validate_experiment(p))
    checked.append("parameter_allowlist")
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);(root/".env").write_text("GREEKS_LIVE_AUTH_TOKEN=offline-fixture\n")
        client=FixtureClient();service=BacktestService(root,client_factory=lambda _:client,poll_seconds=.01)
        service.check_connection();wait(service)
        legacy=service.submit(EXPERIMENT_ID);wait(service)
        client.fail_report=True
        reservations=[]
        created=service.submit_experiment(PARAMS,logical_id="research1:step1",hypothesis="fixture hypothesis",comparison_plan="fixture compare",before_create=lambda:reservations.append("reserved"))
        assert reservations==["reserved"]
        wait(service);run=service.get_run(created["run_id"])
        assert run["run_id"]!=legacy and run["status"]=="retrieval_failed" and run["can_resume"]
        before=len([x for x in client.calls if x[0]=="POST"])
        repeated=service.submit_experiment(PARAMS,logical_id="research1:step1",before_create=lambda:reservations.append("duplicate"))
        assert reservations==["reserved"]
        assert repeated["reused"] and not repeated["created_attempt"]
        changed={**PARAMS,"delta":.3}
        expect_error(lambda:service.submit_experiment(changed,logical_id="research1:step1"))
        client.fail_report=False;service.resume(run["run_id"]);wait(service)
        assert len([x for x in client.calls if x[0]=="POST"])==before
        assert service.get_run(run["run_id"])["status"]=="completed_with_gaps"
        checked.extend(["distinct_from_S2","logical_step_dedup","logical_step_parameter_immutability","resume_GET_only","reserve_budget_after_dedup"])
        same=service.submit_experiment(PARAMS,logical_id="research2:step0",before_create=lambda:reservations.append("duplicate"))
        assert same["reused"] and reservations==["reserved"]
        expect_error(lambda:service.submit_experiment(changed,logical_id="research2:step0"))
        checked.append("semantic_reuse_alias_is_immutable")
        client.ambiguous=True
        unknown=service.submit_experiment(changed,logical_id="research1:step2");wait(service)
        assert service.get_run(unknown["run_id"])["status"]=="submission_unknown"
        expect_error(lambda:service.resume(unknown["run_id"]))
        expect_error(lambda:service.retry(unknown["run_id"],logical_id="research1:retry"))
        assert service.submit_experiment(changed,logical_id="research2:step1")["reused"]
        checked.append("unknown_not_resent")
        client.ambiguous=False;client.fail_verify=True
        localfail=service.submit_experiment({**PARAMS,"delta":.2},logical_id="research3:step1");wait(service)
        failed=service.get_run(localfail["run_id"])
        assert failed["status"]=="not_submitted" and failed["can_retry"]
        client.fail_verify=False
        retried=service.retry(failed["run_id"],logical_id="research3:retry1");wait(service)
        assert service.get_run(retried["run_id"])["previous_run_id"]==failed["run_id"]
        assert len(service.runs)==5
        checked.append("linked_retry_keeps_failure")
        service.stop()
        record=service.get_run(retried["run_id"]);record["status"]="running";save_json(service.storage/record["run_id"]/"run.json",record)
        restarted=BacktestService(root,client_factory=lambda _:client)
        assert restarted.get_run(record["run_id"])["status"]=="paused"
        checked.append("restart_requires_explicit_resume")
        record=restarted.get_run(unknown["run_id"]);record["status"]="submitting";save_json(restarted.storage/record["run_id"]/"run.json",record)
        second_restart=BacktestService(root,client_factory=lambda _:client)
        assert second_restart.get_run(record["run_id"])["status"]=="submission_unknown"
        checked.append("crash_during_submit_stays_unknown")
        second_restart.stop()
        restarted.stop()
    out={"kind":"offline_synthetic_check","passed":True,"checks":checked,"live_model_calls":0,"live_backtest_creations":0}
    save_json(ROOT/"local/s3-backtest-check/evidence.json",out)
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":main()

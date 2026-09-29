"""Offline S3 accounting checks; synthetic rows are never live evidence.

Failure cases fixed before extending the calculator: quantity or fees counted
twice; a mark treated as cash; cross-lot joins; repeated/omitted events; open
positions called closed; a missing daily row treated as zero; a false fee
comparison disconnected from the verified run. Also replay the saved S2 run
when available. This script emits a repeatable, credential-free check artifact.
"""

import copy
import csv
import json
from decimal import Decimal
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from btc_accounting import analyze_report, compare_fee_scenario  # noqa: E402


def fixture():
    common = {
        "asset": "BTC", "numeraire": "BTC", "calculation_version": "backtest_v20",
        "mode": "reopen", "hedge_mode": "none", "side": "long", "option_type": "put",
        "delta_target": "0.3", "DTE": "14", "close_dte": "0", "quantity": "0.1",
        "source_kind": "surface", "surface_tenor_coverage": "covered",
        "market_data_status": "scheduled", "interp_mode": "time_interp",
        "valuation_complete": "True", "result_complete": "True", "valuation_status": "complete",
        "daily_return_valid": "True", "forward": "100000", "strike": "90000",
        "skip_reason": "", "entry_failure_reason": "", "hedge_pnl": "0",
        "hedge_transaction_cost": "0", "hedge_position": "0", "hedge_rebalances": "0",
        "leg_id": "L1",
    }
    rows = []
    for lot, start, end, values in [("R1", 1, 3, ["0.003", "0.004", "0.005"]),
                                     ("R2", 3, 4, ["0.006", "0.004"])]:
        previous = None
        for i, value in enumerate(values):
            day = start + i
            event = "open" if i == 0 else "close" if day == end else "mark"
            fee = Decimal("0.00001") if event != "mark" else Decimal(0)
            pnl = -fee if event == "open" else Decimal(value) - Decimal(previous["option_value"]) - fee
            row = {**common, "lot_id": lot, "event": event,
                   "date": f"2026-05-{day:02}", "event_time": f"2026-05-{day:02}T09:00:00Z",
                   "open_time": f"2026-05-{start:02}T09:00:00Z",
                   "expiry_time": f"2026-05-{start+14:02}T09:00:00Z",
                   "surface_source_time": f"2026-05-{day:02}T09:00:00Z",
                   "position_closed": "True" if event == "close" else "False",
                   "previous_mark_time": previous["event_time"] if previous else "",
                   "previous_option_value": previous["option_value"] if previous else "",
                   "option_value": value, "option_transaction_cost": str(fee), "transaction_cost": str(fee),
                   "option_pnl": str(pnl), "total_pnl": str(pnl)}
            rows.append(row)
            previous = row
    daily = []
    cumulative = Decimal(0)
    for day in range(1, 5):
        date = f"2026-05-{day:02}"
        selected = [r for r in rows if r["date"] == date]
        pnl = sum(Decimal(r["total_pnl"]) for r in selected)
        fees = sum(Decimal(r["transaction_cost"]) for r in selected)
        cumulative += pnl
        daily.append({**common, "date": date, "total_pnl": str(pnl), "option_pnl": str(pnl),
                      "transaction_cost": str(fees), "option_transaction_cost": str(fees),
                      "cum_pnl": str(cumulative), "active_lots": "0" if day == 4 else "1"})
        for row in selected:
            row["cum_pnl"] = str(cumulative)
    report = {"request": {"asset": "BTC", "numeraire": "BTC", "mode": "reopen", "hedge_mode": "none",
                           "start_date": "2026-05-01", "end_date": "2026-05-04", "session_bucket": "09:00:00",
                           "entry_weekdays": list(range(7)), "option_transaction_cost_bp": 1,
                           "hedge_transaction_cost_bp": 0, "legs": [{"side": "long", "option_type": "put",
                             "delta": 0.3, "expiry": 14, "close_dte": 0, "quantity": 0.1}]},
              "kpis": {"calculation_version": "backtest_v20", "asset": "BTC", "numeraire": "BTC",
                        "result_complete": True, "daily_statistics_complete": True, "unresolved_lots": 0,
                        "valid_rows": len(rows), "skip_total": 0, "missing_daily_observations": 0,
                        "total_pnl": "-0.00004", "option_pnl": "-0.00004", "hedge_pnl": 0,
                        "hedge_transaction_cost": 0, "transaction_cost": "0.00004", "option_transaction_cost": "0.00004"}}
    return report, rows, daily


def evaluate(directory, report, rows, daily):
    files = {}
    for name, values in [("csv", rows), ("daily_csv", daily)]:
        path = directory / (name + ".csv")
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
        files[name] = path
    return analyze_report(report, files)


def main():
    checks = []
    with TemporaryDirectory(prefix="optimatrix-s3-accounting-") as directory:
        path = Path(directory)
        report, rows, daily = fixture()
        verified = evaluate(path, report, rows, daily)
        assert verified["model_ledger_verified"], verified["gaps"]
        assert Decimal(verified["premium_paid_btc"]) == Decimal("0.009")
        assert Decimal(verified["exit_income_btc"]) == Decimal("0.009")
        assert Decimal(verified["btc_net_pnl"]) == Decimal("-0.00004")
        comparison = compare_fee_scenario(verified, 5, run_id="offline-fixture")
        assert Decimal(comparison["higher_net_btc"]) == Decimal("-0.0002")
        assert Decimal(comparison["incremental_cost_btc"]) == Decimal("0.00016")
        assert comparison["gross_profit_consumed_base_pct"] is None
        checks.extend(["multi_lot_put_dynamic_parameters", "mark_is_not_cash", "fee_comparison_no_remote_call"])
        # A planned non-entry day is not missing market data. Keep this
        # regression self-contained even when ignored live artifacts are absent.
        filtered_report, filtered_daily = copy.deepcopy(report), copy.deepcopy(daily)
        filtered_report["request"].update(end_date="2026-05-06", entry_weekdays=[0, 2, 3, 4, 5, 6])
        filtered_report["kpis"]["skip_total"] = 1
        filtered_report["skip_counts"] = {"entry_weekday_filtered": 1}
        for row in filtered_daily:
            row.update(entry_data_status="scheduled", valid_events="1")
        for day, entry in [(5, "filtered"), (6, "")]:
            flat = copy.deepcopy(filtered_daily[-1])
            flat.update(date=f"2026-05-{day:02}", entry_data_status=entry, valid_events="0",
                        active_lots="0", valuation_status="flat", total_pnl="0", option_pnl="0",
                        transaction_cost="0", option_transaction_cost="0")
            filtered_daily.append(flat)
        filtered = evaluate(path, filtered_report, rows, filtered_daily)
        assert filtered["model_ledger_verified"], filtered["gaps"]
        assert filtered["audit"]["planned_weekday_filtered_days"] == 1
        false_filter_report = copy.deepcopy(filtered_report)
        false_filter_report["skip_counts"] = {"missing_surface": 1}
        assert not evaluate(path, false_filter_report, rows, filtered_daily)["model_ledger_verified"]
        checks.append("planned_weekday_filter_allowed_but_missing_surface_rejected")
        mutations = {
            "duplicate_event": lambda r, d: r.append(copy.deepcopy(r[-1])),
            "cross_lot_previous_value": lambda r, d: r[-1].update(previous_option_value="0.003"),
            "quantity_drift": lambda r, d: r[-1].update(quantity="0.2"),
            "mark_charged_fee": lambda r, d: r[1].update(option_transaction_cost="0.00001"),
            "unclosed_position": lambda r, d: r[-1].update(event="mark", position_closed="False"),
            "missing_daily_row": lambda r, d: d.pop(1),
            "missing_event": lambda r, d: r.pop(1),
        }
        for name, mutate in mutations.items():
            mutated_rows, mutated_daily = copy.deepcopy(rows), copy.deepcopy(daily)
            mutate(mutated_rows, mutated_daily)
            result = evaluate(path, report, mutated_rows, mutated_daily)
            assert not result["model_ledger_verified"], name
            assert result["btc_net_pnl"] is None, name
            checks.append(name)
        for invalid in [True, "nan", -1, 0, 101]:
            try:
                compare_fee_scenario(verified, invalid)
            except (ValueError, TypeError):
                pass
            else:
                raise AssertionError("Invalid fee assumption accepted")
        checks.append("invalid_fee_rejected")
    s2 = ROOT / "local/backtests/2016fbaa90a241b89f5569e18d06c041"
    if (s2 / "report.raw.json").exists():
        merged = {**json.loads((s2 / "status.raw.json").read_text()), **json.loads((s2 / "report.raw.json").read_text())}
        result = analyze_report(merged, {"csv": s2 / "details.csv", "daily_csv": s2 / "daily.csv"})
        assert result["model_ledger_verified"], result["gaps"]
        assert Decimal(result["btc_net_pnl"]) == Decimal("0.00006643827963801632")
        checks.append("saved_real_s2_replay")
    s3 = ROOT / "local/backtests/47244e3c2dc44c5981cb145708c53e5d"
    if (s3 / "report.raw.json").exists():
        merged = {**json.loads((s3 / "status.raw.json").read_text()), **json.loads((s3 / "report.raw.json").read_text())}
        with (s3 / "details.csv").open() as stream:
            details = list(csv.DictReader(stream))
        with (s3 / "daily.csv").open() as stream:
            daily = list(csv.DictReader(stream))
        with TemporaryDirectory(prefix="optimatrix-s3-weekdays-") as directory:
            result = evaluate(Path(directory), merged, details, daily)
            assert result["model_ledger_verified"], result["gaps"]
            assert result["audit"]["lot_count"] == 20
            assert result["audit"]["planned_weekday_filtered_days"] == 7
            assert abs(Decimal(result["btc_net_pnl"]) - Decimal("0.00002482659608703262")) < Decimal("1e-15")
            checks.append("saved_real_s3_planned_weekday_filters_and_flat_days")
            bad_report = copy.deepcopy(merged)
            bad_report["skip_counts"] = {"missing_surface": 7}
            assert not evaluate(Path(directory), bad_report, details, daily)["model_ledger_verified"]
            bad_report = copy.deepcopy(merged)
            bad_report["kpis"]["missing_daily_observations"] = 1
            assert not evaluate(Path(directory), bad_report, details, daily)["model_ledger_verified"]
            bad_daily = copy.deepcopy(daily)
            next(row for row in bad_daily if row["valuation_status"] == "flat")["active_lots"] = "1"
            assert not evaluate(Path(directory), merged, details, bad_daily)["model_ledger_verified"]
            checks.append("real_s3_missing_data_and_false_flat_rejected")
    artifact = ROOT / "local/s3-accounting-check.json"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text(json.dumps({"passed": True, "offline": True, "checks": checks}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(checks), "artifact": str(artifact)}))


if __name__ == "__main__":
    main()

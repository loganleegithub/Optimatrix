from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

import radar_runtime.workbench as workbench_module
from radar_runtime.workbench_frontend import CSS, HTML, JS

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_assets_are_loaded_outside_business_projection_module() -> None:
    source = inspect.getsource(workbench_module)

    assert "from radar_runtime.workbench_frontend import CSS as CSS" in source
    assert "from radar_runtime.workbench_frontend import HTML as HTML" in source
    assert "from radar_runtime.workbench_frontend import JS as JS" in source
    assert 'HTML = """<!doctype html>' not in source
    assert workbench_module.HTML == HTML
    assert workbench_module.CSS == CSS
    assert workbench_module.JS == JS


def test_frontend_v1_preserves_read_only_semantics_and_truth_boundaries() -> None:
    combined = f"{HTML}\n{JS}"

    assert "Radar 关注列表\uff08非 Candidate\uff09" in HTML
    assert "Attention ≠ Radar clue ≠ Candidate ≠ Case ≠ Outcome" in JS
    assert "实际账户保证金" in JS
    assert "UNKNOWN — 未接入私有账户数据" in JS
    assert "非 Candidate 的 Case 不是交易" in HTML
    assert "生命周期终结不等于经济结果已知" in HTML
    assert "模拟入场, 不是订单或成交" in HTML

    assert "WebSocket" not in combined
    assert "deribit.com" not in combined.lower()
    assert "<button" not in HTML.lower()
    assert "<form" not in HTML.lower()
    assert "/private" not in combined
    assert "submit_order" not in JS.lower()
    assert "set_policy" not in JS.lower()
    assert "const valuationUnit = product.valuation_currency" in JS
    assert "const nativeUnit = product.native_premium_currency" in JS
    assert "boundary_valued_net_pnl_usd" in JS


def test_frontend_v1_aggregates_research_and_outcome_rows_by_default() -> None:
    assert "查看 ${panel.rows.length} 条研究 Case 明细\uff08默认折叠\uff09" in JS
    assert "查看 ${rows.length} 条 Outcome 明细\uff08默认折叠\uff09" in JS
    assert '<details class="detail-group"' in JS
    assert "funnel-ladder" in CSS
    assert "@media print" in CSS
    assert "captureOpenDetailKeys" in JS
    assert "restoreOpenDetailKeys" in JS
    assert 'data-detail-key="research-case-rows"' in JS


def test_frontend_v1_uses_product_owned_outcome_valuation_and_trader_labels() -> None:
    test_js = JS.replace(
        "refresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchTest = { outcomeValuationCellValue, reasonText, "
        "caseStateText, enrollmentText, runCaseOutcomeSummary };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
globalThis.document = {{getElementById() {{ return {{}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__workbenchTest;

assert.equal(api.outcomeValuationCellValue({{
  public_quote_net_pnl_valuation: null,
  boundary_valued_net_pnl_usd: '123.456'
}}, {{name: 'inverse-btc'}}), '123.46');
assert.equal(api.outcomeValuationCellValue({{
  public_quote_net_pnl_valuation: '-3.5',
  boundary_valued_net_pnl_usd: null
}}, {{name: 'linear-btc-usdc'}}), '-3.5');
assert.equal(api.reasonText('CONTROL_OPENED'), '无交易研究对照 Case 已建立');
assert.equal(api.reasonText('UNKNOWN_CONSUMED'), '刷新事实 UNKNOWN, 本次选择已消费');
assert.equal(api.caseStateText('PENDING_OUTCOME'), '等待严格未来 Outcome');
assert.equal(api.enrollmentText('SELECTED_UNDERWRITING_DECISION_CONTROL'),
  '无交易研究对照 Case');
assert.equal(api.runCaseOutcomeSummary({{
  funnel: {{
    stages: [
      {{stage: 'SHADOW_CASE_OPENED', observed_count: 0}},
      {{stage: 'SHADOW_CASE_OUTCOME', observed_count: 0}}
    ],
    decision_control_research: {{pending_counts: {{case_without_outcome: 35}}}}
  }}
}}), '规范 0 Case / 0 Outcome · 研究待未来事实 35');
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_frontend_v1_adds_keyboard_and_table_accessibility_hooks() -> None:
    assert 'class="skip-link"' in HTML
    assert 'id="main-content"' in HTML
    assert 'aria-controls="decision-view"' in HTML
    assert 'scope="col"' in JS
    assert ":focus-visible" in CSS


def test_package_data_declares_static_assets() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"workbench_static/*.html"' in pyproject
    assert '"workbench_static/*.css"' in pyproject
    assert '"workbench_static/*.js"' in pyproject

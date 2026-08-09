from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import radar_runtime.workbench as workbench_module
from options_domain import INVERSE_BTC
from radar_runtime.workbench_frontend import CSS, HTML, JS
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)

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


def test_opportunity_blotter_exposes_the_roadmap_without_fabricating_future_truth() -> None:
    combined = f"{HTML}\n{JS}"

    for identity in (
        "INVERSE_BTC_SHORT_VOL_V1",
        "INVERSE_BTC_LONG_GAMMA_V1",
        "INVERSE_ETH_SHORT_VOL_V1",
        "INVERSE_ETH_LONG_GAMMA_V1",
    ):
        assert identity in JS

    assert "未接入不等于当前机会为零" in HTML
    assert "不可解释为当前 0 个机会" in JS
    assert "尚未接入 · 无独立队列快照" in JS
    assert "不报告业务零值" in JS
    assert "无 Long Gamma 决策契约" in JS
    assert "无 ETH 产品快照" in JS
    assert "身份不匹配" in JS
    assert "拒绝展示" in JS
    assert "Radar 线索与已结算结构分成两类队列" not in combined
    assert "避免浏览器误拼不同 Episode" in JS
    assert "当前 API 未提供 Radar 与 Underwriting 共用的 Episode identity" in JS


def test_opportunity_blotter_preserves_public_only_read_only_boundaries() -> None:
    combined = f"{HTML}\n{JS}"

    assert "PUBLIC SHADOW · READ ONLY · 非订单/成交" in HTML
    assert "公共行情反事实\uff0c不是订单、成交、实际持仓、流动性预留或账户保证金" in HTML
    assert "不是到期 BTC 负债、精确最大损失或账户保证金" in JS
    assert "不是实际账户 PnL" in JS
    assert "actual_account_margin_availability !== 'UNKNOWN'" in JS
    assert "actual_account_margin_reason !== 'ACCOUNT_MARGIN_UNKNOWN'" in JS
    assert "const nativeUnit = documentValue.product.native_premium_currency" in JS
    assert "const valuationUnit = documentValue.product.valuation_currency" in JS

    assert "WebSocket" not in combined
    assert "deribit.com" not in combined.lower()
    assert "<form" not in HTML.lower()
    assert "/private" not in combined
    assert "submit_order" not in JS.lower()
    assert "set_policy" not in JS.lower()
    assert "fetch('/api/workbench/current'" in JS
    assert all('type="button"' in match.group(0) for match in re.finditer(r"<button[^>]*>", HTML))


def test_opportunity_blotter_uses_fixed_detail_and_responsive_dismissible_drawer() -> None:
    assert "grid-template-columns: 238px minmax(700px, 0.85fr) minmax(534px, 1.15fr)" in CSS
    assert "@media (max-width: 1471px)" in CSS
    assert "width: min(648px, calc(100vw - 240px))" in CSS
    assert "width: min(648px, calc(100vw - 24px))" in CSS
    assert "body.detail-open .detail-panel" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "Esc 关闭" in HTML
    assert "DRAWER_MEDIA_QUERY = '(max-width: 1471px)'" in JS
    assert "panel.setAttribute('aria-modal', 'true')" in JS
    assert "setElementInert('.topbar', open)" in JS
    assert "setElementInert('.queue-workspace', open)" in JS
    assert "setElementInert('#detail-panel', drawer && !open)" in JS
    assert 'aria-hidden="true" inert' in HTML
    assert JS.index("updateResponsiveDetailState();\nrefresh();") < JS.index(
        "setInterval(refresh, 2000);"
    )
    assert "event.key === 'Escape'" in JS
    assert "target.closest('#detail-close') || target.closest('#detail-scrim')" in JS
    assert "lastDetailTriggerId" in JS
    assert "trigger.focus()" in JS
    assert "trapDrawerFocus" in JS


def test_opportunity_blotter_supports_explicit_day_and_night_themes() -> None:
    assert '<html lang="zh-CN" data-theme="light">' in HTML
    assert '<meta name="color-scheme" content="light dark">' in HTML
    assert 'class="theme-switch"' in HTML
    assert 'data-theme-option="light"' in HTML
    assert 'data-theme-option="dark"' in HTML
    assert 'html[data-theme="light"]' in CSS
    assert "function setTheme(theme)" in JS
    assert "storage.setItem(THEME_STORAGE_KEY, theme)" in JS

    test_js = JS.replace(
        "syncThemeControl();\nupdateResponsiveDetailState();\nrefresh();\nsetInterval(refresh, 2000);",
        "globalThis.__themeTest = { setTheme, syncThemeControl, restoreThemePreference };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
const light = {{dataset: {{themeOption: 'light'}}, attributes: {{}},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }} }};
const dark = {{dataset: {{themeOption: 'dark'}}, attributes: {{}},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }} }};
const saved = [];
globalThis.localStorage = {{
  getItem() {{ return null; }},
  setItem(key, value) {{ saved.push([key, value]); }}
}};
globalThis.document = {{
  documentElement: {{dataset: {{theme: 'light'}}}},
  querySelectorAll(selector) {{ return selector === '[data-theme-option]' ? [light, dark] : []; }},
  addEventListener() {{}},
  getElementById() {{ return null; }}
}};
globalThis.window = {{matchMedia() {{ return {{matches: false, addEventListener() {{}}}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__themeTest;
api.syncThemeControl();
assert.equal(light.attributes['aria-pressed'], 'true');
assert.equal(dark.attributes['aria-pressed'], 'false');
api.setTheme('dark');
assert.equal(document.documentElement.dataset.theme, 'dark');
assert.equal(dark.attributes['aria-pressed'], 'true');
assert.deepEqual(saved.at(-1), ['optimatrix-workbench-theme', 'dark']);
api.setTheme('unsupported');
assert.equal(document.documentElement.dataset.theme, 'dark');

globalThis.localStorage = {{
  getItem() {{ return 'light'; }},
  setItem(key, value) {{ saved.push([key, value]); }}
}};
api.restoreThemePreference();
assert.equal(document.documentElement.dataset.theme, 'light');

Object.defineProperty(globalThis, 'localStorage', {{
  configurable: true,
  get() {{ throw new Error('storage blocked'); }}
}});
api.restoreThemePreference();
api.setTheme('dark');
assert.equal(document.documentElement.dataset.theme, 'dark');
assert.equal(dark.attributes['aria-pressed'], 'true');

Object.defineProperty(globalThis, 'localStorage', {{
  configurable: true,
  value: {{
    getItem() {{ return null; }},
    setItem() {{ throw new Error('storage write blocked'); }}
  }}
}});
api.setTheme('light');
assert.equal(document.documentElement.dataset.theme, 'light');
assert.equal(light.attributes['aria-pressed'], 'true');
"""
    completed = subprocess.run(
        ["node"],
        check=False,
        capture_output=True,
        input=harness,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_responsive_drawer_executes_inert_focus_trap_escape_and_focus_restore() -> None:
    test_js = JS.replace(
        "refresh();\nsetInterval(refresh, 2000);",
        "globalThis.__drawerTest = { openDetail, closeDetail, updateResponsiveDetailState };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
let drawerMatches = true;
const handlers = {{}};
let mediaChangeHandler = null;
const makeElement = id => ({{
  id, hidden: false, inert: false, attributes: {{}}, dataset: {{}},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  removeAttribute(name) {{ delete this.attributes[name]; }},
  focus() {{ document.activeElement = this; }},
  contains(value) {{ return value === close || value === lastAction; }},
  querySelectorAll() {{ return [close, lastAction]; }}
}});
const panel = makeElement('detail-panel');
const scrim = makeElement('detail-scrim');
const topbar = makeElement('topbar');
const rail = makeElement('channel-rail');
const queue = makeElement('queue-workspace');
const close = makeElement('detail-close');
const lastAction = makeElement('evidence-toggle');
const trigger = makeElement('trigger-row');
trigger.dataset.rowId = 'row-1';
const body = makeElement('body');
body.classList = {{toggle(_name, value) {{ body.open = value; }}}};
globalThis.document = {{
  body, activeElement: body,
  getElementById(id) {{
    return {{'detail-panel': panel, 'detail-scrim': scrim, 'detail-close': close}}[id] || null;
  }},
  querySelector(selector) {{
    return {{'.topbar': topbar, '.channel-rail': rail, '.queue-workspace': queue,
      '#detail-panel': panel}}[selector] || null;
  }},
  querySelectorAll(selector) {{ return selector === '[data-row-id]' ? [trigger] : []; }},
  addEventListener(type, handler) {{ handlers[type] = handler; }}
}};
globalThis.window = {{matchMedia() {{ return {{
  matches: drawerMatches,
  addEventListener(type, handler) {{ if (type === 'change') mediaChangeHandler = handler; }}
}}; }}}};
globalThis.requestAnimationFrame = callback => callback();
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__drawerTest;

// The real startup path must close and inert the responsive drawer before any fetch settles.
assert.equal(panel.inert, true);
assert.equal(panel.attributes['aria-hidden'], 'true');
assert.equal(topbar.inert, false);
api.openDetail('row-1');
assert.equal(panel.inert, false);
assert.equal(topbar.inert, true);
assert.equal(rail.inert, true);
assert.equal(queue.inert, true);
assert.equal(scrim.hidden, false);
assert.equal(document.activeElement, close);

let prevented = false;
handlers.keydown({{key: 'Tab', shiftKey: true, preventDefault() {{ prevented = true; }}}});
assert.equal(prevented, true);
assert.equal(document.activeElement, lastAction);
prevented = false;
handlers.keydown({{key: 'Tab', shiftKey: false, preventDefault() {{ prevented = true; }}}});
assert.equal(prevented, true);
assert.equal(document.activeElement, close);

handlers.keydown({{key: 'Escape', preventDefault() {{ prevented = true; }}}});
assert.equal(panel.inert, true);
assert.equal(topbar.inert, false);
assert.equal(rail.inert, false);
assert.equal(queue.inert, false);
assert.equal(scrim.hidden, true);
assert.equal(document.activeElement, trigger);

api.openDetail('row-1');
drawerMatches = false;
mediaChangeHandler();
assert.equal(panel.inert, false);
assert.equal(topbar.inert, false);
assert.equal(panel.attributes.role, 'complementary');
assert.equal(document.activeElement, trigger);
"""
    completed = subprocess.run(
        ["node"],
        check=False,
        capture_output=True,
        input=harness,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_opportunity_blotter_maps_server_states_without_recomputing_strategy_truth() -> None:
    test_js = JS.replace(
        "syncThemeControl();\nupdateResponsiveDetailState();\nrefresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchTest = { channelSnapshotState, roadmapState, structureState, "
        "radarState, orderedStructureRows, orderedRadarRows, predicateMarginForFailure, "
        "formatMargin, firstFailureSummary, structureJudgement, canonicalShadowMarkup, "
        "reasonText, escapeHtml, runtimeStatusState };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
globalThis.document = {{getElementById() {{ return {{}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__workbenchTest;

const connected = {{
  product: {{name: 'inverse-btc', product_spec_identity: {json.dumps(INVERSE_BTC.identity)}}},
  policy_identities: {{
    radar: {json.dumps(INVERSE_BTC_RADAR_POLICY_IDENTITY)},
    underwriting: {json.dumps(INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY)},
    position: {json.dumps(INVERSE_BTC_POSITION_POLICY_IDENTITY)}
  }},
  service: {{
    phase: 'RUNNING', data_state: 'CURRENT', health: true,
    ready: true, stale: false, reason: 'NONE'
  }},
  system: {{data_delay_ms: 18}}
}};
assert.equal(api.channelSnapshotState(connected).code, 'CONNECTED');
assert.equal(api.runtimeStatusState(connected).key, 'healthy');
assert.equal(api.runtimeStatusState(connected).label, 'Runtime 正常运行');
assert.match(api.runtimeStatusState(connected).blocker, /系统阻塞/);
assert.equal(api.runtimeStatusState(null).key, 'unknown');
const dataBlocked = api.runtimeStatusState({{...connected, service: {{
  ...connected.service, data_state: 'UNKNOWN', ready: false, reason: 'CLOCK_GAP'
}}}});
assert.equal(dataBlocked.key, 'degraded');
assert.equal(dataBlocked.label, 'Runtime 正常运行');
assert.match(dataBlocked.blocker, /可信时间不连续/);
const noScope = api.runtimeStatusState({{...connected, service: {{
  ...connected.service, data_state: 'UNKNOWN', ready: false, reason: 'NO_APPLICABLE_SCOPE'
}}}});
assert.equal(noScope.key, 'degraded');
assert.equal(noScope.label, 'Runtime 正常运行');
assert.match(noScope.blocker, /非 Runtime 故障/);
assert.equal(api.runtimeStatusState({{...connected, service: {{
  ...connected.service, phase: 'RECONNECTING', data_state: 'INTERRUPTED',
  ready: false, reason: 'SESSION_GAP'
}}}}).label, 'Runtime 连接受阻');
assert.equal(api.runtimeStatusState({{...connected, service: {{
  ...connected.service, phase: 'FAILED', data_state: 'STOPPED', health: false,
  ready: false, reason: 'PROCESS_FAILURE'
}}}}).label, 'Runtime 运行失败');
assert.equal(api.runtimeStatusState({{...connected, service: {{
  ...connected.service, phase: 'STOPPED', data_state: 'STOPPED', health: false,
  ready: false, reason: 'HUMAN_STOP'
}}}}).label, 'Runtime 已停止');
assert.equal(api.channelSnapshotState({{...connected, product: {{...connected.product, name: 'linear-btc-usdc'}}}}).code,
  'IDENTITY_MISMATCH');
const identityMismatch = api.runtimeStatusState({{
  ...connected, product: {{...connected.product, name: 'linear-btc-usdc'}}
}});
assert.equal(identityMismatch.key, 'degraded');
assert.equal(identityMismatch.label, 'Runtime 正常运行');
assert.match(identityMismatch.blocker, /身份不匹配/);
assert.equal(api.channelSnapshotState({{
  ...connected, policy_identities: {{...connected.policy_identities, radar: 'sha256:wrong'}}
}}).code, 'IDENTITY_MISMATCH');
assert.equal(api.channelSnapshotState({{...connected, service: {{ready: false, reason: 'CLOCK_GAP'}}}}).code,
  'DATA_BLOCKED');
assert.equal(api.roadmapState({{id: 'INVERSE_BTC_LONG_GAMMA_V1'}}).label, '尚未接入');

assert.deepEqual(api.structureState({{candidate_lifecycle: 'ADMITTED'}}),
  {{key: 'SHADOW_TRACKING', label: 'Shadow 跟踪', tone: 'purple', priority: 0}});
assert.equal(api.structureState({{
  candidate_lifecycle: 'VALID', candidate_still_valid: true
}}).key, 'CANDIDATE');
assert.equal(api.structureState({{availability: 'UNKNOWN'}}).key, 'UNKNOWN');
assert.equal(api.structureState({{availability: 'EVALUABLE', action: 'WATCH'}}).key, 'WATCH');
assert.equal(api.structureState({{availability: 'EVALUABLE', action: 'CANDIDATE'}}).key,
  'CANDIDATE_UNCONFIRMED');
assert.equal(api.radarState({{detector_state: 'ANOMALY_ACTIVE'}}).label, '机会线索');

const ordered = api.orderedStructureRows([
  {{short_leg_instrument_name: 'A', availability: 'EVALUABLE', action: 'ABSTAIN'}},
  {{short_leg_instrument_name: 'W', availability: 'EVALUABLE', action: 'WATCH'}},
  {{short_leg_instrument_name: 'S', candidate_lifecycle: 'ADMITTED'}}
]);
assert.deepEqual(ordered.map(row => row.short_leg_instrument_name), ['S', 'W', 'A']);

const row = {{
  predicate_margin_vector: [{{
    predicate: 'CREDIT_ABOVE_FUTURE_COST_RESERVE',
    signed_margin: '-11.75',
    unit: 'USD_EQUIVALENT',
    passes: false
  }}]
}};
const margin = api.predicateMarginForFailure(row, 'CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE');
assert.equal(margin.signed_margin, '-11.75');
assert.equal(api.formatMargin(margin), '-11.75 USD 等值');
assert.equal(api.formatMargin({{signed_margin: '-0.0718', unit: 'FRACTION'}}), '-0.0718 比例');
assert.deepEqual(api.firstFailureSummary({{
  availability: 'UNKNOWN', failed_predicates: [], unknown_reasons: ['OPTION_BOOK_UNKNOWN']
}}), {{label: '结构经济暂不可判断', margin: '期权簿不可确认'}});
assert.match(api.structureJudgement({{
  availability: 'NOT_EVALUATED', failed_predicates: []
}}).blocker, /尚未进入/);
assert.match(api.canonicalShadowMarkup({{
  candidate_identity: 'candidate', candidate_lifecycle: 'INVALIDATED',
  candidate_invalidation_reason: 'OPTION_BOOK_UNKNOWN'
}}, {{shadow_entries: {{rows: []}}}}), /不再等待 admission/);
assert.match(api.canonicalShadowMarkup({{
  candidate_identity: 'candidate', candidate_lifecycle: 'VALID', candidate_still_valid: true
}}, {{shadow_entries: {{rows: [{{
  candidate_identity: 'candidate', shadow_entry_identity: null,
  admission_refresh_terminal_outcome: 'UNKNOWN_CONSUMED',
  admission_refresh_unknown_reasons: ['OPTION_BOOK_UNKNOWN']
}}]}}}}), /已终结/);
assert.equal(api.reasonText('CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE'), '净权利金未覆盖未来成本准备');
assert.equal(api.escapeHtml('<script>&'), '&lt;script&gt;&amp;');
"""
    completed = subprocess.run(
        ["node"],
        check=False,
        capture_output=True,
        input=harness,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_opportunity_blotter_adds_keyboard_table_and_dialog_accessibility() -> None:
    assert 'class="skip-link"' in HTML
    assert 'id="queue-workspace"' in HTML
    assert 'role="table"' in HTML
    assert 'role="rowgroup"' in HTML
    assert 'scope="col"' in JS
    assert "aria-pressed=" in HTML
    assert 'aria-labelledby="detail-title"' in HTML
    assert 'aria-label="关闭详情"' in HTML
    assert ":focus-visible" in CSS
    assert "focusable[0]" in JS


def test_package_data_declares_static_assets() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"workbench_static/*.html"' in pyproject
    assert '"workbench_static/*.css"' in pyproject
    assert '"workbench_static/*.js"' in pyproject

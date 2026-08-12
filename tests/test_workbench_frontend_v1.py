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
        "INVERSE_BTC_SHORT_VOL_V2",
        "INVERSE_BTC_LONG_GAMMA",
        "INVERSE_ETH_SHORT_VOL",
        "INVERSE_ETH_LONG_GAMMA",
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
    assert "shadow_entry_identity" in JS
    assert "short_leg && row.short_leg.instrument_name" in JS
    assert "Control 留在离线研究面" in JS
    assert "A · 可执行 IV / RV 丰厚度" in JS
    assert "S · 可执行 bid-IV \u2212 同类型局部 mark-IV" in JS
    assert "T · 本到期 ATM mark-IV \u2212 下一到期 ATM mark-IV" in JS
    assert "局部曲面贡献行情不同步\uff0cS 因子不计分" in JS
    assert "相邻期限贡献行情不同步\uff0cT 因子不计分" in JS


def test_opportunity_blotter_preserves_public_only_read_only_boundaries() -> None:
    combined = f"{HTML}\n{JS}"

    assert "PUBLIC SHADOW · READ ONLY · 非订单/成交" in HTML
    assert "只读发现信号 · 非交易指令 · 尚未形成 Shadow Entry" in JS
    assert "不是订单、成交、账户持仓或实际 PnL" in JS
    assert "不显示 0\uff1b继续承担退出或交割责任" in JS
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
    assert 'id="radar-map"' in HTML
    assert 'id="detail-panel"' in HTML
    assert "grid-template-columns: 160px minmax(1000px, 1fr)" in CSS
    assert "width: min(390px, calc(100vw - 56px))" in CSS
    assert "@media (max-width: 900px)" in CSS
    assert "width: min(620px, calc(100vw - 24px))" in CSS
    assert "body.detail-open .detail-panel" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "DRAWER_MEDIA_QUERY = '(max-width: 900px)'" in JS
    assert "panel.setAttribute('aria-modal', 'true')" in JS
    assert "setElementInert('.topbar', drawer && open)" in JS
    assert "setElementInert('.queue-workspace', drawer && open)" in JS
    assert "setElementInert('#detail-panel', !open)" in JS
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


def test_opportunity_blotter_uses_csp_safe_dynamic_graphics() -> None:
    combined = f"{HTML}\n{JS}"

    assert 'style="' not in combined
    assert "--signal-x" not in CSS
    assert "--meter-value" not in CSS
    assert 'class="signal-lane-chart"' in JS
    assert 'class="signal-marker-slot"' in JS
    assert 'transform="translate(-40 0)"' in JS
    assert '<progress class="signal-meter"' in JS
    assert ".signal-meter::-webkit-progress-value" in CSS


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
assert.equal(rail.inert, false);
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
assert.equal(panel.inert, true);
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


def test_shadow_book_maps_server_states_without_recomputing_strategy_truth() -> None:
    test_js = JS.replace(
        "syncThemeControl();\nupdateResponsiveDetailState();\nrefresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchTest = { channelSnapshotState, latencyState, roadmapState, "
        "radarState, radarReviewConstraint, radarConfirmationText, reasonCountsText, radarDetailMarkup, "
        "isStrongSignalRow, strongSignalRows, groupStrongSignalsByExpiry, "
        "signalStrikeBounds, signalXPercent, signalLaneLayout, signalMarkerMarkup, "
        "signalLaneChartMarkup, shadowBookRows, groupShadowBookRowsByExpiry, shadowBookIdentity, "
        "shadowLifecyclePresentation, shadowResponsibilityIssue, shadowTerminalIssue, shadowNextDuty, shadowTriggerText, "
        "shadowCloseEconomics, shadowBookRowMarkup, shadowDetailMarkup, postCloseAttemptText, "
        "validateDocument, reasonText, escapeHtml, runtimeStatusState };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
globalThis.document = {{getElementById() {{ return {{}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__workbenchTest;

const connected = {{
  channel_id: 'INVERSE_BTC_SHORT_VOL_V2',
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
  system: {{
    latest_market_event_timestamp_ms:1700000000000,
    latest_market_event_age_ms:7000, last_wire_message_age_ms:100,
    last_queue_processing_lag_ms:12, queue_lag_deadline_ms:5000,
    queue_lag_currentness_active:false
  }}
}};
assert.equal(api.channelSnapshotState(connected).code, 'CONNECTED');
assert.deepEqual(api.latencyState(connected.system), {{
  event:'行情事件年龄 7.0 秒', wire:'收包静默 100 ms',
  queue:'处理队列 12 ms / 阈值 5.0 秒',
  note:'处理 12 ms · 行情事件 7.0 秒'
}});
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
assert.equal(api.roadmapState({{id: 'INVERSE_BTC_LONG_GAMMA'}}).label, '尚未接入');
const validProjection = {{
  ...connected, schema_version: 7,
  product: {{
    ...connected.product, native_premium_currency: 'BTC', valuation_currency: 'USD_EQUIVALENT',
    actual_account_margin_availability: 'UNKNOWN', actual_account_margin_reason: 'ACCOUNT_MARGIN_UNKNOWN'
  }},
  radar: {{rows: []}}, underwriting: {{rows: []}}, shadow_entries: {{rows: []}},
  positions: {{rows: []}}, outcomes: {{rows: []}}, funnel: {{}}
}};
assert.doesNotThrow(() => api.validateDocument(validProjection));
for (const missingProjection of ['shadow_entries', 'positions', 'outcomes']) {{
  const incomplete = {{...validProjection}};
  delete incomplete[missingProjection];
  assert.throws(() => api.validateDocument(incomplete), /invalid workbench projection/);
}}

assert.equal(api.radarState({{
  instrument_name: 'LEADER', is_bucket_leader: true,
  clue_eligible_tte: true, clue_eligible_delta: true,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'ACTIVE',
  bucket_episode_score_band: 'HIGH', bucket_episode_identity: 'sha256:active',
  bucket_episode_leader_instrument_name: 'LEADER'
}}).label, 'HIGH · 已确认线索');
const strongActive = {{
  instrument_name: 'LEADER', is_bucket_leader: true,
  clue_eligible_tte: true, clue_eligible_delta: true,
  score_result: {{band: 'HIGH', score: {{lower: '78', upper: '78'}}}},
  bucket_episode_state: 'ACTIVE', bucket_episode_score_band: 'HIGH',
  bucket_episode_identity: 'sha256:active', bucket_episode_leader_instrument_name: 'LEADER',
  expiration_timestamp_ms: 1800000000000, strike_price: '63000', option_type: 'put'
}};
assert.equal(api.isStrongSignalRow(strongActive), true);
assert.equal(api.isStrongSignalRow({{...strongActive, is_bucket_leader: false}}), false);
assert.equal(api.isStrongSignalRow({{...strongActive, clue_eligible_tte: false}}), false);
assert.equal(api.isStrongSignalRow({{...strongActive, score_result: {{band: 'MID'}}}}), false);
assert.equal(api.isStrongSignalRow({{...strongActive, bucket_episode_state: 'IDLE'}}), false);
const confirming = {{...strongActive, instrument_name: 'CONFIRM', strike_price: '69000',
  bucket_episode_leader_instrument_name: 'CONFIRM', bucket_episode_identity: null,
  bucket_episode_state: 'CONFIRMING'}};
assert.equal(api.isStrongSignalRow(confirming), true);
assert.equal(api.isStrongSignalRow({{...confirming, bucket_episode_identity: 'sha256:premature'}}), false);
assert.equal(api.isStrongSignalRow({{...strongActive, bucket_episode_identity: null}}), false);
const mapDocument = {{radar: {{rows: [
  {{instrument_name: 'MEMBER', expiration_timestamp_ms: 1800000000000,
    strike_price: '60000', option_type: 'put', score_result: {{band: 'HIGH'}}}},
  strongActive, confirming
]}}}};
assert.deepEqual(api.strongSignalRows(mapDocument).map(row => row.instrument_name), ['LEADER', 'CONFIRM']);
assert.equal(api.groupStrongSignalsByExpiry(api.strongSignalRows(mapDocument)).length, 1);
assert.deepEqual(api.signalStrikeBounds(mapDocument), {{lower: 60000, upper: 69000}});
assert.equal(api.signalXPercent(60000, {{lower: 60000, upper: 69000}}), 4);
assert.equal(api.signalXPercent(69000, {{lower: 60000, upper: 69000}}), 96);
const markerMarkup = api.signalMarkerMarkup(confirming, 0, {{lower: 60000, upper: 69000}}, 0, 130);
assert.match(markerMarkup, /<foreignObject[^>]+x="96%"[^>]+y="34"/);
assert.match(markerMarkup, /transform="translate\\(-40 0\\)"/);
assert.match(markerMarkup, /<circle class="signal-ring/);
assert.match(markerMarkup, /<button[^>]+role="listitem"/);
assert.doesNotMatch(markerMarkup, /style=/);
const stackedGroup = {{scopeRows: mapDocument.radar.rows, rows: [strongActive, {{
  ...confirming, instrument_name: 'CONFIRM-SAME', strike_price: '63000',
  bucket_episode_leader_instrument_name: 'CONFIRM-SAME'
}}]}};
const chartMarkup = api.signalLaneChartMarkup(stackedGroup, {{lower: 60000, upper: 69000}});
const stackedLayout = api.signalLaneLayout(stackedGroup.rows, {{lower: 60000, upper: 69000}});
assert.equal(stackedLayout.tierCount, 2);
assert.equal(stackedLayout.chartHeight, 236);
assert.match(chartMarkup, /<svg class="signal-lane-chart"/);
assert.match(chartMarkup, /<line class="signal-track-line"/);
assert.match(chartMarkup, /y="34"/);
assert.match(chartMarkup, /y="120"/);
assert.doesNotMatch(chartMarkup, /style=/);
assert.match(api.radarState({{
  instrument_name: 'MEMBER', is_bucket_leader: false,
  clue_eligible_tte: true, clue_eligible_delta: true,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'ACTIVE',
  bucket_episode_score_band: 'HIGH', bucket_episode_identity: 'sha256:active',
  bucket_episode_leader_instrument_name: 'LEADER',
  confirmation_observation_count: 3, required_confirmation_observation_count: 3
}}).label, /确认中/);
assert.match(api.radarState({{
  clue_eligible_tte: true, clue_eligible_delta: true,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'CONFIRMING',
  confirmation_observation_count: 1, required_confirmation_observation_count: 3
}}).label, new RegExp('确认中 1/3'));
const reviewOnlyHigh = {{
  instrument_name: 'REVIEW', is_bucket_leader: true,
  clue_eligible_tte: false, clue_eligible_delta: true,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'IDLE',
  confirmation_observation_count: 0, required_confirmation_observation_count: 3
}};
assert.equal(api.radarReviewConstraint(reviewOnlyHigh), 'TTE');
assert.equal(api.radarState(reviewOnlyHigh).label, 'HIGH 分数 · TTE 仅供审查');
assert.equal(api.radarConfirmationText(reviewOnlyHigh), 'TTE 仅供审查 · 不进入确认');
assert.equal(api.radarState(reviewOnlyHigh).label.includes('确认中'), false);
assert.equal(api.radarState(reviewOnlyHigh).label.includes('0/3'), false);
assert.equal(api.radarReviewConstraint({{
  clue_eligible_tte: false, clue_eligible_delta: false
}}), 'TTE/Delta');
assert.equal(api.radarState({{
  clue_eligible_tte: true, clue_eligible_delta: false, score_result: {{band: 'REVIEW'}}
}}).label, 'REVIEW 分数 · Delta 仅供审查');
const resetReasons = api.reasonCountsText({{SCORE_BAND_CHANGE: 3, LEADER_CHANGE: 1}});
assert.match(resetReasons, /Score band 变化 3/);
assert.match(resetReasons, /Bucket leader 变化 1/);
const radarDetail = api.radarDetailMarkup(reviewOnlyHigh, {{funnel: {{
  radar_confirmation: {{reset_counts: {{CORE_UNKNOWN: 2}}}},
  decision_control_research: {{known_no_control_reason_counts: {{NO_PROTECTIVE_COMPONENT: 4}}}}
}}}});
assert.match(radarDetail, /TTE 仅供审查 · 不进入确认/);
assert.match(radarDetail, /核心 Radar 事实变为 UNKNOWN 2/);
assert.match(radarDetail, /没有可冻结的同到期保护腿 4/);
assert.match(radarDetail, /非本行因果归因/);
const meteredDetail = api.radarDetailMarkup({{...strongActive, score_result: {{
  band: 'HIGH', score: {{lower: '78', upper: '78'}},
  premium_evidence: {{lower: '0.72', upper: '0.72'}},
  risk_quality: {{lower: '0.64', upper: '0.64'}}
}}}}, {{funnel: {{}}}});
assert.match(meteredDetail, /<progress class="signal-meter" max="100" value="72"/);
assert.match(meteredDetail, /<progress class="signal-meter" max="100" value="64"/);
assert.doesNotMatch(meteredDetail, /style=/);

const makeEntry = (identity, expiry, optionType = 'put') => ({{
  candidate_identity: `candidate-${{identity}}`, shadow_entry_identity: identity,
  admission_refresh_terminal_outcome: 'ENTRY_EMITTED', expiry_timestamp_ms: expiry,
  option_type: optionType, short_strike_price: optionType === 'put' ? '64500' : '70000',
  long_strike_price: optionType === 'put' ? '63000' : '71500',
  native_gross_entry_credit: '0.00029', native_entry_fee_reserve: '0.00004',
  native_net_entry_credit: '0.00025', simulated_entry_credit_valuation: '18.8206781',
  entry_valuation_index_price: '64898.89', target_quantity_btc: '0.1',
  origin_runtime_identity: 'sha256:origin', current_segment_sequence: 0,
  observation_quality: 'CONTINUOUS', gap_count: 0, qualification_eligible: true,
  tracking_state: 'ACTIVE', post_close_attempt_state: 'NOT_SCHEDULED',
  entry_component_legs: [
    {{canonical_leg_role: 'SHORT', action: 'SELL', instrument_name: `BTC-13AUG26-${{optionType === 'put' ? '64500-P' : '70000-C'}}`}},
    {{canonical_leg_role: 'LONG', action: 'BUY', instrument_name: `BTC-13AUG26-${{optionType === 'put' ? '63000-P' : '71500-C'}}`}}
  ]
}});
const makePosition = (identity, lifecycle, overrides = {{}}) => ({{
  shadow_entry_identity: identity, enrollment_kind: 'ADMITTED_SHADOW_TRADE',
  position_lifecycle_state: lifecycle, position_action: lifecycle === 'MONITORING' ? 'HOLD' : 'CLOSE',
  observation_quality: 'CONTINUOUS', qualification_eligible: true,
  terminal_economics_eligible: lifecycle === 'TERMINAL', continuous_path_eligible: true,
  exit_acquisition_eligible: lifecycle === 'TERMINAL',
  primary_exit_rule: lifecycle === 'MONITORING' ? null : 'MAXIMUM_NET_LOSS_BOUNDARY_REACHED',
  hard_close_countdown_interval_ms: {{lower_ms: 3600000, upper_ms: 3600000}},
  close_quote_state: 'UNKNOWN', valid_shadow_close_opportunity: false, ...overrides
}});
const makeOutcome = (identity, state = 'PENDING', overrides = {{}}) => ({{
  shadow_entry_identity: identity, state, terminal_method: null,
  public_quote_net_pnl_valuation: null, ...overrides
}});
const expiryOne = 1786579200000;
const expiryTwo = expiryOne + 86400000;
const entries = [
  makeEntry('monitor', expiryTwo, 'call'), makeEntry('exit', expiryOne),
  makeEntry('settlement', expiryOne), makeEntry('exited', expiryTwo),
  makeEntry('settled', expiryTwo), makeEntry('terminal-unknown', expiryTwo),
  {{...makeEntry('gapped', expiryOne), observation_quality: 'GAPPED', gap_count: 2,
    qualification_eligible: false, current_segment_sequence: null,
    post_close_attempt_state: 'ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS'}}
];
const positions = [
  makePosition('monitor', 'MONITORING'),
  makePosition('exit', 'EXIT_ACQUIRING', {{
    primary_exit_rule: 'PLATFORM_OR_SOURCE_DISCONTINUITY', observation_quality: 'GAPPED',
    qualification_eligible: false, continuous_path_eligible: false
  }}),
  makePosition('settlement', 'SETTLEMENT_PENDING', {{primary_exit_rule: 'SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED'}}),
  makePosition('exited', 'TERMINAL'), makePosition('settled', 'TERMINAL'),
  makePosition('terminal-unknown', 'TERMINAL'),
  makePosition('gapped', 'EXIT_ACQUIRING', {{
    observation_quality: 'GAPPED', qualification_eligible: false, continuous_path_eligible: false,
    valid_shadow_close_opportunity: true, current_close_debit_valuation: '9.25',
    projected_shadow_pnl_valuation: '7.50'
  }})
];
const outcomes = [
  makeOutcome('monitor'), makeOutcome('exit'), makeOutcome('settlement'),
  makeOutcome('exited', 'EXITED_KNOWN', {{terminal_method: 'MARKET_EXIT', public_quote_net_pnl_valuation: '8.25'}}),
  makeOutcome('settled', 'SETTLED_KNOWN', {{terminal_method: 'CONTRACT_SETTLEMENT', public_quote_net_pnl_valuation: '-2.00'}}),
  makeOutcome('terminal-unknown', 'TERMINAL_UNKNOWN', {{terminal_method: 'TERMINAL_UNKNOWN'}}),
  makeOutcome('gapped')
];
const shadowDocument = {{
  shadow_entries: {{rows: entries}}, positions: {{rows: positions}}, outcomes: {{rows: outcomes}},
  underwriting: {{rows: [{{candidate_identity: 'must-not-render'}}]}},
  product: {{native_premium_currency: 'BTC', valuation_currency: 'USD_EQUIVALENT'}}
}};
const bookRows = api.shadowBookRows(shadowDocument);
assert.equal(bookRows.length, 7);
assert.equal(bookRows.some(value => value.shadow_entry_identity === 'must-not-render'), false);
assert.deepEqual(api.groupShadowBookRowsByExpiry(bookRows).map(value => value.rows.length), [3, 4]);
const byId = Object.fromEntries(bookRows.map(value => [value.shadow_entry_identity, value]));
assert.equal(api.shadowLifecyclePresentation(byId.monitor).label, '观察中');
assert.equal(api.shadowNextDuty(byId.monitor), '继续监控九条退出谓词');
assert.equal(api.shadowLifecyclePresentation(byId.exit).label, '退出中');
assert.equal(api.shadowTriggerText(byId.exit), '历史 CLOSE 已锁存');
assert.equal(api.shadowNextDuty(byId.exit), '继续寻找首组合格退出报价');
assert.equal(api.shadowLifecyclePresentation(byId.settlement).label, '等待交割');
assert.equal(api.shadowNextDuty(byId.settlement), '等待官方 delivery price');
assert.equal(api.shadowLifecyclePresentation(byId.exited).label, '已退出');
assert.equal(api.shadowLifecyclePresentation(byId.settled).label, '已结算');
assert.equal(api.shadowLifecyclePresentation(byId['terminal-unknown']).label, '终端经济未知');
assert.deepEqual(api.shadowCloseEconomics(byId['terminal-unknown']),
  {{kind: 'TERMINAL_UNKNOWN', pnl: null, debit: null}});
const terminalUnknownDetail = api.shadowDetailMarkup(byId['terminal-unknown'], shadowDocument);
assert.match(terminalUnknownDetail, /持仓责任已终结/);
assert.doesNotMatch(terminalUnknownDetail, /继续承担退出或交割责任/);
assert.deepEqual(api.shadowCloseEconomics(byId.gapped), {{kind: 'CURRENT_QUOTE', pnl: '7.50', debit: '9.25'}});
assert.equal(api.shadowLifecyclePresentation(byId.gapped).label, '退出中');
const gappedDetail = api.shadowDetailMarkup(byId.gapped, shadowDocument);
assert.match(gappedDetail, /旧尝试状态未知 · 当前 Segment 持续承担退出责任/);
assert.match(gappedDetail, /Observation Gap 只描述路径质量/);
assert.match(gappedDetail, /不终止退出责任/);
assert.equal(gappedDetail.includes('+7.5 USD_EQUIVALENT'), true);
const pendingDetail = api.shadowDetailMarkup(byId.exit, shadowDocument);
assert.match(pendingDetail, /不显示 0/);
assert.match(pendingDetail, /继续承担退出或交割责任/);
assert.equal(pendingDetail.includes('平台/行情源不连续'), true);
assert.equal(pendingDetail.includes('历史首次 CLOSE 已锁存'), true);
const settledDetail = api.shadowDetailMarkup(byId.settled, shadowDocument);
assert.match(settledDetail, /SETTLED_KNOWN · CONTRACT_SETTLEMENT/);
assert.match(settledDetail, /-2 USD_EQUIVALENT/);
const missingPositionDocument = {{
  ...shadowDocument, shadow_entries: {{rows: [makeEntry('missing-position', expiryOne)]}},
  positions: {{rows: []}}, outcomes: {{rows: [makeOutcome('missing-position')]}}
}};
const [missingPosition] = api.shadowBookRows(missingPositionDocument);
assert.equal(api.shadowResponsibilityIssue(missingPosition), 'MISSING_POSITION_PROJECTION');
assert.equal(api.shadowLifecyclePresentation(missingPosition).label, '关联待恢复');
assert.match(api.shadowDetailMarkup(missingPosition, missingPositionDocument), /Entry 不删除/);
const missingTerminalDocument = {{
  ...shadowDocument, shadow_entries: {{rows: [makeEntry('missing-terminal', expiryOne)]}},
  positions: {{rows: [makePosition('missing-terminal', 'TERMINAL')]}}, outcomes: {{rows: []}}
}};
const [missingTerminal] = api.shadowBookRows(missingTerminalDocument);
assert.equal(api.shadowTerminalIssue(missingTerminal), 'MISSING_TERMINAL_OUTCOME_PROJECTION');
assert.equal(api.shadowLifecyclePresentation(missingTerminal).label, '终端结果待恢复');
assert.equal(api.shadowNextDuty(missingTerminal), '恢复唯一终端 Outcome 投影');
assert.match(api.shadowDetailMarkup(missingTerminal, missingTerminalDocument), /不推断退出方式或经济结果/);
const duplicateTerminalDocument = {{
  ...shadowDocument, shadow_entries: {{rows: [makeEntry('duplicate-terminal', expiryOne)]}},
  positions: {{rows: [makePosition('duplicate-terminal', 'TERMINAL')]}},
  outcomes: {{rows: [
    makeOutcome('duplicate-terminal', 'EXITED_KNOWN', {{terminal_method: 'MARKET_EXIT'}}),
    makeOutcome('duplicate-terminal', 'SETTLED_KNOWN', {{terminal_method: 'CONTRACT_SETTLEMENT'}})
  ]}}
}};
const [duplicateTerminal] = api.shadowBookRows(duplicateTerminalDocument);
assert.equal(api.shadowTerminalIssue(duplicateTerminal), 'DUPLICATE_OUTCOME_IDENTITY');
assert.equal(api.shadowLifecyclePresentation(duplicateTerminal).label, '终端结果待恢复');
const duplicateEntry = makeEntry('duplicate-entry', expiryOne);
const duplicateDocument = {{
  ...shadowDocument, shadow_entries: {{rows: [duplicateEntry, duplicateEntry]}},
  positions: {{rows: [makePosition('duplicate-entry', 'EXIT_ACQUIRING')]}},
  outcomes: {{rows: [makeOutcome('duplicate-entry')]}}
}};
const duplicateRows = api.shadowBookRows(duplicateDocument);
assert.equal(duplicateRows.length, 2);
assert.notEqual(api.shadowBookIdentity(duplicateRows[0]), api.shadowBookIdentity(duplicateRows[1]));
assert.equal(api.shadowLifecyclePresentation(duplicateRows[0]).label, '关联待恢复');
const displayOnlyIssueDocument = {{
  ...shadowDocument, shadow_entries: {{rows: [{{...makeEntry('display-issue', expiryOne), entry_component_legs: []}}]}},
  positions: {{rows: [makePosition('display-issue', 'EXIT_ACQUIRING')]}},
  outcomes: {{rows: [makeOutcome('display-issue')]}}
}};
const [displayOnlyIssue] = api.shadowBookRows(displayOnlyIssueDocument);
assert.equal(displayOnlyIssue.issues.includes('INVALID_ENTRY_COMPONENT_ROLES'), true);
assert.equal(api.shadowLifecyclePresentation(displayOnlyIssue).label, '退出中');
assert.equal(api.shadowNextDuty(displayOnlyIssue), '继续寻找首组合格退出报价');
const rowMarkup = api.shadowBookRowMarkup(byId.exit, 0, shadowDocument);
assert.equal(rowMarkup.includes('Public Shadow · 非订单/成交'), true);
assert.doesNotMatch(rowMarkup, /style=/);
const terminalRowMarkup = api.shadowBookRowMarkup(byId.exited, 1, shadowDocument);
assert.match(terminalRowMarkup, /持仓责任已终结/);
assert.doesNotMatch(terminalRowMarkup, /当前仍承担退出责任/);
assert.equal(api.postCloseAttemptText('ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS'),
  '旧尝试状态未知 · 当前 Segment 持续承担退出责任');
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
    assert 'role="rowgroup"' in JS
    assert 'role="columnheader"' in JS
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

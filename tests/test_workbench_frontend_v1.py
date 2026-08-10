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
    assert "避免浏览器误拼不同 Episode" in JS
    assert "服务器未提供 V2 score packet" in JS
    assert "浏览器不补算" in JS
    assert "A · 可执行 IV / RV 丰厚度" in JS
    assert "S · 可执行 bid-IV \u2212 同类型局部 mark-IV" in JS
    assert "T · 本到期 ATM mark-IV \u2212 下一到期 ATM mark-IV" in JS
    assert "局部曲面贡献行情不同步\uff0cS 因子不计分" in JS
    assert "相邻期限贡献行情不同步\uff0cT 因子不计分" in JS


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
        "globalThis.__workbenchTest = { channelSnapshotState, latencyState, roadmapState, structureState, "
        "radarState, orderedStructureRows, orderedRadarRows, predicateMarginForFailure, "
        "formatMargin, firstFailureSummary, structureJudgement, canonicalShadowMarkup, "
        "canonicalShadowEntry, structureEntryFacts, structureIdentity, structureDetailMarkup, "
        "shadowStructureRow, structureQueueRows, shadowTrackingPresentation, "
        "structureDecisionMarkup, shadowTrackingEvidenceMarkup, postCloseAttemptText, "
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

assert.deepEqual(api.structureState({{candidate_lifecycle: 'ADMITTED'}}),
  {{key: 'SHADOW_TRACKING', label: 'Shadow 跟踪', tone: 'purple', priority: 0}});
assert.equal(api.structureState({{
  candidate_lifecycle: 'VALID', candidate_still_valid: true
}}).key, 'CANDIDATE');
assert.equal(api.structureState({{availability: 'UNKNOWN'}}).key, 'UNKNOWN');
assert.equal(api.structureState({{availability: 'EVALUABLE', action: 'WATCH'}}).key, 'WATCH');
assert.equal(api.structureState({{availability: 'EVALUABLE', action: 'CANDIDATE'}}).key,
  'CANDIDATE_UNCONFIRMED');
assert.equal(api.radarState({{
  instrument_name: 'LEADER', is_bucket_leader: true,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'ACTIVE',
  bucket_episode_score_band: 'HIGH', bucket_episode_identity: 'sha256:active',
  bucket_episode_leader_instrument_name: 'LEADER'
}}).label, 'HIGH · 已确认线索');
assert.match(api.radarState({{
  instrument_name: 'MEMBER', is_bucket_leader: false,
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'ACTIVE',
  bucket_episode_score_band: 'HIGH', bucket_episode_identity: 'sha256:active',
  bucket_episode_leader_instrument_name: 'LEADER',
  confirmation_observation_count: 3, required_confirmation_observation_count: 3
}}).label, /确认中/);
assert.match(api.radarState({{
  score_result: {{band: 'HIGH'}}, bucket_episode_state: 'CONFIRMING',
  confirmation_observation_count: 1, required_confirmation_observation_count: 3
}}).label, new RegExp('确认中 1/3'));

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
const admitted = {{
  candidate_identity: 'candidate', candidate_lifecycle: 'ADMITTED',
  availability: 'NOT_EVALUATED', native_net_entry_credit: null,
  net_entry_credit_valuation: null, entry_valuation_index_price: null
}};
const matchingShadow = {{
  candidate_identity: 'candidate', shadow_entry_identity: 'entry',
  admission_refresh_terminal_outcome: 'ENTRY_EMITTED',
  native_gross_entry_credit: '0.00029', native_entry_fee_reserve: '0.00004',
  native_net_entry_credit: '0.00025', simulated_entry_credit_valuation: '18.8206781',
  entry_valuation_index_price: '64898.89', target_quantity_btc: '0.1',
  entry_component_legs: [
    {{canonical_leg_role: 'SHORT', action: 'SELL', instrument_name: 'BTC-11AUG26-64500-P'}},
    {{canonical_leg_role: 'LONG', action: 'BUY', instrument_name: 'BTC-11AUG26-63000-P'}}
  ]
}};
const shadowDocument = {{shadow_entries: {{rows: [matchingShadow]}}}};
assert.equal(api.canonicalShadowEntry(admitted, shadowDocument), matchingShadow);
assert.deepEqual(api.structureEntryFacts(admitted, shadowDocument), {{
  source: 'SHADOW_ENTRY', status: 'ENTRY_EMITTED',
  valuationIndex: '64898.89', targetQuantity: '0.1', nativeNetCredit: '0.00025',
  nativeGrossCredit: '0.00029', nativeFeeReserve: '0.00004',
  valuationGrossCredit: '18.8206781'
}});
assert.equal(api.structureIdentity({{
  candidate_identity: 'candidate', underwriting_availability_evaluation_identity: 'changing-evaluation'
}}), 'candidate');
assert.equal(api.canonicalShadowEntry(admitted, {{shadow_entries: {{rows: [{{
  ...matchingShadow, candidate_identity: 'different-candidate'
}}]}}}}), null);
const currentUnderwriting = {{
  availability: 'NOT_EVALUATED', candidate_identity: null, candidate_lifecycle: null,
  underwriting_availability_evaluation_identity: 'current-evaluation',
  short_leg_instrument_name: 'BTC-11AUG26-64500-P',
  long_leg_instrument_name: 'BTC-11AUG26-62000-P', failed_predicates: [],
  predicate_margin_vector: [], unknown_reasons: []
}};
const queueDocument = {{
  ...shadowDocument,
  underwriting: {{rows: [currentUnderwriting]}},
  product: {{native_premium_currency: 'BTC', valuation_currency: 'USD_EQUIVALENT'}},
  positions: {{rows: []}}, outcomes: {{rows: []}}
}};
const queueRows = api.structureQueueRows(queueDocument);
assert.equal(queueRows.length, 2);
assert.equal(queueRows[0].queue_row_kind, 'SHADOW_ENTRY');
assert.equal(api.structureIdentity(queueRows[0]), 'candidate');
assert.equal(queueRows[0].short_leg_instrument_name, 'BTC-11AUG26-64500-P');
assert.equal(queueRows[0].long_leg_instrument_name, 'BTC-11AUG26-63000-P');
assert.equal(api.structureState(currentUnderwriting).key, 'NOT_EVALUATED');
assert.equal(api.shadowTrackingEvidenceMarkup(matchingShadow), '');
assert.doesNotMatch(api.structureDecisionMarkup(queueRows[0]), /观察有间隙/);
const gappedShadow = {{
  ...matchingShadow,
  origin_runtime_identity: 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  current_segment_identity: null,
  current_segment_sequence: null,
  observation_quality: 'GAPPED', gap_count: 2,
  qualification_eligible: false, tracking_state: 'RECOVERING',
  post_close_attempt_state: 'ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS',
  entry_fact_boundary: {{causal_seq: 4}},
  entry_component_quote_source_refs: [
    {{canonical_leg_role: 'SHORT', source_timestamp_ms: 1000}},
    {{canonical_leg_role: 'LONG', source_timestamp_ms: 1001}}
  ]
}};
const gappedDocument = {{
  ...queueDocument,
  shadow_entries: {{rows: [gappedShadow]}},
  positions: {{rows: [{{
    shadow_entry_identity: 'entry', position_action: 'UNKNOWN',
    observation_quality: 'GAPPED', qualification_eligible: false,
    primary_exit_rule: null, hard_close_countdown_interval_ms: null,
    valid_shadow_close_opportunity: false
  }}]}}
}};
const [gappedRow] = api.structureQueueRows(gappedDocument);
assert.deepEqual(api.shadowTrackingPresentation(gappedRow), {{
  label: '跨进程跟踪', note: '观察有间隙 · 不计入连续观察资格'
}});
assert.deepEqual(api.shadowTrackingPresentation({{
  candidate_lifecycle: 'ADMITTED',
  shadow_entry_projection: {{...matchingShadow, observation_quality: 'CONTINUOUS',
    qualification_eligible: false}}
}}), {{label: 'Shadow 跟踪', note: '不计入连续观察资格'}});
assert.equal(api.structureState(gappedRow).key, 'SHADOW_TRACKING');
assert.equal(api.structureState(gappedRow).tone, 'purple');
const gappedDecision = api.structureDecisionMarkup(gappedRow);
assert.match(gappedDecision, /跨进程跟踪/);
assert.match(gappedDecision, /观察有间隙/);
assert.match(gappedDecision, /不计入连续观察资格/);
assert.doesNotMatch(gappedDecision, /tone-red|tone-amber|异常|阻塞/);
assert.equal(api.postCloseAttemptText('NOT_SCHEDULED'), '尚未安排');
assert.equal(api.postCloseAttemptText('SCHEDULED'), '已安排');
assert.equal(api.postCloseAttemptText('TERMINAL'), '已终结');
assert.equal(api.postCloseAttemptText('ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS'),
  '进程中断后状态未知\\uFF08不重试\\uFF09');
const trackingEvidence = api.shadowTrackingEvidenceMarkup(gappedShadow);
assert.match(trackingEvidence, /跨进程跟踪/);
assert.match(trackingEvidence, /观察有间隙/);
assert.match(trackingEvidence, /不计入连续观察资格/);
assert.match(trackingEvidence, /sha256:aaaa/);
assert.doesNotMatch(trackingEvidence, /#2/);
assert.match(trackingEvidence, /入场 causal seq/);
assert.match(trackingEvidence, />4</);
assert.match(trackingEvidence, /双腿源时间/);
assert.match(trackingEvidence, new RegExp('1000 / 1001'));
assert.match(trackingEvidence, /进程中断后状态未知\\uFF08不重试\\uFF09/);
assert.doesNotMatch(trackingEvidence, /callout blocker/);
const gappedShadowMarkup = api.canonicalShadowMarkup(gappedRow, gappedDocument);
assert.match(gappedShadowMarkup, /跨进程跟踪/);
assert.match(gappedShadowMarkup, /UNKNOWN/);
const gappedDetail = api.structureDetailMarkup(gappedRow, gappedDocument);
assert.match(gappedDetail, /观察有间隙/);
assert.match(gappedDetail, /不计入连续观察资格/);
assert.match(gappedDetail, /0\\.00025/);
assert.match(gappedDetail, /18\\.82/);
const duplicateDecorated = api.structureQueueRows({{
  ...queueDocument, underwriting: {{rows: [admitted]}}
}});
assert.equal(duplicateDecorated.length, 1);
const secondShadow = {{...matchingShadow, candidate_identity: 'candidate-2', shadow_entry_identity: 'entry-2'}};
assert.equal(api.structureQueueRows({{
  ...queueDocument, underwriting: {{rows: []}}, shadow_entries: {{rows: [matchingShadow, secondShadow]}}
}}).length, 2);
const repeatedCandidateShadow = {{
  ...matchingShadow, shadow_entry_identity: 'entry-duplicate-candidate',
  native_net_entry_credit: '0.00031'
}};
const repeatedCandidateDocument = {{
  ...queueDocument, underwriting: {{rows: []}},
  shadow_entries: {{rows: [matchingShadow, repeatedCandidateShadow]}}
}};
const repeatedCandidateRows = api.structureQueueRows(repeatedCandidateDocument);
assert.equal(repeatedCandidateRows.length, 2);
assert.deepEqual(repeatedCandidateRows.map(value => api.structureIdentity(value)).sort(),
  ['entry', 'entry-duplicate-candidate']);
for (const value of repeatedCandidateRows) {{
  assert.equal(api.structureState(value).key, 'UNKNOWN');
  assert.equal(api.canonicalShadowEntry(value, repeatedCandidateDocument), value.shadow_entry_projection);
}}
assert.equal(api.structureEntryFacts(
  repeatedCandidateRows.find(value => value.shadow_entry_identity === 'entry-duplicate-candidate'),
  repeatedCandidateDocument
).nativeNetCredit, '0.00031');
const missingCandidateShadow = {{...matchingShadow, candidate_identity: null, shadow_entry_identity: 'entry-no-candidate'}};
const missingCandidateDocument = {{
  ...queueDocument, underwriting: {{rows: []}}, shadow_entries: {{rows: [missingCandidateShadow]}}
}};
const [missingCandidateRow] = api.structureQueueRows(missingCandidateDocument);
assert.equal(api.structureState(missingCandidateRow).key, 'UNKNOWN');
assert.equal(api.structureIdentity(missingCandidateRow), 'entry-no-candidate');
assert.match(api.structureDetailMarkup(missingCandidateRow, missingCandidateDocument), /Shadow 投影关联异常/);
const invalidIdentityShadow = {{
  ...matchingShadow, candidate_identity: {{value: 'candidate'}}, shadow_entry_identity: 17
}};
const invalidIdentityDocument = {{
  ...queueDocument, underwriting: {{rows: []}}, shadow_entries: {{rows: [invalidIdentityShadow]}}
}};
const [invalidIdentityRow] = api.structureQueueRows(invalidIdentityDocument);
assert.equal(api.structureState(invalidIdentityRow).key, 'UNKNOWN');
assert.equal(api.structureIdentity(invalidIdentityRow), 'shadow-projection-0');
assert.equal(api.canonicalShadowEntry(invalidIdentityRow, invalidIdentityDocument), null);
const invalidLegsShadow = {{
  ...matchingShadow, shadow_entry_identity: 'entry-invalid-legs', candidate_identity: 'candidate-invalid-legs',
  entry_component_legs: [
    {{canonical_leg_role: 'SHORT', action: 'BUY', instrument_name: 'BTC-11AUG26-64500-P'}},
    {{canonical_leg_role: 'LONG', action: 'SELL', instrument_name: 'BTC-11AUG26-63000-P'}}
  ]
}};
const invalidLegsDocument = {{
  ...queueDocument, underwriting: {{rows: []}}, shadow_entries: {{rows: [invalidLegsShadow]}}
}};
const [invalidLegsRow] = api.structureQueueRows(invalidLegsDocument);
const invalidLegsDetail = api.structureDetailMarkup(invalidLegsRow, invalidLegsDocument);
assert.equal(api.structureState(invalidLegsRow).key, 'UNKNOWN');
assert.match(invalidLegsDetail, new RegExp('拒绝由浏览器补写 SELL/BUY'));
const shadowDetail = api.structureDetailMarkup(queueRows[0], queueDocument);
assert.match(shadowDetail, /ENTRY_EMITTED/);
assert.match(shadowDetail, /64898\\.89/);
assert.match(shadowDetail, /0\\.00025/);
assert.match(shadowDetail, /18\\.82/);
assert.match(shadowDetail, /费前信用/);
assert.match(shadowDetail, /BTC-11AUG26-64500-P/);
assert.match(shadowDetail, /BTC-11AUG26-63000-P/);
assert.doesNotMatch(shadowDetail, /NOT_EVALUATED/);
assert.doesNotMatch(shadowDetail, /跨进程跟踪|观察有间隙|不计入连续观察资格/);
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

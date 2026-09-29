/* One browser poller reads the shared backend state; it never starts a collector. */
(function (root) {
  "use strict";
  const HEARTBEAT_LIMIT_MS = 10000;
  const POLL_MS = 3000;
  const REQUEST_TIMEOUT_MS = 4000;

  function finite(value) { return typeof value === "number" && Number.isFinite(value); }
  function age(value, elapsedMs) { return finite(value) ? Math.max(0, value + Math.max(0, elapsedMs) / 1000) : null; }
  function ageLabel(value) { return finite(value) ? `${Math.floor(value)} 秒` : "未取得数据"; }
  function number(value, digits) {
    return finite(value) ? value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "未取得数据";
  }
  function compactNumber(value) {
    return finite(value) ? value.toLocaleString("en-US", { maximumFractionDigits: 8 }) : "未取得数据";
  }
  function dateText(value, zone) {
    if (!value || !Number.isFinite(Date.parse(value))) return "未取得数据";
    return new Intl.DateTimeFormat("sv-SE", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date(value));
  }
  function utc(value) { return value && Number.isFinite(Date.parse(value)) ? `${dateText(value, "UTC")} UTC` : "未取得数据"; }
  function taipei(value) { return value && Number.isFinite(Date.parse(value)) ? `${dateText(value, "Asia/Taipei")} 台北 UTC+8` : "未取得数据"; }
  function health(session, now) {
    if (session.failure) return { ok: false, kind: "error", text: "服务不可达", detail: `本地服务不可达：${session.failure}。已保留的行情不能视为实时数据。` };
    if (session.verifying || session.heartbeatPerf === null) return { ok: false, kind: "warning", text: "正在确认本地服务", detail: "尚未确认本地服务心跳，行情状态未确认。" };
    if (now - session.heartbeatPerf >= HEARTBEAT_LIMIT_MS) return { ok: false, kind: "warning", text: "服务心跳已过期", detail: "超过 10 秒未确认本地服务；已保留的行情不能视为实时数据，正在重新验证。" };
    return { ok: true, kind: "live", text: "本地服务可达", detail: "本地服务心跳已确认。行情是否新鲜请查看各项数据状态与年龄。" };
  }
  function dataState(item, backendOk, elapsedMs, staleSeconds) {
    if (!item || item.status === "missing" || !item.received_at) return { kind: "neutral", text: "未取得数据" };
    if (!backendOk) return { kind: "error", text: "连接未确认 · 保留值" };
    if (item.status === "expired") return { kind: "warning", text: "合约已到期" };
    const sourceAge = age(item.source_age_seconds, elapsedMs);
    const receiptAge = age(item.receipt_age_seconds, elapsedMs);
    const stale = item.status === "stale" || (sourceAge !== null && sourceAge >= staleSeconds) || (receiptAge !== null && receiptAge >= staleSeconds);
    if (item.status === "error") return { kind: "error", text: stale ? "采集失败 · 数据过时" : "采集失败 · 保留值" };
    if (stale) return { kind: "warning", text: "数据过时 · 保留值" };
    if (sourceAge === null || receiptAge === null) return { kind: "warning", text: "新鲜度未确认" };
    if (item.status !== "live") return { kind: "warning", text: "数据状态未确认" };
    return { kind: "live", text: "更新正常" };
  }

  function catalogState(snapshot, backendOk, elapsed) {
    const catalog = snapshot.catalog;
    if (!catalog || catalog.status === "missing" || !catalog.received_at) return "未取得数据";
    // Derive missing age fields from backend UTC, then advance with monotonic time.
    const serverTime = Date.parse(snapshot.server_time);
    const sourceAge = age(finite(catalog.source_age_seconds) ? catalog.source_age_seconds : (serverTime - Date.parse(catalog.source_at)) / 1000, elapsed);
    const receiptAge = age(finite(catalog.receipt_age_seconds) ? catalog.receipt_age_seconds : (serverTime - Date.parse(catalog.received_at)) / 1000, elapsed);
    const stale = catalog.status === "stale" || (sourceAge !== null && sourceAge >= 660) || (receiptAge !== null && receiptAge >= 660);
    let label = "已取得";
    if (!backendOk) label = "连接未确认 · 保留值";
    else if (catalog.status === "error") label = stale ? "更新失败 · 列表过时" : "更新失败 · 保留值";
    else if (stale) label = "列表过时 · 保留值";
    else if (sourceAge === null || receiptAge === null || catalog.status !== "live") label = "列表新鲜度未确认";
    return `${catalog.count} 个 · ${label}`;
  }

  const api = { age, ageLabel, health, dataState, catalogState, dateText, number, compactNumber, HEARTBEAT_LIMIT_MS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (!root.document) return;
  const document = root.document;
  const session = { snapshot: null, snapshotPerf: 0, heartbeatPerf: null, heartbeatAt: null, failure: null, verifying: false };
  const $ = (id) => document.getElementById(id);
  function setText(id, text) { $(id).textContent = text; }
  function badge(element, state) { element.className = `badge badge-${state.kind}`; element.textContent = state.text; }
  function make(tag, text, className) { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (className) element.className = className; return element; }
  function detail(id, text) { setText(id, text || ""); $(id).hidden = !text; }
  function addTime(parent, value) { parent.append(make("span", utc(value))); if (value) parent.append(make("span", taipei(value), "secondary")); }
  function updateScrollHint() {
    const region = $("options-scroll");
    $("table-scroll-hint").hidden = region.scrollWidth <= region.clientWidth;
  }
  function render() {
    const now = root.performance.now();
    const backend = health(session, now);
    badge($("backend-status"), backend);
    setText("connection-notice", backend.detail);
    $("connection-notice").className = `connection-notice${backend.kind === "error" ? " is-error" : backend.kind === "warning" ? " is-warning" : ""}`;
    setText("heartbeat", session.heartbeatAt ? `${utc(session.heartbeatAt)} · ${ageLabel((now - session.heartbeatPerf) / 1000)}前` : "尚未确认");
    const state = session.snapshot;
    if (!state) { updateScrollHint(); return; }
    const elapsed = now - session.snapshotPerf;
    const stale = finite(state.stale_seconds) && state.stale_seconds > 0 ? state.stale_seconds : 60;
    const index = state.index;
    const collector = state.collector || {};
    const dataConnected = backend.ok && collector.running === true;
    badge($("index-status"), dataState(index, dataConnected, elapsed, stale));
    setText("index-price", index && finite(index.price) ? number(index.price, 2) : "—");
    setText("index-source", index ? utc(index.source_at) : "未取得数据");
    setText("index-received", index ? utc(index.received_at) : "未取得数据");
    setText("index-age", index ? `${ageLabel(age(index.source_age_seconds, elapsed))} / ${ageLabel(age(index.receipt_age_seconds, elapsed))}` : "未取得数据");
    detail("index-error", index && index.error);
    setText("collection", collector.last_success_at ? `${utc(collector.last_success_at)} · 第 ${state.sequence} 轮` : "未取得数据");
    setText("catalog", catalogState(state, dataConnected, elapsed));
    setText("refresh", `采集约 ${state.refresh_seconds} 秒 / 过时 ${stale} 秒`);
    detail("collector-error", !collector.running ? "行情采集未运行，保留数据不代表仍在更新。" : collector.error || (state.catalog && state.catalog.error));
    detail("retry", collector.next_retry_at ? `下次采集尝试：${utc(collector.next_retry_at)}` : null);
    const options = Array.isArray(state.options) ? state.options : [];
    setText("option-count", `${options.length} 个展示合约`);
    const rows = document.createDocumentFragment();
    for (const option of options) {
      const row = make("tr");
      const instrument = make("td");
      instrument.append(make("div", option.instrument_name, "instrument-name"));
      instrument.append(make("span", option.option_type === "call" ? "CALL · 看涨" : "PUT · 看跌", `type-chip type-${option.option_type === "call" ? "call" : "put"}`));
      row.append(instrument);
      const expiry = make("td"); addTime(expiry, option.expires_at); row.append(expiry);
      row.append(make("td", number(option.strike, 0), "number"));
      for (const [field, absent] of [["bid", "无买盘"], ["bid_amount", "—"], ["ask", "无卖盘"], ["ask_amount", "—"]]) {
        const isPrice = field === "bid" || field === "ask";
        const available = finite(option[field]);
        const missing = option.status === "missing" || !option.received_at;
        row.append(make("td", available ? compactNumber(option[field]) : missing ? "未取得数据" : absent, `number ${available && isPrice ? "quote-value" : !available ? "no-quote" : ""}`));
      }
      const times = make("td");
      times.append(make("span", `源 ${utc(option.source_at)}`, "secondary"));
      times.append(make("span", `收 ${utc(option.received_at)}`, "secondary"));
      times.append(make("span", `源龄 ${ageLabel(age(option.source_age_seconds, elapsed))} / 收龄 ${ageLabel(age(option.receipt_age_seconds, elapsed))}`, "secondary"));
      row.append(times);
      const status = make("td"); const pill = make("span"); badge(pill, dataState(option, dataConnected, elapsed, stale)); status.append(pill);
      if (option.error) status.append(make("div", option.error, "row-error"));
      row.append(status); rows.append(row);
    }
    if (!options.length) { const row = make("tr"); const cell = make("td", "未取得数据", "empty-state"); cell.colSpan = 9; row.append(cell); rows.append(row); }
    $("options-body").replaceChildren(rows);
    updateScrollHint();
    const integrations = state.integrations || {};
    for (const item of ["account", "backtest", "agent"]) setText(`${item}-status`, integrations[item] || "状态未确认");
    const codex = integrations.codex;
    setText("codex-status", codex ? `${codex.installed ? codex.version || "已安装，版本未确认" : "未检测到安装"}；${codex.login_status || "登录状态未确认"}` : "状态未确认");
    setText("codex-checked", codex && codex.checked_at ? `检查时间：${utc(codex.checked_at)}；本阶段未运行模型任务。` : "本阶段未运行模型任务。");
  }

  let pollTimer = null;
  let activeController = null;
  let retryImmediately = false;
  async function poll() {
    if (activeController) return;
    root.clearTimeout(pollTimer);
    const controller = new AbortController(); activeController = controller;
    const timeout = root.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await root.fetch("/api/state", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const snapshot = await response.json();
      if (!snapshot || !snapshot.collector || !Array.isArray(snapshot.options) || !snapshot.server_time || !Number.isFinite(Date.parse(snapshot.server_time))) throw new Error("服务返回的数据格式无效");
      session.snapshot = snapshot;
      session.snapshotPerf = root.performance.now();
      session.heartbeatPerf = session.snapshotPerf;
      session.heartbeatAt = snapshot.server_time;
      session.failure = null;
      session.verifying = false;
    } catch (error) {
      session.failure = error.name === "AbortError" ? "请求超时或连接已中断" : error.message || "连接失败";
    } finally {
      root.clearTimeout(timeout); activeController = null; render();
      const wait = retryImmediately ? 0 : POLL_MS; retryImmediately = false;
      pollTimer = root.setTimeout(poll, wait);
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    session.verifying = true; session.failure = null;
    render();
    root.clearTimeout(pollTimer);
    if (activeController) { retryImmediately = true; activeController.abort(); }
    else poll();
  });
  render();
  root.setInterval(render, 1000);
  poll();
})(typeof window === "undefined" ? globalThis : window);

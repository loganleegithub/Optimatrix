/* Browser reads saved state; only explicit button events submit remote work. */
(function () {
  "use strict";
  const POLL_MS = 3000;
  const TIMEOUT_MS = 4000;
  const HEARTBEAT_MS = 10000;
  const $ = (id) => document.getElementById(id);
  const session = { snapshot: null, heartbeat: null, failure: null, verifying: true, posting: false, selected: null };
  const activeStatuses = new Set(["queued", "pending", "running", "submitted", "submitting", "fetching", "checking"]);
  const labels = { queued: "等待运行", pending: "等待运行", running: "正在运行", submitted: "已提交服务", submitting: "正在提交服务", fetching: "正在读取结果", checking: "检查中", completed: "服务任务完成", succeeded: "服务任务完成", success: "服务任务完成", failed: "运行失败", error: "运行失败", interrupted: "运行中断", cancelled: "已取消", unknown: "状态未知", submission_unknown: "提交结果未确认", retrieval_failed: "结果读取失败", result_incomplete: "结果不完整", completed_with_gaps: "服务已返回 · 存在数据缺口", unchecked: "尚未检查", ready: "检查完成" };
  let pollTimer = null;
  let pollController = null;
  let retryImmediately = false;
  let historySignature = null;

  function make(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  function text(id, value) { $(id).textContent = value; }
  function present(value) { return value !== null && value !== undefined && value !== ""; }
  function amount(value, unit, missing) { return present(value) ? `${value} ${unit}` : missing; }
  function percent(value) {
    if (!present(value) || !Number.isFinite(Number(value))) return "无法计算";
    return `≈ ${Number(value).toLocaleString("en-US", { maximumFractionDigits: 8, useGrouping: false })} %`;
  }
  function statusLabel(value) { return labels[value] || (value ? `服务状态：${value}` : "状态未确认"); }
  function badge(id, value, kind) { const element = $(id); element.textContent = value; element.className = `badge badge-${kind}`; }
  function statusKind(value) {
    if (["failed", "error", "interrupted", "cancelled", "retrieval_failed"].includes(value)) return "error";
    if (["unknown", "submission_unknown", "result_incomplete", "completed_with_gaps"].includes(value)) return "warning";
    if (activeStatuses.has(value)) return "warning";
    if (["ready", "completed", "succeeded", "success"].includes(value)) return "live";
    return "neutral";
  }
  function timeLabel(value, zone, suffix) {
    if (!value || !Number.isFinite(Date.parse(value))) return null;
    return `${new Intl.DateTimeFormat("sv-SE", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date(value))} ${suffix}`;
  }
  function time(id, value, absent) {
    const element = $(id);
    const utc = timeLabel(value, "UTC", "UTC");
    if (!utc) { element.textContent = absent; return; }
    element.replaceChildren(make("span", utc, "utc-time"), make("span", timeLabel(value, "Asia/Taipei", "台北 UTC+8"), "taipei-time"));
  }
  function list(id, values, empty) {
    const rows = Array.isArray(values) && values.length ? values : [empty];
    $(id).replaceChildren(...rows.map((value) => make("li", String(value))));
  }
  function json(id, value) { text(id, value && typeof value === "object" ? JSON.stringify(value, null, 2) : "未取得数据"); }
  function connected() {
    return !session.failure && !session.verifying && session.heartbeat !== null && performance.now() - session.heartbeat < HEARTBEAT_MS;
  }
  function renderConnection() {
    let detail;
    let kind;
    if (session.failure) {
      kind = "error"; badge("backend-status", "服务不可达", kind);
      detail = `本地服务不可达：${session.failure}。保留最后读取的历史结果；当前运行状态未确认，暂时不能提交任务。`;
    } else if (!connected()) {
      kind = "warning"; badge("backend-status", session.heartbeat === null || session.verifying ? "正在确认本地服务" : "服务心跳已过期", kind);
      detail = "本地服务连接尚未确认。历史结果可保留查看，当前运行状态不能视为已更新。";
    } else {
      kind = "live"; badge("backend-status", "本地服务可达", kind);
      const utc = timeLabel(session.snapshot.server_time, "UTC", "UTC");
      detail = `最后确认：${utc}。连接状态每约 3 秒检查；历史回测不会自动重新提交。`;
    }
    text("connection-notice", detail);
    $("connection-notice").className = `connection-notice${kind === "error" ? " is-error" : kind === "warning" ? " is-warning" : ""}`;
    updateControls();
  }
  function updateControls() {
    const state = session.snapshot;
    const online = connected();
    const capabilities = state && state.capabilities || {};
    const configured = state && state.configuration && state.configuration.configured === true;
    const active = state && state.runs.some((run) => activeStatuses.has(run.status));
    const hasExperiment = state && state.experiment && state.experiment.id === "S2_BTC_LONG_CALL_V1" && state.experiment.request && typeof state.experiment.request === "object";
    const existing = state && state.runs.some((run) => present(run.submitted_at));
    $("check-connection").disabled = !online || session.posting || capabilities.status === "checking" || active;
    $("check-connection").textContent = capabilities.status === "checking" ? "正在检查服务能力…" : "检查连接与服务能力";
    $("start-run").disabled = existing ? session.posting : !online || session.posting || !configured || capabilities.status !== "ready" || active || !hasExperiment;
    $("start-run").textContent = existing ? "查看已有固定回测" : active ? "已有任务正在运行" : "提交一次真实回测";
    text("submit-reason", existing ? "该固定实验已有提交记录，只读取原任务；即使结果未确认也不会自动重复提交。" : !online ? "等待本地服务连接恢复。" : session.posting ? "正在提交请求，请勿重复操作。" : !configured ? "Greeks.live 配置不齐备，请按说明在本地 .env 中填写；不要在聊天中提供密钥。" : capabilities.status !== "ready" ? "先检查连接与服务能力，确认当前支持范围后才能提交。" : active ? "等待当前任务结束；刷新页面只会读取它的状态。" : !hasExperiment ? "固定实验参数尚未取得，暂时不能提交。" : "将按上方固定参数调用 Greeks.live 一次，不进行批量优化。");
  }
  function renderRun(run) {
    $("run-detail").hidden = !run;
    $("no-runs").hidden = !!run;
    if (!run) return;
    text("run-id", run.run_id);
    const hasResultGaps = run.analysis && Array.isArray(run.analysis.gaps) && run.analysis.gaps.length > 0;
    const displayStatus = hasResultGaps && ["completed", "succeeded", "success"].includes(run.status) ? "completed_with_gaps" : run.status;
    badge("run-status", statusLabel(displayStatus), statusKind(displayStatus));
    time("run-created", run.created_at, "未提供");
    time("run-submitted", run.submitted_at, "尚未提交");
    time("run-completed", run.completed_at, "尚未完成");
    text("service-task-id", present(run.service_task_id) ? run.service_task_id : "服务未提供任务标识");
    text("run-error", run.error || ""); $("run-error").hidden = !run.error;
    json("run-request", run.request);
    const result = run.analysis;
    $("analysis-detail").hidden = !result;
    if (!result) {
      text("analysis-status", activeStatuses.has(run.status) ? "任务尚未返回真实结果。" : "未取得真实结果，无法可靠重建 BTC 净收益。");
      return;
    }
    const modelVerified = result.model_ledger_verified === true;
    const netKnown = modelVerified && present(result.btc_net_pnl);
    text("analysis-status", modelVerified ? "已核对一笔模型开平仓账本与服务汇总；未核对真实成交或账户收益。下列现金流均为模型金额，请同时查看数据缺口与限制。" : "无法可靠重建 BTC 净收益。下方保留服务报告结果和已知模型金额，缺失值不按零处理。");
    text("btc-net-pnl", netKnown ? amount(result.btc_net_pnl, "BTC", "无法可靠重建 BTC 净收益") : "无法可靠重建 BTC 净收益");
    $("btc-net-pnl").className = netKnown ? "" : "is-unknown";
    text("premium-paid", amount(result.premium_paid_btc, "BTC", "未提供"));
    text("exit-income", amount(result.exit_income_btc, "BTC", "未提供"));
    text("fees", amount(result.fees_btc, "BTC", "未确认"));
    text("premium-return", modelVerified ? percent(result.premium_return_pct) : "无法计算");
    text("account-return", modelVerified ? percent(result.hypothetical_account_return_pct) : "无法计算");
    text("reported-result", `${result.reported_currency || "币种未知"} / ${present(result.reported_pnl) ? result.reported_pnl : "盈亏未提供"}`);
    text("price-source", result.price_source || "未知；不能称为可成交收益");
    text("fee-assumption", result.fee_assumption || "未知；未确认是否已包含费用");
    text("analysis-method", result.method || "原始结果未提供足够信息，无法可靠重建 BTC 净收益");
    const hasAudit = result.audit && typeof result.audit === "object" && Object.keys(result.audit).length > 0;
    $("analysis-audit").hidden = !hasAudit;
    if (hasAudit) json("analysis-audit-json", result.audit); else text("analysis-audit-json", "");
    list("analysis-gaps", result.gaps, "服务未报告其他缺口；可核对范围仍以所列原始字段、计量方法与假设为限。");
    const rows = document.createDocumentFragment();
    for (const item of Array.isArray(result.rows) ? result.rows : []) {
      const row = make("tr");
      row.append(make("td", item.date || "时间未提供"), make("td", item.description || "说明未提供"), make("td", present(item.amount_btc) ? item.amount_btc : "无法重建", "number"));
      rows.append(row);
    }
    if (!rows.childNodes.length) {
      const row = make("tr"); const cell = make("td", "没有可展示的模型 BTC 现金流，未完成模型逐笔核账。", "empty-state"); cell.colSpan = 3; row.append(cell); rows.append(row);
    }
    $("cashflow-rows").replaceChildren(rows);
  }
  function renderSnapshot() {
    const state = session.snapshot;
    if (!state) return;
    text("storage-error", state.storage_error || "");
    $("storage-error").hidden = !state.storage_error;
    const configuration = state.configuration || {};
    badge("configuration-status", configuration.configured ? "配置已齐备" : "配置未齐备", configuration.configured ? "live" : "warning");
    text("configuration-reason", configuration.reason || (configuration.configured ? "已检测到必要配置，凭据仅由后端消费；齐备不代表认证已经成功。" : "必要配置缺失，公共行情功能仍可使用。"));
    const capability = state.capabilities || {};
    badge("capability-status", statusLabel(capability.status || "unchecked"), statusKind(capability.status));
    text("capability-reason", capability.reason || "尚未取得当前服务的能力确认信息。");
    time("capability-checked", capability.checked_at, "未检查");
    const coverage = capability.coverage;
    text("coverage", coverage && coverage.start_date && coverage.end_date ? `${coverage.start_date} 至 ${coverage.end_date}` : "未确认");
    list("capability-facts", capability.facts, "未取得确认信息。");
    list("capability-unknowns", capability.unknowns, "未报告其他限制；实际可核对范围以本次结果为准。");
    const experiment = state.experiment || {};
    text("experiment-title", experiment.title || "等待服务返回任务定义");
    text("experiment-description", experiment.description || "未取得任务说明。");
    text("experiment-id", experiment.id || "未取得数据");
    json("experiment-request", experiment.request);
    list("experiment-assumptions", experiment.assumptions, "未取得假设说明。");
    const runs = state.runs;
    text("run-count", `${runs.length} 次已保存运行`);
    text("no-runs", "尚无已保存的运行记录。检查配置后，可提交一次固定参数回测。");
    if (!runs.some((run) => run.run_id === session.selected)) session.selected = runs.length ? runs[0].run_id : null;
    const signature = JSON.stringify(runs.map((run) => [run.run_id, run.status, run.created_at]));
    if (historySignature !== signature) {
      const options = runs.map((run) => {
        const created = timeLabel(run.created_at, "UTC", "UTC") || "时间未提供";
        const option = make("option", `${created} · ${statusLabel(run.status)} · ${run.run_id}`); option.value = run.run_id; return option;
      });
      if (!options.length) { const option = make("option", "尚无运行记录"); option.value = ""; options.push(option); }
      $("run-select").replaceChildren(...options);
      historySignature = signature;
    }
    $("run-select").disabled = !runs.length;
    $("run-select").value = session.selected || "";
    renderRun(runs.find((run) => run.run_id === session.selected));
    renderConnection();
  }
  async function poll() {
    if (pollController) return;
    clearTimeout(pollTimer);
    const controller = new AbortController(); pollController = controller;
    const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch("/api/backtests", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const state = await response.json();
      if (!state || !state.server_time || !Number.isFinite(Date.parse(state.server_time)) || !Array.isArray(state.runs) || !state.configuration || !state.capabilities || typeof state.csrf_token !== "string") throw new Error("状态响应格式无效");
      session.snapshot = state; session.heartbeat = performance.now(); session.failure = null; session.verifying = false;
      renderSnapshot();
    } catch (error) {
      session.failure = error.name === "AbortError" ? "请求超时或连接中断" : error.message || "连接失败";
    } finally {
      clearTimeout(timeout); pollController = null; renderConnection();
      pollTimer = setTimeout(poll, retryImmediately ? 0 : POLL_MS); retryImmediately = false;
    }
  }
  async function post(path, body) {
    if (session.posting || !connected() || !session.snapshot) return;
    session.posting = true; updateControls();
    const message = $("action-message"); message.hidden = false; message.className = "action-message";
    message.textContent = "正在向本地后端提交请求…";
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": session.snapshot.csrf_token }, body: JSON.stringify(body), signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      if (!result.run_id && !result.status) throw new Error("提交响应不完整，操作结果尚未确认，请先查看历史状态");
      if (result.run_id) session.selected = result.run_id;
      message.textContent = result.run_id ? `已受理运行 ${result.run_id}。正在读取实际状态与结果；受理不代表回测完成。` : "已受理连接与服务能力检查，等待返回确认信息。";
    } catch (error) {
      message.className = "action-message is-error";
      message.textContent = error.name === "AbortError" || error instanceof TypeError ? "提交结果未确认：连接中断或请求超时。请先查看已保存记录与服务状态，不要立即重复提交。" : `操作未完成：${error.message || "请求失败"}`;
    } finally {
      clearTimeout(timeout); session.posting = false; updateControls();
      if (pollController) retryImmediately = true; else poll();
    }
  }
  $("check-connection").addEventListener("click", () => { if (!$("check-connection").disabled) post("/api/backtests/check-connection", {}); });
  $("start-run").addEventListener("click", () => {
    if ($("start-run").disabled) return;
    const existing = session.snapshot && session.snapshot.runs.find((run) => present(run.submitted_at));
    if (existing) {
      session.selected = existing.run_id; $("run-select").value = existing.run_id; renderRun(existing);
      $("results-title").scrollIntoView({ behavior: "smooth", block: "start" });
    } else post("/api/backtests", { experiment_id: "S2_BTC_LONG_CALL_V1" });
  });
  $("run-select").addEventListener("change", () => { session.selected = $("run-select").value; if (session.snapshot) renderRun(session.snapshot.runs.find((run) => run.run_id === session.selected)); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    session.verifying = true; session.failure = null; renderConnection(); clearTimeout(pollTimer);
    if (pollController) { retryImmediately = true; pollController.abort(); } else poll();
  });
  setInterval(renderConnection, 1000);
  renderConnection(); poll();
})();

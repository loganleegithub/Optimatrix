/* Read-only polling; only an explicit authorized click starts a research task. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { config: null, runs: [], detail: null, selected: new URLSearchParams(location.search).get("research_id"), posting: false, online: false, lastReceived: null, startKey: null, questionInitialized: false };
  const labels = { local_revalidation: "本地结论重新校验", model_ledger_verified: "BTC 模型账本已核对", unreconciled: "BTC 模型账本尚未核对", stop_requested: "已请求停止", completed_with_gaps: "回测已完成 · 存在数据缺口", accounting_refreshed: "已更新确定性金额核对", requesting_experiment: "申请并校验实验", forming_conclusion: "形成并校验结论", tool_failed: "回测工具执行失败", usage_limit: "订阅额度不足", authentication_failed: "ChatGPT 登录失效", internal_error: "本地研究程序错误", pending: "等待执行", done: "已完成该步骤", model_interrupted: "模型调用已中断", queued: "等待开始", preparing: "准备输入", model_running: "模型运行中", running: "研究运行中", request_experiment: "请求实验", waiting_backtest: "等待回测结果", reading_result: "读取结果", finalizing: "形成结论", completed: "研究完成", stopped: "已停止", stopping: "正在停止", cancelled: "已停止", paused: "已暂停 · 可检查后继续", needs_authorization: "预算已用完 · 需继续授权", budget_exhausted: "预算已用完", failed: "研究失败", model_failed: "模型调用失败", output_invalid: "输出未通过校验", invalid_output: "输出未通过校验", model_timeout: "模型调用超时", task_timeout: "研究任务超时", timed_out: "研究任务超时", subscription_exhausted: "订阅额度不足", login_required: "需要重新登录", model_unavailable: "固定模型不可用", blocked: "研究受阻", submission_unknown: "回测提交结果未知", retrieval_failed: "回测结果读取失败", interrupted: "研究已中断", succeeded: "已完成", reused: "复用已有结果", submitted: "已提交", requested: "已提出", validated: "已校验", rejected: "已拒绝", not_submitted: "未创建远端任务", unrecoverable: "结果不可恢复" };
  let pollTimer = null;
  let polling = false;
  let forcePoll = false;
  let pendingSubmission = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem("optimatrix-pending-research") || "null");
    if (saved && typeof saved.question === "string" && typeof saved.key === "string" && saved.key.length <= 128) pendingSubmission = saved;
  } catch (_) { /* Storage may be unavailable; backend remains the authority. */ }
  function clearPending() { state.startKey = null; pendingSubmission = null; try { sessionStorage.removeItem("optimatrix-pending-research"); } catch (_) {} }
  function make(tag, value, className) { const node = document.createElement(tag); if (value !== undefined) node.textContent = String(value); if (className) node.className = className; return node; }
  function text(id, value) { $(id).textContent = value; }
  function present(value) { return value !== null && value !== undefined && value !== ""; }
  function display(value, fallback = "未取得") { return present(value) ? typeof value === "object" ? JSON.stringify(value, null, 2) : String(value) : fallback; }
  function status(value) { return labels[value] || (value ? `状态：${value}` : "状态未确认"); }
  function badge(node, value, good) { node.textContent = value; node.className = `badge badge-${good === true ? "live" : good === false ? "warning" : "neutral"}`; }
  function time(value) { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC") : "时间未提供"; }
  function jsonNode(title, value) { const details = make("details", undefined, "json-detail"); details.append(make("summary", title), make("pre", display(value))); return details; }
  function list(values, empty) { const ul = make("ul", undefined, "plain-list"); for (const value of Array.isArray(values) && values.length ? values : [empty]) ul.append(make("li", display(value))); return ul; }
  function link(runId) { const anchor = make("a", runId); anchor.href = `/backtest?run_id=${encodeURIComponent(runId)}`; return anchor; }
  function key() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
  function metricList(values) { const dl = make("dl", undefined, "evidence-metrics"); for (const [label, value] of values) { const row = make("div"); row.append(make("dt", label), make("dd", display(value, "未知 / 不支持核对"))); dl.append(row); } return dl; }
  function amount(value) { return present(value) ? `${value} BTC` : "未知 / 不支持核对"; }
  function feeComparisonTable(comparison) {
    const section = make("div", undefined, "fee-comparison");
    section.append(make("h4", "同一实验的费用比较"), make("p", `模型毛盈亏（扣费前）：${amount(comparison.gross_pnl_btc)}。其他价格、头寸和日期保持不变。`));
    const scroll = make("div", undefined, "table-scroll fee-table-scroll");
    scroll.tabIndex = 0; scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", "基础费用与较高费用的模型结果比较");
    const table = make("table", undefined, "fee-table"), head = make("thead"), headings = make("tr"), body = make("tbody");
    table.append(make("caption", "由程序根据已核对的同一模型账本计算；不是新增远端回测", "sr-only"));
    for (const label of ["比较指标", "基础费用假设", "较高费用假设"]) { const cell = make("th", label); cell.scope = "col"; headings.append(cell); }
    head.append(headings);
    const percentage = (value) => present(value) && Number.isFinite(Number(value)) ? `≈ ${Number(value).toLocaleString("en-US", { maximumFractionDigits: 4, useGrouping: false })} %` : "不适用（毛收益不为正）";
    const rows = [
      ["每次开平仓费率", "base_fee_bp", "higher_fee_bp", (value) => `${display(value)} bp`],
      ["模型费用合计", "base_fees_btc", "higher_fees_btc", amount],
      ["扣费后模型净盈亏", "base_net_btc", "higher_net_btc", amount],
      ["费用消耗毛收益的比例", "gross_profit_consumed_base_pct", "gross_profit_consumed_higher_pct", percentage],
      ["费用占累计开仓权利金", "base_cost_as_premium_pct", "higher_cost_as_premium_pct", percentage]
    ];
    for (const [label, baseField, higherField, format] of rows) {
      const row = make("tr"), heading = make("th", label); heading.scope = "row"; row.append(heading);
      for (const field of [baseField, higherField]) { const cell = make("td", format(comparison[field])); if (present(comparison[field])) cell.title = `原始记录值：${comparison[field]}`; row.append(cell); }
      body.append(row);
    }
    table.append(head, body); scroll.append(table); section.append(scroll);
    section.append(make("p", `较高费用额外消耗：${amount(comparison.incremental_cost_btc)}。百分比仅作显示舍入，完整精度保留在下方记录。`, "fineprint"));
    section.append(make("p", comparison.ratio_note || "毛收益不为正时不计算成本消耗毛收益比例。", "fineprint"));
    return section;
  }
  function evidenceField(evidence, path) {
    if (typeof path !== "string" || !/^[a-zA-Z0-9_.]+$/.test(path)) return undefined;
    let value = evidence;
    for (const part of path.split(".")) {
      if (["__proto__", "prototype", "constructor"].includes(part) || value === null || typeof value !== "object" || !Object.prototype.hasOwnProperty.call(value, part)) return undefined;
      value = value[part];
    }
    return value;
  }
  function configSnapshot() { return state.config && state.config.configuration || {}; }
  function controls() {
    const ready = state.online && state.config && state.config.availability && state.config.availability.ready === true;
    const active = state.runs.some((run) => run.can_stop === true || ["queued", "preparing", "running", "model_running", "requesting_experiment", "waiting_backtest", "reading_result", "forming_conclusion", "finalizing", "stopping"].includes(run.status));
    $("research-question").disabled = !state.config || state.posting;
    $("use-example").disabled = !state.config || state.posting;
    $("approve-budget").disabled = !ready || active || state.posting;
    $("start-research").disabled = !ready || active || state.posting || !$("approve-budget").checked || !$("research-question").value.trim();
    text("start-reason", !state.online ? "本地服务连接未确认，暂时不能开始或恢复。" : !ready ? state.config.availability && state.config.availability.reason || "研究配置或权限尚未就绪。" : active ? "已有研究正在运行；请等待结束或停止该任务。" : state.posting ? "正在提交本地操作，请勿重复点击。" : !$("research-question").value.trim() ? "请填写本次研究问题。" : !$("approve-budget").checked ? "请核对问题、固定模型、工具范围和预算，然后勾选本次研究授权。" : "开始后由后端执行预算上限；页面关闭不影响已获准的任务。");
    $("stop-research").disabled = !state.online || state.posting || !state.detail || state.detail.can_stop !== true;
    $("resume-research").disabled = !state.online || state.posting || !state.detail || state.detail.can_resume !== true;
  }
  function renderConfig() {
    const c = configSnapshot(), availability = state.config.availability || {}, limits = c.limits || {};
    badge($("researcher-availability"), availability.ready ? "可开始研究" : "尚未就绪", availability.ready === true);
    text("availability-reason", availability.reason || "尚无可用性说明。");
    text("config-model", `${display(c.model)} / ${display(c.reasoning_effort)} · ${c.speed === "standard" ? "标准速度" : display(c.speed, "速度未提供")}`);
    text("config-prompt", `${display(c.prompt_version)} / ${display(c.output_schema_version)}`);
    text("config-cli", `${display(availability.cli_version)} / ${display(availability.login_status)}`);
    text("config-isolation", display(availability.isolation_status, "未确认，不能宣称已经隔离"));
    text("config-tools", Array.isArray(c.allowed_tools) ? c.allowed_tools.join("、") : display(c.allowed_tools));
    text("config-capabilities", display(state.config.capabilities));
    const capability = state.config.capabilities || {}, ranges = capability.ranges || {}, coverage = capability.coverage;
    const range = (field) => Array.isArray(ranges[field]) ? ranges[field].join(" 至 ") : display(ranges[field], "范围未确认");
    $("capabilities-readable").replaceChildren(...[
      "BTC 币本位期权；单腿买方，无对冲，reopen 模式。",
      `Call / Put；Delta ${range("delta")}；目标期限 ${range("expiry")} 天。`,
      `名义数量 ${range("quantity")} BTC；每次开平仓费用 ${range("option_transaction_cost_bp")} bp。`,
      `实验窗口 ${range("window_days")} 天；选择 UTC 估值时刻和入场星期。`,
      coverage && coverage.start_date && coverage.end_date ? `服务数据日期：${coverage.start_date} 至 ${coverage.end_date}。` : "当前服务数据日期范围尚未确认。",
      capability.mode_description || "模式细节以完整工具记录为准。"
    ].map((value) => make("li", value)));
    text("capabilities-pricing", "Greeks.live SABR/WV4 曲面模型估值；不是可成交买卖价。没有盘口深度、滑点或账户实际费率。费用按 BTC 名义数量计算。");
    text("config-json", display(c));
    text("budget-summary", `本次最多 ${display(limits.model_calls)} 次模型调用（含输出纠正），${display(limits.backtest_creations)} 次新远端回测创建尝试。\n模型单次超时 ${display(limits.model_timeout_seconds)} 秒；任务超时 ${display(limits.task_timeout_seconds)} 秒。普通 GET 轮询不计作回测创建。`);
    if (!state.questionInitialized && typeof state.config.default_question === "string") {
      $("research-question").value = pendingSubmission ? pendingSubmission.question : state.config.default_question;
      if (pendingSubmission) state.startKey = pendingSubmission.key;
      state.questionInitialized = true;
    }
  }
  function renderHistory() {
    text("research-count", `${state.runs.length} 项已保存研究`);
    if (!state.runs.some((run) => run.research_id === state.selected)) state.selected = state.runs.length ? state.runs[0].research_id : null;
    const select = $("research-select");
    const signature = JSON.stringify(state.runs.map((run) => [run.research_id, run.status, run.created_at]));
    if (select.dataset.signature !== signature) {
      const options = state.runs.map((run) => { const option = make("option", `${time(run.created_at)} · ${status(run.status)} · ${run.research_id}`); option.value = run.research_id; return option; });
      if (!options.length) { const option = make("option", "尚无研究任务"); option.value = ""; options.push(option); }
      select.replaceChildren(...options); select.dataset.signature = signature;
    }
    select.value = state.selected || ""; select.disabled = !state.runs.length;
    $("no-research").hidden = !!state.selected;
    text("no-research", "尚无已保存研究。上方填写问题并批准本次预算后，可开始研究。");
    if (!state.selected) { state.detail = null; $("research-detail").hidden = true; }
  }
  function renderEvents(events) {
    const items = (Array.isArray(events) ? events : []).map((event) => { const item = make("li"); item.append(make("time", `${time(event.at)} · ${labels[event.kind] || display(event.kind, "事件")}`), make("span", display(event.message))); return item; });
    if (!items.length) items.push(make("li", "尚无已保存执行事件。"));
    $("research-events").replaceChildren(...items);
  }
  function renderActions(actions) {
    const cards = (Array.isArray(actions) ? actions : []).map((action, index) => {
      const card = make("article", undefined, "action-card"), top = make("div", undefined, "action-topline"), mark = make("span");
      const kind = typeof action.action === "string" ? action.action : action.action && action.action.type || "工具动作";
      top.append(make("strong", `步骤 ${action.step || index + 1} · ${kind}`)); badge(mark, action.reused ? "复用已有结果 · 未创建新任务" : status(action.status)); top.append(mark); card.append(top);
      card.append(make("span", "Agent 简短说明", "source-label"), make("p", action.model_explanation || "未提供说明。"));
      if (action.plan) card.append(jsonNode("提交前保存的假设与比较计划", action.plan));
      card.append(make("span", "程序记录的实际动作", "source-label"));
      if (action.run_id) card.append(link(action.run_id));
      card.append(jsonNode("工具请求与实际参数", { action: action.action, request: action.request, status: action.status, reused: action.reused, run_id: action.run_id, error: action.error }));
      return card;
    });
    $("research-actions").replaceChildren(...(cards.length ? cards : [make("p", "尚无实验提案或工具动作。", "muted-copy")]));
  }
  function renderEvidence(evidence, metrics) {
    const trusted = new Map((Array.isArray(metrics) ? metrics : []).map((item) => [item.run_id, item]));
    const cards = (Array.isArray(evidence) ? evidence : []).map((item) => {
      const card = make("article", undefined, "evidence-card"), top = make("div", undefined, "action-topline"), tag = make("span");
      top.append(link(item.run_id)); badge(tag, status(item.status)); top.append(tag); card.append(top);
      card.append(metricList([["服务任务 ID", item.service_task_id], ["结果出处", item.source], ["金额计量状态", item.accounting && ((item.accounting.status ? status(item.accounting.status) : null) || (item.accounting.model_ledger_verified === true ? "模型账本已核对" : "模型金额未核对"))]]));
      const bound = trusted.get(item.run_id), accounting = bound && bound.accounting;
      if (accounting) {
        card.append(make("h4", "程序绑定的模型金额"), metricList([["模型账本核对", accounting.model_ledger_verified === true ? "已核对受支持的模型记录" : "未完成核对"], ["BTC 净盈亏", accounting.model_ledger_verified === true ? amount(accounting.btc_net_pnl) : "未核对，不能展示为已确认收益"], ["权利金支出", amount(accounting.premium_paid_btc)], ["退出收入", amount(accounting.exit_income_btc)], ["费用", amount(accounting.fees_btc)], ["价格来源", accounting.price_source], ["服务汇总币种 / 盈亏", `${display(accounting.reported_currency, "未知")} / ${display(accounting.reported_pnl, "未提供")}`]]));
      } else card.append(make("p", "没有后端绑定的确定性金额；不能将模型自报金额当作已核对结果。", "muted-copy"));
      if (bound && bound.fee_comparison) {
        const comparison = bound.fee_comparison;
        if (accounting && accounting.model_ledger_verified === true && comparison.status === "computed_from_verified_ledger" && comparison.run_id === item.run_id) card.append(feeComparisonTable(comparison));
        else card.append(make("p", "费用比较尚未通过模型账本及记录身份验证，未显示为已确认金额。", "muted-copy"));
        card.append(jsonNode("程序费用比较的完整精度记录（BTC 模型口径）", comparison));
      }
      card.append(list(item.gaps, "未报告其他缺口；结果仍属于模型回测，不代表可成交优势。"), jsonNode("证据实际请求与计量记录", item));
      return card;
    });
    $("research-evidence").replaceChildren(...(cards.length ? cards : [make("p", "尚无实际结果证据。", "muted-copy")]));
  }
  function renderFinal(final, evidence) {
    $("final-section").hidden = !final;
    if (!final) { $("final-result").replaceChildren(); return; }
    const available = new Map((evidence || []).map((item) => [item.run_id, item]));
    const ids = new Set(available.keys());
    const fragment = document.createDocumentFragment();
    fragment.append(make("p", display(final.verdict, "未提供结论分类"), "final-verdict"));
    const summary = make("div", undefined, "final-summary"); summary.append(make("p", display(final.conclusion), "final-copy")); fragment.append(summary);
    if (final.program_notes && (!Array.isArray(final.program_notes) || final.program_notes.length)) {
      const notes = make("div", undefined, "program-notes");
      notes.append(make("h4", "程序口径说明"), list(Array.isArray(final.program_notes) ? final.program_notes : [final.program_notes], "未提供"));
      fragment.append(notes);
    }
    for (const [title, value] of [["研究问题", final.question], ["事先假设", final.hypothesis]]) fragment.append(make("h4", title), make("p", display(value), "final-copy"));
    fragment.append(make("h4", "实际使用的实验记录"));
    const experiments = make("ul", undefined, "plain-list");
    for (const experiment of Array.isArray(final.experiments) ? final.experiments : []) {
      const li = make("li");
      if (ids.has(experiment.run_id)) li.append(link(experiment.run_id), make("span", ` · ${display(experiment.role, "实验")}`));
      else li.append(make("span", `不可验证的实验引用：${display(experiment.run_id)}。不能视为已执行证据。`));
      experiments.append(li);
    }
    if (!experiments.childNodes.length) experiments.append(make("li", "未列出已执行实验。")); fragment.append(experiments);
    fragment.append(make("h4", "证据引用"));
    for (const claim of Array.isArray(final.claims) ? final.claims : []) {
      const p = make("p", undefined, "final-copy evidence-claim");
      const fieldValue = evidenceField(available.get(claim.run_id), claim.field);
      if (ids.has(claim.run_id) && fieldValue !== undefined) p.append(make("span", `${display(claim.text)}\n`), link(claim.run_id), make("span", ` · 字段 ${display(claim.field)} · 记录值：${display(fieldValue)}`));
      else p.append(make("span", `引用未验证：${display(claim.run_id)} / ${display(claim.field)}。此项未作为已证实事实展示。`));
      fragment.append(p);
    }
    for (const [title, values, empty] of [["主要反例", final.counterexamples, "未提供；不能因此认定不存在反例。"], ["未知项", final.unknowns, "未列出；不代表所有数据均已取得。"], ["仅为建议、尚未执行的实验", final.suggested_experiments, "没有另列建议实验。"]]) fragment.append(make("h4", title), list(values, empty));
    fragment.append(make("h4", "最小下一步"), make("p", display(final.next_step), "final-copy"), make("p", "以上是研究候选建议；未批准任何实盘策略。模型账本核对不等于真实成交核对。", "fineprint"));
    $("final-result").replaceChildren(fragment);
  }
  function renderDetail() {
    const run = state.detail; $("research-detail").hidden = !run; if (!run) return;
    text("research-id", run.research_id); badge($("research-status"), status(run.status), run.status === "completed" ? true : false);
    text("saved-question", run.question || "问题未提供");
    const b = run.budget || {}; text("run-budget", `已使用模型调用 ${display(b.model_calls_used)} / ${display(b.model_calls_limit)}；新远端创建尝试 ${display(b.backtest_creations_used)} / ${display(b.backtest_creations_limit)}。\n任务创建：${time(run.created_at)}；最后更新：${time(run.updated_at)}。`);
    text("research-error", display(run.error, "")); $("research-error").hidden = !run.error;
    const localRevalidation = run.status === "invalid_output" && run.can_resume;
    text("resume-research", localRevalidation ? "重新校验本地结论" : "继续本次研究");
    text("recovery-reason", run.recovery_reason || (localRevalidation ? "只重新校验已保存的结论，不增加模型调用或远端回测；原始输出与此前拒绝记录继续保留。" : run.can_resume ? "可显式继续本任务；已知服务任务 ID 只继续读取，提交结果未知时不会自动重发。" : "停止只结束本任务拥有的本地工作；已经创建的远端任务不会被撤销。重启后请依据保存状态显式继续。"));
    text("saved-config", display({ configuration_snapshot: run.configuration_snapshot, input_references: run.input_references || run.input_refs }));
    renderEvents(run.events); renderActions(run.actions); renderEvidence(run.evidence, run.verified_metrics); renderFinal(run.final, run.evidence); controls();
  }
  async function request(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal });
      let payload;
      try { payload = await response.json(); }
      catch (_) { throw new Error(response.ok ? "本地研究状态格式无效" : `本地研究接口不可用（HTTP ${response.status}）`); }
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    }
    finally { clearTimeout(timer); }
  }
  async function poll() {
    if (polling) { forcePoll = true; return; } polling = true; clearTimeout(pollTimer);
    try {
      const [config, history] = await Promise.all([request("/api/research/config"), request("/api/research/runs")]);
      if (!config.configuration || !config.availability || typeof config.csrf_token !== "string" || !Array.isArray(history.runs)) throw new Error("研究状态响应格式无效");
      state.config = config; state.runs = history.runs; state.online = true; state.lastReceived = performance.now(); renderConfig(); renderHistory();
      if (state.selected) {
        const selected = state.selected, detail = await request(`/api/research/runs/${encodeURIComponent(selected)}`);
        if (detail.research_id !== selected || typeof detail.status !== "string") throw new Error("研究明细响应格式无效");
        if (selected === state.selected) { state.detail = detail; renderDetail(); }
      }
      $("history-error").hidden = true; badge($("backend-status"), "本地服务可达", true);
      text("connection-notice", `最后确认：${time(config.server_time)}。状态每约 3 秒读取；后台研究独立于本页。`); $("connection-notice").className = "connection-notice";
    } catch (error) {
      state.online = false; badge($("backend-status"), "服务状态未确认", false);
      text("connection-notice", `本地状态读取失败：${error.name === "AbortError" ? "请求超时" : error.message}。保留历史内容；其当前运行状态未确认，禁止开始或恢复。`); $("connection-notice").className = "connection-notice is-error";
    } finally { polling = false; controls(); pollTimer = setTimeout(poll, forcePoll ? 0 : 3000); forcePoll = false; }
  }
  async function post(path, body) {
    if (state.posting || !state.online || !state.config) return;
    state.posting = true; controls(); const message = $("action-message"); message.hidden = false; message.className = "action-message"; message.textContent = "正在提交本地操作…";
    try {
      const result = await request(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": state.config.csrf_token }, body: JSON.stringify(body) });
      if (!result.research_id && !result.status) throw new Error("操作响应不完整，请先查看历史记录");
      if (result.research_id) state.selected = result.research_id;
      message.textContent = `操作已受理${result.research_id ? `：${result.research_id}` : ""}。以任务中保存的真实事件与结果为准。`;
      if (path === "/api/research/start") { $("approve-budget").checked = false; clearPending(); }
    } catch (error) { message.className = "action-message is-error"; message.textContent = error.name === "AbortError" || error instanceof TypeError ? "操作结果未确认：请先查看历史状态。重复提交相同问题将沿用本次提交标识，不会据此自动扩大预算。" : `操作未完成：${error.message}`; }
    finally { state.posting = false; controls(); poll(); }
  }
  $("research-question").addEventListener("input", () => { clearPending(); $("approve-budget").checked = false; controls(); });
  $("approve-budget").addEventListener("change", controls);
  $("use-example").addEventListener("click", () => { if (!state.config) return; $("research-question").value = state.config.default_question || ""; $("approve-budget").checked = false; clearPending(); controls(); });
  $("start-research").addEventListener("click", () => {
    if ($("start-research").disabled) return;
    state.startKey = state.startKey || key();
    const question = $("research-question").value.trim();
    try { sessionStorage.setItem("optimatrix-pending-research", JSON.stringify({ key: state.startKey, question })); } catch (_) {}
    post("/api/research/start", { question, approved: true, idempotency_key: state.startKey });
  });
  $("research-select").addEventListener("change", () => { state.selected = $("research-select").value; state.detail = null; $("research-detail").hidden = true; controls(); poll(); });
  $("stop-research").addEventListener("click", () => { if (!$("stop-research").disabled) post(`/api/research/runs/${encodeURIComponent(state.selected)}/stop`, {}); });
  $("resume-research").addEventListener("click", () => { if (!$("resume-research").disabled) post(`/api/research/runs/${encodeURIComponent(state.selected)}/resume`, {}); });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") { state.online = false; controls(); poll(); } });
  setInterval(() => { if (state.lastReceived !== null && performance.now() - state.lastReceived > 15000) { state.online = false; badge($("backend-status"), "服务心跳已过期", false); controls(); } }, 1000);
  controls(); poll();
})();

/* Pure view helpers are also available to the offline verification runner. */
(function (root) {
  "use strict";
  function finiteAmount(value) {
    return (typeof value === "number" || typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)) && Number.isFinite(Number(value));
  }
  function trustedFeeSeries(evidence, metric) {
    if (!evidence || !metric || !evidence.run_id || metric.run_id !== evidence.run_id ||
        !metric.accounting || metric.accounting.model_ledger_verified !== true ||
        !metric.fee_comparison || metric.fee_comparison.status !== "computed_from_verified_ledger" ||
        metric.fee_comparison.run_id !== evidence.run_id || !evidence.fee_comparison) return null;
    const comparison = metric.fee_comparison;
    const fields = ["gross_pnl_btc", "base_net_btc", "higher_net_btc", "base_fee_bp", "higher_fee_bp"];
    if (!fields.every((field) => finiteAmount(comparison[field]) && JSON.stringify(comparison[field]) === JSON.stringify(evidence.fee_comparison[field]))) return null;
    return [
      {label: "扣费前", field: "fee_comparison.gross_pnl_btc", value: comparison.gross_pnl_btc, unit: "BTC"},
      {label: `${comparison.base_fee_bp} bp 后`, field: "fee_comparison.base_net_btc", value: comparison.base_net_btc, unit: "BTC"},
      {label: `${comparison.higher_fee_bp} bp 后`, field: "fee_comparison.higher_net_btc", value: comparison.higher_net_btc, unit: "BTC"}
    ];
  }
  function chartDomain(series) {
    if (!Array.isArray(series) || !series.length || !series.every((row) => finiteAmount(row.value))) return null;
    const values = series.map((row) => Number(row.value)), min = Math.min(0, ...values), max = Math.max(0, ...values);
    return {min, max: max === min ? min + 1 : max};
  }
  const helpers = Object.freeze({trustedFeeSeries, chartDomain});
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.OptimatrixResearchView = helpers;
})(globalThis);

/* Polling is read-only. Research starts or resumes only after an explicit click. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const view = globalThis.OptimatrixResearchView;
  const $ = (id) => document.getElementById(id);
  const state = {
    config: null, workspace: null, runs: [], detail: null,
    selected: new URLSearchParams(location.search).get("research_id"),
    posting: false, online: false, lastReceived: null, startKey: null,
    questionInitialized: false, renderedDetailSignature: null
  };
  const labels = {
    local_revalidation: "本地结论重新校验", model_ledger_verified: "模型账本已核对",
    unreconciled: "模型账本未核对", stop_requested: "已请求停止",
    completed_with_gaps: "完成 · 数据有缺口", accounting_refreshed: "金额核对已更新",
    requesting_experiment: "校验实验", forming_conclusion: "校验结论",
    tool_failed: "回测工具失败", usage_limit: "订阅额度不足", authentication_failed: "登录失效",
    internal_error: "本地程序错误", pending: "等待执行", done: "步骤完成",
    model_interrupted: "模型已中断", queued: "等待开始", preparing: "准备输入",
    model_running: "模型运行中", running: "运行中", request_experiment: "请求实验",
    waiting_backtest: "等待回测", reading_result: "读取结果", finalizing: "形成结论",
    completed: "研究完成", stopped: "已停止", stopping: "正在停止", cancelled: "已停止",
    paused: "已暂停", needs_authorization: "需继续授权", budget_exhausted: "预算已用完",
    failed: "失败", model_failed: "模型调用失败", output_invalid: "输出校验失败",
    invalid_output: "输出校验失败", model_timeout: "模型超时", task_timeout: "任务超时",
    timed_out: "任务超时", subscription_exhausted: "订阅额度不足", login_required: "需重新登录",
    model_unavailable: "固定模型不可用", blocked: "受阻", submission_unknown: "提交结果未知",
    retrieval_failed: "结果读取失败", interrupted: "已中断", succeeded: "已完成",
    reused: "复用结果", submitted: "已提交", requested: "已提出", validated: "已校验",
    rejected: "已拒绝", not_submitted: "未创建远端任务", unrecoverable: "结果不可恢复",
    research_candidate: "研究候选", inconclusive: "未得出结论", validation_gaps: "结论校验有缺口",
    passed: "结构化引用已核对", display_with_gaps: "展示校验有缺口",
    legacy_display_revised: "历史结论派生展示", checked: "引用已核对", derived: "程序派生事实",
    not_connected: "未接入账户", not_authorized: "未获交易授权"
  };
  const fieldUnits = {
    "accounting.btc_net_pnl": "BTC", "accounting.premium_paid_btc": "BTC",
    "accounting.exit_income_btc": "BTC", "accounting.fees_btc": "BTC",
    "accounting.hypothetical_capital_btc": "BTC", "accounting.premium_return_pct": "%",
    "accounting.hypothetical_account_return_pct": "%", "fee_comparison.traded_nominal_btc": "BTC",
    "fee_comparison.gross_pnl_btc": "BTC", "fee_comparison.base_fees_btc": "BTC",
    "fee_comparison.higher_fees_btc": "BTC", "fee_comparison.base_net_btc": "BTC",
    "fee_comparison.higher_net_btc": "BTC", "fee_comparison.incremental_cost_btc": "BTC",
    "fee_comparison.gross_profit_consumed_base_pct": "%",
    "fee_comparison.gross_profit_consumed_higher_pct": "%",
    "fee_comparison.base_cost_as_premium_pct": "%", "fee_comparison.higher_cost_as_premium_pct": "%",
    "fee_comparison.base_fee_bp": "bp", "fee_comparison.higher_fee_bp": "bp"
  };
  let pollTimer = null, polling = false, forcePoll = false, pendingSubmission = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem("optimatrix-pending-research") || "null");
    if (saved && typeof saved.question === "string" && typeof saved.key === "string" && /^[A-Za-z0-9_-]{8,100}$/.test(saved.key)) pendingSubmission = saved;
  } catch (_) { /* Backend remains authoritative when storage is unavailable. */ }

  function make(tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function text(id, value) { const el = $(id); if (el) el.textContent = value; }
  function replace(id, ...nodes) { const el = $(id); if (el) el.replaceChildren(...nodes); }
  function changed(id, value) {
    const el = $(id);
    if (!el) return false;
    const signature = JSON.stringify(value);
    if (el.dataset.renderSignature === signature) return false;
    el.dataset.renderSignature = signature;
    return true;
  }
  function present(value) { return value !== null && value !== undefined && value !== ""; }
  function display(value, fallback = "未取得") {
    return present(value) ? (typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)) : fallback;
  }
  function brief(value, limit = 160) {
    const copy = display(value, "");
    return copy.length > limit ? `${copy.slice(0, limit)}…` : copy;
  }
  function status(value) { return labels[value] || display(value, "状态未确认"); }
  function badge(node, value, good) {
    if (!node) return;
    node.textContent = value;
    node.className = `badge badge-${good === true ? "live" : good === false ? "warning" : "neutral"}`;
  }
  function time(value) {
    return value && Number.isFinite(Date.parse(value))
      ? new Date(value).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC") : "时间未提供";
  }
  function jsonNode(title, value) {
    const details = make("details", undefined, "json-detail");
    details.append(make("summary", title), make("pre", display(value)));
    return details;
  }
  function list(values, empty) {
    const ul = make("ul", undefined, "plain-list");
    const rows = Array.isArray(values) && values.length ? values : [empty];
    for (const row of rows) ul.append(make("li", display(row)));
    return ul;
  }
  function metricList(values, className = "evidence-metrics") {
    const dl = make("dl", undefined, className);
    for (const [label, value] of values) {
      const row = make("div");
      row.append(make("dt", label), make("dd", display(value, "未知")));
      dl.append(row);
    }
    return dl;
  }
  function runLink(runId) {
    const anchor = make("a", display(runId));
    anchor.href = `/backtest?run_id=${encodeURIComponent(runId)}`;
    return anchor;
  }
  function selectResearch(researchId) {
    state.selected = researchId || null;
    state.detail = null;
    state.renderedDetailSignature = null;
    if ($("research-detail")) $("research-detail").hidden = true;
    replace("final-result", make("p", "正在读取所选研究结果…", "muted-copy"));
    replace("research-evidence");
    updateUrl();
    controls();
    poll();
  }
  function researchLink(researchId, label = "查看研究") {
    const anchor = make("a", label);
    anchor.href = `/research?research_id=${encodeURIComponent(researchId)}`;
    anchor.addEventListener("click", (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      selectResearch(researchId);
    });
    return anchor;
  }
  function updateUrl() {
    const url = new URL(location.href);
    if (state.selected) url.searchParams.set("research_id", state.selected);
    else url.searchParams.delete("research_id");
    history.replaceState(null, "", url);
  }
  function amount(value) { return present(value) ? `${value} BTC` : "未知"; }
  function clearPending() {
    state.startKey = null;
    pendingSubmission = null;
    try { sessionStorage.removeItem("optimatrix-pending-research"); } catch (_) {}
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
  function configSnapshot() { return (state.config && state.config.configuration) || {}; }

  function renderWorkspace() {
    const workspace = state.workspace;
    if (!workspace) return;
    const account = workspace.account || {}, strategy = workspace.strategy || {}, agents = workspace.agents || {}, approvals = workspace.approvals || {};
    if (changed("workspace-account", account)) {
    const accountAmount = (value) => present(value) ? amount(value) : account.status === "not_connected" ? "未接入" : "未知";
    const accountNodes = [metricList([
      ["净 BTC 权益", accountAmount(account.net_equity_btc)], ["已实现收益", accountAmount(account.realized_pnl_btc)],
      ["未平仓风险", accountAmount(account.open_risk_btc)], ["剩余权利金预算", accountAmount(account.premium_budget_remaining_btc)]
    ], "account-facts"), make("p", display(account.reason, "账户状态未确认"), "empty-state")];
    if (account.source_at) accountNodes.push(make("p", `账户数据：${time(account.source_at)}`, "fineprint"));
    replace("workspace-account", ...accountNodes);
    }

    if (changed("workspace-strategy", strategy)) {
    const strategyNodes = [metricList([
      ["运行版本", display(strategy.version, "未运行")],
      ["持仓", strategy.positions === null || strategy.positions === undefined ? "未接入" : Array.isArray(strategy.positions) ? `${strategy.positions.length} 项` : display(strategy.positions)],
      ["退出安排", display(strategy.exit_schedule, "未取得")]
    ]), make("p", display(strategy.entry_blocker, "开仓条件未提供"), "empty-state")];
    if (typeof strategy.candidate_count === "number") strategyNodes.push(make("p", strategy.candidate_count > 0 ? `${strategy.candidate_count} 项研究候选通过结论校验` : "暂无通过结论校验的研究候选。", "muted-copy"));
    const candidate = strategy.latest_candidate;
    if (candidate && candidate.research_id) {
      const row = make("div", undefined, "candidate-row");
      row.append(make("strong", status(candidate.status)), make("span", display(candidate.verdict)), researchLink(candidate.research_id, "查看依据"));
      if (candidate.validation_status) row.append(make("span", status(candidate.validation_status), "fineprint"));
      strategyNodes.push(row);
    } else strategyNodes.push(make("p", "尚无完成结论的研究候选。", "muted-copy"));
    replace("workspace-strategy", ...strategyNodes);
    }

    if (changed("workspace-agents", agents)) {
    const active = Array.isArray(agents.active) ? agents.active : [], historyRows = Array.isArray(agents.history) ? agents.history : [];
    const agentNodes = [make("p", active.length ? `${active.length} 个 Agent 正在运行` : "当前没有运行中的 Agent。", "agent-collection-status")];
    const seen = new Set();
    for (const agent of [...active, ...historyRows]) {
      if (!agent || !agent.agent_id || seen.has(agent.agent_id)) continue;
      seen.add(agent.agent_id);
      const row = make("details", undefined, `agent-row${agent.is_active ? " is-active" : ""}`), summary = make("summary"), mark = make("span");
      summary.append(make("strong", display(agent.role, "角色未记录")), make("span", `${display(agent.model, "模型未记录")} / ${display(agent.reasoning_effort, "推理强度未记录")}`));
      badge(mark, status(agent.status), agent.status === "completed");
      summary.append(mark);
      summary.append(make("code", agent.research_id ? agent.research_id.slice(0, 8) : agent.agent_id));
      summary.append(make("time", time(agent.created_at), "fineprint"));
      if (agent.failure) summary.append(make("span", brief(agent.failure, 90), "result-error"));
      else if (agent.result) summary.append(make("span", `判断：${brief(agent.result.verdict, 60)} · ${status(agent.result.validation_status)}`, "agent-outcome"));
      row.append(summary);
      if (agent.research_id) row.append(researchLink(agent.research_id, agent.research_id));
      row.append(make("p", display(agent.question, "问题未记录")));
      if (agent.failure) row.append(make("p", display(agent.failure), "result-error"));
      if (agent.result) row.append(make("p", `${display(agent.result.verdict)} · ${status(agent.result.validation_status)}`, "agent-outcome"));
      const input = agent.inputs || {};
      row.append(metricList([
        ["更新", time(agent.updated_at)], ["Prompt / 输出结构", `${display(agent.prompt_version)} / ${display(agent.schema_version)}`],
        ["输入快照引用", Array.isArray(input.references) ? `${input.references.length} 项` : "未记录"],
        ["工具取得证据", Array.isArray(input.evidence_run_ids) && input.evidence_run_ids.length ? input.evidence_run_ids.join("、") : "未记录证据"],
        ["显式 read_result", Array.isArray(input.read_run_ids) && input.read_run_ids.length ? input.read_run_ids.join("、") : "未记录结果读取"]
      ]));
      if (input.scope) row.append(make("p", input.scope, "fineprint"));
      row.append(jsonNode("已保存输入引用与执行动作", {agent_id: agent.agent_id, inputs: input, actions: agent.actions, budget: agent.budget}));
      agentNodes.push(row);
    }
    if (!seen.size && agents.configured) {
      const configured = agents.configured;
      agentNodes.push(make("p", `可用配置：${display(configured.role)} · ${display(configured.model)} / ${display(configured.reasoning_effort)}`, "fineprint"));
    }
    if (agents.storage_error) agentNodes.push(make("p", display(agents.storage_error), "result-error"));
    replace("workspace-agents", ...agentNodes);
    }

    if (changed("workspace-approvals", approvals)) {
    const approvalNodes = [];
    const pending = Array.isArray(approvals.pending) ? approvals.pending : [];
    if (pending.length) {
      for (const item of pending) approvalNodes.push(jsonNode("待批准事项记录", item));
    } else approvalNodes.push(make("p", "暂无待批准策略。", "empty-state"));
    if (approvals.strategy_approval_status === "requires_s4_authorization") approvalNodes.push(make("p", "策略批准需另行授权 S4。", "fineprint"));
    if (approvals.effect) approvalNodes.push(make("p", approvals.effect, "fineprint"));
    replace("workspace-approvals", ...approvalNodes);
    }
    text("workspace-updated", `状态读取：${time(workspace.server_time)}`);
  }

  function controls() {
    const ready = state.online && state.config && state.config.availability && state.config.availability.ready === true;
    const active = state.runs.some((run) => run.can_stop === true || ["queued", "preparing", "running", "model_running", "requesting_experiment", "waiting_backtest", "reading_result", "forming_conclusion", "finalizing", "stopping"].includes(run.status));
    const question = $("research-question"), approved = $("approve-budget");
    if (question) question.disabled = !state.config || state.posting;
    if ($("use-example")) $("use-example").disabled = !state.config || state.posting;
    if (approved) approved.disabled = !ready || active || state.posting;
    if ($("start-research")) $("start-research").disabled = !ready || active || state.posting || !approved || !approved.checked || !question || !question.value.trim();
    text("start-reason", !state.online ? "连接未确认，暂时不能开始或恢复。"
      : !ready ? (state.config.availability && state.config.availability.reason) || "配置尚未就绪。"
      : active ? "已有研究正在运行。"
      : state.posting ? "正在提交，请勿重复点击。"
      : !question.value.trim() ? "请填写研究问题。"
      : !approved.checked ? "核对问题与预算后，勾选本次授权。"
      : "预算上限由程序执行；关闭页面不会停止任务。");
    if ($("stop-research")) {
      $("stop-research").hidden = !state.detail || state.detail.can_stop !== true;
      $("stop-research").disabled = !state.online || state.posting || !state.detail || state.detail.can_stop !== true;
    }
    if ($("resume-research")) {
      $("resume-research").hidden = !state.detail || state.detail.can_resume !== true;
      $("resume-research").disabled = !state.online || state.posting || !state.detail || state.detail.can_resume !== true;
    }
  }

  function renderConfig() {
    const config = configSnapshot(), availability = state.config.availability || {}, limits = config.limits || {}, capability = state.config.capabilities || {};
    badge($("researcher-availability"), availability.ready ? "可开始研究" : "尚未就绪", availability.ready === true);
    text("availability-reason", availability.reason || "可用性未确认。");
    text("config-model", `${display(config.model)} / ${display(config.reasoning_effort)} · ${display(config.speed, "速度未记录")}`);
    text("config-prompt", `${display(config.prompt_version)} / ${display(config.output_schema_version)}`);
    text("config-cli", `${display(availability.cli_version)} / ${display(availability.login_status)}`);
    text("config-isolation", display(availability.isolation_status, "未确认"));
    text("config-tools", Array.isArray(config.allowed_tools) ? config.allowed_tools.join("、") : display(config.allowed_tools));
    text("config-capabilities", display(capability));
    const fixed = capability.fixed || {}, ranges = capability.ranges || {}, rows = [];
    if (Object.keys(fixed).length) rows.push(`固定范围：${Object.entries(fixed).map(([field, value]) => `${field}=${display(value)}`).join(" · ")}`);
    for (const [field, unit] of [["delta", ""], ["expiry", " 天"], ["quantity", " BTC"], ["option_transaction_cost_bp", " bp"], ["window_days", " 天"]]) {
      if (Array.isArray(ranges[field])) rows.push(`${field}：${ranges[field].join(" 至 ")}${unit}`);
    }
    if (capability.coverage) rows.push(`数据日期：${display(capability.coverage.start_date)} 至 ${display(capability.coverage.end_date)}`);
    if (capability.mode_description) rows.push(capability.mode_description);
    replace("capabilities-readable", ...rows.map((row) => make("li", row)));
    if (!rows.length) replace("capabilities-readable", make("li", "参数范围未取得。"));
    text("capabilities-pricing", [capability.price_source, capability.fee_basis].filter(present).join("；") || "价格与费用来源未确认。");
    text("config-json", display(config));
    text("budget-summary", `最多 ${display(limits.model_calls)} 次模型调用 / ${display(limits.backtest_creations)} 次新远端回测创建尝试。\n单次模型超时 ${display(limits.model_timeout_seconds)} 秒；任务超时 ${display(limits.task_timeout_seconds)} 秒。`);
    if (!state.questionInitialized && typeof state.config.default_question === "string") {
      $("research-question").value = pendingSubmission ? pendingSubmission.question : state.config.default_question;
      if (pendingSubmission) state.startKey = pendingSubmission.key;
      state.questionInitialized = true;
    }
  }

  function renderHistory() {
    text("research-count", `${state.runs.length} 项研究`);
    if (!state.selected && state.runs.length) { state.selected = state.runs[0].research_id; updateUrl(); }
    const exists = state.runs.some((run) => run.research_id === state.selected), select = $("research-select");
    const signature = JSON.stringify(state.runs.map((run) => [run.research_id, run.status, run.question]));
    if (select.dataset.signature !== signature) {
      const options = state.runs.map((run) => {
        const outcome = run.final_presentation && run.final_presentation.verdict || run.final && run.final.verdict || brief(run.question, 28);
        const created = time(run.created_at).replace(/:\d{2} UTC$/, " UTC");
        const option = make("option", `${created} · ${run.research_id.slice(0, 8)} · ${status(run.status)} · ${outcome}`);
        option.value = run.research_id;
        return option;
      });
      if (!options.length || (state.selected && !exists)) {
        const option = make("option", state.selected ? "指定研究不存在" : "尚无研究任务");
        option.value = "";
        options.unshift(option);
      }
      select.replaceChildren(...options);
      select.dataset.signature = signature;
    }
    select.value = exists ? state.selected : "";
    select.disabled = !state.runs.length;
    $("no-research").hidden = exists;
    text("no-research", state.selected && !exists ? "指定的研究记录不存在。可从列表选择已保存研究。" : "尚无研究任务。");
    if (!exists) {
      state.detail = null;
      state.renderedDetailSignature = null;
      $("research-detail").hidden = true;
      replace("final-result", make("p", state.selected ? "指定研究不存在。" : "尚无研究结果。", "muted-copy"));
      replace("research-evidence");
    }
    return exists;
  }

  function renderEvents(events) {
    const items = (Array.isArray(events) ? events : []).map((event) => {
      const item = make("li");
      item.append(make("time", `${time(event.at)} · ${status(event.kind)}`), make("span", display(event.message)));
      return item;
    });
    replace("research-events", ...(items.length ? items : [make("li", "尚无执行事件。") ]));
  }
  function renderActions(actions) {
    const cards = (Array.isArray(actions) ? actions : []).map((action, index) => {
      const card = make("article", undefined, "action-card"), top = make("div", undefined, "action-topline"), mark = make("span");
      const kind = typeof action.action === "string" ? action.action : (action.action && action.action.type) || "动作未记录";
      top.append(make("strong", `步骤 ${action.step || index + 1} · ${kind}`));
      badge(mark, action.reused ? "复用已有结果" : status(action.status));
      top.append(mark);
      card.append(top);
      if (action.run_id) card.append(runLink(action.run_id));
      if (action.model_explanation) card.append(make("p", action.model_explanation));
      if (action.error) card.append(make("p", display(action.error), "result-error"));
      card.append(jsonNode("实验计划与工具请求", {plan: action.plan, action: action.action, request: action.request, status: action.status, reused: action.reused, run_id: action.run_id}));
      return card;
    });
    replace("research-actions", ...(cards.length ? cards : [make("p", "尚无实验动作。", "muted-copy") ]));
  }

  function feeChart(runId, comparison, series) {
    const domain = view.chartDomain(series);
    if (!domain) return make("p", "费用比较金额缺失，图表未生成。", "muted-copy");
    const section = make("section", undefined, "fee-comparison"), title = make("h4", "BTC 模型损益 · ");
    const reference = runLink(runId);
    reference.textContent = runId.slice(0, 8);
    reference.title = runId;
    title.append(reference);
    section.append(title);
    const values = series.map((row) => Number(row.value));
    const x = (value) => 110 + (value - domain.min) / (domain.max - domain.min) * 175;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 480 164");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `回测 ${runId} 的费用前、基础费用后、较高费用后模型损益，单位 BTC。完整精度在图表下方记录。`);
    svg.classList.add("fee-chart");
    const shape = (tag, attrs, content) => {
      const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
      if (tag === "text") node.style.fontSize = "16px";
      if (content !== undefined) node.textContent = String(content);
      svg.append(node);
      return node;
    };
    shape("line", {x1: x(0), x2: x(0), y1: 12, y2: 140, stroke: "#88948e", "stroke-width": 1});
    shape("text", {x: x(0), y: 158, "text-anchor": "middle", fill: "#627168", "font-size": 16}, "0 BTC");
    series.forEach((row, index) => {
      const value = values[index], y = 20 + index * 42;
      shape("text", {x: 0, y: y + 18, fill: "#34453b", "font-size": 16}, row.label);
      shape("rect", {x: Math.min(x(0), x(value)), y, width: value === 0 ? 0 : Math.max(1, Math.abs(x(value) - x(0))), height: 25, rx: 2, fill: value < 0 ? "#ae5b49" : index === 0 ? "#74867c" : "#38765a"});
      const rounded = value.toPrecision(5);
      shape("text", {x: 300, y: y + 18, fill: "#34453b", "font-size": 16}, `${Number(rounded) === value ? "" : "≈ "}${Number(rounded)} BTC`);
    });
    section.append(svg, make("p", "同一实验的费用重算", "fee-chart-note"));
    const exact = make("details", undefined, "json-detail"), table = make("table", undefined, "fee-table"), head = make("thead"), headings = make("tr"), body = make("tbody");
    exact.append(make("summary", "完整精度与字段引用"));
    for (const label of ["字段", "记录值", "单位"]) { const cell = make("th", label); cell.scope = "col"; headings.append(cell); }
    head.append(headings);
    for (const [field, unit] of Object.entries(fieldUnits).filter(([field]) => field.startsWith("fee_comparison."))) {
      const key = field.split(".")[1];
      if (!Object.prototype.hasOwnProperty.call(comparison, key)) continue;
      const row = make("tr"), label = make("th", `${runId} · ${field}`);
      label.scope = "row";
      row.append(label, make("td", display(comparison[key], "未知")), make("td", unit));
      body.append(row);
    }
    table.append(head, body);
    const scroll = make("div", undefined, "fact-table-scroll");
    scroll.tabIndex = 0;
    scroll.append(table);
    exact.append(scroll, jsonNode("完整程序费用记录", comparison));
    section.append(exact);
    return section;
  }
  function verifiedComparison(evidence, metric) {
    return view.trustedFeeSeries(evidence, metric);
  }
  function renderEvidence(evidence, metrics) {
    const trusted = new Map((Array.isArray(metrics) ? metrics : []).map((item) => [item.run_id, item]));
    const cards = (Array.isArray(evidence) ? evidence : []).map((item) => {
      const card = make("article", undefined, "evidence-card"), top = make("div", undefined, "action-topline"), mark = make("span"), bound = trusted.get(item.run_id), accounting = bound && bound.accounting;
      top.append(runLink(item.run_id));
      badge(mark, status(item.status));
      top.append(mark);
      card.append(top, metricList([
        ["服务任务", item.service_task_id], ["结果出处", item.source],
        ["金额核对", accounting && accounting.model_ledger_verified === true ? "模型账本已核对" : "未核对"],
        ["BTC 净模型损益", accounting && accounting.model_ledger_verified === true ? amount(accounting.btc_net_pnl) : "未核对"],
        ["价格来源", accounting && accounting.price_source]
      ]));
      if (Array.isArray(item.gaps) && item.gaps.length) card.append(list(item.gaps, ""));
      if (bound && bound.fee_comparison && !verifiedComparison(item, bound)) card.append(make("p", "费用记录未通过身份与模型账本核对，未生成图表。", "muted-copy"));
      card.append(jsonNode("证据实际请求与计量记录", item));
      return card;
    });
    replace("research-evidence", ...(cards.length ? cards : [make("p", "尚无实际结果证据。", "muted-copy") ]));
  }

  function renderFinal(final, evidence, presentation, metrics, bindingStatus) {
    const section = $("final-section"), container = $("final-result");
    if (!section || !container) return;
    const evidenceRows = Array.isArray(evidence) ? evidence : [];
    section.hidden = false;
    const nodes = [], validation = presentation && presentation.validation || {}, interpretation = presentation && presentation.interpretation || {};
    const audit = make("details", undefined, "json-detail");
    audit.append(make("summary", "结论依据与原始记录"));
    if (presentation) {
      const summary = make("div", undefined, "final-summary");
      summary.append(make("h3", `Researcher 判断：${display(presentation.verdict, "未提供")}`));
      if (interpretation.conclusion) summary.append(make("p", brief(interpretation.conclusion)));
      summary.append(make("p", `证据绑定：${status(bindingStatus || presentation.binding_status || (presentation.derived_from_legacy ? "derived" : validation.status))} · ${display(validation.scope, "自然语言结论未完整验证")}`, "fineprint"));
      if (validation.status && validation.status !== "passed") summary.append(make("p", `展示校验：${status(validation.status)}${Array.isArray(validation.issues) && validation.issues.length ? ` · ${validation.issues.length} 项原始文本或引用缺口` : ""}`, "fineprint"));
      nodes.push(summary);
    } else if (final) nodes.push(make("p", "已保存模型结论；尚无经过绑定校验的展示。", "muted-copy"));
    else if (evidenceRows.length) nodes.push(make("p", "已取得实验结果，尚无完成结论。", "muted-copy"));
    else nodes.push(make("p", "尚无完成结论。", "muted-copy"));

    const trusted = new Map((Array.isArray(metrics) ? metrics : []).map((item) => [item.run_id, item]));
    for (const item of evidenceRows) {
      const metric = trusted.get(item.run_id);
      const series = verifiedComparison(item, metric);
      if (series) nodes.push(feeChart(item.run_id, metric.fee_comparison, series));
    }
    if (presentation) {
      const known = new Map(evidenceRows.map((item) => [item.run_id, item])), facts = Array.isArray(presentation.facts) ? presentation.facts : [], confirmed = [], missing = [];
      for (const fact of facts) {
        const item = known.get(fact.run_id), value = item && evidenceField(item, fact.field), expectedUnit = fieldUnits[fact.field] || "";
        if (value !== undefined && JSON.stringify(value) === JSON.stringify(fact.value) && (fact.unit || "") === expectedUnit) confirmed.push(fact);
        else missing.push(fact);
      }
      if (confirmed.length) {
        const details = make("details", undefined, "json-detail");
        details.append(make("summary", `${confirmed.length} 项绑定事实 · 查看原始精度`));
        const table = make("table", undefined, "fee-table"), head = make("thead"), headings = make("tr"), body = make("tbody");
        for (const label of ["事实 / 引用", "展示值", "原始记录值"]) { const cell = make("th", label); cell.scope = "col"; headings.append(cell); }
        head.append(headings);
        for (const fact of confirmed) {
          const row = make("tr"), reference = make("th");
          reference.scope = "row";
          reference.append(make("span", fact.label || fact.field), make("br"), runLink(fact.run_id), make("small", ` · ${fact.field}`));
          row.append(reference, make("td", `${display(fact.display_value)}${fact.unit ? ` ${fact.unit}` : ""}`), make("td", `${display(fact.value, "未知")}${fact.unit ? ` ${fact.unit}` : ""}`));
          body.append(row);
        }
        table.append(head, body);
        const scroll = make("div", undefined, "fact-table-scroll");
        scroll.tabIndex = 0;
        scroll.append(table);
        details.append(scroll);
        audit.append(details);
      }
      if (missing.length) nodes.push(make("p", `${missing.length} 项事实未匹配当前证据记录，未作为已核对数值展示。`, "result-error"));
      const narrative = make("details", undefined, "json-detail");
      narrative.append(make("summary", "假设、未知项与未执行建议"));
      if (interpretation.conclusion && interpretation.conclusion.length > 160) narrative.append(make("h4", "完整研究解释"), make("p", interpretation.conclusion));
      if (interpretation.hypothesis) narrative.append(make("p", interpretation.hypothesis));
      for (const [label, key] of [["反例", "counterexamples"], ["未知项", "unknowns"]]) {
        if (Array.isArray(interpretation[key]) && interpretation[key].length) narrative.append(make("h4", label), list(interpretation[key], ""));
      }
      const future = presentation.future || {};
      if (future.next_step || (Array.isArray(future.suggested_experiments) && future.suggested_experiments.length)) {
        narrative.append(make("h4", "研究建议"), make("p", display(future.status, "未执行建议")));
        if (future.next_step) narrative.append(make("p", future.next_step));
        if (Array.isArray(future.suggested_experiments) && future.suggested_experiments.length) narrative.append(list(future.suggested_experiments, ""));
      }
      audit.append(narrative);
      if (Array.isArray(presentation.comparisons) && presentation.comparisons.length) audit.append(jsonNode("程序派生的跨实验差额（各实验不可合计）", presentation.comparisons));
      if (validation.issues && validation.issues.length) audit.append(jsonNode("展示校验缺口", validation.issues));
    }
    const raw = presentation && presentation.original_model_output || final;
    if (presentation) audit.append(jsonNode("展示版本与绑定范围", {version: presentation.version, binding_status: bindingStatus || presentation.binding_status, derived_from_legacy: presentation.derived_from_legacy, source_final_sha256: presentation.source_final_sha256, evidence_sha256: presentation.evidence_sha256, validation}));
    if (raw) audit.append(jsonNode("原始模型文本（未验证全部叙述）", raw));
    if (presentation || raw) nodes.push(audit);
    container.replaceChildren(...nodes);
  }

  function renderDetail() {
    const run = state.detail;
    $("research-detail").hidden = !run;
    if (!run) return;
    text("research-id", run.research_id);
    text("selected-result-title", `所选研究 ${run.research_id.slice(0, 8)} · 结果与费用图`);
    badge($("research-status"), status(run.status), run.status === "completed");
    text("saved-question", run.question || "问题未记录");
    const config = run.configuration_snapshot || {}, budget = run.budget || {};
    text("task-identity", `${display(config.role, "角色未记录")} · ${display(config.model, "模型未记录")} / ${display(config.reasoning_effort, "推理强度未记录")}`);
    text("run-budget", `模型 ${display(budget.model_calls_used)} / ${display(budget.model_calls_limit)} · 新回测 ${display(budget.backtest_creations_used)} / ${display(budget.backtest_creations_limit)}`);
    text("research-error", display(run.error, ""));
    $("research-error").hidden = !run.error;
    const local = run.status === "invalid_output" && run.can_resume;
    text("resume-research", local ? "重新校验本地结论" : "继续本次研究");
    text("recovery-reason", run.recovery_reason || (local ? "只校验已保存结论，不增加模型或远端回测调用。" : run.can_resume ? "继续读取已知远端任务；提交结果未知时不重发。" : run.can_stop ? "停止本地研究；已创建的远端任务不会撤销。" : ""));
    text("saved-config", display({configuration_snapshot: run.configuration_snapshot, input_references: run.input_references || run.input_refs, created_at: run.created_at, updated_at: run.updated_at}));
    const signature = JSON.stringify(run);
    if (state.renderedDetailSignature !== signature) {
      state.renderedDetailSignature = signature;
      renderEvents(run.events);
      renderActions(run.actions);
      renderEvidence(run.evidence, run.verified_metrics);
      renderFinal(run.final, run.evidence, run.final_presentation, run.verified_metrics, run.binding_status);
    }
    controls();
  }

  function freshness(fresh, reason) {
    for (const id of ["workspace-account", "workspace-strategy", "workspace-agents", "workspace-approvals", "research-detail", "final-section", "research-evidence"]) {
      const node = $(id);
      if (node) { node.classList.toggle("workspace-stale", !fresh); node.dataset.fresh = String(fresh); }
    }
    if (!fresh) {
      badge($("backend-status"), "当前状态未确认", false);
      if (state.detail) badge($("research-status"), `上次记录 · ${status(state.detail.status)}`);
      text("workspace-updated", `当前状态未确认${state.workspace ? ` · 上次读取 ${time(state.workspace.server_time)}` : ""}`);
      text("connection-notice", reason || "状态读取已过期。以下保留上次记录。" );
      if ($("connection-notice")) $("connection-notice").className = "connection-notice is-error";
    }
  }
  async function request(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, {cache: "no-store", ...options, signal: controller.signal});
      let payload;
      try { payload = await response.json(); }
      catch (_) { throw new Error(response.ok ? "本地状态格式无效" : `本地接口不可用（HTTP ${response.status}）`); }
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    } finally { clearTimeout(timer); }
  }
  async function poll() {
    if (polling) { forcePoll = true; return; }
    polling = true;
    clearTimeout(pollTimer);
    try {
      const [config, history, workspace] = await Promise.all([request("/api/research/config"), request("/api/research/runs"), request("/api/workspace")]);
      if (!config.configuration || !config.availability || typeof config.csrf_token !== "string" || !Array.isArray(history.runs) || !workspace.account || !workspace.strategy || !workspace.agents || !workspace.approvals) throw new Error("业务状态响应格式无效");
      state.config = config;
      state.runs = history.runs;
      state.workspace = workspace;
      renderConfig();
      renderWorkspace();
      const exists = renderHistory();
      if (exists) {
        const selected = state.selected, detail = await request(`/api/research/runs/${encodeURIComponent(selected)}`);
        if (detail.research_id !== selected || typeof detail.status !== "string") throw new Error("研究明细响应格式无效");
        if (selected === state.selected) { state.detail = detail; renderDetail(); }
      }
      state.online = true;
      state.lastReceived = performance.now();
      freshness(true);
      $("history-error").hidden = true;
      badge($("backend-status"), "已连接本地服务", true);
      text("connection-notice", `状态读取：${time(workspace.server_time)} · 约每 3 秒更新`);
      $("connection-notice").className = "connection-notice";
    } catch (error) {
      state.online = false;
      freshness(false, `读取失败：${error.name === "AbortError" ? "请求超时" : error.message}。保留上次记录；当前状态未确认。`);
    } finally {
      polling = false;
      controls();
      pollTimer = setTimeout(poll, forcePoll ? 0 : 3000);
      forcePoll = false;
    }
  }
  async function post(path, body) {
    if (state.posting || !state.online || !state.config) return;
    state.posting = true;
    controls();
    const message = $("action-message");
    message.hidden = false;
    message.className = "action-message";
    message.textContent = "正在提交…";
    try {
      const result = await request(path, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": state.config.csrf_token}, body: JSON.stringify(body)});
      if (!result.research_id && !result.status) throw new Error("操作响应不完整，请先查看历史记录");
      if (result.research_id) { state.selected = result.research_id; updateUrl(); }
      message.textContent = "操作已受理，以保存的任务状态为准。";
      if (path === "/api/research/start") { $("approve-budget").checked = false; clearPending(); }
    } catch (error) {
      message.className = "action-message is-error";
      message.textContent = error.name === "AbortError" || error instanceof TypeError
        ? "操作结果未知，请先查看历史。相同问题保留本次提交标识，不自动重发或扩大预算。" : `操作未完成：${error.message}`;
    } finally { state.posting = false; controls(); poll(); }
  }

  const setup = $("setup-details");
  if (setup) setup.addEventListener("toggle", () => text("setup-toggle-badge", setup.open ? "收起" : "展开"));
  $("research-question").addEventListener("input", () => { clearPending(); $("approve-budget").checked = false; controls(); });
  $("approve-budget").addEventListener("change", controls);
  $("use-example").addEventListener("click", () => {
    if (!state.config) return;
    $("research-question").value = state.config.default_question || "";
    $("approve-budget").checked = false;
    clearPending();
    controls();
  });
  $("start-research").addEventListener("click", () => {
    if ($("start-research").disabled) return;
    state.startKey = state.startKey || (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const question = $("research-question").value.trim();
    try { sessionStorage.setItem("optimatrix-pending-research", JSON.stringify({key: state.startKey, question})); } catch (_) {}
    post("/api/research/start", {question, approved: true, idempotency_key: state.startKey});
  });
  $("research-select").addEventListener("change", () => selectResearch($("research-select").value));
  $("stop-research").addEventListener("click", () => { if (!$("stop-research").disabled) post(`/api/research/runs/${encodeURIComponent(state.selected)}/stop`, {}); });
  $("resume-research").addEventListener("click", () => { if (!$("resume-research").disabled) post(`/api/research/runs/${encodeURIComponent(state.selected)}/resume`, {}); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") { state.online = false; freshness(false, "正在重新确认当前状态…"); controls(); poll(); }
  });
  setInterval(() => {
    if (state.lastReceived !== null && performance.now() - state.lastReceived > 15000 && state.online) {
      state.online = false;
      freshness(false, "状态读取已超过 15 秒；当前运行状态未确认，暂时不能开始或恢复。" );
      controls();
    }
  }, 1000);
  controls();
  poll();
})();

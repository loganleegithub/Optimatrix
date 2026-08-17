(() => {
  'use strict';

  const workbench = window.OPTIMATRIX_WORKBENCH;
  if (!workbench || workbench.schema_version !== 8) {
    document.body.textContent = 'Workbench 数据缺失或版本不受支持。';
    return;
  }

  const documentSignature = document => JSON.stringify({
    schemaVersion: document.schema_version,
    snapshotKnownAt: document.snapshot?.known_at,
    runtimeUpdatedAt: document.runtime?.updated_at,
    runtimeState: document.runtime?.state,
    reviewProjectionId: document.review?.completed?.projection_id,
    ledgerCounts: document.ledger?.counts,
    cases: (document.cases || []).map(item => ({
      tradeCaseId: item.trade_case_id,
      entryStatus: item.entry_status,
      entryReunderwritingId: item.entry_reunderwriting?.summary?.find(row => row.key === 'entry_reunderwriting_id')?.value,
      positionState: item.position_state,
      terminalAt: item.display?.terminal_at,
      gapObserved: item.display?.gap_observed
    }))
  });
  const initialDocumentSignature = documentSignature(workbench);

  const completedReviewProjection = () => {
    const expected = workbench.review.completed;
    const external = window.OPTIMATRIX_COMPLETED_SESSION_REVIEWS;
    if (
      expected.status === 'AVAILABLE' &&
      external?.status === expected.status &&
      external?.projection_id === expected.projection_id
    ) return external;
    if (expected.status === 'AVAILABLE') return {
      ...expected,
      status: 'UNAVAILABLE',
      reason: 'COMPLETED_SESSION_REVIEW_DATA_UNAVAILABLE',
      reviews: []
    };
    return expected;
  };

  const byId = id => document.getElementById(id);
  const create = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const appendText = (node, tag, className, text) => {
    const child = create(tag, className, text);
    node.append(child);
    return child;
  };
  const rowMap = rows => Object.fromEntries((rows || []).map(row => [row.key, row]));
  const valueMap = rows => Object.fromEntries((rows || []).map(row => [row.key, row.value]));
  const isUnknown = value => value === undefined || value === null || value === '' || value === 'UNKNOWN';
  const shortValue = value => {
    if (isUnknown(value)) return '未知';
    const text = String(value);
    if (text.startsWith('sha256:')) return `${text.slice(7, 15)}…`;
    return text.length > 28 ? `${text.slice(0, 27)}…` : text;
  };
  const localFormatter = new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23'
  });
  const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short'
  });
  const formatTimestamp = value => {
    if (isUnknown(value)) return '未知';
    const instantValue = typeof value === 'string' && /^\d{13}$/.test(value) ? Number(value) : value;
    const instant = new Date(instantValue);
    return Number.isNaN(instant.getTime()) ? String(value) : localFormatter.format(instant);
  };
  const formatDate = value => {
    const instant = new Date(value);
    return Number.isNaN(instant.getTime()) ? 'Session 未知' : dateFormatter.format(instant);
  };
  const displayRowValue = row => row.kind === 'timestamp' ? formatTimestamp(row.value) : translate(row.value);
  const countLabel = value => isUnknown(value) ? '未知' : String(value);

  const translations = {
    PUBLIC_SHADOW: '公开行情模拟',
    UNAUTHORIZED: '尚未授权',
    RUNNING: '持续运行',
    RECOVERY_GAP: '恢复中断形成数据缺口',
    MARKET_GAP: '公开行情数据缺口',
    STARTING: '启动中',
    RECOVERING: '恢复中',
    STOPPED: '已停止',
    STOPPED_FOR_RESTART: '等待重启',
    SNAPSHOT_ONLY: '单次快照',
    COMPLETE: '已完成',
    PRIMARY_RANK_UNRESOLVED: 'Primary 排名未决',
    COMPLETE_PENDING_TRADER_ACCEPTANCE: '完成 · 待交易员验收',
    UNKNOWN: '未知',
    KNOWN: '已知',
    EVALUABLE: '可评估',
    NOT_EVALUABLE: '不可评估',
    NOT_APPLICABLE: '不适用',
    DECISION: '决策',
    ENTRY: '入场重承保',
    MONITOR: '持续监控',
    EXIT: '退出估价',
    NO_ENTRY: '不入场对照',
    HOLD_TO_EXPIRY: '持有到期对照',
    OFFICIAL_EXPIRY_SETTLEMENT_PENDING: '等待匹配的官方交割事实',
    YES: '是',
    NO: '否',
    NONE: '无',
    STRUCTURE_FOUND: '发现完整结构',
    NO_STRUCTURE: '无符合条件结构',
    NO_LEGAL_FOUR_LEG_STRUCTURE: '当前到期与行权价组合未形成合法完整四腿',
    NO_PRICE_EVALUABLE_FOUR_LEG_STRUCTURE: '已有合法结构，但完整四腿无法估价',
    NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE: '已有合法且可估价结构，但没有符合当前 Policy 的候选',
    PRIMARY_RANK_UNRESOLVED_BY_MISSING_BOOKS: '缺失盘口仍可能改变 Primary 排名',
    PUBLIC_MARKET_GAP: '公开行情切面不完整，本窗口无法判断',
    RESTART_INTERRUPTED_CAUSAL_CUT: '重启中断因果切面，本窗口不重抓',
    BOUNDARY_NET_CREDIT_TOO_SMALL: '净权利金不足',
    CREDIT_TO_PAYOFF_CAP_TOO_SMALL: '权利金 / 契约赔付上限不足',
    BOUNDARY_REFERENCE_LOSS_TOO_HIGH: '边界参考损失过高',
    SESSION_VRP_PROXY_BELOW_THRESHOLD: '本 Session 隐含—实际波动率溢价代理不足',
    RV_ACCELERATION_TOO_HIGH: '实际波动率正在加速',
    EVENT_OR_SHOCK_IN_PROGRESS: '事件或冲击状态仍在持续',
    NET_DELTA_TOO_DIRECTIONAL: '组合净 Delta 方向性过高',
    NOT_EVALUATED: '未评估',
    ASYMMETRIC_IRON_CONDOR: '非对称铁鹰',
    CORE_CARRY: '核心持有阶段',
    LATEST_EXIT: '最晚退出边界',
    EVENT_OR_SHOCK: '事件或冲击',
    MAXIMUM_LOSS: '最大亏损',
    SHORT_DELTA: '短腿 Delta',
    ADVERSE_MOVE: '标的不利移动',
    RV_ACCELERATION: '实际波动率加速',
    VRP_PROXY_DISSIPATED: 'VRP 代理消散',
    TAKE_PROFIT: '止盈',
    SHADOW_ATOMIC_EVALUABLE: '完整组合可估价',
    SHADOW_ATOMIC_NOT_EVALUABLE: '完整事实证明无法估价',
    ENTRY_EVIDENCE_UNKNOWN: '入场证据未知',
    ENTRY_THESIS_EXPIRED: '入场论点已失效',
    ENTRY_STRUCTURE_LIMIT_BREACHED: '入场结构限制已突破',
    ENTRY_PRICE_DETERIORATED: '入场经济性已恶化',
    RISK_RESERVATION_INVALID: '冻结研究预算无效',
    MONITORING: '管理中',
    EXIT_INTENT_FROZEN: '退出意图已冻结',
    TERMINAL: '终局已冻结',
    WHOLE_PRODUCT_EXIT: '完整组合退出估价',
    CONTRACT_SETTLEMENT: '到期交割结算',
    NO_POSITION: '未形成模拟头寸',
    AVAILABLE: '可用',
    UNAVAILABLE: '不可用',
    SHADOW_PROJECTION: '公开行情模拟',
    MARKET_SOURCE_AFTER_RECEIPT: '市场源时间晚于接收边界',
    MARKET_SOURCE_BOUNDARY_STALE: '行情源时间落后于当前因果边界，本窗口无法判断',
    MARKET_SOURCE_STALE: '行情源时间已过期，本窗口无法判断',
    MARKET_RECEIPT_STALE: '行情接收时间已过期，本窗口无法判断',
    MARKET_SOURCE_IN_FUTURE: '行情源时间超出当前因果边界',
    MARKET_RECEIPT_IN_FUTURE: '行情接收时间超出当前因果边界',
    MARKET_SOURCE_SPAN_EXCEEDED: '所需盘口的市场时间跨度过大',
    MARKET_RECEIVE_SPAN_EXCEEDED: '所需盘口的接收时间跨度过大',
    OBSERVATION_UNIVERSE_MISMATCH: '市场观察与所需期权集合不一致',
    OBSERVATION_AFTER_INPUT_DEADLINE: '市场观察晚于本窗口输入截止',
    OBSERVATION_OUTSIDE_WINDOW: '市场观察不属于当前窗口',
    DATA_HEALTH_POLICY_AGE_MISMATCH: '行情新鲜度不符合冻结的 DataHealth Policy',
    DELIVERY_TWAP: '交割价计算时段',
    BOUNDED_SNAPSHOT_IS_NOT_A_DECISION_RECORD: '当前快照不是权威 DecisionRecord',
    WINDOW: '市场窗口',
    CASE: 'TradeCase',
    NO_OBSERVATION: '无有效市场观察',
    POLICY_NOT_QUALIFIED: 'Policy 尚未资格化',
    PUBLIC_WINDOW_HAS_NO_EXECUTION: '公开行情窗口没有真实执行',
    NOT_YET_MEASURED: '尚未测量',
    NOT_YET_AVAILABLE: '尚未生成',
    NO_DAILY_SESSION_REVIEW_PROJECTION: '尚未生成每日 Session 复盘投影',
    AI_LAB_REVIEW_PROJECTION_INVALID: 'AI Lab 复盘投影校验失败',
    AI_LAB_REVIEW_PROJECTION_STAT_FAILED: '无法读取 AI Lab 复盘投影状态',
    COMPLETED_SESSION_REVIEW_DATA_UNAVAILABLE: '已完成 Session 复盘明细未能加载',
    NOT_READY: 'Session 尚未就绪',
    SUCCEEDED: '复盘成功',
    FAILED: '复盘失败',
    PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR: '部分识别 · 未发现已知规则错误',
    NO_OPPORTUNITY_CORRECTLY_AVOIDED: '没有事后机会 · Base 正确避开',
    RULE_WELL_CALIBRATED: '本 Session 规则取舍一致',
    RULE_TOO_CONSERVATIVE: '规则过于保守',
    RULE_TOO_AGGRESSIVE: '规则过于激进',
    MIXED_RULE_ERROR: '同时存在漏单与过度风险',
    OBSERVED_RULE_TOO_CONSERVATIVE: '已观察到规则过于保守',
    OBSERVED_RULE_TOO_AGGRESSIVE: '已观察到规则过于激进',
    OBSERVED_MIXED_RULE_ERROR: '已观察到混合规则错误',
    CAPTURED_OPPORTUNITY: '抓对机会',
    CORRECT_AVOIDANCE: '正确避开',
    MISSED_OPPORTUNITY: '漏掉机会',
    OVER_RISK_SELECTION: '选择过度风险',
    AUDITABLE: '可审判',
    ABSTAIN: '不做',
    REVIEW: '复核',
    CANDIDATE: '候选',
    FUTURE_VARIANCE_PATH_INCOMPLETE: '未来波动路径不完整',
    DECISION_RECORD_MISSING: '缺少 DecisionRecord',
    WINDOW_OUTCOME_MISSING: '缺少 WindowOutcome',
    DECISION_OBSERVATION_MISSING: '缺少决策时市场观察'
  };
  function translate(value) {
    if (isUnknown(value)) return '未知';
    const text = String(value);
    if (translations[text]) return translations[text];
    if (text.includes('BOUNDARY') || text.includes('SNAPSHOT') || text.includes('MARKET_')) {
      return text.replaceAll('_', ' ');
    }
    return text.replaceAll('_', ' ');
  }
  const translateComposite = value => String(value)
    .split(' · ')
    .map(part => translate(part))
    .join(' · ');

  let selectedCaseId = null;
  let selectedReviewId = null;
  let lastFocusedElement = null;

  function routeFromHash() {
    const raw = window.location.hash.slice(1);
    if (raw.startsWith('product/')) {
      return { screen: 'product', caseId: decodeURIComponent(raw.slice('product/'.length)) };
    }
    if (raw === 'review') return { screen: 'review', caseId: null };
    return { screen: 'ledger', caseId: null };
  }

  function navigate(route, caseId) {
    if (route === 'product') {
      const target = caseId || selectedCaseId || workbench.cases[0]?.trade_case_id;
      if (!target) {
        showNotice('当前没有 TradeCase 可打开；市场窗口仍可在产品账中查看。');
        return;
      }
      window.location.hash = `product/${encodeURIComponent(target)}`;
    } else {
      window.location.hash = route === 'review' ? 'review' : 'ledger';
    }
  }

  function applyRoute() {
    const route = routeFromHash();
    document.querySelectorAll('[data-screen]').forEach(screen => {
      screen.hidden = screen.dataset.screen !== route.screen;
    });
    document.querySelectorAll('.nav-button').forEach(button => {
      const active = button.dataset.route === route.screen || (route.screen === 'product' && button.dataset.route === 'ledger');
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });
    if (route.screen === 'product') {
      selectedCaseId = route.caseId;
      renderProduct(route.caseId);
    }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  function showNotice(message) {
    const notice = byId('channel-notice');
    notice.textContent = message;
    notice.hidden = false;
    window.clearTimeout(showNotice.timeoutId);
    showNotice.timeoutId = window.setTimeout(() => { notice.hidden = true; }, 3600);
  }

  function renderShell() {
    byId('session-label').textContent = `${formatDate(workbench.runtime.session_id)} · Deribit 08:00 UTC 到期`;
    const switcher = byId('channel-switcher');
    switcher.replaceChildren();
    workbench.channels.forEach(channel => {
      const button = create('button', 'channel-button', `${channel.strategy}`);
      button.type = 'button';
      button.dataset.underlying = channel.underlying;
      button.dataset.channelId = channel.channel_id;
      button.classList.toggle('is-active', channel.channel_id === workbench.ledger.active_channel_id);
      button.classList.toggle('is-reserved', !channel.implemented);
      button.title = channel.implemented ? channel.status_label : `${channel.status_label}；没有 Policy、运行时或业务人口`;
      button.addEventListener('click', () => {
        if (!channel.implemented) {
          showNotice(`${channel.underlying} ${channel.strategy}：尚未授权、尚未定义，不显示伪造的机会、持仓或零值。`);
          return;
        }
        navigate('ledger');
      });
      switcher.append(button);
    });
  }

  function renderLedger() {
    const summary = workbench.ledger.summary;
    const summaryTarget = byId('ledger-summary');
    summaryTarget.replaceChildren();
    [
      ['市场窗口', `${countLabel(summary.recorded_windows)} / ${countLabel(summary.session_denominator)}`],
      ['TradeCase', countLabel(summary.case_count)],
      ['未完责任', countLabel(summary.unresolved_count)]
    ].forEach(([label, value]) => {
      const item = create('div', 'heading-metric');
      appendText(item, 'span', '', label);
      appendText(item, 'strong', '', value);
      summaryTarget.append(item);
    });

    const grid = byId('ledger-grid');
    grid.replaceChildren();
    grid.append(create('div', 'ledger-cell ledger-stage-corner', '策略书 / 研究赛道'));
    workbench.ledger.stages.forEach(stage => {
      const head = create('div', 'ledger-cell ledger-stage-head');
      appendText(head, 'strong', '', stage.label);
      appendText(head, 'span', '', stage.description);
      grid.append(head);
    });
    workbench.ledger.rows.forEach(row => {
      const channel = row.channel;
      const channelCell = create('section', `ledger-cell channel-cell ${channel.implemented ? 'is-active' : 'is-reserved'}`);
      appendText(channelCell, 'strong', '', `${channel.underlying} ${channel.strategy}`);
      appendText(channelCell, 'span', '', channel.product_name);
      const status = create('div', 'channel-status');
      appendText(status, 'em', '', channel.implemented ? '业务通道' : 'Authority 边界');
      appendText(status, 'b', '', channel.status_label);
      if (channel.implemented) appendText(status, 'em', '', `${channel.case_count} 宗 Case · ${channel.unresolved_count} 件未完责任`);
      channelCell.append(status);
      grid.append(channelCell);

      workbench.ledger.stages.forEach(stage => {
        const cell = create('div', `ledger-cell stage-cell ${channel.implemented ? '' : 'is-reserved'}`);
        if (!channel.implemented) {
          cell.textContent = '当前 Authority 未授权\n无运行时';
        } else {
          const items = row.items.filter(item => item.stage === stage.key);
          if (!items.length) {
            cell.append(create('div', 'empty-stage', '—'));
          } else {
            items.forEach(item => cell.append(productCard(item)));
          }
        }
        grid.append(cell);
      });
    });

    const attention = workbench.ledger.attention;
    byId('attention-count').textContent = `${attention.length} 件未解决责任`;
    const list = byId('attention-list');
    list.replaceChildren();
    if (!attention.length) {
      list.append(create('div', 'attention-empty', '当前没有未终结 TradeCase。仍需持续观察市场窗口。'));
    } else {
      attention.forEach(item => {
        const card = create('button', 'attention-card');
        card.type = 'button';
        card.dataset.tone = item.tone;
        appendText(card, 'strong', '', `${item.stage_label} · ${item.short_id}`);
        appendText(card, 'span', '', item.structure_line);
        appendText(card, 'small', '', item.responsibility);
        appendText(card, 'small', '', `边界：${formatTimestamp(item.deadline)}`);
        card.addEventListener('click', () => navigate('product', item.case_id));
        list.append(card);
      });
    }
    const urgentButton = byId('open-urgent');
    urgentButton.disabled = !attention.length;
    urgentButton.onclick = attention.length ? () => navigate('product', attention[0].case_id) : null;

    const market = workbench.ledger.market_strip;
    const marketTarget = byId('market-strip');
    marketTarget.replaceChildren();
    [
      ['BTC 指数', `${market.index_price} USD`],
      ['当前 Session 阶段', translate(market.phase)],
      ['Public Shadow runtime', translate(market.runtime_status)],
      ['下一输入截止', formatTimestamp(market.next_boundary)],
      ['最后更新', formatTimestamp(market.updated_at)]
    ].forEach(([label, value]) => {
      const fact = create('div', 'market-fact');
      appendText(fact, 'span', '', label);
      appendText(fact, 'strong', '', value);
      marketTarget.append(fact);
    });
  }

  function productCard(item) {
    const card = create(item.case_id ? 'button' : 'article', 'product-card');
    if (item.case_id) {
      card.type = 'button';
      card.addEventListener('click', () => navigate('product', item.case_id));
    }
    card.dataset.tone = item.tone;
    const head = create('div', 'product-card-head');
    appendText(head, 'strong', '', item.title);
    appendText(head, 'span', '', translate(item.kind));
    card.append(head);
    appendText(card, 'p', '', translateComposite(item.subtitle));
    appendText(card, 'small', '', translate(item.responsibility));
    if (item.kind === 'WINDOW' && item.facts) {
      const facts = create('dl', 'window-facts');
      [
        ['合法结构', item.facts.legal],
        ['可估价', item.facts.price_evaluable],
        ['符合 Policy', item.facts.policy_eligible]
      ].forEach(([label, value]) => {
        const fact = create('div');
        appendText(fact, 'dt', '', label);
        appendText(fact, 'dd', '', countLabel(value));
        facts.append(fact);
      });
      card.append(facts);
    }
    appendText(card, 'small', '', formatTimestamp(item.time));
    return card;
  }

  function renderProduct(caseId) {
    const caseView = workbench.cases.find(item => item.trade_case_id === caseId) || workbench.cases[0];
    if (!caseView || !caseView.display) {
      navigate('ledger');
      return;
    }
    selectedCaseId = caseView.trade_case_id;
    const display = caseView.display;
    byId('product-case-title').textContent = `Case ${display.short_id} · BTC 铁鹰`;
    byId('product-case-subtitle').textContent = `${display.structure_line} · ${display.option_amount} BTC · 公开行情模拟（非真实成交/持仓）`;
    byId('product-stage-label').textContent = display.stage_label;
    byId('product-stage-label').dataset.tone = display.tone;
    byId('product-responsibility').textContent = display.responsibility;
    byId('position-state-badge').textContent = translate(display.position_state);
    byId('position-state-badge').dataset.tone = display.tone;
    renderLifecycle(display.timeline);
    renderStructure(caseView);
    renderManagement(caseView);
    renderOutcomeExplanation(caseView);
    renderResponsibility(caseView);
  }

  function renderLifecycle(timeline) {
    const target = byId('product-lifecycle');
    target.replaceChildren();
    timeline.forEach(item => {
      const step = create('li', 'lifecycle-step');
      step.classList.toggle('is-done', item.state === 'DONE');
      step.classList.toggle('is-current', item.state === 'CURRENT');
      step.append(create('span', 'lifecycle-marker'));
      appendText(step, 'strong', '', item.label);
      if (item.at) step.title = formatTimestamp(item.at);
      target.append(step);
    });
  }

  function metricItem(label, value, tone) {
    const item = create('div', 'metric-item');
    appendText(item, 'span', '', label);
    const strong = appendText(item, 'strong', '', isUnknown(value) ? '未知' : value);
    if (tone) strong.dataset.tone = tone;
    return item;
  }

  function renderStructure(caseView) {
    const display = caseView.display;
    const allocation = valueMap(caseView.risk_allocation);
    const economics = valueMap(caseView.entry_economics);
    const summary = byId('structure-summary');
    summary.replaceChildren(
      metricItem('组合名义金额', `${display.option_amount} BTC`),
      metricItem('入场净权利金', economics.native_net_credit ? `${economics.native_net_credit} BTC` : '未知', 'positive'),
      metricItem('标准 Combo 手续费', economics.combo_standard_fee_native ? `${economics.combo_standard_fee_native} BTC` : allocation.combo_fee_native ? `${allocation.combo_fee_native} BTC` : '未知'),
      metricItem('契约赔付上限', allocation.maximum_contractual_payoff_usd ? `${allocation.maximum_contractual_payoff_usd} USD` : '未知'),
      metricItem('压力预算占用', allocation.stress_reserve_usd ? `${allocation.stress_reserve_usd} USD` : '未知'),
      metricItem('研究预算结果', translate(display.allocation_result), display.allocation_result === 'AVAILABLE' ? 'positive' : 'warning'),
      metricItem('到期', formatTimestamp(display.expiry))
    );
    renderPayoffRail(caseView.selected_structure.legs || []);
    renderLegTable(caseView.selected_structure.legs || []);
    renderCausalStory(caseView);
  }

  function renderPayoffRail(legs) {
    const target = byId('payoff-chart');
    target.replaceChildren();
    if (legs.length !== 4) {
      target.append(create('div', 'trace-empty', '冻结四腿结构不可用。'));
      return;
    }
    const rail = create('div', 'strike-rail');
    const positions = [12, 34, 66, 88];
    const body = create('div', 'payoff-segment');
    body.style.left = `${positions[1]}%`;
    body.style.width = `${positions[2] - positions[1]}%`;
    rail.append(body);
    const leftWing = create('div', 'payoff-wing');
    leftWing.style.left = '0';
    leftWing.style.width = `${positions[0]}%`;
    const rightWing = create('div', 'payoff-wing');
    rightWing.style.left = `${positions[3]}%`;
    rightWing.style.width = `${100 - positions[3]}%`;
    rail.append(leftWing, rightWing);
    legs.forEach((leg, index) => {
      const marker = create('div', 'strike-marker');
      marker.style.left = `${positions[index]}%`;
      appendText(marker, 'span', '', leg.strike);
      rail.append(marker);
    });
    target.append(rail, create('div', 'payoff-axis-label', 'BTC 交割价格（USD） · 示意位置仅表达四腿顺序，经济值来自冻结 Case'));
  }

  function renderLegTable(legs) {
    const target = byId('case-leg-table');
    target.replaceChildren();
    if (!legs.length) return;
    const table = create('table');
    const head = create('thead');
    const headerRow = create('tr');
    ['方向', '买低 Put 翼', '卖高 Put 身', '卖低 Call 身', '买高 Call 翼'].forEach(label => appendText(headerRow, 'th', '', label));
    head.append(headerRow);
    const body = create('tbody');
    const tableRows = [
      ['操作', ...legs.map(leg => leg.action === 'LONG' ? '买入' : '卖出')],
      ['行权价', ...legs.map(leg => `${leg.strike} USD`)],
      ['期权类型', ...legs.map(leg => leg.option_type === 'PUT' ? '看跌期权' : '看涨期权')],
      ['数量', ...legs.map(leg => `${leg.option_amount} BTC`)],
      ['合约', ...legs.map(leg => shortValue(leg.instrument_name))]
    ];
    tableRows.forEach((row, rowIndex) => {
      const tr = create('tr');
      row.forEach((value, cellIndex) => {
        const td = appendText(tr, 'td', '', value);
        if (rowIndex === 0 && cellIndex > 0) td.className = legs[cellIndex - 1].action === 'LONG' ? 'is-long' : 'is-short';
        if (rowIndex === 4 && cellIndex > 0) td.title = legs[cellIndex - 1].instrument_name;
      });
      body.append(tr);
    });
    table.append(head, body);
    target.append(table);
  }

  function renderCausalStory(caseView) {
    const target = byId('causal-story');
    target.replaceChildren();
    const context = valueMap(workbench.context);
    const allocation = valueMap(caseView.risk_allocation);
    const reunderwriting = caseView.entry_reunderwriting || {};
    const reunderwritingSummary = valueMap(reunderwriting.summary);
    const decisionRoute = valueMap((caseView.decision_route_evidence || {}).summary);
    const blocks = [
      ['为什么发现', `本窗口状态为 ${translate(workbench.projection.state)}；IV/RV、跳跃占比与事件状态都是具名公开代理，不是 Edge 或预测。`],
      ['为什么选它', `四腿作为一个不可拆的铁鹰整体冻结。短腿、翼宽与 Combo 费都属于同一候选，不能拆成两笔 Vertical。`],
      ['为什么允许打开 Case', `Shadow 风险预算结果为 ${translate(allocation.result)}；市场上下文为 ${translate(context.knowledge)}。这是研究名义限额，不是保证金或资本预留。`],
      ['Decision 路由证据', `${translate(decisionRoute.kind)} / ${translate(decisionRoute.status)}；完整目标数量 ${decisionRoute.target_amount || '未知'} BTC。仅为公众 component books 合成估价。`],
      ['Entry 二次承销', reunderwriting.available === false
        ? '尚未取得严格更晚的 Entry 证据。'
        : `结果为 ${translate(reunderwritingSummary.status)}；${reunderwriting.comparison || '指标对比未知'}。冻结四腿与预算未被替换。`]
    ];
    blocks.forEach(([title, copy]) => {
      const block = create('article', 'story-block');
      appendText(block, 'h3', '', title);
      appendText(block, 'p', '', copy);
      target.append(block);
    });
  }

  function renderManagement(caseView) {
    const display = caseView.display;
    const outcome = valueMap(caseView.outcome);
    const entryReunderwriting = caseView.entry_reunderwriting || {};
    const routeProjection = (caseView.entry_route_evidence || {}).available
      ? caseView.entry_route_evidence
      : caseView.decision_route_evidence || {};
    const route = valueMap(routeProjection.summary);
    const summary = byId('management-summary');
    summary.replaceChildren(
      metricItem('入场结果', translate(display.entry_status)),
      metricItem('Entry VRP', entryReunderwriting.entry_vrp || '未知'),
      metricItem('Position 状态', translate(display.position_state), display.tone),
      metricItem('最后生命周期观察', formatTimestamp(valueMap(caseView.facts).last_observed_at)),
      metricItem('首次退出原因', translate(display.exit_reason)),
      metricItem('Shadow result', outcome.native_result_btc ? `${outcome.native_result_btc} BTC` : '未知'),
      metricItem('数据 Gap', display.gap_observed ? '有' : '无', display.gap_observed ? 'warning' : 'positive')
    );
    const target = byId('management-timeline');
    target.replaceChildren();
    const track = create('div', 'timeline-track');
    display.timeline.forEach(item => {
      const event = create('div', 'timeline-event');
      event.classList.toggle('is-done', item.state === 'DONE');
      event.classList.toggle('is-current', item.state === 'CURRENT');
      appendText(event, 'strong', '', item.label);
      appendText(event, 'span', '', item.at ? formatTimestamp(item.at) : item.state === 'PENDING' ? '等待后续事实' : '时间未知');
      track.append(event);
    });
    target.append(track);
    const quality = byId('evidence-quality');
    quality.replaceChildren();
    const knownBlock = create('div', 'quality-block');
    appendText(knownBlock, 'strong', '', display.gap_observed ? '存在数据 Gap' : '因果前缀连续');
    appendText(knownBlock, 'span', '', 'DataHealth 不等于 TradingRisk；Gap 不会擦除 Position 或退出责任');
    const pricingBlock = create('div', 'quality-block');
    appendText(pricingBlock, 'strong', '', `${translate(route.kind || 'COMPONENT_SYNTHETIC_ESTIMATE')} · ${translate(route.status || 'UNKNOWN')}`);
    appendText(pricingBlock, 'span', '', `${route.model_id || 'SYNTHETIC_FOUR_LEG_COMPONENT_BOOK_ESTIMATE_V1'}；不代表 Combo 报价、RFQ、订单、成交、账户仓位或已预留流动性`);
    quality.append(knownBlock, pricingBlock);
  }

  function renderOutcomeExplanation(caseView) {
    const explanation = caseView.outcome_explanation || {};
    const summary = valueMap(explanation.summary);
    const metrics = byId('outcome-explanation-summary');
    metrics.replaceChildren(
      metricItem('解释状态', explanation.complete === true ? '完整' : explanation.complete === false ? '等待官方交割补全' : '路径累积中', explanation.complete === true ? 'positive' : 'warning'),
      metricItem('MFE', summary.maximum_favorable_excursion_btc ? `${summary.maximum_favorable_excursion_btc} BTC` : '未知'),
      metricItem('MAE', summary.maximum_adverse_excursion_btc ? `${summary.maximum_adverse_excursion_btc} BTC` : '未知'),
      metricItem('最大短腿 Delta', summary.maximum_short_abs_delta || '未知'),
      metricItem('Put 最近距离', summary.minimum_put_short_distance_usd ? `${summary.minimum_put_short_distance_usd} USD` : '未知'),
      metricItem('Call 最近距离', summary.minimum_call_short_distance_usd ? `${summary.minimum_call_short_distance_usd} USD` : '未知'),
      metricItem('观察 / 代表点', `${explanation.observation_count || 0} / ${(explanation.path || []).length}`),
      metricItem('路径 Gap', String((explanation.gaps || []).length), (explanation.gaps || []).length ? 'warning' : 'positive'),
      metricItem('冻结替代结果', String((explanation.alternative_outcomes || []).length))
    );
    const path = byId('outcome-explanation-path');
    path.replaceChildren();
    (explanation.path || []).forEach(point => {
      const card = create('article', 'explanation-point');
      appendText(card, 'strong', '', `${translate(point.phase)} · ${translate(point.observation_status)}`);
      appendText(card, 'span', '', formatTimestamp(point.observed_at));
      appendText(card, 'span', '', point.native_result_btc === null ? translate(point.valuation_reason || point.reason) : `${point.native_result_btc} BTC`);
      appendText(card, 'small', '', point.observation_status === 'KNOWN'
        ? `Put/Call Delta ${point.short_put_abs_delta} / ${point.short_call_abs_delta} · IV ${point.short_put_mark_iv} / ${point.short_call_mark_iv} · RV ${point.trailing_realized_variance_proxy}`
        : translate(point.reason));
      path.append(card);
    });
    if (!(explanation.path || []).length) {
      path.append(create('p', 'trace-empty', '尚无可展示的解释路径。'));
    }
    const counterfactuals = byId('outcome-counterfactuals');
    counterfactuals.replaceChildren();
    (explanation.counterfactuals || []).forEach(item => {
      const card = create('article', 'quality-block');
      appendText(card, 'strong', '', `${translate(item.kind)} · ${translate(item.status)}`);
      appendText(card, 'span', '', item.native_result_btc === null ? translate(item.reason) : `${item.native_result_btc} BTC · ${item.boundary_reference_result_usd} USD`);
      counterfactuals.append(card);
    });
  }

  function renderResponsibility(caseView) {
    const display = caseView.display;
    const title = display.stage === 'EXIT' ? '退出意图已冻结' : display.stage === 'MONITORING' ? '持续管理完整组合' : display.stage === 'OUTCOME' ? '终局经济结果已冻结' : '等待完整组合入场估价';
    byId('responsibility-title').textContent = title;
    byId('responsibility-copy').textContent = display.responsibility;
    const facts = byId('responsibility-facts');
    facts.replaceChildren();
    const values = [
      ['入场截止', formatTimestamp(display.entry_deadline)],
      ['到期 / 交割边界', formatTimestamp(display.expiry)],
      ['首次退出原因', translate(display.exit_reason)],
      ['终局方法', translate(display.outcome_method)]
    ];
    values.forEach(([label, value]) => {
      const wrapper = create('div');
      appendText(wrapper, 'dt', '', label);
      appendText(wrapper, 'dd', '', value);
      facts.append(wrapper);
    });
    const action = byId('responsibility-action');
    action.textContent = display.stage === 'OUTCOME' ? '进入复盘与进化' : '查看原始证据';
    action.onclick = display.stage === 'OUTCOME' ? () => navigate('review') : openEvidenceDrawer;
  }

  function renderReview() {
    const completed = completedReviewProjection();
    const unavailable = byId('review-unavailable');
    const report = byId('review-report');
    const selector = byId('review-session-select');
    selector.replaceChildren();
    if (completed.status !== 'AVAILABLE' || !completed.reviews.length) {
      unavailable.hidden = false;
      report.hidden = true;
      selector.disabled = true;
      appendText(selector, 'option', '', '暂无已完成复盘');
      byId('review-unavailable-reason').textContent = translate(completed.reason || completed.status);
      byId('review-freeze-time').textContent = '复盘投影：不可用；交易 Runtime 不受影响';
      return;
    }
    unavailable.hidden = true;
    report.hidden = false;
    selector.disabled = false;
    completed.reviews.forEach(item => {
      const option = create('option', '', `${formatDate(item.session_id)} · ${translate(item.verdict)}`);
      option.value = item.review_id;
      selector.append(option);
    });
    if (!completed.reviews.some(item => item.review_id === selectedReviewId)) {
      selectedReviewId = completed.reviews[0].review_id;
    }
    selector.value = selectedReviewId;
    selector.onchange = () => {
      selectedReviewId = selector.value;
      renderSelectedReview(completed);
    };
    byId('review-freeze-time').textContent = `Web 投影：${formatTimestamp(completed.generated_at)} · 展示 ${completed.reviews.length}/${completed.retained_review_count}`;
    renderSelectedReview(completed);
  }

  function renderSelectedReview(completed) {
    const review = completed.reviews.find(item => item.review_id === selectedReviewId) || completed.reviews[0];
    selectedReviewId = review.review_id;
    const verdictTone = review.verdict.includes('TOO_') || review.verdict.includes('MIXED') ? 'danger' : review.verdict.includes('UNKNOWN') || review.verdict.includes('PARTIALLY') || review.verdict.includes('OBSERVED') ? 'warning' : 'positive';
    byId('review-session-subtitle').textContent = `Review ${shortValue(review.review_id)} · 冻结 Policy ${shortValue(review.policy_id)}`;
    byId('review-verdict-title').textContent = `${formatDate(review.session_id)} Session`;
    byId('review-verdict-badge').textContent = translate(review.verdict);
    byId('review-verdict-badge').dataset.tone = verdictTone;
    byId('review-verdict-label').textContent = translate(review.verdict);
    byId('review-verdict-label').dataset.tone = verdictTone;
    byId('review-verdict-reason').textContent = review.verdict_reason;
    renderDefinitionList('review-automation-summary', [
      ['自动复盘状态', translate(completed.automation?.status)],
      ['最近运行', formatTimestamp(completed.automation?.updated_at)],
      ['最近成功 Session', completed.automation?.last_success_session_id ? formatDate(completed.automation.last_success_session_id) : '尚无'],
      ['本报告落盘', formatTimestamp(review.recorded_at)]
    ]);

    const population = review.population;
    byId('review-population-title').textContent = `${population.expected_window_count} 个预登记窗口`;
    byId('review-coverage-badge').textContent = `可审判 ${population.auditable_window_count}/${population.expected_window_count}`;
    renderMetricCards('review-population-grid', [
      ['预登记 Window', population.expected_window_count, '学习分母'],
      ['DecisionRecord', population.recorded_decision_count, '事前 Base 决策'],
      ['WindowOutcome', population.recorded_outcome_count, '实际未来路径'],
      ['IV/RV 曲线点', population.curve_observation_count, '事前可见代理'],
      ['可审判', population.auditable_window_count, '证据完整'],
      ['证据不足', population.unknown_window_count, '保留 UNKNOWN']
    ]);
    renderClassificationCards(review.classifications);
    renderBounds(review.bounds);
    renderFunnel(review.funnel);
    renderKeyCounts('review-base-blockers', review.base_blocker_counts);
    renderKeyCounts('review-evidence-reasons', review.evidence_reason_counts);
    renderOfficialEvidence(review.official_index_evidence);
    renderReviewCurve(review.curve, review.windows);
    renderReviewWindows(review.windows);
    byId('review-window-count').textContent = `${review.windows.length} / ${population.expected_window_count}`;
    byId('review-evidence-boundary').textContent = review.evidence_boundary;
    const challenger = byId('review-challenger-status');
    challenger.textContent = review.challenger_comparison_eligible ? 'ELIGIBLE · 仅可另行冻结实验' : 'NOT ELIGIBLE · 不启动 Challenger 对照';
    challenger.dataset.tone = review.challenger_comparison_eligible ? 'positive' : 'warning';
  }

  function renderDefinitionList(targetId, rows) {
    const target = byId(targetId);
    target.replaceChildren();
    rows.forEach(([label, value]) => {
      const row = create('div');
      appendText(row, 'dt', '', label);
      appendText(row, 'dd', '', value);
      target.append(row);
    });
  }

  function renderMetricCards(targetId, rows) {
    const target = byId(targetId);
    target.replaceChildren();
    rows.forEach(([label, value, note]) => {
      const card = create('div', 'review-metric-card');
      appendText(card, 'span', '', label);
      appendText(card, 'strong', '', countLabel(value));
      appendText(card, 'small', '', note);
      target.append(card);
    });
  }

  function renderClassificationCards(values) {
    const target = byId('review-classification-grid');
    target.replaceChildren();
    [
      ['captured_opportunity_window_count', '抓对机会', 'positive'],
      ['correct_avoidance_window_count', '正确避开', 'info'],
      ['missed_opportunity_window_count', '漏掉机会', 'warning'],
      ['over_risk_window_count', '过度风险', 'danger'],
      ['unknown_window_count', '证据不足', 'neutral']
    ].forEach(([key, label, tone]) => {
      const card = create('div', 'review-classification-card');
      card.dataset.tone = tone;
      appendText(card, 'strong', '', countLabel(values[key]));
      appendText(card, 'span', '', label);
      target.append(card);
    });
  }

  function formatRate(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(2)}%` : '未知';
  }

  function renderBounds(values) {
    const target = byId('review-bounds-table');
    target.replaceChildren();
    const header = create('div', 'review-bounds-row is-header');
    ['逻辑识别区间', '下界', '上界'].forEach(value => appendText(header, 'span', '', value));
    target.append(header);
    [
      ['漏掉机会率', values.miss_rate_lower_bound, values.miss_rate_upper_bound],
      ['过度冒险率', values.over_risk_rate_lower_bound, values.over_risk_rate_upper_bound],
      ['机会出现率', values.opportunity_rate_lower_bound, values.opportunity_rate_upper_bound]
    ].forEach(([label, lower, upper]) => {
      const row = create('div', 'review-bounds-row');
      appendText(row, 'span', '', label);
      appendText(row, 'strong', '', formatRate(lower));
      appendText(row, 'strong', '', formatRate(upper));
      target.append(row);
    });
  }

  function renderFunnel(values) {
    const target = byId('review-funnel-grid');
    target.replaceChildren();
    [
      ['legal_structure_count', '合法四腿'],
      ['price_evaluable_count', '完整数量可估价'],
      ['control_candidate_count', '通过硬控制'],
      ['hindsight_opportunity_structure_count', 'Policy 合格且事后成立'],
      ['hindsight_positive_policy_reject_structure_count', '事后有利但 Policy 拒绝']
    ].forEach(([key, label], index) => {
      const node = create('div', 'review-funnel-node');
      appendText(node, 'span', '', `0${index + 1}`);
      appendText(node, 'strong', '', countLabel(values[key]));
      appendText(node, 'small', '', label);
      target.append(node);
    });
  }

  function renderKeyCounts(targetId, values) {
    const target = byId(targetId);
    target.replaceChildren();
    const rows = Object.entries(values || {}).sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]));
    if (!rows.length) {
      target.append(create('div', 'review-empty-row', '无'));
      return;
    }
    rows.slice(0, 8).forEach(([key, count]) => {
      const row = create('div');
      appendText(row, 'span', '', translate(key));
      appendText(row, 'strong', '', countLabel(count));
      target.append(row);
    });
  }

  function renderOfficialEvidence(evidence) {
    const target = byId('review-official-evidence');
    target.replaceChildren();
    if (!evidence) {
      appendText(target, 'strong', '', '官方事后指数证据：未提供');
      appendText(target, 'p', '', '缺失不会被终值或浏览器展示补齐；相关 Window 保持 UNKNOWN。');
      return;
    }
    appendText(target, 'strong', '', `Deribit 官方指数证据 · ${evidence.point_count} 点`);
    appendText(target, 'p', '', `${evidence.session_coverage_complete ? '完整覆盖 Session' : `存在 ${evidence.coverage_gaps.length} 个 Gap`} · cadence ${evidence.cadence_ms}ms · ${shortValue(evidence.evidence_id)}`);
  }

  function renderReviewCurve(points, windows) {
    const svg = byId('review-curve-chart');
    svg.replaceChildren();
    const namespace = 'http://www.w3.org/2000/svg';
    const pointByWindow = new Map((points || []).map(point => [point.decision_window_id, point]));
    const values = (windows || []).map(windowReview => {
      const point = pointByWindow.get(windowReview.decision_window_id);
      return {
        iv: point ? Number(point.implied_variance_proxy) : Number.NaN,
        rv: point ? Number(point.trailing_realized_variance_proxy) : Number.NaN
      };
    });
    const finiteValues = values.flatMap(point => [point.iv, point.rv]).filter(Number.isFinite);
    if (finiteValues.length < 2 || values.length < 2) {
      const text = document.createElementNS(namespace, 'text');
      text.setAttribute('x', '500');
      text.setAttribute('y', '112');
      text.setAttribute('text-anchor', 'middle');
      text.textContent = '可用 IV / RV 曲线点不足';
      svg.append(text);
      return;
    }
    const maximum = Math.max(...finiteValues, 0.000001);
    [0, 0.25, 0.5, 0.75, 1].forEach(ratio => {
      const line = document.createElementNS(namespace, 'line');
      const y = 190 - ratio * 160;
      line.setAttribute('x1', '50');
      line.setAttribute('x2', '970');
      line.setAttribute('y1', String(y));
      line.setAttribute('y2', String(y));
      line.setAttribute('class', 'review-chart-grid');
      svg.append(line);
    });
    const segments = key => {
      const output = [];
      let current = [];
      values.forEach((point, index) => {
        if (!Number.isFinite(point[key])) {
          if (current.length > 1) output.push(current);
          current = [];
          return;
        }
        const x = 50 + index / (values.length - 1) * 920;
        const y = 190 - point[key] / maximum * 160;
        current.push(`${x.toFixed(2)},${y.toFixed(2)}`);
      });
      if (current.length > 1) output.push(current);
      return output;
    };
    [['iv', 'review-chart-iv'], ['rv', 'review-chart-rv']].forEach(([key, className]) => {
      segments(key).forEach(segment => {
        const line = document.createElementNS(namespace, 'polyline');
        line.setAttribute('points', segment.join(' '));
        line.setAttribute('class', className);
        svg.append(line);
      });
    });
  }

  function renderReviewWindows(windows) {
    const target = byId('review-window-table');
    target.replaceChildren();
    const header = create('div', 'review-window-row is-header');
    ['窗口', 'Base', '证据', '事后分类', '结构漏斗', '首要原因'].forEach(value => appendText(header, 'span', '', value));
    target.append(header);
    windows.forEach(windowReview => {
      const row = create('div', 'review-window-row');
      appendText(row, 'span', '', formatTimestamp(windowReview.starts_at));
      appendText(row, 'span', '', translate(windowReview.base_result));
      appendText(row, 'span', '', translate(windowReview.evidence_status));
      const classification = appendText(row, 'strong', '', translate(windowReview.classification));
      classification.dataset.tone = windowReview.classification === 'MISSED_OPPORTUNITY' ? 'warning' : windowReview.classification === 'OVER_RISK_SELECTION' ? 'danger' : windowReview.classification === 'UNKNOWN' ? 'neutral' : 'positive';
      appendText(row, 'span', '', `${windowReview.legal_structure_count} → ${windowReview.price_evaluable_count} → ${windowReview.control_candidate_count}`);
      const reasons = windowReview.evidence_reasons?.length ? windowReview.evidence_reasons : windowReview.base_blockers;
      appendText(row, 'span', '', reasons?.length ? reasons.slice(0, 2).map(translate).join(' · ') : '无');
      target.append(row);
    });
  }

  function renderEvidence() {
    renderEvidenceRows('evidence-runtime', workbench.runtime.facts);
    renderEvidenceRows('evidence-window', workbench.window);
    renderEvidenceRows('evidence-context', workbench.context);
    renderEvidenceRows('evidence-methodology', workbench.methodology);
    const warnings = byId('evidence-warnings');
    warnings.replaceChildren();
    if (!workbench.warnings.length) warnings.append(create('span', 'warning-chip', '无额外警告'));
    workbench.warnings.forEach(warning => warnings.append(create('span', 'warning-chip', translate(warning.code))));
  }

  function renderEvidenceRows(targetId, rows) {
    const target = byId(targetId);
    target.replaceChildren();
    (rows || []).forEach(row => {
      const wrapper = create('div');
      appendText(wrapper, 'dt', '', row.label);
      appendText(wrapper, 'dd', '', displayRowValue(row));
      target.append(wrapper);
    });
    if (!rows?.length) {
      const wrapper = create('div');
      appendText(wrapper, 'dt', '', '可用性');
      appendText(wrapper, 'dd', '', '未知');
      target.append(wrapper);
    }
  }

  function openEvidenceDrawer() {
    lastFocusedElement = document.activeElement;
    const drawer = byId('evidence-drawer');
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawer.querySelector('.drawer-close').focus();
  }

  function closeEvidenceDrawer() {
    const drawer = byId('evidence-drawer');
    drawer.hidden = true;
    document.body.style.overflow = '';
    if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
  }

  function wireInteractions() {
    document.querySelectorAll('[data-route]').forEach(button => {
      button.addEventListener('click', () => navigate(button.dataset.route));
    });
    byId('product-evidence-button').addEventListener('click', openEvidenceDrawer);
    byId('footer-evidence-button').addEventListener('click', openEvidenceDrawer);
    document.querySelectorAll('[data-close-drawer]').forEach(button => button.addEventListener('click', closeEvidenceDrawer));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !byId('evidence-drawer').hidden) closeEvidenceDrawer();
    });
    window.addEventListener('hashchange', applyRoute);
  }

  function refreshDocumentWhenCurrent() {
    const currentScript = document.querySelector('script[src^="workbench-data.js"]');
    const refreshScript = document.createElement('script');
    refreshScript.src = `workbench-data.js?refresh=${Date.now()}`;
    refreshScript.onload = () => {
      if (documentSignature(window.OPTIMATRIX_WORKBENCH) !== initialDocumentSignature) {
        window.location.reload();
      }
      refreshScript.remove();
    };
    refreshScript.onerror = () => refreshScript.remove();
    currentScript?.parentNode?.insertBefore(refreshScript, currentScript);
  }

  renderShell();
  renderLedger();
  renderReview();
  renderEvidence();
  wireInteractions();
  applyRoute();
  window.setInterval(refreshDocumentWhenCurrent, 10000);
})();

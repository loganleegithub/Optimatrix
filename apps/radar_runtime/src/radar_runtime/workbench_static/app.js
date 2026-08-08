const SUPPORTED_SCHEMA_VERSION = 5;

const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[character]);

const isMissing = value => value === null || value === undefined || value === '';
const displayText = value => {
  if (isMissing(value)) return 'UNKNOWN';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};
const safeText = value => escapeHtml(displayText(value));
const rawText = value => isMissing(value)
  ? 'null'
  : (typeof value === 'object' ? JSON.stringify(value) : String(value));

const card = (label, value, options = {}) => {
  const className = options.primary ? 'card card-primary' : 'card';
  const meta = options.meta ? `<span class="meta">${safeText(options.meta)}</span>` : '';
  return `<div class="${className}"><div class="label">${escapeHtml(label)}</div>` +
    `<div class="value">${safeText(value)}</div>${meta}</div>`;
};

const summaryStat = (label, value, state = null) => {
  const stateMarkup = state
    ? `<span class="status-pill ${escapeHtml(state)}">${safeText(state)}</span>`
    : '';
  return `<div class="summary-stat"><span class="label">${escapeHtml(label)}</span>` +
    `<span class="summary-value">${safeText(value)}</span>${stateMarkup}</div>`;
};

const statusPill = value => {
  const text = displayText(value);
  const className = text.replace(/[^A-Za-z0-9_-]/g, '-');
  return `<span class="status-pill ${escapeHtml(className)}">${safeText(text)}</span>`;
};

const reasonLabels = {
  NONE: '无',
  QUEUE_LAG_CURRENTNESS: '处理队列延迟, 行情时效性不可确认',
  CLOCK_GAP: '可信时间不连续',
  INDEX_WARMUP: '指数基线处于启动或恢复 warmup',
  INDEX_WINDOW_GAP: '指数基线窗口存在缺口',
  INDEX_SOURCE_STALE: '指数来源已陈旧',
  INDEX_CONTINUITY_GAP: '指数行情连续性中断',
  INDEX_HISTORY_REVISION: '官方指数历史已完成点发生修订，等待下一响应确认',
  POST_STATUS_BOOTSTRAP_REQUIRED: '平台状态变化后等待期权簿重新建立',
  OPTION_BOOK_UNKNOWN: '期权簿不可确认',
  OPTION_AMOUNT_METADATA_UNKNOWN: '期权数量元数据不可确认',
  OPTION_PRICE_TICK_METADATA_UNKNOWN: '官方价格 tick 规则不可确认',
  INSUFFICIENT_TARGET_ASK_DEPTH: '目标数量买回深度不足',
  NON_POSITIVE_TARGET_SPREAD: '目标规模双边盘口锁定或交叉',
  ONE_TICK_STRESSED_BID_NON_POSITIVE: '卖价下压一个合法 tick 后不再为正',
  DELTA_INELIGIBLE: 'Delta 不在冻结的可行动风险桶',
  REVIEW_ONLY_TTE_BAND: '临近 admission cutoff，仅供审查不可激活 clue',
  REVIEW_ONLY_DELTA_BUCKET: 'Delta 位于冻结的 clue 风险桶之外，仅供审查',
  REVIEW_ONLY_TTE_AND_DELTA: 'TTE 与 Delta 均位于 review-only 范围',
  FORWARD_TICKER_UNKNOWN: '远期价格 ticker 不可确认',
  INVALID_FORWARD: '远期价格无效',
  NUMERICAL_BOUNDARY_UNRESOLVED: '数值区间跨越决策边界',
  NUMERICAL_UNKNOWN: '数值模型输入不可确认',
  OTHER_INDEX_UNKNOWN: '其他指数输入不可确认',
  OTHER_TICKER_UNKNOWN: '其他 ticker 输入不可确认',
  OTHER_OPTION_UNKNOWN: '其他期权输入不可确认',
  OTHER_RUNTIME_UNKNOWN: '其他运行时输入不可确认',
  OTHER_RADAR_UNKNOWN: '其他 Radar 输入不可确认',
  SESSION_GAP: '公共行情会话中断',
  SESSION_RPC_FAILURE: '公共接口响应超时',
  COMBO_QUOTE_RECEIPT_UNKNOWN: '组合报价回执不可确认',
  NO_ACTIVE_COMBO: '无现成官方组合 - 仅诊断; 不阻塞双腿 Shadow',
  NO_TARGET_SIZE_CREDIT_QUOTE: '现成官方组合没有目标数量正信用报价 - 仅诊断',
  NO_PROTECTIVE_COMPONENT: '没有可冻结的同到期保护腿',
  NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE: '双腿盘口不能同时覆盖目标数量',
  COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN: '双腿保守成交反事实不可确认',
  NO_APPLICABLE_MARKET_SCOPE_OBSERVED: '尚未观察到适用的市场范围',
  NO_ANOMALY_ACTIVATION_OBSERVED: '已完成 Radar 计算，尚未出现异常激活',
  ATOMIC_AVAILABILITY_UNKNOWN: '异常已激活，但组合可用性仍不可确认',
  ATOMIC_AVAILABILITY_NOT_SETTLED: '异常已激活，尚未结算组合可用性',
  PUBLIC_ATOMIC_QUOTE_NOT_OBSERVED: '组合可用性已结算，尚无目标数量原子报价',
  MINIMUM_NET_ENTRY_CREDIT: '净入场权利金低于 Policy 最低值',
  MINIMUM_NET_CREDIT_TO_PAYOFF_CAP: '净权利金相对保护宽度不足',
  CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE: '净权利金未覆盖未来成本准备',
  UNDERWRITING_RESERVED_LOSS_LIMIT: '承保准备损失超过 Policy 上限',
  ADMISSION_PENDING_OR_NOT_REFRESHED: 'Candidate 尚未获得严格未来的成对双腿盘口刷新',
  OUTCOME_PENDING: 'Shadow Case 已打开，Outcome 尚未终结',
  NO_MATERIAL_BLOCKER_OBSERVED: '当前已观察漏斗没有实质转换阻塞',
  POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY: '该承保槽位已被 Shadow Entry 使用',
  RADAR_EPISODE_NOT_ACTIVE: '当前无活跃 Radar 候选, 承保尚未评估',
  CONTROL_OPENED: '无交易研究对照 Case 已建立',
  REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION: '刷新为 Candidate, 必须走规范 admission',
  KNOWN_NO_CONTROL: '刷新结果已知, 未建立 no-trade control Case',
  ENTRY_EMITTED: 'Shadow Case 已建立',
  KNOWN_COMPLETE_NO_ENTRY: '严格未来刷新已完成, 未建立 Case',
  KNOWN_INVALIDATED_BEFORE_REFRESH: 'Candidate 在刷新前已失效',
  UNKNOWN_CONSUMED: '刷新事实 UNKNOWN, 本次选择已消费',
  NOT_STARTED: '服务尚未启动'
};
const reasonText = value => reasonLabels[value] || String(value);

const productLabels = {
  'inverse-btc': 'BTC 币本位反向期权',
  'linear-btc-usdc': 'BTC-USDC 线性期权'
};
const productLabel = value => productLabels[value] || displayText(value);

const actionLabels = {
  CANDIDATE: 'Candidate',
  WATCH: '观察',
  ABSTAIN: '观望',
  HOLD: '继续持有',
  CLOSE: '建议平仓',
  UNKNOWN: 'UNKNOWN',
  NOT_EVALUATED: '未评估'
};
const actionText = value => actionLabels[value] || displayText(value);

const detectorLabels = {
  ANOMALY_ACTIVE: 'Radar clue 已激活',
  NO_ANOMALY: '无 Radar clue',
  UNKNOWN: 'Radar 状态 UNKNOWN'
};
const detectorText = value => detectorLabels[value] || displayText(value);

const deltaBucketLabels = {
  EXTREME_TAIL_LT_05: '<5Δ 极深虚值',
  TAIL_05_15: '5–15Δ 尾部',
  WING_15_30: '15–30Δ 翼部',
  ATM_GT_40: '>40Δ 近 ATM',
  UNKNOWN: 'UNKNOWN'
};
const deltaBucketText = value => deltaBucketLabels[value] || displayText(value);

const formatEpochMs = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(new Date(Number(value)));
};

const formatDurationMs = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  const milliseconds = Math.max(0, Number(value));
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  if (milliseconds < 3600000) return `${(milliseconds / 60000).toFixed(1)} 分钟`;
  return `${(milliseconds / 3600000).toFixed(2)} 小时`;
};

const formatDurationInterval = value => {
  if (!value || !Number.isFinite(Number(value.lower_ms)) ||
      !Number.isFinite(Number(value.upper_ms))) return 'UNKNOWN';
  const lower = formatDurationMs(value.lower_ms);
  const upper = formatDurationMs(value.upper_ms);
  return lower === upper ? lower : `${lower} - ${upper}`;
};

const formatDecimal = value => {
  if (isMissing(value)) return 'UNKNOWN';
  const text = String(value);
  const match = text.match(/^(-?)(\d+)(\.\d+)?$/);
  if (!match) return text;
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] || ''}`;
};

const formatCompactNumber = (value, digits = 2) => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  });
};

const formatPercent = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  return `${(Number(value) * 100).toFixed(2)}%`;
};

const formatInterval = (value, formatter) => {
  if (!value || isMissing(value.lower) || isMissing(value.upper)) return 'UNKNOWN';
  const lower = formatter(value.lower);
  const upper = formatter(value.upper);
  return lower === upper ? lower : `${lower} - ${upper}`;
};

const formatCompactInterval = (value, formatter, suffix = '') => {
  if (!value || isMissing(value.lower) || isMissing(value.upper)) return 'UNKNOWN';
  const lower = formatter(value.lower);
  const upper = formatter(value.upper);
  return lower === upper ? `${lower}${suffix}` : `${lower}${suffix} – ${upper}${suffix}`;
};

const shortIdentity = value => {
  if (isMissing(value)) return 'UNKNOWN';
  const text = String(value);
  return text.length <= 24 ? text : `${text.slice(0, 14)}…${text.slice(-6)}`;
};

const unavailableRadarCalculation = row =>
  row.detector_state === 'NO_ANOMALY' && row.known_evaluation ? 'N/A' : 'UNKNOWN';

const radarCellValue = (row, field, value) => {
  if (field === 'expiration_timestamp_ms') return formatEpochMs(value);
  if (field === 'tte_interval_ms') return formatDurationInterval(value);
  if (field === 'attention_rank') return isMissing(value) ? 'N/A' : `#${formatDecimal(value)}`;
  if (field === 'strike_price') return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  if (['model_executable_sell_price', 'model_executable_buy_price',
      'model_one_tick_stressed_sell_price'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatDecimal(value);
  }
  if (['executable_iv_interval', 'executable_ask_iv_interval',
      'one_tick_stressed_iv_interval'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatInterval(value, formatPercent);
  }
  if (field === 'baseline_annualized_volatility') {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatPercent(value);
  }
  if (field === 'baseline_return_interval_minutes') {
    return isMissing(value) ? unavailableRadarCalculation(row) : `${formatDecimal(value)} 分钟`;
  }
  if (field === 'baseline_selected_lookback_minutes') {
    if (!isMissing(value)) return `${formatDecimal(value)} 分钟`;
    return row.baseline_source === 'ANNUALIZED_VARIANCE_FLOOR'
      ? '固定年化方差下限'
      : unavailableRadarCalculation(row);
  }
  if (['richness_ratio_interval', 'raw_richness_ratio_interval'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatInterval(value, formatDecimal);
  }
  if (['target_spread_ticks', 'bid_premium_ticks', 'surface_residual',
      'best_legged_credit_to_payoff_cap_fraction'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatDecimal(value);
  }
  if (['regime_jump_share', 'regime_adverse_semivariance_share'].includes(field)) {
    return isMissing(value) ? 'UNKNOWN' : formatPercent(value);
  }
  if (field === 'detector_reason' || field === 'option_book_reason') {
    return isMissing(value) ? unavailableRadarCalculation(row) : reasonText(value);
  }
  if (field === 'active_episode_identity' || field === 'anomaly_started_monotonic_ms') {
    return isMissing(value)
      ? (row.detector_state === 'ANOMALY_ACTIVE' ? 'UNKNOWN' : 'N/A')
      : shortIdentity(value);
  }
  if (field === 'anomaly_active_duration_ms') {
    return isMissing(value)
      ? (row.detector_state === 'ANOMALY_ACTIVE' ? 'UNKNOWN' : 'N/A')
      : formatDurationMs(value);
  }
  if (field === 'option_type') {
    return value === 'call' ? 'Call' : (value === 'put' ? 'Put' : displayText(value));
  }
  return displayText(value);
};

const radarPrimaryCellValue = (row, field, value) => {
  if (field === 'richness_ratio_interval') {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatCompactInterval(value, item => formatCompactNumber(item, 2), '×');
  }
  if (field === 'executable_iv_interval') {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatCompactInterval(value, item => `${(Number(item) * 100).toFixed(1)}%`);
  }
  if (field === 'baseline_annualized_volatility') {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : `${(Number(value) * 100).toFixed(1)}%`;
  }
  if (field === 'delta_interval') {
    if (value && !isMissing(value.lower) && !isMissing(value.upper)) {
      return formatCompactInterval(value, item => formatCompactNumber(item, 3));
    }
    return deltaBucketText(row.delta_bucket);
  }
  if (field === 'surface_residual') {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : `${(Number(value) * 100).toFixed(1)}%`;
  }
  if (field === 'detector_state') return detectorText(value);
  return radarCellValue(row, field, value);
};

const underwritingReasonText = (row, value) => {
  if (row.availability === 'NOT_EVALUATED') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    if (reasons.includes('RADAR_EPISODE_NOT_ACTIVE')) {
      return reasonText('RADAR_EPISODE_NOT_ACTIVE');
    }
    return reasons.length
      ? reasons.map(reasonText).join('; ')
      : '已知前置条件未满足, 承保未评估';
  }
  if (row.availability === 'UNKNOWN') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    return reasons.length
      ? reasons.map(reasonText).join('; ')
      : '承保所需事实不可确认';
  }
  if (row.availability === 'EVALUABLE' && !isMissing(row.action)) {
    const failures = Array.isArray(row.failed_predicates) ? row.failed_predicates : [];
    return failures.length
      ? `已结算承保动作: ${row.action}; 未通过: ${failures.map(reasonText).join('; ')}`
      : `已结算承保动作: ${row.action}; 全部经济谓词通过`;
  }
  return isMissing(value) ? 'N/A' : reasonText(value);
};

const underwritingCellValue = (row, field, value) => {
  if (field === 'expiry_timestamp_ms') return isMissing(value) ? 'UNKNOWN' : formatEpochMs(value);
  if (field.endsWith('_strike_price') || field === 'target_quantity_btc') {
    return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  }
  if (field === 'radar_scope_or_short_leg_identity' || field.endsWith('_identity')) {
    return isMissing(value) ? 'UNKNOWN' : shortIdentity(value);
  }
  if (field === 'decision_reason') return underwritingReasonText(row, value);
  if (field === 'action') return isMissing(value)
    ? (row.availability === 'EVALUABLE' ? 'UNKNOWN' : 'N/A')
    : actionText(value);
  const unavailableFields = new Set([
    'action', 'gross_entry_credit_valuation', 'entry_fee_reserve_valuation',
    'net_entry_credit_valuation',
    'entry_boundary_valued_payoff_loss_ex_fees_valuation',
    'future_cost_reserve_valuation', 'underwriting_reserved_loss_valuation',
    'candidate_lifecycle', 'candidate_still_valid', 'candidate_invalidation_reason'
  ]);
  if (unavailableFields.has(field) && isMissing(value)) {
    return row.availability === 'EVALUABLE' ? 'UNKNOWN' : 'N/A';
  }
  return displayText(value);
};

const compactMoney = value => isMissing(value) ? 'UNKNOWN' : formatCompactNumber(value, 2);
const compactNative = value => isMissing(value) ? 'UNKNOWN' : formatCompactNumber(value, 8);

const shadowCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'target_quantity_btc') return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  if (field === 'simulated_entry_price_valuation_per_btc' ||
      field === 'simulated_entry_credit_valuation') {
    return isMissing(value)
      ? (isMissing(row.shadow_entry_identity) ? 'N/A' : 'UNKNOWN')
      : formatDecimal(value);
  }
  if (field === 'no_entry_reason') {
    return isMissing(value) ? (isMissing(row.shadow_entry_identity) ? 'UNKNOWN' : 'N/A')
      : reasonText(value);
  }
  return displayText(value);
};

const positionCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'hard_close_countdown_interval_ms') return formatDurationInterval(value);
  if (field.endsWith('_valuation')) return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  return displayText(value);
};

const outcomeCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'actual_pnl' && isMissing(value)) {
    return 'N/A — public Shadow 无订单、成交或实际持仓';
  }
  if (field.endsWith('_valuation')) return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  return displayText(value);
};

const outcomeValuationCellValue = (row, product) => {
  const value = product.name === 'inverse-btc'
    ? row.boundary_valued_net_pnl_usd
    : row.public_quote_net_pnl_valuation;
  return isMissing(value) ? 'UNKNOWN' : compactMoney(value);
};

const caseStateLabels = {
  NOT_OPENED: '未建立 Case',
  PENDING_OUTCOME: '等待严格未来 Outcome',
  MATURE_KNOWN: '已终结, 经济结果已知',
  MATURE_UNKNOWN: '已终结, 经济结果 UNKNOWN',
  CENSORED_AT_STOP: '停止时删失',
  CENSORED_AT_FAILURE: '失败时删失'
};
const caseStateText = value => caseStateLabels[value] || displayText(value);

const enrollmentLabels = {
  ADMITTED_CANDIDATE: '规范 Candidate Case',
  SELECTED_UNDERWRITING_DECISION_CONTROL: '无交易研究对照 Case'
};
const enrollmentText = value => enrollmentLabels[value] || displayText(value);

const radarPriority = {ANOMALY_ACTIVE: 0, UNKNOWN: 1, NO_ANOMALY: 2};
const underwritingPriority = {EVALUABLE: 0, UNKNOWN: 1, NOT_EVALUATED: 2};
const underwritingActionPriority = {CANDIDATE: 0, WATCH: 1, ABSTAIN: 2};

const orderedRadarRows = rows => [...rows].sort((left, right) =>
  (Number.isFinite(Number(left.attention_rank)) ? Number(left.attention_rank) : 999999) -
    (Number.isFinite(Number(right.attention_rank)) ? Number(right.attention_rank) : 999999) ||
  (radarPriority[left.detector_state] ?? 9) - (radarPriority[right.detector_state] ?? 9) ||
  Number(left.expiration_timestamp_ms || 0) - Number(right.expiration_timestamp_ms || 0) ||
  String(left.option_type || '').localeCompare(String(right.option_type || '')) ||
  String(left.strike_price || '').localeCompare(String(right.strike_price || ''), undefined, {numeric: true}) ||
  String(left.instrument_name || '').localeCompare(String(right.instrument_name || ''))
);

const orderedUnderwritingRows = rows => [...rows].sort((left, right) =>
  (underwritingPriority[left.availability] ?? 9) -
    (underwritingPriority[right.availability] ?? 9) ||
  (underwritingActionPriority[left.action] ?? 9) -
    (underwritingActionPriority[right.action] ?? 9) ||
  Number(left.expiry_timestamp_ms || 0) - Number(right.expiry_timestamp_ms || 0) ||
  String(left.short_leg_instrument_name || left.radar_scope_or_short_leg_identity || '').localeCompare(
    String(right.short_leg_instrument_name || right.radar_scope_or_short_leg_identity || '')
  )
);

const filterRows = (rows, field, selected) => selected === 'ALL'
  ? [...rows]
  : (selected === 'TOP_N'
    ? rows.filter(row => row.within_attention_top_n)
    : rows.filter(row => row[field] === selected));

const stableRowIdentity = (row, fallback) => [
  row.instrument_name,
  row.underwriting_action_identity,
  row.selected_underwriting_decision_identity,
  row.shadow_entry_identity,
  row.shadow_observation_identity,
  row.radar_scope_or_short_leg_identity,
  row.enrollment_identity,
  row.active_episode_identity
].find(value => !isMissing(value)) || fallback;

const details = (row, fields, stateKey) => {
  const body = fields.map(([label, key]) =>
    `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(rawText(row[key]))}</dd>`
  ).join('');
  return `<details class="raw-details" data-detail-key="${escapeHtml(stateKey)}">` +
    `<summary>原始详情</summary><dl>${body}</dl></details>`;
};

const table = (panel, columns, rows = panel.rows, detailFields = []) => {
  if (panel.panel_state === 'EMPTY_NO_SETTLED_OBJECT') {
    return `<div class="empty-state"><strong>当前没有已结算对象</strong>` +
      `${safeText(panel.empty_label)}</div>`;
  }
  if (!rows.length) {
    return '<div class="empty-state"><strong>当前筛选结果为空</strong>原始对象仍可通过其他筛选查看。</div>';
  }
  const header = columns.map(column => `<th scope="col">${escapeHtml(column[0])}</th>`).join('');
  const detailHeader = detailFields.length ? '<th scope="col">详情</th>' : '';
  const body = rows.map((row, rowIndex) => {
    const cells = columns.map(column => {
      const rendered = column[2]
        ? column[2](row, column[1], row[column[1]])
        : displayText(row[column[1]]);
      const renderedText = String(rendered);
      const semanticClass = renderedText.startsWith('N/A')
        ? 'na'
        : (['UNKNOWN', 'STALE', 'INTERRUPTED', 'CURRENT', 'PROVEN_ZERO',
          'ANOMALY_ACTIVE', 'EVALUABLE', 'DEGRADED', 'NOT_EVALUATED',
          'CANDIDATE', 'WATCH', 'ABSTAIN'].includes(renderedText) ? renderedText : '');
      const configuredClass = column[3] || '';
      const className = [semanticClass, configuredClass].filter(Boolean).join(' ');
      return `<td${className ? ` class="${escapeHtml(className)}"` : ''}>${safeText(rendered)}</td>`;
    }).join('');
    const detailKey = `${detailFields[0] ? detailFields[0][1] : 'row'}:${stableRowIdentity(row, rowIndex)}`;
    const detailCell = detailFields.length
      ? `<td>${details(row, detailFields, detailKey)}</td>`
      : '';
    return `<tr>${cells}${detailCell}</tr>`;
  }).join('');
  return `<div class="table-scroll"><table><thead><tr>${header}${detailHeader}</tr></thead>` +
    `<tbody>${body}</tbody></table></div>`;
};

const businessPanelIds = [
  'funnel', 'decision-control', 'zero', 'radar', 'underwriting', 'shadow', 'positions',
  'outcomes'
];
let lastSuccessfulFetchAtMs = null;
let lastPublicationRuntimeIdentity = null;
let lastPublicationSequence = null;
let lastPublicationChangeAtMs = null;
let radarFilterValue = 'TOP_N';
let underwritingFilterValue = 'ALL';
let lastRenderedDocument = null;
const ageMs = timestamp => timestamp === null ? 'UNKNOWN' : Math.max(0, Date.now() - timestamp);

const captureOpenDetailKeys = () => {
  if (typeof document.querySelectorAll !== 'function') return new Set();
  return new Set(Array.from(document.querySelectorAll('details[open][data-detail-key]'))
    .map(detail => detail.dataset.detailKey));
};

const restoreOpenDetailKeys = keys => {
  if (typeof document.querySelectorAll !== 'function') return;
  document.querySelectorAll('details[data-detail-key]').forEach(detail => {
    detail.open = keys.has(detail.dataset.detailKey);
  });
};

function renderUnavailable() {
  lastRenderedDocument = null;
  const connection = document.getElementById('connection');
  connection.hidden = false;
  connection.textContent = '工作台连接中断: 旧业务数据已隐藏, 当前状态 UNKNOWN。';
  document.body.dataset.workbenchState = 'UNKNOWN';
  document.getElementById('runtime').textContent = 'runtime UNKNOWN';
  document.getElementById('system').innerHTML =
    card('工作台连接', 'UNKNOWN') +
    card('最近成功获取 age ms', ageMs(lastSuccessfulFetchAtMs)) +
    card('最后 publication sequence', lastPublicationSequence) +
    card('Publication 未变化 age ms', ageMs(lastPublicationChangeAtMs));
  const unavailable = '<p class="warning UNKNOWN">工作台连接中断; 旧业务数据已隐藏。</p>';
  businessPanelIds.forEach(id => { document.getElementById(id).innerHTML = unavailable; });
}

const zeroClaimText = (claim, noun) => claim.state === 'PROVEN_ZERO'
  ? `已证明当前 0 ${noun}`
  : (claim.state === 'NOT_ZERO' ? `当前 ${claim.value} ${noun}` : `无法证明当前为 0 ${noun}`);

const toolbar = (label, id, selected, choices, shown, total) =>
  `<div class="panel-toolbar"><label>${escapeHtml(label)}<select id="${escapeHtml(id)}">` +
  choices.map(choice => `<option value="${escapeHtml(choice)}"${choice === selected ? ' selected' : ''}>${escapeHtml(choice)}</option>`).join('') +
  `</select></label><span>显示 ${shown} / ${total}</span></div>`;

const countBy = (rows, field) => rows.reduce((result, row) => {
  const key = displayText(row[field]);
  result[key] = (result[key] || 0) + 1;
  return result;
}, {});

const compactCountMap = values => Object.entries(values)
  .filter(([, count]) => Number(count) > 0)
  .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]))
  .map(([key, count]) => `${actionText(key)} ${count}`)
  .join(' · ') || '无';

function renderRadarPanel(documentValue) {
  const product = documentValue.product;
  const ordered = orderedRadarRows(documentValue.radar.rows);
  const rows = filterRows(ordered, 'detector_state', radarFilterValue);
  const active = ordered.filter(row => row.detector_state === 'ANOMALY_ACTIVE').length;
  const unknown = ordered.filter(row => row.detector_state === 'UNKNOWN').length;
  const topN = ordered.filter(row => row.within_attention_top_n).length;
  const summary = '<div class="summary-grid">' +
    summaryStat('Attention Top-N', topN, 'ATTENTION') +
    summaryStat('Radar clue 激活', active, active ? 'CURRENT' : 'NO_ANOMALY') +
    summaryStat('Radar UNKNOWN', unknown, unknown ? 'UNKNOWN' : 'CURRENT') +
    summaryStat('当前展示', `${rows.length} / ${ordered.length}`) +
    '</div>';
  document.getElementById('radar').innerHTML = summary +
    toolbar('注意力筛选', 'radar-filter', radarFilterValue,
      ['TOP_N', 'ALL', 'ANOMALY_ACTIVE', 'UNKNOWN', 'NO_ANOMALY'], rows.length, ordered.length) +
    table(documentValue.radar, [
      ['Rank', 'attention_rank', radarPrimaryCellValue, 'numeric'],
      ['合约', 'instrument_name', null, 'instrument'],
      ['到期', 'expiration_timestamp_ms', radarPrimaryCellValue],
      ['TTE', 'tte_interval_ms', radarPrimaryCellValue, 'numeric'],
      ['类型', 'option_type', radarPrimaryCellValue],
      ['Delta', 'delta_interval', radarPrimaryCellValue],
      ['可执行 IV', 'executable_iv_interval', radarPrimaryCellValue, 'numeric'],
      ['RV 基线', 'baseline_annualized_volatility', radarPrimaryCellValue, 'numeric'],
      ['One-tick IV/RV', 'richness_ratio_interval', radarPrimaryCellValue, 'numeric'],
      ['价差', 'target_spread_ticks', (row, field, value) => {
        const rendered = radarPrimaryCellValue(row, field, value);
        return rendered === 'UNKNOWN' || rendered === 'N/A' ? rendered : `${rendered} ticks`;
      }, 'numeric'],
      ['Radar 状态', 'detector_state', radarPrimaryCellValue],
      ['当前原因', 'detector_reason', radarPrimaryCellValue, 'reason']
    ], rows, [
      ['rank explanation', 'rank_explanation'],
      ['hard screen label', 'hard_screen_label'],
      ['episode identity', 'active_episode_identity'],
      ['expiration timestamp ms', 'expiration_timestamp_ms'],
      ['TTE interval ms', 'tte_interval_ms'],
      [`strike exact (${product.strike_currency})`, 'strike_price'],
      [`model executable sell price (${product.strike_currency})`, 'model_executable_sell_price'],
      [`native executable sell price (${product.native_premium_currency})`, 'native_executable_sell_price'],
      [`native executable buy price (${product.native_premium_currency})`, 'native_executable_buy_price'],
      [`native stressed sell price (${product.native_premium_currency})`, 'native_one_tick_stressed_sell_price'],
      [`native price tick (${product.native_premium_currency})`, 'native_price_tick'],
      [`native target spread (${product.native_premium_currency})`, 'native_target_spread'],
      ['model conversion forward', 'model_conversion_forward'],
      ['product spec identity', 'product_spec_identity'],
      ['executable IV exact', 'executable_iv_interval'],
      ['baseline return interval minutes', 'baseline_return_interval_minutes'],
      ['baseline selected lookback minutes', 'baseline_selected_lookback_minutes'],
      ['baseline source', 'baseline_source'],
      ['baseline volatility exact', 'baseline_annualized_volatility'],
      ['raw richness exact', 'raw_richness_ratio_interval'],
      ['one-tick richness exact', 'richness_ratio_interval'],
      ['delta exact', 'delta_interval'],
      ['quote ask exact', 'model_executable_buy_price'],
      ['one-tick stressed bid exact', 'model_one_tick_stressed_sell_price'],
      ['model price tick exact', 'model_price_tick'],
      ['model spread exact', 'model_target_spread'],
      ['premium ticks', 'bid_premium_ticks'],
      ['surface residual exact', 'surface_residual'],
      ['regime context', 'regime_context'],
      ['surface context', 'surface_context'],
      ['legged structure', 'legged_structure_context'],
      ['detector reason enum', 'detector_reason'],
      ['option book state', 'option_book_state'],
      ['option book reason', 'option_book_reason'],
      ['episode start monotonic ms', 'anomaly_started_monotonic_ms'],
      ['episode duration ms', 'anomaly_active_duration_ms']
    ]);
}

function renderUnderwritingPanel(documentValue) {
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const ordered = orderedUnderwritingRows(documentValue.underwriting.rows);
  const rows = filterRows(ordered, 'availability', underwritingFilterValue);
  const evaluable = ordered.filter(row => row.availability === 'EVALUABLE').length;
  const candidates = ordered.filter(row => row.action === 'CANDIDATE').length;
  const watches = ordered.filter(row => row.action === 'WATCH').length;
  const abstains = ordered.filter(row => row.action === 'ABSTAIN').length;
  const availabilitySummary = compactCountMap(countBy(ordered, 'availability'));
  const actionSummary = compactCountMap(countBy(ordered.filter(row => !isMissing(row.action)), 'action'));
  const summary = '<div class="summary-grid">' +
    summaryStat('可评估结构', evaluable, evaluable ? 'EVALUABLE' : 'NOT_EVALUATED') +
    summaryStat('Candidate', candidates, candidates ? 'CANDIDATE' : 'NO_ANOMALY') +
    summaryStat('观察 / 观望', `${watches} / ${abstains}`, watches ? 'WATCH' : 'ABSTAIN') +
    summaryStat('Availability', availabilitySummary) +
    summaryStat('Action 分布', actionSummary) +
    '</div>';
  const marginSummary = Array.isArray(documentValue.underwriting.predicate_margin_summary)
    ? documentValue.underwriting.predicate_margin_summary : [];
  const marginDetails = marginSummary.length
    ? `<details class="system-details" data-detail-key="underwriting-margin"><summary>当前承保谓词 margin 分布</summary><div class="grid">${
        marginSummary.map(value => card(value.predicate,
          `n=${value.count}; min=${value.min}; p50=${value.p50}; max=${value.max}; ${value.unit}`
        )).join('')
      }</div></details>`
    : '';
  document.getElementById('underwriting').innerHTML = summary +
    toolbar('可用性筛选', 'underwriting-filter', underwritingFilterValue,
      ['ALL', 'EVALUABLE', 'UNKNOWN', 'NOT_EVALUATED'], rows.length, ordered.length) +
    marginDetails + table(documentValue.underwriting, [
      ['Short leg', 'short_leg_instrument_name', underwritingCellValue, 'instrument'],
      ['Long leg', 'long_leg_instrument_name', underwritingCellValue, 'instrument'],
      ['到期', 'expiry_timestamp_ms', underwritingCellValue],
      ['Availability', 'availability', underwritingCellValue],
      ['Action', 'action', underwritingCellValue],
      [`原生净权利金 (${nativeUnit})`, 'native_net_entry_credit',
        (_row, _field, value) => isMissing(value) ? 'N/A' : compactNative(value), 'numeric'],
      [`当前估值净权利金 (${valuationUnit})`, 'net_entry_credit_valuation',
        (_row, _field, value) => isMissing(value) ? 'N/A' : compactMoney(value), 'numeric'],
      [`未来成本准备 (${valuationUnit})`, 'future_cost_reserve_valuation',
        (_row, _field, value) => isMissing(value) ? 'N/A' : compactMoney(value), 'numeric'],
      ['最早失败原因', 'decision_reason', underwritingCellValue, 'reason']
    ], rows, [
      ['radar scope', 'radar_scope_or_short_leg_identity'],
      ['option type', 'option_type'],
      ['short strike exact', 'short_strike_price'],
      ['long strike exact', 'long_strike_price'],
      ['target quantity exact', 'target_quantity_btc'],
      ['availability identity', 'underwriting_availability_evaluation_identity'],
      ['action identity', 'underwriting_action_identity'],
      ['availability enum', 'availability'],
      ['decision reason enum', 'decision_reason'],
      ['unknown reasons', 'unknown_reasons'],
      ['failed predicates', 'failed_predicates'],
      ['predicate margin vector', 'predicate_margin_vector'],
      ['protective-leg selection rule identity', 'protective_leg_selection_rule_identity'],
      ['Candidate protective-leg count', 'candidate_protective_leg_count'],
      ['component blockers', 'component_blockers'],
      ['product spec identity', 'product_spec_identity'],
      ['product name', 'product_name'],
      ['native premium currency', 'native_premium_currency'],
      ['valuation currency', 'valuation_currency'],
      [`native gross entry credit (${product.native_premium_currency})`, 'native_gross_entry_credit'],
      [`native entry fee reserve (${product.native_premium_currency})`, 'native_entry_fee_reserve'],
      [`native net entry credit (${product.native_premium_currency})`, 'native_net_entry_credit'],
      ['entry valuation index price', 'entry_valuation_index_price'],
      [`gross entry credit (${product.valuation_currency})`, 'gross_entry_credit_valuation'],
      ['entry fee reserve exact', 'entry_fee_reserve_valuation'],
      ['net entry credit exact', 'net_entry_credit_valuation'],
      [`entry-boundary payoff loss proxy (${product.valuation_currency}; not native liability, expiry loss, or account margin)`,
        'entry_boundary_valued_payoff_loss_ex_fees_valuation'],
      ['future cost reserve exact', 'future_cost_reserve_valuation'],
      ['reserved loss exact', 'underwriting_reserved_loss_valuation'],
      ['reserve breakdown', 'reserve_breakdown_valuation'],
      ['evaluation fact boundary', 'evaluation_fact_boundary']
    ]);
}

const funnelStageLabels = {
  APPLICABLE_MARKET_SCOPE: '适用市场评估',
  RADAR_KNOWN: 'Radar 已知评估',
  ANOMALY_ACTIVE: '异常 Episode',
  STRUCTURE_REVIEWABLE: '结构可审查',
  COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE: '双腿盘口保守成交反事实',
  UNDERWRITING_EVALUABLE: 'Underwriting 可评估',
  CANDIDATE: 'Candidate',
  SHADOW_CASE_OPENED: 'Shadow Case',
  SHADOW_CASE_OUTCOME: 'Outcome'
};
const funnelStageLabel = value => funnelStageLabels[value] || String(value);

const funnelUnitLabels = {
  POST_WARMUP_COUNTABLE_INSTRUMENT_EVALUATION: '合约评估',
  POST_WARMUP_KNOWN_INSTRUMENT_EVALUATION: '已知合约评估',
  DISTINCT_ANOMALY_EPISODE: '独立 Episode',
  DISTINCT_ADMITTED_SHADOW_CASE: '已接纳 Case'
};
const funnelUnitText = value => funnelUnitLabels[value] || displayText(value);

const funnelBlockerText = values => {
  if (!values || typeof values !== 'object') return '无';
  const entries = Object.entries(values).filter(([, count]) => Number(count) > 0);
  if (!entries.length) return '无';
  return entries
    .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]))
    .map(([reason, count]) => `${reasonText(reason)}: ${count}`)
    .join('; ');
};

const knownnessRatioText = slice => {
  const value = slice && slice.radar_known_over_applicable;
  if (!value) return 'UNKNOWN';
  const counts = `${displayText(value.numerator)}/${displayText(value.denominator)}`;
  if (Number(value.denominator) === 0 || isMissing(value.ratio)) return `${counts} (UNKNOWN)`;
  const percentage = Number(value.ratio) * 100;
  return Number.isFinite(percentage) ? `${counts} (${percentage.toFixed(2)}%)` : `${counts} (UNKNOWN)`;
};

function renderFunnel(documentValue) {
  const funnel = documentValue.funnel;
  const knownness = funnel && funnel.radar_knownness;
  if (!funnel || !Array.isArray(funnel.stages) || !funnel.primary_blocker ||
      !knownness || !knownness.startup_warmup || !knownness.post_warmup) {
    throw new Error('invalid funnel projection');
  }
  const primary = funnel.primary_blocker;
  const startup = knownness.startup_warmup;
  const steady = knownness.post_warmup;
  const summary = '<div class="grid">' +
    card('首要漏斗阻塞阶段', funnelStageLabel(primary.stage)) +
    card('首要阻塞原因', reasonText(primary.reason)) +
    card('受阻数量', primary.blocked_count) +
    card('该阶段上游/已通过', `${primary.upstream_count}/${primary.observed_count}`) +
    card('启动/恢复 warmup Radar known / applicable', knownnessRatioText(startup)) +
    card('启动/恢复 warmup UNKNOWN', funnelBlockerText(startup.blocker_counts)) +
    card('稳态 Radar known / applicable', knownnessRatioText(steady)) +
    card('稳态 Radar UNKNOWN', funnelBlockerText(steady.blocker_counts)) +
    '</div>';
  const ladder = '<div class="funnel-ladder">' + funnel.stages.map(stage => {
    const isPrimary = stage.stage === primary.stage;
    return `<div class="funnel-step${isPrimary ? ' is-primary' : ''}">` +
      `<div class="funnel-stage">${safeText(funnelStageLabel(stage.stage))}</div>` +
      `<div class="funnel-count">${safeText(formatCompactNumber(stage.observed_count, 0))}</div>` +
      `<div class="funnel-unit">${safeText(funnelUnitText(stage.unit))}</div>` +
      `<div class="funnel-blocker">${safeText(funnelBlockerText(stage.blocker_counts))}</div>` +
      '</div>';
  }).join('') + '</div>';
  const header = '<tr><th scope="col">阶段</th><th scope="col">已观察</th>' +
    '<th scope="col">单位</th><th scope="col">上游</th><th scope="col">阻塞归因</th></tr>';
  const rows = funnel.stages.map(stage => '<tr>' +
    `<td>${safeText(funnelStageLabel(stage.stage))}</td>` +
    `<td class="numeric">${safeText(stage.observed_count)}</td>` +
    `<td>${safeText(stage.unit)}</td>` +
    `<td class="numeric">${safeText(stage.upstream_count)}</td>` +
    `<td class="reason">${safeText(funnelBlockerText(stage.blocker_counts))}</td>` +
    '</tr>').join('');
  const exactTable = `<details class="detail-group" data-detail-key="funnel-exact">` +
    `<summary>查看精确阶段表</summary>` +
    `<div class="table-scroll"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div></details>`;
  document.getElementById('funnel').innerHTML = summary + ladder + exactTable;
}

function renderDecisionControlResearch(documentValue) {
  const research = documentValue.funnel && documentValue.funnel.decision_control_research;
  const panel = documentValue.decision_controls;
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  if (!research || !research.pending_counts || !research.selected_action_counts ||
      !research.attempt_terminal_counts || !Array.isArray(research.non_claims) ||
      !panel || !Array.isArray(panel.rows) || !product) {
    throw new Error('invalid selected-decision research projection');
  }
  const summary = '<div class="summary-grid">' +
    summaryStat('因果 activation batch', research.activation_batch_count) +
    summaryStat('预先选定决策', research.selected_decision_count) +
    summaryStat('No-trade control Case', research.decision_case_opened_count, 'RESEARCH') +
    summaryStat('严格未来 Outcome', research.decision_outcome_count,
      research.decision_outcome_count ? 'CURRENT' :
        (research.pending_counts.case_without_outcome ? 'PENDING' : 'NO_ANOMALY')) +
    summaryStat('选定 action', compactCountMap(research.selected_action_counts)) +
    summaryStat('刷新终局', funnelBlockerText(research.attempt_terminal_counts)) +
    summaryStat('尚无可评估选定决策', research.pending_counts.batch_without_selected_evaluable_decision) +
    summaryStat('选定但未开 Case', research.pending_counts.selected_without_case) +
    summaryStat('Case 等待 Outcome', research.pending_counts.case_without_outcome,
      research.pending_counts.case_without_outcome ? 'PENDING' : 'NO_ANOMALY') +
    '</div>';
  const boundary = `<div class="boundary-strip"><strong>研究边界：</strong>${
    safeText(research.non_claims.join('; '))}</div>`;
  const detailed = table(panel, [
    ['选定 action', 'selected_economic_action', (_row, _field, value) => actionText(value)],
    ['刷新后 action', 'refreshed_economic_action', (_row, _field, value) => actionText(value)],
    ['刷新终局', 'refresh_terminal_outcome', (_row, _field, value) => reasonText(value)],
    ['Enrollment', 'enrollment_kind', (_row, _field, value) => enrollmentText(value)],
    ['Case / Outcome', 'case_state', (_row, _field, value) => caseStateText(value)],
    [`Public-quote PnL (${valuationUnit})`, 'public_quote_net_pnl_valuation',
      row => outcomeValuationCellValue(row, product), 'numeric'],
    [`Native PnL (${nativeUnit})`, 'native_net_pnl',
      (_row, _field, value) => isMissing(value) ? 'UNKNOWN' : compactNative(value), 'numeric']
  ], panel.rows, [
    ['selection identity', 'selected_underwriting_decision_identity'],
    ['activation batch identity', 'activation_batch_identity'],
    ['active episode', 'active_episode_identity'],
    ['selected failed predicates', 'selected_failed_predicates'],
    ['selected predicate margin vector', 'selected_predicate_margin_vector'],
    ['protective-leg selection rule identity', 'protective_leg_selection_rule_identity'],
    ['Candidate protective-leg count', 'candidate_protective_leg_count'],
    ['selection fact boundary', 'selection_fact_boundary'],
    ['refresh unknown reasons', 'refresh_unknown_reasons'],
    ['refresh pair timing', 'refresh_component_pair_timing'],
    ['refresh pair limits', 'refresh_component_pair_limits'],
    ['refreshed failed predicates', 'refreshed_failed_predicates'],
    ['refreshed predicate margin vector', 'refreshed_predicate_margin_vector'],
    ['refreshed fact boundary', 'refreshed_fact_boundary'],
    ['enrollment identity', 'enrollment_identity'],
    ['boundary-valued PnL', 'boundary_valued_net_pnl_usd'],
    ['exit-valued native PnL', 'exit_valued_native_net_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['non claims', 'non_claims']
  ]);
  const detail = panel.panel_state === 'EMPTY_NO_SETTLED_OBJECT'
    ? detailed
    : `<details class="detail-group" data-detail-key="research-case-rows">` +
      `<summary>查看 ${panel.rows.length} 条研究 Case 明细（默认折叠）</summary>` +
      `<div class="detail-content">${detailed}</div></details>`;
  document.getElementById('decision-control').innerHTML = summary + boundary + detail;
}

function renderShadowPanel(documentValue) {
  const panel = documentValue.shadow_entries;
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const rows = panel.rows;
  const opened = rows.filter(row => !isMissing(row.shadow_entry_identity)).length;
  const noEntry = rows.length - opened;
  const summary = '<div class="summary-grid">' +
    summaryStat('当前 Shadow Entry', opened, opened ? 'CURRENT' : 'NO_ANOMALY') +
    summaryStat('未入场 / 失败刷新', noEntry, noEntry ? 'ABSTAIN' : 'CURRENT') +
    '</div>';
  const detailed = table(panel, [
    ['刷新结果', 'admission_refresh_terminal_outcome', shadowCellValue],
    ['目标数量 (BTC)', 'target_quantity_btc', shadowCellValue, 'numeric'],
    [`模拟垂直毛信用 (${valuationUnit}/BTC)`, 'simulated_entry_price_valuation_per_btc', shadowCellValue, 'numeric'],
    ['模拟入场价状态', 'simulated_entry_price_availability'],
    [`模拟毛权利金 (${valuationUnit})`, 'simulated_entry_credit_valuation', shadowCellValue, 'numeric'],
    [`原生净权利金 (${nativeUnit})`, 'native_net_entry_credit', shadowCellValue, 'numeric'],
    ['未入场原因', 'no_entry_reason', shadowCellValue, 'reason'],
    ['声明', 'simulation_label']
  ], rows, [
    ['candidate identity', 'candidate_identity'],
    ['active episode', 'active_episode_identity'],
    ['formed boundary', 'candidate_formed_fact_boundary'],
    ['refresh source identity', 'matched_refresh_source_identity'],
    ['shadow entry identity', 'shadow_entry_identity'],
    ['target quantity exact', 'target_quantity_btc'],
    ['simulated entry price exact', 'simulated_entry_price_valuation_per_btc'],
    ['simulated entry credit exact', 'simulated_entry_credit_valuation'],
    ['native gross entry credit', 'native_gross_entry_credit'],
    ['native entry fee reserve', 'native_entry_fee_reserve'],
    ['native net entry credit', 'native_net_entry_credit'],
    ['entry valuation index price', 'entry_valuation_index_price'],
    ['native premium currency', 'native_premium_currency'],
    ['execution model', 'execution_model'],
    ['component pair identity', 'entry_component_pair_identity'],
    ['component pair timing', 'entry_component_pair_timing'],
    ['admission refresh unknown reasons', 'admission_refresh_unknown_reasons'],
    ['admission pair timing', 'admission_component_pair_timing'],
    ['admission pair limits', 'admission_component_pair_limits'],
    ['component legs', 'entry_component_legs']
  ]);
  document.getElementById('shadow').innerHTML = summary + detailed;
}

function renderPositionPanel(documentValue) {
  const panel = documentValue.positions;
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const rows = panel.rows;
  const actions = countBy(rows, 'position_action');
  const summary = '<div class="summary-grid">' +
    summaryStat('当前监督对象', rows.length, rows.length ? 'CURRENT' : 'NO_ANOMALY') +
    summaryStat('Action 分布', compactCountMap(actions)) +
    '</div>';
  const detailed = table(panel, [
    ['Action', 'position_action', (_row, _field, value) => actionText(value)],
    [`剩余权利金 (${valuationUnit})`, 'remaining_premium_valuation', positionCellValue, 'numeric'],
    ['剩余权利金状态', 'remaining_premium_availability'],
    ['Component close', 'close_quote_state'],
    [`Close debit (${valuationUnit})`, 'current_close_debit_valuation', positionCellValue, 'numeric'],
    [`Boundary-valued Shadow PnL (${valuationUnit})`, 'projected_shadow_pnl_valuation', positionCellValue, 'numeric'],
    [`Native projected PnL (${nativeUnit})`, 'native_projected_shadow_net_pnl', positionCellValue, 'numeric'],
    ['Hard-close 倒计时', 'hard_close_countdown_interval_ms', positionCellValue],
    ['首要退出规则', 'primary_exit_rule'],
    ['Outcome', 'outcome_state']
  ], rows, [
    ['shadow entry identity', 'shadow_entry_identity'],
    ['remaining premium exact', 'remaining_premium_valuation'],
    ['close debit exact', 'current_close_debit_valuation'],
    ['component pair timing', 'component_pair_timing'],
    ['component pair limits', 'component_pair_limits'],
    ['component pair business state', 'component_pair_business_state'],
    ['component pair unknown reasons', 'component_pair_unknown_reasons'],
    ['projected Shadow PnL exact', 'projected_shadow_pnl_valuation'],
    ['native close cashflow', 'native_net_close_cashflow'],
    ['native projected Shadow PnL', 'native_projected_shadow_net_pnl'],
    ['boundary-valued projected Shadow PnL', 'boundary_valued_projected_shadow_net_pnl_usd'],
    ['exit-valued native projected PnL', 'exit_valued_native_projected_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['hard-close interval ms', 'hard_close_countdown_interval_ms'],
    ['remaining premium basis', 'remaining_premium_basis'],
    ['ordered exit rules', 'ordered_latched_exit_rules']
  ]);
  document.getElementById('positions').innerHTML = summary + detailed;
}

function renderOutcomePanel(documentValue) {
  const panel = documentValue.outcomes;
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const rows = panel.rows;
  const stateCounts = countBy(rows, 'state');
  const pending = rows.filter(row => row.maturity === 'PENDING').length;
  const known = rows.filter(row => row.maturity === 'MATURE_KNOWN').length;
  const unknown = rows.filter(row => row.maturity === 'MATURE_UNKNOWN').length;
  const censored = rows.filter(row => row.maturity === 'CENSORED').length;
  const economicKnown = known;
  const summary = '<div class="summary-grid">' +
    summaryStat('当前 Outcome 对象', rows.length) +
    summaryStat('等待未来事实', pending, pending ? 'PENDING' : 'CURRENT') +
    summaryStat('Mature known', known, known ? 'CURRENT' : 'NO_ANOMALY') +
    summaryStat('Mature unknown', unknown, unknown ? 'UNKNOWN' : 'NO_ANOMALY') +
    summaryStat('Censored', censored, censored ? 'ABSTAIN' : 'NO_ANOMALY') +
    summaryStat('经济结果可用', economicKnown, economicKnown ? 'CURRENT' : 'UNKNOWN') +
    summaryStat('状态分布', compactCountMap(stateCounts)) +
    '</div>';
  const detailed = table(panel, [
    ['状态', 'state'],
    ['成熟度', 'maturity'],
    [`Boundary-valued public-quote PnL (${valuationUnit})`, 'public_quote_net_pnl_valuation',
      row => outcomeValuationCellValue(row, product), 'numeric'],
    [`Native net PnL (${nativeUnit})`, 'native_net_pnl', outcomeCellValue, 'numeric'],
    ['Actual PnL', 'actual_pnl', outcomeCellValue]
  ], rows, [
    ['observation identity', 'shadow_observation_identity'],
    ['selected exit identity', 'selected_exit_identity'],
    ['public-quote PnL exact', 'public_quote_net_pnl_valuation'],
    ['native net PnL', 'native_net_pnl'],
    ['boundary-valued net PnL', 'boundary_valued_net_pnl_usd'],
    ['exit-valued native net PnL', 'exit_valued_native_net_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['actual PnL exact', 'actual_pnl']
  ]);
  const detail = panel.panel_state === 'EMPTY_NO_SETTLED_OBJECT'
    ? detailed
    : `<details class="detail-group" data-detail-key="outcome-rows">` +
      `<summary>查看 ${rows.length} 条 Outcome 明细（默认折叠）</summary>` +
      `<div class="detail-content">${detailed}</div></details>`;
  document.getElementById('outcomes').innerHTML = summary + detail;
}

const primaryBlockerSummary = documentValue => {
  const primary = documentValue.funnel && documentValue.funnel.primary_blocker;
  if (!primary || primary.reason === 'NO_MATERIAL_BLOCKER_OBSERVED') return '当前无实质漏斗阻塞';
  return `${funnelStageLabel(primary.stage)} · ${reasonText(primary.reason)} · ${primary.blocked_count}`;
};

const runCaseOutcomeSummary = documentValue => {
  const stages = documentValue.funnel && documentValue.funnel.stages;
  const research = documentValue.funnel && documentValue.funnel.decision_control_research;
  if (!Array.isArray(stages) || !research || !research.pending_counts) return 'UNKNOWN';
  const stageCount = stageName => {
    const stage = stages.find(value => value.stage === stageName);
    return stage ? formatCompactNumber(stage.observed_count, 0) : 'UNKNOWN';
  };
  return `规范 ${stageCount('SHADOW_CASE_OPENED')} Case / ` +
    `${stageCount('SHADOW_CASE_OUTCOME')} Outcome · ` +
    `研究待未来事实 ${formatCompactNumber(research.pending_counts.case_without_outcome, 0)}`;
};

const buildExecutiveSummary = documentValue => {
  const service = documentValue.service;
  const anomaly = documentValue.zero_claims.anomaly;
  const candidate = documentValue.zero_claims.candidate;
  if (!service.ready) {
    return `当前数据不可用于判定：${reasonText(service.reason)}。Attention、Candidate 与 Outcome 均不得据此升级。`;
  }
  const anomalyText = anomaly.state === 'PROVEN_ZERO'
    ? '当前已证明无 Radar clue'
    : (anomaly.state === 'NOT_ZERO' ? `当前有 ${anomaly.value} 个 Radar clue` : '当前 Radar clue 不能证明为零');
  const candidateText = candidate.state === 'PROVEN_ZERO'
    ? '已证明当前无 Candidate'
    : (candidate.state === 'NOT_ZERO' ? `当前有 ${candidate.value} 个 Candidate` : '当前 Candidate 不能证明为零');
  return `${anomalyText}；${candidateText}。最早阻塞：${primaryBlockerSummary(documentValue)}。`;
};

function render(documentValue) {
  if (!documentValue || documentValue.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error('unsupported workbench projection schema');
  }
  const product = documentValue.product;
  if (!product || !product.product_spec_identity || !product.name ||
      !product.native_premium_currency || !product.valuation_currency || !product.price_index ||
      !product.native_settlement_payoff_rule || !product.native_settlement_liability_profile ||
      product.actual_account_margin_availability !== 'UNKNOWN' ||
      product.actual_account_margin_reason !== 'ACCOUNT_MARGIN_UNKNOWN') {
    throw new Error('invalid product projection');
  }
  const openDetailKeys = captureOpenDetailKeys();
  const connection = document.getElementById('connection');
  connection.hidden = true;
  connection.textContent = '';
  document.body.dataset.workbenchState = 'CURRENT_FETCH';
  document.getElementById('runtime').textContent = `runtime ${shortIdentity(documentValue.runtime_identity)}`;
  const service = documentValue.service;
  const system = documentValue.system;
  const zero = documentValue.zero_claims;
  document.getElementById('system').innerHTML =
    card('当前结论', buildExecutiveSummary(documentValue), {primary: true,
      meta: '当前快照；Attention ≠ Radar clue ≠ Candidate ≠ Case ≠ Outcome'}) +
    card('产品与经济单位', `${productLabel(product.name)} · ${product.native_premium_currency} 原生 / ${product.valuation_currency} 估值`,
      {meta: `${product.price_index} · ${product.settlement_currency} 结算`}) +
    card('数据状态', `${service.phase} / ${service.data_state}`, {meta: service.ready ? '可用于当前判定' : '不可用于当前判定'}) +
    card('当前覆盖', `${system.known_current_instrument_evaluation_count}/${system.monitored_instrument_count}`,
      {meta: isMissing(system.coverage_ratio_percent) ? '覆盖率 UNKNOWN' : `${formatCompactNumber(system.coverage_ratio_percent, 2)}%`}) +
    card('Radar clue', zeroClaimText(zero.anomaly, 'Radar clue'), {meta: `分母 ${displayText(zero.anomaly.denominator)}`}) +
    card('Candidate', zeroClaimText(zero.candidate, 'Candidate'), {meta: `Underwriting-evaluable 分母 ${displayText(zero.candidate.denominator)}`}) +
    card('Case / Outcome（本次运行）', runCaseOutcomeSummary(documentValue),
      {meta: '规范 Candidate 漏斗 · Selected Decision 独立研究'}) +
    card('当前最早阻塞', primaryBlockerSummary(documentValue)) +
    card('数据延迟', isMissing(system.data_delay_ms) ? 'UNKNOWN' : formatDurationMs(system.data_delay_ms),
      {meta: `last-wire ${isMissing(system.last_wire_age_ms) ? 'UNKNOWN' : formatDurationMs(system.last_wire_age_ms)}`}) +
    card('实际账户保证金', 'UNKNOWN — 未接入私有账户数据', {meta: product.actual_account_margin_reason}) +
    '<details class="system-details" data-detail-key="system-audit">' +
    '<summary>运行、产品与 Policy 审计详情</summary><div class="grid">' +
    card('Ready', service.ready) +
    card('Publication sequence', documentValue.publication_sequence) +
    card('最近成功获取 age', formatDurationMs(ageMs(lastSuccessfulFetchAtMs))) +
    card('Publication 未变化 age', formatDurationMs(ageMs(lastPublicationChangeAtMs))) +
    card('Session epoch', system.session_epoch) +
    card('Platform', reasonText(system.platform_reason)) +
    card('最近行情时间', isMissing(system.latest_market_timestamp_ms) ? 'UNKNOWN' : formatEpochMs(system.latest_market_timestamp_ms)) +
    card('Last-wire age', isMissing(system.last_wire_age_ms) ? 'UNKNOWN' : formatDurationMs(system.last_wire_age_ms)) +
    card('Coverage', system.coverage_state) +
    card('Coverage blocker', system.coverage_blocking_reason) +
    card('覆盖率', isMissing(system.coverage_ratio_percent) ? 'UNKNOWN' : `${formatDecimal(system.coverage_ratio_percent)}%`) +
    card('断线/重连', system.reconnect_count) +
    card('Session gaps', system.session_gap_count) +
    card('最近断线记录', system.disconnect_records.slice(-1)[0]) +
    card('RV source', system.index_history.source) +
    card('RV value semantics', system.index_history.value_semantics) +
    card('History cadence', isMissing(system.index_history.modal_interval_ms)
      ? 'UNKNOWN' : formatDurationMs(system.index_history.modal_interval_ms)) +
    card('History confirmed suffix', `${system.index_history.exact_suffix_point_count} points / ${formatDecimal(system.index_history.exact_suffix_minutes)} minutes`) +
    card('History confirmed age', isMissing(system.index_history.latest_source_age_ms)
      ? 'UNKNOWN' : formatDurationMs(system.index_history.latest_source_age_ms)) +
    card('History newest point outside completion cutoff', system.index_history.newest_response_point_excluded_by_completion_cutoff) +
    card('History revisions', `${system.index_history.revision_count}; pending=${system.index_history.revision_pending}`) +
    card('Runtime identity', documentValue.runtime_identity) +
    card('Code identity', documentValue.code_identity) +
    card('Published fact boundary', documentValue.published_fact_boundary) +
    card('Policy / Radar', documentValue.policy_identities.radar) +
    card('Policy / Underwriting', documentValue.policy_identities.underwriting) +
    card('Policy / Position', documentValue.policy_identities.position) +
    card('Product spec identity', product.product_spec_identity) +
    card('Product instrument type', product.instrument_type) +
    card('Product quote/counter', `${product.quote_currency}/${product.counter_currency}`) +
    card('Native settlement payoff rule', product.native_settlement_payoff_rule) +
    card('Native settlement liability profile', product.native_settlement_liability_profile) +
    '</div></details>';

  document.getElementById('zero').innerHTML =
    card('零异常', zero.anomaly.value === null ? zero.anomaly.explanation : `${zero.anomaly.value} (${zero.anomaly.state})`) +
    card('异常监控分母', zero.anomaly.denominator) +
    card('零 Candidate', zero.candidate.value === null ? zero.candidate.explanation : `${zero.candidate.value} (${zero.candidate.state})`) +
    card('Underwriting-evaluable 分母', zero.candidate.denominator);

  renderFunnel(documentValue);
  renderDecisionControlResearch(documentValue);
  renderRadarPanel(documentValue);
  renderUnderwritingPanel(documentValue);
  renderShadowPanel(documentValue);
  renderPositionPanel(documentValue);
  renderOutcomePanel(documentValue);
  restoreOpenDetailKeys(openDetailKeys);
  lastRenderedDocument = documentValue;
}

function activateTab(targetId) {
  if (typeof document.querySelectorAll !== 'function') return;
  const views = document.querySelectorAll('[data-tab-view]');
  const links = document.querySelectorAll('[data-tab-target]');
  const availableTarget = Array.from(views).some(view => view.id === targetId)
    ? targetId
    : 'decision-view';
  views.forEach(view => { view.hidden = view.id !== availableTarget; });
  links.forEach(link => {
    if (link.dataset.tabTarget === availableTarget) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  return availableTarget;
}

if (typeof document.addEventListener === 'function') {
  document.addEventListener('change', event => {
    if (!lastRenderedDocument || !event.target) return;
    if (event.target.id === 'radar-filter') {
      radarFilterValue = event.target.value;
      renderRadarPanel(lastRenderedDocument);
    } else if (event.target.id === 'underwriting-filter') {
      underwritingFilterValue = event.target.value;
      renderUnderwritingPanel(lastRenderedDocument);
    }
  });
  document.addEventListener('click', event => {
    const target = event.target && typeof event.target.closest === 'function'
      ? event.target.closest('[data-tab-target]') : null;
    if (!target) return;
    event.preventDefault();
    const activeTarget = activateTab(target.dataset.tabTarget);
    if (typeof history.replaceState === 'function') history.replaceState(null, '', `#${activeTarget}`);
    const activeView = document.getElementById(activeTarget);
    if (activeView && typeof activeView.scrollIntoView === 'function') {
      activeView.scrollIntoView({block: 'start'});
    }
  });
  document.addEventListener('DOMContentLoaded', () => {
    const requested = typeof location !== 'undefined' ? location.hash.slice(1) : '';
    activateTab(requested || 'decision-view');
  });
}

async function refresh() {
  try {
    const response = await fetch('/api/workbench/current', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const documentValue = await response.json();
    const fetchedAtMs = Date.now();
    const previousSuccessfulFetchAtMs = lastSuccessfulFetchAtMs;
    const previousPublicationRuntimeIdentity = lastPublicationRuntimeIdentity;
    const previousPublicationSequence = lastPublicationSequence;
    const previousPublicationChangeAtMs = lastPublicationChangeAtMs;
    lastSuccessfulFetchAtMs = fetchedAtMs;
    if (
      documentValue.runtime_identity !== lastPublicationRuntimeIdentity ||
      documentValue.publication_sequence !== lastPublicationSequence
    ) {
      lastPublicationRuntimeIdentity = documentValue.runtime_identity;
      lastPublicationSequence = documentValue.publication_sequence;
      lastPublicationChangeAtMs = fetchedAtMs;
    }
    try {
      render(documentValue);
    } catch (error) {
      lastSuccessfulFetchAtMs = previousSuccessfulFetchAtMs;
      lastPublicationRuntimeIdentity = previousPublicationRuntimeIdentity;
      lastPublicationSequence = previousPublicationSequence;
      lastPublicationChangeAtMs = previousPublicationChangeAtMs;
      throw error;
    }
  } catch (_error) {
    renderUnavailable();
  }
}

refresh();
setInterval(refresh, 2000);

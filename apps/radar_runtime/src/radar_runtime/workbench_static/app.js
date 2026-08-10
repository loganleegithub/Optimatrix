const SUPPORTED_SCHEMA_VERSION = 6;
const ACTIVE_CHANNEL_ID = 'INVERSE_BTC_SHORT_VOL_V2';
const DRAWER_MEDIA_QUERY = '(max-width: 1471px)';
const THEME_STORAGE_KEY = 'optimatrix-workbench-theme';
const ACTIVE_PRODUCT_SPEC_IDENTITY = 'sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131';
const ACTIVE_POLICY_IDENTITIES = Object.freeze({
  radar: 'sha256:79b5ec7c886964ee4c886fb272f287f0645cc69a0b585cf53711c7b5ad0fef57',
  underwriting: 'sha256:5cea5bc8153071359597526e0f1bd665bbf55215b5368ed6135f96ca3b607c31',
  position: 'sha256:f05646f7c1ed1a55bd8747879f1153c2633afde83aa3652549e01140552a6c67'
});

const CHANNELS = [
  {id: ACTIVE_CHANNEL_ID, label: 'BTC Short Vol', product: 'inverse-btc', strategy: 'SHORT_VOL'},
  {id: 'INVERSE_BTC_LONG_GAMMA', label: 'BTC Long Gamma', product: 'inverse-btc', strategy: 'LONG_GAMMA'},
  {id: 'INVERSE_ETH_SHORT_VOL', label: 'ETH Short Vol', product: 'inverse-eth', strategy: 'SHORT_VOL'},
  {id: 'INVERSE_ETH_LONG_GAMMA', label: 'ETH Long Gamma', product: 'inverse-eth', strategy: 'LONG_GAMMA'}
];

const STRUCTURE_FILTERS = [
  ['ALL', '全部'],
  ['SHADOW_TRACKING', 'Shadow 跟踪'],
  ['CANDIDATE', 'Shadow 候选'],
  ['WATCH', '继续观察'],
  ['ABSTAIN', '暂不参与'],
  ['UNKNOWN', '暂不可判断']
];

const RADAR_FILTERS = [
  ['ALL', '全部'],
  ['HIGH', 'HIGH'],
  ['MID', 'MID'],
  ['LOW', 'LOW'],
  ['REVIEW', '边界复核'],
  ['UNKNOWN', '暂不可判断']
];

const reasonLabels = {
  NONE: '无',
  NOT_OTM: '不是虚值合约，不进入当前 Short Vol 风险桶',
  QUEUE_LAG_CURRENTNESS: '处理队列延迟，行情时效性不可确认',
  CLOCK_GAP: '可信时间不连续',
  INDEX_WARMUP: '指数基线处于启动或恢复阶段',
  INDEX_WINDOW_GAP: '指数基线窗口存在缺口',
  INDEX_SOURCE_STALE: '指数来源已陈旧',
  INDEX_CONTINUITY_GAP: '指数行情连续性中断',
  INDEX_HISTORY_REVISION: '官方指数历史发生修订，等待下一响应确认',
  POST_STATUS_BOOTSTRAP_REQUIRED: '平台状态变化后等待期权簿重新建立',
  OPTION_BOOK_UNKNOWN: '期权簿不可确认',
  OPTION_AMOUNT_METADATA_UNKNOWN: '期权数量元数据不可确认',
  OPTION_PRICE_TICK_METADATA_UNKNOWN: '官方价格 tick 规则不可确认',
  INSUFFICIENT_TARGET_ASK_DEPTH: '目标数量买回深度不足',
  NON_POSITIVE_TARGET_SPREAD: '目标规模盘口锁定或交叉',
  ONE_TICK_STRESSED_BID_NON_POSITIVE: '卖价下压一个合法 tick 后不再为正',
  DELTA_INELIGIBLE: 'Delta 不在冻结的可行动风险桶',
  REVIEW_ONLY_TTE_BAND: '临近 admission cutoff，仅供审查',
  REVIEW_ONLY_DELTA_BUCKET: 'Delta 位于线索风险桶之外，仅供审查',
  REVIEW_ONLY_TTE_AND_DELTA: 'TTE 与 Delta 均位于 review-only 范围',
  FORWARD_TICKER_UNKNOWN: '远期价格不可确认',
  INVALID_FORWARD: '远期价格无效',
  NUMERICAL_BOUNDARY_UNRESOLVED: '数值区间跨越决策边界',
  NUMERICAL_UNKNOWN: '数值模型输入不可确认',
  SESSION_GAP: '公共行情会话中断',
  REMOTE_CONNECTION_CLOSED: '公共行情连接已关闭',
  SESSION_RPC_FAILURE: '公共接口响应超时',
  RUNTIME_SESSION_FAILURE: '公共行情会话运行失败',
  TRANSPORT_READ_FAILURE: '公共行情传输读取失败',
  PROTOCOL_INCOMPATIBILITY: '公共数据协议不兼容',
  INGRESS_GAP_OR_DUPLICATE: '行情输入序列存在缺口或重复',
  QUEUE_OVERFLOW: '行情处理队列溢出',
  TICKER_SOURCE_STALE: '期权行情来源已陈旧',
  KNOWN_DEGRADED: '已知覆盖降级',
  NO_APPLICABLE_SCOPE: '当前无适用合约范围',
  NO_APPLICABLE_MARKET_SCOPE_OBSERVED: '当前无适用合约范围',
  PROCESS_FAILURE: 'Runtime 进程失败',
  HUMAN_STOP: '人工停止',
  MISSING_SHADOW_ENTRY_IDENTITY: '缺少 Shadow Entry identity',
  DUPLICATE_SHADOW_ENTRY_IDENTITY: 'Shadow Entry identity 重复',
  MISSING_CANDIDATE_IDENTITY: '缺少 Candidate identity',
  DUPLICATE_CANDIDATE_IDENTITY: 'Candidate identity 对应多条 Shadow Entry',
  INVALID_ENTRY_COMPONENT_ROLES: '冻结入场腿不是唯一一条 SHORT 与一条 LONG',
  INVALID_ENTRY_LEG_ACTIONS: '冻结入场腿方向不是 SHORT/SELL 与 LONG/BUY',
  COMBO_QUOTE_RECEIPT_UNKNOWN: '组合报价回执不可确认',
  NO_ACTIVE_COMBO: '无现成官方组合；不阻塞双腿 Shadow 模拟',
  NO_TARGET_SIZE_CREDIT_QUOTE: '现成官方组合没有目标数量正信用报价',
  NO_PROTECTIVE_COMPONENT: '没有可冻结的同到期保护腿',
  NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE: '双腿盘口不能同时覆盖目标数量',
  COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN: '双腿保守成交反事实不可确认',
  MINIMUM_NET_ENTRY_CREDIT: '净入场权利金低于 Policy 最低值',
  MINIMUM_NET_CREDIT_TO_PAYOFF_CAP: '净权利金相对保护宽度不足',
  CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE: '净权利金未覆盖未来成本准备',
  CREDIT_ABOVE_FUTURE_COST_RESERVE: '净权利金高于未来成本准备',
  UNDERWRITING_RESERVED_LOSS_LIMIT: '承保准备损失超过 Policy 上限',
  UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT: '承保准备损失位于 Policy 上限内',
  ENTRY_CONSUMED_LEVEL_LIMIT: '双腿消耗盘口层数位于限制内',
  POSITIVE_NET_ENTRY_CREDIT: '净入场权利金为正',
  RADAR_EPISODE_NOT_ACTIVE: '当前无活跃 Radar 线索，尚未进入结构评估',
  ACCOUNT_MARGIN_UNKNOWN: '未接入私有账户保证金事实',
  TARGET_SIZE_TWO_SIDED_ONE_TICK_FORMULA_KNOWN: '目标规模双边盘口和 one-tick 公式已知',
  NONE_AT_RADAR_HARD_SCREEN: 'Radar hard screen 当前无阻塞',
  OFFICIAL_ATOMIC_QUOTE_THEN_UNDERWRITING: '下一步查看官方组合诊断与入场经济评估',
  SOURCE_LOSS_OR_REVIEW_BUCKET_OR_STRESSED_RICHNESS_CLEAR_PERSISTENCE: '数据丢失、进入 review-only 风险桶或 richness 持续性消失时失效',
  RESTORE_REQUIRED_HARD_SCREEN_FACTS: '恢复缺失的 hard-screen 必需事实',
  NOT_APPLICABLE_WITHOUT_A_KNOWN_FORMULA: '公式未知时不适用失效判断',
  ENTER_CLUE_ELIGIBLE_TTE_AND_DELTA_BUCKETS: '进入可激活线索的 TTE 与 Delta 风险桶',
  ENTER_CLUE_ELIGIBLE_TTE_BUCKET: '进入可激活线索的 TTE 风险桶',
  ENTER_CLUE_ELIGIBLE_DELTA_BUCKET: '进入可激活线索的 Delta 风险桶',
  MEET_STRESSED_RICHNESS_AND_TIME_PERSISTENCE: '满足 one-tick richness 与持续时间门槛',
  SOURCE_LOSS_OR_KNOWN_FORMULA_INELIGIBILITY: '数据丢失或已知公式变为不合格时失效'
};

const predicateVectorKeys = {
  CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE: 'CREDIT_ABOVE_FUTURE_COST_RESERVE',
  UNDERWRITING_RESERVED_LOSS_LIMIT: 'UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT',
  MINIMUM_NET_ENTRY_CREDIT: 'MINIMUM_NET_ENTRY_CREDIT',
  MINIMUM_NET_CREDIT_TO_PAYOFF_CAP: 'MINIMUM_NET_CREDIT_TO_PAYOFF_CAP'
};

const postCloseAttemptLabels = {
  NOT_SCHEDULED: '尚未安排',
  SCHEDULED: '已安排',
  TERMINAL: '已终结',
  ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS: '进程中断后状态未知（不重试）'
};

const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[character]);

const isMissing = value => value === null || value === undefined || value === '';
const isIdentity = value => typeof value === 'string' && value.length > 0;
const displayText = value => isMissing(value)
  ? '—'
  : (typeof value === 'object' ? JSON.stringify(value) : String(value));
const safeText = value => escapeHtml(displayText(value));
const reasonText = value => isMissing(value) ? '—' : (reasonLabels[value] || String(value));

function syncThemeControl() {
  if (!document.documentElement || typeof document.querySelectorAll !== 'function') return;
  const currentTheme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  for (const button of document.querySelectorAll('[data-theme-option]')) {
    button.setAttribute('aria-pressed', button.dataset.themeOption === currentTheme ? 'true' : 'false');
  }
}

function setTheme(theme) {
  if (!['light', 'dark'].includes(theme) || !document.documentElement) return;
  document.documentElement.dataset.theme = theme;
  try {
    const storage = globalThis.localStorage;
    if (storage && typeof storage.setItem === 'function') storage.setItem(THEME_STORAGE_KEY, theme);
  } catch (_error) {
    // Theme persistence is optional; the visible selection remains active for this page.
  }
  syncThemeControl();
}

function restoreThemePreference() {
  if (!document.documentElement) return;
  try {
    const storage = globalThis.localStorage;
    if (!storage || typeof storage.getItem !== 'function') return;
    const savedTheme = storage.getItem(THEME_STORAGE_KEY);
    if (['light', 'dark'].includes(savedTheme)) document.documentElement.dataset.theme = savedTheme;
  } catch (_error) {
    // The HTML default remains the truthful fallback when browser storage is unavailable.
  }
}

restoreThemePreference();

const formatCompactNumber = (value, digits = 2) => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  });
};

const formatDecimal = value => {
  if (isMissing(value)) return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return displayText(value);
  return numeric.toLocaleString('zh-CN', {maximumFractionDigits: 8});
};

const formatMoney = value => isMissing(value) ? '—' : formatCompactNumber(value, 2);
const formatNative = value => isMissing(value) ? '—' : formatCompactNumber(value, 8);
const formatPercent = value => isMissing(value) || !Number.isFinite(Number(value))
  ? '—'
  : `${(Number(value) * 100).toFixed(1)}%`;

const formatInterval = (value, formatter) => {
  if (!value || isMissing(value.lower) || isMissing(value.upper)) return '—';
  const lower = formatter(value.lower);
  const upper = formatter(value.upper);
  return lower === upper ? lower : `${lower} – ${upper}`;
};

const scoreIntervalText = packet => {
  const result = scorePacketResult(packet);
  return result ? formatInterval(result.score, value => formatCompactNumber(value, 1)) : '—';
};

const scoreComponentText = (packet, member) => {
  const result = scorePacketResult(packet);
  return result ? formatInterval(result[member], formatPercent) : '—';
};

const scoreCoverageText = packet => {
  const result = scorePacketResult(packet);
  if (!result) return 'UNKNOWN';
  const missing = Array.isArray(result.missing_factors) ? result.missing_factors : [];
  return `${displayText(result.coverage)}${missing.length ? ` · 缺失 ${missing.join('/')}` : ' · 无缺失因子'}`;
};

const scoreBucketText = packet => {
  const bucket = packet && packet.bucket_key;
  if (!bucket || typeof bucket !== 'object') return '—';
  return `${displayText(bucket.tte_band_id)} · ${formatDate(bucket.expiry_ms)} · ` +
    `${optionTypeText(bucket.option_type)} · ${displayText(bucket.delta_bucket)}`;
};

const legacyDiagnosticText = packet => {
  if (!packet || packet.legacy_v1_threshold_pass === null ||
      packet.legacy_v1_threshold_pass === undefined) return '跨界/不可判定';
  return packet.legacy_v1_threshold_pass ? '通过' : '未通过';
};

const scorePacketCardMarkup = (label, packet) => {
  const result = scorePacketResult(packet);
  if (!result) {
    return `<div class="data-gap-panel"><strong>${escapeHtml(label)}：</strong>` +
      `服务器未提供 V2 score packet；浏览器不补算。</div>`;
  }
  const boundary = packet.fact_boundary && packet.fact_boundary.causal_seq;
  return `<div class="economics-card">` +
    `<span class="economics-label">${escapeHtml(label)}</span>` +
    `<span class="economics-value">${safeText(scoreIntervalText(packet))} · ${safeText(result.band)}</span>` +
    `<span class="economics-meta">coverage ${safeText(scoreCoverageText(packet))} · causal #${safeText(boundary)}</span>` +
    `<span class="economics-meta">leader ${safeText(packet.leader_instrument_name)}</span></div>`;
};

const scoreFactorMarkup = packet => {
  const result = scorePacketResult(packet);
  const factors = result && Array.isArray(result.factors) ? result.factors : [];
  if (!factors.length) return '<div class="data-gap-panel">服务器未提供 A/S/T/D/E 因子投影。</div>';
  return `<div class="predicate-list">${factors.map(factor => {
    const normalized = formatInterval(factor.normalized, value => formatCompactNumber(value, 3));
    const contribution = formatInterval(
      factor.weighted_contribution,
      value => formatCompactNumber(value, 3)
    );
    const detail = factor.unknown_reason || `标准化 ${normalized} · 加权 ${contribution}`;
    return `<div class="predicate-row"><span>因子 ${safeText(factor.name)}</span>` +
      `<span class="predicate-margin">${safeText(detail)}</span></div>`;
  }).join('')}</div>`;
};

const formatDurationMs = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '—';
  const milliseconds = Math.max(0, Number(value));
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  if (milliseconds < 3600000) return `${(milliseconds / 60000).toFixed(1)} 分钟`;
  if (milliseconds < 86400000) return `${(milliseconds / 3600000).toFixed(1)} 小时`;
  return `${Math.floor(milliseconds / 86400000)}d ${Math.floor((milliseconds % 86400000) / 3600000)}h`;
};

const formatDurationInterval = value => {
  if (!value || !Number.isFinite(Number(value.lower_ms)) || !Number.isFinite(Number(value.upper_ms))) {
    return '—';
  }
  const lower = formatDurationMs(value.lower_ms);
  const upper = formatDurationMs(value.upper_ms);
  return lower === upper ? lower : `${lower} – ${upper}`;
};

const formatDate = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC', day: '2-digit', month: 'short'
  }).format(new Date(Number(value))).toUpperCase();
};

const formatTimestamp = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(new Date(Number(value)));
};

const formatStrike = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '—';
  const numeric = Number(value);
  if (Math.abs(numeric) >= 1000) {
    const scaled = numeric / 1000;
    return `${scaled.toLocaleString('en-US', {maximumFractionDigits: 1})}k`;
  }
  return formatCompactNumber(numeric, 1);
};

const shortIdentity = value => {
  if (isMissing(value)) return '—';
  const text = String(value);
  return text.length <= 22 ? text : `${text.slice(0, 12)}…${text.slice(-6)}`;
};

const optionTypeText = value => value === 'put' ? 'Put' : (value === 'call' ? 'Call' : displayText(value));
const structureTypeText = row => row.queue_row_kind === 'SHADOW_ENTRY'
  ? '冻结双腿' : `${optionTypeText(row.option_type)} Spread`;
const structureLabel = row => row.queue_row_kind === 'SHADOW_ENTRY'
  ? '冻结入场结构'
  : `${formatDate(row.expiry_timestamp_ms)} · ${formatStrike(row.short_strike_price)} / ${formatStrike(row.long_strike_price)} ${structureTypeText(row)}`;

const badgeMarkup = (label, tone = 'neutral', extraClass = 'state-badge') =>
  `<span class="${escapeHtml(extraClass)} tone-${escapeHtml(tone)}">${safeText(label)}</span>`;

const factMarkup = (label, value) =>
  `<div class="fact"><span class="fact-label">${escapeHtml(label)}</span>` +
  `<span class="fact-value">${safeText(value)}</span></div>`;

const economicsCard = (label, value, meta, variant = '') =>
  `<div class="economics-card${variant ? ` ${escapeHtml(variant)}` : ''}">` +
  `<span class="economics-label">${escapeHtml(label)}</span>` +
  `<span class="economics-value">${safeText(value)}</span>` +
  `<span class="economics-meta">${safeText(meta)}</span></div>`;

const stageCount = (documentValue, stageName) => {
  const stages = documentValue && documentValue.funnel && documentValue.funnel.stages;
  if (!Array.isArray(stages)) return null;
  const stage = stages.find(value => value.stage === stageName);
  return stage ? stage.observed_count : null;
};

const channelSnapshotState = documentValue => {
  if (!documentValue) {
    return {code: 'UNAVAILABLE', label: '连接中断', tone: 'amber', note: '旧快照已隐藏'};
  }
  const product = documentValue.product || {};
  const policies = documentValue.policy_identities || {};
  if (documentValue.channel_id !== ACTIVE_CHANNEL_ID ||
      product.name !== 'inverse-btc' ||
      product.product_spec_identity !== ACTIVE_PRODUCT_SPEC_IDENTITY ||
      policies.radar !== ACTIVE_POLICY_IDENTITIES.radar ||
      policies.underwriting !== ACTIVE_POLICY_IDENTITIES.underwriting ||
      policies.position !== ACTIVE_POLICY_IDENTITIES.position) {
    return {code: 'IDENTITY_MISMATCH', label: '身份不匹配', tone: 'red', note: '拒绝展示'};
  }
  if (!documentValue.service || !documentValue.service.ready) {
    return {code: 'DATA_BLOCKED', label: '数据不可判断', tone: 'amber',
      note: reasonText(documentValue.service && documentValue.service.reason)};
  }
  return {code: 'CONNECTED', label: '当前可用', tone: 'green',
    note: `${formatCompactNumber(documentValue.system && documentValue.system.data_delay_ms, 0)} ms`};
};

const runtimeStatusState = documentValue => {
  if (!documentValue) {
    return {
      key: 'unknown', label: 'Runtime 状态未知', detail: '工作台连接中断',
      blocker: '系统阻塞：当前快照不可用；旧业务数据已隐藏'
    };
  }
  const snapshotState = channelSnapshotState(documentValue);
  const identityMismatch = snapshotState.code === 'IDENTITY_MISMATCH';
  const service = documentValue.service || {};
  if (typeof service.phase !== 'string' || typeof service.data_state !== 'string' ||
      typeof service.health !== 'boolean' || typeof service.ready !== 'boolean' ||
      typeof service.stale !== 'boolean') {
    return {
      key: 'unknown', label: 'Runtime 状态未知', detail: '服务状态字段不完整',
      blocker: '系统阻塞：无法从当前快照确认 Runtime 状态'
    };
  }
  const phaseAndData = `${service.phase} · ${service.data_state}`;
  const reason = reasonText(service.reason);
  if (service.phase === 'STOPPED') {
    return {key: 'stopped', label: 'Runtime 已停止', detail: phaseAndData,
      blocker: `停止原因：${reason}${identityMismatch ? '；决策快照身份不匹配' : ''}`};
  }
  if (service.phase === 'FAILED' || !service.health) {
    return {key: 'failed', label: 'Runtime 运行失败', detail: phaseAndData,
      blocker: `运行失败：${reason}${identityMismatch ? '；决策快照身份不匹配' : ''}`};
  }
  if (service.phase === 'STARTING' || service.phase === 'CONNECTING') {
    return {key: 'starting', label: 'Runtime 准备中', detail: phaseAndData,
      blocker: `准备原因：${reason}`};
  }
  if (service.phase === 'STOPPING') {
    return {key: 'starting', label: 'Runtime 正在停止', detail: phaseAndData,
      blocker: `停止原因：${reason}`};
  }
  if (service.phase === 'RECONNECTING') {
    return {key: 'degraded', label: 'Runtime 连接受阻', detail: phaseAndData,
      blocker: `连接阻塞：${reason}`};
  }
  if (service.phase === 'RUNNING' && service.ready && service.data_state === 'CURRENT') {
    if (identityMismatch) {
      return {
        key: 'degraded', label: 'Runtime 正常运行', detail: '决策快照受阻',
        blocker: '快照受阻：产品或 Policy 身份不匹配，当前业务数据拒绝展示'
      };
    }
    return {
      key: 'healthy', label: 'Runtime 正常运行', detail: '决策数据当前可用',
      blocker: '系统阻塞：无；业务机会仍以队列门槛为准'
    };
  }
  if (service.phase === 'RUNNING') {
    const noApplicableScope = ['NO_APPLICABLE_SCOPE', 'NO_APPLICABLE_MARKET_SCOPE_OBSERVED']
      .includes(service.reason);
    return {
      key: 'degraded', label: 'Runtime 正常运行', detail: `决策数据 ${service.data_state}`,
      blocker: noApplicableScope
        ? '决策数据：当前无适用合约范围（非 Runtime 故障）'
        : `决策数据受阻：${reason}`
    };
  }
  return {
    key: 'unknown', label: 'Runtime 状态未知', detail: phaseAndData,
    blocker: `系统阻塞：未识别的服务阶段 ${service.phase}`
  };
};

const roadmapState = channel => {
  if (channel.id === 'INVERSE_BTC_LONG_GAMMA') {
    return {label: '尚未接入', tone: 'neutral', note: '无 Long Gamma 决策契约'};
  }
  if (channel.id === 'INVERSE_ETH_SHORT_VOL') {
    return {label: '尚未接入', tone: 'neutral', note: '无 ETH 产品快照'};
  }
  return {label: '尚未接入', tone: 'neutral', note: '无产品与策略快照'};
};

const shadowTrackingPresentation = row => {
  const shadow = row && row.shadow_entry_projection;
  if (!shadow) return null;
  const gapped = shadow.observation_quality === 'GAPPED';
  const qualificationExcluded = shadow.qualification_eligible === false;
  if (!gapped && !qualificationExcluded) return null;
  return {
    label: gapped ? '跨进程跟踪' : 'Shadow 跟踪',
    note: gapped && qualificationExcluded
      ? '观察有间隙 · 不计入连续观察资格'
      : (gapped ? '观察有间隙' : '不计入连续观察资格')
  };
};

const structureState = row => {
  if (Array.isArray(row.shadow_projection_issues) && row.shadow_projection_issues.length) {
    return {key: 'UNKNOWN', label: 'Shadow 投影异常', tone: 'red', priority: 1};
  }
  if (row.candidate_lifecycle === 'ADMITTED') {
    const tracking = shadowTrackingPresentation(row);
    if (tracking) {
      return {
        key: 'SHADOW_TRACKING', label: tracking.label, tone: 'purple', priority: 0,
        note: tracking.note
      };
    }
    return {key: 'SHADOW_TRACKING', label: 'Shadow 跟踪', tone: 'purple', priority: 0};
  }
  if (row.candidate_lifecycle === 'INVALIDATED') {
    return {key: 'INVALIDATED', label: '候选已失效', tone: 'red', priority: 7};
  }
  if (row.candidate_lifecycle === 'VALID' && row.candidate_still_valid === true) {
    return {key: 'CANDIDATE', label: 'Shadow 候选', tone: 'green', priority: 1};
  }
  if (row.availability === 'UNKNOWN') {
    return {key: 'UNKNOWN', label: '暂不可判断', tone: 'amber', priority: 5};
  }
  if (row.availability === 'NOT_EVALUATED') {
    return {key: 'NOT_EVALUATED', label: '尚未评估', tone: 'neutral', priority: 6};
  }
  if (row.action === 'CANDIDATE') {
    return {key: 'CANDIDATE_UNCONFIRMED', label: '承保通过 · 待确认', tone: 'blue', priority: 2};
  }
  if (row.action === 'WATCH') {
    return {key: 'WATCH', label: '继续观察', tone: 'amber', priority: 3};
  }
  if (row.action === 'ABSTAIN') {
    return {key: 'ABSTAIN', label: '暂不参与', tone: 'neutral', priority: 4};
  }
  return {key: 'UNKNOWN', label: '暂不可判断', tone: 'amber', priority: 5};
};

const scorePacketResult = packet => packet && typeof packet === 'object' &&
  packet.result && typeof packet.result === 'object' ? packet.result : null;

const radarScoreView = row => row.score_packet || (
  row.score_result && typeof row.score_result === 'object'
    ? {
        result: row.score_result,
        bucket_key: row.score_bucket_key,
        leader_instrument_name: row.bucket_leader_instrument_name,
        leader_coverage: row.bucket_leader_coverage,
      }
    : null
);

const scorePacketState = packet => {
  const result = scorePacketResult(packet);
  if (!result) return {key: 'UNKNOWN', label: '暂不可判断', tone: 'amber', priority: 4};
  if (result.band === 'HIGH') return {key: 'HIGH', label: 'HIGH 机会线索', tone: 'blue', priority: 0};
  if (result.band === 'MID') return {key: 'MID', label: 'MID 待观察', tone: 'purple', priority: 1};
  if (result.band === 'LOW') return {key: 'LOW', label: 'LOW 低优先级', tone: 'neutral', priority: 3};
  if (result.band === 'REVIEW') return {key: 'REVIEW', label: '分数边界复核', tone: 'amber', priority: 2};
  return {key: 'UNKNOWN', label: '暂不可判断', tone: 'amber', priority: 4};
};

const radarState = row => {
  const raw = scorePacketState(radarScoreView(row));
  const active = row.is_bucket_leader === true &&
    row.bucket_episode_leader_instrument_name === row.instrument_name &&
    row.bucket_episode_state === 'ACTIVE' &&
    row.bucket_episode_score_band === raw.key && Boolean(row.bucket_episode_identity);
  const count = isMissing(row.confirmation_observation_count)
    ? '—' : row.confirmation_observation_count;
  const required = isMissing(row.required_confirmation_observation_count)
    ? '—' : row.required_confirmation_observation_count;
  if (raw.key === 'HIGH') {
    return active
      ? {...raw, label: 'HIGH · 已确认线索'}
      : {...raw, label: `HIGH · 确认中 ${count}/${required}`, tone: 'amber'};
  }
  if (raw.key === 'MID' || raw.key === 'LOW') {
    return active
      ? {...raw, label: `${raw.key} · 研究 Control 已确认`}
      : {...raw, label: `${raw.key} · 确认中 ${count}/${required}`};
  }
  return raw;
};

const structureIdentity = (row, index = 0) => {
  if (row.queue_row_kind === 'SHADOW_ENTRY') {
    if (row.shadow_candidate_identity_unique === true) return row.candidate_identity;
    if (row.shadow_entry_identity_unique === true) return row.shadow_entry_identity;
    return row.shadow_projection_row_key || `shadow-projection-${index}`;
  }
  return [row.candidate_identity, row.underwriting_availability_evaluation_identity,
    row.underwriting_action_identity, row.radar_scope_or_short_leg_identity]
    .find(isIdentity) || `structure-${index}`;
};
const radarIdentity = (row, index = 0) => row.active_episode_identity || row.instrument_name || `radar-${index}`;

const shadowRowsForCandidate = (row, documentValue) => {
  if (!isIdentity(row.candidate_identity)) return [];
  const shadowRows = documentValue.shadow_entries && Array.isArray(documentValue.shadow_entries.rows)
    ? documentValue.shadow_entries.rows : [];
  return shadowRows.filter(value => value.candidate_identity === row.candidate_identity);
};

const shadowRowForCandidate = (row, documentValue) => {
  const matches = shadowRowsForCandidate(row, documentValue);
  return matches.length === 1 ? matches[0] : null;
};

const canonicalShadowEntry = (row, documentValue) => {
  if (row.queue_row_kind === 'SHADOW_ENTRY') {
    const shadow = row.shadow_entry_projection;
    if (!shadow || !isIdentity(row.shadow_entry_identity) ||
        shadow.shadow_entry_identity !== row.shadow_entry_identity) return null;
    if (isIdentity(row.candidate_identity) &&
        shadow.candidate_identity !== row.candidate_identity) return null;
    return shadow;
  }
  const matches = shadowRowsForCandidate(row, documentValue)
    .filter(value => isIdentity(value.shadow_entry_identity));
  return matches.length === 1 ? matches[0] : null;
};

const structureEntryFacts = (row, documentValue) => {
  const shadow = row.candidate_lifecycle === 'ADMITTED'
    ? canonicalShadowEntry(row, documentValue) : null;
  if (shadow) {
    return {
      source: 'SHADOW_ENTRY',
      status: shadow.admission_refresh_terminal_outcome || 'SHADOW_ENTRY',
      valuationIndex: shadow.entry_valuation_index_price,
      targetQuantity: shadow.target_quantity_btc,
      nativeNetCredit: shadow.native_net_entry_credit,
      nativeGrossCredit: shadow.native_gross_entry_credit,
      nativeFeeReserve: shadow.native_entry_fee_reserve,
      valuationGrossCredit: shadow.simulated_entry_credit_valuation
    };
  }
  if (row.queue_row_kind === 'SHADOW_ENTRY') {
    return {
      source: 'SHADOW_ENTRY_INVALID', status: 'PROJECTION_INVALID', valuationIndex: null,
      targetQuantity: null, nativeNetCredit: null, nativeGrossCredit: null,
      nativeFeeReserve: null, valuationGrossCredit: null
    };
  }
  return {
    source: 'UNDERWRITING',
    status: row.availability,
    valuationIndex: row.entry_valuation_index_price,
    targetQuantity: row.target_quantity_btc,
    nativeNetCredit: row.native_net_entry_credit,
    valuationNetCredit: row.net_entry_credit_valuation
  };
};

const shadowStructureRow = (shadow, candidateCounts = null, entryCounts = null, index = 0) => {
  const legs = Array.isArray(shadow.entry_component_legs) ? shadow.entry_component_legs : [];
  const shortLegs = legs.filter(value => value.canonical_leg_role === 'SHORT');
  const longLegs = legs.filter(value => value.canonical_leg_role === 'LONG');
  const shortLeg = shortLegs.length === 1 ? shortLegs[0] : null;
  const longLeg = longLegs.length === 1 ? longLegs[0] : null;
  const candidateIdentityUnique = isIdentity(shadow.candidate_identity) &&
    (!candidateCounts || candidateCounts.get(shadow.candidate_identity) === 1);
  const entryIdentityUnique = isIdentity(shadow.shadow_entry_identity) &&
    (!entryCounts || entryCounts.get(shadow.shadow_entry_identity) === 1);
  const issues = [];
  if (!isIdentity(shadow.shadow_entry_identity)) issues.push('MISSING_SHADOW_ENTRY_IDENTITY');
  else if (!entryIdentityUnique) issues.push('DUPLICATE_SHADOW_ENTRY_IDENTITY');
  if (!isIdentity(shadow.candidate_identity)) issues.push('MISSING_CANDIDATE_IDENTITY');
  else if (!candidateIdentityUnique) issues.push('DUPLICATE_CANDIDATE_IDENTITY');
  if (!shortLeg || !longLeg || legs.length !== 2) issues.push('INVALID_ENTRY_COMPONENT_ROLES');
  else if (shortLeg.action !== 'SELL' || longLeg.action !== 'BUY') {
    issues.push('INVALID_ENTRY_LEG_ACTIONS');
  }
  return {
    queue_row_kind: 'SHADOW_ENTRY',
    shadow_entry_projection: shadow,
    shadow_projection_row_key: `shadow-projection-${index}`,
    shadow_projection_issues: issues,
    shadow_candidate_identity_unique: candidateIdentityUnique,
    shadow_entry_identity_unique: entryIdentityUnique,
    shadow_entry_identity: shadow.shadow_entry_identity,
    candidate_identity: shadow.candidate_identity,
    candidate_lifecycle: 'ADMITTED',
    candidate_still_valid: false,
    availability: 'SHADOW_ENTRY',
    action: null,
    short_leg_action: shortLeg && shortLeg.action,
    long_leg_action: longLeg && longLeg.action,
    short_leg_instrument_name: shortLeg && shortLeg.instrument_name,
    long_leg_instrument_name: longLeg && longLeg.instrument_name,
    target_quantity_btc: shadow.target_quantity_btc,
    entry_valuation_index_price: shadow.entry_valuation_index_price,
    native_gross_entry_credit: shadow.native_gross_entry_credit,
    native_entry_fee_reserve: shadow.native_entry_fee_reserve,
    native_net_entry_credit: shadow.native_net_entry_credit,
    gross_entry_credit_valuation: shadow.simulated_entry_credit_valuation,
    failed_predicates: [],
    predicate_margin_vector: [],
    unknown_reasons: []
  };
};

const structureQueueRows = documentValue => {
  const projectedShadowRows = documentValue.shadow_entries && Array.isArray(documentValue.shadow_entries.rows)
    ? documentValue.shadow_entries.rows : [];
  const sourceShadowRows = projectedShadowRows.filter(value =>
    isIdentity(value.shadow_entry_identity) || value.admission_refresh_terminal_outcome === 'ENTRY_EMITTED');
  const candidateCounts = new Map();
  const entryCounts = new Map();
  sourceShadowRows.forEach(value => {
    if (isIdentity(value.candidate_identity)) {
      candidateCounts.set(value.candidate_identity, (candidateCounts.get(value.candidate_identity) || 0) + 1);
    }
    if (isIdentity(value.shadow_entry_identity)) {
      entryCounts.set(value.shadow_entry_identity, (entryCounts.get(value.shadow_entry_identity) || 0) + 1);
    }
  });
  const shadowRows = sourceShadowRows.map((value, index) =>
    shadowStructureRow(value, candidateCounts, entryCounts, index));
  const shadowCandidates = new Set(shadowRows.map(value => value.candidate_identity).filter(isIdentity));
  const underwritingRows = documentValue.underwriting && Array.isArray(documentValue.underwriting.rows)
    ? documentValue.underwriting.rows.filter(value => !shadowCandidates.has(value.candidate_identity)) : [];
  return orderedStructureRows([...shadowRows, ...underwritingRows]);
};

const orderedStructureRows = rows => [...rows].sort((left, right) =>
  structureState(left).priority - structureState(right).priority ||
  Number(left.expiry_timestamp_ms || 0) - Number(right.expiry_timestamp_ms || 0) ||
  String(left.short_leg_instrument_name || '').localeCompare(String(right.short_leg_instrument_name || ''))
);

const orderedRadarRows = rows => [...rows].sort((left, right) =>
  (Number.isFinite(Number(left.attention_rank)) ? Number(left.attention_rank) : 999999) -
    (Number.isFinite(Number(right.attention_rank)) ? Number(right.attention_rank) : 999999) ||
  radarState(left).priority - radarState(right).priority ||
  Number(left.expiration_timestamp_ms || 0) - Number(right.expiration_timestamp_ms || 0) ||
  String(left.instrument_name || '').localeCompare(String(right.instrument_name || ''))
);

const predicateMarginForFailure = (row, failedPredicate) => {
  const vector = Array.isArray(row.predicate_margin_vector) ? row.predicate_margin_vector : [];
  const vectorKey = predicateVectorKeys[failedPredicate] || failedPredicate;
  return vector.find(value => value.predicate === vectorKey) || null;
};

const formatMargin = margin => {
  if (!margin || isMissing(margin.signed_margin)) return '—';
  const value = formatCompactNumber(margin.signed_margin, margin.unit === 'FRACTION' ? 4 : 2);
  if (margin.unit === 'USD_EQUIVALENT') return `${value} USD 等值`;
  if (margin.unit === 'FRACTION') return `${value} 比例`;
  if (margin.unit === 'LEVEL_COUNT') return `${value} 层`;
  return `${value} ${displayText(margin.unit)}`;
};

const firstFailureSummary = row => {
  const projectionIssues = Array.isArray(row.shadow_projection_issues)
    ? row.shadow_projection_issues : [];
  if (projectionIssues.length) {
    return {label: 'Shadow 投影关联异常', margin: reasonText(projectionIssues[0])};
  }
  const failures = Array.isArray(row.failed_predicates) ? row.failed_predicates : [];
  if (failures.length) {
    const first = failures[0];
    return {label: reasonText(first), margin: formatMargin(predicateMarginForFailure(row, first))};
  }
  const state = structureState(row);
  if (state.key === 'SHADOW_TRACKING') {
    return {label: '已进入 Shadow 模拟跟踪', margin: '非当前 Candidate'};
  }
  if (state.key === 'INVALIDATED') {
    return {label: '候选已失效', margin: reasonText(row.candidate_invalidation_reason)};
  }
  if (state.key === 'UNKNOWN') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    return {label: '结构经济暂不可判断', margin: reasonText(reasons[0])};
  }
  if (state.key === 'NOT_EVALUATED') {
    return {label: '尚未进入经济评估', margin: '不可判断门槛'};
  }
  if (state.key === 'CANDIDATE_UNCONFIRMED') {
    return {label: '承保通过', margin: '生命周期未确认'};
  }
  if (state.key === 'CANDIDATE') {
    return {label: '经济谓词通过', margin: '等待 admission'};
  }
  return {label: `服务器未列失败谓词`, margin: `当前 ${state.label}`};
};

const structureJudgement = row => {
  const projectionIssues = Array.isArray(row.shadow_projection_issues)
    ? row.shadow_projection_issues : [];
  if (projectionIssues.length) {
    return {
      blocker: projectionIssues.map(reasonText).join('；'),
      upgrade: '等待服务端恢复唯一 Candidate、Shadow Entry 与冻结双腿身份；浏览器拒绝补推关联。'
    };
  }
  const failures = Array.isArray(row.failed_predicates) ? row.failed_predicates : [];
  if (failures.length) {
    return {
      blocker: failures.map(reasonText).join('；'),
      upgrade: `未通过 ${failures.length} 项条件；下方逐项显示 owner 已结算的 signed margin。`
    };
  }
  const state = structureState(row);
  if (state.key === 'SHADOW_TRACKING') {
    return {
      blocker: '无当前承保阻塞：该 Candidate 已进入 Shadow 模拟跟踪。',
      upgrade: '等待严格未来的 Position 与 Outcome 公共行情事实。'
    };
  }
  if (state.key === 'INVALIDATED') {
    return {
      blocker: `候选已失效：${reasonText(row.candidate_invalidation_reason)}`,
      upgrade: '该候选不再等待 admission；需要新的独立机会重新通过承保。'
    };
  }
  if (state.key === 'UNKNOWN') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    return {
      blocker: `结构经济暂不可判断：${reasons.map(reasonText).join('；') || '服务器未提供原因'}`,
      upgrade: '等待缺失的组件盘口或估值事实恢复后重新评估。'
    };
  }
  if (state.key === 'NOT_EVALUATED') {
    return {
      blocker: '尚未进入入场经济评估。',
      upgrade: '等待官方组合诊断与完整承保评估。'
    };
  }
  if (state.key === 'CANDIDATE_UNCONFIRMED') {
    return {
      blocker: '承保 action 已通过，但 Candidate 生命周期尚未确认。',
      upgrade: '等待 owner 发出 VALID 生命周期，再等待严格未来的 admission 刷新。'
    };
  }
  if (state.key === 'CANDIDATE') {
    return {
      blocker: '当前承保经济谓词已通过。',
      upgrade: '等待严格未来的 admission 刷新。'
    };
  }
  return {
    blocker: `服务器未列失败谓词；当前 action 为${state.label}。`,
    upgrade: '等待 owner 后续评估，不由浏览器推断已通过全部门槛。'
  };
};

const structureDecisionMarkup = (row, state = structureState(row)) =>
  badgeMarkup(state.label, state.tone, 'decision-badge') +
  (state.note ? `<span class="cell-secondary">${safeText(state.note)}</span>` : '');

let lastSuccessfulFetchAtMs = null;
let lastPublicationRuntimeIdentity = null;
let lastPublicationSequence = null;
let lastPublicationChangeAtMs = null;
let refreshInFlight = false;
const retiredRuntimeIdentities = new Set();
let currentDocument = null;
let selectedChannelId = 'ALL';
let queueMode = 'structures';
let structureFilter = 'ALL';
let radarFilter = 'ALL';
let selectedStructureId = null;
let selectedRadarId = null;
let drawerOpen = false;
let lastDetailTriggerId = null;
let evidenceExpanded = false;

const isDrawerViewport = () => typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' && window.matchMedia(DRAWER_MEDIA_QUERY).matches;

const setElementInert = (selector, inert) => {
  if (typeof document.querySelector !== 'function') return;
  const element = document.querySelector(selector);
  if (element) element.inert = inert;
};

const captureFocusIdentity = () => {
  const active = document.activeElement;
  if (!active || active === document.body) return null;
  if (active.id) return {kind: 'id', value: active.id};
  for (const key of ['channelId', 'queueMode', 'queueFilter', 'rowId']) {
    if (active.dataset && active.dataset[key]) return {kind: key, value: active.dataset[key]};
  }
  if (typeof active.matches === 'function' && active.matches('[data-evidence-details] summary')) {
    return {kind: 'evidence', value: 'summary'};
  }
  return null;
};

const restoreFocusIdentity = identity => {
  if (!identity) return;
  let target = null;
  if (identity.kind === 'id') {
    target = document.getElementById(identity.value);
  } else if (identity.kind === 'evidence' && typeof document.querySelector === 'function') {
    target = document.querySelector('[data-evidence-details] summary');
  } else if (typeof document.querySelectorAll === 'function') {
    target = Array.from(document.querySelectorAll(`[data-${identity.kind.replace(/[A-Z]/g, value => `-${value.toLowerCase()}`)}]`))
      .find(element => element.dataset && element.dataset[identity.kind] === identity.value);
  }
  if (target && typeof target.focus === 'function' && !target.hidden) target.focus();
};

function updateResponsiveDetailState() {
  const panel = document.getElementById('detail-panel');
  const scrim = document.getElementById('detail-scrim');
  if (!panel || !scrim) return;
  const drawer = isDrawerViewport();
  const open = drawer && drawerOpen;
  if (document.body && document.body.classList) {
    document.body.classList.toggle('detail-open', open);
  }
  panel.setAttribute('aria-hidden', drawer && !open ? 'true' : 'false');
  if (drawer) {
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
  } else {
    panel.setAttribute('role', 'complementary');
    panel.removeAttribute('aria-modal');
  }
  scrim.hidden = !open;
  setElementInert('.channel-rail', open);
  setElementInert('.queue-workspace', open);
  setElementInert('.topbar', open);
  setElementInert('#detail-panel', drawer && !open);
}

function focusDetailPanel() {
  const close = document.getElementById('detail-close');
  const panel = document.getElementById('detail-panel');
  const target = close || panel;
  if (target && typeof target.focus === 'function') target.focus();
}

function openDetail(rowId) {
  lastDetailTriggerId = rowId;
  if (!isDrawerViewport()) return;
  drawerOpen = true;
  updateResponsiveDetailState();
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(focusDetailPanel);
  else focusDetailPanel();
}

function restoreDetailTriggerFocus() {
  if (typeof document.querySelectorAll !== 'function') return;
  const trigger = Array.from(document.querySelectorAll('[data-row-id]'))
    .find(value => value.dataset.rowId === lastDetailTriggerId);
  if (trigger && typeof trigger.focus === 'function') trigger.focus();
}

function closeDetail() {
  if (!isDrawerViewport()) return;
  drawerOpen = false;
  updateResponsiveDetailState();
  restoreDetailTriggerFocus();
}

function renderChannelRail(documentValue) {
  const list = document.getElementById('channel-list');
  if (!list) return;
  const currentState = channelSnapshotState(documentValue);
  const allState = currentState.code === 'CONNECTED'
    ? {label: '1 / 4 已接入', tone: 'purple', note: '仅一条真实通道'}
    : {label: currentState.label, tone: currentState.tone, note: currentState.note};
  const allCard = `<button type="button" class="channel-card all-opportunities" data-channel-id="ALL" ` +
    `aria-pressed="${selectedChannelId === 'ALL'}"><span class="channel-name">全部机会</span>` +
    `<span class="channel-meta">${badgeMarkup(allState.label, allState.tone)}` +
    `<span class="channel-note">${safeText(allState.note)}</span></span></button>`;
  const cards = CHANNELS.map(channel => {
    const state = channel.id === ACTIVE_CHANNEL_ID ? currentState : roadmapState(channel);
    return `<button type="button" class="channel-card" data-channel-id="${escapeHtml(channel.id)}" ` +
      `aria-pressed="${selectedChannelId === channel.id}">` +
      `<span class="channel-name">${escapeHtml(channel.id)}</span>` +
      `<span class="channel-meta">${badgeMarkup(state.label, state.tone)}` +
      `<span class="channel-note">${safeText(state.note)}</span></span></button>`;
  }).join('');
  list.innerHTML = allCard + cards;
}

function renderHeader(documentValue) {
  const asOf = document.getElementById('as-of');
  const runtime = document.getElementById('runtime');
  const status = document.getElementById('runtime-status');
  const stateLabel = document.getElementById('runtime-state-label');
  const stateDetail = document.getElementById('runtime-state-detail');
  const servicePhase = document.getElementById('service-phase');
  const dataCurrentness = document.getElementById('data-currentness');
  const dataDelay = document.getElementById('data-delay');
  const blocker = document.getElementById('runtime-blocker');
  if (!asOf || !runtime || !status || !stateLabel || !stateDetail || !servicePhase ||
      !dataCurrentness || !dataDelay || !blocker) return;
  const state = runtimeStatusState(documentValue);
  const service = documentValue && documentValue.service;
  const system = documentValue && documentValue.system;
  status.dataset.state = state.key;
  stateLabel.textContent = state.label;
  stateDetail.textContent = state.detail;
  servicePhase.textContent = `服务 ${service ? displayText(service.phase) : '—'}`;
  dataCurrentness.textContent = `行情 ${service ? displayText(service.data_state) : '—'}`;
  dataDelay.textContent = `延迟 ${system ? formatDurationMs(system.data_delay_ms) : '—'}`;
  asOf.textContent = `行情时间 ${system ? formatTimestamp(system.latest_market_timestamp_ms) : '—'}`;
  runtime.textContent = `runtime ${documentValue ? shortIdentity(documentValue.runtime_identity) : '—'}`;
  blocker.textContent = state.blocker;
}

const selectedChannelCanUseCurrentSnapshot = documentValue =>
  ['ALL', ACTIVE_CHANNEL_ID].includes(selectedChannelId) &&
  channelSnapshotState(documentValue).code === 'CONNECTED';

function visibleRows(documentValue) {
  if (!selectedChannelCanUseCurrentSnapshot(documentValue)) return [];
  if (queueMode === 'structures') {
    const rows = structureQueueRows(documentValue);
    return structureFilter === 'ALL' ? rows : rows.filter(row => structureState(row).key === structureFilter);
  }
  const rows = orderedRadarRows(documentValue.radar.rows);
  return radarFilter === 'ALL' ? rows : rows.filter(row => radarState(row).key === radarFilter);
}

function totalRows(documentValue) {
  if (!selectedChannelCanUseCurrentSnapshot(documentValue)) return [];
  return queueMode === 'structures'
    ? structureQueueRows(documentValue)
    : orderedRadarRows(documentValue.radar.rows);
}

function renderFilters() {
  const filters = queueMode === 'structures' ? STRUCTURE_FILTERS : RADAR_FILTERS;
  const selected = queueMode === 'structures' ? structureFilter : radarFilter;
  document.getElementById('queue-filters').innerHTML = filters.map(([value, label]) =>
    `<button type="button" data-queue-filter="${escapeHtml(value)}" ` +
    `aria-pressed="${selected === value}">${escapeHtml(label)}</button>`
  ).join('');
  if (typeof document.querySelectorAll === 'function') {
    document.querySelectorAll('[data-queue-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.queueMode === queueMode));
    });
  }
}

function renderQueueHead() {
  const labels = queueMode === 'structures'
    ? ['优先级', '策略通道', '结构', '决策', '入场经济', '首项门槛差']
    : ['优先级', '策略通道', '合约', 'Score band', 'V2 分数', '覆盖 / 阻塞'];
  document.getElementById('queue-head').innerHTML = labels.map(value =>
    `<span role="columnheader">${escapeHtml(value)}</span>`
  ).join('');
}

function structureRowMarkup(row, index) {
  const id = structureIdentity(row, index);
  const state = structureState(row);
  const failure = firstFailureSummary(row);
  const entryFacts = structureEntryFacts(row, currentDocument);
  const nativeUnit = currentDocument.product.native_premium_currency;
  const valuationUnit = currentDocument.product.valuation_currency;
  const valuationCredit = entryFacts.source === 'SHADOW_ENTRY'
    ? entryFacts.valuationGrossCredit : entryFacts.valuationNetCredit;
  const valuationBasis = entryFacts.source === 'SHADOW_ENTRY' && !isMissing(valuationCredit)
    ? ' · 费前' : '';
  return `<button type="button" class="queue-row structure-row" role="row" ` +
    `data-row-id="${escapeHtml(id)}" aria-pressed="${selectedStructureId === id}">` +
    `<span class="queue-priority" role="cell">${index + 1}</span>` +
    `<span role="cell"><span class="cell-primary">BTC Short Vol</span>` +
    `<span class="cell-secondary">${escapeHtml(ACTIVE_CHANNEL_ID)}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(structureLabel(row))}</span>` +
    `<span class="cell-secondary">${safeText(row.short_leg_instrument_name)} → ${safeText(row.long_leg_instrument_name)}</span></span>` +
    `<span role="cell">${structureDecisionMarkup(row, state)}</span>` +
    `<span role="cell"><span class="cell-value">${safeText(formatNative(entryFacts.nativeNetCredit))} ${safeText(nativeUnit)}</span>` +
    `<span class="cell-secondary">${safeText(formatMoney(valuationCredit))} ${safeText(valuationUnit)}${valuationBasis}</span></span>` +
    `<span role="cell"><span class="cell-value ${failure.margin.startsWith('-') ? 'cell-warning' : ''}">${safeText(failure.margin)}</span>` +
    `<span class="cell-secondary">${safeText(failure.label)}</span></span></button>`;
}

function radarRowMarkup(row, index) {
  const id = radarIdentity(row, index);
  const state = radarState(row);
  const packet = radarScoreView(row);
  const result = scorePacketResult(packet);
  const rank = isMissing(row.attention_rank) ? index + 1 : row.attention_rank;
  return `<button type="button" class="queue-row radar-row" role="row" ` +
    `data-row-id="${escapeHtml(id)}" aria-pressed="${selectedRadarId === id}">` +
    `<span class="queue-priority" role="cell">${safeText(rank)}</span>` +
    `<span role="cell"><span class="cell-primary">BTC Short Vol</span>` +
    `<span class="cell-secondary">${escapeHtml(ACTIVE_CHANNEL_ID)}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(row.instrument_name)}</span>` +
    `<span class="cell-secondary">${safeText(formatDate(row.expiration_timestamp_ms))} · ${safeText(formatStrike(row.strike_price))} ${safeText(optionTypeText(row.option_type))}</span></span>` +
    `<span role="cell">${badgeMarkup(state.label, state.tone, 'decision-badge')}</span>` +
    `<span role="cell"><span class="cell-value">${safeText(scoreIntervalText(packet))}</span>` +
    `<span class="cell-secondary">Premium ${safeText(scoreComponentText(packet, 'premium_evidence'))} · Risk ${safeText(scoreComponentText(packet, 'risk_quality'))}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(scoreCoverageText(packet))}</span>` +
    `<span class="cell-secondary">${safeText(result ? `leader ${packet.leader_instrument_name}` : reasonText(row.primary_blocker || row.detector_reason))}</span></span></button>`;
}

function emptyQueueMarkup(documentValue) {
  if (!["ALL", ACTIVE_CHANNEL_ID].includes(selectedChannelId)) {
    const channel = CHANNELS.find(value => value.id === selectedChannelId);
    const state = channel ? roadmapState(channel) : roadmapState({id: ''});
    return `<div class="queue-empty"><strong>${safeText(state.label)}：${safeText(channel && channel.id)}</strong>` +
      `${safeText(state.note)}。此状态表示产品或策略真值尚未接入，不可解释为当前 0 个机会。</div>`;
  }
  const snapshotState = channelSnapshotState(documentValue);
  if (snapshotState.code !== 'CONNECTED') {
    return `<div class="queue-empty"><strong>${safeText(snapshotState.label)}</strong>` +
      `${safeText(snapshotState.note)}。旧业务数据已隐藏，恢复完整且身份匹配的快照后再显示。</div>`;
  }
  return `<div class="queue-empty"><strong>当前筛选没有匹配项</strong>` +
    `这只是当前筛选结果，不改变服务器报告的业务分母或状态。</div>`;
}

function renderQueue(documentValue) {
  const table = document.querySelector && document.querySelector('.queue-table');
  const previousScrollTop = table ? table.scrollTop : 0;
  renderFilters();
  renderQueueHead();
  const rows = visibleRows(documentValue);
  const total = totalRows(documentValue);
  const body = document.getElementById('queue-body');
  const context = document.getElementById('queue-context');
  const status = document.getElementById('queue-status');
  const roadmapOnly = !['ALL', ACTIVE_CHANNEL_ID].includes(selectedChannelId);
  const snapshotState = channelSnapshotState(documentValue);
  context.textContent = queueMode === 'structures'
    ? '结构队列与 Radar 线索分开呈现，避免浏览器误拼不同 Episode。'
    : '这里只显示当前 Radar 合约事实，不把线索称为 Candidate。';
  if (roadmapOnly) {
    status.textContent = '尚未接入 · 无独立队列快照';
  } else if (snapshotState.code !== 'CONNECTED') {
    status.textContent = `${snapshotState.label} · 不报告业务零值`;
  } else {
    status.textContent = `显示 ${rows.length} / ${total.length} · ` +
      (queueMode === 'structures' ? '按服务器已结算的结构状态排序' : '按服务器 Attention rank 排序');
  }
  if (!rows.length) {
    body.innerHTML = emptyQueueMarkup(documentValue);
  } else if (queueMode === 'structures') {
    const ids = rows.map(structureIdentity);
    if (!selectedStructureId || !ids.includes(selectedStructureId)) selectedStructureId = ids[0];
    body.innerHTML = rows.map(structureRowMarkup).join('');
  } else {
    const ids = rows.map(radarIdentity);
    if (!selectedRadarId || !ids.includes(selectedRadarId)) selectedRadarId = ids[0];
    body.innerHTML = rows.map(radarRowMarkup).join('');
  }
  if (table) table.scrollTop = previousScrollTop;
}

const rawEvidenceMarkup = row => `<details class="evidence-details" data-evidence-details${evidenceExpanded ? ' open' : ''}>` +
  `<summary>展开服务器原始证据</summary><pre class="evidence-raw">${escapeHtml(JSON.stringify(row, null, 2))}</pre></details>`;

const scorePacketComparisonMarkup = row => {
  const shadow = row && row.shadow_entry_projection;
  const selection = shadow && shadow.selection_score_packet;
  const refresh = shadow && shadow.entry_refresh_score_packet;
  if (!selection && !refresh) {
    return '<div class="data-gap-panel">当前结构尚未形成同时冻结 selection 与 entry-refresh packet 的 schema-v5 Case。</div>';
  }
  return `<div class="economics-grid">` +
    scorePacketCardMarkup('Selection score', selection) +
    scorePacketCardMarkup('Entry-refresh score', refresh) +
    `</div><div class="data-gap-panel"><strong>Drift 读取规则：</strong>` +
    `并列展示两个服务器冻结 packet 的 score、band、coverage、boundary 与 leader；浏览器不相减、不重算、不归因。</div>`;
};

const predicateListMarkup = row => {
  const vector = Array.isArray(row.predicate_margin_vector) ? row.predicate_margin_vector : [];
  if (!vector.length) return '<div class="data-gap-panel">当前结构没有可显示的精确谓词 margin。</div>';
  return `<div class="predicate-list">${vector.map(value =>
    `<div class="predicate-row${value.passes ? ' predicate-pass' : ''}">` +
    `<span>${safeText(reasonText(value.predicate))}</span>` +
    `<span class="predicate-margin">${safeText(formatMargin(value))}</span></div>`
  ).join('')}</div>`;
};

const postCloseAttemptText = value => isMissing(value)
  ? '—'
  : (postCloseAttemptLabels[value] || displayText(value));

const shadowTrackingEvidenceMarkup = shadow => {
  if (!shadow || typeof shadow !== 'object') return '';
  const gapped = shadow.observation_quality === 'GAPPED';
  const qualificationExcluded = shadow.qualification_eligible === false;
  const parts = [];
  if (gapped) {
    parts.push(`<div class="callout info"><strong>跨进程跟踪</strong>` +
      `观察有间隙；这是服务器声明的观察质量，不是异常或当前交易阻塞。</div>`);
  }
  if (qualificationExcluded) {
    parts.push(`<div class="callout info"><strong>研究资格</strong>` +
      `不计入连续观察资格；已登记的真实 Shadow Entry 入场经济仍保留。</div>`);
  }
  if (gapped) {
    parts.push(`<div class="fact-grid">` +
      factMarkup('Origin runtime', shortIdentity(shadow.origin_runtime_identity)) +
      factMarkup('观察 Segment', isMissing(shadow.current_segment_sequence)
        ? '—' : `#${displayText(shadow.current_segment_sequence)}`) +
      factMarkup('平仓尝试', postCloseAttemptText(shadow.post_close_attempt_state)) +
      `</div>`);
  }
  const entryBoundary = shadow.entry_fact_boundary && typeof shadow.entry_fact_boundary === 'object'
    ? shadow.entry_fact_boundary : null;
  const sourceRefs = Array.isArray(shadow.entry_component_quote_source_refs)
    ? shadow.entry_component_quote_source_refs : [];
  const sourceTimes = sourceRefs
    .map(value => value && value.source_timestamp_ms)
    .filter(value => Number.isFinite(Number(value)));
  if (entryBoundary || sourceTimes.length) {
    parts.push(`<div class="fact-grid">` +
      factMarkup('入场 causal seq', entryBoundary ? displayText(entryBoundary.causal_seq) : '—') +
      factMarkup('双腿源时间', sourceTimes.length ? sourceTimes.map(displayText).join(' / ') : '—') +
      `</div>`);
  }
  return parts.join('');
};

function canonicalShadowMarkup(row, documentValue) {
  const projectionIssues = Array.isArray(row.shadow_projection_issues)
    ? row.shadow_projection_issues : [];
  if (projectionIssues.length) {
    return `<div class="callout blocker"><strong>Shadow 投影关联异常</strong>` +
      `${safeText(projectionIssues.map(reasonText).join('；'))}；拒绝推断 Candidate、Position 或 Outcome 关联。</div>`;
  }
  if (!isIdentity(row.candidate_identity)) {
    return `<div class="callout info"><strong>Shadow 状态</strong>` +
      `当前结构没有 canonical Candidate identity，未建立与 Shadow 跟踪的规范关联。</div>`;
  }
  if (row.candidate_lifecycle === 'INVALIDATED') {
    return `<div class="callout blocker"><strong>Shadow 状态</strong>` +
      `候选已失效：${safeText(reasonText(row.candidate_invalidation_reason))}；不再等待 admission。</div>`;
  }
  const shadowProjection = shadowRowForCandidate(row, documentValue);
  const shadow = canonicalShadowEntry(row, documentValue);
  if (!shadow) {
    const terminal = shadowProjection && shadowProjection.admission_refresh_terminal_outcome;
    if (!isMissing(terminal)) {
      const unknownReasons = Array.isArray(shadowProjection.admission_refresh_unknown_reasons)
        ? shadowProjection.admission_refresh_unknown_reasons.map(reasonText).join('；') : '';
      return `<div class="callout blocker"><strong>Shadow admission 已终结</strong>` +
        `${safeText(terminal)}${unknownReasons ? ` · ${safeText(unknownReasons)}` : ''}；未建立 Shadow Entry，不再称为等待刷新。</div>`;
    }
    if (row.candidate_lifecycle === 'ADMITTED') {
      return `<div class="callout blocker"><strong>Shadow 关联缺口</strong>` +
        `Candidate lifecycle 为 ADMITTED，但当前投影没有匹配的 Shadow Entry identity；拒绝推断已建立跟踪。</div>`;
    }
    if (row.candidate_lifecycle !== 'VALID' || row.candidate_still_valid !== true) {
      return `<div class="callout info"><strong>Shadow 状态</strong>` +
        `承保 action 已通过，但 Candidate 生命周期尚未确认为 VALID；不计为等待 admission 的 Shadow 候选。</div>`;
    }
    return `<div class="callout info"><strong>Shadow 状态</strong>` +
      `Shadow 候选正在等待严格未来的成对双腿公共盘口刷新；不是订单或成交。</div>`;
  }
  const positionRows = documentValue.positions && Array.isArray(documentValue.positions.rows)
    ? documentValue.positions.rows : [];
  const position = positionRows.find(value => value.shadow_entry_identity === shadow.shadow_entry_identity);
  const outcomeRows = documentValue.outcomes && Array.isArray(documentValue.outcomes.rows)
    ? documentValue.outcomes.rows : [];
  const outcome = outcomeRows.find(value => value.shadow_entry_identity === shadow.shadow_entry_identity);
  const parts = [
    `<div class="callout info"><strong>Shadow 模拟跟踪已建立</strong>` +
      `公共盘口反事实已登记；不是订单、成交或实际持仓。</div>`
  ];
  const trackingEvidence = shadowTrackingEvidenceMarkup(shadow);
  if (trackingEvidence) parts.push(trackingEvidence);
  if (position) {
    parts.push(`<div class="callout info"><strong>当前模拟建议</strong>` +
      `${safeText(position.position_action)} · ${safeText(position.primary_exit_rule)} · hard-close ${safeText(formatDurationInterval(position.hard_close_countdown_interval_ms))}</div>`);
    if (position.valid_shadow_close_opportunity === true && !isMissing(position.projected_shadow_pnl_valuation)) {
      parts.push(`<div class="callout upgrade"><strong>公共盘口模拟盈亏</strong>` +
        `${safeText(formatMoney(position.projected_shadow_pnl_valuation))} ${safeText(documentValue.product.valuation_currency)}；不是实际账户 PnL。</div>`);
    }
  }
  if (!outcome || ['PENDING', 'PENDING_OUTCOME'].includes(outcome.state)) {
    parts.push(`<div class="callout blocker"><strong>Outcome</strong>` +
      `等待严格未来的合格双腿平仓事实；当前 PnL 不是 0，而是尚不可得。</div>`);
  } else {
    parts.push(`<div class="callout info"><strong>Outcome</strong>${safeText(outcome.state)}；` +
      `只有经济字段已知时才显示公共盘口 Shadow 结果。</div>`);
  }
  return parts.join('');
}

function structureDetailMarkup(row, documentValue) {
  const state = structureState(row);
  const nativeUnit = documentValue.product.native_premium_currency;
  const valuationUnit = documentValue.product.valuation_currency;
  const judgement = structureJudgement(row);
  const entryFacts = structureEntryFacts(row, documentValue);
  const isShadowEntry = entryFacts.source !== 'UNDERWRITING';
  const shadowLegProjectionInvalid = isShadowEntry && Array.isArray(row.shadow_projection_issues) &&
    row.shadow_projection_issues.some(value =>
      ['INVALID_ENTRY_COMPONENT_ROLES', 'INVALID_ENTRY_LEG_ACTIONS'].includes(value));
  const economicsMarkup = isShadowEntry
    ? economicsCard(`净信用（${nativeUnit}）`, formatNative(entryFacts.nativeNetCredit), '扣除双腿费用准备', 'positive') +
      economicsCard(`费前信用（${nativeUnit}）`, formatNative(entryFacts.nativeGrossCredit), '双腿压力价差', 'positive') +
      economicsCard(`费用准备（${nativeUnit}）`, formatNative(entryFacts.nativeFeeReserve), '两腿标准公共手续费', 'caution') +
      economicsCard(`费前信用（${valuationUnit}）`, formatMoney(entryFacts.valuationGrossCredit), '入场边界 USD 等值')
    : economicsCard(`净信用（${nativeUnit}）`, formatNative(entryFacts.nativeNetCredit), '原生币本位现金流', 'positive') +
      economicsCard(`净信用（${valuationUnit}）`, formatMoney(entryFacts.valuationNetCredit), '评估边界 USD 等值', 'positive') +
      economicsCard(`未来成本准备（${valuationUnit}）`, formatMoney(row.future_cost_reserve_valuation), '不是实际账户保证金', 'caution') +
      economicsCard(`承保准备损失（${valuationUnit}）`, formatMoney(row.underwriting_reserved_loss_valuation), 'Policy 风险准备');
  const riskBoundary = isShadowEntry
    ? '当前 Shadow Entry 投影未提供到期 BTC 负债、精确最大损失或账户保证金；不由浏览器推断。'
    : `入场边界损失代理 ${formatMoney(row.entry_boundary_valued_payoff_loss_ex_fees_valuation)} ${valuationUnit}；` +
      '不是到期 BTC 负债、精确最大损失或账户保证金。';
  const legTableMarkup = isShadowEntry
    ? shadowLegProjectionInvalid
      ? '<div class="data-gap-panel">冻结双腿的角色或方向投影不完整；拒绝由浏览器补写 SELL/BUY。</div>'
      : `<table class="leg-table"><thead><tr><th scope="col">方向</th><th scope="col">冻结合约</th></tr></thead><tbody>` +
        `<tr><td class="leg-sell">${safeText(row.short_leg_action)}</td><td>${safeText(row.short_leg_instrument_name)}</td></tr>` +
        `<tr><td class="leg-buy">${safeText(row.long_leg_action)}</td><td>${safeText(row.long_leg_instrument_name)}</td></tr>` +
        `</tbody></table>`
    : `<table class="leg-table"><thead><tr><th scope="col">方向</th><th scope="col">合约</th><th scope="col">执行价</th></tr></thead><tbody>` +
      `<tr><td class="leg-sell">SELL</td><td>${safeText(row.short_leg_instrument_name)}</td><td>${safeText(formatDecimal(row.short_strike_price))}</td></tr>` +
      `<tr><td class="leg-buy">BUY</td><td>${safeText(row.long_leg_instrument_name)}</td><td>${safeText(formatDecimal(row.long_strike_price))}</td></tr>` +
      `</tbody></table>`;
  const predicateMarkup = isShadowEntry
    ? '<div class="data-gap-panel">当前 Shadow Entry 投影未提供入场时的精确谓词 margin；不从当前 Underwriting 窗口补值。</div>'
    : predicateListMarkup(row);
  const structureSectionTitle = isShadowEntry
    ? '结构（冻结入场双腿）'
    : `结构（卖出 ${structureTypeText(row)}）`;
  return `<div class="detail-title-line"><h3>INVERSE BTC × SHORT VOL</h3>` +
    `${badgeMarkup(state.label, state.tone, 'decision-badge')}</div>` +
    `<p class="detail-subtitle">${safeText(structureLabel(row))}</p>` +
    `<div class="fact-grid">` +
      (isShadowEntry
        ? factMarkup('Shadow Entry', shortIdentity(row.shadow_entry_identity))
        : factMarkup('到期日', formatDate(row.expiry_timestamp_ms))) +
      factMarkup(isShadowEntry ? '入场边界指数' : '评估边界指数', formatMoney(entryFacts.valuationIndex)) +
      factMarkup('目标规模', `${formatDecimal(entryFacts.targetQuantity)} BTC`) +
      factMarkup(isShadowEntry ? '跟踪状态' : '评估状态', entryFacts.status) +
      factMarkup('原生现金流', nativeUnit) +
      factMarkup('估值单位', valuationUnit) +
    `</div>` +
    `<section class="detail-section" data-detail-section="structure"><div class="detail-section-title">` +
      `<h4>${safeText(structureSectionTitle)}</h4><span class="detail-section-note">公共盘口反事实</span></div>` +
      `${legTableMarkup}</section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>入场经济</h4>` +
      `<span class="detail-section-note">${isShadowEntry ? 'Shadow Entry 已结算' : '服务器已结算'} · 浏览器不重算</span></div>` +
      `<div class="economics-grid">${economicsMarkup}</div></section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>交易判断</h4></div>` +
      `<div class="callout-list">` +
        `<div class="callout blocker"><strong>主要阻塞</strong>${safeText(judgement.blocker)}</div>` +
        `<div class="callout upgrade"><strong>升级条件</strong>${safeText(judgement.upgrade)}</div>` +
        `<div class="callout info"><strong>风险边界</strong>${safeText(riskBoundary)}</div>` +
      `</div></section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>精确谓词 margin</h4>` +
      `<span class="detail-section-note">正值通过，负值未过门槛</span></div>${predicateMarkup}</section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>Selection → Entry drift</h4>` +
      `<span class="detail-section-note">同一 schema-v5 packet · 只读并列</span></div>` +
      `${scorePacketComparisonMarkup(row)}</section>` +
    `<section class="detail-section" data-detail-section="shadow"><div class="detail-section-title"><h4>Shadow 条件</h4></div>` +
      `<div class="callout-list">${canonicalShadowMarkup(row, documentValue)}</div></section>` +
    `<section class="detail-section"><div class="data-gap-panel"><strong>未绘制盈亏曲线：</strong>` +
      `当前 API 没有服务器结算的 payoff 序列。为避免浏览器重算 Inverse payoff，本页不伪造图表或保护腿 Greeks。</div></section>` +
    rawEvidenceMarkup(row.shadow_entry_projection || row);
}

function radarDetailMarkup(row) {
  const state = radarState(row);
  const packet = radarScoreView(row);
  const result = scorePacketResult(packet);
  const oi = packet && packet.oi_diagnostic && typeof packet.oi_diagnostic === 'object'
    ? packet.oi_diagnostic : null;
  const delta = formatInterval(row.delta_interval, value => formatCompactNumber(value, 3));
  return `<div class="detail-title-line"><h3>INVERSE BTC × SHORT VOL</h3>` +
    `${badgeMarkup(state.label, state.tone, 'decision-badge')}</div>` +
    `<p class="detail-subtitle">${safeText(row.instrument_name)} · ${safeText(formatDate(row.expiration_timestamp_ms))}</p>` +
    `<div class="fact-grid">` +
      factMarkup('TTE', formatDurationInterval(row.tte_interval_ms)) +
      factMarkup('执行价', formatDecimal(row.strike_price)) +
      factMarkup('Delta', delta) +
      factMarkup('Score', scoreIntervalText(packet)) +
      factMarkup('Band', result && result.band) +
      factMarkup('Coverage', scoreCoverageText(packet)) +
    `</div>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>V2 score decomposition</h4>` +
      `<span class="detail-section-note">服务器结算 · 非概率、非 Edge</span></div>` +
      `<div class="economics-grid">` +
        economicsCard('Score', scoreIntervalText(packet), `Band ${displayText(result && result.band)}`, state.key === 'HIGH' ? 'positive' : '') +
        economicsCard('Premium evidence', scoreComponentText(packet, 'premium_evidence'), 'A + optional S/T') +
        economicsCard('Risk quality', scoreComponentText(packet, 'risk_quality'), 'D + E') +
        economicsCard('Coverage', scoreCoverageText(packet), '缺失不填中性值') +
      `</div></section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>A / S / T / D / E</h4>` +
      `<span class="detail-section-note">原始输入保留在 packet 证据中</span></div>` +
      `${scoreFactorMarkup(packet)}</section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>Bucket 与 leader</h4></div>` +
      `<div class="callout-list">` +
        `<div class="callout info"><strong>Bucket</strong>${safeText(scoreBucketText(packet))}</div>` +
        `<div class="callout info"><strong>Leader</strong>${safeText(packet && packet.leader_instrument_name)}</div>` +
        `<div class="callout info"><strong>Episode 状态</strong>${safeText(row.bucket_episode_state)} · ` +
          `${safeText(row.confirmation_observation_count)}/${safeText(row.required_confirmation_observation_count)} 次确认</div>` +
        `<div class="callout blocker"><strong>当前阻塞</strong>${safeText(reasonText(row.primary_blocker || row.detector_reason))}</div>` +
        `<div class="callout upgrade"><strong>升级条件</strong>${safeText(reasonText(row.upgrade_condition))}</div>` +
        `<div class="callout invalidation"><strong>失效条件</strong>${safeText(reasonText(row.invalidation_condition))}</div>` +
      `</div></section>` +
    `<section class="detail-section"><div class="detail-section-title"><h4>只读诊断</h4></div>` +
      `<div class="fact-grid">` +
        factMarkup('Unsigned OI / gamma', oi && oi.state) +
        factMarkup('OI concentration', oi && formatPercent(oi.concentration_share)) +
        factMarkup('Dealer gamma sign', oi && oi.dealer_gamma_sign) +
        factMarkup('Legacy V1 1.20 threshold', `${legacyDiagnosticText(packet)} · diagnostic only`) +
      `</div><div class="data-gap-panel">Legacy threshold 与 unsigned OI/gamma 只作诊断；不驱动第二个 V1 detector，不声明 dealer 仓位方向。</div></section>` +
    `<section class="detail-section"><div class="data-gap-panel"><strong>关联边界：</strong>` +
      `本行只信任 packet 内的 bucket、leader 与 fact boundary；不会按合约名拼接 Candidate 或 Shadow 状态。</div></section>` +
    rawEvidenceMarkup(row);
}

function selectedRow(documentValue) {
  const rows = visibleRows(documentValue);
  if (!rows.length) return null;
  if (queueMode === 'structures') {
    return rows.find((row, index) => structureIdentity(row, index) === selectedStructureId) || rows[0];
  }
  return rows.find((row, index) => radarIdentity(row, index) === selectedRadarId) || rows[0];
}

function renderDetail(documentValue) {
  const title = document.getElementById('detail-title');
  const content = document.getElementById('detail-content');
  const openEvidence = content && typeof content.querySelector === 'function'
    ? content.querySelector('[data-evidence-details]') : null;
  if (openEvidence) evidenceExpanded = openEvidence.open;
  const previousScrollTop = content ? content.scrollTop : 0;
  const row = selectedRow(documentValue);
  const shadowJump = document.getElementById('shadow-jump');
  const evidenceToggle = document.getElementById('evidence-toggle');
  if (!row) {
    title.textContent = '当前没有可显示的详情';
    content.innerHTML = `<div class="detail-placeholder">${emptyQueueMarkup(documentValue)}</div>`;
  } else if (queueMode === 'structures') {
    title.textContent = '已结算结构详情';
    content.innerHTML = structureDetailMarkup(row, documentValue);
  } else {
    title.textContent = 'Radar 线索详情';
    content.innerHTML = radarDetailMarkup(row);
  }
  if (shadowJump) shadowJump.hidden = !row || queueMode !== 'structures';
  if (evidenceToggle) {
    evidenceToggle.hidden = !row;
    evidenceToggle.textContent = evidenceExpanded ? '收起证据' : '展开证据';
  }
  if (content) content.scrollTop = previousScrollTop;
  updateResponsiveDetailState();
}

function renderFooter(documentValue) {
  const footer = document.getElementById('footer-summary');
  if (!documentValue) {
    footer.textContent = '规范 Shadow Case — · 等待 Outcome —';
    return;
  }
  const cases = stageCount(documentValue, 'SHADOW_CASE_OPENED');
  const outcomes = stageCount(documentValue, 'SHADOW_CASE_OUTCOME');
  const pending = cases === null || outcomes === null ? null : Math.max(0, Number(cases) - Number(outcomes));
  const research = documentValue.funnel && documentValue.funnel.decision_control_research;
  const controls = research ? research.decision_case_opened_count : null;
  footer.textContent = `规范 Shadow Case ${formatCompactNumber(cases, 0)} · 等待 Outcome ${formatCompactNumber(pending, 0)} · 无交易研究对照 ${formatCompactNumber(controls, 0)}`;
}

function renderWorkspace(documentValue) {
  renderChannelRail(documentValue);
  renderQueue(documentValue);
  renderDetail(documentValue);
  renderFooter(documentValue);
}

function validateDocument(documentValue) {
  if (!documentValue || documentValue.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error('unsupported workbench projection schema');
  }
  if (documentValue.channel_id !== ACTIVE_CHANNEL_ID ||
      !documentValue.product || !documentValue.product.name ||
      !documentValue.product.product_spec_identity || !documentValue.product.native_premium_currency ||
      !documentValue.product.valuation_currency || !documentValue.service || !documentValue.system ||
      !documentValue.radar || !Array.isArray(documentValue.radar.rows) ||
      !documentValue.underwriting || !Array.isArray(documentValue.underwriting.rows) ||
      !documentValue.shadow_entries || !Array.isArray(documentValue.shadow_entries.rows) ||
      !documentValue.positions || !Array.isArray(documentValue.positions.rows) ||
      !documentValue.outcomes || !Array.isArray(documentValue.outcomes.rows) ||
      !documentValue.funnel) {
    throw new Error('invalid workbench projection');
  }
  if (documentValue.product.actual_account_margin_availability !== 'UNKNOWN' ||
      documentValue.product.actual_account_margin_reason !== 'ACCOUNT_MARGIN_UNKNOWN') {
    throw new Error('invalid public-only margin boundary');
  }
}

function render(documentValue) {
  validateDocument(documentValue);
  const focusIdentity = captureFocusIdentity();
  currentDocument = documentValue;
  const connection = document.getElementById('connection');
  connection.hidden = true;
  connection.textContent = '';
  document.body.dataset.workbenchState = 'CURRENT_FETCH';
  renderHeader(documentValue);
  renderWorkspace(documentValue);
  restoreFocusIdentity(focusIdentity);
}

function renderUnavailable() {
  currentDocument = null;
  selectedStructureId = null;
  selectedRadarId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  const connection = document.getElementById('connection');
  connection.hidden = false;
  connection.textContent = '工作台连接中断：旧业务数据已隐藏，当前状态暂不可判断。';
  document.body.dataset.workbenchState = 'UNKNOWN';
  renderHeader(null);
  renderWorkspace(null);
}

function activateChannel(channelId) {
  if (channelId !== 'ALL' && !CHANNELS.some(value => value.id === channelId)) return;
  const focusIdentity = captureFocusIdentity();
  selectedChannelId = channelId;
  selectedStructureId = null;
  selectedRadarId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateQueueMode(mode) {
  if (!['structures', 'radar'].includes(mode)) return;
  const focusIdentity = captureFocusIdentity();
  queueMode = mode;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateFilter(filter) {
  const focusIdentity = captureFocusIdentity();
  if (queueMode === 'structures') structureFilter = filter;
  else radarFilter = filter;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateRow(rowId) {
  if (!currentDocument) return;
  const focusIdentity = captureFocusIdentity();
  if (queueMode === 'structures') selectedStructureId = rowId;
  else selectedRadarId = rowId;
  evidenceExpanded = false;
  renderQueue(currentDocument);
  renderDetail(currentDocument);
  restoreFocusIdentity(focusIdentity);
  openDetail(rowId);
}

function trapDrawerFocus(event) {
  if (event.key !== 'Tab' || !drawerOpen || !isDrawerViewport()) return;
  const panel = document.getElementById('detail-panel');
  if (!panel || typeof panel.querySelectorAll !== 'function') return;
  const focusable = Array.from(panel.querySelectorAll(
    'button:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"])'
  )).filter(element => !element.hidden);
  if (!focusable.length) {
    event.preventDefault();
    panel.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

if (typeof document.addEventListener === 'function') {
  document.addEventListener('click', event => {
    const target = event.target && typeof event.target.closest === 'function' ? event.target : null;
    if (!target) return;
    const themeOption = target.closest('[data-theme-option]');
    if (themeOption) {
      setTheme(themeOption.dataset.themeOption);
      return;
    }
    const channel = target.closest('[data-channel-id]');
    if (channel) {
      activateChannel(channel.dataset.channelId);
      return;
    }
    const mode = target.closest('[data-queue-mode]');
    if (mode) {
      activateQueueMode(mode.dataset.queueMode);
      return;
    }
    const filter = target.closest('[data-queue-filter]');
    if (filter) {
      activateFilter(filter.dataset.queueFilter);
      return;
    }
    const row = target.closest('[data-row-id]');
    if (row) {
      activateRow(row.dataset.rowId);
      return;
    }
    const detailAction = target.closest('[data-detail-action]');
    if (detailAction && detailAction.dataset.detailAction === 'shadow') {
      const section = document.querySelector('[data-detail-section="shadow"]');
      if (section && typeof section.scrollIntoView === 'function') section.scrollIntoView({block: 'start'});
      return;
    }
    if (detailAction && detailAction.dataset.detailAction === 'evidence') {
      const evidence = document.querySelector('[data-evidence-details]');
      if (evidence) {
        evidence.open = !evidence.open;
        evidenceExpanded = evidence.open;
        detailAction.textContent = evidenceExpanded ? '收起证据' : '展开证据';
        if (evidenceExpanded && typeof evidence.scrollIntoView === 'function') evidence.scrollIntoView({block: 'nearest'});
      }
      return;
    }
    if (target.closest('#detail-close') || target.closest('#detail-scrim')) closeDetail();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drawerOpen) {
      event.preventDefault();
      closeDetail();
      return;
    }
    trapDrawerFocus(event);
  });
}

if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  const drawerMedia = window.matchMedia(DRAWER_MEDIA_QUERY);
  if (typeof drawerMedia.addEventListener === 'function') {
    drawerMedia.addEventListener('change', () => {
      const panel = document.getElementById('detail-panel');
      const focusWasInPanel = panel && typeof panel.contains === 'function' && panel.contains(document.activeElement);
      drawerOpen = false;
      updateResponsiveDetailState();
      if (focusWasInPanel) restoreDetailTriggerFocus();
    });
  }
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const response = await fetch('/api/workbench/current', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const documentValue = await response.json();
    validateDocument(documentValue);
    const fetchedAtMs = Date.now();
    const incomingRuntimeIdentity = documentValue.runtime_identity;
    const incomingSequence = Number(documentValue.publication_sequence);
    if (typeof incomingRuntimeIdentity !== 'string' || !incomingRuntimeIdentity ||
        !Number.isSafeInteger(incomingSequence) || incomingSequence < 0) {
      throw new Error('invalid publication identity');
    }
    if (incomingRuntimeIdentity === lastPublicationRuntimeIdentity &&
        lastPublicationSequence !== null && incomingSequence < Number(lastPublicationSequence)) {
      throw new Error('publication sequence regressed');
    }
    if (incomingRuntimeIdentity !== lastPublicationRuntimeIdentity &&
        retiredRuntimeIdentities.has(incomingRuntimeIdentity)) {
      throw new Error('retired runtime identity returned');
    }
    const publicationChanged = incomingRuntimeIdentity !== lastPublicationRuntimeIdentity ||
      incomingSequence !== lastPublicationSequence;
    if (publicationChanged || currentDocument === null) {
      render(documentValue);
    }
    if (lastPublicationRuntimeIdentity && incomingRuntimeIdentity !== lastPublicationRuntimeIdentity) {
      retiredRuntimeIdentities.add(lastPublicationRuntimeIdentity);
    }
    lastSuccessfulFetchAtMs = fetchedAtMs;
    lastPublicationRuntimeIdentity = incomingRuntimeIdentity;
    lastPublicationSequence = incomingSequence;
    if (publicationChanged) lastPublicationChangeAtMs = fetchedAtMs;
  } catch (_error) {
    renderUnavailable();
  } finally {
    refreshInFlight = false;
  }
}

syncThemeControl();
updateResponsiveDetailState();
refresh();
setInterval(refresh, 2000);

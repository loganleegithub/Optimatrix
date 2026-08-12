const SUPPORTED_SCHEMA_VERSION = 7;
const ACTIVE_CHANNEL_ID = 'INVERSE_BTC_SHORT_VOL_V2';
const DRAWER_MEDIA_QUERY = '(max-width: 900px)';
const THEME_STORAGE_KEY = 'optimatrix-workbench-theme';
const ACTIVE_PRODUCT_SPEC_IDENTITY = 'sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131';
const ACTIVE_POLICY_IDENTITIES = Object.freeze({
  radar: 'sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d',
  underwriting: 'sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d',
  position: 'sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe'
});

const CHANNELS = [
  {id: ACTIVE_CHANNEL_ID, label: 'BTC Short Vol', product: 'inverse-btc', strategy: 'SHORT_VOL'},
  {id: 'INVERSE_BTC_LONG_GAMMA', label: 'BTC Long Gamma', product: 'inverse-btc', strategy: 'LONG_GAMMA'},
  {id: 'INVERSE_ETH_SHORT_VOL', label: 'ETH Short Vol', product: 'inverse-eth', strategy: 'SHORT_VOL'},
  {id: 'INVERSE_ETH_LONG_GAMMA', label: 'ETH Long Gamma', product: 'inverse-eth', strategy: 'LONG_GAMMA'}
];

const SHADOW_BOOK_FILTERS = [
  ['ALL', '全部'],
  ['EXIT_REQUIRED', '退出责任'],
  ['MONITORING', '观察中'],
  ['TERMINAL', '已终结'],
  ['UNKNOWN', '待恢复']
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
  SURFACE_RESIDUAL_UNKNOWN: '同类型局部曲面残差不可确认',
  SURFACE_SOURCE_TIME_UNKNOWN: '局部曲面贡献行情缺少来源时间',
  SURFACE_SOURCE_SKEW_EXCEEDED: '局部曲面贡献行情不同步，S 因子不计分',
  TERM_RESIDUAL_UNKNOWN: '相邻期限 ATM 残差不可确认',
  TERM_SOURCE_TIME_UNKNOWN: '相邻期限贡献行情缺少来源时间',
  TERM_SOURCE_SKEW_EXCEEDED: '相邻期限贡献行情不同步，T 因子不计分',
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
  SOURCE_LOSS_OR_KNOWN_FORMULA_INELIGIBILITY: '数据丢失或已知公式变为不合格时失效',
  LEADER_CHANGE: 'Bucket leader 变化',
  SCORE_BAND_CHANGE: 'Score band 变化',
  CORE_UNKNOWN: '核心 Radar 事实变为 UNKNOWN',
  SCOPE_LOSS: '合约离开适用市场范围',
  CLUE_INELIGIBLE: 'TTE 或 Delta 变为仅供审查',
  STOP: 'Runtime 停止',
  RADAR_EPISODE_OR_REVIEW_ENDED: 'Radar Episode 或研究审查已结束',
  POSITION_SLOT_CONSUMED: '同一 Position slot 已被占用',
  ATOMIC_STRUCTURE_NOT_EVALUATED: '原子结构未进入评估',
  STRUCTURE_OR_LIFECYCLE_INELIGIBLE: '结构或合约生命周期已不合格',
  LATEST_ADMISSION_BOUNDARY_REACHED: '已到达最晚 admission 边界',
  REFRESHED_OPPORTUNITY_CHANGED: '严格后续刷新已不再是同一机会',
  REQUEST_RETIRED_BEFORE_REFRESH: '刷新请求在返回前退役',
  RUNTIME_TERMINATED_BEFORE_REFRESH: 'Runtime 在刷新返回前终止',
  OTHER_KNOWN_NO_CONTROL: '其他有界的 KNOWN_NO_CONTROL 原因',
  SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED: '到期/交割边界',
  LATEST_EXIT_BOUNDARY_REACHED: '最晚退出边界',
  PLATFORM_OR_SOURCE_DISCONTINUITY: '平台/行情源不连续',
  MAXIMUM_NET_LOSS_BOUNDARY_REACHED: '最大预计净亏损边界',
  SHORT_LEG_RISK_BOUNDARY_REACHED: '卖腿风险边界',
  PATH_OR_JUMP_RISK_BOUNDARY_REACHED: '路径/跳跃风险边界',
  VOLATILITY_STATE_BOUNDARY_REACHED: '波动率状态边界',
  LIQUIDITY_EXIT_BOUNDARY_REACHED: '流动性退出边界',
  ECONOMIC_EXIT_BOUNDARY_REACHED: '止盈经济边界',
  DUPLICATE_SHADOW_ENTRY_IDENTITY: 'Shadow Entry identity 重复',
  MISSING_POSITION_PROJECTION: '缺少 Position 当前投影',
  DUPLICATE_POSITION_IDENTITY: 'Position 投影重复',
  MISSING_TERMINAL_OUTCOME_PROJECTION: '终端 Position 缺少 Outcome 投影',
  DUPLICATE_OUTCOME_IDENTITY: 'Outcome 投影重复',
  TERMINAL_OUTCOME_NOT_FINAL: '终端 Position 的 Outcome 尚未终结',
  INVALID_ENTRY_COMPONENT_ROLES: '冻结双腿角色不完整',
  INVALID_ENTRY_LEG_ACTIONS: '冻结双腿方向不一致',
  MISSING_FROZEN_STRUCTURE_FIELDS: '冻结结构字段不完整',
  POSITION_ENROLLMENT_KIND_MISMATCH: 'Position 不是正式 Shadow Trade'
};

const postCloseAttemptLabels = {
  NOT_SCHEDULED: '尚未安排',
  SCHEDULED: '已安排',
  TERMINAL: '已终结',
  ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS: '旧尝试状态未知 · 当前 Segment 持续承担退出责任'
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

const scoreFactorLabels = {
  A: 'A · 可执行 IV / RV 丰厚度',
  S: 'S · 可执行 bid-IV − 同类型局部 mark-IV',
  T: 'T · 本到期 ATM mark-IV − 下一到期 ATM mark-IV',
  D: 'D · 历史路径质量',
  E: 'E · 目标规模盘口质量'
};

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
    const detail = factor.unknown_reason
      ? reasonText(factor.unknown_reason)
      : `标准化 ${normalized} · 加权 ${contribution}`;
    return `<div class="predicate-row"><span>${safeText(scoreFactorLabels[factor.name] || factor.name)}</span>` +
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

const latencyState = system => {
  const value = system || {};
  const eventAge = formatDurationMs(value.latest_market_event_age_ms);
  const wireAge = formatDurationMs(value.last_wire_message_age_ms);
  const queueLag = formatDurationMs(value.last_queue_processing_lag_ms);
  const queueDeadline = formatDurationMs(value.queue_lag_deadline_ms);
  const queueActive = value.queue_lag_currentness_active === true;
  return {
    event: `行情事件年龄 ${eventAge}`,
    wire: `收包静默 ${wireAge}`,
    queue: `${queueActive ? '处理队列超时' : '处理队列'} ${queueLag} / 阈值 ${queueDeadline}`,
    note: `处理 ${queueLag} · 行情事件 ${eventAge}`
  };
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

const formatExpiryHeading = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return '到期日未知';
  const expiry = Number(value);
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC', day: '2-digit', month: 'short'
  }).format(new Date(expiry)).toUpperCase();
  const today = new Date();
  const utcToday = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const utcExpiry = Date.UTC(
    new Date(expiry).getUTCFullYear(), new Date(expiry).getUTCMonth(), new Date(expiry).getUTCDate()
  );
  const dayDelta = Math.round((utcExpiry - utcToday) / 86400000);
  const prefix = dayDelta === 0 ? 'TODAY' : dayDelta === 1 ? 'TOMORROW' : '';
  return prefix ? `${prefix} · ${parts}` : parts;
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
const badgeMarkup = (label, tone = 'neutral', extraClass = 'state-badge') =>
  `<span class="${escapeHtml(extraClass)} tone-${escapeHtml(tone)}">${safeText(label)}</span>`;

const factMarkup = (label, value) =>
  `<div class="fact"><span class="fact-label">${escapeHtml(label)}</span>` +
  `<span class="fact-value">${safeText(value)}</span></div>`;

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
    note: latencyState(documentValue.system).note};
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

const shadowResponsibilityIssue = row => (Array.isArray(row.issues) ? row.issues : []).find(value => [
  'MISSING_SHADOW_ENTRY_IDENTITY',
  'DUPLICATE_SHADOW_ENTRY_IDENTITY',
  'MISSING_POSITION_PROJECTION',
  'DUPLICATE_POSITION_IDENTITY',
  'POSITION_ENROLLMENT_KIND_MISMATCH'
].includes(value));

const shadowTerminalIssue = row => {
  if (!row.position || row.position.position_lifecycle_state !== 'TERMINAL') return null;
  return (Array.isArray(row.issues) ? row.issues : []).find(value => [
    'MISSING_TERMINAL_OUTCOME_PROJECTION',
    'DUPLICATE_OUTCOME_IDENTITY',
    'TERMINAL_OUTCOME_NOT_FINAL'
  ].includes(value)) || null;
};

const shadowLifecyclePresentation = row => {
  if (shadowResponsibilityIssue(row)) {
    return {key: 'UNKNOWN', label: '关联待恢复', tone: 'red', priority: 2};
  }
  if (shadowTerminalIssue(row)) {
    return {key: 'UNKNOWN', label: '终端结果待恢复', tone: 'red', priority: 2};
  }
  const lifecycle = row.position && row.position.position_lifecycle_state;
  const outcomeState = row.outcome && row.outcome.state;
  if (lifecycle === 'SETTLEMENT_PENDING') {
    return {key: 'EXIT_REQUIRED', label: '等待交割', tone: 'amber', priority: 0};
  }
  if (lifecycle === 'EXIT_ACQUIRING') {
    return {key: 'EXIT_REQUIRED', label: '退出中', tone: 'amber', priority: 1};
  }
  if (lifecycle === 'MONITORING') {
    return {key: 'MONITORING', label: '观察中', tone: 'green', priority: 3};
  }
  if (lifecycle === 'TERMINAL') {
    if (['TERMINAL_UNKNOWN', 'MATURE_UNKNOWN'].includes(outcomeState)) {
      return {key: 'TERMINAL', label: '终端经济未知', tone: 'red', priority: 4};
    }
    const label = outcomeState === 'MATURE_KNOWN'
      ? '已到期'
      : row.outcome && row.outcome.terminal_method === 'CONTRACT_SETTLEMENT'
        ? '已结算' : '已退出';
    return {key: 'TERMINAL', label, tone: 'green', priority: 4};
  }
  return {key: 'UNKNOWN', label: '状态待恢复', tone: 'red', priority: 2};
};

const shadowBookIdentity = (row, index = 0) =>
  isIdentity(row.shadow_entry_identity) &&
    !(Array.isArray(row.issues) && row.issues.includes('DUPLICATE_SHADOW_ENTRY_IDENTITY'))
    ? row.shadow_entry_identity : row.shadow_book_row_key || `shadow-book-${index}`;

const shadowBookRows = documentValue => {
  const sourceEntries = documentValue && documentValue.shadow_entries &&
    Array.isArray(documentValue.shadow_entries.rows)
    ? documentValue.shadow_entries.rows.filter(value =>
      isIdentity(value.shadow_entry_identity) || value.admission_refresh_terminal_outcome === 'ENTRY_EMITTED')
    : [];
  const positions = documentValue && documentValue.positions && Array.isArray(documentValue.positions.rows)
    ? documentValue.positions.rows : [];
  const outcomes = documentValue && documentValue.outcomes && Array.isArray(documentValue.outcomes.rows)
    ? documentValue.outcomes.rows : [];
  const entryCounts = new Map();
  sourceEntries.forEach(value => {
    if (isIdentity(value.shadow_entry_identity)) {
      entryCounts.set(value.shadow_entry_identity, (entryCounts.get(value.shadow_entry_identity) || 0) + 1);
    }
  });
  return sourceEntries.map((entry, index) => {
    const entryIdentity = entry.shadow_entry_identity;
    const positionMatches = isIdentity(entryIdentity)
      ? positions.filter(value => value.shadow_entry_identity === entryIdentity) : [];
    const outcomeMatches = isIdentity(entryIdentity)
      ? outcomes.filter(value => value.shadow_entry_identity === entryIdentity) : [];
    const legs = Array.isArray(entry.entry_component_legs) ? entry.entry_component_legs : [];
    const shortLegs = legs.filter(value => value.canonical_leg_role === 'SHORT');
    const longLegs = legs.filter(value => value.canonical_leg_role === 'LONG');
    const shortLeg = shortLegs.length === 1 ? shortLegs[0] : null;
    const longLeg = longLegs.length === 1 ? longLegs[0] : null;
    const issues = [];
    if (!isIdentity(entryIdentity)) issues.push('MISSING_SHADOW_ENTRY_IDENTITY');
    else if (entryCounts.get(entryIdentity) !== 1) issues.push('DUPLICATE_SHADOW_ENTRY_IDENTITY');
    if (!shortLeg || !longLeg || legs.length !== 2) issues.push('INVALID_ENTRY_COMPONENT_ROLES');
    else if (shortLeg.action !== 'SELL' || longLeg.action !== 'BUY') {
      issues.push('INVALID_ENTRY_LEG_ACTIONS');
    }
    if (!Number.isFinite(Number(entry.expiry_timestamp_ms)) ||
        !['put', 'call'].includes(entry.option_type) ||
        !Number.isFinite(Number(entry.short_strike_price)) ||
        !Number.isFinite(Number(entry.long_strike_price))) {
      issues.push('MISSING_FROZEN_STRUCTURE_FIELDS');
    }
    if (positionMatches.length === 0) issues.push('MISSING_POSITION_PROJECTION');
    else if (positionMatches.length > 1) issues.push('DUPLICATE_POSITION_IDENTITY');
    const position = positionMatches.length === 1 ? positionMatches[0] : null;
    if (outcomeMatches.length > 1) issues.push('DUPLICATE_OUTCOME_IDENTITY');
    if (position && position.position_lifecycle_state === 'TERMINAL') {
      if (outcomeMatches.length === 0) issues.push('MISSING_TERMINAL_OUTCOME_PROJECTION');
      else if (outcomeMatches.length === 1 &&
          ['PENDING', 'PENDING_OUTCOME'].includes(outcomeMatches[0].state)) {
        issues.push('TERMINAL_OUTCOME_NOT_FINAL');
      }
    }
    if (position && position.enrollment_kind && position.enrollment_kind !== 'ADMITTED_SHADOW_TRADE') {
      issues.push('POSITION_ENROLLMENT_KIND_MISMATCH');
    }
    return {
      queue_row_kind: 'SHADOW_POSITION',
      shadow_book_row_key: `shadow-book-${index}`,
      shadow_entry_identity: entryIdentity,
      expiry_timestamp_ms: entry.expiry_timestamp_ms,
      option_type: entry.option_type,
      short_strike_price: entry.short_strike_price,
      long_strike_price: entry.long_strike_price,
      short_leg: shortLeg,
      long_leg: longLeg,
      entry,
      position,
      outcome: outcomeMatches.length === 1 ? outcomeMatches[0] : null,
      issues
    };
  }).sort((left, right) =>
    Number(left.expiry_timestamp_ms || Number.MAX_SAFE_INTEGER) -
      Number(right.expiry_timestamp_ms || Number.MAX_SAFE_INTEGER) ||
    shadowLifecyclePresentation(left).priority - shadowLifecyclePresentation(right).priority ||
    Number(left.short_strike_price || 0) - Number(right.short_strike_price || 0) ||
    String(left.shadow_entry_identity || '').localeCompare(String(right.shadow_entry_identity || ''))
  );
};

const shadowStructureLabel = row =>
  `${formatStrike(row.short_strike_price)} / ${formatStrike(row.long_strike_price)} ` +
  `${optionTypeText(row.option_type)} Credit Spread`;

const filteredShadowBookRows = documentValue => shadowBookRows(documentValue).filter(row => {
  const presentation = shadowLifecyclePresentation(row);
  const actionMatches = shadowLifecycleFilter === 'ALL' || presentation.key === shadowLifecycleFilter;
  const optionMatches = shadowOptionFilter === 'both' || row.option_type === shadowOptionFilter;
  const expiryMatches = shadowExpiryFilter === 'ALL' ||
    String(row.expiry_timestamp_ms) === shadowExpiryFilter;
  const searchHaystack = [
    row.shadow_entry_identity, row.short_strike_price, row.long_strike_price,
    row.short_leg && row.short_leg.instrument_name, row.long_leg && row.long_leg.instrument_name
  ].filter(value => !isMissing(value)).join(' ').toLowerCase();
  return actionMatches && optionMatches && expiryMatches &&
    (!shadowSearchQuery || searchHaystack.includes(shadowSearchQuery.toLowerCase()));
});

const groupShadowBookRowsByExpiry = rows => {
  const groups = new Map();
  rows.forEach(row => {
    const key = Number.isFinite(Number(row.expiry_timestamp_ms))
      ? String(row.expiry_timestamp_ms) : 'UNKNOWN';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return [...groups.entries()].sort(([left], [right]) =>
    (left === 'UNKNOWN' ? Number.MAX_SAFE_INTEGER : Number(left)) -
    (right === 'UNKNOWN' ? Number.MAX_SAFE_INTEGER : Number(right))
  ).map(([expiry, groupRows]) => ({
    expiry: expiry === 'UNKNOWN' ? null : Number(expiry),
    rows: groupRows
  }));
};

const shadowNextDuty = row => {
  if (shadowResponsibilityIssue(row)) return '恢复规范关联；Entry 继续保留';
  if (shadowTerminalIssue(row)) return '恢复唯一终端 Outcome 投影';
  const lifecycle = row.position.position_lifecycle_state;
  if (lifecycle === 'SETTLEMENT_PENDING') return '等待官方 delivery price';
  if (lifecycle === 'EXIT_ACQUIRING') {
    return row.position.valid_shadow_close_opportunity === true
      ? '登记首组合格报价并形成 Outcome'
      : '继续寻找首组合格退出报价';
  }
  if (lifecycle === 'MONITORING') return '继续监控九条退出谓词';
  if (lifecycle === 'TERMINAL') return '持仓责任已终结';
  return '恢复 Position 当前投影';
};

const shadowTriggerText = row => {
  const responsibilityIssue = shadowResponsibilityIssue(row);
  if (responsibilityIssue) return reasonText(responsibilityIssue);
  const position = row.position;
  if (position.position_lifecycle_state === 'MONITORING') return '尚未触发 CLOSE';
  if (position.primary_exit_rule === 'PLATFORM_OR_SOURCE_DISCONTINUITY') {
    return '历史 CLOSE 已锁存';
  }
  return reasonText(position.primary_exit_rule);
};

const shadowCloseEconomics = row => {
  const outcome = row.outcome;
  if (outcome && ['TERMINAL_UNKNOWN', 'MATURE_UNKNOWN'].includes(outcome.state)) {
    return {kind: 'TERMINAL_UNKNOWN', pnl: null, debit: null};
  }
  if (outcome && !['PENDING', 'PENDING_OUTCOME'].includes(outcome.state) &&
      !isMissing(outcome.public_quote_net_pnl_valuation)) {
    return {kind: 'OUTCOME', pnl: outcome.public_quote_net_pnl_valuation, debit: null};
  }
  const position = row.position;
  if (position && position.valid_shadow_close_opportunity === true &&
      !isMissing(position.projected_shadow_pnl_valuation)) {
    return {
      kind: 'CURRENT_QUOTE',
      pnl: position.projected_shadow_pnl_valuation,
      debit: position.current_close_debit_valuation
    };
  }
  return {kind: 'UNKNOWN', pnl: null, debit: null};
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

const radarReviewConstraint = row => {
  const tteReviewOnly = row.clue_eligible_tte === false;
  const deltaReviewOnly = row.clue_eligible_delta === false;
  if (tteReviewOnly && deltaReviewOnly) return 'TTE/Delta';
  if (tteReviewOnly) return 'TTE';
  if (deltaReviewOnly) return 'Delta';
  return null;
};

const radarConfirmationText = row => {
  const reviewConstraint = radarReviewConstraint(row);
  if (reviewConstraint) return `${reviewConstraint} 仅供审查 · 不进入确认`;
  const count = isMissing(row.confirmation_observation_count)
    ? '—' : row.confirmation_observation_count;
  const required = isMissing(row.required_confirmation_observation_count)
    ? '—' : row.required_confirmation_observation_count;
  return `${displayText(row.bucket_episode_state)} · ${count}/${required} 次确认`;
};

const radarState = row => {
  const raw = scorePacketState(radarScoreView(row));
  const reviewConstraint = radarReviewConstraint(row);
  if (reviewConstraint && raw.key !== 'UNKNOWN') {
    return {...raw, label: `${raw.key} 分数 · ${reviewConstraint} 仅供审查`, tone: 'neutral'};
  }
  const active = row.is_bucket_leader === true &&
    row.clue_eligible_tte === true && row.clue_eligible_delta === true &&
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

const isStrongSignalRow = row => {
  const result = scorePacketResult(radarScoreView(row));
  const episodeState = row.bucket_episode_state;
  const episodeIdentityMatchesState = episodeState === 'CONFIRMING'
    ? isMissing(row.bucket_episode_identity)
    : episodeState === 'ACTIVE' && isIdentity(row.bucket_episode_identity);
  return Boolean(result) && result.band === 'HIGH' &&
    row.is_bucket_leader === true &&
    row.clue_eligible_tte === true && row.clue_eligible_delta === true &&
    row.bucket_episode_leader_instrument_name === row.instrument_name &&
    row.bucket_episode_score_band === 'HIGH' &&
    episodeIdentityMatchesState;
};

const scoreLowerBound = row => {
  const result = scorePacketResult(radarScoreView(row));
  const value = result && result.score && Number(result.score.lower);
  return Number.isFinite(value) ? value : null;
};

const strongSignalRows = documentValue => {
  const rows = documentValue && documentValue.radar && Array.isArray(documentValue.radar.rows)
    ? documentValue.radar.rows : [];
  return [...rows].filter(isStrongSignalRow).sort((left, right) =>
    Number(left.expiration_timestamp_ms || 0) - Number(right.expiration_timestamp_ms || 0) ||
    (scoreLowerBound(right) || 0) - (scoreLowerBound(left) || 0) ||
    Number(left.strike_price || 0) - Number(right.strike_price || 0) ||
    String(left.instrument_name || '').localeCompare(String(right.instrument_name || ''))
  );
};

const filteredStrongSignalRows = documentValue => strongSignalRows(documentValue).filter(row =>
  (optionFilter === 'both' || row.option_type === optionFilter) &&
  (!activeOnly || row.bucket_episode_state === 'ACTIVE')
);

const signalStrikeBounds = documentValue => {
  const rows = documentValue && documentValue.radar && Array.isArray(documentValue.radar.rows)
    ? documentValue.radar.rows : [];
  const strikes = rows
    .filter(row => optionFilter === 'both' || row.option_type === optionFilter)
    .map(row => Number(row.strike_price))
    .filter(Number.isFinite);
  if (!strikes.length) return null;
  const lower = Math.min(...strikes);
  const upper = Math.max(...strikes);
  return {lower, upper: upper === lower ? lower + 1 : upper};
};

const signalXPercent = (strike, bounds) => {
  const numeric = Number(strike);
  if (!bounds || !Number.isFinite(numeric)) return 50;
  const raw = (numeric - bounds.lower) / (bounds.upper - bounds.lower);
  return Math.max(4, Math.min(96, 4 + raw * 92));
};

const groupStrongSignalsByExpiry = rows => {
  const groups = new Map();
  rows.forEach(row => {
    const key = Number(row.expiration_timestamp_ms);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return [...groups.entries()].sort(([left], [right]) => left - right)
    .map(([expiry, groupRows]) => ({expiry, rows: groupRows}));
};

const reasonCountsText = values => {
  if (!values || typeof values !== 'object') return '本运行尚未记录';
  const entries = Object.entries(values)
    .filter(([, count]) => Number.isInteger(count) && count > 0)
    .sort(([leftReason, leftCount], [rightReason, rightCount]) =>
      rightCount - leftCount || leftReason.localeCompare(rightReason));
  if (!entries.length) return '本运行尚未记录';
  return entries.map(([reason, count]) => `${reasonText(reason)} ${count}`).join('；');
};

const radarIdentity = (row, index = 0) => row.active_episode_identity || row.instrument_name || `radar-${index}`;

let lastSuccessfulFetchAtMs = null;
let lastPublicationRuntimeIdentity = null;
let lastPublicationSequence = null;
let lastPublicationChangeAtMs = null;
let refreshInFlight = false;
const retiredRuntimeIdentities = new Set();
let currentDocument = null;
let selectedChannelId = ACTIVE_CHANNEL_ID;
let queueMode = 'radar';
let shadowLifecycleFilter = 'ALL';
let optionFilter = 'both';
let shadowOptionFilter = 'both';
let shadowExpiryFilter = 'ALL';
let shadowSearchQuery = '';
let activeOnly = false;
let selectedShadowId = null;
let selectedRadarId = null;
let drawerOpen = false;
let lastDetailTriggerId = null;
let evidenceExpanded = false;
let productMatrixOpen = false;
let shadowFiltersOpen = false;

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
  for (const key of [
    'channelId', 'queueMode', 'queueFilter', 'optionFilter', 'shadowOptionFilter', 'rowId'
  ]) {
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
  const open = !drawer && queueMode === 'structures' ? true : drawerOpen;
  if (document.body && document.body.classList) {
    document.body.classList.toggle('detail-open', open);
  }
  panel.setAttribute('aria-hidden', open ? 'false' : 'true');
  if (drawer) {
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
  } else {
    panel.setAttribute('role', 'complementary');
    panel.removeAttribute('aria-modal');
  }
  scrim.hidden = !(drawer && open);
  setElementInert('.queue-workspace', drawer && open);
  setElementInert('.topbar', drawer && open);
  setElementInert('.product-toolbar', drawer && open);
  setElementInert('.status-footer', drawer && open);
  setElementInert('#detail-panel', !open);
}

function focusDetailPanel() {
  const close = document.getElementById('detail-close');
  const panel = document.getElementById('detail-panel');
  const target = close || panel;
  if (target && typeof target.focus === 'function') target.focus();
}

function openDetail(rowId) {
  lastDetailTriggerId = rowId;
  drawerOpen = true;
  updateResponsiveDetailState();
  if (isDrawerViewport()) {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(focusDetailPanel);
    else focusDetailPanel();
  }
}

function restoreDetailTriggerFocus() {
  if (typeof document.querySelectorAll !== 'function') return;
  const trigger = Array.from(document.querySelectorAll('[data-row-id]'))
    .find(value => value.dataset.rowId === lastDetailTriggerId);
  if (trigger && typeof trigger.focus === 'function') trigger.focus();
}

function closeDetail() {
  drawerOpen = false;
  updateResponsiveDetailState();
  restoreDetailTriggerFocus();
}

function renderChannelRail(documentValue) {
  const list = document.getElementById('channel-list');
  if (!list) return;
  const currentState = channelSnapshotState(documentValue);
  const cards = CHANNELS.map(channel => {
    const state = channel.id === ACTIVE_CHANNEL_ID ? currentState : roadmapState(channel);
    return `<button type="button" class="channel-card" data-channel-id="${escapeHtml(channel.id)}" ` +
      `aria-pressed="${selectedChannelId === channel.id}">` +
      `<span class="channel-name">${escapeHtml(channel.id)}</span>` +
      `<span class="channel-meta">${badgeMarkup(state.label, state.tone)}` +
      `<span class="channel-note">${safeText(state.note)}</span></span></button>`;
  }).join('');
  list.innerHTML = cards;
}

function setProductMatrixOpen(open) {
  productMatrixOpen = Boolean(open);
  const rail = document.getElementById('channel-rail');
  const toggle = document.getElementById('product-matrix-toggle');
  if (!rail || !toggle) return;
  rail.hidden = !productMatrixOpen;
  rail.inert = !productMatrixOpen;
  toggle.setAttribute('aria-expanded', String(productMatrixOpen));
}

function renderProductToolbar(documentValue) {
  const activeProduct = document.getElementById('active-product');
  const count = document.getElementById('product-matrix-count');
  const radarToolbar = document.getElementById('radar-toolbar');
  const activeToggle = document.getElementById('active-only-toggle');
  if (!activeProduct || !count || !radarToolbar || !activeToggle) return;
  const activeChannel = CHANNELS.find(channel => channel.id === selectedChannelId);
  const state = selectedChannelId === ACTIVE_CHANNEL_ID
    ? channelSnapshotState(documentValue)
    : roadmapState(activeChannel || {id: ''});
  activeProduct.innerHTML = `<strong>${safeText(activeChannel ? activeChannel.id : ACTIVE_CHANNEL_ID)}</strong>` +
    badgeMarkup(state.label, state.tone);
  count.textContent = '1 / 4';
  radarToolbar.hidden = false;
  radarToolbar.dataset.surface = queueMode;
  activeToggle.setAttribute('aria-pressed', String(activeOnly));
  activeToggle.hidden = queueMode !== 'radar';
  const shadowFilterToggle = document.getElementById('shadow-filter-toggle');
  if (shadowFilterToggle) {
    shadowFilterToggle.hidden = queueMode !== 'structures';
    shadowFilterToggle.setAttribute('aria-expanded', String(shadowFiltersOpen));
  }
  if (document.body) document.body.dataset.surface = queueMode;
  if (typeof document.querySelectorAll === 'function') {
    document.querySelectorAll('[data-option-filter]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.optionFilter === optionFilter));
    });
    document.querySelectorAll('[data-shadow-option-filter]').forEach(button => {
      button.setAttribute(
        'aria-pressed', String(button.dataset.shadowOptionFilter === shadowOptionFilter)
      );
    });
    document.querySelectorAll('[data-queue-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.queueMode === queueMode));
    });
  }
  setProductMatrixOpen(productMatrixOpen);
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
  const wireAge = document.getElementById('wire-age');
  const queueLag = document.getElementById('queue-lag');
  const blocker = document.getElementById('runtime-blocker');
  if (!asOf || !runtime || !status || !stateLabel || !stateDetail || !servicePhase ||
      !dataCurrentness || !dataDelay || !wireAge || !queueLag || !blocker) return;
  const state = runtimeStatusState(documentValue);
  const service = documentValue && documentValue.service;
  const system = documentValue && documentValue.system;
  const latency = latencyState(system);
  status.dataset.state = state.key;
  stateLabel.textContent = state.label;
  stateDetail.textContent = state.key === 'healthy' ? '决策数据当前可用' : state.detail;
  servicePhase.textContent = `服务 ${service ? displayText(service.phase) : '—'}`;
  dataCurrentness.textContent = `行情 ${service ? displayText(service.data_state) : '—'}`;
  dataDelay.textContent = latency.event;
  wireAge.textContent = latency.wire;
  queueLag.textContent = latency.queue;
  asOf.textContent = `行情事件时间 ${system ? formatTimestamp(system.latest_market_event_timestamp_ms) : '—'}`;
  runtime.textContent = `runtime ${documentValue ? shortIdentity(documentValue.runtime_identity) : '—'}`;
  blocker.textContent = state.blocker;
}

const selectedChannelCanUseCurrentSnapshot = documentValue =>
  selectedChannelId === ACTIVE_CHANNEL_ID &&
  channelSnapshotState(documentValue).code === 'CONNECTED';

function visibleRows(documentValue) {
  if (!selectedChannelCanUseCurrentSnapshot(documentValue)) return [];
  if (queueMode === 'structures') return filteredShadowBookRows(documentValue);
  return filteredStrongSignalRows(documentValue);
}

function totalRows(documentValue) {
  if (!selectedChannelCanUseCurrentSnapshot(documentValue)) return [];
  return queueMode === 'structures'
    ? shadowBookRows(documentValue)
    : documentValue.radar.rows;
}

function renderShadowFilters(documentValue) {
  const filters = SHADOW_BOOK_FILTERS;
  document.getElementById('queue-filters').innerHTML = filters.map(([value, label]) =>
    `<button type="button" data-queue-filter="${escapeHtml(value)}" ` +
    `aria-pressed="${shadowLifecycleFilter === value}">${escapeHtml(label)}</button>`
  ).join('');
  const expirySelect = document.getElementById('shadow-expiry-filter');
  const expiryValues = [...new Set(shadowBookRows(documentValue)
    .map(row => row.expiry_timestamp_ms)
    .filter(value => Number.isFinite(Number(value))))].sort((left, right) => Number(left) - Number(right));
  if (expirySelect) {
    expirySelect.innerHTML = '<option value="ALL">全部</option>' + expiryValues.map(value =>
      `<option value="${escapeHtml(value)}">${safeText(formatDate(value))}</option>`
    ).join('');
    expirySelect.value = expiryValues.some(value => String(value) === shadowExpiryFilter)
      ? shadowExpiryFilter : 'ALL';
    if (expirySelect.value === 'ALL') shadowExpiryFilter = 'ALL';
  }
  const search = document.getElementById('shadow-search');
  if (search && search.value !== shadowSearchQuery) search.value = shadowSearchQuery;
  if (typeof document.querySelectorAll === 'function') {
    document.querySelectorAll('[data-shadow-option-filter]').forEach(button => {
      button.setAttribute(
        'aria-pressed', String(button.dataset.shadowOptionFilter === shadowOptionFilter)
      );
    });
    document.querySelectorAll('[data-queue-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.queueMode === queueMode));
    });
  }
  const popover = document.getElementById('shadow-filter-popover');
  const toggle = document.getElementById('shadow-filter-toggle');
  if (popover) popover.hidden = !shadowFiltersOpen;
  if (toggle) toggle.setAttribute('aria-expanded', String(shadowFiltersOpen));
}

function renderQueueHead() {
  const labels = [
    ['结构（简称）', '合约结构（Short → Long）'],
    ['方向', ''],
    ['数量', '(BTC)'],
    ['现价 vs 短行权', '距离 / 占比'],
    ['TTE', '距离到期'],
    ['当前触发', 'Entry Delta Bucket'],
    ['状态', ''],
    ['关闭成本 / P&L', '当前公共报价（仅参考）'],
    ['下一步行动', '']
  ];
  document.getElementById('queue-head').innerHTML = labels.map(([primary, secondary]) =>
    `<span role="columnheader"><strong>${escapeHtml(primary)}</strong>` +
    `${secondary ? `<small>${escapeHtml(secondary)}</small>` : ''}</span>`
  ).join('');
}

const shadowCurrentIndex = documentValue => documentValue && documentValue.system
  ? documentValue.system.current_index_price_valuation : null;

const shadowStrikeDistance = (row, documentValue) => {
  const index = Number(shadowCurrentIndex(documentValue));
  const strike = Number(row.short_strike_price);
  if (!Number.isFinite(index) || !Number.isFinite(strike) || index === 0) {
    return {primary: '暂不可得', secondary: '当前指数不可得', tone: 'muted'};
  }
  const distance = row.option_type === 'put' ? index - strike : strike - index;
  const percent = distance / index * 100;
  const signed = distance >= 0 ? '+' : '';
  return {
    primary: `${signed}${formatCompactNumber(distance, 0)} / ${signed}${formatCompactNumber(percent, 2)}%`,
    secondary: `现价 ${formatCompactNumber(index, 0)}`,
    tone: distance < 0 ? 'negative' : distance / index < 0.01 ? 'warning' : 'positive'
  };
};

const shadowDistanceToThresholdText = (row, strikeDistance) => {
  if (strikeDistance.primary === '暂不可得') return '暂不可得';
  const strike = formatStrike(row.short_strike_price);
  return `${row.option_type === 'put' ? '≤' : '≥'} ${strike} （${strikeDistance.primary}）`;
};

const shadowEntryScorePacket = row => row.entry.entry_refresh_score_packet ||
  row.entry.selection_score_packet;

const shadowEntryDeltaBucket = row => {
  const packet = shadowEntryScorePacket(row);
  return packet && packet.bucket_key ? displayText(packet.bucket_key.delta_bucket) : '—';
};

const shadowTteText = row => formatDurationInterval(
  row.position && row.position.expiry_countdown_interval_ms
);

const shadowBookTriggerText = row => shadowTriggerText(row) === '历史 CLOSE 已锁存'
  ? 'CLOSE 已锁存' : shadowTriggerText(row);

const shadowBookDutyText = row => {
  const key = shadowLifecyclePresentation(row).key;
  if (key === 'EXIT_REQUIRED') return '退出中 · 等待报价';
  if (key === 'SETTLEMENT_PENDING') return '等待官方交割';
  if (key === 'MONITORING') return '监控 · 观察退出触发';
  if (key === 'TERMINAL') return '持仓责任已终结';
  return shadowNextDuty(row);
};

const shadowStateTone = state => state.tone === 'green' ? 'positive'
  : state.tone === 'amber' ? 'warning' : state.tone === 'red' ? 'negative' : 'muted';

function shadowBookRowMarkup(row, index, documentValue = currentDocument) {
  const id = shadowBookIdentity(row, index);
  const state = shadowLifecyclePresentation(row);
  const economics = shadowCloseEconomics(row);
  const quality = row.position && row.position.observation_quality || row.entry.observation_quality;
  const valuationUnit = documentValue.product.valuation_currency;
  const strikeDistance = shadowStrikeDistance(row, documentValue);
  const economicPrimary = economics.kind === 'UNKNOWN'
    ? '尚不可得'
    : economics.kind === 'TERMINAL_UNKNOWN'
      ? '终端未知'
      : `${Number(economics.pnl) >= 0 ? '+' : ''}${formatMoney(economics.pnl)} ${valuationUnit}`;
  const triggerSecondary = row.position && row.position.position_lifecycle_state === 'TERMINAL'
    ? '责任已终结'
    : row.position && row.position.primary_exit_rule === 'PLATFORM_OR_SOURCE_DISCONTINUITY'
      ? '持仓责任持续'
      : row.position && row.position.close_quote_state
        ? `报价 ${displayText(row.position.close_quote_state)}` : '—';
  const lifecycleTone = shadowStateTone(state);
  const pnlTone = economics.kind === 'UNKNOWN' || economics.kind === 'TERMINAL_UNKNOWN'
    ? 'muted' : Number(economics.pnl) >= 0 ? 'positive' : 'negative';
  return `<button type="button" class="queue-row shadow-book-row tone-row-${escapeHtml(lifecycleTone)}" role="row" ` +
    `data-row-id="${escapeHtml(id)}" aria-pressed="${selectedShadowId === id}">` +
    `<span role="cell"><span class="cell-primary">${safeText(shadowStructureLabel(row))}</span>` +
    `<span class="cell-secondary">${safeText(row.short_leg && row.short_leg.instrument_name)} → ${safeText(row.long_leg && row.long_leg.instrument_name)}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(optionTypeText(row.option_type))}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(formatDecimal(row.entry.target_quantity_btc))}</span>` +
    `<span class="cell-secondary">BTC</span></span>` +
    `<span role="cell"><span class="cell-value cell-${escapeHtml(strikeDistance.tone)}">${safeText(strikeDistance.primary)}</span>` +
    `<span class="cell-secondary">${safeText(strikeDistance.secondary)}</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(shadowTteText(row))}</span>` +
    `<span class="cell-secondary">到期</span></span>` +
    `<span role="cell"><span class="cell-primary">${safeText(shadowBookTriggerText(row))}</span>` +
    `<span class="cell-secondary">${safeText(shadowEntryDeltaBucket(row))}</span></span>` +
    `<span role="cell"><span class="cell-value cell-${escapeHtml(lifecycleTone)}">${safeText(state.label)}</span>` +
    `<span class="cell-secondary">${safeText(quality === 'GAPPED' ? '观察有缺口' : quality === 'CONTINUOUS' ? '连续观察' : '观察未知')}</span></span>` +
    `<span role="cell"><span class="cell-value cell-${escapeHtml(pnlTone)}">${safeText(economics.kind === 'CURRENT_QUOTE' ? `${formatMoney(economics.debit)} ${valuationUnit}` : economics.kind === 'OUTCOME' ? 'Outcome' : '等待可执行报价')}</span>` +
    `<span class="cell-secondary ${pnlTone === 'negative' ? 'cell-negative' : pnlTone === 'positive' ? 'cell-positive' : ''}">${safeText(economicPrimary)}</span></span>` +
    `<span role="cell"><span class="cell-primary shadow-duty">${safeText(shadowBookDutyText(row))}</span>` +
    `<span class="cell-secondary">${safeText(triggerSecondary)}</span></span></button>`;
}

const shadowExpiryHeadingMarkup = group => {
  const exitCount = group.rows.filter(row =>
    shadowLifecyclePresentation(row).key === 'EXIT_REQUIRED').length;
  const monitoringCount = group.rows.filter(row =>
    shadowLifecyclePresentation(row).key === 'MONITORING').length;
  const index = shadowCurrentIndex(currentDocument);
  const shortStrikes = group.rows.map(row => Number(row.short_strike_price)).filter(Number.isFinite);
  const lower = shortStrikes.length ? Math.min(...shortStrikes) : null;
  const upper = shortStrikes.length ? Math.max(...shortStrikes) : null;
  const nearest = Number.isFinite(Number(index)) && shortStrikes.length
    ? Math.min(...shortStrikes.map(value => Math.abs(value - Number(index)))) : null;
  const nearestText = nearest === null
    ? '短腿风险距离暂不可得'
    : `最近短腿 ${formatCompactNumber(nearest, 0)} USD`;
  const concentration = lower === null ? '短腿集中区间暂不可得'
    : `短腿集中 ${formatStrike(lower)}${upper !== lower ? `–${formatStrike(upper)}` : ''}`;
  const countdown = group.rows[0] && group.rows[0].position
    ? formatDurationInterval(group.rows[0].position.hard_close_countdown_interval_ms) : '—';
  return `<div class="shadow-expiry-heading" role="row"><span role="cell">` +
      `<strong>${safeText(formatExpiryHeading(group.expiry))}</strong>` +
      `<small>${group.rows.length} 结构</small>` +
      `<small>${safeText(nearestText)} · ${safeText(countdown)}</small>` +
      `<small>监控 ${monitoringCount} · 退出中 ${exitCount}</small>` +
      `<small>${safeText(concentration)}</small>` +
    `</span></div>`;
};

const shadowExpiryGroupMarkup = (group, groupIndex, includeHeading = true) =>
  `<section class="shadow-expiry-group" role="rowgroup" aria-label="${safeText(formatDate(group.expiry))} 到期">` +
    (includeHeading ? shadowExpiryHeadingMarkup(group) : '') +
    group.rows.map((row, index) => shadowBookRowMarkup(row, groupIndex * 1000 + index)).join('') +
  `</section>`;

const signalLaneLayout = (rows, bounds) => {
  const positioned = rows.map((row, index) => ({
    index,
    x: signalXPercent(row.strike_price, bounds),
    instrumentName: String(row.instrument_name || '')
  })).sort((left, right) => left.x - right.x ||
    left.instrumentName.localeCompare(right.instrumentName));
  const lastXByTier = [];
  const tierByIndex = new Map();
  positioned.forEach(item => {
    let tier = lastXByTier.findIndex(lastX => item.x - lastX >= 8.5);
    if (tier < 0) tier = lastXByTier.length;
    lastXByTier[tier] = item.x;
    tierByIndex.set(item.index, tier);
  });
  const tierCount = Math.max(1, lastXByTier.length);
  const chartHeight = 150 + (tierCount - 1) * 86;
  return {tierByIndex, tierCount, chartHeight, baselineY: chartHeight - 20};
};

const signalMarkerMarkup = (row, index, bounds, tier, baselineY) => {
  const id = radarIdentity(row, index);
  const score = scoreLowerBound(row);
  const state = row.bucket_episode_state;
  const optionClass = row.option_type === 'call' ? 'call' : 'put';
  const stateClass = state === 'ACTIVE' ? 'active' : 'confirming';
  const x = signalXPercent(row.strike_price, bounds);
  const cardY = baselineY - 96 - tier * 86;
  const confirmation = `${displayText(row.confirmation_observation_count)}/${displayText(row.required_confirmation_observation_count)}`;
  return `<line class="signal-stem ${optionClass}" x1="${x}%" x2="${x}%" ` +
    `y1="${cardY + 80}" y2="${baselineY - 10}"></line>` +
    `<circle class="signal-ring ${optionClass} ${stateClass}" cx="${x}%" cy="${baselineY}" r="9"></circle>` +
    `<foreignObject class="signal-marker-slot" x="${x}%" y="${cardY}" ` +
    `width="80" height="86" transform="translate(-40 0)">` +
    `<button xmlns="http://www.w3.org/1999/xhtml" type="button" ` +
    `class="signal-marker ${optionClass} ${stateClass}" role="listitem" ` +
    `data-row-id="${escapeHtml(id)}" aria-pressed="${selectedRadarId === id}" ` +
    `aria-label="${safeText(`${row.instrument_name}，V2 Score ${score === null ? '未知' : formatCompactNumber(score, 1)}，${state}`)}" ` +
    `>` +
      `<span class="signal-leader-mark" aria-hidden="true"></span>` +
      `<span class="signal-card"><small>${safeText(formatCompactNumber(row.strike_price, 0))}</small>` +
      `<strong>${safeText(score === null ? '—' : formatCompactNumber(score, 1))}</strong>` +
      `<em>${safeText(state === 'ACTIVE' ? 'ACTIVE' : confirmation)}</em></span>` +
    `</button></foreignObject>`;
};

const signalLaneChartMarkup = (group, bounds) => {
  const layout = signalLaneLayout(group.rows, bounds);
  const markers = group.rows.map((row, index) => signalMarkerMarkup(
    row, index, bounds, layout.tierByIndex.get(index), layout.baselineY
  )).join('');
  const ticks = group.scopeRows.map(row => {
    const x = signalXPercent(row.strike_price, bounds);
    return `<line class="scope-tick" x1="${x}%" x2="${x}%" ` +
      `y1="${layout.baselineY - 4}" y2="${layout.baselineY + 4}"></line>`;
  }).join('');
  return `<svg class="signal-lane-chart" width="100%" height="${layout.chartHeight}" focusable="false">` +
    `<line class="signal-track-line" x1="4%" x2="96%" ` +
    `y1="${layout.baselineY}" y2="${layout.baselineY}"></line>` +
    `${ticks}${markers}</svg>`;
};

const signalAxisMarkup = bounds => {
  if (!bounds) return '';
  const labels = Array.from({length: 7}, (_, index) =>
    bounds.lower + (bounds.upper - bounds.lower) * index / 6);
  return `<div class="signal-axis" aria-hidden="true">${labels.map(value =>
    `<span>${safeText(formatCompactNumber(value, 0))}</span>`).join('')}</div>`;
};

function renderRadarMap(documentValue, rows) {
  const map = document.getElementById('radar-map');
  if (!map) return;
  if (!selectedChannelCanUseCurrentSnapshot(documentValue) || !rows.length) {
    map.innerHTML = `<div class="signal-map-empty">${emptyQueueMarkup(documentValue)}</div>`;
    return;
  }
  const bounds = signalStrikeBounds(documentValue);
  const allRadarRows = documentValue.radar.rows;
  const scopeGroups = new Map();
  allRadarRows.filter(row =>
    (optionFilter === 'both' || row.option_type === optionFilter) &&
    Number.isFinite(Number(row.expiration_timestamp_ms)) &&
    Number.isFinite(Number(row.strike_price))
  ).forEach(row => {
    const expiry = Number(row.expiration_timestamp_ms);
    if (!scopeGroups.has(expiry)) scopeGroups.set(expiry, []);
    scopeGroups.get(expiry).push(row);
  });
  const groups = [...scopeGroups.entries()].sort(([left], [right]) => left - right)
    .map(([expiry, scopeRows]) => ({
      expiry,
      scopeRows,
      rows: rows.filter(row => Number(row.expiration_timestamp_ms) === expiry)
    }));
  const selected = rows.find((row, index) => radarIdentity(row, index) === selectedRadarId);
  const lanes = groups.map(group => {
    const isCurrent = selected && Number(selected.expiration_timestamp_ms) === group.expiry;
    return `<section class="signal-lane" aria-current="${isCurrent ? 'true' : 'false'}">` +
      `<div class="signal-lane-label"><strong>${safeText(formatDate(group.expiry))}</strong>` +
      `<span>${safeText(formatDurationInterval(group.scopeRows[0].tte_interval_ms))}</span></div>` +
      `<div class="signal-lane-track">${signalLaneChartMarkup(group, bounds)}</div></section>`;
  }).join('');
  map.innerHTML = lanes + signalAxisMarkup(bounds);
}

function emptyQueueMarkup(documentValue) {
  if (selectedChannelId !== ACTIVE_CHANNEL_ID) {
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
  const rows = visibleRows(documentValue);
  const total = totalRows(documentValue);
  const allStrong = selectedChannelCanUseCurrentSnapshot(documentValue)
    ? strongSignalRows(documentValue) : [];
  const body = document.getElementById('queue-body');
  const mapView = document.getElementById('radar-map-view');
  const structureView = document.getElementById('structure-queue-view');
  const title = document.getElementById('queue-title');
  const kicker = document.getElementById('queue-kicker');
  const context = document.getElementById('queue-context');
  const status = document.getElementById('queue-status');
  const structureStatus = document.getElementById('structure-status');
  const roadmapOnly = selectedChannelId !== ACTIVE_CHANNEL_ID;
  const snapshotState = channelSnapshotState(documentValue);
  mapView.hidden = queueMode !== 'radar';
  structureView.hidden = queueMode !== 'structures';
  if (queueMode === 'structures') {
    renderShadowFilters(documentValue);
    renderQueueHead();
    kicker.textContent = '当前 Shadow';
    title.textContent = '到期风险持仓簿';
    context.textContent = '只看正式 Shadow Entry 的当前风险、退出责任与终端结果；Control 留在离线研究面。';
    if (roadmapOnly) structureStatus.textContent = '尚未接入 · 无独立队列快照';
    else if (snapshotState.code !== 'CONNECTED') structureStatus.textContent = `${snapshotState.label} · 不报告业务零值`;
    else {
      const exitRequired = total.filter(row =>
        shadowLifecyclePresentation(row).key === 'EXIT_REQUIRED').length;
      const monitoring = total.filter(row =>
        shadowLifecyclePresentation(row).key === 'MONITORING').length;
      const terminal = total.filter(row =>
        shadowLifecyclePresentation(row).key === 'TERMINAL').length;
      structureStatus.textContent = `显示 ${rows.length} / ${total.length} 个正式 Shadow 持仓 · ` +
        `${exitRequired} 个退出责任 · ${monitoring} 个观察中 · ${terminal} 个已终结`;
      const footerCount = document.getElementById('shadow-footer-count');
      if (footerCount) footerCount.textContent = `显示 1–${rows.length} / ${total.length}`;
    }
    if (!rows.length) {
      const leadingExpiry = document.getElementById('shadow-leading-expiry');
      if (leadingExpiry) leadingExpiry.innerHTML = '';
      body.innerHTML = emptyQueueMarkup(documentValue);
    } else {
      const ids = rows.map(shadowBookIdentity);
      const selectionChanged = !selectedShadowId || !ids.includes(selectedShadowId);
      if (selectionChanged) selectedShadowId = ids[0];
      if (selectedShadowId && !isDrawerViewport()) drawerOpen = true;
      const groups = groupShadowBookRowsByExpiry(rows);
      const leadingExpiry = document.getElementById('shadow-leading-expiry');
      if (leadingExpiry) leadingExpiry.innerHTML = shadowExpiryHeadingMarkup(groups[0]);
      body.innerHTML = groups.map((group, index) =>
        shadowExpiryGroupMarkup(group, index, index !== 0)).join('');
    }
  } else {
    kicker.textContent = '当前 Radar';
    title.textContent = '强信号 Strike 地图';
    context.textContent = '只提升服务器已确认的 HIGH bucket leader；不是交易指令，也不是 Shadow Entry。';
    if (roadmapOnly) status.textContent = '尚未接入 · 无独立 Radar 快照';
    else if (snapshotState.code !== 'CONNECTED') status.textContent = `${snapshotState.label} · 不报告业务零值`;
    else status.textContent = `${rows.length} 个当前可见 / ${allStrong.length} 个强信号 / ${total.length} 个扫描合约`;
    const ids = rows.map(radarIdentity);
    const selectionChanged = !selectedRadarId || !ids.includes(selectedRadarId);
    if (selectionChanged) selectedRadarId = ids[0] || null;
    if (selectionChanged && selectedRadarId && !isDrawerViewport()) drawerOpen = true;
    renderRadarMap(documentValue, rows);
  }
  if (table) table.scrollTop = previousScrollTop;
}

const postCloseAttemptText = value => isMissing(value)
  ? '—'
  : (postCloseAttemptLabels[value] || displayText(value));

function shadowDetailMarkup(row, documentValue) {
  const state = shadowLifecyclePresentation(row);
  const nativeUnit = documentValue.product.native_premium_currency;
  const valuationUnit = documentValue.product.valuation_currency;
  const position = row.position || {};
  const outcome = row.outcome || {state: 'PENDING'};
  const economics = shadowCloseEconomics(row);
  const terminalIssue = shadowTerminalIssue(row);
  const quality = position.observation_quality || row.entry.observation_quality;
  const currentIndex = shadowCurrentIndex(documentValue);
  const strikeDistance = shadowStrikeDistance(row, documentValue);
  const thresholdText = shadowDistanceToThresholdText(row, strikeDistance);
  const scorePacket = shadowEntryScorePacket(row);
  const scoreResult = scorePacketResult(scorePacket);
  const premiumStrength = scoreComponentText(scorePacket, 'premium_evidence');
  const riskQuality = scoreComponentText(scorePacket, 'risk_quality');
  const netCredit = row.entry.net_entry_credit_valuation;
  const maxReward = netCredit;
  const maxRisk = row.entry.entry_fee_reserved_max_loss_valuation;
  const riskReward = !isMissing(netCredit) && !isMissing(maxRisk) && Number(netCredit) > 0
    ? `${formatCompactNumber(Number(maxRisk) / Number(netCredit), 1)}×`
    : '—';
  const closeDebitText = economics.kind === 'CURRENT_QUOTE'
    ? `${formatMoney(economics.debit)} ${valuationUnit}` : '等待可执行报价';
  const pnlText = ['CURRENT_QUOTE', 'OUTCOME'].includes(economics.kind)
    ? `${Number(economics.pnl) >= 0 ? '+' : ''}${formatMoney(economics.pnl)} ${valuationUnit}`
    : economics.kind === 'TERMINAL_UNKNOWN' ? '终端未知' : '尚不可得';
  const terminalText = terminalIssue
    ? '终端 Outcome 投影待恢复；不推断退出方式或经济结果'
    : ['PENDING', 'PENDING_OUTCOME'].includes(outcome.state)
      ? position.position_lifecycle_state === 'SETTLEMENT_PENDING'
        ? '等待官方 delivery price；不可得时才形成 TERMINAL_UNKNOWN'
        : '等待首组合格退出报价；到期未退出则进入官方交割'
    : `${displayText(outcome.state)} · ${displayText(outcome.terminal_method)}`;
  const responsibilityIssue = shadowResponsibilityIssue(row);
  const issueMarkup = responsibilityIssue
    ? `<div class="callout blocker"><strong>责任关联待恢复</strong>${safeText(row.issues.map(reasonText).join('；'))}。Entry 不删除，浏览器拒绝补推 Position 或 Outcome。</div>`
    : terminalIssue
      ? `<div class="callout blocker"><strong>终端结果待恢复</strong>${safeText(row.issues.map(reasonText).join('；'))}。Position 终端态保留，浏览器拒绝推断退出方式或经济结果。</div>`
    : row.issues.length
      ? `<div class="callout info"><strong>部分展示事实待恢复</strong>${safeText(row.issues.map(reasonText).join('；'))}。当前 Position 责任仍按服务器投影显示；浏览器不补推结构或 Outcome。</div>`
      : '';
  return `<div class="detail-title-line"><h3>${safeText(shadowStructureLabel(row))}</h3>` +
    `${badgeMarkup(state.label, state.tone, 'decision-badge')}</div>` +
    `<p class="detail-subtitle">${safeText(row.short_leg && row.short_leg.instrument_name)} → ` +
      `${safeText(row.long_leg && row.long_leg.instrument_name)}</p>` +
    `<p class="detail-meta">数量 ${safeText(formatDecimal(row.entry.target_quantity_btc))} ${safeText(nativeUnit)} · ` +
      `方向 ${safeText(optionTypeText(row.option_type))} · Entry Score ${safeText(scoreIntervalText(scorePacket))}</p>` +
    `${issueMarkup}` +
    `<section class="shadow-trader-section numbered-section"><h4>1. 结构经济</h4>` +
      `<div class="shadow-key-values">` +
        `<div><span>净入场信用（估值）</span><strong>${safeText(isMissing(netCredit) ? '—' : `${formatMoney(netCredit)} ${valuationUnit}`)}</strong></div>` +
        `<div><span>最大收益（净信用）</span><strong>${safeText(isMissing(maxReward) ? '—' : `${formatMoney(maxReward)} ${valuationUnit}`)}</strong></div>` +
        `<div><span>最大亏损（含入场费预留）</span><strong>${safeText(isMissing(maxRisk) ? '—' : `${formatMoney(maxRisk)} ${valuationUnit}`)}</strong></div>` +
        `<div><span>风险 / 信用</span><strong>${safeText(riskReward)}</strong></div>` +
      `</div></section>` +
    `<section class="shadow-trader-section numbered-section"><h4>2. 风险现状</h4>` +
      `<div class="shadow-key-values">` +
        `<div><span>当前指数</span><strong>${safeText(isMissing(currentIndex) ? '暂不可得' : `${formatMoney(currentIndex)} ${valuationUnit}`)}</strong></div>` +
        `<div><span>相对短行权</span><strong class="cell-${escapeHtml(strikeDistance.tone)}">${safeText(strikeDistance.primary)}</strong></div>` +
        `<div><span>当前触发价</span><strong>${safeText(thresholdText)}</strong></div>` +
        `<div><span>当前触发</span><strong>${safeText(shadowTriggerText(row))}</strong></div>` +
        `<div><span>Entry Delta Bucket</span><strong>${safeText(shadowEntryDeltaBucket(row))}</strong></div>` +
        `<div><span>状态</span><strong class="cell-${escapeHtml(shadowStateTone(state))}">${safeText(state.label)}</strong></div>` +
      `</div>` +
      `<div class="signal-metrics shadow-entry-metrics">` +
        `<div class="signal-metric"><div class="signal-metric-head"><span>Entry Premium Strength (A/S/T)</span><strong>${safeText(premiumStrength)}</strong></div>` +
          `<progress class="signal-meter" max="100" value="${scoreMetricWidth(scoreResult, 'premium_evidence')}" aria-label="Entry Premium Strength"></progress></div>` +
        `<div class="signal-metric risk"><div class="signal-metric-head"><span>Entry Risk Quality (D/E)</span><strong>${safeText(riskQuality)}</strong></div>` +
          `<progress class="signal-meter" max="100" value="${scoreMetricWidth(scoreResult, 'risk_quality')}" aria-label="Entry Risk Quality"></progress></div>` +
      `</div></section>` +
    `<section class="shadow-trader-section numbered-section"><h4>3. 关闭职责</h4>` +
      `<div class="shadow-key-values">` +
        `<div><span>最佳可证明路径</span><strong>${safeText(position.position_lifecycle_state === 'SETTLEMENT_PENDING' ? '官方交割' : '首组合格双腿公共报价')}</strong></div>` +
        `<div><span>关闭成本（估值）</span><strong>${safeText(closeDebitText)}</strong></div>` +
        `<div><span>Shadow P&L（仅参考）</span><strong>${safeText(pnlText)}</strong></div>` +
        `<div><span>下一步行动</span><strong>${safeText(shadowNextDuty(row))}</strong></div>` +
      `</div></section>` +
    `<section class="shadow-trader-section numbered-section"><h4>4. 截止与时限</h4>` +
      `<div class="shadow-key-values">` +
        `<div><span>hard-close 边界</span><strong>${safeText(formatTimestamp(position.hard_close_boundary_ms))}</strong></div>` +
        `<div><span>距离 hard-close</span><strong>${safeText(formatDurationInterval(position.hard_close_countdown_interval_ms))}</strong></div>` +
        `<div><span>到期边界</span><strong>${safeText(formatTimestamp(row.expiry_timestamp_ms))}</strong></div>` +
      `</div></section>` +
    `<section class="shadow-trader-section numbered-section"><h4>5. 终端预期</h4>` +
      `<p class="shadow-terminal-text">${safeText(terminalText)}</p></section>` +
    `<details class="signal-evidence shadow-research-evidence" data-evidence-details${evidenceExpanded ? ' open' : ''}>` +
      `<summary>完整责任链与研究证据</summary><div class="signal-evidence-body">` +
        `<div class="fact-grid">` +
          factMarkup('Shadow Entry', shortIdentity(row.shadow_entry_identity)) +
          factMarkup(`入场净信用 ${nativeUnit}`, formatNative(row.entry.native_net_entry_credit)) +
          factMarkup(`入场费前估值 ${valuationUnit}`, formatMoney(row.entry.simulated_entry_credit_valuation)) +
          factMarkup('观察质量', quality) +
          factMarkup('Gap count', row.entry.gap_count) +
          factMarkup('Segment', row.entry.current_segment_sequence) +
          factMarkup('旧尝试', postCloseAttemptText(row.entry.post_close_attempt_state)) +
          factMarkup('终端经济 Cohort', position.terminal_economics_eligible) +
          factMarkup('连续路径 Cohort', position.continuous_path_eligible) +
          factMarkup('退出观察 Cohort', position.exit_acquisition_eligible) +
        `</div>` +
        `<div class="data-gap-panel">Observation Gap 只描述路径质量，不删除 Entry，也不终止退出责任。` +
          `Cohort 资格在离线研究面按问题分别派生；本页不使用一个全局布尔否决持仓。</div>` +
        `<details class="evidence-details"><summary>服务器原始 Entry / Position / Outcome</summary>` +
          `<pre class="evidence-raw">${escapeHtml(JSON.stringify({entry: row.entry, position: row.position, outcome: row.outcome}, null, 2))}</pre></details>` +
      `</div></details>` +
    `<p class="signal-nonclaim">PUBLIC SHADOW · READ ONLY · 公共盘口反事实，不是订单、成交、账户持仓或实际 PnL。</p>`;
}

const scoreMetricWidth = (result, member) => {
  const value = result && result[member] && Number(result[member].lower);
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value * 100)) : 0;
};

function radarDetailMarkup(row, documentValue) {
  const packet = radarScoreView(row);
  const result = scorePacketResult(packet);
  const deltaBucket = packet && packet.bucket_key && packet.bucket_key.delta_bucket;
  const funnel = documentValue && documentValue.funnel && typeof documentValue.funnel === 'object'
    ? documentValue.funnel : {};
  const confirmation = funnel.radar_confirmation && typeof funnel.radar_confirmation === 'object'
    ? funnel.radar_confirmation : {};
  const controlResearch = funnel.decision_control_research &&
    typeof funnel.decision_control_research === 'object' ? funnel.decision_control_research : {};
  const oi = packet && packet.oi_diagnostic && typeof packet.oi_diagnostic === 'object'
    ? packet.oi_diagnostic : null;
  return `<div class="signal-detail-head"><h3>${safeText(row.instrument_name)}</h3>` +
    `${badgeMarkup('Leader', 'purple', 'decision-badge')}</div>` +
    `<div class="signal-detail-grid">` +
      `<div class="signal-detail-fact"><span>V2 Score</span><strong class="signal-score">${safeText(scoreIntervalText(packet))}</strong></div>` +
      `<div class="signal-detail-fact"><span>状态</span><strong>${safeText(radarConfirmationText(row))}</strong></div>` +
      `<div class="signal-detail-fact"><span>到期 / TTE</span><strong>${safeText(formatDate(row.expiration_timestamp_ms))}<br>${safeText(formatDurationInterval(row.tte_interval_ms))}</strong></div>` +
      `<div class="signal-detail-fact"><span>Delta Bucket</span><strong>${safeText(deltaBucket)}</strong></div>` +
    `</div>` +
    `<div class="signal-metrics">` +
      `<div class="signal-metric"><div class="signal-metric-head"><span>Premium Strength (A/S/T)</span>` +
      `<strong>${safeText(scoreComponentText(packet, 'premium_evidence'))}</strong></div>` +
      `<progress class="signal-meter" max="100" value="${scoreMetricWidth(result, 'premium_evidence')}" ` +
      `aria-label="Premium Strength"></progress></div>` +
      `<div class="signal-metric risk"><div class="signal-metric-head"><span>Risk Quality (D/E)</span>` +
      `<strong>${safeText(scoreComponentText(packet, 'risk_quality'))}</strong></div>` +
      `<progress class="signal-meter" max="100" value="${scoreMetricWidth(result, 'risk_quality')}" ` +
      `aria-label="Risk Quality"></progress></div>` +
    `</div>` +
    `<p class="signal-summary">服务器将该 bucket leader 结算为 ${safeText(result && result.band)}；` +
      `当前覆盖为 ${safeText(scoreCoverageText(packet))}。</p>` +
    `<p class="signal-nonclaim">只读发现信号 · 非交易指令 · 尚未形成 Shadow Entry</p>` +
    `<details class="signal-evidence" data-evidence-details${evidenceExpanded ? ' open' : ''}>` +
      `<summary>查看完整证据</summary><div class="signal-evidence-body">` +
        `<div class="fact-grid">` +
          factMarkup('Bucket', scoreBucketText(packet)) +
          factMarkup('Leader coverage', packet && packet.leader_coverage) +
          factMarkup('执行价', formatDecimal(row.strike_price)) +
          factMarkup('Delta', formatInterval(row.delta_interval, value => formatCompactNumber(value, 3))) +
        `</div>` +
        scoreFactorMarkup(packet) +
        `<div class="callout-list">` +
          `<div class="callout info"><strong>Episode</strong>${safeText(radarConfirmationText(row))}</div>` +
          `<div class="callout blocker"><strong>当前 Radar 条件</strong>${safeText(reasonText(row.primary_blocker || row.detector_reason))}</div>` +
          `<div class="callout upgrade"><strong>升级条件</strong>${safeText(reasonText(row.upgrade_condition))}</div>` +
          `<div class="callout invalidation"><strong>失效条件</strong>${safeText(reasonText(row.invalidation_condition))}</div>` +
        `</div>` +
        `<div class="fact-grid">` +
          factMarkup('Unsigned OI / gamma', oi && oi.state) +
          factMarkup('OI concentration', oi && formatPercent(oi.concentration_share)) +
          factMarkup('Legacy V1 threshold', `${legacyDiagnosticText(packet)} · diagnostic only`) +
          factMarkup('Fact boundary', packet && packet.fact_boundary && packet.fact_boundary.causal_seq) +
        `</div>` +
        `<div class="data-gap-panel">Legacy threshold 与 unsigned OI/gamma 只作诊断；不驱动第二个 V1 detector，不声明 dealer 仓位方向。</div>` +
        `<div class="callout-list"><div class="callout info"><strong>非零确认归零</strong>` +
          `${safeText(reasonCountsText(confirmation.reset_counts))}</div>` +
          `<div class="callout info"><strong>KNOWN_NO_CONTROL</strong>` +
          `${safeText(reasonCountsText(controlResearch.known_no_control_reason_counts))}</div></div>` +
        `<div class="data-gap-panel">本 Runtime 累计诊断仅用于有界归因，非本行因果归因；` +
          `本行只信任 packet 内的 bucket、leader 与 fact boundary，不按合约名拼接 Candidate 或 Shadow 状态。</div>` +
        `<pre class="evidence-raw">${escapeHtml(JSON.stringify(row, null, 2))}</pre>` +
      `</div></details>`;
}

function selectedRow(documentValue) {
  const rows = visibleRows(documentValue);
  if (!rows.length) return null;
  if (queueMode === 'structures') {
    return rows.find((row, index) => shadowBookIdentity(row, index) === selectedShadowId) || rows[0];
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
  const kicker = document.getElementById('detail-kicker');
  const evidenceToggle = document.getElementById('evidence-toggle');
  if (!row) {
    drawerOpen = false;
    title.textContent = '当前没有可显示的详情';
    content.innerHTML = `<div class="detail-placeholder">${emptyQueueMarkup(documentValue)}</div>`;
  } else if (queueMode === 'structures') {
    if (kicker) kicker.textContent = '已选择';
    title.textContent = 'Shadow 风险与退出责任';
    content.innerHTML = shadowDetailMarkup(row, documentValue);
  } else {
    if (kicker) kicker.textContent = '当前信号证据';
    title.textContent = '强信号证据';
    content.innerHTML = radarDetailMarkup(row, documentValue);
  }
  if (evidenceToggle) {
    evidenceToggle.hidden = !row;
    evidenceToggle.textContent = evidenceExpanded ? '收起证据' : '展开证据';
  }
  if (content) content.scrollTop = previousScrollTop;
  updateResponsiveDetailState();
}

function renderFooter(documentValue) {
  const radarCount = document.getElementById('footer-radar-count');
  const shadowCount = document.getElementById('footer-shadow-count');
  const evidence = document.getElementById('footer-evidence');
  if (!radarCount || !shadowCount || !evidence) return;
  if (!documentValue || !selectedChannelCanUseCurrentSnapshot(documentValue)) {
    radarCount.textContent = '—';
    shadowCount.textContent = '—';
    evidence.disabled = true;
    return;
  }
  radarCount.textContent = `${strongSignalRows(documentValue).length} 个当前强信号`;
  const shadowRows = shadowBookRows(documentValue);
  const exitRequired = shadowRows.filter(row =>
    shadowLifecyclePresentation(row).key === 'EXIT_REQUIRED').length;
  shadowCount.textContent = `${shadowRows.length} 个持仓 · ${exitRequired} 个退出责任`;
  evidence.disabled = queueMode !== 'radar' || !selectedRow(documentValue);
}

function renderWorkspace(documentValue) {
  renderChannelRail(documentValue);
  renderProductToolbar(documentValue);
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
  const latencyFields = [
    'latest_market_event_timestamp_ms', 'latest_market_event_age_ms',
    'last_wire_message_age_ms', 'last_queue_processing_lag_ms',
    'queue_lag_deadline_ms', 'queue_lag_currentness_active'
  ];
  if (latencyFields.some(field => !(field in documentValue.system)) ||
      typeof documentValue.system.queue_lag_currentness_active !== 'boolean') {
    throw new Error('invalid workbench latency projection');
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
  selectedShadowId = null;
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
  if (!CHANNELS.some(value => value.id === channelId)) return;
  const focusIdentity = captureFocusIdentity();
  selectedChannelId = channelId;
  selectedShadowId = null;
  selectedRadarId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  productMatrixOpen = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateQueueMode(mode) {
  if (!['structures', 'radar'].includes(mode)) return;
  const focusIdentity = captureFocusIdentity();
  queueMode = mode;
  drawerOpen = mode === 'structures' && !isDrawerViewport();
  shadowFiltersOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateFilter(filter) {
  if (queueMode !== 'structures' || !SHADOW_BOOK_FILTERS.some(([value]) => value === filter)) return;
  const focusIdentity = captureFocusIdentity();
  shadowLifecycleFilter = filter;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateOptionFilter(filter) {
  if (!['both', 'put', 'call'].includes(filter)) return;
  const focusIdentity = captureFocusIdentity();
  optionFilter = filter;
  selectedRadarId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateShadowOptionFilter(filter) {
  if (!['both', 'put', 'call'].includes(filter)) return;
  const focusIdentity = captureFocusIdentity();
  shadowOptionFilter = filter;
  selectedShadowId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateShadowExpiryFilter(filter) {
  shadowExpiryFilter = filter || 'ALL';
  selectedShadowId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
}

function activateShadowSearch(query) {
  shadowSearchQuery = String(query || '').trim();
  selectedShadowId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  const input = document.getElementById('shadow-search');
  if (input && typeof input.focus === 'function') {
    input.focus();
    if (typeof input.setSelectionRange === 'function') {
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }
}

function toggleActiveOnly() {
  const focusIdentity = captureFocusIdentity();
  activeOnly = !activeOnly;
  selectedRadarId = null;
  drawerOpen = false;
  evidenceExpanded = false;
  renderWorkspace(currentDocument);
  restoreFocusIdentity(focusIdentity);
}

function activateRow(rowId) {
  if (!currentDocument) return;
  const focusIdentity = captureFocusIdentity();
  if (queueMode === 'structures') selectedShadowId = rowId;
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
    const option = target.closest('[data-option-filter]');
    if (option) {
      if (queueMode === 'structures') activateShadowOptionFilter(option.dataset.optionFilter);
      else activateOptionFilter(option.dataset.optionFilter);
      return;
    }
    const shadowOption = target.closest('[data-shadow-option-filter]');
    if (shadowOption) {
      activateShadowOptionFilter(shadowOption.dataset.shadowOptionFilter);
      return;
    }
    if (target.closest('#active-only-toggle')) {
      toggleActiveOnly();
      return;
    }
    if (target.closest('#shadow-filter-toggle')) {
      shadowFiltersOpen = !shadowFiltersOpen;
      renderWorkspace(currentDocument);
      return;
    }
    if (target.closest('#product-matrix-toggle')) {
      setProductMatrixOpen(!productMatrixOpen);
      return;
    }
    if (target.closest('#channel-close')) {
      setProductMatrixOpen(false);
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
    if (target.closest('#footer-evidence')) {
      const selected = selectedRow(currentDocument);
      if (selected && queueMode === 'radar') openDetail(radarIdentity(selected));
      return;
    }
    const detailAction = target.closest('[data-detail-action]');
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
    if (target.closest('#detail-close') || target.closest('#detail-scrim')) {
      closeDetail();
      return;
    }
    if (shadowFiltersOpen && !target.closest('#shadow-filter-popover')) {
      shadowFiltersOpen = false;
      renderWorkspace(currentDocument);
    }
    if (productMatrixOpen && !target.closest('#channel-rail')) setProductMatrixOpen(false);
  });

  document.addEventListener('change', event => {
    if (event.target && event.target.id === 'shadow-expiry-filter') {
      activateShadowExpiryFilter(event.target.value);
    }
  });

  document.addEventListener('input', event => {
    if (event.target && event.target.id === 'shadow-search') {
      activateShadowSearch(event.target.value);
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drawerOpen) {
      event.preventDefault();
      closeDetail();
      return;
    }
    if (event.key === 'Escape' && productMatrixOpen) {
      event.preventDefault();
      setProductMatrixOpen(false);
      const toggle = document.getElementById('product-matrix-toggle');
      if (toggle && typeof toggle.focus === 'function') toggle.focus();
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

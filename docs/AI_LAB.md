# Optimatrix AI Lab

AI Lab 和主程序位于同一个 Python 包：`src/optimatrix/ai_lab/`。它不在临时目录，也不再叫
Challenger Lab；`Challenger` 只表示 Base 对照实验里的一个冻结角色。

默认研究数据和可读报告放在：

```text
/Users/logan/Library/Application Support/Optimatrix/ai-lab
├── policy-quality-reviews.jsonl  # 当前规则质量 Review 哈希链
├── session-reviews.jsonl         # 旧终值筛选链，只验证，不进入规则质量记忆
├── codex-analyses.jsonl          # 可选结构化 Codex 分析哈希链
├── daily-review-state.json        # 可覆盖的运行状态，不是业务事实
├── workbench-review-projection.json # 最近 32 个当前 Review 的可重建 Web 投影
├── evidence/<session>/<evidence>/official-index-history.json
└── reports/<session>/<review>/
    ├── policy-quality-review.json
    ├── policy-quality-review.md
    └── codex/<analysis>/          # 可选补充；不拥有 verdict
```

这个根与生产 ObservationLedger / CaseJournal 完全分开。AI Lab 只读 Ledger，不回填
Decision、Outcome、Case 或 Position。

`policy-quality-reviews.jsonl`、`evidence/` 和 `reports/` 是可验证的持久证据：Review 追加、
证据和报告按内容身份寻址，不覆盖已有不同内容。另两个顶层 JSON 只服务运行与展示：状态
文件可以更新，Workbench 投影经过内容密封、原子替换，并可随时从 Review 哈希链重建。
它们都不是第二套业务事实。当前只有一个低频写者、每天至多一个新 Review，也没有跨表
查询或并发事务需求，因此不引入数据库、队列、迁移或双写协议。

## AI Lab 真正在回答什么

Base 的事前规则和 DecisionRecord 已经冻结。Session 结束后，Lab 不再检查规则有没有照着
执行，而是利用收盘后才知道的单日 IV 曲线、RV 曲线、真实价格路径、费用和官方结算，判断
这套事前规则的取舍是否正确：有没有漏掉低风险机会，也有没有承担不值得的风险。

每个预登记 Window 只有四种已知分类：

| Base 行为 | 事后 Oracle | 分类 |
|---|---|---|
| 选中同一合格四腿 | 有机会 | `CAPTURED_OPPORTUNITY` |
| 没选 | 无机会 | `CORRECT_AVOIDANCE` |
| 没选 | 有机会 | `MISSED_OPPORTUNITY` |
| 选中的结构事后不合格 | 无论是否有别的结构 | `OVER_RISK_SELECTION` |

任何必需事实缺失时，只有该 Window 是 `UNKNOWN`；它不会抹掉其他 Window 已知的四象限
分类。Lab 始终保留完整注册分母，并报告覆盖率、漏单率、过度冒险率和机会出现率的逻辑
上下界。缺失不假定为随机，因此这些是 identification bounds，不是置信区间或插值估计。

## 固定事后 Oracle

Oracle 不以“最终赚钱”单独定义机会。一个四腿结构必须同时满足：

1. decision-time 组件书能按完整数量计价，并通过冻结 Policy 的全部 Candidate 级结构和
   承保门槛，包括标准 Combo 成本、净 Delta、最低净权利金、权利金/最大赔付比、USD
   contractual-payoff 上限、boundary reference-loss 和费用负担；
2. 入场 same-session IV variance proxy 严格高于事后 RV proxy；未来 variance 路径可来自
   完整预登记切点尾部，或覆盖该 Window 至到期的密封 Deribit 官方指数历史，再与所有可用
   的随后 trailing matched-horizon RV proxy 取较大值；
3. 已知且连续的真实路径没有触及 Put 或 Call 短腿；
4. 官方结算后的 `entry native net credit + settlement native cashflow` 严格大于零。

这四项都是合取条件。终值盈利但 IV 没覆盖后来 RV，不是机会；终值盈利但盘中穿过短腿，
也不是机会；事后赚钱但当时最低权利金、收益/风险比、Delta 或其他 Candidate Policy 门槛
没有通过，同样不是漏单。最后一类单列为 `HINDSIGHT_POSITIVE_POLICY_REJECT` 诊断样本，
用来积累阈值研究证据，但不进入漏单数或漏单率。这样才同时检查“没有放过合格机会”和
“没有为了赚小钱承担过大 Gamma/路径风险”。

Oracle identity 随 Policy 和方法内容密封。当前 V3 不声称拥有可执行 Combo 流动性、盘中
真实平仓价或账户 PnL；这些缺口不能被终值盈利替代。

## Session verdict

- 零个可审判 Window：`UNKNOWN`；
- 有缺口、已知 Window 暂无规则错误：`PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR`；
- 有缺口且已证明漏单/冒险：`OBSERVED_RULE_TOO_CONSERVATIVE`、
  `OBSERVED_RULE_TOO_AGGRESSIVE` 或 `OBSERVED_MIXED_RULE_ERROR`；
- 完整、无事后机会且 Base 全部避开：`NO_OPPORTUNITY_CORRECTLY_AVOIDED`；
- 完整、Base 抓到机会、零漏单、零过度风险：`RULE_WELL_CALIBRATED`；
- 有漏单而无过度风险：`RULE_TOO_CONSERVATIVE`；
- 有过度风险而无漏单：`RULE_TOO_AGGRESSIVE`；
- 同时有漏单和过度风险：`MIXED_RULE_ERROR`。

`RULE_WELL_CALIBRATED` 只证明这个 Session 的取舍一致。单 Session 永远不能证明 Policy
长期优秀或存在 Edge。

## Codex 和累积记忆

`UNKNOWN`、`PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR` 与
`NO_OPPORTUNITY_CORRECTLY_AVOIDED` 直接给结论，不调用 Codex。规则偏保守、偏激进或混合
时，Codex 只能解释确定性事实和提出可证伪假设，不能跳到 Challenger。
只有完整 `RULE_WELL_CALIBRATED` 且 Base 确实抓到至少一个机会，才允许另行研究是否存在
更好的冻结 Challenger。

确定性 JSON/Markdown 报告在任何可选 Codex 子进程之前落盘。Codex 失败会显示
`FAILED_OPTIONAL_ANALYSIS`，但不会抹掉 Review 或阻断交易员报告；成功分析写成独立补充。

记忆只统计每个 Session 终端的 V3 Policy-quality Review、重复 blocker 和可证伪假设。
旧 `optimatrix.ai-lab.policy-quality-review.v1` 保持原哈希链并标为
`SUPERSEDED_BY_PARTIAL_IDENTIFICATION_V2`；V2 保持原哈希链并标为
`SUPERSEDED_BY_RISK_QUALITY_V3`。每个后继 Review 必须精确引用同 Session 的前一个 Review
identity；不能覆盖、删除或分叉旧文件。更早的旧
`optimatrix.ai-lab.session-review.v1` 仍保留并验证哈希链，但统一标为
`INVALID_FOR_POLICY_QUALITY`，其 `MISSED_OPPORTUNITY` 不进入 Codex、累计 verdict 或
Challenger 资格。

## 命令

真实 Ledger 读取需要当前 Stage 和任务单独授权；实现测试只用 synthetic 临时根：

```bash
optimatrix-ai-lab fetch-official-evidence \
  --session-id '<ended-session-expiry-utc>'

optimatrix-ai-lab review-session \
  --ledger-root '/path/to/read-only/ledger' \
  --session-id '<ended-session-expiry-utc>' \
  --official-index-evidence '/path/under/ai-lab/official-index-history.json'

optimatrix-ai-lab review-session \
  --ledger-root '/path/to/read-only/ledger' \
  --session-id '<ended-session-expiry-utc>' \
  --with-codex

optimatrix-ai-lab verify-memory
```

## 每日收盘复盘

常态化入口是一次即退出的命令，而不是常驻循环：

```bash
optimatrix-ai-lab daily-review \
  --ledger-root '/path/to/read-only/ledger' \
  --lab-root '/path/to/separate/ai-lab' \
  --first-session-id '2026-08-17T08:00:00Z'
```

它从授权的首个 Deribit Session 起按日连续寻找最早的未复盘 Session，而不是只从已有
DecisionRecord 猜测日期。因此，即使某天完全没有记录，复盘仍保留注册的 `96` 个 Window，
并把缺失明确记为 `UNKNOWN`，不会让整日从历史中消失。已有 DecisionRecord 必须各自已有
append-once WindowOutcome；否则本次返回 `NOT_READY`，不请求事后历史，也不写部分 Review。

准备就绪后，命令先用 Deribit UTC 确认 Session 已结束，再获取一次固定的官方
`btc_usd/2d` 指数历史；每次最多处理一个 Session，不在进程内等待或重试。报告先按内容
身份幂等落盘，随后才追加 Review 哈希链，因此报告与记忆之间的崩溃边界可以在下次调用
恢复，且不会产生重复 Review。最后重建 Workbench 投影。默认不调用 Codex，也不创建、
修改或晋升 Challenger/Policy。

仓库 plist `deploy/com.optimatrix.d1-session-review.plist` 只用 `RunAtLoad` 和
`StartInterval=900` 唤醒这个一次性命令；没有 `KeepAlive`、内部 sleep 或重试循环。没有
准备好的已结束 Session 时，下一次 launchd 周期自然再检查。

Workbench 只读取最多最近 `32` 个当前 V3 Review 的派生投影。用户可切换已完成 Session，
查看 verdict、96-Window 分母、识别区间、四象限、结构漏斗、blocker、证据缺口、IV/RV
曲线、逐 Window 分类及人类晋升门。投影缺失或损坏只显示明确的不可用状态，不能阻止 B3
Runtime、改变 Decision，或赋予 Policy、执行、账户、订单、成交和资金权限。完整逐 Window
明细作为独立的本地数据脚本只在投影身份变化时原子更新；每秒刷新的 Runtime 页面只携带
小型引用，避免把数 MB 历史报告反复写盘。

旧 D1 的 `seal/register/run/promotion` 只用于冻结 Base/Challenger、时间切分和人审边界。
任何 `ACTUAL_PUBLIC_PATH` Challenger 数据集都必须绑定一个完整、eligible 的当前
Policy-quality Review；旧终值筛选 Review 不再有资格。

## 永久非结论

- public Shadow 组件书估值不是 Combo 报价、订单、成交或可执行流动性；
- 事后 Oracle 不是事前可知信号，也不是交易执行；
- 一个 Session、Candidate 数、终值盈利或胜率不能证明 Policy qualification 或 Edge；
- AI Lab 没有账户、资金、私有 API、部署或自动推广权限。

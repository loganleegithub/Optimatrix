# Optimatrix AI Lab

AI Lab 和主程序位于同一个 Python 包：`src/optimatrix/ai_lab/`。它不在临时目录，也不再叫
Challenger Lab；`Challenger` 只表示 Base 对照实验里的一个冻结角色。

默认研究数据和可读报告放在：

```text
/Users/logan/Library/Application Support/Optimatrix/ai-lab
├── policy-quality-reviews.jsonl  # 当前规则质量 Review 哈希链
├── session-reviews.jsonl         # 旧终值筛选链，只验证，不进入规则质量记忆
├── codex-analyses.jsonl          # 可选结构化 Codex 分析哈希链
└── reports/<session>/<review>/
    ├── policy-quality-review.json
    ├── policy-quality-review.md
    └── codex/<analysis>/          # 可选补充；不拥有 verdict
```

这个根与生产 ObservationLedger / CaseJournal 完全分开。AI Lab 只读 Ledger，不回填
Decision、Outcome、Case 或 Position。

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

任何必需事实缺失时，该 Window 是 `UNKNOWN`。只要完整 Session 分母里还有一个
`UNKNOWN`，最终规则质量 verdict 也必须是 `UNKNOWN`。

## 固定事后 Oracle

Oracle 不以“最终赚钱”单独定义机会。一个四腿结构必须同时满足：

1. decision-time 组件书能按完整数量计价，并保留标准 Combo 成本、USD contractual-payoff
   上限和 boundary reference-loss 硬约束；
2. 入场 same-session IV variance proxy 严格高于事后 RV proxy；事后 RV 取“完整预登记切点的
   未来 log-return variance”和“随后 trailing matched-horizon RV proxy 曲线最大值”两者较大；
3. 已知且连续的真实路径没有触及 Put 或 Call 短腿；
4. 官方结算后的 `entry native net credit + settlement native cashflow` 严格大于零。

这四项都是合取条件。终值盈利但 IV 没覆盖后来 RV，不是机会；终值盈利但盘中穿过短腿，
也不是机会。这样才同时检查“没有放过机会”和“没有为了赚小钱承担过大 Gamma/路径风险”。

Oracle identity 随 Policy 和方法内容密封。当前 V1 不声称拥有可执行 Combo 流动性、盘中
真实平仓价或账户 PnL；这些缺口不能被终值盈利替代。

## Session verdict

- 有证据缺口：`UNKNOWN`；
- 完整、无事后机会且 Base 全部避开：`NO_OPPORTUNITY_CORRECTLY_AVOIDED`；
- 完整、Base 抓到机会、零漏单、零过度风险：`RULE_WELL_CALIBRATED`；
- 有漏单而无过度风险：`RULE_TOO_CONSERVATIVE`；
- 有过度风险而无漏单：`RULE_TOO_AGGRESSIVE`；
- 同时有漏单和过度风险：`MIXED_RULE_ERROR`。

`RULE_WELL_CALIBRATED` 只证明这个 Session 的取舍一致。单 Session 永远不能证明 Policy
长期优秀或存在 Edge。

## Codex 和累积记忆

`UNKNOWN` 与 `NO_OPPORTUNITY_CORRECTLY_AVOIDED` 直接给结论，不调用 Codex。规则偏保守、
偏激进或混合时，Codex 只能解释确定性事实和提出可证伪假设，不能跳到 Challenger。
只有完整 `RULE_WELL_CALIBRATED` 且 Base 确实抓到至少一个机会，才允许另行研究是否存在
更好的冻结 Challenger。

确定性 JSON/Markdown 报告在任何可选 Codex 子进程之前落盘。Codex 失败会显示
`FAILED_OPTIONAL_ANALYSIS`，但不会抹掉 Review 或阻断交易员报告；成功分析写成独立补充。

记忆只统计当前 Policy-quality Review 的 verdict、重复 blocker 和可证伪假设。旧
`optimatrix.ai-lab.session-review.v1` 仍保留并验证哈希链，但统一标为
`INVALID_FOR_POLICY_QUALITY`，其 `MISSED_OPPORTUNITY` 不进入 Codex、累计 verdict 或
Challenger 资格。

## 命令

真实 Ledger 读取需要当前 Stage 和任务单独授权；实现测试只用 synthetic 临时根：

```bash
optimatrix-ai-lab review-session \
  --ledger-root '/path/to/read-only/ledger' \
  --session-id '2026-08-15T08:00:00Z'

optimatrix-ai-lab review-session \
  --ledger-root '/path/to/read-only/ledger' \
  --session-id '2026-08-15T08:00:00Z' \
  --with-codex

optimatrix-ai-lab verify-memory
```

旧 D1 的 `seal/register/run/promotion` 只用于冻结 Base/Challenger、时间切分和人审边界。
任何 `ACTUAL_PUBLIC_PATH` Challenger 数据集都必须绑定一个完整、eligible 的当前
Policy-quality Review；旧终值筛选 Review 不再有资格。

## 永久非结论

- public Shadow 组件书估值不是 Combo 报价、订单、成交或可执行流动性；
- 事后 Oracle 不是事前可知信号，也不是交易执行；
- 一个 Session、Candidate 数、终值盈利或胜率不能证明 Policy qualification 或 Edge；
- AI Lab 没有账户、资金、私有 API、部署或自动推广权限。

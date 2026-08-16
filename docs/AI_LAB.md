# Optimatrix AI Lab

AI Lab 现在和主程序在同一个 Python 包内：
`src/optimatrix/ai_lab/`。它不再是一个放在临时或独立项目目录里的 Challenger Lab。
`Challenger` 只保留为 Base 对照实验中的角色名，不再是 Lab 的产品名。

默认研究数据和可读报告放在：

```text
/Users/logan/Library/Application Support/Optimatrix/ai-lab
├── session-reviews.jsonl       # Session Review 哈希链
├── codex-analyses.jsonl        # 结构化 Codex 分析哈希链
└── reports/<session>/<review>/
    ├── session-review.json     # 完整机器事实
    └── session-review.md       # 期权交易员可读报告
```

这个根与生产 ObservationLedger / CaseJournal 必须完全分开。AI Lab 对 Ledger 只有只读输入，
不会回填 Decision、Outcome、Case 或 Position。

## 每个 Session 的固定工作流

1. 先重建该 Session 的 96 个预登记 DecisionWindow。
2. 检查每个 Window 是否有匹配的 Base DecisionRecord、健康的 decision-time
   MarketObservation、已知且连续的 WindowOutcome 路径、以及同到期日官方交割价。
3. 对每个可审计 Window 枚举当时完整数量可报价的四腿结构。`UNFILTERED_CONDOR` 保留
   四腿结构、DataHealth、标准 Combo 费用和 USD 风险约束，暂时拿掉明确列出的策略筛选。
4. 用官方交割价计算 `entry net credit + settlement cashflow`，并用连续路径极值记录两条
   短腿是否被穿越。
5. 零个成功结构只有在 96/96 全部可审计时才能写成 `NO_OPPORTUNITY`；否则是 `UNKNOWN`。
6. 找到成功结构但 Base 没选中同一 Candidate，写成 `MISSED_OPPORTUNITY`，逐项展示 Base
   blocker、actual、threshold 和 `signed_margin_to_pass`。无法诚实单值量化的门槛明确标记。
7. 只有 Base 选中的同一四腿结构也被事后确认，且 96/96 完整，才把 Challenger 比较标为
   `ELIGIBLE`。这仍只是允许另行冻结实验，不代表 Challenger 更好。

如果原规则给过 Candidate、但固定事后控制没有确认任何正的费用后结算结果，Session
仍是 `NO_OPPORTUNITY` 并停止；“系统有信号”不会被偷换成“市场确有机会”。

## Codex CLI

`--with-codex` 只在工作流允许时启动一次非交互 Codex：

```text
codex exec
  --ignore-user-config
  --ephemeral
  --sandbox read-only
  --output-schema <strict-json-schema>
  --output-last-message <json-output>
```

Codex 收到的是确定性 Session Review、之前密封的 Session 摘要和允许引用的 sha256 事实
编号。输出中的每个诊断和假设必须引用已提供事实；缺引用、引用不存在、越级提出
Challenger、改变 verdict 或输出非结构化内容都会失败关闭。`NO_OPPORTUNITY` 与 `UNKNOWN`
不会调用 Codex。

随着 Session 增加，记忆会统计 verdict、反复出现的 Base blocker 和反复出现的可证伪
假设。这里的“进化”是跨 Session 的证据越来越厚、假设越来越精确；它不自动改代码、
改阈值、推广 Policy 或取得交易权限。

## 命令

下面的真实 Ledger 读取属于单独的只读验证动作；阶段 D 的实现测试只使用 synthetic
fixture：

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

旧 D1 的 `seal/register/run/promotion` 仍存在，用于冻结 Base/Challenger、时间切分和人审
边界；synthetic mechanism fixture 可以继续独立验证机制，但任何包含
`ACTUAL_PUBLIC_PATH` 的真实数据集都必须同时传入一个或多个已密封且完整的
`BASE_FOUND_OPPORTUNITY` Review：

```bash
optimatrix-ai-lab run \
  --base '/path/to/base.json' \
  --challenger '/path/to/challenger.json' \
  --input '/path/to/actual-path-export.json' \
  --plan '/path/to/plan.json' \
  --store '/path/to/experiment-audit' \
  --registration-id 'sha256:...' \
  --session-review-id 'sha256:...'
```

命令会同时核对 Base Policy identity 和数据集 Window 是否被这些 eligible Review 覆盖。
自动推广仍永久拒绝。

## 永久非结论

- public Shadow 组件书估值不是 Combo 报价、订单、成交或可执行流动性；
- 事后正收益不是事前 Edge，也不是 Policy qualification；
- 一个 Session、Candidate 数或胜率不能证明规则更好；
- AI Lab 没有账户、资金、私有 API、部署或自动推广权限。

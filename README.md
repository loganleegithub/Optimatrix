# Optimatrix BTC 0DTE

Optimatrix 当前唯一实现的产品是：在同一 Deribit `08:00–08:00 UTC` Session 内，联合评估并
管理一组上下两侧、defined-risk 的非对称 Iron Condor。

```text
Long Put → Short Put → Short Call → Long Call
```

单边 Credit Vertical 只是铁鹰的一侧组件，不再是可独立选择的 Short Vol 产品路线。

## 产品漏斗

系统用一个 `SessionDecisionUnit` 计数，而不是用 option、strike、leg 或候选结构扩大样本：

```text
APPLICABLE_SESSION_DECISION
→ MARKET_CONTEXT_KNOWN
→ VRP_THETA_QUALIFIED
→ GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE
→ TWO_SIDED_STRUCTURE_EVALUABLE
→ ENTRY_ROUTE_EVALUABLE
→ ENTRY_ATTEMPT_SELECTED
→ DECISION_CASE_OPENED
→ ENTRY_RESULT_KNOWN
→ DECISION_CASE_OUTCOME_KNOWN
```

每一阶段暴露 numerator、denominator 和最早 blocker。测试通过、场景数量、页面完成或运行
时间都不构成产品进展。

## 当前能力

- 精确 Deribit 当日 Session 与 phase；
- inverse BTC 数量、深度、合法 tick、费用、估值和结算；
- Put/Call Credit Vertical 的联合非对称 Iron Condor 选择；
- Session VRP、Theta、Gamma/path、jump、event、breakout 与执行质量过滤；
- 四腿 attempt-boundary coherence；
- `FULL_ENTRY`、partial、cross-side incoherent、wings-only 与 no-entry acquisition truth；
- partial short exposure 创建即 `EXIT_REQUIRED`，不得以单边 Vertical 正常持有；
- short-only risk exit、残余 wing、settlement 和跨进程责任恢复；
- `FULL_ENTRY` 策略 Outcome 与 acquisition/remediation Outcome 分群；
- bounded public-only Deribit HTTP snapshot；
- 离线静态、浏览器不重算的四腿 Workbench。

## Public Shadow 边界

`PUBLIC SHADOW - READ ONLY` 只表示公共市场观察与 counterfactual economics。当前仓库没有
credentials、private API、account、margin、order、fill、RFQ、capital、实际仓位或真实 PnL。
公开 component books 也不证明四腿可原子成交。

Policy 仍是 `PUBLIC_SHADOW_UNQUALIFIED`。本仓库没有证明 Edge、Alpha、胜率或盈利能力；AI
只能提出 Challenger，不能自行改 Base Policy 或批准资本升级。

## 本地运行

```bash
make sync
make check

.venv/bin/python -m optimatrix snapshot \
  --event-state NONE \
  --output build/deribit-current-session-snapshot.json

.venv/bin/python -m optimatrix workbench \
  --snapshot build/deribit-current-session-snapshot.json \
  --output-dir build/workbench
```

打开 `build/workbench/index.html` 可查看静态只读页面。Snapshot 不创建 Decision Case；只有显式
提供的新产品本地 Case root 才能写模拟 journal。

## 重建与隔离

代码基底来自本地归档 `optimatrix-btc-0dte-rebuild-v0.1.0-complete.zip`，SHA-256：
`49bb944d2f873e27d175b6ef39d59ce5096ed42d300990eedff8519b8155e380`。旧仓基线为
`13902c53e972f12721d2ef9d17de866fbda288a7`。

旧单边 `apps/`、`packages/`、`policies/`、V2 contracts 和策略绑定 Workbench 已从当前工作树
物理删除；治理规则、CI/构建骨架、inverse 数学不变量和产品无关的视觉原则被适配保留。旧
实现仍可从 Git 基线恢复，但新产品不得 import、迁移、翻译、读取或计入旧 V2 Cases。

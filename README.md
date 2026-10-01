# Optimatrix · S3 本机 BTC 期权研究

保留 Deribit BTC inverse 公共行情和 Greeks.live 回测，新增一个能提出实验、调用回测工具、读取真实结果并给出中文结论的 Codex CLI researcher。**没有获批策略、真实资金授权、账户连接或下单功能。** 研究结论只是候选建议；模型价格和模型账本不能证明可成交优势。

阶段与真实证据：[S3](docs/stages/S3.md)。原始阶段记录保留：[S1](docs/stages/S1.md)、[S2](docs/stages/S2.md)。

## 启动与验收

本机已准备 Python 3.12+ 的 `.venv`。打开终端：

```sh
cd /Users/logan/Optimatrix
.venv/bin/python app.py
```

打开 [工作台](http://127.0.0.1:8765/)、[公共行情](http://127.0.0.1:8765/market)、[回测记录](http://127.0.0.1:8765/backtest)。原 `/research?research_id=...` 历史链接继续可用。保持终端运行；Ctrl+C 停止。同项目只允许一个服务进程，不能删除锁文件绕过检查。端口被占用时先检查已有页面；也可指定 `--port 8766`。仅监听本机，不设开机自启或云部署。

工作台只显示四类业务状态：BTC 账户、当前策略、Agent 工作、待批准事项。未接入的账户权益、已实现收益、未平仓风险和权利金预算显示“未接入”，不使用假设资金或回测收益代替。S3 没有运行策略、真实持仓或策略审批；研究判断与待批准策略分别呈现。费用图按同一 `run_id` 的已核对账本绘制，跨窗口结果不相加；完整金额、引用和原文按需展开。

`/api/workspace` 只聚合已保存的任务状态。Agent 集合按任务保存的身份、模型、预算、输入引用、动作和结果展示，区分运行中与历史；可用证据、显式读取与工具取得的结果分别列示。页面结构支持后续增加角色，当前执行器仍限单 researcher。新旧策略差异和策略审批需要 S4 业务对象及另行授权，本页不创建虚假的待批提案。现有研究预算授权、停止、继续与未知提交保护照常执行。

1. 研究页先核对问题、固定模型、Prompt 版本、参数范围和预算。每项任务最多 6 次模型调用（包含最多一次输出纠正）、2 次新远端创建尝试；单次模型超时 240 秒，任务活跃运行时间上限 1200 秒。
2. 勾选研究预算授权，点击“开始本次研究”。这不是交易授权。一次只运行一个研究任务，打开页面、刷新和重启都不会自动启动研究。
3. 查看真实事件、Agent 的简短说明、提交前保存的假设及比较计划、实际提交参数。模型不知道服务凭据，普通程序验证后才调用 Greeks.live。
4. 点击关联 `run_id` 打开回测。核对 BTC 模型金额、服务报告和缺口，查看最终中文结论、反例及字段引用。费用比较可以使用同一已核账记录确定性重算，会标明没有第二次远端调用。
5. 关闭页面不会停止已获准的后台任务。点击“停止本次研究”只停止本任务拥有的 CLI 进程和本地等待；远端已创建任务不会撤销，任务 ID 保留。
6. 重启后选择历史。暂停、读取失败或模型失败的可恢复任务需要显式继续，仍用原问题、原模型/Prompt 快照和剩余预算。预算用尽、提交结果未知不能自动扩大预算或盲目重发。

S3 首次真实研究的 ID、参数、结果与实际消耗见阶段记录；查看这条历史不会消耗模型或回测额度。再次点击“开始”会创建新研究，请有意操作。

## 配置和权限

直接依赖仍为 Flask、Waitress、Requests，版本锁在 `requirements.txt`。新环境安装：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Greeks.live 仍使用 S2 既有本机网页回测会话：只有回测后端读取 `.env` 中的 `GREEKS_LIVE_AUTH_TOKEN`。不要把密钥输入网页或聊天。CSV Data API Key 与网页回测会话不同，不替代认证。会话失效时由人类在官方页面登录并在本地更新配置；程序不自动登录、不创建密钥、不购买额度。

研究固定使用 `codex exec`、本机已有 **ChatGPT 登录**、`gpt-6-astra`、`high`、标准速度，未增加 OpenAI API SDK 或 API 计费路径。已验证 CLI 版本为 `0.158.0-alpha.2.1`。只运行 `codex --version`、`codex login status` 检查状态，不打开或复制认证缓存。CLI 版本不匹配时拒绝研究，需重新验证兼容性；不静默换模型。登录失效、额度不足、模型不可用、超时和结构错误分别保留状态。

`researcher/config.json`、`prompt.md`、`output.schema.json` 是固定研究配置。每项任务保存完整配置、Prompt 和输出结构快照及哈希，继续旧任务不会使用新 Prompt。模型输入只有本次问题、预算、能力、相关历史摘要和本任务工具结果。

CLI 忽略用户配置和执行规则，关闭 hooks、插件、连接器、浏览器、记忆、技能发现、子 Agent 和自动 goals。官方权限 profile 默认拒绝所有文件，只开放最小系统运行文件和本次输入目录（只读），模型命令网络禁用；不靠 `.gitignore` 或换 cwd 证明隔离。CLI 宿主正常 ChatGPT 登录通信与模型命令沙盒分开。每次服务启动都用虚假文件和本地网络正向对照运行零模型权限检查，失败则禁用研究。没有修改全局 Codex 配置，没有 `--yolo`。

官方依据：[非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[认证](https://learn.chatgpt.com/docs/auth)、[CLI 参数](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、[权限](https://learn.chatgpt.com/docs/permissions)、[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。

## 回测、恢复与金额边界

S2 的 `S2_BTC_LONG_CALL_V1` 和旧结果继续可看。新实验使用独立参数入口，不会总返回固定 run。同一逻辑步骤不能更换参数；相同实际请求会复用并标明“复用”，不同参数可以分别运行。

本轮只开放 BTC inverse、单腿多头 Call/Put、无对冲、`reopen`。日期窗口、UTC 时段、入场星期、正的绝对 Delta、目标期限、名义数量和费用均须明确提供。范围见研究页面，它是本阶段的保守限制，并非服务极限。禁止空腿、杠杆、其他币种、任意代码、URL、认证或路径参数。接口依据是 [Greeks.live 官方网页](https://backtest.greeks.live/static/) 的当前网页协议，**不是承诺稳定的公开 API**。

- 已有服务任务 ID：点击“继续获取结果”仅继续 GET 和本地处理，不重新 POST，不消耗新建额度。
- 明确未发送 POST：修复原因后可显式新尝试，保留旧失败和新旧关联。研究中的重试仍受原预算限制，不能从回测页绕过。
- POST 超时、中断或响应未确认：保留 `submission_unknown`，不能凭状态码或没有 ID 认定没有创建，不自动重发。
- 远端报告过期且未本地保存：显示不可恢复。网页报告目前说明保留一天，已保存的本地结果不受此影响。

BTC 账本按 lot/leg 和事件核对开仓、估值、平仓、费用及每日汇总。`option_value` 已含 quantity，不重复乘数量；中间 mark 不是现金收入；费用只扣一次。只对已支持且完整闭合记录给出模型核账成功。未闭合、到期结算、缺失、重复或未知形状保留原始报告与精确缺口。不能将 USD 汇总除以期末价格伪装为 BTC 收益。

价格是 SABR/WV4 曲面模型估值，不是买卖价、深度或逐笔成交回放。费用为实验假设；0.2 BTC 为假设资金，不是真实余额。两组费用情景不能证明长期盈利。H1 所需逐笔卖压及同步盘口目前不存在，不以费用实验冒充 H1 已验证。

S1 的公共行情保持独立：UTC 源时间、接收时间和数据年龄照常更新；无盘口、未取得、失败和过时分别显示。旧值不会因刷新变成新行情。网页请求不启动采集线程，研究失败不停止行情。

## 本地检查与外部审查

默认检查不使用真实凭据、不调用模型或远端回测：

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs tests/research_view.test.cjs
.venv/bin/python tests/s2_e2e.py
.venv/bin/python tests/s3_backtest_check.py
.venv/bin/python tests/s3_accounting_check.py
.venv/bin/python tests/s3_research_check.py
.venv/bin/python tests/s3_isolation_check.py
.venv/bin/python tests/s3_replay.py
```

Node 仅用于现有前端检查，不是网站运行依赖。`s3_isolation_check.py` 实际调用本机 CLI 沙盒与临时 loopback 服务，不调用模型、不访问外部服务。S2/S3 业务检查生成明确标为合成检查的本地工件；`s3_replay.py` 则重算已保存的真实文件，没有这些原文件时会明确退出。真实闭环另列在 S3 记录中。

原始任务、输入、CLI 事件/最终文件、配置快照和工具动作位于 `local/research/<research_id>/`；回测完整结果位于 `local/backtests/<run_id>/`；脱敏错误日志位于 `logs/`。这些目录、`.env*`（示例除外）、`.venv/` 和缓存均被忽略。**不要上传整个 local、日志、认证缓存或会话令牌。** GitHub 仅准备必要源文件、检查脚本、阶段记录和脱敏小样例。当前阶段不自动提交或推送 Git。

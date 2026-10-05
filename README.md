# Optimatrix · 策略研究与 Testnet 执行工作台

当前新增 **S4B-Testnet**：三个新手候选入口、结构化规则确认、中文规格导出，以及 BTC 20/60 日均线上穿 Call 的确定性 testnet 循环。人类已明确授权本轮 testnet 下单、撤单及对账；**主网只读公共行情，不能交易真实资金**。实现和实际验收见 [S4B-Testnet](docs/stages/S4B-Testnet.md)。

新增 [公共信号研究](http://127.0.0.1:8765/signals)：解释 Kenny 图片中的 12 类指标，固定运行 SuperTrend 与修正版 Squeeze 的 BTC 4h 观察。首轮历史价格诊断未通过，故没有给这两套规则开放 Testnet 下单；页面明确区分公共信号、假设标的价格交易和已有 Testnet 成交。来源、规则及结果见 [本轮研究记录](docs/stages/S4B-Public-Signal-Study.md)。

日线以 UTC 00:00 分界，每天 UTC 08:00 检查一次入场；Deribit 原生 1D 分界不同，因此使用完整真实小时数据构造日线，缺口会阻塞。每 15 秒核对 testnet 持仓、挂单、成交与退出条件。单次权利金与双边费用准备金不超过 testnet BTC 权益 1%，只持一笔多头、不加仓。实际规则由冻结版本及其导出规格定义。

项目业务凭据统一保存在根目录 `.env`：`DERIBIT_TESTNET_CLIENT_ID`、`DERIBIT_TESTNET_CLIENT_SECRET` 和现有 Greeks.live 字段。参考 `.env.example`，采用标准 `KEY=VALUE`，文件须本人所有、权限 `0600`，不接受软/硬链接；不要粘贴到聊天或提交 Git。共享读取器只向各连接器返回其所需字段，不做变量或 shell 求值、不写入进程环境、不回退到旧 JSON。主网公共客户端不读取凭据，testnet 客户端不能切换主网。已有账户连接不代表执行授权；启动接口绑定被冻结版本、账户、实现身份和本次授权。

根目录 `STOP` 存在时所有交易操作停止，包括撤单，已有挂单与仓位不会消失。正常暂停请用页面“暂停开仓”，它撤销本策略的开仓挂单，并继续对账与退出。停止服务或停止运行不会自动平仓。重启后运行进入待对账状态，不自动恢复交易；不要删除未决订单记录绕过恢复。

运行证据保存在 `local/strategy-runs/<run_id>/`，其中 `strategy_spec.md` 由冻结版本生成。Testnet 账本、主网行情观察与 Greeks 模型结果分别显示，测试网成交不能证明主网流动性或盈利能力。告警持久化并尝试本机 macOS 桌面通知；系统请求成功仍标为“未确认送达”。可另行开启浏览器通知，该通道需要页面打开。

下面保留 S4A 研究流程与原始阶段说明；它们不授予研究员账户执行能力。

围绕明确的策略版本执行“验证—决定—修订—复验”，保留 Deribit BTC inverse 公共行情、Greeks.live 模型回测和单个 Codex CLI researcher。**研究模型没有交易权限；没有主网账户连接或真实资金授权。** 研究结论只是候选建议；模型价格和模型账本不能证明可成交优势。

本轮实施与验收：[S4A](docs/stages/S4A.md)。原始阶段记录保留：[S3](docs/stages/S3.md)、[S1](docs/stages/S1.md)、[S2](docs/stages/S2.md)。

## 启动与验收

本机已准备 Python 3.12+ 的 `.venv`。打开终端：

```sh
cd /Users/logan/Optimatrix
.venv/bin/python app.py
```

打开 [工作台](http://127.0.0.1:8765/)、[公共行情](http://127.0.0.1:8765/market)、[回测记录](http://127.0.0.1:8765/backtest)。原 `/research?research_id=...` 历史链接继续可用。保持终端运行；Ctrl+C 停止。同项目只允许一个服务进程，不能删除锁文件绕过检查。端口被占用时先检查已有页面；也可指定 `--port 8766`。仅监听本机，不设开机自启或云部署。

工作台以策略清单和待处理事项为入口。每个策略保存来源内容、经济假设、失败机制与版本；验证关联原始研究及回测，不复制数字后丢失归属。策略详情围绕概览、验证、版本与决定组织，运行配置与原始技术证据移入折叠详情及 [运行 / 数据](http://127.0.0.1:8765/operations)。

1. 点击“录入想法”或“让研究员形成提案”，填名称与自然语言材料。保存不调用模型。链接未取得内容时明确标记，旧研究不自动升级为获批策略。
2. 检查草案规格和缺口。当前能执行的是 Greeks.live 单腿 BTC 买方曲面模型实验；新的盘口/逐笔算法标为待实现，并可保存面向开发 Codex 的实施任务。
3. 明确版本与本次问题。验证的日期、费用假设、数据用途单独保存；首次用于验证冻结经济规则。人类在页面勾选并批准一次有限研究：每任务最多 6 次模型调用、2 次远端创建，本轮最多 2 项任务。提案和修订建议也属于任务，预算批准不等于策略批准。
4. 验证中模型只提出结构化动作，程序核对参数必须等于批准版本与本次范围。任务完成、BTC 核账完成、经济证据支持分别呈现。达到预算即停止，刷新、轮询、重启不会自动创建研究。
5. 查看真实逐日模型 BTC 损益和费用情景（仅在原数据支持时绘制），展开精度、价格来源、数量、样本与引用。不同窗口不相加，假设资金不显示为真实余额。
6. 人类保存继续验证、修订、放弃或申请下一阶段的决定，写明依据和理由。规则修改通过修订入口创建子版本；费用、日期变化仍是原版本的新验证。旧版本与旧原始结果保留；已看过的重叠区间不能再次称为未见验证。

旧 `/research?research_id=...`、`/market`、`/backtest?run_id=...` 链接继续可访问。历史研究可显式停止/恢复；新研究统一在策略详情建立归属后启动。提交未知的回测不重发，已知远端 ID 仅继续取回。研究后端不可用时策略与历史仍可查看。关闭网页不停止已获准任务；请用任务页停止按钮。

## 配置和权限

直接依赖仍为 Flask、Waitress、Requests，版本锁在 `requirements.txt`。新环境安装：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Greeks.live 仍使用 S2 既有本机网页回测会话：只有回测后端读取 `.env` 中的 `GREEKS_LIVE_AUTH_TOKEN`。不要把密钥输入网页或聊天。CSV Data API Key 与网页回测会话不同，不替代认证。会话失效时由人类在官方页面登录并在本地更新配置；程序不自动登录、不创建密钥、不购买额度。

研究固定使用 `codex exec`、本机已有 **ChatGPT 登录**、`gpt-6-astra`、`high`、标准速度，未增加 OpenAI API SDK 或 API 计费路径。当前支持并验证的 CLI 为 `0.159.2`；旧 `0.158.0-alpha.2.1` 的历史证据保留。无模型检查核对 CLI 帮助、ChatGPT 登录、固定模型目录与实际文件/网络隔离；一次结构化接入探针已通过，见 [兼容证据](docs/samples/s4a-cli-compatibility.json)。不打开或复制认证缓存。CLI 版本不匹配时拒绝研究，需重新验证兼容性；不静默换模型。登录失效、额度不足、模型不可用、超时和结构错误分别保留状态。

`researcher/config.json`、`prompt.md`、`output.schema.json` 是固定验证配置；`proposal-prompt.md`、`proposal.schema.json` 是同一角色形成提案的固定接口。开发施工说明不会复制给内部 researcher。每项任务保存完整配置、Prompt 和输出结构快照及哈希，继续旧任务不会使用新 Prompt；安装 CLI 与旧任务快照不符时阻塞，不悄悄升级历史任务。模型输入只有本次问题、预算、能力、相关历史摘要和本任务工具结果。

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
.venv/bin/python tests/s4a_check.py
```

Node 仅用于前端检查，不是网站运行依赖。`s3_isolation_check.py` 实际调用本机 CLI 沙盒与临时 loopback 服务，不调用模型、不访问外部服务。S2/S3 业务检查生成明确标为合成检查的本地工件；`s3_replay.py` 则重算已保存的真实文件，没有这些原文件时会明确退出。`s4a_check.py` 检查临时修订复验流程与已有真实记录的只读关联；需要操作离线页面时运行 `tests/s4a_browser_fixture.py`，页面明确标记合成，退出删除临时数据。S4A 新真实研究及人类决定尚待页面批准，当前不能算真实验收完成，见阶段记录。

策略、版本、决定及追加关联保存在 `local/strategies.json`；没有自动写入影子结果或交易批准。原始任务、输入、CLI 事件/最终文件、配置快照和工具动作位于 `local/research/<research_id>/`；回测完整结果位于 `local/backtests/<run_id>/`；脱敏错误日志位于 `logs/`。这些目录、`.env*`（示例除外）、`.venv/` 和缓存均被忽略。**不要上传整个 local、日志、认证缓存或会话令牌。** GitHub 仅准备必要源文件、检查脚本、阶段记录和脱敏小样例。当前阶段不自动提交或推送 Git。

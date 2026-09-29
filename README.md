# Optimatrix · S1 公共行情首页

本项目长期研究 Deribit BTC 币本位期权买方机会，目标是增加净 BTC 数量。**目前只有真实公共行情页面，没有获批策略，也没有真实资金授权。** 账户、交易、回测和内部 Agent 均未实现；不提供下单按钮、余额或收益曲线。

## 安装与启动（macOS）

需要 Python 3.12 或更新版本。在“终端”逐行执行：

```sh
cd /Users/logan/Optimatrix
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

第一次安装后，以后只需执行 `cd /Users/logan/Optimatrix` 和 `.venv/bin/python app.py`。这次实施已在本项目创建好 `.venv` 并安装依赖，无需再安装。

在浏览器打开 **<http://127.0.0.1:8765>**，保留启动程序的终端。只能从本机访问，未配置公网或开机自启。无需 Deribit 账户、API 密钥、`.env` 或 OpenAI API；S1 完全不读取 `.env`。不要把密钥填进网页或发给助手。

停止：在启动程序的终端按 **Ctrl+C**，等命令提示符重新出现。重新启动：再次执行 `.venv/bin/python app.py`。已打开的网页会自动恢复；也可刷新页面。

## 页面怎么看、怎样亲手检查

1. 确认顶端写着“公共行情只读”，账户、回测及内部 Agent 均显示未接入/未实现。CLI 登录只表示本机有登录状态，不代表内部 Agent 已接入或模型调用已验证。
2. 等待首批数据（正常网络通常数秒至十几秒）。指数是 USD/BTC；期权 bid/ask 是 BTC 权利金 / 1 BTC 标的；盘口数量是 BTC 标的数量。本阶段仅接受 `contract_size=1` 的 BTC 合约，所以数量在数值上也等于张数。
3. 比较交易所源时间、接收时间和数据年龄。等待约 20–40 秒，应看到采集轮次/时间推进；价格本身可能不变。期权使用订单簿 `timestamp`；指数接口没有独立事件时间，显示的是响应信封 `usOut`，不能当成指数事件时间。
4. 保留网页，在终端按 Ctrl+C。前台正常运行的浏览器通常在 3–7 秒内显示服务不可达，并保留上次值。浏览器后台节流/电脑休眠可能推迟检测；切回页面会立即重新验证。重新运行启动命令，观察页面恢复。
5. 可选：运行中暂时关闭网络。服务仍可达，但公共请求将失败；旧行情须标异常，年龄超过 60 秒标过时。恢复网络后等退避期结束再检查，可能需等待 30 秒到 5 分钟；交易所 `Retry-After` 更长时遵从它。

未取得数据是“未取得数据”，空订单簿是“无买盘/无卖盘”，两者都不是零价格。行情是间隔采集的快照，不保证点击时仍可成交，不是交易信号。

## 运行方式与常见问题

- 一个 Python 进程含一个采集线程与本地 Web 服务；浏览器每 3 秒只读取缓存。采集完成后等待 15 秒再开始下一轮；合约目录约每 5 分钟刷新。超时、HTTP 错误及 JSON-RPC 错误都保留旧值并显示失败；限频/连续失败逐步延长重试间隔。
- 展示规则：按实时合约元数据过滤 BTC 币本位产品，选最近两个到期日，各选最靠近当前指数、同时存在 Call/Put 的行权价。优先离到期超过一小时的合约；没有时才选仍有效合约。每次目录更新重新选择，最多四个合约。这只是展示规则。
- `未取得数据` 一直不变：查看页面错误与 `logs/app.log`，检查网络是否能访问 `https://www.deribit.com`。程序使用直接 HTTPS 并验证 TLS；不读取 `.netrc`、环境代理或密钥。不支持通过关闭证书验证绕过网络问题。
- 时间异常：确认 macOS 日期和时间正确。内部时间为 UTC，页面另显示台北时间（Asia/Taipei，UTC+8）。源时间异常或过时都不能被刷新页面消除。
- `无法监听`：可能已启动，先打开现有页面，或在原终端停止服务。若 8765 被其他程序使用，可运行 `.venv/bin/python app.py --port 8766`，改用 <http://127.0.0.1:8766>。
- Codex CLI 未安装、未登录或检查失败不影响公共行情。服务启动时只调用 `codex --version` 和 `codex login status`，不打开登录文件、不运行任务；页面状态只代表该次启动检查。
- 本地日志自动轮转（最多约 3 MB），位于 `logs/`，不要上传。`.venv/`、`.env*`（示例除外）、日志、`local/`、Python 缓存均被 Git 忽略。

## 检查与文件

离线检查，无真实账户、无实时接口：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

若本机有 Node，可另运行前端离线检查：`node --test tests/frontend.test.cjs`。Node 不是启动网站的依赖。

显式进行一次真实公共连通检查并更新小型样本（访问四次公共接口）：

```sh
.venv/bin/python capture_sample.py
```

样本在 `docs/samples/deribit-public.json`，附 URL、UTC 接收时间及生产环境标志。合约列表保留两条原始记录并明确说明节选。Web 服务从不读取样本。阶段证据和限制见 [docs/stages/S1.md](docs/stages/S1.md)。

仅三个直接依赖：Flask（页面/API）、Waitress（本地 WSGI 服务）、Requests（公共 HTTPS）。完整依赖及传递依赖精确版本在 `requirements.txt`。使用依据：[Flask 官方 Waitress 文档](https://flask.palletsprojects.com/en/stable/deploying/waitress/)、[Requests 超时说明](https://requests.readthedocs.io/en/stable/user/advanced/#timeouts)。

# Kenny 图片策略研究与公共观察

本轮人类要求用 Chrome 阅读原帖图片、增加策略研究，并运行值得尝试的策略。本次已实际读取 [Kenny 原帖](https://x.com/_0xKenny/status/2106088861700915672) 的四张图片和作者回复；浏览器显示发布时间为 2026-10-03 02:28，页面时区未单独核实。原始 Chrome 图像及可访问文本保存在被忽略的 `local/kenny-strategy-study-20261005/`。不将“社区常用”当作盈利证据。

## 结论与范围

两套透明的指标值得作为研究基线，但本次固定 4h、仅多头、2 ATR 初始止损的适配 **没有通过初步价格诊断，不接入 Testnet 下单**。持续运行的是公共信号观察，不读取凭据或账户、不产生订单、不调用模型。已有 BTC 20/60 日线上穿 Call Testnet 继续独立运行；没有增加模型研究预算、主网私人权限或 Git 提交。

这不是原图 1–5 分钟剥头皮策略的等价复现，也不能据此否定所有周期和变体。没有为了翻正结果搜索参数。

| 图片中的工具 | 大白话机制 | 主要失败方式 | 本轮判断 |
|---|---|---|---|
| Squeeze Momentum | 收缩后扩张，顺动量跟进 | 假突破、衰减、反复挤压 | 修正版作为公共观察基线 |
| UT Bot | 越过随波幅移动的边界就翻向 | 横盘反复过线、低周期成本 | 与 SuperTrend 同类，暂不重复实施 |
| SuperTrend | 跨过波幅通道才确认趋势改变 | 震荡连续反转、确认滞后 | 官方标准公式作为公共观察基线 |
| Signals & Overlays | 集成多种入退场提示 | 不透明、事后挑模块过拟合 | 未获完整可复现规则，暂不采用 |
| Oscillator Matrix | 用动量背离寻找反转 | 转折确认滞后、回补画线 | 暂缓，须核对信号当时是否可见 |
| SMC / PAC | 标记结构变化与失衡区，等回踩 | 定义主观、趋势继续突破 | 先明确状态机，未实施 |
| Lorentzian Classification | 找历史相似指标状态进行近邻分类 | 训练窗口和邻居过拟合、统计口径 | 暂缓；作者统计窗不是正式回测 |
| Chandelier Exit + ZLSMA | 波幅退出线配平滑趋势线 | 低周期过敏、震荡止损 | 候补，与趋势基线重合 |
| HalfTrend | 高低点和波幅过滤后的趋势翻向 | 不重画也仍会滞后与误判 | 候补 |
| WaveTrend | 平滑价格动量交叉与极值 | 强趋势长期超买超卖、逆势接入 | 仅列未来过滤变量 |
| Delta / Footprint 近似 | 用小周期价格方向分配成交量 | 估算并非真实主动买卖方向 | 不以近似替代逐笔证据 |
| VWAP + EMA9/21 | 顺主要方向，回踩后恢复再跟进 | 均价附近来回穿、时段与成本 | 下一候选，先固定 BTC 日界/量单位/回踩定义 |

## 原始定义核对

- [SuperTrend 官方公式](https://www.tradingview.com/support/solutions/43000634738-supertrend/)：采用 ATR10 的 Wilder RMA、3倍通道、初始向下、收盘翻转。明确为官方标准的独立实现，不宣称与 Kivanc 脚本逐条一致。
- [LazyBear 作者说明](https://www.tradingview.com/script/nqQ1DT5a-Squeeze-Momentum-Indicator-LazyBear/) 指出旧版将 BB 倍数误用成 1.5，2014 年修正为 2.0；[作者指定修正版](https://pastebin.com/UCpcX8d7) 使用 BB20×2、KC20×1.5，KC 范围是 SMA(TR,20)，动量是指定去中心序列的20期线性回归末端。按严格的前栏 squeeze-on、当前 squeeze-off 与正动量定义入场。
- [Lorentzian 作者页](https://www.tradingview.com/script/WhBzgfDu-Machine-Learning-Lorentzian-Classification/) 将 Trade Stats 定位为特征调整反馈，不能替代正式回测。移植前需冻结版本、邻居池、标签和时间因果。
- [VWAP 官方定义](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/) 涉及锚点及价格/成交量口径，不能直接照搬美股开盘窗口到24小时 BTC。
- [Volume Delta](https://www.tradingview.com/support/solutions/43000725057-volume-delta/) 与 [Footprint](https://www.tradingview.com/support/solutions/43000726164-volume-footprint-charts-a-complete-guide/) 的分类估计，不等于取得交易所逐笔主动买卖流。
- [Deribit inverse 期权](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options) 按 BTC 报价，方向正确不等于期权 BTC 盈利；期限、隐波、权利金与成交成本尚未建立新策略证据。

## 冻结身份与诊断

- SuperTrend：策略 `ab29e50ab4894fbd986fa84846403b06`，版本 `d8894d7726244bb68402a65e4b221377`。
- Squeeze：策略 `5fd843688f424c629fb2c94e295d41b9`，版本 `db973520f45843e4bbe05c7442369082`。
- 固定计算定义 SHA256：`1a43fd81206f8f7326c80a8ae45eaa463165d4cb496628acc8aa8e1cc0c4614d`。
- 中文规格从版本确定性导出，保存在本轮 local 工件。交易实现保持待实现能力，不能进入 Greeks 六参数验证或 Testnet 运行。
- 主网 BTC-PERPETUAL 真实小时 OHLC，精确4根合成 UTC 四小时线。初始窗口 2025-10-04 16:00—2026-10-04 16:00 UTC，之前200根预热。禁止缺口补值、使用未收盘线或未来值。该段为已经看过的探索，不是未见验证。
- 入退场按下一栏开盘价假设，固定入场止损为2倍信号栏 ATR10；跳空按更差开盘价。盘中止损仅有栏级精度，无法证明对应盘口可成交。不给未平仓强制制造最后一笔退出。

| 固定4h适配 | 已闭合假设交易 | 胜率（未计成本） | 闭合交易复合价格回报 | 每边假设10bp | 每边假设25bp |
|---|---:|---:|---:|---:|---:|
| SuperTrend | 28 | 32.14% | -19.38% | -23.77% | -29.91% |
| Squeeze | 31 | 41.94% | -5.07% | -10.77% | -18.70% |

初始区间末 SuperTrend 尚有一笔假设仓位，其未实现价格变化没有并入上述闭合交易回报；Squeeze 没有未闭合假设仓位。以上是**标的价格诊断**，没有永续资金费用、合约现金流、期权定价、真实盘口或实际费用，不能称为账户收益。原始精度见 `first-live-observation.json` 与 `initial-replay.json`，逐笔假设路径独立于任何实际成交账本。

## 运行与验收

`signal_study.py` 纯计算；`signal_observer.py` 固定主网公共白名单、禁止重定向、禁用环境认证/代理，代码不导入凭据或私人交易连接器。只从显式 local manifest 绑定的冻结版本启动；每60秒观察、页面15秒读取缓存。重启不补历史事件；新完成栏首次观察且距收盘不超过120秒才记为新事件。

每轮及每次请求前检查根 STOP；存储失败锁定停止。历史修订检查覆盖每轮重取的约9根小时线，不宣称重新验证全部历史。原始响应留档；时效异常、数据缺口和历史变更均阻塞，不把旧值标为新。此观察服务随现有 app 生命周期运行，不另建账户执行进程。

离线验收：154项 Python 检查、12项前端检查通过。新增覆盖：因果前缀不变、ATR手算、BB修正、UTC边界、缺失/重复/未来K线、下一栏成交、跳空及同栏止损、持仓与闭合交易分离、公共环境/方法白名单、STOP、持久化故障锁定、损坏配置隔离、GET不启动采集。真实公共接口首次取得9562根已完成小时、聚合2390根四小时线；未向新策略发任何订单。

最终实测：公开观察已接入服务生命周期，至少三个连续轮次更新；浏览器实际打开 `/signals`、展开价格诊断，12项解释与两套状态均正确显示，控制台无错误。截图为本轮工件 `study-page.jpg`。

原 Testnet 运行 `8a8d1980cdfa4feeafc103cfd707d386` 在受控重启后先 reconcile 再 resume，状态为 running，继续15秒循环；没有持仓和活动订单，下一入场检查为 2026-10-05 08:00 UTC。未更换规则、实现身份、运行 ID 或订单额度。五个执行身份文件逐字节未变；移除本轮新增候选与决定后，原策略文件重构哈希与本轮前完全一致，98份此前历史文件未变。验收详情保存在 `local/kenny-strategy-study-20261005/acceptance.json`。未提交或推送 Git。

"""Static beginner choices; this module neither invokes models nor starts runs."""
from __future__ import annotations

from strategy import default_spec

# Reasons explain operational constraints, never claim an investment edge.
_RULE_GUIDANCE = {
    'signal_instrument': ('主网信号标的', '固定使用 BTC-PERPETUAL 的公开日线；永续只提供信号，不交易永续。'),
    'fast_days': ('短均线：20 天', '用约一个月的价格观察方向，避免每个短时波动都触发；它会滞后，震荡仍会反复亏损。'),
    'slow_days': ('长均线：60 天', '用更长的平均价格比较方向。必须取得最近连续 61 根完整日线，不补零、不回用旧信号。'),
    'check_hour_utc': ('每天 UTC 08:00 检查入场', '一天只检查一次新上穿，让人能复核；不因短时价格波动频繁交易。全部显示与记录使用 UTC。'),
    'entry_grace_seconds': ('允许调度延迟：60 秒', '错过窗口就等待下一天，不把已经过去的信号补成新订单。'),
    'min_dte': ('剩余期限下限：21 天', '避免默认直接购买临近到期的期权；时间价值仍会流失，期限稍长不代表不会归零。'),
    'target_dte': ('目标剩余期限：30 天', '先按期限、再按行权价确定唯一合约，避免临时挑选看起来更便宜的品种。'),
    'max_dte': ('剩余期限上限：45 天', '限制本案例的期限范围，控制产品差异；没有符合条件的同规格合约就跳过。'),
    'equity_fraction': ('每笔最多使用权益的 1%', '权利金加双边费用准备金不超过已核对测试网 BTC 权益的 1%，且受可用资金约束；不加仓，也不用凯利公式。'),
    'stop_loss_ratio': ('买一价跌至实际买入均价的 70% 时退出', '提前约定减仓触发点。价差、跳价或无买盘可能使实际亏损超过 30%，极端情况下整笔权利金可能损失。'),
    'exit_dte': ('剩余期限不超过 7 天时退出', '尝试在临近到期前结束持仓，降低继续暴露的时间；触发不等于保证成交。'),
    'main_spread_limit': ('主网价差最多为中间价的 10%', '拒绝主网盘口过宽的候选，避免只看一个参考价格；通过筛选也不能证明可以按该价格成交。'),
    'test_spread_limit': ('测试网价差最多为中间价的 20%', '测试网也必须有有效双边盘口；达不到条件就不交易，不用主网价格代替测试网成交。'),
    'loop_seconds': ('每 15 秒检查账户与退出条件', '固定频率核对持仓、成交和挂单，减少本地状态漂移；网络或程序中断期间无法保证及时止损。'),
    'max_orders_per_day': ('每天最多提交 4 次新订单', '限制异常循环的写请求规模；拒单、超时和未知提交也计数。额度用完可能仍有持仓，需要人工处理。'),
    'max_entries_per_day': ('每天最多尝试 1 次开仓', '不反复追同一个信号，不在部分成交后补齐，也不因拒单而重新开仓。'),
    'max_exit_attempts': ('每个退出意图最多提交 3 次', '限制追价和接口故障引起的重复订单。到上限仍未退出时保留实际持仓并告警，不宣称已经平仓。'),
    'entry_timeout_seconds': ('开仓挂单最多等待 300 秒', '五分钟未全成就撤掉剩余部分；确认终态前不发替代单，已成交部分按真实数量管理。'),
    'exit_timeout_seconds': ('退出挂单最多等待 60 秒', '一分钟后处理未成交部分。撤单结果不明必须先对账，不能假定撤单成功。'),
    'source_max_age_seconds': ('行情来源时间最多落后 30 秒', '陈旧行情不能作为下单依据；缺失时间戳也视为不可用，避免把旧价格当作实时价格。'),
    'receive_max_age_seconds': ('本机接收行情最多过去 15 秒', '来源时间与本机接收时间同时核验；每次提交前重新取得盘口，禁止用缓存旧值决策。'),
}


def _draft(contract, entry, exit_rule, frequency, data):
    return {
        'kind': 'unimplemented', 'rules': {}, 'implementation': '',
        'implementation_status': 'pending',
        'contract_selection': contract,
        'entry': entry, 'exit': exit_rule,
        'position_constraints': '研究草案：拟用固定小比例权利金、仅一笔多头、不加仓；具体资金比例及双边费用口径须另行确认。当前无下单权限。',
        'decision_frequency': frequency,
        'data_requirements': data,
        'clock': '研究草案按 UTC 已完成日线讨论；尚未确认检查时间、行情时效和故障恢复规则，不可执行。',
        'implementation_task': '先经现有提案审批明确阈值、合约、退出和数据要求，再另行授权实现。不得复用趋势策略执行器或以 Greeks 曲面替代真实执行验证。',
    }


def templates():
    """Return exactly three independent JSON-serializable cards, never mutate state."""
    spec = default_spec()
    return [
        {
            'id': 'trend', 'name': '20/60 日均线上穿 · BTC Call',
            'hypothesis': '价格已经向上走了一段，希望它继续涨。',
            'profits': '上涨持续而且足够快，期权升值超过时间价值流失、价差与费用时。',
            'failures': '价格来回震荡会反复止损；慢涨也可能抵不过期权时间价值流失。无买盘时止损可能无法成交，整笔权利金仍可能损失。',
            'frequency': '仅新的 20/60 日均线上穿才考虑入场，可能数周或数月没有交易；每天最多一次开仓尝试。',
            'friendliness': '4 / 5 · 规则易懂；期权、盘口与执行风险仍需核对',
            'implemented': True, 'spec': spec,
            'defaults': [{'key': key, 'label': _RULE_GUIDANCE[key][0], 'value': value,
                          'reason': _RULE_GUIDANCE[key][1]} for key, value in spec['rules'].items()],
        },
        {
            'id': 'breakout', 'name': '突破追随 · 研究草案',
            'hypothesis': '价格越过此前高点后，希望它继续向上走。',
            'profits': '突破后出现足够快且持续的上涨，覆盖期权、价差与费用成本时。',
            'failures': '反复冲高回落的假突破会连续亏损；追入后上涨太慢也可能亏损。',
            'frequency': '取决于观察窗口和突破阈值，尚未定参；平静时可能长期不触发，不能保证每日交易。',
            'friendliness': '3 / 5 · 触发易懂；假突破难处理',
            'implemented': False, 'defaults': [],
            'spec': _draft(
                '研究方向仅限 BTC 买入看涨期权；期限、行权价和双环境合约映射待确认，不允许程序自行挑选。',
                '研究假设：已完成日线收盘突破此前一段时间最高价后考虑买入；观察天数、是否需要确认与阈值待提案明确。',
                '必须预先确认止损、突破失败退出、到期前退出和无法成交时的处理；当前均待提案确认，不能运行。',
                '拟每日使用一次完整日线评估；准确检查时间、开仓频率与重复信号规则待确认。',
                '需可核对连续日线及实际期权合约、双边盘口、时间戳和费用；尚无验证结果，不使用虚构数据补齐。'),
        },
        {
            'id': 'rebound', 'name': '急跌反弹 · 研究草案',
            'hypothesis': '价格短期跌得很急，希望它回弹一些。',
            'profits': '急跌后及时出现足够大的反弹，超过期权时间损耗、价差与费用时。',
            'failures': '下跌继续或反弹迟迟不来时，会一再止损；每次觉得更便宜都加仓可能让亏损扩大。',
            'frequency': '取决于急跌幅度和观察窗口，尚未定参；平静时可能长期无交易，急跌时也不能无限重复买入。',
            'friendliness': '2 / 5 · 直觉易懂；过早买入和连续下跌风险较高',
            'implemented': False, 'defaults': [],
            'spec': _draft(
                '研究方向仅限 BTC 买入看涨期权；期限、行权价及合约映射待确认，当前不能自动选择。',
                '研究假设：已完成日线显示短期急跌后考虑反弹；跌幅阈值、观察窗口与是否等待止跌待提案明确。',
                '必须预先确认继续下跌的止损、反弹后的退出、最长持有时间及到期处理；均待提案确认。',
                '拟每日检查已完成日线；重复急跌信号冷却、每日最多次数与实际检查时间待确认。',
                '需连续、时间可核对的日线及真实期权盘口、产品元数据和费用；不得把缺失行情填零或把模型收益称为实盘收益。'),
        },
    ]

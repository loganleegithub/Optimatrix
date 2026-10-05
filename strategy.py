"""Deterministic BTC trend-call rules. No I/O, credentials, model, or order authority.

All cash and prices are BTC Decimal values. Times supplied by the caller are
Unix seconds; exchange candle ticks and expirations are Unix milliseconds.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import hashlib
import json
import math

KIND = 'btc_trend_call_v1'
IMPLEMENTATION = 'strategy.py:btc-trend-call-v1'
DEFAULT_RULES = {
    'signal_instrument': 'BTC-PERPETUAL', 'fast_days': 20, 'slow_days': 60,
    'check_hour_utc': 8, 'entry_grace_seconds': 60,
    'min_dte': 21, 'target_dte': 30, 'max_dte': 45,
    'equity_fraction': '0.01', 'stop_loss_ratio': '0.70', 'exit_dte': 7,
    'main_spread_limit': '0.10', 'test_spread_limit': '0.20',
    'loop_seconds': 15, 'max_orders_per_day': 4, 'max_entries_per_day': 1,
    'max_exit_attempts': 3, 'entry_timeout_seconds': 300,
    'exit_timeout_seconds': 60, 'source_max_age_seconds': 30,
    'receive_max_age_seconds': 15,
}
_DESCRIPTIONS = ('contract_selection', 'entry', 'exit', 'position_constraints',
                 'decision_frequency', 'data_requirements', 'clock')


class StrategyRuleError(ValueError):
    pass


def decimal(value, label='数值', *, positive=False, nonnegative=False):
    if isinstance(value, bool) or value is None:
        raise StrategyRuleError(f'{label}未知或无效')
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise StrategyRuleError(f'{label}未知或无效') from None
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        raise StrategyRuleError(f'{label}未知或无效')
    return result


def _stamp(value, label):
    result = float(decimal(value, label, positive=True))
    if not math.isfinite(result):
        raise StrategyRuleError(f'{label}无效')
    return result


def normalize_rules(rules=None):
    if rules is not None and not isinstance(rules, dict):
        raise StrategyRuleError('趋势规则须为对象')
    if set(rules or {}) - DEFAULT_RULES.keys():
        raise StrategyRuleError('趋势规则含未支持字段')
    result = dict(DEFAULT_RULES, **(rules or {}))
    if result['signal_instrument'] != 'BTC-PERPETUAL':
        raise StrategyRuleError('本实现仅支持 BTC-PERPETUAL 公共信号')
    ranges = {'fast_days': (2, 59), 'slow_days': (3, 120),
              'check_hour_utc': (0, 23), 'entry_grace_seconds': (1, 60),
              'min_dte': (14, 45), 'target_dte': (14, 60), 'max_dte': (14, 60),
              'exit_dte': (1, 14), 'loop_seconds': (15, 60),
              'max_orders_per_day': (1, 4), 'max_entries_per_day': (1, 1),
              'max_exit_attempts': (1, 3), 'entry_timeout_seconds': (15, 300),
              'exit_timeout_seconds': (15, 60), 'source_max_age_seconds': (1, 30),
              'receive_max_age_seconds': (1, 15)}
    for key, (low, high) in ranges.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise StrategyRuleError(f'{key}须为 {low}—{high} 的整数')
    bounds = {'equity_fraction': ('0.0001', '0.01'), 'stop_loss_ratio': ('0.70', '0.99'),
              'main_spread_limit': ('0.001', '0.10'), 'test_spread_limit': ('0.001', '0.20')}
    for key, (low, high) in bounds.items():
        value = decimal(result[key], key)
        if not Decimal(low) <= value <= Decimal(high):
            raise StrategyRuleError(f'{key}须在 {low}—{high} 之间')
        result[key] = format(value.normalize(), 'f')
    if result['fast_days'] >= result['slow_days']:
        raise StrategyRuleError('短均线周期须小于长均线周期')
    if not result['exit_dte'] < result['min_dte'] <= result['target_dte'] <= result['max_dte']:
        raise StrategyRuleError('期限须满足退出天数 < 最短期限 ≤ 目标期限 ≤ 最长期限')
    return result


def default_spec():
    return normalize_trend_spec({'kind': KIND, 'rules': DEFAULT_RULES})


def normalize_trend_spec(spec):
    allowed = {'kind', 'rules', 'implementation', 'implementation_status',
               'implementation_task', *_DESCRIPTIONS}
    if not isinstance(spec, dict) or set(spec) - allowed or spec.get('kind') != KIND:
        raise StrategyRuleError('无效趋势策略规格')
    r = normalize_rules(spec.get('rules'))
    canonical = {
        'kind': KIND, 'rules': r,
        'contract_selection': f"仅 BTC inverse Call；剩余 {r['min_dte']}—{r['max_dte']} 天，先选最接近 {r['target_dte']} 天的到期日，再选最接近主网 BTC 指数的行权价；并列取较早到期、较低行权价；双环境经济规格相同",
        'entry': f"主网 BTC-PERPETUAL 完成 UTC 日线 SMA{r['fast_days']}/SMA{r['slow_days']} 上穿；前一日短均线≤长均线、当日短均线>长均线；仅 UTC {r['check_hour_utc']:02d}:00 后 {r['entry_grace_seconds']} 秒内尝试，不补单；testnet 卖一价限价买入",
        'exit': f"testnet 买一价≤实际加权买入价×{r['stop_loss_ratio']}，或每日检查短均线≤长均线，或剩余期限≤{r['exit_dte']}天；买一价 reduce_only 限价退出，无固定止盈；止损触发不保证成交",
        'position_constraints': f"权利金与双边费用准备金≤testnet BTC 权益×{r['equity_fraction']}且≤可用资金；按数量步长向下取整；仅一笔多头、不加仓，部分成交不补齐；每日最多{r['max_orders_per_day']}次新单、其中开仓最多{r['max_entries_per_day']}次，每个退出意图最多{r['max_exit_attempts']}次",
        'decision_frequency': f"每{r['loop_seconds']}秒先核对真实账户、活动订单和成交；入场每日一次；开仓挂单{r['entry_timeout_seconds']}秒、退出挂单{r['exit_timeout_seconds']}秒后撤未成交部分，确认终态才允许替代单",
        'data_requirements': f"连续{r['slow_days'] + 1}根已完成 UTC 日线；双方活跃 BTC inverse 合约元数据和真实双边盘口；主网价差≤中间价×{r['main_spread_limit']}、testnet≤{r['test_spread_limit']}；来源年龄≤{r['source_max_age_seconds']}秒、接收年龄≤{r['receive_max_age_seconds']}秒；账户费率、权益、可用资金及实际成交费用须核对",
        'clock': 'UTC 00:00—次日00:00 日线；Deribit 24×7，只有元数据确认开放的市场可下单；页面及日志 UTC',
        'implementation': IMPLEMENTATION, 'implementation_status': 'implemented',
    }
    # Never silently erase a model/human condition absent from the executable rules.
    for key in _DESCRIPTIONS:
        if key in spec and spec[key] not in ('', canonical[key]):
            raise StrategyRuleError(f'{key}含不能由结构化规则确认的条件；请保留为待实现提案')
    if spec.get('implementation_task'):
        raise StrategyRuleError('趋势实现不能静默忽略额外实施任务')
    return canonical


def evaluate_signal(candles, now, rules=None):
    """Use exactly the latest consecutive completed UTC days; reject gaps/duplicates.

    Accept Deribit get_tradingview_chart_data result or rows with timestamp/close.
    An in-progress current UTC day may be present and is explicitly excluded.
    """
    r, stamp = normalize_rules(rules), _stamp(now, '当前时间')
    today = int(stamp // 86400) * 86400
    if isinstance(candles, dict):
        if candles.get('status') != 'ok':
            raise StrategyRuleError('日线来源未返回 ok')
        ticks, closes = candles.get('ticks'), candles.get('close')
        if not isinstance(ticks, list) or not isinstance(closes, list) or len(ticks) != len(closes):
            raise StrategyRuleError('日线时间与收盘数据不完整')
        for field in ('open', 'high', 'low'):
            if field in candles and (not isinstance(candles[field], list) or len(candles[field]) != len(ticks)):
                raise StrategyRuleError('日线 OHLC 长度不一致')
        rows = [dict(timestamp=t, close=c) for t, c in zip(ticks, closes)]
    elif isinstance(candles, list):
        rows = candles
    else:
        raise StrategyRuleError('日线格式无效')
    by_day = {}
    for row in rows:
        if not isinstance(row, dict):
            raise StrategyRuleError('日线记录无效')
        tick_ms = decimal(row.get('timestamp', row.get('tick')), '日线时间', positive=True)
        if tick_ms % Decimal(86400000):
            raise StrategyRuleError('日线未对齐 UTC 00:00')
        tick = int(tick_ms / 1000)
        if tick > today:
            raise StrategyRuleError('日线包含未来日期')
        if tick in by_day:
            raise StrategyRuleError('日线日期重复')
        by_day[tick] = decimal(row.get('close'), '日线收盘价', positive=True)
    days = list(range(today - (r['slow_days'] + 1) * 86400, today, 86400))
    if any(day not in by_day for day in days):
        raise StrategyRuleError('最近已完成日线缺失或不连续，禁止补零和旧信号')
    values = [by_day[day] for day in days]
    fast_n, slow_n = r['fast_days'], r['slow_days']
    fast, slow = sum(values[-fast_n:]) / fast_n, sum(values[-slow_n:]) / slow_n
    previous_fast = sum(values[-fast_n-1:-1]) / fast_n
    previous_slow = sum(values[-slow_n-1:-1]) / slow_n
    material = [{'timestamp': day * 1000, 'close': str(by_day[day])} for day in days]
    return {'fast': str(fast), 'slow': str(slow), 'previous_fast': str(previous_fast),
            'previous_slow': str(previous_slow), 'crossover': previous_fast <= previous_slow and fast > slow,
            'bearish': fast <= slow,
            'bar_date': datetime.fromtimestamp(days[-1], timezone.utc).date().isoformat(),
            'bar_count': len(days), 'signal_instrument': r['signal_instrument'],
            'data_sha256': hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def _metadata(meta, now):
    expected = {'kind': 'option', 'instrument_type': 'reversed', 'base_currency': 'BTC',
                'quote_currency': 'BTC', 'settlement_currency': 'BTC', 'counter_currency': 'USD',
                'price_index': 'btc_usd', 'option_type': 'call'}
    if not isinstance(meta, dict) or any(meta.get(k) != v for k, v in expected.items()):
        raise StrategyRuleError('合约不是经元数据确认的 BTC inverse Call')
    if meta.get('is_active') is not True or meta.get('state', 'open') != 'open':
        raise StrategyRuleError('合约不活跃或市场未开放')
    if not isinstance(meta.get('instrument_name'), str) or not meta['instrument_name']:
        raise StrategyRuleError('合约标识未知')
    if decimal(meta.get('contract_size'), '合约乘数') != 1:
        raise StrategyRuleError('不支持的合约数量单位')
    strike = decimal(meta.get('strike'), '行权价', positive=True)
    expiration = decimal(meta.get('expiration_timestamp'), '到期时间', positive=True)
    if expiration / 1000 <= decimal(now, '当前时间'):
        raise StrategyRuleError('合约已到期')
    return expiration, strike


def quantity_step(meta):
    # Deribit inverse option amounts are in BTC; min_trade_amount defines the
    # venue amount increment unless an explicit stricter amount_step is supplied.
    minimum = decimal(meta.get('min_trade_amount'), '最小数量', positive=True)
    step = decimal(meta.get('amount_step', meta['min_trade_amount']), '数量步长', positive=True)
    if minimum % step:
        raise StrategyRuleError('最小数量与数量步长不一致')
    return minimum, step


def price_step(meta, price):
    price = decimal(price, '价格', positive=True)
    step = decimal(meta.get('tick_size'), '价格步长', positive=True)
    bands = meta.get('tick_size_steps', [])
    if not isinstance(bands, list):
        raise StrategyRuleError('价格步长分段未知')
    ordered = []
    for band in bands:
        if not isinstance(band, dict):
            raise StrategyRuleError('价格步长分段无效')
        above = decimal(band.get('above_price'), '分段价格', nonnegative=True)
        tick = decimal(band.get('tick_size'), '分段步长', positive=True)
        ordered.append((above, tick))
    if len({v[0] for v in ordered}) != len(ordered):
        raise StrategyRuleError('价格步长分段重复')
    for above, tick in sorted(ordered):
        if price >= above:
            step = tick
    return step


def select_contract(main_instruments, test_instruments, index_price, now, rules=None):
    r, index = normalize_rules(rules), decimal(index_price, '主网 BTC 指数', positive=True)
    stamp, eligible = _stamp(now, '当前时间'), []
    if not isinstance(main_instruments, list) or not isinstance(test_instruments, list):
        raise StrategyRuleError('合约目录未知')
    for item in main_instruments:
        try:
            expiry, strike = _metadata(item, stamp)
        except StrategyRuleError:
            continue
        dte = (expiry / 1000 - Decimal(str(stamp))) / 86400
        if r['min_dte'] <= dte <= r['max_dte']:
            eligible.append((abs(dte - r['target_dte']), expiry, abs(strike-index), strike, item))
    if not eligible:
        raise StrategyRuleError('没有符合期限的主网 BTC inverse Call')
    eligible.sort(key=lambda row: row[:4])
    chosen = eligible[0][-1]
    matches = []
    for item in test_instruments:
        try:
            _metadata(item, stamp)
        except StrategyRuleError:
            continue
        if (decimal(item['expiration_timestamp']) == decimal(chosen['expiration_timestamp'])
                and decimal(item['strike']) == decimal(chosen['strike'])):
            matches.append(item)
    if len(matches) != 1:
        raise StrategyRuleError('主网所选合约在 testnet 没有唯一相同经济规格，不改选替代品')
    test = matches[0]
    quantity_step(test)
    decimal(test.get('tick_size'), 'testnet 价格步长', positive=True)
    return copy.deepcopy(chosen), copy.deepcopy(test)


def _validate_book_time(book, received_at, now, rules=None):
    r, stamp = normalize_rules(rules), _stamp(now, '当前时间')
    if not isinstance(book, dict) or book.get('state') != 'open':
        raise StrategyRuleError('盘口未知或市场未开放')
    source = _stamp(book.get('timestamp'), '盘口来源时间') / 1000
    received = _stamp(received_at, '盘口接收时间')
    if source > stamp + 5 or received > stamp + 5 or source > received + 5:
        raise StrategyRuleError('盘口时间在未来')
    if stamp - source > r['source_max_age_seconds'] or stamp - received > r['receive_max_age_seconds']:
        raise StrategyRuleError('盘口过时')


def validate_exit_bid(book, received_at, now, rules=None):
    """A held long may exit against a fresh executable bid without an ask side."""
    _validate_book_time(book, received_at, now, rules)
    bid = decimal(book.get('best_bid_price'), '买一价', positive=True)
    decimal(book.get('best_bid_amount'), '买一量', positive=True)
    return bid


def validate_quote(book, received_at, now, spread_limit=None, rules=None):
    bid = validate_exit_bid(book, received_at, now, rules)
    ask = decimal(book.get('best_ask_price'), '卖一价', positive=True)
    decimal(book.get('best_ask_amount'), '卖一量', positive=True)
    if bid > ask:
        raise StrategyRuleError('盘口买卖价倒挂')
    if spread_limit is not None:
        limit = decimal(spread_limit, '价差上限', positive=True)
        if (ask - bid) / ((ask + bid) / 2) > limit:
            raise StrategyRuleError('盘口价差超限')
    return bid, ask


def size_order(meta, ask, equity, available, fee_rate, rules=None):
    """fee_rate is the conservative per-side BTC fee per 1 BTC option amount.

    Reserve the uncapped rate on both sides, ignoring fee discounts/rebates.
    Connector must establish the fee denomination and upper bound first.
    """
    r = normalize_rules(rules)
    ask = decimal(ask, '限价权利金', positive=True)
    if decimal(meta.get('contract_size'), '合约乘数') != 1 or meta.get('instrument_type') != 'reversed' or meta.get('settlement_currency') != 'BTC':
        raise StrategyRuleError('数量或 BTC 费用单位未确认')
    if ask % price_step(meta, ask):
        raise StrategyRuleError('限价不符合 testnet 价格步长')
    equity = decimal(equity, 'testnet BTC 权益', nonnegative=True)
    available = decimal(available, 'testnet BTC 可用资金', nonnegative=True)
    fee = decimal(fee_rate, 'BTC 单边费用上界', positive=True)
    budget = min(equity * Decimal(r['equity_fraction']), available)
    minimum, step = quantity_step(meta)
    quantity = (budget / (ask + 2 * fee) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    return quantity if quantity >= minimum else Decimal(0)


def exit_reason(position, bid, now, bearish, rules=None):
    r = normalize_rules(rules)
    if not isinstance(position, dict):
        raise StrategyRuleError('持仓数据未知')
    size = decimal(position.get('size', position.get('amount')), '实际持仓数量', nonnegative=True)
    if not size:
        return None
    average = decimal(position.get('average_price'), '实际加权买入价', positive=True)
    expiry = decimal(position.get('expiration_timestamp'), '持仓到期时间', positive=True) / 1000
    price = decimal(bid, '退出买一价', positive=True)
    if price <= average * Decimal(r['stop_loss_ratio']):
        return 'stop_loss'
    if expiry - decimal(now, '当前时间', positive=True) <= r['exit_dte'] * 86400:
        return 'expiry'
    if bearish is True:
        return 'bearish_signal'
    return None


def decision(signal, position, bid, now, entry_due, paused=False, rules=None):
    """Pure research-rule decision; an intent grants no network/order authority.

    The runner separately enforces persisted budgets, open-order reconciliation,
    idempotency, quote freshness, quantities, permissions and write-time guards.
    Daily bearish exits apply only at the scheduled daily check. A previously
    latched exit remains the runner's durable intent, outside this pure function.
    """
    try:
        normalized = normalize_rules(rules)
        _stamp(now, '当前时间')
        if not isinstance(entry_due, bool) or not isinstance(paused, bool):
            raise StrategyRuleError('调度或暂停状态未知')
        if (not isinstance(signal, dict) or not isinstance(signal.get('crossover'), bool)
                or not isinstance(signal.get('bearish'), bool)):
            raise StrategyRuleError('已验证日线信号未知')
        if position is not None:
            if not isinstance(position, dict):
                raise StrategyRuleError('已核对持仓未知')
            normalized_position = dict(position)
            if 'size' not in normalized_position and 'quantity' in normalized_position:
                normalized_position['size'] = normalized_position['quantity']
            reason = exit_reason(normalized_position, bid, now,
                                 entry_due and signal['bearish'], normalized)
            return {'action': 'exit_intent' if reason else 'wait',
                    'reason': reason or 'position_held_no_exit'}
        if paused:
            return {'action': 'wait', 'reason': 'entries_paused'}
        if not entry_due:
            return {'action': 'wait', 'reason': 'outside_entry_check'}
        if signal['crossover']:
            return {'action': 'open_intent', 'reason': 'new_daily_crossover'}
        return {'action': 'wait', 'reason': 'no_new_crossover'}
    except StrategyRuleError as error:
        return {'action': 'blocked', 'reason': str(error)}

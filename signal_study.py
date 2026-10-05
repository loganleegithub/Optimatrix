"""Pure, fixed public-price studies. No I/O, models, accounts, or order authority.

Prices are BTC-PERPETUAL USD quote prices, NOT BTC cash flows. Timestamps are
integer Unix milliseconds at bar OPEN. A four-hour bar closes four hours later.
This independent SuperTrend implementation follows TradingView's published
formula; it is not a claimed byte-for-byte clone of the Kivanc script. Squeeze
uses LazyBear's corrected BB multiplier (2.0), not the old 1.5 typo.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from types import MappingProxyType

HOUR_MS = 3_600_000
BAR_MS = 4 * HOUR_MS
STUDY_IDS = ('supertrend', 'squeeze')
_RULES = {
    'schema': 'public_signal_study_v1',
    'instrument': 'BTC-PERPETUAL', 'source': 'Deribit mainnet public hourly OHLC',
    'timeframe_hours': 4, 'bar_clock': 'UTC 00/04/08/12/16/20; completed only',
    'supertrend': {'atr_length': 10, 'atr_method': 'Wilder RMA; SMA seed; first TR high-low',
                   'multiplier': 3.0, 'initial_direction': 'down',
                   'entry': 'confirmed down to up', 'exit': 'confirmed up to down',
                   'source_url': 'https://www.tradingview.com/support/solutions/43000634738-supertrend/'},
    'squeeze': {'length': 20, 'bb_multiplier': 2.0, 'bb_stdev': 'population',
                'kc_multiplier': 1.5, 'kc_range': 'SMA true range; first TR high-low',
                'momentum': 'rolling linear regression endpoint of close minus mean of HL midrange and close SMA',
                'entry': 'previous squeeze on; current squeeze off; momentum > 0',
                'exit': 'momentum <= 0 or momentum < previous momentum',
                'source_url': 'https://pastebin.com/UCpcX8d7'},
    'replay': {'kind': 'unlevered long-only PRICE diagnostic; not futures or options PnL',
               'warmup_bars': 200, 'suggested_evaluation_days': 365,
               'entry_fill': 'next bar open after completed-bar event',
               'signal_exit_fill': 'next bar open', 'initial_stop_atr_multiple': 2.0,
               'stop': 'entry price minus 2 x signal-bar ATR10; fixed, never trailed',
               'stop_fill': 'min(open, stop) if open gaps through; otherwise stop when low reaches it',
               'priority': 'opening gap stop; scheduled open exit; intrabar stop',
               'entry_exit_conflict': 'exit wins; no new entry',
               'same_bar_entry_stop': True, 'pyramiding': False, 'shorting': False,
               'cost_sensitivity_bps_per_side': [10, 25],
               'cost_formula': 'exit*(1-cost)/(entry*(1+cost))-1',
               'excluded': ['funding', 'contract mechanics', 'actual fees', 'liquidity', 'slippage beyond gap stop', 'options pricing'],
               'window': '[start_ms,end_ms); events before start are not executed; no forced final close'},
}
_RULES_JSON = json.dumps(_RULES, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


FIXED_RULES = _freeze(_RULES)
del _RULES


class SignalStudyError(ValueError):
    """Invalid/incomplete data. Callers must report unknown, not reuse old signals."""


def rules_snapshot():
    return json.loads(_RULES_JSON)


def rules_hash():
    return hashlib.sha256(_RULES_JSON.encode()).hexdigest()


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SignalStudyError(f'{name} must be a nonnegative integer millisecond timestamp')
    return value


def _price(value):
    if isinstance(value, bool) or value is None:
        raise SignalStudyError('OHLC values must be finite positive numbers')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise SignalStudyError('OHLC values must be finite positive numbers') from None
    if not math.isfinite(result) or result <= 0:
        raise SignalStudyError('OHLC values must be finite positive numbers')
    return result


def _iso(timestamp):
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError, OSError):
        raise SignalStudyError('Timestamp is outside supported UTC range') from None


def _rows(raw):
    if isinstance(raw, dict):
        if raw.get('status') != 'ok':
            raise SignalStudyError('Hourly source did not return ok')
        fields = ('ticks', 'open', 'high', 'low', 'close')
        if any(not isinstance(raw.get(k), list) for k in fields):
            raise SignalStudyError('Hourly source arrays are missing')
        if len({len(raw[k]) for k in fields}) != 1:
            raise SignalStudyError('Hourly source arrays have different lengths')
        return [dict(zip(('timestamp', 'open', 'high', 'low', 'close'), values))
                for values in zip(*(raw[k] for k in fields))]
    if not isinstance(raw, list):
        raise SignalStudyError('OHLC data must be an array or Deribit chart result')
    return raw


def _validated(raw, interval, now_ms=None):
    if now_ms is not None:
        _integer(now_ms, 'now_ms')
    rows = []
    for source in _rows(raw):
        if not isinstance(source, dict):
            raise SignalStudyError('Malformed OHLC row')
        stamp = _integer(source.get('timestamp', source.get('tick')), 'bar timestamp')
        if stamp % interval:
            raise SignalStudyError('OHLC timestamp is not aligned to the UTC interval')
        if now_ms is not None and stamp > now_ms // interval * interval:
            raise SignalStudyError('OHLC contains a future bar')
        row = {'timestamp': stamp, **{k: _price(source.get(k)) for k in ('open', 'high', 'low', 'close')}}
        if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise SignalStudyError('Invalid OHLC ordering')
        rows.append(row)
    rows.sort(key=lambda row: row['timestamp'])
    if not rows:
        raise SignalStudyError('OHLC data is empty')
    if any(right['timestamp'] - left['timestamp'] != interval for left, right in zip(rows, rows[1:])):
        raise SignalStudyError('OHLC contains duplicate timestamps or missing intervals')
    return rows


def aggregate_hourly(raw, now_ms):
    """Aggregate exactly four contiguous hours; omit only an unfinished final bar.

    Input must start at a UTC four-hour boundary. A completed bar missing even
    one hour is an error. Current in-progress hour/four-hour data may be supplied
    but never contributes to a returned bar. No freshness claim is made here;
    callers must compare the last returned close time with the expected boundary.
    """
    rows = _validated(raw, HOUR_MS, now_ms)
    if rows[0]['timestamp'] % BAR_MS:
        raise SignalStudyError('Hourly data must start at a UTC four-hour boundary')
    result = []
    for index in range(0, len(rows), 4):
        group = rows[index:index + 4]
        start = group[0]['timestamp']
        if start + BAR_MS > now_ms:
            break
        if len(group) != 4:
            raise SignalStudyError('A completed four-hour bar is missing hourly data')
        result.append({'timestamp': start, 'open': group[0]['open'],
                       'high': max(row['high'] for row in group),
                       'low': min(row['low'] for row in group), 'close': group[-1]['close']})
    if not result:
        raise SignalStudyError('No completed four-hour bars')
    return result


def _linreg_endpoint(values):
    count = len(values)
    x_mean = (count - 1) / 2
    y_mean = math.fsum(values) / count
    slope = math.fsum((i - x_mean) * (value - y_mean) for i, value in enumerate(values)) / math.fsum((i - x_mean) ** 2 for i in range(count))
    return y_mean + slope * x_mean


def _analyze_bars(bars, now_ms=None):
    """Return every bar's finite values/events using only that bar and its prefix.

    Supply now_ms when validating externally supplied bars. No internal clock is
    read. Without it, callers promise that bars have already been aggregated by
    aggregate_hourly. Warmup values remain None, not zero or synthetic signals.
    """
    rows = _validated(bars, BAR_MS, now_ms)
    if now_ms is not None and rows[-1]['timestamp'] + BAR_MS > now_ms:
        raise SignalStudyError('Indicator input includes an unfinished four-hour bar')
    output, true_ranges, closes, momentum_inputs = [], [], [], []
    atr = upper = lower = None
    direction = 'down'
    previous_squeeze = None
    previous_momentum = None
    for index, row in enumerate(rows):
        previous_close = rows[index - 1]['close'] if index else None
        tr = row['high'] - row['low']
        if previous_close is not None:
            tr = max(tr, abs(row['high'] - previous_close), abs(row['low'] - previous_close))
        true_ranges.append(tr)
        closes.append(row['close'])
        old_direction, old_atr = direction, atr
        if index == 9:
            atr = math.fsum(true_ranges[:10]) / 10
        elif index > 9:
            atr = atr + (tr - atr) / 10
        if atr is not None:
            midpoint = (row['high'] + row['low']) / 2
            basic_upper, basic_lower = midpoint + 3 * atr, midpoint - 3 * atr
            upper = basic_upper if upper is None or basic_upper < upper or previous_close > upper else upper
            lower = basic_lower if lower is None or basic_lower > lower or previous_close < lower else lower
            if old_atr is None:
                direction = 'down'
            elif old_direction == 'down':
                direction = 'up' if row['close'] > upper else 'down'
            else:
                direction = 'down' if row['close'] < lower else 'up'
        st_entry = old_atr is not None and old_direction == 'down' and direction == 'up'
        st_exit = old_atr is not None and old_direction == 'up' and direction == 'down'
        st = {'ready': atr is not None, 'atr': atr, 'upper_band': upper, 'lower_band': lower,
              'line': (lower if direction == 'up' else upper), 'direction': direction,
              'entry_event': st_entry, 'exit_event': st_exit,
              'event': 'exit' if st_exit else 'entry' if st_entry else 'none'}
        sq = {'ready': False, 'basis': None, 'bb_upper': None, 'bb_lower': None,
              'kc_upper': None, 'kc_lower': None, 'squeeze': None, 'momentum': None,
              'previous_momentum': previous_momentum, 'entry_event': False, 'exit_event': False,
              'event': 'none'}
        squeeze = momentum = None
        if index >= 19:
            window = rows[index - 19:index + 1]
            basis = math.fsum(closes[-20:]) / 20
            stddev = math.sqrt(math.fsum((value - basis) ** 2 for value in closes[-20:]) / 20)
            mean_tr = math.fsum(true_ranges[-20:]) / 20
            bb_upper, bb_lower = basis + 2 * stddev, basis - 2 * stddev
            kc_upper, kc_lower = basis + 1.5 * mean_tr, basis - 1.5 * mean_tr
            sq_on = bb_lower > kc_lower and bb_upper < kc_upper
            sq_off = bb_lower < kc_lower and bb_upper > kc_upper
            squeeze = 'on' if sq_on else 'off' if sq_off else 'neutral'
            midrange = (max(item['high'] for item in window) + min(item['low'] for item in window)) / 2
            momentum_inputs.append(row['close'] - (midrange + basis) / 2)
            if len(momentum_inputs) >= 20:
                momentum = _linreg_endpoint(momentum_inputs[-20:])
            entry = momentum is not None and previous_squeeze == 'on' and sq_off and momentum > 0
            exit_event = momentum is not None and (momentum <= 0 or (previous_momentum is not None and momentum < previous_momentum))
            sq.update(ready=momentum is not None, basis=basis, bb_upper=bb_upper, bb_lower=bb_lower,
                      kc_upper=kc_upper, kc_lower=kc_lower, squeeze=squeeze, momentum=momentum,
                      entry_event=entry, exit_event=exit_event,
                      event='exit' if exit_event else 'entry' if entry else 'none')
        output.append({'timestamp': row['timestamp'], 'closed_at': row['timestamp'] + BAR_MS,
                       'close': row['close'], 'true_range': tr, 'supertrend': st, 'squeeze': sq})
        previous_squeeze, previous_momentum = squeeze, momentum
    try:
        json.dumps(output, allow_nan=False)
    except (ValueError, OverflowError):
        raise SignalStudyError('Indicator arithmetic overflow; values are unknown') from None
    return output


def analyze_bars(bars, now_ms=None):
    """Completed-bar indicator values; see _analyze_bars for warmup conventions."""
    try:
        return _analyze_bars(bars, now_ms)
    except (OverflowError, ZeroDivisionError):
        raise SignalStudyError('Indicator arithmetic overflow; values are unknown') from None


def latest_signals(bars, now_ms=None):
    values = analyze_bars(bars, now_ms)
    last = values[-1]
    return {'rules_hash': rules_hash(), 'instrument': FIXED_RULES['instrument'],
            'bar_count': len(values), 'bar_timestamp': last['timestamp'],
            'closed_at': last['closed_at'], 'closed_at_utc': _iso(last['closed_at']),
            'price': last['close'], 'supertrend': last['supertrend'], 'squeeze': last['squeeze'],
            'authority': 'public signal research only; no trading intent'}


def _net_return(entry, exit_price, bps):
    cost = bps / 10000
    return exit_price * (1 - cost) / (entry * (1 + cost)) - 1


def _replay_one(rows, signals, start_index, strategy_id):
    trades, position = [], None
    for index in range(start_index, len(rows)):
        bar = rows[index]
        # No historical signal is carried across the evaluation boundary.
        previous = signals[index - 1][strategy_id] if index > start_index else None
        exit_price = exit_reason = None
        if position is not None:
            if bar['open'] <= position['stop_price']:
                exit_price, exit_reason = bar['open'], 'stop_gap'
            elif previous and previous['exit_event']:
                exit_price, exit_reason = bar['open'], 'signal_exit'
            elif bar['low'] <= position['stop_price']:
                exit_price, exit_reason = position['stop_price'], 'stop'
        elif previous and previous['entry_event'] and not previous['exit_event']:
            signal_atr = signals[index - 1]['supertrend']['atr']
            stop = bar['open'] - 2 * signal_atr if signal_atr is not None else None
            if stop is not None and 0 < stop < bar['open']:
                position = {'entry_timestamp': bar['timestamp'], 'entry_price': bar['open'],
                            'signal_timestamp': rows[index - 1]['timestamp'],
                            'signal_closed_at': bar['timestamp'], 'signal_atr': signal_atr,
                            'stop_price': stop}
                if bar['low'] <= stop:
                    exit_price, exit_reason = stop, 'stop_same_bar'
        if exit_price is not None:
            intrabar = exit_reason in ('stop', 'stop_same_bar')
            trades.append({**position, 'exit_timestamp': bar['timestamp'],
                           'exit_bar_timestamp': bar['timestamp'],
                           'exit_time_precision': 'bar_only' if intrabar else 'bar_open',
                           'exit_price': exit_price, 'exit_reason': exit_reason,
                           'gross_return': exit_price / position['entry_price'] - 1,
                           'net_return_10bps': _net_return(position['entry_price'], exit_price, 10),
                           'net_return_25bps': _net_return(position['entry_price'], exit_price, 25)})
            position = None
    summary = {'closed_trades': len(trades), 'winning_trades_gross': sum(t['gross_return'] > 0 for t in trades),
               'win_rate_gross': sum(t['gross_return'] > 0 for t in trades) / len(trades) if trades else None,
               'basis': 'closed hypothetical price trades only; open position excluded'}
    for field in ('gross_return', 'net_return_10bps', 'net_return_25bps'):
        summary['compounded_' + field] = math.prod(1 + trade[field] for trade in trades) - 1 if trades else None
    summary['win_rate'] = summary['win_rate_gross']
    summary['gross_compound_return'] = summary['compounded_gross_return']
    summary['cost_scenarios'] = [{'per_side_bps': bps, 'compound_return': summary[f'compounded_net_return_{bps}bps']} for bps in (10, 25)]
    if position is not None:
        last = rows[-1]
        position = {**position, 'mark_timestamp': last['timestamp'] + BAR_MS, 'mark_price': last['close'],
                    'unrealized_gross_price_return': last['close'] / position['entry_price'] - 1,
                    'status': 'open; no forced close; mark is not realized PnL'}
    return {'trades': trades, 'summary': summary, 'open_position': position}


def replay_price_study(bars, start_ms, end_ms, warmup_bars=200):
    """Fixed, unlevered price diagnostic with 200 prewarm bars and explicit window.

    Exactly the 200 bars preceding start seed the indicators. A signal on the
    first evaluation bar can fill on the second; no pre-window signal enters.
    OHLC cannot reveal an intrabar stop timestamp, so its precision is bar_only.
    """
    _integer(start_ms, 'start_ms')
    _integer(end_ms, 'end_ms')
    if start_ms % BAR_MS or end_ms % BAR_MS or end_ms <= start_ms:
        raise SignalStudyError('Evaluation window must use ordered UTC four-hour boundaries')
    if isinstance(warmup_bars, bool) or warmup_bars != 200:
        raise SignalStudyError('Warmup is frozen at 200 bars; no parameter tuning')
    all_rows = _validated(bars, BAR_MS)
    required_start = start_ms - warmup_bars * BAR_MS
    rows = [row for row in all_rows if required_start <= row['timestamp'] < end_ms]
    if not rows or rows[0]['timestamp'] != required_start or rows[-1]['timestamp'] + BAR_MS != end_ms:
        raise SignalStudyError('Evaluation window or its 200-bar warmup is incomplete')
    signals = analyze_bars(rows, end_ms)
    result = {'rules_hash': rules_hash(), 'kind': 'historical_public_price_diagnostic',
              'instrument': FIXED_RULES['instrument'], 'start_ms': start_ms, 'end_ms': end_ms,
              'start_utc': _iso(start_ms), 'end_utc': _iso(end_ms), 'warmup_bars': warmup_bars,
              'evaluation_bars': len(rows) - warmup_bars,
              'limitations': list(FIXED_RULES['replay']['excluded']),
              'strategies': {key: _replay_one(rows, signals, warmup_bars, key) for key in STUDY_IDS}}
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, OverflowError):
        raise SignalStudyError('Replay arithmetic overflow; results are unknown') from None
    return result

import copy
import json
import math
import unittest

from signal_study import (
    BAR_MS, HOUR_MS, FIXED_RULES, SignalStudyError, aggregate_hourly,
    analyze_bars, latest_signals, replay_price_study, rules_hash, rules_snapshot,
    _replay_one,
)


BASE = 1_760_054_400_000 // BAR_MS * BAR_MS


def bar(index, close=100.0, *, width=1.0, interval=BAR_MS):
    return {'timestamp': BASE + index * interval, 'open': close,
            'high': close + width, 'low': close - width, 'close': close}


def flat(count, interval=BAR_MS):
    return [bar(index, interval=interval) for index in range(count)]


class AggregationTest(unittest.TestCase):
    def test_utc_boundaries_and_unfinished_data(self):
        rows = [bar(i, 100 + i, interval=HOUR_MS) for i in range(9)]
        data = aggregate_hourly(rows, BASE + 8 * HOUR_MS + 30_000)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], {'timestamp': BASE, 'open': 100., 'high': 104., 'low': 99., 'close': 103.})
        self.assertEqual(data[-1]['timestamp'], BASE + BAR_MS)
        self.assertEqual(len(aggregate_hourly(rows[:4], BASE + BAR_MS)), 1)
        with self.assertRaises(SignalStudyError):
            aggregate_hourly(rows[:4], BASE + BAR_MS - 1)

    def test_deribit_arrays_and_missing_ohlc(self):
        rows = flat(8, HOUR_MS)
        raw = {'status': 'ok', 'ticks': [r['timestamp'] for r in rows],
               **{key: [r[key] for r in rows] for key in ('open', 'high', 'low', 'close')}}
        self.assertEqual(aggregate_hourly(raw, BASE + 8 * HOUR_MS), aggregate_hourly(rows, BASE + 8 * HOUR_MS))
        raw['low'].pop()
        with self.assertRaises(SignalStudyError):
            aggregate_hourly(raw, BASE + 8 * HOUR_MS)

    def test_reject_duplicates_gaps_future_invalid_prices_and_ohlc(self):
        cases = []
        rows = flat(8, HOUR_MS)
        cases += [rows + [rows[-1]], rows[:3] + rows[4:], rows[1:], rows[:7]]
        cases += [[*rows, bar(9, interval=HOUR_MS)]]
        for field, value in [('timestamp', BASE + 1), ('open', True), ('close', float('nan')),
                             ('high', 99), ('low', 102), ('close', 0), ('high', float('inf'))]:
            changed = copy.deepcopy(rows)
            changed[2][field] = value
            cases.append(changed)
        for rows in cases:
            with self.subTest(rows=rows[-1]):
                with self.assertRaises(SignalStudyError):
                    aggregate_hourly(rows, BASE + 8 * HOUR_MS)

    def test_partial_current_window_allowed_but_missing_completed_hour_rejected(self):
        self.assertEqual(len(aggregate_hourly(flat(6, HOUR_MS), BASE + 6 * HOUR_MS)), 1)
        with self.assertRaises(SignalStudyError):
            aggregate_hourly(flat(6, HOUR_MS), BASE + 8 * HOUR_MS)


class IndicatorTest(unittest.TestCase):
    def test_wilder_seed_ratchet_and_reversals_hand_calculation(self):
        rows = flat(10)
        rows.append({'timestamp': BASE + 10 * BAR_MS, 'open': 100, 'high': 110, 'low': 100, 'close': 110})
        rows.append({'timestamp': BASE + 11 * BAR_MS, 'open': 110, 'high': 110, 'low': 90, 'close': 90})
        result = analyze_bars(rows)
        self.assertIsNone(result[8]['supertrend']['atr'])
        self.assertEqual(result[8]['supertrend']['direction'], 'down')
        self.assertFalse(result[9]['supertrend']['entry_event'])
        self.assertEqual(result[9]['supertrend']['atr'], 2)
        self.assertEqual(result[9]['supertrend']['upper_band'], 106)
        self.assertAlmostEqual(result[10]['supertrend']['atr'], 2.8)
        self.assertAlmostEqual(result[10]['supertrend']['lower_band'], 96.6)
        self.assertEqual(result[10]['supertrend']['upper_band'], 106)
        self.assertEqual(result[10]['supertrend']['event'], 'entry')
        self.assertAlmostEqual(result[11]['supertrend']['atr'], 4.52)
        self.assertAlmostEqual(result[11]['supertrend']['lower_band'], 96.6)
        self.assertEqual(result[11]['supertrend']['event'], 'exit')

    def test_squeeze_population_stdev_corrected_multiplier_and_regression(self):
        values = analyze_bars([bar(i, 100 + i) for i in range(60)])
        squeeze = values[38]['squeeze']
        self.assertAlmostEqual(squeeze['basis'], 128.5)
        self.assertAlmostEqual(squeeze['bb_upper'] - squeeze['basis'], 2 * math.sqrt(33.25))
        self.assertAlmostEqual(squeeze['kc_upper'] - squeeze['basis'], 3)
        self.assertEqual(squeeze['squeeze'], 'off')
        self.assertAlmostEqual(squeeze['momentum'], 9.5)
        self.assertIsNone(values[37]['squeeze']['momentum'])
        self.assertFalse(squeeze['entry_event'])  # No on->off transition in this trend.
        constant = analyze_bars(flat(40))[-1]['squeeze']
        self.assertEqual(constant['squeeze'], 'on')
        self.assertEqual(constant['momentum'], 0)
        self.assertTrue(constant['exit_event'])

    def test_squeeze_release_is_one_event_and_momentum_weakening_exits(self):
        rows = flat(40)
        rows.append({'timestamp': BASE + 40 * BAR_MS, 'open': 100, 'high': 120.5, 'low': 100, 'close': 120})
        rows += [bar(i, 120) for i in range(41, 70)]
        values = analyze_bars(rows)
        self.assertEqual(values[39]['squeeze']['squeeze'], 'on')
        self.assertEqual(values[40]['squeeze']['squeeze'], 'off')
        self.assertTrue(values[40]['squeeze']['entry_event'])
        self.assertGreater(values[40]['squeeze']['momentum'], 0)
        self.assertFalse(values[41]['squeeze']['entry_event'])
        self.assertTrue(any(value['squeeze']['exit_event'] for value in values[42:]))

    def test_strict_squeeze_boundaries_neutral_when_equal(self):
        rows = [{'timestamp': BASE + i * BAR_MS, 'open': 100, 'high': 100, 'low': 100, 'close': 100} for i in range(40)]
        self.assertEqual(analyze_bars(rows)[-1]['squeeze']['squeeze'], 'neutral')

    def test_prefix_invariance_future_cannot_change_past(self):
        rows = [bar(i, 200 + math.sin(i / 9) * 15 + i / 10) for i in range(260)]
        full = analyze_bars(rows)
        for length in (10, 39, 71, 201, 259):
            self.assertEqual(analyze_bars(rows[:length]), full[:length])
        changed = rows[:150] + [bar(i, 1000 + i * 2) for i in range(150, 260)]
        self.assertEqual(analyze_bars(changed)[:150], full[:150])

    def test_latest_is_json_finite_timestamped_and_no_trade_authority(self):
        rows = flat(250)
        latest = latest_signals(rows, BASE + 250 * BAR_MS)
        self.assertEqual(latest['closed_at'], BASE + 250 * BAR_MS)
        self.assertEqual(latest['rules_hash'], rules_hash())
        self.assertIn('no trading', latest['authority'])
        json.dumps(latest, allow_nan=False)
        with self.assertRaises(SignalStudyError):
            latest_signals(rows, BASE + 250 * BAR_MS - 1)
        with self.assertRaises(SignalStudyError):
            analyze_bars(rows[:5] + rows[6:])
        with self.assertRaises(TypeError):
            FIXED_RULES['squeeze']['bb_multiplier'] = 1.5
        editable = rules_snapshot()
        editable['squeeze']['bb_multiplier'] = 1.5
        self.assertEqual(rules_snapshot()['squeeze']['bb_multiplier'], 2.0)


class ReplayTest(unittest.TestCase):
    def _scenario(self, rows, entries=(), exits=(), start_index=0, atr=2):
        signals = [{'supertrend': {'entry_event': i in entries, 'exit_event': i in exits, 'atr': atr}}
                   for i in range(len(rows))]
        return _replay_one(rows, signals, start_index, 'supertrend')

    def test_no_historical_entry_next_open_costs_and_no_pyramiding(self):
        rows = flat(6)
        rows[2] = bar(2, 105)
        rows[3] = bar(3, 106)
        rows[4] = bar(4, 110)
        result = self._scenario(rows, entries=(0, 1, 2), exits=(3,), start_index=1)
        trade = result['trades'][0]
        self.assertEqual(trade['entry_timestamp'], rows[2]['timestamp'])
        self.assertEqual(trade['entry_price'], 105)
        self.assertEqual(trade['exit_timestamp'], rows[4]['timestamp'])
        self.assertEqual(trade['exit_price'], 110)
        self.assertAlmostEqual(trade['gross_return'], 110 / 105 - 1)
        self.assertAlmostEqual(trade['net_return_10bps'], 110 * .999 / (105 * 1.001) - 1)
        self.assertAlmostEqual(trade['net_return_25bps'], 110 * .9975 / (105 * 1.0025) - 1)
        self.assertEqual(len(result['trades']), 1)

    def test_stop_gap_and_partial_bar_precision(self):
        rows = flat(4)
        rows[2] = bar(2, 90)
        result = self._scenario(rows, entries=(0,))
        trade = result['trades'][0]
        self.assertEqual(trade['stop_price'], 96)
        self.assertEqual(trade['exit_price'], 90)
        self.assertEqual(trade['exit_reason'], 'stop_gap')
        self.assertEqual(trade['exit_time_precision'], 'bar_open')
        rows[2] = {'timestamp': rows[2]['timestamp'], 'open': 100, 'high': 102, 'low': 94, 'close': 100}
        trade = self._scenario(rows, entries=(0,))['trades'][0]
        self.assertEqual(trade['exit_price'], 96)
        self.assertEqual(trade['exit_reason'], 'stop')
        self.assertEqual(trade['exit_time_precision'], 'bar_only')

    def test_same_bar_stop_and_signal_exit_precedes_later_low(self):
        rows = flat(4)
        rows[1]['low'] = 90
        trade = self._scenario(rows, entries=(0,))['trades'][0]
        self.assertEqual(trade['exit_reason'], 'stop_same_bar')
        rows[1]['low'] = 99
        rows[2]['low'] = 90
        trade = self._scenario(rows, entries=(0,), exits=(1,))['trades'][0]
        self.assertEqual(trade['exit_reason'], 'signal_exit')
        self.assertEqual(trade['exit_price'], 100)
        rows[2] = bar(2, 90)
        trade = self._scenario(rows, entries=(0,), exits=(1,))['trades'][0]
        self.assertEqual(trade['exit_reason'], 'stop_gap')

    def test_open_position_separate_and_entry_exit_conflict(self):
        rows = flat(4)
        result = self._scenario(rows, entries=(0,))
        self.assertEqual(result['trades'], [])
        self.assertIsNone(result['summary']['compounded_gross_return'])
        self.assertEqual(result['open_position']['mark_timestamp'], BASE + 4 * BAR_MS)
        self.assertIsNone(self._scenario(rows, entries=(0,), exits=(0,))['open_position'])

    def test_window_prewarm_and_future_exclusion(self):
        rows = [bar(i, 200 + 15 * math.sin(i / 10)) for i in range(310)]
        start, end = BASE + 200 * BAR_MS, BASE + 300 * BAR_MS
        result = replay_price_study(rows, start, end)
        self.assertEqual(result['evaluation_bars'], 100)
        self.assertEqual(result, replay_price_study(rows[:300], start, end))
        self.assertEqual(result['kind'], 'historical_public_price_diagnostic')
        json.dumps(result, allow_nan=False)
        for invalid in (rows[1:], rows[:299], rows[:220] + rows[221:]):
            with self.assertRaises(SignalStudyError):
                replay_price_study(invalid, start, end)
        with self.assertRaises(SignalStudyError):
            replay_price_study(rows, start, end, warmup_bars=100)


if __name__ == '__main__':
    unittest.main()

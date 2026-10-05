"""Synthetic offline economic-rule checks; these fixtures are not market evidence."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from strategies import StrategyError, StrategyService, normalize_spec
from strategy import (DEFAULT_RULES, KIND, StrategyRuleError, default_spec,
                      decision, evaluate_signal, exit_reason, normalize_rules, price_step,
                      select_contract, size_order, validate_exit_bid, validate_quote)

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc).timestamp()
DAY = int(NOW // 86400) * 86400


def candles(last=120):
    return {'status': 'ok', 'ticks': [(DAY - (61-i) * 86400) * 1000 for i in range(61)],
            'close': [100] * 60 + [last]}


def instrument(name='synthetic-call', days=30, strike=100000, **changes):
    return dict({'instrument_name': name, 'kind': 'option', 'instrument_type': 'reversed',
        'base_currency': 'BTC', 'quote_currency': 'BTC', 'settlement_currency': 'BTC',
        'counter_currency': 'USD', 'price_index': 'btc_usd', 'option_type': 'call',
        'is_active': True, 'contract_size': 1, 'strike': strike,
        'expiration_timestamp': int((NOW + days * 86400) * 1000),
        'min_trade_amount': 0.1, 'tick_size': 0.0001}, **changes)


def book(**changes):
    return dict({'instrument_name': 'synthetic-call', 'timestamp': NOW * 1000,
        'state': 'open', 'best_bid_price': 0.01, 'best_ask_price': 0.011,
        'best_bid_amount': 1, 'best_ask_amount': 1}, **changes)


class TrendRuleTests(unittest.TestCase):
    def test_crossover_uses_completed_consecutive_utc_days(self):
        data = candles()
        result = evaluate_signal(data, NOW)
        self.assertTrue(result['crossover'])
        self.assertFalse(result['bearish'])
        self.assertEqual(result['bar_count'], 61)
        self.assertEqual(result['bar_date'], '2026-10-04')
        self.assertEqual(result['previous_fast'], result['previous_slow'])
        # Today's unfinished bar does not affect the signal or evidence hash.
        data['ticks'].append(DAY * 1000)
        data['close'].append(1)
        self.assertEqual(evaluate_signal(data, NOW), result)
        self.assertEqual(evaluate_signal(candles(), DAY), result)

    def test_already_rising_is_not_new_crossover_and_equal_is_bearish(self):
        data = candles(130)
        data['close'][-2] = 120
        self.assertFalse(evaluate_signal(data, NOW)['crossover'])
        self.assertTrue(evaluate_signal(candles(100), NOW)['bearish'])

    def test_gaps_duplicates_bad_prices_future_and_non_utc_bars_block(self):
        for mutation in ('gap', 'duplicate', 'bad_price', 'future', 'shift', 'stale'):
            data = candles()
            if mutation == 'gap':
                data['ticks'].pop(20); data['close'].pop(20)
            elif mutation == 'duplicate':
                data['ticks'].append(data['ticks'][-1]); data['close'].append(100)
            elif mutation == 'bad_price':
                data['close'][0] = 'NaN'
            elif mutation == 'future':
                data['ticks'].append((DAY+86400)*1000); data['close'].append(100)
            elif mutation == 'shift':
                data['ticks'][0] += 3600000
            else:
                data['ticks'] = [t-86400000 for t in data['ticks']]
            with self.subTest(mutation=mutation), self.assertRaises(StrategyRuleError):
                evaluate_signal(data, NOW)

    def test_contract_selection_checks_economic_metadata_and_tie_rules(self):
        candidates = [instrument('later', 31, 100000), instrument('higher', 29, 101000),
                      instrument('lower', 29, 99000), instrument('fake', 30, 100000, settlement_currency='USDC')]
        selected, test = select_contract(candidates, candidates, 100000, NOW)
        self.assertEqual(selected['instrument_name'], 'lower')
        self.assertEqual(test, selected)
        with self.assertRaises(StrategyRuleError):
            select_contract(candidates, [candidates[0]], 100000, NOW)
        with self.assertRaises(StrategyRuleError):
            select_contract([instrument()], [instrument(min_trade_amount=None)], 100000, NOW)

    def test_quote_freshness_depth_and_spread(self):
        self.assertEqual(validate_quote(book(), NOW, NOW, '.10'), (Decimal('.01'), Decimal('.011')))
        for changes, received in [({'timestamp': (NOW-31)*1000}, NOW), ({}, NOW-16),
            ({'timestamp': (NOW+6)*1000}, NOW), ({'best_bid_amount': 0}, NOW),
            ({'best_ask_price': .012}, NOW), ({'best_bid_price': None}, NOW),
            ({'state': 'closed'}, NOW), ({'best_bid_price': .012}, NOW)]:
            with self.subTest(changes=changes,received=received), self.assertRaises(StrategyRuleError):
                validate_quote(book(**changes), received, NOW, '.10')

    def test_exit_requires_only_fresh_bid_but_entry_still_requires_both_sides(self):
        bid_only = book(best_ask_price=None,best_ask_amount=0)
        self.assertEqual(validate_exit_bid(bid_only,NOW,NOW),Decimal('.01'))
        with self.assertRaises(StrategyRuleError):
            validate_quote(bid_only,NOW,NOW,'.10')
        for changes,received in [({'best_bid_price':None},NOW),({'best_bid_amount':0},NOW),
                ({'state':'closed'},NOW),({'timestamp':(NOW-31)*1000},NOW),
                ({'timestamp':(NOW+6)*1000},NOW),({},NOW-16)]:
            with self.subTest(changes=changes,received=received), self.assertRaises(StrategyRuleError):
                validate_exit_bid(dict(bid_only,**changes),received,NOW)

    def test_decimal_budget_reserves_both_sides_and_rounds_down(self):
        meta = instrument()
        qty = size_order(meta, '.01', '1', '1', '.0003')
        self.assertEqual(qty, Decimal('.9'))
        self.assertLessEqual(qty * Decimal('.0106'), Decimal('.01'))
        self.assertEqual(size_order(meta, '.01', '1', '.002', '.0003'), Decimal('.1'))
        self.assertEqual(size_order(meta, '.01', '.001', '1', '.0003'), 0)
        for fee in [None, 0, -1, 'NaN']:
            with self.assertRaises(StrategyRuleError):
                size_order(meta, '.01', 1, 1, fee)
        with self.assertRaises(StrategyRuleError):
            size_order(meta, '.01005', 1, 1, '.0003')
        with self.assertRaises(StrategyRuleError):
            size_order(instrument(contract_size=10), '.01', 1, 1, '.0003')

    def test_tick_bands_and_actual_fill_exit_rules(self):
        meta = instrument(tick_size_steps=[{'above_price': .005, 'tick_size': .0005}])
        self.assertEqual(price_step(meta, '.005'), Decimal('.0005'))
        pos = {'size': '.2', 'average_price': '.01', 'expiration_timestamp': (NOW + 30*86400)*1000}
        self.assertEqual(exit_reason(pos, '.007', NOW, False), 'stop_loss')
        self.assertIsNone(exit_reason(pos, '.008', NOW, False))
        self.assertEqual(exit_reason(pos, '.008', NOW, True), 'bearish_signal')
        pos['expiration_timestamp'] = (NOW + 7*86400)*1000
        self.assertEqual(exit_reason(pos, '.008', NOW, False), 'expiry')
        pos['size'] = 0
        self.assertIsNone(exit_reason(pos, '.008', NOW, True))

    def test_rule_validation_prevents_risk_expansion_and_silent_condition_loss(self):
        spec = default_spec()
        self.assertEqual(normalize_spec(spec), spec)
        for change in [{'equity_fraction': '.02'}, {'stop_loss_ratio': None}, {'max_orders_per_day': 5},
                       {'fast_days': 60}, {'signal_instrument': 'ETH-PERPETUAL'}, {'unknown': 1}]:
            with self.subTest(change=change), self.assertRaises(StrategyRuleError):
                normalize_rules(change)
        with self.assertRaises(StrategyError):
            normalize_spec(dict(spec, entry='另外可以手动追涨'))

    def test_pure_decision_has_all_four_states_and_pause_does_not_disable_exit(self):
        signal = evaluate_signal(candles(), NOW)
        self.assertEqual(decision(signal,None,None,NOW,False)['action'],'wait')
        self.assertEqual(decision(signal,None,None,NOW,True)['action'],'open_intent')
        self.assertEqual(decision(signal,None,None,NOW,True,paused=True)['action'],'wait')
        self.assertEqual(decision(None,None,None,NOW,True)['action'],'blocked')
        position = {'quantity': '.2','average_price':'.01','expiration_timestamp':(NOW+30*86400)*1000}
        self.assertEqual(decision(signal,position,'.007',NOW,False,paused=True),
                         {'action':'exit_intent','reason':'stop_loss'})
        bearish = dict(signal,crossover=False,bearish=True)
        self.assertEqual(decision(bearish,position,'.009',NOW,False)['action'],'wait')
        self.assertEqual(decision(bearish,position,'.009',NOW,True),
                         {'action':'exit_intent','reason':'bearish_signal'})


class TrendVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = StrategyService(Path(self.temp.name), object())

    def tearDown(self):
        self.temp.cleanup()

    def create(self, spec=None):
        data = self.service.create({'name': '离线趋势案例', 'idea': '用于确定性离线验证',
                                    'spec': spec or default_spec()})
        return data['strategy']['strategy_id'], data['versions'][0]['version_id']

    def test_capabilities_cannot_route_trend_into_greeks_and_export_is_deterministic(self):
        sid, vid = self.create()
        version = self.service.detail(sid)['versions'][0]
        self.assertTrue(version['can_run_testnet'])
        self.assertFalse(version['can_validate'])
        with self.assertRaises(StrategyError):
            self.service._params(version, {})
        result = self.service.export_spec(sid, vid)
        self.assertEqual(result, self.service.export_spec(sid, vid))
        for term in ['BTC-PERPETUAL', 'STOP', 'reduce_only', '权利金全部损失', '尚未建立可交易优势', vid]:
            self.assertIn(term, result)

    def test_confirmation_hash_binding_and_frozen_identity_are_separate(self):
        sid, vid = self.create()
        original = self.service.detail(sid)['versions'][0]['spec']
        self.service.confirm_onboarding(sid, vid, {'keys': ['fast_days']})
        self.assertFalse(self.service.detail(sid)['versions'][0]['onboarding_complete'])
        self.service.confirm_onboarding(sid, vid, {'use_defaults': True})
        self.assertTrue(self.service.detail(sid)['versions'][0]['onboarding_complete'])
        self.service.update_version(sid, vid, {'spec': {'kind': KIND, 'rules': dict(DEFAULT_RULES, fast_days=15)}})
        self.assertFalse(self.service.detail(sid)['versions'][0]['onboarding_complete'])
        self.service.confirm_onboarding(sid, vid, {'use_defaults': True})
        self.service.freeze_version(sid, vid)
        before = self.service.detail(sid)['versions'][0]
        self.service.confirm_onboarding(sid, vid, {'keys': ['fast_days']})
        after = self.service.detail(sid)['versions'][0]
        self.assertEqual(before['rules_sha256'], after['rules_sha256'])
        self.assertEqual(before['spec'], after['spec'])
        self.assertNotEqual(original, after['spec'])
        with self.assertRaises(StrategyError):
            self.service.update_version(sid, vid, {'spec': default_spec()})

    def test_old_frozen_greeks_record_is_not_normalized_or_rehashed(self):
        rules = {'session_bucket': '09:00:00', 'entry_weekdays': [0], 'option_type': 'call',
                 'delta': .5, 'expiry': 7, 'quantity': .01}
        sid, vid = self.create({'kind': 'greeks_single_long', 'rules': rules})
        self.service.freeze_version(sid, vid)
        before = copy.deepcopy(self.service.data['versions'][0])
        self.create()
        restored = StrategyService(Path(self.temp.name), object())
        after = restored.data['versions'][0]
        self.assertEqual(before, after)
        self.assertTrue(restored.detail(sid)['versions'][0]['can_validate'])
        self.assertFalse(restored.detail(sid)['versions'][0]['can_run_testnet'])
        expected = hashlib.sha256(json.dumps(before['spec'], ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(expected, before['rules_sha256'])


if __name__ == '__main__':
    unittest.main()

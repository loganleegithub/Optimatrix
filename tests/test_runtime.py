"""Offline testnet lifecycle simulation. No network or real account is accessed."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime
from runtime import RuntimeErrorState, StrategyRuntimeService
from strategies import StrategyService
from strategy import default_spec
from testnet import TestnetError

NOW = datetime(2026, 10, 5, 7, 59, 30, tzinfo=timezone.utc).timestamp()


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def metadata(now):
    return {'instrument_name': 'offline-only-call', 'kind': 'option', 'option_type': 'call',
        'instrument_type': 'reversed', 'base_currency': 'BTC', 'quote_currency': 'BTC',
        'settlement_currency': 'BTC', 'counter_currency': 'USD', 'price_index': 'btc_usd',
        'state': 'open', 'is_active': True, 'contract_size': 1, 'strike': 100000,
        'expiration_timestamp': int((now+30*86400)*1000), 'min_trade_amount': .1,
        'tick_size': .0001, 'tick_size_steps': [], 'maker_commission': .0003, 'taker_commission': .0003}


class Market:
    def __init__(self, clock, meta):
        self.clock, self.meta, self.cross = clock, meta, True
        self.calls = []
        self.bid, self.ask = '.0095', '.01'

    def candles(self, now, days=63):
        self.calls.append('candles')
        day = int(now//86400)*86400
        return {'result': {'status': 'ok', 'ticks': [(day-(61-i)*86400)*1000 for i in range(61)],
                           'close': [100]*60+[110 if self.cross else 100]},
                'received_at': self.clock(), 'source_at': self.clock()}

    def index(self):
        self.calls.append('index')
        return {'result': {'index_price': 100000}, 'received_at': self.clock(), 'source_at': self.clock()}

    def instruments(self):
        self.calls.append('instruments')
        return [copy.deepcopy(self.meta)]

    def book(self, name):
        self.calls.append('book')
        return quote(name, self.clock(), self.bid, self.ask)

    def close(self):
        pass


def quote(name, now, bid, ask):
    return {'result': {'instrument_name': name, 'state': 'open', 'timestamp': now*1000,
                      'best_bid_price': bid, 'best_ask_price': ask,
                      'best_bid_amount': 100, 'best_ask_amount': 100},
            'received_at': now, 'source_at': now}


class Client:
    configured = True

    def __init__(self, clock, meta):
        self.clock, self.meta = clock, meta
        self.calls, self.writes = [], []
        self.orders, self.trades, self.positions = {}, [], {}
        self.bid, self.ask = '.0095', '.01'
        self.fail_buy = False
        self.uncertain_accepted = False
        self.hide_order_history = False
        self.account_offset = 0

    def authenticate(self):
        self.calls.append('authenticate')

    def account_snapshot(self, since):
        self.calls.append('account_snapshot')
        orders = list(copy.deepcopy(self.orders).values())
        return {'complete': True, 'account_id': 'offline-test-account',
            'summary': {'currency': 'BTC', 'equity': 1, 'available_funds': 1,
                        'cross_collateral_enabled': False, 'fees': {}},
            'positions': [{'instrument_name': k, 'size': str(v), 'direction': 'buy' if v>0 else 'sell'}
                          for k, v in self.positions.items() if v],
            'open_orders': [] if self.hide_order_history else [o for o in orders if o['order_state']=='open'],
            'orders': [] if self.hide_order_history else orders, 'trades': copy.deepcopy(self.trades),
            'observed_at': self.clock()+self.account_offset, 'since_ms': since,
            'source_at': self.clock(), 'through_ms': int(self.clock()*1000), 'environment': 'testnet'}

    def get_instruments(self):
        self.calls.append('get_instruments')
        return [copy.deepcopy(self.meta)]

    def get_order_book(self, name):
        self.calls.append('get_order_book')
        return quote(name, self.clock(), self.bid, self.ask)

    def _write(self, direction, name, amount, price, label):
        self.calls.append(direction)
        self.writes.append({'direction':direction, 'name':name, 'amount':str(amount), 'price':str(price), 'label':label})
        oid = str(len(self.writes))
        order = {'order_id':oid, 'label':label, 'direction':direction, 'instrument_name':name,
                 'amount':str(amount), 'price':str(price), 'filled_amount':'0', 'order_state':'open',
                 'reduce_only': direction=='sell'}
        if not self.fail_buy or direction!='buy' or self.uncertain_accepted:
            self.orders[oid] = order
        if self.fail_buy and direction=='buy':
            raise TestnetError('离线模拟：提交结果未知', uncertain=True)
        return {'order':copy.deepcopy(order), 'trades':[]}

    def buy(self, name, amount, price, label, validity_deadline=None, preflight=None):
        if preflight:
            preflight()
        if validity_deadline is not None and self.clock() >= validity_deadline:
            raise TestnetError('离线模拟：写请求超过数据时效')
        return self._write('buy', name, amount, price, label)

    def sell(self, name, amount, price, label, reduce_only=True, validity_deadline=None, preflight=None):
        if preflight:
            preflight()
        if reduce_only is not True:
            raise AssertionError('exit must be reduce-only')
        if validity_deadline is not None and self.clock() >= validity_deadline:
            raise TestnetError('离线模拟：写请求超过数据时效')
        return self._write('sell', name, amount, price, label)

    def cancel(self, oid, preflight=None):
        if preflight:
            preflight()
        self.calls.append('cancel')
        self.orders[oid]['order_state'] = 'cancelled'
        return copy.deepcopy(self.orders[oid])

    def get_order_state(self, oid):
        self.calls.append('get_order_state')
        return copy.deepcopy(self.orders.get(oid))

    def orders_by_label(self, label):
        self.calls.append('orders_by_label')
        return [copy.deepcopy(o) for o in self.orders.values() if o['label']==label]

    def fill(self, oid, amount, price=None):
        order = self.orders[oid]
        amount, price = Decimal(str(amount)), Decimal(str(price or order['price']))
        order['filled_amount'] = str(Decimal(order['filled_amount'])+amount)
        if Decimal(order['filled_amount']) == Decimal(order['amount']):
            order['order_state'] = 'filled'
        name, direction = order['instrument_name'], order['direction']
        self.positions[name] = self.positions.get(name,Decimal(0))+(amount if direction=='buy' else -amount)
        self.trades.append({'trade_id':str(len(self.trades)+1), 'order_id':oid, 'instrument_name':name,
            'direction':direction, 'amount':str(amount), 'price':str(price), 'fee':'0.00003',
            'fee_currency':'BTC', 'timestamp':int(self.clock()*1000)})

    def close(self):
        pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.meta = metadata(self.clock())
        self.client, self.market = Client(self.clock, self.meta), Market(self.clock, self.meta)
        self.strategies = StrategyService(self.root, object())
        detail = self.strategies.create({'name':'离线模拟', 'idea':'专用离线 fixture，无市场证据', 'spec':default_spec()})
        self.sid, self.vid = detail['strategy']['strategy_id'], detail['versions'][0]['version_id']
        self.strategies.confirm_onboarding(self.sid,self.vid,{'use_defaults':True})
        self.service = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        view = self.service.create({'strategy_id':self.sid,'version_id':self.vid,
                                    'approved':True,'idempotency_key':'offline-run-0001'})
        self.rid = view['run_id']
        self.run = self.service.runs[self.rid]

    def tearDown(self):
        self.temp.cleanup()

    def due(self):
        self.clock.value = int(self.clock.value//86400)*86400+8*3600+1
        self.service.tick()

    def open_position(self, amount=None):
        self.due()
        self.assertEqual(len(self.client.writes),1,self.run['last_cycle'])
        self.client.fill('1',amount or self.client.writes[0]['amount'])
        self.clock.value += 15
        self.service.tick()

    def test_initial_signal_does_not_trade_outside_window_and_due_orders_once(self):
        self.service.tick()
        self.assertTrue(self.run['signal']['crossover'])
        self.assertFalse(self.client.writes)
        self.due()
        self.assertEqual(len(self.client.writes),1,self.run['last_cycle'])
        self.assertEqual(self.client.writes[0]['amount'],'0.9')
        self.assertEqual(self.run['counts']['2026-10-05'],{'orders':1,'entries':1})
        for _ in range(3):
            self.clock.value += 15
            self.service.tick()
        self.assertEqual(len(self.client.writes),1)
        self.assertEqual(self.run['consumed_signals'],['2026-10-04'])

    def test_due_without_crossover_and_missed_window_never_orders(self):
        self.market.cross = False
        self.due()
        self.assertFalse(self.client.writes)
        self.market.cross = True
        self.clock.value += 86400+61
        self.service.tick()
        self.assertFalse(self.client.writes)

    def test_restart_requires_explicit_resume_and_never_replays_consumed_signal(self):
        self.due()
        restored = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        self.assertIsNone(restored.active_id)
        restored.tick()
        self.assertEqual(len(self.client.writes),1)
        view = restored.operate(self.rid,'resume')
        self.assertFalse(view['resume_required'])
        self.clock.value += 15
        restored.tick()
        self.assertEqual(len(self.client.writes),1)

    def test_partial_fill_timeout_cancels_remainder_and_exit_uses_actual_quantity(self):
        self.open_position('.4')
        self.assertEqual(self.run['position']['quantity'],'0.4')
        self.assertEqual(Decimal(self.run['ledger']['open_premium_cost_btc']),Decimal('.004'))
        self.assertEqual(Decimal(self.run['ledger']['actual_fees_btc']),Decimal('.00003'))
        self.assertEqual(Decimal(self.run['ledger']['cash_flow_btc']),Decimal('-.00403'))
        self.clock.value += 300
        self.service.tick()
        self.assertEqual(self.client.calls.count('cancel'),1,self.run['last_cycle'])
        self.assertEqual(self.run['intents'][0]['status'],'cancel_unknown')
        self.clock.value += 15
        self.client.bid, self.client.ask = '.006', '.0061'
        self.service.tick()
        self.assertEqual(len(self.client.writes),2,self.run['last_cycle'])
        sale = self.client.writes[-1]
        self.assertEqual((sale['direction'],sale['amount']),('sell','0.4'))
        self.assertTrue(self.client.orders['2']['reduce_only'])
        self.client.fill('2','.4')
        self.clock.value += 15
        self.service.tick()
        self.assertIsNone(self.run['position'])
        self.assertEqual(len(self.run['trades']),2)
        self.assertEqual(Decimal(self.run['ledger']['realized_pnl_btc']),Decimal('-.00166'))
        self.assertEqual(Decimal(self.run['ledger']['cash_flow_btc']),Decimal('-.00166'))
        self.assertEqual(Decimal(self.run['ledger']['actual_fees_btc']),Decimal('.00006'))

    def test_unknown_submission_no_resend_even_after_restart_and_new_day(self):
        self.client.fail_buy = True
        self.due()
        self.assertEqual(self.run['intents'][0]['status'],'submission_unknown')
        self.clock.value += 86400
        self.service.tick()
        self.assertEqual(len(self.client.writes),1)
        self.assertEqual(self.run['status'],'reconciliation_required')
        restored = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        with self.assertRaises(RuntimeErrorState):
            restored.operate(self.rid,'resume')
        self.assertEqual(len(self.client.writes),1)

    def test_unknown_response_found_by_label_or_history_does_not_resubmit(self):
        self.client.fail_buy, self.client.uncertain_accepted = True, True
        self.due()
        self.client.hide_order_history = True
        self.clock.value += 15
        self.service.tick()
        self.assertIn('orders_by_label',self.client.calls)
        self.assertEqual(self.run['intents'][0]['order_id'],'1')
        self.assertEqual(len(self.client.writes),1)
        self.client.hide_order_history = False
        self.client.fill('1','.9')
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['position']['quantity'],'0.9')
        self.assertEqual(len(self.client.writes),1)

    def test_daily_cap_prevents_submit_and_stop_does_not_query_or_cancel(self):
        self.run['counts']['2026-10-05'] = {'orders':4,'entries':0}
        self.due()
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['status'],'blocked')
        (self.root/'STOP').touch()
        calls, market_calls = list(self.client.calls),list(self.market.calls)
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.client.calls,calls)
        self.assertEqual(self.market.calls,market_calls)
        self.assertEqual(self.run['status'],'halted_stop_file')

    def test_external_position_fails_closed_without_selling_it(self):
        self.client.positions['some-external-instrument'] = Decimal('.2')
        self.due()
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['status'],'blocked')
        self.assertIn('外部持仓',self.run['last_cycle']['reason'])

    def test_persistence_failure_prevents_transaction_and_stays_blocked(self):
        original = runtime.save_json
        def fail_intent(path, payload):
            if Path(path).name=='run.json' and payload.get('intents'):
                raise OSError('synthetic disk failure')
            return original(path,payload)
        with patch('runtime.save_json',side_effect=fail_intent):
            self.due()
        self.assertFalse(self.client.writes)
        self.assertIsNotNone(self.service.storage_error)
        self.clock.value += 15
        self.service.tick()
        self.assertFalse(self.client.writes)

    def test_trade_id_duplicate_does_not_double_count_and_changed_fill_blocks(self):
        self.open_position()
        original = copy.deepcopy(self.run['trades'])
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['trades'],original)
        self.assertEqual(self.run['position']['quantity'],'0.9')
        self.client.trades[0]['price'] = '.02'
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['status'],'blocked')
        self.assertIn('历史成交内容发生变化',self.run['last_cycle']['reason'])
        self.assertEqual(self.run['trades'],original)

    def test_unknown_previous_run_blocks_new_run_even_with_empty_broker_snapshot(self):
        self.client.fail_buy = True
        self.due()
        restored = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        with self.assertRaises(RuntimeErrorState):
            restored.create({'strategy_id':self.sid,'version_id':self.vid,
                             'approved':True,'idempotency_key':'offline-run-new-attempt'})
        self.assertEqual(len(self.client.writes),1)

    def test_unowned_trades_after_start_block_even_when_they_net_to_flat(self):
        for index,direction in enumerate(('buy','sell')):
            self.client.trades.append({'trade_id':'external-'+str(index),'order_id':'unowned-order-'+str(index),
                'instrument_name':self.meta['instrument_name'],'direction':direction,'amount':'.1','price':'.01',
                'fee':'0.00003','fee_currency':'BTC','timestamp':self.run['created_ms']+1000+index})
        self.due()
        self.assertFalse(self.client.writes,self.run['last_cycle'])
        self.assertEqual(self.run['status'],'blocked')

    def test_reopened_same_contract_uses_current_lot_cost_not_previous_closed_lot(self):
        self.due()
        template = copy.deepcopy(self.run['intents'][0])
        self.run['intents'], self.client.orders, self.client.positions = [],{},{}
        for index,(direction,amount,price) in enumerate([('buy','.5','.01'),('sell','.5','.012'),('buy','.2','.02')],1):
            oid, label = str(index),'offline-lot-'+str(index)
            self.run['intents'].append(dict(template,order_id=oid,label=label,direction=direction,
                amount=amount,price=price,filled_amount='0',status='accepted',reduce_only=direction=='sell'))
            self.client.orders[oid] = {'order_id':oid,'label':label,'direction':direction,
                'instrument_name':self.meta['instrument_name'],'amount':amount,'price':price,
                'filled_amount':'0','order_state':'open','reduce_only':direction=='sell'}
            self.clock.value += 1
            self.client.fill(oid,amount,price)
        self.service._reconcile(self.run,self.client.account_snapshot(self.run['created_ms']))
        self.assertEqual(self.run['position']['quantity'],'0.2')
        self.assertEqual(Decimal(self.run['position']['average_price']),Decimal('.02'))

    def test_order_price_changed_outside_runtime_fails_closed(self):
        self.due()
        self.client.orders['1']['price'] = '.05'
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['status'],'blocked',self.run['last_cycle'])

    def test_unknown_cancel_blocks_replacement_and_never_automatically_repeats_cancel(self):
        self.open_position('.4')
        def uncertain_cancel(oid, preflight=None):
            if preflight:
                preflight()
            self.client.calls.append('cancel')
            raise TestnetError('离线模拟：撤单结果未知',uncertain=True)
        self.client.cancel = uncertain_cancel
        self.clock.value += 300
        self.service.tick()
        self.assertEqual(self.run['intents'][0]['status'],'cancel_unknown')
        self.client.bid, self.client.ask = '.006', '.0061'
        for _ in range(3):
            self.clock.value += 15
            self.service.tick()
        self.assertEqual(self.client.calls.count('cancel'),1)
        self.assertEqual(len(self.client.writes),1)
        self.assertEqual(self.run['status'],'reconciliation_required')

    def test_stop_appearing_after_intent_persistence_blocks_actual_write(self):
        original = self.service._save
        def stop_after_save(run):
            original(run)
            if run['intents']:
                (self.root/'STOP').touch()
        with patch.object(self.service,'_save',side_effect=stop_after_save):
            self.due()
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['counts']['2026-10-05']['orders'],1)
        self.assertEqual(self.run['intents'][0]['status'],'rejected')

    def test_aged_unknown_order_recovers_from_history_without_label_or_resubmission(self):
        self.client.fail_buy, self.client.uncertain_accepted = True,True
        self.due()
        self.client.orders_by_label = lambda label: []  # Recent-label lookup cannot find this old order.
        self.client.fill('1','.9')
        self.clock.value += 3600
        self.service.tick()
        self.assertEqual(self.run['intents'][0]['status'],'filled')
        self.assertEqual(self.run['position']['quantity'],'0.9')
        self.assertEqual(len(self.client.writes),1)

    def test_future_account_snapshot_cannot_authorize_order(self):
        self.client.account_offset = 6
        self.due()
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['status'],'blocked')

    def test_foreground_market_failure_logs_unknown_current_price_and_no_trade(self):
        self.service.tick()
        previous = copy.deepcopy(self.run['signal'])
        self.assertEqual(self.run['last_cycle']['prices']['signal_index_usd'],100000)
        with patch.object(self.market,'index',side_effect=TestnetError('离线模拟：主网公共行情不可取得')):
            self.due()
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['status'],'blocked')
        self.assertIsNone(self.run['last_cycle']['prices']['signal_index_usd'])
        self.assertEqual(self.run['last_cycle']['price_status'],'not_retrieved')
        self.assertEqual(self.run['last_cycle']['signal'],previous)

    def test_daily_bearish_exit_survives_pending_entry_cancellation(self):
        self.open_position('.4')
        self.clock.value = int(self.clock.value//86400)*86400+86400+8*3600+1
        self.market.cross = False
        self.service.tick()
        self.assertEqual(self.run['last_cycle']['decision'],'cancel_intent')
        self.assertEqual(self.run['exit_intent']['reason'],'bearish_signal')
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.client.writes[-1]['direction'],'sell',self.run['last_cycle'])
        self.assertEqual(self.client.writes[-1]['amount'],'0.4')
        self.assertEqual(self.run['last_cycle']['reason'],'bearish_signal')

    def test_partial_exit_allocates_actual_entry_fee_and_retains_open_cost(self):
        self.open_position('.4')
        self.clock.value += 300
        self.service.tick()
        self.clock.value += 15
        self.client.bid, self.client.ask = '.006','.0061'
        self.service.tick()
        self.client.fill('2','.2')
        self.clock.value += 15
        self.service.tick()
        ledger = self.run['ledger']
        self.assertEqual(self.run['position']['quantity'],'0.2')
        self.assertEqual(Decimal(ledger['actual_fees_btc']),Decimal('.00006'))
        self.assertEqual(Decimal(ledger['open_premium_cost_btc']),Decimal('.002'))
        self.assertEqual(Decimal(ledger['open_entry_fees_btc']),Decimal('.000015'))
        self.assertEqual(Decimal(ledger['realized_pnl_btc']),Decimal('-.000845'))

    def test_maker_fill_accounts_using_owned_order_side_not_taker_side(self):
        self.due()
        self.client.fill('1','.9')
        self.client.trades[-1]['direction'] = 'sell'
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['position']['quantity'],'0.9',self.run['last_cycle'])
        self.assertEqual(self.run['trades']['1']['direction'],'buy')
        self.assertEqual(self.run['trades']['1']['reported_direction'],'sell')

    def test_changed_label_reduce_only_or_invalid_fee_block_reconciliation(self):
        self.due()
        order = self.client.orders['1']
        original = copy.deepcopy(order)
        for field,value in [('label','foreign-label'),('reduce_only',True),('filled_amount','1')]:
            with self.subTest(field=field):
                order.update(original)
                order[field] = value
                self.clock.value += 15
                self.service.tick()
                self.assertEqual(self.run['status'],'blocked',self.run['last_cycle'])
        order.update(original)
        self.client.fill('1','.9')
        self.client.trades[0]['fee'] = 'NaN'
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['status'],'blocked')
        self.assertEqual(len(self.run['trades']),0)

    def test_partial_entry_stop_cancels_before_timeout_and_exits_actual_race_fill(self):
        self.open_position('.4')
        self.client.bid, self.client.ask = '.006','.0061'
        self.clock.value += 15
        self.service.tick()
        self.assertLess(self.clock()-self.run['intents'][0]['created_seconds'],300)
        self.assertEqual(self.client.calls.count('cancel'),1,self.run['last_cycle'])
        self.assertEqual(self.run['exit_intent']['reason'],'stop_loss')
        self.assertEqual(len(self.client.writes),1)  # First establish terminal cancellation.
        # An extra execution racing with cancellation must be reconciled before sizing the exit.
        self.client.fill('1','.1')
        self.client.bid, self.client.ask = '.0095','.01'
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.client.writes[-1]['direction'],'sell',self.run['last_cycle'])
        self.assertEqual(self.client.writes[-1]['amount'],'0.5')
        self.assertEqual(self.run['exit_intent']['reason'],'stop_loss')

    def test_stopping_then_recreating_run_cannot_reset_daily_entry_or_consumed_signal(self):
        original_buy = self.client.buy
        def rejected_buy(name,amount,price,label,**kwargs):
            if kwargs.get('preflight'):
                kwargs['preflight']()
            self.client.writes.append({'direction':'buy','amount':str(amount)})
            raise TestnetError('离线模拟：明确拒绝',uncertain=False)
        self.client.buy = rejected_buy
        self.due()
        self.assertEqual(self.run['intents'][0]['status'],'rejected')
        self.assertEqual(self.run['counts']['2026-10-05'],{'orders':1,'entries':1})
        self.assertEqual(self.run['consumed_signals'],['2026-10-04'])
        self.service.operate(self.rid,'stop')
        self.client.buy = original_buy
        self.clock.value += 5
        view = self.service.create({'strategy_id':self.sid,'version_id':self.vid,
            'approved':True,'idempotency_key':'offline-second-run'})
        self.service.tick()
        self.assertEqual(len(self.client.writes),1,self.service.runs[view['run_id']]['last_cycle'])
        restored = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        restored.operate(view['run_id'],'resume')
        self.clock.value += 5
        restored.tick()
        self.assertEqual(len(self.client.writes),1)

    def test_unknown_dependency_exception_blocks_without_killing_worker(self):
        original = self.market.index
        calls = 0
        def occasionally_broken():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ArithmeticError('synthetic private detail must not be echoed')
            return original()
        class TwoCycles:
            count = 0
            def is_set(self):
                return self.count >= 2
            def wait(self, seconds):
                self.count += 1
                return False
        self.service.stop_event = TwoCycles()
        self.market.index = occasionally_broken
        self.service._worker()
        self.assertEqual(self.run['cycle_count'],2)
        self.assertEqual(self.run['status'],'running')
        self.assertEqual(len(self.run['alerts']),1)
        self.assertIn('ArithmeticError',self.run['alerts'][0]['reason'])
        self.assertNotIn('private detail',self.run['alerts'][0]['reason'])
        self.assertFalse(self.client.writes)

    def test_external_recent_or_undated_order_history_blocks_even_before_fill_views_catch_up(self):
        external = {'order_id':'external-order','instrument_name':self.meta['instrument_name'],
                    'direction':'buy','amount':'.1','price':'.01','filled_amount':'.1',
                    'order_state':'filled','reduce_only':False,'label':'external'}
        self.client.orders['external-order'] = external
        # The positions/trades calls may precede a fill; the later history page must still block.
        for timestamp in (self.run['created_ms']+1000,None):
            with self.subTest(timestamp=timestamp):
                external.pop('creation_timestamp',None)
                external.pop('last_update_timestamp',None)
                if timestamp is not None:
                    external.update(creation_timestamp=timestamp,last_update_timestamp=timestamp)
                self.clock.value += 1
                self.service.tick()
                self.assertEqual(self.run['status'],'blocked',self.run['last_cycle'])
                self.assertFalse(self.client.writes)

    def test_new_run_cannot_reset_account_daily_order_cap(self):
        # Persisted counts represent earlier completed/rejected attempts; no live position remains.
        self.run['counts']['2026-10-05'] = {'orders':4,'entries':0}
        self.service._save(self.run)
        self.service.operate(self.rid,'stop')
        view = self.service.create({'strategy_id':self.sid,'version_id':self.vid,
            'approved':True,'idempotency_key':'offline-cap-new-run'})
        self.due()
        self.assertFalse(self.client.writes)
        newrun = self.service.runs[view['run_id']]
        self.assertEqual(newrun['status'],'blocked')
        self.assertIn('额度',newrun['last_cycle']['reason'])

    def test_new_run_daily_entry_cap_is_checked_even_without_a_repeated_signal(self):
        # Exercise the account entry counter independently from signal de-duplication.
        self.run['counts']['2026-10-05'] = {'orders':1,'entries':1}
        self.service._save(self.run)
        self.service.operate(self.rid,'stop')
        view = self.service.create({'strategy_id':self.sid,'version_id':self.vid,
            'approved':True,'idempotency_key':'offline-entry-cap-new-run'})
        self.due()
        self.assertFalse(self.client.writes)
        newrun = self.service.runs[view['run_id']]
        self.assertEqual(newrun['status'],'blocked')
        self.assertIn('额度',newrun['last_cycle']['reason'])

    def test_cancel_definitely_not_sent_restores_open_and_retries_after_fresh_reconciliation(self):
        self.open_position('.4')
        original_cancel = self.client.cancel
        attempts = 0
        def refuse_once(oid,preflight=None):
            nonlocal attempts
            attempts += 1
            if preflight:
                preflight()
            if attempts == 1:
                self.client.calls.append('cancel_refused_before_post')
                raise TestnetError('离线模拟：认证更新后下单前校验拒绝',uncertain=False)
            return original_cancel(oid,preflight=preflight)
        self.client.cancel = refuse_once
        self.clock.value += 300
        self.service.tick()
        self.assertEqual(self.run['intents'][0]['status'],'open',self.run['last_cycle'])
        self.assertEqual(self.run['status'],'blocked')
        self.assertEqual(self.client.calls.count('cancel'),0)
        previous_snapshot_count = self.client.calls.count('account_snapshot')
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(attempts,2)
        self.assertEqual(self.client.calls.count('account_snapshot'),previous_snapshot_count+1)
        self.assertEqual(self.client.calls.count('cancel'),1)
        self.assertEqual(self.run['intents'][0]['status'],'cancel_unknown')
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(self.run['intents'][0]['status'],'cancelled')

    def test_submit_preflight_rejection_is_definite_and_still_consumes_budget(self):
        callbacks = []
        def stop_before_write(name,amount,price,label,*,validity_deadline=None,preflight=None):
            (self.root/'STOP').touch()
            callbacks.append('preflight')
            preflight()
            self.fail('write must not occur after rejecting preflight')
        self.client.buy = stop_before_write
        self.due()
        self.assertEqual(callbacks,['preflight'])
        self.assertFalse(self.client.writes)
        self.assertEqual(self.run['intents'][0]['status'],'rejected')
        self.assertEqual(self.run['counts']['2026-10-05'],{'orders':1,'entries':1})
        self.assertEqual(self.run['consumed_signals'],['2026-10-04'])

    def test_valid_bid_without_ask_still_executes_stop_for_actual_position(self):
        self.open_position()
        self.client.bid,self.client.ask = '.006',None
        self.clock.value += 15
        self.service.tick()
        self.assertEqual(len(self.client.writes),2,self.run['last_cycle'])
        self.assertEqual(self.client.writes[-1]['direction'],'sell')
        self.assertEqual(self.client.writes[-1]['amount'],'0.9')
        self.assertEqual(self.client.writes[-1]['price'],'0.006')

    def test_fsync_crossing_utc_midnight_rejects_post_and_keeps_original_day_count(self):
        self.open_position()
        self.clock.value = int(NOW//86400)*86400+86400-1  # 23:59:59 UTC.
        self.client.bid,self.client.ask = '.006','.0061'
        original = self.service._save
        advanced = False
        def slow_persistence(run):
            nonlocal advanced
            original(run)
            if not advanced and run['intents'][-1]['direction']=='sell' and run['intents'][-1]['status']=='prepared':
                self.clock.value += 2  # Disk persistence completes at 00:00:01 UTC.
                advanced = True
        with patch.object(self.service,'_save',side_effect=slow_persistence):
            self.service.tick()
        self.assertTrue(advanced)
        self.assertEqual(len(self.client.writes),1,self.run['last_cycle'])
        self.assertEqual(self.run['intents'][-1]['status'],'rejected')
        self.assertEqual(self.run['counts']['2026-10-05'],{'orders':2,'entries':1})
        self.assertNotIn('2026-10-06',self.run['counts'])

    def test_slow_catalogs_expire_selection_index_even_if_final_books_are_fresh(self):
        main_instruments, test_instruments = self.market.instruments,self.client.get_instruments
        def slow_main_catalog():
            self.clock.value += 8
            return main_instruments()
        def slow_test_catalog():
            self.clock.value += 8
            return test_instruments()
        with patch.object(self.market,'instruments',side_effect=slow_main_catalog), \
             patch.object(self.client,'get_instruments',side_effect=slow_test_catalog):
            self.due()
        self.assertFalse(self.client.writes,self.run['last_cycle'])
        self.assertEqual(self.run['status'],'blocked')
        self.assertEqual(self.clock.value,int(NOW//86400)*86400+8*3600+17)

    def test_disk_implementation_change_blocks_new_run_before_account_connection(self):
        self.service.operate(self.rid,'stop')
        calls = list(self.client.calls)
        with patch('runtime.implementation_hash',return_value='f'*64):
            with self.assertRaises(RuntimeErrorState):
                self.service.create({'strategy_id':self.sid,'version_id':self.vid,
                    'approved':True,'idempotency_key':'offline-stale-loaded-code'})
        self.assertEqual(self.client.calls,calls)

    def test_stopped_run_stays_stopped_when_loading_new_implementation(self):
        self.service.operate(self.rid,'stop')
        calls = list(self.client.calls)
        restored = StrategyRuntimeService(self.root,self.strategies,self.client,self.market,self.clock)
        self.assertEqual(restored.runs[self.rid]['status'],'stopped')
        self.assertTrue(restored.runs[self.rid]['resume_required'])
        self.assertIsNone(restored.active_id)
        restored.tick()
        self.assertEqual(self.client.calls,calls)


if __name__ == '__main__':
    unittest.main()

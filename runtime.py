"""One deterministic, explicitly authorized TESTNET runner. No model or mainnet writes."""
from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from backtest import save_json, atomic_write
from market import iso
from strategy import (KIND, normalize_rules, evaluate_signal, select_contract,
                      validate_quote, validate_exit_bid, size_order, decision, price_step, StrategyRuleError)
from testnet import DeribitTestnetClient, MarketDataProvider, TestnetError, fee_rate

TERMINAL_ORDERS = {'filled', 'cancelled', 'rejected'}
RUN_SCHEMA = 'optimatrix-testnet-v1'


class RuntimeErrorState(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def implementation_hash():
    root = Path(__file__).resolve().parent
    return digest({name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                   for name in ('strategy.py', 'runtime.py', 'testnet.py', 'strategies.py', 'configuration.py')})


LOADED_IMPLEMENTATION_HASH = implementation_hash()


def dec(value):
    if isinstance(value, bool):
        raise RuntimeErrorState('数值类型异常')
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise RuntimeErrorState('账户或成交数值缺失') from None
    if not result.is_finite():
        raise RuntimeErrorState('账户或成交数值非有限值')
    return result


def next_check(now, hour=8):
    current = datetime.fromtimestamp(now, timezone.utc)
    target = current.replace(hour=hour, minute=0, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return iso(target.timestamp())


class StrategyRuntimeService:
    def __init__(self, root, strategies, client=None, market=None, clock=time.time, notifier=None):
        self.root, self.strategies, self.clock = Path(root), strategies, clock
        self.client = client or DeribitTestnetClient(self.root)
        self.market = market or MarketDataProvider()
        self.directory = self.root/'local/strategy-runs'
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.notifier = notifier
        self.runs = {}
        self.views = {}
        self.active_id = None
        self.storage_error = None
        for path in sorted(self.directory.glob('*/run.json')):
            try:
                run = json.loads(path.read_text())
                if run['schema_version'] != RUN_SCHEMA or not re.fullmatch('[a-f0-9]{32}', run['run_id']):
                    raise ValueError('shape')
                if digest(run['spec']) != run['rules_sha256']:
                    raise ValueError('fingerprint')
                # Loading old state does not authorize trading or rewrite its evidence.
                if run.get('status') != 'stopped':
                    run['status'] = 'paused_reconciliation_required'
                run['resume_required'] = True
                self.runs[run['run_id']] = run
                self._publish(run)
            except (OSError, ValueError, KeyError, TypeError):
                self.storage_error = '运行文件损坏，保留原件；禁止启动交易'

    @property
    def availability(self):
        return {'configured': bool(self.client.configured), 'ready': not self.storage_error and bool(self.client.configured),
                'reason': self.storage_error or ('Testnet 凭据已配置；启动仍需核对权限、账户与规则' if self.client.configured else '待配置本机 testnet 凭据'),
                'environment': 'testnet', 'production_private_enabled': False, 'model_calls': 0}

    def _path(self, run):
        return self.directory/run['run_id']

    def _event(self, run, event, data):
        path = self._path(run)/'events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY|os.O_APPEND|os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps({'at': iso(self.clock()), 'event': event, 'data': data}, ensure_ascii=False, allow_nan=False)+'\n')
            stream.flush()
            os.fsync(stream.fileno())

    def _save(self, run):
        try:
            save_json(self._path(run)/'run.json', run)
        except (OSError, TypeError, ValueError):
            self.storage_error = '运行持久化失败；禁止新的交易写请求'
            run['status'] = 'storage_error'
            self._publish(run)
            raise RuntimeErrorState(self.storage_error) from None
        self._publish(run)

    def _publish(self, run):
        keys = ('run_id', 'strategy_id', 'version_id', 'rules_sha256', 'implementation_sha256', 'account_id', 'status',
                'created_at', 'updated_at', 'last_cycle', 'next_check_at', 'position', 'counts', 'alerts',
                'resume_required', 'paused_entries', 'signal', 'account', 'cycle_count', 'ledger')
        view = {key: copy.deepcopy(run.get(key)) for key in keys}
        view.update(mode='testnet', evidence_type='testnet_execution', production_signal='BTC-PERPETUAL',
                    economic_edge_established=False,
                    orders=[{key: item.get(key) for key in ('intent_id','order_id','instrument_name','direction','amount','price','status','created_at','filled_amount')}
                            for item in run.get('intents', [])],
                    pnl_basis='Testnet 实际成交与费用；不是主网执行或策略盈利证据',
                    stop_present=(self.root/'STOP').exists())
        self.views[run['run_id']] = view

    def snapshot(self, strategy_id=None):
        # Immutable published copies; GET never waits on broker calls or starts work.
        return {'runs': [copy.deepcopy(v) for v in tuple(self.views.values())
                         if strategy_id is None or v['strategy_id'] == strategy_id],
                'availability': self.availability, 'server_time': iso(self.clock())}

    def _version(self, sid, vid):
        detail = self.strategies.detail(sid)
        version = next((v for v in detail['versions'] if v['version_id'] == vid), None)
        if version is None or version['spec']['kind'] != KIND or not version.get('can_run_testnet'):
            raise RuntimeErrorState('该版本没有 Testnet 执行能力')
        return version

    def _identity(self, run):
        version = self._version(run['strategy_id'], run['version_id'])
        if version['status'] != 'frozen' or version['rules_sha256'] != run['rules_sha256'] or digest(version['spec']) != run['rules_sha256']:
            raise RuntimeErrorState('冻结规则身份不一致，禁止运行')
        if implementation_hash() != run['implementation_sha256'] or LOADED_IMPLEMENTATION_HASH != run['implementation_sha256']:
            raise RuntimeErrorState('执行实现已改变，需完成工程复核后建立新运行')

    def create(self, payload):
        with self.lock:
            if self.storage_error:
                raise RuntimeErrorState(self.storage_error)
            if payload.get('approved') is not True:
                raise RuntimeErrorState('需要明确的 Testnet 运行授权')
            key = payload.get('idempotency_key', '')
            if not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}', key):
                raise RuntimeErrorState('缺少有效运行提交标识')
            context = {k: payload.get(k) for k in ('strategy_id','version_id')}
            for run in self.runs.values():
                if run['idempotency_key'] == key:
                    if any(run[k] != context[k] for k in context):
                        raise RuntimeErrorState('同一授权不能改变策略版本')
                    return copy.deepcopy(self.views[run['run_id']])
            if self.active_id:
                raise RuntimeErrorState('本机已有一个运行；请先停止并核对现有运行')
            if any(old.get('position') or any(i['status'] not in TERMINAL_ORDERS for i in old['intents'])
                   for old in self.runs.values()):
                raise RuntimeErrorState('已有运行仍有持仓或未决订单，不能通过新建运行绕过对账')
            if (self.root/'STOP').exists():
                raise RuntimeErrorState('STOP 存在，不能连接账户或启动')
            if implementation_hash()!=LOADED_IMPLEMENTATION_HASH:
                raise RuntimeErrorState('代码已修改，请重启本机服务以加载已复核实现')
            version = self._version(context['strategy_id'], context['version_id'])
            if not version.get('onboarding_complete'):
                raise RuntimeErrorState('请先确认当前版本所有默认规则')
            self.client.authenticate()
            account = self.client.account_snapshot(int((self.clock()-60)*1000))
            if not account.get('complete'):
                raise RuntimeErrorState('账户快照未完整取得')
            if any(dec(p.get('size', 0)) != 0 for p in account['positions']) or account['open_orders']:
                raise RuntimeErrorState('此 Testnet 账户存在外部持仓或挂单；请使用独立且空闲的测试账户')
            if version['status'] != 'frozen':
                self.strategies.freeze_version(context['strategy_id'], context['version_id'])
                version = self._version(context['strategy_id'], context['version_id'])
            now = self.clock()
            run = {'schema_version':RUN_SCHEMA, 'run_id':uuid.uuid4().hex, **context,
                   'rules_sha256':version['rules_sha256'], 'spec':copy.deepcopy(version['spec']),
                   'implementation_sha256':implementation_hash(), 'account_id':str(account['account_id']),
                   'idempotency_key':key, 'approved_at':iso(now), 'authorization_scope':'Deribit testnet only; production public signals',
                   'created_at':iso(now), 'created_ms':int(now*1000), 'updated_at':iso(now),
                   'status':'running', 'resume_required':False, 'paused_entries':False, 'last_cycle':None,
                   'next_check_at':next_check(now), 'intents':[], 'trades':{}, 'position':None, 'signal':None,
                   'checked_days':[], 'consumed_signals':[], 'counts':{}, 'alerts':[], 'account':None,
                   'cycle_count':0, 'exit_intent':None, 'ledger':None}
            self.runs[run['run_id']] = run
            self._event(run, 'authorized', {k:run[k] for k in ('strategy_id','version_id','rules_sha256','account_id','authorization_scope')})
            self._save(run)
            atomic_write(self._path(run)/'strategy_spec.md', self.strategies.export_spec(run['strategy_id'],run['version_id']).encode())
            self.active_id = run['run_id']
            return copy.deepcopy(self.views[run['run_id']])

    def operate(self, rid, operation):
        with self.lock:
            run = self.runs.get(rid)
            if not run:
                raise RuntimeErrorState('运行不存在')
            if operation == 'stop':
                run.update(status='stopped', resume_required=True)
                if self.active_id == rid:
                    self.active_id = None
                self._event(run, 'stopped', {'note':'循环停止；已有挂单与仓位不会自动消失'})
            elif operation == 'pause':
                run['paused_entries'] = True
                self._event(run, 'pause_entries', {})
            elif operation in {'resume','reconcile'}:
                if self.active_id not in (None, rid):
                    raise RuntimeErrorState('已有其他活动运行')
                if (self.root/'STOP').exists():
                    raise RuntimeErrorState('STOP 存在，不能查询或恢复')
                self._identity(run)
                # Only an explicit resume can clear the restart gate; reconciliation is read-only.
                self._cycle(run, read_only=True)
                if run['status'] in {'blocked','storage_error','reconciliation_required'}:
                    raise RuntimeErrorState(run['last_cycle']['reason'])
                if operation == 'resume':
                    run.update(status='running', resume_required=False, paused_entries=False)
                    self.active_id = rid
                self._event(run, operation, {})
            else:
                raise RuntimeErrorState('未知运行操作')
            self._save(run)
            return copy.deepcopy(self.views[rid])

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._worker, name='testnet-strategy', daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=45)
        self.client.close()
        self.market.close()

    def _worker(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            self.tick()
            run = self.runs.get(self.active_id)
            interval = run['spec']['rules']['loop_seconds'] if run else 15
            self.stop_event.wait(max(0.1, interval-(time.monotonic()-started)))

    def tick(self):
        with self.lock:
            run = self.runs.get(self.active_id)
            if run:
                self._cycle(run)

    def _alert(self, run, reason):
        previous = next((a for a in run['alerts'] if a['reason'] == reason), None)
        if previous:
            previous['last_at'] = iso(self.clock())
            previous['count'] += 1
        else:
            alert={'at':iso(self.clock()),'last_at':iso(self.clock()),'reason':reason,'count':1,
                   'notification':'pending_browser_delivery', 'desktop_notification':{'status':'unavailable','detail':'桌面通知未配置'}}
            run['alerts'].append(alert)
            run['alerts'] = run['alerts'][-30:]
            # Save the reason before invoking an optional local side effect.
            try:
                self._event(run,'alert',copy.deepcopy(alert))
                if self.notifier:
                    alert['desktop_notification']=self.notifier(reason)
                self._event(run,'desktop_notification',{'reason':reason,'result':alert['desktop_notification']})
            except OSError:
                self.storage_error='告警持久化失败，禁止后续交易写请求'
            except Exception:
                alert['desktop_notification']={'status':'failed','detail':'本机通知请求失败，未确认送达'}

    def _cycle(self, run, read_only=False):
        now = self.clock()
        cycle = {'at':iso(now),'decision':'hold','reason':'等待下一次 UTC 08:00 入场检查',
                 'signal':copy.deepcopy(run.get('signal')), 'account_at':None,
                 'prices':{'signal_index_usd':None,'mainnet_bid_btc':None,'mainnet_ask_btc':None,'testnet_bid_btc':None,'testnet_ask_btc':None},
                 'price_status':'not_retrieved','read_only':read_only}
        try:
            if self.storage_error:
                raise RuntimeErrorState(self.storage_error)
            if (self.root/'STOP').exists():
                run['status'] = 'halted_stop_file'
                cycle.update(decision='blocked',reason='STOP 存在：不联网、不下单、不撤单；挂单和持仓可能仍在')
                self._alert(run, cycle['reason'])
                return
            self._identity(run)
            snapshot = self.client.account_snapshot(run['created_ms']-60000)
            if not snapshot.get('complete') or str(snapshot['account_id']) != run['account_id']:
                raise RuntimeErrorState('账户身份变化或快照不完整')
            observed = snapshot.get('started_at',snapshot['observed_at'])
            if self.clock()-observed > 15 or observed > self.clock()+5:
                raise RuntimeErrorState('账户快照过时或时间异常')
            cycle['account_at'] = iso(observed)
            save_json(self._path(run)/'account'/f'{run["cycle_count"]:08d}-{uuid.uuid4().hex}.json', snapshot)
            self._reconcile(run, snapshot)
            run['account'] = {'source':'Deribit testnet','at':iso(observed),'equity_btc':snapshot['summary'].get('equity'),
                              'available_funds_btc':snapshot['summary'].get('available_funds'),'account_id':run['account_id']}
            unresolved = [i for i in run['intents'] if i['status'] in {'prepared','submission_unknown','cancel_unknown','missing'}]
            if unresolved:
                run['status'] = 'reconciliation_required'
                cycle.update(decision='blocked',reason='订单提交或撤单结果未知；只对账，不重发')
                self._alert(run, cycle['reason'])
                return
            rules = normalize_rules(run['spec']['rules'])
            index = self.market.index()
            if not -5 <= self.clock()-index['source_at'] <= rules['source_max_age_seconds'] or not -5 <= self.clock()-index['received_at'] <= rules['receive_max_age_seconds']:
                raise RuntimeErrorState('主网 BTC 指数过时或时间异常')
            cycle['prices']['signal_index_usd'] = index['result']['index_price']
            cycle['price_status'] = 'mainnet_index_current'
            current = datetime.fromtimestamp(self.clock(), timezone.utc)
            day = current.date().isoformat()
            check = current.replace(hour=rules['check_hour_utc'],minute=0,second=0,microsecond=0)
            in_window = 0 <= (current-check).total_seconds() < rules['entry_grace_seconds']
            due = in_window and day not in run['checked_days']
            if run['signal'] is None or due or run['signal'].get('observed_day') != day:
                candles = self.market.candles(self.clock(), days=rules['slow_days']+3)
                signal = evaluate_signal(candles['result'], self.clock(), rules)
                signal.update(observed_at=iso(self.clock()), observed_day=day)
                run['signal'] = signal
                save_json(self._path(run)/'signals'/f'{uuid.uuid4().hex}.json', candles)
            cycle['signal'] = copy.deepcopy(run['signal'])
            if due and not read_only:
                run['checked_days'].append(day)
                if run['signal']['bearish'] and run['position'] and run['exit_intent'] is None:
                    run['exit_intent'] = {'reason':'bearish_signal','attempts':0,'created_at':iso(self.clock())}
                self._event(run, 'daily_signal', run['signal'])
                self._save(run)
            position = run['position']
            quote = None
            reason = None
            if position:
                quote = self.client.get_order_book(position['instrument_name'])
                if quote['result'].get('instrument_name') != position['instrument_name']:
                    raise RuntimeErrorState('退出盘口合约不匹配')
                bid = validate_exit_bid(quote['result'],quote['received_at'],self.clock(),rules)
                cycle['prices'].update(testnet_bid_btc=str(bid),testnet_ask_btc=quote['result'].get('best_ask_price'))
                intent = decision(run['signal'],position,bid,self.clock(),due,run['paused_entries'],rules)
                if intent['action']=='blocked':
                    raise RuntimeErrorState(intent['reason'])
                reason = intent['reason'] if intent['action']=='exit_intent' else None
                if reason and run['exit_intent'] is None:
                    run['exit_intent'] = {'reason':reason,'attempts':0,'created_at':iso(self.clock())}
                    self._save(run)
            pending = [i for i in run['intents'] if i['status'] not in TERMINAL_ORDERS]
            for item in pending:
                deadline = rules['entry_timeout_seconds'] if item['direction']=='buy' else rules['exit_timeout_seconds']
                cancel_entry = item['direction']=='buy' and (run['paused_entries'] or run['exit_intent'] is not None)
                if (self.clock()-item['created_seconds'] >= deadline or cancel_entry) and not read_only:
                    self._cancel(run, item)
                    cycle.update(decision='cancel_intent',reason='撤销超时、暂停或已触发退出的未成交部分；等待下轮对账')
                    return
            if pending:
                cycle.update(reason='已有活动订单，禁止重复提交')
                run['status'] = 'running' if not read_only else 'reconciled'
                return
            if position:
                if run['exit_intent'] and not read_only:
                    if run['exit_intent']['attempts'] >= rules['max_exit_attempts']:
                        raise RuntimeErrorState('退出尝试额度耗尽；需要人工核对，禁止无限追价')
                    self._submit(run,'sell',position['instrument_name'],dec(position['quantity']),bid, snapshot,
                                 position['instrument'],run['exit_intent']['reason'],self._deadline(snapshot,[quote],rules))
                    cycle.update(decision='exit_intent',reason=run['exit_intent']['reason'])
                else:
                    cycle['reason'] = '持有本策略多头；退出条件未触发' if not reason else '只读对账：退出条件已触发'
            elif decision(run['signal'],None,None,self.clock(),due,run['paused_entries'],rules)['action']=='open_intent' and not read_only:
                signal_key = run['signal']['bar_date']
                if any(old['account_id']==run['account_id'] and signal_key in old['consumed_signals'] for old in self.runs.values()):
                    cycle['reason'] = '该上穿事件已经消费，不重复开仓'
                else:
                    self._entry(run, snapshot, cycle, rules, signal_key)
            elif due:
                cycle['reason'] = '本次日线没有新的上穿信号' if not run['signal']['crossover'] else '暂停开仓或只读对账，不开仓'
            run['status'] = 'reconciled' if read_only else ('paused_entries' if run['paused_entries'] else 'running')
        except Exception as error:
            # Known client/core errors contain only fixed program-owned text.
            reason = str(error) if isinstance(error, (TestnetError, RuntimeErrorState, StrategyRuleError)) else '数据、规则或持久化校验失败（'+type(error).__name__+'）'
            cycle.update(decision='blocked',reason=reason)
            run['status'] = 'storage_error' if self.storage_error or isinstance(error,OSError) else 'blocked'
            if isinstance(error,OSError):
                self.storage_error = reason
            self._alert(run, reason)
        finally:
            run.update(last_cycle=cycle,updated_at=iso(self.clock()),cycle_count=run['cycle_count']+1,
                       next_check_at=next_check(self.clock(),run['spec']['rules']['check_hour_utc']))
            try:
                self._event(run,'cycle',cycle)
                self._save(run)
            except (OSError, ValueError):
                self.storage_error = '循环日志持久化失败，禁止后续写请求'
                run['status'] = 'storage_error'
                self._publish(run)

    def _entry(self, run, snapshot, cycle, rules, signal_key):
        index = self.market.index()
        if not -5 <= self.clock()-index['received_at'] <= rules['receive_max_age_seconds'] or not -5 <= self.clock()-index['source_at'] <= rules['source_max_age_seconds']:
            raise RuntimeErrorState('主网 BTC 指数过时')
        index_price = index['result']['index_price']
        main_meta,test_meta = select_contract(self.market.instruments(),self.client.get_instruments(),index_price,self.clock(),rules)
        main_name, name = main_meta['instrument_name'], test_meta['instrument_name']
        main_quote, test_quote = self.market.book(main_name), self.client.get_order_book(name)
        if main_quote['result'].get('instrument_name') != main_name or test_quote['result'].get('instrument_name') != name:
            raise RuntimeErrorState('开仓盘口合约不匹配')
        main_bid,main_ask = validate_quote(main_quote['result'],main_quote['received_at'],self.clock(),rules['main_spread_limit'],rules)
        bid,ask = validate_quote(test_quote['result'],test_quote['received_at'],self.clock(),rules['test_spread_limit'],rules)
        cycle['prices'] = {'signal_index_usd':index_price,'mainnet_bid_btc':str(main_bid),'mainnet_ask_btc':str(main_ask),'testnet_bid_btc':str(bid),'testnet_ask_btc':str(ask)}
        # Market discovery can be slow: refresh account and testnet book immediately before committing risk.
        snapshot = self.client.account_snapshot(run['created_ms']-60000)
        self._reconcile(run,snapshot)
        if run['position'] or snapshot['open_orders'] or str(snapshot['account_id']) != run['account_id']:
            raise RuntimeErrorState('下单前账户变化，取消本次开仓')
        main_quote, test_quote = self.market.book(main_name), self.client.get_order_book(name)
        if test_quote['result'].get('instrument_name') != name or main_quote['result'].get('instrument_name') != main_name:
            raise RuntimeErrorState('下单前合约变化')
        main_bid,main_ask=validate_quote(main_quote['result'],main_quote['received_at'],self.clock(),rules['main_spread_limit'],rules)
        bid,ask = validate_quote(test_quote['result'],test_quote['received_at'],self.clock(),rules['test_spread_limit'],rules)
        cycle['prices'].update(mainnet_bid_btc=str(main_bid),mainnet_ask_btc=str(main_ask),testnet_bid_btc=str(bid),testnet_ask_btc=str(ask))
        step = price_step(test_meta,ask)
        if ask % step != 0:
            raise RuntimeErrorState('最优卖价不满足测试网价格步长')
        rate = fee_rate(test_meta,snapshot['summary'])
        amount = size_order(test_meta,ask,snapshot['summary']['equity'],snapshot['summary']['available_funds'],rate,rules)
        if amount <= 0:
            cycle.update(decision='hold',reason='1% 成本预算不足最小交易数量，本次跳过')
            return
        if amount > dec(test_quote['result']['best_ask_amount']):
            cycle.update(decision='hold',reason='测试网卖一深度不足拟交易数量，本次跳过')
            return
        # UTC entry window may have elapsed during network requests; never catch up.
        dt = datetime.fromtimestamp(self.clock(),timezone.utc)
        if dt.hour != rules['check_hour_utc'] or dt.minute*60+dt.second >= rules['entry_grace_seconds']:
            cycle.update(decision='hold',reason='行情与账户检查完成时已超过入场窗口，不补单')
            return
        run['consumed_signals'].append(signal_key)
        window_end=dt.replace(hour=rules['check_hour_utc'],minute=0,second=0,microsecond=0).timestamp()+rules['entry_grace_seconds']
        self._submit(run,'buy',name,amount,ask,snapshot,test_meta,'SMA20/60 新上穿',
                     min(window_end,self._deadline(snapshot,[main_quote,test_quote],rules),
                         index['received_at']+rules['receive_max_age_seconds'],index['source_at']+rules['source_max_age_seconds']))
        cycle.update(decision='entry_intent',reason='新上穿且全部约束通过；只向 Testnet 提交')

    def _guard_write(self, run):
        if (self.root/'STOP').exists():
            raise RuntimeErrorState('STOP 存在，禁止交易写请求')
        if self.storage_error or self.stop_event.is_set() or run['resume_required']:
            raise RuntimeErrorState('运行暂停或存储异常，禁止交易写请求')
        self._identity(run)

    def _deadline(self,snapshot,quotes,rules):
        values=[snapshot.get('started_at',snapshot['observed_at'])+15]
        for quote in quotes:
            values.extend((quote['received_at']+rules['receive_max_age_seconds'],
                           quote['result']['timestamp']/1000+rules['source_max_age_seconds']))
        return min(values)

    def _submit(self,run,direction,name,amount,price,snapshot,meta,reason,validity_deadline):
        self._guard_write(run)
        account_at=snapshot.get('started_at',snapshot['observed_at'])
        if not -5<=self.clock()-account_at<=15 or self.clock()>=validity_deadline or str(snapshot['account_id']) != run['account_id']:
            raise RuntimeErrorState('提交前账户快照过时或身份异常')
        rules=run['spec']['rules']
        day=datetime.fromtimestamp(self.clock(),timezone.utc).date().isoformat()
        day_end=(datetime.fromisoformat(day).replace(tzinfo=timezone.utc)+timedelta(days=1)).timestamp()
        validity_deadline=min(validity_deadline,day_end)
        counts=run['counts'].setdefault(day,{'orders':0,'entries':0})
        account_counts={k:sum(old['counts'].get(day,{}).get(k,0) for old in self.runs.values()
                              if old['account_id']==run['account_id']) for k in ('orders','entries')}
        if account_counts['orders']>=rules['max_orders_per_day'] or (direction=='buy' and account_counts['entries']>=rules['max_entries_per_day']):
            raise RuntimeErrorState('当日订单额度已用完；停止提交并等待处理')
        if direction=='sell' and (not run['position'] or amount>dec(run['position']['quantity'])):
            raise RuntimeErrorState('退出数量超过已核对本策略持仓')
        identifier=uuid.uuid4().hex
        item={'intent_id':identifier,'label':f'opx-{run["run_id"][:12]}-{identifier[:16]}','direction':direction,
              'instrument_name':name,'instrument':copy.deepcopy(meta),'amount':str(amount),'price':str(price),
              'status':'prepared','order_id':None,'created_at':iso(self.clock()),'created_seconds':self.clock(),
              'filled_amount':'0','reason':reason,'reduce_only':direction=='sell'}
        counts['orders']+=1
        if direction=='buy': counts['entries']+=1
        else: run['exit_intent']['attempts']+=1
        run['intents'].append(item)
        self._event(run,'intent_prepared',copy.deepcopy(item))
        self._save(run)
        try:
            self._guard_write(run)
            result=(self.client.buy if direction=='buy' else self.client.sell)(name,amount,price,item['label'],validity_deadline=validity_deadline,
                                                                              preflight=lambda:self._guard_write(run))
            order=result.get('order') if isinstance(result,dict) else None
            if not isinstance(order,dict) or not order.get('order_id'):
                raise TestnetError('订单响应无法确认',status='submission_unknown',uncertain=True)
            item.update(order_id=str(order['order_id']),status='accepted')
            self._event(run,'order_response',result)
        except (TestnetError,RuntimeErrorState) as error:
            item['status']='submission_unknown' if isinstance(error,TestnetError) and error.uncertain else 'rejected'
            self._event(run,item['status'],{'intent_id':identifier,'reason':str(error)})
            self._save(run)
            raise
        self._save(run)

    def _cancel(self,run,item):
        self._guard_write(run)
        if not item.get('order_id'):
            raise RuntimeErrorState('没有已确认订单 ID，不能猜测撤单')
        previous_status=item['status']
        item['status']='cancel_unknown'
        self._event(run,'cancel_prepared',{'intent_id':item['intent_id'],'order_id':item['order_id']})
        self._save(run)
        try:
            self._guard_write(run)
            result=self.client.cancel(item['order_id'],preflight=lambda:self._guard_write(run))
            self._event(run,'cancel_response',result)
            # Even an acknowledged cancellation needs the next account/trade reconciliation.
            if isinstance(result,dict) and result.get('order_state') in TERMINAL_ORDERS:
                item['cancel_acknowledged']=True
        except (TestnetError,RuntimeErrorState) as error:
            if not isinstance(error,TestnetError) or not error.uncertain:
                item['status']=previous_status
                self._event(run,'cancel_not_sent_or_rejected',{'intent_id':item['intent_id'],'reason':str(error)})
            self._save(run)
            raise
        self._save(run)

    def _reconcile(self,run,snapshot):
        if not snapshot.get('complete'):
            raise RuntimeErrorState('账户历史未完整取得')
        orders={str(o['order_id']):o for o in snapshot['orders']+snapshot['open_orders'] if o.get('order_id')}
        owned={}
        for item in run['intents']:
            matching=[o for o in orders.values() if o.get('label')==item['label']]
            if item.get('order_id') and item['order_id'] in orders:
                matching=[orders[item['order_id']]]
            if not matching and item['status'] not in TERMINAL_ORDERS:
                fetched=self.client.get_order_state(item['order_id']) if item.get('order_id') else self.client.orders_by_label(item['label'])
                matching=([fetched] if isinstance(fetched,dict) else fetched) or []
            if len(matching)>1:
                raise RuntimeErrorState('同一意图对应多个订单，禁止继续交易')
            if matching:
                order=matching[0]
                if (order.get('instrument_name')!=item['instrument_name'] or order.get('direction')!=item['direction']
                    or dec(order.get('amount'))!=dec(item['amount']) or dec(order.get('price'))!=dec(item['price'])
                    or order.get('label')!=item['label'] or order.get('reduce_only') is not item['reduce_only']):
                    raise RuntimeErrorState('订单参数与已授权意图不一致')
                identifier=str(order['order_id'])
                if item.get('order_id') and item['order_id']!=identifier:
                    raise RuntimeErrorState('订单 ID 与本地意图冲突')
                item['order_id']=identifier
                status=order.get('order_state')
                if status not in TERMINAL_ORDERS|{'open','untriggered'}:
                    raise RuntimeErrorState('订单状态未知')
                if item['status']!='cancel_unknown' or status in TERMINAL_ORDERS:
                    item['status']=status
                item['filled_amount']=str(dec(order.get('filled_amount',0)))
                if not 0<=dec(item['filled_amount'])<=dec(item['amount']):
                    raise RuntimeErrorState('订单成交量超出授权数量')
                orders[identifier]=order
            elif item['status'] not in TERMINAL_ORDERS:
                item['status']='missing' if item.get('order_id') else 'submission_unknown'
            if item.get('order_id'):
                owned[item['order_id']]=item
        for oid,order in orders.items():
            if oid not in owned:
                stamps=[order.get('creation_timestamp'),order.get('last_update_timestamp')]
                if any(value is None for value in stamps) or max(dec(value) for value in stamps)>=run['created_ms']:
                    raise RuntimeErrorState('发现运行期间外部订单或无法核实的历史订单，停止交易并等待核对')
        for trade in snapshot['trades']:
            item=owned.get(str(trade.get('order_id')))
            if item is None:
                if dec(trade.get('timestamp',0))>=run['created_ms']:
                    raise RuntimeErrorState('运行期间出现外部成交，停止自动交易并等待核对')
                continue
            fields=('trade_id','order_id','instrument_name','direction','amount','price','fee','fee_currency','timestamp')
            if any(trade.get(k) is None for k in fields) or trade['fee_currency']!='BTC':
                raise RuntimeErrorState('成交费用或身份资料缺失，不能完成核账')
            value={k:trade[k] for k in fields}
            if value['instrument_name']!=item['instrument_name'] or value['direction'] not in {'buy','sell'}:
                raise RuntimeErrorState('成交不属于本策略订单')
            # The API describes trade.direction as taker direction. Ownership and
            # our accounting side come from the verified order, including maker fills.
            value['reported_direction']=value['direction']
            value['direction']=item['direction']
            if dec(value['amount'])<=0 or dec(value['price'])<=0:
                raise RuntimeErrorState('成交数量或价格异常')
            dec(value['fee'])
            key=str(value['trade_id'])
            previous=run['trades'].get(key)
            if previous and previous!=value:
                raise RuntimeErrorState('历史成交内容发生变化，保留原记录并停止')
            run['trades'][key]=value
        for oid,item in owned.items():
            actual=sum((dec(t['amount']) for t in run['trades'].values() if str(t['order_id'])==oid),Decimal(0))
            if actual!=dec(item['filled_amount']):
                raise RuntimeErrorState('订单成交量与取得的逐笔成交不一致，等待核对')
        quantities={}
        remaining_costs={}
        remaining_fees={}
        cash_flow=Decimal(0)
        fees=Decimal(0)
        realized=Decimal(0)
        for trade in sorted(run['trades'].values(),key=lambda x:(x['timestamp'],str(x['trade_id']))):
            name=trade['instrument_name']; amount=dec(trade['amount'])
            fee=dec(trade['fee']); price=dec(trade['price'])
            fees+=fee
            previous=quantities.get(name,Decimal(0))
            quantities[name]=previous+(amount if trade['direction']=='buy' else -amount)
            if quantities[name]<0: raise RuntimeErrorState('成交账本产生空头，禁止继续交易')
            if trade['direction']=='buy':
                remaining_costs[name]=remaining_costs.get(name,Decimal(0))+amount*price
                remaining_fees[name]=remaining_fees.get(name,Decimal(0))+fee
                cash_flow-=amount*price+fee
            else:
                fraction=amount/previous
                realized+=amount*price-fee-(remaining_costs[name]+remaining_fees[name])*fraction
                cash_flow+=amount*price-fee
                remaining_costs[name]=remaining_costs[name]*(quantities[name]/previous)
                remaining_fees[name]=remaining_fees[name]*(quantities[name]/previous)
        expected={name:q for name,q in quantities.items() if q}
        actual={}
        for p in snapshot['positions']:
            quantity=dec(p.get('size',0))
            if not quantity: continue
            if p.get('direction')=='sell': quantity=-abs(quantity)
            name=p.get('instrument_name')
            actual[name]=actual.get(name,Decimal(0))+quantity
        if expected!=actual:
            raise RuntimeErrorState('账户有外部持仓或本策略数量不符，不自动处置')
        if any(str(o.get('order_id')) not in owned for o in snapshot['open_orders']):
            raise RuntimeErrorState('账户存在外部挂单，停止新交易且不擅自撤销')
        if len(expected)>1:
            raise RuntimeErrorState('本策略同时持有多笔合约，停止新交易')
        run['ledger']={'currency':'BTC','evidence_type':'testnet_execution','trade_count':len(run['trades']),
                       'cash_flow_btc':str(cash_flow),'actual_fees_btc':str(fees),'realized_pnl_btc':str(realized),
                       'open_premium_cost_btc':str(sum(remaining_costs.values(),Decimal(0))),
                       'open_entry_fees_btc':str(sum(remaining_fees.values(),Decimal(0))),
                       'trade_ids':sorted(run['trades']), 'account_at':iso(snapshot['observed_at']),
                       'note':'仅本运行实际 Testnet 成交；开仓现金流不是已实现亏损，不是主网收益'}
        if expected:
            name,q=next(iter(expected.items()))
            instrument=next(i['instrument'] for i in run['intents'] if i['instrument_name']==name)
            run['position']={'instrument_name':name,'quantity':str(q),'average_price':str(remaining_costs[name]/q),
                             'expiration_timestamp':instrument['expiration_timestamp'],'instrument':instrument}
        else:
            run['position']=None
            run['exit_intent']=None

"""Offline HTTP workflow; fixture account is synthetic and cannot place orders.

Uses the real Flask routes, strategy store and runtime with explicit local-only
fixtures. No model, broker, market network, or production state is accessed.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from runtime import StrategyRuntimeService
from strategies import StrategyService

NOW = datetime(2026, 10, 5, 7, 59, 30, tzinfo=timezone.utc).timestamp()


class FixtureBroker:
    configured = True

    def __init__(self):
        self.calls = []

    def authenticate(self):
        self.calls.append('authenticate')

    def account_snapshot(self, since):
        self.calls.append('account_snapshot')
        return {'complete': True, 'environment': 'testnet', 'account_id': 'offline-api-account',
                'summary': {'currency': 'BTC', 'equity': 1, 'available_funds': 1,
                            'cross_collateral_enabled': False, 'fees': {}},
                'positions': [], 'open_orders': [], 'orders': [], 'trades': [],
                'observed_at': NOW, 'source_at': NOW, 'through_ms': int(NOW * 1000), 'since_ms': since}

    def close(self):
        pass


class FixtureMarket:
    def __init__(self):
        self.calls = []

    def candles(self, now, days=63):
        self.calls.append('candles')
        day = int(now // 86400) * 86400
        return {'result': {'status': 'ok',
                           'ticks': [(day - (61-i) * 86400) * 1000 for i in range(61)],
                           'close': [100] * 61},
                'received_at': NOW, 'source_at': NOW}

    def index(self):
        self.calls.append('index')
        return {'result': {'index_price': 100000}, 'received_at': NOW, 'source_at': NOW}

    def snapshot(self):
        return {'mode': 'synthetic offline fixture only'}

    def close(self):
        pass


class FixtureResearch:
    csrf_token = 'offline-workbench-csrf'
    availability = {'ready': True}
    active_id = None

    def __init__(self):
        self.calls = []

    def start(self, *args, **kwargs):
        self.calls.append('start')
        raise AssertionError('API boundary test must not start model research')

    def list_runs(self):
        return {'runs': []}

    def config_snapshot(self):
        return {'csrf_token': self.csrf_token, 'availability': self.availability,
                'configuration': {'limits': {'model_calls': 6, 'backtest_creations': 2}}}


class RuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # This suite exercises API authorization, not changing source-file hashes.
        self.identity_patch = patch('runtime.implementation_hash', return_value='f' * 64)
        self.identity_patch.start()
        self.addCleanup(self.identity_patch.stop)
        loaded_patch = patch('runtime.LOADED_IMPLEMENTATION_HASH', 'f' * 64)
        loaded_patch.start()
        self.addCleanup(loaded_patch.stop)
        self.broker, self.market, self.research = FixtureBroker(), FixtureMarket(), FixtureResearch()
        self.strategies = StrategyService(self.root, object(), self.research)
        self.runtime = StrategyRuntimeService(self.root, self.strategies, self.broker, self.market, lambda: NOW)
        self.app = create_app(self.market, research=self.research, strategies=self.strategies, runtime=self.runtime)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.headers = {'X-CSRF-Token': self.client.get('/api/strategies').get_json()['csrf_token'],
                        'Origin': 'http://localhost'}
        self.template = self.client.get('/api/strategy-templates').get_json()['templates'][0]

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, payload, **kwargs):
        return self.client.post(path, json=payload, headers=kwargs.pop('headers', self.headers), **kwargs)

    def create(self, spec=None):
        response = self.post('/api/strategies', {'name': '离线 API 案例', 'idea': '合成 fixture，仅作接口检查',
                                               'spec': spec or self.template['spec']})
        self.assertEqual(response.status_code, 201, response.get_json())
        detail = response.get_json()
        sid, vid = detail['strategy']['strategy_id'], detail['versions'][0]['version_id']
        return sid, vid, f'/api/strategies/{sid}/versions/{vid}'

    def approve_start(self):
        sid, vid, path = self.create()
        self.assertEqual(self.post(path+'/confirm', {'keys': [], 'use_defaults': True}).status_code, 200)
        self.assertEqual(self.post(path+'/freeze', {}).status_code, 200)
        payload = {'strategy_id': sid, 'version_id': vid, 'approved': True,
                   'idempotency_key': 'offline-api-idempotency'}
        result = self.post('/api/strategy-runs', payload)
        self.assertEqual(result.status_code, 201, result.get_json())
        return sid, vid, path, payload, result.get_json()['run_id']

    def test_confirmation_freeze_export_and_start_idempotency(self):
        sid, vid, path = self.create()
        detail = self.client.get(f'/api/strategies/{sid}').get_json()
        self.assertTrue(detail['versions'][0]['can_run_testnet'])
        self.assertFalse(detail['versions'][0]['can_validate'])
        self.assertFalse(detail['versions'][0]['onboarding_complete'])
        payload = {'strategy_id': sid, 'version_id': vid, 'approved': True,
                   'idempotency_key': 'offline-api-first-start'}
        self.assertEqual(self.post('/api/strategy-runs', payload).status_code, 409)
        self.assertFalse(self.broker.calls)
        partial = self.post(path+'/confirm', {'keys': ['fast_days'], 'use_defaults': False})
        self.assertEqual(partial.status_code, 200)
        self.assertFalse(partial.get_json()['versions'][0]['onboarding_complete'])
        confirmed = self.post(path+'/confirm', {'keys': [], 'use_defaults': True})
        self.assertTrue(confirmed.get_json()['versions'][0]['onboarding_complete'])
        frozen = self.post(path+'/freeze', {}).get_json()['versions'][0]
        self.assertEqual(frozen['status'], 'frozen')
        self.assertTrue(frozen['rules_sha256'])
        before = copy.deepcopy(self.strategies.detail(sid)['versions'][0])
        export = self.client.get(path+'/spec.md')
        self.assertEqual(export.status_code, 200)
        self.assertTrue(export.content_type.startswith('text/markdown'))
        self.assertIn(frozen['rules_sha256'], export.get_data(as_text=True))
        self.assertEqual(export.data, self.client.get(path+'/spec.md').data)
        self.assertEqual(before, self.strategies.detail(sid)['versions'][0])
        first = self.post('/api/strategy-runs', payload)
        self.assertEqual(first.status_code, 201, first.get_json())
        broker_calls = list(self.broker.calls)
        second = self.post('/api/strategy-runs', payload)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.get_json()['run_id'], second.get_json()['run_id'])
        self.assertEqual(broker_calls, self.broker.calls)
        self.assertEqual(len(self.runtime.runs), 1)
        self.assertIsNone(self.runtime.thread)

    def test_csrf_origin_and_unapproved_requests_cannot_touch_account(self):
        sid, vid, path = self.create()
        self.post(path+'/confirm', {'use_defaults': True})
        self.post(path+'/freeze', {})
        payload = {'strategy_id': sid, 'version_id': vid, 'approved': True,
                   'idempotency_key': 'offline-api-csrf-check'}
        for headers in ({}, {'X-CSRF-Token': 'wrong'},
                        {**self.headers, 'Origin': 'https://external.example'},
                        {**self.headers, 'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post('/api/strategy-runs', payload, headers=headers).status_code, 403)
        self.assertEqual(self.post('/api/strategy-runs', dict(payload, approved=False)).status_code, 409)
        self.assertEqual(self.post('/api/strategy-runs', dict(payload, environment='mainnet')).status_code, 409)
        self.assertFalse(self.broker.calls)
        self.assertFalse(self.runtime.runs)

    def test_page_gets_only_read_cached_state_and_never_start_threads(self):
        sid, vid, path, payload, rid = self.approve_start()
        before = list(self.broker.calls)
        for url in ('/', '/operations', '/api/strategy-templates', '/api/research/config',
                    '/api/research/runs', '/api/strategies', f'/api/strategies/{sid}', path+'/spec.md',
                    '/api/strategy-runs', '/api/strategy-runs?strategy_id='+sid, '/api/strategy-runs/'+rid):
            with self.subTest(url=url):
                with self.client.get(url) as response:
                    self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/strategy-runs?strategy_id=other').get_json()['runs'], [])
        self.assertEqual(before, self.broker.calls)
        self.assertFalse(self.market.calls)
        self.assertFalse(self.research.calls)
        self.assertIsNone(self.runtime.thread)
        self.assertEqual(self.runtime.runs[rid]['cycle_count'], 0)

    def test_capabilities_are_separate_and_rejected_validation_cannot_launch_model(self):
        sid, vid, path = self.create()
        payload = {'version_id': vid, 'purpose': 'validation', 'question': 'test capability only',
                   'approved': True, 'idempotency_key': 'offline-model-check', 'params': {}}
        rejected = self.post(f'/api/strategies/{sid}/research', payload)
        self.assertEqual(rejected.status_code, 409, rejected.get_json())
        self.assertFalse(self.research.calls)
        self.assertFalse(self.broker.calls)
        spec = {'kind': 'greeks_single_long', 'rules': {'option_type': 'call', 'delta': .5, 'expiry': 7,
                 'quantity': .01, 'session_bucket': '09:00:00', 'entry_weekdays': [0]}}
        gs, gv, _ = self.create(spec)
        version = self.client.get(f'/api/strategies/{gs}').get_json()['versions'][0]
        self.assertTrue(version['can_validate'])
        self.assertFalse(version['can_run_testnet'])
        rejected = self.post('/api/strategy-runs', {'strategy_id': gs, 'version_id': gv, 'approved': True,
                                                   'idempotency_key': 'offline-greeks-run'})
        self.assertEqual(rejected.status_code, 409)
        self.assertFalse(self.broker.calls)

    def test_human_gap_decision_can_support_trend_child_without_rewriting_parent(self):
        sid, vid, path, payload, rid = self.approve_start()
        parent = copy.deepcopy(self.strategies.detail(sid)['versions'][0])
        decision_response = self.post(f'/api/strategies/{sid}/decisions', {
            'version_id': vid, 'action': 'revise', 'review_kind': 'economic',
            'reason': '离线案例：尚无盈利证据，先降低每笔测试资金比例。',
            'evidence_refs': [], 'actor': 'offline-human'})
        self.assertEqual(decision_response.status_code, 200, decision_response.get_json())
        decision = decision_response.get_json()['decisions'][-1]
        self.assertEqual(decision['version_id'], vid)
        changed_rules = dict(parent['spec']['rules'], equity_fraction='0.005')
        revised = self.post(path+'/revisions', {
            'spec': {'kind': parent['spec']['kind'], 'rules': changed_rules},
            'change_kind': 'strategy_rules', 'evidence_refs': [decision['decision_id']],
            'reason': '记录缺口后由人类决定缩小预算', 'original_problem': '尚无策略盈利证据',
            'changes': '每笔预算比例从 1% 降到 0.5%', 'expected_improvement': '减少单笔测试风险敞口',
            'possible_harm': '更可能小于最小下单量', 'comparison_plan': '保留原记录；后续测试网交易分别计量，不拼接收益'})
        self.assertEqual(revised.status_code, 200, revised.get_json())
        detail = revised.get_json()
        old = next(v for v in detail['versions'] if v['version_id'] == vid)
        child = next(v for v in detail['versions'] if v['version_id'] != vid)
        self.assertEqual(old, parent)
        self.assertEqual(old['rules_sha256'], parent['rules_sha256'])
        self.assertEqual(child['parent_version'], vid)
        self.assertEqual(child['status'], 'draft')
        self.assertIsNone(child['rules_sha256'])
        self.assertFalse(child['onboarding_complete'])
        self.assertFalse(child.get('onboarding', {}).get('confirmed_keys'))
        self.assertEqual(child['revision']['evidence_refs'], [decision['decision_id']])
        self.assertEqual(child['spec']['rules']['equity_fraction'], '0.005')
        self.assertEqual(self.runtime.runs[rid]['version_id'], vid)
        self.assertEqual(self.runtime.runs[rid]['rules_sha256'], parent['rules_sha256'])
        self.assertFalse(self.research.calls)

    def test_pause_stop_reconcile_and_resume_keep_one_explicit_run(self):
        sid, vid, path, payload, rid = self.approve_start()
        base = '/api/strategy-runs/'+rid
        self.assertEqual(self.post(base+'/pause', {}).status_code, 200)
        self.assertTrue(self.runtime.runs[rid]['paused_entries'])
        self.assertEqual(self.post(base+'/stop', {}).status_code, 200)
        self.assertIsNone(self.runtime.active_id)
        before = len(self.broker.calls)
        denied = self.post(base+'/resume', {}, headers={})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(len(self.broker.calls), before)
        reconciled = self.post(base+'/reconcile', {})
        self.assertEqual(reconciled.status_code, 200, reconciled.get_json())
        self.assertIsNone(self.runtime.active_id)
        ledger = reconciled.get_json()['ledger']
        self.assertEqual(ledger['evidence_type'], 'testnet_execution')
        self.assertEqual(ledger['trade_count'], 0)
        self.assertEqual(ledger['trade_ids'], [])
        self.assertEqual(self.post(base+'/resume', {}).status_code, 200)
        self.assertEqual(self.runtime.active_id, rid)
        self.assertFalse(self.runtime.runs[rid]['resume_required'])
        self.assertEqual(self.post(base+'/pause', {'environment': 'mainnet'}).status_code, 409)
        self.assertEqual(len(self.runtime.runs), 1)
        self.assertFalse(self.research.calls)


if __name__ == '__main__':
    unittest.main()

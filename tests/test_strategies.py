"""Offline S4A identity/revision checks. All records below are synthetic temp files."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from backtest import BacktestError, validate_experiment
from strategies import StrategyError, StrategyService, normalize_spec

PARAMS = {'start_date': '2026-08-03', 'end_date': '2026-08-04', 'session_bucket': '09:00:00',
          'entry_weekdays': [0], 'option_type': 'call', 'delta': .5, 'expiry': 7,
          'quantity': .01, 'option_transaction_cost_bp': 1}
RULES = {k: v for k, v in PARAMS.items() if k not in {'start_date', 'end_date', 'option_transaction_cost_bp'}}
SPEC = {'kind': 'greeks_single_long', 'rules': RULES}
RID = 'a' * 32


class Backtests:
    def __init__(self):
        self.runs = {RID: {'run_id': RID, 'status': 'completed', 'request': validate_experiment(PARAMS),
            'analysis': {'model_ledger_verified': True, 'status': 'model_ledger_verified', 'position_status': 'closed',
                'premium_paid_btc': '.001', 'exit_income_btc': '.002', 'fees_btc': '.000002', 'btc_net_pnl': '.000998',
                'audit': {'daily_rows': 2, 'lot_count': 1, 'base_option_fee_bp': '1', 'traded_nominal_btc': '.02', 'trade_event_count': 2},
                'gaps': ['Synthetic offline ledger, not trading evidence']}}}

    def get_run(self, rid):
        if rid not in self.runs:
            raise BacktestError('no run')
        return copy.deepcopy(self.runs[rid])


class Research:
    def __init__(self):
        self.availability = {'ready': True}
        self.tasks = {}

    def detail(self, rid):
        return copy.deepcopy(self.tasks[rid])


class StrategiesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backtests, self.research = Backtests(), Research()
        self.service = StrategyService(self.root, self.backtests, self.research)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **changes):
        payload = dict(name='明确标记的离线案例', idea='只用于业务检查，不是真实研究', spec=SPEC)
        payload.update(changes)
        detail = self.service.create(payload)
        return detail['strategy']['strategy_id'], detail['versions'][0]['version_id']

    def link(self, sid, vid):
        return self.service.link_history(sid, vid, {'run_id': RID})

    def revision(self, **changes):
        payload = dict(reason='offline only', original_problem='synthetic observed failure', changes='call becomes put',
                       expected_improvement='unproven', possible_harm='opposite exposure', comparison_plan='common dates and costs',
                       spec={'kind': 'greeks_single_long', 'rules': dict(RULES, option_type='put')})
        payload.update(changes)
        return payload

    def test_model_proposal_cannot_lose_unsupported_conditions_on_adoption(self):
        sid, vid = self.create(spec=None)
        before = copy.deepcopy(self.service.detail(sid)['versions'][0])
        for field, condition in [('entry', '只在邻近盘口相对 ask 折价后买入'),
                                 ('exit', '亏损达到百分之十止损'),
                                 ('position_constraints', '总权利金不得超过 0.001 BTC'),
                                 ('data_requirements', '逐笔主动卖出方向和同步深度')]:
            with self.subTest(field=field), self.assertRaises(StrategyError):
                self.service.update_version(sid, vid, {'spec': {**SPEC, field: condition}})
            self.assertEqual(self.service.detail(sid)['versions'][0], before)
        with self.assertRaises(StrategyError):
            normalize_spec({**SPEC, 'stop_loss': .1})
        with self.assertRaises(StrategyError):
            normalize_spec({**SPEC, 'implementation_task': '新增盘口退出算法'})
        # Empty descriptors explicitly select the existing adapter. Re-saving
        # its exact normalized form is stable; free-form paraphrases are not
        # guessed to be semantically equivalent.
        canonical = normalize_spec(SPEC)
        self.assertEqual(normalize_spec(canonical), canonical)
        self.assertEqual(normalize_spec({**SPEC, **{key: '' for key in ('contract_selection', 'entry', 'exit', 'position_constraints', 'decision_frequency', 'data_requirements', 'clock')}}), canonical)
        with self.assertRaises(StrategyError):
            normalize_spec({**canonical, 'rules': dict(RULES, option_type='put')})
        self.assertEqual(normalize_spec({'kind': 'greeks_single_long', 'rules': dict(RULES, option_type='put')})['rules']['option_type'], 'put')
        pending = normalize_spec({'kind': 'unimplemented', 'rules': None, 'exit': '亏损达到百分之十止损'})
        self.assertEqual(pending['exit'], '亏损达到百分之十止损')
        self.assertEqual(pending['implementation_status'], 'pending')

    def test_url_is_not_read_content_and_unsupported_spec_stays_unimplemented(self):
        sid, vid = self.create(spec=None, source={'kind': 'provided_material', 'url': 'https://example.test/idea', 'content_status': 'not_retrieved'})
        detail = self.service.detail(sid)
        self.assertEqual(detail['strategy']['source']['content_status'], 'not_retrieved')
        self.assertEqual(detail['versions'][0]['spec_status'], 'incomplete')
        with self.assertRaises(StrategyError):
            self.service.prepare_research(sid, vid, dict(purpose='validation', approved=True, idempotency_key='offline-task-one', question='test objective', params=PARAMS))
        with self.assertRaises(StrategyError):
            self.create(source={'kind': 'provided_material', 'url': 'https://example.test/idea', 'content_status': 'retrieved'})

    def test_historical_link_freezes_and_does_not_mutate_original(self):
        before = copy.deepcopy(self.backtests.runs)
        sid, vid = self.create()
        detail = self.link(sid, vid)
        self.assertEqual(detail['versions'][0]['status'], 'frozen')
        self.assertEqual(detail['validations'][0]['run_ids'], [RID])
        self.assertEqual(self.backtests.runs, before)
        with self.assertRaises(StrategyError):
            self.service.update_version(sid, vid, {'spec': dict(SPEC)})
        restarted = StrategyService(self.root, self.backtests, self.research)
        self.assertEqual(restarted.detail(sid)['validations'][0]['run_ids'], [RID])
        self.assertEqual(restarted.detail(sid)['research_tasks'], [])

    def test_cross_identity_evidence_and_mismatched_rules_are_rejected(self):
        sid, vid = self.create()
        evidence = self.link(sid, vid)['validations'][0]['validation_id']
        other, other_v = self.create()
        with self.assertRaises(StrategyError):
            self.service.add_decision(other, other_v, dict(action='retain', reason='wrong identity', evidence_refs=[evidence]))
        with self.assertRaises(StrategyError):
            self.service.update_version(other, vid, {'spec': SPEC})
        changed = dict(SPEC, rules=dict(RULES, quantity=.02))
        self.service.update_version(other, other_v, {'spec': changed})
        with self.assertRaises(StrategyError):
            self.link(other, other_v)

    def test_revision_requires_real_rule_change_and_records_tradeoffs(self):
        sid, vid = self.create()
        evidence = self.link(sid, vid)['validations'][0]['validation_id']
        with self.assertRaises(StrategyError):
            self.service.revise(sid, vid, self.revision(spec=SPEC, evidence_refs=[evidence]))
        with self.assertRaises(StrategyError):
            self.service.revise(sid, vid, self.revision(change_kind='engineering_repair', evidence_refs=[evidence]))
        detail = self.service.revise(sid, vid, self.revision(evidence_refs=[evidence]))
        self.assertEqual(detail['versions'][-1]['parent_version'], vid)
        self.assertEqual(detail['versions'][-1]['revision']['possible_harm'], 'opposite exposure')
        self.assertEqual(detail['versions'][0]['spec']['rules']['option_type'], 'call')
        self.assertFalse(detail['comparison'][0]['comparable'])

    def test_approved_request_cannot_change_frozen_rules_or_seen_data_label(self):
        sid, vid = self.create()
        self.link(sid, vid)
        payload = dict(purpose='validation', approved=True, idempotency_key='offline-approval-one', question='offline comparison', params=PARAMS)
        with self.assertRaises(StrategyError):
            self.service.prepare_research(sid, vid, dict(payload, data_role='validation'))
        with self.assertRaises(StrategyError):
            self.service.prepare_research(sid, vid, dict(payload, params=dict(PARAMS, quantity=.02)))
        prepared = self.service.prepare_research(sid, vid, payload)
        self.assertEqual(self.service.prepare_research(sid, vid, payload), prepared)
        with self.assertRaises(StrategyError):
            self.service.prepare_research(sid, vid, dict(payload, question='different goal'))
        validation = self.service.detail(sid)['validations'][-1]
        self.assertEqual(validation['data_role'], 'research')
        self.assertTrue(validation['seen_overlaps'])

    def test_task_binding_and_all_attempts_survive_restart_without_launch(self):
        sid, vid = self.create()
        prepared = self.service.prepare_research(sid, vid, dict(purpose='validation', approved=True, idempotency_key='offline-task-binding', question='offline comparison', params=PARAMS))
        research_id = 'b' * 32
        self.research.tasks[research_id] = {'research_id': research_id, 'strategy_context': prepared['context'], 'idempotency_key': 'offline-task-binding', 'question': 'offline comparison', 'status': 'completed',
             'budget': {}, 'actions': [{'action': 'run_backtest', 'run_id': RID}], 'evidence': [], 'final': None}
        self.service.bind_research(prepared['binding_id'], research_id)
        self.assertEqual(self.service.detail(sid)['validations'][0]['run_ids'], [RID])
        restarted = StrategyService(self.root, self.backtests, self.research)
        self.assertEqual(restarted.detail(sid)['validations'][0]['research_id'], research_id)
        self.assertEqual(len(restarted.data['research_tasks']), 1)
        self.assertFalse(hasattr(restarted, 'worker'))

    def test_fee_scenario_is_new_validation_and_engineering_review_no_version(self):
        sid, vid = self.create()
        evidence = self.link(sid, vid)['validations'][0]['validation_id']
        detail = self.service.fee_scenario(sid, vid, {'validation_id': evidence, 'higher_fee_bp': 5})
        self.assertEqual(len(detail['versions']), 1)
        self.assertEqual(detail['validations'][-1]['change_kind'], 'cost_scenario')
        self.assertEqual(detail['validations'][-1]['charts'][0]['fees']['fee_comparison']['higher_net_btc'], '0.00099')
        detail = self.service.add_decision(sid, vid, dict(action='continue_validation', reason='repair offline accounting', review_kind='engineering_repair', evidence_refs=[evidence]))
        self.assertEqual(len(detail['versions']), 1)
        self.assertEqual(detail['decisions'][0]['review_kind'], 'engineering_repair')

    def test_chart_uses_actual_daily_values_and_refuses_gap_or_unknown(self):
        sid, vid = self.create()
        self.link(sid, vid)
        directory = self.root / 'local' / 'backtests' / RID
        directory.mkdir(parents=True)
        header = 'date,asset,numeraire,daily_return_valid,valuation_complete,result_complete,total_pnl,cum_pnl\n'
        body = '2026-08-03,BTC,BTC,True,True,True,-.000001,-.000001\n2026-08-04,BTC,BTC,True,True,True,.000999,.000998\n'
        path = directory / 'daily.csv'
        path.write_text(header + body)
        chart = self.service.detail(sid)['validations'][0]['charts'][0]
        self.assertEqual(chart['cumulative']['points'][-1]['cumulative_btc'], '0.000998')
        self.assertEqual(chart['cumulative']['points'][-1]['source']['row'], 3)
        path.write_text(header + body.replace('2026-08-04', '2026-08-05'))
        self.assertIsNone(self.service.detail(sid)['validations'][0]['charts'][0]['cumulative'])
        path.write_text(header + body.replace('True,True,True,.000999', 'False,True,True,.000999'))
        self.assertIsNone(self.service.detail(sid)['validations'][0]['charts'][0]['cumulative'])

    def test_seen_global_history_revision_context_and_actual_fee_comparison(self):
        sid, vid = self.create()
        approval = dict(purpose='validation', approved=True, idempotency_key='offline-seen-global', question='offline result reuse', params=PARAMS, data_role='validation')
        with self.assertRaises(StrategyError):
            self.service.prepare_research(sid, vid, approval)
        evidence = self.link(sid, vid)['validations'][0]['validation_id']
        prepared = self.service.prepare_research(sid, vid, dict(purpose='revision', approved=True, idempotency_key='offline-revision-evidence', question='explain specific evidence', evidence_refs=[evidence]))
        self.assertEqual(prepared['context']['available_run_ids'], [RID])
        self.assertEqual(prepared['context']['evidence'][0]['results'][0]['accounting']['btc_net_pnl'], '.000998')
        self.assertNotIn('rows', prepared['context']['evidence'][0]['results'][0]['accounting'])
        detail = self.service.revise(sid, vid, self.revision(evidence_refs=[evidence]))
        child = detail['versions'][-1]['version_id']
        child_run = 'c' * 32
        self.backtests.runs[child_run] = dict(copy.deepcopy(self.backtests.runs[RID]), run_id=child_run, request=validate_experiment(dict(PARAMS, option_type='put')))
        new_evidence = self.service.link_history(sid, child, {'run_id': child_run})['validations'][-1]['validation_id']
        detail = self.service.fee_scenario(sid, child, {'validation_id': new_evidence, 'higher_fee_bp': 5})
        self.assertFalse(detail['comparison'][0]['comparable'])
        self.assertIn('cost_assumption_bp', detail['comparison'][0]['differences'])
        self.assertIsNone(detail['validations'][-1]['charts'][0]['cumulative'])

    def test_exact_orphan_intent_is_bound_before_resume_and_mismatch_refused(self):
        sid, vid = self.create()
        prepared = self.service.prepare_research(sid, vid, dict(purpose='validation', approved=True, idempotency_key='offline-orphan-recovery', question='offline orphan objective', params=PARAMS))
        rid = 'd' * 32
        self.research.tasks[rid] = {'research_id': rid, 'strategy_context': prepared['context'], 'idempotency_key': 'offline-orphan-recovery',
                                  'question': 'offline orphan objective', 'status': 'paused', 'budget': {}, 'actions': [], 'evidence': []}
        restarted = StrategyService(self.root, self.backtests, self.research)
        binding = restarted.ensure_research_binding(rid)
        self.assertEqual(binding['research_id'], rid)
        self.assertEqual(json.loads(restarted.path.read_text())['validations'][0]['research_id'], rid)
        self.research.tasks[rid]['strategy_context']['approved_experiment']['quantity'] = .2
        with self.assertRaises(StrategyError):
            restarted.ensure_research_binding(rid)

    def test_frozen_file_tampering_fails_closed_without_erasing_file(self):
        sid, vid = self.create()
        self.link(sid, vid)
        value = json.loads(self.service.path.read_text())
        value['versions'][0]['spec']['rules']['quantity'] = .02
        self.service.path.write_text(json.dumps(value))
        before = self.service.path.read_bytes()
        restarted = StrategyService(self.root, self.backtests, self.research)
        self.assertTrue(restarted.storage_error)
        with self.assertRaises(StrategyError):
            restarted.create(dict(name='must not save', idea='synthetic test'))
        self.assertEqual(self.service.path.read_bytes(), before)
        self.assertEqual(restarted.snapshot()['strategies'], [])


if __name__ == '__main__':
    unittest.main()

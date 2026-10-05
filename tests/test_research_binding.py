"""Offline regression for task ownership and proposal tool boundaries."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from research import ResearchError, ResearchService, verify_action
from s3_research_check import FakeBacktests, FakeRunner, action, finish, PARAMS, PLAN, wait_idle, fixture_root

ROOT = Path(__file__).resolve().parents[1]


class ResearchBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = fixture_root(Path(self.tmp.name))
        for name in ('proposal-prompt.md', 'proposal.schema.json'):
            shutil.copyfile(ROOT / 'researcher' / name, self.root / 'researcher' / name)
        self.backtests = FakeBacktests()
        self.context = dict(strategy_id='1'*32, version_id='2'*32, purpose='validation',
                            approved_experiment=copy.deepcopy(PARAMS), available_run_ids=[])

    def manager(self, chooser):
        runner = FakeRunner(chooser)
        manager = ResearchService(self.root, self.backtests, runner=runner,
                                  availability=dict(ready=True, reason='offline fixture'))
        self.addCleanup(manager.stop)
        return manager, runner

    def test_changed_rules_or_window_rejected_before_remote_call(self):
        task = dict(strategy_context=self.context, available_run_ids=[])
        for field, replacement in [('option_type','call'), ('end_date','2026-06-03'), ('quantity',.02)]:
            params = {**PARAMS, field: replacement}
            with self.assertRaisesRegex(ValueError, '批准'):
                verify_action(action('run_backtest',experiment=params,plan=PLAN), task)
        verify_action(action('run_backtest',experiment=PARAMS,plan=PLAN), task)
        self.assertEqual(self.backtests.creations, 0)

    def test_prepared_task_does_not_start_until_binding_saved(self):
        def chooser(data, number):
            return action('run_backtest',experiment=PARAMS,plan=PLAN) if number == 1 else finish(data)
        manager, runner = self.manager(chooser)
        rid = manager.start('离线检查已冻结版本的实际验证', True, 'bound-prepare-01', context=self.context, defer_launch=True)
        self.assertEqual(runner.calls, [])
        self.assertEqual(manager.detail(rid)['available_run_ids'], [])
        manager.launch_prepared(rid)
        wait_idle(manager)
        saved = manager.detail(rid)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['strategy_context'], self.context)
        self.assertEqual(len(saved['evidence']), 1)
        self.assertEqual(manager.start('离线检查已冻结版本的实际验证', True, 'bound-prepare-01', context=self.context, defer_launch=True), rid)
        self.assertEqual(len(runner.calls), 2)
        with self.assertRaises(ResearchError):
            manager.start('离线检查已冻结版本的实际验证', True, 'bound-prepare-01', context={**self.context,'version_id':'3'*32})

    def test_proposal_completes_without_backtest_connection_or_code(self):
        spec = dict(kind='unimplemented', rules=None, **{key:'需要补充' for key in
                    ('contract_selection','entry','exit','position_constraints','decision_frequency','data_requirements','clock')})
        proposal = dict(economic_hypothesis='离线待验证', failure_mechanisms=['缺少数据'], data_requirements=['同步盘口'],
                        candidate_spec=spec, validation_method='取得数据后确定性回放', unknowns=['价格未知'], disposition='draft', implementation_task='实现逐笔方向和同步报价读取')
        output = dict(schema_version='strategy-proposal-v1', action='propose', explanation='离线提案', proposal=proposal)
        manager, runner = self.manager(lambda *_: output)
        self.backtests.capability_status='unchecked'
        rid = manager.start('离线形成提案检查，不代表真实研究',True,'proposal-bound-01',context={**self.context,'purpose':'proposal'})
        wait_idle(manager)
        saved = manager.detail(rid)
        self.assertEqual(saved['status'],'completed')
        self.assertEqual(saved['model_proposal'],proposal)
        self.assertEqual(self.backtests.connection_checks,0)
        self.assertEqual(self.backtests.creations,0)
        self.assertEqual(len(runner.calls),1)

    def test_prepared_restart_is_paused_and_requires_explicit_resume(self):
        manager, runner = self.manager(lambda data, number: finish(data))
        rid = manager.start('离线重启不可自动执行',True,'bound-restart-01',context=self.context,defer_launch=True)
        restarted = ResearchService(self.root,self.backtests,runner=runner,availability=dict(ready=True))
        self.addCleanup(restarted.stop)
        self.assertEqual(restarted.detail(rid)['status'],'paused')
        self.assertEqual(runner.calls,[])
        self.assertIsNone(restarted.active_id)


if __name__ == '__main__':
    unittest.main()

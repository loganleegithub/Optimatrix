"""Explicit, disposable offline browser acceptance service; never real research.

Run only when requested:
    .venv/bin/python tests/s4a_browser_fixture.py

Opens only http://127.0.0.1:8766. Ctrl-C / SIGTERM closes the server and
deletes its temporary store. It does not read .env, use Codex, fetch quotes,
or change this repository's local/ records. Every page is visibly marked.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import csv
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from app import create_app
from backtest import EXPERIMENT, BacktestError
from market import iso
from research import ResearchService
from strategies import RULE_FIELDS, StrategyService
from s3_research_check import FakeBacktests, FakeRunner, PARAMS, PLAN, action, finish

MODE = '离线合成验收 · 非真实策略 / 非真实行情 / 无真实模型或远端回测调用'


def prohibited(*args, **kwargs):
    raise AssertionError('Offline browser fixture forbids outbound networking and subprocesses')


class BrowserBacktests(FakeBacktests):
    """Synthetic records solely for checking the real UI/ledger interfaces."""
    def __init__(self, root):
        self.root = root
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__()

    def record(self, run_id, params=PARAMS):
        record = super().record(run_id, params)
        quantity = Decimal(str(params['quantity']))
        rate = Decimal(str(params['option_transaction_cost_bp']))
        premium, income, nominal = quantity * Decimal('.02'), quantity * Decimal('.03'), quantity * 2
        fees = nominal * rate / 10000
        net = income - premium - fees
        start, end = date.fromisoformat(params['start_date']), date.fromisoformat(params['end_date'])
        count = (end - start).days + 1
        record.update(created_at=iso(), service_task_id='offline-synthetic-only',
                      experiment_id='OFFLINE_BROWSER_FIXTURE', error=None)
        record['analysis'].update(premium_paid_btc=str(premium), exit_income_btc=str(income),
            fees_btc=str(fees), btc_net_pnl=str(net),
            hypothetical_account_return_pct=str(net / Decimal('.2') * 100),
            price_source=MODE, fee_assumption=f'离线合成条件：每次名义额 {rate} bp；不是实际费率',
            gaps=['完全合成的软件验收案例，没有市场、执行或盈利证据；改 Delta 不代表改善。'])
        record['analysis']['audit'].update(base_option_fee_bp=str(rate), traded_nominal_btc=str(nominal),
                                          lot_count=1, daily_rows=count)
        folder = self.root / 'local' / 'backtests' / run_id
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'daily.csv').open('w', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=['date', 'asset', 'numeraire', 'daily_return_valid',
                'valuation_complete', 'result_complete', 'total_pnl', 'cum_pnl'])
            writer.writeheader()
            for index in range(count):
                value = net if index == count - 1 else Decimal(0)
                writer.writerow(dict(date=(start + timedelta(days=index)).isoformat(), asset='BTC', numeraire='BTC',
                    daily_return_valid='True', valuation_complete='True', result_complete='True',
                    total_pnl=str(value), cum_pnl=str(value)))
        return record

    def snapshot(self):
        value = super().snapshot()
        value.update(csrf_token=self.csrf_token, configuration={'configured': False, 'reason': MODE},
                     experiment={**copy.deepcopy(EXPERIMENT), 'title': MODE}, mode=MODE)
        value['capabilities']['reason'] = MODE
        return value

    def tool_capabilities(self):
        return {**super().tool_capabilities(), 'source': MODE, 'live_services': False}

    def get_run(self, run_id):
        if run_id not in self.runs:
            raise BacktestError('离线案例没有此回测记录')
        return super().get_run(run_id)


class EmptyMarket:
    def snapshot(self):
        return {'server_time': iso(), 'started_at': iso(), 'sequence': 0, 'refresh_seconds': 5,
                'stale_seconds': 15, 'index': None, 'options': [],
                'catalog': {'count': 0, 'source_at': None, 'received_at': None, 'error': MODE},
                'collector': {'running': False, 'last_attempt_at': None, 'last_success_at': None, 'error': MODE},
                'integrations': {'account': '未接入', 'agent': MODE, 'codex': {'installed': False, 'login_status': '离线，未检查'}},
                'mode': MODE}


def choose_action(input_data, _number):
    context = input_data['strategy_context']
    if context['purpose'] in {'proposal', 'revision'}:
        spec = copy.deepcopy(context['version']['spec'])
        # The real proposal schema deliberately excludes implementation metadata.
        spec = {key: value for key, value in spec.items() if key in {
            'kind', 'rules', 'contract_selection', 'entry', 'exit', 'position_constraints',
            'decision_frequency', 'data_requirements', 'clock'}}
        if spec['kind'] == 'unimplemented':
            spec['rules'] = None
        return {'schema_version': 'strategy-proposal-v1', 'action': 'propose', 'explanation': MODE,
                'proposal': {'economic_hypothesis': '离线软件案例，无真实经济判断',
                    'failure_mechanisms': ['合成结果没有市场含义'], 'data_requirements': ['真实市场数据尚未用于本案例'],
                    'candidate_spec': spec, 'validation_method': '仅检查批准、绑定、冻结、修订与复验的软件流程',
                    'unknowns': ['实际收益及执行均未知'], 'disposition': 'draft',
                    'implementation_task': '本离线服务不创建真实实现任务'}}
    if not input_data['actions']:
        return action('run_backtest', experiment=copy.deepcopy(context['approved_experiment']),
                      plan={**PLAN, 'hypothesis': MODE})
    return finish(input_data)


def build_fixture(root):
    """No server or model side effects; root must be an isolated temporary path."""
    root = Path(root).resolve()
    if root == ROOT or ROOT in root.parents:
        raise ValueError('Fixture storage must be outside the repository')
    (root / 'researcher').mkdir(parents=True)
    for name in ('config.json', 'prompt.md', 'output.schema.json', 'proposal-prompt.md', 'proposal.schema.json'):
        shutil.copyfile(ROOT / 'researcher' / name, root / 'researcher' / name)
    backtests = BrowserBacktests(root)
    runner = FakeRunner(choose_action)
    research = ResearchService(root, backtests, runner=runner,
        availability={'ready': True, 'reason': MODE, 'cli_version': 'NOT_INVOKED',
                      'login_status': 'NOT_CHECKED', 'runtime_snapshot': {'fixture': True, 'live_model_calls': 0}})
    strategies = StrategyService(root, backtests, research)
    detail = strategies.create({'name': '离线案例 · 修订流程（非真实策略）',
        'idea': '仅用于操作验收：先保存工程复核，再按合成证据记录经济修订、创建子版本并复验。不是实际策略改善。',
        'economic_hypothesis': '离线合成的软件流程案例；没有盈利假设获得支持',
        'failure_mechanisms': '这些值是合成记录，不能推断真实收益或执行能力。',
        'spec': {'kind': 'greeks_single_long', 'rules': {key: PARAMS[key] for key in RULE_FIELDS}}})
    sid, vid = detail['strategy']['strategy_id'], detail['strategy']['current_version_id']
    strategies.link_history(sid, vid, {'run_id': backtests.history, 'purpose': '明确标记的合成匹配记录，仅检查页面与修订流程'})
    app = create_app(EmptyMarket(), backtests, research, strategies)

    @app.after_request
    def mark_offline(response):
        response.headers['X-Optimatrix-Evidence'] = 'offline-synthetic-fixture; no-real-model-or-market'
        if response.is_json:
            value = response.get_json(silent=True)
            if isinstance(value, dict):
                value['mode'] = MODE
                value['offline_fixture'] = True
                response.set_data(app.json.dumps(value))
        elif response.mimetype == 'text/html' and not response.is_streamed:
            text = response.get_data(as_text=True)
            response.set_data(text.replace('<body>', '<body><div class="mode-notice" role="note"><strong>' + MODE + '</strong>临时数据，退出即删除；不计入真实研究消耗。</div>', 1))
        elif response.mimetype == 'text/html':
            # send_from_directory uses passthrough: safely buffer only the small HTML page.
            response.direct_passthrough = False
            text = response.get_data(as_text=True)
            response.set_data(text.replace('<body>', '<body><div class="mode-notice" role="note"><strong>' + MODE + '</strong>临时数据，退出即删除；不计入真实研究消耗。</div>', 1))
        return response

    return app, research, strategies, runner, sid


def main():
    # This is not imported by production startup or unittest discovery.
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    with tempfile.TemporaryDirectory(prefix='optimatrix-s4a-browser-offline-') as folder, ExitStack() as guards:
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection',
                       'subprocess.Popen', 'subprocess.run', 'requests.sessions.Session.send'):
            guards.enter_context(patch(target, prohibited))
        app, research, strategies, runner, sid = build_fixture(folder)
        server = None
        try:
            server = make_server('127.0.0.1', 8766, app)
            print(json.dumps({'mode': MODE, 'url': f'http://127.0.0.1:8766/strategies?strategy_id={sid}',
                              'temporary_root': folder, 'live_model_calls': 0, 'live_backtest_creations': 0}, ensure_ascii=False), flush=True)
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass
        finally:
            research.stop()
            if server is not None:
                server.server_close()
            print('离线浏览器验收服务已停止；临时数据即将删除。真实模型 / 远端调用均为 0。', flush=True)


if __name__ == '__main__':
    main()

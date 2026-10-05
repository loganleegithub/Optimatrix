"""Repeatable S4A offline business evidence; no model or remote network calls.

Synthetic scenario lives only in TemporaryDirectory. Optional real-history
projection reads existing bytes and never rewrites original S2/S3 records.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market import iso
from strategies import StrategyError, StrategyService
from test_strategies import Backtests, Research, PARAMS, RID, RULES, SPEC
from backtest import parameters_from_request, validate_experiment

ROOT = Path(__file__).resolve().parents[1]


def run_synthetic():
    with tempfile.TemporaryDirectory(prefix='optimatrix-s4a-offline-') as directory:
        backtests, research = Backtests(), Research()
        service = StrategyService(directory, backtests, research)
        detail = service.create({'name': '离线业务案例 / 非真实策略改善', 'idea': '仅测试证据关联与修订控制，不是交易提案', 'spec': SPEC})
        sid, v1 = detail['strategy']['strategy_id'], detail['versions'][0]['version_id']
        detail = service.link_history(sid, v1, {'run_id': RID, 'purpose': '明确标记的合成 v1 验证'})
        first = detail['validations'][0]['validation_id']
        detail = service.add_decision(sid, v1, {'action': 'revise', 'reason': '合成案例中预设反例触发规则修订，仅用于检查', 'evidence_refs': [first], 'actor': '离线检查程序 / 非真实人类决定'})
        detail = service.revise(sid, v1, {'spec': {'kind': 'greeks_single_long', 'rules': dict(RULES, option_type='put')},
            'reason': '合成规则修改检查', 'original_problem': '合成反例，不代表真实市场发现',
            'changes': 'Call 修改为 Put', 'expected_improvement': '仅测试方向规则变更，未预期或宣称收益改善',
            'possible_harm': '失去上涨敞口，增加下跌假设依赖', 'comparison_plan': '同日期、时段、数量与费用，明确已见研究段', 'evidence_refs': [first]})
        v2 = detail['versions'][-1]['version_id']
        rejected_unseen = False
        request = dict(PARAMS, option_type='put')
        approval = dict(purpose='validation', approved=True, idempotency_key='s4a-offline-v2-validation', question='离线合成子版本复验', params=request)
        try:
            service.prepare_research(sid, v2, dict(approval, data_role='validation'))
        except StrategyError:
            rejected_unseen = True
        prepared = service.prepare_research(sid, v2, dict(approval, data_role='research'))
        rid, research_id = 'c' * 32, 'd' * 32
        backtests.runs[rid] = dict(copy.deepcopy(backtests.runs[RID]), run_id=rid, request=validate_experiment(request))
        research.tasks[research_id] = {'research_id': research_id, 'question': approval['question'], 'idempotency_key': approval['idempotency_key'],
            'strategy_context': prepared['context'], 'status': 'completed', 'budget': {'model_calls_used': 0, 'backtest_creations_used': 0},
            'actions': [{'action': 'run_backtest', 'run_id': rid}], 'evidence': [], 'final': None}
        service.bind_research(prepared['binding_id'], research_id)
        detail = service.detail(sid)
        second = detail['validations'][-1]['validation_id']
        detail = service.add_decision(sid, v2, {'action': 'retain', 'reason': '合成流程完成；不是经济支持', 'evidence_refs': [second], 'actor': '离线检查程序 / 非真实人类决定'})
        restarted = StrategyService(directory, backtests, research).detail(sid)
        assert rejected_unseen and restarted['versions'][-1]['parent_version'] == v1
        assert len(restarted['validations']) == 2 and len(restarted['decisions']) == 2
        assert restarted['comparison'][0]['comparable'] is True
        return {'classification': 'synthetic_offline_only', 'real_model_calls': 0, 'real_remote_creations': 0,
                'scenario': 'v1 验证 → 保存修订决定 → 有依据字段的 v2 → 同条件已见研究段复验 → 保存保留决定 → 重启历史重开',
                'strategy_id': sid, 'versions': [{k: v[k] for k in ('version_id', 'label', 'parent_version', 'status')} for v in restarted['versions']],
                'validations': [{k: v[k] for k in ('validation_id', 'version_id', 'run_ids', 'data_role', 'research_id')} for v in restarted['validations']],
                'decisions': restarted['decisions'], 'comparison': restarted['comparison'], 'unseen_relabel_rejected': rejected_unseen,
                'restart_preserved': True, 'economic_improvement_established': False}


def real_history_projection():
    paths = sorted((ROOT/'local/backtests').glob('*/run.json'))
    if not paths:
        return {'status': 'unavailable', 'reason': '本机没有真实历史；不使用合成记录替代'}
    outputs = []
    with tempfile.TemporaryDirectory(prefix='optimatrix-s4a-real-readonly-') as directory:
        backtests = Backtests()
        backtests.runs = {json.loads(path.read_text())['run_id']: json.loads(path.read_text()) for path in paths}
        for path in paths:
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            record = json.loads(path.read_text())
            params = parameters_from_request(record['request'])
            service = StrategyService(directory, backtests)
            detail = service.create({'name': '真实历史只读投影 / 不批准策略', 'idea': '既有原始回测，仅离线检查策略关联和图表来源',
                'source': {'kind': 'historical_research', 'content': '本机已保存 Greeks.live run；原始输入和结果不修改', 'content_status': 'provided'},
                'spec': {'kind': 'greeks_single_long', 'rules': {k: params[k] for k in RULES}}})
            sid, vid = detail['strategy']['strategy_id'], detail['versions'][0]['version_id']
            daily = path.parent/'daily.csv'
            if daily.exists():
                destination = Path(directory)/'local/backtests'/record['run_id']/'daily.csv'
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(daily.read_bytes())
            detail = service.link_history(sid, vid, {'run_id': record['run_id']})
            validation, = detail['validations']
            chart, = validation['charts']
            assert before == hashlib.sha256(path.read_bytes()).hexdigest()
            outputs.append({'run_id': record['run_id'], 'original_run_sha256': before, 'original_unchanged': True,
                'model_ledger_verified': validation['accounting_status'] == 'verified',
                'cumulative_daily_points': len((chart['cumulative'] or {}).get('points', [])),
                'daily_source_sha256': (chart['cumulative'] or {}).get('source_sha256'), 'chart_gaps': chart['chart_gaps'],
                'currency': chart['metadata']['currency'], 'price_basis': chart['metadata']['price_basis'],
                'sample_count': chart['metadata']['sample_count'], 'production_strategy_written': False})
    return {'status': 'read_only_projection_complete', 'records': outputs, 'new_model_or_remote_calls': 0}


if __name__ == '__main__':
    evidence = {'stage': 'S4A', 'generated_at': iso(), 'synthetic_business_check': run_synthetic(), 'real_saved_history': real_history_projection()}
    path = ROOT/'local/s4a-check/offline-check.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'artifact': str(path), 'synthetic_business_check': 'passed', 'real_saved_history': evidence['real_saved_history']['status'],
                      'model_calls': 0, 'remote_creations': 0}, ensure_ascii=False))

"""Replay the saved live S3 evidence offline; never create a model or backtest call."""
import hashlib
import json
from pathlib import Path
import sys
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backtest import save_json
from btc_accounting import analyze_report, compare_fee_scenario
from research import verify_action
from researcher_cli import CodexRunner

RID='bde2026f95b24da5bea7ce8ca80755e8'

def main():
    task_path=ROOT/'local/research'/RID/'research.json'
    if not task_path.exists():
        print('本机没有原始真实研究文件；不会用合成数据冒充。GitHub 小样例见 docs/samples/s3-research.json。')
        return 2
    task=json.loads(task_path.read_text())
    assert task['status']=='completed'
    assert task['budget']['model_calls_used']==6 and task['budget']['backtest_creations_used']==2
    final=CodexRunner.read_result(task_path.parent/'call-6',task['schema_snapshot'])
    verify_action(final,task)
    rows=[]
    for evidence in task['evidence']:
        directory=ROOT/'local/backtests'/evidence['run_id']
        merged={}
        for name in ('status.raw.json','report.raw.json'):
            if (directory/name).exists(): merged.update(json.loads((directory/name).read_text()))
        files={k:directory/n for k,n in [('csv','details.csv'),('daily_csv','daily.csv'),('report','report.txt')]}
        accounting=analyze_report(merged,files)
        assert accounting['model_ledger_verified']
        for key in ('btc_net_pnl','premium_paid_btc','exit_income_btc','fees_btc'):
            assert accounting[key]==evidence['accounting'][key],key
        fees=compare_fee_scenario(accounting,evidence['fee_comparison']['higher_fee_bp'],run_id=evidence['run_id'])
        assert fees==evidence['fee_comparison']
        assert Decimal(accounting['btc_net_pnl'])==Decimal(accounting['exit_income_btc'])-Decimal(accounting['premium_paid_btc'])-Decimal(accounting['fees_btc'])
        rows.append({'run_id':evidence['run_id'],'model_ledger_verified':True,'btc_net_pnl':accounting['btc_net_pnl'],
            'higher_fee_net_btc':fees['higher_net_btc'],'raw_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files.values()}})
    artifact={'kind':'offline_replay_of_saved_live_evidence','research_id':RID,'passed':True,'runs':rows,
              'new_model_calls':0,'new_remote_calls':0,'verified_final_claims':len(task['final']['claims'])}
    save_json(ROOT/'local/s3-validation/live-replay.json',artifact)
    print(json.dumps(artifact,ensure_ascii=False))
    return 0

if __name__=='__main__': raise SystemExit(main())

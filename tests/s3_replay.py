"""Replay the saved live S3 evidence offline; never create a model or backtest call."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backtest import save_json
from btc_accounting import analyze_report, compare_fee_scenario
from research import verify_action, build_final_presentation, check_claim
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
    artifact_directory=ROOT/'local/s3-claim-fix'
    artifact_directory.mkdir(parents=True,exist_ok=True)
    # Keep all original model/process/validation/history/backtest bytes intact.
    originals=[p for p in task_path.parent.rglob('*') if p.is_file() and 'presentations' not in p.relative_to(task_path.parent).parts]
    for evidence in task['evidence']:
        originals.extend(p for p in (ROOT/'local/backtests'/evidence['run_id']).rglob('*') if p.is_file())
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    # CLI reader writes a validation file; run it only on a temporary copy.
    with tempfile.TemporaryDirectory(prefix='replay-',dir=artifact_directory) as temporary:
        copied=Path(temporary)
        for name in ('process.json','events.jsonl','stderr.txt','final.json'):
            shutil.copyfile(task_path.parent/'call-6'/name,copied/name)
        final=CodexRunner.read_result(copied,task['schema_snapshot'])
    known={e['run_id']:e for e in task['evidence']}
    for claim in final['final']['claims']:
        check_claim(claim,known)
    try:
        verify_action(final,task)
    except ValueError as error:
        current_validation={'accepted_as_new_final':False,'reason':str(error)}
    else:
        current_validation={'accepted_as_new_final':True}
    presentation=build_final_presentation(task)
    assert presentation['original_model_output']==final['final']
    assert len(presentation['facts'])==len(final['final']['claims'])==14
    assert presentation['derived_from_legacy'] and presentation['validation']['status']=='legacy_display_revised'
    assert presentation['interpretation']['conclusion'] is None
    assert not current_validation['accepted_as_new_final']
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
    signature=hashlib.sha256(json.dumps(presentation,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    sidecar=task_path.parent/'presentations'/f'evidence-binding-v2-{signature[:16]}.json'
    record={'kind':'derived_history_presentation','research_id':RID,'generated_at':datetime.now(timezone.utc).isoformat(),
            'presentation':presentation,'source_schema_version':task['configuration_snapshot']['output_schema_version'],
            'source_file_sha256':before,'current_validation':current_validation,
            'original_validation_preserved':True,'new_model_calls':0,'new_remote_calls':0}
    if sidecar.exists():
        saved=json.loads(sidecar.read_text())
        assert saved['presentation']==presentation and saved['source_file_sha256']==before
    else:
        save_json(sidecar,record)
    after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    assert before==after,'Original history, model output, validation or raw backtest was changed'
    artifact={'kind':'offline_replay_of_saved_live_evidence_and_derived_display','research_id':RID,'passed':True,'runs':rows,
              'new_model_calls':0,'new_remote_calls':0,'bound_fact_references':len(presentation['facts']),
              'current_validation':current_validation,'display_adjustments':presentation['validation']['issues'],
              'original_files_unchanged':True,'original_file_count':len(before),'source_file_sha256':before,
              'derived_presentation_path':str(sidecar.relative_to(ROOT))}
    save_json(artifact_directory/'live-replay.json',artifact)
    print(json.dumps({k:v for k,v in artifact.items() if k!='source_file_sha256'},ensure_ascii=False))
    return 0

if __name__=='__main__': raise SystemExit(main())

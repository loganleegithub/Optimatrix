"""Offline research-loop checks with synthetic runner/backtest adapters.

Target failures: model-controlled parameters/budgets; unbound final evidence;
false success from exit code alone; repeated POST after stop/restart; exceeded
six-call/two-creation limits; forgotten configuration snapshots; overwritten
pending model output. Real sockets and subprocesses are blocked throughout.
The artifact is software verification, never evidence of a real model run.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest import BacktestError, save_json, validate_experiment
from app import create_app
from research import ResearchService, ResearchError, DEFAULT_QUESTION
from researcher_cli import CodexRunner, ModelError, validate_schema

PARAMS = dict(start_date="2026-06-01", end_date="2026-06-02", session_bucket="09:00:00",
              entry_weekdays=[0], option_type="put", delta=.4, expiry=14, quantity=.01,
              option_transaction_cost_bp=1)
PLAN = dict(hypothesis="合成模型收益对费用敏感", comparison="同一模型记录提高费用", price_source="模型曲面", falsification="净模型收益不足")

@contextmanager
def offline_only():
    connect, popen, hook = socket.socket.connect, subprocess.Popen, threading.excepthook
    thread_errors=[]
    threading.excepthook=lambda args:thread_errors.append(args.exc_type.__name__)
    def prohibited(*args, **kwargs): raise AssertionError("Offline research check attempted networking or a subprocess")
    socket.socket.connect = prohibited
    subprocess.Popen = prohibited
    try: yield
    finally:
        socket.socket.connect, subprocess.Popen = connect, popen
        threading.excepthook=hook
        assert not thread_errors, 'Background exceptions: '+repr(thread_errors)

def action(kind, **fields):
    value = dict(schema_version="research-action-v1", action=kind, explanation="离线合成动作",
                 plan=None, experiment=None, run_id=None, higher_fee_bp=None, final=None)
    value.update(fields)
    return value

def finish(input_data, *, bad_reference=False):
    ids=[item['run_id'] for item in input_data['evidence']]
    claims=[]
    if ids:
        claims=[dict(text="程序绑定净模型结果",run_id=ids[-1],field="accounting.btc_net_pnl")]
    if bad_reference:
        claims=[dict(text="虚构证据不能通过",run_id="f"*32,field="accounting.btc_net_pnl")]
    return action('finish',final=dict(question=input_data['question'],hypothesis="模型费用影响收益",
        verdict="结果不确定",conclusion="仅验证程序回路，不能证明可成交优势。",counterexamples=["没有盘口"],
        unknowns=["实际成交成本"],next_step="需要交易侧报价证据",claims=claims,
        experiments=[dict(run_id=run_id,role="已读取的合成检查记录") for run_id in ids],suggested_experiments=[]))

class FakeBacktests:
    def __init__(self, status='completed_with_gaps'):
        self.runs={};self.logical={};self.creations=0;self.resume_count=0;self.status=status
        self.capability_status='ready';self.creation_quota=True;self.connection_checks=0
        self.history='a'*32
        self.runs[self.history]=self.record(self.history)
    def record(self, run_id, params=PARAMS):
        return dict(run_id=run_id,status='completed_with_gaps',service_task_id='fixture-task',request=validate_experiment(params),
            can_resume=False,analysis=dict(status='model_ledger_verified',model_ledger_verified=True,position_status='closed',
                price_source='synthetic model fixture; not market data',premium_paid_btc='0.0002',exit_income_btc='0.0003',
                fees_btc='0.000002',btc_net_pnl='0.000098',hypothetical_account_return_pct='0.049',gaps=['Synthetic fixture has no market meaning'],
                audit=dict(base_option_fee_bp='1',traded_nominal_btc='0.02',trade_event_count=2)))
    def tool_capabilities(self): return dict(coverage=dict(start_date='2026-01-01',end_date='2026-09-28'))
    def snapshot(self): return dict(runs=list(reversed(list(self.runs.values()))),capabilities=dict(status=self.capability_status,reason='synthetic creation quota exhausted'))
    def check_connection(self):
        self.connection_checks+=1
        self.capability_status='ready' if self.creation_quota else 'failed'
    def get_run(self, run_id): return copy.deepcopy(self.runs[run_id])
    def submit_experiment(self, params, *, logical_id, hypothesis, comparison_plan, before_create):
        validate_experiment(params)
        if logical_id in self.logical:
            return dict(run_id=self.logical[logical_id],reused=True,created_attempt=False)
        if self.capability_status!='ready':raise BacktestError('synthetic requires verified creation capability')
        before_create()
        self.creations+=1
        run_id=f'{self.creations:032x}'
        record=self.record(run_id,params);record['status']=self.status
        record['can_retry']=self.status=='not_submitted'
        if self.status not in {'completed','completed_with_gaps'}: record['analysis']=None
        self.runs[run_id]=record;self.logical[logical_id]=run_id
        return dict(run_id=run_id,reused=False,created_attempt=True)
    def retry(self, run_id, *, logical_id, before_create=None):
        assert self.runs[run_id].get('can_retry')
        result=self.submit_experiment(PARAMS,logical_id=logical_id,hypothesis=PLAN['hypothesis'],comparison_plan=PLAN,before_create=before_create)
        self.runs[result['run_id']]['previous_run_id']=run_id
        return result
    def resume(self, run_id):
        self.resume_count+=1
        self.runs[run_id]['status']='completed_with_gaps'
        self.runs[run_id]['analysis']=self.record(run_id)['analysis']
    def pause(self, run_id):
        if self.runs[run_id]['status']=='running':
            self.runs[run_id]['status']='paused'
            self.runs[run_id]['can_resume']=True
    def complete(self):
        for run_id in self.logical.values():
            self.runs[run_id]['status']='completed_with_gaps'
            self.runs[run_id]['can_resume']=False
            self.runs[run_id]['analysis']=self.record(run_id)['analysis']

class FakeRunner:
    def __init__(self, chooser): self.calls=[];self.chooser=chooser
    def run(self, *, input_data, config, prompt, schema, directory, stop_event):
        directory=Path(directory)
        self.calls.append(dict(input=copy.deepcopy(input_data),config=copy.deepcopy(config),prompt=prompt))
        save_json(directory/'input.json',input_data)
        output=self.chooser(input_data,len(self.calls))
        interrupt=isinstance(output,tuple)
        if interrupt: output=output[0]
        save_json(directory/'final.json',output)
        # Real runner only writes validated.json when the structure is valid.
        try: validate_schema(output,schema)
        except ValueError: pass
        else: save_json(directory/'validated.json',output)
        if interrupt: raise ModelError('stopped','synthetic interruption after durable model output')
        return output

def fixture_root(path):
    (path/'researcher').mkdir()
    for name in ('config.json','prompt.md','output.schema.json'):
        shutil.copyfile(ROOT/'researcher'/name,path/'researcher'/name)
    return path

def service(path, backtests, runner):
    return ResearchService(path,backtests,runner=runner,availability=dict(ready=True,reason='offline fixture'))

def wait_idle(manager):
    deadline=time.monotonic()+5
    while manager.active_id is not None and time.monotonic()<deadline: time.sleep(.01)
    assert manager.active_id is None, 'Offline worker failed to stop'

def wait_status(manager, rid, status):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if manager.detail(rid)['status']==status:return
        time.sleep(.01)
    raise AssertionError('Expected '+status+', got '+manager.detail(rid)['status'])

def start(manager, key='fixture_0001', question=DEFAULT_QUESTION):
    return manager.start(question,True,key)

def run_case(base, name, chooser, status='completed_with_gaps', question=DEFAULT_QUESTION):
    path=base/name;path.mkdir();fixture_root(path)
    bt=FakeBacktests(status);runner=FakeRunner(chooser);manager=service(path,bt,runner)
    rid=start(manager,question=question);wait_idle(manager)
    return manager,rid,bt,runner,path

def cli_output_case(path, schema, *, events, final, exit_code=0):
    path.mkdir()
    save_json(path/'process.json',dict(exit_code=exit_code))
    (path/'events.jsonl').write_text('\n'.join(json.dumps(event) for event in events)+'\n')
    (path/'stderr.txt').write_text('')
    save_json(path/'final.json',final)
    try: CodexRunner.read_result(path,schema)
    except ModelError: return
    raise AssertionError('CLI process/events/final invalid combination accepted')

def main():
    checks=[]
    with offline_only(),tempfile.TemporaryDirectory(prefix='optimatrix-research-check-') as temp:
        base=Path(temp)
        def closed_loop(i,n):
            if n==1:return action('run_backtest',plan=PLAN,experiment=PARAMS)
            if n==2:return action('compare_fees',plan=PLAN,run_id=i['evidence'][0]['run_id'],higher_fee_bp=5)
            return finish(i)
        manager,rid,bt,runner,path=run_case(base,'closed_loop',closed_loop)
        saved=manager.detail(rid)
        assert saved['status']=='completed',saved.get('error')
        assert saved['budget']['model_calls_used']==3 and saved['budget']['backtest_creations_used']==1 and bt.creations==1
        assert saved['final']['claims'][0]['value']=='0.000098'
        assert saved['evidence'][0]['fee_comparison']['incremental_cost_btc']=='0.000008'
        assert start(manager)==rid and len(runner.calls)==3
        assert 'AUTH_TOKEN' not in json.dumps(runner.calls)
        checks.extend(['agent_tool_feedback_loop_synthetic','bound_amount_and_cost_comparison','start_idempotence'])
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'invalid_reference',lambda i,n:finish(i,bad_reference=True))
        assert manager.detail(rid)['status']=='invalid_output'
        assert manager.detail(rid)['final'] is None and len(runner.calls)==2 and bt.creations==0
        assert manager.detail(rid)['budget']['corrections_used']==1
        checks.append('unknown_evidence_never_completes_one_correction')
        manager.stop()

        def injected(i,n):
            output=action('run_backtest',plan=PLAN,experiment={**PARAMS,'model':'unapproved'})
            output['budget']={'model_calls':999}
            return output
        manager,rid,bt,runner,path=run_case(base,'injected',injected)
        assert manager.detail(rid)['status']=='invalid_output' and bt.creations==0
        assert manager.detail(rid)['budget']['model_calls_limit']==6
        checks.append('model_cannot_override_parameter_budget_or_model')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'model_budget',lambda i,n:action('read_result',run_id='a'*32))
        assert manager.detail(rid)['status']=='budget_exhausted' and len(runner.calls)==6 and bt.creations==0
        checks.append('six_model_call_limit')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'backtest_budget',lambda i,n:action('run_backtest',plan=PLAN,experiment={**PARAMS,'delta':.2+n/10}))
        assert manager.detail(rid)['status']=='tool_failed' and bt.creations==2 and len(runner.calls)==3
        assert manager.detail(rid)['budget']['backtest_creations_used']==2
        checks.append('two_remote_creation_limit')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'unknown_submit',lambda i,n:action('run_backtest',plan=PLAN,experiment=PARAMS),'submission_unknown')
        assert manager.detail(rid)['status']=='submission_unknown' and not manager.detail(rid)['can_resume']
        assert start(manager)==rid and bt.creations==1 and len(runner.calls)==1
        checks.append('unknown_submission_not_replayed')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'linked_retry',lambda i,n:action('run_backtest',plan=PLAN,experiment=PARAMS) if n==1 else finish(i),status='not_submitted',question='离线检验明确未创建后的新尝试')
        assert manager.detail(rid)['status']=='tool_failed' and bt.creations==1
        old=manager.detail(rid)['actions'][0]['run_id']
        bt.status='completed_with_gaps';bt.capability_status='unchecked';manager.resume(rid);wait_idle(manager)
        saved=manager.detail(rid)
        assert saved['status']=='completed' and bt.creations==2 and len(runner.calls)==2
        assert saved['budget']['backtest_creations_used']==2 and saved['actions'][0]['previous_run_ids']==[old]
        assert bt.runs[old]['status']=='not_submitted'
        checks.append('explicit_linked_retry_reserves_remaining_budget_keeps_old_failure')
        manager.stop()

        path=base/'stop_resume';path.mkdir();fixture_root(path)
        bt=FakeBacktests('running');runner=FakeRunner(lambda i,n:action('run_backtest',plan=PLAN,experiment=PARAMS) if n==1 else finish(i))
        manager=service(path,bt,runner);rid=start(manager,question='离线检验停止恢复和证据引用');wait_status(manager,rid,'waiting_backtest')
        manager.stop_task(rid);wait_idle(manager)
        assert manager.detail(rid)['status']=='stopped' and manager.detail(rid)['can_resume']
        bt.complete();manager.resume(rid);wait_idle(manager)
        assert manager.detail(rid)['status']=='completed' and bt.creations==1 and len(runner.calls)==2
        checks.append('stop_resume_pending_backtest_no_recreation')
        manager.stop()

        path=base/'restart';path.mkdir();fixture_root(path)
        bt=FakeBacktests('running');runner=FakeRunner(lambda i,n:action('run_backtest',plan=PLAN,experiment=PARAMS))
        manager=service(path,bt,runner);rid=start(manager,question='离线检验停止恢复和证据引用');wait_status(manager,rid,'waiting_backtest')
        old=manager.detail(rid)['configuration_snapshot'];manager.stop()
        bt.capability_status='unchecked';bt.creation_quota=False
        changed=json.loads((path/'researcher/config.json').read_text());changed['model']='synthetic-future-model'
        save_json(path/'researcher/config.json',changed)
        next_runner=FakeRunner(lambda i,n:finish(i));restarted=service(path,bt,next_runner)
        assert restarted.detail(rid)['status']=='paused' and not next_runner.calls
        bt.complete();restarted.resume(rid);wait_idle(restarted)
        assert restarted.detail(rid)['status']=='completed' and bt.creations==1 and len(next_runner.calls)==1
        assert next_runner.calls[0]['config']['model']==old['model']
        checks.extend(['restart_no_automatic_calls','resume_uses_saved_configuration_and_pending_action','resume_result_does_not_require_new_creation_quota'])
        restarted.stop()

        manager,rid,bt,runner,path=run_case(base,'pending_model',lambda i,n:(action('run_backtest',plan=PLAN,experiment=PARAMS),) if n==1 else finish(i),question='离线检验模型输出的恢复')
        assert manager.detail(rid)['status']=='stopped' and bt.creations==0
        manager.resume(rid);wait_idle(manager)
        assert manager.detail(rid)['status']=='completed' and len(runner.calls)==2 and bt.creations==1
        assert manager.detail(rid)['budget']['model_calls_used']==2
        checks.append('recover_validated_model_output_without_duplicate_call')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'demo_gate',lambda i,n:finish(i))
        assert manager.detail(rid)['status']=='invalid_output' and manager.detail(rid)['final'] is None
        checks.append('demo_cannot_skip_new_backtest_and_comparison')
        manager.stop()

        def role_amount(i,n):
            if n==1:return action('read_result',run_id='a'*32)
            output=finish(i)
            output['final']['experiments'][0]['role']='净收益 9 BTC'
            return output
        manager,rid,bt,runner,path=run_case(base,'role_amount',role_amount,question='离线检验模型金额不能自由编造')
        assert manager.detail(rid)['status']=='invalid_output' and manager.detail(rid)['final'] is None
        checks.append('monetary_experiment_role_rejected')
        manager.stop()

        def rounded_final(i,n, *, false_percentage=False):
            if n==1:return action('read_result',run_id='a'*32)
            output=finish(i)
            output['final']['question']='模型费用影响的概括'
            output['final']['claims'].append(dict(text='假设资金回报率',run_id='a'*32,field='accounting.hypothetical_account_return_pct'))
            output['final']['conclusion']='假设资金回报约 '+('9.99%' if false_percentage else '0.05%')+'，不能保证收益。'
            return output
        question='离线核对原始研究问题与已引用字段的小数显示'
        manager,rid,bt,runner,path=run_case(base,'rounded_percentage',rounded_final,question=question)
        saved=manager.detail(rid)
        assert saved['status']=='completed',saved.get('error')
        assert saved['final']['question']==question and saved['final']['model_question_summary']=='模型费用影响的概括'
        assert saved['final']['claims'][-1]['value']=='0.049'
        checks.append('summarized_question_bound_to_original_and_rounded_percentage_verified')

        # Emulate a historical validator rejection without another inference:
        # the CLI finish, events and exit state remain durable and unmodified.
        task=manager.tasks[rid]
        recovered_output=copy.deepcopy(task['actions'][-1]['output'])
        task['actions']=task['actions'][:-1]
        task.update(status='invalid_output',error='synthetic older strict question/percentage validator',pending_call='call-6',final=None)
        task['budget']['model_calls_used']=6
        manager._save(task)
        stored_call=manager.storage/rid/'call-6'
        save_json(stored_call/'process.json',dict(exit_code=0))
        save_json(stored_call/'final.json',recovered_output)
        (stored_call/'events.jsonl').write_text(json.dumps({'type':'turn.completed'})+'\n')
        (stored_call/'stderr.txt').write_text('')
        old_file=(stored_call/'final.json').read_bytes()
        calls_before=len(runner.calls);creations_before=bt.creations
        manager.resume(rid)
        recovered=manager.detail(rid)
        assert recovered['status']=='completed' and recovered['budget']['model_calls_used']==6
        assert len(runner.calls)==calls_before and bt.creations==creations_before
        assert recovered['validation_history'][-1]['previous_error']=='synthetic older strict question/percentage validator'
        assert recovered['validation_history'][-1]['new_model_calls']==0 and (stored_call/'final.json').read_bytes()==old_file
        checks.append('explicit_local_finish_revalidation_preserves_output_history_and_budget')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'false_percentage',lambda i,n:rounded_final(i,n,false_percentage=True),question=question)
        assert manager.detail(rid)['status']=='invalid_output' and manager.detail(rid)['final'] is None
        checks.append('unreferenced_or_false_percentage_cannot_complete')
        manager.stop()

        manager,rid,bt,runner,path=run_case(base,'nonfinal_revalidation',lambda i,n:{**action('run_backtest',plan=PLAN,experiment=PARAMS),'extra_field':True},question='离线校验本地重校不能执行工具')
        task=manager.tasks[rid]
        assert task['status']=='invalid_output' and task['pending_call']
        stored_call=manager.storage/rid/task['pending_call']
        save_json(stored_call/'process.json',dict(exit_code=0))
        save_json(stored_call/'final.json',action('run_backtest',plan=PLAN,experiment=PARAMS))
        (stored_call/'events.jsonl').write_text(json.dumps({'type':'turn.completed'})+'\n')
        (stored_call/'stderr.txt').write_text('')
        calls_before=len(runner.calls)
        try:
            manager.resume(rid)
        except ResearchError as error:
            assert '只接受最终结论' in str(error)
        else:
            raise AssertionError('Local revalidation executed a tool action')
        assert manager.detail(rid)['status']=='invalid_output' and manager.detail(rid)['final'] is None
        assert bt.creations==0 and len(runner.calls)==calls_before
        checks.append('local_revalidation_rejects_non_finish_without_tools_or_runner')
        manager.stop()

        path=base/'http';path.mkdir();fixture_root(path)
        bt=FakeBacktests();runner=FakeRunner(closed_loop);manager=service(path,bt,runner)
        class FakeMarket:
            def snapshot(self): return dict(status='offline fixture')
        client=create_app(FakeMarket(),bt,manager).test_client()
        settings=client.get('/api/research/config').get_json()
        headers={'Origin':'http://localhost','X-CSRF-Token':settings['csrf_token']}
        payload=dict(question=DEFAULT_QUESTION,approved=True,idempotency_key='http_fixture_1')
        assert client.post('/api/research/start',json=payload).status_code==403
        assert client.post('/api/research/start',json=payload,headers={**headers,'Origin':'https://example.invalid'}).status_code==403
        assert client.post('/api/research/start',json={**payload,'approved':False},headers=headers).status_code==409
        assert client.post('/api/research/start',json={**payload,'model_calls':999},headers=headers).status_code==400
        assert not runner.calls and bt.creations==0
        accepted=client.post('/api/research/start',json=payload,headers=headers)
        assert accepted.status_code==202
        rid=accepted.get_json()['research_id'];wait_idle(manager)
        assert client.get('/api/research/runs/'+rid).get_json()['status']=='completed'
        assert len(client.get('/api/research/runs').get_json()['runs'])==1
        assert client.get('/research').status_code==200
        checks.append('http_authorization_csrf_configuration_override_and_history')
        manager.stop()

        schema=json.loads((ROOT/'researcher/output.schema.json').read_text())
        output=finish({'evidence':[],'question':DEFAULT_QUESTION})
        cli_output_case(base/'cli_missing_completion',schema,events=[{'type':'thread.started'}],final=output)
        cli_output_case(base/'cli_bad_final',schema,events=[{'type':'turn.completed'}],final={'action':'finish'})
        cli_output_case(base/'cli_nonzero',schema,events=[{'type':'turn.completed'}],final=output,exit_code=1)
        checks.extend(['cli_zero_exit_not_success_alone','cli_invalid_final_rejected','cli_nonzero_rejected'])
        cli_output_case(base/'cli_failed_event',schema,events=[{'type':'turn.failed'},{'type':'turn.completed'}],final=output)
        checks.append('cli_failed_event_rejected_independent_of_json_spacing')

    result=dict(kind='offline_synthetic_research_check',passed=True,checks=checks,live_model_calls=0,live_backtest_creations=0)
    save_json(ROOT/'local/s3-research-check/evidence.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        save_json(ROOT/'local/s3-research-check/evidence.json',dict(kind='offline_synthetic_research_check',passed=False,error_type=type(error).__name__,live_model_calls=0,live_backtest_creations=0))
        raise

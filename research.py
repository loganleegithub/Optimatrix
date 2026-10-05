"""One logical researcher; durable actions, bounded calls, deterministic tools."""
from __future__ import annotations
import copy
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import logging
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
import uuid

from backtest import BacktestError, save_json, validate_experiment, request_fingerprint
from btc_accounting import compare_fee_scenario
from market import iso, safe_traceback
from researcher_cli import CodexRunner, ModelError, validate_schema, check_isolation, check_cli_compatibility

DEFAULT_QUESTION = '在当前 Greeks.live 能表达的数据和策略范围内，选择一个简单 BTC inverse 期权买方实验，比较基础费用与较高费用假设下的 BTC 模型结果。回答结果有多少被成本消耗，以及为什么这仍不能证明可成交优势。'
ACTIVE = {'preparing','model_running','requesting_experiment','waiting_backtest','reading_result','forming_conclusion'}
RESUMABLE = {'paused','stopped','tool_failed','model_timeout','model_failed','usage_limit','authentication_failed','model_unavailable'}


class ResearchError(Exception):
    pass


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def evidence_fields(evidence):
    fields = {}
    for prefix, record in [('accounting', evidence.get('accounting', {})), ('fee_comparison', evidence.get('fee_comparison', {}))]:
        for key, value in record.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                fields[prefix + '.' + key] = value
    for key in ('status','service_task_id','source','price_source'):
        fields[key] = evidence.get(key)
    return fields


PRESENTATION_VERSION = 'evidence-binding-v2'
VALIDATION_SCOPE = '仅核对结构化引用、字段与确定性金额；不验证自然语言全部正确。'
# Explicit units, including btc_net_pnl (which has no _btc suffix). Unknown
# scalar fields remain source records, never inferred currency amounts.
METRICS = {
    'accounting.btc_net_pnl': ('模型账本净损益', 'BTC'),
    'accounting.premium_paid_btc': ('累计开仓权利金', 'BTC'),
    'accounting.exit_income_btc': ('累计平仓收入', 'BTC'),
    'accounting.fees_btc': ('基础假设费用', 'BTC'),
    'accounting.hypothetical_capital_btc': ('假设资金（非真实余额）', 'BTC'),
    'accounting.premium_return_pct': ('净损益占累计开仓权利金', '%'),
    'accounting.hypothetical_account_return_pct': ('净损益占假设资金', '%'),
    'fee_comparison.traded_nominal_btc': ('开平仓事件累计名义量（非余额）', 'BTC'),
    'fee_comparison.gross_pnl_btc': ('费用前模型损益', 'BTC'),
    'fee_comparison.base_fees_btc': ('基础费用合计', 'BTC'),
    'fee_comparison.higher_fees_btc': ('较高费用合计', 'BTC'),
    'fee_comparison.base_net_btc': ('基础费用后净模型损益', 'BTC'),
    'fee_comparison.higher_net_btc': ('较高费用后净模型损益', 'BTC'),
    'fee_comparison.incremental_cost_btc': ('提高费率新增成本', 'BTC'),
    'fee_comparison.gross_profit_consumed_base_pct': ('基础费用占正毛模型利润', '%'),
    'fee_comparison.gross_profit_consumed_higher_pct': ('较高费用占正毛模型利润', '%'),
    'fee_comparison.base_cost_as_premium_pct': ('基础费用占累计开仓权利金', '%'),
    'fee_comparison.higher_cost_as_premium_pct': ('较高费用占累计开仓权利金', '%'),
    'fee_comparison.base_fee_bp': ('基础假设费率', 'bp'),
    'fee_comparison.higher_fee_bp': ('较高假设费率', 'bp'),
}
# A small literal guard, not a natural-language fact checker. Scientific
# notation is one token; 1e3 BTC must never be misread as 3 BTC.
FINANCIAL_LITERAL = re.compile(r'([+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(USDC|BTC|USD|美元|比特币|%|％|bp)', re.I)


def referenced_value(ref, known):
    run_id, field = ref.get('run_id'), ref.get('field')
    if run_id not in known or field not in evidence_fields(known[run_id]):
        raise ValueError('结论引用不存在或字段未提供给本任务')
    return evidence_fields(known[run_id])[field]


def check_claim(ref, known):
    value = referenced_value(ref, known)
    unit = METRICS.get(ref['field'], ('', ''))[1]
    for match in FINANCIAL_LITERAL.finditer(ref['text']):
        token, stated_unit = match.groups()
        stated_unit = {'比特币':'BTC', '美元':'USD', '％':'%'}.get(stated_unit, stated_unit.upper() if stated_unit.upper() != 'BP' else 'bp')
        try:
            with localcontext() as context:
                context.prec = 100
                stated = Decimal(token.replace(',', ''))
                actual = Decimal(str(value))
                if stated_unit != unit or not actual.is_finite() or actual.quantize(Decimal(1).scaleb(stated.as_tuple().exponent), rounding=ROUND_HALF_EVEN) != stated:
                    raise ValueError()
        except Exception:
            raise ValueError('本条声明金额或比例未匹配其自己的 run_id 和 field（按显示精度核对）') from None


def formatted_value(value, unit):
    if value is None:
        return '未知'
    if unit:
        with localcontext() as context:
            context.prec = 100
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError('金额字段不是有限数字')
            places = 8 if unit == 'BTC' else 4
            rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
            return ('≈ ' if rounded != number else '') + format(rounded, 'f')
    return str(value)


def computed_comparison(comparison, known):
    if set(comparison) != {'left_run_id', 'right_run_id', 'field'}:
        raise ValueError('比较只接受两个输入 run_id 和同一个金额字段，不接受模型计算值')
    field = comparison['field']
    if field not in METRICS or METRICS[field][1] not in {'BTC', '%'}:
        raise ValueError('该字段不支持确定性差额比较')
    left = {'run_id':comparison['left_run_id'], 'field':field}
    right = {'run_id':comparison['right_run_id'], 'field':field}
    left['value'], right['value'] = referenced_value(left, known), referenced_value(right, known)
    if left['run_id'] == right['run_id']:
        raise ValueError('跨实验比较需要两个不同的输入记录')
    try:
        with localcontext() as context:
            context.prec = 100
            a, b = Decimal(str(left['value'])), Decimal(str(right['value']))
            if not a.is_finite() or not b.is_finite():
                raise ValueError()
            value = format(a-b, 'f')
    except Exception:
        raise ValueError('比较输入缺失或不是有限金额，不能当作零') from None
    unit = '百分点' if METRICS[field][1] == '%' else 'BTC'
    return {'left':left, 'right':right, 'operation':'left_minus_right', 'value':value,
            'display_value':formatted_value(value, unit), 'unit':unit}


def build_final_presentation(task):
    """Pure derived view of the task's evidence snapshot; never edits history."""
    final = task.get('final')
    if not final:
        return None
    known = {e['run_id']:e for e in task['evidence']}
    issues, facts, comparisons = [], [], []
    for index, ref in enumerate(final['claims']):
        location = f'claims[{index}]'
        try:
            value = referenced_value(ref, known)
            label, unit = METRICS.get(ref['field'], (ref['field'], ''))
            facts.append({'run_id':ref['run_id'], 'field':ref['field'], 'label':label, 'value':value,
                          'display_value':formatted_value(value,unit), 'unit':unit})
            check_claim(ref, known)
        except ValueError as error:
            issues.append({'location':location, 'reason':str(error)})
    for index, comparison in enumerate(final.get('comparisons', [])):
        try:
            comparisons.append(computed_comparison(comparison,known))
        except ValueError as error:
            issues.append({'location':f'comparisons[{index}]', 'reason':str(error)})
    def interpretation(text, location):
        if FINANCIAL_LITERAL.search(text):
            issues.append({'location':location, 'reason':'原文含未绑定到单条引用的金额、比例或费率；只保留在原文区，不作为事实展示。'})
            return None
        return text
    narrative = {key:interpretation(final[key],key) for key in ('conclusion','hypothesis')}
    for key in ('counterexamples','unknowns'):
        narrative[key] = [value for i,text in enumerate(final[key]) if (value:=interpretation(text,f'{key}[{i}]')) is not None]
    narrative['experiments'] = [{'run_id':e['run_id'], 'role':interpretation(e['role'],f'experiments[{i}].role')} for i,e in enumerate(final['experiments'])]
    legacy = task['configuration_snapshot']['output_schema_version'] != 'research-action-v2'
    model_fields = ('question','hypothesis','verdict','conclusion','counterexamples','unknowns','next_step','claims','experiments','suggested_experiments','comparisons')
    original = {key:copy.deepcopy(final[key]) for key in model_fields if key in final}
    # Bound values and annotations added by the old application are not model text.
    for claim in original['claims']:
        claim.pop('value',None)
    original['question'] = final.get('model_question_summary',final['question'])
    return {'version':PRESENTATION_VERSION, 'derived_from_legacy':legacy,
            'source_final_sha256':digest(json.dumps(final,sort_keys=True,ensure_ascii=False)),
            'evidence_sha256':digest(json.dumps(task['evidence'],sort_keys=True,ensure_ascii=False)),
            'validation':{'scope':VALIDATION_SCOPE, 'status':('legacy_display_revised' if legacy else 'display_with_gaps') if issues else 'passed', 'issues':issues},
            'question':task['question'], 'verdict':final['verdict'], 'interpretation':narrative,
            'facts':facts, 'comparisons':comparisons,
            'future':{'status':'未执行；未获交易授权', 'suggested_experiments':copy.deepcopy(final['suggested_experiments']), 'next_step':final['next_step']},
            'original_model_output':original}


def verify_action(action, task):
    context = task.get('strategy_context') or {}
    if context.get('purpose') in {'proposal', 'revision'}:
        if action.get('action') != 'propose':
            raise ValueError('形成提案只返回结构化草案，不执行回测或改写版本')
        return
    name = action['action']
    required = {'run_backtest': {'plan','experiment'}, 'read_result': {'run_id'},
                'compare_fees': {'plan','run_id','higher_fee_bp'}, 'finish': {'final'}}[name]
    for field in ('plan','experiment','run_id','higher_fee_bp','final'):
        if (action[field] is not None) != (field in required):
            raise ValueError('动作参数与动作名称不匹配')
    if name == 'run_backtest':
        validate_experiment(action['experiment'])
        if context and action['experiment'] != context.get('approved_experiment'):
            raise ValueError('回测参数不等于本次批准的版本与验证条件；改变目标或规则需要新的明确批准')
    if name in {'read_result','compare_fees'} and action['run_id'] not in task['available_run_ids']:
        raise ValueError('run_id 不属于本任务可用证据')
    if name == 'compare_fees':
        fee = action['higher_fee_bp']
        if type(fee) not in (int,float) or not 0 <= fee <= 100:
            raise ValueError('费用参数超出本阶段范围')
    if name == 'finish':
        final = action['final']
        known = {item['run_id']: item for item in task['evidence']}
        for ref in final['claims']:
            check_claim(ref, known)
        for comparison in final.get('comparisons', []):
            computed_comparison(comparison, known)
        executed = {a.get('run_id') for a in task['actions'] if a['action'] == 'run_backtest' and a.get('run_id')}
        declared = {e['run_id'] for e in final['experiments']}
        if not executed <= declared or not declared <= set(known):
            raise ValueError('最终实验清单缺失已执行实验或含未读取结果')
        # Future proposals carry no tool authority and need not match history.
        text = '\n'.join([action['explanation'],final['conclusion'],final['hypothesis'],final['next_step'],
                          *final['counterexamples'],*final['unknowns'],*final['suggested_experiments'],
                          *(r['text'] for r in final['claims']),*(e['role'] for e in final['experiments'])])
        if re.search(r'(?<!未)(?<!不)(?<!不能)保证收益|(?<!未)(?<!不)已批准实盘|(?<!不)(?<!未)批准实盘交易|长期盈利已证明', text):
            raise ValueError('研究结论超出授权范围')
        for value in [final['conclusion'],final['hypothesis'],*final['counterexamples'],*final['unknowns'],*(e['role'] for e in final['experiments'])]:
            if FINANCIAL_LITERAL.search(value):
                raise ValueError('正文金额没有逐条归属；事实数值请使用 claims 引用，跨实验差额使用 comparisons，未来参数放入建议区')
        if task['question'] == DEFAULT_QUESTION:
            new = [a for a in task['actions'] if a['action']=='run_backtest' and a.get('created_attempt')]
            if not new or not any(known.get(a.get('run_id'),{}).get('accounting',{}).get('model_ledger_verified') for a in new):
                raise ValueError('示范任务需要至少一个新实验及其已支持范围的 BTC 模型核账')
            if not any(e.get('fee_comparison') for e in known.values()):
                raise ValueError('示范任务尚未完成预先计划的费用比较')
        if executed and not final['claims']:
            raise ValueError('执行过实验的结论必须包含可验证证据引用')
        if context.get('purpose') == 'validation' and not executed:
            raise ValueError('本次验证必须实际执行或明确复用已批准请求，不能用其他历史总结代替')


class ResearchService:
    def __init__(self, root, backtests, cli_status=None, runner=None, availability=None):
        self.root = Path(root)
        self.backtests = backtests
        self.storage = self.root / 'local' / 'research'
        self.storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.configuration = json.loads((self.root/'researcher/config.json').read_text())
        self.prompt = (self.root/'researcher/prompt.md').read_text()
        self.schema = json.loads((self.root/'researcher/output.schema.json').read_text())
        self.configuration.update(prompt_sha256=digest(self.prompt), schema_sha256=digest(json.dumps(self.schema, sort_keys=True)))
        self.runner = runner or CodexRunner(shutil.which('codex'))
        self.lock = threading.RLock()
        self.csrf_token = secrets.token_urlsafe(32)
        self.tasks = {}
        self.worker = None
        self.stop_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.active_id = None
        self.storage_error = None
        self.availability = availability or self._availability(cli_status or {})
        for path in self.storage.glob('*/research.json'):
            try:
                task = json.loads(path.read_text())
                if not isinstance(task,dict) or not isinstance(task.get('research_id'),str) or not re.fullmatch(r'[a-f0-9]{32}',task['research_id']) or task['research_id'] != path.parent.name or not isinstance(task.get('status'),str):
                    raise ValueError('历史任务标识无效')
                if not all(isinstance(task.get(k),dict) for k in ('configuration_snapshot','budget','schema_snapshot')) or not all(isinstance(task.get(k),list) for k in ('actions','evidence','events','available_run_ids')):
                    raise ValueError('历史任务结构无效')
                if task['status'] in ACTIVE:
                    task.update(status='paused', error='后端已停止，任务暂停。显式继续后处理已保存动作；不会自动重发回测。')
                    self._save(task)
                self.tasks[task['research_id']] = task
            except (OSError, ValueError, KeyError, TypeError):
                self.storage_error = '部分研究历史损坏；保留原文件，修复前不能新建任务'

    def _availability(self, cli):
        return check_cli_compatibility(shutil.which('codex'), self.configuration, self.root/'local/s4a-validation')

    def config_snapshot(self):
        return {'server_time':iso(),'csrf_token':self.csrf_token,'configuration':copy.deepcopy(self.configuration),
                'capabilities':self.backtests.tool_capabilities(),'availability':self.availability,
                'default_question':DEFAULT_QUESTION,'storage_error':self.storage_error}

    def _save(self, task):
        task['updated_at'] = iso()
        save_json(self.storage/task['research_id']/'research.json', task)

    def _event(self, task, kind, message):
        with self.lock:
            task['events'].append({'at':iso(),'kind':kind,'message':message})
            self._save(task)

    def _state(self, task, status, message):
        with self.lock:
            task['status'] = status
            self._event(task, status, message)

    def detail(self, research_id):
        with self.lock:
            if research_id not in self.tasks:
                raise ResearchError('研究任务不存在')
            task = copy.deepcopy(self.tasks[research_id])
            task.pop('prompt_snapshot',None)
            task.pop('schema_snapshot',None)
            task['can_stop'] = self.active_id == research_id
            task['can_resume'] = self.active_id is None and (task['status'] in RESUMABLE or (task['status']=='invalid_output' and bool(task.get('pending_call'))))
            task['verified_metrics'] = [{'run_id':e['run_id'],'accounting':e.get('accounting'),
                                        'fee_comparison':e.get('fee_comparison')} for e in task['evidence']]
            task['final_presentation'] = build_final_presentation(task)
            return task

    def list_runs(self):
        with self.lock:
            return {'runs':[self.detail(t['research_id']) for t in sorted(self.tasks.values(),key=lambda t:t['created_at'],reverse=True)]}

    def start(self, question, approved, idempotency_key, *, context=None, defer_launch=False):
        if approved is not True or not isinstance(question,str) or not 5 <= len(question.strip()) <= 3000:
            raise ResearchError('请填写研究问题并明确批准本次预算')
        if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', idempotency_key):
            raise ResearchError('无效的逻辑提交标识')
        with self.lock:
            existing = next((t for t in self.tasks.values() if t['idempotency_key']==idempotency_key), None)
            if existing:
                if existing['question'] != question.strip() or existing.get('strategy_context') != context:
                    raise ResearchError('同一提交标识不能替换问题')
                return existing['research_id']
            if self.active_id or self.storage_error:
                raise ResearchError(self.storage_error or '一次只能运行一个研究任务')
            if not self.availability['ready']:
                raise ResearchError(self.availability['reason'])
            if context and sum(bool(t.get('strategy_context')) for t in self.tasks.values()) >= 2:
                raise ResearchError('本轮 S4A 两项研究任务上限已用完；已有证据可继续查看，不能自动扩大预算')
            configuration = copy.deepcopy(self.configuration)
            limits = configuration['limits']
            runs = self.backtests.snapshot()['runs']
            historical = [r['run_id'] for r in runs if r.get('analysis')][:5]
            prompt, schema = self.prompt, self.schema
            if context:
                if context.get('purpose') not in {'proposal', 'validation', 'revision'} or not context.get('strategy_id') or not context.get('version_id'):
                    raise ResearchError('新研究需要明确策略、版本和目的')
                # Unrelated runs are never silently admitted as this version's evidence.
                historical = list(context.get('available_run_ids', []))
                if context['purpose'] in {'proposal', 'revision'}:
                    prompt = (self.root/'researcher/proposal-prompt.md').read_text()
                    schema = json.loads((self.root/'researcher/proposal.schema.json').read_text())
                    configuration.update(prompt_version='btc-proposal-v1', output_schema_version='strategy-proposal-v1', allowed_tools=['propose'])
                configuration.update(prompt_sha256=digest(prompt), schema_sha256=digest(json.dumps(schema, sort_keys=True)))
            configuration['runtime_compatibility'] = copy.deepcopy(self.availability)
            configuration['cli_runtime_snapshot'] = copy.deepcopy(self.availability.get('runtime_snapshot'))
            task = {'research_id':uuid.uuid4().hex,'idempotency_key':idempotency_key,'question':question.strip(),
                'created_at':iso(),'approved_at':iso(),'status':'preparing','configuration_snapshot':configuration,
                'prompt_snapshot':prompt,'schema_snapshot':schema,'capabilities_snapshot':self.backtests.tool_capabilities(),
                'budget':{'model_calls_used':0,'backtest_creations_used':0,'model_calls_limit':limits['model_calls'],
                          'backtest_creations_limit':limits['backtest_creations'],'corrections_used':0},
                'available_run_ids':historical, 'events':[], 'actions':[], 'evidence':[], 'final':None,'error':None,
                'input_references':[], 'pending_call':None, 'elapsed_seconds':0}
            if context:
                task['strategy_context'] = copy.deepcopy(context)
            self.tasks[task['research_id']] = task
            self._save(task)
            if not defer_launch:
                self._launch(task)
            return task['research_id']

    def launch_prepared(self, research_id):
        """Called only after the workbench association has been durably saved."""
        with self.lock:
            task = self.tasks[research_id]
            if self.active_id == research_id:
                return research_id
            if self.active_id or task['status'] != 'preparing' or task['budget']['model_calls_used']:
                raise ResearchError('任务已启动或需要显式恢复，不能重复启动')
            self._launch(task)
            return research_id

    def _launch(self, task):
        self.stop_event = threading.Event()
        self.active_id = task['research_id']
        self.worker = threading.Thread(target=self._work,args=(task,),name='optimatrix-researcher',daemon=True)
        self.worker.start()

    def stop_task(self, research_id):
        with self.lock:
            if self.active_id != research_id:
                raise ResearchError('该研究没有正在运行的本地工作')
            self.stop_event.set()
            self._event(self.tasks[research_id],'stop_requested','已请求停止。已创建的远端回测不会撤销，保留 ID 可取回结果。')

    def resume(self, research_id):
        with self.lock:
            task = self.tasks.get(research_id)
            if task and task['status']=='invalid_output' and self.active_id is None:
                return self.revalidate_final(task)
            if not task or task['status'] not in RESUMABLE or self.active_id:
                raise ResearchError('当前任务不可继续，或另有研究正在运行')
            if not self.availability['ready']:
                raise ResearchError(self.availability['reason'])
            task['error'] = None
            for action in task['actions']:
                if action['status']=='pending' and action['action']=='run_backtest' and action.get('run_id'):
                    if self.backtests.get_run(action['run_id']).get('can_retry'):
                        action['retry_authorized'] = True
            task['refresh_saved_evidence']=True
            self._state(task,'preparing','人类显式继续；使用原配置快照和剩余预算')
            self._launch(task)
            return research_id

    def revalidate_final(self, task):
        """Explicit local recovery after a validator fix; zero new inference/tools."""
        call=task.get('pending_call')
        if not isinstance(call,str) or not re.fullmatch(r'call-[1-6]',call):
            raise ResearchError('没有可重新校验的本地输出')
        try:
            output=CodexRunner.read_result(self.storage/task['research_id']/call, task['schema_snapshot'])
            if output['action']!='finish':
                raise ValueError('本地重新校验只接受最终结论，不执行模型工具动作')
            verify_action(output,task)
        except (ValueError,ModelError) as error:
            raise ResearchError('本地结论仍未通过校验：'+str(error)) from None
        task.setdefault('validation_history',[]).append({'at':iso(),'previous_status':task['status'],'previous_error':task.get('error'),
                                                        'source_call':call,'new_model_calls':0})
        task['error']=None
        action={'step':len(task['actions'])+1,'action':'finish','output':output,'model_explanation':output['explanation'],
                'plan':None,'request':None,'run_id':None,'higher_fee_bp':None,'status':'pending','created_at':iso()}
        task['actions'].append(action)
        task['pending_call']=None
        self.stop_event=threading.Event()
        self.started=time.monotonic()
        self._event(task,'local_revalidation','人类显式重新校验已保存结论：检查逐条引用及本条数值，不验证自然语言全部正确；不调用模型或远端服务')
        self._execute(task,action)
        return task['research_id']

    def stop(self):
        self.shutdown_event.set()
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=7)

    def _check_stop(self, task):
        if self.stop_event.is_set():
            raise ModelError('paused' if self.shutdown_event.is_set() else 'stopped','本地研究已停止；已有远端任务仍可取回')
        if time.monotonic()-self.started + task['elapsed_seconds'] > task['configuration_snapshot']['limits']['task_timeout_seconds']:
            raise ModelError('task_timeout','研究总运行时间已用完；保留结果，不自动扩大预算')

    def _evidence(self, task, run_id):
        if run_id not in task['available_run_ids']:
            raise ValueError('证据未授权')
        run = self.backtests.get_run(run_id)
        analysis = run.get('analysis') or {}
        result = {'run_id':run_id,'status':run['status'],'service_task_id':run.get('service_task_id'),
                  'request':run['request'],'source':'Greeks.live 已保存原始 report / details / daily；模型曲面估值',
                  'price_source':analysis.get('price_source','未知'),'accounting':analysis,
                  'gaps':analysis.get('gaps',['结果尚未取得']),'result_url':'/backtest?run_id='+run_id}
        with self.lock:
            existing = next((e for e in task['evidence'] if e['run_id']==run_id),None)
            if existing:
                existing.update(result)
                result=existing
            else:
                task['evidence'].append(result)
            self._save(task)
        return result

    def _input(self, task):
        histories = []
        for run_id in task['available_run_ids']:
            run = self.backtests.get_run(run_id)
            histories.append({'run_id':run_id,'status':run['status'],'request':run['request'],
                              'accounting_status':(run.get('analysis') or {}).get('status')})
        evidence = []
        for item in task['evidence']:
            # Long detailed rows stay in local raw results; summary is explicitly scoped.
            summary = copy.deepcopy(item)
            summary['accounting'] = {k:v for k,v in summary['accounting'].items() if k not in {'rows'}}
            summary['evidence_fields'] = evidence_fields(item)
            summary['summary_scope'] = '完整确定性汇总；逐事件原始行未送入模型，保存在关联 run 的本地文件。read_result 读取相同核对汇总，不冒充完整明细。'
            evidence.append(summary)
        return {'research_id':task['research_id'],'question':task['question'],'configuration':task['configuration_snapshot'],
                'strategy_context':task.get('strategy_context'),
                'budget':task['budget'],'remaining_model_calls':task['budget']['model_calls_limit']-task['budget']['model_calls_used'],
                'remaining_backtest_creations':task['budget']['backtest_creations_limit']-task['budget']['backtest_creations_used'],
                'workflow_requirements':{'new_real_experiment_and_verified_btc_ledger':task['question']==DEFAULT_QUESTION, 'cost_comparison':task['question']==DEFAULT_QUESTION},
                'capabilities':task['capabilities_snapshot'],'related_history':histories,'actions':task['actions'],
                'evidence':evidence,'evidence_updates':task.get('evidence_updates',[]),'correction':task.get('correction'),
                'instructions':('只按当前 schema 返回 propose 草案；不要调用回测或修改版本。' if (task.get('strategy_context') or {}).get('purpose') in {'proposal','revision'} else
                    '按当前 schema 只返回一个动作；最后一次模型调用请 finish。远端结果由程序轮询，无需询问进度。费用比较可以 compare_fees，金额文字用字段引用。')}

    def _model(self, task):
        budget=task['budget']
        directory = None
        if task.get('pending_call'):
            directory=self.storage/task['research_id']/task['pending_call']
            if (directory/'validated.json').exists():
                value=json.loads((directory/'validated.json').read_text())
                validate_schema(value,task['schema_snapshot'])
                return value
            task['pending_call']=None
            self._event(task,'model_interrupted','上次 CLI 未取得有效最终结果，已计入消耗；本次显式继续使用下一次预算')
        if budget['model_calls_used']>=budget['model_calls_limit']:
            raise ModelError('budget_exhausted','模型调用预算已用完；已有证据保留，需要人类另行授权新研究')
        with self.lock:
            budget['model_calls_used']+=1
            call='call-'+str(budget['model_calls_used'])
            task['pending_call']=call
            directory=self.storage/task['research_id']/call
            task['input_references'].append(call+'/input.json')
            self._state(task,'model_running',f"researcher 模型调用 {budget['model_calls_used']} / {budget['model_calls_limit']}")
        effective = copy.deepcopy(task['configuration_snapshot'])
        remaining = effective['limits']['task_timeout_seconds'] - task['elapsed_seconds'] - (time.monotonic()-self.started)
        effective['limits']['model_timeout_seconds'] = max(1, min(effective['limits']['model_timeout_seconds'], remaining))
        return self.runner.run(input_data=self._input(task),config=effective,
                prompt=task['prompt_snapshot'],schema=task['schema_snapshot'],directory=directory,stop_event=self.stop_event)

    def _ensure_capabilities(self, task):
        self._state(task,'preparing','检查回测认证和当前工具能力（仅 GET）')
        self.backtests.check_connection()
        while self.backtests.snapshot()['capabilities']['status']=='checking':
            self._check_stop(task)
            self.stop_event.wait(0.1)
        if self.backtests.snapshot()['capabilities']['status']!='ready':
            raise ModelError('tool_failed', self.backtests.snapshot()['capabilities']['reason'])
        task['capabilities_snapshot']=self.backtests.tool_capabilities()
        self._save(task)

    def _execute(self, task, action):
        self._check_stop(task)
        name=action['action']
        if name=='propose':
            task['model_proposal'] = copy.deepcopy(action['output']['proposal'])
            task['status'] = 'completed'
            self._event(task,'completed','结构化提案已保存；需人类检查后应用到草案，未修改规则或批准策略')
        elif name=='run_backtest':
            self._state(task,'requesting_experiment','普通程序校验实验参数与预算；实验假设已先保存')
            def reserve():
                with self.lock:
                    self._check_stop(task)
                    budget=task['budget']
                    if budget['backtest_creations_used']>=budget['backtest_creations_limit']:
                        raise ResearchError('远端创建预算已用完')
                    budget['backtest_creations_used']+=1
                    self._save(task)
            if not action.get('run_id'):
                fingerprint=request_fingerprint(validate_experiment(action['request']))
                existing=any(request_fingerprint(r['request'])==fingerprint for r in self.backtests.snapshot()['runs'] if r['status']!='not_submitted')
                if not existing and self.backtests.snapshot()['capabilities']['status']!='ready':
                    self._ensure_capabilities(task)
                result=self.backtests.submit_experiment(action['request'],logical_id=task['research_id']+':step:'+str(action['step']),
                    hypothesis=action['plan']['hypothesis'],comparison_plan=action['plan'],before_create=reserve)
                action.update(result)
                if result['run_id'] not in task['available_run_ids']:
                    task['available_run_ids'].append(result['run_id'])
                self._save(task)
            run=self.backtests.get_run(action['run_id'])
            if action.get('retry_authorized') and run.get('can_retry'):
                if self.backtests.snapshot()['capabilities']['status']!='ready':
                    self._ensure_capabilities(task)
                previous=action['run_id']
                attempt=len(action.get('previous_run_ids',[]))+1
                result=self.backtests.retry(previous,logical_id=task['research_id']+':step:'+str(action['step'])+':retry:'+str(attempt),before_create=reserve)
                action.setdefault('previous_run_ids',[]).append(previous)
                action.update(result, retry_authorized=False)
                task['available_run_ids'].append(result['run_id'])
                self._save(task)
                run=self.backtests.get_run(action['run_id'])
            if run.get('can_resume'):
                self.backtests.resume(action['run_id'])
            self._state(task,'waiting_backtest',('复用已保存请求；' if action.get('reused') else '新实验已交给回测程序；')+'等待或读取真实结果，不重复调用模型')
            while True:
                self._check_stop(task)
                run=self.backtests.get_run(action['run_id'])
                if run['status'] not in {'queued','submitting','running','fetching'}:
                    break
                self.stop_event.wait(0.25)
            if run['status']=='submission_unknown':
                raise ModelError('submission_unknown','回测提交结果未知；不能重发，需核对远端创建状态')
            if run['status'] not in {'completed','completed_with_gaps','result_incomplete'}:
                raise ModelError('tool_failed','回测未取得结果：'+str(run.get('error') or run['status']))
            self._state(task,'reading_result','读取真实服务报告及程序核对结果，交回同一逻辑 researcher')
            self._evidence(task,action['run_id'])
        elif name=='read_result':
            self._state(task,'reading_result','读取已授权 run 的本地结果；不产生新回测')
            self._evidence(task,action['run_id'])
        elif name=='compare_fees':
            self._state(task,'reading_result','按已核对交易事件计算较高费用情景；保持原窗口、价格和头寸不变')
            result=self._evidence(task,action['run_id'])
            result['fee_comparison']=compare_fee_scenario(result['accounting'],action['higher_fee_bp'],run_id=action['run_id'])
            self._save(task)
        elif name=='finish':
            self._state(task,'forming_conclusion','校验所有证据 ID 和字段，关键金额由程序绑定')
            final=copy.deepcopy(action['output']['final'])
            final['model_question_summary']=final['question']
            final['question']=task['question']
            final['program_notes']=[VALIDATION_SCOPE, '事实展示从各自 run_id 与 field 取值；模型解释和未来参数建议不构成事实核验或执行授权。']
            known={e['run_id']:e for e in task['evidence']}
            for ref in final['claims']:
                ref['value']=evidence_fields(known[ref['run_id']])[ref['field']]
            task['final']=final
            task['status']='completed'
            self._event(task,'completed','中文研究结论已保存；仅为研究候选建议，没有交易授权')
        action['status']='done'
        self._save(task)

    def _work(self, task):
        self.started=time.monotonic()
        try:
            if task.pop('refresh_saved_evidence',False) and hasattr(self.backtests,'reanalyze_saved'):
                for run_id in list(task['available_run_ids']):
                    if not any(e['run_id']==run_id for e in task['evidence']):
                        continue
                    if self.backtests.reanalyze_saved(run_id):
                        refreshed=self._evidence(task,run_id)
                        # Cost scenarios already requested by this researcher may be applied to
                        # each ledger independently. No changed windows or remote requests.
                        rates=[a['higher_fee_bp'] for a in task['actions'] if a['action']=='compare_fees' and a['status']=='done']
                        if rates and refreshed['accounting'].get('model_ledger_verified'):
                            refreshed['fee_comparison']=compare_fee_scenario(refreshed['accounting'],rates[-1],run_id=run_id)
                            refreshed['fee_comparison_origin']='本地重新核账后沿用本研究已申请的较高费率，各窗口独立计算；不是两窗口之间的受控比较。'
                        note='重新核账 '+run_id+'：旧核账结果保留在 analysis_history；此次仅重新处理原始文件，无新远端调用。先前模型看到的未核账状态已更新，以此次 evidence 字段为准。'
                        task.setdefault('evidence_updates',[]).append(note)
                        task['pending_call']=None
                        self._event(task,'accounting_refreshed',note)
            # First authorized run checks current capability before its first model call.
            purpose = (task.get('strategy_context') or {}).get('purpose')
            if purpose not in {'proposal','revision'} and task['budget']['model_calls_used']==0 and not task['actions'] and self.backtests.snapshot()['capabilities']['status'] != 'ready':
                self._ensure_capabilities(task)
            while task['status']!='completed':
                self._check_stop(task)
                pending=next((a for a in task['actions'] if a['status']=='pending'),None)
                if pending:
                    self._execute(task,pending)
                    continue
                try:
                    output=self._model(task)
                    validate_schema(output,task['schema_snapshot'])
                    verify_action(output,task)
                except (ValueError,BacktestError,ModelError) as error:
                    invalid = not isinstance(error,ModelError) or error.status=='invalid_output'
                    if invalid and task['budget']['corrections_used']<1 and task['budget']['model_calls_used']<task['budget']['model_calls_limit'] and not self.stop_event.is_set():
                        task['budget']['corrections_used']+=1
                        task['pending_call']=None
                        task['correction']='上次输出被程序拒绝：'+str(error)+'。仅允许这一次纠正；不要新增无关实验。'
                        self._event(task,'output_rejected',task['correction'])
                        continue
                    if not isinstance(error,ModelError):
                        raise ModelError('invalid_output',str(error)) from None
                    raise
                action={'step':len(task['actions'])+1,'action':output['action'],'model_explanation':output['explanation'],
                    'output':output,'plan':output.get('plan'),'request':output.get('experiment'),'run_id':output.get('run_id'),
                    'higher_fee_bp':output.get('higher_fee_bp'),'status':'pending','created_at':iso()}
                with self.lock:
                    task['actions'].append(action)
                    task['pending_call']=None
                    task['correction']=None
                    self._save(task)
                self._execute(task,action)
        except ModelError as error:
            status = 'paused' if error.status=='stopped' and self.shutdown_event.is_set() else error.status
            task.update(status=status,error=str(error))
            for action in task['actions']:
                if action['status']=='pending' and action['action']=='run_backtest' and action.get('run_id'):
                    self.backtests.pause(action['run_id'])
            self._event(task,status,str(error))
        except (BacktestError,ResearchError,ValueError) as error:
            task.update(status='tool_failed',error=str(error))
            self._event(task,'tool_failed',str(error))
        except Exception as error:
            logging.error('research worker: %s',safe_traceback(error))
            task.update(status='internal_error',error='研究内部错误；本地日志保存脱敏诊断，行情服务独立运行')
            self._save(task)
        finally:
            with self.lock:
                task['elapsed_seconds']+=time.monotonic()-self.started
                self._save(task)
                self.active_id=None

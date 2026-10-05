"""S4A strategy/version identity and immutable links to existing research evidence.

This module never invokes a model, creates a remote run, reads credentials, or
places orders. Research and testnet capabilities are explicit and independent.
"""
from __future__ import annotations

import copy
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import uuid

from backtest import BacktestError, parameters_from_request, save_json, validate_experiment
from btc_accounting import MODEL_TOLERANCE, compare_fee_scenario
from market import iso
from research import ResearchError
from strategy import KIND as TREND_KIND, StrategyRuleError, normalize_trend_spec

RULE_FIELDS = {'session_bucket', 'entry_weekdays', 'option_type', 'delta', 'expiry', 'quantity'}
SPEC_FIELDS = ('contract_selection', 'entry', 'exit', 'position_constraints', 'decision_frequency', 'data_requirements', 'clock')
PURPOSES = {'proposal', 'validation', 'revision'}
DECISIONS = {'retain', 'continue_validation', 'revise', 'abandon', 'request_next_stage'}
ACTIVE = {'preparing', 'model_running', 'requesting_experiment', 'waiting_backtest', 'reading_result', 'forming_conclusion'}


class StrategyError(ValueError):
    pass


def _text(value, label, required=True, limit=12000):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise StrategyError(f'{label}须为非空文字，最多 {limit} 字')
    return value.strip()


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normalize_spec(spec):
    spec = copy.deepcopy(spec or {})
    if not isinstance(spec, dict):
        raise StrategyError('策略规格须为对象')
    allowed = {'kind', 'rules', 'implementation', 'implementation_status', 'implementation_task', *SPEC_FIELDS}
    if set(spec) - allowed:
        raise StrategyError('规格含未支持字段，不能静默丢弃条件：' + '、'.join(sorted(set(spec) - allowed)))
    kind = spec.get('kind', 'unimplemented')
    if kind == TREND_KIND:
        try:
            return normalize_trend_spec(spec)
        except StrategyRuleError as error:
            raise StrategyError(str(error)) from None
    if kind not in {'greeks_single_long', 'unimplemented'}:
        raise StrategyError('仅支持已有单腿买方模型表达；其他算法须标记待实现')
    if kind == 'greeks_single_long':
        rules = spec.get('rules')
        if not isinstance(rules, dict) or set(rules) != RULE_FIELDS:
            raise StrategyError('单腿模型规则须完整提供时段、星期、期权类型、Delta、期限和数量；日期及费用属于验证')
        try:
            request = validate_experiment(dict(rules, start_date='2026-01-01', end_date='2026-01-02', option_transaction_cost_bp=0))
        except BacktestError as error:
            raise StrategyError(str(error)) from None
        rules = {key: parameters_from_request(request)[key] for key in sorted(RULE_FIELDS)}
        for key in ('delta', 'quantity'):
            rules[key] = float(rules[key])
        canonical = {'kind': kind, 'rules': rules,
                'contract_selection': f"BTC inverse 曲面模型 long {rules['option_type']}；绝对 Delta {rules['delta']}，目标 {rules['expiry']} 天；无实际挂牌合约映射",
                'entry': f"UTC {rules['session_bucket']}，星期 {','.join(str(v) for v in rules['entry_weekdays'])}（0=周一）；reopen，每个允许日开仓",
                'exit': '下一有曲面数据日平仓；close_dte=0；到期结算、延期和缺失可能无法核账',
                'position_constraints': f"每次名义数量 {rules['quantity']} BTC，单腿买方、无对冲；没有可执行的权利金上限，费用由每次验证另行声明",
                'decision_frequency': '每天一次曲面模型估值；按规则中的 UTC 时段和入场星期执行',
                'data_requirements': 'Greeks.live BTC SABR/WV4 曲面、完整逐事件 details.csv 与 daily.csv；无 bid/ask 和深度',
                'clock': 'UTC，24×7 数据时钟；星期限制仅来自明确入场规则',
                'implementation': 'backtest.py:validate_experiment / Greeks.live reopen，btc-buyer-v1',
                'implementation_status': 'implemented'}
        # Free-form model text is not an executable rule language. The narrow
        # adapter may generate its own descriptions, but must never silently
        # erase a stop, quote condition, budget cap, or even an unrecognized
        # paraphrase. Manual adapter selection submits only kind + rules.
        # Model proposal adoption sends the original candidate unchanged.
        differing = [key for key in SPEC_FIELDS if key in spec
                     and _text(spec[key], key, False) not in {'', canonical[key]}]
        if _text(spec.get('implementation_task', ''), '实施任务', False):
            differing.append('implementation_task')
        if differing:
            raise StrategyError('提案包含现有单腿模型适配器不能确认的描述或额外条件：' + '、'.join(differing)
                + '。未保存、未丢弃条件。请保留完整描述并选择“新算法 / 尚未实现”；只有明确采用现有六参数模型规则时才可省略描述。')
        return canonical
    if spec.get('rules') not in (None, {}):
        raise StrategyError('待实现提案不接受可执行规则或任意代码')
    return {'kind': kind, **{key: _text(spec.get(key, ''), key, False) for key in SPEC_FIELDS},
            'rules': {}, 'implementation': '', 'implementation_status': 'pending',
            'implementation_task': _text(spec.get('implementation_task', ''), '实施任务', False)}


def _source(source, idea=''):
    source = copy.deepcopy(source or {})
    if not isinstance(source, dict):
        raise StrategyError('来源须为对象')
    kind = source.get('kind', 'human_idea')
    if kind not in {'human_idea', 'provided_material', 'researcher_proposal', 'historical_research'}:
        raise StrategyError('未知来源类型')
    content = _text(source.get('content', idea), '来源内容', False)
    url = _text(source.get('url', ''), '来源 URL', False, 3000)
    if url and not re.match(r'^https?://', url):
        raise StrategyError('来源 URL 须为 HTTP(S)；URL 本身不代表已经读取')
    status = source.get('content_status', 'provided' if content else 'not_retrieved')
    if status not in {'provided', 'retrieved', 'not_retrieved'} or (status != 'not_retrieved' and not content):
        raise StrategyError('来源取得状态与实际内容不符')
    if not content and not url:
        raise StrategyError('请填写想法、材料正文或来源 URL')
    if status == 'retrieved' and not source.get('retrieval_evidence'):
        raise StrategyError('实际取得来源须记录取得证据；粘贴材料请选择 provided')
    return {'kind': kind, 'content': content, 'url': url, 'content_status': status,
            'received_at': iso(), 'retrieved_at': source.get('retrieved_at') if status == 'retrieved' else None,
            'retrieval_evidence': _text(source.get('retrieval_evidence', ''), '取得证据', False),
            'content_sha256': hashlib.sha256(content.encode()).hexdigest() if content else None}


class StrategyService:
    def __init__(self, root, backtests, research=None):
        self.root, self.backtests, self.research = Path(root), backtests, research
        self.path = self.root / 'local' / 'strategies.json'
        self.lock = threading.RLock()
        self.storage_error = None
        self.data = {'schema_version': 's4a-strategies-v1', 'strategies': [], 'versions': [], 'validations': [], 'decisions': [], 'research_tasks': []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data.get('schema_version') != self.data['schema_version'] or any(not isinstance(data.get(k), list) for k in self.data if k != 'schema_version'):
                    raise ValueError('storage structure')
                for version in data['versions']:
                    if version.get('status') == 'frozen' and version.get('rules_sha256') != _hash(version['spec']):
                        raise ValueError('frozen rule fingerprint')
                self.data = data
            except (OSError, ValueError, KeyError, TypeError):
                self.storage_error = '策略文件损坏或冻结规则不一致；原文件保留，修复前禁止写入。回测与研究原始历史仍可访问。'
        self._persisted = copy.deepcopy(self.data)

    def _save(self):
        if self.storage_error:
            self.data = copy.deepcopy(self._persisted)
            raise StrategyError(self.storage_error)
        try:
            save_json(self.path, self.data)
        except (OSError, ValueError, TypeError):
            self.data = copy.deepcopy(self._persisted)
            self.storage_error = '策略持久化失败；原记录保留，当前会话禁止继续写入'
            raise StrategyError(self.storage_error) from None
        self._persisted = copy.deepcopy(self.data)

    def _strategy(self, sid):
        value = next((v for v in self.data['strategies'] if v['strategy_id'] == sid), None)
        if value is None:
            raise StrategyError('策略不存在')
        return value

    def _version(self, sid, vid):
        self._strategy(sid)
        value = next((v for v in self.data['versions'] if v['version_id'] == vid and v['strategy_id'] == sid), None)
        if value is None:
            raise StrategyError('策略版本不存在或不属于该策略')
        if value['status'] == 'frozen' and value['rules_sha256'] != _hash(value['spec']):
            raise StrategyError('冻结规则发生变化，拒绝执行')
        return value

    def _version_view(self, version):
        value = copy.deepcopy(version)
        value['gaps'] = [key for key in SPEC_FIELDS if not value['spec'].get(key)]
        value['spec_status'] = 'incomplete' if value['gaps'] else 'complete'
        value['implementation_status'] = value['spec']['implementation_status']
        complete = value['spec_status'] == 'complete' and value['implementation_status'] == 'implemented'
        value['can_validate'] = complete and value['spec']['kind'] == 'greeks_single_long'
        value['can_run_testnet'] = complete and value['spec']['kind'] == TREND_KIND
        if value['spec']['kind'] == TREND_KIND:
            binding = _hash(value['spec'])
            confirmation = value.get('onboarding', {})
            value['onboarding_complete'] = (confirmation.get('rules_sha256') == binding
                and set(confirmation.get('confirmed_keys', [])) == set(value['spec']['rules']))
            if confirmation.get('rules_sha256') != binding:
                value['onboarding'] = {**confirmation, 'confirmed_keys': [], 'complete': False}
        return value

    def _new_version(self, sid, spec, parent=None, revision=None):
        return {'version_id': uuid.uuid4().hex, 'strategy_id': sid,
                'label': 'v' + str(1 + sum(v['strategy_id'] == sid for v in self.data['versions'])),
                'created_at': iso(), 'status': 'draft', 'frozen_at': None, 'rules_sha256': None,
                'parent_version': parent, 'revision': revision, 'spec': normalize_spec(spec),
                'edit_history': []}

    def create(self, payload):
        with self.lock:
            source = _source(payload.get('source'), payload.get('idea', ''))
            strategy = {'strategy_id': uuid.uuid4().hex, 'name': _text(payload.get('name'), '策略名', limit=160),
                        'economic_hypothesis': _text(payload.get('economic_hypothesis', source['content']), '经济假设', False),
                        'product': _text(payload.get('product', 'BTC inverse options'), '适用产品', limit=200),
                        'source': source, 'failure_mechanisms': _text(payload.get('failure_mechanisms', ''), '失败机制', False),
                        'created_at': iso(), 'current_version_id': None}
            version = self._new_version(strategy['strategy_id'], payload.get('spec'))
            strategy['current_version_id'] = version['version_id']
            self.data['strategies'].append(strategy)
            self.data['versions'].append(version)
            self._save()
            return self.detail(strategy['strategy_id'])

    def update_metadata(self, sid, payload):
        """Human-edited descriptions with history; source and economic rules stay separate."""
        with self.lock:
            if not isinstance(payload, dict) or not payload or set(payload) - {'name', 'economic_hypothesis', 'failure_mechanisms'}:
                raise StrategyError('仅可编辑策略名、一句话经济假设与失败机制；来源及冻结规格不可替换')
            strategy = self._strategy(sid)
            values = {key: _text(value, key, key == 'name', 160 if key == 'name' else 12000)
                      for key, value in payload.items()}
            before = {key: strategy[key] for key in values}
            if values != before:
                stamp = iso()
                strategy.setdefault('edit_history', []).append({'at': stamp, 'previous': before, 'updated': copy.deepcopy(values)})
                strategy.update(values, updated_at=stamp)
                self._save()
            return self.detail(sid)

    def update_version(self, sid, vid, payload):
        with self.lock:
            version = self._version(sid, vid)
            if version['status'] != 'draft':
                raise StrategyError('首次验证后经济规则已冻结；实质修改请创建带依据的子版本')
            spec = normalize_spec(payload.get('spec', payload))
            if spec != version['spec']:
                version['edit_history'].append({'at': iso(), 'spec': copy.deepcopy(version['spec'])})
                version['spec'] = spec
            self._save()
            return self.detail(sid)

    def confirm_onboarding(self, sid, vid, payload):
        """Human confirmation binds to exact rules, without changing frozen specs."""
        with self.lock:
            version = self._version(sid, vid)
            if version['spec']['kind'] != TREND_KIND or not isinstance(payload, dict):
                raise StrategyError('参数确认仅适用于趋势策略')
            if set(payload) - {'keys', 'use_defaults'}:
                raise StrategyError('参数确认含未支持字段')
            keys = payload.get('keys', [])
            defaults = payload.get('use_defaults', False)
            allowed = set(version['spec']['rules'])
            if (not isinstance(keys, list) or any(not isinstance(k, str) or k not in allowed for k in keys)
                    or not isinstance(defaults, bool) or (not keys and not defaults)):
                raise StrategyError('请选择要确认的参数，或采用其余已显示值')
            binding = _hash(version['spec'])
            previous = version.get('onboarding', {})
            confirmed = set(previous.get('confirmed_keys', [])) if previous.get('rules_sha256') == binding else set()
            confirmed.update(allowed if defaults else keys)
            history = copy.deepcopy(previous.get('history', []))
            history.append({'at': iso(), 'keys': sorted(allowed if defaults else set(keys)),
                            'use_defaults': defaults, 'rules_sha256': binding,
                            'note': '确认当前页面已显示的规则；不覆盖已编辑参数'})
            version['onboarding'] = {'rules_sha256': binding, 'confirmed_keys': sorted(confirmed),
                                     'complete': confirmed == allowed, 'history': history}
            self._save()
            return self.detail(sid)

    def export_spec(self, sid, vid):
        """A deterministic derived document; persisted version remains authoritative."""
        with self.lock:
            strategy, version = self._strategy(sid), self._version(sid, vid)
            spec = version['spec']
            view = self._version_view(version)
            clean = lambda v: str(v).replace('\r', '').replace('\n', ' ').replace('|', '\\|')
            lines = [f"# 策略规格：{clean(strategy['name'])}", '',
                     '> 本文由策略版本记录确定性生成。修改本文不会修改程序规则；经济规则修改须创建子版本。', '',
                     f"- 策略 ID：`{sid}`", f"- 版本 ID：`{vid}`（{version['label']}）",
                     f"- 创建时间（UTC）：{version['created_at']}",
                     f"- 状态：{version['status']}；冻结时间：{version.get('frozen_at') or '尚未冻结'}",
                     f"- 规则 SHA-256：`{version.get('rules_sha256') or _hash(spec)}`",
                     f"- 实现：`{spec.get('implementation') or '待实现'}`；状态：{view['implementation_status']}",
                     f"- 经济假设：{clean(strategy['economic_hypothesis'])}", '', '## 可读规则', '']
            labels = {'contract_selection': '交易什么', 'entry': '何时入场', 'exit': '何时退出',
                      'position_constraints': '数量与仓位', 'decision_frequency': '检查与挂单',
                      'data_requirements': '数据及有效性', 'clock': '时间口径'}
            lines.extend(f"- **{label}**：{clean(spec.get(key) or '尚未明确')}" for key, label in labels.items())
            lines.extend(['', '## 程序参数', '', '| 参数 | 值 |', '|---|---|'])
            lines.extend(f"| `{key}` | `{clean(value)}` |" for key, value in sorted(spec.get('rules', {}).items()))
            if spec['kind'] == TREND_KIND:
                lines.extend(['', '## 权限与逐轮执行', '',
                    '仅允许 Deribit testnet 自动下单、撤单和对账；主网仅公共行情，永续只作信号来源。无真实资金交易、Shadow 或自动扩大研究预算授权。循环不使用模型。', '',
                    '每轮先检查项目根目录 STOP。存在时不查询账户、不下单、不撤单，仅记录停止和告警；已有挂单与仓位不会消失。每次交易写请求前再次检查 STOP。', '',
                    '有效轮次先拉取真实持仓、未结订单和新增成交；未知账户差异阻止新开仓。只管理本运行的订单与仓位。部分成交只按实际成交量和实际费用入账，以成交 ID 去重；不把提交数量记作成交数量。', '',
                    '先持久化订单意图与当日计数，再发请求。同一上穿事件最多尝试一次。拒绝、超时、未知仍占新单额度；请求不自动重试。撤单未确认终态不得提交替代单。超过订单或退出次数上限后等待人工处理。', '',
                    '每日额度及已消费的日线上穿按同一 testnet 账户跨运行核对，停止、重启或新建运行都不能重置。部分买入时仍每轮检查已成交仓位的退出条件；触发退出先撤剩余买单，确认终态和实际成交数量后才发减仓单。', '',
                    '提交或撤单结果未知时停止写请求并对账：联合检查持仓、活动订单、成交及订单历史；超过 label 查询窗口必须查询历史。重启进入待对账状态，不自动重新开仓；恢复须核对版本哈希、实现身份及未决订单。', '',
                    '交易所历史查询不完整保存旧的完全未成交取消单。查询不到不代表不存在，未知意图保持阻塞；只有能确定请求未发送或明确被拒绝时，才按该已知结果记账并在新鲜对账后考虑后续操作。', '',
                    '日常“暂停开仓”取消本策略未成交开仓单，继续对账和已定减仓规则。数据、认证、持久化或对账异常停止新的交易写请求，写入具体原因并告警；缺失值标未知，旧行情不得伪装新数据。', '',
                    '每轮记录 UTC 时间、价格及来源、指标、账户核对状态、决定和理由，包括什么都没做的轮次。页面与本地记录保留告警，并尝试桌面通知，送达失败明确显示。', '',
                    '## 数量与费用口径', '',
                    '数量单位为 BTC 名义量，合约乘数必须为 1。预算=min(BTC 权益×权益比例，可用 BTC)，单份成本=限价权利金+2×每份 BTC 单边费用上界。数量按 testnet 有效数量步长向下取整；不足最小量则跳过。账户或费率单位无法确认则禁止开仓；不利用返佣或折扣放大数量。', '',
                    '本实现不支持账户跨币抵押，未知账户费率或额外费用阻塞开仓。买入数量超过卖一可见深度也跳过。退出只要求有效买一及正买一量，不因卖一缺失放弃减仓；限价单可能部分成交或不成交。', '',
                    'Deribit 原生日线以 UTC 08:00 分界，本版用主网 BTC-PERPETUAL 的连续真实小时数据，每 24 根形成 UTC 00:00—次日00:00 日线；缺失或重复小时阻塞，不插值。原始小时记录与派生日线一并保留。', '',
                    '## 规格审查与损失情形', '',
                    '- 震荡会反复上穿、下穿并连续止损；均线是滞后信号。',
                    '- 标的缓慢上涨仍可能因时间损耗或隐含波动率下降而亏损。',
                    '- 止损是退出触发条件，不保证成交价或损失上限；盘口断档、限额或接口故障可能使权利金全部损失。',
                    '- STOP 或程序停止会中断本地风险处理；现存挂单和持仓仍有风险。',
                    '- 两边缺少相同经济规格、盘口过宽或最小交易量超过预算会跳过；不能为了交易而改选替代品。',
                    '- Testnet 流动性与成交不能证明主网盈利；本版尚未建立可交易优势。', '',
                    '## 验证状态', '',
                    '此导出只表明规格和实现能力，不证明任何真实成交。离线工件、真实 testnet 运行及成交状态须分别查看运行记录。主网信号、testnet 账本与 Greeks 曲面结果不可混合为收益曲线。'])
            else:
                lines.extend(['', '## 权限及失败机制', '', '仅本机研究与已批准的 Greeks 曲面验证；本文不授予任何交易权限。',
                              '', clean(strategy.get('failure_mechanisms') or '尚未明确；不得据此视作安全策略')])
            return '\n'.join(lines) + '\n'

    def freeze_version(self, sid, vid):
        with self.lock:
            version = self._version(sid, vid)
            if self._version_view(version)['spec_status'] != 'complete':
                raise StrategyError('规格未完成，不能冻结')
            if version['status'] != 'frozen':
                version.update(status='frozen', frozen_at=iso(), rules_sha256=_hash(version['spec']))
                self._save()
            return self.detail(sid)

    def _refs(self, sid, vid, refs, required=True):
        if not isinstance(refs, list) or (required and not refs) or len(refs) > 30:
            raise StrategyError('请列出属于当前版本的证据引用')
        known = {v['validation_id'] for v in self.data['validations'] if v['strategy_id'] == sid and v['version_id'] == vid}
        known |= {t['research_id'] for t in self.data['research_tasks'] if t['strategy_id'] == sid and t['version_id'] == vid and t.get('research_id')}
        known |= {d['decision_id'] for d in self.data['decisions'] if d['strategy_id'] == sid and d['version_id'] == vid}
        if any(not isinstance(ref, str) or ref not in known for ref in refs):
            raise StrategyError('证据不存在或归属其他策略/版本；请先显式关联历史')
        return list(dict.fromkeys(refs))

    def revise(self, sid, vid, payload):
        with self.lock:
            parent = self._version(sid, vid)
            if parent['status'] != 'frozen':
                raise StrategyError('草案可直接编辑；只有冻结版本创建修订子版本')
            if payload.get('change_kind', 'strategy_rules') != 'strategy_rules':
                raise StrategyError('费用/日期情景属于新验证；工程或核账修复保留原版本并记录复核')
            revision = {key: _text(payload.get(key), key) for key in ('reason', 'original_problem', 'changes', 'expected_improvement', 'possible_harm', 'comparison_plan')}
            revision.update(change_kind='strategy_rules', evidence_refs=self._refs(sid, vid, payload.get('evidence_refs')), created_at=iso())
            child = self._new_version(sid, payload.get('spec'), vid, revision)
            if _hash(child['spec']) == _hash(parent['spec']):
                raise StrategyError('经济规则没有改变；换日期、费用展示或工程修复不能创建策略新版本')
            self.data['versions'].append(child)
            self._strategy(sid)['current_version_id'] = child['version_id']
            self._save()
            return self.detail(sid)

    def add_decision(self, sid, vid, payload):
        with self.lock:
            self._version(sid, vid)
            action = payload.get('action')
            if action not in DECISIONS:
                raise StrategyError('决定须为保留、继续验证、修订、放弃或申请下一阶段')
            review_kind = payload.get('review_kind', 'economic')
            if review_kind not in {'economic', 'data_issue', 'engineering_repair'}:
                raise StrategyError('未知复核类型')
            if review_kind != 'economic' and action == 'revise':
                raise StrategyError('工程/数据修复不是交易规则进化；请保留版本并继续验证')
            decision = {'decision_id': uuid.uuid4().hex, 'strategy_id': sid, 'version_id': vid,
                        'action': action, 'reason': _text(payload.get('reason'), '决定理由'),
                        'evidence_refs': self._refs(sid, vid, payload.get('evidence_refs', []), required=False),
                        'actor': _text(payload.get('actor', '本机人类'), '决定人', limit=160),
                        'review_kind': review_kind, 'created_at': iso(),
                        'authorization_scope': '研究决定；不批准 Shadow、真实资金或订单'}
            self.data['decisions'].append(decision)
            self._save()
            return self.detail(sid)

    def _params(self, version, params):
        if not self._version_view(version)['can_validate']:
            raise StrategyError('规格未完成或待实现；当前数据/算法不能运行此验证')
        try:
            request = validate_experiment(params)
        except BacktestError as error:
            raise StrategyError(str(error)) from None
        actual = parameters_from_request(request)
        if any(actual[k] != version['spec']['rules'][k] for k in RULE_FIELDS):
            raise StrategyError('验证参数改变了冻结经济规则；请先创建子版本')
        return actual, request

    def _seen(self, sid, params):
        overlaps = [{'validation_id': v['validation_id'], 'version_id': v['version_id'],
                 'start_date': v['actual_request']['start_date'], 'end_date': v['actual_request']['end_date']}
                for v in self.data['validations'] if v.get('run_ids')
                and v.get('actual_request') and v['actual_request']['start_date'] <= params['end_date']
                and params['start_date'] <= v['actual_request']['end_date']]
        # Previously obtained results remain seen even when no strategy link
        # existed at their receipt time. Global request reuse must not relabel
        # those same bytes as an unseen validation sample.
        if hasattr(self.backtests, 'snapshot'):
            runs = self.backtests.snapshot()['runs']
        else:
            runs = getattr(self.backtests, 'runs', [])
            runs = list(runs.values()) if isinstance(runs, dict) else runs
        for run in runs:
            request = run.get('request', {})
            if (run.get('analysis') and request.get('start_date', '9999') <= params['end_date']
                    and params['start_date'] <= request.get('end_date', '')):
                overlaps.append({'run_id': run['run_id'], 'start_date': request['start_date'],
                                 'end_date': request['end_date'], 'scope': 'previously_received_result',
                                 'note': '本机已取得此范围结果；即使未建立策略关联，也不称为未见验证'})
        return overlaps

    def prepare_research(self, sid, vid, payload):
        """Durable intent before any researcher/model launch; explicit human approval only."""
        with self.lock:
            self._reconcile()
            strategy, version = self._strategy(sid), self._version(sid, vid)
            purpose = payload.get('purpose', 'validation')
            if purpose not in PURPOSES or payload.get('approved') is not True:
                raise StrategyError('须在页面明确批准本次有限研究预算及研究目的')
            key = payload.get('idempotency_key')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', key):
                raise StrategyError('无效的逻辑提交标识')
            question = _text(payload.get('question') or payload.get('purpose_text'), '本次研究目的', limit=3000)
            material = {'strategy_id': sid, 'version_id': vid, 'purpose': purpose, 'question': question,
                        'params': payload.get('params'), 'data_role': payload.get('data_role', 'research')}
            previous = next((r for r in self.data['research_tasks'] if r['idempotency_key'] == key), None)
            if previous:
                if previous['intent_sha256'] != _hash(material):
                    raise StrategyError('同一批准标识不能更换目标、版本或实验范围')
                return copy.deepcopy(previous['prepared'])
            if self.research and not self.research.availability.get('ready'):
                raise StrategyError(self.research.availability.get('reason', '研究入口尚不可用'))
            if sum(t.get('research_id') is not None or t['status'] == 'prepared' for t in self.data['research_tasks'] if t.get('stage') == 'S4A') >= 2:
                raise StrategyError('本轮 S4A 最多两项研究任务；不自动扩大批准范围')
            binding_id, validation_id = uuid.uuid4().hex, None
            context = {'strategy_id': sid, 'version_id': vid, 'purpose': purpose,
                       'source': copy.deepcopy(strategy['source']), 'version': copy.deepcopy(version),
                       'economic_hypothesis': strategy['economic_hypothesis'], 'failure_mechanisms': strategy['failure_mechanisms']}
            if purpose == 'validation':
                params, request = self._params(version, payload.get('params'))
                role = payload.get('data_role', 'research')
                if role not in {'research', 'validation'}:
                    raise StrategyError('本轮只能声明研究段或验证段；没有前向/Shadow 数据')
                seen = self._seen(sid, params)
                if seen and role == 'validation':
                    raise StrategyError('日期与已见结果重叠，不能再称为未见验证段；请选择研究段并保留重叠说明')
                if version['status'] != 'frozen':
                    version.update(status='frozen', frozen_at=iso(), rules_sha256=_hash(version['spec']))
                validation_id = uuid.uuid4().hex
                record = {'validation_id': validation_id, 'strategy_id': sid, 'version_id': vid,
                          'created_at': iso(), 'purpose': question, 'evidence_type': 'model_backtest',
                          'change_kind': 'validation', 'data_role': role, 'seen_overlaps': seen,
                          'actual_request': request, 'approved_experiment': params, 'run_ids': [],
                          'research_id': None, 'execution_status': 'prepared', 'error': None,
                          'data_source': 'Greeks.live BTC SABR/WV4 surface', 'price_basis': '模型曲面估值；不可成交 bid/ask',
                          'quantity_btc': params['quantity'], 'cost_assumption_bp': params['option_transaction_cost_bp']}
                self.data['validations'].append(record)
                context.update(validation_id=validation_id, approved_experiment=params, version=copy.deepcopy(version), data_role=role, seen_overlaps=seen)
            elif purpose == 'revision':
                context['evidence_refs'] = self._refs(sid, vid, payload.get('evidence_refs'))
                selected = set(context['evidence_refs'])
                for decision in self.data['decisions']:
                    if decision['decision_id'] in selected:
                        selected.update(decision['evidence_refs'])
                evidence = []
                allowed_runs = []
                for prior in self.data['validations']:
                    if (prior['strategy_id'], prior['version_id']) != (sid, vid):
                        continue
                    if prior['validation_id'] not in selected and prior.get('research_id') not in selected:
                        continue
                    view = self._validation_view(prior)
                    evidence.append({'validation_id': prior['validation_id'], 'purpose': prior['purpose'],
                        'actual_request': prior['actual_request'], 'data_role': prior['data_role'],
                        'seen_overlaps': prior.get('seen_overlaps', []), 'run_ids': prior['run_ids'],
                        'accounting_status': view['accounting_status'], 'economic_conclusion': view['economic_conclusion'],
                        'results': [{**{k: v for k, v in result.items() if k != 'accounting'},
                                     'accounting': {k: v for k, v in result.get('accounting', {}).items() if k != 'rows'}}
                                    for result in view['results']]})
                    allowed_runs.extend(prior['run_ids'])
                context['evidence'] = evidence
                context['available_run_ids'] = list(dict.fromkeys(allowed_runs))
                context['decisions'] = [copy.deepcopy(d) for d in self.data['decisions'] if d['decision_id'] in selected]
            prepared = {'binding_id': binding_id, 'validation_id': validation_id, 'context': context, 'question': question}
            self.data['research_tasks'].append({'binding_id': binding_id, 'strategy_id': sid, 'version_id': vid,
                'purpose': purpose, 'question': question, 'stage': 'S4A', 'idempotency_key': key,
                'intent_sha256': _hash(material), 'approved_at': iso(), 'status': 'prepared',
                'research_id': None, 'validation_id': validation_id, 'prepared': prepared})
            self._save()
            return copy.deepcopy(prepared)

    def _binding(self, identifier):
        binding = next((r for r in self.data['research_tasks'] if r['binding_id'] == identifier or r.get('validation_id') == identifier), None)
        if binding is None:
            raise StrategyError('研究归属记录不存在')
        return binding

    def bind_research(self, binding_id, research_id):
        with self.lock:
            binding = self._binding(binding_id)
            if binding.get('research_id') not in (None, research_id):
                raise StrategyError('研究归属已固定，不能替换任务')
            if not re.fullmatch(r'[a-f0-9]{32}', research_id):
                raise StrategyError('无效研究 ID')
            if any(r.get('research_id') == research_id and r['binding_id'] != binding['binding_id'] for r in self.data['research_tasks']):
                raise StrategyError('研究任务已归属其他策略/版本')
            if self.research:
                task = self.research.detail(research_id)
                context = task.get('strategy_context', task.get('context', {}))
                if (context != binding['prepared']['context']
                        or task.get('idempotency_key') != binding['idempotency_key']
                        or task.get('question') != binding['question']):
                    raise StrategyError('研究原始配置、批准标识或问题与归属不一致')
                version = self._version(binding['strategy_id'], binding['version_id'])
                if binding['purpose'] == 'validation' and (version['status'] != 'frozen'
                        or context['version']['rules_sha256'] != version['rules_sha256']):
                    raise StrategyError('研究冻结规格与当前绑定版本不一致')
            binding.update(research_id=research_id, status='bound')
            if binding.get('validation_id'):
                validation = next(v for v in self.data['validations'] if v['validation_id'] == binding['validation_id'])
                validation.update(research_id=research_id, execution_status='preparing')
            self._save()
            return copy.deepcopy(binding)

    def ensure_research_binding(self, research_id):
        """Fail closed on S4 orphan resume, or complete an exact durable intent."""
        with self.lock:
            if not self.research:
                raise StrategyError('研究服务不可用')
            task = self.research.detail(research_id)
            context = task.get('strategy_context')
            if not context:
                return None  # S3 original tasks do not gain a retroactive context.
            binding = next((r for r in self.data['research_tasks']
                            if r.get('research_id') == research_id
                            or r.get('idempotency_key') == task.get('idempotency_key')), None)
            if binding is None or not binding.get('prepared'):
                raise StrategyError('此 S4 研究没有对应的持久批准记录，拒绝继续')
            return self.bind_research(binding['binding_id'], research_id)

    def mark_start_failed(self, binding_id, error):
        with self.lock:
            binding = self._binding(binding_id)
            binding.update(status='start_failed', error=str(error))
            if binding.get('validation_id'):
                next(v for v in self.data['validations'] if v['validation_id'] == binding['validation_id']).update(execution_status='start_failed', error=str(error))
            self._save()

    def link_history(self, sid, vid, payload):
        """Append provenance only; never edit an old task or assign it a new input."""
        with self.lock:
            version = self._version(sid, vid)
            run_id = payload.get('run_id')
            try:
                run = self.backtests.get_run(run_id)
                params, request = self._params(version, parameters_from_request(run['request']))
            except (BacktestError, KeyError, IndexError, TypeError) as error:
                raise StrategyError('无法将该回测关联为此版本验证：' + str(error)) from None
            research_id = payload.get('research_id')
            if research_id:
                if not self.research:
                    raise StrategyError('研究历史不可用')
                task = self.research.detail(research_id)
                if run_id not in task.get('available_run_ids', []):
                    raise StrategyError('该研究记录没有该回测证据')
                existing = next((t for t in self.data['research_tasks'] if t.get('research_id') == research_id), None)
                if existing and (existing['strategy_id'], existing['version_id']) != (sid, vid):
                    raise StrategyError('该研究已归属其他策略或版本；不能重绑')
                if not existing:
                    self.data['research_tasks'].append({'binding_id': uuid.uuid4().hex, 'strategy_id': sid, 'version_id': vid,
                        'purpose': 'historical_validation', 'question': task.get('question', ''), 'stage': 'historical',
                        'idempotency_key': 'history-' + research_id, 'research_id': research_id, 'status': 'historical_link',
                        'created_at': iso(), 'original_input_unchanged': True, 'validation_id': None})
            previous = next((v for v in self.data['validations'] if v['strategy_id'] == sid and v['version_id'] == vid and run_id in v['run_ids']), None)
            if previous:
                return self.detail(sid)
            if version['status'] != 'frozen':
                version.update(status='frozen', frozen_at=iso(), rules_sha256=_hash(version['spec']))
            record = {'validation_id': uuid.uuid4().hex, 'strategy_id': sid, 'version_id': vid, 'created_at': iso(),
                      'purpose': _text(payload.get('purpose', '显式关联已保存历史模型证据'), '历史关联目的'),
                      'evidence_type': 'model_backtest', 'change_kind': 'historical_link', 'data_role': 'already_seen',
                      'seen_overlaps': self._seen(sid, params), 'actual_request': request, 'approved_experiment': params,
                      'run_ids': [run_id], 'research_id': research_id, 'execution_status': run['status'], 'error': None,
                      'data_source': 'Greeks.live 已保存 report / details / daily', 'price_basis': '模型曲面估值；不可成交 bid/ask',
                      'quantity_btc': params['quantity'], 'cost_assumption_bp': params['option_transaction_cost_bp'],
                      'linked_at': iso(), 'original_records_unchanged': True}
            self.data['validations'].append(record)
            self._save()
            return self.detail(sid)

    def fee_scenario(self, sid, vid, payload):
        with self.lock:
            self._reconcile()
            self._version(sid, vid)
            source = next((v for v in self.data['validations'] if v['validation_id'] == payload.get('validation_id') and v['strategy_id'] == sid and v['version_id'] == vid), None)
            if not source or len(source['run_ids']) != 1:
                raise StrategyError('费用情景须明确引用本版本的一份实际验证账本')
            run = self.backtests.get_run(source['run_ids'][0])
            rate = payload.get('higher_fee_bp')
            try:
                compare_fee_scenario(run.get('analysis'), rate, run_id=run['run_id'])
            except ValueError as error:
                raise StrategyError(str(error)) from None
            record = copy.deepcopy(source)
            record.update(validation_id=uuid.uuid4().hex, created_at=iso(), purpose=_text(payload.get('purpose', '同账本费用压力情景'), '验证目的'),
                          change_kind='cost_scenario', parent_validation_id=source['validation_id'], higher_fee_bp=rate,
                          research_id=None, data_role='already_seen', execution_status='completed',
                          cost_assumption_bp=rate, seen_overlaps=[{'validation_id': source['validation_id']}])
            self.data['validations'].append(record)
            self._save()
            return self.detail(sid)

    def _reconcile(self):
        if not self.research or self.storage_error:
            return
        changed = False
        for binding in self.data['research_tasks']:
            if not binding.get('research_id') or not binding.get('validation_id'):
                continue
            try:
                task = self.research.detail(binding['research_id'])
            except (ValueError, KeyError, ResearchError):
                continue
            validation = next(v for v in self.data['validations'] if v['validation_id'] == binding['validation_id'])
            ids = list(validation['run_ids'])
            mismatches = []
            for action in task.get('actions', []):
                if action.get('action') != 'run_backtest':
                    continue
                for rid in action.get('previous_run_ids', []) + ([action['run_id']] if action.get('run_id') else []):
                    if rid in ids:
                        continue
                    try:
                        run = self.backtests.get_run(rid)
                        actual = parameters_from_request(run['request'])
                        if actual != validation['approved_experiment']:
                            mismatches.append(rid)
                            continue
                        ids.append(rid)
                    except (BacktestError, KeyError, TypeError):
                        mismatches.append(rid)
            fields = {'run_ids': ids, 'execution_status': task['status'], 'error': task.get('error'), 'rejected_run_ids': mismatches}
            if any(validation.get(k) != v for k, v in fields.items()):
                validation.update(fields)
                changed = True
        if changed:
            self._save()

    def _charts(self, record, run, task=None):
        analysis = run.get('analysis') or {}
        metadata = {'strategy_id': record['strategy_id'], 'version_id': record['version_id'], 'validation_id': record['validation_id'],
                    'run_id': run['run_id'], 'start_date': run['request'].get('start_date'), 'end_date': run['request'].get('end_date'),
                    'currency': 'BTC', 'price_basis': analysis.get('price_source', record['price_basis']),
                    'cost_assumption': (f"同账本压力费用 {record['higher_fee_bp']} bp；基础与压力分别标注" if record.get('higher_fee_bp') is not None else analysis.get('fee_assumption', '未知')), 'quantity_btc': record['quantity_btc'],
                    'sample_count': analysis.get('audit', {}).get('lot_count'), 'gaps': analysis.get('gaps', []),
                    'result_url': '/backtest?run_id=' + run['run_id'], 'data_role': record['data_role'],
                    'seen_overlaps': record.get('seen_overlaps', []), 'accounting_sha256': _hash(analysis),
                    'analysis_history_count': len(run.get('analysis_history', []))}
        charts = {'metadata': metadata, 'cumulative': None, 'fees': None, 'chart_gaps': []}
        if analysis.get('model_ledger_verified') is not True:
            charts['chart_gaps'].append('BTC 模型账本未核对；不从汇总数字生成收益曲线或费用图')
            return charts
        path = self.root / 'local' / 'backtests' / run['run_id'] / 'daily.csv'
        try:
            if path.stat().st_size > 20_000_000:
                raise ValueError('daily too large')
            raw = path.read_bytes()
            rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True))
            if not rows or len(rows) != analysis.get('audit', {}).get('daily_rows'):
                raise ValueError('daily count')
            points, total, previous = [], Decimal(0), None
            with localcontext() as ctx:
                ctx.prec = 80
                for index, row in enumerate(rows):
                    stamp = date.fromisoformat(row['date'])
                    if previous is not None and stamp != previous + timedelta(days=1):
                        raise ValueError('daily gap')
                    if any(row.get(k) != v for k, v in {'asset': 'BTC', 'numeraire': 'BTC', 'daily_return_valid': 'True', 'valuation_complete': 'True', 'result_complete': 'True'}.items()):
                        raise ValueError('daily status')
                    pnl, cumulative = Decimal(row['total_pnl']), Decimal(row['cum_pnl'])
                    if not pnl.is_finite() or not cumulative.is_finite():
                        raise ValueError('daily numeric')
                    total += pnl
                    if abs(cumulative - total) > MODEL_TOLERANCE:
                        raise ValueError('daily cumulative')
                    points.append({'date': row['date'], 'cumulative_btc': str(cumulative), 'pnl_btc': str(pnl),
                                   'source': {'file': 'daily.csv', 'row': index + 2, 'field': 'cum_pnl', 'run_id': run['run_id']}})
                    previous = stamp
                if rows[0]['date'] != run['request']['start_date'] or rows[-1]['date'] < run['request']['end_date']:
                    raise ValueError('daily range')
                if abs(total - Decimal(analysis['btc_net_pnl'])) > MODEL_TOLERANCE:
                    raise ValueError('daily total')
            charts['cumulative'] = {'title': '累计 BTC 模型损益', 'points': points, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                    'source': 'daily.csv: cum_pnl；逐日总额与已核对 BTC 账本再次一致；不等于账户收益', 'connect_gaps': False}
        except (OSError, ValueError, KeyError, InvalidOperation, UnicodeError, csv.Error, TypeError):
            charts['chart_gaps'].append('完整且一致的每日数据不可得；没有生成或补零累计曲线')
        if record.get('change_kind') == 'cost_scenario':
            charts['cumulative'] = None
            charts['chart_gaps'].append('此记录是同账本费用压力情景；不把基础费用累计曲线冒充压力费用曲线')
        with localcontext() as ctx:
            ctx.prec = 80
            gross = Decimal(analysis['exit_income_btc']) - Decimal(analysis['premium_paid_btc'])
        bars = [{'label': '费用前模型损益', 'value_btc': str(gross), 'field': 'exit_income_btc - premium_paid_btc'},
                {'label': '基础费用', 'value_btc': analysis['fees_btc'], 'field': 'fees_btc'},
                {'label': '基础费用后净损益', 'value_btc': analysis['btc_net_pnl'], 'field': 'btc_net_pnl'}]
        fee = None
        if record.get('higher_fee_bp') is not None:
            fee = compare_fee_scenario(analysis, record['higher_fee_bp'], run_id=run['run_id'])
        elif task:
            evidence = next((e for e in task.get('evidence', []) if e.get('run_id') == run['run_id']), {})
            saved_fee = evidence.get('fee_comparison')
            if saved_fee:
                try:
                    fee = compare_fee_scenario(analysis, saved_fee['higher_fee_bp'], run_id=run['run_id'])
                except (ValueError, KeyError):
                    charts['chart_gaps'].append('旧费用比较与当前核账口径不兼容，未混合展示；旧派生仍在研究原记录')
        if fee:
            bars.extend([{'label': '压力费用', 'value_btc': fee['higher_fees_btc'], 'field': 'fee_comparison.higher_fees_btc'},
                         {'label': '压力费用后净损益', 'value_btc': fee['higher_net_btc'], 'field': 'fee_comparison.higher_net_btc'}])
        charts['fees'] = {'title': '费用分解与同账本压力情景', 'bars': bars, 'fee_comparison': fee,
                          'source': '关联 run 的确定性 BTC 核账；每个字段保留精度；费用仅扣一次'}
        return charts

    def _validation_view(self, record):
        value = copy.deepcopy(record)
        task = None
        if record.get('research_id') and self.research:
            try:
                task = self.research.detail(record['research_id'])
            except (ValueError, KeyError, ResearchError):
                value['research_error'] = '关联研究原文件暂不可读取；已保存关联与回测证据保留'
        results, charts = [], []
        for rid in record['run_ids']:
            try:
                run = self.backtests.get_run(rid)
                analysis = run.get('analysis') or {}
                results.append({'run_id': rid, 'execution_status': run['status'], 'accounting_status': analysis.get('status', 'not_available'),
                                'model_ledger_verified': analysis.get('model_ledger_verified') is True,
                                'accounting': analysis, 'result_url': '/backtest?run_id=' + rid,
                                'analysis_history_count': len(run.get('analysis_history', [])), 'error': run.get('error')})
                charts.append(self._charts(record, run, task))
            except BacktestError:
                results.append({'run_id': rid, 'error': '关联原始回测暂不可读取'})
        value['results'], value['charts'] = results, charts
        verified = bool(results) and all(r.get('model_ledger_verified') for r in results)
        value['accounting_status'] = 'verified' if verified else 'not_verified'
        final = (task or {}).get('final_presentation') or (task or {}).get('final') or {}
        value['economic_conclusion'] = final.get('verdict') or '尚未建立经济支持；核账完成不等于策略有效'
        # Use the existing audited derived presentation, never revive financial
        # literals that the S3 presentation deliberately withheld.
        value['interpretation'] = copy.deepcopy(final.get('interpretation') or {})
        value['counterexamples'] = copy.deepcopy(value['interpretation'].get('counterexamples', []))
        value['limitations'] = list(dict.fromkeys(value['interpretation'].get('unknowns', [])
            + [gap for result in results for gap in result.get('accounting', {}).get('gaps', [])]))
        value['suggested_next_step'] = (final.get('future') or {}).get('next_step')
        value['next_step_status'] = (final.get('future') or {}).get('status', '尚无下一步建议')
        value['bound_facts'] = [copy.deepcopy(fact) for fact in final.get('facts', []) if fact.get('run_id') in record['run_ids']]
        value['interpretation_scope'] = '研究解释与引用基于原任务的已保存证据；图表基于关联回测的当前核账派生。旧核账保留于回测历史，工程修复不产生策略新版本' 
        value['presentation_source_sha256'] = final.get('source_final_sha256')
        value['effective_result'] = None
        if len(results) == 1 and results[0].get('model_ledger_verified'):
            accounting = results[0]['accounting']
            if record.get('higher_fee_bp') is not None:
                scenario = compare_fee_scenario(accounting, record['higher_fee_bp'], run_id=results[0]['run_id'])
                net, field = scenario['higher_net_btc'], 'fee_comparison.higher_net_btc'
            else:
                net, field = accounting['btc_net_pnl'], 'accounting.btc_net_pnl'
            value['effective_result'] = {'net_btc': net, 'field': field, 'run_id': results[0]['run_id'],
                                         'validation_id': record['validation_id'], 'cost_assumption_bp': record['cost_assumption_bp']}
        value['research_url'] = '/research?research_id=' + record['research_id'] if record.get('research_id') else None
        if record.get('rejected_run_ids'):
            failure = 'engineering_failure'
        elif record['execution_status'] in {'tool_failed', 'model_failed', 'start_failed', 'submission_unknown', 'invalid_output', 'failed', 'internal_error', 'model_timeout', 'authentication_failed', 'model_unavailable', 'usage_limit'}:
            failure = 'engineering_failure'
        elif results and not verified:
            failure = 'data_insufficient'
        elif final.get('verdict') in {'否定候选', '不支持', 'reject'}:
            failure = 'economic_not_supported'
        else:
            failure = None
        value['failure_class'] = failure
        return value

    def _comparison(self, versions, validations):
        result = []
        for child in versions:
            if not child.get('parent_version'):
                continue
            left = [v for v in validations if v['version_id'] == child['parent_version'] and v['run_ids']]
            right = [v for v in validations if v['version_id'] == child['version_id'] and v['run_ids']]
            if not left or not right:
                result.append({'parent_version': child['parent_version'], 'version_id': child['version_id'], 'comparable': False, 'differences': ['新旧版本尚未均取得实际结果']})
                continue
            a, b = left[-1], right[-1]
            fields = ('start_date', 'end_date', 'session_bucket', 'quantity')
            differences = [key for key in fields if a['approved_experiment'][key] != b['approved_experiment'][key]]
            if a['cost_assumption_bp'] != b['cost_assumption_bp']:
                differences.append('cost_assumption_bp')
            if a['evidence_type'] != b['evidence_type']:
                differences.append('evidence_type')
            if a['accounting_status'] != 'verified' or b['accounting_status'] != 'verified':
                differences.append('账本尚未双方核对')
            result.append({'parent_version': child['parent_version'], 'version_id': child['version_id'],
                           'left_validation_id': a['validation_id'], 'right_validation_id': b['validation_id'],
                           'comparable': not differences, 'differences': differences,
                           'left_result': a['effective_result'], 'right_result': b['effective_result'],
                           'note': '共同条件可描述模型差异；同段已见数据不是独立样本外证据，不自动判定改善',
                           'independent_evidence': False})
        return result

    def detail(self, sid):
        with self.lock:
            self._reconcile()
            strategy = copy.deepcopy(self._strategy(sid))
            versions = [self._version_view(v) for v in self.data['versions'] if v['strategy_id'] == sid]
            validations = [self._validation_view(v) for v in self.data['validations'] if v['strategy_id'] == sid]
            tasks = []
            for binding in self.data['research_tasks']:
                if binding['strategy_id'] != sid:
                    continue
                item = {k: copy.deepcopy(v) for k, v in binding.items() if k not in {'prepared', 'intent_sha256'}}
                if binding.get('research_id') and self.research:
                    try:
                        task = self.research.detail(binding['research_id'])
                    except (ValueError, KeyError, ResearchError):
                        item.update(status='history_unavailable', error='关联研究原文件暂不可读取；原关联保留')
                    else:
                        item.update(status=task['status'], budget=task['budget'], model_proposal=task.get('model_proposal'),
                                    can_resume=task.get('can_resume'), can_stop=task.get('can_stop'), error=task.get('error'),
                                    research_url='/research?research_id=' + task['research_id'])
                tasks.append(item)
            return {'strategy': strategy, 'versions': versions, 'validations': validations,
                    'decisions': copy.deepcopy([d for d in self.data['decisions'] if d['strategy_id'] == sid]),
                    'research_tasks': tasks, 'comparison': self._comparison(versions, validations),
                    'mode': 'S4A 本机研究；独立 Deribit testnet 执行，无主网私人接口、真实资金或 Shadow 授权', 'storage_error': self.storage_error}

    def snapshot(self):
        with self.lock:
            strategies, attention = [], []
            for strategy in self.data['strategies']:
                detail = self.detail(strategy['strategy_id'])
                version = next(v for v in detail['versions'] if v['version_id'] == strategy['current_version_id'])
                validations = [v for v in detail['validations'] if v['version_id'] == version['version_id']]
                decisions = [d for d in detail['decisions'] if d['version_id'] == version['version_id']]
                latest, decision = (validations[-1] if validations else None), (decisions[-1] if decisions else None)
                tasks = [t for t in detail['research_tasks'] if t['version_id'] == version['version_id']]
                active = next((t for t in tasks if t['status'] in ACTIVE), None)
                if active:
                    next_action = '查看正在进行的研究'
                elif decision and decision['action'] == 'abandon':
                    next_action = '查看放弃理由与历史'
                elif version['spec_status'] == 'incomplete':
                    next_action = '补充规格或让研究员形成提案'
                elif version['implementation_status'] != 'implemented':
                    next_action = '查看并补充数据需求 / 实施任务'
                elif version['can_run_testnet']:
                    next_action = '查看 testnet 运行' if version['status'] == 'frozen' else '确认参数并冻结 testnet 规格'
                elif latest:
                    next_action = '记录保留、修订或放弃决定'
                elif version['parent_version']:
                    next_action = '批准共同条件下的对照验证'
                else:
                    next_action = '批准一次有限验证'
                row = {**copy.deepcopy(strategy), 'current_version': version['label'], 'version_status': version['status'],
                       'kind': version['spec']['kind'], 'can_validate': version['can_validate'],
                       'can_run_testnet': version['can_run_testnet'],
                       'spec_status': version['spec_status'], 'implementation_status': version['implementation_status'],
                       'latest_validation_type': latest['evidence_type'] if latest else None,
                       'evidence_conclusion': latest['economic_conclusion'] if latest else '尚无验证证据',
                       'latest_decision': decision, 'running_observation': False, 'running_shadow': False,
                       'research_running': bool(active), 'next_action': next_action}
                strategies.append(row)
                attention.append({'strategy_id': strategy['strategy_id'], 'name': strategy['name'], 'action': next_action})
            return {'strategies': strategies, 'attention': attention, 'mode': 'S4A 本机研究；独立 Deribit testnet 执行，无主网私人接口、真实资金或 Shadow 授权',
                    'storage_error': self.storage_error, 'server_time': iso(),
                    'research_tasks_used': sum(bool(t.get('research_id')) for t in self.data['research_tasks'] if t.get('stage') == 'S4A'),
                    'research_tasks_limit': 2}

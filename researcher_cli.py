"""Noninteractive ChatGPT CLI adapter. No credential files are opened here."""
from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from backtest import save_json, atomic_write

DISABLED_FEATURES = ('apps', 'plugins', 'hooks', 'memories', 'goals', 'multi_agent', 'multi_agent_v2',
                     'browser_use', 'browser_use_external', 'computer_use', 'image_generation',
                     'in_app_browser', 'shell_snapshot', 'skill_mcp_dependency_install',
                     'skill_search', 'tool_suggest', 'unbounded_connection_retries', 'view_image',
                     'workspace_dependencies')

# Explicitly reviewed releases, never a range or a caller-provided allowlist.
# The previous release remains documented; it is not silently substituted for
# the CLI configuration saved with a running task.
VERIFIED_CLI_RELEASES = {
    '0.158.0-alpha.2.1': 's3-named-permissions-v1',
    '0.159.2': 's4a-named-permissions-v1',
}
REQUIRED_EXEC_FLAGS = ('--ignore-user-config', '--ignore-rules', '--ephemeral',
                       '--skip-git-repo-check', '--json', '--color', '--model',
                       '--cd', '--output-schema', '--output-last-message')
OFFICIAL_COMPATIBILITY_SOURCES = [
    'https://learn.chatgpt.com/docs/developer-commands?surface=cli',
    'https://learn.chatgpt.com/docs/auth',
    'https://learn.chatgpt.com/docs/non-interactive-mode',
    'https://learn.chatgpt.com/docs/permissions',
    'https://learn.chatgpt.com/docs/config-file/config-reference',
    'https://developers.openai.com/api/docs/models/gpt-6-astra',
]


class ModelError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validate_schema(value, schema):
    """Validate the deliberately small checked-in schema, independently of CLI."""
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                validate_schema(value, branch)
                return
            except ValueError:
                pass
        raise ValueError('字段类型不匹配')
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'number': type(value) in (float, int),
             'integer': type(value) is int, 'null': value is None}.get(kind, False)
    if not valid:
        raise ValueError('输出字段类型错误')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('输出枚举值错误')
    if kind == 'object':
        if set(value) != set(schema['required']):
            raise ValueError('输出字段缺失或包含额外字段')
        for k, v in value.items():
            validate_schema(v, schema['properties'][k])
    elif kind == 'array':
        if len(value) > schema.get('maxItems', 100):
            raise ValueError('输出数组过长')
        for v in value:
            validate_schema(v, schema['items'])
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 10000):
            raise ValueError('输出文字长度错误')
    elif kind in ('number', 'integer'):
        import math
        if not math.isfinite(value) or not schema.get('minimum', -1e100) <= value <= schema.get('maximum', 1e100):
            raise ValueError('输出数字范围错误')


def clean_environment(workspace):
    # Host authentication stays at its existing location; neither cache nor keys are copied.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'CODEX_HOME') if k in os.environ}
    env.update(NO_COLOR='1')
    return env


def permission_overrides(workspace):
    fs = {':root': 'deny', ':minimal': 'read', str(Path(workspace).resolve()): 'read',
          ':tmpdir': 'deny', ':slash_tmp': 'deny'}
    # Workspace itself is read-only. The CLI host writes outputs outside it.
    table = '{' + ','.join(json.dumps(k) + '=' + json.dumps(v) for k, v in fs.items()) + '}'
    return ['default_permissions="researcher"', 'permissions.researcher.filesystem=' + table,
            'permissions.researcher.network.enabled=false', 'approval_policy="never"']


def cli_overrides(workspace, prompt_path, config):
    values = permission_overrides(workspace) + [
        'model_reasoning_effort=' + json.dumps(config['reasoning_effort']),
        'service_tier=' + json.dumps(config['service_tier']),
        'model_instructions_file=' + json.dumps(str(prompt_path)),
        'project_doc_max_bytes=0', 'web_search="disabled"', 'mcp_servers={}',
        'shell_environment_policy.inherit="none"', 'shell_environment_policy.set={PATH="/usr/bin:/bin:/usr/sbin:/sbin"}',
        'features.skip_host_skill_discovery=true', 'skills.max_context_tokens=1', 'features.fast_mode=false',
        'model_provider="openai"', 'forced_login_method="chatgpt"',
        'agents.enabled=false', 'allow_login_shell=false',
    ]
    values += ['features.' + name + '=false' for name in DISABLED_FEATURES]
    return values


def _cli_read(executable, arguments, workspace):
    result = subprocess.run([executable, *arguments], capture_output=True, text=True,
                            timeout=20, cwd=workspace, env=clean_environment(workspace))
    if result.returncode != 0:
        raise ValueError('CLI 只读检查未成功：' + ' '.join(arguments[:3]))
    return result.stdout + result.stderr


def check_cli_identity(executable, config):
    """No inference: fail closed on version/login drift before every model call."""
    if not executable:
        raise ValueError('未找到 Codex CLI')
    raw = _cli_read(executable, ['--version'], tempfile.gettempdir())
    match = re.fullmatch(r'codex-cli ([0-9A-Za-z.+-]+)', raw.strip())
    actual = match.group(1) if match else 'unrecognized'
    if actual not in VERIFIED_CLI_RELEASES or actual != config.get('cli_version_verified'):
        raise ValueError('CLI 版本未核实或与任务配置不同：' + actual)
    if (config.get('model'), config.get('reasoning_effort'), config.get('service_tier')) != ('gpt-6-astra', 'high', 'default'):
        raise ValueError('固定 researcher 模型、推理或速度配置不匹配')
    login = _cli_read(executable, ['login', 'status'], tempfile.gettempdir())
    if login.strip() != 'Logged in using ChatGPT':
        raise ValueError('需要 ChatGPT 订阅登录；不接受 API key 或其他认证')
    return {'cli_version': actual, 'login_status': 'Logged in using ChatGPT',
            'compatibility_profile': VERIFIED_CLI_RELEASES[actual]}


def check_cli_compatibility(executable, config, evidence_dir=None):
    """Check exact CLI capabilities and real sandbox, without a model request.

    Catalog presence is metadata evidence only, not proof of live entitlement.
    Startup failure disables research while callers can keep history available.
    """
    snapshot = {'checked_at': datetime.now(timezone.utc).isoformat(),
                'model_calls': 0, 'official_sources': OFFICIAL_COMPATIBILITY_SOURCES,
                'model': config.get('model'), 'reasoning_effort': config.get('reasoning_effort'),
                'service_tier': config.get('service_tier'), 'authentication': 'chatgpt_subscription',
                'evidence_reference': 'docs/samples/s4a-cli-compatibility.json'}
    status = {'ready': False, 'cli_version': '未检测到', 'login_status': '未检查',
              'isolation_status': '尚未通过本机权限检查', 'runtime_snapshot': snapshot}
    try:
        identity = check_cli_identity(executable, config)
        status.update(cli_version=identity['cli_version'], login_status=identity['login_status'])
        snapshot.update(identity)
        with tempfile.TemporaryDirectory(prefix='optimatrix-compat-') as temporary:
            workspace = Path(temporary).resolve()
            prompt_path = workspace / 'prompt.md'
            prompt_path.write_text('Compatibility metadata check only. No research.\n')
            help_text = _cli_read(executable, ['exec', '--help'], workspace)
            if not all(flag in help_text for flag in REQUIRED_EXEC_FLAGS):
                raise ValueError('CLI 缺少必要的非交互参数')
            sandbox_help = _cli_read(executable, ['sandbox', '--help'], workspace)
            if '--permission-profile' not in sandbox_help or '--cd' not in sandbox_help:
                raise ValueError('CLI 缺少已验证的命名权限机制')
            overrides = cli_overrides(workspace, prompt_path, config)
            args = ['debug', 'models', '--bundled']
            for value in overrides:
                args += ['-c', value]
            # Uses bundled catalog, never refreshes through a paid model API.
            catalog = json.loads(_cli_read(executable, args, workspace))
            models = catalog.get('models', []) if isinstance(catalog, dict) else catalog
            model = next((m for m in models if isinstance(m, dict) and m.get('slug') == config['model']), None)
            if not model or config['reasoning_effort'] not in [v['effort'] for v in model.get('supported_reasoning_levels', [])]:
                raise ValueError('本机目录未确认固定模型及推理级别')
            snapshot.update(exec_flags=list(REQUIRED_EXEC_FLAGS),
                exec_help_sha256=hashlib.sha256(help_text.encode()).hexdigest(),
                sandbox_help_sha256=hashlib.sha256(sandbox_help.encode()).hexdigest(),
                model_catalog={'source': 'codex debug models --bundled', 'slug': model['slug'],
                    'reasoning_levels': [v['effort'] for v in model['supported_reasoning_levels']],
                    'live_entitlement_verified': False},
                overrides=[v.replace(str(workspace), '<prepared_input>') for v in overrides])
        isolation = check_isolation(executable)
        snapshot['isolation'] = isolation
        if isolation.get('passed') is not True:
            raise ValueError('本机实际沙盒检查未通过')
        status.update(ready=True, isolation_status='本机沙盒检查通过',
                      reason='固定 CLI、ChatGPT 登录、模型目录与本机隔离检查已确认')
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as error:
        status['reason'] = str(error)[:240] or 'CLI 兼容检查失败；不会切换模型或认证方式'
    if evidence_dir is not None:
        save_json(Path(evidence_dir) / 'compatibility-latest.json', status)
    return status


def terminate_owned(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        except ProcessLookupError:
            pass


class CodexRunner:
    def __init__(self, executable):
        self.executable = executable

    def run(self, *, input_data, config, prompt, schema, directory, stop_event):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        save_json(directory / 'input.json', input_data)
        try:
            identity = check_cli_identity(self.executable, config)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ModelError('cli_incompatible', str(error)[:240]) from None
        # Do not inherit project AGENTS, ~/.agents, cwd, shell startup files or app environment.
        with tempfile.TemporaryDirectory(prefix='optimatrix-research-') as temporary:
            workspace = Path(temporary).resolve()
            atomic_write(workspace / 'prompt.md', prompt.encode())
            save_json(workspace / 'schema.json', schema)
            save_json(workspace / 'input.json', input_data)
            args = [self.executable, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
                    '--skip-git-repo-check', '--json', '--color', 'never', '-m', config['model'],
                    '-C', str(workspace), '--output-schema', str(workspace / 'schema.json'),
                    '--output-last-message', str(directory / 'final.json')]
            for value in cli_overrides(workspace, workspace / 'prompt.md', config):
                args += ['-c', value]
            args += ['-']
            save_json(directory / 'invocation.json', {'argv': args, 'configuration': config,
                'actual_cli_identity': identity,
                'environment_keys': sorted(clean_environment(workspace)), 'workspace': str(workspace)})
            started = time.monotonic()
            with (directory / 'events.jsonl').open('w') as events, (directory / 'stderr.txt').open('w') as errors:
                try:
                    input_stream = (directory / 'input.json').open()
                    process = subprocess.Popen(args, stdin=input_stream, stdout=events, stderr=errors,
                        cwd=workspace, env=clean_environment(workspace), text=True, start_new_session=True)
                except OSError:
                    if 'input_stream' in locals():
                        input_stream.close()
                    raise ModelError('cli_unavailable', 'Codex CLI 无法启动') from None
                try:
                    while process.poll() is None:
                        if stop_event.wait(0.15):
                            raise ModelError('stopped', '研究已停止；仅终止本任务拥有的 CLI 子进程')
                        if time.monotonic() - started > config['limits']['model_timeout_seconds']:
                            raise ModelError('model_timeout', '模型子进程超时；没有自动重试')
                finally:
                    terminate_owned(process)
                    input_stream.close()
                    save_json(directory / 'process.json', {'exit_code': process.returncode,
                        'elapsed_seconds': round(time.monotonic() - started, 3)})
        return self.read_result(directory, schema)

    @staticmethod
    def read_result(directory, schema):
        directory = Path(directory)
        try:
            process = json.loads((directory / 'process.json').read_text())
            text = (directory / 'events.jsonl').read_text()
            diagnostics = (directory / 'stderr.txt').read_text() + text
            if not isinstance(process,dict) or type(process.get('exit_code')) is not int:
                raise ValueError('缺少进程退出状态')
        except (OSError,ValueError):
            raise ModelError('invalid_output','CLI 进程或运行事件文件缺失/无效') from None
        try:
            events = [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError:
            raise ModelError('invalid_output', 'CLI 运行事件不是有效 JSONL') from None
        if not all(isinstance(e,dict) for e in events):
            raise ModelError('invalid_output','CLI 运行事件必须为对象')
        if process['exit_code'] != 0 or any(e.get('type') == 'turn.failed' for e in events):
            states = [('usage_limit', r'usage limit|quota|limit reached|insufficient_quota'),
                      ('authentication_failed', r'not logged|unauthorized|401|token.*expired'),
                      ('model_unavailable', r'model.*not.*(available|supported|found)|model_not_found')]
            status = next((s for s, pattern in states if re.search(pattern, diagnostics, re.I)), 'model_failed')
            raise ModelError(status, {'usage_limit':'ChatGPT 订阅额度不足','authentication_failed':'ChatGPT 登录失效',
                'model_unavailable':'固定模型不可用；需人类确认替代模型','model_failed':'CLI 运行失败；原始诊断保存在本地'}[status])
        try:
            events = [json.loads(line) for line in text.splitlines() if line.strip()]
            if not any(e.get('type') == 'turn.completed' for e in events):
                raise ValueError('缺少 turn.completed 事件')
            # Native model actions beyond the configured sandbox are never application tool requests.
            value = json.loads((directory / 'final.json').read_text())
            validate_schema(value, schema)
        except (OSError, ValueError, TypeError) as error:
            raise ModelError('invalid_output', 'CLI 最终文件或输出结构无效：' + str(error)[:150]) from None
        save_json(directory / 'validated.json', value)
        return value


def check_isolation(executable):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    control_body = b'OPTIMATRIX-LOCAL-ISOLATION-CONTROL'

    class ControlHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(control_body)))
            self.end_headers()
            self.wfile.write(control_body)

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix='optimatrix-boundary-') as directory:
        base = Path(directory).resolve()
        workspace = base / 'input'
        workspace.mkdir()
        (workspace / 'allowed.txt').write_text('INPUT-AVAILABLE')
        fake = base / 'fake-sensitive.txt'
        fake.write_text('FAKE-SENSITIVE-NOT-A-SECRET')
        (workspace / 'escape-link').symlink_to(fake)
        # Fixed trusted check commands, not model-generated strings.
        script = '''
/bin/cat "$1/allowed.txt" >/dev/null && echo input_readable
/bin/cat "$2" >/dev/null 2>&1 || echo outside_read_denied
/bin/cat "$1/escape-link" >/dev/null 2>&1 || echo symlink_read_denied
/usr/bin/touch "$3" 2>/dev/null || echo outside_write_denied
/usr/bin/touch "$1/write.txt" 2>/dev/null || echo input_write_denied
'''
        args = [executable, 'sandbox', '-C', str(workspace), '-P', 'researcher']
        for value in permission_overrides(workspace):
            args += ['-c', value]
        file_args = args + ['/bin/sh', '-c', script, 'permission-check', str(workspace), str(fake), str(base/'forbidden.txt')]
        result = subprocess.run(file_args, capture_output=True, text=True, timeout=20, env=clean_environment(workspace))
        # A live local positive control rules out DNS, TLS, Internet outages or
        # a missing curl binary masquerading as a sandbox network denial.
        with ThreadingHTTPServer(('127.0.0.1', 0), ControlHandler) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
            thread.start()
            curl = ['/usr/bin/curl', '--noproxy', '*', '--fail', '--silent', '--show-error',
                    '--connect-timeout', '2', '--max-time', '3', f'http://127.0.0.1:{server.server_port}/']
            try:
                before = subprocess.run(curl, capture_output=True, timeout=5, env=clean_environment(workspace))
                network = subprocess.run(args + curl, capture_output=True, timeout=20, env=clean_environment(workspace))
                after = subprocess.run(curl, capture_output=True, timeout=5, env=clean_environment(workspace))
            finally:
                server.shutdown()
                thread.join(timeout=1)
        network_denied = (before.returncode == after.returncode == 0
                          and before.stdout == after.stdout == control_body
                          and network.returncode != 0 and control_body not in network.stdout)
        expected = {'input_readable','outside_read_denied','symlink_read_denied','outside_write_denied','input_write_denied','network_denied'}
        actual = set(result.stdout.splitlines())
        if network_denied:
            actual.add('network_denied')
        return {'passed': result.returncode == 0 and actual == expected and not (base/'forbidden.txt').exists(),
                'checks': sorted(actual), 'exit_code': result.returncode,
                'network_control_before_exit': before.returncode, 'network_control_after_exit': after.returncode,
                'network_control_expected_body': before.stdout == after.stdout == control_body,
                'network_sandbox_exit': network.returncode,
                'network_sandbox_diagnostic': network.stderr.decode('utf-8', errors='replace')[:500],
                'mechanism':'Codex named permissions profile; root deny, minimal runtime read, input read, network disabled',
                'fake_data_only':True}

"""One local process, one market collector, and explicit fixed backtest requests."""
import argparse
import fcntl
import hmac
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import shutil
import signal
import secrets
import subprocess
import time

from flask import Flask, jsonify, send_from_directory, request, abort, Response
from waitress import create_server

from backtest import BacktestError, BacktestService, EXPERIMENT_ID
from market import MarketService, iso, safe_traceback
from research import ResearchService, ResearchError
from workspace import workspace_snapshot
from strategies import StrategyService, StrategyError
from runtime import StrategyRuntimeService, RuntimeErrorState
from testnet import TestnetError
from onboarding import templates
from notifications import notify_desktop
from signal_observer import SignalStudyService
from researcher_cli import clean_environment

ROOT = Path(__file__).resolve().parent


def codex_status():
    status = {"installed": False, "version": "未检测到", "login_status": "未检查", "checked_at": iso()}
    executable = shutil.which("codex")
    if not executable:
        return status
    status["installed"] = True
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=3, env=clean_environment(ROOT))
        match = re.search(r"codex-cli ([0-9A-Za-z.+-]+)", version.stdout)
        status["version"] = match.group(1) if match else "版本未识别"
        result = subprocess.run([executable, "login", "status"], capture_output=True, text=True, timeout=3, env=clean_environment(ROOT))
        # Parse only recognized status. Never expose raw CLI output or credential files.
        output = result.stdout + result.stderr
        if result.returncode == 0:
            status["login_status"] = "CLI 报告已登录（ChatGPT）" if "Logged in using ChatGPT" in output else "CLI 报告存在登录凭据"
        elif "Not logged in" in output:
            status["login_status"] = "未登录"
        else:
            status["login_status"] = "状态检查失败"
    except (OSError, subprocess.TimeoutExpired):
        status["login_status"] = "状态检查超时或不可用"
    return status


def integrations():
    return {"account": "未接入 · 未读取账户或余额", "backtest": "未实现 · Greeks.live 未接入",
            "agent": "S3 researcher · 仅经页面授权运行研究 / 无交易权限", "codex": codex_status()}


def create_app(service, backtests=None, research=None, strategies=None, runtime=None, signal_studies=None):
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    workbench_token = research.csrf_token if research is not None else secrets.token_urlsafe(32)

    @app.before_request
    def local_only():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
            abort(400)

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/")
    def home():
        return send_from_directory(ROOT / "static", "strategies.html")

    @app.get("/strategies")
    @app.get("/operations")
    def strategies_page():
        return send_from_directory(ROOT / "static", "strategies.html")

    @app.get('/signals')
    def signal_studies_page():
        return send_from_directory(ROOT / 'static', 'signals.html')

    @app.get('/api/signal-studies')
    def signal_studies_state():
        # Pure cached read; requests never create a worker, access accounts or fetch markets.
        return jsonify(signal_studies.snapshot() if signal_studies is not None else
                       {'status': 'not_started', 'authority': 'public_observation_only', 'candidates': [], 'catalog': []})

    @app.get("/market")
    def market_page():
        return send_from_directory(ROOT / "static", "index.html")

    @app.get("/backtest")
    def backtest_page():
        return send_from_directory(ROOT / "static", "backtest.html")

    @app.get("/research")
    def research_page():
        return send_from_directory(ROOT / "static", "research.html")

    @app.get("/api/state")
    def state():
        snapshot = service.snapshot()
        if backtests is not None:
            # This reads only saved local state; page polling never calls Greeks.live.
            try:
                saved = backtests.snapshot()
                configuration = saved["configuration"]
                capabilities = saved["capabilities"]
                count = len(saved["runs"])
                if not configuration["configured"]:
                    label = "回测配置未齐备 · 公共行情不受影响"
                elif capabilities["status"] == "ready":
                    label = "Greeks.live 会话与能力已确认"
                elif capabilities["status"] == "checking":
                    label = "正在检查 Greeks.live 会话与能力"
                elif capabilities["status"] == "failed":
                    label = "Greeks.live 检查失败 · 见回测页原因"
                else:
                    label = "回测适配器已接入 · 会话尚未验证"
                if count:
                    label += f" · 已保存 {count} 次运行，结果与限制见回测页"
                else:
                    label += " · 尚无已保存回测结果"
            except Exception as error:
                logging.error("backtest integration status: %s", safe_traceback(error))
                label = "回测本地状态读取失败 · 公共行情仍独立运行"
            snapshot.setdefault("integrations", {})["backtest"] = label
        return jsonify(snapshot)

    @app.get("/api/backtests")
    def backtest_state():
        if backtests is None:
            return jsonify(error="回测后端未启用"), 503
        try:
            return jsonify(backtests.snapshot())
        except Exception as error:
            logging.error("backtest state: %s", safe_traceback(error))
            return jsonify(error="无法读取本地回测状态；详情已脱敏记录"), 500

    def validate_backtest_post():
        if backtests is None:
            return jsonify(error="回测后端未启用"), 503
        if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return jsonify(error="拒绝跨站回测请求"), 403
        origin = request.headers.get("Origin")
        if origin is not None and origin != request.host_url.rstrip("/"):
            return jsonify(error="回测请求必须来自当前本地页面"), 403
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not token.isascii() or not hmac.compare_digest(token, backtests.csrf_token):
            return jsonify(error="页面验证已失效，请刷新回测页面后再操作"), 403
        if not request.is_json or not isinstance(request.get_json(silent=True), dict):
            return jsonify(error="回测请求必须为 JSON 对象"), 400
        return None

    @app.post("/api/backtests/check-connection")
    def check_backtest_connection():
        invalid = validate_backtest_post()
        if invalid is not None:
            return invalid
        if request.get_json(silent=True):
            return jsonify(error="连接检查不接受额外参数"), 400
        try:
            backtests.check_connection()
            return jsonify(status="checking"), 200
        except BacktestError as error:
            return jsonify(error=str(error)), 409
        except Exception as error:
            logging.error("backtest connection request: %s", safe_traceback(error))
            return jsonify(error="无法启动连接检查；详情已脱敏记录"), 500

    @app.post("/api/backtests")
    def submit_backtest():
        invalid = validate_backtest_post()
        if invalid is not None:
            return invalid
        payload = request.get_json(silent=True)
        if payload != {"experiment_id": EXPERIMENT_ID}:
            return jsonify(error="仅支持页面列出的固定 S2 实验，不能覆盖参数"), 400
        try:
            run_id = backtests.submit(payload["experiment_id"])
            return jsonify(run_id=run_id), 202
        except BacktestError as error:
            return jsonify(error=str(error)), 409
        except Exception as error:
            logging.error("backtest submission request: %s", safe_traceback(error))
            return jsonify(error="提交结果未确认；请查看已保存记录，勿重复提交"), 500

    @app.post("/api/backtests/<run_id>/resume")
    def resume_backtest(run_id):
        invalid = validate_backtest_post()
        if invalid is not None:
            return invalid
        if request.get_json():
            return jsonify(error="继续获取不接受额外参数"), 400
        try:
            return jsonify(run_id=backtests.resume(run_id)), 202
        except BacktestError as error:
            return jsonify(error=str(error)), 409

    @app.post("/api/backtests/<run_id>/retry")
    def retry_backtest(run_id):
        invalid = validate_backtest_post()
        if invalid is not None:
            return invalid
        payload = request.get_json()
        if set(payload) != {"idempotency_key"}:
            return jsonify(error="新尝试需要唯一操作标识"), 400
        try:
            if backtests.get_run(run_id).get("experiment_id") != EXPERIMENT_ID:
                return jsonify(error="研究实验的创建预算由研究任务管理；不能从回测页绕过"), 409
            return jsonify(backtests.retry(run_id, logical_id=payload["idempotency_key"])), 202
        except BacktestError as error:
            return jsonify(error=str(error)), 409

    @app.get("/api/research/config")
    def research_config():
        if research is None:
            return jsonify(csrf_token=workbench_token, availability={"ready":False,"reason":"研究后端不可用；策略与历史仍可查看"}, configuration={"limits":{"model_calls":6,"backtest_creations":2}})
        return jsonify(research.config_snapshot())

    @app.get("/api/workspace")
    def workspace_state():
        try:
            return jsonify(workspace_snapshot(research))
        except Exception as error:
            logging.error("workspace state: %s", safe_traceback(error))
            return jsonify(error="无法读取本地业务状态；详情已脱敏记录"), 500

    @app.get("/api/research/runs")
    def research_runs():
        if research is None:
            return jsonify(error="研究后端未启用"), 503
        return jsonify(research.list_runs())

    @app.get("/api/research/runs/<research_id>")
    def research_detail(research_id):
        if research is None:
            return jsonify(error="研究后端未启用"), 503
        try:
            return jsonify(research.detail(research_id))
        except ResearchError as error:
            return jsonify(error=str(error)), 404

    def validate_research_post():
        if research is None:
            return jsonify(error="研究后端未启用"), 503
        origin = request.headers.get("Origin")
        token = request.headers.get("X-CSRF-Token", "")
        if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site" or (origin is not None and origin != request.host_url.rstrip("/")):
            return jsonify(error="拒绝跨站研究操作"), 403
        if not token or not token.isascii() or not hmac.compare_digest(token, research.csrf_token):
            return jsonify(error="页面验证已失效，请刷新研究页"), 403
        if not request.is_json or not isinstance(request.get_json(silent=True), dict):
            return jsonify(error="需要 JSON 对象"), 400

    @app.post("/api/research/start")
    def start_research():
        invalid = validate_research_post()
        if invalid is not None:
            return invalid
        if set(request.get_json()) != {"question", "approved", "idempotency_key"}:
            return jsonify(error="不允许覆盖模型、预算、权限或配置"), 400
        return jsonify(error="S4A 新研究须在策略详情选择版本、目的并批准；旧研究历史和显式恢复仍可用", next_url="/"), 409

    @app.post("/api/research/runs/<research_id>/<operation>")
    def operate_research(research_id, operation):
        invalid = validate_research_post()
        if invalid is not None:
            return invalid
        if request.get_json() or operation not in {"stop", "resume"}:
            return jsonify(error="不支持该操作或额外参数"), 400
        try:
            if operation == "stop":
                research.stop_task(research_id)
            else:
                if research.detail(research_id).get('strategy_context'):
                    if strategies is None:
                        raise ResearchError('策略归属后端不可用，不能恢复此任务')
                    strategies.ensure_research_binding(research_id)
                research.resume(research_id)
            return jsonify(research_id=research_id), 202
        except (ResearchError, StrategyError) as error:
            return jsonify(error=str(error)), 409

    @app.get("/api/strategies")
    def strategy_list():
        if strategies is None:
            return jsonify(error="策略存储未启用"), 503
        try:
            data = strategies.snapshot()
            data['csrf_token'] = workbench_token
            data['research_availability'] = research.availability if research else {"ready":False,"reason":"研究后端不可用"}
            return jsonify(data)
        except (StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.get("/api/strategies/<strategy_id>")
    def strategy_detail(strategy_id):
        if strategies is None:
            return jsonify(error="策略存储未启用"), 503
        try:
            return jsonify(strategies.detail(strategy_id))
        except (StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 404

    def validate_strategy_post():
        if strategies is None:
            return jsonify(error="策略存储未启用"), 503
        origin = request.headers.get('Origin')
        token = request.headers.get('X-CSRF-Token', '')
        if request.headers.get('Sec-Fetch-Site', '').lower() == 'cross-site' or (origin is not None and origin != request.host_url.rstrip('/')):
            return jsonify(error="拒绝跨站策略操作"), 403
        if not token or not token.isascii() or not hmac.compare_digest(token, workbench_token):
            return jsonify(error="页面验证已失效，请刷新后操作"), 403
        if not request.is_json or not isinstance(request.get_json(silent=True), dict):
            return jsonify(error="需要 JSON 对象"), 400

    @app.post('/api/strategies')
    def create_strategy():
        invalid = validate_strategy_post()
        if invalid is not None:
            return invalid
        try:
            return jsonify(strategies.create(request.get_json())), 201
        except (StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.get('/api/strategy-templates')
    def strategy_templates():
        return jsonify(templates=templates())

    @app.get('/api/strategies/<strategy_id>/versions/<version_id>/spec.md')
    def export_strategy_spec(strategy_id, version_id):
        if strategies is None:
            return jsonify(error='策略存储未启用'), 503
        try:
            return Response(strategies.export_spec(strategy_id, version_id), mimetype='text/markdown',
                            headers={'Content-Disposition':'attachment; filename="strategy_spec.md"'})
        except (StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.get('/api/strategy-runs')
    def strategy_runs():
        if runtime is None:
            return jsonify(runs=[], availability={'ready':False,'reason':'Testnet 运行服务未启用'})
        return jsonify(runtime.snapshot(request.args.get('strategy_id')))

    @app.get('/api/strategy-runs/<run_id>')
    def strategy_run_detail(run_id):
        if runtime is None or run_id not in runtime.views:
            return jsonify(error='运行不存在'), 404
        return jsonify(runtime.views[run_id])

    @app.post('/api/strategy-runs')
    def start_strategy_run():
        invalid = validate_strategy_post()
        if invalid is not None:
            return invalid
        if runtime is None:
            return jsonify(error='Testnet 运行服务未启用'), 503
        try:
            payload = request.get_json()
            if set(payload) != {'strategy_id','version_id','approved','idempotency_key'}:
                raise RuntimeErrorState('Testnet 启动参数不完整或包含未支持的权限配置')
            return jsonify(runtime.create(payload)), 201
        except (RuntimeErrorState, TestnetError, StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.post('/api/strategy-runs/<run_id>/<operation>')
    def operate_strategy_run(run_id, operation):
        invalid = validate_strategy_post()
        if invalid is not None:
            return invalid
        if runtime is None:
            return jsonify(error='Testnet 运行服务未启用'), 503
        try:
            if request.get_json():
                raise RuntimeErrorState('运行操作不接受额外参数')
            return jsonify(runtime.operate(run_id, operation))
        except (RuntimeErrorState, TestnetError, StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.post('/api/strategies/<strategy_id>/versions/<version_id>')
    @app.post('/api/strategies/<strategy_id>/versions/<version_id>/<operation>')
    def operate_version(strategy_id, version_id, operation='edit'):
        invalid = validate_strategy_post()
        if invalid is not None:
            return invalid
        try:
            payload = request.get_json()
            if operation == 'edit':
                result = strategies.update_version(strategy_id, version_id, payload)
            elif operation == 'freeze' and not payload:
                result = strategies.freeze_version(strategy_id, version_id)
            elif operation == 'revisions':
                result = strategies.revise(strategy_id, version_id, payload)
            elif operation == 'confirm':
                result = strategies.confirm_onboarding(strategy_id, version_id, payload)
            else:
                return jsonify(error="不支持该版本操作"), 400
            return jsonify(result)
        except (StrategyError, ValueError) as error:
            return jsonify(error=str(error)), 409

    @app.post('/api/strategies/<strategy_id>/<operation>')
    def operate_strategy(strategy_id, operation):
        invalid = validate_strategy_post()
        if invalid is not None:
            return invalid
        payload = request.get_json()
        version_id = payload.pop('version_id', None)
        try:
            if operation == 'metadata':
                return jsonify(strategies.update_metadata(strategy_id, payload))
            if operation == 'decisions':
                return jsonify(strategies.add_decision(strategy_id, version_id, payload))
            if operation == 'history-links':
                return jsonify(strategies.link_history(strategy_id, version_id, payload))
            if operation == 'fee-scenarios':
                return jsonify(strategies.fee_scenario(strategy_id, version_id, payload))
            if operation == 'research':
                if research is None or not research.availability['ready']:
                    raise ResearchError(research.availability['reason'] if research else '研究后端不可用')
                prepared = strategies.prepare_research(strategy_id, version_id, payload)
                binding_id = prepared['binding_id']
                try:
                    rid = research.start(prepared['question'], payload.get('approved'), payload.get('idempotency_key'),
                        context=prepared['context'], defer_launch=True)
                    strategies.bind_research(binding_id, rid)
                    if research.detail(rid)['status'] == 'preparing' and research.active_id != rid:
                        research.launch_prepared(rid)
                except (ResearchError, StrategyError, ValueError) as error:
                    strategies.mark_start_failed(binding_id, str(error))
                    raise
                return jsonify(research_id=rid, binding_id=binding_id, validation_id=prepared.get('validation_id')), 202
            return jsonify(error="不支持该策略操作"), 400
        except (ResearchError, StrategyError, BacktestError, ValueError) as error:
            return jsonify(error=str(error)), 409

    return app


def main():
    parser = argparse.ArgumentParser(description="Optimatrix：策略研究与明确授权的 Testnet 执行（仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="本机端口，默认 8765")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须在 1024–65535 之间")
    (ROOT / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / "logs" / "app.log", maxBytes=1_000_000, backupCount=2)
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # One process per project: a second launch must not alter an active run's history.
    (ROOT / "local").mkdir(exist_ok=True, mode=0o700)
    lock_file = (ROOT / "local" / "app.lock").open("a")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        print("本项目已有服务运行。请打开现有页面，或先在原终端停止；不要重复启动。")
        return 1
    service = MarketService(integrations=integrations())
    try:
        backtests = BacktestService(ROOT)  # Local configuration/history only; no automatic remote calls.
    except OSError as error:
        service.client.close()
        logging.error("backtest initialization: %s", safe_traceback(error))
        print("无法初始化本地回测记录目录，请检查 local/backtests 的访问权限。")
        lock_file.close()
        return 1
    try:
        research = ResearchService(ROOT, backtests, cli_status=service.snapshot().get("integrations", {}).get("codex", {}))
    except (OSError, ValueError, KeyError, TypeError) as error:
        logging.error("research initialization: %s", safe_traceback(error))
        research = None
        print("研究配置或本地记录不可用；行情和回测继续独立运行。", flush=True)
    strategies = StrategyService(ROOT, backtests, research)
    runtime = StrategyRuntimeService(ROOT, strategies, notifier=notify_desktop)
    signal_studies = SignalStudyService(ROOT, strategies)
    try:
        # Bind before collecting: a second launch on this port cannot create another collector.
        server = create_server(create_app(service, backtests, research, strategies, runtime, signal_studies), host="127.0.0.1", port=args.port, threads=4)
    except OSError:
        service.client.close()
        backtests.stop()
        runtime.stop()
        signal_studies.stop()
        print(f"无法监听 127.0.0.1:{args.port}。请检查端口是否已被使用；不要重复启动。")
        lock_file.close()
        return 1
    def handle_stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_stop)
    service.start()
    runtime.start()  # Idle until an explicit, persisted Testnet authorization; restart never resumes trading.
    signal_studies.start()  # Explicit saved authorization; public observation only, no order capability.
    print(f"工作台：http://127.0.0.1:{args.port}  |  按 Ctrl+C 停止", flush=True)
    print(f"公共行情只读：http://127.0.0.1:{args.port}/market", flush=True)
    print(f"固定回测页面：http://127.0.0.1:{args.port}/backtest  |  不会自动提交回测", flush=True)
    print(f"策略研究：http://127.0.0.1:{args.port}/strategies  |  策略详情批准预算后才运行", flush=True)
    print("Testnet：独立账户执行；主网仅公共行情。已有运行重启后须先对账恢复。", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        print("正在停止本地服务、行情采集与回测工作线程…", flush=True)
    finally:
        server.close()
        if research is not None:
            research.stop()
        runtime.stop()
        signal_studies.stop()
        backtests.stop()
        service.stop()
        lock_file.close()
        print("本地服务已停止；已保存的回测记录会在下次启动时读取。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

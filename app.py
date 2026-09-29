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
import subprocess
import time

from flask import Flask, jsonify, send_from_directory, request, abort
from waitress import create_server

from backtest import BacktestError, BacktestService, EXPERIMENT_ID
from market import MarketService, iso, safe_traceback

ROOT = Path(__file__).resolve().parent


def codex_status():
    status = {"installed": False, "version": "未检测到", "login_status": "未检查", "checked_at": iso()}
    executable = shutil.which("codex")
    if not executable:
        return status
    status["installed"] = True
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=3)
        match = re.search(r"codex-cli ([0-9A-Za-z.+-]+)", version.stdout)
        status["version"] = match.group(1) if match else "版本未识别"
        result = subprocess.run([executable, "login", "status"], capture_output=True, text=True, timeout=3)
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
            "agent": "未接入 · 本轮未运行模型任务 / 未接 OpenAI API", "codex": codex_status()}


def create_app(service, backtests=None):
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")

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
        return send_from_directory(ROOT / "static", "index.html")

    @app.get("/backtest")
    def backtest_page():
        return send_from_directory(ROOT / "static", "backtest.html")

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

    return app


def main():
    parser = argparse.ArgumentParser(description="Optimatrix S2：只读公共行情与 Greeks.live 固定回测（仅本机）")
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
        # Bind before collecting: a second launch on this port cannot create another collector.
        server = create_server(create_app(service, backtests), host="127.0.0.1", port=args.port, threads=4)
    except OSError:
        service.client.close()
        backtests.stop()
        print(f"无法监听 127.0.0.1:{args.port}。请检查端口是否已被使用；不要重复启动。")
        lock_file.close()
        return 1
    def handle_stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_stop)
    service.start()
    print(f"公共行情只读：http://127.0.0.1:{args.port}  |  按 Ctrl+C 停止", flush=True)
    print(f"固定回测页面：http://127.0.0.1:{args.port}/backtest  |  不会自动提交回测", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        print("正在停止本地服务、行情采集与回测工作线程…", flush=True)
    finally:
        server.close()
        backtests.stop()
        service.stop()
        lock_file.close()
        print("本地服务已停止；已保存的回测记录会在下次启动时读取。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

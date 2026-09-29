"""One local process, one collector, read-only HTTP endpoints."""
import argparse
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

from market import MarketService, iso

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


def create_app(service):
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

    @app.get("/api/state")
    def state():
        return jsonify(service.snapshot())

    return app


def main():
    parser = argparse.ArgumentParser(description="Optimatrix S1：Deribit 只读公共行情（仅本机）")
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
    service = MarketService(integrations=integrations())
    try:
        # Bind before collecting: a second launch on this port cannot create another collector.
        server = create_server(create_app(service), host="127.0.0.1", port=args.port, threads=4)
    except OSError:
        service.client.close()
        print(f"无法监听 127.0.0.1:{args.port}。请检查端口是否已被使用；不要重复启动。")
        return 1
    def handle_stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_stop)
    service.start()
    print(f"公共行情只读：http://127.0.0.1:{args.port}  |  按 Ctrl+C 停止", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        print("正在停止本地服务与行情采集…", flush=True)
    finally:
        server.close()
        service.stop()
        print("本地服务与行情采集已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

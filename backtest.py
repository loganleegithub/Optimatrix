"""Small adapter for the observed Greeks.live web backtest protocol, not a pricing engine."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import quote, urlparse
import uuid

import requests

from market import iso, safe_traceback
from btc_accounting import analyze_report

BASE_URL = "https://backtest.greeks.live"
EXPERIMENT_ID = "S2_BTC_LONG_CALL_V1"
EXPERIMENT = {
    "id": EXPERIMENT_ID,
    "title": "单次 BTC 看涨期权买方 · 模型估值连通实验",
    "description": "2026-05-04 周一 09:00 UTC 买入 7D、0.5 Delta Call，下一有曲面数据日平仓；窗口止于 05-05，不对冲、不优化。",
    "request": {"name": "Optimatrix S2 BTC long call V1", "asset": "BTC", "start_date": "2026-05-04",
                "end_date": "2026-05-05", "session_bucket": "09:00:00", "entry_weekdays": [0],
                "mode": "reopen", "hedge_mode": "none", "hedge_delta_mode": "bs", "skew_beta": 1.5,
                "option_transaction_cost_bp": 1, "hedge_transaction_cost_bp": 0, "numeraire": "BTC",
                "save_detail_csv": True, "calculate_annual_return": False, "annual_return_principal": 0.2,
                "legs": [{"side": "long", "option_type": "call", "delta": 0.5, "expiry": 7, "close_dte": 0, "quantity": 0.01}],
                "indicators": [], "signal": None, "exposure_band": None, "selected_chart_columns": []},
    "assumptions": ["SABR/WV4 模型曲面价格，不是 bid/ask 成交回放。", "quantity=0.01 是模型标的名义数量 0.01 BTC，不是权利金；option_value 已包含数量，不能再乘一次。",
                    "期权成本固定为每腿每次开/平仓标的名义额 1 bp，仅为实验假设，不是账户费率。",
                    "0.2 BTC 仅为假设初始资金；无账户连接。不开启服务年化收益计算。",
                    "本实验只允许一次远端提交；再次点击返回已保存任务。提交结果不明时不自动重发。"],
}
FACTS = ["已观察官方网页 POST /api/backtests，随后轮询任务并读取 report-data。",
         "服务网页区分 BTC 反向与 USD 线性；本实验明确请求 BTC。",
         "服务使用 SABR/WV4 曲面和期限插值，属于模型估值。",
         "真实报告说明 BTC 模型价值按每个估值时点的 USD 模型价值 / 该时点 forward 换算。",
         "真实报告说明反向产品成本为 quantity × (bp / 10000) BTC；已从 option_pnl 扣除，另列正费用。",
         "官方网页说明报告保留 1 天；本项目保存请求、原始结果和 CSV 到本地。"]
UNKNOWNS = ["本次是合成行权价和到期日的模型期权，未建立与实际挂牌合约的对应关系。",
            "没有 bid/ask、深度、滑点或真实账户费率；模型账本不能证明可成交收益。",
            "报告注明 1 分钟曲面源，本任务每日 09:00 UTC 估值；未验证全部历史覆盖质量，不具备 H1 微观数据证明。"]
RUNNING = {"queued", "submitting", "running", "fetching"}


def load_config(root):
    """Consume only the two named fields. No env evaluation, interpolation or global changes."""
    result = {}
    try:
        with (Path(root) / ".env").open() as source:
            for line in source:
                key, separator, value = line.partition("=")
                key = key.strip()
                if separator and key in {"GREEKS_LIVE_AUTH_TOKEN", "GREEKS_LIVE_DATA_API_KEY"}:
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    if value and len(value) <= 16384 and not any(c in value for c in "\r\n\x00"):
                        result[key] = value
    except FileNotFoundError:
        pass
    return result


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


class BacktestError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class GreeksClient:
    def __init__(self, token, base_url=BASE_URL, timeout_seconds=45):
        parsed = urlparse(base_url)
        if base_url != BASE_URL and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("Unsupported service origin")
        self.base_url = base_url
        self.timeout = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Authorization": token, "Accept": "application/json", "User-Agent": "Optimatrix-S2/1.0"})

    def close(self):
        self.session.close()

    def request(self, method, path, payload=None, save_to=None, binary=False):
        if not re.fullmatch(r"/api/(metadata|account|backtests(?:/[A-Za-z0-9_-]+(?:/report-data|/artifact/[A-Za-z0-9_.%+-]+)?)?)", path):
            raise BacktestError("拒绝未获支持的服务路径")
        if method not in {"GET", "POST"} or (method == "POST" and path != "/api/backtests"):
            raise BacktestError("拒绝未获支持的服务操作")
        try:
            response = self.session.request(method, self.base_url + path, json=payload,
                                            timeout=(min(3.05, self.timeout), self.timeout), allow_redirects=False)
        except requests.RequestException:
            raise BacktestError("Greeks.live 连接失败或超时；未自动重试", uncertain=method == "POST") from None
        if save_to is not None:
            # Account response can contain API keys; it is never persisted.
            if path == "/api/account":
                raise BacktestError("账户响应不得保存")
            atomic_write(save_to, response.content)
        if not 200 <= response.status_code < 300:
            labels = {401: "回测认证失效或不适用", 403: "回测权限不足", 429: "回测额度不足或服务限频", 402: "服务要求额外付费；已停止"}
            label = labels.get(response.status_code, "服务请求失败")
            raise BacktestError(f"{label}（HTTP {response.status_code}）", uncertain=method == "POST" and response.status_code >= 500)
        if binary:
            return response.content
        try:
            data = response.json()
        except ValueError:
            raise BacktestError("服务返回不可解析的 JSON", uncertain=method == "POST") from None
        if not isinstance(data, dict):
            raise BacktestError("服务响应结构未获支持", uncertain=method == "POST")
        return data


class BacktestService:
    def __init__(self, root, client_factory=None, poll_seconds=2):
        self.root = Path(root)
        self.storage = self.root / "local" / "backtests"
        self.storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.client_factory = client_factory or GreeksClient
        self.poll_seconds = poll_seconds
        self.csrf_token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.active = False
        self.runs = []
        self.storage_error = None
        self.capabilities = {"status": "unchecked", "checked_at": None, "reason": "尚未验证回测会话", "facts": FACTS, "unknowns": UNKNOWNS, "coverage": None}
        for path in sorted(self.storage.glob("*/run.json")):
            try:
                record = json.loads(path.read_text())
                if record["status"] in RUNNING:
                    record.update(status="interrupted", error="程序已停止；远端状态尚未重新核对。不会重复提交。")
                    save_json(path, record)
                self.runs.append(record)
            except (OSError, ValueError, KeyError, TypeError):
                self.storage_error = "部分本地历史文件无法读取；请检查 local/backtests，未覆盖这些文件。"

    def configuration(self):
        try:
            values = load_config(self.root)
        except OSError:
            return {"configured": False, "reason": "无法读取本地 Greeks.live 配置"}
        present = bool(values.get("GREEKS_LIVE_AUTH_TOKEN"))
        return {"configured": present, "reason": "回测会话字段已填写，仍需检查服务能力" if present else
                ("已配置 CSV Data API Key；它不是已验证的回测会话。缺少 GREEKS_LIVE_AUTH_TOKEN。" if values.get("GREEKS_LIVE_DATA_API_KEY") else "缺少 .env 中的 GREEKS_LIVE_AUTH_TOKEN；公共行情不受影响")}

    def snapshot(self):
        with self.lock:
            return {"server_time": iso(), "csrf_token": self.csrf_token, "configuration": self.configuration(),
                    "capabilities": copy.deepcopy(self.capabilities), "experiment": copy.deepcopy(EXPERIMENT),
                    "runs": copy.deepcopy(list(reversed(self.runs))), "storage_error": self.storage_error}

    def _client(self):
        config = load_config(self.root)
        token = config.get("GREEKS_LIVE_AUTH_TOKEN")
        if not token:
            raise BacktestError(self.configuration()["reason"])
        return self.client_factory(token)

    def _launch(self, target, *args):
        if self.active:
            raise BacktestError("已有检查或回测进行中")
        self.active = True
        def run():
            try:
                target(*args)
            finally:
                with self.lock:
                    self.active = False
        self.worker = threading.Thread(target=run, name="greeks-backtest", daemon=True)
        self.worker.start()

    def check_connection(self):
        with self.lock:
            if self.active:
                raise BacktestError("已有检查或回测进行中")
            self.capabilities.update(status="checking", reason="正在读取认证后的元数据与配额")
            self._launch(self._check)

    def _verify(self, client):
        metadata = client.request("GET", "/api/metadata", save_to=self.storage / "metadata.raw.json")
        asset_status = metadata.get("asset_status", {}).get("BTC", {})
        start = asset_status.get("available_start_date") or metadata.get("available_start_date") or metadata.get("earliest_date")
        end = asset_status.get("available_end_date") or metadata.get("available_end_date")
        if not all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in [start, end]):
            raise BacktestError("未取得可验证的 BTC 历史覆盖日期")
        req = EXPERIMENT["request"]
        if not start <= req["start_date"] <= req["end_date"] <= end:
            raise BacktestError("固定实验日期不在服务当前可用范围内；不会自动换参数")
        account = client.request("GET", "/api/account")
        quotas = account.get("quotas", {})
        limit, used = quotas.get("backtests_per_hour"), quotas.get("backtests_used")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (limit, used)) or limit <= used:
            raise BacktestError("未确认有可用的回测额度；未提交任务")
        with self.lock:
            self.capabilities.update(status="ready", checked_at=iso(), reason="回测会话、日期范围及当前可用额度已验证",
                                     coverage={"start_date": start, "end_date": end},
                                     facts=FACTS + [f"认证响应确认 BTC 日期范围：{start} 至 {end}。", f"当前服务响应回测配额：已用 {used} / 每小时 {limit}；不代表付费购买。"])
            save_json(self.storage / "capabilities.json", self.capabilities)

    def _check(self):
        client = None
        try:
            client = self._client()
            self._verify(client)
        except Exception as error:
            with self.lock:
                self.capabilities.update(status="failed", checked_at=iso(), reason=str(error) if isinstance(error, BacktestError) else "能力检查内部异常")
            if not isinstance(error, BacktestError):
                logging.error("backtest check: %s", safe_traceback(error))
        finally:
            if client:
                client.close()

    def _save(self, record):
        save_json(self.storage / record["run_id"] / "run.json", record)

    def submit(self, experiment_id):
        if experiment_id != EXPERIMENT_ID:
            raise BacktestError("仅支持页面列出的固定 S2 实验")
        with self.lock:
            existing = next((r for r in self.runs if r.get("submitted_at") or r["status"] in RUNNING), None)
            if existing:
                return existing["run_id"]
            if self.storage_error:
                raise BacktestError("历史记录存在读取错误；核对已有提交前不能创建新任务")
            if self.active:
                raise BacktestError("已有检查或回测进行中")
            if not self.configuration()["configured"] or self.capabilities["status"] != "ready":
                raise BacktestError("请先配置回测会话并通过服务能力检查")
            record = {"run_id": uuid.uuid4().hex, "experiment_id": EXPERIMENT_ID, "created_at": iso(),
                      "submitted_at": None, "completed_at": None, "service_task_id": None, "status": "queued",
                      "error": None, "request": copy.deepcopy(EXPERIMENT["request"]), "analysis": None}
            self._save(record)
            save_json(self.storage / record["run_id"] / "request.json", {"method": "POST", "url": BASE_URL + "/api/backtests", "body": record["request"], "authentication": "Authorization header intentionally excluded"})
            self.runs.append(record)
            self._launch(self._execute, record)
            return record["run_id"]

    def _execute(self, record):
        client = None
        directory = self.storage / record["run_id"]
        try:
            client = self._client()
            self._verify(client)
            if self.stop_event.is_set():
                raise BacktestError("本地服务已停止；未提交远端任务")
            with self.lock:
                record.update(status="submitting", submitted_at=iso())
                self._save(record)  # Durable before the only POST; crash cannot cause resubmission.
            task = client.request("POST", "/api/backtests", record["request"], save_to=directory / "submit.raw.json")
            task_id = task.get("id")
            if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                raise BacktestError("远端未返回可验证的任务标识；不会重复提交", uncertain=True)
            with self.lock:
                record.update(service_task_id=task_id, status="running")
                self._save(record)
            deadline = time.monotonic() + 600
            while task.get("status") not in {"completed", "failed"}:
                if self.stop_event.wait(self.poll_seconds):
                    raise BacktestError("本地服务已停止；远端任务状态未确认")
                if time.monotonic() > deadline:
                    raise BacktestError("等待远端结果超过 10 分钟；未重复提交")
                task = client.request("GET", "/api/backtests/" + task_id, save_to=directory / "status.raw.json")
                if task.get("id") != task_id:
                    raise BacktestError("服务返回的任务标识不一致；停止读取结果")
            if task["status"] == "failed":
                with self.lock:
                    record.update(status="failed", error="Greeks.live 返回任务失败；原始错误仅保存在本地", completed_at=iso())
                    self._save(record)
                return
            with self.lock:
                record.update(status="fetching")
                self._save(record)
            report = client.request("GET", f"/api/backtests/{task_id}/report-data", save_to=directory / "report.raw.json")
            for response in (task, report):
                if "request" in response and response["request"] != record["request"]:
                    raise BacktestError("服务结果中的请求与本地原始参数不一致；不能计量")
            merged = {**task, **report}
            artifact_files = {}
            for field, local_name in [("csv", "details.csv"), ("daily_csv", "daily.csv"), ("report", "report.txt")]:
                name = merged.get("artifacts", {}).get(field)
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    content = client.request("GET", f"/api/backtests/{task_id}/artifact/{quote(name, safe='')}", binary=True)
                    atomic_write(directory / local_name, content)
                    artifact_files[field] = directory / local_name
            analysis = analyze_report(merged, artifact_files)
            with self.lock:
                status = ("result_incomplete" if analysis.get("reported_pnl") is None else
                          "completed_with_gaps" if analysis["gaps"] else "completed")
                record.update(status=status, analysis=analysis, completed_at=iso())
                self._save(record)
        except Exception as error:
            with self.lock:
                record.update(status="submission_unknown" if isinstance(error, BacktestError) and error.uncertain else
                              ("retrieval_failed" if record.get("service_task_id") else "failed"),
                              error=str(error) if isinstance(error, BacktestError) else "回测内部异常；详情已脱敏记录", completed_at=iso())
                self._save(record)
            if not isinstance(error, BacktestError):
                logging.error("backtest worker: %s", safe_traceback(error))
        finally:
            if client:
                client.close()

    def stop(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)

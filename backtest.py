"""Small adapter for the observed Greeks.live web backtest protocol, not a pricing engine."""
from __future__ import annotations

import copy
from datetime import date, time as daytime
import hashlib
import math
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
from configuration import ConfigurationError, GREEKS_FIELDS, read_secrets

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
PARAMETER_FIELDS = {"start_date", "end_date", "session_bucket", "entry_weekdays", "option_type",
                    "delta", "expiry", "quantity", "option_transaction_cost_bp"}
FINISHED = {"completed", "completed_with_gaps"}


def validate_experiment(params, coverage=None):
    """Narrow, explicit S3 policy; model output never becomes a service payload."""
    if not isinstance(params, dict) or set(params) != PARAMETER_FIELDS:
        raise BacktestError("实验必须提供全部九个允许字段；其他字段一律拒绝")
    try:
        dates = [date.fromisoformat(params[field]) for field in ("start_date", "end_date")]
        if any(params[key] != value.isoformat() for key, value in zip(("start_date", "end_date"), dates)):
            raise ValueError
        session = daytime.fromisoformat(params["session_bucket"])
        if session.tzinfo is not None or session.isoformat() != params["session_bucket"]:
            raise ValueError
    except (ValueError, TypeError):
        raise BacktestError("日期须为 YYYY-MM-DD；UTC 估值时段须为 HH:MM:SS") from None
    if not 1 <= (dates[1] - dates[0]).days <= 31:
        raise BacktestError("本阶段实验窗口须为 1 至 31 天")
    if coverage and not coverage["start_date"] <= params["start_date"] <= params["end_date"] <= coverage["end_date"]:
        raise BacktestError("实验日期不在当前已核实 BTC 覆盖范围内")
    weekdays = params["entry_weekdays"]
    if (not isinstance(weekdays, list) or not weekdays or len(weekdays) > 7
            or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays)
            or len(set(weekdays)) != len(weekdays)):
        raise BacktestError("入场星期须为不重复的 0 至 6 整数列表")
    if not isinstance(params["option_type"], str) or params["option_type"] not in {"call", "put"}:
        raise BacktestError("本阶段只支持单腿 long call 或 long put")
    for field, low, high in (("delta", .01, .99), ("quantity", .01, 1), ("option_transaction_cost_bp", 0, 100)):
        value = params[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise BacktestError(f"字段 {field} 必须为 {low} 至 {high} 的有限数字")
    if type(params["expiry"]) is not int or not 2 <= params["expiry"] <= 90:
        raise BacktestError("本阶段目标期限 expiry 须为 2 至 90 天整数")
    request = copy.deepcopy(EXPERIMENT["request"])
    request.update({key: params[key] for key in ("start_date", "end_date", "session_bucket", "option_transaction_cost_bp")})
    request["entry_weekdays"] = sorted(weekdays)
    request["legs"] = [{"side": "long", "option_type": params["option_type"], "delta": params["delta"],
                        "expiry": params["expiry"], "close_dte": 0, "quantity": params["quantity"]}]
    request["name"] = "Optimatrix S3 BTC buyer " + request_fingerprint(request)[:12]
    return request


def request_fingerprint(request):
    """Names are labels, never an excuse to spend a second remote creation."""
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if type(value) is float and value.is_integer():
            return int(value)
        return value
    material = normalize({key: value for key, value in request.items() if key != "name"})
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def parameters_from_request(request):
    leg = request["legs"][0]
    return {**{key: request[key] for key in ("start_date", "end_date", "session_bucket", "entry_weekdays", "option_transaction_cost_bp")},
            **{key: leg[key] for key in ("option_type", "delta", "expiry", "quantity")}}



def load_config(root):
    """Consume only the two named fields. No env evaluation, interpolation or global changes."""
    return read_secrets(root, GREEKS_FIELDS)


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
    def __init__(self, message, uncertain=False, unavailable=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.unavailable = unavailable


class GreeksClient:
    def __init__(self, token, base_url=BASE_URL, timeout_seconds=45):
        parsed = urlparse(base_url)
        if base_url != BASE_URL and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("Unsupported service origin")
        self.base_url = base_url
        self.timeout = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Authorization": token, "Accept": "application/json", "User-Agent": "Optimatrix-S3/1.0"})

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
            # A status code alone does not prove that a POST had no side effect.
            unavailable = method == "GET" and response.status_code in {404, 410} and bool(re.fullmatch(r"/api/backtests/[A-Za-z0-9_-]+(?:/report-data)?", path))
            raise BacktestError(f"{label}（HTTP {response.status_code}）", uncertain=method == "POST", unavailable=unavailable)
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
        self.pause_events = {}
        self.runs = []
        self.storage_error = None
        self.capabilities = {"status": "unchecked", "checked_at": None, "reason": "尚未验证回测会话", "facts": FACTS, "unknowns": UNKNOWNS, "coverage": None}
        for path in sorted(self.storage.glob("*/run.json")):
            try:
                record = json.loads(path.read_text())
                if (not isinstance(record, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(record.get("run_id", "")))
                        or record["run_id"] != path.parent.name or not isinstance(record.get("request"), dict)
                        or not isinstance(record.get("status"), str)):
                    raise ValueError("invalid local run identity")
                request_fingerprint(record["request"])
                if record.get("service_task_id") is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(record["service_task_id"])):
                    raise ValueError("invalid remote task identity")
                if record["status"] in RUNNING | {"interrupted"}:
                    if record.get("service_task_id"):
                        record.update(status="paused", error="后端已停止；可显式继续获取结果，仅 GET，不重复提交。")
                    elif record.get("submitted_at"):
                        record.update(status="submission_unknown", error="后端在提交过程中停止；无法确认是否创建，禁止重发。")
                    else:
                        record.update(status="not_submitted", confirmed_not_created=True,
                                      error="后端在发送前停止；可显式建立关联的新尝试。")
                    save_json(path, record)
                self.runs.append(record)
            except (OSError, ValueError, KeyError, TypeError):
                self.storage_error = "部分本地历史文件无法读取；请检查 local/backtests，未覆盖这些文件。"

    def configuration(self):
        try:
            values = load_config(self.root)
        except ConfigurationError:
            return {"configured": False, "reason": "本机 .env 格式或权限无效；Greeks.live 配置未启用"}
        present = bool(values.get("GREEKS_LIVE_AUTH_TOKEN"))
        return {"configured": present, "reason": "回测会话字段已填写，仍需检查服务能力" if present else
                ("已配置 CSV Data API Key；它不是已验证的回测会话。缺少 GREEKS_LIVE_AUTH_TOKEN。" if values.get("GREEKS_LIVE_DATA_API_KEY") else "缺少 .env 中的 GREEKS_LIVE_AUTH_TOKEN；公共行情不受影响")}

    def snapshot(self):
        with self.lock:
            return {"server_time": iso(), "csrf_token": self.csrf_token, "configuration": self.configuration(),
                    "capabilities": copy.deepcopy(self.capabilities), "experiment": copy.deepcopy(EXPERIMENT),
                    "runs": [self._public_record(record) for record in reversed(self.runs)], "storage_error": self.storage_error,
                    "tool_capabilities": self.tool_capabilities()}

    def _client(self):
        try:
            config = load_config(self.root)
        except ConfigurationError:
            raise BacktestError(self.configuration()["reason"]) from None
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

    def tool_capabilities(self):
        return {"schema_version": "btc-buyer-v1", "fields": sorted(PARAMETER_FIELDS),
                "fixed": {"asset": "BTC", "numeraire": "BTC", "side": "long", "mode": "reopen", "hedge_mode": "none", "close_dte": 0},
                "ranges": {"window_days": [1, 31], "session_bucket": "HH:MM:SS UTC", "entry_weekdays": "unique integers 0=Monday through 6=Sunday",
                           "option_type": ["call", "put"], "delta": [.01, .99], "expiry": [2, 90], "quantity": [.01, 1], "option_transaction_cost_bp": [0, 100]},
                "range_note": "这些上限为本机 S3 研究范围，并非服务全能力。全部九个字段必填，拒绝其他参数。",
                "coverage": copy.deepcopy(self.capabilities.get("coverage")),
                "price_source": "Greeks.live SABR/WV4 surface model; not executable bid/ask",
                "mode_description": "每个允许入场日开仓，下一有曲面数据日平仓；到期结算或缺失数据仍可能无法核账。",
                "fee_basis": "每次开平仓 quantity × option_transaction_cost_bp / 10000 BTC，服务 PnL 已扣费用。",
                "unknowns": copy.deepcopy(UNKNOWNS),
                "source_urls": [BASE_URL + "/static/render.js?v=20260921-3", BASE_URL + "/static/events.js?v=20260923-1"]}

    def _find(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise BacktestError("无效的回测记录 ID")
        record = next((record for record in self.runs if record["run_id"] == run_id), None)
        if record is None:
            raise BacktestError("不存在该回测记录")
        return record

    def _public_record(self, record):
        result = copy.deepcopy(record)
        result["can_resume"] = bool(record.get("service_task_id") and record["status"] in {"paused", "interrupted", "retrieval_failed", "result_incomplete"})
        result["can_retry"] = bool(record.get("confirmed_not_created") and record["status"] == "not_submitted")
        result["previous_run_id"] = record.get("previous_run_id")
        result["recovery_reason"] = ("仅继续 GET 和本地处理，不重新 POST。" if result["can_resume"] else
                                     "已确认尚未发送 POST；修复后可显式建立新尝试，保留旧记录。" if result["can_retry"] else
                                     "是否创建未知；禁止重发，需人类核对远端。" if record["status"] == "submission_unknown" else
                                     "远端报告过期或不可再取得，未保存的结果不可恢复。" if record["status"] == "unrecoverable" else None)
        return result

    def get_run(self, run_id):
        with self.lock:
            return self._public_record(self._find(run_id))

    def reanalyze_saved(self, run_id):
        """Recheck saved bytes locally. Preserve prior derived analysis; never GET/POST."""
        with self.lock:
            record = self._find(run_id)
            directory = self.storage / run_id
            if not record.get("analysis") or not (directory / "report.raw.json").exists():
                return False
            merged = {}
            for name in ("status.raw.json", "report.raw.json"):
                path = directory / name
                if path.exists():
                    merged.update(json.loads(path.read_text()))
            if merged.get("request") != record["request"]:
                raise BacktestError("保存报告的请求与原始请求不符，拒绝重新核账")
            files = {key: directory / name for key, name in [("csv", "details.csv"), ("daily_csv", "daily.csv"), ("report", "report.txt")] if (directory / name).exists()}
            updated = analyze_report(merged, files)
            if updated == record["analysis"]:
                return False
            record.setdefault("analysis_history", []).append({"analysis": record["analysis"], "superseded_at": iso(), "reason": "使用当前确定性核账器重新核对已保存原始文件；无远端请求"})
            record.update(analysis=updated, analyzed_at=iso())
            self._save(record)
            return True

    def submit(self, experiment_id):
        """Keep the S2 sample's identity without swallowing future experiments."""
        if experiment_id != EXPERIMENT_ID:
            raise BacktestError("未知固定实验")
        with self.lock:
            existing = next((record for record in self.runs if record.get("experiment_id") == EXPERIMENT_ID), None)
            if existing:
                return existing["run_id"]
            return self._submit_request(copy.deepcopy(EXPERIMENT["request"]), "fixed:" + EXPERIMENT_ID,
                                        experiment_id=EXPERIMENT_ID)["run_id"]

    def submit_experiment(self, params, *, logical_id, hypothesis=None, comparison_plan=None, before_create=None):
        with self.lock:
            request = validate_experiment(params, self.capabilities.get("coverage"))
            return self._submit_request(request, logical_id, hypothesis=hypothesis,
                                        comparison_plan=comparison_plan, proposed_parameters=params, before_create=before_create)

    def _submit_request(self, request, logical_id, *, hypothesis=None, comparison_plan=None,
                        proposed_parameters=None, experiment_id="S3_BTC_BUYER_V1", previous_run_id=None, before_create=None):
        if not isinstance(logical_id, str) or not re.fullmatch(r"[A-Za-z0-9_:.~-]{1,160}", logical_id):
            raise BacktestError("无效的逻辑提交标识")
        fingerprint = request_fingerprint(request)
        existing = next((record for record in self.runs if record.get("logical_id") == logical_id or logical_id in record.get("logical_aliases", [])), None)
        if existing:
            if request_fingerprint(existing["request"]) != fingerprint:
                raise BacktestError("同一逻辑步骤不能更换实验参数")
            return {"run_id": existing["run_id"], "reused": True, "created_attempt": False}
        if previous_run_id is None:
            existing = next((record for record in self.runs if request_fingerprint(record["request"]) == fingerprint
                             and record["status"] != "not_submitted"), None)
            if existing:
                existing.setdefault("logical_aliases", []).append(logical_id)
                self._save(existing)
                return {"run_id": existing["run_id"], "reused": True, "created_attempt": False}
        if self.storage_error:
            raise BacktestError("历史记录存在读取错误；核对已有提交前不能创建新任务")
        if self.active:
            raise BacktestError("已有检查或回测进行中")
        if self.stop_event.is_set():
            raise BacktestError("后端正在停止，不能启动任务")
        if not self.configuration()["configured"] or self.capabilities["status"] != "ready":
            raise BacktestError("请先配置回测会话并通过服务能力检查")
        if before_create is not None:
            before_create()  # Caller durably reserves its budget while our creation lock is held.
        record = {"run_id": uuid.uuid4().hex, "experiment_id": experiment_id, "logical_id": logical_id,
                  "request_fingerprint": fingerprint, "created_at": iso(), "submitted_at": None,
                  "completed_at": None, "service_task_id": None, "status": "queued", "error": None,
                  "request": copy.deepcopy(request), "proposed_parameters": copy.deepcopy(proposed_parameters),
                  "hypothesis": copy.deepcopy(hypothesis), "comparison_plan": copy.deepcopy(comparison_plan),
                  "previous_run_id": previous_run_id, "creation_attempted": False,
                  "confirmed_not_created": False, "analysis": None, "retrieval_attempts": 0}
        self._save(record)  # Hypothesis and actual canonical parameters exist before any POST.
        save_json(self.storage / record["run_id"] / "request.json", {"method": "POST", "url": BASE_URL + "/api/backtests", "body": request, "authentication": "Authorization header intentionally excluded"})
        self.runs.append(record)
        self.pause_events[record["run_id"]] = threading.Event()
        self._launch(self._execute, record, False)
        return {"run_id": record["run_id"], "reused": False, "created_attempt": True}

    def resume(self, run_id):
        """Explicit GET-only recovery; never fall through into the POST branch."""
        with self.lock:
            record = self._find(run_id)
            if not self._public_record(record)["can_resume"]:
                raise BacktestError("该记录无法继续获取；未知提交不能重发，过期结果不能恢复")
            if self.active or self.stop_event.is_set():
                raise BacktestError("已有回测操作进行中或后端正在停止")
            self.pause_events[run_id] = threading.Event()
            record.update(status="running", error=None, completed_at=None)
            self._save(record)
            self._launch(self._execute, record, True)
            return run_id

    def retry(self, run_id, *, logical_id, before_create=None):
        with self.lock:
            old = self._find(run_id)
            if not self._public_record(old)["can_retry"]:
                raise BacktestError("仅已确认未发送的失败可以建立新尝试；未知提交禁止重发")
            result = self._submit_request(copy.deepcopy(old["request"]), logical_id,
                experiment_id=old["experiment_id"], hypothesis=old.get("hypothesis"),
                comparison_plan=old.get("comparison_plan"), proposed_parameters=old.get("proposed_parameters"), previous_run_id=run_id, before_create=before_create)
            old["next_attempt_run_id"] = result["run_id"]
            self._save(old)
            return result

    def pause(self, run_id):
        """Stop this run's local polling; this does not cancel a remote task."""
        with self.lock:
            self._find(run_id)
            event = self.pause_events.get(run_id)
            if event:
                event.set()

    def _is_stopped(self, record):
        return self.stop_event.is_set() or self.pause_events.get(record["run_id"], threading.Event()).is_set()

    def _execute(self, record, retrieval_only=False):
        client = None
        directory = self.storage / record["run_id"]
        try:
            client = self._client()
            if retrieval_only:
                task_id = record.get("service_task_id")
                if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                    raise BacktestError("没有可验证的已知任务 ID，拒绝继续")
                task = client.request("GET", "/api/backtests/" + task_id, save_to=directory / "status.raw.json")
                if task.get("id") != task_id:
                    raise BacktestError("服务返回的任务标识不一致；停止读取结果")
            else:
                self._verify(client)
                coverage = self.capabilities["coverage"]
                if not coverage["start_date"] <= record["request"]["start_date"] <= record["request"]["end_date"] <= coverage["end_date"]:
                    raise BacktestError("实验日期不在服务当前可用范围内；不会自动更换参数")
                if self._is_stopped(record):
                    raise BacktestError("本地任务已停止；尚未发送远端请求")
                with self.lock:
                    record.update(status="submitting", submitted_at=iso(), creation_attempted=True)
                    self._save(record)  # Crash after this point is conservatively submission_unknown.
                task = client.request("POST", "/api/backtests", record["request"], save_to=directory / "submit.raw.json")
                task_id = task.get("id")
                if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                    raise BacktestError("远端未返回可验证的任务标识；不会重复提交", uncertain=True)
                with self.lock:
                    record.update(service_task_id=task_id, status="running")
                    self._save(record)
            with self.lock:
                record["retrieval_attempts"] = record.get("retrieval_attempts", 0) + 1
                self._save(record)
            self._retrieve(client, record, task)
        except Exception as error:
            with self.lock:
                if record.get("service_task_id"):
                    status = ("unrecoverable" if isinstance(error, BacktestError) and error.unavailable else
                              "paused" if self._is_stopped(record) else "retrieval_failed")
                elif record.get("creation_attempted") or record.get("submitted_at"):
                    status = "submission_unknown"
                else:
                    status = "not_submitted"
                    record["confirmed_not_created"] = True
                message = str(error) if isinstance(error, BacktestError) else "回测内部异常；详情已脱敏记录"
                if status == "unrecoverable":
                    message = "远端任务已过期或报告不可再取得；未保存的结果不可恢复。" + message
                record.update(status=status, error=message, completed_at=iso())
                self._save(record)
            if not isinstance(error, BacktestError):
                logging.error("backtest worker: %s", safe_traceback(error))
        finally:
            if client:
                client.close()

    def _retrieve(self, client, record, task):
        directory = self.storage / record["run_id"]
        task_id = record["service_task_id"]
        deadline = time.monotonic() + 600
        while task.get("status") not in {"completed", "failed"}:
            if task.get("status") in {"expired", "deleted"}:
                raise BacktestError("服务明确报告任务已经过期或删除", unavailable=True)
            if self.stop_event.wait(self.poll_seconds) or self._is_stopped(record):
                raise BacktestError("本地轮询已暂停；远端任务可能继续，可显式继续获取结果")
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
        if self._is_stopped(record):
            raise BacktestError("本地获取已暂停；远端任务及已保存材料保留")
        with self.lock:
            record.update(status="fetching")
            self._save(record)
        report = client.request("GET", f"/api/backtests/{task_id}/report-data", save_to=directory / "report.raw.json")
        for response in (task, report):
            if "request" in response and response["request"] != record["request"]:
                raise BacktestError("服务结果中的请求与本地原始参数不一致；不能计量")
        merged = {"request": record["request"], **task, **report}
        artifact_files = {}
        for field, local_name in [("csv", "details.csv"), ("daily_csv", "daily.csv"), ("report", "report.txt")]:
            if self._is_stopped(record):
                raise BacktestError("本地下载已暂停；可显式继续获取结果")
            name = merged.get("artifacts", {}).get(field)
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                content = client.request("GET", f"/api/backtests/{task_id}/artifact/{quote(name, safe='')}", binary=True)
                atomic_write(directory / local_name, content)
                artifact_files[field] = directory / local_name
        analysis = analyze_report(merged, artifact_files)
        with self.lock:
            status = ("result_incomplete" if analysis.get("reported_pnl") is None else
                      "completed_with_gaps" if analysis["gaps"] else "completed")
            record.update(status=status, analysis=analysis, completed_at=iso(), error=None)
            self._save(record)

    def stop(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)

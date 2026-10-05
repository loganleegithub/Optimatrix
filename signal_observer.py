"""Two fixed public-data studies. No accounts, credentials, orders or model calls."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import threading
import time

import requests

from market import iso
from signal_study import SignalStudyError, aggregate_hourly, latest_signals, replay_price_study, rules_hash

HOUR = 3_600_000
INTERVAL = 60
BASE = "https://www.deribit.com/api/v2/public/"


class ObservationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def implementation_hash():
    root = Path(__file__).resolve().parent
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in
                                  ("signal_study.py", "signal_observer.py"))).hexdigest()


def save(path, value):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class PublicStudyClient:
    """Fixed endpoint/parameters; .netrc, environment auth/proxies and redirects disabled."""
    def __init__(self, root):
        self.root = Path(root)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "Optimatrix-public-signal-study/1.0"})

    def _get(self, method, params):
        if method not in {"get_instrument", "get_tradingview_chart_data"}:
            raise ObservationError("公共观察接口不在白名单")
        if (self.root / "STOP").exists():
            raise ObservationError("STOP 已触发")
        try:
            response = self.session.get(BASE + method, params=params, timeout=(3.05, 10),
                                        allow_redirects=False)
            if response.status_code != 200:
                raise ObservationError("公共行情 HTTP 请求失败")
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, ObservationError):
                raise
            raise ObservationError("公共行情连接或响应失败") from None
        received = time.time()
        stamp = result.get("usOut") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("testnet") is not False
                or "error" in result or "result" not in result):
            raise ObservationError("主网公共响应身份未核实")
        if (isinstance(stamp, bool) or not isinstance(stamp, (float, int))
                or not math.isfinite(stamp) or not -5 <= received - stamp / 1e6 <= 30):
            raise ObservationError("公共响应时间异常或过时")
        return {"payload": result, "received_at": iso(received), "source_at": iso(stamp / 1e6)}

    def instrument(self):
        result = self._get("get_instrument", {"instrument_name": "BTC-PERPETUAL"})
        meta = result["payload"]["result"]
        required = {"instrument_name": "BTC-PERPETUAL", "kind": "future",
                    "instrument_type": "reversed", "base_currency": "BTC",
                    "counter_currency": "USD", "settlement_currency": "BTC", "price_index": "btc_usd"}
        if not isinstance(meta, dict) or any(meta.get(k) != v for k, v in required.items()):
            raise ObservationError("BTC-PERPETUAL 产品与 USD 价格单位未核实")
        return result

    def candles(self, start, end):
        if not isinstance(start, int) or not isinstance(end, int) or start >= end or end-start > 30*24*HOUR:
            raise ObservationError("公共历史请求区间无效")
        return self._get("get_tradingview_chart_data", {"instrument_name": "BTC-PERPETUAL",
                         "resolution": "60", "start_timestamp": start, "end_timestamp": end-1})

    def close(self):
        self.session.close()


class SignalStudyService:
    def __init__(self, root, strategies, client=None):
        self.root, self.strategies = Path(root), strategies
        self.directory = self.root / "local" / "signal-studies"
        self.client = client or PublicStudyClient(root)
        self.lock, self.stop_event, self.thread = threading.RLock(), threading.Event(), None
        self.manifest = None
        self.hours = []
        self.previous_bar = None  # A restart never invents a newly observed historical event.
        self.loaded_implementation = implementation_hash()
        self.state = {"status": "not_started", "authority": "public_observation_only",
                      "source": "Deribit 主网公共 BTC-PERPETUAL · USD 价格",
                      "observed_at": None, "last_success_at": None, "next_check_at": None,
                      "candidates": [], "catalog": [], "error": None}
        try:
            manifest_path = self.directory / "manifest.json"
            if manifest_path.exists():
                self.manifest = json.loads(manifest_path.read_text())
                self._check_binding()
                self.state.update(status="starting", catalog=self.manifest["catalog"], sources=self.manifest.get("sources", []),
                                  candidates=self.manifest["candidates"])
                cache = self.directory / "hourly.json"
                if cache.exists():
                    saved = json.loads(cache.read_text())
                    if saved["sha256"] != digest(saved["hours"]):
                        raise ObservationError("已保存小时数据校验失败")
                    self.hours = saved["hours"]
        except (OSError, ValueError, KeyError, TypeError):
            self.state.update(status="blocked", error="观察配置、版本身份或缓存无效；未启动")
            self.manifest = None

    def _check_binding(self):
        m = self.manifest
        if (not isinstance(m, dict) or m.get("schema") != "public-signal-study-v1"
                or m.get("enabled") is not True or m.get("authority") != "public_observation_only"
                or m.get("definition_sha256") != rules_hash()
                or m.get("implementation_sha256") != self.loaded_implementation
                or implementation_hash() != self.loaded_implementation
                or not isinstance(m.get("candidates"), list)
                or any(not isinstance(c, dict) for c in m["candidates"])
                or sorted(c.get("key") for c in m.get("candidates", [])) != ["squeeze", "supertrend"]):
            raise ObservationError("观察规则或实现身份不一致")
        for candidate in m["candidates"]:
            detail = self.strategies.detail(candidate["strategy_id"])
            version = next((v for v in detail["versions"] if v["version_id"] == candidate["version_id"]), None)
            if not version or version["status"] != "frozen" or version["rules_sha256"] != candidate["rules_sha256"]:
                raise ObservationError("观察策略的冻结版本不一致")
        seed, evaluation = m.get("seed_start_ms"), m.get("evaluation_start_ms")
        if (type(seed) is not int or type(evaluation) is not int or seed < 0 or seed % (4*HOUR)
                or evaluation-seed != 200*4*HOUR or evaluation > time.time()*1000
                or time.time()*1000-seed > 730*24*HOUR):
            raise ObservationError("观察历史区间无效或超过两年采集上限")

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _publish(self, update, *, evidence=None):
        import os
        with self.lock:
            next_state = {**self.state, **update}
            if self.manifest:
                self.directory.mkdir(parents=True, exist_ok=True)
                record = {**update, "definition_sha256": self.manifest["definition_sha256"],
                          "implementation_sha256": self.loaded_implementation,
                          "evidence_type": "public_signal_observation"}
                if evidence:
                    record["evidence"] = evidence
                with (self.directory / "cycles.jsonl").open("a") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                save(self.directory / "state.json", next_state)
            self.state = next_state

    def cycle(self):
        now = time.time()
        if self.stop_event.is_set():
            return
        if (self.root / "STOP").exists():
            self._publish({"status": "stopped", "observed_at": iso(now), "next_check_at": iso(now+INTERVAL),
                           "error": "STOP 存在：公共观察停止，旧信号仅作历史记录"})
            return
        if not self.manifest:
            return
        try:
            self._check_binding()
            end = int(now * 1000) // HOUR * HOUR
            seed = self.manifest["seed_start_ms"]
            start = max(seed, self.hours[-1]["timestamp"] - 8*HOUR) if self.hours else seed
            if not self.hours:
                save(self.directory / "instrument.json", self.client.instrument())
            combined = {h["timestamp"]: h for h in self.hours}
            envelopes = []
            while start < end:
                if self.stop_event.is_set() or (self.root / "STOP").exists():
                    raise ObservationError("STOP 或服务停止：本轮中止")
                chunk_end = min(start+30*24*HOUR, end)
                envelope = self.client.candles(start, chunk_end)
                result = envelope["payload"]["result"]
                fields = ("ticks", "open", "high", "low", "close")
                if (not isinstance(result, dict) or result.get("status") != "ok"
                        or any(not isinstance(result.get(f), list) for f in fields)
                        or len({len(result[f]) for f in fields}) != 1):
                    raise ObservationError("小时行情缺失或结构无效")
                seen = set()
                for i, stamp in enumerate(result["ticks"]):
                    if (isinstance(stamp, bool) or not isinstance(stamp, int)
                            or stamp % HOUR or stamp < start or stamp >= chunk_end or stamp in seen):
                        raise ObservationError("小时行情重复、越界或时间戳无效")
                    seen.add(stamp)
                    row = {"timestamp": stamp, **{k: result[k][i] for k in fields[1:]}}
                    if stamp in combined and combined[stamp] != row:
                        raise ObservationError("已完成历史小时被修改：保留原记录并停止观察")
                    combined[stamp] = row
                if len(seen) != (chunk_end-start)//HOUR:
                    raise ObservationError("小时行情存在缺口，禁止补值")
                raw_path = self.directory / "raw" / f"{start}-{chunk_end}-{time.time_ns()}.json"
                save(raw_path, envelope)
                envelopes.append(str(raw_path.relative_to(self.root)))
                start = chunk_end
            hours = [combined[key] for key in sorted(combined)]
            bars = aggregate_hourly(hours, int(time.time()*1000))
            latest = latest_signals(bars)
            completed = int(time.time()*1000) // (4*HOUR) * (4*HOUR)
            if not bars or bars[-1]["timestamp"] + 4*HOUR != completed:
                raise ObservationError("最新完整四小时线缺失")
            replay = replay_price_study(bars, self.manifest["evaluation_start_ms"], completed, warmup_bars=200)
            candidates = []
            for item in self.manifest["candidates"]:
                key = item["key"]
                value = latest[key]
                result = replay["strategies"][key]
                summary = result["summary"]
                candidates.append({**item, "latest": {**value,
                    "close": latest["price"], "entry": value["entry_event"], "exit": value["exit_event"],
                    "direction": value.get("direction", "up" if (value.get("momentum") or 0)>0 else "down" if (value.get("momentum") or 0)<0 else "neutral"),
                    "indicators": {k: v for k, v in value.items() if k not in {"ready", "entry_event", "exit_event", "event", "direction"}},
                    "bar_time": iso(bars[-1]["timestamp"]/1000), "bar_end_time": iso(completed/1000),
                    "signal_at": iso(completed/1000),
                    "fresh_event": self.previous_bar is not None and completed > self.previous_bar
                                   and 0 <= time.time()-completed/1000 <= 120},
                    "replay": {**summary, "evidence_type": "underlying_price_diagnostic",
                        "start_at": replay["start_utc"], "end_at": replay["end_utc"],
                        "open_position": result["open_position"], "limitations": [
                            "仅已闭合的假设交易；未闭合仓位另列。", "未包含永续资金费率、期权定价、真实盘口与成交费用。",
                            "单边 10/25bp 是事先固定的成本敏感性，不能替代实际执行成本。",
                            "四小时 K 线无法证明止损价可成交或精确触发时间。"]}})
            # Preserve full causal diagnostic separately; it is not an execution ledger.
            save(self.directory / "replay.json", {"evidence_type": "underlying_price_diagnostic",
                 "data_sha256": digest(hours), "definition_sha256": rules_hash(), "result": replay})
            save(self.directory / "hourly.json", {"sha256": digest(hours), "hours": hours})
            self.hours = hours
            finished = time.time()
            self._publish({"status": "observing", "error": None, "observed_at": iso(finished),
                           "last_success_at": iso(finished), "next_check_at": iso(finished+INTERVAL),
                           "candidates": candidates, "hour_count": len(hours), "bar_count": len(bars),
                           "data_sha256": digest(hours)}, evidence=envelopes)
            self.previous_bar = completed
        except OSError:
            self.stop_event.set()
            with self.lock:
                self.state.update(status="storage_error", error="观察记录无法持久化；已停止公共请求，需修复后重启", observed_at=iso())
            # The in-memory error remains visible even when this best effort write fails.
            try:
                self._publish({"status": "storage_error", "error": self.state["error"], "observed_at": iso()})
            except OSError:
                pass
        except Exception as error:
            reason = str(error) if isinstance(error, (ObservationError, SignalStudyError)) else "公共观察失败（" + type(error).__name__ + "）；旧值不代表新信号"
            self._publish({"status": "blocked", "error": reason, "observed_at": iso(),
                           "next_check_at": iso(time.time()+INTERVAL)})

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.cycle()
            except Exception:
                with self.lock:
                    self.state.update(status="storage_error", error="观察记录无法持久化；已停止公共请求", observed_at=iso())
                return
            self.stop_event.wait(INTERVAL)

    def start(self):
        if self.manifest and self.thread is None:
            self.thread = threading.Thread(target=self._run, name="public-signal-study", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        self.client.close()

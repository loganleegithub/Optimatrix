"""Deribit production public market data. No account or trading capabilities."""
from __future__ import annotations

import copy
import logging
import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

BASE_URL = "https://www.deribit.com/api/v2/"
REFRESH_SECONDS = 15
STALE_SECONDS = 60
CATALOG_SECONDS = 300
PUBLIC_METHODS = {"get_index_price", "get_instruments", "get_order_book"}


def iso(seconds=None):
    return datetime.fromtimestamp(time.time() if seconds is None else seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def number(value, *, positive=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (value > 0 if positive else value >= 0)


class MarketError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def retry_delay(failures, retry_after=0):
    return max(min(REFRESH_SECONDS * 2 ** min(failures, 5), 300), retry_after)


class PublicClient:
    def __init__(self):
        self.session = requests.Session()
        # Avoid .netrc, environment credentials/proxies and implicit authentication.
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "Optimatrix-S1-public/1.0"})

    def close(self):
        self.session.close()

    def get(self, method, **params):
        if method not in PUBLIC_METHODS:
            raise MarketError("拒绝非白名单公共接口")
        try:
            response = self.session.get(BASE_URL + "public/" + method, params=params,
                                        timeout=(3.05, 7), allow_redirects=False)
        except requests.Timeout:
            raise MarketError("Deribit 请求超时") from None
        except requests.RequestException:
            raise MarketError("Deribit 连接失败（网络或 TLS）") from None
        if response.status_code == 429:
            header = response.headers.get("Retry-After", "60")
            try:
                delay = float(header)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(header).timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    delay = 60
            if not math.isfinite(delay):
                delay = 60
            raise MarketError("Deribit 限频（HTTP 429），等待后重试", max(60, delay))
        if response.status_code != 200:
            raise MarketError(f"Deribit HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise MarketError("Deribit 返回非 JSON 数据") from None
        received = time.time()
        if not isinstance(payload, dict):
            raise MarketError("Deribit 响应结构异常")
        if "error" in payload:
            err = payload["error"]
            code = err.get("code") if isinstance(err, dict) else None
            # Never echo arbitrary remote messages into logs or the browser.
            if code == 10028:
                raise MarketError("Deribit 限频（10028），等待后重试", 60)
            raise MarketError(f"Deribit 接口错误（代码 {code if isinstance(code, int) else '未知'}）")
        if payload.get("testnet") is not False or "result" not in payload:
            raise MarketError("未确认生产公共接口响应")
        source_us = payload.get("usOut")
        if not number(source_us, positive=True) or source_us / 1e6 > received + 5:
            raise MarketError("交易所响应时间异常，请检查本机时钟")
        return {"payload": payload, "received_at": iso(received), "source_at": iso(source_us / 1e6)}


def valid_instrument(item, now):
    if not isinstance(item, dict):
        return False
    required = {"kind": "option", "instrument_type": "reversed", "base_currency": "BTC",
                "quote_currency": "BTC", "settlement_currency": "BTC", "counter_currency": "USD",
                "price_index": "btc_usd", "state": "open"}
    return (all(item.get(k) == v for k, v in required.items()) and item.get("is_active") is True
            and item.get("option_type") in ("call", "put")
            and number(item.get("contract_size"), positive=True) and item["contract_size"] == 1
            and number(item.get("strike"), positive=True)
            and number(item.get("expiration_timestamp"), positive=True)
            and item["expiration_timestamp"] / 1000 > now
            and isinstance(item.get("instrument_name"), str) and bool(item["instrument_name"]))


def select_instruments(instruments, spot, now):
    """Two nearest expiries with both sides at the closest common strike. Display only."""
    valid = [i for i in instruments if valid_instrument(i, now)]
    comfortable = [i for i in valid if i["expiration_timestamp"] / 1000 > now + 3600]
    pool = comfortable or valid
    selected = []
    for expiry in sorted({i["expiration_timestamp"] for i in pool}):
        group = [i for i in pool if i["expiration_timestamp"] == expiry]
        calls = {i["strike"]: i for i in group if i["option_type"] == "call"}
        puts = {i["strike"]: i for i in group if i["option_type"] == "put"}
        common = calls.keys() & puts.keys()
        if common:
            strike = min(common, key=lambda k: (abs(k - spot), k))
            selected.extend([calls[strike], puts[strike]])
        if len(selected) == 4:
            break
    if not selected:
        raise MarketError("未取得符合产品字段校验且同时有 Call/Put 的有效合约")
    return selected


def empty_option(item):
    keys = ("instrument_name", "option_type", "strike", "contract_size", "base_currency", "quote_currency", "settlement_currency", "instrument_type")
    return {**{key: item[key] for key in keys}, "expires_at": iso(item["expiration_timestamp"] / 1000),
            "bid": None, "ask": None, "bid_amount": None, "ask_amount": None,
            "source_at": None, "received_at": None, "error": None}


def parse_book(envelope, instrument):
    result = envelope["payload"]["result"]
    if not isinstance(result, dict) or result.get("instrument_name") != instrument["instrument_name"] or result.get("state") != "open":
        raise MarketError("订单簿合约身份不匹配或未开放")
    stamp = result.get("timestamp")
    if not number(stamp, positive=True) or stamp / 1000 > epoch(envelope["received_at"]) + 5:
        raise MarketError("订单簿源时间异常")
    parsed = {"source_at": iso(stamp / 1000), "received_at": envelope["received_at"], "error": None}
    for side, field in (("bid", "bids"), ("ask", "asks")):
        levels = result.get(field)
        if not isinstance(levels, list):
            raise MarketError("订单簿档位缺失")
        if not levels:
            parsed[side] = parsed[side + "_amount"] = None
        else:
            level = levels[0]
            if not isinstance(level, list) or len(level) != 2 or not all(number(v, positive=True) for v in level):
                raise MarketError("订单簿价格或数量异常")
            parsed[side], parsed[side + "_amount"] = level
    if parsed["bid"] is not None and parsed["ask"] is not None and parsed["bid"] > parsed["ask"]:
        raise MarketError("订单簿买卖价交叉")
    return parsed


class MarketService:
    def __init__(self, client=None, integrations=None):
        self.client = client or PublicClient()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.instruments = []
        self.catalog_mono = None
        self.state = {"started_at": iso(), "sequence": 0, "refresh_seconds": REFRESH_SECONDS,
                      "stale_seconds": STALE_SECONDS, "index": None, "options": [],
                      "catalog": {"count": 0, "source_at": None, "received_at": None, "error": None},
                      "collector": {"running": False, "last_attempt_at": None, "last_success_at": None, "next_retry_at": None, "error": None},
                      "integrations": integrations or {}}

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            data = copy.deepcopy(self.state)
        data["server_time"] = iso(now)
        for item in [data["index"], data["catalog"], *data["options"]]:
            if item is None:
                continue
            source = epoch(item["source_at"]) if item.get("source_at") else None
            receipt = epoch(item["received_at"]) if item.get("received_at") else None
            item["source_age_seconds"] = round(max(0, now - source), 3) if source is not None else None
            item["receipt_age_seconds"] = round(max(0, now - receipt), 3) if receipt is not None else None
            threshold = CATALOG_SECONDS * 2 + STALE_SECONDS if item is data["catalog"] else STALE_SECONDS
            item["status"] = "missing" if receipt is None else "live"
            if source is not None and (now - source > threshold or source > now + 5 or now - receipt > threshold):
                item["status"] = "stale"
            if item.get("error"):
                item["status"] = "error"
            if item.get("expires_at") and epoch(item["expires_at"]) <= now:
                item["status"] = "expired"
        return data

    def refresh_once(self):
        target = "index"
        with self.lock:
            self.state["collector"]["last_attempt_at"] = iso()
        try:
            response = self.client.get("get_index_price", index_name="btc_usd")
            result = response["payload"]["result"]
            price = result.get("index_price") if isinstance(result, dict) else None
            if not number(price, positive=True):
                raise MarketError("BTC 指数价格缺失或无效")
            with self.lock:
                self.state["index"] = {"price": price, "source_at": response["source_at"], "received_at": response["received_at"],
                                       "source_time_kind": "Deribit 响应时间（非指数独立事件时间）", "error": None}
            target = "catalog"
            expired = any(epoch(o["expires_at"]) <= time.time() for o in self.state["options"])
            if self.catalog_mono is None or time.monotonic() - self.catalog_mono >= CATALOG_SECONDS or expired:
                response = self.client.get("get_instruments", currency="BTC", kind="option", expired="false")
                values = response["payload"]["result"]
                if not isinstance(values, list):
                    raise MarketError("合约目录结构异常")
                instruments = [i for i in values if valid_instrument(i, time.time())]
                chosen = select_instruments(instruments, price, time.time())
                with self.lock:
                    previous = {o["instrument_name"]: o for o in self.state["options"]}
                    self.state["options"] = [previous.get(i["instrument_name"], empty_option(i)) for i in chosen]
                    self.state["catalog"] = {"count": len(instruments), "source_at": response["source_at"], "received_at": response["received_at"], "error": None}
                self.instruments = instruments
                self.catalog_mono = time.monotonic()
            target = "options"
            for option in self.state["options"]:
                if self.stop_event.is_set():
                    return
                response = self.client.get("get_order_book", instrument_name=option["instrument_name"], depth=1)
                parsed = parse_book(response, option)
                with self.lock:
                    option.update(parsed)
            with self.lock:
                self.state["sequence"] += 1
                self.state["collector"].update(last_success_at=iso(), error=None)
        except MarketError as error:
            with self.lock:
                self.state["collector"]["error"] = str(error)
                affected = self.state["options"] if target == "options" else [self.state[target]]
                for item in affected:
                    if item is not None:
                        item["error"] = str(error)
            raise

    def _run(self):
        failures = 0
        try:
            while not self.stop_event.is_set():
                try:
                    self.refresh_once()
                    failures, delay = 0, REFRESH_SECONDS
                    logging.info("public refresh complete; sequence=%s", self.state["sequence"])
                except MarketError as error:
                    failures += 1
                    delay = retry_delay(failures, error.retry_after)
                    logging.warning("public refresh failed: %s; retry in %.0fs", error, delay)
                except Exception:
                    # Keep the process observable even if a new remote schema causes an unexpected error.
                    failures += 1
                    delay = retry_delay(failures)
                    with self.lock:
                        self.state["collector"]["error"] = "采集内部异常；保留上次数据，等待重试"
                    logging.error("unexpected collector error; retry in %.0fs", delay)
                with self.lock:
                    self.state["collector"]["next_retry_at"] = iso(time.time() + delay)
                self.stop_event.wait(delay)
        finally:
            with self.lock:
                self.state["collector"]["running"] = False
            self.client.close()

    def start(self):
        if self.thread is not None:
            raise RuntimeError("collector already started")
        with self.lock:
            self.state["collector"]["running"] = True
        self.thread = threading.Thread(target=self._run, name="public-market", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=12)

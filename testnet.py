"""Fixed Deribit network boundaries; authentication stays inside this connector.

No model, strategy, or caller may choose a host or a private API method. The
runtime owns persisted intents, budgets and reconciliation; this module never
retries trading writes. All timestamps exposed by envelopes are UTC epoch seconds.
"""
from __future__ import annotations

import math
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from configuration import ConfigurationError, TESTNET_FIELDS, read_secrets

TESTNET_URL = "https://test.deribit.com/api/v2/"
MAINNET_URL = "https://www.deribit.com/api/v2/"
MAX_PAGES = 200
PAGE_SIZE = 1000
PUBLIC_METHODS = frozenset({"public/get_instruments", "public/get_order_book",
                            "public/get_index_price", "public/get_tradingview_chart_data"})
READ_METHODS = frozenset({"private/get_account_summary", "private/get_positions",
                        "private/get_open_orders_by_currency", "private/get_user_trades_by_currency_and_time",
                        "private/get_order_history_by_currency", "private/get_order_state",
                        "private/get_order_state_by_label"})
WRITE_METHODS = frozenset({"private/buy", "private/sell", "private/cancel"})
AUTH_SCOPE = ("trade:read_write account:read wallet:none block_trade:none "
              "block_rfq:none custody:none expires:3600")


class TestnetError(Exception):
    def __init__(self, message, status="blocked", uncertain=False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _decimal(value):
    try:
        if isinstance(value, bool) or value is None:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (ValueError, InvalidOperation):
        raise TestnetError("数值字段无效", "invalid_data") from None


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
        raise TestnetError("标识字段无效", "invalid_data")
    return value


def _session():
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Optimatrix-testnet/1.0"})
    session.mount("https://", HTTPAdapter(max_retries=0))
    return session


def _response(response, *, testnet, received, request_id=None, write=False):
    if response.status_code != 200:
        raise TestnetError("交易所 HTTP 响应失败", "http_error", uncertain=write)
    try:
        payload = response.json()
    except (ValueError, TypeError):
        raise TestnetError("交易所响应不是有效 JSON", "invalid_response", uncertain=write) from None
    if (not isinstance(payload, dict) or payload.get("testnet") is not testnet
            or (request_id is not None and payload.get("id") != request_id)):
        raise TestnetError("交易所环境或响应身份未核实", "wrong_environment", uncertain=write)
    source = payload.get("usOut")
    if not _number(source) or source <= 0 or not -5 <= received - source / 1e6 <= 30:
        raise TestnetError("交易所响应时间无效或过时", "stale", uncertain=write)
    if "error" in payload:
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else None
        safe_code = str(code) if isinstance(code, int) and not isinstance(code, bool) else "未知"
        # A server timeout can be returned as JSON-RPC; do not call it a rejection.
        definite = code in {10000, 10002, 10003, 10005, 10006, 10007, 10009,
                            10010, 10011, 10012, 10013, 10014, 10015, 10016,
                            10017, 10018, 10019, 10020, 10021, 10022, 10023,
                            10024, 10025, 10026, 10027, 10028, 10030, 13009}
        raise TestnetError(f"交易所接口拒绝或失败（代码 {safe_code}）", "rpc_error",
                           uncertain=write and not definite)
    if "result" not in payload:
        raise TestnetError("交易所响应缺失结果", "invalid_response", uncertain=write)
    return {"result": payload["result"], "received_at": received, "source_at": source / 1e6}


def _book(envelope, name):
    book = envelope["result"]
    if not isinstance(book, dict) or book.get("instrument_name") != name:
        raise TestnetError("盘口合约身份未核实", "invalid_data")
    timestamp = book.get("timestamp")
    if not _number(timestamp) or not -5 <= envelope["received_at"] - timestamp / 1000 <= 30:
        raise TestnetError("盘口时间无效或过时", "stale")
    envelope["source_at"] = timestamp / 1000
    return envelope


class MarketDataProvider:
    """Production public reads only. No credential, auth, or arbitrary URL support."""

    def __init__(self):
        self.session = _session()

    def _get(self, method, **params):
        if method not in PUBLIC_METHODS:
            raise TestnetError("拒绝非白名单主网公共接口", "permission_denied")
        try:
            response = self.session.get(MAINNET_URL + method, params=params,
                                        timeout=(3.05, 10), allow_redirects=False)
        except requests.RequestException:
            raise TestnetError("主网公共连接失败", "network_error") from None
        return _response(response, testnet=False, received=time.time())

    def instruments(self):
        result = self._get("public/get_instruments", currency="BTC", kind="option", expired="false")["result"]
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise TestnetError("主网合约目录无效", "invalid_data")
        return result

    def candles(self, now=None, days=63):
        now = time.time() if now is None else now
        if not _number(now) or now <= 0 or not isinstance(days, int) or isinstance(days, bool) or not 2 <= days <= 123:
            raise TestnetError("UTC 时间无效", "invalid_data")
        midnight = int(now // 86400) * 86400
        start = midnight - days * 86400
        # Live verification found Deribit's native 1D bars anchored at 08:00 UTC.
        # The frozen economic rule requires 00:00 UTC, so construct those bars
        # solely from 24 verified actual hourly observations. Never fill gaps.
        envelope = self._get("public/get_tradingview_chart_data", instrument_name="BTC-PERPETUAL",
                             start_timestamp=start * 1000, end_timestamp=midnight * 1000 - 1, resolution="60")
        raw = envelope["result"]
        fields = ("open", "high", "low", "close", "volume", "cost")
        if (not isinstance(raw, dict) or raw.get("status") != "ok" or not isinstance(raw.get("ticks"), list)
                or any(not isinstance(raw.get(field), list) or len(raw[field]) != len(raw["ticks"]) for field in fields)):
            raise TestnetError("主网小时数据缺失或结构无效", "invalid_candles")
        rows = {}
        for index, tick in enumerate(raw["ticks"]):
            if not isinstance(tick, int) or isinstance(tick, bool) or tick % 3600000:
                raise TestnetError("主网小时数据未对齐 UTC 整点", "invalid_candles")
            if not start * 1000 <= tick < midnight * 1000:
                continue
            row = {field: raw[field][index] for field in fields}
            if (tick in rows or any(not _number(value) or value < 0 for value in row.values())
                    or row["low"] <= 0 or row["low"] > min(row["open"], row["close"])
                    or row["high"] < max(row["open"], row["close"])):
                raise TestnetError("主网小时数据重复或价格无效", "invalid_candles")
            rows[tick] = row
        expected = list(range(start * 1000, midnight * 1000, 3600000))
        if sorted(rows) != expected:
            raise TestnetError("主网小时数据有缺口，不能构造完整 UTC 日线", "invalid_candles")
        daily = {"status": "ok", "ticks": [], **{field: [] for field in fields}}
        for day in range(start, midnight, 86400):
            hours = [rows[(day + hour * 3600) * 1000] for hour in range(24)]
            daily["ticks"].append(day * 1000)
            daily["open"].append(hours[0]["open"])
            daily["close"].append(hours[-1]["close"])
            daily["high"].append(max(row["high"] for row in hours))
            daily["low"].append(min(row["low"] for row in hours))
            for field in ("volume", "cost"):
                daily[field].append(float(sum((_decimal(row[field]) for row in hours), Decimal(0))))
        envelope["result"] = daily
        envelope["source_result"] = raw
        envelope["aggregation"] = {"source_resolution": "60", "daily_boundary": "00:00 UTC",
                                   "hours_per_day": 24, "gap_fill": False}
        return envelope

    def index(self):
        return self._get("public/get_index_price", index_name="btc_usd")

    def book(self, name):
        name = _identifier(name)
        return _book(self._get("public/get_order_book", instrument_name=name, depth=5), name)

    def close(self):
        self.session.close()


class DeribitTestnetClient:
    def __init__(self, root):
        self.root = Path(root)
        self.credentials_path = self.root / ".env"
        self.session = _session()
        self._token = None
        self._token_until = 0
        self._auth_info = None
        self._auth_generation = 0
        self._account_auth_generation = None
        self._request_id = 0
        self._instruments = {}
        self._instruments_at = 0

    @property
    def configured(self):
        try:
            self._credentials()
            return True
        except TestnetError:
            return False

    def _credentials(self):
        try:
            fields = read_secrets(self.root, TESTNET_FIELDS)
        except ConfigurationError:
            raise TestnetError("本机 .env 格式或权限无效；testnet 凭据未启用", "credentials_invalid") from None
        if set(fields) != TESTNET_FIELDS:
            raise TestnetError("缺少 .env 中的 DERIBIT_TESTNET_CLIENT_ID 或 DERIBIT_TESTNET_CLIENT_SECRET", "credentials_missing")
        if any(len(value) > 2048 or any(char.isspace() for char in value) for value in fields.values()):
            raise TestnetError("本机 .env 中的 testnet 凭据格式无效", "credentials_invalid")
        return {"client_id": fields["DERIBIT_TESTNET_CLIENT_ID"],
                "client_secret": fields["DERIBIT_TESTNET_CLIENT_SECRET"]}

    def _rpc(self, method, params, *, validity_deadline=None, preflight=None):
        if method not in PUBLIC_METHODS | READ_METHODS | WRITE_METHODS | {"public/auth"}:
            raise TestnetError("拒绝非白名单 testnet 接口", "permission_denied")
        write = method in WRITE_METHODS
        if validity_deadline is not None and (not _number(validity_deadline) or time.time() >= validity_deadline):
            raise TestnetError("下单依据已超过有效期，未发送交易请求", "stale")
        if write and (self.root / "STOP").exists():
            raise TestnetError("STOP 文件存在，禁止交易写请求", "stopped")
        headers = {}
        if method.startswith("private/"):
            if not self._token or time.time() >= self._token_until:
                self.authenticate()
            if write and self._account_auth_generation != self._auth_generation:
                raise TestnetError("认证身份已更新，需先重新核对真实账户", "account_reconciliation_required")
            headers["Authorization"] = "Bearer " + self._token
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        # Recheck after authentication and immediately before any trading write.
        if write and preflight is not None:
            preflight()
        if write and (self.root / "STOP").exists():
            raise TestnetError("STOP 文件存在，禁止交易写请求", "stopped")
        if write and validity_deadline is not None and time.time() >= validity_deadline:
            raise TestnetError("认证或校验期间下单依据过期，未发送交易请求", "stale")
        try:
            response = self.session.post(TESTNET_URL + method, json=payload, headers=headers,
                                         timeout=(3.05, 10), allow_redirects=False)
        except requests.RequestException:
            raise TestnetError("testnet 连接失败；写请求结果需对账" if write else "testnet 连接失败",
                               "network_error", uncertain=write) from None
        return _response(response, testnet=True, received=time.time(), request_id=request_id, write=write)

    def authenticate(self):
        self._token = None
        self._token_until = 0
        self._account_auth_generation = None
        credentials = self._credentials()
        result = self._rpc("public/auth", {"grant_type": "client_credentials", **credentials,
                           "scope": AUTH_SCOPE})["result"]
        del credentials
        if not isinstance(result, dict):
            raise TestnetError("testnet 认证响应无效", "authentication_failed")
        scopes = result.get("scope", "").split() if isinstance(result.get("scope"), str) else []
        # Scope is the server's granted capability set. Explicit denial entries
        # may be omitted by the server (verified on testnet); never interpret an
        # absent positive grant as access. Ask to narrow every functional area,
        # then reject unexpected grants rather than trusting the requested scope.
        # https://docs.deribit.com/articles/access-scope
        permissions = {}
        allowed_metadata = {"name", "session", "expires", "ip"}
        valid_scopes = True
        for scope in scopes:
            if scope in {"connection", "mainaccount"}:
                continue
            area, separator, access = scope.partition(":")
            if not separator or not access:
                valid_scopes = False
            elif area not in allowed_metadata:
                if area in permissions:
                    valid_scopes = False
                permissions[area] = access
        denied = {"wallet", "block_trade", "block_rfq", "custody"}
        if any(area not in {"account", "trade"} | denied for area in permissions):
            valid_scopes = False
        token = result.get("access_token")
        lifetime = result.get("expires_in")
        if (not isinstance(token, str) or not token or result.get("token_type") != "bearer"
                or not _number(lifetime) or lifetime <= 30 or "trade:read_write" not in scopes
                or not valid_scopes or permissions.get("account") != "read"
                or permissions.get("trade") != "read_write"
                or any(permissions.get(area, "none") != "none" for area in denied)):
            raise TestnetError("testnet 认证权限或令牌期限不符合限制", "authentication_failed")
        self._token = token
        self._auth_generation += 1
        self._token_until = time.time() + min(lifetime, 3600) - 30
        self._auth_info = {"environment": "testnet", "scopes": ["account:read", "trade:read_write"],
                           "denied_scopes": sorted(denied),
                           "authenticated": True, "expires_at": self._token_until}
        return dict(self._auth_info)

    def get_instruments(self):
        envelope = self._rpc("public/get_instruments", {"currency": "BTC", "kind": "option", "expired": False})
        result = envelope["result"]
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise TestnetError("testnet 合约目录无效", "invalid_data")
        self._instruments = {row.get("instrument_name"): row for row in result if isinstance(row.get("instrument_name"), str)}
        self._instruments_at = envelope["received_at"]
        return result

    def get_order_book(self, name):
        name = _identifier(name)
        return _book(self._rpc("public/get_order_book", {"instrument_name": name, "depth": 5}), name)

    def _trades(self, start, end, historical):
        rows = {}
        cursor = start
        for _ in range(MAX_PAGES):
            page = self._rpc("private/get_user_trades_by_currency_and_time", {
                "currency": "BTC", "start_timestamp": cursor, "end_timestamp": end,
                "count": PAGE_SIZE, "sorting": "asc", "historical": historical})["result"]
            if not isinstance(page, dict) or not isinstance(page.get("trades"), list) or not isinstance(page.get("has_more"), bool):
                raise TestnetError("成交分页结构无效", "reconciliation_incomplete")
            timestamps = []
            for row in page["trades"]:
                if (not isinstance(row, dict) or not isinstance(row.get("trade_id"), str)
                        or not _number(row.get("timestamp")) or not cursor <= row["timestamp"] <= end):
                    raise TestnetError("成交记录身份或时间无效", "reconciliation_incomplete")
                timestamps.append(row["timestamp"])
                rows[row["trade_id"]] = row
            if timestamps != sorted(timestamps):
                raise TestnetError("成交分页未按时间排序", "reconciliation_incomplete")
            if not page["has_more"]:
                return list(rows.values())
            # Overlap at the last millisecond so simultaneous fills cannot be lost.
            if not timestamps or timestamps[-1] <= cursor:
                raise TestnetError("成交分页无法无遗漏推进", "reconciliation_incomplete")
            cursor = int(timestamps[-1])
        raise TestnetError("成交分页超过安全上限", "reconciliation_incomplete")

    def _orders(self, historical):
        # The live API explicitly rejects include_unfilled=true together with
        # historical=true (-32602). Recent queries cover unfilled cancellations;
        # historical queries retain older fills. An old missing unfilled intent
        # is consequently unresolved, never evidence of a safe-to-retry order.
        rows = {}
        offset = 0
        for _ in range(MAX_PAGES):
            page = self._rpc("private/get_order_history_by_currency", {"currency": "BTC", "count": PAGE_SIZE,
                "offset": offset, "include_old": True, "include_unfilled": not historical, "historical": historical})["result"]
            if not isinstance(page, list):
                raise TestnetError("历史订单分页结构无效", "reconciliation_incomplete")
            added = 0
            for row in page:
                if not isinstance(row, dict) or not isinstance(row.get("order_id"), str):
                    raise TestnetError("历史订单身份无效", "reconciliation_incomplete")
                added += row["order_id"] not in rows
                rows[row["order_id"]] = row
            if len(page) < PAGE_SIZE:
                return list(rows.values())
            if not added:
                raise TestnetError("历史订单分页未推进", "reconciliation_incomplete")
            offset += len(page)
        raise TestnetError("历史订单分页超过安全上限", "reconciliation_incomplete")

    def account_snapshot(self, since_ms=None):
        self._account_auth_generation = None
        started = time.time()
        start = int((started - 86400) * 1000) if since_ms is None else since_ms
        if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= started * 1000:
            raise TestnetError("对账起始 UTC 时间无效", "invalid_data")
        summary_env = self._rpc("private/get_account_summary", {"currency": "BTC", "extended": True})
        auth_generation = self._auth_generation
        summary = summary_env["result"]
        if (not isinstance(summary, dict) or summary.get("currency") != "BTC"
                or not isinstance(summary.get("id"), int) or isinstance(summary.get("id"), bool)
                or not _number(summary.get("equity")) or not _number(summary.get("available_funds"))):
            raise TestnetError("testnet BTC 账户身份或金额未核实", "invalid_account")
        positions = self._rpc("private/get_positions", {"currency": "BTC"})["result"]
        open_orders = self._rpc("private/get_open_orders_by_currency", {"currency": "BTC"})["result"]
        if any(not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
               for rows in (positions, open_orders)):
            raise TestnetError("testnet 持仓或挂单结构无效", "reconciliation_incomplete")
        end = int(time.time() * 1000)
        trades = {}
        orders = {}
        # Recent and historical are disjoint databases. Query both even for a
        # short requested range; indexing delays never prove a missing order absent.
        for historical in (True, False):
            for row in self._trades(start, end, historical):
                trades[row["trade_id"]] = row
            for row in self._orders(historical):
                orders[row["order_id"]] = row
        observed = time.time()
        if observed - started > 15:
            raise TestnetError("完整账户对账耗时超过 15 秒，禁止使用旧快照", "stale")
        if self._auth_generation != auth_generation:
            raise TestnetError("对账期间认证身份变化，需重新核对账户", "account_reconciliation_required")
        self._account_auth_generation = auth_generation
        # Strip personal profile fields; retain monetary/fee source fields needed
        # by deterministic accounting. No token or credential ever leaves auth.
        safe_fields = {"id", "currency", "equity", "balance", "available_funds", "margin_balance",
                       "initial_margin", "maintenance_margin", "fees", "fee_group", "fee_balance",
                       "affiliate_promotion_fee", "cross_collateral_enabled", "portfolio_margining_enabled",
                       "margin_model", "type", "creation_timestamp"}
        return {"environment": "testnet", "summary": {key: value for key, value in summary.items() if key in safe_fields},
                "account_id": str(summary["id"]), "positions": positions, "open_orders": open_orders,
                "trades": sorted(trades.values(), key=lambda row: (row["timestamp"], row["trade_id"])),
                "orders": list(orders.values()), "observed_at": observed, "started_at": started,
                "source_at": summary_env["source_at"], "since_ms": start, "through_ms": end,
                "complete": True, "historical_indexing_may_lag": True,
                "historical_unfilled_orders_available": False}

    def _order_params(self, instrument, amount, price, label):
        if (self.root / "STOP").exists():
            raise TestnetError("STOP 文件存在，禁止交易写请求", "stopped")
        instrument = _identifier(instrument)
        label = _identifier(label)
        if time.time() - self._instruments_at > 300:
            self.get_instruments()
        meta = self._instruments.get(instrument)
        required = {"kind": "option", "option_type": "call", "instrument_type": "reversed",
                    "base_currency": "BTC", "quote_currency": "BTC", "settlement_currency": "BTC",
                    "counter_currency": "USD", "price_index": "btc_usd", "state": "open"}
        if (not isinstance(meta, dict) or any(meta.get(key) != value for key, value in required.items())
                or meta.get("is_active") is not True or _decimal(meta.get("contract_size")) != 1
                or _decimal(meta.get("expiration_timestamp")) / 1000 <= Decimal(str(time.time()))):
            raise TestnetError("只允许已核对的有效 BTC inverse Call", "permission_denied")
        amount, price = _decimal(amount), _decimal(price)
        step, tick = _decimal(meta.get("min_trade_amount")), _decimal(meta.get("tick_size"))
        tiers = meta.get("tick_size_steps")
        if not isinstance(tiers, list):
            raise TestnetError("合约价格步长未知", "invalid_data")
        for tier in tiers:
            if not isinstance(tier, dict):
                raise TestnetError("合约价格步长无效", "invalid_data")
            if price >= _decimal(tier.get("above_price")):
                tick = max(tick, _decimal(tier.get("tick_size")))
        if step <= 0 or tick <= 0 or amount <= 0 or price <= 0 or amount % step or price % tick:
            raise TestnetError("下单数量或价格不符合已核对步长", "invalid_data")
        return {"instrument_name": instrument, "amount": float(amount), "price": float(price),
                "label": label, "type": "limit", "time_in_force": "good_til_cancelled"}

    def buy(self, instrument, amount, price, label, *, validity_deadline=None, preflight=None):
        params = self._order_params(instrument, amount, price, label)
        params["reduce_only"] = False
        return self._rpc("private/buy", params, validity_deadline=validity_deadline, preflight=preflight)["result"]

    def sell(self, instrument, amount, price, label, reduce_only=True, *, validity_deadline=None, preflight=None):
        if reduce_only is not True:
            raise TestnetError("只允许 reduce_only 卖出", "permission_denied")
        params = self._order_params(instrument, amount, price, label)
        params["reduce_only"] = True
        return self._rpc("private/sell", params, validity_deadline=validity_deadline, preflight=preflight)["result"]

    def cancel(self, order_id, *, preflight=None):
        return self._rpc("private/cancel", {"order_id": _identifier(order_id)}, preflight=preflight)["result"]

    def get_order_state(self, order_id):
        return self._rpc("private/get_order_state", {"order_id": _identifier(order_id)})["result"]

    def orders_by_label(self, label):
        return self._rpc("private/get_order_state_by_label", {"currency": "BTC", "label": _identifier(label)})["result"]

    def close(self):
        self._token = None
        self._token_until = 0
        self._account_auth_generation = None
        self.session.close()


def fee_rate(meta, summary):
    """BTC per BTC option amount, per side, ignoring fee caps and discounts.

    Deribit extended account fees are optional when no discounts apply. Relative
    fees multiply the base instrument fee; fixed fees replace it. Taking their
    maximum with the base rate reserves more, never less. Extra fee models fail.
    """
    if not isinstance(meta, dict) or not isinstance(summary, dict) or summary.get("currency") != "BTC":
        raise TestnetError("费用来源或单位未知", "fees_unknown")
    if summary.get("cross_collateral_enabled") is not False:
        raise TestnetError("跨币保证金账户的 BTC 预算口径未核实", "fees_unknown")
    if _decimal(summary.get("affiliate_promotion_fee", 0)) != 0:
        raise TestnetError("账户附加费用口径未知", "fees_unknown")
    base = {side: _decimal(meta.get(side + "_commission")) for side in ("maker", "taker")}
    rates = [Decimal(0), *base.values()]
    fees = summary.get("fees")
    if fees is not None and fees != {}:
        try:
            default = fees["btc_usd"]["option"]["default"]
            kind = default["type"]
            if kind not in {"relative", "fixed"}:
                raise ValueError
            for side in ("maker", "taker"):
                account = _decimal(default[side])
                if kind == "relative" and account < 0:
                    raise ValueError
                rates.append(account * base[side] if kind == "relative" else account)
        except (KeyError, TypeError, ValueError):
            raise TestnetError("账户费用模型未知", "fees_unknown") from None
    rate = max(rates)
    if rate <= 0 or rate > Decimal("0.1"):
        raise TestnetError("费用上界无效", "fees_unknown")
    return rate

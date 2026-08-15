from __future__ import annotations

import gzip
import json
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from http.client import HTTPException, HTTPSConnection
from typing import Protocol

DERIBIT_COMBO_HOST = "test.deribit.com"
DERIBIT_COMBO_AUTH_SCOPE = "trade:read_write"
DERIBIT_COMBO_METHOD_ALLOWLIST = frozenset(
    {
        "public/auth",
        "public/get_combos",
        "public/get_instrument",
        "public/get_order_book",
        "private/get_positions",
        "private/buy",
        "private/sell",
        "private/get_order_state",
        "private/get_user_trades_by_order",
        "private/cancel",
    }
)

_ORDER_STATES = frozenset({"open", "filled", "rejected", "cancelled", "untriggered", "triggered"})
_COMBO_KINDS = frozenset({"future_combo", "option_combo"})
_EXPIRY_MARGIN_MS = 60_000
_MAX_COMBO_CANDIDATES = 12


class DeribitComboError(RuntimeError):
    """Credential-free Testnet transport, protocol, or lifecycle failure."""

    def __init__(self, code: str, *, exchange_code: int | None = None) -> None:
        if not code or not code.replace("_", "").isalnum() or code != code.upper():
            raise ValueError("combo error code must be uppercase identifier text")
        if exchange_code is not None and (
            isinstance(exchange_code, bool) or not isinstance(exchange_code, int)
        ):
            raise ValueError("exchange error code must be an integer")
        self.code = code
        self.exchange_code = exchange_code
        super().__init__(code)


@dataclass(frozen=True)
class ComboAuthGrant:
    access_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.access_token:
            raise ValueError("access token must be non-empty")


class ComboTransport(Protocol):
    def authenticate(self, *, client_id: str, client_secret: str) -> ComboAuthGrant: ...

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        grant: ComboAuthGrant | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class ComboLifecycleReceipt:
    status: str
    outcome: str
    combo_id: str | None = None
    entry_order_id: str | None = None
    entry_order_state: str | None = None
    entry_filled_amount: Decimal | None = None
    entry_trade_amount: Decimal | None = None
    entry_fee_totals: tuple[tuple[str, Decimal], ...] = ()
    cancel_attempted: bool = False
    exit_order_id: str | None = None
    exit_order_state: str | None = None
    exit_filled_amount: Decimal | None = None
    exit_fee_totals: tuple[tuple[str, Decimal], ...] = ()
    reduce_only_exit: str = "UNVERIFIED"
    positions_reconciled: bool | None = None
    blockers: tuple[str, ...] = ()
    exchange_error_code: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"COMPLETE", "BLOCKED"}:
            raise ValueError("receipt status is invalid")
        if self.status == "COMPLETE" and self.blockers:
            raise ValueError("complete receipt cannot contain blockers")

    def as_safe_object(self) -> dict[str, object]:
        return {
            "mode": "TESTNET COMBO LIFECYCLE",
            "environment": "TESTNET",
            "permission": "PRIVATE_EXECUTION",
            "capital": "NO_REAL_CAPITAL",
            "status": self.status,
            "outcome": self.outcome,
            "combo_id": self.combo_id,
            "entry_order_id": self.entry_order_id,
            "entry_order_state": self.entry_order_state,
            "entry_filled_amount": _decimal_text_or_none(self.entry_filled_amount),
            "entry_trade_amount": _decimal_text_or_none(self.entry_trade_amount),
            "actual_entry_fees": _fee_object(self.entry_fee_totals),
            "cancel_attempted": self.cancel_attempted,
            "exit_order_id": self.exit_order_id,
            "exit_order_state": self.exit_order_state,
            "exit_filled_amount": _decimal_text_or_none(self.exit_filled_amount),
            "actual_exit_fees": _fee_object(self.exit_fee_totals),
            "reduce_only_exit": self.reduce_only_exit,
            "positions_reconciled": self.positions_reconciled,
            "blockers": list(self.blockers),
            "exchange_error_code": self.exchange_error_code,
        }


@dataclass(frozen=True)
class _ComboCandidate:
    combo_id: str
    legs: tuple[str, ...]
    direction: str
    amount: Decimal
    amount_parameter: int | float
    price_parameter: int | float


@dataclass(frozen=True)
class _OrderFact:
    order_id: str
    instrument_name: str
    direction: str
    state: str
    amount: Decimal
    filled_amount: Decimal
    post_only: bool
    reduce_only: bool


@dataclass(frozen=True)
class _TradeFacts:
    amount: Decimal
    fees: tuple[tuple[str, Decimal], ...]


PositionSignature = tuple[tuple[str, str, str, Decimal], ...]


class DeribitComboHttpClient:
    """Fixed-host Testnet JSON-RPC client for the exact C2 method surface."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.timeout_seconds = timeout_seconds
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._next_request_id = 1
        self._request_id_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(environment='TESTNET')"

    def authenticate(self, *, client_id: str, client_secret: str) -> ComboAuthGrant:
        if not isinstance(client_id, str) or not client_id:
            raise DeribitComboError("CREDENTIALS_NOT_PROVIDED")
        if not isinstance(client_secret, str) or not client_secret:
            raise DeribitComboError("CREDENTIALS_NOT_PROVIDED")
        result = _mapping(
            self.call(
                "public/auth",
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": DERIBIT_COMBO_AUTH_SCOPE,
                },
            ),
            "AUTH_PAYLOAD_INVALID",
        )
        token = result.get("access_token")
        if not isinstance(token, str) or not token or result.get("token_type") != "bearer":
            raise DeribitComboError("AUTH_PAYLOAD_INVALID")
        expires_in = result.get("expires_in")
        if isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0:
            raise DeribitComboError("AUTH_PAYLOAD_INVALID")
        return ComboAuthGrant(access_token=token)

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        grant: ComboAuthGrant | None = None,
    ) -> object:
        _validate_call(method, params, grant=grant)
        with self._request_id_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Connection": "close",
            "Content-Type": "application/json",
            "User-Agent": "optimatrix-btc-0dte/0.1",
        }
        if grant is not None:
            headers["Authorization"] = f"Bearer {grant.access_token}"
        connection = HTTPSConnection(DERIBIT_COMBO_HOST, timeout=self.timeout_seconds)
        self._monotonic_ns()
        try:
            connection.request("POST", f"/api/v2/{method}", body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            if response.status != 200:
                raise DeribitComboError(f"{_method_prefix(method)}_HTTP_ERROR")
            encoding = response.getheader("Content-Encoding")
            if encoding == "gzip":
                response_body = gzip.decompress(response_body)
            elif encoding not in (None, "", "identity"):
                raise DeribitComboError(f"{_method_prefix(method)}_ENCODING_UNKNOWN")
            payload = json.loads(response_body.decode("utf-8"))
        except DeribitComboError:
            raise
        except (
            OSError,
            EOFError,
            HTTPException,
            UnicodeDecodeError,
            gzip.BadGzipFile,
            json.JSONDecodeError,
        ):
            raise DeribitComboError(f"{_method_prefix(method)}_TRANSPORT_UNKNOWN") from None
        finally:
            connection.close()
        self._monotonic_ns()
        envelope = _mapping(payload, f"{_method_prefix(method)}_PAYLOAD_INVALID")
        if envelope.get("jsonrpc") != "2.0" or envelope.get("id") != request_id:
            raise DeribitComboError(f"{_method_prefix(method)}_PAYLOAD_INVALID")
        if envelope.get("testnet") is not True:
            raise DeribitComboError("ENVIRONMENT_MISMATCH")
        if "error" in envelope:
            error = _mapping(envelope["error"], f"{_method_prefix(method)}_PAYLOAD_INVALID")
            exchange_code = error.get("code")
            if isinstance(exchange_code, bool) or not isinstance(exchange_code, int):
                exchange_code = None
            raise DeribitComboError(
                f"{_method_prefix(method)}_RPC_REJECTED",
                exchange_code=exchange_code,
            )
        if "result" not in envelope:
            raise DeribitComboError(f"{_method_prefix(method)}_PAYLOAD_INVALID")
        return envelope["result"]


def run_testnet_combo_lifecycle(
    *,
    transport: ComboTransport,
    client_id: str,
    client_secret: str,
    now_ms: int,
    label: str,
) -> ComboLifecycleReceipt:
    """Execute at most one passive Testnet entry and its bounded cleanup or exit."""

    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise ValueError("now_ms must be a positive integer")
    _validate_label(label)
    try:
        grant = transport.authenticate(client_id=client_id, client_secret=client_secret)
        baseline = _positions(
            transport.call("private/get_positions", {"currency": "BTC"}, grant=grant)
        )
        candidate = _select_candidate(transport, grant=grant, baseline=baseline, now_ms=now_ms)
    except DeribitComboError as exc:
        return _pre_order_failure(exc)
    if candidate is None:
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="NO_SUITABLE_ACTIVE_COMBO",
            blockers=("NO_SUITABLE_ACTIVE_COMBO",),
        )

    entry_params: dict[str, object] = {
        "instrument_name": candidate.combo_id,
        "amount": candidate.amount_parameter,
        "type": "limit",
        "price": candidate.price_parameter,
        "time_in_force": "good_til_cancelled",
        "post_only": True,
        "reject_post_only": True,
        "reduce_only": False,
        "label": label,
    }
    entry_method = f"private/{candidate.direction}"
    try:
        submitted = _mapping(
            transport.call(entry_method, entry_params, grant=grant),
            "ENTRY_ORDER_PAYLOAD_INVALID",
        )
        submitted_order = _order(
            _mapping(submitted.get("order"), "ENTRY_ORDER_PAYLOAD_INVALID"),
            "ENTRY_ORDER_PAYLOAD_INVALID",
        )
    except DeribitComboError as exc:
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="ENTRY_ORDER_NOT_ACCEPTED",
            combo_id=candidate.combo_id,
            blockers=(exc.code,),
            exchange_error_code=exc.exchange_code,
        )

    order_id = submitted_order.order_id
    cancel_attempted = False
    cancel_error: DeribitComboError | None = None
    try:
        entry_order, entry_trades, current_positions = _order_snapshot(
            transport,
            grant=grant,
            order_id=order_id,
        )
    except DeribitComboError as exc:
        cleanup_error = _attempt_cancel(transport, grant=grant, order_id=order_id)
        blockers = [exc.code]
        if cleanup_error is not None:
            blockers.append(cleanup_error.code)
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="ENTRY_RECONCILIATION_FAILED",
            combo_id=candidate.combo_id,
            entry_order_id=order_id,
            cancel_attempted=True,
            blockers=_unique(blockers),
            exchange_error_code=_exchange_code(exc, cleanup_error),
        )

    if entry_order.state == "open":
        cancel_attempted = True
        cancel_error = _attempt_cancel(transport, grant=grant, order_id=order_id)
        try:
            entry_order, entry_trades, current_positions = _order_snapshot(
                transport,
                grant=grant,
                order_id=order_id,
            )
        except DeribitComboError as exc:
            blockers = [exc.code]
            if cancel_error is not None:
                blockers.append(cancel_error.code)
            return ComboLifecycleReceipt(
                status="BLOCKED",
                outcome="ENTRY_CLEANUP_UNVERIFIED",
                combo_id=candidate.combo_id,
                entry_order_id=order_id,
                cancel_attempted=True,
                blockers=_unique(blockers),
                exchange_error_code=_exchange_code(exc, cancel_error),
            )

    blockers = _entry_blockers(entry_order, entry_trades, candidate)
    if entry_order.state == "open" and cancel_error is not None:
        blockers.append(cancel_error.code)
    if entry_order.state == "open":
        blockers.append("ENTRY_REMAINDER_STILL_OPEN")

    positions_match = current_positions == baseline
    if entry_order.filled_amount == 0:
        if entry_order.state != "cancelled":
            blockers.append("NO_FILL_FINAL_STATE_NOT_CANCELLED")
        if not cancel_attempted:
            blockers.append("NO_FILL_CANCEL_NOT_ATTEMPTED")
        if entry_trades.amount != 0:
            blockers.append("NO_FILL_HAS_TRADES")
        if not positions_match:
            blockers.append("NO_FILL_POSITION_MISMATCH")
        blockers = list(_unique(blockers))
        return ComboLifecycleReceipt(
            status="BLOCKED" if blockers else "COMPLETE",
            outcome="NO_FILL_CANCELLED" if not blockers else "NO_FILL_CLEANUP_INCOMPLETE",
            combo_id=candidate.combo_id,
            entry_order_id=order_id,
            entry_order_state=entry_order.state,
            entry_filled_amount=entry_order.filled_amount,
            entry_trade_amount=entry_trades.amount,
            entry_fee_totals=entry_trades.fees,
            cancel_attempted=cancel_attempted,
            reduce_only_exit="NOT_APPLICABLE_NO_FILL",
            positions_reconciled=positions_match,
            blockers=tuple(blockers),
            exchange_error_code=cancel_error.exchange_code if cancel_error is not None else None,
        )

    if entry_order.state not in {"filled", "cancelled"}:
        blockers.append("FILLED_ENTRY_REMAINDER_NOT_CLOSED")
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="ENTRY_CLEANUP_INCOMPLETE",
            combo_id=candidate.combo_id,
            entry_order_id=order_id,
            entry_order_state=entry_order.state,
            entry_filled_amount=entry_order.filled_amount,
            entry_trade_amount=entry_trades.amount,
            entry_fee_totals=entry_trades.fees,
            cancel_attempted=cancel_attempted,
            reduce_only_exit="UNVERIFIED",
            positions_reconciled=positions_match,
            blockers=_unique(blockers),
            exchange_error_code=cancel_error.exchange_code if cancel_error is not None else None,
        )

    exit_direction = "sell" if candidate.direction == "buy" else "buy"
    exit_label = f"{label[:59]}-exit"
    exit_params: dict[str, object] = {
        "instrument_name": candidate.combo_id,
        "amount": _json_number(entry_order.filled_amount),
        "type": "market",
        "post_only": False,
        "reduce_only": True,
        "label": exit_label,
    }
    try:
        exit_submitted = _mapping(
            transport.call(f"private/{exit_direction}", exit_params, grant=grant),
            "EXIT_ORDER_PAYLOAD_INVALID",
        )
        exit_order_id = _order(
            _mapping(exit_submitted.get("order"), "EXIT_ORDER_PAYLOAD_INVALID"),
            "EXIT_ORDER_PAYLOAD_INVALID",
        ).order_id
    except DeribitComboError as exc:
        blockers.append(exc.code)
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="REDUCE_ONLY_EXIT_REJECTED",
            combo_id=candidate.combo_id,
            entry_order_id=order_id,
            entry_order_state=entry_order.state,
            entry_filled_amount=entry_order.filled_amount,
            entry_trade_amount=entry_trades.amount,
            entry_fee_totals=entry_trades.fees,
            cancel_attempted=cancel_attempted,
            reduce_only_exit="REJECTED",
            positions_reconciled=False,
            blockers=_unique(blockers),
            exchange_error_code=exc.exchange_code,
        )

    try:
        exit_order, exit_trades, final_positions = _order_snapshot(
            transport,
            grant=grant,
            order_id=exit_order_id,
        )
    except DeribitComboError as exc:
        blockers.append(exc.code)
        return ComboLifecycleReceipt(
            status="BLOCKED",
            outcome="REDUCE_ONLY_EXIT_UNVERIFIED",
            combo_id=candidate.combo_id,
            entry_order_id=order_id,
            entry_order_state=entry_order.state,
            entry_filled_amount=entry_order.filled_amount,
            entry_trade_amount=entry_trades.amount,
            entry_fee_totals=entry_trades.fees,
            cancel_attempted=cancel_attempted,
            exit_order_id=exit_order_id,
            reduce_only_exit="UNVERIFIED",
            positions_reconciled=None,
            blockers=_unique(blockers),
            exchange_error_code=exc.exchange_code,
        )

    blockers.extend(
        _exit_blockers(
            exit_order,
            exit_trades,
            combo_id=candidate.combo_id,
            direction=exit_direction,
            expected_amount=entry_order.filled_amount,
        )
    )
    final_match = final_positions == baseline
    if not final_match:
        blockers.append("FINAL_POSITION_MISMATCH")
    blockers = list(_unique(blockers))
    return ComboLifecycleReceipt(
        status="BLOCKED" if blockers else "COMPLETE",
        outcome="NATURAL_FILL_EXITED" if not blockers else "REDUCE_ONLY_EXIT_INCOMPLETE",
        combo_id=candidate.combo_id,
        entry_order_id=order_id,
        entry_order_state=entry_order.state,
        entry_filled_amount=entry_order.filled_amount,
        entry_trade_amount=entry_trades.amount,
        entry_fee_totals=entry_trades.fees,
        cancel_attempted=cancel_attempted,
        exit_order_id=exit_order_id,
        exit_order_state=exit_order.state,
        exit_filled_amount=exit_order.filled_amount,
        exit_fee_totals=exit_trades.fees,
        reduce_only_exit="COMPLETE" if not blockers else "INCOMPLETE",
        positions_reconciled=final_match,
        blockers=tuple(blockers),
    )


def _select_candidate(
    transport: ComboTransport,
    *,
    grant: ComboAuthGrant,
    baseline: PositionSignature,
    now_ms: int,
) -> _ComboCandidate | None:
    del grant
    combos = _sequence(
        transport.call("public/get_combos", {"currency": "BTC"}),
        "COMBO_LIST_PAYLOAD_INVALID",
    )
    active: list[tuple[str, tuple[str, ...]]] = []
    for raw_combo in combos:
        try:
            combo = _mapping(raw_combo, "COMBO_PAYLOAD_INVALID")
            combo_id = _text(combo.get("id"), "COMBO_PAYLOAD_INVALID")
            if combo.get("state") != "active":
                continue
            legs_raw = _sequence(combo.get("legs"), "COMBO_PAYLOAD_INVALID")
            parsed_legs: list[str] = []
            for raw_leg in legs_raw:
                leg = _mapping(raw_leg, "COMBO_PAYLOAD_INVALID")
                leg_name = _text(leg.get("instrument_name"), "COMBO_PAYLOAD_INVALID")
                if _decimal(leg.get("amount"), "COMBO_PAYLOAD_INVALID") == 0:
                    raise DeribitComboError("COMBO_PAYLOAD_INVALID")
                parsed_legs.append(leg_name)
            if len(parsed_legs) < 2 or len(set(parsed_legs)) != len(parsed_legs):
                continue
            active.append((combo_id, tuple(parsed_legs)))
        except DeribitComboError:
            continue
    occupied = {item[0] for item in baseline if item[3] != 0}
    for combo_id, legs in sorted(active)[:_MAX_COMBO_CANDIDATES]:
        if occupied.intersection((combo_id, *legs)):
            continue
        try:
            instrument = _mapping(
                transport.call("public/get_instrument", {"instrument_name": combo_id}),
                "INSTRUMENT_PAYLOAD_INVALID",
            )
            if (
                instrument.get("instrument_name") != combo_id
                or instrument.get("kind") not in _COMBO_KINDS
                or instrument.get("base_currency") != "BTC"
                or instrument.get("is_active") is not True
                or instrument.get("state") != "open"
            ):
                continue
            expiry = instrument.get("expiration_timestamp")
            if isinstance(expiry, bool) or not isinstance(expiry, int):
                continue
            if expiry <= now_ms + _EXPIRY_MARGIN_MS:
                continue
            amount_raw = instrument.get("min_trade_amount")
            amount = _decimal(amount_raw, "INSTRUMENT_PAYLOAD_INVALID")
            tick = _decimal(instrument.get("tick_size"), "INSTRUMENT_PAYLOAD_INVALID")
            if amount <= 0 or tick <= 0:
                continue
            book = _mapping(
                transport.call(
                    "public/get_order_book",
                    {"instrument_name": combo_id, "depth": 1},
                ),
                "ORDER_BOOK_PAYLOAD_INVALID",
            )
            if book.get("state") != "open" or book.get("instrument_name") != combo_id:
                continue
            side = _book_side(book.get("bids"), "buy")
            if side is None:
                side = _book_side(book.get("asks"), "sell")
            if side is None:
                continue
            direction, price_parameter = side
            return _ComboCandidate(
                combo_id=combo_id,
                legs=legs,
                direction=direction,
                amount=amount,
                amount_parameter=_json_primitive_number(amount_raw, "INSTRUMENT_PAYLOAD_INVALID"),
                price_parameter=price_parameter,
            )
        except DeribitComboError as exc:
            if exc.code.endswith("_PAYLOAD_INVALID"):
                continue
            raise
    return None


def _book_side(value: object, direction: str) -> tuple[str, int | float] | None:
    levels = _sequence(value, "ORDER_BOOK_PAYLOAD_INVALID")
    if not levels:
        return None
    level = _sequence(levels[0], "ORDER_BOOK_PAYLOAD_INVALID")
    if len(level) < 2:
        raise DeribitComboError("ORDER_BOOK_PAYLOAD_INVALID")
    price = _json_primitive_number(level[0], "ORDER_BOOK_PAYLOAD_INVALID")
    amount = _decimal(level[1], "ORDER_BOOK_PAYLOAD_INVALID")
    if amount <= 0:
        raise DeribitComboError("ORDER_BOOK_PAYLOAD_INVALID")
    return direction, price


def _order_snapshot(
    transport: ComboTransport,
    *,
    grant: ComboAuthGrant,
    order_id: str,
) -> tuple[_OrderFact, _TradeFacts, PositionSignature]:
    order = _order(
        _mapping(
            transport.call(
                "private/get_order_state",
                {"order_id": order_id},
                grant=grant,
            ),
            "ORDER_STATE_PAYLOAD_INVALID",
        ),
        "ORDER_STATE_PAYLOAD_INVALID",
    )
    trades = _trades(
        transport.call(
            "private/get_user_trades_by_order",
            {"order_id": order_id, "sorting": "default", "historical": False},
            grant=grant,
        ),
        order_id=order_id,
    )
    positions = _positions(
        transport.call("private/get_positions", {"currency": "BTC"}, grant=grant)
    )
    return order, trades, positions


def _attempt_cancel(
    transport: ComboTransport,
    *,
    grant: ComboAuthGrant,
    order_id: str,
) -> DeribitComboError | None:
    try:
        transport.call("private/cancel", {"order_id": order_id}, grant=grant)
    except DeribitComboError as exc:
        return exc
    return None


def _entry_blockers(
    order: _OrderFact,
    trades: _TradeFacts,
    candidate: _ComboCandidate,
) -> list[str]:
    blockers: list[str] = []
    if order.instrument_name != candidate.combo_id:
        blockers.append("ENTRY_INSTRUMENT_MISMATCH")
    if order.direction != candidate.direction:
        blockers.append("ENTRY_DIRECTION_MISMATCH")
    if order.amount != candidate.amount:
        blockers.append("ENTRY_AMOUNT_MISMATCH")
    if order.reduce_only:
        blockers.append("ENTRY_REDUCE_ONLY_MISMATCH")
    if not order.post_only:
        blockers.append("ENTRY_POST_ONLY_MISMATCH")
    if order.filled_amount > order.amount:
        blockers.append("ENTRY_FILLED_AMOUNT_INVALID")
    if trades.amount != order.filled_amount:
        blockers.append("ENTRY_TRADE_AMOUNT_MISMATCH")
    if order.state in {"rejected", "untriggered", "triggered"}:
        blockers.append("ENTRY_FINAL_STATE_INVALID")
    return blockers


def _exit_blockers(
    order: _OrderFact,
    trades: _TradeFacts,
    *,
    combo_id: str,
    direction: str,
    expected_amount: Decimal,
) -> list[str]:
    blockers: list[str] = []
    if order.instrument_name != combo_id:
        blockers.append("EXIT_INSTRUMENT_MISMATCH")
    if order.direction != direction:
        blockers.append("EXIT_DIRECTION_MISMATCH")
    if order.amount != expected_amount or order.filled_amount != expected_amount:
        blockers.append("EXIT_AMOUNT_MISMATCH")
    if not order.reduce_only:
        blockers.append("EXIT_REDUCE_ONLY_MISMATCH")
    if order.post_only:
        blockers.append("EXIT_POST_ONLY_MISMATCH")
    if order.state != "filled":
        blockers.append("EXIT_FINAL_STATE_NOT_FILLED")
    if trades.amount != order.filled_amount:
        blockers.append("EXIT_TRADE_AMOUNT_MISMATCH")
    return blockers


def _order(value: Mapping[str, object], code: str) -> _OrderFact:
    order_id = _text(value.get("order_id"), code)
    instrument_name = _text(value.get("instrument_name"), code)
    direction = value.get("direction")
    state = value.get("order_state")
    if direction not in {"buy", "sell"} or state not in _ORDER_STATES:
        raise DeribitComboError(code)
    amount = _decimal(value.get("amount"), code)
    filled_amount = _decimal(value.get("filled_amount"), code)
    if amount <= 0 or filled_amount < 0:
        raise DeribitComboError(code)
    post_only = value.get("post_only")
    reduce_only = value.get("reduce_only")
    if not isinstance(post_only, bool) or not isinstance(reduce_only, bool):
        raise DeribitComboError(code)
    return _OrderFact(
        order_id=order_id,
        instrument_name=instrument_name,
        direction=direction,
        state=state,
        amount=amount,
        filled_amount=filled_amount,
        post_only=post_only,
        reduce_only=reduce_only,
    )


def _trades(value: object, *, order_id: str) -> _TradeFacts:
    if isinstance(value, Mapping):
        raw_trades = value.get("trades")
    else:
        raw_trades = value
    rows = _sequence(raw_trades, "TRADES_PAYLOAD_INVALID")
    seen: set[str] = set()
    amount = Decimal(0)
    fees: dict[str, Decimal] = {}
    for row in rows:
        trade = _mapping(row, "TRADES_PAYLOAD_INVALID")
        trade_id = _text(trade.get("trade_id"), "TRADES_PAYLOAD_INVALID")
        if trade_id in seen or trade.get("order_id") != order_id:
            raise DeribitComboError("TRADES_PAYLOAD_INVALID")
        seen.add(trade_id)
        trade_amount = _decimal(trade.get("amount"), "TRADES_PAYLOAD_INVALID")
        fee = _decimal(trade.get("fee"), "TRADES_PAYLOAD_INVALID")
        fee_currency = _text(trade.get("fee_currency"), "TRADES_PAYLOAD_INVALID")
        if trade_amount <= 0:
            raise DeribitComboError("TRADES_PAYLOAD_INVALID")
        amount += trade_amount
        fees[fee_currency] = fees.get(fee_currency, Decimal(0)) + fee
    return _TradeFacts(amount=amount, fees=tuple(sorted(fees.items())))


def _positions(value: object) -> PositionSignature:
    rows = _sequence(value, "POSITIONS_PAYLOAD_INVALID")
    positions: dict[str, tuple[str, str, Decimal]] = {}
    for row in rows:
        position = _mapping(row, "POSITIONS_PAYLOAD_INVALID")
        name = _text(position.get("instrument_name"), "POSITIONS_PAYLOAD_INVALID")
        kind = _text(position.get("kind"), "POSITIONS_PAYLOAD_INVALID")
        direction = _text(position.get("direction"), "POSITIONS_PAYLOAD_INVALID")
        size = _decimal(position.get("size"), "POSITIONS_PAYLOAD_INVALID")
        if size == 0:
            continue
        if name in positions:
            raise DeribitComboError("POSITIONS_PAYLOAD_INVALID")
        positions[name] = (kind, direction, size)
    return tuple(
        (name, details[0], details[1], details[2]) for name, details in sorted(positions.items())
    )


def _validate_call(
    method: str,
    params: Mapping[str, object],
    *,
    grant: ComboAuthGrant | None,
) -> None:
    if method not in DERIBIT_COMBO_METHOD_ALLOWLIST:
        raise DeribitComboError("METHOD_OUTSIDE_C2_ALLOWLIST")
    if not isinstance(params, Mapping):
        raise DeribitComboError("REQUEST_OUTSIDE_C2_BOUNDARY")
    private = method.startswith("private/")
    if private != (grant is not None):
        raise DeribitComboError("AUTHORIZATION_BOUNDARY_INVALID")
    keys = set(params)
    if method == "public/auth":
        if keys != {"grant_type", "client_id", "client_secret", "scope"}:
            raise DeribitComboError("REQUEST_OUTSIDE_C2_BOUNDARY")
        if (
            params.get("grant_type") != "client_credentials"
            or params.get("scope") != DERIBIT_COMBO_AUTH_SCOPE
        ):
            raise DeribitComboError("REQUEST_OUTSIDE_C2_BOUNDARY")
        return
    if method == "public/get_combos":
        valid = keys == {"currency"} and params.get("currency") == "BTC"
    elif method == "public/get_instrument":
        valid = keys == {"instrument_name"} and _is_text(params.get("instrument_name"))
    elif method == "public/get_order_book":
        valid = (
            keys == {"instrument_name", "depth"}
            and _is_text(params.get("instrument_name"))
            and params.get("depth") == 1
        )
    elif method == "private/get_positions":
        valid = keys == {"currency"} and params.get("currency") == "BTC"
    elif method == "private/get_order_state" or method == "private/cancel":
        valid = keys == {"order_id"} and _is_text(params.get("order_id"))
    elif method == "private/get_user_trades_by_order":
        valid = (
            keys == {"order_id", "sorting", "historical"}
            and _is_text(params.get("order_id"))
            and params.get("sorting") == "default"
            and params.get("historical") is False
        )
    else:
        valid = _valid_order_params(params)
    if not valid:
        raise DeribitComboError("REQUEST_OUTSIDE_C2_BOUNDARY")


def _valid_order_params(params: Mapping[str, object]) -> bool:
    common = (
        _is_text(params.get("instrument_name"))
        and _positive_number(params.get("amount"))
        and _valid_label_value(params.get("label"))
    )
    if not common:
        return False
    if params.get("type") == "limit":
        return (
            set(params)
            == {
                "instrument_name",
                "amount",
                "type",
                "price",
                "time_in_force",
                "post_only",
                "reject_post_only",
                "reduce_only",
                "label",
            }
            and _finite_number(params.get("price"))
            and params.get("time_in_force") == "good_til_cancelled"
            and params.get("post_only") is True
            and params.get("reject_post_only") is True
            and params.get("reduce_only") is False
        )
    if params.get("type") == "market":
        return (
            set(params)
            == {
                "instrument_name",
                "amount",
                "type",
                "post_only",
                "reduce_only",
                "label",
            }
            and params.get("post_only") is False
            and params.get("reduce_only") is True
        )
    return False


def _pre_order_failure(error: DeribitComboError) -> ComboLifecycleReceipt:
    return ComboLifecycleReceipt(
        status="BLOCKED",
        outcome="PRE_ORDER_CONNECTIVITY_FAILED",
        blockers=(error.code,),
        exchange_error_code=error.exchange_code,
    )


def _exchange_code(*errors: DeribitComboError | None) -> int | None:
    return next(
        (error.exchange_code for error in errors if error is not None and error.exchange_code),
        None,
    )


def _method_prefix(method: str) -> str:
    return method.replace("/", "_").upper()


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DeribitComboError(code)
    for key in value:
        if not isinstance(key, str):
            raise DeribitComboError(code)
    return value


def _sequence(value: object, code: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise DeribitComboError(code)
    return value


def _text(value: object, code: str) -> str:
    if not _is_text(value):
        raise DeribitComboError(code)
    assert isinstance(value, str)
    return value


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value


def _decimal(value: object, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DeribitComboError(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise DeribitComboError(code) from None
    if not number.is_finite():
        raise DeribitComboError(code)
    return number


def _finite_number(value: object) -> bool:
    try:
        _decimal(value, "INVALID")
    except DeribitComboError:
        return False
    return True


def _positive_number(value: object) -> bool:
    try:
        return _decimal(value, "INVALID") > 0
    except DeribitComboError:
        return False


def _json_primitive_number(value: object, code: str) -> int | float:
    _decimal(value, code)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return _json_number(value)
    raise DeribitComboError(code)


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _validate_label(label: str) -> None:
    if not _valid_label_value(label):
        raise ValueError("label must be non-empty printable text of at most 64 characters")


def _valid_label_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value.strip() == value
        and value.isprintable()
    )


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _decimal_text_or_none(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _fee_object(values: tuple[tuple[str, Decimal], ...]) -> dict[str, str]:
    return {currency: format(amount, "f") for currency, amount in values}

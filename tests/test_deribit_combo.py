from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar

import pytest

from optimatrix.deribit_combo import (
    DERIBIT_COMBO_AUTH_SCOPE,
    DERIBIT_COMBO_HOST,
    DERIBIT_COMBO_METHOD_ALLOWLIST,
    ComboAuthGrant,
    DeribitComboError,
    DeribitComboHttpClient,
    run_testnet_combo_lifecycle,
)

_CLIENT_ID = "combo-client-id-must-not-leak"
_CLIENT_SECRET = "combo-client-secret-must-not-leak"
_TOKEN = "combo-token-must-not-leak"
_NOW_MS = 1_787_000_000_000
_COMBO = "BTC-FS-21AUG26_28AUG26"
_LEG_ONE = "BTC-21AUG26"
_LEG_TWO = "BTC-28AUG26"


class _FakeTransport:
    def __init__(self, responses: Mapping[str, list[object]]) -> None:
        self.responses = {method: list(values) for method, values in responses.items()}
        self.calls: list[tuple[str, dict[str, object], bool]] = []

    def authenticate(self, *, client_id: str, client_secret: str) -> ComboAuthGrant:
        assert client_id == _CLIENT_ID
        assert client_secret == _CLIENT_SECRET
        self.calls.append(("public/auth", {"scope": DERIBIT_COMBO_AUTH_SCOPE}, False))
        return ComboAuthGrant(access_token=_TOKEN)

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        grant: ComboAuthGrant | None = None,
    ) -> object:
        self.calls.append((method, dict(params), grant is not None))
        if method.startswith("private/"):
            assert grant is not None and grant.access_token == _TOKEN
        else:
            assert grant is None
        values = self.responses.get(method)
        if not values:
            raise AssertionError(f"unexpected call: {method}")
        value = values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _combo(combo_id: str = _COMBO, *, state: str = "active") -> dict[str, object]:
    return {
        "id": combo_id,
        "state": state,
        "legs": [
            {"instrument_name": _LEG_ONE, "amount": 1},
            {"instrument_name": _LEG_TWO, "amount": -1},
        ],
    }


def _instrument(combo_id: str = _COMBO) -> dict[str, object]:
    return {
        "instrument_name": combo_id,
        "kind": "future_combo",
        "base_currency": "BTC",
        "is_active": True,
        "state": "open",
        "expiration_timestamp": _NOW_MS + 86_400_000,
        "min_trade_amount": 10,
        "tick_size": 0.5,
    }


def _book(
    *,
    combo_id: str = _COMBO,
    bids: list[list[float | int]] | None = None,
    asks: list[list[float | int]] | None = None,
) -> dict[str, object]:
    return {
        "instrument_name": combo_id,
        "state": "open",
        "bids": [[-12.5, 20]] if bids is None else bids,
        "asks": [[-12.0, 20]] if asks is None else asks,
    }


def _order(
    order_id: str,
    *,
    direction: str = "buy",
    state: str = "open",
    amount: float | int = 10,
    filled: float | int = 0,
    post_only: bool = True,
    reduce_only: bool = False,
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "instrument_name": _COMBO,
        "direction": direction,
        "order_state": state,
        "amount": amount,
        "filled_amount": filled,
        "post_only": post_only,
        "reduce_only": reduce_only,
    }


def _trade(
    trade_id: str,
    order_id: str,
    *,
    amount: float | int,
    fee: float,
    fee_currency: str = "BTC",
) -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "order_id": order_id,
        "amount": amount,
        "fee": fee,
        "fee_currency": fee_currency,
        "combo_id": _COMBO,
        "legs": [{"instrument_name": _LEG_ONE}, {"instrument_name": _LEG_TWO}],
    }


def _position(name: str, *, direction: str, size: float) -> dict[str, object]:
    return {
        "instrument_name": name,
        "kind": "future",
        "direction": direction,
        "size": size,
        "mark_price": 1_000_000,
        "floating_profit_loss": 9_999,
    }


def _base_responses() -> dict[str, list[object]]:
    return {
        "private/get_positions": [[]],
        "public/get_combos": [[_combo()]],
        "public/get_instrument": [_instrument()],
        "public/get_order_book": [_book()],
    }


def _run(transport: _FakeTransport):
    return run_testnet_combo_lifecycle(
        transport=transport,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
        now_ms=_NOW_MS,
        label="optimatrix-c2-test",
    )


def test_no_fill_places_one_exact_passive_order_then_cancels_and_reconciles() -> None:
    responses = _base_responses()
    responses.update(
        {
            "private/get_positions": [[], [], []],
            "private/buy": [{"order": _order("entry-1"), "trades": []}],
            "private/get_order_state": [
                _order("entry-1"),
                _order("entry-1", state="cancelled"),
            ],
            "private/get_user_trades_by_order": [[], []],
            "private/cancel": [_order("entry-1", state="cancelled")],
        }
    )
    transport = _FakeTransport(responses)

    receipt = _run(transport)

    assert receipt.status == "COMPLETE"
    assert receipt.outcome == "NO_FILL_CANCELLED"
    assert receipt.entry_filled_amount == 0
    assert receipt.entry_trade_amount == 0
    assert receipt.entry_fee_totals == ()
    assert receipt.cancel_attempted is True
    assert receipt.reduce_only_exit == "NOT_APPLICABLE_NO_FILL"
    assert receipt.positions_reconciled is True
    order_calls = [call for call in transport.calls if call[0] in {"private/buy", "private/sell"}]
    assert order_calls == [
        (
            "private/buy",
            {
                "instrument_name": _COMBO,
                "amount": 10,
                "type": "limit",
                "price": -12.5,
                "time_in_force": "good_til_cancelled",
                "post_only": True,
                "reject_post_only": True,
                "reduce_only": False,
                "label": "optimatrix-c2-test",
            },
            True,
        )
    ]
    assert [call[0] for call in transport.calls].count("private/cancel") == 1


def test_partial_fill_uses_unique_trade_and_fee_facts_then_exits_actual_fill_only() -> None:
    open_position = [_position(_LEG_ONE, direction="buy", size=4)]
    responses = _base_responses()
    responses.update(
        {
            "private/get_positions": [[], open_position, open_position, []],
            "private/buy": [{"order": _order("entry-2", filled=4), "trades": []}],
            "private/sell": [
                {
                    "order": _order(
                        "exit-2",
                        direction="sell",
                        state="filled",
                        amount=4,
                        filled=4,
                        post_only=False,
                        reduce_only=True,
                    ),
                    "trades": [],
                }
            ],
            "private/get_order_state": [
                _order("entry-2", filled=4),
                _order("entry-2", state="cancelled", filled=4),
                _order(
                    "exit-2",
                    direction="sell",
                    state="filled",
                    amount=4,
                    filled=4,
                    post_only=False,
                    reduce_only=True,
                ),
            ],
            "private/get_user_trades_by_order": [
                [
                    _trade("entry-t1", "entry-2", amount=1.5, fee=0.0001),
                    _trade("entry-t2", "entry-2", amount=2.5, fee=0.20, fee_currency="USD"),
                ],
                [
                    _trade("entry-t1", "entry-2", amount=1.5, fee=0.0001),
                    _trade("entry-t2", "entry-2", amount=2.5, fee=0.20, fee_currency="USD"),
                ],
                [_trade("exit-t1", "exit-2", amount=4, fee=0.0002)],
            ],
            "private/cancel": [_order("entry-2", state="cancelled", filled=4)],
        }
    )
    transport = _FakeTransport(responses)

    receipt = _run(transport)

    assert receipt.status == "COMPLETE"
    assert receipt.outcome == "NATURAL_FILL_EXITED"
    assert receipt.entry_filled_amount == 4
    assert receipt.entry_trade_amount == 4
    assert receipt.entry_fee_totals == (("BTC", Decimal("0.0001")), ("USD", Decimal("0.2")))
    assert receipt.exit_fee_totals == (("BTC", Decimal("0.0002")),)
    assert receipt.cancel_attempted is True
    assert receipt.reduce_only_exit == "COMPLETE"
    assert receipt.positions_reconciled is True
    sell = next(call for call in transport.calls if call[0] == "private/sell")
    assert sell[1] == {
        "instrument_name": _COMBO,
        "amount": 4,
        "type": "market",
        "post_only": False,
        "reduce_only": True,
        "label": "optimatrix-c2-test-exit",
    }


def test_cancel_fill_race_refetches_filled_state_and_still_reduces_position() -> None:
    open_position = [_position(_LEG_TWO, direction="sell", size=10)]
    responses = _base_responses()
    responses.update(
        {
            "private/get_positions": [[], open_position, open_position, []],
            "private/buy": [{"order": _order("entry-race"), "trades": []}],
            "private/sell": [
                {
                    "order": _order(
                        "exit-race",
                        direction="sell",
                        state="filled",
                        filled=10,
                        post_only=False,
                        reduce_only=True,
                    ),
                    "trades": [],
                }
            ],
            "private/get_order_state": [
                _order("entry-race"),
                _order("entry-race", state="filled", filled=10),
                _order(
                    "exit-race",
                    direction="sell",
                    state="filled",
                    filled=10,
                    post_only=False,
                    reduce_only=True,
                ),
            ],
            "private/get_user_trades_by_order": [
                [],
                [_trade("race-entry", "entry-race", amount=10, fee=0.001)],
                [_trade("race-exit", "exit-race", amount=10, fee=0.001)],
            ],
            "private/cancel": [
                DeribitComboError("PRIVATE_CANCEL_RPC_REJECTED", exchange_code=11044)
            ],
        }
    )
    receipt = _run(_FakeTransport(responses))

    assert receipt.status == "COMPLETE"
    assert receipt.outcome == "NATURAL_FILL_EXITED"
    assert receipt.blockers == ()


def test_candidate_scan_is_bounded_deterministic_and_never_creates_combo() -> None:
    conflicted = "A-COMBO"
    empty = "B-COMBO"
    selected = "C-COMBO"
    malformed = {"id": "BAD", "state": "active", "legs": []}
    combos = [
        _combo(selected),
        malformed,
        _combo(empty),
        _combo(conflicted),
        _combo("Z-INACTIVE", state="inactive"),
    ]
    baseline = [_position(conflicted, direction="buy", size=1)]
    responses = {
        "private/get_positions": [baseline, baseline, baseline],
        "public/get_combos": [combos],
        "public/get_instrument": [_instrument(empty), _instrument(selected)],
        "public/get_order_book": [
            _book(combo_id=empty, bids=[], asks=[]),
            _book(combo_id=selected, bids=[], asks=[[-7.5, 10]]),
        ],
        "private/sell": [
            {
                "order": {
                    **_order("entry-ask", direction="sell"),
                    "instrument_name": selected,
                },
                "trades": [],
            }
        ],
        "private/get_order_state": [
            {**_order("entry-ask", direction="sell"), "instrument_name": selected},
            {
                **_order("entry-ask", direction="sell", state="cancelled"),
                "instrument_name": selected,
            },
        ],
        "private/get_user_trades_by_order": [[], []],
        "private/cancel": [_order("entry-ask", direction="sell", state="cancelled")],
    }
    transport = _FakeTransport(responses)

    receipt = _run(transport)

    assert receipt.status == "COMPLETE"
    sell = next(call for call in transport.calls if call[0] == "private/sell")
    assert sell[1]["instrument_name"] == selected
    assert sell[1]["price"] == -7.5
    assert all(call[0] != "private/create_combo" for call in transport.calls)


def test_trade_inconsistency_still_attempts_exit_but_cannot_claim_closure() -> None:
    open_position = [_position(_LEG_ONE, direction="buy", size=10)]
    responses = _base_responses()
    responses.update(
        {
            "private/get_positions": [[], open_position, []],
            "private/buy": [
                {"order": _order("entry-bad", state="filled", filled=10), "trades": []}
            ],
            "private/sell": [
                {
                    "order": _order(
                        "exit-bad",
                        direction="sell",
                        state="filled",
                        filled=10,
                        post_only=False,
                        reduce_only=True,
                    ),
                    "trades": [],
                }
            ],
            "private/get_order_state": [
                _order("entry-bad", state="filled", filled=10),
                _order(
                    "exit-bad",
                    direction="sell",
                    state="filled",
                    filled=10,
                    post_only=False,
                    reduce_only=True,
                ),
            ],
            "private/get_user_trades_by_order": [
                [_trade("entry-short", "entry-bad", amount=9, fee=0.001)],
                [_trade("exit-ok", "exit-bad", amount=10, fee=0.001)],
            ],
        }
    )
    transport = _FakeTransport(responses)

    receipt = _run(transport)

    assert receipt.status == "BLOCKED"
    assert "ENTRY_TRADE_AMOUNT_MISMATCH" in receipt.blockers
    assert any(call[0] == "private/sell" for call in transport.calls)
    assert receipt.positions_reconciled is True


def test_post_only_rejection_has_no_fabricated_order_or_cleanup() -> None:
    responses = _base_responses()
    responses["private/buy"] = [DeribitComboError("PRIVATE_BUY_RPC_REJECTED", exchange_code=11044)]
    transport = _FakeTransport(responses)

    receipt = _run(transport)

    assert receipt.status == "BLOCKED"
    assert receipt.outcome == "ENTRY_ORDER_NOT_ACCEPTED"
    assert receipt.entry_order_id is None
    assert receipt.exchange_error_code == 11044
    assert all(call[0] != "private/cancel" for call in transport.calls)


class _HttpResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def getheader(self, name: str) -> str | None:
        del name
        return None


class _HttpConnection:
    instances: ClassVar[list[_HttpConnection]] = []

    def __init__(self, host: str, timeout: float) -> None:
        self.host = host
        self.timeout = timeout
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.closed = False
        type(self).instances.append(self)

    def request(
        self,
        verb: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.requests.append((verb, path, body, headers))

    def getresponse(self) -> _HttpResponse:
        request_id = json.loads(self.requests[-1][2])["id"]
        return _HttpResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "testnet": True,
                "result": {
                    "access_token": _TOKEN,
                    "token_type": "bearer",
                    "expires_in": 900,
                    "scope": "irrelevant exchange response text",
                },
            }
        )

    def close(self) -> None:
        self.closed = True


def test_http_client_is_testnet_only_requests_fixed_scope_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _HttpConnection.instances.clear()
    monkeypatch.setattr("optimatrix.deribit_combo.HTTPSConnection", _HttpConnection)
    client = DeribitComboHttpClient()

    grant = client.authenticate(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)

    connection = _HttpConnection.instances[0]
    assert connection.host == DERIBIT_COMBO_HOST == "test.deribit.com"
    request = json.loads(connection.requests[0][2])
    assert request["method"] == "public/auth"
    assert request["params"]["scope"] == "trade:read_write"
    assert grant.access_token == _TOKEN
    safe = f"{client!r} {grant!r}"
    assert "TESTNET" in safe
    for secret in (_CLIENT_ID, _CLIENT_SECRET, _TOKEN):
        assert secret not in safe


def test_http_method_and_parameter_surface_rejects_mainnet_or_expansion_before_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DERIBIT_COMBO_METHOD_ALLOWLIST == {
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

    def forbidden_connection(*args: object, **kwargs: object) -> Any:
        raise AssertionError((args, kwargs))

    monkeypatch.setattr("optimatrix.deribit_combo.HTTPSConnection", forbidden_connection)
    client = DeribitComboHttpClient()
    grant = ComboAuthGrant(access_token=_TOKEN)
    with pytest.raises(DeribitComboError, match="METHOD_OUTSIDE_C2_ALLOWLIST"):
        client.call("private/create_combo", {}, grant=grant)
    with pytest.raises(DeribitComboError, match="REQUEST_OUTSIDE_C2_BOUNDARY"):
        client.call("private/get_positions", {"currency": "ETH"}, grant=grant)
    with pytest.raises(DeribitComboError, match="AUTHORIZATION_BOUNDARY_INVALID"):
        client.call("private/get_positions", {"currency": "BTC"})
    with pytest.raises(DeribitComboError, match="REQUEST_OUTSIDE_C2_BOUNDARY"):
        client.call(
            "private/buy",
            {
                "instrument_name": _COMBO,
                "amount": 10,
                "type": "market",
                "post_only": False,
                "reduce_only": False,
                "label": "unsafe",
            },
            grant=grant,
        )


def test_receipt_and_error_never_contain_secret_token_or_position_values() -> None:
    responses = _base_responses()
    responses["private/buy"] = [DeribitComboError("PRIVATE_BUY_RPC_REJECTED")]
    receipt = _run(_FakeTransport(responses))

    safe = json.dumps(receipt.as_safe_object(), sort_keys=True)
    for secret in (_CLIENT_ID, _CLIENT_SECRET, _TOKEN, "1000000", "9999"):
        assert secret not in safe
    error = DeribitComboError("AUTH_RPC_REJECTED", exchange_code=13009)
    assert repr(error) == "DeribitComboError('AUTH_RPC_REJECTED')"

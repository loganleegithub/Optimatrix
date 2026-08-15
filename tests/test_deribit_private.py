from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from optimatrix.account import (
    AccountObservationStatus,
    CredentialScopeCapability,
    DeribitAccountEnvironment,
)
from optimatrix.deribit_private import (
    DERIBIT_PRIVATE_METHOD_ALLOWLIST,
    DERIBIT_REQUIRED_AUTH_SCOPE,
    DeribitPrivateError,
    DeribitPrivateHttpClient,
    PrivateAuthGrant,
    PrivateRpcResponse,
    capture_authenticated_account,
)

_SERVER_US = int(datetime(2026, 8, 15, 12, tzinfo=UTC).timestamp() * 1_000_000)
_CLIENT_ID = "client-identifier-must-not-leak"
_CLIENT_SECRET = "client-secret-must-not-leak"
_ACCESS_TOKEN = "access-token-must-not-leak"


def _response(result: object, *, request_id: int = 1, testnet: bool = False) -> PrivateRpcResponse:
    return PrivateRpcResponse(
        request_id=request_id,
        result=result,
        testnet=testnet,
        server_received_at_us=_SERVER_US,
        server_sent_at_us=_SERVER_US + 2_000,
        server_processing_us=2_000,
        request_sent_monotonic_ns=1_000_000_000,
        response_received_monotonic_ns=1_005_000_000,
    )


def _summary(currency: str = "BTC") -> dict[str, object]:
    return {
        "currency": currency,
        "balance": 1.2,
        "equity": 1.1,
        "available_funds": 0.8,
        "initial_margin": 0.2,
        "maintenance_margin": 0.1,
    }


def _position(name: str = "BTC-15AUG26-60000-C") -> dict[str, object]:
    return {
        "instrument_name": name,
        "kind": "option",
        "direction": "sell",
        "size": 0.1,
        "average_price": 0.003,
        "mark_price": 0.002,
        "floating_profit_loss": 0.001,
        "total_profit_loss": 0.001,
        "initial_margin": 0.02,
        "maintenance_margin": 0.01,
        "delta": -0.2,
    }


class _FakeTransport:
    def __init__(
        self,
        *,
        summary: object | DeribitPrivateError | None = None,
        positions: object | DeribitPrivateError | None = None,
    ) -> None:
        self.summary = _summary() if summary is None else summary
        self.positions = [] if positions is None else positions
        self.calls: list[str] = []

    def authenticate(self, *, client_id: str, client_secret: str) -> PrivateAuthGrant:
        self.calls.append("public/auth")
        assert client_id == _CLIENT_ID
        assert client_secret == _CLIENT_SECRET
        return PrivateAuthGrant(
            boundary=_response({}).boundary,
            access_token=_ACCESS_TOKEN,
        )

    def get_account_summary(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        self.calls.append("private/get_account_summary")
        assert grant.access_token == _ACCESS_TOKEN
        if isinstance(self.summary, DeribitPrivateError):
            raise self.summary
        return _response(self.summary, request_id=2)

    def get_positions(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        self.calls.append("private/get_positions")
        assert grant.access_token == _ACCESS_TOKEN
        if isinstance(self.positions, DeribitPrivateError):
            raise self.positions
        return _response(self.positions, request_id=3)


class _HttpResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def getheader(self, name: str) -> str | None:
        del name
        return None


class _HttpConnection:
    def __init__(self, host: str, timeout: float, responses: list[_HttpResponse]) -> None:
        self.host = host
        self.timeout = timeout
        self.responses = responses
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.closed = False

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
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _monotonic(values: tuple[int, ...]) -> Iterator[int]:
    yield from values


def test_complete_and_empty_positions_are_known_but_partial_components_are_not_flat() -> None:
    complete_transport = _FakeTransport(positions=[])
    complete = capture_authenticated_account(
        transport=complete_transport,
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    assert complete.status is AccountObservationStatus.KNOWN
    assert complete.positions == ()
    assert complete.blockers == ()
    assert complete_transport.calls == [
        "public/auth",
        "private/get_account_summary",
        "private/get_positions",
    ]

    partial_transport = _FakeTransport(
        positions=DeribitPrivateError("ACCOUNT_POSITIONS_RPC_REJECTED")
    )
    partial = capture_authenticated_account(
        transport=partial_transport,
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    assert partial.status is AccountObservationStatus.UNKNOWN
    assert partial.summary is not None
    assert partial.positions is None
    assert partial.as_object()["position_count"] is None
    assert partial.blockers == ("ACCOUNT_POSITIONS_RPC_REJECTED",)


def test_capture_validates_components_without_persisting_auth_scope_text() -> None:
    currency = capture_authenticated_account(
        transport=_FakeTransport(summary=_summary("ETH")),
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    assert currency.summary is None
    assert currency.positions == ()
    assert currency.blockers == ("ACCOUNT_SUMMARY_CURRENCY_MISMATCH",)

    duplicate = capture_authenticated_account(
        transport=_FakeTransport(positions=[_position(), _position()]),
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    assert duplicate.positions is None
    assert duplicate.blockers == ("ACCOUNT_POSITIONS_DUPLICATE_INSTRUMENT",)

    invalid_numeric_summary = _summary()
    invalid_numeric_summary["equity"] = "NaN"
    invalid_numeric = capture_authenticated_account(
        transport=_FakeTransport(summary=invalid_numeric_summary),
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    assert invalid_numeric.summary is None
    assert invalid_numeric.blockers == ("ACCOUNT_SUMMARY_PAYLOAD_INVALID",)

    complete = capture_authenticated_account(
        transport=_FakeTransport(),
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    serialized = json.dumps(complete.as_object(), sort_keys=True)
    assert complete.credential_scope is CredentialScopeCapability.USER_DECLARED_READ_ONLY
    assert complete.token_scope_normalization == "UNAVAILABLE"
    assert "effective_scopes" not in serialized
    assert _CLIENT_ID not in serialized
    assert _CLIENT_SECRET not in serialized
    assert _ACCESS_TOKEN not in serialized


def test_client_has_fixed_hosts_and_rejects_methods_and_params_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DERIBIT_PRIVATE_METHOD_ALLOWLIST == {
        "public/auth",
        "private/get_account_summary",
        "private/get_positions",
    }

    def forbidden_connection(*args: object, **kwargs: object) -> Any:
        raise AssertionError((args, kwargs))

    monkeypatch.setattr("optimatrix.deribit_private.HTTPSConnection", forbidden_connection)
    client = DeribitPrivateHttpClient(environment=DeribitAccountEnvironment.MAINNET)
    with pytest.raises(DeribitPrivateError, match="METHOD_OUTSIDE_C1_ALLOWLIST"):
        client.call("private/get_order_state", {"order_id": "x"}, access_token="token")
    with pytest.raises(DeribitPrivateError, match="PRIVATE_REQUEST_OUTSIDE_C1_BOUNDARY"):
        client.call(
            "private/get_positions",
            {"currency": "ETH"},
            access_token="token",
        )
    with pytest.raises(DeribitPrivateError, match="ENVIRONMENT_OUTSIDE_C1_ALLOWLIST"):
        DeribitPrivateHttpClient(environment="https://evil.example")  # type: ignore[arg-type]
    with pytest.raises(DeribitPrivateError, match="ENVIRONMENT_OUTSIDE_C1_ALLOWLIST"):
        DeribitPrivateHttpClient(environment=DeribitAccountEnvironment.TESTNET)


@pytest.mark.parametrize(
    ("environment", "expected_host", "testnet"),
    [(DeribitAccountEnvironment.MAINNET, "www.deribit.com", False)],
)
def test_auth_uses_fixed_environment_and_never_exposes_the_token(
    monkeypatch: pytest.MonkeyPatch,
    environment: DeribitAccountEnvironment,
    expected_host: str,
    testnet: bool,
) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "testnet": testnet,
        "usIn": _SERVER_US,
        "usOut": _SERVER_US + 2_000,
        "usDiff": 2_000,
        "result": {
            "access_token": _ACCESS_TOKEN,
            "token_type": "bearer",
            "expires_in": 60,
            "scope": "account:read trade:read connection expires:60",
        },
    }
    connections: list[_HttpConnection] = []

    def connection_factory(host: str, timeout: float) -> _HttpConnection:
        connection = _HttpConnection(host, timeout, [_HttpResponse(payload)])
        connections.append(connection)
        return connection

    monotonic = _monotonic((1_000_000_000, 1_005_000_000))
    monkeypatch.setattr("optimatrix.deribit_private.HTTPSConnection", connection_factory)
    client = DeribitPrivateHttpClient(
        environment=environment,
        monotonic_ns=lambda: next(monotonic),
    )
    grant = client.authenticate(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)

    assert connections[0].host == expected_host
    assert connections[0].closed is True
    verb, path, body, headers = connections[0].requests[0]
    assert (verb, path) == ("POST", "/api/v2/public/auth")
    assert headers.get("Authorization") is None
    request = json.loads(body)
    assert request["params"]["scope"] == DERIBIT_REQUIRED_AUTH_SCOPE
    assert not hasattr(grant, "effective_scopes")
    assert _ACCESS_TOKEN not in repr(grant)
    assert _CLIENT_SECRET not in repr(client)


@pytest.mark.parametrize(
    "scope_payload",
    [
        {},
        {"scope": "response-scope-sentinel:!must-never-survive ip:any/session/value"},
    ],
)
def test_mainnet_auth_response_scope_text_is_not_a_read_gate_or_output(
    monkeypatch: pytest.MonkeyPatch,
    scope_payload: dict[str, str],
) -> None:
    payloads = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "testnet": False,
            "usIn": _SERVER_US,
            "usOut": _SERVER_US + 2_000,
            "usDiff": 2_000,
            "result": {
                "access_token": _ACCESS_TOKEN,
                "token_type": "bearer",
                "expires_in": 60,
                **scope_payload,
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "testnet": False,
            "usIn": _SERVER_US + 10_000,
            "usOut": _SERVER_US + 12_000,
            "usDiff": 2_000,
            "result": _summary(),
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "testnet": False,
            "usIn": _SERVER_US + 20_000,
            "usOut": _SERVER_US + 22_000,
            "usDiff": 2_000,
            "result": [],
        },
    ]
    connections: list[_HttpConnection] = []

    def connection_factory(host: str, timeout: float) -> _HttpConnection:
        connection = _HttpConnection(host, timeout, [_HttpResponse(payloads.pop(0))])
        connections.append(connection)
        return connection

    monotonic = _monotonic(
        (
            1_000_000_000,
            1_005_000_000,
            2_000_000_000,
            2_005_000_000,
            3_000_000_000,
            3_005_000_000,
        )
    )
    monkeypatch.setattr("optimatrix.deribit_private.HTTPSConnection", connection_factory)
    observation = capture_authenticated_account(
        transport=DeribitPrivateHttpClient(
            environment=DeribitAccountEnvironment.MAINNET,
            monotonic_ns=lambda: next(monotonic),
        ),
        environment=DeribitAccountEnvironment.MAINNET,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )

    assert observation.status is AccountObservationStatus.KNOWN
    assert [connection.requests[0][1] for connection in connections] == [
        "/api/v2/public/auth",
        "/api/v2/private/get_account_summary",
        "/api/v2/private/get_positions",
    ]
    serialized = json.dumps(observation.as_object(), sort_keys=True)
    assert "response-scope-sentinel" not in serialized
    assert _ACCESS_TOKEN not in serialized


def test_environment_mismatch_and_rpc_error_are_safe_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "testnet": True,
            "usIn": _SERVER_US,
            "usOut": _SERVER_US + 2_000,
            "usDiff": 2_000,
            "error": {"message": _CLIENT_SECRET},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "testnet": False,
            "usIn": _SERVER_US,
            "usOut": _SERVER_US + 2_000,
            "usDiff": 2_000,
            "error": {"message": _CLIENT_SECRET},
        },
    ]
    monotonic_values = iter((1_000_000_000, 1_005_000_000, 2_000_000_000, 2_005_000_000))

    def connection_factory(host: str, timeout: float) -> _HttpConnection:
        del host, timeout
        return _HttpConnection("fixed", 10, [_HttpResponse(payloads.pop(0))])

    monkeypatch.setattr("optimatrix.deribit_private.HTTPSConnection", connection_factory)
    client = DeribitPrivateHttpClient(
        environment=DeribitAccountEnvironment.MAINNET,
        monotonic_ns=lambda: next(monotonic_values),
    )
    with pytest.raises(DeribitPrivateError) as mismatch:
        client.authenticate(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)
    assert str(mismatch.value) == "AUTH_ENVIRONMENT_MISMATCH"

    with pytest.raises(DeribitPrivateError) as rejected:
        client.authenticate(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)
    assert str(rejected.value) == "AUTH_RPC_REJECTED"
    safe_text = f"{mismatch.value!r} {rejected.value!r}"
    assert _CLIENT_ID not in safe_text
    assert _CLIENT_SECRET not in safe_text
    assert _ACCESS_TOKEN not in safe_text

from __future__ import annotations

import gzip
import json
import math
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from http.client import HTTPException, HTTPSConnection
from typing import Protocol

from optimatrix.account import (
    AccountPositionDirection,
    AccountPositionKind,
    AccountResponseBoundary,
    AuthenticatedAccountObservation,
    AuthenticatedAccountPosition,
    AuthenticatedAccountSummary,
    DeribitAccountEnvironment,
    account_scope_identity,
)

DERIBIT_PRIVATE_METHOD_ALLOWLIST = frozenset(
    {
        "public/auth",
        "private/get_account_summary",
        "private/get_positions",
    }
)
DERIBIT_REQUIRED_AUTH_SCOPE = "account:read trade:read"
_ENDPOINTS = {
    DeribitAccountEnvironment.MAINNET: ("www.deribit.com", False),
}


class DeribitPrivateError(RuntimeError):
    """One safe, credential-free C1 transport or translation failure."""

    def __init__(self, code: str) -> None:
        if not code or not code.replace("_", "").isalnum() or code != code.upper():
            raise ValueError("private error code must be uppercase identifier text")
        self.code = code
        super().__init__(code)


def _continuous_monotonic_ns() -> int:
    if sys.platform == "darwin":
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    boot_time_clock = getattr(time, "CLOCK_BOOTTIME", None)
    if boot_time_clock is not None:
        return time.clock_gettime_ns(boot_time_clock)
    return time.monotonic_ns()


@dataclass(frozen=True)
class PrivateRpcResponse:
    request_id: int
    result: object
    testnet: bool
    server_received_at_us: int
    server_sent_at_us: int
    server_processing_us: int
    request_sent_monotonic_ns: int
    response_received_monotonic_ns: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id <= 0
        ):
            raise ValueError("private response request id must be positive")
        for value, field_name in (
            (self.server_received_at_us, "server_received_at_us"),
            (self.server_sent_at_us, "server_sent_at_us"),
            (self.server_processing_us, "server_processing_us"),
            (self.request_sent_monotonic_ns, "request_sent_monotonic_ns"),
            (self.response_received_monotonic_ns, "response_received_monotonic_ns"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.server_received_at_us <= 0 or self.server_sent_at_us < self.server_received_at_us:
            raise ValueError("private response server timing order is invalid")
        if self.server_processing_us != self.server_sent_at_us - self.server_received_at_us:
            raise ValueError("private response processing time is inconsistent")
        if self.response_received_monotonic_ns < self.request_sent_monotonic_ns:
            raise ValueError("private response monotonic timing order is invalid")

    @property
    def boundary(self) -> AccountResponseBoundary:
        round_trip_us = _ceil_div(
            self.response_received_monotonic_ns - self.request_sent_monotonic_ns,
            1_000,
        )
        uncertainty_us = max(0, round_trip_us - self.server_processing_us)
        server_received_at = _datetime_from_epoch_us(self.server_received_at_us)
        server_sent_at = _datetime_from_epoch_us(self.server_sent_at_us)
        return AccountResponseBoundary(
            server_received_at=server_received_at,
            server_sent_at=server_sent_at,
            known_at=server_sent_at + timedelta(microseconds=uncertainty_us),
            request_round_trip_ms=_ceil_div(
                self.response_received_monotonic_ns - self.request_sent_monotonic_ns,
                1_000_000,
            ),
        )


@dataclass(frozen=True)
class PrivateAuthGrant:
    boundary: AccountResponseBoundary
    access_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.access_token:
            raise ValueError("access token must be non-empty")


class PrivateAccountTransport(Protocol):
    def authenticate(self, *, client_id: str, client_secret: str) -> PrivateAuthGrant: ...

    def get_account_summary(self, grant: PrivateAuthGrant) -> PrivateRpcResponse: ...

    def get_positions(self, grant: PrivateAuthGrant) -> PrivateRpcResponse: ...


class DeribitPrivateHttpClient:
    """Fixed-host, fixed-method, one-shot Deribit private read-only client."""

    def __init__(
        self,
        *,
        environment: DeribitAccountEnvironment,
        timeout_seconds: float = 10.0,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        if environment is not DeribitAccountEnvironment.MAINNET:
            raise DeribitPrivateError("ENVIRONMENT_OUTSIDE_C1_ALLOWLIST")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.environment = environment
        self.timeout_seconds = timeout_seconds
        self._host, self._expected_testnet = _ENDPOINTS[environment]
        self._monotonic_ns = monotonic_ns or _continuous_monotonic_ns
        self._next_request_id = 1
        self._request_id_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(environment={self.environment.value!r})"

    def authenticate(self, *, client_id: str, client_secret: str) -> PrivateAuthGrant:
        if not isinstance(client_id, str) or not client_id:
            raise DeribitPrivateError("CREDENTIALS_NOT_PROVIDED")
        if not isinstance(client_secret, str) or not client_secret:
            raise DeribitPrivateError("CREDENTIALS_NOT_PROVIDED")
        response = self.call(
            "public/auth",
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": DERIBIT_REQUIRED_AUTH_SCOPE,
            },
        )
        result = _mapping(response.result, "AUTH_PAYLOAD_INVALID")
        access_token = _credential_text(result, "access_token", "AUTH_PAYLOAD_INVALID")
        if result.get("token_type") != "bearer":
            raise DeribitPrivateError("AUTH_PAYLOAD_INVALID")
        expires_in = _integer(result.get("expires_in"), "AUTH_PAYLOAD_INVALID")
        if expires_in <= 0:
            raise DeribitPrivateError("AUTH_PAYLOAD_INVALID")
        return PrivateAuthGrant(
            boundary=response.boundary,
            access_token=access_token,
        )

    def get_account_summary(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        return self.call(
            "private/get_account_summary",
            {"currency": "BTC", "extended": False},
            access_token=grant.access_token,
        )

    def get_positions(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        return self.call(
            "private/get_positions",
            {"currency": "BTC"},
            access_token=grant.access_token,
        )

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        access_token: str | None = None,
    ) -> PrivateRpcResponse:
        _validate_call(method, params, access_token=access_token)
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
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        connection = HTTPSConnection(self._host, timeout=self.timeout_seconds)
        request_sent_monotonic_ns = self._monotonic_ns()
        try:
            connection.request(
                "POST",
                f"/api/v2/{method}",
                body=body,
                headers=headers,
            )
            response = connection.getresponse()
            response_body = response.read()
            if response.status != 200:
                raise DeribitPrivateError(f"{_method_prefix(method)}_HTTP_ERROR")
            encoding = response.getheader("Content-Encoding")
            if encoding == "gzip":
                response_body = gzip.decompress(response_body)
            elif encoding not in (None, "", "identity"):
                raise DeribitPrivateError(f"{_method_prefix(method)}_ENCODING_UNKNOWN")
            response_received_monotonic_ns = self._monotonic_ns()
            payload = json.loads(response_body.decode("utf-8"))
        except DeribitPrivateError:
            raise
        except (
            OSError,
            EOFError,
            HTTPException,
            UnicodeDecodeError,
            gzip.BadGzipFile,
            json.JSONDecodeError,
        ):
            raise DeribitPrivateError(f"{_method_prefix(method)}_TRANSPORT_UNKNOWN") from None
        finally:
            connection.close()
        return _validated_private_response(
            payload,
            method=method,
            request_id=request_id,
            expected_testnet=self._expected_testnet,
            timeout_seconds=self.timeout_seconds,
            request_sent_monotonic_ns=request_sent_monotonic_ns,
            response_received_monotonic_ns=response_received_monotonic_ns,
        )


def capture_authenticated_account(
    *,
    transport: PrivateAccountTransport,
    environment: DeribitAccountEnvironment,
    client_id: str,
    client_secret: str,
) -> AuthenticatedAccountObservation:
    if environment is not DeribitAccountEnvironment.MAINNET:
        raise DeribitPrivateError("ENVIRONMENT_OUTSIDE_C1_ALLOWLIST")
    account_scope_id = account_scope_identity(environment, client_id)
    try:
        grant = transport.authenticate(client_id=client_id, client_secret=client_secret)
    except DeribitPrivateError as exc:
        return AuthenticatedAccountObservation(
            environment=environment,
            account_scope_id=account_scope_id,
            auth_boundary=None,
            summary=None,
            summary_boundary=None,
            positions=None,
            positions_boundary=None,
            blockers=(exc.code,),
        )
    summary: AuthenticatedAccountSummary | None = None
    summary_boundary: AccountResponseBoundary | None = None
    positions: tuple[AuthenticatedAccountPosition, ...] | None = None
    positions_boundary: AccountResponseBoundary | None = None
    blockers: list[str] = []
    try:
        response = transport.get_account_summary(grant)
        summary = _account_summary(response.result)
        summary_boundary = response.boundary
    except DeribitPrivateError as exc:
        blockers.append(exc.code)
    try:
        response = transport.get_positions(grant)
        positions = _account_positions(response.result)
        positions_boundary = response.boundary
    except DeribitPrivateError as exc:
        blockers.append(exc.code)
    return AuthenticatedAccountObservation(
        environment=environment,
        account_scope_id=account_scope_id,
        auth_boundary=grant.boundary,
        summary=summary,
        summary_boundary=summary_boundary,
        positions=positions,
        positions_boundary=positions_boundary,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _validate_call(
    method: str,
    params: Mapping[str, object],
    *,
    access_token: str | None,
) -> None:
    if method not in DERIBIT_PRIVATE_METHOD_ALLOWLIST:
        raise DeribitPrivateError("METHOD_OUTSIDE_C1_ALLOWLIST")
    if method == "public/auth":
        if access_token is not None or set(params) != {
            "grant_type",
            "client_id",
            "client_secret",
            "scope",
        }:
            raise DeribitPrivateError("AUTH_REQUEST_OUTSIDE_C1_BOUNDARY")
        if (
            params.get("grant_type") != "client_credentials"
            or params.get("scope") != DERIBIT_REQUIRED_AUTH_SCOPE
            or not isinstance(params.get("client_id"), str)
            or not params.get("client_id")
            or not isinstance(params.get("client_secret"), str)
            or not params.get("client_secret")
        ):
            raise DeribitPrivateError("AUTH_REQUEST_OUTSIDE_C1_BOUNDARY")
        return
    if not isinstance(access_token, str) or not access_token:
        raise DeribitPrivateError("PRIVATE_BEARER_TOKEN_MISSING")
    expected = (
        {"currency": "BTC", "extended": False}
        if method == "private/get_account_summary"
        else {"currency": "BTC"}
    )
    if dict(params) != expected:
        raise DeribitPrivateError("PRIVATE_REQUEST_OUTSIDE_C1_BOUNDARY")


def _validated_private_response(
    value: object,
    *,
    method: str,
    request_id: int,
    expected_testnet: bool,
    timeout_seconds: float,
    request_sent_monotonic_ns: int,
    response_received_monotonic_ns: int,
) -> PrivateRpcResponse:
    prefix = _method_prefix(method)
    root = _mapping(value, f"{prefix}_RESPONSE_INVALID")
    if (
        root.get("jsonrpc") != "2.0"
        or _integer(root.get("id"), f"{prefix}_RESPONSE_INVALID") != request_id
    ):
        raise DeribitPrivateError(f"{prefix}_RESPONSE_INVALID")
    if root.get("testnet") is not expected_testnet:
        raise DeribitPrivateError(f"{prefix}_ENVIRONMENT_MISMATCH")
    server_received_at_us = _integer(root.get("usIn"), f"{prefix}_TIMING_INVALID")
    server_sent_at_us = _integer(root.get("usOut"), f"{prefix}_TIMING_INVALID")
    server_processing_us = _integer(root.get("usDiff"), f"{prefix}_TIMING_INVALID")
    round_trip_us = _ceil_div(
        response_received_monotonic_ns - request_sent_monotonic_ns,
        1_000,
    )
    if (
        response_received_monotonic_ns < request_sent_monotonic_ns
        or server_received_at_us <= 0
        or server_sent_at_us < server_received_at_us
        or server_processing_us != server_sent_at_us - server_received_at_us
        or server_processing_us > round_trip_us
        or server_processing_us > int(timeout_seconds * 1_000_000)
        or round_trip_us > int(timeout_seconds * 1_000_000)
    ):
        raise DeribitPrivateError(f"{prefix}_TIMING_INVALID")
    has_result = "result" in root
    has_error = root.get("error") is not None
    if has_error or not has_result:
        raise DeribitPrivateError(f"{prefix}_RPC_REJECTED")
    try:
        response = PrivateRpcResponse(
            request_id=request_id,
            result=root["result"],
            testnet=expected_testnet,
            server_received_at_us=server_received_at_us,
            server_sent_at_us=server_sent_at_us,
            server_processing_us=server_processing_us,
            request_sent_monotonic_ns=request_sent_monotonic_ns,
            response_received_monotonic_ns=response_received_monotonic_ns,
        )
        _ = response.boundary
    except (OSError, OverflowError, ValueError):
        raise DeribitPrivateError(f"{prefix}_TIMING_INVALID") from None
    return response


def _account_summary(value: object) -> AuthenticatedAccountSummary:
    try:
        root = _mapping(value, "ACCOUNT_SUMMARY_PAYLOAD_INVALID")
        currency = _text(root, "currency", "ACCOUNT_SUMMARY_PAYLOAD_INVALID")
        if currency != "BTC":
            raise DeribitPrivateError("ACCOUNT_SUMMARY_CURRENCY_MISMATCH")
        return AuthenticatedAccountSummary(
            currency=currency,
            balance=_decimal(root, "balance"),
            equity=_decimal(root, "equity"),
            available_funds=_decimal(root, "available_funds"),
            initial_margin=_decimal(root, "initial_margin"),
            maintenance_margin=_decimal(root, "maintenance_margin"),
        )
    except DeribitPrivateError:
        raise
    except (InvalidOperation, TypeError, ValueError):
        raise DeribitPrivateError("ACCOUNT_SUMMARY_PAYLOAD_INVALID") from None


def _account_positions(value: object) -> tuple[AuthenticatedAccountPosition, ...]:
    if not isinstance(value, list):
        raise DeribitPrivateError("ACCOUNT_POSITIONS_PAYLOAD_INVALID")
    positions: list[AuthenticatedAccountPosition] = []
    try:
        for member in value:
            item = _mapping(member, "ACCOUNT_POSITIONS_PAYLOAD_INVALID")
            positions.append(
                AuthenticatedAccountPosition(
                    instrument_name=_text(
                        item,
                        "instrument_name",
                        "ACCOUNT_POSITIONS_PAYLOAD_INVALID",
                    ),
                    kind=AccountPositionKind(
                        _text(item, "kind", "ACCOUNT_POSITIONS_PAYLOAD_INVALID")
                    ),
                    direction=AccountPositionDirection(
                        _text(item, "direction", "ACCOUNT_POSITIONS_PAYLOAD_INVALID")
                    ),
                    size=_decimal(item, "size"),
                    average_price=_decimal(item, "average_price"),
                    mark_price=_decimal(item, "mark_price"),
                    floating_profit_loss=_decimal(item, "floating_profit_loss"),
                    total_profit_loss=_decimal(item, "total_profit_loss"),
                    initial_margin=_decimal(item, "initial_margin"),
                    maintenance_margin=_decimal(item, "maintenance_margin"),
                    delta=_decimal(item, "delta"),
                )
            )
    except (InvalidOperation, TypeError, ValueError):
        raise DeribitPrivateError("ACCOUNT_POSITIONS_PAYLOAD_INVALID") from None
    positions.sort(key=lambda position: position.instrument_name)
    names = tuple(position.instrument_name for position in positions)
    if len(names) != len(set(names)):
        raise DeribitPrivateError("ACCOUNT_POSITIONS_DUPLICATE_INSTRUMENT")
    return tuple(positions)


def _mapping(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise DeribitPrivateError(code)
    if any(not isinstance(key, str) for key in value):
        raise DeribitPrivateError(code)
    return dict(value)


def _text(value: Mapping[str, object], field: str, code: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise DeribitPrivateError(code)
    return item


def _credential_text(value: Mapping[str, object], field: str, code: str) -> str:
    item = _text(value, field, code)
    if len(item) > 8_192 or any(
        not character.isascii() or character.isspace() or not character.isprintable()
        for character in item
    ):
        raise DeribitPrivateError(code)
    return item


def _integer(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeribitPrivateError(code)
    return value


def _decimal(value: Mapping[str, object], field: str) -> Decimal:
    item = value.get(field)
    if isinstance(item, bool) or not isinstance(item, int | float | str):
        raise ValueError(f"{field} must be numeric")
    result = Decimal(str(item))
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _method_prefix(method: str) -> str:
    return {
        "public/auth": "AUTH",
        "private/get_account_summary": "ACCOUNT_SUMMARY",
        "private/get_positions": "ACCOUNT_POSITIONS",
    }.get(method, "PRIVATE")


def _datetime_from_epoch_us(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC)


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)

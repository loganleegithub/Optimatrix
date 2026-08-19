from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity, require_identity

DERIBIT_PRIVATE_ACCOUNT_SOURCE_ID = "DERIBIT_PRIVATE_HTTP_FIXED_READ_METHODS_V3"
DERIBIT_REQUESTED_READ_SCOPE = "account:read trade:read"
APPLICATION_METHOD_PERMISSION = "READ_ONLY_FIXED_ALLOWLIST"
ORDERS_EXECUTED = "NONE"
TOKEN_SCOPE_NORMALIZATION = "UNAVAILABLE"


class DeribitAccountEnvironment(StrEnum):
    MAINNET = "MAINNET"
    TESTNET = "TESTNET"


class AccountObservationStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class CredentialScopeCapability(StrEnum):
    USER_DECLARED_READ_ONLY = "USER_DECLARED_READ_ONLY"
    UNKNOWN = "UNKNOWN"


class AccountPositionKind(StrEnum):
    FUTURE = "future"
    OPTION = "option"
    FUTURE_COMBO = "future_combo"
    OPTION_COMBO = "option_combo"


class AccountPositionDirection(StrEnum):
    BUY = "buy"
    SELL = "sell"
    ZERO = "zero"


@dataclass(frozen=True)
class AccountResponseBoundary:
    server_received_at: datetime
    server_sent_at: datetime
    known_at: datetime
    request_round_trip_ms: int

    def __post_init__(self) -> None:
        received = _utc(self.server_received_at, "server_received_at")
        sent = _utc(self.server_sent_at, "server_sent_at")
        known = _utc(self.known_at, "known_at")
        if not received <= sent <= known:
            raise ValueError("account response boundary order is invalid")
        if (
            isinstance(self.request_round_trip_ms, bool)
            or not isinstance(self.request_round_trip_ms, int)
            or self.request_round_trip_ms < 0
        ):
            raise ValueError("request_round_trip_ms must be a non-negative integer")
        object.__setattr__(self, "server_received_at", received)
        object.__setattr__(self, "server_sent_at", sent)
        object.__setattr__(self, "known_at", known)

    def as_object(self) -> dict[str, object]:
        return {
            "server_received_at": _iso(self.server_received_at),
            "server_sent_at": _iso(self.server_sent_at),
            "known_at": _iso(self.known_at),
            "request_round_trip_ms": self.request_round_trip_ms,
        }


@dataclass(frozen=True)
class AuthenticatedAccountSummary:
    currency: str
    balance: Decimal
    equity: Decimal
    available_funds: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal

    def __post_init__(self) -> None:
        if self.currency != "BTC":
            raise ValueError("authenticated account summary currency must be BTC")
        for value, field in (
            (self.balance, "balance"),
            (self.equity, "equity"),
            (self.available_funds, "available_funds"),
            (self.initial_margin, "initial_margin"),
            (self.maintenance_margin, "maintenance_margin"),
        ):
            _finite(value, field)
        for value, field in (
            (self.initial_margin, "initial_margin"),
            (self.maintenance_margin, "maintenance_margin"),
        ):
            if value < 0:
                raise ValueError(f"{field} must be non-negative")

    def as_object(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "balance": str(self.balance),
            "equity": str(self.equity),
            "available_funds": str(self.available_funds),
            "initial_margin": str(self.initial_margin),
            "maintenance_margin": str(self.maintenance_margin),
        }


@dataclass(frozen=True)
class AuthenticatedAccountPosition:
    instrument_name: str
    kind: AccountPositionKind
    direction: AccountPositionDirection
    size: Decimal
    average_price: Decimal
    mark_price: Decimal
    floating_profit_loss: Decimal
    total_profit_loss: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal
    delta: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.instrument_name, str)
            or not self.instrument_name.startswith("BTC-")
            or len(self.instrument_name) > 128
            or not all(
                character.isascii() and (character.isalnum() or character in "-_")
                for character in self.instrument_name
            )
        ):
            raise ValueError("authenticated account position must be a BTC instrument")
        if not isinstance(self.kind, AccountPositionKind):
            raise ValueError("authenticated account position kind is unsupported")
        if not isinstance(self.direction, AccountPositionDirection):
            raise ValueError("authenticated account position direction is unsupported")
        for value, field in (
            (self.size, "size"),
            (self.average_price, "average_price"),
            (self.mark_price, "mark_price"),
            (self.floating_profit_loss, "floating_profit_loss"),
            (self.total_profit_loss, "total_profit_loss"),
            (self.initial_margin, "initial_margin"),
            (self.maintenance_margin, "maintenance_margin"),
            (self.delta, "delta"),
        ):
            _finite(value, field)
        for value, field in (
            (self.size, "size"),
            (self.average_price, "average_price"),
            (self.mark_price, "mark_price"),
            (self.initial_margin, "initial_margin"),
            (self.maintenance_margin, "maintenance_margin"),
        ):
            if value < 0:
                raise ValueError(f"{field} must be non-negative")
        if (self.direction is AccountPositionDirection.ZERO) != (self.size == 0):
            raise ValueError("account position direction and size are incoherent")

    def as_object(self) -> dict[str, object]:
        return {
            "instrument_name": self.instrument_name,
            "kind": self.kind.value,
            "direction": self.direction.value,
            "size": str(self.size),
            "average_price": str(self.average_price),
            "mark_price": str(self.mark_price),
            "floating_profit_loss": str(self.floating_profit_loss),
            "total_profit_loss": str(self.total_profit_loss),
            "initial_margin": str(self.initial_margin),
            "maintenance_margin": str(self.maintenance_margin),
            "delta": str(self.delta),
        }


@dataclass(frozen=True)
class AuthenticatedAccountObservation:
    environment: DeribitAccountEnvironment
    account_scope_id: str
    auth_boundary: AccountResponseBoundary | None
    summary: AuthenticatedAccountSummary | None
    summary_boundary: AccountResponseBoundary | None
    positions: tuple[AuthenticatedAccountPosition, ...] | None
    positions_boundary: AccountResponseBoundary | None
    blockers: tuple[str, ...]
    source_id: str = DERIBIT_PRIVATE_ACCOUNT_SOURCE_ID

    def __post_init__(self) -> None:
        if not isinstance(self.environment, DeribitAccountEnvironment):
            raise ValueError("authenticated account environment is unsupported")
        require_identity(self.account_scope_id, "account_scope_id")
        if self.source_id != DERIBIT_PRIVATE_ACCOUNT_SOURCE_ID:
            raise ValueError("authenticated account observation source is unsupported")
        if (self.summary is None) != (self.summary_boundary is None):
            raise ValueError("account summary and boundary must be present together")
        if (self.positions is None) != (self.positions_boundary is None):
            raise ValueError("account positions and boundary must be present together")
        if (self.summary is not None or self.positions is not None) and self.auth_boundary is None:
            raise ValueError("account components require a validated authentication boundary")
        if self.positions is not None:
            names = tuple(position.instrument_name for position in self.positions)
            if len(names) != len(set(names)):
                raise ValueError("authenticated account positions contain duplicate instruments")
            if tuple(sorted(names)) != names:
                raise ValueError("authenticated account positions must be ordered by instrument")
        if tuple(dict.fromkeys(self.blockers)) != self.blockers:
            raise ValueError("account observation blockers must be ordered and unique")
        if any(
            not blocker or blocker != blocker.upper() or not blocker.replace("_", "").isalnum()
            for blocker in self.blockers
        ):
            raise ValueError("account observation blockers must be safe identifier codes")
        complete = self.summary is not None and self.positions is not None
        if complete == bool(self.blockers):
            raise ValueError("account observation completeness and blockers are incoherent")

    @property
    def status(self) -> AccountObservationStatus:
        if self.summary is not None and self.positions is not None:
            return AccountObservationStatus.KNOWN
        return AccountObservationStatus.UNKNOWN

    @property
    def known_at(self) -> datetime | None:
        boundaries = tuple(
            boundary.known_at
            for boundary in (
                self.auth_boundary,
                self.summary_boundary,
                self.positions_boundary,
            )
            if boundary is not None
        )
        return max(boundaries, default=None)

    @property
    def credential_scope(self) -> CredentialScopeCapability:
        if self.environment is DeribitAccountEnvironment.MAINNET and self.auth_boundary is not None:
            return CredentialScopeCapability.USER_DECLARED_READ_ONLY
        return CredentialScopeCapability.UNKNOWN

    @property
    def token_scope_normalization(self) -> str:
        return TOKEN_SCOPE_NORMALIZATION

    @property
    def identity(self) -> str:
        return canonical_identity(
            "AuthenticatedAccountObservationV3",
            self.environment,
            self.account_scope_id,
            self.auth_boundary,
            self.summary,
            self.summary_boundary,
            self.positions,
            self.positions_boundary,
            self.blockers,
            self.source_id,
        )

    def as_object(self) -> dict[str, object]:
        return {
            "account_observation_id": self.identity,
            "environment": self.environment.value,
            "truth_layer": "PRIVATE_EXECUTION",
            "credential_scope": self.credential_scope.value,
            "application_method_permission": APPLICATION_METHOD_PERMISSION,
            "orders_executed": ORDERS_EXECUTED,
            "source_id": self.source_id,
            "account_scope_id": self.account_scope_id,
            "status": self.status.value,
            "known_at": _iso(self.known_at) if self.known_at is not None else None,
            "requested_token_scope": DERIBIT_REQUESTED_READ_SCOPE,
            "token_scope_normalization": self.token_scope_normalization,
            "auth_boundary": (
                self.auth_boundary.as_object() if self.auth_boundary is not None else None
            ),
            "summary_status": "KNOWN" if self.summary is not None else "UNKNOWN",
            "summary": self.summary.as_object() if self.summary is not None else None,
            "summary_boundary": (
                self.summary_boundary.as_object() if self.summary_boundary is not None else None
            ),
            "positions_status": "KNOWN" if self.positions is not None else "UNKNOWN",
            "position_count": len(self.positions) if self.positions is not None else None,
            "positions": (
                [position.as_object() for position in self.positions]
                if self.positions is not None
                else None
            ),
            "positions_boundary": (
                self.positions_boundary.as_object() if self.positions_boundary is not None else None
            ),
            "blockers": list(self.blockers),
        }


def account_scope_identity(environment: DeribitAccountEnvironment, client_id: str) -> str:
    if not isinstance(environment, DeribitAccountEnvironment):
        raise ValueError("account environment is unsupported")
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("client id must be non-empty")
    return canonical_identity("DeribitAccountScopeV1", environment, client_id)


def _finite(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    return value


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

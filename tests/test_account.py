from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.account import (
    APPLICATION_METHOD_PERMISSION,
    ORDERS_EXECUTED,
    AccountObservationStatus,
    AccountPositionDirection,
    AccountPositionKind,
    AccountResponseBoundary,
    AuthenticatedAccountObservation,
    AuthenticatedAccountPosition,
    AuthenticatedAccountSummary,
    CredentialScopeCapability,
    DeribitAccountEnvironment,
    account_scope_identity,
)


def _boundary(offset_seconds: int = 0) -> AccountResponseBoundary:
    received = datetime(2026, 8, 15, 12, 0, offset_seconds, tzinfo=UTC)
    return AccountResponseBoundary(
        server_received_at=received,
        server_sent_at=received + timedelta(milliseconds=2),
        known_at=received + timedelta(milliseconds=5),
        request_round_trip_ms=5,
    )


def _summary() -> AuthenticatedAccountSummary:
    return AuthenticatedAccountSummary(
        currency="BTC",
        balance=Decimal("1.2"),
        equity=Decimal("1.1"),
        available_funds=Decimal("0.8"),
        initial_margin=Decimal("0.2"),
        maintenance_margin=Decimal("0.1"),
    )


def _position(name: str = "BTC-15AUG26-60000-C") -> AuthenticatedAccountPosition:
    return AuthenticatedAccountPosition(
        instrument_name=name,
        kind=AccountPositionKind.OPTION,
        direction=AccountPositionDirection.SELL,
        size=Decimal("0.1"),
        average_price=Decimal("0.003"),
        mark_price=Decimal("0.002"),
        floating_profit_loss=Decimal("0.001"),
        total_profit_loss=Decimal("0.001"),
        initial_margin=Decimal("0.02"),
        maintenance_margin=Decimal("0.01"),
        delta=Decimal("-0.2"),
    )


def test_complete_mainnet_observation_separates_declared_credential_and_method_truth() -> None:
    client_id = "client-id-must-not-serialize"
    secret = "secret-must-not-serialize"
    token = "token-must-not-serialize"
    observation = AuthenticatedAccountObservation(
        environment=DeribitAccountEnvironment.MAINNET,
        account_scope_id=account_scope_identity(DeribitAccountEnvironment.MAINNET, client_id),
        auth_boundary=_boundary(),
        summary=_summary(),
        summary_boundary=_boundary(1),
        positions=(_position(),),
        positions_boundary=_boundary(2),
        blockers=(),
    )

    assert observation.status is AccountObservationStatus.KNOWN
    assert observation.known_at == _boundary(2).known_at
    value = observation.as_object()
    assert value["truth_layer"] == "PRIVATE_EXECUTION"
    assert observation.credential_scope is CredentialScopeCapability.USER_DECLARED_READ_ONLY
    assert value["credential_scope"] == "USER_DECLARED_READ_ONLY"
    assert value["token_scope_normalization"] == "UNAVAILABLE"
    assert value["requested_token_scope"] == "account:read trade:read"
    assert "effective_scopes" not in value
    assert value["application_method_permission"] == APPLICATION_METHOD_PERMISSION
    assert value["orders_executed"] == ORDERS_EXECUTED
    serialized = json.dumps(value, sort_keys=True)
    for sensitive in (client_id, secret, token):
        assert sensitive not in serialized


def test_uncaptured_testnet_observation_cannot_claim_declared_mainnet_scope() -> None:
    observation = AuthenticatedAccountObservation(
        environment=DeribitAccountEnvironment.TESTNET,
        account_scope_id=account_scope_identity(
            DeribitAccountEnvironment.TESTNET,
            "safe-client",
        ),
        auth_boundary=None,
        summary=None,
        summary_boundary=None,
        positions=None,
        positions_boundary=None,
        blockers=("ENVIRONMENT_OUTSIDE_C1_ALLOWLIST",),
    )

    assert observation.credential_scope is CredentialScopeCapability.UNKNOWN
    assert observation.token_scope_normalization == "UNAVAILABLE"


def test_partial_observation_remains_unknown_and_does_not_infer_empty_positions() -> None:
    observation = AuthenticatedAccountObservation(
        environment=DeribitAccountEnvironment.MAINNET,
        account_scope_id=account_scope_identity(
            DeribitAccountEnvironment.MAINNET,
            "safe-client",
        ),
        auth_boundary=_boundary(),
        summary=_summary(),
        summary_boundary=_boundary(1),
        positions=None,
        positions_boundary=None,
        blockers=("ACCOUNT_POSITIONS_RPC_REJECTED",),
    )

    assert observation.status is AccountObservationStatus.UNKNOWN
    value = observation.as_object()
    assert value["credential_scope"] == "USER_DECLARED_READ_ONLY"
    assert value["token_scope_normalization"] == "UNAVAILABLE"
    assert value["summary_status"] == "KNOWN"
    assert value["positions_status"] == "UNKNOWN"
    assert value["position_count"] is None
    assert value["positions"] is None


def test_duplicate_positions_and_non_finite_account_numbers_fail_closed() -> None:
    position = _position()
    with pytest.raises(ValueError, match="duplicate instruments"):
        AuthenticatedAccountObservation(
            environment=DeribitAccountEnvironment.MAINNET,
            account_scope_id=account_scope_identity(
                DeribitAccountEnvironment.MAINNET,
                "safe-client",
            ),
            auth_boundary=_boundary(),
            summary=_summary(),
            summary_boundary=_boundary(1),
            positions=(position, position),
            positions_boundary=_boundary(2),
            blockers=(),
        )

    with pytest.raises(ValueError, match="finite Decimal"):
        AuthenticatedAccountSummary(
            currency="BTC",
            balance=Decimal("NaN"),
            equity=Decimal("1"),
            available_funds=Decimal("1"),
            initial_margin=Decimal("0"),
            maintenance_margin=Decimal("0"),
        )


def test_account_response_boundary_rejects_naive_or_reversed_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AccountResponseBoundary(
            server_received_at=datetime(2026, 8, 15, 12),
            server_sent_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
            known_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
            request_round_trip_ms=0,
        )
    with pytest.raises(ValueError, match="order"):
        AccountResponseBoundary(
            server_received_at=datetime(2026, 8, 15, 12, 0, 1, tzinfo=UTC),
            server_sent_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
            known_at=datetime(2026, 8, 15, 12, 0, 2, tzinfo=UTC),
            request_round_trip_ms=1,
        )

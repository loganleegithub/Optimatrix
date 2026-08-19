from __future__ import annotations

from collections.abc import Mapping

import pytest

from optimatrix.account import DeribitAccountEnvironment
from optimatrix.combo_cli import run
from optimatrix.deribit_combo import ComboAuthGrant, DeribitComboError
from optimatrix.private_cli import PrivateCredentials

_CLIENT_ID = "cli-combo-id-must-not-leak"
_CLIENT_SECRET = "cli-combo-secret-must-not-leak"
_TOKEN = "cli-combo-token-must-not-leak"
_COMBO = "BTC-FS-21AUG26_28AUG26"


class _Reader:
    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials:
        assert environment is DeribitAccountEnvironment.TESTNET
        return PrivateCredentials(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)


class _NoFillTransport:
    def __init__(self, *, no_combo: bool = False) -> None:
        self.no_combo = no_combo
        self.state_calls = 0

    def authenticate(self, *, client_id: str, client_secret: str) -> ComboAuthGrant:
        assert client_id == _CLIENT_ID
        assert client_secret == _CLIENT_SECRET
        return ComboAuthGrant(access_token=_TOKEN)

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        grant: ComboAuthGrant | None = None,
    ) -> object:
        del params
        if method.startswith("private/"):
            assert grant is not None and grant.access_token == _TOKEN
        if method == "private/get_positions":
            return []
        if method == "public/get_combos":
            if self.no_combo:
                return []
            return [
                {
                    "id": _COMBO,
                    "state": "active",
                    "legs": [
                        {"instrument_name": "BTC-21AUG26", "amount": 1},
                        {"instrument_name": "BTC-28AUG26", "amount": -1},
                    ],
                }
            ]
        if method == "public/get_instrument":
            return {
                "instrument_name": _COMBO,
                "kind": "future_combo",
                "base_currency": "BTC",
                "is_active": True,
                "state": "open",
                "expiration_timestamp": 1_787_086_400_000,
                "min_trade_amount": 10,
                "tick_size": 0.5,
            }
        if method == "public/get_order_book":
            return {
                "instrument_name": _COMBO,
                "state": "open",
                "bids": [[1.5, 20]],
                "asks": [[2, 20]],
            }
        if method == "private/buy":
            return {"order": self._order("open"), "trades": []}
        if method == "private/get_order_state":
            self.state_calls += 1
            return self._order("open" if self.state_calls == 1 else "cancelled")
        if method == "private/get_user_trades_by_order":
            return []
        if method == "private/cancel":
            return self._order("cancelled")
        raise AssertionError(method)

    @staticmethod
    def _order(state: str) -> dict[str, object]:
        return {
            "order_id": "safe-order-id",
            "instrument_name": _COMBO,
            "direction": "buy",
            "order_state": state,
            "amount": 10,
            "filled_amount": 0,
            "post_only": True,
            "reduce_only": False,
        }


def test_cli_runs_fixed_testnet_no_fill_closure_and_prints_only_safe_receipt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run(
        [],
        credential_reader=_Reader(),
        transport_factory=_NoFillTransport,
        now_ms=lambda: 1_787_000_000_000,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert '"environment": "TESTNET"' in output
    assert '"permission": "PRIVATE_EXECUTION"' in output
    assert '"capital": "NO_REAL_CAPITAL"' in output
    assert '"outcome": "NO_FILL_CANCELLED"' in output
    assert '"entry_filled_amount": "0"' in output
    assert '"actual_entry_fees": {}' in output
    assert '"reduce_only_exit": "NOT_APPLICABLE_NO_FILL"' in output
    for secret in (_CLIENT_ID, _CLIENT_SECRET, _TOKEN):
        assert secret not in output


def test_cli_no_suitable_combo_is_truthful_nonzero_connectivity_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run(
        [],
        credential_reader=_Reader(),
        transport_factory=lambda: _NoFillTransport(no_combo=True),
        now_ms=lambda: 1_787_000_000_000,
    )

    output = capsys.readouterr().out
    assert result == 2
    assert '"status": "BLOCKED"' in output
    assert '"outcome": "NO_SUITABLE_ACTIVE_COMBO"' in output
    assert '"entry_order_id": null' in output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--client-secret", _CLIENT_SECRET],
        [f"--token={_TOKEN}"],
        ["--environment", "mainnet"],
        ["--host", "www.deribit.com"],
    ],
)
def test_cli_rejects_credentials_environment_and_host_arguments_without_echo(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run(arguments, credential_reader=_Reader())

    output = capsys.readouterr().out
    assert result == 2
    assert output == '{"error": "CREDENTIAL_OR_ENVIRONMENT_ARGUMENT_FORBIDDEN"}\n'
    assert _CLIENT_SECRET not in output
    assert _TOKEN not in output


def test_cli_redacts_unexpected_transport_error_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> _NoFillTransport:
        raise ValueError(_CLIENT_SECRET)

    result = run(
        [],
        credential_reader=_Reader(),
        transport_factory=fail,
        now_ms=lambda: 1_787_000_000_000,
    )

    output = capsys.readouterr().out
    assert result == 2
    assert output == '{"error": "TESTNET_COMBO_LIFECYCLE_FAILED"}\n'
    assert _CLIENT_SECRET not in output


def test_cli_redacts_safe_protocol_error_and_does_not_print_exchange_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Rejected(_NoFillTransport):
        def authenticate(self, *, client_id: str, client_secret: str) -> ComboAuthGrant:
            del client_id, client_secret
            raise DeribitComboError("PUBLIC_AUTH_RPC_REJECTED", exchange_code=13009)

    result = run(
        [],
        credential_reader=_Reader(),
        transport_factory=_Rejected,
        now_ms=lambda: 1_787_000_000_000,
    )

    output = capsys.readouterr().out
    assert result == 2
    assert '"blockers": ["PUBLIC_AUTH_RPC_REJECTED"]' in output
    assert '"exchange_error_code": 13009' in output
    for secret in (_CLIENT_ID, _CLIENT_SECRET):
        assert secret not in output

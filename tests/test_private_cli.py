from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from optimatrix.account import DeribitAccountEnvironment
from optimatrix.deribit_private import (
    DeribitPrivateError,
    PrivateAuthGrant,
    PrivateRpcResponse,
)
from optimatrix.private_cli import CredentialFileReader, PrivateCredentials, run
from optimatrix.workbench import WorkbenchExport

_CLIENT_ID = "cli-client-id-must-not-leak"
_CLIENT_SECRET = "cli-client-secret-must-not-leak"
_ACCESS_TOKEN = "cli-access-token-must-not-leak"


def _response(result: object, request_id: int) -> PrivateRpcResponse:
    return PrivateRpcResponse(
        request_id=request_id,
        result=result,
        testnet=False,
        server_received_at_us=1_787_000_000_000_000,
        server_sent_at_us=1_787_000_000_002_000,
        server_processing_us=2_000,
        request_sent_monotonic_ns=1_000_000_000,
        response_received_monotonic_ns=1_005_000_000,
    )


class _Reader:
    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials:
        assert environment is DeribitAccountEnvironment.MAINNET
        return PrivateCredentials(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)


class _Transport:
    def __init__(self, *, position_error: bool = False) -> None:
        self.position_error = position_error

    def authenticate(self, *, client_id: str, client_secret: str) -> PrivateAuthGrant:
        assert client_id == _CLIENT_ID
        assert client_secret == _CLIENT_SECRET
        return PrivateAuthGrant(
            boundary=_response({}, 1).boundary,
            access_token=_ACCESS_TOKEN,
        )

    def get_account_summary(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        assert grant.access_token == _ACCESS_TOKEN
        return _response(
            {
                "currency": "BTC",
                "balance": 1,
                "equity": 1,
                "available_funds": 1,
                "initial_margin": 0,
                "maintenance_margin": 0,
            },
            2,
        )

    def get_positions(self, grant: PrivateAuthGrant) -> PrivateRpcResponse:
        assert grant.access_token == _ACCESS_TOKEN
        if self.position_error:
            raise DeribitPrivateError("ACCOUNT_POSITIONS_RPC_REJECTED")
        return _response([], 3)


def _arguments(snapshot: Path, output_dir: Path) -> list[str]:
    return [
        "--environment",
        "mainnet",
        "--snapshot",
        str(snapshot),
        "--output-dir",
        str(output_dir),
    ]


def _snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"safe": "snapshot"}), encoding="utf-8")
    return path


def _credential_file(tmp_path: Path, content: str, *, mode: int = 0o600) -> Path:
    path = tmp_path / "credentials.env"
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def _export(output_dir: Path) -> WorkbenchExport:
    return WorkbenchExport(
        output_dir=output_dir,
        index_path=output_dir / "index.html",
        data_path=output_dir / "workbench-data.js",
        stylesheet_path=output_dir / "styles.css",
        script_path=output_dir / "app.js",
    )


def test_cli_uses_injected_credentials_without_argv_or_output_leakage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(tmp_path)
    output_dir = tmp_path / "workbench"
    captured: dict[str, object] = {}

    def fake_write(
        value: object,
        destination: Path,
        **kwargs: object,
    ) -> WorkbenchExport:
        captured["snapshot"] = value
        captured["account"] = kwargs["account_observation"]
        return _export(destination)

    monkeypatch.setattr("optimatrix.private_cli.write_workbench", fake_write)
    result = run(
        _arguments(snapshot, output_dir),
        credential_reader=_Reader(),
        transport_factory=lambda environment: _Transport(),
    )

    assert result == 0
    output = capsys.readouterr().out
    assert '"credential_scope": "USER_DECLARED_READ_ONLY"' in output
    assert '"token_scope_normalization": "UNAVAILABLE"' in output
    assert '"application_method_permission": "READ_ONLY_FIXED_ALLOWLIST"' in output
    assert '"orders_executed": "NONE"' in output
    assert _CLIENT_ID not in output
    assert _CLIENT_SECRET not in output
    assert _ACCESS_TOKEN not in output
    serialized = json.dumps(captured["account"].as_object(), sort_keys=True)  # type: ignore[union-attr]
    assert _CLIENT_ID not in serialized
    assert _CLIENT_SECRET not in serialized
    assert _ACCESS_TOKEN not in serialized


def test_cli_partial_capture_writes_truthful_unknown_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(tmp_path)
    output_dir = tmp_path / "workbench"
    captured: dict[str, object] = {}

    def fake_write(
        value: object,
        destination: Path,
        **kwargs: object,
    ) -> WorkbenchExport:
        del value
        captured["account"] = kwargs["account_observation"]
        return _export(destination)

    monkeypatch.setattr("optimatrix.private_cli.write_workbench", fake_write)
    result = run(
        _arguments(snapshot, output_dir),
        credential_reader=_Reader(),
        transport_factory=lambda environment: _Transport(position_error=True),
    )

    assert result == 2
    output = capsys.readouterr().out
    assert '"status": "UNKNOWN"' in output
    assert "ACCOUNT_POSITIONS_RPC_REJECTED" in output
    observation = captured["account"]
    assert observation.as_object()["positions"] is None  # type: ignore[union-attr]


def test_cli_rejects_credential_arguments_without_echoing_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run(["--client-secret", _CLIENT_SECRET])
    output = capsys.readouterr().out
    assert result == 2
    assert "CREDENTIAL_ARGUMENT_FORBIDDEN" in output
    assert _CLIENT_SECRET not in output


def test_cli_rejects_testnet_before_reading_credentials(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run(
        [
            "--environment",
            "testnet",
            "--snapshot",
            str(_snapshot(tmp_path)),
            "--output-dir",
            str(tmp_path / "workbench"),
        ],
        credential_reader=_Reader(),
    )

    assert result == 2
    assert capsys.readouterr().out == '{"error": "CLI_ARGUMENTS_INVALID"}\n'


def test_cli_non_tty_fails_closed_instead_of_echoing_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "optimatrix.private_cli.sys.stdin",
        SimpleNamespace(isatty=lambda: False),
    )
    result = run(_arguments(snapshot, tmp_path / "workbench"))

    output = capsys.readouterr().out
    assert result == 2
    assert output == '{"error": "CREDENTIALS_NOT_PROVIDED"}\n'


def test_cli_redacts_exception_text_from_workbench_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(tmp_path)

    def fail_write(*args: object, **kwargs: object) -> WorkbenchExport:
        del args, kwargs
        raise ValueError(_CLIENT_SECRET)

    monkeypatch.setattr("optimatrix.private_cli.write_workbench", fail_write)
    result = run(
        _arguments(snapshot, tmp_path / "workbench"),
        credential_reader=_Reader(),
        transport_factory=lambda environment: _Transport(),
    )

    output = capsys.readouterr().out
    assert result == 2
    assert "PRIVATE_WORKBENCH_WRITE_FAILED" in output
    assert _CLIENT_SECRET not in output


def test_credential_file_selects_only_the_requested_environment_and_hides_values(
    tmp_path: Path,
) -> None:
    mainnet_id = "mainnet-id-must-not-leak"
    mainnet_secret = "mainnet-secret-must-not-leak"
    testnet_id = "testnet-id-must-not-leak"
    testnet_secret = "testnet-secret-must-not-leak"
    path = _credential_file(
        tmp_path,
        "\n".join(
            (
                f"DERIBIT_MAINNET_CLIENT_ID={mainnet_id}",
                f"DERIBIT_MAINNET_CLIENT_SECRET={mainnet_secret}",
                f"DERIBIT_TESTNET_CLIENT_ID={testnet_id}",
                f"DERIBIT_TESTNET_CLIENT_SECRET={testnet_secret}",
            )
        )
        + "\n",
    )
    reader = CredentialFileReader(path)

    credentials = reader.read(DeribitAccountEnvironment.TESTNET)

    assert credentials.client_id == testnet_id
    assert credentials.client_secret == testnet_secret
    safe_text = f"{reader!r} {credentials!r}"
    for value in (mainnet_id, mainnet_secret, testnet_id, testnet_secret):
        assert value not in safe_text


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (
            "DERIBIT_TESTNET_CLIENT_ID=one\nDERIBIT_TESTNET_CLIENT_ID=two\n"
            "DERIBIT_TESTNET_CLIENT_SECRET=secret\n",
            "CREDENTIAL_FILE_DUPLICATE_KEY",
        ),
        (
            "DERIBIT_TESTNET_CLIENT_ID=one\nDERIBIT_TESTNET_CLIENT_SECRET=secret\n"
            "UNEXPECTED_KEY=value\n",
            "CREDENTIAL_FILE_UNKNOWN_KEY",
        ),
        (
            'DERIBIT_TESTNET_CLIENT_ID="quoted"\nDERIBIT_TESTNET_CLIENT_SECRET=secret\n',
            "CREDENTIAL_FILE_FORMAT_INVALID",
        ),
        (
            "DERIBIT_TESTNET_CLIENT_ID=$(command)\nDERIBIT_TESTNET_CLIENT_SECRET=secret\n",
            "CREDENTIAL_FILE_FORMAT_INVALID",
        ),
    ],
)
def test_credential_file_rejects_duplicate_unknown_quote_and_shell_syntax_without_leakage(
    tmp_path: Path,
    content: str,
    code: str,
) -> None:
    path = _credential_file(tmp_path, content)

    with pytest.raises(DeribitPrivateError) as error:
        CredentialFileReader(path).read(DeribitAccountEnvironment.TESTNET)

    assert str(error.value) == code
    assert content not in str(error.value)
    assert str(path) not in str(error.value)


def test_credential_file_rejects_mode_symlink_nonregular_owner_and_environment_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "DERIBIT_MAINNET_CLIENT_ID=main-id\nDERIBIT_MAINNET_CLIENT_SECRET=main-secret\n"
    broad = _credential_file(tmp_path, content, mode=0o644)
    with pytest.raises(DeribitPrivateError, match="CREDENTIAL_FILE_MODE_INVALID"):
        CredentialFileReader(broad).read(DeribitAccountEnvironment.MAINNET)

    broad.chmod(0o600)
    link = tmp_path / "credentials-link.env"
    link.symlink_to(broad)
    with pytest.raises(DeribitPrivateError, match="CREDENTIAL_FILE_SYMLINK_FORBIDDEN"):
        CredentialFileReader(link).read(DeribitAccountEnvironment.MAINNET)

    directory = tmp_path / "credentials-directory"
    directory.mkdir()
    with pytest.raises(DeribitPrivateError, match="CREDENTIAL_FILE_NOT_REGULAR"):
        CredentialFileReader(directory).read(DeribitAccountEnvironment.MAINNET)

    owner = broad.stat().st_uid
    monkeypatch.setattr("optimatrix.private_cli.os.geteuid", lambda: owner + 1)
    with pytest.raises(DeribitPrivateError, match="CREDENTIAL_FILE_OWNER_INVALID"):
        CredentialFileReader(broad).read(DeribitAccountEnvironment.MAINNET)
    monkeypatch.undo()

    with pytest.raises(
        DeribitPrivateError,
        match="CREDENTIAL_FILE_ENVIRONMENT_MISMATCH",
    ):
        CredentialFileReader(broad).read(DeribitAccountEnvironment.TESTNET)


def test_cli_credential_file_success_does_not_write_secrets_to_output_or_workbench(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _credential_file(
        tmp_path,
        f"DERIBIT_MAINNET_CLIENT_ID={_CLIENT_ID}\nDERIBIT_MAINNET_CLIENT_SECRET={_CLIENT_SECRET}\n",
    )
    snapshot = _snapshot(tmp_path)
    output_dir = tmp_path / "workbench"
    captured: dict[str, object] = {}

    def fake_write(
        value: object,
        destination: Path,
        **kwargs: object,
    ) -> WorkbenchExport:
        del value
        captured["account"] = kwargs["account_observation"]
        return _export(destination)

    monkeypatch.setattr("optimatrix.private_cli.write_workbench", fake_write)
    result = run(
        [*_arguments(snapshot, output_dir), "--credentials-file", str(path)],
        transport_factory=lambda environment: _Transport(),
    )

    streams = capsys.readouterr()
    assert result == 0
    serialized = json.dumps(captured["account"].as_object())  # type: ignore[union-attr]
    for value in (_CLIENT_ID, _CLIENT_SECRET, _ACCESS_TOKEN):
        assert value not in streams.out
        assert value not in streams.err
        assert value not in serialized


def test_cli_credential_file_failure_reports_only_a_safe_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _credential_file(
        tmp_path,
        f"DERIBIT_MAINNET_CLIENT_ID={_CLIENT_ID}\nDERIBIT_MAINNET_CLIENT_SECRET={_CLIENT_SECRET}\n",
        mode=0o644,
    )
    snapshot = _snapshot(tmp_path)

    result = run(
        [
            *_arguments(snapshot, tmp_path / "workbench"),
            "--credentials-file",
            str(path),
        ],
        transport_factory=lambda environment: _Transport(),
    )

    streams = capsys.readouterr()
    assert result == 2
    assert streams.out == '{"error": "CREDENTIAL_FILE_MODE_INVALID"}\n'
    assert streams.err == ""
    for value in (str(path), _CLIENT_ID, _CLIENT_SECRET, _ACCESS_TOKEN):
        assert value not in streams.out
        assert value not in streams.err

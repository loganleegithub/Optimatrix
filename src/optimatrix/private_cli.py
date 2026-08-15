from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, Protocol

from optimatrix.account import (
    APPLICATION_METHOD_PERMISSION,
    ORDERS_EXECUTED,
    AccountObservationStatus,
    DeribitAccountEnvironment,
)
from optimatrix.deribit_private import (
    DeribitPrivateError,
    DeribitPrivateHttpClient,
    PrivateAccountTransport,
    capture_authenticated_account,
)
from optimatrix.workbench import write_workbench


@dataclass(frozen=True)
class PrivateCredentials:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.client_id, str)
            or not self.client_id
            or not isinstance(self.client_secret, str)
            or not self.client_secret
        ):
            raise DeribitPrivateError("CREDENTIALS_NOT_PROVIDED")


class PrivateCredentialReader(Protocol):
    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials: ...


class NoEchoCredentialReader:
    """Read one client identifier and secret without placing either in argv."""

    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials:
        if not sys.stdin.isatty():
            raise DeribitPrivateError("CREDENTIALS_NOT_PROVIDED")
        label = environment.value.lower()
        try:
            client_id = getpass.getpass(f"Deribit {label} client id: ")
            client_secret = getpass.getpass(f"Deribit {label} client secret: ")
        except (EOFError, KeyboardInterrupt):
            raise DeribitPrivateError("CREDENTIALS_NOT_PROVIDED") from None
        return PrivateCredentials(client_id=client_id, client_secret=client_secret)


@dataclass(frozen=True)
class CredentialFileReader:
    path: Path

    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials:
        selected_keys = {
            DeribitAccountEnvironment.MAINNET: (
                "DERIBIT_MAINNET_CLIENT_ID",
                "DERIBIT_MAINNET_CLIENT_SECRET",
            ),
            DeribitAccountEnvironment.TESTNET: (
                "DERIBIT_TESTNET_CLIENT_ID",
                "DERIBIT_TESTNET_CLIENT_SECRET",
            ),
        }[environment]
        selected = _read_credential_file(self.path, selected_keys=selected_keys)
        return PrivateCredentials(
            client_id=selected[selected_keys[0]],
            client_secret=selected[selected_keys[1]],
        )


TransportFactory = Callable[[DeribitAccountEnvironment], PrivateAccountTransport]


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise DeribitPrivateError("CLI_ARGUMENTS_INVALID")


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def run(
    argv: list[str] | None = None,
    *,
    credential_reader: PrivateCredentialReader | None = None,
    transport_factory: TransportFactory | None = None,
) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if any(
        argument == forbidden or argument.startswith(f"{forbidden}=")
        for argument in raw_arguments
        for forbidden in (
            "--client-id",
            "--client-secret",
            "--access-token",
            "--refresh-token",
            "--secret",
            "--token",
        )
    ):
        _print_safe_error("CREDENTIAL_ARGUMENT_FORBIDDEN")
        return 2

    parser = _SafeArgumentParser(prog="optimatrix-account")
    parser.add_argument(
        "--environment",
        required=True,
        choices=("mainnet",),
        help="fixed Deribit account environment",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="existing Public Shadow snapshot JSON to project beside the account capture",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="explicit owner-only 0600 credential file; never searched or auto-loaded",
    )
    try:
        args = parser.parse_args(raw_arguments)
    except DeribitPrivateError as exc:
        _print_safe_error(exc.code)
        return 2

    try:
        snapshot = _read_snapshot(args.snapshot)
    except DeribitPrivateError as exc:
        _print_safe_error(exc.code)
        return 2

    environment = DeribitAccountEnvironment(args.environment.upper())
    if credential_reader is not None and args.credentials_file is not None:
        _print_safe_error("CLI_ARGUMENTS_INVALID")
        return 2
    reader = credential_reader or (
        CredentialFileReader(args.credentials_file)
        if args.credentials_file is not None
        else NoEchoCredentialReader()
    )
    factory = transport_factory or _http_transport
    try:
        credentials = reader.read(environment)
        transport = factory(environment)
        observation = capture_authenticated_account(
            transport=transport,
            environment=environment,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
        )
        del credentials
        exported = write_workbench(
            snapshot,
            args.output_dir,
            account_observation=observation,
        )
    except DeribitPrivateError as exc:
        _print_safe_error(exc.code)
        return 2
    except (OSError, TypeError, ValueError):
        _print_safe_error("PRIVATE_WORKBENCH_WRITE_FAILED")
        return 2

    print(
        json.dumps(
            {
                "mode": "AUTHENTICATED ACCOUNT OBSERVATION",
                "environment": environment.value,
                "credential_scope": observation.credential_scope.value,
                "requested_token_scope": "account:read trade:read",
                "token_scope_normalization": observation.token_scope_normalization,
                "application_method_permission": APPLICATION_METHOD_PERMISSION,
                "orders_executed": ORDERS_EXECUTED,
                "status": observation.status.value,
                "completeness": (
                    "COMPLETE"
                    if observation.status is AccountObservationStatus.KNOWN
                    else "PARTIAL_OR_UNKNOWN"
                ),
                "blockers": list(observation.blockers),
                "workbench": str(exported.index_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if observation.status is AccountObservationStatus.KNOWN else 2


def _http_transport(environment: DeribitAccountEnvironment) -> PrivateAccountTransport:
    return DeribitPrivateHttpClient(environment=environment)


def _read_snapshot(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise DeribitPrivateError("PUBLIC_SNAPSHOT_UNREADABLE") from None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DeribitPrivateError("PUBLIC_SNAPSHOT_INVALID")
    return value


_CREDENTIAL_FILE_KEYS = frozenset(
    {
        "DERIBIT_MAINNET_CLIENT_ID",
        "DERIBIT_MAINNET_CLIENT_SECRET",
        "DERIBIT_TESTNET_CLIENT_ID",
        "DERIBIT_TESTNET_CLIENT_SECRET",
    }
)
_CREDENTIAL_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_CREDENTIAL_VALUE_PATTERN = re.compile(r"[A-Za-z0-9._:/+=-]+\Z")


def _read_credential_file(
    path: Path,
    *,
    selected_keys: tuple[str, str],
) -> dict[str, str]:
    try:
        initial = os.lstat(path)
    except OSError:
        raise DeribitPrivateError("CREDENTIAL_FILE_UNREADABLE") from None
    if stat.S_ISLNK(initial.st_mode):
        raise DeribitPrivateError("CREDENTIAL_FILE_SYMLINK_FORBIDDEN")
    if not stat.S_ISREG(initial.st_mode):
        raise DeribitPrivateError("CREDENTIAL_FILE_NOT_REGULAR")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise DeribitPrivateError("CREDENTIAL_FILE_UNREADABLE") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DeribitPrivateError("CREDENTIAL_FILE_NOT_REGULAR")
        if (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
            raise DeribitPrivateError("CREDENTIAL_FILE_CHANGED")
        if opened.st_uid != os.geteuid():
            raise DeribitPrivateError("CREDENTIAL_FILE_OWNER_INVALID")
        if stat.S_IMODE(opened.st_mode) != 0o600:
            raise DeribitPrivateError("CREDENTIAL_FILE_MODE_INVALID")
        if opened.st_size > 65_536:
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        with os.fdopen(descriptor, encoding="utf-8", closefd=False) as handle:
            selected = _parse_credential_lines(handle, selected_keys=selected_keys)
    except UnicodeDecodeError:
        raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID") from None
    except OSError:
        raise DeribitPrivateError("CREDENTIAL_FILE_UNREADABLE") from None
    finally:
        os.close(descriptor)
    if set(selected) != set(selected_keys):
        raise DeribitPrivateError("CREDENTIAL_FILE_ENVIRONMENT_MISMATCH")
    return selected


def _parse_credential_lines(
    lines: object,
    *,
    selected_keys: tuple[str, str],
) -> dict[str, str]:
    if not hasattr(lines, "__iter__"):
        raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
    seen: set[str] = set()
    selected: dict[str, str] = {}
    for raw_line in lines:
        if not isinstance(raw_line, str):
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        line = raw_line.removesuffix("\n")
        if line.endswith("\r") or len(line) > 8_192:
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        if not line or line.startswith("#"):
            continue
        if line.strip() != line or "=" not in line:
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        key, value = line.split("=", 1)
        if _CREDENTIAL_KEY_PATTERN.fullmatch(key) is None:
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        if key not in _CREDENTIAL_FILE_KEYS:
            raise DeribitPrivateError("CREDENTIAL_FILE_UNKNOWN_KEY")
        if key in seen:
            raise DeribitPrivateError("CREDENTIAL_FILE_DUPLICATE_KEY")
        seen.add(key)
        if value and _CREDENTIAL_VALUE_PATTERN.fullmatch(value) is None:
            raise DeribitPrivateError("CREDENTIAL_FILE_FORMAT_INVALID")
        if key in selected_keys and value:
            selected[key] = value
    return selected


def _print_safe_error(code: str) -> None:
    print(json.dumps({"error": code}, ensure_ascii=False, sort_keys=True))

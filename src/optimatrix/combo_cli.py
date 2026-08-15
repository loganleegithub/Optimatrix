from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, Protocol

from optimatrix.account import DeribitAccountEnvironment
from optimatrix.deribit_combo import (
    ComboTransport,
    DeribitComboError,
    DeribitComboHttpClient,
    run_testnet_combo_lifecycle,
)
from optimatrix.deribit_private import DeribitPrivateError
from optimatrix.private_cli import CredentialFileReader, PrivateCredentials


class ComboCredentialReader(Protocol):
    def read(self, environment: DeribitAccountEnvironment) -> PrivateCredentials: ...


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise DeribitComboError("CLI_ARGUMENTS_INVALID")


def main(argv: list[str] | None = None) -> int:
    return run(argv)


def run(
    argv: list[str] | None = None,
    *,
    credential_reader: ComboCredentialReader | None = None,
    transport_factory: Callable[[], ComboTransport] | None = None,
    now_ms: Callable[[], int] | None = None,
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
            "--environment",
            "--host",
        )
    ):
        _print_safe_error("CREDENTIAL_OR_ENVIRONMENT_ARGUMENT_FORBIDDEN")
        return 2

    parser = _SafeArgumentParser(prog="optimatrix-combo")
    parser.add_argument(
        "--credentials-file",
        required=credential_reader is None,
        type=Path,
        help="explicit owner-only 0600 machine credential file",
    )
    try:
        args = parser.parse_args(raw_arguments)
    except DeribitComboError as exc:
        _print_safe_error(exc.code)
        return 2
    if credential_reader is not None and args.credentials_file is not None:
        _print_safe_error("CLI_ARGUMENTS_INVALID")
        return 2

    reader = credential_reader or CredentialFileReader(args.credentials_file)
    clock = now_ms or (lambda: time.time_ns() // 1_000_000)
    try:
        credentials = reader.read(DeribitAccountEnvironment.TESTNET)
        known_ms = clock()
        receipt = run_testnet_combo_lifecycle(
            transport=(transport_factory or DeribitComboHttpClient)(),
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            now_ms=known_ms,
            label=f"optimatrix-c2-{known_ms}",
        )
        del credentials
    except (DeribitComboError, DeribitPrivateError) as exc:
        _print_safe_error(exc.code)
        return 2
    except (OSError, TypeError, ValueError):
        _print_safe_error("TESTNET_COMBO_LIFECYCLE_FAILED")
        return 2

    print(json.dumps(receipt.as_safe_object(), ensure_ascii=False, sort_keys=True))
    return 0 if receipt.status == "COMPLETE" else 2


def _print_safe_error(code: str) -> None:
    print(json.dumps({"error": code}, ensure_ascii=True, sort_keys=True))

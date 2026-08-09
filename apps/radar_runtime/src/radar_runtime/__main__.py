from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from options_domain import OptionProductName
from short_vol_underwriting import migrate_legacy_admitted_cases

from radar_runtime.identity import clean_code_identity, git_repository_root
from radar_runtime.service import (
    PersistentServiceStartupError,
    SingleInstanceLease,
    load_persistent_product_policies,
    prepare_persistent_state_root,
    run_persistent_service,
)


def _existing_source_directory(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise PersistentServiceStartupError(f"{label} must be absolute")
    if path.is_symlink() or not path.is_dir():
        raise PersistentServiceStartupError(f"{label} must be one existing non-symlink directory")
    return path.resolve()


def _run_legacy_migration(arguments: argparse.Namespace) -> int:
    repository = git_repository_root(Path.cwd())
    clean_code_identity(repository)
    source_root = _existing_source_directory(
        arguments.source_state_root,
        label="legacy source state root",
    )
    source_cases = _existing_source_directory(
        arguments.source_cases,
        label="legacy source cases directory",
    )
    if source_root != source_cases and source_root not in source_cases.parents:
        raise PersistentServiceStartupError(
            "legacy source cases directory must belong to its state root"
        )
    destination_requested = arguments.destination_state_root
    if not destination_requested.is_absolute():
        raise PersistentServiceStartupError("persistent state root must be absolute")
    destination_candidate = destination_requested.resolve()
    if (
        destination_candidate == source_root
        or source_root in destination_candidate.parents
        or destination_candidate in source_root.parents
    ):
        raise PersistentServiceStartupError(
            "migration source and destination state roots cannot overlap"
        )
    product, policies = load_persistent_product_policies(repository, arguments.product)
    with SingleInstanceLease(source_root, preserve_existing_lock=True):
        destination_root = prepare_persistent_state_root(
            arguments.destination_state_root,
            repository,
        )
        with SingleInstanceLease(destination_root):
            recovered = migrate_legacy_admitted_cases(
                source_cases,
                destination_root / "cases",
                policies=policies,
            )
    if not recovered:
        raise PersistentServiceStartupError(
            "legacy source contains no compatible non-terminal admitted Shadow Entry"
        )
    print(
        f"product={product.name.value} "
        f"migrated_entries={len(recovered)} "
        f"source={source_cases} "
        f"destination={destination_root / 'cases'}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m radar_runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    service_parser = subparsers.add_parser("serve-shadow")
    service_parser.add_argument("--state-root", type=Path, required=True)
    service_parser.add_argument("--workbench-host", default="127.0.0.1")
    service_parser.add_argument("--workbench-port", type=int, default=8765)
    service_parser.add_argument(
        "--product",
        choices=tuple(product.value for product in OptionProductName),
        default=OptionProductName.LINEAR_BTC_USDC.value,
    )
    migration_parser = subparsers.add_parser("migrate-shadow-cases")
    migration_parser.add_argument("--source-state-root", type=Path, required=True)
    migration_parser.add_argument("--source-cases", type=Path, required=True)
    migration_parser.add_argument("--destination-state-root", type=Path, required=True)
    migration_parser.add_argument(
        "--product",
        choices=tuple(product.value for product in OptionProductName),
        required=True,
    )
    arguments = parser.parse_args()
    if arguments.command == "migrate-shadow-cases":
        return _run_legacy_migration(arguments)
    service_startup, terminal_summary = asyncio.run(
        run_persistent_service(
            state_root=arguments.state_root,
            process_cwd=Path.cwd(),
            workbench_host=arguments.workbench_host,
            workbench_port=arguments.workbench_port,
            product=arguments.product,
        )
    )
    print(
        f"product={service_startup.product.name.value} "
        f"runtime={service_startup.runtime_identity} "
        f"workbench=http://{service_startup.workbench_host}:{service_startup.workbench_port} "
        f"cases={service_startup.cases_directory} "
        f"terminal={terminal_summary.get('object_kind', 'RADAR_RUN_SUMMARY')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

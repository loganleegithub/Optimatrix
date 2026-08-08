from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from options_domain import OptionProductName

from radar_runtime.service import run_persistent_service


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
    arguments = parser.parse_args()
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

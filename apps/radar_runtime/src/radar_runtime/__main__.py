from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from radar_runtime.observation import run_bounded_radar_knownness_observation
from radar_runtime.service import run_persistent_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m radar_runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    service_parser = subparsers.add_parser("serve-shadow")
    service_parser.add_argument("--state-root", type=Path, required=True)
    service_parser.add_argument("--workbench-host", default="127.0.0.1")
    service_parser.add_argument("--workbench-port", type=int, default=8765)

    observation_parser = subparsers.add_parser("observe-radar-knownness")
    observation_parser.add_argument("--state-root", type=Path, required=True)
    observation_parser.add_argument("--duration-seconds", type=int, required=True)

    arguments = parser.parse_args()
    if arguments.command == "observe-radar-knownness":
        _startup, observation = asyncio.run(
            run_bounded_radar_knownness_observation(
                state_root=arguments.state_root,
                process_cwd=Path.cwd(),
                duration_seconds=arguments.duration_seconds,
            )
        )
        print(
            json.dumps(
                observation.as_object(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        return 0

    service_startup, terminal_summary = asyncio.run(
        run_persistent_service(
            state_root=arguments.state_root,
            process_cwd=Path.cwd(),
            workbench_host=arguments.workbench_host,
            workbench_port=arguments.workbench_port,
        )
    )
    print(
        f"runtime={service_startup.runtime_identity} "
        f"workbench=http://{service_startup.workbench_host}:{service_startup.workbench_port} "
        f"cases={service_startup.cases_directory} "
        f"terminal={terminal_summary.get('object_kind', 'RADAR_RUN_SUMMARY')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

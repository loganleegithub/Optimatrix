from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from short_vol_radar.policy import load_policy

from radar_runtime.identity import (
    clean_code_identity,
    git_repository_root,
    prepare_evidence_directory,
)
from radar_runtime.runtime import observe
from radar_runtime.service import run_persistent_service
from radar_runtime.shadow import (
    build_shadow_composition,
    observe_shadow,
    prepare_shadow_startup,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m radar_runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--policy", type=Path, required=True)
    observe_parser.add_argument("--expected-policy-digest", required=True)
    observe_parser.add_argument("--evidence-dir", type=Path, required=True)
    shadow_parser = subparsers.add_parser("observe-shadow")
    shadow_parser.add_argument("--manifest", type=Path, required=True)
    shadow_parser.add_argument("--radar-evidence-dir", type=Path, required=True)
    service_parser = subparsers.add_parser("serve-shadow")
    service_parser.add_argument("--state-root", type=Path, required=True)
    service_parser.add_argument("--workbench-host", default="127.0.0.1")
    service_parser.add_argument("--workbench-port", type=int, default=8765)
    arguments = parser.parse_args()
    if arguments.command == "observe-shadow":
        shadow_startup = prepare_shadow_startup(
            manifest_path=arguments.manifest,
            radar_evidence_directory=arguments.radar_evidence_dir,
            process_argv=tuple(sys.argv),
            process_cwd=Path.cwd(),
        )
        composition = build_shadow_composition(shadow_startup)
        summary_path = asyncio.run(observe_shadow(composition))
        print(
            json.dumps(
                {
                    "manifest_identity": shadow_startup.manifest.manifest_identity,
                    "manifest_path": str(composition.manifest_path),
                    "code_identity": shadow_startup.code_identity,
                    "runtime_identity": shadow_startup.runtime_identity,
                    "radar_summary_path": str(summary_path),
                    "downstream_evidence_directory": str(
                        shadow_startup.downstream_evidence_directory
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "serve-shadow":
        service_startup, summary_path = asyncio.run(
            run_persistent_service(
                state_root=arguments.state_root,
                process_cwd=Path.cwd(),
                workbench_host=arguments.workbench_host,
                workbench_port=arguments.workbench_port,
            )
        )
        print(
            json.dumps(
                {
                    "code_identity": service_startup.code_identity,
                    "runtime_identity": service_startup.runtime_identity,
                    "run_directory": str(service_startup.run_directory),
                    "radar_summary_path": str(summary_path),
                    "workbench_host": service_startup.workbench_host,
                    "workbench_port": service_startup.workbench_port,
                },
                sort_keys=True,
            )
        )
        return 0
    repository = git_repository_root(Path.cwd())
    policy = load_policy(arguments.policy, arguments.expected_policy_digest)
    code_identity = clean_code_identity(repository)
    evidence_directory = prepare_evidence_directory(arguments.evidence_dir, repository)
    summary_path = asyncio.run(
        observe(
            policy=policy,
            code_identity=code_identity,
            evidence_directory=evidence_directory,
        )
    )
    print(
        json.dumps(
            {
                "policy_path": str(arguments.policy.resolve()),
                "policy_identity": policy.identity,
                "code_identity": code_identity,
                "summary_path": str(summary_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

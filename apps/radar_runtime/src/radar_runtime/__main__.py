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
    arguments = parser.parse_args()
    if arguments.command == "observe-shadow":
        startup = prepare_shadow_startup(
            manifest_path=arguments.manifest,
            radar_evidence_directory=arguments.radar_evidence_dir,
            process_argv=tuple(sys.argv),
            process_cwd=Path.cwd(),
        )
        composition = build_shadow_composition(startup)
        summary_path = asyncio.run(observe_shadow(composition))
        print(
            json.dumps(
                {
                    "manifest_identity": startup.manifest.manifest_identity,
                    "manifest_path": str(composition.manifest_path),
                    "code_identity": startup.code_identity,
                    "runtime_identity": startup.runtime_identity,
                    "radar_summary_path": str(summary_path),
                    "downstream_evidence_directory": str(startup.downstream_evidence_directory),
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

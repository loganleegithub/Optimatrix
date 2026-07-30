from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from short_vol_radar.policy import load_policy

from radar_runtime.identity import (
    clean_code_identity,
    git_repository_root,
    prepare_evidence_directory,
)
from radar_runtime.runtime import observe


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m radar_runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--policy", type=Path, required=True)
    observe_parser.add_argument("--expected-policy-digest", required=True)
    observe_parser.add_argument("--evidence-dir", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command != "observe":
        parser.error("unsupported command")
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

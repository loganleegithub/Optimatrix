"""Command-line entrypoint for the bounded Outcome Truth closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from radar_runtime.outcome_bundle import (
    create_outcome_evidence_bundle,
    verify_outcome_evidence_bundle,
)
from radar_runtime.outcome_runtime import (
    replay_outcome,
    run_public_outcome_capture,
    run_synthetic_outcome,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimatrix bounded Outcome Truth runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    synthetic = commands.add_parser("synthetic")
    synthetic.add_argument("--output", type=Path, required=True)

    capture = commands.add_parser("capture")
    capture.add_argument("--duration-seconds", type=int, required=True)
    capture.add_argument("--output", type=Path, required=True)

    replay = commands.add_parser("replay")
    replay.add_argument("run_root", type=Path)
    replay.add_argument("--output", type=Path, required=True)

    bundle = commands.add_parser("bundle")
    bundle.add_argument("--synthetic-run", type=Path, required=True)
    bundle.add_argument("--synthetic-replay", type=Path, required=True)
    bundle.add_argument("--public-run", type=Path, required=True)
    bundle.add_argument("--public-replay", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify-bundle")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "synthetic":
        payload = run_synthetic_outcome(arguments.output)
    elif arguments.command == "capture":
        payload = run_public_outcome_capture(
            arguments.output,
            arguments.duration_seconds,
        )
    elif arguments.command == "replay":
        payload = replay_outcome(arguments.run_root, arguments.output)
    elif arguments.command == "bundle":
        payload = create_outcome_evidence_bundle(
            synthetic_run=arguments.synthetic_run,
            synthetic_replay=arguments.synthetic_replay,
            public_run=arguments.public_run,
            public_replay=arguments.public_replay,
            output=arguments.output,
        )
    else:
        payload = verify_outcome_evidence_bundle(
            arguments.bundle,
            archive=arguments.archive,
        )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return 0

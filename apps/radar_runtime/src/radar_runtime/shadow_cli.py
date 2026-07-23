"""CLI for one bounded Fixed-Policy public-Shadow run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from radar_runtime.shadow_bundle import (
    create_shadow_evidence_bundle,
    verify_shadow_evidence_bundle,
)
from radar_runtime.shadow_runtime import (
    replay_shadow,
    run_historical_semantic_regression,
    run_public_shadow_capture,
    run_synthetic_shadow,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimatrix Fixed-Policy public Shadow")
    commands = parser.add_subparsers(dest="command", required=True)

    synthetic = commands.add_parser("synthetic")
    synthetic.add_argument("--output", type=Path, required=True)

    capture = commands.add_parser("capture")
    capture.add_argument("--output", type=Path, required=True)

    replay = commands.add_parser("replay")
    replay.add_argument("run_root", type=Path)
    replay.add_argument("--output", type=Path, required=True)

    semantic = commands.add_parser("semantic-regression")
    semantic.add_argument("--accepted-outcome-bundle", type=Path, required=True)
    semantic.add_argument("--output", type=Path, required=True)

    bundle = commands.add_parser("bundle")
    bundle.add_argument("--synthetic-run", type=Path, required=True)
    bundle.add_argument("--synthetic-replay", type=Path, required=True)
    bundle.add_argument("--public-run", type=Path, required=True)
    bundle.add_argument("--public-replay", type=Path, required=True)
    bundle.add_argument("--semantic-regression", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)

    verify_bundle = commands.add_parser("verify-bundle")
    verify_bundle.add_argument("bundle", type=Path)
    verify_bundle.add_argument("--archive", type=Path)
    verify_bundle.add_argument("--static-only", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "synthetic":
        payload = run_synthetic_shadow(arguments.output)
    elif arguments.command == "capture":
        payload = run_public_shadow_capture(arguments.output)
    elif arguments.command == "semantic-regression":
        payload = run_historical_semantic_regression(
            arguments.accepted_outcome_bundle,
            arguments.output,
        )
    elif arguments.command == "bundle":
        payload = create_shadow_evidence_bundle(
            synthetic_run=arguments.synthetic_run,
            synthetic_replay=arguments.synthetic_replay,
            public_run=arguments.public_run,
            public_replay=arguments.public_replay,
            semantic_regression=arguments.semantic_regression,
            output=arguments.output,
        )
    elif arguments.command == "verify-bundle":
        payload = verify_shadow_evidence_bundle(
            arguments.bundle,
            archive=arguments.archive,
            authoritative_replay=not arguments.static_only,
        )
    else:
        payload = replay_shadow(arguments.run_root, arguments.output)
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return 0

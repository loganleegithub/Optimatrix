"""Small deterministic command-line runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from market_tape import read_capture

from radar_runtime.deribit_public import (
    inspect_payload,
    replay_payload,
    run_public_capture,
)
from radar_runtime.fixture import build_fixture_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimatrix public-Shadow radar runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output", type=Path, required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--duration-seconds", type=int, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("capture", type=Path)
    replay = commands.add_parser("replay")
    replay.add_argument("capture", type=Path)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--live", type=Path)
    replay.add_argument("--decision", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "demo":
        print(
            json.dumps(
                build_fixture_result(arguments.output),
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "capture":
        print(
            json.dumps(
                run_public_capture(arguments.output, arguments.duration_seconds),
                sort_keys=True,
            )
        )
        return 0
    manifest, events = read_capture(arguments.capture)
    if arguments.command == "inspect":
        print(json.dumps(inspect_payload(manifest, events), sort_keys=True))
        return 0
    live: dict[str, object] | None = None
    if arguments.live is not None:
        raw_live: object = json.loads(arguments.live.read_text(encoding="utf-8"))
        if not isinstance(raw_live, dict):
            raise ValueError("live result must be an object")
        live = cast(dict[str, object], raw_live)
    decision: dict[str, object] | None = None
    if arguments.decision is not None:
        raw_decision: object = json.loads(arguments.decision.read_text(encoding="utf-8"))
        if not isinstance(raw_decision, dict):
            raise ValueError("Decision receipt must be an object")
        decision = cast(dict[str, object], raw_decision)
    payload = replay_payload(manifest, events, live=live, decision_receipt=decision)
    arguments.output.mkdir(parents=True, exist_ok=False)
    (arguments.output / "replay.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 0

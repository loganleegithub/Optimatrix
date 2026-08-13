from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from optimatrix.channels import CHANNELS
from optimatrix.deribit_snapshot import (
    DEFAULT_DERIBIT_API,
    DeribitHttpClient,
    DeribitSourceError,
    evaluate_live_btc_snapshot,
)
from optimatrix.market import EventState
from optimatrix.policy import (
    DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    load_btc_short_vol_policy,
)
from optimatrix.runtime import (
    AUTHORIZED_RUNTIME_POLICY_IDENTITY,
    AUTHORIZED_RUNTIME_ROOT,
    BtcPublicShadowRuntime,
    DeribitPublicRuntimeSource,
)
from optimatrix.scenarios import run_all_scenarios
from optimatrix.workbench import write_workbench

_AUTHORIZED_WORKBENCH_PORT = 8765


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optimatrix-shadow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate", help="run deterministic business scenarios")
    simulate.add_argument("--scenario", default="all", choices=("all",))
    simulate.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    )
    simulate.add_argument("--output", type=Path)
    simulate.add_argument("--ledger-root", type=Path, default=Path("build/simulation-ledger"))

    channels = subparsers.add_parser("channels", help="show the fixed 2x2 channel matrix")
    channels.add_argument("--json", action="store_true")

    snapshot = subparsers.add_parser(
        "snapshot",
        help="evaluate one bounded read-only Deribit current-session snapshot",
    )
    snapshot.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    )
    snapshot.add_argument(
        "--event-state",
        required=True,
        choices=tuple(value.value for value in EventState),
    )
    snapshot.add_argument("--base-url", default=DEFAULT_DERIBIT_API)
    snapshot.add_argument("--timeout-seconds", type=float, default=10.0)
    snapshot.add_argument("--maximum-books", type=int, default=32)
    snapshot.add_argument(
        "--depth",
        type=int,
        default=20,
        choices=(1, 5, 10, 20, 50, 100, 1000, 10000),
    )
    snapshot.add_argument("--output", type=Path)

    workbench = subparsers.add_parser(
        "workbench",
        help="render one snapshot JSON as a static read-only four-leg Workbench",
    )
    workbench.add_argument("--snapshot", type=Path, required=True)
    workbench.add_argument("--output-dir", type=Path, default=Path("build/workbench"))

    runtime = subparsers.add_parser(
        "runtime",
        help="run the current production Deribit Public Shadow Session",
    )
    runtime.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    )
    runtime.add_argument(
        "--event-state",
        required=True,
        choices=tuple(value.value for value in EventState),
    )
    runtime.add_argument("--root", type=Path, default=AUTHORIZED_RUNTIME_ROOT)
    runtime.add_argument("--workbench-port", type=int, default=_AUTHORIZED_WORKBENCH_PORT)

    args = parser.parse_args(argv)
    if args.command == "simulate":
        return _simulate(args.policy, args.output, args.ledger_root)
    if args.command == "channels":
        return _channels(args.json)
    if args.command == "snapshot":
        return _snapshot(
            policy_path=args.policy,
            event_state=EventState(args.event_state),
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            maximum_books=args.maximum_books,
            depth=args.depth,
            output=args.output,
        )
    if args.command == "workbench":
        return _workbench(args.snapshot, args.output_dir)
    if args.command == "runtime":
        return _runtime(
            policy_path=args.policy,
            event_state=EventState(args.event_state),
            root=args.root,
            workbench_port=args.workbench_port,
        )
    raise AssertionError("unreachable command")


def _simulate(policy_path: Path, output: Path | None, ledger_root: Path) -> int:
    policy = load_btc_short_vol_policy(policy_path)
    results = run_all_scenarios(policy, root=ledger_root)
    document = {
        "policy_identity": policy.identity,
        "scenario_count": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "scenarios": [
            {"name": result.name, "passed": result.passed, "facts": result.facts}
            for result in results
        ],
    }
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if document["failed"] == 0 else 1


def _channels(as_json: bool) -> int:
    document = [
        {
            "channel_id": descriptor.channel_id.value,
            "product_id": descriptor.product.product_id.value,
            "strategy_id": descriptor.strategy_id.value,
            "implemented": descriptor.implemented,
            "implementation_name": descriptor.implementation_name,
        }
        for descriptor in CHANNELS.values()
    ]
    if as_json:
        print(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for item in document:
            state = "IMPLEMENTED" if item["implemented"] else "RESERVED"
            print(f"{item['channel_id']}: {state}")
    return 0


def _snapshot(
    *,
    policy_path: Path,
    event_state: EventState,
    base_url: str,
    timeout_seconds: float,
    maximum_books: int,
    depth: int,
    output: Path | None,
) -> int:
    policy = load_btc_short_vol_policy(policy_path)
    client = DeribitHttpClient(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    try:
        evaluation = evaluate_live_btc_snapshot(
            client=client,
            policy=policy,
            now=datetime.now(UTC),
            event_state=event_state,
            maximum_books=maximum_books,
            depth=depth,
        )
    except DeribitSourceError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    text = (
        json.dumps(
            evaluation.as_object(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def _workbench(snapshot_path: Path, output_dir: Path) -> int:
    try:
        value = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"snapshot input is unreadable: {exc}"}, ensure_ascii=False))
        return 2
    if not isinstance(value, dict):
        print(json.dumps({"error": "snapshot input must be a JSON object"}, ensure_ascii=False))
        return 2
    try:
        exported = write_workbench(value, output_dir)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"error": f"snapshot input is invalid: {exc}"}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "mode": "PUBLIC SHADOW - READ ONLY",
                "index": str(exported.index_path),
                "data": str(exported.data_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _runtime(
    *,
    policy_path: Path,
    event_state: EventState,
    root: Path,
    workbench_port: int,
) -> int:
    permission_error = _runtime_permission_error(
        event_state=event_state,
        root=root,
        workbench_port=workbench_port,
    )
    if permission_error is not None:
        print(
            json.dumps(
                {"error": permission_error},
                ensure_ascii=False,
            )
        )
        return 2
    try:
        policy = load_btc_short_vol_policy(policy_path)
        if policy.identity != AUTHORIZED_RUNTIME_POLICY_IDENTITY:
            print(
                json.dumps(
                    {"error": "runtime policy identity is outside the active task authorization"},
                    ensure_ascii=False,
                )
            )
            return 2
        source = DeribitPublicRuntimeSource(policy=policy, event_state=event_state)
        runtime = BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=event_state,
            now=datetime.now(UTC),
        )
        print(
            json.dumps(
                {
                    "mode": "PUBLIC SHADOW - READ ONLY",
                    "root": str(root),
                    "session_id": runtime.session.session_id,
                    "workbench": f"http://127.0.0.1:{workbench_port}/",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return runtime.run_forever(port=workbench_port)
    except (DeribitSourceError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"error": f"runtime failed: {exc}"}, ensure_ascii=False))
        return 2


def _runtime_permission_error(
    *,
    event_state: EventState,
    root: Path,
    workbench_port: int,
) -> str | None:
    if event_state is not EventState.NONE:
        return "runtime event state is outside the active task authorization"
    if workbench_port != _AUTHORIZED_WORKBENCH_PORT:
        return "runtime Workbench port is outside the active task authorization"
    if not root.is_absolute() or root != AUTHORIZED_RUNTIME_ROOT:
        return "runtime root is outside the active task authorization"
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.is_symlink():
            return "runtime root and its parents must not be symbolic links"
    return None


if __name__ == "__main__":
    raise SystemExit(main())

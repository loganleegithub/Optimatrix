from __future__ import annotations

import plistlib
import re
from pathlib import Path

from optimatrix.policy import DEFAULT_BTC_SHORT_VOL_POLICY_PATH, load_btc_short_vol_policy
from optimatrix.runtime import AUTHORIZED_RUNTIME_POLICY_IDENTITY, AUTHORIZED_RUNTIME_ROOT

ROOT = Path(__file__).parents[1]
AUTHORITY = ROOT / "docs" / "authority"
TASK_KINDS = {"NONE", "AUTHORITY_ONLY", "IMPLEMENTATION", "VALIDATION_ONLY"}


def _current_task_kind(stage: str) -> str:
    match = re.search(r"\*\*Current task kind:\*\* `([^`]+)`", stage)
    assert match is not None
    return match.group(1)


def test_current_stage_and_task_are_one_exact_closure() -> None:
    stage = (AUTHORITY / "CURRENT_STAGE.md").read_text(encoding="utf-8")
    task_kind = _current_task_kind(stage)
    tasks = sorted(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md")
    assert task_kind in TASK_KINDS

    for field in (
        "Offline checks and simulation",
        "Public market calls",
        "Stable ObservationLedger root",
        "Stable CaseJournal root",
        "Continuous runtime",
        "Private read-only account permission",
        "Orders, capital, and deployment",
        "Policy qualification / Edge claim",
    ):
        assert f"**{field}:**" in stage

    if task_kind == "NONE":
        assert tasks == []
        assert "**Sole authorized closure:** `NONE`" in stage
        assert "**Public market calls:** `NONE_AUTHORIZED`" in stage
        return

    assert len(tasks) == 1
    task = tasks[0]
    task_text = task.read_text(encoding="utf-8")
    assert "**Status:** ACTIVE" in task_text
    assert f"**Task kind:** {task_kind}" in task_text

    closure = re.search(r"\*\*Sole authorized closure:\*\* \[[^]]+\]\(([^)]+)\)", stage)
    assert closure is not None
    assert (AUTHORITY / closure.group(1)).resolve() == task.resolve()

    if task_kind == "AUTHORITY_ONLY":
        assert "**Runtime implementation:** FORBIDDEN" in task_text
        assert "**Live commands:** FORBIDDEN" in task_text
    elif task_kind == "VALIDATION_ONLY":
        assert "**Runtime implementation:** FORBIDDEN" in task_text


def test_authorized_runtime_matches_active_b3_deployment() -> None:
    expected_root = Path(
        "/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2"
    )
    policy = load_btc_short_vol_policy(DEFAULT_BTC_SHORT_VOL_POLICY_PATH)
    tasks = sorted(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md")

    assert AUTHORIZED_RUNTIME_ROOT == expected_root
    assert AUTHORIZED_RUNTIME_POLICY_IDENTITY == policy.identity

    stage = (AUTHORITY / "CURRENT_STAGE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert str(expected_root) in stage
    assert str(expected_root) in readme
    assert policy.identity in stage
    if tasks:
        assert len(tasks) == 1
        task_text = tasks[0].read_text(encoding="utf-8")
        assert policy.identity in task_text
    else:
        task_text = ""
        assert "**Current task kind:** `NONE`" in stage
    if "**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`" in task_text:
        assert str(expected_root) in task_text
    elif task_text:
        assert "retains its exact" in stage
        assert "replaced exactly once" in stage
        assert "deployment" in task_text
        assert "No other process control" in task_text
    else:
        assert "existing B3 launchd job remains unchanged" in stage


def test_daily_review_launchagent_is_bounded_and_has_no_keepalive_loop() -> None:
    path = ROOT / "deploy" / "com.optimatrix.d1-session-review.plist"
    with path.open("rb") as handle:
        manifest = plistlib.load(handle)

    assert manifest["Label"] == "com.optimatrix.d1-session-review"
    assert manifest["RunAtLoad"] is True
    assert manifest["StartInterval"] == 900
    assert "KeepAlive" not in manifest
    assert manifest["ProgramArguments"] == [
        "/Users/logan/Optimatrix/.venv/bin/optimatrix-ai-lab",
        "daily-review",
        "--ledger-root",
        "/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2",
        "--lab-root",
        "/Users/logan/Library/Application Support/Optimatrix/ai-lab",
        "--first-session-id",
        "2026-08-17T08:00:00Z",
    ]


def test_capability_acceptance_does_not_manufacture_market_evidence() -> None:
    constitution = (AUTHORITY / "PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    stage = (AUTHORITY / "CURRENT_STAGE.md").read_text(encoding="utf-8")

    for fact in (
        "PIPELINE_CAPABILITY_ACCEPTED",
        "NATURAL_CHAIN_OBSERVED",
        "NOT_YET_OBSERVED",
        "Policy reachability",
        "Policy qualification",
        "Edge",
    ):
        assert fact in constitution

    assert "B3_PIPELINE_CAPABILITY_ACCEPTED" in stage
    assert "natural_chain=NOT_YET_OBSERVED" in stage
    assert "policy_reachability=" in stage
    assert "policy_qualification=NONE" in stage
    assert "edge_claim=NONE" in stage


def test_agent_route_resolves_to_current_owners() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    routed_paths = set(re.findall(r"`((?:docs|tasks)/[^`]+\.md)`", agents))
    assert routed_paths
    for routed_path in routed_paths:
        assert (ROOT / routed_path).is_file(), routed_path

    assert "docs/contracts/CASE_POSITION_OUTCOME.md" in routed_paths
    assert not (ROOT / "docs" / "contracts" / "SHADOW_LIFECYCLE.md").exists()
    assert agents.index("docs/authority/CURRENT_STAGE.md") < agents.index(
        "docs/authority/PRODUCT_CONSTITUTION.md"
    )


def test_markdown_links_resolve() -> None:
    markdown_files = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "tasks").glob("*.md")),
    ]
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            assert (path.parent / target.split("#", 1)[0]).resolve().exists(), (path, target)


def test_legacy_strategy_runtime_is_physically_absent() -> None:
    for path in (ROOT / "apps", ROOT / "packages", ROOT / "policies"):
        assert not path.exists()

    manifest = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "src").rglob("*.py"))
    )
    for legacy_name in (
        "market_monitor",
        "options_domain",
        "short_vol_radar",
        "short_vol_underwriting",
        "radar_runtime",
        "optimatrix-shadow-v2-v9",
        "INVERSE_BTC_SHORT_VOL_V2",
    ):
        assert legacy_name not in manifest
        assert legacy_name not in source

from __future__ import annotations

import re
from pathlib import Path

from optimatrix.product_funnel import FunnelStageName

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
        "Offline simulation",
        "Public snapshot",
        "Continuous runtime",
        "Stable Decision Case root",
        "Private/account/order permission",
        "Policy qualification / Edge claim",
    ):
        assert f"**{field}:**" in stage

    if task_kind == "NONE":
        assert tasks == []
        assert "**Sole authorized closure:** `NONE`" in stage
        assert "**Public snapshot:** `NONE_AUTHORIZED`" in stage
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


def test_agent_route_resolves_to_current_owners() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    routed_paths = set(re.findall(r"`((?:docs|tasks)/[^`]+\.md)`", agents))
    assert routed_paths
    for routed_path in routed_paths:
        assert (ROOT / routed_path).is_file(), routed_path

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


def test_contract_funnel_matches_the_product_projection() -> None:
    contract = (ROOT / "docs" / "contracts" / "BTC_0DTE_TWO_SIDED_SHORT_VOL.md").read_text(
        encoding="utf-8"
    )
    funnel = contract.partition("## Canonical funnel")[2]
    prior = -1
    for stage in FunnelStageName:
        offset = funnel.index(stage.value)
        assert offset > prior
        prior = offset


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

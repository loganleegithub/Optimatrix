from __future__ import annotations

import json
from pathlib import Path

from optimatrix.product_funnel import FunnelStageName

ROOT = Path(__file__).parents[1]
AUTHORITY = ROOT / "docs" / "authority"


def test_current_stage_and_active_task_are_one_exact_closure() -> None:
    stage = (AUTHORITY / "CURRENT_STAGE.md").read_text(encoding="utf-8")
    task_files = sorted(
        path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md"
    )
    if "**Current task kind:** `NONE`" in stage:
        assert task_files == []
        assert "**Sole authorized closure:** `NONE`" in stage
    else:
        assert len(task_files) == 1
        assert "**Status:** ACTIVE" in task_files[0].read_text(encoding="utf-8")
        assert task_files[0].stem in stage
        assert "**Current task kind:** `IMPLEMENTATION`" in stage


def test_authority_canonical_funnel_matches_the_product_projection() -> None:
    constitution = (AUTHORITY / "PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    prior = -1
    for stage in FunnelStageName:
        offset = constitution.index(stage.value)
        assert offset > prior
        prior = offset
    assert "Green tests alone never satisfy" in (AUTHORITY / "DELIVERY_CONTRACT.md").read_text(
        encoding="utf-8"
    )


def test_legacy_strategy_runtime_is_physically_absent_and_not_a_dependency() -> None:
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


def test_provenance_and_legacy_isolation_are_machine_readable() -> None:
    baseline = json.loads((ROOT / "docs" / "UPSTREAM_BASELINE.json").read_text(encoding="utf-8"))
    assert baseline["source_main_commit_inspected"] == "13902c53e972f12721d2ef9d17de866fbda288a7"
    assert (
        baseline["rebuild_source_sha256"]
        == "49bb944d2f873e27d175b6ef39d59ce5096ed42d300990eedff8519b8155e380"
    )
    assert baseline["legacy_repository_runtime_import_allowed"] is False
    assert baseline["legacy_case_root_access_allowed"] is False
    assert baseline["legacy_case_migration_implemented"] is False

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_FILES = (
    ROOT / "docs/authority/PRODUCT_CONSTITUTION.md",
    ROOT / "docs/authority/CURRENT_STAGE.md",
    ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md",
    ROOT / "docs/authority/DELIVERY_CONTRACT.md",
)
IMPLEMENTATION_CONTRACTS = (
    ROOT / "docs/contracts/SHORT_VOL_RADAR.md",
    ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md",
    ROOT / "docs/contracts/SHORT_VOL_SHADOW_CASE.md",
    ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md",
)
INTERNAL_PACKAGES = {
    "market_monitor",
    "options_domain",
    "short_vol_radar",
    "short_vol_underwriting",
    "radar_runtime",
}
PACKAGE_ROOTS = {
    "market_monitor": ROOT / "packages/market_monitor/src/market_monitor",
    "options_domain": ROOT / "packages/options_domain/src/options_domain",
    "short_vol_radar": ROOT / "packages/short_vol_radar/src/short_vol_radar",
    "short_vol_underwriting": ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting",
    "radar_runtime": ROOT / "apps/radar_runtime/src/radar_runtime",
}
ALLOWED_IMPORTS = {
    "market_monitor": {"market_monitor"},
    "options_domain": {"market_monitor", "options_domain"},
    "short_vol_radar": {"market_monitor", "options_domain", "short_vol_radar"},
    "short_vol_underwriting": {
        "market_monitor",
        "options_domain",
        "short_vol_radar",
        "short_vol_underwriting",
    },
    "radar_runtime": INTERNAL_PACKAGES,
}


def _internal_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules = (node.module,)
        else:
            continue
        values.update(
            module.split(".", 1)[0]
            for module in modules
            if module.split(".", 1)[0] in INTERNAL_PACKAGES
        )
    return values


def test_active_authority_is_one_small_consistent_map() -> None:
    assert {path.name for path in (ROOT / "docs/authority").glob("*.md")} == {
        "CURRENT_STAGE.md",
        "DELIVERY_CONTRACT.md",
        "PRODUCT_CONSTITUTION.md",
        "SYSTEM_ARCHITECTURE.md",
    }
    assert {path.name for path in (ROOT / "docs/contracts").glob("*.md")} == {
        "SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md",
        "SHORT_VOL_RADAR.md",
        "SHORT_VOL_SHADOW_CASE.md",
        "SHORT_VOL_UNDERWRITING_POSITION.md",
    }
    for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS):
        opening = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        assert "**Status:** ACTIVE" in opening
    normative_line_count = sum(
        len(path.read_text(encoding="utf-8").splitlines())
        for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS)
    )
    assert normative_line_count < 1_600


def test_agents_routes_work_and_enforces_anti_defensive_stops() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    agents_flat = " ".join(agents.split())
    assert len(agents.splitlines()) <= 100
    for path in AUTHORITY_FILES:
        assert path.relative_to(ROOT).as_posix() in agents
    for phrase in (
        "Before `SHADOW_CASE_OPENED`, durable business record count is zero",
        "fix the largest funnel loss",
        "validator-of-validator",
        "second real run failure",
        "Green tests alone are insufficient",
    ):
        assert phrase.lower() in agents_flat.lower()


def test_repository_relative_markdown_links_resolve() -> None:
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    checked = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        *AUTHORITY_FILES,
        *IMPLEMENTATION_CONTRACTS,
        ROOT / "docs/architecture/PERSISTENT_RUNTIME_TRADER_WORKBENCH.md",
        *(ROOT / "tasks").glob("*.md"),
    )
    for path in checked:
        for raw_target in pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            assert (path.parent / target).resolve().exists(), (
                f"broken link from {path}: {raw_target}"
            )


def test_product_data_boundary_is_unambiguous() -> None:
    product = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    shadow_case = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_CASE.md").read_text(encoding="utf-8")

    assert "The first durable business object is `SHADOW_CASE_OPENED`" in product
    assert "Pre-Shadow durable business record count is exactly zero" in product
    assert "The Online Runtime does not own Cohort" in " ".join(product.split())
    assert "No pre-Shadow component may open a file" in architecture
    assert "Pre-Shadow persistence is forbidden by default" in " ".join(delivery.split())
    assert "does not persist anomaly" in radar
    assert "Exactly three record kinds are authorized" in shadow_case
    assert "SHADOW_CASE_OPENED" in shadow_case
    assert "SHADOW_CASE_FIRST_CLOSE" in shadow_case
    assert "SHADOW_CASE_OUTCOME" in shadow_case


def test_public_only_validation_does_not_recreate_commissioning() -> None:
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    assert "at most one explicitly authorized bounded read-only smoke" in " ".join(delivery.split())
    assert "does not require a manifest, receipt chain" in delivery
    assert "Two-strike deletion rule" in delivery
    persistent = (
        ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md"
    ).read_text(encoding="utf-8")
    assert "Process supervision, restart policy, CPU, memory, host logs" in persistent
    assert "No terminal manifest" in persistent


def test_current_stage_disables_legacy_persistence_and_live_commands() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert (
        "`LEGACY_IMPLEMENTATION_DISABLED_PENDING_SHADOW_CASE_DATA_BOUNDARY`" in current
    )
    assert "**Live commands:** `FORBIDDEN`" in current
    assert "**Sole authorized closure:** `SHORT_VOL_SHADOW_CASE_DATA_BOUNDARY`" in current


def test_task_template_measures_product_progress_not_proof_volume() -> None:
    template = (ROOT / "tasks/TEMPLATE.md").read_text(encoding="utf-8")
    for field in (
        "**Current funnel node:**",
        "**Baseline:**",
        "**Primary blocker:**",
        "**Expected user-visible delta:**",
        "**Durable-data effect:**",
        "**Complexity added:**",
        "**Complexity deleted:**",
    ):
        assert field in template
    assert "Tests alone do not satisfy the task" in template


def test_tasks_hold_only_template_and_at_most_one_active_closure() -> None:
    task_paths = sorted((ROOT / "tasks").glob("*.md"))
    assert any(path.name == "TEMPLATE.md" for path in task_paths)
    active = [
        path
        for path in task_paths
        if path.name != "TEMPLATE.md"
        and "**Status:** ACTIVE" in "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
    ]
    assert len(active) <= 1
    assert all(
        path.name == "TEMPLATE.md" or path in active
        for path in task_paths
    ), "completed or inactive task files must not accumulate"


def test_internal_package_dependency_direction() -> None:
    for owner, root in PACKAGE_ROOTS.items():
        for path in root.rglob("*.py"):
            forbidden = _internal_imports(path) - ALLOWED_IMPORTS[owner]
            assert not forbidden, f"{path} imports higher layers: {sorted(forbidden)}"


def test_fixed_policy_files_remain_content_identified_and_unchanged() -> None:
    expected = {
        "policies/short-vol-fixed-public-shadow-radar.json": (
            "2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
        ),
        "policies/short-vol-fixed-public-shadow-underwriting.json": (
            "be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af"
        ),
        "policies/short-vol-fixed-public-shadow-position.json": (
            "498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439"
        ),
    }
    for relative, digest in expected.items():
        path = ROOT / relative
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        parsed = json.loads(raw)
        assert raw == json.dumps(parsed, ensure_ascii=False, indent=2).encode() + b"\n"


def test_markdown_contract_bytes_are_not_runtime_identity_authority() -> None:
    all_authority = "\n".join(
        path.read_text(encoding="utf-8") for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS)
    )
    assert "Markdown contract bytes are not runtime business identities" in all_authority
    assert "ContractContentDigest" not in all_authority
    assert "OutcomeContractContentDigest" not in all_authority

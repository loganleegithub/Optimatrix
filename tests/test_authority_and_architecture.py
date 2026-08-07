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
    assert "No market fact, clue, diagnostic, rank, atomic quote" in radar
    assert "Exactly three record kinds are authorized" in shadow_case
    assert "SHADOW_CASE_OPENED" in shadow_case
    assert "SHADOW_CASE_FIRST_CLOSE" in shadow_case
    assert "SHADOW_CASE_OUTCOME" in shadow_case


def test_online_runtime_has_no_rejected_counterfactual_or_cohort_surface() -> None:
    package = ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting"
    assert not (package / "cohort.py").exists()
    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "apps", ROOT / "packages")
        for path in root.rglob("*.py")
    )
    for forbidden in (
        "REJECTED_COUNTERFACTUAL",
        "RejectedAnchor",
        "AlignedPair",
        "cohort_enrolled",
        "_create_rejected_trade",
    ):
        assert forbidden not in production_source


def test_public_only_validation_does_not_recreate_commissioning() -> None:
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    assert "at most one explicitly authorized bounded read-only integration smoke" in (
        " ".join(delivery.split())
    )
    assert "source-contract probe" in delivery
    assert "does not require a manifest, receipt chain" in delivery
    assert "Two-strike deletion rule" in delivery
    persistent = (ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md").read_text(
        encoding="utf-8"
    )
    assert "Process supervision, restart policy, CPU, memory, host logs" in persistent
    assert "No terminal manifest" in persistent


def test_current_stage_selects_underwriting_margin_truth_after_natural_stop() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    normalized = " ".join(current.split())
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert "`COMPONENT_BOOK_SHADOW_LIFECYCLE_ACCEPTED`" in current
    assert "`UNDERWRITING_SELECTION_AND_MARGIN_TRUTH_ACTIVE`" in current
    assert "**Production Short Vol Radar:** `CREDIBLE_CLUE_GENERATOR_FROZEN`" in current
    assert "**Persistent service:** `NATURAL_PUBLIC_SHADOW_STOPPED_NO_DEPLOYMENT`" in current
    assert "**Live commands:** `NONE_AUTHORIZED_PAIR_TIMING_PROBE_EXHAUSTED`" in current
    assert (
        "**Sole authorized closure:** `SHORT_VOL_UNDERWRITING_SELECTION_AND_MARGIN_TRUTH`"
        in current
    )
    assert "1,812,600 contract evaluations" in current
    assert "1,811,662 contract evaluations" in current
    assert "10 distinct Episodes" in current
    assert "7 distinct Episodes" in current
    assert "`NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE 3`" in current
    assert "`CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE 7`" in current
    assert "`NO_ACTIVE_COMBO 10`" in current
    assert "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE" in current
    assert "exactly two strictly later `public/get_order_book` responses" in normalized
    assert "no live command or Shadow runtime is authorized" in normalized
    assert "maximum pair source-timestamp skew at `6000 ms`" in normalized
    assert "receive skew at `4000 ms`" in normalized
    assert "automatic restart" in current
    assert not (ROOT / "tasks/SHORT_VOL_RADAR_CANDIDATE_VALIDITY.md").exists()
    assert not (ROOT / "tasks/SHORT_VOL_RADAR_CREDIBLE_CLUE_FREEZE.md").exists()
    assert not (ROOT / "tasks/SHORT_VOL_COMPONENT_BOOK_SHADOW_LIFECYCLE.md").exists()
    assert not (ROOT / "tasks/SHORT_VOL_NATURAL_SHADOW_OPERATION.md").exists()
    assert (ROOT / "tasks/SHORT_VOL_UNDERWRITING_SELECTION_AND_MARGIN_TRUTH.md").exists()
    entrypoint = (ROOT / "apps/radar_runtime/src/radar_runtime/__main__.py").read_text(
        encoding="utf-8"
    )
    assert "observe-radar-knownness" not in entrypoint
    assert "observe-radar-candidate-validity" not in entrypoint


def test_architecture_restores_applicable_scope_and_freezes_warmup_partition() -> None:
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    stage_block = architecture.split("The canonical stages are:", 1)[1].split("```", 2)[1]

    assert "APPLICABLE_MARKET_SCOPE\nRADAR_KNOWN" in stage_block
    assert "the boundary at which that band first has an `AVAILABLE` tail is post-warmup" in (
        " ".join(architecture.split())
    )
    assert "`INDEX_WARMUP` remains visible" in " ".join(contract.split())
    assert "Every Radar UNKNOWN contributes exactly one bounded aggregate reason" in contract
    assert "configured completed-interval cutoff" in architecture
    assert "one-tick-stressed executable bid IV" in contract
    assert "LEGGED_REFERENCE_NOT_ATOMIC" in contract
    assert "deterministic lexicographic rank" in contract


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
    assert "VALIDATION_ONLY" in template
    assert "EVIDENCE_ONLY" not in template
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
    assert all(path.name == "TEMPLATE.md" or path in active for path in task_paths), (
        "completed or inactive task files must not accumulate"
    )


def test_internal_package_dependency_direction() -> None:
    for owner, root in PACKAGE_ROOTS.items():
        for path in root.rglob("*.py"):
            forbidden = _internal_imports(path) - ALLOWED_IMPORTS[owner]
            assert not forbidden, f"{path} imports higher layers: {sorted(forbidden)}"


def test_fixed_policy_files_remain_content_identified_after_pair_timing_rebind() -> None:
    expected = {
        "policies/short-vol-fixed-public-shadow-radar.json": (
            "74f286e07f8013e6178b44421db1d4d04808e5e0b0c604a80a0fdbc50f276c21"
        ),
        "policies/short-vol-fixed-public-shadow-underwriting.json": (
            "5cbff45fc342489a0c34b476d1947a54e490e04610dadd7f54a1e18f4681d79a"
        ),
        "policies/short-vol-fixed-public-shadow-position.json": (
            "e7c38b12cb8c8d79c0f6409ee31289386f7f313a60ef593771648c0504016ef3"
        ),
    }
    for relative, digest in expected.items():
        path = ROOT / relative
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        parsed = json.loads(raw)
        assert raw == json.dumps(parsed, ensure_ascii=False, indent=2).encode() + b"\n"

    radar = json.loads((ROOT / "policies/short-vol-fixed-public-shadow-radar.json").read_bytes())
    limits = radar["runtime_limits"]
    assert (
        limits["clock_refresh_interval_ms"]
        + 4 * limits["rpc_deadline_ms"]
        + limits["time_boundary_poll_interval_ms"]
        < limits["clock_stale_deadline_ms"]
    )


def test_markdown_contract_bytes_are_not_runtime_identity_authority() -> None:
    all_authority = "\n".join(
        path.read_text(encoding="utf-8") for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS)
    )
    assert "Markdown contract bytes are not runtime business identities" in all_authority
    assert "ContractContentDigest" not in all_authority
    assert "OutcomeContractContentDigest" not in all_authority

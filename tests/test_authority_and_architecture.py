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
    assert "No market fact, score, clue, diagnostic, rank, atomic quote" in radar
    assert "Exactly five record kinds are authorized" in shadow_case
    for kind in (
        "SHADOW_CASE_OPENED",
        "SHADOW_CASE_SEGMENT_OPENED",
        "SHADOW_CASE_SEGMENT_CLOSED",
        "SHADOW_CASE_FIRST_CLOSE",
        "SHADOW_CASE_OUTCOME",
    ):
        assert kind in delivery
        assert kind in shadow_case
    assert "SHADOW_CASE_LEGACY_MIGRATION" not in delivery
    assert "SHADOW_CASE_LEGACY_MIGRATION" not in shadow_case
    assert "SHADOW_CASE_OBSERVATION_SEGMENT" not in delivery
    assert "SHADOW_CASE_TRANSITION" not in delivery


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


def test_current_stage_records_40_entry_recovery_running_truth() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    normalized = " ".join(current.split())
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert "**Current task kind:** `NONE`" in current
    assert "`INVERSE_BTC_SHORT_VOL_V2_40_ENTRY_RECOVERY_RUNNING_8765`" in current
    assert "**Accepted online product:** `INVERSE_BTC_V1_ONLY`" in current
    assert "`RUNNING_8765_USER_TERMINAL_9002B6E_WITH_40_RECOVERED_ADMITTED_ENTRIES`" in current
    assert "**Live commands:** `NONE_CONSUMED`" in current
    assert "**Sole authorized closure:** `NONE`" in current
    for phrase in (
        "The sole Online Runtime product is `INVERSE_BTC_V1`",
        "There is no product selector, fallback product, compatibility profile",
        "The repository contains only the three fixed V2 Inverse Policy artifacts",
        "/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9",
        "9002b6ef7b0ec183cd1448fc975a4b7ebea19084",
        "sha256:a3ba1393dbbd5406463d63b251927b8e44fbd0da42d0e5e4babc080178c354b0",
        "sha256:b364a34267e62e7115a2b49c9f3ddf9afe342f5776682e742220ced6b8ed2a59",
        "127.0.0.1:8675",
        "127.0.0.1:8765",
        "/Users/logan/Optimatrix-runtime",
        "All six declared GET and HEAD routes return HTTP 200",
        "`RUNNING`, `CURRENT`, `health=true`, and `ready=true`",
        "`128/128` Radar rows",
        "b32e3629332e89cbcfdf0cf46f126ad49d230044b836e7a59458d2704bb9891a",
        "validated 62 schema-v5 Cases and 40 compatible non-terminal admitted Entries",
        "read `INCOMPLETE_UNCLEAN_EXIT`",
        "restored all 40 Entries",
        "preserved every incomplete predecessor Segment",
        "40 Shadow Entry rows, 40 Position rows, and 40 `PENDING` Outcome projections",
        "all 40 predecessor Entry identities exactly once",
        "latest Segment is `OPEN`, `GAPPED`, and bound to the current runtime",
        "four at one, two at two, two at three, 28 at four, two at five, and two at six",
        "zero admitted Outcome files",
        "12 Radar-score Controls and 10 selected Underwriting Controls",
        "user-owned foreground Terminal rather than a temporary execution session",
        "manual external-operator launch, not automatic process persistence",
        "Persistence ownership remains the next discussion",
        "all 751 tests",
        "style-src 'self'",
        "CSP-safe SVG coordinate plane",
        "native progress elements",
        "one authorized external-operator start was consumed",
        "Runtime persistence design remains explicitly deferred to a later task",
    ):
        assert phrase in normalized
    for identity in (
        "sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131",
        "sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d",
        "sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d",
        "sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe",
    ):
        assert identity in current
    assert {path.name for path in (ROOT / "tasks").glob("*.md")} == {"TEMPLATE.md"}
    assert not (ROOT / "tasks/INVERSE_BTC_SHORT_VOL_V2_40_ENTRY_RECOVERY_START.md").exists()
    assert not (ROOT / "tasks/INVERSE_BTC_SHORT_VOL_V2_RADAR_MAP_CSP_LAYOUT_REPAIR.md").exists()
    assert not (ROOT / "tasks/INVERSE_BTC_SHORT_VOL_V2_STRONG_SIGNAL_MAP.md").exists()
    assert not (ROOT / "tasks/INVERSE_BTC_SHORT_VOL_V2_INDEX_GRID_PHASE_REPAIR.md").exists()
    assert not (ROOT / "tasks/SHORT_VOL_INVERSE_ONLY_REPOSITORY_CLEANUP.md").exists()
    assert not (ROOT / "tasks/SHORT_VOL_PROCESS_INDEPENDENT_SHADOW_ENTRY_RECOVERY.md").exists()


def test_online_product_surface_is_inverse_only() -> None:
    active_product_docs = (
        ROOT / "README.md",
        *AUTHORITY_FILES,
        *IMPLEMENTATION_CONTRACTS,
        ROOT / "docs/architecture/PERSISTENT_RUNTIME_TRADER_WORKBENCH.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_product_docs)
    assert "INVERSE_BTC_V1" in combined
    for forbidden in (
        "LINEAR_BTC_USDC_V1",
        "Linear BTC-USDC",
        "schema v3",
        "schema-v3",
        "v3/v4",
        "`btc_usdc`",
        "both products",
    ):
        assert forbidden not in combined

    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "apps", ROOT / "packages")
        for path in root.rglob("*.py")
    )
    for forbidden in (
        "LINEAR_BTC_USDC",
        "OptionProductName.LINEAR",
        "short-vol-fixed-public-shadow",
        "btc_usdc",
    ):
        assert forbidden not in production_source

    for obsolete in (
        "short-vol-fixed-public-shadow-radar.json",
        "short-vol-fixed-public-shadow-underwriting.json",
        "short-vol-fixed-public-shadow-position.json",
    ):
        assert not (ROOT / "policies" / obsolete).exists()


def test_product_roadmap_does_not_grant_policy_or_runtime_authority() -> None:
    product = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for document in (product, readme):
        normalized = " ".join(document.split())
        assert "Only the upper-left channel is implemented" in normalized
        assert "INVERSE_BTC_SHORT_VOL_V2" in document
        assert (
            "| `INVERSE_BTC_SHORT_VOL` (`INVERSE_BTC_SHORT_VOL_V2`) | `IMPLEMENTED` |" in document
        )
        for channel in (
            "INVERSE_BTC_LONG_GAMMA",
            "INVERSE_ETH_SHORT_VOL",
            "INVERSE_ETH_LONG_GAMMA",
        ):
            assert f"| `{channel}` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |" in document


def test_entry_aggregate_and_segment_contracts_are_consistent() -> None:
    product = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    position = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    shadow = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_CASE.md").read_text(encoding="utf-8")
    service = (ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md").read_text(
        encoding="utf-8"
    )
    combined = " ".join(
        "\n".join((product, delivery, architecture, position, shadow, service)).split()
    )

    for phrase in (
        "process-independent Shadow Entry aggregate",
        "runtime owns only one bounded Observation Segment",
        "state-root/cases",
        "automatically restores all compatible non-terminal admitted Entries",
        "HANDOFF_GAP",
        "cannot synthesize `CLOSE`",
        "recovery data starts `UNKNOWN`",
        "FIRST_CLOSE_AND_ATTEMPT_SCHEDULED",
        "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS",
        "observation_quality=GAPPED",
        "qualification_eligible=false",
        "Selected no-trade Controls are not restored",
        "entry_position_baseline",
        "opened.json + segments/0/opened.json",
        "one no-replace atomic directory publication",
        "not a manifest or fencing protocol",
        "No database",
    ):
        assert phrase.lower() in combined.lower()
    normalized_shadow = " ".join(shadow.split())
    assert "An origin Segment is `CONTINUOUS`" in normalized_shadow
    assert "Every process-recovery Segment is `GAPPED`" in normalized_shadow
    assert "schema-v5" in normalized_shadow
    assert "migration branch" not in normalized_shadow
    assert "runs/<runtime-id>/cases/<case-id>" not in combined
    assert "A new runtime never resumes another runtime's Case" not in combined
    assert "immutable entry baselines from `opened.json`" not in combined
    assert "publishes its first `SHADOW_CASE_SEGMENT_OPENED` immediately after" not in combined
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
    assert "ordering is score lower bound" in contract


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


def test_inverse_policy_files_remain_byte_exact_and_content_identified() -> None:
    expected = {
        "policies/short-vol-inverse-btc-public-shadow-radar.json": (
            "fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d"
        ),
        "policies/short-vol-inverse-btc-public-shadow-underwriting.json": (
            "933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d"
        ),
        "policies/short-vol-inverse-btc-public-shadow-position.json": (
            "8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe"
        ),
    }
    for relative, digest in expected.items():
        path = ROOT / relative
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        parsed = json.loads(raw)
        assert raw == json.dumps(parsed, ensure_ascii=False, indent=2).encode() + b"\n"

    radar = json.loads(
        (ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json").read_bytes()
    )
    assert radar["product_spec_identity"] == (
        "sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131"
    )
    assert radar["policy_schema_version"] == 9
    assert radar["policy_family"] == "INVERSE_BTC_SHORT_VOL_ORDINAL_MARKET_STRUCTURE_V2"
    assert radar["score_model"]["maximum_cross_sectional_ticker_source_skew_ms"] == 6000
    assert radar["score_model"]["maximum_atm_delta_distance"] == 0.05
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

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)

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
    ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
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
    "short_vol_underwriting": (ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting"),
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


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


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


def test_agents_is_a_short_map_to_all_active_authority() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(agents.splitlines()) <= 100
    assert "are orthogonal; none overrides another" in agents
    for path in AUTHORITY_FILES:
        assert path.relative_to(ROOT).as_posix() in agents
    assert "tasks/TEMPLATE.md" in agents


def test_active_authority_has_explicit_status_and_no_stale_location() -> None:
    assert {path.name for path in (ROOT / "docs/authority").glob("*.md")} == {
        "CURRENT_STAGE.md",
        "DELIVERY_CONTRACT.md",
        "PRODUCT_CONSTITUTION.md",
        "SYSTEM_ARCHITECTURE.md",
    }
    assert {path.name for path in (ROOT / "docs/contracts").glob("*.md")} == {
        "SHORT_VOL_RADAR.md",
        "SHORT_VOL_UNDERWRITING_POSITION.md",
        "SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
        "SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md",
    }
    for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS):
        opening = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        assert "**Status:** ACTIVE" in opening, f"missing active status in {path}"
        assert "**Version:**" not in path.read_text(encoding="utf-8")
    markdown = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md"))
    assert "docs/architecture/PRODUCT_CONSTITUTION.md" not in markdown


def test_repository_relative_markdown_links_resolve() -> None:
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    checked = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        *AUTHORITY_FILES,
        *IMPLEMENTATION_CONTRACTS,
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


def test_internal_package_dependency_direction() -> None:
    for owner, root in PACKAGE_ROOTS.items():
        for path in root.rglob("*.py"):
            forbidden = _internal_imports(path) - ALLOWED_IMPORTS[owner]
            assert not forbidden, f"{path} imports higher layers: {sorted(forbidden)}"


def test_task_template_carries_business_and_evidence_contract() -> None:
    template = (ROOT / "tasks/TEMPLATE.md").read_text(encoding="utf-8")
    for section in (
        "## Business closure",
        "## Change declarations",
        "## Product operating behavior",
        "## Validation harness",
        "## Evidence boundary",
        "## Acceptance",
        "## Definition of done",
    ):
        assert section in template
    for value in (
        "**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | EVIDENCE_ONLY",
        "Minimal-hit recomputation",
        "business event or human stop",
        "duration, file, cutoff, archive, or process lifetime never",
        "**Market/Decision input contract change:**",
        "**Decision Policy change:**",
        "**Outcome/evaluation contract change:**",
        "**Stage/authorization change:**",
    ):
        assert value in template


def test_current_stage_records_the_only_active_offline_closure() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    flat = " ".join(current.split())
    marker = "**Sole authorized closure:**"

    assert current.count(marker) == 1
    assert f"{marker} `SHORT_VOL_SYSTEM_RUNTIME_SLIMDOWN`" in flat
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert "**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_REVALIDATION`" in current
    assert "**Persistent service:** `STOPPED_NO_DEPLOYMENT`" in current
    assert "**Live commands:** `FORBIDDEN`" in current
    assert "rejected its Radar results as unreliable" in flat
    assert "Deleted history is not a business premise" in flat
    assert "duplicate persistence reader/schema/provenance proof layer" in flat
    for stale_claim in (
        "R4_COMMISSIONED",
        "R4_COMMISSIONED_24H_OBSERVATION_ACTIVE",
        "R4_COMMISSIONED_24H_PENDING",
        "CONSUMED_FAILED_NO_RETRY",
        "engineering_end_to_end = PASS",
        "production_public_integration = PASS",
    ):
        assert stale_claim not in current


def test_only_the_active_runtime_task_is_present() -> None:
    assert sorted(path.name for path in (ROOT / "tasks").glob("*.md")) == [
        "SHORT_VOL_SYSTEM_RUNTIME_SLIMDOWN.md",
        "TEMPLATE.md",
    ]
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    assert "**Sole authorized closure:** `SHORT_VOL_SYSTEM_RUNTIME_SLIMDOWN`" in current
    assert "**Live commands:** `FORBIDDEN`" in current


def test_acceptance_only_runtime_harness_is_absent() -> None:
    assert not (ROOT / "apps/radar_runtime/src/radar_runtime/shadow.py").exists()
    assert not (
        ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting/manifest.py"
    ).exists()
    assert not (
        ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting/schemas.py"
    ).exists()
    assert not (
        ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting/validation.py"
    ).exists()
    cli = (ROOT / "apps/radar_runtime/src/radar_runtime/__main__.py").read_text(encoding="utf-8")
    underwriting = (
        ROOT / "packages/short_vol_underwriting/src/short_vol_underwriting/__init__.py"
    ).read_text(encoding="utf-8")
    assert "observe-shadow" not in cli
    assert '"observe"' not in cli
    assert "read_complete_evidence" not in underwriting
    assert "read_current_evidence" not in underwriting
    assert "validate_downstream_object" not in underwriting


def test_fixed_three_policy_chain_and_implementation_boundary_are_exact() -> None:
    radar_path = ROOT / "policies/short-vol-fixed-public-shadow-radar.json"
    underwriting_path = ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json"
    position_path = ROOT / "policies/short-vol-fixed-public-shadow-position.json"
    policy_paths = (radar_path, underwriting_path, position_path)

    assert sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "policies").rglob("*.json")
    ) == [
        "policies/short-vol-fixed-public-shadow-position.json",
        "policies/short-vol-fixed-public-shadow-radar.json",
        "policies/short-vol-fixed-public-shadow-underwriting.json",
    ]
    assert (ROOT / "packages/short_vol_underwriting").is_dir()
    assert "short_vol_underwriting" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    declared_policy_digests = (
        "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4",
        "sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af",
        "sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439",
    )
    declared_contract_digests = (
        UNDERWRITING_POSITION_CONTRACT_DIGEST,
        OUTCOME_CONTRACT_DIGEST,
    )

    radar_bytes = radar_path.read_bytes()
    assert len(radar_bytes) == 1405
    assert hashlib.sha256(radar_bytes).hexdigest() == (
        declared_policy_digests[0].removeprefix("sha256:")
    )
    radar = json.loads(radar_bytes)
    assert radar_bytes == (json.dumps(radar, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    assert radar["policy_schema_version"] == 3
    assert radar["policy_family"] == "POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE"
    assert radar["target_base_quantity_btc"] == 0.1

    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    key_blocks = re.findall(
        r"The exact top-level key set is:\n\n```text\n(.*?)\n```",
        contract,
        flags=re.DOTALL,
    )
    assert len(key_blocks) == 2
    underwriting_keys = tuple(key_blocks[0].splitlines())
    position_keys = tuple(key_blocks[1].splitlines())
    assert len(underwriting_keys) == 24
    assert len(position_keys) == 23

    underwriting_bytes = underwriting_path.read_bytes()
    position_bytes = position_path.read_bytes()
    assert hashlib.sha256(underwriting_bytes).hexdigest() == (
        declared_policy_digests[1].removeprefix("sha256:")
    )
    assert hashlib.sha256(position_bytes).hexdigest() == (
        declared_policy_digests[2].removeprefix("sha256:")
    )
    underwriting = json.loads(underwriting_bytes)
    position = json.loads(position_bytes)
    assert tuple(underwriting) == underwriting_keys
    assert tuple(position) == position_keys
    assert underwriting_bytes == (
        json.dumps(underwriting, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    assert position_bytes == (
        json.dumps(position, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )

    expected_budgets = {
        "clock_currentness_budget_ms": 45000,
        "platform_currentness_budget_ms": 90000,
        "combo_snapshot_send_budget_ms": 30000,
        "combo_snapshot_response_budget_ms": 30000,
        "index_currentness_budget_ms": 90000,
        "option_ticker_currentness_budget_ms": 300000,
    }
    fee_metadata = (
        "TAKER",
        "https://support.deribit.com/hc/en-us/articles/25944746248989-Fees",
        "2026-07-30T10:47:09Z",
        "FEE_TIER_CHANGES_EFFECTIVE_2026-08-01",
        0.0003,
    )
    assert underwriting["policy_semantic_name"] == ("SHORT_VOL_PUBLIC_SHADOW_UNDERWRITING_POLICY")
    assert underwriting["radar_policy_identity"] == (
        "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
    )
    assert position["policy_semantic_name"] == "SHORT_VOL_PUBLIC_SHADOW_POSITION_POLICY"
    assert position["underwriting_policy_identity"] == (
        f"sha256:{hashlib.sha256(underwriting_bytes).hexdigest()}"
    )
    assert (
        underwriting["target_base_quantity_btc"]
        == radar["target_base_quantity_btc"]
        == (position["target_base_quantity_btc"])
    )
    for key, value in expected_budgets.items():
        assert underwriting[key] == position[key] == value
        assert type(underwriting[key]) is int
        assert type(position[key]) is int
    for policy in (underwriting, position):
        assert (
            policy["fee_role"],
            policy["fee_schedule_source_url"],
            policy["fee_schedule_retrieved_at_utc"],
            policy["fee_schedule_effective_label"],
            policy["fee_rate_index_fraction"],
        ) == fee_metadata
        for key, value in policy.items():
            if key not in {
                "policy_semantic_name",
                "radar_policy_identity",
                "underwriting_policy_identity",
                "fee_role",
                "fee_schedule_source_url",
                "fee_schedule_retrieved_at_utc",
                "fee_schedule_effective_label",
            }:
                assert type(value) in {int, float}

    assert tuple(
        underwriting[key]
        for key in (
            "path_risk_reserve_usdc",
            "jump_risk_reserve_usdc",
            "tail_risk_reserve_usdc",
            "liquidity_cost_reserve_usdc",
            "uncertainty_reserve_usdc",
            "settlement_cost_reserve_usdc",
        )
    ) == (2, 2, 2, 2, 2, 2)
    assert underwriting["maximum_underwriting_reserved_loss_usdc"] == 250
    assert underwriting["minimum_net_entry_credit_usdc"] == 15
    assert underwriting["minimum_net_credit_to_payoff_cap_fraction"] == 0.1
    assert underwriting["maximum_entry_consumed_level_count"] == 10000
    assert position["latest_exit_lead_ms"] == 1800000
    assert position["maximum_projected_net_loss_usdc"] == 125
    assert position["maximum_absolute_short_delta"] == 0.5
    assert position["maximum_absolute_index_return_since_entry_fraction"] == 0.05
    assert position["maximum_absolute_index_return_since_prior_evaluation_fraction"] == 0.01
    assert position["maximum_short_mark_iv_increase_fraction"] == 0.15
    assert position["maximum_close_consumed_level_count"] == 10000
    assert position["minimum_take_profit_usdc"] == 10
    assert position["maximum_remaining_premium_fraction"] == 0.5

    for label in (
        "POLICY_CHOICE_WITHOUT_PRIOR_OUTCOME_EVIDENCE",
        "NON_QUALIFIED_FORWARD_OBSERVATION_BASELINE",
    ):
        assert all(label.encode("utf-8") not in path.read_bytes() for path in policy_paths)

    underwriting_contract = ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md"
    outcome_contract = ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md"
    assert hashlib.sha256(underwriting_contract.read_bytes()).hexdigest() == (
        declared_contract_digests[0].removeprefix("sha256:")
    )
    assert hashlib.sha256(outcome_contract.read_bytes()).hexdigest() == (
        declared_contract_digests[1].removeprefix("sha256:")
    )


def test_authority_describes_the_current_single_public_runtime() -> None:
    current_stage = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    architecture = _flat(ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md")
    readme = _flat(ROOT / "README.md")
    combined = " ".join(
        path.read_text(encoding="utf-8")
        for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS, ROOT / "README.md")
    )

    for value in (
        "OFFLINE_PUBLIC_SHADOW_RUNTIME",
        "NOT_ACCEPTED_PENDING_REVALIDATION",
        "SHORT_VOL_SYSTEM_RUNTIME_SLIMDOWN",
        "STOPPED_NO_DEPLOYMENT",
        "Live commands:",
        "FORBIDDEN",
    ):
        assert value in current_stage

    for value in (
        "Deribit",
        "Radar",
        "Underwriting",
        "Shadow",
        "Position",
        "Outcome",
        "Workbench",
    ):
        assert value in architecture
        assert value in readme
    assert "flush_pending()" in architecture

    for removed in (
        "NOT_APPLICABLE_TTE",
        "configured_risk_scenario_slot_count",
        "OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_ASSESSMENT",
        "STRUCTURE_ASSESSMENT_REACHABILITY",
        "NON-ACTIVE HISTORICAL APPENDIX",
        "EXECUTABLE_VARIANCE_RICHNESS",
    ):
        assert removed not in combined


def test_radar_contract_keeps_market_signal_execution_and_decision_distinct() -> None:
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    radar_flat = " ".join(radar.split())

    terms = (
        "Market Monitor",
        "Detector evaluation",
        "Anomaly episode",
        "Public atomic availability",
        "Future maker/order state",
        "Candidate",
        "`CLOSE`",
        "Shadow close opportunity",
        "Actual exposure duration",
    )
    for term in terms:
        assert term in radar_flat

    assert (
        "The Radar never returns `CANDIDATE`, `WATCH`, `ABSTAIN`, `HOLD`, or `CLOSE`." in radar_flat
    )
    assert "Two component-leg orders are not an atomic substitute at any layer." in radar_flat
    assert "No Layer 2 result changes Layer 1." in radar_flat
    assert (
        "No current enum, placeholder service, simulation, or artifact represents them."
        in radar_flat
    )
    assert "The objects do not contain the full option chain" in radar_flat
    assert (
        "This closure stops at `SHORT_VOL_ANOMALY_EVENT` plus optional "
        "`PUBLIC_ATOMIC_QUOTE_EVENT`." in radar_flat
    )
    assert "Neither entry kind has a planned holding duration." in radar_flat
    assert "never let a missing quote override a known hard-close condition" in radar_flat
    assert "emit `SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE`" in radar_flat
    assert "keep `LEGGED_CLOSE_REFERENCE` diagnostic" in radar_flat


def test_persistent_service_contract_is_minimal_and_has_no_service_ledger() -> None:
    contract_path = ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md"
    contract = contract_path.read_text(encoding="utf-8")
    flat = " ".join(contract.split())
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    assert not (ROOT / "apps/radar_runtime/src/radar_runtime/service_evidence.py").exists()
    assert not (ROOT / "apps/radar_runtime/src/radar_runtime/commissioning.py").exists()
    assert not (ROOT / "tests/test_persistent_service_commissioning.py").exists()
    for invariant in (
        "Deribit → Radar → Underwriting → Shadow → Position → Outcome",
        "service.lock",
        "one public Deribit session",
        "same reducer and downstream owner",
        "service lifecycle events, terminal manifests",
        "There is no repository reader, duplicate schema table, provenance envelope",
        "at most once per 500 monotonic milliseconds",
        "semantic safety or lifecycle status change",
        "before reconnect or clean stop",
        "loopback IP",
        "Other methods return 405",
    ):
        assert invariant in flat
    for removed in (
        "PersistentServiceTerminalIdentity",
        "read_complete_persistent_service_evidence",
        "lifecycle_inventory_identity",
        "service_evidence_status",
    ):
        assert removed not in contract
    assert "`STOPPED_NO_DEPLOYMENT`" in current
    assert "**Live commands:** `FORBIDDEN`" in current
    assert "**Sole authorized closure:** `SHORT_VOL_SYSTEM_RUNTIME_SLIMDOWN`" in current
    assert "Deleted history is not a business premise" in " ".join(current.split())


def test_at_most_one_active_task_and_it_declares_every_change_axis() -> None:
    task_paths = tuple(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md")
    assert len(task_paths) <= 1, f"multiple task files: {[path.name for path in task_paths]}"
    active = tuple(
        path
        for path in task_paths
        if "**Status:** ACTIVE" in "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
    )

    assert len(active) <= 1, f"multiple active tasks: {[path.name for path in active]}"
    assert all(
        "**Status:** COMPLETE" not in path.read_text(encoding="utf-8") for path in task_paths
    )
    for path in active:
        text = path.read_text(encoding="utf-8")
        task_kind_matches = re.findall(
            r"^\*\*Task kind:\*\* (AUTHORITY_ONLY|IMPLEMENTATION|EVIDENCE_ONLY)$",
            text,
            flags=re.MULTILINE,
        )
        assert len(task_kind_matches) == 1, f"invalid or missing task kind in {path}"
        task_kind = task_kind_matches[0]
        if task_kind == "AUTHORITY_ONLY":
            assert "**Runtime implementation:** FORBIDDEN" in text
            assert "**Live commands:** FORBIDDEN" in text
        elif task_kind == "IMPLEMENTATION":
            assert "**Runtime implementation:** REQUIRED" in text
            assert "**Live commands:** FORBIDDEN" in text
        else:
            assert "**Runtime implementation:** FORBIDDEN" in text
            assert "**Live commands:** REQUIRED" in text
        for declaration in (
            "**Market/Decision input contract change:**",
            "**Decision Policy change:**",
            "**Outcome/evaluation contract change:**",
            "**Stage/authorization change:**",
        ):
            assert declaration in text, f"missing {declaration} in {path}"


def test_repository_owned_contracts_use_semantic_not_ordinal_identities() -> None:
    forbidden = re.compile(
        r"(?:^|[^A-Za-z0-9])v[0-9]+(?:[^A-Za-z0-9]|$)|_v[0-9]+|task-(?:v[0-9]+-)?[0-9]+",
        re.IGNORECASE,
    )
    checked = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / "tasks").rglob("*.md"),
        *(ROOT / "apps").rglob("*.py"),
        *(ROOT / "packages").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    )
    for path in checked:
        text = path.read_text(encoding="utf-8")
        if path == ROOT / "apps/radar_runtime/src/radar_runtime/deribit_public.py":
            text = text.replace("/api/" + "v" + "2", "/api/external")
        relative_path = path.relative_to(ROOT).as_posix()
        assert forbidden.search(relative_path) is None, f"ordinal identity remains in {path}"
        assert forbidden.search(text) is None, f"ordinal identity remains in {path}"
        if path.suffix == ".py" and (
            ROOT / "apps" in path.parents or ROOT / "packages" in path.parents
        ):
            assert '"version":' not in text, f"owned version field remains in {path}"


def test_index_publication_contract_owns_one_current_evidence_schema() -> None:
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    radar_flat = " ".join(radar.split())

    for invariant in (
        "`IndexTailStatus` and `IndexBaselineState.status` remain current production Python "
        "projections",
        "This compatibility projection does not make publication pending a coverage blocker",
        "`INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name",
        "not serialized. Current coverage rejects",
        "`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING`",
        "Normal index publication pending is not a suspension or detector state",
        "baseline component of identity is only the exact selected immutable `MinuteClose` tuple",
        "provenance, not detector de-duplication facts",
        "The summary contains no transport, RPC, source-shape, publication-cadence",
        "same-tail/same-target latch",
    ):
        assert invariant in radar_flat
    for forbidden in (
        "Pending statuses preserve episode identity",
        "pause known duration, stop Layer 2, reset incomplete persistence",
    ):
        assert forbidden not in radar


def test_stage_record_rejects_deleted_live_history_as_authority() -> None:
    current_stage = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")

    for invariant in (
        "**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_REVALIDATION`",
        "**Persistent service:** `STOPPED_NO_DEPLOYMENT`",
        "**Live commands:** `FORBIDDEN`",
        "Deleted history is not a business premise",
        "reconstructing or relabelling deleted historical results",
    ):
        assert invariant in current_stage

    for stale_claim in (
        "REACHABILITY_SMOKE`: `MET",
        "OPERATIONAL_SOAK`: `MET",
        "R4_COMMISSIONED",
        "natural_shadow_opportunity = NOT_OBSERVED",
    ):
        assert stale_claim not in current_stage


def test_delegation_separates_prepush_receipt_from_postpush_remote_equality() -> None:
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    delivery_flat = " ".join(delivery.split())

    for invariant in (
        "Before a non-force push",
        "pre-push independent exact-commit pass receipt",
        "intended bounded remote ref",
        "After the push",
        "verified remote ref value equals the exact commit",
        "Only the post-push binding",
    ):
        assert invariant in delivery_flat

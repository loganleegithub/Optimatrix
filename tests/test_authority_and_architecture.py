from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_FILES = (
    ROOT / "docs/authority/PRODUCT_CONSTITUTION.md",
    ROOT / "docs/authority/CURRENT_STAGE.md",
    ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md",
    ROOT / "docs/authority/DELIVERY_CONTRACT.md",
)

IMPLEMENTATION_CONTRACTS = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md",)

INTERNAL_PACKAGES = {
    "market_monitor",
    "options_domain",
    "short_vol_radar",
    "radar_runtime",
}

PACKAGE_ROOTS = {
    "market_monitor": ROOT / "packages/market_monitor/src/market_monitor",
    "options_domain": ROOT / "packages/options_domain/src/options_domain",
    "short_vol_radar": ROOT / "packages/short_vol_radar/src/short_vol_radar",
    "radar_runtime": ROOT / "apps/radar_runtime/src/radar_runtime",
}

ALLOWED_IMPORTS = {
    "market_monitor": {"market_monitor"},
    "options_domain": {"market_monitor", "options_domain"},
    "short_vol_radar": {"market_monitor", "options_domain", "short_vol_radar"},
    "radar_runtime": INTERNAL_PACKAGES,
}


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
    assert {path.name for path in (ROOT / "docs/contracts").glob("*.md")} == {"SHORT_VOL_RADAR.md"}
    for path in (*AUTHORITY_FILES, *IMPLEMENTATION_CONTRACTS):
        opening = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        assert "**Status:** ACTIVE" in opening, f"missing active status in {path}"
        assert "**Version:**" not in path.read_text(encoding="utf-8")

    markdown = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md"))
    assert "docs/architecture/PRODUCT_CONSTITUTION.md" not in markdown


def test_repository_relative_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    checked_roots = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        *AUTHORITY_FILES,
        *IMPLEMENTATION_CONTRACTS,
        *(ROOT / "tasks").glob("*.md"),
    )

    for path in checked_roots:
        for raw_target in link_pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            assert resolved.exists(), f"broken link from {path}: {raw_target}"


def _internal_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        modules: tuple[str, ...]
        if isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules = (node.module,)
        else:
            continue
        imports.update(
            module.split(".", 1)[0]
            for module in modules
            if module.split(".", 1)[0] in INTERNAL_PACKAGES
        )
    return imports


def test_internal_package_dependency_direction() -> None:
    for owner, root in PACKAGE_ROOTS.items():
        for path in root.rglob("*.py"):
            forbidden = _internal_imports(path) - ALLOWED_IMPORTS[owner]
            assert not forbidden, f"{path} imports forbidden higher layer(s): {sorted(forbidden)}"


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

    assert "**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | EVIDENCE_ONLY" in template
    assert "Minimal-hit recomputation" in template
    assert "business event or human stop" in template
    assert "duration, file, cutoff, archive, or process lifetime never" in template

    for declaration in (
        "**Market/Decision input contract change:**",
        "**Decision Policy change:**",
        "**Outcome/evaluation contract change:**",
        "**Stage/authorization change:**",
    ):
        assert declaration in template


def test_current_stage_records_established_radar_without_activating_successor() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")

    marker = "**Sole authorized next product-capability closure:**"
    assert current_stage.count(marker) == 1
    assert f"{marker} `NONE — no successor closure activated`" in current_stage
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current_stage
    assert (
        "**Implemented runtime capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`" in current_stage
    )
    assert "**Production Short Vol Radar:** `ESTABLISHED`" in current_stage
    assert "## Queued sequence — not authorized" in current_stage


def test_completed_radar_consolidation_leaves_no_active_task_or_successor() -> None:
    old_task = ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md"
    task_path = ROOT / "tasks/RADAR_IMPLEMENTATION_SURFACE_CONSOLIDATION.md"

    assert not old_task.exists()
    assert not task_path.exists()
    assert sorted(path.name for path in (ROOT / "tasks").glob("*.md")) == ["TEMPLATE.md"]

    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    assert "There is no active product-capability or implementation-maintenance closure" in (
        current_stage
    )
    assert "`NONE — no successor closure activated`" in current_stage

    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    assert "`IndexTailStatus` and `IndexBaselineState.status` remain current production" in radar
    assert "`INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name" in radar
    assert "never serialized by the current or sealed evidence writers" in radar
    assert "`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING`" in radar


def test_authority_defines_one_live_short_vol_business_flow() -> None:
    constitution = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    target_authority = "\n".join(
        (constitution, current_stage, architecture, delivery, radar, readme)
    )
    constitution = " ".join(constitution.split())
    current_stage = " ".join(current_stage.split())
    architecture = " ".join(architecture.split())
    delivery = " ".join(delivery.split())
    radar = " ".join(radar.split())
    readme = " ".join(readme.split())

    for invariant in (
        "Receiving a relevant public market event",
        "Normal market events that produce no Short Vol anomaly are not durable business objects",
        "POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE",
        "`SHORT_VOL_ANOMALY_EVENT`",
        "`PUBLIC_ATOMIC_QUOTE_EVENT`",
        "`SHADOW_ENTRY`",
        "`EXECUTED_ENTRY`",
        "refreshed target-size atomic combo quote",
        "Actual exposure begins with the first opening fill",
        "Neither entry kind selects a planned holding duration",
        "`SHADOW_CLOSE_OPPORTUNITY`",
        "A missing quote cannot erase a known hard-close obligation",
    ):
        assert invariant in constitution
    assert (
        "`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`"
        in constitution
    )

    for invariant in (
        "Root blocker",
        "human may approve a successor inside the same authorized Policy schema",
        "no replay, independent offline recomputation",
        "`PUBLIC_RADAR_ESTABLISHMENT_DELEGATION`",
        "The two gates remain semantically independent",
        "does not prove indefinite uptime",
        "not authorization for persistent service deployment",
        "private/account data",
        "orders, fills, capital",
    ):
        assert invariant in current_stage

    for invariant in (
        "There is no capture job followed by a scan job",
        "Normal live operation does not seal every market event",
        "`SHORT_VOL_ANOMALY_EVENT`",
        "`PUBLIC_ATOMIC_QUOTE_EVENT`",
        "quiet unchanged book remains current",
        "NO_TARGET_SIZE_CREDIT_QUOTE",
        "first Radar closure intentionally creates no replay path",
        "no preselected holding duration",
    ):
        assert invariant in architecture

    assert "Do not require full replay" in delivery
    assert (
        "Predetermined elapsed time may bound a validation run but neither accepts nor rejects "
        "a capability" in delivery
    )
    assert "human-approved successor identity and new forward interval" in delivery
    assert "`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` are independent" in delivery
    assert "Terminal business-goal delegation" in delivery
    assert "candidate author cannot be its sole verifier" in delivery
    assert "## Denominator integrity" in delivery
    assert "`UNKNOWN` is neither numeric zero nor economic `ABSTAIN`" in delivery

    for invariant in (
        "**Current implementation state:** `ESTABLISHED`",
        "**Owning implemented capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`",
        "`POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE`",
        "`detector_state`",
        "`public_atomic_quote_state`",
        "`NOT_EVALUATED`",
        "`NO_TARGET_SIZE_CREDIT_QUOTE`",
        "instrument.state.option.USDC",
        "final 30 minutes",
        "does not become stale merely because no level changed",
        "target_base_quantity_btc",
        "human or an active terminal-goal delegate may pre-bind a successor inside this same "
        "Policy schema",
        "`qty_tick_size`",
        "`data.timestamp`",
        "baseline_total_variance",
        "`runtime identity × Policy identity × instrument_name × activation_causal_seq`",  # noqa: RUF001
        "`Policy identity × expiry_timestamp × option_type`",  # noqa: RUF001
        "`public/status`",
        "`public/set_heartbeat`",
        "`BAND_SUSPENDED`",
        "`INDEX_TAIL_PENDING`",
        "`IndexTailStatus`",
        "`TIME_BOUNDARY_PENDING`",
        "`WATERMARK_PENDING`",
        "bootstrap `WARMUP`, not `CONTINUITY_GAP`",
        "complete snapshot",
        "`LATE_IGNORED`",
        "`global_continuity_epoch`",
        "`current_market_truth_coverage`",
        "`option_local_availability`",
        "has_current_full_formula = true",
        "`EvidenceWriter` receives only a settled",
        "`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` are independent production-public evidence "
        "gates",
        "`policy_schema_version = 3`",
        "`ticker_source_stale_deadline_ms`",
        "`AHEAD_IGNORED`",
        "`operational_diagnostics_schema_version = 6`",
        "`blocking_groups`",
        "sealed version-5, version-4, version-3, and version-2",
        "`index_baseline_publication`",
        "`KNOWN_INELIGIBLE`",
        "`UNKNOWN_AT_GAP`",
        "required combo order direction",
        "gross_entry_credit_usdc > 0",
        "-signed_order_amount_btc × required_side_vwap_usdc_per_btc",  # noqa: RUF001
        "`NOT_A_DELIVERY_TWAP_DISTRIBUTION_FORECAST`",
        "applicable_instrument_count >= 1",
        "known_per_instrument_detector_evaluation_count >= 1",
        "known_full_detector_formula_evaluation_count >= 1",
        "complete_aggregate_detector_evaluation_count >= 1",
        "complete_aggregate_with_full_formula_evaluation_count >= 1",
        "does not create replay, a second calculation path",
        "## Public-source basis and inference limits",
        "define mechanics, not a universal target quantity",
    ):
        assert invariant in radar

    for invariant in (
        "Ordinary no-anomaly updates",
        "planned holding duration",
        "`PRODUCTION_PUBLIC_SHORT_VOL_RADAR`",
        "No successor product-capability closure is active",
        "future maker/order/fill",
    ):
        assert invariant in readme

    legacy_fragments = (
        "NOT_APPLICABLE_" + "TTE",
        "configured_risk_" + "scenario_slot_count",
        "OBSERVED_PATH_STRESS_FIXED_PRIOR_" + "RADAR_ASSESSMENT",
        "STRUCTURE_ASSESSMENT_" + "REACHABILITY",
        "NON-ACTIVE HISTORICAL " + "APPENDIX",
        "`EXECUTABLE_VARIANCE_" + "RICHNESS`",
    )
    for fragment in legacy_fragments:
        assert fragment not in target_authority


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
        if "**Task kind:** `AUTHORITY_ONLY`" in text:
            assert "**Runtime implementation:** FORBIDDEN" in text
            assert "**Live commands:** FORBIDDEN" in text
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


def test_index_publication_contract_owns_current_projection_and_actual_sealed_vocabulary() -> None:
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    radar_flat = " ".join(radar.split())

    for invariant in (
        "`IndexTailStatus` and `IndexBaselineState.status` remain current production Python "
        "projections",
        "This compatibility projection does not make publication pending a coverage blocker",
        "`INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name",
        "never serialized by the current or sealed evidence writers",
        "`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING`",
        "`SOAK_PENDING_REASONS`",
        "Normal index publication pending is not a suspension or detector state",
        "baseline component of identity is only the exact selected immutable `MinuteClose` tuple",
        "provenance, not detector de-duplication facts",
        "current-schema writer and validator path accept only version 6",
        "Explicit read-only validators continue to validate sealed version-5, version-4, "
        "version-3, and version-2",
        "implementation-surface consolidation may not change the current version-6 writer/reader",
        "same-tail/same-target latch",
    ):
        assert invariant in radar_flat
    for forbidden in (
        "Pending statuses preserve episode identity",
        "pause known duration, stop Layer 2, reset incomplete persistence",
    ):
        assert forbidden not in radar


def test_stage_record_binds_both_independent_live_gates() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    current_stage_flat = " ".join(current_stage.split())

    for invariant in (
        "candidate commit `9c58120d358fd0e0ccb4885123ab95c67d1c3f31`",
        "candidate tree `1ff49ff697df1a91237eb35f290301e26a7c06dc`",
        "both live manifests' pre-run verified remote ref "
        "`refs/heads/codex/radar-repository-consolidation` resolved to that exact candidate commit",
        "does not prove indefinite uptime",
        "no successor closure",
    ):
        assert invariant in current_stage_flat

    smoke_binding = (
        "`REACHABILITY_SMOKE`: `MET`, independently accepted by "
        "`/Users/logan/Optimatrix-smoke/receipts/"
        "reachability-smoke-radar-consolidation-001-independent-acceptance.json`, "
        "SHA-256 `4bbf832ab7340e7224a0df5db79aea1cd6fed33d156f2aeec12690f986217a4f`, "
        "manifest SHA-256 `70511dad86aa37dcaaab1167b688d342a33a8248635097b6f4c84b436e8e09fd`, "
        "evidence directory "
        "`/Users/logan/Optimatrix-smoke/evidence/reachability-smoke-radar-consolidation-001`, "
        "summary SHA-256 `700dbbf2649830b656a75de3e3eb74aabef21cb4003786429b823091abcbbfa6`, "
        "and 47-entry absolute-path-bound ordered evidence manifest SHA-256 "
        "`3b70b2a7d93b3bbcf2ce31c0e63bc03ff971b18ea4ad7e9270cd943a351cccde`"
    )
    soak_binding = (
        "`OPERATIONAL_SOAK`: `MET`, independently accepted by "
        "`/Users/logan/Optimatrix-soak/receipts/"
        "operational-soak-radar-consolidation-001-independent-acceptance.json`, "
        "SHA-256 `d38c5bebef1e2bccfeeb9c69715970d03fda2a0359f02520a5c3deef08463345`, "
        "manifest SHA-256 `2cf6af08bdcf7ec3c72e5bbb9292b58261c992dda67b298cf7f4ea99eac64574`, "
        "evidence directory "
        "`/Users/logan/Optimatrix-soak/evidence/operational-soak-radar-consolidation-001`, "
        "summary SHA-256 `1ec01c5dba427e3a273671ef57421a6f6bfe01f95d26416e35a2d69fe6a6b218`, "
        "and absolute-path-bound ordered evidence manifest SHA-256 "
        "`7ff691e9b3665e0e9db7196a032440a9f6e79c6802f803b7546cb23f5125f361`"
    )
    assert smoke_binding in current_stage_flat
    assert soak_binding in current_stage_flat


def test_delegation_separates_prepush_receipt_from_postpush_remote_equality() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    current_stage_flat = " ".join(current_stage.split())
    delivery_flat = " ".join(delivery.split())

    assert "both live manifests' pre-run verified remote ref" in current_stage_flat
    assert "resolved to that exact candidate commit" in current_stage_flat
    for invariant in (
        "Before a non-force push",
        "pre-push independent exact-commit pass receipt",
        "intended bounded remote ref",
        "After the push",
        "verified remote ref value equals the exact commit",
        "Only the post-push binding",
    ):
        assert invariant in delivery_flat

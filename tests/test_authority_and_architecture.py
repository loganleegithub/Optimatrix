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


def test_current_stage_authorizes_exactly_one_next_closure() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")

    marker = "**Sole authorized next product-capability closure:**"
    assert current_stage.count(marker) == 1
    assert f"{marker} `SHORT_VOL_RADAR_ESTABLISHMENT`" in current_stage
    assert "**Implemented runtime capability:** `NONE`" in current_stage
    assert "**Production Short Vol Radar:** `NOT_ESTABLISHED`" in current_stage
    assert "## Queued sequence — not authorized" in current_stage


def test_short_vol_task_records_terminal_delegation_and_conditional_live_gates() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    opening = "\n".join(task.splitlines()[:70])

    assert "**Status:** ACTIVE" in opening
    assert "**Construction gate:** `OPENED_BY_EXPLICIT_HUMAN_COMMAND_2026_07_25`" in opening
    assert (
        "**Terminal business-goal delegation:** `PUBLIC_RADAR_ESTABLISHMENT_DELEGATION`" in opening
    )
    assert (
        "**Current construction subgate:** "
        "`ONLINE_INDEX_BASELINE_PUBLICATION_CONTINUITY_REARCHITECTURE`" in opening
    )
    assert (
        "**Current subgate exact base HEAD:** `d6e506b343c6fc5570243ba01def46d6a047428e`" in opening
    )
    assert "`CONDITIONALLY_AUTHORIZED_AFTER_OFFLINE_ACCEPTANCE_AND_EXACT_RUN_BINDING`" in opening
    assert "`CONDITIONALLY_AUTHORIZED_AFTER_SMOKE_ACCEPTANCE_AND_EXACT_RUN_BINDING`" in opening


def test_successor_soak_keeps_publication_diagnostic_outside_coverage_denominators() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    successor = task.split("### Successor `OPERATIONAL_SOAK`", maxsplit=1)[1].split(
        "## First-principles scope",
        maxsplit=1,
    )[0]

    for invariant in (
        "Integrity ledger",
        "Index-baseline-publication ledger",
        "Currentness-incident recovery ledger",
        "diagnostic and may overlap `KNOWN_COMPLETE`",
        "duration(K) / 3_600_000 >= 0.99",
        "`E = W \\ G`",
    ):
        assert invariant in successor
    for forbidden in (
        "pending_budget_status",
        "P_budget_ms",
        "require duration(P) <= 36_000",
        "E = W \\ (P union G)",
    ):
        assert forbidden not in successor


def test_successor_soak_local_recovery_does_not_rebind_global_witness() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    successor = task.split("### Successor `OPERATIONAL_SOAK`", maxsplit=1)[1].split(
        "## First-principles scope",
        maxsplit=1,
    )[0]

    for invariant in (
        "does not relabel the earlier global witness as post-recovery",
        "one registered exact Policy path/digest",
        "heartbeat wire observation is conditional",
    ):
        assert invariant in successor
    assert "strictly later exact joint witness" not in successor


def test_historical_soak_remains_not_met_without_governing_the_terminal_successor() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")

    for invariant in (
        "/Users/logan/Optimatrix-soak/policies/operational-soak-successor.json",
        "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4",
        "/Users/logan/Optimatrix-soak/evidence/operational-soak-attempt-001",
        "/Users/logan/Optimatrix-soak/evidence/operational-soak-attempt-003",
        "425e7304ae3f102aefd2f3bedd23ea12767e597b05e17cc3b74988f4282dd30f",
        "25f77930d041421a6bc5029848aec79ff4025dc1573cb037dc158064b40bd273",
        "attempt-003`, whose acceptance is permanently",
        "continuous_covered_after_witness_ms >= 3_600_000",
        "semantic comparison to the predecessor Smoke Policy proves that only `band_id` changed",
        "Attempt-001 is permanently `NOT_MET`",
        "heartbeat wire probe had to receive its",
        "a human had to freeze new",
        "historical `3_600_000 ms` value was not",
        "They do not govern the current",
        "`PUBLIC_RADAR_ESTABLISHMENT_DELEGATION`",
    ):
        assert invariant in task


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
        "A covered `NO_ANOMALY` interval is valid reachability evidence",
        "human may approve a successor inside the same authorized Policy schema",
        "no replay, independent offline recomputation",
        "named bounded terminal-goal delegation",
        "`PUBLIC_RADAR_ESTABLISHMENT_DELEGATION`",
        "`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` remain independent evidence gates",
        "does not authorize `main` merge",
        "private/account data",
        "orders, fills, trades",
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
        (
            "**Current implementation state:** TERMINAL PUBLIC-RADAR GOAL ACTIVE — EXACT-CANDIDATE "
            "OFFLINE ACCEPTANCE REQUIRED BEFORE PRE-AUTHORIZED SMOKE"
        ),
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
        "`SHORT_VOL_RADAR_ESTABLISHMENT`",
        "future maker/order/fill",
        "expressly terminal-goal-delegated successor inside the declared Policy schema",
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
        if path == ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md":
            text = text.replace(
                "/Users/logan/Optimatrix-smoke/policies/reachability-smoke-" + "v" + "2.json",
                "/registered/external/reachability-smoke-policy.json",
            )
        relative_path = path.relative_to(ROOT).as_posix()
        assert forbidden.search(relative_path) is None, f"ordinal identity remains in {path}"
        assert forbidden.search(text) is None, f"ordinal identity remains in {path}"
        if path.suffix == ".py" and (
            ROOT / "apps" in path.parents or ROOT / "packages" in path.parents
        ):
            assert '"version":' not in text, f"owned version field remains in {path}"


def test_index_publication_successor_is_registered_authority_first() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    opening = "\n".join(task.splitlines()[:75])
    assert "`ONLINE_INDEX_BASELINE_PUBLICATION_CONTINUITY_REARCHITECTURE`" in opening
    assert "`d6e506b343c6fc5570243ba01def46d6a047428e`" in opening
    section = task.split(
        "### `ONLINE_INDEX_BASELINE_PUBLICATION_CONTINUITY_REARCHITECTURE`",
        maxsplit=1,
    )[1].split("## Business closure", maxsplit=1)[0]
    for declaration in (
        "**Market/Decision input contract change:** `APPROVED`",
        "**Decision Policy change:** `NONE`",
        "**Outcome/evaluation contract change:** `NONE`",
        "**Stage/authorization change:** `APPROVED`",
        "Permission remains `PUBLIC_SHADOW`",
        "implemented runtime capability remains `NONE`",
        "`NOT_ESTABLISHED`",
        "operational-soak-attempt-005",
        "operational-soak-attempt-006",
        "7270ade324ebcb5c362b279737fab22be2c7745639b238cea0b31bac5d729a52",
        "4f80b34a1000ca22cc61f04d9f327a310e3f10d86f5514599ebfbd9ad15753bf",
    ):
        assert declaration in section
    assert (
        len(tuple(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md"))
        == 1
    )


def test_current_index_publication_contract_does_not_reactivate_sealed_pending_semantics() -> None:
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    radar_flat = " ".join(radar.split())
    task_flat = " ".join(task.split())
    task_currentness = task.split("### Index-minute coverage", maxsplit=1)[1].split(
        "## Configured trailing-variance baseline",
        maxsplit=1,
    )[0]
    task_currentness_flat = " ".join(task_currentness.split())

    for invariant in (
        "current runtime never enters it",
        "Normal index publication pending is not a suspension or detector state",
        "baseline component of identity is only the exact selected immutable `MinuteClose` tuple",
        "provenance, not detector de-duplication facts",
        "current-schema writer and validator path accept only version 6",
        "same-tail/same-target latch",
    ):
        assert invariant in radar_flat
    for invariant in (
        "Normal publication pending preserves the previously published tuple as `AVAILABLE`",
        "never enters the sealed-version legacy `INDEX_TAIL_PENDING` tracker state",
        "Pending phase is a target-scoped latch",
    ):
        assert invariant in task_currentness_flat
    assert "provenance, not detector de-duplication facts" in task_flat
    for forbidden in (
        "Pending statuses preserve episode identity",
        "pause known duration, stop Layer 2, reset incomplete persistence",
    ):
        assert forbidden not in task_currentness


def test_current_task_uses_current_schema_and_explicit_sealed_readers() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    task_flat = " ".join(task.split())
    current_evidence = task.split(
        "New evidence requires strict `operational_diagnostics_schema_version = 6`",
        maxsplit=1,
    )[1].split("## Product operating behavior", maxsplit=1)[0]

    assert "index_baseline_publication" in current_evidence
    assert "sealed version-5, version-4, version-3, and version-2" in current_evidence
    assert "Each current version-6 segment" in current_evidence
    assert "schema version 5" not in current_evidence
    assert "No repeated technical approval is required between those steps." in task_flat
    assert "persistent service deployment" in task_flat
    assert "remain unauthorized" in task_flat
    assert "regular non-symlink `.json` entries" in task_flat
    assert "exactly one summary named `radar-run-summary.json`" in task_flat
    assert "sealed readers keep their historical behavior" in " ".join(radar.split())


def test_active_delegation_seals_the_original_repair_and_orders_the_current_successor() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    current_stage_flat = " ".join(current_stage.split())

    for invariant in (
        "Original terminal-goal grant — completed and sealed",
        "`3b6864c97f21a4991c10b8105a30c6239afae247`",
        "H1/H2/H3 operational-accounting repair is completed and sealed",
        "2. the current `ONLINE_INDEX_BASELINE_PUBLICATION_CONTINUITY_REARCHITECTURE`",
        "exact base `d6e506b343c6fc5570243ba01def46d6a047428e`",
    ):
        assert invariant in current_stage_flat


def test_delegation_separates_prepush_receipt_from_postpush_remote_equality() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    authority = " ".join((current_stage + "\n" + task).split())
    delivery_flat = " ".join(delivery.split())

    for invariant in (
        "pre-push independent exact-commit pass receipt",
        "intended bounded remote ref",
        "after the non-force push",
        "verified remote ref value equals the exact candidate commit",
        "post-push verified remote equality and run binding",
    ):
        assert invariant in authority
    for invariant in (
        "Before a non-force push",
        "pre-push independent exact-commit pass receipt",
        "intended bounded remote ref",
        "After the push",
        "verified remote ref value equals the exact commit",
        "Only the post-push binding",
    ):
        assert invariant in delivery_flat


def test_external_run_manifest_and_deadline_supervisor_are_exact_and_bounded() -> None:
    task = (ROOT / "tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md").read_text(encoding="utf-8")
    manifest = task.split("#### External run manifest", maxsplit=1)[1].split(
        "### `ONLINE_INDEX_BASELINE_PUBLICATION_CONTINUITY_REARCHITECTURE`",
        maxsplit=1,
    )[0]
    manifest_flat = " ".join(manifest.split())

    for key in (
        '"external_run_manifest_schema"',
        '"external_run_manifest_schema_version"',
        '"gate"',
        '"commit"',
        '"tree"',
        '"branch"',
        '"intended_remote_ref"',
        '"verified_remote_ref"',
        '"verified_remote_commit"',
        '"policy_path"',
        '"policy_digest"',
        '"evidence_directory"',
        '"startup_empty_proof"',
        '"argv"',
        '"cwd"',
        '"duration_ms"',
        '"supervisor_started_monotonic_ms"',
        '"deadline_monotonic_ms"',
        '"result_independent"',
        '"signal"',
        '"emergency_stop"',
        '"required_checks"',
        '"thresholds"',
    ):
        assert key in manifest
    for invariant in (
        "created and durably flushed before the production-public child starts",
        "exactly one `SIGINT`",
        "waits for the writer",
        "`SIGSTOP`",
        "`SIGCONT`",
        "`SIGKILL`",
        "must not inspect a witness, counter, threshold, or provisional verdict",
        "new manifest and new empty evidence directory",
        "Smoke and Soak durations are selected before startup",
        "a missing or unknown key makes the binding invalid",
    ):
        assert invariant in manifest_flat

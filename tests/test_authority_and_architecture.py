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
IMPLEMENTATION_CONTRACTS = (
    ROOT / "docs/contracts/SHORT_VOL_RADAR.md",
    ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md",
    ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
)
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


def test_current_stage_closes_outcome_prerequisite_without_runtime() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    flat = " ".join(current.split())
    marker = "**Sole authorized next product-capability closure:**"
    assert current.count(marker) == 1
    assert "`NONE` — no successor product-capability closure is active" in flat
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert "**Implemented runtime capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`" in current
    assert "**Production Short Vol Radar:** `ESTABLISHED`" in current
    assert "Shadow Outcome, rejected-counterfactual, aligned `NO_TRADE`" in flat
    assert "absence of a separately activated fixed-contract runtime" in flat
    assert "no downstream runtime or live command is authorized" in flat
    assert "SHORT_VOL_PUBLIC_SHADOW_TERMINAL_GOAL_DELEGATION" in current
    assert "## Queued sequence — not authorized" in current


def test_completed_outcome_contract_leaves_no_active_task() -> None:
    task = ROOT / "tasks/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT_CONTRACT.md"
    assert not task.exists()
    assert sorted(path.name for path in (ROOT / "tasks").glob("*.md")) == ["TEMPLATE.md"]
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    assert "SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT_CONTRACT" not in current


def test_underwriting_position_contract_freezes_public_economics_and_identity() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md")
    for invariant in (
        "**Status:** ACTIVE IMPLEMENTATION CONTRACT",
        "`CONTRACT_FROZEN_RUNTIME_NOT_IMPLEMENTED`",
        "Underwriting and Position are two separate immutable Policy artifacts",
        "There is no third admission Policy",
        '`fee_role = "TAKER"',
        "`fee_rate_index_fraction = 0.0003`",
        "public standard base-trading-fee upper bound",
        "`actual_all_in_max_loss_usdc` is always `null`",
        "contractual_payoff_max_loss_ex_fees_usdc",
        "entry_fee_reserved_payoff_loss_usdc",
        "underwriting_reserved_loss_usdc",
        "A Candidate has no arbitrary TTL and never revives",
    ):
        assert invariant in contract


def test_underwriting_position_contract_freezes_causality_and_admission() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md")
    for invariant in (
        "UnderwritingPositionSlotKey",
        "at most one Shadow Entry and open Position may arise",
        "Complete Candidate invalidation order",
        "`FAILED_ADMISSION_EVALUATION_CONSUMED`",
        "ScheduledAdmissionAttemptIdentity",
        "Candidate-scoped `PendingRpc`",
        "exact_request_params_including_depth_10000",
        "No second admission request is permitted",
        "SubscriptionAdmissionRefreshSourceIdentity",
        "RpcAdmissionRefreshSourceIdentity",
        "change_id` must equal the current accepted same-session combo-book market frontier",
        "The refreshed book may have economically identical levels",
        "Raw source identity, source timestamp, receipt identity, request id",
        "provenance only",
    ):
        assert invariant in contract


def test_underwriting_position_contract_freezes_position_and_hard_close_order() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(contract.split())
    ordered = (
        "`SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED`",
        "`LATEST_EXIT_BOUNDARY_REACHED`",
        "`PLATFORM_OR_SOURCE_DISCONTINUITY`",
        "`MAXIMUM_NET_LOSS_BOUNDARY_REACHED`",
        "`SHORT_LEG_RISK_BOUNDARY_REACHED`",
        "`PATH_OR_JUMP_RISK_BOUNDARY_REACHED`",
        "`VOLATILITY_STATE_BOUNDARY_REACHED`",
        "`LIQUIDITY_EXIT_BOUNDARY_REACHED`",
        "`ECONOMIC_EXIT_BOUNDARY_REACHED`",
    )
    section = contract.split("## Hard-close and close-reason total order", 1)[1]
    offsets = [section.index(value) for value in ordered]
    assert offsets == sorted(offsets)
    for invariant in (
        "CLOSE_LATCHED → CLOSE_LATCHED",
        "An unknown higher-priority predicate cannot erase a lower-priority known true predicate",
        "Position action and quote state are separate",
        "CloseQuoteEvaluationIdentity",
        "ScheduledPostCloseQuoteAttemptIdentity",
        "CloseOpportunityEvaluationIdentity",
        "Every quote evaluation on the first-CLOSE boundary remains `PRE_CLOSE`",
        "first-match total order",
        "A new official `change_id`, generation, request id, receipt",
    ):
        assert invariant in flat


def test_underwriting_position_contract_freezes_denominators_and_non_claims() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md")
    for invariant in (
        "Underwriting action rate",
        "admission-evaluable rate",
        "Position known-action rate",
        "close-opportunity rate while closing",
        "A zero or unknown denominator serializes rate `null`, never `0`",
        "No `SHADOW_ENTRY` means no Position, close opportunity, or Outcome object",
        "No current package implements this boundary",
        "This contract requires no live market command",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_identity_lifecycle_and_no_new_policy() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "**Status:** ACTIVE IMPLEMENTATION/EVALUATION CONTRACT",
        "`SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT`",
        "`RUNTIME_NOT_IMPLEMENTED`",
        "There is no Outcome Policy and no Cohort Policy",
        "No fourth strategy Policy exists",
        "OutcomeContractIdentity",
        "ShadowObservationIdentity",
        "PENDING → MATURE_KNOWN → MATURE_UNKNOWN",
        "CENSORED_AT_STOP",
        "CENSORED_AT_FAILURE",
        "every terminal state is immutable",
        "ShadowOutcomeIdentity",
    ):
        assert invariant in contract
    assert "TBD" not in contract


def test_outcome_contract_selects_first_eligible_exit_and_freezes_exact_economics() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "ShadowCounterfactualExitIdentity",
        "causal_order_first_ELIGIBLE_CloseOpportunityEvaluationIdentity",
        "The first qualifying identity in reducer causal order wins atomically",
        "hindsight cannot replace it",
        "`SHADOW_COUNTERFACTUAL_EXIT`",
        "gross_pnl_usdc",
        "gross_entry_credit_usdc + gross_close_cashflow_usdc",
        "total_public_fee_reserve_usdc",
        "entry_fee_reserve_usdc + close_fee_reserve_usdc",
        "net_pnl_after_public_standard_fee_reserve_usdc",
        "net_loss_usdc",
        "actual_pnl_usdc",
        "always `null` with availability `UNKNOWN`",
        "never cap, floor, replace, or clamp Outcome PnL or loss",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_unknown_maturity_without_settlement_payoff() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "consumes no delivery or settlement-price source",
        "never computes settlement payoff",
        "`ScheduledPostCloseQuoteAttemptIdentity` is already terminal",
        "`delivered` or `archivized`",
        "strictly later than Entry, first CLOSE",
        "`settlement`, `inactive`, `locked`, `halted`",
        "all exit, fee, PnL, loss, settlement cashflow",
        "`null / UNKNOWN`",
        "stop/failure-owned attempt terminal cannot manufacture `MATURE_UNKNOWN`",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_one_rejected_anchor_and_separate_path() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "RejectedCounterfactualAnchorIdentity",
        "causal_order_first_complete_EVALUABLE_WATCH_or_ABSTAIN",
        "at most one anchor",
        "not conditioned on cohort enrollment",
        "bytewise-ascending canonical `UnderwritingActionIdentity`",
        "availability `UNKNOWN`",
        "never create a rejected anchor",
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
        "REJECTED_COUNTERFACTUAL_EXIT",
        "RejectedCounterfactualOutcomeIdentity",
        "None may serialize Candidate",
        "Each slot can contribute at most one rejected observation",
    ):
        assert invariant in contract


def test_outcome_contract_aligns_no_trade_and_excludes_unknown_trade_arms() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "AlignedPolicyNoTradePairIdentity",
        "policy_arm = SHADOW_TRADE",
        "alternative_arm = NO_TRADE",
        "policy_arm = NO_TRADE",
        "alternative_arm = REJECTED_COUNTERFACTUAL_TRADE",
        "`NO_TRADE` cashflow is exactly zero USDC",
        "Both arms bind the same anchor",
        "one durable `ALIGNED_POLICY_NO_TRADE_PAIR`",
        "trade arm is `MATURE_KNOWN`",
        "both-arm comparison fields are `null / UNKNOWN`",
        "excluded from the aligned economic-comparison denominator",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_stop_manifest_and_result_independence() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "open the clean-stop barrier",
        "settle every application event already accepted",
        "commit one immutable clean-stop `FactBoundary`",
        "cannot reuse the last quote, mark, mid",
        "CENSORED_AT_FAILURE",
        "incomplete/invalid",
        "runtime_start_boundary",
        "enrollment_cutoff_boundary",
        "final_stop_boundary",
        "`start < cutoff < stop`",
        "`[start, cutoff)`",
        "`[cutoff, stop)`",
        "stop predicate cannot depend on anomaly, Candidate, Entry, rejection, Outcome",
        "Empty/zero natural activity is truthful evidence",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_objects_writer_readers_and_compatibility() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "SHADOW_OUTCOME_OBSERVATION",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
        "REJECTED_COUNTERFACTUAL_ANCHOR",
        "REJECTED_COUNTERFACTUAL_OUTCOME",
        "ALIGNED_POLICY_NO_TRADE_PAIR",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
        "only future pure downstream owner is `short_vol_underwriting`",
        "separate from Radar evidence",
        "identical duplicate is an idempotent no-op",
        "conflicting duplicate is a hard error",
        "mixed code/contract/Policy/runtime identities fail closed",
        "`NOT_COMPARABLE`",
        "No migration, replay, recomputation, backfill, relabeling",
    ):
        assert invariant in contract


def test_outcome_contract_freezes_conservation_denominators_and_nulls() -> None:
    contract = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    for invariant in (
        "ShadowEntry_count = shadow_pending_count",
        "RejectedCounterfactualAnchor_count = rejected_pending_count",
        "logical_aligned_pair_count = ShadowEntry_count",
        "enrolled_aligned_pair_count",
        "mature_known + mature_unknown",
        "mature-known units only",
        "trade arm is `MATURE_KNOWN`",
        "exact zero is neither win nor loss",
        "numeric zero Entry claim requires the known nonzero upstream",
        "numeric zero rejected-anchor claim requires a known nonzero",
        "zero or unknown denominator serializes every rate as `null`, never `0`",
    ):
        assert invariant in contract


def test_authority_defines_one_live_flow_and_two_frozen_downstream_contracts() -> None:
    constitution = _flat(ROOT / "docs/authority/PRODUCT_CONSTITUTION.md")
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    architecture = _flat(ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md")
    delivery = _flat(ROOT / "docs/authority/DELIVERY_CONTRACT.md")
    radar = _flat(ROOT / "docs/contracts/SHORT_VOL_RADAR.md")
    underwriting = _flat(ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md")
    outcome = _flat(ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md")
    readme = _flat(ROOT / "README.md")
    for invariant in (
        "Receiving a relevant public market event",
        "Without Shadow admission there is no Outcome object",
        "A missing quote cannot erase a known hard-close obligation",
    ):
        assert invariant in constitution
    for invariant in (
        "root blocker",
        "no downstream runtime or live command is authorized",
        "orders, fills, capital",
    ):
        assert invariant.lower() in current.lower()
    for invariant in (
        "There is no capture job followed by a scan job",
        "Contracted downstream Underwriting, Position, Outcome, and cohort boundary",
        "pure downstream owner named `short_vol_underwriting`",
        "No current package implements or consumes either boundary",
    ):
        assert invariant in architecture
    assert "Do not require full replay" in delivery
    assert "The Radar never returns `CANDIDATE`" in radar
    assert "No current package implements this boundary" in underwriting
    assert "No fourth strategy Policy exists" in outcome
    for invariant in (
        "SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT",
        "no successor product-capability task is active",
        "no Underwriting, Candidate, Shadow Entry, Position",
    ):
        assert invariant in readme


def test_radar_contract_keeps_market_signal_execution_and_decision_distinct() -> None:
    radar = _flat(ROOT / "docs/contracts/SHORT_VOL_RADAR.md")
    for invariant in (
        "Market Monitor",
        "Detector evaluation",
        "Anomaly episode",
        "Public atomic availability",
        "Future maker/order state",
        "The Radar never returns `CANDIDATE`, `WATCH`, `ABSTAIN`, `HOLD`, or `CLOSE`.",
        "Two component-leg orders are not an atomic substitute at any layer.",
        "No Layer 2 result changes Layer 1.",
        "This closure stops at `SHORT_VOL_ANOMALY_EVENT` plus optional",
        "Neither entry kind has a planned holding duration.",
        "never let a missing quote override a known hard-close condition",
        "emit `SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE`",
    ):
        assert invariant in radar


def test_at_most_one_active_task_and_it_declares_every_change_axis() -> None:
    paths = tuple(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md")
    assert len(paths) <= 1
    active = tuple(
        path
        for path in paths
        if "**Status:** ACTIVE"
        in "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
    )
    assert len(active) <= 1
    assert all(
        "**Status:** COMPLETE" not in path.read_text(encoding="utf-8") for path in paths
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
            assert declaration in text


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
        assert forbidden.search(path.relative_to(ROOT).as_posix()) is None
        assert forbidden.search(text) is None, f"ordinal identity remains in {path}"
        if path.suffix == ".py" and (
            ROOT / "apps" in path.parents or ROOT / "packages" in path.parents
        ):
            assert '"version":' not in text


def test_index_publication_contract_owns_current_projection_and_actual_sealed_vocabulary() -> None:
    radar = _flat(ROOT / "docs/contracts/SHORT_VOL_RADAR.md")
    for invariant in (
        "`IndexTailStatus` and `IndexBaselineState.status` remain current production Python",
        "`INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name",
        "never serialized by the current or sealed evidence writers",
        "`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING`",
        "`SOAK_PENDING_REASONS`",
        "Normal index publication pending is not a suspension or detector state",
        "current-schema writer and validator path accept only version 6",
        "Explicit read-only validators continue to validate sealed version-5",
        "implementation-surface consolidation may not change the current version-6 writer/reader",
        "same-tail/same-target latch",
    ):
        assert invariant in radar
    assert "Pending statuses preserve episode identity" not in radar


def test_stage_record_binds_both_independent_live_gates() -> None:
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    for invariant in (
        "candidate commit `9c58120d358fd0e0ccb4885123ab95c67d1c3f31`",
        "candidate tree `1ff49ff697df1a91237eb35f290301e26a7c06dc`",
        "refs/heads/codex/radar-repository-consolidation",
        "does not prove indefinite uptime",
        "changes no accepted Radar runtime or live evidence identity",
        "4bbf832ab7340e7224a0df5db79aea1cd6fed33d156f2aeec12690f986217a4f",
        "d38c5bebef1e2bccfeeb9c69715970d03fda2a0359f02520a5c3deef08463345",
        "700dbbf2649830b656a75de3e3eb74aabef21cb4003786429b823091abcbbfa6",
        "1ec01c5dba427e3a273671ef57421a6f6bfe01f95d26416e35a2d69fe6a6b218",
    ):
        assert invariant in current


def test_delegation_separates_prepush_receipt_from_postpush_remote_equality() -> None:
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    delivery = _flat(ROOT / "docs/authority/DELIVERY_CONTRACT.md")
    assert "both live manifests' pre-run verified remote ref" in current
    assert "resolved to that exact candidate commit" in current
    for invariant in (
        "Before a non-force push",
        "pre-push independent exact-commit pass receipt",
        "intended bounded remote ref",
        "After the push",
        "verified remote ref value equals the exact commit",
        "Only the post-push binding",
    ):
        assert invariant in delivery

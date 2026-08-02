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


def _text_block_after(text: str, marker: str) -> str:
    tail = text.split(marker, 1)[1]
    return tail.split("```text\n", 1)[1].split("\n```", 1)[0]


def _text_block_after_last(text: str, marker: str) -> str:
    tail = text.rsplit(marker, 1)[1]
    return tail.split("```text\n", 1)[1].split("\n```", 1)[0]


def _declared_keys(block: str) -> tuple[str, ...]:
    return tuple(
        line.strip().split(":", 1)[0]
        for line in block.splitlines()
        if line.strip() and line.strip() not in {"{", "}"} and ":" in line
    )


def _table_rows_after(text: str, marker: str) -> tuple[tuple[str, ...], ...]:
    tail = text.split(marker, 1)[1]
    rows: list[tuple[str, ...]] = []
    for line in tail.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
            rows.append(cells)
    return tuple(rows)


def _canonical_identity(label: str, *members: object) -> str:
    preimage = json.dumps(
        [label, *members],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(preimage).hexdigest()}"


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


def test_current_stage_authorizes_one_runtime_simplification() -> None:
    current = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    flat = " ".join(current.split())
    marker = "**Sole authorized closure:**"

    assert current.count(marker) == 1
    assert f"{marker} `SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`" in flat
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current
    assert "**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_REVALIDATION`" in current
    assert "**Persistent service:** `STOPPED_NO_DEPLOYMENT`" in current
    assert "**Live commands:** `FORBIDDEN`" in current
    assert "rejected its Radar results as unreliable" in flat
    assert "Deleted history is not a business premise" in flat
    assert "removes the obsolete macOS commissioning controller" in flat
    assert "service lifecycle evidence/terminal-manifest system" in flat
    for stale_claim in (
        "R4_COMMISSIONED",
        "R4_COMMISSIONED_24H_OBSERVATION_ACTIVE",
        "R4_COMMISSIONED_24H_PENDING",
        "CONSUMED_FAILED_NO_RETRY",
        "engineering_end_to_end = PASS",
        "production_public_integration = PASS",
    ):
        assert stale_claim not in current


def test_runtime_simplification_is_exactly_authorized() -> None:
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    task_path = ROOT / "tasks/SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION.md"
    task = task_path.read_text(encoding="utf-8")
    task_flat = " ".join(task.split())

    assert (
        "**Sole authorized closure:** `SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`"
    ) in current
    for exact in (
        "**Status:** ACTIVE",
        "**Task kind:** IMPLEMENTATION",
        "**Runtime implementation:** REQUIRED",
        "**Live commands:** FORBIDDEN",
        "**Market/Decision input contract change:** NONE",
        "**Decision Policy change:** NONE",
        "**Outcome/evaluation contract change:** NONE",
        "**Stage/authorization change:** APPROVED",
        "macOS commissioning controller",
        "service lifecycle evidence ledger",
        "minimal business writers",
        "`serve-shadow` owns one process",
        "service-manifest",
        "commissioning, `launchd`, `lsof`, unified-log, probe",
        "radar_runtime.service",
        "radar_runtime.workbench",
        "Direct behavior | REQUIRED",
        "Production-public Radar | NOT_APPLICABLE",
    ):
        assert exact in task_flat, exact
    assert "Decision Policy change:** NONE" in task_flat


def test_only_runtime_simplification_task_is_active() -> None:
    assert sorted(path.name for path in (ROOT / "tasks").glob("*.md")) == [
        "SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION.md",
        "TEMPLATE.md",
    ]
    current = _flat(ROOT / "docs/authority/CURRENT_STAGE.md")
    assert (
        "**Sole authorized closure:** `SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`"
    ) in current
    assert "**Live commands:** `FORBIDDEN`" in current


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
        "sha256:b9733ad0c90837338b88fb5b6eb66ad8eed448cce6372a3f527988395087b3fe",
        "sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03",
        "sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695",
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

    radar_contract = ROOT / "docs/contracts/SHORT_VOL_RADAR.md"
    underwriting_contract = ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md"
    outcome_contract = ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md"
    assert hashlib.sha256(radar_contract.read_bytes()).hexdigest() == (
        declared_contract_digests[0].removeprefix("sha256:")
    )
    assert hashlib.sha256(underwriting_contract.read_bytes()).hexdigest() == (
        declared_contract_digests[1].removeprefix("sha256:")
    )
    assert hashlib.sha256(outcome_contract.read_bytes()).hexdigest() == (
        declared_contract_digests[2].removeprefix("sha256:")
    )


def test_underwriting_position_contract_freezes_public_economics_and_identity() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(contract.split())

    assert "**Status:** ACTIVE IMPLEMENTATION CONTRACT" in contract
    assert "**Current implementation state:** `CONTRACT_FROZEN_RUNTIME_NOT_IMPLEMENTED`" in contract
    assert "TBD" not in contract
    assert "`combo_book_currentness_budget_ms`" not in contract
    assert "`catalog_currentness_budget_ms`" not in contract
    for invariant in (
        'Policy identity = "sha256:" + lowercase_sha256_of_exact_file_bytes',
        "Underwriting and Position are two separate immutable Policy artifacts",
        "There is no third admission Policy",
        '`fee_role = "TAKER"',
        "`fee_rate_index_fraction = 0.0003`",
        "`combo_snapshot_send_budget_ms`",
        "`combo_snapshot_response_budget_ms`",
        "`fee_schedule_effective_label`",
        "buy_leg_standard_fee_usdc <= 0.0003 × index × q",  # noqa: RUF001
        "combo_standard_base_fee_usdc = max(buy_leg_standard_fee_usdc, "
        "sell_leg_standard_fee_usdc) <= 0.0003 × index × q",  # noqa: RUF001
        "public standard base-trading-fee upper bound",
        "`taker_commission <= 0.0003`",
        "entry_fee_reserve_usdc",
        "net_entry_credit_usdc",
        "contractual_payoff_max_loss_ex_fees_usdc",
        "entry_fee_reserved_payoff_loss_usdc",
        "underwriting_reserved_loss_usdc",
        "`actual_all_in_max_loss_usdc` is always `null`",
        "never `actual_fee`",
        "A Candidate has no arbitrary TTL and never revives",
        "`ADMITTED` and `INVALIDATED` are terminal",
        "Candidate-scoped",
        "`public/get_order_book` request",
        "later source identities with the same fingerprint cannot repeat it",
    ):
        assert invariant in flat

    key_blocks = re.findall(
        r"The exact top-level key set is:\n\n```text\n(.*?)\n```",
        contract,
        flags=re.DOTALL,
    )
    assert len(key_blocks) == 2
    assert tuple(key_blocks[0].splitlines()) == (
        "policy_semantic_name",
        "radar_policy_identity",
        "target_base_quantity_btc",
        "clock_currentness_budget_ms",
        "platform_currentness_budget_ms",
        "combo_snapshot_send_budget_ms",
        "combo_snapshot_response_budget_ms",
        "index_currentness_budget_ms",
        "option_ticker_currentness_budget_ms",
        "fee_role",
        "fee_schedule_source_url",
        "fee_schedule_retrieved_at_utc",
        "fee_schedule_effective_label",
        "fee_rate_index_fraction",
        "path_risk_reserve_usdc",
        "jump_risk_reserve_usdc",
        "tail_risk_reserve_usdc",
        "liquidity_cost_reserve_usdc",
        "uncertainty_reserve_usdc",
        "settlement_cost_reserve_usdc",
        "maximum_underwriting_reserved_loss_usdc",
        "minimum_net_entry_credit_usdc",
        "minimum_net_credit_to_payoff_cap_fraction",
        "maximum_entry_consumed_level_count",
    )
    assert tuple(key_blocks[1].splitlines()) == (
        "policy_semantic_name",
        "underwriting_policy_identity",
        "target_base_quantity_btc",
        "clock_currentness_budget_ms",
        "platform_currentness_budget_ms",
        "combo_snapshot_send_budget_ms",
        "combo_snapshot_response_budget_ms",
        "index_currentness_budget_ms",
        "option_ticker_currentness_budget_ms",
        "fee_role",
        "fee_schedule_source_url",
        "fee_schedule_retrieved_at_utc",
        "fee_schedule_effective_label",
        "fee_rate_index_fraction",
        "latest_exit_lead_ms",
        "maximum_projected_net_loss_usdc",
        "maximum_absolute_short_delta",
        "maximum_absolute_index_return_since_entry_fraction",
        "maximum_absolute_index_return_since_prior_evaluation_fraction",
        "maximum_short_mark_iv_increase_fraction",
        "maximum_close_consumed_level_count",
        "minimum_take_profit_usdc",
        "maximum_remaining_premium_fraction",
    )


def test_underwriting_position_contract_freezes_causality_and_admission() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(contract.split())

    for invariant in (
        "code_identity × runtime_identity × session_epoch × ingress_seq",  # noqa: RUF001
        "Source timestamps describe the exchange fact but do not replace local known-at order",
        "`NOT_EVALUATED`",
        "`UNKNOWN`",
        "exactly one of `CANDIDATE | WATCH | ABSTAIN`",
        "UnderwritingAvailabilityEvaluationIdentity",
        "consumed_availability_fact_fingerprint",
        "An availability identity is created only when that normalized fingerprint or resulting "
        "availability changes",
        "UnderwritingActionIdentity",
        "UnderwritingPositionSlotKey",
        "at most one Shadow Entry and open Position may arise",
        "candidate_activation_FactBoundary",
        "`RUNTIME_OR_CODE_IDENTITY_CHANGED`",
        "`RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED`",
        "`CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED`",
        "`REUNDERWRITING_NO_LONGER_CANDIDATE`",
        "`FAILED_ADMISSION_EVALUATION_CONSUMED`",
        "SubscriptionAdmissionRefreshSourceIdentity",
        "RpcAdmissionRefreshSourceIdentity",
        "ScheduledAdmissionAttemptIdentity",
        "Candidate-scoped `PendingRpc`",
        "request_SENT_FactBoundary",
        "all before/after claims use same-runtime `FactBoundary.causal_seq`",
        "The refreshed book may have economically identical levels",
        "Raw source identity, source timestamp, receipt identity, request id, subscription "
        "generation, and official `change_id` are immutable provenance only",
        "A source update that preserves every normalized business fact neither creates another "
        "evaluation or Candidate nor invalidates the existing Candidate",
        "exact_request_params_including_depth_10000",
        "change_id` must equal the current accepted same-session combo-book market frontier",
        "No second admission request is permitted",
        "`ORPHAN_LATE_WIRE` and cannot consume the Candidate's own pending attempt",
        "Candidate-time projection",
        "component legs, mark, or mid cannot refresh admission",
        "After `SHADOW_ENTRY`, the Shadow Position lifecycle is independent",
        "Radar Layer 2 stopping cannot stop Position observation",
    ):
        assert invariant in flat
    assert "source event began after Candidate activation" not in contract
    assert "Last-mutation age is diagnostic only and never expires the book" in contract
    assert (
        "| no active Radar episode; the episode/short-leg slot is already consumed by Entry; "
        "complete current scope proves "
        "`NO_ACTIVE_COMBO` / `NO_TARGET_SIZE_CREDIT_QUOTE`;"
    ) in contract
    assert (
        "| an active episode exists but atomic availability is `UNKNOWN`, or any required public "
        "fact is missing, stale, incomplete, malformed, gapped, contradictory, or contaminated"
    ) in contract


def test_underwriting_position_contract_freezes_position_and_hard_close_order() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(contract.split())
    ordered_reasons = (
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
    reason_section = contract.split("## Hard-close and close-reason total order", 1)[1].split(
        "The predicate truth rules are exact:", 1
    )[0]
    offsets = [reason_section.index(reason) for reason in ordered_reasons]
    assert offsets == sorted(offsets)

    for invariant in (
        "ENTRY_BOUNDARY → PENDING_STRICTLY_FUTURE_FACT",
        "CLOSE_LATCHED → CLOSE_LATCHED",
        "if lifecycle is already `CLOSE_LATCHED`, serialized action remains `CLOSE`",
        "An unknown higher-priority predicate cannot erase a lower-priority known true predicate",
        "`trusted_time.upper_ms >= expiry_ms - 1800000`",
        "`index >= short_strike` for a short call",
        "`index <= short_strike` for a short put",
        "`abs(current_index - entry_index) >= entry_return_limit × entry_index`",  # noqa: RUF001
        "PositionEvaluationIdentity",
        "PositionActionIdentity",
        "CloseQuoteEvaluationIdentity",
        "CloseOpportunityEvaluationIdentity",
        "ScheduledPostCloseQuoteAttemptIdentity",
        "The entry index is the initial `prior_evaluation_index`",
        "An evaluation with index `UNKNOWN` does not advance the anchor",
        "Position action and quote state are separate",
        "`ATOMIC_COMBO_CLOSE_QUOTE`",
        "`LEGGED_CLOSE_REFERENCE`",
        "`UNEXECUTABLE` or `LEGGED_CLOSE_REFERENCE`",
        "`UNEXECUTABLE`",
        "full remaining `q`",
        "Every quote evaluation on the first-CLOSE boundary remains `PRE_CLOSE`",
        "That one conditioning transition permits verification of a quiet book even when the "
        "normalized business fingerprint is unchanged",
        "The opportunity fingerprint consumes only facts through the first matched eligibility "
        "rule",
        "commission and index are ignored",
        "index is ignored and fee/net economics remain `null / UNKNOWN`",
        "A new official `change_id`, generation, request id, receipt, or equal-value repeated tick "
        "alone cannot",
        "`NOT_REQUESTABLE_UNKNOWN`",
        "quiet market still invalidates a Candidate at admission cutoff",
    ):
        assert invariant in flat

    for lifecycle_row in (
        "| `open` | trusted-time rule below | false when every other required source is continuous |",
        "| `settlement` | `TRUE` | false unless another discontinuity exists |",
        "| `delivered` | `TRUE` | false unless another discontinuity exists |",
        "| `archivized` | `TRUE` | false unless another discontinuity exists |",
        "| `inactive` | trusted-time rule below | `TRUE` |",
        "| `locked` | trusted-time rule below | `TRUE` |",
        "| `halted` | trusted-time rule below | `TRUE` |",
    ):
        assert lifecycle_row in contract

    classifier = contract.split("The classifier applies this first-match total order:", 1)[1].split(
        "`LEGGED_CLOSE_REFERENCE` cannot", 1
    )[0]
    classifier_states = (
        "`UNEXECUTABLE`",
        "`LEGGED_CLOSE_REFERENCE`",
        "`UNEXECUTABLE`",
        "`UNKNOWN`",
        "`ATOMIC_COMBO_CLOSE_QUOTE`",
        "`UNEXECUTABLE`",
    )
    offsets = []
    start = 0
    for state in classifier_states:
        offset = classifier.index(state, start)
        offsets.append(offset)
        start = offset + len(state)
    assert offsets == sorted(offsets)
    assert "A bounded REST response that does not cover `q` is also `UNKNOWN`" in flat


def test_underwriting_position_contract_freezes_denominators_and_non_claims() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(contract.split())

    for invariant in (
        "Underwriting action rate",
        "Candidate activation rate",
        "admission-evaluable rate",
        "Shadow Entry rate",
        "Position known-action rate",
        "close-quote known-state rate",
        "close-opportunity rate while closing",
        "A zero or unknown denominator serializes rate `null`, never `0`",
        "No `SHADOW_ENTRY` means no Position, close opportunity, or Outcome object",
        "Position `UNKNOWN` is a serialized decision-availability result",
        "every `PositionActionIdentity` whose action is `HOLD` or `CLOSE`",
        "`CloseOpportunityEvaluationIdentity` values with eligibility `ELIGIBLE + INELIGIBLE`",
        "all-`UNKNOWN` economics therefore serialize `null`, never zero",
        "No current package implements this boundary",
        "This contract requires no live market command",
        "public-quote-not-fill",
    ):
        assert invariant in flat


def test_outcome_contract_freezes_identity_lifecycle_and_no_new_policy() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )

    assert "**Status:** ACTIVE IMPLEMENTATION/EVALUATION CONTRACT" in contract
    assert (
        "**Owning semantic identity:** `SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT`" in contract
    )
    assert "**Current implementation state:** `RUNTIME_NOT_IMPLEMENTED`" in contract
    assert (
        "There is no Outcome Policy and no Cohort Policy. No fourth strategy Policy exists."
        in contract
    )
    assert _text_block_after(
        contract, "The initial lifecycle is `PENDING`. Its state machine is exactly:"
    ).splitlines() == [
        "PENDING → MATURE_KNOWN",
        "PENDING → MATURE_UNKNOWN",
        "PENDING → CENSORED_AT_STOP",
        "PENDING → CENSORED_AT_FAILURE",
    ]
    assert "These are four alternative branches, never a serial chain." in contract
    assert "Every terminal state is immutable" in contract
    assert "ShadowObservationIdentity =" in contract
    assert "ShadowOutcomeIdentity =" in contract
    canonical = _text_block_after(
        contract,
        "Every new identity equation in this contract uses one exact typed encoding.",
    )
    assert '"sha256:"' in canonical
    assert "lowercase_sha256(" in canonical
    assert "JSON_array(" in canonical
    assert 'separators = [",", ":"]' in canonical
    assert "no_BOM = true" in canonical
    assert "No object or array is first serialized into a JSON string" in contract
    assert "embedded as its native\n`CanonicalValue`" in contract
    assert '{"instrument_name": Identity, "depth": 10000}' in contract
    assert "request params is native JSON `null`" in contract
    fixed_vectors = _text_block_after(contract, "The normative fixed vectors are:")
    assert fixed_vectors == (
        '["FooIdentity","member_1","member_2"]\n'
        "→ sha256:961665d18281a3f4d46b0e72f1d05c494d73d11a9f829def2f4509e09e76bf3a\n"
        "\n"
        '["CompositeIdentity",{"code_identity":"code","runtime_identity":"runtime",'
        '"session_epoch":1,"ingress_seq":2,"received_monotonic_ms":3,"causal_seq":4},'
        '["TRUE","UNKNOWN"],{"instrument_name":"combo","depth":10000},7,null]\n'
        "→ sha256:2a6013410106bda9c407cb910982744c77f406384beb93f17b917464639e05ff\n"
        "\n"
        '["UnderwritingPositionSlotKeyIdentity","runtime","radar-policy","episode",'
        '"short-leg","0.1"]\n'
        "→ sha256:3d9a604d72459c3f0353f0a623c7f1f014ec0a24ff38a79975dd272f73e0a8dc"
    )
    fact_boundary = {
        "code_identity": "code",
        "runtime_identity": "runtime",
        "session_epoch": 1,
        "ingress_seq": 2,
        "received_monotonic_ms": 3,
        "causal_seq": 4,
    }
    assert _canonical_identity("FooIdentity", "member_1", "member_2") == (
        "sha256:961665d18281a3f4d46b0e72f1d05c494d73d11a9f829def2f4509e09e76bf3a"
    )
    assert (
        _canonical_identity(
            "CompositeIdentity",
            fact_boundary,
            ["TRUE", "UNKNOWN"],
            {"instrument_name": "combo", "depth": 10000},
            7,
            None,
        )
        == "sha256:2a6013410106bda9c407cb910982744c77f406384beb93f17b917464639e05ff"
    )
    assert (
        _canonical_identity(
            "UnderwritingPositionSlotKeyIdentity",
            "runtime",
            "radar-policy",
            "episode",
            "short-leg",
            "0.1",
        )
        == "sha256:3d9a604d72459c3f0353f0a623c7f1f014ec0a24ff38a79975dd272f73e0a8dc"
    )
    assert "No native tuple,\narray, object, or alternative slot-key hash is accepted" in contract
    assert 'CanonicalIdentity("FooIdentity", member_1, member_2)' in contract
    rejected_observation = _text_block_after(
        contract, "Each selected rejected anchor creates exactly one:"
    )
    assert rejected_observation == (
        "RejectedCounterfactualObservationIdentity =\n"
        "    RejectedCounterfactualAnchorIdentity\n"
        "    × REJECTED_COUNTERFACTUAL_OBSERVATION"  # noqa: RUF001
    )
    assert "EXACT_KEYS_AND_TYPES_DECLARED_IN_THIS_CONTRACT" not in contract
    assert "TBD" not in contract


def test_outcome_contract_selects_first_eligible_exit_and_freezes_exact_economics() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )

    assert _text_block_after(contract, "Selection is exactly once and causal:") == (
        "ShadowCounterfactualExitIdentity =\n"
        "    ShadowObservationIdentity\n"
        "    × first_latched_CLOSE_action_identity\n"  # noqa: RUF001
        "    × causal_order_first_ELIGIBLE_CloseOpportunityEvaluationIdentity"  # noqa: RUF001
    )
    economics = _text_block_after(contract, "equations are normative:")
    assert (
        "gross_pnl_usdc =\n    gross_entry_credit_usdc\n    + gross_close_cashflow_usdc"
        in economics
    )
    assert (
        "total_public_fee_reserve_usdc =\n    entry_fee_reserve_usdc\n    + close_fee_reserve_usdc"
    ) in economics
    assert (
        "net_pnl_after_public_standard_fee_reserve_usdc =\n"
        "    gross_pnl_usdc\n"
        "    - total_public_fee_reserve_usdc"
    ) in economics
    assert (
        "net_loss_usdc =\n    max(0, -net_pnl_after_public_standard_fee_reserve_usdc)" in economics
    )
    assert "first qualifying identity in reducer causal order wins atomically" in contract
    assert "hindsight cannot replace it" in contract
    assert "exactly the same full `q`" in contract
    assert "never cap, floor, replace, or clamp Outcome PnL or loss" in contract


def test_outcome_contract_freezes_unknown_maturity_without_settlement_payoff() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    traces = _text_block_after(contract, "The required boundary traces are:")

    assert traces.split("\n\n") == [
        "first_CLOSE < B; eligible_exit = B; ordinary_attempt_terminal <= B;\n"
        "natural_lifecycle_ready = B\n"
        "    → MATURE_KNOWN",
        "first_CLOSE < B; no_eligible_exit; ordinary_attempt_terminal = B;\n"
        "natural_lifecycle_ready = B\n"
        "    → MATURE_UNKNOWN",
        "first_CLOSE < B; no_eligible_exit; attempt_terminal_owner = STOP | FAILURE;\n"
        "natural_lifecycle_ready = B\n"
        "    → CENSORED_AT_STOP | CENSORED_AT_FAILURE",
        "first_CLOSE < ordinary_attempt_terminal < B; no_eligible_exit;\n"
        "natural_lifecycle_not_ready = B; terminal_source = STOP | FAILURE\n"
        "    → CENSORED_AT_STOP | CENSORED_AT_FAILURE; retain ORDINARY attempt terminal",
    ]
    total_order = contract.split(
        "At every settled boundary `B`, the reducer applies this exact terminal total order:", 1
    )[1].split("The natural-terminal predicate at `B`", 1)[0]
    assert total_order.index("select its causal-order first eligible exit") < total_order.index(
        "evaluate the natural-terminal predicate"
    )
    assert "`causal_seq < B.causal_seq`" in contract
    assert "`causal_seq <= B.causal_seq`" in contract
    assert "`first_CLOSE = B` never satisfies the natural-terminal predicate" in contract
    assert "at an\nordinary boundary with no exit it remains `PENDING`" in contract
    assert "consumes no delivery or settlement-price source" in contract
    assert "never computes settlement payoff" in contract
    assert "`settlement`, `inactive`, `locked`, `halted`" in contract
    assert "stop/failure-owned attempt terminal cannot manufacture `MATURE_UNKNOWN`" in contract


def test_outcome_contract_freezes_one_rejected_anchor_and_separate_path() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    identities = _text_block_after(contract, "The rejected identity family is exact:")

    for identity in (
        "RejectedCounterfactualPositionEvaluationIdentity",
        "RejectedCounterfactualPositionActionIdentity",
        "RejectedScheduledPostCloseQuoteAttemptIdentity",
        "RejectedPostCloseAttemptTerminalIdentity",
        "RejectedCounterfactualCloseQuoteEvaluationIdentity",
        "RejectedCounterfactualCloseOpportunityEvaluationIdentity",
        "RejectedCounterfactualExitIdentity",
        "RejectedCounterfactualOutcomeIdentity",
    ):
        assert identities.count(f"{identity} =") == 1
    assert (
        "causal_order_first_ELIGIBLE_RejectedCounterfactualCloseOpportunityEvaluationIdentity"
    ) in identities
    assert "creates exactly one" in contract
    assert "created at the rejected anchor boundary" in contract
    assert "strictly greater same-runtime `causal_seq`" in contract
    assert (
        "early rejected close-quote or opportunity evaluation whose state is `UNKNOWN` or `INELIGIBLE`"
        in contract
    )
    assert "does not consume the observation and is not an exit" in contract
    assert "later Candidate or `SHADOW_ENTRY` in the same slot coexists" in contract
    assert "neither identity cancels, merges, replaces, or consumes the other" in contract
    assert "not conditioned on cohort enrollment" in contract
    assert "bytewise-ascending canonical `UnderwritingActionIdentity`" in contract


def test_outcome_contract_aligns_no_trade_and_excludes_unknown_trade_arms() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    pair_identity = _text_block_after(contract, "The identity is:")

    assert pair_identity == (
        "AlignedPolicyNoTradePairIdentity =\n"
        "    OutcomeContractIdentity\n"
        "    × pair_anchor\n"  # noqa: RUF001
        "    × exact_policy_arm\n"  # noqa: RUF001
        "    × exact_alternative_arm"  # noqa: RUF001
    )
    assert "policy_arm = SHADOW_TRADE\nalternative_arm = NO_TRADE" in contract
    assert "policy_arm = NO_TRADE\nalternative_arm = REJECTED_COUNTERFACTUAL_TRADE" in contract
    assert "`NO_TRADE` cashflow is exactly zero USDC" in contract
    assert "one durable `ALIGNED_POLICY_NO_TRADE_PAIR`" in contract
    assert "Economic comparison is available only when the trade arm is `MATURE_KNOWN`" in contract
    assert "both-arm comparison fields are `null / UNKNOWN`" in contract
    assert "known zero `NO_TRADE` arm cannot\nmake an unknown trade arm comparable" in contract


def test_outcome_contract_freezes_stop_manifest_and_result_independence() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    trigger = _text_block_after(contract, "They are exact\npre-start supervisor triggers:")
    emergency = _text_block_after(
        contract, "An authorized early stop is a distinct external supervisor control:"
    )
    fatal = _text_block_after(contract, "A fatal failure uses a distinct supervisor control:")
    manifest_schema = _text_block_after(contract, "The manifest exact top-level schema is:")
    realized = _text_block_after(contract, "The summary records one exact realized boundary set:")
    summary_schema = _text_block_after_last(contract, "`SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY`:")
    terminal_rows = _table_rows_after(contract, "| Terminal source | Exact disposition")

    assert _declared_keys(trigger) == (
        '"runtime_identity"',
        '"supervisor_clock_identity"',
        '"trigger_monotonic_ms"',
        '"trigger_kind"',
    )
    assert _declared_keys(emergency) == (
        '"runtime_identity"',
        '"supervisor_clock_identity"',
        '"authority_identity"',
        '"control_monotonic_ms"',
        '"control_kind"',
        '"reason"',
    )
    assert _declared_keys(fatal) == (
        '"runtime_identity"',
        '"supervisor_clock_identity"',
        '"failure_source_identity"',
        '"control_monotonic_ms"',
        '"control_kind"',
        '"failure_kind"',
    )
    assert "PreboundSupervisorTriggerIdentity =" in trigger
    assert "AuthorizedEmergencyStopControlIdentity =" in emergency
    assert "FatalFailureControlIdentity =" in fatal
    assert '"PreboundSupervisorTriggerIdentity"' in trigger
    assert '"AuthorizedEmergencyStopControlIdentity"' in emergency
    assert '"FatalFailureControlIdentity"' in fatal
    assert _declared_keys(manifest_schema) == (
        "manifest_content_schema_identity",
        "candidate_commit",
        "candidate_tree",
        "intended_remote_ref",
        "verified_remote_ref",
        "outcome_contract_identity",
        "outcome_contract_path",
        "radar_policy_path",
        "radar_policy_identity",
        "underwriting_policy_path",
        "underwriting_policy_identity",
        "position_policy_path",
        "position_policy_identity",
        "evidence_directory",
        "process_argv",
        "process_cwd",
        "required_pre_run_checks",
        "runtime_start_trigger",
        "enrollment_cutoff_trigger",
        "final_stop_trigger",
        "clean_stop_predicate",
        "emergency_stop_authority",
        "forbidden_capabilities",
        "non_claims",
    )
    assert tuple(realized.splitlines()) == (
        "runtime_start_fact_boundary: FactBoundary",
        "enrollment_end_fact_boundary: FactBoundary",
        'enrollment_end_reason: "PREBOUND_CUTOFF" | "TERMINAL_BEFORE_CUTOFF"',
        "terminal_fact_boundary: FactBoundary",
        'terminal_disposition: "PLANNED_CLEAN_STOP" | "AUTHORIZED_EMERGENCY_STOP" |',
        '                      "PROCESS_FAILURE"',
        "planned_final_stop_fact_boundary: FactBoundary | null",
    )
    assert tuple(realized.splitlines()) == tuple(summary_schema.splitlines()[2:9])
    assert (
        "`runtime_start_fact_boundary.causal_seq < anchor.causal_seq <\n"
        "enrollment_end_fact_boundary.causal_seq`"
    ) in contract
    assert (
        "`enrollment_end_fact_boundary.causal_seq < fact.causal_seq <\n"
        "terminal_fact_boundary.causal_seq`"
    ) in contract
    assert terminal_rows == (
        (
            "fatal runtime or evidence-integrity failure",
            "`PROCESS_FAILURE`",
            "`FAILURE`",
            "`null`",
            "`FatalFailureControl`",
        ),
        (
            "valid `AuthorizedEmergencyStopControl` and no fatal failure at that boundary",
            "`AUTHORIZED_EMERGENCY_STOP`",
            "`STOP`",
            "`null`",
            "`AuthorizedEmergencyStopControl`",
        ),
        (
            "pre-bound final-stop trigger and neither earlier owner",
            "`PLANNED_CLEAN_STOP`",
            "`STOP`",
            "required and equal to terminal boundary",
            "manifest `final_stop_trigger`",
        ),
    )
    assert "emergency stop or failure commits before cutoff" in contract
    assert "No missing future boundary is fabricated" in contract
    assert "TERMINAL_FAILURE" not in contract
    assert "terminal_reason:" not in contract
    assert "`PLANNED_CLEAN_STOP | AUTHORIZED_EMERGENCY_STOP` own `CENSORED_AT_STOP`" in contract
    assert "`PROCESS_FAILURE` owns `CENSORED_AT_FAILURE`" in contract
    assert "fatal runtime or evidence-integrity error is never relabelled" in " ".join(
        contract.split()
    )
    assert "exact_file_bytes_including_the_trailing_LF" in contract
    assert "Pretty printing, key sorting, CRLF" in contract
    assert "bytewise-ascending UTF-8 Identity bytes" in contract
    assert "`candidate_commit = verified_remote_ref = every envelope.code_identity`" in contract
    assert "`candidate_tree = GitTree(candidate_commit)`" in contract
    assert "recomputes every declared path's exact-byte digest" in contract
    assert "every envelope and every `FactBoundary`" in contract
    assert "fresh remote resolution is a process-start preflight gate only" in contract
    assert "never resolves or depends on current remote state" in " ".join(contract.split())
    manifest_vector = (
        json.dumps(
            {"kind": "组合", "values": ["\u03b1", 1, None]},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert manifest_vector == '{"kind":"组合","values":["\u03b1",1,null]}\n'.encode()
    assert hashlib.sha256(manifest_vector).hexdigest() == (
        "8467e20e8dd44a9849ac4b63dd33d086f4fb7cedc027d663c16f70e3ed4b68f9"
    )
    assert hashlib.sha256(manifest_vector[:-1]).hexdigest() != (
        "8467e20e8dd44a9849ac4b63dd33d086f4fb7cedc027d663c16f70e3ed4b68f9"
    )
    assert "The LF is one byte\n`0a`" in contract
    assert "open the clean-stop barrier" in contract
    assert "settle every application event already accepted" in contract
    assert "commit one immutable clean-stop `FactBoundary`" in contract
    assert "cannot reuse the last quote, mark, mid" in contract
    assert (
        "stop predicate cannot depend on anomaly, Candidate, Entry, rejection, Outcome" in contract
    )
    assert "Empty/zero natural activity is truthful evidence" in " ".join(contract.split())


def test_outcome_contract_freezes_objects_writer_readers_and_compatibility() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    kinds = _text_block_after(
        contract, "This restriction does\nnot prevent the same future owner"
    ).splitlines()
    envelope = _text_block_after(contract, "Every object has exactly this top-level envelope:")
    provenance = _text_block_after(
        contract, "Every `source_provenance` member is an object with exactly:"
    )
    direct_source = _text_block_after(
        contract, "Every external direct source reference is an object with exactly:"
    )
    leg_commission_source = _text_block_after(
        contract, "Every leg commission source reference is an object with exactly:"
    )
    provenance_roles = _table_rows_after(contract, "| Consumed root | Exact role")
    provenance_kinds = _table_rows_after(contract, "| Object kind | Exact provenance derivation")
    opportunity_provenance = _table_rows_after(
        contract, "| Eligibility reason | `COMMISSION` roots"
    )

    assert tuple(kinds) == (
        "SHADOW_OUTCOME_OBSERVATION",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
        "REJECTED_COUNTERFACTUAL_ANCHOR",
        "REJECTED_COUNTERFACTUAL_OBSERVATION",
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
        "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
        "REJECTED_COUNTERFACTUAL_EXIT",
        "REJECTED_COUNTERFACTUAL_OUTCOME",
        "ALIGNED_POLICY_NO_TRADE_PAIR",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    assert _declared_keys(envelope) == (
        "object_kind",
        "content_schema_identity",
        "object_identity",
        "outcome_contract_identity",
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
        "fact_boundary",
        "source_provenance",
        "payload",
        "non_claims",
    )
    assert _declared_keys(provenance) == (
        "source_role",
        "source_identity",
        "receipt_fact_boundary",
    )
    assert _declared_keys(direct_source) == (
        "source_identity",
        "receipt_fact_boundary",
    )
    assert hashlib.sha256(direct_source.encode("utf-8")).hexdigest() == (
        "9bddc681625770a66b39caafb5bf79b4f64ed96b395e5da61f9ab7ca42b2df39"
    )
    assert _declared_keys(leg_commission_source) == (
        "canonical_leg_role",
        "source_identity",
        "receipt_fact_boundary",
    )
    assert hashlib.sha256(leg_commission_source.encode("utf-8")).hexdigest() == (
        "690ddd9d3b974b910447363be4c2c3efaf63142d61a63281e1fe90ed6bd6d60a"
    )
    assert tuple(row[1] for row in provenance_roles) == (
        "`ANCHOR`",
        "`POSITION_EVALUATION`",
        "`POSITION_ACTION`",
        "`CLOSE_QUOTE_EVALUATION`",
        "`CLOSE_OPPORTUNITY_EVALUATION`",
        "`SELECTED_EXIT`",
        "`TERMINAL_OUTCOME`",
        "`POSITION_FACT`",
        "`COMBO_QUOTE`",
        "`COMMISSION`",
        "`INDEX`",
        "`INSTRUMENT_LIFECYCLE`",
        "`ATTEMPT_CONTROL`",
        "`SUPERVISOR_CONTROL`",
    )
    assert tuple(row[0].strip("`") for row in provenance_kinds) == tuple(kinds)
    provenance_derivation_bytes = json.dumps(
        provenance_kinds,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(provenance_derivation_bytes).hexdigest() == (
        "9b28c00ea94434cf2dae07bd1946ff36553fc45eea9613c00e13de5911157ca7"
    )
    assert tuple(row[0] for row in opportunity_provenance) == (
        "`KNOWN_ATOMIC_UNAVAILABLE`",
        "`QUOTE_OR_ATTEMPT_UNKNOWN`",
        "`COMMISSION_UNKNOWN`",
        "`COMMISSION_ABOVE_POLICY`",
        "`INDEX_UNKNOWN`",
        "`ELIGIBLE_COMPLETE`",
    )
    assert opportunity_provenance[0][1:] == ("zero", "zero")
    assert "zero through two" in opportunity_provenance[2][1]
    assert opportunity_provenance[3][1:] == ("exactly two", "zero")
    assert opportunity_provenance[5][1:] == ("exactly two", "exactly one")
    assert "every\nactually consumed short- or long-leg commission fraction" in contract
    assert "one-hop audit set, not a transitive provenance graph" in contract
    assert "never attempts to expand an upstream\n`X.source_provenance`" in contract
    assert "pure projection with no independently supplied identity or boundary" in " ".join(
        contract.split()
    )
    assert "committed terminal-barrier identity" not in contract
    assert "same `terminal_source_identity` stored by the summary" in contract
    assert "Every rejected-exit economic field is byte-identical" in " ".join(contract.split())
    assert "bytewise-ascending UTF-8 `(source_role, source_identity)`" in contract
    assert "exact sum of `amount_btc` equals the object's `full_quantity_btc`" in contract
    assert "only\nthe final member may be truncated" in contract
    expected_payload_keys = {
        "SHADOW_OUTCOME_OBSERVATION": (
            "shadow_observation_identity",
            "shadow_entry_identity",
            "start_fact_boundary",
            "aligned_pair_identity",
            "cohort_enrolled",
            "lifecycle_state",
        ),
        "SHADOW_COUNTERFACTUAL_EXIT": (
            "shadow_counterfactual_exit_identity",
            "shadow_observation_identity",
            "first_latched_close_action_identity",
            "close_opportunity_evaluation_identity",
            "shadow_close_opportunity_identity",
            "selection_fact_boundary",
            "first_latched_close_action_fact_boundary",
            "close_opportunity_evaluation_fact_boundary",
            "combo_quote_source_ref",
            "commission_source_refs",
            "index_source_ref",
            "canonical_combo_identity",
            "canonical_leg_identities",
            "close_direction",
            "full_quantity_btc",
            "consumed_levels",
            "short_leg_taker_commission_fraction",
            "long_leg_taker_commission_fraction",
            "close_index_usdc_per_btc",
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "net_close_debit_usdc",
            "projected_shadow_net_pnl_usdc",
            "projected_net_loss_usdc",
        ),
        "SHADOW_OUTCOME": (
            "shadow_outcome_identity",
            "shadow_observation_identity",
            "shadow_entry_identity",
            "terminal_state",
            "terminal_fact_boundary",
            "selected_exit_identity",
            "first_latched_close_action_identity",
            "first_latched_close_action_fact_boundary",
            "scheduled_post_close_attempt_identity",
            "scheduled_post_close_attempt_fact_boundary",
            "post_close_attempt_terminal_identity",
            "post_close_attempt_terminal_status",
            "post_close_attempt_terminal_owner",
            "post_close_attempt_terminal_fact_boundary",
            "natural_terminal_lifecycle_witnesses",
            "censor_mask",
            "terminal_supervisor_source_identity",
            "gross_entry_credit_usdc",
            "entry_fee_reserve_usdc",
            "net_entry_credit_usdc",
            "contractual_payoff_max_loss_ex_fees_usdc",
            "entry_fee_reserved_payoff_loss_usdc",
            "underwriting_reserved_loss_usdc",
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "gross_pnl_usdc",
            "total_public_fee_reserve_usdc",
            "net_pnl_after_public_standard_fee_reserve_usdc",
            "net_loss_usdc",
            "economic_availability",
            "actual_entry_fee_usdc",
            "actual_close_fee_usdc",
            "actual_total_fee_usdc",
            "actual_pnl_usdc",
            "actual_exposure_quantity_btc",
            "actual_exposure_duration_ms",
            "actual_all_in_loss_usdc",
            "actual_all_in_max_loss_usdc",
            "actual_fill_identity",
            "actual_settlement_cashflow_usdc",
            "actual_availability",
        ),
        "REJECTED_COUNTERFACTUAL_ANCHOR": (
            "rejected_anchor_identity",
            "underwriting_position_slot_key",
            "underwriting_action_identity",
            "underwriting_action",
            "anchor_fact_boundary",
            "canonical_combo_identity",
            "canonical_leg_identities",
            "entry_direction",
            "full_quantity_btc",
            "entry_consumed_levels",
            "entry_combo_quote_source_ref",
            "entry_commission_source_refs",
            "entry_index_usdc_per_btc",
            "entry_index_source_identity",
            "entry_index_fact_boundary",
            "entry_short_leg_mark_iv_fraction",
            "entry_short_leg_mark_iv_source_identity",
            "entry_short_leg_mark_iv_fact_boundary",
            "gross_entry_credit_usdc",
            "entry_fee_reserve_usdc",
            "net_entry_credit_usdc",
            "contractual_payoff_max_loss_ex_fees_usdc",
            "entry_fee_reserved_payoff_loss_usdc",
            "underwriting_reserved_loss_usdc",
        ),
        "REJECTED_COUNTERFACTUAL_OBSERVATION": (
            "rejected_observation_identity",
            "rejected_anchor_identity",
            "start_fact_boundary",
            "aligned_pair_identity",
            "cohort_enrolled",
            "lifecycle_state",
        ),
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION": (
            "rejected_position_evaluation_identity",
            "rejected_observation_identity",
            "consumed_position_fact_fingerprint",
            "evaluation_fact_boundary",
            "ordered_predicate_truth_vector",
            "entry_index_usdc_per_btc",
            "entry_index_source_identity",
            "entry_index_fact_boundary",
            "entry_short_leg_mark_iv_fraction",
            "entry_short_leg_mark_iv_source_identity",
            "entry_short_leg_mark_iv_fact_boundary",
            "prior_evaluation_index_usdc_per_btc",
            "prior_evaluation_index_source_identity",
            "prior_evaluation_index_fact_boundary",
            "current_index_usdc_per_btc",
            "current_index_source_identity",
            "current_index_fact_boundary",
            "current_index_availability",
            "next_evaluation_index_usdc_per_btc",
        ),
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION": (
            "rejected_position_action_identity",
            "rejected_position_evaluation_identity",
            "serialized_action",
            "ordered_predicate_truth_vector",
            "ordered_latched_close_reason_vector",
            "first_latched_close_action_identity",
            "scheduled_post_close_attempt_identity",
            "action_fact_boundary",
        ),
        "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION": (
            "rejected_close_quote_evaluation_identity",
            "rejected_observation_identity",
            "first_latched_close_action_identity",
            "canonical_combo_identity",
            "canonical_leg_identities",
            "close_direction",
            "full_quantity_btc",
            "consumed_rule_scoped_quote_fingerprint",
            "close_quote_state",
            "close_conditioning",
            "consumed_levels",
            "gross_close_cashflow_usdc",
            "evaluation_fact_boundary",
        ),
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION": (
            "rejected_close_opportunity_evaluation_identity",
            "rejected_observation_identity",
            "first_latched_close_action_identity",
            "close_quote_evaluation_identity",
            "attempt_terminal_identity",
            "attempt_terminal_fact_boundary",
            "opportunity_economics_business_fingerprint",
            "eligibility",
            "eligibility_reason",
            "evaluation_fact_boundary",
            "gross_close_cashflow_usdc",
            "gross_cashflow_availability",
            "short_leg_taker_commission_fraction",
            "long_leg_taker_commission_fraction",
            "commission_source_refs",
            "close_index_usdc_per_btc",
            "index_source_ref",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "net_close_debit_usdc",
            "projected_shadow_net_pnl_usdc",
            "projected_net_loss_usdc",
            "derived_economics_availability",
        ),
        "REJECTED_COUNTERFACTUAL_EXIT": (
            "rejected_exit_identity",
            "rejected_observation_identity",
            "first_latched_close_action_identity",
            "close_quote_evaluation_identity",
            "close_opportunity_evaluation_identity",
            "selection_fact_boundary",
            "first_latched_close_action_fact_boundary",
            "close_quote_evaluation_fact_boundary",
            "close_opportunity_evaluation_fact_boundary",
            "consumed_rule_scoped_quote_fingerprint",
            "commission_source_refs",
            "index_source_ref",
            "canonical_combo_identity",
            "canonical_leg_identities",
            "close_direction",
            "full_quantity_btc",
            "consumed_levels",
            "short_leg_taker_commission_fraction",
            "long_leg_taker_commission_fraction",
            "close_index_usdc_per_btc",
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "net_close_debit_usdc",
            "projected_shadow_net_pnl_usdc",
            "projected_net_loss_usdc",
        ),
        "REJECTED_COUNTERFACTUAL_OUTCOME": (
            "rejected_outcome_identity",
            "rejected_observation_identity",
            "rejected_anchor_identity",
            "terminal_state",
            "terminal_fact_boundary",
            "selected_exit_identity",
            "first_latched_close_action_identity",
            "first_latched_close_action_fact_boundary",
            "scheduled_post_close_attempt_identity",
            "scheduled_post_close_attempt_fact_boundary",
            "post_close_attempt_terminal_identity",
            "post_close_attempt_terminal_status",
            "post_close_attempt_terminal_owner",
            "post_close_attempt_terminal_fact_boundary",
            "natural_terminal_lifecycle_witnesses",
            "censor_mask",
            "terminal_supervisor_source_identity",
            "gross_entry_credit_usdc",
            "entry_fee_reserve_usdc",
            "net_entry_credit_usdc",
            "contractual_payoff_max_loss_ex_fees_usdc",
            "entry_fee_reserved_payoff_loss_usdc",
            "underwriting_reserved_loss_usdc",
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "gross_pnl_usdc",
            "total_public_fee_reserve_usdc",
            "net_pnl_after_public_standard_fee_reserve_usdc",
            "net_loss_usdc",
            "economic_availability",
            "actual_entry_fee_usdc",
            "actual_close_fee_usdc",
            "actual_total_fee_usdc",
            "actual_pnl_usdc",
            "actual_exposure_quantity_btc",
            "actual_exposure_duration_ms",
            "actual_all_in_loss_usdc",
            "actual_all_in_max_loss_usdc",
            "actual_fill_identity",
            "actual_settlement_cashflow_usdc",
            "actual_availability",
        ),
        "ALIGNED_POLICY_NO_TRADE_PAIR": (
            "aligned_pair_identity",
            "pair_family",
            "cohort_enrolled",
            "pair_anchor_identity",
            "policy_arm",
            "alternative_arm",
            "trade_observation_identity",
            "trade_outcome_identity",
            "terminal_state",
            "terminal_fact_boundary",
            "censor_mask",
            "no_trade_cashflow_usdc",
            "trade_net_pnl_after_public_standard_fee_reserve_usdc",
            "policy_advantage_usdc",
            "comparison_availability",
        ),
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY": (
            "cohort_summary_identity",
            "manifest_identity",
            "runtime_start_fact_boundary",
            "enrollment_end_fact_boundary",
            "enrollment_end_reason",
            "terminal_fact_boundary",
            "terminal_disposition",
            "planned_final_stop_fact_boundary",
            "terminal_source_identity",
            "terminal_source",
            "evidence_status",
            "counts",
            "rates",
            "conservation_status",
        ),
    }
    for kind, keys in expected_payload_keys.items():
        payload_schema = _text_block_after_last(contract, f"`{kind}`:")
        assert _declared_keys(payload_schema) == keys
        assert (
            hashlib.sha256(payload_schema.encode("utf-8")).hexdigest()
            == {
                "SHADOW_OUTCOME_OBSERVATION": (
                    "30ca3ec8d42cf234d45588c9749aa61bc15b246e05f0292dd9af22a93d2d9f99"
                ),
                "SHADOW_COUNTERFACTUAL_EXIT": (
                    "67b813dceab5b0e202de81bbfcc3c986bf57dbae8beae73c65ef7a9f8a02f402"
                ),
                "SHADOW_OUTCOME": (
                    "92c97fa534e9366ba53cd0f9efb63091429ddbaea797c15b889960168975d2f9"
                ),
                "REJECTED_COUNTERFACTUAL_ANCHOR": (
                    "3ef7cfdf942d086bb4a0530c9cf9aacd3a616a32a2ece9d58fd14581943e9614"
                ),
                "REJECTED_COUNTERFACTUAL_OBSERVATION": (
                    "97308f20ff8b3dfb9da8397821e5bff86f762157d2e9670f52438af1b6d7a683"
                ),
                "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION": (
                    "009a94fd5dff1c095658e55f584500cee75200e1d53b2f1dd59f011f6049334c"
                ),
                "REJECTED_COUNTERFACTUAL_POSITION_ACTION": (
                    "ddfea924cdcf649e1d6bdafb7a46aac780bb57e0f8d56b1cd6b3b96ff609b9de"
                ),
                "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION": (
                    "8ea30fed1e1fde5cf8346759eb0f7233f8902c8542d57d85c99faafbb0e110c9"
                ),
                "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION": (
                    "04f59da0e1ad343154e2fde26691828e6a391b2c1631dc3eb8fefa860284b20e"
                ),
                "REJECTED_COUNTERFACTUAL_EXIT": (
                    "8ff949f80c5251330929840e2411b030db9433df968972e47e7628f019d243b6"
                ),
                "REJECTED_COUNTERFACTUAL_OUTCOME": (
                    "982141d36ce923778058cae9a27bfa78efdbf54d51e6e079974f5d4eb9d32d11"
                ),
                "ALIGNED_POLICY_NO_TRADE_PAIR": (
                    "471b60dcb44923337f2c87c2da46e27abe3afd954b527f3366a8ef9d7f4c6e99"
                ),
                "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY": (
                    "9a5a27082374f4c01651ecbca5b0fce5f8ae1eeaf3e1d65547eac7aedbe6042f"
                ),
            }[kind]
        )

    assert "only future pure downstream owner is `short_vol_underwriting`" in contract
    assert _text_block_after(contract, "For each kind:") == (
        "content_schema_identity =\n"
        "    CanonicalIdentity(\n"
        '        "OUTCOME_CONTENT_SCHEMA",\n'
        "        OutcomeContractContentDigest,\n"
        "        object_kind\n"
        "    )"
    )
    assert "EXACT_KEYS_AND_TYPES_DECLARED_IN_THIS_CONTRACT" not in contract
    assert "they do\nnot accept a minimum subset, unknown extension" in contract
    assert "identical duplicate is an idempotent no-op" in contract
    assert "conflicting duplicate is a hard error" in contract
    assert "mixed code/contract/Policy/runtime identities fail closed" in contract
    assert "`objects/<object_kind>/<object_identity_without_sha256_prefix>.json`" in contract
    assert "Unknown entries inside `objects/` are invalid" in contract
    assert "`NOT_COMPARABLE`" in contract
    assert "No migration, replay, recomputation, backfill, relabeling" in " ".join(contract.split())


def test_outcome_contract_freezes_rejected_rule_matrix_and_witness_dependencies() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    opportunity_rows = _table_rows_after(contract, "| Eligibility reason | eligibility")
    actual_availability = _text_block_after(
        contract, "`ActualAvailability` is an object with exactly these keys"
    )
    actual_values = _text_block_after(
        contract, "The following value members are always JSON `null`"
    )

    assert opportunity_rows == (
        (
            "`KNOWN_ATOMIC_UNAVAILABLE`",
            "`INELIGIBLE`",
            "`null / NOT_APPLICABLE`",
            "both `null`",
            "`null`",
            "all `null / NOT_APPLICABLE`",
        ),
        (
            "`QUOTE_OR_ATTEMPT_UNKNOWN`",
            "`UNKNOWN`",
            "`null / UNKNOWN`",
            "both `null`",
            "`null`",
            "all `null / UNKNOWN`",
        ),
        (
            "`COMMISSION_UNKNOWN`",
            "`UNKNOWN`",
            "`Decimal / KNOWN`",
            "both `null`",
            "`null`",
            "all `null / UNKNOWN`",
        ),
        (
            "`COMMISSION_ABOVE_POLICY`",
            "`INELIGIBLE`",
            "`Decimal / KNOWN`",
            "both `Decimal`",
            "`null`",
            "all `null / UNKNOWN`",
        ),
        (
            "`INDEX_UNKNOWN`",
            "`UNKNOWN`",
            "`Decimal / KNOWN`",
            "both `Decimal`",
            "`null`",
            "all `null / UNKNOWN`",
        ),
        (
            "`ELIGIBLE_COMPLETE`",
            "`ELIGIBLE`",
            "`Decimal / KNOWN`",
            "both `Decimal`",
            "positive `Decimal`",
            "all `Decimal / KNOWN`",
        ),
    )
    assert _declared_keys(actual_availability) == (
        "actual_entry_fee_usdc",
        "actual_close_fee_usdc",
        "actual_total_fee_usdc",
        "actual_pnl_usdc",
        "actual_exposure_quantity_btc",
        "actual_exposure_duration_ms",
        "actual_all_in_loss_usdc",
        "actual_all_in_max_loss_usdc",
        "actual_fill_identity",
        "actual_settlement_cashflow_usdc",
    )
    assert tuple(actual_values.splitlines()) == tuple(
        f"{key}: null" for key in _declared_keys(actual_availability)
    )
    assert all(line.endswith(': "UNKNOWN"') for line in actual_availability.splitlines())
    assert '`close_conditioning = "PRE_CLOSE"` iff' in contract
    assert "first_latched_close_action_identity` is `null`" in contract
    assert "only a strictly later accepted source fact changes conditioning" in contract
    assert "current index availability is `KNOWN`" in contract
    assert ("`next_evaluation_index_usdc_per_btc = current_index_usdc_per_btc`") in contract
    assert (
        "`next_evaluation_index_usdc_per_btc = prior_evaluation_index_usdc_per_btc`"
    ) in contract
    assert "first_latched_close_action_identity` is `null` iff" in contract
    flat = " ".join(contract.split())
    assert "attempt still pending when the barrier opens" in flat
    assert "attempt terminal boundary equal to the Outcome terminal boundary" in flat


def test_outcome_contract_freezes_conservation_denominators_and_nulls() -> None:
    contract = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    conservation = _text_block_after(contract, "For every complete evidence directory:")
    cohort_counts = _text_block_after(
        contract, "`CohortCounts` has exactly these nonnegative-integer keys:"
    )
    cohort_rates = _text_block_after(
        contract, "`CohortRates` has exactly these `ExactRate | null` keys:"
    )
    exact_rate = _text_block_after(contract, "`ExactRate` is an object with exactly:")
    summary_identity = _text_block_after(contract, "The summary identity is:")
    status_rows = _table_rows_after(contract, "| evidence status | conservation status")
    null_rows = _table_rows_after(contract, "### Exact terminal null matrix")
    metric_rows = _table_rows_after(contract, "| `CohortRates` key | Exact numerator")

    assert tuple(cohort_counts.splitlines()) == (
        "shadow_entry_count",
        "shadow_observation_count",
        "shadow_pending_count",
        "shadow_mature_known_count",
        "shadow_mature_unknown_count",
        "shadow_censored_stop_count",
        "shadow_censored_failure_count",
        "shadow_outcome_count",
        "shadow_selected_exit_count",
        "shadow_terminal_pair_count",
        "rejected_anchor_count",
        "rejected_observation_count",
        "rejected_pending_count",
        "rejected_mature_known_count",
        "rejected_mature_unknown_count",
        "rejected_censored_stop_count",
        "rejected_censored_failure_count",
        "rejected_outcome_count",
        "rejected_selected_exit_count",
        "rejected_terminal_pair_count",
        "rejected_position_evaluation_count",
        "rejected_position_action_count",
        "rejected_close_quote_evaluation_count",
        "rejected_close_opportunity_evaluation_count",
        "logical_admitted_pair_count",
        "logical_rejected_pair_count",
        "logical_aligned_pair_count",
        "non_enrolled_admitted_pair_count",
        "non_enrolled_rejected_pair_count",
        "enrolled_admitted_pair_count",
        "enrolled_admitted_pending_count",
        "enrolled_admitted_mature_known_count",
        "enrolled_admitted_mature_unknown_count",
        "enrolled_admitted_censored_stop_count",
        "enrolled_admitted_censored_failure_count",
        "enrolled_rejected_pair_count",
        "enrolled_rejected_pending_count",
        "enrolled_rejected_mature_known_count",
        "enrolled_rejected_mature_unknown_count",
        "enrolled_rejected_censored_stop_count",
        "enrolled_rejected_censored_failure_count",
        "enrolled_aligned_pair_count",
        "enrolled_terminal_pair_count",
        "enrolled_comparable_pair_count",
        "logical_no_trade_arm_count",
        "durable_terminal_pair_count",
        "durable_no_trade_arm_count",
        "enrolled_admitted_mature_known_win_count",
        "enrolled_admitted_mature_known_loss_count",
        "enrolled_admitted_mature_known_zero_count",
        "enrolled_rejected_mature_known_win_count",
        "enrolled_rejected_mature_known_loss_count",
        "enrolled_rejected_mature_known_zero_count",
    )
    assert tuple(cohort_rates.splitlines()) == (
        "admitted_terminal_availability_rate",
        "rejected_terminal_availability_rate",
        "admitted_maturity_known_share",
        "rejected_maturity_known_share",
        "admitted_win_rate",
        "admitted_loss_rate",
        "rejected_win_rate",
        "rejected_loss_rate",
        "aligned_economic_comparison_availability_rate",
    )
    assert tuple(exact_rate.splitlines()) == (
        "numerator: NonNegativeInteger",
        "denominator: positive JSON integer",
    )
    assert summary_identity == (
        "CohortSummaryIdentity =\n"
        "    OutcomeContractIdentity\n"
        "    × runtime_identity\n"  # noqa: RUF001
        "    × manifest_identity\n"  # noqa: RUF001
        "    × terminal_FactBoundary"  # noqa: RUF001
    )
    assert tuple(row[:2] for row in status_rows) == (
        ("`COMPLETE`", "exactly `MET`"),
        ("`INCOMPLETE` with a deterministic contradiction below", "exactly `NOT_MET`"),
        (
            "`INCOMPLETE` with no deterministic contradiction below",
            "exactly `UNKNOWN`",
        ),
    )
    assert "every positive-denominator formula is its exact `ExactRate`" in status_rows[0][3]
    assert status_rows[1][3] == "all nine values `null`"
    assert status_rows[2][3] == "all nine values `null`"
    assert "`COMPLETE × NOT_MET`, `COMPLETE × UNKNOWN`, and `INCOMPLETE × MET` are invalid" in (  # noqa: RUF001
        " ".join(contract.split())
    )
    assert "observed-valid unique-identity lower-bound counts" in status_rows[1][2]
    assert "bytewise-ascending relative-path order" in contract
    assert "existing unreadable or truncated file inside\n`objects/`" in contract
    for equation in (
        "shadow_entry_count =\n    shadow_observation_count",
        "shadow_outcome_count =",
        "shadow_selected_exit_count =\n    shadow_mature_known_count",
        "shadow_terminal_pair_count =\n    shadow_outcome_count",
        "rejected_anchor_count =\n    rejected_observation_count",
        "rejected_outcome_count =",
        "rejected_selected_exit_count =\n    rejected_mature_known_count",
        "rejected_terminal_pair_count =\n    rejected_outcome_count",
        "rejected_position_evaluation_count =\n    rejected_position_action_count",
        "logical_admitted_pair_count =",
        "logical_rejected_pair_count =",
        "enrolled_admitted_pair_count =",
        "enrolled_rejected_pair_count =",
        "enrolled_terminal_pair_count =",
        "enrolled_comparable_pair_count =",
        "logical_no_trade_arm_count =\n    logical_aligned_pair_count",
        "durable_no_trade_arm_count =\n    durable_terminal_pair_count",
    ):
        assert equation in conservation
    assert [row[0] for row in null_rows[1:]] == [
        "`MATURE_KNOWN`",
        "`MATURE_UNKNOWN`",
        "`CENSORED_AT_STOP`",
        "`CENSORED_AT_FAILURE`",
    ]
    assert null_rows[1][6:9] == (
        "all seven `Decimal`",
        "`KNOWN`",
        "all ten `null`; all ten availability values `UNKNOWN`",
    )
    assert null_rows[2][6:9] == (
        "all seven `null`",
        "`UNKNOWN`",
        "all ten `null`; all ten availability values `UNKNOWN`",
    )
    assert "retain an earlier `ORDINARY` non-`CENSORED` terminal" in null_rows[3][2]
    assert "owner `STOP`" in null_rows[3][2]
    assert "retain an earlier `ORDINARY` non-`CENSORED` terminal" in null_rows[4][2]
    assert "owner `FAILURE`" in null_rows[4][2]
    assert "stop/failure never rewrites it" in contract
    aligned_row = next(
        row for row in metric_rows if row[0] == "`aligned_economic_comparison_availability_rate`"
    )
    assert aligned_row[1] == "`enrolled_comparable_pair_count`"
    assert "`enrolled_terminal_pair_count`" in aligned_row[2]
    assert "mature-unknown/censored included" in aligned_row[2]
    assert "so `1/3` remains exactly `{1, 3}`" in contract
    assert "not tautologically one" in contract
    assert "Admitted and rejected economic distributions are never silently pooled" in contract
    assert "exact zero is neither win nor loss" in contract
    assert "zero or unavailable denominator serializes the rate as `null`, never `0`" in (
        " ".join(contract.split()).lower()
    )


def test_authority_defines_one_live_flow_and_implemented_frozen_downstream_contracts() -> None:
    constitution = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    underwriting = (ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md").read_text(
        encoding="utf-8"
    )
    outcome = (ROOT / "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    target_authority = "\n".join(
        (
            constitution,
            current_stage,
            architecture,
            delivery,
            radar,
            underwriting,
            outcome,
            service,
            readme,
        )
    )
    constitution = " ".join(constitution.split())
    current_stage = " ".join(current_stage.split())
    architecture = " ".join(architecture.split())
    delivery = " ".join(delivery.split())
    radar = " ".join(radar.split())
    underwriting = " ".join(underwriting.split())
    outcome = " ".join(outcome.split())
    service = " ".join(service.split())
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
        "Without Shadow admission there is no Outcome object",
        "A missing quote cannot erase a known hard-close obligation",
    ):
        assert invariant in constitution
    assert (
        "`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`"
        in constitution
    )

    for invariant in (
        "## Current truth",
        "`OFFLINE_PUBLIC_SHADOW_RUNTIME`",
        "`NOT_ACCEPTED_PENDING_REVALIDATION`",
        "`SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`",
        "`STOPPED_NO_DEPLOYMENT`",
        "**Live commands:** `FORBIDDEN`",
        "Deleted history is not a business premise",
        "commissioning controller",
        "service lifecycle evidence/terminal-manifest system",
        "cannot accept the Radar, authorize deployment",
        "private/account APIs",
        "orders, fills",
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
        "### `short_vol_underwriting`",
        "The pure downstream owner `short_vol_underwriting`",
        "Production-public invocation and deployment authority comes only from `CURRENT_STAGE`",
        "at least 500 monotonic milliseconds",
        "`flush_pending()` once before reconnect or clean-stop terminal mutation",
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
        "public-only modular runtime",
        "SHORT_VOL_UNDERWRITING_POSITION",
        "SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT",
        "No production result is currently accepted",
        "`SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`",
        "coalesced Workbench publication",
        "commissioning controller",
        "maker/order/fill",
        "service-evidence ledger",
        "no deployed process",
    ):
        assert invariant in readme
    assert "effective-time" not in readme
    assert "2026-08-01T00:00:00Z" not in readme

    for invariant in (
        "**Status:** ACTIVE IMPLEMENTATION CONTRACT",
        "`CONTRACT_FROZEN_RUNTIME_NOT_IMPLEMENTED`",
        "public quote is not a fill",
        "`actual_all_in_max_loss_usdc` is always `null`",
        "A Candidate has no arbitrary TTL",
        "The refreshed book may have economically identical levels",
        "Once a known close predicate is true",
        "A zero or unknown denominator serializes rate `null`, never `0`",
    ):
        assert invariant in underwriting

    for invariant in (
        "**Status:** ACTIVE IMPLEMENTATION/EVALUATION CONTRACT",
        "No fourth strategy Policy exists",
        "Same-boundary total order",
        "NO_ACTUAL_ALL_IN_LOSS_OR_MAX_LOSS",
    ):
        assert invariant in outcome

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
        "There is no second service-level reader or hash ledger",
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
    assert "`SHORT_VOL_PUBLIC_SHADOW_RUNTIME_SIMPLIFICATION`" in current
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

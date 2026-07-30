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


def test_agents_is_a_short_map_to_all_active_authority() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert len(agents.splitlines()) <= 100
    assert "are orthogonal; none overrides another" in agents
    for path in AUTHORITY_FILES:
        assert path.relative_to(ROOT).as_posix() in agents
    assert "tasks/TEMPLATE.md" in agents


def test_active_authority_and_contract_sets_are_exact() -> None:
    assert {path.name for path in (ROOT / "docs/authority").glob("*.md")} == {
        "CURRENT_STAGE.md",
        "DELIVERY_CONTRACT.md",
        "PRODUCT_CONSTITUTION.md",
        "SYSTEM_ARCHITECTURE.md",
    }
    assert {path.name for path in (ROOT / "docs/contracts").glob("*.md")} == {
        "SHORT_VOL_RADAR.md",
        "SHORT_VOL_UNDERWRITING_POSITION.md",
    }
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
    for owner, package_root in PACKAGE_ROOTS.items():
        for path in package_root.rglob("*.py"):
            forbidden = _internal_imports(path) - ALLOWED_IMPORTS[owner]
            assert not forbidden, f"{path} imports higher layer(s): {sorted(forbidden)}"


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


def test_contract_freeze_is_closed_without_activating_implementation() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    current_stage_flat = " ".join(current_stage.split())

    marker = "**Sole authorized next product-capability closure:**"
    assert current_stage.count(marker) == 1
    assert f"{marker} `NONE — no successor closure activated`" in current_stage
    assert "**Current permission boundary:** `PUBLIC_SHADOW`" in current_stage
    assert (
        "**Implemented runtime capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`" in current_stage
    )
    assert "**Production Short Vol Radar:** `ESTABLISHED`" in current_stage
    assert "The complete Underwriting, Shadow-admission, and Position contract now exists" in (
        current_stage_flat
    )
    assert "separately authorized minimal deterministic implementation" in current_stage_flat
    deterministic_heading = (
        "**Deterministic Underwriting, Shadow-admission, and Position domain implementation:**"
    )
    assert deterministic_heading in current_stage
    assert "**Production-public integration and fixed-Policy forward cohort:**" in current_stage
    assert sorted(path.name for path in (ROOT / "tasks").glob("*.md")) == ["TEMPLATE.md"]
    assert not (ROOT / "tasks/SHORT_VOL_UNDERWRITING_SHADOW_POSITION_CONTRACT.md").exists()


def test_underwriting_position_contract_is_complete_and_implementation_ready() -> None:
    contract_path = ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md"
    contract = contract_path.read_text(encoding="utf-8")
    flat = " ".join(contract.split())

    assert "**Status:** ACTIVE IMPLEMENTATION CONTRACT" in contract
    assert "**Current implementation state:** `CONTRACT_FROZEN — NOT_IMPLEMENTED`" in contract
    for section in (
        "## Exact identities and causal order",
        "## Underwriting Policy contract",
        "## Position Policy contract",
        "## Required public facts",
        "## Exact structure and entry economics",
        "## Fee and reserve economics",
        "## Underwriting truth model",
        "## Underwriting Decision and Candidate identity",
        "## Shadow admission",
        "## Position state",
        "## Position action and hard-close total order",
        "## Shadow close opportunity",
        "## Future durable object meanings",
        "## Business denominators",
        "## Compatibility and evidence boundary",
        "## Implementation boundary",
        "## Official public-source basis",
    ):
        assert section in contract

    for invariant in (
        "policy_schema: SHORT_VOL_UNDERWRITING_POLICY",
        "policy_schema: SHORT_VOL_POSITION_POLICY",
        "Shadow admission is a deterministic gate, not a third Policy",
        "execution_assumption: VISIBLE_ATOMIC_TAKER",
        "account_assumption: DIRECT_STANDARD_ACCOUNT",
        "option_trading_fee_rate_of_index = 0.0003",
        "option_fee_cap_fraction_of_leg_premium = 0.125",
        "delivery_fee_rate_of_index = 0.00015",
        "delivery_fee_cap_fraction_of_intrinsic = 0.125",
        "Fee is never zero by default",
        "accepted_ticker_source_timestamp_ms",
        "observed_maximum_adverse_log_return",
        "The field is a signed cash cost",
        "Underwriting unknown Decision count",
        "gross_entry_credit_usdc = -a_entry × p_entry",
        "gross_close_debit_usdc = a_close × p_close",
        "payoff_maximum_loss_usdc",
        "policy_bounded_conservative_maximum_loss_usdc",
        "underwriting_availability =",
        "NOT_EVALUATED | UNKNOWN | EVALUABLE",
        "underwriting_action =",
        "null | CANDIDATE | WATCH | ABSTAIN",
        "Candidate validity has no arbitrary elapsed-time limit",
        "SUPERSEDED_BY_REUNDERWRITING",
        "strictly later than the Candidate boundary",
        "quiet but continuously usable",
        "shadow_remaining_quantity_btc = entry_target_quantity_btc",
        "position_hold_margin_usdc",
        "position_action = HOLD | CLOSE | UNKNOWN",
        "EXPIRY_OR_FINAL_SETTLEMENT_WINDOW",
        "SOURCE_CONTINUITY_LOST",
        "RADAR_THESIS_ENDED",
        "SETTLEMENT_STRESS_BOUND_INSUFFICIENT",
        "SHORT_LEG_DELTA_OR_GAMMA_LIMIT",
        "ATOMIC_CLOSE_NOT_EXECUTABLE",
        "A known hard close has priority over missing soft-risk facts",
        "close_quote_state =",
        "ATOMIC_COMBO_CLOSE_QUOTE",
        "LEGGED_CLOSE_REFERENCE",
        "SHORT_VOL_SHADOW_ADMISSION_DECISION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "A close opportunity is not a fill",
        "Every rate serializes `null` when its denominator is zero or unknown",
        "No current package, CLI, schema writer, service, or live command is created",
    ):
        assert invariant in contract

    assert "TBD" not in contract
    assert "NOT_APPLICABLE AT ACTIVATION" not in contract
    assert "public quote" in flat.lower()
    assert "private/get_leg_prices" in contract


def test_authority_defines_one_live_radar_and_one_frozen_downstream_contract() -> None:
    constitution = (ROOT / "docs/authority/PRODUCT_CONSTITUTION.md").read_text(encoding="utf-8")
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/authority/SYSTEM_ARCHITECTURE.md").read_text(encoding="utf-8")
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    downstream = (
        ROOT / "docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md"
    ).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for invariant in (
        "Receiving a relevant public market event",
        "Normal market events that produce no Short Vol anomaly are not durable business objects",
        "`SHADOW_ENTRY` requires a still-valid Candidate",
        "A missing quote cannot erase a known hard-close obligation",
        "Without Shadow admission there is no Outcome object",
    ):
        assert invariant in constitution

    for invariant in (
        "There is no capture job followed by a scan job",
        "A quiet unchanged book remains current",
        "Frozen downstream domain boundary",
        "No current package implements or consumes that boundary",
        "the first deterministic implementation must precede any forward cohort",
        "Shadow admission has no independent Policy",
    ):
        assert invariant in architecture

    assert "Do not require full replay" in delivery
    assert "`UNKNOWN` is neither numeric zero nor economic `ABSTAIN`" in delivery
    assert "The Radar never returns `CANDIDATE`, `WATCH`, `ABSTAIN`, `HOLD`, or `CLOSE`." in radar
    assert "Layer 2 intentionally stops at gross public availability" in radar
    assert "Candidate validity has no arbitrary elapsed-time limit" in downstream
    assert "No successor product-capability closure is active" in readme
    assert "no Underwriting or Position package" in readme
    assert "`NONE — no successor closure activated`" in current_stage


def test_current_runtime_surface_has_no_downstream_implementation() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    cli = (ROOT / "apps/radar_runtime/src/radar_runtime/__main__.py").read_text(encoding="utf-8")
    evidence = (
        ROOT / "packages/short_vol_radar/src/short_vol_radar/evidence.py"
    ).read_text(encoding="utf-8")
    atomic = (
        ROOT / "packages/short_vol_radar/src/short_vol_radar/atomic.py"
    ).read_text(encoding="utf-8")

    assert '"market_monitor"' in pyproject
    assert '"options_domain"' in pyproject
    assert '"short_vol_radar"' in pyproject
    assert '"radar_runtime"' in pyproject
    assert "short_vol_underwriting" not in pyproject
    assert "short_vol_position" not in pyproject
    assert 'subparsers.add_parser("observe")' in cli
    assert "underwrite" not in cli
    assert "shadow" not in cli.lower()
    assert "def write_anomaly" in evidence
    assert "def write_atomic" in evidence
    assert "def write_summary" in evidence
    for forbidden in (
        "def write_underwriting",
        "def write_shadow_entry",
        "def write_position",
        "def write_close_opportunity",
    ):
        assert forbidden not in evidence
    assert "gross_entry_credit_usdc" in atomic
    assert "maximum_loss" not in atomic
    assert "trading_fee" not in atomic


def test_no_active_or_completed_task_accumulates() -> None:
    task_paths = tuple(path for path in (ROOT / "tasks").glob("*.md") if path.name != "TEMPLATE.md")
    assert task_paths == ()


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


def test_index_publication_contract_and_sealed_readers_remain_unchanged() -> None:
    radar = (ROOT / "docs/contracts/SHORT_VOL_RADAR.md").read_text(encoding="utf-8")
    flat = " ".join(radar.split())

    for invariant in (
        "`IndexTailStatus` and `IndexBaselineState.status` remain current production Python "
        "projections",
        "`INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name",
        "never serialized by the current or sealed evidence writers",
        "`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING`",
        "Normal index publication pending is not a suspension or detector state",
        "current-schema writer and validator path accept only version 6",
        "Explicit read-only validators continue to validate sealed version-5, version-4, "
        "version-3, and version-2",
    ):
        assert invariant in flat


def test_stage_record_preserves_exact_accepted_radar_hashes() -> None:
    current_stage = (ROOT / "docs/authority/CURRENT_STAGE.md").read_text(encoding="utf-8")
    flat = " ".join(current_stage.split())

    for invariant in (
        "candidate commit `9c58120d358fd0e0ccb4885123ab95c67d1c3f31`",
        "candidate tree `1ff49ff697df1a91237eb35f290301e26a7c06dc`",
        "`refs/heads/codex/radar-repository-consolidation` resolved to that exact candidate commit",
        "SHA-256 `4bbf832ab7340e7224a0df5db79aea1cd6fed33d156f2aeec12690f986217a4f`",
        "manifest SHA-256 `70511dad86aa37dcaaab1167b688d342a33a8248635097b6f4c84b436e8e09fd`",
        "summary SHA-256 `700dbbf2649830b656a75de3e3eb74aabef21cb4003786429b823091abcbbfa6`",
        "`3b70b2a7d93b3bbcf2ce31c0e63bc03ff971b18ea4ad7e9270cd943a351cccde`",
        "SHA-256 `d38c5bebef1e2bccfeeb9c69715970d03fda2a0359f02520a5c3deef08463345`",
        "manifest SHA-256 `2cf6af08bdcf7ec3c72e5bbb9292b58261c992dda67b298cf7f4ea99eac64574`",
        "summary SHA-256 `1ec01c5dba427e3a273671ef57421a6f6bfe01f95d26416e35a2d69fe6a6b218`",
        "`7ff691e9b3665e0e9db7196a032440a9f6e79c6802f803b7546cb23f5125f361`",
    ):
        assert invariant in flat


def test_delivery_contract_keeps_remote_and_evidence_authority_separate() -> None:
    delivery = (ROOT / "docs/authority/DELIVERY_CONTRACT.md").read_text(encoding="utf-8")
    flat = " ".join(delivery.split())

    for invariant in (
        "Before a non-force push",
        "pre-push independent exact-commit pass receipt",
        "After the push",
        "verified remote ref value equals the exact commit",
        "Evidence does not create stage permission",
        "Green checks and a Draft PR do not accept authority",
    ):
        assert invariant in flat

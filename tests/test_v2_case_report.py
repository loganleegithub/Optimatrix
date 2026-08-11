from __future__ import annotations

import subprocess
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest
from options_domain import INVERSE_BTC
from radar_runtime.offline_report import (
    V2CaseReportError,
    build_v2_case_report,
    load_v2_case_report,
)
from radar_runtime.service import load_persistent_product_policies
from short_vol_underwriting import (
    ShadowCaseRead,
    ShadowCaseReadStatus,
    ShadowCaseSegmentRead,
    ShadowCaseSegmentStatus,
    ShadowCaseStore,
)

ROOT = Path(__file__).resolve().parents[1]


def _leg(action: str, raw_vwap_native: str, index_price: str) -> dict[str, object]:
    return {
        "action": action,
        "raw_vwap_native": raw_vwap_native,
        "valuation_index_price": index_price,
    }


def _case(
    digit: str,
    *,
    expiry_ms: int,
    selection_band: str,
    entry_band: str,
    outcome_state: str | None,
    gapped: bool = False,
    enrollment_kind: str = "ADMITTED_SHADOW_TRADE",
    sampling_inclusion: tuple[int, int] | None = None,
    unclean: bool = False,
) -> ShadowCaseRead:
    sampling_metadata = (
        {
            "kind": "DETERMINISTIC_BAND_CONTROL",
            "inclusion_numerator": sampling_inclusion[0],
            "inclusion_denominator": sampling_inclusion[1],
        }
        if sampling_inclusion is not None
        else None
    )
    opened = {
        "schema_version": 5,
        "case_id": "sha256:" + digit * 64,
        "enrollment_kind": enrollment_kind,
        "selection_score_packet": {
            "bucket_key": {
                "tte_band_id": "ultra-short-45m-to-6h",
                "expiry_ms": expiry_ms,
                "option_type": "call",
                "delta_bucket": "0.20-0.25",
            },
            "result": {"band": selection_band, "coverage": "COMPLETE"},
            "sampling_metadata": sampling_metadata,
        },
        "entry_refresh_score_packet": {"result": {"band": entry_band}},
        "structure": {
            "expiry_ms": expiry_ms,
            "full_quantity_btc": "0.1",
            "entry_component_legs": [
                _leg("SELL", "0.01", "100000"),
                _leg("BUY", "0.004", "100000"),
            ],
        },
        "entry_economics": {"contractual_payoff_cap_usd": "100"},
        "underwriting": {
            "action": ("CANDIDATE" if enrollment_kind == "ADMITTED_SHADOW_TRADE" else "WATCH")
        },
        "selected_underwriting_decision": (
            None
            if enrollment_kind == "ADMITTED_SHADOW_TRADE"
            else {"selected_economic_action": "WATCH"}
        ),
    }
    outcome = None
    if outcome_state is not None:
        known = outcome_state in {"MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN"}
        outcome = {
            "terminal_state": outcome_state,
            "terminal_method": (
                "CONTRACT_SETTLEMENT"
                if outcome_state == "SETTLED_KNOWN"
                else "MARKET_EXIT"
                if known
                else None
            ),
            "close_component_legs": (
                [
                    _leg("BUY", "0.008", "110000"),
                    _leg("SELL", "0.003", "110000"),
                ]
                if outcome_state in {"MATURE_KNOWN", "EXITED_KNOWN"}
                else []
            ),
            "native_outcome_economics": {"boundary_valued_net_pnl_usd": ("-10" if known else None)},
            "observation_quality": "GAPPED" if gapped else "CONTINUOUS",
        }
    segments = (
        (
            ShadowCaseSegmentRead(
                sequence=0,
                status=ShadowCaseSegmentStatus.CENSORED_AT_STOP,
                opened={"observation_quality": "GAPPED"},
                closed={"terminal_state": "CENSORED_AT_STOP"},
            ),
        )
        if gapped
        else ()
    )
    return ShadowCaseRead(
        status=(
            ShadowCaseReadStatus.INCOMPLETE_UNCLEAN_EXIT
            if unclean
            else ShadowCaseReadStatus.COMPLETE
            if outcome is not None
            else ShadowCaseReadStatus.OPEN
        ),
        opened=opened,
        first_close=None,
        outcome=outcome,
        segments=segments,
    )


def test_named_cohorts_keep_gapped_known_settlement_without_claiming_continuous_path() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    report = build_v2_case_report(
        (
            _case(
                "9",
                expiry_ms=1_000,
                selection_band="HIGH",
                entry_band="HIGH",
                outcome_state="SETTLED_KNOWN",
                gapped=True,
            ),
        ),
        product=product,
        policies=policies,
    )

    cohorts = report["cohorts"]
    assert isinstance(cohorts, Mapping)
    terminal_economics = cohorts["terminal_economics"]
    continuous_path = cohorts["continuous_path"]
    exit_acquisition = cohorts["exit_acquisition"]
    assert isinstance(terminal_economics, Mapping)
    assert isinstance(continuous_path, Mapping)
    assert isinstance(exit_acquisition, Mapping)
    assert terminal_economics["denominators"]["opened"] == 1
    assert continuous_path["denominators"]["opened"] == 0
    assert exit_acquisition["denominators"]["opened"] == 0
    views = report["views"]
    assert isinstance(views, Mapping)
    gapped_secondary = views["gapped_secondary"]
    assert isinstance(gapped_secondary, Mapping)
    assert gapped_secondary["terminal_method_counts"] == {
        "market_exit": 0,
        "contract_settlement": 1,
        "terminal_unknown": 0,
    }


def test_case_only_report_separates_continuous_and_gapped_denominators() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    report = build_v2_case_report(
        (
            _case(
                "1",
                expiry_ms=1_000,
                selection_band="MID",
                entry_band="HIGH",
                outcome_state="MATURE_KNOWN",
            ),
            _case(
                "2",
                expiry_ms=2_000,
                selection_band="LOW",
                entry_band="LOW",
                outcome_state=None,
            ),
            _case(
                "3",
                expiry_ms=1_000,
                selection_band="MID",
                entry_band="MID",
                outcome_state="MATURE_UNKNOWN",
                gapped=True,
            ),
        ),
        product=product,
        policies=policies,
    )

    assert report["claim_boundary"] == {
        "population": "SCHEMA_V5_CASE_OPENED_AFTER_SUCCESSFUL_PAIRED_REFRESH",
        "interpretation": "CONDITIONAL_DESCRIPTIVE_RESEARCH_ONLY",
        "primary_view": "CONTINUOUS",
        "secondary_view": "GAPPED",
        "pending_view": "PENDING_OPEN",
        "incomplete_view": "INCOMPLETE_UNCLEAN_EXIT",
        "snapshot_mode": "SUPPLIED_CASE_READ_STATES",
        "non_claims": [
            "NOT_UNCONDITIONAL_MARKET_OPPORTUNITY_RATE",
            "NOT_CAUSAL_ALPHA_OR_EXPECTED_PROFIT",
            "NOT_CROSS_ENROLLMENT_ALPHA_COMPARISON",
            "NOT_ORDER_FILL_TRADE_OR_ACCOUNT_PNL",
        ],
    }
    views = report["views"]
    assert isinstance(views, Mapping)
    continuous = views["continuous_primary"]
    assert isinstance(continuous, Mapping)
    assert continuous["denominators"] == {
        "opened": 1,
        "mature_known": 1,
        "mature_unknown": 0,
        "censored": 0,
        "right_censored_without_outcome": 0,
        "pending_open": 0,
        "incomplete_unclean_exit": 0,
    }
    assert continuous["expiry_cluster_count"] == 1
    stressed = continuous["stressed_normalized_outcome"]
    raw = continuous["raw_vwap_fee_recomputed_sensitivity"]
    assert isinstance(stressed, Mapping)
    assert isinstance(raw, Mapping)
    assert stressed["mean"] == "-0.1"
    assert raw["known_count"] == 1
    assert raw["mean"] != "-0.1"
    gapped = views["gapped_secondary"]
    assert isinstance(gapped, Mapping)
    gapped_denominators = gapped["denominators"]
    gapped_stressed = gapped["stressed_normalized_outcome"]
    assert isinstance(gapped_denominators, Mapping)
    assert isinstance(gapped_stressed, Mapping)
    assert gapped_denominators["opened"] == 1
    assert gapped_denominators["mature_unknown"] == 1
    assert gapped_stressed["known_count"] == 0
    pending = views["pending_open"]
    assert isinstance(pending, Mapping)
    assert pending["denominators"] == {
        "opened": 1,
        "mature_known": 0,
        "mature_unknown": 0,
        "censored": 0,
        "right_censored_without_outcome": 0,
        "pending_open": 1,
        "incomplete_unclean_exit": 0,
    }
    by_band = continuous["by_selection_score_band"]
    assert isinstance(by_band, Mapping)
    assert by_band["MID"]["denominators"]["opened"] == 1
    assert by_band["LOW"]["denominators"]["opened"] == 0
    by_enrollment = continuous["by_enrollment_kind"]
    assert isinstance(by_enrollment, Mapping)
    assert by_enrollment["ADMITTED_SHADOW_TRADE"]["denominators"]["opened"] == 1
    assert by_enrollment["RADAR_SCORE_BAND_NO_TRADE_CONTROL"]["denominators"]["opened"] == 0


def test_raw_vwap_sensitivity_recomputes_each_fee_with_product_native_rule() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    report = build_v2_case_report(
        (
            _case(
                "4",
                expiry_ms=1_000,
                selection_band="HIGH",
                entry_band="HIGH",
                outcome_state="MATURE_KNOWN",
            ),
        ),
        product=product,
        policies=policies,
    )
    quantity = Decimal("0.1")
    entry_fee = sum(
        product.native_option_fee(
            native_option_price=price,
            index_price=Decimal("100000"),
            quantity_btc=quantity,
            fee_rate=policies.underwriting.fee_rate_index_fraction,
        )
        for price in (Decimal("0.01"), Decimal("0.004"))
    )
    close_fee = sum(
        product.native_option_fee(
            native_option_price=price,
            index_price=Decimal("110000"),
            quantity_btc=quantity,
            fee_rate=policies.position.fee_rate_index_fraction,
        )
        for price in (Decimal("0.008"), Decimal("0.003"))
    )
    entry_native = (Decimal("0.01") - Decimal("0.004")) * quantity - entry_fee
    close_native = (-Decimal("0.008") + Decimal("0.003")) * quantity - close_fee
    expected = (
        product.valuation(entry_native, index_price=Decimal("100000"))
        + product.valuation(close_native, index_price=Decimal("110000"))
    ) / Decimal("100")

    views = report["views"]
    assert isinstance(views, Mapping)
    continuous = views["continuous_primary"]
    assert isinstance(continuous, Mapping)
    summary = continuous["raw_vwap_fee_recomputed_sensitivity"]
    assert isinstance(summary, Mapping)
    assert Decimal(summary["mean"]) == expected


def test_report_keeps_control_sampling_ratio_and_excludes_unclean_open_from_primary() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    report = build_v2_case_report(
        (
            _case(
                "5",
                expiry_ms=3_000,
                selection_band="LOW",
                entry_band="MID",
                outcome_state=None,
                enrollment_kind="RADAR_SCORE_BAND_NO_TRADE_CONTROL",
                sampling_inclusion=(1, 6),
                unclean=True,
            ),
        ),
        product=product,
        policies=policies,
    )
    views = report["views"]
    assert isinstance(views, Mapping)
    assert views["continuous_primary"]["denominators"]["opened"] == 0
    incomplete = views["incomplete_unclean_exit"]
    row = incomplete["case_rows"][0]
    assert row["enrollment_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL"
    assert row["inclusion_numerator"] == 1
    assert row["inclusion_denominator"] == 6
    assert row["selection_tte_band_id"] == "ultra-short-45m-to-6h"
    assert row["selection_option_type"] == "call"
    assert row["selection_delta_bucket"] == "0.20-0.25"
    assert row["selection_score_coverage"] == "COMPLETE"
    assert row["selected_economic_action"] == "WATCH"
    assert row["refreshed_economic_action"] == "WATCH"
    low = incomplete["by_selection_score_band"]["LOW"]
    assert low["denominators"]["opened"] == 1
    assert low["expiry_cluster_count"] == 1


def test_offline_reader_rejects_relative_or_non_case_members(tmp_path: Path) -> None:
    with pytest.raises(V2CaseReportError, match="must be absolute"):
        load_v2_case_report(Path("cases"), repository=ROOT)

    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "not-a-case").write_text("diagnostic", encoding="utf-8")
    with pytest.raises(V2CaseReportError, match="non-Case member"):
        load_v2_case_report(cases, repository=ROOT)


def test_case_report_cli_exposes_explicit_runtime_active_assertion() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "radar_runtime",
            "report-v2-cases",
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--runtime-active" in completed.stdout


def test_offline_reader_ignores_only_official_case_staging_directories(
    tmp_path: Path,
) -> None:
    valid_cases = tmp_path / "valid-cases"
    valid_cases.mkdir()
    staging_name = ".case-" + "a" * 32 + ".tmp"
    (valid_cases / staging_name).mkdir()

    report = load_v2_case_report(valid_cases, repository=ROOT)
    views = report["views"]
    assert isinstance(views, Mapping)
    continuous = views["continuous_primary"]
    assert isinstance(continuous, Mapping)
    denominators = continuous["denominators"]
    assert isinstance(denominators, Mapping)
    assert denominators["opened"] == 0

    active_report = load_v2_case_report(valid_cases, repository=ROOT, runtime_active=True)
    active_claim = active_report["claim_boundary"]
    assert isinstance(active_claim, Mapping)
    assert active_claim["snapshot_mode"] == "CALLER_ASSERTED_ACTIVE_RUNTIME"

    fake_cases = tmp_path / "fake-cases"
    fake_cases.mkdir()
    (fake_cases / ".case-not-hex.tmp").mkdir()
    with pytest.raises(V2CaseReportError, match="invalid Case identity"):
        load_v2_case_report(fake_cases, repository=ROOT)

    file_cases = tmp_path / "file-cases"
    file_cases.mkdir()
    (file_cases / staging_name).write_text("partial", encoding="utf-8")
    with pytest.raises(V2CaseReportError, match="non-Case member"):
        load_v2_case_report(file_cases, repository=ROOT)


def test_offline_reader_restores_store_owned_bare_hex_case_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    case_id = "sha256:" + "a" * 64
    (cases / case_id.removeprefix("sha256:")).mkdir()
    expected = _case(
        "a",
        expiry_ms=4_000,
        selection_band="MID",
        entry_band="MID",
        outcome_state=None,
        enrollment_kind="RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        sampling_inclusion=(1, 3),
    )
    requested: list[str] = []

    def read_case(
        _store: ShadowCaseStore,
        requested_case_id: str,
        *,
        runtime_active: bool = False,
    ) -> ShadowCaseRead:
        requested.append(requested_case_id)
        assert runtime_active
        return expected

    monkeypatch.setattr(ShadowCaseStore, "read_case", read_case)

    report = load_v2_case_report(cases, repository=ROOT, runtime_active=True)

    assert requested == [case_id]
    views = report["views"]
    assert isinstance(views, Mapping)
    pending = views["pending_open"]
    assert isinstance(pending, Mapping)
    denominators = pending["denominators"]
    assert isinstance(denominators, Mapping)
    assert denominators["pending_open"] == 1


def test_open_control_is_pending_not_an_unclean_exit() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    report = build_v2_case_report(
        (
            _case(
                "6",
                expiry_ms=4_000,
                selection_band="MID",
                entry_band="MID",
                outcome_state=None,
                enrollment_kind="RADAR_SCORE_BAND_NO_TRADE_CONTROL",
                sampling_inclusion=(1, 3),
            ),
        ),
        product=product,
        policies=policies,
    )

    views = report["views"]
    assert isinstance(views, Mapping)
    pending = views["pending_open"]
    incomplete = views["incomplete_unclean_exit"]
    assert isinstance(pending, Mapping)
    assert isinstance(incomplete, Mapping)
    pending_denominators = pending["denominators"]
    incomplete_denominators = incomplete["denominators"]
    assert isinstance(pending_denominators, Mapping)
    assert isinstance(incomplete_denominators, Mapping)
    assert pending_denominators["pending_open"] == 1
    assert incomplete_denominators["opened"] == 0


def test_open_admitted_case_with_unclean_segment_is_not_mislabeled_pending() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    case = _case(
        "7",
        expiry_ms=5_000,
        selection_band="HIGH",
        entry_band="HIGH",
        outcome_state=None,
    )
    case = ShadowCaseRead(
        status=ShadowCaseReadStatus.OPEN,
        opened=case.opened,
        first_close=None,
        outcome=None,
        segments=(
            ShadowCaseSegmentRead(
                sequence=0,
                status=ShadowCaseSegmentStatus.INCOMPLETE_UNCLEAN_EXIT,
                opened={"observation_quality": "CONTINUOUS"},
                closed=None,
            ),
        ),
    )

    report = build_v2_case_report((case,), product=product, policies=policies)

    views = report["views"]
    assert isinstance(views, Mapping)
    incomplete = views["incomplete_unclean_exit"]
    assert isinstance(incomplete, Mapping)
    denominators = incomplete["denominators"]
    assert isinstance(denominators, Mapping)
    assert denominators["incomplete_unclean_exit"] == 1


def test_terminal_outcome_closes_the_final_segment_for_offline_cohorts() -> None:
    product, policies = load_persistent_product_policies(ROOT, INVERSE_BTC)
    case = _case(
        "8",
        expiry_ms=6_000,
        selection_band="HIGH",
        entry_band="HIGH",
        outcome_state="EXITED_KNOWN",
        gapped=True,
    )
    assert case.outcome is not None
    case = ShadowCaseRead(
        status=ShadowCaseReadStatus.COMPLETE,
        opened=case.opened,
        first_close=None,
        outcome={**case.outcome, "outcome_contract_version": 2},
        segments=(
            ShadowCaseSegmentRead(
                sequence=0,
                status=ShadowCaseSegmentStatus.INCOMPLETE_UNCLEAN_EXIT,
                opened={"observation_quality": "GAPPED"},
                closed=None,
            ),
        ),
    )

    report = build_v2_case_report((case,), product=product, policies=policies)

    views = report["views"]
    cohorts = report["cohorts"]
    assert isinstance(views, Mapping)
    assert isinstance(cohorts, Mapping)
    assert views["gapped_secondary"]["denominators"]["opened"] == 1
    assert views["incomplete_unclean_exit"]["denominators"]["opened"] == 0
    assert cohorts["terminal_economics"]["denominators"]["opened"] == 1

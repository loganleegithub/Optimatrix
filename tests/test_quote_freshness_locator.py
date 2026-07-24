from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path
from typing import cast

import pytest
from market_tape import write_capture
from options_domain import OptionQuote, build_surface_summary
from radar_runtime.deribit_public import (
    build_decision_receipt,
    decision_receipt_payload,
    project_events,
)
from radar_runtime.fixture import build_fixture_events, replay_fixture
from radar_runtime.runtime_identity import runtime_source_identity
from short_vol_radar import DecisionFrame, evaluate_radar_evidence

from offline_audits.quote_freshness_locator import (
    COUNTERFACTUAL_LABEL,
    build_quote_freshness_report,
    main,
)


def _call_quotes(*, stale_names: set[str]) -> tuple[OptionQuote, ...]:
    frame, _ = replay_fixture(build_fixture_events())
    lower = next(quote for quote in frame.option_quotes if quote.strike == Decimal("102000"))
    upper = next(quote for quote in frame.option_quotes if quote.strike == Decimal("104000"))
    spare = next(quote for quote in frame.option_quotes if quote.strike == Decimal("96000"))
    middle = replace(
        upper,
        instrument_name="BTC_USDC-20JUL26-103000-C",
        strike=Decimal("103000"),
        bid=Decimal("350"),
        ask=Decimal("360"),
        instrument_source_capture_seq=spare.instrument_source_capture_seq,
        ticker_source_capture_seq=spare.ticker_source_capture_seq,
    )
    quotes = (lower, middle, upper)
    return tuple(
        replace(
            quote,
            quote_age_ms=(6_000 if quote.instrument_name in stale_names else 0),
            fresh=quote.instrument_name not in stale_names,
        )
        for quote in quotes
    )


def _frame(*, stale_names: set[str], one_quote: bool = False) -> DecisionFrame:
    frame, _ = replay_fixture(build_fixture_events())
    quotes = _call_quotes(stale_names=stale_names)
    if one_quote:
        quotes = quotes[:1]
    assert frame.market_as_of is not None
    stale = any(not quote.fresh for quote in quotes)
    return replace(
        frame,
        option_quotes=quotes,
        surface=build_surface_summary(quotes, as_of=frame.market_as_of),
        complete=not stale,
        completeness_reasons=(("OPTION_UNIVERSE_QUOTES_STALE",) if stale else ()),
    )


def _report(frame: DecisionFrame) -> dict[str, object]:
    return build_quote_freshness_report(
        frame,
        evaluate_radar_evidence(frame),
        receipt_binding_verified=True,
        capture_digest="capture-digest",
        decision_receipt_digest="decision-receipt-digest",
    )


def _counterfactual(report: dict[str, object]) -> dict[str, object]:
    value = report["counterfactual"]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_one_stale_leg_locates_multiple_verticals_and_configured_horizons() -> None:
    stale_name = "BTC_USDC-20JUL26-103000-C"

    report = _report(_frame(stale_names={stale_name}))

    observed = report["authoritative_observed_behavior"]
    assert isinstance(observed, dict)
    assert observed["global_universe_fail_closed"] is True
    assert observed["global_fail_closed_reason"] == "OPTION_UNIVERSE_QUOTES_STALE"
    stale = report["stale_instruments"]
    assert isinstance(stale, list)
    assert len(stale) == 1
    located = stale[0]
    assert located["instrument_name"] == stale_name
    assert located["quote_age_ms"] == 6_000
    assert located["freshness_limit_ms"] == 5_000
    assert located["affected_vertical_ids"] == [
        "vertical:call:BTC_USDC-20JUL26-102000-C:BTC_USDC-20JUL26-103000-C",
        "vertical:call:BTC_USDC-20JUL26-103000-C:BTC_USDC-20JUL26-104000-C",
    ]
    assert located["affected_vertical_count"] == 2
    assert located["affected_configured_horizons_seconds"] == [1_800, 3_600, 7_200, 14_400]
    assert located["affected_vertical_horizon_count"] == 8
    counterfactual = _counterfactual(report)
    assert counterfactual["affected_structural_vertical_count"] == 2
    assert counterfactual["affected_vertical_horizon_count"] == 8
    assert counterfactual["configured_horizon_count"] == 4


def test_multiple_stale_legs_deduplicate_global_vertical_impact() -> None:
    report = _report(
        _frame(
            stale_names={
                "BTC_USDC-20JUL26-102000-C",
                "BTC_USDC-20JUL26-104000-C",
            }
        )
    )

    stale = report["stale_instruments"]
    assert isinstance(stale, list)
    assert sum(cast(int, item["affected_vertical_count"]) for item in stale) == 4
    counterfactual = _counterfactual(report)
    assert counterfactual["structural_vertical_count"] == 3
    assert counterfactual["affected_structural_vertical_count"] == 3
    assert counterfactual["affected_vertical_horizon_count"] == 12


def test_no_stale_quote_reports_zero_localized_impact() -> None:
    report = _report(_frame(stale_names=set()))

    assert report["analysis_availability"] == "AVAILABLE"
    assert report["stale_instruments"] == []
    observed = report["authoritative_observed_behavior"]
    assert isinstance(observed, dict)
    assert observed["global_universe_fail_closed"] is False
    counterfactual = _counterfactual(report)
    assert counterfactual["affected_structural_vertical_count"] == 0
    assert counterfactual["affected_vertical_horizon_count"] == 0
    assert counterfactual["affected_vertical_rate"] == "0"


def test_zero_structural_denominator_keeps_rates_null() -> None:
    report = _report(
        _frame(
            stale_names={"BTC_USDC-20JUL26-102000-C"},
            one_quote=True,
        )
    )

    counterfactual = _counterfactual(report)
    assert counterfactual["structural_vertical_count"] == 0
    assert counterfactual["affected_structural_vertical_count"] == 0
    assert counterfactual["affected_vertical_rate"] is None
    assert counterfactual["affected_vertical_horizon_rate"] is None


def test_counterfactual_rate_rendering_ignores_global_decimal_context() -> None:
    frame = _frame(stale_names={"BTC_USDC-20JUL26-103000-C"})
    baseline = _report(frame)

    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        changed_context = _report(frame)

    assert changed_context == baseline
    assert _counterfactual(baseline)["affected_vertical_rate"] == (
        "0.6666666666666666666666666666666667"
    )


def test_incomplete_or_noncurrent_universe_keeps_denominators_and_rates_unknown() -> None:
    frame = _frame(stale_names=set())
    unknown_catalog = replace(
        frame,
        catalog_scope=None,
        catalog_snapshot_capture_seq=None,
        catalog_source_at=None,
        catalog_age_ms=None,
        catalog_instrument_count=None,
        catalog_instrument_names_digest=None,
        catalog_generation_id=None,
        catalog_metadata_set_digest=None,
        catalog_instrument_source_capture_seqs=(),
        catalog_generation_complete=False,
        complete=False,
        completeness_reasons=("CATALOG_SNAPSHOT_UNKNOWN",),
    )
    stale_catalog = replace(
        frame,
        catalog_age_ms=361_000,
        complete=False,
        completeness_reasons=("CATALOG_SNAPSHOT_STALE",),
    )
    incomplete_universe = replace(
        frame,
        complete=False,
        completeness_reasons=("OPTION_UNIVERSE_QUOTES_INCOMPLETE",),
    )

    for incomplete in (unknown_catalog, stale_catalog, incomplete_universe):
        report = _report(incomplete)
        counterfactual = _counterfactual(report)

        assert report["analysis_availability"] == "UNKNOWN"
        assert report["stale_instruments"] is None
        assert counterfactual["structural_vertical_count"] is None
        assert counterfactual["structural_vertical_horizon_count"] is None
        assert counterfactual["affected_structural_vertical_count"] is None
        assert counterfactual["affected_vertical_horizon_count"] is None
        assert counterfactual["affected_vertical_rate"] is None
        assert counterfactual["affected_vertical_horizon_rate"] is None


def test_missing_receipt_binding_and_mismatched_frame_facts_fail_closed() -> None:
    frame = _frame(stale_names={"BTC_USDC-20JUL26-103000-C"})
    evaluation = evaluate_radar_evidence(frame)

    missing_receipt = build_quote_freshness_report(
        frame,
        evaluation,
        receipt_binding_verified=False,
        capture_digest="capture-digest",
        decision_receipt_digest=None,
    )
    drifted = build_quote_freshness_report(
        frame,
        replace(evaluation, option_quote_set_digest="drifted"),
        receipt_binding_verified=True,
        capture_digest="capture-digest",
        decision_receipt_digest="decision-receipt-digest",
    )

    assert missing_receipt["analysis_availability"] == "UNKNOWN"
    assert missing_receipt["authoritative_observed_behavior"] is None
    assert missing_receipt["stale_instruments"] is None
    missing_reasons = missing_receipt["unknown_reasons"]
    assert isinstance(missing_reasons, list)
    assert "DECISION_RECEIPT_BINDING_UNVERIFIED" in missing_reasons
    assert drifted["analysis_availability"] == "UNKNOWN"
    drift_reasons = drifted["unknown_reasons"]
    assert isinstance(drift_reasons, list)
    assert "FRAME_EVALUATION_BINDING_UNKNOWN" in drift_reasons
    assert _counterfactual(drifted)["affected_structural_vertical_count"] is None


def test_counterfactual_is_explicitly_non_authoritative_and_cannot_feed_outputs() -> None:
    counterfactual = _counterfactual(_report(_frame(stale_names={"BTC_USDC-20JUL26-103000-C"})))

    assert counterfactual["label"] == COUNTERFACTUAL_LABEL
    assert counterfactual["authoritative"] is False
    assert counterfactual["counterfactual_decision_action"] is None
    assert counterfactual["counterfactual_policy_value"] is None
    assert counterfactual["counterfactual_outcome"] is None
    for surface in (
        "feeds_decision",
        "feeds_policy",
        "feeds_outcome",
        "feeds_run_receipt",
        "feeds_qualification",
        "feeds_candidate_selection",
    ):
        assert counterfactual[surface] is False


def _bound_cli_inputs(tmp_path: Path) -> tuple[Path, Path]:
    events = build_fixture_events()
    capture = tmp_path / "inputs" / "capture"
    manifest = write_capture(capture, events, complete=True)
    projection = project_events(events)
    receipt = decision_receipt_payload(
        build_decision_receipt(
            manifest,
            projection,
            source_identity=runtime_source_identity(require_clean=True),
        )
    )
    decision = tmp_path / "decision-input" / "decision.json"
    decision.parent.mkdir(parents=True)
    decision.write_text(json.dumps(receipt), encoding="utf-8")
    return capture, decision


def test_cli_requires_exact_decision_receipt_binding(tmp_path: Path) -> None:
    capture, decision = _bound_cli_inputs(tmp_path)
    output = tmp_path / "output" / "report.json"

    assert (
        main(
            [
                str(capture),
                "--decision",
                str(decision),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    saved: object = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)
    assert saved["analysis_availability"] == "AVAILABLE"
    assert saved["receipt_binding_verified"] is True


def test_cli_rejects_output_inside_capture_or_decision_input_tree(tmp_path: Path) -> None:
    capture, decision = _bound_cli_inputs(tmp_path)
    forbidden_outputs = (
        capture / "report.json",
        decision.parent / "nested" / "report.json",
    )

    for output in forbidden_outputs:
        with pytest.raises(ValueError, match="separate from sealed input"):
            main(
                [
                    str(capture),
                    "--decision",
                    str(decision),
                    "--output",
                    str(output),
                ]
            )
        assert not output.exists()

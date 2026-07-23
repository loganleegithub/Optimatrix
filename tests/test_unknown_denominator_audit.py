from __future__ import annotations

from decimal import localcontext

from radar_runtime.shadow_bundle import _build_unknown_denominator_audit


def _receipt(
    *,
    complete: bool,
    blockers: list[str],
    option_quotes: int,
    fresh_quotes: int,
    catalog_instruments: int,
    assessment_count: int,
    assessment_opportunities: int,
    assessment_blockers: list[tuple[str, int]],
) -> dict[str, object]:
    return {
        "readiness": {
            "frame_complete": complete,
            "frame_incomplete_reasons": blockers,
            "catalog": {"instrument_count": catalog_instruments},
            "quotes": {
                "option_quote_count": option_quotes,
                "fresh_quote_count": fresh_quotes,
                "incomplete_reasons": blockers,
            },
        },
        "evaluation": {
            "assessment_count": assessment_count,
            "assessment_opportunity_count": assessment_opportunities,
            "assessment_unavailable_count": assessment_opportunities - assessment_count,
            "assessment_unavailable_reason_counts": [list(item) for item in assessment_blockers],
        },
    }


def test_unknown_denominator_audit_preserves_sole_and_co_blockers() -> None:
    receipt_0 = _receipt(
        complete=False,
        blockers=["OPTION_UNIVERSE_QUOTES_STALE"],
        option_quotes=2,
        fresh_quotes=1,
        catalog_instruments=3,
        assessment_count=0,
        assessment_opportunities=4,
        assessment_blockers=[("OPTION_UNIVERSE_QUOTES_STALE", 4)],
    )
    receipt_1 = _receipt(
        complete=False,
        blockers=["CATALOG_GENERATION_STALE", "SCHEDULED_BLOCK_UNKNOWN"],
        option_quotes=3,
        fresh_quotes=3,
        catalog_instruments=5,
        assessment_count=2,
        assessment_opportunities=4,
        assessment_blockers=[("REQUIRED_PATH_WINDOW_UNKNOWN", 2)],
    )
    receipt_2 = _receipt(
        complete=True,
        blockers=[],
        option_quotes=4,
        fresh_quotes=4,
        catalog_instruments=5,
        assessment_count=4,
        assessment_opportunities=4,
        assessment_blockers=[],
    )
    receipt_0["receipt_digest"] = "decision-0"
    receipt_1["receipt_digest"] = "decision-1"
    receipt_2["receipt_digest"] = "decision-2"
    run_receipt: dict[str, object] = {
        "run_id": "audit-run",
        "run_receipt_digest": "run-digest",
        "decision_receipt_digests": ["decision-0", "decision-1", "decision-2", None],
        "opportunity_summaries": [
            {
                "slot_index": 0,
                "event_backed": True,
                "admission_reason": "DECISION_OR_BINDING_INCOMPLETE",
            },
            {
                "slot_index": 1,
                "event_backed": True,
                "admission_reason": "DECISION_OR_BINDING_INCOMPLETE",
            },
            {
                "slot_index": 2,
                "event_backed": True,
                "admission_reason": "DECISION_ABSTAIN",
            },
            {
                "slot_index": 3,
                "event_backed": False,
                "admission_reason": "NO_CANONICAL_EVENT_IN_SLOT",
            },
        ],
    }

    audit = _build_unknown_denominator_audit(
        run_receipt,
        {
            0: receipt_0,
            1: receipt_1,
            2: receipt_2,
        },
    )
    slots = audit["slots"]
    assert isinstance(slots, list)
    assert slots[0]["sole_blocker"] == "OPTION_UNIVERSE_QUOTES_STALE"
    assert slots[0]["co_blockers"] == []
    assert slots[0]["quote_coverage"]["rate"] == "1"
    assert slots[0]["assessment_availability"]["rate"] == "0"
    assert slots[1]["sole_blocker"] is None
    assert slots[1]["co_blockers"] == [
        "CATALOG_GENERATION_STALE",
        "REQUIRED_PATH_WINDOW_UNKNOWN",
        "SCHEDULED_BLOCK_UNKNOWN",
    ]
    assert slots[1]["quote_coverage"]["rate"] == "0.75"
    assert slots[2]["availability"] == "AVAILABLE"
    assert slots[3]["sole_blocker"] == "NO_CANONICAL_EVENT_IN_SLOT"
    assert slots[3]["quote_coverage"]["status"] == "UNKNOWN_DENOMINATOR"
    assert slots[3]["assessment_availability"]["rate"] is None
    assert audit["availability_rate"] == {
        "numerator": 1,
        "denominator": 4,
        "rate": "0.25",
        "status": "DEFINED",
    }


def test_unknown_denominator_audit_keeps_zero_denominators_null() -> None:
    run_receipt: dict[str, object] = {
        "run_id": "zero-denominator-run",
        "run_receipt_digest": "run-digest",
        "decision_receipt_digests": ["decision-0"],
        "opportunity_summaries": [
            {
                "slot_index": 0,
                "event_backed": True,
                "admission_reason": "DECISION_ABSTAIN",
            }
        ],
    }
    receipt = _receipt(
        complete=True,
        blockers=[],
        option_quotes=0,
        fresh_quotes=0,
        catalog_instruments=0,
        assessment_count=0,
        assessment_opportunities=0,
        assessment_blockers=[],
    )
    receipt["receipt_digest"] = "decision-0"

    audit = _build_unknown_denominator_audit(run_receipt, {0: receipt})
    slots = audit["slots"]
    assert isinstance(slots, list)
    assert slots[0]["quote_coverage"] == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
        "status": "UNDEFINED_ZERO_DENOMINATOR",
    }
    assert slots[0]["assessment_availability"] == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
        "status": "UNDEFINED_ZERO_DENOMINATOR",
    }

    empty = _build_unknown_denominator_audit(
        {
            "run_id": "empty",
            "run_receipt_digest": "empty-digest",
            "decision_receipt_digests": [],
            "opportunity_summaries": [],
        },
        {},
    )
    assert empty["availability_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
        "status": "UNDEFINED_ZERO_DENOMINATOR",
    }


def test_unknown_denominator_audit_rate_rendering_ignores_global_decimal_precision() -> None:
    receipt = _receipt(
        complete=True,
        blockers=[],
        option_quotes=1,
        fresh_quotes=1,
        catalog_instruments=4,
        assessment_count=1,
        assessment_opportunities=3,
        assessment_blockers=[("UNAVAILABLE_STRUCTURE", 2)],
    )
    receipt["receipt_digest"] = "decision-0"
    run_receipt: dict[str, object] = {
        "run_id": "precision-run",
        "run_receipt_digest": "run-digest",
        "decision_receipt_digests": ["decision-0"],
        "opportunity_summaries": [
            {
                "slot_index": 0,
                "event_backed": True,
                "admission_reason": "DECISION_ABSTAIN",
            }
        ],
    }

    expected = _build_unknown_denominator_audit(run_receipt, {0: receipt})
    with localcontext() as context:
        context.prec = 6
        actual = _build_unknown_denominator_audit(run_receipt, {0: receipt})

    assert actual == expected
    slots = actual["slots"]
    assert isinstance(slots, list)
    assert slots[0]["quote_coverage"]["rate"] == ("0.3333333333333333333333333333333333")

"""Locate stale option-quote impact without changing the authoritative Decision."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import cast

from market_tape import OptionKind, canonical_digest, read_capture
from options_domain import OptionQuote
from radar_runtime.deribit_public import project_events, replay_payload
from short_vol_radar import (
    DecisionEvaluation,
    DecisionFrame,
    DecisionInputContract,
    RadarPolicy,
)

REPORT_TYPE = "NON_AUTHORITATIVE_QUOTE_FRESHNESS_LOCATOR_REPORT"
COUNTERFACTUAL_LABEL = "NON_AUTHORITATIVE_COUNTERFACTUAL"
GLOBAL_STALE_REASON = "OPTION_UNIVERSE_QUOTES_STALE"
STRUCTURAL_UNIVERSE_REASONS = frozenset(
    {
        "CATALOG_SNAPSHOT_UNKNOWN",
        "CATALOG_SNAPSHOT_STALE",
        "OPTION_UNIVERSE_QUOTES_INCOMPLETE",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only locator for stale option-quote structural impact"
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _load_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(dict[str, object], value)


def _path_contains(tree: Path, target: Path) -> bool:
    return target == tree or tree in target.parents


def _require_separate_output(
    *,
    capture: Path,
    decision: Path | None,
    output: Path,
) -> None:
    output_path = output.resolve()
    input_trees = [capture.resolve()]
    if decision is not None:
        input_trees.append(decision.resolve().parent)
    if any(
        _path_contains(tree, output_path) or _path_contains(output_path, tree)
        for tree in input_trees
    ):
        raise ValueError("quote freshness output must be separate from sealed input trees")


def _rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return str(Decimal(numerator) / Decimal(denominator))


def _quantity_valid(quote: OptionQuote, quantity: Decimal) -> bool:
    return (
        quote.min_trade_amount > 0
        and quote.amount_step > 0
        and quantity >= quote.min_trade_amount
        and quantity % quote.amount_step == 0
    )


def _topology_eligible(
    quote: OptionQuote,
    *,
    reference_price: Decimal,
    policy: RadarPolicy,
) -> bool:
    is_otm = (
        quote.strike > reference_price
        if quote.option_kind is OptionKind.CALL
        else quote.strike < reference_price
    )
    return (
        policy.minimum_tte_seconds <= quote.tte_seconds <= policy.maximum_tte_seconds
        and is_otm
        and _quantity_valid(quote, policy.quantity)
    )


def _is_vertical(short_quote: OptionQuote, long_quote: OptionQuote) -> bool:
    if (
        short_quote.instrument_name == long_quote.instrument_name
        or short_quote.expiry != long_quote.expiry
        or short_quote.option_kind is not long_quote.option_kind
        or short_quote.contract_size != long_quote.contract_size
    ):
        return False
    if short_quote.option_kind is OptionKind.CALL:
        return long_quote.strike > short_quote.strike
    return long_quote.strike < short_quote.strike


def _vertical_id(short_quote: OptionQuote, long_quote: OptionQuote) -> str:
    return (
        f"vertical:{short_quote.option_kind.value.lower()}:"
        f"{short_quote.instrument_name}:{long_quote.instrument_name}"
    )


def _unknown_report(
    reasons: tuple[str, ...],
    *,
    capture_digest: str | None,
    decision_receipt_digest: str | None,
) -> dict[str, object]:
    return {
        "report_type": REPORT_TYPE,
        "analysis_mode": "READ_ONLY_OFFLINE",
        "analysis_availability": "UNKNOWN",
        "unknown_reasons": list(reasons),
        "capture_digest": capture_digest,
        "decision_receipt_digest": decision_receipt_digest,
        "receipt_binding_verified": False,
        "authoritative_observed_behavior": None,
        "stale_instruments": None,
        "counterfactual": {
            "label": COUNTERFACTUAL_LABEL,
            "authoritative": False,
            "structural_vertical_count": None,
            "structural_vertical_horizon_count": None,
            "affected_structural_vertical_count": None,
            "affected_vertical_horizon_count": None,
            "unaffected_structural_vertical_count": None,
            "unaffected_vertical_horizon_count": None,
            "affected_vertical_rate": None,
            "affected_vertical_horizon_rate": None,
            "feeds_decision": False,
            "feeds_policy": False,
            "feeds_outcome": False,
            "feeds_run_receipt": False,
            "feeds_qualification": False,
            "feeds_candidate_selection": False,
        },
    }


def build_quote_freshness_report(
    frame: DecisionFrame,
    evaluation: DecisionEvaluation,
    *,
    receipt_binding_verified: bool,
    capture_digest: str | None,
    decision_receipt_digest: str | None,
) -> dict[str, object]:
    """Build a read-only report from an exact receipt-bound final DecisionFrame."""

    policy = RadarPolicy()
    input_contract = DecisionInputContract()
    reasons: list[str] = []
    if not receipt_binding_verified:
        reasons.append("DECISION_RECEIPT_BINDING_UNVERIFIED")
    if not capture_digest:
        reasons.append("CAPTURE_IDENTITY_UNKNOWN")
    if not decision_receipt_digest:
        reasons.append("DECISION_RECEIPT_IDENTITY_UNKNOWN")
    if frame.reference_price is None or frame.reference_price <= 0:
        reasons.append("REFERENCE_PRICE_UNKNOWN")
    if (
        frame.input_contract_id != input_contract.contract_id
        or frame.input_contract_digest != input_contract.digest
    ):
        reasons.append("DECISION_INPUT_CONTRACT_IDENTITY_UNKNOWN")
    if (
        not frame.catalog_generation_complete
        or frame.catalog_scope != input_contract.catalog_scope
        or frame.catalog_age_ms is None
        or frame.catalog_age_ms > input_contract.catalog_max_age_ms
        or any(reason in STRUCTURAL_UNIVERSE_REASONS for reason in frame.completeness_reasons)
    ):
        reasons.append("STRUCTURAL_OPTION_UNIVERSE_UNKNOWN")
    if (
        evaluation.decision.frame_capture_seq != frame.as_of_capture_seq
        or evaluation.decision.frame_digest != frame.digest
        or evaluation.option_quote_count != len(frame.option_quotes)
        or evaluation.option_quote_set_digest != canonical_digest(frame.option_quotes)
    ):
        reasons.append("FRAME_EVALUATION_BINDING_UNKNOWN")
    quote_names = tuple(quote.instrument_name for quote in frame.option_quotes)
    if len(set(quote_names)) != len(quote_names):
        reasons.append("OPTION_QUOTE_IDENTITY_CONFLICT")
    lineage = set(frame.source_capture_seqs)
    if any(
        not set(quote.source_capture_seqs).issubset(lineage)
        or any(source_seq > frame.as_of_capture_seq for source_seq in quote.source_capture_seqs)
        for quote in frame.option_quotes
    ):
        reasons.append("OPTION_QUOTE_LINEAGE_UNKNOWN")
    if any(
        quote.fresh is not (quote.quote_age_ms <= input_contract.option_freshness_ms)
        for quote in frame.option_quotes
    ):
        reasons.append("OPTION_QUOTE_FRESHNESS_FACT_INCONSISTENT")
    stale_quotes = tuple(quote for quote in frame.option_quotes if not quote.fresh)
    global_stale_observed = GLOBAL_STALE_REASON in frame.completeness_reasons
    if global_stale_observed is not bool(stale_quotes) or (
        global_stale_observed and frame.complete
    ):
        reasons.append("AUTHORITATIVE_STALE_BEHAVIOR_INCONSISTENT")
    if reasons:
        return _unknown_report(
            tuple(sorted(set(reasons))),
            capture_digest=capture_digest,
            decision_receipt_digest=decision_receipt_digest,
        )

    reference_price = frame.reference_price
    if reference_price is None:
        raise AssertionError("reference price was checked above")
    eligible = tuple(
        quote
        for quote in frame.option_quotes
        if _topology_eligible(
            quote,
            reference_price=reference_price,
            policy=policy,
        )
    )
    vertical_legs: dict[str, tuple[OptionQuote, OptionQuote]] = {}
    for short_quote in eligible:
        for long_quote in eligible:
            if _is_vertical(short_quote, long_quote):
                vertical_legs[_vertical_id(short_quote, long_quote)] = (
                    short_quote,
                    long_quote,
                )
    all_vertical_ids = tuple(sorted(vertical_legs))
    affected_vertical_ids = tuple(
        vertical_id
        for vertical_id in all_vertical_ids
        if not vertical_legs[vertical_id][0].fresh or not vertical_legs[vertical_id][1].fresh
    )
    affected_set = set(affected_vertical_ids)
    unaffected_vertical_ids = tuple(
        vertical_id for vertical_id in all_vertical_ids if vertical_id not in affected_set
    )
    horizon_count = len(policy.horizons_seconds)
    structural_opportunity_count = len(all_vertical_ids) * horizon_count
    affected_opportunity_count = len(affected_vertical_ids) * horizon_count
    affected_by_instrument = {
        quote.instrument_name: tuple(
            vertical_id
            for vertical_id in affected_vertical_ids
            if quote.instrument_name
            in {
                vertical_legs[vertical_id][0].instrument_name,
                vertical_legs[vertical_id][1].instrument_name,
            }
        )
        for quote in stale_quotes
    }
    stale_instruments = [
        {
            "instrument_name": quote.instrument_name,
            "quote_age_ms": quote.quote_age_ms,
            "freshness_limit_ms": input_contract.option_freshness_ms,
            "instrument_source_capture_seq": quote.instrument_source_capture_seq,
            "ticker_source_capture_seq": quote.ticker_source_capture_seq,
            "affected_vertical_ids": list(affected_by_instrument[quote.instrument_name]),
            "affected_vertical_count": len(affected_by_instrument[quote.instrument_name]),
            "affected_configured_horizons_seconds": (
                list(policy.horizons_seconds)
                if affected_by_instrument[quote.instrument_name]
                else []
            ),
            "affected_vertical_horizon_count": (
                len(affected_by_instrument[quote.instrument_name]) * horizon_count
            ),
        }
        for quote in sorted(stale_quotes, key=lambda item: item.instrument_name)
    ]
    fresh_quote_count = sum(quote.fresh for quote in frame.option_quotes)
    return {
        "report_type": REPORT_TYPE,
        "analysis_mode": "READ_ONLY_OFFLINE",
        "analysis_availability": "AVAILABLE",
        "unknown_reasons": [],
        "capture_digest": capture_digest,
        "decision_receipt_digest": decision_receipt_digest,
        "receipt_binding_verified": True,
        "frame_capture_seq": frame.as_of_capture_seq,
        "frame_digest": frame.digest,
        "input_contract_id": frame.input_contract_id,
        "input_contract_digest": frame.input_contract_digest,
        "policy_id": policy.policy_id,
        "policy_digest": policy.digest,
        "authoritative_observed_behavior": {
            "label": "AUTHORITATIVE_OBSERVED_BEHAVIOR",
            "global_universe_fail_closed": global_stale_observed,
            "global_fail_closed_reason": (GLOBAL_STALE_REASON if global_stale_observed else None),
            "frame_complete": frame.complete,
            "frame_incomplete_reasons": list(frame.completeness_reasons),
            "decision_action": evaluation.decision.action.value,
            "decision_reason": evaluation.decision.reason,
            "option_quote_count": evaluation.option_quote_count,
            "fresh_quote_count": fresh_quote_count,
            "stale_quote_count": len(stale_quotes),
            "executable_structure_count": evaluation.executable_structure_count,
            "assessment_opportunity_count": evaluation.assessment_opportunity_count,
            "assessment_count": evaluation.assessment_count,
            "assessment_unavailable_count": evaluation.assessment_unavailable_count,
        },
        "stale_instruments": stale_instruments,
        "counterfactual": {
            "label": COUNTERFACTUAL_LABEL,
            "authoritative": False,
            "assumption": ("ONLY_STRUCTURALLY_AFFECTED_VERTICAL_HORIZON_OPPORTUNITIES_UNAVAILABLE"),
            "structural_vertical_definition": (
                "SAME_EXPIRY_SAME_SIDE_1X1_OTM_TTE_AND_QUANTITY_VALID"
            ),
            "configured_horizons_seconds": list(policy.horizons_seconds),
            "configured_horizon_count": horizon_count,
            "structural_vertical_count": len(all_vertical_ids),
            "structural_vertical_horizon_count": structural_opportunity_count,
            "affected_structural_vertical_ids": list(affected_vertical_ids),
            "affected_structural_vertical_count": len(affected_vertical_ids),
            "affected_vertical_horizon_count": affected_opportunity_count,
            "unaffected_structural_vertical_ids": list(unaffected_vertical_ids),
            "unaffected_structural_vertical_count": len(unaffected_vertical_ids),
            "unaffected_vertical_horizon_count": len(unaffected_vertical_ids) * horizon_count,
            "affected_vertical_rate": _rate(
                len(affected_vertical_ids),
                len(all_vertical_ids),
            ),
            "affected_vertical_horizon_rate": _rate(
                affected_opportunity_count,
                structural_opportunity_count,
            ),
            "unaffected_executable_or_assessable": "UNKNOWN",
            "counterfactual_decision_action": None,
            "counterfactual_policy_value": None,
            "counterfactual_outcome": None,
            "feeds_decision": False,
            "feeds_policy": False,
            "feeds_outcome": False,
            "feeds_run_receipt": False,
            "feeds_qualification": False,
            "feeds_candidate_selection": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    _require_separate_output(
        capture=arguments.capture,
        decision=arguments.decision,
        output=arguments.output,
    )
    manifest, events = read_capture(arguments.capture)
    projection = project_events(events)
    receipt: Mapping[str, object] | None = None
    binding_verified = False
    receipt_digest: str | None = None
    if arguments.decision is not None:
        receipt = _load_object(arguments.decision)
        raw_digest = receipt.get("receipt_digest")
        receipt_digest = raw_digest if isinstance(raw_digest, str) and raw_digest else None
        try:
            replay = replay_payload(
                manifest,
                events,
                decision_receipt=receipt,
            )
        except (RuntimeError, ValueError):
            binding_verified = False
        else:
            binding_verified = replay.get("decision_receipt_binding_verified") is True
    report = build_quote_freshness_report(
        projection.frame,
        projection.evaluation,
        receipt_binding_verified=binding_verified,
        capture_digest=manifest.content_sha256,
        decision_receipt_digest=receipt_digest,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

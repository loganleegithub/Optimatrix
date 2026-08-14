from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.decision import DecisionRecord
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.identity import canonical_identity
from optimatrix.lifecycle import evaluate_shadow_entry, open_trade_case
from optimatrix.market import OptionQuote, PriceLevel
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.risk import ShadowCapacity
from optimatrix.route import (
    RouteEvidenceKind,
    RouteEvidenceStatus,
    ShadowRouteEvidence,
    component_synthetic_route_evidence,
)
from optimatrix.scenarios import base_chain, current_expiry, market_context


def _instrument_names(quotes: tuple[OptionQuote, ...]) -> tuple[str, str, str, str]:
    if len(quotes) != 4:
        raise ValueError("route fixture requires four quotes")
    return (
        quotes[0].instrument_name,
        quotes[1].instrument_name,
        quotes[2].instrument_name,
        quotes[3].instrument_name,
    )


def _candidate(policy, tmp_path):
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item
        for item in engine.decision_windows(at=observed_at)
        if item.starts_at <= observed_at < item.ends_at
    )
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(observed_at), observed_at=observed_at),
        context=market_context(observed_at),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(tmp_path / "ledger"),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    return engine, assessment.record


def test_decision_and_entry_freeze_distinct_component_route_evidence(policy, tmp_path) -> None:
    engine, record = _candidate(policy, tmp_path)
    decision_route = record.route_evidence
    assert decision_route is not None
    assert decision_route.kind is RouteEvidenceKind.COMPONENT_SYNTHETIC_ESTIMATE
    assert decision_route.status is RouteEvidenceStatus.EVALUABLE
    assert decision_route.observation_id == record.observation_id
    assert decision_route.evaluated_at == record.known_at
    assert decision_route.target_amount == Decimal("0.1")
    assert tuple(leg.ratio for leg in decision_route.legs) == (
        Decimal(1),
        Decimal(-1),
        Decimal(-1),
        Decimal(1),
    )
    assert all(leg.requested_amount == decision_route.target_amount for leg in decision_route.legs)
    assert all(leg.depth_coverage == 1 for leg in decision_route.legs)
    assert DecisionRecord.from_object(record.as_object()) == record

    case = open_trade_case(record, policy)
    assert case.decision_route_evidence == decision_route
    entry_at = record.known_at + timedelta(seconds=30)
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(entry_at), observed_at=entry_at),
        context=market_context(entry_at),
    )
    entered, evaluation = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )
    entry_route = evaluation.route_evidence
    assert entry_route.identity != decision_route.identity
    assert entry_route.kind is RouteEvidenceKind.COMPONENT_SYNTHETIC_ESTIMATE
    assert entry_route.status is RouteEvidenceStatus.EVALUABLE
    assert entry_route.selected_structure_id == decision_route.selected_structure_id
    assert entry_route.observation_id == observation.identity
    assert entry_route.evaluated_at == observation.known_at
    assert entered.entry_reunderwriting is not None
    assert entered.entry_reunderwriting.route_evidence == entry_route


def test_component_route_statuses_distinguish_unknown_from_complete_insufficient_depth(
    policy,
) -> None:
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)
    names = _instrument_names(quotes)
    structure_id = canonical_identity("TestFrozenStructure", names)
    unknown = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=structure_id,
        evaluated_at=observed_at,
        target_amount=Decimal("0.1"),
        instrument_names=names,
        observation_id=None,
        observed_at=None,
        observation_known_at=None,
        quotes=None,
        pricing=None,
        unknown_reason="NO_CAUSAL_COMPONENT_CUT",
    )
    assert unknown.status is RouteEvidenceStatus.UNKNOWN
    assert unknown.reason == "NO_CAUSAL_COMPONENT_CUT"
    assert all(leg.depth_coverage is None for leg in unknown.legs)
    assert ShadowRouteEvidence.from_object(unknown.as_object()) == unknown

    shallow_quotes = tuple(
        replace(quote, bid=(PriceLevel(quote.bid[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P")
        else quote
        for quote in quotes
    )
    insufficient = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=structure_id,
        evaluated_at=observed_at,
        target_amount=Decimal("0.1"),
        instrument_names=names,
        observation_id=canonical_identity("TestObservation", observed_at),
        observed_at=observed_at,
        observation_known_at=observed_at,
        quotes=shallow_quotes,
        pricing=None,
    )
    assert insufficient.status is RouteEvidenceStatus.NOT_EVALUABLE
    assert insufficient.reason == "FULL_TARGET_COMPONENT_ESTIMATE_UNAVAILABLE"
    assert insufficient.legs[1].depth_coverage == Decimal("0.5")
    assert ShadowRouteEvidence.from_object(insufficient.as_object()) == insufficient


@pytest.mark.parametrize(
    ("foreign_field", "value"),
    (
        ("combo_instrument_name", "BTC-COMBO"),
        ("combo_book_quote", "0.001"),
        ("rfq_id", "rfq-1"),
        ("order_id", "order-1"),
        ("trade_id", "trade-1"),
        ("filled_amount", "0.1"),
        ("account_id", "account-1"),
        ("executable_liquidity", True),
        ("fill_probability", "1"),
    ),
)
def test_b3_route_codec_rejects_execution_layer_claims(
    policy,
    foreign_field,
    value,
) -> None:
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)
    evidence = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=canonical_identity("TestFrozenStructure", "codec"),
        evaluated_at=observed_at,
        target_amount=Decimal("0.1"),
        instrument_names=_instrument_names(quotes),
        observation_id=None,
        observed_at=None,
        observation_known_at=None,
        quotes=None,
        pricing=None,
        unknown_reason="NO_CAUSAL_COMPONENT_CUT",
    )
    payload = evidence.as_object()
    payload[foreign_field] = value
    with pytest.raises(ValueError, match="fields do not match"):
        ShadowRouteEvidence.from_object(payload)


@pytest.mark.parametrize(
    "kind",
    (
        RouteEvidenceKind.COMBO_BOOK_QUOTE,
        RouteEvidenceKind.RFQ,
        RouteEvidenceKind.ACTUAL_FILL,
    ),
)
def test_b3_route_object_rejects_non_component_truth_kinds(policy, kind) -> None:
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)
    evidence = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=canonical_identity("TestFrozenStructure", "kind"),
        evaluated_at=observed_at,
        target_amount=Decimal("0.1"),
        instrument_names=_instrument_names(quotes),
        observation_id=None,
        observed_at=None,
        observation_known_at=None,
        quotes=None,
        pricing=None,
        unknown_reason="NO_CAUSAL_COMPONENT_CUT",
    )
    with pytest.raises(ValueError, match="only accepts component synthetic"):
        replace(evidence, kind=kind)

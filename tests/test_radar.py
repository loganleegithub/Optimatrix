from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from optimatrix.engine import ShadowEngine
from optimatrix.market import BreakoutState, EventState, MarketContextEvidence
from optimatrix.radar import Decision
from optimatrix.scenarios import base_chain, current_expiry, market_context


def test_high_vrp_calm_session_selects_two_sided_candidate(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now)),
        context=market_context(now),
    )
    assert decision.decision is Decision.CANDIDATE
    assert decision.structure is not None
    assert decision.structure.short_put.option_type.value == "PUT"
    assert decision.structure.short_call.option_type.value == "CALL"
    assert decision.score is not None and decision.score.vrp_ratio == Decimal("1.5")


def test_high_premium_cannot_override_gamma_explosion(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now)),
        context=market_context(
            now,
            implied_variance=Decimal("0.0032"),
            rv_acceleration=Decimal("0.9"),
            jump_share=Decimal("0.9"),
            directional_persistence=Decimal("0.9"),
            breakout=BreakoutState.BREAKING_CONCENTRATED_STRIKE,
        ),
    )
    assert decision.decision is Decision.ABSTAIN
    assert "CONCENTRATED_STRIKE_BREAKOUT" in decision.blockers


def test_live_event_is_not_a_mechanical_sell_signal(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 16, 0, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now)),
        context=market_context(now, event=EventState.LIVE_EVENT),
    )
    assert decision.decision is Decision.ABSTAIN
    assert "EVENT_OR_SHOCK_IN_PROGRESS" in decision.blockers


def test_unbound_market_context_is_unknown_without_structure_score_or_case(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    case_root = tmp_path / "cases"
    engine = ShadowEngine(policy=policy, case_root=case_root)
    known_context = market_context(now)
    future_ms = int(now.timestamp() * 1000) + 1
    invalid_evidence = replace(
        known_context.evidence,
        market_source_max_ms=future_ms,
        market_received_max_ms=future_ms,
    )
    monkeypatch.setattr(
        "optimatrix.radar.select_iron_condor",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("selector must not run")),
    )
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now)),
        context=replace(known_context, evidence=invalid_evidence),
    )

    assert decision.decision is Decision.UNKNOWN
    assert decision.structure is None
    assert decision.score is None
    assert decision.blockers[0] == "MARKET_CONTEXT_EVIDENCE_NOT_BOUND"
    assert "MARKET_SOURCE_BOUNDARY_IN_FUTURE" in decision.blockers
    with pytest.raises(ValueError, match="only a CANDIDATE"):
        engine.open_decision_case(decision=decision, opened_at=now)
    assert not tuple(case_root.rglob("*.jsonl"))


def test_missing_event_source_is_unknown_not_calm(policy, tmp_path) -> None:
    from dataclasses import replace

    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    known = market_context(now, event=EventState.NONE)
    context = replace(
        known,
        evidence=replace(known.evidence, event_state_source=None),
    )
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=base_chain(expiry=current_expiry(now)),
        context=context,
    )

    assert decision.decision is Decision.UNKNOWN
    assert "EVENT_STATE_SOURCE_UNKNOWN" in decision.blockers


def test_incoherent_vertical_books_cannot_form_a_two_sided_candidate(
    policy,
    tmp_path,
) -> None:
    from dataclasses import replace

    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    chain = list(base_chain(expiry=current_expiry(now), observed_at=now))
    chain[0] = replace(
        chain[0],
        source_timestamp_ms=chain[1].source_timestamp_ms + 7000,
        received_timestamp_ms=chain[1].received_timestamp_ms + 5000,
    )
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=tuple(chain),
        context=market_context(now),
    )
    assert decision.decision is Decision.ABSTAIN
    assert "NO_EXECUTABLE_PUT_VERTICAL" in decision.blockers


def test_market_context_requires_timezone_aware_time() -> None:
    from optimatrix.market import BreakoutState, EventState, MarketContext

    with pytest.raises(ValueError, match="timezone-aware"):
        MarketContext(
            now=datetime(2026, 8, 12, 18, 0),
            index_price=Decimal("100000"),
            forward_price=Decimal("100000"),
            physical_variance_forecast=Decimal("0.002"),
            same_session_implied_variance=Decimal("0.003"),
            rv_acceleration=Decimal("0.1"),
            jump_share=Decimal("0.1"),
            directional_persistence=Decimal("0.1"),
            event_state=EventState.NONE,
            breakout_state=BreakoutState.NEUTRAL,
            concentrated_strike=None,
            concentration_strength=Decimal("0"),
            evidence=MarketContextEvidence.unknown(),
        )


def test_four_leg_decision_requires_one_coherent_market_snapshot(policy, tmp_path) -> None:
    from dataclasses import replace
    from datetime import timedelta

    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    quotes = list(base_chain(expiry=current_expiry(now), observed_at=now))
    for index, quote in enumerate(quotes):
        if quote.option_type.value == "CALL":
            quotes[index] = replace(
                quote,
                source_timestamp_ms=quote.source_timestamp_ms + 10_000,
                received_timestamp_ms=quote.received_timestamp_ms + 10_000,
            )
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(
        quotes=tuple(quotes),
        context=market_context(now + timedelta(seconds=20)),
    )
    assert decision.decision is Decision.ABSTAIN
    assert "NO_COHERENT_COMBINABLE_TWO_SIDED_STRUCTURE" in decision.blockers

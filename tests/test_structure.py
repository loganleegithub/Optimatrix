from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.market import PriceLevel
from optimatrix.scenarios import (
    all_joint_adversarial_chain,
    base_chain,
    current_expiry,
    market_context,
)
from optimatrix.structure import select_btc_0dte_condor


def _observation(policy, quotes, at):
    return Btc0DteShortVolEngine(policy=policy).capture_observation(
        quotes=quotes,
        context=market_context(
            at,
            book_names=tuple(quote.instrument_name for quote in quotes),
        ),
    )


def test_direct_four_leg_selection_is_order_invariant_and_bounded(policy) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = all_joint_adversarial_chain(expiry=current_expiry(at), observed_at=at)
    baseline = select_btc_0dte_condor(
        observation=_observation(policy, quotes, at),
        policy=policy,
    )
    assert baseline.selected is not None
    assert baseline.legal_structure_count > 0
    assert baseline.price_evaluable_count > 0
    assert baseline.policy_eligible_count > 0
    assert len(baseline.retained_alternatives) <= policy.structure.maximum_retained_alternatives
    for seed in range(30):
        shuffled = list(quotes)
        random.Random(seed).shuffle(shuffled)
        selected = select_btc_0dte_condor(
            observation=_observation(policy, tuple(shuffled), at),
            policy=policy,
        )
        assert selected.selected is not None
        assert selected.selected.identity == baseline.selected.identity
        assert selected.legal_structure_count == baseline.legal_structure_count
        assert selected.price_evaluable_count == baseline.price_evaluable_count


def test_shallow_reverse_depth_is_diagnostic_not_a_hard_veto(policy) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = tuple(
        replace(quote, ask=(PriceLevel(quote.ask[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P") or quote.instrument_name.endswith("105000-C")
        else quote
        for quote in base_chain(expiry=current_expiry(at), observed_at=at)
    )
    selection = select_btc_0dte_condor(
        observation=_observation(policy, quotes, at),
        policy=policy,
    )
    assert selection.selected is not None
    assert min(selection.selected.close_depth_coverage) == Decimal("0.5")
    assert selection.selected.pricing.observed_close_native_debit is None
    assert not any("BUYBACK" in blocker for blocker in selection.blockers)


def test_entry_depth_failure_preserves_legal_structure_count(policy) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = tuple(
        replace(quote, bid=(PriceLevel(quote.bid[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P") or quote.instrument_name.endswith("105000-C")
        else quote
        for quote in base_chain(expiry=current_expiry(at), observed_at=at)
    )
    selection = select_btc_0dte_condor(
        observation=_observation(policy, quotes, at),
        policy=policy,
    )
    assert selection.legal_structure_count == 1
    assert selection.price_evaluable_count == 0
    assert selection.blockers == ("NO_PRICE_EVALUABLE_FOUR_LEG_STRUCTURE",)

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from options_domain import build_vertical_quote, enumerate_verticals
from radar_runtime.fixture import build_fixture_events, replay_fixture


def test_visible_bid_ask_vertical_freezes_real_economics() -> None:
    frame, _ = replay_fixture(build_fixture_events())
    assert frame.reference_price is not None
    assert frame.index_price is not None
    candidates = enumerate_verticals(
        frame_capture_seq=frame.as_of_capture_seq,
        reference_price=frame.reference_price,
        index_price=frame.index_price,
        option_quotes=frame.option_quotes,
        quantity=Decimal("0.04"),
        minimum_tte_seconds=1_800,
        maximum_tte_seconds=72 * 3_600,
    )
    candidate = next(item for item in candidates if item.sold_side.value == "PUT")

    assert candidate.executable_entry_credit > 0
    assert candidate.executable_close_debit >= candidate.executable_entry_credit
    assert candidate.max_loss_usdc > 0
    assert candidate.gross_credit_usdc == (candidate.executable_entry_credit * candidate.quantity)
    assert candidate.execution_source == "CONSERVATIVE_LEG_CROSS"
    assert candidate.close_execution_source == "CONSERVATIVE_LEG_CROSS"


def test_mark_iv_never_changes_executable_vertical_price() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    assert decision.assessment is not None
    assert frame.reference_price is not None
    assert frame.index_price is not None
    original = decision.assessment.candidate
    rebuilt = build_vertical_quote(
        frame_capture_seq=frame.as_of_capture_seq,
        reference_price=frame.reference_price,
        index_price=frame.index_price,
        short_quote=replace(original.short_leg, mark_iv=Decimal("999")),
        long_quote=replace(original.long_leg, mark_iv=Decimal("1")),
        quantity=original.quantity,
    )
    assert rebuilt is not None
    assert rebuilt.executable_entry_credit == original.executable_entry_credit
    assert rebuilt.executable_close_debit == original.executable_close_debit


def test_missing_immediate_close_side_removes_candidate() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    assert decision.assessment is not None
    assert frame.reference_price is not None
    assert frame.index_price is not None
    original = decision.assessment.candidate
    rebuilt = build_vertical_quote(
        frame_capture_seq=frame.as_of_capture_seq,
        reference_price=frame.reference_price,
        index_price=frame.index_price,
        short_quote=original.short_leg,
        long_quote=replace(original.long_leg, bid=None),
        quantity=original.quantity,
    )
    assert rebuilt is None

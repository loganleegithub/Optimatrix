from __future__ import annotations

from datetime import UTC, datetime, timedelta

from optimatrix.scenarios import current_expiry
from optimatrix.session import SessionPhase, current_deribit_session, expiry_is_current_session


def test_deribit_zero_dte_is_the_current_08_00_session() -> None:
    before = datetime(2026, 8, 12, 7, 30, tzinfo=UTC)
    session = current_deribit_session(before)
    assert session.start == datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    assert session.end == datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    assert expiry_is_current_session(current_expiry(before), session)

    after = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    next_session = current_deribit_session(after)
    assert next_session.start == datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    assert next_session.end == datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    assert expiry_is_current_session(current_expiry(after), next_session)


def test_session_phases_are_business_windows_not_rolling_dte_labels() -> None:
    roll = current_deribit_session(datetime(2026, 8, 12, 8, 20, tzinfo=UTC))
    core = current_deribit_session(datetime(2026, 8, 12, 18, 0, tzinfo=UTC))
    late = current_deribit_session(datetime(2026, 8, 13, 5, 30, tzinfo=UTC))
    exit_only = current_deribit_session(datetime(2026, 8, 13, 6, 45, tzinfo=UTC))
    twap = current_deribit_session(datetime(2026, 8, 13, 7, 45, tzinfo=UTC))
    assert roll.phase is SessionPhase.ROLL_REPRICE
    assert core.phase is SessionPhase.CORE_CARRY
    assert late.phase is SessionPhase.LATE_THETA
    assert exit_only.phase is SessionPhase.EXIT_ONLY
    assert twap.phase is SessionPhase.DELIVERY_TWAP


def test_non_current_expiry_is_not_zero_dte_even_if_nearby() -> None:
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    session = current_deribit_session(now)
    assert not expiry_is_current_session(session.end + timedelta(days=1), session)

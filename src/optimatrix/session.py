from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

SETTLEMENT_HOUR_UTC = 8


class SessionPhase(StrEnum):
    ROLL_REPRICE = "ROLL_REPRICE"
    CORE_CARRY = "CORE_CARRY"
    LATE_THETA = "LATE_THETA"
    EXIT_ONLY = "EXIT_ONLY"
    DELIVERY_TWAP = "DELIVERY_TWAP"


@dataclass(frozen=True)
class SessionPhasePolicy:
    roll_reprice_minutes: int
    late_theta_start_minutes_to_expiry: int
    exit_only_minutes_to_expiry: int
    delivery_twap_minutes_to_expiry: int

    def __post_init__(self) -> None:
        values = (
            self.roll_reprice_minutes,
            self.late_theta_start_minutes_to_expiry,
            self.exit_only_minutes_to_expiry,
            self.delivery_twap_minutes_to_expiry,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values
        ):
            raise ValueError("session phase values must be positive integers")
        if not (
            self.late_theta_start_minutes_to_expiry
            > self.exit_only_minutes_to_expiry
            > self.delivery_twap_minutes_to_expiry
        ):
            raise ValueError("late/exit/twap boundaries must be strictly descending")


DEFAULT_SESSION_PHASE_POLICY = SessionPhasePolicy(
    roll_reprice_minutes=60,
    late_theta_start_minutes_to_expiry=180,
    exit_only_minutes_to_expiry=90,
    delivery_twap_minutes_to_expiry=30,
)


@dataclass(frozen=True)
class DeribitSession:
    session_id: str
    start: datetime
    end: datetime
    now: datetime
    minute: int
    minutes_to_expiry: int
    phase: SessionPhase

    @property
    def is_current_expiry(self) -> bool:
        return self.start <= self.now < self.end


def current_deribit_session(
    now: datetime,
    *,
    phase_policy: SessionPhasePolicy = DEFAULT_SESSION_PHASE_POLICY,
) -> DeribitSession:
    normalized = _utc(now)
    same_day_settlement = normalized.replace(
        hour=SETTLEMENT_HOUR_UTC,
        minute=0,
        second=0,
        microsecond=0,
    )
    end = (
        same_day_settlement
        if normalized < same_day_settlement
        else same_day_settlement + timedelta(days=1)
    )
    start = end - timedelta(days=1)
    elapsed_seconds = (normalized - start).total_seconds()
    remaining_seconds = (end - normalized).total_seconds()
    elapsed = int(elapsed_seconds // 60)
    remaining = int(remaining_seconds // 60)
    phase = _classify_session_phase_seconds(
        elapsed_seconds=elapsed_seconds,
        seconds_to_expiry=remaining_seconds,
        policy=phase_policy,
    )
    return DeribitSession(
        session_id=end.isoformat().replace("+00:00", "Z"),
        start=start,
        end=end,
        now=normalized,
        minute=elapsed,
        minutes_to_expiry=remaining,
        phase=phase,
    )


def expiry_is_current_session(expiry: datetime, session: DeribitSession) -> bool:
    return _utc(expiry) == session.end


def classify_session_phase(
    *,
    elapsed_minutes: int,
    minutes_to_expiry: int,
    policy: SessionPhasePolicy = DEFAULT_SESSION_PHASE_POLICY,
) -> SessionPhase:
    if elapsed_minutes < 0 or minutes_to_expiry < 0:
        raise ValueError("session timing must be non-negative")
    return _classify_session_phase_seconds(
        elapsed_seconds=elapsed_minutes * 60,
        seconds_to_expiry=minutes_to_expiry * 60,
        policy=policy,
    )


def _classify_session_phase_seconds(
    *,
    elapsed_seconds: float,
    seconds_to_expiry: float,
    policy: SessionPhasePolicy,
) -> SessionPhase:
    if elapsed_seconds < 0 or seconds_to_expiry < 0:
        raise ValueError("session timing must be non-negative")
    if seconds_to_expiry <= policy.delivery_twap_minutes_to_expiry * 60:
        return SessionPhase.DELIVERY_TWAP
    if seconds_to_expiry <= policy.exit_only_minutes_to_expiry * 60:
        return SessionPhase.EXIT_ONLY
    if seconds_to_expiry <= policy.late_theta_start_minutes_to_expiry * 60:
        return SessionPhase.LATE_THETA
    if elapsed_seconds < policy.roll_reprice_minutes * 60:
        return SessionPhase.ROLL_REPRICE
    return SessionPhase.CORE_CARRY


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)

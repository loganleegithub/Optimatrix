from __future__ import annotations

from dataclasses import dataclass

from market_monitor.types import ContinuityGap, TimeInterval

DRIFT_PARTS_PER_MILLION = 1_000
CLOCK_REFRESH_INTERVAL_MS = 30_000
CLOCK_EXPIRY_MS = 60_000


def _floor_ratio(value: int, numerator: int, denominator: int) -> int:
    return value * numerator // denominator


def _ceil_ratio(value: int, numerator: int, denominator: int) -> int:
    product = value * numerator
    return -(-product // denominator)


@dataclass(frozen=True)
class TrustedClock:
    base: TimeInterval
    base_monotonic_ms: int
    last_refresh_monotonic_ms: int

    @classmethod
    def from_response(
        cls, server_ms: int, sent_monotonic_ms: int, received_monotonic_ms: int
    ) -> TrustedClock:
        if isinstance(server_ms, bool) or not isinstance(server_ms, int) or server_ms < 0:
            raise ValueError("server time must be a non-negative integer millisecond")
        if sent_monotonic_ms < 0 or received_monotonic_ms < sent_monotonic_ms:
            raise ValueError("invalid monotonic request interval")
        round_trip_ms = received_monotonic_ms - sent_monotonic_ms
        return cls(
            base=TimeInterval(server_ms, server_ms + 1 + round_trip_ms),
            base_monotonic_ms=received_monotonic_ms,
            last_refresh_monotonic_ms=received_monotonic_ms,
        )

    def interval_at(self, monotonic_ms: int) -> TimeInterval:
        elapsed_ms = monotonic_ms - self.base_monotonic_ms
        if elapsed_ms < 0:
            raise ValueError("monotonic time moved backward")
        if monotonic_ms - self.last_refresh_monotonic_ms >= CLOCK_EXPIRY_MS:
            raise ContinuityGap("trusted clock refresh expired")
        denominator = 1_000_000
        lower_elapsed = _floor_ratio(elapsed_ms, denominator - DRIFT_PARTS_PER_MILLION, denominator)
        upper_elapsed = _ceil_ratio(elapsed_ms, denominator + DRIFT_PARTS_PER_MILLION, denominator)
        return TimeInterval(
            self.base.lower_ms + lower_elapsed,
            self.base.upper_ms + upper_elapsed,
        )

    def refresh(
        self,
        server_ms: int,
        sent_monotonic_ms: int,
        received_monotonic_ms: int,
    ) -> TrustedClock:
        previous_at_receipt = self.interval_at(received_monotonic_ms)
        fresh = TrustedClock.from_response(server_ms, sent_monotonic_ms, received_monotonic_ms)
        intersection = previous_at_receipt.intersection(fresh.base)
        if intersection is None:
            raise ContinuityGap("trusted clock intervals do not intersect")
        return TrustedClock(
            base=intersection,
            base_monotonic_ms=received_monotonic_ms,
            last_refresh_monotonic_ms=received_monotonic_ms,
        )

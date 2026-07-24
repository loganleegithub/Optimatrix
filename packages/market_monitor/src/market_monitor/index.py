from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from market_monitor.types import ContinuityGap, decimal_from_source

MINUTE_MS = 60_000


@dataclass(frozen=True)
class MinuteClose:
    minute_start_ms: int
    price: Decimal
    causal_seq: int


class IndexMinuteReducer:
    def __init__(self, maximum_return_count: int) -> None:
        if maximum_return_count <= 0:
            raise ValueError("maximum return count must be positive")
        self._maximum_close_count = maximum_return_count + 1
        self._coverage_start_ms: int | None = None
        self._last_source_timestamp_ms: int | None = None
        self._watermark_ms: int | None = None
        self._working: dict[int, MinuteClose] = {}
        self._sealed: list[MinuteClose] = []

    @property
    def sealed(self) -> tuple[MinuteClose, ...]:
        return tuple(self._sealed)

    @property
    def has_accepted_tick(self) -> bool:
        return self._last_source_timestamp_ms is not None

    def start_continuous_coverage(self, source_timestamp_ms: int) -> None:
        if source_timestamp_ms < 0:
            raise ValueError("coverage start must be non-negative")
        self._coverage_start_ms = source_timestamp_ms
        self._last_source_timestamp_ms = None
        self._watermark_ms = None
        self._working.clear()
        self._sealed.clear()

    def gap(self) -> None:
        self._coverage_start_ms = None
        self._last_source_timestamp_ms = None
        self._watermark_ms = None
        self._working.clear()
        self._sealed.clear()

    def accept_tick(
        self,
        *,
        source_timestamp_ms: int,
        price: object,
        causal_seq: int,
    ) -> None:
        if self._coverage_start_ms is None:
            raise ContinuityGap("index coverage has not started")
        if source_timestamp_ms < 0 or causal_seq <= 0:
            raise ValueError("invalid index timestamp or causal sequence")
        if (
            self._last_source_timestamp_ms is not None
            and source_timestamp_ms < self._last_source_timestamp_ms
        ):
            self.gap()
            raise ContinuityGap("index timestamp regressed")
        minute_start = source_timestamp_ms // MINUTE_MS * MINUTE_MS
        if self._sealed and minute_start <= self._sealed[-1].minute_start_ms:
            self.gap()
            raise ContinuityGap("late tick targeted a sealed index minute")
        parsed_price = decimal_from_source(price, "index.price")
        if parsed_price <= 0:
            raise ValueError("index price must be positive")
        self._working[minute_start] = MinuteClose(minute_start, parsed_price, causal_seq)
        self._last_source_timestamp_ms = source_timestamp_ms
        self._watermark_ms = source_timestamp_ms

    def seal_ready(self, trusted_time_lower_ms: int) -> tuple[MinuteClose, ...]:
        if self._coverage_start_ms is None or self._watermark_ms is None:
            return ()
        newly_sealed: list[MinuteClose] = []
        for minute_start in sorted(self._working):
            minute_end = minute_start + MINUTE_MS
            if minute_end > trusted_time_lower_ms or minute_end > self._watermark_ms:
                break
            if self._coverage_start_ms > minute_start:
                self._working.pop(minute_start)
                continue
            close = self._working.pop(minute_start)
            self._sealed.append(close)
            if len(self._sealed) > self._maximum_close_count:
                del self._sealed[: len(self._sealed) - self._maximum_close_count]
            newly_sealed.append(close)
        return tuple(newly_sealed)

    def consecutive_prices(self, return_count: int) -> tuple[Decimal, ...] | None:
        if return_count <= 0:
            raise ValueError("return_count must be positive")
        required_closes = return_count + 1
        if len(self._sealed) < required_closes:
            return None
        closes = self._sealed[-required_closes:]
        for earlier, later in pairwise(closes):
            if later.minute_start_ms - earlier.minute_start_ms != MINUTE_MS:
                return None
        return tuple(close.price for close in closes)

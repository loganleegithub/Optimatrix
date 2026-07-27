from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from market_monitor.types import ContinuityGap, TimeInterval, decimal_from_source

MINUTE_MS = 60_000


@dataclass(frozen=True)
class MinuteClose:
    minute_start_ms: int
    price: Decimal
    causal_seq: int


class IndexTailStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    WARMUP = "WARMUP"
    TIME_BOUNDARY_PENDING = "TIME_BOUNDARY_PENDING"
    WATERMARK_PENDING = "WATERMARK_PENDING"
    WINDOW_GAP = "WINDOW_GAP"
    SOURCE_STALE = "SOURCE_STALE"
    CONTINUITY_GAP = "CONTINUITY_GAP"


@dataclass(frozen=True)
class IndexTail:
    status: IndexTailStatus
    closes: tuple[MinuteClose, ...] = ()

    @property
    def prices(self) -> tuple[Decimal, ...] | None:
        if self.status is not IndexTailStatus.AVAILABLE:
            return None
        return tuple(close.price for close in self.closes)


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
        self._continuity_gap = False

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
        self._continuity_gap = False

    def gap(self) -> None:
        self._coverage_start_ms = None
        self._last_source_timestamp_ms = None
        self._watermark_ms = None
        self._working.clear()
        self._sealed.clear()
        self._continuity_gap = True

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

    def current_tail(
        self,
        return_count: int,
        *,
        trusted_time: TimeInterval,
        source_stale_deadline_ms: int,
    ) -> IndexTail:
        if return_count <= 0:
            raise ValueError("return_count must be positive")
        if source_stale_deadline_ms <= 0:
            raise ValueError("index source stale deadline must be positive")
        if self._continuity_gap:
            return IndexTail(IndexTailStatus.CONTINUITY_GAP)
        if self._coverage_start_ms is None:
            return IndexTail(IndexTailStatus.WARMUP)
        if (
            self._last_source_timestamp_ms is not None
            and trusted_time.lower_ms - self._last_source_timestamp_ms > source_stale_deadline_ms
        ):
            return IndexTail(IndexTailStatus.SOURCE_STALE)

        lower_current_minute = trusted_time.lower_ms // MINUTE_MS
        upper_current_minute = trusted_time.upper_ms // MINUTE_MS
        if lower_current_minute != upper_current_minute:
            return IndexTail(IndexTailStatus.TIME_BOUNDARY_PENDING)

        current_minute_start_ms = lower_current_minute * MINUTE_MS
        if self._watermark_ms is None or self._watermark_ms < current_minute_start_ms:
            return IndexTail(IndexTailStatus.WATERMARK_PENDING)

        required_closes = return_count + 1
        expected_tail_start_ms = current_minute_start_ms - MINUTE_MS
        earliest_required_start_ms = expected_tail_start_ms - return_count * MINUTE_MS
        closes = tuple(
            close
            for close in self._sealed
            if earliest_required_start_ms <= close.minute_start_ms <= expected_tail_start_ms
        )
        if len(closes) < required_closes:
            if (
                self._coverage_start_ms is None
                or self._coverage_start_ms > earliest_required_start_ms
            ):
                return IndexTail(IndexTailStatus.WARMUP, closes)
            return IndexTail(IndexTailStatus.WINDOW_GAP, closes)
        if any(
            later.minute_start_ms - earlier.minute_start_ms != MINUTE_MS
            for earlier, later in pairwise(closes)
        ):
            return IndexTail(IndexTailStatus.WINDOW_GAP, closes)
        if closes[-1].minute_start_ms != expected_tail_start_ms:
            return IndexTail(IndexTailStatus.WINDOW_GAP, closes)
        return IndexTail(IndexTailStatus.AVAILABLE, closes)

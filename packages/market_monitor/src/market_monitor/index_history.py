from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from market_monitor.index import IndexAvailabilityState
from market_monitor.types import (
    SourceDataError,
    TimeInterval,
    decimal_from_source,
    require_int,
    require_list,
)

MINUTE_MS = 60_000
MAX_INDEX_HISTORY_POINTS = 10_000


@dataclass(frozen=True)
class IndexHistoryPoint:
    timestamp_ms: int
    average_price: Decimal


@dataclass(frozen=True)
class IndexHistoryState:
    availability: IndexAvailabilityState
    points: tuple[IndexHistoryPoint, ...] = ()
    latest_source_timestamp_ms: int | None = None
    reason: str | None = None

    @property
    def prices(self) -> tuple[Decimal, ...] | None:
        if self.availability is not IndexAvailabilityState.AVAILABLE:
            return None
        return tuple(point.average_price for point in self.points)

    @property
    def economic_identity(self) -> tuple[object, ...] | None:
        if self.availability is not IndexAvailabilityState.AVAILABLE:
            return None
        return tuple(self.points)


class IndexHistoryReducer:
    """Sole in-memory owner for official causal index-chart baseline samples."""

    def __init__(self, *, maximum_lookback_minutes: int, return_interval_minutes: int) -> None:
        if maximum_lookback_minutes <= 0 or return_interval_minutes <= 0:
            raise ValueError("index history horizons must be positive")
        if maximum_lookback_minutes % return_interval_minutes:
            raise ValueError("index history lookback must be divisible by return interval")
        self.maximum_lookback_minutes = maximum_lookback_minutes
        self.return_interval_minutes = return_interval_minutes
        self._points: tuple[IndexHistoryPoint, ...] = ()
        self._has_response = False

    @property
    def points(self) -> tuple[IndexHistoryPoint, ...]:
        return self._points

    def apply_chart_result(self, value: object) -> bool:
        rows = require_list(value, "index chart result")
        if len(rows) > MAX_INDEX_HISTORY_POINTS:
            raise SourceDataError("index chart result exceeds the bounded point limit")
        points: list[IndexHistoryPoint] = []
        previous_timestamp: int | None = None
        for index, raw in enumerate(rows):
            pair = require_list(raw, f"index chart result[{index}]")
            if len(pair) != 2:
                raise SourceDataError(f"index chart result[{index}] must contain two values")
            timestamp = require_int(pair[0], f"index chart result[{index}].timestamp")
            price = decimal_from_source(pair[1], f"index chart result[{index}].average_price")
            if timestamp < 0 or price <= 0:
                raise SourceDataError("index chart point timestamp or price is invalid")
            if previous_timestamp is not None and timestamp <= previous_timestamp:
                raise SourceDataError("index chart timestamps must be strictly increasing")
            points.append(IndexHistoryPoint(timestamp, price))
            previous_timestamp = timestamp
        parsed = tuple(points)
        changed = not self._has_response or parsed != self._points
        self._points = parsed
        self._has_response = True
        return changed

    def current_tail(
        self,
        lookback_minutes: int,
        *,
        trusted_time: TimeInterval,
        source_stale_deadline_ms: int,
    ) -> IndexHistoryState:
        if lookback_minutes <= 0 or lookback_minutes > self.maximum_lookback_minutes:
            raise ValueError("index history lookback is outside the configured maximum")
        if lookback_minutes % self.return_interval_minutes:
            raise ValueError("index history lookback must be divisible by return interval")
        if source_stale_deadline_ms <= 0:
            raise ValueError("index history stale deadline must be positive")
        if not self._points:
            return IndexHistoryState(
                IndexAvailabilityState.WARMUP,
                reason=(
                    "INDEX_HISTORY_WARMUP"
                    if self._has_response
                    else "INDEX_HISTORY_BOOTSTRAP_REQUIRED"
                ),
            )

        interval_ms = self.return_interval_minutes * MINUTE_MS
        completed_cutoff_ms = trusted_time.lower_ms - interval_ms
        eligible = tuple(
            point for point in self._points if point.timestamp_ms <= completed_cutoff_ms
        )
        if not eligible:
            return IndexHistoryState(
                IndexAvailabilityState.WARMUP,
                reason="INDEX_HISTORY_WARMUP",
            )
        latest = eligible[-1]
        if trusted_time.lower_ms - latest.timestamp_ms > source_stale_deadline_ms:
            return IndexHistoryState(
                IndexAvailabilityState.SOURCE_STALE,
                latest_source_timestamp_ms=latest.timestamp_ms,
                reason="INDEX_HISTORY_SOURCE_STALE",
            )

        required_count = lookback_minutes // self.return_interval_minutes + 1
        by_timestamp = {point.timestamp_ms: point for point in eligible}
        required_timestamps = tuple(
            latest.timestamp_ms - offset * interval_ms for offset in reversed(range(required_count))
        )
        selected = tuple(
            by_timestamp[timestamp]
            for timestamp in required_timestamps
            if timestamp in by_timestamp
        )
        if len(selected) != required_count:
            earliest_required = required_timestamps[0]
            availability = (
                IndexAvailabilityState.WARMUP
                if eligible[0].timestamp_ms > earliest_required
                else IndexAvailabilityState.WINDOW_GAP
            )
            return IndexHistoryState(
                availability,
                points=selected,
                latest_source_timestamp_ms=latest.timestamp_ms,
                reason=(
                    "INDEX_HISTORY_WARMUP"
                    if availability is IndexAvailabilityState.WARMUP
                    else "INDEX_HISTORY_WINDOW_GAP"
                ),
            )
        return IndexHistoryState(
            IndexAvailabilityState.AVAILABLE,
            points=selected,
            latest_source_timestamp_ms=latest.timestamp_ms,
        )


__all__ = [
    "IndexHistoryPoint",
    "IndexHistoryReducer",
    "IndexHistoryState",
]

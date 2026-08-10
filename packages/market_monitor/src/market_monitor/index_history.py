from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

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
class IndexHistoryContract:
    source_point_count: int
    interval_counts: tuple[tuple[int, int], ...]
    modal_interval_ms: int | None
    newest_response_timestamp_ms: int | None
    newest_response_age_ms: int | None
    newest_response_point_excluded_by_completion_cutoff: bool
    latest_source_timestamp_ms: int | None
    latest_source_age_ms: int | None
    exact_suffix_point_count: int
    exact_suffix_minutes: int
    revision_count: int
    revision_pending: bool
    revised_timestamps_ms: tuple[int, ...]


@dataclass(frozen=True)
class IndexHistoryState:
    availability: IndexAvailabilityState
    points: tuple[IndexHistoryPoint, ...] = ()
    latest_source_timestamp_ms: int | None = None
    reason: str | None = None
    contract: IndexHistoryContract | None = None

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
        self._revision_pending = False
        self._revision_count = 0
        self._revised_timestamps: tuple[int, ...] = ()
        self._completed_cutoff_ms: int | None = None
        self._timestamps: tuple[int, ...] = ()
        self._point_by_timestamp: dict[int, IndexHistoryPoint] = {}
        self._exact_suffix_count_by_timestamp: dict[int, int] = {}
        self._interval_counts: tuple[tuple[int, int], ...] = ()
        self._modal_interval_ms: int | None = None

    @property
    def points(self) -> tuple[IndexHistoryPoint, ...]:
        return self._points

    @property
    def revision_pending(self) -> bool:
        return self._revision_pending

    def apply_chart_result(
        self,
        value: object,
        *,
        trusted_time: TimeInterval | None = None,
    ) -> bool:
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
        revised = self._completed_overlap_revisions(self._points, parsed)
        if revised:
            self._revision_count += 1
            self._revision_pending = True
            self._revised_timestamps = revised
        elif self._revision_pending and self._pending_revision_is_confirmed(parsed):
            # One subsequent response may append a new provider bucket; it confirms the
            # replacement generation when every previously revised completed point is stable.
            self._revision_pending = False
            self._revised_timestamps = ()
        if trusted_time is not None:
            interval_ms = self.return_interval_minutes * MINUTE_MS
            self._completed_cutoff_ms = trusted_time.lower_ms - interval_ms
        source_intervals = Counter(
            later.timestamp_ms - earlier.timestamp_ms for earlier, later in pairwise(parsed)
        )
        exact_suffix_counts: dict[int, int] = {}
        exact_interval_ms = self.return_interval_minutes * MINUTE_MS
        for point in parsed:
            exact_suffix_counts[point.timestamp_ms] = (
                exact_suffix_counts.get(point.timestamp_ms - exact_interval_ms, 0) + 1
            )
        self._points = parsed
        self._timestamps = tuple(point.timestamp_ms for point in parsed)
        self._point_by_timestamp = {point.timestamp_ms: point for point in parsed}
        self._exact_suffix_count_by_timestamp = exact_suffix_counts
        self._interval_counts = tuple(sorted(source_intervals.items()))
        self._modal_interval_ms = (
            min(source_intervals, key=lambda value: (-source_intervals[value], value))
            if source_intervals
            else None
        )
        self._has_response = True
        return changed

    def _pending_revision_is_confirmed(
        self,
        current: tuple[IndexHistoryPoint, ...],
    ) -> bool:
        if not self._revised_timestamps:
            return False
        previous_by_timestamp = {point.timestamp_ms: point.average_price for point in self._points}
        current_by_timestamp = {point.timestamp_ms: point.average_price for point in current}
        return all(
            timestamp in previous_by_timestamp
            and current_by_timestamp.get(timestamp) == previous_by_timestamp[timestamp]
            for timestamp in self._revised_timestamps
        )

    def _completed_overlap_revisions(
        self,
        previous: tuple[IndexHistoryPoint, ...],
        current: tuple[IndexHistoryPoint, ...],
    ) -> tuple[int, ...]:
        if len(previous) < 2 or not current:
            return ()
        if self._completed_cutoff_ms is None:
            # Before trusted time exists, only the previous response's newest point may be open.
            completed = previous[:-1]
        else:
            completed = tuple(
                point for point in previous if point.timestamp_ms <= self._completed_cutoff_ms
            )
        previous_completed = {point.timestamp_ms: point.average_price for point in completed}
        return tuple(
            point.timestamp_ms
            for point in current
            if point.timestamp_ms in previous_completed
            and point.average_price != previous_completed[point.timestamp_ms]
        )

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

        interval_ms = self.return_interval_minutes * MINUTE_MS
        completed_cutoff_ms = trusted_time.lower_ms - interval_ms
        aligned_cutoff_ms = completed_cutoff_ms - (completed_cutoff_ms % interval_ms)
        # Consume only points old enough to represent a completed configured interval. The
        # source probe separately reports whether the provider's newest response point usually
        # falls outside this cutoff. The economic suffix is anchored to one UTC-epoch-aligned
        # grid so finer source points cannot rotate the return-sampling phase every minute.
        eligible = self._points[: bisect_right(self._timestamps, completed_cutoff_ms)]
        contract = self._contract(eligible, trusted_time=trusted_time)

        if self._revision_pending:
            return IndexHistoryState(
                IndexAvailabilityState.REVISION,
                latest_source_timestamp_ms=(eligible[-1].timestamp_ms if eligible else None),
                reason="INDEX_HISTORY_REVISION",
                contract=contract,
            )
        if not self._points:
            return IndexHistoryState(
                IndexAvailabilityState.WARMUP,
                reason=(
                    "INDEX_HISTORY_WARMUP"
                    if self._has_response
                    else "INDEX_HISTORY_BOOTSTRAP_REQUIRED"
                ),
                contract=contract,
            )
        if not eligible:
            return IndexHistoryState(
                IndexAvailabilityState.WARMUP,
                reason="INDEX_HISTORY_WARMUP",
                contract=contract,
            )
        latest = eligible[-1]
        if trusted_time.lower_ms - latest.timestamp_ms > source_stale_deadline_ms:
            return IndexHistoryState(
                IndexAvailabilityState.SOURCE_STALE,
                latest_source_timestamp_ms=latest.timestamp_ms,
                reason="INDEX_HISTORY_SOURCE_STALE",
                contract=contract,
            )

        required_count = lookback_minutes // self.return_interval_minutes + 1
        required_timestamps = tuple(
            aligned_cutoff_ms - offset * interval_ms for offset in reversed(range(required_count))
        )
        selected = tuple(
            self._point_by_timestamp[timestamp]
            for timestamp in required_timestamps
            if timestamp in self._point_by_timestamp
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
                contract=contract,
            )
        return IndexHistoryState(
            IndexAvailabilityState.AVAILABLE,
            points=selected,
            latest_source_timestamp_ms=latest.timestamp_ms,
            contract=contract,
        )

    def _contract(
        self,
        eligible: tuple[IndexHistoryPoint, ...],
        *,
        trusted_time: TimeInterval,
    ) -> IndexHistoryContract:
        suffix_count = (
            self._exact_suffix_count_by_timestamp.get(eligible[-1].timestamp_ms, 0)
            if eligible
            else 0
        )
        latest_timestamp = eligible[-1].timestamp_ms if eligible else None
        newest_timestamp = self._points[-1].timestamp_ms if self._points else None
        return IndexHistoryContract(
            source_point_count=len(self._points),
            interval_counts=self._interval_counts,
            modal_interval_ms=self._modal_interval_ms,
            newest_response_timestamp_ms=newest_timestamp,
            newest_response_age_ms=(
                trusted_time.lower_ms - newest_timestamp if newest_timestamp is not None else None
            ),
            newest_response_point_excluded_by_completion_cutoff=(
                bool(self._points)
                and (not eligible or eligible[-1].timestamp_ms != self._points[-1].timestamp_ms)
            ),
            latest_source_timestamp_ms=latest_timestamp,
            latest_source_age_ms=(
                trusted_time.lower_ms - latest_timestamp if latest_timestamp is not None else None
            ),
            exact_suffix_point_count=suffix_count,
            exact_suffix_minutes=max(0, suffix_count - 1) * self.return_interval_minutes,
            revision_count=self._revision_count,
            revision_pending=self._revision_pending,
            revised_timestamps_ms=self._revised_timestamps,
        )


__all__ = [
    "IndexHistoryContract",
    "IndexHistoryPoint",
    "IndexHistoryReducer",
    "IndexHistoryState",
]

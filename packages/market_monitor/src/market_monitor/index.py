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


@dataclass(frozen=True)
class IndexPublicationBoundary:
    session_epoch: int
    ingress_seq: int
    received_monotonic_ms: int
    causal_seq: int

    def __post_init__(self) -> None:
        values = (
            self.session_epoch,
            self.ingress_seq,
            self.received_monotonic_ms,
            self.causal_seq,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("index publication boundary fields must be integers")
        if self.session_epoch <= 0 or self.ingress_seq < 0 or self.received_monotonic_ms < 0:
            raise ValueError("index publication boundary identity is invalid")
        if self.causal_seq < 0:
            raise ValueError("index publication causal sequence must be non-negative")


class IndexAvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    WARMUP = "WARMUP"
    WINDOW_GAP = "WINDOW_GAP"
    SOURCE_STALE = "SOURCE_STALE"
    CONTINUITY_GAP = "CONTINUITY_GAP"


class BaselinePublicationPhase(StrEnum):
    CURRENT = "CURRENT"
    TIME_BOUNDARY_PENDING = "TIME_BOUNDARY_PENDING"
    WATERMARK_PENDING = "WATERMARK_PENDING"


@dataclass(frozen=True)
class PublishedIndexTail:
    generation: int
    global_continuity_epoch: int
    closes: tuple[MinuteClose, ...]
    published_end_ms: int
    published_tail_last_minute_start_ms: int
    first_publish_boundary: IndexPublicationBoundary
    proof_lower_ms: int
    proof_watermark_ms: int

    def __post_init__(self) -> None:
        if self.generation <= 0 or self.global_continuity_epoch <= 0:
            raise ValueError("published index tail generation and epoch must be positive")
        if not self.closes:
            raise ValueError("published index tail requires at least one immutable close")
        if self.published_tail_last_minute_start_ms % MINUTE_MS:
            raise ValueError("published index tail minute must be 60-second aligned")
        if self.published_end_ms != self.published_tail_last_minute_start_ms + MINUTE_MS:
            raise ValueError("published index tail end does not match its last minute")
        if self.closes[-1].minute_start_ms != self.published_tail_last_minute_start_ms:
            raise ValueError("published index tail closes do not end at the declared minute")
        if any(
            later.minute_start_ms - earlier.minute_start_ms != MINUTE_MS
            for earlier, later in pairwise(self.closes)
        ):
            raise ValueError("published index tail closes must be consecutive")
        if self.proof_lower_ms < self.published_end_ms:
            raise ValueError("published index tail lower-time proof is insufficient")
        if self.proof_watermark_ms < self.published_end_ms:
            raise ValueError("published index tail watermark proof is insufficient")


@dataclass(frozen=True)
class IndexBaselineState:
    availability: IndexAvailabilityState
    publication_phase: BaselinePublicationPhase
    closes: tuple[MinuteClose, ...] = ()
    expected_latest_close_start_ms: int | None = None
    published_tail_last_minute_start_ms: int | None = None
    target_successor_minute_start_ms: int | None = None
    published_tail: PublishedIndexTail | None = None
    reason: str | None = None

    @property
    def prices(self) -> tuple[Decimal, ...] | None:
        if self.availability is not IndexAvailabilityState.AVAILABLE:
            return None
        return tuple(close.price for close in self.closes)

    @property
    def economic_identity(self) -> tuple[object, ...] | None:
        if self.availability is not IndexAvailabilityState.AVAILABLE:
            return None
        if self.published_tail is None:
            raise RuntimeError("available baseline lacks a published tail")
        return tuple(self.closes)


@dataclass(frozen=True)
class IndexPublicationUpdate:
    previous_tail: PublishedIndexTail | None
    published_tail: PublishedIndexTail | None
    previous_phase: BaselinePublicationPhase
    phase: BaselinePublicationPhase
    expected_latest_close_start_ms: int | None
    published_advanced: bool
    published_minute_count: int
    epoch_rebound: bool
    currentness_lost_reason: str | None


class IndexMinuteReducer:
    def __init__(self, maximum_return_count: int) -> None:
        if maximum_return_count <= 0:
            raise ValueError("maximum return count must be positive")
        self._maximum_close_count = maximum_return_count + 1
        self._coverage_start_ms: int | None = None
        self._generation: int | None = None
        self._last_source_timestamp_ms: int | None = None
        self._watermark_ms: int | None = None
        self._working: dict[int, MinuteClose] = {}
        self._sealed: list[MinuteClose] = []
        self._continuity_gap = False
        self._published_tail: PublishedIndexTail | None = None
        self._publication_phase = BaselinePublicationPhase.CURRENT

    @property
    def sealed(self) -> tuple[MinuteClose, ...]:
        return tuple(self._sealed)

    @property
    def has_accepted_tick(self) -> bool:
        return self._last_source_timestamp_ms is not None

    @property
    def generation(self) -> int | None:
        return self._generation

    @property
    def published_tail(self) -> PublishedIndexTail | None:
        return self._published_tail

    @property
    def publication_phase(self) -> BaselinePublicationPhase:
        return self._publication_phase

    def start_continuous_coverage(
        self,
        source_timestamp_ms: int,
        *,
        generation: int = 1,
    ) -> None:
        if source_timestamp_ms < 0:
            raise ValueError("coverage start must be non-negative")
        if generation <= 0:
            raise ValueError("index generation must be positive")
        self._coverage_start_ms = source_timestamp_ms
        self._generation = generation
        self._last_source_timestamp_ms = None
        self._watermark_ms = None
        self._working.clear()
        self._sealed.clear()
        self._continuity_gap = False
        self._published_tail = None
        self._publication_phase = BaselinePublicationPhase.CURRENT

    def gap(self) -> None:
        self._coverage_start_ms = None
        self._generation = None
        self._last_source_timestamp_ms = None
        self._watermark_ms = None
        self._working.clear()
        self._sealed.clear()
        self._continuity_gap = True
        self._published_tail = None
        self._publication_phase = BaselinePublicationPhase.CURRENT

    def invalidate_publication(self) -> None:
        self._published_tail = None
        self._publication_phase = BaselinePublicationPhase.CURRENT

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

    def publish_ready(
        self,
        *,
        trusted_time: TimeInterval,
        source_stale_deadline_ms: int,
        generation: int,
        global_continuity_epoch: int,
        boundary: IndexPublicationBoundary,
    ) -> IndexPublicationUpdate:
        if source_stale_deadline_ms <= 0:
            raise ValueError("index source stale deadline must be positive")
        if generation <= 0 or global_continuity_epoch <= 0:
            raise ValueError("publication generation and epoch must be positive")
        previous_tail = self._published_tail
        previous_phase = self._publication_phase
        if self._continuity_gap or self._coverage_start_ms is None:
            self.invalidate_publication()
            return IndexPublicationUpdate(
                previous_tail=previous_tail,
                published_tail=None,
                previous_phase=previous_phase,
                phase=self._publication_phase,
                expected_latest_close_start_ms=None,
                published_advanced=False,
                published_minute_count=0,
                epoch_rebound=False,
                currentness_lost_reason=("INDEX_CONTINUITY_GAP" if self._continuity_gap else None),
            )
        if self._generation != generation:
            self.gap()
            raise ContinuityGap("index publication generation changed without coverage reset")
        if self._watermark_ms is None or self._last_source_timestamp_ms is None:
            self.invalidate_publication()
            return IndexPublicationUpdate(
                previous_tail=previous_tail,
                published_tail=None,
                previous_phase=previous_phase,
                phase=self._publication_phase,
                expected_latest_close_start_ms=None,
                published_advanced=False,
                published_minute_count=0,
                epoch_rebound=False,
                currentness_lost_reason=None,
            )
        expected_latest = self._expected_latest_start(trusted_time)
        if trusted_time.lower_ms - self._last_source_timestamp_ms > source_stale_deadline_ms:
            self.invalidate_publication()
            return IndexPublicationUpdate(
                previous_tail=previous_tail,
                published_tail=None,
                previous_phase=previous_phase,
                phase=self._publication_phase,
                expected_latest_close_start_ms=expected_latest,
                published_advanced=False,
                published_minute_count=0,
                epoch_rebound=False,
                currentness_lost_reason="INDEX_SOURCE_STALE",
            )

        epoch_rebound = previous_tail is not None and (
            previous_tail.generation != generation
            or previous_tail.global_continuity_epoch != global_continuity_epoch
        )
        suffix = self._continuous_suffix_ending(expected_latest)
        published_minute_count = 0
        created_tail = False
        previous_last = (
            previous_tail.published_tail_last_minute_start_ms
            if previous_tail is not None
            and previous_tail.generation == generation
            and previous_tail.global_continuity_epoch == global_continuity_epoch
            else None
        )
        if suffix and (previous_last is None or expected_latest > previous_last or epoch_rebound):
            self._published_tail = PublishedIndexTail(
                generation=generation,
                global_continuity_epoch=global_continuity_epoch,
                closes=suffix,
                published_end_ms=expected_latest + MINUTE_MS,
                published_tail_last_minute_start_ms=expected_latest,
                first_publish_boundary=boundary,
                proof_lower_ms=trusted_time.lower_ms,
                proof_watermark_ms=self._watermark_ms,
            )
            created_tail = True
            if previous_last is None:
                published_minute_count = 1
            elif expected_latest > previous_last:
                published_minute_count = (expected_latest - previous_last) // MINUTE_MS

        self._publication_phase = self._phase_for_immediate_successor(
            trusted_time,
            previous_phase=previous_phase,
            previous_tail=previous_tail,
        )
        return IndexPublicationUpdate(
            previous_tail=previous_tail,
            published_tail=self._published_tail,
            previous_phase=previous_phase,
            phase=self._publication_phase,
            expected_latest_close_start_ms=expected_latest,
            published_advanced=created_tail,
            published_minute_count=published_minute_count,
            epoch_rebound=epoch_rebound,
            currentness_lost_reason=None,
        )

    def current_tail(
        self,
        return_count: int,
        *,
        trusted_time: TimeInterval,
        source_stale_deadline_ms: int,
    ) -> IndexBaselineState:
        if return_count <= 0:
            raise ValueError("return_count must be positive")
        if return_count + 1 > self._maximum_close_count:
            raise ValueError("return_count exceeds the configured reducer maximum")
        if source_stale_deadline_ms <= 0:
            raise ValueError("index source stale deadline must be positive")
        if self._continuity_gap:
            return self._state(
                IndexAvailabilityState.CONTINUITY_GAP,
                reason="INDEX_CONTINUITY_GAP",
            )
        if self._coverage_start_ms is None:
            return self._state(IndexAvailabilityState.WARMUP, reason="INDEX_WARMUP")
        if (
            self._last_source_timestamp_ms is not None
            and trusted_time.lower_ms - self._last_source_timestamp_ms > source_stale_deadline_ms
        ):
            return self._state(
                IndexAvailabilityState.SOURCE_STALE,
                reason="INDEX_SOURCE_STALE",
            )

        expected_latest = self._expected_latest_start(trusted_time)
        tail = self._published_tail
        required_closes = return_count + 1
        if tail is None:
            earliest_required = expected_latest - return_count * MINUTE_MS
            availability = (
                IndexAvailabilityState.WARMUP
                if expected_latest < 0 or self._coverage_start_ms > earliest_required
                else IndexAvailabilityState.WINDOW_GAP
            )
            return self._state(
                availability,
                expected_latest=expected_latest,
                reason=(
                    "INDEX_WARMUP"
                    if availability is IndexAvailabilityState.WARMUP
                    else "INDEX_WINDOW_GAP"
                ),
            )

        actual_latest = tail.published_tail_last_minute_start_ms
        if self._publication_phase is BaselinePublicationPhase.CURRENT:
            if expected_latest > actual_latest:
                earliest_required = expected_latest - return_count * MINUTE_MS
                availability = (
                    IndexAvailabilityState.WARMUP
                    if self._coverage_start_ms > earliest_required
                    else IndexAvailabilityState.WINDOW_GAP
                )
                return self._state(
                    availability,
                    expected_latest=expected_latest,
                    reason=(
                        "INDEX_WARMUP"
                        if availability is IndexAvailabilityState.WARMUP
                        else "INDEX_WINDOW_GAP"
                    ),
                )
            if expected_latest < actual_latest:
                return self._state(
                    IndexAvailabilityState.CONTINUITY_GAP,
                    expected_latest=expected_latest,
                    reason="INDEX_CONTINUITY_GAP",
                )

        # During a publication phase transition the latest proven immutable tail remains
        # the economic input. The phase is diagnostic only; it cannot erase an AVAILABLE
        # per-band baseline window.
        selected_latest = actual_latest
        earliest_required = selected_latest - return_count * MINUTE_MS
        by_minute = {close.minute_start_ms: close for close in tail.closes}
        expected_minutes = tuple(
            earliest_required + offset * MINUTE_MS for offset in range(required_closes)
        )
        closes = tuple(by_minute[minute] for minute in expected_minutes if minute in by_minute)
        if len(closes) != required_closes:
            availability = (
                IndexAvailabilityState.WARMUP
                if self._coverage_start_ms > earliest_required
                else IndexAvailabilityState.WINDOW_GAP
            )
            return self._state(
                availability,
                closes=closes,
                expected_latest=expected_latest,
                reason=(
                    "INDEX_WARMUP"
                    if availability is IndexAvailabilityState.WARMUP
                    else "INDEX_WINDOW_GAP"
                ),
            )
        if closes[-1].minute_start_ms != selected_latest or any(
            later.minute_start_ms - earlier.minute_start_ms != MINUTE_MS
            for earlier, later in pairwise(closes)
        ):
            return self._state(
                IndexAvailabilityState.WINDOW_GAP,
                closes=closes,
                expected_latest=expected_latest,
                reason="INDEX_WINDOW_GAP",
            )
        return self._state(
            IndexAvailabilityState.AVAILABLE,
            closes=closes,
            expected_latest=expected_latest,
            reason=None,
        )

    def _state(
        self,
        availability: IndexAvailabilityState,
        *,
        closes: tuple[MinuteClose, ...] = (),
        expected_latest: int | None = None,
        reason: str | None,
    ) -> IndexBaselineState:
        tail = self._published_tail
        return IndexBaselineState(
            availability=availability,
            publication_phase=(
                self._publication_phase if tail is not None else BaselinePublicationPhase.CURRENT
            ),
            closes=closes,
            expected_latest_close_start_ms=expected_latest,
            published_tail_last_minute_start_ms=(
                None if tail is None else tail.published_tail_last_minute_start_ms
            ),
            target_successor_minute_start_ms=(
                None if tail is None else tail.published_tail_last_minute_start_ms + MINUTE_MS
            ),
            published_tail=tail,
            reason=reason,
        )

    def _expected_latest_start(self, trusted_time: TimeInterval) -> int:
        watermark = self._watermark_ms
        if watermark is None:
            return -MINUTE_MS
        proven_end_ms = min(trusted_time.lower_ms, watermark) // MINUTE_MS * MINUTE_MS
        return proven_end_ms - MINUTE_MS

    def _continuous_suffix_ending(self, expected_latest: int) -> tuple[MinuteClose, ...]:
        if expected_latest < 0:
            return ()
        by_minute = {close.minute_start_ms: close for close in self._sealed}
        if expected_latest not in by_minute:
            return ()
        values: list[MinuteClose] = []
        minute = expected_latest
        while len(values) < self._maximum_close_count and minute in by_minute:
            values.append(by_minute[minute])
            minute -= MINUTE_MS
        values.reverse()
        return tuple(values)

    def _phase_for_immediate_successor(
        self,
        trusted_time: TimeInterval,
        *,
        previous_phase: BaselinePublicationPhase,
        previous_tail: PublishedIndexTail | None,
    ) -> BaselinePublicationPhase:
        tail = self._published_tail
        watermark = self._watermark_ms
        if tail is None or watermark is None:
            return BaselinePublicationPhase.CURRENT
        target_start = tail.published_tail_last_minute_start_ms + MINUTE_MS
        target_end = target_start + MINUTE_MS
        if trusted_time.lower_ms < target_end <= trusted_time.upper_ms:
            raw = BaselinePublicationPhase.TIME_BOUNDARY_PENDING
        elif trusted_time.lower_ms >= target_end and watermark < target_end:
            raw = BaselinePublicationPhase.WATERMARK_PENDING
        else:
            raw = BaselinePublicationPhase.CURRENT
        same_target = (
            previous_tail is not None
            and previous_tail.generation == tail.generation
            and previous_tail.global_continuity_epoch == tail.global_continuity_epoch
            and previous_tail.published_tail_last_minute_start_ms
            == tail.published_tail_last_minute_start_ms
        )
        successor_proven = trusted_time.lower_ms >= target_end and watermark >= target_end
        if (
            same_target
            and not successor_proven
            and previous_phase is BaselinePublicationPhase.TIME_BOUNDARY_PENDING
        ):
            if raw is BaselinePublicationPhase.CURRENT:
                return previous_phase
        if (
            same_target
            and not successor_proven
            and previous_phase is BaselinePublicationPhase.WATERMARK_PENDING
        ):
            if raw in {
                BaselinePublicationPhase.TIME_BOUNDARY_PENDING,
                BaselinePublicationPhase.CURRENT,
            }:
                return previous_phase
        return raw

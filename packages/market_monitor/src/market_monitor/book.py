from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from market_monitor.types import (
    ContinuityGap,
    PriceLevel,
    SourceDataError,
    decimal_from_source,
    require_int,
    require_list,
    require_mapping,
    require_str,
)


class BookState(StrEnum):
    UNKNOWN = "UNKNOWN"
    USABLE = "USABLE"


@dataclass
class ContinuousOrderBook:
    instrument_name: str
    state: BookState = BookState.UNKNOWN
    reason: str | None = "SNAPSHOT_REQUIRED"
    change_id: int | None = None
    economic_revision: int = 0
    source_timestamp_ms: int | None = None
    last_mutation_monotonic_ms: int | None = None
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)

    def invalidate(self, reason: str) -> None:
        self.state = BookState.UNKNOWN
        self.reason = reason
        self.change_id = None
        self.economic_revision = 0
        self.source_timestamp_ms = None
        self.last_mutation_monotonic_ms = None
        self.bids.clear()
        self.asks.clear()

    def apply(self, payload: object, monotonic_ms: int) -> bool:
        data = require_mapping(payload, "book")
        instrument_name = require_str(data.get("instrument_name"), "book.instrument_name")
        if instrument_name != self.instrument_name:
            raise SourceDataError("book instrument does not match subscription")
        message_type = require_str(data.get("type"), "book.type")
        change_id = require_int(data.get("change_id"), "book.change_id")
        source_timestamp_ms = require_int(data.get("timestamp"), "book.timestamp")
        if source_timestamp_ms < 0:
            raise SourceDataError("book.timestamp must be non-negative")
        if self.source_timestamp_ms is not None and source_timestamp_ms < self.source_timestamp_ms:
            self.invalidate("SOURCE_TIMESTAMP_GAP")
            raise ContinuityGap("book source timestamp regressed")

        if message_type == "snapshot":
            bids = _apply_levels({}, data.get("bids"), "book.bids")
            asks = _apply_levels({}, data.get("asks"), "book.asks")
        elif message_type == "change":
            if self.state is not BookState.USABLE or self.change_id is None:
                self.invalidate("SNAPSHOT_REQUIRED")
                raise ContinuityGap("book change arrived before usable snapshot")
            prev_change_id = require_int(data.get("prev_change_id"), "book.prev_change_id")
            if prev_change_id != self.change_id:
                self.invalidate("CHANGE_ID_GAP")
                raise ContinuityGap("book change_id continuity gap")
            bids = _apply_levels(dict(self.bids), data.get("bids"), "book.bids")
            asks = _apply_levels(dict(self.asks), data.get("asks"), "book.asks")
        else:
            raise SourceDataError("book.type must be snapshot or change")

        _validate_uncrossed(bids, asks)
        changed = message_type == "snapshot" or bids != self.bids or asks != self.asks
        self.bids = bids
        self.asks = asks
        self.change_id = change_id
        self.source_timestamp_ms = source_timestamp_ms
        self.state = BookState.USABLE
        self.reason = None
        if changed:
            self.economic_revision += 1
            self.last_mutation_monotonic_ms = monotonic_ms
        return changed

    def levels(self, side: str) -> tuple[PriceLevel, ...]:
        if self.state is not BookState.USABLE:
            raise ContinuityGap(self.reason or "book is unavailable")
        if side == "bid":
            items = sorted(self.bids.items(), reverse=True)
        elif side == "ask":
            items = sorted(self.asks.items())
        else:
            raise ValueError("side must be bid or ask")
        return tuple(PriceLevel(price, amount) for price, amount in items)


def _apply_levels(
    current: dict[Decimal, Decimal], raw_levels: object, field: str
) -> dict[Decimal, Decimal]:
    for index, raw_level in enumerate(require_list(raw_levels, field)):
        level = require_list(raw_level, f"{field}[{index}]")
        if len(level) != 3:
            raise SourceDataError(f"{field}[{index}] must contain action, price, amount")
        action = require_str(level[0], f"{field}[{index}].action")
        price = decimal_from_source(level[1], f"{field}[{index}].price")
        amount = decimal_from_source(level[2], f"{field}[{index}].amount")
        if amount < 0:
            raise SourceDataError(f"{field}[{index}].amount must be non-negative")
        if action == "delete":
            if amount != 0:
                raise SourceDataError(f"{field}[{index}] delete amount must be zero")
            current.pop(price, None)
        elif action in {"new", "change"}:
            if amount <= 0:
                raise SourceDataError(f"{field}[{index}] live amount must be positive")
            current[price] = amount
        else:
            raise SourceDataError(f"{field}[{index}] has unsupported action")
    return current


def _validate_uncrossed(bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal]) -> None:
    if bids and asks and max(bids) >= min(asks):
        raise SourceDataError("book is crossed or locked")

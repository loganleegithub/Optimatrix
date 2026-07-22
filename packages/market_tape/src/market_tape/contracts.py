"""Strategy-neutral canonical public-market contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum


class EventKind(StrEnum):
    INSTRUMENT = "INSTRUMENT"
    SUBSCRIPTION_START = "SUBSCRIPTION_START"
    TICKER = "TICKER"
    TRADE = "TRADE"
    TRADE_GAP = "TRADE_GAP"
    BOOK_SNAPSHOT = "BOOK_SNAPSHOT"
    BOOK_CHANGE = "BOOK_CHANGE"
    BOOK_GAP = "BOOK_GAP"
    HEARTBEAT = "HEARTBEAT"
    RECONNECT = "RECONNECT"
    PLATFORM_STATE = "PLATFORM_STATE"


class InstrumentKind(StrEnum):
    OPTION = "OPTION"
    PERPETUAL = "PERPETUAL"
    FUTURE = "FUTURE"
    COMBO = "COMBO"


class OptionKind(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


def canonical_value(value: object) -> object:
    if is_dataclass(value):
        return {item.name: canonical_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, set):
        return [canonical_value(item) for item in sorted(value, key=str)]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    capture_seq: int
    collector_received_at_ms: int
    collector_elapsed_ms: int
    exchange_timestamp_ms: int | None
    channel: str
    event_kind: EventKind
    instrument_name: str | None
    raw_payload: str

    def __post_init__(self) -> None:
        if self.capture_seq <= 0:
            raise ValueError("capture_seq must be positive")
        if self.collector_received_at_ms <= 0:
            raise ValueError("collector timestamp must be positive")
        if self.collector_elapsed_ms < 0:
            raise ValueError("collector elapsed time cannot be negative")
        if not self.channel:
            raise ValueError("channel is required")
        if self.exchange_timestamp_ms is not None and (
            not isinstance(self.exchange_timestamp_ms, int)
            or isinstance(self.exchange_timestamp_ms, bool)
            or self.exchange_timestamp_ms <= 0
        ):
            raise ValueError("exchange timestamp must be a positive integer")
        if self.event_kind in {EventKind.TICKER, EventKind.TRADE, EventKind.TRADE_GAP} and (
            self.exchange_timestamp_ms is None
        ):
            raise ValueError("market event requires an exchange timestamp")

    @property
    def collector_received_at(self) -> datetime:
        return datetime.fromtimestamp(self.collector_received_at_ms / 1_000, tz=UTC)

    @property
    def source_at_ms(self) -> int:
        return self.exchange_timestamp_ms or self.collector_received_at_ms

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_name: str
    kind: InstrumentKind
    active: bool
    source_capture_seq: int
    contract_size: Decimal
    min_trade_amount: Decimal
    amount_step: Decimal
    taker_commission: Decimal
    expiration_timestamp_ms: int | None = None
    strike: Decimal | None = None
    option_kind: OptionKind | None = None

    def __post_init__(self) -> None:
        if not self.instrument_name:
            raise ValueError("instrument name is required")
        if self.source_capture_seq <= 0:
            raise ValueError("instrument source capture sequence must be positive")
        if self.kind is InstrumentKind.OPTION and (
            self.expiration_timestamp_ms is None or self.strike is None or self.option_kind is None
        ):
            raise ValueError("option instrument is incomplete")
        if self.contract_size <= 0 or self.min_trade_amount <= 0 or self.amount_step <= 0:
            raise ValueError("instrument quantity metadata must be positive")
        if self.taker_commission < 0:
            raise ValueError("instrument commission cannot be negative")


@dataclass(frozen=True, slots=True)
class TickerFact:
    instrument_name: str
    capture_seq: int
    source_at_ms: int
    observed_elapsed_ms: int
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.capture_seq <= 0 or self.source_at_ms <= 0:
            raise ValueError("ticker capture sequence and source time must be positive")
        if self.observed_elapsed_ms < 0:
            raise ValueError("ticker observed elapsed time cannot be negative")


@dataclass(frozen=True, slots=True)
class TradeFact:
    instrument_name: str
    capture_seq: int
    trade_seq: int
    source_at_ms: int
    observed_elapsed_ms: int
    price: Decimal
    amount: Decimal
    direction: str
    liquidation: str | None = None

    def __post_init__(self) -> None:
        if self.trade_seq <= 0 or self.source_at_ms <= 0:
            raise ValueError("trade sequence and source time must be positive")
        if self.price <= 0 or self.amount <= 0:
            raise ValueError("trade price and amount must be positive")
        if self.direction not in {"buy", "sell"}:
            raise ValueError("trade direction must be buy or sell")


@dataclass(slots=True)
class BookState:
    instrument_name: str
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    change_id: int | None = None
    valid: bool = False
    source_at_ms: int | None = None
    capture_seq: int | None = None

    def best_bid(self) -> tuple[Decimal, Decimal] | None:
        if not self.valid or not self.bids:
            return None
        price = max(self.bids)
        return price, self.bids[price]

    def best_ask(self) -> tuple[Decimal, Decimal] | None:
        if not self.valid or not self.asks:
            return None
        price = min(self.asks)
        return price, self.asks[price]


@dataclass(frozen=True, slots=True)
class GapFact:
    instrument_name: str
    capture_seq: int
    source_at_ms: int
    observed_elapsed_ms: int
    expected_sequence: int | None
    observed_sequence: int | None


@dataclass(frozen=True, slots=True)
class PlatformState:
    capture_seq: int
    source_at_ms: int
    observed_elapsed_ms: int
    state: str
    locked: bool | None
    status_capture_seq: int | None
    source_capture_seqs: tuple[int, ...]

    def __post_init__(self) -> None:
        expected_locked = {"OPEN": False, "LOCKED": True, "UNKNOWN": None}
        if self.state not in expected_locked or self.locked is not expected_locked[self.state]:
            raise ValueError("platform state and lock flag are inconsistent")
        if self.status_capture_seq is not None and (
            self.status_capture_seq <= 0 or self.status_capture_seq > self.capture_seq
        ):
            raise ValueError("platform status source sequence is invalid")
        if tuple(sorted(set(self.source_capture_seqs))) != self.source_capture_seqs:
            raise ValueError("platform source sequences must be sorted and unique")
        if self.capture_seq not in self.source_capture_seqs or any(
            item <= 0 or item > self.capture_seq for item in self.source_capture_seqs
        ):
            raise ValueError("platform source sequence is invalid")


@dataclass(frozen=True, slots=True)
class MarketTapeSnapshot:
    as_of_capture_seq: int
    collector_as_of_ms: int
    instruments: tuple[Instrument, ...]
    tickers: tuple[TickerFact, ...]
    trades: tuple[TradeFact, ...]
    books: tuple[BookState, ...]
    trade_gaps: tuple[GapFact, ...]
    book_gaps: tuple[GapFact, ...]
    reconnect_capture_seq: int | None
    reconnect_at_ms: int | None
    platform_state: PlatformState | None

    @property
    def digest(self) -> str:
        return canonical_digest(self)

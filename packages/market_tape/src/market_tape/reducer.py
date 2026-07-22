"""Deterministic canonical event reducer."""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import pairwise
from typing import cast

from market_tape.contracts import (
    BookState,
    CanonicalEvent,
    CatalogSnapshot,
    EventKind,
    GapFact,
    Instrument,
    InstrumentKind,
    MarketTapeSnapshot,
    OptionKind,
    PlatformState,
    TickerFact,
    TradeFact,
)


class TapeContractError(ValueError):
    pass


def _payload(event: CanonicalEvent) -> dict[str, object]:
    try:
        value = json.loads(event.raw_payload)
    except json.JSONDecodeError as error:
        raise TapeContractError("canonical payload is not valid JSON") from error
    if not isinstance(value, dict):
        raise TapeContractError("canonical payload must be an object")
    return cast(dict[str, object], value)


def _decimal(value: object, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TapeContractError(f"missing decimal field: {field}")
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError) as error:
        raise TapeContractError(f"invalid decimal field: {field}") from error
    if not result.is_finite():
        raise TapeContractError(f"invalid decimal field: {field}")
    return result


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TapeContractError(f"missing integer field: {field}")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TapeContractError(f"required positive integer field: {field}")
    return value


def _require_market_envelope(event: CanonicalEvent, source_at_ms: int) -> None:
    if event.exchange_timestamp_ms != source_at_ms:
        raise TapeContractError("market payload timestamp does not match canonical envelope")


class MarketTapeReducer:
    def __init__(self) -> None:
        self._last_capture_seq = 0
        self._last_collector_received_at_ms = 0
        self._last_collector_elapsed_ms: int | None = None
        self._instruments: dict[str, Instrument] = {}
        self._catalog_snapshot: CatalogSnapshot | None = None
        self._tickers: dict[str, TickerFact] = {}
        self._trades: list[TradeFact] = []
        self._trade_sequences: dict[str, int] = {}
        self._trade_source_times: dict[str, int] = {}
        self._books: dict[str, BookState] = {}
        self._trade_gaps: list[GapFact] = []
        self._book_gaps: list[GapFact] = []
        self._reconnect_capture_seq: int | None = None
        self._reconnect_at_ms: int | None = None
        self._platform_state: PlatformState | None = None
        self._platform_subscription_capture_seq: int | None = None
        self._platform_status_capture_seq: int | None = None

    @property
    def last_capture_seq(self) -> int:
        return self._last_capture_seq

    def ingest(self, event: CanonicalEvent) -> None:
        if event.capture_seq != self._last_capture_seq + 1:
            raise TapeContractError("capture sequence must be contiguous and start at one")
        if (
            self._last_collector_elapsed_ms is not None
            and event.collector_elapsed_ms < self._last_collector_elapsed_ms
        ):
            raise TapeContractError("collector elapsed time must be nondecreasing")
        payload = _payload(event)
        if event.event_kind is EventKind.INSTRUMENT:
            self._ingest_instrument(event, payload)
        elif event.event_kind is EventKind.CATALOG_SNAPSHOT:
            self._ingest_catalog_snapshot(event, payload)
        elif event.event_kind is EventKind.TICKER:
            self._ingest_ticker(event, payload)
        elif event.event_kind in {EventKind.TRADE, EventKind.TRADE_GAP}:
            self._ingest_trade(event, payload)
        elif event.event_kind in {
            EventKind.BOOK_SNAPSHOT,
            EventKind.BOOK_CHANGE,
            EventKind.BOOK_GAP,
        }:
            self._ingest_book(event, payload)
        elif event.event_kind is EventKind.RECONNECT:
            self._reconnect_capture_seq = event.capture_seq
            self._reconnect_at_ms = event.collector_received_at_ms
            self._platform_state = None
            self._platform_subscription_capture_seq = None
            self._platform_status_capture_seq = None
            for book in self._books.values():
                book.valid = False
        elif event.event_kind is EventKind.SUBSCRIPTION_START:
            stream = payload.get("stream")
            if not isinstance(stream, str) or not stream:
                raise TapeContractError("subscription start requires a stream")
            if stream == "platform_state":
                self._platform_subscription_capture_seq = event.capture_seq
                self._platform_status_capture_seq = None
                if self._platform_state is not None and self._platform_state.locked is not True:
                    self._platform_state = None
        elif event.event_kind is EventKind.PLATFORM_STATE:
            status_event = event.channel == "public/status"
            recognized_status_capture_seq = (
                event.capture_seq
                if status_event and payload.get("status_capture_seq") == event.capture_seq
                else self._platform_status_capture_seq
            )
            self._platform_state = self._validated_platform_state(
                event,
                payload,
                recognized_status_capture_seq=recognized_status_capture_seq,
                status_event=status_event,
            )
            if status_event and recognized_status_capture_seq == event.capture_seq:
                self._platform_status_capture_seq = event.capture_seq
        self._last_capture_seq = event.capture_seq
        self._last_collector_received_at_ms = event.collector_received_at_ms
        self._last_collector_elapsed_ms = event.collector_elapsed_ms

    def _validated_platform_state(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
        *,
        recognized_status_capture_seq: int | None,
        status_event: bool,
    ) -> PlatformState:
        state = payload.get("state")
        if not isinstance(state, str) or state not in {"OPEN", "LOCKED", "UNKNOWN"}:
            raise TapeContractError("platform state must be OPEN, LOCKED, or UNKNOWN")
        if "locked" not in payload:
            raise TapeContractError("platform state requires an explicit locked value")
        locked = payload["locked"]
        expected_locked: dict[str, bool | None] = {
            "OPEN": False,
            "LOCKED": True,
            "UNKNOWN": None,
        }
        if locked is not expected_locked[state]:
            raise TapeContractError("platform state and lock flag are inconsistent")
        raw_status_capture_seq = payload.get("status_capture_seq")
        if raw_status_capture_seq is not None and (
            not isinstance(raw_status_capture_seq, int)
            or isinstance(raw_status_capture_seq, bool)
            or raw_status_capture_seq <= 0
            or raw_status_capture_seq > event.capture_seq
        ):
            raise TapeContractError("platform status source sequence is invalid")
        if status_event and raw_status_capture_seq not in {None, event.capture_seq}:
            raise TapeContractError("public status sequence must identify its canonical event")
        if (
            not status_event
            and raw_status_capture_seq is not None
            and raw_status_capture_seq != recognized_status_capture_seq
        ):
            raise TapeContractError("platform status source is not an observed public status fact")
        raw_sources = payload.get("source_capture_seqs", [])
        if not isinstance(raw_sources, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in raw_sources
        ):
            raise TapeContractError("platform source sequences must be integer list")
        sources = tuple(raw_sources)
        if tuple(sorted(set(sources))) != sources or any(
            item <= 0 or item >= event.capture_seq for item in sources
        ):
            raise TapeContractError("platform source sequence is invalid")
        lineage = {
            event.capture_seq,
            *sources,
            *(() if recognized_status_capture_seq is None else (recognized_status_capture_seq,)),
            *(
                ()
                if self._platform_subscription_capture_seq is None
                else (self._platform_subscription_capture_seq,)
            ),
        }
        barrier_complete = bool(
            self._platform_subscription_capture_seq is not None
            and recognized_status_capture_seq is not None
            and recognized_status_capture_seq > self._platform_subscription_capture_seq
        )
        effective_state = "UNKNOWN" if state == "OPEN" and not barrier_complete else state
        effective_locked = None if effective_state == "UNKNOWN" else locked
        try:
            return PlatformState(
                capture_seq=event.capture_seq,
                source_at_ms=event.source_at_ms,
                observed_elapsed_ms=event.collector_elapsed_ms,
                state=effective_state,
                locked=effective_locked,
                status_capture_seq=recognized_status_capture_seq,
                source_capture_seqs=tuple(sorted(lineage)),
            )
        except ValueError as error:
            raise TapeContractError(str(error)) from error

    def _ingest_instrument(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
    ) -> None:
        name = event.instrument_name or str(payload.get("instrument_name", ""))
        raw_kind = str(payload.get("kind", "")).lower()
        kinds = {
            "option": InstrumentKind.OPTION,
            "future": InstrumentKind.FUTURE,
            "perpetual": InstrumentKind.PERPETUAL,
            "combo": InstrumentKind.COMBO,
        }
        kind = kinds.get(raw_kind)
        if not name or kind is None:
            raise TapeContractError("instrument event is incomplete")
        raw_option = str(payload.get("option_type", "")).lower()
        option_kind = (
            OptionKind.CALL
            if raw_option == "call"
            else OptionKind.PUT
            if raw_option == "put"
            else None
        )
        raw_expiry = payload.get("expiration_timestamp")
        raw_active = payload.get("active")
        if not isinstance(raw_active, bool):
            raise TapeContractError("instrument active state must be boolean")
        try:
            instrument = Instrument(
                instrument_name=name,
                kind=kind,
                active=raw_active,
                source_capture_seq=event.capture_seq,
                contract_size=_decimal(payload.get("contract_size"), "contract_size"),
                min_trade_amount=_decimal(
                    payload.get("min_trade_amount"),
                    "min_trade_amount",
                ),
                amount_step=_decimal(payload.get("amount_step"), "amount_step"),
                taker_commission=_decimal(
                    payload.get("taker_commission"),
                    "taker_commission",
                ),
                expiration_timestamp_ms=(
                    _positive_int(raw_expiry, "expiration_timestamp")
                    if raw_expiry is not None
                    else None
                ),
                strike=_optional_decimal(payload.get("strike")),
                option_kind=option_kind,
            )
        except (ArithmeticError, ValueError) as error:
            raise TapeContractError("instrument metadata is invalid") from error
        self._instruments[name] = instrument

    def _ingest_catalog_snapshot(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
    ) -> None:
        raw_names = payload.get("instrument_names")
        if not isinstance(raw_names, list) or not all(
            isinstance(item, str) and item for item in raw_names
        ):
            raise TapeContractError("catalog snapshot instrument_names must be a string list")
        source_at_ms = _positive_int(payload.get("timestamp"), "timestamp")
        _require_market_envelope(event, source_at_ms)
        try:
            self._catalog_snapshot = CatalogSnapshot(
                capture_seq=event.capture_seq,
                source_at_ms=source_at_ms,
                observed_elapsed_ms=event.collector_elapsed_ms,
                scope=str(payload.get("scope", "")),
                instrument_names=tuple(raw_names),
            )
        except ValueError as error:
            raise TapeContractError(str(error)) from error

    def _ingest_ticker(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
    ) -> None:
        if event.instrument_name is None:
            raise TapeContractError("ticker event has no instrument")
        source_at_ms = _positive_int(payload.get("timestamp"), "timestamp")
        _require_market_envelope(event, source_at_ms)
        try:
            ticker = TickerFact(
                event.instrument_name,
                event.capture_seq,
                source_at_ms,
                event.collector_elapsed_ms,
                payload,
            )
        except ValueError as error:
            raise TapeContractError("ticker fact is invalid") from error
        previous = self._tickers.get(event.instrument_name)
        if previous is not None and ticker.source_at_ms < previous.source_at_ms:
            return
        self._tickers[event.instrument_name] = ticker

    def _ingest_trade(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
    ) -> None:
        if event.instrument_name is None:
            raise TapeContractError("trade event has no instrument")
        previous = self._trade_sequences.get(event.instrument_name)
        previous_source_at_ms = self._trade_source_times.get(event.instrument_name)
        pending_gaps: list[GapFact] = []
        if event.event_kind is EventKind.TRADE_GAP:
            raw_expected = payload.get("expected_sequence")
            raw_observed = payload.get("observed_sequence")
            pending_gaps.append(
                GapFact(
                    event.instrument_name,
                    event.capture_seq,
                    event.source_at_ms,
                    event.collector_elapsed_ms,
                    (
                        int(raw_expected)
                        if isinstance(raw_expected, int) and not isinstance(raw_expected, bool)
                        else previous + 1
                        if previous is not None
                        else None
                    ),
                    (
                        int(raw_observed)
                        if isinstance(raw_observed, int) and not isinstance(raw_observed, bool)
                        else None
                    ),
                )
            )
        raw_trades = payload.get("trades", [payload])
        if not isinstance(raw_trades, list):
            raise TapeContractError("trades must be an array")
        if not raw_trades and event.event_kind is not EventKind.TRADE_GAP:
            raise TapeContractError("trades must not be empty")
        if not raw_trades:
            _positive_int(event.exchange_timestamp_ms, "exchange_timestamp_ms")
        validated: list[TradeFact] = []
        for raw_item in raw_trades:
            if not isinstance(raw_item, dict):
                raise TapeContractError("trade item must be an object")
            item = cast(dict[str, object], raw_item)
            sequence = _positive_int(item.get("trade_seq"), "trade_seq")
            source_at_ms = _positive_int(item.get("timestamp"), "timestamp")
            try:
                validated.append(
                    TradeFact(
                        instrument_name=event.instrument_name,
                        capture_seq=event.capture_seq,
                        trade_seq=sequence,
                        source_at_ms=source_at_ms,
                        observed_elapsed_ms=event.collector_elapsed_ms,
                        price=_decimal(item.get("price"), "price"),
                        amount=_decimal(item.get("amount"), "amount"),
                        direction=str(item.get("direction", "")),
                        liquidation=(
                            str(item["liquidation"])
                            if item.get("liquidation") is not None
                            else None
                        ),
                    )
                )
            except ValueError as error:
                raise TapeContractError(str(error)) from error
        if validated:
            _require_market_envelope(
                event,
                max(item.source_at_ms for item in validated),
            )
        if any(left.trade_seq >= right.trade_seq for left, right in pairwise(validated)):
            raise TapeContractError("trade batch sequences must be strictly increasing")

        pending_trades: list[TradeFact] = []
        for index, trade in enumerate(validated):
            sequence = trade.trade_seq
            explicit_first_gap = (
                event.event_kind is EventKind.TRADE_GAP
                and index == 0
                and sequence == payload.get("observed_sequence")
            )
            if previous is not None and sequence > previous + 1 and not explicit_first_gap:
                pending_gaps.append(
                    GapFact(
                        event.instrument_name,
                        event.capture_seq,
                        event.source_at_ms,
                        event.collector_elapsed_ms,
                        previous + 1,
                        sequence,
                    )
                )
            if previous is not None and sequence <= previous:
                continue
            if previous_source_at_ms is not None and trade.source_at_ms < previous_source_at_ms:
                raise TapeContractError("trade source time regressed as trade sequence increased")
            pending_trades.append(trade)
            previous = sequence
            previous_source_at_ms = trade.source_at_ms
        self._trades.extend(pending_trades)
        self._trade_gaps.extend(pending_gaps)
        if previous is not None:
            self._trade_sequences[event.instrument_name] = previous
        if previous_source_at_ms is not None:
            self._trade_source_times[event.instrument_name] = previous_source_at_ms

    def _ingest_book(
        self,
        event: CanonicalEvent,
        payload: dict[str, object],
    ) -> None:
        if event.instrument_name is None:
            raise TapeContractError("book event has no instrument")
        current = self._books.get(event.instrument_name)
        book = BookState(
            instrument_name=event.instrument_name,
            bids=(dict(current.bids) if current is not None else {}),
            asks=(dict(current.asks) if current is not None else {}),
            change_id=(current.change_id if current is not None else None),
            valid=(current.valid if current is not None else False),
            source_at_ms=(current.source_at_ms if current is not None else None),
            capture_seq=(current.capture_seq if current is not None else None),
        )
        if event.event_kind is EventKind.BOOK_GAP:
            gap = GapFact(
                event.instrument_name,
                event.capture_seq,
                event.source_at_ms,
                event.collector_elapsed_ms,
                book.change_id + 1 if book.change_id is not None else None,
                None,
            )
            book.valid = False
            self._books[event.instrument_name] = book
            self._book_gaps.append(gap)
            return
        change_id = _required_int(payload.get("change_id"), "change_id")
        previous_change_id = payload.get("prev_change_id")
        if event.event_kind is EventKind.BOOK_CHANGE and (
            book.change_id is None or not book.valid or previous_change_id != book.change_id
        ):
            gap = GapFact(
                event.instrument_name,
                event.capture_seq,
                event.source_at_ms,
                event.collector_elapsed_ms,
                book.change_id,
                int(previous_change_id) if isinstance(previous_change_id, int) else None,
            )
            book.valid = False
            self._books[event.instrument_name] = book
            self._book_gaps.append(gap)
            return
        if event.event_kind is EventKind.BOOK_SNAPSHOT:
            book.bids.clear()
            book.asks.clear()
        self._apply_levels(book.bids, payload.get("bids", []))
        self._apply_levels(book.asks, payload.get("asks", []))
        book.change_id = change_id
        book.valid = True
        book.source_at_ms = event.source_at_ms
        book.capture_seq = event.capture_seq
        self._books[event.instrument_name] = book

    @staticmethod
    def _apply_levels(side: dict[Decimal, Decimal], raw_levels: object) -> None:
        if not isinstance(raw_levels, list):
            raise TapeContractError("book levels must be an array")
        for raw_row in raw_levels:
            if not isinstance(raw_row, list) or len(raw_row) not in {2, 3}:
                raise TapeContractError("book row has invalid shape")
            row = cast(list[object], raw_row)
            offset = 1 if len(row) == 3 else 0
            action = str(row[0]) if len(row) == 3 else "change"
            price = _decimal(row[offset], "book price")
            amount = _decimal(row[offset + 1], "book amount")
            if action == "delete" or amount <= 0:
                side.pop(price, None)
            else:
                side[price] = amount

    def snapshot(self, collector_as_of_ms: int | None = None) -> MarketTapeSnapshot:
        if self._last_capture_seq == 0:
            raise TapeContractError("cannot snapshot empty tape")
        books = tuple(
            BookState(
                instrument_name=item.instrument_name,
                bids=dict(item.bids),
                asks=dict(item.asks),
                change_id=item.change_id,
                valid=item.valid,
                source_at_ms=item.source_at_ms,
                capture_seq=item.capture_seq,
            )
            for item in sorted(self._books.values(), key=lambda value: value.instrument_name)
        )
        return MarketTapeSnapshot(
            as_of_capture_seq=self._last_capture_seq,
            collector_as_of_ms=(
                collector_as_of_ms
                if collector_as_of_ms is not None
                else self._last_collector_received_at_ms
            ),
            instruments=tuple(
                sorted(self._instruments.values(), key=lambda item: item.instrument_name)
            ),
            catalog_snapshot=self._catalog_snapshot,
            tickers=tuple(sorted(self._tickers.values(), key=lambda item: item.instrument_name)),
            trades=tuple(
                sorted(
                    self._trades,
                    key=lambda item: (item.source_at_ms, item.trade_seq, item.capture_seq),
                )
            ),
            books=books,
            trade_gaps=tuple(self._trade_gaps),
            book_gaps=tuple(self._book_gaps),
            reconnect_capture_seq=self._reconnect_capture_seq,
            reconnect_at_ms=self._reconnect_at_ms,
            platform_state=self._platform_state,
        )

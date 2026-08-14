from __future__ import annotations

import json
import math
import threading
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from time import monotonic
from typing import Protocol, cast

from websockets.sync.client import connect

from optimatrix.deribit_snapshot import (
    DeribitSourceError,
    PublicStreamResponse,
)
from optimatrix.products import BTC

DEFAULT_DERIBIT_WEBSOCKET_API = "wss://www.deribit.com/ws/api/v2"
DERIBIT_INDEX_CHANNEL = "deribit_price_index.btc_usd"
DERIBIT_BOOK_INTERVAL = "100ms"
DERIBIT_TICKER_INTERVAL = "100ms"
MAX_STREAM_INSTRUMENTS = 32
MAX_STREAM_CHANNELS = MAX_STREAM_INSTRUMENTS * 2 + 1


class WebSocketConnection(Protocol):
    def send(self, message: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


WebSocketConnectionFactory = Callable[[str, float], WebSocketConnection]


@dataclass(frozen=True)
class RestBookSnapshot:
    instrument_name: str
    result: Mapping[str, object]
    source_timestamp_ms: int
    received_timestamp_ms: int

    def __post_init__(self) -> None:
        _instrument_name(self.instrument_name)
        _boundary(self.source_timestamp_ms, "REST resync source timestamp")
        _boundary(self.received_timestamp_ms, "REST resync receipt timestamp")
        if self.source_timestamp_ms > self.received_timestamp_ms:
            raise ValueError("REST resync source timestamp follows receipt")


RestBookResync = Callable[[str], RestBookSnapshot]
PublicCallAudit = Callable[[str, Mapping[str, object], float], None]


class ForwardObservationGap(DeribitSourceError):
    """One exact stream discontinuity that must reach the Runtime Gap path."""


class WebSocketSequenceGap(ForwardObservationGap):
    def __init__(
        self,
        *,
        instrument_name: str,
        expected_change_id: int,
        actual_previous_change_id: int | None,
    ) -> None:
        self.instrument_name = instrument_name
        self.expected_change_id = expected_change_id
        self.actual_previous_change_id = actual_previous_change_id
        super().__init__(
            "WEBSOCKET_BOOK_SEQUENCE_GAP:"
            f"{instrument_name}:expected_prev={expected_change_id}:"
            f"actual_prev={actual_previous_change_id}"
        )


class _CutNotReady(RuntimeError):
    pass


@dataclass
class _BookState:
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    change_id: int | None = None
    source_timestamp_ms: int | None = None
    received_timestamp_ms: int | None = None
    epoch: int = 0
    ready: bool = False
    resync_seeded: bool = False


@dataclass
class _TickerState:
    data: dict[str, object] = field(default_factory=dict)
    source_timestamp_ms: int | None = None
    received_timestamp_ms: int | None = None
    epoch: int = 0
    ready: bool = False


@dataclass
class _InstrumentState:
    book: _BookState = field(default_factory=_BookState)
    ticker: _TickerState = field(default_factory=_TickerState)


@dataclass(frozen=True)
class BtcWebSocketCut:
    continuity_epoch: int
    index_price: Decimal
    source_floor_ms: int
    source_watermark_ms: int
    received_floor_ms: int
    received_watermark_ms: int
    instrument_names: tuple[str, ...]
    index_response: PublicStreamResponse
    history_response: PublicStreamResponse
    book_responses: tuple[tuple[str, PublicStreamResponse], ...]

    def __post_init__(self) -> None:
        if self.continuity_epoch <= 0:
            raise ValueError("WebSocket cut continuity epoch must be positive")
        if not self.index_price.is_finite() or self.index_price <= 0:
            raise ValueError("WebSocket cut index price must be positive")
        if self.source_floor_ms > self.source_watermark_ms:
            raise ValueError("WebSocket cut source watermark is invalid")
        if self.received_floor_ms > self.received_watermark_ms:
            raise ValueError("WebSocket cut receipt watermark is invalid")
        if tuple(sorted(self.instrument_names)) != self.instrument_names:
            raise ValueError("WebSocket cut instruments must be sorted")
        if tuple(name for name, _response in self.book_responses) != self.instrument_names:
            raise ValueError("WebSocket cut books do not match its instrument universe")

    def client(
        self,
        *,
        instrument_metadata: Sequence[Mapping[str, object]],
        depth: int,
    ) -> BtcWebSocketCutClient:
        return BtcWebSocketCutClient(
            cut=self,
            instrument_metadata=instrument_metadata,
            depth=depth,
        )


class BtcWebSocketCutClient:
    """Immutable RPC-shaped view consumed by the existing BTC snapshot evaluator."""

    def __init__(
        self,
        *,
        cut: BtcWebSocketCut,
        instrument_metadata: Sequence[Mapping[str, object]],
        depth: int,
    ) -> None:
        if depth <= 0:
            raise ValueError("WebSocket cut depth must be positive")
        metadata = tuple(dict(item) for item in instrument_metadata)
        metadata_names = tuple(sorted(str(item.get("instrument_name")) for item in metadata))
        if metadata_names != cut.instrument_names:
            raise ValueError("WebSocket cut metadata does not match its instrument universe")
        self._cut = cut
        self._metadata = metadata
        self._depth = depth
        self._books = dict(cut.book_responses)

    def call(self, method: str, params: Mapping[str, object]) -> object:
        if method == "public/get_index_price":
            if dict(params) != {"index_name": BTC.price_index}:
                raise ValueError("WebSocket cut index parameters are outside BTC")
            return self._cut.index_response
        if method == "public/get_instruments":
            expected = {"currency": BTC.public_currency, "kind": "option", "expired": False}
            if dict(params) != expected:
                raise ValueError("WebSocket cut instrument parameters are outside BTC options")
            return list(self._metadata)
        if method == "public/get_index_chart_data":
            if dict(params) != {"index_name": BTC.price_index, "range": "2d"}:
                raise ValueError("WebSocket cut history parameters are outside BTC 2d")
            return self._cut.history_response
        if method == "public/get_order_book":
            name = params.get("instrument_name")
            if params.get("depth") != self._depth or not isinstance(name, str):
                raise ValueError("WebSocket cut book parameters are invalid")
            try:
                return self._books[name]
            except KeyError as exc:
                raise DeribitSourceError(
                    f"WebSocket cut lacks requested instrument: {name}"
                ) from exc
        raise ValueError("WebSocket cut exposes no other public methods")


class BtcWebSocketCache:
    """BTC-only in-memory cache with per-instrument sequence and cut watermarks."""

    def __init__(self, *, maximum_instruments: int = MAX_STREAM_INSTRUMENTS) -> None:
        if maximum_instruments < 4 or maximum_instruments > MAX_STREAM_INSTRUMENTS:
            raise ValueError("WebSocket cache instrument bound must be between four and 32")
        self.maximum_instruments = maximum_instruments
        self._condition = threading.Condition()
        self._desired_names: tuple[str, ...] = ()
        self._states: dict[str, _InstrumentState] = {}
        self._connected = False
        self._epoch = 0
        self._index_price: Decimal | None = None
        self._index_source_timestamp_ms: int | None = None
        self._index_received_timestamp_ms: int | None = None
        self._index_epoch = 0
        self._history: list[tuple[int, Decimal]] = []
        self._history_cadence_ms = 300_000
        self._history_received_timestamp_ms: int | None = None
        self._pending_gaps: deque[str] = deque(maxlen=MAX_STREAM_CHANNELS)

    @property
    def continuity_epoch(self) -> int:
        with self._condition:
            return self._epoch

    @property
    def desired_channels(self) -> tuple[str, ...]:
        with self._condition:
            return _channels(self._desired_names)

    def configure_instruments(self, instrument_names: Sequence[str]) -> None:
        names = tuple(sorted(instrument_names))
        if len(names) < 4 or len(names) > self.maximum_instruments:
            raise ValueError("WebSocket instrument universe must contain between four and 32 names")
        if len(set(names)) != len(names):
            raise ValueError("WebSocket instrument universe must be unique")
        for name in names:
            _instrument_name(name)
        with self._condition:
            if names == self._desired_names:
                return
            prior = self._states
            self._states = {name: prior.get(name, _InstrumentState()) for name in names}
            self._desired_names = names
            self._condition.notify_all()

    def seed_index_history(
        self,
        history: Sequence[tuple[int, Decimal]],
        *,
        received_timestamp_ms: int,
    ) -> None:
        _boundary(received_timestamp_ms, "history receipt timestamp")
        points = list(history)
        if len(points) < 3:
            raise ValueError("WebSocket history bootstrap requires at least three points")
        previous = -1
        for timestamp_ms, price in points:
            _boundary(timestamp_ms, "history timestamp")
            if timestamp_ms <= previous or not price.is_finite() or price <= 0:
                raise ValueError("WebSocket history bootstrap must be chronological and positive")
            if timestamp_ms > received_timestamp_ms:
                raise ValueError("WebSocket history bootstrap follows its receipt boundary")
            previous = timestamp_ms
        intervals = [current[0] - prior[0] for prior, current in pairwise(points)]
        cadence = Counter(intervals).most_common(1)[0][0]
        if cadence <= 0 or cadence > 15 * 60_000:
            raise ValueError("WebSocket history bootstrap cadence is invalid")
        with self._condition:
            self._history = points
            self._history_cadence_ms = cadence
            self._history_received_timestamp_ms = received_timestamp_ms
            self._condition.notify_all()

    def latest_index_price(self) -> Decimal:
        with self._condition:
            if self._index_price is not None:
                return self._index_price
            if self._history:
                return self._history[-1][1]
        raise DeribitSourceError("WebSocket index price is not initialized")

    def index_history(self) -> tuple[tuple[int, Decimal], ...]:
        with self._condition:
            return tuple(self._history)

    def begin_connection(self) -> int:
        with self._condition:
            self._epoch += 1
            self._connected = True
            self._index_price = None
            self._index_source_timestamp_ms = None
            self._index_received_timestamp_ms = None
            self._index_epoch = 0
            for name in self._desired_names:
                self._states[name] = _InstrumentState()
            self._condition.notify_all()
            return self._epoch

    def disconnect(self, *, reason: str) -> None:
        if not reason or reason != reason.strip():
            raise ValueError("WebSocket disconnect reason must be non-empty text")
        with self._condition:
            if self._connected:
                gap = f"WEBSOCKET_DISCONNECTED:epoch={self._epoch}:reason={reason}"
            else:
                gap = f"WEBSOCKET_CONNECT_FAILED:reason={reason}"
            if not self._pending_gaps or self._pending_gaps[-1] != gap:
                self._pending_gaps.append(gap)
            self._connected = False
            self._index_epoch = 0
            for state in self._states.values():
                state.book.ready = False
                state.ticker.ready = False
            self._condition.notify_all()

    def accept_subscription(
        self,
        *,
        channel: str,
        data: object,
        received_timestamp_ms: int,
    ) -> None:
        _boundary(received_timestamp_ms, "WebSocket receipt timestamp")
        payload = _mapping(data, "WebSocket subscription data")
        with self._condition:
            if not self._connected:
                raise ForwardObservationGap("WEBSOCKET_NOTIFICATION_WHILE_DISCONNECTED")
            if channel == DERIBIT_INDEX_CHANNEL:
                self._accept_index(payload, received_timestamp_ms=received_timestamp_ms)
            elif channel.startswith("book.") and channel.endswith(f".{DERIBIT_BOOK_INTERVAL}"):
                name = channel[len("book.") : -len(f".{DERIBIT_BOOK_INTERVAL}")]
                self._accept_book(
                    name,
                    payload,
                    received_timestamp_ms=received_timestamp_ms,
                )
            elif channel.startswith("ticker.") and channel.endswith(f".{DERIBIT_TICKER_INTERVAL}"):
                name = channel[len("ticker.") : -len(f".{DERIBIT_TICKER_INTERVAL}")]
                self._accept_ticker(
                    name,
                    payload,
                    received_timestamp_ms=received_timestamp_ms,
                )
            else:
                raise ForwardObservationGap(f"WEBSOCKET_CHANNEL_OUTSIDE_BTC_FEED:{channel}")
            self._condition.notify_all()

    def seed_rest_resync(self, snapshot: RestBookSnapshot) -> None:
        result = _mapping(snapshot.result, "REST resync result")
        with self._condition:
            if not self._connected:
                raise ForwardObservationGap("REST_RESYNC_WHILE_WEBSOCKET_DISCONNECTED")
            try:
                state = self._states[snapshot.instrument_name]
            except KeyError as exc:
                raise ForwardObservationGap(
                    f"REST_RESYNC_INSTRUMENT_NOT_SUBSCRIBED:{snapshot.instrument_name}"
                ) from exc
            if result.get("instrument_name") != snapshot.instrument_name:
                raise ForwardObservationGap("REST_RESYNC_INSTRUMENT_IDENTITY_MISMATCH")
            if result.get("state") != "open":
                raise ForwardObservationGap(f"REST_RESYNC_BOOK_NOT_OPEN:{snapshot.instrument_name}")
            change_id = _integer(result.get("change_id"), "REST resync change_id")
            bids = _rest_levels(result.get("bids"), "REST resync bids")
            asks = _rest_levels(result.get("asks"), "REST resync asks")
            state.book = _BookState(
                bids=bids,
                asks=asks,
                change_id=change_id,
                source_timestamp_ms=snapshot.source_timestamp_ms,
                received_timestamp_ms=snapshot.received_timestamp_ms,
                epoch=self._epoch,
                ready=False,
                resync_seeded=True,
            )
            self._condition.notify_all()

    def mark_resync_failed(self, *, instrument_name: str, reason: str) -> None:
        _instrument_name(instrument_name)
        if not reason:
            raise ValueError("REST resync failure reason must be non-empty")
        with self._condition:
            self._pending_gaps.append(f"REST_RESYNC_FAILED:{instrument_name}:reason={reason}")
            state = self._states.get(instrument_name)
            if state is not None:
                state.book.ready = False
            self._condition.notify_all()

    def cut(
        self,
        *,
        instrument_names: Sequence[str],
        known_at_ms: int,
        maximum_age_ms: int,
        maximum_source_span_ms: int,
        maximum_receive_span_ms: int,
    ) -> BtcWebSocketCut:
        names = tuple(sorted(instrument_names))
        with self._condition:
            if self._pending_gaps:
                raise ForwardObservationGap(self._pending_gaps.popleft())
            try:
                return self._cut_locked(
                    names=names,
                    known_at_ms=known_at_ms,
                    maximum_age_ms=maximum_age_ms,
                    maximum_source_span_ms=maximum_source_span_ms,
                    maximum_receive_span_ms=maximum_receive_span_ms,
                )
            except _CutNotReady as exc:
                raise ForwardObservationGap(str(exc)) from exc

    def wait_for_cut(
        self,
        *,
        instrument_names: Sequence[str],
        known_at_ms: Callable[[], int],
        maximum_age_ms: int,
        maximum_source_span_ms: int,
        maximum_receive_span_ms: int,
        timeout_seconds: float,
    ) -> BtcWebSocketCut:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("WebSocket cut timeout must be finite and positive")
        names = tuple(sorted(instrument_names))
        deadline = monotonic() + timeout_seconds
        with self._condition:
            while True:
                if self._pending_gaps:
                    raise ForwardObservationGap(self._pending_gaps.popleft())
                try:
                    return self._cut_locked(
                        names=names,
                        known_at_ms=known_at_ms(),
                        maximum_age_ms=maximum_age_ms,
                        maximum_source_span_ms=maximum_source_span_ms,
                        maximum_receive_span_ms=maximum_receive_span_ms,
                    )
                except _CutNotReady as exc:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise ForwardObservationGap(str(exc)) from exc
                    self._condition.wait(timeout=remaining)

    def _accept_index(
        self,
        payload: Mapping[str, object],
        *,
        received_timestamp_ms: int,
    ) -> None:
        if payload.get("index_name") != BTC.price_index:
            raise ForwardObservationGap("WEBSOCKET_INDEX_IDENTITY_MISMATCH")
        source_timestamp_ms = _integer(payload.get("timestamp"), "index timestamp")
        _source_before_receipt(source_timestamp_ms, received_timestamp_ms)
        price = _positive_decimal(payload.get("price"), "index price")
        if not self._history:
            raise ForwardObservationGap("WEBSOCKET_INDEX_HISTORY_NOT_BOOTSTRAPPED")
        self._index_price = price
        self._index_source_timestamp_ms = source_timestamp_ms
        self._index_received_timestamp_ms = received_timestamp_ms
        self._index_epoch = self._epoch
        last_timestamp_ms = self._history[-1][0]
        if source_timestamp_ms >= last_timestamp_ms + self._history_cadence_ms:
            self._history.append((source_timestamp_ms, price))
            cutoff = source_timestamp_ms - 2 * 24 * 60 * 60 * 1_000
            while len(self._history) > 3 and self._history[1][0] < cutoff:
                self._history.pop(0)
        self._history_received_timestamp_ms = received_timestamp_ms

    def _accept_book(
        self,
        instrument_name: str,
        payload: Mapping[str, object],
        *,
        received_timestamp_ms: int,
    ) -> None:
        state = self._instrument_state(instrument_name, payload)
        source_timestamp_ms = _integer(payload.get("timestamp"), "book timestamp")
        _source_before_receipt(source_timestamp_ms, received_timestamp_ms)
        change_id = _integer(payload.get("change_id"), "book change_id")
        update_type = _text(payload.get("type"), "book type")
        if update_type == "snapshot":
            bids = _incremental_levels({}, payload.get("bids"), "book bids")
            asks = _incremental_levels({}, payload.get("asks"), "book asks")
            state.book = _BookState(
                bids=bids,
                asks=asks,
                change_id=change_id,
                source_timestamp_ms=source_timestamp_ms,
                received_timestamp_ms=received_timestamp_ms,
                epoch=self._epoch,
                ready=True,
                resync_seeded=False,
            )
            return
        if update_type != "change":
            raise ForwardObservationGap(f"WEBSOCKET_BOOK_TYPE_INVALID:{instrument_name}")
        book = state.book
        previous_change_id = _optional_integer(payload.get("prev_change_id"), "prev_change_id")
        if (
            book.change_id is None
            or book.epoch != self._epoch
            or previous_change_id != book.change_id
        ):
            expected = book.change_id if book.change_id is not None else -1
            book.ready = False
            book.resync_seeded = False
            gap = WebSocketSequenceGap(
                instrument_name=instrument_name,
                expected_change_id=expected,
                actual_previous_change_id=previous_change_id,
            )
            self._pending_gaps.append(str(gap))
            self._condition.notify_all()
            raise gap
        book.bids = _incremental_levels(book.bids, payload.get("bids"), "book bids")
        book.asks = _incremental_levels(book.asks, payload.get("asks"), "book asks")
        book.change_id = change_id
        book.source_timestamp_ms = source_timestamp_ms
        book.received_timestamp_ms = received_timestamp_ms
        book.ready = book.ready or book.resync_seeded
        book.resync_seeded = False

    def _accept_ticker(
        self,
        instrument_name: str,
        payload: Mapping[str, object],
        *,
        received_timestamp_ms: int,
    ) -> None:
        state = self._instrument_state(instrument_name, payload)
        source_timestamp_ms = _integer(payload.get("timestamp"), "ticker timestamp")
        _source_before_receipt(source_timestamp_ms, received_timestamp_ms)
        if payload.get("state", "open") == "open":
            _positive_decimal(payload.get("underlying_price"), "ticker underlying_price")
            _positive_decimal(payload.get("mark_iv"), "ticker mark_iv")
            _nonnegative_decimal(payload.get("open_interest"), "ticker open_interest")
            greeks = _mapping(payload.get("greeks"), "ticker greeks")
            delta = _decimal(greeks.get("delta"), "ticker delta")
            if abs(delta) > 1:
                raise ForwardObservationGap("ticker delta must be in [-1, 1]")
            _decimal(greeks.get("gamma"), "ticker gamma")
        state.ticker = _TickerState(
            data=dict(payload),
            source_timestamp_ms=source_timestamp_ms,
            received_timestamp_ms=received_timestamp_ms,
            epoch=self._epoch,
            ready=True,
        )

    def _instrument_state(
        self,
        instrument_name: str,
        payload: Mapping[str, object],
    ) -> _InstrumentState:
        if payload.get("instrument_name") != instrument_name:
            raise ForwardObservationGap(f"WEBSOCKET_INSTRUMENT_IDENTITY_MISMATCH:{instrument_name}")
        try:
            return self._states[instrument_name]
        except KeyError as exc:
            raise ForwardObservationGap(
                f"WEBSOCKET_INSTRUMENT_NOT_SUBSCRIBED:{instrument_name}"
            ) from exc

    def _cut_locked(
        self,
        *,
        names: tuple[str, ...],
        known_at_ms: int,
        maximum_age_ms: int,
        maximum_source_span_ms: int,
        maximum_receive_span_ms: int,
    ) -> BtcWebSocketCut:
        _boundary(known_at_ms, "WebSocket cut known-at")
        if min(maximum_age_ms, maximum_source_span_ms, maximum_receive_span_ms) <= 0:
            raise ValueError("WebSocket cut DataHealth bounds must be positive")
        if names != self._desired_names:
            raise _CutNotReady("WEBSOCKET_CUT_UNIVERSE_NOT_SUBSCRIBED")
        if not self._connected:
            raise _CutNotReady("WEBSOCKET_CUT_DISCONNECTED")
        if (
            self._index_price is None
            or self._index_source_timestamp_ms is None
            or self._index_received_timestamp_ms is None
            or self._index_epoch != self._epoch
        ):
            raise _CutNotReady("WEBSOCKET_INDEX_SNAPSHOT_PENDING")
        if not self._history or self._history_received_timestamp_ms is None:
            raise _CutNotReady("WEBSOCKET_INDEX_HISTORY_PENDING")
        source_boundaries = [self._index_source_timestamp_ms]
        received_boundaries = [self._index_received_timestamp_ms]
        responses: list[tuple[str, PublicStreamResponse]] = []
        for name in names:
            state = self._states[name]
            book = state.book
            ticker = state.ticker
            if (
                not book.ready
                or book.epoch != self._epoch
                or book.source_timestamp_ms is None
                or book.received_timestamp_ms is None
            ):
                raise _CutNotReady(f"WEBSOCKET_BOOK_SNAPSHOT_PENDING:{name}")
            if (
                not ticker.ready
                or ticker.epoch != self._epoch
                or ticker.source_timestamp_ms is None
                or ticker.received_timestamp_ms is None
            ):
                raise _CutNotReady(f"WEBSOCKET_TICKER_SNAPSHOT_PENDING:{name}")
            local_sources = (book.source_timestamp_ms, ticker.source_timestamp_ms)
            local_receipts = (book.received_timestamp_ms, ticker.received_timestamp_ms)
            effective_source_timestamp_ms = max(local_sources)
            effective_received_timestamp_ms = max(local_receipts)
            source_boundaries.append(effective_source_timestamp_ms)
            received_boundaries.append(effective_received_timestamp_ms)
            result = {
                **ticker.data,
                "instrument_name": name,
                "state": ticker.data.get("state", "open"),
                "timestamp": effective_source_timestamp_ms,
                "change_id": book.change_id,
                "bids": [
                    [str(price), str(quantity)]
                    for price, quantity in sorted(book.bids.items(), reverse=True)
                ],
                "asks": [
                    [str(price), str(quantity)] for price, quantity in sorted(book.asks.items())
                ],
            }
            responses.append(
                (
                    name,
                    PublicStreamResponse(
                        result=result,
                        source_timestamp_min_ms=effective_source_timestamp_ms,
                        source_timestamp_max_ms=effective_source_timestamp_ms,
                        received_timestamp_min_ms=effective_received_timestamp_ms,
                        received_timestamp_max_ms=effective_received_timestamp_ms,
                        continuity_epoch=self._epoch,
                    ),
                )
            )
        source_floor = min(source_boundaries)
        source_watermark = max(source_boundaries)
        received_floor = min(received_boundaries)
        received_watermark = max(received_boundaries)
        if source_watermark > known_at_ms or received_watermark > known_at_ms:
            raise ForwardObservationGap("WEBSOCKET_CUT_BOUNDARY_IN_FUTURE")
        if known_at_ms - source_floor > maximum_age_ms:
            raise _CutNotReady("WEBSOCKET_CUT_SOURCE_STALE")
        if known_at_ms - received_floor > maximum_age_ms:
            raise _CutNotReady("WEBSOCKET_CUT_RECEIPT_STALE")
        if source_watermark - source_floor > maximum_source_span_ms:
            raise _CutNotReady("WEBSOCKET_CUT_SOURCE_SPAN_EXCEEDED")
        if received_watermark - received_floor > maximum_receive_span_ms:
            raise _CutNotReady("WEBSOCKET_CUT_RECEIVE_SPAN_EXCEEDED")
        index_response = PublicStreamResponse(
            result={"index_price": str(self._index_price)},
            source_timestamp_min_ms=self._index_source_timestamp_ms,
            source_timestamp_max_ms=self._index_source_timestamp_ms,
            received_timestamp_min_ms=self._index_received_timestamp_ms,
            received_timestamp_max_ms=self._index_received_timestamp_ms,
            continuity_epoch=self._epoch,
        )
        history_response = PublicStreamResponse(
            result=[[timestamp_ms, str(price)] for timestamp_ms, price in self._history],
            source_timestamp_min_ms=self._history[0][0],
            source_timestamp_max_ms=self._history[-1][0],
            received_timestamp_min_ms=self._history_received_timestamp_ms,
            received_timestamp_max_ms=self._history_received_timestamp_ms,
            continuity_epoch=self._epoch,
        )
        return BtcWebSocketCut(
            continuity_epoch=self._epoch,
            index_price=self._index_price,
            source_floor_ms=source_floor,
            source_watermark_ms=source_watermark,
            received_floor_ms=received_floor,
            received_watermark_ms=received_watermark,
            instrument_names=names,
            index_response=index_response,
            history_response=history_response,
            book_responses=tuple(responses),
        )


class DeribitPublicWebSocketFeed:
    """One reconnecting unauthenticated public WebSocket reader for the BTC cache."""

    def __init__(
        self,
        *,
        cache: BtcWebSocketCache,
        received_timestamp_ms: Callable[[], int],
        rest_resync: RestBookResync,
        timeout_seconds: float = 10.0,
        url: str = DEFAULT_DERIBIT_WEBSOCKET_API,
        connection_factory: WebSocketConnectionFactory | None = None,
        audit_callback: PublicCallAudit | None = None,
    ) -> None:
        if url != DEFAULT_DERIBIT_WEBSOCKET_API:
            raise ValueError("B3 WebSocket feed requires the production Deribit endpoint")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("WebSocket timeout must be finite and positive")
        self.cache = cache
        self.received_timestamp_ms = received_timestamp_ms
        self.rest_resync = rest_resync
        self.timeout_seconds = timeout_seconds
        self.url = url
        self.connection_factory = connection_factory or _open_connection
        self.audit_callback = audit_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: WebSocketConnection | None = None
        self._next_request_id = 1
        self._subscribed_channels: set[str] = set()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("WebSocket feed is already started")
        self._thread = threading.Thread(
            target=self._run,
            name="optimatrix-btc-public-websocket",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        connection = self._connection
        if connection is not None:
            connection.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.timeout_seconds)
            if thread.is_alive():
                raise RuntimeError("WebSocket feed did not stop within its bounded timeout")
        self._thread = None

    def configure_instruments(self, instrument_names: Sequence[str]) -> None:
        self.cache.configure_instruments(instrument_names)

    def wait_for_cut(
        self,
        *,
        instrument_names: Sequence[str],
        maximum_age_ms: int,
        maximum_source_span_ms: int,
        maximum_receive_span_ms: int,
    ) -> BtcWebSocketCut:
        return self.cache.wait_for_cut(
            instrument_names=instrument_names,
            known_at_ms=self.received_timestamp_ms,
            maximum_age_ms=maximum_age_ms,
            maximum_source_span_ms=maximum_source_span_ms,
            maximum_receive_span_ms=maximum_receive_span_ms,
            timeout_seconds=self.timeout_seconds,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            connection: WebSocketConnection | None = None
            try:
                connection = self.connection_factory(self.url, self.timeout_seconds)
                self._connection = connection
                self._subscribed_channels = set()
                self.cache.begin_connection()
                self._send(connection, "public/set_heartbeat", {"interval": 10})
                self._sync_channels(connection)
                while not self._stop.is_set():
                    self._sync_channels(connection)
                    try:
                        raw = connection.recv(timeout=0.25)
                    except TimeoutError:
                        continue
                    self._accept_frame(connection, raw)
            except Exception as exc:
                if not self._stop.is_set():
                    self.cache.disconnect(reason=f"{type(exc).__name__}:{exc}")
            finally:
                self._connection = None
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
            if not self._stop.wait(1.0):
                continue

    def _sync_channels(self, connection: WebSocketConnection) -> None:
        desired = set(self.cache.desired_channels)
        remove = tuple(sorted(self._subscribed_channels - desired))
        add = tuple(sorted(desired - self._subscribed_channels))
        if remove:
            self._send(connection, "public/unsubscribe", {"channels": list(remove)})
            self._subscribed_channels.difference_update(remove)
        if add:
            if len(add) > MAX_STREAM_CHANNELS or len(desired) > MAX_STREAM_CHANNELS:
                raise ForwardObservationGap("WEBSOCKET_SUBSCRIPTION_BOUND_EXCEEDED")
            self._send(connection, "public/subscribe", {"channels": list(add)})
            self._subscribed_channels.update(add)

    def _send(
        self,
        connection: WebSocketConnection,
        method: str,
        params: Mapping[str, object],
    ) -> None:
        if method not in {
            "public/set_heartbeat",
            "public/subscribe",
            "public/unsubscribe",
            "public/test",
        }:
            raise ValueError("WebSocket feed permits only bounded public methods")
        request_id = self._next_request_id
        self._next_request_id += 1
        if self.audit_callback is not None:
            self.audit_callback(method, params, self.timeout_seconds)
        connection.send(
            json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)},
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )

    def _accept_frame(self, connection: WebSocketConnection, raw: str | bytes) -> None:
        if not isinstance(raw, str):
            raise ForwardObservationGap("WEBSOCKET_BINARY_FRAME_FORBIDDEN")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ForwardObservationGap("WEBSOCKET_JSON_INVALID") from exc
        root = _mapping(payload, "WebSocket frame")
        if root.get("jsonrpc") != "2.0":
            raise ForwardObservationGap("WEBSOCKET_JSONRPC_VERSION_INVALID")
        if "id" in root:
            if root.get("error") is not None or "result" not in root:
                raise ForwardObservationGap("WEBSOCKET_PUBLIC_REQUEST_REJECTED")
            return
        method = root.get("method")
        params = _mapping(root.get("params"), "WebSocket notification params")
        if method == "heartbeat":
            if params.get("type") == "test_request":
                self._send(connection, "public/test", {})
            return
        if method != "subscription":
            raise ForwardObservationGap("WEBSOCKET_NOTIFICATION_METHOD_INVALID")
        channel = _text(params.get("channel"), "subscription channel")
        if channel not in set(self.cache.desired_channels):
            return
        received_at_ms = self.received_timestamp_ms()
        try:
            self.cache.accept_subscription(
                channel=channel,
                data=params.get("data"),
                received_timestamp_ms=received_at_ms,
            )
        except WebSocketSequenceGap as gap:
            try:
                snapshot = self.rest_resync(gap.instrument_name)
                self.cache.seed_rest_resync(snapshot)
            except Exception as exc:
                self.cache.mark_resync_failed(
                    instrument_name=gap.instrument_name,
                    reason=f"{type(exc).__name__}:{exc}",
                )


def _open_connection(url: str, timeout_seconds: float) -> WebSocketConnection:
    return cast(
        WebSocketConnection,
        connect(
            url,
            open_timeout=timeout_seconds,
            close_timeout=timeout_seconds,
            ping_interval=None,
            max_size=2**20,
        ),
    )


def _channels(names: tuple[str, ...]) -> tuple[str, ...]:
    channels = [DERIBIT_INDEX_CHANNEL]
    channels.extend(f"book.{name}.{DERIBIT_BOOK_INTERVAL}" for name in names)
    channels.extend(f"ticker.{name}.{DERIBIT_TICKER_INTERVAL}" for name in names)
    return tuple(sorted(channels))


def _incremental_levels(
    current: Mapping[Decimal, Decimal],
    value: object,
    field_name: str,
) -> dict[Decimal, Decimal]:
    if not isinstance(value, list):
        raise ForwardObservationGap(f"{field_name} must be an array")
    levels = dict(current)
    for raw in value:
        if not isinstance(raw, list) or len(raw) != 3:
            raise ForwardObservationGap(f"{field_name} contains a malformed change")
        action = _text(raw[0], f"{field_name} action")
        if action not in {"new", "change", "delete"}:
            raise ForwardObservationGap(f"{field_name} contains an invalid action")
        price = _positive_decimal(raw[1], f"{field_name} price")
        quantity = _decimal(raw[2], f"{field_name} quantity")
        if action == "delete" or quantity == 0:
            levels.pop(price, None)
        elif quantity > 0:
            levels[price] = quantity
        else:
            raise ForwardObservationGap(f"{field_name} quantity is negative")
    return levels


def _rest_levels(value: object, field_name: str) -> dict[Decimal, Decimal]:
    if not isinstance(value, list):
        raise ForwardObservationGap(f"{field_name} must be an array")
    levels: dict[Decimal, Decimal] = {}
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            raise ForwardObservationGap(f"{field_name} contains a malformed level")
        price = _positive_decimal(raw[0], f"{field_name} price")
        quantity = _decimal(raw[1], f"{field_name} quantity")
        if quantity > 0:
            levels[price] = quantity
    return levels


def _instrument_name(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(BTC.instrument_prefix):
        raise ValueError("WebSocket cache accepts only BTC instruments")
    if not value or value != value.strip() or "." in value:
        raise ValueError("WebSocket instrument name is malformed")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ForwardObservationGap(f"{field_name} must be an object")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ForwardObservationGap(f"{field_name} must be non-empty text")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ForwardObservationGap(f"{field_name} must be a non-negative integer")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    return None if value is None else _integer(value, field_name)


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ForwardObservationGap(f"{field_name} must be decimal-compatible")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ForwardObservationGap(f"{field_name} must be decimal-compatible") from exc
    if not parsed.is_finite():
        raise ForwardObservationGap(f"{field_name} must be finite")
    return parsed


def _positive_decimal(value: object, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name)
    if parsed <= 0:
        raise ForwardObservationGap(f"{field_name} must be positive")
    return parsed


def _nonnegative_decimal(value: object, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name)
    if parsed < 0:
        raise ForwardObservationGap(f"{field_name} must be non-negative")
    return parsed


def _boundary(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _source_before_receipt(source_timestamp_ms: int, received_timestamp_ms: int) -> None:
    if source_timestamp_ms > received_timestamp_ms:
        raise ForwardObservationGap("WEBSOCKET_SOURCE_AFTER_RECEIPT")

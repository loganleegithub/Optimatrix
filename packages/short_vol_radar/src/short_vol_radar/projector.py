"""Strict as-of public facts projected into scenario-free radar frames."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import cast

from market_tape import (
    CanonicalEvent,
    EventKind,
    Instrument,
    InstrumentKind,
    MarketTapeReducer,
    MarketTapeSnapshot,
    TickerFact,
    canonical_digest,
)
from options_domain import ComboQuote, OptionQuote, SurfaceSummary, build_surface_summary

from short_vol_radar.contracts import (
    BreakoutDirection,
    DecisionFrame,
    DecisionInputContract,
    FlowMetrics,
    PathMetrics,
    RadarPolicy,
    ReferenceDynamics,
    WindowCoverage,
    WindowObservation,
)


@dataclass(frozen=True, slots=True)
class _PriceSample:
    source_at_ms: int
    observed_elapsed_ms: int
    capture_seq: int
    price: Decimal


@dataclass(frozen=True, slots=True)
class _TradeSample:
    source_at_ms: int
    observed_elapsed_ms: int
    capture_seq: int
    trade_seq: int
    price: Decimal
    amount: Decimal
    direction: str
    liquidation: str | None


@dataclass(frozen=True, slots=True)
class _ControlFact:
    observed_elapsed_ms: int
    capture_seq: int


def _payload(event: CanonicalEvent) -> dict[str, object]:
    value = json.loads(event.raw_payload)
    if not isinstance(value, dict):
        raise ValueError("canonical payload must be an object")
    return cast(dict[str, object], value)


def _optional_decimal(
    payload: Mapping[str, object],
    field: str,
) -> Decimal | None:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _ticker_price(ticker: TickerFact) -> Decimal | None:
    return _optional_decimal(ticker.payload, "index_price")


class RadarProjector:
    """Project one deterministic decision frame without future facts."""

    def __init__(
        self,
        *,
        input_contract: DecisionInputContract | None = None,
        policy: RadarPolicy | None = None,
    ) -> None:
        self.input_contract = input_contract or DecisionInputContract()
        self.reference_instrument = self.input_contract.reference_instrument
        self.policy = policy or RadarPolicy()
        self.reducer = MarketTapeReducer()
        self._price_samples: list[_PriceSample] = []
        self._trade_samples: list[_TradeSample] = []
        self._price_subscription: _ControlFact | None = None
        self._trade_subscription: _ControlFact | None = None
        self._platform_subscription: _ControlFact | None = None
        self._trade_gaps: list[_ControlFact] = []
        self._reconnects: list[_ControlFact] = []
        self._market_as_of_ms: int | None = None
        self._market_as_of_capture_seq: int | None = None
        self._market_watermark_progress_elapsed_ms: int | None = None
        self._previous_reference: (
            tuple[Decimal | None, Decimal | None, Decimal | None, int] | None
        ) = None
        self._current_reference_dynamics: ReferenceDynamics | None = None
        self._scheduled_block_observed = False
        self._scheduled_block: str | None = None
        self._scheduled_block_source_capture_seq: int | None = None
        self._scheduled_block_source_id: str | None = None
        self._scheduled_block_valid_from_ms: int | None = None
        self._scheduled_block_valid_until_ms: int | None = None
        self._last_event: CanonicalEvent | None = None
        self._current_frame: DecisionFrame | None = None

    def ingest(self, event: CanonicalEvent) -> DecisionFrame | None:
        self.reducer.ingest(event)
        self._last_event = event
        if event.event_kind is EventKind.SUBSCRIPTION_START:
            payload = _payload(event)
            stream = str(payload.get("stream", ""))
            fact = _ControlFact(event.collector_elapsed_ms, event.capture_seq)
            if stream == "reference_price":
                self._price_subscription = fact
            elif stream == "reference_trade":
                self._trade_subscription = fact
            elif stream == "platform_state":
                self._platform_subscription = fact
            return None
        if event.event_kind is EventKind.RECONNECT:
            self._reconnects.append(_ControlFact(event.collector_elapsed_ms, event.capture_seq))
            self._price_samples.clear()
            self._trade_samples.clear()
            self._price_subscription = None
            self._trade_subscription = None
            self._platform_subscription = None
            self._previous_reference = None
            self._current_reference_dynamics = None
            self._market_as_of_ms = None
            self._market_as_of_capture_seq = None
            self._market_watermark_progress_elapsed_ms = None
            self._current_frame = None
            return None
        if event.event_kind is EventKind.SCHEDULED_BLOCK_STATE:
            payload = _payload(event)
            state = payload.get("state")
            label = payload.get("label")
            source_id = payload.get("source_id")
            valid_from_ms = payload.get("valid_from_ms")
            valid_until_ms = payload.get("valid_until_ms")
            if state not in {"CLEAR", "BLOCKED"}:
                raise ValueError("scheduled-block state must be CLEAR or BLOCKED")
            if state == "BLOCKED" and (not isinstance(label, str) or not label):
                raise ValueError("blocked scheduled state requires a label")
            if state == "CLEAR" and label is not None:
                raise ValueError("clear scheduled state cannot have a label")
            if not isinstance(source_id, str) or not source_id:
                raise ValueError("scheduled-block source identity is required")
            if (
                not isinstance(valid_from_ms, int)
                or isinstance(valid_from_ms, bool)
                or not isinstance(valid_until_ms, int)
                or isinstance(valid_until_ms, bool)
                or valid_from_ms <= 0
                or valid_until_ms < valid_from_ms
            ):
                raise ValueError("scheduled-block validity interval is invalid")
            self._scheduled_block_observed = True
            self._scheduled_block = str(label) if state == "BLOCKED" else None
            self._scheduled_block_source_capture_seq = event.capture_seq
            self._scheduled_block_source_id = source_id
            self._scheduled_block_valid_from_ms = valid_from_ms
            self._scheduled_block_valid_until_ms = valid_until_ms
            frame = self._frame(
                event,
                dynamics_override=self._current_reference_dynamics,
                update_previous=False,
            )
            self._current_frame = frame
            return frame
        if event.event_kind is EventKind.CATALOG_SNAPSHOT:
            frame = self._frame(
                event,
                dynamics_override=self._current_reference_dynamics,
                update_previous=False,
            )
            self._current_frame = frame
            return frame
        if event.instrument_name != self.reference_instrument:
            return None
        if event.event_kind is EventKind.TICKER:
            snapshot = self.reducer.snapshot(event.collector_received_at_ms)
            ticker = next(
                item
                for item in snapshot.tickers
                if item.instrument_name == self.reference_instrument
            )
            ticker_applied = ticker.capture_seq == event.capture_seq
            price = _ticker_price(ticker) if ticker_applied else None
            if price is not None and ticker_applied:
                self._advance_market_as_of(
                    ticker.source_at_ms,
                    ticker.capture_seq,
                    ticker.observed_elapsed_ms,
                )
            if price is not None and ticker_applied:
                self._price_samples.append(
                    _PriceSample(
                        ticker.source_at_ms,
                        ticker.observed_elapsed_ms,
                        ticker.capture_seq,
                        price,
                    )
                )
            frame = self._frame(
                event,
                dynamics_override=(None if ticker_applied else self._current_reference_dynamics),
                update_previous=ticker_applied,
            )
            self._current_frame = frame
            return frame
        if event.event_kind in {EventKind.TRADE, EventKind.TRADE_GAP}:
            if event.event_kind is EventKind.TRADE_GAP:
                self._trade_gaps.append(_ControlFact(event.collector_elapsed_ms, event.capture_seq))
            snapshot = self.reducer.snapshot(event.collector_received_at_ms)
            existing = {item.trade_seq for item in self._trade_samples}
            for trade in snapshot.trades:
                if (
                    trade.instrument_name != self.reference_instrument
                    or trade.trade_seq in existing
                    or (
                        snapshot.reconnect_capture_seq is not None
                        and trade.capture_seq <= snapshot.reconnect_capture_seq
                    )
                    or self._market_as_of_ms is None
                    or trade.source_at_ms > self._market_as_of_ms
                ):
                    continue
                sample = _TradeSample(
                    source_at_ms=trade.source_at_ms,
                    observed_elapsed_ms=trade.observed_elapsed_ms,
                    capture_seq=trade.capture_seq,
                    trade_seq=trade.trade_seq,
                    price=trade.price,
                    amount=trade.amount,
                    direction=trade.direction,
                    liquidation=trade.liquidation,
                )
                self._trade_samples.append(sample)
                existing.add(trade.trade_seq)
            frame = self._frame(
                event,
                dynamics_override=self._current_reference_dynamics,
                update_previous=False,
            )
            self._current_frame = frame
            return frame
        return None

    def _advance_market_as_of(
        self,
        source_at_ms: int,
        capture_seq: int,
        observed_elapsed_ms: int,
    ) -> None:
        if self._market_as_of_ms is None or source_at_ms > self._market_as_of_ms:
            self._market_watermark_progress_elapsed_ms = observed_elapsed_ms
        if self._market_as_of_ms is None or source_at_ms >= self._market_as_of_ms:
            self._market_as_of_ms = source_at_ms
            self._market_as_of_capture_seq = capture_seq

    def finalize(self) -> DecisionFrame:
        """Project the current state at the final ingested canonical event."""

        if self._last_event is None:
            raise RuntimeError("cannot finalize an empty radar projection")
        if (
            self._current_frame is not None
            and self._current_frame.as_of_capture_seq == self._last_event.capture_seq
        ):
            return self._current_frame
        current_frame_known = bool(
            self._current_frame is not None
            and self._current_frame.as_of_capture_seq <= self._last_event.capture_seq
        )
        dynamics = self._current_reference_dynamics
        if dynamics is None and current_frame_known and self._current_frame is not None:
            dynamics = self._current_frame.reference_dynamics
        return self._frame(
            self._last_event,
            dynamics_override=dynamics,
            update_previous=False,
        )

    def _frame(
        self,
        trigger: CanonicalEvent,
        *,
        dynamics_override: ReferenceDynamics | None = None,
        update_previous: bool = True,
    ) -> DecisionFrame:
        collector_now_ms = trigger.collector_received_at_ms
        observed_now_ms = trigger.collector_elapsed_ms
        market_now_ms = self._market_as_of_ms
        market_as_of_capture_seq = self._market_as_of_capture_seq
        snapshot = self.reducer.snapshot(collector_now_ms)
        collector_as_of = datetime.fromtimestamp(collector_now_ms / 1_000, tz=UTC)
        market_as_of = (
            datetime.fromtimestamp(market_now_ms / 1_000, tz=UTC)
            if market_now_ms is not None
            else None
        )
        surface_as_of = market_as_of or collector_as_of
        reference = next(
            (
                item
                for item in snapshot.tickers
                if item.instrument_name == self.reference_instrument
                and market_now_ms is not None
                and item.source_at_ms <= market_now_ms
                and (
                    snapshot.reconnect_capture_seq is None
                    or item.capture_seq > snapshot.reconnect_capture_seq
                )
            ),
            None,
        )
        known_prices = tuple(
            item
            for item in self._price_samples
            if market_now_ms is not None and item.source_at_ms <= market_now_ms
        )
        reference_sample = known_prices[-1] if known_prices else None
        reference_price = reference_sample.price if reference_sample is not None else None
        reference_source_capture_seq = (
            reference_sample.capture_seq if reference_sample is not None else None
        )
        index_price = reference_price
        mark_price = (
            _optional_decimal(reference.payload, "mark_price") if reference is not None else None
        )
        funding = (
            _optional_decimal(reference.payload, "funding_8h") if reference is not None else None
        )
        open_interest = (
            _optional_decimal(reference.payload, "open_interest") if reference is not None else None
        )
        basis = (
            (mark_price - index_price) / index_price
            if mark_price is not None and index_price not in {None, Decimal("0")}
            else None
        )
        previous_reference = self._previous_reference
        if previous_reference is None:
            old_funding = None
            old_basis = None
            old_open_interest = None
            prior_reference_capture_seq = None
        else:
            (
                old_funding,
                old_basis,
                old_open_interest,
                prior_reference_capture_seq,
            ) = previous_reference
        funding_change = (
            funding - old_funding if funding is not None and old_funding is not None else None
        )
        basis_change = basis - old_basis if basis is not None and old_basis is not None else None
        open_interest_change_fraction = (
            (open_interest - old_open_interest) / old_open_interest
            if open_interest is not None and old_open_interest not in {None, Decimal("0")}
            else None
        )
        prior_reference_used = (
            prior_reference_capture_seq
            if any(
                item is not None
                for item in (
                    funding_change,
                    basis_change,
                    open_interest_change_fraction,
                )
            )
            else None
        )
        dynamics = dynamics_override or ReferenceDynamics(
            funding_8h=funding,
            funding_change=funding_change,
            basis_fraction=basis,
            basis_change=basis_change,
            open_interest=open_interest,
            open_interest_change_fraction=open_interest_change_fraction,
            prior_reference_capture_seq=prior_reference_used,
        )
        catalog = snapshot.catalog_snapshot
        catalog_matches = bool(
            catalog is not None
            and catalog.scope == self.input_contract.catalog_scope
            and catalog.reference_instrument == self.reference_instrument
        )
        catalog_names = (
            frozenset(catalog.instrument_names)
            if catalog is not None and catalog_matches
            else frozenset()
        )
        catalog_age_ms = (
            max(0, observed_now_ms - catalog.observed_elapsed_ms)
            if catalog is not None and catalog_matches
            else None
        )
        option_quotes = self._option_quotes(
            snapshot,
            market_now_ms,
            observed_now_ms,
            catalog_instruments=(catalog.instruments if catalog_matches and catalog else ()),
        )
        combo_quotes: tuple[ComboQuote, ...] = ()
        surface: SurfaceSummary = build_surface_summary(option_quotes, as_of=surface_as_of)
        windows = tuple(
            self._window(
                market_now_ms,
                observed_now_ms,
                seconds,
            )
            for seconds in self.input_contract.required_windows_seconds
        )
        reasons: list[str] = []
        platform_state = snapshot.platform_state
        if market_now_ms is None:
            reasons.append("NO_MARKET_AS_OF")
        if reference_price is None:
            reasons.append("NO_REFERENCE_PRICE")
        if index_price is None:
            reasons.append("NO_INDEX_PRICE")
        if reference is not None and str(reference.payload.get("state", "")).lower() != "open":
            reasons.append("REFERENCE_NOT_OPEN")
        reference_age_ms = (
            max(
                max(0, observed_now_ms - reference_sample.observed_elapsed_ms),
                max(0, market_now_ms - reference_sample.source_at_ms),
            )
            if reference_sample is not None and market_now_ms is not None
            else None
        )
        if (
            reference_age_ms is None
            or reference_age_ms > self.input_contract.reference_freshness_ms
        ):
            reasons.append("REFERENCE_STALE")
        if (
            sum(item.fresh for item in option_quotes)
            < self.input_contract.minimum_fresh_option_quotes
        ):
            reasons.append("INSUFFICIENT_FRESH_OPTION_QUOTES")
        if not catalog_matches:
            reasons.append("CATALOG_SNAPSHOT_UNKNOWN")
        elif catalog_age_ms is None or catalog_age_ms > self.input_contract.catalog_max_age_ms:
            reasons.append("CATALOG_SNAPSHOT_STALE")
        catalog_option_names = catalog_names - {self.reference_instrument}
        expected_option_names = {
            item.instrument_name
            for item in (() if catalog is None or not catalog_matches else catalog.instruments)
            if item.instrument_name in catalog_option_names
            and item.kind is InstrumentKind.OPTION
            and item.active
            and item.expiration_timestamp_ms is not None
            and market_now_ms is not None
            and 0
            < item.expiration_timestamp_ms - market_now_ms
            <= self.policy.maximum_tte_seconds * 1_000
        }
        quote_names = {item.instrument_name for item in option_quotes}
        if expected_option_names != quote_names:
            reasons.append("OPTION_UNIVERSE_QUOTES_INCOMPLETE")
        if any(not item.fresh for item in option_quotes):
            reasons.append("OPTION_UNIVERSE_QUOTES_STALE")
        if any(
            (item.bid is not None and item.bid_amount is None)
            or (item.ask is not None and item.ask_amount is None)
            for item in option_quotes
        ):
            reasons.append("OPTION_DEPTH_UNKNOWN")
        if not surface.expiries:
            reasons.append("NO_SURFACE")
        for window in windows:
            if not window.coverage.price_complete or window.path is None:
                reasons.append(f"REQUIRED_PRICE_WINDOW_UNKNOWN:{window.coverage.requested_seconds}")
            if not window.coverage.trade_complete or window.flow is None:
                reasons.append(f"REQUIRED_FLOW_WINDOW_UNKNOWN:{window.coverage.requested_seconds}")
        platform_is_locked = (
            platform_state is not None
            and platform_state.state == "LOCKED"
            and platform_state.locked is True
        )
        platform_is_open = (
            platform_state is not None
            and platform_state.state == "OPEN"
            and platform_state.locked is False
            and self._platform_subscription is not None
            and self._platform_subscription.capture_seq in platform_state.source_capture_seqs
            and platform_state.status_capture_seq is not None
            and platform_state.status_capture_seq > self._platform_subscription.capture_seq
        )
        if platform_is_locked:
            reasons.append("PLATFORM_LOCKED")
        elif not platform_is_open:
            reasons.append("PLATFORM_STATE_UNKNOWN")
        effective_platform_state = (
            "LOCKED" if platform_is_locked else "OPEN" if platform_is_open else "UNKNOWN"
        )
        effective_platform_locked: bool | None = (
            True if platform_is_locked else False if platform_is_open else None
        )
        scheduled_block_current = bool(
            self._scheduled_block_observed
            and market_now_ms is not None
            and self._scheduled_block_valid_from_ms is not None
            and self._scheduled_block_valid_until_ms is not None
            and self._scheduled_block_valid_from_ms
            <= market_now_ms
            <= self._scheduled_block_valid_until_ms
        )
        if not self._scheduled_block_observed:
            reasons.append("SCHEDULED_BLOCK_UNKNOWN")
        elif market_now_ms is None:
            reasons.append("SCHEDULED_BLOCK_TIME_UNKNOWN")
        elif (
            self._scheduled_block_valid_from_ms is not None
            and market_now_ms < self._scheduled_block_valid_from_ms
        ):
            reasons.append("SCHEDULED_BLOCK_NOT_YET_VALID")
        elif (
            self._scheduled_block_valid_until_ms is not None
            and market_now_ms > self._scheduled_block_valid_until_ms
        ):
            reasons.append("SCHEDULED_BLOCK_STALE")
        elif self._scheduled_block is not None:
            reasons.append("SCHEDULED_BLOCK")
        source_capture_seqs = tuple(
            sorted(
                {
                    trigger.capture_seq,
                    *(seq for window in windows for seq in window.source_capture_seqs),
                    *(seq for item in option_quotes for seq in item.source_capture_seqs),
                    *(item.source_capture_seq for item in combo_quotes),
                    *(() if reference is None else (reference.capture_seq,)),
                    *(() if catalog is None or not catalog_matches else (catalog.capture_seq,)),
                    *(
                        ()
                        if catalog is None or not catalog_matches
                        else catalog.instrument_source_capture_seqs
                    ),
                    *(
                        ()
                        if self._scheduled_block_source_capture_seq is None
                        else (self._scheduled_block_source_capture_seq,)
                    ),
                    *(
                        ()
                        if self._platform_subscription is None
                        else (self._platform_subscription.capture_seq,)
                    ),
                    *(() if platform_state is None else platform_state.source_capture_seqs),
                    *(
                        ()
                        if platform_is_open or platform_is_locked
                        else (
                            ()
                            if snapshot.reconnect_capture_seq is None
                            else (snapshot.reconnect_capture_seq,)
                        )
                    ),
                    *(() if market_as_of_capture_seq is None else (market_as_of_capture_seq,)),
                    *(
                        ()
                        if dynamics.prior_reference_capture_seq is None
                        else (dynamics.prior_reference_capture_seq,)
                    ),
                }
            )
        )
        frame = DecisionFrame(
            as_of_capture_seq=trigger.capture_seq,
            collector_as_of=collector_as_of,
            collector_elapsed_ms=observed_now_ms,
            market_as_of=market_as_of,
            market_as_of_capture_seq=market_as_of_capture_seq,
            input_contract_id=self.input_contract.contract_id,
            input_contract_digest=self.input_contract.digest,
            reference_instrument=self.reference_instrument,
            reference_price_source=self.input_contract.reference_price_field,
            reference_source_capture_seq=reference_source_capture_seq,
            reference_price=reference_price,
            index_price=index_price,
            best_bid=(
                _optional_decimal(reference.payload, "best_bid_price")
                if reference is not None
                else None
            ),
            best_ask=(
                _optional_decimal(reference.payload, "best_ask_price")
                if reference is not None
                else None
            ),
            windows=windows,
            reference_dynamics=dynamics,
            surface=surface,
            option_quotes=option_quotes,
            combo_quotes=combo_quotes,
            platform_state=effective_platform_state,
            platform_locked=effective_platform_locked,
            catalog_scope=(catalog.scope if catalog is not None and catalog_matches else None),
            catalog_snapshot_capture_seq=(
                catalog.capture_seq if catalog is not None and catalog_matches else None
            ),
            catalog_source_at=(
                datetime.fromtimestamp(catalog.source_at_ms / 1_000, tz=UTC)
                if catalog is not None and catalog_matches
                else None
            ),
            catalog_age_ms=catalog_age_ms,
            catalog_instrument_count=(
                len(catalog.instrument_names) if catalog is not None and catalog_matches else None
            ),
            catalog_instrument_names_digest=(
                canonical_digest(catalog.instrument_names)
                if catalog is not None and catalog_matches
                else None
            ),
            catalog_generation_id=(
                catalog.generation_id if catalog is not None and catalog_matches else None
            ),
            catalog_metadata_set_digest=(
                catalog.metadata_set_digest if catalog is not None and catalog_matches else None
            ),
            catalog_instrument_source_capture_seqs=(
                catalog.instrument_source_capture_seqs
                if catalog is not None and catalog_matches
                else ()
            ),
            catalog_generation_complete=catalog_matches,
            scheduled_block_observed=self._scheduled_block_observed,
            scheduled_block_source_capture_seq=self._scheduled_block_source_capture_seq,
            scheduled_block_source_id=self._scheduled_block_source_id,
            scheduled_block_valid_from=(
                datetime.fromtimestamp(self._scheduled_block_valid_from_ms / 1_000, tz=UTC)
                if self._scheduled_block_valid_from_ms is not None
                else None
            ),
            scheduled_block_valid_until=(
                datetime.fromtimestamp(self._scheduled_block_valid_until_ms / 1_000, tz=UTC)
                if self._scheduled_block_valid_until_ms is not None
                else None
            ),
            scheduled_block_current=scheduled_block_current,
            scheduled_block=self._scheduled_block,
            complete=not reasons,
            completeness_reasons=tuple(reasons),
            source_capture_seqs=source_capture_seqs,
        )
        if update_previous and reference is not None:
            self._previous_reference = (
                funding,
                basis,
                open_interest,
                reference.capture_seq,
            )
            self._current_reference_dynamics = dynamics
        self._prune(observed_now_ms)
        return frame

    def _option_quotes(
        self,
        snapshot: MarketTapeSnapshot,
        market_now_ms: int | None,
        observed_now_ms: int,
        *,
        catalog_instruments: tuple[Instrument, ...],
    ) -> tuple[OptionQuote, ...]:
        instruments = {
            item.instrument_name: item
            for item in catalog_instruments
            if item.kind is InstrumentKind.OPTION and item.active
        }
        tickers = {item.instrument_name: item for item in snapshot.tickers}
        quotes: list[OptionQuote] = []
        for name, instrument in instruments.items():
            ticker = tickers.get(name)
            if (
                ticker is None
                or market_now_ms is None
                or ticker.source_at_ms > market_now_ms
                or (
                    snapshot.reconnect_capture_seq is not None
                    and ticker.capture_seq <= snapshot.reconnect_capture_seq
                )
                or str(ticker.payload.get("state", "")).lower() != "open"
                or instrument.expiration_timestamp_ms is None
                or instrument.strike is None
                or instrument.option_kind is None
            ):
                continue
            tte_seconds = int((instrument.expiration_timestamp_ms - market_now_ms) / 1_000)
            if tte_seconds <= 0 or tte_seconds > 72 * 3_600:
                continue
            payload = ticker.payload
            raw_greeks = payload.get("greeks")
            greeks = cast(dict[str, object], raw_greeks) if isinstance(raw_greeks, dict) else {}
            arrival_age_ms = max(0, observed_now_ms - ticker.observed_elapsed_ms)
            market_age_ms = max(0, market_now_ms - ticker.source_at_ms)
            quote_age_ms = max(arrival_age_ms, market_age_ms)
            quotes.append(
                OptionQuote(
                    instrument_name=name,
                    expiry=datetime.fromtimestamp(
                        instrument.expiration_timestamp_ms / 1_000,
                        tz=UTC,
                    ),
                    tte_seconds=tte_seconds,
                    strike=instrument.strike,
                    option_kind=instrument.option_kind,
                    bid=_optional_decimal(payload, "best_bid_price"),
                    ask=_optional_decimal(payload, "best_ask_price"),
                    bid_amount=_optional_decimal(payload, "best_bid_amount"),
                    ask_amount=_optional_decimal(payload, "best_ask_amount"),
                    bid_iv=_optional_decimal(payload, "bid_iv"),
                    ask_iv=_optional_decimal(payload, "ask_iv"),
                    mark_iv=_optional_decimal(payload, "mark_iv"),
                    delta=_optional_decimal(greeks, "delta"),
                    gamma=_optional_decimal(greeks, "gamma"),
                    open_interest=_optional_decimal(payload, "open_interest"),
                    contract_size=instrument.contract_size,
                    min_trade_amount=instrument.min_trade_amount,
                    amount_step=instrument.amount_step,
                    taker_commission=instrument.taker_commission,
                    quote_age_ms=quote_age_ms,
                    fresh=(
                        ticker.source_at_ms <= market_now_ms
                        and quote_age_ms <= self.input_contract.option_freshness_ms
                    ),
                    instrument_source_capture_seq=instrument.source_capture_seq,
                    ticker_source_capture_seq=ticker.capture_seq,
                    source_at=datetime.fromtimestamp(
                        ticker.source_at_ms / 1_000,
                        tz=UTC,
                    ),
                )
            )
        return tuple(
            sorted(
                quotes,
                key=lambda item: (
                    item.expiry,
                    item.strike,
                    item.option_kind,
                    item.instrument_name,
                ),
            )
        )

    def _window(
        self,
        market_now_ms: int | None,
        observed_now_ms: int,
        seconds: int,
    ) -> WindowObservation:
        observed_start_ms = observed_now_ms - seconds * 1_000
        market_start_ms = market_now_ms - seconds * 1_000 if market_now_ms is not None else None
        reconnects = tuple(
            item
            for item in self._reconnects
            if observed_start_ms <= item.observed_elapsed_ms <= observed_now_ms
        )
        gaps = tuple(
            item
            for item in self._trade_gaps
            if observed_start_ms <= item.observed_elapsed_ms <= observed_now_ms
        )
        reconnect_contaminated = bool(reconnects)
        gap_contaminated = bool(gaps)
        price_subscription = (
            self._price_subscription
            if self._price_subscription is not None
            and self._price_subscription.observed_elapsed_ms <= observed_now_ms
            else None
        )
        trade_subscription = (
            self._trade_subscription
            if self._trade_subscription is not None
            and self._trade_subscription.observed_elapsed_ms <= observed_now_ms
            else None
        )
        price_started = (
            price_subscription.observed_elapsed_ms if price_subscription is not None else None
        )
        trade_started = (
            trade_subscription.observed_elapsed_ms if trade_subscription is not None else None
        )
        price_subscription_elapsed_ms = (
            min(seconds * 1_000, max(0, observed_now_ms - price_started))
            if price_started is not None
            else 0
        )
        trade_subscription_elapsed_ms = (
            min(seconds * 1_000, max(0, observed_now_ms - trade_started))
            if trade_started is not None
            else 0
        )
        prices = (
            self._selected_prices(
                market_start_ms,
                market_now_ms,
                after_capture_seq=(
                    price_subscription.capture_seq if price_subscription is not None else None
                ),
            )
            if market_start_ms is not None and market_now_ms is not None
            else ()
        )
        price_anchor = (
            next(
                (item for item in reversed(prices) if item.source_at_ms <= market_start_ms),
                None,
            )
            if market_start_ms is not None
            else None
        )
        price_endpoint = next(
            (item for item in reversed(prices) if item.source_at_ms == market_now_ms),
            None,
        )
        price_market_lookback_ms = (
            min(
                seconds * 1_000,
                max(0, price_endpoint.source_at_ms - price_anchor.source_at_ms),
            )
            if price_anchor is not None and price_endpoint is not None
            else 0
        )
        price_watermark_progress_age_ms = (
            max(0, observed_now_ms - self._market_watermark_progress_elapsed_ms)
            if market_now_ms is not None and self._market_watermark_progress_elapsed_ms is not None
            else None
        )
        price_elapsed_complete = price_subscription_elapsed_ms == seconds * 1_000
        price_market_complete = (
            price_anchor is not None
            and price_endpoint is not None
            and market_start_ms is not None
            and price_anchor.source_at_ms <= market_start_ms
            and price_endpoint.source_at_ms == market_now_ms
            and price_market_lookback_ms == seconds * 1_000
        )
        price_watermark_live = (
            price_watermark_progress_age_ms is not None
            and price_watermark_progress_age_ms <= self.input_contract.reference_freshness_ms
        )
        price_complete = (
            market_now_ms is not None
            and price_elapsed_complete
            and price_market_complete
            and price_watermark_live
            and not reconnect_contaminated
        )
        trade_complete = (
            market_now_ms is not None
            and trade_subscription_elapsed_ms == seconds * 1_000
            and not reconnect_contaminated
            and not gap_contaminated
        )
        reasons: list[str] = []
        if not price_elapsed_complete:
            reasons.append("PRICE_SUBSCRIPTION_LOOKBACK_INCOMPLETE")
        if not price_market_complete:
            reasons.append("PRICE_MARKET_LOOKBACK_INCOMPLETE")
        if not price_watermark_live:
            reasons.append("PRICE_MARKET_WATERMARK_STALE")
        if not trade_complete:
            reasons.append("TRADE_LOOKBACK_INCOMPLETE")
        if gap_contaminated:
            reasons.append("TRADE_GAP_IN_WINDOW")
        if reconnect_contaminated:
            reasons.append("RECONNECT_IN_WINDOW")
        coverage = WindowCoverage(
            requested_seconds=seconds,
            requested_market_start_at=(
                datetime.fromtimestamp(market_start_ms / 1_000, tz=UTC)
                if market_start_ms is not None
                else None
            ),
            market_as_of=(
                datetime.fromtimestamp(market_now_ms / 1_000, tz=UTC)
                if market_now_ms is not None
                else None
            ),
            price_market_anchor_at=(
                datetime.fromtimestamp(price_anchor.source_at_ms / 1_000, tz=UTC)
                if price_anchor is not None
                else None
            ),
            price_market_endpoint_at=(
                datetime.fromtimestamp(price_endpoint.source_at_ms / 1_000, tz=UTC)
                if price_endpoint is not None
                else None
            ),
            price_market_lookback_seconds=int(price_market_lookback_ms / 1_000),
            price_subscription_elapsed_seconds=int(price_subscription_elapsed_ms / 1_000),
            trade_subscription_elapsed_seconds=int(trade_subscription_elapsed_ms / 1_000),
            price_watermark_progress_age_ms=price_watermark_progress_age_ms,
            price_complete=price_complete,
            trade_complete=trade_complete,
            gap_contaminated=gap_contaminated,
            reconnect_contaminated=reconnect_contaminated,
            incomplete_reasons=tuple(reasons),
        )
        trades = tuple(
            item
            for item in self._trade_samples
            if market_start_ms is not None
            and market_now_ms is not None
            and trade_subscription is not None
            and item.capture_seq > trade_subscription.capture_seq
            and market_start_ms <= item.source_at_ms <= market_now_ms
        )
        return WindowObservation(
            coverage=coverage,
            path=self._path_metrics(prices) if price_complete else None,
            flow=self._flow_metrics(trades) if trade_complete else None,
            source_capture_seqs=tuple(
                sorted(
                    {
                        *(item.capture_seq for item in prices),
                        *(item.capture_seq for item in trades),
                        *(() if price_subscription is None else (price_subscription.capture_seq,)),
                        *(() if trade_subscription is None else (trade_subscription.capture_seq,)),
                        *(item.capture_seq for item in gaps),
                        *(item.capture_seq for item in reconnects),
                    }
                )
            ),
        )

    def _selected_prices(
        self,
        start_ms: int,
        end_ms: int,
        *,
        after_capture_seq: int | None,
    ) -> tuple[_PriceSample, ...]:
        ordered = tuple(
            sorted(
                (
                    item
                    for item in self._price_samples
                    if item.source_at_ms <= end_ms
                    and (after_capture_seq is None or item.capture_seq > after_capture_seq)
                ),
                key=lambda item: (item.source_at_ms, item.capture_seq),
            )
        )
        before = tuple(item for item in ordered if item.source_at_ms < start_ms)
        inside = tuple(item for item in ordered if item.source_at_ms >= start_ms)
        return (*((before[-1],) if before else ()), *inside)

    @staticmethod
    def _path_metrics(
        samples: tuple[_PriceSample, ...],
    ) -> PathMetrics | None:
        if len(samples) < 2 or samples[0].price == 0:
            return None
        prices = tuple(item.price for item in samples)
        returns = tuple(
            (current - previous) / previous
            for previous, current in pairwise(prices)
            if previous != 0
        )
        absolute_path = sum((abs(item) for item in returns), Decimal("0"))
        net_return = (prices[-1] - prices[0]) / prices[0]
        directional_efficiency = (
            min(Decimal("1"), abs(net_return) / absolute_path)
            if absolute_path > 0
            else Decimal("0")
        )
        prior_prices = prices[:-1]
        breakout = (
            BreakoutDirection.UP
            if prices[-1] > max(prior_prices)
            else BreakoutDirection.DOWN
            if prices[-1] < min(prior_prices)
            else BreakoutDirection.NONE
        )
        return PathMetrics(
            return_fraction=net_return,
            range_fraction=(max(prices) - min(prices)) / prices[0],
            realized_variation=sum(
                (item * item for item in returns),
                Decimal("0"),
            ).sqrt(),
            directional_efficiency=directional_efficiency,
            maximum_up_fraction=(max(prices) - prices[0]) / prices[0],
            maximum_down_fraction=(min(prices) - prices[0]) / prices[0],
            maximum_step_fraction=max(
                (abs(item) for item in returns),
                default=Decimal("0"),
            ),
            breakout=breakout,
        )

    @staticmethod
    def _flow_metrics(samples: tuple[_TradeSample, ...]) -> FlowMetrics:
        volume = sum((item.amount for item in samples), Decimal("0"))
        signed = sum(
            (item.amount if item.direction == "buy" else -item.amount for item in samples),
            Decimal("0"),
        )
        liquidation = sum(
            (
                item.amount
                if item.liquidation == "T" and item.direction == "buy"
                else -item.amount
                if item.liquidation == "T"
                else -item.amount
                if item.liquidation == "M" and item.direction == "buy"
                else item.amount
                if item.liquidation == "M"
                else Decimal("0")
                for item in samples
            ),
            Decimal("0"),
        )
        return FlowMetrics(
            trade_volume=volume,
            aggressor_imbalance=(signed / volume if volume > 0 else Decimal("0")),
            liquidation_amount=liquidation,
            liquidation_fraction=(
                max(Decimal("-1"), min(Decimal("1"), liquidation / volume))
                if volume > 0
                else Decimal("0")
            ),
        )

    def _prune(self, observed_now_ms: int) -> None:
        cutoff = observed_now_ms - max(self.input_contract.required_windows_seconds) * 2_000
        self._price_samples = [
            item for item in self._price_samples if item.observed_elapsed_ms >= cutoff
        ]
        self._trade_samples = [
            item for item in self._trade_samples if item.observed_elapsed_ms >= cutoff
        ]
        self._trade_gaps = [item for item in self._trade_gaps if item.observed_elapsed_ms >= cutoff]
        self._reconnects = [item for item in self._reconnects if item.observed_elapsed_ms >= cutoff]

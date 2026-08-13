from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from itertools import pairwise
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from optimatrix.decision import (
    DecisionWindow,
    MarketObservation,
    schedule_decision_windows,
)
from optimatrix.market import (
    EventState,
    EventStateSource,
    ImpliedVarianceMethod,
    MarketContext,
    MarketContextEvidence,
    OptionQuote,
    OptionType,
    PriceLevel,
    RealizedVarianceMethod,
    TickSchedule,
    TickStep,
)
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.products import BTC
from optimatrix.session import current_deribit_session
from optimatrix.structure import (
    Btc0DteCondorSelection,
    select_btc_0dte_condor,
)

DEFAULT_DERIBIT_API = "https://www.deribit.com/api/v2"


class DeribitSourceError(RuntimeError):
    """A bounded public Deribit snapshot could not be interpreted truthfully."""


class PublicRpcClient(Protocol):
    def call(self, method: str, params: Mapping[str, object]) -> object: ...


@dataclass(frozen=True)
class SnapshotMethodology:
    delta_method: str
    concentration_method: str
    index_history_cadence_ms: int
    book_fetch_mode: str

    def as_object(self) -> dict[str, object]:
        return {
            "delta_method": self.delta_method,
            "concentration_method": self.concentration_method,
            "index_history_cadence_ms": self.index_history_cadence_ms,
            "book_fetch_mode": self.book_fetch_mode,
        }


@dataclass(frozen=True)
class PublicSnapshotEvaluation:
    observed_at: datetime
    session_id: str
    instrument_count: int
    requested_book_count: int
    fetched_book_count: int
    quotes: tuple[OptionQuote, ...]
    context: MarketContext
    observation: MarketObservation
    selection: Btc0DteCondorSelection | None
    methodology: SnapshotMethodology
    warnings: tuple[str, ...]
    decision_window: DecisionWindow

    def as_object(self) -> dict[str, object]:
        structure = self.selection.selected if self.selection is not None else None
        projection_state = (
            "UNKNOWN"
            if self.observation.data_health_blockers
            else "STRUCTURE_FOUND"
            if structure is not None
            else "NO_STRUCTURE"
        )
        blockers = (
            self.observation.data_health_blockers
            if self.observation.data_health_blockers
            else ("BOUNDED_SNAPSHOT_IS_NOT_A_DECISION_RECORD",)
            if structure is not None
            else self.selection.blockers
            if self.selection is not None
            else ("STRUCTURE_NOT_EVALUATED",)
        )
        return {
            "observed_at": self.observed_at.isoformat(),
            "session_id": self.session_id,
            "instrument_count": self.instrument_count,
            "requested_book_count": self.requested_book_count,
            "fetched_book_count": self.fetched_book_count,
            "methodology": {
                "realized_variance_method": (
                    self.context.evidence.realized_variance_method.value
                    if self.context.evidence.realized_variance_method is not None
                    else None
                ),
                "implied_variance_method": (
                    self.context.evidence.implied_variance_method.value
                    if self.context.evidence.implied_variance_method is not None
                    else None
                ),
                "event_state_source": (
                    self.context.evidence.event_state_source.value
                    if self.context.evidence.event_state_source is not None
                    else None
                ),
                **self.methodology.as_object(),
            },
            "warnings": list(self.warnings),
            "window": {
                **self.decision_window.as_object(),
                "observation_id": self.observation.identity,
                "ledger_state": "NOT_RECORDED_BY_BOUNDED_SNAPSHOT",
            },
            "market_counts": {
                "current_session_instruments": self.instrument_count,
                "books_requested": self.requested_book_count,
                "usable_quotes": len(self.quotes),
                "legal_structures": self.selection.legal_structure_count
                if self.selection is not None
                else None,
                "price_evaluable_structures": self.selection.price_evaluable_count
                if self.selection is not None
                else None,
                "policy_eligible_structures": self.selection.policy_eligible_count
                if self.selection is not None
                else None,
                "projection": projection_state,
            },
            "context": {
                "knowledge": self.context.knowledge.value,
                "index_price": str(self.context.index_price),
                "forward_price": str(self.context.forward_price),
                "trailing_realized_variance_proxy": str(
                    self.context.trailing_realized_variance_proxy
                ),
                "same_session_implied_variance_proxy": str(
                    self.context.same_session_implied_variance_proxy
                ),
                "rv_acceleration": str(self.context.rv_acceleration),
                "jump_share": str(self.context.jump_share),
                "directional_persistence": str(self.context.directional_persistence),
                "event_state": self.context.event_state.value,
                "concentrated_strike": (
                    str(self.context.concentrated_strike)
                    if self.context.concentrated_strike is not None
                    else None
                ),
                "concentration_strength": str(self.context.concentration_strength),
                "realized_variance_method": (
                    self.context.evidence.realized_variance_method.value
                    if self.context.evidence.realized_variance_method is not None
                    else None
                ),
                "implied_variance_method": (
                    self.context.evidence.implied_variance_method.value
                    if self.context.evidence.implied_variance_method is not None
                    else None
                ),
                "event_state_source": (
                    self.context.evidence.event_state_source.value
                    if self.context.evidence.event_state_source is not None
                    else None
                ),
                "required_history_start_ms": self.context.evidence.required_history_start_ms,
                "history_coverage_start_ms": self.context.evidence.history_coverage_start_ms,
                "history_coverage_end_ms": self.context.evidence.history_coverage_end_ms,
                "history_cadence_ms": self.context.evidence.history_cadence_ms,
                "market_source_min_ms": self.context.evidence.market_source_min_ms,
                "market_source_max_ms": self.context.evidence.market_source_max_ms,
                "market_received_min_ms": self.context.evidence.market_received_min_ms,
                "market_received_max_ms": self.context.evidence.market_received_max_ms,
                "event_state_known_at_ms": self.context.evidence.event_state_known_at_ms,
            },
            "projection": {
                "state": projection_state,
                "phase": current_deribit_session(self.observed_at).phase.value,
                "blockers": list(blockers),
                "structure": (
                    {
                        "long_put": structure.long_put.instrument_name,
                        "short_put": structure.short_put.instrument_name,
                        "short_call": structure.short_call.instrument_name,
                        "long_call": structure.long_call.instrument_name,
                        "boundary_net_credit_usd": str(structure.pricing.boundary_net_credit_usd),
                        "boundary_reference_loss_usd": str(
                            structure.pricing.boundary_reference_loss_usd
                        ),
                        "native_net_credit_btc": str(structure.pricing.native_net_credit),
                        "combo_standard_fee_btc": str(structure.pricing.combo_standard_fee_native),
                        "maximum_contractual_payoff_cap_usd": str(
                            structure.pricing.maximum_contractual_payoff_cap_usd
                        ),
                        "net_delta": str(structure.net_delta),
                        "minimum_body_distance_sigma": str(structure.minimum_body_distance_sigma),
                        "minimum_observed_close_depth_coverage": str(
                            min(structure.close_depth_coverage)
                        ),
                    }
                    if structure is not None
                    else None
                ),
            },
            "quotes": [
                {
                    "instrument_name": quote.instrument_name,
                    "strike": str(quote.strike),
                    "option_type": quote.option_type.value,
                    "signed_delta": str(quote.signed_delta),
                    "mark_iv": str(quote.mark_iv),
                    "best_bid": str(quote.bid[0].price) if quote.bid else None,
                    "best_ask": str(quote.ask[0].price) if quote.ask else None,
                    "open_interest": str(quote.open_interest),
                    "gamma": str(quote.gamma),
                    "source_timestamp_ms": quote.source_timestamp_ms,
                    "received_timestamp_ms": quote.received_timestamp_ms,
                    "delivery_fee_exempt": quote.delivery_fee_exempt,
                }
                for quote in self.quotes
            ],
        }


class DeribitHttpClient:
    """Small read-only HTTP client for bounded local validation."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_DERIBIT_API,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def call(self, method: str, params: Mapping[str, object]) -> object:
        if not method.startswith("public/"):
            raise ValueError("only public Deribit methods are allowed")
        query = urlencode(
            {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in params.items()
            }
        )
        request = Request(
            f"{self.base_url}/{method}?{query}",
            headers={"User-Agent": "optimatrix-btc-0dte/0.1"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, HTTPException, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeribitSourceError(
                f"Deribit request failed: {method}: {type(exc).__name__}: {exc}"
            ) from exc
        root = _mapping(payload, "JSON-RPC response")
        if root.get("error") is not None:
            raise DeribitSourceError(f"Deribit returned an error for {method}")
        if "result" not in root:
            raise DeribitSourceError(f"Deribit response lacks result: {method}")
        return root["result"]


def evaluate_live_btc_snapshot(
    *,
    client: PublicRpcClient,
    policy: BtcShortVolPolicy,
    now: datetime,
    event_state: EventState,
    maximum_books: int = 32,
    depth: int = 20,
) -> PublicSnapshotEvaluation:
    """Evaluate one current-session public snapshot without opening a Case."""

    if maximum_books < 4:
        raise ValueError("maximum_books must allow at least four option books")
    if depth not in {1, 5, 10, 20, 50, 100, 1000, 10000}:
        raise ValueError("depth is outside Deribit's supported values")
    normalized_now = _utc(now)
    session = current_deribit_session(normalized_now, phase_policy=policy.session)
    index_result = _mapping(
        client.call("public/get_index_price", {"index_name": BTC.price_index}),
        "index price result",
    )
    index_price = _positive_decimal(index_result.get("index_price"), "index_price")
    instruments = _instrument_metadata(
        client.call(
            "public/get_instruments",
            {"currency": BTC.public_currency, "kind": "option", "expired": False},
        ),
        session_end_ms=int(session.end.timestamp() * 1000),
    )
    selected_metadata = _shortlist_instruments(
        instruments,
        index_price=index_price,
        maximum_books=maximum_books,
    )
    quotes, forwards, fetch_warnings = _fetch_books(
        client=client,
        metadata=selected_metadata,
        depth=depth,
    )
    warnings: list[str] = list(fetch_warnings)
    if len(quotes) < 4:
        raise DeribitSourceError("fewer than four current-session option books were usable")
    history = _index_history(
        client.call(
            "public/get_index_chart_data",
            {"index_name": BTC.price_index, "range": "2d"},
        ),
        now_ms=int(normalized_now.timestamp() * 1000),
    )
    horizon_minutes = max(
        5,
        session.minutes_to_expiry - policy.lifecycle.latest_exit_minutes_to_expiry,
    )
    history_cadence_ms = _history_cadence_ms(history, horizon_minutes=horizon_minutes)
    physical_variance, acceleration, jump_share, persistence = _physical_path_context(
        history,
        horizon_minutes=horizon_minutes,
        expected_cadence_ms=history_cadence_ms,
    )
    forward = _median(forwards) if forwards else index_price
    implied_variance, implied_warnings = _same_session_implied_variance(
        tuple(quotes),
        forward_price=forward,
        horizon_minutes=horizon_minutes,
    )
    warnings.extend(implied_warnings)
    concentrated_strike, concentration_strength = _concentration(tuple(quotes))
    methodology = SnapshotMethodology(
        delta_method="DERIBIT_ORDER_BOOK_GREEKS",
        concentration_method=("SHORTLISTED_PUBLIC_OPEN_INTEREST_TIMES_ABSOLUTE_GAMMA"),
        index_history_cadence_ms=history_cadence_ms,
        book_fetch_mode="BOUNDED_CONCURRENT_PUBLIC_GET_ORDER_BOOK",
    )
    request_boundary_ms = int(normalized_now.timestamp() * 1000)
    known_at_ms = max(request_boundary_ms, int(time.time() * 1000))
    known_at = datetime.fromtimestamp(known_at_ms / 1000, tz=UTC)
    requested_books = tuple(sorted(str(item["instrument_name"]) for item in selected_metadata))
    usable_books = tuple(sorted(quote.instrument_name for quote in quotes))
    evidence_blockers: list[str] = []
    if any(quote.source_timestamp_ms > quote.received_timestamp_ms for quote in quotes):
        evidence_blockers.append("MARKET_SOURCE_AFTER_RECEIPT")
    if (
        current_deribit_session(known_at, phase_policy=policy.session).session_id
        != session.session_id
    ):
        evidence_blockers.append("SNAPSHOT_CROSSED_SESSION_BOUNDARY")
    evidence = MarketContextEvidence(
        realized_variance_method=(
            RealizedVarianceMethod.TRAILING_MATCHED_HORIZON_INDEX_REALIZED_VARIANCE_PROXY
        ),
        implied_variance_method=(
            ImpliedVarianceMethod.NEAREST_ATM_CALL_PUT_MARK_IV_SQUARED_TIMES_RISK_HORIZON
        ),
        event_state_source=EventStateSource.EXPLICIT_HUMAN_OR_EXTERNAL_CALENDAR_INPUT,
        required_history_start_ms=history[-1][0] - horizon_minutes * 60_000,
        history_coverage_start_ms=history[0][0],
        history_coverage_end_ms=history[-1][0],
        history_cadence_ms=history_cadence_ms,
        market_source_min_ms=min(quote.source_timestamp_ms for quote in quotes),
        market_source_max_ms=max(quote.source_timestamp_ms for quote in quotes),
        market_received_min_ms=min(quote.received_timestamp_ms for quote in quotes),
        market_received_max_ms=max(quote.received_timestamp_ms for quote in quotes),
        event_state_known_at_ms=request_boundary_ms,
        maximum_market_age_ms=policy.observation.maximum_age_ms,
        requested_books=requested_books,
        usable_books=usable_books,
        declared_blockers=tuple(evidence_blockers),
    )
    context = MarketContext(
        now=known_at,
        index_price=index_price,
        forward_price=forward,
        trailing_realized_variance_proxy=physical_variance,
        same_session_implied_variance_proxy=implied_variance,
        rv_acceleration=acceleration,
        jump_share=jump_share,
        directional_persistence=persistence,
        event_state=event_state,
        concentrated_strike=concentrated_strike,
        concentration_strength=concentration_strength,
        evidence=evidence,
    )
    windows = schedule_decision_windows(
        session=session,
        channel_id=policy.channel_id,
        policy=policy.window,
    )
    decision_window = next(
        (window for window in windows if window.starts_at <= context.now < window.ends_at),
        windows[-1],
    )
    observation = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=context,
        quotes=tuple(quotes),
    )
    selection = (
        None
        if observation.data_health_blockers
        else select_btc_0dte_condor(observation=observation, policy=policy)
    )
    return PublicSnapshotEvaluation(
        observed_at=known_at,
        session_id=session.session_id,
        instrument_count=len(instruments),
        requested_book_count=len(selected_metadata),
        fetched_book_count=len(quotes),
        quotes=tuple(quotes),
        context=context,
        observation=observation,
        selection=selection,
        methodology=methodology,
        warnings=tuple(sorted(set((*warnings, "OI_GAMMA_CONCENTRATION_IS_SHORTLIST_ONLY")))),
        decision_window=decision_window,
    )


def _fetch_books(
    *,
    client: PublicRpcClient,
    metadata: tuple[dict[str, object], ...],
    depth: int,
) -> tuple[list[OptionQuote], list[Decimal], tuple[str, ...]]:
    quotes: list[OptionQuote] = []
    forwards: list[Decimal] = []
    warnings: list[str] = []

    def fetch_one(item: dict[str, object]) -> tuple[dict[str, object], object, int]:
        result = client.call(
            "public/get_order_book",
            {"instrument_name": item["instrument_name"], "depth": depth},
        )
        return item, result, int(time.time() * 1000)

    workers = min(8, max(1, len(metadata)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="deribit-book") as executor:
        futures = {executor.submit(fetch_one, item): item for item in metadata}
        for future in as_completed(futures):
            item = futures[future]
            instrument_name = str(item["instrument_name"])
            try:
                returned_metadata, raw_result, received_timestamp_ms = future.result()
                result = _mapping(raw_result, "order book result")
                quote, forward, quote_warnings = _quote_from_public_book(
                    metadata=returned_metadata,
                    result=result,
                    received_timestamp_ms=received_timestamp_ms,
                )
            except (DeribitSourceError, OSError, ValueError) as exc:
                warnings.append(
                    f"BOOK_REQUEST_OR_PARSE_FAILED:{instrument_name}:{type(exc).__name__}"
                )
                continue
            warnings.extend(f"{instrument_name}:{warning}" for warning in quote_warnings)
            if quote is not None:
                quotes.append(quote)
            if forward is not None:
                forwards.append(forward)
    quotes.sort(key=lambda quote: (quote.strike, quote.option_type.value, quote.instrument_name))
    return quotes, forwards, tuple(warnings)


def _instrument_metadata(value: object, *, session_end_ms: int) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise DeribitSourceError("instrument result must be an array")
    output: list[dict[str, object]] = []
    for raw in value:
        item = _mapping(raw, "instrument")
        if item.get("kind") != "option" or item.get("is_active") is not True:
            continue
        if _integer(item.get("expiration_timestamp"), "expiration_timestamp") != session_end_ms:
            continue
        required_product = {
            "base_currency": BTC.base_currency,
            "settlement_currency": BTC.settlement_currency,
            "price_index": BTC.price_index,
        }
        if any(item.get(field) != expected for field, expected in required_product.items()):
            continue
        instrument_name = _text(item.get("instrument_name"), "instrument_name")
        if not instrument_name.startswith(BTC.instrument_prefix):
            continue
        contract_size = _positive_decimal(item.get("contract_size"), "contract_size")
        minimum = _positive_decimal(item.get("min_trade_amount"), "min_trade_amount")
        if contract_size != 1 or minimum > BTC.minimum_quantity:
            continue
        option_type = _text(item.get("option_type"), "option_type").lower()
        if option_type not in {"call", "put"}:
            continue
        settlement_period = _text(item.get("settlement_period"), "settlement_period").lower()
        output.append(
            {
                "instrument_name": instrument_name,
                "expiration_timestamp": session_end_ms,
                "strike": _positive_decimal(item.get("strike"), "strike"),
                "option_type": option_type,
                "tick_size": _positive_decimal(item.get("tick_size"), "tick_size"),
                "tick_size_steps": item.get("tick_size_steps", []),
                "settlement_period": settlement_period,
            }
        )
    return tuple(output)


def _shortlist_instruments(
    instruments: tuple[dict[str, object], ...],
    *,
    index_price: Decimal,
    maximum_books: int,
) -> tuple[dict[str, object], ...]:
    lower = index_price * Decimal("0.75")
    upper = index_price * Decimal("1.25")
    in_range = [
        item
        for item in instruments
        if lower <= _positive_decimal(item["strike"], "strike") <= upper
    ]
    per_side = maximum_books // 2
    selected: list[dict[str, object]] = []
    for option_type in ("put", "call"):
        side = [
            item
            for item in in_range
            if item["option_type"] == option_type
            and (
                _positive_decimal(item["strike"], "strike") < index_price
                if option_type == "put"
                else _positive_decimal(item["strike"], "strike") > index_price
            )
        ]
        side.sort(
            key=lambda item: abs(
                math.log(float(_positive_decimal(item["strike"], "strike") / index_price))
            )
        )
        selected.extend(side[:per_side])
    selected.sort(
        key=lambda item: (
            _positive_decimal(item["strike"], "strike"),
            item["option_type"],
        )
    )
    return tuple(selected[:maximum_books])


def _quote_from_public_book(
    *,
    metadata: Mapping[str, object],
    result: Mapping[str, object],
    received_timestamp_ms: int,
) -> tuple[OptionQuote | None, Decimal | None, tuple[str, ...]]:
    warnings: list[str] = []
    if result.get("state") != "open":
        return None, None, ("BOOK_NOT_OPEN",)
    instrument_name = _text(result.get("instrument_name"), "book.instrument_name")
    if instrument_name != metadata["instrument_name"]:
        raise DeribitSourceError("order book instrument identity mismatch")
    greeks = _mapping(result.get("greeks"), "greeks")
    signed_delta = _decimal(greeks.get("delta"), "greeks.delta")
    gamma = max(Decimal(0), _decimal(greeks.get("gamma"), "greeks.gamma"))
    mark_iv = _decimal(result.get("mark_iv"), "mark_iv")
    if mark_iv > 3:
        mark_iv /= Decimal(100)
    bids = _book_levels(result.get("bids"), "bids")
    asks = _book_levels(result.get("asks"), "asks")
    tick_steps = _tick_steps(metadata.get("tick_size_steps"))
    settlement_period = str(metadata["settlement_period"])
    if settlement_period not in {"day", "week", "month"}:
        warnings.append(f"UNRECOGNIZED_SETTLEMENT_PERIOD:{settlement_period}")
    quote = OptionQuote(
        instrument_name=instrument_name,
        product=BTC,
        expiry=datetime.fromtimestamp(
            _integer(metadata["expiration_timestamp"], "expiration_timestamp") / 1000,
            tz=UTC,
        ),
        strike=_positive_decimal(metadata["strike"], "strike"),
        option_type=(OptionType.CALL if metadata["option_type"] == "call" else OptionType.PUT),
        signed_delta=signed_delta,
        mark_iv=mark_iv,
        bid=bids,
        ask=asks,
        tick_schedule=TickSchedule(
            _positive_decimal(metadata["tick_size"], "tick_size"),
            tick_steps,
        ),
        source_timestamp_ms=_integer(result.get("timestamp"), "timestamp"),
        received_timestamp_ms=received_timestamp_ms,
        continuity_epoch=1,
        delivery_fee_exempt=settlement_period == "day",
        open_interest=max(
            Decimal(0),
            _decimal(result.get("open_interest", 0), "open_interest"),
        ),
        gamma=gamma,
    )
    forward_raw = result.get("underlying_price")
    forward = (
        _positive_decimal(forward_raw, "underlying_price") if forward_raw is not None else None
    )
    return quote, forward, tuple(warnings)


def _book_levels(value: object, field: str) -> tuple[PriceLevel, ...]:
    if not isinstance(value, list):
        raise DeribitSourceError(f"{field} must be an array")
    output: list[PriceLevel] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            raise DeribitSourceError(f"{field} contains a malformed level")
        price = _decimal(raw[0], f"{field}.price")
        quantity = _decimal(raw[1], f"{field}.quantity")
        if price <= 0 or quantity <= 0:
            continue
        output.append(PriceLevel(price, quantity))
    return tuple(output)


def _tick_steps(value: object) -> tuple[TickStep, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise DeribitSourceError("tick_size_steps must be an array")
    output: list[TickStep] = []
    for raw in value:
        item = _mapping(raw, "tick step")
        output.append(
            TickStep(
                above_price=_decimal(item.get("above_price"), "above_price"),
                tick_size=_positive_decimal(item.get("tick_size"), "tick_size"),
            )
        )
    return tuple(output)


def _index_history(value: object, *, now_ms: int) -> tuple[tuple[int, Decimal], ...]:
    if not isinstance(value, list):
        raise DeribitSourceError("index history must be an array")
    output: list[tuple[int, Decimal]] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) != 2:
            raise DeribitSourceError("index history point is malformed")
        timestamp = _integer(raw[0], "history timestamp")
        price = _positive_decimal(raw[1], "history price")
        if timestamp <= now_ms:
            output.append((timestamp, price))
    output.sort(key=lambda point: point[0])
    if len(output) < 3 or any(current[0] <= previous[0] for previous, current in pairwise(output)):
        raise DeribitSourceError("index history is not strictly chronological")
    return tuple(output)


def _history_cadence_ms(
    history: tuple[tuple[int, Decimal], ...],
    *,
    horizon_minutes: int,
) -> int:
    end_ms = history[-1][0]
    start_ms = end_ms - max(horizon_minutes, 120) * 60_000
    tail = [point for point in history if point[0] >= start_ms]
    intervals = [
        current[0] - previous[0] for previous, current in pairwise(tail) if current[0] > previous[0]
    ]
    if not intervals:
        raise DeribitSourceError("index history cadence is unavailable")
    counts: dict[int, int] = {}
    for interval in intervals:
        counts[interval] = counts.get(interval, 0) + 1
    cadence = min(counts, key=lambda interval: (-counts[interval], interval))
    if cadence <= 0 or cadence > 15 * 60_000:
        raise DeribitSourceError("index history cadence is too coarse")
    return cadence


def _physical_path_context(
    history: tuple[tuple[int, Decimal], ...],
    *,
    horizon_minutes: int,
    expected_cadence_ms: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    end_ms = history[-1][0]
    horizon_start = end_ms - horizon_minutes * 60_000
    horizon_prices = [point for point in history if point[0] >= horizon_start]
    if len(horizon_prices) < 3:
        raise DeribitSourceError("index history does not cover the risk horizon")
    if horizon_prices[0][0] > horizon_start + expected_cadence_ms * 2:
        raise DeribitSourceError("index history starts too late for the risk horizon")
    if any(
        current[0] - previous[0] > expected_cadence_ms * 2
        for previous, current in pairwise(horizon_prices)
    ):
        raise DeribitSourceError("index history contains a material risk-horizon gap")
    returns = _log_returns(horizon_prices)
    physical = max(Decimal("1e-12"), sum((value * value for value in returns), Decimal(0)))
    short_start = end_ms - 30 * 60_000
    long_start = end_ms - 120 * 60_000
    short_returns = _log_returns([point for point in history if point[0] >= short_start])
    long_returns = _log_returns([point for point in history if point[0] >= long_start])
    short_rate = _variance_rate(short_returns)
    long_rate = _variance_rate(long_returns)
    acceleration = (
        _clamp((short_rate / long_rate - Decimal(1)) / Decimal(2)) if long_rate > 0 else Decimal(0)
    )
    squared = tuple(value * value for value in returns)
    jump_share = _clamp(max(squared) / physical) if squared else Decimal(0)
    absolute_sum = sum((abs(value) for value in returns), Decimal(0))
    persistence = (
        _clamp(abs(sum(returns, Decimal(0))) / absolute_sum) if absolute_sum > 0 else Decimal(0)
    )
    return physical, acceleration, jump_share, persistence


def _same_session_implied_variance(
    quotes: tuple[OptionQuote, ...],
    *,
    forward_price: Decimal,
    horizon_minutes: int,
) -> tuple[Decimal, tuple[str, ...]]:
    del forward_price
    calls = [quote for quote in quotes if quote.option_type is OptionType.CALL]
    puts = [quote for quote in quotes if quote.option_type is OptionType.PUT]
    if not calls or not puts:
        raise DeribitSourceError("ATM implied variance requires both Call and Put quotes")
    call = min(calls, key=lambda quote: abs(abs(quote.signed_delta) - Decimal("0.5")))
    put = min(puts, key=lambda quote: abs(abs(quote.signed_delta) - Decimal("0.5")))
    warnings: list[str] = []
    for label, quote in (("CALL", call), ("PUT", put)):
        distance = abs(abs(quote.signed_delta) - Decimal("0.5"))
        if distance > Decimal("0.15"):
            warnings.append(f"{label}_ATM_PROXY_DELTA_DISTANCE_WIDE:{distance}")
    average_iv = (call.mark_iv + put.mark_iv) / Decimal(2)
    year_fraction = Decimal(horizon_minutes) / Decimal(365 * 24 * 60)
    variance = max(Decimal("1e-12"), average_iv * average_iv * year_fraction)
    return variance, tuple(warnings)


def _concentration(
    quotes: tuple[OptionQuote, ...],
) -> tuple[Decimal | None, Decimal]:
    by_strike: dict[Decimal, Decimal] = {}
    for quote in quotes:
        by_strike[quote.strike] = by_strike.get(quote.strike, Decimal(0)) + (
            quote.open_interest * abs(quote.gamma)
        )
    total = sum(by_strike.values(), Decimal(0))
    if total <= 0:
        return None, Decimal(0)
    strike, weight = max(by_strike.items(), key=lambda item: item[1])
    return strike, _clamp(weight / total)


def _log_returns(points: Sequence[tuple[int, Decimal]]) -> tuple[Decimal, ...]:
    if len(points) < 2:
        return ()
    return tuple((current[1] / previous[1]).ln() for previous, current in pairwise(points))


def _variance_rate(returns: tuple[Decimal, ...]) -> Decimal:
    if not returns:
        return Decimal(0)
    return sum((value * value for value in returns), Decimal(0)) / Decimal(len(returns))


def _median(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DeribitSourceError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeribitSourceError(f"{field} must be non-empty text")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DeribitSourceError(f"{field} must be decimal-compatible")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DeribitSourceError(f"{field} must be decimal-compatible") from exc
    if not parsed.is_finite():
        raise DeribitSourceError(f"{field} must be finite")
    return parsed


def _positive_decimal(value: object, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed <= 0:
        raise DeribitSourceError(f"{field} must be positive")
    return parsed


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeribitSourceError(f"{field} must be an integer")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))

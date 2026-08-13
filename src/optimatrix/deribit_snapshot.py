from __future__ import annotations

import gzip
import json
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException, HTTPSConnection
from itertools import pairwise
from typing import Protocol
from urllib.parse import urlsplit

from optimatrix.decision import (
    DecisionWindow,
    MarketObservation,
    schedule_decision_windows,
)
from optimatrix.lifecycle import FuturePathSummary
from optimatrix.market import (
    EventState,
    EventStateSource,
    ExpirySettlementFact,
    ImpliedVarianceMethod,
    MarketContext,
    MarketContextEvidence,
    OptionQuote,
    OptionType,
    PriceLevel,
    RealizedVarianceMethod,
    SettlementEvidenceKind,
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
DERIBIT_PUBLIC_METHOD_ALLOWLIST = frozenset(
    {
        "public/get_delivery_prices",
        "public/get_index_chart_data",
        "public/get_index_price",
        "public/get_instruments",
        "public/get_order_book",
        "public/get_time",
    }
)
DERIBIT_DELIVERY_PRICE_SOURCE_ID = "DERIBIT_PUBLIC_GET_DELIVERY_PRICES_BTC_USD"
DERIBIT_DELIVERY_PRICE_METHOD_ID = "DERIBIT_OFFICIAL_DELIVERY_PRICE_BY_EXPIRY_UTC_DATE_V1"
DERIBIT_INDEX_PATH_SOURCE_ID = "DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_BTC_USD_2D"
DERIBIT_INDEX_PATH_METHOD_ID = (
    "DERIBIT_CADENCE_COVERED_INDEX_PATH_ROLLING_30M_OVER_120M_RV_ACCELERATION_V1"
)


class DeribitSourceError(RuntimeError):
    """A bounded public Deribit snapshot could not be interpreted truthfully."""


class PublicRpcClient(Protocol):
    def call(self, method: str, params: Mapping[str, object]) -> object: ...


@dataclass(frozen=True)
class PublicRpcResponse:
    """One validated production Deribit JSON-RPC response and its local boundaries."""

    jsonrpc: str
    request_id: int
    result: object
    testnet: bool
    server_received_at_us: int
    server_sent_at_us: int
    server_processing_us: int
    local_sent_at_ms: int
    local_received_at_ms: int


@dataclass(frozen=True)
class PublicClockPreflight:
    server_time_ms: int
    local_time_ms: int
    clock_skew_ms: int
    request_round_trip_ms: int | None
    known_at: datetime


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
        audit_callback: Callable[[str, Mapping[str, object], float], None] | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("Deribit base_url must use HTTPS")
        parsed_base_url = urlsplit(base_url)
        if (
            parsed_base_url.scheme != "https"
            or parsed_base_url.hostname is None
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("Deribit base_url must be a plain HTTPS origin and path")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.base_url = base_url.rstrip("/")
        self._host = parsed_base_url.hostname
        self._port = parsed_base_url.port
        self._path = parsed_base_url.path.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.audit_callback = audit_callback
        self._next_request_id = 1
        self._request_id_lock = threading.Lock()

    def call(self, method: str, params: Mapping[str, object]) -> PublicRpcResponse:
        if method not in DERIBIT_PUBLIC_METHOD_ALLOWLIST:
            raise ValueError("only public Deribit methods in the B3 allowlist are allowed")
        if self.audit_callback is not None:
            self.audit_callback(method, dict(params), self.timeout_seconds)
        with self._request_id_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        connection = HTTPSConnection(
            self._host,
            port=self._port,
            timeout=self.timeout_seconds,
        )
        local_sent_at_ms = int(time.time() * 1000)
        try:
            connection.request(
                "POST",
                f"{self._path}/{method}",
                body=body.encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Connection": "keep-alive",
                    "Content-Type": "application/json",
                    "User-Agent": "optimatrix-btc-0dte/0.1",
                },
            )
            response = connection.getresponse()
            response_body = response.read()
            if response.status != 200:
                raise DeribitSourceError(
                    f"Deribit HTTP response is not successful: {response.status}"
                )
            content_encoding = response.getheader("Content-Encoding")
            if content_encoding == "gzip":
                response_body = gzip.decompress(response_body)
            elif content_encoding not in (None, "", "identity"):
                raise DeribitSourceError(
                    f"Deribit HTTP response uses unsupported encoding: {content_encoding}"
                )
            local_received_at_ms = int(time.time() * 1000)
            payload = json.loads(response_body.decode("utf-8"))
        except DeribitSourceError:
            raise
        except (
            OSError,
            EOFError,
            HTTPException,
            UnicodeDecodeError,
            gzip.BadGzipFile,
            json.JSONDecodeError,
        ) as exc:
            raise DeribitSourceError(
                f"Deribit request failed: {method}: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            connection.close()
        return _validated_public_rpc_response(
            payload,
            method=method,
            request_id=request_id,
            timeout_seconds=self.timeout_seconds,
            local_sent_at_ms=local_sent_at_ms,
            local_received_at_ms=local_received_at_ms,
        )


def preflight_public_clock(
    client: PublicRpcClient,
    *,
    local_now: datetime,
    maximum_clock_skew_ms: int,
) -> PublicClockPreflight:
    """Fail closed when Deribit's public clock is too far from the runtime clock."""

    if (
        isinstance(maximum_clock_skew_ms, bool)
        or not isinstance(maximum_clock_skew_ms, int)
        or maximum_clock_skew_ms < 0
    ):
        raise ValueError("maximum_clock_skew_ms must be a non-negative integer")
    normalized_local_now = _utc(local_now)
    local_time_ms = int(normalized_local_now.timestamp() * 1000)
    response = client.call("public/get_time", {})
    server_time_ms = _integer(_rpc_result(response), "public/get_time result")
    if server_time_ms <= 0:
        raise DeribitSourceError("public/get_time result must be positive")
    request_round_trip_ms: int | None = None
    known_at_ms = local_time_ms
    comparison_local_ms = local_time_ms
    if isinstance(response, PublicRpcResponse):
        earliest_server_ms = response.server_received_at_us // 1000 - 1
        latest_server_ms = (response.server_sent_at_us + 999) // 1000 + 1
        if not earliest_server_ms <= server_time_ms <= latest_server_ms:
            raise DeribitSourceError(
                "public/get_time result is outside its response timing envelope"
            )
        request_round_trip_ms = response.local_received_at_ms - response.local_sent_at_ms
        known_at_ms = max(known_at_ms, response.local_received_at_ms)
        comparison_local_ms = (response.local_sent_at_ms + response.local_received_at_ms) // 2
    clock_skew_ms = server_time_ms - comparison_local_ms
    if abs(clock_skew_ms) > maximum_clock_skew_ms:
        raise DeribitSourceError(
            "Deribit public clock skew exceeds the configured preflight boundary"
        )
    return PublicClockPreflight(
        server_time_ms=server_time_ms,
        local_time_ms=local_time_ms,
        clock_skew_ms=clock_skew_ms,
        request_round_trip_ms=request_round_trip_ms,
        known_at=datetime.fromtimestamp(known_at_ms / 1000, tz=UTC),
    )


def fetch_btc_index_history(
    client: PublicRpcClient,
    *,
    known_at: datetime,
) -> tuple[tuple[int, Decimal], ...]:
    """Read the validated public 2d BTC index series needed by WindowOutcome assembly."""

    normalized_known_at = _utc(known_at)
    response = client.call(
        "public/get_index_chart_data",
        {"index_name": BTC.price_index, "range": "2d"},
    )
    return _index_history(
        _rpc_result(response),
        now_ms=int(normalized_known_at.timestamp() * 1000),
    )


def summarize_btc_index_path(
    history: tuple[tuple[int, Decimal], ...],
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> FuturePathSummary | None:
    """Summarize one cadence-covered continuous path without deciding an Outcome."""

    normalized_start = _utc(starts_at)
    normalized_end = _utc(ends_at)
    if normalized_start >= normalized_end:
        raise ValueError("index path boundaries must have positive duration")
    points = _validated_index_history_points(history)
    start_ms = int(normalized_start.timestamp() * 1000)
    end_ms = int(normalized_end.timestamp() * 1000)
    path = tuple(point for point in points if start_ms <= point[0] <= end_ms)
    if not path:
        return None
    context_start_ms = start_ms - 120 * 60_000
    context = tuple(point for point in points if context_start_ms <= point[0] <= end_ms)
    try:
        cadence_ms = _history_cadence_ms(
            context,
            horizon_minutes=max(120, math.ceil((end_ms - context_start_ms) / 60_000)),
        )
    except DeribitSourceError:
        return None
    if (
        not context
        or context[0][0] > context_start_ms + cadence_ms * 2
        or path[0][0] > start_ms + cadence_ms * 2
        or path[-1][0] < end_ms - cadence_ms * 2
        or any(current[0] - previous[0] > cadence_ms * 2 for previous, current in pairwise(path))
    ):
        return None
    accelerations: list[Decimal] = []
    for timestamp_ms, _ in path:
        acceleration = _rolling_rv_acceleration(
            points,
            at_ms=timestamp_ms,
            expected_cadence_ms=cadence_ms,
        )
        if acceleration is None:
            return None
        accelerations.append(acceleration)
    prices = tuple(price for _, price in path)
    return FuturePathSummary(
        source_id=DERIBIT_INDEX_PATH_SOURCE_ID,
        method_id=DERIBIT_INDEX_PATH_METHOD_ID,
        starts_at=normalized_start,
        ends_at=normalized_end,
        observation_count=len(path),
        start_index_price_usd=prices[0],
        end_index_price_usd=prices[-1],
        minimum_index_price_usd=min(prices),
        maximum_index_price_usd=max(prices),
        maximum_rv_acceleration=max(accelerations),
    )


def fetch_btc_expiry_settlement(
    client: PublicRpcClient,
    *,
    expiry: datetime,
    known_at: datetime,
) -> ExpirySettlementFact:
    """Translate the exact UTC expiry-date row into one official BTC settlement fact."""

    normalized_expiry = _utc(expiry)
    normalized_known_at = _utc(known_at)
    if normalized_known_at < normalized_expiry:
        raise ValueError("settlement lookup cannot run before expiry")
    response = client.call(
        "public/get_delivery_prices",
        {"index_name": BTC.price_index, "offset": 0, "count": 10},
    )
    result = _mapping(_rpc_result(response), "delivery price result")
    data = result.get("data")
    if not isinstance(data, list):
        raise DeribitSourceError("delivery price data must be an array")
    expiry_date = normalized_expiry.date().isoformat()
    matching_prices: list[Decimal] = []
    for raw in data:
        item = _mapping(raw, "delivery price row")
        date_text = _text(item.get("date"), "delivery price date")
        try:
            parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise DeribitSourceError("delivery price date must be YYYY-MM-DD") from exc
        if parsed_date.isoformat() != date_text:
            raise DeribitSourceError("delivery price date must be canonical YYYY-MM-DD")
        if date_text == expiry_date:
            matching_prices.append(_positive_decimal(item.get("delivery_price"), "delivery_price"))
    if not matching_prices:
        raise DeribitSourceError("delivery prices lack the exact UTC expiry date")
    if len(matching_prices) != 1:
        raise DeribitSourceError("delivery prices contain duplicate UTC expiry dates")
    effective_known_at_ms = int(normalized_known_at.timestamp() * 1000)
    if isinstance(response, PublicRpcResponse):
        effective_known_at_ms = max(effective_known_at_ms, response.local_received_at_ms)
    return ExpirySettlementFact(
        product_id=BTC.product_id,
        expiry=normalized_expiry,
        delivery_price_usd=matching_prices[0],
        known_at=datetime.fromtimestamp(effective_known_at_ms / 1000, tz=UTC),
        evidence_kind=SettlementEvidenceKind.OFFICIAL_EXCHANGE,
        source_id=DERIBIT_DELIVERY_PRICE_SOURCE_ID,
        method_id=DERIBIT_DELIVERY_PRICE_METHOD_ID,
    )


def evaluate_live_btc_snapshot(
    *,
    client: PublicRpcClient,
    policy: BtcShortVolPolicy,
    now: datetime,
    event_state: EventState,
    maximum_books: int = 32,
    depth: int = 20,
    target_window: DecisionWindow | None = None,
    required_instrument_names: Sequence[str] = (),
) -> PublicSnapshotEvaluation:
    """Evaluate one current-session public snapshot without opening a Case."""

    if maximum_books < 4 or maximum_books > 32:
        raise ValueError("maximum_books must be between four and 32")
    if depth not in {1, 5, 10, 20, 50, 100, 1000, 10000}:
        raise ValueError("depth is outside Deribit's supported values")
    required_names = _required_instrument_names(
        required_instrument_names,
        maximum_books=maximum_books,
    )
    normalized_now = _utc(now)
    session = current_deribit_session(normalized_now, phase_policy=policy.session)
    if target_window is not None:
        _validate_target_window(
            target_window,
            policy=policy,
            request_boundary=normalized_now,
        )
    index_response = client.call(
        "public/get_index_price",
        {"index_name": BTC.price_index},
    )
    index_result = _mapping(
        _rpc_result(index_response),
        "index price result",
    )
    index_price = _positive_decimal(index_result.get("index_price"), "index_price")
    instrument_response = client.call(
        "public/get_instruments",
        {"currency": BTC.public_currency, "kind": "option", "expired": False},
    )
    instruments = _instrument_metadata(
        _rpc_result(instrument_response),
        session_end_ms=int(session.end.timestamp() * 1000),
    )
    available_names = {str(item["instrument_name"]) for item in instruments}
    missing_required_names = tuple(name for name in required_names if name not in available_names)
    selected_metadata = _shortlist_instruments(
        instruments,
        index_price=index_price,
        maximum_books=maximum_books,
        required_instrument_names=required_names,
    )
    quotes, forwards, fetch_warnings = _fetch_books(
        client=client,
        metadata=selected_metadata,
        depth=depth,
    )
    warnings: list[str] = list(fetch_warnings)
    warnings.extend(
        f"REQUIRED_INSTRUMENT_METADATA_MISSING:{name}" for name in missing_required_names
    )
    if len(quotes) < 4:
        raise DeribitSourceError("fewer than four current-session option books were usable")
    history = fetch_btc_index_history(
        client,
        known_at=normalized_now,
    )
    horizon_minutes = max(
        5,
        session.minutes_to_expiry - policy.lifecycle.latest_exit_minutes_to_expiry,
    )
    history_cadence_ms = _history_cadence_ms(history, horizon_minutes=horizon_minutes)
    horizon_minutes = max(
        horizon_minutes,
        math.ceil(history_cadence_ms * 2 / 60_000),
    )
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
    if missing_required_names:
        evidence_blockers.append("REQUIRED_INSTRUMENT_METADATA_MISSING")
    if (
        current_deribit_session(known_at, phase_policy=policy.session).session_id
        != session.session_id
    ):
        evidence_blockers.append("SNAPSHOT_CROSSED_SESSION_BOUNDARY")
    if target_window is not None and not (
        target_window.starts_at <= known_at < target_window.ends_at
    ):
        evidence_blockers.append("SNAPSHOT_CROSSED_TARGET_WINDOW_BOUNDARY")
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
    if target_window is not None:
        decision_window = target_window
    else:
        windows = schedule_decision_windows(
            session=session,
            channel_id=policy.channel_id,
            policy=policy.window,
        )
        decision_window = next(
            window for window in windows if window.starts_at <= normalized_now < window.ends_at
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
        response = client.call(
            "public/get_order_book",
            {"instrument_name": item["instrument_name"], "depth": depth},
        )
        received_at_ms = (
            response.local_received_at_ms
            if isinstance(response, PublicRpcResponse)
            else int(time.time() * 1000)
        )
        return item, _rpc_result(response), received_at_ms

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
    required_instrument_names: tuple[str, ...] = (),
) -> tuple[dict[str, object], ...]:
    lower = index_price * Decimal("0.75")
    upper = index_price * Decimal("1.25")
    in_range = [
        item
        for item in instruments
        if lower <= _positive_decimal(item["strike"], "strike") <= upper
    ]
    per_side = maximum_books // 2
    ranked: list[dict[str, object]] = []
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
        ranked.extend(side[:per_side])
    by_name = {str(item["instrument_name"]): item for item in instruments}
    selected: list[dict[str, object]] = [
        by_name[name] for name in required_instrument_names if name in by_name
    ]
    selected_names = {str(item["instrument_name"]) for item in selected}
    for item in ranked:
        name = str(item["instrument_name"])
        if name not in selected_names and len(selected) < maximum_books:
            selected.append(item)
            selected_names.add(name)
    selected.sort(
        key=lambda item: (
            _positive_decimal(item["strike"], "strike"),
            item["option_type"],
        )
    )
    return tuple(selected)


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


def _validated_index_history_points(
    history: tuple[tuple[int, Decimal], ...],
) -> tuple[tuple[int, Decimal], ...]:
    points: list[tuple[int, Decimal]] = []
    for raw in history:
        if not isinstance(raw, tuple) or len(raw) != 2:
            raise DeribitSourceError("validated index history point is malformed")
        points.append(
            (
                _integer(raw[0], "history timestamp"),
                _positive_decimal(raw[1], "history price"),
            )
        )
    if any(current[0] <= previous[0] for previous, current in pairwise(points)):
        raise DeribitSourceError("validated index history is not strictly chronological")
    return tuple(points)


def _rolling_rv_acceleration(
    history: tuple[tuple[int, Decimal], ...],
    *,
    at_ms: int,
    expected_cadence_ms: int,
) -> Decimal | None:
    long_start_ms = at_ms - 120 * 60_000
    short_start_ms = at_ms - 30 * 60_000
    long_points = tuple(point for point in history if long_start_ms <= point[0] <= at_ms)
    if (
        len(long_points) < 3
        or long_points[0][0] > long_start_ms + expected_cadence_ms * 2
        or long_points[-1][0] != at_ms
        or any(
            current[0] - previous[0] > expected_cadence_ms * 2
            for previous, current in pairwise(long_points)
        )
    ):
        return None
    short_points = tuple(point for point in long_points if point[0] >= short_start_ms)
    if len(short_points) < 2:
        return None
    short_rate = _variance_rate(_log_returns(short_points))
    long_rate = _variance_rate(_log_returns(long_points))
    if long_rate <= 0:
        return Decimal(0)
    return _clamp((short_rate / long_rate - Decimal(1)) / Decimal(2))


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


def _validated_public_rpc_response(
    value: object,
    *,
    method: str,
    request_id: int,
    timeout_seconds: float,
    local_sent_at_ms: int,
    local_received_at_ms: int,
) -> PublicRpcResponse:
    root = _mapping(value, "JSON-RPC response")
    if root.get("jsonrpc") != "2.0":
        raise DeribitSourceError(f"Deribit response has invalid JSON-RPC version: {method}")
    if _integer(root.get("id"), "JSON-RPC id") != request_id:
        raise DeribitSourceError(f"Deribit response id mismatch: {method}")
    if root.get("testnet") is not False:
        raise DeribitSourceError(f"Deribit response is not from production: {method}")
    server_received_at_us = _integer(root.get("usIn"), "JSON-RPC usIn")
    server_sent_at_us = _integer(root.get("usOut"), "JSON-RPC usOut")
    server_processing_us = _integer(root.get("usDiff"), "JSON-RPC usDiff")
    if local_received_at_ms < local_sent_at_ms:
        raise DeribitSourceError("local receive boundary precedes request boundary")
    if server_received_at_us <= 0 or server_sent_at_us < server_received_at_us:
        raise DeribitSourceError(f"Deribit response timing order is invalid: {method}")
    if server_processing_us != server_sent_at_us - server_received_at_us:
        raise DeribitSourceError(f"Deribit response processing time is inconsistent: {method}")
    if server_processing_us > int(timeout_seconds * 1_000_000):
        raise DeribitSourceError(f"Deribit response processing time exceeds timeout: {method}")
    maximum_clock_distance_us = 24 * 60 * 60 * 1_000_000
    if (
        server_received_at_us < local_sent_at_ms * 1000 - maximum_clock_distance_us
        or server_sent_at_us > local_received_at_ms * 1000 + maximum_clock_distance_us
    ):
        raise DeribitSourceError(f"Deribit response timing fields are implausible: {method}")
    has_result = "result" in root
    error = root.get("error")
    if error is not None and has_result:
        raise DeribitSourceError(f"Deribit response contains both result and error: {method}")
    if error is not None:
        raise DeribitSourceError(f"Deribit returned an error for {method}")
    if not has_result:
        raise DeribitSourceError(f"Deribit response lacks result: {method}")
    return PublicRpcResponse(
        jsonrpc="2.0",
        request_id=request_id,
        result=root["result"],
        testnet=False,
        server_received_at_us=server_received_at_us,
        server_sent_at_us=server_sent_at_us,
        server_processing_us=server_processing_us,
        local_sent_at_ms=local_sent_at_ms,
        local_received_at_ms=local_received_at_ms,
    )


def _rpc_result(value: object) -> object:
    return value.result if isinstance(value, PublicRpcResponse) else value


def _required_instrument_names(
    value: Sequence[str],
    *,
    maximum_books: int,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError("required_instrument_names must be a sequence of instrument names")
    names = tuple(value)
    if len(names) > maximum_books:
        raise ValueError("required_instrument_names exceed the bounded book universe")
    if len(set(names)) != len(names) or any(
        not isinstance(name, str) or not name or name != name.strip() for name in names
    ):
        raise ValueError("required_instrument_names must be unique non-empty text")
    return names


def _validate_target_window(
    window: DecisionWindow,
    *,
    policy: BtcShortVolPolicy,
    request_boundary: datetime,
) -> None:
    target_session = current_deribit_session(window.starts_at, phase_policy=policy.session)
    expected_windows = schedule_decision_windows(
        session=target_session,
        channel_id=policy.channel_id,
        policy=policy.window,
    )
    if window.identity not in {item.identity for item in expected_windows}:
        raise ValueError("target_window does not belong to the current BTC Policy schedule")
    request_session = current_deribit_session(request_boundary, phase_policy=policy.session)
    if request_session.session_id != window.market_session_id:
        raise ValueError("target_window does not belong to the request Session")
    if not window.starts_at <= request_boundary < window.ends_at:
        raise ValueError("request boundary must be inside target_window")


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

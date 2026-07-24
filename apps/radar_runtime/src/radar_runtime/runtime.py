from __future__ import annotations

import asyncio
import signal
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from market_monitor import (
    BookState,
    ContinuityGap,
    ContinuousOrderBook,
    IndexMinuteReducer,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import (
    COMBO_LIFECYCLE_CHANNEL,
    HEARTBEAT_INTERVAL_SECONDS,
    INDEX_CHANNEL,
    LIVENESS_DEADLINE_SECONDS,
    OPTION_LIFECYCLE_CHANNEL,
    PLATFORM_CHANNELS,
    CatalogBootstrap,
    PlatformReadiness,
    book_channel,
    ticker_channel,
)
from market_monitor.types import (
    SourceDataError,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from options_domain import (
    Applicability,
    ComboInstrument,
    OptionInstrument,
    OptionType,
    monitor_applicability,
    parse_combo_instrument,
    parse_option_instrument,
)
from short_vol_radar.atomic import (
    PublicAtomicQuoteState,
    classify_atomic_quotes,
    match_vertical_combo,
)
from short_vol_radar.detector import (
    AggregateDetectorResult,
    DetectorCoverage,
    DetectorState,
    EpisodeEnd,
    EpisodeTracker,
    TrackerState,
    aggregate_detector,
)
from short_vol_radar.evidence import (
    AnomalyEvidence,
    AtomicEvidence,
    CoverageSegment,
    CoverageState,
    EvidenceWriter,
    decimal_text,
    project_anomaly_event,
    project_atomic_event,
    project_run_summary,
    ratio_or_none,
)
from short_vol_radar.policy import RadarPolicy, band_for_tte
from short_vol_radar.radar import (
    EvaluationResult,
    TickerState,
    evaluate_instrument,
    parse_ticker,
)
from websockets.exceptions import WebSocketException

from radar_runtime.deribit_public import DeribitPublicClient, PublicProtocolError


class PublicClient(Protocol):
    last_inbound_monotonic: float

    async def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object: ...

    async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None: ...

    async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> None: ...

    async def next_notification(
        self, timeout_seconds: float | None = None
    ) -> dict[str, object]: ...

    def drain_notifications(self) -> tuple[dict[str, object], ...]: ...


@dataclass
class ScopeCounts:
    policy_identity: str
    option_type: str
    tte_band_id: str
    applicable_instrument_count: int = 0
    known_per_instrument_detector_evaluation_count: int = 0
    known_full_detector_formula_evaluation_count: int = 0
    complete_aggregate_detector_evaluation_count: int = 0
    complete_aggregate_with_full_formula_evaluation_count: int = 0
    distinct_anomaly_episode_count: int = 0
    anomaly_activation_transition_count: int = 0
    anomaly_end_count_by_reason: Counter[str] = field(default_factory=Counter)
    known_active_duration_ms_sum_by_end_reason: Counter[str] = field(default_factory=Counter)
    public_atomic_quote_state_transition_count: Counter[str] = field(default_factory=Counter)

    def as_object(self) -> dict[str, object]:
        known_formula_rate = ratio_or_none(
            self.known_full_detector_formula_evaluation_count,
            self.known_per_instrument_detector_evaluation_count,
        )
        complete_formula_rate = ratio_or_none(
            self.complete_aggregate_with_full_formula_evaluation_count,
            self.complete_aggregate_detector_evaluation_count,
        )
        return {
            "policy_identity": self.policy_identity,
            "option_type": self.option_type,
            "tte_band_id": self.tte_band_id,
            "applicable_instrument_count": self.applicable_instrument_count,
            "known_per_instrument_detector_evaluation_count": (
                self.known_per_instrument_detector_evaluation_count
            ),
            "known_full_detector_formula_evaluation_count": (
                self.known_full_detector_formula_evaluation_count
            ),
            "complete_aggregate_detector_evaluation_count": (
                self.complete_aggregate_detector_evaluation_count
            ),
            "complete_aggregate_with_full_formula_evaluation_count": (
                self.complete_aggregate_with_full_formula_evaluation_count
            ),
            "known_full_formula_rate_given_known_per_instrument": (
                decimal_text(known_formula_rate) if known_formula_rate is not None else None
            ),
            "complete_aggregate_with_full_formula_rate_given_complete_aggregate": (
                decimal_text(complete_formula_rate) if complete_formula_rate is not None else None
            ),
            "distinct_anomaly_episode_count": self.distinct_anomaly_episode_count,
            "anomaly_activation_transition_count": self.anomaly_activation_transition_count,
            "anomaly_end_count_by_reason": dict(self.anomaly_end_count_by_reason),
            "known_active_duration_ms_sum_by_end_reason": dict(
                self.known_active_duration_ms_sum_by_end_reason
            ),
            "public_atomic_quote_state_transition_count": dict(
                self.public_atomic_quote_state_transition_count
            ),
        }


class CoverageLedger:
    def __init__(self, started_monotonic_ms: int) -> None:
        self._current_state = CoverageState.UNKNOWN
        self._current_start_ms = started_monotonic_ms
        self._segments: list[CoverageSegment] = []

    def transition(self, state: CoverageState, monotonic_ms: int) -> None:
        if monotonic_ms < self._current_start_ms:
            raise RuntimeError("coverage monotonic time moved backward")
        if state is self._current_state:
            return
        if monotonic_ms > self._current_start_ms:
            self._segments.append(
                CoverageSegment(self._current_start_ms, monotonic_ms, self._current_state)
            )
        self._current_start_ms = monotonic_ms
        self._current_state = state

    def close(self, stop_monotonic_ms: int) -> tuple[CoverageSegment, ...]:
        if stop_monotonic_ms <= self._current_start_ms:
            stop_monotonic_ms = self._current_start_ms + 1
        self._segments.append(
            CoverageSegment(self._current_start_ms, stop_monotonic_ms, self._current_state)
        )
        return tuple(self._segments)


class LiveRadarRuntime:
    def __init__(
        self,
        *,
        policy: RadarPolicy,
        code_identity: str,
        evidence_writer: EvidenceWriter,
        runtime_identity: str | None = None,
    ) -> None:
        self.policy = policy
        self.code_identity = code_identity
        self.runtime_identity = runtime_identity or str(uuid.uuid4())
        self.writer = evidence_writer
        self.platform = PlatformReadiness()
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options: dict[str, OptionInstrument] = {}
        self.options: dict[str, OptionInstrument] = {}
        self.combos: dict[str, ComboInstrument] = {}
        self.option_books: dict[str, ContinuousOrderBook] = {}
        self.combo_books: dict[str, ContinuousOrderBook] = {}
        self.tickers: dict[str, TickerState] = {}
        self.trackers: dict[str, EpisodeTracker] = {}
        self.results: dict[str, EvaluationResult] = {}
        self.atomic_states: dict[str, PublicAtomicQuoteState] = {}
        self._subscribed_combo_names: set[str] = set()
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock: TrustedClock | None = None
        self.causal_seq = 0
        self._last_fingerprints: dict[str, tuple[object, ...]] = {}
        self._last_unknown_reason: dict[str, str | None] = {}
        self._scope_counts: dict[tuple[str, OptionType, str], ScopeCounts] = {}
        self._unknown_counts: Counter[str] = Counter()
        self._episode_end_counts: Counter[str] = Counter()
        self._known_active_duration_ms: Counter[str] = Counter()
        self._atomic_transition_counts: Counter[str] = Counter()
        self._episode_active_segment_started_ms: dict[str, int] = {}
        self._episode_active_accumulated_ms: Counter[str] = Counter()
        self._episode_option_types: dict[str, OptionType] = {}
        self._band_suspended_started_ms: dict[str, int] = {}
        self._band_suspended_duration_ms = 0
        started = _monotonic_ms()
        self._coverage = CoverageLedger(started)

    async def run(self, client: PublicClient, stop_event: asyncio.Event) -> Path:
        await self._bootstrap(client)
        next_clock_refresh_ms = _monotonic_ms() + 30_000
        next_membership_refresh_ms = _monotonic_ms() + 1_000
        while not stop_event.is_set():
            now_ms = _monotonic_ms()
            if now_ms >= next_clock_refresh_ms:
                await self._refresh_clock(client)
                next_clock_refresh_ms = now_ms + 30_000
            if now_ms >= next_membership_refresh_ms:
                if await self._sync_option_membership(client):
                    await self._refresh_combo_catalog(client)
                next_membership_refresh_ms = now_ms + 1_000
            if time.monotonic() - client.last_inbound_monotonic >= LIVENESS_DEADLINE_SECONDS:
                self._invalidate_all("SESSION_LIVENESS_DEADLINE")
                raise PublicProtocolError("production-public session liveness deadline expired")
            try:
                message = await client.next_notification(timeout_seconds=1.0)
            except TimeoutError:
                continue
            await self._handle_message(client, message)
        return await self._clean_stop(client)

    async def _bootstrap(self, client: PublicClient) -> None:
        self._reset_session_state()
        heartbeat = await client.request(
            "public/set_heartbeat", {"interval": HEARTBEAT_INTERVAL_SECONDS}
        )
        if heartbeat != "ok":
            raise PublicProtocolError("heartbeat acknowledgement was not ok")
        await client.subscribe(list(PLATFORM_CHANNELS))
        self.platform.acknowledge(PLATFORM_CHANNELS)
        await client.subscribe([OPTION_LIFECYCLE_CHANNEL, COMBO_LIFECYCLE_CHANNEL])
        self.option_catalog.acknowledge_lifecycle()
        self.combo_catalog.acknowledge_lifecycle()
        status = await client.request("public/status", {})
        self.platform.apply_status(status)
        self.platform.public_methods_allowed = True
        await self._bootstrap_clock(client)
        option_payloads = require_list(
            await client.request(
                "public/get_instruments",
                {"currency": "USDC", "kind": "option", "expired": False},
            ),
            "public/get_instruments result",
        )
        option_snapshot_complete = self._replace_options(option_payloads)
        combo_payloads = require_list(
            await client.request("public/get_combos", {"currency": "USDC"}),
            "public/get_combos result",
        )
        combo_snapshot_complete = await self._replace_combos(client, combo_payloads)
        for message in client.drain_notifications():
            await self._handle_bootstrap_message(client, message)
        for event in self.option_catalog.reconcile():
            await self._apply_option_lifecycle(client, event)
        self.option_catalog.complete = self.option_catalog.complete and option_snapshot_complete
        for _event in self.combo_catalog.reconcile():
            await self._refresh_combo_catalog(client)
        self.combo_catalog.complete = self.combo_catalog.complete and combo_snapshot_complete
        await self._sync_option_membership(client)
        await client.subscribe([INDEX_CHANNEL])
        if self.clock is None:
            raise RuntimeError("clock was not established")
        self.index.start_continuous_coverage(self.clock.interval_at(_monotonic_ms()).lower_ms)
        try:
            self.platform.prove_operational_from_post_status_public_success()
        except RuntimeError as exc:
            raise PublicProtocolError("platform state was unusable after public bootstrap") from exc
        self._update_coverage()

    def _reset_session_state(self) -> None:
        self.platform = PlatformReadiness()
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options.clear()
        self.options.clear()
        self.combos.clear()
        self.option_books.clear()
        self.combo_books.clear()
        self.tickers.clear()
        self.results.clear()
        self._subscribed_combo_names.clear()
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock = None
        self._last_fingerprints.clear()

    def prepare_reconnect(self, reason: str) -> None:
        self._invalidate_all(reason)

    async def _bootstrap_clock(self, client: PublicClient) -> None:
        sent = _monotonic_ms()
        result = await client.request("public/get_time", {})
        received = _monotonic_ms()
        server_ms = require_int(result, "public/get_time result")
        self.clock = TrustedClock.from_response(server_ms, sent, received)

    async def _refresh_clock(self, client: PublicClient) -> None:
        if self.clock is None:
            await self._bootstrap_clock(client)
            return
        sent = _monotonic_ms()
        result = await client.request("public/get_time", {})
        received = _monotonic_ms()
        try:
            self.clock = self.clock.refresh(
                require_int(result, "public/get_time result"),
                sent,
                received,
            )
        except ContinuityGap:
            self._invalidate_all("CLOCK_GAP")
            raise
        if await self._sync_option_membership(client):
            await self._refresh_combo_catalog(client)
        await self._evaluate_all(client)

    def _replace_options(self, payloads: list[object]) -> bool:
        if self.clock is None:
            raise RuntimeError("clock required before catalog filtering")
        options: dict[str, OptionInstrument] = {}
        complete = True
        for payload in payloads:
            try:
                instrument = parse_option_instrument(payload)
            except SourceDataError:
                complete = False
                continue
            if instrument is None:
                continue
            options[instrument.instrument_name] = instrument
        self.catalog_options = options
        trusted_time = self.clock.interval_at(_monotonic_ms())
        self.options = {
            name: instrument
            for name, instrument in options.items()
            if monitor_applicability(instrument.expiration_timestamp_ms, trusted_time)
            is not Applicability.OUT_OF_MONITOR_SCOPE
        }
        for instrument_name in set(self.trackers) - set(self.options):
            self.trackers.pop(instrument_name, None)
            self._last_unknown_reason.pop(instrument_name, None)
        for instrument_name in self.options:
            self.trackers.setdefault(
                instrument_name,
                EpisodeTracker(
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    instrument_name=instrument_name,
                ),
            )
        return complete

    async def _sync_option_membership(self, client: PublicClient) -> bool:
        if self.clock is None:
            raise RuntimeError("clock required before membership synchronization")
        trusted_time = self.clock.interval_at(_monotonic_ms())
        desired = {
            name: instrument
            for name, instrument in self.catalog_options.items()
            if monitor_applicability(instrument.expiration_timestamp_ms, trusted_time)
            is not Applicability.OUT_OF_MONITOR_SCOPE
        }
        current_names = set(self.options)
        desired_names = set(desired)
        removals = sorted(current_names - desired_names)
        additions = sorted(name for name in desired_names if name not in self.option_books)
        for instrument_name in removals:
            tracker = self.trackers[instrument_name]
            transition = tracker.membership_loss(causal_seq=self.causal_seq)
            self._record_episode_end(transition.ended_episode)
            self.option_books.pop(instrument_name, None)
            self.tickers.pop(instrument_name, None)
            self.results.pop(instrument_name, None)
            self._last_fingerprints.pop(instrument_name, None)
            self._last_unknown_reason.pop(instrument_name, None)
            self.trackers.pop(instrument_name, None)
        self.options = desired
        for instrument_name in additions:
            self.trackers.setdefault(
                instrument_name,
                EpisodeTracker(
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    instrument_name=instrument_name,
                ),
            )
            self.option_books[instrument_name] = ContinuousOrderBook(instrument_name)
        if removals:
            await client.unsubscribe(
                [
                    channel
                    for name in removals
                    for channel in (ticker_channel(name), book_channel(name))
                ]
            )
        if additions:
            await client.subscribe(
                [
                    channel
                    for name in additions
                    for channel in (ticker_channel(name), book_channel(name))
                ]
            )
        if removals:
            await self._sync_combo_subscriptions(client)
        return bool(additions or removals)

    async def _replace_combos(self, client: PublicClient, payloads: list[object]) -> bool:
        combos: dict[str, ComboInstrument] = {}
        complete = True
        for payload in payloads:
            try:
                summary = require_mapping(payload, "combo")
                raw_legs = require_list(summary.get("legs"), "combo.legs")
                leg_names = {
                    require_str(
                        require_mapping(item, "combo leg").get("instrument_name"),
                        "combo leg.instrument_name",
                    )
                    for item in raw_legs
                }
            except SourceDataError:
                complete = False
                continue
            if len(raw_legs) != 2 or len(leg_names) != 2 or not leg_names <= set(self.options):
                continue
            try:
                combo_id = require_str(summary.get("id"), "combo.id")
            except SourceDataError:
                complete = False
                continue
            metadata = await client.request("public/get_instrument", {"instrument_name": combo_id})
            try:
                combo = parse_combo_instrument(summary, metadata)
            except SourceDataError:
                complete = False
                continue
            if combo is not None:
                combos[combo.instrument_name] = combo
        self.combos = combos
        return complete

    async def _handle_bootstrap_message(
        self, client: PublicClient, message: dict[str, object]
    ) -> None:
        method = message.get("method")
        if method == "heartbeat":
            await self._handle_heartbeat(client, message)
            return
        if method != "subscription":
            if method == "connection_error":
                raise PublicProtocolError("connection failed during bootstrap")
            return
        params = require_mapping(message.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        data = params.get("data")
        if channel == OPTION_LIFECYCLE_CHANNEL:
            try:
                self.option_catalog.accept_lifecycle(data)
            except SourceDataError:
                self.option_catalog.mark_incomplete()
        elif channel == COMBO_LIFECYCLE_CHANNEL:
            try:
                self.combo_catalog.accept_lifecycle(data)
            except SourceDataError:
                self.combo_catalog.mark_incomplete()
        elif channel == "platform_state":
            self.platform.apply_platform_notification(data)
        elif channel == "platform_state.public_methods_state":
            self.platform.apply_public_methods_notification(data)

    async def _handle_message(self, client: PublicClient, message: dict[str, object]) -> None:
        method = message.get("method")
        if method == "heartbeat":
            await self._handle_heartbeat(client, message)
            return
        if method == "connection_error":
            self._invalidate_all("CONNECTION_CLOSED")
            raise PublicProtocolError("production-public connection closed")
        if method != "subscription":
            raise PublicProtocolError("unexpected non-subscription notification")
        params = require_mapping(message.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        data = params.get("data")
        self.causal_seq += 1
        if channel == INDEX_CHANNEL:
            await self._handle_index(client, data)
        elif channel.startswith("ticker.") and channel.endswith(".100ms"):
            instrument_name = channel[len("ticker.") : -len(".100ms")]
            try:
                ticker = parse_ticker(data, instrument_name)
            except ValueError:
                self.tickers.pop(instrument_name, None)
                self._last_fingerprints.pop(instrument_name, None)
                tracker = self.trackers.get(instrument_name)
                if tracker is not None:
                    transition = tracker.unknown(
                        reason="FORWARD_TICKER_INVALID",
                        causal_seq=self.causal_seq,
                    )
                    self._record_episode_end(transition.ended_episode)
                self._update_coverage()
                return
            previous_ticker = self.tickers.get(instrument_name)
            if (
                previous_ticker is not None
                and ticker.source_timestamp_ms < previous_ticker.source_timestamp_ms
            ):
                self.tickers.pop(instrument_name, None)
                self._last_fingerprints.pop(instrument_name, None)
                tracker = self.trackers.get(instrument_name)
                if tracker is not None:
                    transition = tracker.unknown(
                        reason="FORWARD_TICKER_TIMESTAMP_GAP",
                        causal_seq=self.causal_seq,
                        continuity_gap=True,
                    )
                    self._record_episode_end(transition.ended_episode)
                await client.unsubscribe([ticker_channel(instrument_name)])
                await client.subscribe([ticker_channel(instrument_name)])
                self._update_coverage()
                return
            self.tickers[instrument_name] = ticker
            await self._evaluate_one(client, instrument_name)
        elif channel.startswith("book.") and channel.endswith(".100ms"):
            instrument_name = channel[len("book.") : -len(".100ms")]
            await self._handle_book(client, instrument_name, data)
        elif channel == OPTION_LIFECYCLE_CHANNEL:
            try:
                await self._apply_option_lifecycle(client, data)
            except SourceDataError:
                self.option_catalog.mark_incomplete()
        elif channel == COMBO_LIFECYCLE_CHANNEL:
            await self._refresh_combo_catalog(client)
        elif channel == "platform_state":
            self.platform.apply_platform_notification(data)
            if self.platform.maintenance is True:
                self._invalidate_all(self.platform.reason)
                raise PublicProtocolError("platform state requires full bootstrap")
        elif channel == "platform_state.public_methods_state":
            self.platform.apply_public_methods_notification(data)
            if self.platform.public_methods_allowed is False:
                self._invalidate_all(self.platform.reason)
                raise PublicProtocolError("public-method state requires full bootstrap")
        else:
            raise PublicProtocolError(f"unexpected subscription channel: {channel}")
        await self._maybe_complete_post_status_bootstrap(client)
        self._update_coverage()

    async def _maybe_complete_post_status_bootstrap(self, client: PublicClient) -> None:
        if self.platform.post_status_bootstrap_complete:
            return
        if (
            not self.platform.status_usable
            or self.platform.maintenance is not False
            or self.platform.public_methods_allowed is not True
            or not self.index.has_accepted_tick
        ):
            return
        for instrument_name in self.options:
            book = self.option_books.get(instrument_name)
            if (
                book is None
                or book.state is not BookState.USABLE
                or instrument_name not in self.tickers
            ):
                return
        self.platform.complete_post_status_bootstrap()
        self._last_fingerprints.clear()
        await self._evaluate_all(client)

    async def _handle_heartbeat(self, client: PublicClient, message: dict[str, object]) -> None:
        params = require_mapping(message.get("params"), "heartbeat.params")
        heartbeat_type = require_str(params.get("type"), "heartbeat.params.type")
        if heartbeat_type == "test_request":
            result = await client.request("public/test", {}, responding_to_test_request=True)
            if result != "ok":
                raise PublicProtocolError("public/test acknowledgement was not ok")
        elif heartbeat_type != "heartbeat":
            raise PublicProtocolError("unknown heartbeat type")

    async def _handle_index(self, client: PublicClient, payload: object) -> None:
        if self.clock is None:
            raise RuntimeError("index tick arrived before clock")
        try:
            data = require_mapping(payload, "index notification")
            if require_str(data.get("index_name"), "index.index_name") != "btc_usdc":
                raise SourceDataError("unexpected index_name")
            self.index.accept_tick(
                source_timestamp_ms=require_int(data.get("timestamp"), "index.timestamp"),
                price=data.get("price"),
                causal_seq=self.causal_seq,
            )
        except (ContinuityGap, SourceDataError, ValueError):
            self.index.gap()
            self._last_fingerprints.clear()
            for tracker in self.trackers.values():
                transition = tracker.unknown(
                    reason="INDEX_GAP",
                    causal_seq=self.causal_seq,
                    continuity_gap=True,
                )
                self._record_episode_end(transition.ended_episode)
            await client.unsubscribe([INDEX_CHANNEL])
            await client.subscribe([INDEX_CHANNEL])
            if self.clock is not None:
                self.index.start_continuous_coverage(
                    self.clock.interval_at(_monotonic_ms()).lower_ms
                )
            return
        sealed = self.index.seal_ready(self.clock.interval_at(_monotonic_ms()).lower_ms)
        if sealed:
            await self._evaluate_all(client)

    async def _handle_book(
        self, client: PublicClient, instrument_name: str, payload: object
    ) -> None:
        book = self.option_books.get(instrument_name)
        if book is not None:
            try:
                changed = book.apply(payload, _monotonic_ms())
            except (ContinuityGap, SourceDataError) as exc:
                book.invalidate(type(exc).__name__)
                transition = self.trackers[instrument_name].unknown(
                    reason="OPTION_BOOK_GAP",
                    causal_seq=self.causal_seq,
                    continuity_gap=True,
                )
                self._record_episode_end(transition.ended_episode)
                self._last_fingerprints.pop(instrument_name, None)
                await client.unsubscribe([book_channel(instrument_name)])
                self.option_books[instrument_name] = ContinuousOrderBook(instrument_name)
                await client.subscribe([book_channel(instrument_name)])
                return
            if changed:
                await self._evaluate_one(client, instrument_name)
            return
        combo_book = self.combo_books.get(instrument_name)
        if combo_book is None:
            raise PublicProtocolError("book notification has no owned instrument")
        try:
            changed = combo_book.apply(payload, _monotonic_ms())
        except (ContinuityGap, SourceDataError) as exc:
            combo_book.invalidate(type(exc).__name__)
            await client.unsubscribe([book_channel(instrument_name)])
            self.combo_books[instrument_name] = ContinuousOrderBook(instrument_name)
            await client.subscribe([book_channel(instrument_name)])
            changed = True
        if changed:
            await self._evaluate_atomic_for_combo(instrument_name)

    async def _apply_option_lifecycle(self, client: PublicClient, payload: object) -> None:
        data = require_mapping(payload, "option lifecycle")
        instrument_name = require_str(
            data.get("instrument_name"), "option lifecycle.instrument_name"
        )
        state = require_str(data.get("state"), "option lifecycle.state")
        if state == "open":
            metadata = await client.request(
                "public/get_instrument", {"instrument_name": instrument_name}
            )
            try:
                instrument = parse_option_instrument(metadata)
            except SourceDataError:
                self.option_catalog.mark_incomplete()
                return
            if instrument is None or self.clock is None:
                return
            self.catalog_options[instrument_name] = instrument
        else:
            self.catalog_options.pop(instrument_name, None)
        if await self._sync_option_membership(client):
            await self._refresh_combo_catalog(client)

    async def _refresh_combo_catalog(self, client: PublicClient) -> None:
        payloads = require_list(
            await client.request("public/get_combos", {"currency": "USDC"}),
            "public/get_combos result",
        )
        self.combo_catalog.complete = await self._replace_combos(client, payloads)
        await self._sync_combo_subscriptions(client)
        for tracker in self.trackers.values():
            if tracker.episode_id is not None:
                await self._evaluate_atomic(tracker)

    async def _evaluate_all(self, client: PublicClient) -> None:
        for instrument_name in tuple(self.options):
            await self._evaluate_one(client, instrument_name)

    async def _evaluate_one(self, client: PublicClient, instrument_name: str) -> None:
        instrument = self.options.get(instrument_name)
        if instrument is None or self.clock is None:
            return
        trusted_time = self.clock.interval_at(_monotonic_ms())
        fingerprint = self._fingerprint(instrument, trusted_time)
        if self._last_fingerprints.get(instrument_name) == fingerprint:
            return
        self._last_fingerprints[instrument_name] = fingerprint
        tracker = self.trackers[instrument_name]
        if not self.platform.usable:
            transition = tracker.unknown(
                reason=self.platform.reason,
                causal_seq=self.causal_seq,
                continuity_gap=True,
            )
            self._record_episode_end(transition.ended_episode)
            return
        closes = self.index.consecutive_prices(self.policy.largest_lookback_minutes)
        previous_state = tracker.state
        previous_episode_id = tracker.episode_id
        result = evaluate_instrument(
            policy=self.policy,
            tracker=tracker,
            instrument=instrument,
            trusted_time=trusted_time,
            causal_seq=self.causal_seq,
            option_book=self.option_books.get(instrument_name),
            ticker=self.tickers.get(instrument_name),
            causal_closes=closes,
        )
        self.results[instrument_name] = result
        self._record_evaluation(instrument, result)
        self._record_band_timing(
            previous_state=previous_state,
            previous_episode_id=previous_episode_id,
            tracker=tracker,
        )
        self._record_episode_end(result.transition.ended_episode)
        aggregate = self._scope_aggregate(instrument, trusted_time)
        if result.transition.activated_episode_id is not None:
            self._record_activation(
                instrument,
                result,
                aggregate.coverage or DetectorCoverage.DEGRADED,
                trusted_time,
            )
        self._record_aggregate(instrument, result, aggregate)
        if tracker.state is TrackerState.BAND_SUSPENDED:
            self._record_atomic_transition(
                tracker,
                PublicAtomicQuoteState.NOT_EVALUATED,
                band_id=result.band_id or tracker.activation_band_id,
            )
        await self._sync_combo_subscriptions(client)
        if tracker.detector_state is DetectorState.ANOMALY_ACTIVE:
            await self._evaluate_atomic(tracker)

    def _fingerprint(
        self, instrument: OptionInstrument, trusted_time: TimeInterval
    ) -> tuple[object, ...]:
        book = self.option_books.get(instrument.instrument_name)
        ticker = self.tickers.get(instrument.instrument_name)
        lower_tte = instrument.expiration_timestamp_ms - trusted_time.upper_ms
        upper_tte = instrument.expiration_timestamp_ms - trusted_time.lower_ms
        band = band_for_tte(
            self.policy,
            lower_tte_ms=lower_tte,
            upper_tte_ms=upper_tte,
            option_type=instrument.option_type,
        )
        last_close = self.index.sealed[-1].causal_seq if self.index.sealed else None
        return (
            self.platform.usable,
            book.economic_revision if book is not None else None,
            (
                ticker.forward_usdc,
                ticker.underlying_index,
            )
            if ticker is not None
            else None,
            last_close,
            band.band_id if band is not None else "BOUNDARY_OR_GAP",
        )

    def _scope_aggregate(
        self, instrument: OptionInstrument, trusted_time: TimeInterval
    ) -> AggregateDetectorResult:
        lower_tte = instrument.expiration_timestamp_ms - trusted_time.upper_ms
        upper_tte = instrument.expiration_timestamp_ms - trusted_time.lower_ms
        band = band_for_tte(
            self.policy,
            lower_tte_ms=lower_tte,
            upper_tte_ms=upper_tte,
            option_type=instrument.option_type,
        )
        if band is None:
            return aggregate_detector(
                (),
                catalog_complete=self.option_catalog.complete,
                has_applicable_scope=False,
            )
        scope_instruments = tuple(
            item
            for item in self.options.values()
            if item.expiration_timestamp_ms == instrument.expiration_timestamp_ms
            and item.option_type is instrument.option_type
        )
        states = tuple(
            self.trackers[item.instrument_name].detector_state for item in scope_instruments
        )
        scope = self._scope_counter(instrument.option_type, band.band_id)
        scope.applicable_instrument_count = max(
            scope.applicable_instrument_count,
            len(scope_instruments),
        )
        return aggregate_detector(
            states,
            catalog_complete=self.option_catalog.complete,
            has_applicable_scope=bool(scope_instruments),
        )

    def _record_evaluation(self, instrument: OptionInstrument, result: EvaluationResult) -> None:
        if result.reason != self._last_unknown_reason.get(instrument.instrument_name):
            if result.reason is not None and not result.known_evaluation:
                self._unknown_counts[result.reason] += 1
            self._last_unknown_reason[instrument.instrument_name] = result.reason
        if result.band_id is None:
            return
        scope = self._scope_counter(instrument.option_type, result.band_id)
        scope.applicable_instrument_count = max(scope.applicable_instrument_count, 1)
        if result.known_evaluation:
            scope.known_per_instrument_detector_evaluation_count += 1
        if result.full_formula_evaluation:
            scope.known_full_detector_formula_evaluation_count += 1

    def _record_aggregate(
        self,
        instrument: OptionInstrument,
        result: EvaluationResult,
        aggregate: AggregateDetectorResult,
    ) -> None:
        if result.band_id is None or aggregate.coverage is not DetectorCoverage.COMPLETE:
            return
        scope = self._scope_counter(instrument.option_type, result.band_id)
        scope.complete_aggregate_detector_evaluation_count += 1
        if result.full_formula_evaluation:
            scope.complete_aggregate_with_full_formula_evaluation_count += 1

    def _record_activation(
        self,
        instrument: OptionInstrument,
        result: EvaluationResult,
        coverage: DetectorCoverage,
        trusted_time: TimeInterval,
    ) -> None:
        episode_id = result.transition.activated_episode_id
        calculation = result.calculation
        if episode_id is None or calculation is None:
            raise RuntimeError("activation requires a full detector calculation")
        scope = self._scope_counter(instrument.option_type, calculation.band.band_id)
        scope.distinct_anomaly_episode_count += 1
        scope.anomaly_activation_transition_count += 1
        self._episode_active_segment_started_ms[episode_id] = _monotonic_ms()
        self._episode_active_accumulated_ms[episode_id] = 0
        self._episode_option_types[episode_id] = instrument.option_type
        event = project_anomaly_event(
            AnomalyEvidence(
                code_identity=self.code_identity,
                runtime_identity=self.runtime_identity,
                policy_identity=self.policy.identity,
                episode_identity=episode_id,
                causal_seq=self.causal_seq,
                instrument_name=instrument.instrument_name,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                option_type=instrument.option_type.value,
                activation_band_id=calculation.band.band_id,
                aggregate_coverage=coverage,
                target_base_quantity_btc=self.policy.target_base_quantity_btc,
                rule=calculation.rule,
                baseline=calculation.baseline,
                trusted_time=trusted_time,
                remaining_life_years=calculation.remaining_life_years,
                consumed_bid_levels=calculation.target_bid.consumed,
                forward_usdc=calculation.forward_usdc,
                strike_usdc=instrument.strike,
                executable_sell_price_usdc=calculation.executable_sell_price_usdc,
                total_volatility=calculation.total_volatility,
                executable_bid_iv=calculation.executable_bid_iv,
                delta=calculation.delta,
                implied_total_variance=calculation.implied_total_variance,
                richness=calculation.richness,
            )
        )
        self.writer.write_anomaly(event)

    async def _sync_combo_subscriptions(self, client: PublicClient) -> None:
        needed: set[str] = set()
        for instrument_name, tracker in self.trackers.items():
            if tracker.detector_state is not DetectorState.ANOMALY_ACTIVE:
                continue
            short_leg = self.options[instrument_name]
            for combo in self.combos.values():
                if (
                    match_vertical_combo(
                        short_leg=short_leg,
                        options_by_name=self.options,
                        combo=combo,
                        target_btc=self.policy.target_base_quantity_btc,
                    )
                    is not None
                ):
                    needed.add(combo.instrument_name)
        additions = sorted(needed - self._subscribed_combo_names)
        removals = sorted(self._subscribed_combo_names - needed)
        if additions:
            for instrument_name in additions:
                self.combo_books[instrument_name] = ContinuousOrderBook(instrument_name)
            await client.subscribe([book_channel(name) for name in additions])
        if removals:
            await client.unsubscribe([book_channel(name) for name in removals])
            for instrument_name in removals:
                self.combo_books.pop(instrument_name, None)
        self._subscribed_combo_names = needed

    async def _evaluate_atomic_for_combo(self, combo_name: str) -> None:
        combo = self.combos.get(combo_name)
        if combo is None:
            return
        leg_names = {leg.instrument_name for leg in combo.legs}
        for instrument_name in leg_names:
            tracker = self.trackers.get(instrument_name)
            if tracker is not None and tracker.detector_state is DetectorState.ANOMALY_ACTIVE:
                await self._evaluate_atomic(tracker)

    async def _evaluate_atomic(self, tracker: EpisodeTracker) -> None:
        if tracker.episode_id is None or tracker.detector_state is not DetectorState.ANOMALY_ACTIVE:
            return
        short_leg = self.options[tracker.instrument_name]
        result = classify_atomic_quotes(
            anomaly_active=True,
            combo_catalog_complete=self.combo_catalog.complete,
            short_leg=short_leg,
            options_by_name=self.options,
            combos=tuple(self.combos.values()),
            combo_books=self.combo_books,
            target_btc=self.policy.target_base_quantity_btc,
        )
        current_result = self.results.get(tracker.instrument_name)
        self._record_atomic_transition(
            tracker,
            result.state,
            band_id=(
                current_result.band_id if current_result is not None else tracker.activation_band_id
            ),
        )
        if result.state is PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE:
            for quote in result.quotes:
                combo = self.combos[quote.match.combo_instrument_name]
                combo_book = self.combo_books[combo.instrument_name]
                event = project_atomic_event(
                    AtomicEvidence(
                        code_identity=self.code_identity,
                        runtime_identity=self.runtime_identity,
                        policy_identity=self.policy.identity,
                        episode_identity=tracker.episode_id,
                        detector_causal_seq=tracker.activation_causal_seq or self.causal_seq,
                        quote_causal_seq=self.causal_seq,
                        short_instrument_name=tracker.instrument_name,
                        combo_legs=(
                            (combo.legs[0].instrument_name, combo.legs[0].amount),
                            (combo.legs[1].instrument_name, combo.legs[1].amount),
                        ),
                        quote=quote,
                        target_base_quantity_btc=self.policy.target_base_quantity_btc,
                        source_timestamp_ms=combo_book.source_timestamp_ms or 0,
                    )
                )
                self.writer.write_atomic(event)

    def _record_episode_end(self, ended: EpisodeEnd | None) -> None:
        if ended is None:
            return
        now = _monotonic_ms()
        self._episode_end_counts[ended.reason.value] += 1
        suspended_started = self._band_suspended_started_ms.pop(ended.episode_id, None)
        if suspended_started is not None:
            self._band_suspended_duration_ms += max(0, now - suspended_started)
        active_started = self._episode_active_segment_started_ms.pop(ended.episode_id, None)
        if active_started is not None:
            self._episode_active_accumulated_ms[ended.episode_id] += max(0, now - active_started)
        active_duration = self._episode_active_accumulated_ms.pop(ended.episode_id, 0)
        self._known_active_duration_ms[ended.reason.value] += active_duration
        option_type = self._episode_option_types.pop(ended.episode_id, None)
        if option_type is not None:
            scope = self._scope_counter(option_type, ended.activation_band_id)
            scope.anomaly_end_count_by_reason[ended.reason.value] += 1
            scope.known_active_duration_ms_sum_by_end_reason[ended.reason.value] += active_duration
        previous_atomic = self.atomic_states.pop(ended.episode_id, None)
        if (
            previous_atomic is not None
            and previous_atomic is not PublicAtomicQuoteState.NOT_EVALUATED
        ):
            self._atomic_transition_counts[PublicAtomicQuoteState.NOT_EVALUATED.value] += 1
            if option_type is not None:
                scope = self._scope_counter(option_type, ended.activation_band_id)
                scope.public_atomic_quote_state_transition_count[
                    PublicAtomicQuoteState.NOT_EVALUATED.value
                ] += 1

    def _record_atomic_transition(
        self,
        tracker: EpisodeTracker,
        state: PublicAtomicQuoteState,
        *,
        band_id: str | None,
    ) -> None:
        if tracker.episode_id is None:
            return
        previous = self.atomic_states.get(tracker.episode_id)
        if previous is state:
            return
        self.atomic_states[tracker.episode_id] = state
        self._atomic_transition_counts[state.value] += 1
        instrument = self.options.get(tracker.instrument_name)
        if instrument is not None and band_id is not None:
            scope = self._scope_counter(instrument.option_type, band_id)
            scope.public_atomic_quote_state_transition_count[state.value] += 1

    def _record_band_timing(
        self,
        *,
        previous_state: object,
        previous_episode_id: str | None,
        tracker: EpisodeTracker,
    ) -> None:
        if previous_episode_id is None:
            return
        now = _monotonic_ms()
        if previous_state in {TrackerState.ACTIVE, TrackerState.CLEARING}:
            if tracker.state is TrackerState.BAND_SUSPENDED:
                active_started = self._episode_active_segment_started_ms.pop(
                    previous_episode_id, None
                )
                if active_started is not None:
                    self._episode_active_accumulated_ms[previous_episode_id] += max(
                        0, now - active_started
                    )
                self._band_suspended_started_ms[previous_episode_id] = now
        elif (
            previous_state is TrackerState.BAND_SUSPENDED
            and tracker.state is not TrackerState.BAND_SUSPENDED
        ):
            suspended_started = self._band_suspended_started_ms.pop(previous_episode_id, None)
            if suspended_started is not None:
                self._band_suspended_duration_ms += max(0, now - suspended_started)
            if tracker.episode_id == previous_episode_id and tracker.state in {
                TrackerState.ACTIVE,
                TrackerState.CLEARING,
            }:
                self._episode_active_segment_started_ms[previous_episode_id] = now

    def _scope_counter(self, option_type: OptionType, band_id: str) -> ScopeCounts:
        key = (self.policy.identity, option_type, band_id)
        if key not in self._scope_counts:
            self._scope_counts[key] = ScopeCounts(self.policy.identity, option_type.value, band_id)
        return self._scope_counts[key]

    def _invalidate_all(self, reason: str) -> None:
        self.platform.post_status_bootstrap_complete = False
        self.platform.reason = reason
        self.index.gap()
        for book in (*self.option_books.values(), *self.combo_books.values()):
            book.invalidate(reason)
        for tracker in self.trackers.values():
            transition = tracker.unknown(
                reason=reason,
                causal_seq=self.causal_seq,
                continuity_gap=True,
            )
            self._record_episode_end(transition.ended_episode)
        self._last_fingerprints.clear()
        self._update_coverage()

    def _update_coverage(self) -> None:
        now = _monotonic_ms()
        if self.clock is None or not self.platform.usable:
            self._coverage.transition(CoverageState.UNKNOWN, now)
            return
        try:
            trusted = self.clock.interval_at(now)
        except ContinuityGap:
            self._coverage.transition(CoverageState.UNKNOWN, now)
            return
        if not self.option_catalog.complete:
            state = (
                CoverageState.KNOWN_DEGRADED
                if any(
                    tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                    for name, tracker in self.trackers.items()
                    if name in self.options
                )
                else CoverageState.UNKNOWN
            )
            self._coverage.transition(state, now)
            return
        scoped: list[tuple[OptionInstrument, object]] = []
        for instrument in self.options.values():
            lower_tte = instrument.expiration_timestamp_ms - trusted.upper_ms
            upper_tte = instrument.expiration_timestamp_ms - trusted.lower_ms
            band = band_for_tte(
                self.policy,
                lower_tte_ms=lower_tte,
                upper_tte_ms=upper_tte,
                option_type=instrument.option_type,
            )
            if band is not None:
                scoped.append((instrument, band))
        if not scoped:
            self._coverage.transition(CoverageState.NO_APPLICABLE_SCOPE, now)
            return
        states = [self.trackers[item.instrument_name].detector_state for item, _ in scoped]
        if all(state is not DetectorState.UNKNOWN for state in states):
            self._coverage.transition(CoverageState.KNOWN_COMPLETE, now)
        elif DetectorState.ANOMALY_ACTIVE in states:
            self._coverage.transition(CoverageState.KNOWN_DEGRADED, now)
        else:
            self._coverage.transition(CoverageState.UNKNOWN, now)

    async def _clean_stop(self, client: PublicClient | None) -> Path:
        self.causal_seq += 1
        for tracker in self.trackers.values():
            self._record_episode_end(tracker.stop(causal_seq=self.causal_seq).ended_episode)
        if client is not None:
            await self._sync_combo_subscriptions(client)
        stop_ms = _monotonic_ms()
        segments = self._coverage.close(stop_ms)
        summary = project_run_summary(
            code_identity=self.code_identity,
            runtime_identity=self.runtime_identity,
            policy_identity=self.policy.identity,
            coverage_segments=segments,
            band_suspended_duration_ms=self._band_suspended_duration_ms,
            counts_by_scope=[
                value.as_object()
                for _, value in sorted(
                    self._scope_counts.items(),
                    key=lambda item: (
                        item[0][1].value,
                        item[0][2],
                    ),
                )
            ],
            detector_unknown_transition_count_by_reason=self._unknown_counts,
            anomaly_end_count_by_reason=self._episode_end_counts,
            known_active_duration_ms_sum_by_end_reason=self._known_active_duration_ms,
            public_atomic_quote_state_transition_count=self._atomic_transition_counts,
            heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
            liveness_deadline_seconds=LIVENESS_DEADLINE_SECONDS,
            clock_drift_ppm=1_000,
        )
        return self.writer.write_summary(summary)


async def observe(
    *,
    policy: RadarPolicy,
    code_identity: str,
    evidence_directory: Path,
    stop_event: asyncio.Event | None = None,
) -> Path:
    runtime_identity = str(uuid.uuid4())
    writer = EvidenceWriter(
        evidence_directory,
        code_identity=code_identity,
        runtime_identity=runtime_identity,
        policy_identity=policy.identity,
    )
    runtime = LiveRadarRuntime(
        policy=policy,
        code_identity=code_identity,
        evidence_writer=writer,
        runtime_identity=runtime_identity,
    )
    event = stop_event or _signal_stop_event()
    while not event.is_set():
        try:
            async with DeribitPublicClient() as client:
                return await runtime.run(client, event)
        except (
            ConnectionError,
            ContinuityGap,
            OSError,
            PublicProtocolError,
            SourceDataError,
            TimeoutError,
            WebSocketException,
        ) as exc:
            runtime.prepare_reconnect(f"SESSION_RECONNECT:{type(exc).__name__}")
            if not event.is_set():
                await asyncio.sleep(1)
    return await runtime._clean_stop(None)


def _signal_stop_event() -> asyncio.Event:
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, event.set)
        except NotImplementedError:
            pass
    return event


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000

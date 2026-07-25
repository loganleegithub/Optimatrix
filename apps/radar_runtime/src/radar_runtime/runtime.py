from __future__ import annotations

import asyncio
import contextlib
import random
import signal
import time
import uuid
from collections import Counter, deque
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from market_monitor import (
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
    decimal_from_source,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from options_domain import (
    ComboInstrument,
    OptionInstrument,
    OptionType,
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
    EpisodeEndReason,
    EpisodeTracker,
    TrackerState,
    TrackerTransition,
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
from short_vol_radar.policy import (
    RadarPolicy,
    TimeApplicability,
    classify_time_applicability,
)
from short_vol_radar.radar import (
    CurrentDisposition,
    CurrentEvaluation,
    EvaluationResult,
    TickerState,
    apply_current_evaluation,
    calculate_current_evaluation,
    detector_observation_identity,
    parse_ticker,
)
from websockets.exceptions import WebSocketException

from radar_runtime.deribit_public import (
    DeribitPublicClient,
    InboundEnvelope,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicRequestError,
    PublicSessionError,
)

MAX_NOTIFICATION_QUEUE_LAG_MS = 1_000


class PublicClient(Protocol):
    last_inbound_monotonic: float

    async def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object: ...

    async def subscribe(self, channels: tuple[str, ...] | list[str]) -> object: ...

    async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> object: ...

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


@dataclass(frozen=True)
class ScopeSnapshot:
    causal_seq: int
    trusted_time: TimeInterval
    clock_revision: int
    instrument_names: tuple[str, ...]
    boundary_observation_eligible: bool
    observation_reason: str | None


@dataclass
class _OptionCatalogContinuation:
    generation: int
    dirty: bool = False
    earliest_lifecycle_ingress_seq: int | None = None
    has_unsequenced_lifecycle: bool = False


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
        if stop_monotonic_ms < self._current_start_ms:
            raise RuntimeError("coverage stop precedes the current segment")
        if stop_monotonic_ms > self._current_start_ms or not self._segments:
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
        self._pending_option_unsubscribe: set[str] = set()
        self._failed_option_subscriptions: set[str] = set()
        self._failed_combo_subscriptions: set[str] = set()
        self._combo_summary_fingerprints: dict[str, tuple[object, ...]] = {}
        self._combo_refresh_task: asyncio.Task[None] | None = None
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock: TrustedClock | None = None
        self.causal_seq = 0
        self._clock_revision = 0
        self._last_fingerprints: dict[str, tuple[object, ...]] = {}
        self._last_observation_fingerprints: dict[str, tuple[object, ...]] = {}
        self._last_detector_causal_seq: dict[str, int] = {}
        self._emitted_atomic_quotes: set[tuple[str, str]] = set()
        self._last_unknown_reason: dict[str, str | None] = {}
        self._scope_counts: dict[tuple[str, OptionType, str], ScopeCounts] = {}
        self._unknown_counts: Counter[str] = Counter()
        self._episode_end_counts: Counter[str] = Counter()
        self._known_active_duration_ms: Counter[str] = Counter()
        self._atomic_transition_counts: Counter[str] = Counter()
        self._episode_active_segment_started_ms: dict[str, int] = {}
        self._episode_active_accumulated_ms: Counter[str] = Counter()
        self._episode_last_trusted_boundary_ms: dict[str, int] = {}
        self._episode_option_types: dict[str, OptionType] = {}
        self._band_suspended_started_ms: dict[str, int] = {}
        self._band_suspended_duration_ms = 0
        self._max_notification_queue_lag_ms = 0
        self._last_applied_ingress_seq = 0
        self._last_rpc_received_monotonic_ms: int | None = None
        self._last_rpc_ingress_seq: int | None = None
        self._deferred_notifications: deque[dict[str, object]] = deque()
        self._noted_notification_ids: set[int] = set()
        self._option_lifecycle_generation = 0
        self._option_catalog_continuations: list[_OptionCatalogContinuation] = []
        self._combo_lifecycle_generation = 0
        self._combo_refresh_dirty = False
        self._economic_reducer_depth = 0
        self._max_economic_reducer_depth = 0
        self._bootstrap_in_progress = False
        self._session_established = False
        started = _monotonic_ms()
        self._coverage = CoverageLedger(started)

    async def run(self, client: PublicClient, stop_event: asyncio.Event) -> Path:
        await self._bootstrap(client)
        self._session_established = True
        next_clock_refresh_ms = _monotonic_ms() + 30_000
        next_membership_refresh_ms = _monotonic_ms() + 1_000
        while not stop_event.is_set():
            now_ms = _monotonic_ms()
            if now_ms >= next_clock_refresh_ms:
                await self._refresh_clock(client)
                next_clock_refresh_ms = now_ms + 30_000
            if now_ms >= next_membership_refresh_ms:
                await self._recover_incomplete_catalogs(client)
                if await self._sync_option_membership(client):
                    await self._coalesced_combo_refresh(client)
                next_membership_refresh_ms = now_ms + 1_000
            if time.monotonic() - client.last_inbound_monotonic >= LIVENESS_DEADLINE_SECONDS:
                self._accept_causal_fact()
                self._invalidate_all("SESSION_GAP")
                raise PublicSessionError("production-public session liveness deadline expired")
            try:
                message = await self._next_notification(client, timeout_seconds=1.0)
            except TimeoutError:
                continue
            await self._handle_message(
                client,
                message,
                received_monotonic_ms=getattr(message, "received_monotonic_ms", None),
            )
        return await self._clean_stop(client)

    async def _bootstrap(self, client: PublicClient) -> None:
        self._bootstrap_in_progress = True
        try:
            self._reset_session_state()
            heartbeat = await self._request_public(
                client,
                "public/set_heartbeat",
                {"interval": HEARTBEAT_INTERVAL_SECONDS},
            )
            if heartbeat != "ok":
                raise PublicProtocolIncompatibility("heartbeat acknowledgement was not ok")
            await self._subscribe_public(client, list(PLATFORM_CHANNELS))
            self.platform.acknowledge(PLATFORM_CHANNELS)
            await self._subscribe_public(
                client,
                [OPTION_LIFECYCLE_CHANNEL, COMBO_LIFECYCLE_CHANNEL],
            )
            self.option_catalog.acknowledge_lifecycle()
            self.combo_catalog.acknowledge_lifecycle()
            status = await self._request_public(client, "public/status", {})
            self.platform.apply_status(status)
            self._accept_causal_fact()
            self.platform.public_methods_allowed = True
            await self._bootstrap_clock(client)
            option_payloads = require_list(
                await self._request_public(
                    client,
                    "public/get_instruments",
                    {"currency": "USDC", "kind": "option", "expired": False},
                ),
                "public/get_instruments result",
            )
            option_snapshot_complete = self._replace_options(option_payloads)
            self._accept_causal_fact()
            try:
                combo_payloads = require_list(
                    await self._request_public(client, "public/get_combos", {"currency": "USDC"}),
                    "public/get_combos result",
                )
                self._accept_causal_fact()
                combo_snapshot_complete = await self._replace_combos(client, combo_payloads)
            except (SourceDataError, PublicRequestError, TimeoutError):
                self.combo_catalog.mark_incomplete()
                self.combos.clear()
                combo_snapshot_complete = False
            for message in (*self._drain_deferred(), *client.drain_notifications()):
                await self._handle_bootstrap_message(client, message)
            for event in self.option_catalog.reconcile():
                await self._apply_option_lifecycle(client, event)
            self.option_catalog.complete = self.option_catalog.complete and option_snapshot_complete
            for _event in self.combo_catalog.reconcile():
                await self._coalesced_combo_refresh(client)
            self.combo_catalog.complete = self.combo_catalog.complete and combo_snapshot_complete
            await self._sync_option_membership(client)
            await self._subscribe_public(client, [INDEX_CHANNEL])
            if self.clock is None:
                raise RuntimeError("clock was not established")
            self.index.start_continuous_coverage(self.clock.interval_at(_monotonic_ms()).lower_ms)
            try:
                self.platform.prove_operational_from_post_status_public_success()
            except RuntimeError as exc:
                raise PublicSessionError(
                    "platform state was unusable after public bootstrap"
                ) from exc
            self._update_coverage()
        finally:
            self._bootstrap_in_progress = False

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
        self._last_detector_causal_seq.clear()
        self._subscribed_combo_names.clear()
        self._pending_option_unsubscribe.clear()
        self._failed_option_subscriptions.clear()
        self._failed_combo_subscriptions.clear()
        self._combo_summary_fingerprints.clear()
        self._combo_refresh_task = None
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock = None
        self._clock_revision = 0
        self._last_fingerprints.clear()
        self._last_observation_fingerprints.clear()
        self._last_applied_ingress_seq = 0
        self._last_rpc_received_monotonic_ms = None
        self._last_rpc_ingress_seq = None
        self._deferred_notifications.clear()
        self._noted_notification_ids.clear()
        self._option_lifecycle_generation = 0
        self._option_catalog_continuations.clear()
        self._combo_lifecycle_generation = 0
        self._combo_refresh_dirty = False
        self._economic_reducer_depth = 0
        self._max_economic_reducer_depth = 0
        self._session_established = False

    def prepare_reconnect(self, reason: str) -> None:
        reason = _canonical_unknown_reason(reason)
        if self.platform.reason == reason:
            return
        self._accept_causal_fact()
        self._invalidate_all(reason)

    async def _request_public(
        self,
        client: PublicClient,
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        request_task = asyncio.create_task(
            client.request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )
        )
        result, notifications = await self._await_operation(client, request_task)
        if not isinstance(result, InboundEnvelope):
            for message in notifications:
                self._defer_notification(message)
            self._last_rpc_received_monotonic_ms = _monotonic_ms()
            self._last_rpc_ingress_seq = None
            return result
        notifications.extend(self._drain_deferred())
        notifications.extend(client.drain_notifications())
        notifications.sort(key=lambda item: getattr(item, "ingress_seq", result.ingress_seq + 1))
        for message in notifications:
            if message.get("method") == "heartbeat":
                await self._route_ingress_notification(client, message)
                continue
            if (
                getattr(message, "ingress_seq", result.ingress_seq + 1) < result.ingress_seq
                and self._economic_reducer_depth == 0
            ):
                await self._route_ingress_notification(client, message)
            else:
                self._defer_notification(message)
        crossed_pending_economic = any(
            message.get("method") != "heartbeat"
            and getattr(message, "ingress_seq", result.ingress_seq + 1) < result.ingress_seq
            for message in self._deferred_notifications
        )
        if responding_to_test_request:
            self._check_receive_lag(result)
        elif crossed_pending_economic:
            self._check_receive_lag(result)
        else:
            self._start_ingress(result)
        self._last_rpc_received_monotonic_ms = result.received_monotonic_ms
        self._last_rpc_ingress_seq = result.ingress_seq
        value = result.value
        if (
            crossed_pending_economic
            and self._economic_reducer_depth
            and not responding_to_test_request
        ):
            raise PublicRequestError(
                "RPC continuation crossed an earlier pending economic ingress",
                envelope=result,
            )
        return value

    async def _await_operation(
        self,
        client: PublicClient,
        operation_task: asyncio.Future[object],
    ) -> tuple[object, list[dict[str, object]]]:
        notifications: list[dict[str, object]] = []
        await asyncio.sleep(0)
        try:
            while not operation_task.done():
                notification_task = asyncio.create_task(
                    self._next_notification(client, timeout_seconds=0.05)
                )
                done, _pending = await asyncio.wait(
                    (operation_task, notification_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if notification_task in done:
                    try:
                        message = notification_task.result()
                    except TimeoutError:
                        self._check_blocked_request_deadlines(client)
                    else:
                        self._note_notification_arrival(message)
                        if message.get("method") == "heartbeat":
                            try:
                                self._check_receive_lag(message)
                                await self._handle_heartbeat(client, message)
                            finally:
                                self._noted_notification_ids.discard(id(message))
                        else:
                            notifications.append(message)
                else:
                    notification_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                        await notification_task
        except BaseException:
            if not operation_task.done():
                operation_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await operation_task
            raise
        try:
            result = await operation_task
        except BaseException:
            for message in notifications:
                self._defer_notification(message)
            raise
        return result, notifications

    async def _subscribe_public(
        self,
        client: PublicClient,
        channels: tuple[str, ...] | list[str],
    ) -> None:
        await self._change_channels(client, client.subscribe(channels))

    async def _unsubscribe_public(
        self,
        client: PublicClient,
        channels: tuple[str, ...] | list[str],
    ) -> None:
        await self._change_channels(client, client.unsubscribe(channels))

    async def _change_channels(
        self,
        client: PublicClient,
        operation: Awaitable[object],
    ) -> None:
        task = asyncio.ensure_future(operation)
        try:
            result, notifications = await self._await_operation(client, task)
        except PublicRequestError as exc:
            if exc.envelope is not None:
                queued = [*self._drain_deferred(), *client.drain_notifications()]
                queued.sort(key=lambda item: getattr(item, "ingress_seq", 2**63))
                crossed = any(
                    message.get("method") != "heartbeat"
                    and getattr(message, "ingress_seq", exc.envelope.ingress_seq + 1)
                    < exc.envelope.ingress_seq
                    for message in queued
                )
                if crossed and self._economic_reducer_depth:
                    for message in queued:
                        self._defer_notification(message)
                    self._check_receive_lag(exc.envelope)
                else:
                    for message in queued:
                        if message.get("method") == "heartbeat":
                            await self._route_ingress_notification(client, message)
                        elif (
                            getattr(
                                message,
                                "ingress_seq",
                                exc.envelope.ingress_seq + 1,
                            )
                            < exc.envelope.ingress_seq
                        ):
                            await self._route_ingress_notification(client, message)
                        else:
                            self._defer_notification(message)
                    self._start_ingress(exc.envelope)
            raise
        notifications.extend(self._drain_deferred())
        notifications.extend(client.drain_notifications())
        notifications.sort(key=lambda item: getattr(item, "ingress_seq", 2**63))
        envelopes = result if isinstance(result, tuple) else ()
        envelope_values = tuple(
            envelope for envelope in envelopes if isinstance(envelope, InboundEnvelope)
        )
        crossed = bool(envelope_values) and any(
            message.get("method") != "heartbeat"
            and getattr(message, "ingress_seq", envelope_values[-1].ingress_seq + 1)
            < envelope_values[-1].ingress_seq
            for message in notifications
        )
        if crossed and self._economic_reducer_depth:
            for message in notifications:
                self._defer_notification(message)
            for envelope in envelope_values:
                self._check_receive_lag(envelope)
            raise PublicRequestError(
                "channel RPC continuation crossed an earlier pending economic ingress",
                envelope=envelope_values[-1],
            )
        pending_envelopes = list(envelope_values)
        last_envelope_seq = envelope_values[-1].ingress_seq if envelope_values else None
        for message in notifications:
            message_seq = getattr(message, "ingress_seq", 2**63)
            while pending_envelopes and pending_envelopes[0].ingress_seq < message_seq:
                self._start_ingress(pending_envelopes.pop(0))
            if message.get("method") == "heartbeat":
                await self._route_ingress_notification(client, message)
            elif last_envelope_seq is not None and message_seq < last_envelope_seq:
                await self._route_ingress_notification(client, message)
            else:
                self._defer_notification(message)
        for envelope in pending_envelopes:
            self._start_ingress(envelope)

    def _check_blocked_request_deadlines(self, client: PublicClient) -> None:
        if time.monotonic() - client.last_inbound_monotonic >= LIVENESS_DEADLINE_SECONDS:
            self._accept_causal_fact()
            self._invalidate_all("SESSION_GAP")
            raise PublicSessionError("production-public session liveness deadline expired")
        if self.clock is None:
            return
        try:
            self.clock.interval_at(_monotonic_ms())
        except ContinuityGap:
            self._accept_causal_fact()
            self._invalidate_all("CLOCK_GAP")
            raise

    async def _route_ingress_notification(
        self,
        client: PublicClient,
        message: dict[str, object],
    ) -> None:
        self._note_notification_arrival(message)
        if message.get("method") == "heartbeat":
            self._check_receive_lag(message)
            await self._handle_heartbeat(client, message)
            self._noted_notification_ids.discard(id(message))
            return
        if self._economic_reducer_depth:
            self._defer_notification(message)
            return
        if self._bootstrap_in_progress:
            await self._handle_bootstrap_message(client, message)
        else:
            await self._handle_message(
                client,
                message,
                received_monotonic_ms=getattr(message, "received_monotonic_ms", None),
            )

    def _defer_notification(self, message: dict[str, object]) -> None:
        self._note_notification_arrival(message)
        if not any(existing is message for existing in self._deferred_notifications):
            self._deferred_notifications.append(message)

    def _note_notification_arrival(self, message: dict[str, object]) -> None:
        identity = id(message)
        if identity in self._noted_notification_ids:
            return
        self._noted_notification_ids.add(identity)
        if message.get("method") != "subscription":
            return
        params = message.get("params")
        if not isinstance(params, dict):
            return
        channel = params.get("channel")
        if channel == OPTION_LIFECYCLE_CHANNEL:
            self._option_lifecycle_generation += 1
            ingress_seq = getattr(message, "ingress_seq", None)
            for continuation in self._option_catalog_continuations:
                continuation.dirty = True
                if not isinstance(ingress_seq, int):
                    continuation.has_unsequenced_lifecycle = True
                elif (
                    continuation.earliest_lifecycle_ingress_seq is None
                    or ingress_seq < continuation.earliest_lifecycle_ingress_seq
                ):
                    continuation.earliest_lifecycle_ingress_seq = ingress_seq
        elif channel == COMBO_LIFECYCLE_CHANNEL:
            self._combo_lifecycle_generation += 1
            if self._combo_refresh_task is not None:
                self._combo_refresh_dirty = True

    async def _next_notification(
        self,
        client: PublicClient,
        *,
        timeout_seconds: float | None,
    ) -> dict[str, object]:
        if self._deferred_notifications:
            return self._deferred_notifications.popleft()
        return await client.next_notification(timeout_seconds=timeout_seconds)

    def _drain_deferred(self) -> tuple[dict[str, object], ...]:
        values = tuple(self._deferred_notifications)
        self._deferred_notifications.clear()
        return values

    def _start_ingress(
        self,
        frame: object,
        *,
        received_monotonic_ms: int | None = None,
    ) -> int | None:
        ingress_seq = getattr(frame, "ingress_seq", None)
        if ingress_seq is not None:
            if not isinstance(ingress_seq, int) or ingress_seq <= self._last_applied_ingress_seq:
                raise PublicProtocolError("inbound frame ingress sequence is not increasing")
            self._last_applied_ingress_seq = ingress_seq
        return self._check_receive_lag(
            frame,
            received_monotonic_ms=received_monotonic_ms,
        )

    def _check_receive_lag(
        self,
        frame: object,
        *,
        received_monotonic_ms: int | None = None,
    ) -> int | None:
        if received_monotonic_ms is None:
            received_monotonic_ms = getattr(frame, "received_monotonic_ms", None)
        if received_monotonic_ms is None:
            return None
        if not isinstance(received_monotonic_ms, int):
            raise PublicProtocolError("inbound frame receive time is invalid")
        queue_lag_ms = _monotonic_ms() - received_monotonic_ms
        if queue_lag_ms < 0:
            raise PublicProtocolError("inbound frame receive time is in the future")
        self._max_notification_queue_lag_ms = max(
            self._max_notification_queue_lag_ms,
            queue_lag_ms,
        )
        if queue_lag_ms > MAX_NOTIFICATION_QUEUE_LAG_MS:
            self._accept_causal_fact()
            self._invalidate_all("SESSION_GAP")
            raise PublicSessionError(
                f"notification queue lag exceeded {MAX_NOTIFICATION_QUEUE_LAG_MS} ms"
            )
        return received_monotonic_ms

    async def _bootstrap_clock(self, client: PublicClient) -> None:
        sent = _monotonic_ms()
        result = await self._request_public(client, "public/get_time", {})
        received = self._last_rpc_received_monotonic_ms
        if received is None:
            raise RuntimeError("public/get_time response lacked a receive boundary")
        server_ms = require_int(result, "public/get_time result")
        self.clock = TrustedClock.from_response(server_ms, sent, received)
        self._clock_revision += 1
        self._accept_causal_fact()

    async def _refresh_clock(self, client: PublicClient) -> None:
        if self.clock is None:
            await self._bootstrap_clock(client)
            return
        sent = _monotonic_ms()
        result = await self._request_public(client, "public/get_time", {})
        received = self._last_rpc_received_monotonic_ms
        if received is None:
            raise RuntimeError("public/get_time response lacked a receive boundary")
        server_ms = require_int(result, "public/get_time result")
        self._accept_causal_fact()
        try:
            self.clock = self.clock.refresh(
                server_ms,
                sent,
                received,
            )
        except ContinuityGap:
            self._invalidate_all("CLOCK_GAP")
            raise
        self._clock_revision += 1
        if await self._sync_option_membership(client):
            await self._coalesced_combo_refresh(client)
        self.index.seal_ready(self.clock.interval_at(_monotonic_ms()).lower_ms)
        await self._evaluate_all(
            client,
            boundary_observation_eligible=False,
            observation_reason="CLOCK_ONLY",
        )

    def _replace_options(self, payloads: list[object]) -> bool:
        if self.clock is None:
            raise RuntimeError("clock required before catalog filtering")
        options, complete = self._parse_option_snapshot(payloads)
        self.catalog_options = options
        trusted_time = self.clock.interval_at(_monotonic_ms())
        self.options = {
            name: instrument
            for name, instrument in options.items()
            if classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted_time,
                option_type=instrument.option_type,
            ).classification
            is not TimeApplicability.OUT_OF_MONITOR_SCOPE
        }
        for instrument_name in set(self.trackers) - set(self.options):
            self.trackers.pop(instrument_name, None)
            self._last_unknown_reason.pop(instrument_name, None)
            self._last_detector_causal_seq.pop(instrument_name, None)
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

    @staticmethod
    def _parse_option_snapshot(
        payloads: list[object],
    ) -> tuple[dict[str, OptionInstrument], bool]:
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
        return options, complete

    async def _sync_option_membership(self, client: PublicClient) -> bool:
        if self.clock is None:
            raise RuntimeError("clock required before membership synchronization")
        boundary_monotonic_ms = _monotonic_ms()
        trusted_time = self.clock.interval_at(boundary_monotonic_ms)
        desired = {
            name: instrument
            for name, instrument in self.catalog_options.items()
            if classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted_time,
                option_type=instrument.option_type,
            ).classification
            is not TimeApplicability.OUT_OF_MONITOR_SCOPE
        }
        current_names = set(self.options)
        desired_names = set(desired)
        membership_removals = sorted(current_names - desired_names)
        removals = sorted(set(membership_removals) | self._pending_option_unsubscribe)
        additions = sorted(
            name
            for name in desired_names
            if name not in self.option_books or name in self._failed_option_subscriptions
        )
        if membership_removals or additions:
            self._accept_causal_fact()
        for instrument_name in membership_removals:
            tracker = self.trackers[instrument_name]
            transition = tracker.membership_loss(causal_seq=self.causal_seq)
            self._record_episode_end(
                transition.ended_episode,
                boundary_monotonic_ms=boundary_monotonic_ms,
            )
            self.option_books.pop(instrument_name, None)
            self.tickers.pop(instrument_name, None)
            self.results.pop(instrument_name, None)
            self._last_fingerprints.pop(instrument_name, None)
            self._last_observation_fingerprints.pop(instrument_name, None)
            self._last_unknown_reason.pop(instrument_name, None)
            self._last_detector_causal_seq.pop(instrument_name, None)
            self.trackers.pop(instrument_name, None)
            self._pending_option_unsubscribe.add(instrument_name)
            self._failed_option_subscriptions.discard(instrument_name)
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
        if membership_removals or additions:
            self._update_coverage(monotonic_ms=boundary_monotonic_ms)
        if removals:
            try:
                await self._unsubscribe_public(
                    client,
                    [
                        channel
                        for name in removals
                        for channel in (ticker_channel(name), book_channel(name))
                    ],
                )
            except (PublicRequestError, SourceDataError, TimeoutError):
                pass
            else:
                self._pending_option_unsubscribe.difference_update(removals)
        if additions:
            try:
                await self._subscribe_public(
                    client,
                    [
                        channel
                        for name in additions
                        for channel in (ticker_channel(name), book_channel(name))
                    ],
                )
            except (PublicRequestError, SourceDataError, TimeoutError):
                for name in additions:
                    self.option_books[name].invalidate("OPTION_CHANNEL_REQUEST_FAILURE")
                    self._failed_option_subscriptions.add(name)
                    tracker = self.trackers[name]
                    self._mark_tracker_unknown(
                        tracker,
                        reason="OPTION_CHANNEL_REQUEST_FAILURE",
                    )
            else:
                self._failed_option_subscriptions.difference_update(additions)
        if membership_removals:
            await self._sync_combo_subscriptions(client)
        return bool(additions or membership_removals)

    async def _replace_combos(self, client: PublicClient, payloads: list[object]) -> bool:
        combos: dict[str, ComboInstrument] = {}
        fingerprints: dict[str, tuple[object, ...]] = {}
        complete = True
        for payload in payloads:
            try:
                summary = require_mapping(payload, "combo")
                raw_legs = require_list(summary.get("legs"), "combo.legs")
                parsed_legs = tuple(
                    (
                        require_str(
                            require_mapping(item, "combo leg").get("instrument_name"),
                            "combo leg.instrument_name",
                        ),
                        decimal_from_source(
                            require_mapping(item, "combo leg").get("amount"),
                            "combo leg.amount",
                        ),
                    )
                    for item in raw_legs
                )
                leg_names = {name for name, _amount in parsed_legs}
                combo_id = require_str(summary.get("id"), "combo.id")
                state = require_str(summary.get("state"), "combo.state")
            except SourceDataError:
                complete = False
                continue
            if len(raw_legs) != 2 or len(leg_names) != 2:
                continue
            if not leg_names <= set(self.options):
                if leg_names & set(self.options):
                    complete = False
                continue
            fingerprint = (
                state,
                tuple(parsed_legs),
            )
            if not combo_id:
                complete = False
                continue
            fingerprints[combo_id] = fingerprint
            combo = self.combos.get(combo_id)
            if combo is None or self._combo_summary_fingerprints.get(combo_id) != fingerprint:
                metadata = await self._request_public(
                    client,
                    "public/get_instrument",
                    {"instrument_name": combo_id},
                )
                self._accept_causal_fact()
                try:
                    combo = parse_combo_instrument(summary, metadata)
                except SourceDataError:
                    complete = False
                    continue
            if combo is not None:
                combos[combo.instrument_name] = combo
        self.combos = combos
        self._combo_summary_fingerprints = fingerprints
        return complete

    async def _handle_bootstrap_message(
        self, client: PublicClient, message: dict[str, object]
    ) -> None:
        await self._run_economic_reducer(client, message, bootstrap=True)

    async def _handle_message(
        self,
        client: PublicClient,
        message: dict[str, object],
        *,
        received_monotonic_ms: int | None = None,
    ) -> None:
        if received_monotonic_ms is not None and not hasattr(message, "received_monotonic_ms"):
            self._check_receive_lag(message, received_monotonic_ms=received_monotonic_ms)
        await self._run_economic_reducer(client, message, bootstrap=False)

    async def _run_economic_reducer(
        self,
        client: PublicClient,
        message: dict[str, object],
        *,
        bootstrap: bool,
    ) -> None:
        self._note_notification_arrival(message)
        if message.get("method") == "heartbeat":
            self._check_receive_lag(message)
            await self._handle_heartbeat(client, message)
            self._noted_notification_ids.discard(id(message))
            return
        if self._economic_reducer_depth:
            self._defer_notification(message)
            return
        self._economic_reducer_depth = 1
        self._max_economic_reducer_depth = max(
            self._max_economic_reducer_depth,
            self._economic_reducer_depth,
        )
        pending = [message]
        try:
            while pending:
                pending.sort(key=lambda item: getattr(item, "ingress_seq", 2**63))
                current = pending.pop(0)
                if bootstrap:
                    await self._reduce_bootstrap_message(client, current)
                else:
                    await self._reduce_message(client, current)
                self._noted_notification_ids.discard(id(current))
                if self._deferred_notifications:
                    pending.extend(self._drain_deferred())
        finally:
            self._economic_reducer_depth = 0

    async def _reduce_bootstrap_message(
        self, client: PublicClient, message: dict[str, object]
    ) -> None:
        self._start_ingress(message)
        method = message.get("method")
        if method == "heartbeat":
            await self._handle_heartbeat(client, message)
            return
        if method != "subscription":
            if method == "connection_error":
                raise PublicSessionError("connection failed during bootstrap")
            return
        params = require_mapping(message.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        data = params.get("data")
        self._accept_causal_fact()
        if channel == OPTION_LIFECYCLE_CHANNEL:
            try:
                event = self.option_catalog.accept_lifecycle(data)
            except SourceDataError:
                self.option_catalog.mark_incomplete()
            else:
                if event is not None:
                    await self._apply_option_lifecycle(client, event)
        elif channel == COMBO_LIFECYCLE_CHANNEL:
            try:
                event = self.combo_catalog.accept_lifecycle(data)
            except SourceDataError:
                self.combo_catalog.mark_incomplete()
            else:
                if event is not None:
                    await self._coalesced_combo_refresh(client)
        elif channel == "platform_state":
            self.platform.apply_platform_notification(data)
        elif channel == "platform_state.public_methods_state":
            self.platform.apply_public_methods_notification(data)

    async def _reduce_message(
        self,
        client: PublicClient,
        message: dict[str, object],
    ) -> None:
        processing_ms = _monotonic_ms()
        ingress_received_ms = self._start_ingress(message)
        known_at_ms = ingress_received_ms if ingress_received_ms is not None else processing_ms
        method = message.get("method")
        if method == "heartbeat":
            await self._handle_heartbeat(client, message)
            return
        if method == "connection_error":
            self._accept_causal_fact()
            self._invalidate_all("SESSION_GAP")
            raise PublicSessionError("production-public connection closed")
        if method != "subscription":
            raise PublicProtocolError("unexpected non-subscription notification")
        params = require_mapping(message.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        data = params.get("data")
        self.causal_seq += 1
        if channel == INDEX_CHANNEL:
            await self._handle_index(client, data, received_monotonic_ms=known_at_ms)
        elif channel.startswith("ticker.") and channel.endswith(".100ms"):
            instrument_name = channel[len("ticker.") : -len(".100ms")]
            if (
                instrument_name not in self.options
                or instrument_name in self._pending_option_unsubscribe
                or instrument_name in self._failed_option_subscriptions
            ):
                return
            try:
                ticker = parse_ticker(data, instrument_name)
            except ValueError:
                self.tickers.pop(instrument_name, None)
                self._last_fingerprints.pop(instrument_name, None)
                self._last_observation_fingerprints.pop(instrument_name, None)
                tracker = self.trackers.get(instrument_name)
                if tracker is not None:
                    transition = self._mark_tracker_unknown(
                        tracker,
                        reason="FORWARD_TICKER_INVALID",
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
                self._last_observation_fingerprints.pop(instrument_name, None)
                tracker = self.trackers.get(instrument_name)
                if tracker is not None:
                    transition = self._mark_tracker_unknown(
                        tracker,
                        reason="FORWARD_TICKER_TIMESTAMP_GAP",
                        continuity_gap=True,
                    )
                    self._record_episode_end(transition.ended_episode)
                try:
                    await self._unsubscribe_public(client, [ticker_channel(instrument_name)])
                    await self._subscribe_public(client, [ticker_channel(instrument_name)])
                except (PublicRequestError, SourceDataError, TimeoutError):
                    self._failed_option_subscriptions.add(instrument_name)
                self._update_coverage()
                return
            self.tickers[instrument_name] = ticker
            await self._evaluate_one(
                client,
                instrument_name,
                evaluation_monotonic_ms=known_at_ms,
            )
        elif channel.startswith("book.") and channel.endswith(".100ms"):
            instrument_name = channel[len("book.") : -len(".100ms")]
            await self._handle_book(
                client,
                instrument_name,
                data,
                received_monotonic_ms=known_at_ms,
            )
        elif channel == OPTION_LIFECYCLE_CHANNEL:
            try:
                await self._apply_option_lifecycle(client, data)
            except SourceDataError:
                self.option_catalog.mark_incomplete()
                await self._recover_option_catalog(client)
        elif channel == COMBO_LIFECYCLE_CHANNEL:
            await self._coalesced_combo_refresh(client)
        elif channel == "platform_state":
            self.platform.apply_platform_notification(data)
            if self.platform.maintenance is True or not self.platform.status_usable:
                self._invalidate_all(self.platform.reason)
                raise PublicSessionError("platform state requires full bootstrap")
        elif channel == "platform_state.public_methods_state":
            self.platform.apply_public_methods_notification(data)
            if self.platform.public_methods_allowed is False:
                self._invalidate_all(self.platform.reason)
                raise PublicSessionError("public-method state requires full bootstrap")
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
        self.platform.complete_post_status_bootstrap()
        self._last_fingerprints.clear()
        await self._evaluate_all(client)

    async def _handle_heartbeat(self, client: PublicClient, message: dict[str, object]) -> None:
        params = require_mapping(message.get("params"), "heartbeat.params")
        heartbeat_type = require_str(params.get("type"), "heartbeat.params.type")
        if heartbeat_type == "test_request":
            result = await self._request_public(
                client,
                "public/test",
                {},
                responding_to_test_request=True,
            )
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("version"), str)
                or not result["version"]
            ):
                raise PublicProtocolIncompatibility("public/test result lacks a valid version")
        elif heartbeat_type != "heartbeat":
            raise PublicProtocolIncompatibility("unknown heartbeat type")

    async def _handle_index(
        self,
        client: PublicClient,
        payload: object,
        *,
        received_monotonic_ms: int | None = None,
    ) -> None:
        if self.clock is None:
            raise RuntimeError("index tick arrived before clock")
        known_at_ms = (
            received_monotonic_ms if received_monotonic_ms is not None else _monotonic_ms()
        )
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
            self._last_observation_fingerprints.clear()
            for tracker in self.trackers.values():
                transition = self._mark_tracker_unknown(
                    tracker,
                    reason="INDEX_GAP",
                    continuity_gap=True,
                )
                self._record_episode_end(transition.ended_episode)
            self.platform.reason = "INDEX_GAP"
            self._update_coverage(monotonic_ms=known_at_ms)
            try:
                await self._unsubscribe_public(client, [INDEX_CHANNEL])
                await self._subscribe_public(client, [INDEX_CHANNEL])
            except (PublicRequestError, SourceDataError, TimeoutError) as exc:
                raise ContinuityGap("index resubscription failed") from exc
            if self.clock is not None:
                self.index.start_continuous_coverage(
                    self.clock.interval_at(_monotonic_ms()).lower_ms
                )
            if self.platform.usable:
                self.platform.reason = "USABLE"
            return
        sealed = self.index.seal_ready(self.clock.interval_at(known_at_ms).lower_ms)
        if sealed:
            await self._evaluate_all(client, evaluation_monotonic_ms=known_at_ms)

    async def _handle_book(
        self,
        client: PublicClient,
        instrument_name: str,
        payload: object,
        *,
        received_monotonic_ms: int | None = None,
    ) -> None:
        known_at_ms = (
            received_monotonic_ms if received_monotonic_ms is not None else _monotonic_ms()
        )
        if instrument_name in self._pending_option_unsubscribe:
            return
        if instrument_name in self._failed_option_subscriptions:
            return
        book = self.option_books.get(instrument_name)
        if book is not None:
            try:
                changed = book.apply(payload, known_at_ms)
            except (ContinuityGap, SourceDataError) as exc:
                book.invalidate(type(exc).__name__)
                transition = self._mark_tracker_unknown(
                    self.trackers[instrument_name],
                    reason="OPTION_BOOK_GAP",
                    continuity_gap=True,
                )
                self._record_episode_end(transition.ended_episode)
                self._last_fingerprints.pop(instrument_name, None)
                self._last_observation_fingerprints.pop(instrument_name, None)
                self.option_books[instrument_name] = ContinuousOrderBook(instrument_name)
                try:
                    await self._unsubscribe_public(client, [book_channel(instrument_name)])
                    await self._subscribe_public(client, [book_channel(instrument_name)])
                except (PublicRequestError, SourceDataError, TimeoutError):
                    self.option_books[instrument_name].invalidate("OPTION_CHANNEL_REQUEST_FAILURE")
                    self._failed_option_subscriptions.add(instrument_name)
                return
            if changed:
                await self._evaluate_one(
                    client,
                    instrument_name,
                    evaluation_monotonic_ms=known_at_ms,
                )
            return
        combo_book = self.combo_books.get(instrument_name)
        if combo_book is None:
            raise PublicProtocolError("book notification has no owned instrument")
        try:
            changed = combo_book.apply(payload, known_at_ms)
        except (ContinuityGap, SourceDataError) as exc:
            combo_book.invalidate(type(exc).__name__)
            self.combo_books[instrument_name] = ContinuousOrderBook(instrument_name)
            try:
                await self._unsubscribe_public(client, [book_channel(instrument_name)])
                await self._subscribe_public(client, [book_channel(instrument_name)])
            except (PublicRequestError, SourceDataError, TimeoutError):
                self.combo_books[instrument_name].invalidate("COMBO_LAYER_REQUEST_FAILURE")
                self._subscribed_combo_names.discard(instrument_name)
                self._failed_combo_subscriptions.add(instrument_name)
                self._mark_layer_two_unknown()
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
            continuation = _OptionCatalogContinuation(self._option_lifecycle_generation)
            self._option_catalog_continuations.append(continuation)
            try:
                metadata = await self._request_public(
                    client,
                    "public/get_instrument",
                    {"instrument_name": instrument_name},
                )
                stale = self._option_continuation_is_stale(
                    continuation,
                    response_ingress_seq=self._last_rpc_ingress_seq,
                )
            except (PublicRequestError, TimeoutError):
                self.option_catalog.mark_incomplete()
                return
            finally:
                self._option_catalog_continuations.remove(continuation)
            if stale:
                self.option_catalog.mark_incomplete()
                return
            self._accept_causal_fact()
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
            await self._coalesced_combo_refresh(client)

    async def _recover_option_catalog(self, client: PublicClient) -> None:
        continuation = _OptionCatalogContinuation(self._option_lifecycle_generation)
        self._option_catalog_continuations.append(continuation)
        try:
            payloads = require_list(
                await self._request_public(
                    client,
                    "public/get_instruments",
                    {"currency": "USDC", "kind": "option", "expired": False},
                ),
                "public/get_instruments result",
            )
            options, complete = self._parse_option_snapshot(payloads)
            stale = self._option_continuation_is_stale(
                continuation,
                response_ingress_seq=self._last_rpc_ingress_seq,
            )
        except (SourceDataError, PublicRequestError, TimeoutError):
            self.option_catalog.mark_incomplete()
            return
        finally:
            self._option_catalog_continuations.remove(continuation)
        if stale:
            self.option_catalog.mark_incomplete()
            return
        self._accept_causal_fact()
        if complete:
            self.catalog_options = options
        else:
            self.catalog_options.update(options)
        self.option_catalog.source_complete = complete
        self.option_catalog.complete = complete
        await self._sync_option_membership(client)

    def _option_continuation_is_stale(
        self,
        continuation: _OptionCatalogContinuation,
        *,
        response_ingress_seq: int | None,
    ) -> bool:
        if not continuation.dirty and continuation.generation == self._option_lifecycle_generation:
            return False
        if (
            continuation.has_unsequenced_lifecycle
            or response_ingress_seq is None
            or continuation.earliest_lifecycle_ingress_seq is None
        ):
            return True
        return continuation.earliest_lifecycle_ingress_seq < response_ingress_seq

    async def _recover_incomplete_catalogs(self, client: PublicClient) -> None:
        if not self.option_catalog.complete:
            await self._recover_option_catalog(client)
        if not self.combo_catalog.complete:
            await self._coalesced_combo_refresh(client)
        elif self._failed_combo_subscriptions:
            await self._sync_combo_subscriptions(client)

    async def _refresh_combo_catalog(self, client: PublicClient) -> None:
        try:
            payloads = require_list(
                await self._request_public(client, "public/get_combos", {"currency": "USDC"}),
                "public/get_combos result",
            )
            self._accept_causal_fact()
            self.combo_catalog.complete = await self._replace_combos(client, payloads)
        except (SourceDataError, PublicRequestError, TimeoutError):
            self.combo_catalog.mark_incomplete()
            for book in self.combo_books.values():
                book.invalidate("COMBO_CATALOG_UNAVAILABLE")
            for tracker in self.trackers.values():
                if tracker.detector_state is DetectorState.ANOMALY_ACTIVE:
                    self._record_atomic_transition(
                        tracker,
                        PublicAtomicQuoteState.UNKNOWN,
                        band_id=tracker.activation_band_id,
                    )
            return
        await self._sync_combo_subscriptions(client)
        for tracker in self.trackers.values():
            if tracker.episode_id is not None:
                await self._evaluate_atomic(tracker)

    async def _coalesced_combo_refresh(self, client: PublicClient) -> None:
        existing = self._combo_refresh_task
        if existing is not None:
            if existing is asyncio.current_task():
                return
            await existing
            return
        self._combo_refresh_dirty = False
        starting_generation = self._combo_lifecycle_generation

        async def refresh_with_one_trailing_pass() -> None:
            await self._refresh_combo_catalog(client)
            if self._combo_refresh_dirty or self._combo_lifecycle_generation != starting_generation:
                self._combo_refresh_dirty = False
                await self._refresh_combo_catalog(client)

        task = asyncio.create_task(refresh_with_one_trailing_pass())
        self._combo_refresh_task = task
        try:
            await task
        finally:
            if self._combo_refresh_task is task:
                self._combo_refresh_task = None

    async def _evaluate_all(
        self,
        client: PublicClient,
        *,
        evaluation_monotonic_ms: int | None = None,
        boundary_observation_eligible: bool = True,
        observation_reason: str | None = None,
    ) -> None:
        await self._evaluate_batch(
            client,
            tuple(self.options),
            evaluation_monotonic_ms=evaluation_monotonic_ms,
            boundary_observation_eligible=boundary_observation_eligible,
            observation_reason=observation_reason,
        )

    async def _evaluate_one(
        self,
        client: PublicClient,
        instrument_name: str,
        *,
        evaluation_monotonic_ms: int | None = None,
        boundary_observation_eligible: bool = True,
        observation_reason: str | None = None,
    ) -> None:
        await self._evaluate_batch(
            client,
            (instrument_name,),
            evaluation_monotonic_ms=evaluation_monotonic_ms,
            boundary_observation_eligible=boundary_observation_eligible,
            observation_reason=observation_reason,
        )

    async def _evaluate_batch(
        self,
        client: PublicClient,
        instrument_names: tuple[str, ...],
        *,
        evaluation_monotonic_ms: int | None = None,
        boundary_observation_eligible: bool = True,
        observation_reason: str | None = None,
    ) -> None:
        if self.clock is None:
            return
        known_at_ms = (
            evaluation_monotonic_ms if evaluation_monotonic_ms is not None else _monotonic_ms()
        )
        trusted_time = self.clock.interval_at(known_at_ms)
        index_window = self.index.current_window(
            self.policy.largest_lookback_minutes,
            trusted_time_lower_ms=trusted_time.lower_ms,
        )
        global_index_reason = (
            index_window.reason
            if index_window.reason in {"INDEX_BASELINE_STALE", "INDEX_BASELINE_GAP"}
            else None
        )
        global_index_gap = global_index_reason is not None
        evaluation_names = tuple(self.options) if global_index_gap else instrument_names
        snapshot = ScopeSnapshot(
            causal_seq=self.causal_seq,
            trusted_time=trusted_time,
            clock_revision=self._clock_revision,
            instrument_names=evaluation_names,
            boundary_observation_eligible=boundary_observation_eligible,
            observation_reason=observation_reason,
        )
        prepared: list[
            tuple[
                OptionInstrument,
                CurrentEvaluation,
                tuple[object, ...],
                bool,
                str | None,
                TrackerState,
                str | None,
            ]
        ] = []
        evaluated: list[tuple[OptionInstrument, EvaluationResult, TrackerState, str | None]] = []
        state_changed = False
        for instrument_name in evaluation_names:
            instrument = self.options.get(instrument_name)
            if instrument is None:
                continue
            fingerprint, observation_fingerprint = self._fingerprints(
                instrument,
                snapshot,
                index_window_reason=index_window.reason,
                index_window_prices=index_window.prices,
            )
            if not global_index_gap and self._last_fingerprints.get(instrument_name) == fingerprint:
                continue
            tracker = self.trackers[instrument_name]
            previous_state = tracker.state
            previous_episode_id = tracker.episode_id
            observation_eligible = (
                snapshot.boundary_observation_eligible
                and self._last_observation_fingerprints.get(instrument_name)
                != observation_fingerprint
            )
            current_observation_reason = (
                None
                if observation_eligible
                else snapshot.observation_reason or "DUPLICATE_REDUCED_STATE"
            )
            current_applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted_time,
                option_type=instrument.option_type,
            )
            current_band_id = (
                current_applicability.band.band_id
                if current_applicability.band is not None
                else None
            )
            if not self.platform.usable:
                current = CurrentEvaluation(
                    disposition=CurrentDisposition.UNKNOWN,
                    reason=self.platform.reason,
                    known_evaluation=False,
                    full_formula_evaluation=False,
                    band_id=current_band_id,
                    continuity_gap=True,
                )
            elif global_index_gap:
                current = CurrentEvaluation(
                    disposition=CurrentDisposition.UNKNOWN,
                    reason=global_index_reason,
                    known_evaluation=False,
                    full_formula_evaluation=False,
                    band_id=current_band_id,
                    continuity_gap=True,
                )
            else:
                current = calculate_current_evaluation(
                    policy=self.policy,
                    instrument=instrument,
                    trusted_time=trusted_time,
                    causal_seq=self.causal_seq,
                    option_book=self.option_books.get(instrument_name),
                    ticker=self.tickers.get(instrument_name),
                    causal_closes=index_window.prices,
                    baseline_unavailable_reason=(index_window.reason or "INDEX_BASELINE_WARMUP"),
                )
            prepared.append(
                (
                    instrument,
                    current,
                    observation_fingerprint,
                    observation_eligible,
                    current_observation_reason,
                    previous_state,
                    previous_episode_id,
                )
            )

        for (
            instrument,
            current,
            observation_fingerprint,
            observation_eligible,
            current_observation_reason,
            previous_state,
            previous_episode_id,
        ) in prepared:
            instrument_name = instrument.instrument_name
            tracker = self.trackers[instrument_name]
            transition = apply_current_evaluation(
                tracker=tracker,
                current=current,
                causal_seq=self.causal_seq,
                observation_eligible=observation_eligible,
            )
            result = EvaluationResult(
                detector_state=tracker.detector_state,
                reason=current.reason,
                known_evaluation=current.known_evaluation,
                full_formula_evaluation=current.full_formula_evaluation,
                band_id=current.band_id,
                transition=transition,
                observation_eligible=observation_eligible,
                observation_reason=current_observation_reason,
                calculation=current.calculation,
                current_evaluation=current,
            )
            self._last_fingerprints[instrument_name] = self._fingerprints(
                instrument,
                snapshot,
                index_window_reason=index_window.reason,
                index_window_prices=index_window.prices,
            )[0]
            if observation_eligible:
                self._last_observation_fingerprints[instrument_name] = observation_fingerprint
            self.results[instrument_name] = result
            if (
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                and result.observation_eligible
            ):
                self._last_detector_causal_seq[instrument_name] = self.causal_seq
            evaluated.append((instrument, result, previous_state, previous_episode_id))
            state_changed = state_changed or result.transition.state_changed

        for instrument, result, previous_state, previous_episode_id in evaluated:
            tracker = self.trackers[instrument.instrument_name]
            self._record_evaluation(instrument, result)
            self._record_band_timing(
                previous_state=previous_state,
                previous_episode_id=previous_episode_id,
                tracker=tracker,
                boundary_monotonic_ms=known_at_ms,
            )
            self._record_episode_end(
                result.transition.ended_episode,
                boundary_monotonic_ms=known_at_ms,
            )
            if (
                result.known_evaluation
                and result.observation_eligible
                and tracker.detector_state is DetectorState.ANOMALY_ACTIVE
            ):
                if tracker.episode_id is not None:
                    self._episode_last_trusted_boundary_ms[tracker.episode_id] = known_at_ms

        if global_index_reason is not None:
            self.index.gap()
            self._last_fingerprints.clear()
            self._last_observation_fingerprints.clear()
            self.platform.reason = global_index_reason

        by_scope: dict[
            tuple[int, OptionType, str], list[tuple[OptionInstrument, EvaluationResult]]
        ] = {}
        for instrument, result, _previous_state, _previous_episode_id in evaluated:
            if result.band_id is None:
                continue
            key = (
                instrument.expiration_timestamp_ms,
                instrument.option_type,
                result.band_id,
            )
            by_scope.setdefault(key, []).append((instrument, result))

        for scope_results in by_scope.values():
            representative = scope_results[0][0]
            aggregate = self._scope_aggregate(representative, trusted_time)
            for instrument, result in scope_results:
                if result.transition.activated_episode_id is not None:
                    self._record_activation(
                        instrument,
                        result,
                        aggregate.coverage or DetectorCoverage.DEGRADED,
                        trusted_time,
                        boundary_monotonic_ms=known_at_ms,
                    )
            if any(result.observation_eligible for _instrument, result in scope_results):
                self._record_aggregate(
                    representative,
                    scope_results[0][1].band_id,
                    aggregate,
                    full_formula_witness=any(
                        result.full_formula_evaluation and result.observation_eligible
                        for _instrument, result in scope_results
                    ),
                )

        for instrument, result, _previous_state, _previous_episode_id in evaluated:
            tracker = self.trackers[instrument.instrument_name]
            if tracker.state is TrackerState.BAND_SUSPENDED:
                self._record_atomic_transition(
                    tracker,
                    PublicAtomicQuoteState.NOT_EVALUATED,
                    band_id=result.band_id or tracker.activation_band_id,
                )
            elif (
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                and tracker.episode_id is not None
                and tracker.episode_id not in self.atomic_states
            ):
                self._record_atomic_transition(
                    tracker,
                    PublicAtomicQuoteState.UNKNOWN,
                    band_id=result.band_id or tracker.activation_band_id,
                )
        self._update_coverage(monotonic_ms=known_at_ms)
        if global_index_reason is not None:
            try:
                await self._unsubscribe_public(client, [INDEX_CHANNEL])
                await self._subscribe_public(client, [INDEX_CHANNEL])
            except (PublicRequestError, SourceDataError, TimeoutError) as exc:
                raise ContinuityGap("index resubscription failed") from exc
            self.index.start_continuous_coverage(trusted_time.lower_ms)
            if self.platform.usable:
                self.platform.reason = "USABLE"
        if state_changed:
            await self._sync_combo_subscriptions(client)
        for instrument, _result, _previous_state, _previous_episode_id in evaluated:
            tracker = self.trackers[instrument.instrument_name]
            if tracker.detector_state is DetectorState.ANOMALY_ACTIVE:
                await self._evaluate_atomic(tracker)

    def _fingerprints(
        self,
        instrument: OptionInstrument,
        snapshot: ScopeSnapshot,
        *,
        index_window_reason: str | None,
        index_window_prices: tuple[object, ...] | None,
    ) -> tuple[tuple[object, ...], tuple[object, ...]]:
        book = self.option_books.get(instrument.instrument_name)
        ticker = self.tickers.get(instrument.instrument_name)
        applicability = classify_time_applicability(
            self.policy,
            expiration_timestamp_ms=instrument.expiration_timestamp_ms,
            trusted_time=snapshot.trusted_time,
            option_type=instrument.option_type,
        )
        consumed_prices = index_window_prices
        if applicability.band is not None and index_window_prices is not None:
            close_count = max(applicability.band.lookbacks_minutes) + 1
            consumed_prices = index_window_prices[-close_count:]
        baseline_identity: tuple[object, ...] = (
            (
                self.index.sealed[-1].minute_start_ms,
                consumed_prices,
            )
            if consumed_prices is not None and self.index.sealed
            else (index_window_reason,)
        )
        observation = detector_observation_identity(
            policy=self.policy,
            instrument=instrument,
            trusted_time=snapshot.trusted_time,
            option_book=book,
            ticker=ticker,
            baseline_identity=baseline_identity,
        )
        current = (
            self.platform.usable,
            snapshot.clock_revision,
            instrument.amount,
            (book.state, book.reason) if book is not None else None,
            observation,
        )
        return current, observation

    def _scope_aggregate(
        self, instrument: OptionInstrument, trusted_time: TimeInterval
    ) -> AggregateDetectorResult:
        applicability = classify_time_applicability(
            self.policy,
            expiration_timestamp_ms=instrument.expiration_timestamp_ms,
            trusted_time=trusted_time,
            option_type=instrument.option_type,
        )
        band = applicability.band
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
        if result.observation_eligible or result.transition.state_changed:
            if result.reason is not None and not result.known_evaluation:
                self._record_unknown_reason(instrument.instrument_name, result.reason)
            else:
                self._last_unknown_reason[instrument.instrument_name] = None
        if not result.observation_eligible:
            return
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
        band_id: str | None,
        aggregate: AggregateDetectorResult,
        *,
        full_formula_witness: bool,
    ) -> None:
        if band_id is None or aggregate.coverage is not DetectorCoverage.COMPLETE:
            return
        scope = self._scope_counter(instrument.option_type, band_id)
        scope.complete_aggregate_detector_evaluation_count += 1
        if full_formula_witness:
            scope.complete_aggregate_with_full_formula_evaluation_count += 1

    def _record_activation(
        self,
        instrument: OptionInstrument,
        result: EvaluationResult,
        coverage: DetectorCoverage,
        trusted_time: TimeInterval,
        *,
        boundary_monotonic_ms: int | None = None,
    ) -> None:
        episode_id = result.transition.activated_episode_id
        calculation = result.calculation
        if episode_id is None or calculation is None:
            raise RuntimeError("activation requires a full detector calculation")
        scope = self._scope_counter(instrument.option_type, calculation.band.band_id)
        scope.distinct_anomaly_episode_count += 1
        scope.anomaly_activation_transition_count += 1
        boundary_ms = (
            boundary_monotonic_ms if boundary_monotonic_ms is not None else _monotonic_ms()
        )
        self._episode_active_segment_started_ms[episode_id] = boundary_ms
        self._episode_active_accumulated_ms[episode_id] = 0
        self._episode_last_trusted_boundary_ms[episode_id] = boundary_ms
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
        abandoned_failures = self._failed_combo_subscriptions - (
            needed | self._subscribed_combo_names
        )
        for instrument_name in abandoned_failures:
            self.combo_books.pop(instrument_name, None)
        self._failed_combo_subscriptions.difference_update(abandoned_failures)
        additions = sorted(needed - self._subscribed_combo_names)
        removals = sorted(self._subscribed_combo_names - needed)
        if additions:
            for instrument_name in additions:
                self.combo_books[instrument_name] = ContinuousOrderBook(instrument_name)
            try:
                await self._subscribe_public(client, [book_channel(name) for name in additions])
            except (PublicRequestError, SourceDataError, TimeoutError):
                for instrument_name in additions:
                    self.combo_books[instrument_name].invalidate("COMBO_LAYER_REQUEST_FAILURE")
                    self._failed_combo_subscriptions.add(instrument_name)
                self._mark_layer_two_unknown()
            else:
                self._subscribed_combo_names.update(additions)
                self._failed_combo_subscriptions.difference_update(additions)
        if removals:
            try:
                await self._unsubscribe_public(client, [book_channel(name) for name in removals])
            except (PublicRequestError, SourceDataError, TimeoutError):
                for instrument_name in removals:
                    book = self.combo_books.get(instrument_name)
                    if book is not None:
                        book.invalidate("COMBO_LAYER_REQUEST_FAILURE")
                    self._failed_combo_subscriptions.add(instrument_name)
                self._mark_layer_two_unknown()
            else:
                for instrument_name in removals:
                    self.combo_books.pop(instrument_name, None)
                    self._subscribed_combo_names.discard(instrument_name)
                    self._failed_combo_subscriptions.discard(instrument_name)

    def _mark_layer_two_unknown(self) -> None:
        for tracker in self.trackers.values():
            if tracker.detector_state is DetectorState.ANOMALY_ACTIVE:
                self._record_atomic_transition(
                    tracker,
                    PublicAtomicQuoteState.UNKNOWN,
                    band_id=tracker.activation_band_id,
                )

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
            option_catalog_complete=self.option_catalog.complete,
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
                emitted_key = (tracker.episode_id, combo.instrument_name)
                if emitted_key in self._emitted_atomic_quotes:
                    continue
                combo_book = self.combo_books[combo.instrument_name]
                event = project_atomic_event(
                    AtomicEvidence(
                        code_identity=self.code_identity,
                        runtime_identity=self.runtime_identity,
                        policy_identity=self.policy.identity,
                        episode_identity=tracker.episode_id,
                        detector_causal_seq=self._last_detector_causal_seq.get(
                            tracker.instrument_name,
                            tracker.activation_causal_seq or self.causal_seq,
                        ),
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
                self._emitted_atomic_quotes.add(emitted_key)

    def _record_episode_end(
        self,
        ended: EpisodeEnd | None,
        *,
        boundary_monotonic_ms: int | None = None,
    ) -> None:
        if ended is None:
            return
        observed_boundary_ms = (
            boundary_monotonic_ms if boundary_monotonic_ms is not None else _monotonic_ms()
        )
        if ended.reason in {
            EpisodeEndReason.UNKNOWN_AT_GAP,
            EpisodeEndReason.UNKNOWN_DETECTOR,
            EpisodeEndReason.OUT_OF_BASELINE_SCOPE,
        }:
            end_boundary_ms = self._episode_last_trusted_boundary_ms.get(
                ended.episode_id,
                observed_boundary_ms,
            )
        else:
            end_boundary_ms = observed_boundary_ms
        self._episode_end_counts[ended.reason.value] += 1
        suspended_started = self._band_suspended_started_ms.pop(ended.episode_id, None)
        if suspended_started is not None:
            self._band_suspended_duration_ms += max(0, end_boundary_ms - suspended_started)
        active_started = self._episode_active_segment_started_ms.pop(ended.episode_id, None)
        if active_started is not None:
            self._episode_active_accumulated_ms[ended.episode_id] += max(
                0, end_boundary_ms - active_started
            )
        self._episode_last_trusted_boundary_ms.pop(ended.episode_id, None)
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
        boundary_monotonic_ms: int | None = None,
    ) -> None:
        if previous_episode_id is None:
            return
        now = boundary_monotonic_ms if boundary_monotonic_ms is not None else _monotonic_ms()
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

    def _record_unknown_reason(self, instrument_name: str, reason: str) -> None:
        if self._last_unknown_reason.get(instrument_name) == reason:
            return
        self._unknown_counts[reason] += 1
        self._last_unknown_reason[instrument_name] = reason

    def _accept_causal_fact(self) -> int:
        self.causal_seq += 1
        return self.causal_seq

    def _mark_tracker_unknown(
        self,
        tracker: EpisodeTracker,
        *,
        reason: str,
        continuity_gap: bool = False,
    ) -> TrackerTransition:
        transition = tracker.unknown(
            reason=reason,
            causal_seq=self.causal_seq,
            continuity_gap=continuity_gap,
        )
        self._record_unknown_reason(tracker.instrument_name, reason)
        return transition

    def _invalidate_all(self, reason: str) -> None:
        reason = _canonical_unknown_reason(reason)
        self.platform.post_status_bootstrap_complete = False
        self.platform.reason = reason
        self.index.gap()
        for book in (*self.option_books.values(), *self.combo_books.values()):
            book.invalidate(reason)
        for tracker in self.trackers.values():
            transition = self._mark_tracker_unknown(
                tracker,
                reason=reason,
                continuity_gap=True,
            )
            self._record_episode_end(transition.ended_episode)
        self._last_fingerprints.clear()
        self._last_observation_fingerprints.clear()
        self._update_coverage()

    def _update_coverage(self, *, monotonic_ms: int | None = None) -> None:
        now = monotonic_ms if monotonic_ms is not None else _monotonic_ms()
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
        scoped: list[OptionInstrument] = []
        unresolved_time_boundary = False
        for instrument in self.options.values():
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            if applicability.classification is TimeApplicability.IN_BAND:
                scoped.append(instrument)
            elif applicability.classification in {
                TimeApplicability.ADJACENT_BAND_BOUNDARY,
                TimeApplicability.MONITOR_BOUNDARY,
            }:
                unresolved_time_boundary = True
        if not scoped:
            self._coverage.transition(
                CoverageState.UNKNOWN
                if unresolved_time_boundary
                else CoverageState.NO_APPLICABLE_SCOPE,
                now,
            )
            return
        states = [self.trackers[item.instrument_name].detector_state for item in scoped]
        if unresolved_time_boundary:
            states.append(DetectorState.UNKNOWN)
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
            notification_queue_lag_limit_ms=MAX_NOTIFICATION_QUEUE_LAG_MS,
            max_notification_queue_lag_ms=self._max_notification_queue_lag_ms,
        )
        return self.writer.write_summary(summary)


def _canonical_unknown_reason(reason: str) -> str:
    if (
        reason == "CONNECTION_CLOSED"
        or reason == "NOTIFICATION_QUEUE_LAG"
        or reason.startswith("SESSION_")
    ):
        return "SESSION_GAP"
    if reason in {"PROTOCOL_INCOMPATIBILITY", "FATAL_PROTOCOL_INCOMPATIBILITY"}:
        return "FATAL_PROTOCOL_INCOMPATIBILITY"
    return reason


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
    reconnect_attempt = 0
    while not event.is_set():
        try:
            async with DeribitPublicClient() as client:
                return await runtime.run(client, event)
        except PublicProtocolIncompatibility:
            runtime.prepare_reconnect("PROTOCOL_INCOMPATIBILITY")
            raise
        except ContinuityGap:
            runtime.prepare_reconnect(
                runtime.platform.reason
                if runtime.platform.reason
                in {
                    "CLOCK_GAP",
                    "INDEX_GAP",
                    "INDEX_BASELINE_STALE",
                    "INDEX_BASELINE_GAP",
                }
                else "CLOCK_OR_INDEX_GAP"
            )
        except (PublicRequestError, SourceDataError, TimeoutError):
            runtime.prepare_reconnect("TRANSIENT_PUBLIC_REQUEST_FAILURE")
        except (
            ConnectionError,
            OSError,
            PublicSessionError,
            WebSocketException,
        ) as exc:
            runtime.prepare_reconnect(
                runtime.platform.reason
                if runtime.platform.reason
                in {
                    "PLATFORM_MAINTENANCE",
                    "PUBLIC_METHODS_DENIED",
                    "RELEVANT_PLATFORM_LOCK",
                }
                else f"SESSION_RECONNECT:{type(exc).__name__}"
            )
        except PublicProtocolError:
            runtime.prepare_reconnect("FATAL_PROTOCOL_INCOMPATIBILITY")
            raise
        if not event.is_set():
            if runtime._session_established:
                reconnect_attempt = 0
            await asyncio.sleep(reconnect_delay_seconds(reconnect_attempt))
            reconnect_attempt += 1
    return await runtime._clean_stop(None)


def reconnect_delay_seconds(
    attempt: int,
    *,
    jitter_fraction: float | None = None,
) -> float:
    if attempt < 0:
        raise ValueError("reconnect attempt must be non-negative")
    jitter = random.random() if jitter_fraction is None else jitter_fraction
    if not 0 <= jitter <= 1:
        raise ValueError("jitter_fraction must be within [0, 1]")
    base_seconds = min(30.0, float(2 ** min(attempt, 30)))
    return base_seconds * (0.8 + 0.4 * jitter)


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

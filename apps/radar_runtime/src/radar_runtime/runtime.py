from __future__ import annotations

import asyncio
import random
import signal
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from market_monitor import (
    ContinuityGap,
    ContinuousOrderBook,
    IndexMinuteReducer,
    IndexTailStatus,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import (
    COMBO_LIFECYCLE_CHANNEL,
    INDEX_CHANNEL,
    OPTION_LIFECYCLE_CHANNEL,
    PLATFORM_CHANNELS,
    CatalogBootstrap,
    PlatformReadiness,
    book_channel,
    subscription_batches,
    ticker_channel,
    validate_subscription_ack,
)
from market_monitor.types import (
    SourceDataError,
    require_bool,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from options_domain import (
    FINAL_INSTRUMENT_LIFECYCLE_STATES,
    INSTRUMENT_LIFECYCLE_STATES,
    TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES,
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
    aggregate_detector,
)
from short_vol_radar.evidence import (
    CHANNEL_CLASSES,
    CORE_SOURCE_NAMES,
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
    MAX_PENDING_INBOUND_FRAMES,
    DeribitPublicClient,
    InboundEnvelope,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicSessionError,
)


class PublicClient(Protocol):
    session_epoch: int
    queue_high_water_frames: int
    overflow_count: int
    received_frame_count: int

    async def send_request(
        self,
        *,
        request_id: int,
        method: str,
        params: dict[str, object],
        responding_to_test_request: bool = False,
    ) -> None: ...

    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope: ...


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
class ScopeCurrent:
    instrument: OptionInstrument
    current: CurrentEvaluation
    observation_identity: tuple[object, ...]
    index_tail_identity: tuple[object, ...] | None
    observation_eligible: bool
    previous_tracker_state: TrackerState
    previous_episode_id: str | None


@dataclass(frozen=True)
class ScopeSnapshot:
    boundary: FactBoundary
    trusted_time: TimeInterval
    clock_revision: int
    current: tuple[ScopeCurrent, ...]
    boundary_countable: bool
    acceptance_eligible: bool
    observation_reason: str | None


class ChannelState(StrEnum):
    UNSUBSCRIBED = "UNSUBSCRIBED"
    SUBSCRIBE_PENDING = "SUBSCRIBE_PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNSUBSCRIBE_PENDING = "UNSUBSCRIBE_PENDING"
    RETIRED = "RETIRED"


class RpcPurpose(StrEnum):
    SET_HEARTBEAT = "SET_HEARTBEAT"
    SUBSCRIBE_CHANNELS = "SUBSCRIBE_CHANNELS"
    UNSUBSCRIBE_CHANNELS = "UNSUBSCRIBE_CHANNELS"
    PLATFORM_STATUS = "PLATFORM_STATUS"
    CLOCK_BOOTSTRAP = "CLOCK_BOOTSTRAP"
    CLOCK_REFRESH = "CLOCK_REFRESH"
    OPTION_CATALOG = "OPTION_CATALOG"
    OPTION_METADATA = "OPTION_METADATA"
    COMBO_CATALOG = "COMBO_CATALOG"
    COMBO_METADATA = "COMBO_METADATA"
    HEARTBEAT_TEST = "HEARTBEAT_TEST"


POST_STATUS_BOOTSTRAP_PURPOSES = frozenset(
    {
        RpcPurpose.CLOCK_BOOTSTRAP,
        RpcPurpose.OPTION_CATALOG,
        RpcPurpose.COMBO_CATALOG,
    }
)


class FailureScope(StrEnum):
    SESSION = "SESSION"
    CLOCK_INDEX = "CLOCK_INDEX"
    OPTION = "OPTION"
    OPTION_CATALOG = "OPTION_CATALOG"
    COMBO_LAYER = "COMBO_LAYER"
    FATAL_PROTOCOL = "FATAL_PROTOCOL"


@dataclass(frozen=True)
class FactBoundary:
    session_epoch: int
    ingress_seq: int
    received_monotonic_ms: int
    causal_seq: int


@dataclass(frozen=True)
class PendingRpc:
    request_id: int
    purpose: RpcPurpose
    method: str
    params: dict[str, object]
    session_epoch: int
    scope: str
    generation: int | None
    origin_boundary: FactBoundary
    deadline_monotonic_ms: int
    failure_scope: FailureScope


@dataclass
class RuntimeDiagnostics:
    wire_received_envelope_count: int = 0
    received_envelope_count: int = 0
    reduced_envelope_count: int = 0
    ingress_gap_or_duplicate_count: int = 0
    retired_epoch_frame_count: int = 0
    queue_high_water_frames: int = 0
    max_receive_to_reduce_lag_ms: int = 0
    overflow_count: int = 0
    late_response_count: int = 0
    combo_authoritative_refresh_attempt_count: int = 0
    reconnect_count: int = 0
    session_gap_count: int = 0
    index_gap_count: int = 0
    index_resubscribe_count: int = 0
    option_channel_resync_count: int = 0
    clock_refresh_attempt_count: int = 0
    clock_refresh_success_count: int = 0
    clock_refresh_failure_count: int = 0
    option_catalog_refresh_success_count: int = 0
    option_catalog_refresh_failure_count: int = 0
    combo_authoritative_refresh_success_count: int = 0
    combo_authoritative_refresh_failure_count: int = 0
    peak_subscribed_instrument_count: int = 0
    peak_subscribed_channel_count: int = 0
    rpc_request_count: Counter[str] = field(default_factory=Counter)
    rpc_success_count: Counter[str] = field(default_factory=Counter)
    rpc_error_count: Counter[str] = field(default_factory=Counter)
    rpc_late_count: Counter[str] = field(default_factory=Counter)
    rpc_rate_limit_count: Counter[str] = field(default_factory=Counter)
    rpc_latency_count: Counter[str] = field(default_factory=Counter)
    rpc_latency_sum: Counter[str] = field(default_factory=Counter)
    rpc_latency_max: Counter[str] = field(default_factory=Counter)
    channel_received_count: Counter[str] = field(default_factory=Counter)
    channel_processed_count: Counter[str] = field(default_factory=Counter)
    heartbeat_test_request_count: int = 0
    heartbeat_public_test_success_count: int = 0
    heartbeat_public_test_error_count: int = 0
    heartbeat_latency_count: int = 0
    heartbeat_latency_sum: int = 0
    heartbeat_latency_max: int = 0
    source_observed_count: Counter[str] = field(default_factory=Counter)
    source_valid_count: Counter[str] = field(default_factory=Counter)
    source_invalid_count: Counter[str] = field(default_factory=Counter)
    source_consumed_fields: dict[str, set[tuple[str, str]]] = field(default_factory=dict)


@dataclass
class _ChannelSlot:
    state: ChannelState = ChannelState.UNSUBSCRIBED
    generation: int = 0
    desired_subscribed: bool = False
    resync_requested: bool = False
    retry_after_ms: int | None = None
    retry_failure_scope: FailureScope = FailureScope.SESSION


@dataclass
class _HeldSubscriptionFrame:
    envelope: InboundEnvelope
    channel: str
    generation: int | None
    eligible: bool


@dataclass(frozen=True)
class _TickerCurrentnessLatch:
    generation: int
    source_timestamp_ms: int
    reason: str


class RadarReducer:
    """Single synchronous owner for one public Radar session's reduced facts."""

    def __init__(
        self,
        *,
        policy: RadarPolicy,
        code_identity: str,
        evidence_writer: EvidenceWriter,
        runtime_identity: str,
    ) -> None:
        self.policy = policy
        self.code_identity = code_identity
        self.writer = evidence_writer
        self.runtime_identity = runtime_identity
        self.platform = PlatformReadiness()
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options: dict[str, OptionInstrument] = {}
        self.options: dict[str, OptionInstrument] = {}
        self.combos: dict[str, ComboInstrument] = {}
        self.option_books: dict[str, ContinuousOrderBook] = {}
        self.combo_books: dict[str, ContinuousOrderBook] = {}
        self.tickers: dict[str, TickerState] = {}
        self._ticker_generations: dict[str, int] = {}
        self._ticker_currentness_latches: dict[str, _TickerCurrentnessLatch] = {}
        self._ticker_unavailable: dict[str, tuple[str, bool]] = {}
        self.trackers: dict[str, EpisodeTracker] = {}
        self.results: dict[str, EvaluationResult] = {}
        self.atomic_states: dict[str, PublicAtomicQuoteState] = {}
        self.aggregate_results: dict[
            tuple[int, OptionType, str],
            AggregateDetectorResult,
        ] = {}
        self.index = IndexMinuteReducer(policy.largest_lookback_minutes)
        self.clock: TrustedClock | None = None
        self.diagnostics = RuntimeDiagnostics()
        self.pending_rpcs: dict[int, PendingRpc] = {}
        self._channels: dict[str, _ChannelSlot] = {}
        self._held_subscription_frames: list[_HeldSubscriptionFrame] = []
        self._held_subscription_frame_count = 0
        self._session_epoch: int | None = None
        self._retired_epochs: set[int] = set()
        self._last_ingress_seq = 0
        self._last_boundary_monotonic_ms = 0
        self._last_inbound_received_ms = 0
        self._causal_seq = 0
        self._clock_revision = 0
        self._last_time_currentness_token: tuple[object, ...] | None = None
        self._next_request_id = 1
        self._next_channel_generation = 1
        self._commands: list[PendingRpc] = []
        self._bootstrap_queries_issued = False
        self._platform_status_ingress_seq: int | None = None
        self._post_status_bootstrap_successes: set[RpcPurpose] = set()
        self._option_lifecycle_revision: Counter[str] = Counter()
        self._option_lifecycle_state: dict[str, str] = {}
        self._option_metadata_pending: dict[str, int] = {}
        self._option_lifecycle_unavailable: dict[str, str] = {}
        self._option_positive_scope_safe = True
        self._combo_refresh_request_id: int | None = None
        self._combo_refresh_generation = 0
        self._combo_lifecycle_revision = 0
        self._combo_refresh_origin_revision: dict[int, int] = {}
        self._combo_summaries: dict[str, dict[str, object]] = {}
        self._combo_summary_fingerprints: dict[str, tuple[object, ...]] = {}
        self._combo_metadata_revisions: Counter[str] = Counter()
        self._combo_metadata_pending: dict[str, int] = {}
        self._combo_lifecycle_state: dict[str, str] = {}
        self._coverage = CoverageLedger(_monotonic_ms())
        self._transport_enqueued_by_epoch: dict[int, int] = {}
        self._transport_overflow_by_epoch: dict[int, int] = {}
        self._scope_counts: dict[tuple[str, OptionType, str], ScopeCounts] = {}
        self._unknown_counts: Counter[str] = Counter()
        self._episode_end_counts: Counter[str] = Counter()
        self._known_active_duration_ms: Counter[str] = Counter()
        self._atomic_transition_counts: Counter[str] = Counter()
        self._band_suspended_duration_ms = 0
        self._band_suspended_started_ms: int | None = None
        self._first_joint_witness_ms: int | None = None
        self._last_observation_identity: dict[str, tuple[object, ...]] = {}
        self._last_index_tail_identity: dict[str, tuple[object, ...]] = {}
        self._last_unknown_reason: dict[str, str | None] = {}
        self._last_detector_causal_seq: dict[str, int] = {}
        self._emitted_atomic_quotes: set[tuple[str, str]] = set()
        self._episode_started_ms: dict[str, int] = {}
        self._episode_last_trusted_ms: dict[str, int] = {}
        self._episode_pause_started_ms: dict[str, int] = {}
        self._episode_paused_duration_ms: Counter[str] = Counter()
        self._episode_option_type: dict[str, OptionType] = {}
        self._subscribed_combo_names: set[str] = set()
        self._index_resubscribe_pending = False
        self._index_coverage_generation: int | None = None
        self._index_gap_active = False
        self._next_clock_refresh_ms: int | None = None
        self._next_option_catalog_recovery_ms: int | None = None
        self._next_combo_catalog_recovery_ms: int | None = None

    def begin_session(
        self,
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[PendingRpc, ...]:
        if session_epoch <= 0 or monotonic_ms < 0:
            raise ValueError("session identity must be positive")
        if self._session_epoch is not None:
            self.diagnostics.reconnect_count += 1
            self._retire_current_epoch()
        else:
            self._coverage = CoverageLedger(monotonic_ms)
        self._session_epoch = session_epoch
        self._last_ingress_seq = 0
        self._last_boundary_monotonic_ms = monotonic_ms
        self._last_inbound_received_ms = monotonic_ms
        self._bootstrap_queries_issued = False
        self._platform_status_ingress_seq = None
        self._post_status_bootstrap_successes.clear()
        self._channels.clear()
        self._held_subscription_frames.clear()
        self._held_subscription_frame_count = 0
        self.pending_rpcs.clear()
        self.platform = PlatformReadiness()
        self.platform.start_epoch(session_epoch)
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options.clear()
        self.options.clear()
        self.combos.clear()
        self.option_books.clear()
        self.combo_books.clear()
        self.tickers.clear()
        self._ticker_generations.clear()
        self._ticker_currentness_latches.clear()
        self._ticker_unavailable.clear()
        self.results.clear()
        self.atomic_states.clear()
        self.aggregate_results.clear()
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock = None
        self._last_time_currentness_token = None
        self._option_lifecycle_revision.clear()
        self._option_lifecycle_state.clear()
        self._option_metadata_pending.clear()
        self._option_lifecycle_unavailable.clear()
        self._option_positive_scope_safe = True
        self._combo_refresh_request_id = None
        self._combo_lifecycle_revision = 0
        self._combo_refresh_origin_revision.clear()
        self._combo_summaries.clear()
        self._combo_summary_fingerprints.clear()
        self._combo_metadata_revisions.clear()
        self._combo_metadata_pending.clear()
        self._combo_lifecycle_state.clear()
        self._last_observation_identity.clear()
        self._last_index_tail_identity.clear()
        self._subscribed_combo_names.clear()
        self._index_resubscribe_pending = False
        self._index_coverage_generation = None
        self._index_gap_active = False
        self._next_clock_refresh_ms = (
            monotonic_ms + self.policy.runtime_limits.clock_refresh_interval_ms
        )
        self._next_option_catalog_recovery_ms = None
        self._next_combo_catalog_recovery_ms = None
        self._commands = []
        boundary = FactBoundary(session_epoch, 0, monotonic_ms, self._causal_seq)
        self._schedule(
            purpose=RpcPurpose.SET_HEARTBEAT,
            method="public/set_heartbeat",
            params={
                "interval": self.policy.runtime_limits.heartbeat_interval_seconds,
            },
            scope="SESSION",
            generation=None,
            origin_boundary=boundary,
            failure_scope=FailureScope.SESSION,
        )
        return self._take_commands()

    def reduce(
        self,
        envelope: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[PendingRpc, ...]:
        self._commands = []
        self.diagnostics.received_envelope_count += 1
        channel_class = _channel_class(
            envelope,
            combo_names=set(self.combos) | self._subscribed_combo_names,
        )
        self.diagnostics.channel_received_count[channel_class] += 1
        self.diagnostics.reduced_envelope_count += 1
        self.diagnostics.channel_processed_count[channel_class] += 1
        if (
            envelope.session_epoch != self._session_epoch
            or envelope.session_epoch in self._retired_epochs
        ):
            self.diagnostics.retired_epoch_frame_count += 1
            return ()
        lag_ms = processed_monotonic_ms - envelope.received_monotonic_ms
        if lag_ms < 0:
            raise PublicProtocolError("inbound frame receive time is in the future")
        self.diagnostics.max_receive_to_reduce_lag_ms = max(
            self.diagnostics.max_receive_to_reduce_lag_ms,
            lag_ms,
        )
        if lag_ms > self.policy.runtime_limits.notification_queue_lag_deadline_ms:
            self._retire_current_epoch()
            raise PublicSessionError("inbound queue lag deadline exceeded")
        if envelope.ingress_seq != self._last_ingress_seq + 1:
            self.diagnostics.ingress_gap_or_duplicate_count += 1
            self._retire_current_epoch()
            raise PublicSessionError("inbound frame ingress sequence is not continuous")
        self._last_ingress_seq = envelope.ingress_seq
        self._last_inbound_received_ms = max(
            self._last_inbound_received_ms,
            envelope.received_monotonic_ms,
        )
        self._last_boundary_monotonic_ms = max(
            self._last_boundary_monotonic_ms,
            envelope.received_monotonic_ms,
        )
        if "id" in envelope and (
            isinstance(envelope.get("id"), bool) or not isinstance(envelope.get("id"), int)
        ):
            raise PublicProtocolIncompatibility("response id is invalid")
        if isinstance(envelope.get("id"), int):
            self._apply_response(envelope)
        else:
            method = envelope.get("method")
            if method == "heartbeat":
                params = envelope.get("params")
                try:
                    self._apply_heartbeat(envelope)
                except (SourceDataError, ValueError) as exc:
                    self._note_source_shape("heartbeat", params, valid=False)
                    raise PublicProtocolIncompatibility(
                        "heartbeat notification shape is incompatible"
                    ) from exc
                self._note_source_shape("heartbeat", params, valid=True)
            elif method == "subscription":
                try:
                    self._accept_subscription_frame(envelope)
                except (SourceDataError, ValueError) as exc:
                    raise PublicProtocolIncompatibility(
                        "subscription routing shape is incompatible"
                    ) from exc
            elif method == "connection_error":
                self._retire_current_epoch()
                params = envelope.get("params")
                kind = params.get("kind") if isinstance(params, dict) else None
                if kind == "PROTOCOL_INCOMPATIBILITY":
                    raise PublicProtocolIncompatibility(
                        "production-public protocol is incompatible"
                    )
                raise PublicSessionError("production-public connection closed")
            else:
                raise PublicProtocolError("unexpected inbound JSON-RPC frame")
        return self._take_commands()

    def channel_state(self, channel: str) -> ChannelState:
        return self._channels.get(channel, _ChannelSlot()).state

    def business_fingerprint(self) -> tuple[object, ...]:
        return (
            self._session_epoch,
            tuple(sorted(self.catalog_options)),
            tuple(sorted(self.combos)),
            self.platform.reason,
            tuple(
                sorted(
                    (channel, slot.state.value, slot.generation)
                    for channel, slot in self._channels.items()
                )
            ),
        )

    def _schedule(
        self,
        *,
        purpose: RpcPurpose,
        method: str,
        params: dict[str, object],
        scope: str,
        generation: int | None,
        origin_boundary: FactBoundary,
        failure_scope: FailureScope,
    ) -> PendingRpc:
        if self._session_epoch is None:
            raise RuntimeError("cannot schedule an RPC without a session")
        request = PendingRpc(
            request_id=self._next_request_id,
            purpose=purpose,
            method=method,
            params=params,
            session_epoch=self._session_epoch,
            scope=scope,
            generation=generation,
            origin_boundary=origin_boundary,
            deadline_monotonic_ms=(
                origin_boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            ),
            failure_scope=failure_scope,
        )
        self._next_request_id += 1
        self.pending_rpcs[request.request_id] = request
        self._commands.append(request)
        self.diagnostics.rpc_request_count[method] += 1
        if purpose is RpcPurpose.COMBO_CATALOG:
            self.diagnostics.combo_authoritative_refresh_attempt_count += 1
            self._combo_refresh_request_id = request.request_id
        return request

    def _take_commands(self) -> tuple[PendingRpc, ...]:
        commands = tuple(self._commands)
        self._commands = []
        return commands

    def _drop_held_frames(
        self,
        *,
        channel: str | None = None,
        generation: int | None = None,
    ) -> None:
        retained: list[_HeldSubscriptionFrame] = []
        for held in self._held_subscription_frames:
            matches_channel = channel is None or held.channel == channel
            matches_generation = generation is None or held.generation == generation
            if matches_channel and matches_generation:
                continue
            retained.append(held)
        self._held_subscription_frames = retained
        self._held_subscription_frame_count = len(retained)

    def _mark_held_frames_eligible(
        self,
        channels: tuple[str, ...],
        generation: int | None,
    ) -> None:
        channel_set = set(channels)
        for held in self._held_subscription_frames:
            if held.channel in channel_set and held.generation == generation:
                held.eligible = True

    def _hold_subscription_frame(
        self,
        envelope: InboundEnvelope,
        *,
        channel: str,
        generation: int,
    ) -> None:
        if self._held_subscription_frame_count >= MAX_PENDING_INBOUND_FRAMES:
            self._retire_current_epoch()
            raise PublicSessionError("pre-ack inbound frame buffer overflow")
        self._held_subscription_frames.append(
            _HeldSubscriptionFrame(
                envelope=envelope,
                channel=channel,
                generation=generation,
                eligible=False,
            )
        )
        self._held_subscription_frame_count += 1

    def _drain_held_frames(self, release_boundary: FactBoundary) -> None:
        ready = tuple(held for held in self._held_subscription_frames if held.eligible)
        if not ready:
            return
        self._held_subscription_frames = [
            held for held in self._held_subscription_frames if not held.eligible
        ]
        self._held_subscription_frame_count = len(self._held_subscription_frames)
        for held in ready:
            self._apply_acknowledged_subscription(
                held.envelope,
                commit_boundary=release_boundary,
            )

    def _current_boundary(self, envelope: InboundEnvelope) -> FactBoundary:
        return FactBoundary(
            envelope.session_epoch,
            envelope.ingress_seq,
            self._last_boundary_monotonic_ms,
            self._causal_seq,
        )

    def _current_fact_boundary(self) -> FactBoundary:
        if self._session_epoch is None:
            raise RuntimeError("current fact boundary requires a session")
        return FactBoundary(
            self._session_epoch,
            self._last_ingress_seq,
            self._last_boundary_monotonic_ms,
            self._causal_seq,
        )

    def _apply_response(self, envelope: InboundEnvelope) -> None:
        request_id = envelope.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            raise PublicProtocolError("response id is invalid")
        request = self.pending_rpcs.pop(request_id, None)
        if request is None or request.session_epoch != self._session_epoch:
            self.diagnostics.late_response_count += 1
            return
        if request.purpose not in {
            RpcPurpose.SET_HEARTBEAT,
            RpcPurpose.HEARTBEAT_TEST,
        }:
            self._causal_seq += 1
        if envelope.received_monotonic_ms > request.deadline_monotonic_ms:
            self.diagnostics.late_response_count += 1
            self.diagnostics.rpc_late_count[request.method] += 1
            self._note_source_shape(request.method, envelope.get("result"), valid=False)
            self._apply_request_failure(request)
            return
        if "error" in envelope:
            self.diagnostics.rpc_error_count[request.method] += 1
            self._note_source_shape(request.method, envelope["error"], valid=False)
            if _is_rate_limit_error(envelope["error"]):
                self.diagnostics.rpc_rate_limit_count[request.method] += 1
            if request.purpose is RpcPurpose.HEARTBEAT_TEST:
                self.diagnostics.heartbeat_public_test_error_count += 1
            self._apply_request_failure(request)
            return
        if "result" not in envelope:
            raise PublicProtocolIncompatibility("JSON-RPC response lacks result")
        result = envelope["result"]
        latency_ms = max(
            0,
            envelope.received_monotonic_ms - request.origin_boundary.received_monotonic_ms,
        )
        self.diagnostics.rpc_success_count[request.method] += 1
        self.diagnostics.rpc_latency_count[request.method] += 1
        self.diagnostics.rpc_latency_sum[request.method] += latency_ms
        self.diagnostics.rpc_latency_max[request.method] = max(
            self.diagnostics.rpc_latency_max[request.method],
            latency_ms,
        )
        boundary = self._current_boundary(envelope)
        source_valid = True
        if request.purpose is RpcPurpose.SET_HEARTBEAT:
            if result != "ok":
                raise PublicProtocolIncompatibility("heartbeat acknowledgement was not ok")
            self._plan_channel_change(
                (
                    *PLATFORM_CHANNELS,
                    OPTION_LIFECYCLE_CHANNEL,
                    COMBO_LIFECYCLE_CHANNEL,
                ),
                subscribe=True,
                origin_boundary=boundary,
            )
        elif request.purpose in {
            RpcPurpose.SUBSCRIBE_CHANNELS,
            RpcPurpose.UNSUBSCRIBE_CHANNELS,
        }:
            try:
                self._apply_channel_ack(request, result, boundary)
            except SourceDataError as exc:
                self._note_source_shape(request.method, result, valid=False)
                raise PublicProtocolIncompatibility(
                    f"{request.method} acknowledgement shape is incompatible"
                ) from exc
        elif request.purpose is RpcPurpose.PLATFORM_STATUS:
            prior_reason = self.platform.reason
            try:
                self.platform.apply_status(result)
            except SourceDataError as exc:
                self._note_source_shape(request.method, result, valid=False)
                raise PublicProtocolIncompatibility(
                    "public/status response shape is incompatible"
                ) from exc
            if prior_reason in {"PLATFORM_MAINTENANCE", "PUBLIC_METHODS_DENIED"}:
                self.platform.reason = prior_reason
            if self.platform.reason == "RELEVANT_PLATFORM_LOCK":
                self._retire_current_epoch()
                raise PublicSessionError(
                    "platform status invalidated bootstrap epoch: RELEVANT_PLATFORM_LOCK"
                )
            self._platform_status_ingress_seq = envelope.ingress_seq
            self._post_status_bootstrap_successes.clear()
            self._schedule_post_status_bootstrap(boundary)
        elif request.purpose in {RpcPurpose.CLOCK_BOOTSTRAP, RpcPurpose.CLOCK_REFRESH}:
            try:
                server_ms = require_int(result, f"{request.method} result")
            except SourceDataError as exc:
                self._note_source_shape(request.method, result, valid=False)
                raise PublicProtocolIncompatibility(
                    f"{request.method} response shape is incompatible"
                ) from exc
            try:
                if request.purpose is RpcPurpose.CLOCK_BOOTSTRAP or self.clock is None:
                    self.clock = TrustedClock.from_response(
                        server_ms,
                        request.origin_boundary.received_monotonic_ms,
                        envelope.received_monotonic_ms,
                        stale_deadline_ms=self.policy.runtime_limits.clock_stale_deadline_ms,
                    )
                else:
                    self.clock = self.clock.refresh(
                        server_ms,
                        request.origin_boundary.received_monotonic_ms,
                        envelope.received_monotonic_ms,
                    )
            except ContinuityGap:
                self._invalidate_clock_index(boundary, reason="CLOCK_GAP")
                self._note_source_shape(request.method, result, valid=True)
                return
            self._clock_revision += 1
            self._next_clock_refresh_ms = (
                envelope.received_monotonic_ms
                + self.policy.runtime_limits.clock_refresh_interval_ms
            )
            index_slot = self._channels.get(INDEX_CHANNEL)
            release_index_generation = (
                index_slot.generation
                if (
                    index_slot is not None
                    and index_slot.state is ChannelState.ACKNOWLEDGED
                    and self._index_coverage_generation != index_slot.generation
                )
                else None
            )
            if release_index_generation is not None:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
                self.index.start_continuous_coverage(trusted.upper_ms)
                self._index_coverage_generation = release_index_generation
                self._index_resubscribe_pending = False
            if request.purpose is RpcPurpose.CLOCK_REFRESH:
                self.diagnostics.clock_refresh_success_count += 1
            self._sync_membership(boundary)
            self._settle_fact(
                boundary=boundary,
                affected_instruments=tuple(self.options),
                countable=False,
                observation_reason="CLOCK_FACT",
            )
            if release_index_generation is not None:
                self._mark_held_frames_eligible(
                    (INDEX_CHANNEL,),
                    release_index_generation,
                )
                self._drain_held_frames(boundary)
        elif request.purpose is RpcPurpose.OPTION_CATALOG:
            source_valid = self._apply_option_snapshot(result, boundary)
        elif request.purpose is RpcPurpose.OPTION_METADATA:
            source_valid = self._apply_option_metadata(request, result)
        elif request.purpose is RpcPurpose.COMBO_CATALOG:
            source_valid = self._apply_combo_snapshot(request, result, boundary)
        elif request.purpose is RpcPurpose.COMBO_METADATA:
            source_valid = self._apply_combo_metadata(request, result, boundary)
        elif request.purpose is RpcPurpose.HEARTBEAT_TEST:
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("version"), str)
                or not result["version"]
            ):
                raise PublicProtocolIncompatibility("public/test result lacks a valid version")
            self.diagnostics.heartbeat_public_test_success_count += 1
            self.diagnostics.heartbeat_latency_count += 1
            self.diagnostics.heartbeat_latency_sum += latency_ms
            self.diagnostics.heartbeat_latency_max = max(
                self.diagnostics.heartbeat_latency_max,
                latency_ms,
            )
        self._note_source_shape(request.method, result, valid=source_valid)
        self._note_post_status_bootstrap_success(
            request,
            source_valid=source_valid,
            boundary=self._current_fact_boundary(),
        )

    def _apply_request_failure(self, request: PendingRpc) -> None:
        if request.purpose in {
            RpcPurpose.CLOCK_BOOTSTRAP,
            RpcPurpose.CLOCK_REFRESH,
        }:
            boundary = self._current_fact_boundary()
            if request.purpose is RpcPurpose.CLOCK_REFRESH:
                self.diagnostics.clock_refresh_failure_count += 1
            if self.clock is not None:
                try:
                    self.clock.interval_at(boundary.received_monotonic_ms)
                except ContinuityGap:
                    self._invalidate_clock_index(boundary, reason="CLOCK_GAP")
                    return
                self._next_clock_refresh_ms = (
                    boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
                )
                return
            self.platform.invalidate_fresh_index_coverage("CLOCK_GAP")
            self._settle_clock_gap(boundary)
            self._next_clock_refresh_ms = (
                boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            return
        if request.purpose is RpcPurpose.OPTION_METADATA and (
            self._option_metadata_pending.get(request.scope) != request.generation
            or self._option_lifecycle_revision[request.scope] != request.generation
            or self._option_lifecycle_state.get(request.scope) != "open"
        ):
            return
        if request.purpose is RpcPurpose.COMBO_METADATA and (
            self._combo_metadata_pending.get(request.scope) != request.generation
            or self._combo_metadata_revisions[request.scope] != request.generation
        ):
            return
        if request.purpose is RpcPurpose.OPTION_CATALOG:
            self.diagnostics.option_catalog_refresh_failure_count += 1
        elif request.purpose is RpcPurpose.COMBO_CATALOG:
            self.diagnostics.combo_authoritative_refresh_failure_count += 1
        current_subscription_channels: tuple[str, ...] = ()
        if request.purpose in {
            RpcPurpose.SUBSCRIBE_CHANNELS,
            RpcPurpose.UNSUBSCRIBE_CHANNELS,
        }:
            channels = request.params.get("channels")
            if isinstance(channels, list):
                current_subscription_channels = tuple(
                    channel
                    for channel in channels
                    if isinstance(channel, str)
                    and (slot := self._channels.get(channel)) is not None
                    and slot.generation == request.generation
                )
            if not current_subscription_channels:
                return
            boundary = self._current_fact_boundary()
            for channel in current_subscription_channels:
                slot = self._channels[channel]
                slot.state = (
                    ChannelState.RETIRED
                    if request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
                    else ChannelState.ACKNOWLEDGED
                )
                slot.retry_after_ms = (
                    boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
                )
                slot.retry_failure_scope = request.failure_scope
                self._drop_held_frames(
                    channel=channel,
                    generation=request.generation,
                )
            self._drain_held_frames(boundary)
        if request.failure_scope is FailureScope.OPTION_CATALOG:
            if (
                request.purpose is RpcPurpose.OPTION_METADATA
                and self._option_metadata_pending.get(request.scope) == request.generation
            ):
                self._option_metadata_pending.pop(request.scope, None)
                self._option_lifecycle_unavailable[request.scope] = "OPTION_METADATA_REQUEST_FAILED"
                self._commit_forced_unknown(
                    request.scope,
                    reason="OPTION_METADATA_REQUEST_FAILED",
                    boundary=self._current_fact_boundary(),
                    continuity_gap=False,
                )
            self.option_catalog.mark_incomplete()
            self._next_option_catalog_recovery_ms = (
                self._last_boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._refresh_atomic_current()
            self._update_coverage(self._last_boundary_monotonic_ms)
        elif request.failure_scope is FailureScope.OPTION:
            option_channels = (
                current_subscription_channels
                if request.purpose
                in {RpcPurpose.SUBSCRIBE_CHANNELS, RpcPurpose.UNSUBSCRIBE_CHANNELS}
                else ()
            )
            affected_instruments: set[str] = set()
            for channel in option_channels:
                instrument_name = _instrument_from_channel(channel)
                if instrument_name is None:
                    continue
                if instrument_name not in self.options:
                    continue
                affected_instruments.add(instrument_name)
                if channel == ticker_channel(instrument_name):
                    latch = self._ticker_currentness_latches.get(instrument_name)
                    if latch is None:
                        self._ticker_unavailable.setdefault(
                            instrument_name,
                            ("OPTION_CHANNEL_FAILURE", True),
                        )
                elif channel == book_channel(instrument_name):
                    book = self.option_books.get(instrument_name)
                    if book is not None:
                        book.invalidate("OPTION_CHANNEL_FAILURE")
            if affected_instruments:
                self._settle_fact(
                    boundary=self._current_fact_boundary(),
                    affected_instruments=tuple(sorted(affected_instruments)),
                    countable=False,
                    observation_reason="OPTION_CHANNEL_FAILURE",
                )
        elif request.failure_scope is FailureScope.COMBO_LAYER:
            self.combo_catalog.mark_incomplete()
            self._next_combo_catalog_recovery_ms = (
                self._last_boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            if request.purpose is RpcPurpose.COMBO_METADATA:
                if self._combo_metadata_pending.get(request.scope) == request.generation:
                    self._combo_metadata_pending.pop(request.scope, None)
            if request.request_id == self._combo_refresh_request_id:
                self._combo_refresh_request_id = None
            self._combo_refresh_origin_revision.pop(request.request_id, None)
            self._refresh_atomic_current()
        elif request.failure_scope is FailureScope.CLOCK_INDEX:
            self._invalidate_clock_index(
                self._current_fact_boundary(),
                reason="CLOCK_GAP",
            )
        elif request.failure_scope is FailureScope.SESSION:
            self._retire_current_epoch()
            raise PublicSessionError(f"{request.purpose.value} request failed")
        elif request.failure_scope is FailureScope.FATAL_PROTOCOL:
            raise PublicProtocolIncompatibility(f"{request.purpose.value} request failed")

    def _plan_channel_change(
        self,
        channels: tuple[str, ...],
        *,
        subscribe: bool,
        origin_boundary: FactBoundary,
        failure_scope: FailureScope = FailureScope.SESSION,
    ) -> None:
        planned: list[str] = []
        for channel in dict.fromkeys(channels):
            slot = self._channels.setdefault(channel, _ChannelSlot())
            slot.desired_subscribed = subscribe
            slot.retry_failure_scope = failure_scope
            if not subscribe:
                slot.resync_requested = False
            if slot.retry_after_ms is not None:
                continue
            if subscribe and slot.state in {
                ChannelState.UNSUBSCRIBED,
                ChannelState.RETIRED,
            }:
                planned.append(channel)
            elif not subscribe and slot.state is ChannelState.ACKNOWLEDGED:
                planned.append(channel)
        self._issue_channel_change(
            tuple(planned),
            subscribe=subscribe,
            origin_boundary=origin_boundary,
            failure_scope=failure_scope,
        )

    def _issue_channel_change(
        self,
        channels: tuple[str, ...],
        *,
        subscribe: bool,
        origin_boundary: FactBoundary,
        failure_scope: FailureScope,
    ) -> None:
        for batch in subscription_batches(channels):
            generation = self._next_channel_generation
            self._next_channel_generation += 1
            for channel in batch:
                slot = self._channels.setdefault(channel, _ChannelSlot())
                slot.generation = generation
                slot.retry_after_ms = None
                slot.retry_failure_scope = failure_scope
                slot.state = (
                    ChannelState.SUBSCRIBE_PENDING
                    if subscribe
                    else ChannelState.UNSUBSCRIBE_PENDING
                )
                if subscribe:
                    self._drop_held_frames(channel=channel)
            self._schedule(
                purpose=(
                    RpcPurpose.SUBSCRIBE_CHANNELS if subscribe else RpcPurpose.UNSUBSCRIBE_CHANNELS
                ),
                method="public/subscribe" if subscribe else "public/unsubscribe",
                params={"channels": list(batch)},
                scope="CHANNELS",
                generation=generation,
                origin_boundary=origin_boundary,
                failure_scope=failure_scope,
            )

    def _reconcile_channel_intents(
        self,
        channels: tuple[str, ...],
        boundary: FactBoundary,
    ) -> None:
        subscribe: list[str] = []
        unsubscribe: list[str] = []
        scope_by_channel: dict[str, FailureScope] = {}
        for channel in dict.fromkeys(channels):
            slot = self._channels.get(channel)
            if slot is None or slot.retry_after_ms is not None:
                continue
            scope_by_channel[channel] = slot.retry_failure_scope
            if slot.desired_subscribed:
                if slot.state in {ChannelState.UNSUBSCRIBED, ChannelState.RETIRED}:
                    slot.resync_requested = False
                    subscribe.append(channel)
                elif slot.state is ChannelState.ACKNOWLEDGED and slot.resync_requested:
                    unsubscribe.append(channel)
            elif slot.state is ChannelState.ACKNOWLEDGED:
                unsubscribe.append(channel)
        for failure_scope in FailureScope:
            scoped_subscribe = tuple(
                channel for channel in subscribe if scope_by_channel[channel] is failure_scope
            )
            if scoped_subscribe:
                self._issue_channel_change(
                    scoped_subscribe,
                    subscribe=True,
                    origin_boundary=boundary,
                    failure_scope=failure_scope,
                )
            scoped_unsubscribe = tuple(
                channel for channel in unsubscribe if scope_by_channel[channel] is failure_scope
            )
            if scoped_unsubscribe:
                self._issue_channel_change(
                    scoped_unsubscribe,
                    subscribe=False,
                    origin_boundary=boundary,
                    failure_scope=failure_scope,
                )

    def _apply_channel_ack(
        self,
        request: PendingRpc,
        result: object,
        boundary: FactBoundary,
    ) -> None:
        channels_raw = request.params.get("channels")
        if not isinstance(channels_raw, list) or not all(
            isinstance(channel, str) for channel in channels_raw
        ):
            raise RuntimeError("pending channel request lost its exact channels")
        channels = tuple(channels_raw)
        validate_subscription_ack(channels, result)
        current_channels = tuple(
            channel
            for channel in channels
            if self._channels[channel].generation == request.generation
        )
        if not current_channels:
            return
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS:
            for channel in current_channels:
                slot = self._channels[channel]
                slot.state = ChannelState.RETIRED
                self._drop_held_frames(channel=channel)
            self._drain_held_frames(boundary)
            self._reconcile_channel_intents(current_channels, boundary)
            self._update_subscription_peaks()
            return

        admitted_channels = tuple(
            channel
            for channel in current_channels
            if self._channels[channel].desired_subscribed
            and not self._channels[channel].resync_requested
        )
        self.platform.acknowledge(admitted_channels)
        if OPTION_LIFECYCLE_CHANNEL in admitted_channels:
            self.option_catalog.acknowledge_lifecycle()
        if COMBO_LIFECYCLE_CHANNEL in admitted_channels:
            self.combo_catalog.acknowledge_lifecycle()
        for channel in current_channels:
            slot = self._channels[channel]
            slot.state = ChannelState.ACKNOWLEDGED
            if channel not in admitted_channels:
                self._drop_held_frames(
                    channel=channel,
                    generation=request.generation,
                )
                continue
            if channel == INDEX_CHANNEL and self.clock is not None:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
                self.index.start_continuous_coverage(trusted.upper_ms)
                self._index_coverage_generation = slot.generation
                self._index_resubscribe_pending = False
            if channel != INDEX_CHANNEL or self.clock is not None:
                self._mark_held_frames_eligible((channel,), request.generation)
        self._drain_held_frames(boundary)
        self._reconcile_channel_intents(current_channels, boundary)
        self._update_subscription_peaks()
        if not self._bootstrap_queries_issued and all(
            self.channel_state(channel) is ChannelState.ACKNOWLEDGED
            for channel in (
                *PLATFORM_CHANNELS,
                OPTION_LIFECYCLE_CHANNEL,
                COMBO_LIFECYCLE_CHANNEL,
            )
        ):
            self._bootstrap_queries_issued = True
            self._schedule_bootstrap_queries(boundary)

    def _schedule_bootstrap_queries(self, boundary: FactBoundary) -> None:
        self._schedule(
            purpose=RpcPurpose.PLATFORM_STATUS,
            method="public/status",
            params={},
            scope="PLATFORM",
            generation=None,
            origin_boundary=boundary,
            failure_scope=FailureScope.SESSION,
        )

    def _schedule_post_status_bootstrap(self, boundary: FactBoundary) -> None:
        self._schedule(
            purpose=RpcPurpose.CLOCK_BOOTSTRAP,
            method="public/get_time",
            params={},
            scope="CLOCK_INDEX",
            generation=None,
            origin_boundary=boundary,
            failure_scope=FailureScope.CLOCK_INDEX,
        )
        self._schedule_option_catalog_refresh(boundary)
        self._schedule_combo_refresh(boundary, trailing=False)

    def _note_post_status_bootstrap_success(
        self,
        request: PendingRpc,
        *,
        source_valid: bool,
        boundary: FactBoundary,
    ) -> None:
        if (
            not source_valid
            or request.purpose not in POST_STATUS_BOOTSTRAP_PURPOSES
            or self._platform_status_ingress_seq is None
            or request.origin_boundary.ingress_seq < self._platform_status_ingress_seq
        ):
            return
        if request.purpose is RpcPurpose.CLOCK_BOOTSTRAP and self.clock is None:
            return
        if request.purpose is RpcPurpose.OPTION_CATALOG and not self.option_catalog.source_complete:
            return
        if request.purpose is RpcPurpose.COMBO_CATALOG and not self.combo_catalog.source_complete:
            return
        self._post_status_bootstrap_successes.add(request.purpose)
        if self._post_status_bootstrap_successes == POST_STATUS_BOOTSTRAP_PURPOSES:
            was_usable = self.platform.usable
            self.platform.prove_operational_from_post_status_public_success()
            if not was_usable and self.platform.usable:
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=tuple(self.options),
                    countable=False,
                    observation_reason="PLATFORM_READY",
                )

    def _schedule_option_catalog_refresh(self, boundary: FactBoundary) -> PendingRpc:
        self.option_catalog.begin_reconciliation()
        return self._schedule(
            purpose=RpcPurpose.OPTION_CATALOG,
            method="public/get_instruments",
            params={"currency": "USDC", "kind": "option", "expired": False},
            scope="OPTION_CATALOG",
            generation=None,
            origin_boundary=boundary,
            failure_scope=FailureScope.OPTION_CATALOG,
        )

    def _accept_subscription_frame(self, envelope: InboundEnvelope) -> None:
        params = require_mapping(envelope.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        slot = self._channels.get(channel)
        if slot is None or slot.state in {
            ChannelState.UNSUBSCRIBED,
            ChannelState.RETIRED,
        }:
            return
        if slot.state is ChannelState.SUBSCRIBE_PENDING:
            self._hold_subscription_frame(
                envelope,
                channel=channel,
                generation=slot.generation,
            )
            return
        if (
            slot.state is not ChannelState.ACKNOWLEDGED
            or not slot.desired_subscribed
            or slot.resync_requested
        ):
            return
        if channel == INDEX_CHANNEL and (
            self.clock is None or self._index_coverage_generation != slot.generation
        ):
            self._hold_subscription_frame(
                envelope,
                channel=channel,
                generation=slot.generation,
            )
            return
        self._apply_acknowledged_subscription(envelope)

    def _apply_acknowledged_subscription(
        self,
        envelope: InboundEnvelope,
        *,
        commit_boundary: FactBoundary | None = None,
    ) -> None:
        params = require_mapping(envelope.get("params"), "subscription.params")
        channel = require_str(params.get("channel"), "subscription.params.channel")
        data = params.get("data")
        source = _source_name_for_channel(
            channel,
            combo_names=set(self.combos) | self._subscribed_combo_names,
        )
        self._causal_seq += 1
        boundary = (
            self._current_boundary(envelope)
            if commit_boundary is None
            else FactBoundary(
                session_epoch=commit_boundary.session_epoch,
                ingress_seq=commit_boundary.ingress_seq,
                received_monotonic_ms=commit_boundary.received_monotonic_ms,
                causal_seq=self._causal_seq,
            )
        )
        valid = True
        epoch_failure_reason: str | None = None
        try:
            if channel == OPTION_LIFECYCLE_CHANNEL:
                try:
                    if self.option_catalog.buffering:
                        self.option_catalog.accept_lifecycle(data)
                    else:
                        self._apply_option_lifecycle(data, boundary)
                except (SourceDataError, ValueError):
                    self._mark_option_catalog_incomplete(boundary)
                    valid = False
            elif channel == COMBO_LIFECYCLE_CHANNEL:
                try:
                    if self.combo_catalog.buffering:
                        self.combo_catalog.accept_lifecycle(data)
                    else:
                        self._apply_combo_lifecycle(data, boundary)
                except (SourceDataError, ValueError):
                    self._mark_combo_catalog_incomplete(boundary)
                    valid = False
                if self._combo_refresh_request_id is not None:
                    pass
                else:
                    self._schedule_combo_refresh(
                        boundary,
                        trailing=False,
                    )
            elif channel == "platform_state":
                self.platform.apply_platform_notification(data)
                if self.platform.reason in {
                    "PLATFORM_MAINTENANCE",
                    "RELEVANT_PLATFORM_LOCK",
                }:
                    epoch_failure_reason = self.platform.reason
                else:
                    self._settle_fact(
                        boundary=boundary,
                        affected_instruments=tuple(self.options),
                        countable=False,
                        observation_reason="PLATFORM_FACT",
                    )
            elif channel == "platform_state.public_methods_state":
                self.platform.apply_public_methods_notification(data)
                if self.platform.reason == "PUBLIC_METHODS_DENIED":
                    epoch_failure_reason = self.platform.reason
                else:
                    self._settle_fact(
                        boundary=boundary,
                        affected_instruments=tuple(self.options),
                        countable=False,
                        observation_reason="PLATFORM_FACT",
                    )
            elif channel == INDEX_CHANNEL:
                valid = self._apply_index(data, boundary)
            elif channel.startswith("ticker.") and channel.endswith(".100ms"):
                instrument_name = channel[len("ticker.") : -len(".100ms")]
                valid = self._apply_ticker(
                    instrument_name,
                    data,
                    boundary,
                )
            elif channel.startswith("book.") and channel.endswith(".100ms"):
                instrument_name = channel[len("book.") : -len(".100ms")]
                valid = self._apply_book(
                    instrument_name,
                    data,
                    boundary,
                )
        except (ContinuityGap, SourceDataError, ValueError) as exc:
            self._note_source_shape(source, data, valid=False)
            raise PublicProtocolIncompatibility(
                f"{source} subscription payload is incompatible"
            ) from exc
        self._note_source_shape(source, data, valid=valid)
        if epoch_failure_reason is not None:
            self._retire_current_epoch()
            raise PublicSessionError(
                f"platform guard invalidated bootstrap epoch: {epoch_failure_reason}"
            )

    def _mark_option_catalog_incomplete(self, boundary: FactBoundary) -> None:
        self.option_catalog.mark_incomplete()
        self._next_option_catalog_recovery_ms = (
            boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        self._refresh_atomic_current()
        self._update_coverage(boundary.received_monotonic_ms)

    def _mark_combo_catalog_incomplete(self, boundary: FactBoundary) -> None:
        self.combo_catalog.mark_incomplete()
        self._next_combo_catalog_recovery_ms = (
            boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        self._refresh_atomic_current()

    def _apply_heartbeat(self, envelope: InboundEnvelope) -> None:
        params = require_mapping(envelope.get("params"), "heartbeat.params")
        heartbeat_type = require_str(params.get("type"), "heartbeat.params.type")
        if heartbeat_type == "heartbeat":
            return
        if heartbeat_type != "test_request":
            raise PublicProtocolIncompatibility("unknown heartbeat type")
        self.diagnostics.heartbeat_test_request_count += 1
        self._schedule(
            purpose=RpcPurpose.HEARTBEAT_TEST,
            method="public/test",
            params={},
            scope="SESSION_CONTROL",
            generation=None,
            origin_boundary=self._current_boundary(envelope),
            failure_scope=FailureScope.SESSION,
        )

    def _apply_option_snapshot(
        self,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        try:
            values = require_list(payload, "public/get_instruments result")
        except SourceDataError:
            values = []
            complete = False
        else:
            complete = True
        parsed: dict[str, OptionInstrument] = {}
        parsed_states: dict[str, str] = {}
        parsed_unavailable: dict[str, str] = {}
        positive_scope_safe = True
        for value in values:
            instrument_name = (
                value.get("instrument_name")
                if isinstance(value, dict) and isinstance(value.get("instrument_name"), str)
                else None
            )
            try:
                instrument = parse_option_instrument(value)
            except SourceDataError:
                complete = False
                if instrument_name is None:
                    positive_scope_safe = False
                else:
                    self._option_lifecycle_unavailable[instrument_name] = "OPTION_SNAPSHOT_INVALID"
                    self._commit_forced_unknown(
                        instrument_name,
                        reason="OPTION_SNAPSHOT_INVALID",
                        boundary=boundary,
                        continuity_gap=False,
                    )
                continue
            if instrument is not None:
                parsed[instrument.instrument_name] = instrument
                state = instrument.lifecycle_state.value
                parsed_states[instrument.instrument_name] = state
                if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES or not instrument.is_active:
                    parsed_unavailable[instrument.instrument_name] = (
                        f"OPTION_SNAPSHOT_{state.upper()}"
                        if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES
                        else "OPTION_SNAPSHOT_OPEN_INACTIVE"
                    )
                continue
            try:
                target_product = _is_target_option_product(value)
            except SourceDataError:
                complete = False
                positive_scope_safe = False
                continue
            if not target_product:
                continue
            data = require_mapping(value, "instrument")
            state = require_str(data.get("state"), "instrument.state")
            require_bool(data.get("is_active"), "instrument.is_active")
            if state in FINAL_INSTRUMENT_LIFECYCLE_STATES:
                continue
            complete = False
            if instrument_name is None:
                positive_scope_safe = False
            else:
                self._option_lifecycle_unavailable[instrument_name] = (
                    f"OPTION_SNAPSHOT_{state.upper()}"
                )
                self._commit_forced_unknown(
                    instrument_name,
                    reason=self._option_lifecycle_unavailable[instrument_name],
                    boundary=boundary,
                    continuity_gap=False,
                )
        reconciliation_intact = self.option_catalog.source_complete
        if complete:
            self.catalog_options = parsed
            self._option_lifecycle_unavailable = parsed_unavailable
            self._option_positive_scope_safe = True
            for instrument_name, state in parsed_states.items():
                self._option_lifecycle_state[instrument_name] = state
        else:
            self.catalog_options.update(parsed)
            for instrument_name, state in parsed_states.items():
                self._option_lifecycle_state[instrument_name] = state
                if instrument_name in parsed_unavailable:
                    self._option_lifecycle_unavailable[instrument_name] = parsed_unavailable[
                        instrument_name
                    ]
                else:
                    self._option_lifecycle_unavailable.pop(instrument_name, None)
            self._option_positive_scope_safe = (
                self._option_positive_scope_safe and positive_scope_safe
            )
        self.option_catalog.source_complete = complete and reconciliation_intact
        for event in self.option_catalog.reconcile():
            try:
                self._apply_option_lifecycle(event, boundary)
            except (SourceDataError, ValueError):
                self.option_catalog.mark_incomplete()
        self._complete_option_catalog_if_ready()
        reconciliation_success = complete and reconciliation_intact
        if reconciliation_success:
            self.diagnostics.option_catalog_refresh_success_count += 1
        else:
            self.diagnostics.option_catalog_refresh_failure_count += 1
        self._next_option_catalog_recovery_ms = (
            None
            if self.option_catalog.complete
            else boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        self._sync_membership(boundary)
        self._refresh_atomic_current()
        self._settle_fact(
            boundary=boundary,
            affected_instruments=tuple(self.options),
            countable=False,
            observation_reason="OPTION_CATALOG",
        )
        self._ensure_combo_catalog_refresh(boundary)
        return complete

    def _apply_option_lifecycle(
        self,
        payload: object,
        boundary: FactBoundary,
    ) -> None:
        data = require_mapping(payload, "option lifecycle")
        instrument_name = require_str(
            data.get("instrument_name"),
            "option lifecycle.instrument_name",
        )
        state = require_str(data.get("state"), "option lifecycle.state")
        self._option_lifecycle_revision[instrument_name] += 1
        generation = self._option_lifecycle_revision[instrument_name]
        self._option_lifecycle_state[instrument_name] = state
        if state not in INSTRUMENT_LIFECYCLE_STATES:
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable[instrument_name] = (
                f"OPTION_LIFECYCLE_UNKNOWN:{state}"
            )
            self._commit_forced_unknown(
                instrument_name,
                reason=self._option_lifecycle_unavailable[instrument_name],
                boundary=boundary,
                continuity_gap=False,
            )
            raise SourceDataError("option lifecycle.state is unsupported")
        if state in FINAL_INSTRUMENT_LIFECYCLE_STATES:
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable.pop(instrument_name, None)
            self.catalog_options.pop(instrument_name, None)
            self._complete_option_catalog_if_ready()
            self._sync_membership(boundary)
            self._settle_fact(
                boundary=boundary,
                affected_instruments=tuple(self.options),
                countable=False,
                observation_reason="OPTION_LIFECYCLE",
            )
            return
        if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES:
            reason = f"OPTION_LIFECYCLE_{state.upper()}"
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable[instrument_name] = reason
            self._commit_forced_unknown(
                instrument_name,
                reason=reason,
                boundary=boundary,
                continuity_gap=False,
            )
            if instrument_name in self.catalog_options:
                self._complete_option_catalog_if_ready()
                self._refresh_atomic_current()
                self._update_coverage(boundary.received_monotonic_ms)
            else:
                self._mark_option_catalog_incomplete(boundary)
            return
        self._option_metadata_pending[instrument_name] = generation
        self._option_lifecycle_unavailable[instrument_name] = "OPTION_METADATA_PENDING"
        self.option_catalog.complete = False
        self._commit_forced_unknown(
            instrument_name,
            reason="OPTION_METADATA_PENDING",
            boundary=boundary,
            continuity_gap=False,
        )
        self._refresh_atomic_current()
        self._update_coverage(boundary.received_monotonic_ms)
        self._schedule(
            purpose=RpcPurpose.OPTION_METADATA,
            method="public/get_instrument",
            params={"instrument_name": instrument_name},
            scope=instrument_name,
            generation=generation,
            origin_boundary=boundary,
            failure_scope=FailureScope.OPTION_CATALOG,
        )

    def _apply_option_metadata(self, request: PendingRpc, payload: object) -> bool:
        if (
            self._option_lifecycle_revision[request.scope] != request.generation
            or self._option_lifecycle_state.get(request.scope) != "open"
        ):
            if self._option_metadata_pending.get(request.scope) == request.generation:
                self._option_metadata_pending.pop(request.scope, None)
            return True
        try:
            instrument = parse_option_instrument(payload)
        except SourceDataError:
            instrument = None
        if instrument is None or instrument.instrument_name != request.scope:
            if _is_explicit_final_target_option_metadata(
                payload, request.scope
            ) or _is_valid_irrelevant_option_metadata(payload, request.scope):
                if self._option_metadata_pending.get(request.scope) == request.generation:
                    self._option_metadata_pending.pop(request.scope, None)
                self._option_lifecycle_unavailable.pop(request.scope, None)
                self.catalog_options.pop(request.scope, None)
                self._complete_option_catalog_if_ready()
                if self.option_catalog.complete:
                    self._next_option_catalog_recovery_ms = None
                boundary = self._current_fact_boundary()
                self._sync_membership(boundary)
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=tuple(self.options),
                    countable=False,
                    observation_reason="OPTION_METADATA_ABSENT",
                )
                self._ensure_combo_catalog_refresh(boundary)
                return True
            if self._option_metadata_pending.get(request.scope) == request.generation:
                self._option_metadata_pending.pop(request.scope, None)
            self._option_lifecycle_unavailable[request.scope] = "OPTION_METADATA_INVALID"
            self.option_catalog.mark_incomplete()
            self._commit_forced_unknown(
                request.scope,
                reason="OPTION_METADATA_INVALID",
                boundary=self._current_fact_boundary(),
                continuity_gap=False,
            )
            self._next_option_catalog_recovery_ms = (
                self._last_boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._refresh_atomic_current()
            self._update_coverage(self._last_boundary_monotonic_ms)
            return False
        if self._option_metadata_pending.get(request.scope) == request.generation:
            self._option_metadata_pending.pop(request.scope, None)
        state = instrument.lifecycle_state.value
        self._option_lifecycle_state[request.scope] = state
        if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES or not instrument.is_active:
            self._option_lifecycle_unavailable[request.scope] = (
                f"OPTION_METADATA_{state.upper()}"
                if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES
                else "OPTION_METADATA_OPEN_INACTIVE"
            )
        else:
            self._option_lifecycle_unavailable.pop(request.scope, None)
        self.catalog_options[instrument.instrument_name] = instrument
        self._complete_option_catalog_if_ready()
        if self.option_catalog.complete:
            self._next_option_catalog_recovery_ms = None
        boundary = self._current_fact_boundary()
        self._sync_membership(boundary)
        self._settle_fact(
            boundary=boundary,
            affected_instruments=tuple(self.options),
            countable=False,
            observation_reason="OPTION_METADATA",
        )
        self._ensure_combo_catalog_refresh(boundary)
        return True

    def _complete_option_catalog_if_ready(self) -> None:
        self.option_catalog.complete = (
            self.option_catalog.source_complete and not self._option_metadata_pending
        )

    def _sync_membership(self, boundary: FactBoundary) -> None:
        if self.clock is None:
            return
        try:
            trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        except ContinuityGap:
            return
        for name in set(self.catalog_options) & set(self.options):
            previous = self.options[name]
            current = self.catalog_options[name]
            if (
                previous.expiration_timestamp_ms,
                previous.strike,
                previous.option_type,
            ) != (
                current.expiration_timestamp_ms,
                current.strike,
                current.option_type,
            ):
                raise PublicProtocolIncompatibility(f"same-name option identity changed: {name}")
        desired = {
            name: instrument
            for name, instrument in self.catalog_options.items()
            if classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            ).classification
            is not TimeApplicability.OUT_OF_MONITOR_SCOPE
        }
        additions = tuple(sorted(set(desired) - set(self.options)))
        removals = tuple(sorted(set(self.options) - set(desired)))
        updates = tuple(
            sorted(
                name
                for name in set(desired) & set(self.options)
                if desired[name] != self.options[name]
            )
        )
        for name in removals:
            tracker = self.trackers.get(name)
            if tracker is not None:
                transition = tracker.membership_loss(causal_seq=self._causal_seq)
                self._record_episode_end(transition.ended_episode, boundary.received_monotonic_ms)
            self.options.pop(name, None)
            self.results.pop(name, None)
            self.tickers.pop(name, None)
            self._ticker_generations.pop(name, None)
            self._ticker_currentness_latches.pop(name, None)
            self._ticker_unavailable.pop(name, None)
            self.option_books.pop(name, None)
            self._last_observation_identity.pop(name, None)
            self._last_index_tail_identity.pop(name, None)
        for name in additions:
            self.options[name] = desired[name]
            self.option_books[name] = ContinuousOrderBook(name)
            self.trackers.setdefault(
                name,
                EpisodeTracker(
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    instrument_name=name,
                ),
            )
        for name in updates:
            self.options[name] = desired[name]
        if removals:
            channels = tuple(
                channel
                for name in removals
                for channel in (ticker_channel(name), book_channel(name))
                if self.channel_state(channel)
                not in {ChannelState.UNSUBSCRIBED, ChannelState.RETIRED}
            )
            if channels:
                self._plan_channel_change(
                    channels,
                    subscribe=False,
                    origin_boundary=boundary,
                    failure_scope=FailureScope.OPTION,
                )
        missing_option_channels = tuple(
            channel
            for name in sorted(desired)
            for channel in (ticker_channel(name), book_channel(name))
            if self.channel_state(channel) in {ChannelState.UNSUBSCRIBED, ChannelState.RETIRED}
        )
        if missing_option_channels:
            self._plan_channel_change(
                missing_option_channels,
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=FailureScope.OPTION,
            )
        if self.channel_state(INDEX_CHANNEL) in {
            ChannelState.UNSUBSCRIBED,
            ChannelState.RETIRED,
        }:
            self._index_resubscribe_pending = True
            self._plan_channel_change(
                (INDEX_CHANNEL,),
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )

    def _apply_index(self, payload: object, boundary: FactBoundary) -> bool:
        if self.clock is None:
            return False
        try:
            data = require_mapping(payload, "index notification")
            if require_str(data.get("index_name"), "index.index_name") != "btc_usdc":
                raise SourceDataError("unexpected index_name")
            self.index.accept_tick(
                source_timestamp_ms=require_int(data.get("timestamp"), "index.timestamp"),
                price=data.get("price"),
                causal_seq=self._causal_seq,
            )
        except (ContinuityGap, SourceDataError, ValueError):
            if not self._index_gap_active:
                self.diagnostics.index_gap_count += 1
                self._index_gap_active = True
            self.index.gap()
            self._index_coverage_generation = None
            self.platform.invalidate_fresh_index_coverage("INDEX_CONTINUITY_GAP")
            if not self._index_resubscribe_pending:
                self._index_resubscribe_pending = True
                self._plan_resubscribe(
                    INDEX_CHANNEL,
                    boundary,
                    failure_scope=FailureScope.CLOCK_INDEX,
                )
            self._settle_fact(
                boundary=boundary,
                affected_instruments=tuple(self.options),
                countable=False,
                observation_reason="INDEX_CONTINUITY_GAP",
            )
            return False
        trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        self.index.seal_ready(trusted.lower_ms)
        self._index_gap_active = False
        self.platform.note_fresh_index_coverage()
        self._settle_fact(
            boundary=boundary,
            affected_instruments=tuple(self.options),
            countable=True,
            observation_reason=None,
        )
        return True

    def _ticker_generation(self, instrument_name: str) -> int:
        generation = self._ticker_generations.get(instrument_name)
        if generation is not None:
            return generation
        slot = self._channels.get(ticker_channel(instrument_name))
        generation = slot.generation if slot is not None else 0
        self._ticker_generations[instrument_name] = generation
        return generation

    def _request_ticker_resubscribe_once(
        self,
        instrument_name: str,
        boundary: FactBoundary,
    ) -> None:
        channel = ticker_channel(instrument_name)
        slot = self._channels.get(channel)
        if slot is not None and slot.resync_requested:
            return
        self._plan_resubscribe(
            channel,
            boundary,
            failure_scope=FailureScope.OPTION,
        )

    def _latch_ticker_currentness(
        self,
        instrument_name: str,
        *,
        generation: int,
        source_timestamp_ms: int,
        reason: str,
        boundary: FactBoundary,
    ) -> None:
        previous = self._ticker_currentness_latches.get(instrument_name)
        if previous is not None and previous.generation == generation:
            return
        self._ticker_currentness_latches[instrument_name] = _TickerCurrentnessLatch(
            generation=generation,
            source_timestamp_ms=source_timestamp_ms,
            reason=reason,
        )
        self._request_ticker_resubscribe_once(instrument_name, boundary)

    def _current_ticker(
        self,
        instrument_name: str,
        trusted: TimeInterval,
        boundary: FactBoundary,
    ) -> tuple[TickerState | None, str, bool]:
        unavailable = self._ticker_unavailable.get(instrument_name)
        latch = self._ticker_currentness_latches.get(instrument_name)
        if latch is not None:
            return None, latch.reason, True
        if unavailable is not None:
            return None, unavailable[0], unavailable[1]
        ticker = self.tickers.get(instrument_name)
        if ticker is None:
            return None, "FORWARD_TICKER_UNKNOWN", False
        if ticker.source_timestamp_ms > trusted.upper_ms:
            self._latch_ticker_currentness(
                instrument_name,
                generation=self._ticker_generation(instrument_name),
                source_timestamp_ms=ticker.source_timestamp_ms,
                reason="TICKER_TIMESTAMP_AHEAD",
                boundary=boundary,
            )
            return None, "TICKER_TIMESTAMP_AHEAD", True
        if (
            trusted.upper_ms
            > ticker.source_timestamp_ms
            + self.policy.runtime_limits.ticker_source_stale_deadline_ms
        ):
            self._latch_ticker_currentness(
                instrument_name,
                generation=self._ticker_generation(instrument_name),
                source_timestamp_ms=ticker.source_timestamp_ms,
                reason="TICKER_SOURCE_STALE",
                boundary=boundary,
            )
            return None, "TICKER_SOURCE_STALE", True
        return ticker, "FORWARD_TICKER_UNKNOWN", False

    def _apply_ticker(
        self,
        instrument_name: str,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        if instrument_name not in self.options:
            return False
        try:
            ticker = parse_ticker(payload, instrument_name)
        except ValueError:
            self.tickers.pop(instrument_name, None)
            self._ticker_generations.pop(instrument_name, None)
            self._ticker_unavailable[instrument_name] = ("TICKER_INVALID", False)
            self._settle_fact(
                boundary=boundary,
                affected_instruments=(instrument_name,),
                countable=False,
                observation_reason="TICKER_INVALID",
            )
            return False
        channel = ticker_channel(instrument_name)
        slot = self._channels.get(channel)
        generation = slot.generation if slot is not None else 0
        if self.clock is not None:
            try:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
            except ContinuityGap:
                trusted = None
            if trusted is not None and ticker.source_timestamp_ms > trusted.upper_ms:
                self._latch_ticker_currentness(
                    instrument_name,
                    generation=generation,
                    source_timestamp_ms=ticker.source_timestamp_ms,
                    reason="TICKER_TIMESTAMP_AHEAD",
                    boundary=boundary,
                )
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=(instrument_name,),
                    countable=False,
                    observation_reason="TICKER_TIMESTAMP_AHEAD",
                )
                return False
        latch = self._ticker_currentness_latches.get(instrument_name)
        if latch is not None:
            recovered = (
                generation != latch.generation
                and ticker.source_timestamp_ms > latch.source_timestamp_ms
            )
            if not recovered:
                if generation != latch.generation:
                    self._ticker_currentness_latches[instrument_name] = _TickerCurrentnessLatch(
                        generation=generation,
                        source_timestamp_ms=max(
                            latch.source_timestamp_ms,
                            ticker.source_timestamp_ms,
                        ),
                        reason=latch.reason,
                    )
                    self._request_ticker_resubscribe_once(instrument_name, boundary)
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=(instrument_name,),
                    countable=False,
                    observation_reason=latch.reason,
                )
                return True
            self._ticker_currentness_latches.pop(instrument_name, None)
        previous = self.tickers.get(instrument_name)
        if previous is not None and ticker.source_timestamp_ms < previous.source_timestamp_ms:
            self.tickers.pop(instrument_name, None)
            self._ticker_generations.pop(instrument_name, None)
            self._ticker_unavailable[instrument_name] = (
                "TICKER_CONTINUITY_GAP",
                True,
            )
            self._settle_fact(
                boundary=boundary,
                affected_instruments=(instrument_name,),
                countable=False,
                observation_reason="TICKER_CONTINUITY_GAP",
            )
            self._plan_resubscribe(
                ticker_channel(instrument_name),
                boundary,
                failure_scope=FailureScope.OPTION,
            )
            return False
        self.tickers[instrument_name] = ticker
        self._ticker_generations[instrument_name] = generation
        self._ticker_unavailable.pop(instrument_name, None)
        countable = previous is None or ticker.forward_usdc != previous.forward_usdc
        self._settle_fact(
            boundary=boundary,
            affected_instruments=(instrument_name,),
            countable=countable,
            observation_reason=None,
        )
        return True

    def _apply_book(
        self,
        instrument_name: str,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        if instrument_name in self.options:
            book = self.option_books.setdefault(
                instrument_name,
                ContinuousOrderBook(instrument_name),
            )
            try:
                changed = book.apply(payload, boundary.received_monotonic_ms)
            except (ContinuityGap, SourceDataError):
                book.invalidate("OPTION_BOOK_GAP")
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=(instrument_name,),
                    countable=False,
                    observation_reason="OPTION_BOOK_GAP",
                )
                self.option_books[instrument_name] = ContinuousOrderBook(instrument_name)
                self._plan_resubscribe(
                    book_channel(instrument_name),
                    boundary,
                    failure_scope=FailureScope.OPTION,
                )
                return False
            if changed:
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=(instrument_name,),
                    countable=True,
                    observation_reason=None,
                )
            return True
        if instrument_name not in self.combos:
            return False
        book = self.combo_books.setdefault(
            instrument_name,
            ContinuousOrderBook(instrument_name),
        )
        try:
            changed = book.apply(payload, boundary.received_monotonic_ms)
        except (ContinuityGap, SourceDataError):
            book.invalidate("COMBO_BOOK_GAP")
            changed = True
            valid = False
            self._plan_resubscribe(
                book_channel(instrument_name),
                boundary,
                failure_scope=FailureScope.COMBO_LAYER,
            )
        else:
            valid = True
        if changed:
            self._evaluate_atomic_for_combo(instrument_name)
        return valid

    def _plan_resubscribe(
        self,
        channel: str,
        boundary: FactBoundary,
        *,
        failure_scope: FailureScope,
    ) -> None:
        if channel == INDEX_CHANNEL:
            self.diagnostics.index_resubscribe_count += 1
        else:
            self.diagnostics.option_channel_resync_count += 1
        state = self.channel_state(channel)
        slot = self._channels.setdefault(channel, _ChannelSlot())
        slot.desired_subscribed = True
        slot.resync_requested = True
        slot.retry_failure_scope = failure_scope
        if state in {ChannelState.UNSUBSCRIBED, ChannelState.RETIRED}:
            slot.resync_requested = False
            self._issue_channel_change(
                (channel,),
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=failure_scope,
            )
            return
        if state is ChannelState.ACKNOWLEDGED:
            self._issue_channel_change(
                (channel,),
                subscribe=False,
                origin_boundary=boundary,
                failure_scope=failure_scope,
            )

    def _schedule_combo_refresh(
        self,
        boundary: FactBoundary,
        *,
        trailing: bool,
    ) -> PendingRpc:
        del trailing
        self._combo_refresh_generation += 1
        request = self._schedule(
            purpose=RpcPurpose.COMBO_CATALOG,
            method="public/get_combos",
            params={"currency": "USDC"},
            scope="COMBO_CATALOG",
            generation=self._combo_refresh_generation,
            origin_boundary=boundary,
            failure_scope=FailureScope.COMBO_LAYER,
        )
        self._combo_refresh_origin_revision[request.request_id] = self._combo_lifecycle_revision
        return request

    def _ensure_combo_catalog_refresh(self, boundary: FactBoundary) -> None:
        if (
            self.option_catalog.complete
            and not self.combo_catalog.complete
            and self._combo_refresh_request_id is None
        ):
            self._schedule_combo_refresh(boundary, trailing=False)

    def _apply_combo_snapshot(
        self,
        request: PendingRpc,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        reconciliation_intact = (
            self.combo_catalog.source_complete if self.combo_catalog.buffering else True
        )
        refresh_revision = self._combo_refresh_origin_revision.pop(
            request.request_id,
            -1,
        )
        try:
            values = require_list(payload, "public/get_combos result")
        except SourceDataError:
            values = []
            complete = False
        else:
            complete = True
        if not self.option_catalog.complete:
            self.combo_catalog.mark_incomplete()
            self._combo_refresh_request_id = None
            self._next_combo_catalog_recovery_ms = (
                boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._refresh_atomic_current()
            return complete
        crossed_before_commit = refresh_revision != self._combo_lifecycle_revision
        if crossed_before_commit and not self.combo_catalog.buffering:
            self.combo_catalog.mark_incomplete()
            self._combo_refresh_request_id = None
            self._schedule_combo_refresh(boundary, trailing=True)
            self._next_combo_catalog_recovery_ms = (
                boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._refresh_atomic_current()
            return complete
        summaries: dict[str, dict[str, object]] = {}
        fingerprints: dict[str, tuple[object, ...]] = {}
        for value in values:
            try:
                summary = require_mapping(value, "combo")
                combo_name = require_str(summary.get("id"), "combo.id")
                state = require_str(summary.get("state"), "combo.state")
                raw_legs = require_list(summary.get("legs"), "combo.legs")
                leg_names: list[str] = []
                legs: list[tuple[str, Decimal]] = []
                for index, raw_leg in enumerate(raw_legs):
                    leg = require_mapping(raw_leg, f"combo.legs[{index}]")
                    leg_name = require_str(
                        leg.get("instrument_name"),
                        f"combo.legs[{index}].instrument_name",
                    )
                    leg_names.append(leg_name)
                    legs.append(
                        (
                            leg_name,
                            Decimal(str(leg.get("amount"))),
                        )
                    )
            except SourceDataError:
                complete = False
                continue
            except (ValueError, ArithmeticError):
                complete = False
                continue
            if state not in {"active", "inactive"}:
                complete = False
                continue
            if state != "active":
                continue
            if len(leg_names) != 2 or any(name not in self.options for name in leg_names):
                continue
            summary_fingerprint = (state, tuple(legs))
            summaries[combo_name] = summary
            fingerprints[combo_name] = summary_fingerprint

        removed = set(self._combo_summaries) - set(summaries) if complete else set()
        for combo_name in removed:
            self.combos.pop(combo_name, None)
            self.combo_books.pop(combo_name, None)
            self._combo_metadata_pending.pop(combo_name, None)
        if complete:
            effective_summaries = summaries
            effective_fingerprints = fingerprints
        else:
            effective_summaries = {**self._combo_summaries, **summaries}
            effective_fingerprints = {
                **self._combo_summary_fingerprints,
                **fingerprints,
            }
        self._combo_summaries = effective_summaries
        for combo_name, stored_fingerprint in effective_fingerprints.items():
            if (
                self._combo_summary_fingerprints.get(combo_name) == stored_fingerprint
                and combo_name in self.combos
            ):
                continue
            if (
                self._combo_summary_fingerprints.get(combo_name) == stored_fingerprint
                and combo_name in self._combo_metadata_pending
            ):
                continue
            self.combos.pop(combo_name, None)
            self._combo_metadata_revisions[combo_name] += 1
            generation = self._combo_metadata_revisions[combo_name]
            self._combo_metadata_pending[combo_name] = generation
            self._schedule(
                purpose=RpcPurpose.COMBO_METADATA,
                method="public/get_instrument",
                params={"instrument_name": combo_name},
                scope=combo_name,
                generation=generation,
                origin_boundary=boundary,
                failure_scope=FailureScope.COMBO_LAYER,
            )
        self._combo_summary_fingerprints = effective_fingerprints
        self.combo_catalog.source_complete = complete and reconciliation_intact
        if self.combo_catalog.buffering:
            buffered = self.combo_catalog.reconcile()
            for event in buffered:
                try:
                    self._apply_combo_lifecycle(event, boundary)
                except (SourceDataError, ValueError):
                    self.combo_catalog.mark_incomplete()
        crossed_lifecycle = refresh_revision != self._combo_lifecycle_revision
        if crossed_lifecycle:
            self.combo_catalog.source_complete = False
        self._complete_combo_catalog_if_ready()
        self._combo_refresh_request_id = None
        if crossed_lifecycle:
            self._schedule_combo_refresh(boundary, trailing=True)
        self._next_combo_catalog_recovery_ms = (
            None
            if self.combo_catalog.complete
            else boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        if complete:
            self.diagnostics.combo_authoritative_refresh_success_count += 1
        else:
            self.diagnostics.combo_authoritative_refresh_failure_count += 1
        self._sync_combo_subscriptions(boundary)
        self._refresh_atomic_current()
        return complete

    def _apply_combo_lifecycle(
        self,
        payload: object,
        boundary: FactBoundary,
    ) -> None:
        data = require_mapping(payload, "combo lifecycle")
        combo_name = require_str(
            data.get("instrument_name"),
            "combo lifecycle.instrument_name",
        )
        state = require_str(data.get("state"), "combo lifecycle.state")
        self._combo_lifecycle_revision += 1
        self._combo_metadata_revisions[combo_name] += 1
        self._combo_lifecycle_state[combo_name] = state
        self._combo_metadata_pending.pop(combo_name, None)
        self.combos.pop(combo_name, None)
        self.combo_books.pop(combo_name, None)
        self._combo_summaries.pop(combo_name, None)
        self._combo_summary_fingerprints.pop(combo_name, None)
        self.combo_catalog.mark_incomplete()
        self._sync_combo_subscriptions(boundary)
        self._refresh_atomic_current()
        if state not in INSTRUMENT_LIFECYCLE_STATES:
            raise SourceDataError("combo lifecycle.state is unsupported")

    def _apply_combo_metadata(
        self,
        request: PendingRpc,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        if (
            self._combo_metadata_pending.get(request.scope) != request.generation
            or self._combo_metadata_revisions[request.scope] != request.generation
        ):
            if self._combo_metadata_pending.get(request.scope) == request.generation:
                self._combo_metadata_pending.pop(request.scope, None)
            return True
        summary = self._combo_summaries.get(request.scope)
        if summary is None:
            self._combo_metadata_pending.pop(request.scope, None)
            self._complete_combo_catalog_if_ready()
            return False
        try:
            combo = parse_combo_instrument(summary, payload)
        except SourceDataError:
            self._combo_metadata_pending.pop(request.scope, None)
            self.combo_catalog.mark_incomplete()
            return False
        self._combo_metadata_pending.pop(request.scope, None)
        if combo is None:
            if _is_valid_irrelevant_combo_metadata(payload, request.scope):
                self._combo_summaries.pop(request.scope, None)
                self._combo_summary_fingerprints.pop(request.scope, None)
                self.combos.pop(request.scope, None)
                self.combo_books.pop(request.scope, None)
                self._complete_combo_catalog_if_ready()
                if self.combo_catalog.complete:
                    self._next_combo_catalog_recovery_ms = None
                self._sync_combo_subscriptions(boundary)
                self._refresh_atomic_current()
                return True
            self.combo_catalog.mark_incomplete()
            return False
        self.combos[combo.instrument_name] = combo
        self.combo_books.setdefault(
            combo.instrument_name,
            ContinuousOrderBook(combo.instrument_name),
        )
        self._complete_combo_catalog_if_ready()
        if self.combo_catalog.complete:
            self._next_combo_catalog_recovery_ms = None
        self._sync_combo_subscriptions(boundary)
        self._refresh_atomic_current()
        return True

    def _complete_combo_catalog_if_ready(self) -> None:
        self.combo_catalog.complete = (
            self.combo_catalog.source_complete
            and not self._combo_metadata_pending
            and set(self._combo_summaries) == set(self.combos)
        )

    def settle_fact(
        self,
        *,
        boundary: FactBoundary,
        affected_instruments: tuple[str, ...],
        countable: bool,
        observation_reason: str | None = None,
    ) -> None:
        self._settle_fact(
            boundary=boundary,
            affected_instruments=affected_instruments,
            countable=countable,
            observation_reason=observation_reason,
        )

    def _settle_clock_gap(self, boundary: FactBoundary) -> None:
        self._first_joint_witness_ms = None
        self.aggregate_results.clear()
        for name in self.trackers:
            self._commit_forced_unknown(
                name,
                reason="CLOCK_GAP",
                boundary=boundary,
                continuity_gap=True,
            )
        self._transition_coverage(CoverageState.UNKNOWN, boundary.received_monotonic_ms)

    def _invalidate_clock_index(self, boundary: FactBoundary, *, reason: str) -> None:
        self._settle_clock_gap(boundary)
        self.clock = None
        self._last_time_currentness_token = None
        self.index.gap()
        self._index_coverage_generation = None
        self.platform.invalidate_fresh_index_coverage(reason)
        if self._session_epoch is None or self._session_epoch in self._retired_epochs:
            return
        if not any(
            request.purpose is RpcPurpose.CLOCK_BOOTSTRAP for request in self.pending_rpcs.values()
        ):
            self._schedule(
                purpose=RpcPurpose.CLOCK_BOOTSTRAP,
                method="public/get_time",
                params={},
                scope="CLOCK_INDEX",
                generation=None,
                origin_boundary=boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )
        if not self._index_resubscribe_pending:
            self._index_resubscribe_pending = True
            self._plan_resubscribe(
                INDEX_CHANNEL,
                boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )

    def _time_currentness_token(
        self,
        trusted: TimeInterval,
    ) -> tuple[object, ...]:
        catalog_membership = tuple(
            sorted(
                (
                    name,
                    instrument.expiration_timestamp_ms,
                    instrument.strike,
                    instrument.option_type.value,
                    classify_time_applicability(
                        self.policy,
                        expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                        trusted_time=trusted,
                        option_type=instrument.option_type,
                    ).classification.value,
                )
                for name, instrument in self.catalog_options.items()
            )
        )
        detector_currentness: list[tuple[object, ...]] = []
        for name, instrument in sorted(self.options.items()):
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            if applicability.band is None:
                tail_identity: tuple[object, ...] = ()
            else:
                tail = self.index.current_tail(
                    max(applicability.band.lookbacks_minutes),
                    trusted_time=trusted,
                    source_stale_deadline_ms=(
                        self.policy.runtime_limits.index_source_stale_deadline_ms
                    ),
                )
                tail_identity = (
                    tail.status.value,
                    tuple((close.minute_start_ms, close.causal_seq) for close in tail.closes),
                )
            detector_currentness.append(
                (
                    name,
                    applicability.classification.value,
                    applicability.band.band_id if applicability.band is not None else None,
                    tail_identity,
                )
            )
        return (catalog_membership, tuple(detector_currentness))

    def _settle_fact(
        self,
        *,
        boundary: FactBoundary,
        affected_instruments: tuple[str, ...],
        countable: bool,
        observation_reason: str | None,
        acceptance_eligible: bool = True,
    ) -> None:
        if self.clock is None:
            self._update_coverage(boundary.received_monotonic_ms)
            return
        try:
            trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        except ContinuityGap:
            self._invalidate_clock_index(boundary, reason="CLOCK_GAP")
            return

        names = tuple(
            sorted(dict.fromkeys(name for name in affected_instruments if name in self.options))
        )
        countable_names = set(names) if countable else set()
        if self._time_currentness_token(trusted) != self._last_time_currentness_token:
            names = tuple(sorted(self.options))
        prepared: list[ScopeCurrent] = []
        global_gap = False
        global_resubscribe = False
        global_resubscribe_reason: str | None = None
        for name in names:
            instrument = self.options[name]
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            tail = None
            if applicability.band is not None:
                tail = self.index.current_tail(
                    max(applicability.band.lookbacks_minutes),
                    trusted_time=trusted,
                    source_stale_deadline_ms=(
                        self.policy.runtime_limits.index_source_stale_deadline_ms
                    ),
                )
                if tail.status in {
                    IndexTailStatus.WINDOW_GAP,
                    IndexTailStatus.SOURCE_STALE,
                    IndexTailStatus.CONTINUITY_GAP,
                }:
                    global_gap = True
                if tail.status in {
                    IndexTailStatus.SOURCE_STALE,
                    IndexTailStatus.CONTINUITY_GAP,
                }:
                    global_resubscribe = True
                    if tail.status is IndexTailStatus.CONTINUITY_GAP:
                        global_resubscribe_reason = "INDEX_CONTINUITY_GAP"
                    elif global_resubscribe_reason is None:
                        global_resubscribe_reason = "INDEX_SOURCE_STALE"
        if global_gap:
            self._first_joint_witness_ms = None
            names = tuple(sorted(self.options))
            prepared.clear()
        if global_resubscribe:
            if not self._index_gap_active:
                self.diagnostics.index_gap_count += 1
                self._index_gap_active = True
            self.platform.invalidate_fresh_index_coverage(
                global_resubscribe_reason or "INDEX_CONTINUITY_GAP"
            )
            if not self._index_resubscribe_pending:
                self._index_resubscribe_pending = True
                self._plan_resubscribe(
                    INDEX_CHANNEL,
                    boundary,
                    failure_scope=FailureScope.CLOCK_INDEX,
                )

        for name in names:
            instrument = self.options[name]
            tracker = self.trackers[name]
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            tail = (
                self.index.current_tail(
                    max(applicability.band.lookbacks_minutes),
                    trusted_time=trusted,
                    source_stale_deadline_ms=(
                        self.policy.runtime_limits.index_source_stale_deadline_ms
                    ),
                )
                if applicability.band is not None
                else None
            )
            band_id = applicability.band.band_id if applicability.band is not None else None
            if not self.platform.usable:
                current = CurrentEvaluation(
                    disposition=CurrentDisposition.UNKNOWN,
                    reason=self.platform.reason,
                    known_evaluation=False,
                    full_formula_evaluation=False,
                    band_id=band_id,
                    continuity_gap=self.platform.reason
                    in {
                        "CLOCK_GAP",
                        "INDEX_GAP",
                        "INDEX_SOURCE_STALE",
                        "INDEX_CONTINUITY_GAP",
                    },
                )
            elif name in self._option_lifecycle_unavailable:
                current = CurrentEvaluation(
                    disposition=CurrentDisposition.UNKNOWN,
                    reason=self._option_lifecycle_unavailable[name],
                    known_evaluation=False,
                    full_formula_evaluation=False,
                    band_id=band_id,
                    continuity_gap=False,
                )
            else:
                current_ticker, ticker_reason, ticker_continuity_gap = self._current_ticker(
                    name,
                    trusted,
                    boundary,
                )
                baseline_reason = (
                    _index_tail_reason(tail.status)
                    if tail is not None and tail.status is not IndexTailStatus.AVAILABLE
                    else "INDEX_WARMUP"
                )
                current = calculate_current_evaluation(
                    policy=self.policy,
                    instrument=instrument,
                    trusted_time=trusted,
                    causal_seq=self._causal_seq,
                    option_book=self.option_books.get(name),
                    ticker=current_ticker,
                    causal_closes=(
                        tail.prices
                        if tail is not None and tail.status is IndexTailStatus.AVAILABLE
                        else None
                    ),
                    baseline_unavailable_reason=baseline_reason,
                    ticker_unavailable_reason=ticker_reason,
                    ticker_continuity_gap=ticker_continuity_gap,
                )
            baseline_identity = (
                (tail.status.value, tuple(tail.closes))
                if tail is not None
                else (applicability.classification.value,)
            )
            identity = detector_observation_identity(
                policy=self.policy,
                instrument=instrument,
                trusted_time=trusted,
                option_book=self.option_books.get(name),
                ticker=self.tickers.get(name),
                baseline_identity=baseline_identity,
            )
            observation_eligible = (
                name in countable_names
                and current.disposition is CurrentDisposition.RICHNESS
                and self._last_observation_identity.get(name) != identity
            )
            prepared.append(
                ScopeCurrent(
                    instrument=instrument,
                    current=current,
                    observation_identity=identity,
                    index_tail_identity=(baseline_identity if tail is not None else None),
                    observation_eligible=observation_eligible,
                    previous_tracker_state=tracker.state,
                    previous_episode_id=tracker.episode_id,
                )
            )

        current_by_scope: dict[
            tuple[int, OptionType, str | None],
            list[ScopeCurrent],
        ] = {}
        for item in prepared:
            scope_key = (
                item.instrument.expiration_timestamp_ms,
                item.instrument.option_type,
                item.current.band_id,
            )
            current_by_scope.setdefault(scope_key, []).append(item)
        snapshots = tuple(
            ScopeSnapshot(
                boundary=boundary,
                trusted_time=trusted,
                clock_revision=self._clock_revision,
                current=tuple(current),
                boundary_countable=countable,
                acceptance_eligible=acceptance_eligible,
                observation_reason=observation_reason,
            )
            for current in current_by_scope.values()
        )

        evaluated: list[tuple[OptionInstrument, EvaluationResult, TrackerState, str | None]] = []
        evaluated_by_name: dict[
            str,
            tuple[OptionInstrument, EvaluationResult, TrackerState, str | None],
        ] = {}
        for snapshot in snapshots:
            for item in snapshot.current:
                instrument = item.instrument
                current = item.current
                eligible = item.observation_eligible
                tracker = self.trackers[instrument.instrument_name]
                previous_result = self.results.get(instrument.instrument_name)
                previous_tail = self._last_index_tail_identity.get(instrument.instrument_name)
                current_tail = item.index_tail_identity
                rolled_available_minute = (
                    previous_tail is not None
                    and current_tail is not None
                    and previous_tail[0] == IndexTailStatus.AVAILABLE.value
                    and current_tail[0] == IndexTailStatus.AVAILABLE.value
                    and previous_tail != current_tail
                )
                if (
                    previous_result is not None
                    and previous_result.band_id is not None
                    and current.band_id is not None
                    and previous_result.band_id != current.band_id
                    and tracker.state
                    not in {
                        TrackerState.BAND_SUSPENDED,
                        TrackerState.INDEX_TAIL_PENDING,
                    }
                ):
                    tracker.suspend_for_band_boundary()
                elif rolled_available_minute and tracker.state not in {
                    TrackerState.BAND_SUSPENDED,
                    TrackerState.INDEX_TAIL_PENDING,
                }:
                    tracker.suspend_for_index_tail()
                transition = apply_current_evaluation(
                    tracker=tracker,
                    current=current,
                    causal_seq=snapshot.boundary.causal_seq,
                    observation_eligible=eligible,
                )
                if current.disposition is CurrentDisposition.RICHNESS:
                    self._last_observation_identity[instrument.instrument_name] = (
                        item.observation_identity
                    )
                elif (
                    instrument.instrument_name not in self._ticker_currentness_latches
                    and current.reason not in {"TICKER_SOURCE_STALE", "TICKER_TIMESTAMP_AHEAD"}
                ):
                    self._last_observation_identity.pop(instrument.instrument_name, None)
                if current_tail is None:
                    self._last_index_tail_identity.pop(
                        instrument.instrument_name,
                        None,
                    )
                else:
                    self._last_index_tail_identity[instrument.instrument_name] = current_tail
                result = EvaluationResult(
                    detector_state=tracker.detector_state,
                    reason=current.reason,
                    known_evaluation=current.known_evaluation,
                    full_formula_evaluation=current.full_formula_evaluation,
                    band_id=current.band_id,
                    transition=transition,
                    observation_eligible=eligible,
                    observation_reason=(
                        None
                        if eligible
                        else snapshot.observation_reason or "NON_COUNTABLE_FACT_BOUNDARY"
                    ),
                    calculation=current.calculation,
                    current_evaluation=current,
                )
                self.results[instrument.instrument_name] = result
                if current.reason is not None and not current.known_evaluation:
                    self._record_unknown(instrument.instrument_name, current.reason)
                else:
                    self._last_unknown_reason[instrument.instrument_name] = None
                self._record_episode_end(
                    transition.ended_episode,
                    boundary.received_monotonic_ms,
                )
                if tracker.episode_id is not None:
                    episode_id = tracker.episode_id
                    if tracker.state in {
                        TrackerState.BAND_SUSPENDED,
                        TrackerState.INDEX_TAIL_PENDING,
                    }:
                        self._episode_pause_started_ms.setdefault(
                            episode_id,
                            boundary.received_monotonic_ms,
                        )
                        self._episode_last_trusted_ms[episode_id] = boundary.received_monotonic_ms
                    elif (
                        current.known_evaluation
                        and tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                    ):
                        paused_at = self._episode_pause_started_ms.pop(
                            episode_id,
                            None,
                        )
                        if paused_at is not None:
                            self._episode_paused_duration_ms[episode_id] += max(
                                0,
                                boundary.received_monotonic_ms - paused_at,
                            )
                        self._episode_last_trusted_ms[episode_id] = boundary.received_monotonic_ms
                if (
                    tracker.episode_id is not None
                    and current.known_evaluation
                    and tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                ):
                    self._last_detector_causal_seq[instrument.instrument_name] = (
                        snapshot.boundary.causal_seq
                    )
                value = (
                    instrument,
                    result,
                    item.previous_tracker_state,
                    item.previous_episode_id,
                )
                evaluated.append(value)
                evaluated_by_name[instrument.instrument_name] = value

        for snapshot in snapshots:
            scope_results = [
                (
                    evaluated_by_name[item.instrument.instrument_name][0],
                    evaluated_by_name[item.instrument.instrument_name][1],
                )
                for item in snapshot.current
                if evaluated_by_name[item.instrument.instrument_name][1].band_id is not None
            ]
            if not scope_results:
                continue
            representative = scope_results[0][0]
            aggregate = self._scope_aggregate(representative, snapshot.trusted_time)
            for instrument, result in scope_results:
                if result.transition.activated_episode_id is not None:
                    self._record_activation(
                        instrument,
                        result,
                        aggregate.coverage or DetectorCoverage.DEGRADED,
                        snapshot.trusted_time,
                        boundary.received_monotonic_ms,
                    )
            if snapshot.acceptance_eligible and aggregate.coverage is DetectorCoverage.COMPLETE:
                counter = self._scope_counter(
                    representative.option_type,
                    scope_results[0][1].band_id or "",
                )
                counter.complete_aggregate_detector_evaluation_count += 1
                if any(result.full_formula_evaluation for _, result in scope_results):
                    counter.complete_aggregate_with_full_formula_evaluation_count += 1
                    if self._first_joint_witness_ms is None:
                        self._first_joint_witness_ms = boundary.received_monotonic_ms

        for instrument, result, _state, _episode in evaluated:
            if result.band_id is not None:
                counter = self._scope_counter(instrument.option_type, result.band_id)
                counter.applicable_instrument_count = max(
                    counter.applicable_instrument_count,
                    1,
                )
                if acceptance_eligible and result.known_evaluation:
                    counter.known_per_instrument_detector_evaluation_count += 1
                if acceptance_eligible and result.full_formula_evaluation:
                    counter.known_full_detector_formula_evaluation_count += 1
            tracker = self.trackers[instrument.instrument_name]
            if tracker.episode_id is not None:
                self._evaluate_atomic(tracker)

        self._sync_combo_subscriptions(boundary)
        self._update_coverage(boundary.received_monotonic_ms)
        if set(names) == set(self.options):
            self._last_time_currentness_token = self._time_currentness_token(trusted)

    def _scope_aggregate(
        self,
        instrument: OptionInstrument,
        trusted: TimeInterval,
    ) -> AggregateDetectorResult:
        applicability = classify_time_applicability(
            self.policy,
            expiration_timestamp_ms=instrument.expiration_timestamp_ms,
            trusted_time=trusted,
            option_type=instrument.option_type,
        )
        if applicability.band is None:
            return aggregate_detector(
                (),
                catalog_complete=self.option_catalog.complete,
                has_applicable_scope=False,
            )
        instruments = tuple(
            candidate
            for candidate in self.options.values()
            if candidate.expiration_timestamp_ms == instrument.expiration_timestamp_ms
            and candidate.option_type is instrument.option_type
        )
        states = tuple(
            self.trackers[candidate.instrument_name].detector_state for candidate in instruments
        )
        counter = self._scope_counter(
            instrument.option_type,
            applicability.band.band_id,
        )
        counter.applicable_instrument_count = max(
            counter.applicable_instrument_count,
            len(instruments),
        )
        aggregate = aggregate_detector(
            states,
            catalog_complete=self.option_catalog.complete,
            has_applicable_scope=bool(instruments),
        )
        self.aggregate_results[
            (
                instrument.expiration_timestamp_ms,
                instrument.option_type,
                applicability.band.band_id,
            )
        ] = aggregate
        return aggregate

    def _record_activation(
        self,
        instrument: OptionInstrument,
        result: EvaluationResult,
        coverage: DetectorCoverage,
        trusted: TimeInterval,
        monotonic_ms: int,
    ) -> None:
        episode_id = result.transition.activated_episode_id
        calculation = result.calculation
        if episode_id is None or calculation is None:
            raise RuntimeError("activation lacks full calculation")
        counter = self._scope_counter(instrument.option_type, calculation.band.band_id)
        counter.distinct_anomaly_episode_count += 1
        counter.anomaly_activation_transition_count += 1
        self._episode_started_ms[episode_id] = monotonic_ms
        self._episode_last_trusted_ms[episode_id] = monotonic_ms
        self._episode_paused_duration_ms[episode_id] = 0
        self._episode_option_type[episode_id] = instrument.option_type
        event = project_anomaly_event(
            AnomalyEvidence(
                code_identity=self.code_identity,
                runtime_identity=self.runtime_identity,
                policy_identity=self.policy.identity,
                episode_identity=episode_id,
                causal_seq=self._causal_seq,
                instrument_name=instrument.instrument_name,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                option_type=instrument.option_type.value,
                activation_band_id=calculation.band.band_id,
                aggregate_coverage=coverage,
                target_base_quantity_btc=self.policy.target_base_quantity_btc,
                rule=calculation.rule,
                baseline=calculation.baseline,
                trusted_time=trusted,
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

    def _record_episode_end(self, ended: EpisodeEnd | None, monotonic_ms: int) -> None:
        if ended is None:
            return
        self._episode_end_counts[ended.reason.value] += 1
        end_ms = (
            self._episode_last_trusted_ms.get(ended.episode_id, monotonic_ms)
            if ended.reason
            in {
                EpisodeEndReason.UNKNOWN_AT_GAP,
                EpisodeEndReason.UNKNOWN_DETECTOR,
                EpisodeEndReason.OUT_OF_BASELINE_SCOPE,
            }
            else monotonic_ms
        )
        pause_started = self._episode_pause_started_ms.pop(ended.episode_id, None)
        paused_duration = self._episode_paused_duration_ms.pop(ended.episode_id, 0)
        if pause_started is not None and end_ms > pause_started:
            paused_duration += end_ms - pause_started
        duration = max(
            0,
            end_ms - self._episode_started_ms.pop(ended.episode_id, end_ms) - paused_duration,
        )
        self._known_active_duration_ms[ended.reason.value] += duration
        option_type = self._episode_option_type.pop(ended.episode_id, None)
        self._episode_last_trusted_ms.pop(ended.episode_id, None)
        if option_type is not None:
            counter = self._scope_counter(option_type, ended.activation_band_id)
            counter.anomaly_end_count_by_reason[ended.reason.value] += 1
            counter.known_active_duration_ms_sum_by_end_reason[ended.reason.value] += duration
        previous_atomic = self.atomic_states.pop(ended.episode_id, None)
        if (
            previous_atomic is not None
            and previous_atomic is not PublicAtomicQuoteState.NOT_EVALUATED
        ):
            state = PublicAtomicQuoteState.NOT_EVALUATED.value
            self._atomic_transition_counts[state] += 1
            if option_type is not None:
                counter = self._scope_counter(option_type, ended.activation_band_id)
                counter.public_atomic_quote_state_transition_count[state] += 1

    def _record_unknown(self, instrument_name: str, reason: str) -> None:
        if self._last_unknown_reason.get(instrument_name) == reason:
            return
        self._last_unknown_reason[instrument_name] = reason
        self._unknown_counts[reason] += 1

    def _commit_forced_unknown(
        self,
        instrument_name: str,
        *,
        reason: str,
        boundary: FactBoundary,
        continuity_gap: bool,
    ) -> None:
        tracker = self.trackers.get(instrument_name)
        if tracker is None:
            return
        previous = self.results.get(instrument_name)
        current = CurrentEvaluation(
            disposition=CurrentDisposition.UNKNOWN,
            reason=reason,
            known_evaluation=False,
            full_formula_evaluation=False,
            band_id=(previous.band_id if previous is not None else tracker.activation_band_id),
            continuity_gap=continuity_gap,
        )
        transition = apply_current_evaluation(
            tracker=tracker,
            current=current,
            causal_seq=boundary.causal_seq,
            observation_eligible=False,
        )
        self.results[instrument_name] = EvaluationResult(
            detector_state=tracker.detector_state,
            reason=reason,
            known_evaluation=False,
            full_formula_evaluation=False,
            band_id=current.band_id,
            transition=transition,
            observation_eligible=False,
            observation_reason=reason,
            calculation=None,
            current_evaluation=current,
        )
        if instrument_name not in self._ticker_currentness_latches:
            self._last_observation_identity.pop(instrument_name, None)
        self._last_index_tail_identity.pop(instrument_name, None)
        self._record_unknown(instrument_name, reason)
        self._record_episode_end(
            transition.ended_episode,
            boundary.received_monotonic_ms,
        )

    def _transition_coverage(self, state: CoverageState, monotonic_ms: int) -> None:
        self._coverage.transition(state, monotonic_ms)
        if state is not CoverageState.KNOWN_COMPLETE:
            self._first_joint_witness_ms = None

    def _scope_counter(self, option_type: OptionType, band_id: str) -> ScopeCounts:
        key = (self.policy.identity, option_type, band_id)
        if key not in self._scope_counts:
            self._scope_counts[key] = ScopeCounts(
                self.policy.identity,
                option_type.value,
                band_id,
            )
        return self._scope_counts[key]

    def _evaluate_atomic_for_combo(self, combo_name: str) -> None:
        combo = self.combos.get(combo_name)
        if combo is None:
            return
        for leg in combo.legs:
            tracker = self.trackers.get(leg.instrument_name)
            if tracker is not None:
                self._evaluate_atomic(tracker)

    def _refresh_atomic_current(self) -> None:
        for tracker in self.trackers.values():
            if tracker.episode_id is not None:
                self._evaluate_atomic(tracker)

    def _evaluate_atomic(self, tracker: EpisodeTracker) -> None:
        if tracker.episode_id is None:
            return
        short_leg = self.options.get(tracker.instrument_name)
        if short_leg is None:
            return
        current_options = (
            {
                name: option
                for name, option in self.options.items()
                if name not in self._option_lifecycle_unavailable
            }
            if self._option_positive_scope_safe
            else {}
        )
        unresolved_protective_lifecycle = any(
            name in self._option_lifecycle_unavailable
            and candidate.expiration_timestamp_ms == short_leg.expiration_timestamp_ms
            and candidate.option_type is short_leg.option_type
            and (
                (short_leg.option_type is OptionType.CALL and candidate.strike > short_leg.strike)
                or (short_leg.option_type is OptionType.PUT and candidate.strike < short_leg.strike)
            )
            for name, candidate in self.options.items()
        )
        result = classify_atomic_quotes(
            anomaly_active=tracker.detector_state is DetectorState.ANOMALY_ACTIVE,
            combo_catalog_complete=self.combo_catalog.complete,
            option_catalog_complete=(
                self.option_catalog.complete
                and self._option_positive_scope_safe
                and not unresolved_protective_lifecycle
            ),
            short_leg=short_leg,
            options_by_name=current_options,
            combos=tuple(self.combos.values()),
            combo_books=self.combo_books,
            target_btc=self.policy.target_base_quantity_btc,
        )
        previous = self.atomic_states.get(tracker.episode_id)
        if previous is not result.state:
            self.atomic_states[tracker.episode_id] = result.state
            self._atomic_transition_counts[result.state.value] += 1
            short_type = self.options[tracker.instrument_name].option_type
            if tracker.activation_band_id is None:
                raise RuntimeError("active tracker lacks activation band")
            counter = self._scope_counter(short_type, tracker.activation_band_id)
            counter.public_atomic_quote_state_transition_count[result.state.value] += 1
        if result.state is not PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE:
            return
        for quote in result.quotes:
            combo_name = quote.match.combo_instrument_name
            emitted_key = (tracker.episode_id, combo_name)
            if emitted_key in self._emitted_atomic_quotes:
                continue
            combo = self.combos[combo_name]
            book = self.combo_books[combo_name]
            detector_causal_seq = self._last_detector_causal_seq.get(
                tracker.instrument_name,
                tracker.activation_causal_seq,
            )
            if detector_causal_seq is None or book.source_timestamp_ms is None:
                raise RuntimeError("available atomic quote lacks causal source identity")
            event = project_atomic_event(
                AtomicEvidence(
                    code_identity=self.code_identity,
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    episode_identity=tracker.episode_id,
                    detector_causal_seq=detector_causal_seq,
                    quote_causal_seq=self._causal_seq,
                    short_instrument_name=tracker.instrument_name,
                    combo_legs=(
                        (combo.legs[0].instrument_name, combo.legs[0].amount),
                        (combo.legs[1].instrument_name, combo.legs[1].amount),
                    ),
                    quote=quote,
                    target_base_quantity_btc=self.policy.target_base_quantity_btc,
                    source_timestamp_ms=book.source_timestamp_ms,
                )
            )
            self.writer.write_atomic(event)
            self._emitted_atomic_quotes.add(emitted_key)

    def _sync_combo_subscriptions(self, boundary: FactBoundary) -> None:
        needed: set[str] = set()
        for tracker in self.trackers.values():
            if tracker.detector_state is not DetectorState.ANOMALY_ACTIVE:
                continue
            short = self.options.get(tracker.instrument_name)
            if short is None:
                continue
            for combo in self.combos.values():
                if (
                    match_vertical_combo(
                        short_leg=short,
                        options_by_name=self.options,
                        combo=combo,
                        target_btc=self.policy.target_base_quantity_btc,
                    )
                    is not None
                ):
                    needed.add(combo.instrument_name)
        additions = tuple(sorted(needed - self._subscribed_combo_names))
        removals = tuple(sorted(self._subscribed_combo_names - needed))
        if removals:
            self._subscribed_combo_names.difference_update(removals)
            self._plan_channel_change(
                tuple(book_channel(name) for name in removals),
                subscribe=False,
                origin_boundary=boundary,
                failure_scope=FailureScope.COMBO_LAYER,
            )
            for name in removals:
                self.combo_books.pop(name, None)
        if additions:
            for name in additions:
                self.combo_books[name] = ContinuousOrderBook(name)
            self._subscribed_combo_names.update(additions)
            self._plan_channel_change(
                tuple(book_channel(name) for name in additions),
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=FailureScope.COMBO_LAYER,
            )
        missing_combo_channels = tuple(
            book_channel(name)
            for name in sorted(needed)
            if self.channel_state(book_channel(name))
            in {ChannelState.UNSUBSCRIBED, ChannelState.RETIRED}
        )
        if missing_combo_channels:
            self._plan_channel_change(
                missing_combo_channels,
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=FailureScope.COMBO_LAYER,
            )

    def _update_coverage(self, monotonic_ms: int) -> None:
        self._update_band_suspension(monotonic_ms)
        if self.clock is None:
            self.aggregate_results.clear()
            positive = any(
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                for tracker in self.trackers.values()
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                monotonic_ms,
            )
            return
        try:
            trusted = self.clock.interval_at(monotonic_ms)
        except ContinuityGap:
            self.aggregate_results.clear()
            self._transition_coverage(CoverageState.UNKNOWN, monotonic_ms)
            return
        self._refresh_current_aggregates(trusted)
        if not self.platform.usable or not self.option_catalog.complete:
            positive = any(
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                for tracker in self.trackers.values()
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                monotonic_ms,
            )
            return
        scoped: list[OptionInstrument] = []
        unresolved = False
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
                unresolved = True
        if not scoped:
            self._transition_coverage(
                CoverageState.UNKNOWN if unresolved else CoverageState.NO_APPLICABLE_SCOPE,
                monotonic_ms,
            )
            return
        states = [self.trackers[item.instrument_name].detector_state for item in scoped]
        if unresolved:
            states.append(DetectorState.UNKNOWN)
        if all(state is not DetectorState.UNKNOWN for state in states):
            state = CoverageState.KNOWN_COMPLETE
        elif DetectorState.ANOMALY_ACTIVE in states:
            state = CoverageState.KNOWN_DEGRADED
        else:
            state = CoverageState.UNKNOWN
        self._transition_coverage(state, monotonic_ms)

    def _refresh_current_aggregates(self, trusted: TimeInterval) -> None:
        grouped: dict[
            tuple[int, OptionType, str],
            list[DetectorState],
        ] = {}
        for instrument in self.options.values():
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            if applicability.band is None:
                continue
            key = (
                instrument.expiration_timestamp_ms,
                instrument.option_type,
                applicability.band.band_id,
            )
            grouped.setdefault(key, []).append(
                self.trackers[instrument.instrument_name].detector_state
            )
        self.aggregate_results = {
            key: aggregate_detector(
                tuple(states),
                catalog_complete=self.option_catalog.complete,
                has_applicable_scope=True,
            )
            for key, states in grouped.items()
        }

    def _update_band_suspension(self, monotonic_ms: int) -> None:
        suspended = any(
            tracker.state is TrackerState.BAND_SUSPENDED for tracker in self.trackers.values()
        )
        if suspended and self._band_suspended_started_ms is None:
            self._band_suspended_started_ms = monotonic_ms
        elif not suspended and self._band_suspended_started_ms is not None:
            self._band_suspended_duration_ms += max(
                0,
                monotonic_ms - self._band_suspended_started_ms,
            )
            self._band_suspended_started_ms = None

    def _retire_current_epoch(self) -> None:
        if self._session_epoch is None or self._session_epoch in self._retired_epochs:
            return
        self.diagnostics.session_gap_count += 1
        self._first_joint_witness_ms = None
        self.aggregate_results.clear()
        self._causal_seq += 1
        boundary = self._current_fact_boundary()
        for name in self.trackers:
            self._commit_forced_unknown(
                name,
                reason="SESSION_GAP",
                boundary=boundary,
                continuity_gap=True,
            )
        self._retired_epochs.add(self._session_epoch)
        platform_reason = (
            self.platform.reason
            if self.platform.reason
            in {
                "PLATFORM_MAINTENANCE",
                "PUBLIC_METHODS_DENIED",
                "RELEVANT_PLATFORM_LOCK",
            }
            else "SESSION_GAP"
        )
        self.platform.invalidate_fresh_index_coverage(platform_reason)
        for slot in self._channels.values():
            slot.state = ChannelState.RETIRED
        self._drop_held_frames()
        self.pending_rpcs.clear()
        self._update_band_suspension(self._last_boundary_monotonic_ms)
        self._transition_coverage(
            CoverageState.UNKNOWN,
            self._last_boundary_monotonic_ms,
        )

    def _update_subscription_peaks(self) -> None:
        acknowledged = tuple(
            channel
            for channel, slot in self._channels.items()
            if slot.state is ChannelState.ACKNOWLEDGED
        )
        instruments = {
            instrument
            for channel in acknowledged
            if (instrument := _instrument_from_channel(channel)) is not None
        }
        self.diagnostics.peak_subscribed_channel_count = max(
            self.diagnostics.peak_subscribed_channel_count,
            len(acknowledged),
        )
        self.diagnostics.peak_subscribed_instrument_count = max(
            self.diagnostics.peak_subscribed_instrument_count,
            len(instruments),
        )

    def note_transport_metrics(
        self,
        *,
        session_epoch: int | None = None,
        queue_high_water_frames: int,
        overflow_count: int,
        enqueued_envelope_count: int | None = None,
        received_frame_count: int | None = None,
    ) -> None:
        if queue_high_water_frames < 0 or overflow_count < 0:
            raise ValueError("transport diagnostics cannot be negative")
        self.diagnostics.queue_high_water_frames = max(
            self.diagnostics.queue_high_water_frames,
            queue_high_water_frames,
        )
        if session_epoch is not None:
            if session_epoch <= 0:
                raise ValueError("transport session epoch must be positive")
            self._transport_overflow_by_epoch[session_epoch] = max(
                self._transport_overflow_by_epoch.get(session_epoch, 0),
                overflow_count,
            )
            self.diagnostics.overflow_count = sum(self._transport_overflow_by_epoch.values())
        else:
            self.diagnostics.overflow_count = max(
                self.diagnostics.overflow_count,
                overflow_count,
            )
        enqueued = (
            enqueued_envelope_count if enqueued_envelope_count is not None else received_frame_count
        )
        if enqueued is not None:
            if enqueued < 0:
                raise ValueError("transport enqueued envelope count cannot be negative")
            if session_epoch is None:
                self.diagnostics.wire_received_envelope_count = max(
                    self.diagnostics.wire_received_envelope_count,
                    enqueued,
                )
            else:
                self._transport_enqueued_by_epoch[session_epoch] = max(
                    self._transport_enqueued_by_epoch.get(session_epoch, 0),
                    enqueued,
                )
                self.diagnostics.wire_received_envelope_count = sum(
                    self._transport_enqueued_by_epoch.values()
                )

    def _note_source_shape(self, source: str, payload: object, *, valid: bool) -> None:
        if source not in CORE_SOURCE_NAMES:
            return
        self.diagnostics.source_observed_count[source] += 1
        if valid:
            self.diagnostics.source_valid_count[source] += 1
        else:
            self.diagnostics.source_invalid_count[source] += 1
        fields = self.diagnostics.source_consumed_fields.setdefault(source, set())
        consumed_keys = _CONSUMED_FIELDS_BY_SOURCE[source]
        payloads: tuple[dict[str, object], ...]
        if isinstance(payload, dict):
            payloads = (payload,)
        elif isinstance(payload, list):
            payloads = tuple(item for item in payload if isinstance(item, dict))
        else:
            payloads = ()
        for item in payloads:
            for key in consumed_keys:
                if key in item:
                    fields.add((key, _json_type_name(item[key])))

    @property
    def session_established(self) -> bool:
        return (
            self._session_epoch is not None
            and self._session_epoch not in self._retired_epochs
            and self._bootstrap_queries_issued
            and self.clock is not None
            and self.option_catalog.complete
        )

    @property
    def causal_seq(self) -> int:
        return self._causal_seq

    @property
    def clock_revision(self) -> int:
        return self._clock_revision

    @property
    def platform_reason(self) -> str:
        return self.platform.reason

    def advance_time(self, monotonic_ms: int) -> tuple[PendingRpc, ...]:
        self._commands = []
        if self._session_epoch is None:
            return ()
        if (
            monotonic_ms - self._last_inbound_received_ms
            > self.policy.runtime_limits.session_liveness_deadline_ms
        ):
            self._last_boundary_monotonic_ms = max(
                self._last_boundary_monotonic_ms,
                monotonic_ms,
            )
            self._retire_current_epoch()
            raise PublicSessionError("production-public session liveness deadline expired")
        self._last_boundary_monotonic_ms = max(
            self._last_boundary_monotonic_ms,
            monotonic_ms,
        )
        self._causal_seq += 1
        boundary = self._current_fact_boundary()
        expired = tuple(
            request
            for request in self.pending_rpcs.values()
            if monotonic_ms > request.deadline_monotonic_ms
        )
        for request in expired:
            self.pending_rpcs.pop(request.request_id, None)
            self.diagnostics.rpc_late_count[request.method] += 1
            self._apply_request_failure(request)
        due_channel_retries = tuple(
            channel
            for channel, slot in self._channels.items()
            if slot.retry_after_ms is not None and monotonic_ms >= slot.retry_after_ms
        )
        for channel in due_channel_retries:
            self._channels[channel].retry_after_ms = None
        if due_channel_retries:
            self._reconcile_channel_intents(due_channel_retries, boundary)
        if self.clock is not None:
            try:
                trusted = self.clock.interval_at(monotonic_ms)
            except ContinuityGap:
                self._invalidate_clock_index(boundary, reason="CLOCK_GAP")
            else:
                self.index.seal_ready(trusted.lower_ms)
                self._sync_membership(boundary)
                token = self._time_currentness_token(trusted)
                self._settle_fact(
                    boundary=boundary,
                    affected_instruments=tuple(self.options),
                    countable=False,
                    observation_reason="TIME_BOUNDARY",
                    acceptance_eligible=(token != self._last_time_currentness_token),
                )
        if (
            self._next_clock_refresh_ms is not None
            and monotonic_ms >= self._next_clock_refresh_ms
            and not any(
                request.purpose in {RpcPurpose.CLOCK_BOOTSTRAP, RpcPurpose.CLOCK_REFRESH}
                for request in self.pending_rpcs.values()
            )
        ):
            purpose = RpcPurpose.CLOCK_BOOTSTRAP if self.clock is None else RpcPurpose.CLOCK_REFRESH
            self._schedule(
                purpose=purpose,
                method="public/get_time",
                params={},
                scope="CLOCK_INDEX",
                generation=None,
                origin_boundary=boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )
            if purpose is RpcPurpose.CLOCK_REFRESH:
                self.diagnostics.clock_refresh_attempt_count += 1
            self._next_clock_refresh_ms = (
                monotonic_ms + self.policy.runtime_limits.clock_refresh_interval_ms
            )
        if (
            self._next_option_catalog_recovery_ms is not None
            and monotonic_ms >= self._next_option_catalog_recovery_ms
            and not any(
                request.purpose in {RpcPurpose.OPTION_CATALOG, RpcPurpose.OPTION_METADATA}
                for request in self.pending_rpcs.values()
            )
        ):
            self._schedule_option_catalog_refresh(boundary)
            self._next_option_catalog_recovery_ms = (
                monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
        if (
            self._next_combo_catalog_recovery_ms is not None
            and monotonic_ms >= self._next_combo_catalog_recovery_ms
            and not any(
                request.purpose in {RpcPurpose.COMBO_CATALOG, RpcPurpose.COMBO_METADATA}
                for request in self.pending_rpcs.values()
            )
        ):
            self._schedule_combo_refresh(boundary, trailing=False)
            self._next_combo_catalog_recovery_ms = (
                monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
        return self._take_commands()

    def prepare_reconnect(self, reason: str) -> None:
        del reason
        self._retire_current_epoch()
        self._transition_coverage(CoverageState.UNKNOWN, _monotonic_ms())

    def clean_stop(self, monotonic_ms: int) -> Path:
        self._last_boundary_monotonic_ms = max(
            self._last_boundary_monotonic_ms,
            monotonic_ms,
        )
        self._causal_seq += 1
        witness_at_stop = self._first_joint_witness_ms
        for tracker in self.trackers.values():
            transition = tracker.stop(causal_seq=self._causal_seq)
            self._record_episode_end(transition.ended_episode, monotonic_ms)
        self._update_coverage(monotonic_ms)
        if witness_at_stop is not None:
            self._first_joint_witness_ms = witness_at_stop
        segments = self._coverage.close(monotonic_ms)
        observation_ms = segments[-1].end_monotonic_ms - segments[0].start_monotonic_ms
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
                    key=lambda item: (item[0][1].value, item[0][2]),
                )
            ],
            detector_unknown_transition_count_by_reason=self._unknown_counts,
            anomaly_end_count_by_reason=self._episode_end_counts,
            known_active_duration_ms_sum_by_end_reason=self._known_active_duration_ms,
            public_atomic_quote_state_transition_count=self._atomic_transition_counts,
            operational_diagnostics=self._operational_diagnostics(observation_ms),
        )
        return self.writer.write_summary(summary)

    def _operational_diagnostics(self, observation_ms: int) -> dict[str, object]:
        methods = sorted(self.diagnostics.rpc_request_count)
        channel_rows: list[dict[str, object]] = []
        for channel_class in CHANNEL_CLASSES:
            received = self.diagnostics.channel_received_count[channel_class]
            processed = self.diagnostics.channel_processed_count[channel_class]
            channel_rows.append(
                {
                    "channel_class": channel_class,
                    "received_count": received,
                    "processed_count": processed,
                    "received_rate_per_second": _rate(received, observation_ms),
                    "processed_rate_per_second": _rate(processed, observation_ms),
                }
            )
        acknowledged_channels = tuple(
            channel
            for channel, slot in self._channels.items()
            if slot.state is ChannelState.ACKNOWLEDGED
        )
        subscribed_instruments = {
            _instrument_from_channel(channel)
            for channel in acknowledged_channels
            if _instrument_from_channel(channel) is not None
        }
        source_rows = []
        for source in CORE_SOURCE_NAMES:
            observed = self.diagnostics.source_observed_count[source]
            valid = self.diagnostics.source_valid_count[source]
            invalid = self.diagnostics.source_invalid_count[source]
            source_rows.append(
                {
                    "source": source,
                    "observed_count": observed,
                    "valid_count": valid,
                    "invalid_count": invalid,
                    "validation": (
                        "NOT_OBSERVED" if observed == 0 else "INVALID" if invalid else "VALID"
                    ),
                    "consumed_fields": [
                        {"key": key, "type": field_type}
                        for key, field_type in sorted(
                            self.diagnostics.source_consumed_fields.get(source, set())
                        )
                    ],
                }
            )
        post_witness = (
            None
            if self._first_joint_witness_ms is None
            else max(0, self._last_boundary_monotonic_ms - self._first_joint_witness_ms)
        )
        return {
            "operational_diagnostics_schema_version": 2,
            "runtime_limits": self.policy.runtime_limits.as_object(),
            "ingress": {
                "received_envelope_count": max(
                    self.diagnostics.received_envelope_count,
                    self.diagnostics.wire_received_envelope_count,
                ),
                "reduced_envelope_count": self.diagnostics.reduced_envelope_count,
                "ingress_gap_or_duplicate_count": (self.diagnostics.ingress_gap_or_duplicate_count),
                "queue_high_water_frames": self.diagnostics.queue_high_water_frames,
                "max_receive_to_reduce_lag_ms": (self.diagnostics.max_receive_to_reduce_lag_ms),
                "overflow_count": self.diagnostics.overflow_count,
            },
            "rpc_by_method": [
                {
                    "method": method,
                    "request_count": self.diagnostics.rpc_request_count[method],
                    "success_count": self.diagnostics.rpc_success_count[method],
                    "error_count": self.diagnostics.rpc_error_count[method],
                    "late_response_count": self.diagnostics.rpc_late_count[method],
                    "rate_limit_count": self.diagnostics.rpc_rate_limit_count[method],
                    "latency_observation_count": self.diagnostics.rpc_latency_count[method],
                    "latency_ms_sum": self.diagnostics.rpc_latency_sum[method],
                    "latency_ms_max": self.diagnostics.rpc_latency_max[method],
                }
                for method in methods
            ],
            "channel_by_class": channel_rows,
            "subscriptions": {
                "current_subscribed_instrument_count": len(subscribed_instruments),
                "peak_subscribed_instrument_count": (
                    self.diagnostics.peak_subscribed_instrument_count
                ),
                "current_subscribed_channel_count": len(acknowledged_channels),
                "peak_subscribed_channel_count": (self.diagnostics.peak_subscribed_channel_count),
            },
            "heartbeat": {
                "test_request_count": self.diagnostics.heartbeat_test_request_count,
                "public_test_success_count": (self.diagnostics.heartbeat_public_test_success_count),
                "public_test_error_count": self.diagnostics.heartbeat_public_test_error_count,
                "latency_observation_count": self.diagnostics.heartbeat_latency_count,
                "latency_ms_sum": self.diagnostics.heartbeat_latency_sum,
                "latency_ms_max": self.diagnostics.heartbeat_latency_max,
            },
            "recovery": {
                "reconnect_count": self.diagnostics.reconnect_count,
                "session_gap_count": self.diagnostics.session_gap_count,
                "index_gap_count": self.diagnostics.index_gap_count,
                "index_resubscribe_count": self.diagnostics.index_resubscribe_count,
                "option_channel_resync_count": (self.diagnostics.option_channel_resync_count),
                "clock_refresh_attempt_count": (self.diagnostics.clock_refresh_attempt_count),
                "clock_refresh_success_count": (self.diagnostics.clock_refresh_success_count),
                "clock_refresh_failure_count": (self.diagnostics.clock_refresh_failure_count),
                "option_catalog_refresh_attempt_count": (
                    self.diagnostics.rpc_request_count["public/get_instruments"]
                ),
                "option_catalog_refresh_success_count": (
                    self.diagnostics.option_catalog_refresh_success_count
                ),
                "option_catalog_refresh_failure_count": (
                    self.diagnostics.option_catalog_refresh_failure_count
                ),
                "combo_authoritative_refresh_attempt_count": (
                    self.diagnostics.combo_authoritative_refresh_attempt_count
                ),
                "combo_authoritative_refresh_success_count": (
                    self.diagnostics.combo_authoritative_refresh_success_count
                ),
                "combo_authoritative_refresh_failure_count": (
                    self.diagnostics.combo_authoritative_refresh_failure_count
                ),
            },
            "source_shapes": source_rows,
            "witness": {
                "first_joint_witness_monotonic_ms": self._first_joint_witness_ms,
                "continuous_covered_after_witness_ms": post_witness,
            },
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
        if stop_monotonic_ms < self._current_start_ms:
            raise RuntimeError("coverage stop precedes the current segment")
        if stop_monotonic_ms > self._current_start_ms or not self._segments:
            self._segments.append(
                CoverageSegment(self._current_start_ms, stop_monotonic_ms, self._current_state)
            )
        return tuple(self._segments)


class LiveRadarRuntime:
    """Async transport driver; all mutable business state lives in `RadarReducer`."""

    def __init__(
        self,
        *,
        policy: RadarPolicy,
        code_identity: str,
        evidence_writer: EvidenceWriter,
        runtime_identity: str | None = None,
    ) -> None:
        identity = runtime_identity or str(uuid.uuid4())
        self.reducer = RadarReducer(
            policy=policy,
            code_identity=code_identity,
            evidence_writer=evidence_writer,
            runtime_identity=identity,
        )

    @property
    def policy(self) -> RadarPolicy:
        return self.reducer.policy

    @property
    def code_identity(self) -> str:
        return self.reducer.code_identity

    @property
    def runtime_identity(self) -> str:
        return self.reducer.runtime_identity

    @property
    def writer(self) -> EvidenceWriter:
        return self.reducer.writer

    @property
    def platform(self) -> PlatformReadiness:
        return self.reducer.platform

    @property
    def session_established(self) -> bool:
        return self.reducer.session_established

    async def run(self, client: PublicClient, stop_event: asyncio.Event) -> Path:
        if stop_event.is_set():
            return self.reducer.clean_stop(_monotonic_ms())
        self._capture_transport_metrics(client)
        started_monotonic_ms = _monotonic_ms()
        outbound: asyncio.Queue[PendingRpc] = asyncio.Queue(maxsize=MAX_PENDING_INBOUND_FRAMES)
        sender_task = asyncio.create_task(
            self._sender_loop(client, outbound),
            name="radar-public-sender",
        )
        buffered: deque[InboundEnvelope] = deque()
        commands = self.reducer.begin_session(
            session_epoch=client.session_epoch,
            monotonic_ms=started_monotonic_ms,
        )
        self._enqueue_commands(outbound, commands)
        poll_ms = self.policy.runtime_limits.time_boundary_poll_interval_ms
        next_poll_ms = started_monotonic_ms + poll_ms
        try:
            while True:
                self._raise_sender_failure(sender_task)
                buffered.extend(self._drain_client_envelopes(client))
                if stop_event.is_set():
                    await self._stop_client_intake(client)
                    buffered.extend(self._drain_client_envelopes(client))
                    while buffered:
                        envelope = buffered.popleft()
                        while next_poll_ms < envelope.received_monotonic_ms:
                            self._enqueue_commands(
                                outbound,
                                self.reducer.advance_time(next_poll_ms),
                            )
                            next_poll_ms += poll_ms
                        self._enqueue_commands(
                            outbound,
                            self.reducer.reduce(
                                envelope,
                                processed_monotonic_ms=_monotonic_ms(),
                            ),
                        )
                    break
                if buffered:
                    envelope = buffered.popleft()
                    while next_poll_ms < envelope.received_monotonic_ms:
                        self._enqueue_commands(
                            outbound,
                            self.reducer.advance_time(next_poll_ms),
                        )
                        next_poll_ms += poll_ms
                    self._enqueue_commands(
                        outbound,
                        self.reducer.reduce(
                            envelope,
                            processed_monotonic_ms=_monotonic_ms(),
                        ),
                    )
                    continue
                now_ms = _monotonic_ms()
                if now_ms >= next_poll_ms:
                    self._enqueue_commands(
                        outbound,
                        self.reducer.advance_time(next_poll_ms),
                    )
                    next_poll_ms += poll_ms
                    continue
                timeout_seconds = (next_poll_ms - now_ms) / 1_000
                try:
                    envelope = await client.next_envelope(timeout_seconds=timeout_seconds)
                except TimeoutError:
                    continue
                buffered.append(envelope)
        finally:
            if stop_event.is_set() and not sender_task.done():
                try:
                    await asyncio.wait_for(
                        outbound.join(),
                        timeout=(
                            min(
                                self.policy.runtime_limits.rpc_deadline_ms,
                                self.policy.runtime_limits.notification_queue_lag_deadline_ms,
                            )
                            / 1_000
                        ),
                    )
                except TimeoutError:
                    self.reducer._retire_current_epoch()
            self._raise_sender_failure(sender_task)
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
        self._capture_transport_metrics(client)
        return self.reducer.clean_stop(_monotonic_ms())

    async def _sender_loop(
        self,
        client: PublicClient,
        outbound: asyncio.Queue[PendingRpc],
    ) -> None:
        while True:
            command = await outbound.get()
            try:
                await client.send_request(
                    request_id=command.request_id,
                    method=command.method,
                    params=command.params,
                    responding_to_test_request=(command.purpose is RpcPurpose.HEARTBEAT_TEST),
                )
            finally:
                outbound.task_done()

    def _enqueue_commands(
        self,
        outbound: asyncio.Queue[PendingRpc],
        commands: tuple[PendingRpc, ...],
    ) -> None:
        try:
            for command in commands:
                outbound.put_nowait(command)
        except asyncio.QueueFull as exc:
            self.reducer._retire_current_epoch()
            raise PublicSessionError("outbound command queue overflow") from exc

    @staticmethod
    def _raise_sender_failure(sender_task: asyncio.Task[None]) -> None:
        if not sender_task.done() or sender_task.cancelled():
            return
        exception = sender_task.exception()
        if exception is not None:
            raise exception
        raise PublicSessionError("outbound sender stopped unexpectedly")

    @staticmethod
    def _drain_client_envelopes(
        client: PublicClient,
    ) -> tuple[InboundEnvelope, ...]:
        drain = getattr(client, "drain_envelopes", None)
        if not callable(drain):
            return ()
        values = drain()
        if not isinstance(values, tuple) or not all(
            isinstance(value, InboundEnvelope) for value in values
        ):
            raise PublicProtocolIncompatibility("transport drain returned incompatible envelopes")
        return values

    @staticmethod
    async def _stop_client_intake(client: PublicClient) -> None:
        stop_intake = getattr(client, "stop_intake", None)
        if callable(stop_intake):
            await stop_intake()

    def _capture_transport_metrics(self, client: PublicClient) -> None:
        self.reducer.note_transport_metrics(
            session_epoch=client.session_epoch,
            queue_high_water_frames=getattr(client, "queue_high_water_frames", 0),
            overflow_count=getattr(client, "overflow_count", 0),
            enqueued_envelope_count=getattr(
                client,
                "enqueued_envelope_count",
                None,
            ),
            received_frame_count=getattr(client, "received_frame_count", None),
        )

    async def _send_commands(
        self,
        client: PublicClient,
        commands: tuple[PendingRpc, ...],
    ) -> None:
        """Compatibility helper for focused transport tests; `run` uses the sender queue."""
        for command in commands:
            await client.send_request(
                request_id=command.request_id,
                method=command.method,
                params=command.params,
                responding_to_test_request=command.purpose is RpcPurpose.HEARTBEAT_TEST,
            )

    def prepare_reconnect(self, reason: str) -> None:
        self.reducer.prepare_reconnect(reason)

    async def _clean_stop(self, _client: PublicClient | None = None) -> Path:
        return self.reducer.clean_stop(_monotonic_ms())


_OPTION_INSTRUMENT_FIELDS = frozenset(
    {
        "instrument_name",
        "kind",
        "base_currency",
        "quote_currency",
        "settlement_currency",
        "counter_currency",
        "price_index",
        "instrument_type",
        "is_active",
        "state",
        "option_type",
        "expiration_timestamp",
        "strike",
        "contract_size",
        "min_trade_amount",
        "qty_tick_size",
    }
)
_COMBO_METADATA_FIELDS = frozenset(
    {
        "instrument_name",
        "kind",
        "base_currency",
        "quote_currency",
        "settlement_currency",
        "counter_currency",
        "instrument_type",
        "is_active",
        "state",
        "contract_size",
        "min_trade_amount",
        "qty_tick_size",
    }
)
_CONSUMED_FIELDS_BY_SOURCE: dict[str, frozenset[str]] = {
    "combo_book": frozenset(
        {"type", "timestamp", "instrument_name", "change_id", "prev_change_id", "bids", "asks"}
    ),
    "combo_lifecycle": frozenset({"instrument_name", "state"}),
    "heartbeat": frozenset({"type"}),
    "index": frozenset({"timestamp", "index_name", "price"}),
    "option_book": frozenset(
        {"type", "timestamp", "instrument_name", "change_id", "prev_change_id", "bids", "asks"}
    ),
    "option_lifecycle": frozenset({"instrument_name", "state"}),
    "option_ticker": frozenset(
        {"instrument_name", "timestamp", "underlying_price", "underlying_index"}
    ),
    "platform_state": frozenset({"maintenance", "price_index", "locked"}),
    "platform_state.public_methods_state": frozenset({"allow_unauthenticated_public_requests"}),
    "public/get_combos": frozenset({"id", "state", "legs"}),
    "public/get_instrument": _OPTION_INSTRUMENT_FIELDS | _COMBO_METADATA_FIELDS,
    "public/get_instruments": _OPTION_INSTRUMENT_FIELDS,
    "public/get_time": frozenset(),
    "public/set_heartbeat": frozenset(),
    "public/status": frozenset({"locked", "locked_indices"}),
    "public/subscribe": frozenset(),
    "public/test": frozenset({"version"}),
    "public/unsubscribe": frozenset(),
}


def _channel_class(
    envelope: InboundEnvelope,
    *,
    combo_names: set[str],
) -> str:
    if isinstance(envelope.get("id"), int):
        return "CONNECTION_CONTROL"
    method = envelope.get("method")
    if method == "heartbeat":
        return "HEARTBEAT"
    if method == "connection_error":
        return "CONNECTION_CONTROL"
    if method != "subscription":
        return "INVALID"
    params = envelope.get("params")
    channel = params.get("channel") if isinstance(params, dict) else None
    if channel in PLATFORM_CHANNELS:
        return "PLATFORM"
    if channel == OPTION_LIFECYCLE_CHANNEL:
        return "OPTION_LIFECYCLE"
    if channel == COMBO_LIFECYCLE_CHANNEL:
        return "COMBO_LIFECYCLE"
    if channel == INDEX_CHANNEL:
        return "INDEX"
    if isinstance(channel, str) and channel.startswith("ticker."):
        return "OPTION_TICKER"
    if isinstance(channel, str) and channel.startswith("book."):
        instrument_name = _instrument_from_channel(channel)
        if instrument_name in combo_names:
            return "COMBO_BOOK"
        return "OPTION_BOOK"
    return "INVALID"


def _source_name_for_channel(channel: str, *, combo_names: set[str]) -> str:
    if channel in PLATFORM_CHANNELS:
        return channel
    if channel == OPTION_LIFECYCLE_CHANNEL:
        return "option_lifecycle"
    if channel == COMBO_LIFECYCLE_CHANNEL:
        return "combo_lifecycle"
    if channel == INDEX_CHANNEL:
        return "index"
    if channel.startswith("ticker."):
        return "option_ticker"
    if channel.startswith("book."):
        instrument_name = _instrument_from_channel(channel)
        if instrument_name in combo_names:
            return "combo_book"
        return "option_book"
    return ""


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "object"


def _rate(count: int, observation_ms: int) -> str | None:
    if observation_ms == 0:
        return None
    return decimal_text(Decimal(count) / (Decimal(observation_ms) / Decimal(1_000)))


def _instrument_from_channel(channel: str) -> str | None:
    if channel.startswith("ticker.") and channel.endswith(".100ms"):
        return channel[len("ticker.") : -len(".100ms")]
    if channel.startswith("book.") and channel.endswith(".100ms"):
        return channel[len("book.") : -len(".100ms")]
    return None


def _is_rate_limit_error(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    code = value.get("code")
    message = value.get("message")
    return code == 10_028 or (isinstance(message, str) and "too_many_requests" in message.lower())


def _is_target_option_product(payload: object) -> bool:
    data = require_mapping(payload, "instrument")
    return {
        "kind": require_str(data.get("kind"), "instrument.kind"),
        "base_currency": require_str(data.get("base_currency"), "instrument.base_currency"),
        "quote_currency": require_str(data.get("quote_currency"), "instrument.quote_currency"),
        "settlement_currency": require_str(
            data.get("settlement_currency"),
            "instrument.settlement_currency",
        ),
        "counter_currency": require_str(
            data.get("counter_currency"),
            "instrument.counter_currency",
        ),
        "price_index": require_str(data.get("price_index"), "instrument.price_index"),
        "instrument_type": require_str(
            data.get("instrument_type"),
            "instrument.instrument_type",
        ),
    } == {
        "kind": "option",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "counter_currency": "USDC",
        "price_index": "btc_usdc",
        "instrument_type": "linear",
    }


def _is_valid_irrelevant_option_metadata(
    payload: object,
    expected_name: str,
) -> bool:
    try:
        data = require_mapping(payload, "instrument")
        if require_str(data.get("instrument_name"), "instrument.instrument_name") != expected_name:
            return False
        product = {
            "kind": require_str(data.get("kind"), "instrument.kind"),
            "base_currency": require_str(
                data.get("base_currency"),
                "instrument.base_currency",
            ),
            "quote_currency": require_str(
                data.get("quote_currency"),
                "instrument.quote_currency",
            ),
            "settlement_currency": require_str(
                data.get("settlement_currency"),
                "instrument.settlement_currency",
            ),
            "counter_currency": require_str(
                data.get("counter_currency"),
                "instrument.counter_currency",
            ),
            "price_index": require_str(data.get("price_index"), "instrument.price_index"),
            "instrument_type": require_str(
                data.get("instrument_type"),
                "instrument.instrument_type",
            ),
        }
        require_bool(data.get("is_active"), "instrument.is_active")
        require_str(data.get("state"), "instrument.state")
    except SourceDataError:
        return False
    return (
        product["kind"] == "option"
        and product["base_currency"] != "BTC"
        and product["quote_currency"] == "USDC"
        and product["settlement_currency"] == "USDC"
        and product["counter_currency"] == "USDC"
        and product["instrument_type"] == "linear"
    )


def _is_explicit_final_target_option_metadata(
    payload: object,
    expected_name: str,
) -> bool:
    try:
        data = require_mapping(payload, "instrument")
        if require_str(data.get("instrument_name"), "instrument.instrument_name") != expected_name:
            return False
        if not _is_target_option_product(data):
            return False
        require_bool(data.get("is_active"), "instrument.is_active")
        state = require_str(data.get("state"), "instrument.state")
    except SourceDataError:
        return False
    return state in FINAL_INSTRUMENT_LIFECYCLE_STATES


def _is_valid_irrelevant_combo_metadata(
    payload: object,
    expected_name: str,
) -> bool:
    try:
        data = require_mapping(payload, "combo metadata")
        if (
            require_str(
                data.get("instrument_name"),
                "combo metadata.instrument_name",
            )
            != expected_name
        ):
            return False
        product = {
            "kind": require_str(data.get("kind"), "combo metadata.kind"),
            "base_currency": require_str(
                data.get("base_currency"),
                "combo metadata.base_currency",
            ),
            "quote_currency": require_str(
                data.get("quote_currency"),
                "combo metadata.quote_currency",
            ),
            "settlement_currency": require_str(
                data.get("settlement_currency"),
                "combo metadata.settlement_currency",
            ),
            "counter_currency": require_str(
                data.get("counter_currency"),
                "combo metadata.counter_currency",
            ),
            "instrument_type": require_str(
                data.get("instrument_type"),
                "combo metadata.instrument_type",
            ),
        }
    except SourceDataError:
        return False
    return (
        product["kind"] == "option_combo"
        and product["base_currency"] != "BTC"
        and product["quote_currency"] == "USDC"
        and product["settlement_currency"] == "USDC"
        and product["counter_currency"] == "USDC"
        and product["instrument_type"] == "linear"
    )


def _current_for_index_tail(
    status: IndexTailStatus,
    band_id: str | None,
) -> CurrentEvaluation:
    reason = _index_tail_reason(status)
    if status is IndexTailStatus.AVAILABLE:
        raise ValueError("available index tail requires detector calculation")
    if status in {
        IndexTailStatus.TIME_BOUNDARY_PENDING,
        IndexTailStatus.WATERMARK_PENDING,
    }:
        disposition = CurrentDisposition.INDEX_TAIL_PENDING
        continuity_gap = False
    else:
        disposition = CurrentDisposition.UNKNOWN
        continuity_gap = status in {
            IndexTailStatus.WINDOW_GAP,
            IndexTailStatus.SOURCE_STALE,
            IndexTailStatus.CONTINUITY_GAP,
        }
    return CurrentEvaluation(
        disposition=disposition,
        reason=reason,
        known_evaluation=False,
        full_formula_evaluation=False,
        band_id=band_id,
        continuity_gap=continuity_gap,
    )


def _index_tail_reason(status: IndexTailStatus) -> str:
    reasons = {
        IndexTailStatus.WARMUP: "INDEX_WARMUP",
        IndexTailStatus.TIME_BOUNDARY_PENDING: "INDEX_TIME_BOUNDARY_PENDING",
        IndexTailStatus.WATERMARK_PENDING: "INDEX_WATERMARK_PENDING",
        IndexTailStatus.WINDOW_GAP: "INDEX_WINDOW_GAP",
        IndexTailStatus.SOURCE_STALE: "INDEX_SOURCE_STALE",
        IndexTailStatus.CONTINUITY_GAP: "INDEX_CONTINUITY_GAP",
    }
    if status is IndexTailStatus.AVAILABLE:
        raise ValueError("available index tail requires detector calculation")
    return reasons[status]


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
    session_epoch = 0
    while not event.is_set():
        try:
            session_epoch += 1
            async with DeribitPublicClient(
                session_epoch=session_epoch,
                rpc_deadline_ms=policy.runtime_limits.rpc_deadline_ms,
            ) as client:
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
        except (SourceDataError, TimeoutError):
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
            if runtime.session_established:
                reconnect_attempt = 0
            await asyncio.sleep(
                reconnect_delay_seconds(
                    reconnect_attempt,
                    base_delay_ms=policy.runtime_limits.time_boundary_poll_interval_ms,
                    maximum_delay_ms=policy.runtime_limits.rpc_deadline_ms,
                )
            )
            reconnect_attempt += 1
    return await runtime._clean_stop(None)


def reconnect_delay_seconds(
    attempt: int,
    *,
    base_delay_ms: int,
    maximum_delay_ms: int,
    jitter_fraction: float | None = None,
) -> float:
    if attempt < 0:
        raise ValueError("reconnect attempt must be non-negative")
    if base_delay_ms <= 0 or maximum_delay_ms < base_delay_ms:
        raise ValueError("reconnect delay bounds are invalid")
    jitter = random.random() if jitter_fraction is None else jitter_fraction
    if not 0 <= jitter <= 1:
        raise ValueError("jitter_fraction must be within [0, 1]")
    base_seconds = min(
        maximum_delay_ms / 1_000,
        (base_delay_ms / 1_000) * float(2 ** min(attempt, 30)),
    )
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

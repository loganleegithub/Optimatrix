from __future__ import annotations

import asyncio
import random
import re
import signal
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from market_monitor import (
    BookState,
    ContinuityGap,
    ContinuousOrderBook,
    IndexMinuteReducer,
    IndexTailStatus,
    PriceLevel,
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
    AtomicResult,
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
    OPTION_LOCAL_ACCEPTANCE_WINDOW_MS,
    OPTION_LOCAL_RETAINED_INTERVAL_LIMIT,
    RPC_METHOD_ALLOWLIST,
    SOURCE_CONSUMED_FIELD_TYPES,
    TRANSPORT_CLOSE_CODE_ALLOWLIST,
    TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST,
    TRANSPORT_EXCEPTION_CLASS_ALLOWLIST,
    AnomalyEvidence,
    AtomicEvidence,
    CoverageBlockingReason,
    CoverageSegment,
    CoverageState,
    EvidenceWriter,
    decimal_text,
    project_anomaly_event,
    project_atomic_event,
    project_run_summary,
    ratio_or_none,
    validate_atomic_causal_invariant,
)
from short_vol_radar.evidence import (
    CausalCause as CausalCause,
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
    detector_observation_identity,
    parse_ticker,
)
from short_vol_radar.radar import (
    calculate_current_evaluation as calculate_current_evaluation,
)
from websockets.exceptions import WebSocketException

from radar_runtime.deribit_public import (
    MAX_PENDING_INBOUND_FRAMES,
    DeribitPublicClient,
    InboundEnvelope,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicSessionError,
    SendControlEvent,
    SendControlKind,
    SendFailureKind,
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

    def enqueue_send_control(self, event: SendControlEvent) -> None: ...


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
    result: EvaluationResult | None = None


@dataclass(frozen=True)
class ScopeSnapshot:
    commit: CausalCommit
    trusted_time: TimeInterval
    clock_revision: int
    current: tuple[ScopeCurrent, ...]
    boundary_countable: bool
    acceptance_eligible: bool
    catalog_complete: bool


@dataclass(frozen=True)
class AtomicBookSnapshot:
    instrument_name: str
    state: BookState
    reason: str | None
    change_id: int | None
    economic_revision: int
    source_timestamp_ms: int | None
    last_mutation_monotonic_ms: int | None
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]


@dataclass(frozen=True)
class AtomicScopeSnapshot:
    commit: CausalCommit
    episode_identity: str
    anomaly_activation_seq: int
    activation_band_id: str
    detector_state: DetectorState
    detector_causal_seq: int
    short_leg: OptionInstrument
    short_current: CurrentEvaluation | None
    option_catalog_complete: bool
    combo_catalog_complete: bool
    current_options: tuple[OptionInstrument, ...]
    combos: tuple[ComboInstrument, ...]
    combo_books: tuple[AtomicBookSnapshot, ...]
    result: AtomicResult


@dataclass(frozen=True)
class _CurrentScopeTruth:
    aggregate: AggregateDetectorResult
    has_current_full_formula: bool
    formula_instrument: OptionInstrument | None


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


class RpcState(StrEnum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEADLINE_LATE = "DEADLINE_LATE"
    RETIRED = "RETIRED"
    CENSORED = "CENSORED"
    ORPHAN_LATE_WIRE = "ORPHAN_LATE_WIRE"


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
class CausalEffect:
    cause: CausalCause
    failure_domain: FailureScope
    affected_scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cause, CausalCause):
            raise TypeError("causal effect cause must be a CausalCause")
        if not isinstance(self.failure_domain, FailureScope):
            raise TypeError("causal effect failure domain must be a FailureScope")
        if not isinstance(self.affected_scopes, tuple):
            raise TypeError("causal effect affected scopes must be an immutable tuple")
        _validate_causal_scopes(self.affected_scopes)


@dataclass(frozen=True)
class CausalCommit:
    boundary: FactBoundary
    cause: CausalCause
    failure_domain: FailureScope
    affected_scopes: tuple[str, ...]
    concurrent_effects: tuple[CausalEffect, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.boundary, FactBoundary):
            raise TypeError("causal commit boundary must be a FactBoundary")
        if not isinstance(self.cause, CausalCause):
            raise TypeError("causal commit cause must be a CausalCause")
        if not isinstance(self.failure_domain, FailureScope):
            raise TypeError("causal commit failure domain must be a FailureScope")
        if not isinstance(self.affected_scopes, tuple):
            raise TypeError("causal commit affected scopes must be an immutable tuple")
        _validate_causal_scopes(self.affected_scopes)
        if not isinstance(self.concurrent_effects, tuple):
            raise TypeError("causal commit concurrent effects must be an immutable tuple")
        if not all(isinstance(effect, CausalEffect) for effect in self.concurrent_effects):
            raise TypeError("causal commit effects must be CausalEffect values")

    @property
    def transaction_affected_scopes(self) -> tuple[str, ...]:
        return _merge_causal_scopes(
            self.affected_scopes,
            *(effect.affected_scopes for effect in self.concurrent_effects),
        )

    @property
    def source_currentness_causes(self) -> tuple[CausalCause, ...]:
        return tuple(
            effect.cause
            for effect in self.concurrent_effects
            if effect.cause is CausalCause.TICKER_SOURCE_STALE
        )


@dataclass(frozen=True)
class ContinuityIncident:
    incident_id: int
    root_commit: CausalCommit
    restart_effect: CausalEffect
    from_epoch: int
    to_epoch: int


class TickerAcceptedCurrentness(StrEnum):
    MISSING = "MISSING"
    CURRENT = "CURRENT"
    SOURCE_STALE = "SOURCE_STALE"


@dataclass(frozen=True)
class _SettledTickerCurrentness:
    ticker: TickerState | None
    state: TickerAcceptedCurrentness
    reason: str
    continuity_gap: bool


@dataclass(frozen=True)
class _JointWitnessIdentity:
    boundary: FactBoundary
    expiration_timestamp_ms: int
    option_type: OptionType
    tte_band_id: str
    instrument_name: str


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
    send_deadline_monotonic_ms: int
    failure_scope: FailureScope


@dataclass
class _RpcLifecycle:
    request: PendingRpc
    state: RpcState = RpcState.SCHEDULED
    sent_monotonic_ms: int | None = None
    response_deadline_monotonic_ms: int | None = None
    terminal_monotonic_ms: int | None = None
    terminal_from_state: RpcState | None = None


@dataclass
class RuntimeDiagnostics:
    transport_enqueued_envelope_count: int = 0
    received_envelope_count: int = 0
    reduced_envelope_count: int = 0
    ingress_gap_or_duplicate_count: int = 0
    retired_epoch_frame_count: int = 0
    queue_high_water_frames: int = 0
    max_receive_to_reduce_lag_ms: int = 0
    overflow_count: int = 0
    late_response_count: int = 0
    rpc_orphan_late_wire_count: int = 0
    send_control_event_count: int = 0
    connection_error_event_count: int = 0
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
    rpc_sent_count: Counter[str] = field(default_factory=Counter)
    rpc_success_count: Counter[str] = field(default_factory=Counter)
    rpc_error_count: Counter[str] = field(default_factory=Counter)
    rpc_deadline_late_count: Counter[str] = field(default_factory=Counter)
    rpc_retired_count: Counter[str] = field(default_factory=Counter)
    rpc_censored_count: Counter[str] = field(default_factory=Counter)
    rpc_pre_send_terminal_count: Counter[tuple[str, str]] = field(default_factory=Counter)
    rpc_post_send_terminal_count: Counter[tuple[str, str]] = field(default_factory=Counter)
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
    global_continuity_restart_count: Counter[str] = field(default_factory=Counter)
    global_continuity_restart_edges: list[dict[str, object]] = field(default_factory=list)
    global_continuity_recovery_edges: list[dict[str, object]] = field(default_factory=list)
    ticker_application_count: Counter[str] = field(default_factory=Counter)
    ticker_candidate_currentness_count: Counter[str] = field(default_factory=Counter)
    ticker_accepted_currentness_transition_count: Counter[str] = field(default_factory=Counter)
    late_ticker_diagnostics: list[dict[str, object]] = field(default_factory=list)
    omitted_late_ticker_diagnostic_count: int = 0
    option_local_unavailable_count: Counter[str] = field(default_factory=Counter)
    option_local_recovery_count: Counter[str] = field(default_factory=Counter)
    option_local_end_count: Counter[str] = field(default_factory=Counter)
    option_local_intervals: deque[dict[str, object]] = field(default_factory=deque)
    option_local_outside_window_interval_count: int = 0
    option_local_outside_window_latest_end_monotonic_ms: int | None = None
    option_local_outside_window_interval_count_by_reason: Counter[tuple[str, str]] = field(
        default_factory=Counter
    )
    omitted_option_local_interval_count: int = 0
    omitted_option_local_interval_count_by_reason: Counter[tuple[str, str]] = field(
        default_factory=Counter
    )
    transport_terminal_attribution_count: Counter[tuple[str, str, str]] = field(
        default_factory=Counter
    )


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


@dataclass(frozen=True)
class _OptionLocalUnavailable:
    instrument_name: str
    generation: int
    reason: str
    start_monotonic_ms: int
    global_continuity_epoch: int


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
        self._ticker_accepted_currentness: dict[str, str] = {}
        self._settled_ticker_currentness: dict[str, _SettledTickerCurrentness] = {}
        self._option_local_unavailable: dict[str, _OptionLocalUnavailable] = {}
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
        self._rpc_lifecycles: dict[int, _RpcLifecycle] = {}
        self._early_rpc_responses: dict[int, InboundEnvelope] = {}
        self._channels: dict[str, _ChannelSlot] = {}
        self._held_subscription_frames: list[_HeldSubscriptionFrame] = []
        self._held_subscription_frame_count = 0
        self._session_epoch: int | None = None
        self._retired_epochs: set[int] = set()
        self._application_frontier_by_epoch: dict[int, int] = {}
        self._last_ingress_seq = 0
        self._last_boundary_monotonic_ms = 0
        self._last_wire_received_ms = 0
        self._causal_seq = 0
        self._clock_revision = 0
        self._last_time_currentness_token: tuple[object, ...] | None = None
        self._last_time_currentness_by_instrument: dict[str, tuple[object, ...]] = {}
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
        initialized_ms = _monotonic_ms()
        self._coverage = CoverageLedger(
            initialized_ms,
            initial_commit=CausalCommit(
                boundary=FactBoundary(1, 0, initialized_ms, 0),
                cause=CausalCause.RUNTIME_START,
                failure_domain=FailureScope.SESSION,
                affected_scopes=("GLOBAL",),
            ),
        )
        self._transport_enqueued_by_epoch: dict[int, int] = {}
        self._transport_overflow_by_epoch: dict[int, int] = {}
        self._scope_counts: dict[tuple[str, OptionType, str], ScopeCounts] = {}
        self._unknown_counts: Counter[str] = Counter()
        self._episode_end_counts: Counter[str] = Counter()
        self._known_active_duration_ms: Counter[str] = Counter()
        self._atomic_transition_counts: Counter[str] = Counter()
        self._band_suspended_duration_ms = 0
        self._band_suspended_started_ms: int | None = None
        self._global_continuity_epoch = 1
        self._current_continuity_epoch_started_ms = initialized_ms
        self._current_epoch_joint_evaluation_counts: Counter[tuple[str, int, str, str, str]] = (
            Counter()
        )
        self._current_epoch_joint_evaluation_first_boundaries: dict[
            tuple[str, int, str, str, str],
            FactBoundary,
        ] = {}
        self._active_continuity_incident: ContinuityIncident | None = None
        self._latest_continuity_recovery_boundary: FactBoundary | None = None
        self._next_continuity_incident_id = 1
        self._first_joint_witness_ms: int | None = None
        self._first_joint_witness_identity: _JointWitnessIdentity | None = None
        self._last_observation_identity: dict[str, tuple[object, ...]] = {}
        self._last_index_tail_identity: dict[str, tuple[object, ...]] = {}
        self._last_unknown_reason: dict[str, str | None] = {}
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
        self._fact_transaction_active = False
        self._fact_transaction_revision = 0
        self._queue_lag_currentness_active = False
        self._queue_lag_transition_pending = False
        self._queue_lag_transition_application: tuple[int, int] | None = None
        self._clean_stop_barrier_open = False

    def begin_session(
        self,
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[PendingRpc, ...]:
        if session_epoch <= 0 or monotonic_ms < 0:
            raise ValueError("session identity must be positive")
        if self._session_epoch is not None and session_epoch <= self._session_epoch:
            raise ValueError("session epoch must increase and cannot be reused")
        if self._session_epoch is not None:
            self.diagnostics.reconnect_count += 1
            self._retire_current_epoch()
        else:
            self._coverage = CoverageLedger(
                monotonic_ms,
                initial_commit=CausalCommit(
                    boundary=FactBoundary(session_epoch, 0, monotonic_ms, self._causal_seq),
                    cause=CausalCause.RUNTIME_START,
                    failure_domain=FailureScope.SESSION,
                    affected_scopes=("GLOBAL",),
                ),
            )
            self._current_continuity_epoch_started_ms = monotonic_ms
        active_incident = self._active_continuity_incident
        if active_incident is not None:
            self._recover_continuity_incident(
                active_incident,
                boundary=FactBoundary(
                    session_epoch,
                    0,
                    monotonic_ms,
                    self._causal_seq,
                ),
            )
        self._session_epoch = session_epoch
        self._last_ingress_seq = 0
        self._application_frontier_by_epoch[session_epoch] = 0
        self._last_boundary_monotonic_ms = monotonic_ms
        self._last_wire_received_ms = monotonic_ms
        self._bootstrap_queries_issued = False
        self._platform_status_ingress_seq = None
        self._post_status_bootstrap_successes.clear()
        self._channels.clear()
        self._held_subscription_frames.clear()
        self._held_subscription_frame_count = 0
        self.pending_rpcs.clear()
        self._early_rpc_responses.clear()
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
        self._ticker_accepted_currentness.clear()
        self._settled_ticker_currentness.clear()
        self._option_local_unavailable.clear()
        self.results.clear()
        self.atomic_states.clear()
        self.aggregate_results.clear()
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.clock = None
        self._last_time_currentness_token = None
        self._last_time_currentness_by_instrument.clear()
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
        self._queue_lag_currentness_active = False
        self._queue_lag_transition_pending = False
        self._queue_lag_transition_application = None
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

    @staticmethod
    def _parse_connection_error_control(
        envelope: InboundEnvelope,
    ) -> tuple[str, str, str, str, str]:
        params = envelope.get("params")
        try:
            connection_error = require_mapping(params, "connection_error.params")
            if set(connection_error) != {
                "kind",
                "reason",
                "close_code",
                "close_disposition",
                "exception_class",
            }:
                raise SourceDataError(
                    "connection_error.params fields are not the exact bounded shape"
                )
            kind = require_str(
                connection_error.get("kind"),
                "connection_error.params.kind",
            )
            reason = require_str(
                connection_error.get("reason"),
                "connection_error.params.reason",
            )
            close_code = require_str(
                connection_error.get("close_code"),
                "connection_error.params.close_code",
            )
            close_disposition = require_str(
                connection_error.get("close_disposition"),
                "connection_error.params.close_disposition",
            )
            exception_class = require_str(
                connection_error.get("exception_class"),
                "connection_error.params.exception_class",
            )
        except SourceDataError as exc:
            raise PublicProtocolIncompatibility(
                "connection error control shape is incompatible"
            ) from exc
        expected_reasons = {
            "SESSION_FAILURE": {
                CausalCause.REMOTE_CONNECTION_CLOSED.value,
                CausalCause.TRANSPORT_READ_FAILURE.value,
            },
            "PROTOCOL_INCOMPATIBILITY": {
                CausalCause.PROTOCOL_INCOMPATIBILITY.value,
            },
        }
        if reason not in expected_reasons.get(kind, set()):
            raise PublicProtocolIncompatibility("connection error kind and reason are inconsistent")
        if (
            close_code not in TRANSPORT_CLOSE_CODE_ALLOWLIST
            or close_disposition not in TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST
            or exception_class not in TRANSPORT_EXCEPTION_CLASS_ALLOWLIST
        ):
            raise PublicProtocolIncompatibility(
                "connection error attribution is outside the bounded allowlist"
            )
        expected_disposition = "CLEAN" if close_code in {"1000", "1001"} else "ABNORMAL"
        if close_disposition != expected_disposition:
            raise PublicProtocolIncompatibility(
                "connection close code and disposition are inconsistent"
            )
        return kind, reason, close_code, close_disposition, exception_class

    def reduce(
        self,
        envelope: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[PendingRpc, ...]:
        self._commands = []
        self.diagnostics.received_envelope_count += 1
        last_application_seq = self._application_frontier_by_epoch.get(
            envelope.session_epoch,
            0,
        )
        if envelope.ingress_seq != last_application_seq + 1:
            self.diagnostics.ingress_gap_or_duplicate_count += 1
            if (
                envelope.session_epoch == self._session_epoch
                and envelope.session_epoch not in self._retired_epochs
            ):
                self._retire_current_epoch(
                    "INGRESS_GAP_OR_DUPLICATE",
                    monotonic_ms=envelope.received_monotonic_ms,
                )
            raise PublicSessionError("application event sequence is not continuous")
        self._application_frontier_by_epoch[envelope.session_epoch] = envelope.ingress_seq
        channel_class = _channel_class(
            envelope,
            combo_names=set(self.combos) | self._subscribed_combo_names,
        )
        self.diagnostics.channel_received_count[channel_class] += 1
        self.diagnostics.reduced_envelope_count += 1
        self.diagnostics.channel_processed_count[channel_class] += 1
        connection_error_control: tuple[str, str, str, str, str] | None = None
        if envelope.control_event is not None:
            self.diagnostics.send_control_event_count += 1
        elif envelope.get("method") == "connection_error":
            connection_error_control = self._parse_connection_error_control(envelope)
            _, _, close_code, close_disposition, exception_class = connection_error_control
            self.diagnostics.connection_error_event_count += 1
            self.diagnostics.transport_terminal_attribution_count[
                (close_code, close_disposition, exception_class)
            ] += 1
        if envelope.session_epoch == self._session_epoch:
            self._last_ingress_seq = envelope.ingress_seq
        if (
            envelope.session_epoch != self._session_epoch
            or envelope.session_epoch in self._retired_epochs
        ):
            self.diagnostics.retired_epoch_frame_count += 1
            if channel_class == "HEARTBEAT":
                params = envelope.get("params")
                try:
                    heartbeat_params = require_mapping(params, "heartbeat.params")
                    heartbeat_type = require_str(
                        heartbeat_params.get("type"),
                        "heartbeat.params.type",
                    )
                    valid_heartbeat = heartbeat_type in {"heartbeat", "test_request"}
                except SourceDataError:
                    valid_heartbeat = False
                self._note_source_shape("heartbeat", params, valid=valid_heartbeat)
            response_id = envelope.get("id")
            if isinstance(response_id, int) and not isinstance(response_id, bool):
                self.diagnostics.late_response_count += 1
                self.diagnostics.rpc_orphan_late_wire_count += 1
            return ()
        self._queue_lag_transition_application = None
        lag_ms = processed_monotonic_ms - envelope.received_monotonic_ms
        if lag_ms < 0:
            raise PublicProtocolError("inbound frame receive time is in the future")
        self.diagnostics.max_receive_to_reduce_lag_ms = max(
            self.diagnostics.max_receive_to_reduce_lag_ms,
            lag_ms,
        )
        lagged = lag_ms > self.policy.runtime_limits.notification_queue_lag_deadline_ms
        if lagged != self._queue_lag_currentness_active:
            self._queue_lag_currentness_active = lagged
            self._queue_lag_transition_pending = True
            self._queue_lag_transition_application = (
                envelope.session_epoch,
                envelope.ingress_seq,
            )
        transaction_revision = self._fact_transaction_revision
        causal_seq = self._causal_seq
        if envelope.control_event is not None:
            self._last_boundary_monotonic_ms = max(
                self._last_boundary_monotonic_ms,
                envelope.received_monotonic_ms,
            )
            self._apply_send_control(
                envelope.control_event,
                boundary=self._current_boundary(envelope),
            )
            self._settle_pending_queue_lag_transition(
                envelope,
                transaction_revision=transaction_revision,
                causal_seq=causal_seq,
            )
            return self._take_commands()
        if envelope.get("method") != "connection_error":
            self._last_wire_received_ms = max(
                self._last_wire_received_ms,
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
                kind, reason, _, _, _ = cast(
                    tuple[str, str, str, str, str],
                    connection_error_control,
                )
                self._retire_current_epoch(reason)
                if kind == "PROTOCOL_INCOMPATIBILITY":
                    raise PublicProtocolIncompatibility(
                        "production-public protocol is incompatible"
                    )
                raise PublicSessionError("production-public connection closed")
            else:
                raise PublicProtocolError("unexpected inbound JSON-RPC frame")
        self._settle_pending_queue_lag_transition(
            envelope,
            transaction_revision=transaction_revision,
            causal_seq=causal_seq,
        )
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
        if method not in RPC_METHOD_ALLOWLIST:
            raise ValueError("RPC method is outside the exact public allowlist")
        request = PendingRpc(
            request_id=self._next_request_id,
            purpose=purpose,
            method=method,
            params=params,
            session_epoch=self._session_epoch,
            scope=scope,
            generation=generation,
            origin_boundary=origin_boundary,
            send_deadline_monotonic_ms=(
                origin_boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            ),
            failure_scope=failure_scope,
        )
        self._next_request_id += 1
        self.pending_rpcs[request.request_id] = request
        self._rpc_lifecycles[request.request_id] = _RpcLifecycle(request=request)
        self._commands.append(request)
        self.diagnostics.rpc_request_count[method] += 1
        if purpose is RpcPurpose.COMBO_CATALOG:
            self.diagnostics.combo_authoritative_refresh_attempt_count += 1
            self._combo_refresh_request_id = request.request_id
        return request

    def begin_clean_stop(self) -> None:
        self._clean_stop_barrier_open = True

    def _apply_send_control(
        self,
        event: SendControlEvent,
        *,
        boundary: FactBoundary,
    ) -> None:
        lifecycle = self._rpc_lifecycles.get(event.request_id)
        if lifecycle is None:
            return
        if lifecycle.state in {
            RpcState.SUCCESS,
            RpcState.ERROR,
            RpcState.DEADLINE_LATE,
            RpcState.RETIRED,
            RpcState.CENSORED,
        }:
            return
        request = lifecycle.request
        if (
            lifecycle.state is RpcState.SCHEDULED
            and event.boundary_monotonic_ms > request.send_deadline_monotonic_ms
        ):
            held_response = self._early_rpc_responses.pop(event.request_id, None)
            if held_response is not None:
                self.diagnostics.late_response_count += 1
                self.diagnostics.rpc_orphan_late_wire_count += 1
            self.pending_rpcs.pop(event.request_id, None)
            transitioned = self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=event.boundary_monotonic_ms,
                record_latency=False,
                allow_unsent=True,
            )
            if transitioned:
                self._apply_request_failure(request)
            return
        if event.kind is SendControlKind.SEND_COMPLETED:
            if lifecycle.state is RpcState.SENT:
                return
            if event.boundary_monotonic_ms < request.origin_boundary.received_monotonic_ms:
                raise PublicProtocolError("RPC send boundary precedes scheduling boundary")
            lifecycle.state = RpcState.SENT
            lifecycle.sent_monotonic_ms = event.boundary_monotonic_ms
            lifecycle.response_deadline_monotonic_ms = (
                event.boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self.diagnostics.rpc_sent_count[request.method] += 1
            held_response = self._early_rpc_responses.pop(event.request_id, None)
            if held_response is not None:
                self._apply_response(
                    held_response,
                    commit_boundary=boundary,
                )
            return
        if event.kind is not SendControlKind.SEND_FAILED:
            raise PublicProtocolError("unknown send control kind")
        if lifecycle.state is RpcState.SENT:
            raise PublicProtocolError("RPC send failure cannot follow a completed send boundary")
        held_response = self._early_rpc_responses.pop(event.request_id, None)
        if held_response is not None:
            self.diagnostics.late_response_count += 1
            self.diagnostics.rpc_orphan_late_wire_count += 1
        self.pending_rpcs.pop(event.request_id, None)
        if event.failure is SendFailureKind.CANCELLED and self._clean_stop_barrier_open:
            self._finish_rpc(
                request,
                state=RpcState.CENSORED,
                terminal_monotonic_ms=event.boundary_monotonic_ms,
                record_latency=False,
                allow_unsent=True,
            )
            return
        transitioned = self._finish_rpc(
            request,
            state=RpcState.ERROR,
            terminal_monotonic_ms=event.boundary_monotonic_ms,
            record_latency=False,
            allow_unsent=True,
        )
        if transitioned:
            self._apply_request_failure(request)

    def _finish_rpc(
        self,
        request: PendingRpc,
        *,
        state: RpcState,
        terminal_monotonic_ms: int,
        record_latency: bool,
        allow_unsent: bool = False,
    ) -> bool:
        lifecycle = self._rpc_lifecycles.get(request.request_id)
        if lifecycle is None or lifecycle.request != request:
            raise RuntimeError("RPC lifecycle identity is missing")
        terminal_states = {
            RpcState.SUCCESS,
            RpcState.ERROR,
            RpcState.DEADLINE_LATE,
            RpcState.RETIRED,
            RpcState.CENSORED,
        }
        if state not in terminal_states:
            raise ValueError("RPC terminal state is invalid")
        if lifecycle.state in terminal_states:
            return False
        if (
            state
            in {
                RpcState.SUCCESS,
                RpcState.ERROR,
                RpcState.DEADLINE_LATE,
            }
            and lifecycle.state is not RpcState.SENT
            and not allow_unsent
        ):
            raise RuntimeError("wire RPC terminal state requires a send boundary")
        if (
            lifecycle.sent_monotonic_ms is not None
            and terminal_monotonic_ms < lifecycle.sent_monotonic_ms
        ):
            raise PublicProtocolError("RPC terminal boundary precedes its send boundary")
        previous_state = lifecycle.state
        lifecycle.state = state
        lifecycle.terminal_from_state = previous_state
        lifecycle.terminal_monotonic_ms = terminal_monotonic_ms
        method = request.method
        if state is RpcState.SUCCESS:
            self.diagnostics.rpc_success_count[method] += 1
        elif state is RpcState.ERROR:
            self.diagnostics.rpc_error_count[method] += 1
        elif state is RpcState.DEADLINE_LATE:
            self.diagnostics.rpc_deadline_late_count[method] += 1
        elif state is RpcState.RETIRED:
            self.diagnostics.rpc_retired_count[method] += 1
        else:
            self.diagnostics.rpc_censored_count[method] += 1
        terminal_origin = (
            self.diagnostics.rpc_pre_send_terminal_count
            if previous_state is RpcState.SCHEDULED
            else self.diagnostics.rpc_post_send_terminal_count
        )
        if previous_state not in {RpcState.SCHEDULED, RpcState.SENT}:
            raise RuntimeError("RPC terminal origin is invalid")
        terminal_origin[(method, state.value)] += 1
        if record_latency:
            sent_monotonic_ms = lifecycle.sent_monotonic_ms
            if sent_monotonic_ms is None:
                raise RuntimeError("RPC latency requires a send boundary")
            latency_ms = terminal_monotonic_ms - sent_monotonic_ms
            self.diagnostics.rpc_latency_count[method] += 1
            self.diagnostics.rpc_latency_sum[method] += latency_ms
            self.diagnostics.rpc_latency_max[method] = max(
                self.diagnostics.rpc_latency_max[method],
                latency_ms,
            )
        return True

    def _record_heartbeat_wire_terminal(
        self,
        request: PendingRpc,
        *,
        latency_ms: int,
        success: bool,
    ) -> None:
        if request.purpose is not RpcPurpose.HEARTBEAT_TEST:
            return
        if success:
            self.diagnostics.heartbeat_public_test_success_count += 1
        else:
            self.diagnostics.heartbeat_public_test_error_count += 1
        self.diagnostics.heartbeat_latency_count += 1
        self.diagnostics.heartbeat_latency_sum += latency_ms
        self.diagnostics.heartbeat_latency_max = max(
            self.diagnostics.heartbeat_latency_max,
            latency_ms,
        )

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
            self._retire_current_epoch(
                "QUEUE_OVERFLOW",
                monotonic_ms=envelope.received_monotonic_ms,
            )
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

    def _settle_pending_queue_lag_transition(
        self,
        envelope: InboundEnvelope,
        *,
        transaction_revision: int,
        causal_seq: int,
    ) -> None:
        if not self._queue_lag_transition_pending:
            self._queue_lag_transition_application = None
            return
        if self._fact_transaction_revision != transaction_revision:
            self._queue_lag_transition_pending = False
            self._queue_lag_transition_application = None
            return
        if self._causal_seq == causal_seq:
            self._causal_seq += 1
        boundary = FactBoundary(
            envelope.session_epoch,
            envelope.ingress_seq,
            self._last_boundary_monotonic_ms,
            self._causal_seq,
        )
        try:
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.QUEUE_LAG_DEADLINE,
                    failure_domain=FailureScope.SESSION,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=tuple(self.options),
                countable=False,
                acceptance_eligible=False,
            )
        finally:
            self._queue_lag_transition_pending = False
            self._queue_lag_transition_application = None

    def _apply_response(
        self,
        envelope: InboundEnvelope,
        *,
        commit_boundary: FactBoundary | None = None,
    ) -> None:
        request_id = envelope.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            raise PublicProtocolError("response id is invalid")
        request = self.pending_rpcs.get(request_id)
        if request is None or request.session_epoch != self._session_epoch:
            self.diagnostics.late_response_count += 1
            self.diagnostics.rpc_orphan_late_wire_count += 1
            return
        lifecycle = self._rpc_lifecycles[request_id]
        if lifecycle.state is RpcState.SCHEDULED:
            if request_id in self._early_rpc_responses:
                self.diagnostics.late_response_count += 1
                self.diagnostics.rpc_orphan_late_wire_count += 1
            else:
                self._early_rpc_responses[request_id] = envelope
            return
        if lifecycle.state is not RpcState.SENT:
            self.pending_rpcs.pop(request_id, None)
            self.diagnostics.late_response_count += 1
            self.diagnostics.rpc_orphan_late_wire_count += 1
            return
        sent_monotonic_ms = lifecycle.sent_monotonic_ms
        deadline_monotonic_ms = lifecycle.response_deadline_monotonic_ms
        if sent_monotonic_ms is None or deadline_monotonic_ms is None:
            raise RuntimeError("sent RPC lacks its immutable send boundary")
        terminal_monotonic_ms = max(
            envelope.received_monotonic_ms,
            sent_monotonic_ms,
        )
        latency_ms = terminal_monotonic_ms - sent_monotonic_ms
        self.pending_rpcs.pop(request_id, None)
        if request.purpose not in {
            RpcPurpose.SET_HEARTBEAT,
            RpcPurpose.HEARTBEAT_TEST,
        }:
            self._causal_seq += 1
        if terminal_monotonic_ms > deadline_monotonic_ms:
            self.diagnostics.late_response_count += 1
            self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._record_heartbeat_wire_terminal(
                request,
                latency_ms=latency_ms,
                success=False,
            )
            self._note_source_shape(request.method, envelope.get("result"), valid=False)
            self._apply_request_failure(request)
            return
        if "error" in envelope:
            self._finish_rpc(
                request,
                state=RpcState.ERROR,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._record_heartbeat_wire_terminal(
                request,
                latency_ms=latency_ms,
                success=False,
            )
            self._note_source_shape(request.method, envelope["error"], valid=False)
            if _is_rate_limit_error(envelope["error"]):
                self.diagnostics.rpc_rate_limit_count[request.method] += 1
            self._apply_request_failure(request)
            return
        if "result" not in envelope:
            self._finish_rpc(
                request,
                state=RpcState.ERROR,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._record_heartbeat_wire_terminal(
                request,
                latency_ms=latency_ms,
                success=False,
            )
            self._note_source_shape(request.method, None, valid=False)
            raise PublicProtocolIncompatibility("JSON-RPC response lacks result")
        result = envelope["result"]
        channel_change_response = request.purpose in {
            RpcPurpose.SUBSCRIBE_CHANNELS,
            RpcPurpose.UNSUBSCRIBE_CHANNELS,
        }
        if request.purpose is RpcPurpose.HEARTBEAT_TEST and (
            not isinstance(result, dict)
            or not isinstance(result.get("version"), str)
            or not result["version"]
        ):
            self._finish_rpc(
                request,
                state=RpcState.ERROR,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._record_heartbeat_wire_terminal(
                request,
                latency_ms=latency_ms,
                success=False,
            )
            self._note_source_shape(request.method, result, valid=False)
            raise PublicProtocolIncompatibility("public/test result lacks a valid version")
        if not channel_change_response:
            self._finish_rpc(
                request,
                state=RpcState.SUCCESS,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
        boundary = (
            replace(commit_boundary, causal_seq=self._causal_seq)
            if commit_boundary is not None
            else self._current_boundary(envelope)
        )
        source_valid = True
        source_shape_noted = False
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
                (
                    acknowledged_channels,
                    missing_channels,
                    wire_partial,
                ) = self._partition_channel_ack(request, result)
            except SourceDataError as exc:
                self._finish_rpc(
                    request,
                    state=RpcState.ERROR,
                    terminal_monotonic_ms=terminal_monotonic_ms,
                    record_latency=True,
                )
                self._note_source_shape(request.method, result, valid=False)
                raise PublicProtocolIncompatibility(
                    f"{request.method} acknowledgement shape is incompatible"
                ) from exc
            self._finish_rpc(
                request,
                state=RpcState.ERROR if wire_partial else RpcState.SUCCESS,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._note_source_shape(request.method, result, valid=True)
            source_shape_noted = True
            if missing_channels:
                self._apply_request_failure(
                    replace(
                        request,
                        params={"channels": list(missing_channels)},
                    )
                )
            self._apply_channel_ack(request, acknowledged_channels, boundary)
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
                self._retire_current_epoch(CausalCause.RELEVANT_PLATFORM_LOCK.value)
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
                        sent_monotonic_ms,
                        terminal_monotonic_ms,
                        stale_deadline_ms=self.policy.runtime_limits.clock_stale_deadline_ms,
                    )
                else:
                    self.clock = self.clock.refresh(
                        server_ms,
                        sent_monotonic_ms,
                        terminal_monotonic_ms,
                    )
            except ContinuityGap:
                self._invalidate_clock_index(
                    boundary,
                    reason="CLOCK_GAP",
                    triggering_commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.CLOCK_FACT,
                        failure_domain=FailureScope.CLOCK_INDEX,
                        affected_scopes=("GLOBAL",),
                    ),
                )
                self._note_source_shape(request.method, result, valid=True)
                return
            self._clock_revision += 1
            self._next_clock_refresh_ms = (
                boundary.received_monotonic_ms
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
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.CLOCK_FACT,
                    failure_domain=FailureScope.CLOCK_INDEX,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=tuple(self.options),
                countable=False,
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
            self._record_heartbeat_wire_terminal(
                request,
                latency_ms=latency_ms,
                success=True,
            )
        if not source_shape_noted:
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
            self._settle_clock_gap(
                CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.CLOCK_GAP,
                    failure_domain=FailureScope.CLOCK_INDEX,
                    affected_scopes=("GLOBAL",),
                )
            )
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
            failure_boundary = self._current_fact_boundary()
            cause = CausalCause.OPTION_CATALOG
            catalog_affected_instruments = tuple(self.options)
            catalog_affected_scopes: tuple[str, ...] = ("GLOBAL",)
            if (
                request.purpose is RpcPurpose.OPTION_METADATA
                and self._option_metadata_pending.get(request.scope) == request.generation
            ):
                self._option_metadata_pending.pop(request.scope, None)
                self._option_lifecycle_unavailable[request.scope] = "OPTION_METADATA_REQUEST_FAILED"
                cause = CausalCause.OPTION_METADATA_REQUEST_FAILED
                catalog_affected_instruments = (request.scope,)
                catalog_affected_scopes = self._option_local_coverage_scopes((request.scope,))
            self.option_catalog.mark_incomplete()
            self._next_option_catalog_recovery_ms = (
                self._last_boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._settle_fact(
                commit=CausalCommit(
                    boundary=failure_boundary,
                    cause=cause,
                    failure_domain=FailureScope.OPTION_CATALOG,
                    affected_scopes=catalog_affected_scopes,
                ),
                affected_instruments=catalog_affected_instruments,
                countable=False,
            )
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
                failure_boundary = self._current_fact_boundary()
                self._settle_fact(
                    commit=CausalCommit(
                        boundary=failure_boundary,
                        cause=CausalCause.OPTION_CHANNEL_FAILURE,
                        failure_domain=FailureScope.OPTION,
                        affected_scopes=self._option_local_coverage_scopes(
                            tuple(sorted(affected_instruments))
                        ),
                    ),
                    affected_instruments=tuple(sorted(affected_instruments)),
                    countable=False,
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
            self._settle_combo_boundary(
                self._current_fact_boundary(),
                cause=CausalCause.COMBO_CATALOG,
            )
        elif request.failure_scope is FailureScope.CLOCK_INDEX:
            self._invalidate_clock_index(
                self._current_fact_boundary(),
                reason="CLOCK_GAP",
            )
        elif request.failure_scope is FailureScope.SESSION:
            self._retire_current_epoch(CausalCause.SESSION_RPC_FAILURE.value)
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

    def _partition_channel_ack(
        self,
        request: PendingRpc,
        result: object,
    ) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
        channels_raw = request.params.get("channels")
        if not isinstance(channels_raw, list) or not all(
            isinstance(channel, str) for channel in channels_raw
        ):
            raise RuntimeError("pending channel request lost its exact channels")
        channels = tuple(channels_raw)
        acknowledged = validate_subscription_ack(channels, result)
        acknowledged_set = set(acknowledged)
        current_channels = tuple(
            channel
            for channel in channels
            if self._channels[channel].generation == request.generation
        )
        acknowledged_channels = tuple(
            channel for channel in current_channels if channel in acknowledged_set
        )
        missing_channels = tuple(
            channel for channel in current_channels if channel not in acknowledged_set
        )
        return (
            acknowledged_channels,
            missing_channels,
            len(acknowledged) != len(channels),
        )

    def _apply_channel_ack(
        self,
        request: PendingRpc,
        acknowledged_channels: tuple[str, ...],
        boundary: FactBoundary,
    ) -> None:
        if not acknowledged_channels:
            return
        if request.purpose is RpcPurpose.UNSUBSCRIBE_CHANNELS:
            for channel in acknowledged_channels:
                slot = self._channels[channel]
                slot.state = ChannelState.RETIRED
                self._drop_held_frames(channel=channel)
            self._drain_held_frames(boundary)
            self._reconcile_channel_intents(acknowledged_channels, boundary)
            self._update_subscription_peaks()
            return

        admitted_channels = tuple(
            channel
            for channel in acknowledged_channels
            if self._channels[channel].desired_subscribed
            and not self._channels[channel].resync_requested
        )
        self.platform.acknowledge(admitted_channels)
        if OPTION_LIFECYCLE_CHANNEL in admitted_channels:
            self.option_catalog.acknowledge_lifecycle()
        if COMBO_LIFECYCLE_CHANNEL in admitted_channels:
            self.combo_catalog.acknowledge_lifecycle()
        for channel in acknowledged_channels:
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
        self._reconcile_channel_intents(acknowledged_channels, boundary)
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
                    commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.PLATFORM_READY,
                        failure_domain=FailureScope.SESSION,
                        affected_scopes=("GLOBAL",),
                    ),
                    affected_instruments=tuple(self.options),
                    countable=False,
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
                if _is_target_option_lifecycle(data):
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
                        commit=CausalCommit(
                            boundary=boundary,
                            cause=CausalCause.PLATFORM_FACT,
                            failure_domain=FailureScope.SESSION,
                            affected_scopes=("GLOBAL",),
                        ),
                        affected_instruments=tuple(self.options),
                        countable=False,
                    )
            elif channel == "platform_state.public_methods_state":
                self.platform.apply_public_methods_notification(data)
                if self.platform.reason == "PUBLIC_METHODS_DENIED":
                    epoch_failure_reason = self.platform.reason
                else:
                    self._settle_fact(
                        commit=CausalCommit(
                            boundary=boundary,
                            cause=CausalCause.PLATFORM_FACT,
                            failure_domain=FailureScope.SESSION,
                            affected_scopes=("GLOBAL",),
                        ),
                        affected_instruments=tuple(self.options),
                        countable=False,
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
            self._retire_current_epoch(epoch_failure_reason)
            raise PublicSessionError(
                f"platform guard invalidated bootstrap epoch: {epoch_failure_reason}"
            )

    def _mark_option_catalog_incomplete(self, boundary: FactBoundary) -> None:
        self.option_catalog.mark_incomplete()
        self._next_option_catalog_recovery_ms = (
            boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=CausalCause.OPTION_LIFECYCLE,
                failure_domain=FailureScope.OPTION_CATALOG,
                affected_scopes=("GLOBAL",),
            ),
            affected_instruments=tuple(self.options),
            countable=False,
        )

    def _mark_combo_catalog_incomplete(self, boundary: FactBoundary) -> None:
        self.combo_catalog.mark_incomplete()
        self._next_combo_catalog_recovery_ms = (
            boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
        self._settle_combo_boundary(
            boundary,
            cause=CausalCause.COMBO_LIFECYCLE,
        )

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
                self._apply_option_lifecycle(event, boundary, settle=False)
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
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=CausalCause.OPTION_CATALOG,
                failure_domain=FailureScope.OPTION_CATALOG,
                affected_scopes=("GLOBAL",),
            ),
            affected_instruments=tuple(self.options),
            countable=False,
        )
        self._ensure_combo_catalog_refresh(boundary)
        return complete

    def _apply_option_lifecycle(
        self,
        payload: object,
        boundary: FactBoundary,
        *,
        settle: bool = True,
    ) -> None:
        data = require_mapping(payload, "option lifecycle")
        instrument_name = require_str(
            data.get("instrument_name"),
            "option lifecycle.instrument_name",
        )
        state = require_str(data.get("state"), "option lifecycle.state")
        if not _is_target_option_instrument_name(instrument_name):
            return
        existing = self.catalog_options.get(instrument_name) or self.options.get(instrument_name)
        affected_scope_keys = (
            ((existing.expiration_timestamp_ms, existing.option_type),)
            if existing is not None
            else ()
        )
        affected_scopes = self._option_lifecycle_affected_scopes(
            instrument_name,
            existing,
            boundary,
        )
        self._option_lifecycle_revision[instrument_name] += 1
        generation = self._option_lifecycle_revision[instrument_name]
        self._option_lifecycle_state[instrument_name] = state
        if state not in INSTRUMENT_LIFECYCLE_STATES:
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable[instrument_name] = (
                f"OPTION_LIFECYCLE_UNKNOWN:{state}"
            )
            raise SourceDataError("option lifecycle.state is unsupported")
        if state in FINAL_INSTRUMENT_LIFECYCLE_STATES:
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable.pop(instrument_name, None)
            self.catalog_options.pop(instrument_name, None)
            self._complete_option_catalog_if_ready()
            self._sync_membership(boundary)
            if settle:
                self._settle_fact(
                    commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.OPTION_LIFECYCLE,
                        failure_domain=FailureScope.OPTION_CATALOG,
                        affected_scopes=affected_scopes,
                    ),
                    affected_instruments=(instrument_name,),
                    affected_scope_keys=affected_scope_keys,
                    countable=False,
                )
            return
        if state in TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES:
            reason = f"OPTION_LIFECYCLE_{state.upper()}"
            self._option_metadata_pending.pop(instrument_name, None)
            self._option_lifecycle_unavailable[instrument_name] = reason
            if instrument_name in self.catalog_options:
                self._complete_option_catalog_if_ready()
                if settle:
                    self._settle_fact(
                        commit=CausalCommit(
                            boundary=boundary,
                            cause=CausalCause.OPTION_LIFECYCLE,
                            failure_domain=FailureScope.OPTION_CATALOG,
                            affected_scopes=affected_scopes,
                        ),
                        affected_instruments=(instrument_name,),
                        affected_scope_keys=affected_scope_keys,
                        countable=False,
                    )
            else:
                if settle:
                    self._mark_option_catalog_incomplete(boundary)
                else:
                    self.option_catalog.mark_incomplete()
                    self._next_option_catalog_recovery_ms = (
                        boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
                    )
            return
        self._option_metadata_pending[instrument_name] = generation
        self._option_lifecycle_unavailable[instrument_name] = "OPTION_METADATA_PENDING"
        self.option_catalog.complete = False
        if settle:
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.OPTION_METADATA_PENDING,
                    failure_domain=FailureScope.OPTION_CATALOG,
                    affected_scopes=affected_scopes,
                ),
                affected_instruments=(instrument_name,),
                affected_scope_keys=affected_scope_keys,
                countable=False,
            )
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
            boundary = self._current_fact_boundary()
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.OPTION_METADATA,
                    failure_domain=FailureScope.OPTION_CATALOG,
                    affected_scopes=self._option_local_coverage_scopes((request.scope,)),
                ),
                affected_instruments=(request.scope,),
                countable=False,
            )
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
                    commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.OPTION_METADATA_ABSENT,
                        failure_domain=FailureScope.OPTION_CATALOG,
                        affected_scopes=("GLOBAL",),
                    ),
                    affected_instruments=tuple(self.options),
                    countable=False,
                )
                self._ensure_combo_catalog_refresh(boundary)
                return True
            if self._option_metadata_pending.get(request.scope) == request.generation:
                self._option_metadata_pending.pop(request.scope, None)
            self._option_lifecycle_unavailable[request.scope] = "OPTION_METADATA_INVALID"
            self.option_catalog.mark_incomplete()
            self._next_option_catalog_recovery_ms = (
                self._last_boundary_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            failure_boundary = self._current_fact_boundary()
            self._settle_fact(
                commit=CausalCommit(
                    boundary=failure_boundary,
                    cause=CausalCause.OPTION_METADATA_INVALID,
                    failure_domain=FailureScope.OPTION_CATALOG,
                    affected_scopes=self._option_local_coverage_scopes((request.scope,)),
                ),
                affected_instruments=(request.scope,),
                countable=False,
            )
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
            commit=CausalCommit(
                boundary=boundary,
                cause=CausalCause.OPTION_METADATA,
                failure_domain=FailureScope.OPTION_CATALOG,
                affected_scopes=self._option_lifecycle_affected_scopes(
                    instrument.instrument_name,
                    instrument,
                    boundary,
                ),
            ),
            affected_instruments=(instrument.instrument_name,),
            affected_scope_keys=((instrument.expiration_timestamp_ms, instrument.option_type),),
            countable=False,
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
            self._close_option_local_unavailability(
                name,
                monotonic_ms=boundary.received_monotonic_ms,
                end_disposition="REASON_CHANGED",
            )
            self._ticker_accepted_currentness.pop(name, None)
            self.options.pop(name, None)
            self.results.pop(name, None)
            self.tickers.pop(name, None)
            self._ticker_generations.pop(name, None)
            self._ticker_currentness_latches.pop(name, None)
            self._ticker_unavailable.pop(name, None)
            self._settled_ticker_currentness.pop(name, None)
            self.option_books.pop(name, None)
            self._last_observation_identity.pop(name, None)
            self._last_index_tail_identity.pop(name, None)
            self._last_time_currentness_by_instrument.pop(name, None)
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
            gap_commit = CausalCommit(
                boundary=boundary,
                cause=CausalCause.INDEX_CONTINUITY_GAP,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            )
            if not self._index_gap_active:
                self.diagnostics.index_gap_count += 1
                self._index_gap_active = True
                active = self._active_continuity_incident
                self._restart_global_continuity(
                    gap_commit,
                    incident=(
                        active
                        if active is not None
                        and active.restart_effect.failure_domain is FailureScope.CLOCK_INDEX
                        else None
                    ),
                )
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
                commit=gap_commit,
                affected_instruments=tuple(self.options),
                countable=False,
            )
            return False
        trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        self.index.seal_ready(trusted.lower_ms)
        self.platform.note_fresh_index_coverage()
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=CausalCause.INDEX_TICK,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            ),
            affected_instruments=tuple(self.options),
            countable=True,
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

    def _record_ticker_application(
        self,
        disposition: str,
        *,
        instrument_name: str,
        generation: int,
        boundary: FactBoundary,
        previous_source_timestamp_ms: int | None = None,
        candidate_source_timestamp_ms: int | None = None,
    ) -> None:
        self.diagnostics.ticker_application_count[disposition] += 1
        if (
            disposition != "LATE_IGNORED"
            or previous_source_timestamp_ms is None
            or candidate_source_timestamp_ms is None
            or candidate_source_timestamp_ms >= previous_source_timestamp_ms
        ):
            return
        row = {
            "instrument_name": instrument_name,
            "generation": generation,
            "ingress_seq": boundary.ingress_seq,
            "previous_source_timestamp_ms": previous_source_timestamp_ms,
            "candidate_source_timestamp_ms": candidate_source_timestamp_ms,
            "timestamp_delta_ms": (candidate_source_timestamp_ms - previous_source_timestamp_ms),
            "received_monotonic_ms": boundary.received_monotonic_ms,
            "disposition": "LATE_IGNORED",
        }
        if len(self.diagnostics.late_ticker_diagnostics) < 256:
            self.diagnostics.late_ticker_diagnostics.append(row)
        else:
            self.diagnostics.omitted_late_ticker_diagnostic_count += 1

    def _classify_ticker_candidate(
        self,
        ticker: TickerState,
        boundary: FactBoundary,
    ) -> str:
        if self.clock is None:
            classification = "TRUSTED_TIME_UNKNOWN"
        else:
            try:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
            except ContinuityGap:
                classification = "TRUSTED_TIME_UNKNOWN"
            else:
                if ticker.source_timestamp_ms > trusted.upper_ms:
                    classification = "TIMESTAMP_AHEAD"
                elif (
                    trusted.upper_ms
                    > ticker.source_timestamp_ms
                    + self.policy.runtime_limits.ticker_source_stale_deadline_ms
                ):
                    classification = "SOURCE_STALE"
                else:
                    classification = "CURRENT"
        self.diagnostics.ticker_candidate_currentness_count[classification] += 1
        return classification

    def _start_option_local_unavailability(
        self,
        instrument_name: str,
        *,
        generation: int,
        reason: str,
        monotonic_ms: int,
    ) -> None:
        previous = self._option_local_unavailable.get(instrument_name)
        if previous is not None and previous.generation == generation and previous.reason == reason:
            return
        if previous is not None:
            self._close_option_local_unavailability(
                instrument_name,
                monotonic_ms=monotonic_ms,
                end_disposition="REASON_CHANGED",
            )
        self._option_local_unavailable[instrument_name] = _OptionLocalUnavailable(
            instrument_name=instrument_name,
            generation=generation,
            reason=reason,
            start_monotonic_ms=monotonic_ms,
            global_continuity_epoch=self._global_continuity_epoch,
        )
        self.diagnostics.option_local_unavailable_count[reason] += 1

    def _close_option_local_unavailability(
        self,
        instrument_name: str,
        *,
        monotonic_ms: int,
        end_disposition: str,
    ) -> None:
        unavailable = self._option_local_unavailable.pop(instrument_name, None)
        if unavailable is None:
            return
        row = {
            "instrument_name": unavailable.instrument_name,
            "generation": unavailable.generation,
            "reason": unavailable.reason,
            "start_monotonic_ms": unavailable.start_monotonic_ms,
            "end_monotonic_ms": monotonic_ms,
            "duration_ms": max(0, monotonic_ms - unavailable.start_monotonic_ms),
            "end_disposition": end_disposition,
            "global_continuity_epoch": unavailable.global_continuity_epoch,
        }
        self._compact_option_local_intervals(monotonic_ms)
        if len(self.diagnostics.option_local_intervals) < OPTION_LOCAL_RETAINED_INTERVAL_LIMIT:
            self.diagnostics.option_local_intervals.append(row)
        else:
            self.diagnostics.omitted_option_local_interval_count += 1
            self.diagnostics.omitted_option_local_interval_count_by_reason[
                (unavailable.reason, end_disposition)
            ] += 1
        self.diagnostics.option_local_end_count[end_disposition] += 1
        if end_disposition == "RECOVERED":
            self.diagnostics.option_local_recovery_count[unavailable.reason] += 1

    def _compact_option_local_intervals(self, monotonic_ms: int) -> None:
        acceptance_start_ms = monotonic_ms - OPTION_LOCAL_ACCEPTANCE_WINDOW_MS
        intervals = self.diagnostics.option_local_intervals
        while intervals:
            next_end_monotonic_ms = cast(int, intervals[0]["end_monotonic_ms"])
            if next_end_monotonic_ms > acceptance_start_ms:
                break
            row = intervals.popleft()
            reason = str(row["reason"])
            disposition = str(row["end_disposition"])
            self.diagnostics.option_local_outside_window_interval_count += 1
            self.diagnostics.option_local_outside_window_interval_count_by_reason[
                (reason, disposition)
            ] += 1
            previous_latest = self.diagnostics.option_local_outside_window_latest_end_monotonic_ms
            self.diagnostics.option_local_outside_window_latest_end_monotonic_ms = (
                next_end_monotonic_ms
                if previous_latest is None
                else max(previous_latest, next_end_monotonic_ms)
            )

    def _close_all_option_local_unavailable(
        self,
        monotonic_ms: int,
        *,
        end_disposition: str,
    ) -> None:
        for instrument_name in tuple(self._option_local_unavailable):
            self._close_option_local_unavailability(
                instrument_name,
                monotonic_ms=monotonic_ms,
                end_disposition=end_disposition,
            )

    def _transition_ticker_accepted_currentness(
        self,
        instrument_name: str,
        *,
        state: str,
        reason: str,
        boundary: FactBoundary,
    ) -> None:
        if self._ticker_accepted_currentness.get(instrument_name) != state:
            self._ticker_accepted_currentness[instrument_name] = state
            self.diagnostics.ticker_accepted_currentness_transition_count[state] += 1
        if state == "CURRENT":
            self._close_option_local_unavailability(
                instrument_name,
                monotonic_ms=boundary.received_monotonic_ms,
                end_disposition="RECOVERED",
            )
            return
        self._start_option_local_unavailability(
            instrument_name,
            generation=self._ticker_generation(instrument_name),
            reason=reason,
            monotonic_ms=boundary.received_monotonic_ms,
        )

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
    ) -> None:
        previous = self._ticker_currentness_latches.get(instrument_name)
        if previous is not None and previous.generation == generation:
            return
        self._ticker_currentness_latches[instrument_name] = _TickerCurrentnessLatch(
            generation=generation,
            source_timestamp_ms=source_timestamp_ms,
            reason=reason,
        )

    def settle_source_currentness(
        self,
        boundary: FactBoundary,
    ) -> tuple[str, ...]:
        """Settle accepted source as-of state without invoking detector evaluation."""
        trusted: TimeInterval | None = None
        if self.clock is not None:
            try:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
            except ContinuityGap:
                trusted = None
        newly_stale: list[str] = []
        settled: dict[str, _SettledTickerCurrentness] = {}
        for instrument_name in sorted(self.options):
            previous_state = self._ticker_accepted_currentness.get(instrument_name)
            unavailable = self._ticker_unavailable.get(instrument_name)
            latch = self._ticker_currentness_latches.get(instrument_name)
            if trusted is None:
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.MISSING,
                    reason="TRUSTED_TIME_UNKNOWN",
                    continuity_gap=True,
                )
                continue
            if latch is not None:
                self._transition_ticker_accepted_currentness(
                    instrument_name,
                    state=TickerAcceptedCurrentness.SOURCE_STALE.value,
                    reason=latch.reason,
                    boundary=boundary,
                )
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.SOURCE_STALE,
                    reason=latch.reason,
                    continuity_gap=True,
                )
                if previous_state != TickerAcceptedCurrentness.SOURCE_STALE.value:
                    newly_stale.append(instrument_name)
                continue
            if unavailable is not None:
                self._transition_ticker_accepted_currentness(
                    instrument_name,
                    state=TickerAcceptedCurrentness.MISSING.value,
                    reason=unavailable[0],
                    boundary=boundary,
                )
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.MISSING,
                    reason=unavailable[0],
                    continuity_gap=unavailable[1],
                )
                continue
            ticker = self.tickers.get(instrument_name)
            if ticker is None:
                self._transition_ticker_accepted_currentness(
                    instrument_name,
                    state=TickerAcceptedCurrentness.MISSING.value,
                    reason="FORWARD_TICKER_UNKNOWN",
                    boundary=boundary,
                )
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.MISSING,
                    reason="FORWARD_TICKER_UNKNOWN",
                    continuity_gap=False,
                )
                continue
            if ticker.source_timestamp_ms > trusted.upper_ms:
                self._transition_ticker_accepted_currentness(
                    instrument_name,
                    state=TickerAcceptedCurrentness.MISSING.value,
                    reason="TICKER_TIMESTAMP_AHEAD",
                    boundary=boundary,
                )
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.MISSING,
                    reason="TICKER_TIMESTAMP_AHEAD",
                    continuity_gap=False,
                )
                continue
            if (
                trusted.upper_ms
                > ticker.source_timestamp_ms
                + self.policy.runtime_limits.ticker_source_stale_deadline_ms
            ):
                self._latch_ticker_currentness(
                    instrument_name,
                    generation=self._ticker_generation(instrument_name),
                    source_timestamp_ms=ticker.source_timestamp_ms,
                    reason=CausalCause.TICKER_SOURCE_STALE.value,
                )
                self._transition_ticker_accepted_currentness(
                    instrument_name,
                    state=TickerAcceptedCurrentness.SOURCE_STALE.value,
                    reason=CausalCause.TICKER_SOURCE_STALE.value,
                    boundary=boundary,
                )
                settled[instrument_name] = _SettledTickerCurrentness(
                    ticker=None,
                    state=TickerAcceptedCurrentness.SOURCE_STALE,
                    reason=CausalCause.TICKER_SOURCE_STALE.value,
                    continuity_gap=True,
                )
                if previous_state != TickerAcceptedCurrentness.SOURCE_STALE.value:
                    newly_stale.append(instrument_name)
                continue
            self._transition_ticker_accepted_currentness(
                instrument_name,
                state=TickerAcceptedCurrentness.CURRENT.value,
                reason=TickerAcceptedCurrentness.CURRENT.value,
                boundary=boundary,
            )
            settled[instrument_name] = _SettledTickerCurrentness(
                ticker=ticker,
                state=TickerAcceptedCurrentness.CURRENT,
                reason=TickerAcceptedCurrentness.CURRENT.value,
                continuity_gap=False,
            )
        self._settled_ticker_currentness = settled
        return tuple(newly_stale)

    def _current_ticker(
        self,
        instrument_name: str,
    ) -> tuple[TickerState | None, str, bool]:
        settled = self._settled_ticker_currentness.get(instrument_name)
        if settled is None:
            raise RuntimeError("detector current truth requires settled source currentness")
        return settled.ticker, settled.reason, settled.continuity_gap

    def _settle_ticker_boundary(
        self,
        instrument_name: str,
        *,
        boundary: FactBoundary,
        cause: CausalCause,
        countable: bool,
    ) -> None:
        known = instrument_name in self.options
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=cause,
                failure_domain=FailureScope.OPTION,
                affected_scopes=(
                    self._option_local_coverage_scopes((instrument_name,)) if known else ("GLOBAL",)
                ),
            ),
            affected_instruments=((instrument_name,) if known else ()),
            countable=countable,
        )

    def _apply_ticker(
        self,
        instrument_name: str,
        payload: object,
        boundary: FactBoundary,
    ) -> bool:
        if instrument_name not in self.options:
            self._record_ticker_application(
                "SHAPE_REJECTED",
                instrument_name=instrument_name,
                generation=0,
                boundary=boundary,
            )
            self._settle_ticker_boundary(
                instrument_name,
                boundary=boundary,
                cause=CausalCause.TICKER_SHAPE_REJECTED,
                countable=False,
            )
            return False
        slot = self._channels.get(ticker_channel(instrument_name))
        generation = (
            slot.generation
            if slot is not None
            else self._ticker_generations.get(instrument_name, 0)
        )
        try:
            ticker = parse_ticker(payload, instrument_name)
        except ValueError:
            self._record_ticker_application(
                "SHAPE_REJECTED",
                instrument_name=instrument_name,
                generation=generation,
                boundary=boundary,
            )
            self._settle_ticker_boundary(
                instrument_name,
                boundary=boundary,
                cause=CausalCause.TICKER_SHAPE_REJECTED,
                countable=False,
            )
            return False
        candidate_currentness = self._classify_ticker_candidate(ticker, boundary)
        previous = self.tickers.get(instrument_name)
        if previous is not None and ticker.source_timestamp_ms < previous.source_timestamp_ms:
            self._record_ticker_application(
                "LATE_IGNORED",
                instrument_name=instrument_name,
                generation=generation,
                boundary=boundary,
                previous_source_timestamp_ms=previous.source_timestamp_ms,
                candidate_source_timestamp_ms=ticker.source_timestamp_ms,
            )
            self._settle_ticker_boundary(
                instrument_name,
                boundary=boundary,
                cause=CausalCause.TICKER_LATE_IGNORED,
                countable=False,
            )
            return True
        if candidate_currentness == "TIMESTAMP_AHEAD":
            self._record_ticker_application(
                "AHEAD_IGNORED",
                instrument_name=instrument_name,
                generation=generation,
                boundary=boundary,
            )
            self._settle_ticker_boundary(
                instrument_name,
                boundary=boundary,
                cause=CausalCause.TICKER_AHEAD_IGNORED,
                countable=False,
            )
            return True
        latch = self._ticker_currentness_latches.get(instrument_name)
        if latch is not None:
            recovered = (
                generation != latch.generation
                and ticker.source_timestamp_ms > latch.source_timestamp_ms
            )
            if not recovered:
                self._record_ticker_application(
                    "STALE_GENERATION_IGNORED",
                    instrument_name=instrument_name,
                    generation=generation,
                    boundary=boundary,
                )
                self._settle_ticker_boundary(
                    instrument_name,
                    boundary=boundary,
                    cause=CausalCause.TICKER_STALE_GENERATION_IGNORED,
                    countable=False,
                )
                return True
            self._ticker_currentness_latches.pop(instrument_name, None)
        self.tickers[instrument_name] = ticker
        self._ticker_generations[instrument_name] = generation
        self._ticker_unavailable.pop(instrument_name, None)
        self._record_ticker_application(
            "APPLIED",
            instrument_name=instrument_name,
            generation=generation,
            boundary=boundary,
        )
        countable = previous is None or ticker.forward_usdc != previous.forward_usdc
        self._settle_ticker_boundary(
            instrument_name,
            boundary=boundary,
            cause=CausalCause.TICKER_APPLIED,
            countable=countable,
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
                self.option_books[instrument_name] = ContinuousOrderBook(instrument_name)
                self._settle_fact(
                    commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.OPTION_BOOK_GAP,
                        failure_domain=FailureScope.OPTION,
                        affected_scopes=self._option_local_coverage_scopes((instrument_name,)),
                    ),
                    affected_instruments=(instrument_name,),
                    countable=False,
                )
                self._plan_resubscribe(
                    book_channel(instrument_name),
                    boundary,
                    failure_scope=FailureScope.OPTION,
                )
                return False
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=(
                        CausalCause.OPTION_BOOK_CHANGED if changed else CausalCause.OPTION_BOOK_FACT
                    ),
                    failure_domain=FailureScope.OPTION,
                    affected_scopes=self._option_local_coverage_scopes((instrument_name,)),
                ),
                affected_instruments=(instrument_name,),
                countable=changed,
            )
            return True
        if instrument_name not in self.combos:
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.COMBO_BOOK_FACT,
                    failure_domain=FailureScope.COMBO_LAYER,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=(),
                countable=False,
            )
            return False
        combo = self.combos[instrument_name]
        affected = tuple(
            sorted(leg.instrument_name for leg in combo.legs if leg.instrument_name in self.options)
        )
        affected_scopes = self._option_local_coverage_scopes(affected) if affected else ("GLOBAL",)
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
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=(
                    CausalCause.COMBO_BOOK_GAP
                    if not valid
                    else (
                        CausalCause.COMBO_BOOK_CHANGED if changed else CausalCause.COMBO_BOOK_FACT
                    )
                ),
                failure_domain=FailureScope.COMBO_LAYER,
                affected_scopes=affected_scopes,
            ),
            affected_instruments=affected,
            countable=False,
        )
        return valid

    def _settle_combo_boundary(
        self,
        boundary: FactBoundary,
        *,
        cause: CausalCause,
    ) -> None:
        self._settle_fact(
            commit=CausalCommit(
                boundary=boundary,
                cause=cause,
                failure_domain=FailureScope.COMBO_LAYER,
                affected_scopes=("GLOBAL",),
            ),
            affected_instruments=tuple(self.options),
            countable=False,
        )

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
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_CATALOG,
            )
            return complete
        crossed_before_commit = refresh_revision != self._combo_lifecycle_revision
        if crossed_before_commit and not self.combo_catalog.buffering:
            self.combo_catalog.mark_incomplete()
            self._combo_refresh_request_id = None
            self._schedule_combo_refresh(boundary, trailing=True)
            self._next_combo_catalog_recovery_ms = (
                boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_CATALOG,
            )
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
                    self._apply_combo_lifecycle(event, boundary, settle=False)
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
        self._settle_combo_boundary(
            boundary,
            cause=CausalCause.COMBO_CATALOG,
        )
        return complete

    def _apply_combo_lifecycle(
        self,
        payload: object,
        boundary: FactBoundary,
        *,
        settle: bool = True,
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
        if state not in INSTRUMENT_LIFECYCLE_STATES:
            raise SourceDataError("combo lifecycle.state is unsupported")
        if settle:
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_LIFECYCLE,
            )

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
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_METADATA,
            )
            return True
        summary = self._combo_summaries.get(request.scope)
        if summary is None:
            self._combo_metadata_pending.pop(request.scope, None)
            self._complete_combo_catalog_if_ready()
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_METADATA,
            )
            return False
        try:
            combo = parse_combo_instrument(summary, payload)
        except SourceDataError:
            self._combo_metadata_pending.pop(request.scope, None)
            self.combo_catalog.mark_incomplete()
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_METADATA,
            )
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
                self._settle_combo_boundary(
                    boundary,
                    cause=CausalCause.COMBO_METADATA,
                )
                return True
            self.combo_catalog.mark_incomplete()
            self._settle_combo_boundary(
                boundary,
                cause=CausalCause.COMBO_METADATA,
            )
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
        self._settle_combo_boundary(
            boundary,
            cause=CausalCause.COMBO_METADATA,
        )
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
        commit: CausalCommit,
        affected_instruments: tuple[str, ...],
        countable: bool,
    ) -> None:
        self._settle_fact(
            commit=commit,
            affected_instruments=affected_instruments,
            countable=countable,
        )

    def _restart_global_continuity(
        self,
        commit: CausalCommit,
        *,
        effect: CausalEffect | None = None,
        incident: ContinuityIncident | None = None,
    ) -> ContinuityIncident:
        restart_effect = effect or CausalEffect(
            cause=commit.cause,
            failure_domain=commit.failure_domain,
            affected_scopes=commit.affected_scopes,
        )
        if incident is not None:
            if (
                self._active_continuity_incident is None
                or incident.incident_id != self._active_continuity_incident.incident_id
            ):
                raise ValueError("continuity incident is not active")
            return incident
        if self._active_continuity_incident is not None:
            return self._active_continuity_incident
        from_epoch = self._global_continuity_epoch
        incident = ContinuityIncident(
            incident_id=self._next_continuity_incident_id,
            root_commit=commit,
            restart_effect=restart_effect,
            from_epoch=from_epoch,
            to_epoch=from_epoch + 1,
        )
        self._next_continuity_incident_id += 1
        self._active_continuity_incident = incident
        self._global_continuity_epoch += 1
        self._current_continuity_epoch_started_ms = commit.boundary.received_monotonic_ms
        self._current_epoch_joint_evaluation_counts.clear()
        self._current_epoch_joint_evaluation_first_boundaries.clear()
        self._latest_continuity_recovery_boundary = None
        self.diagnostics.global_continuity_restart_count[restart_effect.cause.value] += 1
        self.diagnostics.global_continuity_restart_edges.append(
            {
                "incident_id": incident.incident_id,
                "from_epoch": incident.from_epoch,
                "to_epoch": incident.to_epoch,
                "trigger_cause": commit.cause.value,
                "reason": restart_effect.cause.value,
                "failure_domain": restart_effect.failure_domain.value,
                "affected_scopes": list(restart_effect.affected_scopes),
                "boundary": _fact_boundary_object(commit.boundary),
            }
        )
        self._first_joint_witness_ms = None
        self._first_joint_witness_identity = None
        self._coverage.transition(
            self._coverage._current_state,
            commit=commit,
            causal_effect=restart_effect,
            affected_scopes=restart_effect.affected_scopes,
            blocking_reason=restart_effect.cause.value,
            global_continuity_epoch=self._global_continuity_epoch,
            force=True,
        )
        return incident

    def _recover_continuity_incident(
        self,
        incident: ContinuityIncident,
        *,
        boundary: FactBoundary | None = None,
    ) -> None:
        if (
            self._active_continuity_incident is not None
            and self._active_continuity_incident.incident_id == incident.incident_id
        ):
            recovery_boundary = boundary
            if recovery_boundary is None:
                current = self._current_fact_boundary()
                recovery_boundary = (
                    current
                    if current.received_monotonic_ms
                    >= incident.root_commit.boundary.received_monotonic_ms
                    else incident.root_commit.boundary
                )
            if _fact_boundary_key(recovery_boundary) <= _fact_boundary_key(
                incident.root_commit.boundary
            ):
                raise ValueError("continuity recovery must be strictly later than its incident")
            self.diagnostics.global_continuity_recovery_edges.append(
                {
                    "incident_id": incident.incident_id,
                    "boundary": _fact_boundary_object(recovery_boundary),
                }
            )
            self._active_continuity_incident = None
            self._latest_continuity_recovery_boundary = recovery_boundary
            self._current_epoch_joint_evaluation_counts.clear()
            self._current_epoch_joint_evaluation_first_boundaries.clear()

    def _settle_clock_gap(
        self,
        commit: CausalCommit,
        *,
        effect: CausalEffect | None = None,
    ) -> None:
        boundary = commit.boundary
        active = self._active_continuity_incident
        self._restart_global_continuity(
            commit,
            effect=effect,
            incident=(
                active
                if active is not None
                and active.restart_effect.failure_domain is FailureScope.CLOCK_INDEX
                else None
            ),
        )
        self.aggregate_results.clear()
        for name in self.trackers:
            self._commit_forced_unknown(
                name,
                reason="CLOCK_GAP",
                boundary=boundary,
                continuity_gap=True,
            )
        self._transition_coverage(
            CoverageState.UNKNOWN,
            commit=commit,
            causal_effect=effect,
            blocking_reason=(effect.cause.value if effect is not None else commit.cause.value),
        )

    def _invalidate_clock_index(
        self,
        boundary: FactBoundary,
        *,
        reason: str,
        triggering_commit: CausalCommit | None = None,
    ) -> None:
        if reason != CausalCause.CLOCK_GAP.value:
            raise ValueError("clock/index invalidation requires CLOCK_GAP cause")
        clock_effect = CausalEffect(
            cause=CausalCause.CLOCK_GAP,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        )
        if triggering_commit is None:
            transaction_commit = CausalCommit(
                boundary=boundary,
                cause=CausalCause.CLOCK_GAP,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            )
            transaction_effect = None
        else:
            if triggering_commit.boundary != boundary:
                raise ValueError("clock gap triggering commit boundary does not match")
            transaction_commit = self._freeze_fact_commit(
                triggering_commit,
                (clock_effect,),
            )
            transaction_effect = clock_effect
        self._settle_clock_gap(
            transaction_commit,
            effect=transaction_effect,
        )
        self.clock = None
        self._last_time_currentness_token = None
        self._last_time_currentness_by_instrument.clear()
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

    def _instrument_time_currentness_token(
        self,
        instrument: OptionInstrument,
        trusted: TimeInterval,
    ) -> tuple[object, ...]:
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
        return (
            applicability.classification.value,
            applicability.band.band_id if applicability.band is not None else None,
            tail_identity,
        )

    def _time_currentness_by_instrument(
        self,
        trusted: TimeInterval,
    ) -> dict[str, tuple[object, ...]]:
        return {
            name: self._instrument_time_currentness_token(instrument, trusted)
            for name, instrument in sorted(self.options.items())
        }

    def _time_currentness_token(
        self,
        trusted: TimeInterval,
    ) -> tuple[object, ...]:
        return tuple(self._time_currentness_by_instrument(trusted).items())

    @staticmethod
    def _freeze_fact_commit(
        commit: CausalCommit,
        concurrent_effects: tuple[CausalEffect, ...],
    ) -> CausalCommit:
        effects = tuple(dict.fromkeys((*commit.concurrent_effects, *concurrent_effects)))
        return replace(
            commit,
            concurrent_effects=effects,
        )

    def _settle_fact(
        self,
        *,
        commit: CausalCommit,
        affected_instruments: tuple[str, ...],
        countable: bool,
        acceptance_eligible: bool = True,
        affected_scope_keys: tuple[tuple[int, OptionType], ...] = (),
    ) -> None:
        if self._fact_transaction_active:
            raise RuntimeError("fact lifecycle transaction is not reentrant")
        queue_lag_transition_boundary = self._queue_lag_transition_application == (
            commit.boundary.session_epoch,
            commit.boundary.ingress_seq,
        )
        queue_lag_currentness_active = self._queue_lag_currentness_active
        queue_lag_non_countable = queue_lag_currentness_active or queue_lag_transition_boundary
        self._fact_transaction_active = True
        try:
            self._settle_fact_transaction(
                commit=commit,
                affected_instruments=affected_instruments,
                countable=(countable and not queue_lag_non_countable),
                acceptance_eligible=(acceptance_eligible and not queue_lag_non_countable),
                affected_scope_keys=affected_scope_keys,
                force_full_currentness=queue_lag_transition_boundary,
            )
            self._fact_transaction_revision += 1
            if queue_lag_transition_boundary:
                self._queue_lag_transition_pending = False
        finally:
            self._fact_transaction_active = False

    def _settle_fact_transaction(
        self,
        *,
        commit: CausalCommit,
        affected_instruments: tuple[str, ...],
        countable: bool,
        acceptance_eligible: bool,
        affected_scope_keys: tuple[tuple[int, OptionType], ...],
        force_full_currentness: bool,
    ) -> None:
        boundary = commit.boundary
        newly_stale = self.settle_source_currentness(boundary)
        if commit.cause is not CausalCause.CLEAN_STOP:
            for instrument_name in newly_stale:
                self._request_ticker_resubscribe_once(instrument_name, boundary)
        source_currentness_effect = (
            CausalEffect(
                cause=CausalCause.TICKER_SOURCE_STALE,
                failure_domain=FailureScope.OPTION,
                affected_scopes=self._option_local_coverage_scopes(newly_stale),
            )
            if newly_stale
            else None
        )
        queue_lag_effect = (
            CausalEffect(
                cause=CausalCause.QUEUE_LAG_DEADLINE,
                failure_domain=FailureScope.SESSION,
                affected_scopes=("GLOBAL",),
            )
            if self._queue_lag_currentness_active
            else None
        )
        concurrent_effects = tuple(
            effect
            for effect in (
                source_currentness_effect,
                queue_lag_effect,
            )
            if effect is not None
        )
        if self.clock is None:
            transaction_commit = self._freeze_fact_commit(
                commit,
                concurrent_effects,
            )
            self._update_coverage(
                commit=transaction_commit,
            )
            return
        try:
            trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        except ContinuityGap:
            transaction_commit = self._freeze_fact_commit(
                commit,
                concurrent_effects,
            )
            self._invalidate_clock_index(
                boundary,
                reason="CLOCK_GAP",
                triggering_commit=transaction_commit,
            )
            return

        self.index.seal_ready(trusted.lower_ms)

        directly_affected_names = tuple(
            sorted(
                dict.fromkeys(
                    name for name in (*affected_instruments, *newly_stale) if name in self.options
                )
            )
        )
        countable_names = set(directly_affected_names) if countable else set()
        current_time_tokens = self._time_currentness_by_instrument(trusted)
        time_changed_names = {
            name
            for name, token in current_time_tokens.items()
            if self._last_time_currentness_by_instrument.get(name) != token
        }
        frozen_scope_keys = set(affected_scope_keys)
        frozen_scope_keys.update(
            (
                self.options[name].expiration_timestamp_ms,
                self.options[name].option_type,
            )
            for name in (*directly_affected_names, *time_changed_names)
        )
        if force_full_currentness:
            frozen_scope_keys.update(
                (
                    instrument.expiration_timestamp_ms,
                    instrument.option_type,
                )
                for instrument in self.options.values()
            )
        names = tuple(
            sorted(
                name
                for name, instrument in self.options.items()
                if (
                    instrument.expiration_timestamp_ms,
                    instrument.option_type,
                )
                in frozen_scope_keys
            )
        )
        for scope_key in frozen_scope_keys:
            if not any(
                (
                    instrument.expiration_timestamp_ms,
                    instrument.option_type,
                )
                == scope_key
                for instrument in self.options.values()
            ):
                for aggregate_key in tuple(self.aggregate_results):
                    if aggregate_key[:2] == scope_key:
                        self.aggregate_results.pop(aggregate_key, None)
        prepared: list[ScopeCurrent] = []
        global_gap_reasons: set[str] = set()
        global_gap_scope_labels: set[str] = set()
        global_gap_reason: str | None = None
        global_gap_effect: CausalEffect | None = None
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
                    global_gap_reasons.add(_index_tail_reason(tail.status))
                    global_gap_scope_labels.add(
                        "SCOPE:"
                        f"{instrument.expiration_timestamp_ms}:"
                        f"{instrument.option_type.value}:"
                        f"{applicability.band.band_id}"
                    )
                if tail.status in {
                    IndexTailStatus.SOURCE_STALE,
                    IndexTailStatus.CONTINUITY_GAP,
                }:
                    global_resubscribe = True
                    if tail.status is IndexTailStatus.CONTINUITY_GAP:
                        global_resubscribe_reason = "INDEX_CONTINUITY_GAP"
                    elif global_resubscribe_reason is None:
                        global_resubscribe_reason = "INDEX_SOURCE_STALE"
        if global_gap_reasons:
            global_gap_reason = next(
                reason
                for reason in (
                    "INDEX_CONTINUITY_GAP",
                    "INDEX_SOURCE_STALE",
                    "INDEX_WINDOW_GAP",
                )
                if reason in global_gap_reasons
            )
            gap_affected_scopes = (
                ("GLOBAL",)
                if global_gap_reason
                in {
                    "INDEX_CONTINUITY_GAP",
                    "INDEX_SOURCE_STALE",
                }
                or not global_gap_scope_labels
                or len(global_gap_scope_labels) > 256
                else tuple(sorted(global_gap_scope_labels))
            )
            global_gap_effect = CausalEffect(
                cause=CausalCause(global_gap_reason),
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=gap_affected_scopes,
            )
            transaction_commit = self._freeze_fact_commit(
                commit,
                (*concurrent_effects, global_gap_effect),
            )
            if not self._index_gap_active:
                self.diagnostics.index_gap_count += 1
                self._index_gap_active = True
                active = self._active_continuity_incident
                self._restart_global_continuity(
                    transaction_commit,
                    effect=global_gap_effect,
                    incident=(
                        active
                        if active is not None
                        and active.restart_effect.failure_domain is FailureScope.CLOCK_INDEX
                        else None
                    ),
                )
            names = tuple(sorted(self.options))
            prepared.clear()
        else:
            transaction_commit = self._freeze_fact_commit(
                commit,
                concurrent_effects,
            )
            if set(names) == set(self.options):
                self._index_gap_active = False
                active = self._active_continuity_incident
                if (
                    commit.cause is CausalCause.INDEX_TICK
                    and active is not None
                    and active.restart_effect.failure_domain is FailureScope.CLOCK_INDEX
                ):
                    self._recover_continuity_incident(active, boundary=boundary)
        if global_resubscribe:
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
            tracker = self.trackers.setdefault(
                name,
                EpisodeTracker(
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    instrument_name=name,
                ),
            )
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
            if self._queue_lag_currentness_active:
                current = CurrentEvaluation(
                    disposition=CurrentDisposition.UNKNOWN,
                    reason=CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value,
                    known_evaluation=False,
                    full_formula_evaluation=False,
                    band_id=band_id,
                    continuity_gap=True,
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
            elif not self.platform.usable:
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
            else:
                current_ticker, ticker_reason, ticker_continuity_gap = self._current_ticker(name)
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
            band_scope_key = (
                item.instrument.expiration_timestamp_ms,
                item.instrument.option_type,
                item.current.band_id,
            )
            current_by_scope.setdefault(band_scope_key, []).append(item)
        snapshots = tuple(
            ScopeSnapshot(
                commit=transaction_commit,
                trusted_time=trusted,
                clock_revision=self._clock_revision,
                current=tuple(current),
                boundary_countable=countable,
                acceptance_eligible=acceptance_eligible,
                catalog_complete=self.option_catalog.complete,
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
                    causal_seq=snapshot.commit.boundary.causal_seq,
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
                    observation_reason=(None if eligible else snapshot.commit.cause.value),
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
                value = (
                    instrument,
                    result,
                    item.previous_tracker_state,
                    item.previous_episode_id,
                )
                evaluated.append(value)
                evaluated_by_name[instrument.instrument_name] = value

        settled_snapshots = tuple(
            replace(
                snapshot,
                current=tuple(
                    replace(
                        item,
                        result=evaluated_by_name[item.instrument.instrument_name][1],
                    )
                    for item in snapshot.current
                ),
            )
            for snapshot in snapshots
        )
        for snapshot in settled_snapshots:
            scope_results = [
                (
                    item.instrument,
                    item.result,
                )
                for item in snapshot.current
                if item.result is not None and item.result.band_id is not None
            ]
            if not scope_results:
                continue
            representative = scope_results[0][0]
            scope_truth = self._current_scope_truth(snapshot)
            aggregate = scope_truth.aggregate
            for instrument, result in scope_results:
                if result is None:
                    raise RuntimeError("settled scope snapshot lacks a current result")
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
                if scope_truth.has_current_full_formula:
                    counter.complete_aggregate_with_full_formula_evaluation_count += 1
                    formula_instrument = scope_truth.formula_instrument
                    if formula_instrument is None:
                        raise RuntimeError(
                            "full-formula joint evaluation lacks formula instrument identity"
                        )
                    epoch_scope = (
                        self.policy.identity,
                        formula_instrument.expiration_timestamp_ms,
                        representative.option_type.value,
                        scope_results[0][1].band_id or "",
                        formula_instrument.instrument_name,
                    )
                    self._current_epoch_joint_evaluation_counts[epoch_scope] += 1
                    latest_recovery = self._latest_continuity_recovery_boundary
                    witness_eligible = (
                        self._active_continuity_incident is None
                        and boundary.received_monotonic_ms
                        > self._current_continuity_epoch_started_ms
                        and (
                            latest_recovery is None
                            or _fact_boundary_key(boundary) > _fact_boundary_key(latest_recovery)
                        )
                    )
                    if witness_eligible:
                        self._current_epoch_joint_evaluation_first_boundaries.setdefault(
                            epoch_scope,
                            boundary,
                        )
                    if self._first_joint_witness_ms is None and witness_eligible:
                        self._first_joint_witness_ms = boundary.received_monotonic_ms
                        self._first_joint_witness_identity = _JointWitnessIdentity(
                            boundary=boundary,
                            expiration_timestamp_ms=(formula_instrument.expiration_timestamp_ms),
                            option_type=formula_instrument.option_type,
                            tte_band_id=scope_results[0][1].band_id or "",
                            instrument_name=formula_instrument.instrument_name,
                        )

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

        for instrument, _result, _state, _episode in evaluated:
            tracker = self.trackers[instrument.instrument_name]
            atomic_snapshot = self._freeze_atomic_scope_snapshot(
                tracker,
                commit=transaction_commit,
            )
            if atomic_snapshot is not None:
                self._evaluate_atomic(atomic_snapshot)

        self._sync_combo_subscriptions(boundary)
        self._update_coverage(
            commit=transaction_commit,
        )
        self._last_time_currentness_by_instrument = current_time_tokens
        self._last_time_currentness_token = tuple(current_time_tokens.items())

    def _current_scope_truth(
        self,
        snapshot: ScopeSnapshot,
    ) -> _CurrentScopeTruth:
        if not snapshot.current:
            return _CurrentScopeTruth(
                aggregate=aggregate_detector(
                    (),
                    catalog_complete=snapshot.catalog_complete,
                    has_applicable_scope=False,
                ),
                has_current_full_formula=False,
                formula_instrument=None,
            )
        first = snapshot.current[0]
        instrument = first.instrument
        band_id = first.result.band_id if first.result is not None else first.current.band_id
        if band_id is None:
            return _CurrentScopeTruth(
                aggregate=aggregate_detector(
                    (),
                    catalog_complete=snapshot.catalog_complete,
                    has_applicable_scope=False,
                ),
                has_current_full_formula=False,
                formula_instrument=None,
            )
        for item in snapshot.current:
            if (
                item.instrument.expiration_timestamp_ms != instrument.expiration_timestamp_ms
                or item.instrument.option_type is not instrument.option_type
                or item.result is None
                or item.result.band_id != band_id
            ):
                raise RuntimeError("scope snapshot contains cross-scope or unsettled current truth")
        states = tuple(
            item.result.detector_state for item in snapshot.current if item.result is not None
        )
        counter = self._scope_counter(
            instrument.option_type,
            band_id,
        )
        counter.applicable_instrument_count = max(
            counter.applicable_instrument_count,
            len(snapshot.current),
        )
        aggregate = aggregate_detector(
            states,
            catalog_complete=snapshot.catalog_complete,
            has_applicable_scope=True,
        )
        self.aggregate_results[
            (
                instrument.expiration_timestamp_ms,
                instrument.option_type,
                band_id,
            )
        ] = aggregate
        formula_instrument = next(
            (
                item.instrument
                for item in snapshot.current
                if item.result is not None and item.result.full_formula_evaluation
            ),
            None,
        )
        return _CurrentScopeTruth(
            aggregate=aggregate,
            has_current_full_formula=formula_instrument is not None,
            formula_instrument=formula_instrument,
        )

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

    def _transition_coverage(
        self,
        state: CoverageState,
        *,
        commit: CausalCommit,
        causal_effect: CausalEffect | None = None,
        affected_scopes: tuple[str, ...] | None = None,
        blocking_reason: str,
        force: bool = False,
    ) -> None:
        self._coverage.transition(
            state,
            commit=commit,
            causal_effect=causal_effect,
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
            global_continuity_epoch=self._global_continuity_epoch,
            force=force,
        )

    def _coverage_affected_scopes(self, names: tuple[str, ...]) -> tuple[str, ...]:
        if not names or set(names) == set(self.options):
            return ("GLOBAL",)
        return self._option_local_coverage_scopes(names)

    @staticmethod
    def _option_local_coverage_scopes(names: tuple[str, ...]) -> tuple[str, ...]:
        scopes = tuple(sorted(f"OPTION:{name}" for name in names))
        return scopes if len(scopes) <= 256 else ("OPTION_LOCAL",)

    def _option_lifecycle_affected_scopes(
        self,
        instrument_name: str,
        instrument: OptionInstrument | None,
        boundary: FactBoundary,
    ) -> tuple[str, ...]:
        option_scope = f"OPTION:{instrument_name}"
        if instrument is None or self.clock is None:
            return (option_scope,)
        try:
            trusted = self.clock.interval_at(boundary.received_monotonic_ms)
        except ContinuityGap:
            return (option_scope,)
        applicability = classify_time_applicability(
            self.policy,
            expiration_timestamp_ms=instrument.expiration_timestamp_ms,
            trusted_time=trusted,
            option_type=instrument.option_type,
        )
        if applicability.band is None:
            return (option_scope,)
        return tuple(
            sorted(
                (
                    option_scope,
                    "SCOPE:"
                    f"{instrument.expiration_timestamp_ms}:"
                    f"{instrument.option_type.value}:"
                    f"{applicability.band.band_id}",
                )
            )
        )

    def _scope_counter(self, option_type: OptionType, band_id: str) -> ScopeCounts:
        key = (self.policy.identity, option_type, band_id)
        if key not in self._scope_counts:
            self._scope_counts[key] = ScopeCounts(
                self.policy.identity,
                option_type.value,
                band_id,
            )
        return self._scope_counts[key]

    def _freeze_atomic_scope_snapshot(
        self,
        tracker: EpisodeTracker,
        *,
        commit: CausalCommit,
    ) -> AtomicScopeSnapshot | None:
        episode_identity = tracker.episode_id
        anomaly_activation_seq = tracker.activation_causal_seq
        activation_band_id = tracker.activation_band_id
        short_leg = self.options.get(tracker.instrument_name)
        if (
            episode_identity is None
            or anomaly_activation_seq is None
            or activation_band_id is None
            or short_leg is None
        ):
            return None
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
        frozen_books = tuple(
            AtomicBookSnapshot(
                instrument_name=name,
                state=book.state,
                reason=book.reason,
                change_id=book.change_id,
                economic_revision=book.economic_revision,
                source_timestamp_ms=book.source_timestamp_ms,
                last_mutation_monotonic_ms=book.last_mutation_monotonic_ms,
                bids=tuple(
                    PriceLevel(price, amount)
                    for price, amount in sorted(book.bids.items(), reverse=True)
                ),
                asks=tuple(
                    PriceLevel(price, amount) for price, amount in sorted(book.asks.items())
                ),
            )
            for name, book in sorted(self.combo_books.items())
        )
        frozen_book_values: dict[str, ContinuousOrderBook] = {}
        for frozen in frozen_books:
            book = ContinuousOrderBook(frozen.instrument_name)
            book.state = frozen.state
            book.reason = frozen.reason
            book.change_id = frozen.change_id
            book.economic_revision = frozen.economic_revision
            book.source_timestamp_ms = frozen.source_timestamp_ms
            book.last_mutation_monotonic_ms = frozen.last_mutation_monotonic_ms
            book.bids = {level.price: level.amount for level in frozen.bids}
            book.asks = {level.price: level.amount for level in frozen.asks}
            frozen_book_values[frozen.instrument_name] = book
        frozen_options = tuple(
            sorted(current_options.values(), key=lambda value: value.instrument_name)
        )
        frozen_combos = tuple(sorted(self.combos.values(), key=lambda value: value.instrument_name))
        result = classify_atomic_quotes(
            anomaly_active=tracker.detector_state is DetectorState.ANOMALY_ACTIVE,
            combo_catalog_complete=self.combo_catalog.complete,
            option_catalog_complete=(
                self.option_catalog.complete
                and self._option_positive_scope_safe
                and not unresolved_protective_lifecycle
            ),
            short_leg=short_leg,
            options_by_name={option.instrument_name: option for option in frozen_options},
            combos=frozen_combos,
            combo_books=frozen_book_values,
            target_btc=self.policy.target_base_quantity_btc,
        )
        current_result = self.results.get(tracker.instrument_name)
        return AtomicScopeSnapshot(
            commit=commit,
            episode_identity=episode_identity,
            anomaly_activation_seq=anomaly_activation_seq,
            activation_band_id=activation_band_id,
            detector_state=tracker.detector_state,
            detector_causal_seq=commit.boundary.causal_seq,
            short_leg=short_leg,
            short_current=(
                current_result.current_evaluation if current_result is not None else None
            ),
            option_catalog_complete=(
                self.option_catalog.complete
                and self._option_positive_scope_safe
                and not unresolved_protective_lifecycle
            ),
            combo_catalog_complete=self.combo_catalog.complete,
            current_options=frozen_options,
            combos=frozen_combos,
            combo_books=frozen_books,
            result=result,
        )

    def _evaluate_atomic(self, snapshot: AtomicScopeSnapshot) -> None:
        result = snapshot.result
        previous = self.atomic_states.get(snapshot.episode_identity)
        if previous is not result.state:
            self.atomic_states[snapshot.episode_identity] = result.state
            self._atomic_transition_counts[result.state.value] += 1
            counter = self._scope_counter(
                snapshot.short_leg.option_type,
                snapshot.activation_band_id,
            )
            counter.public_atomic_quote_state_transition_count[result.state.value] += 1
        if result.state is not PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE:
            return
        combos = {combo.instrument_name: combo for combo in snapshot.combos}
        books = {book.instrument_name: book for book in snapshot.combo_books}
        for quote in result.quotes:
            combo_name = quote.match.combo_instrument_name
            emitted_key = (snapshot.episode_identity, combo_name)
            if emitted_key in self._emitted_atomic_quotes:
                continue
            combo = combos[combo_name]
            book = books[combo_name]
            if book.source_timestamp_ms is None:
                raise RuntimeError("available atomic quote lacks causal source identity")
            validate_atomic_causal_invariant(
                anomaly_activation_seq=snapshot.anomaly_activation_seq,
                detector_causal_seq=snapshot.detector_causal_seq,
                quote_causal_seq=snapshot.commit.boundary.causal_seq,
            )
            event = project_atomic_event(
                AtomicEvidence(
                    code_identity=self.code_identity,
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    episode_identity=snapshot.episode_identity,
                    detector_causal_seq=snapshot.detector_causal_seq,
                    quote_causal_seq=snapshot.commit.boundary.causal_seq,
                    short_instrument_name=snapshot.short_leg.instrument_name,
                    combo_legs=(
                        (combo.legs[0].instrument_name, combo.legs[0].amount),
                        (combo.legs[1].instrument_name, combo.legs[1].amount),
                    ),
                    quote=quote,
                    target_base_quantity_btc=self.policy.target_base_quantity_btc,
                    source_timestamp_ms=book.source_timestamp_ms,
                    anomaly_activation_seq=snapshot.anomaly_activation_seq,
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

    def _update_coverage(
        self,
        *,
        commit: CausalCommit,
    ) -> None:
        monotonic_ms = commit.boundary.received_monotonic_ms
        self._update_band_suspension(monotonic_ms)
        if self._queue_lag_currentness_active:
            self.aggregate_results.clear()
            self._transition_coverage(
                CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value,
            )
            return
        if self.clock is None:
            self.aggregate_results.clear()
            positive = any(
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                for tracker in self.trackers.values()
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=(
                    CoverageBlockingReason.ACTIVE_POSITIVE_SCOPE_INCOMPLETE.value
                    if positive
                    else (
                        CoverageBlockingReason.CLOCK_GAP.value
                        if commit.cause is CausalCause.CLOCK_GAP
                        else CoverageBlockingReason.CLOCK_UNAVAILABLE.value
                    )
                ),
            )
            return
        try:
            trusted = self.clock.interval_at(monotonic_ms)
        except ContinuityGap:
            self.aggregate_results.clear()
            self._transition_coverage(
                CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=CoverageBlockingReason.CLOCK_GAP.value,
            )
            return
        if not self.platform.usable or not self.option_catalog.complete:
            positive = any(
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                for tracker in self.trackers.values()
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=(
                    CoverageBlockingReason.ACTIVE_POSITIVE_SCOPE_INCOMPLETE.value
                    if positive
                    else (
                        self._bounded_coverage_blocking_reason(self.platform.reason)
                        if not self.platform.usable
                        else CoverageBlockingReason.OPTION_CATALOG_INCOMPLETE.value
                    )
                ),
            )
            return
        scoped_keys: set[tuple[int, OptionType, str]] = set()
        unresolved_names: list[str] = []
        unresolved = False
        for instrument in self.options.values():
            applicability = classify_time_applicability(
                self.policy,
                expiration_timestamp_ms=instrument.expiration_timestamp_ms,
                trusted_time=trusted,
                option_type=instrument.option_type,
            )
            if (
                applicability.classification is TimeApplicability.IN_BAND
                and applicability.band is not None
            ):
                scoped_keys.add(
                    (
                        instrument.expiration_timestamp_ms,
                        instrument.option_type,
                        applicability.band.band_id,
                    )
                )
            elif applicability.classification in {
                TimeApplicability.ADJACENT_BAND_BOUNDARY,
                TimeApplicability.MONITOR_BOUNDARY,
            }:
                unresolved = True
                unresolved_names.append(instrument.instrument_name)
        if not scoped_keys:
            self._transition_coverage(
                CoverageState.UNKNOWN if unresolved else CoverageState.NO_APPLICABLE_SCOPE,
                commit=commit,
                affected_scopes=(
                    self._option_local_coverage_scopes(tuple(unresolved_names))
                    if unresolved_names
                    else ("GLOBAL",)
                ),
                blocking_reason=(
                    CoverageBlockingReason.TIME_APPLICABILITY_UNRESOLVED.value
                    if unresolved
                    else CoverageBlockingReason.NO_APPLICABLE_SCOPE.value
                ),
            )
            return
        aggregates = tuple(
            self.aggregate_results.get(key)
            for key in sorted(
                scoped_keys,
                key=lambda item: (item[0], item[1].value, item[2]),
            )
        )
        if not unresolved and all(
            aggregate is not None and aggregate.coverage is DetectorCoverage.COMPLETE
            for aggregate in aggregates
        ):
            state = CoverageState.KNOWN_COMPLETE
        elif any(
            aggregate is not None and aggregate.state is DetectorState.ANOMALY_ACTIVE
            for aggregate in aggregates
        ):
            state = CoverageState.KNOWN_DEGRADED
        else:
            state = CoverageState.UNKNOWN
        scope_blocking_reason, scope_blocker_scopes = self._current_scope_blocker(scoped_keys)
        blocking_reason = (
            CoverageBlockingReason.NONE.value
            if state is CoverageState.KNOWN_COMPLETE
            else (
                CoverageBlockingReason.ACTIVE_POSITIVE_SCOPE_INCOMPLETE.value
                if state is CoverageState.KNOWN_DEGRADED
                else (
                    CoverageBlockingReason.TIME_APPLICABILITY_UNRESOLVED.value
                    if unresolved
                    else scope_blocking_reason
                )
            )
        )
        affected_scopes = (
            self._coverage_scope_labels(scoped_keys)
            if state is CoverageState.KNOWN_COMPLETE
            else (
                self._option_local_coverage_scopes(tuple(unresolved_names))
                if unresolved_names
                else scope_blocker_scopes
            )
        )
        self._transition_coverage(
            state,
            commit=commit,
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
        )

    @staticmethod
    def _bounded_coverage_blocking_reason(reason: str) -> str:
        if reason == CausalCause.QUEUE_LAG_DEADLINE.value:
            return CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value
        try:
            return CoverageBlockingReason(reason).value
        except ValueError:
            if reason.startswith(("OPTION_LIFECYCLE_", "OPTION_METADATA_", "OPTION_SNAPSHOT_")):
                return CoverageBlockingReason.OPTION_LIFECYCLE_UNAVAILABLE.value
            if "BOOK" in reason:
                return CoverageBlockingReason.OPTION_BOOK_UNAVAILABLE.value
            return CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value

    @staticmethod
    def _coverage_scope_labels(
        scoped_keys: set[tuple[int, OptionType, str]],
    ) -> tuple[str, ...]:
        labels = tuple(
            sorted(
                f"SCOPE:{expiry}:{option_type.value}:{band_id}"
                for expiry, option_type, band_id in scoped_keys
            )
        )
        return labels if labels and len(labels) <= 256 else ("GLOBAL",)

    def _current_scope_blocker(
        self,
        scoped_keys: set[tuple[int, OptionType, str]],
    ) -> tuple[str, tuple[str, ...]]:
        candidates = tuple(
            (name, result.reason, self._bounded_coverage_blocking_reason(result.reason))
            for name, result in self.results.items()
            if result.reason is not None
            and not result.known_evaluation
            and name in self.options
            and (
                self.options[name].expiration_timestamp_ms,
                self.options[name].option_type,
                result.band_id,
            )
            in scoped_keys
        )
        selected = CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value
        for reason in sorted({reason for _, reason, _ in candidates}):
            bounded = self._bounded_coverage_blocking_reason(reason)
            if bounded != CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value:
                selected = bounded
                break
        selected_names = tuple(
            sorted(name for name, _, bounded in candidates if bounded == selected)
        )
        global_blockers = {
            CoverageBlockingReason.CLOCK_GAP.value,
            CoverageBlockingReason.SESSION_GAP.value,
            CoverageBlockingReason.REMOTE_CONNECTION_CLOSED.value,
            CoverageBlockingReason.TRANSPORT_READ_FAILURE.value,
            CoverageBlockingReason.SESSION_LIVENESS_DEADLINE.value,
            CoverageBlockingReason.SESSION_RPC_FAILURE.value,
            CoverageBlockingReason.RUNTIME_SESSION_FAILURE.value,
            CoverageBlockingReason.PROTOCOL_INCOMPATIBILITY.value,
            CoverageBlockingReason.INGRESS_GAP_OR_DUPLICATE.value,
            CoverageBlockingReason.QUEUE_OVERFLOW.value,
            CoverageBlockingReason.PLATFORM_UNESTABLISHED.value,
            CoverageBlockingReason.POST_STATUS_BOOTSTRAP_REQUIRED.value,
            CoverageBlockingReason.PLATFORM_MAINTENANCE.value,
            CoverageBlockingReason.PUBLIC_METHODS_DENIED.value,
            CoverageBlockingReason.RELEVANT_PLATFORM_LOCK.value,
            CoverageBlockingReason.OPTION_CATALOG_INCOMPLETE.value,
            CoverageBlockingReason.INDEX_SOURCE_STALE.value,
            CoverageBlockingReason.INDEX_CONTINUITY_GAP.value,
            CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value,
        }
        if selected in global_blockers:
            return selected, ("GLOBAL",)
        if selected == CoverageBlockingReason.INDEX_WINDOW_GAP.value:
            matching_scopes = {
                (
                    self.options[name].expiration_timestamp_ms,
                    self.options[name].option_type,
                    self.results[name].band_id,
                )
                for name in selected_names
                if self.results[name].band_id is not None
            }
            return selected, self._coverage_scope_labels(
                {
                    (expiry, option_type, cast(str, band_id))
                    for expiry, option_type, band_id in matching_scopes
                }
            )
        option_local_blockers = {
            CoverageBlockingReason.TICKER_SOURCE_STALE.value,
            CoverageBlockingReason.TICKER_TIMESTAMP_AHEAD.value,
            CoverageBlockingReason.OPTION_LIFECYCLE_UNAVAILABLE.value,
            CoverageBlockingReason.OPTION_BOOK_UNAVAILABLE.value,
        }
        if selected in option_local_blockers and selected_names:
            return selected, self._option_local_coverage_scopes(selected_names)
        return selected, self._coverage_scope_labels(scoped_keys)

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

    def _retire_current_epoch(
        self,
        reason: str = CausalCause.SESSION_GAP.value,
        *,
        monotonic_ms: int | None = None,
    ) -> None:
        if self._session_epoch is None or self._session_epoch in self._retired_epochs:
            return
        retired_ms = (
            self._last_boundary_monotonic_ms
            if monotonic_ms is None
            else max(self._last_boundary_monotonic_ms, monotonic_ms)
        )
        self._queue_lag_currentness_active = False
        self._queue_lag_transition_pending = False
        self._queue_lag_transition_application = None
        self._last_boundary_monotonic_ms = retired_ms
        self.diagnostics.session_gap_count += 1
        boundary = FactBoundary(
            self._session_epoch,
            self._last_ingress_seq,
            retired_ms,
            self._causal_seq,
        )
        commit = CausalCommit(
            boundary=boundary,
            cause=CausalCause(reason),
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        )
        self._restart_global_continuity(commit)
        self._close_all_option_local_unavailable(
            retired_ms,
            end_disposition="REASON_CHANGED",
        )
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
        if self._early_rpc_responses:
            self.diagnostics.late_response_count += len(self._early_rpc_responses)
            self.diagnostics.rpc_orphan_late_wire_count += len(self._early_rpc_responses)
            self._early_rpc_responses.clear()
        for request in tuple(self.pending_rpcs.values()):
            self._finish_rpc(
                request,
                state=RpcState.RETIRED,
                terminal_monotonic_ms=retired_ms,
                record_latency=False,
            )
        self.pending_rpcs.clear()
        self._update_band_suspension(retired_ms)
        self._transition_coverage(
            CoverageState.UNKNOWN,
            commit=commit,
            blocking_reason=commit.cause.value,
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
                self.diagnostics.transport_enqueued_envelope_count = max(
                    self.diagnostics.transport_enqueued_envelope_count,
                    enqueued,
                )
            else:
                self._transport_enqueued_by_epoch[session_epoch] = max(
                    self._transport_enqueued_by_epoch.get(session_epoch, 0),
                    enqueued,
                )
                self.diagnostics.transport_enqueued_envelope_count = sum(
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
        consumed_keys = SOURCE_CONSUMED_FIELD_TYPES[source]
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
            monotonic_ms - self._last_wire_received_ms
            > self.policy.runtime_limits.session_liveness_deadline_ms
        ):
            self._last_boundary_monotonic_ms = max(
                self._last_boundary_monotonic_ms,
                monotonic_ms,
            )
            self._retire_current_epoch(CausalCause.SESSION_LIVENESS_DEADLINE.value)
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
            if (
                (
                    (lifecycle := self._rpc_lifecycles[request.request_id]).state
                    is RpcState.SCHEDULED
                    and monotonic_ms > request.send_deadline_monotonic_ms
                )
                or (
                    lifecycle.state is RpcState.SENT
                    and lifecycle.response_deadline_monotonic_ms is not None
                    and monotonic_ms > lifecycle.response_deadline_monotonic_ms
                )
            )
        )
        for request in expired:
            self.pending_rpcs.pop(request.request_id, None)
            lifecycle = self._rpc_lifecycles[request.request_id]
            held_response = self._early_rpc_responses.pop(request.request_id, None)
            if held_response is not None:
                self.diagnostics.late_response_count += 1
                self.diagnostics.rpc_orphan_late_wire_count += 1
            self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=monotonic_ms,
                record_latency=False,
                allow_unsent=(lifecycle.state is RpcState.SCHEDULED),
            )
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
                self._invalidate_clock_index(
                    boundary,
                    reason="CLOCK_GAP",
                    triggering_commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.TIME_BOUNDARY,
                        failure_domain=FailureScope.CLOCK_INDEX,
                        affected_scopes=("GLOBAL",),
                    ),
                )
            else:
                self.index.seal_ready(trusted.lower_ms)
                self._sync_membership(boundary)
                token = self._time_currentness_token(trusted)
                self._settle_fact(
                    commit=CausalCommit(
                        boundary=boundary,
                        cause=CausalCause.TIME_BOUNDARY,
                        failure_domain=FailureScope.CLOCK_INDEX,
                        affected_scopes=("GLOBAL",),
                    ),
                    affected_instruments=tuple(self.options),
                    countable=False,
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
        try:
            cause = CausalCause(reason)
        except ValueError:
            cause = CausalCause.RUNTIME_SESSION_FAILURE
        if cause is CausalCause.QUEUE_LAG_DEADLINE:
            raise ValueError("ordered queue lag is a currentness incident, not a reconnect cause")
        session_causes = {
            CausalCause.SESSION_GAP,
            CausalCause.REMOTE_CONNECTION_CLOSED,
            CausalCause.TRANSPORT_READ_FAILURE,
            CausalCause.SESSION_LIVENESS_DEADLINE,
            CausalCause.SESSION_RPC_FAILURE,
            CausalCause.RUNTIME_SESSION_FAILURE,
            CausalCause.PROTOCOL_INCOMPATIBILITY,
            CausalCause.INGRESS_GAP_OR_DUPLICATE,
            CausalCause.QUEUE_OVERFLOW,
            CausalCause.PLATFORM_MAINTENANCE,
            CausalCause.PUBLIC_METHODS_DENIED,
            CausalCause.RELEVANT_PLATFORM_LOCK,
        }
        if cause not in session_causes:
            cause = CausalCause.RUNTIME_SESSION_FAILURE
        self._retire_current_epoch(cause.value)

    def clean_stop(self, monotonic_ms: int) -> Path:
        self.begin_clean_stop()
        self._last_boundary_monotonic_ms = max(
            self._last_boundary_monotonic_ms,
            monotonic_ms,
        )
        self._causal_seq += 1
        boundary = FactBoundary(
            self._session_epoch or 1,
            self._last_ingress_seq,
            monotonic_ms,
            self._causal_seq,
        )
        clean_commit = CausalCommit(
            boundary=boundary,
            cause=CausalCause.CLEAN_STOP,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        )
        self._settle_fact(
            commit=clean_commit,
            affected_instruments=tuple(self.options),
            countable=False,
            acceptance_eligible=False,
        )
        for tracker in self.trackers.values():
            transition = tracker.stop(causal_seq=self._causal_seq)
            self._record_episode_end(transition.ended_episode, monotonic_ms)
        self._close_all_option_local_unavailable(
            monotonic_ms,
            end_disposition="CENSORED_AT_STOP",
        )
        if self._early_rpc_responses:
            self.diagnostics.late_response_count += len(self._early_rpc_responses)
            self.diagnostics.rpc_orphan_late_wire_count += len(self._early_rpc_responses)
            self._early_rpc_responses.clear()
        for request in tuple(self.pending_rpcs.values()):
            self._finish_rpc(
                request,
                state=RpcState.CENSORED,
                terminal_monotonic_ms=monotonic_ms,
                record_latency=False,
            )
        self.pending_rpcs.clear()
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
                    "consumed_fields": _summarize_source_fields(
                        self.diagnostics.source_consumed_fields.get(source, set())
                    ),
                }
            )
        post_witness = (
            None
            if self._first_joint_witness_ms is None
            else max(0, self._last_boundary_monotonic_ms - self._first_joint_witness_ms)
        )
        self._compact_option_local_intervals(self._last_boundary_monotonic_ms)
        option_local_intervals = list(self.diagnostics.option_local_intervals)
        outside_option_local_intervals = self.diagnostics.option_local_outside_window_interval_count
        outside_option_local_latest_end = (
            self.diagnostics.option_local_outside_window_latest_end_monotonic_ms
        )
        outside_option_local_by_reason = Counter(
            self.diagnostics.option_local_outside_window_interval_count_by_reason
        )
        omitted_option_local_intervals = self.diagnostics.omitted_option_local_interval_count
        option_local_end_counts = Counter(self.diagnostics.option_local_end_count)
        omitted_option_local_by_reason = Counter(
            self.diagnostics.omitted_option_local_interval_count_by_reason
        )
        for unavailable in sorted(
            self._option_local_unavailable.values(),
            key=lambda item: (item.start_monotonic_ms, item.instrument_name),
        ):
            row = {
                "instrument_name": unavailable.instrument_name,
                "generation": unavailable.generation,
                "reason": unavailable.reason,
                "start_monotonic_ms": unavailable.start_monotonic_ms,
                "end_monotonic_ms": self._last_boundary_monotonic_ms,
                "duration_ms": max(
                    0,
                    self._last_boundary_monotonic_ms - unavailable.start_monotonic_ms,
                ),
                "end_disposition": "CENSORED_AT_STOP",
                "global_continuity_epoch": unavailable.global_continuity_epoch,
            }
            if len(option_local_intervals) < OPTION_LOCAL_RETAINED_INTERVAL_LIMIT:
                option_local_intervals.append(row)
            else:
                omitted_option_local_intervals += 1
                omitted_option_local_by_reason[(unavailable.reason, "CENSORED_AT_STOP")] += 1
            option_local_end_counts["CENSORED_AT_STOP"] += 1

        def interval_count_rows(
            counts: Counter[tuple[str, str]],
        ) -> dict[str, dict[str, int]]:
            rows: dict[str, dict[str, int]] = {}
            for reason, _disposition in sorted(counts):
                rows[reason] = {
                    disposition: counts[(reason, disposition)]
                    for disposition in ("RECOVERED", "REASON_CHANGED", "CENSORED_AT_STOP")
                }
            return rows

        outside_reason_rows = interval_count_rows(outside_option_local_by_reason)
        omitted_reason_rows = interval_count_rows(omitted_option_local_by_reason)
        witness_identity = self._first_joint_witness_identity
        return {
            "operational_diagnostics_schema_version": 4,
            "runtime_limits": self.policy.runtime_limits.as_object(),
            "ingress": {
                "received_envelope_count": max(
                    self.diagnostics.received_envelope_count,
                    self.diagnostics.transport_enqueued_envelope_count,
                ),
                "reduced_envelope_count": self.diagnostics.reduced_envelope_count,
                "ingress_gap_or_duplicate_count": (self.diagnostics.ingress_gap_or_duplicate_count),
                "queue_high_water_frames": self.diagnostics.queue_high_water_frames,
                "max_receive_to_reduce_lag_ms": (self.diagnostics.max_receive_to_reduce_lag_ms),
                "overflow_count": self.diagnostics.overflow_count,
                "send_control_event_count": self.diagnostics.send_control_event_count,
                "connection_error_event_count": self.diagnostics.connection_error_event_count,
            },
            "rpc_by_method": [
                {
                    "method": method,
                    "scheduled_count": self.diagnostics.rpc_request_count[method],
                    "sent_count": self.diagnostics.rpc_sent_count[method],
                    "success_count": self.diagnostics.rpc_success_count[method],
                    "error_count": self.diagnostics.rpc_error_count[method],
                    "deadline_late_count": (self.diagnostics.rpc_deadline_late_count[method]),
                    "retired_count": self.diagnostics.rpc_retired_count[method],
                    "censored_count": self.diagnostics.rpc_censored_count[method],
                    "pre_send_error_count": self.diagnostics.rpc_pre_send_terminal_count[
                        (method, RpcState.ERROR.value)
                    ],
                    "pre_send_deadline_late_count": (
                        self.diagnostics.rpc_pre_send_terminal_count[
                            (method, RpcState.DEADLINE_LATE.value)
                        ]
                    ),
                    "pre_send_retired_count": self.diagnostics.rpc_pre_send_terminal_count[
                        (method, RpcState.RETIRED.value)
                    ],
                    "pre_send_censored_count": self.diagnostics.rpc_pre_send_terminal_count[
                        (method, RpcState.CENSORED.value)
                    ],
                    "post_send_success_count": self.diagnostics.rpc_post_send_terminal_count[
                        (method, RpcState.SUCCESS.value)
                    ],
                    "post_send_error_count": self.diagnostics.rpc_post_send_terminal_count[
                        (method, RpcState.ERROR.value)
                    ],
                    "post_send_deadline_late_count": (
                        self.diagnostics.rpc_post_send_terminal_count[
                            (method, RpcState.DEADLINE_LATE.value)
                        ]
                    ),
                    "post_send_retired_count": self.diagnostics.rpc_post_send_terminal_count[
                        (method, RpcState.RETIRED.value)
                    ],
                    "post_send_censored_count": self.diagnostics.rpc_post_send_terminal_count[
                        (method, RpcState.CENSORED.value)
                    ],
                    "rate_limit_count": self.diagnostics.rpc_rate_limit_count[method],
                    "latency_observation_count": self.diagnostics.rpc_latency_count[method],
                    "latency_ms_sum": self.diagnostics.rpc_latency_sum[method],
                    "latency_ms_max": self.diagnostics.rpc_latency_max[method],
                }
                for method in methods
            ],
            "rpc_orphan_late_wire_count": self.diagnostics.rpc_orphan_late_wire_count,
            "transport_terminal_attribution": [
                {
                    "close_code": close_code,
                    "close_disposition": close_disposition,
                    "exception_class": exception_class,
                    "count": count,
                }
                for (
                    close_code,
                    close_disposition,
                    exception_class,
                ), count in sorted(self.diagnostics.transport_terminal_attribution_count.items())
                if count > 0
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
            "global_continuity": {
                "current_epoch": self._global_continuity_epoch,
                "restart_count": sum(self.diagnostics.global_continuity_restart_count.values()),
                "restart_count_by_reason": dict(
                    sorted(self.diagnostics.global_continuity_restart_count.items())
                ),
                "restart_edges": list(self.diagnostics.global_continuity_restart_edges),
                "recovery_edges": list(self.diagnostics.global_continuity_recovery_edges),
                "current_epoch_joint_evaluation_count_by_scope": [
                    {
                        "policy_identity": policy_identity,
                        "expiration_timestamp_ms": expiration_timestamp_ms,
                        "option_type": option_type,
                        "tte_band_id": band_id,
                        "formula_instrument_name": formula_instrument_name,
                        "count": count,
                        "first_joint_evaluation_boundary": (
                            _fact_boundary_object(
                                self._current_epoch_joint_evaluation_first_boundaries[
                                    (
                                        policy_identity,
                                        expiration_timestamp_ms,
                                        option_type,
                                        band_id,
                                        formula_instrument_name,
                                    )
                                ]
                            )
                            if (
                                policy_identity,
                                expiration_timestamp_ms,
                                option_type,
                                band_id,
                                formula_instrument_name,
                            )
                            in self._current_epoch_joint_evaluation_first_boundaries
                            else None
                        ),
                    }
                    for (
                        policy_identity,
                        expiration_timestamp_ms,
                        option_type,
                        band_id,
                        formula_instrument_name,
                    ), count in sorted(self._current_epoch_joint_evaluation_counts.items())
                    if count > 0
                ],
            },
            "ticker_application": {
                "disposition_count": {
                    disposition: self.diagnostics.ticker_application_count[disposition]
                    for disposition in (
                        "APPLIED",
                        "LATE_IGNORED",
                        "AHEAD_IGNORED",
                        "STALE_GENERATION_IGNORED",
                        "SHAPE_REJECTED",
                    )
                },
                "late_ignored_diagnostic_limit": 256,
                "omitted_late_ignored_diagnostic_count": (
                    self.diagnostics.omitted_late_ticker_diagnostic_count
                ),
                "late_ignored_diagnostics": list(self.diagnostics.late_ticker_diagnostics),
            },
            "ticker_currentness": {
                "candidate_count_by_classification": {
                    classification: (
                        self.diagnostics.ticker_candidate_currentness_count[classification]
                    )
                    for classification in (
                        "CURRENT",
                        "SOURCE_STALE",
                        "TIMESTAMP_AHEAD",
                        "TRUSTED_TIME_UNKNOWN",
                    )
                },
                "accepted_transition_count_by_state": {
                    state: (self.diagnostics.ticker_accepted_currentness_transition_count[state])
                    for state in ("MISSING", "CURRENT", "SOURCE_STALE")
                },
            },
            "option_local_availability": {
                "unavailable_count_by_reason": dict(
                    sorted(self.diagnostics.option_local_unavailable_count.items())
                ),
                "recovery_count_by_reason": dict(
                    sorted(self.diagnostics.option_local_recovery_count.items())
                ),
                "end_count_by_disposition": {
                    disposition: option_local_end_counts[disposition]
                    for disposition in (
                        "RECOVERED",
                        "REASON_CHANGED",
                        "CENSORED_AT_STOP",
                    )
                },
                "acceptance_window_ms": OPTION_LOCAL_ACCEPTANCE_WINDOW_MS,
                "retained_interval_limit": OPTION_LOCAL_RETAINED_INTERVAL_LIMIT,
                "outside_window_interval_count": outside_option_local_intervals,
                "outside_window_latest_end_monotonic_ms": outside_option_local_latest_end,
                "outside_window_interval_count_by_reason": outside_reason_rows,
                "omitted_interval_count": omitted_option_local_intervals,
                "omitted_interval_count_by_reason": omitted_reason_rows,
                "intervals": option_local_intervals,
            },
            "witness": {
                "global_continuity_epoch": self._global_continuity_epoch,
                "first_joint_witness_monotonic_ms": self._first_joint_witness_ms,
                "continuous_global_continuity_after_witness_ms": post_witness,
                "scope": (
                    None
                    if witness_identity is None
                    else {
                        "expiration_timestamp_ms": (witness_identity.expiration_timestamp_ms),
                        "option_type": witness_identity.option_type.value,
                        "tte_band_id": witness_identity.tte_band_id,
                    }
                ),
                "boundary": (
                    None
                    if witness_identity is None
                    else _fact_boundary_object(witness_identity.boundary)
                ),
                "formula_instrument": (
                    None
                    if witness_identity is None
                    else {
                        "instrument_name": witness_identity.instrument_name,
                        "expiration_timestamp_ms": (witness_identity.expiration_timestamp_ms),
                        "option_type": witness_identity.option_type.value,
                        "tte_band_id": witness_identity.tte_band_id,
                    }
                ),
            },
        }


class CoverageLedger:
    def __init__(
        self,
        started_monotonic_ms: int,
        *,
        initial_commit: CausalCommit,
    ) -> None:
        if initial_commit.boundary.received_monotonic_ms != started_monotonic_ms:
            raise ValueError("initial coverage commit must match the ledger start")
        if initial_commit.cause is not CausalCause.RUNTIME_START:
            raise ValueError("initial coverage commit cause must be RUNTIME_START")
        self._current_state = CoverageState.UNKNOWN
        self._current_start_ms = started_monotonic_ms
        self._current_trigger_cause = initial_commit.cause.value
        self._current_blocking_reason = CoverageBlockingReason.RUNTIME_START_PENDING.value
        self._current_affected_scopes = initial_commit.affected_scopes
        self._current_global_continuity_epoch = 1
        self._segments: list[CoverageSegment] = []

    def transition(
        self,
        state: CoverageState,
        *,
        commit: CausalCommit,
        causal_effect: CausalEffect | None = None,
        affected_scopes: tuple[str, ...] | None = None,
        blocking_reason: str,
        global_continuity_epoch: int,
        force: bool = False,
    ) -> None:
        monotonic_ms = commit.boundary.received_monotonic_ms
        if monotonic_ms < self._current_start_ms:
            raise RuntimeError("coverage monotonic time moved backward")
        try:
            CoverageBlockingReason(blocking_reason)
        except ValueError as exc:
            raise ValueError("coverage blocking reason is outside the bounded allowlist") from exc
        resolved_affected_scopes = (
            affected_scopes
            if affected_scopes is not None
            else (
                causal_effect.affected_scopes
                if causal_effect is not None
                else commit.transaction_affected_scopes
            )
        )
        _validate_causal_scopes(resolved_affected_scopes)
        same_coverage_semantics = (
            state is self._current_state
            and blocking_reason == self._current_blocking_reason
            and resolved_affected_scopes == self._current_affected_scopes
            and global_continuity_epoch == self._current_global_continuity_epoch
        )
        if same_coverage_semantics and not force:
            return
        if monotonic_ms > self._current_start_ms:
            self._segments.append(
                CoverageSegment(
                    self._current_start_ms,
                    monotonic_ms,
                    self._current_state,
                    reason=self._current_trigger_cause,
                    blocking_reason=self._current_blocking_reason,
                    affected_scopes=self._current_affected_scopes,
                    global_continuity_epoch=self._current_global_continuity_epoch,
                )
            )
        self._current_start_ms = monotonic_ms
        self._current_state = state
        self._current_trigger_cause = commit.cause.value
        self._current_blocking_reason = blocking_reason
        self._current_affected_scopes = resolved_affected_scopes
        self._current_global_continuity_epoch = global_continuity_epoch

    def close(self, stop_monotonic_ms: int) -> tuple[CoverageSegment, ...]:
        if stop_monotonic_ms < self._current_start_ms:
            raise RuntimeError("coverage stop precedes the current segment")
        if stop_monotonic_ms > self._current_start_ms or not self._segments:
            self._segments.append(
                CoverageSegment(
                    self._current_start_ms,
                    stop_monotonic_ms,
                    self._current_state,
                    reason=self._current_trigger_cause,
                    blocking_reason=self._current_blocking_reason,
                    affected_scopes=self._current_affected_scopes,
                    global_continuity_epoch=self._current_global_continuity_epoch,
                )
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
        failure: BaseException | None = None
        try:
            while True:
                self._raise_sender_failure(sender_task)
                buffered.extend(self._drain_client_envelopes(client))
                if stop_event.is_set():
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
        except BaseException as exc:
            failure = exc

        clean_stop_requested = failure is None and stop_event.is_set()
        if clean_stop_requested:
            self.reducer.begin_clean_stop()
        else:
            self.reducer.prepare_reconnect(
                type(failure).__name__ if failure is not None else "runtime failure"
            )

        sender_cancelled_by_barrier = False
        if not sender_task.done():
            sender_cancelled_by_barrier = True
            sender_task.cancel()
        try:
            await self._stop_client_intake(client)
        except BaseException as exc:
            if failure is None:
                failure = exc
        try:
            await sender_task
        except asyncio.CancelledError:
            if not sender_cancelled_by_barrier and failure is None:
                failure = PublicSessionError("outbound sender cancelled unexpectedly")
        except BaseException as exc:
            if failure is None:
                failure = exc

        if failure is not None and clean_stop_requested:
            self.reducer.prepare_reconnect(type(failure).__name__)
            clean_stop_requested = False

        buffered.extend(self._drain_client_envelopes(client))
        if clean_stop_requested:
            try:
                while buffered:
                    envelope = buffered.popleft()
                    while next_poll_ms < envelope.received_monotonic_ms:
                        self.reducer.advance_time(next_poll_ms)
                        next_poll_ms += poll_ms
                    self.reducer.reduce(
                        envelope,
                        processed_monotonic_ms=_monotonic_ms(),
                    )
            except BaseException as exc:
                failure = exc
                self.reducer.prepare_reconnect(type(exc).__name__)

        if failure is not None:
            while buffered:
                envelope = buffered.popleft()
                try:
                    self.reducer.reduce(
                        envelope,
                        processed_monotonic_ms=_monotonic_ms(),
                    )
                except BaseException:
                    continue

        while True:
            try:
                outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                outbound.task_done()

        try:
            self._capture_transport_metrics(client)
        except BaseException as exc:
            if failure is None:
                failure = exc
        if failure is not None:
            raise failure.with_traceback(failure.__traceback__)
        return self.reducer.clean_stop(_monotonic_ms())

    async def _sender_loop(
        self,
        client: PublicClient,
        outbound: asyncio.Queue[PendingRpc],
    ) -> None:
        while True:
            command = await outbound.get()
            try:
                await self._send_one(client, command)
            finally:
                outbound.task_done()

    async def _send_one(
        self,
        client: PublicClient,
        command: PendingRpc,
    ) -> None:
        try:
            remaining_ms = command.send_deadline_monotonic_ms - _monotonic_ms()
            if remaining_ms <= 0:
                raise TimeoutError("RPC send deadline expired before transport send")
            async with asyncio.timeout(remaining_ms / 1_000):
                await client.send_request(
                    request_id=command.request_id,
                    method=command.method,
                    params=command.params,
                    responding_to_test_request=(command.purpose is RpcPurpose.HEARTBEAT_TEST),
                )
        except asyncio.CancelledError:
            client.enqueue_send_control(
                SendControlEvent(
                    kind=SendControlKind.SEND_FAILED,
                    request_id=command.request_id,
                    boundary_monotonic_ms=_monotonic_ms(),
                    failure=SendFailureKind.CANCELLED,
                )
            )
            raise
        except Exception:
            client.enqueue_send_control(
                SendControlEvent(
                    kind=SendControlKind.SEND_FAILED,
                    request_id=command.request_id,
                    boundary_monotonic_ms=_monotonic_ms(),
                    failure=SendFailureKind.ERROR,
                )
            )
            return
        client.enqueue_send_control(
            SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=command.request_id,
                boundary_monotonic_ms=_monotonic_ms(),
            )
        )

    def _enqueue_commands(
        self,
        outbound: asyncio.Queue[PendingRpc],
        commands: tuple[PendingRpc, ...],
    ) -> None:
        try:
            for command in commands:
                outbound.put_nowait(command)
        except asyncio.QueueFull as exc:
            self.reducer._retire_current_epoch("QUEUE_OVERFLOW")
            raise PublicSessionError("outbound command queue overflow") from exc

    @staticmethod
    def _raise_sender_failure(sender_task: asyncio.Task[None]) -> None:
        if not sender_task.done():
            return
        if sender_task.cancelled():
            raise PublicSessionError("outbound sender cancelled unexpectedly")
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
            await self._send_one(client, command)

    def prepare_reconnect(self, reason: str) -> None:
        self.reducer.prepare_reconnect(reason)

    async def _clean_stop(self, _client: PublicClient | None = None) -> Path:
        return self.reducer.clean_stop(_monotonic_ms())


def _merge_causal_scopes(*scope_groups: tuple[str, ...]) -> tuple[str, ...]:
    scopes = {scope for group in scope_groups for scope in group}
    if "GLOBAL" in scopes:
        return ("GLOBAL",)
    if "OPTION_LOCAL" in scopes or len(scopes) > 256:
        return ("OPTION_LOCAL",)
    return tuple(sorted(scopes))


def _validate_causal_scopes(scopes: tuple[str, ...]) -> None:
    if not scopes or len(scopes) > 256:
        raise ValueError("causal commit affected scopes must contain 1 to 256 labels")
    scope_pattern = re.compile(r"SCOPE:[0-9]+:(?:call|put):[^:]+$")
    for scope in scopes:
        if not isinstance(scope, str) or not scope:
            raise TypeError("causal commit affected scope must be a non-empty string")
        if not (
            scope in {"GLOBAL", "OPTION_LOCAL"}
            or (scope.startswith("OPTION:") and len(scope) > len("OPTION:"))
            or scope_pattern.fullmatch(scope) is not None
        ):
            raise ValueError("causal commit affected scope label is invalid")
    if tuple(sorted(set(scopes))) != scopes:
        raise ValueError("causal commit affected scopes must be unique and sorted")
    if ("GLOBAL" in scopes or "OPTION_LOCAL" in scopes) and len(scopes) != 1:
        raise ValueError("global causal scope labels must stand alone")


def _fact_boundary_object(boundary: FactBoundary) -> dict[str, int]:
    return {
        "session_epoch": boundary.session_epoch,
        "ingress_seq": boundary.ingress_seq,
        "received_monotonic_ms": boundary.received_monotonic_ms,
        "causal_seq": boundary.causal_seq,
    }


def _fact_boundary_key(boundary: FactBoundary) -> tuple[int, int, int, int]:
    return (
        boundary.received_monotonic_ms,
        boundary.session_epoch,
        boundary.ingress_seq,
        boundary.causal_seq,
    )


def _channel_class(
    envelope: InboundEnvelope,
    *,
    combo_names: set[str],
) -> str:
    if envelope.control_event is not None:
        return "CONNECTION_CONTROL"
    if isinstance(envelope.get("id"), int) and not isinstance(envelope.get("id"), bool):
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


def _summarize_source_fields(fields: set[tuple[str, str]]) -> list[dict[str, str]]:
    types_by_key: dict[str, set[str]] = {}
    for key, field_type in fields:
        types_by_key.setdefault(key, set()).add(field_type)
    summary: list[dict[str, str]] = []
    for key, field_types in sorted(types_by_key.items()):
        if len(field_types) == 1:
            field_type = next(iter(field_types))
        elif field_types <= {"integer", "number"}:
            field_type = "number"
        else:
            raise RuntimeError(f"consumed source field changed JSON type: {key}")
        summary.append({"key": key, "type": field_type})
    return summary


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


def _is_target_option_instrument_name(instrument_name: str) -> bool:
    return instrument_name.startswith("BTC_USDC-")


def _is_target_option_lifecycle(payload: object) -> bool:
    data = require_mapping(payload, "option lifecycle")
    instrument_name = require_str(
        data.get("instrument_name"),
        "option lifecycle.instrument_name",
    )
    require_str(data.get("state"), "option lifecycle.state")
    return _is_target_option_instrument_name(instrument_name)


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

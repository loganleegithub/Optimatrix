from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, cast

from market_monitor import (
    BookState,
    ContinuityGap,
    ContinuousOrderBook,
    IndexAvailabilityState,
    IndexHistoryReducer,
    IndexHistoryState,
    IndexMinuteReducer,
    IndexPublicationBoundary,
    IndexPublicationUpdate,
    PriceLevel,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import (
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
    decimal_from_source,
    require_bool,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from options_domain import (
    FINAL_INSTRUMENT_LIFECYCLE_STATES,
    INSTRUMENT_LIFECYCLE_STATES,
    INVERSE_BTC,
    TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES,
    ComboInstrument,
    OptionInstrument,
    OptionProductSpec,
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
from short_vol_radar.baseline import (
    BaselineStatistics,
    BaselineUnavailable,
    compute_baseline_statistics,
)
from short_vol_radar.bucket import (
    BucketEpisodeEndReason,
    BucketLeaderCandidate,
    RadarBucketEpisodeEnd,
    RadarBucketEpisodeTracker,
    RadarBucketTrackerTransition,
    select_bucket_leader,
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
    CoverageBlockingGroup,
    CoverageBlockingReason,
    CoverageSegment,
    CoverageState,
    EvidenceError,
    RadarEventSink,
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
    TteBand,
    classify_time_applicability,
)
from short_vol_radar.radar import (
    CurrentDisposition,
    CurrentEvaluation,
    EvaluationResult,
    TickerState,
    detector_observation_identity,
    finalize_current_evaluation,
    parse_ticker,
)
from short_vol_radar.radar import (
    calculate_current_evaluation as calculate_current_evaluation,
)
from short_vol_radar.review import build_score_feature_contexts
from short_vol_radar.score import (
    LeaderCoverage,
    RadarBucketKey,
    RadarScorePacket,
    RadarScoreResult,
    ScoreBand,
    ScoreUnavailable,
    build_radar_score_packet,
    compute_unsigned_oi_concentration,
    radar_score_observation_identity,
)

from radar_runtime.deribit_public import (
    MAX_PENDING_INBOUND_FRAMES,
    TRANSPORT_CLOSE_CODE_ALLOWLIST,
    TRANSPORT_CLOSE_DISPOSITION_ALLOWLIST,
    TRANSPORT_EXCEPTION_CLASS_ALLOWLIST,
    InboundEnvelope,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicSessionError,
    SendControlEvent,
    SendControlKind,
    SendFailureKind,
)

PUBLIC_RPC_METHODS = frozenset(
    {
        "public/get_combos",
        "public/get_index_chart_data",
        "public/get_instrument",
        "public/get_instruments",
        "public/get_time",
        "public/set_heartbeat",
        "public/status",
        "public/subscribe",
        "public/unsubscribe",
    }
)


class PublicClient(Protocol):
    session_epoch: int

    async def send_request(
        self,
        *,
        request_id: int,
        method: str,
        params: dict[str, object],
    ) -> None: ...

    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope: ...

    def enqueue_send_control(self, event: SendControlEvent) -> None: ...


class _SessionReconnectRequired(PublicSessionError):
    def __init__(self, reason: str) -> None:
        super().__init__("production-public connection closed")
        self.reason = reason


class ShadowRuntimeIntegrityError(RuntimeError):
    """A synchronous Shadow owner/evidence callback failed closed."""


def _call_shadow[ShadowResult](
    operation: str,
    callback: Callable[[], ShadowResult],
) -> ShadowResult:
    try:
        return callback()
    except ShadowRuntimeIntegrityError:
        raise
    except Exception as exc:
        raise ShadowRuntimeIntegrityError(
            f"Shadow runtime integrity failure during {operation}"
        ) from exc


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
    candidate_activation_batch_count: int = 0
    anomaly_end_count_by_reason: Counter[str] = field(default_factory=Counter)
    known_active_duration_ms_sum_by_end_reason: Counter[str] = field(default_factory=Counter)
    public_atomic_quote_state_transition_count: Counter[str] = field(default_factory=Counter)
    _last_candidate_activation_causal_seq: int | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def record_candidate_activation(self, causal_seq: int) -> None:
        if isinstance(causal_seq, bool) or not isinstance(causal_seq, int) or causal_seq <= 0:
            raise ValueError("candidate activation causal sequence must be a positive integer")
        self.distinct_anomaly_episode_count += 1
        self.anomaly_activation_transition_count += 1
        if self._last_candidate_activation_causal_seq != causal_seq:
            self.candidate_activation_batch_count += 1
            self._last_candidate_activation_causal_seq = causal_seq

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
            "candidate_activation_batch_count": self.candidate_activation_batch_count,
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
    scope_results: tuple[tuple[OptionInstrument, EvaluationResult | None], ...]
    boundary_countable: bool
    acceptance_eligible: bool
    catalog_complete: bool


@dataclass(frozen=True)
class RadarFunnelEvaluation:
    instrument_name: str
    known_evaluation: bool
    reason: str | None


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
class AcceptedBookReceipt:
    instrument_name: str
    snapshot_kind: str
    prev_change_id: int | None
    change_id: int
    source_timestamp_ms: int
    session_epoch: int
    subscription_generation: int
    boundary: FactBoundary


@dataclass(frozen=True)
class AcceptedIndexReceipt:
    price_usdc_per_btc: Decimal
    source_timestamp_ms: int
    boundary: FactBoundary


@dataclass(frozen=True)
class AtomicScopeSnapshot:
    commit: CausalCommit
    episode_identity: str
    anomaly_activation_seq: int
    activation_band_id: str
    score_band: ScoreBand
    radar_score_packet: RadarScorePacket
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
    INDEX_HISTORY = "INDEX_HISTORY"
    OPTION_CATALOG = "OPTION_CATALOG"
    OPTION_METADATA = "OPTION_METADATA"
    COMBO_CATALOG = "COMBO_CATALOG"
    COMBO_METADATA = "COMBO_METADATA"
    ADMISSION_REFRESH = "ADMISSION_REFRESH"
    POST_CLOSE_REFRESH = "POST_CLOSE_REFRESH"


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
    response_budget_ms: int
    failure_scope: FailureScope


SHADOW_RPC_PURPOSES = frozenset(
    {
        RpcPurpose.ADMISSION_REFRESH,
        RpcPurpose.POST_CLOSE_REFRESH,
    }
)


@dataclass(frozen=True)
class ShadowRpcIntent:
    request_id: int
    purpose: RpcPurpose
    method: str
    params: Mapping[str, object]
    scope: str
    origin_boundary: FactBoundary
    send_budget_ms: int
    response_budget_ms: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.request_id, bool)
            or not isinstance(self.request_id, int)
            or self.request_id <= 0
        ):
            raise ValueError("Shadow request id must be a positive integer")
        if self.purpose not in SHADOW_RPC_PURPOSES:
            raise ValueError("Shadow request purpose is outside the exact typed route")
        if self.method != "public/get_order_book":
            raise ValueError("Shadow requests may use only public/get_order_book")
        if dict(self.params) != {
            "instrument_name": self.params.get("instrument_name"),
            "depth": 10000,
        }:
            raise ValueError("Shadow request params must be exact")
        instrument_name = self.params.get("instrument_name")
        if not isinstance(instrument_name, str) or not instrument_name:
            raise ValueError("Shadow request instrument_name must be non-empty")
        if not self.scope:
            raise ValueError("Shadow request scope must be non-empty")
        for field_name in ("send_budget_ms", "response_budget_ms"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


class SettledSnapshotPublisher(Protocol):
    def publish_settled(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> None: ...

    def flush_pending(self) -> None: ...


class ShadowRuntimeAdapter(Protocol):
    @property
    def required_combo_instrument_names(self) -> tuple[str, ...]: ...

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]: ...

    def next_time_boundary_monotonic_ms(
        self,
        *,
        reducer: RadarReducer,
        after_monotonic_ms: int,
    ) -> int | None: ...

    def on_request_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]: ...

    def on_request_failure(
        self,
        *,
        request_id: int,
        terminal_state: RpcState,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]: ...

    def on_rpc_response(
        self,
        *,
        request_id: int,
        result: object,
        sent_boundary: FactBoundary,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]: ...

    def terminate(self, *, source: str, boundary: FactBoundary) -> None: ...


@dataclass
class _RpcLifecycle:
    request: PendingRpc
    state: RpcState = RpcState.SCHEDULED
    sent_monotonic_ms: int | None = None
    sent_boundary: FactBoundary | None = None
    response_deadline_monotonic_ms: int | None = None
    terminal_monotonic_ms: int | None = None
    terminal_from_state: RpcState | None = None


@dataclass
class RuntimeDiagnostics:
    reconnect_count: int = 0
    session_gap_count: int = 0
    last_queue_processing_lag_ms: int | None = None
    global_continuity_restart_edges: deque[dict[str, object]] = field(
        default_factory=lambda: deque(maxlen=20)
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


type _BaselineSpecKey = tuple[tuple[int, ...], int, Decimal]


@dataclass(frozen=True)
class _BaselineStatisticsSlot:
    tail_identity: tuple[object, ...]
    statistics: BaselineStatistics


class RadarReducer:
    """Single synchronous owner for one public Radar session's reduced facts."""

    def __init__(
        self,
        *,
        policy: RadarPolicy,
        code_identity: str,
        event_sink: RadarEventSink,
        runtime_identity: str,
        product: OptionProductSpec = INVERSE_BTC,
        shadow_adapter: ShadowRuntimeAdapter | None = None,
        snapshot_publisher: SettledSnapshotPublisher | None = None,
    ) -> None:
        if policy.product_spec_identity != product.identity:
            raise ValueError("Radar Policy product identity does not match the selected product")
        self.policy = policy
        self.product = product
        self.option_lifecycle_channel = product.option_lifecycle_channel
        self.combo_lifecycle_channel = product.combo_lifecycle_channel
        self.index_channel = product.index_channel
        self.code_identity = code_identity
        self.event_sink = event_sink
        self.runtime_identity = runtime_identity
        self.shadow_adapter = shadow_adapter
        self.snapshot_publisher = snapshot_publisher
        self.platform = PlatformReadiness(price_index=product.price_index)
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options: dict[str, OptionInstrument] = {}
        self.options: dict[str, OptionInstrument] = {}
        self.combos: dict[str, ComboInstrument] = {}
        self.option_books: dict[str, ContinuousOrderBook] = {}
        self.combo_books: dict[str, ContinuousOrderBook] = {}
        self.accepted_book_receipts: dict[str, AcceptedBookReceipt] = {}
        self.accepted_index_receipt: AcceptedIndexReceipt | None = None
        self.accepted_platform_continuity_boundary: FactBoundary | None = None
        self.tickers: dict[str, TickerState] = {}
        self._ticker_generations: dict[str, int] = {}
        self._ticker_currentness_latches: dict[str, _TickerCurrentnessLatch] = {}
        self._ticker_unavailable: dict[str, tuple[str, bool]] = {}
        self._ticker_accepted_currentness: dict[str, str] = {}
        self._settled_ticker_currentness: dict[str, _SettledTickerCurrentness] = {}
        self.trackers: dict[str, EpisodeTracker] = {}
        self.results: dict[str, EvaluationResult] = {}
        self.score_results: dict[str, RadarScoreResult] = {}
        self.score_packets: dict[str, RadarScorePacket] = {}
        self.score_bucket_keys: dict[str, RadarBucketKey] = {}
        self.bucket_trackers: dict[RadarBucketKey, RadarBucketEpisodeTracker] = {}
        self.bucket_leader_by_key: dict[RadarBucketKey, str] = {}
        self.bucket_leader_coverage: dict[RadarBucketKey, LeaderCoverage] = {}
        self.atomic_states: dict[str, PublicAtomicQuoteState] = {}
        self.aggregate_results: dict[
            tuple[int, OptionType, str],
            AggregateDetectorResult,
        ] = {}
        self.index = IndexMinuteReducer(policy.largest_lookback_minutes)
        self.index_history = IndexHistoryReducer(
            maximum_lookback_minutes=policy.largest_lookback_minutes,
            return_interval_minutes=policy.return_interval_minutes,
        )
        self._baseline_statistics_by_spec: dict[
            _BaselineSpecKey,
            _BaselineStatisticsSlot,
        ] = {}
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
        self._reserved_shadow_request_ids: set[int] = set()
        self._shadow_terminalized = False
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
        self._coverage = CoverageTracker(
            initialized_ms,
            initial_commit=CausalCommit(
                boundary=FactBoundary(1, 0, initialized_ms, 0),
                cause=CausalCause.RUNTIME_START,
                failure_domain=FailureScope.SESSION,
                affected_scopes=("GLOBAL",),
            ),
        )
        self._scope_counts: dict[tuple[str, OptionType, str], ScopeCounts] = {}
        self._unknown_counts: Counter[str] = Counter()
        self._episode_end_counts: Counter[str] = Counter()
        self._known_active_duration_ms: Counter[str] = Counter()
        self._atomic_transition_counts: Counter[str] = Counter()
        self._band_suspended_duration_ms = 0
        self._band_suspended_started_ms: int | None = None
        self._global_continuity_epoch = 1
        self._active_continuity_incident: ContinuityIncident | None = None
        self._next_continuity_incident_id = 1
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
        self._next_index_history_refresh_ms: int | None = None
        self._next_option_catalog_recovery_ms: int | None = None
        self._next_combo_catalog_recovery_ms: int | None = None
        self._fact_transaction_active = False
        self._fact_transaction_revision = 0
        self._latest_funnel_causal_seq = 0
        self._latest_funnel_evaluations: tuple[RadarFunnelEvaluation, ...] = ()
        self._confirmation_reset_counts: Counter[str] = Counter()
        self._queue_lag_currentness_active = False
        self._queue_lag_transition_pending = False
        self._queue_lag_transition_application: tuple[int, int] | None = None
        self._outbound_barrier_open = False
        self._terminal_barrier_open = False
        self._runtime_barrier_monotonic_ms: int | None = None
        self._runtime_barrier_frontier: tuple[int, int] | None = None

    def begin_session(
        self,
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[PendingRpc, ...]:
        if session_epoch <= 0 or monotonic_ms < 0:
            raise ValueError("session identity must be positive")
        if self._terminal_barrier_open or self._shadow_terminalized:
            raise RuntimeError("terminalized Shadow runtime cannot begin another session")
        if self._session_epoch is not None and session_epoch <= self._session_epoch:
            raise ValueError("session epoch must increase and cannot be reused")
        if self._session_epoch is not None:
            self.diagnostics.reconnect_count += 1
            self.begin_runtime_barrier(monotonic_ms)
            self._retire_current_epoch()
        else:
            self._coverage = CoverageTracker(
                monotonic_ms,
                initial_commit=CausalCommit(
                    boundary=FactBoundary(session_epoch, 0, monotonic_ms, self._causal_seq),
                    cause=CausalCause.RUNTIME_START,
                    failure_domain=FailureScope.SESSION,
                    affected_scopes=("GLOBAL",),
                ),
            )
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
        self._outbound_barrier_open = False
        self._runtime_barrier_monotonic_ms = None
        self._runtime_barrier_frontier = None
        self._last_ingress_seq = 0
        self._application_frontier_by_epoch[session_epoch] = 0
        self._last_boundary_monotonic_ms = monotonic_ms
        self._last_wire_received_ms = monotonic_ms
        self.diagnostics.last_queue_processing_lag_ms = None
        self._bootstrap_queries_issued = False
        self._platform_status_ingress_seq = None
        self._post_status_bootstrap_successes.clear()
        self._channels.clear()
        self._held_subscription_frames.clear()
        self._held_subscription_frame_count = 0
        self.pending_rpcs.clear()
        self._early_rpc_responses.clear()
        self.platform = PlatformReadiness(price_index=self.product.price_index)
        self.platform.start_epoch(session_epoch)
        self.option_catalog = CatalogBootstrap()
        self.combo_catalog = CatalogBootstrap()
        self.catalog_options.clear()
        self.options.clear()
        self.combos.clear()
        self.option_books.clear()
        self.combo_books.clear()
        self.accepted_book_receipts.clear()
        self.accepted_index_receipt = None
        self.accepted_platform_continuity_boundary = None
        self.tickers.clear()
        self._ticker_generations.clear()
        self._ticker_currentness_latches.clear()
        self._ticker_unavailable.clear()
        self._ticker_accepted_currentness.clear()
        self._settled_ticker_currentness.clear()
        self.results.clear()
        self.atomic_states.clear()
        self.aggregate_results.clear()
        self.index = IndexMinuteReducer(self.policy.largest_lookback_minutes)
        self.index_history = IndexHistoryReducer(
            maximum_lookback_minutes=self.policy.largest_lookback_minutes,
            return_interval_minutes=self.policy.return_interval_minutes,
        )
        self._baseline_statistics_by_spec.clear()
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
        self._next_index_history_refresh_ms = None
        self._next_option_catalog_recovery_ms = None
        self._next_combo_catalog_recovery_ms = None
        self._queue_lag_currentness_active = False
        self._queue_lag_transition_pending = False
        self._queue_lag_transition_application = None
        self._latest_funnel_causal_seq = self._causal_seq
        self._latest_funnel_evaluations = ()
        self._commands = []
        boundary = FactBoundary(session_epoch, 0, monotonic_ms, self._causal_seq)
        if active_incident is not None:
            self._transition_coverage(
                CoverageState.UNKNOWN,
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.BOOTSTRAP,
                    failure_domain=FailureScope.SESSION,
                    affected_scopes=("GLOBAL",),
                ),
                affected_scopes=("GLOBAL",),
                blocking_reason=CoverageBlockingReason.PLATFORM_UNESTABLISHED.value,
            )
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
        last_application_seq = self._application_frontier_by_epoch.get(
            envelope.session_epoch,
            0,
        )
        if envelope.ingress_seq != last_application_seq + 1:
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
        connection_error_control: tuple[str, str, str, str, str] | None = None
        if envelope.get("method") == "connection_error":
            connection_error_control = self._parse_connection_error_control(envelope)
        if envelope.session_epoch == self._session_epoch:
            self._last_ingress_seq = envelope.ingress_seq
        if (
            envelope.session_epoch != self._session_epoch
            or envelope.session_epoch in self._retired_epochs
        ):
            return ()
        barrier_frontier = self._runtime_barrier_frontier
        if (
            self._outbound_barrier_open
            and barrier_frontier is not None
            and envelope.session_epoch == barrier_frontier[0]
            and envelope.ingress_seq > barrier_frontier[1]
        ):
            return ()
        self._queue_lag_transition_application = None
        lag_ms = processed_monotonic_ms - envelope.received_monotonic_ms
        if lag_ms < 0:
            raise PublicProtocolError("inbound frame receive time is in the future")
        self.diagnostics.last_queue_processing_lag_ms = lag_ms
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
            control_lifecycle = self._rpc_lifecycles.get(envelope.control_event.request_id)
            if (
                control_lifecycle is not None
                and control_lifecycle.request.purpose in SHADOW_RPC_PURPOSES
            ):
                self._causal_seq += 1
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
                try:
                    self._apply_heartbeat(envelope)
                except (SourceDataError, ValueError) as exc:
                    raise PublicProtocolIncompatibility(
                        "heartbeat notification shape is incompatible"
                    ) from exc
            elif method == "subscription":
                try:
                    self._accept_subscription_frame(envelope)
                except EvidenceError:
                    raise
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
                raise _SessionReconnectRequired(reason)
            else:
                raise PublicProtocolError("unexpected inbound JSON-RPC frame")
        self._settle_pending_queue_lag_transition(
            envelope,
            transaction_revision=transaction_revision,
            causal_seq=causal_seq,
        )
        if self.platform.usable:
            self.accepted_platform_continuity_boundary = self._current_boundary(envelope)
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
        if method not in PUBLIC_RPC_METHODS:
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
            response_budget_ms=self.policy.runtime_limits.rpc_deadline_ms,
            failure_scope=failure_scope,
        )
        self._next_request_id += 1
        self.pending_rpcs[request.request_id] = request
        self._rpc_lifecycles[request.request_id] = _RpcLifecycle(request=request)
        self._commands.append(request)
        if purpose is RpcPurpose.COMBO_CATALOG:
            self._combo_refresh_request_id = request.request_id
        return request

    def allocate_shadow_request_id(self) -> int:
        """Reserve the next id from the sole process-wide JSON-RPC sequence."""
        if self.shadow_adapter is None:
            raise RuntimeError("cannot reserve a Shadow request without an adapter")
        request_id = self._next_request_id
        self._next_request_id += 1
        self._reserved_shadow_request_ids.add(request_id)
        return request_id

    def _schedule_shadow_intents(
        self,
        intents: tuple[ShadowRpcIntent, ...],
    ) -> None:
        if not intents:
            return
        if self.shadow_adapter is None:
            raise RuntimeError("Shadow request intent requires an adapter")
        if self._session_epoch is None:
            raise RuntimeError("cannot schedule a Shadow RPC without a session")
        seen: set[int] = set()
        for intent in intents:
            if not isinstance(intent, ShadowRpcIntent):
                raise TypeError("Shadow adapter must return immutable ShadowRpcIntent values")
            if intent.request_id in seen:
                raise ValueError("Shadow adapter returned a duplicate request id")
            seen.add(intent.request_id)
            if intent.request_id not in self._reserved_shadow_request_ids:
                raise ValueError("Shadow request id was not reserved from the global allocator")
            if intent.request_id in self.pending_rpcs or intent.request_id in self._rpc_lifecycles:
                raise ValueError("Shadow request id conflicts with an existing lifecycle")
            if intent.origin_boundary.session_epoch != self._session_epoch:
                raise ValueError("Shadow request origin belongs to another session epoch")
            if self._outbound_barrier_open:
                self._reserved_shadow_request_ids.remove(intent.request_id)
                continue
            request = PendingRpc(
                request_id=intent.request_id,
                purpose=intent.purpose,
                method=intent.method,
                params=dict(intent.params),
                session_epoch=self._session_epoch,
                scope=intent.scope,
                generation=None,
                origin_boundary=intent.origin_boundary,
                send_deadline_monotonic_ms=(
                    intent.origin_boundary.received_monotonic_ms + intent.send_budget_ms
                ),
                response_budget_ms=intent.response_budget_ms,
                failure_scope=FailureScope.COMBO_LAYER,
            )
            self._reserved_shadow_request_ids.remove(intent.request_id)
            self.pending_rpcs[request.request_id] = request
            self._rpc_lifecycles[request.request_id] = _RpcLifecycle(request=request)
            self._commands.append(request)

    def retire_shadow_rpc(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> bool:
        request = self.pending_rpcs.get(request_id)
        lifecycle = self._rpc_lifecycles.get(request_id)
        if request is None or lifecycle is None:
            return False
        if request.purpose not in SHADOW_RPC_PURPOSES:
            raise ValueError("only a Shadow RPC may use owner retirement")
        if boundary.session_epoch != request.session_epoch:
            raise ValueError("Shadow RPC retirement belongs to another session")
        if boundary.causal_seq <= request.origin_boundary.causal_seq:
            raise ValueError("Shadow RPC retirement must be strictly after its origin")
        self.pending_rpcs.pop(request_id, None)
        self._early_rpc_responses.pop(request_id, None)
        return self._finish_rpc(
            request,
            state=RpcState.RETIRED,
            terminal_monotonic_ms=boundary.received_monotonic_ms,
            record_latency=False,
        )

    def next_shadow_time_boundary_monotonic_ms(
        self,
        *,
        after_monotonic_ms: int,
    ) -> int | None:
        adapter = self.shadow_adapter
        if adapter is None or self._shadow_terminalized:
            return None
        return _call_shadow(
            "trusted-time boundary schedule",
            lambda: adapter.next_time_boundary_monotonic_ms(
                reducer=self,
                after_monotonic_ms=after_monotonic_ms,
            ),
        )

    def begin_runtime_barrier(
        self,
        monotonic_ms: int,
        *,
        terminal: bool = False,
    ) -> None:
        if isinstance(monotonic_ms, bool) or not isinstance(monotonic_ms, int):
            raise TypeError("runtime barrier monotonic time must be an integer")
        if monotonic_ms < 0:
            raise ValueError("runtime barrier monotonic time must be non-negative")
        self._outbound_barrier_open = True
        if self._runtime_barrier_monotonic_ms is None:
            self._runtime_barrier_monotonic_ms = monotonic_ms
        else:
            self._runtime_barrier_monotonic_ms = min(
                self._runtime_barrier_monotonic_ms,
                monotonic_ms,
            )
        if terminal:
            self._terminal_barrier_open = True

    def bind_runtime_barrier_frontier(
        self,
        *,
        session_epoch: int,
        ingress_seq: int,
    ) -> None:
        if not self._outbound_barrier_open:
            raise RuntimeError("runtime barrier must open before binding its frontier")
        if session_epoch != self._session_epoch:
            raise ValueError("runtime barrier frontier belongs to another session")
        if ingress_seq < self._last_ingress_seq:
            raise ValueError("runtime barrier frontier precedes the reduced application frontier")
        frontier = (session_epoch, ingress_seq)
        if self._runtime_barrier_frontier not in {None, frontier}:
            raise ValueError("runtime barrier frontier is immutable")
        self._runtime_barrier_frontier = frontier

    def settle_barrier_deadlines(self, barrier_monotonic_ms: int) -> None:
        if not self._outbound_barrier_open:
            raise RuntimeError("RPC deadline barrier has not opened")
        if (
            isinstance(barrier_monotonic_ms, bool)
            or not isinstance(barrier_monotonic_ms, int)
            or barrier_monotonic_ms < 0
        ):
            raise ValueError("RPC deadline barrier time must be a non-negative integer")
        expired = tuple(
            request
            for request in self.pending_rpcs.values()
            if (
                (
                    (lifecycle := self._rpc_lifecycles[request.request_id]).state
                    is RpcState.SCHEDULED
                    and barrier_monotonic_ms > request.send_deadline_monotonic_ms
                )
                or (
                    lifecycle.state is RpcState.SENT
                    and lifecycle.response_deadline_monotonic_ms is not None
                    and barrier_monotonic_ms > lifecycle.response_deadline_monotonic_ms
                )
            )
        )
        if not expired:
            return
        self._last_boundary_monotonic_ms = max(
            self._last_boundary_monotonic_ms,
            barrier_monotonic_ms,
        )
        self._causal_seq += 1
        for request in expired:
            self.pending_rpcs.pop(request.request_id, None)
            lifecycle = self._rpc_lifecycles[request.request_id]
            self._early_rpc_responses.pop(request.request_id, None)
            transitioned = self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=self._last_boundary_monotonic_ms,
                record_latency=False,
                allow_unsent=(lifecycle.state is RpcState.SCHEDULED),
            )
            if transitioned:
                self._apply_request_failure(
                    request,
                    terminal_state=RpcState.DEADLINE_LATE,
                )

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
            event.kind is SendControlKind.SEND_FAILED
            and event.failure is SendFailureKind.CANCELLED
            and self._outbound_barrier_open
        ):
            return
        if (
            lifecycle.state is RpcState.SCHEDULED
            and event.boundary_monotonic_ms > request.send_deadline_monotonic_ms
        ):
            self._early_rpc_responses.pop(event.request_id, None)
            self.pending_rpcs.pop(event.request_id, None)
            transitioned = self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=event.boundary_monotonic_ms,
                record_latency=False,
                allow_unsent=True,
            )
            if transitioned:
                self._apply_request_failure(
                    request,
                    terminal_state=RpcState.DEADLINE_LATE,
                )
            return
        if event.kind is SendControlKind.SEND_COMPLETED:
            if lifecycle.state is RpcState.SENT:
                return
            if event.boundary_monotonic_ms < request.origin_boundary.received_monotonic_ms:
                raise PublicProtocolError("RPC send boundary precedes scheduling boundary")
            lifecycle.state = RpcState.SENT
            lifecycle.sent_monotonic_ms = event.boundary_monotonic_ms
            lifecycle.sent_boundary = boundary
            lifecycle.response_deadline_monotonic_ms = (
                event.boundary_monotonic_ms + request.response_budget_ms
            )
            if request.purpose in SHADOW_RPC_PURPOSES:
                adapter = self.shadow_adapter
                if adapter is None:
                    raise RuntimeError("Shadow RPC lifecycle lost its adapter")
                self._schedule_shadow_intents(
                    _call_shadow(
                        "request SENT",
                        lambda: adapter.on_request_sent(
                            request_id=request.request_id,
                            boundary=boundary,
                        ),
                    )
                )
            self._early_rpc_responses.pop(event.request_id, None)
            return
        if event.kind is not SendControlKind.SEND_FAILED:
            raise PublicProtocolError("unknown send control kind")
        if lifecycle.state is RpcState.SENT:
            raise PublicProtocolError("RPC send failure cannot follow a completed send boundary")
        self._early_rpc_responses.pop(event.request_id, None)
        self.pending_rpcs.pop(event.request_id, None)
        transitioned = self._finish_rpc(
            request,
            state=RpcState.ERROR,
            terminal_monotonic_ms=event.boundary_monotonic_ms,
            record_latency=False,
            allow_unsent=True,
        )
        if transitioned:
            self._apply_request_failure(
                request,
                terminal_state=RpcState.ERROR,
            )

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
        if previous_state not in {RpcState.SCHEDULED, RpcState.SENT}:
            raise RuntimeError("RPC terminal origin is invalid")
        if record_latency:
            sent_monotonic_ms = lifecycle.sent_monotonic_ms
            if sent_monotonic_ms is None:
                raise RuntimeError("RPC latency requires a send boundary")
        return True

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
    ) -> None:
        request_id = envelope.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            raise PublicProtocolError("response id is invalid")
        request = self.pending_rpcs.get(request_id)
        if request is None or request.session_epoch != self._session_epoch:
            return
        lifecycle = self._rpc_lifecycles[request_id]
        if lifecycle.state is RpcState.SCHEDULED:
            if request_id not in self._early_rpc_responses:
                self._early_rpc_responses[request_id] = envelope
            return
        if lifecycle.state is not RpcState.SENT:
            self.pending_rpcs.pop(request_id, None)
            return
        sent_monotonic_ms = lifecycle.sent_monotonic_ms
        deadline_monotonic_ms = lifecycle.response_deadline_monotonic_ms
        if sent_monotonic_ms is None or deadline_monotonic_ms is None:
            raise RuntimeError("sent RPC lacks its immutable send boundary")
        terminal_monotonic_ms = max(
            envelope.received_monotonic_ms,
            sent_monotonic_ms,
        )
        self.pending_rpcs.pop(request_id, None)
        if request.purpose is not RpcPurpose.SET_HEARTBEAT:
            self._causal_seq += 1
        if terminal_monotonic_ms > deadline_monotonic_ms:
            self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._apply_request_failure(
                request,
                terminal_state=RpcState.DEADLINE_LATE,
            )
            return
        if "error" in envelope:
            self._finish_rpc(
                request,
                state=RpcState.ERROR,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._apply_request_failure(
                request,
                terminal_state=RpcState.ERROR,
            )
            return
        if "result" not in envelope:
            self._finish_rpc(
                request,
                state=RpcState.ERROR,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
            self._apply_request_failure(
                request,
                terminal_state=RpcState.ERROR,
            )
            raise PublicProtocolIncompatibility("JSON-RPC response lacks result")
        result = envelope["result"]
        channel_change_response = request.purpose in {
            RpcPurpose.SUBSCRIBE_CHANNELS,
            RpcPurpose.UNSUBSCRIBE_CHANNELS,
        }
        if not channel_change_response:
            self._finish_rpc(
                request,
                state=RpcState.SUCCESS,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
        boundary = self._current_boundary(envelope)
        if request.purpose in SHADOW_RPC_PURPOSES:
            adapter = self.shadow_adapter
            if adapter is None:
                raise RuntimeError("Shadow RPC lifecycle lost its adapter")
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.SHADOW_RPC_RESPONSE,
                    failure_domain=FailureScope.OPTION,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=tuple(self.options),
                countable=False,
                acceptance_eligible=False,
            )
            sent_boundary = lifecycle.sent_boundary
            if sent_boundary is None:
                raise RuntimeError("Shadow RPC lacks its immutable SENT boundary")
            self._schedule_shadow_intents(
                _call_shadow(
                    "RPC response",
                    lambda: adapter.on_rpc_response(
                        request_id=request.request_id,
                        result=result,
                        sent_boundary=sent_boundary,
                        boundary=boundary,
                    ),
                )
            )
            return
        source_valid = True
        if request.purpose is RpcPurpose.SET_HEARTBEAT:
            if result != "ok":
                raise PublicProtocolIncompatibility("heartbeat acknowledgement was not ok")
            self._plan_channel_change(
                (
                    *PLATFORM_CHANNELS,
                    self.option_lifecycle_channel,
                    self.combo_lifecycle_channel,
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
                raise PublicProtocolIncompatibility(
                    f"{request.method} acknowledgement shape is incompatible"
                ) from exc
            self._finish_rpc(
                request,
                state=RpcState.ERROR if wire_partial else RpcState.SUCCESS,
                terminal_monotonic_ms=terminal_monotonic_ms,
                record_latency=True,
            )
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
                return
            self._clock_revision += 1
            self._next_clock_refresh_ms = (
                boundary.received_monotonic_ms
                + self.policy.runtime_limits.clock_refresh_interval_ms
            )
            index_slot = self._channels.get(self.index_channel)
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
                self.index.start_continuous_coverage(
                    trusted.upper_ms,
                    generation=release_index_generation,
                )
                self._index_coverage_generation = release_index_generation
                self._index_resubscribe_pending = False
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
                    (self.index_channel,),
                    release_index_generation,
                )
                self._drain_held_frames(boundary)
        elif request.purpose is RpcPurpose.INDEX_HISTORY:
            history_trusted_time: TimeInterval | None = None
            if self.clock is not None:
                try:
                    history_trusted_time = self.clock.interval_at(boundary.received_monotonic_ms)
                except (ContinuityGap, ValueError):
                    pass
            try:
                history_changed = self.index_history.apply_chart_result(
                    result,
                    trusted_time=history_trusted_time,
                )
            except SourceDataError as exc:
                raise PublicProtocolIncompatibility(
                    "public/get_index_chart_data response shape is incompatible"
                ) from exc
            self._next_index_history_refresh_ms = (
                boundary.received_monotonic_ms
                + self.policy.runtime_limits.index_history_refresh_interval_ms
            )
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.INDEX_HISTORY,
                    failure_domain=FailureScope.CLOCK_INDEX,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=tuple(self.options),
                countable=history_changed,
            )
        elif request.purpose is RpcPurpose.OPTION_CATALOG:
            source_valid = self._apply_option_snapshot(result, boundary)
        elif request.purpose is RpcPurpose.OPTION_METADATA:
            source_valid = self._apply_option_metadata(request, result)
        elif request.purpose is RpcPurpose.COMBO_CATALOG:
            source_valid = self._apply_combo_snapshot(request, result, boundary)
        elif request.purpose is RpcPurpose.COMBO_METADATA:
            source_valid = self._apply_combo_metadata(request, result, boundary)
        self._note_post_status_bootstrap_success(
            request,
            source_valid=source_valid,
            boundary=self._current_fact_boundary(),
        )

    def _apply_request_failure(
        self,
        request: PendingRpc,
        *,
        terminal_state: RpcState | None = None,
    ) -> None:
        if request.purpose in SHADOW_RPC_PURPOSES:
            adapter = self.shadow_adapter
            if adapter is None:
                raise RuntimeError("Shadow RPC lifecycle lost its adapter")
            if terminal_state not in {
                RpcState.ERROR,
                RpcState.DEADLINE_LATE,
                RpcState.RETIRED,
            }:
                raise RuntimeError("Shadow RPC failure requires an exact terminal state")
            self._schedule_shadow_intents(
                _call_shadow(
                    f"RPC {terminal_state.value}",
                    lambda: adapter.on_request_failure(
                        request_id=request.request_id,
                        terminal_state=terminal_state,
                        boundary=self._current_fact_boundary(),
                    ),
                )
            )
            return
        if request.purpose is RpcPurpose.INDEX_HISTORY:
            boundary = self._current_fact_boundary()
            self._next_index_history_refresh_ms = (
                boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
            )
            self._settle_fact(
                commit=CausalCommit(
                    boundary=boundary,
                    cause=CausalCause.INDEX_HISTORY,
                    failure_domain=FailureScope.CLOCK_INDEX,
                    affected_scopes=("GLOBAL",),
                ),
                affected_instruments=tuple(self.options),
                countable=False,
            )
            return
        if request.purpose in {
            RpcPurpose.CLOCK_BOOTSTRAP,
            RpcPurpose.CLOCK_REFRESH,
        }:
            boundary = self._current_fact_boundary()
            if self.clock is not None:
                try:
                    self.clock.interval_at(boundary.received_monotonic_ms)
                except ContinuityGap:
                    self._invalidate_clock_index(boundary, reason="CLOCK_GAP")
                    return
                self._next_clock_refresh_ms = (
                    boundary.received_monotonic_ms
                    + self.policy.runtime_limits.time_boundary_poll_interval_ms
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
                boundary.received_monotonic_ms
                + self.policy.runtime_limits.time_boundary_poll_interval_ms
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
            return

        admitted_channels = tuple(
            channel
            for channel in acknowledged_channels
            if self._channels[channel].desired_subscribed
            and not self._channels[channel].resync_requested
        )
        self.platform.acknowledge(admitted_channels)
        if self.option_lifecycle_channel in admitted_channels:
            self.option_catalog.acknowledge_lifecycle()
        if self.combo_lifecycle_channel in admitted_channels:
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
            if channel == self.index_channel and self.clock is not None:
                trusted = self.clock.interval_at(boundary.received_monotonic_ms)
                self.index.start_continuous_coverage(
                    trusted.upper_ms,
                    generation=slot.generation,
                )
                self._index_coverage_generation = slot.generation
                self._index_resubscribe_pending = False
            if channel != self.index_channel or self.clock is not None:
                self._mark_held_frames_eligible((channel,), request.generation)
        self._drain_held_frames(boundary)
        self._reconcile_channel_intents(acknowledged_channels, boundary)
        if not self._bootstrap_queries_issued and all(
            self.channel_state(channel) is ChannelState.ACKNOWLEDGED
            for channel in (
                *PLATFORM_CHANNELS,
                self.option_lifecycle_channel,
                self.combo_lifecycle_channel,
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
        self._schedule_index_history_refresh(boundary)
        self._schedule_option_catalog_refresh(boundary)
        self._schedule_combo_refresh(boundary)

    def _schedule_index_history_refresh(self, boundary: FactBoundary) -> PendingRpc:
        self._next_index_history_refresh_ms = (
            boundary.received_monotonic_ms
            + self.policy.runtime_limits.index_history_refresh_interval_ms
        )
        return self._schedule(
            purpose=RpcPurpose.INDEX_HISTORY,
            method="public/get_index_chart_data",
            params={"index_name": self.product.price_index, "range": "2d"},
            scope="INDEX_HISTORY",
            generation=None,
            origin_boundary=boundary,
            failure_scope=FailureScope.CLOCK_INDEX,
        )

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
            params={"currency": self.product.public_currency, "kind": "option", "expired": False},
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
        if channel == self.index_channel and (
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
            product=self.product,
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
        epoch_failure_reason: str | None = None
        try:
            if channel == self.option_lifecycle_channel:
                if _is_target_option_lifecycle(data, self.product):
                    try:
                        if self.option_catalog.buffering:
                            self.option_catalog.accept_lifecycle(data)
                        else:
                            self._apply_option_lifecycle(data, boundary)
                    except (SourceDataError, ValueError):
                        self._mark_option_catalog_incomplete(boundary)
            elif channel == self.combo_lifecycle_channel:
                try:
                    if self.combo_catalog.buffering:
                        self.combo_catalog.accept_lifecycle(data)
                    else:
                        self._apply_combo_lifecycle(data, boundary)
                except (SourceDataError, ValueError):
                    self._mark_combo_catalog_incomplete(boundary)
                if self._combo_refresh_request_id is None:
                    self._schedule_combo_refresh(boundary)
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
            elif channel == self.index_channel:
                self._apply_index(data, boundary)
            elif channel.startswith("ticker.") and channel.endswith(".agg2"):
                instrument_name = channel[len("ticker.") : -len(".agg2")]
                self._apply_ticker(
                    instrument_name,
                    data,
                    boundary,
                )
            elif channel.startswith("book.") and channel.endswith(".agg2"):
                instrument_name = channel[len("book.") : -len(".agg2")]
                self._apply_book(
                    instrument_name,
                    data,
                    boundary,
                )
        except EvidenceError:
            raise
        except (ContinuityGap, SourceDataError) as exc:
            raise PublicProtocolIncompatibility(
                f"{source} subscription payload is incompatible"
            ) from exc
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
        return

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
                instrument = parse_option_instrument(value, product=self.product)
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
                target_product = _is_target_option_product(value, self.product)
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
        if not _is_target_option_instrument_name(instrument_name, self.product):
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
            instrument = parse_option_instrument(payload, product=self.product)
        except SourceDataError:
            instrument = None
        if instrument is None or instrument.instrument_name != request.scope:
            if _is_explicit_final_target_option_metadata(
                payload, request.scope, self.product
            ) or _is_valid_irrelevant_option_metadata(payload, request.scope, self.product):
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
                tracker.state = TrackerState.UNKNOWN
                tracker.episode_id = None
                tracker.activation_band_id = None
                tracker.activation_causal_seq = None
            bucket_key = self.score_bucket_keys.pop(name, None)
            self.score_results.pop(name, None)
            self.score_packets.pop(name, None)
            bucket_tracker = (
                self.bucket_trackers.get(bucket_key) if bucket_key is not None else None
            )
            if bucket_tracker is not None and bucket_tracker.frozen_instrument_name == name:
                transition = bucket_tracker.scope_loss(causal_seq=self._causal_seq)
                self._record_bucket_tracker_transition(
                    transition,
                    boundary.received_monotonic_ms,
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
        if self.channel_state(self.index_channel) in {
            ChannelState.UNSUBSCRIBED,
            ChannelState.RETIRED,
        }:
            self._index_resubscribe_pending = True
            self._plan_channel_change(
                (self.index_channel,),
                subscribe=True,
                origin_boundary=boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )

    def _apply_index(self, payload: object, boundary: FactBoundary) -> bool:
        if self.clock is None:
            return False
        try:
            data = require_mapping(payload, "index notification")
            if require_str(data.get("index_name"), "index.index_name") != self.product.price_index:
                raise SourceDataError("unexpected index_name")
            source_timestamp_ms = require_int(data.get("timestamp"), "index.timestamp")
            price = decimal_from_source(data.get("price"), "index.price")
            try:
                trusted_upper_ms = self.clock.interval_at(boundary.received_monotonic_ms).upper_ms
            except (ContinuityGap, ValueError):
                downstream_receipt_eligible = False
            else:
                downstream_receipt_eligible = source_timestamp_ms <= trusted_upper_ms
            self.index.accept_tick(
                source_timestamp_ms=source_timestamp_ms,
                price=price,
                causal_seq=self._causal_seq,
            )
        except (ContinuityGap, SourceDataError, ValueError):
            gap_commit = CausalCommit(
                boundary=boundary,
                cause=CausalCause.INDEX_CONTINUITY_GAP,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            )
            self._invalidate_index_publication_currentness()
            if not self._index_gap_active:
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
                    self.index_channel,
                    boundary,
                    failure_scope=FailureScope.CLOCK_INDEX,
                )
            self._settle_fact(
                commit=gap_commit,
                affected_instruments=tuple(self.options),
                countable=False,
            )
            return False
        if downstream_receipt_eligible:
            self.accepted_index_receipt = AcceptedIndexReceipt(
                price_usdc_per_btc=price,
                source_timestamp_ms=source_timestamp_ms,
                boundary=boundary,
            )
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
        return classification

    def _invalidate_index_publication_currentness(
        self,
    ) -> None:
        self.index.invalidate_publication()

    def _publish_index_baseline(
        self,
        *,
        trusted: TimeInterval,
        boundary: FactBoundary,
    ) -> IndexPublicationUpdate | None:
        generation = self._index_coverage_generation or self.index.generation
        if generation is None:
            return None
        return self.index.publish_ready(
            trusted_time=trusted,
            source_stale_deadline_ms=(self.policy.runtime_limits.index_source_stale_deadline_ms),
            generation=generation,
            global_continuity_epoch=self._global_continuity_epoch,
            boundary=IndexPublicationBoundary(
                session_epoch=boundary.session_epoch,
                ingress_seq=boundary.ingress_seq,
                received_monotonic_ms=boundary.received_monotonic_ms,
                causal_seq=boundary.causal_seq,
            ),
        )

    def _transition_ticker_accepted_currentness(
        self,
        instrument_name: str,
        *,
        state: str,
    ) -> None:
        self._ticker_accepted_currentness[instrument_name] = state

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
            self._settle_ticker_boundary(
                instrument_name,
                boundary=boundary,
                cause=CausalCause.TICKER_LATE_IGNORED,
                countable=False,
            )
            return True
        if candidate_currentness == "TIMESTAMP_AHEAD":
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
        countable = previous is None or any(
            current != prior
            for current, prior in (
                (ticker.forward_usdc, previous.forward_usdc),
                (ticker.signed_delta, previous.signed_delta),
                (ticker.mark_iv_fraction, previous.mark_iv_fraction),
            )
        )
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
            except (ContinuityGap, SourceDataError) as exc:
                reason = (
                    book.reason
                    if isinstance(exc, ContinuityGap) or book.reason == "CROSSED_OR_LOCKED_BOOK"
                    else "BOOK_SOURCE_INVALID"
                )
                book.invalidate(reason or "OPTION_BOOK_GAP")
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
            self._record_accepted_book_receipt(
                instrument_name=instrument_name,
                payload=payload,
                boundary=boundary,
            )
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
            self._record_accepted_book_receipt(
                instrument_name=instrument_name,
                payload=payload,
                boundary=boundary,
            )
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

    def _record_accepted_book_receipt(
        self,
        *,
        instrument_name: str,
        payload: object,
        boundary: FactBoundary,
    ) -> None:
        data = require_mapping(payload, "book")
        snapshot_kind = require_str(data.get("type"), "book.type")
        change_id = require_int(data.get("change_id"), "book.change_id")
        source_timestamp_ms = require_int(data.get("timestamp"), "book.timestamp")
        prev_change_id = (
            require_int(data.get("prev_change_id"), "book.prev_change_id")
            if snapshot_kind == "change"
            else None
        )
        slot = self._channels.get(book_channel(instrument_name))
        generation = slot.generation if slot is not None else 0
        self.accepted_book_receipts[instrument_name] = AcceptedBookReceipt(
            instrument_name=instrument_name,
            snapshot_kind=snapshot_kind,
            prev_change_id=prev_change_id,
            change_id=change_id,
            source_timestamp_ms=source_timestamp_ms,
            session_epoch=boundary.session_epoch,
            subscription_generation=generation,
            boundary=boundary,
        )

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

    def _schedule_combo_refresh(self, boundary: FactBoundary) -> PendingRpc:
        self._combo_refresh_generation += 1
        request = self._schedule(
            purpose=RpcPurpose.COMBO_CATALOG,
            method="public/get_combos",
            params={"currency": self.product.public_currency},
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
            self._schedule_combo_refresh(boundary)

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
            self._schedule_combo_refresh(boundary)
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
            self._schedule_combo_refresh(boundary)
        self._next_combo_catalog_recovery_ms = (
            None
            if self.combo_catalog.complete
            else boundary.received_monotonic_ms + self.policy.runtime_limits.rpc_deadline_ms
        )
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
            combo = parse_combo_instrument(summary, payload, product=self.product)
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
            if _is_valid_irrelevant_combo_metadata(payload, request.scope, self.product):
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
        self._invalidate_index_publication_currentness()
        if incident is not None:
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
        restart_state = (
            CoverageState.KNOWN_DEGRADED
            if any(
                tracker.detector_state is DetectorState.ANOMALY_ACTIVE
                for tracker in self.trackers.values()
            )
            else CoverageState.UNKNOWN
        )
        self._coverage.transition(
            restart_state,
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
            self._active_continuity_incident = None

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
                self.index_channel,
                boundary,
                failure_scope=FailureScope.CLOCK_INDEX,
            )
        if not self._fact_transaction_active:
            self._settle_shadow_transaction(transaction_commit)

    def _instrument_time_currentness_token(
        self,
        instrument: OptionInstrument,
        trusted: TimeInterval,
        tail_by_lookback: dict[int, IndexHistoryState],
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
            tail = self._cached_index_tail(
                max(applicability.band.lookbacks_minutes),
                trusted=trusted,
                tail_by_lookback=tail_by_lookback,
            )
            tail_identity = (
                tail.availability.value,
                tail.reason,
                tail.latest_source_timestamp_ms,
                tail.points,
            )
        return (
            applicability.classification.value,
            applicability.band.band_id if applicability.band is not None else None,
            tail_identity,
        )

    def _time_currentness_by_instrument(
        self,
        trusted: TimeInterval,
        tail_by_lookback: dict[int, IndexHistoryState] | None = None,
    ) -> dict[str, tuple[object, ...]]:
        tails = {} if tail_by_lookback is None else tail_by_lookback
        return {
            name: self._instrument_time_currentness_token(instrument, trusted, tails)
            for name, instrument in sorted(self.options.items())
        }

    def _cached_index_tail(
        self,
        lookback_minutes: int,
        *,
        trusted: TimeInterval,
        tail_by_lookback: dict[int, IndexHistoryState],
    ) -> IndexHistoryState:
        tail = tail_by_lookback.get(lookback_minutes)
        if tail is None:
            tail = self.index_history.current_tail(
                lookback_minutes,
                trusted_time=trusted,
                source_stale_deadline_ms=(
                    self.policy.runtime_limits.index_history_source_stale_deadline_ms
                ),
            )
            tail_by_lookback[lookback_minutes] = tail
        return tail

    def _baseline_statistics_for(
        self,
        *,
        band: TteBand,
        tail: IndexHistoryState,
    ) -> BaselineStatistics:
        tail_identity = tail.economic_identity
        sampled_prices = tail.prices
        if tail_identity is None or sampled_prices is None:
            raise ValueError("baseline statistics require an available index-history tail")
        spec_key: _BaselineSpecKey = (
            band.lookbacks_minutes,
            band.return_interval_minutes,
            band.annualized_variance_floor,
        )
        cached = self._baseline_statistics_by_spec.get(spec_key)
        if cached is not None and cached.tail_identity == tail_identity:
            return cached.statistics
        statistics = compute_baseline_statistics(
            sampled_prices=sampled_prices,
            lookbacks=band.lookbacks_minutes,
            return_interval_minutes=band.return_interval_minutes,
            annualized_variance_floor=band.annualized_variance_floor,
        )
        self._baseline_statistics_by_spec[spec_key] = _BaselineStatisticsSlot(
            tail_identity=tail_identity,
            statistics=statistics,
        )
        return statistics

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
        queue_lag_transition_rebuild = (
            queue_lag_transition_boundary and self._queue_lag_transition_pending
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
                force_full_currentness=queue_lag_transition_rebuild,
            )
            self._settle_shadow_transaction(commit)
            self._fact_transaction_revision += 1
            if queue_lag_transition_rebuild:
                self._queue_lag_transition_pending = False
        finally:
            self._fact_transaction_active = False

    def _settle_shadow_transaction(
        self,
        commit: CausalCommit,
        *,
        sync_combo_subscriptions: bool = True,
    ) -> None:
        adapter = self.shadow_adapter
        if adapter is None or self._shadow_terminalized or commit.cause is CausalCause.CLEAN_STOP:
            return
        self._schedule_shadow_intents(
            _call_shadow(
                "settled transaction",
                lambda: adapter.on_settled_transaction(
                    reducer=self,
                    commit=commit,
                ),
            )
        )
        if sync_combo_subscriptions:
            self._sync_combo_subscriptions(commit.boundary)
        publisher = self.snapshot_publisher
        if publisher is not None:
            try:
                publisher.publish_settled(reducer=self, commit=commit)
            except Exception as exc:
                raise ShadowRuntimeIntegrityError(
                    "settled workbench snapshot publication failed"
                ) from exc

    def _cross_sectional_score_dependents(
        self,
        affected_instruments: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return Call/Put score peers on the affected and immediately shorter expiries."""

        surface_expiries = sorted(
            {candidate.expiration_timestamp_ms for candidate in self.options.values()}
        )
        dependent_expiries: set[int] = set()
        for affected_name in affected_instruments:
            affected = self.options.get(affected_name)
            if affected is None:
                continue
            try:
                expiry_index = surface_expiries.index(affected.expiration_timestamp_ms)
            except ValueError:
                continue
            dependent_expiries.update(surface_expiries[max(0, expiry_index - 1) : expiry_index + 1])
        return tuple(
            sorted(
                name
                for name, candidate in self.options.items()
                if candidate.expiration_timestamp_ms in dependent_expiries
            )
        )

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
        publication_update = self._publish_index_baseline(
            trusted=trusted,
            boundary=boundary,
        )
        if (
            publication_update is not None
            and publication_update.currentness_lost_reason is not None
        ):
            self._invalidate_index_publication_currentness()

        directly_affected_names = tuple(
            sorted(
                dict.fromkeys(
                    name for name in (*affected_instruments, *newly_stale) if name in self.options
                )
            )
        )
        countable_names = set(directly_affected_names) if countable else set()
        tail_by_lookback: dict[int, IndexHistoryState] = {}
        current_time_tokens = self._time_currentness_by_instrument(
            trusted,
            tail_by_lookback,
        )
        time_changed_names = {
            name
            for name, token in current_time_tokens.items()
            if self._last_time_currentness_by_instrument.get(name) != token
        }
        core_recalculation_names = set((*directly_affected_names, *time_changed_names))
        recalculation_names = set(core_recalculation_names)
        score_only_names: set[str] = set()
        if commit.cause in {CausalCause.TICKER_APPLIED, CausalCause.TICKER_SOURCE_STALE}:
            surface_dependencies = set(
                self._cross_sectional_score_dependents(directly_affected_names)
            )
            score_only_names.update(surface_dependencies - core_recalculation_names)
            recalculation_names.update(surface_dependencies)
            if countable and commit.cause is CausalCause.TICKER_APPLIED:
                countable_names.update(surface_dependencies)
        if force_full_currentness:
            core_recalculation_names.update(self.options)
            recalculation_names.update(self.options)
        elif affected_scope_keys:
            scoped_names = {
                name
                for name, instrument in self.options.items()
                if (instrument.expiration_timestamp_ms, instrument.option_type)
                in affected_scope_keys
            }
            core_recalculation_names.update(scoped_names)
            recalculation_names.update(scoped_names)
        score_only_names.difference_update(core_recalculation_names)
        frozen_scope_keys = set(affected_scope_keys)
        frozen_scope_keys.update(
            (
                self.options[name].expiration_timestamp_ms,
                self.options[name].option_type,
            )
            for name in recalculation_names
        )
        names = tuple(sorted(recalculation_names))
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
        global_gap_reason: str | None = None
        global_gap_effect: CausalEffect | None = None
        global_resubscribe = False
        global_resubscribe_reason: str | None = None
        publication_epoch_restarted = False
        if (
            publication_update is not None
            and publication_update.currentness_lost_reason is not None
        ):
            global_gap_reasons.add(publication_update.currentness_lost_reason)
            if publication_update.currentness_lost_reason in {
                "INDEX_SOURCE_STALE",
                "INDEX_CONTINUITY_GAP",
            }:
                global_resubscribe = True
                global_resubscribe_reason = publication_update.currentness_lost_reason
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
            global_gap_effect = CausalEffect(
                cause=CausalCause(global_gap_reason),
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            )
            transaction_commit = self._freeze_fact_commit(
                commit,
                (*concurrent_effects, global_gap_effect),
            )
            if not self._index_gap_active:
                self._index_gap_active = True
                active = self._active_continuity_incident
                epoch_before_restart = self._global_continuity_epoch
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
                publication_epoch_restarted = self._global_continuity_epoch != epoch_before_restart
            names = tuple(sorted(self.options))
            score_only_names.clear()
            prepared.clear()
            if publication_epoch_restarted:
                self._publish_index_baseline(
                    trusted=trusted,
                    boundary=boundary,
                )
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
                    self.index_channel,
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
                self._cached_index_tail(
                    max(applicability.band.lookbacks_minutes),
                    trusted=trusted,
                    tail_by_lookback=tail_by_lookback,
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
                prior = self.results.get(name)
                prior_current = prior.current_evaluation if prior is not None else None
                if name in score_only_names and prior_current is not None:
                    if prior_current.calculation is None:
                        current = prior_current
                    else:
                        current = CurrentEvaluation(
                            disposition=CurrentDisposition.SCORE_PENDING,
                            reason="V2_SCORE_FEATURES_PENDING",
                            known_evaluation=False,
                            full_formula_evaluation=False,
                            band_id=prior_current.band_id,
                            calculation=prior_current.calculation,
                        )
                else:
                    current_ticker, ticker_reason, ticker_continuity_gap = self._current_ticker(
                        name
                    )
                    baseline_reason = (
                        tail.reason
                        if tail is not None
                        and tail.availability is not IndexAvailabilityState.AVAILABLE
                        and tail.reason is not None
                        else "INDEX_WARMUP"
                    )
                    baseline_statistics: BaselineStatistics | None = None
                    if (
                        applicability.band is not None
                        and tail is not None
                        and tail.availability is IndexAvailabilityState.AVAILABLE
                    ):
                        try:
                            baseline_statistics = self._baseline_statistics_for(
                                band=applicability.band,
                                tail=tail,
                            )
                        except BaselineUnavailable as exc:
                            baseline_reason = str(exc) or type(exc).__name__
                    current = calculate_current_evaluation(
                        policy=self.policy,
                        instrument=instrument,
                        trusted_time=trusted,
                        causal_seq=self._causal_seq,
                        option_book=self.option_books.get(name),
                        ticker=current_ticker,
                        causal_closes=None,
                        baseline_statistics=baseline_statistics,
                        baseline_unavailable_reason=baseline_reason,
                        ticker_unavailable_reason=ticker_reason,
                        ticker_continuity_gap=ticker_continuity_gap,
                    )
            baseline_identity = (
                tail.economic_identity
                if tail is not None and tail.economic_identity is not None
                else (
                    "INDEX_BASELINE_UNAVAILABLE",
                    tail.availability.value
                    if tail is not None
                    else applicability.classification.value,
                )
            )
            identity = detector_observation_identity(
                policy=self.policy,
                instrument=instrument,
                trusted_time=trusted,
                option_book=self.option_books.get(name),
                ticker=self.tickers.get(name),
                baseline_identity=baseline_identity,
            )
            prepared.append(
                ScopeCurrent(
                    instrument=instrument,
                    current=current,
                    observation_identity=identity,
                    index_tail_identity=(baseline_identity if tail is not None else None),
                    observation_eligible=False,
                    previous_tracker_state=tracker.state,
                    previous_episode_id=tracker.episode_id,
                )
            )

        calculations = {
            name: result.calculation
            for name, result in self.results.items()
            if result.calculation is not None
        }
        calculations.update(
            {
                item.instrument.instrument_name: item.current.calculation
                for item in prepared
                if item.current.calculation is not None
            }
        )
        score_contexts = build_score_feature_contexts(
            options=self.options,
            calculations=calculations,
            tickers=self.current_diagnostic_tickers,
            score_model=self.policy.score_model,
            instrument_names=names,
        )
        finalized_prepared: list[ScopeCurrent] = []
        for item in prepared:
            name = item.instrument.instrument_name
            current = item.current
            if current.disposition is CurrentDisposition.SCORE_PENDING:
                if current.calculation is None:
                    raise RuntimeError("pending V2 score lacks its core calculation")
                try:
                    score_inputs = score_contexts[name].score_inputs(current.calculation)
                    current = finalize_current_evaluation(
                        policy=self.policy,
                        core=current,
                        score_inputs=score_inputs,
                        causal_seq=transaction_commit.boundary.causal_seq,
                        trusted_time=trusted,
                    )
                except ScoreUnavailable as exc:
                    current = CurrentEvaluation(
                        disposition=CurrentDisposition.UNKNOWN,
                        reason=str(exc) or "V2_SCORE_CORE_UNKNOWN",
                        known_evaluation=False,
                        full_formula_evaluation=False,
                        band_id=current.band_id,
                        calculation=current.calculation,
                    )
            score_known = current.score_result is not None
            observation_identity = item.observation_identity
            if current.score_result is not None:
                observation_identity = radar_score_observation_identity(
                    core_identity=observation_identity,
                    result=current.score_result,
                )
            observation_eligible = (
                name in countable_names
                and score_known
                and current.disposition
                in {CurrentDisposition.V2_SCORE, CurrentDisposition.REVIEW_ONLY}
                and self._last_observation_identity.get(name) != observation_identity
            )
            finalized_prepared.append(
                replace(
                    item,
                    current=current,
                    observation_identity=observation_identity,
                    observation_eligible=observation_eligible,
                )
            )
        prepared = finalized_prepared

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
                scope_results=(),
                boundary_countable=countable,
                acceptance_eligible=acceptance_eligible,
                catalog_complete=self.option_catalog.complete,
            )
            for current in current_by_scope.values()
        )

        evaluated = self._settle_v2_bucket_evaluations(
            prepared=tuple(prepared),
            commit=transaction_commit,
            trusted=trusted,
        )
        evaluated_by_name = {
            instrument.instrument_name: value for value in evaluated for instrument in (value[0],)
        }

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
                scope_results=tuple(
                    (candidate, self.results.get(candidate.instrument_name))
                    for candidate in self.options.values()
                    if candidate.expiration_timestamp_ms
                    == snapshot.current[0].instrument.expiration_timestamp_ms
                    and candidate.option_type is snapshot.current[0].instrument.option_type
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
                        boundary.causal_seq,
                    )
            if snapshot.acceptance_eligible and aggregate.coverage is DetectorCoverage.COMPLETE:
                counter = self._scope_counter(
                    representative.option_type,
                    scope_results[0][1].band_id or "",
                )
                counter.complete_aggregate_detector_evaluation_count += 1
                if scope_truth.has_current_full_formula:
                    counter.complete_aggregate_with_full_formula_evaluation_count += 1
                    if scope_truth.formula_instrument is None:
                        raise RuntimeError(
                            "full-formula joint evaluation lacks formula instrument identity"
                        )

        for instrument, result, _state, _episode in evaluated:
            if result.band_id is not None:
                counter = self._scope_counter(instrument.option_type, result.band_id)
                counter.applicable_instrument_count = max(
                    counter.applicable_instrument_count,
                    1,
                )
                if (
                    acceptance_eligible
                    and instrument.instrument_name in countable_names
                    and result.known_evaluation
                ):
                    counter.known_per_instrument_detector_evaluation_count += 1
                if (
                    acceptance_eligible
                    and instrument.instrument_name in countable_names
                    and result.full_formula_evaluation
                ):
                    counter.known_full_detector_formula_evaluation_count += 1

        self._latest_funnel_causal_seq = transaction_commit.boundary.causal_seq
        self._latest_funnel_evaluations = tuple(
            RadarFunnelEvaluation(
                instrument_name=instrument.instrument_name,
                known_evaluation=result.known_evaluation,
                reason=result.reason,
            )
            for instrument, result, _state, _episode in evaluated
            if (
                instrument.instrument_name in countable_names
                and acceptance_eligible
                and result.band_id is not None
            )
        )

        for atomic_snapshot in self.active_radar_scope_snapshots(commit=transaction_commit):
            if atomic_snapshot.score_band is ScoreBand.HIGH:
                self._evaluate_atomic(atomic_snapshot)

        self._sync_combo_subscriptions(boundary)
        self._update_coverage(
            commit=transaction_commit,
        )
        self._last_time_currentness_by_instrument = current_time_tokens
        self._last_time_currentness_token = tuple(current_time_tokens.items())

    def _settle_v2_bucket_evaluations(
        self,
        *,
        prepared: tuple[ScopeCurrent, ...],
        commit: CausalCommit,
        trusted: TimeInterval,
    ) -> list[tuple[OptionInstrument, EvaluationResult, TrackerState, str | None]]:
        """Settle one causal batch through the sole V2 bucket episode owner."""
        prepared_by_name = {item.instrument.instrument_name: item for item in prepared}
        calculations = {
            name: result.calculation
            for name, result in self.results.items()
            if result.calculation is not None
        }
        calculations.update(
            {
                name: item.current.calculation
                for name, item in prepared_by_name.items()
                if item.current.calculation is not None
            }
        )

        for name, item in prepared_by_name.items():
            calculation = item.current.calculation
            if calculation is not None and item.current.band_id is not None:
                self.score_bucket_keys[name] = RadarBucketKey(
                    tte_band_id=item.current.band_id,
                    expiry_ms=item.instrument.expiration_timestamp_ms,
                    option_type=item.instrument.option_type,
                    delta_bucket=calculation.delta_bucket.value,
                )
            elif item.current.band_id is None:
                self.score_bucket_keys.pop(name, None)
            if item.current.score_result is None:
                self.score_results.pop(name, None)
            else:
                self.score_results[name] = item.current.score_result

        live_names = set(self.options)
        for mapping in (self.score_bucket_keys, self.score_results, self.score_packets):
            for name in set(mapping) - live_names:
                mapping.pop(name, None)

        grouped_names: dict[RadarBucketKey, list[str]] = {}
        for name, bucket_key in self.score_bucket_keys.items():
            if name in self.options:
                grouped_names.setdefault(bucket_key, []).append(name)

        for bucket_key, existing_bucket_tracker in tuple(self.bucket_trackers.items()):
            if bucket_key in grouped_names:
                continue
            transition = existing_bucket_tracker.scope_loss(causal_seq=commit.boundary.causal_seq)
            self._record_bucket_tracker_transition(
                transition,
                commit.boundary.received_monotonic_ms,
            )
            self.bucket_trackers.pop(bucket_key, None)

        current_tickers = self.current_diagnostic_tickers
        new_packets: dict[str, RadarScorePacket] = {}
        new_bucket_leaders: dict[RadarBucketKey, str] = {}
        new_bucket_coverages: dict[RadarBucketKey, LeaderCoverage] = {}
        activated_high_by_name: dict[str, str] = {}
        for bucket_key in sorted(
            grouped_names,
            key=lambda key: (
                key.expiry_ms,
                key.option_type.value,
                key.tte_band_id,
                key.delta_bucket,
            ),
        ):
            names = tuple(sorted(grouped_names[bucket_key]))
            candidates: list[BucketLeaderCandidate] = []
            for name in names:
                instrument = self.options[name]
                candidate_score = self.score_results.get(name)
                calculation = calculations.get(name)
                if candidate_score is None or calculation is None:
                    prepared_member = prepared_by_name.get(name)
                    prior = self.results.get(name)
                    candidates.append(
                        BucketLeaderCandidate(
                            bucket_key=bucket_key,
                            instrument_name=name,
                            strike=instrument.strike,
                            score_result=None,
                            stressed_richness=None,
                            target_spread_ticks=None,
                            total_consumed_level_count=None,
                            unknown_reason=(
                                prepared_member.current.reason
                                if prepared_member is not None
                                and prepared_member.current.reason is not None
                                else prior.reason
                                if prior is not None and prior.reason is not None
                                else "V2_SCORE_CURRENT_UNKNOWN"
                            ),
                        )
                    )
                    continue
                candidates.append(
                    BucketLeaderCandidate(
                        bucket_key=bucket_key,
                        instrument_name=name,
                        strike=instrument.strike,
                        score_result=candidate_score,
                        stressed_richness=calculation.richness,
                        target_spread_ticks=calculation.target_spread_ticks,
                        total_consumed_level_count=(
                            len(calculation.target_bid.consumed)
                            + len(calculation.target_ask.consumed)
                        ),
                    )
                )

            bucket_tracker = self.bucket_trackers.get(bucket_key)
            selection = select_bucket_leader(
                tuple(candidates),
                frozen_instrument_name=(
                    bucket_tracker.frozen_instrument_name if bucket_tracker is not None else None
                ),
            )
            if selection.leader is None and bucket_tracker is not None:
                prior_leader = self.bucket_leader_by_key.get(bucket_key)
                if (
                    self._queue_lag_currentness_active
                    and bucket_tracker.episode is None
                    and bucket_tracker.confirmation_observation_count > 0
                    and prior_leader in names
                ):
                    new_bucket_leaders[bucket_key] = prior_leader
                    new_bucket_coverages[bucket_key] = LeaderCoverage.UNKNOWN
                    continue
                transition = (
                    bucket_tracker.scope_loss(causal_seq=commit.boundary.causal_seq)
                    if selection.reason == "FROZEN_LEADER_SCOPE_LOSS"
                    else bucket_tracker.core_unknown(
                        causal_seq=commit.boundary.causal_seq,
                        reason=selection.reason or "BUCKET_CORE_UNKNOWN",
                    )
                )
                self._record_bucket_tracker_transition(
                    transition,
                    commit.boundary.received_monotonic_ms,
                )
                selection = select_bucket_leader(tuple(candidates))
            if selection.leader is None:
                continue

            leader_name = selection.leader.instrument_name
            new_bucket_leaders[bucket_key] = leader_name
            new_bucket_coverages[bucket_key] = selection.coverage
            leader_calculation = calculations.get(leader_name)
            if leader_calculation is None:
                raise RuntimeError("known V2 bucket leader lacks its calculation")
            if bucket_tracker is None:
                bucket_tracker = RadarBucketEpisodeTracker(
                    runtime_identity=self.runtime_identity,
                    policy_identity=self.policy.identity,
                    bucket_key=bucket_key,
                    score_model=self.policy.score_model,
                    clue_eligible=leader_calculation.clue_eligible,
                )
                self.bucket_trackers[bucket_key] = bucket_tracker

            bucket_oi_known = all(
                (ticker := current_tickers.get(name)) is not None
                and ticker.open_interest is not None
                and ticker.option_gamma is not None
                for name in names
            )
            bucket_total_unsigned_gamma_weight: Decimal | None = None
            if bucket_oi_known:
                bucket_total_unsigned_gamma_weight = Decimal(0)
                for name in names:
                    ticker = current_tickers[name]
                    if ticker.open_interest is None or ticker.option_gamma is None:
                        raise RuntimeError("known bucket OI completeness lost during settlement")
                    bucket_total_unsigned_gamma_weight += ticker.open_interest * abs(
                        ticker.option_gamma
                    )
            leader_result = self.score_results.get(leader_name)
            if leader_result is None:
                raise RuntimeError("known V2 bucket leader lacks its score result")
            leader_ticker = current_tickers.get(leader_name)
            prior_packet = self.score_packets.get(leader_name)
            if (
                leader_name not in prepared_by_name
                and prior_packet is not None
                and prior_packet.bucket_key == bucket_key
                and prior_packet.leader_instrument_name == leader_name
                and prior_packet.result == leader_result
                and prior_packet.leader_coverage is selection.coverage
            ):
                new_packets[leader_name] = prior_packet
            else:
                new_packets[leader_name] = build_radar_score_packet(
                    policy_identity=self.policy.identity,
                    fact_boundary=self._radar_packet_fact_boundary(commit.boundary),
                    bucket_key=bucket_key,
                    leader_instrument_name=leader_name,
                    result=leader_result,
                    oi_diagnostic=compute_unsigned_oi_concentration(
                        open_interest=(
                            leader_ticker.open_interest if leader_ticker is not None else None
                        ),
                        option_gamma=(
                            leader_ticker.option_gamma if leader_ticker is not None else None
                        ),
                        bucket_total_unsigned_gamma_weight=bucket_total_unsigned_gamma_weight,
                    ),
                    stressed_richness=leader_calculation.richness,
                    leader_coverage=selection.coverage,
                )

            leader_packet = new_packets[leader_name]
            if bucket_tracker.episode is None:
                alignment_transition = bucket_tracker.align_leader(
                    instrument_name=leader_name,
                    score_band=leader_packet.result.band,
                )
                self._record_bucket_tracker_transition(
                    alignment_transition,
                    commit.boundary.received_monotonic_ms,
                )
            leader_item = prepared_by_name.get(leader_name)
            bucket_transition = RadarBucketTrackerTransition()
            if leader_item is not None and leader_item.observation_eligible:
                bucket_transition = bucket_tracker.observe(
                    packet=leader_packet,
                    observation_identity=leader_item.observation_identity,
                    causal_seq=commit.boundary.causal_seq,
                    trusted_time=trusted,
                    rule=leader_calculation.rule,
                )
            self._record_bucket_tracker_transition(
                bucket_transition,
                commit.boundary.received_monotonic_ms,
            )
            if (
                bucket_transition.newly_confirmed is not None
                and bucket_transition.newly_confirmed.score_band is ScoreBand.HIGH
            ):
                activated_high_by_name[leader_name] = (
                    bucket_transition.newly_confirmed.episode_identity
                )

        self.score_packets = new_packets
        self.bucket_leader_by_key = new_bucket_leaders
        self.bucket_leader_coverage = new_bucket_coverages
        active_high_by_name = {
            candidate.episode.leader_instrument_name: candidate.episode
            for candidate in self.bucket_trackers.values()
            if candidate.episode is not None and candidate.episode.score_band is ScoreBand.HIGH
        }
        for name, compatibility in self.trackers.items():
            active = active_high_by_name.get(name)
            prepared_member = prepared_by_name.get(name)
            prior = self.results.get(name)
            known_current = (
                prepared_member.current.known_evaluation
                if prepared_member is not None
                else prior.known_evaluation
                if prior is not None
                else name in self.score_results
            )
            if active is not None:
                compatibility.state = TrackerState.ACTIVE
                compatibility.episode_id = active.episode_identity
                compatibility.activation_band_id = active.bucket_key.tte_band_id
                compatibility.activation_causal_seq = active.activation_causal_seq
                self._episode_last_trusted_ms[active.episode_identity] = (
                    commit.boundary.received_monotonic_ms
                )
            else:
                compatibility.episode_id = None
                compatibility.activation_band_id = None
                compatibility.activation_causal_seq = None
                compatibility.state = TrackerState.ARMED if known_current else TrackerState.UNKNOWN
            if prior is not None and name not in prepared_by_name:
                score_result = self.score_results.get(name)
                score_packet = self.score_packets.get(name)
                if (
                    prior.detector_state is not compatibility.detector_state
                    or prior.score_result != score_result
                    or prior.score_packet != score_packet
                ):
                    self.results[name] = replace(
                        prior,
                        detector_state=compatibility.detector_state,
                        transition=TrackerTransition(),
                        score_result=score_result,
                        score_packet=score_packet,
                    )

        evaluated: list[tuple[OptionInstrument, EvaluationResult, TrackerState, str | None]] = []
        for item in prepared:
            instrument = item.instrument
            name = instrument.instrument_name
            item_current = item.current
            compatibility = self.trackers[name]
            compatibility_transition = TrackerTransition(
                activated_episode_id=activated_high_by_name.get(name),
                state_changed=(
                    item.previous_tracker_state is not compatibility.state
                    or item.previous_episode_id != compatibility.episode_id
                ),
            )
            if item_current.score_result is not None:
                self._last_observation_identity[name] = item.observation_identity
            elif name not in self._ticker_currentness_latches and item_current.reason not in {
                "TICKER_SOURCE_STALE",
                "TICKER_TIMESTAMP_AHEAD",
            }:
                self._last_observation_identity.pop(name, None)
            if item.index_tail_identity is None:
                self._last_index_tail_identity.pop(name, None)
            else:
                self._last_index_tail_identity[name] = item.index_tail_identity
            evaluation_result = EvaluationResult(
                detector_state=compatibility.detector_state,
                reason=item_current.reason,
                known_evaluation=item_current.known_evaluation,
                full_formula_evaluation=item_current.full_formula_evaluation,
                band_id=item_current.band_id,
                transition=compatibility_transition,
                observation_eligible=item.observation_eligible,
                observation_reason=(None if item.observation_eligible else commit.cause.value),
                calculation=item_current.calculation,
                current_evaluation=item_current,
                score_result=item_current.score_result,
                score_packet=self.score_packets.get(name),
            )
            self.results[name] = evaluation_result
            if item_current.reason is not None and not item_current.known_evaluation:
                self._record_unknown(name, item_current.reason)
            else:
                self._last_unknown_reason[name] = None
            evaluated.append(
                (
                    instrument,
                    evaluation_result,
                    item.previous_tracker_state,
                    item.previous_episode_id,
                )
            )
        return evaluated

    def _record_bucket_tracker_transition(
        self,
        transition: RadarBucketTrackerTransition,
        monotonic_ms: int,
    ) -> None:
        reset_reason = transition.confirmation_reset_reason
        if reset_reason is not None:
            self._confirmation_reset_counts[reset_reason.value] += 1
        self._record_bucket_episode_end(transition.ended, monotonic_ms)

    def _record_bucket_episode_end(
        self,
        ended: RadarBucketEpisodeEnd | None,
        monotonic_ms: int,
    ) -> None:
        if ended is None or ended.episode.score_band is not ScoreBand.HIGH:
            return
        reason = {
            BucketEpisodeEndReason.SCORE_BAND_CHANGE: EpisodeEndReason.CLEAR,
            BucketEpisodeEndReason.CORE_UNKNOWN: EpisodeEndReason.UNKNOWN_DETECTOR,
            BucketEpisodeEndReason.SCOPE_LOSS: EpisodeEndReason.MEMBERSHIP_LOSS,
            BucketEpisodeEndReason.STOP: EpisodeEndReason.CENSORED_AT_STOP,
            BucketEpisodeEndReason.LEADER_CHANGE: EpisodeEndReason.KNOWN_INELIGIBLE,
        }[ended.reason]
        self._record_episode_end(
            EpisodeEnd(
                episode_id=ended.episode.episode_identity,
                reason=reason,
                detail=ended.detail,
                end_causal_seq=ended.end_causal_seq,
                activation_band_id=ended.episode.bucket_key.tte_band_id,
            ),
            monotonic_ms,
        )

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
            result.detector_state
            if result is not None and result.band_id == band_id
            else DetectorState.UNKNOWN
            for _candidate, result in snapshot.scope_results
        )
        counter = self._scope_counter(
            instrument.option_type,
            band_id,
        )
        counter.applicable_instrument_count = max(
            counter.applicable_instrument_count,
            len(snapshot.scope_results),
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
                candidate
                for candidate, result in snapshot.scope_results
                if result is not None
                and result.band_id == band_id
                and result.full_formula_evaluation
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
        activation_causal_seq: int,
    ) -> None:
        episode_id = result.transition.activated_episode_id
        calculation = result.calculation
        if episode_id is None or calculation is None:
            raise RuntimeError("activation lacks its full calculation")
        counter = self._scope_counter(instrument.option_type, calculation.band.band_id)
        counter.record_candidate_activation(activation_causal_seq)
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
        self.event_sink.record_anomaly(event)

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
        self.event_sink.retire_episode(ended.episode_id)
        self._emitted_atomic_quotes = {
            key for key in self._emitted_atomic_quotes if key[0] != ended.episode_id
        }
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
        bucket_key = self.score_bucket_keys.get(instrument_name)
        bucket_tracker = self.bucket_trackers.get(bucket_key) if bucket_key is not None else None
        if (
            bucket_key is not None
            and bucket_tracker is not None
            and (
                bucket_tracker.frozen_instrument_name == instrument_name
                or self.bucket_leader_by_key.get(bucket_key) == instrument_name
            )
        ):
            bucket_transition = bucket_tracker.core_unknown(
                causal_seq=boundary.causal_seq,
                reason=reason,
            )
            self._record_bucket_tracker_transition(
                bucket_transition,
                boundary.received_monotonic_ms,
            )
        tracker.state = TrackerState.UNKNOWN
        tracker.episode_id = None
        tracker.activation_band_id = None
        tracker.activation_causal_seq = None
        transition = TrackerTransition(state_changed=True)
        self.score_results.pop(instrument_name, None)
        self.score_packets.pop(instrument_name, None)
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
            score_result=None,
            score_packet=None,
        )
        if instrument_name not in self._ticker_currentness_latches:
            self._last_observation_identity.pop(instrument_name, None)
        self._last_index_tail_identity.pop(instrument_name, None)
        self._record_unknown(instrument_name, reason)

    def _transition_coverage(
        self,
        state: CoverageState,
        *,
        commit: CausalCommit,
        causal_effect: CausalEffect | None = None,
        affected_scopes: tuple[str, ...] | None = None,
        blocking_reason: str,
        blocking_groups: tuple[CoverageBlockingGroup, ...] | None = None,
        force: bool = False,
    ) -> None:
        self._coverage.transition(
            state,
            commit=commit,
            causal_effect=causal_effect,
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
            blocking_groups=blocking_groups,
            global_continuity_epoch=self._global_continuity_epoch,
            force=force,
        )

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
        bucket_tracker = next(
            (
                candidate
                for candidate in self.bucket_trackers.values()
                if candidate.episode is not None
                and candidate.episode.episode_identity == tracker.episode_id
            ),
            None,
        )
        if bucket_tracker is None:
            return None
        return self._freeze_bucket_scope_snapshot(bucket_tracker, commit=commit)

    def active_radar_scope_snapshots(
        self,
        *,
        commit: CausalCommit,
    ) -> tuple[AtomicScopeSnapshot, ...]:
        return tuple(
            snapshot
            for tracker in self.bucket_trackers.values()
            if (snapshot := self._freeze_bucket_scope_snapshot(tracker, commit=commit)) is not None
        )

    def active_radar_score_packet(
        self,
        *,
        episode_identity: str,
        boundary: FactBoundary,
    ) -> RadarScorePacket | None:
        tracker = next(
            (
                candidate
                for candidate in self.bucket_trackers.values()
                if candidate.episode is not None
                and candidate.episode.episode_identity == episode_identity
            ),
            None,
        )
        if tracker is None or tracker.episode is None:
            return None
        packet = self.score_packets.get(tracker.episode.leader_instrument_name)
        if packet is None:
            return None
        if dict(packet.fact_boundary) != self._radar_packet_fact_boundary(boundary):
            return None
        return packet

    def _radar_packet_fact_boundary(
        self,
        boundary: FactBoundary,
    ) -> dict[str, object]:
        return {
            "code_identity": self.code_identity,
            "runtime_identity": self.runtime_identity,
            **_fact_boundary_object(boundary),
        }

    def _freeze_bucket_scope_snapshot(
        self,
        tracker: RadarBucketEpisodeTracker,
        *,
        commit: CausalCommit,
    ) -> AtomicScopeSnapshot | None:
        episode = tracker.episode
        if episode is None:
            return None
        episode_identity = episode.episode_identity
        anomaly_activation_seq = episode.activation_causal_seq
        activation_band_id = episode.bucket_key.tte_band_id
        short_leg = self.options.get(episode.leader_instrument_name)
        activation_packet = episode.activation_packet
        score_packet = (
            activation_packet
            if dict(activation_packet.fact_boundary)
            == self._radar_packet_fact_boundary(commit.boundary)
            else self.score_packets.get(episode.leader_instrument_name)
        )
        if (
            short_leg is None
            or score_packet is None
            or dict(score_packet.fact_boundary) != self._radar_packet_fact_boundary(commit.boundary)
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
            anomaly_active=episode.score_band is ScoreBand.HIGH,
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
        current_result = self.results.get(episode.leader_instrument_name)
        return AtomicScopeSnapshot(
            commit=commit,
            episode_identity=episode_identity,
            anomaly_activation_seq=anomaly_activation_seq,
            activation_band_id=activation_band_id,
            score_band=episode.score_band,
            radar_score_packet=score_packet,
            detector_state=(
                DetectorState.ANOMALY_ACTIVE
                if episode.score_band is ScoreBand.HIGH
                else DetectorState.NO_ANOMALY
            ),
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
            self.event_sink.record_atomic(event)
            self._emitted_atomic_quotes.add(emitted_key)

    def _sync_combo_subscriptions(self, boundary: FactBoundary) -> None:
        adapter = self.shadow_adapter
        needed: set[str] = (
            set(
                _call_shadow(
                    "required combo projection",
                    lambda: adapter.required_combo_instrument_names,
                )
            )
            if adapter is not None
            else set()
        )
        if any(not isinstance(name, str) or not name for name in needed):
            raise TypeError("Shadow required combo names must be non-empty strings")
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
            blocking_reason = (
                CoverageBlockingReason.CLOCK_GAP.value
                if commit.cause is CausalCause.CLOCK_GAP
                else CoverageBlockingReason.CLOCK_UNAVAILABLE.value
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=blocking_reason,
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
            blocking_reason = (
                self._bounded_coverage_blocking_reason(self.platform.reason)
                if not self.platform.usable
                else CoverageBlockingReason.OPTION_CATALOG_INCOMPLETE.value
            )
            self._transition_coverage(
                CoverageState.KNOWN_DEGRADED if positive else CoverageState.UNKNOWN,
                commit=commit,
                affected_scopes=("GLOBAL",),
                blocking_reason=blocking_reason,
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
        blocking_groups = self._current_scope_blocking_groups(scoped_keys)
        if unresolved_names:
            blocking_groups = self._merge_coverage_blocking_groups(
                blocking_groups,
                (
                    CoverageBlockingGroup(
                        CoverageBlockingReason.TIME_APPLICABILITY_UNRESOLVED.value,
                        self._option_local_coverage_scopes(tuple(unresolved_names)),
                    ),
                ),
            )
        if state is CoverageState.KNOWN_COMPLETE:
            blocking_reason = CoverageBlockingReason.NONE.value
            affected_scopes = self._coverage_scope_labels(scoped_keys)
            blocking_groups = ()
        else:
            if not blocking_groups:
                blocking_groups = (
                    CoverageBlockingGroup(
                        CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value,
                        self._coverage_scope_labels(scoped_keys),
                    ),
                )
            blocking_reason, affected_scopes = self._coverage_blocking_summary(blocking_groups)
        self._transition_coverage(
            state,
            commit=commit,
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
            blocking_groups=blocking_groups,
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

    @staticmethod
    def _summarize_scope_labels(scopes: set[str]) -> tuple[str, ...]:
        return _summarize_coverage_scope_labels(scopes)

    @classmethod
    def _merge_coverage_blocking_groups(
        cls,
        *collections: tuple[CoverageBlockingGroup, ...],
    ) -> tuple[CoverageBlockingGroup, ...]:
        scopes_by_reason: dict[str, set[str]] = {}
        for groups in collections:
            for group in groups:
                scopes_by_reason.setdefault(group.blocking_reason, set()).update(
                    group.affected_scopes
                )
        return tuple(
            CoverageBlockingGroup(reason, cls._summarize_scope_labels(scopes))
            for reason, scopes in sorted(scopes_by_reason.items())
        )

    @staticmethod
    def _coverage_blocking_summary(
        groups: tuple[CoverageBlockingGroup, ...],
    ) -> tuple[str, tuple[str, ...]]:
        return _coverage_blocking_group_summary(groups)

    def _current_scope_blocking_groups(
        self,
        scoped_keys: set[tuple[int, OptionType, str]],
    ) -> tuple[CoverageBlockingGroup, ...]:
        candidates = tuple(
            (name, self._bounded_coverage_blocking_reason(result.reason))
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
        option_local_blockers = {
            CoverageBlockingReason.TICKER_SOURCE_STALE.value,
            CoverageBlockingReason.TICKER_TIMESTAMP_AHEAD.value,
            CoverageBlockingReason.OPTION_LIFECYCLE_UNAVAILABLE.value,
            CoverageBlockingReason.OPTION_BOOK_UNAVAILABLE.value,
        }
        groups: list[CoverageBlockingGroup] = []
        for reason in sorted({reason for _, reason in candidates}):
            selected_names = tuple(
                sorted(name for name, candidate_reason in candidates if candidate_reason == reason)
            )
            scopes: tuple[str, ...]
            if reason in global_blockers:
                scopes = ("GLOBAL",)
            elif reason == CoverageBlockingReason.INDEX_WINDOW_GAP.value:
                matching_scopes = {
                    (
                        self.options[name].expiration_timestamp_ms,
                        self.options[name].option_type,
                        self.results[name].band_id,
                    )
                    for name in selected_names
                    if self.results[name].band_id is not None
                }
                scopes = self._coverage_scope_labels(
                    {
                        (expiry, option_type, cast(str, band_id))
                        for expiry, option_type, band_id in matching_scopes
                    }
                )
            elif reason in option_local_blockers and selected_names:
                scopes = self._option_local_coverage_scopes(selected_names)
            else:
                matching_scopes = {
                    (
                        self.options[name].expiration_timestamp_ms,
                        self.options[name].option_type,
                        self.results[name].band_id,
                    )
                    for name in selected_names
                    if self.results[name].band_id is not None
                }
                scopes = self._coverage_scope_labels(
                    {
                        (expiry, option_type, cast(str, band_id))
                        for expiry, option_type, band_id in matching_scopes
                    }
                    or scoped_keys
                )
            groups.append(CoverageBlockingGroup(reason, scopes))
        return tuple(groups)

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
        self.begin_runtime_barrier(retired_ms)
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
        self.accepted_platform_continuity_boundary = None
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
            self._early_rpc_responses.clear()
        for request in tuple(self.pending_rpcs.values()):
            transitioned = self._finish_rpc(
                request,
                state=RpcState.RETIRED,
                terminal_monotonic_ms=retired_ms,
                record_latency=False,
            )
            if transitioned and request.purpose in SHADOW_RPC_PURPOSES:
                self._apply_request_failure(
                    request,
                    terminal_state=RpcState.RETIRED,
                )
        self.pending_rpcs.clear()
        self._update_band_suspension(retired_ms)
        self._transition_coverage(
            CoverageState.UNKNOWN,
            commit=commit,
            blocking_reason=commit.cause.value,
        )
        self._settle_shadow_transaction(
            CausalCommit(
                boundary=boundary,
                cause=commit.cause,
                failure_domain=commit.failure_domain,
                affected_scopes=commit.affected_scopes,
            ),
            sync_combo_subscriptions=False,
        )

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

    @property
    def current_session_epoch(self) -> int | None:
        return self._session_epoch

    @property
    def last_boundary_monotonic_ms(self) -> int:
        return self._last_boundary_monotonic_ms

    @property
    def last_wire_received_monotonic_ms(self) -> int:
        return self._last_wire_received_ms

    @property
    def queue_lag_currentness_active(self) -> bool:
        return self._queue_lag_currentness_active

    @property
    def current_coverage_state(self) -> CoverageState:
        return self._coverage.current_state

    @property
    def current_coverage_blocking_reason(self) -> str:
        return self._coverage.current_blocking_reason

    @property
    def current_coverage_affected_scopes(self) -> tuple[str, ...]:
        return self._coverage.current_affected_scopes

    @property
    def current_global_continuity_epoch(self) -> int:
        return self._global_continuity_epoch

    @property
    def latest_funnel_causal_seq(self) -> int:
        return self._latest_funnel_causal_seq

    @property
    def latest_funnel_evaluations(self) -> tuple[RadarFunnelEvaluation, ...]:
        return self._latest_funnel_evaluations

    @property
    def confirmation_reset_counts(self) -> Mapping[str, int]:
        return self._confirmation_reset_counts

    @property
    def current_diagnostic_tickers(self) -> dict[str, TickerState]:
        """Return only tickers whose source currentness was settled as CURRENT."""
        return {
            name: settled.ticker
            for name, settled in self._settled_ticker_currentness.items()
            if settled.state is TickerAcceptedCurrentness.CURRENT and settled.ticker is not None
        }

    @property
    def current_index_price_usdc_per_btc(self) -> Decimal | None:
        receipt = self.accepted_index_receipt
        if receipt is None or not self.platform.usable or self.clock is None:
            return None
        try:
            trusted = self.clock.interval_at(self._last_boundary_monotonic_ms)
        except (ContinuityGap, ValueError):
            return None
        if (
            trusted.lower_ms - receipt.source_timestamp_ms
            > self.policy.runtime_limits.index_source_stale_deadline_ms
        ):
            return None
        return receipt.price_usdc_per_btc

    def episode_started_monotonic_ms(self, episode_identity: str) -> int | None:
        return self._episode_started_ms.get(episode_identity)

    def episode_active_duration_ms(
        self,
        episode_identity: str,
        *,
        observed_monotonic_ms: int,
    ) -> int | None:
        started = self._episode_started_ms.get(episode_identity)
        if started is None:
            return None
        paused = self._episode_paused_duration_ms[episode_identity]
        pause_started = self._episode_pause_started_ms.get(episode_identity)
        if pause_started is not None:
            paused += max(0, observed_monotonic_ms - pause_started)
        return max(0, observed_monotonic_ms - started - paused)

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
            self._early_rpc_responses.pop(request.request_id, None)
            self._finish_rpc(
                request,
                state=RpcState.DEADLINE_LATE,
                terminal_monotonic_ms=monotonic_ms,
                record_latency=False,
                allow_unsent=(lifecycle.state is RpcState.SCHEDULED),
            )
            self._apply_request_failure(
                request,
                terminal_state=RpcState.DEADLINE_LATE,
            )
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
            self._next_clock_refresh_ms = (
                monotonic_ms + self.policy.runtime_limits.clock_refresh_interval_ms
            )
        if (
            self._next_index_history_refresh_ms is not None
            and monotonic_ms >= self._next_index_history_refresh_ms
            and not any(
                request.purpose is RpcPurpose.INDEX_HISTORY
                for request in self.pending_rpcs.values()
            )
        ):
            self._schedule_index_history_refresh(boundary)
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
            self._schedule_combo_refresh(boundary)
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

    def clean_stop(self, monotonic_ms: int) -> Mapping[str, object]:
        if monotonic_ms < self._last_boundary_monotonic_ms:
            raise RuntimeError("clean-stop boundary precedes an accepted application boundary")
        self.begin_runtime_barrier(monotonic_ms, terminal=True)
        self._last_boundary_monotonic_ms = monotonic_ms
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
        for bucket_tracker in self.bucket_trackers.values():
            transition = bucket_tracker.stop(causal_seq=self._causal_seq)
            self._record_bucket_tracker_transition(transition, monotonic_ms)
        for compatibility in self.trackers.values():
            compatibility.state = TrackerState.UNKNOWN
            compatibility.episode_id = None
            compatibility.activation_band_id = None
            compatibility.activation_causal_seq = None
        if self._early_rpc_responses:
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
        )
        try:
            settled_summary = self.event_sink.record_summary(summary)
        except Exception:
            try:
                self._terminate_shadow(source="FAILURE", boundary=boundary)
            except Exception:
                pass
            raise
        self._terminate_shadow(source="STOP", boundary=boundary)
        return settled_summary

    def finalize_shadow_failure(self, monotonic_ms: int) -> None:
        if self.shadow_adapter is None or self._shadow_terminalized:
            return
        if monotonic_ms < self._last_boundary_monotonic_ms:
            raise RuntimeError("failure boundary precedes an accepted application boundary")
        self.begin_runtime_barrier(monotonic_ms, terminal=True)
        self._last_boundary_monotonic_ms = monotonic_ms
        self._causal_seq += 1
        boundary = FactBoundary(
            self._session_epoch or 1,
            self._last_ingress_seq,
            self._last_boundary_monotonic_ms,
            self._causal_seq,
        )
        for request in tuple(self.pending_rpcs.values()):
            self._finish_rpc(
                request,
                state=RpcState.CENSORED,
                terminal_monotonic_ms=monotonic_ms,
                record_latency=False,
            )
        self.pending_rpcs.clear()
        self._terminate_shadow(source="FAILURE", boundary=boundary)

    def _terminate_shadow(self, *, source: str, boundary: FactBoundary) -> None:
        adapter = self.shadow_adapter
        if adapter is None or self._shadow_terminalized:
            return
        if source not in {"STOP", "FAILURE"}:
            raise ValueError("Shadow terminal source must be STOP or FAILURE")
        _call_shadow(
            f"{source} terminal",
            lambda: adapter.terminate(source=source, boundary=boundary),
        )
        self._shadow_terminalized = True


class CoverageTracker:
    def __init__(
        self,
        started_monotonic_ms: int,
        *,
        initial_commit: CausalCommit,
    ) -> None:
        if initial_commit.boundary.received_monotonic_ms != started_monotonic_ms:
            raise ValueError("initial coverage commit must match the coverage start")
        if initial_commit.cause is not CausalCause.RUNTIME_START:
            raise ValueError("initial coverage commit cause must be RUNTIME_START")
        self._current_state = CoverageState.UNKNOWN
        self._current_start_ms = started_monotonic_ms
        self._current_trigger_cause = initial_commit.cause.value
        self._current_blocking_reason = CoverageBlockingReason.RUNTIME_START_PENDING.value
        self._current_affected_scopes = initial_commit.affected_scopes
        self._current_blocking_groups: tuple[CoverageBlockingGroup, ...] = (
            CoverageBlockingGroup(
                CoverageBlockingReason.RUNTIME_START_PENDING.value,
                initial_commit.affected_scopes,
            ),
        )
        self._current_global_continuity_epoch = 1
        self._segments: list[CoverageSegment] = []

    @property
    def current_state(self) -> CoverageState:
        return self._current_state

    @property
    def current_blocking_reason(self) -> str:
        return self._current_blocking_reason

    @property
    def current_affected_scopes(self) -> tuple[str, ...]:
        return self._current_affected_scopes

    def transition(
        self,
        state: CoverageState,
        *,
        commit: CausalCommit,
        causal_effect: CausalEffect | None = None,
        affected_scopes: tuple[str, ...] | None = None,
        blocking_reason: str,
        blocking_groups: tuple[CoverageBlockingGroup, ...] | None = None,
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
        resolved_blocking_groups = (
            blocking_groups
            if blocking_groups is not None
            else (
                ()
                if state is CoverageState.KNOWN_COMPLETE
                else (CoverageBlockingGroup(blocking_reason, resolved_affected_scopes),)
            )
        )
        for group in resolved_blocking_groups:
            try:
                CoverageBlockingReason(group.blocking_reason)
            except ValueError as exc:
                raise ValueError(
                    "coverage blocking group reason is outside the bounded allowlist"
                ) from exc
            _validate_causal_scopes(group.affected_scopes)
        if len(resolved_blocking_groups) > 256:
            raise ValueError("coverage blocking groups cannot exceed 256")
        if tuple(
            sorted(
                resolved_blocking_groups,
                key=lambda group: (group.blocking_reason, group.affected_scopes),
            )
        ) != resolved_blocking_groups or len(
            {group.blocking_reason for group in resolved_blocking_groups}
        ) != len(resolved_blocking_groups):
            raise ValueError("coverage blocking groups must be sorted with unique reasons")
        if state is CoverageState.KNOWN_COMPLETE:
            if resolved_blocking_groups or blocking_reason != CoverageBlockingReason.NONE.value:
                raise ValueError("KNOWN_COMPLETE coverage cannot have blocking groups")
        elif not resolved_blocking_groups:
            raise ValueError("incomplete coverage must have at least one blocking group")
        else:
            forbidden_group_reasons = {CoverageBlockingReason.NONE.value}
            if any(
                group.blocking_reason in forbidden_group_reasons
                for group in resolved_blocking_groups
            ):
                raise ValueError("coverage blocking group uses a synthetic or empty reason")
            expected_reason, expected_scopes = _coverage_blocking_group_summary(
                resolved_blocking_groups
            )
            if blocking_reason != expected_reason:
                raise ValueError("coverage blocking_reason must summarize blocking groups")
            if resolved_affected_scopes != expected_scopes:
                raise ValueError("coverage affected_scopes must summarize blocking groups")
            if state is CoverageState.NO_APPLICABLE_SCOPE and (
                len(resolved_blocking_groups) != 1
                or resolved_blocking_groups[0].blocking_reason
                != CoverageBlockingReason.NO_APPLICABLE_SCOPE.value
            ):
                raise ValueError(
                    "NO_APPLICABLE_SCOPE coverage must have one matching blocking group"
                )
        same_coverage_semantics = (
            state is self._current_state
            and resolved_blocking_groups == self._current_blocking_groups
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
                    blocking_groups=self._current_blocking_groups,
                )
            )
        self._current_start_ms = monotonic_ms
        self._current_state = state
        self._current_trigger_cause = commit.cause.value
        self._current_blocking_reason = blocking_reason
        self._current_affected_scopes = resolved_affected_scopes
        self._current_blocking_groups = resolved_blocking_groups
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
                    blocking_groups=self._current_blocking_groups,
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
        event_sink: RadarEventSink,
        runtime_identity: str | None = None,
        product: OptionProductSpec = INVERSE_BTC,
        shadow_adapter: ShadowRuntimeAdapter | None = None,
        snapshot_publisher: SettledSnapshotPublisher | None = None,
    ) -> None:
        identity = runtime_identity or str(uuid.uuid4())
        self.reducer = RadarReducer(
            policy=policy,
            code_identity=code_identity,
            event_sink=event_sink,
            runtime_identity=identity,
            product=product,
            shadow_adapter=shadow_adapter,
            snapshot_publisher=snapshot_publisher,
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
    def event_sink(self) -> RadarEventSink:
        return self.reducer.event_sink

    @property
    def platform(self) -> PlatformReadiness:
        return self.reducer.platform

    @property
    def session_established(self) -> bool:
        return self.reducer.session_established

    @property
    def shadow_terminalized(self) -> bool:
        return self.reducer._shadow_terminalized

    async def run(
        self,
        client: PublicClient,
        stop_event: asyncio.Event,
    ) -> Mapping[str, object]:
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
        if not stop_event.is_set():
            self._enqueue_commands(outbound, commands)
        poll_ms = self.policy.runtime_limits.time_boundary_poll_interval_ms
        next_poll_ms = started_monotonic_ms + poll_ms
        failure: BaseException | None = None
        try:
            while True:
                self._raise_sender_failure(sender_task)
                now_ms = _monotonic_ms()
                if stop_event.is_set():
                    break
                if buffered:
                    envelope = buffered[0]
                    envelope = buffered.popleft()
                    next_time_boundary_ms = self._next_runtime_time_boundary_ms(
                        next_poll_ms,
                    )
                    while next_time_boundary_ms < envelope.received_monotonic_ms:
                        self._enqueue_commands(
                            outbound,
                            self.reducer.advance_time(next_time_boundary_ms),
                        )
                        if next_time_boundary_ms == next_poll_ms:
                            next_poll_ms += poll_ms
                        next_time_boundary_ms = self._next_runtime_time_boundary_ms(
                            next_poll_ms,
                        )
                    self._enqueue_commands(
                        outbound,
                        self.reducer.reduce(
                            envelope,
                            processed_monotonic_ms=now_ms,
                        ),
                    )
                    await asyncio.sleep(0)
                    continue
                next_time_boundary_ms = self._next_runtime_time_boundary_ms(
                    next_poll_ms,
                )
                if now_ms >= next_time_boundary_ms:
                    self._enqueue_commands(
                        outbound,
                        self.reducer.advance_time(next_time_boundary_ms),
                    )
                    if next_time_boundary_ms == next_poll_ms:
                        next_poll_ms += poll_ms
                    await asyncio.sleep(0)
                    continue
                timeout_seconds = (next_time_boundary_ms - now_ms) / 1_000
                try:
                    received_envelope = await self._next_envelope_or_stop(
                        client,
                        stop_event,
                        timeout_seconds=timeout_seconds,
                    )
                except TimeoutError:
                    continue
                if received_envelope is not None:
                    buffered.append(received_envelope)
        except BaseException as exc:
            failure = exc

        clean_stop_requested = failure is None and stop_event.is_set()
        barrier_monotonic_ms = (
            self._stop_terminal_monotonic_ms(stop_event, _monotonic_ms())
            if clean_stop_requested
            else _monotonic_ms()
        )
        self.reducer.begin_runtime_barrier(
            barrier_monotonic_ms,
            terminal=clean_stop_requested,
        )
        try:
            await self._stop_client_intake(client)
        except BaseException as exc:
            if failure is None:
                failure = exc
        buffered.extend(self._drain_client_envelopes(client))
        barrier_frontier = self._barrier_frontier(
            client,
            buffered,
            barrier_monotonic_ms=barrier_monotonic_ms,
            exact_terminal_time=clean_stop_requested
            and self._has_stop_terminal_monotonic_ms(stop_event),
        )
        if self.reducer._session_epoch is not None:
            self.reducer.bind_runtime_barrier_frontier(
                session_epoch=client.session_epoch,
                ingress_seq=barrier_frontier,
            )

        sender_cancelled_by_barrier = False
        if not sender_task.done():
            sender_cancelled_by_barrier = True
            sender_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            if not sender_cancelled_by_barrier and failure is None:
                failure = PublicSessionError("outbound sender cancelled unexpectedly")
        except BaseException as exc:
            if failure is None:
                failure = exc

        buffered.extend(self._drain_client_envelopes(client))
        while buffered:
            envelope = buffered.popleft()
            try:
                next_time_boundary_ms = self._next_runtime_time_boundary_ms(
                    next_poll_ms,
                )
                while (
                    next_time_boundary_ms < envelope.received_monotonic_ms
                    and next_time_boundary_ms <= barrier_monotonic_ms
                ):
                    self.reducer.advance_time(next_time_boundary_ms)
                    if next_time_boundary_ms == next_poll_ms:
                        next_poll_ms += poll_ms
                    next_time_boundary_ms = self._next_runtime_time_boundary_ms(
                        next_poll_ms,
                    )
                self.reducer.reduce(
                    envelope,
                    processed_monotonic_ms=max(
                        _monotonic_ms(),
                        envelope.received_monotonic_ms,
                    ),
                )
                await asyncio.sleep(0)
            except BaseException as exc:
                if failure is None:
                    failure = exc
        try:
            self.reducer.settle_barrier_deadlines(barrier_monotonic_ms)
        except BaseException as exc:
            if failure is None:
                failure = exc

        while True:
            try:
                outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                outbound.task_done()

        publisher = self.reducer.snapshot_publisher
        if publisher is not None:
            try:
                publisher.flush_pending()
            except BaseException as exc:
                if failure is None:
                    failure = exc
        if failure is not None:
            reconnect_reason = (
                failure.reason
                if isinstance(failure, _SessionReconnectRequired)
                else type(failure).__name__
            )
            self.reducer.prepare_reconnect(reconnect_reason)
            raise failure.with_traceback(failure.__traceback__)
        return self.reducer.clean_stop(barrier_monotonic_ms)

    def finalize_shadow_failure(self, monotonic_ms: int) -> None:
        self.reducer.finalize_shadow_failure(monotonic_ms)

    def _next_runtime_time_boundary_ms(self, next_poll_ms: int) -> int:
        shadow_boundary_ms = self.reducer.next_shadow_time_boundary_monotonic_ms(
            after_monotonic_ms=self.reducer._last_boundary_monotonic_ms,
        )
        return next_poll_ms if shadow_boundary_ms is None else min(next_poll_ms, shadow_boundary_ms)

    @staticmethod
    def _has_stop_terminal_monotonic_ms(stop_event: asyncio.Event) -> bool:
        return getattr(stop_event, "terminal_monotonic_ms", None) is not None

    @staticmethod
    def _stop_terminal_monotonic_ms(
        stop_event: asyncio.Event,
        fallback_monotonic_ms: int,
    ) -> int:
        value = getattr(stop_event, "terminal_monotonic_ms", None)
        if value is None:
            return fallback_monotonic_ms
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("stop terminal monotonic time must be a non-negative integer")
        return value

    def _barrier_frontier(
        self,
        client: PublicClient,
        buffered: deque[InboundEnvelope],
        *,
        barrier_monotonic_ms: int,
        exact_terminal_time: bool,
    ) -> int:
        frontier = self.reducer._last_ingress_seq
        if exact_terminal_time:
            for envelope in buffered:
                if envelope.ingress_seq != frontier + 1:
                    break
                if envelope.received_monotonic_ms >= barrier_monotonic_ms:
                    break
                frontier = envelope.ingress_seq
            return frontier
        enqueued = getattr(client, "enqueued_envelope_count", None)
        if isinstance(enqueued, int) and not isinstance(enqueued, bool) and enqueued >= frontier:
            return enqueued
        return max(
            (envelope.ingress_seq for envelope in buffered),
            default=frontier,
        )

    @staticmethod
    async def _next_envelope_or_stop(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        timeout_seconds: float,
    ) -> InboundEnvelope | None:
        envelope_task = asyncio.create_task(client.next_envelope(timeout_seconds=timeout_seconds))
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {envelope_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if envelope_task in done:
            return await envelope_task
        return None

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
        lifecycle = self.reducer._rpc_lifecycles.get(command.request_id)
        if command.purpose in SHADOW_RPC_PURPOSES and (
            self.reducer.pending_rpcs.get(command.request_id) != command
            or lifecycle is None
            or lifecycle.state is not RpcState.SCHEDULED
        ):
            return
        try:
            remaining_ms = command.send_deadline_monotonic_ms - _monotonic_ms()
            if remaining_ms <= 0:
                raise TimeoutError("RPC send deadline expired before transport send")
            async with asyncio.timeout(remaining_ms / 1_000):
                await client.send_request(
                    request_id=command.request_id,
                    method=command.method,
                    params=command.params,
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

    def prepare_reconnect(self, reason: str) -> None:
        self.reducer.prepare_reconnect(reason)


def _merge_causal_scopes(*scope_groups: tuple[str, ...]) -> tuple[str, ...]:
    scopes = {scope for group in scope_groups for scope in group}
    if "GLOBAL" in scopes:
        return ("GLOBAL",)
    if "OPTION_LOCAL" in scopes or len(scopes) > 256:
        return ("OPTION_LOCAL",)
    return tuple(sorted(scopes))


def _summarize_coverage_scope_labels(scopes: set[str]) -> tuple[str, ...]:
    if "GLOBAL" in scopes:
        return ("GLOBAL",)
    if "OPTION_LOCAL" in scopes:
        if all(scope == "OPTION_LOCAL" or scope.startswith("OPTION:") for scope in scopes):
            return ("OPTION_LOCAL",)
        return ("GLOBAL",)
    ordered = tuple(sorted(scopes))
    if len(ordered) <= 256:
        return ordered
    if all(scope.startswith("OPTION:") for scope in ordered):
        return ("OPTION_LOCAL",)
    return ("GLOBAL",)


def _coverage_blocking_group_summary(
    groups: tuple[CoverageBlockingGroup, ...],
) -> tuple[str, tuple[str, ...]]:
    reason = (
        groups[0].blocking_reason
        if len(groups) == 1
        else CoverageBlockingReason.CURRENT_SCOPE_INCOMPLETE.value
    )
    scopes = _summarize_coverage_scope_labels(
        {scope for group in groups for scope in group.affected_scopes}
    )
    return reason, scopes


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


def _source_name_for_channel(
    channel: str,
    *,
    combo_names: set[str],
    product: OptionProductSpec,
) -> str:
    if channel in PLATFORM_CHANNELS:
        return channel
    if channel == product.option_lifecycle_channel:
        return "option_lifecycle"
    if channel == product.combo_lifecycle_channel:
        return "combo_lifecycle"
    if channel == product.index_channel:
        return "index"
    if channel.startswith("ticker."):
        return "option_ticker"
    if channel.startswith("book."):
        instrument_name = _instrument_from_channel(channel)
        if instrument_name in combo_names:
            return "combo_book"
        return "option_book"
    return ""


def _instrument_from_channel(channel: str) -> str | None:
    if channel.startswith("ticker.") and channel.endswith(".agg2"):
        return channel[len("ticker.") : -len(".agg2")]
    if channel.startswith("book.") and channel.endswith(".agg2"):
        return channel[len("book.") : -len(".agg2")]
    return None


def _is_target_option_product(payload: object, product: OptionProductSpec) -> bool:
    data = require_mapping(payload, "instrument")
    actual = {
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
    }
    return actual == product.product_fields(kind="option")


def _is_target_option_instrument_name(
    instrument_name: str,
    product: OptionProductSpec,
) -> bool:
    return product.matches_instrument_name(instrument_name)


def _is_target_option_lifecycle(payload: object, product: OptionProductSpec) -> bool:
    data = require_mapping(payload, "option lifecycle")
    instrument_name = require_str(
        data.get("instrument_name"),
        "option lifecycle.instrument_name",
    )
    require_str(data.get("state"), "option lifecycle.state")
    return _is_target_option_instrument_name(instrument_name, product)


def _is_valid_irrelevant_option_metadata(
    payload: object,
    expected_name: str,
    target: OptionProductSpec,
) -> bool:
    try:
        data = require_mapping(payload, "instrument")
        if require_str(data.get("instrument_name"), "instrument.instrument_name") != expected_name:
            return False
        product = {
            "kind": require_str(data.get("kind"), "instrument.kind"),
            "base_currency": require_str(data.get("base_currency"), "instrument.base_currency"),
            "quote_currency": require_str(data.get("quote_currency"), "instrument.quote_currency"),
            "settlement_currency": require_str(
                data.get("settlement_currency"), "instrument.settlement_currency"
            ),
            "counter_currency": require_str(
                data.get("counter_currency"), "instrument.counter_currency"
            ),
            "price_index": require_str(data.get("price_index"), "instrument.price_index"),
            "instrument_type": require_str(
                data.get("instrument_type"), "instrument.instrument_type"
            ),
        }
        require_bool(data.get("is_active"), "instrument.is_active")
        require_str(data.get("state"), "instrument.state")
    except SourceDataError:
        return False
    return (
        product["kind"] == "option"
        and product != target.product_fields(kind="option")
        and product["quote_currency"] == target.quote_currency
        and product["settlement_currency"] == target.settlement_currency
        and product["instrument_type"] == target.instrument_type
    )


def _is_explicit_final_target_option_metadata(
    payload: object,
    expected_name: str,
    product: OptionProductSpec,
) -> bool:
    try:
        data = require_mapping(payload, "instrument")
        if require_str(data.get("instrument_name"), "instrument.instrument_name") != expected_name:
            return False
        if not _is_target_option_product(data, product):
            return False
        require_bool(data.get("is_active"), "instrument.is_active")
        state = require_str(data.get("state"), "instrument.state")
    except SourceDataError:
        return False
    return state in FINAL_INSTRUMENT_LIFECYCLE_STATES


def _is_valid_irrelevant_combo_metadata(
    payload: object,
    expected_name: str,
    target: OptionProductSpec,
) -> bool:
    try:
        data = require_mapping(payload, "combo metadata")
        if (
            require_str(data.get("instrument_name"), "combo metadata.instrument_name")
            != expected_name
        ):
            return False
        product = {
            "kind": require_str(data.get("kind"), "combo metadata.kind"),
            "base_currency": require_str(data.get("base_currency"), "combo metadata.base_currency"),
            "quote_currency": require_str(
                data.get("quote_currency"), "combo metadata.quote_currency"
            ),
            "settlement_currency": require_str(
                data.get("settlement_currency"), "combo metadata.settlement_currency"
            ),
            "counter_currency": require_str(
                data.get("counter_currency"), "combo metadata.counter_currency"
            ),
            "instrument_type": require_str(
                data.get("instrument_type"), "combo metadata.instrument_type"
            ),
        }
    except SourceDataError:
        return False
    return (
        product["kind"] == "option_combo"
        and product != target.combo_product_fields()
        and product["quote_currency"] == target.quote_currency
        and product["settlement_currency"] == target.settlement_currency
        and product["instrument_type"] == target.instrument_type
    )


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


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000

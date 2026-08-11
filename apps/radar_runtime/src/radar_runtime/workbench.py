from __future__ import annotations

import ipaddress
import json
import socket
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from typing import Protocol, cast

from market_monitor import ContinuityGap, TimeInterval
from options_domain import INVERSE_BTC, OptionProductSpec, product_for_identity
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import DetectorState
from short_vol_radar.evidence import CoverageBlockingReason, CoverageState
from short_vol_radar.radar import DetectorCalculation
from short_vol_radar.review import (
    DEFAULT_ATTENTION_TOP_N,
    ReviewContext,
    build_review_contexts,
)
from short_vol_underwriting.evidence import RuntimeBindings, ShadowStateStore
from short_vol_underwriting.identity import canonical_decimal, canonical_value
from short_vol_underwriting.policy import PolicyChain

from radar_runtime.funnel import FunnelSnapshot, FunnelTracker
from radar_runtime.runtime import CausalCommit, RadarReducer
from radar_runtime.workbench_frontend import CSS as CSS
from radar_runtime.workbench_frontend import HTML as HTML
from radar_runtime.workbench_frontend import JS as JS

WORKBENCH_SCHEMA_VERSION = 7
WORKBENCH_CHANNEL_ID = "INVERSE_BTC_SHORT_VOL_V2"
WORKBENCH_PUBLICATION_INTERVAL_MS = 500
SIMULATION_LABEL = "模拟入场, 不是订单或成交"
EMPTY_PANEL_LABEL = "无已结算对象; 这不是业务零值"
UNKNOWN_DENOMINATOR_LABEL = "UNKNOWN (分母未知或为零)"
WORKBENCH_NON_CLAIMS = (
    "READ_ONLY_OPERATIONAL_PROJECTION",
    "PUBLIC_QUOTE_NOT_FILL",
    "NO_PRIVATE_ACCOUNT_OR_ORDER_ACCESS",
    "THIS_ARTIFACT_DOES_NOT_GRANT_LIVE_OR_DEPLOYMENT_AUTHORITY",
)
_STALE_REASONS = frozenset(
    {
        CoverageBlockingReason.INDEX_SOURCE_STALE.value,
        CoverageBlockingReason.TICKER_SOURCE_STALE.value,
        CoverageBlockingReason.QUEUE_LAG_CURRENTNESS.value,
        CoverageBlockingReason.SESSION_LIVENESS_DEADLINE.value,
    }
)
_INTERRUPTED_REASONS = frozenset(
    {
        CoverageBlockingReason.SESSION_GAP.value,
        CoverageBlockingReason.REMOTE_CONNECTION_CLOSED.value,
        CoverageBlockingReason.TRANSPORT_READ_FAILURE.value,
        CoverageBlockingReason.SESSION_RPC_FAILURE.value,
        CoverageBlockingReason.RUNTIME_SESSION_FAILURE.value,
        CoverageBlockingReason.PROTOCOL_INCOMPATIBILITY.value,
        CoverageBlockingReason.INGRESS_GAP_OR_DUPLICATE.value,
        CoverageBlockingReason.QUEUE_OVERFLOW.value,
    }
)
_ENTRY_TRACKING_PAYLOAD_KEYS = frozenset(
    {
        "origin_runtime_identity",
        "current_segment_identity",
        "current_segment_sequence",
        "observation_quality",
        "gap_count",
        "qualification_eligible",
        "tracking_state",
        "post_close_attempt_state",
    }
)
_OBSERVATION_QUALITIES = frozenset({"CONTINUOUS", "GAPPED"})
_TRACKING_STATES = frozenset({"RECOVERING", "ACTIVE"})
_POST_CLOSE_ATTEMPT_STATES = frozenset(
    {
        "NOT_SCHEDULED",
        "SCHEDULED",
        "TERMINAL",
        "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS",
    }
)


class PanelState(StrEnum):
    HAS_SETTLED_OBJECTS = "HAS_SETTLED_OBJECTS"
    EMPTY_NO_SETTLED_OBJECT = "EMPTY_NO_SETTLED_OBJECT"


class ZeroClaimState(StrEnum):
    PROVEN_ZERO = "PROVEN_ZERO"
    NOT_ZERO = "NOT_ZERO"
    UNKNOWN = "UNKNOWN"


class ServicePhase(StrEnum):
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class DataState(StrEnum):
    CURRENT = "CURRENT"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    INTERRUPTED = "INTERRUPTED"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class ServiceStatus:
    phase: ServicePhase
    data_state: DataState
    health: bool
    ready: bool
    stale: bool
    reason: str
    recorded_monotonic_ms: int

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("service status reason must be non-empty")
        if self.recorded_monotonic_ms < 0:
            raise ValueError("service status monotonic time must be non-negative")
        if self.ready and (
            not self.health
            or self.phase is not ServicePhase.RUNNING
            or self.data_state is not DataState.CURRENT
        ):
            raise ValueError("ready service status must be healthy running current")
        if self.stale != (self.data_state is DataState.STALE):
            raise ValueError("stale flag must exactly match STALE data state")
        terminal_phase = self.phase in {ServicePhase.STOPPED, ServicePhase.FAILED}
        if terminal_phase and self.health:
            raise ValueError("terminal service phase cannot remain healthy")
        if (self.data_state is DataState.STOPPED) is not terminal_phase:
            raise ValueError("STOPPED data state must exactly match a terminal phase")


@dataclass(frozen=True)
class ZeroClaim:
    state: ZeroClaimState
    value: int | None
    numerator: int
    denominator: int | None
    explanation: str

    def as_object(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class PublishedSnapshot:
    sequence: int
    workbench_body: bytes
    health_body: bytes
    ready_body: bytes
    health: bool
    ready: bool


@dataclass(frozen=True)
class _DownstreamProjection:
    kinds: Mapping[str, Sequence[Mapping[str, object]]]
    underwriting_rows: Sequence[Mapping[str, object]]
    shadow_rows: Sequence[Mapping[str, object]]
    outcome_rows: Sequence[Mapping[str, object]]
    decision_control_rows: Sequence[Mapping[str, object]]
    underwriting_counts: Mapping[str, int]


class ShadowMetadataSource(Protocol):
    def workbench_option_metadata(self) -> tuple[Mapping[str, object], ...]: ...

    def workbench_underwriting_metadata(self) -> tuple[Mapping[str, object], ...]: ...


def panel_state(rows: Sequence[object]) -> PanelState:
    return PanelState.HAS_SETTLED_OBJECTS if rows else PanelState.EMPTY_NO_SETTLED_OBJECT


def zero_anomaly_claim(
    *,
    active_anomaly_count: int,
    monitor_denominator: int | None,
    monitor_complete: bool,
) -> ZeroClaim:
    _require_count(active_anomaly_count, "active_anomaly_count")
    if monitor_denominator is not None:
        _require_count(monitor_denominator, "monitor_denominator")
    if active_anomaly_count > 0:
        return ZeroClaim(
            ZeroClaimState.NOT_ZERO,
            active_anomaly_count,
            active_anomaly_count,
            monitor_denominator,
            "至少一个当前异常是已知正向事实; 不要求完整市场来证明其存在。",
        )
    if monitor_complete and monitor_denominator is not None and monitor_denominator > 0:
        return ZeroClaim(
            ZeroClaimState.PROVEN_ZERO,
            0,
            0,
            monitor_denominator,
            "当前非空相关监控范围完整且已知, 零异常才是可报告业务零值。",
        )
    return ZeroClaim(
        ZeroClaimState.UNKNOWN,
        None,
        0,
        monitor_denominator,
        UNKNOWN_DENOMINATOR_LABEL,
    )


def zero_candidate_claim(
    *,
    candidate_count: int,
    underwriting_evaluable_denominator: int | None,
) -> ZeroClaim:
    _require_count(candidate_count, "candidate_count")
    if underwriting_evaluable_denominator is not None:
        _require_count(
            underwriting_evaluable_denominator,
            "underwriting_evaluable_denominator",
        )
    if candidate_count > 0:
        return ZeroClaim(
            ZeroClaimState.NOT_ZERO,
            candidate_count,
            candidate_count,
            underwriting_evaluable_denominator,
            "至少一个 Candidate 已形成。",
        )
    if underwriting_evaluable_denominator is not None and underwriting_evaluable_denominator > 0:
        return ZeroClaim(
            ZeroClaimState.PROVEN_ZERO,
            0,
            0,
            underwriting_evaluable_denominator,
            "存在非零 Underwriting-evaluable 分母, 零 Candidate 才是可报告业务零值。",
        )
    return ZeroClaim(
        ZeroClaimState.UNKNOWN,
        None,
        0,
        underwriting_evaluable_denominator,
        UNKNOWN_DENOMINATOR_LABEL,
    )


class SnapshotStore:
    """Thread-safe immutable byte publication; HTTP readers never see mutable runtime state."""

    def __init__(self, initial: Mapping[str, object]) -> None:
        self._lock = threading.Lock()
        self._snapshot = self._build_snapshot(1, initial)

    def publish(self, document: Mapping[str, object]) -> PublishedSnapshot:
        with self._lock:
            sequence = self._snapshot.sequence + 1
            self._snapshot = self._build_snapshot(sequence, document)
            return self._snapshot

    def publish_preencoded_members(
        self,
        document: Mapping[str, object],
        *,
        preencoded_members: Mapping[str, bytes],
    ) -> PublishedSnapshot:
        """Publish exact bytes while reusing trusted immutable top-level JSON members."""
        with self._lock:
            sequence = self._snapshot.sequence + 1
            self._snapshot = self._build_snapshot(
                sequence,
                document,
                preencoded_members=dict(preencoded_members),
            )
            return self._snapshot

    def read(self) -> PublishedSnapshot:
        with self._lock:
            return self._snapshot

    @staticmethod
    def _build_snapshot(
        sequence: int,
        document: Mapping[str, object],
        *,
        preencoded_members: Mapping[str, bytes] | None = None,
    ) -> PublishedSnapshot:
        value = dict(document)
        value["publication_sequence"] = sequence
        body = (
            _json_bytes(value)
            if preencoded_members is None
            else _json_bytes_with_preencoded_members(value, preencoded_members)
        )
        service = _mapping(value.get("service"), "service")
        health = _boolean(service.get("health"), "service.health")
        ready = _boolean(service.get("ready"), "service.ready")
        health_body = _json_bytes(
            {
                "schema_version": WORKBENCH_SCHEMA_VERSION,
                "health": health,
                "runtime_identity": value.get("runtime_identity"),
            }
        )
        ready_body = _json_bytes(
            {
                "schema_version": WORKBENCH_SCHEMA_VERSION,
                "ready": ready,
                "runtime_identity": value.get("runtime_identity"),
            }
        )
        return PublishedSnapshot(sequence, body, health_body, ready_body, health, ready)


class WorkbenchPublisher:
    """Build one immutable trader projection after a fully settled runtime transaction."""

    def __init__(
        self,
        *,
        store: SnapshotStore,
        bindings: RuntimeBindings,
        policies: PolicyChain,
        shadow_state: ShadowStateStore,
        shadow_metadata: ShadowMetadataSource,
        initial_recorded_monotonic_ms: int = 0,
    ) -> None:
        self.store = store
        self.bindings = bindings
        self.policies = policies
        self.product = product_for_identity(policies.radar.product_spec_identity)
        self.shadow_state = shadow_state
        self.shadow_metadata = shadow_metadata
        self.funnel_tracker = FunnelTracker()
        self._status = ServiceStatus(
            ServicePhase.STARTING,
            DataState.UNKNOWN,
            True,
            False,
            False,
            "STARTING",
            initial_recorded_monotonic_ms,
        )
        self._published_status_key = _status_key(self._status)
        self._last_publication_monotonic_ms = initial_recorded_monotonic_ms
        has_staged_recovery = any(
            value.get("object_kind") == "SHADOW_ENTRY"
            and isinstance((payload := value.get("payload")), Mapping)
            and payload.get("tracking_state") == "RECOVERING"
            for value in self.shadow_state.objects
        )
        initial_underwriting_metadata = (
            self.shadow_metadata.workbench_underwriting_metadata() if has_staged_recovery else ()
        )
        initial_downstream: _DownstreamProjection | None = None
        initial_business = _empty_business_projection(self.product)
        if has_staged_recovery:
            initial_downstream = _build_downstream_projection(
                objects=self.shadow_state.objects,
                policies=self.policies,
                underwriting_metadata=initial_underwriting_metadata,
            )
            position_rows = _position_rows(
                initial_downstream.kinds,
                self.policies,
                trusted_time=None,
                option_metadata=(),
            )
            initial_business.update(
                {
                    "underwriting": {
                        "panel_state": panel_state(initial_downstream.underwriting_rows).value,
                        "empty_label": (
                            EMPTY_PANEL_LABEL if not initial_downstream.underwriting_rows else None
                        ),
                        "predicate_margin_summary": _underwriting_margin_summary(
                            initial_downstream.underwriting_rows
                        ),
                        "rows": initial_downstream.underwriting_rows,
                    },
                    "decision_controls": {
                        "panel_state": panel_state(initial_downstream.decision_control_rows).value,
                        "empty_label": (
                            EMPTY_PANEL_LABEL
                            if not initial_downstream.decision_control_rows
                            else None
                        ),
                        "rows": initial_downstream.decision_control_rows,
                    },
                    "shadow_entries": {
                        "panel_state": panel_state(initial_downstream.shadow_rows).value,
                        "empty_label": (
                            EMPTY_PANEL_LABEL if not initial_downstream.shadow_rows else None
                        ),
                        "simulation_label": SIMULATION_LABEL,
                        "rows": initial_downstream.shadow_rows,
                    },
                    "positions": {
                        "panel_state": panel_state(position_rows).value,
                        "empty_label": EMPTY_PANEL_LABEL if not position_rows else None,
                        "rows": position_rows,
                    },
                    "outcomes": {
                        "panel_state": panel_state(initial_downstream.outcome_rows).value,
                        "empty_label": (
                            EMPTY_PANEL_LABEL if not initial_downstream.outcome_rows else None
                        ),
                        "rows": initial_downstream.outcome_rows,
                    },
                }
            )
        self._last_business: Mapping[str, object] = MappingProxyType(initial_business)
        self._latest_reducer: RadarReducer | None = None
        self._latest_commit: CausalCommit | None = None
        self._dirty = False
        self._business_dirty = False
        self._cached_downstream_revision: int | None = (
            self.shadow_state.revision if initial_downstream is not None else None
        )
        self._cached_underwriting_metadata: tuple[Mapping[str, object], ...] | None = (
            tuple(initial_underwriting_metadata) if initial_downstream is not None else None
        )
        self._cached_admission_terminal_diagnostics: tuple[Mapping[str, object], ...] | None = (
            () if initial_downstream is not None else None
        )
        self._cached_downstream_projection: _DownstreamProjection | None = initial_downstream
        self._admission_terminal_diagnostics_by_episode: dict[str, Mapping[str, object]] = {}
        initial_document = self._document(self._last_business, status=self._status)
        self._preencoded_members = {
            key: _json_value_bytes(initial_document[key])
            for key in (
                "schema_version",
                "channel_id",
                "runtime_identity",
                "code_identity",
                "policy_identities",
                "product",
                "non_claims",
                "underwriting",
                "shadow_entries",
                "outcomes",
            )
        }

    @property
    def status(self) -> ServiceStatus:
        return self._status

    @property
    def funnel_snapshot(self) -> FunnelSnapshot:
        return self.funnel_tracker.snapshot()

    def update_status(self, status: ServiceStatus) -> None:
        self._status = status
        self._dirty = True
        self._publish_pending(status=status)

    def publish_settled(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> None:
        status = _settled_status(
            reducer,
            phase=self._status.phase,
            recorded_monotonic_ms=max(
                commit.boundary.received_monotonic_ms,
                self._status.recorded_monotonic_ms,
            ),
        )
        new_shadow_records = self.shadow_state.take_pending_records()
        self._update_admission_terminal_diagnostics(new_shadow_records)
        self.funnel_tracker.observe(
            reducer=reducer,
            commit=commit,
            new_shadow_records=new_shadow_records,
        )
        self._latest_reducer = reducer
        self._latest_commit = commit
        self._dirty = True
        self._business_dirty = True
        status_key = _status_key(status)
        self._status = status
        if (
            status_key != self._published_status_key
            or status.recorded_monotonic_ms - self._last_publication_monotonic_ms
            >= WORKBENCH_PUBLICATION_INTERVAL_MS
        ):
            self._publish_pending(status=status)

    def flush_pending(self) -> None:
        if self._dirty:
            self._publish_pending(status=self._status)

    def _publish_pending(self, *, status: ServiceStatus) -> None:
        business = self._last_business
        preencoded_members = dict(self._preencoded_members)
        downstream_revision = self._cached_downstream_revision
        underwriting_metadata = self._cached_underwriting_metadata
        admission_terminal_diagnostics = self._cached_admission_terminal_diagnostics
        downstream_projection = self._cached_downstream_projection

        if self._business_dirty:
            reducer = self._latest_reducer
            commit = self._latest_commit
            if reducer is None or commit is None:
                raise RuntimeError("pending workbench business state is incomplete")
            option_metadata = self.shadow_metadata.workbench_option_metadata()
            latest_underwriting_metadata = self.shadow_metadata.workbench_underwriting_metadata()
            latest_downstream_revision = self.shadow_state.revision
            latest_admission_terminal_diagnostics = tuple(
                self._admission_terminal_diagnostics_by_episode[key]
                for key in sorted(self._admission_terminal_diagnostics_by_episode)
            )
            downstream_changed = (
                downstream_projection is None
                or latest_downstream_revision != downstream_revision
                or latest_underwriting_metadata != underwriting_metadata
                or latest_admission_terminal_diagnostics != admission_terminal_diagnostics
            )
            if downstream_changed:
                downstream_projection = _build_downstream_projection(
                    objects=self.shadow_state.objects,
                    diagnostic_records=latest_admission_terminal_diagnostics,
                    policies=self.policies,
                    underwriting_metadata=latest_underwriting_metadata,
                )
                downstream_revision = latest_downstream_revision
                underwriting_metadata = latest_underwriting_metadata
                admission_terminal_diagnostics = latest_admission_terminal_diagnostics
            if downstream_projection is None:
                raise RuntimeError("workbench downstream projection cache was not initialized")
            projected_business = _build_business_projection(
                reducer=reducer,
                commit=commit,
                downstream=downstream_projection,
                policies=self.policies,
                option_metadata=option_metadata,
                funnel=self.funnel_tracker.snapshot(),
            )
            business = MappingProxyType(projected_business)
            if downstream_changed:
                for key in ("underwriting", "shadow_entries", "outcomes"):
                    preencoded_members[key] = _json_value_bytes(projected_business[key])

        self.store.publish_preencoded_members(
            self._document(business, status=status),
            preencoded_members=preencoded_members,
        )
        self._last_business = business
        self._preencoded_members = preencoded_members
        self._cached_downstream_revision = downstream_revision
        self._cached_underwriting_metadata = underwriting_metadata
        self._cached_admission_terminal_diagnostics = admission_terminal_diagnostics
        self._cached_downstream_projection = downstream_projection
        self._published_status_key = _status_key(status)
        self._last_publication_monotonic_ms = status.recorded_monotonic_ms
        self._dirty = False
        self._business_dirty = False

    def _update_admission_terminal_diagnostics(
        self,
        records: Sequence[Mapping[str, object]],
    ) -> None:
        """Keep at most one current terminal per still-active Radar Episode."""
        for value in records:
            kind = value.get("object_kind")
            payload = value.get("payload")
            if not isinstance(payload, Mapping):
                continue
            episode = payload.get("active_episode_identity")
            if not isinstance(episode, str):
                continue
            if kind == "CANDIDATE_ACTIVATION":
                self._admission_terminal_diagnostics_by_episode.pop(episode, None)
            elif kind == "ADMISSION_ATTEMPT_TERMINAL":
                self._admission_terminal_diagnostics_by_episode[episode] = value
        active_episodes = {
            str(payload.get("active_episode_identity"))
            for value in self.shadow_state.objects
            if value.get("object_kind") == "UNDERWRITING_AVAILABILITY_EVALUATION"
            and isinstance((payload := value.get("payload")), Mapping)
            and isinstance(payload.get("active_episode_identity"), str)
        }
        for episode in tuple(self._admission_terminal_diagnostics_by_episode):
            if episode not in active_episodes:
                self._admission_terminal_diagnostics_by_episode.pop(episode, None)

    def _document(
        self,
        business: Mapping[str, object],
        *,
        status: ServiceStatus,
    ) -> dict[str, object]:
        return {
            "schema_version": WORKBENCH_SCHEMA_VERSION,
            "channel_id": WORKBENCH_CHANNEL_ID,
            "runtime_identity": self.bindings.runtime_identity,
            "code_identity": self.bindings.code_identity,
            "policy_identities": {
                "radar": self.bindings.radar_policy_identity,
                "underwriting": self.bindings.underwriting_policy_identity,
                "position": self.bindings.position_policy_identity,
            },
            "product": _product_object(self.product),
            "service": _status_object(status),
            **dict(business),
            "non_claims": list(WORKBENCH_NON_CLAIMS),
        }


def initial_workbench_document(
    bindings: RuntimeBindings,
    *,
    product: OptionProductSpec = INVERSE_BTC,
    recorded_monotonic_ms: int = 0,
) -> dict[str, object]:
    status = ServiceStatus(
        ServicePhase.STARTING,
        DataState.UNKNOWN,
        True,
        False,
        False,
        "STARTING",
        recorded_monotonic_ms,
    )
    return {
        "schema_version": WORKBENCH_SCHEMA_VERSION,
        "channel_id": WORKBENCH_CHANNEL_ID,
        "runtime_identity": bindings.runtime_identity,
        "code_identity": bindings.code_identity,
        "policy_identities": {
            "radar": bindings.radar_policy_identity,
            "underwriting": bindings.underwriting_policy_identity,
            "position": bindings.position_policy_identity,
        },
        "product": _product_object(product),
        "service": _status_object(status),
        **_empty_business_projection(product),
        "non_claims": list(WORKBENCH_NON_CLAIMS),
    }


def _build_business_projection(
    *,
    reducer: RadarReducer,
    commit: CausalCommit,
    downstream: _DownstreamProjection,
    policies: PolicyChain,
    option_metadata: Sequence[Mapping[str, object]],
    funnel: FunnelSnapshot,
) -> dict[str, object]:
    trusted = _trusted_interval(reducer, commit.boundary.received_monotonic_ms)
    calculations: dict[str, DetectorCalculation] = {}
    for name, result in reducer.results.items():
        if result.calculation is not None:
            calculations[name] = result.calculation
    detector_states = {name: result.detector_state for name, result in reducer.results.items()}
    detector_reasons = {name: result.reason for name, result in reducer.results.items()}
    review_contexts = build_review_contexts(
        options=reducer.options,
        calculations=calculations,
        detector_states=detector_states,
        detector_reasons=detector_reasons,
        tickers=reducer.current_diagnostic_tickers,
        option_books=reducer.option_books,
        option_catalog_complete=reducer.option_catalog.complete,
        index_usdc_per_btc=reducer.current_index_price_usdc_per_btc,
        target_quantity_btc=policies.radar.target_base_quantity_btc,
        fee_rate_index_fraction=policies.underwriting.fee_rate_index_fraction,
        score_model=policies.radar.score_model,
        attention_top_n=DEFAULT_ATTENTION_TOP_N,
    )
    radar_rows = _radar_rows(reducer, commit, trusted, review_contexts)
    position_rows = _position_rows(
        downstream.kinds,
        policies,
        trusted_time=trusted,
        option_metadata=option_metadata,
    )

    monitored_count = len(reducer.options)
    known_count = sum(
        result.known_evaluation
        for name, result in reducer.results.items()
        if name in reducer.options
    )
    coverage_ratio = _ratio_percent(known_count, monitored_count)
    active_anomalies = _active_anomaly_count(reducer)
    monitor_complete = (
        reducer.current_coverage_state is CoverageState.KNOWN_COMPLETE and monitored_count > 0
    )
    anomaly_zero = zero_anomaly_claim(
        active_anomaly_count=active_anomalies,
        monitor_denominator=(monitored_count if monitored_count > 0 else None),
        monitor_complete=monitor_complete,
    )
    candidate_zero = zero_candidate_claim(
        candidate_count=downstream.underwriting_counts["candidate_count"],
        underwriting_evaluable_denominator=(
            downstream.underwriting_counts["underwriting_availability_evaluable_count"] or None
        ),
    )
    latency = _latency_projection(reducer, commit, trusted)
    history_state = (
        reducer.index_history.current_tail(
            reducer.policy.largest_lookback_minutes,
            trusted_time=trusted,
            source_stale_deadline_ms=(
                reducer.policy.runtime_limits.index_history_source_stale_deadline_ms
            ),
        )
        if trusted is not None
        else None
    )
    history_contract = history_state.contract if history_state is not None else None
    return {
        "published_fact_boundary": _runtime_boundary_object(commit),
        "funnel": funnel.as_object(),
        "system": {
            "session_epoch": reducer.current_session_epoch,
            "platform_usable": reducer.platform.usable,
            "platform_reason": reducer.platform.reason,
            **latency,
            "coverage_state": reducer.current_coverage_state.value,
            "coverage_blocking_reason": reducer.current_coverage_blocking_reason,
            "coverage_affected_scopes": list(reducer.current_coverage_affected_scopes),
            "coverage_ratio_percent": coverage_ratio,
            "known_current_instrument_evaluation_count": known_count,
            "monitored_instrument_count": monitored_count,
            "reconnect_count": reducer.diagnostics.reconnect_count,
            "session_gap_count": reducer.diagnostics.session_gap_count,
            "global_continuity_epoch": reducer.current_global_continuity_epoch,
            "disconnect_records": _disconnect_records(reducer),
            "index_history": {
                "source": (
                    f"DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_{reducer.product.price_index.upper()}_2D"
                ),
                "value_semantics": "AVERAGE_INDEX_PRICE",
                "availability": (
                    history_state.availability.value if history_state is not None else "UNKNOWN"
                ),
                "reason": history_state.reason if history_state is not None else "CLOCK_UNKNOWN",
                "source_point_count": (
                    history_contract.source_point_count if history_contract is not None else None
                ),
                "interval_counts": (
                    [
                        {"interval_ms": interval, "count": count}
                        for interval, count in history_contract.interval_counts
                    ]
                    if history_contract is not None
                    else []
                ),
                "modal_interval_ms": (
                    history_contract.modal_interval_ms if history_contract is not None else None
                ),
                "newest_response_timestamp_ms": (
                    history_contract.newest_response_timestamp_ms
                    if history_contract is not None
                    else None
                ),
                "newest_response_age_ms": (
                    history_contract.newest_response_age_ms
                    if history_contract is not None
                    else None
                ),
                "newest_response_point_excluded_by_completion_cutoff": (
                    history_contract.newest_response_point_excluded_by_completion_cutoff
                    if history_contract is not None
                    else False
                ),
                "latest_source_timestamp_ms": (
                    history_contract.latest_source_timestamp_ms
                    if history_contract is not None
                    else None
                ),
                "latest_source_age_ms": (
                    history_contract.latest_source_age_ms if history_contract is not None else None
                ),
                "exact_suffix_point_count": (
                    history_contract.exact_suffix_point_count if history_contract is not None else 0
                ),
                "exact_suffix_minutes": (
                    history_contract.exact_suffix_minutes if history_contract is not None else 0
                ),
                "revision_count": (
                    history_contract.revision_count if history_contract is not None else 0
                ),
                "revision_pending": (
                    history_contract.revision_pending if history_contract is not None else False
                ),
                "revised_timestamps_ms": (
                    list(history_contract.revised_timestamps_ms)
                    if history_contract is not None
                    else []
                ),
            },
        },
        "zero_claims": {
            "anomaly": anomaly_zero.as_object(),
            "candidate": candidate_zero.as_object(),
        },
        "radar": {
            "panel_state": panel_state(radar_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not radar_rows else None,
            "attention_top_n": DEFAULT_ATTENTION_TOP_N,
            "ranked_row_count": len(review_contexts),
            "rows": radar_rows,
        },
        "underwriting": {
            "panel_state": panel_state(downstream.underwriting_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not downstream.underwriting_rows else None,
            "predicate_margin_summary": _underwriting_margin_summary(downstream.underwriting_rows),
            "rows": downstream.underwriting_rows,
        },
        "decision_controls": {
            "panel_state": panel_state(downstream.decision_control_rows).value,
            "empty_label": (EMPTY_PANEL_LABEL if not downstream.decision_control_rows else None),
            "rows": downstream.decision_control_rows,
        },
        "shadow_entries": {
            "panel_state": panel_state(downstream.shadow_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not downstream.shadow_rows else None,
            "simulation_label": SIMULATION_LABEL,
            "rows": downstream.shadow_rows,
        },
        "positions": {
            "panel_state": panel_state(position_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not position_rows else None,
            "rows": position_rows,
        },
        "outcomes": {
            "panel_state": panel_state(downstream.outcome_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not downstream.outcome_rows else None,
            "rows": downstream.outcome_rows,
        },
    }


def _build_downstream_projection(
    *,
    objects: Sequence[Mapping[str, object]],
    diagnostic_records: Sequence[Mapping[str, object]] = (),
    policies: PolicyChain,
    underwriting_metadata: Sequence[Mapping[str, object]],
) -> _DownstreamProjection:
    current_keys = {(value.get("object_kind"), value.get("object_identity")) for value in objects}
    projection_objects = (
        *objects,
        *(
            value
            for value in diagnostic_records
            if (value.get("object_kind"), value.get("object_identity")) not in current_keys
        ),
    )
    kinds = _objects_by_kind(projection_objects)
    return _DownstreamProjection(
        kinds=kinds,
        underwriting_rows=_underwriting_rows(
            kinds,
            policies,
            display_metadata=underwriting_metadata,
        ),
        shadow_rows=_shadow_rows(kinds, policies),
        outcome_rows=_outcome_rows(kinds),
        decision_control_rows=_decision_control_rows(kinds),
        underwriting_counts=_underwriting_counts(objects),
    )


def _underwriting_counts(
    objects: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    counts = {
        "candidate_count": 0,
        "underwriting_availability_evaluable_count": 0,
    }
    seen: set[tuple[str, str]] = set()
    for value in objects:
        kind = value.get("object_kind")
        identity = value.get("object_identity")
        if not isinstance(kind, str) or not isinstance(identity, str):
            continue
        if (kind, identity) in seen:
            continue
        seen.add((kind, identity))
        if kind == "CANDIDATE_ACTIVATION":
            counts["candidate_count"] += 1
        elif kind == "UNDERWRITING_AVAILABILITY_EVALUATION":
            payload = value.get("payload")
            if isinstance(payload, Mapping) and payload.get("availability") == "EVALUABLE":
                counts["underwriting_availability_evaluable_count"] += 1
    return counts


def _radar_rows(
    reducer: RadarReducer,
    commit: CausalCommit,
    trusted: TimeInterval | None,
    review_contexts: Mapping[str, ReviewContext] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    contexts = review_contexts or {}
    trusted_interval = trusted
    for name, instrument in sorted(reducer.options.items()):
        product = instrument.product
        result = reducer.results.get(name)
        tracker = reducer.trackers.get(name)
        calculation = result.calculation if result is not None else None
        typed_score_packet = getattr(result, "score_packet", None) if result is not None else None
        score_packet = _score_packet_object(typed_score_packet)
        typed_score_result = getattr(result, "score_result", None) if result is not None else None
        score_result = typed_score_result.as_object() if typed_score_result is not None else None
        bucket_key = reducer.score_bucket_keys.get(name)
        bucket_leader = (
            reducer.bucket_leader_by_key.get(bucket_key) if bucket_key is not None else None
        )
        bucket_projection = None
        if bucket_key is not None and calculation is not None:
            bucket_tracker = reducer.bucket_trackers.get(bucket_key)
            if bucket_tracker is not None:
                bucket_projection = bucket_tracker.projection(calculation.rule)
        option_book = reducer.option_books.get(name)
        review = contexts.get(name)
        episode = tracker.episode_id if tracker is not None else None
        tte = (
            None
            if trusted_interval is None
            else {
                "lower_ms": instrument.expiration_timestamp_ms - trusted_interval.upper_ms,
                "upper_ms": instrument.expiration_timestamp_ms - trusted_interval.lower_ms,
            }
        )
        rows.append(
            {
                "instrument_name": name,
                "product_spec_identity": product.identity,
                "product_name": product.name.value,
                "native_premium_currency": product.native_premium_currency,
                "valuation_currency": product.valuation_currency,
                "strike_currency": product.strike_currency,
                "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
                "tte_interval_ms": tte,
                "option_type": instrument.option_type.value,
                "strike_price": str(instrument.strike),
                "detector_state": (
                    result.detector_state.value if result is not None else "UNKNOWN"
                ),
                "detector_reason": result.reason if result is not None else "NOT_SETTLED",
                "score_packet": score_packet,
                "score_result": score_result,
                "score_bucket_key": (bucket_key.as_object() if bucket_key is not None else None),
                "bucket_leader_instrument_name": bucket_leader,
                "is_bucket_leader": bucket_leader == name,
                "bucket_leader_coverage": (
                    reducer.bucket_leader_coverage[bucket_key].value
                    if bucket_key is not None and bucket_key in reducer.bucket_leader_coverage
                    else "UNKNOWN"
                ),
                "bucket_episode_state": (
                    bucket_projection.state.value if bucket_projection is not None else "IDLE"
                ),
                "bucket_episode_identity": (
                    bucket_projection.episode_identity if bucket_projection is not None else None
                ),
                "bucket_episode_leader_instrument_name": (
                    bucket_projection.leader_instrument_name
                    if bucket_projection is not None
                    else None
                ),
                "bucket_episode_score_band": (
                    bucket_projection.score_band.value
                    if bucket_projection is not None and bucket_projection.score_band is not None
                    else None
                ),
                "confirmation_observation_count": (
                    bucket_projection.confirmation_observation_count
                    if bucket_projection is not None
                    else 0
                ),
                "required_confirmation_observation_count": (
                    bucket_projection.required_confirmation_observation_count
                    if bucket_projection is not None
                    else None
                ),
                "end_confirmation_observation_count": (
                    bucket_projection.end_confirmation_observation_count
                    if bucket_projection is not None
                    else 0
                ),
                "required_end_confirmation_observation_count": (
                    bucket_projection.required_end_confirmation_observation_count
                    if bucket_projection is not None
                    else None
                ),
                "option_book_state": (
                    option_book.state.value if option_book is not None else "UNKNOWN"
                ),
                "option_book_reason": (
                    option_book.reason if option_book is not None else "BOOK_NOT_CREATED"
                ),
                "known_evaluation": (result.known_evaluation if result is not None else False),
                "tte_band_id": result.band_id if result is not None else None,
                "clue_eligible_tte": (
                    calculation.band.clue_eligible if calculation is not None else None
                ),
                "clue_eligible_delta": (
                    calculation.delta_clue_eligible if calculation is not None else None
                ),
                "delta_bucket": (
                    calculation.delta_bucket.value if calculation is not None else None
                ),
                "delta_interval": (
                    _decimal_interval(calculation.delta) if calculation is not None else None
                ),
                "native_executable_sell_price": (
                    str(
                        getattr(
                            calculation,
                            "native_executable_sell_price",
                            calculation.executable_sell_price_usdc,
                        )
                    )
                    if calculation is not None
                    else None
                ),
                "native_executable_buy_price": (
                    str(
                        getattr(
                            calculation,
                            "native_executable_buy_price",
                            calculation.executable_buy_price_usdc,
                        )
                    )
                    if calculation is not None
                    else None
                ),
                "native_one_tick_stressed_sell_price": (
                    str(
                        getattr(
                            calculation,
                            "native_stressed_executable_sell_price",
                            calculation.stressed_executable_sell_price_usdc,
                        )
                    )
                    if calculation is not None
                    else None
                ),
                "native_price_tick": (
                    str(getattr(calculation, "native_price_tick", calculation.price_tick_usdc))
                    if calculation is not None
                    else None
                ),
                "native_target_spread": (
                    str(
                        getattr(
                            calculation,
                            "native_target_spread",
                            calculation.target_spread_usdc,
                        )
                    )
                    if calculation is not None
                    else None
                ),
                "model_conversion_forward": (
                    str(
                        getattr(
                            calculation,
                            "model_conversion_forward",
                            getattr(calculation, "forward_usdc", None),
                        )
                    )
                    if calculation is not None
                    else None
                ),
                "model_executable_sell_price": (
                    str(calculation.executable_sell_price_usdc) if calculation is not None else None
                ),
                "model_executable_buy_price": (
                    str(calculation.executable_buy_price_usdc) if calculation is not None else None
                ),
                "model_one_tick_stressed_sell_price": (
                    str(calculation.stressed_executable_sell_price_usdc)
                    if calculation is not None
                    else None
                ),
                "model_price_tick": (
                    str(calculation.price_tick_usdc) if calculation is not None else None
                ),
                "model_target_spread": (
                    str(calculation.target_spread_usdc) if calculation is not None else None
                ),
                "target_spread_ticks": (
                    str(calculation.target_spread_ticks) if calculation is not None else None
                ),
                "bid_premium_ticks": (
                    str(calculation.bid_premium_ticks) if calculation is not None else None
                ),
                "bid_consumed_level_count": (
                    len(calculation.target_bid.consumed) if calculation is not None else None
                ),
                "ask_consumed_level_count": (
                    len(calculation.target_ask.consumed) if calculation is not None else None
                ),
                "executable_iv_interval": (
                    _decimal_interval(calculation.executable_bid_iv)
                    if calculation is not None
                    else None
                ),
                "executable_ask_iv_interval": (
                    _decimal_interval(calculation.executable_ask_iv)
                    if calculation is not None
                    else None
                ),
                "one_tick_stressed_iv_interval": (
                    _decimal_interval(calculation.stressed_executable_bid_iv)
                    if calculation is not None
                    else None
                ),
                "baseline_annualized_volatility": (
                    str(calculation.baseline.annualized_volatility)
                    if calculation is not None
                    else None
                ),
                "baseline_return_interval_minutes": (
                    calculation.baseline.return_interval_minutes
                    if calculation is not None
                    else None
                ),
                "baseline_selected_lookback_minutes": (
                    calculation.baseline.selected_lookback_minutes
                    if calculation is not None
                    else None
                ),
                "baseline_source": (
                    (
                        "ANNUALIZED_VARIANCE_FLOOR"
                        if calculation.baseline.selected_lookback_minutes is None
                        else "SOURCE_CONFIRMED_UTC_ALIGNED_5M_INDEX_CHART_AVERAGE_PRICE_RV"
                    )
                    if calculation is not None
                    else None
                ),
                "raw_richness_ratio_interval": (
                    _decimal_interval(calculation.raw_richness) if calculation is not None else None
                ),
                "richness_ratio_interval": (
                    _decimal_interval(calculation.richness) if calculation is not None else None
                ),
                "hard_screen_label": review.hard_screen_label if review is not None else None,
                "positive_witness": review.positive_witness if review is not None else None,
                "primary_blocker": review.primary_blocker if review is not None else None,
                "upgrade_condition": review.upgrade_condition if review is not None else None,
                "invalidation_condition": (
                    review.invalidation_condition if review is not None else None
                ),
                "rank_inputs": (review.rank_inputs.as_object() if review is not None else None),
                "attention_rank": review.attention_rank if review is not None else None,
                "within_attention_top_n": (
                    review.within_attention_top_n if review is not None else False
                ),
                "rank_explanation": (list(review.rank_explanation) if review is not None else []),
                "regime_context": review.regime.as_object() if review is not None else None,
                "regime_jump_share": (
                    str(review.regime.jump_share)
                    if review is not None and review.regime.jump_share is not None
                    else None
                ),
                "regime_adverse_semivariance_share": (
                    str(review.regime.adverse_semivariance_share)
                    if review is not None and review.regime.adverse_semivariance_share is not None
                    else None
                ),
                "surface_context": review.surface.as_object() if review is not None else None,
                "surface_residual": (
                    str(review.surface.stressed_executable_bid_iv_minus_local_mark_iv)
                    if review is not None
                    and review.surface.stressed_executable_bid_iv_minus_local_mark_iv is not None
                    else None
                ),
                "legged_structure_context": (
                    review.legged_structure.as_object() if review is not None else None
                ),
                "legged_reference_state": (
                    review.legged_structure.state.value if review is not None else None
                ),
                "best_legged_credit_to_payoff_cap_fraction": (
                    str(review.legged_structure.best_credit_to_payoff_cap_fraction)
                    if review is not None
                    and review.legged_structure.best_credit_to_payoff_cap_fraction is not None
                    else None
                ),
                "public_atomic_quote_state": _public_atomic_quote_state(
                    reducer,
                    tracker=tracker,
                    episode_identity=episode,
                ),
                "active_episode_identity": episode,
                "anomaly_started_monotonic_ms": (
                    reducer.episode_started_monotonic_ms(episode) if episode is not None else None
                ),
                "anomaly_active_duration_ms": (
                    reducer.episode_active_duration_ms(
                        episode,
                        observed_monotonic_ms=commit.boundary.received_monotonic_ms,
                    )
                    if episode is not None
                    else None
                ),
            }
        )
    return rows


def _active_anomaly_count(reducer: RadarReducer) -> int:
    return sum(
        tracker.detector_state is DetectorState.ANOMALY_ACTIVE
        for tracker in reducer.trackers.values()
    )


def _public_atomic_quote_state(
    reducer: RadarReducer,
    *,
    tracker: object,
    episode_identity: str | None,
) -> str:
    if (
        tracker is None
        or getattr(tracker, "detector_state", None) is not DetectorState.ANOMALY_ACTIVE
    ):
        return "NOT_EVALUATED"
    if episode_identity is None:
        return "UNKNOWN"
    state = reducer.atomic_states.get(episode_identity)
    return "UNKNOWN" if state is None else state.value


def _underwriting_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
    policies: PolicyChain,
    *,
    display_metadata: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    display_by_scope: dict[str, Mapping[str, object]] = {}
    for value in display_metadata:
        scope_identity = value.get("radar_scope_identity")
        if not isinstance(scope_identity, str):
            raise TypeError("workbench Underwriting display scope identity must be a string")
        if scope_identity in display_by_scope:
            raise ValueError("duplicate workbench Underwriting display scope identity")
        display_by_scope[scope_identity] = value
    actions_by_availability: dict[str, list[Mapping[str, object]]] = {}
    for value in kinds.get("UNDERWRITING_ACTION", ()):
        availability_identity = _payload(value).get("underwriting_availability_evaluation_identity")
        if isinstance(availability_identity, str):
            actions_by_availability.setdefault(availability_identity, []).append(value)
    candidates_by_action = {
        str(_payload(value).get("underwriting_action_identity")): value
        for value in kinds.get("CANDIDATE_ACTIVATION", ())
    }
    invalidations = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("CANDIDATE_INVALIDATION", ())
    }
    entries_by_candidate = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("SHADOW_ENTRY", ())
        if isinstance(_payload(value).get("candidate_identity"), str)
    }
    rows: list[dict[str, object]] = []
    for availability_value in _latest_by_payload_key(
        kinds.get("UNDERWRITING_AVAILABILITY_EVALUATION", ()),
        "radar_scope_or_short_leg_identity",
    ):
        availability_payload = _payload(availability_value)
        scope_identity = availability_payload.get("radar_scope_or_short_leg_identity")
        display = display_by_scope.get(str(scope_identity), {})
        availability_identity = str(availability_value["object_identity"])
        action = _latest(actions_by_availability.get(availability_identity, ()))
        payload = _payload(action) if action is not None else {}
        action_identity = str(action["object_identity"]) if action is not None else None
        candidate = (
            candidates_by_action.get(action_identity) if action_identity is not None else None
        )
        candidate_identity = str(candidate["object_identity"]) if candidate is not None else None
        admitted_entry = (
            entries_by_candidate.get(candidate_identity) if candidate_identity is not None else None
        )
        if admitted_entry is not None:
            lifecycle = "ADMITTED"
        elif candidate_identity in invalidations:
            lifecycle = "INVALIDATED"
        elif candidate_identity is not None:
            lifecycle = "VALID"
        else:
            lifecycle = None
        availability = availability_payload.get("availability", "UNKNOWN")
        unknown_reasons = availability_payload.get("unknown_reasons", [])
        rows.append(
            {
                "radar_scope_or_short_leg_identity": scope_identity,
                "short_leg_instrument_name": display.get("short_leg_instrument_name"),
                "long_leg_instrument_name": payload.get(
                    "selected_long_leg_instrument_name",
                    display.get("long_leg_instrument_name"),
                ),
                "combo_instrument_name": display.get("combo_instrument_name"),
                "expiry_timestamp_ms": display.get("expiry_timestamp_ms"),
                "option_type": display.get("option_type"),
                "short_strike_price": display.get("short_strike_usdc_per_btc"),
                "long_strike_price": display.get("long_strike_usdc_per_btc"),
                "target_quantity_btc": display.get("target_quantity_btc"),
                "underwriting_availability_evaluation_identity": availability_identity,
                "underwriting_action_identity": action_identity,
                "availability": availability,
                "unknown_reasons": unknown_reasons,
                "component_state": availability_payload.get("component_state", "UNKNOWN"),
                "component_blockers": availability_payload.get("component_blockers", []),
                "atomic_state_diagnostic": availability_payload.get(
                    "atomic_state_diagnostic", "NOT_EVALUATED"
                ),
                "action": payload.get("economic_action"),
                "radar_score_packet": payload.get("radar_score_packet")
                or availability_payload.get("radar_score_packet"),
                "product_spec_identity": payload.get("product_spec_identity"),
                "product_name": payload.get("product_name"),
                "native_premium_currency": payload.get("native_premium_currency"),
                "valuation_currency": payload.get("valuation_currency"),
                "native_gross_entry_credit": payload.get("native_gross_entry_credit"),
                "native_entry_fee_reserve": payload.get("native_entry_fee_reserve"),
                "native_net_entry_credit": payload.get("native_net_entry_credit"),
                "entry_valuation_index_price": payload.get("entry_valuation_index_price"),
                "gross_entry_credit_valuation": payload.get("gross_entry_credit_usdc"),
                "entry_fee_reserve_valuation": payload.get("entry_fee_reserve_usdc"),
                "net_entry_credit_valuation": payload.get("net_entry_credit_usdc"),
                "entry_boundary_valued_payoff_loss_ex_fees_valuation": payload.get(
                    "contractual_payoff_max_loss_ex_fees_usdc"
                ),
                "future_cost_reserve_valuation": payload.get("future_cost_reserve_usdc"),
                "underwriting_reserved_loss_valuation": payload.get(
                    "underwriting_reserved_loss_usdc"
                ),
                "failed_predicates": payload.get("failed_predicates", []),
                "predicate_margin_vector": payload.get("predicate_margin_vector", []),
                "protective_leg_selection_rule_identity": payload.get(
                    "protective_leg_selection_rule_identity"
                ),
                "candidate_protective_leg_count": payload.get("candidate_protective_leg_count"),
                "reserve_breakdown_valuation": {
                    "path": str(policies.underwriting.path_risk_reserve_usdc),
                    "jump": str(policies.underwriting.jump_risk_reserve_usdc),
                    "tail": str(policies.underwriting.tail_risk_reserve_usdc),
                    "liquidity": str(policies.underwriting.liquidity_cost_reserve_usdc),
                    "uncertainty": str(policies.underwriting.uncertainty_reserve_usdc),
                    "settlement": str(policies.underwriting.settlement_cost_reserve_usdc),
                    "gamma": None,
                    "slippage": None,
                },
                "reserve_non_claims": [
                    "GAMMA_RESERVE_NOT_SEPARATELY_DEFINED_BY_POLICY",
                    "SLIPPAGE_RESERVE_NOT_SEPARATELY_DEFINED_BY_POLICY",
                ],
                "decision_reason": _underwriting_decision_reason(
                    availability=availability,
                    action=payload.get("economic_action"),
                    unknown_reasons=unknown_reasons,
                    failed_predicates=payload.get("failed_predicates", []),
                ),
                "candidate_identity": candidate_identity,
                "candidate_lifecycle": lifecycle,
                "candidate_still_valid": lifecycle == "VALID",
                "candidate_invalidation_reason": (
                    _payload(invalidations[candidate_identity]).get("primary_reason")
                    if candidate_identity in invalidations
                    else None
                ),
                "evaluation_fact_boundary": (
                    payload.get("evaluation_fact_boundary")
                    if action is not None
                    else availability_payload.get("availability_evaluation_fact_boundary")
                ),
            }
        )
    return rows


def _underwriting_decision_reason(
    *,
    availability: object,
    action: object,
    unknown_reasons: object,
    failed_predicates: object,
) -> str:
    if isinstance(action, str):
        failures = (
            ",".join(str(value) for value in failed_predicates)
            if isinstance(failed_predicates, list) and failed_predicates
            else "NONE"
        )
        return f"UNDERWRITING_ACTION:{action};FAILED:{failures}"
    reasons = (
        ",".join(str(value) for value in unknown_reasons)
        if isinstance(unknown_reasons, list) and unknown_reasons
        else "NO_ADDITIONAL_REASON_PERSISTED"
    )
    return f"UNDERWRITING_{availability}:{reasons}"


def _underwriting_margin_summary(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Aggregate owner-emitted current margins without recalculating a predicate."""
    values: dict[str, list[Decimal]] = {}
    units: dict[str, str] = {}
    predicate_order: list[str] = []
    for row in rows:
        vector = row.get("predicate_margin_vector")
        if not isinstance(vector, list):
            continue
        seen_in_row: set[str] = set()
        for member in vector:
            if not isinstance(member, Mapping):
                continue
            predicate = member.get("predicate")
            unit = member.get("unit")
            margin = member.get("signed_margin")
            if (
                not isinstance(predicate, str)
                or not isinstance(unit, str)
                or predicate in seen_in_row
            ):
                continue
            seen_in_row.add(predicate)
            if predicate not in values:
                values[predicate] = []
                units[predicate] = unit
                predicate_order.append(predicate)
            elif units[predicate] != unit:
                continue
            try:
                parsed = Decimal(str(margin))
            except (InvalidOperation, ValueError):
                continue
            if parsed.is_finite():
                values[predicate].append(parsed)
    result: list[dict[str, object]] = []
    for predicate in predicate_order:
        ordered = sorted(values[predicate])
        if not ordered:
            continue
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
        )
        result.append(
            {
                "predicate": predicate,
                "unit": units[predicate],
                "count": len(ordered),
                "min": str(ordered[0]),
                "p50": str(median),
                "max": str(ordered[-1]),
            }
        )
    return result


def _decision_control_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    selections = {
        str(value["object_identity"]): value
        for value in kinds.get("SELECTED_UNDERWRITING_DECISION", ())
    }
    terminals = {
        str(_payload(value).get("selected_underwriting_decision_identity")): value
        for value in _latest_by_payload_key(
            kinds.get("UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL", ()),
            "selected_underwriting_decision_identity",
        )
    }
    refresh_terminals_by_identity = {
        str(value["object_identity"]): value
        for kind in (
            "ADMISSION_ATTEMPT_TERMINAL",
            "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
        )
        for value in kinds.get(kind, ())
    }
    admission_terminals_by_candidate = {
        str(_payload(value).get("candidate_identity")): value
        for value in _latest_by_payload_key(
            kinds.get("ADMISSION_ATTEMPT_TERMINAL", ()),
            "candidate_identity",
        )
    }
    enrollments: dict[str, Mapping[str, object]] = {}
    for kind in ("SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN", "SHADOW_ENTRY"):
        for value in kinds.get(kind, ()):
            payload = _payload(value)
            selected = payload.get("selected_underwriting_decision")
            if not isinstance(selected, Mapping):
                continue
            selection_identity = selected.get("selected_underwriting_decision_identity")
            if isinstance(selection_identity, str):
                enrollments[selection_identity] = value
    outcomes_by_enrollment = {
        str(_payload(value).get("shadow_entry_identity")): value
        for kind in ("SHADOW_OUTCOME", "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME")
        for value in kinds.get(kind, ())
    }
    rows: list[dict[str, object]] = []
    for selection_identity in sorted(set(selections) | set(enrollments)):
        selection = selections.get(selection_identity)
        selection_payload = _payload(selection) if selection is not None else {}
        enrollment = enrollments.get(selection_identity)
        enrollment_payload = _payload(enrollment) if enrollment is not None else {}
        selected_observation = enrollment_payload.get("selected_underwriting_decision")
        if not isinstance(selected_observation, Mapping):
            selected_observation = selection_payload
        terminal = terminals.get(selection_identity)
        if (
            terminal is None
            and selection_payload.get("entry_refresh_attempt_kind") == "CANDIDATE_ADMISSION"
        ):
            refresh_owner = selection_payload.get("entry_refresh_owner_identity")
            if isinstance(refresh_owner, str):
                terminal = admission_terminals_by_candidate.get(refresh_owner)
        if terminal is None:
            terminal_identity = enrollment_payload.get("entry_refresh_attempt_terminal_identity")
            if isinstance(terminal_identity, str):
                terminal = refresh_terminals_by_identity.get(terminal_identity)
        terminal_payload = _payload(terminal) if terminal is not None else {}
        refreshed_observation = (
            selected_observation
            if isinstance(selected_observation.get("refreshed_economic_action"), str)
            else terminal_payload
        )
        direct_terminal_outcome = enrollment_payload.get("entry_refresh_terminal_outcome")
        refresh_terminal_outcome = (
            direct_terminal_outcome
            if isinstance(direct_terminal_outcome, str)
            else terminal_payload.get("terminal_outcome")
        )
        direct_unknown_reasons = enrollment_payload.get("entry_refresh_terminal_unknown_reasons")
        refresh_unknown_reasons = (
            direct_unknown_reasons
            if isinstance(direct_unknown_reasons, list)
            else terminal_payload.get("terminal_unknown_reasons", [])
        )
        enrollment_identity = str(enrollment["object_identity"]) if enrollment is not None else None
        outcome = (
            outcomes_by_enrollment.get(enrollment_identity)
            if enrollment_identity is not None
            else None
        )
        outcome_payload = _payload(outcome) if outcome is not None else {}
        rows.append(
            {
                "selected_underwriting_decision_identity": selection_identity,
                "activation_batch_identity": selected_observation.get("activation_batch_identity"),
                "active_episode_identity": selection_payload.get("active_episode_identity")
                or enrollment_payload.get("active_episode_identity"),
                "selected_economic_action": selected_observation.get("selected_economic_action")
                or selection_payload.get("economic_action"),
                "selected_failed_predicates": selected_observation.get("selected_failed_predicates")
                or selection_payload.get("failed_predicates", []),
                "selected_predicate_margin_vector": selected_observation.get(
                    "selected_predicate_margin_vector"
                )
                or selection_payload.get("predicate_margin_vector", []),
                "protective_leg_selection_rule_identity": selection_payload.get(
                    "protective_leg_selection_rule_identity"
                )
                or enrollment_payload.get(
                    "entry_underwriting_protective_leg_selection_rule_identity"
                ),
                "candidate_protective_leg_count": selection_payload.get(
                    "candidate_protective_leg_count"
                )
                if selection_payload.get("candidate_protective_leg_count") is not None
                else enrollment_payload.get("entry_underwriting_candidate_protective_leg_count"),
                "selection_fact_boundary": selected_observation.get("selection_fact_boundary")
                or selection_payload.get("selection_fact_boundary"),
                "selection_score_packet": enrollment_payload.get("selection_score_packet")
                or selected_observation.get("selection_score_packet")
                or selection_payload.get("radar_score_packet"),
                "refresh_terminal_outcome": refresh_terminal_outcome,
                "refresh_unknown_reasons": refresh_unknown_reasons,
                "refresh_known_no_control_reason": terminal_payload.get("known_no_control_reason"),
                "refresh_component_pair_timing": enrollment_payload.get(
                    "entry_refresh_component_pair_timing"
                )
                or terminal_payload.get("component_pair_timing")
                or enrollment_payload.get("entry_component_pair_timing"),
                "refresh_component_pair_limits": enrollment_payload.get(
                    "entry_refresh_component_pair_limits"
                )
                or terminal_payload.get("component_pair_limits")
                or enrollment_payload.get("entry_component_pair_limits"),
                "refreshed_economic_action": refreshed_observation.get("refreshed_economic_action"),
                "refreshed_failed_predicates": refreshed_observation.get(
                    "refreshed_failed_predicates",
                    [],
                ),
                "refreshed_predicate_margin_vector": refreshed_observation.get(
                    "refreshed_predicate_margin_vector",
                    [],
                ),
                "refreshed_fact_boundary": refreshed_observation.get("refreshed_fact_boundary"),
                "entry_refresh_score_packet": enrollment_payload.get("entry_refresh_score_packet")
                or refreshed_observation.get("entry_refresh_score_packet")
                or terminal_payload.get("entry_refresh_score_packet"),
                "enrollment_kind": enrollment_payload.get("enrollment_kind"),
                "enrollment_identity": enrollment_identity,
                "case_state": (
                    outcome_payload.get("terminal_state")
                    if outcome is not None
                    else "PENDING_OUTCOME"
                    if enrollment is not None
                    else "NOT_OPENED"
                ),
                "public_quote_net_pnl_valuation": outcome_payload.get(
                    "net_pnl_after_public_standard_fee_reserve_usdc"
                ),
                "native_premium_currency": outcome_payload.get("native_premium_currency"),
                "native_net_pnl": outcome_payload.get("native_net_pnl"),
                "boundary_valued_net_pnl_usd": outcome_payload.get("boundary_valued_net_pnl_usd"),
                "exit_valued_native_net_pnl_usd": outcome_payload.get(
                    "exit_valued_native_net_pnl_usd"
                ),
                "non_claims": enrollment_payload.get("non_claims")
                or selection_payload.get("non_claims", []),
            }
        )
    return rows


def _shadow_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
    policies: PolicyChain,
) -> list[dict[str, object]]:
    entries_by_candidate = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("SHADOW_ENTRY", ())
    }
    terminals_by_candidate = {
        str(_payload(value).get("candidate_identity")): value
        for value in _latest_by_payload_key(
            kinds.get("ADMISSION_ATTEMPT_TERMINAL", ()),
            "candidate_identity",
        )
    }
    rows: list[dict[str, object]] = []
    for candidate in kinds.get("CANDIDATE_ACTIVATION", ()):
        candidate_identity = str(candidate["object_identity"])
        if candidate_identity in entries_by_candidate:
            continue
        terminal = terminals_by_candidate.get(candidate_identity)
        terminal_payload = _payload(terminal) if terminal is not None else {}
        terminal_outcome = terminal_payload.get("terminal_outcome")
        terminal_unknown_reasons = terminal_payload.get("terminal_unknown_reasons", [])
        rows.append(
            {
                "candidate_identity": candidate_identity,
                "active_episode_identity": _payload(candidate).get("active_episode_identity"),
                "candidate_formed_fact_boundary": _payload(candidate).get(
                    "candidate_activation_fact_boundary"
                ),
                "admission_refresh_terminal_outcome": terminal_outcome,
                "admission_refresh_unknown_reasons": terminal_unknown_reasons,
                "admission_component_pair_timing": terminal_payload.get("component_pair_timing"),
                "admission_component_pair_limits": terminal_payload.get("component_pair_limits"),
                "matched_refresh_source_identity": terminal_payload.get(
                    "matched_response_identity"
                ),
                "shadow_entry_identity": None,
                "execution_model": None,
                "entry_component_pair_identity": None,
                "entry_component_legs": None,
                "simulated_entry_price_valuation_per_btc": None,
                "simulated_entry_price_availability": "UNKNOWN",
                "simulated_entry_price_basis": None,
                "simulated_entry_credit_valuation": None,
                "native_premium_currency": None,
                "native_gross_entry_credit": None,
                "native_entry_fee_reserve": None,
                "native_net_entry_credit": None,
                "entry_valuation_index_price": None,
                "target_quantity_btc": str(policies.underwriting.target_base_quantity_btc),
                "entry_consumed_levels": None,
                "no_entry_reason": (
                    ",".join(str(value) for value in terminal_unknown_reasons)
                    if isinstance(terminal_unknown_reasons, list) and terminal_unknown_reasons
                    else terminal_outcome or "PENDING_REFRESH"
                ),
                "simulation_label": SIMULATION_LABEL,
                "selection_score_packet": None,
                "entry_refresh_score_packet": None,
            }
        )
    candidate_ids = {
        str(value["object_identity"]) for value in kinds.get("CANDIDATE_ACTIVATION", ())
    }
    for terminal in terminals_by_candidate.values():
        terminal_payload = _payload(terminal)
        terminal_candidate_identity = terminal_payload.get("candidate_identity")
        if (
            not isinstance(terminal_candidate_identity, str)
            or terminal_candidate_identity in candidate_ids
            or terminal_candidate_identity in entries_by_candidate
        ):
            continue
        terminal_unknown_reasons = terminal_payload.get("terminal_unknown_reasons", [])
        terminal_outcome = terminal_payload.get("terminal_outcome")
        rows.append(
            {
                "candidate_identity": terminal_candidate_identity,
                "active_episode_identity": terminal_payload.get("active_episode_identity"),
                "candidate_formed_fact_boundary": None,
                "admission_refresh_terminal_outcome": terminal_outcome,
                "admission_refresh_unknown_reasons": terminal_unknown_reasons,
                "admission_component_pair_timing": terminal_payload.get("component_pair_timing"),
                "admission_component_pair_limits": terminal_payload.get("component_pair_limits"),
                "matched_refresh_source_identity": terminal_payload.get(
                    "matched_response_identity"
                ),
                "shadow_entry_identity": None,
                "execution_model": None,
                "entry_component_pair_identity": None,
                "entry_component_legs": None,
                "simulated_entry_price_valuation_per_btc": None,
                "simulated_entry_price_availability": "UNKNOWN",
                "simulated_entry_price_basis": None,
                "simulated_entry_credit_valuation": None,
                "native_premium_currency": None,
                "native_gross_entry_credit": None,
                "native_entry_fee_reserve": None,
                "native_net_entry_credit": None,
                "entry_valuation_index_price": None,
                "target_quantity_btc": str(policies.underwriting.target_base_quantity_btc),
                "entry_consumed_levels": None,
                "no_entry_reason": (
                    ",".join(str(value) for value in terminal_unknown_reasons)
                    if isinstance(terminal_unknown_reasons, list) and terminal_unknown_reasons
                    else terminal_outcome or "PENDING_REFRESH"
                ),
                "simulation_label": SIMULATION_LABEL,
                "selection_score_packet": None,
                "entry_refresh_score_packet": None,
            }
        )
    for entry in kinds.get("SHADOW_ENTRY", ()):
        entry_payload = _payload(entry)
        tracking = _entry_tracking_projection(entry)
        candidate_identity = str(entry_payload.get("candidate_identity"))
        target_quantity = entry_payload.get("full_quantity_btc") or str(
            policies.underwriting.target_base_quantity_btc
        )
        entry_price = _component_vertical_credit_per_btc(
            entry_payload.get("entry_component_legs"),
            target_quantity,
        )
        rows.append(
            {
                "candidate_identity": candidate_identity,
                "active_episode_identity": entry_payload.get("active_episode_identity"),
                "candidate_formed_fact_boundary": None,
                "admission_refresh_terminal_outcome": "ENTRY_EMITTED",
                "admission_refresh_unknown_reasons": [],
                "admission_component_pair_timing": entry_payload.get("entry_component_pair_timing"),
                "admission_component_pair_limits": None,
                "matched_refresh_source_identity": entry_payload.get(
                    "entry_component_pair_identity"
                ),
                "shadow_entry_identity": str(entry["object_identity"]),
                "execution_model": entry_payload.get("execution_model"),
                "entry_component_pair_identity": entry_payload.get("entry_component_pair_identity"),
                "entry_component_pair_timing": entry_payload.get("entry_component_pair_timing"),
                "entry_fact_boundary": entry_payload.get("entry_fact_boundary"),
                "entry_component_quote_source_refs": entry_payload.get(
                    "entry_component_quote_source_refs"
                ),
                "entry_component_legs": _workbench_component_legs(
                    entry_payload.get("entry_component_legs")
                ),
                "simulated_entry_price_valuation_per_btc": entry_price,
                "simulated_entry_price_availability": (
                    "AVAILABLE_FROM_SHADOW_ENTRY_STRESSED_COMPONENT_LEGS"
                    if entry_price is not None
                    else "UNKNOWN"
                ),
                "simulated_entry_price_basis": (
                    "SHORT_STRESSED_SELL_VWAP_MINUS_LONG_STRESSED_BUY_VWAP"
                    if entry_price is not None
                    else None
                ),
                "simulated_entry_credit_valuation": entry_payload.get("gross_entry_credit_usdc"),
                "native_premium_currency": entry_payload.get("native_premium_currency"),
                "native_gross_entry_credit": entry_payload.get("native_gross_entry_credit"),
                "native_entry_fee_reserve": entry_payload.get("native_entry_fee_reserve"),
                "native_net_entry_credit": entry_payload.get("native_net_entry_credit"),
                "entry_valuation_index_price": entry_payload.get("entry_valuation_index_price"),
                "target_quantity_btc": target_quantity,
                "no_entry_reason": None,
                "simulation_label": SIMULATION_LABEL,
                "selection_score_packet": entry_payload.get("selection_score_packet"),
                "entry_refresh_score_packet": entry_payload.get("entry_refresh_score_packet"),
                **tracking,
            }
        )
    return rows


def _position_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
    policies: PolicyChain,
    *,
    trusted_time: TimeInterval | None,
    option_metadata: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    evaluations = {
        str(value["object_identity"]): value for value in kinds.get("POSITION_EVALUATION", ())
    }
    actions_by_entry: dict[str, list[Mapping[str, object]]] = {}
    for action_value in kinds.get("POSITION_ACTION", ()):
        evaluation = evaluations.get(
            str(_payload(action_value).get("position_evaluation_identity"))
        )
        if evaluation is None:
            continue
        entry_identity = str(_payload(evaluation).get("shadow_entry_identity"))
        actions_by_entry.setdefault(entry_identity, []).append(action_value)
    quotes_by_entry = _group_by_payload_key(
        kinds.get("CLOSE_QUOTE_EVALUATION", ()),
        "shadow_entry_identity",
    )
    opportunities_by_entry = _group_by_payload_key(
        kinds.get("CLOSE_OPPORTUNITY_EVALUATION", ()),
        "shadow_entry_identity",
    )
    selected_by_entry = {
        str(_payload(value).get("shadow_entry_identity")): value
        for value in kinds.get("SHADOW_CLOSE_OPPORTUNITY", ())
    }
    outcome_values = (
        *kinds.get("SHADOW_OUTCOME", ()),
        *kinds.get("SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME", ()),
        *kinds.get("RADAR_SCORE_BAND_NO_TRADE_CONTROL_OUTCOME", ()),
    )
    outcomes_by_entry = {
        str(_payload(value).get("shadow_entry_identity")): value for value in outcome_values
    }
    expiry_by_leg = {
        str(value.get("semantic_identity")): value.get("expiration_timestamp_ms")
        for value in option_metadata
    }
    trusted = trusted_time
    rows: list[dict[str, object]] = []
    position_opens = (
        *kinds.get("SHADOW_ENTRY", ()),
        *kinds.get("SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN", ()),
        *kinds.get("RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN", ()),
    )
    for entry in position_opens:
        entry_identity = str(entry["object_identity"])
        entry_payload = _payload(entry)
        tracking = _entry_tracking_projection(entry)
        latest_action = _latest(actions_by_entry.get(entry_identity, ()))
        action_payload = _payload(latest_action) if latest_action is not None else {}
        quote = _latest(quotes_by_entry.get(entry_identity, ()))
        quote_payload = _payload(quote) if quote is not None else {}
        opportunity = _latest(opportunities_by_entry.get(entry_identity, ()))
        opportunity_payload = _payload(opportunity) if opportunity is not None else {}
        component_pair_timing = quote_payload.get("component_pair_timing") or (
            opportunity_payload.get("component_pair_timing")
        )
        component_pair_limits = quote_payload.get("component_pair_limits") or (
            opportunity_payload.get("component_pair_limits")
        )
        component_pair_unknown_reasons = quote_payload.get(
            "component_pair_unknown_reasons", []
        ) or opportunity_payload.get("component_pair_unknown_reasons", [])
        selected = selected_by_entry.get(entry_identity)
        outcome = outcomes_by_entry.get(entry_identity)
        outcome_payload = _payload(outcome) if outcome is not None else {}
        leg_ids = entry_payload.get("canonical_leg_identities")
        expiry_value = entry_payload.get("expiry_ms")
        expiry_ms = expiry_value if isinstance(expiry_value, int) else None
        if expiry_ms is None and isinstance(leg_ids, list):
            expiries: set[int] = set()
            for identity in leg_ids:
                option_expiry = expiry_by_leg.get(str(identity))
                if isinstance(option_expiry, int):
                    expiries.add(option_expiry)
            if len(expiries) == 1:
                expiry_ms = next(iter(expiries))
        hard_close_boundary_ms = (
            expiry_ms - policies.position.latest_exit_lead_ms
            if isinstance(expiry_ms, int)
            else None
        )
        countdown = (
            {
                "lower_ms": hard_close_boundary_ms - trusted.upper_ms,
                "upper_ms": hard_close_boundary_ms - trusted.lower_ms,
            }
            if hard_close_boundary_ms is not None and trusted is not None
            else None
        )
        gross_close_cashflow = _decimal_or_none(
            opportunity_payload.get("gross_close_cashflow_usdc")
        )
        remaining_premium = (
            str(max(Decimal(0), -gross_close_cashflow))
            if gross_close_cashflow is not None
            else None
        )
        rows.append(
            {
                "shadow_entry_identity": entry_identity,
                "enrollment_kind": entry_payload.get("enrollment_kind", "ADMITTED_SHADOW_TRADE"),
                "position_action": action_payload.get("serialized_action", "UNKNOWN"),
                "observation_quality": tracking["observation_quality"],
                "qualification_eligible": tracking["qualification_eligible"],
                "terminal_economics_eligible": outcome_payload.get(
                    "terminal_economics_eligible",
                    outcome_payload.get("terminal_state")
                    in {"MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN"},
                ),
                "continuous_path_eligible": (tracking["observation_quality"] == "CONTINUOUS"),
                "exit_acquisition_eligible": outcome_payload.get(
                    "exit_acquisition_eligible",
                    outcome_payload.get("terminal_state") in {"MATURE_KNOWN", "EXITED_KNOWN"}
                    and tracking["observation_quality"] == "CONTINUOUS",
                ),
                "position_lifecycle_state": (
                    "TERMINAL"
                    if outcome is not None
                    else "SETTLEMENT_PENDING"
                    if action_payload.get("serialized_action") == "CLOSE"
                    and isinstance(expiry_ms, int)
                    and trusted is not None
                    and trusted.lower_ms >= expiry_ms
                    else "EXIT_ACQUIRING"
                    if action_payload.get("serialized_action") == "CLOSE"
                    else "MONITORING"
                ),
                "remaining_premium_valuation": remaining_premium,
                "remaining_premium_availability": (
                    "AVAILABLE_FROM_PERSISTED_COMPONENT_CLOSE_ECONOMICS"
                    if remaining_premium is not None
                    else "UNKNOWN"
                ),
                "remaining_premium_basis": (
                    "MAX_ZERO_NEGATIVE_GROSS_CLOSE_CASHFLOW_VALUATION"
                    if remaining_premium is not None
                    else None
                ),
                "close_quote_state": quote_payload.get("close_quote_state", "UNKNOWN"),
                "component_pair_timing": component_pair_timing,
                "component_pair_limits": component_pair_limits,
                "component_pair_unknown_reasons": component_pair_unknown_reasons,
                "component_pair_business_state": (
                    "UNKNOWN" if component_pair_unknown_reasons else None
                ),
                "current_close_debit_valuation": opportunity_payload.get("net_close_debit_usdc"),
                "projected_shadow_pnl_valuation": opportunity_payload.get(
                    "projected_shadow_net_pnl_usdc"
                ),
                "native_premium_currency": opportunity_payload.get("native_premium_currency")
                or entry_payload.get("native_premium_currency"),
                "native_net_close_cashflow": opportunity_payload.get("native_net_close_cashflow"),
                "native_projected_shadow_net_pnl": opportunity_payload.get(
                    "native_projected_shadow_net_pnl"
                ),
                "boundary_valued_projected_shadow_net_pnl_usd": opportunity_payload.get(
                    "boundary_valued_projected_shadow_net_pnl_usd"
                ),
                "exit_valued_native_projected_pnl_usd": opportunity_payload.get(
                    "exit_valued_native_projected_pnl_usd"
                ),
                "hard_close_boundary_ms": hard_close_boundary_ms,
                "hard_close_countdown_interval_ms": countdown,
                "ordered_latched_exit_rules": action_payload.get(
                    "ordered_latched_close_reason_vector", []
                ),
                "primary_exit_rule": action_payload.get("primary_close_reason"),
                "close_opportunity_eligibility": opportunity_payload.get("eligibility"),
                "close_opportunity_reason": opportunity_payload.get("eligibility_reason"),
                "valid_shadow_close_opportunity": selected is not None,
                "shadow_close_opportunity_identity": (
                    str(selected["object_identity"]) if selected is not None else None
                ),
                "outcome_state": (
                    outcome_payload.get("terminal_state") if outcome is not None else "PENDING"
                ),
            }
        )
    return rows


def _entry_tracking_projection(entry: Mapping[str, object]) -> dict[str, object]:
    payload = _payload(entry)
    outer_runtime = entry.get("runtime_identity")
    if not isinstance(outer_runtime, str) or not outer_runtime:
        raise TypeError("SHADOW_ENTRY.runtime_identity must be a non-empty string")

    present = _ENTRY_TRACKING_PAYLOAD_KEYS.intersection(payload)
    if present != _ENTRY_TRACKING_PAYLOAD_KEYS:
        missing = sorted(_ENTRY_TRACKING_PAYLOAD_KEYS - present)
        raise ValueError(f"SHADOW_ENTRY recovery tracking payload is incomplete: {missing!r}")

    origin_runtime = payload["origin_runtime_identity"]
    if not isinstance(origin_runtime, str) or not origin_runtime:
        raise TypeError("origin_runtime_identity must be a non-empty string")
    segment_identity = payload["current_segment_identity"]
    segment_sequence = payload["current_segment_sequence"]
    observation_quality = payload["observation_quality"]
    if (
        not isinstance(observation_quality, str)
        or observation_quality not in _OBSERVATION_QUALITIES
    ):
        raise ValueError("observation_quality must be CONTINUOUS or GAPPED")
    gap_count = _integer(payload["gap_count"], "gap_count")
    _require_count(gap_count, "gap_count")
    qualification_eligible = payload["qualification_eligible"]
    if not isinstance(qualification_eligible, bool):
        raise TypeError("qualification_eligible must be boolean")
    tracking_state = payload["tracking_state"]
    if not isinstance(tracking_state, str) or tracking_state not in _TRACKING_STATES:
        raise ValueError("tracking_state must be RECOVERING or ACTIVE")
    if segment_identity is None:
        if tracking_state != "RECOVERING" or segment_sequence is not None:
            raise TypeError(
                "only a RECOVERING Entry may lack current Segment identity and sequence"
            )
    elif not isinstance(segment_identity, str) or not segment_identity:
        raise TypeError("current_segment_identity must be a non-empty string or null")
    elif tracking_state == "RECOVERING" or segment_sequence is None:
        raise TypeError("an ACTIVE Entry requires current Segment identity and sequence")
    else:
        segment_sequence = _integer(segment_sequence, "current_segment_sequence")
        _require_count(segment_sequence, "current_segment_sequence")
    post_close_attempt_state = payload["post_close_attempt_state"]
    if post_close_attempt_state is not None and (
        not isinstance(post_close_attempt_state, str)
        or post_close_attempt_state not in _POST_CLOSE_ATTEMPT_STATES
    ):
        raise ValueError("post_close_attempt_state is not an allowed lifecycle state")

    if observation_quality == "CONTINUOUS" and gap_count != 0:
        raise ValueError("CONTINUOUS observation_quality requires gap_count zero")
    if observation_quality == "GAPPED":
        if gap_count == 0:
            raise ValueError("GAPPED observation_quality requires a positive gap_count")
        if qualification_eligible:
            raise ValueError("GAPPED observation_quality cannot be qualification eligible")
    if tracking_state == "RECOVERING" and observation_quality != "GAPPED":
        raise ValueError("RECOVERING tracking_state requires GAPPED observation quality")

    return {
        "origin_runtime_identity": origin_runtime,
        "current_segment_identity": segment_identity,
        "current_segment_sequence": segment_sequence,
        "observation_quality": observation_quality,
        "gap_count": gap_count,
        "qualification_eligible": qualification_eligible,
        "tracking_state": tracking_state,
        "post_close_attempt_state": post_close_attempt_state,
    }


def _outcome_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    outcomes_by_observation = {
        str(_payload(value).get("shadow_observation_identity")): value
        for value in kinds.get("SHADOW_OUTCOME", ())
    }
    rows: list[dict[str, object]] = []
    for observation in kinds.get("SHADOW_OUTCOME_OBSERVATION", ()):
        payload = _payload(observation)
        observation_identity = str(observation["object_identity"])
        outcome = outcomes_by_observation.get(observation_identity)
        outcome_payload = _payload(outcome) if outcome is not None else {}
        rows.append(
            {
                "shadow_observation_identity": observation_identity,
                "shadow_entry_identity": payload.get("shadow_entry_identity"),
                "state": outcome_payload.get("terminal_state", "PENDING"),
                "terminal_method": outcome_payload.get("terminal_method"),
                "terminal_economics_eligible": outcome_payload.get(
                    "terminal_economics_eligible",
                    outcome_payload.get("terminal_state")
                    in {"MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN"},
                ),
                "continuous_path_eligible": outcome_payload.get(
                    "continuous_path_eligible",
                    payload.get("observation_quality") == "CONTINUOUS",
                ),
                "exit_acquisition_eligible": outcome_payload.get(
                    "exit_acquisition_eligible", False
                ),
                "maturity": _outcome_maturity(
                    cast(str, outcome_payload.get("terminal_state", "PENDING"))
                ),
                "selected_exit_identity": outcome_payload.get("selected_exit_identity"),
                "censor_mask": outcome_payload.get("censor_mask"),
                "public_quote_net_pnl_valuation": (
                    outcome_payload.get("net_pnl_after_public_standard_fee_reserve_usdc")
                ),
                "native_premium_currency": outcome_payload.get("native_premium_currency"),
                "native_net_pnl": outcome_payload.get("native_net_pnl"),
                "boundary_valued_net_pnl_usd": outcome_payload.get("boundary_valued_net_pnl_usd"),
                "exit_valued_native_net_pnl_usd": outcome_payload.get(
                    "exit_valued_native_net_pnl_usd"
                ),
                "delivery_price_valuation_per_btc": outcome_payload.get(
                    "delivery_price_usdc_per_btc"
                ),
                "official_delivery_price_source_ref": outcome_payload.get(
                    "official_delivery_price_source_ref"
                ),
                "actual_pnl": outcome_payload.get("actual_pnl_usdc"),
                "actual_availability": outcome_payload.get("actual_availability", "UNKNOWN"),
            }
        )
    return rows


def _outcome_maturity(state: str) -> str:
    if state in {"MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN"}:
        return "KNOWN_TERMINAL"
    if state in {"MATURE_UNKNOWN", "TERMINAL_UNKNOWN"}:
        return "UNKNOWN_TERMINAL"
    if state in {"CENSORED_AT_STOP", "CENSORED_AT_FAILURE"}:
        return "CENSORED"
    return "PENDING"


def _settled_status(
    reducer: RadarReducer,
    *,
    phase: ServicePhase,
    recorded_monotonic_ms: int,
) -> ServiceStatus:
    coverage = reducer.current_coverage_state
    reason = reducer.current_coverage_blocking_reason
    if reason in _INTERRUPTED_REASONS:
        data_state = DataState.INTERRUPTED
    elif reason in _STALE_REASONS:
        data_state = DataState.STALE
    elif coverage is CoverageState.KNOWN_COMPLETE:
        data_state = DataState.CURRENT
        reason = CoverageBlockingReason.NONE.value
    elif coverage is CoverageState.KNOWN_DEGRADED:
        data_state = DataState.DEGRADED
    else:
        data_state = DataState.UNKNOWN
    health = phase not in {ServicePhase.STOPPED, ServicePhase.FAILED}
    ready = (
        health
        and phase is ServicePhase.RUNNING
        and reducer.session_established
        and data_state is DataState.CURRENT
    )
    return ServiceStatus(
        phase,
        data_state,
        health,
        ready,
        data_state is DataState.STALE,
        reason,
        recorded_monotonic_ms,
    )


def _status_object(status: ServiceStatus) -> dict[str, object]:
    return {
        "phase": status.phase.value,
        "data_state": status.data_state.value,
        "health": status.health,
        "ready": status.ready,
        "stale": status.stale,
        "reason": status.reason,
        "recorded_monotonic_ms": status.recorded_monotonic_ms,
    }


def _status_key(status: ServiceStatus) -> tuple[object, ...]:
    return (
        status.phase,
        status.data_state,
        status.health,
        status.ready,
        status.stale,
        status.reason,
    )


def _product_object(product: OptionProductSpec) -> dict[str, object]:
    return {
        "product_spec_identity": product.identity,
        "name": product.name.value,
        "market_family": product.market_family,
        "economic_semantics_version": product.economic_semantics_version,
        "case_schema_version": product.case_schema_version,
        "public_currency": product.public_currency,
        "base_currency": product.base_currency,
        "quote_currency": product.quote_currency,
        "settlement_currency": product.settlement_currency,
        "counter_currency": product.counter_currency,
        "price_index": product.price_index,
        "instrument_type": product.instrument_type,
        "native_premium_currency": product.native_premium_currency,
        "valuation_currency": product.valuation_currency,
        "strike_currency": product.strike_currency,
        "model_premium_rule": product.model_premium_rule,
        "valuation_rule": product.valuation_rule,
        "fee_rule": product.fee_rule,
        "native_settlement_payoff_rule": product.native_settlement_payoff_rule,
        "native_settlement_liability_profile": product.native_settlement_liability_profile,
        "actual_account_margin_requirement": None,
        "actual_account_margin_availability": product.actual_account_margin_availability,
        "actual_account_margin_reason": product.actual_account_margin_reason,
    }


def _empty_business_projection(product: OptionProductSpec) -> dict[str, object]:
    empty = {
        "panel_state": PanelState.EMPTY_NO_SETTLED_OBJECT.value,
        "empty_label": EMPTY_PANEL_LABEL,
        "rows": [],
    }
    return {
        "published_fact_boundary": None,
        "funnel": FunnelTracker().snapshot().as_object(),
        "system": {
            "session_epoch": None,
            "platform_usable": False,
            "platform_reason": "NOT_STARTED",
            "latest_market_event_timestamp_ms": None,
            "latest_market_event_age_ms": None,
            "last_wire_message_age_ms": None,
            "last_queue_processing_lag_ms": None,
            "queue_lag_deadline_ms": None,
            "queue_lag_currentness_active": False,
            "coverage_state": CoverageState.UNKNOWN.value,
            "coverage_blocking_reason": "NOT_STARTED",
            "coverage_affected_scopes": ["GLOBAL"],
            "coverage_ratio_percent": None,
            "known_current_instrument_evaluation_count": 0,
            "monitored_instrument_count": 0,
            "reconnect_count": 0,
            "session_gap_count": 0,
            "global_continuity_epoch": 1,
            "disconnect_records": [],
            "index_history": {
                "source": (f"DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_{product.price_index.upper()}_2D"),
                "value_semantics": "AVERAGE_INDEX_PRICE",
                "availability": "UNKNOWN",
                "reason": "NOT_STARTED",
                "source_point_count": None,
                "interval_counts": [],
                "modal_interval_ms": None,
                "newest_response_timestamp_ms": None,
                "newest_response_age_ms": None,
                "newest_response_point_excluded_by_completion_cutoff": False,
                "latest_source_timestamp_ms": None,
                "latest_source_age_ms": None,
                "exact_suffix_point_count": 0,
                "exact_suffix_minutes": 0,
                "revision_count": 0,
                "revision_pending": False,
                "revised_timestamps_ms": [],
            },
        },
        "zero_claims": {
            "anomaly": zero_anomaly_claim(
                active_anomaly_count=0,
                monitor_denominator=None,
                monitor_complete=False,
            ).as_object(),
            "candidate": zero_candidate_claim(
                candidate_count=0,
                underwriting_evaluable_denominator=None,
            ).as_object(),
        },
        "radar": dict(empty),
        "underwriting": {**empty, "predicate_margin_summary": []},
        "decision_controls": dict(empty),
        "shadow_entries": {**empty, "simulation_label": SIMULATION_LABEL},
        "positions": dict(empty),
        "outcomes": dict(empty),
    }


def _objects_by_kind(
    objects: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for value in objects:
        kind = value.get("object_kind")
        if isinstance(kind, str):
            result.setdefault(kind, []).append(value)
    return result


def _latest_by_payload_key(
    values: Sequence[Mapping[str, object]],
    key: str,
) -> list[Mapping[str, object]]:
    grouped = _group_by_payload_key(values, key)
    result: list[Mapping[str, object]] = []
    for _, members in sorted(grouped.items()):
        latest = _latest(members)
        if latest is not None:
            result.append(latest)
    return result


def _group_by_payload_key(
    values: Sequence[Mapping[str, object]],
    key: str,
) -> dict[str, list[Mapping[str, object]]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for value in values:
        member = _payload(value).get(key)
        if isinstance(member, str):
            result.setdefault(member, []).append(value)
    return result


def _latest(
    values: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    return max(values, key=_boundary_key, default=None)


def _boundary_key(value: Mapping[str, object]) -> tuple[int, int, int, int]:
    boundary = _mapping(value.get("fact_boundary"), "fact_boundary")
    return (
        _integer(boundary.get("causal_seq"), "causal_seq"),
        _integer(boundary.get("received_monotonic_ms"), "received_monotonic_ms"),
        _integer(boundary.get("session_epoch"), "session_epoch"),
        _integer(boundary.get("ingress_seq"), "ingress_seq"),
    )


def _payload(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {}
    return _mapping(value.get("payload"), "payload")


def _trusted_interval(reducer: RadarReducer, monotonic_ms: int) -> TimeInterval | None:
    if reducer.clock is None:
        return None
    try:
        return reducer.clock.interval_at(monotonic_ms)
    except (ContinuityGap, ValueError):
        return None


def _latency_projection(
    reducer: RadarReducer,
    commit: CausalCommit,
    trusted: TimeInterval | None,
) -> dict[str, object]:
    latest_source_ms = _latest_market_event_timestamp(reducer)
    return {
        "latest_market_event_timestamp_ms": latest_source_ms,
        "latest_market_event_age_ms": (
            None
            if trusted is None or latest_source_ms is None
            else max(0, trusted.upper_ms - latest_source_ms)
        ),
        "last_wire_message_age_ms": (
            None
            if reducer.last_wire_received_monotonic_ms <= 0
            else max(
                0,
                commit.boundary.received_monotonic_ms - reducer.last_wire_received_monotonic_ms,
            )
        ),
        "last_queue_processing_lag_ms": reducer.diagnostics.last_queue_processing_lag_ms,
        "queue_lag_deadline_ms": (reducer.policy.runtime_limits.notification_queue_lag_deadline_ms),
        "queue_lag_currentness_active": reducer.queue_lag_currentness_active,
    }


def _latest_market_event_timestamp(reducer: RadarReducer) -> int | None:
    values: list[int] = []
    if reducer.accepted_index_receipt is not None:
        values.append(reducer.accepted_index_receipt.source_timestamp_ms)
    values.extend(value.source_timestamp_ms for value in reducer.tickers.values())
    values.extend(value.source_timestamp_ms for value in reducer.accepted_book_receipts.values())
    return max(values) if values else None


def _disconnect_records(reducer: RadarReducer) -> list[dict[str, object]]:
    records = [
        dict(value)
        for value in reducer.diagnostics.global_continuity_restart_edges
        if value.get("failure_domain") == "SESSION" and value.get("reason") in _INTERRUPTED_REASONS
    ]
    return records[-20:]


def _ratio_percent(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return format(Decimal(numerator) * Decimal(100) / Decimal(denominator), "f")


def _decimal_interval(value: DecimalInterval) -> dict[str, str]:
    return {"lower": str(value.lower), "upper": str(value.upper)}


def _score_packet_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    projector = getattr(value, "as_object", None)
    if not callable(projector):
        raise TypeError("Radar score packet must expose as_object()")
    projected = projector()
    if not isinstance(projected, Mapping):
        raise TypeError("Radar score packet projection must be an object")
    return dict(projected)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return parsed if parsed.is_finite() else None


def _component_vertical_credit_per_btc(legs: object, full_quantity: object) -> str | None:
    quantity = _decimal_or_none(full_quantity)
    if quantity is None or quantity <= 0 or not isinstance(legs, list) or len(legs) != 2:
        return None
    by_role: dict[str, Mapping[str, object]] = {}
    for leg in legs:
        if not isinstance(leg, Mapping):
            return None
        role = leg.get("canonical_leg_role")
        if not isinstance(role, str) or role in by_role:
            return None
        by_role[role] = leg
    short = by_role.get("SHORT")
    long = by_role.get("LONG")
    if (
        short is None
        or long is None
        or short.get("action") != "SELL"
        or long.get("action") != "BUY"
    ):
        return None
    short_price = _decimal_or_none(short.get("stressed_vwap_usdc_per_btc"))
    long_price = _decimal_or_none(long.get("stressed_vwap_usdc_per_btc"))
    if short_price is None or long_price is None:
        return None
    return canonical_decimal(short_price - long_price)


def _workbench_component_legs(legs: object) -> list[dict[str, object]] | None:
    """Project legacy runtime component fields into Workbench-owned product-neutral names."""
    if legs is None:
        return None
    if not isinstance(legs, list):
        return None
    projected: list[dict[str, object]] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            return None
        projected.append(
            {
                "canonical_leg_role": leg.get("canonical_leg_role"),
                "instrument_name": leg.get("instrument_name"),
                "action": leg.get("action"),
                "native_premium_currency": leg.get("native_premium_currency"),
                "valuation_index_price": leg.get("valuation_index_price"),
                "raw_consumed_levels_native": leg.get("raw_consumed_levels_native"),
                "raw_vwap_native": leg.get("raw_vwap_native"),
                "stressed_consumed_levels_native": leg.get("stressed_consumed_levels_native"),
                "stressed_vwap_native": leg.get("stressed_vwap_native"),
                "native_fee_reserve": leg.get("native_fee_reserve"),
                "raw_consumed_levels_valuation": _workbench_valuation_levels(
                    leg.get("raw_consumed_levels")
                ),
                "raw_vwap_valuation_per_btc": leg.get("raw_vwap_usdc_per_btc"),
                "stressed_consumed_levels_valuation": _workbench_valuation_levels(
                    leg.get("stressed_consumed_levels")
                ),
                "stressed_vwap_valuation_per_btc": leg.get("stressed_vwap_usdc_per_btc"),
                "fee_reserve_valuation": leg.get("fee_reserve_usdc"),
            }
        )
    return projected


def _workbench_valuation_levels(levels: object) -> list[dict[str, object]] | None:
    if levels is None:
        return None
    if not isinstance(levels, list):
        return None
    projected: list[dict[str, object]] = []
    for level in levels:
        if not isinstance(level, Mapping):
            return None
        projected.append(
            {
                "price_valuation_per_btc": level.get("price_usdc_per_btc"),
                "amount_btc": level.get("amount_btc"),
            }
        )
    return projected


def _runtime_boundary_object(commit: CausalCommit) -> dict[str, object]:
    boundary = commit.boundary
    return {
        "session_epoch": boundary.session_epoch,
        "ingress_seq": boundary.ingress_seq,
        "received_monotonic_ms": boundary.received_monotonic_ms,
        "causal_seq": boundary.causal_seq,
        "cause": commit.cause.value,
    }


def _json_value_bytes(value: object) -> bytes:
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return _json_value_bytes(value) + b"\n"


def _json_bytes_with_preencoded_members(
    value: Mapping[str, object],
    preencoded_members: Mapping[str, bytes],
) -> bytes:
    unknown = set(preencoded_members) - set(value)
    if unknown:
        raise ValueError(f"preencoded JSON members are absent from document: {sorted(unknown)!r}")
    members: list[bytes] = []
    for key in sorted(value):
        if not isinstance(key, str):
            raise TypeError("workbench JSON object keys must be strings")
        encoded = preencoded_members.get(key)
        if encoded is None:
            encoded = _json_value_bytes(value[key])
        elif not isinstance(encoded, bytes) or not encoded:
            raise TypeError("preencoded JSON member must be nonempty bytes")
        members.append(_json_value_bytes(key) + b":" + encoded)
    return b"{" + b",".join(members) + b"}\n"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be boolean")
    return value


def _require_count(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server_version = "OptimatrixReadOnly/1"

    def __getattr__(self, name: str) -> Callable[[], None]:
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    @property
    def _store(self) -> SnapshotStore:
        return cast(WorkbenchHTTPServer, self.server).snapshot_store

    def do_GET(self) -> None:
        self._serve(head=False)

    def do_HEAD(self) -> None:
        self._serve(head=True)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _serve(self, *, head: bool) -> None:
        path = self.path.split("?", 1)[0]
        snapshot = self._store.read()
        if path == "/":
            self._response(HTTPStatus.OK, "text/html; charset=utf-8", HTML.encode(), head)
        elif path == "/app.js":
            self._response(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                JS.encode(),
                head,
            )
        elif path == "/styles.css":
            self._response(HTTPStatus.OK, "text/css; charset=utf-8", CSS.encode(), head)
        elif path == "/api/workbench/current":
            self._response(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                snapshot.workbench_body,
                head,
            )
        elif path == "/healthz":
            self._response(
                HTTPStatus.OK if snapshot.health else HTTPStatus.SERVICE_UNAVAILABLE,
                "application/json; charset=utf-8",
                snapshot.health_body,
                head,
            )
        elif path == "/readyz":
            self._response(
                HTTPStatus.OK if snapshot.ready else HTTPStatus.SERVICE_UNAVAILABLE,
                "application/json; charset=utf-8",
                snapshot.ready_body,
                head,
            )
        else:
            self._response(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n", head)

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, HEAD")
        self._security_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _response(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        head: bool,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'",
        )


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        snapshot_store: SnapshotStore,
    ) -> None:
        self.snapshot_store = snapshot_store
        self.address_family = (
            socket.AF_INET6
            if ipaddress.ip_address(server_address[0]).version == 6
            else socket.AF_INET
        )
        super().__init__(server_address, WorkbenchRequestHandler)


class LoopbackWorkbenchServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        store: SnapshotStore,
    ) -> None:
        validated_host, validated_port = validate_loopback_endpoint(host, port)
        self._server = WorkbenchHTTPServer((validated_host, validated_port), store)
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("workbench server already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="optimatrix-read-only-workbench",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        thread = self._thread
        if thread is not None:
            self._server.shutdown()
            thread.join()
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> LoopbackWorkbenchServer:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


def validate_loopback_endpoint(host: str, port: int) -> tuple[str, int]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("workbench host must be an explicit loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("workbench may bind only to loopback")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("workbench port must be within [0, 65535]")
    return str(address), port

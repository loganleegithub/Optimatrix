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
from options_domain import LINEAR_BTC_USDC, OptionProductSpec, product_for_identity
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

WORKBENCH_SCHEMA_VERSION = 5
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
        self._last_business: Mapping[str, object] = MappingProxyType(
            _empty_business_projection(self.product)
        )
        self._latest_reducer: RadarReducer | None = None
        self._latest_commit: CausalCommit | None = None
        self._dirty = False
        self._business_dirty = False
        self._cached_downstream_revision: int | None = None
        self._cached_underwriting_metadata: tuple[Mapping[str, object], ...] | None = None
        self._cached_admission_terminal_diagnostics: tuple[Mapping[str, object], ...] | None = None
        self._cached_downstream_projection: _DownstreamProjection | None = None
        self._admission_terminal_diagnostics_by_episode: dict[str, Mapping[str, object]] = {}
        initial_document = self._document(self._last_business, status=self._status)
        self._preencoded_members = {
            key: _json_value_bytes(initial_document[key])
            for key in (
                "schema_version",
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
    product: OptionProductSpec = LINEAR_BTC_USDC,
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
    latest_source_ms = _latest_market_timestamp(reducer)
    data_delay_ms = (
        None
        if trusted is None or latest_source_ms is None
        else max(0, trusted.upper_ms - latest_source_ms)
    )
    last_wire_age_ms = (
        None
        if reducer.last_wire_received_monotonic_ms <= 0
        else max(
            0,
            commit.boundary.received_monotonic_ms - reducer.last_wire_received_monotonic_ms,
        )
    )
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
            "latest_market_timestamp_ms": latest_source_ms,
            "data_delay_ms": data_delay_ms,
            "last_wire_age_ms": last_wire_age_ms,
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
                    f"DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_{reducer.product.price_index.upper()}_1D"
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
        product = getattr(instrument, "product", LINEAR_BTC_USDC)
        result = reducer.results.get(name)
        tracker = reducer.trackers.get(name)
        calculation = result.calculation if result is not None else None
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
                        else "OFFICIAL_INDEX_CHART_AVERAGE_PRICE_RV"
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
                    str(review.surface.executable_bid_iv_minus_local_mark_iv)
                    if review is not None
                    and review.surface.executable_bid_iv_minus_local_mark_iv is not None
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
    entries_by_scope = {
        str(_payload(value).get("radar_scope_identity")): value
        for value in kinds.get("SHADOW_ENTRY", ())
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
        admitted_entry = entries_by_scope.get(str(scope_identity))
        if admitted_entry is not None:
            admitted_candidate = _payload(admitted_entry).get("candidate_identity")
            candidate_identity = (
                str(admitted_candidate)
                if isinstance(admitted_candidate, str)
                else candidate_identity
            )
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
                "refresh_terminal_outcome": refresh_terminal_outcome,
                "refresh_unknown_reasons": refresh_unknown_reasons,
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
            }
        )
    for entry in kinds.get("SHADOW_ENTRY", ()):
        entry_payload = _payload(entry)
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
    outcomes_by_entry = {
        str(_payload(value).get("shadow_entry_identity")): value
        for value in kinds.get("SHADOW_OUTCOME", ())
    }
    expiry_by_leg = {
        str(value.get("semantic_identity")): value.get("expiration_timestamp_ms")
        for value in option_metadata
    }
    trusted = trusted_time
    rows: list[dict[str, object]] = []
    for entry in kinds.get("SHADOW_ENTRY", ()):
        entry_identity = str(entry["object_identity"])
        entry_payload = _payload(entry)
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
                "position_action": action_payload.get("serialized_action", "UNKNOWN"),
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
                    _payload(outcome).get("terminal_state") if outcome is not None else "PENDING"
                ),
            }
        )
    return rows


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
                "actual_pnl": outcome_payload.get("actual_pnl_usdc"),
                "actual_availability": outcome_payload.get("actual_availability", "UNKNOWN"),
            }
        )
    return rows


def _outcome_maturity(state: str) -> str:
    if state == "MATURE_KNOWN":
        return "MATURE_KNOWN"
    if state == "MATURE_UNKNOWN":
        return "MATURE_UNKNOWN"
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
            "latest_market_timestamp_ms": None,
            "data_delay_ms": None,
            "last_wire_age_ms": None,
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
                "source": (f"DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_{product.price_index.upper()}_1D"),
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


def _latest_market_timestamp(reducer: RadarReducer) -> int | None:
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


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Optimatrix 交易员工作台</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header><h1>Optimatrix 只读交易员工作台</h1><p id="runtime"></p><p id="connection" class="warning" role="alert" hidden></p></header>
  <main>
    <section><h2>交易摘要</h2><div id="system" class="grid"></div></section>
    <section><h2>业务漏斗</h2><div id="funnel"></div></section>
    <section><h2>Selected Decision 研究闭环</h2><p class="warning">独立研究样本, 非 Candidate 的 Case 不是交易。</p><div id="decision-control"></div></section>
    <section><h2>业务零值证明</h2><div id="zero" class="grid"></div></section>
    <section><h2>Radar 可信候选</h2><div id="radar"></div></section>
    <section><h2>承保详情</h2><div id="underwriting"></div></section>
    <section><h2>Shadow 入场</h2><p class="warning">模拟入场, 不是订单或成交</p><div id="shadow"></div></section>
    <section><h2>持仓管理</h2><div id="positions"></div></section>
    <section><h2>Outcome</h2><div id="outcomes"></div></section>
  </main>
  <footer>只读 public-only 投影; 无 Policy 修改、私有账户或下单能力。</footer>
  <script src="/app.js" defer></script>
</body>
</html>
"""

CSS = """*{box-sizing:border-box}[hidden]{display:none!important}html,body{max-width:100%;overflow-x:hidden}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#e6edf3}header,footer{padding:20px 5vw;background:#161b22}main{max-width:1600px;margin:0 auto;padding:20px 5vw}section{min-width:0;margin:0 0 24px;padding:18px;background:#161b22;border:1px solid #30363d;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.card{min-width:0;padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow-wrap:anywhere}.label{color:#8b949e;font-size:.85rem}.value{font-weight:650;margin-top:4px}.warning{padding:10px;border:1px solid #d29922;background:#2d2308;border-radius:8px}.system-details{margin-top:12px}.system-details>summary{cursor:pointer;color:#58a6ff}.system-details>.grid{margin-top:10px}.panel-toolbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin:0 0 10px}.panel-toolbar label{color:#8b949e}.panel-toolbar select{margin-left:8px;padding:6px 8px;color:#e6edf3;background:#0d1117;border:1px solid #30363d;border-radius:6px}.table-scroll{max-width:100%;overflow-x:auto}.table-scroll table{min-width:900px;width:100%;border-collapse:collapse;font-size:.88rem}th,td{padding:8px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}th{position:sticky;top:0;color:#8b949e;background:#161b22;z-index:1}.empty{color:#d29922}.UNKNOWN,.STALE,.INTERRUPTED,.state-unknown{color:#f0883e}.CURRENT,.PROVEN_ZERO,.ANOMALY_ACTIVE,.EVALUABLE{color:#3fb950}.DEGRADED,.NOT_EVALUATED{color:#d29922}.na{color:#8b949e}.raw-details{max-width:360px}.raw-details summary{cursor:pointer;color:#58a6ff}.raw-details dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 8px}.raw-details dt{color:#8b949e}.raw-details dd{margin:0;overflow-wrap:anywhere;font-family:ui-monospace,SFMono-Regular,monospace;font-size:.78rem}@media(max-width:800px){header,footer,main{padding-left:16px;padding-right:16px}.grid{grid-template-columns:1fr}}"""

JS = r"""const SUPPORTED_SCHEMA_VERSION = 5;
const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[character]);
const isMissing = value => value === null || value === undefined || value === '';
const displayText = value => {
  if (value === null || value === undefined || value === '') return 'UNKNOWN';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};
const safeText = value => escapeHtml(displayText(value));
const rawText = value => isMissing(value)
  ? 'null'
  : (typeof value === 'object' ? JSON.stringify(value) : String(value));
const card = (label, value) =>
  `<div class="card"><div class="label">${escapeHtml(label)}</div>` +
  `<div class="value">${safeText(value)}</div></div>`;
const reasonLabels = {
  QUEUE_LAG_CURRENTNESS: '处理队列延迟, 行情时效性不可确认',
  CLOCK_GAP: '可信时间不连续',
  INDEX_WARMUP: '指数基线处于启动或恢复 warmup',
  INDEX_WINDOW_GAP: '指数基线窗口存在缺口',
  INDEX_SOURCE_STALE: '指数来源已陈旧',
  INDEX_CONTINUITY_GAP: '指数行情连续性中断',
  INDEX_HISTORY_REVISION: '官方指数历史已完成点发生修订, 等待下一响应确认',
  OPTION_BOOK_UNKNOWN: '期权簿不可确认',
  OPTION_AMOUNT_METADATA_UNKNOWN: '期权数量元数据不可确认',
  OPTION_PRICE_TICK_METADATA_UNKNOWN: '官方价格 tick 规则不可确认',
  INSUFFICIENT_TARGET_ASK_DEPTH: '目标数量买回深度不足',
  NON_POSITIVE_TARGET_SPREAD: '目标规模双边盘口锁定或交叉',
  ONE_TICK_STRESSED_BID_NON_POSITIVE: '卖价下压一个合法 tick 后不再为正',
  DELTA_INELIGIBLE: 'Delta 不在冻结的可行动风险桶',
  REVIEW_ONLY_TTE_BAND: '临近 admission cutoff, 仅供审查不可激活 clue',
  REVIEW_ONLY_DELTA_BUCKET: 'Delta 位于冻结的 clue 风险桶之外, 仅供审查',
  REVIEW_ONLY_TTE_AND_DELTA: 'TTE 与 Delta 均位于 review-only 范围',
  FORWARD_TICKER_UNKNOWN: '远期价格 ticker 不可确认',
  INVALID_FORWARD: '远期价格无效',
  NUMERICAL_BOUNDARY_UNRESOLVED: '数值区间跨越决策边界',
  NUMERICAL_UNKNOWN: '数值模型输入不可确认',
  OTHER_INDEX_UNKNOWN: '其他指数输入不可确认',
  OTHER_TICKER_UNKNOWN: '其他 ticker 输入不可确认',
  OTHER_OPTION_UNKNOWN: '其他期权输入不可确认',
  OTHER_RUNTIME_UNKNOWN: '其他运行时输入不可确认',
  OTHER_RADAR_UNKNOWN: '其他 Radar 输入不可确认',
  SESSION_GAP: '公共行情会话中断',
  SESSION_RPC_FAILURE: '公共接口响应超时',
  COMBO_QUOTE_RECEIPT_UNKNOWN: '组合报价回执不可确认',
  NO_ACTIVE_COMBO: '无现成官方组合 - 仅诊断; 不阻塞双腿 Shadow',
  NO_TARGET_SIZE_CREDIT_QUOTE: '现成官方组合没有目标数量正信用报价 - 仅诊断',
  NO_PROTECTIVE_COMPONENT: '没有可冻结的同到期保护腿',
  NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE: '双腿盘口不能同时覆盖目标数量',
  COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN: '双腿保守成交反事实不可确认',
  NO_APPLICABLE_MARKET_SCOPE_OBSERVED: '尚未观察到适用的市场范围',
  NO_ANOMALY_ACTIVATION_OBSERVED: '已完成 Radar 计算, 尚未出现异常激活',
  ATOMIC_AVAILABILITY_UNKNOWN: '异常已激活, 但组合可用性仍不可确认',
  ATOMIC_AVAILABILITY_NOT_SETTLED: '异常已激活, 尚未结算组合可用性',
  PUBLIC_ATOMIC_QUOTE_NOT_OBSERVED: '组合可用性已结算, 尚无目标数量原子报价',
  MINIMUM_NET_ENTRY_CREDIT: '净入场权利金低于 Policy 最低值',
  MINIMUM_NET_CREDIT_TO_PAYOFF_CAP: '净权利金相对保护宽度不足',
  CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE: '净权利金未覆盖未来成本准备',
  UNDERWRITING_RESERVED_LOSS_LIMIT: '承保准备损失超过 Policy 上限',
  ADMISSION_PENDING_OR_NOT_REFRESHED: 'Candidate 尚未获得严格未来的成对双腿盘口刷新',
  OUTCOME_PENDING: 'Shadow Case 已打开, Outcome 尚未终结',
  NO_MATERIAL_BLOCKER_OBSERVED: '当前已观察漏斗没有实质转换阻塞',
  POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY: '该承保槽位已被 Shadow Entry 使用',
  RADAR_EPISODE_NOT_ACTIVE: '当前无活跃 Radar 候选, 承保尚未评估',
  NOT_STARTED: '服务尚未启动'
};
const reasonText = value => reasonLabels[value] || String(value);
const formatEpochMs = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(new Date(Number(value)));
};
const formatDurationMs = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  const milliseconds = Math.max(0, Number(value));
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  if (milliseconds < 3600000) return `${(milliseconds / 60000).toFixed(1)} 分钟`;
  return `${(milliseconds / 3600000).toFixed(2)} 小时`;
};
const formatDurationInterval = value => {
  if (!value || !Number.isFinite(Number(value.lower_ms)) ||
      !Number.isFinite(Number(value.upper_ms))) return 'UNKNOWN';
  const lower = formatDurationMs(value.lower_ms);
  const upper = formatDurationMs(value.upper_ms);
  return lower === upper ? lower : `${lower} - ${upper}`;
};
const formatDecimal = value => {
  if (isMissing(value)) return 'UNKNOWN';
  const text = String(value);
  const match = text.match(/^(-?)(\d+)(\.\d+)?$/);
  if (!match) return text;
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] || ''}`;
};
const formatPercent = value => {
  if (isMissing(value) || !Number.isFinite(Number(value))) return 'UNKNOWN';
  return `${(Number(value) * 100).toFixed(2)}%`;
};
const formatInterval = (value, formatter) => {
  if (!value || isMissing(value.lower) || isMissing(value.upper)) return 'UNKNOWN';
  const lower = formatter(value.lower);
  const upper = formatter(value.upper);
  return lower === upper ? lower : `${lower} - ${upper}`;
};
const shortIdentity = value => {
  if (isMissing(value)) return 'UNKNOWN';
  const text = String(value);
  return text.length <= 24 ? text : `${text.slice(0, 14)}…${text.slice(-6)}`;
};
const unavailableRadarCalculation = row =>
  row.detector_state === 'NO_ANOMALY' && row.known_evaluation ? 'N/A' : 'UNKNOWN';
const radarCellValue = (row, field, value) => {
  if (field === 'expiration_timestamp_ms') return formatEpochMs(value);
  if (field === 'tte_interval_ms') return formatDurationInterval(value);
  if (field === 'attention_rank') return isMissing(value) ? 'N/A' : `#${formatDecimal(value)}`;
  if (field === 'strike_price') {
    return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  }
  if (['model_executable_sell_price', 'model_executable_buy_price',
      'model_one_tick_stressed_sell_price'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatDecimal(value);
  }
  if (['executable_iv_interval', 'executable_ask_iv_interval',
      'one_tick_stressed_iv_interval'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatInterval(value, formatPercent);
  }
  if (field === 'baseline_annualized_volatility') {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatPercent(value);
  }
  if (field === 'baseline_return_interval_minutes') {
    return isMissing(value) ? unavailableRadarCalculation(row) : `${formatDecimal(value)} 分钟`;
  }
  if (field === 'baseline_selected_lookback_minutes') {
    if (!isMissing(value)) return `${formatDecimal(value)} 分钟`;
    return row.baseline_source === 'ANNUALIZED_VARIANCE_FLOOR'
      ? '固定年化方差下限'
      : unavailableRadarCalculation(row);
  }
  if (['richness_ratio_interval', 'raw_richness_ratio_interval'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row)
      : formatInterval(value, formatDecimal);
  }
  if (['target_spread_ticks', 'bid_premium_ticks', 'surface_residual',
      'best_legged_credit_to_payoff_cap_fraction'].includes(field)) {
    return isMissing(value) ? unavailableRadarCalculation(row) : formatDecimal(value);
  }
  if (['regime_jump_share', 'regime_adverse_semivariance_share'].includes(field)) {
    return isMissing(value) ? 'UNKNOWN' : formatPercent(value);
  }
  if (field === 'detector_reason' || field === 'option_book_reason') {
    return isMissing(value) ? unavailableRadarCalculation(row) : reasonText(value);
  }
  if (field === 'active_episode_identity' || field === 'anomaly_started_monotonic_ms') {
    return isMissing(value)
      ? (row.detector_state === 'ANOMALY_ACTIVE' ? 'UNKNOWN' : 'N/A')
      : shortIdentity(value);
  }
  if (field === 'anomaly_active_duration_ms') {
    return isMissing(value)
      ? (row.detector_state === 'ANOMALY_ACTIVE' ? 'UNKNOWN' : 'N/A')
      : formatDurationMs(value);
  }
  if (field === 'option_type') return value === 'call' ? 'Call' : (value === 'put' ? 'Put' : displayText(value));
  return displayText(value);
};
const underwritingReasonText = (row, value) => {
  if (row.availability === 'NOT_EVALUATED') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    if (reasons.includes('RADAR_EPISODE_NOT_ACTIVE')) {
      return reasonText('RADAR_EPISODE_NOT_ACTIVE');
    }
    return reasons.length
      ? reasons.map(reasonText).join('; ')
      : '已知前置条件未满足, 承保未评估';
  }
  if (row.availability === 'UNKNOWN') {
    const reasons = Array.isArray(row.unknown_reasons) ? row.unknown_reasons : [];
    return reasons.length
      ? reasons.map(reasonText).join('; ')
      : '承保所需事实不可确认';
  }
  if (row.availability === 'EVALUABLE' && !isMissing(row.action)) {
    const failures = Array.isArray(row.failed_predicates) ? row.failed_predicates : [];
    return failures.length
      ? `已结算承保动作: ${row.action}; 未通过: ${failures.map(reasonText).join('; ')}`
      : `已结算承保动作: ${row.action}; 全部经济谓词通过`;
  }
  return isMissing(value) ? 'N/A' : reasonText(value);
};
const underwritingCellValue = (row, field, value) => {
  if (field === 'expiry_timestamp_ms') return isMissing(value) ? 'UNKNOWN' : formatEpochMs(value);
  if (field.endsWith('_strike_price') || field === 'target_quantity_btc') {
    return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  }
  if (field === 'radar_scope_or_short_leg_identity' || field.endsWith('_identity')) {
    return isMissing(value) ? 'UNKNOWN' : shortIdentity(value);
  }
  if (field === 'decision_reason') return underwritingReasonText(row, value);
  const unavailableFields = new Set([
    'action', 'gross_entry_credit_valuation', 'entry_fee_reserve_valuation',
    'net_entry_credit_valuation',
    'entry_boundary_valued_payoff_loss_ex_fees_valuation',
    'future_cost_reserve_valuation', 'underwriting_reserved_loss_valuation',
    'candidate_lifecycle', 'candidate_still_valid', 'candidate_invalidation_reason'
  ]);
  if (unavailableFields.has(field) && isMissing(value)) {
    return row.availability === 'EVALUABLE' ? 'UNKNOWN' : 'N/A';
  }
  return displayText(value);
};
const shadowCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'target_quantity_btc') return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  if (field === 'simulated_entry_price_valuation_per_btc' ||
      field === 'simulated_entry_credit_valuation') {
    return isMissing(value)
      ? (isMissing(row.shadow_entry_identity) ? 'N/A' : 'UNKNOWN')
      : formatDecimal(value);
  }
  if (field === 'no_entry_reason') {
    return isMissing(value) ? (isMissing(row.shadow_entry_identity) ? 'UNKNOWN' : 'N/A')
      : reasonText(value);
  }
  return displayText(value);
};
const positionCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'hard_close_countdown_interval_ms') return formatDurationInterval(value);
  if (field.endsWith('_valuation')) return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  return displayText(value);
};
const outcomeCellValue = (row, field, value) => {
  if (field.endsWith('_identity')) return isMissing(value) ? 'N/A' : shortIdentity(value);
  if (field === 'actual_pnl' && isMissing(value)) {
    return 'N/A — public Shadow 无订单、成交或实际持仓';
  }
  if (field.endsWith('_valuation')) return isMissing(value) ? 'UNKNOWN' : formatDecimal(value);
  return displayText(value);
};
const radarPriority = {ANOMALY_ACTIVE: 0, UNKNOWN: 1, NO_ANOMALY: 2};
const underwritingPriority = {EVALUABLE: 0, UNKNOWN: 1, NOT_EVALUATED: 2};
const underwritingActionPriority = {CANDIDATE: 0, WATCH: 1, ABSTAIN: 2};
const orderedRadarRows = rows => [...rows].sort((left, right) =>
  (Number.isFinite(Number(left.attention_rank)) ? Number(left.attention_rank) : 999999) -
    (Number.isFinite(Number(right.attention_rank)) ? Number(right.attention_rank) : 999999) ||
  (radarPriority[left.detector_state] ?? 9) - (radarPriority[right.detector_state] ?? 9) ||
  Number(left.expiration_timestamp_ms || 0) - Number(right.expiration_timestamp_ms || 0) ||
  String(left.option_type || '').localeCompare(String(right.option_type || '')) ||
  String(left.strike_price || '').localeCompare(String(right.strike_price || ''), undefined, {numeric: true}) ||
  String(left.instrument_name || '').localeCompare(String(right.instrument_name || ''))
);
const orderedUnderwritingRows = rows => [...rows].sort((left, right) =>
  (underwritingPriority[left.availability] ?? 9) -
    (underwritingPriority[right.availability] ?? 9) ||
  (underwritingActionPriority[left.action] ?? 9) -
    (underwritingActionPriority[right.action] ?? 9) ||
  Number(left.expiry_timestamp_ms || 0) - Number(right.expiry_timestamp_ms || 0) ||
  String(left.short_leg_instrument_name || left.radar_scope_or_short_leg_identity || '').localeCompare(
    String(right.short_leg_instrument_name || right.radar_scope_or_short_leg_identity || '')
  )
);
const filterRows = (rows, field, selected) => selected === 'ALL'
  ? [...rows]
  : (selected === 'TOP_N'
    ? rows.filter(row => row.within_attention_top_n)
    : rows.filter(row => row[field] === selected));
const details = (row, fields) => {
  const body = fields.map(([label, key]) =>
    `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(rawText(row[key]))}</dd>`
  ).join('');
  return `<details class="raw-details"><summary>原始详情</summary><dl>${body}</dl></details>`;
};
const table = (panel, columns, rows = panel.rows, detailFields = []) => {
  if (panel.panel_state === 'EMPTY_NO_SETTLED_OBJECT') {
    return `<p class="empty">${safeText(panel.empty_label)}</p>`;
  }
  const header = columns.map(column => `<th>${escapeHtml(column[0])}</th>`).join('');
  const detailHeader = detailFields.length ? '<th>详情</th>' : '';
  const body = rows.map(row => {
    const cells = columns.map(column => {
      const rendered = column[2]
        ? column[2](row, column[1], row[column[1]])
        : displayText(row[column[1]]);
      const renderedText = String(rendered);
      const className = renderedText.startsWith('N/A')
        ? ' class="na"'
        : (['UNKNOWN', 'STALE', 'INTERRUPTED', 'CURRENT', 'PROVEN_ZERO',
          'ANOMALY_ACTIVE', 'EVALUABLE', 'DEGRADED', 'NOT_EVALUATED'].includes(renderedText)
          ? ` class="${renderedText}"` : '');
      return `<td${className}>${safeText(rendered)}</td>`;
    }).join('');
    const detailCell = detailFields.length ? `<td>${details(row, detailFields)}</td>` : '';
    return `<tr>${cells}${detailCell}</tr>`;
  }).join('');
  return `<div class="table-scroll"><table><thead><tr>${header}${detailHeader}</tr></thead>` +
    `<tbody>${body}</tbody></table></div>`;
};
const businessPanelIds = [
  'funnel', 'decision-control', 'zero', 'radar', 'underwriting', 'shadow', 'positions',
  'outcomes'
];
let lastSuccessfulFetchAtMs = null;
let lastPublicationRuntimeIdentity = null;
let lastPublicationSequence = null;
let lastPublicationChangeAtMs = null;
let radarFilterValue = 'TOP_N';
let underwritingFilterValue = 'ALL';
let lastRenderedDocument = null;
const ageMs = timestamp => timestamp === null ? 'UNKNOWN' : Math.max(0, Date.now() - timestamp);
function renderUnavailable() {
  lastRenderedDocument = null;
  const connection = document.getElementById('connection');
  connection.hidden = false;
  connection.textContent = '工作台连接中断: 旧业务数据已隐藏, 当前状态 UNKNOWN。';
  document.body.dataset.workbenchState = 'UNKNOWN';
  document.getElementById('runtime').textContent = 'runtime UNKNOWN';
  document.getElementById('system').innerHTML =
    card('工作台连接', 'UNKNOWN') +
    card('最近成功获取 age ms', ageMs(lastSuccessfulFetchAtMs)) +
    card('最后 publication sequence', lastPublicationSequence) +
    card('Publication 未变化 age ms', ageMs(lastPublicationChangeAtMs));
  const unavailable = '<p class="warning UNKNOWN">工作台连接中断; 旧业务数据已隐藏。</p>';
  businessPanelIds.forEach(id => { document.getElementById(id).innerHTML = unavailable; });
}
const zeroClaimText = (claim, noun) => claim.state === 'PROVEN_ZERO'
  ? `已证明当前 0 ${noun}`
  : (claim.state === 'NOT_ZERO' ? `当前 ${claim.value} ${noun}` : `无法证明当前为 0 ${noun}`);
const toolbar = (label, id, selected, choices, shown, total) =>
  `<div class="panel-toolbar"><label>${escapeHtml(label)}<select id="${escapeHtml(id)}">` +
  choices.map(choice => `<option value="${escapeHtml(choice)}"${choice === selected ? ' selected' : ''}>${escapeHtml(choice)}</option>`).join('') +
  `</select></label><span>显示 ${shown} / ${total}</span></div>`;
function renderRadarPanel(documentValue) {
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const ordered = orderedRadarRows(documentValue.radar.rows);
  const rows = filterRows(ordered, 'detector_state', radarFilterValue);
  document.getElementById('radar').innerHTML =
    toolbar('注意力筛选', 'radar-filter', radarFilterValue,
      ['TOP_N', 'ALL', 'ANOMALY_ACTIVE', 'UNKNOWN', 'NO_ANOMALY'], rows.length, ordered.length) +
    table(documentValue.radar, [
      ['Rank', 'attention_rank', radarCellValue], ['合约', 'instrument_name'],
      ['到期(北京时间)', 'expiration_timestamp_ms', radarCellValue],
      ['TTE', 'tte_interval_ms', radarCellValue], ['类型', 'option_type', radarCellValue],
      ['Delta 桶', 'delta_bucket', radarCellValue],
      ['One-tick Richness', 'richness_ratio_interval', radarCellValue],
      ['Spread ticks', 'target_spread_ticks', radarCellValue],
      ['Surface residual', 'surface_residual', radarCellValue],
      ['Jump share', 'regime_jump_share', radarCellValue],
      ['Legged ref', 'legged_reference_state', radarCellValue],
      ['Clue 状态', 'detector_state', radarCellValue], ['原因', 'detector_reason', radarCellValue],
      ['Atomic combo', 'public_atomic_quote_state', radarCellValue]
    ], rows, [['rank explanation', 'rank_explanation'],
      ['hard screen label', 'hard_screen_label'],
      ['episode identity', 'active_episode_identity'],
      ['expiration timestamp ms', 'expiration_timestamp_ms'],
      ['TTE interval ms', 'tte_interval_ms'], [`strike exact (${product.strike_currency})`, 'strike_price'],
      [`model executable sell price (${product.strike_currency})`, 'model_executable_sell_price'],
      [`native executable sell price (${nativeUnit})`, 'native_executable_sell_price'],
      [`native executable buy price (${nativeUnit})`, 'native_executable_buy_price'],
      [`native stressed sell price (${nativeUnit})`, 'native_one_tick_stressed_sell_price'],
      [`native price tick (${nativeUnit})`, 'native_price_tick'],
      [`native target spread (${nativeUnit})`, 'native_target_spread'],
      ['model conversion forward', 'model_conversion_forward'],
      ['product spec identity', 'product_spec_identity'],
      ['executable IV exact', 'executable_iv_interval'],
      ['baseline return interval minutes', 'baseline_return_interval_minutes'],
      ['baseline selected lookback minutes', 'baseline_selected_lookback_minutes'],
      ['baseline source', 'baseline_source'],
      ['baseline volatility exact', 'baseline_annualized_volatility'],
      ['raw richness exact', 'raw_richness_ratio_interval'],
      ['one-tick richness exact', 'richness_ratio_interval'],
      ['delta exact', 'delta_interval'], ['quote ask exact', 'model_executable_buy_price'],
      ['one-tick stressed bid exact', 'model_one_tick_stressed_sell_price'],
      ['model price tick exact', 'model_price_tick'], ['model spread exact', 'model_target_spread'],
      ['premium ticks', 'bid_premium_ticks'], ['regime context', 'regime_context'],
      ['surface context', 'surface_context'], ['legged structure', 'legged_structure_context'],
      ['detector reason enum', 'detector_reason'],
      ['option book state', 'option_book_state'], ['option book reason', 'option_book_reason'],
      ['episode start monotonic ms', 'anomaly_started_monotonic_ms'],
      ['episode duration ms', 'anomaly_active_duration_ms']]);
}
function renderUnderwritingPanel(documentValue) {
  const product = documentValue.product;
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const ordered = orderedUnderwritingRows(documentValue.underwriting.rows);
  const rows = filterRows(ordered, 'availability', underwritingFilterValue);
  const marginSummary = Array.isArray(documentValue.underwriting.predicate_margin_summary)
    ? documentValue.underwriting.predicate_margin_summary : [];
  const marginDetails = marginSummary.length
    ? `<details class="system-details"><summary>当前承保谓词 margin 分布</summary><div class="grid">${
        marginSummary.map(value => card(value.predicate,
          `n=${value.count}; min=${value.min}; p50=${value.p50}; max=${value.max}; ${value.unit}`
        )).join('')
      }</div></details>`
    : '';
  document.getElementById('underwriting').innerHTML =
    toolbar('可用性筛选', 'underwriting-filter', underwritingFilterValue,
      ['ALL', 'EVALUABLE', 'UNKNOWN', 'NOT_EVALUATED'], rows.length, ordered.length) + marginDetails +
    table(documentValue.underwriting, [
      ['Short leg', 'short_leg_instrument_name', underwritingCellValue],
      ['Long leg', 'long_leg_instrument_name', underwritingCellValue],
      ['Component 状态', 'component_state', underwritingCellValue],
      ['Combo 诊断', 'atomic_state_diagnostic', underwritingCellValue],
      ['到期(北京时间)', 'expiry_timestamp_ms', underwritingCellValue],
      ['Availability', 'availability', underwritingCellValue],
      ['Action', 'action', underwritingCellValue],
      [`净权利金 (${valuationUnit})`, 'net_entry_credit_valuation', underwritingCellValue],
      [`原生净权利金 (${nativeUnit})`, 'native_net_entry_credit', underwritingCellValue],
      [`承保准备损失 (${valuationUnit})`, 'underwriting_reserved_loss_valuation', underwritingCellValue],
      ['Candidate 状态', 'candidate_lifecycle', underwritingCellValue],
      ['原因', 'decision_reason', underwritingCellValue]
    ], rows, [['radar scope', 'radar_scope_or_short_leg_identity'],
      ['option type', 'option_type'], ['short strike exact', 'short_strike_price'],
      ['long strike exact', 'long_strike_price'],
      ['target quantity exact', 'target_quantity_btc'],
      ['availability identity', 'underwriting_availability_evaluation_identity'],
      ['action identity', 'underwriting_action_identity'], ['availability enum', 'availability'],
      ['decision reason enum', 'decision_reason'], ['unknown reasons', 'unknown_reasons'],
      ['failed predicates', 'failed_predicates'],
      ['predicate margin vector', 'predicate_margin_vector'],
      ['protective-leg selection rule identity', 'protective_leg_selection_rule_identity'],
      ['Candidate protective-leg count', 'candidate_protective_leg_count'],
      ['component blockers', 'component_blockers'],
      ['product spec identity', 'product_spec_identity'],
      ['product name', 'product_name'],
      ['native premium currency', 'native_premium_currency'],
      ['valuation currency', 'valuation_currency'],
      [`native gross entry credit (${nativeUnit})`, 'native_gross_entry_credit'],
      [`native entry fee reserve (${nativeUnit})`, 'native_entry_fee_reserve'],
      [`native net entry credit (${nativeUnit})`, 'native_net_entry_credit'],
      ['entry valuation index price', 'entry_valuation_index_price'],
      [`gross entry credit (${valuationUnit})`, 'gross_entry_credit_valuation'],
      ['entry fee reserve exact', 'entry_fee_reserve_valuation'],
      ['net entry credit exact', 'net_entry_credit_valuation'],
      [`entry-boundary payoff loss proxy (${valuationUnit}; not native liability, expiry loss, or account margin)`,
        'entry_boundary_valued_payoff_loss_ex_fees_valuation'],
      ['future cost reserve exact', 'future_cost_reserve_valuation'],
      ['reserved loss exact', 'underwriting_reserved_loss_valuation'],
      ['reserve breakdown', 'reserve_breakdown_valuation'],
      ['evaluation fact boundary', 'evaluation_fact_boundary']]);
}
const funnelStageLabels = {
  APPLICABLE_MARKET_SCOPE: '适用市场评估',
  RADAR_KNOWN: 'Radar 已知评估',
  ANOMALY_ACTIVE: '异常 Episode',
  STRUCTURE_REVIEWABLE: '结构可审查',
  COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE: '双腿盘口保守成交反事实',
  UNDERWRITING_EVALUABLE: 'Underwriting 可评估',
  CANDIDATE: 'Candidate',
  SHADOW_CASE_OPENED: 'Shadow Case',
  SHADOW_CASE_OUTCOME: 'Outcome'
};
const funnelStageLabel = value => funnelStageLabels[value] || String(value);
const funnelBlockerText = values => {
  if (!values || typeof values !== 'object') return '无';
  const entries = Object.entries(values).filter(([, count]) => Number(count) > 0);
  if (!entries.length) return '无';
  return entries
    .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]))
    .map(([reason, count]) => `${reasonText(reason)}: ${count}`)
    .join('; ');
};
const knownnessRatioText = slice => {
  const value = slice && slice.radar_known_over_applicable;
  if (!value) return 'UNKNOWN';
  const counts = `${displayText(value.numerator)}/${displayText(value.denominator)}`;
  if (Number(value.denominator) === 0 || isMissing(value.ratio)) {
    return `${counts} (UNKNOWN)`;
  }
  const percentage = Number(value.ratio) * 100;
  return Number.isFinite(percentage)
    ? `${counts} (${percentage.toFixed(2)}%)`
    : `${counts} (UNKNOWN)`;
};
function renderFunnel(documentValue) {
  const funnel = documentValue.funnel;
  const knownness = funnel && funnel.radar_knownness;
  if (!funnel || !Array.isArray(funnel.stages) || !funnel.primary_blocker ||
      !knownness || !knownness.startup_warmup || !knownness.post_warmup) {
    throw new Error('invalid funnel projection');
  }
  const primary = funnel.primary_blocker;
  const startup = knownness.startup_warmup;
  const steady = knownness.post_warmup;
  const summary = '<div class="grid">' +
    card('首要漏斗阻塞阶段', funnelStageLabel(primary.stage)) +
    card('首要阻塞原因', reasonText(primary.reason)) +
    card('受阻数量', primary.blocked_count) +
    card('该阶段上游/已通过', `${primary.upstream_count}/${primary.observed_count}`) +
    card('启动/恢复 warmup Radar known / applicable', knownnessRatioText(startup)) +
    card('启动/恢复 warmup UNKNOWN', funnelBlockerText(startup.blocker_counts)) +
    card('稳态 Radar known / applicable', knownnessRatioText(steady)) +
    card('稳态 Radar UNKNOWN', funnelBlockerText(steady.blocker_counts)) +
    '</div>';
  const header = '<tr><th>阶段</th><th>已观察</th><th>单位</th>' +
    '<th>上游</th><th>阻塞归因</th></tr>';
  const rows = funnel.stages.map(stage =>
    '<tr>' +
    `<td>${safeText(funnelStageLabel(stage.stage))}</td>` +
    `<td>${safeText(stage.observed_count)}</td>` +
    `<td>${safeText(stage.unit)}</td>` +
    `<td>${safeText(stage.upstream_count)}</td>` +
    `<td>${safeText(funnelBlockerText(stage.blocker_counts))}</td>` +
    '</tr>'
  ).join('');
  document.getElementById('funnel').innerHTML = summary +
    `<div class="table-scroll"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div>`;
}
function renderDecisionControlResearch(documentValue) {
  const research = documentValue.funnel && documentValue.funnel.decision_control_research;
  const panel = documentValue.decision_controls;
  const product = documentValue.product;
  if (!research || !research.pending_counts || !research.selected_action_counts ||
      !research.attempt_terminal_counts || !Array.isArray(research.non_claims) ||
      !panel || !Array.isArray(panel.rows) || !product) {
    throw new Error('invalid selected-decision research projection');
  }
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const summary = '<div class="grid">' +
    card('因果 activation batch', research.activation_batch_count) +
    card('预先选定决策', research.selected_decision_count) +
    card('Decision Case 已开', research.decision_case_opened_count) +
    card('严格未来 Outcome', research.decision_outcome_count) +
    card('选定 action', funnelBlockerText(research.selected_action_counts)) +
    card('刷新终局', funnelBlockerText(research.attempt_terminal_counts)) +
    card('尚无可评估选定决策', research.pending_counts.batch_without_selected_evaluable_decision) +
    card('选定但未开 Case', research.pending_counts.selected_without_case) +
    card('Case 等待 Outcome', research.pending_counts.case_without_outcome) +
    card('边界声明', research.non_claims.join('; ')) +
    '</div>';
  const rows = table(panel, [
    ['选定 action', 'selected_economic_action'],
    ['刷新后 action', 'refreshed_economic_action'],
    ['刷新终局', 'refresh_terminal_outcome'],
    ['Enrollment', 'enrollment_kind'],
    ['Case / Outcome', 'case_state'],
    [`Public-quote PnL (${valuationUnit})`, 'public_quote_net_pnl_valuation'],
    [`Native PnL (${nativeUnit})`, 'native_net_pnl']
  ], panel.rows, [
    ['selection identity', 'selected_underwriting_decision_identity'],
    ['activation batch identity', 'activation_batch_identity'],
    ['active episode', 'active_episode_identity'],
    ['selected failed predicates', 'selected_failed_predicates'],
    ['selected predicate margin vector', 'selected_predicate_margin_vector'],
    ['protective-leg selection rule identity', 'protective_leg_selection_rule_identity'],
    ['Candidate protective-leg count', 'candidate_protective_leg_count'],
    ['selection fact boundary', 'selection_fact_boundary'],
    ['refresh unknown reasons', 'refresh_unknown_reasons'],
    ['refresh pair timing', 'refresh_component_pair_timing'],
    ['refresh pair limits', 'refresh_component_pair_limits'],
    ['refreshed failed predicates', 'refreshed_failed_predicates'],
    ['refreshed predicate margin vector', 'refreshed_predicate_margin_vector'],
    ['refreshed fact boundary', 'refreshed_fact_boundary'],
    ['enrollment identity', 'enrollment_identity'],
    ['boundary-valued PnL', 'boundary_valued_net_pnl_usd'],
    ['exit-valued native PnL', 'exit_valued_native_net_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['non claims', 'non_claims']
  ]);
  document.getElementById('decision-control').innerHTML = summary + rows;
}
function render(documentValue) {
  if (!documentValue || documentValue.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error('unsupported workbench projection schema');
  }
  const product = documentValue.product;
  if (!product || !product.product_spec_identity || !product.name ||
      !product.native_premium_currency || !product.valuation_currency || !product.price_index ||
      !product.native_settlement_payoff_rule || !product.native_settlement_liability_profile ||
      product.actual_account_margin_availability !== 'UNKNOWN' ||
      product.actual_account_margin_reason !== 'ACCOUNT_MARGIN_UNKNOWN') {
    throw new Error('invalid product projection');
  }
  const valuationUnit = product.valuation_currency;
  const nativeUnit = product.native_premium_currency;
  const connection = document.getElementById('connection');
  connection.hidden = true;
  connection.textContent = '';
  document.body.dataset.workbenchState = 'CURRENT_FETCH';
  document.getElementById('runtime').textContent = `runtime ${shortIdentity(documentValue.runtime_identity)}`;
  const service = documentValue.service;
  const system = documentValue.system;
  document.getElementById('system').innerHTML =
    card('产品', product.name) +
    card('原生权利金 / 结算币种', `${nativeUnit} / ${product.settlement_currency}`) +
    card('估值币种 / 指数', `${valuationUnit} / ${product.price_index}`) +
    card('合约 payoff / 原生负债', `${product.strike_currency}; ${product.native_settlement_liability_profile}`) +
    card('实际账户保证金', `${product.actual_account_margin_availability}: ${product.actual_account_margin_reason}`) +
    card('服务阶段', service.phase) +
    card('数据状态', service.data_state) +
    card('当前行情判定', service.ready ? '可用于当前判定' : '不可用于当前判定') +
    card('主阻塞原因', reasonText(service.reason)) +
    card('Coverage 已知/监控', `${system.known_current_instrument_evaluation_count}/${system.monitored_instrument_count}`) +
    card('Radar clue 结论', zeroClaimText(documentValue.zero_claims.anomaly, 'Radar clue')) +
    card('Candidate 结论', zeroClaimText(documentValue.zero_claims.candidate, 'Candidate')) +
    card('数据延迟', isMissing(system.data_delay_ms) ? 'UNKNOWN' : formatDurationMs(system.data_delay_ms)) +
    '<details class="system-details"><summary>运行与 Policy 详情</summary><div class="grid">' +
    card('Ready', service.ready) +
    card('Publication sequence', documentValue.publication_sequence) +
    card('最近成功获取 age', formatDurationMs(ageMs(lastSuccessfulFetchAtMs))) +
    card('Publication 未变化 age', formatDurationMs(ageMs(lastPublicationChangeAtMs))) +
    card('Session epoch', system.session_epoch) +
    card('Platform', reasonText(system.platform_reason)) +
    card('最近行情时间', isMissing(system.latest_market_timestamp_ms) ? 'UNKNOWN' : formatEpochMs(system.latest_market_timestamp_ms)) +
    card('Last-wire age', isMissing(system.last_wire_age_ms) ? 'UNKNOWN' : formatDurationMs(system.last_wire_age_ms)) +
    card('Coverage', system.coverage_state) +
    card('Coverage blocker', system.coverage_blocking_reason) +
    card('覆盖率', isMissing(system.coverage_ratio_percent) ? 'UNKNOWN' : `${formatDecimal(system.coverage_ratio_percent)}%`) +
    card('断线/重连', system.reconnect_count) +
    card('Session gaps', system.session_gap_count) +
    card('最近断线记录', system.disconnect_records.slice(-1)[0]) +
    card('RV source', system.index_history.source) +
    card('RV value semantics', system.index_history.value_semantics) +
    card('History cadence', isMissing(system.index_history.modal_interval_ms)
      ? 'UNKNOWN' : formatDurationMs(system.index_history.modal_interval_ms)) +
    card('History confirmed suffix', `${system.index_history.exact_suffix_point_count} points / ${formatDecimal(system.index_history.exact_suffix_minutes)} minutes`) +
    card('History confirmed age', isMissing(system.index_history.latest_source_age_ms)
      ? 'UNKNOWN' : formatDurationMs(system.index_history.latest_source_age_ms)) +
    card('History newest point outside completion cutoff', system.index_history.newest_response_point_excluded_by_completion_cutoff) +
    card('History revisions', `${system.index_history.revision_count}; pending=${system.index_history.revision_pending}`) +
    card('Runtime identity', documentValue.runtime_identity) +
    card('Code identity', documentValue.code_identity) +
    card('Published fact boundary', documentValue.published_fact_boundary) +
    card('Policy / Radar', documentValue.policy_identities.radar) +
    card('Policy / Underwriting', documentValue.policy_identities.underwriting) +
    card('Policy / Position', documentValue.policy_identities.position) +
    card('Product spec identity', product.product_spec_identity) +
    card('Product instrument type', product.instrument_type) +
    card('Product quote/counter', `${product.quote_currency}/${product.counter_currency}`) +
    card('Native settlement payoff rule', product.native_settlement_payoff_rule) +
    '</div></details>';
  const zero = documentValue.zero_claims;
  document.getElementById('zero').innerHTML =
    card('零异常', zero.anomaly.value === null
      ? zero.anomaly.explanation
      : `${zero.anomaly.value} (${zero.anomaly.state})`) +
    card('异常监控分母', zero.anomaly.denominator) +
    card('零 Candidate', zero.candidate.value === null
      ? zero.candidate.explanation
      : `${zero.candidate.value} (${zero.candidate.state})`) +
    card('Underwriting-evaluable 分母', zero.candidate.denominator);
  renderFunnel(documentValue);
  renderDecisionControlResearch(documentValue);
  renderRadarPanel(documentValue);
  renderUnderwritingPanel(documentValue);
  document.getElementById('shadow').innerHTML = table(documentValue.shadow_entries, [
    ['刷新结果', 'admission_refresh_terminal_outcome', shadowCellValue],
    ['目标数量 (BTC)', 'target_quantity_btc', shadowCellValue],
    [`模拟垂直毛信用 (${valuationUnit}/BTC)`, 'simulated_entry_price_valuation_per_btc', shadowCellValue],
    ['模拟入场价状态', 'simulated_entry_price_availability'],
    [`模拟毛权利金 (${valuationUnit})`, 'simulated_entry_credit_valuation', shadowCellValue],
    [`原生净权利金 (${nativeUnit})`, 'native_net_entry_credit', shadowCellValue],
    ['未入场原因', 'no_entry_reason', shadowCellValue], ['声明', 'simulation_label']
  ], documentValue.shadow_entries.rows, [
    ['candidate identity', 'candidate_identity'], ['active episode', 'active_episode_identity'],
    ['formed boundary', 'candidate_formed_fact_boundary'],
    ['refresh source identity', 'matched_refresh_source_identity'],
    ['shadow entry identity', 'shadow_entry_identity'], ['target quantity exact', 'target_quantity_btc'],
    ['simulated entry price exact', 'simulated_entry_price_valuation_per_btc'],
    ['simulated entry credit exact', 'simulated_entry_credit_valuation'],
    ['native gross entry credit', 'native_gross_entry_credit'],
    ['native entry fee reserve', 'native_entry_fee_reserve'],
    ['native net entry credit', 'native_net_entry_credit'],
    ['entry valuation index price', 'entry_valuation_index_price'],
    ['native premium currency', 'native_premium_currency'],
    ['execution model', 'execution_model'],
    ['component pair identity', 'entry_component_pair_identity'],
    ['component pair timing', 'entry_component_pair_timing'],
    ['admission refresh unknown reasons', 'admission_refresh_unknown_reasons'],
    ['admission pair timing', 'admission_component_pair_timing'],
    ['admission pair limits', 'admission_component_pair_limits'],
    ['component legs', 'entry_component_legs']
  ]);
  document.getElementById('positions').innerHTML = table(documentValue.positions, [
    ['Action', 'position_action'],
    [`剩余权利金 (${valuationUnit})`, 'remaining_premium_valuation', positionCellValue],
    ['剩余权利金状态', 'remaining_premium_availability'],
    ['Component close', 'close_quote_state'],
    [`Close debit (${valuationUnit})`, 'current_close_debit_valuation', positionCellValue],
    [`Boundary-valued Shadow PnL (${valuationUnit})`, 'projected_shadow_pnl_valuation', positionCellValue],
    [`Native projected PnL (${nativeUnit})`, 'native_projected_shadow_net_pnl', positionCellValue],
    ['Hard-close 倒计时', 'hard_close_countdown_interval_ms', positionCellValue],
    ['首要退出规则', 'primary_exit_rule'],
    ['Close eligibility', 'close_opportunity_eligibility'],
    ['Close 原因', 'close_opportunity_reason'],
    ['有效 close opportunity', 'valid_shadow_close_opportunity'],
    ['Outcome', 'outcome_state']
  ], documentValue.positions.rows, [
    ['shadow entry identity', 'shadow_entry_identity'],
    ['remaining premium exact', 'remaining_premium_valuation'],
    ['close debit exact', 'current_close_debit_valuation'],
    ['component pair timing', 'component_pair_timing'],
    ['component pair limits', 'component_pair_limits'],
    ['component pair business state', 'component_pair_business_state'],
    ['component pair unknown reasons', 'component_pair_unknown_reasons'],
    ['projected Shadow PnL exact', 'projected_shadow_pnl_valuation'],
    ['native close cashflow', 'native_net_close_cashflow'],
    ['native projected Shadow PnL', 'native_projected_shadow_net_pnl'],
    ['boundary-valued projected Shadow PnL', 'boundary_valued_projected_shadow_net_pnl_usd'],
    ['exit-valued native projected PnL', 'exit_valued_native_projected_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['hard-close interval ms', 'hard_close_countdown_interval_ms'],
    ['remaining premium basis', 'remaining_premium_basis'],
    ['ordered exit rules', 'ordered_latched_exit_rules']
  ]);
  document.getElementById('outcomes').innerHTML = table(documentValue.outcomes, [
    ['状态', 'state'], ['成熟度', 'maturity'],
    [`Boundary-valued public-quote PnL (${valuationUnit})`, 'public_quote_net_pnl_valuation', outcomeCellValue],
    [`Native net PnL (${nativeUnit})`, 'native_net_pnl', outcomeCellValue],
    ['Actual PnL', 'actual_pnl', outcomeCellValue]
  ], documentValue.outcomes.rows, [
    ['observation identity', 'shadow_observation_identity'],
    ['selected exit identity', 'selected_exit_identity'],
    ['public-quote PnL exact', 'public_quote_net_pnl_valuation'],
    ['native net PnL', 'native_net_pnl'],
    ['boundary-valued net PnL', 'boundary_valued_net_pnl_usd'],
    ['exit-valued native net PnL', 'exit_valued_native_net_pnl_usd'],
    ['native premium currency', 'native_premium_currency'],
    ['actual PnL exact', 'actual_pnl']
  ]);
  lastRenderedDocument = documentValue;
}
if (typeof document.addEventListener === 'function') {
  document.addEventListener('change', event => {
    if (!lastRenderedDocument || !event.target) return;
    if (event.target.id === 'radar-filter') {
      radarFilterValue = event.target.value;
      renderRadarPanel(lastRenderedDocument);
    } else if (event.target.id === 'underwriting-filter') {
      underwritingFilterValue = event.target.value;
      renderUnderwritingPanel(lastRenderedDocument);
    }
  });
}
async function refresh() {
  try {
    const response = await fetch('/api/workbench/current', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const documentValue = await response.json();
    const fetchedAtMs = Date.now();
    const previousSuccessfulFetchAtMs = lastSuccessfulFetchAtMs;
    const previousPublicationRuntimeIdentity = lastPublicationRuntimeIdentity;
    const previousPublicationSequence = lastPublicationSequence;
    const previousPublicationChangeAtMs = lastPublicationChangeAtMs;
    lastSuccessfulFetchAtMs = fetchedAtMs;
    if (
      documentValue.runtime_identity !== lastPublicationRuntimeIdentity ||
      documentValue.publication_sequence !== lastPublicationSequence
    ) {
      lastPublicationRuntimeIdentity = documentValue.runtime_identity;
      lastPublicationSequence = documentValue.publication_sequence;
      lastPublicationChangeAtMs = fetchedAtMs;
    }
    try {
      render(documentValue);
    } catch (error) {
      lastSuccessfulFetchAtMs = previousSuccessfulFetchAtMs;
      lastPublicationRuntimeIdentity = previousPublicationRuntimeIdentity;
      lastPublicationSequence = previousPublicationSequence;
      lastPublicationChangeAtMs = previousPublicationChangeAtMs;
      throw error;
    }
  } catch (_error) {
    renderUnavailable();
  }
}
refresh();
setInterval(refresh, 2000);
"""


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

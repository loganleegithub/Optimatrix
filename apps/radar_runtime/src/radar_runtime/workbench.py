from __future__ import annotations

import ipaddress
import json
import socket
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast

from market_monitor import ContinuityGap, TimeInterval
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import DetectorState
from short_vol_radar.evidence import CoverageBlockingReason, CoverageState
from short_vol_underwriting.conservation import derive_underwriting_counts
from short_vol_underwriting.evidence import DownstreamEvidenceWriter
from short_vol_underwriting.identity import canonical_decimal, canonical_value
from short_vol_underwriting.policy import PolicyChain

from radar_runtime.runtime import CausalCommit, RadarReducer
from radar_runtime.service_evidence import (
    DataState,
    PersistentServiceBindings,
    ServicePhase,
    ServiceStatus,
)

WORKBENCH_SCHEMA_VERSION = 1
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


class ShadowMetadataSource(Protocol):
    def workbench_option_metadata(self) -> tuple[Mapping[str, object], ...]: ...


StatusSink = Callable[[ServiceStatus], object]


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

    def read(self) -> PublishedSnapshot:
        with self._lock:
            return self._snapshot

    @staticmethod
    def _build_snapshot(
        sequence: int,
        document: Mapping[str, object],
    ) -> PublishedSnapshot:
        value = dict(document)
        value["publication_sequence"] = sequence
        body = _json_bytes(value)
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
        bindings: PersistentServiceBindings,
        policies: PolicyChain,
        downstream_writer: DownstreamEvidenceWriter,
        shadow_metadata: ShadowMetadataSource,
        status_sink: StatusSink | None = None,
        initial_recorded_monotonic_ms: int = 0,
    ) -> None:
        self.store = store
        self.bindings = bindings
        self.policies = policies
        self.downstream_writer = downstream_writer
        self.shadow_metadata = shadow_metadata
        self.status_sink = status_sink
        self._status = ServiceStatus(
            ServicePhase.STARTING,
            DataState.UNKNOWN,
            True,
            False,
            False,
            "STARTING",
            initial_recorded_monotonic_ms,
        )
        self._last_status_key: tuple[object, ...] | None = None
        self._last_business: Mapping[str, object] = MappingProxyType(_empty_business_projection())

    @property
    def status(self) -> ServiceStatus:
        return self._status

    def update_status(self, status: ServiceStatus, *, persist: bool = True) -> None:
        status_key = _status_key(status)
        if persist and status_key != self._last_status_key and self.status_sink is not None:
            self.status_sink(status)
        self._last_status_key = status_key
        self._status = status
        self.store.publish(self._document(self._last_business, status=status))

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
        objects = tuple(self.downstream_writer.objects)
        metadata = self.shadow_metadata.workbench_option_metadata()
        business = _build_business_projection(
            reducer=reducer,
            commit=commit,
            objects=objects,
            policies=self.policies,
            option_metadata=metadata,
        )
        normalized = canonical_value(business)
        if not isinstance(normalized, dict):
            raise TypeError("workbench business projection must be an object")
        self._last_business = MappingProxyType(normalized)
        status_key = _status_key(status)
        if status_key != self._last_status_key and self.status_sink is not None:
            self.status_sink(status)
        self._last_status_key = status_key
        self._status = status
        self.store.publish(self._document(self._last_business, status=status))

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
            "service": _status_object(status),
            **dict(business),
            "non_claims": list(WORKBENCH_NON_CLAIMS),
        }


def initial_workbench_document(
    bindings: PersistentServiceBindings,
    *,
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
        "service": _status_object(status),
        **_empty_business_projection(),
        "non_claims": list(WORKBENCH_NON_CLAIMS),
    }


def _build_business_projection(
    *,
    reducer: RadarReducer,
    commit: CausalCommit,
    objects: Sequence[Mapping[str, object]],
    policies: PolicyChain,
    option_metadata: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    trusted = _trusted_interval(reducer, commit.boundary.received_monotonic_ms)
    radar_rows = _radar_rows(reducer, commit, trusted)
    kinds = _objects_by_kind(objects)
    underwriting_rows = _underwriting_rows(kinds, policies)
    shadow_rows = _shadow_rows(kinds, policies)
    position_rows = _position_rows(
        kinds,
        policies,
        trusted_time=trusted,
        option_metadata=option_metadata,
    )
    outcome_rows = _outcome_rows(kinds)

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
    underwriting_counts = derive_underwriting_counts(objects)
    candidate_zero = zero_candidate_claim(
        candidate_count=underwriting_counts["candidate_count"],
        underwriting_evaluable_denominator=(
            underwriting_counts["underwriting_availability_evaluable_count"] or None
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
    return {
        "published_fact_boundary": _runtime_boundary_object(commit),
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
        },
        "zero_claims": {
            "anomaly": anomaly_zero.as_object(),
            "candidate": candidate_zero.as_object(),
        },
        "radar": {
            "panel_state": panel_state(radar_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not radar_rows else None,
            "rows": radar_rows,
        },
        "underwriting": {
            "panel_state": panel_state(underwriting_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not underwriting_rows else None,
            "rows": underwriting_rows,
        },
        "shadow_entries": {
            "panel_state": panel_state(shadow_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not shadow_rows else None,
            "simulation_label": SIMULATION_LABEL,
            "rows": shadow_rows,
        },
        "positions": {
            "panel_state": panel_state(position_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not position_rows else None,
            "rows": position_rows,
        },
        "outcomes": {
            "panel_state": panel_state(outcome_rows).value,
            "empty_label": EMPTY_PANEL_LABEL if not outcome_rows else None,
            "rows": outcome_rows,
        },
    }


def _radar_rows(
    reducer: RadarReducer,
    commit: CausalCommit,
    trusted: TimeInterval | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    trusted_interval = trusted
    for name, instrument in sorted(reducer.options.items()):
        result = reducer.results.get(name)
        tracker = reducer.trackers.get(name)
        calculation = result.calculation if result is not None else None
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
                "expiration_timestamp_ms": instrument.expiration_timestamp_ms,
                "tte_interval_ms": tte,
                "option_type": instrument.option_type.value,
                "strike_usdc_per_btc": str(instrument.strike),
                "detector_state": (
                    result.detector_state.value if result is not None else "UNKNOWN"
                ),
                "detector_reason": result.reason if result is not None else "NOT_SETTLED",
                "known_evaluation": (result.known_evaluation if result is not None else False),
                "tte_band_id": result.band_id if result is not None else None,
                "executable_sell_price_usdc_per_btc": (
                    str(calculation.executable_sell_price_usdc) if calculation is not None else None
                ),
                "executable_iv_interval": (
                    _decimal_interval(calculation.executable_bid_iv)
                    if calculation is not None
                    else None
                ),
                "baseline_annualized_volatility": (
                    str(calculation.baseline.annualized_volatility)
                    if calculation is not None
                    else None
                ),
                "richness_ratio_interval": (
                    _decimal_interval(calculation.richness) if calculation is not None else None
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
) -> list[dict[str, object]]:
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
    entries = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("SHADOW_ENTRY", ())
    }
    rows: list[dict[str, object]] = []
    for availability_value in _latest_by_payload_key(
        kinds.get("UNDERWRITING_AVAILABILITY_EVALUATION", ()),
        "radar_scope_or_short_leg_identity",
    ):
        availability_payload = _payload(availability_value)
        availability_identity = str(availability_value["object_identity"])
        action = _latest(actions_by_availability.get(availability_identity, ()))
        payload = _payload(action) if action is not None else {}
        action_identity = str(action["object_identity"]) if action is not None else None
        candidate = (
            candidates_by_action.get(action_identity) if action_identity is not None else None
        )
        candidate_identity = str(candidate["object_identity"]) if candidate is not None else None
        if candidate_identity in entries:
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
                "radar_scope_or_short_leg_identity": availability_payload.get(
                    "radar_scope_or_short_leg_identity"
                ),
                "underwriting_availability_evaluation_identity": availability_identity,
                "underwriting_action_identity": action_identity,
                "availability": availability,
                "unknown_reasons": unknown_reasons,
                "action": payload.get("economic_action"),
                "gross_entry_credit_usdc": payload.get("gross_entry_credit_usdc"),
                "entry_fee_reserve_usdc": payload.get("entry_fee_reserve_usdc"),
                "net_entry_credit_usdc": payload.get("net_entry_credit_usdc"),
                "contractual_payoff_max_loss_ex_fees_usdc": payload.get(
                    "contractual_payoff_max_loss_ex_fees_usdc"
                ),
                "future_cost_reserve_usdc": payload.get("future_cost_reserve_usdc"),
                "underwriting_reserved_loss_usdc": payload.get("underwriting_reserved_loss_usdc"),
                "reserve_breakdown_usdc": {
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
) -> str:
    if isinstance(action, str):
        return f"CONTROLLED_RUNTIME_ACTION:{action};FAILED_ECONOMIC_PREDICATE_VECTOR_NOT_PERSISTED"
    reasons = (
        ",".join(str(value) for value in unknown_reasons)
        if isinstance(unknown_reasons, list) and unknown_reasons
        else "NO_ADDITIONAL_REASON_PERSISTED"
    )
    return f"UNDERWRITING_{availability}:{reasons}"


def _shadow_rows(
    kinds: Mapping[str, Sequence[Mapping[str, object]]],
    policies: PolicyChain,
) -> list[dict[str, object]]:
    terminals = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("ADMISSION_ATTEMPT_TERMINAL", ())
    }
    invalidations = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("CANDIDATE_INVALIDATION", ())
    }
    entries = {
        str(_payload(value).get("candidate_identity")): value
        for value in kinds.get("SHADOW_ENTRY", ())
    }
    rows: list[dict[str, object]] = []
    for candidate in kinds.get("CANDIDATE_ACTIVATION", ()):
        candidate_identity = str(candidate["object_identity"])
        terminal = terminals.get(candidate_identity)
        invalidation = invalidations.get(candidate_identity)
        entry = entries.get(candidate_identity)
        entry_payload = _payload(entry) if entry is not None else {}
        terminal_payload = _payload(terminal) if terminal is not None else {}
        no_entry_reason = None
        if entry is None:
            no_entry_reason = (
                _payload(invalidation).get("primary_reason")
                if invalidation is not None
                else terminal_payload.get("terminal_outcome", "PENDING_REFRESH")
            )
        target_quantity = entry_payload.get("full_quantity_btc") or str(
            policies.underwriting.target_base_quantity_btc
        )
        entry_price = _consumed_levels_vwap(
            entry_payload.get("entry_consumed_levels"),
            target_quantity,
        )
        rows.append(
            {
                "candidate_identity": candidate_identity,
                "candidate_formed_fact_boundary": _payload(candidate).get(
                    "candidate_activation_fact_boundary"
                ),
                "admission_refresh_terminal_outcome": terminal_payload.get("terminal_outcome"),
                "matched_refresh_source_identity": terminal_payload.get(
                    "matched_response_identity"
                ),
                "shadow_entry_identity": (
                    str(entry["object_identity"]) if entry is not None else None
                ),
                "simulated_entry_price_usdc_per_btc": entry_price,
                "simulated_entry_price_availability": (
                    "AVAILABLE_FROM_PERSISTED_ATOMIC_CONSUMED_LEVELS"
                    if entry_price is not None
                    else "UNKNOWN"
                ),
                "simulated_entry_price_basis": (
                    "PERSISTED_ATOMIC_COMBO_CONSUMED_LEVELS_VWAP"
                    if entry_price is not None
                    else None
                ),
                "simulated_entry_credit_usdc": entry_payload.get("gross_entry_credit_usdc"),
                "target_quantity_btc": target_quantity,
                "entry_consumed_levels": entry_payload.get("entry_consumed_levels"),
                "no_entry_reason": no_entry_reason,
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
        selected = selected_by_entry.get(entry_identity)
        outcome = outcomes_by_entry.get(entry_identity)
        leg_ids = entry_payload.get("canonical_leg_identities")
        expiry_ms = None
        if isinstance(leg_ids, list):
            expiries = {
                expiry_by_leg.get(str(identity))
                for identity in leg_ids
                if expiry_by_leg.get(str(identity)) is not None
            }
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
                "remaining_premium_usdc": remaining_premium,
                "remaining_premium_availability": (
                    "AVAILABLE_FROM_PERSISTED_ATOMIC_CLOSE_ECONOMICS"
                    if remaining_premium is not None
                    else "UNKNOWN"
                ),
                "remaining_premium_basis": (
                    "MAX_ZERO_NEGATIVE_GROSS_CLOSE_CASHFLOW_USDC"
                    if remaining_premium is not None
                    else None
                ),
                "atomic_close_quote_state": quote_payload.get("close_quote_state", "UNKNOWN"),
                "current_atomic_close_debit_usdc": opportunity_payload.get("net_close_debit_usdc"),
                "projected_shadow_pnl_usdc": opportunity_payload.get(
                    "projected_shadow_net_pnl_usdc"
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
                "net_pnl_after_public_standard_fee_reserve_usdc": (
                    outcome_payload.get("net_pnl_after_public_standard_fee_reserve_usdc")
                ),
                "actual_pnl_usdc": outcome_payload.get("actual_pnl_usdc"),
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


def _empty_business_projection() -> dict[str, object]:
    empty = {
        "panel_state": PanelState.EMPTY_NO_SETTLED_OBJECT.value,
        "empty_label": EMPTY_PANEL_LABEL,
        "rows": [],
    }
    return {
        "published_fact_boundary": None,
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
        "underwriting": dict(empty),
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


def _consumed_levels_vwap(levels: object, full_quantity: object) -> str | None:
    quantity = _decimal_or_none(full_quantity)
    if quantity is None or quantity <= 0 or not isinstance(levels, list) or not levels:
        return None
    amount_sum = Decimal(0)
    total = Decimal(0)
    for level in levels:
        if not isinstance(level, Mapping):
            return None
        price = _decimal_or_none(level.get("price_usdc_per_btc"))
        amount = _decimal_or_none(level.get("amount_btc"))
        if price is None or amount is None or amount <= 0:
            return None
        amount_sum += amount
        total += price * amount
    if amount_sum != quantity:
        return None
    return canonical_decimal(total / quantity)


def _runtime_boundary_object(commit: CausalCommit) -> dict[str, object]:
    boundary = commit.boundary
    return {
        "session_epoch": boundary.session_epoch,
        "ingress_seq": boundary.ingress_seq,
        "received_monotonic_ms": boundary.received_monotonic_ms,
        "causal_seq": boundary.causal_seq,
        "cause": commit.cause.value,
    }


def _json_bytes(value: Mapping[str, object]) -> bytes:
    normalized = canonical_value(value)
    return (
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


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
    <section><h2>系统状态</h2><div id="system" class="grid"></div></section>
    <section><h2>业务零值证明</h2><div id="zero" class="grid"></div></section>
    <section><h2>Radar</h2><div id="radar"></div></section>
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

CSS = """*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#e6edf3}header,footer{padding:20px 5vw;background:#161b22}main{padding:20px 5vw}section{margin:0 0 24px;padding:18px;background:#161b22;border:1px solid #30363d;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.card{padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow-wrap:anywhere}.label{color:#8b949e;font-size:.85rem}.value{font-weight:650;margin-top:4px}.warning{padding:10px;border:1px solid #d29922;background:#2d2308;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{padding:8px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}th{color:#8b949e}.empty{color:#d29922}.UNKNOWN,.STALE,.INTERRUPTED{color:#f0883e}.CURRENT,.PROVEN_ZERO{color:#3fb950}.DEGRADED{color:#d29922}@media(max-width:800px){table{display:block;overflow-x:auto}}"""

JS = r"""const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[character]);
const displayText = value => {
  if (value === null || value === undefined || value === '') return 'UNKNOWN';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};
const safeText = value => escapeHtml(displayText(value));
const card = (label, value) =>
  `<div class="card"><div class="label">${escapeHtml(label)}</div>` +
  `<div class="value">${safeText(value)}</div></div>`;
const table = (panel, columns) => {
  if (panel.panel_state === 'EMPTY_NO_SETTLED_OBJECT') {
    return `<p class="empty">${safeText(panel.empty_label)}</p>`;
  }
  const header = columns.map(column => `<th>${escapeHtml(column[0])}</th>`).join('');
  const rows = panel.rows.map(row => {
    const cells = columns.map(column => `<td>${safeText(row[column[1]])}</td>`).join('');
    return `<tr>${cells}</tr>`;
  }).join('');
  return `<table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`;
};
const businessPanelIds = ['zero', 'radar', 'underwriting', 'shadow', 'positions', 'outcomes'];
let lastSuccessfulFetchAtMs = null;
let lastPublicationRuntimeIdentity = null;
let lastPublicationSequence = null;
let lastPublicationChangeAtMs = null;
const ageMs = timestamp => timestamp === null ? 'UNKNOWN' : Math.max(0, Date.now() - timestamp);
function renderUnavailable() {
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
function render(documentValue) {
  const connection = document.getElementById('connection');
  connection.hidden = true;
  connection.textContent = '';
  document.body.dataset.workbenchState = 'CURRENT_FETCH';
  document.getElementById('runtime').textContent = `runtime ${documentValue.runtime_identity}`;
  const service = documentValue.service;
  const system = documentValue.system;
  document.getElementById('system').innerHTML =
    card('Radar', service.phase) +
    card('数据状态', service.data_state) +
    card('Ready', service.ready) +
    card('Policy / Radar', documentValue.policy_identities.radar) +
    card('Policy / Underwriting', documentValue.policy_identities.underwriting) +
    card('Policy / Position', documentValue.policy_identities.position) +
    card('Publication sequence', documentValue.publication_sequence) +
    card('最近成功获取 age ms', ageMs(lastSuccessfulFetchAtMs)) +
    card('Publication 未变化 age ms', ageMs(lastPublicationChangeAtMs)) +
    card('Session epoch', system.session_epoch) +
    card('Platform', system.platform_reason) +
    card('最近行情时间', system.latest_market_timestamp_ms) +
    card('数据延迟 ms', system.data_delay_ms) +
    card('Last-wire age ms', system.last_wire_age_ms) +
    card('Coverage', system.coverage_state) +
    card('Coverage blocker', system.coverage_blocking_reason) +
    card('覆盖率 %', system.coverage_ratio_percent) +
    card('断线/重连', system.reconnect_count) +
    card('Session gaps', system.session_gap_count) +
    card('最近断线记录', system.disconnect_records.slice(-1)[0]);
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
  document.getElementById('radar').innerHTML = table(documentValue.radar, [
    ['合约', 'instrument_name'], ['到期时间', 'expiration_timestamp_ms'],
    ['TTE', 'tte_interval_ms'], ['类型', 'option_type'],
    ['Strike', 'strike_usdc_per_btc'], ['Executable IV', 'executable_iv_interval'],
    ['基准波动率', 'baseline_annualized_volatility'], ['Richness', 'richness_ratio_interval'],
    ['Radar', 'detector_state'], ['原因', 'detector_reason'],
    ['Atomic combo', 'public_atomic_quote_state'],
    ['异常 identity', 'active_episode_identity'],
    ['异常开始', 'anomaly_started_monotonic_ms'],
    ['异常持续 ms', 'anomaly_active_duration_ms']
  ]);
  document.getElementById('underwriting').innerHTML = table(documentValue.underwriting, [
    ['Radar scope', 'radar_scope_or_short_leg_identity'],
    ['Availability', 'availability'], ['Action', 'action'],
    ['总权利金', 'gross_entry_credit_usdc'], ['净权利金', 'net_entry_credit_usdc'],
    ['最大损失', 'contractual_payoff_max_loss_ex_fees_usdc'],
    ['费用', 'entry_fee_reserve_usdc'], ['未来准备', 'future_cost_reserve_usdc'],
    ['准备金明细', 'reserve_breakdown_usdc'],
    ['承保准备损失', 'underwriting_reserved_loss_usdc'],
    ['Candidate 状态', 'candidate_lifecycle'],
    ['Candidate 有效', 'candidate_still_valid'],
    ['失效原因', 'candidate_invalidation_reason'], ['原因', 'decision_reason']
  ]);
  document.getElementById('shadow').innerHTML = table(documentValue.shadow_entries, [
    ['Candidate', 'candidate_identity'], ['形成边界', 'candidate_formed_fact_boundary'],
    ['刷新结果', 'admission_refresh_terminal_outcome'],
    ['刷新报价来源', 'matched_refresh_source_identity'],
    ['Shadow Entry', 'shadow_entry_identity'], ['目标数量', 'target_quantity_btc'],
    ['模拟入场价', 'simulated_entry_price_usdc_per_btc'],
    ['模拟入场价状态', 'simulated_entry_price_availability'],
    ['模拟权利金', 'simulated_entry_credit_usdc'],
    ['消耗组合报价', 'entry_consumed_levels'],
    ['未入场原因', 'no_entry_reason'], ['声明', 'simulation_label']
  ]);
  document.getElementById('positions').innerHTML = table(documentValue.positions, [
    ['Shadow Entry', 'shadow_entry_identity'], ['Action', 'position_action'],
    ['剩余权利金', 'remaining_premium_usdc'],
    ['剩余权利金状态', 'remaining_premium_availability'],
    ['剩余权利金口径', 'remaining_premium_basis'],
    ['Atomic close', 'atomic_close_quote_state'],
    ['Close debit', 'current_atomic_close_debit_usdc'],
    ['Shadow PnL', 'projected_shadow_pnl_usdc'],
    ['Hard-close 倒计时', 'hard_close_countdown_interval_ms'],
    ['退出规则', 'ordered_latched_exit_rules'],
    ['首要退出规则', 'primary_exit_rule'],
    ['Close eligibility', 'close_opportunity_eligibility'],
    ['Close 原因', 'close_opportunity_reason'],
    ['有效 close opportunity', 'valid_shadow_close_opportunity'],
    ['Outcome', 'outcome_state']
  ]);
  document.getElementById('outcomes').innerHTML = table(documentValue.outcomes, [
    ['Observation', 'shadow_observation_identity'], ['状态', 'state'],
    ['成熟度', 'maturity'], ['Selected exit', 'selected_exit_identity'],
    ['Public-quote PnL', 'net_pnl_after_public_standard_fee_reserve_usdc'],
    ['Actual PnL', 'actual_pnl_usdc']
  ]);
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

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_CONNECT(self) -> None:
        self._method_not_allowed()

    def do_TRACE(self) -> None:
        self._method_not_allowed()

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


def write_static_fixture(path: Path, document: Mapping[str, object]) -> None:
    """Test helper for UI fixtures; not used by the runtime or HTTP path."""
    path.write_bytes(_json_bytes(document))

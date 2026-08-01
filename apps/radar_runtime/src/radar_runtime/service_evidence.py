from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from short_vol_radar.evidence import (
    EvidenceError,
    validate_anomaly_event,
    validate_atomic_event,
    validate_persistent_service_evidence_directory,
    validate_radar_object_relationships,
)
from short_vol_underwriting.conservation import (
    COHORT_COUNT_KEYS,
    COHORT_RATE_KEYS,
    UNDERWRITING_COUNT_KEYS,
    UNDERWRITING_RATE_KEYS,
    cohort_conservation_status,
    compute_cohort_rates,
    compute_underwriting_rates,
    derive_cohort_counts,
    derive_underwriting_counts,
    underwriting_conservation_status,
)
from short_vol_underwriting.evidence import (
    DownstreamEvidenceError,
    RuntimeBindings,
    read_current_evidence,
)
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary
from short_vol_underwriting.validation import (
    PayloadValidationError,
    validate_attempt_relationships,
    validate_complete_semantic_graph,
    validate_object_graph,
)

PERSISTENT_SERVICE_CONTRACT_DIGEST = (
    "sha256:9c3b46eae8b646d2c86f38df35cfcf962605c0b670385376d7c2ebef3a771778"
)
PERSISTENT_SERVICE_SEMANTIC_IDENTITY = "SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE"
SERVICE_NON_CLAIMS = (
    "THIS_ARTIFACT_DOES_NOT_GRANT_LIVE_OR_DEPLOYMENT_AUTHORITY",
    "PUBLIC_QUOTE_NOT_FILL",
    "NO_ACTUAL_EXPOSURE_OR_PNL",
    "NOT_A_FORWARD_COHORT",
    "NO_POLICY_QUALITY_OR_PROFITABILITY_CLAIM",
)
EVENT_KEYS = {
    "object_kind",
    "content_schema_identity",
    "object_identity",
    "persistent_service_contract_identity",
    "code_identity",
    "runtime_identity",
    "radar_policy_identity",
    "underwriting_policy_identity",
    "position_policy_identity",
    "event_sequence",
    "service_phase",
    "data_state",
    "health",
    "ready",
    "stale",
    "reason",
    "recorded_monotonic_ms",
    "non_claims",
}
TERMINAL_KEYS = {
    "object_kind",
    "content_schema_identity",
    "object_identity",
    "persistent_service_contract_identity",
    "code_identity",
    "runtime_identity",
    "radar_policy_identity",
    "underwriting_policy_identity",
    "position_policy_identity",
    "terminal_disposition",
    "terminal_source_identity",
    "terminal_fact_boundary",
    "radar_evidence_status",
    "downstream_evidence_status",
    "service_evidence_status",
    "radar_summary_relative_path",
    "radar_object_count",
    "radar_inventory_identity",
    "downstream_object_count",
    "downstream_inventory_identity",
    "underwriting_counts",
    "underwriting_rates",
    "underwriting_conservation_status",
    "cohort_counts",
    "cohort_rates",
    "cohort_conservation_status",
    "cohort_enrollment_mode",
    "forward_cohort_summary_emitted",
    "lifecycle_event_count",
    "lifecycle_inventory_identity",
    "non_claims",
}
FORBIDDEN_DOWNSTREAM_SUMMARIES = frozenset(
    {
        "UNDERWRITING_POSITION_SUMMARY",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    }
)


class PersistentServiceEvidenceError(ValueError):
    """Persistent-service evidence is malformed, mixed, incomplete, or conflicting."""


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
class PersistentServiceBindings:
    code_identity: str
    runtime_identity: str
    radar_policy_identity: str
    underwriting_policy_identity: str
    position_policy_identity: str
    contract_digest: str = PERSISTENT_SERVICE_CONTRACT_DIGEST

    def __post_init__(self) -> None:
        try:
            require_code_identity(self.code_identity)
            require_identity(self.runtime_identity, "runtime_identity")
            require_identity(self.radar_policy_identity, "radar_policy_identity")
            require_identity(self.underwriting_policy_identity, "underwriting_policy_identity")
            require_identity(self.position_policy_identity, "position_policy_identity")
            require_identity(self.contract_digest, "persistent service contract digest")
        except ValueError as exc:
            raise PersistentServiceEvidenceError(str(exc)) from exc
        if self.contract_digest != PERSISTENT_SERVICE_CONTRACT_DIGEST:
            raise PersistentServiceEvidenceError("persistent service contract digest mismatch")

    @property
    def contract_identity(self) -> str:
        return canonical_identity(
            "PERSISTENT_SERVICE_CONTRACT",
            PERSISTENT_SERVICE_SEMANTIC_IDENTITY,
            self.contract_digest,
            self.code_identity,
            self.runtime_identity,
            self.radar_policy_identity,
            self.underwriting_policy_identity,
            self.position_policy_identity,
        )

    @classmethod
    def from_runtime_bindings(cls, bindings: RuntimeBindings) -> PersistentServiceBindings:
        return cls(
            code_identity=bindings.code_identity,
            runtime_identity=bindings.runtime_identity,
            radar_policy_identity=bindings.radar_policy_identity,
            underwriting_policy_identity=bindings.underwriting_policy_identity,
            position_policy_identity=bindings.position_policy_identity,
        )


@dataclass(frozen=True)
class PersistentServiceEvidence:
    events: tuple[Mapping[str, object], ...]
    terminal: Mapping[str, object] | None


class PersistentServiceEvidenceWriter:
    def __init__(
        self,
        directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_directory: Path,
        radar_directory: Path,
        downstream_bindings: RuntimeBindings,
    ) -> None:
        if not directory.is_dir():
            raise PersistentServiceEvidenceError("service evidence directory must already exist")
        self.directory = directory
        self.events_directory = directory / "events"
        self.events_directory.mkdir(exist_ok=True)
        self.bindings = bindings
        self.downstream_directory = downstream_directory
        self.radar_directory = radar_directory
        self.downstream_bindings = downstream_bindings
        self._events: list[dict[str, object]] = []
        self._terminal: dict[str, object] | None = None

    @property
    def events(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._events)

    @property
    def terminal(self) -> Mapping[str, object] | None:
        return self._terminal

    def write_event(self, status: ServiceStatus) -> Path | None:
        if self._terminal is not None:
            raise PersistentServiceEvidenceError("terminal service cannot accept lifecycle events")
        if self._events and status.recorded_monotonic_ms < _non_negative_int(
            self._events[-1]["recorded_monotonic_ms"],
            "recorded_monotonic_ms",
        ):
            raise PersistentServiceEvidenceError("lifecycle monotonic time moved backward")
        sequence = len(self._events) + 1
        identity = canonical_identity(
            "PersistentServiceLifecycleEventIdentity",
            self.bindings.contract_identity,
            sequence,
            status.phase.value,
            status.data_state.value,
            status.health,
            status.ready,
            status.stale,
            status.reason,
            status.recorded_monotonic_ms,
        )
        value: dict[str, object] = {
            "object_kind": "PERSISTENT_SERVICE_LIFECYCLE_EVENT",
            "content_schema_identity": canonical_identity(
                "PERSISTENT_SERVICE_CONTENT_SCHEMA",
                self.bindings.contract_digest,
                "PERSISTENT_SERVICE_LIFECYCLE_EVENT",
            ),
            "object_identity": identity,
            "persistent_service_contract_identity": self.bindings.contract_identity,
            "code_identity": self.bindings.code_identity,
            "runtime_identity": self.bindings.runtime_identity,
            "radar_policy_identity": self.bindings.radar_policy_identity,
            "underwriting_policy_identity": self.bindings.underwriting_policy_identity,
            "position_policy_identity": self.bindings.position_policy_identity,
            "event_sequence": sequence,
            "service_phase": status.phase.value,
            "data_state": status.data_state.value,
            "health": status.health,
            "ready": status.ready,
            "stale": status.stale,
            "reason": status.reason,
            "recorded_monotonic_ms": status.recorded_monotonic_ms,
            "non_claims": list(SERVICE_NON_CLAIMS),
        }
        validate_lifecycle_event(value, bindings=self.bindings)
        path = self.events_directory / (f"{sequence:020d}-{identity.removeprefix('sha256:')}.json")
        published = _publish_exclusive(path, _serialize(value))
        self._events.append(value)
        return published

    def finalize(
        self,
        *,
        terminal_disposition: str,
        terminal_source_identity: str,
        terminal_fact_boundary: FactBoundary,
    ) -> Path:
        if terminal_disposition not in {"CLEAN_STOP", "PROCESS_FAILURE"}:
            raise PersistentServiceEvidenceError("invalid service terminal disposition")
        try:
            require_identity(terminal_source_identity, "terminal_source_identity")
        except ValueError as exc:
            raise PersistentServiceEvidenceError(str(exc)) from exc
        if self._terminal is not None:
            existing = self._terminal
            if (
                existing["terminal_disposition"] != terminal_disposition
                or existing["terminal_source_identity"] != terminal_source_identity
                or existing["terminal_fact_boundary"] != terminal_fact_boundary.as_object()
            ):
                raise PersistentServiceEvidenceError("service terminal barrier is immutable")
            return self.directory / "terminal.json"

        terminal_phase = (
            ServicePhase.STOPPED if terminal_disposition == "CLEAN_STOP" else ServicePhase.FAILED
        )
        terminal_status = ServiceStatus(
            phase=terminal_phase,
            data_state=DataState.STOPPED,
            health=False,
            ready=False,
            stale=False,
            reason=terminal_disposition,
            recorded_monotonic_ms=terminal_fact_boundary.received_monotonic_ms,
        )
        if not self._events or not _event_matches_status(self._events[-1], terminal_status):
            self.write_event(terminal_status)
        value = _build_terminal_value(
            service_directory=self.directory,
            radar_directory=self.radar_directory,
            downstream_directory=self.downstream_directory,
            bindings=self.bindings,
            downstream_bindings=self.downstream_bindings,
            terminal_disposition=terminal_disposition,
            terminal_source_identity=terminal_source_identity,
            terminal_fact_boundary=terminal_fact_boundary,
            expected_lifecycle_event_count=len(self._events),
        )
        path = self.directory / "terminal.json"
        published = _publish_exclusive(path, _serialize(value))
        if published is None:
            raise PersistentServiceEvidenceError(
                "first service terminal publication unexpectedly found an existing file"
            )
        self._terminal = value
        return path


def _event_matches_status(value: Mapping[str, object], status: ServiceStatus) -> bool:
    return (
        value.get("service_phase") == status.phase.value
        and value.get("data_state") == status.data_state.value
        and value.get("health") is status.health
        and value.get("ready") is status.ready
        and value.get("stale") is status.stale
        and value.get("reason") == status.reason
        and value.get("recorded_monotonic_ms") == status.recorded_monotonic_ms
    )


def validate_lifecycle_event(
    value: Mapping[str, object],
    *,
    bindings: PersistentServiceBindings,
) -> None:
    _exact_keys(value, EVENT_KEYS, "lifecycle event")
    _validate_bindings(value, bindings)
    if value["object_kind"] != "PERSISTENT_SERVICE_LIFECYCLE_EVENT":
        raise PersistentServiceEvidenceError("invalid lifecycle object kind")
    expected_schema = canonical_identity(
        "PERSISTENT_SERVICE_CONTENT_SCHEMA",
        bindings.contract_digest,
        "PERSISTENT_SERVICE_LIFECYCLE_EVENT",
    )
    if value["content_schema_identity"] != expected_schema:
        raise PersistentServiceEvidenceError("lifecycle content schema identity mismatch")
    sequence = _positive_int(value["event_sequence"], "event_sequence")
    phase = _enum(ServicePhase, value["service_phase"], "service_phase")
    data_state = _enum(DataState, value["data_state"], "data_state")
    health = _bool(value["health"], "health")
    ready = _bool(value["ready"], "ready")
    stale = _bool(value["stale"], "stale")
    reason = _string(value["reason"], "reason")
    recorded = _non_negative_int(value["recorded_monotonic_ms"], "recorded_monotonic_ms")
    ServiceStatus(phase, data_state, health, ready, stale, reason, recorded)
    _non_claims(value["non_claims"])
    expected_identity = canonical_identity(
        "PersistentServiceLifecycleEventIdentity",
        bindings.contract_identity,
        sequence,
        phase.value,
        data_state.value,
        health,
        ready,
        stale,
        reason,
        recorded,
    )
    if value["object_identity"] != expected_identity:
        raise PersistentServiceEvidenceError("lifecycle event identity mismatch")


def validate_terminal(
    value: Mapping[str, object],
    *,
    bindings: PersistentServiceBindings,
    downstream_bindings: RuntimeBindings,
    service_directory: Path,
    radar_directory: Path,
    downstream_directory: Path,
    lifecycle_events: Sequence[Mapping[str, object]],
) -> None:
    _exact_keys(value, TERMINAL_KEYS, "service terminal")
    _validate_bindings(value, bindings)
    if value["object_kind"] != "PERSISTENT_SERVICE_TERMINAL":
        raise PersistentServiceEvidenceError("invalid service terminal object kind")
    expected_schema = canonical_identity(
        "PERSISTENT_SERVICE_CONTENT_SCHEMA",
        bindings.contract_digest,
        "PERSISTENT_SERVICE_TERMINAL",
    )
    if value["content_schema_identity"] != expected_schema:
        raise PersistentServiceEvidenceError("terminal content schema identity mismatch")
    disposition = _string(value["terminal_disposition"], "terminal_disposition")
    if disposition not in {"CLEAN_STOP", "PROCESS_FAILURE"}:
        raise PersistentServiceEvidenceError("invalid terminal disposition")
    terminal_source = _identity(value["terminal_source_identity"], "terminal_source_identity")
    boundary = _boundary(value["terminal_fact_boundary"], "terminal_fact_boundary")
    if (
        boundary.code_identity != bindings.code_identity
        or boundary.runtime_identity != bindings.runtime_identity
    ):
        raise PersistentServiceEvidenceError("terminal boundary identity mismatch")
    if value["cohort_enrollment_mode"] != "DISABLED_NON_COHORT_SERVICE":
        raise PersistentServiceEvidenceError("persistent service cannot enroll a forward cohort")
    if value["forward_cohort_summary_emitted"] is not False:
        raise PersistentServiceEvidenceError("persistent service cannot emit cohort summary")
    if value["service_evidence_status"] != "COMPLETE":
        raise PersistentServiceEvidenceError("terminal service evidence must be COMPLETE")
    if value["downstream_evidence_status"] != "COMPLETE":
        raise PersistentServiceEvidenceError("terminal downstream evidence must be COMPLETE")
    if value["lifecycle_event_count"] != len(lifecycle_events):
        raise PersistentServiceEvidenceError("terminal lifecycle event count mismatch")
    expected_terminal_phase = (
        ServicePhase.STOPPED.value if disposition == "CLEAN_STOP" else ServicePhase.FAILED.value
    )
    if not lifecycle_events:
        raise PersistentServiceEvidenceError("service terminal requires lifecycle events")
    final_event = lifecycle_events[-1]
    if (
        final_event.get("service_phase") != expected_terminal_phase
        or final_event.get("data_state") != DataState.STOPPED.value
        or final_event.get("reason") != disposition
        or final_event.get("recorded_monotonic_ms") != boundary.received_monotonic_ms
    ):
        raise PersistentServiceEvidenceError(
            "terminal lifecycle event does not match the terminal boundary"
        )
    recomputed = _build_terminal_value(
        service_directory=service_directory,
        radar_directory=radar_directory,
        downstream_directory=downstream_directory,
        bindings=bindings,
        downstream_bindings=downstream_bindings,
        terminal_disposition=disposition,
        terminal_source_identity=terminal_source,
        terminal_fact_boundary=boundary,
        expected_lifecycle_event_count=len(lifecycle_events),
    )
    if dict(value) != recomputed:
        raise PersistentServiceEvidenceError("service terminal recomputation mismatch")


def read_current_persistent_service_evidence(
    run_directory: Path,
    *,
    bindings: PersistentServiceBindings,
    downstream_bindings: RuntimeBindings,
) -> PersistentServiceEvidence:
    service_directory = run_directory / "service"
    events_directory = service_directory / "events"
    radar_directory = run_directory / "radar"
    downstream_directory = run_directory / "downstream"
    if not events_directory.is_dir():
        raise PersistentServiceEvidenceError("service events directory is missing")
    entries = sorted(service_directory.iterdir(), key=lambda item: item.name)
    if any(item.name not in {"events", "terminal.json"} for item in entries):
        raise PersistentServiceEvidenceError("unexpected service evidence entry")
    events: list[dict[str, object]] = []
    previous_recorded = -1
    for expected_sequence, path in enumerate(sorted(events_directory.iterdir()), start=1):
        if not path.is_file() or path.is_symlink() or path.suffix != ".json":
            raise PersistentServiceEvidenceError("unexpected lifecycle event entry")
        value = _parse(path)
        validate_lifecycle_event(value, bindings=bindings)
        if value["event_sequence"] != expected_sequence:
            raise PersistentServiceEvidenceError("lifecycle event sequence is not contiguous")
        recorded = _non_negative_int(value["recorded_monotonic_ms"], "recorded_monotonic_ms")
        if recorded < previous_recorded:
            raise PersistentServiceEvidenceError("lifecycle monotonic time moved backward")
        previous_recorded = recorded
        expected_name = (
            f"{expected_sequence:020d}-{str(value['object_identity']).removeprefix('sha256:')}.json"
        )
        if path.name != expected_name:
            raise PersistentServiceEvidenceError("lifecycle event path identity mismatch")
        events.append(value)
    terminal_path = service_directory / "terminal.json"
    terminal: dict[str, object] | None = None
    if terminal_path.exists():
        if not terminal_path.is_file() or terminal_path.is_symlink():
            raise PersistentServiceEvidenceError("service terminal path is invalid")
        terminal = _parse(terminal_path)
        validate_terminal(
            terminal,
            bindings=bindings,
            downstream_bindings=downstream_bindings,
            service_directory=service_directory,
            radar_directory=radar_directory,
            downstream_directory=downstream_directory,
            lifecycle_events=events,
        )
    return PersistentServiceEvidence(tuple(events), terminal)


def read_complete_persistent_service_evidence(
    run_directory: Path,
    *,
    bindings: PersistentServiceBindings,
    downstream_bindings: RuntimeBindings,
) -> PersistentServiceEvidence:
    evidence = read_current_persistent_service_evidence(
        run_directory,
        bindings=bindings,
        downstream_bindings=downstream_bindings,
    )
    if evidence.terminal is None:
        raise PersistentServiceEvidenceError("complete service evidence requires terminal.json")
    if not evidence.events:
        raise PersistentServiceEvidenceError("complete service evidence requires lifecycle events")
    if evidence.events[0]["service_phase"] != ServicePhase.STARTING.value:
        raise PersistentServiceEvidenceError("complete service evidence must start at STARTING")
    terminal_phase = evidence.events[-1]["service_phase"]
    expected_phase = (
        "STOPPED" if evidence.terminal["terminal_disposition"] == "CLEAN_STOP" else "FAILED"
    )
    if terminal_phase != expected_phase:
        raise PersistentServiceEvidenceError("terminal lifecycle phase mismatch")
    return evidence


def _build_terminal_value(
    *,
    service_directory: Path,
    radar_directory: Path,
    downstream_directory: Path,
    bindings: PersistentServiceBindings,
    downstream_bindings: RuntimeBindings,
    terminal_disposition: str,
    terminal_source_identity: str,
    terminal_fact_boundary: FactBoundary,
    expected_lifecycle_event_count: int | None,
) -> dict[str, object]:
    expected_terminal_source = canonical_identity(
        "PersistentServiceTerminalSourceIdentity",
        bindings.contract_identity,
        terminal_disposition,
        terminal_fact_boundary.as_object(),
    )
    if terminal_source_identity != expected_terminal_source:
        raise PersistentServiceEvidenceError("persistent terminal source identity mismatch")
    try:
        objects_by_identity = read_current_evidence(
            downstream_directory,
            bindings=downstream_bindings,
        )
        validate_object_graph(objects_by_identity)
        validate_attempt_relationships(objects_by_identity, require_complete=True)
        validate_complete_semantic_graph(
            objects_by_identity,
            runtime_start=terminal_fact_boundary,
            enrollment_end=terminal_fact_boundary,
            terminal_boundary=terminal_fact_boundary,
            cohort_enrollment_mode="DISABLED_NON_COHORT_SERVICE",
        )
    except (DownstreamEvidenceError, PayloadValidationError) as exc:
        raise PersistentServiceEvidenceError(str(exc)) from exc
    objects = tuple(objects_by_identity.values())
    kinds = {str(value["object_kind"]) for value in objects}
    forbidden = kinds & FORBIDDEN_DOWNSTREAM_SUMMARIES
    if forbidden:
        raise PersistentServiceEvidenceError(
            f"persistent service contains bounded summary: {sorted(forbidden)}"
        )
    underwriting_counts = derive_underwriting_counts(objects)
    underwriting_rates = compute_underwriting_rates(underwriting_counts)
    underwriting_status = underwriting_conservation_status(underwriting_counts)
    cohort_counts = derive_cohort_counts(objects)
    cohort_rates = compute_cohort_rates(cohort_counts, evidence_status="COMPLETE")
    cohort_status = cohort_conservation_status(cohort_counts, evidence_status="COMPLETE")
    if underwriting_status != "MET" or cohort_status != "MET":
        raise PersistentServiceEvidenceError("persistent terminal conservation is not MET")
    if cohort_counts["shadow_pending_count"] or cohort_counts["rejected_pending_count"]:
        raise PersistentServiceEvidenceError("persistent terminal retains pending observations")
    if terminal_disposition == "CLEAN_STOP" and (
        cohort_counts["shadow_censored_failure_count"]
        or cohort_counts["rejected_censored_failure_count"]
    ):
        raise PersistentServiceEvidenceError("clean stop contains failure-censored observations")
    if terminal_disposition == "PROCESS_FAILURE" and (
        cohort_counts["shadow_censored_stop_count"] or cohort_counts["rejected_censored_stop_count"]
    ):
        raise PersistentServiceEvidenceError("process failure contains stop-censored observations")
    if any(
        bool(_mapping(value.get("payload"), "observation payload").get("cohort_enrolled"))
        for value in objects
        if value.get("object_kind")
        in {"SHADOW_OUTCOME_OBSERVATION", "REJECTED_COUNTERFACTUAL_OBSERVATION"}
    ):
        raise PersistentServiceEvidenceError("persistent service cannot enroll cohort observations")
    inventory = [
        [str(value["object_kind"]), str(value["object_identity"])]
        for value in sorted(
            objects,
            key=lambda item: (str(item["object_kind"]), str(item["object_identity"])),
        )
    ]
    inventory_identity = canonical_identity(
        "PersistentServiceDownstreamInventoryIdentity",
        bindings.contract_identity,
        inventory,
    )
    (
        radar_status,
        relative_summary,
        radar_object_count,
        radar_inventory_identity,
    ) = _validate_radar_inventory(
        radar_directory,
        bindings=bindings,
        terminal_disposition=terminal_disposition,
        terminal_fact_boundary=terminal_fact_boundary,
    )
    lifecycle_event_count, lifecycle_inventory_identity = _lifecycle_inventory(
        service_directory / "events",
        bindings=bindings,
    )
    if (
        expected_lifecycle_event_count is not None
        and lifecycle_event_count != expected_lifecycle_event_count
    ):
        raise PersistentServiceEvidenceError("lifecycle event count changed during terminal build")
    normalized_underwriting_counts = _ordered_counts(
        underwriting_counts,
        UNDERWRITING_COUNT_KEYS,
    )
    normalized_underwriting_rates = _ordered_rates(
        underwriting_rates,
        UNDERWRITING_RATE_KEYS,
    )
    normalized_cohort_counts = _ordered_counts(cohort_counts, COHORT_COUNT_KEYS)
    normalized_cohort_rates = _ordered_rates(cohort_rates, COHORT_RATE_KEYS)
    identity = canonical_identity(
        "PersistentServiceTerminalIdentity",
        bindings.contract_identity,
        terminal_disposition,
        terminal_source_identity,
        terminal_fact_boundary.as_object(),
        radar_status,
        "COMPLETE",
        "COMPLETE",
        radar_object_count,
        radar_inventory_identity,
        inventory_identity,
        normalized_underwriting_counts,
        normalized_underwriting_rates,
        underwriting_status,
        normalized_cohort_counts,
        normalized_cohort_rates,
        cohort_status,
        lifecycle_event_count,
        lifecycle_inventory_identity,
    )
    value: dict[str, object] = {
        "object_kind": "PERSISTENT_SERVICE_TERMINAL",
        "content_schema_identity": canonical_identity(
            "PERSISTENT_SERVICE_CONTENT_SCHEMA",
            bindings.contract_digest,
            "PERSISTENT_SERVICE_TERMINAL",
        ),
        "object_identity": identity,
        "persistent_service_contract_identity": bindings.contract_identity,
        "code_identity": bindings.code_identity,
        "runtime_identity": bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
        "terminal_disposition": terminal_disposition,
        "terminal_source_identity": terminal_source_identity,
        "terminal_fact_boundary": terminal_fact_boundary.as_object(),
        "radar_evidence_status": radar_status,
        "downstream_evidence_status": "COMPLETE",
        "service_evidence_status": "COMPLETE",
        "radar_summary_relative_path": relative_summary,
        "radar_object_count": radar_object_count,
        "radar_inventory_identity": radar_inventory_identity,
        "downstream_object_count": len(objects),
        "downstream_inventory_identity": inventory_identity,
        "underwriting_counts": normalized_underwriting_counts,
        "underwriting_rates": normalized_underwriting_rates,
        "underwriting_conservation_status": underwriting_status,
        "cohort_counts": normalized_cohort_counts,
        "cohort_rates": normalized_cohort_rates,
        "cohort_conservation_status": cohort_status,
        "cohort_enrollment_mode": "DISABLED_NON_COHORT_SERVICE",
        "forward_cohort_summary_emitted": False,
        "lifecycle_event_count": lifecycle_event_count,
        "lifecycle_inventory_identity": lifecycle_inventory_identity,
        "non_claims": list(SERVICE_NON_CLAIMS),
    }
    _non_claims(value["non_claims"])
    return value


def _validate_radar_inventory(
    directory: Path,
    *,
    bindings: PersistentServiceBindings,
    terminal_disposition: str,
    terminal_fact_boundary: FactBoundary,
) -> tuple[str, str | None, int, str]:
    if not directory.is_dir():
        raise PersistentServiceEvidenceError("Radar evidence directory is missing")
    inventory: list[list[str]] = []
    anomaly_objects: list[Mapping[str, object]] = []
    atomic_objects: list[Mapping[str, object]] = []
    summary_count = 0
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise PersistentServiceEvidenceError("cannot enumerate Radar evidence") from exc
    for path in entries:
        if not path.is_file() or path.is_symlink() or path.suffix != ".json":
            raise PersistentServiceEvidenceError("unexpected Radar evidence entry")
        exact = _read_exact(path)
        value = _parse_exact(exact, path)
        for field, expected in (
            ("code_identity", bindings.code_identity),
            ("runtime_identity", bindings.runtime_identity),
            ("policy_identity", bindings.radar_policy_identity),
        ):
            if value.get(field) != expected:
                raise PersistentServiceEvidenceError(f"Radar {field} binding mismatch")
        kind = value.get("object_kind")
        try:
            if kind == "SHORT_VOL_ANOMALY_EVENT":
                validate_anomaly_event(value)
                anomaly_objects.append(value)
            elif kind == "PUBLIC_ATOMIC_QUOTE_EVENT":
                validate_atomic_event(value)
                atomic_objects.append(value)
            elif kind == "RADAR_RUN_SUMMARY":
                summary_count += 1
            else:
                raise PersistentServiceEvidenceError("unknown Radar evidence object kind")
        except EvidenceError as exc:
            raise PersistentServiceEvidenceError(str(exc)) from exc
        inventory.append([path.name, _sha256_identity(exact)])
    try:
        validate_radar_object_relationships(
            anomalies=anomaly_objects,
            atomic_events=atomic_objects,
        )
    except EvidenceError as exc:
        raise PersistentServiceEvidenceError(str(exc)) from exc
    terminal_causal_seq = terminal_fact_boundary.causal_seq
    if any(
        _non_negative_int(value["causal_seq"], "anomaly causal_seq") > terminal_causal_seq
        for value in anomaly_objects
    ) or any(
        max(
            _non_negative_int(value["detector_causal_seq"], "atomic detector_causal_seq"),
            _non_negative_int(value["quote_causal_seq"], "atomic quote_causal_seq"),
        )
        > terminal_causal_seq
        for value in atomic_objects
    ):
        raise PersistentServiceEvidenceError(
            "Radar evidence causal boundary follows the service terminal"
        )
    summary_path = directory / "radar-run-summary.json"
    if terminal_disposition == "CLEAN_STOP":
        try:
            validate_persistent_service_evidence_directory(directory)
        except EvidenceError as exc:
            raise PersistentServiceEvidenceError(str(exc)) from exc
        if summary_count != 1 or not summary_path.is_file():
            raise PersistentServiceEvidenceError("clean service terminal lacks Radar summary")
        status = "COMPLETE_CLEAN_STOP"
        relative_summary: str | None = "radar/radar-run-summary.json"
    else:
        if summary_count or summary_path.exists():
            raise PersistentServiceEvidenceError(
                "process failure cannot claim a clean Radar summary"
            )
        status = "INCOMPLETE_PROCESS_FAILURE"
        relative_summary = None
    inventory_identity = canonical_identity(
        "PersistentServiceRadarInventoryIdentity",
        bindings.contract_identity,
        inventory,
    )
    return status, relative_summary, len(inventory), inventory_identity


def _lifecycle_inventory(
    events_directory: Path,
    *,
    bindings: PersistentServiceBindings,
) -> tuple[int, str]:
    if not events_directory.is_dir():
        raise PersistentServiceEvidenceError("service events directory is missing")
    inventory: list[list[str]] = []
    for expected_sequence, path in enumerate(
        sorted(events_directory.iterdir(), key=lambda item: item.name),
        start=1,
    ):
        if not path.is_file() or path.is_symlink() or path.suffix != ".json":
            raise PersistentServiceEvidenceError("unexpected lifecycle event entry")
        exact = _read_exact(path)
        value = _parse_exact(exact, path)
        validate_lifecycle_event(value, bindings=bindings)
        if value["event_sequence"] != expected_sequence:
            raise PersistentServiceEvidenceError("lifecycle event sequence is not contiguous")
        inventory.append([path.name, _sha256_identity(exact)])
    identity = canonical_identity(
        "PersistentServiceLifecycleInventoryIdentity",
        bindings.contract_identity,
        inventory,
    )
    return len(inventory), identity


def _validate_bindings(
    value: Mapping[str, object],
    bindings: PersistentServiceBindings,
) -> None:
    expected = {
        "persistent_service_contract_identity": bindings.contract_identity,
        "code_identity": bindings.code_identity,
        "runtime_identity": bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
    }
    for field, member in expected.items():
        if value.get(field) != member:
            raise PersistentServiceEvidenceError(f"{field} binding mismatch")
    _identity(value.get("object_identity"), "object_identity")


def _ordered_counts(value: Mapping[str, int], keys: tuple[str, ...]) -> dict[str, int]:
    if set(value) != set(keys):
        raise PersistentServiceEvidenceError("count registry requires exact keys")
    return {key: _non_negative_int(value[key], key) for key in keys}


def _ordered_rates(
    value: Mapping[str, Mapping[str, int] | None],
    keys: tuple[str, ...],
) -> dict[str, dict[str, int] | None]:
    if set(value) != set(keys):
        raise PersistentServiceEvidenceError("rate registry requires exact keys")
    result: dict[str, dict[str, int] | None] = {}
    for key in keys:
        member = value[key]
        if member is None:
            result[key] = None
            continue
        numerator = _non_negative_int(member.get("numerator"), f"{key}.numerator")
        denominator = _positive_int(member.get("denominator"), f"{key}.denominator")
        result[key] = {"numerator": numerator, "denominator": denominator}
    return result


def _serialize(value: Mapping[str, object]) -> bytes:
    try:
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
    except (TypeError, ValueError) as exc:
        raise PersistentServiceEvidenceError(
            f"service evidence is not canonical JSON: {exc}"
        ) from exc


def _publish_exclusive(path: Path, serialized: bytes) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        try:
            existing = path.read_bytes()
        except OSError as read_exc:
            raise PersistentServiceEvidenceError(
                "existing service evidence cannot be verified"
            ) from read_exc
        if existing == serialized:
            return None
        raise PersistentServiceEvidenceError("conflicting service evidence exists") from exc
    except OSError as exc:
        raise PersistentServiceEvidenceError(f"service evidence publish failed: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    _fsync(path.parent)
    if path.parent.parent.exists():
        _fsync(path.parent.parent)
    return path


def _fsync(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PersistentServiceEvidenceError(
            f"service evidence directory sync failed: {path}"
        ) from exc


def _parse(path: Path) -> dict[str, object]:
    exact = _read_exact(path)
    return _parse_exact(exact, path)


def _read_exact(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PersistentServiceEvidenceError(f"cannot read evidence: {path}") from exc


def _parse_exact(exact: bytes, path: Path) -> dict[str, object]:
    if exact.startswith(b"\xef\xbb\xbf") or not exact.endswith(b"\n"):
        raise PersistentServiceEvidenceError("evidence object must be UTF-8 and end in one LF")
    try:
        value = json.loads(
            exact.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, PersistentServiceEvidenceError) as exc:
        raise PersistentServiceEvidenceError(f"invalid service evidence JSON: {path}") from exc
    if not isinstance(value, dict) or _serialize(value) != exact:
        raise PersistentServiceEvidenceError("evidence is not canonical bytewise JSON")
    return value


def _sha256_identity(exact: bytes) -> str:
    return f"sha256:{hashlib.sha256(exact).hexdigest()}"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PersistentServiceEvidenceError(f"duplicate service JSON member: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> object:
    raise PersistentServiceEvidenceError(f"service JSON numbers must be integers: {value}")


def _reject_constant(value: str) -> object:
    raise PersistentServiceEvidenceError(f"service JSON number must be finite: {value}")


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise PersistentServiceEvidenceError(
            f"{field} requires exact keys; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PersistentServiceEvidenceError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersistentServiceEvidenceError(f"{field} must be a non-empty string")
    return value


def _identity(value: object, field: str) -> str:
    try:
        return require_identity(value, field)
    except ValueError as exc:
        raise PersistentServiceEvidenceError(str(exc)) from exc


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PersistentServiceEvidenceError(f"{field} must be boolean")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PersistentServiceEvidenceError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise PersistentServiceEvidenceError(f"{field} must be positive")
    return result


def _boundary(value: object, field: str) -> FactBoundary:
    try:
        return FactBoundary.from_object(value)
    except ValueError as exc:
        raise PersistentServiceEvidenceError(f"{field}: {exc}") from exc


def _enum[EnumT: StrEnum](enum_type: type[EnumT], value: object, field: str) -> EnumT:
    raw = _string(value, field)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise PersistentServiceEvidenceError(f"invalid {field}") from exc


def _non_claims(value: object) -> None:
    if value != list(SERVICE_NON_CLAIMS):
        raise PersistentServiceEvidenceError("service non_claims mismatch")

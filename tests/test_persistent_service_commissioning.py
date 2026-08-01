from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import radar_runtime.commissioning as commissioning
from radar_runtime.commissioning import (
    CommissioningController,
    CommissioningEnvelope,
    CommissioningError,
    CommissioningObservation,
    LifecycleObservation,
    MacOSHost,
    OperabilityObservation,
    SubprocessAudit,
    SubprocessProbe,
)
from radar_runtime.service_evidence import (
    PERSISTENT_SERVICE_CONTRACT_DIGEST,
    SERVICE_NON_CLAIMS,
    PersistentServiceBindings,
    PersistentServiceEvidence,
)
from radar_runtime.workbench import EMPTY_PANEL_LABEL, SIMULATION_LABEL, WORKBENCH_NON_CLAIMS
from short_vol_underwriting.identity import canonical_identity

CODE = "a" * 40
RUNTIME = "sha256:" + "b" * 64
RADAR_POLICY = "sha256:" + "c" * 64
UNDERWRITING_POLICY = "sha256:" + "d" * 64
POSITION_POLICY = "sha256:" + "e" * 64
BOUND_DIGEST = "sha256:" + "f" * 64


def _envelope_mapping(tmp_path: Path) -> dict[str, object]:
    root = (tmp_path / "deployment").resolve()
    repository = root / "repo"
    state_root = root / "state"
    python = repository / ".venv/bin/python"
    service_label = "com.optimatrix.public-shadow.r4"
    probe_label = f"{service_label}.probe"
    service_target = f"gui/501/{service_label}"
    probe_target = f"gui/501/{probe_label}"
    service_plist = root / f"{service_label}.plist"
    probe_plist = root / f"{probe_label}.plist"
    probe_script = root / "deployment/probe.py"
    audit_script = root / "deployment/audit.py"
    return {
        "schema_version": 1,
        "deployment_root": str(root),
        "repository": str(repository),
        "state_root": str(state_root),
        "journal_directory": str(root / "controller/journal"),
        "receipt_path": str(root / "controller/receipt.json"),
        "stop_receipt_path": str(root / "controller/stop-receipt.json"),
        "failure_closure_receipt_path": str(root / "controller/failure-closure-receipt.json"),
        "probe_ledger_path": str(root / "probe/probes.jsonl"),
        "service_label": service_label,
        "probe_label": probe_label,
        "service_target": service_target,
        "probe_target": probe_target,
        "service_plist_path": str(service_plist),
        "probe_plist_path": str(probe_plist),
        "uid": 501,
        "listener_host": "127.0.0.1",
        "listener_port": 8765,
        "expected_service_cwd": str(repository),
        "expected_service_argv": [
            str(python),
            "-m",
            "radar_runtime",
            "serve-shadow",
            "--state-root",
            str(state_root),
            "--workbench-host",
            "127.0.0.1",
            "--workbench-port",
            "8765",
        ],
        "service_bootstrap_argv": [
            "/bin/launchctl",
            "bootstrap",
            "gui/501",
            str(service_plist),
        ],
        "service_kickstart_argv": [
            "/bin/launchctl",
            "kickstart",
            service_target,
        ],
        "service_bootout_argv": ["/bin/launchctl", "bootout", service_target],
        "probe_bootstrap_argv": [
            "/bin/launchctl",
            "bootstrap",
            "gui/501",
            str(probe_plist),
        ],
        "probe_bootout_argv": ["/bin/launchctl", "bootout", probe_target],
        "service_sigint_argv": [
            "/bin/launchctl",
            "kill",
            "SIGINT",
            service_target,
        ],
        "manual_probe_argv": [str(python), str(probe_script), "--mode", "periodic"],
        "final_probe_argv": [str(python), str(probe_script), "--mode", "final-online"],
        "current_audit_argv": [
            str(python),
            str(audit_script),
            "--mode",
            "current",
            "--output",
            str(root / "audit/current.json"),
        ],
        "operability_audit_argv": [
            str(python),
            str(audit_script),
            "--mode",
            "current",
            "--output",
            str(root / "audit/operability.json"),
        ],
        "terminal_audit_argv": [
            str(python),
            str(audit_script),
            "--mode",
            "complete",
            "--output",
            str(root / "audit/terminal.json"),
        ],
        "diagnostic_report_directories": [
            "/Library/Logs/DiagnosticReports",
            "/Users/logan/Library/Logs/DiagnosticReports",
        ],
        "diagnostic_report_baseline": ["old.cpu_resource.diag"],
        "code_identity": CODE,
        "remote_main_tree": "f" * 40,
        "radar_policy_identity": RADAR_POLICY,
        "underwriting_policy_identity": UNDERWRITING_POLICY,
        "position_policy_identity": POSITION_POLICY,
        "persistent_service_contract_digest": PERSISTENT_SERVICE_CONTRACT_DIGEST,
        "authority_digest": BOUND_DIGEST,
        "task_digest": BOUND_DIGEST,
        "controller_digest": BOUND_DIGEST,
        "service_plist_digest": BOUND_DIGEST,
        "probe_plist_digest": BOUND_DIGEST,
        "probe_script_digest": BOUND_DIGEST,
        "audit_script_digest": BOUND_DIGEST,
        "python_executable_digest": BOUND_DIGEST,
        "python_version": "Python 3.13.5",
        "service_hot_path_digest": BOUND_DIGEST,
        "old_root_inventory_identities": {
            "r1": BOUND_DIGEST,
            "r2": BOUND_DIGEST,
            "r3": BOUND_DIGEST,
        },
        "preflight_facts": {
            "r1_no_writer": True,
            "r2_no_writer": True,
            "r3_no_writer": True,
            "old_labels_absent": True,
            "r4_root_absent_before_materialization": True,
            "r4_labels_absent_at_binding": True,
            "listener_free_at_binding": True,
            "installed_plists_absent_before_install": True,
        },
    }


def _event(
    *,
    contract_field: str = "persistent_service_contract_identity",
    recorded_monotonic_ms: int = 1_000,
) -> dict[str, object]:
    bindings = PersistentServiceBindings(
        code_identity=CODE,
        runtime_identity=RUNTIME,
        radar_policy_identity=RADAR_POLICY,
        underwriting_policy_identity=UNDERWRITING_POLICY,
        position_policy_identity=POSITION_POLICY,
    )
    event: dict[str, object] = {
        "object_kind": "PERSISTENT_SERVICE_LIFECYCLE_EVENT",
        "content_schema_identity": canonical_identity(
            "PERSISTENT_SERVICE_CONTENT_SCHEMA",
            bindings.contract_digest,
            "PERSISTENT_SERVICE_LIFECYCLE_EVENT",
        ),
        "object_identity": canonical_identity(
            "PersistentServiceLifecycleEventIdentity",
            bindings.contract_identity,
            1,
            "STARTING",
            "UNKNOWN",
            True,
            False,
            False,
            "STARTING",
            recorded_monotonic_ms,
        ),
        contract_field: (
            bindings.contract_identity
            if contract_field == "persistent_service_contract_identity"
            else bindings.contract_digest
        ),
        "code_identity": CODE,
        "runtime_identity": RUNTIME,
        "radar_policy_identity": RADAR_POLICY,
        "underwriting_policy_identity": UNDERWRITING_POLICY,
        "position_policy_identity": POSITION_POLICY,
        "event_sequence": 1,
        "service_phase": "STARTING",
        "data_state": "UNKNOWN",
        "health": True,
        "ready": False,
        "stale": False,
        "reason": "STARTING",
        "recorded_monotonic_ms": recorded_monotonic_ms,
        "non_claims": list(SERVICE_NON_CLAIMS),
    }
    return event


def _workbench_document(*, ready: bool = False, data_state: str = "UNKNOWN") -> dict[str, object]:
    empty_panel = {
        "panel_state": "EMPTY_NO_SETTLED_OBJECT",
        "empty_label": EMPTY_PANEL_LABEL,
        "rows": [],
    }
    zero_claim = {
        "state": "UNKNOWN",
        "value": None,
        "numerator": 0,
        "denominator": None,
        "explanation": "Required denominator is unavailable.",
    }
    return {
        "status": 200,
        "schema_version": 2,
        "runtime_identity": RUNTIME,
        "code_identity": CODE,
        "policy_identities": {
            "radar": RADAR_POLICY,
            "underwriting": UNDERWRITING_POLICY,
            "position": POSITION_POLICY,
        },
        "service": {
            "phase": "RUNNING",
            "data_state": data_state,
            "health": True,
            "ready": ready,
            "stale": data_state == "STALE",
            "reason": "INDEX_WARMUP",
            "recorded_monotonic_ms": 1_000,
        },
        "published_fact_boundary": None,
        "system": {
            "session_epoch": 1,
            "platform_usable": False,
            "platform_reason": "INDEX_WARMUP",
            "latest_market_timestamp_ms": None,
            "data_delay_ms": None,
            "last_wire_age_ms": None,
            "coverage_state": "UNKNOWN",
            "coverage_blocking_reason": "INDEX_WARMUP",
            "coverage_affected_scopes": [],
            "coverage_ratio_percent": None,
            "known_current_instrument_evaluation_count": 0,
            "monitored_instrument_count": 0,
            "reconnect_count": 0,
            "session_gap_count": 0,
            "global_continuity_epoch": 0,
            "disconnect_records": [],
        },
        "zero_claims": {
            "anomaly": dict(zero_claim),
            "candidate": dict(zero_claim),
        },
        "radar": dict(empty_panel),
        "underwriting": dict(empty_panel),
        "shadow_entries": {
            **empty_panel,
            "simulation_label": SIMULATION_LABEL,
        },
        "positions": dict(empty_panel),
        "outcomes": dict(empty_panel),
        "non_claims": list(WORKBENCH_NON_CLAIMS),
        "publication_sequence": 1,
    }


def _projection_envelope() -> CommissioningEnvelope:
    envelope = object.__new__(CommissioningEnvelope)
    for name, value in (
        ("code_identity", CODE),
        ("radar_policy_identity", RADAR_POLICY),
        ("underwriting_policy_identity", UNDERWRITING_POLICY),
        ("position_policy_identity", POSITION_POLICY),
    ):
        object.__setattr__(envelope, name, value)
    return envelope


def _validate_workbench_document(workbench: Mapping[str, object]) -> None:
    commissioning._validate_http_documents(
        _projection_envelope(),
        runtime_identity=RUNTIME,
        health={
            "status": 200,
            "schema_version": 2,
            "health": True,
            "runtime_identity": RUNTIME,
        },
        ready={
            "status": 503,
            "schema_version": 2,
            "ready": False,
            "runtime_identity": RUNTIME,
        },
        workbench=workbench,
        observed_monotonic_ms=2_000,
    )


def _failure_closure(controller: CommissioningController) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(controller.envelope.failure_closure_receipt_path.read_text(encoding="utf-8")),
    )


def _probe_row(
    envelope: CommissioningEnvelope,
    *,
    sequence: int,
    mode: str,
    monotonic_ms: int,
    pid: int = 123,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "mode": mode,
        "wall_time_utc": "2026-08-01T00:00:00+00:00",
        "monotonic_ms": monotonic_ms,
        "service_label": envelope.service_label,
        "launchd_pid": pid,
        "process": {
            "matching_process_count": 1,
            "matching_pids": [pid],
            "pid": pid,
            "argv": list(envelope.expected_service_argv),
            "cwd": str(envelope.expected_service_cwd),
            "listeners": [[pid, "127.0.0.1:8765"]],
            "rss_bytes": 4_096,
            "cpu_time_ms": 10,
        },
        "inventory": {
            "run_directories": [RUNTIME.removeprefix("sha256:")],
            "unexpected_run_entries": [],
            "file_count": 1,
            "byte_count": 1,
            "symlink_count": 0,
            "latest_mtime_ns": 1,
        },
        "runtime_identity": RUNTIME,
        "expected_runtime_identity": RUNTIME,
        "runtime_identity_frozen": True,
        "lifecycle_event_sequence": 1,
        "healthz": {
            "status": 200,
            "schema_version": 2,
            "health": True,
            "runtime_identity": RUNTIME,
        },
        "readyz": {
            "status": 503,
            "schema_version": 2,
            "ready": False,
            "runtime_identity": RUNTIME,
        },
        "workbench": _workbench_document(),
        "resource_sources_readable": True,
        "new_exact_pid_cpu_resource_event_count": 0,
        "errors": [],
        "operational_success": True,
    }


@dataclass
class FakeClock:
    now: int = 900

    def monotonic_ms(self) -> int:
        return self.now

    def wall_time(self) -> float:
        return datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC).timestamp()

    def sleep_until(self, deadline_ms: int) -> None:
        self.now = max(self.now, deadline_ms)


@dataclass
class FakeProbe:
    envelope: CommissioningEnvelope
    clock: FakeClock
    calls: list[tuple[str, int]] = field(default_factory=list)
    manual_monotonic_ms: int = 2_000

    def collect(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        expected_sequence: int,
        deadline_ms: int,
    ) -> Mapping[str, object]:
        self.calls.append((str(argv[-1]), deadline_ms))
        monotonic_ms = self.manual_monotonic_ms
        self.clock.now = monotonic_ms
        assert runtime_identity == RUNTIME
        return _probe_row(
            self.envelope,
            sequence=expected_sequence,
            mode=str(argv[-1]),
            monotonic_ms=monotonic_ms,
        )


@dataclass
class FakeAudit:
    envelope: CommissioningEnvelope
    clock: FakeClock
    calls: list[str] = field(default_factory=list)
    fail_current: bool = False
    current_monotonic_ms: int = 2_100
    invalid_terminal: bool = False
    terminal_integrity_status: str = "PASS_COMPLETE_CLEAN_STOP"
    terminal_business_status: str = "CLEAN_STOP_COMPLETE"
    terminal_business_acceptance: str = "OPERATIONAL_24H_GATE_NOT_MET"

    def run(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        deadline_ms: int,
    ) -> Mapping[str, object]:
        mode = str(argv[argv.index("--mode") + 1])
        self.calls.append(mode)
        if self.fail_current and mode == "current":
            raise CommissioningError("audit failed")
        current_call_count = self.calls.count("current")
        audit_monotonic_ms = self.current_monotonic_ms if current_call_count <= 1 else deadline_ms
        self.clock.now = audit_monotonic_ms
        result: dict[str, object] = {
            "schema_version": 1,
            "audit_mode": mode,
            "audit_monotonic_ms": audit_monotonic_ms,
            "reader_verdict": "PASS",
            "reader_integrity_status": (
                "PASS_CURRENT_INCOMPLETE" if mode == "current" else self.terminal_integrity_status
            ),
            "terminal_business_status": (
                "LIVE_INCOMPLETE_NO_TERMINAL"
                if mode == "current"
                else self.terminal_business_status
            ),
            "business_acceptance": (
                "PENDING_LIVE" if mode == "current" else self.terminal_business_acceptance
            ),
            "runtime_identity": runtime_identity,
            "envelope_identity": self.envelope.envelope_identity,
            "probe_evaluation": {
                "row_count": 1 if current_call_count <= 1 else 3,
                "contiguous_sequence": True,
                "all_operational_success": True,
                "all_rows_contract_valid": True,
                "first_probe_within_limit": True,
                "failure_marker_count": 0,
                "stderr_failure_sentinel_count": 0,
            },
            "twenty_four_hour_continuous_public_service_sample": (
                "PENDING" if mode == "current" else "NOT_MET"
            ),
            "operability_evaluation": {
                "present": current_call_count > 1,
                "valid": current_call_count > 1,
            },
        }
        if self.invalid_terminal and mode == "complete":
            result["reader_verdict"] = "FAIL"
        return result


@dataclass
class FakeHost:
    envelope: CommissioningEnvelope
    clock: FakeClock
    event: Mapping[str, object] = field(default_factory=_event)
    calls: list[str] = field(default_factory=list)
    fail_bootstrap: bool = False
    fail_kickstart: bool = False
    fail_lifecycle: bool = False
    fail_commissioning: bool = False
    fail_service_running: bool = False
    fail_terminal_wait: bool = False
    current_pid_available: bool = True
    lifecycle_observed_monotonic_ms: int = 1_000
    commission_observed_monotonic_ms: int = 1_000
    periodic_offsets_ms: tuple[int, ...] = (60_000, 120_000)
    operability_covered_from_delta_ms: int = 0
    all_probe_attempts_operational: bool = True
    resource_sources_readable: bool = True
    resource_boundary_delta_ms: int = 0
    resource_event_count: int = 0
    probe_bootstrap_delay_ms: int = 0
    observed_gate_start_ms: int | None = None
    observed_gate_end_ms: int | None = None
    observed_resource_boundary_ms: int | None = None
    service_is_running: bool = True
    receipt_existed_at_cleanup_start: bool | None = None
    receipt_bytes_at_cleanup_start: bytes | None = None

    def preflight(self) -> None:
        self.calls.append("preflight")

    def bootstrap_service(self) -> None:
        self.calls.append("bootstrap_service")
        if self.fail_bootstrap:
            raise CommissioningError("bootstrap failed after partial mutation")

    def kickstart_service(self) -> None:
        self.calls.append("kickstart_service")
        if self.fail_kickstart:
            raise CommissioningError("kickstart failed")

    def wait_for_lifecycle(self, *, deadline_ms: int) -> LifecycleObservation:
        self.calls.append("wait_for_lifecycle")
        if self.fail_lifecycle:
            self.clock.now = deadline_ms
            raise CommissioningError("lifecycle deadline exceeded")
        self.clock.now = self.lifecycle_observed_monotonic_ms
        return LifecycleObservation(
            run_directory=self.envelope.state_root / "runs" / RUNTIME.removeprefix("sha256:"),
            event=self.event,
            observed_monotonic_ms=self.lifecycle_observed_monotonic_ms,
        )

    def inspect_commissioning(
        self,
        *,
        runtime_identity: str,
        run_directory: Path,
        deadline_ms: int,
    ) -> CommissioningObservation:
        self.calls.append("inspect_commissioning")
        if self.fail_commissioning:
            raise CommissioningError("commissioning inspection failed after lifecycle")
        self.clock.now = self.commission_observed_monotonic_ms
        return CommissioningObservation(
            pid=123,
            launchd_runs=1,
            argv=self.envelope.expected_service_argv,
            cwd=self.envelope.expected_service_cwd,
            listeners=((123, "127.0.0.1:8765"),),
            healthz={
                "status": 200,
                "schema_version": 2,
                "health": True,
                "runtime_identity": RUNTIME,
            },
            readyz={
                "status": 503,
                "schema_version": 2,
                "ready": False,
                "runtime_identity": RUNTIME,
            },
            workbench=_workbench_document(),
            observed_monotonic_ms=self.commission_observed_monotonic_ms,
        )

    def bootstrap_periodic_probe(self) -> None:
        self.calls.append("bootstrap_periodic_probe")
        self.clock.now += self.probe_bootstrap_delay_ms

    def inspect_operability(
        self,
        *,
        pid: int,
        runtime_identity: str,
        gate_start_monotonic_ms: int,
        gate_end_monotonic_ms: int,
        resource_audit_boundary_monotonic_ms: int,
        resource_query_end_wall: float,
    ) -> OperabilityObservation:
        self.calls.append("inspect_operability")
        self.observed_gate_start_ms = gate_start_monotonic_ms
        self.observed_gate_end_ms = gate_end_monotonic_ms
        self.observed_resource_boundary_ms = resource_audit_boundary_monotonic_ms
        self.clock.now = resource_audit_boundary_monotonic_ms
        return OperabilityObservation(
            pid=pid,
            runtime_identity=runtime_identity,
            launchd_runs=1,
            covered_from_monotonic_ms=(
                gate_start_monotonic_ms + self.operability_covered_from_delta_ms
            ),
            covered_until_monotonic_ms=gate_end_monotonic_ms,
            periodic_row_monotonic_ms=tuple(
                gate_start_monotonic_ms + offset for offset in self.periodic_offsets_ms
            ),
            all_probe_attempts_operational=self.all_probe_attempts_operational,
            cpu_time_delta_ms=900,
            elapsed_monotonic_ms=180_000,
            cpu_utilization_percent="0.500000",
            rss_bytes=4_096,
            max_http_latency_ms=7,
            http_attempt_count=15,
            http_success_count=15,
            readiness_states=(False, False),
            data_states=("UNKNOWN", "UNKNOWN"),
            queue_lag_transition_count=0,
            resource_sources_readable=self.resource_sources_readable,
            resource_audit_boundary_monotonic_ms=(
                resource_audit_boundary_monotonic_ms + self.resource_boundary_delta_ms
            ),
            resource_query_start_wall_utc="2026-08-01T00:00:00+00:00",
            resource_query_end_wall_utc=datetime.fromtimestamp(
                resource_query_end_wall, tz=UTC
            ).isoformat(timespec="microseconds"),
            diagnostic_report_count_examined=0,
            unified_log_row_count_examined=0,
            new_exact_pid_cpu_resource_event_count=self.resource_event_count,
        )

    def bootout_periodic_probe(self) -> None:
        self.calls.append("bootout_periodic_probe")
        if self.receipt_existed_at_cleanup_start is None:
            self.receipt_existed_at_cleanup_start = self.envelope.receipt_path.is_file()
            if self.receipt_existed_at_cleanup_start:
                self.receipt_bytes_at_cleanup_start = self.envelope.receipt_path.read_bytes()

    def sigint_service(self) -> None:
        self.calls.append("sigint_service")

    def wait_for_terminal(self, *, run_directory: Path, deadline_ms: int) -> None:
        self.calls.append("wait_for_terminal")
        if self.fail_terminal_wait:
            raise CommissioningError("terminal deadline exceeded")

    def bootout_service(self) -> None:
        self.calls.append("bootout_service")

    def current_service_pid(self) -> int:
        self.calls.append("current_service_pid")
        if not self.current_pid_available:
            raise CommissioningError("service label is absent")
        return 123

    def service_running(self, *, expected_pid: int) -> bool:
        self.calls.append("service_running")
        assert expected_pid == 123
        if self.fail_service_running:
            raise CommissioningError("service liveness query failed")
        return self.service_is_running

    def verify_quiescent(self, *, expected_pid: int | None) -> None:
        self.calls.append("verify_quiescent")
        assert expected_pid in {None, 123}


def _controller(
    tmp_path: Path,
    *,
    event: Mapping[str, object] | None = None,
    manual_monotonic_ms: int = 2_000,
    fail_audit: bool = False,
    audit_monotonic_ms: int = 2_100,
    host_overrides: Mapping[str, object] | None = None,
) -> tuple[CommissioningController, FakeHost, FakeProbe, FakeAudit]:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    envelope.journal_directory.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    clock = FakeClock()
    probe = FakeProbe(envelope, clock, manual_monotonic_ms=manual_monotonic_ms)
    audit = FakeAudit(
        envelope,
        clock,
        fail_current=fail_audit,
        current_monotonic_ms=audit_monotonic_ms,
    )
    host = FakeHost(envelope, clock, event=_event() if event is None else event)
    for name, value in (host_overrides or {}).items():
        setattr(host, name, value)

    def current_reader(
        _run_directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_bindings: object,
    ) -> PersistentServiceEvidence:
        del bindings, downstream_bindings
        return PersistentServiceEvidence((host.event,), None)

    return (
        CommissioningController(
            envelope,
            host=host,
            clock=clock,
            probe=probe,
            audit=audit,
            current_reader=current_reader,
        ),
        host,
        probe,
        audit,
    )


def _materialize_wrapper_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CommissioningEnvelope, Path, Path, dict[str, object]]:
    mapping = _envelope_mapping(tmp_path)
    envelope = CommissioningEnvelope.from_mapping(mapping, allow_test_boundary=True)
    envelope_path = envelope.deployment_root / "deployment/deployment-envelope.json"
    envelope_path.parent.mkdir(parents=True, exist_ok=True)
    envelope_path.write_text(json.dumps(mapping) + "\n", encoding="utf-8")
    run_directory = envelope.state_root / "runs" / RUNTIME.removeprefix("sha256:")
    event_path = run_directory / "service/events/00000000000000000001.json"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event = _event()
    event_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    envelope.journal_directory.mkdir(parents=True, exist_ok=True)
    (envelope.journal_directory / "SERVICE_BOOTSTRAP_INTENT.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "SERVICE_BOOTSTRAP_INTENT",
                "envelope_identity": envelope.envelope_identity,
                "wall_time_utc": "2026-08-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (envelope.journal_directory / "KICKSTART_INTENT.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "KICKSTART_INTENT",
                "envelope_identity": envelope.envelope_identity,
                "wall_time_utc": "2026-08-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    production_from_mapping = CommissioningEnvelope.from_mapping

    def from_test_mapping(
        _cls: type[CommissioningEnvelope],
        value: Mapping[str, object],
    ) -> CommissioningEnvelope:
        return production_from_mapping(value, allow_test_boundary=True)

    monkeypatch.setattr(
        CommissioningEnvelope,
        "from_mapping",
        classmethod(from_test_mapping),
    )

    def current_reader(
        _run_directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_bindings: object,
    ) -> PersistentServiceEvidence:
        del bindings, downstream_bindings
        return PersistentServiceEvidence((event,), None)

    monkeypatch.setattr(
        commissioning,
        "read_current_persistent_service_evidence",
        current_reader,
    )
    return envelope, envelope_path, run_directory, event


def _write_probe_ledger(
    envelope: CommissioningEnvelope,
    rows: Sequence[Mapping[str, object]],
) -> None:
    envelope.probe_ledger_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.probe_ledger_path.write_text(
        "".join(json.dumps(dict(row)) + "\n" for row in rows),
        encoding="utf-8",
    )


def _operability_facts() -> dict[str, object]:
    return {
        "pid": 123,
        "runtime_identity": RUNTIME,
        "launchd_runs": 1,
        "gate_start_monotonic_ms": 2_100,
        "gate_end_monotonic_ms": 182_100,
        "covered_duration_ms": 180_000,
        "periodic_row_monotonic_ms": [62_100, 122_100],
        "partition_gap_ms": [60_000, 60_000, 60_000],
        "cpu_time_delta_ms": 900,
        "elapsed_monotonic_ms": 180_000,
        "cpu_utilization_percent": "0.500000",
        "cpu_utilization_denominator": "one_process_elapsed_monotonic_ms",
        "rss_bytes": 4_096,
        "max_http_latency_ms": 7,
        "http_attempt_count": 15,
        "http_success_count": 15,
        "readiness_states": [False, False],
        "data_states": ["UNKNOWN", "UNKNOWN"],
        "queue_lag_transition_count": 0,
        "resource_sources_readable": True,
        "resource_audit_boundary_monotonic_ms": 212_100,
        "resource_query_start_wall_utc": "2026-08-01T00:00:00+00:00",
        "resource_query_end_wall_utc": "2026-08-01T00:04:00.000000+00:00",
        "diagnostic_report_count_examined": 0,
        "unified_log_row_count_examined": 0,
        "new_exact_pid_cpu_resource_event_count": 0,
    }


def _write_stop_intent(envelope: CommissioningEnvelope) -> None:
    (envelope.journal_directory / "STOP_INTENT.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "STOP_INTENT",
                "envelope_identity": envelope.envelope_identity,
                "runtime_identity": RUNTIME,
                "wall_time_utc": "2026-08-02T00:00:00+00:00",
                "recorded_monotonic_ms": 86_401_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_valid_operability_journals(envelope: CommissioningEnvelope) -> None:
    (envelope.journal_directory / "HOST_OPERABILITY_GATE_START.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "HOST_OPERABILITY_GATE_START",
                "envelope_identity": envelope.envelope_identity,
                "runtime_identity": RUNTIME,
                "gate_start_monotonic_ms": 2_100,
                "gate_end_monotonic_ms": 182_100,
                "resource_audit_boundary_monotonic_ms": 212_100,
                "resource_query_end_wall_utc": "2026-08-01T00:04:00.000000+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (envelope.journal_directory / "HOST_OPERABILITY_GATE_RESULT.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "HOST_OPERABILITY_GATE_RESULT",
                "envelope_identity": envelope.envelope_identity,
                "runtime_identity": RUNTIME,
                "operability": _operability_facts(),
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_envelope_is_exact_and_forbids_kickstart_replace(tmp_path: Path) -> None:
    value = _envelope_mapping(tmp_path)
    envelope = CommissioningEnvelope.from_mapping(value, allow_test_boundary=True)
    assert envelope.service_kickstart_argv == (
        "/bin/launchctl",
        "kickstart",
        envelope.service_target,
    )

    with pytest.raises(CommissioningError, match="exact keys"):
        CommissioningEnvelope.from_mapping({**value, "extra": True}, allow_test_boundary=True)
    replaced = {
        **value,
        "service_kickstart_argv": ["/bin/launchctl", "kickstart", "-k", value["service_target"]],
    }
    with pytest.raises(CommissioningError, match="kickstart"):
        CommissioningEnvelope.from_mapping(replaced, allow_test_boundary=True)

    with pytest.raises(CommissioningError, match="production root/plist"):
        CommissioningEnvelope.from_mapping(value)
    with pytest.raises(CommissioningError, match="uid must be 501"):
        CommissioningEnvelope.from_mapping({**value, "uid": 502}, allow_test_boundary=True)
    with pytest.raises(CommissioningError, match="receipt paths must be distinct"):
        CommissioningEnvelope.from_mapping(
            {**value, "failure_closure_receipt_path": value["receipt_path"]},
            allow_test_boundary=True,
        )
    with pytest.raises(CommissioningError, match="must remain inside deployment_root"):
        CommissioningEnvelope.from_mapping(
            {**value, "failure_closure_receipt_path": str(tmp_path / "outside.json")},
            allow_test_boundary=True,
        )
    with pytest.raises(CommissioningError, match="r4 launchd labels are not exact"):
        CommissioningEnvelope.from_mapping(
            {
                **value,
                "service_label": "com.optimatrix.public-shadow.r3",
                "probe_label": "com.optimatrix.public-shadow.r3.probe",
            },
            allow_test_boundary=True,
        )
    with pytest.raises(CommissioningError, match="old_root_inventory_identities"):
        CommissioningEnvelope.from_mapping(
            {
                **value,
                "old_root_inventory_identities": {
                    "r1": BOUND_DIGEST,
                    "r2": BOUND_DIGEST,
                },
            },
            allow_test_boundary=True,
        )
    preflight_facts = value["preflight_facts"]
    assert isinstance(preflight_facts, dict)
    missing_r3_writer = dict(preflight_facts)
    del missing_r3_writer["r3_no_writer"]
    with pytest.raises(CommissioningError, match="preflight_facts"):
        CommissioningEnvelope.from_mapping(
            {**value, "preflight_facts": missing_r3_writer},
            allow_test_boundary=True,
        )


def test_all_executable_controller_vocabulary_is_bound_to_r4() -> None:
    source = Path(commissioning.__file__).read_text(encoding="utf-8")
    for stale in (
        "__OPTIMATRIX_R3_PREFLIGHT_UNMATCHABLE__",
        "Read-only r3 persistent-service probe",
        "Independent r3 persistent-service audit",
        "Deadline-safe r3 service controller",
        "SHORT_VOL_R3_DEADLINE_SAFE_SERVICE_ONLINE.md",
        "r3 uid must be 501",
        "r3 launchd labels are not exact",
        "r3 production root/plist boundary mismatch",
        "r3_root_absent_before_materialization",
        "r3_labels_absent_at_binding",
    ):
        assert stale not in source
    for current in (
        "__OPTIMATRIX_R4_PREFLIGHT_UNMATCHABLE__",
        "Read-only r4 persistent-service probe",
        "Independent r4 persistent-service audit",
        "Deadline-safe r4 service controller",
        "SHORT_VOL_R4_COMMISSIONING_INTEGRITY_REPAIR.md",
        "r4_root_absent_before_materialization",
        "r4_labels_absent_at_binding",
    ):
        assert current in source


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("session_epoch", -1),
        ("session_epoch", True),
        ("session_epoch", "1"),
        ("latest_market_timestamp_ms", -1),
        ("latest_market_timestamp_ms", True),
        ("latest_market_timestamp_ms", "1"),
        ("data_delay_ms", -1),
        ("data_delay_ms", True),
        ("data_delay_ms", "1"),
        ("last_wire_age_ms", -1),
        ("last_wire_age_ms", True),
        ("last_wire_age_ms", "1"),
    ],
)
def test_schema_2_workbench_system_time_fields_reject_negative_and_non_integer_values(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    workbench = _workbench_document()
    system = workbench["system"]
    assert isinstance(system, dict)
    system[field] = invalid_value

    with pytest.raises(CommissioningError, match="workbench system value mismatch"):
        commissioning._validate_http_documents(
            envelope,
            runtime_identity=RUNTIME,
            health={
                "status": 200,
                "schema_version": 2,
                "health": True,
                "runtime_identity": RUNTIME,
            },
            ready={
                "status": 503,
                "schema_version": 2,
                "ready": False,
                "runtime_identity": RUNTIME,
            },
            workbench=workbench,
            observed_monotonic_ms=2_000,
        )


@pytest.mark.parametrize(
    ("state", "value", "numerator", "denominator"),
    [
        ("UNKNOWN", None, 0, None),
        ("UNKNOWN", None, 0, 0),
        ("UNKNOWN", None, 0, 7),
        ("PROVEN_ZERO", 0, 0, 7),
        ("NOT_ZERO", 2, 2, None),
        ("NOT_ZERO", 2, 2, 2),
        ("NOT_ZERO", 2, 2, 7),
    ],
)
def test_schema_2_workbench_accepts_every_valid_zero_claim_shape(
    state: str,
    value: int | None,
    numerator: int,
    denominator: int | None,
) -> None:
    for name in ("anomaly", "candidate"):
        workbench = _workbench_document()
        zero_claims = workbench["zero_claims"]
        assert isinstance(zero_claims, dict)
        claim = zero_claims[name]
        assert isinstance(claim, dict)
        claim.update(
            {
                "state": state,
                "value": value,
                "numerator": numerator,
                "denominator": denominator,
            }
        )
        _validate_workbench_document(workbench)


@pytest.mark.parametrize(
    ("state", "value", "numerator", "denominator"),
    [
        ("UNKNOWN", 0, 0, None),
        ("UNKNOWN", None, 1, 7),
        ("UNKNOWN", None, -1, 7),
        ("UNKNOWN", None, True, 1),
        ("UNKNOWN", None, 0.0, 1),
        ("UNKNOWN", None, 0, -1),
        ("UNKNOWN", None, 0, True),
        ("UNKNOWN", None, 0, 1.0),
        ("PROVEN_ZERO", 0, 0, None),
        ("PROVEN_ZERO", 0, 0, 0),
        ("PROVEN_ZERO", 1, 0, 1),
        ("PROVEN_ZERO", False, 0, 1),
        ("NOT_ZERO", 2, 1, None),
        ("NOT_ZERO", 0, 0, None),
        ("NOT_ZERO", True, 1, None),
        ("NOT_ZERO", 2.0, 2, None),
        ("NOT_ZERO", 2, 2, 1),
        ("NOT_ZERO", 2, 2, 0),
        ("NOT_ZERO", 2, 2, True),
        ("NOT_ZERO", 2, 2, 2.0),
    ],
)
def test_schema_2_workbench_rejects_contradictory_zero_claim_shapes(
    state: str,
    value: object,
    numerator: object,
    denominator: object,
) -> None:
    workbench = _workbench_document()
    zero_claims = workbench["zero_claims"]
    assert isinstance(zero_claims, dict)
    claim = zero_claims["anomaly"]
    assert isinstance(claim, dict)
    claim.update(
        {
            "state": state,
            "value": value,
            "numerator": numerator,
            "denominator": denominator,
        }
    )
    with pytest.raises(CommissioningError, match="workbench zero claim anomaly value mismatch"):
        _validate_workbench_document(workbench)


def test_commissioning_accepts_actual_lifecycle_field_and_orders_effects(tmp_path: Path) -> None:
    controller, host, probe, audit = _controller(tmp_path)

    receipt = controller.commission()

    assert receipt.status == "COMMISSIONED"
    assert host.calls == [
        "preflight",
        "bootstrap_service",
        "kickstart_service",
        "wait_for_lifecycle",
        "current_service_pid",
        "inspect_commissioning",
        "bootstrap_periodic_probe",
        "inspect_operability",
    ]
    assert probe.calls == [("periodic", 91_000)]
    assert audit.calls == ["current", "current"]
    assert "sigint_service" not in host.calls
    assert not controller.envelope.failure_closure_receipt_path.exists()


def test_fabricated_contract_digest_field_fails_before_probe_and_stops_once(
    tmp_path: Path,
) -> None:
    event = _event(contract_field="contract_digest")
    controller, host, probe, audit = _controller(tmp_path, event=event)

    with pytest.raises(CommissioningError, match="lifecycle"):
        controller.commission()

    assert probe.calls == []
    assert audit.calls == ["complete"]
    assert host.calls.count("kickstart_service") == 1
    assert host.calls.count("sigint_service") == 1
    assert "bootstrap_periodic_probe" not in host.calls


@pytest.mark.parametrize("delay_ms", [90_001, 120_001])
def test_manual_probe_uses_lifecycle_absolute_deadline_and_never_loads_periodic_probe(
    tmp_path: Path,
    delay_ms: int,
) -> None:
    controller, host, _probe, _audit = _controller(
        tmp_path,
        manual_monotonic_ms=1_000 + delay_ms,
    )

    with pytest.raises(CommissioningError, match="manual probe deadline"):
        controller.commission()

    assert "bootstrap_periodic_probe" not in host.calls
    assert host.calls.count("sigint_service") == 1


def test_current_audit_failure_does_not_load_periodic_probe_and_stops_once(
    tmp_path: Path,
) -> None:
    controller, host, _probe, _audit = _controller(tmp_path, fail_audit=True)

    with pytest.raises(CommissioningError, match="audit failed"):
        controller.commission()

    assert "bootstrap_periodic_probe" not in host.calls
    assert host.calls.count("sigint_service") == 1


def test_existing_journal_refuses_second_start_without_any_host_effect(tmp_path: Path) -> None:
    first, first_host, _probe, _audit = _controller(tmp_path)
    first.commission()
    second, second_host, _probe, _audit = _controller(tmp_path)

    with pytest.raises(CommissioningError, match="already exists"):
        second.commission()

    assert first_host.calls.count("kickstart_service") == 1
    assert second_host.calls == []


@pytest.mark.parametrize(
    ("host_overrides", "match"),
    [
        ({"commission_observed_monotonic_ms": 61_001}, "commissioning deadline"),
        ({"periodic_offsets_ms": (60_000,)}, "two ordered periodic rows"),
        ({"periodic_offsets_ms": (10_000, 170_000)}, "periodic gap"),
        ({"operability_covered_from_delta_ms": 1}, "operability observation"),
        ({"all_probe_attempts_operational": False}, "operability observation"),
        ({"resource_sources_readable": False}, "operability observation"),
        ({"resource_boundary_delta_ms": -1}, "operability observation"),
        ({"resource_event_count": 1}, "operability observation"),
    ],
)
def test_commissioning_and_full_operability_boundaries_fail_closed(
    tmp_path: Path,
    host_overrides: Mapping[str, object],
    match: str,
) -> None:
    controller, host, _probe, _audit = _controller(
        tmp_path,
        host_overrides=host_overrides,
    )

    with pytest.raises(CommissioningError, match=match):
        controller.commission()

    assert host.calls.count("kickstart_service") == 1
    assert host.calls.count("sigint_service") == 1
    assert host.calls[-2:] == ["bootout_service", "verify_quiescent"]


def test_current_audit_must_finish_by_lifecycle_absolute_deadline(
    tmp_path: Path,
) -> None:
    controller, host, _probe, _audit = _controller(
        tmp_path,
        audit_monotonic_ms=111_001,
    )

    with pytest.raises(CommissioningError, match="current audit deadline"):
        controller.commission()

    assert "bootstrap_periodic_probe" not in host.calls
    assert host.calls.count("sigint_service") == 1


def test_probe_bootstrap_completion_cannot_cross_absolute_deadline(tmp_path: Path) -> None:
    controller, host, _probe, _audit = _controller(
        tmp_path,
        audit_monotonic_ms=111_000,
        host_overrides={"probe_bootstrap_delay_ms": 1},
    )

    with pytest.raises(CommissioningError, match="periodic probe bootstrap deadline"):
        controller.commission()

    assert host.calls.count("bootstrap_periodic_probe") == 1
    assert host.calls.count("sigint_service") == 1


@pytest.mark.parametrize("failure", ["kickstart", "lifecycle"])
def test_startup_without_runtime_records_no_terminal_failure_and_never_signals(
    tmp_path: Path,
    failure: str,
) -> None:
    overrides = {
        "fail_kickstart": failure == "kickstart",
        "fail_lifecycle": failure == "lifecycle",
    }
    controller, host, probe, audit = _controller(tmp_path, host_overrides=overrides)

    with pytest.raises(CommissioningError, match=failure):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING"
    closure = _failure_closure(controller)
    assert closure["status"] == "STARTUP_FAILED_NO_RUNTIME_QUIESCENT"
    assert closure["envelope_identity"] == controller.envelope.envelope_identity
    assert "sigint_service" not in host.calls
    assert "wait_for_terminal" not in host.calls
    assert audit.calls == []
    assert probe.calls == []
    assert host.calls[-2:] == ["bootout_service", "verify_quiescent"]


def test_lifecycle_bound_failure_binds_pid_then_naturally_terminates_and_fully_closes(
    tmp_path: Path,
) -> None:
    controller, host, probe, audit = _controller(
        tmp_path,
        host_overrides={
            "fail_commissioning": True,
            "service_is_running": False,
        },
    )
    audit.terminal_integrity_status = "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY"
    audit.terminal_business_status = "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"
    audit.terminal_business_acceptance = "NOT_ACCEPTED_PROCESS_FAILURE"

    with pytest.raises(CommissioningError, match="commissioning inspection failed after lifecycle"):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "COMMISSION_FAILED_CLEANUP_PENDING"
    assert receipt["runtime_identity"] == RUNTIME
    assert receipt["pid"] == 123
    closure = _failure_closure(controller)
    assert closure["status"] == "COMMISSION_FAILED_TERMINAL_AUDITED_QUIESCENT"
    assert closure["runtime_identity"] == RUNTIME
    assert closure["pid"] == 123
    assert controller.envelope.receipt_path != controller.envelope.failure_closure_receipt_path
    assert host.receipt_existed_at_cleanup_start is True
    assert host.receipt_bytes_at_cleanup_start == controller.envelope.receipt_path.read_bytes()
    assert probe.calls == []
    assert audit.calls == ["complete"]
    assert "sigint_service" not in host.calls
    assert "wait_for_terminal" in host.calls
    assert host.calls[-2:] == ["bootout_service", "verify_quiescent"]
    pid_binding = json.loads(
        (controller.envelope.journal_directory / "RUNTIME_PID_BINDING.json").read_text(
            encoding="utf-8"
        )
    )
    assert pid_binding["pid"] == 123
    assert (controller.envelope.journal_directory / "NATURAL_TERMINAL_CLOSE_INTENT.json").is_file()
    assert (controller.envelope.journal_directory / "FAILURE_CLOSURE_COMPLETE.json").is_file()


def test_lifecycle_bound_failure_with_unknown_pid_cleans_up_but_remains_blocked(
    tmp_path: Path,
) -> None:
    controller, host, probe, _audit = _controller(
        tmp_path,
        host_overrides={
            "fail_commissioning": True,
            "current_pid_available": False,
        },
    )

    with pytest.raises(CommissioningError) as raised:
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "COMMISSION_FAILED_CLEANUP_PENDING"
    assert receipt["runtime_identity"] == RUNTIME
    assert receipt["pid"] is None
    closure = _failure_closure(controller)
    assert closure["status"] == "COMMISSION_FAILED_CLEANUP_BLOCKED"
    assert "runtime PID binding failed" in str(closure["failure_reason"])
    assert host.receipt_existed_at_cleanup_start is True
    assert probe.calls == []
    assert "sigint_service" not in host.calls
    assert host.calls[-2:] == ["bootout_service", "verify_quiescent"]
    assert not (
        controller.envelope.journal_directory / "NATURAL_TERMINAL_CLOSE_INTENT.json"
    ).exists()
    assert not (controller.envelope.journal_directory / "FAILURE_CLOSURE_COMPLETE.json").exists()
    assert not (controller.envelope.journal_directory / "RUNTIME_PID_BINDING.json").exists()
    assert "service label is absent" in str(raised.value)


def test_happy_path_covers_full_gate_partition_and_resource_grace(tmp_path: Path) -> None:
    controller, host, _probe, _audit = _controller(tmp_path)

    receipt = controller.commission()

    assert receipt.gate_start_monotonic_ms == 2_100
    assert receipt.gate_end_monotonic_ms == 182_100
    assert host.observed_gate_start_ms == 2_100
    assert host.observed_gate_end_ms == 182_100
    assert host.observed_resource_boundary_ms == 212_100
    journal = controller.envelope.journal_directory / "HOST_OPERABILITY_GATE_START.json"
    value = json.loads(journal.read_text(encoding="utf-8"))
    assert value["gate_start_monotonic_ms"] == 2_100
    assert value["gate_end_monotonic_ms"] == 182_100
    assert value["resource_audit_boundary_monotonic_ms"] == 212_100


def test_stop_mode_is_start_incapable_exactly_once_and_quiesces_after_terminal(
    tmp_path: Path,
) -> None:
    controller, host, _probe, audit = _controller(tmp_path)
    controller.commission()
    calls_before_stop = tuple(host.calls)

    receipt = controller.stop()

    stop_calls = host.calls[len(calls_before_stop) :]
    assert receipt.status == "STOPPED_TERMINAL_AUDITED_QUIESCENT"
    assert "kickstart_service" not in stop_calls
    assert stop_calls == [
        "bootout_periodic_probe",
        "service_running",
        "sigint_service",
        "wait_for_terminal",
        "bootout_service",
        "verify_quiescent",
    ]
    assert audit.calls[-1] == "complete"

    with pytest.raises(CommissioningError, match="STOP_INTENT"):
        controller.stop()
    assert host.calls[len(calls_before_stop) :] == stop_calls


def test_stop_liveness_query_failure_still_boots_out_probe_and_completes_cleanup(
    tmp_path: Path,
) -> None:
    controller, host, probe, _audit = _controller(
        tmp_path,
        host_overrides={"fail_service_running": True},
    )
    controller.commission()
    calls_before_stop = len(host.calls)
    probe_call_count = len(probe.calls)

    with pytest.raises(CommissioningError, match="service liveness query failed"):
        controller.stop()

    stop_calls = host.calls[calls_before_stop:]
    assert stop_calls[:2] == ["bootout_periodic_probe", "service_running"]
    assert "sigint_service" not in stop_calls
    assert len(probe.calls) == probe_call_count
    assert "bootout_service" in stop_calls
    assert "verify_quiescent" in stop_calls
    assert stop_calls.index("bootout_service") < stop_calls.index("verify_quiescent")
    receipt = json.loads(controller.envelope.stop_receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "TERMINAL_CLOSURE_NOT_ACCEPTED"
    assert "service liveness query failed" in receipt["failure_reason"]


def test_stop_terminal_timeout_blocks_before_audit_or_service_bootout(
    tmp_path: Path,
) -> None:
    controller, host, _probe, audit = _controller(tmp_path)
    controller.commission()
    calls_before_stop = len(host.calls)
    audit_call_count = len(audit.calls)
    host.fail_terminal_wait = True

    with pytest.raises(CommissioningError, match=r"terminal wait failed.*terminal deadline"):
        controller.stop()

    stop_calls = host.calls[calls_before_stop:]
    assert stop_calls == [
        "bootout_periodic_probe",
        "service_running",
        "sigint_service",
        "wait_for_terminal",
    ]
    assert stop_calls.count("sigint_service") == 1
    assert len(audit.calls) == audit_call_count
    assert "bootout_service" not in stop_calls
    assert "verify_quiescent" not in stop_calls
    blocked_paths = sorted(controller.envelope.journal_directory.glob("*_CLOSURE_BLOCKED.json"))
    assert len(blocked_paths) == 1
    blocked = json.loads(blocked_paths[0].read_text(encoding="utf-8"))
    assert str(blocked["intent"]).endswith("_CLOSURE_BLOCKED")
    assert "terminal deadline exceeded" in json.dumps(blocked["errors"])
    receipt = json.loads(controller.envelope.stop_receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "TERMINAL_CLOSURE_NOT_ACCEPTED"
    assert "terminal wait failed" in receipt["failure_reason"]

    calls_after_stop = tuple(host.calls)
    with pytest.raises(CommissioningError, match="STOP_INTENT"):
        controller.stop()
    assert tuple(host.calls) == calls_after_stop


def test_partial_service_bootstrap_writes_failure_receipt_before_cleanup(
    tmp_path: Path,
) -> None:
    controller, host, probe, audit = _controller(
        tmp_path,
        host_overrides={"fail_bootstrap": True},
    )

    with pytest.raises(CommissioningError, match="bootstrap failed after partial mutation"):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING"
    assert receipt["failure_reason"] == "bootstrap failed after partial mutation"
    closure = _failure_closure(controller)
    assert closure["status"] == "STARTUP_FAILED_NO_RUNTIME_QUIESCENT"
    assert host.receipt_existed_at_cleanup_start is True
    assert host.receipt_bytes_at_cleanup_start == controller.envelope.receipt_path.read_bytes()
    assert probe.calls == []
    assert audit.calls == []
    assert host.calls == [
        "preflight",
        "bootstrap_service",
        "bootout_periodic_probe",
        "bootout_service",
        "verify_quiescent",
    ]


@pytest.mark.parametrize("runtime_bound", [False, True])
def test_final_failure_receipt_precedes_its_closure_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_bound: bool,
) -> None:
    controller, _host, _probe, _audit = _controller(
        tmp_path,
        host_overrides=(
            {"fail_commissioning": True, "service_is_running": False}
            if runtime_bound
            else {"fail_bootstrap": True}
        ),
    )
    original_journal = controller._journal
    observed_closure_journals: list[str] = []

    def journal(intent: str, facts: Mapping[str, object]) -> None:
        if intent in {"FAILURE_CLOSURE_COMPLETE", "NO_RUNTIME_CLOSURE_COMPLETE"}:
            assert controller.envelope.failure_closure_receipt_path.is_file()
            observed_closure_journals.append(intent)
        return original_journal(intent, facts)

    monkeypatch.setattr(controller, "_journal", journal)

    with pytest.raises(CommissioningError):
        controller.commission()

    assert observed_closure_journals == [
        "FAILURE_CLOSURE_COMPLETE" if runtime_bound else "NO_RUNTIME_CLOSURE_COMPLETE"
    ]


def test_no_runtime_failure_records_blocked_final_closure_after_all_cleanup_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, host, _probe, _audit = _controller(
        tmp_path,
        host_overrides={"fail_bootstrap": True},
    )

    def fail_service_bootout() -> None:
        host.calls.append("bootout_service")
        raise CommissioningError("service inventory unavailable")

    def fail_quiescence(*, expected_pid: int | None) -> None:
        assert expected_pid is None
        host.calls.append("verify_quiescent")
        raise CommissioningError("listener inventory malformed")

    monkeypatch.setattr(host, "bootout_service", fail_service_bootout)
    monkeypatch.setattr(host, "verify_quiescent", fail_quiescence)

    with pytest.raises(CommissioningError, match="service inventory unavailable"):
        controller.commission()

    primary = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    closure = _failure_closure(controller)
    assert primary["status"] == "STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING"
    assert closure["status"] == "STARTUP_FAILED_NO_RUNTIME_CLEANUP_BLOCKED"
    assert "service bootout: service inventory unavailable" in str(closure["failure_reason"])
    assert "quiescence: listener inventory malformed" in str(closure["failure_reason"])
    assert host.receipt_bytes_at_cleanup_start == controller.envelope.receipt_path.read_bytes()
    assert host.calls.count("bootstrap_service") == 1
    assert "kickstart_service" not in host.calls
    assert "sigint_service" not in host.calls


def test_existing_failure_closure_receipt_is_never_rewritten(
    tmp_path: Path,
) -> None:
    controller, _host, _probe, _audit = _controller(
        tmp_path,
        host_overrides={"fail_bootstrap": True},
    )
    controller.envelope.failure_closure_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"sealed":"original"}\n'
    controller.envelope.failure_closure_receipt_path.write_bytes(original)

    with pytest.raises(CommissioningError, match="output already exists"):
        controller.commission()

    assert controller.envelope.failure_closure_receipt_path.read_bytes() == original


def test_invalid_terminal_audit_fails_failure_closure_but_preserves_receipt(
    tmp_path: Path,
) -> None:
    controller, host, _probe, audit = _controller(
        tmp_path,
        event=_event(contract_field="contract_digest"),
    )
    audit.invalid_terminal = True

    with pytest.raises(
        CommissioningError,
        match=r"failure closure failed: terminal audit (failed: )?terminal audit mismatch",
    ):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "COMMISSION_FAILED_CLEANUP_PENDING"
    assert "lifecycle" in receipt["failure_reason"]
    closure = _failure_closure(controller)
    assert closure["status"] == "COMMISSION_FAILED_CLEANUP_BLOCKED"
    assert "terminal audit" in str(closure["failure_reason"])
    assert host.receipt_existed_at_cleanup_start is True
    assert host.calls.count("sigint_service") == 1
    assert host.calls.count("bootout_service") == 1
    assert host.calls[-1] == "verify_quiescent"


def test_commission_failure_terminal_timeout_blocks_before_audit_or_service_bootout(
    tmp_path: Path,
) -> None:
    controller, host, probe, audit = _controller(
        tmp_path,
        host_overrides={
            "fail_commissioning": True,
            "fail_terminal_wait": True,
        },
    )

    with pytest.raises(CommissioningError, match=r"terminal wait failed.*terminal deadline"):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "COMMISSION_FAILED_CLEANUP_PENDING"
    assert receipt["runtime_identity"] == RUNTIME
    assert receipt["pid"] == 123
    closure = _failure_closure(controller)
    assert closure["status"] == "COMMISSION_FAILED_CLEANUP_BLOCKED"
    assert "terminal wait" in str(closure["failure_reason"])
    assert host.receipt_existed_at_cleanup_start is True
    assert probe.calls == []
    assert audit.calls == []
    assert host.calls.count("sigint_service") == 1
    assert host.calls.count("kickstart_service") == 1
    assert "bootout_service" not in host.calls
    assert "verify_quiescent" not in host.calls
    assert not (controller.envelope.journal_directory / "FAILURE_CLOSURE_COMPLETE.json").exists()
    blocked = json.loads(
        (controller.envelope.journal_directory / "FAILURE_CLOSURE_BLOCKED.json").read_text(
            encoding="utf-8"
        )
    )
    assert "terminal deadline exceeded" in json.dumps(blocked["errors"])


def test_terminal_validator_rejects_clean_integrity_with_process_failure_business_token(
    tmp_path: Path,
) -> None:
    controller, _host, _probe, audit = _controller(tmp_path)
    terminal = dict(
        audit.run(
            controller.envelope.terminal_audit_argv,
            runtime_identity=RUNTIME,
            deadline_ms=2_000,
        )
    )
    terminal["reader_integrity_status"] = "PASS_COMPLETE_CLEAN_STOP"
    terminal["terminal_business_status"] = "CLEAN_STOP_COMPLETE"
    terminal["business_acceptance"] = "NOT_ACCEPTED_PROCESS_FAILURE"
    terminal["twenty_four_hour_continuous_public_service_sample"] = "NOT_MET"

    with pytest.raises(CommissioningError, match="terminal audit mismatch"):
        controller._validate_terminal_audit(
            terminal,
            runtime_identity=RUNTIME,
            explicit_stop_probe_required=False,
        )


@pytest.mark.parametrize(
    ("recorded_monotonic_ms", "observed_monotonic_ms"),
    [
        (899, 1_000),
        (1_001, 1_000),
        (1_000, 30_901),
    ],
)
def test_lifecycle_must_be_causally_after_kickstart_and_within_one_deadline(
    tmp_path: Path,
    recorded_monotonic_ms: int,
    observed_monotonic_ms: int,
) -> None:
    controller, host, probe, audit = _controller(
        tmp_path,
        event=_event(recorded_monotonic_ms=recorded_monotonic_ms),
        host_overrides={"lifecycle_observed_monotonic_ms": observed_monotonic_ms},
    )

    with pytest.raises(CommissioningError, match="lifecycle deadline exceeded"):
        controller.commission()

    receipt = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING"
    closure = _failure_closure(controller)
    assert closure["status"] == "STARTUP_FAILED_NO_RUNTIME_QUIESCENT"
    assert host.calls.count("kickstart_service") == 1
    assert "sigint_service" not in host.calls
    assert probe.calls == []
    assert audit.calls == []


def test_success_receipt_persists_recomputable_operability_facts(tmp_path: Path) -> None:
    controller, _host, _probe, _audit = _controller(tmp_path)

    receipt = controller.commission()

    assert receipt.operability == _operability_facts()
    persisted = json.loads(controller.envelope.receipt_path.read_text(encoding="utf-8"))
    assert persisted["operability"] == receipt.operability


def test_natural_terminal_stop_does_not_probe_or_signal(tmp_path: Path) -> None:
    controller, host, probe, audit = _controller(tmp_path)
    controller.commission()
    probe_call_count = len(probe.calls)
    calls_before_stop = len(host.calls)
    host.service_is_running = False
    audit.terminal_integrity_status = "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY"
    audit.terminal_business_status = "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"
    audit.terminal_business_acceptance = "NOT_ACCEPTED_PROCESS_FAILURE"

    receipt = controller.stop()

    assert receipt.status == "NATURAL_TERMINAL_AUDITED_QUIESCENT"
    assert len(probe.calls) == probe_call_count
    stop_calls = host.calls[calls_before_stop:]
    assert "sigint_service" not in stop_calls
    assert stop_calls == [
        "bootout_periodic_probe",
        "service_running",
        "wait_for_terminal",
        "bootout_service",
        "verify_quiescent",
    ]


def test_live_explicit_stop_accepts_process_failure_as_a_complete_not_met_closure(
    tmp_path: Path,
) -> None:
    controller, host, probe, audit = _controller(tmp_path)
    controller.commission()
    probe_call_count = len(probe.calls)
    calls_before_stop = len(host.calls)
    audit.terminal_integrity_status = "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY"
    audit.terminal_business_status = "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"
    audit.terminal_business_acceptance = "NOT_ACCEPTED_PROCESS_FAILURE"

    receipt = controller.stop()

    assert receipt.status == "STOPPED_TERMINAL_AUDITED_QUIESCENT"
    assert receipt.failure_reason is None
    assert probe.calls[probe_call_count:][0][0] == "final-online"
    assert audit.calls[-1] == "complete"
    stop_calls = host.calls[calls_before_stop:]
    assert stop_calls == [
        "bootout_periodic_probe",
        "service_running",
        "sigint_service",
        "wait_for_terminal",
        "bootout_service",
        "verify_quiescent",
    ]


def test_subprocess_probe_requires_an_exact_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    envelope.probe_ledger_path.parent.mkdir(parents=True)
    first = {"sequence": 1, "runtime_identity": RUNTIME, "preserved": True}
    envelope.probe_ledger_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    appended = {"sequence": 2, "runtime_identity": RUNTIME}

    def append_once(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        with envelope.probe_ledger_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(appended) + "\n")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", append_once)
    result = SubprocessProbe(envelope, FakeClock()).collect(
        envelope.manual_probe_argv,
        runtime_identity=RUNTIME,
        expected_sequence=2,
        deadline_ms=2_000,
    )

    assert result == appended
    rows = [json.loads(line) for line in envelope.probe_ledger_path.read_text().splitlines()]
    assert rows == [first, appended]


def test_subprocess_probe_rejects_rewrite_of_prior_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    envelope.probe_ledger_path.parent.mkdir(parents=True)
    first = {"sequence": 1, "runtime_identity": RUNTIME, "preserved": True}
    envelope.probe_ledger_path.write_text(json.dumps(first) + "\n", encoding="utf-8")

    def rewrite_then_append(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        changed = {**first, "preserved": False}
        appended = {"sequence": 2, "runtime_identity": RUNTIME}
        envelope.probe_ledger_path.write_text(
            json.dumps(changed) + "\n" + json.dumps(appended) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", rewrite_then_append)

    with pytest.raises(CommissioningError, match="sequence/count mismatch"):
        SubprocessProbe(envelope, FakeClock()).collect(
            envelope.manual_probe_argv,
            runtime_identity=RUNTIME,
            expected_sequence=2,
            deadline_ms=2_000,
        )


def test_subprocess_audit_rejects_stale_output_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    output = Path(envelope.current_audit_argv[-1])
    output.parent.mkdir(parents=True)
    output.write_text("{}\n", encoding="utf-8")

    def must_not_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("stale audit output must be rejected before subprocess execution")

    monkeypatch.setattr(subprocess, "run", must_not_run)

    with pytest.raises(CommissioningError, match="audit output already exists"):
        SubprocessAudit(envelope, FakeClock()).run(
            envelope.current_audit_argv,
            runtime_identity=RUNTIME,
            deadline_ms=2_000,
        )


def test_cpu_time_parser_accepts_fractional_seconds() -> None:
    assert commissioning._parse_cpu_time_ms("0:00.01") == 10
    assert commissioning._parse_cpu_time_ms("1-02:03:04.005") == 93_784_005


def test_stop_cli_constructs_macos_host_without_unified_log_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    stop_calls: list[CommissioningController] = []

    def load_envelope(_path: Path, *, expected_identity: str) -> CommissioningEnvelope:
        assert expected_identity == envelope.envelope_identity
        return envelope

    def stop(controller: CommissioningController) -> commissioning.CommissioningReceipt:
        stop_calls.append(controller)
        return commissioning.CommissioningReceipt(
            status="STOPPED_TERMINAL_AUDITED_QUIESCENT",
            runtime_identity=RUNTIME,
            pid=123,
            run_directory=str(envelope.state_root / "runs" / RUNTIME.removeprefix("sha256:")),
            gate_start_monotonic_ms=2_100,
            gate_end_monotonic_ms=182_100,
            envelope_identity=envelope.envelope_identity,
        )

    def reject_unified_log(
        argv: Sequence[str],
        *,
        timeout: float = 10,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del timeout, cwd
        if argv and argv[0] == "/usr/bin/log":
            raise AssertionError("stop must not run unified-log preflight")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(commissioning, "_load_envelope", load_envelope)
    monkeypatch.setattr(CommissioningController, "stop", stop)
    monkeypatch.setattr(MacOSHost, "_run", staticmethod(reject_unified_log))
    monkeypatch.setattr(time, "time", lambda: 1_754_006_400.0)

    assert (
        commissioning.main(
            [
                "--envelope",
                str(tmp_path / "envelope.json"),
                "--expected-envelope-identity",
                envelope.envelope_identity,
                "--mode",
                "stop",
            ]
        )
        == 0
    )
    assert len(stop_calls) == 1
    assert isinstance(stop_calls[0].host, MacOSHost)


@pytest.mark.parametrize(
    ("stderr", "expected_absent"),
    [
        ("Could not find service com.example", True),
        ("Input/output error", False),
    ],
)
def test_launchd_inventory_distinguishes_known_absence_from_unknown_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    expected_absent: bool,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())

    def failed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 3, "", stderr)

    monkeypatch.setattr(host, "_run", failed)
    if expected_absent:
        assert host._launchd(envelope.service_target) is None
    else:
        with pytest.raises(CommissioningError, match="launchd inventory failed"):
            host._launchd(envelope.service_target)


def test_launchd_inventory_rejects_success_without_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    monkeypatch.setattr(
        host,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    with pytest.raises(CommissioningError, match="launchd inventory is malformed"):
        host._launchd(envelope.service_target)


@pytest.mark.parametrize(
    ("method_name", "target_name"),
    [
        ("bootout_periodic_probe", "probe_target"),
        ("bootout_service", "service_target"),
    ],
)
def test_bootout_waits_for_asynchronous_launchd_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    target_name: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    states = iter(("loaded", "loaded", None))
    effects: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        host,
        "_effect",
        lambda argv, _label, **_kwargs: effects.append(tuple(argv)),
    )
    monkeypatch.setattr(host, "_launchd", lambda _target: next(states))

    getattr(host, method_name)()

    assert effects
    assert clock.now == 1_100
    assert getattr(envelope, target_name) in effects[0]


@pytest.mark.parametrize("method_name", ["bootout_periodic_probe", "bootout_service"])
def test_bootout_fails_closed_when_launchd_absence_does_not_converge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    monkeypatch.setattr(host, "_effect", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(host, "_launchd", lambda _target: "still loaded")

    with pytest.raises(CommissioningError, match="did not unload before deadline"):
        getattr(host, method_name)()

    assert clock.now == 30_900


@pytest.mark.parametrize("method_name", ["bootout_periodic_probe", "bootout_service"])
def test_bootout_rejects_absence_observed_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    monkeypatch.setattr(host, "_effect", lambda *_args, **_kwargs: None)

    def late_absence(_target: str) -> None:
        clock.now = 30_901
        return None

    monkeypatch.setattr(host, "_launchd", late_absence)

    with pytest.raises(CommissioningError, match="did not unload before deadline"):
        getattr(host, method_name)()


def test_verify_quiescent_requires_all_predicates_absent_in_the_same_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    listener_states = iter((((123, "127.0.0.1:8765"),), (), ()))
    process_states = iter(((), (123,), ()))
    pid_states = iter(((0, "123\n"), (0, "123\n"), (1, "")))

    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(host, "_listener_inventory", lambda: next(listener_states))
    monkeypatch.setattr(host, "_matching_process_pids", lambda: next(process_states))

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert tuple(argv[:3]) == ("/bin/ps", "-p", "123")
        returncode, output = next(pid_states)
        return subprocess.CompletedProcess(argv, returncode, output, "")

    monkeypatch.setattr(host, "_run", run)

    host.verify_quiescent(expected_pid=123)

    assert clock.now == 1_100


def test_verify_quiescent_waits_through_transient_service_and_probe_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    label_states = iter(("service loaded", None, None, "probe loaded", None, None))
    observed_targets: list[str] = []

    def launchd(target: str) -> str | None:
        observed_targets.append(target)
        return next(label_states)

    monkeypatch.setattr(host, "_launchd", launchd)
    monkeypatch.setattr(host, "_listener_inventory", lambda: ())
    monkeypatch.setattr(host, "_matching_process_pids", lambda: ())

    host.verify_quiescent(expected_pid=None)

    assert observed_targets == [
        envelope.service_target,
        envelope.probe_target,
        envelope.service_target,
        envelope.probe_target,
        envelope.service_target,
        envelope.probe_target,
    ]
    assert clock.now == 1_100


def test_verify_quiescent_fails_closed_at_one_bounded_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(
        host,
        "_listener_inventory",
        lambda: ((123, "127.0.0.1:8765"),),
    )
    monkeypatch.setattr(host, "_matching_process_pids", lambda: ())
    monkeypatch.setattr(
        host,
        "_run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", ""),
    )

    with pytest.raises(CommissioningError, match="quiescence did not converge"):
        host.verify_quiescent(expected_pid=123)

    assert clock.now == 30_900


def test_verify_quiescent_rejects_all_absent_observed_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    clock = FakeClock()
    host = MacOSHost(envelope, clock)
    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(host, "_listener_inventory", lambda: ())

    def late_process_absence() -> tuple[int, ...]:
        clock.now = 30_901
        return ()

    monkeypatch.setattr(host, "_matching_process_pids", late_process_absence)
    monkeypatch.setattr(
        host,
        "_run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", ""),
    )

    with pytest.raises(CommissioningError, match="quiescence did not converge"):
        host.verify_quiescent(expected_pid=123)


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (0, ""),
        (0, "456\n"),
        (1, "123\n"),
        (2, ""),
    ],
)
def test_verify_quiescent_rejects_malformed_or_substituted_original_pid_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(host, "_listener_inventory", lambda: ())
    monkeypatch.setattr(host, "_matching_process_pids", lambda: ())
    monkeypatch.setattr(
        host,
        "_run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, returncode, stdout, ""),
    )

    with pytest.raises(CommissioningError, match="original PID absence query"):
        host.verify_quiescent(expected_pid=123)


def test_listener_inventory_binds_each_listener_to_its_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())

    def listener_result(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            "p123\nf17\nn127.0.0.1:8765\np456\nf8\nn*:8765\n",
            "",
        )

    monkeypatch.setattr(host, "_run", listener_result)
    assert host._listener_inventory() == (
        (123, "127.0.0.1:8765"),
        (456, "*:8765"),
    )


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (0, ""),
        (1, "p123\n"),
        (0, "n127.0.0.1:8765\n"),
        (0, "f17\nn127.0.0.1:8765\n"),
        (0, "pnope\nn127.0.0.1:8765\n"),
        (0, "xunexpected\n"),
    ],
)
def test_listener_inventory_rejects_malformed_or_indeterminate_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    monkeypatch.setattr(
        host,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode, stdout, ""),
    )

    with pytest.raises(CommissioningError, match="listener inventory"):
        host._listener_inventory()


@pytest.mark.parametrize("stdout", ["not-a-pid command\n", "123\n", "garbage\n"])
def test_matching_process_inventory_rejects_malformed_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    monkeypatch.setattr(
        host,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout, ""),
    )

    with pytest.raises(CommissioningError, match="service process inventory is malformed"):
        host._matching_process_pids()


def test_preflight_rejects_an_existing_r4_service_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(host, "_listener_inventory", lambda: ())
    monkeypatch.setattr(host, "_matching_process_pids", lambda: (123,))

    with pytest.raises(CommissioningError, match="service process already exists"):
        host.preflight()


def test_preflight_runs_every_git_query_in_bound_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
    host = MacOSHost(envelope, FakeClock())
    calls: list[tuple[tuple[str, ...], Path | None]] = []

    def run(
        argv: Sequence[str],
        *,
        timeout: float = 10,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        command = tuple(argv)
        calls.append((command, cwd))
        if command == ("git", "rev-parse", "HEAD^{commit}"):
            return subprocess.CompletedProcess(command, 0, CODE + "\n", "")
        if command == ("git", "rev-parse", "HEAD^{tree}"):
            return subprocess.CompletedProcess(command, 0, "f" * 40 + "\n", "")
        if command == ("git", "rev-parse", "refs/remotes/origin/main^{commit}"):
            return subprocess.CompletedProcess(command, 0, CODE + "\n", "")
        if command == ("git", "status", "--porcelain"):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ("git", "symbolic-ref", "-q", "HEAD"):
            return subprocess.CompletedProcess(command, 1, "", "")
        raise AssertionError(f"unexpected command before artifact validation: {command}")

    monkeypatch.setattr(host, "_launchd", lambda _target: None)
    monkeypatch.setattr(host, "_listener_inventory", lambda: ())
    monkeypatch.setattr(host, "_matching_process_pids", lambda: ())
    monkeypatch.setattr(host, "_run", run)

    def stop_after_git(_path: Path) -> str:
        raise CommissioningError("artifact validation sentinel")

    monkeypatch.setattr(commissioning, "_file_identity", stop_after_git)

    with pytest.raises(CommissioningError, match="artifact validation sentinel"):
        host.preflight()

    git_calls = [(argv, cwd) for argv, cwd in calls if argv and argv[0] == "git"]
    assert len(git_calls) == 5
    assert all(cwd == envelope.repository for _argv, cwd in git_calls)


def test_wrapper_context_binds_envelope_identity_to_kickstart_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, envelope_path, run_directory, event = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )

    context = commissioning._bound_wrapper_context(envelope_path)

    assert context[0] == envelope
    assert context[1] == run_directory
    assert context[2] == event
    assert context[3] == RUNTIME

    kickstart_path = envelope.journal_directory / "KICKSTART_INTENT.json"
    kickstart = json.loads(kickstart_path.read_text(encoding="utf-8"))
    kickstart["envelope_identity"] = BOUND_DIGEST
    kickstart_path.write_text(json.dumps(kickstart) + "\n", encoding="utf-8")

    with pytest.raises(CommissioningError, match="wrapper envelope/journal binding mismatch"):
        commissioning._bound_wrapper_context(envelope_path)


def test_production_probe_locks_and_exactly_appends_full_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, envelope_path, _run_directory, _event_value = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    ordering: list[str] = []
    real_append = commissioning._append_probe_row

    monkeypatch.setattr(MacOSHost, "_pid_runs", lambda _self: (123, 1))
    monkeypatch.setattr(MacOSHost, "_matching_process_pids", lambda _self: (123,))
    monkeypatch.setattr(
        MacOSHost,
        "_process",
        lambda _self, _pid: (
            envelope.expected_service_argv,
            envelope.expected_service_cwd,
            4_096,
            10,
        ),
    )
    monkeypatch.setattr(
        MacOSHost,
        "_listener_inventory",
        lambda _self: ((123, "127.0.0.1:8765"),),
    )

    def http(
        _self: MacOSHost,
        path: str,
    ) -> tuple[dict[str, object], int]:
        if path == "/healthz":
            return {
                "status": 200,
                "schema_version": 2,
                "health": True,
                "runtime_identity": RUNTIME,
            }, 1
        if path == "/readyz":
            return {
                "status": 503,
                "schema_version": 2,
                "ready": False,
                "runtime_identity": RUNTIME,
            }, 1
        assert path == "/api/workbench/current"
        return _workbench_document(), 1

    monkeypatch.setattr(MacOSHost, "_http", http)
    monkeypatch.setattr(
        MacOSHost,
        "inspect_resource_events",
        lambda _self, **_kwargs: commissioning.ResourceEventObservation(
            sources_readable=True,
            exact_pid_event_count=0,
            query_start_wall_utc="2026-08-01T00:00:00+00:00",
            query_end_wall_utc="2026-08-01T00:00:01+00:00",
            diagnostic_report_count_examined=0,
            unified_log_row_count_examined=0,
        ),
    )

    def lock(_descriptor: int, operation: int) -> None:
        assert operation == fcntl.LOCK_EX
        ordering.append("lock")

    def append(path: Path, row: Mapping[str, object]) -> None:
        ordering.append("append")
        real_append(path, row)

    monkeypatch.setattr(fcntl, "flock", lock)
    monkeypatch.setattr(commissioning, "_append_probe_row", append)

    assert (
        commissioning.production_probe_main(
            ["--mode", "periodic"],
            envelope_path=envelope_path,
        )
        == 0
    )

    rows = commissioning._read_ledger(envelope.probe_ledger_path)
    assert ordering == ["lock", "append"]
    assert len(rows) == 1
    inventory = rows[0]["inventory"]
    assert isinstance(inventory, Mapping)
    assert inventory["run_directories"] == [RUNTIME.removeprefix("sha256:")]
    commissioning._validate_probe_row(
        envelope,
        rows[0],
        runtime_identity=RUNTIME,
        pid=123,
        expected_sequence=1,
        expected_mode="periodic",
    )


def test_production_probe_failure_writes_marker_and_stderr_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    envelope, envelope_path, _run_directory, _event_value = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )

    def fail_pid(_self: MacOSHost) -> tuple[int, int]:
        raise CommissioningError("probe pid unavailable")

    monkeypatch.setattr(MacOSHost, "_pid_runs", fail_pid)
    monkeypatch.setattr(time, "monotonic_ns", lambda: 123_000_000)

    assert (
        commissioning.production_probe_main(
            ["--mode", "periodic"],
            envelope_path=envelope_path,
        )
        == 1
    )

    markers = list((envelope.deployment_root / "probe/failures").glob("*.json"))
    assert len(markers) == 1
    marker = json.loads(markers[0].read_text(encoding="utf-8"))
    assert set(marker) == {
        "schema_version",
        "record_kind",
        "mode",
        "wall_time_utc",
        "monotonic_ms",
        "error_type",
        "error",
        "operational_success",
    }
    assert marker["record_kind"] == "UNLEDGERED_EXPLICIT_FAILED_PROBE_ROW"
    assert marker["monotonic_ms"] == 123
    assert marker["error"] == "probe pid unavailable"
    assert marker["operational_success"] is False
    assert not envelope.probe_ledger_path.exists()
    stderr = capsys.readouterr().err
    assert stderr.startswith("UNLEDGERED_EXPLICIT_FAILED_PROBE_ROW ")
    assert '"marker_write_status":"PASS"' in stderr


def test_production_audit_current_requires_exact_initial_row_and_output_is_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, envelope_path, _run_directory, _event_value = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.write_text('{"pid":123}\n', encoding="utf-8")
    _write_probe_ledger(
        envelope,
        [_probe_row(envelope, sequence=1, mode="periodic", monotonic_ms=2_000)],
    )
    output = Path(envelope.current_audit_argv[-1])

    assert (
        commissioning.production_audit_main(
            ["--mode", "current", "--output", str(output)],
            envelope_path=envelope_path,
        )
        == 0
    )
    first_bytes = output.read_bytes()
    report = json.loads(first_bytes)
    assert report["reader_integrity_status"] == "PASS_CURRENT_INCOMPLETE"
    assert report["terminal_business_status"] == "LIVE_INCOMPLETE_NO_TERMINAL"
    assert report["business_acceptance"] == "PENDING_LIVE"
    assert report["twenty_four_hour_continuous_public_service_sample"] == "PENDING"
    assert report["probe_evaluation"]["row_count"] == 1
    assert report["probe_evaluation"]["all_rows_contract_valid"] is True

    assert (
        commissioning.production_audit_main(
            ["--mode", "current", "--output", str(output)],
            envelope_path=envelope_path,
        )
        == 1
    )
    assert output.read_bytes() == first_bytes


def test_production_audit_recomputes_operability_gate_for_three_current_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, envelope_path, _run_directory, _event_value = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.write_text('{"pid":123}\n', encoding="utf-8")
    _write_probe_ledger(
        envelope,
        [
            _probe_row(envelope, sequence=1, mode="periodic", monotonic_ms=2_000),
            _probe_row(envelope, sequence=2, mode="periodic", monotonic_ms=62_100),
            _probe_row(envelope, sequence=3, mode="periodic", monotonic_ms=122_100),
        ],
    )
    result_path = envelope.journal_directory / "HOST_OPERABILITY_GATE_RESULT.json"
    start_path = envelope.journal_directory / "HOST_OPERABILITY_GATE_START.json"
    start_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "intent": "HOST_OPERABILITY_GATE_START",
                "envelope_identity": envelope.envelope_identity,
                "runtime_identity": RUNTIME,
                "gate_start_monotonic_ms": 2_100,
                "gate_end_monotonic_ms": 182_100,
                "resource_audit_boundary_monotonic_ms": 212_100,
                "resource_query_end_wall_utc": "2026-08-01T00:04:00.000000+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "intent": "HOST_OPERABILITY_GATE_RESULT",
        "envelope_identity": envelope.envelope_identity,
        "runtime_identity": RUNTIME,
        "operability": _operability_facts(),
    }
    result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    valid_output = Path(envelope.operability_audit_argv[-1])

    assert (
        commissioning.production_audit_main(
            ["--mode", "current", "--output", str(valid_output)],
            envelope_path=envelope_path,
        )
        == 0
    )
    valid_report = json.loads(valid_output.read_text(encoding="utf-8"))
    assert valid_report["probe_evaluation"]["row_count"] == 3
    assert valid_report["operability_evaluation"]["valid"] is True

    tampered = json.loads(json.dumps(result))
    tampered["operability"]["partition_gap_ms"] = [1, 1, 1]
    result_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    invalid_evaluation = commissioning._operability_evaluation(
        envelope,
        runtime_identity=RUNTIME,
        pid=123,
    )
    assert invalid_evaluation["valid"] is False


@pytest.mark.parametrize(
    (
        "terminal_disposition",
        "reader_integrity",
        "terminal_business",
        "business_acceptance",
    ),
    [
        (
            "CLEAN_STOP",
            "PASS_COMPLETE_CLEAN_STOP",
            "CLEAN_STOP_COMPLETE",
            "OPERATIONAL_24H_GATE_NOT_MET",
        ),
        (
            "PROCESS_FAILURE",
            "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY",
            "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED",
            "NOT_ACCEPTED_PROCESS_FAILURE",
        ),
    ],
)
def test_production_audit_complete_emits_exact_terminal_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_disposition: str,
    reader_integrity: str,
    terminal_business: str,
    business_acceptance: str,
) -> None:
    envelope, envelope_path, _run_directory, event = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.write_text('{"pid":123}\n', encoding="utf-8")
    clean_stop = terminal_disposition == "CLEAN_STOP"
    rows = [
        _probe_row(envelope, sequence=1, mode="periodic", monotonic_ms=2_000),
        _probe_row(envelope, sequence=2, mode="periodic", monotonic_ms=62_000),
        _probe_row(
            envelope,
            sequence=3,
            mode="final-online" if clean_stop else "periodic",
            monotonic_ms=122_000,
        ),
    ]
    _write_probe_ledger(envelope, rows)
    terminal = {
        "terminal_disposition": terminal_disposition,
        "terminal_fact_boundary": {"received_monotonic_ms": 11_000},
    }

    def complete_reader(
        _run_directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_bindings: object,
    ) -> PersistentServiceEvidence:
        del bindings, downstream_bindings
        return PersistentServiceEvidence((event,), terminal)

    monkeypatch.setattr(
        commissioning,
        "read_complete_persistent_service_evidence",
        complete_reader,
    )
    output = Path(envelope.terminal_audit_argv[-1])

    assert (
        commissioning.production_audit_main(
            ["--mode", "complete", "--output", str(output)],
            envelope_path=envelope_path,
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["reader_integrity_status"] == reader_integrity
    assert report["terminal_business_status"] == terminal_business
    assert report["business_acceptance"] == business_acceptance
    assert report["twenty_four_hour_continuous_public_service_sample"] == "NOT_MET"
    assert report["covered_duration_ms"] == 10_000


def test_process_failure_after_live_explicit_stop_keeps_final_online_row_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, envelope_path, _run_directory, event = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.write_text('{"pid":123}\n', encoding="utf-8")
    _write_stop_intent(envelope)
    _write_probe_ledger(
        envelope,
        [
            _probe_row(envelope, sequence=1, mode="periodic", monotonic_ms=2_000),
            _probe_row(envelope, sequence=2, mode="periodic", monotonic_ms=62_000),
            _probe_row(envelope, sequence=3, mode="final-online", monotonic_ms=122_000),
        ],
    )

    def complete_reader(
        _run_directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_bindings: object,
    ) -> PersistentServiceEvidence:
        del bindings, downstream_bindings
        return PersistentServiceEvidence(
            (event,),
            {
                "terminal_disposition": "PROCESS_FAILURE",
                "terminal_fact_boundary": {"received_monotonic_ms": 11_000},
            },
        )

    monkeypatch.setattr(
        commissioning,
        "read_complete_persistent_service_evidence",
        complete_reader,
    )
    output = Path(envelope.terminal_audit_argv[-1])

    assert (
        commissioning.production_audit_main(
            ["--mode", "complete", "--output", str(output)],
            envelope_path=envelope_path,
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["reader_integrity_status"] == ("PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY")
    assert report["business_acceptance"] == "NOT_ACCEPTED_PROCESS_FAILURE"
    assert report["twenty_four_hour_continuous_public_service_sample"] == "NOT_MET"
    assert report["probe_evaluation"]["all_rows_contract_valid"] is True
    assert report["probe_evaluation"]["mode_sequence_valid"] is True


@pytest.mark.parametrize(
    ("later_probe_times", "monotonic_valid", "maximum_gap_ms"),
    [
        ((212_100, 302_100, 252_100), False, 90_000),
        ((212_101,), True, 90_001),
    ],
    ids=("monotonic-regression", "gap-over-90-seconds"),
)
def test_twenty_four_hour_met_rejects_probe_time_regression_or_gap_over_90_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    later_probe_times: tuple[int, ...],
    monotonic_valid: bool,
    maximum_gap_ms: int,
) -> None:
    envelope, envelope_path, _run_directory, event = _materialize_wrapper_context(
        tmp_path,
        monkeypatch,
    )
    envelope.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    envelope.receipt_path.write_text('{"pid":123}\n', encoding="utf-8")
    _write_stop_intent(envelope)
    _write_valid_operability_journals(envelope)
    probe_times = (2_000, 62_100, 122_100, *later_probe_times)
    _write_probe_ledger(
        envelope,
        [
            _probe_row(
                envelope,
                sequence=sequence,
                mode="final-online" if sequence == len(probe_times) else "periodic",
                monotonic_ms=monotonic_ms,
            )
            for sequence, monotonic_ms in enumerate(probe_times, start=1)
        ],
    )

    def complete_reader(
        _run_directory: Path,
        *,
        bindings: PersistentServiceBindings,
        downstream_bindings: object,
    ) -> PersistentServiceEvidence:
        del bindings, downstream_bindings
        return PersistentServiceEvidence(
            (event,),
            {
                "terminal_disposition": "CLEAN_STOP",
                "terminal_fact_boundary": {"received_monotonic_ms": 86_401_000},
            },
        )

    monkeypatch.setattr(
        commissioning,
        "read_complete_persistent_service_evidence",
        complete_reader,
    )
    output = Path(envelope.terminal_audit_argv[-1])

    assert (
        commissioning.production_audit_main(
            ["--mode", "complete", "--output", str(output)],
            envelope_path=envelope_path,
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["covered_duration_ms"] == 86_400_000
    assert report["operability_evaluation"]["valid"] is True
    assert report["probe_evaluation"]["monotonic_valid"] is monotonic_valid
    assert report["probe_evaluation"]["max_probe_gap_ms"] == maximum_gap_ms
    assert report["twenty_four_hour_continuous_public_service_sample"] == "NOT_MET"
    assert report["business_acceptance"] == "OPERATIONAL_24H_GATE_NOT_MET"


def test_unified_resource_events_match_exact_pid_in_message_not_emitter_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic_directory = tmp_path / "DiagnosticReports"
    diagnostic_directory.mkdir()
    mapping = _envelope_mapping(tmp_path)
    mapping["diagnostic_report_directories"] = [str(diagnostic_directory.resolve())]
    mapping["diagnostic_report_baseline"] = []
    envelope = CommissioningEnvelope.from_mapping(mapping, allow_test_boundary=True)
    host = MacOSHost(envelope, FakeClock())
    timestamp = datetime.fromtimestamp(1_754_006_400.5, tz=UTC).strftime("%Y-%m-%d %H:%M:%S.%f%z")
    unified_rows = [
        {
            "timestamp": timestamp,
            "processID": 123,
            "eventMessage": "cpu resource event for process 999",
        },
        {
            "timestamp": timestamp,
            "processID": 999,
            "eventMessage": "cpu resource event for process 123",
        },
        {
            "timestamp": timestamp,
            "processID": 123,
            "eventMessage": "cpu resource event for process 1234",
        },
    ]

    def log_show(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(unified_rows), "")

    monkeypatch.setattr(host, "_run", log_show)

    observation = host.inspect_resource_events(
        pid=123,
        query_start_wall=1_754_006_400,
        query_end_wall=1_754_006_401,
    )

    assert observation.sources_readable is True
    assert observation.exact_pid_event_count == 1
    assert observation.diagnostic_report_count_examined == 0
    assert observation.unified_log_row_count_examined == 3


def test_resource_audit_excludes_events_after_exact_frozen_wall_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic_directory = tmp_path / "DiagnosticReports"
    diagnostic_directory.mkdir()
    cutoff_wall = 1_754_006_401.25
    before_wall = cutoff_wall - 0.125
    after_wall = cutoff_wall + 0.125
    before_report = diagnostic_directory / "before.cpu_resource.diag"
    after_report = diagnostic_directory / "after.cpu_resource.diag"
    before_report.write_text("PID: 123\n", encoding="utf-8")
    after_report.write_text("PID: 123\n", encoding="utf-8")
    before_ns = int(before_wall * 1_000_000_000)
    after_ns = int(after_wall * 1_000_000_000)
    os.utime(before_report, ns=(before_ns, before_ns))
    os.utime(after_report, ns=(after_ns, after_ns))

    mapping = _envelope_mapping(tmp_path)
    mapping["diagnostic_report_directories"] = [str(diagnostic_directory.resolve())]
    mapping["diagnostic_report_baseline"] = []
    envelope = CommissioningEnvelope.from_mapping(mapping, allow_test_boundary=True)
    host = MacOSHost(envelope, FakeClock())
    unified_rows = [
        {
            "timestamp": datetime.fromtimestamp(before_wall, tz=UTC).strftime(
                "%Y-%m-%d %H:%M:%S.%f%z"
            ),
            "eventMessage": "cpu resource event for process 123",
        },
        {
            "timestamp": datetime.fromtimestamp(after_wall, tz=UTC).strftime(
                "%Y-%m-%d %H:%M:%S.%f%z"
            ),
            "eventMessage": "cpu resource event for process 123",
        },
    ]

    def log_show(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(unified_rows), "")

    monkeypatch.setattr(host, "_run", log_show)
    monkeypatch.setattr(time, "time", lambda: cutoff_wall + 10)

    observation = host.inspect_resource_events(
        pid=123,
        query_start_wall=cutoff_wall - 10,
        query_end_wall=cutoff_wall,
    )

    assert observation.sources_readable is True
    assert observation.exact_pid_event_count == 2
    assert observation.query_end_wall_utc == datetime.fromtimestamp(
        cutoff_wall,
        tz=UTC,
    ).isoformat(timespec="microseconds")

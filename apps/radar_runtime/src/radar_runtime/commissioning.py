from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import plistlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Protocol, cast

from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.evidence import RuntimeBindings

from .service_evidence import (
    PERSISTENT_SERVICE_CONTRACT_DIGEST,
    PersistentServiceBindings,
    PersistentServiceEvidence,
    PersistentServiceEvidenceError,
    read_complete_persistent_service_evidence,
    read_current_persistent_service_evidence,
    validate_lifecycle_event,
)
from .workbench import EMPTY_PANEL_LABEL, SIMULATION_LABEL, WORKBENCH_NON_CLAIMS

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[0-9a-f]{40}$")
_SERVICE_LABEL = "com.optimatrix.public-shadow.r4"
_PROBE_LABEL = f"{_SERVICE_LABEL}.probe"
_LOOPBACK_HOST = "127.0.0.1"
_LOOPBACK_PORT = 8765
_UID = 501
_PRODUCTION_ROOT = Path("/Users/logan/Optimatrix-public-shadow-observation-004")
_PRODUCTION_SERVICE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.plist"
)
_PRODUCTION_PROBE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.probe.plist"
)
_PRODUCTION_ENVELOPE = _PRODUCTION_ROOT / "deployment/deployment-envelope.json"
_LIFECYCLE_WAIT_MS = 30_000
_COMMISSION_MS = 60_000
_MANUAL_PROBE_MS = 90_000
_PROBE_BOOTSTRAP_MS = 110_000
_HARD_PROBE_MS = 120_000
_OPERABILITY_MS = 180_000
_MAX_PERIODIC_GAP_MS = 90_000
_RESOURCE_GRACE_MS = 30_000
_TERMINAL_WAIT_MS = 120_000
_TEARDOWN_CONVERGENCE_MS = 30_000
_TEARDOWN_POLL_MS = 100


class CommissioningError(RuntimeError):
    """The frozen commissioning boundary failed closed."""


def _require_exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise CommissioningError(
            f"{label} must have exact keys; missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CommissioningError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommissioningError(f"{label} must be an integer")
    return value


def _absolute_path(value: object, label: str) -> Path:
    path = Path(_string(value, label))
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise CommissioningError(f"{label} must be an absolute normalized path")
    return path


def _argv(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CommissioningError(f"{label} must be a non-empty string array")
    result = tuple(_string(item, f"{label} item") for item in value)
    if any("\x00" in item for item in result):
        raise CommissioningError(f"{label} contains NUL")
    return result


def _identity(value: object, label: str) -> str:
    text = _string(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise CommissioningError(f"{label} must be sha256:<64 lowercase hex>")
    return text


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _file_identity(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CommissioningError(f"bound artifact is not a regular file: {path}")
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _directory_inventory_identity(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise CommissioningError(f"inventory root is not a regular directory: {root}")
    digest = hashlib.sha256()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        directory_path = Path(directory)
        for name in (*directory_names, *file_names):
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                kind = "symlink"
                content_identity = hashlib.sha256(os.readlink(path).encode()).hexdigest()
            elif path.is_dir():
                kind = "directory"
                content_identity = "-"
            elif path.is_file():
                kind = "file"
                content_identity = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                raise CommissioningError(f"unsupported inventory entry: {path}")
            digest.update(f"{kind}\0{relative}\0{content_identity}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def _diagnostic_inventory(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        stat = path.stat()
        identity = (
            f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|"
            f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        )
        result[identity] = path
    return result


def _state_inventory(state_root: Path) -> dict[str, object]:
    if not state_root.is_dir() or state_root.is_symlink():
        raise CommissioningError("state root is not a regular directory")
    runs = state_root / "runs"
    if not runs.is_dir() or runs.is_symlink():
        raise CommissioningError("state runs directory is invalid")
    run_directories = sorted(
        path.name for path in runs.iterdir() if path.is_dir() and not path.is_symlink()
    )
    unexpected_run_entries = sorted(
        path.name for path in runs.iterdir() if not path.is_dir() or path.is_symlink()
    )
    file_count = 0
    byte_count = 0
    symlink_count = 0
    latest_mtime_ns = 0
    for directory, directory_names, file_names in os.walk(state_root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            if (directory_path / name).is_symlink():
                symlink_count += 1
        for name in file_names:
            path = directory_path / name
            if path.is_symlink():
                symlink_count += 1
                continue
            stat = path.stat()
            file_count += 1
            byte_count += stat.st_size
            latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
    return {
        "run_directories": run_directories,
        "unexpected_run_entries": unexpected_run_entries,
        "file_count": file_count,
        "byte_count": byte_count,
        "symlink_count": symlink_count,
        "latest_mtime_ns": latest_mtime_ns,
    }


def _known_absent_launchctl(completed: subprocess.CompletedProcess[str]) -> bool:
    if completed.returncode == 0:
        return False
    message = f"{completed.stdout}\n{completed.stderr}".lower()
    return any(
        token in message
        for token in (
            "could not find service",
            "could not find specified service",
            "service not found",
            "no such process",
        )
    )


def _validate_http_documents(
    envelope: CommissioningEnvelope,
    *,
    runtime_identity: str,
    health: Mapping[str, object],
    ready: Mapping[str, object],
    workbench: Mapping[str, object],
    observed_monotonic_ms: int | None = None,
) -> tuple[bool, str]:
    _require_exact_keys(
        health,
        frozenset({"status", "schema_version", "health", "runtime_identity"}),
        "healthz",
    )
    if not (
        health.get("status") == 200
        and health.get("schema_version") == 2
        and health.get("health") is True
        and health.get("runtime_identity") == runtime_identity
    ):
        raise CommissioningError("healthz commissioning mismatch")
    _require_exact_keys(
        ready,
        frozenset({"status", "schema_version", "ready", "runtime_identity"}),
        "readyz",
    )
    ready_value = ready.get("ready")
    if not (
        ready.get("schema_version") == 2
        and ready.get("runtime_identity") == runtime_identity
        and type(ready_value) is bool
        and ready.get("status") == (200 if ready_value else 503)
    ):
        raise CommissioningError("readyz commissioning mismatch")

    _require_exact_keys(
        workbench,
        frozenset(
            {
                "status",
                "schema_version",
                "runtime_identity",
                "code_identity",
                "policy_identities",
                "service",
                "published_fact_boundary",
                "system",
                "zero_claims",
                "radar",
                "underwriting",
                "shadow_entries",
                "positions",
                "outcomes",
                "non_claims",
                "publication_sequence",
            }
        ),
        "workbench",
    )
    policies = workbench.get("policy_identities")
    service = workbench.get("service")
    system = workbench.get("system")
    zero_claims = workbench.get("zero_claims")
    if not (
        workbench.get("status") == 200
        and workbench.get("schema_version") == 2
        and workbench.get("code_identity") == envelope.code_identity
        and workbench.get("runtime_identity") == runtime_identity
        and type(workbench.get("publication_sequence")) is int
        and cast(int, workbench["publication_sequence"]) > 0
        and policies
        == {
            "radar": envelope.radar_policy_identity,
            "underwriting": envelope.underwriting_policy_identity,
            "position": envelope.position_policy_identity,
        }
        and isinstance(service, Mapping)
        and isinstance(system, Mapping)
        and isinstance(zero_claims, Mapping)
        and workbench.get("non_claims") == list(WORKBENCH_NON_CLAIMS)
    ):
        raise CommissioningError("workbench commissioning mismatch")
    _require_exact_keys(
        cast(Mapping[str, object], service),
        frozenset(
            {"phase", "data_state", "health", "ready", "stale", "reason", "recorded_monotonic_ms"}
        ),
        "workbench service",
    )
    data_state = service.get("data_state")
    if not (
        service.get("phase") in {"STARTING", "CONNECTING", "RUNNING", "RECONNECTING", "STOPPING"}
        and data_state in {"CURRENT", "DEGRADED", "STALE", "UNKNOWN", "INTERRUPTED"}
        and service.get("health") is True
        and service.get("ready") is ready_value
        and type(service.get("stale")) is bool
        and service.get("stale") is (data_state == "STALE")
        and isinstance(service.get("reason"), str)
        and service.get("reason")
        and type(service.get("recorded_monotonic_ms")) is int
        and cast(int, service["recorded_monotonic_ms"]) >= 0
        and (
            observed_monotonic_ms is None
            or cast(int, service["recorded_monotonic_ms"]) <= observed_monotonic_ms
        )
        and (
            ready_value is False or (service.get("phase") == "RUNNING" and data_state == "CURRENT")
        )
    ):
        raise CommissioningError("workbench service mismatch")
    _require_exact_keys(
        cast(Mapping[str, object], system),
        frozenset(
            {
                "session_epoch",
                "platform_usable",
                "platform_reason",
                "latest_market_timestamp_ms",
                "data_delay_ms",
                "last_wire_age_ms",
                "coverage_state",
                "coverage_blocking_reason",
                "coverage_affected_scopes",
                "coverage_ratio_percent",
                "known_current_instrument_evaluation_count",
                "monitored_instrument_count",
                "reconnect_count",
                "session_gap_count",
                "global_continuity_epoch",
                "disconnect_records",
            }
        ),
        "workbench system",
    )
    coverage_state = system.get("coverage_state")
    if coverage_state not in {
        "NO_APPLICABLE_SCOPE",
        "KNOWN_COMPLETE",
        "KNOWN_DEGRADED",
        "UNKNOWN",
    }:
        raise CommissioningError("workbench coverage state mismatch")
    integer_system_fields = (
        "known_current_instrument_evaluation_count",
        "monitored_instrument_count",
        "reconnect_count",
        "session_gap_count",
        "global_continuity_epoch",
    )
    session_epoch = system.get("session_epoch")
    nullable_monotonic_fields = (
        "latest_market_timestamp_ms",
        "data_delay_ms",
        "last_wire_age_ms",
    )
    if not (
        (session_epoch is None or (type(session_epoch) is int and session_epoch > 0))
        and all(
            system.get(field) is None
            or (type(system.get(field)) is int and cast(int, system[field]) >= 0)
            for field in nullable_monotonic_fields
        )
        and type(system.get("platform_usable")) is bool
        and isinstance(system.get("platform_reason"), str)
        and isinstance(system.get("coverage_blocking_reason"), str)
        and isinstance(system.get("coverage_affected_scopes"), list)
        and all(
            isinstance(item, str) for item in cast(list[object], system["coverage_affected_scopes"])
        )
        and isinstance(system.get("disconnect_records"), list)
        and all(
            type(system.get(field)) is int and cast(int, system[field]) >= 0
            for field in integer_system_fields
        )
        and cast(int, system["known_current_instrument_evaluation_count"])
        <= cast(int, system["monitored_instrument_count"])
    ):
        raise CommissioningError("workbench system value mismatch")
    coverage_ratio = system.get("coverage_ratio_percent")
    if coverage_ratio is not None:
        if not isinstance(coverage_ratio, str):
            raise CommissioningError("workbench coverage ratio mismatch")
        try:
            ratio = Decimal(coverage_ratio)
        except InvalidOperation as exc:
            raise CommissioningError("workbench coverage ratio mismatch") from exc
        if not Decimal(0) <= ratio <= Decimal(100):
            raise CommissioningError("workbench coverage ratio mismatch")
    _require_exact_keys(
        cast(Mapping[str, object], zero_claims),
        frozenset({"anomaly", "candidate"}),
        "workbench zero_claims",
    )
    for name in ("anomaly", "candidate"):
        claim = zero_claims.get(name)
        if not isinstance(claim, Mapping):
            raise CommissioningError(f"workbench zero claim {name} mismatch")
        _require_exact_keys(
            cast(Mapping[str, object], claim),
            frozenset({"state", "value", "numerator", "denominator", "explanation"}),
            f"workbench zero claim {name}",
        )
        if claim.get("state") not in {"PROVEN_ZERO", "NOT_ZERO", "UNKNOWN"}:
            raise CommissioningError(f"workbench zero claim {name} state mismatch")
        state = claim.get("state")
        value = claim.get("value")
        numerator = claim.get("numerator")
        denominator = claim.get("denominator")
        denominator_valid = denominator is None or (type(denominator) is int and denominator >= 0)
        claim_valid = (
            (state == "UNKNOWN" and value is None and numerator == 0 and type(numerator) is int)
            or (
                state == "PROVEN_ZERO"
                and type(value) is int
                and value == 0
                and type(numerator) is int
                and numerator == 0
                and type(denominator) is int
                and denominator > 0
            )
            or (
                state == "NOT_ZERO"
                and type(value) is int
                and value > 0
                and type(numerator) is int
                and numerator == value
                and (denominator is None or denominator >= numerator)
            )
        )
        if not (denominator_valid and isinstance(claim.get("explanation"), str) and claim_valid):
            raise CommissioningError(f"workbench zero claim {name} value mismatch")
    for name in ("radar", "underwriting", "shadow_entries", "positions", "outcomes"):
        panel = workbench.get(name)
        if not isinstance(panel, Mapping):
            raise CommissioningError(f"workbench panel {name} mismatch")
        expected_panel_keys = {"panel_state", "empty_label", "rows"}
        if name == "shadow_entries":
            expected_panel_keys.add("simulation_label")
        _require_exact_keys(
            cast(Mapping[str, object], panel),
            frozenset(expected_panel_keys),
            f"workbench panel {name}",
        )
        rows = panel.get("rows")
        if not isinstance(rows, list) or panel.get("panel_state") not in {
            "HAS_SETTLED_OBJECTS",
            "EMPTY_NO_SETTLED_OBJECT",
        }:
            raise CommissioningError(f"workbench panel {name} shape mismatch")
        if (panel.get("panel_state") == "EMPTY_NO_SETTLED_OBJECT") is (len(rows) > 0):
            raise CommissioningError(f"workbench panel {name} state/rows mismatch")
        if panel.get("empty_label") != (EMPTY_PANEL_LABEL if not rows else None):
            raise CommissioningError(f"workbench panel {name} empty label mismatch")
        if name == "shadow_entries" and panel.get("simulation_label") != SIMULATION_LABEL:
            raise CommissioningError("workbench shadow simulation label mismatch")
    boundary = workbench.get("published_fact_boundary")
    if boundary is not None:
        if not isinstance(boundary, Mapping):
            raise CommissioningError("workbench published boundary mismatch")
        _require_exact_keys(
            cast(Mapping[str, object], boundary),
            frozenset(
                {"session_epoch", "ingress_seq", "received_monotonic_ms", "causal_seq", "cause"}
            ),
            "workbench published boundary",
        )
        if not (
            all(
                type(boundary.get(field)) is int and cast(int, boundary[field]) >= 0
                for field in ("session_epoch", "ingress_seq", "received_monotonic_ms", "causal_seq")
            )
            and isinstance(boundary.get("cause"), str)
        ):
            raise CommissioningError("workbench published boundary value mismatch")
    return cast(bool, ready_value), cast(str, data_state)


def _validate_probe_row(
    envelope: CommissioningEnvelope,
    row: Mapping[str, object],
    *,
    runtime_identity: str,
    pid: int,
    expected_sequence: int,
    expected_mode: str,
) -> int:
    _require_exact_keys(
        row,
        frozenset(
            {
                "schema_version",
                "sequence",
                "mode",
                "wall_time_utc",
                "monotonic_ms",
                "service_label",
                "launchd_pid",
                "process",
                "inventory",
                "runtime_identity",
                "expected_runtime_identity",
                "runtime_identity_frozen",
                "lifecycle_event_sequence",
                "healthz",
                "readyz",
                "workbench",
                "resource_sources_readable",
                "new_exact_pid_cpu_resource_event_count",
                "errors",
                "operational_success",
            }
        ),
        "probe row",
    )
    monotonic = _integer(row.get("monotonic_ms"), "probe monotonic_ms")
    try:
        wall_time = datetime.fromisoformat(_string(row.get("wall_time_utc"), "probe wall_time_utc"))
    except ValueError as exc:
        raise CommissioningError("probe wall_time_utc mismatch") from exc
    process = row.get("process")
    if not isinstance(process, Mapping):
        raise CommissioningError("probe process mismatch")
    _require_exact_keys(
        cast(Mapping[str, object], process),
        frozenset(
            {
                "matching_process_count",
                "matching_pids",
                "pid",
                "argv",
                "cwd",
                "listeners",
                "rss_bytes",
                "cpu_time_ms",
            }
        ),
        "probe process",
    )
    inventory = row.get("inventory")
    if not isinstance(inventory, Mapping):
        raise CommissioningError("probe state inventory mismatch")
    _require_exact_keys(
        cast(Mapping[str, object], inventory),
        frozenset(
            {
                "run_directories",
                "unexpected_run_entries",
                "file_count",
                "byte_count",
                "symlink_count",
                "latest_mtime_ns",
            }
        ),
        "probe state inventory",
    )
    utc_offset = wall_time.utcoffset()
    if not (
        row.get("schema_version") == 1
        and row.get("sequence") == expected_sequence
        and row.get("mode") == expected_mode
        and wall_time.tzinfo is not None
        and utc_offset is not None
        and utc_offset.total_seconds() == 0
        and row.get("service_label") == envelope.service_label
        and row.get("launchd_pid") == pid
        and row.get("runtime_identity") == runtime_identity
        and row.get("expected_runtime_identity") == runtime_identity
        and row.get("runtime_identity_frozen") is True
        and row.get("lifecycle_event_sequence") == 1
        and row.get("resource_sources_readable") is True
        and type(row.get("new_exact_pid_cpu_resource_event_count")) is int
        and cast(int, row["new_exact_pid_cpu_resource_event_count"]) >= 0
        and row.get("operational_success") is True
        and row.get("errors") == []
        and process.get("matching_process_count") == 1
        and process.get("matching_pids") == [pid]
        and process.get("pid") == pid
        and process.get("argv") == list(envelope.expected_service_argv)
        and process.get("cwd") == str(envelope.expected_service_cwd)
        and process.get("listeners") == [[pid, f"{_LOOPBACK_HOST}:{_LOOPBACK_PORT}"]]
        and type(process.get("rss_bytes")) is int
        and cast(int, process["rss_bytes"]) > 0
        and type(process.get("cpu_time_ms")) is int
        and cast(int, process["cpu_time_ms"]) >= 0
        and inventory.get("run_directories") == [runtime_identity.removeprefix("sha256:")]
        and inventory.get("unexpected_run_entries") == []
        and type(inventory.get("file_count")) is int
        and cast(int, inventory["file_count"]) > 0
        and type(inventory.get("byte_count")) is int
        and cast(int, inventory["byte_count"]) >= 0
        and inventory.get("symlink_count") == 0
        and type(inventory.get("latest_mtime_ns")) is int
        and cast(int, inventory["latest_mtime_ns"]) > 0
    ):
        raise CommissioningError("probe row mismatch")
    health = row.get("healthz")
    ready = row.get("readyz")
    workbench = row.get("workbench")
    if (
        not isinstance(health, Mapping)
        or not isinstance(ready, Mapping)
        or not isinstance(workbench, Mapping)
    ):
        raise CommissioningError("probe endpoint shape mismatch")
    _validate_http_documents(
        envelope,
        runtime_identity=runtime_identity,
        health=cast(Mapping[str, object], health),
        ready=cast(Mapping[str, object], ready),
        workbench=cast(Mapping[str, object], workbench),
        observed_monotonic_ms=monotonic,
    )
    return monotonic


@dataclass(frozen=True)
class CommissioningEnvelope:
    deployment_root: Path
    repository: Path
    state_root: Path
    journal_directory: Path
    receipt_path: Path
    stop_receipt_path: Path
    failure_closure_receipt_path: Path
    probe_ledger_path: Path
    service_label: str
    probe_label: str
    service_target: str
    probe_target: str
    service_plist_path: Path
    probe_plist_path: Path
    uid: int
    listener_host: str
    listener_port: int
    expected_service_cwd: Path
    expected_service_argv: tuple[str, ...]
    service_bootstrap_argv: tuple[str, ...]
    service_kickstart_argv: tuple[str, ...]
    service_bootout_argv: tuple[str, ...]
    probe_bootstrap_argv: tuple[str, ...]
    probe_bootout_argv: tuple[str, ...]
    service_sigint_argv: tuple[str, ...]
    manual_probe_argv: tuple[str, ...]
    final_probe_argv: tuple[str, ...]
    current_audit_argv: tuple[str, ...]
    operability_audit_argv: tuple[str, ...]
    terminal_audit_argv: tuple[str, ...]
    diagnostic_report_directories: tuple[Path, ...]
    diagnostic_report_baseline: tuple[str, ...]
    code_identity: str
    remote_main_tree: str
    radar_policy_identity: str
    underwriting_policy_identity: str
    position_policy_identity: str
    persistent_service_contract_digest: str
    authority_digest: str
    task_digest: str
    controller_digest: str
    service_plist_digest: str
    probe_plist_digest: str
    probe_script_digest: str
    audit_script_digest: str
    python_executable_digest: str
    python_version: str
    service_hot_path_digest: str
    old_root_inventory_identities: Mapping[str, str]
    preflight_facts: Mapping[str, bool]
    envelope_identity: str

    _KEYS = frozenset(
        {
            "schema_version",
            "deployment_root",
            "repository",
            "state_root",
            "journal_directory",
            "receipt_path",
            "stop_receipt_path",
            "failure_closure_receipt_path",
            "probe_ledger_path",
            "service_label",
            "probe_label",
            "service_target",
            "probe_target",
            "service_plist_path",
            "probe_plist_path",
            "uid",
            "listener_host",
            "listener_port",
            "expected_service_cwd",
            "expected_service_argv",
            "service_bootstrap_argv",
            "service_kickstart_argv",
            "service_bootout_argv",
            "probe_bootstrap_argv",
            "probe_bootout_argv",
            "service_sigint_argv",
            "manual_probe_argv",
            "final_probe_argv",
            "current_audit_argv",
            "operability_audit_argv",
            "terminal_audit_argv",
            "diagnostic_report_directories",
            "diagnostic_report_baseline",
            "code_identity",
            "remote_main_tree",
            "radar_policy_identity",
            "underwriting_policy_identity",
            "position_policy_identity",
            "persistent_service_contract_digest",
            "authority_digest",
            "task_digest",
            "controller_digest",
            "service_plist_digest",
            "probe_plist_digest",
            "probe_script_digest",
            "audit_script_digest",
            "python_executable_digest",
            "python_version",
            "service_hot_path_digest",
            "old_root_inventory_identities",
            "preflight_facts",
        }
    )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
        *,
        allow_test_boundary: bool = False,
    ) -> CommissioningEnvelope:
        _require_exact_keys(value, cls._KEYS, "commissioning envelope")
        if _integer(value["schema_version"], "schema_version") != 1:
            raise CommissioningError("unsupported commissioning envelope schema")
        root = _absolute_path(value["deployment_root"], "deployment_root")
        repository = _absolute_path(value["repository"], "repository")
        state_root = _absolute_path(value["state_root"], "state_root")
        journal = _absolute_path(value["journal_directory"], "journal_directory")
        receipt = _absolute_path(value["receipt_path"], "receipt_path")
        stop_receipt = _absolute_path(value["stop_receipt_path"], "stop_receipt_path")
        failure_closure_receipt = _absolute_path(
            value["failure_closure_receipt_path"], "failure_closure_receipt_path"
        )
        ledger = _absolute_path(value["probe_ledger_path"], "probe_ledger_path")
        for path, label in (
            (repository, "repository"),
            (state_root, "state_root"),
            (journal, "journal_directory"),
            (receipt, "receipt_path"),
            (stop_receipt, "stop_receipt_path"),
            (failure_closure_receipt, "failure_closure_receipt_path"),
            (ledger, "probe_ledger_path"),
        ):
            if not path.is_relative_to(root):
                raise CommissioningError(f"{label} must remain inside deployment_root")
        receipt_paths = (receipt, stop_receipt, failure_closure_receipt)
        if len(set(receipt_paths)) != len(receipt_paths):
            raise CommissioningError("receipt paths must be distinct")

        uid = _integer(value["uid"], "uid")
        if uid != _UID:
            raise CommissioningError("r4 uid must be 501")
        service_label = _string(value["service_label"], "service_label")
        probe_label = _string(value["probe_label"], "probe_label")
        service_target = _string(value["service_target"], "service_target")
        probe_target = _string(value["probe_target"], "probe_target")
        if service_label != _SERVICE_LABEL or probe_label != _PROBE_LABEL:
            raise CommissioningError("r4 launchd labels are not exact")
        if service_target != f"gui/{uid}/{service_label}":
            raise CommissioningError("service target mismatch")
        if probe_target != f"gui/{uid}/{probe_label}":
            raise CommissioningError("probe target mismatch")
        if _string(value["listener_host"], "listener_host") != _LOOPBACK_HOST:
            raise CommissioningError("listener must be exact loopback")
        if _integer(value["listener_port"], "listener_port") != _LOOPBACK_PORT:
            raise CommissioningError("listener port mismatch")

        service_plist = _absolute_path(value["service_plist_path"], "service_plist_path")
        probe_plist = _absolute_path(value["probe_plist_path"], "probe_plist_path")
        if not allow_test_boundary and (
            root != _PRODUCTION_ROOT
            or repository != _PRODUCTION_ROOT / "repo"
            or state_root != _PRODUCTION_ROOT / "state"
            or service_plist != _PRODUCTION_SERVICE_PLIST
            or probe_plist != _PRODUCTION_PROBE_PLIST
        ):
            raise CommissioningError("r4 production root/plist boundary mismatch")
        cwd = _absolute_path(value["expected_service_cwd"], "expected_service_cwd")
        expected_service_argv = _argv(value["expected_service_argv"], "expected_service_argv")
        expected_runtime_argv = (
            str(repository / ".venv/bin/python"),
            "-m",
            "radar_runtime",
            "serve-shadow",
            "--state-root",
            str(state_root),
            "--workbench-host",
            _LOOPBACK_HOST,
            "--workbench-port",
            str(_LOOPBACK_PORT),
        )
        if cwd != repository or expected_service_argv != expected_runtime_argv:
            raise CommissioningError("service cwd/argv mismatch")

        commands = {
            "service_bootstrap_argv": _argv(
                value["service_bootstrap_argv"], "service_bootstrap_argv"
            ),
            "service_kickstart_argv": _argv(
                value["service_kickstart_argv"], "service_kickstart_argv"
            ),
            "service_bootout_argv": _argv(value["service_bootout_argv"], "service_bootout_argv"),
            "probe_bootstrap_argv": _argv(value["probe_bootstrap_argv"], "probe_bootstrap_argv"),
            "probe_bootout_argv": _argv(value["probe_bootout_argv"], "probe_bootout_argv"),
            "service_sigint_argv": _argv(value["service_sigint_argv"], "service_sigint_argv"),
        }
        exact_commands = {
            "service_bootstrap_argv": (
                "/bin/launchctl",
                "bootstrap",
                f"gui/{uid}",
                str(service_plist),
            ),
            "service_kickstart_argv": ("/bin/launchctl", "kickstart", service_target),
            "service_bootout_argv": ("/bin/launchctl", "bootout", service_target),
            "probe_bootstrap_argv": ("/bin/launchctl", "bootstrap", f"gui/{uid}", str(probe_plist)),
            "probe_bootout_argv": ("/bin/launchctl", "bootout", probe_target),
            "service_sigint_argv": ("/bin/launchctl", "kill", "SIGINT", service_target),
        }
        for label, expected in exact_commands.items():
            if commands[label] != expected:
                raise CommissioningError(
                    f"{label} is not exact; kickstart replacement is forbidden"
                )

        python = str(repository / ".venv/bin/python")
        manual_probe = _argv(value["manual_probe_argv"], "manual_probe_argv")
        final_probe = _argv(value["final_probe_argv"], "final_probe_argv")
        if (
            len(manual_probe) != 4
            or manual_probe[0] != python
            or manual_probe[2:] != ("--mode", "periodic")
            or not Path(manual_probe[1]).is_relative_to(root)
        ):
            raise CommissioningError("manual probe command mismatch")
        if (
            len(final_probe) != 4
            or final_probe[0] != python
            or final_probe[1] != manual_probe[1]
            or final_probe[2:] != ("--mode", "final-online")
        ):
            raise CommissioningError("final probe command mismatch")

        audits: dict[str, tuple[str, ...]] = {}
        for label, mode in (
            ("current_audit_argv", "current"),
            ("operability_audit_argv", "current"),
            ("terminal_audit_argv", "complete"),
        ):
            command = _argv(value[label], label)
            if (
                len(command) != 6
                or command[0] != python
                or not Path(command[1]).is_relative_to(root)
                or command[2:4] != ("--mode", mode)
                or command[4] != "--output"
                or not Path(command[5]).is_relative_to(root)
            ):
                raise CommissioningError(f"{label} mismatch")
            audits[label] = command
        if not (
            manual_probe[1] == final_probe[1]
            and audits["current_audit_argv"][1]
            == audits["operability_audit_argv"][1]
            == audits["terminal_audit_argv"][1]
        ):
            raise CommissioningError("probe/audit script binding mismatch")

        raw_directories = value["diagnostic_report_directories"]
        if not isinstance(raw_directories, list) or not raw_directories:
            raise CommissioningError("diagnostic_report_directories must be non-empty")
        diagnostic_directories = tuple(
            _absolute_path(item, "diagnostic report directory") for item in raw_directories
        )
        raw_baseline = value["diagnostic_report_baseline"]
        if not isinstance(raw_baseline, list):
            raise CommissioningError("diagnostic_report_baseline must be an array")
        baseline = tuple(_string(item, "diagnostic report baseline item") for item in raw_baseline)
        if len(set(baseline)) != len(baseline):
            raise CommissioningError("diagnostic report baseline contains duplicates")

        code_identity = _string(value["code_identity"], "code_identity")
        if _CODE_RE.fullmatch(code_identity) is None:
            raise CommissioningError("code_identity must be 40 lowercase hex")
        remote_main_tree = _string(value["remote_main_tree"], "remote_main_tree")
        if _CODE_RE.fullmatch(remote_main_tree) is None:
            raise CommissioningError("remote_main_tree must be 40 lowercase hex")
        contract_digest = _identity(
            value["persistent_service_contract_digest"],
            "persistent_service_contract_digest",
        )
        if contract_digest != PERSISTENT_SERVICE_CONTRACT_DIGEST:
            raise CommissioningError("persistent service contract digest mismatch")
        old_inventory = value["old_root_inventory_identities"]
        if not isinstance(old_inventory, Mapping):
            raise CommissioningError("old_root_inventory_identities must be an object")
        _require_exact_keys(
            cast(Mapping[str, object], old_inventory),
            frozenset({"r1", "r2", "r3"}),
            "old_root_inventory_identities",
        )
        old_inventory_identities = {
            name: _identity(old_inventory[name], f"old inventory {name}")
            for name in ("r1", "r2", "r3")
        }
        raw_preflight = value["preflight_facts"]
        if not isinstance(raw_preflight, Mapping):
            raise CommissioningError("preflight_facts must be an object")
        preflight_keys = frozenset(
            {
                "r1_no_writer",
                "r2_no_writer",
                "r3_no_writer",
                "old_labels_absent",
                "r4_root_absent_before_materialization",
                "r4_labels_absent_at_binding",
                "listener_free_at_binding",
                "installed_plists_absent_before_install",
            }
        )
        _require_exact_keys(
            cast(Mapping[str, object], raw_preflight), preflight_keys, "preflight_facts"
        )
        if any(raw_preflight[key] is not True for key in preflight_keys):
            raise CommissioningError("every frozen preflight fact must be true")
        envelope_identity = f"sha256:{hashlib.sha256(_canonical_json(value)).hexdigest()}"
        return cls(
            deployment_root=root,
            repository=repository,
            state_root=state_root,
            journal_directory=journal,
            receipt_path=receipt,
            stop_receipt_path=stop_receipt,
            failure_closure_receipt_path=failure_closure_receipt,
            probe_ledger_path=ledger,
            service_label=service_label,
            probe_label=probe_label,
            service_target=service_target,
            probe_target=probe_target,
            service_plist_path=service_plist,
            probe_plist_path=probe_plist,
            uid=uid,
            listener_host=_LOOPBACK_HOST,
            listener_port=_LOOPBACK_PORT,
            expected_service_cwd=cwd,
            expected_service_argv=expected_service_argv,
            manual_probe_argv=manual_probe,
            final_probe_argv=final_probe,
            current_audit_argv=audits["current_audit_argv"],
            operability_audit_argv=audits["operability_audit_argv"],
            terminal_audit_argv=audits["terminal_audit_argv"],
            diagnostic_report_directories=diagnostic_directories,
            diagnostic_report_baseline=baseline,
            code_identity=code_identity,
            remote_main_tree=remote_main_tree,
            radar_policy_identity=_identity(
                value["radar_policy_identity"], "radar_policy_identity"
            ),
            underwriting_policy_identity=_identity(
                value["underwriting_policy_identity"], "underwriting_policy_identity"
            ),
            position_policy_identity=_identity(
                value["position_policy_identity"], "position_policy_identity"
            ),
            persistent_service_contract_digest=contract_digest,
            authority_digest=_identity(value["authority_digest"], "authority_digest"),
            task_digest=_identity(value["task_digest"], "task_digest"),
            controller_digest=_identity(value["controller_digest"], "controller_digest"),
            service_plist_digest=_identity(value["service_plist_digest"], "service_plist_digest"),
            probe_plist_digest=_identity(value["probe_plist_digest"], "probe_plist_digest"),
            probe_script_digest=_identity(value["probe_script_digest"], "probe_script_digest"),
            audit_script_digest=_identity(value["audit_script_digest"], "audit_script_digest"),
            python_executable_digest=_identity(
                value["python_executable_digest"], "python_executable_digest"
            ),
            python_version=_string(value["python_version"], "python_version"),
            service_hot_path_digest=_identity(
                value["service_hot_path_digest"], "service_hot_path_digest"
            ),
            old_root_inventory_identities=old_inventory_identities,
            preflight_facts={key: True for key in preflight_keys},
            envelope_identity=envelope_identity,
            **commands,
        )


@dataclass(frozen=True)
class LifecycleObservation:
    run_directory: Path
    event: Mapping[str, object]
    observed_monotonic_ms: int


def _bindings_from_event(
    envelope: CommissioningEnvelope,
    event: Mapping[str, object],
) -> tuple[PersistentServiceBindings, RuntimeBindings]:
    if event.get("event_sequence") != 1:
        raise CommissioningError("first lifecycle sequence mismatch")
    expected = {
        "code_identity": envelope.code_identity,
        "radar_policy_identity": envelope.radar_policy_identity,
        "underwriting_policy_identity": envelope.underwriting_policy_identity,
        "position_policy_identity": envelope.position_policy_identity,
    }
    for field, exact in expected.items():
        if event.get(field) != exact:
            raise CommissioningError(f"first lifecycle {field} mismatch")
    runtime_identity = _identity(event.get("runtime_identity"), "runtime_identity")
    downstream = RuntimeBindings(
        code_identity=envelope.code_identity,
        runtime_identity=runtime_identity,
        radar_policy_identity=envelope.radar_policy_identity,
        underwriting_policy_identity=envelope.underwriting_policy_identity,
        position_policy_identity=envelope.position_policy_identity,
        underwriting_position_contract_digest=UNDERWRITING_POSITION_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    service = PersistentServiceBindings.from_runtime_bindings(downstream)
    try:
        validate_lifecycle_event(event, bindings=service)
    except PersistentServiceEvidenceError as exc:
        raise CommissioningError(f"lifecycle validation failed: {exc}") from exc
    if event.get("persistent_service_contract_identity") != service.contract_identity:
        raise CommissioningError("lifecycle persistent service contract identity mismatch")
    return service, downstream


@dataclass(frozen=True)
class CommissioningObservation:
    pid: int
    launchd_runs: int
    argv: tuple[str, ...]
    cwd: Path
    listeners: tuple[tuple[int, str], ...]
    healthz: Mapping[str, object]
    readyz: Mapping[str, object]
    workbench: Mapping[str, object]
    observed_monotonic_ms: int


@dataclass(frozen=True)
class OperabilityObservation:
    pid: int
    runtime_identity: str
    launchd_runs: int
    covered_from_monotonic_ms: int
    covered_until_monotonic_ms: int
    periodic_row_monotonic_ms: tuple[int, ...]
    all_probe_attempts_operational: bool
    cpu_time_delta_ms: int
    elapsed_monotonic_ms: int
    cpu_utilization_percent: str
    rss_bytes: int
    max_http_latency_ms: int
    http_attempt_count: int
    http_success_count: int
    readiness_states: tuple[bool, ...]
    data_states: tuple[str, ...]
    queue_lag_transition_count: int
    resource_sources_readable: bool
    resource_audit_boundary_monotonic_ms: int
    resource_query_start_wall_utc: str
    resource_query_end_wall_utc: str
    diagnostic_report_count_examined: int
    unified_log_row_count_examined: int
    new_exact_pid_cpu_resource_event_count: int


@dataclass(frozen=True)
class ResourceEventObservation:
    sources_readable: bool
    exact_pid_event_count: int
    query_start_wall_utc: str
    query_end_wall_utc: str
    diagnostic_report_count_examined: int
    unified_log_row_count_examined: int


@dataclass(frozen=True)
class CommissioningReceipt:
    status: str
    runtime_identity: str | None
    pid: int | None
    run_directory: str | None
    gate_start_monotonic_ms: int | None
    gate_end_monotonic_ms: int | None
    envelope_identity: str
    failure_reason: str | None = None
    operability: Mapping[str, object] | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "runtime_identity": self.runtime_identity,
            "pid": self.pid,
            "run_directory": self.run_directory,
            "gate_start_monotonic_ms": self.gate_start_monotonic_ms,
            "gate_end_monotonic_ms": self.gate_end_monotonic_ms,
            "envelope_identity": self.envelope_identity,
            "failure_reason": self.failure_reason,
            "operability": None if self.operability is None else dict(self.operability),
        }


class Clock(Protocol):
    def monotonic_ms(self) -> int: ...

    def wall_time(self) -> float: ...

    def sleep_until(self, deadline_ms: int) -> None: ...


class ProbeAdapter(Protocol):
    def collect(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        expected_sequence: int,
        deadline_ms: int,
    ) -> Mapping[str, object]: ...


class AuditAdapter(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        deadline_ms: int,
    ) -> Mapping[str, object]: ...


class HostAdapter(Protocol):
    def preflight(self) -> None: ...

    def bootstrap_service(self) -> None: ...

    def kickstart_service(self) -> None: ...

    def wait_for_lifecycle(self, *, deadline_ms: int) -> LifecycleObservation: ...

    def inspect_commissioning(
        self, *, runtime_identity: str, run_directory: Path, deadline_ms: int
    ) -> CommissioningObservation: ...

    def bootstrap_periodic_probe(self) -> None: ...

    def inspect_operability(
        self,
        *,
        pid: int,
        runtime_identity: str,
        gate_start_monotonic_ms: int,
        gate_end_monotonic_ms: int,
        resource_audit_boundary_monotonic_ms: int,
        resource_query_end_wall: float,
    ) -> OperabilityObservation: ...

    def bootout_periodic_probe(self) -> None: ...

    def sigint_service(self) -> None: ...

    def wait_for_terminal(self, *, run_directory: Path, deadline_ms: int) -> None: ...

    def bootout_service(self) -> None: ...

    def current_service_pid(self) -> int: ...

    def service_running(self, *, expected_pid: int) -> bool: ...

    def verify_quiescent(self, *, expected_pid: int | None) -> None: ...


CurrentReader = Callable[..., PersistentServiceEvidence]


class CommissioningController:
    def __init__(
        self,
        envelope: CommissioningEnvelope,
        *,
        host: HostAdapter,
        clock: Clock,
        probe: ProbeAdapter,
        audit: AuditAdapter,
        current_reader: CurrentReader = read_current_persistent_service_evidence,
    ) -> None:
        self.envelope = envelope
        self.host = host
        self.clock = clock
        self.probe = probe
        self.audit = audit
        self.current_reader = current_reader

    def _journal(self, name: str, value: Mapping[str, object]) -> None:
        existed = self.envelope.journal_directory.exists()
        self.envelope.journal_directory.mkdir(parents=True, exist_ok=True)
        if not existed:
            parent_descriptor = os.open(self.envelope.journal_directory.parent, os.O_RDONLY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        path = self.envelope.journal_directory / f"{name}.json"
        payload = _canonical_json(
            {
                "schema_version": 1,
                "envelope_identity": self.envelope.envelope_identity,
                "intent": name,
                "wall_time_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
                "recorded_monotonic_ms": self.clock.monotonic_ms(),
                **value,
            }
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise CommissioningError(f"journal intent already exists: {name}") from exc
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            directory_descriptor = os.open(self.envelope.journal_directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except BaseException:
            raise

    def _write_receipt(self, path: Path, receipt: CommissioningReceipt) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json(receipt.as_mapping())
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise CommissioningError(f"output already exists: {path}") from exc
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def _bindings(
        self, event: Mapping[str, object]
    ) -> tuple[PersistentServiceBindings, RuntimeBindings]:
        return _bindings_from_event(self.envelope, event)

    def _validate_commissioning(
        self,
        observation: CommissioningObservation,
        *,
        runtime_identity: str,
        deadline_ms: int,
    ) -> None:
        if observation.observed_monotonic_ms > deadline_ms:
            raise CommissioningError("commissioning deadline exceeded")
        if observation.pid <= 0 or observation.launchd_runs != 1:
            raise CommissioningError("service pid/runs mismatch")
        if observation.argv != self.envelope.expected_service_argv:
            raise CommissioningError("service argv mismatch")
        if observation.cwd != self.envelope.expected_service_cwd:
            raise CommissioningError("service cwd mismatch")
        if observation.listeners != ((observation.pid, f"{_LOOPBACK_HOST}:{_LOOPBACK_PORT}"),):
            raise CommissioningError("service listener is not exact loopback")
        _validate_http_documents(
            self.envelope,
            runtime_identity=runtime_identity,
            health=observation.healthz,
            ready=observation.readyz,
            workbench=observation.workbench,
            observed_monotonic_ms=observation.observed_monotonic_ms,
        )

    def _validate_probe(
        self,
        row: Mapping[str, object],
        *,
        runtime_identity: str,
        pid: int,
        expected_sequence: int,
        expected_mode: str,
        deadline_ms: int,
    ) -> None:
        monotonic = _validate_probe_row(
            self.envelope,
            row,
            runtime_identity=runtime_identity,
            pid=pid,
            expected_sequence=expected_sequence,
            expected_mode=expected_mode,
        )
        if monotonic > deadline_ms:
            raise CommissioningError("manual probe deadline exceeded")

    def _validate_current_audit(
        self,
        value: Mapping[str, object],
        *,
        runtime_identity: str,
        earliest_ms: int,
        deadline_ms: int,
        minimum_probe_rows: int,
        exact_probe_rows: int | None = None,
    ) -> None:
        audit_ms = _integer(value.get("audit_monotonic_ms"), "audit_monotonic_ms")
        if not earliest_ms <= audit_ms <= deadline_ms:
            raise CommissioningError("current audit deadline exceeded")
        if not (
            value.get("schema_version") == 1
            and value.get("audit_mode") == "current"
            and value.get("reader_verdict") == "PASS"
            and value.get("reader_integrity_status") == "PASS_CURRENT_INCOMPLETE"
            and value.get("terminal_business_status") == "LIVE_INCOMPLETE_NO_TERMINAL"
            and value.get("business_acceptance") == "PENDING_LIVE"
            and value.get("runtime_identity") == runtime_identity
            and value.get("envelope_identity") == self.envelope.envelope_identity
            and value.get("twenty_four_hour_continuous_public_service_sample") == "PENDING"
        ):
            raise CommissioningError("current audit mismatch")
        probe = value.get("probe_evaluation")
        if not (
            isinstance(probe, Mapping)
            and type(probe.get("row_count")) is int
            and cast(int, probe["row_count"]) >= minimum_probe_rows
            and (exact_probe_rows is None or cast(int, probe["row_count"]) == exact_probe_rows)
            and probe.get("contiguous_sequence") is True
            and probe.get("all_operational_success") is True
            and probe.get("all_rows_contract_valid") is True
            and probe.get("first_probe_within_limit") is True
            and probe.get("failure_marker_count") == 0
            and probe.get("stderr_failure_sentinel_count") == 0
        ):
            raise CommissioningError("current audit probe evaluation mismatch")
        if minimum_probe_rows >= 3:
            operability = value.get("operability_evaluation")
            if not (
                isinstance(operability, Mapping)
                and operability.get("present") is True
                and operability.get("valid") is True
            ):
                raise CommissioningError("current audit operability evaluation mismatch")

    def _validate_terminal_audit(
        self,
        value: Mapping[str, object],
        *,
        runtime_identity: str,
        explicit_stop_probe_required: bool,
    ) -> None:
        integrity = value.get("reader_integrity_status")
        business = value.get("business_acceptance")
        sample = value.get("twenty_four_hour_continuous_public_service_sample")
        clean = integrity == "PASS_COMPLETE_CLEAN_STOP"
        process_failure = integrity == "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY"
        if not (
            value.get("schema_version") == 1
            and value.get("audit_mode") == "complete"
            and value.get("reader_verdict") == "PASS"
            and (clean or process_failure)
            and value.get("terminal_business_status")
            in {"CLEAN_STOP_COMPLETE", "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"}
            and business
            in {
                "OPERATIONAL_24H_GATE_MET",
                "OPERATIONAL_24H_GATE_NOT_MET",
                "NOT_ACCEPTED_PROCESS_FAILURE",
            }
            and sample in {"MET", "NOT_MET"}
            and value.get("runtime_identity") == runtime_identity
            and value.get("envelope_identity") == self.envelope.envelope_identity
            and (business == "OPERATIONAL_24H_GATE_MET") is (sample == "MET")
            and (
                (
                    clean
                    and value.get("terminal_business_status") == "CLEAN_STOP_COMPLETE"
                    and business in {"OPERATIONAL_24H_GATE_MET", "OPERATIONAL_24H_GATE_NOT_MET"}
                )
                or (
                    process_failure
                    and value.get("terminal_business_status")
                    == "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"
                    and business == "NOT_ACCEPTED_PROCESS_FAILURE"
                    and sample == "NOT_MET"
                )
            )
        ):
            raise CommissioningError("terminal audit mismatch")
        probe = value.get("probe_evaluation")
        if not (
            isinstance(probe, Mapping)
            and type(probe.get("row_count")) is int
            and cast(int, probe["row_count"]) >= 0
            and type(probe.get("contiguous_sequence")) is bool
            and type(probe.get("all_operational_success")) is bool
            and type(probe.get("all_rows_contract_valid")) is bool
            and type(probe.get("first_probe_within_limit")) is bool
            and type(probe.get("failure_marker_count")) is int
            and cast(int, probe["failure_marker_count"]) >= 0
            and type(probe.get("stderr_failure_sentinel_count")) is int
            and cast(int, probe["stderr_failure_sentinel_count"]) >= 0
        ):
            raise CommissioningError("terminal audit probe evaluation mismatch")
        if explicit_stop_probe_required and not (
            cast(int, probe["row_count"]) >= 2
            and probe.get("contiguous_sequence") is True
            and probe.get("all_operational_success") is True
            and probe.get("all_rows_contract_valid") is True
            and probe.get("first_probe_within_limit") is True
            and probe.get("failure_marker_count") == 0
            and probe.get("stderr_failure_sentinel_count") == 0
        ):
            raise CommissioningError("terminal explicit-stop probe evaluation mismatch")

    @staticmethod
    def _validate_operability(
        value: OperabilityObservation,
        *,
        pid: int,
        runtime_identity: str,
        gate_start_ms: int,
        gate_end_ms: int,
        resource_boundary_ms: int,
        resource_query_end_wall_utc: str,
    ) -> None:
        if not (
            value.pid == pid
            and value.runtime_identity == runtime_identity
            and value.launchd_runs == 1
            and value.covered_from_monotonic_ms == gate_start_ms
            and value.covered_until_monotonic_ms >= gate_end_ms
            and value.all_probe_attempts_operational
            and value.cpu_time_delta_ms >= 0
            and value.elapsed_monotonic_ms >= _OPERABILITY_MS
            and value.cpu_utilization_percent
            and value.rss_bytes > 0
            and value.max_http_latency_ms >= 0
            and value.http_attempt_count >= 6
            and value.http_success_count == value.http_attempt_count
            and len(value.readiness_states) >= 2
            and len(value.data_states) >= 2
            and value.queue_lag_transition_count >= 0
            and value.resource_sources_readable
            and value.resource_audit_boundary_monotonic_ms >= resource_boundary_ms
            and value.resource_query_end_wall_utc == resource_query_end_wall_utc
            and value.resource_query_start_wall_utc
            and value.resource_query_end_wall_utc
            and value.diagnostic_report_count_examined >= 0
            and value.unified_log_row_count_examined >= 0
            and value.new_exact_pid_cpu_resource_event_count == 0
        ):
            raise CommissioningError("operability observation mismatch")
        rows = value.periodic_row_monotonic_ms
        if len(rows) < 2 or tuple(sorted(rows)) != rows or len(set(rows)) != len(rows):
            raise CommissioningError("operability requires two ordered periodic rows")
        partition = (gate_start_ms, *rows, gate_end_ms)
        if any(later - earlier > _MAX_PERIODIC_GAP_MS for earlier, later in pairwise(partition)):
            raise CommissioningError("operability periodic gap exceeded")
        if rows[0] <= gate_start_ms or rows[-1] > gate_end_ms:
            raise CommissioningError("operability periodic rows are outside gate")

    @staticmethod
    def _operability_mapping(value: OperabilityObservation) -> dict[str, object]:
        partition = (
            value.covered_from_monotonic_ms,
            *value.periodic_row_monotonic_ms,
            value.covered_until_monotonic_ms,
        )
        return {
            "pid": value.pid,
            "runtime_identity": value.runtime_identity,
            "launchd_runs": value.launchd_runs,
            "gate_start_monotonic_ms": value.covered_from_monotonic_ms,
            "gate_end_monotonic_ms": value.covered_until_monotonic_ms,
            "covered_duration_ms": (
                value.covered_until_monotonic_ms - value.covered_from_monotonic_ms
            ),
            "periodic_row_monotonic_ms": list(value.periodic_row_monotonic_ms),
            "partition_gap_ms": [later - earlier for earlier, later in pairwise(partition)],
            "cpu_time_delta_ms": value.cpu_time_delta_ms,
            "elapsed_monotonic_ms": value.elapsed_monotonic_ms,
            "cpu_utilization_percent": value.cpu_utilization_percent,
            "cpu_utilization_denominator": "one_process_elapsed_monotonic_ms",
            "rss_bytes": value.rss_bytes,
            "max_http_latency_ms": value.max_http_latency_ms,
            "http_attempt_count": value.http_attempt_count,
            "http_success_count": value.http_success_count,
            "readiness_states": list(value.readiness_states),
            "data_states": list(value.data_states),
            "queue_lag_transition_count": value.queue_lag_transition_count,
            "resource_sources_readable": value.resource_sources_readable,
            "resource_audit_boundary_monotonic_ms": (value.resource_audit_boundary_monotonic_ms),
            "resource_query_start_wall_utc": value.resource_query_start_wall_utc,
            "resource_query_end_wall_utc": value.resource_query_end_wall_utc,
            "diagnostic_report_count_examined": value.diagnostic_report_count_examined,
            "unified_log_row_count_examined": value.unified_log_row_count_examined,
            "new_exact_pid_cpu_resource_event_count": (
                value.new_exact_pid_cpu_resource_event_count
            ),
        }

    def _bootout_and_verify(self, *, reason: str, expected_pid: int | None) -> tuple[str, ...]:
        errors: list[str] = []
        try:
            self._journal("PROBE_BOOTOUT_INTENT", {"reason": reason})
            self.host.bootout_periodic_probe()
        except Exception as exc:
            errors.append(f"probe bootout: {exc}")
        try:
            self._journal("SERVICE_BOOTOUT_INTENT", {"reason": reason})
            self.host.bootout_service()
        except Exception as exc:
            errors.append(f"service bootout: {exc}")
        try:
            self.host.verify_quiescent(expected_pid=expected_pid)
        except Exception as exc:
            errors.append(f"quiescence: {exc}")
        return tuple(errors)

    def _failure_with_runtime(
        self,
        *,
        run_directory: Path,
        runtime_identity: str,
        pid: int | None,
        error: Exception,
    ) -> None:
        receipt = CommissioningReceipt(
            status="COMMISSION_FAILED_CLEANUP_PENDING",
            runtime_identity=runtime_identity,
            pid=pid,
            run_directory=str(run_directory),
            gate_start_monotonic_ms=None,
            gate_end_monotonic_ms=None,
            envelope_identity=self.envelope.envelope_identity,
            failure_reason=str(error),
        )
        self._write_receipt(self.envelope.receipt_path, receipt)
        bound_pid = pid
        pid_binding_error = (
            CommissioningError("runtime PID was not durably bound after lifecycle")
            if bound_pid is None
            else None
        )
        probe_bootout_error: Exception | None = None
        try:
            self._journal("PROBE_BOOTOUT_INTENT", {"reason": "FAILURE"})
            self.host.bootout_periodic_probe()
        except Exception as exc:
            probe_bootout_error = exc
        liveness_error: Exception | None = None
        running: bool | None = None
        if bound_pid is not None:
            try:
                running = self.host.service_running(expected_pid=bound_pid)
            except Exception as exc:
                liveness_error = exc
        if running is True:
            try:
                self._journal("SIGINT_INTENT", {"runtime_identity": runtime_identity})
                self.host.sigint_service()
            except Exception as exc:
                liveness_error = exc
        elif running is False:
            self._journal(
                "NATURAL_TERMINAL_CLOSE_INTENT",
                {
                    "runtime_identity": runtime_identity,
                    "reason": "COMMISSION_FAILURE",
                },
            )
        terminal_wait_error: Exception | None = None
        try:
            self.host.wait_for_terminal(
                run_directory=run_directory,
                deadline_ms=self.clock.monotonic_ms() + _TERMINAL_WAIT_MS,
            )
        except Exception as exc:
            terminal_wait_error = exc
        terminal: Mapping[str, object] | None = None
        audit_error: Exception | None = None
        if terminal_wait_error is None:
            try:
                terminal = self.audit.run(
                    self.envelope.terminal_audit_argv,
                    runtime_identity=runtime_identity,
                    deadline_ms=self.clock.monotonic_ms() + _TERMINAL_WAIT_MS,
                )
                self._validate_terminal_audit(
                    terminal,
                    runtime_identity=runtime_identity,
                    explicit_stop_probe_required=False,
                )
            except Exception as exc:
                audit_error = exc
        cleanup_errors: list[str] = []
        terminal_proven = terminal_wait_error is None
        if terminal_proven:
            try:
                self._journal("SERVICE_BOOTOUT_INTENT", {"reason": "FAILURE"})
                self.host.bootout_service()
            except Exception as exc:
                cleanup_errors.append(f"service bootout failed: {exc}")
            try:
                self.host.verify_quiescent(expected_pid=bound_pid)
            except Exception as exc:
                cleanup_errors.append(f"quiescence failed: {exc}")
        closure_errors = [
            message
            for message in (
                f"runtime PID binding failed: {pid_binding_error}"
                if pid_binding_error is not None
                else None,
                f"probe bootout failed: {probe_bootout_error}"
                if probe_bootout_error is not None
                else None,
                f"service liveness/signal failed: {liveness_error}"
                if liveness_error is not None
                else None,
                f"terminal wait failed: {terminal_wait_error}"
                if terminal_wait_error is not None
                else None,
                f"terminal audit failed: {audit_error}" if audit_error is not None else None,
            )
            if message is not None
        ] + cleanup_errors
        closure = CommissioningReceipt(
            status=(
                "COMMISSION_FAILED_TERMINAL_AUDITED_QUIESCENT"
                if not closure_errors
                else "COMMISSION_FAILED_CLEANUP_BLOCKED"
            ),
            runtime_identity=runtime_identity,
            pid=bound_pid,
            run_directory=str(run_directory),
            gate_start_monotonic_ms=None,
            gate_end_monotonic_ms=None,
            envelope_identity=self.envelope.envelope_identity,
            failure_reason=(str(error) if not closure_errors else "; ".join(closure_errors)),
        )
        self._write_receipt(self.envelope.failure_closure_receipt_path, closure)
        if closure_errors:
            self._journal(
                "FAILURE_CLOSURE_BLOCKED",
                {
                    "runtime_identity": runtime_identity,
                    "failure_closure_status": closure.status,
                    "errors": closure_errors,
                },
            )
        else:
            self._journal(
                "FAILURE_CLOSURE_COMPLETE",
                {
                    "runtime_identity": runtime_identity,
                    "failure_closure_status": closure.status,
                    "terminal_audit_status": "PASS",
                    "terminal_business_status": (
                        terminal.get("terminal_business_status") if terminal is not None else None
                    ),
                },
            )
        if closure_errors:
            raise CommissioningError("; ".join(closure_errors))

    def _failure_without_runtime(self, error: Exception) -> None:
        self._write_receipt(
            self.envelope.receipt_path,
            CommissioningReceipt(
                status="STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING",
                runtime_identity=None,
                pid=None,
                run_directory=None,
                gate_start_monotonic_ms=None,
                gate_end_monotonic_ms=None,
                envelope_identity=self.envelope.envelope_identity,
                failure_reason=str(error),
            ),
        )
        self._journal("STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING", {"error": str(error)})
        cleanup_errors = self._bootout_and_verify(reason="NO_RUNTIME", expected_pid=None)
        closure = CommissioningReceipt(
            status=(
                "STARTUP_FAILED_NO_RUNTIME_QUIESCENT"
                if not cleanup_errors
                else "STARTUP_FAILED_NO_RUNTIME_CLEANUP_BLOCKED"
            ),
            runtime_identity=None,
            pid=None,
            run_directory=None,
            gate_start_monotonic_ms=None,
            gate_end_monotonic_ms=None,
            envelope_identity=self.envelope.envelope_identity,
            failure_reason=(str(error) if not cleanup_errors else "; ".join(cleanup_errors)),
        )
        self._write_receipt(self.envelope.failure_closure_receipt_path, closure)
        if cleanup_errors:
            self._journal(
                "NO_RUNTIME_CLOSURE_BLOCKED",
                {"failure_closure_status": closure.status, "errors": cleanup_errors},
            )
            raise CommissioningError("; ".join(cleanup_errors))
        self._journal(
            "NO_RUNTIME_CLOSURE_COMPLETE",
            {"failure_closure_status": closure.status},
        )

    def commission(self) -> CommissioningReceipt:
        if self.envelope.journal_directory.exists():
            raise CommissioningError("commissioning journal already exists")
        self.host.preflight()
        lifecycle: LifecycleObservation | None = None
        runtime_identity: str | None = None
        pid: int | None = None
        mutation_possible = False
        try:
            self._journal("SERVICE_BOOTSTRAP_INTENT", {})
            mutation_possible = True
            self.host.bootstrap_service()
            self._journal("KICKSTART_INTENT", {})
            kickstart_ms = self.clock.monotonic_ms()
            self.host.kickstart_service()
            lifecycle = self.host.wait_for_lifecycle(deadline_ms=kickstart_ms + _LIFECYCLE_WAIT_MS)
            start_ms = _integer(
                lifecycle.event.get("recorded_monotonic_ms"), "recorded_monotonic_ms"
            )
            if not (
                kickstart_ms
                <= start_ms
                <= lifecycle.observed_monotonic_ms
                <= kickstart_ms + _LIFECYCLE_WAIT_MS
            ):
                raise CommissioningError("lifecycle deadline exceeded")
            runtime_identity = _identity(
                lifecycle.event.get("runtime_identity"), "runtime_identity"
            )
            pid = self.host.current_service_pid()
            self._journal(
                "RUNTIME_PID_BINDING",
                {"runtime_identity": runtime_identity, "pid": pid},
            )
            service_bindings, downstream_bindings = self._bindings(lifecycle.event)
            if downstream_bindings.runtime_identity != runtime_identity:
                raise CommissioningError("lifecycle runtime identity mismatch")
            if lifecycle.run_directory.name != runtime_identity.removeprefix("sha256:"):
                raise CommissioningError("run directory/runtime identity mismatch")
            evidence = self.current_reader(
                lifecycle.run_directory,
                bindings=service_bindings,
                downstream_bindings=downstream_bindings,
            )
            if not evidence.events or dict(evidence.events[0]) != dict(lifecycle.event):
                raise CommissioningError("current reader first lifecycle mismatch")
            observation = self.host.inspect_commissioning(
                runtime_identity=runtime_identity,
                run_directory=lifecycle.run_directory,
                deadline_ms=start_ms + _COMMISSION_MS,
            )
            if observation.pid != pid:
                raise CommissioningError("commissioning PID changed after lifecycle binding")
            self._validate_commissioning(
                observation,
                runtime_identity=runtime_identity,
                deadline_ms=start_ms + _COMMISSION_MS,
            )
            row = self.probe.collect(
                self.envelope.manual_probe_argv,
                runtime_identity=runtime_identity,
                expected_sequence=1,
                deadline_ms=start_ms + _MANUAL_PROBE_MS,
            )
            self._validate_probe(
                row,
                runtime_identity=runtime_identity,
                pid=observation.pid,
                expected_sequence=1,
                expected_mode="periodic",
                deadline_ms=start_ms + _MANUAL_PROBE_MS,
            )
            audit = self.audit.run(
                self.envelope.current_audit_argv,
                runtime_identity=runtime_identity,
                deadline_ms=start_ms + _PROBE_BOOTSTRAP_MS,
            )
            self._validate_current_audit(
                audit,
                runtime_identity=runtime_identity,
                earliest_ms=start_ms,
                deadline_ms=start_ms + _PROBE_BOOTSTRAP_MS,
                minimum_probe_rows=1,
                exact_probe_rows=1,
            )
            if self.clock.monotonic_ms() > start_ms + _PROBE_BOOTSTRAP_MS:
                raise CommissioningError("periodic probe bootstrap deadline exceeded")
            self._journal("PROBE_BOOTSTRAP_INTENT", {"runtime_identity": runtime_identity})
            self.host.bootstrap_periodic_probe()
            if self.clock.monotonic_ms() > start_ms + _PROBE_BOOTSTRAP_MS:
                raise CommissioningError("periodic probe bootstrap deadline exceeded")
            gate_start_ms = self.clock.monotonic_ms()
            gate_end_ms = gate_start_ms + _OPERABILITY_MS
            resource_boundary_ms = gate_end_ms + _RESOURCE_GRACE_MS
            resource_query_end_wall = (
                self.clock.wall_time() + (_OPERABILITY_MS + _RESOURCE_GRACE_MS) / 1000
            )
            resource_query_end_wall_utc = datetime.fromtimestamp(
                resource_query_end_wall, tz=UTC
            ).isoformat(timespec="microseconds")
            self._journal(
                "HOST_OPERABILITY_GATE_START",
                {
                    "runtime_identity": runtime_identity,
                    "gate_start_monotonic_ms": gate_start_ms,
                    "gate_end_monotonic_ms": gate_end_ms,
                    "resource_audit_boundary_monotonic_ms": resource_boundary_ms,
                    "resource_query_end_wall_utc": resource_query_end_wall_utc,
                },
            )
            operability = self.host.inspect_operability(
                pid=observation.pid,
                runtime_identity=runtime_identity,
                gate_start_monotonic_ms=gate_start_ms,
                gate_end_monotonic_ms=gate_end_ms,
                resource_audit_boundary_monotonic_ms=resource_boundary_ms,
                resource_query_end_wall=resource_query_end_wall,
            )
            self._validate_operability(
                operability,
                pid=observation.pid,
                runtime_identity=runtime_identity,
                gate_start_ms=gate_start_ms,
                gate_end_ms=gate_end_ms,
                resource_boundary_ms=resource_boundary_ms,
                resource_query_end_wall_utc=resource_query_end_wall_utc,
            )
            operability_mapping = self._operability_mapping(operability)
            self._journal(
                "HOST_OPERABILITY_GATE_RESULT",
                {
                    "runtime_identity": runtime_identity,
                    "operability": operability_mapping,
                },
            )
            final_audit = self.audit.run(
                self.envelope.operability_audit_argv,
                runtime_identity=runtime_identity,
                deadline_ms=resource_boundary_ms + _LIFECYCLE_WAIT_MS,
            )
            self._validate_current_audit(
                final_audit,
                runtime_identity=runtime_identity,
                earliest_ms=resource_boundary_ms,
                deadline_ms=resource_boundary_ms + _LIFECYCLE_WAIT_MS,
                minimum_probe_rows=3,
            )
            receipt = CommissioningReceipt(
                status="COMMISSIONED",
                runtime_identity=runtime_identity,
                pid=observation.pid,
                run_directory=str(lifecycle.run_directory),
                gate_start_monotonic_ms=gate_start_ms,
                gate_end_monotonic_ms=gate_end_ms,
                envelope_identity=self.envelope.envelope_identity,
                operability=operability_mapping,
            )
            self._write_receipt(self.envelope.receipt_path, receipt)
            return receipt
        except Exception as exc:
            error = exc if isinstance(exc, CommissioningError) else CommissioningError(str(exc))
            if mutation_possible:
                try:
                    if lifecycle is None or runtime_identity is None:
                        self._failure_without_runtime(error)
                    else:
                        self._failure_with_runtime(
                            run_directory=lifecycle.run_directory,
                            runtime_identity=runtime_identity,
                            pid=pid,
                            error=error,
                        )
                except Exception as cleanup_exc:
                    raise CommissioningError(
                        f"{error}; failure closure failed: {cleanup_exc}"
                    ) from cleanup_exc
            raise error from exc

    def stop(self) -> CommissioningReceipt:
        if not self.envelope.receipt_path.is_file():
            raise CommissioningError("commissioning receipt is missing")
        existing = _read_json(self.envelope.receipt_path)
        if existing.get("status") != "COMMISSIONED":
            raise CommissioningError("stop requires a commissioned service")
        if existing.get("envelope_identity") != self.envelope.envelope_identity:
            raise CommissioningError("commissioning receipt envelope mismatch")
        runtime_identity = _identity(existing.get("runtime_identity"), "runtime_identity")
        run_directory = _absolute_path(existing.get("run_directory"), "run_directory")
        pid = _integer(existing.get("pid"), "pid")
        self._journal("STOP_INTENT", {"runtime_identity": runtime_identity})
        closure_errors: list[str] = []
        try:
            self._journal("PROBE_BOOTOUT_INTENT", {"reason": "STOP"})
            self.host.bootout_periodic_probe()
        except Exception as exc:
            closure_errors.append(f"probe bootout failed: {exc}")
        running: bool | None
        try:
            running = self.host.service_running(expected_pid=pid)
        except Exception as exc:
            running = None
            closure_errors.append(f"service liveness query failed: {exc}")
        reason = (
            "EXPLICIT_STOP"
            if running is True
            else "NATURAL_TERMINAL"
            if running is False
            else "LIVENESS_UNKNOWN"
        )
        if running is True:
            rows = _read_ledger(self.envelope.probe_ledger_path)
            final_probe_deadline_ms = self.clock.monotonic_ms() + _LIFECYCLE_WAIT_MS
            try:
                final_row = self.probe.collect(
                    self.envelope.final_probe_argv,
                    runtime_identity=runtime_identity,
                    expected_sequence=len(rows) + 1,
                    deadline_ms=final_probe_deadline_ms,
                )
                self._validate_probe(
                    final_row,
                    runtime_identity=runtime_identity,
                    pid=pid,
                    expected_sequence=len(rows) + 1,
                    expected_mode="final-online",
                    deadline_ms=final_probe_deadline_ms,
                )
            except Exception as exc:
                closure_errors.append(f"final-online probe failed: {exc}")
            try:
                self._journal("SIGINT_INTENT", {"runtime_identity": runtime_identity})
                self.host.sigint_service()
            except Exception as exc:
                closure_errors.append(f"service SIGINT failed: {exc}")
        elif running is False:
            self._journal("NATURAL_TERMINAL_CLOSE_INTENT", {"runtime_identity": runtime_identity})
        terminal_wait_error: Exception | None = None
        try:
            self.host.wait_for_terminal(
                run_directory=run_directory,
                deadline_ms=self.clock.monotonic_ms() + _TERMINAL_WAIT_MS,
            )
        except Exception as exc:
            terminal_wait_error = exc
            closure_errors.append(f"terminal wait failed: {exc}")
        if terminal_wait_error is None:
            try:
                terminal = self.audit.run(
                    self.envelope.terminal_audit_argv,
                    runtime_identity=runtime_identity,
                    deadline_ms=self.clock.monotonic_ms() + _TERMINAL_WAIT_MS,
                )
                self._validate_terminal_audit(
                    terminal,
                    runtime_identity=runtime_identity,
                    explicit_stop_probe_required=running is True,
                )
            except Exception as exc:
                closure_errors.append(f"terminal audit failed: {exc}")
        terminal_proven = terminal_wait_error is None
        if terminal_proven:
            try:
                self._journal("SERVICE_BOOTOUT_INTENT", {"reason": reason})
                self.host.bootout_service()
            except Exception as exc:
                closure_errors.append(f"service bootout failed: {exc}")
            try:
                self.host.verify_quiescent(expected_pid=pid)
            except Exception as exc:
                closure_errors.append(f"quiescence failed: {exc}")
        else:
            self._journal(
                "TERMINAL_CLOSURE_BLOCKED",
                {"runtime_identity": runtime_identity, "errors": closure_errors},
            )
        receipt = CommissioningReceipt(
            status=(
                "STOPPED_TERMINAL_AUDITED_QUIESCENT"
                if running is True and not closure_errors
                else (
                    "NATURAL_TERMINAL_AUDITED_QUIESCENT"
                    if running is False and not closure_errors
                    else "TERMINAL_CLOSURE_NOT_ACCEPTED"
                )
            ),
            runtime_identity=runtime_identity,
            pid=pid,
            run_directory=str(run_directory),
            gate_start_monotonic_ms=cast(int | None, existing.get("gate_start_monotonic_ms")),
            gate_end_monotonic_ms=cast(int | None, existing.get("gate_end_monotonic_ms")),
            envelope_identity=self.envelope.envelope_identity,
            failure_reason="; ".join(closure_errors) if closure_errors else None,
            operability=(
                cast(Mapping[str, object], existing["operability"])
                if isinstance(existing.get("operability"), Mapping)
                else None
            ),
        )
        self._write_receipt(self.envelope.stop_receipt_path, receipt)
        if closure_errors:
            raise CommissioningError("; ".join(closure_errors))
        return receipt


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommissioningError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CommissioningError(f"JSON is not an object: {path}")
    return cast(dict[str, object], value)


def _read_ledger(path: Path) -> list[dict[str, object]]:
    if not path.is_file() or path.is_symlink():
        return []
    result: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CommissioningError("probe ledger row is not an object")
            result.append(cast(dict[str, object], value))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommissioningError(f"probe ledger is unreadable: {exc}") from exc
    return result


@dataclass
class SystemClock:
    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def wall_time(self) -> float:
        return time.time()

    def sleep_until(self, deadline_ms: int) -> None:
        remaining = deadline_ms - self.monotonic_ms()
        if remaining > 0:
            time.sleep(remaining / 1000)


class SubprocessProbe:
    def __init__(self, envelope: CommissioningEnvelope, clock: Clock) -> None:
        self.envelope = envelope
        self.clock = clock

    def collect(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        expected_sequence: int,
        deadline_ms: int,
    ) -> Mapping[str, object]:
        before = _read_ledger(self.envelope.probe_ledger_path)
        if len(before) != expected_sequence - 1:
            raise CommissioningError("probe ledger pre-append sequence/count mismatch")
        timeout = max(0.001, (deadline_ms - self.clock.monotonic_ms()) / 1000)
        completed = subprocess.run(
            argv,
            cwd=self.envelope.deployment_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            raise CommissioningError(f"probe failed: {completed.returncode}: {completed.stderr}")
        rows = _read_ledger(self.envelope.probe_ledger_path)
        if len(rows) != expected_sequence or rows[:-1] != before:
            raise CommissioningError("probe ledger sequence/count mismatch")
        if rows[-1].get("runtime_identity") != runtime_identity:
            raise CommissioningError("probe appended runtime identity mismatch")
        return rows[-1]


class SubprocessAudit:
    def __init__(self, envelope: CommissioningEnvelope, clock: Clock) -> None:
        self.envelope = envelope
        self.clock = clock

    def run(
        self,
        argv: Sequence[str],
        *,
        runtime_identity: str,
        deadline_ms: int,
    ) -> Mapping[str, object]:
        del runtime_identity
        output = Path(argv[argv.index("--output") + 1])
        if output.exists() or output.is_symlink():
            raise CommissioningError(f"audit output already exists: {output}")
        timeout = max(0.001, (deadline_ms - self.clock.monotonic_ms()) / 1000)
        completed = subprocess.run(
            argv,
            cwd=self.envelope.deployment_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            raise CommissioningError(f"audit failed: {completed.returncode}: {completed.stderr}")
        if self.clock.monotonic_ms() > deadline_ms:
            raise CommissioningError("audit deadline exceeded")
        return _read_json(output)


class MacOSHost:
    def __init__(self, envelope: CommissioningEnvelope, clock: Clock) -> None:
        self.envelope = envelope
        self.clock = clock
        self._resource_start_wall: float | None = None

    def _preflight_unified_log_source(self) -> None:
        boundary = float(math.ceil(time.time()))
        remaining = boundary - time.time()
        if remaining > 0:
            time.sleep(remaining)
        log_start = datetime.fromtimestamp(boundary - 1).strftime("%Y-%m-%d %H:%M:%S")
        log_end = datetime.fromtimestamp(boundary).strftime("%Y-%m-%d %H:%M:%S")
        log_probe = self._run(
            (
                "/usr/bin/log",
                "show",
                "--style",
                "json",
                "--start",
                log_start,
                "--end",
                log_end,
                "--predicate",
                "eventMessage CONTAINS '__OPTIMATRIX_R4_PREFLIGHT_UNMATCHABLE__'",
            ),
            timeout=30,
        )
        try:
            log_probe_value = json.loads(log_probe.stdout)
        except json.JSONDecodeError as exc:
            raise CommissioningError("unified log preflight query is unreadable") from exc
        if log_probe.returncode != 0 or not isinstance(log_probe_value, list):
            raise CommissioningError("unified log preflight query failed")

    @staticmethod
    def _run(
        argv: Sequence[str],
        *,
        timeout: float = 10,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CommissioningError(f"command timeout: {' '.join(argv)}") from exc

    def _launchd(self, target: str) -> str | None:
        completed = self._run(("/bin/launchctl", "print", target))
        if completed.returncode == 0:
            if not completed.stdout.strip() or completed.stderr.strip():
                raise CommissioningError("launchd inventory is malformed")
            return completed.stdout
        if _known_absent_launchctl(completed):
            return None
        raise CommissioningError(
            f"launchd inventory failed: {completed.returncode}: {completed.stderr}"
        )

    def _listener_inventory(self) -> tuple[tuple[int, str], ...]:
        completed = self._run(
            (
                "/usr/sbin/lsof",
                "-nP",
                f"-iTCP:{self.envelope.listener_port}",
                "-sTCP:LISTEN",
                "-Fp",
                "-Fn",
            )
        )
        if completed.returncode == 1:
            if completed.stdout or completed.stderr:
                raise CommissioningError("listener inventory is indeterminate")
            return ()
        if completed.returncode != 0 or not completed.stdout.strip() or completed.stderr.strip():
            raise CommissioningError("listener inventory failed")
        result: list[tuple[int, str]] = []
        current_pid: int | None = None
        current_pid_has_listener = False
        for line in completed.stdout.splitlines():
            if re.fullmatch(r"p[1-9][0-9]*", line):
                if current_pid is not None and not current_pid_has_listener:
                    raise CommissioningError("listener inventory is malformed")
                current_pid = int(line[1:])
                current_pid_has_listener = False
            elif re.fullmatch(r"f[0-9]+", line):
                if current_pid is None:
                    raise CommissioningError("listener inventory is malformed")
            elif line.startswith("n") and len(line) > 1:
                if current_pid is None:
                    raise CommissioningError("listener inventory is malformed")
                result.append((current_pid, line[1:]))
                current_pid_has_listener = True
            else:
                raise CommissioningError("listener inventory is malformed")
        if current_pid is None or not current_pid_has_listener or not result:
            raise CommissioningError("listener inventory is malformed")
        return tuple(result)

    def preflight(self) -> None:
        if self._launchd(self.envelope.service_target) is not None:
            raise CommissioningError("service label already loaded")
        if self._launchd(self.envelope.probe_target) is not None:
            raise CommissioningError("probe label already loaded")
        if self._listener_inventory():
            raise CommissioningError("loopback port already has a listener")
        if self._matching_process_pids():
            raise CommissioningError("service process already exists")
        if self.envelope.state_root.exists():
            raise CommissioningError("state root must be absent before start")
        git_checks = {
            "commit": ("git", "rev-parse", "HEAD^{commit}"),
            "tree": ("git", "rev-parse", "HEAD^{tree}"),
            "remote_main": ("git", "rev-parse", "refs/remotes/origin/main^{commit}"),
            "status": ("git", "status", "--porcelain"),
            "branch": ("git", "symbolic-ref", "-q", "HEAD"),
        }
        git_results = {
            name: self._run(command, cwd=self.envelope.repository)
            for name, command in git_checks.items()
        }
        if (
            git_results["commit"].returncode != 0
            or git_results["commit"].stdout.strip() != self.envelope.code_identity
            or git_results["tree"].returncode != 0
            or git_results["tree"].stdout.strip() != self.envelope.remote_main_tree
            or git_results["remote_main"].returncode != 0
            or git_results["remote_main"].stdout.strip() != self.envelope.code_identity
            or git_results["status"].returncode != 0
            or git_results["status"].stdout
            or git_results["branch"].returncode != 1
        ):
            raise CommissioningError("deployment checkout Git binding mismatch")
        controller_path = (
            self.envelope.repository / "apps/radar_runtime/src/radar_runtime/commissioning.py"
        )
        bound_artifacts = (
            (
                self.envelope.repository / "docs/authority/CURRENT_STAGE.md",
                self.envelope.authority_digest,
            ),
            (
                self.envelope.repository / "tasks/SHORT_VOL_R4_COMMISSIONING_INTEGRITY_REPAIR.md",
                self.envelope.task_digest,
            ),
            (controller_path, self.envelope.controller_digest),
            (self.envelope.service_plist_path, self.envelope.service_plist_digest),
            (self.envelope.probe_plist_path, self.envelope.probe_plist_digest),
            (Path(self.envelope.manual_probe_argv[1]), self.envelope.probe_script_digest),
            (Path(self.envelope.current_audit_argv[1]), self.envelope.audit_script_digest),
            (
                self.envelope.repository / "apps/radar_runtime/src/radar_runtime/service.py",
                self.envelope.service_hot_path_digest,
            ),
            (
                self.envelope.repository
                / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md",
                self.envelope.persistent_service_contract_digest,
            ),
            (
                self.envelope.repository / "policies/short-vol-fixed-public-shadow-radar.json",
                self.envelope.radar_policy_identity,
            ),
            (
                self.envelope.repository
                / "policies/short-vol-fixed-public-shadow-underwriting.json",
                self.envelope.underwriting_policy_identity,
            ),
            (
                self.envelope.repository / "policies/short-vol-fixed-public-shadow-position.json",
                self.envelope.position_policy_identity,
            ),
        )
        artifact_paths = [path for path, _ in bound_artifacts]
        if len(set(artifact_paths)) != len(artifact_paths):
            raise CommissioningError("bound artifact paths must be distinct")
        for path, expected in bound_artifacts:
            if _file_identity(path) != expected:
                raise CommissioningError(f"bound artifact digest mismatch: {path}")
        python_path = Path(self.envelope.expected_service_argv[0])
        if _file_identity(python_path.resolve()) != self.envelope.python_executable_digest:
            raise CommissioningError("Python executable digest mismatch")
        python_version = self._run((str(python_path), "--version"), cwd=self.envelope.repository)
        observed_python_version = python_version.stdout.strip() or python_version.stderr.strip()
        if (
            python_version.returncode != 0
            or observed_python_version != self.envelope.python_version
        ):
            raise CommissioningError("Python version mismatch")
        output_paths = (
            self.envelope.state_root,
            self.envelope.journal_directory,
            self.envelope.receipt_path,
            self.envelope.stop_receipt_path,
            self.envelope.failure_closure_receipt_path,
            self.envelope.probe_ledger_path,
            *(
                Path(command[command.index("--output") + 1])
                for command in (
                    self.envelope.current_audit_argv,
                    self.envelope.operability_audit_argv,
                    self.envelope.terminal_audit_argv,
                )
            ),
        )
        if len(set(output_paths)) != len(output_paths) or any(
            path.exists() or path.is_symlink() for path in output_paths
        ):
            raise CommissioningError("attempt output paths are not fresh and distinct")
        self._validate_plists()
        for path in self.envelope.diagnostic_report_directories:
            if not path.is_dir() or not os.access(path, os.R_OK):
                raise CommissioningError("diagnostic report source is unreadable")
        inventory = {
            identity
            for directory in self.envelope.diagnostic_report_directories
            for identity in _diagnostic_inventory(directory)
        }
        if inventory != set(self.envelope.diagnostic_report_baseline):
            raise CommissioningError("diagnostic report baseline does not match current inventory")
        if not Path("/usr/bin/log").is_file():
            raise CommissioningError("unified log source is unavailable")
        self._preflight_unified_log_source()
        old_roots = {
            "r1": Path("/Users/logan/Optimatrix-public-shadow-observation"),
            "r2": Path("/Users/logan/Optimatrix-public-shadow-observation-002"),
            "r3": Path("/Users/logan/Optimatrix-public-shadow-observation-003"),
        }
        for name, root in old_roots.items():
            if (
                _directory_inventory_identity(root)
                != self.envelope.old_root_inventory_identities[name]
            ):
                raise CommissioningError(f"old root inventory changed: {name}")
            open_files = self._run(("/usr/sbin/lsof", "+D", str(root)), timeout=60)
            if open_files.returncode not in {0, 1} or open_files.stdout.strip():
                raise CommissioningError(f"old root writer/reader inventory is not empty: {name}")
        for label in (
            "com.optimatrix.public-shadow",
            "com.optimatrix.public-shadow.probe",
            "com.optimatrix.public-shadow.r2",
            "com.optimatrix.public-shadow.r2.probe",
            "com.optimatrix.public-shadow.r3",
            "com.optimatrix.public-shadow.r3.probe",
        ):
            if self._launchd(f"gui/{self.envelope.uid}/{label}") is not None:
                raise CommissioningError(f"old launchd label remains loaded: {label}")
        self._resource_start_wall = time.time()

    def _validate_plists(self) -> None:
        try:
            service = plistlib.loads(self.envelope.service_plist_path.read_bytes())
            probe = plistlib.loads(self.envelope.probe_plist_path.read_bytes())
        except (OSError, plistlib.InvalidFileException) as exc:
            raise CommissioningError(f"cannot parse installed plist: {exc}") from exc
        if not isinstance(service, dict) or not isinstance(probe, dict):
            raise CommissioningError("installed plist is not a dictionary")
        expected_service = {
            "Label": self.envelope.service_label,
            "ProgramArguments": list(self.envelope.expected_service_argv),
            "WorkingDirectory": str(self.envelope.expected_service_cwd),
            "KeepAlive": False,
            "RunAtLoad": False,
            "LaunchOnlyOnce": True,
            "StandardOutPath": str(self.envelope.deployment_root / "logs/service.stdout.log"),
            "StandardErrorPath": str(self.envelope.deployment_root / "logs/service.stderr.log"),
        }
        expected_probe = {
            "Label": self.envelope.probe_label,
            "ProgramArguments": list(self.envelope.manual_probe_argv),
            "WorkingDirectory": str(self.envelope.deployment_root),
            "KeepAlive": False,
            "RunAtLoad": False,
            "StartInterval": 60,
            "StandardOutPath": str(self.envelope.deployment_root / "logs/probe.stdout.log"),
            "StandardErrorPath": str(self.envelope.deployment_root / "logs/probe.stderr.log"),
        }
        for label, value, expected in (
            ("service", service, expected_service),
            ("probe", probe, expected_probe),
        ):
            if set(value) != set(expected) or any(
                value.get(key) != exact for key, exact in expected.items()
            ):
                raise CommissioningError(f"{label} plist semantic mismatch")
        for path in (self.envelope.service_plist_path, self.envelope.probe_plist_path):
            stat = path.stat()
            if stat.st_uid != self.envelope.uid or stat.st_mode & 0o777 != 0o600:
                raise CommissioningError("installed plist owner/mode mismatch")

    def _effect(self, argv: Sequence[str], label: str, *, allow_absent: bool = False) -> None:
        completed = self._run(argv)
        if completed.returncode != 0:
            if allow_absent and _known_absent_launchctl(completed):
                return
            raise CommissioningError(f"{label} failed: {completed.returncode}: {completed.stderr}")

    def bootstrap_service(self) -> None:
        self._effect(self.envelope.service_bootstrap_argv, "service bootstrap")

    def kickstart_service(self) -> None:
        self._effect(self.envelope.service_kickstart_argv, "service kickstart")

    def wait_for_lifecycle(self, *, deadline_ms: int) -> LifecycleObservation:
        while self.clock.monotonic_ms() <= deadline_ms:
            runs = self.envelope.state_root / "runs"
            entries = (
                tuple(path for path in runs.iterdir() if path.is_dir() and not path.is_symlink())
                if runs.is_dir() and not runs.is_symlink()
                else ()
            )
            if len(entries) == 1:
                event_directory = entries[0] / "service/events"
                events = (
                    tuple(sorted(event_directory.glob("*.json")))
                    if event_directory.is_dir()
                    else ()
                )
                if events:
                    return LifecycleObservation(
                        run_directory=entries[0],
                        event=_read_json(events[0]),
                        observed_monotonic_ms=self.clock.monotonic_ms(),
                    )
            time.sleep(0.1)
        raise CommissioningError("lifecycle deadline exceeded")

    def _pid_runs(self) -> tuple[int, int]:
        output = self._launchd(self.envelope.service_target)
        if output is None:
            raise CommissioningError("service label is absent")
        pid_match = re.search(r"(?m)^\s*pid = ([1-9][0-9]*)\s*$", output)
        runs_match = re.search(r"(?m)^\s*runs = ([0-9]+)\s*$", output)
        if pid_match is None or runs_match is None:
            raise CommissioningError("launchd pid/runs are missing")
        return int(pid_match.group(1)), int(runs_match.group(1))

    def current_service_pid(self) -> int:
        pid, _runs = self._pid_runs()
        return pid

    def service_running(self, *, expected_pid: int) -> bool:
        output = self._launchd(self.envelope.service_target)
        if output is None:
            return False
        pid_match = re.search(r"(?m)^\s*pid = ([1-9][0-9]*)\s*$", output)
        if pid_match is None:
            raise CommissioningError("service launchd PID inventory is malformed")
        observed_pid = int(pid_match.group(1))
        if observed_pid != expected_pid:
            raise CommissioningError("service PID changed before terminal closure")
        completed = self._run(("/bin/ps", "-p", str(expected_pid), "-o", "pid="))
        if (
            completed.returncode == 1
            and not completed.stdout.strip()
            and not completed.stderr.strip()
        ):
            return False
        if (
            completed.returncode != 0
            or completed.stdout.strip() != str(expected_pid)
            or completed.stderr.strip()
        ):
            raise CommissioningError("service PID liveness query failed")
        return True

    def _matching_process_pids(self) -> tuple[int, ...]:
        completed = self._run(("/bin/ps", "-axo", "pid=,command="))
        if completed.returncode != 0 or not completed.stdout.strip() or completed.stderr.strip():
            raise CommissioningError("service process inventory failed")
        expected = " ".join(self.envelope.expected_service_argv)
        result: list[int] = []
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            pid_text, separator, command = stripped.partition(" ")
            if (
                not separator
                or re.fullmatch(r"[1-9][0-9]*", pid_text) is None
                or not command.strip()
            ):
                raise CommissioningError("service process inventory is malformed")
            if " ".join(command.split()) == expected:
                result.append(int(pid_text))
        return tuple(result)

    def _process(self, pid: int) -> tuple[tuple[str, ...], Path, int, int]:
        completed = self._run(("/bin/ps", "-p", str(pid), "-o", "rss=,time=,command="))
        if completed.returncode != 0 or not completed.stdout.strip():
            raise CommissioningError("service process is absent")
        fields = completed.stdout.strip().split(None, 2)
        if len(fields) != 3:
            raise CommissioningError("service process shape mismatch")
        rss_bytes = int(fields[0]) * 1024
        cpu_time_ms = _parse_cpu_time_ms(fields[1])
        command = tuple(fields[2].split())
        cwd_result = self._run(("/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"))
        if cwd_result.returncode != 0:
            raise CommissioningError("service cwd inventory failed")
        cwd_values = tuple(
            line[1:] for line in cwd_result.stdout.splitlines() if line.startswith("n")
        )
        if len(cwd_values) != 1:
            raise CommissioningError("service cwd is unavailable")
        return command, Path(cwd_values[0]), rss_bytes, cpu_time_ms

    def _http(self, path: str) -> tuple[dict[str, object], int]:
        started = self.clock.monotonic_ms()
        request = urllib.request.Request(
            f"http://{_LOOPBACK_HOST}:{_LOOPBACK_PORT}{path}",
            headers={"Accept": "application/json", "Cache-Control": "no-store"},
            method="GET",
        )
        status: int
        body: bytes
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                body = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read(2_000_001)
        if len(body) > 2_000_000:
            raise CommissioningError("HTTP response exceeds bound")
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommissioningError("HTTP response is not JSON") from exc
        if not isinstance(value, dict):
            raise CommissioningError("HTTP response is not an object")
        result = cast(dict[str, object], value)
        if "status" in result:
            raise CommissioningError("HTTP response body contains reserved status field")
        result["status"] = status
        return result, self.clock.monotonic_ms() - started

    def inspect_commissioning(
        self, *, runtime_identity: str, run_directory: Path, deadline_ms: int
    ) -> CommissioningObservation:
        pid, runs = self._pid_runs()
        if self._matching_process_pids() != (pid,):
            raise CommissioningError("service process is not globally unique")
        argv, cwd, _rss, _cpu = self._process(pid)
        listeners = self._listener_inventory()
        health, _ = self._http("/healthz")
        ready, _ = self._http("/readyz")
        workbench, _ = self._http("/api/workbench/current")
        _validate_http_documents(
            self.envelope,
            runtime_identity=runtime_identity,
            health=health,
            ready=ready,
            workbench=workbench,
            observed_monotonic_ms=self.clock.monotonic_ms(),
        )
        expected_run = self.envelope.state_root / "runs" / runtime_identity.removeprefix("sha256:")
        if run_directory != expected_run or self.clock.monotonic_ms() > deadline_ms:
            raise CommissioningError("commissioning run/deadline mismatch")
        return CommissioningObservation(
            pid=pid,
            launchd_runs=runs,
            argv=argv,
            cwd=cwd,
            listeners=listeners,
            healthz=health,
            readyz=ready,
            workbench=workbench,
            observed_monotonic_ms=self.clock.monotonic_ms(),
        )

    def bootstrap_periodic_probe(self) -> None:
        self._effect(self.envelope.probe_bootstrap_argv, "probe bootstrap")

    def inspect_resource_events(
        self,
        *,
        pid: int,
        query_start_wall: float,
        query_end_wall: float,
    ) -> ResourceEventObservation:
        query_start_second = math.floor(query_start_wall)
        query_end_second = math.ceil(query_end_wall)
        remaining = query_end_wall - time.time()
        if remaining > 0:
            time.sleep(remaining)
        baseline = set(self.envelope.diagnostic_report_baseline)
        new_reports: list[Path] = []
        readable = True
        for directory in self.envelope.diagnostic_report_directories:
            try:
                current_inventory = _diagnostic_inventory(directory)
                new_reports.extend(
                    path
                    for identity, path in current_inventory.items()
                    if identity not in baseline
                    and query_start_wall
                    <= path.stat().st_mtime_ns / 1_000_000_000
                    <= query_end_wall
                )
            except OSError:
                readable = False
        exact_pid_events = 0
        for path in new_reports:
            if "cpu_resource" not in path.name.lower():
                continue
            try:
                report = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                readable = False
                continue
            report_pid = re.search(r"(?m)^PID:\s+([1-9][0-9]*)\s*$", report)
            if report_pid is None:
                readable = False
            elif int(report_pid.group(1)) == pid:
                exact_pid_events += 1
        query_start_text = datetime.fromtimestamp(query_start_wall, tz=UTC).isoformat(
            timespec="microseconds"
        )
        query_end_text = datetime.fromtimestamp(query_end_wall, tz=UTC).isoformat(
            timespec="microseconds"
        )
        query_start_argument = datetime.fromtimestamp(query_start_second).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        query_end_argument = datetime.fromtimestamp(query_end_second).strftime("%Y-%m-%d %H:%M:%S")
        log_result = self._run(
            (
                "/usr/bin/log",
                "show",
                "--style",
                "json",
                "--start",
                query_start_argument,
                "--end",
                query_end_argument,
                "--predicate",
                "eventMessage CONTAINS[c] 'cpu' OR eventMessage CONTAINS[c] 'resource'",
            ),
            timeout=30,
        )
        unified_rows: list[object] = []
        if log_result.returncode != 0:
            readable = False
        elif log_result.stdout.strip():
            try:
                loaded_rows = json.loads(log_result.stdout)
            except json.JSONDecodeError:
                readable = False
            else:
                if not isinstance(loaded_rows, list):
                    readable = False
                else:
                    pid_pattern = re.compile(rf"(?<![0-9]){pid}(?![0-9])")
                    for raw_row in loaded_rows:
                        if not isinstance(raw_row, Mapping):
                            readable = False
                            continue
                        timestamp = raw_row.get("timestamp")
                        if not isinstance(timestamp, str):
                            readable = False
                            continue
                        try:
                            observed_wall = datetime.strptime(
                                timestamp, "%Y-%m-%d %H:%M:%S.%f%z"
                            ).timestamp()
                        except ValueError:
                            readable = False
                            continue
                        if not query_start_wall <= observed_wall <= query_end_wall:
                            continue
                        unified_rows.append(raw_row)
                        message = raw_row.get("eventMessage")
                        if not isinstance(message, str):
                            continue
                        lowered = message.lower()
                        resource_event = "resource" in lowered or "burning cpu" in lowered
                        if resource_event and pid_pattern.search(message):
                            exact_pid_events += 1
                        elif resource_event and self.envelope.service_label in message:
                            readable = False
        return ResourceEventObservation(
            sources_readable=readable,
            exact_pid_event_count=exact_pid_events,
            query_start_wall_utc=query_start_text,
            query_end_wall_utc=query_end_text,
            diagnostic_report_count_examined=len(new_reports),
            unified_log_row_count_examined=len(unified_rows),
        )

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
        start_pid, start_runs = self._pid_runs()
        if start_pid != pid or start_runs != 1 or self._matching_process_pids() != (pid,):
            raise CommissioningError("service identity changed at operability gate start")
        start_argv, start_cwd, _initial_rss, initial_cpu = self._process(pid)
        if (
            start_argv != self.envelope.expected_service_argv
            or start_cwd != self.envelope.expected_service_cwd
            or self._listener_inventory()
            != ((pid, f"{self.envelope.listener_host}:{self.envelope.listener_port}"),)
        ):
            raise CommissioningError("service shape changed at operability gate start")
        start_health, start_health_latency = self._http("/healthz")
        start_ready, start_ready_latency = self._http("/readyz")
        start_workbench, start_workbench_latency = self._http("/api/workbench/current")
        start_readiness, start_data_state = _validate_http_documents(
            self.envelope,
            runtime_identity=runtime_identity,
            health=start_health,
            ready=start_ready,
            workbench=start_workbench,
            observed_monotonic_ms=self.clock.monotonic_ms(),
        )
        self.clock.sleep_until(gate_end_monotonic_ms)
        current_pid, runs = self._pid_runs()
        if current_pid != pid or runs != 1 or self._matching_process_pids() != (pid,):
            raise CommissioningError("service identity changed at operability gate end")
        final_argv, final_cwd, rss, final_cpu = self._process(current_pid)
        if (
            final_argv != self.envelope.expected_service_argv
            or final_cwd != self.envelope.expected_service_cwd
            or self._listener_inventory()
            != ((pid, f"{self.envelope.listener_host}:{self.envelope.listener_port}"),)
        ):
            raise CommissioningError("service shape changed at operability gate end")
        end_health, end_health_latency = self._http("/healthz")
        end_ready, end_ready_latency = self._http("/readyz")
        end_workbench, end_workbench_latency = self._http("/api/workbench/current")
        end_readiness, end_data_state = _validate_http_documents(
            self.envelope,
            runtime_identity=runtime_identity,
            health=end_health,
            ready=end_ready,
            workbench=end_workbench,
            observed_monotonic_ms=self.clock.monotonic_ms(),
        )
        latencies = [
            start_health_latency,
            start_ready_latency,
            start_workbench_latency,
            end_health_latency,
            end_ready_latency,
            end_workbench_latency,
        ]
        rows = _read_ledger(self.envelope.probe_ledger_path)
        if len(rows) < 3:
            raise CommissioningError("operability ledger has fewer than three rows")
        periodic_times: list[int] = []
        readiness_states = [start_readiness]
        data_states = [start_data_state]
        currentness_reasons = [
            cast(
                str,
                cast(Mapping[str, object], start_workbench["system"])["coverage_blocking_reason"],
            )
        ]
        exact_pid_events = 0
        for sequence, row in enumerate(rows, start=1):
            monotonic = _validate_probe_row(
                self.envelope,
                row,
                runtime_identity=runtime_identity,
                pid=pid,
                expected_sequence=sequence,
                expected_mode="periodic",
            )
            exact_pid_events += cast(int, row["new_exact_pid_cpu_resource_event_count"])
            row_workbench = cast(Mapping[str, object], row["workbench"])
            row_service = cast(Mapping[str, object], row_workbench["service"])
            readiness_states.append(cast(bool, row_service["ready"]))
            data_states.append(cast(str, row_service["data_state"]))
            row_system = cast(Mapping[str, object], row_workbench["system"])
            currentness_reasons.append(cast(str, row_system["coverage_blocking_reason"]))
            if sequence > 1 and gate_start_monotonic_ms < monotonic <= gate_end_monotonic_ms:
                periodic_times.append(monotonic)
        readiness_states.append(end_readiness)
        data_states.append(end_data_state)
        currentness_reasons.append(
            cast(
                str, cast(Mapping[str, object], end_workbench["system"])["coverage_blocking_reason"]
            )
        )
        all_operational = all(row.get("operational_success") is True for row in rows)
        self.clock.sleep_until(resource_audit_boundary_monotonic_ms)
        if self._resource_start_wall is None:
            raise CommissioningError("resource audit cursor is not initialized")
        resources = self.inspect_resource_events(
            pid=pid,
            query_start_wall=self._resource_start_wall,
            query_end_wall=resource_query_end_wall,
        )
        exact_pid_events += resources.exact_pid_event_count
        elapsed_ms = gate_end_monotonic_ms - gate_start_monotonic_ms
        cpu_delta_ms = final_cpu - initial_cpu
        cpu_utilization_percent = (
            f"{(cpu_delta_ms * 100 / elapsed_ms):.6f}" if elapsed_ms > 0 else ""
        )
        queue_lag_flags = [reason == "QUEUE_LAG_CURRENTNESS" for reason in currentness_reasons]
        queue_lag_transitions = sum(before != after for before, after in pairwise(queue_lag_flags))
        return OperabilityObservation(
            pid=current_pid,
            runtime_identity=runtime_identity,
            launchd_runs=runs,
            covered_from_monotonic_ms=gate_start_monotonic_ms,
            covered_until_monotonic_ms=gate_end_monotonic_ms,
            periodic_row_monotonic_ms=tuple(periodic_times),
            all_probe_attempts_operational=all_operational,
            cpu_time_delta_ms=cpu_delta_ms,
            elapsed_monotonic_ms=elapsed_ms,
            cpu_utilization_percent=cpu_utilization_percent,
            rss_bytes=rss,
            max_http_latency_ms=max(latencies),
            http_attempt_count=9 + len(rows) * 3,
            http_success_count=9 + len(rows) * 3,
            readiness_states=tuple(readiness_states),
            data_states=tuple(data_states),
            queue_lag_transition_count=queue_lag_transitions,
            resource_sources_readable=resources.sources_readable,
            resource_audit_boundary_monotonic_ms=self.clock.monotonic_ms(),
            resource_query_start_wall_utc=resources.query_start_wall_utc,
            resource_query_end_wall_utc=resources.query_end_wall_utc,
            diagnostic_report_count_examined=resources.diagnostic_report_count_examined,
            unified_log_row_count_examined=resources.unified_log_row_count_examined,
            new_exact_pid_cpu_resource_event_count=exact_pid_events,
        )

    def _wait_for_launchd_absence(self, *, target: str, label: str) -> None:
        deadline_ms = self.clock.monotonic_ms() + _TEARDOWN_CONVERGENCE_MS
        while True:
            inventory = self._launchd(target)
            observed_ms = self.clock.monotonic_ms()
            if observed_ms > deadline_ms:
                raise CommissioningError(f"{label} did not unload before deadline")
            if inventory is None:
                return
            if observed_ms >= deadline_ms:
                raise CommissioningError(f"{label} did not unload before deadline")
            self.clock.sleep_until(min(deadline_ms, observed_ms + _TEARDOWN_POLL_MS))

    def bootout_periodic_probe(self) -> None:
        self._effect(self.envelope.probe_bootout_argv, "probe bootout", allow_absent=True)
        self._wait_for_launchd_absence(
            target=self.envelope.probe_target,
            label="probe label",
        )

    def sigint_service(self) -> None:
        self._effect(self.envelope.service_sigint_argv, "service SIGINT")

    def wait_for_terminal(self, *, run_directory: Path, deadline_ms: int) -> None:
        terminal = run_directory / "service/terminal.json"
        while self.clock.monotonic_ms() <= deadline_ms:
            if terminal.is_file() and not terminal.is_symlink():
                return
            time.sleep(0.1)
        raise CommissioningError("terminal deadline exceeded")

    def bootout_service(self) -> None:
        self._effect(self.envelope.service_bootout_argv, "service bootout", allow_absent=True)
        self._wait_for_launchd_absence(
            target=self.envelope.service_target,
            label="service label",
        )

    def _original_pid_present(self, expected_pid: int) -> bool:
        completed = self._run(("/bin/ps", "-p", str(expected_pid), "-o", "pid="))
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if completed.returncode == 0 and stdout == str(expected_pid) and not stderr:
            return True
        if completed.returncode == 1 and not stdout and not stderr:
            return False
        raise CommissioningError("original PID absence query is malformed or indeterminate")

    def verify_quiescent(self, *, expected_pid: int | None) -> None:
        deadline_ms = self.clock.monotonic_ms() + _TEARDOWN_CONVERGENCE_MS
        while True:
            service_loaded = self._launchd(self.envelope.service_target) is not None
            probe_loaded = self._launchd(self.envelope.probe_target) is not None
            listeners = self._listener_inventory()
            matching_processes = self._matching_process_pids()
            original_pid_present = (
                self._original_pid_present(expected_pid) if expected_pid is not None else False
            )
            observed_ms = self.clock.monotonic_ms()
            if observed_ms > deadline_ms:
                raise CommissioningError("quiescence did not converge before deadline")
            if not (
                service_loaded
                or probe_loaded
                or listeners
                or matching_processes
                or original_pid_present
            ):
                return
            if observed_ms >= deadline_ms:
                raise CommissioningError("quiescence did not converge before deadline")
            self.clock.sleep_until(min(deadline_ms, observed_ms + _TEARDOWN_POLL_MS))


def _write_exclusive_mapping(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(value)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CommissioningError(f"output already exists: {path}") from exc
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _bound_wrapper_context(
    envelope_path: Path,
) -> tuple[
    CommissioningEnvelope,
    Path,
    Mapping[str, object],
    str,
    PersistentServiceBindings,
    RuntimeBindings,
]:
    envelope = CommissioningEnvelope.from_mapping(_read_json(envelope_path))
    kickstart = _read_json(envelope.journal_directory / "KICKSTART_INTENT.json")
    if not (
        kickstart.get("intent") == "KICKSTART_INTENT"
        and kickstart.get("envelope_identity") == envelope.envelope_identity
    ):
        raise CommissioningError("wrapper envelope/journal binding mismatch")
    inventory = _state_inventory(envelope.state_root)
    runs = cast(list[object], inventory["run_directories"])
    if len(runs) != 1 or inventory["unexpected_run_entries"] != []:
        raise CommissioningError("wrapper requires one exact run directory")
    run_directory = envelope.state_root / "runs" / cast(str, runs[0])
    event_directory = run_directory / "service/events"
    event_paths = (
        sorted(event_directory.iterdir(), key=lambda path: path.name)
        if event_directory.is_dir() and not event_directory.is_symlink()
        else []
    )
    if not event_paths or any(
        not path.is_file() or path.is_symlink() or path.suffix != ".json" for path in event_paths
    ):
        raise CommissioningError("wrapper lifecycle inventory is invalid")
    first = _read_json(event_paths[0])
    service_bindings, downstream_bindings = _bindings_from_event(envelope, first)
    runtime_identity = service_bindings.runtime_identity
    if run_directory.name != runtime_identity.removeprefix("sha256:"):
        raise CommissioningError("wrapper run/runtime identity mismatch")
    evidence = read_current_persistent_service_evidence(
        run_directory,
        bindings=service_bindings,
        downstream_bindings=downstream_bindings,
    )
    if not evidence.events or dict(evidence.events[0]) != first:
        raise CommissioningError("wrapper current-reader lifecycle mismatch")
    return (
        envelope,
        run_directory,
        first,
        runtime_identity,
        service_bindings,
        downstream_bindings,
    )


def _append_probe_row(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(row)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise CommissioningError("short probe ledger append")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _record_probe_failure(
    *,
    envelope_path: Path,
    mode: str,
    error: Exception,
) -> None:
    root = envelope_path.parent.parent
    monotonic_ms = time.monotonic_ns() // 1_000_000
    marker = root / "probe/failures" / f"{monotonic_ms:020d}-{mode}.json"
    value: dict[str, object] = {
        "schema_version": 1,
        "record_kind": "UNLEDGERED_EXPLICIT_FAILED_PROBE_ROW",
        "mode": mode,
        "wall_time_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
        "monotonic_ms": monotonic_ms,
        "error_type": type(error).__name__,
        "error": str(error),
        "operational_success": False,
    }
    try:
        _write_exclusive_mapping(marker, value)
        marker_status = "PASS"
    except Exception:
        marker_status = "FAIL"
    print(
        "UNLEDGERED_EXPLICIT_FAILED_PROBE_ROW "
        + json.dumps(
            {**value, "marker_write_status": marker_status},
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
        flush=True,
    )


def production_probe_main(
    argv: Sequence[str] | None = None,
    *,
    envelope_path: Path = _PRODUCTION_ENVELOPE,
) -> int:
    parser = argparse.ArgumentParser(description="Read-only r4 persistent-service probe")
    parser.add_argument("--mode", choices=("periodic", "final-online"), required=True)
    arguments = parser.parse_args(argv)
    try:
        (
            envelope,
            _run_directory,
            first_event,
            runtime_identity,
            _service_bindings,
            _downstream_bindings,
        ) = _bound_wrapper_context(envelope_path.resolve())
        if (
            arguments.mode == "final-online"
            and not (envelope.journal_directory / "STOP_INTENT.json").is_file()
        ):
            raise CommissioningError("final-online probe requires durable STOP_INTENT")
        lock_path = envelope.probe_ledger_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            before = _read_ledger(envelope.probe_ledger_path)
            sequence = len(before) + 1
            clock = SystemClock()
            host = MacOSHost(envelope, clock)
            pid, runs = host._pid_runs()
            if runs != 1 or host._matching_process_pids() != (pid,):
                raise CommissioningError("probe service PID/runs/process uniqueness mismatch")
            process_argv, process_cwd, rss_bytes, cpu_time_ms = host._process(pid)
            listeners = host._listener_inventory()
            health, _health_latency = host._http("/healthz")
            ready, _ready_latency = host._http("/readyz")
            workbench, _workbench_latency = host._http("/api/workbench/current")
            bootstrap_intent = _read_json(
                envelope.journal_directory / "SERVICE_BOOTSTRAP_INTENT.json"
            )
            start_wall = datetime.fromisoformat(
                _string(
                    bootstrap_intent.get("wall_time_utc"),
                    "service bootstrap wall_time_utc",
                )
            ).timestamp()
            resources = host.inspect_resource_events(
                pid=pid,
                query_start_wall=start_wall,
                query_end_wall=time.time(),
            )
            monotonic_ms = clock.monotonic_ms()
            _validate_http_documents(
                envelope,
                runtime_identity=runtime_identity,
                health=health,
                ready=ready,
                workbench=workbench,
                observed_monotonic_ms=monotonic_ms,
            )
            row: dict[str, object] = {
                "schema_version": 1,
                "sequence": sequence,
                "mode": arguments.mode,
                "wall_time_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
                "monotonic_ms": monotonic_ms,
                "service_label": envelope.service_label,
                "launchd_pid": pid,
                "process": {
                    "matching_process_count": 1,
                    "matching_pids": [pid],
                    "pid": pid,
                    "argv": list(process_argv),
                    "cwd": str(process_cwd),
                    "listeners": [list(item) for item in listeners],
                    "rss_bytes": rss_bytes,
                    "cpu_time_ms": cpu_time_ms,
                },
                "inventory": _state_inventory(envelope.state_root),
                "runtime_identity": runtime_identity,
                "expected_runtime_identity": runtime_identity,
                "runtime_identity_frozen": True,
                "lifecycle_event_sequence": first_event["event_sequence"],
                "healthz": dict(health),
                "readyz": dict(ready),
                "workbench": dict(workbench),
                "resource_sources_readable": resources.sources_readable,
                "new_exact_pid_cpu_resource_event_count": resources.exact_pid_event_count,
                "errors": [],
                "operational_success": True,
            }
            _validate_probe_row(
                envelope,
                row,
                runtime_identity=runtime_identity,
                pid=pid,
                expected_sequence=sequence,
                expected_mode=arguments.mode,
            )
            _append_probe_row(envelope.probe_ledger_path, row)
            after = _read_ledger(envelope.probe_ledger_path)
            if after[:-1] != before or after[-1] != row:
                raise CommissioningError("probe ledger append was not exact")
        finally:
            os.close(lock_descriptor)
    except Exception as exc:
        _record_probe_failure(envelope_path=envelope_path, mode=arguments.mode, error=exc)
        return 1
    return 0


def _probe_evaluation(
    envelope: CommissioningEnvelope,
    *,
    runtime_identity: str,
    pid: int | None,
    startup_monotonic_ms: int,
    complete: bool,
    terminal_monotonic_ms: int | None,
    explicit_live_stop: bool,
) -> dict[str, object]:
    rows = _read_ledger(envelope.probe_ledger_path)
    errors: dict[str, str] = {}
    valid_rows = 0
    for sequence, row in enumerate(rows, start=1):
        expected_mode = (
            "final-online"
            if complete and explicit_live_stop and sequence == len(rows)
            else "periodic"
        )
        try:
            if pid is None:
                raise CommissioningError("probe PID binding is unavailable")
            _validate_probe_row(
                envelope,
                row,
                runtime_identity=runtime_identity,
                pid=pid,
                expected_sequence=sequence,
                expected_mode=expected_mode,
            )
        except CommissioningError as exc:
            errors[str(sequence)] = str(exc)
        else:
            valid_rows += 1
    times = [cast(int, row["monotonic_ms"]) for row in rows if type(row.get("monotonic_ms")) is int]
    first_delay = times[0] - startup_monotonic_ms if times else None
    gaps = [later - earlier for earlier, later in pairwise(times)]
    continuous_partition = [startup_monotonic_ms, *times]
    if complete and terminal_monotonic_ms is not None:
        continuous_partition.append(terminal_monotonic_ms)
    continuous_gaps = [later - earlier for earlier, later in pairwise(continuous_partition)]
    failure_directory = envelope.probe_ledger_path.parent / "failures"
    failure_markers = (
        sorted(path.name for path in failure_directory.iterdir())
        if failure_directory.is_dir() and not failure_directory.is_symlink()
        else []
    )
    stderr_path = envelope.deployment_root / "logs/probe.stderr.log"
    stderr_sentinels = 0
    if stderr_path.is_file() and not stderr_path.is_symlink():
        stderr_sentinels = sum(
            line.startswith("UNLEDGERED_EXPLICIT_FAILED_PROBE_ROW ")
            for line in stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    modes = [row.get("mode") for row in rows]
    expected_modes = ["periodic"] * len(rows)
    if complete and explicit_live_stop and expected_modes:
        expected_modes[-1] = "final-online"
    return {
        "row_count": len(rows),
        "contiguous_sequence": all(
            row.get("sequence") == sequence for sequence, row in enumerate(rows, start=1)
        ),
        "all_operational_success": bool(rows)
        and all(row.get("operational_success") is True for row in rows),
        "all_rows_contract_valid": valid_rows == len(rows),
        "row_contract_errors": errors,
        "first_probe_delay_ms": first_delay,
        "first_probe_within_limit": first_delay is not None
        and 0 <= first_delay <= _MANUAL_PROBE_MS,
        "hard_first_probe_within_limit": first_delay is not None
        and 0 <= first_delay <= _HARD_PROBE_MS,
        "mode_sequence_valid": modes == expected_modes,
        "monotonic_valid": len(times) == len(rows)
        and all(later >= earlier for earlier, later in pairwise(times)),
        "max_probe_gap_ms": max(gaps, default=0),
        "continuous_partition_monotonic_valid": all(
            later >= earlier for earlier, later in pairwise(continuous_partition)
        ),
        "continuous_partition_max_gap_ms": max(continuous_gaps, default=0),
        "failure_marker_count": len(failure_markers),
        "failure_markers": failure_markers,
        "stderr_failure_sentinel_count": stderr_sentinels,
        "endpoint_success": {
            name: {
                "successful_response_count": valid_rows,
                "recorded_probe_row_count": len(rows),
            }
            for name in ("healthz", "readyz", "workbench")
        },
    }


def _operability_evaluation(
    envelope: CommissioningEnvelope,
    *,
    runtime_identity: str,
    pid: int | None,
) -> dict[str, object]:
    start_path = envelope.journal_directory / "HOST_OPERABILITY_GATE_START.json"
    result_path = envelope.journal_directory / "HOST_OPERABILITY_GATE_RESULT.json"
    if (
        not start_path.is_file()
        or start_path.is_symlink()
        or not result_path.is_file()
        or result_path.is_symlink()
    ):
        return {"present": False, "valid": False}
    start = _read_json(start_path)
    result = _read_json(result_path)
    value = result.get("operability")
    if not isinstance(value, Mapping):
        return {"present": True, "valid": False}
    gate_start = start.get("gate_start_monotonic_ms")
    gate_end = start.get("gate_end_monotonic_ms")
    resource_boundary = start.get("resource_audit_boundary_monotonic_ms")
    resource_query_end_wall_utc = start.get("resource_query_end_wall_utc")
    ledger = _read_ledger(envelope.probe_ledger_path)
    rows = [
        cast(int, row["monotonic_ms"])
        for row in ledger[1:]
        if type(row.get("monotonic_ms")) is int
        and type(gate_start) is int
        and type(gate_end) is int
        and gate_start < cast(int, row["monotonic_ms"]) <= gate_end
    ]
    partition = (
        [gate_start, *rows, gate_end] if type(gate_start) is int and type(gate_end) is int else []
    )
    recomputed_gaps = [later - earlier for earlier, later in pairwise(partition)]
    elapsed = value.get("elapsed_monotonic_ms")
    cpu_delta = value.get("cpu_time_delta_ms")
    expected_cpu_percent = (
        f"{(cpu_delta * 100 / elapsed):.6f}"
        if type(cpu_delta) is int and type(elapsed) is int and elapsed > 0
        else None
    )
    valid = bool(
        start.get("envelope_identity") == envelope.envelope_identity
        and result.get("envelope_identity") == envelope.envelope_identity
        and start.get("runtime_identity") == runtime_identity
        and result.get("runtime_identity") == runtime_identity
        and value.get("runtime_identity") == runtime_identity
        and value.get("pid") == pid
        and value.get("launchd_runs") == 1
        and type(gate_start) is int
        and type(gate_end) is int
        and gate_end - gate_start == _OPERABILITY_MS
        and resource_boundary == gate_end + _RESOURCE_GRACE_MS
        and isinstance(resource_query_end_wall_utc, str)
        and value.get("resource_query_end_wall_utc") == resource_query_end_wall_utc
        and value.get("gate_start_monotonic_ms") == gate_start
        and value.get("gate_end_monotonic_ms") == gate_end
        and value.get("covered_duration_ms") == _OPERABILITY_MS
        and len(rows) >= 2
        and value.get("periodic_row_monotonic_ms") == rows
        and value.get("partition_gap_ms") == recomputed_gaps
        and all(0 <= gap <= _MAX_PERIODIC_GAP_MS for gap in recomputed_gaps)
        and value.get("elapsed_monotonic_ms") == _OPERABILITY_MS
        and value.get("cpu_utilization_percent") == expected_cpu_percent
        and value.get("cpu_utilization_denominator") == "one_process_elapsed_monotonic_ms"
        and type(value.get("rss_bytes")) is int
        and cast(int, value["rss_bytes"]) > 0
        and type(value.get("max_http_latency_ms")) is int
        and cast(int, value["max_http_latency_ms"]) >= 0
        and value.get("resource_sources_readable") is True
        and type(value.get("resource_audit_boundary_monotonic_ms")) is int
        and cast(int, value["resource_audit_boundary_monotonic_ms"]) >= resource_boundary
        and value.get("new_exact_pid_cpu_resource_event_count") == 0
        and type(value.get("http_attempt_count")) is int
        and cast(int, value["http_attempt_count"]) > 0
        and value.get("http_success_count") == value.get("http_attempt_count")
    )
    return {"present": True, "valid": valid, "facts": dict(value)}


def production_audit_main(
    argv: Sequence[str] | None = None,
    *,
    envelope_path: Path = _PRODUCTION_ENVELOPE,
) -> int:
    parser = argparse.ArgumentParser(description="Independent r4 persistent-service audit")
    parser.add_argument("--mode", choices=("current", "complete"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        (
            envelope,
            run_directory,
            first_event,
            runtime_identity,
            service_bindings,
            downstream_bindings,
        ) = _bound_wrapper_context(envelope_path.resolve())
        output_path = arguments.output.resolve()
        expected_current_outputs = {
            Path(envelope.current_audit_argv[envelope.current_audit_argv.index("--output") + 1]),
            Path(
                envelope.operability_audit_argv[
                    envelope.operability_audit_argv.index("--output") + 1
                ]
            ),
        }
        expected_terminal_output = Path(
            envelope.terminal_audit_argv[envelope.terminal_audit_argv.index("--output") + 1]
        )
        if (arguments.mode == "current" and output_path not in expected_current_outputs) or (
            arguments.mode == "complete" and output_path != expected_terminal_output
        ):
            raise CommissioningError("audit output path/mode is not envelope-bound")
        complete = arguments.mode == "complete"
        evidence = (
            read_complete_persistent_service_evidence(
                run_directory,
                bindings=service_bindings,
                downstream_bindings=downstream_bindings,
            )
            if complete
            else read_current_persistent_service_evidence(
                run_directory,
                bindings=service_bindings,
                downstream_bindings=downstream_bindings,
            )
        )
        receipt = (
            _read_json(envelope.receipt_path)
            if envelope.receipt_path.is_file() and not envelope.receipt_path.is_symlink()
            else {}
        )
        pid_value = receipt.get("pid")
        if pid_value is not None:
            pid = _integer(pid_value, "receipt pid")
        else:
            pid_binding_path = envelope.journal_directory / "RUNTIME_PID_BINDING.json"
            if pid_binding_path.is_file() and not pid_binding_path.is_symlink():
                pid = _integer(_read_json(pid_binding_path).get("pid"), "runtime PID binding")
            elif complete:
                pid = None
            else:
                pid = MacOSHost(envelope, SystemClock()).current_service_pid()
        clean_stop = bool(
            complete
            and evidence.terminal is not None
            and evidence.terminal.get("terminal_disposition") == "CLEAN_STOP"
        )
        terminal_boundary = (
            evidence.terminal.get("terminal_fact_boundary")
            if complete and isinstance(evidence.terminal, Mapping)
            else None
        )
        terminal_ms = (
            _integer(terminal_boundary.get("received_monotonic_ms"), "terminal monotonic")
            if isinstance(terminal_boundary, Mapping)
            else None
        )
        startup_ms = _integer(first_event.get("recorded_monotonic_ms"), "startup monotonic")
        stop_intent_path = envelope.journal_directory / "STOP_INTENT.json"
        natural_close_path = envelope.journal_directory / "NATURAL_TERMINAL_CLOSE_INTENT.json"
        if stop_intent_path.is_symlink() or natural_close_path.is_symlink():
            raise CommissioningError("terminal branch journal must not be a symlink")
        explicit_live_stop = bool(
            complete and stop_intent_path.is_file() and not natural_close_path.is_file()
        )
        probe = _probe_evaluation(
            envelope,
            runtime_identity=runtime_identity,
            pid=pid,
            startup_monotonic_ms=startup_ms,
            complete=complete,
            terminal_monotonic_ms=terminal_ms,
            explicit_live_stop=explicit_live_stop,
        )
        operability = _operability_evaluation(
            envelope,
            runtime_identity=runtime_identity,
            pid=pid,
        )
        duration_ms = terminal_ms - startup_ms if terminal_ms is not None else None
        twenty_four_hour_met = bool(
            complete
            and clean_stop
            and duration_ms is not None
            and duration_ms >= 86_400_000
            and operability.get("valid") is True
            and probe["contiguous_sequence"] is True
            and probe["all_operational_success"] is True
            and probe["all_rows_contract_valid"] is True
            and probe["first_probe_within_limit"] is True
            and probe["hard_first_probe_within_limit"] is True
            and probe["mode_sequence_valid"] is True
            and probe["monotonic_valid"] is True
            and cast(int, probe["max_probe_gap_ms"]) <= _MAX_PERIODIC_GAP_MS
            and probe["continuous_partition_monotonic_valid"] is True
            and cast(int, probe["continuous_partition_max_gap_ms"]) <= _MAX_PERIODIC_GAP_MS
            and probe["failure_marker_count"] == 0
            and probe["stderr_failure_sentinel_count"] == 0
        )
        if not complete:
            reader_integrity = "PASS_CURRENT_INCOMPLETE"
            terminal_business = "LIVE_INCOMPLETE_NO_TERMINAL"
            business_acceptance = "PENDING_LIVE"
            sample = "PENDING"
        elif clean_stop:
            reader_integrity = "PASS_COMPLETE_CLEAN_STOP"
            terminal_business = "CLEAN_STOP_COMPLETE"
            business_acceptance = (
                "OPERATIONAL_24H_GATE_MET"
                if twenty_four_hour_met
                else "OPERATIONAL_24H_GATE_NOT_MET"
            )
            sample = "MET" if twenty_four_hour_met else "NOT_MET"
        else:
            reader_integrity = "PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY"
            terminal_business = "PROCESS_FAILURE_COMPLETE_NOT_ACCEPTED"
            business_acceptance = "NOT_ACCEPTED_PROCESS_FAILURE"
            sample = "NOT_MET"
        report: dict[str, object] = {
            "schema_version": 1,
            "audit_mode": arguments.mode,
            "audit_monotonic_ms": time.monotonic_ns() // 1_000_000,
            "envelope_identity": envelope.envelope_identity,
            "runtime_identity": runtime_identity,
            "reader_verdict": "PASS",
            "reader_integrity_status": reader_integrity,
            "terminal_business_status": terminal_business,
            "business_acceptance": business_acceptance,
            "twenty_four_hour_continuous_public_service_sample": sample,
            "covered_duration_ms": duration_ms,
            "probe_evaluation": probe,
            "operability_evaluation": operability,
        }
        _write_exclusive_mapping(output_path, report)
        if not complete:
            initial_output = output_path == Path(
                envelope.current_audit_argv[envelope.current_audit_argv.index("--output") + 1]
            )
            current_valid = bool(
                probe["row_count"] == (1 if initial_output else probe["row_count"])
                and (initial_output or cast(int, probe["row_count"]) >= 3)
                and probe["contiguous_sequence"] is True
                and probe["all_operational_success"] is True
                and probe["all_rows_contract_valid"] is True
                and probe["first_probe_within_limit"] is True
                and probe["hard_first_probe_within_limit"] is True
                and probe["mode_sequence_valid"] is True
                and probe["failure_marker_count"] == 0
                and probe["stderr_failure_sentinel_count"] == 0
                and (initial_output or operability.get("valid") is True)
            )
            if not current_valid:
                print("current audit predicates are not met", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _parse_cpu_time_ms(value: str) -> int:
    days = 0
    rest = value
    if "-" in rest:
        day_text, rest = rest.split("-", 1)
        days = int(day_text)
    raw_parts = rest.split(":")
    try:
        seconds_ms = round(float(raw_parts[-1]) * 1000)
        parts = [int(item) for item in raw_parts[:-1]]
    except (ValueError, IndexError) as exc:
        raise CommissioningError("process CPU time shape mismatch") from exc
    if len(parts) == 2:
        hours, minutes = parts
    elif len(parts) == 1:
        hours = 0
        (minutes,) = parts
    else:
        raise CommissioningError("process CPU time shape mismatch")
    return ((days * 24 + hours) * 60 + minutes) * 60_000 + seconds_ms


def _load_envelope(path: Path, *, expected_identity: str) -> CommissioningEnvelope:
    envelope = CommissioningEnvelope.from_mapping(_read_json(path))
    if envelope.envelope_identity != _identity(expected_identity, "expected envelope identity"):
        raise CommissioningError("commissioning envelope identity mismatch")
    return envelope


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deadline-safe r4 service controller")
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--expected-envelope-identity", required=True)
    parser.add_argument("--mode", choices=("commission", "stop"), default="commission")
    arguments = parser.parse_args(argv)
    try:
        envelope = _load_envelope(
            arguments.envelope.resolve(),
            expected_identity=arguments.expected_envelope_identity,
        )
        clock = SystemClock()
        controller = CommissioningController(
            envelope,
            host=MacOSHost(envelope, clock),
            clock=clock,
            probe=SubprocessProbe(envelope, clock),
            audit=SubprocessAudit(envelope, clock),
        )
        receipt = controller.commission() if arguments.mode == "commission" else controller.stop()
    except CommissioningError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(receipt.as_mapping(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

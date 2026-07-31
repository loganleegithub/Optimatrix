from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
)
from short_vol_underwriting.identity import (
    GIT_COMMIT_PATTERN,
    canonical_identity,
    require_identity,
)

MANIFEST_KEYS = (
    "manifest_content_schema_identity",
    "candidate_commit",
    "candidate_tree",
    "intended_remote_ref",
    "verified_remote_ref",
    "outcome_contract_identity",
    "outcome_contract_path",
    "radar_policy_path",
    "radar_policy_identity",
    "underwriting_policy_path",
    "underwriting_policy_identity",
    "position_policy_path",
    "position_policy_identity",
    "evidence_directory",
    "process_argv",
    "process_cwd",
    "required_pre_run_checks",
    "runtime_start_trigger",
    "enrollment_cutoff_trigger",
    "final_stop_trigger",
    "clean_stop_predicate",
    "emergency_stop_authority",
    "forbidden_capabilities",
    "non_claims",
)
TRIGGER_KEYS = (
    "runtime_identity",
    "supervisor_clock_identity",
    "trigger_monotonic_ms",
    "trigger_kind",
)
REMOTE_REF_PATTERN = re.compile(r"refs/heads/[^\x00-\x20~^:?*\\[\\\\]+")


class ManifestError(ValueError):
    """The forward-cohort manifest is not the frozen exact identity graph."""


@dataclass(frozen=True)
class ValidatedManifest:
    value: Mapping[str, object]
    exact_bytes: bytes
    manifest_identity: str
    candidate_commit: str
    candidate_tree: str
    intended_remote_ref: str
    runtime_identity: str
    supervisor_clock_identity: str
    evidence_directory: Path


def manifest_identity_bytes(exact_bytes: bytes) -> str:
    if not exact_bytes.endswith(b"\n") or exact_bytes.endswith(b"\n\n"):
        raise ManifestError("manifest bytes must end in exactly one LF")
    return f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"


def load_manifest_bytes(exact_bytes: bytes) -> ValidatedManifest:
    if exact_bytes.startswith(b"\xef\xbb\xbf"):
        raise ManifestError("manifest must not contain a UTF-8 BOM")
    if not exact_bytes.endswith(b"\n") or exact_bytes.endswith(b"\n\n"):
        raise ManifestError("manifest must end in exactly one LF")
    try:
        text = exact_bytes.decode("utf-8")
        value = json.loads(
            text,
            parse_float=_reject_non_integer,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ManifestError) as exc:
        raise ManifestError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest must be one object")
    if tuple(value) != MANIFEST_KEYS:
        raise ManifestError("manifest requires exact keys in contract order")
    serialized = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    if serialized != exact_bytes:
        raise ManifestError("manifest bytes are not the normative serializer output")
    _validate_manifest(value)
    start = _mapping(value["runtime_start_trigger"], "runtime_start_trigger")
    return ValidatedManifest(
        value=value,
        exact_bytes=exact_bytes,
        manifest_identity=manifest_identity_bytes(exact_bytes),
        candidate_commit=_git_identity(value["candidate_commit"], "candidate_commit"),
        candidate_tree=_git_identity(value["candidate_tree"], "candidate_tree"),
        intended_remote_ref=_string(value["intended_remote_ref"], "intended_remote_ref"),
        runtime_identity=_identity(start["runtime_identity"], "runtime_identity"),
        supervisor_clock_identity=_identity(
            start["supervisor_clock_identity"],
            "supervisor_clock_identity",
        ),
        evidence_directory=Path(_string(value["evidence_directory"], "evidence_directory")),
    )


def _validate_manifest(value: Mapping[str, object]) -> None:
    expected_schema = canonical_identity(
        "SHORT_VOL_SHADOW_FORWARD_COHORT_MANIFEST_SCHEMA",
        OUTCOME_CONTRACT_DIGEST,
    )
    if value["manifest_content_schema_identity"] != expected_schema:
        raise ManifestError("manifest content schema identity mismatch")
    candidate = _git_identity(value["candidate_commit"], "candidate_commit")
    _git_identity(value["candidate_tree"], "candidate_tree")
    verified = _git_identity(value["verified_remote_ref"], "verified_remote_ref")
    if verified != candidate:
        raise ManifestError("candidate_commit and verified_remote_ref must match")
    intended = _string(value["intended_remote_ref"], "intended_remote_ref")
    if REMOTE_REF_PATTERN.fullmatch(intended) is None:
        raise ManifestError("intended_remote_ref must be an exact refs/heads/... string")
    radar_identity = _identity(value["radar_policy_identity"], "radar_policy_identity")
    underwriting_identity = _identity(
        value["underwriting_policy_identity"],
        "underwriting_policy_identity",
    )
    position_identity = _identity(
        value["position_policy_identity"],
        "position_policy_identity",
    )
    if (
        radar_identity,
        underwriting_identity,
        position_identity,
    ) != (
        RADAR_POLICY_IDENTITY,
        UNDERWRITING_POLICY_IDENTITY,
        POSITION_POLICY_IDENTITY,
    ):
        raise ManifestError("manifest must bind the frozen exact three-Policy chain")
    expected_contract = canonical_identity(
        "OUTCOME_CONTRACT",
        "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
        OUTCOME_CONTRACT_DIGEST,
        candidate,
        radar_identity,
        underwriting_identity,
        position_identity,
    )
    if value["outcome_contract_identity"] != expected_contract:
        raise ManifestError("Outcome contract identity graph mismatch")
    expected_paths = {
        "outcome_contract_path": ("docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md"),
        "radar_policy_path": "policies/short-vol-fixed-public-shadow-radar.json",
        "underwriting_policy_path": ("policies/short-vol-fixed-public-shadow-underwriting.json"),
        "position_policy_path": "policies/short-vol-fixed-public-shadow-position.json",
    }
    for field, expected in expected_paths.items():
        path = _repository_relative_path(value[field], field)
        if path.as_posix() != expected:
            raise ManifestError(f"{field} must bind the frozen repository path")
    evidence_directory = Path(_string(value["evidence_directory"], "evidence_directory"))
    if not evidence_directory.is_absolute():
        raise ManifestError("evidence_directory must be absolute")
    process_cwd = Path(_string(value["process_cwd"], "process_cwd"))
    if not process_cwd.is_absolute():
        raise ManifestError("process_cwd must be absolute")
    argv = _non_empty_string_array(value["process_argv"], "process_argv")
    if "observe-shadow" not in argv:
        raise ManifestError("process_argv must select the guarded observe-shadow command")
    _non_empty_string_array(value["required_pre_run_checks"], "required_pre_run_checks")
    triggers = (
        _trigger(value["runtime_start_trigger"], "RUNTIME_START"),
        _trigger(value["enrollment_cutoff_trigger"], "ENROLLMENT_CUTOFF"),
        _trigger(value["final_stop_trigger"], "FINAL_STOP"),
    )
    runtime_identities = {trigger["runtime_identity"] for trigger in triggers}
    clock_identities = {trigger["supervisor_clock_identity"] for trigger in triggers}
    if len(runtime_identities) != 1 or len(clock_identities) != 1:
        raise ManifestError("manifest triggers must share runtime and supervisor clock identities")
    times = tuple(
        _non_negative_integer(
            trigger["trigger_monotonic_ms"],
            "trigger_monotonic_ms",
        )
        for trigger in triggers
    )
    if not times[0] < times[1] < times[2]:
        raise ManifestError("manifest trigger order must be start < cutoff < stop")
    _string(value["clean_stop_predicate"], "clean_stop_predicate")
    _identity(value["emergency_stop_authority"], "emergency_stop_authority")
    _sorted_identity_array(value["forbidden_capabilities"], "forbidden_capabilities")
    _sorted_identity_array(value["non_claims"], "non_claims")


def _trigger(value: object, expected_kind: str) -> Mapping[str, object]:
    trigger = _mapping(value, f"{expected_kind} trigger")
    if tuple(trigger) != TRIGGER_KEYS:
        raise ManifestError(f"{expected_kind} trigger requires exact keys in contract order")
    _identity(trigger["runtime_identity"], "trigger.runtime_identity")
    _identity(trigger["supervisor_clock_identity"], "trigger.supervisor_clock_identity")
    monotonic = trigger["trigger_monotonic_ms"]
    if isinstance(monotonic, bool) or not isinstance(monotonic, int) or monotonic < 0:
        raise ManifestError("trigger_monotonic_ms must be a non-negative integer")
    if trigger["trigger_kind"] != expected_kind:
        raise ManifestError(f"trigger_kind must be {expected_kind}")
    return trigger


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise ManifestError(f"duplicate manifest member: {key}")
        value[key] = member
    return value


def _reject_non_integer(value: str) -> object:
    raise ManifestError(f"manifest JSON number must be an integer: {value}")


def _reject_constant(value: str) -> object:
    raise ManifestError(f"manifest number must be finite: {value}")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty string")
    return value


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestError(f"{field} must be a non-negative integer")
    return value


def _identity(value: object, field: str) -> str:
    try:
        return require_identity(value, field)
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc


def _git_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or GIT_COMMIT_PATTERN.fullmatch(value) is None:
        raise ManifestError(f"{field} must be lowercase 40-hex")
    return value


def _repository_relative_path(value: object, field: str) -> PurePosixPath:
    raw = _string(value, field)
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or raw != path.as_posix():
        raise ManifestError(f"{field} must be one normalized repository-relative path")
    return path


def _non_empty_string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{field} must be a non-empty string array")
    result = tuple(_string(member, field) for member in value)
    return result


def _sorted_string_array(value: object, field: str) -> tuple[str, ...]:
    result = _non_empty_string_array(value, field)
    if result != tuple(sorted(result)) or len(result) != len(set(result)):
        raise ManifestError(f"{field} must be unique and bytewise sorted")
    return result


def _sorted_identity_array(value: object, field: str) -> tuple[str, ...]:
    result = _sorted_string_array(value, field)
    for member in result:
        _identity(member, field)
    return result

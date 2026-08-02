from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
from short_vol_underwriting.constants import (
    ALL_DOWNSTREAM_OBJECT_KINDS,
    CANDIDATE_INVALIDATION_REASONS,
    DOWNSTREAM_NON_CLAIMS,
    OUTCOME_CONTRACT_DIGEST,
    OUTCOME_OBJECT_KINDS,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.domain import ordered_candidate_invalidation
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.manifest import (
    ManifestError,
    ValidatedManifest,
    load_manifest_bytes,
)
from short_vol_underwriting.model import FactBoundary
from short_vol_underwriting.schemas import (
    IDENTITY_PAYLOAD_FIELDS,
    PAYLOAD_KEYS,
    PRIMARY_BOUNDARY_FIELDS,
)
from short_vol_underwriting.validation import (
    PayloadValidationError,
    validate_complete_attempt_relationships,
    validate_complete_cohort_summary_provenance,
    validate_complete_semantic_graph,
    validate_exact_attempt_provenance,
    validate_object_graph,
    validate_payload_semantics,
    validate_provenance_shape,
)


class DownstreamEvidenceError(ValueError):
    """Downstream evidence is malformed, mixed, incomplete, or conflicting."""


GitObjectReader = Callable[[Path, Sequence[str]], bytes]


@dataclass(frozen=True)
class RuntimeBindings:
    code_identity: str
    runtime_identity: str
    radar_policy_identity: str
    underwriting_policy_identity: str
    position_policy_identity: str
    underwriting_position_contract_digest: str
    outcome_contract_digest: str

    def __post_init__(self) -> None:
        try:
            require_code_identity(self.code_identity)
            require_identity(self.runtime_identity, "runtime_identity")
            require_identity(self.radar_policy_identity, "radar_policy_identity")
            require_identity(self.underwriting_policy_identity, "underwriting_policy_identity")
            require_identity(self.position_policy_identity, "position_policy_identity")
            require_identity(
                self.underwriting_position_contract_digest,
                "underwriting_position_contract_digest",
            )
            require_identity(self.outcome_contract_digest, "outcome_contract_digest")
        except ValueError as exc:
            raise DownstreamEvidenceError(str(exc)) from exc
        if self.underwriting_position_contract_digest != UNDERWRITING_POSITION_CONTRACT_DIGEST:
            raise DownstreamEvidenceError("Underwriting/Position contract digest mismatch")
        if self.outcome_contract_digest != OUTCOME_CONTRACT_DIGEST:
            raise DownstreamEvidenceError("Outcome contract digest mismatch")

    @property
    def outcome_contract_identity(self) -> str:
        return canonical_identity(
            "OUTCOME_CONTRACT",
            "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
            self.outcome_contract_digest,
            self.code_identity,
            self.radar_policy_identity,
            self.underwriting_policy_identity,
            self.position_policy_identity,
        )


class DownstreamEvidenceWriter:
    def __init__(self, directory: Path, *, bindings: RuntimeBindings) -> None:
        self.directory = directory
        self.bindings = bindings
        if not directory.exists() or not directory.is_dir():
            raise DownstreamEvidenceError("downstream evidence directory must already exist")
        self.objects_directory = directory / "objects"
        try:
            self.objects_directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise DownstreamEvidenceError("cannot create downstream objects directory") from exc
        self._objects: dict[tuple[str, str], dict[str, object]] = {}
        self._revision = 0

    @property
    def objects(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._objects[key] for key in sorted(self._objects))

    @property
    def revision(self) -> int:
        return self._revision

    def write(
        self,
        *,
        object_kind: str,
        object_identity: str,
        fact_boundary: FactBoundary,
        payload: Mapping[str, object],
        source_provenance: Sequence[Mapping[str, object]],
    ) -> Path | None:
        value = build_downstream_object(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
            source_provenance=source_provenance,
            bindings=self.bindings,
        )
        serialized = _serialize(value)
        path = _object_path(self.objects_directory, object_kind, object_identity)
        published = _publish_exclusive(path, serialized)
        key = (object_kind, object_identity)
        previous = self._objects.get(key)
        self._objects[key] = value
        if previous != value:
            self._revision += 1
        return published


def build_downstream_object(
    *,
    object_kind: str,
    object_identity: str,
    fact_boundary: FactBoundary,
    payload: Mapping[str, object],
    source_provenance: Sequence[Mapping[str, object]],
    bindings: RuntimeBindings,
) -> dict[str, object]:
    if object_kind not in ALL_DOWNSTREAM_OBJECT_KINDS:
        raise DownstreamEvidenceError("unknown downstream object kind")
    try:
        require_identity(object_identity, "object_identity")
    except ValueError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc
    normalized_payload = canonical_value(payload)
    normalized_provenance = canonical_value(source_provenance)
    if not isinstance(normalized_payload, dict):
        raise DownstreamEvidenceError("payload must be an object")
    if not isinstance(normalized_provenance, list):
        raise DownstreamEvidenceError("source_provenance must be an array")
    if object_kind in OUTCOME_OBJECT_KINDS:
        value: dict[str, object] = {
            "object_kind": object_kind,
            "content_schema_identity": canonical_identity(
                "OUTCOME_CONTENT_SCHEMA",
                bindings.outcome_contract_digest,
                object_kind,
            ),
            "object_identity": object_identity,
            "outcome_contract_identity": bindings.outcome_contract_identity,
            "code_identity": bindings.code_identity,
            "runtime_identity": bindings.runtime_identity,
            "radar_policy_identity": bindings.radar_policy_identity,
            "underwriting_policy_identity": bindings.underwriting_policy_identity,
            "position_policy_identity": bindings.position_policy_identity,
            "fact_boundary": fact_boundary.as_object(),
            "source_provenance": normalized_provenance,
            "payload": normalized_payload,
            "non_claims": list(DOWNSTREAM_NON_CLAIMS),
        }
    else:
        value = {
            "object_kind": object_kind,
            "content_schema_identity": canonical_identity(
                "UNDERWRITING_POSITION_CONTENT_SCHEMA",
                bindings.underwriting_position_contract_digest,
                object_kind,
            ),
            "object_identity": object_identity,
            "underwriting_position_contract_digest": (
                bindings.underwriting_position_contract_digest
            ),
            "code_identity": bindings.code_identity,
            "runtime_identity": bindings.runtime_identity,
            "radar_policy_identity": bindings.radar_policy_identity,
            "underwriting_policy_identity": bindings.underwriting_policy_identity,
            "position_policy_identity": bindings.position_policy_identity,
            "fact_boundary": fact_boundary.as_object(),
            "source_provenance": normalized_provenance,
            "payload": normalized_payload,
            "non_claims": list(DOWNSTREAM_NON_CLAIMS),
        }
    validate_downstream_object(value, bindings=bindings)
    return value


def read_current_evidence(
    directory: Path,
    *,
    bindings: RuntimeBindings,
) -> dict[str, dict[str, object]]:
    objects_directory = directory / "objects"
    if not objects_directory.is_dir():
        raise DownstreamEvidenceError("downstream objects directory is missing")
    result: dict[str, dict[str, object]] = {}
    try:
        kind_entries = sorted(objects_directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise DownstreamEvidenceError("cannot enumerate downstream objects") from exc
    for kind_path in kind_entries:
        if not kind_path.is_dir() or kind_path.name not in ALL_DOWNSTREAM_OBJECT_KINDS:
            raise DownstreamEvidenceError(f"unknown entry inside objects: {kind_path.name}")
        try:
            entries = sorted(kind_path.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise DownstreamEvidenceError(
                f"cannot enumerate object kind: {kind_path.name}"
            ) from exc
        for path in entries:
            if not path.is_file() or path.suffix != ".json":
                raise DownstreamEvidenceError(f"unknown object entry: {path.name}")
            exact_bytes = _read_bytes(path)
            value = _parse_canonical_json(exact_bytes, path)
            validate_downstream_object(value, bindings=bindings)
            identity = _required_string(value, "object_identity")
            expected_path = _object_path(objects_directory, kind_path.name, identity)
            if path != expected_path:
                raise DownstreamEvidenceError("object path identity mismatch")
            result_key = identity
            if result_key in result:
                result_key = f"{kind_path.name}:{identity}"
            result[result_key] = value
    try:
        validate_object_graph(result)
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc
    return result


def read_complete_evidence(
    directory: Path,
    *,
    bindings: RuntimeBindings,
) -> dict[str, dict[str, object]]:
    """Read one terminal, conservation-valid fixed-contract evidence directory."""
    return _read_complete_evidence_with_git_reader(
        directory,
        bindings=bindings,
        git_object_reader=_read_local_git_object,
    )


def _read_complete_evidence_with_git_reader(
    directory: Path,
    *,
    bindings: RuntimeBindings,
    git_object_reader: GitObjectReader,
) -> dict[str, dict[str, object]]:
    """Private deterministic seam for exercising local Git-object failure cases."""
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise DownstreamEvidenceError("complete evidence requires root manifest.json")
    try:
        manifest = load_manifest_bytes(_read_bytes(manifest_path))
    except ManifestError as exc:
        raise DownstreamEvidenceError(f"invalid root manifest.json: {exc}") from exc
    _validate_manifest_bindings(
        manifest,
        directory=directory,
        bindings=bindings,
    )
    _validate_manifest_repository_graph(
        manifest,
        git_object_reader=git_object_reader,
    )

    objects = read_current_evidence(directory, bindings=bindings)
    underwriting_summary = _single_summary(
        objects,
        "UNDERWRITING_POSITION_SUMMARY",
    )
    cohort_summary = _single_summary(
        objects,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    _validate_complete_summaries(
        objects,
        underwriting_summary=underwriting_summary,
        cohort_summary=cohort_summary,
        manifest=manifest,
    )
    return objects


def _read_local_git_object(repository: Path, arguments: Sequence[str]) -> bytes:
    try:
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DownstreamEvidenceError("cannot read required local Git object") from exc


def _validate_manifest_repository_graph(
    manifest: ValidatedManifest,
    *,
    git_object_reader: GitObjectReader,
) -> None:
    repository = Path(_required_string(manifest.value, "process_cwd"))

    def read(*arguments: str) -> bytes:
        try:
            return git_object_reader(repository, arguments)
        except DownstreamEvidenceError:
            raise
        except (OSError, subprocess.CalledProcessError) as exc:
            raise DownstreamEvidenceError("cannot read required local Git object") from exc

    try:
        top_level = Path(read("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve(
            strict=True
        )
        expected_top_level = repository.resolve(strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise DownstreamEvidenceError("invalid local Git repository root") from exc
    if top_level != expected_top_level:
        raise DownstreamEvidenceError("manifest process_cwd is not the local Git repository root")

    candidate = manifest.candidate_commit
    read("cat-file", "-e", f"{candidate}^{{commit}}")
    try:
        candidate_tree = read("rev-parse", f"{candidate}^{{tree}}").decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise DownstreamEvidenceError("candidate tree is not an ASCII Git identity") from exc
    if candidate_tree != manifest.candidate_tree:
        raise DownstreamEvidenceError("manifest candidate tree differs from named commit tree")
    read("cat-file", "-e", f"{manifest.candidate_tree}^{{tree}}")

    expected_blobs = (
        (
            "Outcome contract",
            _required_string(manifest.value, "outcome_contract_path"),
            OUTCOME_CONTRACT_DIGEST,
        ),
        (
            "Radar Policy",
            _required_string(manifest.value, "radar_policy_path"),
            _required_identity(manifest.value, "radar_policy_identity"),
        ),
        (
            "Underwriting Policy",
            _required_string(manifest.value, "underwriting_policy_path"),
            _required_identity(manifest.value, "underwriting_policy_identity"),
        ),
        (
            "Position Policy",
            _required_string(manifest.value, "position_policy_path"),
            _required_identity(manifest.value, "position_policy_identity"),
        ),
    )
    for label, path, expected_digest in expected_blobs:
        exact_bytes = read("cat-file", "blob", f"{candidate}:{path}")
        actual_digest = f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"
        if actual_digest != expected_digest:
            raise DownstreamEvidenceError(f"{label} blob digest differs from manifest binding")


def _validate_manifest_bindings(
    manifest: ValidatedManifest,
    *,
    directory: Path,
    bindings: RuntimeBindings,
) -> None:
    if manifest.evidence_directory != directory:
        raise DownstreamEvidenceError("manifest evidence directory mismatch")
    if manifest.candidate_commit != bindings.code_identity:
        raise DownstreamEvidenceError("manifest/code identity mismatch")
    if manifest.runtime_identity != bindings.runtime_identity:
        raise DownstreamEvidenceError("manifest/runtime identity mismatch")
    for field in (
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        if manifest.value[field] != getattr(bindings, field):
            raise DownstreamEvidenceError(f"manifest/{field} mismatch")
    if manifest.value["outcome_contract_identity"] != bindings.outcome_contract_identity:
        raise DownstreamEvidenceError("manifest/Outcome contract identity mismatch")


def _single_summary(
    objects: Mapping[str, Mapping[str, object]],
    object_kind: str,
) -> Mapping[str, object]:
    summaries = tuple(value for value in objects.values() if value["object_kind"] == object_kind)
    if len(summaries) != 1:
        raise DownstreamEvidenceError(
            f"complete evidence requires exactly one {object_kind} summary"
        )
    return summaries[0]


def _validate_complete_summaries(
    objects: Mapping[str, Mapping[str, object]],
    *,
    underwriting_summary: Mapping[str, object],
    cohort_summary: Mapping[str, object],
    manifest: ValidatedManifest,
) -> None:
    underwriting_payload = _mapping(underwriting_summary["payload"], "Underwriting summary payload")
    cohort_payload = _mapping(cohort_summary["payload"], "cohort summary payload")
    if underwriting_payload["conservation_status"] != "MET":
        raise DownstreamEvidenceError("complete Underwriting summary must be MET")
    if cohort_payload["evidence_status"] != "COMPLETE":
        raise DownstreamEvidenceError("complete cohort summary must declare COMPLETE")
    if cohort_payload["conservation_status"] != "MET":
        raise DownstreamEvidenceError("complete cohort summary must be MET, never UNKNOWN")
    if cohort_payload["manifest_identity"] != manifest.manifest_identity:
        raise DownstreamEvidenceError("cohort summary manifest identity mismatch")

    try:
        validate_complete_attempt_relationships(objects)
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc

    terminal_boundary = _fact_boundary(
        cohort_payload["terminal_fact_boundary"],
        "cohort summary terminal_fact_boundary",
    )
    if underwriting_payload["terminal_fact_boundary"] != terminal_boundary.as_object():
        raise DownstreamEvidenceError("summary terminal FactBoundary mismatch")
    terminal_source_identity = _required_identity(
        cohort_payload,
        "terminal_source_identity",
    )
    if underwriting_payload["terminal_source_identity"] != terminal_source_identity:
        raise DownstreamEvidenceError("summary terminal source identity mismatch")
    runtime_start, enrollment_end = _validate_cohort_terminal(
        cohort_payload,
        terminal_boundary=terminal_boundary,
        terminal_source_identity=terminal_source_identity,
        manifest=manifest,
    )
    try:
        validate_complete_cohort_summary_provenance(
            cohort_summary,
            manifest_identity=manifest.manifest_identity,
            runtime_start_trigger=_mapping(
                manifest.value["runtime_start_trigger"],
                "manifest runtime_start_trigger",
            ),
            enrollment_cutoff_trigger=_mapping(
                manifest.value["enrollment_cutoff_trigger"],
                "manifest enrollment_cutoff_trigger",
            ),
        )
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc
    _validate_censored_outcome_terminal_cross_bind(
        objects,
        terminal_boundary=terminal_boundary,
        terminal_source_identity=terminal_source_identity,
        terminal_disposition=_required_string(
            cohort_payload,
            "terminal_disposition",
        ),
    )
    try:
        validate_complete_semantic_graph(
            objects,
            runtime_start=runtime_start,
            enrollment_end=enrollment_end,
            terminal_boundary=terminal_boundary,
        )
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc

    values = tuple(objects.values())
    try:
        underwriting_counts = derive_underwriting_counts(values)
        cohort_counts = derive_cohort_counts(values)
        underwriting_rates = compute_underwriting_rates(underwriting_counts)
        cohort_rates = compute_cohort_rates(cohort_counts, evidence_status="COMPLETE")
    except ValueError as exc:
        raise DownstreamEvidenceError(f"cannot derive complete-directory counts: {exc}") from exc
    if underwriting_payload["counts"] != underwriting_counts:
        raise DownstreamEvidenceError("summary differs from derived Underwriting counts")
    if underwriting_payload["rates"] != underwriting_rates:
        raise DownstreamEvidenceError("summary differs from derived Underwriting rates")
    if cohort_payload["counts"] != cohort_counts:
        raise DownstreamEvidenceError("summary differs from derived cohort counts")
    if cohort_payload["rates"] != cohort_rates:
        raise DownstreamEvidenceError("summary differs from derived cohort rates")
    if underwriting_conservation_status(underwriting_counts) != "MET":
        raise DownstreamEvidenceError("derived Underwriting conservation is not MET")
    if cohort_conservation_status(cohort_counts, evidence_status="COMPLETE") != "MET":
        raise DownstreamEvidenceError("derived cohort conservation is not MET")


def _validate_censored_outcome_terminal_cross_bind(
    objects: Mapping[str, Mapping[str, object]],
    *,
    terminal_boundary: FactBoundary,
    terminal_source_identity: str,
    terminal_disposition: str,
) -> None:
    expected_state = (
        "CENSORED_AT_FAILURE" if terminal_disposition == "PROCESS_FAILURE" else "CENSORED_AT_STOP"
    )
    for value in objects.values():
        if value["object_kind"] not in {
            "SHADOW_OUTCOME",
            "REJECTED_COUNTERFACTUAL_OUTCOME",
        }:
            continue
        payload = _mapping(value["payload"], "Outcome payload")
        if payload["terminal_state"] not in {
            "CENSORED_AT_STOP",
            "CENSORED_AT_FAILURE",
        }:
            continue
        if payload["terminal_state"] != expected_state:
            raise DownstreamEvidenceError(
                "censored Outcome state differs from terminal disposition"
            )
        if payload["terminal_supervisor_source_identity"] != terminal_source_identity:
            raise DownstreamEvidenceError(
                "censored Outcome terminal source differs from cohort summary"
            )
        if payload["terminal_fact_boundary"] != terminal_boundary.as_object():
            raise DownstreamEvidenceError(
                "censored Outcome terminal boundary differs from cohort summary"
            )


def _validate_cohort_terminal(
    payload: Mapping[str, object],
    *,
    terminal_boundary: FactBoundary,
    terminal_source_identity: str,
    manifest: ValidatedManifest,
) -> tuple[FactBoundary, FactBoundary]:
    start = _fact_boundary(
        payload["runtime_start_fact_boundary"],
        "runtime_start_fact_boundary",
    )
    enrollment_end = _fact_boundary(
        payload["enrollment_end_fact_boundary"],
        "enrollment_end_fact_boundary",
    )
    start_trigger = _mapping(
        manifest.value["runtime_start_trigger"],
        "manifest runtime_start_trigger",
    )
    cutoff_trigger = _mapping(
        manifest.value["enrollment_cutoff_trigger"],
        "manifest enrollment_cutoff_trigger",
    )
    final_trigger = _mapping(
        manifest.value["final_stop_trigger"],
        "manifest final_stop_trigger",
    )
    for name, boundary in (
        ("runtime start", start),
        ("enrollment end", enrollment_end),
        ("terminal", terminal_boundary),
    ):
        if (
            boundary.code_identity != manifest.candidate_commit
            or boundary.runtime_identity != manifest.runtime_identity
        ):
            raise DownstreamEvidenceError(f"{name} boundary manifest identity mismatch")
    start_monotonic_ms = _non_negative_integer(
        start_trigger["trigger_monotonic_ms"],
        "runtime_start_trigger.trigger_monotonic_ms",
    )
    if start.received_monotonic_ms < start_monotonic_ms:
        raise DownstreamEvidenceError("runtime start boundary does not realize manifest trigger")
    reason = payload["enrollment_end_reason"]
    if reason == "PREBOUND_CUTOFF":
        if not (
            enrollment_end.is_strictly_after(start)
            and terminal_boundary.is_strictly_after(enrollment_end)
        ):
            raise DownstreamEvidenceError(
                "realized enrollment cutoff must be strictly after runtime start "
                "and strictly before terminal"
            )
        cutoff_monotonic_ms = _non_negative_integer(
            cutoff_trigger["trigger_monotonic_ms"],
            "enrollment_cutoff_trigger.trigger_monotonic_ms",
        )
        if enrollment_end.received_monotonic_ms < cutoff_monotonic_ms:
            raise DownstreamEvidenceError(
                "enrollment end boundary does not realize manifest cutoff"
            )
    elif reason == "TERMINAL_BEFORE_CUTOFF":
        if enrollment_end != terminal_boundary:
            raise DownstreamEvidenceError("terminal-before-cutoff enrollment boundary mismatch")
        if not terminal_boundary.is_strictly_after(start):
            raise DownstreamEvidenceError(
                "terminal-before-cutoff must be strictly after runtime start"
            )
    else:
        raise DownstreamEvidenceError("invalid enrollment end reason")

    terminal_source = _mapping(payload["terminal_source"], "terminal_source")
    disposition = payload["terminal_disposition"]
    if disposition == "PLANNED_CLEAN_STOP":
        if terminal_source != final_trigger:
            raise DownstreamEvidenceError("planned terminal source differs from manifest trigger")
        expected_identity = canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            final_trigger,
        )
        terminal_monotonic_ms = _non_negative_integer(
            terminal_source["trigger_monotonic_ms"],
            "final_stop_trigger.trigger_monotonic_ms",
        )
        terminal_time_matches = terminal_boundary.received_monotonic_ms >= terminal_monotonic_ms
        if payload["planned_final_stop_fact_boundary"] != terminal_boundary.as_object():
            raise DownstreamEvidenceError("planned final-stop boundary mismatch")
    elif disposition == "AUTHORIZED_EMERGENCY_STOP":
        _require_exact_keys(
            terminal_source,
            {
                "runtime_identity",
                "supervisor_clock_identity",
                "authority_identity",
                "control_monotonic_ms",
                "control_kind",
                "reason",
            },
            "AuthorizedEmergencyStopControl",
        )
        if (
            terminal_source["control_kind"] != "AUTHORIZED_EMERGENCY_STOP"
            or terminal_source["authority_identity"] != manifest.value["emergency_stop_authority"]
            or terminal_source["reason"]
            not in {
                "USER_REQUEST",
                "AUTHORITY_REVOCATION",
                "EXTERNAL_SAFETY_STOP",
            }
        ):
            raise DownstreamEvidenceError("invalid authorized emergency-stop source")
        expected_identity = canonical_identity(
            "AuthorizedEmergencyStopControlIdentity",
            {
                key: terminal_source[key]
                for key in (
                    "runtime_identity",
                    "supervisor_clock_identity",
                    "authority_identity",
                    "control_monotonic_ms",
                    "control_kind",
                    "reason",
                )
            },
        )
        terminal_monotonic_ms = _non_negative_integer(
            terminal_source["control_monotonic_ms"],
            "AuthorizedEmergencyStopControl.control_monotonic_ms",
        )
        terminal_time_matches = terminal_boundary.received_monotonic_ms == terminal_monotonic_ms
        if payload["planned_final_stop_fact_boundary"] is not None:
            raise DownstreamEvidenceError("emergency stop cannot claim planned final boundary")
    elif disposition == "PROCESS_FAILURE":
        _require_exact_keys(
            terminal_source,
            {
                "runtime_identity",
                "supervisor_clock_identity",
                "failure_source_identity",
                "control_monotonic_ms",
                "control_kind",
                "failure_kind",
            },
            "FatalFailureControl",
        )
        if terminal_source["control_kind"] != "PROCESS_FAILURE" or terminal_source[
            "failure_kind"
        ] not in {"FATAL_RUNTIME", "FATAL_EVIDENCE_INTEGRITY"}:
            raise DownstreamEvidenceError("invalid fatal-failure terminal source")
        _required_identity(terminal_source, "failure_source_identity")
        expected_identity = canonical_identity(
            "FatalFailureControlIdentity",
            {
                key: terminal_source[key]
                for key in (
                    "runtime_identity",
                    "supervisor_clock_identity",
                    "failure_source_identity",
                    "control_monotonic_ms",
                    "control_kind",
                    "failure_kind",
                )
            },
        )
        terminal_monotonic_ms = _non_negative_integer(
            terminal_source["control_monotonic_ms"],
            "FatalFailureControl.control_monotonic_ms",
        )
        terminal_time_matches = terminal_boundary.received_monotonic_ms == terminal_monotonic_ms
        if payload["planned_final_stop_fact_boundary"] is not None:
            raise DownstreamEvidenceError("process failure cannot claim planned final boundary")
    else:
        raise DownstreamEvidenceError("invalid terminal disposition")
    if (
        terminal_source["runtime_identity"] != manifest.runtime_identity
        or terminal_source["supervisor_clock_identity"] != manifest.supervisor_clock_identity
    ):
        raise DownstreamEvidenceError("terminal source manifest identity mismatch")
    if expected_identity != terminal_source_identity:
        raise DownstreamEvidenceError("terminal source identity mismatch")
    if not terminal_time_matches:
        raise DownstreamEvidenceError("terminal boundary does not realize terminal source")
    return start, enrollment_end


def validate_downstream_object(
    value: Mapping[str, object],
    *,
    bindings: RuntimeBindings,
) -> None:
    object_kind = _required_string(value, "object_kind")
    if object_kind not in ALL_DOWNSTREAM_OBJECT_KINDS:
        raise DownstreamEvidenceError("unknown downstream object kind")
    outcome_family = object_kind in OUTCOME_OBJECT_KINDS
    contract_key = (
        "outcome_contract_identity" if outcome_family else "underwriting_position_contract_digest"
    )
    expected_envelope = {
        "object_kind",
        "content_schema_identity",
        "object_identity",
        contract_key,
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
        "fact_boundary",
        "source_provenance",
        "payload",
        "non_claims",
    }
    _require_exact_keys(value, expected_envelope, "downstream envelope")
    expected_schema = canonical_identity(
        "OUTCOME_CONTENT_SCHEMA" if outcome_family else "UNDERWRITING_POSITION_CONTENT_SCHEMA",
        bindings.outcome_contract_digest
        if outcome_family
        else bindings.underwriting_position_contract_digest,
        object_kind,
    )
    if value["content_schema_identity"] != expected_schema:
        raise DownstreamEvidenceError("content_schema_identity mismatch")
    object_identity = _required_identity(value, "object_identity")
    if value["code_identity"] != bindings.code_identity:
        raise DownstreamEvidenceError("mixed code identity")
    if value["runtime_identity"] != bindings.runtime_identity:
        raise DownstreamEvidenceError("mixed runtime identity")
    for field in (
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        if value[field] != getattr(bindings, field):
            raise DownstreamEvidenceError(f"mixed {field}")
    if outcome_family:
        if value[contract_key] != bindings.outcome_contract_identity:
            raise DownstreamEvidenceError("mixed Outcome contract identity")
    elif value[contract_key] != bindings.underwriting_position_contract_digest:
        raise DownstreamEvidenceError("mixed Underwriting/Position contract digest")
    boundary = _fact_boundary(value["fact_boundary"], "fact_boundary")
    if (
        boundary.code_identity != bindings.code_identity
        or boundary.runtime_identity != bindings.runtime_identity
    ):
        raise DownstreamEvidenceError("FactBoundary identity mismatch")
    payload = _mapping(value["payload"], "payload")
    _require_exact_keys(payload, set(PAYLOAD_KEYS[object_kind]), f"{object_kind} payload")
    identity_field = IDENTITY_PAYLOAD_FIELDS[object_kind]
    if payload[identity_field] != object_identity:
        raise DownstreamEvidenceError("payload object identity mismatch")
    primary_boundary = _fact_boundary(
        payload[PRIMARY_BOUNDARY_FIELDS[object_kind]],
        f"payload.{PRIMARY_BOUNDARY_FIELDS[object_kind]}",
    )
    if primary_boundary != boundary:
        raise DownstreamEvidenceError("payload/envelope FactBoundary mismatch")
    _validate_source_provenance(
        value["source_provenance"],
        bindings,
        object_boundary=boundary,
    )
    if value["non_claims"] != list(DOWNSTREAM_NON_CLAIMS):
        raise DownstreamEvidenceError("downstream non_claims mismatch")
    _validate_kind_specific(object_kind, object_identity, payload, bindings)
    try:
        validate_payload_semantics(
            object_kind=object_kind,
            object_identity=object_identity,
            payload=payload,
            code_identity=bindings.code_identity,
            runtime_identity=bindings.runtime_identity,
            radar_policy_identity=bindings.radar_policy_identity,
            underwriting_policy_identity=bindings.underwriting_policy_identity,
            position_policy_identity=bindings.position_policy_identity,
            underwriting_contract_digest=bindings.underwriting_position_contract_digest,
            outcome_contract_identity=bindings.outcome_contract_identity,
        )
        validate_exact_attempt_provenance(value)
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc


def _validate_kind_specific(
    object_kind: str,
    object_identity: str,
    payload: Mapping[str, object],
    bindings: RuntimeBindings,
) -> None:
    if object_kind == "CANDIDATE_INVALIDATION":
        candidate = _required_identity(payload, "candidate_identity")
        primary = _required_string(payload, "primary_reason")
        reasons_raw = payload["ordered_applicable_reason_vector"]
        if not isinstance(reasons_raw, list) or not all(
            isinstance(reason, str) for reason in reasons_raw
        ):
            raise DownstreamEvidenceError("Candidate invalidation reasons must be an array")
        try:
            expected_primary, ordered = ordered_candidate_invalidation(reasons_raw)
        except ValueError as exc:
            raise DownstreamEvidenceError(str(exc)) from exc
        if primary != expected_primary or tuple(reasons_raw) != ordered:
            raise DownstreamEvidenceError("Candidate invalidation reason order mismatch")
        if primary not in CANDIDATE_INVALIDATION_REASONS:
            raise DownstreamEvidenceError("Candidate invalidation primary reason is invalid")
        expected_identity = canonical_identity(
            "CANDIDATE_INVALIDATION",
            candidate,
            primary,
            list(ordered),
            _fact_boundary(
                payload["terminal_fact_boundary"],
                "payload.terminal_fact_boundary",
            ).as_object(),
        )
        if object_identity != expected_identity:
            raise DownstreamEvidenceError("Candidate invalidation identity mismatch")
    elif object_kind == "ADMISSION_ATTEMPT_TERMINAL":
        outcome = payload["terminal_outcome"]
        if outcome not in {
            "ENTRY_EMITTED",
            "KNOWN_COMPLETE_NO_ENTRY",
            "KNOWN_INVALIDATED_BEFORE_REFRESH",
            "UNKNOWN_CONSUMED",
        }:
            raise DownstreamEvidenceError("admission terminal outcome is invalid")
        expected_identity = canonical_identity(
            "ADMISSION_ATTEMPT_TERMINAL",
            _required_identity(payload, "scheduled_admission_attempt_identity"),
            outcome,
            _fact_boundary(
                payload["terminal_fact_boundary"],
                "payload.terminal_fact_boundary",
            ).as_object(),
        )
        if object_identity != expected_identity:
            raise DownstreamEvidenceError("admission terminal identity mismatch")
    elif object_kind in {"POSITION_EVALUATION", "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION"}:
        vector = payload["ordered_predicate_truth_vector"]
        if (
            not isinstance(vector, list)
            or len(vector) != 9
            or any(item not in {"TRUE", "FALSE", "UNKNOWN"} for item in vector)
        ):
            raise DownstreamEvidenceError("Position predicate vector must have exact nine truths")
    elif object_kind in {"POSITION_ACTION", "REJECTED_COUNTERFACTUAL_POSITION_ACTION"}:
        vector = payload["ordered_predicate_truth_vector"]
        if (
            not isinstance(vector, list)
            or len(vector) != 9
            or any(item not in {"TRUE", "FALSE", "UNKNOWN"} for item in vector)
        ):
            raise DownstreamEvidenceError("Position action predicate vector is invalid")
        if payload["serialized_action"] not in {"HOLD", "CLOSE", "UNKNOWN"}:
            raise DownstreamEvidenceError("Position serialized action is invalid")
    elif object_kind == "UNDERWRITING_POSITION_SUMMARY":
        raw_counts = _integer_mapping(payload["counts"], "counts")
        counts = {key: raw_counts[key] for key in UNDERWRITING_COUNT_KEYS}
        rates = _ordered_rates(payload["rates"], UNDERWRITING_RATE_KEYS)
        try:
            expected_rates = compute_underwriting_rates(counts)
            expected_conservation = underwriting_conservation_status(counts)
        except ValueError as exc:
            raise DownstreamEvidenceError(str(exc)) from exc
        if dict(rates) != expected_rates:
            raise DownstreamEvidenceError("Underwriting summary rates mismatch")
        if payload["conservation_status"] != expected_conservation:
            raise DownstreamEvidenceError("Underwriting summary conservation mismatch")
        expected_identity = canonical_identity(
            "UNDERWRITING_POSITION_SUMMARY",
            bindings.underwriting_position_contract_digest,
            bindings.code_identity,
            bindings.runtime_identity,
            bindings.radar_policy_identity,
            bindings.underwriting_policy_identity,
            bindings.position_policy_identity,
            _required_identity(payload, "terminal_source_identity"),
            _fact_boundary(
                payload["terminal_fact_boundary"],
                "payload.terminal_fact_boundary",
            ).as_object(),
            counts,
            dict(rates),
            expected_conservation,
        )
        if object_identity != expected_identity:
            raise DownstreamEvidenceError("Underwriting summary identity mismatch")
    elif object_kind == "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY":
        raw_counts = _integer_mapping(payload["counts"], "counts")
        counts = {key: raw_counts[key] for key in COHORT_COUNT_KEYS}
        rates = _ordered_rates(payload["rates"], COHORT_RATE_KEYS)
        evidence_status = _required_string(payload, "evidence_status")
        try:
            expected_rates = compute_cohort_rates(
                counts,
                evidence_status=evidence_status,
            )
            expected_conservation = cohort_conservation_status(
                counts,
                evidence_status=evidence_status,
            )
        except ValueError as exc:
            raise DownstreamEvidenceError(str(exc)) from exc
        if dict(rates) != expected_rates:
            raise DownstreamEvidenceError("cohort summary rates mismatch")
        if payload["conservation_status"] != expected_conservation:
            raise DownstreamEvidenceError("cohort summary conservation mismatch")
        expected_identity = canonical_identity(
            "CohortSummaryIdentity",
            bindings.outcome_contract_identity,
            bindings.runtime_identity,
            _required_identity(payload, "manifest_identity"),
            _fact_boundary(
                payload["terminal_fact_boundary"],
                "payload.terminal_fact_boundary",
            ).as_object(),
        )
        if object_identity != expected_identity:
            raise DownstreamEvidenceError("cohort summary identity mismatch")


def _validate_source_provenance(
    value: object,
    bindings: RuntimeBindings,
    *,
    object_boundary: FactBoundary,
) -> None:
    try:
        provenance = validate_provenance_shape(
            value,
            code_identity=bindings.code_identity,
            runtime_identity=bindings.runtime_identity,
        )
    except PayloadValidationError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc
    if any(
        receipt_boundary.causal_seq > object_boundary.causal_seq
        for _role, _identity, receipt_boundary in provenance
    ):
        raise DownstreamEvidenceError("source provenance cannot cite a future causal boundary")


def _object_path(objects_directory: Path, object_kind: str, object_identity: str) -> Path:
    return objects_directory / object_kind / f"{object_identity.removeprefix('sha256:')}.json"


def _publish_exclusive(path: Path, serialized: bytes) -> Path | None:
    try:
        path.parent.mkdir(exist_ok=True)
    except OSError as exc:
        raise DownstreamEvidenceError(
            f"cannot create object kind directory: {path.parent}"
        ) from exc
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
            raise DownstreamEvidenceError("existing evidence cannot be verified") from read_exc
        if existing == serialized:
            return None
        raise DownstreamEvidenceError("conflicting evidence already exists") from exc
    except OSError as exc:
        raise DownstreamEvidenceError(f"evidence publish failed: {path}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise DownstreamEvidenceError("evidence temporary cleanup failed") from exc
    _fsync_directory(path.parent)
    _fsync_directory(path.parent.parent)
    return path


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DownstreamEvidenceError(f"evidence directory sync failed: {path}") from exc


def _serialize(value: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DownstreamEvidenceError(f"evidence is not canonical JSON: {exc}") from exc


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DownstreamEvidenceError(f"cannot read downstream object: {path}") from exc


def _parse_canonical_json(exact_bytes: bytes, path: Path) -> dict[str, object]:
    if exact_bytes.startswith(b"\xef\xbb\xbf") or not exact_bytes.endswith(b"\n"):
        raise DownstreamEvidenceError("object must be UTF-8 without BOM and end in one LF")
    try:
        text = exact_bytes.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DownstreamEvidenceError) as exc:
        raise DownstreamEvidenceError(f"invalid downstream object JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DownstreamEvidenceError("downstream object must be an object")
    if _serialize(value) != exact_bytes:
        raise DownstreamEvidenceError("downstream object is not canonical bytewise JSON")
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DownstreamEvidenceError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DownstreamEvidenceError(f"{field} must be an object")
    return value


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DownstreamEvidenceError(f"{field} must be a non-negative integer")
    return value


def _integer_mapping(value: object, field: str) -> dict[str, int]:
    mapping = _mapping(value, field)
    result: dict[str, int] = {}
    for key, member in mapping.items():
        if isinstance(member, bool) or not isinstance(member, int) or member < 0:
            raise DownstreamEvidenceError(f"{field}.{key} must be a non-negative integer")
        result[key] = member
    return result


def _ordered_rates(
    value: object,
    keys: tuple[str, ...],
) -> dict[str, dict[str, int] | None]:
    mapping = _mapping(value, "rates")
    if set(mapping) != set(keys):
        raise DownstreamEvidenceError("rates require exact keys")
    result: dict[str, dict[str, int] | None] = {}
    for key in keys:
        member = mapping[key]
        if member is None:
            result[key] = None
            continue
        rate = _mapping(member, f"rates.{key}")
        if set(rate) != {"numerator", "denominator"}:
            raise DownstreamEvidenceError(f"rates.{key} requires exact keys")
        numerator = rate["numerator"]
        denominator = rate["denominator"]
        if (
            isinstance(numerator, bool)
            or not isinstance(numerator, int)
            or numerator < 0
            or isinstance(denominator, bool)
            or not isinstance(denominator, int)
            or denominator <= 0
        ):
            raise DownstreamEvidenceError(f"rates.{key} is not an ExactRate")
        result[key] = {
            "numerator": numerator,
            "denominator": denominator,
        }
    return result


def _required_string(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise DownstreamEvidenceError(f"{field} must be a non-empty string")
    return member


def _required_identity(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    try:
        return require_identity(member, field)
    except ValueError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc


def _fact_boundary(value: object, field: str) -> FactBoundary:
    try:
        return FactBoundary.from_object(value)
    except ValueError as exc:
        raise DownstreamEvidenceError(f"{field}: {exc}") from exc


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise DownstreamEvidenceError(
            f"{field} requires exact keys; missing={missing}, unknown={unknown}"
        )

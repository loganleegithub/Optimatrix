from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
from short_vol_underwriting.model import FactBoundary
from short_vol_underwriting.schemas import (
    IDENTITY_PAYLOAD_FIELDS,
    PAYLOAD_KEYS,
    PRIMARY_BOUNDARY_FIELDS,
)
from short_vol_underwriting.validation import (
    PayloadValidationError,
    validate_payload_identity,
    validate_provenance_shape,
)


class DownstreamEvidenceError(ValueError):
    """Downstream evidence is malformed, mixed, incomplete, or conflicting."""


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
    return result


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
        validate_payload_identity(
            object_kind=object_kind,
            object_identity=object_identity,
            payload=payload,
            runtime_identity=bindings.runtime_identity,
            radar_policy_identity=bindings.radar_policy_identity,
            underwriting_policy_identity=bindings.underwriting_policy_identity,
            position_policy_identity=bindings.position_policy_identity,
            outcome_contract_identity=bindings.outcome_contract_identity,
        )
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

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from short_vol_underwriting.constants import (
    ALL_DOWNSTREAM_OBJECT_KINDS,
    OUTCOME_CONTRACT_DIGEST,
    OUTCOME_OBJECT_KINDS,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary


class DownstreamEvidenceError(ValueError):
    """A downstream business object cannot be projected or published."""


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
            for field in (
                "runtime_identity",
                "radar_policy_identity",
                "underwriting_policy_identity",
                "position_policy_identity",
                "underwriting_position_contract_digest",
                "outcome_contract_digest",
            ):
                require_identity(getattr(self, field), field)
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
        if not directory.is_dir():
            raise DownstreamEvidenceError("downstream directory must already exist")
        self.directory = directory
        self.bindings = bindings
        self.objects_directory = directory / "objects"
        self.objects_directory.mkdir(exist_ok=True)
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
    ) -> Path | None:
        value = build_downstream_object(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
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
    bindings: RuntimeBindings,
) -> dict[str, object]:
    if object_kind not in ALL_DOWNSTREAM_OBJECT_KINDS:
        raise DownstreamEvidenceError("unknown downstream object kind")
    try:
        require_identity(object_identity, "object_identity")
    except ValueError as exc:
        raise DownstreamEvidenceError(str(exc)) from exc
    if (
        fact_boundary.code_identity != bindings.code_identity
        or fact_boundary.runtime_identity != bindings.runtime_identity
    ):
        raise DownstreamEvidenceError("FactBoundary does not belong to this writer")
    normalized_payload = canonical_value(payload)
    if not isinstance(normalized_payload, dict):
        raise DownstreamEvidenceError("payload must be an object")
    value: dict[str, object] = {
        "object_kind": object_kind,
        "object_identity": object_identity,
        "code_identity": bindings.code_identity,
        "runtime_identity": bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
        "fact_boundary": fact_boundary.as_object(),
        "payload": normalized_payload,
    }
    if object_kind in OUTCOME_OBJECT_KINDS:
        value["outcome_contract_identity"] = bindings.outcome_contract_identity
    else:
        value["underwriting_position_contract_digest"] = (
            bindings.underwriting_position_contract_digest
        )
    return value


def _object_path(objects_directory: Path, object_kind: str, object_identity: str) -> Path:
    return objects_directory / object_kind / f"{object_identity.removeprefix('sha256:')}.json"


def _publish_exclusive(path: Path, serialized: bytes) -> Path | None:
    path.parent.mkdir(exist_ok=True)
    temporary = path.parent / f".object-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        if path.read_bytes() == serialized:
            return None
        raise DownstreamEvidenceError(f"conflicting business object: {path}") from exc
    except OSError as exc:
        raise DownstreamEvidenceError(f"business object publish failed: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return path


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
        raise DownstreamEvidenceError("business object is not JSON serializable") from exc

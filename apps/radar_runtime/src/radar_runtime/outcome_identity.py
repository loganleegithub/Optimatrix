"""Content identity for the bounded Outcome Truth runtime."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from radar_runtime.runtime_identity import RuntimeSourceIdentity, runtime_source_identity

OUTCOME_RUNTIME_SOURCE_ID = "OPTIMATRIX_OUTCOME_RUNTIME_SOURCE"
OUTCOME_RUNTIME_SOURCE_SCOPE = (
    "packages/shadow_engine/src/shadow_engine",
    "apps/radar_runtime/src/radar_runtime/outcome_identity.py",
    "apps/radar_runtime/src/radar_runtime/outcome_seal.py",
    "apps/radar_runtime/src/radar_runtime/outcome_runtime.py",
    "apps/radar_runtime/src/radar_runtime/outcome_bundle.py",
    "apps/radar_runtime/src/radar_runtime/outcome_cli.py",
    "apps/radar_runtime/src/radar_runtime/fixture.py",
    "pyproject.toml",
)


@dataclass(frozen=True, slots=True)
class OutcomeRuntimeSourceIdentity:
    git_commit_sha: str
    runtime_source_id: str
    runtime_source_digest: str
    decision_runtime_source_id: str
    decision_runtime_source_digest: str
    file_hashes: tuple[tuple[str, str], ...]
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.git_commit_sha or self.runtime_source_id != OUTCOME_RUNTIME_SOURCE_ID:
            raise ValueError("Outcome runtime source identity is invalid")
        if (
            not self.runtime_source_digest
            or not self.decision_runtime_source_id
            or not self.decision_runtime_source_digest
            or not self.file_hashes
        ):
            raise ValueError("Outcome runtime source content identity is incomplete")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _source_files(root: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for relative in OUTCOME_RUNTIME_SOURCE_SCOPE:
        target = root / relative
        if target.is_dir():
            files.update(item for item in target.rglob("*.py") if item.is_file())
        elif target.is_file():
            files.add(target)
        else:
            raise RuntimeError(f"Outcome runtime source scope is missing: {relative}")
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def outcome_runtime_source_file_hashes(
    root: Path | None = None,
) -> tuple[tuple[str, str], ...]:
    active_root = root or _repository_root()
    return tuple(
        (
            path.relative_to(active_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _source_files(active_root)
    )


def outcome_runtime_source_digest(
    decision_identity: RuntimeSourceIdentity,
    file_hashes: tuple[tuple[str, str], ...],
) -> str:
    payload = json.dumps(
        {
            "runtime_source_id": OUTCOME_RUNTIME_SOURCE_ID,
            "decision_runtime_source_id": decision_identity.runtime_source_id,
            "decision_runtime_source_digest": decision_identity.runtime_source_digest,
            "files": file_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def outcome_runtime_source_identity(
    *,
    root: Path | None = None,
    require_clean: bool,
) -> OutcomeRuntimeSourceIdentity:
    active_root = root or _repository_root()
    decision_identity = runtime_source_identity(root=active_root, require_clean=require_clean)
    status = subprocess.run(
        (
            "git",
            "-C",
            str(active_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *OUTCOME_RUNTIME_SOURCE_SCOPE,
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dirty_paths = tuple(line for line in status.splitlines() if line)
    if require_clean and dirty_paths:
        raise RuntimeError("Outcome runtime source scope is dirty: " + ",".join(dirty_paths))
    file_hashes = outcome_runtime_source_file_hashes(active_root)
    return OutcomeRuntimeSourceIdentity(
        git_commit_sha=decision_identity.git_commit_sha,
        runtime_source_id=OUTCOME_RUNTIME_SOURCE_ID,
        runtime_source_digest=outcome_runtime_source_digest(decision_identity, file_hashes),
        decision_runtime_source_id=decision_identity.runtime_source_id,
        decision_runtime_source_digest=decision_identity.runtime_source_digest,
        file_hashes=file_hashes,
        dirty_paths=dirty_paths,
    )

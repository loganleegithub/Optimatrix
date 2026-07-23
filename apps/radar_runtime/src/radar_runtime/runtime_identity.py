"""Content identity for the bounded Decision runtime source."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

RUNTIME_SOURCE_ID = "OPTIMATRIX_DECISION_RUNTIME_SOURCE"
RUNTIME_SOURCE_SCOPE = (
    "packages/market_tape/src/market_tape",
    "packages/options_domain/src/options_domain",
    "packages/short_vol_radar/src/short_vol_radar",
    "apps/radar_runtime/src/radar_runtime/cli.py",
    "apps/radar_runtime/src/radar_runtime/deribit_public.py",
    "apps/radar_runtime/src/radar_runtime/runtime_identity.py",
)


@dataclass(frozen=True, slots=True)
class RuntimeSourceIdentity:
    git_commit_sha: str
    runtime_source_id: str
    runtime_source_digest: str
    file_hashes: tuple[tuple[str, str], ...]
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.git_commit_sha or self.runtime_source_id != RUNTIME_SOURCE_ID:
            raise ValueError("runtime source identity is invalid")
        if not self.runtime_source_digest or not self.file_hashes:
            raise ValueError("runtime source content identity is incomplete")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _source_files(root: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for relative in RUNTIME_SOURCE_SCOPE:
        target = root / relative
        if target.is_dir():
            files.update(item for item in target.rglob("*.py") if item.is_file())
        elif target.is_file():
            files.add(target)
        else:
            raise RuntimeError(f"runtime source scope is missing: {relative}")
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def runtime_source_file_hashes(root: Path | None = None) -> tuple[tuple[str, str], ...]:
    active_root = root or repository_root()
    return tuple(
        (
            path.relative_to(active_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _source_files(active_root)
    )


def runtime_source_digest(file_hashes: tuple[tuple[str, str], ...]) -> str:
    payload = json.dumps(
        {
            "runtime_source_id": RUNTIME_SOURCE_ID,
            "files": file_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def runtime_source_identity(
    *,
    root: Path | None = None,
    require_clean: bool,
) -> RuntimeSourceIdentity:
    active_root = root or repository_root()
    revision = subprocess.run(
        ("git", "-C", str(active_root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        (
            "git",
            "-C",
            str(active_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *RUNTIME_SOURCE_SCOPE,
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dirty_paths = tuple(line for line in status.splitlines() if line)
    if require_clean and dirty_paths:
        raise RuntimeError("Decision runtime source scope is dirty: " + ",".join(dirty_paths))
    file_hashes = runtime_source_file_hashes(active_root)
    return RuntimeSourceIdentity(
        git_commit_sha=revision,
        runtime_source_id=RUNTIME_SOURCE_ID,
        runtime_source_digest=runtime_source_digest(file_hashes),
        file_hashes=file_hashes,
        dirty_paths=dirty_paths,
    )

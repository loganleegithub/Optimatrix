"""Offline report identity for the bounded Shadow evidence bundle."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from market_tape import canonical_digest

from radar_runtime.shadow_identity import (
    RUN_RUNTIME_SOURCE_ID,
    RunRuntimeSourceIdentity,
    repository_root,
    run_runtime_source_identity,
)

RUN_REPORT_SOURCE_ID = "OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_OFFLINE_REPORT_SOURCE"
RUN_REPORT_SOURCE_SCOPE = (
    "apps/radar_runtime/src/radar_runtime/shadow_bundle.py",
    "apps/radar_runtime/src/radar_runtime/shadow_cli.py",
    "apps/radar_runtime/src/radar_runtime/shadow_report_identity.py",
)
RUN_REPORT_OPTIONAL_SOURCE_SCOPE = ("offline_audits",)


@dataclass(frozen=True, slots=True)
class RunReportSourceIdentity:
    git_commit_sha: str
    report_source_id: str
    report_source_digest: str
    online_runtime_source_id: str
    online_runtime_source_digest: str
    file_hashes: tuple[tuple[str, str], ...]
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            len(self.git_commit_sha) != 40
            or self.report_source_id != RUN_REPORT_SOURCE_ID
            or self.online_runtime_source_id != RUN_RUNTIME_SOURCE_ID
            or not self.report_source_digest
            or not self.online_runtime_source_digest
            or not self.file_hashes
        ):
            raise ValueError("run report source identity is invalid")


def _report_source_files(root: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for relative in RUN_REPORT_SOURCE_SCOPE + RUN_REPORT_OPTIONAL_SOURCE_SCOPE:
        target = root / relative
        if target.is_dir():
            files.update(path for path in target.rglob("*.py") if path.is_file())
        elif target.is_file():
            files.add(target)
        elif relative not in RUN_REPORT_OPTIONAL_SOURCE_SCOPE:
            raise RuntimeError(f"run report source scope is missing: {relative}")
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def run_report_source_file_hashes(
    root: Path | None = None,
) -> tuple[tuple[str, str], ...]:
    active_root = root or repository_root()
    return tuple(
        (
            path.relative_to(active_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _report_source_files(active_root)
    )


def run_report_source_digest(
    online_identity: RunRuntimeSourceIdentity,
    file_hashes: tuple[tuple[str, str], ...],
) -> str:
    return canonical_digest(
        {
            "report_source_id": RUN_REPORT_SOURCE_ID,
            "online_runtime_source_id": online_identity.runtime_source_id,
            "online_runtime_source_digest": online_identity.runtime_source_digest,
            "files": file_hashes,
        }
    )


def run_report_source_identity(
    *,
    root: Path | None = None,
    require_clean: bool,
) -> RunReportSourceIdentity:
    active_root = root or repository_root()
    online_identity = run_runtime_source_identity(
        root=active_root,
        require_clean=require_clean,
    )
    status = subprocess.run(
        (
            "git",
            "-C",
            str(active_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *RUN_REPORT_SOURCE_SCOPE,
            *RUN_REPORT_OPTIONAL_SOURCE_SCOPE,
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dirty_paths = tuple(line for line in status.splitlines() if line)
    if require_clean and dirty_paths:
        raise RuntimeError("public-Shadow report source scope is dirty: " + ",".join(dirty_paths))
    hashes = run_report_source_file_hashes(active_root)
    return RunReportSourceIdentity(
        git_commit_sha=online_identity.git_commit_sha,
        report_source_id=RUN_REPORT_SOURCE_ID,
        report_source_digest=run_report_source_digest(online_identity, hashes),
        online_runtime_source_id=online_identity.runtime_source_id,
        online_runtime_source_digest=online_identity.runtime_source_digest,
        file_hashes=hashes,
        dirty_paths=dirty_paths,
    )

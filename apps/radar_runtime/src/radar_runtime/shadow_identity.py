"""Online runtime and environment identities for the bounded Shadow run."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from market_tape import canonical_digest

RUN_RUNTIME_SOURCE_ID = "OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_ONLINE_RUNTIME_SOURCE"
RUN_RUNTIME_SOURCE_SCOPE = (
    "packages/market_tape/src/market_tape",
    "packages/options_domain/src/options_domain",
    "packages/short_vol_radar/src/short_vol_radar",
    "packages/shadow_engine/src/shadow_engine",
    "apps/radar_runtime/src/radar_runtime/__init__.py",
    "apps/radar_runtime/src/radar_runtime/deribit_public.py",
    "apps/radar_runtime/src/radar_runtime/fixture.py",
    "apps/radar_runtime/src/radar_runtime/outcome_identity.py",
    "apps/radar_runtime/src/radar_runtime/outcome_runtime.py",
    "apps/radar_runtime/src/radar_runtime/outcome_seal.py",
    "apps/radar_runtime/src/radar_runtime/runtime_identity.py",
    "apps/radar_runtime/src/radar_runtime/shadow_identity.py",
    "apps/radar_runtime/src/radar_runtime/shadow_runtime.py",
    "pyproject.toml",
)


@dataclass(frozen=True, slots=True)
class RuntimeEnvironmentIdentity:
    python_implementation: str
    python_version: str
    python_cache_tag: str
    websockets_version: str
    pyproject_sha256: str
    operating_system: str
    machine: str
    runtime_environment_digest: str

    def __post_init__(self) -> None:
        expected = canonical_digest(
            {
                "python_implementation": self.python_implementation,
                "python_version": self.python_version,
                "python_cache_tag": self.python_cache_tag,
                "websockets_version": self.websockets_version,
                "pyproject_sha256": self.pyproject_sha256,
            }
        )
        if self.runtime_environment_digest != expected:
            raise ValueError("runtime environment digest changed")


@dataclass(frozen=True, slots=True)
class RunRuntimeSourceIdentity:
    git_commit_sha: str
    runtime_source_id: str
    runtime_source_digest: str
    file_hashes: tuple[tuple[str, str], ...]
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            len(self.git_commit_sha) != 40
            or self.runtime_source_id != RUN_RUNTIME_SOURCE_ID
            or not self.runtime_source_digest
            or not self.file_hashes
        ):
            raise ValueError("run runtime source identity is invalid")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _source_files(
    root: Path,
    scope: tuple[str, ...],
    *,
    optional_scope: tuple[str, ...] = (),
) -> tuple[Path, ...]:
    files: set[Path] = set()
    for relative in scope:
        target = root / relative
        if target.is_dir():
            files.update(path for path in target.rglob("*.py") if path.is_file())
        elif target.is_file():
            files.add(target)
        elif relative in optional_scope:
            continue
        else:
            raise RuntimeError(f"run runtime source scope is missing: {relative}")
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def run_runtime_source_file_hashes(
    root: Path | None = None,
) -> tuple[tuple[str, str], ...]:
    active_root = root or repository_root()
    return tuple(
        (
            path.relative_to(active_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _source_files(active_root, RUN_RUNTIME_SOURCE_SCOPE)
    )


def run_runtime_source_digest(file_hashes: tuple[tuple[str, str], ...]) -> str:
    return canonical_digest(
        {
            "runtime_source_id": RUN_RUNTIME_SOURCE_ID,
            "files": file_hashes,
        }
    )


def run_runtime_source_identity(
    *,
    root: Path | None = None,
    require_clean: bool,
) -> RunRuntimeSourceIdentity:
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
            *RUN_RUNTIME_SOURCE_SCOPE,
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dirty_paths = tuple(line for line in status.splitlines() if line)
    if require_clean and dirty_paths:
        raise RuntimeError("public-Shadow runtime source scope is dirty: " + ",".join(dirty_paths))
    hashes = run_runtime_source_file_hashes(active_root)
    return RunRuntimeSourceIdentity(
        git_commit_sha=revision,
        runtime_source_id=RUN_RUNTIME_SOURCE_ID,
        runtime_source_digest=run_runtime_source_digest(hashes),
        file_hashes=hashes,
        dirty_paths=dirty_paths,
    )


def runtime_environment_identity(root: Path | None = None) -> RuntimeEnvironmentIdentity:
    active_root = root or repository_root()
    implementation = platform.python_implementation()
    python_version = platform.python_version()
    cache_tag = sys.implementation.cache_tag
    if cache_tag is None:
        raise RuntimeError("Python cache tag is unavailable")
    websockets_version = importlib.metadata.version("websockets")
    pyproject_digest = hashlib.sha256((active_root / "pyproject.toml").read_bytes()).hexdigest()
    equality_fields = {
        "python_implementation": implementation,
        "python_version": python_version,
        "python_cache_tag": cache_tag,
        "websockets_version": websockets_version,
        "pyproject_sha256": pyproject_digest,
    }
    return RuntimeEnvironmentIdentity(
        **equality_fields,
        operating_system=platform.system(),
        machine=platform.machine(),
        runtime_environment_digest=canonical_digest(equality_fields),
    )

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class StartupGuardError(RuntimeError):
    """A production observation precondition is not satisfied."""


GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


def validate_clean_git_outputs(*, head_output: str, status_output: str) -> str:
    head = head_output.strip()
    if GIT_COMMIT_PATTERN.fullmatch(head) is None:
        raise StartupGuardError("Git HEAD is not one exact full commit identity")
    if status_output:
        raise StartupGuardError("production observation requires a clean Git worktree")
    return head


def clean_code_identity(repository: Path) -> str:
    head = _git(repository, "rev-parse", "HEAD")
    status = _git(repository, "status", "--porcelain", "--untracked-files=all")
    return validate_clean_git_outputs(head_output=head, status_output=status)


def git_repository_root(start: Path) -> Path:
    output = _git(start, "rev-parse", "--show-toplevel").strip()
    if not output:
        raise StartupGuardError("Git repository root is empty")
    root = Path(output).resolve()
    if not root.is_dir():
        raise StartupGuardError("Git repository root is not a directory")
    return root


def _git(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StartupGuardError(f"Git identity check failed: {' '.join(arguments)}") from exc
    return completed.stdout

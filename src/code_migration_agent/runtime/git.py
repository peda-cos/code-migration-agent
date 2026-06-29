"""Git helpers for per-repository migration workspaces."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command fails."""


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Code Migration Agent")
    env.setdefault("GIT_AUTHOR_EMAIL", "agent@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "Code Migration Agent")
    env.setdefault("GIT_COMMITTER_EMAIL", "agent@localhost")
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def init_repo(root: Path) -> None:
    _git(root, "init", "-b", "main")
    # The per-workspace identity is local only; it never changes the user's config.
    _git(root, "config", "user.name", "Code Migration Agent")
    _git(root, "config", "user.email", "agent@localhost")
    _git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "--short", "HEAD").strip()


def create_branch(root: Path, branch: str = "migration/py3") -> None:
    _git(root, "checkout", "-b", branch)


def diff(root: Path, base: str = "main") -> str:
    return _git(root, "diff", base)


def log(root: Path) -> list[str]:
    raw = _git(root, "log", "--pretty=format:%h %s", "main..HEAD")
    return [line for line in raw.splitlines() if line.strip()]


def status(root: Path) -> str:
    return _git(root, "status", "--porcelain")

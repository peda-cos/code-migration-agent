"""Local subprocess sandbox with workspace confinement and timeouts."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from ..models import CommandResult

MAX_STREAM_CHARS = 20_000


class SandboxError(RuntimeError):
    """Raised for invalid sandbox paths or launch failures."""


class Sandbox(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> CommandResult: ...


def _truncate(text: str, limit: int = MAX_STREAM_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


class LocalSandbox:
    """Runs commands in a repo workspace; no shell, no network setup."""

    def __init__(self, root: Path, default_timeout_s: float = 120.0) -> None:
        self.root = root.resolve()
        self.default_timeout_s = default_timeout_s

    def _cwd(self, cwd: Path | None) -> Path:
        target = self.root if cwd is None else cwd
        resolved = target.resolve()
        if not resolved.is_relative_to(self.root):
            raise SandboxError(f"command cwd escapes workspace: {cwd}")
        return resolved

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> CommandResult:
        if not args:
            raise SandboxError("empty command")
        workdir = self._cwd(cwd)
        merged_env = os.environ.copy()
        existing_pythonpath = merged_env.get("PYTHONPATH")
        merged_env["PYTHONPATH"] = (
            str(self.root)
            if not existing_pythonpath
            else f"{self.root}{os.pathsep}{existing_pythonpath}"
        )
        merged_env["PYTHONDONTWRITEBYTECODE"] = "1"
        merged_env["PYTHONUNBUFFERED"] = "1"
        merged_env["PYTHONHASHSEED"] = "0"
        if env:
            merged_env.update(env)
        timeout = self.default_timeout_s if timeout_s is None else timeout_s
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(args),
                cwd=workdir,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise SandboxError(f"failed to launch {args[0]}: {exc}") from exc
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        duration = time.monotonic() - started
        return CommandResult(
            args=tuple(str(arg) for arg in args),
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=_truncate(stdout or ""),
            stderr=_truncate(stderr or ""),
            duration_s=duration,
            timed_out=timed_out,
        )


def copy_repo(source: Path, destination: Path) -> None:
    if destination.exists():
        raise SandboxError(f"destination already exists: {destination}")
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".cache", ".coverage*", ".pytest_cache"
        ),
    )

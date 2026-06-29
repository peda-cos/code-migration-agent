"""Confined tools exposed to the agent loop."""

from __future__ import annotations

from pathlib import Path

from ..build import run_build, run_tests
from ..gate import evaluate
from ..models import (
    BuildResult,
    Evaluation,
    FixerResult,
    MigrationSpec,
    TestResult,
)
from ..recipes.agent_fixes import apply_fixer as _apply_fixer
from ..runtime import git
from ..runtime.sandbox import LocalSandbox


class ToolError(RuntimeError):
    """Raised for invalid or out-of-workspace tool calls."""


class ToolBox:
    def __init__(
        self,
        root: Path,
        sandbox: LocalSandbox,
        spec: MigrationSpec,
        base_coverage: float | None,
        base_test_digest: str,
    ) -> None:
        self.root = root.resolve()
        self.sandbox = sandbox
        self.spec = spec
        self.base_coverage = base_coverage
        self.base_test_digest = base_test_digest

    def _resolve(self, path: str, *, write: bool) -> Path:
        if not path:
            raise ToolError("path is required")
        candidate = Path(path)
        if candidate.is_absolute():
            raise ToolError(f"absolute paths are not allowed: {path}")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise ToolError(f"path escapes workspace: {path}")
        relative = resolved.relative_to(self.root)
        if ".git" in relative.parts:
            raise ToolError("access to .git is not allowed")
        if write and (
            resolved == self.root / self.spec.test_dir
            or resolved.is_relative_to(self.root / self.spec.test_dir)
        ):
            raise ToolError("agent may not modify tests")
        return resolved

    def read_file(self, path: str, max_bytes: int = 20_000) -> str:
        resolved = self._resolve(path, write=False)
        if not resolved.is_file():
            raise ToolError(f"not a file: {path}")
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"cannot read {path}: {exc}") from exc
        if len(text) > max_bytes:
            return text[:max_bytes] + "\n...[truncated]"
        return text

    def edit_file(self, path: str, old: str, new: str) -> FixerResult:
        if not old:
            raise ToolError("old must not be empty")
        resolved = self._resolve(path, write=True)
        if not resolved.is_file():
            raise ToolError(f"not a file: {path}")
        try:
            source = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"cannot read {path}: {exc}") from exc
        occurrences = source.count(old)
        if occurrences != 1:
            raise ToolError(
                f"old text must occur exactly once in {path}; found {occurrences}"
            )
        resolved.write_text(source.replace(old, new, 1), encoding="utf-8")
        return FixerResult(
            fixer="edit_file",
            files=[resolved.relative_to(self.root).as_posix()],
            edits=1,
        )

    def apply_fixer(self, name: str) -> FixerResult:
        try:
            return _apply_fixer(name, self.root, self.spec)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc

    def run_build(self) -> BuildResult:
        return run_build(self.root, self.spec, self.sandbox)

    def run_test(self) -> TestResult:
        return run_tests(self.root, self.spec, self.sandbox, with_coverage=False)

    def git_diff(self) -> str:
        return git.diff(self.root)

    def evaluate(self) -> Evaluation:
        return evaluate(
            self.root,
            self.spec,
            self.sandbox,
            self.base_coverage,
            self.base_test_digest,
        )

    def commit(self, message: str) -> str:
        return git.commit_all(self.root, message)

    def list_files(self) -> list[str]:
        package_dir = self.root / self.spec.package.replace(".", "/")
        if not package_dir.exists():
            return []
        return [
            path.relative_to(self.root).as_posix()
            for path in sorted(package_dir.rglob("*.py"))
        ]

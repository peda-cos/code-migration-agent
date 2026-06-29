"""Typed data shared by the migration pipeline, benchmark, and dashboard."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class FailureClass(StrEnum):
    """Failure taxonomy. The first six names match the capstone spec."""

    DEP_UPGRADE_REQUIRED = "dep_upgrade_required"
    BUILD_TOOL_DRIFT = "build_tool_drift"
    CUSTOM_ANNOTATION = "custom_annotation"
    TEST_FLAKE = "test_flake"
    SYNTAX_EDGE_CASE = "syntax_edge_case"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COVERAGE_REGRESSION = "coverage_regression"
    TEST_INTEGRITY = "test_integrity"
    UNCLASSIFIED_FAILURE = "unclassified_failure"


@dataclass(frozen=True)
class Budgets:
    max_turns: int = 20
    max_seconds: float = 1800.0
    max_cost_usd: float = 8.0


@dataclass(frozen=True)
class MigrationSpec:
    name: str
    source: Path
    package: str = "app"
    test_dir: str = "tests"
    python_requirement: str = ">=3.12"
    budgets: Budgets = Budgets()


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    packaging_diagnostics: list[str] = field(default_factory=list)
    output: str = ""


@dataclass(frozen=True)
class TestResult:
    __test__ = False

    ok: bool
    ran: int
    failures: int
    output: str
    coverage: float | None = None


@dataclass(frozen=True)
class BaselineResult:
    coverage: float | None
    source: str
    tests_ran: int


@dataclass(frozen=True)
class GateResult:
    status: str
    delta: float | None
    reason: str = ""


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    failure_class: FailureClass | None
    reason: str
    build: BuildResult
    tests: TestResult | None = None
    coverage_delta: float | None = None


@dataclass(frozen=True)
class FixerResult:
    fixer: str
    files: list[str] = field(default_factory=list)
    edits: int = 0


@dataclass(frozen=True)
class LoopResult:
    outcome: str
    failure_class: FailureClass | None
    reason: str
    turns: int
    cost_usd: float
    duration_s: float
    agent_fixes: list[str] = field(default_factory=list)
    final_evaluation: Evaluation | None = None


@dataclass(frozen=True)
class RepoRun:
    name: str
    archetype: str
    mode: str
    outcome: str
    failure_class: FailureClass | None
    reason: str
    base_coverage: float | None
    base_coverage_source: str
    final_coverage: float | None
    coverage_delta: float | None
    turns: int
    cost_usd: float
    duration_s: float
    recipes_applied: dict[str, int] = field(default_factory=dict)
    agent_fixes: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    branch: str | None = None
    pr_path: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def to_jsonable(value: object) -> object:
    """Convert nested dataclasses/Paths/Enums to JSON-compatible values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field_info.name: to_jsonable(getattr(value, field_info.name))
            for field_info in dataclasses.fields(value)
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value

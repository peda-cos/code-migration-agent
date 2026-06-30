"""One-repository migration orchestrator: recipes, sandbox, agent, PR bundle."""

from __future__ import annotations

import json
import time
import tokenize
from pathlib import Path
from typing import Any, Literal

from .agent.loop import run_agent
from .agent.policy import DeterministicPolicy, Policy
from .agent.tools import ToolBox
from .build import baseline_probe
from .gate import evaluate, test_tree_digest
from .models import Budgets, Evaluation, FailureClass, MigrationSpec, RepoRun
from .pr import render_failure, render_pr, write
from .recipes import RECIPE_IDS, apply_recipes
from .recipes.base import RecipeParseError
from .recipes.legacy_syntax import normalize_source
from .runtime import git
from .runtime.sandbox import LocalSandbox, copy_repo

Mode = Literal["full", "recipes-only"]
_GITIGNORE_LINES = (".coverage", ".coverage.json", "__pycache__/", ".cache/", "*.pyc")


def _append_trace(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _ensure_gitignore(workspace: Path) -> None:
    path = workspace / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    for entry in _GITIGNORE_LINES:
        if entry not in lines:
            lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _recipe_targets(workspace: Path, spec: MigrationSpec) -> list[Path]:
    test_root = (workspace / spec.test_dir).resolve()
    targets: list[Path] = []
    for path in sorted(workspace.rglob("*.py")):
        if ".git" in path.parts or path.resolve().is_relative_to(test_root):
            continue
        targets.append(path)
    return targets


def _apply_deterministic(
    workspace: Path, spec: MigrationSpec
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    counts: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    for path in _recipe_targets(workspace, spec):
        relative = path.relative_to(workspace).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            legacy = normalize_source(source, str(path))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            events.append({"file": relative, "stage": "legacy_syntax", "error": True})
            continue
        current = legacy.module_code
        if current != source:
            path.write_text(current, encoding="utf-8")
            counts["legacy_syntax"] = counts.get("legacy_syntax", 0) + len(legacy.edits)
        try:
            updated, recipe_counts = apply_recipes(current, RECIPE_IDS)
        except RecipeParseError:
            events.append({"file": relative, "stage": "recipes", "error": True})
            continue
        if updated != current:
            path.write_text(updated, encoding="utf-8")
        for recipe_id, count in recipe_counts.items():
            counts[recipe_id] = counts.get(recipe_id, 0) + count
    return counts, events


def _final_coverage(evaluation: Evaluation) -> float | None:
    if evaluation.tests is None:
        return None
    return evaluation.tests.coverage


def migrate_repo(
    spec: MigrationSpec,
    out_root: Path,
    mode: Mode = "full",
    policy: Policy | None = None,
    budgets: Budgets | None = None,
    archetype: str = "manual",
) -> RepoRun:
    started = time.monotonic()
    source = spec.source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"repository does not exist: {source}")
    run_dir = out_root / "repos" / spec.name
    workspace = run_dir / "workspace"
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir()
    trace_path = evidence_dir / "trace.jsonl"
    _append_trace(trace_path, {"event": "start", "mode": mode, "archetype": archetype})

    copy_repo(source, workspace)
    _ensure_gitignore(workspace)
    git.init_repo(workspace)
    git.commit_all(workspace, f"base: import {spec.name}")
    git.create_branch(workspace)

    base_digest = test_tree_digest(source, spec.test_dir)
    baseline_dir = run_dir / "baseline"
    baseline = baseline_probe(
        source, spec, baseline_dir, LocalSandbox(baseline_dir)
    )
    _append_trace(
        trace_path,
        {
            "event": "baseline",
            "coverage": baseline.coverage,
            "source": baseline.source,
            "tests_ran": baseline.tests_ran,
        },
    )

    recipes, stage_events = _apply_deterministic(workspace, spec)
    for event in stage_events:
        _append_trace(trace_path, {"event": "stage_error", **event})
    if git.status(workspace):
        git.commit_all(
            workspace,
            f"recipe: apply {sum(recipes.values())} deterministic rewrites",
        )
    _append_trace(
        trace_path,
        {"event": "recipes", "edits": recipes, "total": sum(recipes.values())},
    )

    sandbox = LocalSandbox(workspace)
    initial_evaluation = evaluate(
        workspace, spec, sandbox, baseline.coverage, base_digest
    )
    _append_trace(
        trace_path,
        {
            "event": "evaluate",
            "passed": initial_evaluation.passed,
            "failure_class": (
                initial_evaluation.failure_class.value
                if initial_evaluation.failure_class
                else None
            ),
        },
    )

    loop_result = None
    active_budgets = budgets or spec.budgets
    if mode == "full" and not initial_evaluation.passed:
        toolbox = ToolBox(
            workspace, sandbox, spec, baseline.coverage, base_digest
        )
        loop_result = run_agent(
            toolbox,
            policy or DeterministicPolicy(),
            initial_evaluation,
            active_budgets,
        )
        _append_trace(
            trace_path,
            {
                "event": "agent",
                "turns": loop_result.turns,
                "cost_usd": loop_result.cost_usd,
                "fixes": loop_result.agent_fixes,
                "failure_class": (
                    loop_result.failure_class.value
                    if loop_result.failure_class
                    else None
                ),
            },
        )

    if loop_result is not None:
        outcome = loop_result.outcome
        failure_class = loop_result.failure_class
        reason = loop_result.reason
        turns = loop_result.turns
        cost_usd = loop_result.cost_usd
        agent_fixes = list(loop_result.agent_fixes)
        final_evaluation = loop_result.final_evaluation or initial_evaluation
    else:
        outcome = "passed" if initial_evaluation.passed else "failed"
        failure_class = initial_evaluation.failure_class
        reason = initial_evaluation.reason
        turns = 0
        cost_usd = 0.0
        agent_fixes = []
        final_evaluation = initial_evaluation

    final_coverage = _final_coverage(final_evaluation)
    coverage_delta = final_evaluation.coverage_delta
    if coverage_delta is None and baseline.coverage is not None and final_coverage is not None:
        coverage_delta = final_coverage - baseline.coverage

    if outcome == "passed" and git.status(workspace):
        git.commit_all(workspace, "chore: capture remaining migration edits")
    diff_text = git.diff(workspace)
    commits = git.log(workspace)
    branch = "migration/py3"
    pr_path: Path | None = None
    failure_path: Path | None = None
    if outcome == "passed":
        pr_path = write(
            run_dir / "pr.md",
            render_pr(
                spec,
                branch,
                recipes,
                agent_fixes,
                commits,
                baseline.coverage,
                final_coverage,
                coverage_delta,
                turns,
                cost_usd,
                diff_text[:12_000],
            ),
        )
    else:
        failure = failure_class or FailureClass.UNCLASSIFIED_FAILURE
        failure_path = write(
            run_dir / "failure.md",
            render_failure(
                spec,
                failure,
                reason,
                recipes,
                agent_fixes,
                final_evaluation.build.output,
                final_evaluation.tests.output if final_evaluation.tests else "",
                diff_text[:4_000],
            ),
        )

    evidence: dict[str, Any] = {
        "reason": reason,
        "build_ok": final_evaluation.build.ok,
        "tests_ok": (
            final_evaluation.tests.ok
            if final_evaluation.tests is not None
            else False
        ),
        "build_output": final_evaluation.build.output[-4_000:],
        "test_output": (
            final_evaluation.tests.output[-4_000:]
            if final_evaluation.tests is not None
            else ""
        ),
        "tests_ran": (
            final_evaluation.tests.ran if final_evaluation.tests is not None else 0
        ),
        "diff_excerpt": diff_text[:4_000] or "no source changes; see test output",
        "baseline_source": baseline.source,
        "baseline_tests_ran": baseline.tests_ran,
        "test_digest": base_digest,
        "failure_path": str(failure_path) if failure_path is not None else None,
    }
    duration = time.monotonic() - started
    run = RepoRun(
        name=spec.name,
        archetype=archetype,
        mode=mode,
        outcome=outcome,
        failure_class=failure_class,
        reason=reason,
        base_coverage=baseline.coverage,
        base_coverage_source=baseline.source,
        final_coverage=final_coverage,
        coverage_delta=coverage_delta,
        turns=turns,
        cost_usd=cost_usd,
        duration_s=duration,
        recipes_applied=recipes,
        agent_fixes=agent_fixes,
        commits=commits,
        branch=branch,
        pr_path=str(pr_path) if pr_path is not None else None,
        evidence=evidence,
    )
    _append_trace(
        trace_path,
        {
            "event": "final",
            "outcome": outcome,
            "failure_class": (
                failure_class.value if failure_class is not None else None
            ),
            "coverage": final_coverage,
            "duration_s": duration,
        },
    )
    return run

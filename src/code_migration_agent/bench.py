"""Benchmark runner, metrics, taxonomy, JSON, and dashboard output."""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .agent.llm import LLMPolicy, OpenAICompatibleClient
from .agent.policy import DeterministicPolicy, Policy
from .config import LLMConfig
from .corpus.generate import GeneratedRepo
from .dashboard import render_dashboard
from .migrate import migrate_repo
from .models import Budgets, FailureClass, RepoRun, to_jsonable

_MODE_SLUG = {"recipes_only": "recipes-only", "full": "full"}


def _policy_factory(name: str) -> Callable[[], Policy]:
    if name == "deterministic":
        return DeterministicPolicy
    if name == "llm":
        config = LLMConfig.from_env()
        client = OpenAICompatibleClient(config)
        return lambda: LLMPolicy(client, config.prices)
    raise ValueError(f"unknown policy: {name}")


def _run_mode(
    entries: Sequence[GeneratedRepo],
    mode_key: str,
    out_root: Path,
    policy_name: str,
    jobs: int,
) -> list[RepoRun]:
    mode_slug = _MODE_SLUG[mode_key]
    if mode_slug not in {"full", "recipes-only"}:
        raise ValueError(f"unknown mode: {mode_key}")
    factory = _policy_factory(policy_name)
    root = out_root / mode_key

    def run_one(entry: GeneratedRepo) -> RepoRun:
        return migrate_repo(
            entry.spec,
            root,
            mode="full" if mode_slug == "full" else "recipes-only",
            policy=factory() if mode_slug == "full" else None,
            archetype=entry.archetype,
        )

    if jobs <= 1:
        return [run_one(entry) for entry in entries]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_one, entry) for entry in entries]
        return [future.result() for future in futures]


def _metrics(runs: Sequence[RepoRun], mode: str) -> dict[str, Any]:
    total = len(runs)
    passed = [run for run in runs if run.outcome == "passed"]
    coverage_values = [
        run.coverage_delta for run in runs if run.coverage_delta is not None
    ]
    recipe_edits = sum(sum(run.recipes_applied.values()) for run in runs)
    agent_fixes = sum(len(run.agent_fixes) for run in runs)
    total_cost = sum(run.cost_usd for run in runs)
    durations = sorted(run.duration_s for run in passed)
    return {
        "pass_rate": len(passed) / total if total else 0.0,
        "passes": len(passed),
        "total": total,
        "mean_coverage_delta": (
            round(statistics.fmean(coverage_values), 4) if coverage_values else None
        ),
        "coverage_n": len(coverage_values),
        "cost_per_passing_repo": (
            round(total_cost / len(passed), 6) if passed else 0.0
        ),
        "agent_fix_share": (
            round(agent_fixes / (agent_fixes + recipe_edits), 4)
            if (agent_fixes + recipe_edits)
            else 0.0
        ),
        "agent_fixes": agent_fixes,
        "recipe_edits": recipe_edits,
        "ttfgb_median_s": (
            round(statistics.median(durations), 3) if durations else 0.0
        ),
        "mode": mode,
    }


def _taxonomy(runs: Sequence[RepoRun]) -> dict[str, Any]:
    classes: dict[str, Any] = {}
    for run in runs:
        if run.outcome == "passed":
            continue
        failure = run.failure_class or FailureClass.UNCLASSIFIED_FAILURE
        key = failure.value
        entry = classes.setdefault(key, {"count": 0, "exemplars": []})
        entry["count"] += 1
        if len(entry["exemplars"]) < 3:
            entry["exemplars"].append(
                {
                    "repo": run.name,
                    "reason": run.reason[:800],
                    "diff_excerpt": str(
                        run.evidence.get("diff_excerpt", "no source changes")
                    )[:1600],
                }
            )
    return classes


def _portable(value: Any, out_root: Path) -> Any:
    """Make artifact paths relative so the committed report is portable."""
    project_root = Path(__file__).resolve().parents[2]
    prefixes = (str(out_root.resolve()), str(project_root), str(Path.home()))
    if isinstance(value, str):
        result = value
        for prefix in prefixes:
            result = result.replace(prefix + "/", "")
            result = result.replace(prefix, "<project>")
        return result
    if isinstance(value, dict):
        return {key: _portable(item, out_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item, out_root) for item in value]
    return value


def run_benchmark(
    entries: Sequence[GeneratedRepo],
    out_root: Path,
    modes: Sequence[str] = ("recipes_only", "full"),
    policy_name: str = "deterministic",
    seed: int = 0,
    jobs: int = 1,
) -> dict[str, Any]:
    if not entries:
        raise ValueError("benchmark needs at least one repository")
    if jobs < 1:
        raise ValueError("jobs must be >= 1")
    out_root.mkdir(parents=True, exist_ok=True)
    runs_by_mode: dict[str, list[RepoRun]] = {}
    for mode_key in modes:
        if mode_key not in _MODE_SLUG:
            raise ValueError(f"unknown mode: {mode_key}")
        runs_by_mode[mode_key] = _run_mode(
            entries, mode_key, out_root, policy_name, jobs
        )

    default_budgets = Budgets()
    overrides = [
        {
            "name": entry.spec.name,
            "max_turns": entry.spec.budgets.max_turns,
            "max_seconds": entry.spec.budgets.max_seconds,
            "max_cost_usd": entry.spec.budgets.max_cost_usd,
        }
        for entry in entries
        if entry.spec.budgets != default_budgets
    ]
    result: dict[str, Any] = {
        "schema_version": 1,
        "corpus": {
            "kind": (
                "manifest"
                if all(entry.archetype == "manifest" for entry in entries)
                else "synthetic"
            ),
            "count": len(entries),
            "seed": seed,
            "archetypes": _archetype_counts(entries),
        },
        "config": {
            "policy": policy_name,
            "target": "3.12",
            "budgets": to_jsonable(default_budgets),
            "budget_overrides": overrides,
        },
        "modes": {
            mode_key: {"metrics": _metrics(runs, mode_key)}
            for mode_key, runs in runs_by_mode.items()
        },
        "runs": {
            mode_key: [_portable(to_jsonable(run), out_root) for run in runs]
            for mode_key, runs in runs_by_mode.items()
        },
        "taxonomy": {
            mode_key: _portable(_taxonomy(runs), out_root)
            for mode_key, runs in runs_by_mode.items()
        },
        "metrics": {
            mode_key: _metrics(runs, mode_key)
            for mode_key, runs in runs_by_mode.items()
        },
    }

    results_path = out_root / "results.json"
    results_path.write_text(
        json.dumps(to_jsonable(result), indent=2) + "\n", encoding="utf-8"
    )
    (out_root / "dashboard.html").write_text(
        render_dashboard(result), encoding="utf-8"
    )
    return result


def _archetype_counts(entries: Sequence[GeneratedRepo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.archetype] = counts.get(entry.archetype, 0) + 1
    return counts

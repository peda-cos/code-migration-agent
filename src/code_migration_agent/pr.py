"""Markdown PR and failure bundles for a migrated repository."""

from __future__ import annotations

from pathlib import Path

from .models import FailureClass, MigrationSpec


def _fence(diff: str) -> str:
    return "````diff\n" + diff.strip() + "\n````"


def render_pr(
    spec: MigrationSpec,
    branch: str,
    recipes: dict[str, int],
    agent_fixes: list[str],
    commits: list[str],
    base_coverage: float | None,
    final_coverage: float | None,
    coverage_delta: float | None,
    turns: int,
    cost_usd: float,
    diff: str,
) -> str:
    recipe_rows = "\n".join(
        f"| `{name}` | {count} |" for name, count in sorted(recipes.items())
    ) or "| _(none)_ | 0 |"
    fixes = "\n".join(f"- `{fixer}`" for fixer in agent_fixes) or "- _(no agent fix needed)_"
    commit_lines = "\n".join(f"- `{commit}`" for commit in commits) or "- _(none)_"
    delta = "n/a" if coverage_delta is None else f"{coverage_delta:+.2f} pp"
    base = "n/a" if base_coverage is None else f"{base_coverage:.2f}%"
    final = "n/a" if final_coverage is None else f"{final_coverage:.2f}%"
    return "\n".join(
        [
            f"# Migrate `{spec.name}` to Python {spec.python_requirement}",
            "",
            "Status: **green**",
            "",
            f"Branch: `{branch}`",
            "",
            "## Deterministic recipes",
            "",
            "| Recipe | Edits |",
            "|---|---:|",
            recipe_rows,
            "",
            "## Agent fixes",
            "",
            fixes,
            "",
            "## Commits",
            "",
            commit_lines,
            "",
            "## Test + coverage gate",
            "",
            f"- Coverage: {base} -> {final} ({delta})",
            "- All tests pass; tests were not modified.",
            f"- Agent turns: {turns}",
            f"- Cost: ${cost_usd:.4f}",
            "",
            "## Diff",
            "",
            _fence(diff or "(no source changes)"),
            "",
        ]
    )


def render_failure(
    spec: MigrationSpec,
    failure_class: FailureClass,
    reason: str,
    recipes: dict[str, int],
    agent_fixes: list[str],
    build_output: str,
    test_output: str,
    diff_excerpt: str,
) -> str:
    recipe_rows = "\n".join(
        f"- `{name}`: {count}" for name, count in sorted(recipes.items())
    ) or "- _(none)_"
    fixes = "\n".join(f"- `{fixer}`" for fixer in agent_fixes) or "- _(none)_"
    return "\n".join(
        [
            f"# Migration failure: `{spec.name}`",
            "",
            f"Failure class: **`{failure_class.value}`**",
            "",
            f"Reason: {reason}",
            "",
            "## Recipes",
            "",
            recipe_rows,
            "",
            "## Agent fixes attempted",
            "",
            fixes,
            "",
            "## Build evidence",
            "",
            "```text",
            build_output[-4000:] or "(empty)",
            "```",
            "",
            "## Test evidence",
            "",
            "```text",
            test_output[-4000:] or "(empty)",
            "```",
            "",
            "## Diff excerpt",
            "",
            "```diff",
            (diff_excerpt or "no source changes")[-4000:],
            "```",
            "",
            "The branch and workspace are retained for replay.",
            "",
        ]
    )


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path

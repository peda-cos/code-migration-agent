from pathlib import Path

from code_migration_agent.corpus.generate import GeneratedRepo, generate_corpus
from code_migration_agent.migrate import migrate_repo
from code_migration_agent.models import FailureClass
from code_migration_agent.runtime import git


def _entry(tmp_path: Path, archetype: str) -> GeneratedRepo:
    entries = generate_corpus(50, 7, tmp_path / "corpus")
    return next(entry for entry in entries if entry.archetype == archetype)


def test_recipe_only_migration_creates_green_pr(tmp_path):
    entry = _entry(tmp_path, "legacy_syntax")
    original = (entry.spec.source / "app" / "report.py").read_text(encoding="utf-8")
    run = migrate_repo(
        entry.spec, tmp_path / "out", mode="full", archetype=entry.archetype
    )
    assert run.outcome == "passed"
    assert run.failure_class is None
    assert run.branch == "migration/py3"
    assert run.pr_path is not None
    pr = Path(run.pr_path)
    assert pr.is_file()
    text = pr.read_text(encoding="utf-8")
    assert "Deterministic recipes" in text
    assert "Test + coverage gate" in text
    assert "## Diff" in text
    assert run.recipes_applied["legacy_syntax"] > 0
    assert run.turns == 0
    assert any(commit.endswith("rewrites") for commit in run.commits)
    workspace = Path(run.pr_path).parent / "workspace"
    assert git.status(workspace) == ""
    assert (entry.spec.source / "app" / "report.py").read_text(encoding="utf-8") == original


def test_agent_unlocks_a_repo_that_recipes_fail(tmp_path):
    entry = _entry(tmp_path, "reduce_import")
    full = migrate_repo(
        entry.spec, tmp_path / "full", mode="full", archetype=entry.archetype
    )
    assert full.outcome == "passed"
    assert "functools_reduce" in full.agent_fixes
    assert any("agent:" in commit for commit in full.commits)
    assert full.final_coverage is not None

    recipes_only = migrate_repo(
        entry.spec,
        tmp_path / "recipes",
        mode="recipes-only",
        archetype=entry.archetype,
    )
    assert recipes_only.outcome == "failed"
    assert recipes_only.failure_class is FailureClass.SYNTAX_EDGE_CASE
    assert recipes_only.agent_fixes == []
    assert recipes_only.pr_path is None


def test_coverage_regression_is_filed_with_evidence(tmp_path):
    entry = _entry(tmp_path, "coverage_trim")
    run = migrate_repo(
        entry.spec, tmp_path / "out", mode="full", archetype=entry.archetype
    )
    assert run.outcome == "failed"
    assert run.failure_class is FailureClass.COVERAGE_REGRESSION
    assert run.base_coverage is not None and run.final_coverage is not None
    assert run.coverage_delta is not None and run.coverage_delta < -2.0
    assert "commands_shim" in run.agent_fixes
    failure_path = Path(str(run.evidence["failure_path"]))
    assert failure_path.is_file()
    assert "coverage_regression" in failure_path.read_text(encoding="utf-8")


def test_tight_budget_halts_with_current_diff(tmp_path):
    entry = _entry(tmp_path, "tight_budget")
    assert entry.spec.budgets.max_turns == 1
    run = migrate_repo(
        entry.spec, tmp_path / "out", mode="full", archetype=entry.archetype
    )
    assert run.outcome == "failed"
    assert run.failure_class is FailureClass.BUDGET_EXHAUSTED
    assert run.turns == 1
    assert "turn budget" in run.reason
    failure_path = Path(str(run.evidence["failure_path"]))
    assert failure_path.is_file()

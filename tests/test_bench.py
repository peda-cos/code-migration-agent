import json
from pathlib import Path

from code_migration_agent.bench import run_benchmark
from code_migration_agent.corpus.generate import generate_corpus


def test_benchmark_schema_and_taxonomy(tmp_path: Path):
    entries = generate_corpus(12, 11, tmp_path / "corpus")
    result = run_benchmark(entries, tmp_path / "out", seed=11)

    assert result["schema_version"] == 1
    assert result["corpus"]["count"] == 12
    assert len(result["runs"]["full"]) == 12
    assert len(result["runs"]["recipes_only"]) == 12
    full = result["modes"]["full"]["metrics"]
    recipes = result["modes"]["recipes_only"]["metrics"]
    assert full["passes"] == 9
    assert recipes["passes"] == 4
    assert full["pass_rate"] == 9 / 12
    assert recipes["pass_rate"] == 4 / 12
    assert full["agent_fix_share"] > 0
    assert full["cost_per_passing_repo"] == 0.0
    assert full["ttfgb_median_s"] > 0
    assert result["taxonomy"]["full"]["custom_annotation"]["count"] == 1
    assert result["taxonomy"]["full"]["dep_upgrade_required"]["count"] == 1
    assert result["taxonomy"]["full"]["test_flake"]["count"] == 1
    assert result["taxonomy"]["recipes_only"]["dep_upgrade_required"]["count"] >= 1

    results_path = tmp_path / "out" / "results.json"
    dashboard_path = tmp_path / "out" / "dashboard.html"
    assert results_path.is_file()
    assert dashboard_path.is_file()
    parsed = json.loads(results_path.read_text(encoding="utf-8"))
    assert parsed["modes"]["full"]["metrics"]["passes"] == 9
    dashboard = dashboard_path.read_text(encoding="utf-8")
    assert "Failure taxonomy" in dashboard
    assert "custom_annotation" in dashboard


def test_benchmark_outcomes_are_deterministic(tmp_path: Path):
    entries = generate_corpus(12, 11, tmp_path / "corpus")
    first = run_benchmark(entries, tmp_path / "first", modes=("full",), seed=11)
    second = run_benchmark(entries, tmp_path / "second", modes=("full",), seed=11)
    first_outcomes = [
        (run["name"], run["outcome"], run["failure_class"])
        for run in first["runs"]["full"]
    ]
    second_outcomes = [
        (run["name"], run["outcome"], run["failure_class"])
        for run in second["runs"]["full"]
    ]
    assert first_outcomes == second_outcomes

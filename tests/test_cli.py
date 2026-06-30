import json
from pathlib import Path

from code_migration_agent.cli import main
from code_migration_agent.corpus.generate import generate_corpus


def _reduce_repo(tmp_path: Path) -> Path:
    entries = generate_corpus(50, 3, tmp_path / "corpus")
    return next(
        entry.spec.source for entry in entries if entry.archetype == "reduce_import"
    )


def test_recipes_command(capsys):
    assert main(["recipes"]) == 0
    output = capsys.readouterr().out
    assert "legacy_syntax" in output
    assert "moved_imports" in output


def test_migrate_example_and_preserve_source(tmp_path, capsys):
    example = Path("examples/legacy_service").resolve()
    before = (example / "app" / "service.py").read_text(encoding="utf-8")
    assert main(["migrate", str(example), "--out", str(tmp_path / "out")]) == 0
    output = capsys.readouterr().out
    assert "[recipe]" in output
    assert "[build] OK" in output
    assert "[tests]" in output
    assert "[pr]" in output
    assert "branch migration/py3" in output
    assert (tmp_path / "out" / "repos" / "legacy_service" / "pr.md").is_file()
    assert (example / "app" / "service.py").read_text(encoding="utf-8") == before


def test_recipes_only_failure_exit_code(tmp_path, capsys):
    repo = _reduce_repo(tmp_path)
    assert main(["migrate", str(repo), "--mode", "recipes-only", "--out", str(tmp_path / "out")]) == 1
    output = capsys.readouterr().out
    assert "[fail]" in output
    assert "syntax_edge_case" in output


def test_dashboard_command(tmp_path):
    results = {
        "corpus": {"kind": "synthetic", "count": 0},
        "modes": {"full": {"metrics": {}}, "recipes_only": {"metrics": {}}},
        "taxonomy": {},
        "runs": {},
    }
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    out = tmp_path / "dashboard.html"
    assert main(["dashboard", str(results_path), "--out", str(out)]) == 0
    assert out.is_file()
    assert "Code Migration Agent" in out.read_text(encoding="utf-8")


def test_missing_repository_is_usage_error(tmp_path, capsys):
    assert main(["migrate", str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 2
    assert "repository does not exist" in capsys.readouterr().err


def test_bench_cli_writes_results(tmp_path, capsys):
    assert main(["bench", "--count", "4", "--seed", "5", "--out", str(tmp_path / "bench")]) == 0
    output = capsys.readouterr().out
    assert "full:" in output
    assert (tmp_path / "bench" / "results.json").is_file()
    assert (tmp_path / "bench" / "dashboard.html").is_file()

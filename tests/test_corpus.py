import json
from pathlib import Path

import pytest

from code_migration_agent.corpus.generate import (
    MAX_CORPUS_SIZE,
    generate_corpus,
    load_manifest_corpus,
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_corpus_has_fixed_archetype_distribution(tmp_path):
    entries = generate_corpus(50, 20261123, tmp_path / "corpus")
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.archetype] = counts.get(entry.archetype, 0) + 1
    assert len(entries) == 50
    assert len({entry.spec.name for entry in entries}) == 50
    assert counts == {
        "legacy_syntax": 5,
        "dict_methods": 4,
        "builtin_aliases": 4,
        "stdlib_imports": 4,
        "reduce_import": 4,
        "urllib2_request": 4,
        "cmp_sort": 4,
        "keys_indexing": 3,
        "packaging_drift": 3,
        "custom_metaclass": 3,
        "missing_dependency": 3,
        "flaky_test": 2,
        "coverage_trim": 2,
        "semantic_division": 2,
        "py2_exec": 1,
        "tight_budget": 2,
    }
    for entry in entries:
        assert (entry.spec.source / "app" / "__init__.py").is_file()
        assert (entry.spec.source / "tests").is_dir()


def test_generation_is_deterministic_and_seed_sensitive(tmp_path):
    first = generate_corpus(50, 7, tmp_path / "a")
    second = generate_corpus(50, 7, tmp_path / "b")
    different = generate_corpus(50, 8, tmp_path / "c")
    assert _snapshot(tmp_path / "a") == _snapshot(tmp_path / "b")
    assert _snapshot(tmp_path / "a") != _snapshot(tmp_path / "c")
    assert [entry.spec.name for entry in first] == [entry.spec.name for entry in second]
    assert [entry.archetype for entry in first] == [entry.archetype for entry in different]


def test_generate_corpus_count_bounds(tmp_path):
    with pytest.raises(ValueError):
        generate_corpus(0, 1, tmp_path / "x")
    with pytest.raises(ValueError):
        generate_corpus(MAX_CORPUS_SIZE + 1, 1, tmp_path / "y")


def test_manifest_loader_applies_budget_overrides(tmp_path):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repos": [
                    {
                        "name": "local",
                        "path": "repo",
                        "package": "app",
                        "test_dir": "tests",
                        "budgets": {"max_turns": 3, "max_cost_usd": 1.5},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    entries = load_manifest_corpus(manifest)
    assert entries[0].spec.name == "local"
    assert entries[0].archetype == "manifest"
    assert entries[0].spec.budgets.max_turns == 3
    assert entries[0].spec.budgets.max_cost_usd == 1.5


def test_manifest_rejects_duplicate_names(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repos": [
                    {"name": "x", "path": str(tmp_path)},
                    {"name": "x", "path": str(tmp_path)},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_manifest_corpus(manifest)

"""Deterministic corpus generation and local manifest loading."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import Budgets, MigrationSpec
from .templates import ARCHETYPES, MAX_CORPUS_SIZE, Archetype


@dataclass(frozen=True)
class GeneratedRepo:
    spec: MigrationSpec
    archetype: str


def _schedule(count: int) -> list[tuple[Archetype, int]]:
    slots: list[tuple[Archetype, int]] = []
    depth = 0
    while len(slots) < MAX_CORPUS_SIZE:
        added = False
        for archetype in ARCHETYPES:
            if depth < archetype.count:
                slots.append((archetype, depth))
                added = True
        if not added:
            break
        depth += 1
    return slots[:count]


def generate_corpus(count: int, seed: int, dest: Path) -> list[GeneratedRepo]:
    if count < 1 or count > MAX_CORPUS_SIZE:
        raise ValueError(f"count must be between 1 and {MAX_CORPUS_SIZE}")
    dest.mkdir(parents=True, exist_ok=True)
    generated: list[GeneratedRepo] = []
    for index, (archetype, variant) in enumerate(_schedule(count)):
        repo_name = f"r{index:03d}_{archetype.name}_{variant:02d}"
        repo_dir = dest / repo_name
        if repo_dir.exists():
            raise FileExistsError(f"corpus repo already exists: {repo_dir}")
        repo_dir.mkdir(parents=True)
        rng = random.Random(seed * 1_000 + index)
        files = archetype.builder(repo_name, variant, rng)
        for relative, content in sorted(files.items()):
            path = repo_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        spec = MigrationSpec(
            name=repo_name,
            source=repo_dir,
            package="app",
            test_dir="tests",
            budgets=archetype.budgets,
        )
        generated.append(GeneratedRepo(spec=spec, archetype=archetype.name))
    return generated


def _budgets_from_entry(entry: dict[str, Any]) -> Budgets:
    raw = entry.get("budgets", {})
    if not isinstance(raw, dict):
        raise ValueError("manifest budgets must be an object")
    return Budgets(
        max_turns=int(raw.get("max_turns", 20)),
        max_seconds=float(raw.get("max_seconds", 1800.0)),
        max_cost_usd=float(raw.get("max_cost_usd", 8.0)),
    )


def load_manifest_corpus(path: Path) -> list[GeneratedRepo]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid corpus manifest: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        raise ValueError("corpus manifest must contain a repos array")
    base = path.resolve().parent
    seen: set[str] = set()
    result: list[GeneratedRepo] = []
    for entry in data["repos"]:
        if not isinstance(entry, dict):
            raise ValueError("manifest repo entries must be objects")
        name = entry.get("name")
        raw_path = entry.get("path")
        if not isinstance(name, str) or not name:
            raise ValueError("manifest repo needs a non-empty name")
        if name in seen:
            raise ValueError(f"duplicate repo name: {name}")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError(f"repo {name} needs a path")
        source = Path(raw_path)
        if not source.is_absolute():
            source = (base / source).resolve()
        if not source.is_dir():
            raise ValueError(f"repo source does not exist: {source}")
        seen.add(name)
        spec = MigrationSpec(
            name=name,
            source=source,
            package=str(entry.get("package", "app")),
            test_dir=str(entry.get("test_dir", "tests")),
            budgets=_budgets_from_entry(entry),
        )
        result.append(GeneratedRepo(spec=spec, archetype="manifest"))
    if not result:
        raise ValueError("corpus manifest has no repos")
    return result


def archetype_counts(generated: list[GeneratedRepo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for repo in generated:
        counts[repo.archetype] = counts.get(repo.archetype, 0) + 1
    return counts

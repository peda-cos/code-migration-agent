"""Command-line interface for migration, benchmark, and dashboard runs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .agent.llm import LLMPolicy, OpenAICompatibleClient
from .agent.policy import DeterministicPolicy, Policy
from .bench import run_benchmark
from .config import LLMConfig, LLMConfigurationError
from .corpus.generate import generate_corpus, load_manifest_corpus
from .dashboard import write_dashboard
from .migrate import migrate_repo
from .models import Budgets, MigrationSpec, RepoRun, to_jsonable
from .recipes import RECIPES


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cma", description="Deterministic Python migration with a budgeted agent loop."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="migrate one repository")
    migrate.add_argument("repo", type=Path)
    migrate.add_argument("--out", type=Path, default=Path(".cache/migrate"))
    migrate.add_argument("--mode", choices=("full", "recipes-only"), default="full")
    migrate.add_argument("--policy", choices=("deterministic", "llm"), default="deterministic")
    migrate.add_argument("--package")
    migrate.add_argument("--test-dir", default="tests")
    migrate.add_argument("--max-turns", type=int, default=20)
    migrate.add_argument("--max-seconds", type=float, default=1800.0)
    migrate.add_argument("--max-cost", type=float, default=8.0)
    migrate.add_argument("--json", action="store_true")

    bench = sub.add_parser("bench", help="run the migration benchmark")
    bench.add_argument("--corpus", choices=("synthetic", "manifest"), default="synthetic")
    bench.add_argument("--count", type=int, default=50)
    bench.add_argument("--seed", type=int, default=20261123)
    bench.add_argument("--manifest", type=Path)
    bench.add_argument("--out", type=Path, default=Path(".cache/bench"))
    bench.add_argument("--policy", choices=("deterministic", "llm"), default="deterministic")
    bench.add_argument("--jobs", type=int, default=1)
    bench.add_argument("--json", action="store_true")

    dashboard = sub.add_parser("dashboard", help="render a results JSON file")
    dashboard.add_argument("results", type=Path)
    dashboard.add_argument("--out", type=Path, required=True)

    sub.add_parser("recipes", help="list deterministic recipes")
    return parser


def _resolve_package(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    if (repo / "app" / "__init__.py").is_file():
        return "app"
    candidates = [
        path.name
        for path in sorted(repo.iterdir())
        if path.is_dir()
        and (path / "__init__.py").is_file()
        and path.name not in {"tests", "test", ".git", ".venv"}
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        "cannot infer package; use --package. Candidates: "
        + (", ".join(candidates) if candidates else "none")
    )


def _policy(kind: str) -> Policy:
    if kind == "deterministic":
        return DeterministicPolicy()
    config = LLMConfig.from_env()
    return LLMPolicy(OpenAICompatibleClient(config), config.prices)


def _print_run(run: RepoRun) -> None:
    recipe_total = sum(run.recipes_applied.values())
    recipe_detail = ", ".join(
        f"{name}={count}" for name, count in sorted(run.recipes_applied.items())
    )
    print(f"[recipe] {recipe_total} rewrites applied ({recipe_detail or 'none'})")
    build_ok = bool(run.evidence.get("build_ok"))
    build_output = str(run.evidence.get("build_output", "")).strip().splitlines()
    print("[build] OK" if build_ok else f"[build] FAIL: {build_output[0] if build_output else 'see evidence'}")
    if run.turns:
        print(
            f"[agent] turns={run.turns} classify: {run.failure_class or 'none'}; "
            f"fixes={', '.join(run.agent_fixes) or 'none'}"
        )
    tests_ok = bool(run.evidence.get("tests_ok"))
    base = "n/a" if run.base_coverage is None else f"{run.base_coverage:.1f}"
    final = "n/a" if run.final_coverage is None else f"{run.final_coverage:.1f}"
    if tests_ok:
        print(
            f"[tests] {run.evidence.get('tests_ran', 0)}/"
            f"{run.evidence.get('tests_ran', 0)} passing; coverage {base}% -> {final}%"
        )
    else:
        print(f"[tests] FAIL; coverage {base}% -> {final}%")
    if run.outcome == "passed":
        print(
            f"[pr] branch {run.branch}; bundle {run.pr_path} "
            f"(turns={run.turns}, cost=${run.cost_usd:.2f})"
        )
    else:
        evidence = Path(str(run.evidence.get("failure_path") or "failure.md"))
        print(f"[fail] {run.failure_class}: {run.reason}; evidence {evidence}")


def _cmd_migrate(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    if not repo.is_dir():
        raise ValueError(f"repository does not exist: {repo}")
    package = _resolve_package(repo, args.package)
    budgets = Budgets(
        max_turns=args.max_turns,
        max_seconds=args.max_seconds,
        max_cost_usd=args.max_cost,
    )
    spec = MigrationSpec(
        name=repo.name,
        source=repo,
        package=package,
        test_dir=args.test_dir,
        budgets=budgets,
    )
    run = migrate_repo(
        spec,
        args.out.expanduser().resolve(),
        mode=args.mode,
        policy=_policy(args.policy) if args.mode == "full" else None,
        budgets=budgets,
    )
    if args.json:
        print(json.dumps(to_jsonable(run), indent=2))
    else:
        _print_run(run)
    return 0 if run.outcome == "passed" else 1


def _cmd_bench(args: argparse.Namespace) -> int:
    out = args.out.expanduser().resolve()
    temporary: Path | None = None
    if args.corpus == "manifest":
        if args.manifest is None:
            raise ValueError("--manifest is required for --corpus manifest")
        entries = load_manifest_corpus(args.manifest.expanduser().resolve())
    else:
        temporary = Path(tempfile.mkdtemp(prefix="cma-corpus-"))
        entries = generate_corpus(args.count, args.seed, temporary)
    try:
        result = run_benchmark(
            entries,
            out,
            policy_name=args.policy,
            seed=args.seed,
            jobs=args.jobs,
        )
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
    if args.json:
        print(json.dumps(to_jsonable(result), indent=2))
    else:
        for mode in ("full", "recipes_only"):
            metrics = result["modes"][mode]["metrics"]
            print(
                f"{mode}: {metrics['passes']}/{metrics['total']} passed "
                f"({metrics['pass_rate'] * 100:.1f}%), "
                f"coverage Δ {metrics['mean_coverage_delta']} pp, "
                f"agent fix share {metrics['agent_fix_share'] * 100:.1f}%"
            )
        print(f"results: {out / 'results.json'}")
        print(f"dashboard: {out / 'dashboard.html'}")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    path = write_dashboard(
        args.results.expanduser().resolve(), args.out.expanduser().resolve()
    )
    print(f"dashboard: {path}")
    return 0


def _cmd_recipes() -> int:
    print("legacy_syntax: token-position Python 2 statement normalization")
    for recipe in RECIPES.values():
        print(f"{recipe.recipe_id}: {recipe.description}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "migrate":
            return _cmd_migrate(args)
        if args.command == "bench":
            return _cmd_bench(args)
        if args.command == "dashboard":
            return _cmd_dashboard(args)
        if args.command == "recipes":
            return _cmd_recipes()
    except (ValueError, FileExistsError, FileNotFoundError, LLMConfigurationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

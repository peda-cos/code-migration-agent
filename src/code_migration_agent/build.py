"""Build and test execution, package drift checks, and coverage measurement."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

from .config import TARGET_PYTHON
from .models import BaselineResult, BuildResult, MigrationSpec, TestResult
from .recipes.legacy_syntax import normalize_source
from .runtime.sandbox import LocalSandbox, copy_repo

_RAN_RE = re.compile(r"Ran (\d+) tests?")
_FAILED_RE = re.compile(r"FAILED \((.*?)\)")
_COUNT_RE = re.compile(r"(failures|errors)=(\d+)")


def package_drift(repo_root: Path, target: str = TARGET_PYTHON) -> list[str]:
    diagnostics: list[str] = []
    setup = repo_root / "setup.py"
    if setup.exists():
        text = setup.read_text(encoding="utf-8", errors="replace")
        if "use_2to3" in text:
            diagnostics.append("setup.py uses removed setuptools use_2to3 option")
        if re.search(r"(^|\n)\s*(from|import)\s+distutils", text):
            diagnostics.append("setup.py imports removed distutils package")
        if re.search(r"python_requires\s*=\s*['\"][^'\"]*\b2\.", text):
            diagnostics.append("setup.py python_requires still targets Python 2")
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            diagnostics.append(f"pyproject.toml is invalid TOML: {exc}")
        else:
            project = data.get("project")
            requires = project.get("requires-python") if isinstance(project, dict) else None
            if isinstance(requires, str) and re.search(
                r"(^|[<>=!~,\s])2(\.|$)", requires
            ):
                diagnostics.append(
                    f"pyproject requires-python={requires!r} excludes Python {target}"
                )
    return diagnostics


def run_build(
    repo_root: Path, spec: MigrationSpec, sandbox: LocalSandbox
) -> BuildResult:
    diagnostics = package_drift(repo_root)
    if diagnostics:
        return BuildResult(
            ok=False,
            packaging_diagnostics=diagnostics,
            output="\n".join(diagnostics),
        )
    if not (repo_root / spec.test_dir).is_dir():
        return BuildResult(
            ok=False,
            packaging_diagnostics=[],
            output=f"test directory not found: {spec.test_dir}",
        )
    result = sandbox.run(
        [
            sys.executable,
            "-m",
            "code_migration_agent.runtime.checkrepo",
            str(repo_root),
            spec.package,
            spec.test_dir,
        ],
        cwd=repo_root,
    )
    return BuildResult(
        ok=result.returncode == 0 and not result.timed_out,
        packaging_diagnostics=[],
        output=result.output,
    )


def _test_counts(output: str) -> tuple[int, int]:
    ran_match = _RAN_RE.search(output)
    ran = int(ran_match.group(1)) if ran_match else 0
    failures = 0
    failed_match = _FAILED_RE.search(output)
    if failed_match:
        for _name, value in _COUNT_RE.findall(failed_match.group(1)):
            failures += int(value)
    return ran, failures


def _read_coverage(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        statements = int(totals.get("num_statements", 0))
        covered = int(totals.get("covered_lines", 0))
        if statements <= 0 or covered <= 0:
            return None
        return float(totals["percent_covered"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def run_tests(
    repo_root: Path,
    spec: MigrationSpec,
    sandbox: LocalSandbox,
    with_coverage: bool = True,
) -> TestResult:
    if not (repo_root / spec.test_dir).is_dir():
        return TestResult(
            ok=False,
            ran=0,
            failures=0,
            output=f"test directory not found: {spec.test_dir}",
        )
    discover = ["-m", "unittest", "discover", "-s", spec.test_dir]
    result = sandbox.run([sys.executable, *discover], cwd=repo_root)
    ran, failures = _test_counts(result.output)
    output = result.output
    coverage: float | None = None
    if with_coverage and not result.timed_out:
        coverage_file = repo_root / ".coverage"
        coverage_json = repo_root / ".coverage.json"
        env = {"COVERAGE_FILE": str(coverage_file)}
        cov_run = sandbox.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--source",
                spec.package,
                *discover,
            ],
            cwd=repo_root,
            env=env,
        )
        cov_export = sandbox.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "-o",
                str(coverage_json),
            ],
            cwd=repo_root,
            env=env,
        )
        if cov_export.returncode == 0:
            coverage = _read_coverage(coverage_json)
        if cov_run.timed_out:
            output += "\ncoverage run timed out"
    return TestResult(
        ok=result.returncode == 0 and not result.timed_out,
        ran=ran,
        failures=failures,
        output=output,
        coverage=coverage,
    )


def baseline_probe(
    source: Path, spec: MigrationSpec, workdir: Path, sandbox: LocalSandbox
) -> BaselineResult:
    copy_repo(source, workdir)
    test_root = workdir / spec.test_dir
    for path in sorted(workdir.rglob("*.py")):
        if path.is_relative_to(test_root):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        normalized = normalize_source(original, str(path)).module_code
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
    tests = run_tests(workdir, spec, sandbox, with_coverage=True)
    return BaselineResult(
        coverage=tests.coverage,
        source="measured_normalized_base" if tests.coverage is not None else "unavailable",
        tests_ran=tests.ran,
    )

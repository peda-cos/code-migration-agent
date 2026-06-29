"""End-to-end build/test/integrity/coverage evaluation for one repository."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .build import run_build, run_tests
from .classify import classify_build, classify_tests
from .coverage_gate import CoverageGate
from .models import Evaluation, FailureClass, MigrationSpec
from .runtime.sandbox import LocalSandbox


def test_tree_digest(repo_root: Path, test_dir: str) -> str:
    digest = hashlib.sha256()
    root = repo_root / test_dir
    if not root.exists():
        digest.update(b"<missing-tests>")
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(repo_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _tail(text: str, limit: int = 1600) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]


def evaluate(
    repo_root: Path,
    spec: MigrationSpec,
    sandbox: LocalSandbox,
    base_coverage: float | None,
    base_test_digest: str,
) -> Evaluation:
    build = run_build(repo_root, spec, sandbox)
    if not build.ok:
        return Evaluation(
            passed=False,
            failure_class=classify_build(build),
            reason=_tail(build.output),
            build=build,
        )

    tests = run_tests(repo_root, spec, sandbox, with_coverage=True)
    if not tests.ok:
        rerun = run_tests(repo_root, spec, sandbox, with_coverage=False)
        if rerun.ok:
            return Evaluation(
                passed=False,
                failure_class=FailureClass.TEST_FLAKE,
                reason="test suite failed once and passed on an unchanged rerun",
                build=build,
                tests=tests,
            )
        return Evaluation(
            passed=False,
            failure_class=classify_tests(tests, repo_root),
            reason=_tail(tests.output),
            build=build,
            tests=tests,
        )

    current_digest = test_tree_digest(repo_root, spec.test_dir)
    if current_digest != base_test_digest:
        return Evaluation(
            passed=False,
            failure_class=FailureClass.TEST_INTEGRITY,
            reason="test tree changed; test invariance is enforced",
            build=build,
            tests=tests,
        )

    gate = CoverageGate().check(base_coverage, tests.coverage)
    if gate.status == "regressed":
        return Evaluation(
            passed=False,
            failure_class=FailureClass.COVERAGE_REGRESSION,
            reason=gate.reason,
            build=build,
            tests=tests,
            coverage_delta=gate.delta,
        )
    return Evaluation(
        passed=True,
        failure_class=None,
        reason=gate.reason,
        build=build,
        tests=tests,
        coverage_delta=gate.delta,
    )

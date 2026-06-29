from pathlib import Path

from code_migration_agent.coverage_gate import CoverageGate
from code_migration_agent.gate import evaluate, test_tree_digest as digest
from code_migration_agent.models import FailureClass, MigrationSpec
from code_migration_agent.runtime.sandbox import LocalSandbox


def test_coverage_gate_tolerance_boundary() -> None:
    gate = CoverageGate(tolerance_pp=2.0)
    assert gate.check(90.0, 88.0).status == "passed"
    assert gate.check(90.0, 87.99).status == "regressed"
    assert gate.check(None, 90.0).status == "unmeasured"
    assert gate.check(90.0, None).status == "unmeasured"


def _repo(root: Path, test_body: str) -> MigrationSpec:
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (root / "tests" / "test_calc.py").write_text(test_body, encoding="utf-8")
    (root / "setup.py").write_text(
        'from setuptools import setup\nsetup(name="calc", packages=["app"])\n',
        encoding="utf-8",
    )
    return MigrationSpec(name="calc", source=root)


def test_digest_changes_with_test_bytes(tmp_path) -> None:
    _repo(tmp_path, "def test_x():\n    assert True\n")
    first = digest(tmp_path, "tests")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "def test_x():\n    assert 1\n", encoding="utf-8"
    )
    assert digest(tmp_path, "tests") != first


def test_test_integrity_violation(tmp_path) -> None:
    spec = _repo(
        tmp_path,
        "import unittest\nfrom app.calc import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
    )
    base = digest(tmp_path, "tests")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "import unittest\nfrom app.calc import add\n\n"
        "class T(unittest.TestCase):\n    def test_trivial(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    result = evaluate(tmp_path, spec, LocalSandbox(tmp_path), None, base)
    assert result.failure_class is FailureClass.TEST_INTEGRITY
    assert not result.passed


def test_flaky_test_is_detected(tmp_path) -> None:
    spec = _repo(
        tmp_path,
        "import unittest\nfrom pathlib import Path\nfrom app.calc import add\n\n"
        "STATE = Path(__file__).with_name('.state')\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_stateful(self):\n"
        "        if not STATE.exists():\n"
        "            STATE.write_text('seen', encoding='utf-8')\n"
        "            self.fail('transient')\n"
        "        self.assertEqual(add(1, 2), 3)\n",
    )
    assert not (tmp_path / "tests" / ".state").exists()
    base = digest(tmp_path, "tests")
    result = evaluate(tmp_path, spec, LocalSandbox(tmp_path), None, base)
    assert result.failure_class is FailureClass.TEST_FLAKE
    assert "unchanged rerun" in result.reason


def test_passing_gate_with_unmeasured_coverage(tmp_path) -> None:
    spec = _repo(
        tmp_path,
        "import unittest\nfrom app.calc import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
    )
    base = digest(tmp_path, "tests")
    result = evaluate(tmp_path, spec, LocalSandbox(tmp_path), None, base)
    assert result.passed
    assert result.failure_class is None

from pathlib import Path

from code_migration_agent.build import baseline_probe, package_drift, run_build, run_tests
from code_migration_agent.models import MigrationSpec
from code_migration_agent.runtime.sandbox import LocalSandbox


def _write_repo(root: Path, legacy: bool = False) -> MigrationSpec:
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    if legacy:
        (root / "app" / "maths.py").write_text(
            'def show(value):\n    print "value", value\n    return value\n',
            encoding="utf-8",
        )
        test = '''\
import unittest
from app.maths import show

class MathsTests(unittest.TestCase):
    def test_show(self):
        self.assertEqual(show(3), 3)
'''
    else:
        (root / "app" / "maths.py").write_text(
            "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
            encoding="utf-8",
        )
        test = '''\
import unittest
from app.maths import add, mul

class MathsTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_mul(self):
        self.assertEqual(mul(2, 3), 6)
'''
    (root / "tests" / "test_maths.py").write_text(test, encoding="utf-8")
    (root / "setup.py").write_text(
        'from setuptools import setup\nsetup(name="demo", packages=["app"])\n',
        encoding="utf-8",
    )
    return MigrationSpec(name="demo", source=root)


def test_build_and_tests_with_coverage(tmp_path):
    spec = _write_repo(tmp_path)
    sandbox = LocalSandbox(tmp_path)
    build = run_build(tmp_path, spec, sandbox)
    assert build.ok, build.output
    tests = run_tests(tmp_path, spec, sandbox)
    assert tests.ok, tests.output
    assert tests.ran == 2
    assert tests.coverage is not None and tests.coverage > 0


def test_build_reports_missing_dependency(tmp_path):
    spec = _write_repo(tmp_path)
    (tmp_path / "app" / "bad.py").write_text("import absent_package\n", encoding="utf-8")
    build = run_build(tmp_path, spec, LocalSandbox(tmp_path))
    assert not build.ok
    assert "ModuleNotFoundError" in build.output
    assert "absent_package" in build.output


def test_package_drift_markers(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from distutils.core import setup\n"
        "setup(name='x', packages=['app'], use_2to3=True, python_requires='>=2.7')\n",
        encoding="utf-8",
    )
    diagnostics = package_drift(tmp_path)
    assert any("distutils" in item for item in diagnostics)
    assert any("use_2to3" in item for item in diagnostics)
    assert any("Python 2" in item for item in diagnostics)


def test_pyproject_python2_requirement(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=2.7"\n', encoding="utf-8"
    )
    diagnostics = package_drift(tmp_path)
    assert any("requires-python" in item for item in diagnostics)


def test_baseline_probe_normalizes_legacy_syntax(tmp_path):
    spec = _write_repo(tmp_path, legacy=True)
    probe = tmp_path / "probe"
    baseline = baseline_probe(tmp_path, spec, probe, LocalSandbox(probe))
    assert baseline.source == "measured_normalized_base"
    assert baseline.coverage is not None
    assert baseline.tests_ran == 1
    assert "print(" in (probe / "app" / "maths.py").read_text(encoding="utf-8")


def test_missing_test_directory_fails_build(tmp_path):
    spec = _write_repo(tmp_path)
    (tmp_path / "tests").rename(tmp_path / "gone")
    build = run_build(tmp_path, spec, LocalSandbox(tmp_path))
    assert not build.ok
    assert "test directory not found" in build.output

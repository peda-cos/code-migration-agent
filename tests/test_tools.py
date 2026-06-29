import os
from pathlib import Path

import pytest

from code_migration_agent.agent.tools import ToolBox, ToolError
from code_migration_agent.gate import test_tree_digest as digest
from code_migration_agent.models import MigrationSpec
from code_migration_agent.runtime import git
from code_migration_agent.runtime.sandbox import LocalSandbox


def _repo(tmp_path: Path) -> tuple[Path, MigrationSpec]:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "mod.py").write_text(
        "def value():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_mod.py").write_text(
        "import unittest\nfrom app.mod import value\n\n"
        "class T(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value(), 1)\n",
        encoding="utf-8",
    )
    (tmp_path / "setup.py").write_text(
        'from setuptools import setup\nsetup(name="demo", packages=["app"])\n',
        encoding="utf-8",
    )
    git.init_repo(tmp_path)
    git.commit_all(tmp_path, "base")
    git.create_branch(tmp_path)
    spec = MigrationSpec(name="demo", source=tmp_path)
    return tmp_path, spec


def _toolbox(root: Path, spec: MigrationSpec) -> ToolBox:
    return ToolBox(root, LocalSandbox(root), spec, None, digest(root, "tests"))


def test_edit_commit_and_diff(tmp_path):
    root, spec = _repo(tmp_path)
    toolbox = _toolbox(root, spec)
    result = toolbox.edit_file("app/mod.py", "return 1", "return 2")
    assert result.edits == 1
    assert toolbox.read_file("app/mod.py").endswith("return 2\n")
    commit = toolbox.commit("agent: change value")
    assert commit
    diff = toolbox.git_diff()
    assert "-    return 1" in diff
    assert "+    return 2" in diff


def test_edit_requires_unique_match(tmp_path):
    root, spec = _repo(tmp_path)
    (root / "app" / "mod.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    toolbox = _toolbox(root, spec)
    with pytest.raises(ToolError, match="exactly once"):
        toolbox.edit_file("app/mod.py", "x = 1", "x = 2")
    assert (root / "app" / "mod.py").read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_path_confinement(tmp_path):
    root, spec = _repo(tmp_path)
    toolbox = _toolbox(root, spec)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    for path in ("../outside.txt", str(outside), ".git/config"):
        with pytest.raises(ToolError):
            toolbox.read_file(path)
    with pytest.raises(ToolError, match="tests"):
        toolbox.edit_file("tests/test_mod.py", "value", "other")


def test_test_files_are_readable(tmp_path):
    root, spec = _repo(tmp_path)
    toolbox = _toolbox(root, spec)
    assert "test_value" in toolbox.read_file("tests/test_mod.py")


def test_symlink_escape_is_rejected(tmp_path):
    root, spec = _repo(tmp_path)
    toolbox = _toolbox(root, spec)
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "app" / "link.py"
    os.symlink(outside, link)
    with pytest.raises(ToolError):
        toolbox.read_file("app/link.py")

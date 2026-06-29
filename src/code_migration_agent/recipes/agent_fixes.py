"""Diagnostic-triggered agent fixers (deterministic policy's action space)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

import libcst as cst

from ..models import FixerResult, MigrationSpec
from ..recipes.imports import MOVED_MODULES, apply_moved_modules
from .base import RecipeParseError, apply_transformer


def _py_files(repo_root: Path, spec: MigrationSpec) -> Iterable[Path]:
    package_dir = repo_root / spec.package.replace(".", "/")
    if not package_dir.exists():
        return ()
    return sorted(package_dir.rglob("*.py"))


def _write_if_changed(path: Path, old: str, new: str) -> bool:
    if old == new:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _is_docstring_line(node: cst.BaseStatement) -> bool:
    if not isinstance(node, cst.SimpleStatementLine) or len(node.body) != 1:
        return False
    expr = node.body[0]
    return isinstance(expr, cst.Expr) and isinstance(
        expr.value, (cst.SimpleString, cst.ConcatenatedString)
    )


def _is_future_import(node: cst.BaseStatement) -> bool:
    return isinstance(node, cst.SimpleStatementLine) and any(
        isinstance(stmt, cst.ImportFrom)
        and isinstance(stmt.module, cst.Name)
        and stmt.module.value == "__future__"
        for stmt in node.body
    )


def _same_import(stmt: cst.BaseSmallStatement, target: cst.BaseSmallStatement) -> bool:
    if isinstance(stmt, cst.Import) and isinstance(target, cst.Import):
        current = {
            alias.name.value
            for alias in stmt.names
            if isinstance(alias.name, cst.Name)
        }
        wanted = {
            alias.name.value
            for alias in target.names
            if isinstance(alias.name, cst.Name)
        }
        return bool(wanted) and wanted <= current
    if isinstance(stmt, cst.ImportFrom) and isinstance(target, cst.ImportFrom):
        if isinstance(stmt.names, cst.ImportStar) or isinstance(
            target.names, cst.ImportStar
        ):
            return False
        stmt_module = (
            stmt.module.value if isinstance(stmt.module, cst.Name) else None
        )
        target_module = (
            target.module.value if isinstance(target.module, cst.Name) else None
        )
        if stmt_module != target_module:
            return False
        current = {
            alias.name.value
            for alias in stmt.names
            if isinstance(alias, cst.ImportAlias) and isinstance(alias.name, cst.Name)
        }
        wanted = {
            alias.name.value
            for alias in target.names
            if isinstance(alias, cst.ImportAlias) and isinstance(alias.name, cst.Name)
        }
        return bool(wanted) and wanted <= current
    return False


def add_import(source: str, statement: str) -> tuple[str, bool]:
    """Insert a top-level import after the docstring and future imports."""
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return source, False
    new_statement = cst.parse_statement(statement)
    if not isinstance(new_statement, cst.SimpleStatementLine) or not new_statement.body:
        return source, False
    target = new_statement.body[0]
    for node in module.body:
        if isinstance(node, cst.SimpleStatementLine):
            if any(_same_import(stmt, target) for stmt in node.body):
                return source, False
    body = list(module.body)
    index = 1 if body and _is_docstring_line(body[0]) else 0
    while index < len(body) and _is_future_import(body[index]):
        index += 1
    updated = module.with_changes(
        body=tuple(body[:index]) + (new_statement,) + tuple(body[index:])
    )
    return updated.code, True


class _ReduceFinder(cst.CSTVisitor):
    def __init__(self) -> None:
        self.used = False
        self.defined = False

    def visit_Call(self, node: cst.Call) -> None:
        if isinstance(node.func, cst.Name) and node.func.value == "reduce":
            self.used = True

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        if node.name.value == "reduce":
            self.defined = True


def functools_reduce(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    files: list[str] = []
    edits = 0
    for path in _py_files(repo_root, spec):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        finder = _ReduceFinder()
        try:
            cst.parse_module(source).visit(finder)
        except cst.ParserSyntaxError:
            continue
        if not finder.used or finder.defined:
            continue
        updated, changed = add_import(source, "from functools import reduce\n")
        if changed:
            path.write_text(updated, encoding="utf-8")
            files.append(str(path.relative_to(repo_root)))
            edits += 1
    return FixerResult(fixer="functools_reduce", files=files, edits=edits)


def urllib2_request(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    files: list[str] = []
    edits = 0
    for path in _py_files(repo_root, spec):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated, count = apply_moved_modules(source, MOVED_MODULES)
        if updated != source:
            path.write_text(updated, encoding="utf-8")
            files.append(str(path.relative_to(repo_root)))
            edits += count
    return FixerResult(fixer="urllib2_request", files=files, edits=edits)


class _CmpTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        self.count = 0

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        is_sorted = isinstance(updated_node.func, cst.Name) and updated_node.func.value == "sorted"
        is_sort = (
            isinstance(updated_node.func, cst.Attribute)
            and updated_node.func.attr.value == "sort"
        )
        if not (is_sorted or is_sort):
            return updated_node
        args: list[cst.Arg] = []
        changed = False
        for arg in updated_node.args:
            if isinstance(arg.keyword, cst.Name) and arg.keyword.value == "cmp":
                replacement = cst.Call(
                    func=cst.Attribute(
                        value=cst.Name("functools"), attr=cst.Name("cmp_to_key")
                    ),
                    args=[cst.Arg(value=arg.value)],
                )
                args.append(
                    cst.Arg(
                        keyword=cst.Name("key"),
                        equal=cst.AssignEqual(
                            whitespace_before=cst.SimpleWhitespace(""),
                            whitespace_after=cst.SimpleWhitespace(""),
                        ),
                        value=replacement,
                    )
                )
                changed = True
                self.count += 1
            else:
                args.append(arg)
        return updated_node.with_changes(args=tuple(args)) if changed else updated_node


def cmp_to_key(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    files: list[str] = []
    edits = 0
    for path in _py_files(repo_root, spec):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        transformer = _CmpTransformer()
        try:
            _, code = apply_transformer(source, transformer)
        except RecipeParseError:
            continue
        if transformer.count == 0:
            continue
        code, _ = add_import(code, "import functools\n")
        path.write_text(code, encoding="utf-8")
        files.append(str(path.relative_to(repo_root)))
        edits += transformer.count
    return FixerResult(fixer="cmp_to_key", files=files, edits=edits)


class _KeysTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        self.count = 0

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.Subscript:
        value = updated_node.value
        if (
            isinstance(value, cst.Call)
            and isinstance(value.func, cst.Attribute)
            and value.func.attr.value in {"keys", "values", "items"}
            and not value.args
        ):
            self.count += 1
            return updated_node.with_changes(
                value=cst.Call(func=cst.Name("list"), args=[cst.Arg(value=value)])
            )
        return updated_node


def keys_to_list(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    files: list[str] = []
    edits = 0
    for path in _py_files(repo_root, spec):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        transformer = _KeysTransformer()
        try:
            _, code = apply_transformer(source, transformer)
        except RecipeParseError:
            continue
        if transformer.count and _write_if_changed(path, source, code):
            files.append(str(path.relative_to(repo_root)))
            edits += transformer.count
    return FixerResult(fixer="keys_to_list", files=files, edits=edits)


def fix_packaging(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    del spec
    files: list[str] = []
    edits = 0
    setup = repo_root / "setup.py"
    if setup.exists():
        original = setup.read_text(encoding="utf-8")
        updated = original.replace(
            "from distutils.core import setup", "from setuptools import setup"
        )
        updated = re.sub(
            r"^\s*use_2to3(?:_fixers)?\s*=\s*[^,\n]+,\s*$",
            "",
            updated,
            flags=re.MULTILINE,
        )
        updated = re.sub(
            r"^\s*use_2to3\s*=\s*True\s*,?\s*$",
            "",
            updated,
            flags=re.MULTILINE,
        )
        updated = re.sub(
            r"python_requires\s*=\s*['\"][^'\"]*['\"]",
            'python_requires=">=3.12"',
            updated,
        )
        if updated != original:
            setup.write_text(updated, encoding="utf-8")
            files.append("setup.py")
            edits += 1
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        original = pyproject.read_text(encoding="utf-8")
        updated = re.sub(
            r"requires-python\s*=\s*['\"][^'\"]*['\"]",
            'requires-python = ">=3.12"',
            original,
        )
        if updated != original:
            pyproject.write_text(updated, encoding="utf-8")
            files.append("pyproject.toml")
            edits += 1
    return FixerResult(fixer="fix_packaging", files=files, edits=edits)


_COMMANDS_SHIM = r'''"""Local replacement for the removed Python 2 commands module."""
from __future__ import annotations

import subprocess


def getoutput(command: str) -> str:
    proc = subprocess.run(command, shell=True, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip()
        if not detail:
            detail = f"command failed: {command}"
        raise RuntimeError(detail)
    return proc.stdout.rstrip("\n")
'''


class _CommandsTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        self.count = 0
        self.used = False

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import | cst.RemovalSentinel:
        aliases = [
            alias
            for alias in updated_node.names
            if not (
                isinstance(alias.name, cst.Name)
                and alias.name.value == "commands"
                and alias.asname is None
            )
        ]
        if len(aliases) == len(updated_node.names):
            return updated_node
        self.count += 1
        if not aliases:
            return cst.RemoveFromParent()
        return updated_node.with_changes(names=tuple(aliases))

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            isinstance(updated_node.value, cst.Name)
            and updated_node.value.value == "commands"
            and updated_node.attr.value == "getoutput"
        ):
            self.used = True
            self.count += 1
            return cst.Name("getoutput")
        return updated_node


def commands_shim(repo_root: Path, spec: MigrationSpec) -> FixerResult:
    package_dir = repo_root / spec.package.replace(".", "/")
    files: list[str] = []
    edits = 0
    shim = package_dir / "_compat.py"
    shim_written = False
    for path in _py_files(repo_root, spec):
        if path == shim:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "commands" not in source:
            continue
        transformer = _CommandsTransformer()
        try:
            _, code = apply_transformer(source, transformer)
        except RecipeParseError:
            continue
        if transformer.count == 0:
            continue
        if not shim.exists():
            package_dir.mkdir(parents=True, exist_ok=True)
            shim.write_text(_COMMANDS_SHIM, encoding="utf-8")
            shim_written = True
        if transformer.used:
            import_line = f"from {spec.package}._compat import getoutput\n"
            code, _ = add_import(code, import_line)
        path.write_text(code, encoding="utf-8")
        files.append(str(path.relative_to(repo_root)))
        edits += transformer.count
    if shim_written:
        files.append(str(shim.relative_to(repo_root)))
        edits += 1
    return FixerResult(fixer="commands_shim", files=files, edits=edits)


FIXERS: dict[str, Callable[[Path, MigrationSpec], FixerResult]] = {
    "functools_reduce": functools_reduce,
    "urllib2_request": urllib2_request,
    "cmp_to_key": cmp_to_key,
    "keys_to_list": keys_to_list,
    "fix_packaging": fix_packaging,
    "commands_shim": commands_shim,
}


def apply_fixer(
    name: str, repo_root: Path, spec: MigrationSpec
) -> FixerResult:
    fixer = FIXERS.get(name)
    if fixer is None:
        raise KeyError(f"unknown fixer: {name}")
    return fixer(repo_root, spec)

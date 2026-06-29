"""Deterministic failure classification from build and test evidence."""

from __future__ import annotations

import re
from pathlib import Path

from .models import BuildResult, FailureClass, TestResult

_SYNTAX_PATTERNS = (
    r"SyntaxError",
    r"IndentationError",
    r"TabError",
    r"NameError: name 'unicode' is not defined",
    r"NameError: name 'xrange' is not defined",
    r"NameError: name 'raw_input' is not defined",
    r"NameError: name 'reduce' is not defined",
    r"NameError: name 'basestring' is not defined",
    r"sort\(\) takes no positional arguments",
    r"invalid keyword argument.*cmp",
    r"not subscriptable",
    r"module 'string' has no attribute",
    r"has no attribute '(iteritems|iterkeys|itervalues|has_key|next)'",
)
_SYNTAX_RE = re.compile("|".join(f"(?:{pattern})" for pattern in _SYNTAX_PATTERNS))
_MODULE_RE = re.compile(r"(?:ModuleNotFoundError|ImportError): No module named ['\"]?([\w.]+)")
_METACLASS_RE = re.compile(r"^\s*__metaclass__\s*=", re.MULTILINE)


def classify_build(build: BuildResult) -> FailureClass:
    if build.packaging_diagnostics:
        return FailureClass.BUILD_TOOL_DRIFT
    if re.search(r"(SyntaxError|IndentationError|TabError)", build.output):
        return FailureClass.SYNTAX_EDGE_CASE
    if _MODULE_RE.search(build.output):
        return FailureClass.DEP_UPGRADE_REQUIRED
    return FailureClass.UNCLASSIFIED_FAILURE


def _has_py2_metaclass(repo_root: Path) -> bool:
    for path in sorted(repo_root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _METACLASS_RE.search(text):
            return True
    return False


def classify_tests(tests: TestResult, repo_root: Path) -> FailureClass:
    output = tests.output
    if _has_py2_metaclass(repo_root):
        return FailureClass.CUSTOM_ANNOTATION
    if _MODULE_RE.search(output):
        return FailureClass.DEP_UPGRADE_REQUIRED
    if _SYNTAX_RE.search(output):
        return FailureClass.SYNTAX_EDGE_CASE
    if "AssertionError" in output:
        # Remaining semantic edges (for example int division) have no safe
        # mechanical rewrite and are grouped with syntax edges with evidence.
        return FailureClass.SYNTAX_EDGE_CASE
    return FailureClass.UNCLASSIFIED_FAILURE

from pathlib import Path

from code_migration_agent.classify import classify_build, classify_tests
from code_migration_agent.models import BuildResult, FailureClass, TestResult


def _test_result(output: str) -> TestResult:
    return TestResult(ok=False, ran=1, failures=1, output=output)


def test_build_classification() -> None:
    assert (
        classify_build(BuildResult(False, ["setup.py uses use_2to3"], "x"))
        is FailureClass.BUILD_TOOL_DRIFT
    )
    assert (
        classify_build(BuildResult(False, [], "SyntaxError in app/x.py:1: bad"))
        is FailureClass.SYNTAX_EDGE_CASE
    )
    assert (
        classify_build(
            BuildResult(False, [], "ModuleNotFoundError: No module named 'legacyhttp'")
        )
        is FailureClass.DEP_UPGRADE_REQUIRED
    )
    assert (
        classify_build(BuildResult(False, [], "BUILD OK"))
        is FailureClass.UNCLASSIFIED_FAILURE
    )


def test_test_output_patterns(tmp_path: Path) -> None:
    cases = {
        "NameError: name 'reduce' is not defined": FailureClass.SYNTAX_EDGE_CASE,
        "TypeError: sort() takes no positional arguments": FailureClass.SYNTAX_EDGE_CASE,
        "TypeError: 'dict_keys' object is not subscriptable": FailureClass.SYNTAX_EDGE_CASE,
        "ModuleNotFoundError: No module named 'urllib2'": FailureClass.DEP_UPGRADE_REQUIRED,
        "AssertionError: 2.5 != 2": FailureClass.SYNTAX_EDGE_CASE,
        "something unexpected": FailureClass.UNCLASSIFIED_FAILURE,
    }
    for output, expected in cases.items():
        assert classify_tests(_test_result(output), tmp_path) is expected


def test_py2_metaclass_is_custom_annotation(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        "class Plugin(object):\n    __metaclass__ = object\n", encoding="utf-8"
    )
    assert (
        classify_tests(_test_result("AssertionError: false"), tmp_path)
        is FailureClass.CUSTOM_ANNOTATION
    )

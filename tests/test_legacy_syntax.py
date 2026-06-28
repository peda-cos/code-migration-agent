import ast
import contextlib
import io

from code_migration_agent.recipes.legacy_syntax import normalize_source


def test_rewrites_py2_syntax_to_executable_python3() -> None:
    source = '''\
import sys

def classify(code):
    try:
        if code < 0:
            raise ValueError, "neg"
        return "ok"
    except ValueError, err:
        print >>sys.stderr, "bad", err
        return str(err)

def encode(value):
    return `value`, 0777, 10L, value <> 0

def show(value):
    print "value", value
'''
    result = normalize_source(source, "demo.py")
    ast.parse(result.module_code)
    rules = {edit.rule for edit in result.edits}
    assert {"print_stmt", "except_comma", "raise_comma", "backticks", "octal", "long_suffix", "ne_operator"} <= rules
    namespace: dict[str, object] = {}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        exec(compile(result.module_code, "demo.py", "exec"), namespace)
        assert namespace["classify"](-1) == "neg"  # type: ignore[operator]
        assert namespace["encode"](3) == ("3", 511, 10, True)  # type: ignore[operator]
        assert namespace["show"](7) is None  # type: ignore[operator]


def test_valid_source_and_strings_are_untouched() -> None:
    source = '''\
# print "this is a comment"
def demo():
    text = "print x; except E, e"
    return text
'''
    result = normalize_source(source)
    assert result.edits == []
    assert result.module_code == source


def test_second_pass_is_idempotent() -> None:
    source = 'def f():\n    print "x"\n    return 0777\n'
    first = normalize_source(source)
    second = normalize_source(first.module_code)
    assert first.edits
    assert second.edits == []
    assert second.module_code == first.module_code


def test_unsupported_exec_is_left_for_taxonomy() -> None:
    source = 'def f(code):\n    exec code in {}\n'
    result = normalize_source(source)
    assert result.module_code == source
    assert result.edits == []
    try:
        ast.parse(result.module_code)
    except SyntaxError:
        pass
    else:  # pragma: no cover - the fixture must stay unparsable
        raise AssertionError("unsupported py2 exec unexpectedly parsed")


def test_semicolon_print_statement_is_left_unsupported() -> None:
    source = 'print "a"; print "b"\n'
    result = normalize_source(source)
    assert result.module_code == source
    assert result.edits == []

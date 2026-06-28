import ast

from code_migration_agent.recipes import apply_recipes
from code_migration_agent.recipes.imports import MOVED_MODULES, apply_moved_modules


def _run(source: str) -> str:
    output, _ = apply_recipes(source)
    ast.parse(output)
    return output


def test_moved_imports_and_itertools_aliases() -> None:
    source = '''\
import ConfigParser
import Queue
import StringIO
from itertools import izip, islice

def build(items):
    parser = ConfigParser.ConfigParser()
    queue = Queue.Queue()
    stream = StringIO.StringIO()
    return parser, queue, stream, list(izip(items, items)), list(islice(items, 1))
'''
    output = _run(source)
    assert "import configparser" in output
    assert "import queue" in output
    assert "import io" in output
    assert "from itertools import islice" in output
    assert "izip(" not in output
    assert "io.StringIO()" in output
    assert "zip(items, items)" in output
    assert apply_recipes(output)[1] == {}


def test_url_modules_are_reserved_for_the_agent() -> None:
    source = '''\
def fetch(url):
    import urllib2
    return urllib2.urlopen(url)
'''
    recipe_only, counts = apply_recipes(source)
    assert counts == {}
    assert "urllib2" in recipe_only

    agent_output, agent_count = apply_moved_modules(source, MOVED_MODULES)
    assert agent_count > 0
    assert "urllib.request.urlopen" in agent_output
    assert "import urllib2" not in agent_output
    ast.parse(agent_output)


def test_builtin_aliases_are_only_rewritten_in_call_positions() -> None:
    source = '''\
def unicode(value):
    return value

def uses(value):
    return unicode(value), unichr(65), isinstance(value, (basestring, int))
'''
    output = _run(source)
    assert "def unicode(value):" in output
    assert "return str(value), chr(65), isinstance(value, (str, int))" in output


def test_dict_methods_full_semantics() -> None:
    source = '''\
def lookup(data, key):
    if data.has_key(key):
        return data[key]
    return None

def pairs(data):
    return list(data.iteritems())

def advance(cursor):
    return cursor.next()
'''
    output = _run(source)
    namespace: dict[str, object] = {}
    exec(compile(output, "dicts.py", "exec"), namespace)
    lookup = namespace["lookup"]
    pairs = namespace["pairs"]
    advance = namespace["advance"]
    assert lookup({"a": 1}, "a") == 1  # type: ignore[operator]
    assert lookup({"a": 1}, "b") is None  # type: ignore[operator]
    assert pairs({"a": 1}) == [("a", 1)]  # type: ignore[operator]
    assert advance(iter([7])) == 7  # type: ignore[operator]


def test_recipes_are_idempotent() -> None:
    source = "import cPickle\n\ndef dumps(value):\n    return cPickle.dumps(value)\n"
    output, counts = apply_recipes(source)
    assert counts
    assert apply_recipes(output) == (output, {})

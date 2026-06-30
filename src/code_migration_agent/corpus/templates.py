"""Deterministic repository templates for the local migration corpus.

Each archetype models a documented Python-2-era failure shape. Tests are
Python 3 (the benchmark supplies target-runtime tests) and contain no network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from textwrap import dedent
from typing import Callable

from ..models import Budgets


def _default_setup(name: str) -> str:
    return dedent(
        """\
        from setuptools import setup

        setup(
            name="__NAME__",
            version="0.1.0",
            packages=["app"],
            python_requires=">=3.12",
        )
        """
    ).replace("__NAME__", name)


def _legacy_setup(name: str, variant: int) -> str:
    if variant % 2 == 0:
        return dedent(
            """\
            from distutils.core import setup

            setup(
                name="__NAME__",
                version="0.1.0",
                packages=["app"],
                use_2to3=True,
                python_requires=">=2.7",
            )
            """
        ).replace("__NAME__", name)
    return dedent(
        """\
        from distutils.core import setup

        setup(
            name="__NAME__",
            version="0.1.0",
            packages=["app"],
            python_requires=">=2.7",
        )
        """
    ).replace("__NAME__", name)


_UTIL_MODULE = dedent(
    """\
    def clamp(value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value
    """
)

_UTIL_TESTS = dedent(
    """\
    import unittest

    from app.util import clamp


    class UtilTests(unittest.TestCase):
        def test_clamp_upper(self):
            self.assertEqual(clamp(5, 0, 3), 3)

        def test_clamp_lower(self):
            self.assertEqual(clamp(-1, 0, 3), 0)

        def test_clamp_inside(self):
            self.assertEqual(clamp(2, 0, 3), 2)


    if __name__ == "__main__":
        unittest.main()
    """
)


@dataclass(frozen=True)
class Archetype:
    name: str
    count: int
    builder: Callable[[str, int, random.Random], dict[str, str]]
    budgets: Budgets = Budgets()


def _files(
    name: str,
    module: str,
    source: str,
    tests: str,
    *,
    setup: str | None = None,
    pyproject: str | None = None,
    extras: dict[str, str] | None = None,
) -> dict[str, str]:
    files = {
        "app/__init__.py": "",
        "app/util.py": _UTIL_MODULE,
        f"app/{module}.py": dedent(source),
        f"tests/test_{module}.py": dedent(tests),
        "tests/test_util.py": _UTIL_TESTS,
        "setup.py": setup if setup is not None else _default_setup(name),
    }
    if pyproject is not None:
        files["pyproject.toml"] = pyproject.replace("__NAME__", name)
    if extras:
        files.update(extras)
    return files


def build_legacy_syntax(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    title = f"report_{variant}_{rng.randrange(10, 99)}"
    long_value = 10 + variant * 7 + rng.randrange(0, 5)
    source = '''\
        import sys


        class Report(object):
            def __init__(self, title):
                self.title = title
                self.rows = []

            def add(self, name, value):
                self.rows.append((name, value))

            def render(self):
                print "%s: %d" % (self.title, len(self.rows))
                return len(self.rows)

            def classify(self, code):
                try:
                    if code < 0:
                        raise ValueError, "negative"
                    return "ok"
                except ValueError, err:
                    print >>sys.stderr, "bad", err
                    return "error"

            def encode(self, value):
                return `value`, 0777, __LONG__L, value <> 0
        '''.replace("__LONG__", str(long_value))
    tests = '''\
        import unittest

        from app.report import Report


        class ReportTests(unittest.TestCase):
            def test_render(self):
                report = Report("__TITLE__")
                report.add("a", 1)
                report.add("b", 2)
                self.assertEqual(report.render(), 2)

            def test_classify(self):
                report = Report("x")
                self.assertEqual(report.classify(3), "ok")
                self.assertEqual(report.classify(-1), "error")

            def test_encode(self):
                report = Report("x")
                self.assertEqual(report.encode(3), ("3", 511, __LONG__, True))


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__TITLE__", title).replace("__LONG__", str(long_value))
    return _files(name, "report", source, tests)


def build_dict_methods(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    offset = variant + rng.randrange(1, 9)
    source = '''\
        class Store(object):
            def __init__(self):
                self._data = {}

            def put(self, key, value):
                self._data[key] = value

            def get(self, key):
                if self._data.has_key(key):
                    return self._data[key]
                return None

            def has(self, key):
                return self._data.has_key(key)

            def pairs(self):
                return list(self._data.iteritems())

            def keys(self):
                return list(self._data.iterkeys())

            def values(self):
                return list(self._data.itervalues())
        '''
    tests = '''\
        import unittest

        from app.store import Store


        class StoreTests(unittest.TestCase):
            def setUp(self):
                self.store = Store()
                self.store.put("a", __OFFSET__)
                self.store.put("b", __OFFSET__ + 1)

            def test_get(self):
                self.assertEqual(self.store.get("a"), __OFFSET__)
                self.assertIsNone(self.store.get("missing"))

            def test_has(self):
                self.assertTrue(self.store.has("b"))
                self.assertFalse(self.store.has("missing"))

            def test_views(self):
                self.assertEqual(self.store.pairs(), [("a", __OFFSET__), ("b", __OFFSET__ + 1)])
                self.assertEqual(self.store.keys(), ["a", "b"])
                self.assertEqual(self.store.values(), [__OFFSET__, __OFFSET__ + 1])


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__OFFSET__", str(offset))
    return _files(name, "store", source, tests)


def build_builtin_aliases(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    limit = 3 + variant + rng.randrange(0, 4)
    source = '''\
        def normalize(text):
            return unicode(text).strip()

        def range_sum(limit):
            total = 0
            for value in xrange(limit):
                total += value
            return total

        def read_name(prompt):
            return raw_input(prompt)

        def is_text(value):
            return isinstance(value, basestring)

        def char_at(code):
            return unichr(code)

        def parse_number(text):
            return long(text)
        '''
    tests = '''\
        import unittest
        from unittest.mock import patch

        from app.legacy_text import char_at, is_text, normalize, parse_number, range_sum, read_name


        class LegacyTextTests(unittest.TestCase):
            def test_normalize(self):
                self.assertEqual(normalize("  legacy  "), "legacy")

            def test_range_sum(self):
                self.assertEqual(range_sum(__LIMIT__), sum(range(__LIMIT__)))

            def test_read_name(self):
                with patch("builtins.input", return_value="Ada"):
                    self.assertEqual(read_name("name? "), "Ada")

            def test_is_text(self):
                self.assertTrue(is_text("abc"))

            def test_char_and_number(self):
                self.assertEqual(char_at(65), "A")
                self.assertEqual(parse_number("42"), 42)


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__LIMIT__", str(limit))
    return _files(name, "legacy_text", source, tests)


def build_stdlib_imports(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    payload = variant + rng.randrange(1, 20)
    source = '''\
        def parse_bool(raw):
            import ConfigParser
            parser = ConfigParser.ConfigParser()
            parser.add_section("main")
            parser.set("main", "enabled", raw)
            return parser.getboolean("main", "enabled")

        def roundtrip(value):
            import cPickle
            return cPickle.loads(cPickle.dumps(value))

        def queue_items(items):
            import Queue
            queue = Queue.Queue()
            for item in items:
                queue.put(item)
            return [queue.get() for _ in items]

        def capture(text):
            import StringIO
            stream = StringIO.StringIO()
            stream.write(text)
            value = stream.getvalue()
            stream.close()
            return value

        def pair(items):
            from itertools import izip
            return [item for item in izip(items, items)]

        def first_two(items):
            from itertools import islice
            return list(islice(items, 2))
        '''
    tests = '''\
        import unittest

        from app.compat import capture, first_two, pair, parse_bool, queue_items, roundtrip


        class CompatTests(unittest.TestCase):
            def test_config(self):
                self.assertTrue(parse_bool("yes"))
                self.assertFalse(parse_bool("no"))

            def test_pickle(self):
                self.assertEqual(roundtrip({"value": __PAYLOAD__}), {"value": __PAYLOAD__})

            def test_queue(self):
                self.assertEqual(queue_items([1, 2, 3]), [1, 2, 3])

            def test_stringio(self):
                self.assertEqual(capture("hello"), "hello")

            def test_itertools(self):
                self.assertEqual(pair([1, 2]), [(1, 1), (2, 2)])
                self.assertEqual(first_two([1, 2, 3]), [1, 2])


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__PAYLOAD__", str(payload))
    return _files(name, "compat", source, tests)


def build_reduce_import(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    base = variant + rng.randrange(1, 6)
    source = '''\
        def total(values):
            return reduce(lambda left, right: left + right, values)

        def product(values):
            return reduce(lambda left, right: left * right, values, 1)

        def longest(words):
            return reduce(lambda left, right: left if len(left) >= len(right) else right, words)
        '''
    tests = '''\
        import unittest

        from app.aggregate import longest, product, total


        class AggregateTests(unittest.TestCase):
            def test_total(self):
                self.assertEqual(total([1, 2, __BASE__]), __BASE__ + 3)

            def test_product(self):
                self.assertEqual(product([2, 3, 4]), 24)

            def test_longest(self):
                self.assertEqual(longest(["a", "longer", "mid"]), "longer")


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__BASE__", str(base))
    return _files(name, "aggregate", source, tests)


def build_urllib2_request(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    payload = f"payload-{variant}-{rng.randrange(100, 999)}"
    source = '''\
        def fetch_text(url):
            import urllib2
            return urllib2.urlopen(url).read().decode("utf-8")

        def split_url(url):
            import urlparse
            parsed = urlparse.urlparse(url)
            return parsed.scheme, parsed.netloc
        '''
    tests = '''\
        import unittest
        from unittest.mock import patch

        from app.network import fetch_text, split_url


        class _Response(object):
            def read(self):
                return b"__PAYLOAD__"


        class NetworkTests(unittest.TestCase):
            def test_fetch(self):
                with patch("urllib.request.urlopen", return_value=_Response()):
                    self.assertEqual(fetch_text("http://example.test/data"), "__PAYLOAD__")

            def test_split(self):
                self.assertEqual(split_url("https://example.test/a"), ("https", "example.test"))


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__PAYLOAD__", payload)
    return _files(name, "network", source, tests)


def build_cmp_sort(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    extra = variant + rng.randrange(1, 4)
    source = '''\
        def by_length(words):
            result = list(words)
            result.sort(cmp=lambda left, right: len(left) - len(right))
            return result

        def sorted_scores(scores):
            return sorted(scores, cmp=lambda left, right: left[1] - right[1])
        '''
    tests = '''\
        import unittest

        from app.ordering import by_length, sorted_scores


        class OrderingTests(unittest.TestCase):
            def test_by_length(self):
                self.assertEqual(by_length(["bbb", "a", "cc"]), ["a", "cc", "bbb"])

            def test_sorted_scores(self):
                rows = [("x", __EXTRA__ + 1), ("y", __EXTRA__), ("z", __EXTRA__ + 2)]
                self.assertEqual(sorted_scores(rows), [("y", __EXTRA__), ("x", __EXTRA__ + 1), ("z", __EXTRA__ + 2)])


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__EXTRA__", str(extra))
    return _files(name, "ordering", source, tests)


def build_keys_indexing(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    first = variant + rng.randrange(1, 9)
    source = '''\
        def first_key(mapping):
            return mapping.keys()[0]

        def second_value(mapping):
            return mapping.values()[1]

        def first_pair(mapping):
            return mapping.items()[0]
        '''
    tests = '''\
        import unittest

        from app.mapping import first_key, first_pair, second_value


        class MappingTests(unittest.TestCase):
            def setUp(self):
                self.data = {"a": __FIRST__, "b": __FIRST__ + 1, "c": __FIRST__ + 2}

            def test_first_key(self):
                self.assertEqual(first_key(self.data), "a")

            def test_second_value(self):
                self.assertEqual(second_value(self.data), __FIRST__ + 1)

            def test_first_pair(self):
                self.assertEqual(first_pair(self.data), ("a", __FIRST__))


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__FIRST__", str(first))
    return _files(name, "mapping", source, tests)


def build_packaging_drift(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    value = variant + rng.randrange(1, 10)
    source = '''\
        def add(left, right):
            return left + right

        def describe(text):
            return f"value={text}"
        '''
    tests = '''\
        import unittest

        from app.metadata import add, describe


        class MetadataTests(unittest.TestCase):
            def test_add(self):
                self.assertEqual(add(2, __VALUE__), __VALUE__ + 2)

            def test_describe(self):
                self.assertEqual(describe("x"), "value=x")


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__VALUE__", str(value))
    pyproject = None
    if variant == 2:
        pyproject = dedent(
            """\
            [build-system]
            requires = ["setuptools"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "__NAME__"
            version = "0.1.0"
            requires-python = ">=2.7"
            """
        )
        setup = _default_setup(name)
    else:
        setup = _legacy_setup(name, variant)
    return _files(name, "metadata", source, tests, setup=setup, pyproject=pyproject)


def build_custom_metaclass(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    marker = f"plugin_{variant}_{rng.randrange(10, 99)}"
    source = '''\
        REGISTRY = {}


        class RegistryMeta(type):
            def __new__(mcls, name, bases, namespace):
                cls = super().__new__(mcls, name, bases, namespace)
                REGISTRY[name] = cls
                return cls


        class Plugin(object):
            __metaclass__ = RegistryMeta

            def run(self):
                return "__MARKER__"


        def registered():
            return "Plugin" in REGISTRY
        '''
    tests = '''\
        import unittest

        from app.plugin import Plugin, registered


        class PluginTests(unittest.TestCase):
            def test_run(self):
                self.assertEqual(Plugin().run(), "__MARKER__")

            def test_registered(self):
                self.assertTrue(registered())


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__MARKER__", marker)
    return _files(name, "plugin", source, tests)


def build_missing_dependency(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    endpoint = f"/api/v{variant}/{rng.randrange(100, 999)}"
    source = '''\
        import legacyhttp


        def fetch(path):
            return legacyhttp.get(path)


        def endpoint():
            return "__ENDPOINT__"
        '''
    tests = '''\
        import unittest

        from app.client import endpoint, fetch


        class ClientTests(unittest.TestCase):
            def test_endpoint(self):
                self.assertEqual(endpoint(), "__ENDPOINT__")

            def test_fetch(self):
                self.assertEqual(fetch("/data"), {"ok": True})


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__ENDPOINT__", endpoint)
    return _files(
        name,
        "client",
        source,
        tests,
        extras={"requirements.txt": "legacyhttp==0.9\n"},
    )


def build_flaky_test(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    value = variant + rng.randrange(1, 7)
    source = '''\
        def add(left, right):
            return left + right
        '''
    tests = '''\
        import unittest
        from pathlib import Path

        from app.arithmetic import add


        STATE = Path(__file__).with_name(".flake_state")


        class FlakyTests(unittest.TestCase):
            def test_order_dependent(self):
                if not STATE.exists():
                    STATE.write_text("seen", encoding="utf-8")
                    self.fail("transient order-dependent failure")
                self.assertEqual(add(2, __VALUE__), __VALUE__ + 2)


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__VALUE__", str(value))
    return _files(name, "arithmetic", source, tests)


def build_coverage_trim(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    word = f"token_{variant}_{rng.randrange(10, 99)}"
    source = '''\
        def run_command(command):
            import commands
            return commands.getoutput(command)

        def normalize(text):
            return text.strip().lower()

        def total(values):
            return sum(values)
        '''
    tests = '''\
        import unittest

        from app.runner import normalize, run_command, total


        class RunnerTests(unittest.TestCase):
            def test_command(self):
                self.assertEqual(run_command("printf hello"), "hello")

            def test_normalize(self):
                self.assertEqual(normalize("  __WORD__  "), "__WORD__")

            def test_total(self):
                self.assertEqual(total([1, 2, 3]), 6)


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__WORD__", word)
    return _files(name, "runner", source, tests)


def build_semantic_division(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    total_value = 5 + variant + rng.randrange(0, 3)
    source = '''\
        def average(total, count):
            return total / count

        def ratio(left, right):
            return left / right
        '''
    tests = '''\
        import unittest

        from app.stats import average, ratio


        class StatsTests(unittest.TestCase):
            def test_average(self):
                self.assertEqual(average(__TOTAL__, 2), 2)

            def test_ratio(self):
                self.assertEqual(ratio(7, 2), 3)


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__TOTAL__", str(total_value * 2 - 1))
    return _files(name, "stats", source, tests)


def build_py2_exec(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    value = variant + rng.randrange(1, 5)
    source = '''\
        def compute(value):
            namespace = {}
            exec "result = value * 2" in namespace
            return namespace["result"]
        '''
    tests = '''\
        import unittest

        from app.dynamic import compute


        class DynamicTests(unittest.TestCase):
            def test_compute(self):
                self.assertEqual(compute(__VALUE__), __VALUE__ * 2)


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__VALUE__", str(value))
    return _files(name, "dynamic", source, tests)


def build_tight_budget(name: str, variant: int, rng: random.Random) -> dict[str, str]:
    base = variant + rng.randrange(1, 7)
    source = '''\
        def total(values):
            return reduce(lambda left, right: left + right, values)

        def first_key(mapping):
            return mapping.keys()[0]
        '''
    tests = '''\
        import unittest

        from app.combined import first_key, total


        class CombinedTests(unittest.TestCase):
            def test_total(self):
                self.assertEqual(total([1, 2, __BASE__]), __BASE__ + 3)

            def test_first_key(self):
                self.assertEqual(first_key({"a": 1, "b": 2}), "a")


        if __name__ == "__main__":
            unittest.main()
        '''.replace("__BASE__", str(base))
    return _files(name, "combined", source, tests)


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype("legacy_syntax", 5, build_legacy_syntax),
    Archetype("dict_methods", 4, build_dict_methods),
    Archetype("builtin_aliases", 4, build_builtin_aliases),
    Archetype("stdlib_imports", 4, build_stdlib_imports),
    Archetype("reduce_import", 4, build_reduce_import),
    Archetype("urllib2_request", 4, build_urllib2_request),
    Archetype("cmp_sort", 4, build_cmp_sort),
    Archetype("keys_indexing", 3, build_keys_indexing),
    Archetype("packaging_drift", 3, build_packaging_drift),
    Archetype("custom_metaclass", 3, build_custom_metaclass),
    Archetype("missing_dependency", 3, build_missing_dependency),
    Archetype("flaky_test", 2, build_flaky_test),
    Archetype("coverage_trim", 2, build_coverage_trim),
    Archetype("semantic_division", 2, build_semantic_division),
    Archetype("py2_exec", 1, build_py2_exec),
    Archetype("tight_budget", 2, build_tight_budget, budgets=Budgets(max_turns=1)),
)

MAX_CORPUS_SIZE = sum(archetype.count for archetype in ARCHETYPES)

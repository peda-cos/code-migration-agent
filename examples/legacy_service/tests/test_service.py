import unittest

from app.service import Greeter, squares


class ServiceTests(unittest.TestCase):
    def test_greet(self):
        greeter = Greeter("Ada")
        self.assertEqual(greeter.greet(), "Ada")
        self.assertEqual(greeter.seen, ["Ada"])

    def test_labels(self):
        greeter = Greeter("Ada")
        self.assertEqual(greeter.labels({"x": 1, "y": 2}), [("x", 1), ("y", 2)])
        self.assertEqual(greeter.labels({}), [])

    def test_fail(self):
        self.assertEqual(Greeter("Ada").fail("nope"), "invalid")

    def test_squares(self):
        self.assertEqual(squares(4), [0, 1, 4, 9])


if __name__ == "__main__":
    unittest.main()

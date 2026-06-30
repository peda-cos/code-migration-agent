import sys


class Greeter(object):
    def __init__(self, name):
        self.name = name
        self.seen = []

    def greet(self):
        self.seen.append(self.name)
        print "Hello, %s" % self.name
        return self.name

    def labels(self, mapping):
        if mapping.has_key("x"):
            return list(mapping.iteritems())
        return []

    def fail(self, reason):
        try:
            raise ValueError, reason
        except ValueError, err:
            print >>sys.stderr, "invalid:", err
            return "invalid"


def squares(limit):
    return [value * value for value in xrange(limit)]

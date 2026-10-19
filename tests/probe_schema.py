# SPDX-License-Identifier: GPL-3.0-or-later
# The probe output (protocol/probe-output.schema.json, generated from include/plugin-hostd/protocol.h) against its four
# fixtures, and against broken copies of the first and of the instrument's: a guard that refuses nothing is decoration, so each
# copy must be refused, and at the path the schema names.
#   probe_schema.py [tree]   tree holds the schema (default: this checkout); the fixtures are always this checkout's
import copy, json, os, sys

try:
    import jsonschema
except ImportError:
    sys.exit("the probe schema test needs python3-jsonschema (dnf install python3-jsonschema, apt install python3-jsonschema)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "probe")
SCHEMA = json.load(open(os.path.join(TREE, "protocol", "probe-output.schema.json")))
failed = 0


def check(cond, what):
    global failed
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failed += 1


def fixture(name):
    return json.load(open(os.path.join(FIXTURES, name + ".json")))


def errors(document):
    validator = jsonschema.Draft202012Validator(SCHEMA)
    return [("/" + "/".join(str(p) for p in e.absolute_path), e.validator) for e in validator.iter_errors(document)]


try:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    check(True, "the schema is a valid draft 2020-12 schema")
except jsonschema.SchemaError as e:
    check(False, "the schema is a valid draft 2020-12 schema: %s" % e.message)

for name in ("success-msi", "plugin-crash", "memory-limit-refused", "instrument-notes"):
    found = errors(fixture(name))
    check(not found, "%s validates%s" % (name, "" if not found else ": " + str(found[:3])))


def drop(path, key):
    def go(d):
        for p in path:
            d = d[p]
        del d[key]
    return go


def put(path, key, value):
    def go(d):
        for p in path:
            d = d[p]
        d[key] = value
    return go


# (what is broken in a copy of the success document, the path the schema must refuse it at, the keyword that refuses[,
# the fixture broken when it is not the success document])
BROKEN = [
    ("a verdict block added", "/", "not", put([], "verdict", {"class": "in-process"})),
    ("binary.sha256 removed", "/binary", "required", drop(["binary"], "sha256")),
    ("a step outcome that is no code", "/steps/0/outcome", "enum", put(["steps", 0], "outcome", "probe.exploded")),
    ("a format version of another major", "/formatVersion", "pattern", put([], "formatVersion", "2.0")),
    ("a cost percentile of 50", "/grid/0/cost/percentile/p", "exclusiveMinimum", None),
    ("an instrument timed holding no note", "/grid/0/cost/voices/held", "minimum",
     put(["grid", 0, "cost", "voices"], "held", 0), "instrument-notes"),
    ("held notes with a basis that is none of the format's", "/grid/1/cost/voices/basis", "enum",
     put(["grid", 1, "cost", "voices"], "basis", "guess"), "instrument-notes"),
    ("held notes that do not say why that many", "/grid/1/cost/voices", "required",
     drop(["grid", 1, "cost", "voices"], "basis"), "instrument-notes"),
]


def percentile_50(d):
    d["grid"][0]["cost"]["percentile"]["p"] = 50


for what, path, keyword, mutate, *broken in BROKEN:
    d = copy.deepcopy(fixture(broken[0] if broken else "success-msi"))
    (mutate or percentile_50)(d)
    found = errors(d)
    check((path, keyword) in found,
          "refused: %s, at %s by %s%s" % (what, path, keyword, "" if (path, keyword) in found else " (got %s)" % found[:3]))

sys.exit(1 if failed else 0)

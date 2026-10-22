# SPDX-License-Identifier: GPL-3.0-or-later
# The org.openmixer.preset file (docs/presets.md) against its schema, protocol/preset.schema.json: the files of
# tests/fixtures/presets hold, and each broken copy of them is refused: an unknown format version, a fingerprint of a
# scheme this version does not know, a /2 without its plugin's version or fingerprint, a carries the body does not
# agree with, an alias longer than 12, a /1 with a state body.
#
#   python3 tests/preset_format.py [<tree>]     the tree whose protocol/ is read (default: this one)
import copy, json, os, sys

try:
    import jsonschema
except ImportError:
    sys.exit("check-preset-schema needs python3-jsonschema (dnf install python3-jsonschema, apt install python3-jsonschema)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "presets")

with open(os.path.join(TREE, "protocol", "preset.schema.json")) as f:
    schema = json.load(f)
jsonschema.Draft202012Validator.check_schema(schema)
validator = jsonschema.Draft202012Validator(schema)
good = {}
for name in sorted(os.listdir(FIXTURES)):
    with open(os.path.join(FIXTURES, name)) as f:
        good[name] = json.load(f)


def broken(name, change):
    doc = copy.deepcopy(good[name])
    change(doc)
    return doc


def drop(key):
    return lambda d: d.pop(key)


REFUSED = [
    ("an unknown format version", "v2-params.json", lambda d: d.update(format="org.openmixer.preset/3")),
    ("no format at all", "v1-params.json", drop("format")),
    ("a fingerprint of an unknown scheme", "v2-params.json",
     lambda d: d["plugin"].update(fingerprint="omx-layout/9:" + "0" * 64)),
    ("a fingerprint that is no sha256", "v2-params.json", lambda d: d["plugin"].update(fingerprint="omx-layout/1:abc")),
    ("a /2 without the plugin's fingerprint", "v2-params.json", lambda d: d["plugin"].pop("fingerprint")),
    ("a /2 without the plugin's version", "v2-params.json", lambda d: d["plugin"].pop("version")),
    ("a /2 without carries", "v2-params.json", drop("carries")),
    ("params+state with the state body dropped", "v2-state.json", drop("state")),
    ("carries params with a state body", "v2-state.json", lambda d: d.update(carries="params")),
    ("carries params with no params", "v2-params.json", drop("params")),
    ("a /1 with a state body", "v1-params.json", lambda d: d.update(state=good["v2-state.json"]["state"])),
    ("an alias of 13 characters", "v2-params.json", lambda d: d.update(alias="A" * 13)),
    ("a value that is a string", "v2-params.json", lambda d: d["params"][0].update(value="-3.25")),
    ("a state of another encoding", "v2-state.json", lambda d: d["state"].update(encoding="hex")),
    ("a state file with a path in its name", "v2-state.json", lambda d: d["state"]["files"][0].update(name="../x")),
    ("a time that is not UTC", "v2-params.json", lambda d: d.update(createdAt="2026-10-22T21:00:00+02:00")),
]

failed = 0
for name, doc in good.items():
    errors = list(validator.iter_errors(doc))
    if errors:
        failed += 1
        print("FAIL %s is refused: %s" % (name, errors[0].message))
    else:
        print("ok   %s holds" % name)
for what, name, change in REFUSED:
    if validator.is_valid(broken(name, change)):
        failed += 1
        print("FAIL %s is taken" % what)
    else:
        print("ok   %s is refused" % what)
sys.exit(1 if failed else 0)

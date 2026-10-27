"""Unit tests of the harness: run with `python3 -I bench/tests/test_bench.py`. They need no JACK server and no host:
the schema and validator rules, and (below) the pieces of the runner that decide a number."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def example():
    path = sorted(os.listdir(os.path.join(BENCH, "examples")))[0]
    with open(os.path.join(BENCH, "examples", path)) as f:
        return json.load(f)


def validate(doc):
    """(exit code, output) of validate.sh on doc"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "doc.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        r = subprocess.run([os.path.join(BENCH, "validate.sh"), path], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        return r.returncode, r.stdout


def first_ok(doc):
    return [s for s in doc["scenarios"] if s["status"] == "ok"][0]


class Schema(unittest.TestCase):
    def test_the_shipped_example_is_valid(self):
        code, out = validate(example())
        self.assertEqual(code, 0, out)

    def test_the_new_fields_are_valid_together(self):
        doc = example()
        s = first_ok(doc)
        s.update({"mode": "plan", "xruns": 2, "latency_frames": 256, "stress": "busy24+mem256", "repeats": 3,
                  "spread": {"xruns": [0, 5], "cpu_pct": [0, s["cpu_pct"] + 1]}})
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_a_negative_xrun_count_is_red(self):
        doc = example()
        first_ok(doc)["xruns"] = -1
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenarios/\d+/xruns:minimum")

    def test_a_stress_no_one_declared_is_red(self):
        doc = example()
        first_ok(doc)["stress"] = "heavy"
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenarios/\d+/stress:pattern")

    def test_a_mode_no_one_declared_is_red(self):
        doc = example()
        first_ok(doc)["mode"] = "grouped"
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenarios/\d+/mode:enum")

    def test_a_spread_that_does_not_hold_the_median_is_red(self):
        doc = example()
        s = first_ok(doc)
        s.update({"repeats": 3, "xruns": 4, "spread": {"xruns": [0, 2]}})
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:spread-holds-median", out)

    def test_a_spread_with_min_above_max_is_red(self):
        doc = example()
        s = first_ok(doc)
        s.update({"repeats": 3, "xruns": 1, "spread": {"xruns": [3, 0]}})
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:spread-min-max", out)

    def test_a_spread_of_one_run_is_red(self):
        doc = example()
        s = first_ok(doc)
        s.update({"repeats": 1, "xruns": 1, "spread": {"xruns": [0, 2]}})
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:spread-needs-repeats", out)

    def test_a_stressed_row_without_xruns_is_red(self):
        doc = example()
        first_ok(doc)["stress"] = "busy4+mem256"
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:stress-reports-xruns", out)

    def test_the_same_row_with_and_without_stress_are_two_rows(self):
        doc = example()
        a = first_ok(doc)
        b = copy.deepcopy(a)
        a.update({"stress": "none", "xruns": 0})
        b.update({"stress": "busy4+mem256", "xruns": 3})
        doc["scenarios"].append(b)
        code, out = validate(doc)
        self.assertEqual(code, 0, out)
        c = copy.deepcopy(b)
        doc["scenarios"].append(c)
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:unique-row", out)


if __name__ == "__main__":
    unittest.main()

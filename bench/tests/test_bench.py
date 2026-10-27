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


bench = load("bench_runner", os.path.join(BENCH, "lib", "bench.py"))


class FakeJack:
    """libjack as far as the probe uses it: the calls are Python functions, the xrun callback is kept for the test
    to fire as JACK's notification thread would"""

    def __init__(self, ports=None):
        self.callback = None
        self.ports = ports or {}
        self.calls = []
        self.opened = {}

    def jack_client_open(self, name, options, status, server):
        self.opened = {"name": name, "options": options, "server": server}
        return 1

    def jack_set_xrun_callback(self, client, cb, arg):
        self.callback = cb
        return 0

    def jack_activate(self, client):
        self.calls.append("activate")
        return 0

    def jack_deactivate(self, client):
        self.calls.append("deactivate")
        return 0

    def jack_client_close(self, client):
        self.calls.append("close")
        return 0

    def jack_port_by_name(self, client, name):
        return 7 if name.decode() in self.ports else 0

    def jack_recompute_total_latencies(self, client):
        self.calls.append("recompute")
        return 0

    def jack_port_get_latency_range(self, port, mode, rng):
        assert mode == 0, "the capture latency is what reaches a playback port"
        rng._obj.min, rng._obj.max = 128, [v for v in self.ports.values()][0]

    def xrun(self, n=1):
        for _ in range(n):
            assert self.callback(None) == 0


class Xruns(unittest.TestCase):
    def test_the_probe_counts_what_jack_reports(self):
        lib = FakeJack()
        probe = bench.JackProbe("bench1", lib=lib)
        self.assertEqual(probe.count(), 0)
        lib.xrun(3)
        self.assertEqual(probe.count(), 3)
        lib.xrun(2)
        self.assertEqual(probe.count(), 5)

    def test_the_probe_joins_the_private_server_only(self):
        lib = FakeJack()
        bench.JackProbe("bench1", lib=lib)
        self.assertEqual(lib.opened["server"], b"bench1")
        self.assertEqual(lib.opened["options"], 0x04 | 0x01, "a named server, and never one started by the probe")

    def test_a_window_counts_the_xruns_inside_it(self):
        lib = FakeJack()
        probe = bench.JackProbe("bench1", lib=lib)
        lib.xrun(4)
        before = probe.count()
        lib.xrun(2)
        self.assertEqual(bench.window_xruns(probe.count() - before, 0), 2)

    def test_the_latency_is_the_longest_of_the_range(self):
        lib = FakeJack(ports={"system:playback_1": 512})
        probe = bench.JackProbe("bench1", lib=lib)
        self.assertEqual(probe.latency_frames("system:playback_1"), 512)
        self.assertIn("recompute", lib.calls)
        self.assertIsNone(probe.latency_frames("nobody:out"))

    def test_close_leaves_the_server(self):
        lib = FakeJack()
        bench.JackProbe("bench1", lib=lib).close()
        self.assertEqual(lib.calls[-2:], ["deactivate", "close"])

    def test_a_deaf_probe_is_failed_not_zero(self):
        with self.assertRaisesRegex(bench.Failed, "logged 2 xrun line"):
            bench.window_xruns(0, 2)
        self.assertEqual(bench.window_xruns(0, 0), 0)
        self.assertEqual(bench.window_xruns(3, 1), 3)

    def test_the_servers_log_counts_new_xrun_lines_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "jackd.log")
            with open(path, "w") as f:
                f.write("JackEngine::XRun: client = a was not finished\n")
            n, end = bench.jack_log_xruns(path, 0)
            self.assertEqual(n, 1)
            with open(path, "a") as f:
                f.write("started\nJackEngine::XRun: client = b\nan XRUN again\n")
            n2, end2 = bench.jack_log_xruns(path, end)
            self.assertEqual(n2, 2)
            self.assertEqual(bench.jack_log_xruns(path, end2), (0, end2))
            self.assertEqual(bench.jack_log_xruns(os.path.join(d, "none"), 5), (0, 5))


if __name__ == "__main__":
    unittest.main()

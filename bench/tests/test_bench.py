"""Unit tests of the harness: run with `python3 -I bench/tests/test_bench.py`. They need no JACK server and no host:
the schema and validator rules, and (below) the pieces of the runner that decide a number."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
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


def proc_field(pid, key):
    with open("/proc/%d/status" % pid) as f:
        for line in f:
            if line.startswith(key + ":"):
                return line.split(":", 1)[1].strip()


class Stress(unittest.TestCase):
    def test_the_profile_names_the_cores_and_the_memory(self):
        self.assertEqual(bench.stress_profile([0, 1, 2, 3]), "busy4+mem256")
        self.assertEqual(bench.stress_profile(list(range(24))), "busy24+mem256")

    def test_the_profile_is_one_the_schema_accepts(self):
        doc = example()
        s = first_ok(doc)
        s.update({"stress": bench.stress_profile([0, 1]), "xruns": 0})
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_one_busy_loop_per_core_and_one_memory_touch(self):
        argvs = bench.stress_argvs([2, 5, 7])
        self.assertEqual([n for n, _ in argvs], ["stress-busy-2", "stress-busy-5", "stress-busy-7", "stress-mem"])
        self.assertEqual([a[-1] for _, a in argvs], ["2", "5", "7", "256"])
        for _, a in argvs:
            self.assertEqual(a[1], "-I", "no code from the current directory")

    def test_a_busy_loop_runs_on_its_core_only(self):
        core = bench.stress_cores()[-1]
        _, argv = bench.stress_argvs([core])[0]
        p = subprocess.Popen(argv)
        try:
            deadline = time.monotonic() + 5
            while proc_field(p.pid, "Cpus_allowed_list") != str(core):
                self.assertLess(time.monotonic(), deadline, "never pinned to core %d" % core)
                time.sleep(0.02)
            self.assertEqual(proc_field(p.pid, "State")[0], "R", "it should be busy, not asleep")
        finally:
            p.kill()
            p.wait()

    def test_the_memory_touch_holds_its_size(self):
        _, argv = bench.stress_argvs([0], mem_mb=64)[-1]
        p = subprocess.Popen(argv)
        try:
            deadline = time.monotonic() + 10
            kb = 0
            while kb < 64 * 1024:
                self.assertLess(time.monotonic(), deadline, "resident only %d kB" % kb)
                kb = int(proc_field(p.pid, "VmRSS").split()[0])
                time.sleep(0.05)
        finally:
            p.kill()
            p.wait()

    def test_stress_rows_are_the_same_scenario_with_and_without(self):
        import types
        with open(os.path.join(BENCH, "scenarios.json")) as f:
            table = json.load(f)
        for choice, want in (("none", [False]), ("on", [True]), ("both", [False, True])):
            fake = types.SimpleNamespace(args=types.SimpleNamespace(hosts=["H2"], scenarios=["cvp8", "clap1"],
                                                                    stress=choice), table=table)
            rows = bench.Runner.plan(fake)
            self.assertEqual(sorted({st for sc, _, _, st in rows if sc["id"] == "cvp8"}), want)
            self.assertEqual({st for sc, _, _, st in rows if sc["id"] == "clap1"}, {False},
                             "a scenario that declares no stress never runs under it")
            self.assertEqual(sorted(m for sc, _, m, st in rows if sc["id"] == "cvp8" and st == want[0]),
                             ["chain", "individual"])


def run_row(**kw):
    row = {"id": "cvp8", "title": "t", "host": "H2", "mode": "chain", "rate": 48000, "frames": 256, "plugins": ["a"],
           "dsp_load_avg": 4.0, "dsp_load_max": 5.0, "samples": 10, "rss_mb": 100.0, "add_ms": 50.0,
           "recover_ms": None, "status": "ok", "note": "", "processes": 2, "rss_mb_total": 100.0,
           "pss_mb_total": 40.0, "cpu_pct": 7.0, "ctx_switches": 1000, "ctx_involuntary": 10, "xruns": 0,
           "latency_frames": 256, "stress": "none"}
    row.update(kw)
    return row


class Repeats(unittest.TestCase):
    def test_the_median_and_the_spread_of_three_runs(self):
        runs = [run_row(xruns=0, cpu_pct=7.0), run_row(xruns=5, cpu_pct=9.5), run_row(xruns=2, cpu_pct=8.0)]
        row = bench.aggregate(runs, 3)
        self.assertEqual(row["xruns"], 2)
        self.assertEqual(row["spread"]["xruns"], [0, 5])
        self.assertEqual(row["cpu_pct"], 8.0)
        self.assertEqual(row["spread"]["cpu_pct"], [7.0, 9.5])
        self.assertEqual(row["repeats"], 3)
        self.assertEqual(row["status"], "ok")

    def test_a_count_stays_a_count_and_is_never_understated(self):
        row = bench.aggregate([run_row(xruns=1, ctx_switches=10), run_row(xruns=4, ctx_switches=20)], 2)
        self.assertEqual(row["xruns"], 4)
        self.assertIsInstance(row["xruns"], int)
        self.assertEqual(row["ctx_switches"], 20)
        self.assertEqual(row["spread"]["xruns"], [1, 4])

    def test_the_median_is_the_middle_run_not_the_mean(self):
        row = bench.aggregate([run_row(dsp_load_avg=1.0), run_row(dsp_load_avg=2.0), run_row(dsp_load_avg=90.0)], 3)
        self.assertEqual(row["dsp_load_avg"], 2.0)

    def test_the_aggregate_row_is_a_valid_row(self):
        doc = example()
        doc["scenarios"] = [bench.aggregate([run_row(xruns=x, recover_ms=r) for x, r in
                                             ((0, 900.0), (3, 1100.0), (1, 1000.0))], 3)]
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_one_run_is_a_row_with_no_spread(self):
        row = bench.aggregate([run_row(xruns=3)], 1)
        self.assertEqual(row["xruns"], 3)
        self.assertEqual(row["repeats"], 1)
        self.assertNotIn("spread", row)

    def test_a_measure_missing_from_a_run_has_no_median(self):
        row = bench.aggregate([run_row(recover_ms=None), run_row(recover_ms=1000.0), run_row(recover_ms=None)], 3)
        self.assertIsNone(row["recover_ms"])
        self.assertNotIn("recover_ms", row["spread"])

    def test_a_failed_repeat_fails_the_row_and_names_it(self):
        runs = [run_row(xruns=0), run_row(status="failed", note="the chain did not form", xruns=7)]
        row = bench.aggregate(runs, 3)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["note"], "repeat 2 of 3: the chain did not form")
        self.assertNotIn("spread", row)
        self.assertNotIn("repeats", row)

    def test_an_unsupported_row_is_not_a_failure_of_a_repeat(self):
        row = bench.aggregate([run_row(status="unsupported", note="jalv is not installed")], 3)
        self.assertEqual(row["status"], "unsupported")
        self.assertEqual(row["note"], "jalv is not installed")

    def test_the_runner_stops_repeating_at_the_first_row_that_is_not_ok(self):
        import types
        calls = []
        answers = [run_row(), run_row(status="failed", note="broke")]
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=3))
        fake.row = lambda *a: calls.append(a) or answers[len(calls) - 1]
        row = bench.Runner.measure(fake, {}, "H2", "chain", 48000, 256, False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(row["status"], "failed")

    def test_the_runner_runs_the_row_as_many_times_as_asked(self):
        import types
        calls = []
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=3))
        fake.row = lambda *a: calls.append(a) or run_row(xruns=len(calls))
        row = bench.Runner.measure(fake, {}, "H2", "chain", 48000, 256, False)
        self.assertEqual(len(calls), 3)
        self.assertEqual(row["xruns"], 2)
        self.assertEqual(row["spread"]["xruns"], [1, 3])


if __name__ == "__main__":
    unittest.main()

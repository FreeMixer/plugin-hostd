"""Unit tests of the harness: run with `python3 -I bench/tests/test_bench.py`. They need no JACK server and no host:
the schema and validator rules, and (below) the pieces of the runner that decide a number."""

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
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
        s.update({"mode": "plan", "xruns": 2, "latency_frames": 256, "jack_clients": 3, "stress": "busy24+mem256", "repeats": 3,
                  "spread": {"xruns": [0, 5], "cpu_pct": [0, s["cpu_pct"] + 1]}})
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_a_repeat_state_as_the_runner_reads_it_is_valid(self):
        # what machine_state writes before and after each window, the core of each frequency included
        doc = example()
        st = {"freq_mhz": [800.0, 4800.0], "freq_cores": [0, 1], "temp_c": 41.0, "throttled": None,
              "host_cores": [1], "jackd_cores": [1], "usb_irq_core": None,
              "cpufreq_driver": "intel_pstate", "pstate": "active", "governor": "performance",
              "throttle_core": [112434, 7], "throttle_package": [238271, 238271]}
        first_ok(doc)["repeat_state"] = [{"before": dict(st), "after": dict(st)}]
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_a_negative_xrun_count_is_red(self):
        doc = example()
        first_ok(doc)["xruns"] = -1
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenarios/\d+/xruns:minimum")

    def test_a_negative_jack_client_count_is_red(self):
        doc = example()
        first_ok(doc)["jack_clients"] = -1
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenarios/\d+/jack_clients:minimum")

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

    def jack_on_shutdown(self, client, callback, arg):
        self.shutdown = callback

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

    loads = ()

    def jack_cpu_load(self, client):
        """the loads the test scripted, one a call, the last one again when they run out"""
        self.calls.append("cpu_load")
        n = self.calls.count("cpu_load") - 1
        return self.loads[min(n, len(self.loads) - 1)] if self.loads else 0.0

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
        self.assertEqual(bench.window_xruns(probe.count() - before, 0), (2, ""))

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

    def test_a_windows_xruns_are_the_larger_of_the_probe_and_the_log(self):
        """a client that misses its cycle is an xrun the server logs and tells that client alone; the probe hears the
        driver's overruns only. Neither source may understate the other"""
        self.assertEqual(bench.window_xruns(0, 13), (13, "xruns: the probe counted 0, jackd logged 13 event(s)"))
        self.assertEqual(bench.window_xruns(50, 10), (50, "xruns: the probe counted 50, jackd logged 10 event(s)"))
        self.assertEqual(bench.window_xruns(0, 0), (0, ""))
        self.assertEqual(bench.window_xruns(3, 1), (3, ""), "within the tolerance: no note")
        self.assertEqual(bench.window_xruns(100, 92), (100, ""), "a tenth of the larger: no note")
        self.assertEqual(bench.window_xruns(100, 88), (100, "xruns: the probe counted 100, jackd logged 88 event(s)"))

    def test_a_deaf_probe_is_not_zero_and_not_a_failure(self):
        self.assertEqual(bench.window_xruns(0, 2), (2, ""), "two events the probe missed: the log's count, inside the tolerance")
        xruns, note = bench.window_xruns(0, 13)
        self.assertEqual(xruns, 13)
        self.assertIn("counted 0", note)

    def test_the_servers_log_counts_new_xrun_events_only(self):
        """the server writes one XRun line per client late in the cycle, together: a burst is one event"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "jackd.log")
            with open(path, "w") as f:
                f.write("JackEngine::XRun: client = a was not finished\n")
            n, end = bench.jack_log_xruns(path, 0)
            self.assertEqual(n, 1)
            with open(path, "a") as f:
                f.write("JackEngine::XRun: client = b was not finished\nJackEngine::XRun: client = c was not finished\n"
                        "JackAudioDriver::ProcessGraphAsyncMaster: Process error\n"
                        "JackEngine::XRun: client = b was not finished\nan XRUN again\n"
                        "JackAudioDriver::ProcessGraphAsyncMaster: Process error\n")
            n2, end2 = bench.jack_log_xruns(path, end)
            self.assertEqual(n2, 2, "two bursts of late clients, 4 lines, are two events")
            self.assertEqual(bench.jack_log_xruns(path, end2), (0, end2))
            self.assertEqual(bench.jack_log_xruns(os.path.join(d, "none"), 5), (0, 5))

    def test_the_dsp_load_is_read_from_the_server_by_the_probe_and_the_first_reading_is_dropped(self):
        import types
        lib = FakeJack()
        lib.loads = (0.0, 12.5, 13.5, 11.0)
        probe = bench.JackProbe("bench1", lib=lib)
        fake = types.SimpleNamespace(probe=probe)
        loads = bench.Runner.dsp_window(fake, 3, pace=0.01)
        self.assertEqual(loads, [12.5, 13.5, 11.0])
        self.assertEqual(lib.calls.count("cpu_load"), 4, "one reading a second over seconds+1, the first the warm-up")

    def test_a_probe_without_a_client_cannot_read_the_dsp_load(self):
        lib = FakeJack()
        probe = bench.JackProbe("bench1", lib=lib)
        probe.close()
        with self.assertRaisesRegex(bench.Failed, "no JACK client"):
            probe.cpu_load()


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

    def test_a_guard_prefixes_every_load_process_and_none_without_one(self):
        guard = ["/opt/guard.sh", "bench", "--"]
        plain = bench.stress_argvs([0, 3])
        guarded = bench.stress_argvs([0, 3], guard=guard)
        self.assertEqual(len(guarded), len(plain))
        for (name, argv), (gname, gargv) in zip(plain, guarded):
            self.assertEqual(name, gname)
            self.assertEqual(gargv[:3], guard)
            self.assertEqual(gargv[3:], argv)
        self.assertEqual(bench.stress_argvs([0, 3], guard=()), plain)

    def test_a_load_process_that_ended_is_named_and_a_running_one_is_not(self):
        class P:
            def __init__(self, name, rc):
                self.name, self.rc = name, rc

            def poll(self):
                return self.rc

        self.assertEqual(bench.stress_ended([P("stress-busy-0", None), P("stress-mem", 1), P("stress-busy-1", 0)]),
                         ["stress-mem", "stress-busy-1"])
        self.assertEqual(bench.stress_ended([]), [])

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
                             ["chain", "chain-add", "individual"])


def run_row(**kw):
    row = {"id": "cvp8", "title": "t", "host": "H2", "mode": "chain", "rate": 48000, "frames": 256, "plugins": ["a"],
           "dsp_load_avg": 4.0, "dsp_load_max": 5.0, "samples": 10, "rss_mb": 100.0, "add_ms": 50.0,
           "recover_ms": None, "status": "ok", "note": "", "processes": 2, "rss_mb_total": 100.0,
           "pss_mb_total": 40.0, "cpu_pct": 7.0, "ctx_switches": 1000, "ctx_involuntary": 10, "xruns": 0,
           "latency_frames": 256, "stress": "none"}
    row.update(kw)
    return row



class ProcessSet(unittest.TestCase):
    """the per-process memory beside the totals: this process is a real one, so its set is read from /proc"""

    def test_this_process_is_named_with_its_memory(self):
        me = os.getpid()
        entries = bench.process_set([me])
        self.assertEqual(len(entries), 1)
        e = entries[0]
        with open("/proc/%d/comm" % me) as f:
            self.assertEqual(e["name"], f.read().strip())
        self.assertEqual(e["pid"], me)
        self.assertGreater(e["rss_mb"], 0)
        self.assertTrue(e["pss_mb"] is None or 0 < e["pss_mb"] <= e["rss_mb"] + 0.1)
        self.assertEqual(sorted(e), ["name", "pid", "pss_mb", "rss_mb"])

    def test_a_process_that_is_gone_is_left_out_and_the_set_is_sorted(self):
        me = os.getpid()
        gone = 2 ** 22 - 1  # above pid_max on every default kernel
        sampled = {me: bench.proc_sample(me), 1: {"ticks": 0, "rss": 2048, "pss": None, "vol": 0, "invol": 0}}
        entries = bench.process_set([me, gone, 1], sampled)
        self.assertEqual([e["pid"] for e in entries if e["pid"] == gone], [])
        self.assertEqual(entries, sorted(entries, key=lambda e: (e["name"], e["pid"])))
        one = [e for e in entries if e["pid"] == 1][0]
        self.assertEqual((one["rss_mb"], one["pss_mb"]), (2.0, None))

    def test_a_row_with_the_set_is_valid_and_a_set_that_does_not_count_the_processes_is_red(self):
        doc = example()
        row = first_ok(doc)
        row["processes"] = 2
        row["rss_mb_total"] = row["rss_mb"]
        row["process_set"] = [{"name": "plugin-hostd", "pid": 10, "rss_mb": 3.5, "pss_mb": 2.0},
                              {"name": "omx-clap-host", "pid": 11, "rss_mb": 20.0, "pss_mb": None}]
        code, out = validate(doc)
        self.assertEqual(code, 0, out)
        row["process_set"].pop()
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:process-set-counts-processes", out)
        row["process_set"].append({"name": "omx-clap-host", "pid": 11, "rss_mb": -1, "pss_mb": None})
        code, out = validate(doc)
        self.assertEqual(code, 1, out)
        doc["stress_guard"] = "/opt/guard.sh bench --"
        row["process_set"][-1]["rss_mb"] = 20.0
        code, out = validate(doc)
        self.assertEqual(code, 0, out)
        doc["stress_guard"] = ""
        self.assertEqual(validate(doc)[0], 1)

    def test_the_aggregate_carries_the_set_of_the_run_whose_total_it_holds(self):
        base = first_ok(example())
        runs = []
        for n, total in enumerate((30.0, 10.0, 20.0)):
            r = dict(base)
            r["processes"] = 1
            r["rss_mb_total"] = total
            r["process_set"] = [{"name": "w", "pid": 100 + n, "rss_mb": total, "pss_mb": None}]
            runs.append(r)
        row = bench.aggregate(runs)
        self.assertEqual(row["rss_mb_total"], 20.0)
        self.assertEqual(row["process_set"][0]["pid"], 102)

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
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=3), jack_dirty=False, cell_rate=48000,
                                     cell_frames=256)
        fake.row = lambda *a: calls.append(a) or answers[len(calls) - 1]
        row = bench.Runner.measure_group(fake, [({}, "H2", "chain", False)])[0]
        self.assertEqual(len(calls), 2)
        self.assertEqual(row["status"], "failed")

    def test_the_runner_runs_the_row_as_many_times_as_asked(self):
        import types
        calls = []
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=3), jack_dirty=False, cell_rate=48000,
                                     cell_frames=256)
        fake.row = lambda *a: calls.append(a) or run_row(xruns=len(calls))
        row = bench.Runner.measure_group(fake, [({}, "H2", "chain", False)])[0]
        self.assertEqual(len(calls), 3)
        self.assertEqual(row["xruns"], 2)
        self.assertEqual(row["spread"]["xruns"], [1, 3])


class JackUnanswered(unittest.TestCase):
    """a JACK that stops answering (a wedged server: jack_lsp hangs) fails the row it was in with that reason, the
    server is started again for the next row, and the run goes on to its document"""

    def setUp(self):
        keep = getattr(bench, "JACK_TOOL_TIMEOUT_S", None)
        bench.JACK_TOOL_TIMEOUT_S = 0.5
        self.addCleanup(setattr, bench, "JACK_TOOL_TIMEOUT_S", keep)
        self.bin = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.bin]))
        with open(os.path.join(self.bin, "jack_lsp"), "w") as f:
            f.write("#!/bin/sh\nexec sleep 30\n")
        os.chmod(os.path.join(self.bin, "jack_lsp"), 0o755)
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))

    def test_a_jack_tool_that_hangs_is_a_failed_row_naming_it(self):
        t0 = time.monotonic()
        with self.assertRaises(bench.Failed) as e:
            bench.ports(self.env)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertIn("JACK did not answer: jack_lsp timed out", str(e.exception))

    def test_the_run_goes_on_and_jack_starts_again_after_a_row_it_did_not_answer(self):
        import types
        starts, rows = [], []
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=1), jack_dirty=False)
        fake.jack_stop = lambda: None

        def jack_start(rate, frames):
            starts.append((rate, frames))

        def row(s, hkey, mode, rate, frames, stress=False):
            rows.append(s["id"])
            if s["id"] == "wedged":
                return bench.Runner.row_failed_by(fake, bench.JackUnanswered("JACK did not answer: jack_lsp timed out"),
                                                  bench.Runner.blank_row(fake, s, hkey, mode, rate, frames, stress))
            return run_row(id=s["id"])

        fake.jack_start = jack_start
        fake.row = row
        fake.measure_group = lambda g: bench.Runner.measure_group(fake, g)
        fake.blank_row = lambda *a: bench.Runner.blank_row(fake, *a)
        fake.row_failed_by = lambda e, r: bench.Runner.row_failed_by(fake, e, r)
        plan = [({"id": i, "title": i}, "H2", "individual", False) for i in ("first", "wedged", "after")]
        out = bench.Runner.run_cell(fake, 96000, 64, plan)
        self.assertEqual(rows, ["first", "wedged", "after"])
        self.assertEqual([r["status"] for r in out], ["ok", "failed", "ok"])
        self.assertIn("JACK did not answer: jack_lsp timed out", out[1]["note"])
        self.assertEqual(starts, [(96000, 64), (96000, 64)], "one start for the cell and one after the wedged row")

    def test_a_jack_that_does_not_start_again_fails_each_row_and_the_run_still_ends(self):
        import types
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=1), jack_dirty=False)
        fake.jack_stop = lambda: None

        def jack_start(rate, frames):
            raise bench.JackUnanswered("JACK did not start at %d Hz / %d frames" % (rate, frames))

        fake.jack_start = jack_start
        fake.row = lambda *a: self.fail("no row runs without a JACK server")
        fake.measure_group = lambda g: bench.Runner.measure_group(fake, g)
        fake.blank_row = lambda *a: bench.Runner.blank_row(fake, *a)
        fake.row_failed_by = lambda e, r: bench.Runner.row_failed_by(fake, e, r)
        plan = [({"id": i, "title": i}, "H2", "individual", False) for i in ("a", "b")]
        out = bench.Runner.run_cell(fake, 96000, 64, plan)
        self.assertEqual([(r["id"], r["status"]) for r in out], [("a", "failed"), ("b", "failed")])
        self.assertIn("JACK did not start", out[0]["note"])


class ProbeHardTimeout(unittest.TestCase):
    """a server that stops answering holds a libjack call forever: the call runs in a process of its own, and past its
    timeout that process is killed and the row fails, so one wedged server never holds the run"""

    READY = 'import sys, time; print(\'{"ok": true}\', flush=True); '

    def setUp(self):
        keep = bench.PROBE_TIMEOUT_S
        bench.PROBE_TIMEOUT_S = 0.5
        self.addCleanup(setattr, bench, "PROBE_TIMEOUT_S", keep)
        self.logs = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.logs]))
        self.procs = bench.Procs(self.logs, "bench1")
        self.addCleanup(self.procs.stop_all)

    def probe(self, body):
        return bench.ProbeProcess("bench1", self.procs, argv=[sys.executable, "-I", "-c", body])

    def test_a_call_that_hangs_fails_the_row_within_the_timeout_and_the_process_is_gone(self):
        probe = self.probe(self.READY + "sys.stdin.readline(); time.sleep(60)")
        proc = probe.proc
        t0 = time.monotonic()
        with self.assertRaises(bench.JackUnanswered) as e:
            probe.cpu_load()
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIn("JACK did not answer: the xrun probe timed out", str(e.exception))
        self.assertIsNotNone(proc.poll(), "the stuck process is killed")
        self.assertEqual(self.procs.live, [])

    def test_a_start_that_hangs_fails_the_row(self):
        t0 = time.monotonic()
        with self.assertRaises(bench.JackUnanswered):
            self.probe("import time; time.sleep(60)")
        self.assertLess(time.monotonic() - t0, 10)

    def test_close_returns_from_a_wedged_server_and_kills_the_process(self):
        probe = self.probe(self.READY + "time.sleep(60)")
        proc = probe.proc
        t0 = time.monotonic()
        probe.close()
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(self.procs.live, [])

    def test_jack_stop_gets_past_a_wedged_probe_to_the_server(self):
        fake = types.SimpleNamespace(probe=self.probe(self.READY + "time.sleep(60)"), jackd=None, procs=self.procs)
        bench.Runner.jack_stop(fake)
        self.assertIsNone(fake.probe)

    def test_the_probe_is_not_a_process_left_behind_by_a_row(self):
        fake = types.SimpleNamespace(probe=self.probe(self.READY + "time.sleep(60)"), jackd=None)
        bench.Runner.assert_only_jack(fake, "after a row")

    def test_a_process_that_dies_fails_the_row(self):
        probe = self.probe(self.READY)
        with self.assertRaises(bench.JackUnanswered) as e:
            probe.count()
        self.assertIn("exited", str(e.exception))

    def test_a_call_after_the_process_is_gone_fails_the_row_again(self):
        probe = self.probe(self.READY)
        with self.assertRaises(bench.JackUnanswered):
            probe.count()
        with self.assertRaises(bench.JackUnanswered):
            probe.count()

    def test_no_libjack_still_ends_the_run(self):
        with self.assertRaises(SystemExit):
            self.probe("""print('{"error": "bench: libjack is needed to count xruns"}', flush=True)""")

    def test_the_process_answers_what_the_probe_reads(self):
        import io
        lib = FakeJack(ports={"system:playback_1": 512})
        probe = bench.JackProbe("bench1", lib=lib)
        lib.xrun(2)
        out = io.StringIO()
        asks = [{"op": "count"}, {"op": "latency_frames", "args": ["system:playback_1"]}, {"op": "close"}]
        bench.probe_serve(probe, [json.dumps(a) for a in asks], out)
        self.assertEqual([json.loads(x) for x in out.getvalue().splitlines()], [{"ok": 2}, {"ok": 512}, {"ok": None}])
        self.assertEqual(lib.calls[-2:], ["deactivate", "close"])

    def test_a_server_that_went_away_is_an_error_not_an_old_reading(self):
        import io
        lib = FakeJack()
        probe = bench.JackProbe("bench1", lib=lib)
        probe._on_shutdown(None)
        out = io.StringIO()
        bench.probe_serve(probe, [json.dumps({"op": "cpu_load"}), json.dumps({"op": "close"})], out)
        self.assertEqual(json.loads(out.getvalue().splitlines()[0]), {"error": "the JACK server went away"})


class FakeDaemon:
    """plugin-hostd as far as the plan and pool modes talk to it, on a socket, NUL-framed like the real one: add,
    remove, plan, worker_list. Its planner is the simplest honest one: runs of consecutive members that are not
    `isolated` share a worker. `pool_apart` makes it put each pooled member in a worker of its own, and `pool_as` puts them
    in a pool of another name, as a daemon that ignored the place would"""

    def __init__(self, isolated, pool_apart=False, one_segment=False, pool_as=None):
        import socketserver
        import threading
        self.isolated, self.pool_apart, self.one_segment, self.pool_as = set(isolated), pool_apart, one_segment, pool_as
        self.inst = {}  # instance -> place
        self.log = []
        daemon = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                buf = b""
                while True:
                    chunk = self.request.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                    while b"\0" in buf:
                        line, buf = buf.split(b"\0", 1)
                        self.request.sendall(daemon.reply(line.decode()).encode() + b"\0")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def reply(self, line):
        self.log.append(line)
        w = line.split()
        if w[0] == "add":
            place = w[3] if len(w) > 3 else "own"
            self.inst[int(w[2])] = self.pool_as if self.pool_as and place.startswith("pool:") else place
            return "resp %s" % w[2]
        if w[0] == "remove":
            self.inst.pop(int(w[1]))
            return "resp 0"
        if w[0] == "plan":
            members = [int(x) for x in w[2:]]
            segs, cur = [], []
            for i in members:
                if i in self.isolated:
                    if cur:
                        segs.append(cur)
                    segs.append([i])
                    cur = []
                else:
                    cur.append(i)
            if cur:
                segs.append(cur)
            if self.one_segment:
                segs = [members]
            for k, seg in enumerate(segs):
                for i in seg:
                    self.inst[i] = "chain:1.%d" % k if len(seg) > 1 else "own"
            return "resp 0 " + ";".join(",".join(map(str, g)) for g in segs) + " " + ";".join(
                ",".join("1" for _ in g) for g in segs)
        if w[0] == "worker_list":
            workers = {}
            for i, place in sorted(self.inst.items()):
                key = place if place.startswith(("chain:", "pool:")) and not (
                    self.pool_apart and place.startswith("pool:")) else "own%d" % i
                workers.setdefault(key, (place, []))[1].append(i)
            recs = ["%d:%d:clap:up:%d:qualified:%s:%s" % (n, 1000 + n, 1 + n % 3, place, ",".join(map(str, ids)))
                    for n, (place, ids) in enumerate(workers.values())]
            return "resp 0 " + " ".join(recs)
        return "resp -902"


class Gone:
    def poll(self):
        return None


def daemon_host(daemon, case):
    host = bench.Host.__new__(bench.Host)
    host.key = "H2"
    host.ctl = bench.Control(daemon.port, Gone())
    case.addCleanup(host.ctl.close)
    return host


class Grouping(unittest.TestCase):
    def setUp(self):
        keep = bench.READY_LIMIT_S
        bench.READY_LIMIT_S = 0.5
        self.addCleanup(setattr, bench, "READY_LIMIT_S", keep)

    uris = ["clap:/c#comp", "clap:/d#delay", "clap:/x#drive", "clap:/c#comp", "clap:/x#drive", "clap:/c#comp"]

    def test_the_plan_is_read_as_segments_and_waited_for(self):
        d = FakeDaemon(isolated=[2, 4])
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            segs = host.declare_plan(list(range(6)))
            self.assertEqual(segs, [[0, 1], [2], [3], [4], [5]])
            self.assertIn("plan 1 0 1 2 3 4 5", d.log)
        finally:
            d.close()

    def test_a_plan_of_one_segment_fails_the_row(self):
        d = FakeDaemon(isolated=[], one_segment=True)
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            with self.assertRaisesRegex(bench.Failed, "one segment"):
                host.declare_plan(list(range(6)))
        finally:
            d.close()

    def test_a_refused_plan_is_failed_with_the_daemons_words(self):
        d = FakeDaemon(isolated=[])
        d.reply = lambda line: "resp -501 0,1"
        try:
            with self.assertRaisesRegex(bench.Failed, "plan answered 'resp -501 0,1'"):
                daemon_host(d, self).declare_plan([0, 1])
        finally:
            d.close()

    def test_the_pool_takes_the_shareable_members_the_plan_left_alone(self):
        d = FakeDaemon(isolated=[2, 4])
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            segs, pooled = host.declare_pool(list(range(6)), self.uris, alone={2, 4})
            self.assertEqual(segs, [[0, 1], [2], [3], [4], [5]])
            self.assertEqual(pooled, [3, 5], "the isolated members stay out of the pool")
            self.assertEqual(d.inst[3], "pool:g1")
            self.assertEqual(d.inst[5], "pool:g1")
            self.assertEqual(d.inst[2], "own")
            self.assertIn("add clap:/c#comp 3 pool:g1", d.log)
        finally:
            d.close()

    def test_a_pool_the_daemon_split_is_failed(self):
        d = FakeDaemon(isolated=[2, 4], pool_apart=True)
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            with self.assertRaises(bench.Failed):
                host.declare_pool(list(range(6)), self.uris, alone={2, 4})
        finally:
            d.close()

    def test_a_pool_under_another_name_is_failed(self):
        d = FakeDaemon(isolated=[2, 4], pool_as="pool:other")
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            with self.assertRaisesRegex(bench.Failed, "pool:g1 holds"):
                host.declare_pool(list(range(6)), self.uris, alone={2, 4})
        finally:
            d.close()

    def test_a_pool_of_one_is_not_a_pool(self):
        d = FakeDaemon(isolated=[2, 3, 4])
        try:
            host = daemon_host(d, self)
            for i, u in enumerate(self.uris):
                host.add(u, i)
            with self.assertRaisesRegex(bench.Failed, "left 1 shareable"):
                host.declare_pool(list(range(6)), self.uris, alone={2, 3, 4})
        finally:
            d.close()


class Scenarios(unittest.TestCase):
    def test_every_name_a_scenario_uses_is_declared(self):
        with open(os.path.join(BENCH, "scenarios.json")) as f:
            table = json.load(f)
        for sc in table["scenarios"]:
            for key in sc["plugins"] + sc.get("unshared", []):
                self.assertIn(key, table["plugins"], sc["id"])
            if sc.get("family"):
                self.assertIn(sc["family"], table["modes"], sc["id"])
            self.assertTrue(set(sc.get("unshared", [])) <= set(sc["plugins"]), sc["id"])

    def test_the_grouping_scenarios_have_all_four_modes_and_a_strip_the_pins_cut(self):
        with open(os.path.join(BENCH, "scenarios.json")) as f:
            table = json.load(f)
        modes = [m["mode"] for m in table["modes"]["grouping-vs-processes"]]
        self.assertEqual(modes, ["individual", "chain", "plan", "pool"])
        for sc in table["scenarios"]:
            if sc.get("family") != "grouping-vs-processes":
                continue
            keys = [sc["plugins"][n % len(sc["plugins"])] for n in range(sc["count"])]
            cut = [k in sc["unshared"] for k in keys]
            self.assertTrue(any(cut), "%s has nothing for the pins to refuse" % sc["id"])
            single = [i for i, c in enumerate(cut) if not c and (i == 0 or cut[i - 1])
                      and (i == len(cut) - 1 or cut[i + 1])]
            self.assertGreaterEqual(len(single), 2, "%s leaves fewer than two shareable members alone" % sc["id"])


table = load("bench_table", os.path.join(BENCH, "lib", "table.py"))


def family_doc():
    def row(mode, stress, procs, rss, pss, cpu, ctx, dsp, xr, **kw):
        r = run_row(id="cvp8", plugins=["a"] * 8, mode=mode, stress=stress, processes=procs, rss_mb_total=rss,
                    pss_mb_total=pss, cpu_pct=cpu, ctx_switches=ctx, dsp_load_avg=dsp, dsp_load_max=dsp + 1,
                    xruns=xr, rss_mb=rss)
        r.update(kw)
        return r
    doc = example()
    doc["scenarios"] = [
        row("individual", "none", 9, 880.0, 92.0, 6.0, 20000, 4.8, 0),
        row("chain", "none", 2, 118.0, 36.0, 4.0, 2800, 3.9, 0),
        row("individual", "busy4+mem256", 9, 881.0, 92.5, 6.5, 19800, 4.9, 10, repeats=3, spread={"xruns": [4, 18]}),
        row("chain", "busy4+mem256", 2, 118.0, 36.0, 4.1, 2810, 3.9, 3),
        row("plan", "none", 0, 0.0, 0.0, 0.0, 0, 0.0, 0, status="failed", note="the plan is one segment"),
        run_row(id="idle", plugins=[], mode="individual")]
    return doc


class Table(unittest.TestCase):
    def test_the_ratios_of_individual_over_chain(self):
        lines = table.ratios(family_doc())
        self.assertEqual(lines[2], "| cvp8 | 48000/256 | 8 | 9 vs 2 | 7.46x | 2.56x | 1.50x | 7.14x | 1.23x |")

    def test_xruns_are_summed_per_mode_with_and_without_stress(self):
        lines = table.xrun_sums(family_doc())
        self.assertIn("| chain | no | 1 | 0 |", lines)
        self.assertIn("| chain | yes | 1 | 3 |", lines)
        self.assertIn("| individual | yes | 1 | 10 |", lines)

    def test_a_spread_shows_beside_its_median(self):
        lines = table.table(family_doc())
        row = [x for x in lines if "individual | 9 | 881.0" in x][0]
        self.assertIn("| 10 [4-18] |", row)
        self.assertTrue(row.endswith("| 3 |"))

    def test_a_failed_row_is_shown_with_its_reason(self):
        lines = table.table(family_doc())
        self.assertIn("| cvp8 | 48000/256 | 8 | none | plan | failed: the plan is one segment |", lines)

    def test_a_scenario_that_is_not_a_family_is_left_out(self):
        self.assertFalse([x for x in table.table(family_doc()) if "idle" in x])


class Pins(unittest.TestCase):
    store = ("pin_set clap:/c#comp /c.clap=aa omx-layout/1:11\n"
             "pin_set clap:/x#drive /x.clap=bb omx-layout/1:22 verdict=in-process\n"
             "# a comment\n")

    def test_each_uri_gets_its_verdict_and_the_rest_is_kept(self):
        out = bench.set_verdicts(self.store, {"clap:/c#comp": "in-process", "clap:/x#drive": "isolated"})
        self.assertEqual(out.splitlines(), ["pin_set clap:/c#comp /c.clap=aa omx-layout/1:11 verdict=in-process",
                                            "pin_set clap:/x#drive /x.clap=bb omx-layout/1:22 verdict=isolated",
                                            "# a comment"])

    def test_a_uri_the_daemon_never_learned_is_failed(self):
        with self.assertRaisesRegex(bench.Failed, "no pin for clap:/nobody#x"):
            bench.set_verdicts(self.store, {"clap:/nobody#x": "in-process"})

    def test_the_conf_of_a_plan_row_turns_pins_and_grouping_on_and_package_pins_off(self):
        import types
        with tempfile.TemporaryDirectory() as wd:
            fake = types.SimpleNamespace(learn_pins=lambda uris: self.store)
            conf = bench.Runner.plan_conf(fake, wd, ["clap:/c#comp", "clap:/x#drive"], {"clap:/x#drive"})
            self.assertEqual(conf, ("require_pins 1", "pin_mode first-use", "pin_store " + os.path.join(wd, "pins"),
                                    "pins_dir", "grouping on"))
            with open(os.path.join(wd, "pins")) as f:
                lines = f.read().splitlines()
            self.assertIn("pin_set clap:/x#drive /x.clap=bb omx-layout/1:22 verdict=isolated", lines)
            self.assertIn("pin_set clap:/c#comp /c.clap=aa omx-layout/1:11 verdict=in-process", lines)

    def test_a_host_log_is_read_from_where_the_row_began(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "H2.log"), "w") as f:
                f.write("old: bad setting 'grouping'\n")
            end = bench.log_size(d, "H2")
            with open(os.path.join(d, "H2.log"), "a") as f:
                f.write("new line\n")
            self.assertEqual(bench.log_since(d, "H2", end), "new line\n")
            self.assertEqual(bench.log_since(d, "none", 0), "")


class GraphBeforeHost(unittest.TestCase):
    """the graph a row counts from: a client of the host before it may still be leaving JACK, and counting it out of the
    row's clients read 23 at 24 plugins and 46 at 48"""

    def graphs(self, *seen):
        calls = iter(seen)
        real = bench.ports
        bench.ports = lambda env: {c: {} for c in next(calls)}
        self.addCleanup(setattr, bench, "ports", real)

    def test_it_waits_for_the_last_hosts_clients_to_leave(self):
        self.graphs(["system", "effect_23"], ["system", "effect_23"], ["system"])
        self.assertEqual(bench.graph_before_host({}, poll_s=0), {"system"})

    def test_a_client_that_never_leaves_stops_the_row(self):
        self.graphs(*[["system", "effect_0"]] * 5)
        with self.assertRaisesRegex(bench.Failed, "effect_0"):
            bench.graph_before_host({}, limit_s=0, poll_s=0)


class ChainNotFormed(unittest.TestCase):
    """a chain that does not form says what the daemon holds: without it a failed row left nothing to read"""

    def test_the_failure_names_what_the_daemon_answers(self):
        class Ctl:
            def cmd(self, line):
                return {"chain_get 1": "resp 0 w3 0,1,2 0,2", "worker_list": "resp 2 w3:9:clap:up:1:q:chain:1:0,2"}[line]

        class Host:
            ctl = Ctl()

        real = bench.READY_LIMIT_S
        bench.READY_LIMIT_S = 0
        self.addCleanup(setattr, bench, "READY_LIMIT_S", real)
        with self.assertRaisesRegex(bench.Failed, r"did not form within 0 s.*chain_get: resp 0 w3 0,1,2 0,2.*worker_list: resp 2 w3"):
            bench.Runner.chain_formed(None, Host(), [0, 1, 2])


class JackPriority(unittest.TestCase):
    """the private JACK server is asked for a real-time priority; the run refuses to start when a JACK server of someone
    else or an IRQ thread is read at or above it, and says when the server it started was not read at the priority
    asked. Nothing more is claimed: only the threads read from /proc are compared."""

    def proc(self, threads):
        """a /proc of (pid, tid, comm, policy, rt_priority) threads"""
        root = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", root]))
        for pid, tid, comm, policy, prio in threads:
            d = os.path.join(root, str(pid), "task", str(tid))
            os.makedirs(d, exist_ok=True)
            fields = ["S"] + ["0"] * 36 + [str(prio), str(policy)] + ["0"] * 10
            with open(os.path.join(d, "stat"), "w") as f:
                f.write("%d (%s) %s\n" % (tid, comm, " ".join(fields)))
        os.makedirs(os.path.join(root, "self"), exist_ok=True)
        return root

    def test_an_alsa_device_replaces_the_dummy_driver_and_nothing_else(self):
        dummy = bench.jackd_argv("bench1", 48000, 64, 70)
        card = bench.jackd_argv("bench1", 48000, 64, 70, alsa="hw:2")
        self.assertEqual(dummy[:5], card[:5])
        self.assertEqual(dummy[5:7], ["-d", "dummy"])
        self.assertEqual(card[5:9], ["-d", "alsa", "-d", "hw:2"])
        self.assertEqual(dummy[7:], card[9:])
        self.assertEqual(card[9:], ["-r", "48000", "-p", "64"])

    def test_the_runner_starts_its_server_on_the_card_it_was_given_and_on_the_dummy_driver_otherwise(self):
        for alsa, driver in ((None, ["-d", "dummy"]), ("hw:1", ["-d", "alsa", "-d", "hw:1"])):
            fake = types.SimpleNamespace(args=types.SimpleNamespace(jack_priority=70, alsa=alsa, periods=None), server="bench9")
            argv = bench.Runner.jack_argv(fake, 96000, 128)
            self.assertEqual(argv, ["jackd", "-P", "70", "-n", "bench9"] + driver + ["-r", "96000", "-p", "128"])

    def test_a_server_not_read_at_the_priority_asked_is_said_so(self):
        root = self.proc([(707, 708, "jackd", 1, 70), (707, 709, "jackd", 1, 65), (808, 808, "jackd", 1, 10), (909, 909, "jackd", 0, 0)])
        threads = bench.rt_threads(root)
        self.assertIsNone(bench.server_priority_note(threads, 707, 70))
        self.assertRegex(bench.server_priority_note(threads, 808, 70), r"asked for priority 70 and its real-time threads run at 10")
        self.assertRegex(bench.server_priority_note(threads, 909, 70), r"no real-time thread")

    def test_the_server_is_started_at_the_priority_asked(self):
        argv = bench.jackd_argv("bench1", 48000, 64, 70)
        self.assertEqual(argv[:3], ["jackd", "-P", "70"])
        self.assertIn("dummy", argv)
        self.assertEqual(bench.JACK_PRIORITY, 70)

    def test_rt_threads_reads_policy_and_priority_of_every_thread(self):
        root = self.proc([(10, 10, "jackd", 1, 70), (10, 11, "jackd", 0, 0), (20, 21, "irq/38-aer drv", 1, 50)])
        self.assertEqual(sorted(bench.rt_threads(root)), [(10, "jackd", 70), (20, "irq/38-aer drv", 50)])

    def test_a_live_jackd_above_the_bench_refuses_the_run_naming_it(self):
        root = self.proc([(707, 708, "jackd", 1, 80), (707, 709, "jackd", 1, 70), (99, 99, "irq/161-mmc0", 1, 50)])
        why = bench.priority_refusal(bench.rt_threads(root), 70)
        self.assertRegex(why, r"jackd \(pid 707\) runs at real-time priority 80, above the bench's 70")

    def test_irq_threads_at_or_above_the_bench_do_not_refuse_the_run_they_are_warned_of(self):
        root = self.proc([(99, 99, "irq/161-mmc0", 1, 50), (98, 98, "irq/40-vc4", 1, 50)])
        threads = bench.rt_threads(root)
        self.assertIsNone(bench.priority_refusal(threads, 10))
        warned = bench.priority_warnings(threads, 10)
        self.assertEqual(len(warned), 2)
        self.assertTrue(any(re.search(r"irq/161-mmc0 .* 50, at or above the bench's 10", w) for w in warned))
        self.assertEqual(bench.priority_warnings(threads, 70), [])

    def test_a_foreign_jackd_above_the_bench_still_refuses_at_a_low_priority(self):
        root = self.proc([(707, 708, "jackd", 1, 70), (99, 99, "irq/161-mmc0", 1, 50)])
        self.assertRegex(bench.priority_refusal(bench.rt_threads(root), 10), r"jackd \(pid 707\)")

    def test_periods_are_the_alsa_drivers_n_and_the_dummy_driver_has_none(self):
        argv = bench.jackd_argv("b1", 48000, 256, 70, alsa="hw:2", periods=3)
        self.assertEqual(argv[5:], ["-d", "alsa", "-d", "hw:2", "-n", "3", "-r", "48000", "-p", "256"])
        self.assertNotIn("-n", bench.jackd_argv("b1", 48000, 256, 70, alsa="hw:2")[5:])
        with self.assertRaises(ValueError):
            bench.jackd_argv("b1", 48000, 256, 70, periods=3)
        fake = types.SimpleNamespace(args=types.SimpleNamespace(jack_priority=70, alsa="hw:2", periods=3), server="b9")
        self.assertEqual(bench.Runner.jack_argv(fake, 48000, 256)[5:9], ["-d", "alsa", "-d", "hw:2"])
        self.assertEqual(bench.Runner.jack_argv(fake, 48000, 256)[9:11], ["-n", "3"])

    def test_the_document_records_the_driver_the_priority_the_periods_and_what_was_warned(self):
        def jack(**kw):
            args = types.SimpleNamespace(jack_priority=10, alsa=None, periods=None, priority_warnings=[])
            args.__dict__.update(kw)
            return bench.Runner.jack_doc(types.SimpleNamespace(args=args))
        self.assertEqual(jack(), {"driver": "dummy", "priority": 10})
        self.assertEqual(jack(alsa="hw:2", periods=3), {"driver": "alsa", "priority": 10, "device": "hw:2", "periods": 3})
        self.assertEqual(jack(alsa="hw:2")["periods"], 2)
        self.assertEqual(jack(priority_warnings=["x"])["warnings"], ["x"])
        doc = example()
        doc["jack"] = jack(alsa="hw:2", periods=3, priority_warnings=["the IRQ thread irq/1-x (pid 1) runs at 50"])
        self.assertEqual(validate(doc)[0], 0, validate(doc)[1])
        doc["jack"]["periods"] = 1
        self.assertNotEqual(validate(doc)[0], 0)

    def test_the_command_line_refuses_periods_with_the_dummy_driver(self):
        r = subprocess.run([sys.executable, os.path.join(BENCH, "lib", "bench.py"), "--out", "/nonexistent", "--class", "ci",
                            "--periods", "3"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--periods needs --alsa", r.stdout)

    def test_a_machine_with_nothing_above_runs(self):
        root = self.proc([(707, 708, "jackd", 1, 60), (5, 5, "migration/0", 1, 99)])
        self.assertIsNone(bench.priority_refusal(bench.rt_threads(root), 70))

    def test_the_bench_s_own_server_is_not_a_reason_to_refuse(self):
        root = self.proc([(707, 708, "jackd", 1, 80)])
        self.assertIsNone(bench.priority_refusal(bench.rt_threads(root), 70, own={707}))


soundness = load("bench_soundness", os.path.join(BENCH, "lib", "soundness.py"))
DATA = os.path.join(BENCH, "tests", "data")


def pi(name):
    with open(os.path.join(DATA, "pi-1105-cvp16-%s.json" % name)) as f:
        return json.load(f)


def pi_docs():
    """the 11-05 Pi 5 cvp16 H2 rows at 48 kHz: 2 and 3 periods, 128 and 256 frames, and the 3-period stress run"""
    return [pi(n) for n in ("p2-f128", "p2-f256", "p3-f128", "p3-f256", "p3-f256-busy")]


def flagged(docs):
    bad = soundness.check(docs)
    return {(docs[d]["scenarios"][n]["mode"], docs[d]["scenarios"][n]["frames"], docs[d]["jack"]["periods"],
             docs[d]["scenarios"][n].get("stress", "none")): why for (d, n), why in bad.items()}


def cell_doc(rows, periods=None):
    doc = example()
    doc["scenarios"] = rows
    doc["jack"] = {"driver": "alsa", "priority": 70, "periods": periods} if periods else {"driver": "dummy", "priority": 70}
    return doc


def crow(avg, **kw):
    kw.setdefault("dsp_load_max", avg + 1)
    return run_row(dsp_load_avg=avg, **kw)


class Soundness(unittest.TestCase):
    def test_the_pi_chain_cell_at_7_87_is_flagged_by_its_twins(self):
        bad = flagged(pi_docs())
        why = bad[("chain", 256, 3, "none")]
        self.assertTrue(any(w.startswith("twin:") and "6.55" in w for w in why), why)
        self.assertTrue(any(w.startswith("stress:") and "6.68" in w for w in why), why)
        self.assertTrue(any(w.startswith("scaling:") and "6.98" in w for w in why), why)

    def test_the_pi_individual_cell_at_12_52_is_flagged_and_its_twin_is_not_blamed_for_it(self):
        bad = flagged(pi_docs())
        why = bad[("individual", 256, 2, "none")]
        self.assertTrue(any(w.startswith("scaling:") and "11.31" in w for w in why), why)
        self.assertTrue(any(w.startswith("spread:") for w in why), why)

    def test_the_cells_that_agree_are_not_flagged(self):
        bad = flagged(pi_docs())
        for ok in (("chain", 256, 2, "none"), ("chain", 256, 3, "busy4+mem256"), ("chain", 128, 2, "none"),
                   ("chain", 128, 3, "none"), ("chain-add", 256, 2, "none"), ("chain-add", 128, 2, "none")):
            self.assertNotIn(ok, bad)

    def test_the_quiet_cell_alone_in_its_document_is_not_flagged(self):
        self.assertEqual(soundness.check([pi("p2-f256")]).keys() & {(0, 1)}, set())

    def test_a_wide_spread_is_flagged_and_a_narrow_one_is_not(self):
        wide = crow(8.0, repeats=3, spread={"dsp_load_avg": [6.5, 8.1]})
        narrow = crow(8.0, mode="chain-add", repeats=3, spread={"dsp_load_avg": [7.8, 8.2]})
        bad = soundness.check([cell_doc([wide, narrow])])
        self.assertEqual(list(bad), [(0, 0)])
        self.assertTrue(bad[(0, 0)][0].startswith("spread:"))

    def test_a_spread_inside_the_noise_floor_is_not_flagged(self):
        quiet = crow(0.5, repeats=3, spread={"dsp_load_avg": [0.4, 0.6]})
        self.assertEqual(soundness.check([cell_doc([quiet])]), {})

    def test_twins_at_two_period_counts_that_disagree_flag_the_higher(self):
        docs = [cell_doc([crow(6.5)], 2), cell_doc([crow(7.9)], 3)]
        self.assertEqual(list(soundness.check(docs)), [(1, 0)])

    def test_three_twins_flag_the_one_away_from_the_median(self):
        docs = [cell_doc([crow(6.5)], 2), cell_doc([crow(6.6)], 3), cell_doc([crow(5.0)], 4)]
        self.assertEqual(list(soundness.check(docs)), [(2, 0)])

    def test_twins_that_agree_are_not_flagged(self):
        docs = [cell_doc([crow(6.5)], 2), cell_doc([crow(6.8)], 3)]
        self.assertEqual(soundness.check(docs), {})

    def test_a_cell_above_its_stressed_twin_is_flagged(self):
        doc = cell_doc([crow(7.9), crow(6.7, stress="busy4+mem256")], 3)
        bad = soundness.check([doc])
        self.assertEqual(list(bad), [(0, 0)])
        self.assertTrue(bad[(0, 0)][0].startswith("stress:"))

    def test_a_stressed_cell_above_its_quiet_twin_is_the_expected_direction(self):
        doc = cell_doc([crow(6.5), crow(9.0, stress="busy4+mem256")], 3)
        self.assertEqual(soundness.check([doc]), {})

    def test_more_frames_costing_more_is_flagged_and_fewer_is_not(self):
        doc = cell_doc([crow(7.0, frames=128), crow(8.2, frames=256), crow(6.6, frames=512)], 3)
        bad = soundness.check([doc])
        self.assertEqual(list(bad), [(0, 1)])
        self.assertTrue(bad[(0, 1)][0].startswith("scaling:"))

    def test_a_throttled_repeat_is_flagged(self):
        state = [{"after": {"throttled": "0x0", "freq_mhz": [2400.0]}}, {"after": {"throttled": "0x50005", "freq_mhz": [2400.0]}}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=state)])])
        self.assertIn("state: throttled 0x50005 (after of repeat 2)", bad[(0, 0)])

    def test_a_history_only_throttle_bit_is_not_a_disturbance_now(self):
        state = [{"after": {"throttled": "0x50000", "freq_mhz": [2400.0]}}]
        self.assertEqual(soundness.check([cell_doc([crow(6.5, repeat_state=state)])]), {})

    def test_a_frequency_that_moved_between_repeats_is_flagged(self):
        state = [{"before": {"freq_mhz": [2400.0, 2400.0]}}, {"before": {"freq_mhz": [1500.0, 2400.0]}}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=state)])])
        self.assertTrue(bad[(0, 0)][0].startswith("state: CPU frequency 1500..2400"))

    def test_idle_cores_slower_than_the_measured_ones_are_no_disturbance(self):
        # a desk: the cores nothing runs on idle at 800 MHz, the ones the host and JACK run on hold 4800 MHz
        freqs = [800.0, 800.0, 4800.0, 4800.0, 800.0, 800.0]
        st = {"freq_mhz": freqs, "freq_cores": [0, 1, 2, 3, 4, 5], "host_cores": [2], "jackd_cores": [3]}
        state = [{"before": dict(st), "after": dict(st)} for _ in range(3)]
        self.assertEqual(soundness.check([cell_doc([crow(6.5, repeat_state=state)])]), {})

    def test_a_measured_core_that_slowed_between_repeats_is_flagged(self):
        quick = {"freq_mhz": [800.0, 800.0, 4800.0, 4800.0], "freq_cores": [0, 1, 2, 3], "host_cores": [2], "jackd_cores": [3]}
        slow = dict(quick, freq_mhz=[800.0, 800.0, 3000.0, 4800.0])
        state = [{"before": quick, "after": quick}, {"before": slow, "after": slow}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=state)])])
        self.assertTrue(bad[(0, 0)][0].startswith("state: CPU frequency 3000..4800"), bad)

    def test_the_cores_of_the_frequencies_are_read_in_their_own_order(self):
        with tempfile.TemporaryDirectory() as d:
            for n, khz in ((0, 800000), (1, 801000), (2, 802000), (10, 4800000), (11, 4801000)):
                os.makedirs("%s/devices/system/cpu/cpu%d/cpufreq" % (d, n))
                with open("%s/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq" % (d, n), "w") as f:
                    f.write("%d\n" % khz)
            st = bench.machine_state(sysfs=d, proc=d)
        self.assertEqual(st["freq_cores"], [0, 1, 2, 10, 11])
        self.assertEqual(st["freq_mhz"], [800.0, 801.0, 802.0, 4800.0, 4801.0])

    def test_the_clock_driver_and_the_thermal_throttle_counts_are_read_core_by_core(self):
        with tempfile.TemporaryDirectory() as d:
            for n, khz, core, pkg in ((0, 800000, 5, 40), (1, 4800000, 9, 40), (10, 4801000, 0, 41)):
                base = "%s/devices/system/cpu/cpu%d" % (d, n)
                os.makedirs(base + "/cpufreq")
                os.makedirs(base + "/thermal_throttle")
                for name, value in (("cpufreq/scaling_cur_freq", khz), ("cpufreq/scaling_driver", "intel_pstate"),
                                    ("cpufreq/scaling_governor", "performance"),
                                    ("thermal_throttle/core_throttle_count", core),
                                    ("thermal_throttle/package_throttle_count", pkg)):
                    with open("%s/%s" % (base, name), "w") as f:
                        f.write("%s\n" % value)
            os.makedirs(d + "/devices/system/cpu/intel_pstate")
            with open(d + "/devices/system/cpu/intel_pstate/status", "w") as f:
                f.write("active\n")
            st = bench.machine_state(sysfs=d, proc=d)
        self.assertEqual((st["cpufreq_driver"], st["pstate"], st["governor"]), ("intel_pstate", "active", "performance"))
        self.assertEqual(st["throttle_core"], [5, 9, 0])
        self.assertEqual(st["throttle_package"], [40, 40, 41])

    def test_a_clock_the_hardware_picks_is_recorded_and_not_judged(self):
        # intel_pstate active under the performance governor: the core of an idle host reads 800 MHz in one repeat
        # and 5200 in the next, and that is the hardware's choice, not a disturbance
        hw = {"cpufreq_driver": "intel_pstate", "pstate": "active", "governor": "performance",
              "freq_cores": [0, 1], "host_cores": [0], "jackd_cores": [1],
              "throttle_core": [3, 3], "throttle_package": [7, 7]}
        state = [{"before": dict(hw, freq_mhz=[800.0, 5200.0]), "after": dict(hw, freq_mhz=[800.0, 5200.0])},
                 {"before": dict(hw, freq_mhz=[5200.0, 5200.0]), "after": dict(hw, freq_mhz=[2200.0, 5200.0])}]
        self.assertEqual(soundness.check([cell_doc([crow(6.5, repeat_state=state)])]), {})

    def test_a_thermal_throttle_during_a_window_on_a_measured_core_is_flagged(self):
        hw = {"cpufreq_driver": "intel_pstate", "pstate": "active", "governor": "performance",
              "freq_mhz": [5200.0, 5200.0], "freq_cores": [0, 1], "host_cores": [0], "jackd_cores": [1]}
        state = [{"before": dict(hw, throttle_core=[3, 3], throttle_package=[7, 7]),
                  "after": dict(hw, throttle_core=[3, 4], throttle_package=[7, 7])}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=state)])])
        self.assertIn("state: thermal throttle (core 1, repeat 1)", bad[(0, 0)])
        pkg = [{"before": dict(hw, throttle_core=[3, 3], throttle_package=[7, 7]),
                "after": dict(hw, throttle_core=[3, 3], throttle_package=[8, 8])}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=pkg)])])
        self.assertIn("state: thermal throttle (package of core 0, repeat 1)", bad[(0, 0)])

    def test_a_thermal_throttle_on_a_core_nothing_measured_ran_on_is_not_a_disturbance(self):
        hw = {"cpufreq_driver": "intel_pstate", "pstate": "active", "governor": "performance",
              "freq_mhz": [5200.0, 5200.0, 800.0], "freq_cores": [0, 1, 2], "host_cores": [0], "jackd_cores": [1]}
        state = [{"before": dict(hw, throttle_core=[3, 3, 9], throttle_package=[7, 7, 7]),
                  "after": dict(hw, throttle_core=[3, 3, 12], throttle_package=[7, 7, 7])}]
        self.assertEqual(soundness.check([cell_doc([crow(6.5, repeat_state=state)])]), {})

    def test_a_shared_clock_that_moved_is_still_flagged_without_a_hardware_clock_driver(self):
        # a Pi: no cpufreq_driver the hardware runs, the cores share one clock
        state = [{"before": {"freq_mhz": [2400.0] * 4, "freq_cores": [0, 1, 2, 3], "host_cores": [2], "jackd_cores": [3]}},
                 {"before": {"freq_mhz": [1500.0] * 4, "freq_cores": [0, 1, 2, 3], "host_cores": [2], "jackd_cores": [3]}}]
        bad = soundness.check([cell_doc([crow(6.5, repeat_state=state)])])
        self.assertTrue(bad[(0, 0)][0].startswith("state: CPU frequency 1500..2400"), bad)

    def test_a_silent_output_is_flagged(self):
        row = crow(6.5, output={"rms_db": -200.0, "peak_db": -200.0})
        self.assertEqual(soundness.check([cell_doc([row])])[(0, 0)], ["output: silent"])

    def test_an_output_unlike_the_same_set_one_process_per_plugin_is_flagged(self):
        ind = crow(9.0, mode="individual", output={"rms_db": -12.0, "peak_db": -9.0})
        chain = crow(6.5, mode="chain", output={"rms_db": -17.5, "peak_db": -14.0})
        same = crow(6.5, mode="chain-add", output={"rms_db": -12.3, "peak_db": -9.3})
        bad = soundness.check([cell_doc([ind, chain, same])])
        self.assertEqual(list(bad), [(0, 1)])
        self.assertIn("output: -17.5 dB against -12.0 dB", bad[(0, 1)][0])

    def test_the_other_builds_of_h3_and_h4_are_not_held_to_the_h2_level(self):
        ind = crow(9.0, mode="individual", output={"rms_db": -12.0, "peak_db": -9.0})
        other = crow(6.5, host="H3", mode="shared-process", output={"rms_db": -20.0, "peak_db": -9.0})
        self.assertEqual(soundness.check([cell_doc([ind, other])]), {})

    def test_annotate_marks_every_row_and_names_the_reasons(self):
        doc = pi("p3-f256")
        n = soundness.annotate(doc, [pi("p2-f256"), pi("p3-f256-busy"), pi("p3-f128")])
        self.assertEqual(n, 3)
        gates = {s["mode"]: s["gate"] for s in doc["scenarios"]}
        self.assertEqual(gates["chain"]["verdict"], "unstable")
        self.assertTrue(gates["chain"]["reasons"])
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_annotate_marks_a_sound_row_pass(self):
        doc = cell_doc([crow(6.5)])
        self.assertEqual(soundness.annotate(doc), 0)
        self.assertEqual(doc["scenarios"][0]["gate"], {"verdict": "pass", "reasons": []})

    def test_a_thread_on_the_usb_interrupt_core_is_a_note_not_a_verdict(self):
        state = [{"after": {"usb_irq_core": 2, "host_cores": [2, 3]}}]
        doc = cell_doc([crow(6.5, repeat_state=state)])
        self.assertEqual(soundness.annotate(doc), 0)
        self.assertIn("core 2", doc["scenarios"][0]["gate"]["notes"][0])


class GateCommands(unittest.TestCase):
    def run_cmd(self, tool, *docs):
        with tempfile.TemporaryDirectory() as d:
            names = []
            for n, doc in enumerate(docs):
                names.append(os.path.join(d, "doc%d.json" % n))
                with open(names[-1], "w") as f:
                    json.dump(doc, f)
            r = subprocess.run([os.path.join(BENCH, tool)] + names, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
            return r.returncode, r.stdout

    def test_validate_refuses_the_disturbed_pi_cell_and_names_it(self):
        code, out = self.run_cmd("validate.sh", pi("p2-f256"), pi("p3-f256"))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"scenario cvp16 H2 48000/256 chain: rule:gate-disturbed-cell: .*twin: 7\.87 against its twin at 6\.55")

    def test_validate_accepts_the_same_cell_once_it_is_marked_unstable(self):
        docs = [pi("p2-f256"), pi("p3-f256")]
        for doc in docs:
            soundness.annotate(doc, [d for d in docs if d is not doc])
        code, out = self.run_cmd("validate.sh", *docs)
        self.assertEqual(code, 0, out)

    def test_validate_refuses_a_pass_mark_on_a_disturbed_cell(self):
        docs = [pi("p2-f256"), pi("p3-f256")]
        for doc in docs:
            for s in doc["scenarios"]:
                s["gate"] = {"verdict": "pass", "reasons": []}
        code, out = self.run_cmd("validate.sh", *docs)
        self.assertEqual(code, 1)
        self.assertIn("rule:gate-disturbed-cell", out)

    def test_validate_wants_a_reason_with_an_unstable_mark(self):
        doc = cell_doc([crow(6.5, gate={"verdict": "unstable", "reasons": []})])
        code, out = validate(doc)
        self.assertEqual(code, 1)
        self.assertIn("rule:gate-unstable-names-why", out)

    def test_gate_sh_exits_1_on_the_pi_cells_and_prints_the_rerun(self):
        code, out = self.run_cmd("gate.sh", pi("p2-f256"), pi("p3-f256"))
        self.assertEqual(code, 1)
        self.assertIn("UNSTABLE cvp16 H2 chain 48000/256 dsp 7.87", out)
        self.assertIn("bench/run.sh --out DIR --class rpi5 --rates 48000 --frames 256 --scenarios cvp16 --hosts H2 "
                      "--stress none --alsa hw:Pro73107815 --periods 3", out)

    def test_gate_sh_exits_0_on_cells_that_agree(self):
        code, out = self.run_cmd("gate.sh", cell_doc([crow(6.5), crow(6.6, mode="chain-add")]))
        self.assertEqual(code, 0, out)


class Interleave(unittest.TestCase):
    def fake(self, repeats):
        order = []
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=repeats), jack_dirty=False, cell_rate=48000,
                                     cell_frames=256)
        fake.row = lambda s, h, mode, rate, frames, stress: order.append(h) or run_row(host=h)
        return fake, order

    def test_the_hosts_take_turns_across_the_repeats(self):
        fake, order = self.fake(3)
        group = [({"id": "x"}, h, "m", False) for h in ("H1", "H2", "H3")]
        rows = bench.Runner.measure_group(fake, group)
        self.assertEqual(order, ["H1", "H2", "H3"] * 3)
        self.assertEqual([r["host"] for r in rows], ["H1", "H2", "H3"])
        self.assertTrue(all(r["repeats"] == 3 for r in rows))

    def test_a_row_that_broke_leaves_the_turns_and_the_others_go_on(self):
        order = []
        fake = types.SimpleNamespace(args=types.SimpleNamespace(repeats=2), jack_dirty=False, cell_rate=48000,
                                     cell_frames=256)
        fake.row = lambda s, h, mode, rate, frames, stress: order.append(h) or (
            run_row(host=h, status="failed", note="broke") if h == "H2" else run_row(host=h))
        rows = bench.Runner.measure_group(fake, [({"id": "x"}, h, "m", False) for h in ("H1", "H2", "H3")])
        self.assertEqual(order, ["H1", "H2", "H3", "H1", "H3"])
        self.assertEqual([r["status"] for r in rows], ["ok", "failed", "ok"])


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class MachineState(unittest.TestCase):
    def tree(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        for n, f in enumerate((2400000, 1500000)):
            p = os.path.join(d, "sys/devices/system/cpu/cpu%d/cpufreq" % n)
            os.makedirs(p)
            put(os.path.join(p, "scaling_cur_freq"), "%d\n" % f)
        os.makedirs(os.path.join(d, "sys/class/thermal/thermal_zone0"))
        put(os.path.join(d, "sys/class/thermal/thermal_zone0/temp"), "61250\n")
        os.makedirs(os.path.join(d, "proc/77/task/77"))
        os.makedirs(os.path.join(d, "proc/77/task/78"))
        for tid, core in ((77, 3), (78, 2)):
            fields = ["S"] + ["0"] * 35 + [str(core)] + ["0"] * 10
            put(os.path.join(d, "proc/77/task/%d/stat" % tid), "%d (omx host) %s\n" % (tid, " ".join(fields)))
        put(os.path.join(d, "proc/interrupts"),
            "           CPU0       CPU1       CPU2       CPU3\n"
            " 30:         10          0       9000          5     GICv3  xhci-hcd:usb1\n"
            " 31:       7000          1          0          0     GICv3  eth0\n")
        return d

    def test_the_state_reads_frequency_temperature_cores_and_the_usb_interrupt(self):
        d = self.tree()
        st = bench.machine_state([77], None, d + "/sys", d + "/proc")
        self.assertEqual(st["freq_mhz"], [2400.0, 1500.0])
        self.assertEqual(st["temp_c"], 61.2)
        self.assertEqual(st["host_cores"], [2, 3])
        self.assertEqual(st["usb_irq_core"], 2)

    def test_a_machine_with_none_of_it_still_answers(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        st = bench.machine_state([], None, d, d)
        self.assertEqual((st["freq_mhz"], st["temp_c"], st["host_cores"], st["usb_irq_core"]), ([], None, [], None))

    def test_the_repeats_keep_their_states_and_cycles(self):
        runs = [run_row(state={"before": {"freq_mhz": [2400.0]}}, cycles=1870),
                run_row(state={"before": {"freq_mhz": [2400.0]}}, cycles=1875),
                run_row(state={"before": {"freq_mhz": [2400.0]}}, cycles=1880)]
        row = bench.aggregate(runs, 3)
        self.assertEqual(len(row["repeat_state"]), 3)
        self.assertEqual(row["cycles"], 1875)
        self.assertNotIn("state", row)
        doc = example()
        doc["scenarios"] = [row]
        code, out = validate(doc)
        self.assertEqual(code, 0, out)

    def test_a_wav_is_read_as_its_level(self):
        import math
        import struct
        import wave
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        for name, amp in (("sine", 16384), ("silent", 0)):
            with wave.open(os.path.join(d, name + ".wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 1000 * i / 48000)))
                                       for i in range(48000)))
        sine = bench.wav_level(os.path.join(d, "sine.wav"))
        self.assertAlmostEqual(sine["peak_db"], -6.0, delta=0.1)
        self.assertAlmostEqual(sine["rms_db"], -9.0, delta=0.1)
        self.assertEqual(bench.wav_level(os.path.join(d, "silent.wav"))["rms_db"], -200.0)


class SettleGate(unittest.TestCase):
    def fake(self, again):
        fake = types.SimpleNamespace(jack_dirty=False, cell_rate=0, cell_frames=0)
        fake.jack_stop = lambda: None
        fake.calls = []
        fake.rerun_alone = lambda plan, first, reasons=None: fake.calls.append(first["mode"]) or again(first)
        return fake

    def doc(self):
        return cell_doc([crow(7.9, mode="chain"), crow(6.7, mode="chain", stress="busy4+mem256")], 3)

    def rows(self):
        s = {"id": "cvp8", "title": "t"}
        return [(s, "H2", "chain", False), (s, "H2", "chain", True)]

    def test_a_cell_that_breaks_a_check_is_rerun_and_marked_pass_when_the_rerun_agrees(self):
        doc = self.doc()
        again = lambda first: dict(first, dsp_load_avg=6.6, gate={"rerun": True, "first_dsp_load_avg": first["dsp_load_avg"]})
        fake = self.fake(again)
        bench.Runner.settle_gate(fake, doc, self.rows())
        self.assertEqual(fake.calls, ["chain"])
        gate = doc["scenarios"][0]["gate"]
        self.assertEqual((gate["verdict"], gate["rerun"], gate["first_dsp_load_avg"]), ("pass", True, 7.9))

    def test_a_cell_that_still_breaks_after_the_rerun_is_published_as_unstable(self):
        doc = self.doc()
        fake = self.fake(lambda first: dict(first, gate={"rerun": True, "first_dsp_load_avg": first["dsp_load_avg"]}))
        bench.Runner.settle_gate(fake, doc, self.rows())
        gate = doc["scenarios"][0]["gate"]
        self.assertEqual(gate["verdict"], "unstable")
        self.assertTrue(gate["reasons"][0].startswith("stress:"))
        self.assertEqual(doc["scenarios"][1]["gate"]["verdict"], "pass")

    def test_a_cell_already_rerun_alone_is_not_rerun_again(self):
        doc = self.doc()
        doc["scenarios"][0]["gate"] = {"verdict": "pass", "reasons": [], "rerun": True, "first_dsp_load_avg": 9.0}
        fake = self.fake(lambda first: self.fail("one rerun is all a cell gets"))
        bench.Runner.settle_gate(fake, doc, self.rows())
        gate = doc["scenarios"][0]["gate"]
        self.assertEqual((gate["verdict"], gate["rerun"], gate["first_dsp_load_avg"]), ("unstable", True, 9.0))

    def test_a_document_in_which_every_cell_agrees_reruns_nothing(self):
        doc = cell_doc([crow(6.5)], 3)
        fake = self.fake(lambda first: self.fail("nothing to rerun"))
        bench.Runner.settle_gate(fake, doc, [({"id": "cvp8", "title": "t"}, "H2", "chain", False)])
        self.assertEqual(doc["scenarios"][0]["gate"]["verdict"], "pass")


class TableSoundness(unittest.TestCase):
    def test_an_unstable_cell_is_shown_as_such_and_makes_no_ratio(self):
        docs = [pi("p2-f256"), pi("p3-f256")]
        text = table.render(docs[1], [docs[0]])
        self.assertIn("7.87 [7.47-8.16] / 8.36 [8.35-8.52] UNSTABLE", text)
        self.assertNotIn("| cvp16 | 48000/256 | 16 | 17 vs 2", text)

    def test_a_cell_that_agrees_keeps_its_ratio(self):
        doc = family_doc()
        self.assertEqual(len(table.ratios(doc, table.unstable_rows([doc]))), 3)

    def test_the_table_carries_the_switches_of_a_cycle(self):
        lines = table.table(family_doc())
        self.assertIn("ctx/cycle", lines[0])
        row = [x for x in lines if "| chain | 2 | 118.0" in x][0]
        self.assertIn("| ~1.5 |", row)  # 2800 switches over the 1875 cycles of a 10 s window at 48000/256

    def test_a_document_that_says_its_cycles_is_not_estimated(self):
        r = run_row(cycles=1000, ctx_switches=16000)
        self.assertEqual(table.cycle_figure(r, "ctx_switches"), "16.0")

    def test_the_format_pairs_put_clap_beside_lv2_on_one_host(self):
        doc = cell_doc([crow(7.0, id="cvc16", plugins=["a"] * 16), crow(7.7, id="cvl16", plugins=["a"] * 16),
                        crow(9.0, id="cvc16", host="H1", mode="shared-process", plugins=["a"] * 16),
                        crow(5.0, id="cvl16", host="H3", mode="shared-process", plugins=["a"] * 16)], 3)
        lines = table.format_pairs([doc])
        self.assertEqual(len(lines), 3)
        self.assertIn("| 16 | H2 | chain | 48000/256 | 3 | none | 7.00 | 7.70 | 1.10x |", lines[2])

    def test_the_rate_ratio_is_made_from_cells_that_passed(self):
        lo = cell_doc([crow(6.5), crow(7.9, mode="chain-add")], 3)
        hi = cell_doc([crow(13.0, rate=96000), crow(15.8, mode="chain-add", rate=96000)], 3)
        bad = table.unstable_rows([lo, hi])
        for r in lo["scenarios"] + hi["scenarios"]:
            r["id"] = "cvp16"
        lo["scenarios"][1]["gate"] = {"verdict": "unstable", "reasons": ["twin: x"]}
        lines = table.rate_ratios([lo, hi], table.unstable_rows([lo, hi]))
        self.assertEqual(len(lines), 3)
        self.assertIn("2.00x", lines[2])


class FormatScenarios(unittest.TestCase):
    def test_every_clap_chain_scenario_has_its_lv2_twin_on_h1_and_h2(self):
        with open(os.path.join(BENCH, "scenarios.json")) as f:
            tbl = json.load(f)
        ids = {s["id"]: s for s in tbl["scenarios"]}
        for sid, sc in ids.items():
            if not re.match(r"^cvc[0-9]+$", sid):
                continue
            twin = ids.get("cvl" + sid[3:])
            self.assertIsNotNone(twin, "%s has no cvl%s" % (sid, sid[3:]))
            self.assertEqual(twin["count"], sc["count"])
            self.assertEqual(twin["plugins"], sc["plugins"])
            self.assertEqual(twin["format"], "lv2")
            self.assertEqual(twin["family"], sc["family"])
        hosts = {(m["host"], m["mode"]) for m in tbl["modes"]["chains-vs-processes"]}
        self.assertTrue({("H1", "shared-process"), ("H2", "chain"), ("H2", "individual")} <= hosts)


if __name__ == "__main__":
    unittest.main()

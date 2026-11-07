"""The xrun probe against a real private JACK server: run with `python3 -I bench/tests/test_probe_jack.py`, where jackd2
is the JACK library. A server killed or stopped in the middle fails the row within the probe's timeout, and the runner
gets past it. Never run it where libjack is PipeWire's: the probe would join the session's graph."""

import importlib.util
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("bench", os.path.join(BENCH, "lib", "bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
LIMIT_S = 5


def libjack_is_pipewires():
    r = subprocess.run("ldconfig -p | grep libjack.so.0", shell=True, stdout=subprocess.PIPE, text=True)
    paths = [line.split("=>")[-1].strip() for line in r.stdout.splitlines()]
    return not paths or any("pipewire" in os.path.realpath(p) for p in paths)


@unittest.skipIf(not shutil.which("jackd") or libjack_is_pipewires(), "needs jackd2's JACK, not PipeWire's")
class RealServer(unittest.TestCase):
    def setUp(self):
        keep = bench.PROBE_TIMEOUT_S
        bench.PROBE_TIMEOUT_S = LIMIT_S
        self.addCleanup(setattr, bench, "PROBE_TIMEOUT_S", keep)
        self.logs = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.logs, ignore_errors=True))
        self.server = "probetest%d" % os.getpid()
        self.procs = bench.Procs(self.logs, self.server)
        self.addCleanup(self.procs.stop_all)
        self.jackd = self.procs.spawn(["jackd", "-r", "-n", self.server, "-d", "dummy", "-r", "48000", "-p", "256"], "jackd")
        end = time.monotonic() + 20
        while True:
            try:
                self.probe = bench.ProbeProcess(self.server, self.procs)
                break
            except bench.JackUnanswered:
                self.assertLess(time.monotonic(), end, "the private server did not start")
                time.sleep(0.2)
        self.assertGreaterEqual(self.probe.cpu_load(), 0.0)

    def test_a_server_killed_in_the_middle_fails_the_row_within_the_timeout(self):
        self.jackd.send_signal(signal.SIGKILL)
        t0 = time.monotonic()
        with self.assertRaises(bench.JackUnanswered):
            end = t0 + LIMIT_S
            while time.monotonic() < end:  # the news reaches the client a moment after the kill
                self.probe.cpu_load()
                time.sleep(0.1)
            self.probe.latency_frames("system:playback_1")
            self.probe.cpu_load()
        self.assertLess(time.monotonic() - t0, 2 * LIMIT_S + 2)

    def test_a_server_that_stops_answering_fails_the_row_and_close_returns(self):
        self.jackd.send_signal(signal.SIGSTOP)
        self.addCleanup(self.jackd.send_signal, signal.SIGCONT)
        t0 = time.monotonic()
        with self.assertRaises(bench.JackUnanswered) as e:
            self.probe.latency_frames("system:playback_1")
        self.assertLess(time.monotonic() - t0, LIMIT_S + 2)
        self.assertIn("timed out", str(e.exception))
        self.probe.close()
        self.assertLess(time.monotonic() - t0, LIMIT_S + 4)

    def test_close_returns_from_a_stopped_server(self):
        self.jackd.send_signal(signal.SIGSTOP)
        self.addCleanup(self.jackd.send_signal, signal.SIGCONT)
        t0 = time.monotonic()
        self.probe.close()
        self.assertLess(time.monotonic() - t0, LIMIT_S + 4)


if __name__ == "__main__":
    unittest.main()

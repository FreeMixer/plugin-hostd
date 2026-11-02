#!/usr/bin/env python3
"""perf record on a bench row's host while the row runs: the same chain, JACK server, source and wiring as bench/run.sh.

    profile-chain.py --bench DIR --out DIR [--seconds 30] [--rate 48000] [--frames 256]
        [--rows cvp24:H2:chain-add:fp,cvp24:H3::fp,...]

Each row is scenario:host:mode:callgraph, callgraph fp (perf record -g) or dwarf (--call-graph dwarf). The row runs once,
as in bench.py, except that its measuring window also runs perf record for the same seconds on the host's processes:
plugin-hostd's worker(s) for H2 (the daemon only answers its port), the mod-host process for H3. The perf file is
<out>/<scenario>-<host>-<mode>-<callgraph>.data; the row's DSP load, xruns and memory, taken under perf, go to the
omx-bench/1 document bench.py writes in <out>."""
import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--bench", required=True, help="plugin-hostd's bench directory")
ap.add_argument("--out", required=True)
ap.add_argument("--seconds", type=int, default=30)
ap.add_argument("--rate", type=int, default=48000)
ap.add_argument("--frames", type=int, default=256)
ap.add_argument("--freq", type=int, default=999, help="samples a second for fp; dwarf rows take a quarter")
ap.add_argument("--rows", default="cvp24:H2:chain-add:fp,cvp24:H3::fp")
ap.add_argument("--conf", action="append", default=[], help="a line added to plugin-hostd's conf on H2 rows")
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.bench, "lib"))
import bench  # noqa: E402

ROWS = []
for spec in a.rows.split(","):
    sid, h, mode, cg = spec.split(":")
    ROWS.append((sid, h, mode or None, cg))

last = {}
_pids = bench.Host.pids


def pids(self):
    out = _pids(self)
    last["key"], last["roots"], last["pids"] = self.key, self.roots(), out
    return out


bench.Host.pids = pids

# --conf LINE (repeatable): lines added to plugin-hostd's conf of every H2 row, e.g. clap_host <path>
_init = bench.Host.__init__


def init(self, key, procs, env, workdir, port, conf=("require_pins 0",)):
    if key == "H2" and a.conf:
        conf = tuple(conf) + tuple(a.conf)
    _init(self, key, procs, env, workdir, port, conf)


bench.Host.__init__ = init


class Profiler(bench.Runner):
    def plan(self):
        by_id = {s["id"]: s for s in self.table["scenarios"]}
        return [(by_id[sid], h, mode, False) for sid, h, mode, _ in ROWS]

    def measure(self, s, hkey, mode, rate, frames, stress):
        self.current = next(r for r in ROWS if r[0] == s["id"] and r[1] == hkey and r[2] == mode)
        ROWS.remove(self.current)
        return super().measure(s, hkey, mode, rate, frames, stress)

    def dsp_window(self, seconds):
        sid, h, mode, cg = self.current
        targets = last["pids"]
        if last["key"] == "H2":
            targets = [p for p in targets if p not in last["roots"]] or targets
        comms = []
        for p in targets:
            try:
                libs = sorted({l.split()[-1] for l in open("/proc/%d/maps" % p) if "libomx-clap-core" in l})
                comms.append("%d %s (%s) [%s]" % (p, open("/proc/%d/comm" % p).read().strip(), os.readlink("/proc/%d/exe" % p),
                                                  " ".join(libs) or "no libomx-clap-core"))
            except OSError:
                pass
        data = os.path.join(a.out, "%s-%s-%s-%s.data" % (sid, h, mode or "shared-process", cg))
        if cg == "fp":
            how = ["-g", "-F", str(a.freq)]
        else:
            how = ["--call-graph", "dwarf,8192", "-F", str(max(a.freq // 4, 100))]
        argv = ["perf", "record"] + how + ["-p", ",".join(map(str, targets)), "-o", data, "--", "sleep", str(seconds)]
        bench.log("profile %s %s %s %s: perf on %s" % (sid, h, mode or "-", cg, ", ".join(comms)))
        with open(data + ".txt", "w") as f:
            f.write("row %s %s %s, call graph %s, %d Hz / %d frames, %d s\nprocesses: %s\nargv: %s\n" % (
                sid, h, mode or "shared-process", cg, self.args.rates[0], self.args.frames[0], seconds,
                "; ".join(comms), " ".join(argv)))
        perf = subprocess.Popen(argv, stdout=open(data + ".log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
        try:
            loads = super().dsp_window(seconds)
            perf.wait(seconds + 60)
        finally:
            if perf.poll() is None:
                os.killpg(perf.pid, signal.SIGINT)
                perf.wait(30)
        return loads


def main():
    os.makedirs(a.out, exist_ok=True)
    args = argparse.Namespace(cls="rpi5", out=a.out, rates=[a.rate], frames=[a.frames],
                              scenarios=None, hosts=list(bench.HOSTS), stress="none", repeats=1, window=a.seconds,
                              pianoteq_dir=None, qualify=False, keep_governor=False, logs=os.path.join(a.out, "logs"))
    import json
    table = json.load(open(os.path.join(a.bench, "scenarios.json")))
    try:
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)
    except (OSError, AttributeError):
        pass
    runner = Profiler(args, table)

    def on_signal(sig, _frame):
        raise SystemExit("profile: stopped by signal %d" % sig)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    code = 0
    try:
        print(runner.run())
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code, file=sys.stderr)
            code = 1
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if not runner.teardown():
            code = 3
    return code


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""One placement run: a plugin-hostd of its own on a free port, N instruments in separate workers (each a chain of its
own), a held chord on each, then per-core CPU from /proc/stat once a second and the xruns of the JACK server over the
window, counted by a JACK client of this script's own (the JACK-Client module; without it the xruns are not measured). Writes <out>/cores.tsv (one line per second and core, busy percent), <out>/summary.json, <out>/workers.txt
(worker_list and each worker's affinity) and <out>/events.txt (the feedback port).

    measure.py --daemon ./plugin-hostd --placement spread --uri clap:<path>#<id> [--uri ...] --count 3 --out DIR

The daemon uses the running JACK server; nothing of the system's is changed, and everything it started is stopped."""
import argparse, json, os, shutil, socket, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tests", "lib"))
from plugin_hostd_client import Client


def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                w = line.split()
                v = [int(x) for x in w[1:]]
                idle = v[3] + v[4]
                out[int(w[0][3:])] = (sum(v[:8]), idle)
    return out


class Xruns:
    """the xruns the JACK server reports to a client of ours, from start() on; None when the module is not there"""

    def __init__(self):
        self.count = None
        try:
            import jack
        except ImportError:
            self.client = None
            return
        self.client = jack.Client("placement-xruns", no_start_server=True)
        self.client.set_xrun_callback(self._xrun)
        self.client.activate()

    def _xrun(self, delay):
        if self.count is not None:
            self.count += 1

    def start(self):
        if self.client:
            self.count = 0

    def stop(self):
        n = self.count
        if self.client:
            self.client.deactivate()
            self.client.close()
        return n


def allowed(pid):
    with open("/proc/%d/status" % pid) as f:
        return [l.split()[1] for l in f if l.startswith("Cpus_allowed_list")][0]


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--daemon", required=True)
    a.add_argument("--placement", choices=("spread", "none"), required=True)
    a.add_argument("--uri", action="append", required=True, help="an instrument; repeated round the count")
    a.add_argument("--count", type=int, required=True)
    a.add_argument("--window", type=int, default=60)
    a.add_argument("--port", type=int, default=15555)
    a.add_argument("--clap-host", default="omx-clap-host")
    a.add_argument("--lv2-path", default=os.environ.get("LV2_PATH", "/usr/lib/lv2:/usr/local/lib/lv2"))
    a.add_argument("--out", required=True)
    o = a.parse_args()
    os.makedirs(o.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="placement-run.")
    conf = os.path.join(tmp, "plugin-hostd.conf")
    with open(conf, "w") as f:
        for k, v in (("placement", o.placement), ("require_pins", 0), ("clap_host", o.clap_host), ("state_root", tmp),
                     ("history_window_s", 0), ("descriptor_dir", tmp + "/d"), ("qualification_dir", tmp + "/q"),
                     ("probe", tmp + "/no-probe"), ("pins_dir", ""), ("lv2_path", o.lv2_path)):
            f.write("%s %s\n" % (k, v))
    log = open(os.path.join(o.out, "daemon.log"), "w")
    d = subprocess.Popen([o.daemon, "-n", "-p", str(o.port), "-f", str(o.port + 1), "-c", conf], stdout=log, stderr=log)
    events = []
    try:
        time.sleep(1.0)
        c = Client.connect(o.port, timeout=30)
        fb = socket.create_connection(("127.0.0.1", o.port + 1))

        def read():
            buf = b""
            while True:
                try:
                    chunk = fb.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\0" in buf:
                    line, buf = buf.split(b"\0", 1)
                    events.append((time.monotonic(), line.decode(errors="replace")))
        threading.Thread(target=read, daemon=True).start()
        for n in range(o.count):
            r = c.send("add %s %d" % (o.uri[n % len(o.uri)], n), timeout=60)
            if r != "resp %d" % n:
                raise SystemExit("add %d answered %r" % (n, r))
        workers = c.send("worker_list")
        time.sleep(3.0)
        # a held chord of four notes on each instrument
        for n in range(o.count):
            for note in (48, 55, 60, 64):
                c.send("note_on %d 0 %d 100" % (n, note))
        time.sleep(2.0)
        start_events = len(events)
        xruns = Xruns()
        xruns.start()
        t0 = cpu_times()
        prev = t0
        rows = []
        for s in range(o.window):
            time.sleep(1.0)
            now = cpu_times()
            for core in sorted(now):
                tot = now[core][0] - prev[core][0]
                idle = now[core][1] - prev[core][1]
                rows.append((s + 1, core, 100.0 * (tot - idle) / tot if tot else 0.0))
            prev = now
        end = cpu_times()
        jack_xruns = xruns.stop()
        window_events = [e for _, e in events[start_events:]]
        with open(os.path.join(o.out, "cores.tsv"), "w") as f:
            f.write("second\tcore\tbusy_percent\n")
            for r in rows:
                f.write("%d\t%d\t%.1f\n" % r)
        with open(os.path.join(o.out, "workers.txt"), "w") as f:
            f.write(workers + "\n")
            for rec in workers.split()[2:]:
                pid = int(rec.split(":")[1])
                f.write("pid %d allowed %s daemon %s\n" % (pid, allowed(pid), allowed(d.pid)))
            f.write(subprocess.run(["ps", "-L", "-o", "pid,tid,psr,pcpu,comm", "--ppid", str(d.pid)],
                                   capture_output=True, text=True).stdout)
        with open(os.path.join(o.out, "events.txt"), "w") as f:
            for t, e in events:
                f.write("%.3f %s\n" % (t, e))
        xr = {}
        for e in window_events:
            if e.startswith("xruns "):
                w = e.split()
                xr[w[1] if len(w) > 2 else "-"] = w[-1]
        busy = {}
        for core in sorted(end):
            tot = end[core][0] - t0[core][0]
            busy[core] = round(100.0 * (tot - (end[core][1] - t0[core][1])) / tot, 1) if tot else 0.0
        summary = {"placement": o.placement, "instruments": o.count, "uris": o.uri, "window_s": o.window,
                   "busy_percent_by_core": busy, "busy_percent_max_core": max(busy.values()),
                   "jack_xruns_in_window": jack_xruns, "worker_xrun_events_in_window": [e for e in window_events if "xrun" in e],
                   "xruns_last_count": xr,
                   "worker_list": workers}
        with open(os.path.join(o.out, "summary.json"), "w") as f:
            json.dump(summary, f, indent=1)
        print(json.dumps({k: summary[k] for k in ("placement", "instruments", "busy_percent_by_core", "jack_xruns_in_window")}))
        for n in range(o.count):
            c.send("all_notes_off %d" % n)
        c.send("remove -1")
    finally:
        d.terminate()
        try:
            d.wait(10)
        except subprocess.TimeoutExpired:
            d.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

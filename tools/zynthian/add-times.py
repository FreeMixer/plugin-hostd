#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""Add times of chains of 2, 4 and 7 plugins, cold and warm, on a private dummy JACK server.

    add-times.py --out FILE [--sizes 2,4,7] [--repeats 3] [--rate 48000] [--frames 256] [--port 5810]
        [--hosts mod-host,omx-clap-host,plugin-hostd:grouped,plugin-hostd:own]

The plugins are omx comp, delay and drive in turn, their LV2 builds on every host, so that every host runs the same
code: mod-host takes the LV2 URI, omx-clap-host and plugin-hostd take lv2:<uri> through the LV2 adapter. With
--builds clap they are the CLAP builds, which mod-host cannot run.

  cold   the host started fresh, then every plugin added: from the host's start to the last reply
  warm   the same host, every plugin removed, then added again: from the first add to the last reply

plugin-hostd runs two ways: grouped, each plugin added into one chain (add <uri> <n> chain:1), the time running until
chain_get shows every member running in it; and one worker each (add <uri> <n> own). Its settings are require_pins 0
and a state directory of the run's own. One JSON row per host, mode, size and phase: the median of the repeats, the
lowest and the highest, and the workers and JACK clients the last repeat left.
"""
import argparse
import json
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time

LV2 = ["urn:openmixer:comp", "urn:openmixer:delay", "urn:openmixer:drive"]
CLAP = ["clap:/usr/lib/clap/omx-%s.clap#org.openmixer.%s" % (k, k) for k in ("comp", "delay", "drive")]
HOSTS = [("mod-host", None), ("omx-clap-host", None), ("plugin-hostd", "grouped"), ("plugin-hostd", "own")]


def connect(port, limit=60):
    end = time.monotonic() + limit
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port))
            s.settimeout(120)
            return s
        except OSError:
            if time.monotonic() > end:
                raise
            time.sleep(0.002)


def call(s, line):
    s.sendall(line.encode() + b"\0")
    buf = b""
    while b"\0" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            raise RuntimeError("the host closed the connection on " + line)
        buf += chunk
    return buf.split(b"\0")[0].decode(errors="replace")


def clients(env):
    out = subprocess.run(["jack_lsp"], env=env, capture_output=True, text=True).stdout.split()
    return {p.split(":")[0] for p in out} - {"system"}


class host:
    def __init__(self, name, mode, port, work, env, builds="lv2"):
        self.name, self.mode, self.env, self.builds = name, mode, env, builds
        if name == "plugin-hostd":
            conf = os.path.join(work, "plugin-hostd.conf")
            with open(conf, "w") as f:
                f.write("require_pins 0\nstate_root %s/state\n" % work)
            argv = ["plugin-hostd", "-n", "-p", str(port), "-f", str(port + 1), "-c", conf]
        else:
            argv = [name, "-n", "-p", str(port)]
        self.log = open(os.path.join(work, "%s.log" % name), "a")
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(argv, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.feedback = []
        if name == "plugin-hostd":
            # plugin-hostd answers its command port once a client holds the feedback port: connected first, and read
            # all along, so that a full socket never holds the daemon up; the lines are kept for the row
            fb = connect(port + 1)
            threading.Thread(target=self.drain, args=(fb,), daemon=True).start()
        self.ctl = connect(port)
        self.answering_ms = (time.monotonic() - self.t0) * 1000
        self.base = clients(env)

    def drain(self, fb):
        buf = b""
        while True:
            try:
                chunk = fb.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\0" in buf:
                line, buf = buf.split(b"\0", 1)
                self.feedback.append(line.decode(errors="replace"))

    def uri(self, u):
        return u if self.name == "mod-host" or self.builds == "clap" else "lv2:" + u

    def add_all(self, n):
        """add n plugins; for grouped, until the chain runs all of them. The time from the first add."""
        t = time.monotonic()
        for i in range(n):
            place = {"grouped": " chain:1", "own": " own"}.get(self.mode, "")
            r = call(self.ctl, "add %s %d%s" % (self.uri((CLAP if self.builds == "clap" else LV2)[i % 3]), i, place))
            if not r.startswith("resp %d" % i):
                raise RuntimeError("add %d answered %s" % (i, r))
        if self.mode == "grouped":
            want = ",".join(map(str, range(n)))
            end = time.monotonic() + 30
            while True:
                f = call(self.ctl, "chain_get 1").split()
                if len(f) >= 5 and f[2] != "-" and f[4] == want:
                    break
                if time.monotonic() > end:
                    raise RuntimeError("the chain did not run every member: %s" % " ".join(f))
                time.sleep(0.002)
        return (time.monotonic() - t) * 1000

    def remove_all(self, n):
        """remove every plugin and wait until the graph holds the host's own clients only"""
        for i in reversed(range(n)):
            call(self.ctl, "remove %d" % i)
        end = time.monotonic() + 30
        while clients(self.env) != self.base:
            if time.monotonic() > end:
                raise RuntimeError("clients left after remove: %s" % sorted(clients(self.env) - self.base))
            time.sleep(0.05)

    def workers(self):
        if self.name != "plugin-hostd":
            return 1
        f = call(self.ctl, "worker_list").split()
        return int(f[1]) if len(f) > 1 and f[1].isdigit() else None

    def stop(self):
        for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
            try:
                os.killpg(self.proc.pid, sig)
                self.proc.wait(wait)
                return
            except ProcessLookupError:
                return
            except subprocess.TimeoutExpired:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="2,4,7")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--frames", type=int, default=256)
    ap.add_argument("--port", type=int, default=5810)
    ap.add_argument("--builds", choices=("lv2", "clap"), default="lv2", help="clap: the omx plugins' CLAP builds; mod-host is left out")
    ap.add_argument("--hosts", default="mod-host,omx-clap-host,plugin-hostd:grouped,plugin-hostd:own",
                    help="the rows to run, host or host:mode")
    a = ap.parse_args()
    work = tempfile.mkdtemp(prefix="add-times-")
    server = "addt%d" % os.getpid()
    env = dict(os.environ, JACK_DEFAULT_SERVER=server)
    jackd = subprocess.Popen(["jackd", "-n", server, "-d", "dummy", "-r", str(a.rate), "-p", str(a.frames)], env=env,
                             stdout=open(os.path.join(work, "jackd.log"), "w"), stderr=subprocess.STDOUT, start_new_session=True)
    rows = []
    try:
        end = time.monotonic() + 10
        while subprocess.run(["jack_lsp"], env=env, capture_output=True).returncode != 0:
            if time.monotonic() > end:
                raise SystemExit("the private JACK server did not start")
            time.sleep(0.1)
        for n in [int(x) for x in a.sizes.split(",")]:
            for name, mode in HOSTS:
                if (name if mode is None else "%s:%s" % (name, mode)) not in a.hosts.split(","):
                    continue
                if a.builds == "clap" and name == "mod-host":
                    continue
                print("add-times: %d %s %s" % (n, name, mode or "one process"), flush=True)
                cold, warm, answering, last = [], [], [], {}
                for rep in range(a.repeats):
                    h = None
                    try:
                        h = host(name, mode, a.port, work, env, a.builds)
                        answering.append(h.answering_ms)
                        add = h.add_all(n)
                        cold.append(h.answering_ms + add)
                        h.remove_all(n)
                        warm.append(h.add_all(n))
                        last = {"workers": h.workers(), "jack_clients": len(clients(env)),
                                "abi_clobber": sorted({x for x in h.feedback if x.startswith("abi_clobber")})}
                    finally:
                        if h:
                            h.stop()
                    time.sleep(0.5)
                for phase, vals in (("cold", cold), ("warm", warm)):
                    row = {"plugins": n, "builds": a.builds, "host": name, "mode": mode or "one process", "phase": phase,
                           "ms": round(statistics.median(vals), 1), "min": round(min(vals), 1), "max": round(max(vals), 1),
                           "repeats": len(vals), "start_to_answering_ms": round(statistics.median(answering), 1)}
                    row.update(last)
                    rows.append(row)
                    print("add-times: %d %s %s %s: %.1f ms [%.1f, %.1f]" % (n, name, row["mode"], phase, row["ms"], row["min"], row["max"]),
                          flush=True)
    finally:
        os.killpg(jackd.pid, signal.SIGTERM)
        jackd.wait(15)
        shutil.rmtree(work, ignore_errors=True)
    with open(a.out, "w") as f:
        json.dump({"rate": a.rate, "frames": a.frames, "plugins": CLAP if a.builds == "clap" else LV2, "rows": rows}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

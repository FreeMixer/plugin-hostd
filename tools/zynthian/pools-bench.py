#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""The same light plugins under plugin-hostd, placed three ways: a worker each, a few pools, one pool.

    pools-bench.py --out DIR [--window 30] [--repeats 3] [--pin-file FILE] [--rate 48000] [--frames 256]

On a private JACK server on the dummy driver, each plugin is a single-plugin chain of its own: a sine into it and its
output into the server's playback. Each row reads over the window: the host's CPU, DSP load, PSS, voluntary and involuntary
context switches of all the host's threads and of the server's, xruns, the load of each core, JACK clients and worker_list.
Modes: own (a worker each), pools3 (three pools), pool1 (one pool, pool_config as large as the plugins), pool1-default (one
pool at the default cap, to see what the daemon does past it), mixed (two small pools and a heavy instrument on a worker of
its own holding notes). Every row is built from nothing.
"""
import argparse
import importlib.util
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("voices_cores", os.path.join(HERE, "voices-cores.py"))
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)
LIGHT = ["comp", "delay", "drive", "eq8", "chorus", "tremolo", "limiter", "phaser"]
COLUMNS = ["mode", "plugins", "repeat", "status", "xruns", "dsp_avg", "dsp_max", "cpu_pct", "pss_mb", "processes", "jack_clients",
           "ctx_vol_s", "ctx_invol_s", "ctx_jackd_s", "core0", "core1", "core2", "core3", "busiest_core", "add_s", "peak_db", "workers", "note"]


def placements(mode, n):
    if mode == "own":
        return ["own"] * n
    if mode == "pools3":
        return ["pool:p%d" % (i % 3) for i in range(n)]
    if mode in ("pool1", "pool1-default"):
        return ["pool:big"] * n
    return ["pool:p%d" % (i % 2) for i in range(n)]


def one_row(a, mode, rep):
    row = {"mode": mode, "plugins": a.plugins, "repeat": rep, "status": "failed"}
    srv = vc.server(a, a.out)
    host, sine, probe, load = None, None, None, None
    try:
        host = vc.protocol_host(a, srv, a.out, a.port)
        if mode == "pool1":
            r = host.cmd("pool_config big %d" % a.plugins)
            if r != "resp 0":
                raise RuntimeError("pool_config answered " + r)
        elif mode == "pools3":
            for i in range(3):
                host.cmd("pool_config p%d %d" % (i, a.plugins))
        elif mode == "mixed":
            for i in range(2):
                host.cmd("pool_config p%d %d" % (i, a.plugins))
        t0 = time.monotonic()
        notes = []
        for i, place in enumerate(placements(mode, a.plugins)):
            p = LIGHT[i % len(LIGHT)]
            r = host.cmd("add clap:/usr/lib/clap/omx-%s.clap#org.openmixer.%s %d %s" % (p, p, i + 1, place))
            if not r.startswith("resp %d" % (i + 1)):
                notes.append("add %d %s answered %s" % (i + 1, place, r))
        added = [i + 1 for i in range(a.plugins)]
        ports = srv.ports()
        sine = subprocess.Popen(["jack_simple_client"], env=srv.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
        ports = srv.ports()
        wired = 0
        for n in added:
            head = "effect_%d" % n
            ins = [x for x in ports if x.startswith(head + ":in")]
            outs = [x for x in ports if x.startswith(head + ":out")]
            if ins and outs:
                subprocess.run(["jack_connect", "jack_simple:output1", ins[0]], env=srv.env, stderr=subprocess.DEVNULL)
                subprocess.run(["jack_connect", outs[0], "system:playback_1"], env=srv.env, stderr=subprocess.DEVNULL)
                wired += 1
        if wired != a.plugins:
            notes.append("%d of %d wired" % (wired, a.plugins))
        heavy = None
        if mode == "mixed":
            r = host.cmd("add %s %d own" % (a.heavy, a.plugins + 1), timeout=120)
            if not r.startswith("resp"):
                notes.append("heavy add answered " + r)
            heavy = "effect_%d" % (a.plugins + 1)
        got = None
        if heavy:
            got = vc.wait_ports(srv, [{"audio": heavy, "midi": heavy}])[heavy]
            script = os.path.join(a.out, "scenario-pools.txt")
            vc.probe_script(script, list(range(a.notes)), int((a.window + 3) * 1000))
            probe = subprocess.Popen([vc.PROBE, script, "pool_probe"], env=srv.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            probe.stdout.readline()
            subprocess.run(["jack_connect", "pool_probe:midi_out", got[1]], env=srv.env, check=True)
            for src, dst in zip(got[0], ("pool_probe:in_1", "pool_probe:in_2")):
                subprocess.run(["jack_connect", src, dst], env=srv.env, check=True)
            probe.stdin.write("go\n")
            probe.stdin.flush()
        row["add_s"] = round(time.monotonic() - t0, 2)
        time.sleep(3)
        log_before = vc_xruns(srv)
        pids = host.pids()
        jd = [srv.proc.pid]
        c0, th0, x0, j0, t0 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        load = subprocess.Popen(["jack_cpu_load"], env=srv.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(a.window)
        c1, th1, x1, j1, t1 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        row["pss_mb"], row["processes"] = vc.pss_mb(pids), len(pids)
        row["workers"] = host.cmd("worker_list")[:400].replace("\t", " ")
        row["jack_clients"] = len({n.split(":")[0] for n in srv.ports()} - {"system", "jack_simple", "pool_probe"})
        load.terminate()
        vals = []
        for line in load.communicate(timeout=5)[0].splitlines():
            for tok in line.replace("%", " ").split():
                try:
                    vals.append(float(tok))
                    break
                except ValueError:
                    pass
        vals = vals[1:]
        row["dsp_avg"], row["dsp_max"] = (round(statistics.mean(vals), 2), round(max(vals), 2)) if vals else ("", "")
        cores = []
        for k in sorted(c1):
            tot, idle = c1[k][0] - c0[k][0], c1[k][1] - c0[k][1]
            cores.append(100.0 * (tot - idle) / tot if tot else 0.0)
        for i, v in enumerate(cores[:4]):
            row["core%d" % i] = round(v, 1)
        row["busiest_core"] = round(max(cores), 1)
        span = t1 - t0
        row["cpu_pct"] = round(sum(t - th0.get(k, (t, 0))[0] for k, (t, _) in th1.items()) * 100.0 / vc.HZ / span, 2)
        row["ctx_vol_s"], row["ctx_invol_s"] = round((x1[0] - x0[0]) / span), round((x1[1] - x0[1]) / span)
        row["ctx_jackd_s"] = round((j1[0] - j0[0] + j1[1] - j0[1]) / span)
        row["xruns"] = vc_xruns(srv) - log_before
        row["status"] = "ok"
        row["note"] = "; ".join(notes)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        row["note"] = ("; ".join(notes) if "notes" in dir() else "") + " " + str(e)
    finally:
        for p in (sine, probe, load):
            if p and p.poll() is None:
                p.kill()
                p.wait(5)
        if host:
            host.close()
        srv.stop()
    return row


def vc_xruns(srv):
    """the server's own count of xruns, from its log, whose file every row appends to"""
    srv.logf.flush()
    with open(srv.logf.name, errors="replace") as f:
        return sum(1 for line in f if "XRun" in line or "xrun" in line)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--plugins", type=int, default=16)
    ap.add_argument("--modes", default="own,pools3,pool1,pool1-default,mixed")
    ap.add_argument("--heavy", default="clap:/usr/local/lib/clap/Surge%20XT.clap#org.surge-synth-team.surge-xt")
    ap.add_argument("--notes", type=int, default=16)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--frames", type=int, default=256)
    ap.add_argument("--port", type=int, default=5740)
    a = ap.parse_args()
    a.host = "hostd"
    os.makedirs(a.out, exist_ok=True)
    tsv = os.path.join(a.out, "pools.tsv")
    if not os.path.exists(tsv):
        with open(tsv, "w") as f:
            f.write("\t".join(COLUMNS) + "\n")
    for rep in range(1, a.repeats + 1):
        for mode in a.modes.split(","):
            row = one_row(a, mode, rep)
            with open(tsv, "a") as f:
                f.write("\t".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
            print("pools: %s rep %d: %s dsp %s cpu %s pss %s clients %s xruns %s busiest %s %s" % (
                mode, rep, row["status"], row.get("dsp_avg"), row.get("cpu_pct"), row.get("pss_mb"), row.get("jack_clients"),
                row.get("xruns"), row.get("busiest_core"), row.get("note", "")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""A shared effect against an effect per chain, as a JACK graph on a private server (no Zynthian routing).

    mixbus-bench.py --out DIR graph [--instruments 4,8] [--set third|omx] [--hosts jalv,mod-host,hostd,hostd-chain]
    mixbus-bench.py --out DIR parallel
    mixbus-bench.py --out DIR crash [--instruments 4]

graph: instruments holding notes feed either one reverb and delay (shared) or a reverb and delay each (perchain), into the
main output. Each row reads DSP, PSS, JACK clients, context switches, xruns and the level at main. hostd gives every plugin
a worker; hostd-chain makes each reverb and delay one chain.
parallel: a tone through one path, then through two identical paths side by side: two in phase read +6.02 dB over one.
crash: kill -9 the worker of a shared reverb and delay while the instruments sound: the gap at main, when its client is back,
the xruns, and whether a parameter set before the kill reads the same after.
"""
import argparse
import importlib.util
import math
import os
import signal
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("voices_cores", os.path.join(HERE, "voices-cores.py"))
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)
INSTRUMENT = "http://moddevices.com/plugins/mda/EPiano"
SETS = {"third": ("urn:dragonfly:room", "urn:zamaudio:ZamDelay"), "omx": ("urn:openmixer:reverb", "urn:openmixer:delay")}
COLUMNS = ["set", "topology", "instruments", "host", "repeat", "status", "plugins", "xruns", "dsp_avg", "dsp_max", "cpu_pct", "pss_mb",
           "processes", "jack_clients", "ctx_vol_s", "ctx_invol_s", "ctx_jackd_s", "peak_db", "rms_db", "core0", "core1", "core2", "core3", "note"]


class rig:
    """one host on one private server, plugins by number, and the wires between them"""

    def __init__(self, a, host, out):
        self.a, self.kind, self.out = a, host, out
        b = argparse.Namespace(host=host, rate=a.rate, frames=a.frames, cmd="", client="", midi_client="")
        self.srv = vc.server(b, out)
        self.host = vc.proc_host(b, self.srv, out) if host == "jalv" else vc.protocol_host(b, self.srv, out, a.port)
        self.n = 0
        self.via_host = False  # the daemon's own connect verb, which it replays after a crash; jack_connect's links it does not know

    def add(self, uri):
        self.n += 1
        n = self.n
        if self.kind == "jalv":
            self.host.spawn(["jalv", "-n", "inst_%d" % n, uri])
            return "inst_%d" % n
        target = "lv2:" + uri if self.kind == "clap-host" else uri
        tail = " own" if self.kind == "hostd" else ""
        r = self.host.cmd("add %s %d%s" % (target, n, tail))
        if not r.startswith("resp %d" % n):
            raise RuntimeError("add %s answered %s" % (uri, r))
        return "effect_%d" % n

    def ports_of(self, client, want):
        ports = self.srv.ports()
        names = [p for p in ports if p.startswith(client + ":")]
        audio = [p for p in names if "audio" in ports[p] and want in ports[p]]
        return sorted(audio)

    def wait(self, client, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.ports_of(client, "output"):
                return
            time.sleep(0.1)
        raise RuntimeError("%s has no audio output" % client)

    def link(self, src, dst):
        outs, ins = self.ports_of(src, "output"), dst if isinstance(dst, list) else self.ports_of(dst, "input")
        if not outs or not ins:
            raise RuntimeError("no ports to link %s to %s" % (src, dst))
        for i, d in enumerate(ins[:2]):
            if self.via_host:
                r = self.host.cmd("connect %s %s" % (outs[min(i, len(outs) - 1)], d))
                if not r.startswith("resp 0"):
                    raise RuntimeError("connect answered " + r)
            else:
                subprocess.run(["jack_connect", outs[min(i, len(outs) - 1)], d], env=self.srv.env, stderr=subprocess.DEVNULL)

    def close(self):
        self.host.close()
        self.srv.stop()


def midi_inputs(r, client):
    ports = r.srv.ports()
    return [p for p in ports if p.startswith(client + ":") and "midi" in ports[p] and "input" in ports[p]]


def probe_up(r, steps, name="mb_probe"):
    script = os.path.join(r.out, "scenario-mb.txt")
    with open(script, "w") as f:
        f.write("\n".join(steps) + "\n")
    p = subprocess.Popen([vc.PROBE, script, name], env=r.srv.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    if p.stdout.readline().strip() != "ready":
        raise RuntimeError("the probe did not start")
    return p, ["%s:in_1" % name, "%s:in_2" % name]


def build(r, topology, instruments, fx):
    """the plugins and their wires; returns the instruments, and the clients that reach main"""
    insts = [r.add(INSTRUMENT) for _ in range(instruments)]
    pairs = [(r.add(fx[0]), r.add(fx[1]))] if topology == "shared" else [(r.add(fx[0]), r.add(fx[1])) for _ in range(instruments)]
    for c in insts + [x for pair in pairs for x in pair]:
        r.wait(c)
    grouped = r.kind == "hostd-chain"
    if grouped:
        for k, (a, b) in enumerate(pairs, 1):
            reply = r.host.cmd("chain %d %s %s" % (k, a.split("_")[1], b.split("_")[1]))
            if reply != "resp 0":
                raise RuntimeError("chain answered " + reply)
        time.sleep(1)
    tails = []
    for k, (a, b) in enumerate(pairs):
        one_client = grouped and not r.ports_of(b, "output")
        if not grouped:
            r.link(a, b)
        tails.append(a if one_client else b)
    for i, c in enumerate(insts):
        r.link(c, pairs[0][0] if topology == "shared" else pairs[i][0])
    return insts, tails


def graph_row(a, fx_name, topology, instruments, host, rep):
    row = {"set": fx_name, "topology": topology, "instruments": instruments, "host": host, "repeat": rep, "status": "failed"}
    r = None
    load, p = None, None
    try:
        r = rig(a, host, a.out)
        insts, tails = build(r, topology, instruments, SETS[fx_name])
        keys = [48, 52, 55, 60]
        steps = ["wait 300"] + ["midi 90 %x 64" % k for k in keys] + ["wait 1500", "mark held", "wait %d" % int((a.window + 3) * 1000), "end"]
        steps += ["midi 80 %x 0" % k for k in keys] + ["wait 300"]
        p, ins = probe_up(r, steps)
        for c in insts:
            for m in midi_inputs(r, c)[:1]:
                subprocess.run(["jack_connect", "mb_probe:midi_out", m], env=r.srv.env, check=True)
        for t in tails:
            r.link(t, ins)
            r.link(t, ["system:playback_1", "system:playback_2"])
        p.stdin.write("go\n")
        p.stdin.flush()
        time.sleep(2.2)
        pids, jd = r.host.pids(), [r.srv.proc.pid]
        c0, th0, x0, j0, t0 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        load = subprocess.Popen(["jack_cpu_load"], env=r.srv.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(a.window)
        c1, th1, x1, j1, t1 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        span = t1 - t0
        row["pss_mb"], row["processes"] = vc.pss_mb(pids), len(pids)
        row["plugins"] = r.n
        row["jack_clients"] = len({x.split(":")[0] for x in r.srv.ports()} - {"system", "mb_probe"})
        row["cpu_pct"] = round(sum(t - th0.get(k, (t, 0))[0] for k, (t, _) in th1.items()) * 100.0 / vc.HZ / span, 2)
        row["ctx_vol_s"], row["ctx_invol_s"] = round((x1[0] - x0[0]) / span), round((x1[1] - x0[1]) / span)
        row["ctx_jackd_s"] = round((j1[0] - j0[0] + j1[1] - j0[1]) / span)
        for i, k in enumerate(sorted(c1)[:4]):
            tot, idle = c1[k][0] - c0[k][0], c1[k][1] - c0[k][1]
            row["core%d" % i] = round(100.0 * (tot - idle) / tot, 1) if tot else ""
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
        if vals:
            row["dsp_avg"], row["dsp_max"] = round(statistics.mean(vals), 2), round(max(vals), 2)
        for line in p.stdout:
            w = line.split()
            if w and w[0] == "window":
                kv = dict(zip(w[2::2], w[3::2]))
                row["peak_db"], row["rms_db"], row["xruns"] = kv["peak"], kv["rms"], kv["xruns"]
            elif w and w[0] == "done":
                break
        row["status"] = "ok"
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        row["note"] = str(e)[:250]
    finally:
        for x in (load, p):
            if x and x.poll() is None:
                x.kill()
                x.wait(5)
        if r:
            r.close()
    return row


def tone_level(a, paths):
    """the tone through `paths` copies of a flat omx eq8 side by side, read at one probe: peak in dBFS"""
    r = rig(a, "hostd", a.out)
    tone, p = None, None
    try:
        clients = [r.add("urn:openmixer:eq8") for _ in range(paths)]
        for c in clients:
            r.wait(c)
        p, ins = probe_up(r, ["wait 1500", "mark tone", "wait 3000", "end"])
        tone = subprocess.Popen(["jack_simple_client"], env=r.srv.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
        for k in (1, 2):
            subprocess.run(["jack_disconnect", "jack_simple_client:output%d" % k, "system:playback_%d" % k], env=r.srv.env, stderr=subprocess.DEVNULL)
        for c in clients:
            cin, cout = r.ports_of(c, "input"), r.ports_of(c, "output")
            subprocess.run(["jack_connect", "jack_simple_client:output1", cin[0]], env=r.srv.env, check=True)
            subprocess.run(["jack_connect", cout[0], ins[0]], env=r.srv.env, check=True)
        p.stdin.write("go\n")
        p.stdin.flush()
        for line in p.stdout:
            w = line.split()
            if w and w[0] == "window":
                return float(dict(zip(w[2::2], w[3::2]))["peak"])
            if w and w[0] == "done":
                break
        raise RuntimeError("no window")
    finally:
        for x in (tone, p):
            if x and x.poll() is None:
                x.kill()
                x.wait(5)
        r.close()


def crash_row(a, instruments, rep):
    row = {"repeat": rep, "instruments": instruments}
    r = rig(a, "hostd", a.out)
    p = None
    try:
        r.via_host = True
        insts, tails = build(r, "shared", instruments, SETS["omx"])
        worker = None
        for w in r.host.cmd("worker_list").split()[2:]:
            f = w.split(":")
            members = f[-1].split(",")
            if str(instruments + 1) in members:
                worker = int(f[1])
        if not worker:
            raise RuntimeError("no worker holds the reverb")
        before = r.host.cmd("param_get %d mix" % (instruments + 1))
        row["param_before"] = before
        step_ms, total = 50, 8000
        # the notes struck again and again, so that a silence at main is the kill and not the notes dying away
        strike = ["midi 90 %x 64" % k for k in (48, 52, 55, 60)]
        steps = ["wait 300"] + strike + ["wait 1000"]
        for i in range(total // step_ms):
            steps += (strike if i % 8 == 0 else []) + ["mark w%d" % i, "wait %d" % step_ms, "end"]
        p, ins = probe_up(r, steps)
        for c in insts:
            for m in midi_inputs(r, c)[:1]:
                subprocess.run(["jack_connect", "mb_probe:midi_out", m], env=r.srv.env, check=True)
        for t in tails:
            r.link(t, ins)
        p.stdin.write("go\n")
        p.stdin.flush()
        time.sleep(3.3)
        t_kill = time.monotonic()
        os.kill(worker, signal.SIGKILL)
        client = "effect_%d" % (instruments + 1)
        gone, back, wired = None, None, None
        while time.monotonic() - t_kill < 20:
            if gone is None and not r.ports_of(client, "output"):
                gone = time.monotonic() - t_kill
            if gone is not None and back is None and r.ports_of(client, "output"):
                back = time.monotonic() - t_kill
            if back is not None:
                out = subprocess.run(["jack_lsp", "-c"], env=r.srv.env, capture_output=True, text=True).stdout
                lines = out.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith(client + ":in") and i + 1 < len(lines) and lines[i + 1].startswith(" "):
                        wired = time.monotonic() - t_kill
                if wired:
                    break
            time.sleep(0.02)
        row["client_back_s"] = round(back, 2) if back else ""
        row["rewired_s"] = round(wired, 2) if wired else ""
        peaks, xruns = [], 0
        for line in p.stdout:
            w = line.split()
            if w and w[0] == "window":
                kv = dict(zip(w[2::2], w[3::2]))
                peaks.append(float(kv["peak"]))
                xruns = max(xruns, int(kv["xruns"]))
            elif w and w[0] == "done":
                break
        silent = [i for i, v in enumerate(peaks) if not v > -100]
        row["gap_ms"] = len(silent) * step_ms
        row["first_silent_ms"] = silent[0] * step_ms if silent else ""
        row["last_silent_ms"] = silent[-1] * step_ms if silent else ""
        row["xruns"] = xruns
        row["peak_before"], row["peak_end"] = max(peaks[:20]), max(peaks[-20:])
        row["param_after"] = r.host.cmd("param_get %d mix" % (instruments + 1))
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        row["note"] = str(e)[:250]
    finally:
        if p and p.poll() is None:
            p.kill()
            p.wait(5)
        r.close()
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("what", choices=("graph", "parallel", "crash"))
    ap.add_argument("--instruments", default="4,8")
    ap.add_argument("--set", default="third,omx")
    ap.add_argument("--hosts", default="jalv,mod-host,hostd,hostd-chain")
    ap.add_argument("--window", type=int, default=15)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--frames", type=int, default=256)
    ap.add_argument("--port", type=int, default=5760)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.what == "graph":
        path = os.path.join(a.out, "mixbus.tsv")
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write("\t".join(COLUMNS) + "\n")
        for rep in range(1, a.repeats + 1):
            for fx in a.set.split(","):
                for n in [int(x) for x in a.instruments.split(",")]:
                    for topo in ("shared", "perchain"):
                        for host in a.hosts.split(","):
                            row = graph_row(a, fx, topo, n, host, rep)
                            with open(path, "a") as f:
                                f.write("\t".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
                            print("mixbus: %s %s x%d %s rep %d: %s dsp %s pss %s clients %s xruns %s peak %s %s" % (
                                fx, topo, n, host, rep, row["status"], row.get("dsp_avg"), row.get("pss_mb"), row.get("jack_clients"),
                                row.get("xruns"), row.get("peak_db"), row.get("note", "")), flush=True)
    elif a.what == "parallel":
        for rep in range(1, a.repeats + 1):
            one, two = tone_level(a, 1), tone_level(a, 2)
            print("parallel: rep %d one path %.2f dB, two paths %.2f dB, difference %.2f dB, closed form %.2f dB" % (
                rep, one, two, two - one, 20 * math.log10(2)), flush=True)
    else:
        for rep in range(1, a.repeats + 1):
            print("crash: %s" % crash_row(a, int(a.instruments.split(",")[0]), rep), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

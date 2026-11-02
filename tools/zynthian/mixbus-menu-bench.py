#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""A Mixbus as Zynthian builds it, on the device's own JACK server, with Zynthian's mixer in the path.

    mixbus-menu-bench.py graph --out FILE
    mixbus-menu-bench.py measure --out DIR --label LABEL --host hostd|mod-host|jalv --instruments auto|C1,C2,...
        [--repeat N] [--window 15] [--main PORT_A,PORT_B]
    mixbus-menu-bench.py modhost --out DIR --port 5580 --add NAME=URI ... --link SRC=DST ... [--cut SRC=DST ...]

graph: the device graph as JSON (every port with its direction and type, and every connection), to compare the
wiring Zynthian made with the wiring another host is given.
measure: the chains are already built (from Zynthian's own menu, or by modhost). The probe holds four notes on every
instrument named (auto: every client linked into a channel strip's input), by a link from its MIDI output to each instrument's MIDI input, and reads the main output, after
Zynthian's mixer. One row over --window seconds with the notes held: JACK's DSP load (jack_cpu_load), the PSS of the
host's processes, the server's xruns, the level at main, context switches and the load of each core. The host's
processes: plugin-hostd's daemon and every process under it; mod-host: the process listening on --modhost-port;
jalv: every jalv process.
modhost: one mod-host on the device's JACK server, its plugins added in order (NAME is the role, so that a --link can
name it: NAME:out1 is the plugin's first audio output, NAME:in2 its second audio input, NAME:midi its MIDI input) and
the links made with jack_connect; each --cut is a link Zynthian made that the host takes the place of (a Mixbus with
no effect has its send linked straight to its strip), removed with jack_disconnect. It stays up until it is sent SIGTERM; it writes its pid to DIR/mod-host.pid. mod-host finds plugins on LV2_PATH: give
it Zynthian's.
measure --cut SRC=DST, as modhost takes it, removes that link again before the window, and the row fails when Zynthian
has made it again by the end of the window (its autoconnect runs on every UI action).
Nothing here touches Zynthian's configuration: the device's server is read and linked to, and only the probe's own
links and the mod-host this tool started are removed when it ends.
"""
import argparse
import importlib.util
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("voices_cores", os.path.join(HERE, "voices-cores.py"))
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)
PROBE_NAME = "mb_probe"
KEYS = [48, 52, 55, 60]
COLUMNS = ["label", "host", "repeat", "status", "instruments", "xruns", "dsp_avg", "dsp_max", "cpu_pct", "pss_mb", "processes",
           "jack_clients", "ctx_vol_s", "ctx_invol_s", "ctx_jackd_s", "peak_db", "rms_db", "core0", "core1", "core2", "core3",
           "mem_avail_mb", "note"]


def ports():
    """{port: 'input audio' ...} on the device's server"""
    out = subprocess.run(["jack_lsp", "-p", "-t"], capture_output=True, text=True, check=True).stdout.splitlines()
    res, cur = {}, None
    for line in out:
        if not line.startswith("\t"):
            cur = line.strip()
            res[cur] = ""
        elif cur:
            res[cur] += " " + line.strip()
    return res


def connections():
    out = subprocess.run(["jack_lsp", "-c"], capture_output=True, text=True, check=True).stdout.splitlines()
    edges, cur = [], None
    for line in out:
        if not line.startswith((" ", "\t")):
            cur = line.strip()
        elif cur:
            edges.append((cur, line.strip()))
    return edges


def graph():
    p = ports()
    kinds = {n: {"dir": "input" if "input" in v else "output", "type": "midi" if "midi" in v else "audio"} for n, v in p.items()}
    edges = sorted({(a, b) if kinds.get(a, {}).get("dir") == "output" else (b, a) for a, b in connections()})
    return {"ports": kinds, "edges": edges}


def of(client, p, direction, kind):
    return sorted(n for n, v in p.items() if n.startswith(client + ":") and direction in v and kind in v)


def strip_feeders():
    """the clients linked into a channel strip's input, in the strips' order: the instruments of the chains"""
    seen = []
    for src, dst in sorted(graph()["edges"], key=lambda e: e[1]):
        client = src.split(":")[0]
        if dst.startswith("zynmixer_chan:input_") and not client.startswith(("system", "zynmixer")) and client not in seen:
            seen.append(client)
    return seen


def descendants(root):
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/stat" % d) as f:
                    s = f.read()
                kids.setdefault(int(s[s.rindex(")") + 2:].split()[1]), []).append(int(d))
            except OSError:
                pass
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def pgrep(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]


def host_pids(a):
    if a.host == "hostd":
        roots = pgrep("^plugin-hostd ")
        return sorted({p for r in roots for p in descendants(r)})
    if a.host == "mod-host":
        return sorted({p for r in pgrep("^mod-host -n -p %d" % a.modhost_port) for p in descendants(r)})
    return sorted(pgrep("^(/usr/local/bin/)?jalv "))


def measure(a):
    os.makedirs(a.out, exist_ok=True)
    row = {"label": a.label, "host": a.host, "repeat": a.repeat, "status": "failed"}
    insts = strip_feeders() if a.instruments == "auto" else [c for c in a.instruments.split(",") if c]
    row["instruments"] = len(insts)
    probe, load, links = None, None, []
    try:
        p = ports()
        midi_ins = []
        for c in insts:
            m = of(c, p, "input", "midi")
            if not m:
                raise RuntimeError("%s has no MIDI input" % c)
            midi_ins.append(m[0])
        cuts = [tuple(c.split("=", 1)) for c in a.cut]
        for src, dst in cuts:
            subprocess.run(["jack_disconnect", src, dst], stderr=subprocess.DEVNULL)
        main = a.main.split(",")
        for m in main:
            if m not in p:
                raise RuntimeError("no port %s" % m)
        steps = ["wait 300"] + ["midi 90 %x 64" % k for k in KEYS] + ["wait 1500", "mark held", "wait %d" % int((a.window + 3) * 1000), "end"]
        steps += ["midi 80 %x 0" % k for k in KEYS] + ["wait 300"]
        script = os.path.join(a.out, "scenario-%s-%s.txt" % (a.label, a.repeat))
        with open(script, "w") as f:
            f.write("\n".join(steps) + "\n")
        probe = subprocess.Popen([vc.PROBE, script, PROBE_NAME], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if probe.stdout.readline().strip() != "ready":
            raise RuntimeError("the probe did not start")
        links = [("%s:midi_out" % PROBE_NAME, m) for m in midi_ins] + [(main[0], "%s:in_1" % PROBE_NAME), (main[1], "%s:in_2" % PROBE_NAME)]
        for s, d in links:
            subprocess.run(["jack_connect", s, d], check=True)
        probe.stdin.write("go\n")
        probe.stdin.flush()
        time.sleep(2.2)
        pids = host_pids(a)
        if not pids:
            raise RuntimeError("no %s process" % a.host)
        jd = pgrep("^/usr/bin/jackd ")
        c0, th0, x0, j0, t0 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        load = subprocess.Popen(["jack_cpu_load"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(a.window)
        c1, th1, x1, j1, t1 = vc.core_times(), vc.thread_ticks(pids), vc.ctx(pids), vc.ctx(jd), time.monotonic()
        span = t1 - t0
        row["pss_mb"], row["processes"] = vc.pss_mb(pids), len(pids)
        row["mem_avail_mb"] = vc.mem_available_mb()
        row["jack_clients"] = len({x.split(":")[0] for x in ports()} - {PROBE_NAME})
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
        for line in probe.stdout:
            w = line.split()
            if w and w[0] == "window":
                kv = dict(zip(w[2::2], w[3::2]))
                row["peak_db"], row["rms_db"], row["xruns"] = kv["peak"], kv["rms"], kv["xruns"]
            elif w and w[0] == "done":
                break
        after = graph()
        if a.graph_after:
            with open(a.graph_after, "w") as f:
                json.dump(after, f, indent=1)
        back = [c for c in cuts if tuple(c) in set(map(tuple, after["edges"]))]
        if back:
            raise RuntimeError("Zynthian linked %s again during the window" % " and ".join("=".join(c) for c in back))
        row["status"] = "ok"
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        row["note"] = str(e)[:250]
    finally:
        for x in (load, probe):
            if x and x.poll() is None:
                x.kill()
                x.wait(5)
    path = os.path.join(a.out, "mixbus-menu.tsv")
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new:
            f.write("\t".join(COLUMNS) + "\n")
        f.write("\t".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
    print("mixbus-menu: %s %s rep %s: %s dsp %s pss %s clients %s xruns %s peak %s %s" % (
        a.label, a.host, a.repeat, row["status"], row.get("dsp_avg"), row.get("pss_mb"), row.get("jack_clients"), row.get("xruns"),
        row.get("peak_db"), row.get("note", "")), flush=True)
    return 0 if row["status"] == "ok" else 1


class modhost:
    def __init__(self, port, out):
        self.logf = open(os.path.join(out, "mod-host.log"), "a")
        self.proc = subprocess.Popen(["mod-host", "-n", "-p", str(port)], stdout=self.logf, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        end = time.monotonic() + 15
        self.sock = None
        while time.monotonic() < end and not self.sock:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.1)
        if not self.sock:
            raise RuntimeError("mod-host never listened on %d" % port)
        self.buf = b""

    def cmd(self, line):
        self.sock.settimeout(120)
        self.sock.sendall(line.encode() + b"\0")
        while b"\0" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("mod-host closed the connection on: " + line)
            self.buf += chunk
        reply, _, self.buf = self.buf.partition(b"\0")
        return reply.decode(errors="replace")


def resolve(end, roles, p):
    """NAME:out1 / NAME:in2 / NAME:midi to a port of the role's client; anything else is a port name as it is"""
    name, _, what = end.partition(":")
    if name not in roles:
        return end
    client = roles[name]
    if what == "midi":
        return of(client, p, "input", "midi")[0]
    kind, idx = ("output", int(what[3:])) if what.startswith("out") else ("input", int(what[2:]))
    found = of(client, p, kind, "audio")
    return found[min(idx, len(found)) - 1]


def run_modhost(a):
    os.makedirs(a.out, exist_ok=True)
    h = modhost(a.port, a.out)
    try:
        return serve_modhost(a, h)
    finally:
        if h.proc.poll() is None:
            os.killpg(h.proc.pid, signal.SIGTERM)
            h.proc.wait(10)


def serve_modhost(a, h):
    """the plugins and links of run_modhost, then wait for SIGTERM; mod-host is stopped by the caller"""
    with open(os.path.join(a.out, "mod-host.pid"), "w") as f:
        f.write("%d\n" % h.proc.pid)
    roles = {}
    for n, item in enumerate(a.add):
        name, _, uri = item.partition("=")
        r = h.cmd("add %s %d" % (uri, n))
        if not r.startswith("resp %d" % n):
            raise SystemExit("add %s answered %s" % (uri, r))
        roles[name] = "effect_%d" % n
    end = time.monotonic() + 60
    while time.monotonic() < end:
        p = ports()
        if all(of(c, p, "output", "audio") for c in roles.values()):
            break
        time.sleep(0.2)
    p = ports()
    made = []
    for item in a.link:
        s, _, d = item.partition("=")
        src, dst = resolve(s, roles, p), resolve(d, roles, p)
        subprocess.run(["jack_connect", src, dst], check=True)
        made.append((src, dst))
    cut = []
    for item in a.cut:
        s, _, d = item.partition("=")
        subprocess.run(["jack_disconnect", s, d], check=True)
        cut.append((s, d))
    with open(os.path.join(a.out, "mod-host-links.json"), "w") as f:
        json.dump({"roles": roles, "links": made, "cut": cut}, f, indent=1)
    print("modhost: up, pid %d, %d plugins, %d links" % (h.proc.pid, len(roles), len(made)), flush=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    while not stop and h.proc.poll() is None:
        time.sleep(0.5)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("graph", "measure", "modhost"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--host", choices=("hostd", "mod-host", "jalv"), default="hostd")
    ap.add_argument("--instruments", default="")
    ap.add_argument("--repeat", default="1")
    ap.add_argument("--window", type=int, default=15)
    ap.add_argument("--main", default="zynmixer_bus:output_00a,zynmixer_bus:output_00b")
    ap.add_argument("--modhost-port", type=int, default=5580)
    ap.add_argument("--port", type=int, default=5580)
    ap.add_argument("--add", action="append", default=[])
    ap.add_argument("--link", action="append", default=[])
    ap.add_argument("--cut", action="append", default=[], help="modhost and measure: a link to remove, SRC=DST")
    ap.add_argument("--graph-after", default="", help="measure: the graph as JSON once the row is read, to show the wiring held")
    a = ap.parse_args()
    if a.what == "graph":
        with open(a.out, "w") as f:
            json.dump(graph(), f, indent=1)
        return 0
    if a.what == "measure":
        return measure(a)
    return run_modhost(a)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""How an instrument uses the cores: one row per host, instance count, notes held and repeat.

    voices-cores.py --out DIR --host hostd|hostd-chain|clap-host|mod-host|jalv|cmd --uri URI --name NAME
        [--instances 1,2,4] [--notes 16] [--total] [--hold 15] [--repeats 3] [--rate 48000] [--frames 256]
        [--param 'SYMBOL VALUE'] [--cmd 'PROGRAM ...' --client CLIENT --midi-client CLIENT]

It starts a private JACK server on the dummy driver at the rate and quantum, so the device's JACK is never touched, then
the host and its instances, and one jack-instrument-probe per instance, which holds the notes on that instance alone and
reads its first two outputs. Each row reads, over --hold seconds with the notes held: the probes' xruns, level and pitch,
JACK's DSP load (jack_cpu_load), the load of each core (/proc/stat), the CPU of every thread of the host (with the core it
last ran on), the voluntary and involuntary context switches of the host's threads and the server's, and PSS.

--notes is the notes each instance holds. With --total it is the notes of all the instances together, dealt round-robin,
so that one instance with 16 notes and four with 4 each play the same chord. --instances is the climb: after a level with
xruns over --burst, DSP load over --dsp-limit, or under --mem-floor MB available, the climb stops. A level that would go
under the floor is not started.

busy_threads counts threads over 5 % of a core. gain is the CPU of the busy threads over that of the busiest one: 1.0 means
all the work is on one thread. Those are the program's own threads: this tool says nothing about whose threads they are.
"""
import argparse
import glob
import os
import shlex
import signal
import socket
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.environ.get("INSTRUMENT_PROBE", os.path.join(HERE, "jack-instrument-probe"))
HZ = os.sysconf("SC_CLK_TCK")
COLUMNS = ["name", "host", "rate", "frames", "instances", "notes_each", "notes_total", "repeat", "status", "xruns",
           "dsp_avg", "dsp_max", "peak_db", "rms_db", "hz", "core0", "core1", "core2", "core3", "cores_over_20", "busy_threads",
           "busiest_pct", "threads_pct", "gain", "ctx_vol_s", "ctx_invol_s", "ctx_jackd_s", "pss_mb", "processes", "add_s",
           "voices",
           "threads", "note"]


def log(msg):
    print("voices-cores: " + msg, file=sys.stderr, flush=True)


def mem_available_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0


def thread_ticks(pids):
    out = {}
    for pid in pids:
        for stat in glob.glob("/proc/%d/task/*/stat" % pid):
            try:
                s = open(stat).read()
            except OSError:
                continue
            w = s[s.rindex(")") + 2:].split()
            tid = stat.split("/")[4]
            out["%d/%s/%s" % (pid, tid, s[s.index("(") + 1:s.rindex(")")].replace(" ", "_"))] = (int(w[11]) + int(w[12]), int(w[36]))
    return out


def ctx(pids):
    vol = invol = 0
    for pid in pids:
        for status in glob.glob("/proc/%d/task/*/status" % pid):
            try:
                with open(status) as f:
                    for line in f:
                        if line.startswith("voluntary_ctxt_switches:"):
                            vol += int(line.split()[1])
                        elif line.startswith("nonvoluntary_ctxt_switches:"):
                            invol += int(line.split()[1])
            except OSError:
                pass
    return vol, invol


def pss_mb(pids):
    total = 0
    for pid in pids:
        try:
            with open("/proc/%d/smaps_rollup" % pid) as f:
                for line in f:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1])
        except OSError:
            pass
    return round(total / 1024, 1)


def core_times():
    cores = {}
    with open("/proc/stat") as f:
        for line in f:
            w = line.split()
            if w[0].startswith("cpu") and w[0] != "cpu":
                vals = [int(x) for x in w[1:]]
                cores[w[0]] = (sum(vals), vals[3] + vals[4])
    return cores


class server:
    def __init__(self, a, out):
        self.name = "vc%d" % os.getpid()
        self.env = dict(os.environ, JACK_DEFAULT_SERVER=self.name)
        self.logf = open(os.path.join(out, "jackd.log"), "a")
        self.proc = subprocess.Popen(["jackd", "-n", self.name, "-d", "dummy", "-r", str(a.rate), "-p", str(a.frames)],
                                     stdout=self.logf, stderr=subprocess.STDOUT, start_new_session=True)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if subprocess.run(["jack_lsp"], env=self.env, capture_output=True).returncode == 0:
                return
            time.sleep(0.2)
        raise SystemExit("the private JACK server did not start")

    def ports(self, flags=()):
        out = subprocess.run(["jack_lsp", "-p", "-t"], env=self.env, capture_output=True, text=True).stdout.splitlines()
        res, cur, props = {}, None, ""
        for line in out:
            if not line.startswith("\t"):
                cur = line.strip()
                res[cur] = ""
            elif cur:
                res[cur] += " " + line.strip()
        return res

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


class protocol_host:
    """plugin-hostd, omx-clap-host or mod-host on a private port, spoken to over the mod-host protocol"""

    def __init__(self, a, srv, out, port):
        self.out, self.a = out, a
        self.logf = open(os.path.join(out, "host.log"), "a")
        if a.host in ("hostd", "hostd-chain"):
            conf = os.path.join(out, "plugin-hostd.conf")
            state = os.path.join(out, "state")
            with open(conf, "w") as f:
                f.write("clap_host omx-clap-host\nlv2_worker omx-clap-host\nrequire_pins 0\nstate_root %s\n"
                        "descriptor_dir %s/descriptors\nqualification_dir %s/qualification\n" % (state, state, state))
            argv = ["plugin-hostd", "-n", "-p", str(port), "-c", conf]
        elif a.host == "clap-host":
            argv = ["omx-clap-host", "-n", "-p", str(port)]
        else:
            argv = ["mod-host", "-n", "-p", str(port)]
        self.proc = subprocess.Popen(argv, env=srv.env, stdout=self.logf, stderr=subprocess.STDOUT, start_new_session=True)
        end = time.monotonic() + 15
        self.sock = None
        while time.monotonic() < end and not self.sock:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.1)
        if not self.sock:
            raise RuntimeError("%s never listened" % a.host)
        self.buf = b""

    def cmd(self, line, timeout=120):
        self.sock.settimeout(timeout)
        self.sock.sendall(line.encode() + b"\0")
        while b"\0" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("the host closed the connection on: " + line)
            self.buf += chunk
        reply, _, self.buf = self.buf.partition(b"\0")
        reply = reply.decode(errors="replace")
        with open(os.path.join(self.out, "protocol.log"), "a") as f:
            f.write("> %s\n< %s\n" % (line, reply))
        return reply

    def pids(self):
        out = subprocess.run(["pgrep", "-g", str(self.proc.pid)], capture_output=True, text=True).stdout.split()
        return [int(p) for p in out]

    def close(self):
        for sig, wait in ((signal.SIGTERM, 8), (signal.SIGKILL, 3)):
            try:
                os.killpg(self.proc.pid, sig)
                self.proc.wait(wait)
                return
            except ProcessLookupError:
                return
            except subprocess.TimeoutExpired:
                pass


class proc_host:
    """programs of their own: one jalv per instance, or a --cmd"""

    def __init__(self, a, srv, out):
        self.procs, self.a, self.srv, self.out = [], a, srv, out

    def spawn(self, argv):
        log_file = open(os.path.join(self.out, "host.log"), "a")
        self.procs.append(subprocess.Popen(argv, env=self.srv.env, stdin=subprocess.PIPE, stdout=log_file,
                                           stderr=subprocess.STDOUT, start_new_session=True, text=True))

    def pids(self):
        out = []
        for p in self.procs:
            out += [int(x) for x in subprocess.run(["pgrep", "-g", str(p.pid)], capture_output=True, text=True).stdout.split()]
        return out

    def close(self):
        for p in self.procs:
            for sig, wait in ((signal.SIGTERM, 8), (signal.SIGKILL, 3)):
                try:
                    os.killpg(p.pid, sig)
                    p.wait(wait)
                    break
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    pass


def wait_ports(srv, clients, end_s=90):
    """each client's audio outputs and MIDI input, once it has them"""
    end = time.monotonic() + end_s
    while True:
        ports = srv.ports()
        got = {}
        for c in clients:
            names = [n for n in ports if n.startswith(c["audio"] + ":")]
            audio = [n for n in names if "output" in ports[n] and "audio" in ports[n]]
            mnames = [n for n in ports if n.startswith(c["midi"] + ":")]
            midi = [n for n in mnames if "input" in ports[n] and "midi" in ports[n]]
            if audio and midi:
                got[c["audio"]] = (audio[:2], midi[0])
        if len(got) == len(clients):
            return got
        if time.monotonic() > end:
            raise RuntimeError("no audio outputs and note input on %s" % [c["audio"] for c in clients if c["audio"] not in got])
        time.sleep(0.2)


def deal(notes, instances, total):
    """the keys of each instance; with total, the one chord dealt round-robin"""
    if not total:
        return [list(range(notes)) for _ in range(instances)]
    hands = [[] for _ in range(instances)]
    for i in range(notes):
        hands[i % instances].append(i)
    return hands


def key(k):
    """the k-th note: 80 keys from 36, on one channel after another past those"""
    return 36 + k % 80


def channel(k):
    c = k // 80 % 15
    return c + 1 if c >= 9 else c


def probe_script(path, keys, hold_ms):
    steps = ["wait 300"] + ["midi %x %x 64" % (0x90 | channel(k), key(k)) for k in keys]
    steps += ["wait 1500", "mark held", "wait %d" % hold_ms, "end"]
    steps += ["midi %x %x 0" % (0x80 | channel(k), key(k)) for k in keys] + ["wait 500"]
    with open(path, "w") as f:
        f.write("\n".join(steps) + "\n")


def one_row(a, srv, inst, notes, rep, out, port):
    row = {"name": a.name, "host": a.host, "rate": a.rate, "frames": a.frames, "instances": inst, "repeat": rep, "status": "failed"}
    hands = deal(notes, inst, a.total)
    row["notes_each"] = "/".join(str(len(h)) for h in hands) if a.total else notes
    row["notes_total"] = sum(len(h) for h in hands)
    host, probes, cpu_load = None, [], None
    try:
        t0 = time.monotonic()
        clients = []
        if a.host in ("hostd", "hostd-chain", "clap-host", "mod-host"):
            host = protocol_host(a, srv, out, port)
            for n in range(1, inst + 1):
                if mem_available_mb() < a.mem_floor:
                    raise RuntimeError("under %d MB available at instance %d" % (a.mem_floor, n))
                tail = " own" if a.host == "hostd" else ""
                reply = host.cmd("add %s %d%s" % (a.uri, n, tail))
                if not reply.startswith("resp %d" % n):
                    raise RuntimeError("add %d answered %s" % (n, reply))
                clients.append({"audio": "effect_%d" % n, "midi": "effect_%d" % n})
            if a.host == "hostd-chain" and inst > 1:
                reply = host.cmd("chain 1 " + " ".join(str(n) for n in range(1, inst + 1)))
                if not reply.startswith("resp 0"):
                    raise RuntimeError("chain answered %s" % reply)
            for p in a.param:
                for n in range(1, inst + 1):
                    host.cmd("param_set %d %s" % (n, p))
        elif a.host == "jalv":
            host = proc_host(a, srv, out)
            for n in range(1, inst + 1):
                if mem_available_mb() < a.mem_floor:
                    raise RuntimeError("under %d MB available at instance %d" % (a.mem_floor, n))
                host.spawn(["jalv", "-n", "inst_%d" % n, a.uri])
                clients.append({"audio": "inst_%d" % n, "midi": "inst_%d" % n})
        else:
            host = proc_host(a, srv, out)
            host.spawn(shlex.split(a.cmd))
            clients.append({"audio": a.client, "midi": a.midi_client or a.client})
        got = wait_ports(srv, clients)
        row["add_s"] = round(time.monotonic() - t0, 2)
        time.sleep(a.settle)
        hold_ms = int(a.hold * 1000)
        for i, c in enumerate(clients):
            audio, midi = got[c["audio"]]
            name = "vc_probe_%d" % i
            script = os.path.join(out, "scenario-%d.txt" % i)
            probe_script(script, [] if a.shell_notes else hands[i], hold_ms)
            p = subprocess.Popen([PROBE, script, name], env=srv.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            if p.stdout.readline().strip() != "ready":
                raise RuntimeError("the probe did not start")
            subprocess.run(["jack_connect", name + ":midi_out", midi], env=srv.env, check=True)
            for src, dst in zip(audio, (name + ":in_1", name + ":in_2")):
                subprocess.run(["jack_connect", src, dst], env=srv.env, check=True)
            probes.append(p)
        for p in probes:
            p.stdin.write("go\n")
            p.stdin.flush()
        if a.shell_notes:
            # a --cmd with a shell of its own takes the notes directly: FluidSynth's JACK MIDI did not take a chord this size
            host.procs[0].stdin.write("".join("noteon %d %d 100\n" % (channel(k), key(k)) for k in hands[0]))
            host.procs[0].stdin.flush()
        # the notes sound after the probes' first waits; the figures are read inside the probes' window
        time.sleep(2.2)
        pids = host.pids()
        jackd = [srv.proc.pid]
        c0, th0, x0, j0, t0 = core_times(), thread_ticks(pids), ctx(pids), ctx(jackd), time.monotonic()
        cpu_load = subprocess.Popen(["jack_cpu_load"], env=srv.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(max(1.0, a.hold - 1.0))
        if a.voice_query:
            host.procs[0].stdin.write(a.voice_query + "\n")
            host.procs[0].stdin.flush()
        c1, th1, x1, j1, t1 = core_times(), thread_ticks(pids), ctx(pids), ctx(jackd), time.monotonic()
        row["pss_mb"], row["processes"] = pss_mb(pids), len(pids)
        if a.voice_query:
            time.sleep(0.2)
            with open(os.path.join(out, "host.log"), errors="replace") as f:
                said = [line for line in f if line.lstrip("> ").startswith(a.voice_query + ":")]
            row["voices"] = said[-1].rsplit(":", 1)[1].strip() if said else ""
        cpu_load.terminate()
        loads = []
        for line in cpu_load.communicate(timeout=5)[0].splitlines():
            w = line.replace("%", " ").split()
            for tok in w:
                try:
                    loads.append(float(tok))
                    break
                except ValueError:
                    pass
        loads = loads[1:]
        row["dsp_avg"] = round(statistics.mean(loads), 1) if loads else ""
        row["dsp_max"] = round(max(loads), 1) if loads else ""
        cores = []
        for k in sorted(c1):
            tot, idle = c1[k][0] - c0[k][0], c1[k][1] - c0[k][1]
            cores.append(100.0 * (tot - idle) / tot if tot else 0.0)
        for i, v in enumerate(cores[:4]):
            row["core%d" % i] = round(v, 1)
        row["cores_over_20"] = sum(1 for v in cores if v > 20)
        span = t1 - t0
        th = []
        for k, (ticks, core) in th1.items():
            pct = 100.0 * (ticks - th0.get(k, (ticks, 0))[0]) / HZ / span
            th.append((pct, k.split("/", 2)[2], core))
        th.sort(reverse=True)
        busy = [t for t in th if t[0] > 5.0]
        row["busy_threads"] = len(busy)
        row["busiest_pct"] = round(th[0][0], 1) if th else ""
        row["threads_pct"] = round(sum(t[0] for t in th), 1)
        row["gain"] = round(sum(t[0] for t in busy) / busy[0][0], 2) if busy else ""
        row["threads"] = " ".join("%s@cpu%d=%.0f" % (t[1], t[2], t[0]) for t in th if t[0] >= 1.0)
        row["ctx_vol_s"] = round((x1[0] - x0[0]) / span)
        row["ctx_invol_s"] = round((x1[1] - x0[1]) / span)
        row["ctx_jackd_s"] = round((j1[0] - j0[0] + j1[1] - j0[1]) / span)
        peaks, rmss, hzs, xruns = [], [], [], []
        for p in probes:
            for line in p.stdout:
                w = line.split()
                if w and w[0] == "window":
                    kv = dict(zip(w[2::2], w[3::2]))
                    peaks.append(float(kv["peak"]))
                    rmss.append(float(kv["rms"]))
                    hzs.append(kv["hz"])
                    xruns.append(int(kv["xruns"]))
                elif w and w[0] == "done":
                    break
            p.wait(10)
        row["peak_db"] = round(max(peaks), 1) if peaks else ""
        row["rms_db"] = round(max(rmss), 1) if rmss else ""
        row["hz"] = hzs[0] if hzs else ""
        row["xruns"] = max(xruns) if xruns else ""
        row["status"] = "ok"
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        row["note"] = str(e).replace("\t", " ")[:300]
    finally:
        if cpu_load and cpu_load.poll() is None:
            cpu_load.kill()
        for p in probes:
            if p.poll() is None:
                p.kill()
                p.wait(5)
        if host:
            host.close()
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--host", required=True, choices=("hostd", "hostd-chain", "clap-host", "mod-host", "jalv", "cmd"))
    ap.add_argument("--uri", default="")
    ap.add_argument("--instances", default="1")
    ap.add_argument("--notes", default="16", help="comma-separated: each is a climb of its own")
    ap.add_argument("--total", action="store_true", help="--notes is the chord of all the instances together, dealt round-robin")
    ap.add_argument("--hold", type=float, default=15)
    ap.add_argument("--settle", type=float, default=2)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--frames", type=int, default=256)
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--cmd", default="")
    ap.add_argument("--client", default="")
    ap.add_argument("--midi-client", default="")
    ap.add_argument("--shell-notes", action="store_true", help="send the notes as 'noteon' lines to a --cmd's stdin")
    ap.add_argument("--voice-query", default="", help="a line for a --cmd's stdin that prints '<line>: <voices>' in its log")
    ap.add_argument("--burst", type=int, default=5)
    ap.add_argument("--dsp-limit", type=float, default=95)
    ap.add_argument("--mem-floor", type=int, default=700)
    ap.add_argument("--port", type=int, default=5720)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tsv = os.path.join(a.out, "voices-cores.tsv")
    if not os.path.exists(tsv):
        with open(tsv, "w") as f:
            f.write("\t".join(COLUMNS) + "\n")
    for notes in [int(x) for x in a.notes.split(",")]:
        for inst in [int(x) for x in a.instances.split(",")]:
            stop = None
            for rep in range(1, a.repeats + 1):
                srv = server(a, a.out)
                try:
                    row = one_row(a, srv, inst, notes, rep, a.out, a.port)
                finally:
                    srv.stop()
                with open(tsv, "a") as f:
                    f.write("\t".join(str(row.get(c, "")) for c in COLUMNS) + "\n")
                log("%s %s x%d notes %s rep %d: %s xruns %s dsp %s peak %s threads %s busy %s gain %s %s" % (
                    a.name, a.host, inst, row.get("notes_each"), rep, row["status"], row.get("xruns"), row.get("dsp_avg"),
                    row.get("peak_db"), row.get("threads_pct"), row.get("busy_threads"), row.get("gain"), row.get("note", "")))
                if row["status"] != "ok":
                    stop = "failed"
                    break
                if int(row["xruns"] or 0) > a.burst or float(row["dsp_avg"] or 0) > a.dsp_limit or mem_available_mb() < a.mem_floor:
                    stop = "limit"
            if stop:
                log("%s %s: the climb stops at %d instances, %d notes (%s)" % (a.name, a.host, inst, notes, stop))
                break
        if stop and "," not in a.instances:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())

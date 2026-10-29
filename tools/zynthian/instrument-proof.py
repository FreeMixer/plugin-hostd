#!/usr/bin/env python3
"""An instrument played through plugin-hostd (or jalv), and what it gives back: level, pitch, brightness, CPU per core.

    instrument-proof.py --out <dir> --host hostd --uri '<clap:...#id | lv2 uri>' [--port 5591] [--only a,b]
    instrument-proof.py --out <dir> --host jalv --uri '<lv2 uri>' [--only a,b]

It starts its own plugin-hostd on --port with a settings file of its own (no pins, its state, descriptors and
qualification records under <out>), or a jalv as Zynthian's jalv engine starts one (`jalv -i -n <name> <uri>`), adds
the instrument, links jack-instrument-probe (from this directory, built next to it) to the instrument's note input and
its first two audio outputs, and plays each scenario. Every window prints one line and is kept in <out>/windows.tsv:
level (peak and RMS dBFS), pitch (in_1's zero crossings per second), brightness, the server's xruns, JACK's DSP load,
the CPU of every core and of every thread of the host process (with the core it last ran on).

Scenarios: start (the time from the add to the ports), velocity, poly (1, 8, 16, 32 notes held), bend, sustain,
anoff (all notes off, by CC 123 and by the all_notes_off verb), mpe (a zone set by the MPE configuration message,
a member channel's bend), cc (the mod wheel, on a patch routing it to the filter: --cc-preset). Everything it starts
it stops, on any exit.
"""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.environ.get("INSTRUMENT_PROBE", os.path.join(HERE, "jack-instrument-probe"))
HZ = os.sysconf("SC_CLK_TCK")


def log(msg):
    print("instrument-proof: " + msg, file=sys.stderr, flush=True)


class hostd:
    """a plugin-hostd of this run's own on a private port, spoken to over the mod-host protocol"""

    def __init__(self, out, port, conf_extra):
        self.out, self.port = out, port
        conf = os.path.join(out, "plugin-hostd.conf")
        settings = {"mod_host": "/usr/local/bin/mod-host", "clap_host": "omx-clap-host", "lv2_worker": "omx-clap-host",
                    "require_pins": 0, "state_root": os.path.join(out, "state"),
                    "descriptor_dir": os.path.join(out, "descriptors"),
                    "qualification_dir": os.path.join(out, "qualification")}
        settings.update(conf_extra)
        with open(conf, "w") as f:
            for k, v in settings.items():
                f.write("%s %s\n" % (k, v))
        self.logf = open(os.path.join(out, "plugin-hostd.log"), "w+")
        self.proc = subprocess.Popen(["plugin-hostd", "-n", "-p", str(port), "-c", conf], stdout=self.logf,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        end = time.monotonic() + 15
        while time.monotonic() < end:
            self.logf.seek(0)
            if "plugin-hostd ready!" in self.logf.read():
                break
            time.sleep(0.05)
        else:
            raise SystemExit("plugin-hostd never said ready, see %s" % self.logf.name)
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.buf = b""

    def cmd(self, line, timeout=60):
        self.sock.settimeout(timeout)
        self.sock.sendall(line.encode() + b"\0")
        while b"\0" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise SystemExit("plugin-hostd closed the connection on: " + line)
            self.buf += chunk
        reply, _, self.buf = self.buf.partition(b"\0")
        reply = reply.decode(errors="replace")
        with open(os.path.join(self.out, "protocol.log"), "a") as f:
            f.write("> %s\n< %s\n" % (line, reply))
        return reply

    def pids(self):
        """the plugin-hostd process and its workers"""
        out = subprocess.run(["pgrep", "-g", str(self.proc.pid)], capture_output=True, text=True).stdout.split()
        return [int(p) for p in out]

    def close(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def jack_ports(prefix, flags):
    out = subprocess.run(["jack_lsp", "-p"], capture_output=True, text=True).stdout.splitlines()
    ports, cur = [], None
    for line in out:
        if not line.startswith("\t"):
            cur = line.strip()
        elif cur and cur.startswith(prefix + ":") and all(f in line for f in flags):
            ports.append(cur)
    return ports


def jack_types(port):
    out = subprocess.run(["jack_lsp", "-t", port], capture_output=True, text=True).stdout
    return out


def cpu_cores():
    cores = {}
    with open("/proc/stat") as f:
        for line in f:
            w = line.split()
            if w[0].startswith("cpu") and w[0] != "cpu":
                vals = [int(x) for x in w[1:]]
                cores[w[0]] = (sum(vals), vals[3] + vals[4])
    return cores


def cpu_threads(pids):
    th = {}
    for pid in pids:
        try:
            tids = os.listdir("/proc/%d/task" % pid)
        except OSError:
            continue
        for tid in tids:
            try:
                s = open("/proc/%d/task/%s/stat" % (pid, tid)).read()
            except OSError:
                continue
            comm = s[s.index("(") + 1:s.rindex(")")]
            w = s[s.rindex(")") + 2:].split()
            th["%d/%s/%s" % (pid, tid, comm.replace(" ", "_"))] = (int(w[11]) + int(w[12]), int(w[36]))
    return th


def dsp_load():
    """JACK's DSP load, from the venv's JACK client when there is one"""
    try:
        import jack
    except ImportError:
        return float("nan")
    c = jack.Client("inst_load", no_start_server=True)
    v = c.cpu_load()
    c.close()
    return v


class run:
    def __init__(self, a):
        self.a = a
        self.out = a.out
        self.rows = open(os.path.join(self.out, "windows.tsv"), "a")
        self.host = None
        self.jalv = None

    # ---- the instrument ----

    def start(self):
        a = self.a
        t0 = time.monotonic()
        if a.host == "hostd":
            self.host = hostd(self.out, a.port, {})
            t_ready = time.monotonic()
            reply = self.host.cmd("add %s 1" % a.uri, timeout=120)
            t_add = time.monotonic()
            if not reply.startswith("resp 1"):
                raise SystemExit("add refused: " + reply)
            self.client = "effect_1"
            self.extra_notes = []
            for n in range(2, a.instances + 1):
                r2 = self.host.cmd("add %s %d" % (a.uri, n), timeout=120)
                if not r2.startswith("resp %d" % n):
                    raise SystemExit("add %d refused: %s" % (n, r2))
                self.extra_notes.append("effect_%d:midi_in" % n)
            if a.instances > 1:
                self.row("instances", a.instances, self.host.cmd("worker_list"))
            note = self.host.cmd("note_input 1")
            self.note_port = None
            if note.startswith("resp 0 ") and note.split()[2] != "-":
                self.note_port = note.split()[2]
                if ":" not in self.note_port:
                    self.note_port = "%s:%s" % (self.client, self.note_port)
        else:
            self.client = "inst_jalv"
            # without -i jalv reads its console from stdin: "preset <uri>" is how Zynthian's jalv engine loads one
            self.jalv = subprocess.Popen(["jalv", "-n", self.client, a.uri], stdin=subprocess.PIPE, stdout=open(
                os.path.join(self.out, "jalv.log"), "w"), stderr=subprocess.STDOUT, start_new_session=True, text=True)
            self.extra_notes = []
            t_ready = t_add = t0
            self.note_port = None
        end = time.monotonic() + 60
        while time.monotonic() < end:
            self.outs = jack_ports(self.client, ["output"])
            audio_outs = [p for p in self.outs if "audio" in jack_types(p)]
            if len(audio_outs) >= 2:
                break
            time.sleep(0.02)
        else:
            raise SystemExit("the instrument's client %s has no audio outputs" % self.client)
        t_ports = time.monotonic()
        self.audio_outs = audio_outs[:2]
        if not self.note_port:
            ins = [p for p in jack_ports(self.client, ["input"]) if "midi" in jack_types(p)]
            self.note_port = ins[0] if ins else None
        if not self.note_port:
            raise SystemExit("the instrument has no note input")
        self.row("start", "add_ms", "%.0f" % ((t_add - t_ready) * 1000), "ports_ms", "%.0f" % ((t_ports - t0) * 1000),
                 "note_port", self.note_port, "outs", ",".join(self.audio_outs))
        log("started: %s, notes into %s, out %s" % (self.client, self.note_port, self.audio_outs))
        self.settle(1.0)

    def pids(self):
        if self.host:
            return self.host.pids()
        return [self.jalv.pid] if self.jalv else []

    def settle(self, s):
        time.sleep(s)

    def stop(self):
        if self.host:
            self.host.close()
        if self.jalv:
            try:
                os.killpg(self.jalv.pid, signal.SIGTERM)
                self.jalv.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

    def row(self, *cols):
        self.rows.write("\t".join(str(c) for c in (self.a.host,) + cols) + "\n")
        self.rows.flush()

    # ---- one scenario through the probe ----

    def play(self, name, steps):
        path = os.path.join(self.out, "scenario-%s.txt" % name)
        with open(path, "w") as f:
            f.write("\n".join(steps) + "\n")
        p = subprocess.Popen([PROBE, path, "inst_probe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if p.stdout.readline().strip() != "ready":
            raise SystemExit("the probe did not start")
        subprocess.run(["jack_connect", "inst_probe:midi_out", self.note_port], check=True)
        for extra in self.extra_notes:
            subprocess.run(["jack_connect", "inst_probe:midi_out", extra], check=True)
        for src, dst in zip(self.audio_outs, ("inst_probe:in_1", "inst_probe:in_2")):
            subprocess.run(["jack_connect", src, dst], check=True)
        p.stdin.write("go\n")
        p.stdin.flush()
        marks = {}
        results = {}
        for line in p.stdout:
            w = line.split()
            if not w:
                continue
            if w[0] == "mark":
                marks[w[1]] = (time.monotonic(), cpu_cores(), cpu_threads(self.pids()))
            elif w[0] == "window":
                label = w[1]
                t1, c1, th1 = time.monotonic(), cpu_cores(), cpu_threads(self.pids())
                t0, c0, th0 = marks[label]
                kv = dict(zip(w[2::2], w[3::2]))
                cores = []
                for k in sorted(c1):
                    tot = c1[k][0] - c0[k][0]
                    idle = c1[k][1] - c0[k][1]
                    cores.append("%s=%.0f" % (k, 100.0 * (tot - idle) / tot if tot else 0))
                threads = []
                for k, (ticks, core) in sorted(th1.items()):
                    d = ticks - th0.get(k, (ticks, 0))[0]
                    pct = 100.0 * d / HZ / (t1 - t0)
                    if pct >= 1.0:
                        threads.append("%s@cpu%d=%.0f" % (k.split("/", 2)[2], core, pct))
                load = dsp_load()
                kv.update({"dsp": "%.1f" % load, "cores": " ".join(cores), "threads": " ".join(threads)})
                results[label] = kv
                self.row(name, label, kv["peak"], kv["rms"], kv["hz"], kv["bright"], kv["xruns"], kv["dsp"],
                         kv["cores"], kv["threads"])
                log("%s %s: peak %s rms %s hz %s bright %s xruns %s dsp %s | %s | %s" % (
                    name, label, kv["peak"], kv["rms"], kv["hz"], kv["bright"], kv["xruns"], kv["dsp"], kv["cores"],
                    kv["threads"]))
            elif w[0] == "done":
                break
        p.wait(10)
        return results


def note_on(ch, key, vel):
    return "midi %x %x %x" % (0x90 | ch, key, vel)


def note_off(ch, key):
    return "midi %x %x 0" % (0x80 | ch, key)


def cc(ch, num, val):
    return "midi %x %x %x" % (0xb0 | ch, num, val)


def bend(ch, value14):
    return "midi %x %x %x" % (0xe0 | ch, value14 & 0x7f, (value14 >> 7) & 0x7f)


def silence_after(steps, ms=1500):
    steps += [cc(0, 123, 0), "wait %d" % ms]


def sc_velocity():
    s = ["wait 300"]
    for v in (20, 64, 127):
        s += [note_on(0, 60, v), "wait 300", "mark vel%d" % v, "wait 700", "end", note_off(0, 60), "wait 1200"]
    return s


def sc_poly(counts):
    s = ["wait 300", "mark idle", "wait 2000", "end"]
    for n in counts:
        keys = [36 + i for i in range(n)]
        s += [note_on(0, k, 100) for k in keys]
        s += ["wait 1000", "mark poly%d" % n, "wait 4000", "end"] + [note_off(0, k) for k in keys] + ["wait 2500"]
    return s


def sc_bend():
    s = ["wait 300", note_on(0, 69, 100), "wait 500", "mark centre", "wait 1000", "end",
         bend(0, 16383), "wait 200", "mark up", "wait 1000", "end",
         bend(0, 0), "wait 200", "mark down", "wait 1000", "end",
         bend(0, 8192), "wait 200", "mark back", "wait 1000", "end", note_off(0, 69), "wait 1500"]
    return s


def sc_sustain():
    s = ["wait 300", note_on(0, 60, 100), "wait 500", note_off(0, 60), "wait 1500", "mark released", "wait 500",
         "end", cc(0, 64, 127), "wait 100", note_on(0, 60, 100), "wait 500", note_off(0, 60), "wait 1500",
         "mark sustained", "wait 500", "end", cc(0, 64, 0), "wait 1500", "mark pedal_up", "wait 500", "end"]
    return s


def sc_anoff():
    keys = [48, 52, 55, 60, 64, 67, 72, 76]
    s = ["wait 300"] + [note_on(0, k, 100) for k in keys] + ["wait 500", "mark held", "wait 500", "end",
                                                             cc(0, 123, 0), "wait 1500", "mark after_cc123",
                                                             "wait 500", "end"]
    return s


def sc_mpe():
    # the MPE configuration message: RPN 6 on the manager channel (1, index 0), 15 member channels (channels 2-16)
    zone = [cc(0, 101, 0), cc(0, 100, 6), cc(0, 6, 15), cc(0, 101, 127), cc(0, 100, 127)]
    s = ["wait 300"] + zone + ["wait 200",
         note_on(1, 69, 100), "wait 500", "mark member_centre", "wait 1000", "end",
         bend(2, 16383), "wait 200", "mark other_member_bent", "wait 1000", "end", bend(2, 8192),
         bend(1, 8192 + 2048), "wait 200", "mark member_bent_quarter", "wait 1000", "end",
         bend(1, 8192), note_off(1, 69), "wait 1500"]
    return s


def sc_cc():
    s = ["wait 300", cc(0, 1, 0), note_on(0, 48, 100), "wait 800", "mark mw0", "wait 1500", "end",
         cc(0, 1, 127), "wait 300", "mark mw127", "wait 1500", "end", cc(0, 1, 0), "wait 300", "mark mw0_again",
         "wait 1500", "end", note_off(0, 48), "wait 1500"]
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host", choices=("hostd", "jalv"), required=True)
    ap.add_argument("--uri", required=True)
    ap.add_argument("--port", type=int, default=5591)
    ap.add_argument("--only", default="start,velocity,poly,bend,sustain,anoff,mpe,cc")
    ap.add_argument("--poly", default="1,8,16,32")
    ap.add_argument("--param", action="append", default=[], help="a param_set line's tail, sent after the add")
    ap.add_argument("--cc-preset", help="a patch routing the mod wheel: preset_load's word (hostd), an LV2 preset URI (jalv)")
    ap.add_argument("--instances", type=int, default=1, help="instances of the plugin, each fed the same notes (hostd)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    r = run(a)
    only = a.only.split(",")
    try:
        r.start()
        for p in a.param:
            sym = p.split()[0]
            before = r.host.cmd("param_get 1 %s" % sym)
            log("param_set 1 %s -> %s (before: %s, after: %s)" % (p, r.host.cmd("param_set 1 %s" % p), before,
                                                                  r.host.cmd("param_get 1 %s" % sym)))
            r.row("param", sym, before, p)
        if "velocity" in only:
            r.play("velocity", sc_velocity())
        if "poly" in only:
            r.play("poly", sc_poly([int(x) for x in a.poly.split(",")]))
        if "bend" in only:
            r.play("bend", sc_bend())
        if "sustain" in only:
            r.play("sustain", sc_sustain())
        if "anoff" in only:
            r.play("anoff", sc_anoff())
            if r.host:
                keys = [48, 52, 55, 60, 64, 67, 72, 76]
                steps = ["wait 300"] + [note_on(0, k, 100) for k in keys] + ["wait 500", "mark held_verb",
                                                                             "wait 500", "end", "wait 300"]
                # the verb is sent while the probe holds the notes: the probe's window after it reads the release
                steps += ["wait 1700", "mark after_verb", "wait 500", "end"]
                path = os.path.join(r.out, "scenario-anoff-verb.txt")
                open(path, "w").write("\n".join(steps) + "\n")
                p = subprocess.Popen([PROBE, path, "inst_probe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True)
                p.stdout.readline()
                subprocess.run(["jack_connect", "inst_probe:midi_out", r.note_port], check=True)
                for src, dst in zip(r.audio_outs, ("inst_probe:in_1", "inst_probe:in_2")):
                    subprocess.run(["jack_connect", src, dst], check=True)
                p.stdin.write("go\n")
                p.stdin.flush()
                for line in p.stdout:
                    w = line.split()
                    if w[:2] == ["window", "held_verb"]:
                        log("all_notes_off 1 -> %s" % r.host.cmd("all_notes_off 1"))
                    if w and w[0] == "window":
                        r.row("anoff-verb", *w[1:])
                        log("anoff-verb " + " ".join(w[1:]))
                    if w and w[0] == "done":
                        break
                p.wait(10)
        if "mpe" in only:
            r.play("mpe", sc_mpe())
        if "cc" in only and a.cc_preset:
            if a.cc_preset and r.host:
                reply = r.host.cmd("preset_load 1 %s" % a.cc_preset)
                log("preset_load -> %s" % reply)
                r.row("preset_load", a.cc_preset, reply)
                time.sleep(1.0)
            elif a.cc_preset:
                r.jalv.stdin.write("preset %s\n" % a.cc_preset)
                r.jalv.stdin.flush()
                r.row("preset", a.cc_preset)
                time.sleep(2.0)
            r.play("cc", sc_cc())
    finally:
        r.stop()
        shutil.rmtree(os.path.join(a.out, "state"), ignore_errors=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The Pi 5 stress run, on the device: chains of 4 plugins at rising counts, hosted three ways.

    stress-pi5.py --out <dir> [--port 5590] [--hold 60] [--levels 1,2,4,8,16] [--modes grouped,alone,jalv]

Run by tools/zynthian/stress-pi5.sh, which copies it to the device and brings <dir> back. It needs Zynthian's
Python (the JACK-Client module), the system JACK server, plugin-hostd and its start script from zynthian-sys.

Host modes, each at every level from scratch:
  grouped  plugin-hostd: the four members added, then declared one chain (the chain verb): one worker per chain
  alone    plugin-hostd: every member added with placement own, no chain: one worker per plugin
  jalv     one jalv process per plugin, as Zynthian's stock jalv engine runs an LV2 plugin

The members of a chain are linked in series from system:capture to system:playback. A level is held --hold seconds;
over the hold it samples /proc/stat per core and the JACK DSP load each second, counts xruns with a JACK client of
its own and from Zynthian's own counter in its journal, and at the end reads RSS and PSS per process group, the
worker list, the JACK client count and one capture of the screen. A mode stops climbing at the first level whose
busiest core averages over --cpu-limit percent, whose xruns exceed the baseline's by --burst, whose free memory falls
under --mem-floor MB, or after which the UI no longer answers. Everything this run starts it stops again.
"""
import argparse
import csv
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

import jack

OMX = ["urn:openmixer:eq8", "urn:openmixer:comp", "urn:openmixer:drive", "urn:openmixer:chorus",
       "urn:openmixer:delay", "urn:openmixer:reverb", "urn:openmixer:limiter"]
# LV2 plugins of other projects whose qualification record on this device rates them suitable in process
THIRD = ["http://distrho.sf.net/plugins/3BandEQ", "http://calf.sourceforge.net/plugins/Compressor",
         "http://calf.sourceforge.net/plugins/Saturator", "http://calf.sourceforge.net/plugins/MultiChorus",
         "http://calf.sourceforge.net/plugins/VintageDelay", "http://distrho.sf.net/plugins/MaFreeverb",
         "http://gareus.org/oss/lv2/dpl#stereo"]
FIRST_INSTANCE = 7000
START_SCRIPT = "/zynthian/zynthian-sys/sbin/plugin-hostd-start.sh"
ENVARS = "/zynthian/config/zynthian_envars.sh"
QUALIFICATION = "/var/lib/omx/qualification"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sh(cmd, timeout=30):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return None


def lv2_path():
    with open(ENVARS) as f:
        for line in f:
            m = re.match(r'^export LV2_PATH="?([^"\n]*)"?', line)
            if m:
                return m.group(1)
    return "/usr/lib/lv2:/usr/local/lib/lv2"


def chain_members(c):
    """chain c (0-based): even chains are omx-plugins, odd ones other projects' plugins, four consecutive of seven"""
    pool = OMX if c % 2 == 0 else THIRD
    k = (c // 2) % len(pool)
    return [pool[(k + j) % len(pool)] for j in range(4)]


# ---- /proc readings ----

def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if re.match(r"^cpu\d", line):
                p = line.split()
                v = list(map(int, p[1:]))
                idle = v[3] + v[4]
                out[p[0]] = (sum(v), idle)
    return out


def busy(a, b):
    res = {}
    for k in sorted(a):
        tot = b[k][0] - a[k][0]
        idl = b[k][1] - a[k][1]
        res[k] = 100.0 * (tot - idl) / tot if tot > 0 else 0.0
    return res


def proc_ticks():
    """pid -> (utime + stime in clock ticks, name, cmdline head) of every process"""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                raw = f.read()
            name = raw[raw.index("(") + 1:raw.rindex(")")]
            rest = raw.rsplit(")", 1)[1].split()
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()[:120]
            out[int(d)] = (int(rest[11]) + int(rest[12]), name, cmd)
        except (OSError, ValueError, IndexError):
            continue
    return out


def top_consumers(a, b, seconds, n=8):
    """the processes that used the most CPU between two proc_ticks readings, in percent of one core"""
    hz = os.sysconf("SC_CLK_TCK")
    used = []
    for pid, (t, name, cmd) in b.items():
        t0 = a.get(pid, (0, None, None))[0] if a.get(pid, (0, name))[1] == name else 0
        used.append((100.0 * (t - t0) / hz / seconds, pid, name, cmd))
    used.sort(reverse=True)
    return [{"pid": pid, "name": name, "cmd": cmd, "cpu_pct_of_core": round(pct, 1)} for pct, pid, name, cmd in used[:n]]


def cpu_mhz():
    out = {}
    for c in range(os.cpu_count() or 4):
        try:
            with open(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq") as f:
                out[f"mhz{c}"] = int(f.read()) // 1000
        except OSError:
            pass
    return out


def mem_available_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024.0
    return None


def procs():
    """pid -> (ppid, cmdline)"""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            with open(f"/proc/{d}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            out[int(d)] = (ppid, cmd)
        except (OSError, IndexError, ValueError):
            continue
    return out


def mem_of(pid):
    """(rss MB, pss MB) of one process; None when it is gone"""
    try:
        rss = pss = 0
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Rss:"):
                    rss = int(line.split()[1])
                elif line.startswith("Pss:"):
                    pss = int(line.split()[1])
        return rss / 1024.0, pss / 1024.0
    except OSError:
        return None


def descendants(table, root):
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        kids = [c for c, (pp, _) in table.items() if pp == p]
        out += kids
        todo += kids
    return out


def groups(daemon_pid, jalv_pids):
    """process group -> [pids]: Zynthian's UI, the system JACK server, the daemon, its workers, the jalv processes"""
    t = procs()
    g = {"zynthian": [p for p, (_, c) in t.items() if "zynthian_main.py" in c],
         "jackd": [p for p, (_, c) in t.items() if c.startswith("/usr/bin/jackd ")],
         "plugin-hostd": [daemon_pid] if daemon_pid and daemon_pid in t else [],
         "workers": descendants(t, daemon_pid) if daemon_pid and daemon_pid in t else [],
         "jalv": [p for p in jalv_pids if p in t]}
    return g


def memory(daemon_pid, jalv_pids):
    out = {}
    for name, pids in groups(daemon_pid, jalv_pids).items():
        rss = pss = 0.0
        for p in pids:
            m = mem_of(p)
            if m:
                rss += m[0]
                pss += m[1]
        out[name] = {"processes": len(pids), "rss_mb": round(rss, 1), "pss_mb": round(pss, 1)}
    return out


def zynthian_xruns():
    """the last count Zynthian's own xrun callback wrote to its journal (zynthian_autoconnect.cb_jack_xrun)"""
    out = sh("journalctl -u zynthian -o cat --no-pager -n 20000 | grep -o 'XRUN! =>count: [0-9]*' | tail -1", 20)
    m = re.search(r"(\d+)\s*$", out or "")
    return int(m.group(1)) if m else 0


def zynthian_pid():
    for p, (_, c) in procs().items():
        if "zynthian_main.py" in c:
            return p
    return None


def jack_clients():
    out = sh("jack_lsp | cut -d: -f1 | sort -u | wc -l", 20)
    return int(out.strip()) if out and out.strip().isdigit() else None


def capture(path):
    """one capture of the UI's screen; False when the X server did not answer within 15 s"""
    env = "DISPLAY=:0 XAUTHORITY=/root/.Xauthority"
    r = subprocess.run(f"{env} timeout 15 scrot -o {path}", shell=True, capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


def ui_answers(pid0, shots):
    """the UI answers: Zynthian's process is the one the run started with and is not stopped or in an uninterruptible
    wait, and the X server gave a capture; shots is the capture's result"""
    pid = zynthian_pid()
    state = None
    if pid:
        try:
            with open(f"/proc/{pid}/stat") as f:
                state = f.read().rsplit(")", 1)[1].split()[0]
        except OSError:
            pass
    ok = pid is not None and pid == pid0 and state not in ("T", "D", "Z") and shots
    return ok, {"zynthian_pid": pid, "state": state, "capture": shots}


# ---- plugin-hostd ----

class Daemon:
    def __init__(self, port, env):
        self.port = port
        self.pid = None
        self.started = False
        out = subprocess.run([START_SCRIPT, str(port)], capture_output=True, text=True, timeout=30, env=env,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        if out.returncode != 0:
            raise RuntimeError(f"{START_SCRIPT} {port}: {out.stderr.strip()}")
        if out.stdout.strip().isdigit():
            self.pid = int(out.stdout.strip())
            self.started = True
        else:
            pids = sh(f"pgrep -f '^(/usr/bin/)?plugin-hostd .*-p {port}( |$)'").split()
            self.pid = int(pids[0]) if pids else None
        # the start script returns at the daemon's ready line; on this device the first connect right after it was
        # once refused, so the connect is retried for 10 s and the wait recorded
        t0 = time.monotonic()
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=60)
                break
            except ConnectionRefusedError:
                if time.monotonic() - t0 > 10:
                    raise
                time.sleep(0.1)
        self.connect_wait_s = round(time.monotonic() - t0, 2)

    def call(self, line, timeout=60):
        self.sock.settimeout(timeout)
        self.sock.sendall(line.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            d = self.sock.recv(65536)
            if not d:
                raise OSError("daemon closed the connection")
            buf += d
        reply = buf.rstrip(b"\0").decode()
        parts = reply.split(" ", 2)
        code = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
        return code, reply

    def workers(self):
        _, reply = self.call("worker_list")
        recs = reply.split()[2:]
        out = []
        for r in recs:
            f = r.split(":")
            insts = [int(i) for i in f[-1].split(",") if i.isdigit()]
            out.append({"worker": f[0], "pid": f[1], "row": f[2], "state": f[3], "place": ":".join(f[4:-1]),
                        "instances": insts})
        return out

    def stop(self):
        try:
            self.sock.close()
        except OSError:
            pass
        if self.started and self.pid:
            os.kill(self.pid, signal.SIGTERM)
            for _ in range(100):
                if not os.path.exists(f"/proc/{self.pid}"):
                    return True
                time.sleep(0.1)
            os.kill(self.pid, signal.SIGKILL)
        return not (self.pid and os.path.exists(f"/proc/{self.pid}"))


# ---- the run ----

class Run:
    def __init__(self, a):
        self.a = a
        self.out = a.out
        os.makedirs(os.path.join(self.out, "captures"), exist_ok=True)
        os.makedirs(os.path.join(self.out, "levels"), exist_ok=True)
        os.makedirs(os.path.join(self.out, "logs"), exist_ok=True)
        self.env = dict(os.environ, LV2_PATH=lv2_path())
        self.meter = jack.Client("omx_stress_meter", no_start_server=True)
        self.xruns = 0
        self.meter.set_xrun_callback(self.on_xrun)
        self.meter.activate()
        self.daemon = None
        self.jalv = []
        self.zpid = zynthian_pid()
        self.summary = []

    def on_xrun(self, delay):
        self.xruns += 1

    def ports(self, client, out, audio=True):
        return [p.name for p in self.meter.get_ports(f"^{re.escape(client)}:", is_audio=audio,
                                                     is_output=out, is_input=not out)]

    def link_series(self, clients):
        """system:capture -> clients in order -> system:playback, port by port"""
        made = 0
        chain = ["system"] + clients + ["system"]
        for src, dst in zip(chain, chain[1:]):
            outs = self.ports(src, True) if src != "system" else ["system:capture_1", "system:capture_2"]
            ins = self.ports(dst, False) if dst != "system" else ["system:playback_1", "system:playback_2"]
            for o, i in zip(outs, ins):
                try:
                    self.meter.connect(o, i)
                    made += 1
                except jack.JackError:
                    pass
        return made

    def has_client(self, name):
        return bool(self.meter.get_ports(f"^{re.escape(name)}:"))

    def wait_up(self, instances, timeout=90):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ws = self.daemon.workers()
            running = {i for w in ws if w["state"] == "up" for i in w["instances"]}
            if set(instances) <= running and all(self.has_client(f"effect_{i}") or
                                                 any(i in w["instances"] and w["place"].startswith("chain")
                                                     for w in ws) for i in instances):
                return True
            time.sleep(0.1)
        return False

    def build(self, mode, n):
        """build n chains; returns (chains: [[jack client, ...]], per-chain seconds, refusals, stopped-for)"""
        chains, secs, refused, stop = [], [], [], None
        for c in range(n):
            if mem_available_mb() < self.a.mem_floor:
                stop = "memory"
                break
            uris = chain_members(c)
            t0 = time.monotonic()
            if mode == "jalv":
                names = []
                for j, uri in enumerate(uris):
                    name = f"jalv_{c:02d}_{j}"
                    lf = open(os.path.join(self.out, "logs", f"{name}.log"), "w")
                    p = subprocess.Popen(["jalv", "-i", "-n", name, uri], stdin=subprocess.DEVNULL, stdout=lf,
                                         stderr=subprocess.STDOUT, env=self.env, start_new_session=True)
                    self.jalv.append(p)
                    names.append((name, uri, p))
                end = time.monotonic() + 60
                while time.monotonic() < end and not all(self.has_client(nm) or q.poll() is not None
                                                         for nm, _, q in names):
                    time.sleep(0.05)
                members = [nm for nm, _, _ in names]
                refused += [{"uri": u, "why": f"jalv exited {q.returncode}" if q.poll() is not None else "no client"}
                            for nm, u, q in names if not self.has_client(nm)]
            else:
                insts = []
                for j, uri in enumerate(uris):
                    inst = FIRST_INSTANCE + 4 * c + j
                    line = f"add {uri} {inst}" + (" own" if mode == "alone" else "")
                    code, reply = self.daemon.call(line, 60)
                    if code == inst:
                        insts.append(inst)
                    else:
                        refused.append({"uri": uri, "why": reply})
                if mode == "grouped" and insts:
                    code, reply = self.daemon.call(f"chain {c + 1} {' '.join(map(str, insts))}", 60)
                    if code != 0:
                        refused.append({"chain": c + 1, "why": reply})
                self.wait_up(insts)
                members = [f"effect_{i}" for i in insts]
            secs.append(time.monotonic() - t0)
            chains.append(members)
        # the clients are read once the level has settled: a client's ports come after the client, and a chain's
        # members leave the clients of their own workers when the chain's worker takes them
        time.sleep(2.0)
        chains = [[m for m in members if self.ports(m, True) and self.ports(m, False)] for members in chains]
        return chains, secs, refused, stop

    def teardown(self, mode, n):
        if mode == "jalv":
            for p in self.jalv:
                if p.poll() is None:
                    p.terminate()
            # jalv -i does not end on SIGTERM on this device: all of them get 10 s together, then SIGKILL
            end = time.monotonic() + 10
            while time.monotonic() < end and any(p.poll() is None for p in self.jalv):
                time.sleep(0.1)
            killed = [p for p in self.jalv if p.poll() is None]
            for p in killed:
                p.kill()
            for p in killed:
                p.wait(5)
            self.jalv_killed = len(killed)
            self.jalv = []
            return True
        for c in range(n):
            if mode == "grouped":
                self.daemon.call(f"chain_clear {c + 1}", 60)
        for c in range(n):
            for j in range(4):
                self.daemon.call(f"remove {FIRST_INSTANCE + 4 * c + j}", 60)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            mine = [w for w in self.daemon.workers() if any(i >= FIRST_INSTANCE for i in w["instances"])]
            if not mine:
                return True
            time.sleep(0.2)
        return False

    def hold(self, tag):
        """sample the hold; returns the per-second rows and the readings at its end"""
        rows = []
        with open(os.path.join(self.out, "holding"), "w") as f:
            f.write(tag + "\n")  # stress-pi5.sh takes the MOD-UI capture of the level while this names it
        x0, z0 = self.xruns, zynthian_xruns()
        ticks0, mono0 = proc_ticks(), time.monotonic()
        prev = cpu_times()
        t_end = time.monotonic() + self.a.hold
        while time.monotonic() < t_end:
            time.sleep(1.0)
            cur = cpu_times()
            b = busy(prev, cur)
            prev = cur
            row = {"t": round(self.a.hold - (t_end - time.monotonic()), 1), "jack_dsp": round(self.meter.cpu_load(), 2),
                   "mem_avail_mb": round(mem_available_mb(), 1), "xruns": self.xruns - x0}
            row.update({k: round(v, 1) for k, v in b.items()})
            row.update(cpu_mhz())
            rows.append(row)
        top = top_consumers(ticks0, proc_ticks(), time.monotonic() - mono0)
        os.unlink(os.path.join(self.out, "holding"))
        with open(os.path.join(self.out, "levels", f"{tag}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        cores = [k for k in rows[0] if k.startswith("cpu")]
        means = {k: sum(r[k] for r in rows) / len(rows) for k in cores}
        return {"top_consumers": top, "mhz_mean": round(sum(r.get("mhz0", 0) for r in rows) / len(rows)),
                "xruns_meter": self.xruns - x0, "xruns_zynthian": zynthian_xruns() - z0,
                "cpu_core_mean": {k: round(v, 1) for k, v in means.items()},
                "cpu_busiest_core": round(max(means.values()), 1),
                "cpu_mean": round(sum(means.values()) / len(means), 1),
                "cpu_busiest_second": round(max(max(r[k] for k in cores) for r in rows), 1),
                "jack_dsp_mean": round(sum(r["jack_dsp"] for r in rows) / len(rows), 2),
                "jack_dsp_max": round(max(r["jack_dsp"] for r in rows), 2),
                "mem_avail_min_mb": min(r["mem_avail_mb"] for r in rows)}

    def level(self, mode, n, baseline_xruns):
        tag = f"{mode}-{n:02d}"
        log(f"level {tag}: building")
        chains, secs, refused, stop = self.build(mode, n)
        links = sum(self.link_series(cl) for cl in chains if cl)
        workers = self.daemon.workers() if mode != "jalv" else []
        mine = [w for w in workers if any(i >= FIRST_INSTANCE for i in w["instances"])]
        log(f"level {tag}: {len(chains)} chains in {sum(secs):.1f} s, {len(mine)} workers, {links} links; holding")
        h = self.hold(tag)
        shot = os.path.join(self.out, "captures", f"l{n:02d}-{mode}-zynthian.png")
        ok, ui = ui_answers(self.zpid, capture(shot))
        mem = memory(self.daemon.pid if self.daemon else None, [p.pid for p in self.jalv])
        rec = {"mode": mode, "chains_asked": n, "chains_built": len(chains),
               "plugins_running": sum(len(cl) for cl in chains) if mode == "jalv" else
               sum(len(w["instances"]) for w in mine),
               "jack_clients_of_chains": sum(len(cl) for cl in chains),
               "creation_s_total": round(sum(secs), 2),
               "creation_s_per_chain": round(sum(secs) / len(secs), 3) if secs else None,
               "workers_mine": len(mine), "workers": mine, "links": links, "refused": refused,
               "jack_clients": jack_clients(), "memory": mem,
               "rss_total_mb": round(sum(v["rss_mb"] for v in mem.values()), 1),
               "pss_total_mb": round(sum(v["pss_mb"] for v in mem.values()), 1),
               "ui": ui, "capture": os.path.basename(shot) if ui["capture"] else None,
               "modui_active": (sh("systemctl is-active mod-ui") or "").strip(), **h}
        limit = None
        if stop:
            limit = stop
        elif not ok:
            limit = "ui"
        elif h["cpu_busiest_core"] > self.a.cpu_limit:
            limit = "cpu"
        elif h["xruns_meter"] > baseline_xruns + self.a.burst:
            limit = "xruns"
        elif h["mem_avail_min_mb"] < self.a.mem_floor:
            limit = "memory"
        rec["limit"] = limit
        log(f"level {tag}: busiest {h['cpu_busiest_core']}% mean {h['cpu_mean']}% xruns {h['xruns_meter']} "
            f"rss {rec['rss_total_mb']} MB limit {limit}")
        self.jalv_killed = 0
        rec["teardown_clean"] = self.teardown(mode, n)
        rec["jalv_killed_after_sigterm"] = self.jalv_killed
        with open(os.path.join(self.out, "levels", f"{tag}.json"), "w") as f:
            json.dump(rec, f, indent=1)
        self.summary.append(rec)
        return limit

    def baseline(self):
        log("baseline: holding")
        h = self.hold("baseline")
        shot = os.path.join(self.out, "captures", "l00-baseline-zynthian.png")
        ok, ui = ui_answers(self.zpid, capture(shot))
        mem = memory(None, [])
        rec = {"mode": "baseline", "chains_asked": 0, "chains_built": 0, "plugins_running": 0, "workers_mine": 0,
               "jack_clients": jack_clients(), "memory": mem, "creation_s_total": None,
               "rss_total_mb": round(sum(v["rss_mb"] for v in mem.values()), 1),
               "pss_total_mb": round(sum(v["pss_mb"] for v in mem.values()), 1), "ui": ui,
               "capture": os.path.basename(shot) if ui["capture"] else None, "limit": None, **h}
        with open(os.path.join(self.out, "levels", "baseline.json"), "w") as f:
            json.dump(rec, f, indent=1)
        self.summary.append(rec)
        log(f"baseline: busiest {h['cpu_busiest_core']}% xruns {h['xruns_meter']} rss {rec['rss_total_mb']} MB")
        return h["xruns_meter"]

    def run(self):
        base = self.baseline()
        reached = {}
        for mode in self.a.modes:
            if mode in ("grouped", "alone") and not self.daemon:
                self.daemon = Daemon(self.a.port, self.env)
                log(f"plugin-hostd on {self.a.port}: pid {self.daemon.pid}, started here: {self.daemon.started}, "
                    f"first connect after {self.daemon.connect_wait_s} s")
            reached[mode] = {"levels": [], "limit": None}
            for n in self.a.levels:
                limit = self.level(mode, n, base)
                reached[mode]["levels"].append(n)
                if limit:
                    reached[mode]["limit"] = {"level": n, "by": limit}
                    break
            if mode == "alone" or (mode == "grouped" and "alone" not in self.a.modes):
                if self.daemon:
                    leftover = [w for w in self.daemon.workers() if any(i >= FIRST_INSTANCE for i in w["instances"])]
                    reached["daemon_clean"] = not leftover
                    reached["daemon_stopped"] = self.daemon.stop()
                    self.daemon = None
        self.meter.deactivate()
        self.meter.close()
        with open(os.path.join(self.out, "summary.json"), "w") as f:
            json.dump({"reached": reached, "baseline_xruns": base, "levels": self.summary}, f, indent=1)
        return reached


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=5590)
    ap.add_argument("--hold", type=float, default=60)
    ap.add_argument("--levels", type=lambda s: [int(x) for x in s.split(",")], default=[1, 2, 4, 8, 16])
    ap.add_argument("--modes", type=lambda s: s.split(","), default=["grouped", "alone", "jalv"])
    ap.add_argument("--cpu-limit", type=float, default=85.0)
    ap.add_argument("--burst", type=int, default=3)
    ap.add_argument("--mem-floor", type=float, default=400.0)
    a = ap.parse_args()
    r = Run(a)
    try:
        print(json.dumps(r.run(), indent=1))
    finally:
        for p in r.jalv:
            if p.poll() is None:
                p.kill()
        if r.daemon:
            r.daemon.stop()


if __name__ == "__main__":
    sys.exit(main())

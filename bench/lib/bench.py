"""The benchmark runner behind bench/run.sh: four plugin hosts, one private JACK server per rate and frame count,
one omx-bench/1 document per run. bench/README.md says what each scenario measures."""

import argparse
import ctypes
import datetime
import glob
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
HOSTS = ("H1", "H2", "H3", "H4")
HOST_PROGRAM = {"H1": "omx-clap-host", "H2": "plugin-hostd", "H3": "mod-host", "H4": "jalv"}
MARK = "OMX_BENCH_RUN"
TAG = "omx-bench-%d" % os.getpid()
RECOVER_LIMIT_S = 30.0
READY_LIMIT_S = 20.0
POOL_MAX = 8  # plugin-hostd's pool_max: a full pool opens a second one, which these rows do not read


def log(msg):
    print("bench: " + msg, file=sys.stderr, flush=True)


class Refused(Exception):
    """a row that cannot run here: status unsupported, the message is the note"""


class Failed(Exception):
    """a row that ran and broke: status failed, the message is the note"""


# ---------------------------------------------------------------- processes


class Procs:
    """every process the run starts: each in a session of its own, each marked with MARK so the last check finds
    any that outlives the teardown, whoever its parent is by then"""

    def __init__(self, logdir, server):
        self.logdir = logdir
        self.server = server
        self.live = []
        self.env = dict(os.environ)
        self.env[MARK] = TAG
        self.env["JACK_DEFAULT_SERVER"] = server
        self.env["JACK_NO_AUDIO_RESERVATION"] = "1"

    def spawn(self, argv, name, env=None, stdin=subprocess.DEVNULL):
        e = dict(self.env)
        e.update(env or {})
        out = open(os.path.join(self.logdir, name + ".log"), "ab")
        p = subprocess.Popen(argv, stdin=stdin, stdout=out, stderr=subprocess.STDOUT, env=e, start_new_session=True)
        out.close()
        p.name = name
        self.live.append(p)
        return p

    def stop(self, p, grace=3.0):
        """SIGTERM to the process group and every descendant, SIGKILL to what is left after grace"""
        if p not in self.live:
            return
        self.live.remove(p)
        group = [p.pid] + descendants(p.pid)
        signal_all(p.pid, group, signal.SIGTERM)
        end = time.monotonic() + grace
        while time.monotonic() < end and any(alive(q) for q in group):
            reap()
            time.sleep(0.02)
        signal_all(p.pid, group, signal.SIGKILL)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        reap()

    def stop_all(self):
        for p in list(reversed(self.live)):
            self.stop(p)


def signal_all(pgid, pids, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    for q in pids:
        try:
            os.kill(q, sig)
        except (ProcessLookupError, PermissionError):
            pass


def alive(pid):
    """running and not a zombie"""
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def reap():
    """collect exited children, orphans included: the runner is the subreaper of everything it starts"""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def stop_strays(found):
    """SIGTERM first, so a JACK server takes its shared memory with it and the next one starts; SIGKILL after 3 s"""
    pids = [p for p, _ in found]
    for sig, grace in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass
        end = time.monotonic() + grace
        while time.monotonic() < end and any(alive(p) for p in pids):
            reap()
            time.sleep(0.02)
    reap()


def ppid_map():
    m = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/stat" % d) as f:
                    m[int(d)] = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                pass
    return m


def descendants(pid):
    m = ppid_map()
    out, todo = [], [pid]
    while todo:
        cur = todo.pop()
        kids = [c for c, pp in m.items() if pp == cur]
        out += kids
        todo += kids
    return out


def marked():
    """(pid, command) of every live process carrying this run's mark"""
    found = []
    needle = ("%s=%s" % (MARK, TAG)).encode()
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == os.getpid():
            continue
        try:
            with open("/proc/%s/environ" % d, "rb") as f:
                if needle not in f.read().split(b"\0"):
                    continue
            if not alive(int(d)):
                continue
            with open("/proc/%s/comm" % d) as f:
                found.append((int(d), f.read().strip()))
        except OSError:
            pass
    return found


# ---------------------------------------------------------------- /proc measurements


def proc_sample(pid):
    """utime+stime ticks, RSS kB, PSS kB, voluntary and involuntary context switches of one process"""
    with open("/proc/%d/stat" % pid) as f:
        fields = f.read().rsplit(")", 1)[1].split()
    ticks = int(fields[11]) + int(fields[12])
    rss = int(fields[21]) * PAGE_KB
    pss = 0
    try:
        with open("/proc/%d/smaps_rollup" % pid) as f:
            for line in f:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1])
    except OSError:
        pss = None
    # a process's status counts its main thread only: the switches are summed over its threads
    vol = invol = 0
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
    return {"ticks": ticks, "rss": rss, "pss": pss, "vol": vol, "invol": invol}


def samples(pids):
    out = {}
    for pid in pids:
        try:
            out[pid] = proc_sample(pid)
        except (OSError, IndexError, ValueError):
            pass
    return out


# ---------------------------------------------------------------- repeats

MEASURED = ("dsp_load_avg", "dsp_load_max", "rss_mb", "add_ms", "recover_ms", "processes", "rss_mb_total",
            "pss_mb_total", "cpu_pct", "ctx_switches", "ctx_involuntary", "xruns", "latency_frames", "jack_clients")
COUNTS = ("processes", "ctx_switches", "ctx_involuntary", "xruns", "latency_frames", "samples", "jack_clients")


def aggregate(runs, wanted=None):
    """one row from the repeats of one row: the median of every measure and, for each, its [min, max] under
    `spread`. A count stays a count: with an even number of runs it takes the higher middle one, so a number of xruns
    is never understated. A run that is failed ends it: that run's row, naming the repeat of `wanted`, and no figures
    from the runs before it; one that is unsupported ends it as it is."""
    for n, run in enumerate(runs, 1):
        if run["status"] != "ok":
            row = dict(run)
            if row["status"] == "failed" and (wanted or len(runs)) > 1:
                row["note"] = "repeat %d of %d: %s" % (n, wanted or len(runs), row["note"])
            return row
    row = dict(runs[0])
    row["repeats"] = len(runs)
    if len(runs) == 1:
        return row
    spread = {}
    for key in MEASURED + ("samples",):
        vals = [r[key] for r in runs if r.get(key) is not None]
        if len(vals) != len(runs):
            continue
        if key in COUNTS:
            row[key] = int(statistics.median_high(vals))
        else:
            row[key] = round(statistics.median(vals), 2)
        if key != "samples":
            spread[key] = [min(vals), max(vals)]
    row["spread"] = spread
    notes = list(dict.fromkeys(r["note"] for r in runs if r["note"]))
    row["note"] = "; ".join(notes)
    return row


# ---------------------------------------------------------------- the stress load

STRESS_MEM_MB = 256
# one busy loop per core, each pinned to its core; one process that keeps touching a buffer of a fixed size
BUSY_CODE = "import os, sys\nos.sched_setaffinity(0, {int(sys.argv[1])})\nwhile True:\n    pass\n"
MEM_CODE = ("import sys, time\nbuf = bytearray(int(sys.argv[1]) << 20)\nwhile True:\n"
            "    for i in range(0, len(buf), 4096):\n        buf[i] = (buf[i] + 1) & 255\n    time.sleep(0.1)\n")


def stress_cores():
    """the cores the host may run on: the stress sits on every one of them"""
    return sorted(os.sched_getaffinity(0))


def stress_profile(cores):
    """the name a row carries: the same name on the same machine means the same load"""
    return "busy%d+mem%d" % (len(cores), STRESS_MEM_MB)


def stress_argvs(cores, mem_mb=STRESS_MEM_MB):
    """[(process name, argv)] of the load: a busy loop pinned to each core, and the memory touch"""
    out = [("stress-busy-%d" % c, [sys.executable, "-I", "-c", BUSY_CODE, str(c)]) for c in cores]
    out.append(("stress-mem", [sys.executable, "-I", "-c", MEM_CODE, str(mem_mb)]))
    return out


# ---------------------------------------------------------------- JACK


def run(argv, env, timeout=10):
    return subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                          timeout=timeout).stdout


def ports(env):
    """{client: {"audio_in": [...], "audio_out": [...], "midi_in": [...]}} from jack_lsp, in port order"""
    out, port = {}, None
    props = ""
    for line in run(["jack_lsp", "-p", "-t"], env).splitlines():
        if not line.startswith((" ", "\t")):
            port, props = line.strip(), ""
            continue
        text = line.strip()
        if text.startswith("properties:"):
            props = text
            continue
        if port is None:
            continue
        kind = "audio" if "audio" in text else "midi" if "midi" in text else None
        if kind:
            direction = "in" if "input" in props else "out"
            client = port.split(":", 1)[0]
            out.setdefault(client, {}).setdefault("%s_%s" % (kind, direction), []).append(port)
    return out


def connected(env, a, b):
    return b in run(["jack_lsp", "-c", a], env).split()


class JackProbe:
    """a JACK client of the private server that counts its xruns and reads the latency JACK reports. It registers no
    port and no process callback, so it adds nothing to the cycle it watches. `lib` is libjack, or a stand-in in the
    unit tests."""

    NO_START = 0x01  # JackNoStartServer
    SERVER_NAME = 0x04  # JackServerName
    CAPTURE = 0  # JackCaptureLatency

    class Range(ctypes.Structure):
        _fields_ = [("min", ctypes.c_uint32), ("max", ctypes.c_uint32)]

    def __init__(self, server, lib=None, name="omx-bench-probe"):
        if lib is None:
            for so in ("libjack.so.0", "libjack.so"):
                try:
                    lib = ctypes.CDLL(so, use_errno=True)
                    break
                except OSError:
                    pass
            else:
                raise SystemExit("bench: libjack is needed to count xruns (package jackd2)")
        self.lib = lib
        self.total = 0
        self._bind()
        status = ctypes.c_int(0)
        self.client = lib.jack_client_open(name.encode(), self.NO_START | self.SERVER_NAME, ctypes.byref(status),
                                           server.encode())
        if not self.client:
            raise SystemExit("bench: cannot open a JACK client on server %s (status %d)" % (server, status.value))
        self._callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(self._on_xrun)
        if lib.jack_set_xrun_callback(self.client, self._callback, None) != 0:
            raise SystemExit("bench: cannot set the xrun callback on server %s" % server)
        if lib.jack_activate(self.client) != 0:
            raise SystemExit("bench: cannot activate the xrun probe on server %s" % server)

    def _bind(self):
        lib = self.lib
        vp, ci = ctypes.c_void_p, ctypes.c_int
        for name, res, args in (
                ("jack_client_open", vp, [ctypes.c_char_p, ci, ctypes.POINTER(ci), ctypes.c_char_p]),
                ("jack_set_xrun_callback", ci, [vp, vp, vp]),
                ("jack_activate", ci, [vp]),
                ("jack_deactivate", ci, [vp]),
                ("jack_client_close", ci, [vp]),
                ("jack_port_by_name", vp, [vp, ctypes.c_char_p]),
                ("jack_recompute_total_latencies", ci, [vp]),
                ("jack_port_get_latency_range", None, [vp, ci, ctypes.POINTER(self.Range)])):
            fn = getattr(lib, name)
            try:
                fn.restype, fn.argtypes = res, args
            except AttributeError:
                pass  # a stand-in function, not a ctypes one

    def _on_xrun(self, _arg):
        self.total += 1
        return 0

    def count(self):
        """xruns since the probe opened"""
        return self.total

    def latency_frames(self, port):
        """the capture latency JACK reports at an input port, in frames, the longest of its range: the delay from
        the sources to the port as the clients on the path declared it; None when the port is not there"""
        p = self.lib.jack_port_by_name(self.client, port.encode())
        if not p:
            return None
        self.lib.jack_recompute_total_latencies(self.client)
        rng = self.Range()
        self.lib.jack_port_get_latency_range(p, self.CAPTURE, ctypes.byref(rng))
        return int(rng.max)

    def close(self):
        if self.client:
            self.lib.jack_deactivate(self.client)
            self.lib.jack_client_close(self.client)
            self.client = None


def log_size(logdir, name):
    try:
        return os.path.getsize(os.path.join(logdir, name + ".log"))
    except OSError:
        return 0


def log_since(logdir, name, start):
    """what a host wrote to its log after byte start"""
    try:
        with open(os.path.join(logdir, name + ".log"), "rb") as f:
            f.seek(start)
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def jack_log_xruns(path, offset):
    """lines of the JACK server's own log from offset on that name an xrun, and the new end of the file"""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return 0, offset
    return sum(1 for line in raw.decode(errors="replace").splitlines() if "xrun" in line.lower()), offset + len(raw)


def window_xruns(counted, logged):
    """the xruns of one window: what the probe counted, unless the server's own log names xruns the probe never
    heard, which would mean the probe is deaf and every row would read 0"""
    if counted == 0 and logged > 0:
        raise Failed("jackd logged %d xrun line(s) in the window and the probe counted none" % logged)
    return counted


# ---------------------------------------------------------------- the protocol


class Control:
    """one controller connection to a mod-host protocol port, held for the life of the host, as a controller holds
    it: NUL-terminated lines, one reply each (the same framing as lib/send.sh)"""

    def __init__(self, port, proc, limit_s=READY_LIMIT_S):
        end = time.monotonic() + limit_s
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                if proc.poll() is not None:
                    raise Failed("the host exited at start (exit %s)" % proc.returncode)
                if time.monotonic() > end:
                    raise Failed("no host on port %d after %.0f s" % (port, limit_s))
                time.sleep(0.05)
        self.sock.settimeout(60)

    def cmd(self, line):
        self.sock.sendall(line.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Failed("the host closed the connection on: " + line)
            buf += chunk
        return buf[:-1].decode(errors="replace").strip()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def free_port(start):
    p = start
    while True:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            # a daemon may take p+1 as its feedback port
            s = socket.socket()
            s.bind(("127.0.0.1", p + 1))
            s.close()
            return p
        except OSError:
            s.close()
            p += 2


# ---------------------------------------------------------------- the machine and the software


def read(path, default=""):
    try:
        with open(path, "rb") as f:
            return f.read().replace(b"\0", b"").decode(errors="replace").strip()
    except OSError:
        return default


def governors():
    return sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor"))


def governor_now():
    vals = sorted({read(p) for p in governors()})
    if not vals:
        return "none"
    return vals[0] if len(vals) == 1 else "mixed:" + ",".join(vals)


def write_sys(path, value):
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError:
        pass
    if shutil.which("sudo"):
        r = subprocess.run(["sudo", "-n", "tee", path], input=value, text=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        return r.returncode == 0
    return False


def machine(cls):
    model = read("/proc/device-tree/model") or " ".join(
        x for x in (read("/sys/class/dmi/id/sys_vendor"), read("/sys/class/dmi/id/product_name")) if x) or "unknown"
    cpu = ""
    for line in read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    if not cpu and shutil.which("lscpu"):
        for line in subprocess.run(["lscpu"], stdout=subprocess.PIPE, text=True).stdout.splitlines():
            if line.startswith("Model name:"):
                cpu = line.split(":", 1)[1].strip()
                break
    mem = 0
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            mem = int(line.split()[1]) // 1024
    rel = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rel[k] = v.strip('"')
    os_name = ("%s %s" % (rel.get("NAME", "Linux").split()[0], rel.get("VERSION_ID", ""))).strip()
    return {"class": cls, "model": model, "cpu": cpu or "unknown", "cores": os.cpu_count() or 1, "ram_mb": mem,
            "os": os_name, "kernel": os.uname().release, "governor": governor_now()}


def package_of(path):
    """(package, version) of the installed package that owns path, from dpkg or rpm"""
    real = os.path.realpath(path)
    for cand in dict.fromkeys([path, real]):
        if shutil.which("dpkg-query"):
            r = subprocess.run(["dpkg-query", "-S", cand], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if r.returncode == 0 and ":" in r.stdout:
                pkg = r.stdout.split(":", 1)[0].split(",")[0].strip()
                v = subprocess.run(["dpkg-query", "-W", "-f", "${Version}", pkg], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True).stdout.strip()
                return pkg, v or None
        if shutil.which("rpm"):
            r = subprocess.run(["rpm", "-qf", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n", cand], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
            if r.returncode == 0 and r.stdout.strip():
                pkg, v = r.stdout.splitlines()[0].split(" ", 1)
                return pkg, v
    return None, None


def program_version(name):
    path = shutil.which(name)
    if not path:
        return None
    _, v = package_of(path)
    if v:
        return v
    for flag in ("-V", "--version"):
        try:
            out = subprocess.run([path, flag], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"\d+\.\d+[\w.+~-]*", out)
        if m:
            return m.group(0) + " (not packaged)"
    return "not packaged"


def software(plugin_files):
    sw = {"plugin-hostd": program_version("plugin-hostd"), "omx-clap-host": program_version("omx-clap-host"),
          "mod-host": program_version("mod-host"), "jalv": program_version("jalv"), "jack": program_version("jackd")}
    for f in plugin_files:
        pkg, v = package_of(f)
        if pkg and pkg not in sw:
            sw[pkg] = v
    return sw


# ---------------------------------------------------------------- plugins


def _search_paths():
    """tools/search-paths.py: the lists plugin-hostd searches, written once in include/plugin-hostd/search_paths.h"""
    import importlib.util
    # SEARCH_PATHS_TOOL names it for a copy of bench/ that lives outside the checkout (bench/tests/sabotage.sh)
    path = os.environ.get("SEARCH_PATHS_TOOL") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                                               "tools", "search-paths.py")
    spec = importlib.util.spec_from_file_location("search_paths", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clap_dirs():
    return _search_paths().search("clap", env=True)


def lv2_dirs():
    return _search_paths().search("lv2", env=True)


def clap_uri(spec):
    fname, pid = spec.split("#", 1)
    for d in clap_dirs():
        if os.path.exists(os.path.join(d, fname)):
            return "clap:%s#%s" % (os.path.join(d, fname), pid), os.path.join(d, fname)
    return None, None


class Catalog:
    def __init__(self, table, pianoteq_dir):
        self.plugins = table["plugins"]
        self.midi = table["midi"]
        self.pianoteq_dir = pianoteq_dir
        self.manifests = {}

    def name(self, key):
        return self.plugins[key]["name"]

    def needs(self, key):
        if self.plugins[key].get("needs") == "pianoteq" and not self.pianoteq_dir:
            raise Refused("Pianoteq is not on this machine (no --pianoteq-dir)")

    def for_host(self, key, host, fmt=None):
        """(uri the host takes, label for the document, note) for one plugin on one host"""
        self.needs(key)
        p = self.plugins[key]
        if host in ("H1", "H2"):
            if fmt != "lv2" and "clap" in p:
                uri, _ = clap_uri(p["clap"])
                if not uri:
                    raise Refused("%s is not installed as CLAP" % p["name"])
                return uri, "%s (CLAP)" % p["name"], None
            if fmt == "clap":
                raise Refused("%s has no CLAP build" % p["name"])
            self.lv2_installed(p)
            return "lv2:" + p["lv2"], "%s (LV2)" % p["name"], None
        if fmt == "clap":
            raise Refused("%s runs LV2 only" % HOST_PROGRAM[host])
        if "lv2" not in p:
            raise Refused("%s has no LV2 build" % p["name"])
        self.lv2_installed(p)
        return p["lv2"], "%s (LV2)" % p["name"], p["name"] if "clap" in p else None

    def lv2_installed(self, p):
        """a plugin no bundle's manifest names is not on this machine: the row is unsupported, not a failed add"""
        uri = "<%s>" % p["lv2"]
        if uri not in self.manifests:
            dirs = ([self.pianoteq_dir] if self.pianoteq_dir else []) + lv2_dirs()
            found = [m for d in dirs for pat in ("manifest.ttl", "*.lv2/manifest.ttl")
                     for m in glob.glob(os.path.join(d, pat))]
            self.manifests[uri] = any(uri in read(m) for m in found)
        if not self.manifests[uri]:
            raise Refused("%s is not installed (no LV2 bundle names %s)" % (p["name"], p["lv2"]))

    def files(self):
        out = []
        for p in self.plugins.values():
            if "clap" in p:
                _, f = clap_uri(p["clap"])
                if f:
                    out.append(f)
        for d in lv2_dirs():
            for b in ("omx-comp.lv2", "calf.lv2"):
                m = os.path.join(d, b, "manifest.ttl")
                if os.path.exists(m):
                    out.append(m)
        return list(dict.fromkeys(out))


# ---------------------------------------------------------------- pins for the plan and pool modes


def set_verdicts(store, verdicts):
    """the daemon's pin store with a verdict on the line of each uri in verdicts ({uri: word}), replacing any it had;
    the other lines as they were. Failed when a uri has no line: the daemon never learned it"""
    out, seen = [], set()
    for line in store.splitlines():
        words = line.split()
        if len(words) >= 4 and words[0] == "pin_set" and words[1] in verdicts:
            seen.add(words[1])
            line = " ".join([w for w in words if not w.startswith("verdict=")] + ["verdict=" + verdicts[words[1]]])
        out.append(line)
    missing = sorted(set(verdicts) - seen)
    if missing:
        raise Failed("the daemon recorded no pin for %s" % ", ".join(missing))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- hosts


class Host:
    """one host program started for one scenario row"""

    def __init__(self, key, procs, env, workdir, port, conf=("require_pins 0",)):
        self.key, self.procs, self.env, self.workdir, self.port = key, procs, env, workdir, port
        self.conf = conf
        self.proc = None
        self.ctl = None
        self.jalvs = {}

    def start(self):
        if self.key == "H1":
            self.proc = self.procs.spawn(["omx-clap-host", "-n", "-p", str(self.port)], "H1", self.env)
        elif self.key == "H2":
            conf = os.path.join(self.workdir, "plugin-hostd.conf")
            with open(conf, "w") as f:
                f.write("".join(line + "\n" for line in self.conf))
            self.proc = self.procs.spawn(["plugin-hostd", "-n", "-p", str(self.port), "-c", conf], "H2", self.env)
        elif self.key == "H3":
            self.proc = self.procs.spawn(["mod-host", "-n", "-p", str(self.port)], "H3", self.env)
        if self.key != "H4":
            self.ctl = Control(self.port, self.proc)

    def roots(self):
        if self.key == "H4":
            return [p.pid for p in self.jalvs.values() if p.poll() is None]
        return [self.proc.pid] if self.proc and self.proc.poll() is None else []

    def pids(self):
        """the processes the host runs: its own and every descendant, the workers of plugin-hostd included"""
        out = []
        for r in self.roots():
            out += [r] + descendants(r)
        return [p for p in dict.fromkeys(out) if alive(p)]

    def workers(self):
        """plugin-hostd's worker_list: [(worker, pid, format, state, place, [instances])]"""
        reply = self.ctl.cmd("worker_list").split()
        out = []
        for rec in reply[2:]:
            f = rec.split(":")
            # an id followed by ! is an instance the pins read again refuse, still running
            insts = [int(i.rstrip("!")) for i in f[-1].split(",") if i.rstrip("!").isdigit()]
            # <worker>:<pid>:<format>:<state>:<core>:<pool>:<place>:<instances> (docs/placement.md), the place holding
            # colons of its own
            out.append((f[0], int(f[1]), f[2], f[3], ":".join(f[6:-1]), insts))
        return out

    def wait_workers(self, want, what):
        """until worker_list shows `want` workers, all up; the workers, or Failed after READY_LIMIT_S"""
        end = time.monotonic() + READY_LIMIT_S
        while True:
            ws = self.workers()
            if len(ws) == want and all(w[3] == "up" for w in ws):
                return ws
            if time.monotonic() > end:
                raise Failed("%s: %d workers up of %d wanted after %.0f s" % (
                    what, sum(1 for w in ws if w[3] == "up"), want, READY_LIMIT_S))
            time.sleep(0.01)

    def declare_plan(self, insts):
        """plan 1 <insts>: the segments the daemon made, [[inst, ...], ...], once their workers are up"""
        reply = self.ctl.cmd("plan 1 " + " ".join(map(str, insts)))
        words = reply.split()
        if len(words) < 3 or words[:2] != ["resp", "0"]:
            raise Failed("plan answered '%s'" % reply)
        segments = [[int(i) for i in seg.split(",")] for seg in words[2].split(";")]
        if sorted(i for seg in segments for i in seg) != sorted(insts):
            raise Failed("plan answered segments '%s' for instances %s" % (words[2], insts))
        if len(segments) < 2:
            raise Failed("the plan is one segment: no member of the strip was left alone, so it is the chain row")
        self.wait_workers(len(segments), "plan")
        return segments

    def declare_pool(self, insts, uris, alone, name="g1"):
        """plan, then the members the plan left alone that the pins would let share (every segment of one that is not
        an `alone` instance) leave their workers for the pool: remove and add again with the pool's place. Returns
        (segments, pooled instances)"""
        segments = self.declare_plan(insts)
        pooled = [seg[0] for seg in segments if len(seg) == 1 and seg[0] not in alone]
        if len(pooled) < 2:
            raise Failed("the plan left %d shareable member(s) alone: a pool needs two" % len(pooled))
        if len(pooled) > POOL_MAX:
            raise Failed("%d members for one pool, which holds %d" % (len(pooled), POOL_MAX))
        for i in pooled:
            reply = self.ctl.cmd("remove %d" % i)
            if reply != "resp 0":
                raise Failed("remove %d answered '%s'" % (i, reply))
            self.add(uris[i], i, "pool:" + name)
        ws = self.wait_workers(len(segments) - len(pooled) + 1, "pool")
        holder = [w for w in ws if w[4] == "pool:" + name]
        if len(holder) != 1 or sorted(holder[0][5]) != sorted(pooled):
            raise Failed("pool:%s holds %s, not %s" % (name, [w[5] for w in holder], pooled))
        return segments, pooled

    def add(self, uri, inst, placement=None):
        """add one plugin; returns the client name"""
        client = "effect_%d" % inst
        if self.key == "H4":
            argv = ["jalv", "-i", "-n", client, uri]
            self.jalvs[inst] = self.procs.spawn(argv, "H4-%d" % inst, self.env)
            end = time.monotonic() + READY_LIMIT_S
            while client not in ports(self.env):
                if self.jalvs[inst].poll() is not None:
                    raise Failed("jalv exited at start for %s" % uri)
                if time.monotonic() > end:
                    raise Failed("jalv shows no JACK client for %s after %.0f s" % (uri, READY_LIMIT_S))
                time.sleep(0.01)
            return client
        line = "add %s %d" % (uri, inst) + (" " + placement if placement else "")
        reply = self.ctl.cmd(line)
        if reply != "resp %d" % inst:
            raise Failed("%s answered '%s' to: %s" % (HOST_PROGRAM[self.key], reply, line))
        return client

    def connect(self, a, b):
        if self.key == "H4":
            subprocess.run(["jack_connect", a, b], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        reply = self.ctl.cmd("connect %s %s" % (a, b))
        if reply != "resp 0":
            raise Failed("connect %s %s answered '%s'" % (a, b, reply))

    def stop(self):
        if self.ctl:
            self.ctl.close()
        for p in list(self.jalvs.values()):
            self.procs.stop(p)
        if self.proc:
            self.procs.stop(self.proc)


def wire(host, env, clients, instrument):
    """sine (or the chords) into the first client, each client into the next, the last into the playback ports"""
    graph = ports(env)
    if instrument:
        host.connect("seq:out", graph[clients[0]]["midi_in"][0])
        src = []
    else:
        src = graph["sine"]["audio_out"]
    for c in clients:
        ins = graph.get(c, {}).get("audio_in", [])
        for k, port in enumerate(ins):
            if src:
                host.connect(src[min(k, len(src) - 1)], port)
        src = graph.get(c, {}).get("audio_out", [])
        if not src:
            raise Failed("%s has no audio output" % c)
    for k, port in enumerate(graph["system"]["audio_in"][:2]):
        host.connect(src[min(k, len(src) - 1)], port)
    return src


# ---------------------------------------------------------------- the runner


class Runner:
    def __init__(self, args, table):
        self.args = args
        self.table = table
        self.cat = Catalog(table, args.pianoteq_dir)
        self.work = tempfile.mkdtemp(prefix="omx-bench-")
        self.logdir = args.logs or os.path.join(self.work, "logs")
        os.makedirs(self.logdir, exist_ok=True)
        self.server = "bench%d" % os.getpid()
        self.procs = Procs(self.logdir, self.server)
        self.env = dict(self.procs.env)
        self.env["XDG_STATE_HOME"] = os.path.join(self.work, "state")
        self.env["XDG_RUNTIME_DIR"] = self.env.get("XDG_RUNTIME_DIR") or os.path.join(self.work, "run")
        os.makedirs(self.env["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
        if args.pianoteq_dir:
            self.env["LV2_PATH"] = ":".join([args.pianoteq_dir] + [d for d in lv2_dirs() if os.path.isdir(d)])
        self.saved_governor = {}
        self.jackd = None
        self.probe = None
        self.learned = {}
        self.jack_log = None
        self.jack_log_end = 0
        self.port = 5700

    # -- governor

    def governor_on(self):
        if self.args.keep_governor:
            return
        paths = governors()
        for p in paths:
            self.saved_governor[p] = read(p)
        ok = paths and all(write_sys(p, "performance") for p in paths)
        if not ok:
            self.governor_off()
            msg = "cannot set the CPU governor to performance (run as root, or with sudo, or pass --keep-governor)"
            if self.args.cls != "ci":
                raise SystemExit("bench: " + msg)
            log(msg + "; class ci goes on with the governor it has: " + governor_now())

    def governor_off(self):
        for p, v in self.saved_governor.items():
            if v and read(p) != v:
                write_sys(p, v)
        self.saved_governor = {}

    # -- JACK

    def jack_start(self, rate, frames):
        self.jack_stop()
        self.jackd = self.procs.spawn(["jackd", "-n", self.server, "-d", "dummy", "-r", str(rate), "-p", str(frames)],
                                      "jackd-%d-%d" % (rate, frames))
        end = time.monotonic() + READY_LIMIT_S
        while "system" not in ports(self.env):
            if self.jackd.poll() is not None or time.monotonic() > end:
                raise SystemExit("bench: the private JACK server did not start at %d Hz / %d frames (see %s)"
                                 % (rate, frames, self.logdir))
            time.sleep(0.1)
        self.probe = JackProbe(self.server)
        self.jack_log = os.path.join(self.logdir, "jackd-%d-%d.log" % (rate, frames))
        self.jack_log_end = jack_log_xruns(self.jack_log, 0)[1]

    def jack_stop(self):
        if self.probe:
            self.probe.close()
            self.probe = None
        if self.jackd:
            self.procs.stop(self.jackd)
            self.jackd = None

    def dsp_window(self, seconds):
        """jack_cpu_load's one line a second for seconds+1 s; the first is the warm-up and is dropped"""
        p = subprocess.Popen(["jack_cpu_load"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, start_new_session=True)
        time.sleep(seconds + 1.3)
        p.send_signal(signal.SIGINT)
        try:
            out, _ = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
        vals = [float(m) for m in re.findall(r"DSP load\s+([0-9.]+)", out)]
        return vals[1:seconds + 1]

    # -- rows

    def plan(self):
        hosts = self.args.hosts
        rows = []
        for s in self.table["scenarios"]:
            if self.args.scenarios and s["id"] not in self.args.scenarios:
                continue
            loads = {"none": [False], "on": [True], "both": [False, True]}[self.args.stress] if s.get("stress") \
                else [False]
            if s.get("family"):
                for load in loads:
                    for m in self.table["modes"][s["family"]]:
                        if m["host"] in hosts:
                            rows.append((s, m["host"], m["mode"], load))
            else:
                for load in loads:
                    for h in hosts:
                        rows.append((s, h, None, load))
        return rows

    def plugin_list(self, s):
        keys = s["plugins"]
        if s.get("count"):
            keys = [keys[n % len(keys)] for n in range(s["count"])]
        elif s.get("repeat"):
            keys = keys * s["repeat"]
        return keys

    def row(self, s, hkey, mode, rate, frames, stress=False):
        cores = stress_cores()
        r = {"id": s["id"], "title": s["title"], "host": hkey, "rate": rate, "frames": frames, "plugins": [],
             "dsp_load_avg": None, "dsp_load_max": None, "samples": 0, "rss_mb": None, "add_ms": None,
             "recover_ms": None, "status": "failed", "note": "",
             "stress": stress_profile(cores) if stress else "none"}
        if mode:
            r["mode"] = mode
        host = None
        sources = []
        try:
            keys = self.plugin_list(s)
            if hkey == "H4" and not keys:
                raise Refused("jalv runs one plugin per process; it has no host without a plugin")
            if s.get("chain") and hkey == "H2":
                mode = "chain"
            picks = [self.cat.for_host(k, hkey, s.get("format")) for k in keys]
            r["plugins"] = [label for _, label, _ in picks]
            if not shutil.which(HOST_PROGRAM[hkey]):
                raise Refused("%s is not installed" % HOST_PROGRAM[hkey])
            builds = list(dict.fromkeys(n for _, _, n in picks if n))
            notes = ["LV2 builds of " + ", ".join(builds)] if builds else []
            instrument = any(self.cat.plugins[k].get("instrument") for k in keys)

            self.port = free_port(self.port + 2)
            wd = tempfile.mkdtemp(dir=self.work)
            conf, alone, uris = ("require_pins 0",), set(), [u for u, _, _ in picks]
            if mode in ("plan", "pool"):
                if hkey != "H2":
                    raise Refused("only plugin-hostd plans and pools")
                alone = {i for i, k in enumerate(keys) if k in s.get("unshared", [])}
                conf = self.plan_conf(wd, uris, {uris[i] for i in alone})
                notes.append("pins: in-process, isolated for %s" % ", ".join(
                    dict.fromkeys(self.cat.name(keys[i]) for i in sorted(alone))))
            host = Host(hkey, self.procs, self.env, wd, self.port, conf)
            graph_before = set(ports(self.env))
            log_end = log_size(self.logdir, hkey)
            try:
                host.start()
            except Failed:
                if mode in ("plan", "pool") and "bad setting 'grouping'" in log_since(self.logdir, hkey, log_end):
                    raise Refused("this plugin-hostd has no grouping setting: it predates the planner (plugin-hostd#185)")
                raise
            if instrument:
                sources.append(self.procs.spawn(["jack_midiseq", "seq"] + self.cat.midi["chords"], "midiseq"))
                want = "seq"
            else:
                sources.append(self.procs.spawn(["jack_simple_client", "sine"], "sine"))
                want = "sine"
            end = time.monotonic() + READY_LIMIT_S
            while want not in ports(self.env):
                if time.monotonic() > end:
                    raise Failed("the %s source did not start" % want)
                time.sleep(0.05)
            for k in range(2):
                subprocess.run(["jack_disconnect", "sine:output%d" % (k + 1), "system:playback_%d" % (k + 1)],
                               env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            insts = list(range(len(picks)))
            placement = "own" if hkey == "H2" and mode == "individual" else None
            t0 = time.monotonic()
            clients = [host.add(uri, i, placement) for (uri, _, _), i in zip(picks, insts)]
            if mode == "chain" and insts:
                reply = host.ctl.cmd("chain 1 " + " ".join(map(str, insts)))
                if reply != "resp 0":
                    raise Failed("chain answered '%s'" % reply)
                self.chain_formed(host, insts)
            elif mode == "plan":
                segments = host.declare_plan(insts)
                notes.append("plan: " + ";".join(",".join(map(str, g)) for g in segments))
            elif mode == "pool":
                segments, pooled = host.declare_pool(insts, uris, alone)
                notes.append("plan: " + ";".join(",".join(map(str, g)) for g in segments)
                             + "; pool:g1 holds " + ",".join(map(str, pooled)))
            add_ms = (time.monotonic() - t0) * 1000 if insts else None
            if clients:
                graph = ports(self.env)
                clients = [c for c in clients if c in graph]
                wire(host, self.env, clients, instrument)
            if hkey == "H2" and insts:
                ws = host.workers()
                if mode is None:
                    mode = "individual" if len(ws) == len(insts) else "shared-process"
                if mode == "individual" and len(ws) != len(insts):
                    notes.append("worker_list shows %d workers for %d instances" % (len(ws), len(insts)))
                if mode == "chain" and len(ws) != 1:
                    notes.append("worker_list shows %d workers for one chain" % len(ws))
                if mode == "chain" and len(clients) > 1:
                    notes.append("one worker, %d JACK clients" % len(clients))
            elif insts:
                mode = mode or ("individual" if hkey == "H4" else "shared-process")
            if mode:
                r["mode"] = mode
            if stress:
                for name, argv in stress_argvs(cores):
                    sources.append(self.procs.spawn(argv, name))
            time.sleep(2.0 if stress else 1.0)

            pids = host.pids()
            before = samples(pids)
            t_start = time.monotonic()
            x_before = self.probe.count()
            self.jack_log_end = jack_log_xruns(self.jack_log, self.jack_log_end)[1]
            loads = self.dsp_window(self.args.window)
            logged, self.jack_log_end = jack_log_xruns(self.jack_log, self.jack_log_end)
            r["xruns"] = window_xruns(self.probe.count() - x_before, logged)
            after = samples(pids)
            span = time.monotonic() - t_start
            if not host.pids() or any(not alive(p) for p in pids):
                raise Failed("a host process exited during the window")
            if not loads:
                raise Failed("jack_cpu_load gave no reading")
            r["dsp_load_avg"] = round(sum(loads) / len(loads), 2)
            r["dsp_load_max"] = round(max(loads), 2)
            r["samples"] = len(loads)
            common = [p for p in pids if p in before and p in after]
            rss = sum(after[p]["rss"] for p in common) / 1024
            r["rss_mb"] = round(rss, 1)
            r["add_ms"] = round(add_ms, 1) if add_ms is not None else None
            r["processes"] = len(common)
            r["rss_mb_total"] = round(rss, 1)
            if all(after[p]["pss"] is not None for p in common):
                r["pss_mb_total"] = round(sum(after[p]["pss"] for p in common) / 1024, 1)
            ticks = sum(after[p]["ticks"] - before[p]["ticks"] for p in common)
            r["cpu_pct"] = round(100.0 * ticks / CLK_TCK / span, 2)
            vol = sum(after[p]["vol"] - before[p]["vol"] for p in common)
            invol = sum(after[p]["invol"] - before[p]["invol"] for p in common)
            r["ctx_switches"] = vol + invol
            r["ctx_involuntary"] = invol
            r["latency_frames"] = self.probe.latency_frames("system:playback_1")
            # the JACK clients the host put on the graph: every client there now that was not there before it started,
            # the source excepted
            r["jack_clients"] = len(set(ports(self.env)) - graph_before - {want})
            r["status"] = "ok"

            if s.get("kill"):
                self.kill_and_recover(host, r, insts[0], clients[0])
            r["note"] = "; ".join(notes + ([r["note"]] if r["note"] else []))
        except Refused as e:
            r["status"], r["note"] = "unsupported", str(e)
        except Failed as e:
            r["status"], r["note"] = "failed", str(e)
        finally:
            if host:
                host.stop()
            for p in sources:
                self.procs.stop(p)
            self.assert_only_jack("after %s %s %d/%d" % (s["id"], hkey, rate, frames))
        return r

    def plan_conf(self, wd, uris, alone):
        """the conf of a plan or pool row: pins on, the store holding a verdict for each plugin the strip uses
        (in-process, and isolated for those in `alone`), grouping on, no package pins to say otherwise"""
        store = os.path.join(wd, "pins")
        learned = self.learn_pins(uris)
        with open(store, "w") as f:
            f.write(set_verdicts(learned, {u: "isolated" if u in alone else "in-process" for u in uris}))
        return ("require_pins 1", "pin_mode first-use", "pin_store " + store, "pins_dir", "grouping on")

    def learn_pins(self, uris):
        """the pin store a daemon writes when it first sees each plugin (files hashed, layout learned): the pins a
        plugin-qualify run would write, minus the verdicts. One daemon start for each set of plugins in the run"""
        key = tuple(dict.fromkeys(uris))
        if key not in self.learned:
            wd = tempfile.mkdtemp(dir=self.work)
            store = os.path.join(wd, "pins")
            self.port = free_port(self.port + 2)
            host = Host("H2", self.procs, self.env, wd, self.port,
                        ("require_pins 1", "pin_mode first-use", "pin_store " + store, "pins_dir"))
            try:
                host.start()
                for i, uri in enumerate(key):
                    host.add(uri, i, "own")
            finally:
                host.stop()
            with open(store) as f:
                self.learned[key] = f.read()
        return self.learned[key]

    def measure(self, s, hkey, mode, rate, frames, stress):
        """the row, run args.repeats times; a row that cannot run, or breaks, ends the repeats"""
        runs = []
        for _ in range(self.args.repeats):
            runs.append(self.row(s, hkey, mode, rate, frames, stress))
            if runs[-1]["status"] != "ok":
                break
        return aggregate(runs, self.args.repeats)

    def chain_formed(self, host, insts):
        want = ",".join(map(str, insts))
        end = time.monotonic() + READY_LIMIT_S
        while time.monotonic() < end:
            f = host.ctl.cmd("chain_get 1").split()
            if len(f) >= 5 and f[2] != "-" and f[4] == want:
                return
            time.sleep(0.01)
        raise Failed("the chain did not form within %.0f s" % READY_LIMIT_S)

    def kill_and_recover(self, host, r, inst, client):
        """kill -9 the process that holds the plugin; time until its client is back and wired as before"""
        if host.key == "H2":
            holder = [w for w in host.workers() if inst in w[5]]
            if not holder:
                raise Failed("worker_list names no worker for instance %d" % inst)
            pid = holder[0][1]
        elif host.key == "H4":
            pid = host.jalvs[inst].pid
        else:
            pid = host.proc.pid
        graph = ports(self.env)
        ins = graph[client]["audio_in"][0]
        outs = graph[client]["audio_out"][0]
        wired = lambda: connected(self.env, ins, "sine:output1") and connected(self.env, outs, "system:playback_1")
        t0 = time.monotonic()
        os.kill(pid, signal.SIGKILL)
        gone = False
        while time.monotonic() - t0 < RECOVER_LIMIT_S:
            reap()
            if host.key != "H2":
                if not alive(pid):
                    break
            elif not gone:
                # the old client leaves the graph first; only then can a wired client be the respawned one
                gone = not alive(pid) and not wired()
            elif wired():
                r["recover_ms"] = round((time.monotonic() - t0) * 1000, 1)
                return
            time.sleep(0.005)
        if host.key == "H2":
            raise Failed("the plugin's audio was not back %.0f s after kill -9 of its worker" % RECOVER_LIMIT_S)
        reap()
        time.sleep(0.5)
        if client in ports(self.env):
            raise Failed("the client outlived kill -9 of its process")
        r["status"] = "failed"
        r["note"] = "host process lost"

    def assert_only_jack(self, when):
        jack = {self.jackd.pid} if self.jackd and self.jackd.poll() is None else set()
        stray = [(p, c) for p, c in marked() if p not in jack]
        if stray:
            stop_strays(stray)
            raise SystemExit("bench: teardown %s left %s" % (when, ", ".join("%d %s" % x for x in stray)))

    # -- the run

    def qualify(self, rates, frames):
        if not shutil.which("plugin-qualify"):
            raise SystemExit("bench: --qualify needs plugin-qualify")
        empty = os.path.join(self.work, "no-lv2")
        os.makedirs(empty, exist_ok=True)
        env = dict(self.env)
        env["LV2_PATH"] = empty
        t0 = time.monotonic()
        p = subprocess.run(["plugin-qualify", "--all", "--isolate", "--rates", str(rates[0]), "--quanta",
                            str(frames[0]), "--format", "json"], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True)
        secs = time.monotonic() - t0
        if p.returncode not in (0, 1):
            raise SystemExit("bench: plugin-qualify could not measure (exit %d)" % p.returncode)
        recs = json.loads(p.stdout)
        good = sum(1 for x in recs if x["verdicts"] and x["verdicts"][0].get("rating") == "suitable")
        return {"plugins": len(recs), "files": len({x["binary"]["path"] for x in recs}), "seconds": round(secs, 1),
                "rates": [rates[0]], "quanta": [frames[0]], "suitable": good, "unsuitable": len(recs) - good}

    def doc_id(self):
        day = datetime.date.today().strftime("%Y%m%d")
        os.makedirs(self.args.out, exist_ok=True)
        seq = 1
        while os.path.exists(os.path.join(self.args.out, "%s-%s-%d.json" % (self.args.cls, day, seq))):
            seq += 1
        return "%s-%s-%d" % (self.args.cls, day, seq)

    def run(self):
        self.governor_on()
        doc = {"schema": "omx-bench/1", "id": self.doc_id(), "machine": machine(self.args.cls),
               "software": software(self.cat.files()), "scenarios": []}
        rows = self.plan()
        for rate in self.args.rates:
            for frames in self.args.frames:
                self.jack_start(rate, frames)
                for s, h, mode, stress in rows:
                    r = self.measure(s, h, mode, rate, frames, stress)
                    log("%-8s %s %-14s %6d/%-4d %-11s dsp %s%% rss %s MB add %s ms xruns %s %s%s" % (
                        r["id"], h, r.get("mode", "-"), rate, frames, r["status"], r["dsp_load_avg"], r["rss_mb"],
                        r["add_ms"], r.get("xruns"), "" if r["stress"] == "none" else r["stress"] + " ", r["note"]))
                    doc["scenarios"].append(r)
                self.jack_stop()
        if self.args.qualify:
            doc["qualification"] = self.qualify(self.args.rates, self.args.frames)
        path = os.path.join(self.args.out, doc["id"] + ".json")
        with open(path + ".tmp", "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        os.rename(path + ".tmp", path)
        return path

    def teardown(self):
        """always: every process stopped, the governor put back, then nothing of this run may be left"""
        self.procs.stop_all()
        self.governor_off()
        reap()
        time.sleep(0.2)
        left = marked()
        if not self.args.logs:
            shutil.rmtree(self.work, ignore_errors=True)
        if left:
            stop_strays(left)
            log("teardown left %d process(es) of this run: %s" % (len(left), ", ".join("%d %s" % x for x in left)))
            return False
        log("teardown: no host, no JACK server, no other process of this run is left")
        return True


def csv_ints(text):
    return [int(x) for x in text.split(",") if x]


def main():
    ap = argparse.ArgumentParser(prog="bench/run.sh", description="compare four plugin hosts; write omx-bench/1")
    ap.add_argument("--class", dest="cls", required=True, choices=["rpi5", "desk", "ci"])
    ap.add_argument("--out", required=True, help="directory of the documents")
    ap.add_argument("--rates", type=csv_ints, default=[48000, 96000])
    ap.add_argument("--frames", type=csv_ints, default=[128, 256])
    ap.add_argument("--scenarios", type=lambda t: [x for x in t.split(",") if x], default=None)
    ap.add_argument("--hosts", type=lambda t: [x for x in t.split(",") if x], default=list(HOSTS))
    ap.add_argument("--stress", choices=["none", "on", "both"], default="both",
                    help="the scenarios that declare a stress run without it, with it, or both")
    ap.add_argument("--repeats", type=int, default=3, help="runs of each row; the document holds the median and the "
                    "spread (1 for a quick look, 3 at least for a document that says anything)")
    ap.add_argument("--window", type=int, default=10, help="seconds of DSP load and /proc sampling per row")
    ap.add_argument("--pianoteq-dir", default=None, help="the directory of Pianoteq's LV2 bundle")
    ap.add_argument("--qualify", action="store_true", help="also time plugin-qualify --all --isolate")
    ap.add_argument("--keep-governor", action="store_true", help="leave the CPU governor as it is")
    ap.add_argument("--logs", default=None, help="keep the host logs in this directory")
    args = ap.parse_args()
    if args.repeats < 1:
        ap.error("--repeats takes 1 or more")
    if set(args.hosts) - set(HOSTS):
        ap.error("--hosts takes H1,H2,H3,H4")
    table = json.load(open(os.path.join(BENCH, "scenarios.json")))
    known = {s["id"] for s in table["scenarios"]}
    if args.scenarios and set(args.scenarios) - known:
        ap.error("unknown scenario: " + ", ".join(sorted(set(args.scenarios) - known)))
    for prog in ("jackd", "jack_cpu_load", "jack_simple_client", "jack_lsp", "jack_connect"):
        if not shutil.which(prog):
            ap.error(prog + " is needed (packages jackd2 and jack-example-tools)")

    # orphans of the hosts come back to the runner, which reaps them and sees them in the last check
    try:
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
    except (OSError, AttributeError):
        pass
    runner = Runner(args, table)

    def on_signal(sig, _frame):
        raise SystemExit("bench: stopped by signal %d" % sig)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    code = 0
    try:
        path = runner.run()
        print(path)
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code if isinstance(e.code, str) else "bench: exit %s" % e.code, file=sys.stderr)
            code = 1
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if not runner.teardown():
            code = 3
    sys.exit(code)


if __name__ == "__main__":
    main()

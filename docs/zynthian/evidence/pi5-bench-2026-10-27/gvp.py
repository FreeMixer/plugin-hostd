#!/usr/bin/env python3
# grouped (chain, one worker) vs one process per plugin, on the private JACK server, with and without stress
import os, sys, re, time, json, glob, socket, subprocess, signal
os.chdir("/root/omx-run")
PINS = "/var/lib/omx/qualified.pins"
WINDOW = 10
RATES = [int(x) for x in os.environ.get("RATES", "48000,96000").split(",")]
NS = [int(x) for x in os.environ.get("NS", "3,8,16").split(",")]
FRAMES = 256
PORT = 5590
TCK = os.sysconf("SC_CLK_TCK")
env = dict(os.environ)
env["LV2_PATH"] = "/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/zynthian/zynthian-plugins/lv2"

pool = []
for l in open(PINS):
    m = re.match(r"pin_set (clap:/usr/lib/clap/omx-[a-z0-9]+\.clap#\S+) .*verdict=in-process", l)
    if m:
        pool.append(m[1])
pool = [u for u in pool if any(k in u for k in ("omx-comp", "omx-delay", "omx-drive", "omx-chorus", "omx-flanger", "omx-eq8", "omx-deesser", "omx-geq"))]
print("pool", pool, flush=True)
assert pool, "no in-process omx plugins in the pin file"

class Hostd:
    def __init__(self):
        self.s = socket.create_connection(("127.0.0.1", PORT), timeout=60)
    def call(self, line):
        self.s.sendall(line.encode() + b"\0")
        b = b""
        while not b.endswith(b"\0"):
            c = self.s.recv(65536)
            if not c: break
            b += c
        return b.decode(errors="replace").rstrip("\0")

def pids_stats(pids):
    rss = pss = ticks = ctx = 0
    for p in pids:
        try:
            for l in open(f"/proc/{p}/smaps_rollup"):
                if l.startswith("Rss:"): rss += int(l.split()[1])
                if l.startswith("Pss:"): pss += int(l.split()[1])
            st = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            ticks += int(st[11]) + int(st[12])
            for t in glob.glob(f"/proc/{p}/task/*/status"):
                for l in open(t):
                    if "ctxt_switches" in l: ctx += int(l.split()[1])
        except (FileNotFoundError, ProcessLookupError):
            pass
    return rss, pss, ticks, ctx

def run(rate, n, mode, stress):
    srv = f"gvp{rate}"
    env["JACK_DEFAULT_SERVER"] = srv
    jack = subprocess.Popen(["jackd", "-n", srv, "-d", "dummy", "-r", str(rate), "-p", str(FRAMES)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    time.sleep(3)
    conf = f"/root/omx-run/gvp.conf"
    open(conf, "w").write("mod_host /usr/local/bin/mod-host\nclap_host omx-clap-host\nlv2_worker auto\nrequire_pins 1\npin_file %s\nstate_root /run/plugin-hostd-gvp\ndescriptor_dir /var/lib/omx/descriptors\n" % PINS)
    os.makedirs("/run/plugin-hostd-gvp", exist_ok=True)
    hd = subprocess.Popen(["plugin-hostd", "-n", "-p", str(PORT), "-c", conf], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    procs = [hd, jack]
    busy = []
    try:
        for _ in range(50):
            try:
                h = Hostd(); break
            except OSError:
                time.sleep(0.2)
        t0 = time.monotonic()
        for i in range(n):
            r = h.call(f"add {pool[i % len(pool)]} {i}")
            if not r.startswith("resp") or int(r.split()[1]) < 0:
                raise RuntimeError(f"add {i} {pool[i % len(pool)]}: {r}")
        add_ms = (time.monotonic() - t0) * 1000
        chain_reply = ""
        if mode == "grouped":
            chain_reply = h.call("chain 1 " + " ".join(map(str, range(n))))
            if not chain_reply.startswith("resp") or int(chain_reply.split()[1]) < 0:
                raise RuntimeError("chain: " + chain_reply)
        wl = h.call("worker_list")
        workers = [w.split(":") for w in wl.split()[2:]] if wl.startswith("resp") else []
        wpids = [int(w[1]) for w in workers]
        pids = [hd.pid] + wpids
        # series routing
        sine = subprocess.Popen(["jack_simple_client"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        procs.append(sine)
        time.sleep(2)
        sh = lambda *a: subprocess.run(a, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sh("jack_disconnect", "jack_simple_client:output1", "system:playback_1")
        sh("jack_disconnect", "jack_simple_client:output2", "system:playback_2")
        sh("jack_connect", "jack_simple_client:output1", "effect_0:in_1")
        ports = subprocess.run(["jack_lsp"], env=env, capture_output=True, text=True).stdout.split()
        tail = f"effect_{n-1}:out_1"
        if mode == "individual":
            for i in range(n - 1):
                sh("jack_connect", f"effect_{i}:out_1", f"effect_{i+1}:in_1")
        else:
            # a chain of CLAP members is ONE client: the head's ports are the chain's ports
            tail = tail if tail in ports else "effect_0:out_1"
        if stress:
            for _ in range(8):
                busy.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
            time.sleep(2)
        peak = subprocess.Popen(["./jackpeak", tail, str(WINDOW + 2)], env=env, stdout=subprocess.PIPE, text=True)
        time.sleep(1)
        a = pids_stats(pids); ta = time.monotonic()
        time.sleep(WINDOW)
        b = pids_stats(pids); tb = time.monotonic()
        out = peak.communicate()[0]
        m = re.search(r"cpu_avg ([\d.]+) cpu_max ([\d.]+) xruns (\d+) peak ([\d.]+)", out)
        dt = tb - ta
        row = dict(rate=rate, n=n, mode=mode, stress=stress, processes=len(pids), jack_clients=len({p.split(':')[0] for p in ports if p.startswith('effect_')}), rss_mb=round((b[0]) / 1024, 1), pss_mb=round(b[1] / 1024, 1),
                   cpu_pct=round((b[2] - a[2]) / TCK / dt * 100, 2), ctx_switches=b[3] - a[3], dsp_load_avg=float(m[1]), dsp_load_max=float(m[2]),
                   xruns=int(m[3]), peak=float(m[4]), add_ms=round(add_ms))
        return row
    finally:
        for p in busy + [x for x in procs if x is not hd and x is not jack]:
            p.kill()
        try: h.call("quit")
        except Exception: pass
        hd.terminate()
        try: hd.wait(5)
        except subprocess.TimeoutExpired: hd.kill()
        jack.terminate()
        try: jack.wait(5)
        except subprocess.TimeoutExpired: jack.kill()
        subprocess.run(["pkill", "-f", "omx-clap-host"], stderr=subprocess.DEVNULL)
        time.sleep(2)

out = open("gvp.jsonl", "a")
for rate in RATES:
    for n in NS:
        for stress in (False, True):
            for mode in ("grouped", "individual"):
                try:
                    r = run(rate, n, mode, stress)
                except Exception as e:
                    r = dict(rate=rate, n=n, mode=mode, stress=stress, error=str(e))
                print(json.dumps(r), flush=True); out.write(json.dumps(r) + "\n"); out.flush()

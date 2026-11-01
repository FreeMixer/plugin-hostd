#!/usr/bin/env python3
# Cold host to a loaded snapshot on the Pi's full LV2 world: the host started fresh, then every plugin of the set added;
# the time from the start to the last reply. mod-host scans the whole world at its start; hostd adds into a chain
# (chain_expect) and adds own what the chain refuses, as Zynthian does. A private dummy JACK server; 3 repeats, medians.
import os, socket, subprocess, sys, tempfile, time, signal, statistics as st, shutil
COMP, DELAY, DRIVE = ("clap:/usr/lib/clap/omx-%s.clap#org.openmixer.%s" % (k, k) for k in ("comp", "delay", "drive"))
CALF = "http://calf.sourceforge.net/plugins/Compressor"
SETS = {
    "24 plugins": {"clap": [COMP, "lv2:" + CALF, DELAY, DRIVE] * 6,
                   "lv2": ["urn:openmixer:comp", CALF, "urn:openmixer:delay", "urn:openmixer:drive"] * 6},
    "ten third-party": {"lv2": ["http://distrho.sf.net/plugins/3BandEQ", "http://distrho.sf.net/plugins/MVerb",
                                "http://gareus.org/oss/lv2/fil4#stereo", "http://guitarix.sourceforge.net/plugins/gx_flanger#_flanger",
                                "http://guitarix.sourceforge.net/plugins/gx_reverb_stereo#_reverb_stereo",
                                "http://invadarecords.com/plugins/lv2/compressor/stereo", "http://invadarecords.com/plugins/lv2/erreverb/sum",
                                "urn:zamaudio:ZamComp", "urn:zamaudio:ZamEQ2", "urn:zamaudio:ZamDelay"]},
}
SETS["ten third-party"]["clap"] = ["lv2:" + u for u in SETS["ten third-party"]["lv2"]]
SERVER = "omxcold"
env = dict(os.environ, JACK_DEFAULT_SERVER=SERVER)

def conn(port, limit=60):
    end = time.monotonic() + limit
    while True:
        try:
            c = socket.create_connection(("127.0.0.1", port)); c.settimeout(120); return c
        except OSError:
            if time.monotonic() > end: raise
            time.sleep(0.002)

def call(s, l):
    s.sendall(l.encode() + b"\0"); b = b""
    while b"\0" not in b: b += s.recv(65536)
    return b.split(b"\0")[0].decode()

def run(host, uris, port):
    tmp = tempfile.mkdtemp(prefix="coldsnap-")
    if host == "mod-host":
        argv = ["mod-host", "-n", "-p", str(port), "-f", str(port + 1)]
    elif host == "omx-clap-host":
        argv = ["omx-clap-host", "-n", "-p", str(port), "-f", str(port + 1)]
    else:
        open(f"{tmp}/c.conf", "w").write(f"clap_host omx-clap-host\nlv2_worker omx-clap-host\nrequire_pins 0\nstate_root {tmp}\n")
        argv = ["plugin-hostd", "-n", "-p", str(port), "-c", f"{tmp}/c.conf"]
    t0 = time.monotonic()
    p = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    s = conn(port)
    if host != "plugin-hostd":
        conn(port + 1)
    ready = time.monotonic() - t0
    own = 0
    for i, u in enumerate(uris, 1):
        if host == "plugin-hostd":
            r = call(s, f"add {u} {i} chain:1")
            if r == "resp -501":
                own += 1; r = call(s, f"add {u} {i} own")
        else:
            r = call(s, f"add {u} {i}")
        if not r.startswith(f"resp {i}"):
            print("  refused", host, u, r)
    total = time.monotonic() - t0
    os.killpg(p.pid, signal.SIGKILL); p.wait()
    # only the workers of this daemon: their ports were given by it, so match by the parent's session
    subprocess.run(["pkill", "-KILL", "-s", str(p.pid)], stderr=subprocess.DEVNULL)
    time.sleep(1)
    shutil.rmtree(tmp, ignore_errors=True)
    return ready * 1000, total * 1000, own

jack = subprocess.Popen(["jackd", "-n", SERVER, "-d", "dummy", "-r", "48000", "-p", "256"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True)
time.sleep(2)
port = 6400
try:
    for name, uris in SETS.items():
        for host, key in (("mod-host", "lv2"), ("omx-clap-host", "clap"), ("plugin-hostd", "clap")):
            res = []
            for rep in range(3):
                port += 4
                res.append(run(host, uris[key], port))
            r = [x[0] for x in res]; t = [x[1] for x in res]
            print(f"{name:16s} {host:14s} start to answering {st.median(r):6.0f} ms | cold to loaded {st.median(t):6.0f} ms [{min(t):.0f}, {max(t):.0f}]"
                  + (f" | {res[0][2]} added own" if res[0][2] else ""), flush=True)
finally:
    os.killpg(jack.pid, signal.SIGTERM)

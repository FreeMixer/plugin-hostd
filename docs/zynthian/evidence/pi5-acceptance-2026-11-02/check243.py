#!/usr/bin/env python3
"""omx-plugins#243 on the device: two omx plugins chained in plugin-hostd's default mode, the replies as they come.
The daemon reads a copy of the device's own settings (/zynthian/config/plugin-hostd.conf: require_pins 1, the system
pin file), with only its state directory moved to a private one, on a private dummy JACK server."""
import os, re, shutil, signal, socket, subprocess, sys, tempfile, threading, time

def connect(port):
    end = time.monotonic() + 30
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port)); s.settimeout(60); return s
        except OSError:
            if time.monotonic() > end: raise
            time.sleep(0.01)

def call(s, line):
    s.sendall(line.encode() + b"\0"); b = b""
    while b"\0" not in b: b += s.recv(65536)
    r = b.split(b"\0")[0].decode(errors="replace")
    print("> %s\n< %s" % (line, r), flush=True)
    return r

work = tempfile.mkdtemp(prefix="check243-")
conf = open("/zynthian/config/plugin-hostd.conf").read()
conf = re.sub(r"(?m)^state_root .*$", "state_root %s/state" % work, conf)
open(os.path.join(work, "plugin-hostd.conf"), "w").write(conf)
print("settings (comments left out):")
for l in conf.splitlines():
    if l.strip() and not l.startswith("#"): print("  " + l)
name = "c243%d" % os.getpid(); env = dict(os.environ, JACK_DEFAULT_SERVER=name)
jack = subprocess.Popen(["jackd", "-n", name, "-d", "dummy", "-r", "48000", "-p", "256"], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
time.sleep(2)
d = subprocess.Popen(["plugin-hostd", "-n", "-p", "5830", "-f", "5831", "-c", os.path.join(work, "plugin-hostd.conf")],
                     env=env, stdout=open(os.path.join(work, "d.log"), "w"), stderr=subprocess.STDOUT, start_new_session=True)
fbl = []
try:
    fb = connect(5831)
    def drain():
        b = b""
        while True:
            try: c = fb.recv(65536)
            except OSError: return
            if not c: return
            b += c
            while b"\0" in b:
                l, b = b.split(b"\0", 1); fbl.append(l.decode(errors="replace"))
    threading.Thread(target=drain, daemon=True).start()
    s = connect(5830)
    a, b = "clap:/usr/lib/clap/omx-eq8.clap#org.openmixer.eq8", "clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp"
    call(s, "add %s 1" % a); call(s, "add %s 2" % b)
    call(s, "chain 1 1 2")
    end = time.monotonic() + 10
    while time.monotonic() < end:
        r = call(s, "chain_get 1") if time.monotonic() > end - 9.9 else None
        f = (r or "").split()
        if len(f) >= 5 and f[4] == "1,2": break
        time.sleep(0.5)
    call(s, "worker_list")
    print("feedback:", fbl)
    with open(os.path.join(work, "d.log")) as f:
        lines = [l.rstrip() for l in f if l.strip()]
    print("daemon log (last 8 lines):"); [print("  " + l) for l in lines[-8:]]
finally:
    for p in (d, jack):
        try: os.killpg(p.pid, signal.SIGTERM); p.wait(10)
        except Exception: pass
    shutil.rmtree(work, ignore_errors=True)

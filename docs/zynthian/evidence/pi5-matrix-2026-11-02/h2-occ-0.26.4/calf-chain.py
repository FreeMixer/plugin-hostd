#!/usr/bin/env python3
"""N instances of one LV2 plugin added into chain 1 of plugin-hostd on a private dummy JACK server: the abi_clobber line its worker says, if any.

    calf-chain.py [--uri URI] [--count 24] [--seconds 6] [--port 5790]

Prints every feedback line that names abi_clobber or quarantine, the worker logs' lines about it, and the versions.
Starts its own jackd (dummy driver, its own name) and plugin-hostd (require_pins 0, its own state directory), and stops
both, with their process groups, at the end."""
import argparse
import glob
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


def connect(port, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("nothing listens on %d" % port)


def cmd(s, line):
    s.sendall(line.encode() + b"\0")
    buf = b""
    while b"\0" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            raise SystemExit("the daemon closed the connection on " + line)
        buf += chunk
    return buf.split(b"\0")[0].decode(errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="http://calf.sourceforge.net/plugins/Compressor")
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--port", type=int, default=5790)
    ap.add_argument("--count", type=int, default=24)
    a = ap.parse_args()
    # jack2's own libjack, never another JACK (a PipeWire libjack would put the worker on the machine's own graph)
    pw = os.path.isdir("/usr/lib64/pipewire-0.3/jack") or os.path.isdir("/usr/lib/aarch64-linux-gnu/pipewire-0.3/jack")
    if pw:
        os.environ["LD_LIBRARY_PATH"] = "/usr/lib64"
        for prog in ("omx-clap-host", "plugin-hostd", "jackd"):
            out = subprocess.run(["ldd", shutil.which(prog)], capture_output=True, text=True).stdout
            jl = [l for l in out.splitlines() if "libjack.so" in l]
            if jl and "pipewire" in jl[0]:
                raise SystemExit("%s would load %s: refused" % (prog, jl[0].strip()))
    work = tempfile.mkdtemp(prefix="calf-chain-")
    name = "cc%d" % os.getpid()
    env = dict(os.environ, JACK_DEFAULT_SERVER=name, JACK_NO_AUDIO_RESERVATION="1")
    procs = []
    try:
        jlog = open(os.path.join(work, "jackd.log"), "w")
        procs.append(subprocess.Popen(["jackd", "-n", name, "-d", "dummy", "-r", "48000", "-p", "256"], env=env,
                                      stdout=jlog, stderr=subprocess.STDOUT, start_new_session=True))
        time.sleep(2)
        conf = os.path.join(work, "plugin-hostd.conf")
        with open(conf, "w") as f:
            f.write("require_pins 0\nstate_root %s/state\n" % work)
        hlog = open(os.path.join(work, "plugin-hostd.log"), "w")
        procs.append(subprocess.Popen(["plugin-hostd", "-n", "-p", str(a.port), "-f", str(a.port + 1), "-c", conf], env=env, stdout=hlog,
                                      stderr=subprocess.STDOUT, start_new_session=True))
        fb = connect(a.port + 1)
        ctl = connect(a.port)
        for i in range(a.count):
            r = cmd(ctl, "add %s %d chain:1" % (a.uri, i))
            if not r.startswith("resp %d" % i):
                print("add %d: %s" % (i, r))
        want = ",".join(map(str, range(a.count)))
        end = time.monotonic() + 30
        while True:
            f = cmd(ctl, "chain_get 1").split()
            if len(f) >= 5 and f[2] != "-" and f[4] == want:
                print("chain formed: %d/%d members: %s" % (a.count, a.count, " ".join(f)))
                break
            if time.monotonic() > end:
                print("chain NOT formed: %s" % " ".join(f))
                break
            time.sleep(0.05)
        time.sleep(1)
        for p in list(procs):
            for pid in [p.pid] + [int(x) for x in subprocess.run(["pgrep", "-g", str(p.pid)], capture_output=True,
                                                                    text=True).stdout.split()]:
                try:
                    maps = open("/proc/%d/maps" % pid).read()
                except OSError:
                    continue
                if "pipewire-0.3/jack" in maps:
                    raise SystemExit("process %d mapped PipeWire's libjack: stopped" % pid)
        fb.settimeout(0.5)
        buf, end = b"", time.monotonic() + a.seconds
        while time.monotonic() < end:
            try:
                chunk = fb.recv(65536)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                pass
        lines = [x.decode(errors="replace") for x in buf.split(b"\0") if x]
        hits = [x for x in lines if "abi_clobber" in x or "quarantin" in x]
        print("feedback lines: %d; about the guard: %d" % (len(lines), len(hits)))
        for x in hits:
            print("  " + x)
        print("worker_list:", cmd(ctl, "worker_list"))
        hlog.flush()
        for path in [os.path.join(work, "plugin-hostd.log")] + glob.glob(os.path.join(work, "state", "**", "*.log"), recursive=True):
            with open(path, errors="replace") as f:
                for line in f:
                    if "clobber" in line or "callee" in line or "register" in line:
                        print("  %s: %s" % (os.path.basename(path), line.rstrip()))
        for p in ("omx-clap-host", "plugin-hostd"):
            print("%s: %s" % (p, subprocess.run([p, "--version"], capture_output=True, text=True).stdout.strip().splitlines()[:1]))
        print("machine:", os.uname().machine)
    finally:
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

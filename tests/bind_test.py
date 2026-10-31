# SPDX-License-Identifier: GPL-3.0-or-later
# Who reaches the daemon's ports. By default a program on this machine at 127.0.0.1, and nobody at any other address:
# 127.0.0.2 (also this machine, refused by a port bound to 127.0.0.1 alone, so the arm runs on a host with no network)
# and the machine's address off the loopback when it has one. --bind-address and bind_address in the settings widen it.
# Reached means the daemon answers a command there, on the command port, and a feedback connect succeeds.
import os, re, shutil, socket, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", "./plugin-hostd"))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", "tests/fake-host"))

failed = []


def off_loopback():
    """the address this machine sends from, or None: a UDP connect only picks a route, it sends nothing"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.connect(("192.0.2.1", 9))
            addr = u.getsockname()[0]
    except OSError:
        return None
    return None if addr.startswith("127.") else addr


def answers(address, port):
    """whether a command sent to address:port is answered"""
    try:
        with socket.create_connection((address, port), timeout=2) as s:
            s.settimeout(5)
            s.sendall(b"worker_list\0")
            buf = b""
            while b"\0" not in buf:
                c = s.recv(4096)
                if not c:
                    return False
                buf += c
            return buf.startswith(b"resp ")
    except OSError:
        return False


def connects(address, port):
    try:
        socket.create_connection((address, port), timeout=2).close()
        return True
    except OSError:
        return False


def start(tmp, args=(), conf=(), ports=None):
    cmd, fb = ports or harness.port_pair()
    path = os.path.join(tmp, "plugin-hostd.conf")
    with open(path, "w") as f:
        for k, v in (("mod_host", FAKE), ("clap_host", FAKE), ("state_root", tmp), ("require_pins", 0), ("pins_dir", ""),
                     ("history_file", tmp + "/history"), ("descriptor_dir", tmp + "/descriptors"),
                     ("qualification_dir", tmp + "/qualification"), ("probe", tmp + "/no-probe")) + tuple(conf):
            f.write("%s %s\n" % (k, v))
    p = subprocess.Popen([EXE, "-n", "-p", str(cmd), "-f", str(fb), "-c", path, *args], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    for line in iter(p.stdout.readline, b""):
        if line.decode().rstrip("\n") == harness.READY_LINE:
            return p, cmd, fb
    p.wait()
    return p, None, None


def stop(p):
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def arm(name, reached, refused, args=(), conf=()):
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-bind.")
    p, cmd, fb = start(tmp, args, conf)
    try:
        if cmd is None:
            failed.append("%s: the daemon did not start (exit %s)" % (name, p.returncode))
            return
        # the feedback connect comes after the commands: the first command waits for a controller on the feedback port
        for address in reached:
            if not connects(address, fb):
                failed.append("%s: the feedback port does not answer at %s" % (name, address))
            if not answers(address, cmd):
                failed.append("%s: the command port does not answer at %s" % (name, address))
        for address in refused:
            if connects(address, fb):
                failed.append("%s: the feedback port is reached at %s" % (name, address))
            if connects(address, cmd):
                failed.append("%s: the command port is reached at %s" % (name, address))
        print("%s: reached at %s, refused at %s" % (name, reached, refused))
    finally:
        stop(p)
        shutil.rmtree(tmp, ignore_errors=True)


def refused_to_start(name, args=(), conf=()):
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-bind.")
    p, cmd, _ = start(tmp, args, conf)
    if cmd is not None:
        stop(p)
        failed.append("%s: the daemon started" % name)
    elif p.returncode == 0:
        failed.append("%s: the daemon exited 0" % name)
    else:
        print("%s: the daemon refuses to start, exit %d" % (name, p.returncode))
    shutil.rmtree(tmp, ignore_errors=True)


def refused_when_held(name, which):
    """the port taken by another program: the daemon that cannot listen on it does not start"""
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-bind.")
    ports = harness.port_pair()
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", ports[which]))
        holder.listen(1)
        p, cmd, _ = start(tmp, ports=ports)
        if cmd is not None:
            stop(p)
            failed.append("%s: the daemon started" % name)
        elif p.returncode == 0:
            failed.append("%s: the daemon exited 0" % name)
        else:
            print("%s: the daemon refuses to start, exit %d" % (name, p.returncode))
    shutil.rmtree(tmp, ignore_errors=True)


nic = off_loopback()
others = ["127.0.0.2"] + ([nic] if nic else [])
if not nic:
    print("NOT RUN: no address off the loopback on this machine; 127.0.0.2 stands for it")

arm("by default", ["127.0.0.1"], others)
arm("--bind-address 0.0.0.0", ["127.0.0.1"] + others, [], args=("--bind-address", "0.0.0.0"))
arm("-b 0.0.0.0", ["127.0.0.1"] + others, [], args=("-b", "0.0.0.0"))
arm("bind_address 0.0.0.0 in the settings", ["127.0.0.1"] + others, [], conf=(("bind_address", "0.0.0.0"),))
arm("the option over the settings", ["127.0.0.1"], others, args=("-b", "127.0.0.1"), conf=(("bind_address", "0.0.0.0"),))
if nic:
    arm("one named address", [nic], ["127.0.0.1"], args=("-b", nic))
refused_to_start("--bind-address localhost", args=("--bind-address", "localhost"))
refused_to_start("bind_address ::1 in the settings", conf=(("bind_address", "::1"),))
refused_to_start("an address of no interface", args=("-b", "192.0.2.1"))
refused_when_held("the command port held by another program", 0)
refused_when_held("the feedback port held by another program", 1)

if failed:
    print("FAIL %d:\n  %s" % (len(failed), "\n  ".join(failed)))
    sys.exit(1)
print("ok   the ports are reached where they were asked to be and nowhere else")

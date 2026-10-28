#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# The two protocol clients plugin-hostd-tests ships (tests/lib/protocol.sh, tests/lib/plugin_hostd_client.py) against a
# peer that answers in NUL-ended replies, split across writes, then its sabotage: a copy of each client that frames by
# newline instead of NUL must fail the same checks, so the checks can tell a client that frames wrongly.
import os, re, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")


def serve(srv, stop):
    """echo "resp <line>" as one reply, written in two pieces; "mute" is never answered; "bye" closes"""
    while not stop.is_set():
        try:
            c, _ = srv.accept()
        except OSError:
            return
        buf = b""
        while True:
            try:
                d = c.recv(4096)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\0" in buf:
                line, buf = buf.split(b"\0", 1)
                if line == b"mute":
                    continue
                if line == b"bye":
                    c.close()
                    break
                reply = b"resp " + line + b"\0"
                c.sendall(reply[:3])
                time.sleep(0.02)
                c.sendall(reply[3:])
        c.close()


def shell(lib, port, script):
    """a bash that opens the peer on descriptor 3, sources `lib` and runs `script`; its stdout, stderr and status"""
    body = 'exec 3<>/dev/tcp/127.0.0.1/%d\n. %s\n%s' % (port, lib, script)
    p = subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=30)
    return p.stdout, p.stderr, p.returncode


def check_shell(lib, port, failures):
    out, _, rc = shell(lib, port, 'PROTOCOL_TIMEOUT=2; send "add x 0"; protocol_send 3 2 "a b"')
    if out != "resp add x 0\nresp a b\n":
        failures.append("shell send: %r" % out)
    _, _, rc = shell(lib, port, 'protocol_expect 3 2 "ping" "resp ping"')
    if rc != 0:
        failures.append("shell expect of the right reply returned %d" % rc)
    _, err, rc = shell(lib, port, 'protocol_expect 3 2 "ping" "resp pong"')
    if rc == 0 or "resp ping" not in err:
        failures.append("shell expect of the wrong reply returned %d, said %r" % (rc, err))
    with tempfile.NamedTemporaryFile("w", suffix=".log") as log:
        _, _, rc = shell(lib, port, 'protocol_wait_ready %s 2' % log.name)
        if rc == 0:
            failures.append("a log without the marker was ready")
        log.write("starting\nplugin-hostd ready!\n")
        log.flush()
        _, _, rc = shell(lib, port, 'protocol_wait_ready %s 2' % log.name)
        if rc != 0:
            failures.append("a log with the marker was not ready")


def check_python(libdir, port, failures):
    sys.path.insert(0, libdir)
    sys.modules.pop("plugin_hostd_client", None)
    import plugin_hostd_client as m
    c = m.Client.connect(port)
    if c.send("add x 0") != "resp add x 0":
        failures.append("python send")
    if c.expect("ping", "resp ping") != "resp ping":
        failures.append("python expect")
    try:
        c.expect("ping", "resp pong")
        failures.append("python expect of the wrong reply raised nothing")
    except AssertionError:
        pass
    if c.try_send("mute", 0.2) != (None, "timeout"):
        failures.append("python timeout")
    c2 = m.Client.connect(port)
    if c2.try_send("bye", 1) != (None, "closed"):
        failures.append("python closed")
    sys.path.pop(0)


def run(libsh, libpy, port, failures):
    check_shell(libsh, port, failures)
    check_python(libpy, port, failures)


def main():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = srv.getsockname()[1]
    stop = threading.Event()
    for _ in range(8):
        threading.Thread(target=serve, args=(srv, stop), daemon=True).start()
    good = []
    run(os.path.join(LIB, "protocol.sh"), LIB, port, good)
    if good:
        print("FAIL the clients:", *good, sep="\n  ")
        return 1
    print("ok: the shell and the python client frame by NUL, split replies, time out and close")
    # sabotage: frame by newline, and the same checks must fail
    with tempfile.TemporaryDirectory() as d:
        sh = open(os.path.join(LIB, "protocol.sh")).read().replace("'%s\\0'", "'%s\\n'").replace("-d ''", "-d $'\\n'")
        py = open(os.path.join(LIB, "plugin_hostd_client.py")).read().replace('b"\\0"', 'b"\\n"')
        if sh == open(os.path.join(LIB, "protocol.sh")).read() or py == open(os.path.join(LIB, "plugin_hostd_client.py")).read():
            print("FAIL the sabotage changed nothing")
            return 1
        open(os.path.join(d, "protocol.sh"), "w").write(sh)
        open(os.path.join(d, "plugin_hostd_client.py"), "w").write(py)
        bad_sh, bad_py = [], []
        check_shell(os.path.join(d, "protocol.sh"), port, bad_sh)
        try:
            check_python(d, port, bad_py)
        except Exception as e:
            bad_py.append(repr(e))
        if not bad_sh or not bad_py:
            print("FAIL a client that frames by newline passed: shell %r, python %r" % (bad_sh, bad_py))
            return 1
    print("ok: a client that frames by newline fails the same checks")
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())

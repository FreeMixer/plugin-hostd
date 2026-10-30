# SPDX-License-Identifier: GPL-3.0-or-later
# issue 238: a connect made once, with no retry, right after the ready line is accepted, on the command port and on the
# feedback port, in every one of many starts. The line is read from the daemon's pipe as it is written, so the connect
# is as close behind it as a controller's can be.
import os, socket, subprocess, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", "./plugin-hostd"))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", "tests/fake-host"))
STARTS = int(os.environ.get("READY_CONNECT_STARTS", "150"))


def start_and_connect():
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-ready.")
    try:
        cmd, fb = harness.port_pair()
        conf = os.path.join(tmp, "plugin-hostd.conf")
        with open(conf, "w") as f:
            for k, v in (("mod_host", FAKE), ("clap_host", FAKE), ("state_root", tmp), ("require_pins", 0), ("pins_dir", ""),
                         ("history_file", tmp + "/history"), ("descriptor_dir", tmp + "/descriptors"),
                         ("qualification_dir", tmp + "/qualification"), ("probe", tmp + "/no-probe")):
                f.write("%s %s\n" % (k, v))
        p = subprocess.Popen([EXE, "-n", "-p", str(cmd), "-f", str(fb), "-c", conf], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        try:
            for line in iter(p.stdout.readline, b""):
                if line.decode().rstrip("\n") == harness.READY_LINE:
                    break
            else:
                return ["the daemon ended before its ready line"]
            refused = []
            for name, port in (("command", cmd), ("feedback", fb)):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=5).close()
                except OSError as e:
                    refused.append("%s port %d: %s" % (name, port, e))
            return refused
        finally:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                return ["the daemon did not end on SIGTERM sent right after its ready line"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


failed = []
for n in range(STARTS):
    failed += ["start %d: %s" % (n, r) for r in start_and_connect()]
if failed:
    print("FAIL %d of %d starts:\n  %s" % (len(failed), STARTS, "\n  ".join(failed[:10])))
    sys.exit(1)
print("ok   %d starts, each accepted its first connect on both ports and ended on SIGTERM" % STARTS)

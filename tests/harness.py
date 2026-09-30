# The daemon under test and a controller for it: a command socket, a feedback socket read on a thread, and
# helpers that wait for what the daemon does instead of sleeping and hoping.
import json, os, re, shutil, signal, socket, subprocess, tempfile, threading, time

# The protocol the daemon declares, read from the file a consumer reads: the tree's own, or PLUGIN_HOSTD_PROTOCOL (the
# installed package's /usr/share/plugin-hostd/protocol.json, in the smoke test of a package). No value of it is
# spelled in a test.
with open(os.environ.get("PLUGIN_HOSTD_PROTOCOL",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "protocol", "plugin-hostd.json"))) as f:
    DECLARED = json.load(f)
CODE = {e["name"]: e["code"] for e in DECLARED["errors"]}
READY_LINE = DECLARED["readiness"]["daemon_line"]


def resp(name):
    """the reply for a declared error, by its name: resp(\"GAVE_UP\") is "resp -505" while the header says so"""
    return "resp %d" % CODE[name]


DAEMONS = []


class Fail(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Fail(what)


def port_pair():
    socks = []
    ports = []
    for _ in range(2):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        # a process that goes while its stat is read answers ESRCH to the read
        return False


def wait_for(cond, what, timeout=10.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise Fail("timed out waiting for " + what)


class Daemon:
    def __init__(self, exe, worker, clap_worker=None, conf=None, env=None, feedback=True):
        self.exe = exe
        DAEMONS.append(self)
        self.tmp = tempfile.mkdtemp(prefix="plugin-hostd-test.")
        self.cmd_port, self.fb_port = port_pair()
        settings = {
            "mod_host": worker, "clap_host": clap_worker or worker, "state_root": self.tmp,
            "backoff_base_ms": 20, "backoff_max_ms": 80, "checkpoint_ms": 600000, "ready_timeout_ms": 4000,
            "rpc_timeout_ms": 1500, "idle_ms": 10,
            # the tests of placement, replay and attribution add plugins no one pinned; the pin tests turn it back on,
            # and a None leaves a setting out of the file, so the daemon's own default holds
            "require_pins": 0,
        }
        settings.update(conf or {})
        self.conf = os.path.join(self.tmp, "plugin-hostd.conf")
        with open(self.conf, "w") as f:
            for k, v in settings.items():
                if v is not None:
                    f.write("%s %s\n" % (k, v))
        e = dict(os.environ)
        e.update(env or {})
        args = [exe, "-n", "-p", str(self.cmd_port), "-c", self.conf]
        if feedback:
            args += ["-f", str(self.fb_port)]
        self.out = open(os.path.join(self.tmp, "daemon.out"), "w+")
        self.proc = subprocess.Popen(args, stdout=self.out, stderr=subprocess.STDOUT, env=e)
        wait_for(lambda: READY_LINE in self.log().splitlines(), "the readiness line")
        self.events = []
        self.lock = threading.Lock()
        self.sock = socket.create_connection(("127.0.0.1", self.cmd_port), timeout=10)
        self.fb = socket.create_connection(("127.0.0.1", self.fb_port), timeout=10) if feedback else None
        if self.fb:
            self.fb.settimeout(None)   # silence on the feedback port is not an error
            threading.Thread(target=self._read_feedback, daemon=True).start()

    def log(self):
        self.out.flush()
        with open(self.out.name) as f:
            return f.read()

    def _read_feedback(self):
        buf = b""
        while True:
            try:
                c = self.fb.recv(4096)
            except OSError:
                return
            if not c:
                return
            buf += c
            while b"\0" in buf:
                line, buf = buf.split(b"\0", 1)
                with self.lock:
                    self.events.append(line.decode())

    def send(self, msg):
        self.sock.sendall(msg.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            c = self.sock.recv(65536)
            if not c:
                raise Fail("daemon closed on " + msg)
            buf += c
        return buf[:-1].decode()

    def ok(self, msg, expect=None):
        r = self.send(msg)
        check(r == (expect if expect is not None else r) and r.startswith("resp") and
              (expect is not None or not r.startswith("resp -")), "%s -> %r (wanted %r)" % (msg, r, expect or "resp >= 0"))
        return r

    def expect(self, msg, expect):
        r = self.send(msg)
        check(r == expect, "%s -> %r, wanted %r" % (msg, r, expect))

    def until_ok(self, msg, timeout=5.0):
        """a jack port is announced to the other clients a moment after it is registered: ask again"""
        end = time.monotonic() + timeout
        while True:
            r = self.send(msg)
            if r == "resp 0":
                return
            if time.monotonic() > end:
                raise Fail("%s -> %r after %.0f s" % (msg, r, timeout))
            time.sleep(0.05)

    def workers(self):
        r = self.send("worker_list")
        parts = r.split()
        check(parts[0] == "resp" and int(parts[1]) == len(parts) - 2, "worker_list shape: " + r)
        out = {}
        for rec in parts[2:]:
            head, insts = rec.rsplit(":", 1)
            k, pid, fmt, state, place = head.split(":", 4)
            out[k] = {"pid": int(pid), "fmt": fmt, "state": state, "place": place,
                      "inst": [] if insts == "-" else [int(x) for x in insts.split(",")]}
        return out

    def holder(self, inst):
        for k, w in self.workers().items():
            if inst in w["inst"]:
                return k, w
        raise Fail("no worker holds instance %d" % inst)

    def wait_event(self, prefix, timeout=10.0, since=0):
        def find():
            if self.proc.poll() is not None:
                raise Fail("the daemon exited with %s: %s" % (self.proc.returncode, self.log()[-600:]))
            with self.lock:
                for i, e in enumerate(self.events):
                    if i >= since and e.startswith(prefix):
                        return e
            return None
        return wait_for(find, "event '%s' (have %s)" % (prefix, self.events), timeout)

    def mark(self):
        with self.lock:
            return len(self.events)

    def wait_up(self, inst, timeout=10.0):
        return wait_for(lambda: self._up(inst), "instance %d up" % inst, timeout)

    def _up(self, inst):
        for k, w in self.workers().items():
            if inst in w["inst"] and w["state"] == "up":
                return k, w
        return None

    def close(self, kill_workers=True):
        self.snap = "daemon exit %s, events %s, log:\n%s" % (self.proc.poll(), self.events[-12:], self.log()[-800:])
        try:
            self.sock.settimeout(3)
            self.snap += "\nworkers: " + self.send("worker_list")
        except Exception as e:
            self.snap += "\nworker_list failed: %r" % (e,)
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)


def run_tests(tests):
    only = os.environ.get("ONLY")
    failed = 0
    for name, fn in tests:
        if only and only != name:
            continue
        del DAEMONS[:]
        try:
            fn()
            print("ok   " + name, flush=True)
        except (Fail, Exception) as e:
            failed += 1
            print("FAIL %s: %s" % (name, e if isinstance(e, Fail) else "%s: %s" % (type(e).__name__, e)), flush=True)
            for d in DAEMONS:
                print("     " + getattr(d, "snap", "daemon not closed"), flush=True)
    print("%s (%d failed)" % ("plugin-hostd tests FAILED" if failed else "plugin-hostd tests ok", failed))
    return 1 if failed else 0

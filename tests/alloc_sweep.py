# SPDX-License-Identifier: GPL-3.0-or-later
# The daemon when memory runs out, wherever it runs out. One run of the scenario below lists the places in the daemon that
# ask for memory; then the scenario runs with each of those refused, its first asking, its second, and from its first
# asking on every allocation of the daemon. Whatever is refused the daemon does not die of it: it answers every command, or
# says at start that it cannot start, and after a single refusal it still answers. A command it has no memory for may be
# refused, and which command that is depends on the run: the test holds the daemon to living, not to a reply.
import concurrent.futures, hashlib, json, os, shutil, signal, socket, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

EXE = os.path.abspath(os.environ.get("ALLOC_SWEEP_DAEMON", "tests/plugin-hostd-alloc-fail"))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", "tests/fake-host"))
JOBS = int(os.environ.get("ALLOC_SWEEP_JOBS", "4"))
# The daemons of this sweep run side by side, and their workers take ports the kernel hands out. A daemon's command port from
# that same range can be given to a worker of the next daemon, and the protocol library opens its ports with SO_REUSEPORT:
# on one address the kernel shares connections between the two, and a controller lands on somebody else's worker. So the
# command ports come from below the kernel's range (tests/sabotage_pool.py draws arms from there too).
os.environ.setdefault("PLUGIN_HOSTD_TEST_PORT_BASE", "20000")
os.environ.setdefault("PLUGIN_HOSTD_TEST_PORT_SPAN", "12000")
LV2_URI = "urn:plugin-hostd:test:pinned"
LV2_URI_2 = "urn:plugin-hostd:test:second"
WAIT = "wait"
MANIFEST = """@prefix lv2: <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<%s> a lv2:Plugin ; lv2:binary <pinned.so> ; rdfs:seeAlso <pinned.ttl> .
"""
PLUGIN_TTL = """@prefix lv2: <http://lv2plug.in/ns/lv2core#> .
<%s> a lv2:Plugin ; lv2:port [ a lv2:InputPort , lv2:ControlPort ; lv2:index 0 ; lv2:symbol "gain" ; lv2:name "Gain" ;
  lv2:minimum 0 ; lv2:maximum 1 ; lv2:default 0.5 ] .
"""


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def clap_uri(tmp, n):
    return "clap:%s/clap/omx-%d.clap#org.openmixer.%d" % (tmp, n, n)


def scenario(tmp, layout):
    """every command reaches an allocation the table of plugin-hostd#174 names"""
    pins = ["pin_set %s omx-%d.clap=%s %s verdict=in-process" % (clap_uri(tmp, n), n, sha("%s/clap/omx-%d.clap" % (tmp, n)), layout)
            for n in (1, 2, 3)]
    return [
        "worker_list", *pins, "pin_reload",
        "add %s 0" % LV2_URI, "add %s 1" % clap_uri(tmp, 1), "add %s 2" % clap_uri(tmp, 2), "add %s 3" % clap_uri(tmp, 3),
        "add %s 4 pool:p" % clap_uri(tmp, 3), "add %s 5 pool:p" % clap_uri(tmp, 3),
        # no pin yet: learned on this add, with the layout the worker reports
        "add %s 9" % clap_uri(tmp, 4),
        "add %s 6" % LV2_URI_2, "add %s 10" % clap_uri(tmp, 2), "add %s 11" % clap_uri(tmp, 2),
        "set_bpm 120", "set_bpb 4",
        WAIT,
        "connect effect_1:out_1 system:playback_1", "connect effect_2:out_1 effect_3:in_1",
        "disconnect effect_2:out_1 effect_3:in_1",
        "param_set 1 gain 0.5", "param_set 1 gain 0.6", "param_set 2 gain 0.25", "preset_load 1 urn:preset:one",
        "track_info 1 Kick #ff8000", "track_info 0 Bass -", "remote_pages 0", "remote_page_get 0 0",
        "param_info 0 gain", "param_info 0 none", "param_info 1 gain",
        "instance_info 1", "chain 7 1 2", "chain_get 7", "chain 7 2 1", "chain 7 1 2 3", "chain_get 7",
        # the members' worlds are built for a chain of LV2 plugins
        "chain 12 0 6", "chain_get 12", "chain_clear 12",
        "worker_list", "chain_clear 7", "plan 8 1 2 3", "plan_get 8", "plan 8 2 3", "plan 13 4 5", "plan_get 13",
        "estimate 48000 256 %s %s" % (clap_uri(tmp, 1), LV2_URI), "estimate 48000 256 %s" % clap_uri(tmp, 4),
        # a connection replayed into a worker too young to have its ports is asked again
        "param_set 1 crash 1", WAIT,
        # a pool's member quarantined, its plan made again when it is cleared
        "param_set 4 crash 1", WAIT, "worker_list", "param_set 2 crashnow 1", "worker_list",
        "descriptor_get %s" % clap_uri(tmp, 1), "policy_set lv2 pool:x", "add %s 14" % LV2_URI, "policy_set * own",
        "quarantine_clear all", WAIT, "plan_clear 13", "plan_clear 8", "remove 3", "remove 0", "worker_list",
    ]


def one_run(site=None, nth=1, every_after=False):
    """(what went wrong or None, the log of the allocator, the replies): one scenario with that asking of `site` refused"""
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-alloc.")
    p = None
    try:
        for n in (1, 2, 3, 4):
            write("%s/clap/omx-%d.clap" % (tmp, n), b"clean pad %d" % n)
        for name, uri in (("pinned", LV2_URI), ("second", LV2_URI_2)):
            write("%s/lv2/%s.lv2/manifest.ttl" % (tmp, name), (MANIFEST % uri).encode())
            write("%s/lv2/%s.lv2/pinned.so" % (tmp, name), b"lv2 binary " + name.encode())
            write("%s/lv2/%s.lv2/pinned.ttl" % (tmp, name), (PLUGIN_TTL % uri).encode())
        # a qualification record: read as JSON whenever a plan or an estimate asks the plugin's cost
        doc = {"schema": "plugin-qualify.qualification-record/1", "plugin": {"format": "clap", "id": "org.openmixer.4"},
               "measurements": {"grid": [{"rate": 48000, "quantum": 256, "outcome": "probe.ok",
                                          "cost": {"median": 1000, "percentile": {"p": 95, "value": 2000}, "blocks": 100,
                                                   "warmupBlocks": 10}}]}}
        write("%s/qualification/org.openmixer.4@1.0-0123456789ab.default.qualification.json" % tmp, json.dumps(doc).encode())
        layout = subprocess.check_output([FAKE, "-L"], text=True).strip()
        cmds = scenario(tmp, layout)
        conf = "%s/plugin-hostd.conf" % tmp
        with open(conf, "w") as f:
            for k, v in (("mod_host", os.path.basename(FAKE)), ("clap_host", os.path.basename(FAKE)), ("state_root", tmp), ("require_pins", 1),
                         ("pin_mode", "first-use"), ("grouping", "on"), ("lv2_worker", "mod-host"),
                         ("lv2_path", tmp + "/lv2"), ("pin_store", tmp + "/pins"), ("pins_dir", tmp + "/pins.d"),
                         ("history_file", tmp + "/history"), ("descriptor_dir", tmp + "/descriptors"),
                         ("qualification_dir", tmp + "/qualification"), ("probe", shutil.which("true")),
                         ("backoff_base_ms", 10), ("backoff_max_ms", 20), ("ready_timeout_ms", 2000),
                         ("rpc_timeout_ms", 1000), ("idle_ms", 5), ("checkpoint_ms", 600000)):
                f.write("%s %s\n" % (k, v))
        log = "%s/alloc.log" % tmp
        # the workers are found on PATH; one younger than FAKE_CONNECT_AFTER_MS refuses a connect, as a jack client does
        env = dict(os.environ, ALLOC_FAIL_LOG=log, FAKE_CRASH_AFTER_MS="1", FAKE_CONNECT_AFTER_MS="15",
                   PATH=os.path.dirname(FAKE) + ":" + os.environ["PATH"])
        if site:
            env.update(ALLOC_FAIL_SITE=site, ALLOC_FAIL_NTH=str(nth))
        if every_after:
            env["ALLOC_FAIL_ALL"] = "1"
        cmd, fb = harness.port_pair()
        out = open("%s/daemon.out" % tmp, "w+")
        p = subprocess.Popen([EXE, "-n", "-p", str(cmd), "-f", str(fb), "-c", conf], stdout=out, stderr=subprocess.STDOUT,
                             env=env, start_new_session=True)
        deadline = time.monotonic() + 10
        while harness.READY_LINE not in open(out.name).read().splitlines():
            if p.poll() is not None:
                # it may say it cannot start, and exit; a signal is the thing this test exists for
                return (None if p.returncode > 0 else "at start, exit %d: %s" % (p.returncode, tail(out)), None, None)
            if time.monotonic() > deadline:
                return ("no ready line in 10 s: " + tail(out), None, None)
            time.sleep(0.005)
        s = socket.create_connection(("127.0.0.1", cmd), timeout=5)
        f = socket.create_connection(("127.0.0.1", fb), timeout=5)
        last = None
        replies = {}
        try:
            for c in cmds:
                if c == WAIT:
                    time.sleep(0.03)
                    continue
                last = c
                s.settimeout(8)
                s.sendall(c.encode() + b"\0")
                buf = b""
                while not buf.endswith(b"\0"):
                    got = s.recv(65536)
                    if not got:
                        return ("connection closed on %r, daemon exit %s: %s" % (c, p.poll(), tail(out)), None, None)
                    buf += got
                replies[c] = buf.rstrip(b"\0").decode()
                if not buf.startswith(b"resp "):
                    return ("%r was answered %r" % (c, buf[:80]), None, None)
        except OSError as e:
            return ("%r: %s, daemon exit %s: %s" % (last, e, p.poll(), tail(out)), None, None)
        s.close()
        f.close()
        if p.poll() is not None:
            return ("the daemon is gone after the scenario, exit %s: %s" % (p.returncode, tail(out)), None, None)
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return ("the daemon did not end on SIGTERM", None, None)
        if p.returncode not in (0, -signal.SIGTERM):
            return ("the daemon ended with %d: %s" % (p.returncode, tail(out)), None, None)
        return (None, open(log).read().split("\n"), replies)
    finally:
        if p and p.poll() is None:
            p.kill()
            p.wait()
        if p:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def tail(out):
    out.flush()
    return " | ".join(open(out.name).read().splitlines()[-3:])


err, log, replies = one_run()
if err:
    print("FAIL the scenario with no refusal: %s" % err)
    sys.exit(1)
# with nothing refused the scenario must go where it means to, or every later run passes for nothing
for command, reply in (("chain 7 1 2 3", "resp 0"), ("chain 12 0 6", "resp 0"), ("chain_clear 7", "resp 0"), ("plan_clear 8", "resp 0"),
                       ("remove 0", "resp 0"), ("param_info 0 gain", "resp 0 "), ("plan 8 1 2 3", "resp 0 1,2,3 ")):
    if not replies.get(command, "").startswith(reply):
        print("FAIL with no refusal %r answered %r, not %r" % (command, replies.get(command), reply))
        sys.exit(1)
sites = sorted({l.split()[1] for l in log if l.startswith("site ")})
print("the scenario asks for memory at %d places in the daemon" % len(sites))
arms = [dict(site=site, nth=nth, every_after=every) for site in sites for nth, every in ((1, False), (2, False), (1, True))]
failed = []


def arm(a):
    """daemons running side by side take their workers' ports from the system's free ones, and two can pick one port between
    its check and its bind: a run that gets no answer is run again, on other ports, before it counts. A daemon that hangs
    on a refusal hangs each time."""
    for _ in range(3):
        result = one_run(**a)
        if not (result[0] and "timed out" in result[0]):
            break
    return result


pool = concurrent.futures.ThreadPoolExecutor(JOBS)
for a, (err, _, _) in zip(arms, pool.map(arm, arms)):
    if err:
        failed.append("site %s, asking %d%s: %s" % (a["site"], a["nth"], " and all after it" if a["every_after"] else "", err))
        # the sabotage arms need only one
        if os.environ.get("ALLOC_SWEEP_FIRST_FAILURE"):
            break
pool.shutdown(wait=True, cancel_futures=True)
if failed:
    print("FAIL %d of %d runs:\n  %s" % (len(failed), len(arms), "\n  ".join(failed[:25])))
    sys.exit(1)
print("ok   %d runs, each with one place refused: the daemon lived through all" % len(arms))

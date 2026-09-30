# The real workers behind the daemon, over jack, in the namespace tests/jack_e2e.sh built.
import filecmp, os, signal, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Daemon, Fail, alive, check, run_tests, wait_for

EXE = os.environ["PLUGIN_HOSTD"]
CLAP_HOST = os.environ["OMX_CLAP_HOST"]
STRESS = "clap:%s#org.plugin-hostd.test.stress" % os.environ["STRESS_CLAP"]
LEVELS = os.environ["JACK_LEVELS"]
MOD_HOST = os.environ.get("MOD_HOST")
LV2_DIR = os.environ.get("LV2_DIR")
DELAY_URI = "urn:openmixer:dpf:delay"
TESTS = []
LEVEL, CRASH = 3, 0


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


def daemon(**kw):
    # the previous test's workers leave the graph a moment after they exit; a client of the same name would be renamed
    wait_for(lambda: not any(l.startswith("effect_") for l in links()), "the graph to hold no effect_ port", 10)
    conf = {}
    if LV2_DIR:
        conf["lv2_path"] = LV2_DIR
    conf.update(kw.pop("conf", {}))
    return Daemon(EXE, MOD_HOST or CLAP_HOST, clap_worker=CLAP_HOST, conf=conf, **kw)


def links():
    out = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=10).stdout
    out += subprocess.run(["pw-link", "-i"], capture_output=True, text=True, timeout=10).stdout
    return set(out.split("\n"))


def has_ports(inst, names=("in_1", "in_2", "out_1", "out_2")):
    ports = links()
    return all("effect_%d:%s" % (inst, n) in ports for n in names)


def node_id(name):
    import json
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10).stdout)
    for o in dump:
        if o.get("type") == "PipeWire:Interface:Node" and o["info"]["props"].get("node.name") == name:
            return o["id"]
    return None


def crash(d, inst):
    """the plugin aborts on this write: the worker is gone either after the reply (a callback: 'resp 0') or with
    the command on the wire ('resp -503'), and both are the daemon's to deal with"""
    r = d.send("param_set %d %d 1" % (inst, CRASH))
    check(r in ("resp 0", "resp -503"), "param_set that crashes the plugin -> %r" % r)


def ckpt(d, inst):
    return os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "ckpt", "effect_%d.clapstate" % inst)


@test
def clap_own_crash_replays_bit_identically_and_the_neighbour_never_notices():
    d = daemon(conf={"checkpoint_ms": 300})
    try:
        d.expect("add %s 0" % STRESS, "resp 0")
        d.expect("add %s 1" % STRESS, "resp 1")
        check(has_ports(0) and has_ports(1), "both inserts are in the graph")
        d.expect("param_set 0 %d 0.75" % LEVEL, "resp 0")
        d.expect("param_set 1 %d 0.25" % LEVEL, "resp 0")
        wait_for(lambda: os.path.exists(ckpt(d, 0)), "a checkpoint of instance 0")
        s1, s2 = tempfile.mkdtemp(dir=d.tmp), tempfile.mkdtemp(dir=d.tmp)
        d.expect("state_save " + s1, "resp 0")
        ka, wa = d.holder(0)
        kb, wb = d.holder(1)
        node_b = node_id("effect_1")
        check(node_b is not None, "effect_1 has a node in the graph")
        mark = d.mark()
        os.kill(wa["pid"], signal.SIGKILL)
        wait_for(lambda: not has_ports(0), "effect_0's ports to leave the graph (the kill landed)")
        d.wait_event("instance_restored 0 ", since=mark)
        wait_for(lambda: has_ports(0), "effect_0's ports to come back")
        d.expect("param_get 0 %d" % LEVEL, "resp 0 0.7500")
        d.expect("state_save " + s2, "resp 0")
        check(filecmp.cmp(os.path.join(s1, "effect_0.clapstate"), os.path.join(s2, "effect_0.clapstate"), shallow=False),
              "the state file after the respawn is byte-identical to the one before")
        check(d.holder(1)[1]["pid"] == wb["pid"] and node_id("effect_1") == node_b, "effect_1's process and graph node are the same")
    finally:
        d.close()


@test
def clap_one_shot_crash_in_callback_comes_back_with_its_params():
    marker = tempfile.mktemp(prefix="plugin-hostd-once.")
    d = daemon(env={"STRESS_CRASH_ONCE": marker})
    try:
        d.expect("add %s 0" % STRESS, "resp 0")
        d.expect("param_set 0 %d 0.5" % LEVEL, "resp 0")
        mark = d.mark()
        crash(d, 0)
        died = d.wait_event("worker_died ", since=mark)
        check("signal:6" in died, "the plugin's abort is signal 6: " + died)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 %d" % LEVEL, "resp 0 0.5000")
        check(has_ports(0), "the insert is back in the graph")
    finally:
        d.close()
        if os.path.exists(marker):
            os.unlink(marker)


@test
def clap_pool_crash_names_the_culprit_and_the_others_come_back():
    d = daemon()
    try:
        for i in (10, 11, 12, 13):
            d.expect("add %s %d pool:p" % (STRESS, i), "resp %d" % i)
            d.expect("param_set %d %d 0.%d" % (i, LEVEL, i - 9), "resp 0")
        w = d.workers()
        check(len(w) == 1 and list(w.values())[0]["inst"] == [10, 11, 12, 13], "the pool held all four before: %s" % w)
        check(all(has_ports(i) for i in (10, 11, 12, 13)), "all four are in the graph")
        mark = d.mark()
        crash(d, 12)
        d.wait_event("instance_quarantined 12 ", since=mark)
        for i in (10, 11, 13):
            k, w = d.wait_up(i)
            check(i in w["inst"], "instance %d is back: %s" % (i, w))
            d.expect("param_get %d %d" % (i, LEVEL), "resp 0 0.%d000" % (i - 9))
            wait_for(lambda: has_ports(i), "instance %d's ports" % i)
        info = d.send("instance_info 12").split()
        check(info[6] == "1" and d.holder(12)[1]["place"] == "own", "the culprit is quarantined and own: %s" % info)
    finally:
        d.close()


@test
def audio_of_the_other_strip_never_changes_when_one_worker_is_killed():
    d = daemon(conf={"backoff_base_ms": 600})
    probe = None
    try:
        d.expect("add %s 0" % STRESS, "resp 0")
        d.expect("add %s 1" % STRESS, "resp 1")
        probe = subprocess.Popen([LEVELS, "16000"], stdout=subprocess.PIPE, stderr=open(os.path.join(d.tmp, "levels.err"), "w"), text=True)
        assert probe.stdout.readline().strip() == "ready"
        d.until_ok("connect lv_src:out_1 effect_0:in_1")
        d.until_ok("connect effect_0:out_1 lv_sink:in_1")
        d.until_ok("connect lv_src:out_2 effect_1:in_1")
        d.until_ok("connect effect_1:out_1 lv_sink:in_2")
        rows = []

        def read():
            for line in probe.stdout:
                t, a, b = line.split()
                rows.append((int(t), float(a), float(b), time.monotonic()))
        threading.Thread(target=read, daemon=True).start()
        wait_for(lambda: len(rows) > 6 and rows[-1][1] > 0.25 and rows[-1][2] > 0.25, "both chains to carry the tone (0.3)")
        base = (rows[-1][1], rows[-1][2])
        _, wa = d.holder(0)
        mark = d.mark()
        n0 = len(rows)
        os.kill(wa["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        wait_for(lambda: len(rows) > n0 + 40 and rows[-1][1] > 0.25, "chain A to carry the tone again (probe exit %s, %d rows, peaks a, b from the kill: %s)"
                 % (probe.poll(), len(rows), [r[:3] for r in rows[n0 - 2:n0 + 70:4]]), 20)
        window = rows[n0:]
        check(min(r[1] for r in window) < 0.01, "chain A fell silent while its worker was gone (min %.4f)" % min(r[1] for r in window))
        check(min(r[2] for r in window) >= 0.25, "chain B's lowest peak across the kill was %.4f (baseline %.4f)"
              % (min(r[2] for r in window), base[1]))
        check(window[-1][1] >= 0.25, "chain A is back at %.4f" % window[-1][1])
    finally:
        if probe:
            probe.kill()
        d.close()


if MOD_HOST and LV2_DIR:
    @test
    def lv2_own_worker_sees_one_bundle_and_replays_after_a_kill():
        d = daemon()
        try:
            d.expect("add lv2:%s 0" % DELAY_URI, "resp 0")
            d.expect("add %s 1 pool:l" % DELAY_URI, "resp 1")
            names = ("lv2_audio_in_1", "lv2_audio_in_2", "lv2_audio_out_1", "lv2_audio_out_2")
            check(has_ports(0, names) and has_ports(1, names), "both LV2 inserts are in the graph")
            k, w = d.holder(0)
            env = open("/proc/%d/environ" % w["pid"], "rb").read().split(b"\0")
            world = [e for e in env if e.startswith(b"LV2_PATH=")][0][9:].decode()
            entries = os.listdir(world)
            check(entries == ["omx-delay.lv2"] and os.path.islink(os.path.join(world, entries[0])),
                  "an own LV2 worker's world is one linked bundle: %s in %s" % (entries, world))
            kp, wp = d.holder(1)
            penv = [e for e in open("/proc/%d/environ" % wp["pid"], "rb").read().split(b"\0") if e.startswith(b"LV2_PATH=")]
            check(not penv or penv[0][9:].decode() == LV2_DIR, "a pool keeps the whole set")
            d.expect("param_set 0 timeMs 123.5", "resp 0")
            before = d.send("param_get 0 timeMs")
            check(before.startswith("resp 0 "), "timeMs answers: " + before)
            mark = d.mark()
            os.kill(w["pid"], signal.SIGKILL)
            wait_for(lambda: not has_ports(0, names), "the LV2 insert to leave the graph")
            d.wait_event("instance_restored 0 ", since=mark)
            wait_for(lambda: has_ports(0, names), "the LV2 insert to come back")
            d.expect("param_get 0 timeMs", before)
        finally:
            d.close()


sys.exit(run_tests(TESTS))

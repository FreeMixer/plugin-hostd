# The real workers behind the daemon, over jack, in the namespace tests/jack_e2e.sh built.
import filecmp, os, signal, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Daemon, Fail, alive, check, resp, run_tests, wait_for

EXE = os.environ["PLUGIN_HOSTD"]
CLAP_HOST = os.environ["OMX_CLAP_HOST"]
STRESS = "clap:%s#org.plugin-hostd.test.stress" % os.environ["STRESS_CLAP"]
LEVELS = os.environ["JACK_LEVELS"]
MOD_HOST = os.environ.get("MOD_HOST")
LV2_DIR = os.environ.get("LV2_DIR")
LV2_URI = os.environ.get("LV2_URI")          # a stereo effect in a bundle of LV2_DIR, its ports lv2_audio_in_1 ..
LV2_BUNDLE = os.environ.get("LV2_BUNDLE")    # the bundle's directory name
LV2_PARAM = os.environ.get("LV2_PARAM")      # a control symbol of it that takes 0.25
LV2 = MOD_HOST and LV2_DIR and LV2_URI and LV2_BUNDLE and LV2_PARAM
# omx-clap-host's own meter fixtures: a compressor that reports gain reduction and input levels, and a constant source
COMPRESSOR = os.environ.get("FAKE_COMPRESSOR_CLAP")
METER_SOURCE = os.environ.get("JACK_METER_SOURCE")
HOST_SCENARIOS = os.environ.get("HOST_SCENARIOS")
FAKE_CLAP = os.environ.get("FAKE_CLAP")      # omx-clap-host's tests/fake.clap: its passthrough reads clap.track-info
SCENARIOS = os.environ.get("SCENARIOS")
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
    the command on the wire (VERB_DROPPED), and both are the daemon's to deal with"""
    r = d.send("param_set %d %d 1" % (inst, CRASH))
    check(r in ("resp 0", resp("VERB_DROPPED")), "param_set that crashes the plugin -> %r" % r)


def ckpt(d, inst):
    return os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "ckpt", "effect_%d.clapstate" % inst)


def run_scenarios(uri, bad_uri, param, port_a, port_b):
    """mod-host's own scenario corpus, unmodified, against the daemon with no placement and no verb of ours,
    started the way a controller starts mod-host (-n -p <port>: no feedback port, and the runner opens none)"""
    d = daemon(feedback=False)
    try:
        d.sock.close()   # one controller at a time, as in mod-host: the runner is the controller here
        state = tempfile.mkdtemp(dir=d.tmp)
        r = subprocess.run([HOST_SCENARIOS, str(d.cmd_port), SCENARIOS, "URI=" + uri, "BAD_URI=" + bad_uri, "PARAM=" + param,
                            "DIR=" + state, "PORT_A=" + port_a, "PORT_B=" + port_b, "REMOVE_TWICE=resp 0"],
                           capture_output=True, text=True, timeout=120)
        check(r.returncode == 0, "the scenario corpus against the daemon: rc %d\n%s%s" % (r.returncode, r.stdout, r.stderr))
        check("0 failed" in r.stdout, r.stdout)
    finally:
        d.close()


if HOST_SCENARIOS and SCENARIOS and os.path.exists(HOST_SCENARIOS) and os.path.exists(SCENARIOS):
    @test
    def mod_host_scenarios_pass_unchanged_with_a_clap_worker():
        run_scenarios(STRESS, "clap:/nonexistent.clap#no.such.plugin", str(LEVEL), "effect_3:out_1", "effect_3:in_1")

    if LV2:
        @test
        def mod_host_scenarios_pass_unchanged_with_an_lv2_worker():
            run_scenarios(LV2_URI, "urn:no:such:plugin", LV2_PARAM, "effect_3:lv2_audio_out_1", "effect_3:lv2_audio_in_1")


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


def meter_source(d, *ports):
    """0.5 left and 0.25 right into the ports, -6.0206 and -12.0412 dBFS; it connects them itself"""
    src = subprocess.Popen([METER_SOURCE] + list(ports), stdout=subprocess.PIPE,
                           stderr=open(os.path.join(d.tmp, "source.err"), "a"), text=True)
    check(src.stdout.readline().strip() == "playing", "the meter source plays into %s" % (ports,))
    return src


def output_values(d, inst, sym, since=0):
    prefix = "output_set %d %s " % (inst, sym)
    with d.lock:
        return [e[len(prefix):] for e in d.events[since:] if e.startswith(prefix)]


def reads(d, inst, sym, want, tol, since=0, timeout=5):
    def near():
        v = output_values(d, inst, sym, since)
        return v and v[-1] != "-inf" and abs(float(v[-1]) - want) <= tol
    wait_for(near, "output_set %d %s to read %s (have %s)" % (inst, sym, want, output_values(d, inst, sym, since)[-5:]), timeout)


if COMPRESSOR and METER_SOURCE:
    @test
    def clap_meters_reach_the_controller_through_the_daemon_and_survive_a_kill():
        """omx-clap-host's meters e2e, with the daemon between: monitor_output is answered by the worker, output_set
        comes back on the daemon's feedback port, and after the worker is killed the replayed subscription reports
        the same meters again, once each"""
        d = daemon()
        src = None
        uri = "clap:%s#org.omx-clap-host.test.compressor" % COMPRESSOR
        try:
            d.expect("add %s 0" % uri, "resp 0")
            d.expect("add %s#org.omx-clap-host.test.compressor-std 1" % uri.split("#")[0], "resp 1")
            src = meter_source(d, "effect_0:in_1", "effect_0:in_2", "effect_1:in_1", "effect_1:in_2")
            d.expect("monitor_output 0 gain_reduction", "resp 1")
            d.expect("monitor_output 0 input_level_0", "resp 1")
            d.expect("monitor_output 0 input_level_1", "resp 1")
            d.expect("monitor_output 0 nothing", "resp 0")
            d.expect("monitor_output 1 gain_adjustment_metering", "resp 1")
            reads(d, 0, "gain_reduction", -6, 0.0001)
            reads(d, 0, "input_level_0", -6.0206, 0.0001)
            reads(d, 0, "input_level_1", -12.0412, 0.0001)
            reads(d, 1, "gain_adjustment_metering", -6, 0.0001)
            check(not output_values(d, 0, "nothing"), "an output the plugin does not have sends nothing")
            # a value that does not move is not sent again, through the daemon as from the host
            n = len(output_values(d, 0, "gain_reduction"))
            time.sleep(1)
            check(len(output_values(d, 0, "gain_reduction")) == n, "no output_set while the value holds")

            _, w = d.holder(0)
            _, w1 = d.holder(1)
            mark = d.mark()
            os.kill(w["pid"], signal.SIGKILL)
            d.wait_event("instance_restored 0 ", since=mark)
            wait_for(lambda: has_ports(0), "effect_0's ports to come back")
            src.kill()
            src.wait()
            src = meter_source(d, "effect_0:in_1", "effect_0:in_2", "effect_1:in_1", "effect_1:in_2")
            reads(d, 0, "gain_reduction", -6, 0.0001, since=mark)
            reads(d, 0, "input_level_0", -6.0206, 0.0001, since=mark)
            reads(d, 0, "input_level_1", -12.0412, 0.0001, since=mark)
            check(d.holder(1)[1]["pid"] == w1["pid"], "instance 1's worker was not touched")
            # the replayed subscription is one per output: a doubled one would send each value twice in a row
            for sym in ("gain_reduction", "input_level_0", "input_level_1"):
                v = output_values(d, 0, sym, mark)
                check(all(a != b for a, b in zip(v, v[1:])), "output_set 0 %s after the respawn: no value twice: %s" % (sym, v))
        finally:
            if src:
                src.kill()
            d.close()


if LV2:
    @test
    def lv2_own_worker_sees_one_bundle_and_replays_after_a_kill():
        d = daemon()
        try:
            d.expect("add lv2:%s 0" % LV2_URI, "resp 0")
            d.expect("add %s 1 pool:l" % LV2_URI, "resp 1")
            names = ("lv2_audio_in_1", "lv2_audio_in_2", "lv2_audio_out_1", "lv2_audio_out_2")
            check(has_ports(0, names) and has_ports(1, names), "both LV2 inserts are in the graph")
            k, w = d.holder(0)
            env = open("/proc/%d/environ" % w["pid"], "rb").read().split(b"\0")
            world = [e for e in env if e.startswith(b"LV2_PATH=")][0][9:].decode()
            entries = os.listdir(world)
            check(entries == [LV2_BUNDLE] and os.path.islink(os.path.join(world, entries[0])),
                  "an own LV2 worker's world is one linked bundle: %s in %s" % (entries, world))
            kp, wp = d.holder(1)
            penv = [e for e in open("/proc/%d/environ" % wp["pid"], "rb").read().split(b"\0") if e.startswith(b"LV2_PATH=")]
            check(not penv or penv[0][9:].decode() == LV2_DIR, "a pool keeps the whole set")
            d.expect("param_set 0 %s 0.25" % LV2_PARAM, "resp 0")
            before = d.send("param_get 0 " + LV2_PARAM)
            check(before == "resp 0 0.2500", "%s answers: %s" % (LV2_PARAM, before))
            mark = d.mark()
            os.kill(w["pid"], signal.SIGKILL)
            wait_for(lambda: not has_ports(0, names), "the LV2 insert to leave the graph")
            d.wait_event("instance_restored 0 ", since=mark)
            wait_for(lambda: has_ports(0, names), "the LV2 insert to come back")
            d.expect("param_get 0 " + LV2_PARAM, before)
        finally:
            d.close()


if FAKE_CLAP:
    @test
    def clap_track_info_and_remote_pages_reach_the_plugin_through_the_daemon():
        """track_info reaches the plugin through the worker, is replayed to it after a kill, and the plugin's call of
        the host's remote_controls.changed comes back on the daemon's feedback port"""
        log = os.path.join(tempfile.mkdtemp(), "fake.log")
        d = daemon(env={"FAKE_LOG": log})
        uri = "clap:%s#org.omx-clap-host.test.passthrough" % FAKE_CLAP

        def told():
            if not os.path.exists(log):
                return []
            with open(log, encoding="utf-8") as f:
                return [l.rstrip("\n").split(" track_info ", 1)[1] for l in f if " track_info " in l]
        try:
            d.expect("add %s 0" % uri, "resp 0")
            mark = d.mark()
            d.expect('track_info 0 "Kick In" #FF8000 bus', "resp 0")
            check(told() == ["1 13 255,255,128,0 Kick In"], "the plugin read the strip once: %s" % told())
            check(d.wait_event("remote_pages_changed ", since=mark) == "remote_pages_changed 0",
                  "the plugin's changed comes back through the daemon: %s" % d.events[mark:])
            d.expect("remote_pages 0", "resp 2")
            d.expect("remote_page_get 0 1", 'resp 0 8 "" "Two" - - - - - - - 0')
            d.expect("param_info 0 0", resp("NO_PARAM_CONTRACT"))
            _, w = d.holder(0)
            mark = d.mark()
            os.kill(w["pid"], signal.SIGKILL)
            d.wait_event("instance_restored 0 ", since=mark)
            check(told() == ["1 13 255,255,128,0 Kick In"] * 2, "the respawned plugin was told the strip once: %s" % told())
            d.expect("remote_pages 0", "resp 2")
        finally:
            d.close()


sys.exit(run_tests(TESTS))

# plugin-hostd against workers that are not plugin hosts (tests/fake-host). No jack, no plugin: the daemon's own
# behaviour, over the wire, the way a controller sees it. tests/jack_e2e.sh runs the real workers.
import hashlib, os, shutil, signal, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from harness import Daemon, Fail, alive, check, resp, run_tests, wait_for

EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", "./plugin-hostd"))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", "tests/fake-host"))
TESTS = []


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


def daemon(**kw):
    return Daemon(EXE, FAKE, **kw)


@test
def ready_line_and_empty_table():
    d = daemon()
    try:
        check(d.workers() == {}, "a daemon with no controller work holds no worker")
        d.expect("worker_list", "resp 0")
        d.expect("instance_info 0", "resp -3")
    finally:
        d.close()


@test
def placement_own_default_and_pool():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("add fake:b 1 own", "resp 1")
        d.expect("add fake:c 2 pool:p", "resp 2")
        d.expect("add fake:d 3 pool:p", "resp 3")
        d.expect("add fake:e 4 default", "resp 4")
        w = d.workers()
        by_inst = {tuple(v["inst"]): v for v in w.values()}
        check(set(by_inst) == {(0,), (1,), (2, 3), (4,)}, "workers hold %s" % sorted(by_inst))
        check(by_inst[(2, 3)]["place"] == "pool:p" and by_inst[(0,)]["place"] == "own", "places %s" % w)
        pids = {v["pid"] for v in w.values()}
        check(len(pids) == 4 and all(alive(p) for p in pids), "four processes, all alive")
        d.expect("add fake:x 9 pool:bad!name", resp("PLACEMENT_INVALID"))
        d.expect("add fake:x 9 pool:", resp("PLACEMENT_INVALID"))
        d.expect("add fake:a 0", "resp -2")
        d.expect("add fake:x 10000", "resp -1")
    finally:
        d.close()


@test
def lv2_prefix_is_stripped_and_missing_backend_refused():
    d = daemon(conf={"clap_host": "/nonexistent/omx-clap-host"})
    try:
        d.expect("add lv2:urn:test:one 0", "resp 0")
        d.expect("add clap:/x.clap#id 1", resp("NO_BACKEND"))
        check(list(d.workers().values())[0]["inst"] == [0], "only the LV2 instance has a worker")
    finally:
        d.close()


@test
def plain_verbs_pass_through_unchanged():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.7500", "resp 0")
        d.expect("param_get 0 gain", "resp 0 0.7500")
        d.expect("param_get 0 nope", "resp -103")
        d.expect("param_get 7 gain", "resp -3")
        d.expect("bypass 0 1", "resp 0")
        d.expect("param_get 0 :bypass", "resp 0 1")
        d.expect("remove 7", "resp 0")
        d.expect("remove 0", "resp 0")
        check(d.workers() == {}, "the last instance's removal retires its worker")
        d.expect("add fake:refuse 5", "resp -101")
        check(d.workers() == {}, "a worker's own refusal is passed through and nothing is left running")
    finally:
        d.close()


@test
def remove_all_and_quit():
    d = daemon()
    try:
        for i in range(3):
            d.expect("add fake:a %d" % i, "resp %d" % i)
        pids = [w["pid"] for w in d.workers().values()]
        d.expect("remove -1", "resp 0")
        check(d.workers() == {}, "remove -1 leaves no worker")
        wait_for(lambda: not any(alive(p) for p in pids), "the workers to exit")
        d.expect("add fake:a 0", "resp 0")
        pid = list(d.workers().values())[0]["pid"]
        d.expect("quit", "resp 0")
        wait_for(lambda: d.proc.poll() is not None, "the daemon to exit")
        wait_for(lambda: not alive(pid), "the worker to exit with it")
    finally:
        d.close()


@test
def sigkill_of_the_daemon_takes_the_workers_with_it():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        pid = list(d.workers().values())[0]["pid"]
        d.proc.kill()
        d.proc.wait()
        wait_for(lambda: not alive(pid), "the orphaned worker to exit (PR_SET_PDEATHSIG)", 5)
    finally:
        d.close()


@test
def own_crash_respawns_only_that_instance_and_replays_it():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("add fake:b 1", "resp 1")
        for i, g in ((0, "0.7500"), (1, "0.2500")):
            d.expect("param_set %d gain %s" % (i, g), "resp 0")
            d.expect("param_set %d tone 0.1000" % i, "resp 0")
        d.expect("bypass 0 1", "resp 0")
        ka, wa = d.holder(0)
        kb, wb = d.holder(1)
        mark = d.mark()
        os.kill(wa["pid"], signal.SIGKILL)
        ev = d.wait_event("worker_respawned %s " % ka, since=mark)
        d.wait_event("instance_restored 0 ", since=mark)
        died = d.wait_event("worker_died %s " % ka, since=mark)
        check("signal:9" in died and died.endswith(" 0"), "the death names the signal and the instance: " + died)
        ka2, wa2 = d.holder(0)
        kb2, wb2 = d.holder(1)
        check(ka2 == ka and wa2["pid"] != wa["pid"] and wa2["state"] == "up", "instance 0 has a new process")
        check(wb2["pid"] == wb["pid"], "instance 1's process is the same one")
        d.expect("param_get 0 gain", "resp 0 0.7500")
        d.expect("param_get 0 tone", "resp 0 0.1000")
        d.expect("param_get 0 :bypass", "resp 0 1")
        d.expect("param_get 1 gain", "resp 0 0.2500")
        info = d.send("instance_info 0").split()
        check(info[:2] == ["resp", "0"] and info[4] == "up" and info[5] == "1" and info[6] == "0", "instance_info: %s" % info)
        check(not any(e.startswith("instance_quarantined") for e in d.events), "an own crash quarantines nothing")
    finally:
        d.close()


@test
def connections_are_replayed_and_disconnect_forgets():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("connect effect_0:out_1 system:playback_1", "resp 0")
        d.expect("connect effect_0:out_2 system:playback_2", "resp 0")
        d.expect("disconnect effect_0:out_2 system:playback_2", "resp 0")
        d.expect("list_connections", "resp 0 effect_0:out_1>system:playback_1")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("list_connections", "resp 0 effect_0:out_1>system:playback_1")
    finally:
        d.close()


@test
def a_connect_the_new_worker_cannot_make_yet_is_asked_again():
    d = daemon(env={"FAKE_CONNECT_AFTER_MS": "400"})
    try:
        d.expect("add fake:a 0", "resp 0")
        time.sleep(0.5)
        d.expect("connect effect_0:out_1 system:playback_1", "resp 0")
        d.expect("list_connections", "resp 0 effect_0:out_1>system:playback_1")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        check(d.send("list_connections") == "resp 0", "the worker refused the connect while it was new")
        wait_for(lambda: d.send("list_connections") == "resp 0 effect_0:out_1>system:playback_1", "the connection to come back", 5)
    finally:
        d.close()


@test
def replay_is_text_identical_and_state_checkpoint_is_byte_identical():
    d = daemon(conf={"checkpoint_ms": 300})
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 old 9.0000", "resp 0")
        d.expect("preset_load 0 urn:preset:one", "resp 0")
        names = []
        for n in range(12):
            names.append("p%d" % n)
            d.expect("param_set 0 p%d %s" % (n, "%d.%04d" % (n, 1234 + n)), "resp 0")
        d.expect("patch_set 0 urn:ir:path /tmp/ir.wav", "resp 0")
        d.expect("bypass 0 1", "resp 0")
        wait_for(lambda: os.path.exists(os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "ckpt", "effect_0.fakestate")),
                 "a checkpoint of instance 0")
        d.expect("param_set 0 late 5.5000", "resp 0")
        before = {n: d.send("param_get 0 " + n) for n in names + ["preset", "patch:urn:ir:path", "late", ":bypass"]}
        check(all(v.startswith("resp 0 ") for v in before.values()), "every parameter answers before: %s" % before)
        check(d.send("param_get 0 old") == "resp -103", "the preset dropped a parameter set before it")
        s1 = tempfile.mkdtemp(dir=d.tmp)
        s2 = tempfile.mkdtemp(dir=d.tmp)
        d.expect("state_save " + s1, "resp 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        after = {n: d.send("param_get 0 " + n) for n in before}
        check(after == before, "replayed parameters differ: %s vs %s" % (before, after))
        check(d.send("param_get 0 old") == "resp -103", "the dropped parameter did not come back")
        d.expect("state_save " + s2, "resp 0")
        a = open(os.path.join(s1, "effect_0.fakestate"), "rb").read()
        b = open(os.path.join(s2, "effect_0.fakestate"), "rb").read()
        check(a == b and len(a) > 100, "state_save after the respawn is byte-identical (%d bytes)" % len(a))
    finally:
        d.close()


@test
def instance_without_state_replays_from_verbs_alone():
    d = daemon(conf={"checkpoint_ms": 300})
    try:
        d.expect("add fake:nostate 0", "resp 0")
        d.expect("param_set 0 gain 0.6000", "resp 0")
        time.sleep(0.8)
        check(not os.path.exists(os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "ckpt", "effect_0.fakestate")),
              "the fake worker never writes state for it")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.6000")
    finally:
        d.close()


def make_pool(d, ids, name="p"):
    for i in ids:
        d.expect("add fake:m%d %d pool:%s" % (i, i, name), "resp %d" % i)
        d.expect("param_set %d gain 0.%d000" % (i, i % 10), "resp 0")


@test
def pool_callback_crash_splits_the_pool_and_the_culprit_comes_back_own():
    d = daemon(conf={"suspect_window_ms": 0})
    try:
        make_pool(d, [10, 11, 12, 13])
        w = d.workers()
        check(len(w) == 1 and w[list(w)[0]]["inst"] == [10, 11, 12, 13] and w[list(w)[0]]["place"] == "pool:p",
              "before the kill the pool holds all four: %s" % w)
        pool_k = list(w)[0]
        mark = d.mark()
        d.expect("param_set 12 crash 1", "resp 0")
        died = d.wait_event("worker_died %s " % pool_k, since=mark)
        check("signal:6" in died, "abort is signal 6: " + died)
        q = d.wait_event("instance_quarantined 12 ", since=mark)
        for i in (10, 11, 13):
            k, w = d.wait_up(i)
            check(w["place"] == "own" and w["inst"] == [i], "instance %d is back alone: %s" % (i, w))
            d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))
        info = d.send("instance_info 12").split()
        check(info[6] == "1" and int(info[5]) >= 1, "instance_info names the culprit: %s" % info)
        check(not any(e.startswith("instance_quarantined") and " %d " % i in e for e in d.events for i in (10, 11, 13)),
              "no innocent was quarantined: %s" % d.events)
        check(all(d.holder(i)[1]["pid"] != 0 for i in (10, 11, 13)), "the others run")
        k12, w12 = d.holder(12)
        check(w12["place"] == "own", "the culprit is own: %s" % w12)
    finally:
        d.close()


@test
def pool_in_flight_command_names_the_culprit_and_the_pool_stays_a_pool():
    d = daemon(conf={"rpc_timeout_ms": 400})
    try:
        make_pool(d, [20, 21, 22, 23])
        mark = d.mark()
        r = d.send("param_set 21 hang 1")
        check(r == resp("VERB_DROPPED"), "the controller is told its command was dropped: " + r)
        d.wait_event("instance_verb_dropped 21 param_set 21 hang 1", since=mark)
        d.wait_event("instance_quarantined 21 ", since=mark)
        for i in (20, 22, 23):
            k, w = d.wait_up(i)
            check(w["place"] == "pool:p" and set(w["inst"]) == {20, 22, 23}, "survivors stay pooled: %s" % w)
            d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))
        k, w = d.holder(21)
        check(w["place"] == "own", "the culprit left the pool: %s" % w)
    finally:
        d.close()


@test
def quarantined_instance_is_placed_own_until_cleared():
    # the pool's respawn waits out a backoff longer than the steps below take, so an add into the pool before its
    # instance_restored meets it in backoff every time, not one run in ten
    d = daemon(conf={"backoff_base_ms": 300, "backoff_max_ms": 300})
    try:
        make_pool(d, [30, 31])
        mark = d.mark()
        d.expect("param_set 30 crash 1", "resp 0")
        d.wait_event("instance_quarantined 30 ", since=mark)
        d.expect("remove 30", "resp 0")
        d.expect("add fake:m30 30 pool:p", "resp 30")
        k, w = d.holder(30)
        check(w["place"] == "own", "a quarantined instance asked into a pool is placed own: %s" % w)
        d.expect("remove 30", "resp 0")
        d.expect("quarantine_clear 30", "resp 0")
        d.wait_event("instance_restored 31 ", since=mark)
        d.expect("add fake:m30 30 pool:p", "resp 30")
        wait_for(lambda: d.holder(30)[1]["place"].startswith("pool:p"), "instance 30 back in the pool")
        d.expect("quarantine_clear 999", "resp -3")
        d.expect("quarantine_clear all", "resp 0")
    finally:
        d.close()


@test
def crash_on_add_in_a_pool_quarantines_it_and_spares_the_others():
    d = daemon()
    try:
        make_pool(d, [40, 41])
        r = d.send("add fake:crash_on_add 42 pool:p")
        check(r == "resp -102", "a worker that died instantiating answers -102: " + r)
        d.wait_event("instance_quarantined 42 ")
        for i in (40, 41):
            k, w = d.wait_up(i)
            check(w["place"] == "pool:p", "survivors are back in the pool: %s" % w)
            d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))
        d.expect("instance_info 42", "resp -3")
    finally:
        d.close()


@test
def storm_bound_is_per_placement_and_reset_rearms_it():
    d = daemon(conf={"storm_deaths": 3})
    try:
        d.expect("add fake:ok 50", "resp 50")
        d.expect("param_set 50 gain 0.5000", "resp 0")
        for _ in range(3):
            d.expect("add fake:crash_on_add 51", "resp -102")
        d.expect("add fake:crash_on_add 51", resp("GAVE_UP"))
        d.expect("add fake:ok 52", "resp 52")
        d.expect("param_get 50 gain", "resp 0 0.5000")
        d.expect("supervisor_reset all", "resp 0")
        d.expect("add fake:crash_on_add 51", "resp -102")
        d.expect("supervisor_reset w99", resp("NO_SUCH_WORKER"))
    finally:
        d.close()


@test
def crashing_own_instance_is_given_up_alone():
    d = daemon(conf={"storm_deaths": 3, "suspect_window_ms": 0})
    try:
        d.expect("add fake:ok 60", "resp 60")
        d.expect("param_set 60 gain 0.5000", "resp 0")
        d.expect("add fake:bad 61", "resp 61")
        mark = d.mark()
        d.expect("param_set 61 crash 1", "resp 0")
        gave = d.wait_event("supervisor_gave_up ", since=mark)
        k, w = d.holder(61)
        check(w["state"] == "given-up", "the crasher's placement is given up: %s" % w)
        check(gave.startswith("supervisor_gave_up %s " % k), "the event names its worker: " + gave)
        d.expect("param_get 61 gain", resp("GAVE_UP"))
        d.expect("param_get 60 gain", "resp 0 0.5000")
        d.expect("add fake:ok 62", "resp 62")
        check(d.holder(60)[1]["state"] == "up", "the neighbour is untouched")
        d.expect("supervisor_reset all", "resp 0")
        d.expect("remove 61", "resp 0")
        d.expect("instance_info 61", "resp -3")
    finally:
        d.close()


@test
def a_crash_just_after_the_reply_drops_the_verb_it_answered_and_does_not_crash_again():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.4000", "resp 0")
        mark = d.mark()
        d.expect("param_set 0 crash 1", "resp 0")
        dropped = d.wait_event("instance_verb_dropped 0 suspect:", since=mark)
        check(dropped.endswith(" param_set 0 crash 1"), "the event names the verb: " + dropped)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.4000")
        d.expect("param_get 0 crash", "resp -103")
        time.sleep(0.5)
        deaths = [e for e in d.events[mark:] if e.startswith("worker_died")]
        check(len(deaths) == 1, "the plugin does not crash again on the replay: %s" % deaths)
        check(d.holder(0)[1]["state"] == "up", "and it stays up")
        info = d.send("instance_info 0").split()
        check(info[4] == "up" and info[5] == "1", "one crash counted, not given up: %s" % info)
        check(not any(e.startswith("supervisor_gave_up") for e in d.events), "the storm bound was not spent")
    finally:
        d.close()


@test
def a_dropped_suspect_gives_back_the_value_it_replaced():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.4000", "resp 0")
        mark = d.mark()
        d.expect("param_set 0 gain 0.9000", "resp 0")
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_verb_dropped 0 suspect:", since=mark)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.9000")
        d.expect("param_set 0 crash 0", "resp 0")
        mark = d.mark()
        d.expect("param_set 0 gain 0.2000", "resp 0")
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_verb_dropped 0 suspect:", since=mark)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.2000")
        d.expect("param_get 0 crash", "resp 0 0")
    finally:
        d.close()


@test
def a_crash_well_after_the_reply_replays_the_verb_as_before():
    marker = tempfile.mktemp(prefix="plugin-hostd-once.")
    d = daemon(env={"FAKE_CRASH_ONCE": marker, "FAKE_CRASH_AFTER_MS": "900"})
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.4000", "resp 0")
        mark = d.mark()
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.4000")
        d.expect("param_get 0 crash", "resp 0 1")
        check(not any(e.startswith("instance_verb_dropped") for e in d.events), "nothing was dropped: %s" % d.events)
        check(d.holder(0)[1]["state"] == "up", "and it stays up")
        info = d.send("instance_info 0").split()
        check(info[5] == "1", "one crash counted: %s" % info)
    finally:
        d.close()
        if os.path.exists(marker):
            os.unlink(marker)


@test
def a_kill_from_outside_inside_the_window_drops_nothing():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.4000", "resp 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.4000")
        check(not any(e.startswith("instance_verb_dropped") for e in d.events), "nothing was dropped: %s" % d.events)
    finally:
        d.close()


@test
def pool_crash_just_after_the_reply_names_the_sender_and_the_pool_stays_a_pool():
    d = daemon()
    try:
        make_pool(d, [80, 81, 82])
        mark = d.mark()
        d.expect("param_set 81 crash 1", "resp 0")
        d.wait_event("instance_verb_dropped 81 suspect:", since=mark)
        d.wait_event("instance_quarantined 81 ", since=mark)
        for i in (80, 82):
            k, w = d.wait_up(i)
            check(w["place"] == "pool:p" and set(w["inst"]) == {80, 82}, "survivors stay pooled: %s" % w)
            d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))
        d.wait_up(81)
        d.expect("param_get 81 crash", "resp -103")
        time.sleep(0.5)
        deaths = [e for e in d.events[mark:] if e.startswith("worker_died")]
        check(len(deaths) == 1, "one death, no second crash: %s" % deaths)
    finally:
        d.close()


@test
def the_verb_the_worker_died_on_is_dropped_and_not_replayed():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("param_set 0 gain 0.4000", "resp 0")
        mark = d.mark()
        r = d.send("param_set 0 crashnow 1")
        check(r == resp("VERB_DROPPED"), "the controller is told its command was dropped: " + r)
        d.wait_event("instance_verb_dropped 0 param_set 0 crashnow 1", since=mark)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("param_get 0 gain", "resp 0 0.4000")
        d.expect("param_get 0 crashnow", "resp -103")
        time.sleep(0.5)
        deaths = [e for e in d.events[mark:] if e.startswith("worker_died")]
        check(len(deaths) == 1, "the plugin does not crash again on the replay: %s" % deaths)
        check(d.holder(0)[1]["state"] == "up", "and it stays up")
        info = d.send("instance_info 0").split()
        check(info[4] == "up" and info[5] == "1", "one crash counted, not given up: %s" % info)
        check(not any(e.startswith("supervisor_gave_up") for e in d.events), "the storm bound was not spent")
    finally:
        d.close()


@test
def pool_drops_the_verb_of_the_instance_it_names_and_replays_the_rest():
    d = daemon()
    try:
        make_pool(d, [70, 71, 72])
        mark = d.mark()
        r = d.send("param_set 71 crashnow 1")
        check(r == resp("VERB_DROPPED"), "dropped: " + r)
        d.wait_event("instance_verb_dropped 71 param_set 71 crashnow 1", since=mark)
        d.wait_event("instance_quarantined 71 ", since=mark)
        for i in (70, 71, 72):
            d.wait_up(i)
            d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))
        d.expect("param_get 71 crashnow", "resp -103")
        time.sleep(0.5)
        deaths = [e for e in d.events[mark:] if e.startswith("worker_died")]
        check(len(deaths) == 1, "one death, no second crash: %s" % deaths)
        check(sum(1 for e in d.events[mark:] if e.startswith("instance_verb_dropped")) == 1, "one verb dropped")
    finally:
        d.close()


@test
def policy_and_pool_config():
    d = daemon()
    try:
        d.expect("policy_set lv2 pool:x", "resp 0")
        d.expect("pool_config x 2", "resp 0")
        for i in range(3):
            d.expect("add fake:a %d default" % i, "resp %d" % i)
        places = sorted(w["place"] for w in d.workers().values())
        check(places == ["pool:x", "pool:x#2"], "a full pool opens a sibling: %s" % places)
        d.expect("add fake:o 5 own", "resp 5")
        d.expect("policy_set * own", "resp 0")
        d.expect("add fake:d 6", "resp 6")
        check(d.holder(6)[1]["place"] == "own", "the default follows the policy")
        d.expect("policy_set lv2 pool:!", resp("PLACEMENT_INVALID"))
        d.expect("policy_set midi own", "resp -902")
        d.expect("pool_config y 0", "resp -902")
    finally:
        d.close()


@test
def worker_env_reaches_new_and_running_workers():
    cpus = sorted(os.sched_getaffinity(0))
    d = daemon()
    try:
        d.expect("worker_env lv2 %d 5" % cpus[0], "resp 0")
        d.expect("add fake:a 0", "resp 0")
        pid = d.holder(0)[1]["pid"]

        def stat():
            f = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
            allowed = [l for l in open("/proc/%d/status" % pid) if l.startswith("Cpus_allowed_list")][0].split()[1]
            return int(f[16]), allowed
        check(stat() == (5, str(cpus[0])), "a new worker has nice 5 and cpu %d: %s" % (cpus[0], stat()))
        d.expect("worker_env lv2 - 7", "resp 0")
        check(stat()[0] == 7, "a running worker follows: %s" % (stat(),))
        d.expect("worker_env lv2 abc -", "resp -902")
        d.expect("worker_env lv2 - 99", "resp -902")
        d.expect("worker_env lv2 - - 50", "resp -902")   # no fifth word: a priority is not offered
        d.expect("worker_env midi - -", "resp -902")
    finally:
        d.close()


@test
def feedback_off_is_the_same_daemon():
    d = daemon(feedback=False)
    try:
        d.expect("add fake:a 0", "resp 0")
        _, w = d.holder(0)
        os.kill(w["pid"], signal.SIGKILL)
        wait_for(lambda: d.holder(0)[1]["pid"] not in (0, w["pid"]) and d.holder(0)[1]["state"] == "up", "the respawn")
    finally:
        d.close()


# ---------------------------------------------------------------- pins (one-contract §10, supervisor §5.8)

MANIFEST = """@prefix lv2: <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<%s>
    a lv2:Plugin ;
    lv2:binary <pinned.so> ;
    rdfs:seeAlso <pinned.ttl> .
"""
LV2_URI = "urn:test:pinned"


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def fake_layout(default=None):
    """the layout pin of the fake's one parameter, as the fake computes it through pin.h"""
    env = dict(os.environ)
    if default is not None:
        env["FAKE_LAYOUT_DEFAULT"] = default
    return subprocess.check_output([FAKE, "-L"], env=env, text=True).strip()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


class Plugins:
    """a CLAP file and an LV2 bundle on disk, and the log of every command a fake worker received"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="plugin-hostd-pins.")
        self.clap = os.path.join(self.dir, "clap", "omx-fault.clap")
        os.makedirs(os.path.dirname(self.clap))
        write(self.clap, b"clean pad build")
        self.clap_uri = "clap:%s#org.openmixer.fault" % self.clap
        self.lv2_dir = os.path.join(self.dir, "lv2")
        self.bundle = os.path.join(self.lv2_dir, "pinned.lv2")
        os.makedirs(self.bundle)
        write(os.path.join(self.bundle, "manifest.ttl"), (MANIFEST % LV2_URI).encode())
        write(os.path.join(self.bundle, "pinned.so"), b"lv2 binary")
        write(os.path.join(self.bundle, "pinned.ttl"), b"lv2:port [ lv2:index 0 ; lv2:symbol \"gain\" ] .")
        self.log = os.path.join(self.dir, "commands.log")

    def clap_pin(self, layout=None):
        return "pin_set %s omx-fault.clap=%s %s" % (self.clap_uri, sha(self.clap), layout or fake_layout())

    def lv2_pin(self, files=("manifest.ttl", "pinned.so", "pinned.ttl")):
        return "pin_set %s %s %s" % (LV2_URI, ",".join("%s=%s" % (f, sha(os.path.join(self.bundle, f))) for f in files),
                                     fake_layout())

    def daemon(self, conf=None, env=None):
        c = {"require_pins": 1, "lv2_path": self.lv2_dir}
        c.update(conf or {})
        e = {"FAKE_LOG": self.log}
        e.update(env or {})
        return daemon(conf=c, env=e)

    def received(self):
        """(pid, command) of every command a worker received, in order"""
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [tuple(l.rstrip("\n").split(" ", 1)) for l in f if l.strip()]

    def verbs(self, word):
        return [c for _, c in self.received() if c.split()[0] == word]

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


@test
def an_unpinned_plugin_is_refused_by_default_and_no_worker_starts():
    p = Plugins()
    d = p.daemon(conf={"require_pins": None})
    try:
        d.expect("add %s 0" % p.clap_uri, resp("PIN_ABSENT"))
        d.expect("add %s 1" % LV2_URI, resp("PIN_ABSENT"))
        d.expect("add lv2:%s 1" % LV2_URI, resp("PIN_ABSENT"))
        check(d.workers() == {}, "no worker was spawned: %s" % d.workers())
        check(p.received() == [], "no worker received anything: %s" % p.received())
        d.expect(p.clap_pin().replace(fake_layout(), "omx-layout/0:" + "0" * 64), "resp 0")
        d.expect("add %s 0" % p.clap_uri, resp("PIN_ABSENT"))
        check(p.received() == [], "a pin in a scheme this version does not know is no pin")
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        d.expect("pin_clear %s" % p.clap_uri, "resp 0")
        d.expect("add %s 2" % p.clap_uri, resp("PIN_ABSENT"))
    finally:
        d.close()
    os.unlink(p.log)
    d = p.daemon(conf={"require_pins": 0})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check(p.verbs("pin_expect") == [], "with require_pins 0 no pin is asked for or sent")
    finally:
        d.close()
        p.close()


@test
def a_swapped_clap_binary_is_refused_before_any_worker_sees_add():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect(p.clap_pin(), "resp 0")
        good = open(p.clap, "rb").read()
        write(p.clap, b"another mode's build")
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        d.expect("add %s 0 pool:p" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        check(d.workers() == {}, "no worker was spawned: %s" % d.workers())
        check(p.received() == [], "no worker received anything: %s" % p.received())
        os.unlink(p.clap)
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        write(p.clap, good)
        other = os.path.join(os.path.dirname(p.clap), "other.clap")
        write(other, b"x")
        d.expect("pin_set %s other.clap=%s %s" % (p.clap_uri, sha(other), fake_layout()), "resp 0")
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        check(p.received() == [], "a pin that does not hold the .clap is refused before any worker")
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        got = p.received()
        check([c.split()[0] for _, c in got] == ["pin_expect", "add"] and got[0][0] == got[1][0],
              "the worker got the layout pin, then the add: %s" % got)
        check(got[0][1] == "pin_expect 0 %s" % fake_layout(), "the layout pin as set: %s" % got[0][1])
    finally:
        d.close()
        p.close()


@test
def a_changed_layout_is_refused_by_the_worker_and_reaches_the_client():
    p = Plugins()
    d = p.daemon(env={"FAKE_LAYOUT_DEFAULT": "0.25"})
    try:
        check(fake_layout("0.25") != fake_layout(), "the two defaults are two layouts")
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, resp("PIN_LAYOUT_MISMATCH"))
        check(p.verbs("add") == ["add %s 0" % p.clap_uri], "the binary passed and the worker checked the layout")
        check(d.workers() == {}, "the worker of the refused instance is gone: %s" % d.workers())
        d.expect("instance_info 0", "resp -3")
        d.expect(p.clap_pin(fake_layout("0.25")), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
    finally:
        d.close()
    d = p.daemon(env={"FAKE_NO_PIN_EXPECT": "1"})
    try:
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp -902")
        check(p.verbs("add").count("add %s 0" % p.clap_uri) == 2, "a worker that cannot check the layout gets no add")
    finally:
        d.close()
        p.close()


@test
def an_lv2_bundle_is_pinned_by_its_manifest_binary_and_seealso():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect(p.lv2_pin(("manifest.ttl", "pinned.ttl")), "resp 0")
        d.expect("add %s 0" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
        d.expect(p.lv2_pin(("manifest.ttl", "pinned.so")), "resp 0")
        d.expect("add %s 0" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
        d.expect(p.lv2_pin(("pinned.so", "pinned.ttl")), "resp 0")
        d.expect("add %s 0" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
        check(p.received() == [], "a pin short of a file the manifest names is refused before any worker")
        d.expect(p.lv2_pin(), "resp 0")
        for f, data in (("pinned.so", b"swapped"), ("pinned.ttl", b"lv2:port [ lv2:index 0 ; lv2:symbol \"mix\" ] ."),
                        ("manifest.ttl", (MANIFEST % LV2_URI + "<%s> lv2:extensionData <urn:x> .\n" % LV2_URI).encode())):
            path = os.path.join(p.bundle, f)
            good = open(path, "rb").read()
            write(path, data)
            d.expect("add lv2:%s 0" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
            write(path, good)
        check(p.received() == [], "a changed file of the bundle is refused before any worker: %s" % p.received())
        d.expect("add lv2:%s 0" % LV2_URI, "resp 0")
        check(p.verbs("add") == ["add %s 0" % LV2_URI] and p.verbs("pin_expect") == [],
              "the LV2 worker got its add and no pin verb: %s" % p.received())
        d.expect("pin_set %s ../pinned.so=%s %s" % (LV2_URI, "0" * 64, fake_layout()), "resp -902")
        d.expect("pin_set %s /abs=%s %s" % (LV2_URI, "0" * 64, fake_layout()), "resp -902")
        d.expect("pin_set %s pinned.so=%s %s" % (LV2_URI, "0" * 63, fake_layout()), "resp -902")
        d.expect("pin_set %s pinned.so=%s %s" % (LV2_URI, "A" * 64, fake_layout()), "resp -902")
        d.expect("pin_set %s pinned.so=%s,pinned.so=%s %s" % (LV2_URI, "0" * 64, "0" * 64, fake_layout()), "resp -902")
        d.expect("pin_set %s pinned.so=%s %s" % (LV2_URI, "0" * 64, "nolayout"), "resp -902")
        d.expect("pin_set %s pinned.so=%s" % (LV2_URI, "0" * 64), "resp -902")
        d.expect("pin_clear", "resp -902")
        d.expect("pin_clear all", "resp 0")
        d.expect("add %s 1" % LV2_URI, resp("PIN_ABSENT"))
    finally:
        d.close()
        p.close()


@test
def a_binary_swapped_while_its_worker_was_down_is_not_replayed():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        d.expect("param_set 0 gain 0.7", "resp 0")
        _, w = d.holder(0)
        good = open(p.clap, "rb").read()
        write(p.clap, b"another mode's build")
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("worker_respawned", since=mark)
        new = d.holder(0)[1]["pid"]
        check(new != w["pid"], "a new worker")
        check([c for pid, c in p.received() if int(pid) == new] == [],
              "the new worker got neither the add nor the verbs of the refused instance: %s" % p.received())
        check(not [e for e in d.events[mark:] if e.startswith("instance_restored 0 ")], "instance 0 is not restored")
        log = d.log()
        check("resp %d" % harness.CODE["REPLAY"] in log and "resp %d" % harness.CODE["PIN_BINARY_MISMATCH"] in log,
              "the refusal is written with PHD_ERR_REPLAY and the pin's code: %s" % log[-400:])
        write(p.clap, good)
        mark = d.mark()
        os.kill(new, signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        again = d.holder(0)[1]["pid"]
        check([c for pid, c in p.received() if int(pid) == again][:3] ==
              ["pin_expect 0 %s" % fake_layout(), "add %s 0" % p.clap_uri, "param_set 0 gain 0.7"],
              "with the true binary back the replay checks the layout, adds and replays: %s" % p.received())
    finally:
        d.close()
        p.close()


sys.exit(run_tests(TESTS))

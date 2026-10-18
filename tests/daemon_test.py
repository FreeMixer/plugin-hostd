# SPDX-License-Identifier: GPL-3.0-or-later
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
def a_command_whose_first_argument_is_a_uri_reaches_every_worker():
    log = tempfile.mktemp(prefix="plugin-hostd-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("add fake:b 1", "resp 1")
        pids = {w["pid"] for w in d.workers().values()}
        d.send("preset_show http://example.org/presets#0")
        with open(log) as f:
            got = {int(l.split(" ", 1)[0]) for l in f if l.split()[1:2] == ["preset_show"]}
        check(got == pids, "preset_show <uri> names no instance: every worker gets it, not the holder of %s: %s of %s"
              % ("instance 0", sorted(got), sorted(pids)))
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


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
def a_worker_that_lost_the_race_for_its_ports_is_started_again_on_fresh_ones():
    marker = os.path.join(tempfile.mkdtemp(), "bind-failed")
    d = daemon(env={"FAKE_BIND_FAIL_ONCE": marker})
    try:
        d.expect("add fake:a 0", "resp 0")
        check(os.path.exists(marker), "positive control: the first worker did exit before it listened")
        check(d.holder(0)[1]["state"] == "up", "the instance is on a worker that is up")
    finally:
        d.close()


@test
def a_worker_that_never_listens_is_refused_after_a_bounded_number_of_starts():
    d = daemon(env={"FAKE_BIND_FAIL_ALWAYS": "1"})
    try:
        t0 = time.time()
        d.expect("add fake:a 0", resp("WORKER_SPAWN"))
        check(time.time() - t0 < 3, "three quick starts, not three ready timeouts (%.1fs)" % (time.time() - t0))
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


# ---------------------------------------------------------------- the workers' own feedback (PHD_RELAY)

def outputs(d, inst, sym, since=0):
    """the values of every output_set line the controller got for one output, in the order it got them"""
    prefix = "output_set %d %s " % (inst, sym)
    with d.lock:
        return [float(e[len(prefix):]) for e in d.events[since:] if e.startswith(prefix)]


def counts_up(values):
    """the fake counts 0, 1, 2 ... per output and process: a lost, doubled or reordered line breaks the run"""
    return all(b == a + 1 for a, b in zip(values, values[1:]))


@test
def worker_feedback_reaches_the_controller_verbatim_and_in_order():
    d = daemon()
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("add fake:b 1 pool:p", "resp 1")
        d.expect("add fake:c 2 pool:p", "resp 2")
        d.expect("monitor_output 0 gain_reduction", "resp 1")
        d.expect("monitor_output 2 level", "resp 1")
        d.expect("monitor_output 1 none", "resp 0")
        wait_for(lambda: len(outputs(d, 0, "gain_reduction")) >= 20 and len(outputs(d, 2, "level")) >= 20,
                 "twenty output_set lines of each monitored output")
        for inst, sym in ((0, "gain_reduction"), (2, "level")):
            v = outputs(d, inst, sym)
            check(v[0] == 0 and counts_up(v), "output_set %d %s arrives whole and in order: %s" % (inst, sym, v[:30]))
        with d.lock:
            line = next(e for e in d.events if e.startswith("output_set 0 "))
        check(line == "output_set 0 gain_reduction 0.000000", "the line is the worker's, unchanged: %r" % line)
        check(not outputs(d, 1, "none"), "an output the worker does not have sends nothing")
    finally:
        d.close()


@test
def a_respawned_worker_reports_the_same_outputs_once_each():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("monitor_output 0 gain_reduction", "resp 1")
        d.expect("monitor_output 0 gain_reduction", "resp 1")
        d.expect("monitor_output 0 input_level_0", "resp 1")
        wait_for(lambda: len(outputs(d, 0, "gain_reduction")) >= 5, "output_set before the kill")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        pid = d.holder(0)[1]["pid"]
        # what the dead worker wrote comes before the news of its death, the new worker's lines after it
        with d.lock:
            died = next(n for n in range(mark, len(d.events)) if d.events[n].startswith("worker_died "))
        for sym in ("gain_reduction", "input_level_0"):
            wait_for(lambda: len(outputs(d, 0, sym, died)) >= 10, "output_set %s after the respawn" % sym)
            v = outputs(d, 0, sym, died)
            check(v[0] == 0 and counts_up(v), "%s starts again from its first value, once: %s" % (sym, v[:30]))
        with open(log) as f:
            sent = [l.split(" ", 1)[1].strip() for l in f if l.startswith("%d " % pid)]
        mon = [l for l in sent if l.startswith("monitor_output")]
        check(mon == ["monitor_output 0 gain_reduction", "monitor_output 0 input_level_0"],
              "the new worker is asked for each output once: %s" % mon)
        check(sent.index(mon[0]) > sent.index(next(l for l in sent if l.startswith("add "))), "after its add: %s" % sent)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_worker_is_read_when_no_controller_reads_the_feedback():
    """a worker whose feedback port no one reads stops on a full socket, as a real host does: the daemon reads it
    with no feedback port of its own, so the worker still answers"""
    d = daemon(feedback=False, env={"FAKE_FEEDBACK_BURST": "2000"})
    try:
        d.expect("add fake:a 0", "resp 0")
        d.expect("monitor_output 0 gain_reduction", "resp 1")
        time.sleep(2)
        for n in range(20):
            d.expect("param_set 0 gain 0.%d" % n, "resp 0")
        _, w = d.holder(0)
        check(alive(w["pid"]) and w["state"] == "up", "the worker is up: %s" % w)
    finally:
        d.close()


# ---------------------------------------------------------------- verbs a worker answers by instance (PHD_INSTANCE_VERBS)

VERBS = {v["name"]: v for v in harness.DECLARED["instance_verbs"]}
TRACK = 'track_info 0 "Kick \\"In\\" ñ" #FF8000 bus'
BAD_TRACK = ['track_info 0 "%s" - ' % ("x" * 256), "track_info 0 a #FF800", "track_info 0 a FF8000",
             "track_info 0 a #FF8000 aux", "track_info 0 a", 'track_info 0 "a\tb" -', "track_info x a -"]


def sent_to(log, pid=None):
    """the commands the fake workers were sent, or one worker's"""
    if not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as f:
        return [l.split(" ", 1)[1].rstrip("\n") for l in f if pid is None or l.startswith("%d " % pid)]


@test
def an_lv2_instance_is_answered_by_the_daemon_and_its_worker_never_sees_the_verbs():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        check(set(VERBS) == {"track_info", "remote_pages", "remote_page_get", "param_info", "note_input", "note_on", "note_off",
                             "all_notes_off", "preset_list", "preset_get"}, "declared: %s" % VERBS)
        d.expect("add fake:a 0", "resp 0")
        d.expect(TRACK, "resp 0")
        d.expect('track_info 0 "" -', "resp 0")
        d.expect("track_info 0 Kick #ff8000", "resp 0")
        for bad in BAD_TRACK:
            d.expect(bad, "resp -902")
        d.expect("track_info 9 a -", "resp -3")
        d.expect("remote_pages 0", "resp 0")
        d.expect("remote_page_get 0 0", "resp -902")
        d.expect("param_set 0 gain 0.5000", "resp 0")
        d.expect("param_info 0 gain", resp("NO_PARAM_CONTRACT"))
        d.expect("param_info 0 no_such_symbol", "resp -103")
        d.expect("param_info 0 :bypass", "resp -103")
        d.expect("remote_pages 9", "resp -3")
        d.expect("param_info 9 gain", "resp -3")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        d.expect("remote_pages 0", "resp 0")
        got = [c for c in sent_to(log) if c.split(" ", 1)[0] in VERBS]
        check(got == [], "mod-host learns none of the verbs, before or after a respawn: %s" % got)
        check(any(c.startswith("add ") for c in sent_to(log, d.holder(0)[1]["pid"])), "the respawned worker got its add")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_clap_instance_is_routed_to_its_worker_and_its_reply_passed_through():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#a 0", "resp 0")
        d.expect(TRACK, "resp 0")
        d.expect("remote_pages 0", "resp 2")
        d.expect("remote_page_get 0 0", 'resp 0 7 "Main" "Page \\"A\\"" 0 2 - - - - - -')
        d.expect("remote_page_get 0 2", "resp -902")
        d.expect("param_info 0 0", "resp 0 ms linear 1 2000 350 1 time_ms")
        # a parameter the worker holds no contract for is -511, passed through as the worker said it; a symbol that is no parameter is -103
        d.expect("param_info 0 1", resp("NO_PARAM_CONTRACT"))
        d.expect("param_info 0 2", "resp -103")
        for bad in BAD_TRACK:
            d.expect(bad, "resp -902")
        d.expect("remote_pages 9", "resp -3")
        got = [c for c in sent_to(log) if c.split(" ", 1)[0] in VERBS]
        check(got == [TRACK, "remote_pages 0", "remote_page_get 0 0", "remote_page_get 0 2", "param_info 0 0",
                      "param_info 0 1", "param_info 0 2"], "the worker gets each verb as sent, and no line the daemon refused: %s" % got)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def track_info_is_replayed_once_after_the_add_and_before_the_state():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(conf={"checkpoint_ms": 300}, env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#a 0", "resp 0")
        d.expect("track_info 0 Old #000000", "resp 0")
        d.expect(TRACK, "resp 0")
        d.expect("remote_pages 0", "resp 2")
        d.expect("param_set 0 gain 0.6000", "resp 0")
        wait_for(lambda: os.path.exists(os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "ckpt", "effect_0.fakestate")),
                 "a checkpoint of instance 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        first = [c.split(" ", 1)[0] for c in sent][:3]
        check(first == ["add", "track_info", "state_load"], "add, then track_info, then the state: %s" % sent)
        check([c for c in sent if c.startswith("track_info")] == [TRACK], "the latest track_info, once: %s" % sent)
        check(not [c for c in sent if c.split(" ", 1)[0] in ("remote_pages", "remote_page_get", "param_info")],
              "a query is never replayed: %s" % sent)
        d.expect("remove 0", "resp 0")
        d.expect("add clap:fake#a 0", "resp 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        check(not [c for c in sent if c.startswith("track_info")], "a removed instance's track_info is gone: %s" % sent)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def remote_pages_changed_from_a_worker_reaches_the_controller():
    d = daemon()
    try:
        d.expect("add clap:fake#a 3", "resp 3")
        mark = d.mark()
        d.expect("param_set 3 pages_changed 1", "resp 0")
        check(d.wait_event("remote_pages_changed ", since=mark) == "remote_pages_changed 3",
              "the worker's line, unchanged: %s" % d.events[mark:])
    finally:
        d.close()


LINE_LIMIT = 1024 * 1024  # src/relay.c: the longest worker line the relay passes on


@test
def a_worker_line_too_long_to_relay_is_dropped_whole():
    d = daemon()
    try:
        d.expect("add clap:fake#a 3", "resp 3")
        # just over the limit, and sizes that do and do not land on the relay buffer's doubling
        for size in (LINE_LIMIT + 1, LINE_LIMIT + 32 * 1024, LINE_LIMIT + 200 * 1024, LINE_LIMIT + 600 * 1024,
                     LINE_LIMIT * 3 // 2, 2 * LINE_LIMIT):
            mark = d.mark()
            d.expect("param_set 3 long_line %d" % size, "resp 0")
            check(d.wait_event("remote_pages_changed ", since=mark) == "remote_pages_changed 3",
                  "the line after the %d-byte one, unchanged" % size)
            with d.lock:
                pieces = ["%d bytes" % len(e) for e in d.events[mark:] if e.startswith("x")]
            check(not pieces, "no piece of a %d-byte line reaches the controller: %s" % (size, pieces))
        # the longest line relayed arrives whole
        mark = d.mark()
        d.expect("param_set 3 long_line %d" % LINE_LIMIT, "resp 0")
        check(d.wait_event("remote_pages_changed ", since=mark) == "remote_pages_changed 3",
              "the line after the %d-byte one, unchanged" % LINE_LIMIT)
        with d.lock:
            lines = [len(e) for e in d.events[mark:] if e.startswith("x")]
        check(lines == [LINE_LIMIT], "a line of exactly %d bytes arrives whole: %s" % (LINE_LIMIT, lines))
    finally:
        d.close()


# ---------------------------------------------------------------- presets, gestures, values the plugin moved, suggested pages

FROM_PLUGIN = ("param_gesture ", "param_set ", "remote_page_suggest ")


def from_plugin(d, since):
    return [e for e in d.events[since:] if e.startswith(FROM_PLUGIN)]


@test
def presets_are_listed_by_a_clap_worker_and_an_lv2_instance_on_mod_host_answers_no_list():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#a 0", "resp 0")
        d.expect("preset_list 0", "resp 2")
        d.expect("preset_get 0 0", 'resp 0 "file:///presets/warm.clap-preset" "Warm"')
        d.expect("preset_get 0 1", 'resp 0 urn:fake:bright "Bright \\"B\\""')
        d.expect("preset_get 0 2", "resp -902")
        d.expect("preset_list 9", "resp -3")
        d.expect("add fake:a 1", "resp 1")
        d.expect("preset_list 1", resp("NO_PRESET_LIST"))
        d.expect("preset_get 1 0", resp("NO_PRESET_LIST"))
        got = [c for c in sent_to(log) if c.startswith("preset_")]
        check(got == ["preset_list 0", "preset_get 0 0", "preset_get 0 1", "preset_get 0 2"],
              "the clap worker gets each as sent, mod-host none: %s" % got)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_gesture_the_value_it_moved_and_a_suggested_page_reach_the_controller_unchanged_and_in_order():
    d = daemon()
    try:
        d.expect("add clap:fake#a 3", "resp 3")
        mark = d.mark()
        d.expect("param_set 3 gesture 0.7000", "resp 0")
        wait_for(lambda: len(from_plugin(d, mark)) >= 4, "the plugin's four lines")
        check(from_plugin(d, mark) == ["param_gesture 3 0 begin", "param_set 3 0 0.7000", "param_gesture 3 0 end",
                                       "remote_page_suggest 3 8"], "as the worker wrote them: %s" % d.events[mark:])
        # an ended gesture is not ended again when its worker dies
        _, w = d.holder(3)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 3 ", since=mark)
        # (the replay of the cue writes its own begin and end again: only an end without its begin is the daemon's)
        seen = d.events[mark:]
        check(seen.count("param_gesture 3 0 end") == seen.count("param_gesture 3 0 begin"), "no gesture to end: %s" % seen)
    finally:
        d.close()


@test
def a_gesture_its_worker_did_not_end_is_ended_by_the_daemon_before_worker_died():
    d = daemon()
    try:
        d.expect("add clap:fake#a 3", "resp 3")
        d.expect("add clap:fake#b 4", "resp 4")
        mark = d.mark()
        d.expect("param_set 3 hold 1", "resp 0")
        d.expect("param_set 4 hold 1", "resp 0")
        d.wait_event("param_gesture 4 0 begin", since=mark)
        d.wait_event("param_gesture 3 0 begin", since=mark)
        _, w = d.holder(3)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        died = d.wait_event("worker_died ", since=mark)
        seen = d.events[mark:]
        check("param_gesture 3 0 end" in seen and seen.index("param_gesture 3 0 end") < seen.index(died),
              "the held gesture ends before the death is told: %s" % seen)
        check("param_gesture 4 0 end" not in seen, "another worker's gesture is not touched: %s" % seen)
        # a removed instance's worker goes too: its held gesture ends
        mark = d.mark()
        d.expect("remove 4", "resp 0")
        d.wait_event("param_gesture 4 0 end", since=mark)
    finally:
        d.close()


@test
def a_gesture_of_a_removed_instance_is_ended_once_though_its_pool_worker_stays():
    d = daemon()
    try:
        d.expect("add clap:fake#a 3 pool:p", "resp 3")
        d.expect("add clap:fake#a 5 pool:p", "resp 5")
        mark = d.mark()
        d.expect("param_set 5 hold 1", "resp 0")
        d.wait_event("param_gesture 5 0 begin", since=mark)
        pid = d.holder(5)[1]["pid"]
        mark = d.mark()
        d.expect("remove 5", "resp 0")
        d.wait_event("param_gesture 5 0 end", since=mark)
        check(d.holder(3)[1]["pid"] == pid, "the pool worker stays")
        mark = d.mark()
        d.expect("remove 3", "resp 0")
        check("param_gesture 5 0 end" not in d.events[mark:], "ended once: %s" % d.events[mark:])
    finally:
        d.close()


# ---------------------------------------------------------------- notes, and the tempo across a respawn

NOTES = ["note_on 0 0 60 100", "note_on 0 15 127 127", "note_off 0 0 60 0", "note_off 0 15 127 64", "all_notes_off 0"]
BAD_NOTES = ["note_on 0 16 60 100", "note_on 0 0 128 100", "note_on 0 0 60 0", "note_on 0 0 60 128", "note_on 0 -1 60 100",
             "note_on 0 0 60", "note_on 0 0 60 100 1", "note_on 0 0 6x 100", "note_on 0 0 60 +100", "note_off 0 0 60 128",
             "note_on 0 -0 60 100", "note_on 0 0 -0 100", "note_off 0 0 60 -0", "note_on -0 0 60 100", "note_off 0 0 60", "all_notes_off 0 0", "note_input 0 midi_in", "note_on x 0 60 100"]
NOTE_VERBS = ("note_input", "note_on", "note_off", "all_notes_off")


@test
def notes_reach_a_clap_worker_unchanged_and_an_effect_refuses_them():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#synth 0", "resp 0")
        d.expect("add clap:fake#a 1", "resp 1")
        d.expect("note_input 0", "resp 0 midi_in")
        d.expect("note_input 1", "resp 0 -")
        for line in NOTES:
            d.expect(line, "resp 0")
        for bad in BAD_NOTES:
            d.expect(bad, "resp -902")
        d.expect("note_on 1 0 60 100", resp("NO_NOTE_INPUT"))
        d.expect("all_notes_off 1", resp("NO_NOTE_INPUT"))
        d.expect("note_on 9 0 60 100", "resp -3")
        d.expect("note_input 9", "resp -3")
        got = [c for c in sent_to(log) if c.split(" ", 1)[0] in NOTE_VERBS]
        check(got == ["note_input 0", "note_input 1"] + NOTES + ["note_on 1 0 60 100", "all_notes_off 1"],
              "each note as sent, in order, and no line the daemon refused: %s" % got)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_worker_whose_note_queue_is_full_answers_the_declared_code_and_the_daemon_passes_it():
    """omx-clap-host refuses a note it has no room for in the block with NOTE_QUEUE_FULL; the daemon hands the code to the
    controller unchanged and keeps nothing of the note"""
    d = daemon()
    try:
        full = resp("NOTE_QUEUE_FULL")
        check(full != resp("NO_NOTE_INPUT") and int(full.split()[1]) <= -501, "a code of its own: %s" % full)
        d.expect("add clap:fake#synth_full 0", "resp 0")
        d.expect("note_on 0 0 60 100", full)
        d.expect("note_off 0 0 60 0", full)
        d.expect("all_notes_off 0", full)
        d.expect("note_input 0", "resp 0 midi_in")
    finally:
        d.close()


@test
def notes_are_never_replayed():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#synth 0", "resp 0")
        d.expect("note_on 0 0 60 100", "resp 0")
        d.expect("param_set 0 gain 0.2500", "resp 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        check("param_set 0 gain 0.2500" in sent, "the setting is replayed: %s" % sent)
        check(not [c for c in sent if c.split(" ", 1)[0] in NOTE_VERBS], "a note is never replayed: %s" % sent)
        d.expect("note_off 0 0 60 0", "resp 0")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def an_lv2_instance_on_mod_host_answers_notes_by_jack_and_mod_host_never_sees_them():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add fake:synth 0", "resp 0")
        d.expect("note_input 0", resp("NOTES_BY_JACK"))
        for line in NOTES:
            d.expect(line, resp("NOTES_BY_JACK"))
        for bad in BAD_NOTES:
            d.expect(bad, "resp -902")
        got = [c for c in sent_to(log) if c.split(" ", 1)[0] in NOTE_VERBS]
        check(got == [], "mod-host is sent no note: %s" % got)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


SETTINGS = ["set_bpb 3", "transport 1 4 140", "set_bpm 133", "transport_sync none"]


@test
def tempo_and_transport_are_handed_to_a_respawned_worker_before_its_add():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        # before any worker: kept for the first one
        d.expect("set_bpm 99", "resp 0")
        d.expect("add clap:fake#a 0", "resp 0")
        first = sent_to(log, d.holder(0)[1]["pid"])
        check(first[:2] == ["set_bpm 99", "add clap:fake#a 0"], "a worker's first lines: the tempo, then its add: %s" % first)
        d.expect("set_bpm 120", "resp 0")
        for line in SETTINGS:
            d.expect(line, "resp 0")
        # not the grammar: passed on, answered by the worker, never kept
        for bad in ("set_bpm fast", "set_bpm", "transport 1 4", "transport x 4 120", "set_bpb 3 4"):
            d.expect(bad, "resp 0")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        check(sent[:len(SETTINGS) + 1] == SETTINGS + ["add clap:fake#a 0"],
              "the latest of each, in the order last sent, before the add: %s" % sent)
        check(sum(1 for c in sent if c.startswith(("set_b", "transport"))) == len(SETTINGS), "each once: %s" % sent)
        # a worker of a new placement is handed them too
        d.expect("add clap:fake#b 1", "resp 1")
        sent = sent_to(log, d.holder(1)[1]["pid"])
        check(sent[:len(SETTINGS) + 1] == SETTINGS + ["add clap:fake#b 1"], "a new worker gets them first: %s" % sent)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_tempo_the_worker_refuses_is_kept_written_and_the_worker_still_comes_back():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log, "FAKE_REFUSE_SETTINGS": "1"})
    try:
        d.expect("add clap:fake#a 0", "resp 0")
        d.expect("set_bpm 133", "resp -902")
        _, w = d.holder(0)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        check(sent[:2] == ["set_bpm 133", "add clap:fake#a 0"], "kept though refused, and handed again: %s" % sent)
        check(d.holder(0)[1]["state"] == "up", "the worker is up: %s" % d.workers())
        check("refused 'set_bpm 133': resp -902" in d.log(), "the refusal is written: %s" % d.log()[-400:])
        d.expect("param_get 0 gain", "resp -103")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


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
        self.store = os.path.join(self.dir, "state", "plugin-hostd", "pins")

    def clap_pin(self, layout=None):
        return "pin_set %s omx-fault.clap=%s %s" % (self.clap_uri, sha(self.clap), layout or fake_layout())

    def lv2_pin(self, files=("manifest.ttl", "pinned.so", "pinned.ttl")):
        return "pin_set %s %s %s" % (LV2_URI, ",".join("%s=%s" % (f, sha(os.path.join(self.bundle, f))) for f in files),
                                     fake_layout())

    def daemon(self, conf=None, env=None):
        # strict unless a test asks for first-use; the store is the test's own, never the user's
        c = {"require_pins": 1, "pin_mode": "strict", "lv2_path": self.lv2_dir, "pin_store": self.store}
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
def an_unpinned_plugin_is_refused_under_strict_and_no_worker_starts():
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
        check(d.workers() == {}, "the worker of the refused instance is gone: %s" % d.workers())
    finally:
        d.close()
    os.unlink(p.log)
    d = p.daemon(conf={"rpc_timeout_ms": 400}, env={"FAKE_PIN_EXPECT_HANG": "1"})
    try:
        d.expect(p.clap_pin(), "resp 0")
        mark = d.mark()
        d.expect("add %s 0" % p.clap_uri, resp("VERB_DROPPED"))
        d.wait_event("instance_verb_dropped 0 pin_expect 0 %s" % fake_layout(), since=mark)
        check(p.verbs("pin_expect") and not p.verbs("add"), "a worker that does not answer the layout pin gets no add: %s"
              % p.received())
        check(d.workers() == {}, "the worker that did not answer is gone: %s" % d.workers())
        d.expect("instance_info 0", "resp -3")
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
def what_cannot_be_pinned_is_refused_and_never_pinned_in_part():
    line_max = next(c["value"] for c in harness.DECLARED["constants"] if c["name"] == "line_max")
    p = Plugins()
    d = p.daemon()
    try:
        # a path holding the digest separator: refused, and the earlier pin stands
        d.expect(p.lv2_pin(), "resp 0")
        eq = os.path.join(p.bundle, "a=b.so")
        write(eq, b"x")
        d.expect("pin_set %s a=b.so=%s,manifest.ttl=%s %s" % (LV2_URI, sha(eq), sha(os.path.join(p.bundle, "manifest.ttl")),
                                                              fake_layout()), "resp -902")
        d.expect("add %s 0" % LV2_URI, "resp 0")
        d.expect("remove 0", "resp 0")

        # a pin_set line of line_max bytes is taken, one byte more is not
        head = p.lv2_pin()
        cut = head.rindex(" ")
        pad = ",p%s=" + "0" * 64
        fill = line_max - len(head) - len(pad % "")
        d.expect(head[:cut] + (pad % ("a" * fill)) + head[cut:], "resp 0")
        check(len(head[:cut] + (pad % ("a" * fill)) + head[cut:]) == line_max, "the line is line_max long")
        d.expect(head[:cut] + (pad % ("a" * (fill + 1))) + head[cut:], "resp -902")
        d.expect(p.lv2_pin(), "resp 0")

        # a manifest that sets @base: its names are resolved against a base the daemon does not follow
        manifest = os.path.join(p.bundle, "manifest.ttl")
        good = open(manifest, "rb").read()
        write(manifest, b"@base <http://example.org/elsewhere/> .\n" + good)
        d.expect(p.lv2_pin(), "resp 0")
        mark = len(p.received())
        d.expect("add %s 1" % LV2_URI, resp("PIN_BINARY_MISMATCH"))

        # a percent-encoded name: the host decodes it, the daemon would hash the file of the name as written
        encoded = os.path.join(p.bundle, "pinned%2Eso")
        write(encoded, b"not the binary the host loads")
        write(manifest, (MANIFEST % LV2_URI).replace("<pinned.so>", "<pinned%2Eso>").encode())
        d.expect(p.lv2_pin(("manifest.ttl", "pinned%2Eso", "pinned.so", "pinned.ttl")), "resp 0")
        d.expect("add %s 1" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
        check(p.received()[mark:] == [], "no worker saw a refused add: %s" % p.received()[mark:])
        write(manifest, good)
    finally:
        d.close()
        p.close()


@test
def a_pinned_lv2_plugin_gets_a_worker_of_its_own():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect(p.lv2_pin(), "resp 0")
        d.expect("add %s 0 pool:fx" % LV2_URI, resp("PLACEMENT_INVALID"))
        check(d.workers() == {} and p.received() == [], "a refused pool starts no worker: %s" % d.workers())
        d.expect("policy_set lv2 pool:fx", "resp 0")
        d.expect("add %s 1 default" % LV2_URI, "resp 1")
        d.expect("add %s 2" % LV2_URI, "resp 2")
        for i in (1, 2):
            check(d.holder(i)[1]["place"] == "own" and d.holder(i)[1]["inst"] == [i],
                  "a default that resolves to a pool is placed own: %s" % d.workers())
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 3 pool:fx" % p.clap_uri, "resp 3")
        d.expect("add %s 4 pool:fx" % p.clap_uri, "resp 4")
        check(d.holder(3)[1]["place"] == "pool:fx" and d.holder(3)[1]["inst"] == [3, 4],
              "a pinned CLAP still goes into a pool: %s" % d.workers())
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
        d.wait_event("instance_replay_refused 0 %d" % harness.CODE["PIN_BINARY_MISMATCH"], since=mark)
        log = d.log()
        check("resp %d, its pin resp %d" % (harness.CODE["REPLAY"], harness.CODE["PIN_BINARY_MISMATCH"]) in log,
              "the refusal is written with PHD_ERR_REPLAY, the step and the pin's code: %s" % log[-400:])
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


@test
def a_layout_pinned_again_while_its_worker_was_down_is_refused_by_the_replayed_add():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        d.expect("param_set 0 gain 0.7", "resp 0")
        _, w = d.holder(0)
        d.expect(p.clap_pin(fake_layout("0.25")), "resp 0")
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_replay_refused 0 %d" % harness.CODE["PIN_LAYOUT_MISMATCH"], since=mark)
        d.wait_event("worker_respawned", since=mark)
        new = d.holder(0)[1]["pid"]
        check([c for pid, c in p.received() if int(pid) == new] ==
              ["pin_expect 0 %s" % fake_layout("0.25"), "add %s 0" % p.clap_uri],
              "the worker refused the replayed add and got none of its verbs: %s" % p.received())
        check(not [e for e in d.events[mark:] if e.startswith("instance_restored 0 ")], "instance 0 is not restored")
        check("resp %d, its add resp %d" % (harness.CODE["REPLAY"], harness.CODE["PIN_LAYOUT_MISMATCH"]) in d.log(),
              "the refusal is written with PHD_ERR_REPLAY, the step and the worker's code: %s" % d.log()[-400:])
    finally:
        d.close()
        p.close()


@test
def a_pin_whose_verdict_is_refused_refuses_the_add_with_its_own_code():
    """issue 71: verdict=refused names bytes that failed qualification; an add of them is refused by code, no worker
    sees it, and a replay of an instance whose pin turned refused is refused the same way"""
    p = Plugins()
    d = p.daemon()
    refused = harness.CODE.get("PIN_REFUSED")
    try:
        check(refused is not None, "the protocol declares PIN_REFUSED: %s" % sorted(harness.CODE))
        d.expect(p.clap_pin() + " verdict=refused", "resp 0")
        r = d.send("add %s 0" % p.clap_uri)
        check(r == "resp %d" % refused, "the add of a refused plugin answers PIN_REFUSED: %r" % r)
        check(d.workers() == {} and p.received() == [], "no worker started, none was told: %s %s" % (d.workers(), p.received()))
        # positive control: the same bytes qualified again run
        d.expect(p.clap_pin() + " verdict=isolated", "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        # a pin turned refused while the instance runs: its replay is refused with the same code
        _, w = d.holder(0)
        d.expect(p.clap_pin() + " verdict=refused", "resp 0")
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_replay_refused 0 %d" % refused, since=mark)
        check(not [e for e in d.events[mark:] if e.startswith("pin_changed")], "a refusal is no change of the files")
    finally:
        d.close()
    # bytes that changed are a mismatch first: a verdict is about the bytes it was given for
    d = p.daemon()
    try:
        d.expect(p.clap_pin().replace(sha(p.clap)[:8], "00000000") + " verdict=refused", "resp 0")
        d.expect("add %s 1" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
    finally:
        d.close()
    # a pin_file carries the verdict as pin_set does
    pins = os.path.join(p.dir, "pins.txt")
    write(pins, ("%s verdict=refused\n" % p.clap_pin().split(" ", 1)[1]).encode())
    d = p.daemon(conf={"pin_mode": "first-use", "pin_file": pins})
    try:
        r = d.send("add %s 2" % p.clap_uri)
        check(r == "resp %d" % refused, "a pin_file's refused verdict refuses the add: %r" % r)
        check(store_lines(p) == [], "and the refused plugin is not learned into the store")
    finally:
        d.close()
        p.close()


def own_worker_of(d, inst):
    return d.holder(inst)[1]["place"] == "own"


def store_lines(p):
    if not os.path.exists(p.store):
        return []
    with open(p.store) as f:
        return [l.split() for l in f if l.strip()]


@test
def first_use_pins_an_unpinned_plugin_and_runs_it_isolated():
    p = Plugins()
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("policy_set * pool:shared", "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        d.expect("add %s 1" % LV2_URI, "resp 1")
        check(own_worker_of(d, 0) and own_worker_of(d, 1), "unpinned plugins run isolated, not in the policy's pool: %s"
              % d.workers())
        got = [c.split()[0] for _, c in p.received()]
        check("pin_expect" not in got[:got.index("add")], "the first add sends no layout to expect: %s" % got)
        check(len(p.verbs("pin_layout")) == 1, "the layout was asked of the CLAP worker once: %s" % p.received())
        lines = store_lines(p)
        check(sorted(l[1] for l in lines) == sorted([p.clap_uri, LV2_URI]), "both pins are in the store: %s" % lines)
        clap = [l for l in lines if l[1] == p.clap_uri][0]
        check(clap[0] == "pin_set" and clap[3] == fake_layout() and clap[2].startswith("omx-fault.clap=%s" % sha(p.clap)),
              "the CLAP pin has its file digest and the layout the worker found: %s" % clap)
        d.expect("add %s 2 pool:p" % p.clap_uri, resp("PLACEMENT_INVALID"))
        d.expect("remove 0", "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check(p.verbs("pin_expect") == ["pin_expect 0 %s" % fake_layout()], "a later add checks the stored layout: %s"
              % p.received())
        check(len(p.verbs("pin_layout")) == 1, "a known layout is not asked again")
    finally:
        d.close()
    # a restart keeps what was learned
    os.unlink(p.log)
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check(p.verbs("pin_expect") == ["pin_expect 0 %s" % fake_layout()] and not p.verbs("pin_layout"),
              "the stored pin is checked after a restart and learned nothing: %s" % p.received())
    finally:
        d.close()
        p.close()


@test
def a_plugin_changed_after_first_use_is_refused_with_an_event_until_accepted():
    p = Plugins()
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        d.expect("remove 0", "resp 0")
        good = open(p.clap, "rb").read()
        write(p.clap, good[:-1] + b"X")
        mark = d.mark()
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        d.wait_event("pin_changed %s files" % p.clap_uri, since=mark)
        check(d.workers() == {}, "the changed plugin reached no worker: %s" % d.workers())
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        d.expect("pin_accept %s" % p.clap_uri, "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check(own_worker_of(d, 0), "an accepted plugin is isolated again")
        check(len(p.verbs("pin_layout")) == 2, "the layout is learned again after pin_accept: %s" % p.received())
        check([l for l in store_lines(p) if l[1] == p.clap_uri][0][2].startswith("omx-fault.clap=%s" % sha(p.clap)),
              "the store holds the new digest")
        d.expect("pin_accept clap:/nowhere/x.clap#id", resp("PIN_ABSENT"))
    finally:
        d.close()
        p.close()


@test
def a_layout_that_changed_after_first_use_is_refused_with_an_event():
    p = Plugins()
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
    finally:
        d.close()
    d = p.daemon(conf={"pin_mode": "first-use"}, env={"FAKE_LAYOUT_DEFAULT": "0.25"})
    try:
        mark = d.mark()
        d.expect("add %s 0" % p.clap_uri, resp("PIN_LAYOUT_MISMATCH"))
        d.wait_event("pin_changed %s layout" % p.clap_uri, since=mark)
    finally:
        d.close()
        p.close()


@test
def a_corrupt_store_line_is_kept_announced_and_its_plugin_is_not_learned_again():
    p = Plugins()
    bad = "pin_set %s not-a-pin-word\n" % p.clap_uri
    os.makedirs(os.path.dirname(p.store))
    write(p.store, bad.encode())
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        check("not a pin" in d.log() and "kept as it is" in d.log(), "the corrupt line is announced: %s" % d.log())
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        check(p.verbs("pin_layout") == [] and "its line in the pin store is corrupt" in d.log(),
              "the plugin of the corrupt line is refused, and says why: %s" % d.log())
        d.expect("add %s 1" % LV2_URI, "resp 1")   # another plugin is learned; that save keeps the corrupt line
        with open(p.store) as f:
            text = f.read()
        check(text.splitlines()[0] == bad.strip(), "the corrupt line survives the save verbatim: %r" % text)
        check(LV2_URI in text, "the new pin is saved beside it: %r" % text)
    finally:
        d.close()
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
    finally:
        d.close()
        p.close()


@test
def an_overlong_store_line_is_one_held_line_and_its_tail_is_not_a_pin():
    p = Plugins()
    os.makedirs(os.path.dirname(p.store))
    # a line longer than the daemon's read buffer whose tail, cut off where a buffer would end, is a good pin
    long_line = "pin_set junk " + "x" * 9000 + " " + p.clap_pin().split(" ", 1)[1]
    write(p.store, (long_line + "\n").encode())
    d = p.daemon()
    try:
        check("too long" in d.log(), "the overlong line is announced: %s" % d.log()[:300])
        d.expect("add %s 0" % p.clap_uri, resp("PIN_ABSENT"))
    finally:
        d.close()
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 1" % LV2_URI, "resp 1")
        with open(p.store) as f:
            lines = f.read().split("\n")
        check(lines[0] == long_line and len([l for l in lines if l]) == 2,
              "the overlong line survives the save as one line: %d lines" % len(lines))
    finally:
        d.close()
        p.close()


@test
def a_pin_line_too_long_for_pin_set_is_refused_when_learned():
    p = Plugins()
    names = ["f%03d-%s.ttl" % (n, "n" * 40) for n in range(120)]
    seealso = " ;\n    ".join("rdfs:seeAlso <%s>" % n for n in names)
    for n in names:
        write(os.path.join(p.bundle, n), b"x")
    write(os.path.join(p.bundle, "manifest.ttl"), (MANIFEST.replace("rdfs:seeAlso <pinned.ttl>", seealso) % LV2_URI).encode())
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
        check("too many files for one pin line" in d.log(), "the refusal is announced: %s" % d.log())
        check(store_lines(p) == [], "nothing too long is stored")
    finally:
        d.close()
        p.close()


@test
def a_missing_store_is_a_first_run_and_says_nothing():
    p = Plugins()
    check(not os.path.exists(p.store), "no store yet")
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check("not a pin" not in d.log() and "can't" not in d.log() and "NOT" not in d.log(), "a first run is quiet: %s" % d.log())
        check([l[1] for l in store_lines(p)] == [p.clap_uri], "the pin is saved: %s" % store_lines(p))
    finally:
        d.close()
        p.close()


@test
def a_store_that_cannot_be_written_is_announced_and_a_store_that_cannot_be_read_blocks_learning():
    p = Plugins()
    blocker = os.path.join(p.dir, "blocker")
    write(blocker, b"a file where the store's directory should be\n")
    d = p.daemon(conf={"pin_mode": "first-use", "pin_store": os.path.join(blocker, "pins")})
    try:
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check("can't write the pin store" in d.log() and "NOT persisted" in d.log(),
              "a failed save says the pin is not persisted: %s" % d.log())
    finally:
        d.close()
    os.makedirs(p.store)   # a store that exists and is not a readable file is not a first run
    d = p.daemon(conf={"pin_mode": "first-use"})
    try:
        check("can't read the pin store" in d.log(), "the unreadable store is announced: %s" % d.log())
        d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        check(os.path.isdir(p.store), "the store was not replaced")
    finally:
        d.close()
        p.close()


@test
def pin_accept_and_first_use_are_not_strict():
    p = Plugins()
    d = p.daemon()
    try:
        d.expect("pin_accept %s" % p.clap_uri, "resp -902")
        d.expect("add %s 0" % p.clap_uri, resp("PIN_ABSENT"))
        check(store_lines(p) == [], "strict learns nothing")
    finally:
        d.close()
        p.close()


@test
def a_pin_file_is_loaded_with_its_verdict_and_a_corrupt_hash_is_refused():
    p = Plugins()
    pins = os.path.join(p.dir, "pins.txt")
    write(pins, ("# written by plugin-qualify\n%s verdict=in-process\n" % p.clap_pin().split(" ", 1)[1]).encode())
    d = p.daemon(conf={"pin_mode": "first-use", "pin_file": pins})
    try:
        d.expect("policy_set * pool:shared", "resp 0")
        d.expect("add %s 0" % p.clap_uri, "resp 0")
        check(d.holder(0)[1]["place"] == "pool:shared", "a qualified in-process plugin follows the policy: %s" % d.workers())
        check(store_lines(p) == [], "a pin of the file is not written to the store")
    finally:
        d.close()
    bad = open(pins).read().replace(sha(p.clap)[:8], "00000000")
    write(pins, bad.encode())
    d = p.daemon(conf={"pin_mode": "first-use", "pin_file": pins})
    try:
        d.expect("add %s 1" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
    finally:
        d.close()
    write(pins, b"this is not a pin\n")
    try:
        p.daemon(conf={"pin_mode": "first-use", "pin_file": pins}).close()
        raise Fail("the daemon started on a pin file outside the grammar")
    except Fail as e:
        check("exited" in str(e) or "ready" in str(e), "the start failed on the pin file: %s" % e)
    finally:
        p.close()


# ---------------------------------------------------------------- who runs an LV2 plugin

class Programs:
    """two programs for the two workers, so a test sees which one ran a plugin: each wrapper notes its pid, its name and the
    LV2_PATH it was started with, then becomes the fake worker"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="plugin-hostd-programs.")
        self.notes = os.path.join(self.dir, "notes")
        open(self.notes, "w").close()
        self.mod_host = self.wrapper("mod-host")
        self.clap_host = self.wrapper("omx-clap-host")

    def wrapper(self, name):
        path = os.path.join(self.dir, name)
        write(path, ('#!/bin/sh\necho "$$ %s $LV2_PATH" >> %s\nexec %s "$@"\n' % (name, self.notes, FAKE)).encode())
        os.chmod(path, 0o755)
        return path

    def conf(self, **more):
        c = {"mod_host": self.mod_host, "clap_host": self.clap_host}
        c.update(more)
        return c

    def of(self, pid):
        """(program, LV2_PATH) of a worker, by pid"""
        with open(self.notes) as f:
            for line in f:
                parts = line.rstrip("\n").split(" ", 2)
                if parts[0] == str(pid):
                    return parts[1], parts[2] if len(parts) > 2 else ""
        raise Fail("no program started as pid %d" % pid)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def lv2_run(**conf):
    """a daemon with both programs; returns (daemon, programs, log path of every command a worker received)"""
    programs = Programs()
    log = os.path.join(programs.dir, "commands.log")
    return Daemon(EXE, FAKE, conf=programs.conf(**conf), env={"FAKE_LOG": log}), programs, log


def adds_of(log, pid):
    return [c for c in sent_to(log, pid) if c.startswith("add ")]


@test
def lv2_worker_defaults_to_mod_host_on_the_lv2_row():
    d, programs, log = lv2_run()
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        _, w = d.holder(0)
        check(w["fmt"] == "lv2", "the default row is lv2: %s" % w)
        check(programs.of(w["pid"])[0] == "mod-host", "mod-host runs it, not %s" % programs.of(w["pid"])[0])
        check(adds_of(log, w["pid"]) == ["add urn:test:a 0"], "mod-host is given the bare uri: %s" % adds_of(log, w["pid"]))
    finally:
        d.close()
        programs.close()


@test
def lv2_worker_omx_clap_host_runs_the_plugin_in_the_clap_program_on_the_adapter_row():
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        d.expect("add urn:test:b 1", "resp 1")
        for i, uri in ((0, "urn:test:a"), (1, "urn:test:b")):
            _, w = d.holder(i)
            check(w["fmt"] == "lv2-clap", "the adapter row: %s" % w)
            check(programs.of(w["pid"])[0] == "omx-clap-host", "omx-clap-host runs it, not %s" % programs.of(w["pid"])[0])
            check(adds_of(log, w["pid"]) == ["add lv2:%s %d" % (uri, i)],
                  "the adapter worker is given the uri with its lv2: prefix: %s" % adds_of(log, w["pid"]))
        d.expect("add clap:fake#c 2", "resp 2")
        check(d.holder(2)[1]["fmt"] == "clap", "a CLAP plugin is not affected")
    finally:
        d.close()
        programs.close()



@test
def a_plugin_can_be_given_its_own_lv2_worker_and_taken_back():
    d, programs, log = lv2_run()
    try:
        d.expect("lv2_worker_set lv2:urn:test:b omx-clap-host", "resp 0")
        d.expect("add urn:test:a 0", "resp 0")
        d.expect("add urn:test:b 1", "resp 1")
        check(d.holder(0)[1]["fmt"] == "lv2" and d.holder(1)[1]["fmt"] == "lv2-clap",
              "the override moves only its plugin: %s" % d.workers())
        d.expect("lv2_worker_set urn:test:b -", "resp 0")
        d.expect("add urn:test:b 2", "resp 2")
        check(d.holder(2)[1]["fmt"] == "lv2", "the override taken back, the setting holds again: %s" % d.workers())
        d.expect("lv2_worker_set urn:test:b nonsense", "resp -902")
        d.expect("lv2_worker_set urn:test:b", "resp -902")
        d.expect("lv2_worker_set urn:test:b -", "resp 0")
    finally:
        d.close()
        programs.close()
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        d.expect("lv2_worker_set urn:test:a mod-host", "resp 0")
        d.expect("add urn:test:a 0", "resp 0")
        d.expect("add urn:test:b 1", "resp 1")
        check(d.holder(0)[1]["fmt"] == "lv2" and d.holder(1)[1]["fmt"] == "lv2-clap",
              "the override can move a plugin the other way: %s" % d.workers())
    finally:
        d.close()
        programs.close()


@test
def the_adapter_row_answers_the_instance_verbs_from_its_worker_and_replays_track_info():
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        d.expect(TRACK, "resp 0")
        d.expect("remote_pages 0", "resp 2")
        d.expect("remote_page_get 0 0", 'resp 0 7 "Main" "Page \\"A\\"" 0 2 - - - - - -')
        d.expect("param_info 0 0", "resp 0 ms linear 1 2000 350 1 time_ms")
        _, w = d.holder(0)
        got = [c for c in sent_to(log, w["pid"]) if c.split(" ", 1)[0] in VERBS]
        check(got == [TRACK, "remote_pages 0", "remote_page_get 0 0", "param_info 0 0"],
              "the adapter's worker gets each verb as sent, where mod-host gets none: %s" % got)
        mark = d.mark()
        os.kill(w["pid"], signal.SIGKILL)
        d.wait_event("instance_restored 0 ", since=mark)
        sent = sent_to(log, d.holder(0)[1]["pid"])
        check([c.split(" ", 1)[0] for c in sent][:2] == ["add", "track_info"] and TRACK in sent,
              "the respawned adapter worker is given its track_info after the add: %s" % sent)
    finally:
        d.close()
        programs.close()


@test
def a_plugin_the_adapter_refuses_answers_a_named_code_and_the_event_names_the_reason():
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        mark = d.mark()
        d.expect("add lv2:urn:test:adapter_midi 0", resp("LV2_ADAPTER_REFUSED"))
        event = d.wait_event("lv2_adapter_refused ", since=mark)
        check(event == "lv2_adapter_refused urn:test:adapter_midi hosting.features.midi-in-fed-empty omx-clap-host", "the event: %r" % event)
        check(d.workers() == {}, "the worker that refused is gone, no instance is left: %s" % d.workers())
        d.expect("add lv2:urn:test:fine 1", "resp 1")
        check(d.holder(1)[1]["fmt"] == "lv2-clap", "another plugin still runs on the adapter")
        d.expect("lv2_worker_set urn:test:adapter_midi mod-host", "resp 0")
        d.expect("add lv2:urn:test:adapter_midi 2", "resp 2")
        check(d.holder(2)[1]["fmt"] == "lv2", "the refused plugin runs on mod-host once it is placed there")
        check(CODE_OF_REFUSAL == -512, "the code is stable: %s" % CODE_OF_REFUSAL)
    finally:
        d.close()
        programs.close()


CODE_OF_REFUSAL = harness.CODE["LV2_ADAPTER_REFUSED"]


@test
def under_auto_a_plugin_the_adapter_refuses_runs_on_mod_host_and_the_adapter_is_not_asked_again():
    d, programs, log = lv2_run(lv2_worker="auto")
    try:
        d.expect("add lv2:urn:test:fine 0", "resp 0")
        check(d.holder(0)[1]["fmt"] == "lv2-clap", "auto asks the adapter first: %s" % d.workers())
        mark = d.mark()
        d.expect("add lv2:urn:test:adapter_midi 1", "resp 1")
        event = d.wait_event("lv2_adapter_refused ", since=mark)
        check(event == "lv2_adapter_refused urn:test:adapter_midi hosting.features.midi-in-fed-empty auto", "the event: %r" % event)
        _, w = d.holder(1)
        check(w["fmt"] == "lv2" and programs.of(w["pid"])[0] == "mod-host", "the refused plugin runs on mod-host: %s" % w)
        check(adds_of(log, w["pid"]) == ["add urn:test:adapter_midi 1"], "mod-host is given the bare uri")
        mark = d.mark()
        d.expect("add lv2:urn:test:adapter_midi 2", "resp 2")
        check(d.holder(2)[1]["fmt"] == "lv2", "the second add goes straight to mod-host")
        asked = [c for c in sent_to(log) if c.startswith("add lv2:urn:test:adapter_midi")]
        check(len(asked) == 1, "the adapter was asked about the plugin once: %s" % asked)
        check(not [e for e in d.events[mark:] if e.startswith("lv2_adapter_refused")], "and said why once")
    finally:
        d.close()
        programs.close()
    # the CLAP program is not installed: auto runs the plugin on mod-host, an explicit omx-clap-host has no backend
    d, programs, log = lv2_run(lv2_worker="auto", clap_host="/nonexistent/omx-clap-host")
    try:
        d.expect("add lv2:urn:test:fine 0", "resp 0")
        check(d.holder(0)[1]["fmt"] == "lv2", "auto without the adapter's program is mod-host: %s" % d.workers())
        d.expect("lv2_worker_set urn:test:fine omx-clap-host", "resp 0")
        d.expect("add lv2:urn:test:fine 1", resp("NO_BACKEND"))
    finally:
        d.close()
        programs.close()


@test
def under_auto_a_refused_plugin_that_kills_mod_host_on_add_costs_only_its_own_worker():
    """issue 66: drumkv1 and its kin abort in instantiate with no display. The adapter refuses them, mod-host runs them,
    and the abort must not take the instances of a shared mod-host worker with it"""
    d, programs, log = lv2_run(lv2_worker="auto")
    try:
        d.expect("policy_set lv2 pool:fx", "resp 0")
        d.expect("lv2_worker_set urn:test:plain mod-host", "resp 0")
        d.expect("add lv2:urn:test:plain 0", "resp 0")
        k0, w0 = d.holder(0)
        check(w0["fmt"] == "lv2" and w0["place"] == "pool:fx", "positive control: the policy puts mod-host's plugins in the pool: %s" % w0)
        mark = d.mark()
        d.expect("add lv2:urn:test:adapter_midi_abort_on_mod_host 1", "resp -102")
        dropped = d.wait_event("instance_verb_dropped 1 ", since=mark)
        check(dropped == "instance_verb_dropped 1 add urn:test:adapter_midi_abort_on_mod_host 1",
              "the event names the instance and the plugin it died adding: %r" % dropped)
        died = d.wait_event("worker_died ", since=mark)
        check(not died.startswith("worker_died %s " % k0), "the pool's worker did not die: %s" % died)
        k, w = d.holder(0)
        check(k == k0 and w["pid"] == w0["pid"] and w["state"] == "up", "instance 0 kept its process: %s" % d.workers())
        check(not [e for e in d.events[mark:] if e.startswith(("instance_restored 0", "instance_quarantined"))],
              "nothing was restored or quarantined: %s" % d.events[mark:])
        d.expect("instance_info 1", "resp -3")
        # the adapter is not asked again, and the plugin is still not put in the pool
        d.expect("add lv2:urn:test:adapter_midi_abort_on_mod_host 3", "resp -102")
        k, w = d.holder(0)
        check(w["pid"] == w0["pid"], "a second add of it spares the pool too: %s" % d.workers())
        d.expect("add lv2:urn:test:adapter_midi 4", "resp 4")
        check(d.holder(4)[1]["place"] == "own", "a refused plugin that runs is placed own: %s" % d.workers())
        # an explicit placement is the caller's: it is kept
        d.expect("add lv2:urn:test:adapter_midi 2 pool:fx", "resp 2")
        check(d.holder(2)[0] == k0, "an explicit pool is honoured: %s" % d.workers())
    finally:
        d.close()
        programs.close()


@test
def the_code_of_a_refusal_is_the_one_on_the_reply_of_its_own_add():
    # one pool worker, one log: each refusal is named by its own reply, never by what an earlier one wrote on stderr
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        d.expect("add lv2:urn:test:fine 0 pool:fx", "resp 0")
        for i, (uri, code) in enumerate((("adapter_wide", "hosting.topology.wider-than-strip"),
                                         ("adapter_nocode", "-"),
                                         ("adapter_missing", "hosting.features.missing"),
                                         ("adapter_unrealised", "hosting.no-realisation"),
                                         ("adapter_nocode", "-")), 1):
            mark = d.mark()
            d.expect("add lv2:urn:test:%s %d pool:fx" % (uri, i), resp("LV2_ADAPTER_REFUSED"))
            event = d.wait_event("lv2_adapter_refused ", since=mark)
            check(event == "lv2_adapter_refused urn:test:%s %s omx-clap-host" % (uri, code), "the event of %s: %r" % (uri, event))
        w = d.holder(0)[1]
        check(w["inst"] == [0] and w["fmt"] == "lv2-clap", "the pool worker lived through the refusals: %s" % d.workers())
    finally:
        d.close()
        programs.close()


@test
def a_plugin_the_adapter_does_not_find_is_not_found_and_no_refusal():
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        mark = d.mark()
        d.expect("add lv2:urn:test:absent 0", "resp -101")
        check(d.workers() == {}, "no instance is left: %s" % d.workers())
        d.expect("add lv2:urn:test:adapter_midi 1", resp("LV2_ADAPTER_REFUSED"))
        d.wait_event("lv2_adapter_refused urn:test:adapter_midi ", since=mark)
        said = [e for e in d.events[mark:] if e.startswith("lv2_adapter_refused")]
        check(len(said) == 1, "the plugin not found is no refusal: %s" % said)
    finally:
        d.close()
        programs.close()
    # under auto, mod-host looks for it, for that add only: the adapter is asked again next time
    d, programs, log = lv2_run(lv2_worker="auto")
    try:
        mark = d.mark()
        d.expect("add lv2:urn:test:absent 0", "resp 0")
        _, w = d.holder(0)
        check(w["fmt"] == "lv2" and programs.of(w["pid"])[0] == "mod-host", "mod-host runs it: %s" % w)
        check(adds_of(log, w["pid"]) == ["add urn:test:absent 0"], "mod-host is given the bare uri")
        d.expect("add lv2:urn:test:absent 1", "resp 1")
        check(d.holder(1)[1]["fmt"] == "lv2", "and runs it again: %s" % d.workers())
        asked = [c for c in sent_to(log) if c.startswith("add lv2:urn:test:absent")]
        check(len(asked) == 2, "the adapter is asked on every add, nothing is remembered: %s" % asked)
        # a plugin neither finds is mod-host's own -101
        d.expect("add lv2:urn:test:absent_refuse 2", "resp -101")
        d.expect("add lv2:urn:test:adapter_midi 3", "resp 3")
        d.wait_event("lv2_adapter_refused urn:test:adapter_midi ", since=mark)
        said = [e for e in d.events[mark:] if e.startswith("lv2_adapter_refused")]
        check(len(said) == 1, "no event for the plugins the adapter did not find: %s" % said)
    finally:
        d.close()
        programs.close()


def adapter_asked(log, uri="urn:test:adapter_midi"):
    """how many times the adapter was sent an add of the uri"""
    return len([c for c in sent_to(log) if c.startswith("add lv2:%s " % uri)])


def refuse_once(d, log, uri="urn:test:adapter_midi"):
    """under auto: the adapter refuses the uri once, mod-host runs it, and the adapter is not asked on the next add"""
    d.expect("add lv2:%s 0" % uri, "resp 0")
    check(d.holder(0)[1]["fmt"] == "lv2", "the refused plugin runs on mod-host: %s" % d.workers())
    d.expect("add lv2:%s 1" % uri, "resp 1")
    check(adapter_asked(log, uri) == 1, "the adapter is asked once: %s" % sent_to(log))
    d.expect("remove -1", "resp 0")


def asked_again(d, log, uri="urn:test:adapter_midi"):
    before = adapter_asked(log, uri)
    d.expect("add lv2:%s 2" % uri, "resp 2")
    check(adapter_asked(log, uri) == before + 1, "the adapter is asked once more: %s" % sent_to(log))
    d.expect("remove -1", "resp 0")


@test
def lv2_worker_set_makes_the_adapter_be_asked_again_about_that_plugin_only():
    d, programs, log = lv2_run(lv2_worker="auto")
    try:
        refuse_once(d, log)
        d.expect("add lv2:urn:test:adapter_wide 3", "resp 3")
        d.expect("remove -1", "resp 0")
        d.expect("lv2_worker_set urn:test:adapter_wide auto", "resp 0")
        # the other plugin keeps its refusal
        d.expect("add lv2:urn:test:adapter_midi 4", "resp 4")
        check(adapter_asked(log) == 1, "the other plugin's refusal stands: %s" % sent_to(log))
        d.expect("remove -1", "resp 0")
        d.expect("lv2_worker_set lv2:urn:test:adapter_midi -", "resp 0")
        asked_again(d, log)
    finally:
        d.close()
        programs.close()


@test
def pin_set_and_pin_clear_make_the_adapter_be_asked_again():
    d, programs, log = lv2_run(lv2_worker="auto")
    try:
        refuse_once(d, log)
        d.expect("pin_set urn:test:adapter_midi pinned.so=%s %s" % ("0" * 64, fake_layout()), "resp 0")
        asked_again(d, log)
        # it refused again, and that is remembered again until the next change
        d.expect("pin_clear urn:test:adapter_midi", "resp 0")
        asked_again(d, log)
    finally:
        d.close()
        programs.close()


@test
def pin_accept_makes_the_adapter_be_asked_again():
    plugins = Plugins()
    uri = "urn:test:adapter_midi"
    bundle = os.path.join(plugins.lv2_dir, "adapter.lv2")
    os.makedirs(bundle)
    write(os.path.join(bundle, "manifest.ttl"), (MANIFEST % uri).encode())
    write(os.path.join(bundle, "pinned.so"), b"lv2 binary")
    write(os.path.join(bundle, "pinned.ttl"), b"lv2:port [ lv2:index 0 ; lv2:symbol \"gain\" ] .")
    programs = Programs()
    d = Daemon(EXE, FAKE, conf=programs.conf(lv2_worker="auto", require_pins=1, pin_mode="first-use", lv2_path=plugins.lv2_dir,
                                              pin_store=plugins.store), env={"FAKE_LOG": plugins.log})
    try:
        refuse_once(d, plugins.log, uri)
        write(os.path.join(bundle, "pinned.so"), b"lv2 binary, rebuilt")
        d.expect("add lv2:%s 3" % uri, resp("PIN_BINARY_MISMATCH"))
        check(adapter_asked(plugins.log, uri) == 1, "the changed plugin reached no worker: %s" % sent_to(plugins.log))
        d.expect("pin_accept lv2:%s" % uri, "resp 0")
        asked_again(d, plugins.log, uri)
    finally:
        d.close()
        programs.close()
        plugins.close()


@test
def lv2_worker_must_be_one_of_the_declared_values():
    programs = Programs()
    try:
        conf = os.path.join(programs.dir, "bad.conf")
        write(conf, b"lv2_worker nonsense\n")
        p = subprocess.run([EXE, "-n", "-p", "0", "-c", conf], capture_output=True, text=True, timeout=10)
        check(p.returncode != 0 and "lv2_worker 'nonsense' is not one of: mod-host omx-clap-host auto" in p.stderr,
              "the daemon refuses to start: %s %r" % (p.returncode, p.stderr))
    finally:
        programs.close()


@test
def the_adapter_row_keeps_the_pin_rules_of_the_lv2_row_and_checks_no_layout():
    programs = Programs()
    p = Plugins()
    d = p.daemon(conf=programs.conf(lv2_worker="omx-clap-host"))
    try:
        d.expect("add %s 0" % LV2_URI, resp("PIN_ABSENT"))
        check(d.workers() == {}, "an unpinned plugin starts no worker on the adapter row either")
        d.expect(p.lv2_pin(), "resp 0")
        # pin_pool: the world holds one bundle, so a pool is refused and a default that resolves to one is placed own
        d.expect("add %s 0 pool:fx" % LV2_URI, resp("PLACEMENT_INVALID"))
        d.expect("policy_set lv2-clap pool:fx", "resp 0")
        d.expect("add %s 1 default" % LV2_URI, "resp 1")
        d.expect("add %s 2" % LV2_URI, "resp 2")
        for i in (1, 2):
            _, w = d.holder(i)
            check(w["place"] == "own" and w["inst"] == [i] and w["fmt"] == "lv2-clap", "own, on the adapter row: %s" % d.workers())
        # layout_check: the layout of an LV2 pin is the ports', so the worker is never asked to check one or to report one
        check(p.verbs("pin_expect") == [] and p.verbs("pin_layout") == [],
              "no layout travels to the adapter's worker: %s" % p.received())
        # world_scope: the worker's LV2_PATH is a directory of one link, to the plugin's bundle
        _, w = d.holder(1)
        program, world = programs.of(w["pid"])
        check(program == "omx-clap-host" and world != p.lv2_dir and os.path.exists(os.path.join(world, "pinned.lv2", "manifest.ttl")),
              "the world is narrowed to the bundle: %s %s" % (program, world))
        check(os.listdir(world) == ["pinned.lv2"], "and holds nothing else: %s" % os.listdir(world))
        # the pin is checked on every add as it is for the lv2 row
        write(os.path.join(p.bundle, "pinned.so"), b"swapped")
        d.expect("add %s 3" % LV2_URI, resp("PIN_BINARY_MISMATCH"))
    finally:
        d.close()
        p.close()
        programs.close()


sys.exit(run_tests(TESTS))

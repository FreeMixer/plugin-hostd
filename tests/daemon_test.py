# SPDX-License-Identifier: GPL-3.0-or-later
# plugin-hostd against workers that are not plugin hosts (tests/fake-host). No jack, no plugin: the daemon's own
# behaviour, over the wire, the way a controller sees it. tests/jack_e2e.sh runs the real workers.
import json, os, shutil, signal, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
import scan_fixture
from harness import Daemon, Fail, alive, check, resp, run_tests, wait_for
from scan_fixture import CLAP_ID, FIELDS, LV2_COMPRESSOR, MANIFEST, PROBE, ROOT, descriptor_name, panel_name, sha, write

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
def a_word_past_the_grammar_of_a_daemon_verb_is_refused():
    d = daemon()
    try:
        # worker_list takes no word, supervisor_reset at most one and quit none, as protocol.h declares them
        d.expect("worker_list w1", "resp -902")
        d.expect("supervisor_reset all w1", "resp -902")
        d.expect("quit now", "resp -902")
        d.expect("worker_list", "resp 0")
        d.expect("supervisor_reset all", "resp 0")
    finally:
        d.close()


@test
def the_whitespace_that_ends_a_command_is_not_part_of_its_last_word():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add fake:a 0", "resp 0")
        # a tab separates words as a space does, so a tab at the end, after a carriage return, is trimmed like one
        d.expect("param_set 0 gain 0.5000\r\t", "resp 0")
        # read as bytes: a carriage return the worker was sent must not be taken for the end of a line of the log
        with open(log, "rb") as f:
            got = [l.split(b" ", 1)[1] for l in f.read().split(b"\n") if b" param_set " in l]
        check(got == [b"param_set 0 gain 0.5000"], "the worker gets the command without its trailing whitespace: %r" % got)
    finally:
        d.close()


@test
def a_state_root_that_does_not_exist_yet_is_made_and_the_add_answers():
    """issue 180: a configured state_root is created at start; an add used to answer -503 with nothing in the log"""
    base = tempfile.mkdtemp(prefix="plugin-hostd-root.")
    root = os.path.join(base, "run")
    d = daemon(conf={"state_root": root})
    try:
        d.expect("add fake:a 0", "resp 0")
        check(os.path.isdir(os.path.join(root, "plugin-hostd")), "the daemon's directory is under the new root")
    finally:
        d.close()
        shutil.rmtree(base, ignore_errors=True)


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


PRESET_LEARN_INSTANCE = ("preset_load 0 file:///presets/warm.preset", "preset_save 0 warm /tmp/presets warm.ttl",
                         "midi_learn 0 gain 0.0 1.0", "midi_map 0 gain 0 7 0.0 1.0", "midi_unmap 0 gain",
                         "cv_map 0 gain /cv/lfo 0.0 1.0 linear", "cv_unmap 0 gain")
PRESET_LEARN_WORLD = ("preset_show file:///presets/warm.preset", "bundle_add /usr/lib/lv2/warm.lv2",
                      "bundle_remove /usr/lib/lv2/warm.lv2 warm.ttl")


@test
def the_preset_bundle_and_learn_verbs_are_relayed_and_the_workers_answer_comes_back():
    """the host verb table requires preset_load, preset_save, preset_show, bundle_add, bundle_remove, midi_learn,
    midi_map, midi_unmap, cv_map and cv_unmap of a CLAP worker and of Zynthian: the daemon relays each one, an instance
    verb to the worker that holds the instance and the others to every worker, and passes the worker's answer back. It
    answers -902 only while the worker does"""
    for answers, want in ((True, "resp 0"), (False, "resp -902")):
        log = tempfile.mktemp(prefix="plugin-hostd-log.")
        d = daemon(env={"FAKE_LOG": log, "FAKE_PRESETS_LEARN": "answer" if answers else "refuse"})
        try:
            d.expect("add clap:fake#a 0", "resp 0")
            d.expect("add clap:fake#b 1", "resp 1")
            holder = d.holder(0)[1]["pid"]
            pids = {w["pid"] for w in d.workers().values()}
            for line in PRESET_LEARN_INSTANCE:
                d.expect(line, want)
                got = {pid for pid in pids if line in sent_to(log, pid)}
                check(got == {holder}, "%s reaches the holder of 0 only: %s of %s" % (line, sorted(got), sorted(pids)))
            for line in PRESET_LEARN_WORLD:
                d.expect(line, want)
                got = {pid for pid in pids if line in sent_to(log, pid)}
                check(got == pids, "%s reaches every worker: %s of %s" % (line, sorted(got), sorted(pids)))
            if answers:
                # an instance no add made is the daemon's own answer, mod-host's ERR_INSTANCE_NON_EXISTS, and no worker is asked
                d.expect("midi_learn 9 gain 0.0 1.0", "resp -3")
                check(not any("midi_learn 9" in c for c in sent_to(log)), "no worker was asked about 9")
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
def a_worker_that_warns_more_than_a_page_before_ready_still_starts():
    """lilv writes a warning line for every entry of the world that is no bundle, before mod-host says ready: a world
    of a few dozen stray files puts the marker past the first 4 KB of the log (plugin-hostd#105, resp -503)"""
    d = daemon(env={"FAKE_WARN_BEFORE_READY": "64"})
    try:
        t0 = time.time()
        d.expect("add fake:a 0", "resp 0")
        check(time.time() - t0 < 3, "the start saw the ready line, it did not wait out the ready timeout (%.1fs)" % (time.time() - t0))
        log = open(os.path.join(d.tmp, "plugin-hostd", str(d.proc.pid), "%s.log" % d.holder(0)[0])).read()
        check(log.index("ready!") > 4096, "positive control: the ready line sits past the first page of the log (%d)" % log.index("ready!"))
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


def can_lower():
    """whether this identity may give a process a nice below the one it has (CAP_SYS_NICE, or RLIMIT_NICE reaching it),
    asked of the kernel: a root without CAP_SYS_NICE, as in a container, cannot"""
    p = subprocess.Popen(["sleep", "30"])
    try:
        os.setpriority(os.PRIO_PROCESS, p.pid, os.getpriority(os.PRIO_PROCESS, p.pid) - 1)
        return True
    except PermissionError:
        return False
    finally:
        p.kill()
        p.wait()


@test
def worker_env_reaches_new_and_running_workers():
    cpus = sorted(os.sched_getaffinity(0))
    own = os.getpriority(os.PRIO_PROCESS, 0)   # the daemon's nice is the test's

    def applied(nice, current=own):
        """a daemon that cannot lower a nice cannot give a worker one below the one the worker has: its own, for a new worker"""
        return nice if can_lower() else max(nice, current)

    d = daemon()
    try:
        d.expect("worker_env lv2 %d 5" % cpus[0], "resp 0")
        d.expect("add fake:a 0", "resp 0")
        pid = d.holder(0)[1]["pid"]

        def stat():
            f = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
            allowed = [l for l in open("/proc/%d/status" % pid) if l.startswith("Cpus_allowed_list")][0].split()[1]
            return int(f[16]), allowed
        check(stat() == (applied(5), str(cpus[0])), "a new worker has nice %d and cpu %d: %s" % (applied(5), cpus[0], stat()))
        # the daemon says so when a nice is not applied, and only then
        kept = "worker_env: worker %d keeps nice" % pid
        check((kept in d.log()) == (applied(5) != 5), "a nice 5 not applied is logged, one applied is not: %r" % d.log())
        d.expect("worker_env lv2 - 7", "resp 0")
        check(stat()[0] == applied(7, applied(5)), "a running worker follows: %s" % (stat(),))
        check((kept in d.log()) == (applied(5) != 5 or applied(7, applied(5)) != 7), "the nice of a running worker is logged the same way")
        # lower than the worker has: only a privileged daemon can, and one that cannot says so
        have = stat()[0]
        d.expect("worker_env lv2 - %d" % (have - 1), "resp 0")
        check(stat()[0] == applied(have - 1, have), "a nice below the worker's: %s" % (stat(),))
        check(("keeps nice %d, the nice %d was not applied" % (have, have - 1) in d.log()) == (applied(have - 1, have) != have - 1),
              "a nice below the worker's is logged when it is not applied: %r" % d.log())
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
                # an empty line is a piece too: the end of a 2 MiB line whose start filled the relay buffer
                pieces = ["%d bytes" % len(e) for e in d.events[mark:] if e.startswith("x") or not e]
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
def a_value_the_plugin_moved_by_itself_reaches_the_controller_and_a_controllers_value_writes_no_feedback():
    """parameter feedback: a worker reports a value its plugin moved by itself (automation, an LFO, a preset load) as
    mod-host's param_set feedback line, and the daemon relays each one as written and in order. A value a controller
    set is answered and nothing more: a worker that reports nothing makes the daemon write no line of its own"""
    d = daemon()
    try:
        d.expect("add clap:fake#a 3", "resp 3")
        d.expect("add clap:fake#b 4", "resp 4")
        mark = d.mark()
        for line in ("param_set 3 0 0.5", "param_set 4 0 0.75", "bypass 3 1", "preset_load 4 urn:fake:bright"):
            d.expect(line, "resp 0")
        d.expect("param_set 3 moves 0.6000", "resp 0")
        wait_for(lambda: len(from_plugin(d, mark)) >= 2, "the two values the plugin moved")
        time.sleep(0.2)
        check(from_plugin(d, mark) == ["param_set 3 0 0.6000", "param_set 3 0 0.25"],
              "the plugin's values only, as written and in order, none for the controller's: %s" % d.events[mark:])
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

LV2_URI = "urn:test:pinned"


def fake_layout(default=None):
    """the layout pin of the fake's one parameter, as the fake computes it through pin.h"""
    env = dict(os.environ)
    if default is not None:
        env["FAKE_LAYOUT_DEFAULT"] = default
    return subprocess.check_output([FAKE, "-L"], env=env, text=True).strip()


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
        self.pins_dir = os.path.join(self.dir, "pins.d")

    def clap_pin(self, layout=None):
        return "pin_set %s omx-fault.clap=%s %s" % (self.clap_uri, sha(self.clap), layout or fake_layout())

    def lv2_pin(self, files=("manifest.ttl", "pinned.so", "pinned.ttl")):
        return "pin_set %s %s %s" % (LV2_URI, ",".join("%s=%s" % (f, sha(os.path.join(self.bundle, f))) for f in files),
                                     fake_layout())

    def daemon(self, conf=None, env=None):
        # strict unless a test asks for first-use; the store and the pins_dir are the test's own, never the user's or
        # the system's
        c = {"require_pins": 1, "pin_mode": "strict", "lv2_path": self.lv2_dir, "pin_store": self.store,
             "pins_dir": self.pins_dir}
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


def pin_line(p, verdict=None, good=True, uri=None, clap=None):
    """a pin line as a pins.d file holds it, no verb: the CLAP's real digest, or one that is not its own"""
    clap = clap or p.clap
    digest = sha(clap) if good else "0" * 64
    line = "%s %s=%s %s" % (uri or p.clap_uri, os.path.basename(clap), digest, fake_layout())
    return line + (" verdict=%s" % verdict if verdict else "")


def pins_d(p, files):
    """the test's pins_dir holding exactly these files, written in reverse name order so the directory's own order is
    not the order of their names"""
    shutil.rmtree(p.pins_dir, ignore_errors=True)
    os.makedirs(p.pins_dir)
    for name in sorted(files, reverse=True):
        write(os.path.join(p.pins_dir, name), "".join(l + "\n" for l in files[name]).encode())


def other_clap(p):
    """a second CLAP beside the first, for a uri that is not the one under test"""
    path = os.path.join(os.path.dirname(p.clap), "omx-other.clap")
    write(path, b"another clean build")
    return path, "clap:%s#org.openmixer.other" % path


def add_answer(p, conf, inst=0, uri=None):
    """the reply to one add of a fresh daemon over the test's pins_dir"""
    d = p.daemon(conf=conf)
    try:
        return d.send("add %s %d" % (uri or p.clap_uri, inst))
    finally:
        d.close()


@test
def a_pins_d_pin_admits_its_plugin_and_of_two_files_the_last_by_name_wins():
    """issue 42: the *.pins files of pins_dir are read at start in name order; a pin there admits its plugin under
    strict, and of two pins of one uri that are not refusals the file last by name, or the later line, holds"""
    p = Plugins()
    try:
        pins_d(p, {"10-a.pins": [pin_line(p, good=False)], "20-b.pins": [pin_line(p)]})
        r = add_answer(p, {})
        check(r == "resp 0", "the later file's good pin holds over the earlier bad one: %r" % r)
        pins_d(p, {"10-a.pins": [pin_line(p)], "20-b.pins": [pin_line(p, good=False)]})
        r = add_answer(p, {})
        check(r == resp("PIN_BINARY_MISMATCH"), "the later file's bad pin holds over the earlier good one: %r" % r)
        pins_d(p, {"10-a.pins": [pin_line(p, good=False), pin_line(p)]})
        r = add_answer(p, {})
        check(r == "resp 0", "in one file the later line holds: %r" % r)
        # only *.pins files that are not hidden are read: a package manager's leftovers and an editor's are not pins (the
        # hidden one is a refusal, which would win whatever its place in name order)
        pins_d(p, {"10-a.pins": [pin_line(p)], "20-b.pins.rpmnew": [pin_line(p, good=False)],
                   ".30-c.pins": [pin_line(p, "refused")], "README": [pin_line(p, good=False)]})
        r = add_answer(p, {})
        check(r == "resp 0", "a file that is not a .pins file holds no pin: %r" % r)
        # first-use trusts a package pin as it is: nothing is learned into the store
        d = p.daemon(conf={"pin_mode": "first-use"})
        try:
            d.expect("add %s 0" % p.clap_uri, "resp 0")
            check(store_lines(p) == [], "a package pin is not copied into the store: %s" % store_lines(p))
        finally:
            d.close()
    finally:
        p.close()


@test
def a_pins_d_refusal_wins_over_any_other_pins_d_pin_and_over_the_host():
    """issue 42, decisions of 2026-10-18: a pins.d pin of verdict=refused wins over another pins.d pin of its uri in
    either name order, and nothing of the host overrides it: not the store, not a pin_file, not pin_set, not
    pin_accept, not pin_clear"""
    p = Plugins()
    refused = resp("PIN_REFUSED")
    try:
        other, other_uri = other_clap(p)
        for files in ({"10-a.pins": [pin_line(p, "refused")], "20-b.pins": [pin_line(p, "isolated")]},
                      {"10-a.pins": [pin_line(p, "isolated")], "20-b.pins": [pin_line(p, "refused")]},
                      {"10-a.pins": [pin_line(p, "refused"), pin_line(p, "isolated")]}):
            pins_d(p, files)
            r = add_answer(p, {})
            check(r == refused, "a refusal wins whichever file or line comes last (%s): %r" % (sorted(files), r))
        pins_d(p, {"10-a.pins": [pin_line(p, "refused"), pin_line(p, "isolated", uri=other_uri, clap=other)]})
        # the store and a pin_file both hold the same files as isolated
        os.makedirs(os.path.dirname(p.store), exist_ok=True)
        write(p.store, ("pin_set %s\n" % pin_line(p, "isolated")).encode())
        pins = os.path.join(p.dir, "pins.txt")
        write(pins, (pin_line(p, "isolated") + "\n").encode())
        d = p.daemon(conf={"pin_mode": "first-use", "pin_file": pins})
        try:
            r = d.send("add %s 0" % p.clap_uri)
            check(r == refused, "the store and the pin_file do not override a pins.d refusal: %r" % r)
            r = d.send("pin_set %s" % pin_line(p, "isolated"))
            check(r == refused, "pin_set of a uri a pins.d pin refuses answers PIN_REFUSED: %r" % r)
            r = d.send("pin_accept %s" % p.clap_uri)
            check(r == refused, "pin_accept of it answers PIN_REFUSED: %r" % r)
            d.expect("pin_clear %s" % p.clap_uri, "resp 0")
            d.expect("pin_clear all", "resp 0")
            r = d.send("add %s 0" % p.clap_uri)
            check(r == refused, "after pin_set, pin_accept and pin_clear the refusal still holds: %r" % r)
            check(d.workers() == {} and p.received() == [], "no worker saw it: %s %s" % (d.workers(), p.received()))
            # positive control: the other plugin of the same file runs
            d.expect("add %s 1" % other_uri, "resp 1")
            check("which the pin of the pin_file does not override" in d.log(),
                  "stderr names the pin_file line that has no effect: %s" % d.log())
        finally:
            d.close()
        # the store alone: its line has no effect and is not dropped from the store either
        write(p.store, ("pin_set %s\n" % pin_line(p, "isolated")).encode())
        d = p.daemon(conf={"pin_mode": "first-use"})
        try:
            r = d.send("add %s 0" % p.clap_uri)
            check(r == refused, "the store does not override a pins.d refusal: %r" % r)
            check("which the pin of the pin store does not override" in d.log(), "stderr names the store line")
            d.expect("add %s 1" % other_uri, "resp 1")
            check([l[1] for l in store_lines(p)] == [p.clap_uri], "the store line is kept: %s" % store_lines(p))
        finally:
            d.close()
    finally:
        p.close()


@test
def the_host_holds_over_a_pins_d_pin_that_is_not_a_refusal():
    """issue 42: a pins.d pin that is not a refusal is under the host's layer: pin_set holds over it, a change of the
    files is announced by pin_changed until pin_accept records the new files in the store, which then hold across a
    restart, and pin_clear lets the package pin hold again"""
    p = Plugins()
    try:
        pins_d(p, {"50-pkg.pins": [pin_line(p, "isolated", good=False)]})
        d = p.daemon(conf={"pin_mode": "first-use"})
        try:
            mark = d.mark()
            d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
            d.wait_event("pin_changed %s files" % p.clap_uri, since=mark)
            check(store_lines(p) == [], "a plugin with a package pin is not learned: %s" % store_lines(p))
            d.expect("pin_accept %s" % p.clap_uri, "resp 0")
            d.expect("add %s 0" % p.clap_uri, "resp 0")
            check([l for l in store_lines(p) if l[1] == p.clap_uri][0][2] == "omx-fault.clap=%s" % sha(p.clap),
                  "the accepted files are in the store: %s" % store_lines(p))
        finally:
            d.close()
        d = p.daemon(conf={"pin_mode": "first-use"})
        try:
            d.expect("add %s 0" % p.clap_uri, "resp 0")
            d.expect("remove 0", "resp 0")
            d.expect("pin_clear %s" % p.clap_uri, "resp 0")
            d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
        finally:
            d.close()
        d = p.daemon()
        try:
            d.expect("add %s 0" % p.clap_uri, resp("PIN_BINARY_MISMATCH"))
            d.expect("pin_set %s" % pin_line(p), "resp 0")
            d.expect("add %s 0" % p.clap_uri, "resp 0")
        finally:
            d.close()
    finally:
        p.close()


@test
def a_bad_pins_d_line_or_file_is_skipped_and_the_rest_is_read():
    """issue 42: a line outside the grammar, a line longer than a pin line can be and a file that cannot be read are
    named on stderr and skipped; the daemon starts and the good lines hold"""
    p = Plugins()
    try:
        long_refusal = pin_line(p, "refused") + " " * 9000
        pins_d(p, {"10-a.pins": ["this is not a pin", long_refusal, pin_line(p)]})
        os.makedirs(os.path.join(p.pins_dir, "20-dir.pins"))
        d = p.daemon()
        try:
            d.expect("add %s 0" % p.clap_uri, "resp 0")
            log = d.log()
            path = os.path.join(p.pins_dir, "10-a.pins")
            check("%s:1: not a pin; the line is skipped" % path in log, "the bad line is named: %s" % log)
            check("%s:2: not a pin (the line is too long); the line is skipped" % path in log, "the long line is named")
            check("can't read the pins.d file %s" % os.path.join(p.pins_dir, "20-dir.pins") in log,
                  "the file that cannot be read is named: %s" % log)
        finally:
            d.close()
    finally:
        p.close()


@test
def an_empty_or_missing_pins_dir_holds_no_pins():
    """issue 42: a pins_dir that is missing, empty or not set holds no pins and is no error"""
    p = Plugins()
    try:
        for what, conf in (("missing", {}), ("empty", {}), ("not set", {"pins_dir": ""})):
            if what == "empty":
                os.makedirs(p.pins_dir)
            d = p.daemon(conf=conf)
            try:
                d.expect("add %s 0" % p.clap_uri, resp("PIN_ABSENT"))
                check("pins directory" not in d.log(), "a %s pins_dir is no error: %s" % (what, d.log()))
            finally:
                d.close()
        d = p.daemon(conf={"pin_mode": "first-use"})
        try:
            d.expect("add %s 0" % p.clap_uri, "resp 0")
            check(len(store_lines(p)) == 1, "first-use learns as before: %s" % store_lines(p))
        finally:
            d.close()
    finally:
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
def lv2_worker_mod_host_runs_an_lv2_plugin_on_the_lv2_row():
    d, programs, log = lv2_run(lv2_worker="mod-host")
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        _, w = d.holder(0)
        check(w["fmt"] == "lv2", "the mod-host row is lv2: %s" % w)
        check(programs.of(w["pid"])[0] == "mod-host", "mod-host runs it, not %s" % programs.of(w["pid"])[0])
        check(adds_of(log, w["pid"]) == ["add urn:test:a 0"], "mod-host is given the bare uri: %s" % adds_of(log, w["pid"]))
    finally:
        d.close()
        programs.close()


@test
def lv2_worker_defaults_to_auto_the_adapter_row_first():
    # None leaves lv2_worker out of the settings file: the daemon's own default holds
    d, programs, log = lv2_run(lv2_worker=None)
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        _, w = d.holder(0)
        check(w["fmt"] == "lv2-clap", "the default sends an LV2 plugin to the adapter row first: %s" % w)
        check(programs.of(w["pid"])[0] == "omx-clap-host", "omx-clap-host runs it, not %s" % programs.of(w["pid"])[0])
        check(adds_of(log, w["pid"]) == ["add lv2:urn:test:a 0"], "the adapter's worker is given the lv2: uri: %s" % adds_of(log, w["pid"]))
    finally:
        d.close()
        programs.close()


@test
def lv2_worker_default_without_the_adapter_worker_installed_is_the_lv2_row():
    # auto with no clap_host program on the system: the add is the lv2 row's, mod-host runs it, nothing is refused
    d, programs, log = lv2_run(lv2_worker=None, clap_host=os.path.join(tempfile.gettempdir(), "no-such-omx-clap-host"))
    try:
        d.expect("add lv2:urn:test:a 0", "resp 0")
        _, w = d.holder(0)
        check(w["fmt"] == "lv2", "no adapter worker installed: the lv2 row: %s" % w)
        check(programs.of(w["pid"])[0] == "mod-host", "mod-host runs it, not %s" % programs.of(w["pid"])[0])
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



def chain_of(d, chain):
    """the workers of place chain:<chain>"""
    return {k: w for k, w in d.workers().items() if w["place"] == "chain:%d" % chain}


def gains(d, ids):
    for i in ids:
        d.expect("param_get %d gain" % i, "resp 0 0.%d000" % (i % 10))


@test
def a_chain_is_declared_over_existing_instances_and_each_refusal_is_named():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        for i in (1, 2, 3, 4):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
            d.expect("param_set %d gain 0.%d000" % (i, i), "resp 0")
        d.expect("add fake:lv %d" % 9, "resp 9")
        before = d.workers()
        d.expect("chain 1 1 2 77", resp("CHAIN_UNKNOWN_INSTANCE"))
        d.expect("chain 1 1 2 1", resp("CHAIN_DUPLICATE"))
        d.expect("chain 1 1 9", resp("CHAIN_MIXED_FORMAT"))
        for bad in ("chain 1", "chain x 1 2", "chain 1 1 two", "chain -1 1 2", "chain_clear", "chain_clear x"):
            d.expect(bad, "resp -902")
        check(d.workers() == before, "a refused chain moves nothing: %s" % d.workers())
        old = d.holder(1)[1]["pid"]
        mark = d.mark()
        d.expect("chain 1 1 2 3", "resp 0")
        formed = d.wait_event("chain_formed 1 ", since=mark)
        w = chain_of(d, 1)
        check(len(w) == 1, "one worker runs the chain: %s" % d.workers())
        k, w = list(w.items())[0]
        check(w["inst"] == [1, 2, 3] and w["fmt"] == "clap" and w["state"] == "up", "its members, in order: %s" % w)
        check(formed == "chain_formed 1 %s 1,2,3" % k, "the event names the chain, its worker and the order: " + formed)
        check(not any(1 in x["inst"] or 2 in x["inst"] or 3 in x["inst"] for kk, x in d.workers().items() if kk != k),
              "the members left their own workers: %s" % d.workers())
        gains(d, (1, 2, 3, 4))
        was = sent_to(log, old)
        check([c.split()[0] for c in was[-2:]] == ["state_save", "remove"] and was[-1] == "remove 1",
              "the worker a member leaves saves its state, then removes it: %s" % was[-3:])
        got = sent_to(log, w["pid"])
        adds = [c.split()[2] for c in got if c.startswith("add ")]
        check(adds == ["1", "2", "3"] and "chain 1 1 2 3" in got and got.index("chain 1 1 2 3") > max(
              n for n, c in enumerate(got) if c.startswith("add ")), "the worker is given the adds, then the order: %s" % got)
        d.expect("chain 2 4 3", resp("CHAIN_INSTANCE_BUSY"))
        d.expect("chain_clear 5", resp("NO_SUCH_CHAIN"))
        d.expect("chain_clear 1", "resp 0")
        for i in (1, 2, 3):
            _, w = d.wait_up(i)
            check(w["place"] == "own" and w["inst"] == [i], "chain_clear gives %d a worker of its own: %s" % (i, w))
        check(chain_of(d, 1) == {}, "the chain's worker is gone: %s" % d.workers())
        gains(d, (1, 2, 3))
        d.expect("chain 2 4 3", "resp 0")
        d.wait_event("chain_formed 2 ", since=mark)
        check(list(chain_of(d, 2).values())[0]["inst"] == [4, 3], "a freed member joins another chain: %s" % d.workers())
        # a declared chain takes a new order; the member it leaves out goes back to a worker of its own
        d.expect("chain 2 3 1 2", "resp 0")
        check(list(chain_of(d, 2).values())[0]["inst"] == [3, 1, 2], "the new order: %s" % d.workers())
        _, w = d.wait_up(4)
        check(w["place"] == "own" and w["inst"] == [4], "the member left out is alone: %s" % w)
        # a removed member leaves the order and the worker is told the order without it
        k, w = list(chain_of(d, 2).items())[0]
        d.expect("remove 3", "resp 0")
        check(chain_of(d, 2)[k]["inst"] == [1, 2], "the chain goes on without it, in order: %s" % d.workers())
        check(sent_to(log, w["pid"])[-1] == "chain 2 1 2", "the worker is told: %s" % sent_to(log, w["pid"])[-3:])
        d.expect("remove 1", "resp 0")
        d.expect("remove 2", "resp 0")
        d.expect("chain_clear 2", resp("NO_SUCH_CHAIN"))
        # mod-host runs no chain: its members share one worker and it is never sent the line
        d.expect("add fake:lv 8", "resp 8")
        d.expect("chain 3 9 8", "resp 0")
        k, w = list(chain_of(d, 3).items())[0]
        check(w["inst"] == [9, 8] and w["fmt"] == "lv2", "an lv2 chain is one worker too: %s" % w)
        check(not any(c.startswith("chain") for c in sent_to(log, w["pid"])), "mod-host never sees the line")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_chain_of_one_runs_in_a_worker_of_its_own_and_a_chain_of_none_is_refused():
    """chain_members_min is 1: one isolated plugin is a chain like any other, and a chain with no member is no line"""
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add clap:fake#solo 21", "resp 21")
        d.expect("param_set 21 gain 0.7000", "resp 0")
        before = d.workers()
        d.expect("chain 5", "resp -902")
        check(d.workers() == before and chain_of(d, 5) == {}, "a chain of none moves nothing: %s" % d.workers())
        d.expect("chain_clear 5", resp("NO_SUCH_CHAIN"))
        mark = d.mark()
        d.expect("chain 5 21", "resp 0")
        formed = d.wait_event("chain_formed 5 ", since=mark)
        w = chain_of(d, 5)
        check(len(w) == 1, "one worker runs the chain of one: %s" % d.workers())
        k, w = list(w.items())[0]
        check(w["inst"] == [21] and w["state"] == "up", "its one member: %s" % w)
        check(formed == "chain_formed 5 %s 21" % k, "the event names the chain of one: " + formed)
        d.expect("param_get 21 gain", "resp 0 0.7000")
        check("chain 5 21" in sent_to(log, w["pid"]), "the worker is told the chain of one: %s" % sent_to(log, w["pid"]))
        d.expect("chain_clear 5", "resp 0")
        _, w = d.wait_up(21)
        check(w["place"] == "own" and w["inst"] == [21], "chain_clear gives the member a worker of its own: %s" % w)
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def under_require_pins_a_chain_of_lv2_members_runs_in_a_world_of_the_union_of_their_bundles():
    """an LV2 pin holds only in a world narrowed to the plugin's bundle: a chain's worker sees a world narrowed to the union
    of its members' bundles, each linked once, so a chain of pinned LV2 members forms under require_pins; a chain with a
    member whose bundle is gone is refused with PLACEMENT_INVALID and nothing moves"""
    programs = Programs()
    p = Plugins()
    uri = "urn:test:second"
    second = os.path.join(p.lv2_dir, "second.lv2")
    os.makedirs(second)
    write(os.path.join(second, "manifest.ttl"), (MANIFEST % uri).encode())
    write(os.path.join(second, "pinned.so"), b"second lv2 binary")
    write(os.path.join(second, "pinned.ttl"), b"lv2:port [ lv2:index 0 ; lv2:symbol \"gain\" ] .")
    write(os.path.join(p.lv2_dir, "stray.lv2.txt"), b"no bundle")
    d = p.daemon(conf=programs.conf(lv2_worker="omx-clap-host"))
    try:
        d.expect(p.lv2_pin(), "resp 0")
        d.expect("pin_set %s %s %s" % (uri, ",".join("%s=%s" % (f, sha(os.path.join(second, f)))
                                                      for f in ("manifest.ttl", "pinned.so", "pinned.ttl")), fake_layout()), "resp 0")
        d.expect("add %s 1" % LV2_URI, "resp 1")
        d.expect("add %s 2" % uri, "resp 2")
        d.expect("add %s 3" % LV2_URI, "resp 3")
        mark = d.mark()
        d.expect("chain 4 1 2 3", "resp 0")
        d.wait_event("chain_formed 4 ", since=mark)
        k, w = list(chain_of(d, 4).items())[0]
        check(w["inst"] == [1, 2, 3] and w["fmt"] == "lv2-clap", "one adapter worker runs the chain: %s" % d.workers())
        program, world = programs.of(w["pid"])
        check(program == "omx-clap-host" and world != p.lv2_dir, "the chain's world is narrowed: %s %s" % (program, world))
        check(sorted(os.listdir(world)) == ["pinned.lv2", "second.lv2"],
              "it holds the union of the members' bundles, each once, and nothing else: %s" % os.listdir(world))
        check(os.path.exists(os.path.join(world, "second.lv2", "manifest.ttl")), "each link reaches its bundle")
        check("chain 4 1 2 3" in [c for _, c in p.received()], "the worker is told the chain: %s" % p.received()[-4:])
        # a chain of one gets the world of its one member
        d.expect("add %s 5" % uri, "resp 5")
        mark = d.mark()
        d.expect("chain 6 5", "resp 0")
        d.wait_event("chain_formed 6 ", since=mark)
        _, w = list(chain_of(d, 6).items())[0]
        check(os.listdir(programs.of(w["pid"])[1]) == ["second.lv2"], "a chain of one sees its own bundle only")
        # a member whose bundle is gone leaves no union to build: the chain is refused and nothing moves
        d.expect("add %s 7" % uri, "resp 7")
        d.expect("add %s 8" % LV2_URI, "resp 8")
        shutil.move(second, second + ".gone")
        before, seen = d.workers(), len(p.received())
        d.expect("chain 9 8 7", resp("PLACEMENT_INVALID"))
        check(d.workers() == before and chain_of(d, 9) == {}, "a refused chain moves nothing: %s" % d.workers())
        check(p.received()[seen:] == [], "no worker saw a refused chain: %s" % p.received()[seen:])
        d.expect("chain_clear 9", resp("NO_SUCH_CHAIN"))
    finally:
        d.close()
        p.close()
        programs.close()


@test
def a_chain_of_three_runs_in_one_worker_and_its_crashed_member_is_quarantined_while_the_others_go_on_in_order():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        for i in (10, 11, 12):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
            d.expect("param_set %d gain 0.%d000" % (i, i % 10), "resp 0")
        d.expect("chain 7 10 11 12", "resp 0")
        d.wait_event("chain_formed 7 ")
        k, w = list(chain_of(d, 7).items())[0]
        check(w["inst"] == [10, 11, 12] and len(d.workers()) == 1, "three members, one worker: %s" % d.workers())
        # every instance verb names one member by its own number
        d.expect("bypass 12 1", "resp 0")
        d.expect("param_set 10 gain 0.5000", "resp 0")
        d.expect("param_get 10 gain", "resp 0 0.5000")
        d.expect("param_get 11 gain", "resp 0 0.1000")
        d.expect("param_info 11 0", "resp 0 ms linear 1 2000 350 1 time_ms")
        got = sent_to(log, w["pid"])
        check(["bypass 12 1", "param_set 10 gain 0.5000", "param_info 11 0"] == [c for c in got if c.startswith(
              ("bypass", "param_set 10", "param_info"))], "the chain's worker got each by its instance: %s" % got)
        d.expect("param_set 10 gain 0.0000", "resp 0")
        mark = d.mark()
        d.expect("param_set 11 crash 1", "resp 0")
        died = d.wait_event("worker_died %s " % k, since=mark)
        check(died.endswith(" 10,11,12"), "the chain's worker died with all three: " + died)
        d.wait_event("instance_quarantined 11 %s" % k, since=mark)
        formed = d.wait_event("chain_formed 7 ", since=mark)
        k2, w2 = list(chain_of(d, 7).items())[0]
        check(formed == "chain_formed 7 %s 10,12" % k2 and w2["inst"] == [10, 12] and w2["state"] == "up",
              "the chain goes on with the other two in order: %s %s" % (formed, w2))
        check("chain 7 10 12" in sent_to(log, w2["pid"]), "and its worker is told the order: %s" % sent_to(log, w2["pid"]))
        k11, w11 = d.wait_up(11)
        check(w11["place"] == "own" and w11["inst"] == [11] and k11 != k2, "the crashed member runs alone: %s" % w11)
        gains(d, (10, 11, 12))
        d.expect("param_get 12 :bypass", "resp 0 1")
        info = d.send("instance_info 11").split()
        check(info[6] == "1" and int(info[5]) == 1, "instance_info names the culprit: %s" % info)
        check(not any(e.startswith("instance_quarantined") and e.split()[1] in ("10", "12") for e in d.events),
              "no neighbour was quarantined: %s" % d.events)
        # cleared, it goes back into its place in the order
        mark = d.mark()
        d.expect("quarantine_clear 11", "resp 0")
        formed = d.wait_event("chain_formed 7 ", since=mark)
        k3, w3 = list(chain_of(d, 7).items())[0]
        check(formed.endswith(" 10,11,12") and w3["inst"] == [10, 11, 12] and len(d.workers()) == 1,
              "the chain is whole again: %s %s" % (formed, d.workers()))
        gains(d, (10, 11, 12))
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_chain_that_dies_naming_no_culprit_is_split_and_rejoins_without_the_one_that_dies_again():
    d = daemon(conf={"suspect_window_ms": 0})
    try:
        for i in (20, 21, 22):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
            d.expect("param_set %d gain 0.%d000" % (i, i % 10), "resp 0")
        d.expect("chain 4 20 21 22", "resp 0")
        # the declaration's own chain_formed comes on the feedback port, after the reply: it is not the rejoin's
        d.wait_event("chain_formed 4 ")
        mark = d.mark()
        # no suspect window: the death names no one, the members are split, and the verb is replayed to 21 alone
        d.expect("param_set 21 crash 1", "resp 0")
        d.wait_event("instance_quarantined 21 ", since=mark)
        formed = d.wait_event("chain_formed 4 ", since=mark)
        k, w = list(chain_of(d, 4).items())[0]
        wait_for(lambda: d.workers()[k]["state"] == "up", "the chain's worker up")
        check(formed == "chain_formed 4 %s 20,22" % k and d.workers()[k]["inst"] == [20, 22],
              "the others rejoin in order: %s %s" % (formed, d.workers()))
        _, w21 = d.holder(21)
        check(w21["place"] == "own" and w21["inst"] == [21], "the one that died again is alone: %s" % w21)
        gains(d, (20, 22))
    finally:
        d.close()


@test
def a_worker_that_runs_no_chain_refuses_the_line_and_the_members_still_share_it():
    d = daemon(env={"FAKE_REFUSE_CHAIN": "1"})
    try:
        for i in (40, 41):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        mark = d.mark()
        d.expect("chain 5 41 40", "resp 0")
        d.wait_event("chain_formed 5 ", since=mark)
        k, w = list(chain_of(d, 5).items())[0]
        check(w["inst"] == [41, 40] and w["state"] == "up", "the members share the worker: %s" % w)
        check("refused 'chain 5 41 40'" in d.log(), "the refusal is written: %s" % d.log()[-400:])
    finally:
        d.close()


@test
def chain_get_reads_a_chain_back_as_declared_and_as_it_runs():
    d = daemon()
    try:
        for i in (50, 51, 52):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("chain_get 8", resp("NO_SUCH_CHAIN"))
        for bad in ("chain_get", "chain_get x", "chain_get 8 9"):
            d.expect(bad, "resp -902")
        mark = d.mark()
        d.expect("chain 8 52 50 51", "resp 0")
        d.wait_event("chain_formed 8 ", since=mark)
        k = list(chain_of(d, 8))[0]
        d.expect("chain_get 8", "resp 0 %s 52,50,51 52,50,51" % k)
        # a crashed member is declared and not running
        mark = d.mark()
        d.expect("param_set 50 crash 1", "resp 0")
        d.wait_event("instance_quarantined 50 ", since=mark)
        d.wait_event("chain_formed 8 ", since=mark)
        k2 = list(chain_of(d, 8))[0]
        wait_for(lambda: d.workers()[k2]["state"] == "up", "the chain's worker up")
        d.expect("chain_get 8", "resp 0 %s 52,50,51 52,51" % k2)
        d.expect("chain_clear 8", "resp 0")
        d.expect("chain_get 8", resp("NO_SUCH_CHAIN"))
    finally:
        d.close()


@test
def a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(env={"FAKE_LOG": log})
    try:
        for i in (1, 3, 4):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
            d.expect("param_set %d gain 0.%d000" % (i, i), "resp 0")
        d.expect("connect effect_4:out_1 system:playback_1", "resp 0")
        mark = d.mark()
        d.expect("chain 2 1 3", "resp 0")
        d.wait_event("chain_formed 2 ", since=mark)
        k, w = list(chain_of(d, 2).items())[0]
        pid, own4 = w["pid"], d.holder(4)[1]["pid"]
        # a survivor's value moved since its checkpoint: the joiner's state must not load the survivors' again
        d.expect("param_set 1 gain 0.9000", "resp 0")
        # a member joins at a position: the same worker, its add, the order, its state, its connection
        seen, mark = len(sent_to(log, pid)), d.mark()
        d.expect("chain 2 1 4 3", "resp 0")
        formed = d.wait_event("chain_formed 2 ", since=mark)
        check(chain_of(d, 2) == {k: dict(w, inst=[1, 4, 3])}, "the same worker, the new order: %s" % d.workers())
        check(formed == "chain_formed 2 %s 1,4,3" % k, "chain_formed names the same worker: " + formed)
        got = sent_to(log, pid)[seen:]
        check([c.split()[0] for c in got] == ["add", "chain", "state_load", "connect"] and got[0] == "add clap:fake#m4 4"
              and got[1] == "chain 2 1 4 3" and got[3] == "connect effect_4:out_1 system:playback_1",
              "the running worker is sent the add, the order, the joiner's state and its connection only: %s" % got)
        check(not any(x["pid"] == own4 for x in d.workers().values()), "the joiner's own worker is retired: %s" % d.workers())
        gains(d, (3, 4))
        d.expect("param_get 1 gain", "resp 0 0.9000")
        d.expect("chain_get 2", "resp 0 %s 1,4,3 1,4,3" % k)
        # a move is the order and nothing else
        seen, mark = len(sent_to(log, pid)), d.mark()
        d.expect("chain 2 3 1 4", "resp 0")
        d.wait_event("chain_formed 2 %s 3,1,4" % k, since=mark)
        check(sent_to(log, pid)[seen:] == ["chain 2 3 1 4"], "a move sends the order only: %s" % sent_to(log, pid)[seen:])
        d.expect("chain_get 2", "resp 0 %s 3,1,4 3,1,4" % k)
        # a member left out goes to a worker of its own; the chain's worker goes on
        seen, mark = len(sent_to(log, pid)), d.mark()
        d.expect("chain 2 3 4", "resp 0")
        d.wait_event("chain_formed 2 %s 3,4" % k, since=mark)
        check(sent_to(log, pid)[seen:][-2:] == ["remove 1", "chain 2 3 4"], "removed, then the order: %s" % sent_to(log, pid)[seen:])
        _, w1 = d.wait_up(1)
        check(w1["place"] == "own" and w1["inst"] == [1], "the member left out is alone: %s" % w1)
        check(chain_of(d, 2)[k]["pid"] == pid, "no survivor restarted: %s" % d.workers())
        gains(d, (3, 4))
        d.expect("param_get 1 gain", "resp 0 0.9000")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


# ---------------------------------------------------------------- plan (the grouping planner, src/planner.c)

def plan_of(d, plan):
    """{k: worker} of the segment workers of a plan, place chain:<plan>.<k>, by the segment's k"""
    prefix = "chain:%d." % plan
    return {int(w["place"][len(prefix):]): dict(w, name=name) for name, w in d.workers().items() if w["place"].startswith(prefix)}


def clap_n(p, n):
    """the uri of the n-th plugin of one file: five plugins in one .clap, each with a pin of its own"""
    return "clap:%s#org.openmixer.fault.%d" % (p.clap, n)


def pin_n(p, n, verdict=None):
    return "pin_set %s omx-fault.clap=%s %s%s" % (clap_n(p, n), sha(p.clap), fake_layout(), " verdict=" + verdict if verdict else "")


def record_for(d, plugin_id, ns_p95, rate=48000, quantum=128, name=None):
    """a qualification record of plugin-qualify, as far as the daemon reads one: the cost of one grid point"""
    point = {"rate": rate, "quantum": quantum, "outcome": "probe.ok",
             "cost": {"median": ns_p95 / 2, "percentile": {"p": 95, "value": ns_p95}, "blocks": 100, "warmupBlocks": 10}}
    doc = {"schema": "plugin-qualify.qualification-record/1", "plugin": {"format": "clap", "id": plugin_id},
           "measurements": {"grid": [point]}}
    path = os.path.join(d.tmp, "qualification", name or "%s@1.0-0123456789ab.default.qualification.json" % plugin_id)
    with open(path, "w") as f:
        json.dump(doc, f)


def plan_run(conf=None, history=None):
    """five pinned plugins of one file under first-use, 3 of verdict isolated and 6 never given a verdict, a daemon with
    grouping on. history is the body of a history file the daemon finds at start: the lines of {n: "key=value ..."}, each
    for the n-th plugin and the binary its pin holds, under the test's own host class, or a string written as it is"""
    p = Plugins()
    c = {"pin_mode": "first-use", "grouping": "on"}
    if history is not None:
        path = os.path.join(p.dir, "history")
        if isinstance(history, str):
            body = history
        else:
            body = "# plugin-hostd history/1\n" + "".join(
                "history %s %s %s %s\n" % (clap_n(p, n), sha(p.clap), HISTORY_CLASS, kv) for n, kv in sorted(history.items()))
        write(path, body.encode())
        c.update({"history_file": path, "host_class": HISTORY_CLASS, "history_window_s": 3600})
    c.update(conf or {})
    d = p.daemon(conf=c)
    for n in (1, 2, 4, 5):
        d.expect(pin_n(p, n, "in-process"), "resp 0")
    d.expect(pin_n(p, 3, "isolated"), "resp 0")
    for n in range(1, 7):
        d.expect("add %s %d" % (clap_n(p, n), n), "resp %d" % n)
    return p, d


@test
def a_plan_forms_the_runs_that_may_share_and_leaves_the_member_that_may_not_in_a_worker_of_its_own():
    """A B C D E with C isolated is [A B] [C] [D E]: chain workers of place chain:1.0 and chain:1.2 (k counts the segments of
    the plan, the lone one too), and C own"""
    p, d = plan_run()
    try:
        for n in range(1, 6):
            d.expect("param_set %d gain 0.%d000" % (n, n), "resp 0")
        mark = d.mark()
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4,5")
        e0 = d.wait_event("chain_formed 1.0 ", since=mark)
        e1 = d.wait_event("chain_formed 1.2 ", since=mark)
        segs = plan_of(d, 1)
        check(sorted(segs) == [0, 2] and segs[0]["inst"] == [1, 2] and segs[2]["inst"] == [4, 5], "two chain workers: %s" % d.workers())
        check(e0 == "chain_formed 1.0 %s 1,2" % segs[0]["name"] and e1 == "chain_formed 1.2 %s 4,5" % segs[2]["name"],
              "the events name the segments: %s / %s" % (e0, e1))
        _, w3 = d.wait_up(3)
        check(w3["place"] == "own" and w3["inst"] == [3], "the isolated member is alone: %s" % w3)
        gains(d, (1, 2, 3, 4, 5))
        d.expect("plan_get 1", "resp 0 1,2;3;4,5 1:cost-assumed,2:cost-assumed,3:verdict-isolated,4:cost-assumed,5:cost-assumed")
        check(d.wait_event("plan_reason 1 ", since=mark) == "plan_reason 1 1:cost-assumed,2:cost-assumed,3:verdict-isolated,"
              "4:cost-assumed,5:cost-assumed", "the plan_reason event carries the reasons")
        # a member that was never given a verdict is alone as well
        d.expect("plan 2 6", "resp 0 6")
        d.expect("plan_get 2", "resp 0 6 6:no-verdict")
        d.expect("plan 3 5", resp("CHAIN_INSTANCE_BUSY"))
    finally:
        d.close()
        p.close()


@test
def a_plan_again_keeps_the_worker_of_a_segment_that_did_not_change_and_forms_the_ones_that_did():
    p, d = plan_run()
    try:
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4,5")
        d.wait_event("chain_formed 1.2 ")
        segs = plan_of(d, 1)
        first, second = segs[0], segs[2]
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4,5")
        again = plan_of(d, 1)
        check(again[0]["pid"] == first["pid"] and again[2]["pid"] == second["pid"] and again[0]["name"] == first["name"],
              "the same plan moves nothing: %s" % d.workers())
        # the plan loses its last two members: [1 2] stays where it runs, 4 and 5 are alone
        d.expect("plan 1 1 2 3", "resp 0 1,2;3")
        now = plan_of(d, 1)
        check(sorted(now) == [0] and now[0]["pid"] == first["pid"], "the segment that did not change keeps its worker: %s" % d.workers())
        for n in (4, 5):
            _, w = d.wait_up(n)
            check(w["place"] == "own" and w["inst"] == [n], "%d is alone: %s" % (n, w))
        # 3 earns an in-process verdict: all of 1 2 3 are one segment, in a worker that is formed again
        d.expect(pin_n(p, 3, "in-process"), "resp 0")
        mark = d.mark()
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        d.wait_event("chain_formed 1.0 ", since=mark)
        now = plan_of(d, 1)
        check(sorted(now) == [0] and now[0]["inst"] == [1, 2, 3], "one segment of three: %s" % d.workers())
        # a segment that moves to another place in the plan keeps its worker and takes the place's name
        d.expect("plan 1 4 1 2 3", "resp 0 4,1,2,3")
        moved = plan_of(d, 1)
        check(sorted(moved) == [0] and moved[0]["inst"] == [4, 1, 2, 3], "four in one: %s" % d.workers())
        d.expect(pin_n(p, 4, "isolated"), "resp 0")
        d.expect("plan 1 4 1 2 3", "resp 0 4;1,2,3")
        moved2 = plan_of(d, 1)
        check(sorted(moved2) == [1] and moved2[1]["inst"] == [1, 2, 3],
              "the segment of 1 2 3 is the plan's second now and its worker is named for it: %s" % d.workers())
        check(any(w["place"] == "own" and w["inst"] == [4] for w in d.workers().values()), "and 4 is alone: %s" % d.workers())
    finally:
        d.close()
        p.close()


@test
def a_plan_that_keeps_a_segment_in_another_place_renames_its_worker_and_restarts_nothing():
    p, d = plan_run()
    try:
        d.expect(pin_n(p, 1, "isolated"), "resp 0")
        d.expect("plan 1 2 3 4 5", "resp 0 2;3;4,5")
        d.wait_event("chain_formed 1.2 ")
        was = plan_of(d, 1)[2]
        check(was["inst"] == [4, 5], "4 5 is the plan's third segment: %s" % d.workers())
        d.expect("plan 1 1 2 3 4 5", "resp 0 1;2;3;4,5")
        now = plan_of(d, 1)
        check(sorted(now) == [3] and now[3]["pid"] == was["pid"] and now[3]["inst"] == [4, 5],
              "the same worker, named for the place it stands in now: %s" % d.workers())
    finally:
        d.close()
        p.close()


@test
def while_grouping_is_off_a_plan_is_answered_and_kept_and_nothing_moves():
    d = daemon()
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        before = d.workers()
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        check(d.workers() == before and not any(w["place"].startswith("chain:") for w in d.workers().values()),
              "nothing moved: %s" % d.workers())
        d.expect("plan_get 1", "resp 0 1,2,3 1:grouping-off,2:grouping-off,3:grouping-off")
        d.expect("plan_clear 1", "resp 0")
        check(d.workers() == before, "and clearing it moves nothing: %s" % d.workers())
        d.expect("plan_get 1", resp("NO_SUCH_PLAN"))
    finally:
        d.close()


@test
def a_setting_that_is_none_of_the_grouping_modes_stops_the_daemon_and_names_the_modes():
    p = Plugins()
    try:
        try:
            d = p.daemon(conf={"grouping": "maybe"})
        except Fail as e:
            check("grouping 'maybe' is not one of: off on" in str(e), "stderr names the modes: %s" % e)
        else:
            d.close()
            raise Fail("a daemon started with grouping maybe")
    finally:
        p.close()


@test
def a_plan_is_refused_for_what_chain_refuses_and_moves_nothing():
    d = daemon(conf={"grouping": "on"})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        before = d.workers()
        d.expect("plan 1 1 2 77", resp("CHAIN_UNKNOWN_INSTANCE"))
        d.expect("plan 1 1 2 1", resp("CHAIN_DUPLICATE"))
        for bad in ("plan 1", "plan x 1 2", "plan 1 1 two", "plan -1 1 2", "plan_get", "plan_get x", "plan_clear", "plan_clear x"):
            d.expect(bad, "resp -902")
        d.expect("plan_get 1", resp("NO_SUCH_PLAN"))
        d.expect("plan_clear 1", resp("NO_SUCH_PLAN"))
        check(d.workers() == before, "a refused plan moves nothing: %s" % d.workers())
        # a member of a chain, or of another chain's plan, is not the plan's to place
        d.expect("chain 9 1 2", "resp 0")
        d.expect("plan 1 2 3", resp("CHAIN_INSTANCE_BUSY"))
        d.expect("chain_clear 9", "resp 0")
        d.expect("plan 1 2 3", "resp 0 2,3")
        d.expect("plan 2 3", resp("CHAIN_INSTANCE_BUSY"))
        d.expect("chain 9 3 1", resp("CHAIN_INSTANCE_BUSY"))
        # a plan and a chain of one number are two things
        d.expect("chain 1 1", "resp 0")
        d.expect("chain_get 1", "resp 0 " + [k for k, w in d.workers().items() if w["place"] == "chain:1"][0] + " 1 1")
        d.expect("plan_get 1", "resp 0 2,3 2:cost-assumed,3:cost-assumed")
    finally:
        d.close()


@test
def plan_clear_gives_every_member_a_worker_of_its_own_and_forgets_the_plan():
    d = daemon(conf={"grouping": "on"})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
            d.expect("param_set %d gain 0.%d000" % (i, i), "resp 0")
        mark = d.mark()
        d.expect("plan 4 1 2 3", "resp 0 1,2,3")
        d.wait_event("chain_formed 4.0 ", since=mark)
        check(plan_of(d, 4)[0]["inst"] == [1, 2, 3], "one worker: %s" % d.workers())
        d.expect("plan_clear 4", "resp 0")
        for i in (1, 2, 3):
            _, w = d.wait_up(i)
            check(w["place"] == "own" and w["inst"] == [i], "plan_clear gives %d a worker of its own: %s" % (i, w))
        check(plan_of(d, 4) == {}, "the segment worker is gone: %s" % d.workers())
        gains(d, (1, 2, 3))
        d.expect("plan_get 4", resp("NO_SUCH_PLAN"))
        d.expect("plan_clear 4", resp("NO_SUCH_PLAN"))
        d.expect("chain 4 1 2", "resp 0")
    finally:
        d.close()


@test
def a_member_that_is_removed_leaves_its_segment_and_the_worker_is_told_the_order_without_it():
    log = tempfile.mktemp(prefix="plugin-hostd-fake-log.")
    d = daemon(conf={"grouping": "on"}, env={"FAKE_LOG": log})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        w = plan_of(d, 1)[0]
        d.expect("remove 2", "resp 0")
        check(plan_of(d, 1)[0]["inst"] == [1, 3], "the segment goes on without it: %s" % d.workers())
        check(sent_to(log, w["pid"])[-1] == "chain 1 1 3", "the worker is told: %s" % sent_to(log, w["pid"])[-3:])
        d.expect("remove 1", "resp 0")
        d.expect("remove 3", "resp 0")
        check(plan_of(d, 1) == {}, "no segment is left: %s" % d.workers())
        d.expect("plan_clear 1", "resp 0")
    finally:
        d.close()
        if os.path.exists(log):
            os.unlink(log)


@test
def a_segment_whose_worker_dies_is_respawned_with_its_members_in_order_and_its_plan_is_still_read_back():
    d = daemon(conf={"grouping": "on"})
    try:
        for i in (10, 11, 12):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("plan 7 10 11 12", "resp 0 10,11,12")
        d.wait_event("chain_formed 7.0 ")
        os.kill(plan_of(d, 7)[0]["pid"], signal.SIGKILL)
        _, w = d.wait_up(10)
        check(w["place"] == "chain:7.0" and w["inst"] == [10, 11, 12], "the same place, the same order: %s" % d.workers())
        d.expect("plan_get 7", "resp 0 10,11,12 10:cost-assumed,11:cost-assumed,12:cost-assumed")
    finally:
        d.close()


@test
def the_cost_a_qualification_record_holds_decides_the_segments_and_a_missing_one_is_assumed():
    """a record's p95 nanoseconds per sample at group_rate and group_quantum is a fraction of a core: 5000 ns at 48 kHz is
    24 %, and the segment adds them up against group_cost_max"""
    p, d = plan_run(conf={"group_cost_max": 50, "group_rate": 48000, "group_quantum": 128, "group_max": 3})
    try:
        for n in (1, 2, 4, 5):
            d.expect(pin_n(p, n, "in-process"), "resp 0")
        d.expect(pin_n(p, 3, "in-process"), "resp 0")
        record_for(d, "org.openmixer.fault.1", 5000)
        record_for(d, "org.openmixer.fault.2", 5000)
        record_for(d, "org.openmixer.fault.3", 5000)
        record_for(d, "org.openmixer.fault.4", 12500)        # 60 %: over the limit alone
        record_for(d, "org.openmixer.fault.5", 5000, rate=96000)   # another rate: not this plan's figure
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4;5")
        d.expect("plan_get 1", "resp 0 1,2;3;4;5 3:group-cost,4:cost-over,5:no-neighbour")
        # a record of the plugin at a lower cost, in another version, is not preferred: the larger figure stands
        record_for(d, "org.openmixer.fault.2", 1000, name="org.openmixer.fault.2@0.9-fedcba987654.default.qualification.json")
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4;5")
        # the plugin's figure lowered, in the record that held it: 24 + 24 + 0.5 % fits 50
        record_for(d, "org.openmixer.fault.3", 100, name="org.openmixer.fault.3@1.0-0123456789ab.default.qualification.json")
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        d.expect("plan_get 1", "resp 0 1,2,3 -")
    finally:
        d.close()
        p.close()


@test
def the_same_members_are_planned_into_the_same_segments_and_reasons_by_every_daemon_and_every_time():
    answers = []
    for _ in range(2):
        p, d = plan_run()
        try:
            run = []
            for _ in range(3):
                d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4,5")
                run.append(d.send("plan_get 1"))
            answers.append(run)
        finally:
            d.close()
            p.close()
    check(len(set(answers[0] + answers[1])) == 1, "six plan_get answers, one text: %s" % answers)


# ---------------------------------------------------------------- the planner reads the history, and plans again

HISTORY_CLASS = "testarch/1-2/<1.5GHz"
DAY = 86400


def plan_after_history(history, conf=None, records=None):
    """the plan of 1 2 3 4 5 under a history, all five pinned in-process, then the daemon's two answers"""
    p, d = plan_run(conf=conf, history=history)
    try:
        for n in range(1, 6):
            d.expect(pin_n(p, n, "in-process"), "resp 0")
        for plugin_id, ns, kw in records or []:
            record_for(d, plugin_id, ns, **kw)
        segments = d.send("plan 1 1 2 3 4 5")
        return segments, d.send("plan_get 1")
    finally:
        d.close()
        p.close()


@test
def a_plugin_the_history_marks_crashed_stays_alone_for_30_days_and_says_so():
    now = int(time.time())
    seg, got = plan_after_history({3: "crashes_solo=1 last_crash=%d" % (now - 29 * DAY)})
    check(seg == "resp 0 1,2;3;4,5", "the crashed one is alone: %s" % seg)
    check(got == "resp 0 1,2;3;4,5 1:cost-assumed,2:cost-assumed,3:history-crashed,4:cost-assumed,5:cost-assumed", got)
    # a crash in a group counts the same; one 31 days old does not
    seg, got = plan_after_history({2: "crashes_grouped=2 last_crash_grouped=%d" % (now - DAY),
                                   4: "crashes_solo=3 last_crash=%d" % (now - 31 * DAY)})
    check(seg == "resp 0 1;2;3,4,5", "plugin 2 alone, plugin 4 forgiven: %s" % seg)
    check(got == "resp 0 1;2;3,4,5 1:no-neighbour,2:history-crashed,3:cost-assumed,4:cost-assumed,5:cost-assumed", got)


@test
def a_plugin_the_history_marks_as_raising_xruns_stays_alone_and_says_so():
    # 20 of 40 windows in a group with an xrun, none of 40 alone: far over the 5 point margin
    seg, got = plan_after_history({3: "windows_solo=40 windows_grouped=40 xrun_windows_grouped=20"})
    check(seg == "resp 0 1,2;3;4,5", seg)
    check(got == "resp 0 1,2;3;4,5 1:cost-assumed,2:cost-assumed,3:history-xruns,4:cost-assumed,5:cost-assumed", got)
    # too few windows, or a share that is not over the margin: it joins
    seg, got = plan_after_history({3: "windows_solo=40 windows_grouped=29 xrun_windows_grouped=29",
                                   4: "windows_solo=40 windows_grouped=40 xrun_windows_solo=20 xrun_windows_grouped=22"})
    check(seg == "resp 0 1,2,3,4,5", "29 windows are too few, 22 of 40 against 20 of 40 is no margin: %s" % seg)


@test
def a_crash_is_said_before_xruns_and_the_pin_is_said_before_both():
    now = int(time.time())
    hist = {3: "crashes_solo=1 last_crash=%d windows_solo=40 windows_grouped=40 xrun_windows_grouped=40" % now,
            2: "crashes_solo=1 last_crash=%d" % now}
    p, d = plan_run(history=hist)
    try:
        for n in (1, 3, 4, 5):
            d.expect(pin_n(p, n, "in-process"), "resp 0")
        # 2 is crashed and isolated, 3 is crashed and raises xruns
        d.expect(pin_n(p, 2, "isolated"), "resp 0")
        d.expect("plan 1 1 2 3 4 5", "resp 0 1;2;3;4,5")
        d.expect("plan_get 1", "resp 0 1;2;3;4,5 1:no-neighbour,2:verdict-isolated,3:history-crashed,4:cost-assumed,5:cost-assumed")
    finally:
        d.close()
        p.close()


@test
def the_solo_cost_the_history_holds_is_the_cost_when_it_is_larger_than_the_qualified_one():
    # 48 kHz: 5000 ns/sample is 24 %, 12500 ns is 60 %
    hist = {2: "windows_solo=40 cpu_p95_solo=55.00", 4: "windows_solo=40 cpu_p95_solo=10.00"}
    conf = {"group_cost_max": 50, "group_rate": 48000, "group_quantum": 128}
    recs = [("org.openmixer.fault.2", 5000, {}), ("org.openmixer.fault.4", 12500, {})]
    seg, got = plan_after_history(hist, conf=conf, records=recs)
    # 2 costs 55 % (history over 24 %): over the limit alone; 4 costs 60 % (the record over 10 %): over it too
    check(seg == "resp 0 1;2;3;4;5", seg)
    check(got == "resp 0 1;2;3;4;5 1:no-neighbour,2:cost-over,3:no-neighbour,4:cost-over,5:no-neighbour", got)
    # a plugin with no record: the larger of nothing and 55 percent is 55 percent, which the segment adds up
    seg, got = plan_after_history({2: "windows_solo=40 cpu_p95_solo=55.00"}, conf={"group_cost_max": 60})
    check(seg == "resp 0 1,2;3,4,5", "1 (unknown) and 2 (55 percent) fit 60; 3 would add the median of them again: %s" % seg)
    check(got == "resp 0 1,2;3,4,5 1:cost-assumed,3:group-cost,4:cost-assumed,5:cost-assumed", got)
    # a plugin that never ran alone has no solo cost, whatever cpu_p95_solo says
    seg, got = plan_after_history({2: "windows_solo=0 windows_grouped=40 cpu_p95_solo=55.00"}, conf={"group_cost_max": 60})
    check(seg == "resp 0 1,2,3,4,5", seg)


@test
def a_history_that_cannot_be_read_or_is_off_plans_as_without_one_and_says_so():
    now = int(time.time())
    line = "crashes_solo=1 last_crash=%d" % now
    want = "resp 0 1,2,3,4,5 " + ",".join("%d:history-unavailable" % n for n in range(1, 6))
    # a file of another version: blocked, so the crash in it is not read
    p, d = plan_run(history="# plugin-hostd history/2\nhistory x y z %s\n" % line)
    try:
        for n in range(1, 6):
            d.expect(pin_n(p, n, "in-process"), "resp 0")
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2,3,4,5")
        d.expect("plan_get 1", want)
    finally:
        d.close()
        p.close()
    # window 0: the history is off, and so is the crash in its file
    p, d = plan_run(history={3: line}, conf={"history_window_s": 0})
    try:
        for n in range(1, 6):
            d.expect(pin_n(p, n, "in-process"), "resp 0")
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2,3,4,5")
        d.expect("plan_get 1", want)
        # a member that has a harder reason says that one
        d.expect(pin_n(p, 3, "isolated"), "resp 0")
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3;4,5")
        d.expect("plan_get 1", "resp 0 1,2;3;4,5 1:history-unavailable,2:history-unavailable,3:verdict-isolated,"
                 "4:history-unavailable,5:history-unavailable")
    finally:
        d.close()
        p.close()


def plan_of_five(conf=None):
    """a fake-host daemon with grouping on and the members 1 to 5 planned"""
    c = {"grouping": "on"}
    c.update(conf or {})
    d = daemon(conf=c)
    for i in range(1, 6):
        d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
    return d


def places(d):
    """{place: [members]} of the workers, by place"""
    return {w["place"]: w["inst"] for w in d.workers().values()}


@test
def a_member_that_is_quarantined_leaves_its_plan_alone_and_the_segments_that_did_not_change_keep_their_workers():
    d = plan_of_five({"group_max": 2})
    try:
        d.expect("plan 1 1 2 3 4 5", "resp 0 1,2;3,4;5")
        d.wait_event("chain_formed 1.1 ")
        first = plan_of(d, 1)[0]["pid"]
        mark = d.mark()
        d.expect("param_set 4 crash 1", "resp 0")
        d.wait_event("instance_quarantined 4 ", since=mark)
        wait_for(lambda: d.send("plan_get 1").startswith("resp 0 1,2;3;4;5 "), "the plan again: %s" % d.send("plan_get 1"))
        d.expect("plan_get 1", "resp 0 1,2;3;4;5 1:cost-assumed,2:cost-assumed,3:group-full,4:history-crashed,5:no-neighbour")
        d.wait_event("plan_reason 1 1:cost-assumed,2:cost-assumed,3:group-full,4:history-crashed,5:no-neighbour", since=mark)
        for i in (1, 2, 3, 4, 5):
            d.wait_up(i)
        check(places(d)["chain:1.0"] == [1, 2], "the first segment runs: %s" % d.workers())
        check(plan_of(d, 1)[0]["pid"] == first, "and it is the worker it was: no restart")
        check(not any(w["place"].startswith("chain:1.") and w["place"] != "chain:1.0" for w in d.workers().values()),
              "the dissolved segment left no worker: %s" % d.workers())
        check(sorted(w["inst"][0] for w in d.workers().values() if w["place"] == "own") == [3, 4, 5], "three alone: %s" % d.workers())
        # cleared, the daemon plans it again and the member goes back in its place: the history holds nothing against it
        mark = d.mark()
        d.expect("quarantine_clear 4", "resp 0")
        wait_for(lambda: d.send("plan_get 1").startswith("resp 0 1,2;3,4;5 "), "the plan once more: %s" % d.send("plan_get 1"))
        d.wait_event("chain_formed 1.1 ", since=mark)
        check(places(d)["chain:1.1"] == [3, 4] and plan_of(d, 1)[0]["pid"] == first, "3 and 4 share again: %s" % d.workers())
        # quarantined again, and all quarantines cleared at once: the same
        mark = d.mark()
        d.expect("param_set 4 crash 1", "resp 0")
        d.wait_event("instance_quarantined 4 ", since=mark)
        wait_for(lambda: "4:history-crashed" in d.send("plan_get 1"), "the plan again: %s" % d.send("plan_get 1"))
        d.expect("quarantine_clear all", "resp 0")
        wait_for(lambda: d.send("plan_get 1").startswith("resp 0 1,2;3,4;5 "), "the plan once more: %s" % d.send("plan_get 1"))
        check(plan_of(d, 1)[0]["pid"] == first, "and the first segment never restarted: %s" % d.workers())
    finally:
        d.close()


def kill_chain(d, plan, k):
    """kill the worker of segment k of a plan from outside: it names no culprit, so the group is split"""
    os.kill(plan_of(d, plan)[k]["pid"], signal.SIGKILL)
    wait_for(lambda: len(plan_of(d, plan)) == 0, "the group split")
    t0 = time.monotonic()
    for i in (1, 2, 3):
        d.wait_up(i)
    return t0


@test
def a_group_split_by_a_death_with_no_culprit_is_gathered_again_after_history_regroup_s_of_steady_running():
    d = daemon(conf={"grouping": "on", "history_regroup_s": 3})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        d.wait_event("chain_formed 1.0 ")
        mark = d.mark()
        t0 = kill_chain(d, 1, 0)
        time.sleep(1.2)
        check(not plan_of(d, 1) and not any(e.startswith("chain_formed") for e in d.events[mark:]),
              "not before its time: %s %s" % (d.workers(), d.events[mark:]))
        d.wait_event("chain_formed 1.0 ", since=mark)
        late = time.monotonic() - t0
        check(2.0 < late < 8.0, "about 3 s of steady running after the death: %.1f s" % late)
        check(places(d) == {"chain:1.0": [1, 2, 3]}, "the group runs as one again: %s" % d.workers())
        d.expect("plan_get 1", "resp 0 1,2,3 1:cost-assumed,2:cost-assumed,3:cost-assumed")
    finally:
        d.close()


@test
def another_death_of_a_member_puts_the_regroup_off_by_another_history_regroup_s():
    d = daemon(conf={"grouping": "on", "history_regroup_s": 3, "group_max": 2})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("plan 1 1 2 3", "resp 0 1,2;3")
        d.wait_event("chain_formed 1.0 ")
        mark = d.mark()
        os.kill(plan_of(d, 1)[0]["pid"], signal.SIGKILL)
        t0 = time.monotonic()
        wait_for(lambda: not plan_of(d, 1), "the group split")
        time.sleep(1.8)
        # member 3 is alone and not of the split group: its death is steady running broken
        _, w3 = d.holder(3)
        os.kill(w3["pid"], signal.SIGKILL)
        t1 = time.monotonic()
        d.wait_up(3)
        time.sleep(max(0, 3.6 - (time.monotonic() - t0)))
        check(not plan_of(d, 1), "3 s after the first death, 1.8 s after the second: still apart: %s" % d.workers())
        d.wait_event("chain_formed 1.0 ", since=mark)
        late = time.monotonic() - t1
        check(late > 2.0, "3 s after the second death, not 3 s after the first: %.1f s" % late)
        check(places(d) == {"chain:1.0": [1, 2], "own": [3]}, "gathered: %s" % d.workers())
    finally:
        d.close()


@test
def history_regroup_s_zero_leaves_a_split_group_apart_until_the_controller_plans_it_again():
    d = daemon(conf={"grouping": "on", "history_regroup_s": 0})
    try:
        for i in (1, 2, 3):
            d.expect("add clap:fake#m%d %d" % (i, i), "resp %d" % i)
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        d.wait_event("chain_formed 1.0 ")
        kill_chain(d, 1, 0)
        time.sleep(4.5)
        check(not plan_of(d, 1) and [w["place"] for w in d.workers().values()] == ["own", "own", "own"], "apart after longer than the timer of the other tests: %s" % d.workers())
        mark = d.mark()
        d.expect("plan 1 1 2 3", "resp 0 1,2,3")
        d.wait_event("chain_formed 1.0 ", since=mark)
        check(places(d) == {"chain:1.0": [1, 2, 3]}, "and a plan call gathers it, though the segment did not change: %s" % d.workers())
    finally:
        d.close()


@test
def a_clap_member_and_an_lv2_member_of_the_adapter_row_form_one_chain():
    """clap and lv2-clap are two rows of one program, both running chains in one client; lv2 (mod-host) and clap are two
    programs and stay refused. An LV2 member joining a running chain forms it again: its bundle is not in the world"""
    d, programs, log = lv2_run(lv2_worker="omx-clap-host")
    try:
        d.expect("add clap:fake#a 1", "resp 1")
        d.expect("add lv2:urn:test:b 2", "resp 2")
        mark = d.mark()
        d.expect("chain 1 1 2", "resp 0")
        d.wait_event("chain_formed 1 ", since=mark)
        k, w = list(chain_of(d, 1).items())[0]
        check(w["inst"] == [1, 2] and w["fmt"] == "lv2-clap" and len(d.workers()) == 1,
              "one worker, of the row that narrows its world: %s" % d.workers())
        check(programs.of(w["pid"])[0] == "omx-clap-host", "omx-clap-host runs it: %s" % (programs.of(w["pid"]),))
        got = sent_to(log, w["pid"])
        check(adds_of(log, w["pid"]) == ["add clap:fake#a 1", "add lv2:urn:test:b 2"] and "chain 1 1 2" in got,
              "each member's own add, then the order: %s" % got)
        d.expect("chain_get 1", "resp 0 %s 1,2 1,2" % k)
        # a CLAP member joins in place
        d.expect("add clap:fake#c 3", "resp 3")
        mark = d.mark()
        d.expect("chain 1 3 1 2", "resp 0")
        d.wait_event("chain_formed 1 %s 3,1,2" % k, since=mark)
        check(chain_of(d, 1)[k]["pid"] == w["pid"], "the CLAP joiner restarts no one: %s" % d.workers())
        # an LV2 member forms the chain again, in a world with its bundle
        d.expect("add lv2:urn:test:d 4", "resp 4")
        mark = d.mark()
        d.expect("chain 1 3 4 1 2", "resp 0")
        d.wait_event("chain_formed 1 ", since=mark)
        k2, w2 = list(chain_of(d, 1).items())[0]
        check(k2 != k and w2["inst"] == [3, 4, 1, 2], "an LV2 joiner forms the chain again: %s" % d.workers())
        # two programs are still two workers
        d.expect("lv2_worker_set urn:test:e mod-host", "resp 0")
        d.expect("add lv2:urn:test:e 5", "resp 5")
        d.expect("add clap:fake#f 6", "resp 6")
        d.expect("chain 2 6 5", resp("CHAIN_MIXED_FORMAT"))
        d.expect("chain 2 5 6", resp("CHAIN_MIXED_FORMAT"))
    finally:
        d.close()
        programs.close()


@test
def under_require_pins_a_chain_of_a_clap_and_an_lv2_member_sees_the_lv2_members_bundle_only():
    programs = Programs()
    p = Plugins()
    d = p.daemon(conf=programs.conf(lv2_worker="omx-clap-host"))
    try:
        d.expect(p.lv2_pin(), "resp 0")
        d.expect(p.clap_pin(), "resp 0")
        d.expect("add %s 1" % p.clap_uri, "resp 1")
        d.expect("add %s 2" % LV2_URI, "resp 2")
        mark = d.mark()
        d.expect("chain 3 1 2", "resp 0")
        d.wait_event("chain_formed 3 ", since=mark)
        _, w = list(chain_of(d, 3).items())[0]
        check(w["inst"] == [1, 2] and w["fmt"] == "lv2-clap", "one adapter-row worker: %s" % d.workers())
        program, world = programs.of(w["pid"])
        check(program == "omx-clap-host" and world != p.lv2_dir and os.listdir(world) == ["pinned.lv2"],
              "the world is the LV2 member's bundle, the CLAP member found by its path: %s %s" % (program, world))
    finally:
        d.close()
        p.close()
        programs.close()



# ---------------------------------------------------------------- descriptors

def Scan():
    """tests/scan_fixture.py's files and scanner, in front of the daemon under test"""
    return scan_fixture.Scan(daemon)


def config_meaning(key):
    return [c for c in harness.DECLARED["config"] if c["key"] == key][0]


def answered(d, uri, path):
    return d.send("descriptor_get %s" % uri) == 'resp 0 "%s"' % path


def panel_answered(d, uri, path):
    return d.send("panel_get %s" % uri) == 'resp 0 "%s"' % path


def same_bytes(a, b):
    with open(a, "rb") as f, open(b, "rb") as g:
        return f.read() == g.read()


@test
def an_add_writes_the_descriptor_by_id_version_and_hash_and_descriptor_get_answers_from_it():
    s = Scan()
    d = s.daemon()
    try:
        d.expect("descriptor_get %s" % s.clap_uri, resp("DESCRIPTOR_ABSENT"))
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        name = s.clap_name()
        wait_for(lambda: answered(d, s.clap_uri, name), "descriptor_get answers %s" % name)
        check(same_bytes(name, os.path.join(FIELDS, "clap-controls.json")),
              "the file is what describe writes for the plugin")
        wait_for(lambda: panel_answered(d, s.clap_uri, panel_name(name)), "panel_get answers %s" % panel_name(name))
        check(sorted(os.listdir(os.path.dirname(name))) == sorted([os.path.basename(name), "panels"]),
              "nothing else is left beside it but the panels: %s" % os.listdir(os.path.dirname(name)))
        check(os.listdir(os.path.dirname(panel_name(name))) == [os.path.basename(name)],
              "the panels hold its panel alone: %s" % os.listdir(os.path.dirname(panel_name(name))))
        for path in (s.descriptors, s.qualification):
            check(os.stat(path).st_mode & 0o777 == 0o700, "%s is made 0700" % path)
        # written once: a second instance of the same files reads the file and runs no scan
        d.expect("add %s 1" % s.clap_uri, "resp 1")
        d.expect("add lv2:%s 2" % LV2_COMPRESSOR, "resp 2")
        wait_for(lambda: answered(d, "lv2:" + LV2_COMPRESSOR, s.lv2_name()), "the LV2 descriptor %s" % s.lv2_name())
        check(same_bytes(s.lv2_name(), os.path.join(FIELDS, "lv2-compressor.json")), "the LV2 file is describe's")
        check(s.scans() == [s.clap_uri, "lv2:" + LV2_COMPRESSOR], "one scan per plugin: %s" % s.scans())
        # the name hashes the binary alone: a changed data file of the bundle keeps it
        write(os.path.join(s.bundle, "pinned.ttl"), b"lv2:port [ lv2:index 1 ] .")
        check(answered(d, "lv2:" + LV2_COMPRESSOR, s.lv2_name()), "a changed .ttl keeps the LV2 binary's descriptor")
        # a changed binary is no longer described: its next add scans again under a new name; the old file stays
        write(s.clap, b"another clap build")
        d.expect("descriptor_get %s" % s.clap_uri, resp("DESCRIPTOR_ABSENT"))
        d.expect("add %s 3" % s.clap_uri, "resp 3")
        wait_for(lambda: answered(d, s.clap_uri, s.clap_name()), "the new binary's descriptor")
        check(s.clap_name() != name and os.path.exists(name), "a new file, and the old one kept")
        check(len(s.scans()) == 3, "the changed binary was scanned: %s" % s.scans())
    finally:
        d.close()
        s.close()


@test
def a_scan_that_runs_answers_pending_and_one_that_fails_answers_its_code_while_the_add_stands():
    s = Scan()
    hold = os.path.join(s.dir, "go")
    d = s.daemon(env={"SCAN_HOLD": hold})
    try:
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        wait_for(lambda: s.scans(), "the scan starts")
        d.expect("descriptor_get %s" % s.clap_uri, resp("DESCRIPTOR_PENDING"))
        d.expect("add %s 1" % s.clap_uri, "resp 1")
        write(hold, b"")
        wait_for(lambda: answered(d, s.clap_uri, s.clap_name()), "the held scan ends")
        check(len(s.scans()) == 1, "an add while the scan runs starts no second one: %s" % s.scans())
    finally:
        d.close()
    d = s.daemon(conf={"descriptor_dir": os.path.join(s.dir, "other")}, env={"SCAN_EXIT": "2"})
    try:
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        wait_for(lambda: d.send("descriptor_get %s" % s.clap_uri) == resp("DESCRIPTOR_SCAN_FAILED"),
                 "the failed scan's code")
        check(d.workers() and list(d.workers().values())[0]["inst"] == [0], "the instance runs")
        check("the scan wrote no descriptor" in d.log() and "resp %d" % harness.CODE["DESCRIPTOR_SCAN_FAILED"] in d.log(),
              "stderr says so with the code: %s" % d.log()[-400:])
        check(not [f for r, _, fs in os.walk(os.path.join(s.dir, "other")) for f in fs], "no file is left behind")
    finally:
        d.close()
    d = s.daemon(conf={"descriptor_dir": os.path.join(s.dir, "third"), "probe": os.path.join(s.dir, "absent")})
    try:
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        d.expect("descriptor_get %s" % s.clap_uri, resp("DESCRIPTOR_SCAN_FAILED"))
        d.expect("descriptor_get clap:fake#x", resp("DESCRIPTOR_ABSENT"))
        d.expect("descriptor_get", "resp -902")
    finally:
        d.close()
        s.close()


@test
def the_scan_files_the_panel_under_the_descriptors_name_and_panel_get_answers_from_it():
    s = Scan()
    hold = os.path.join(s.dir, "go")
    d = s.daemon(env={"SCAN_HOLD": hold})
    try:
        d.expect("panel_get %s" % s.clap_uri, resp("DESCRIPTOR_ABSENT"))
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        wait_for(lambda: s.scans(), "the scan starts")
        d.expect("panel_get %s" % s.clap_uri, resp("DESCRIPTOR_PENDING"))
        write(hold, b"")
        name = s.clap_name()
        wait_for(lambda: panel_answered(d, s.clap_uri, panel_name(name)), "panel_get answers %s" % panel_name(name))
        doc = json.load(open(panel_name(name)))
        check(doc["plugin"] == {"format": "clap", "id": CLAP_ID}, "the panel names its plugin: %s" % doc["plugin"])
        scan = json.load(open(os.path.join(FIELDS, "clap-panel-scan.json")))
        check(doc["panel"] == scan["files"][0]["plugins"][0]["panel"], "the panel is the scan's panel object")
        check(doc["panel"]["roles"] == {"refused": "too-many", "count": 5000, "max": 4096},
              "a table the scan refused is refused: %s" % doc["panel"]["roles"])
        check(s.scans(".panel") == [s.clap_uri], "one panel stage, after the descriptor: %s" % s.scans(".panel"))
        d.expect("add lv2:%s 1" % LV2_COMPRESSOR, "resp 1")
        wait_for(lambda: panel_answered(d, "lv2:" + LV2_COMPRESSOR, panel_name(s.lv2_name())), "the LV2 panel")
        check(json.load(open(panel_name(s.lv2_name()))) == {"plugin": {"format": "lv2", "id": LV2_COMPRESSOR},
                                                            "panel": None}, "an LV2 plugin's panel is null")
        d.expect("panel_get", "resp -902")
        d.expect("panel_get clap:fake#x", resp("DESCRIPTOR_ABSENT"))
        # a descriptor in place with no panel (filed before the panel stage was): absent until an add scans the panel
        os.unlink(panel_name(name))
        d.expect("panel_get %s" % s.clap_uri, resp("DESCRIPTOR_ABSENT"))
        d.expect("add %s 2" % s.clap_uri, "resp 2")
        wait_for(lambda: panel_answered(d, s.clap_uri, panel_name(name)), "the panel scanned again")
        check(len(s.scans()) == 2 and len(s.scans(".panel")) == 3,
              "the descriptor is not scanned again, its panel is: %s %s" % (s.scans(), s.scans(".panel")))
    finally:
        d.close()
    d = s.daemon(conf={"descriptor_dir": os.path.join(s.dir, "other")}, env={"PANEL_EXIT": "2"})
    try:
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        other = descriptor_name(os.path.join(s.dir, "other"), CLAP_ID, "1", s.clap)
        wait_for(lambda: d.send("panel_get %s" % s.clap_uri) == resp("DESCRIPTOR_SCAN_FAILED"), "the failed panel's code")
        check(answered(d, s.clap_uri, other), "the descriptor stands")
        check("the scan wrote no panel" in d.log(), "stderr says so: %s" % d.log()[-400:])
        check(os.listdir(os.path.join(s.dir, "other", "panels")) == [], "no file is left behind")
    finally:
        d.close()
        s.close()


def start_refused(conf, env=None):
    """the daemon run with a settings file that must stop it before it is ready: (exit status, output)"""
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-refused.")
    path = os.path.join(tmp, "plugin-hostd.conf")
    settings = {"state_root": tmp, "require_pins": 0, "pins_dir": "", "mod_host": FAKE, "clap_host": FAKE}
    settings.update(conf)
    with open(path, "w") as f:
        for k, v in settings.items():
            if v is not None:
                f.write("%s %s\n" % (k, v))
    e = dict(os.environ)
    e.update(env or {})
    cmd, fb = harness.port_pair()
    try:
        p = subprocess.run([EXE, "-n", "-p", str(cmd), "-f", str(fb), "-c", path], capture_output=True, text=True,
                           timeout=10, env=e)
        return p.returncode, p.stdout + p.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def a_read_only_directory_stops_the_daemon_with_its_code_and_names_the_key():
    if os.geteuid() == 0:
        print("     skip: root writes a 0500 directory")
        return
    s = Scan()
    try:
        for key, other in (("descriptor_dir", "qualification_dir"), ("qualification_dir", "descriptor_dir")):
            ro = os.path.join(s.dir, "ro-" + key)
            os.makedirs(ro)
            os.chmod(ro, 0o500)
            for path in (ro, os.path.join(ro, "below")):
                rc, out = start_refused({key: path, other: os.path.join(s.dir, "fine")})
                check(rc != 0 and harness.READY_LINE not in out, "%s %s: the daemon does not start: %d %r" % (key, path, rc, out))
                check("%s %s" % (key, path) in out and "resp %d" % harness.CODE["DIR_NOT_WRITABLE"] in out,
                      "stderr names the key, the path and the code: %r" % out)
            os.chmod(ro, 0o700)
        # a path that is a file is no directory either
        write(os.path.join(s.dir, "plain"), b"")
        rc, out = start_refused({"descriptor_dir": os.path.join(s.dir, "plain"),
                                 "qualification_dir": os.path.join(s.dir, "fine")})
        check(rc != 0 and "resp %d" % harness.CODE["DIR_NOT_WRITABLE"] in out, "a file in its place: %r" % out)
    finally:
        s.close()


@test
def a_directory_that_turns_read_only_makes_the_scan_answer_its_code():
    if os.geteuid() == 0:
        print("     skip: root writes a 0500 directory")
        return
    s = Scan()
    d = s.daemon()
    try:
        os.chmod(s.descriptors, 0o500)
        d.expect("add %s 0" % s.clap_uri, "resp 0")
        d.expect("descriptor_get %s" % s.clap_uri, resp("DIR_NOT_WRITABLE"))
        check(s.scans() == [], "no scan ran: %s" % s.scans())
        os.chmod(s.descriptors, 0o700)
        d.expect("add %s 1" % s.clap_uri, "resp 1")
        wait_for(lambda: answered(d, s.clap_uri, s.clap_name()), "the next add scans again")
    finally:
        os.chmod(s.descriptors, 0o700)
        d.close()
        s.close()


@test
def a_missing_key_falls_to_the_documented_default_and_the_key_holds_over_the_variable():
    s = Scan()
    try:
        # the defaults as protocol.json documents them, the same text the man page and the README carry
        declared = {}
        for key in ("descriptor_dir", "qualification_dir"):
            meaning = config_meaning(key)["meaning"]
            check(config_meaning(key)["default"] == "", "%s's declared default is empty, resolved at start" % key)
            xdg = meaning.split("empty is $XDG_STATE_HOME/", 1)[1].split(",", 1)[0]
            home = meaning.split("else $HOME/", 1)[1].split(";", 1)[0]
            declared[key] = (xdg, home)
        cases = [
            ({"XDG_STATE_HOME": os.path.join(s.dir, "xdg"), "HOME": os.path.join(s.dir, "home")}, 0),
            ({"XDG_STATE_HOME": "", "HOME": os.path.join(s.dir, "home")}, 1),
        ]
        for env, which in cases:
            if which == 1 and os.geteuid() == 0:
                # a root daemon without $XDG_STATE_HOME keeps its state in /var/lib, which a test must not write;
                # the $HOME branch is exercised by the non-root runs
                print("skip: the $HOME default, the euid is 0 and the daemon then picks /var/lib")
                continue
            env = dict(env, OMX_DESCRIPTOR_DIR="", OMX_QUALIFICATION_DIR="")
            base = env["XDG_STATE_HOME"] or env["HOME"]
            d = s.daemon(conf={"descriptor_dir": None, "qualification_dir": None}, env=env)
            try:
                want = {k: os.path.join(base, v[which]) for k, v in declared.items()}
                check(os.path.isdir(want["qualification_dir"]), "qualification_dir is made at %s" % want["qualification_dir"])
                d.expect("add %s 0" % s.clap_uri, "resp 0")
                name = s.clap_name(want["descriptor_dir"])
                wait_for(lambda: answered(d, s.clap_uri, name), "the descriptor at the default %s" % name)
            finally:
                d.close()
        # the variable stands in for the default; the key in the settings file holds over it
        env = {"OMX_DESCRIPTOR_DIR": os.path.join(s.dir, "by-env"), "OMX_QUALIFICATION_DIR": os.path.join(s.dir, "q-env")}
        d = s.daemon(conf={"descriptor_dir": None, "qualification_dir": None}, env=env)
        try:
            d.expect("add %s 0" % s.clap_uri, "resp 0")
            wait_for(lambda: answered(d, s.clap_uri, s.clap_name(env["OMX_DESCRIPTOR_DIR"])), "the variable's directory")
            check(os.path.isdir(env["OMX_QUALIFICATION_DIR"]), "the qualification variable's directory")
        finally:
            d.close()
        d = s.daemon(conf={"descriptor_dir": os.path.join(s.dir, "by-key")}, env=env)
        try:
            d.expect("add %s 0" % s.clap_uri, "resp 0")
            wait_for(lambda: answered(d, s.clap_uri, s.clap_name(os.path.join(s.dir, "by-key"))), "the key's directory")
        finally:
            d.close()
    finally:
        s.close()


# ---------------------------------------------------------------- the running history (src/history.c)

HISTORY_CLASS = "testarch/1-2/<1.5GHz"


def history_conf(p, **kw):
    """a daemon that keeps its history in the test's own file, under a class of the test's own, a window of one second"""
    c = {"pin_mode": "strict", "history_file": os.path.join(p.dir, "history"), "history_window_s": 1,
         "history_save_s": 1, "host_class": HISTORY_CLASS}
    c.update(kw)
    return c


def pin_in_process(p, d, uri=None, clap=None):
    """the pin of the CLAP (or of another) with the verdict that lets it share a worker"""
    d.expect("pin_set %s verdict=in-process" % pin_line(p, uri=uri, clap=clap), "resp 0")


def history_of(d, uri):
    """history_get's one word as a dict, or the word itself ('-', 'unavailable')"""
    r = d.send("history_get %s" % uri)
    check(r.startswith("resp 0 "), "history_get answers resp 0: %r" % r)
    word = r[len("resp 0 "):]
    if word in ("-", "unavailable"):
        return word
    return dict(kv.split("=", 1) for kv in word.split(","))


def history_lines(path):
    """(uri, digest, class, {key: value}) of every history line of the file"""
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for l in f:
            w = l.split()
            if w and w[0] == "history":
                out.append((w[1], w[2], w[3], dict(kv.split("=", 1) for kv in w[4:])))
    return out


@test
def a_pinned_plugin_leaves_a_record_of_its_windows_alone_and_in_a_group():
    t0 = int(time.time())
    p = Plugins()
    d = p.daemon(conf=history_conf(p))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        h = wait_for(lambda: (lambda r: r if isinstance(r, dict) and int(r["windows_solo"]) >= 1 else None)(history_of(d, p.clap_uri)),
                     "a window of the plugin alone")
        check(h["digest"] == sha(p.clap), "the record is of the binary its pin holds: %s" % h["digest"])
        check(h["class"] == HISTORY_CLASS, "under the class the setting names: %s" % h["class"])
        check(h["windows_grouped"] == "0" and h["crashed"] == "0" and h["raises_xruns"] == "0", "%s" % h)
        check(0 < float(h["pss_mb_solo"]) < 100, "the worker's Pss was read, in MiB: %s" % h["pss_mb_solo"])
        check(0 <= float(h["cpu_p95_solo"]) <= float(h["cpu_max_solo"]), "cpu p95 %s, max %s" % (h["cpu_p95_solo"], h["cpu_max_solo"]))
        check(t0 <= int(h["first"]) <= int(h["last"]), "first %s, last %s, since %d" % (h["first"], h["last"], t0))
        check(history_of(d, "clap:/nowhere.clap#x") == "-", "a plugin with no pin has no history")
        # the file, written within history_save_s of a change
        lines = wait_for(lambda: history_lines(os.path.join(p.dir, "history")) or None, "the history file")
        check(len(lines) == 1 and lines[0][0] == p.clap_uri and lines[0][1] == sha(p.clap) and lines[0][2] == HISTORY_CLASS,
              "the file holds the record under its key: %s" % lines)
        st = os.stat(os.path.join(p.dir, "history"))
        check(st.st_mode & 0o777 == 0o600, "mode %o" % (st.st_mode & 0o777))
        # a group: the same plugin twice in a pool; the windows of the group are counted apart
        d.expect("remove 0", "resp 0")
        solo = int(history_of(d, p.clap_uri)["windows_solo"])
        d.expect("add %s 1 pool:g" % p.clap_uri, "resp 1")
        d.expect("add %s 2 pool:g" % p.clap_uri, "resp 2")
        h = wait_for(lambda: (lambda r: r if int(r["windows_grouped"]) >= 1 else None)(history_of(d, p.clap_uri)), "a window of the group")
        check(int(h["windows_solo"]) == solo, "the group's windows did not move the solo ones: %d then %s" % (solo, h["windows_solo"]))
    finally:
        d.close()
        p.close()


@test
def crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them():
    p = Plugins()
    other, other_uri = other_clap(p)
    d = p.daemon(conf=history_conf(p, history_window_s=3600))
    try:
        pin_in_process(p, d)
        pin_in_process(p, d, other_uri, other)
        d.expect("add %s 0 pool:g" % p.clap_uri, "resp 0")
        d.expect("add %s 1 pool:g" % other_uri, "resp 1")
        a, b = history_of(d, p.clap_uri), history_of(d, other_uri)
        check(a == "-" and b == "-", "nothing has happened yet, so there is no record: %s %s" % (a, b))
        mark = d.mark()
        # the second dies just after a reply, in a pool of two: it is the culprit, the first only went down with it
        d.expect("param_set 1 crash 1", "resp 0")
        d.wait_event("instance_quarantined 1 ", since=mark)
        d.wait_up(0)
        a, b = history_of(d, p.clap_uri), history_of(d, other_uri)
        check((a["crashes_grouped"], a["restarts_grouped"], a["quarantines"], a["crashes_solo"]) == ("0", "1", "0", "0"),
              "the member that was not the culprit went down with the group: %s" % a)
        check((b["crashes_grouped"], b["restarts_grouped"], b["quarantines"], b["crashes_solo"]) == ("1", "0", "1", "0"),
              "the culprit crashed in a group and was quarantined: %s" % b)
        check(int(b["last_crash_grouped"]) > 1600000000 and b["last_crash"] == "0", "when: %s" % b)
        check(b["crashed"] == "1" and a["crashed"] == "0", "only the culprit is marked crashed: %s %s" % (a["crashed"], b["crashed"]))
        # the culprit is alone now: its next crash is a crash alone
        mark = d.mark()
        d.wait_up(1)
        d.expect("param_set 1 crash 1", "resp 0")
        d.wait_event("instance_restored 1 ", since=mark)
        b = history_of(d, other_uri)
        check((b["crashes_solo"], b["crashes_grouped"], b["restarts_grouped"]) == ("1", "1", "0"), "a crash alone: %s" % b)
        a = history_of(d, p.clap_uri)
        check(a["restarts_grouped"] == "1" and a["crashes_solo"] == "0", "the other plugin is not touched by it: %s" % a)
    finally:
        d.close()
        p.close()


@test
def a_worker_that_dies_after_half_a_window_still_counts_it_and_before_half_does_not():
    p = Plugins()
    d = p.daemon(conf=history_conf(p, history_window_s=4, history_save_s=3600))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        mark = d.mark()
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_restored 0 ", since=mark)
        h = history_of(d, p.clap_uri)
        check(h["crashes_solo"] == "1" and h["windows_solo"] == "0", "up for less than half a window: not counted: %s" % h)
        # half of four seconds is two: the new worker is up, and a window of it is open; let it pass half
        time.sleep(2.6)
        mark = d.mark()
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_restored 0 ", since=mark)
        h = history_of(d, p.clap_uri)
        check(h["crashes_solo"] == "2" and h["windows_solo"] == "1", "up for more than half a window: counted: %s" % h)
    finally:
        d.close()
        p.close()


@test
def history_clear_deletes_one_plugin_or_all_of_it_and_the_file_follows_at_once():
    p = Plugins()
    other, other_uri = other_clap(p)
    d = p.daemon(conf=history_conf(p, history_save_s=3600))
    path = os.path.join(p.dir, "history")
    try:
        for uri, clap in ((p.clap_uri, None), (other_uri, other)):
            pin_in_process(p, d, uri if clap else None, clap)
            d.expect("add %s %d own" % (uri, 0 if not clap else 1), "resp %d" % (0 if not clap else 1))
        wait_for(lambda: all(isinstance(history_of(d, u), dict) for u in (p.clap_uri, other_uri)), "both have a window")
        d.expect("history_clear %s" % p.clap_uri, "resp 0")
        check(history_of(d, p.clap_uri) == "-", "the plugin has no history")
        check(isinstance(history_of(d, other_uri), dict), "and the other one is untouched")
        check([l[0] for l in history_lines(path)] == [other_uri], "the file lost the line at once: %s" % history_lines(path))
        d.expect("history_clear all", "resp 0")
        check(history_lines(path) == [], "all of it: %s" % history_lines(path))
        d.expect("history_clear", "resp -902")
        d.expect("history_clear a b", "resp -902")
        d.expect("history_get", "resp -902")
    finally:
        d.close()
        p.close()


@test
def a_history_file_of_another_version_is_neither_read_nor_overwritten_and_the_daemon_runs_on():
    p = Plugins()
    path = os.path.join(p.dir, "history")
    body = "# plugin-hostd history/2\nhistory %s %s %s windows_solo=7\n" % (p.clap_uri, sha(p.clap), HISTORY_CLASS)
    write(path, body.encode())
    d = p.daemon(conf=history_conf(p))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        check(history_of(d, p.clap_uri) == "unavailable", "the history is unavailable")
        d.expect("history_clear all", "resp -902")
        check("has a version this daemon does not know" in d.log(), "stderr says why: %s" % d.log())
        check(d.holder(0)[1]["state"] == "up", "the plugin runs")
    finally:
        d.close()
    with open(path) as f:
        check(f.read() == body, "the file is as it was")
    p.close()


@test
def with_history_window_s_zero_nothing_is_kept_and_a_plugin_runs_as_before():
    p = Plugins()
    d = p.daemon(conf=history_conf(p, history_window_s=0))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        check(history_of(d, p.clap_uri) == "unavailable", "no history")
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_up(0)
        check(not os.path.exists(os.path.join(p.dir, "history")), "no file")
    finally:
        d.close()
        p.close()


@test
def the_history_is_written_when_the_daemon_quits_and_found_again_by_the_next_one():
    p = Plugins()
    path = os.path.join(p.dir, "history")
    d = p.daemon(conf=history_conf(p, history_save_s=3600))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        wait_for(lambda: isinstance(history_of(d, p.clap_uri), dict) or None, "a window")
        check(not os.path.exists(path), "an hour between saves: nothing written yet")
        d.expect("quit", "resp 0")
        wait_for(lambda: d.proc.poll() is not None, "the daemon to exit")
    finally:
        d.close()
    lines = history_lines(path)
    check(len(lines) == 1 and int(lines[0][3]["windows_solo"]) >= 1, "the quit wrote the record: %s" % lines)
    first = lines[0][3]["first"]
    d = p.daemon(conf=history_conf(p, history_save_s=3600))
    try:
        pin_in_process(p, d)
        h = history_of(d, p.clap_uri)
        check(isinstance(h, dict) and h["first"] == first and h["windows_solo"] == lines[0][3]["windows_solo"],
              "the next daemon reads what the last wrote: %s" % h)
    finally:
        d.close()
        p.close()


@test
def the_history_goes_to_the_xdg_state_home_by_default_and_to_the_machines_class_unless_host_class_says_otherwise():
    p = Plugins()
    state = os.path.join(p.dir, "xdg")
    d = p.daemon(conf=history_conf(p, history_file=None, host_class=None, history_save_s=3600), env={"XDG_STATE_HOME": state})
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        h = wait_for(lambda: (lambda r: r if isinstance(r, dict) else None)(history_of(d, p.clap_uri)), "a window")
        arch = subprocess.check_output(["uname", "-m"], text=True).strip()
        cls = h["class"].split("/")
        check(cls[0] == arch and len(cls) == 3, "arch/cores/clock of this machine: %s" % h["class"])
        d.expect("quit", "resp 0")
        wait_for(lambda: d.proc.poll() is not None, "the daemon to exit")
    finally:
        d.close()
    lines = history_lines(os.path.join(state, "plugin-hostd", "history"))
    check(len(lines) == 1 and lines[0][2] == h["class"], "$XDG_STATE_HOME/plugin-hostd/history: %s" % lines)
    p.close()
    bad = Plugins()
    try:
        d = bad.daemon(conf=history_conf(bad, host_class="two words"))
    except Fail:
        d = None
    check(d is None, "a host class with white space stops the daemon")
    bad.close()


@test
def a_window_in_which_the_members_of_a_worker_changed_is_not_counted():
    p = Plugins()
    other, other_uri = other_clap(p)
    d = p.daemon(conf=history_conf(p, history_window_s=4, history_save_s=3600))
    try:
        pin_in_process(p, d)
        pin_in_process(p, d, other_uri, other)
        d.expect("add %s 0 pool:g" % p.clap_uri, "resp 0")
        t0 = time.monotonic()
        time.sleep(2.4)
        d.expect("add %s 1 pool:g" % other_uri, "resp 1")
        # the window that began with one member would have closed at four seconds with two: it was dropped, and a new one
        # began when the second came, to close at six
        time.sleep(max(0, 4.8 - (time.monotonic() - t0)))
        check(history_of(d, p.clap_uri) == "-" and history_of(d, other_uri) == "-",
              "no window closed on a pool whose members changed: %s %s" % (history_of(d, p.clap_uri), history_of(d, other_uri)))
        h = wait_for(lambda: (lambda r: r if isinstance(r, dict) else None)(history_of(d, p.clap_uri)), "the window of the two")
        check(h["windows_grouped"] == "1" and h["windows_solo"] == "0", "it is a window of a group: %s" % h)
    finally:
        d.close()
        p.close()


def history_windows(d, uri):
    """the windows the plugin has, alone and in a group"""
    h = history_of(d, uri)
    return int(h["windows_solo"]) + int(h["windows_grouped"]) if isinstance(h, dict) else 0


def worker_writes_xruns(d, uri, inst, count):
    """the worker of the instance writes `xruns <count>` as the fake is told to, and the call returns when two windows of the
    plugin have closed since: the second began after the line, so the line is inside a window that is folded by then"""
    before = history_windows(d, uri)
    d.expect("param_get %d xruns=%s" % (inst, count), "resp 0 0")
    wait_for(lambda: history_windows(d, uri) >= before + 2, "two windows after xruns %s" % count, timeout=15.0)


@test
def a_window_in_which_the_count_of_xruns_rose_is_counted_once_for_the_plugin_alone():
    p = Plugins()
    d = p.daemon(conf=history_conf(p))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        wait_for(lambda: history_windows(d, p.clap_uri) >= 2 or None, "two windows")
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "0" and h["xrun_windows_grouped"] == "0",
              "a worker that wrote no count had no xruns: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 5)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "0", "the first count is where the daemon begins to look, not xruns: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 8)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "1" and h["xrun_windows_grouped"] == "0", "3 xruns in a window are one window, alone: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 8)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "1", "the same count again is no new xrun, the count is the worker's since it started: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 11)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "2", "3 more are the next window: %s" % h)
        # lines that are not a count: none of them moves the baseline or counts
        for bad in ("14x", "-5", "abc", "99999999999999999999999"):
            d.expect("param_get 0 xruns=%s" % bad, "resp 0 0")
        before = history_windows(d, p.clap_uri)
        wait_for(lambda: history_windows(d, p.clap_uri) >= before + 2, "two windows after the lines that are no count", timeout=15.0)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "2", "a line that is not a whole number counts nothing: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 12)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "3", "and the baseline was where it was: %s" % h)
    finally:
        d.close()
        p.close()


@test
def a_worker_that_restarts_begins_its_xruns_count_again_and_its_first_count_is_a_baseline_again():
    p = Plugins()
    d = p.daemon(conf=history_conf(p))
    try:
        pin_in_process(p, d)
        d.expect("add %s 0 own" % p.clap_uri, "resp 0")
        wait_for(lambda: history_windows(d, p.clap_uri) >= 1 or None, "a window")
        worker_writes_xruns(d, p.clap_uri, 0, 2)
        worker_writes_xruns(d, p.clap_uri, 0, 3)
        check(history_of(d, p.clap_uri)["xrun_windows_solo"] == "1", "one window of xruns before the restart: %s" % history_of(d, p.clap_uri))
        mark = d.mark()
        d.expect("param_set 0 crash 1", "resp 0")
        d.wait_event("instance_restored 0 ", since=mark)
        d.wait_up(0)
        # the new process counts from zero: 40 is its first count, above the 3 the old one ended at
        worker_writes_xruns(d, p.clap_uri, 0, 40)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "1", "the restarted worker's first count is a baseline, not 37 more xruns: %s" % h)
        worker_writes_xruns(d, p.clap_uri, 0, 41)
        h = history_of(d, p.clap_uri)
        check(h["xrun_windows_solo"] == "2", "and its next is counted: %s" % h)
    finally:
        d.close()
        p.close()


@test
def the_xruns_of_a_worker_of_two_are_a_window_of_each_member_in_a_group_and_none_alone():
    p = Plugins()
    other, other_uri = other_clap(p)
    d = p.daemon(conf=history_conf(p))
    try:
        pin_in_process(p, d)
        pin_in_process(p, d, other_uri, other)
        d.expect("add %s 0 pool:g" % p.clap_uri, "resp 0")
        d.expect("add %s 1 pool:g" % other_uri, "resp 1")
        wait_for(lambda: history_windows(d, p.clap_uri) >= 1 or None, "a window of the two")
        worker_writes_xruns(d, p.clap_uri, 0, 1)
        worker_writes_xruns(d, p.clap_uri, 0, 4)
        for uri in (p.clap_uri, other_uri):
            h = history_of(d, uri)
            check(h["xrun_windows_grouped"] == "1" and h["xrun_windows_solo"] == "0",
                  "every member of the worker has the window, in the grouped count: %s %s" % (uri, h))
    finally:
        d.close()
        p.close()


@test
def xruns_in_a_window_dropped_because_the_members_changed_are_nobodys():
    p = Plugins()
    other, other_uri = other_clap(p)
    d = p.daemon(conf=history_conf(p, history_window_s=2))
    try:
        pin_in_process(p, d)
        pin_in_process(p, d, other_uri, other)
        d.expect("add %s 0 pool:g" % p.clap_uri, "resp 0")
        wait_for(lambda: history_windows(d, p.clap_uri) >= 1 or None, "a window")
        worker_writes_xruns(d, p.clap_uri, 0, 1)
        # just after a window closed: the count rises, and the second member comes, inside the next one
        before = history_windows(d, p.clap_uri)
        wait_for(lambda: history_windows(d, p.clap_uri) > before or None, "the next window to close", timeout=15.0)
        d.expect("param_get 0 xruns=4", "resp 0 0")
        d.expect("add %s 1 pool:g" % other_uri, "resp 1")
        grouped = int(history_of(d, p.clap_uri)["windows_grouped"])
        wait_for(lambda: int(history_of(d, p.clap_uri)["windows_grouped"]) >= grouped + 2 or None, "two windows of the two", timeout=15.0)
        for uri in (p.clap_uri, other_uri):
            h = history_of(d, uri)
            check(h["xrun_windows_grouped"] == "0" and h["xrun_windows_solo"] == "0",
                  "the window the xruns came in was dropped with the change of members, and no later one has them: %s %s" % (uri, h))
    finally:
        d.close()
        p.close()


@test
def an_lv2_plugins_record_is_under_the_first_file_its_pin_holds():
    p = Plugins()
    d = p.daemon(conf=history_conf(p, lv2_worker="mod-host"))
    try:
        d.expect(p.lv2_pin(), "resp 0")
        d.expect("add lv2:%s 0 own" % LV2_URI, "resp 0")
        h = wait_for(lambda: (lambda r: r if isinstance(r, dict) else None)(history_of(d, "lv2:" + LV2_URI)), "a window")
        check(h["digest"] == sha(os.path.join(p.bundle, "manifest.ttl")), "the first file of the pin, manifest.ttl: %s" % h["digest"])
        check(history_of(d, LV2_URI)["digest"] == h["digest"], "with or without the lv2: prefix")
        d.expect("history_clear lv2:%s" % LV2_URI, "resp 0")
        check(history_of(d, LV2_URI) == "-", "and cleared by either")
    finally:
        d.close()
        p.close()


sys.exit(run_tests(TESTS))

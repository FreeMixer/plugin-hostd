# SPDX-License-Identifier: GPL-3.0-or-later
# The LV2 adapter of a real omx-clap-host behind the daemon, over jack, in the namespace tests/jack_e2e.sh built: which
# worker runs an LV2 plugin (lv2_worker), what a refusal of the adapter answers and says, and what a plugin the adapter
# does not find answers. mod-host is the real one too.
import os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Daemon, Fail, check, resp, run_tests, wait_for

EXE = os.environ["PLUGIN_HOSTD"]
CLAP_HOST = os.environ["OMX_CLAP_HOST"]
MOD_HOST = os.environ["MOD_HOST"]
FIXTURE = os.environ["LV2_FIXTURE"]            # the directory of plugin-hostd-fixture.lv2, built
ADAPTER_BUNDLES = os.environ["ADAPTER_BUNDLES"]  # omx-clap-core's build/lv2: omx-host-fixture.lv2 and its refused twins
GAIN = "urn:plugin-hostd:test:gain"
ATOM_IN = "urn:plugin-hostd:test:atom-in"            # the adapter takes it; mod-host runs it with the notes by jack
FIXED_BLOCK = "urn:plugin-hostd:test:fixed-block"    # requires a host feature the adapter lacks
MISSING = "hosting.features.missing"
BASED = "http://plugin-hostd.invalid/fixture/based"
BASE = "http://plugin-hostd.invalid/fixture/"
HOST_FIXTURE = "urn:openmixer:test:host-fixture"
REFUSED = "lv2_adapter_refused"
TESTS = []


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


class Run:
    """a daemon whose two programs are wrappers that note their pid and name before they become the real worker"""

    def __init__(self, lv2_path, **conf):
        wait_for(lambda: not any(l.startswith("effect_") for l in ports()), "the graph to hold no effect_ port", 10)
        self.dir = tempfile.mkdtemp(prefix="plugin-hostd-lv2-adapter.")
        self.notes = os.path.join(self.dir, "notes")
        open(self.notes, "w").close()
        settings = {"mod_host": self.wrapper("mod-host", MOD_HOST), "clap_host": self.wrapper("omx-clap-host", CLAP_HOST),
                    "lv2_path": lv2_path, "rpc_timeout_ms": 5000, "ready_timeout_ms": 10000}
        settings.update(conf)
        self.d = Daemon(EXE, settings["mod_host"], clap_worker=settings["clap_host"], conf=settings)

    def wrapper(self, name, real):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write('#!/bin/sh\necho "$$ %s" >> %s\nexec %s "$@"\n' % (name, self.notes, real))
        os.chmod(path, 0o755)
        return path

    def started(self):
        with open(self.notes) as f:
            return [l.split()[1] for l in f if l.strip()]

    def program(self, inst):
        pid = self.d.holder(inst)[1]["pid"]
        with open(self.notes) as f:
            for l in f:
                if l.split()[0] == str(pid):
                    return l.split()[1]
        raise Fail("no program started as pid %d" % pid)

    def refusals(self, since):
        return [e for e in self.d.events[since:] if e.startswith(REFUSED)]

    def close(self):
        self.d.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def ports():
    out = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=10).stdout
    out += subprocess.run(["pw-link", "-i"], capture_output=True, text=True, timeout=10).stdout
    return set(out.split("\n"))


def client_ports(inst):
    return sorted(p for p in ports() if p.startswith("effect_%d:" % inst))


def both():
    return "%s:%s" % (FIXTURE, ADAPTER_BUNDLES)


@test
def lv2_worker_omx_clap_host_runs_an_lv2_plugin_through_the_adapter():
    r = Run(both(), lv2_worker="omx-clap-host")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        r.d.expect("add %s 1" % HOST_FIXTURE, "resp 1")
        for i in (0, 1):
            check(r.d.holder(i)[1]["fmt"] == "lv2-clap" and r.program(i) == "omx-clap-host",
                  "instance %d is on the adapter row, run by omx-clap-host: %s" % (i, r.d.workers()))
        check("mod-host" not in r.started(), "mod-host never started: %s" % r.started())
        wait_for(lambda: client_ports(0), "effect_0's ports on the graph")
        r.d.expect("param_set 0 gain 0.5", "resp 0")
        r.d.expect("param_get 0 gain", "resp 0 0.5000")
    finally:
        r.close()


@test
def a_plugin_the_adapter_refuses_answers_512_and_the_event_carries_the_code_of_its_reply():
    r = Run(both(), lv2_worker="omx-clap-host")
    try:
        for i, (uri, code) in enumerate(((FIXED_BLOCK, MISSING),
                                         (HOST_FIXTURE + "#wide", "hosting.topology.wider-than-strip"),
                                         (HOST_FIXTURE + "#fixed", "hosting.features.missing"))):
            mark = r.d.mark()
            r.d.expect("add lv2:%s %d" % (uri, i), resp("LV2_ADAPTER_REFUSED"))
            event = r.d.wait_event(REFUSED + " ", since=mark)
            check(event == "%s %s %s omx-clap-host" % (REFUSED, uri, code), "the event of %s: %r" % (uri, event))
        check(r.d.workers() == {}, "no worker is left: %s" % r.d.workers())
        # in one pool worker, whose log every plugin of it shares, each refusal is named by its own reply
        r.d.expect("add lv2:%s 0 pool:fx" % GAIN, "resp 0")
        for i, (uri, code) in enumerate(((HOST_FIXTURE + "#fixed", "hosting.features.missing"),
                                         (HOST_FIXTURE + "#wide", "hosting.topology.wider-than-strip"),
                                         (FIXED_BLOCK, MISSING)), 1):
            mark = r.d.mark()
            r.d.expect("add lv2:%s %d pool:fx" % (uri, i), resp("LV2_ADAPTER_REFUSED"))
            event = r.d.wait_event(REFUSED + " ", since=mark)
            check(event == "%s %s %s omx-clap-host" % (REFUSED, uri, code), "in the pool, the event of %s: %r" % (uri, event))
        check(r.d.holder(0)[1]["inst"] == [0], "the pool worker lived through the refusals: %s" % r.d.workers())
    finally:
        r.close()


@test
def under_auto_a_plugin_the_adapter_refuses_runs_on_mod_host():
    r = Run(both(), lv2_worker="auto")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        check(r.program(0) == "omx-clap-host", "auto asks the adapter first: %s" % r.d.workers())
        mark = r.d.mark()
        r.d.expect("add lv2:%s 1" % FIXED_BLOCK, "resp 1")
        event = r.d.wait_event(REFUSED + " ", since=mark)
        check(event == "%s %s %s auto" % (REFUSED, FIXED_BLOCK, MISSING), "the event: %r" % event)
        check(r.d.holder(1)[1]["fmt"] == "lv2" and r.program(1) == "mod-host", "mod-host runs it: %s" % r.d.workers())
        wait_for(lambda: client_ports(1), "effect_1's ports on the graph")
        r.d.expect("param_set 1 gain 0.25", "resp 0")
        r.d.expect("param_get 1 gain", "resp 0 0.2500")
        before = r.started().count("omx-clap-host")
        r.d.expect("add lv2:%s 2" % FIXED_BLOCK, "resp 2")
        check(r.program(2) == "mod-host" and r.started().count("omx-clap-host") == before,
              "the next add goes straight to mod-host: %s" % r.started())
        check(len(r.refusals(mark)) == 1, "and the event was sent once: %s" % r.refusals(mark))
    finally:
        r.close()


def based_world():
    """a bundle that names the gain plugin under BASED behind an @base: lilv resolves it, the adapter's search of the
    manifest text does not find the uri"""
    world = tempfile.mkdtemp(prefix="plugin-hostd-based.")
    bundle = os.path.join(world, "based.lv2")
    os.mkdir(bundle)
    so = os.path.join(FIXTURE, "plugin-hostd-fixture.lv2", "plugin-hostd-fixture.so")
    with open(os.path.join(FIXTURE, "plugin-hostd-fixture.lv2", "plugin-hostd-fixture.ttl")) as f:
        ttl = f.read().split("<urn:plugin-hostd:test:atom-in>")[0].replace("<%s>" % GAIN, "<based>")
    with open(os.path.join(bundle, "manifest.ttl"), "w") as f:
        f.write("@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .\n@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                "@base <%s> .\n\n<based>\n    a lv2:Plugin ;\n    lv2:binary <file://%s> ;\n"
                "    rdfs:seeAlso <file://%s/based.ttl> .\n" % (BASE, so, bundle))
    with open(os.path.join(bundle, "based.ttl"), "w") as f:
        f.write("@base <%s> .\n" % BASE + ttl)
    return world


@test
def a_plugin_the_adapter_does_not_find_is_not_found_and_under_auto_mod_host_looks_for_it():
    world = based_world()
    try:
        r = Run(world, lv2_worker="omx-clap-host")
        try:
            mark = r.d.mark()
            r.d.expect("add lv2:%s 0" % BASED, "resp -101")
            r.d.expect("add lv2:urn:plugin-hostd:test:nowhere 1", "resp -101")
            check(r.d.workers() == {} and "mod-host" not in r.started(), "nothing runs, mod-host never started: %s" % r.started())
            check(r.refusals(mark) == [], "no refusal is said: %s" % r.refusals(mark))
        finally:
            r.close()
        r = Run(world, lv2_worker="auto")
        try:
            mark = r.d.mark()
            r.d.expect("add lv2:%s 0" % BASED, "resp 0")
            check(r.d.holder(0)[1]["fmt"] == "lv2" and r.program(0) == "mod-host", "mod-host found it: %s" % r.d.workers())
            check(r.started() == ["omx-clap-host", "mod-host"], "the adapter was asked first: %s" % r.started())
            r.d.expect("add lv2:%s 1" % BASED, "resp 1")
            check(r.started().count("omx-clap-host") == 2, "and is asked again on the next add: %s" % r.started())
            r.d.expect("add lv2:urn:plugin-hostd:test:nowhere 2", "resp -101")
            check(r.started().count("mod-host") >= 2, "a plugin neither finds is mod-host's own -101: %s" % r.started())
            check(r.refusals(mark) == [], "no refusal is said: %s" % r.refusals(mark))
        finally:
            r.close()
    finally:
        shutil.rmtree(world, ignore_errors=True)


def code_of(reply):
    words = reply.split()
    return int(words[1]) if len(words) > 1 and words[0] == "resp" and words[1].lstrip("-").isdigit() else None


@test
def the_tempo_is_handed_again_to_a_respawned_real_worker():
    r = Run(both(), lv2_worker="omx-clap-host")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        r.d.expect("param_set 0 gain 0.5", "resp 0")
        answer = r.d.send("set_bpm 133")
        check(code_of(answer) is not None, "the worker's answer to set_bpm, passed through: %r" % answer)
        pid = r.d.holder(0)[1]["pid"]
        mark = r.d.mark()
        os.kill(pid, 9)
        r.d.wait_event("instance_restored 0 ", since=mark, timeout=20)
        check(r.d.holder(0)[1]["pid"] != pid and r.d.holder(0)[1]["state"] == "up", "a new worker is up: %s" % r.d.workers())
        r.d.expect("param_get 0 gain", "resp 0 0.5000")
        if code_of(answer) < 0:
            # omx-clap-host does not take a tempo yet: its refusal of the replayed line is what shows it was handed again
            check("refused 'set_bpm 133': %s" % answer in r.d.log(), "the respawned worker was handed set_bpm 133: %s" % r.d.log()[-600:])
            print("PENDING FreeMixer/omx-clap-core#88: omx-clap-host answers set_bpm %r; the respawned worker was handed it again" % answer)
    finally:
        r.close()


@test
def notes_through_the_daemon_reach_the_real_workers_as_declared():
    r = Run(both(), lv2_worker="omx-clap-host")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        pid = r.d.holder(0)[1]["pid"]
        r.d.expect("note_on 0 16 60 100", "resp -902")
        answer = r.d.send("note_input 0")
        if answer.startswith("resp 0 "):
            check(answer == "resp 0 -", "a gain plugin takes no notes: %r" % answer)
            r.d.expect("note_on 0 0 60 100", resp("NO_NOTE_INPUT"))
        else:
            # omx-clap-host does not know the note verbs yet: its protocol's own "not found" is passed through and the
            # worker lives on
            note = r.d.send("note_on 0 0 60 100")
            check(answer == note == "not found", "the worker's answers, passed through: %r %r" % (answer, note))
            print("PENDING FreeMixer/omx-clap-core#122: omx-clap-host answers note_input %r and note_on %r" % (answer, note))
        check(r.d.holder(0)[1]["pid"] == pid and r.d.holder(0)[1]["state"] == "up", "the worker lives on: %s" % r.d.workers())
    finally:
        r.close()
    r = Run(both(), lv2_worker="mod-host")
    try:
        r.d.expect("add lv2:%s 0" % ATOM_IN, "resp 0")
        check(r.program(0) == "mod-host", "mod-host runs the MIDI plugin: %s" % r.started())
        r.d.expect("note_input 0", resp("NOTES_BY_JACK"))
        r.d.expect("note_on 0 0 60 100", resp("NOTES_BY_JACK"))
        r.d.expect("all_notes_off 0", resp("NOTES_BY_JACK"))
        wait_for(lambda: client_ports(0), "effect_0's ports on the graph")
    finally:
        r.close()


@test
def the_real_worker_answers_the_preset_list_as_declared():
    r = Run(both(), lv2_worker="omx-clap-host")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        pid = r.d.holder(0)[1]["pid"]
        answer = r.d.send("preset_list 0")
        if code_of(answer) is not None and code_of(answer) >= 0:
            for k in range(code_of(answer)):
                check(r.d.send("preset_get 0 %d" % k).startswith("resp 0 "), "preset %d of %r" % (k, answer))
        else:
            # omx-clap-host lists no presets yet: its answer is passed through and the worker lives on
            check(answer == "not found", "the worker's answer, passed through: %r" % answer)
            print("PENDING FreeMixer/omx-clap-core#95: omx-clap-host answers preset_list %r" % answer)
        check(r.d.holder(0)[1]["pid"] == pid and r.d.holder(0)[1]["state"] == "up", "the worker lives on: %s" % r.d.workers())
        # gestures, plugin-moved values and suggested pages are written by omx-clap-host from omx-clap-core#87 on; the
        # daemon relays them like any line, which the fake worker's cases prove
        print("PENDING FreeMixer/omx-clap-core#87: omx-clap-host writes no param_gesture or remote_page_suggest yet")
        r.d.expect("add lv2:%s 1" % GAIN, "resp 1")
    finally:
        r.close()
    r = Run(both(), lv2_worker="mod-host")
    try:
        r.d.expect("add lv2:%s 0" % GAIN, "resp 0")
        r.d.expect("preset_list 0", resp("NO_PRESET_LIST"))
    finally:
        r.close()


sys.exit(run_tests(TESTS))

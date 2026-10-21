#!/usr/bin/env python3
"""The plugind strip of the Zynthian spike against plugin-hostd and its fake host: no JACK, no plugin, no Zynthian
hardware.

    test-strip.py --zui <zynthian-ui checkout with zynthian_engine_plugind.patch applied>

Environment: PLUGIN_HOSTD (./plugin-hostd), FAKE_HOST (tests/fake-host). The real zynthian_chain, zynthian_processor
and zynthian_plugind_strip are imported; zyncoder, pyliblo3 and zynautoconnect are stubbed as test-path-b.py stubs them.
The engines are stand-ins that add one fake instance each (the plugind engine itself needs lilv and JACK:
test-path-b.py covers it); each JACK client has two audio ins and two outs, named as the CLAP worker names them.
Every instance goes to one pool worker (PLUGIND_PLACEMENT=pool:zyn), so the fake's list_connections is the whole graph
the daemon made. A parallel slot's mixer is the fake plugin fake:mix, declared in PLUGIND_MIX.

Each scenario is run as is and must pass, then once under each sabotage that breaks the guard it holds, and must fail.
Exit 0 when every scenario passes and every sabotage turns its scenario red.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", os.path.join(ROOT, "plugin-hostd")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))
MIX = '{"uri": "fake:mix", "branches": 4, "in": "in_{branch}_{ch}", "out": "out_{ch}", "channels": 2, "gain": "gain_{branch}"}'


class Fail(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Fail(what)


def stubs(root):
    os.makedirs(os.path.join(root, "zyncoder"))
    open(os.path.join(root, "zyncoder", "__init__.py"), "w").close()
    open(os.path.join(root, "zyncoder", "zyncore.py"), "w").write(
        "class _Z:\n    def __getattr__(self, name):\n        return lambda *a, **k: 0\nlib_zyncore = _Z()\n")
    open(os.path.join(root, "pyliblo3.py"), "w").write(
        "UDP = 1\nTCP = 2\nclass AddressError(Exception): pass\nclass ServerError(Exception): pass\n"
        "class Address:\n    def __init__(self, *a, **k): pass\n"
        "class ServerThread:\n    def __init__(self, *a, **k): pass\n")
    open(os.path.join(root, "zynautoconnect.py"), "w").write(
        "def _noop(*a, **k): pass\nadd_sidechain_ports = remove_sidechain_ports = request_audio_connect = "
        "request_midi_connect = release_lock = _noop\n"
        "def acquire_lock(*a, **k): return True\ndef get_audio_capture_ports(): return []\n")


def free_pair():
    """a command port whose next port is free too: the engine's client opens the feedback port at port + 1"""
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        try:
            t = socket.socket()
            t.bind(("127.0.0.1", p + 1))
            t.close()
            return p
        except OSError:
            continue
    raise Fail("no free pair of ports")


class daemon:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="zyn-strip.")
        conf = os.path.join(self.tmp, "plugin-hostd.conf")
        with open(conf, "w") as f:
            for k, v in {"mod_host": FAKE, "clap_host": FAKE, "state_root": self.tmp, "require_pins": 0,
                         "pins_dir": "", "backoff_base_ms": 20, "backoff_max_ms": 80, "ready_timeout_ms": 4000,
                         "rpc_timeout_ms": 1500, "idle_ms": 10, "checkpoint_ms": 600000}.items():
                f.write("%s %s\n" % (k, v))
        self.port = free_pair()
        self.log = open(os.path.join(self.tmp, "daemon.out"), "w+")
        self.proc = subprocess.Popen([EXE, "-n", "-p", str(self.port), "-f", str(self.port + 1), "-c", conf],
                                     stdout=self.log, stderr=subprocess.STDOUT)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise Fail("the daemon never listened")

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def setup(zui):
    root = tempfile.mkdtemp(prefix="zyn-strip-stubs-")
    stubs(root)
    sys.path[:0] = [root, zui]
    pkg = types.ModuleType("zyngine")
    pkg.__path__ = [os.path.join(zui, "zyngine")]
    sys.modules["zyngine"] = pkg
    from zyngine import zynthian_plugind_strip, zynthian_chain, zynthian_processor
    return zynthian_plugind_strip, zynthian_chain.zynthian_chain, zynthian_processor.zynthian_processor


S = CHAIN = PROC = None


class fake_engine:
    """what the strip asks of a plugind engine: the mark, an instance the daemon holds, its JACK client"""
    plugind = True

    def __init__(self, name):
        self.instance = S.alloc_instance()
        reply = S.client().cmd(S.add_line("fake:" + name, self.instance))
        check(S.resp_code(reply) == self.instance, "add fake:%s -> %r" % (name, reply))
        self.jackname = "effect_%d" % self.instance
        self.processors = []

    def get_jackname(self):
        return self.jackname

    def add_processor(self, p):
        self.processors.append(p)

    def remove_processor(self, p):
        self.processors.remove(p)

    def set_midi_chan(self, p):
        pass

    def stop(self):
        S.client().cmd("remove %d" % self.instance)
        S.free_instance(self.instance)


class foreign_engine(fake_engine):
    """a processor plugin-hostd does not run (a jalv one): its links are autoconnect's"""
    plugind = False

    def __init__(self, name):
        self.instance = None
        self.jackname = name
        self.processors = []


def ports(client_name, is_output):
    return ["%s:%s_%d" % (client_name, "out" if is_output else "in", c) for c in (1, 2)]


def graph():
    words = S.client().cmd("list_connections").split()
    check(words[:2] == ["resp", "0"], "list_connections -> %r" % words)
    return sorted(tuple(w.split(">")) for w in words[2:])


def links(*pairs):
    """effect clients joined in order, both channels: links("effect_0", "effect_1") is out_1>in_1, out_2>in_2"""
    out = []
    for a, b in pairs:
        out += [("%s:out_%d" % (a, c), "%s:in_%d" % (b, c)) for c in (1, 2)]
    return sorted(out)


def branch_links(members, mix):
    out = []
    for k, m in enumerate(members):
        out += [("%s:out_%d" % (m, c), "%s:in_%d_%d" % (mix, k + 1, c)) for c in (1, 2)]
    return out


class rig:
    """a chain of the real zynthian_chain, its strip on the fake ports, a daemon behind it"""

    def __init__(self, mix=True):
        os.environ["PLUGIND_PLACEMENT"] = "pool:zyn"
        if mix:
            os.environ["PLUGIND_MIX"] = MIX
        else:
            os.environ.pop("PLUGIND_MIX", None)
        S.instances.clear()
        S.strips.clear()
        self.d = daemon()
        S.set_client(S.plugind_client(port=self.d.port))
        self.chain = CHAIN(1, None, False, True)
        S.strips[1] = S.plugind_strip(ports=ports)
        self.chain.audio_out = ["system:playback"]

    def add(self, name, slot=None, engine=fake_engine):
        """as zynthian_chain_manager.add_processor: insert, then start the engine, then rebuild the graph"""
        p = PROC("PL/" + name, {"TYPE": "Audio Effect", "NAME": name}, len(self.chain.get_processors()) + 10)
        self.chain.insert_processor(p, slot)
        p.set_engine(engine(name))
        self.chain.rebuild_graph()
        return p

    def remove(self, p):
        """as zynthian_chain_manager.remove_processor: out of the chain (rebuilt), then the unused engine stops"""
        check(self.chain.remove_processor(p), "remove_processor")
        p.engine.stop()

    def order(self):
        return [[p.get_jackname() for p in slot] for slot in self.chain.audio_slots]

    def close(self):
        self.d.close()
        S.set_client(None)

# ------------------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------------------


def series_order_add_at_position():
    r = rig()
    try:
        a, b, c = r.add("a"), r.add("b"), r.add("c")
        check(r.order() == [["effect_0"], ["effect_1"], ["effect_2"]], "slots %s" % r.order())
        check(graph() == links(("effect_0", "effect_1"), ("effect_1", "effect_2")), "series graph %s" % graph())
        d = r.add("d", slot=1)
        check(r.order() == [["effect_0"], ["effect_3"], ["effect_1"], ["effect_2"]], "slots after add at 1: %s" % r.order())
        want = links(("effect_0", "effect_3"), ("effect_3", "effect_1"), ("effect_1", "effect_2"))
        check(graph() == want, "add at slot 1 re-links a>d>b>c: %s" % graph())
        # what the strip owns is no longer autoconnect's; the chain's ends still are
        routes = r.chain.audio_routes
        check("effect_3" not in routes and "effect_1" not in routes and "effect_2" not in routes,
              "strip-owned destinations left to autoconnect: %s" % sorted(routes))
        check(routes.get("system:playback") == ["effect_2"], "the chain's output fed by the last slot: %s" % routes)
    finally:
        r.close()


def removal_heals_and_replay_keeps_no_stale_link():
    r = rig()
    try:
        a, b, c = r.add("a"), r.add("b"), r.add("c")
        r.remove(b)
        check(r.order() == [["effect_0"], ["effect_2"]], "slots %s" % r.order())
        check(graph() == links(("effect_0", "effect_2")), "a joined to c, nothing to b: %s" % graph())
        check(r.chain.audio_routes.get("system:playback") == ["effect_2"], "output %s" % r.chain.audio_routes)
        # the daemon's ledger replays a's links when its worker comes back: a link to the removed b must not be there
        info = S.client().cmd("instance_info 0").split()
        os.kill(int(info[3]), signal.SIGKILL)
        end = time.monotonic() + 10
        while time.monotonic() < end and S.client().cmd("instance_info 0").split()[4:5] != ["up"]:
            time.sleep(0.05)
        time.sleep(0.3)
        check(graph() == links(("effect_0", "effect_2")), "after the worker's respawn, replayed: %s" % graph())
    finally:
        r.close()


def move_relinks_through_the_parallel_step():
    """Zynthian moves a processor by nudges: up into the neighbour's slot (parallel), then up out of it"""
    r = rig()
    try:
        a, b, c = r.add("a"), r.add("b"), r.add("c")
        check(r.chain.nudge_processor(c, True), "first nudge of c accepted with a mixer declared")
        check(r.order() == [["effect_0"], ["effect_1", "effect_2"]], "slots %s" % r.order())
        mix = "effect_3"
        want = sorted(links(("effect_0", "effect_1"), ("effect_0", "effect_2")) + branch_links(["effect_1", "effect_2"], mix))
        check(graph() == want, "fan-out a>{b,c}, b and c into the mix's branches: %s" % graph())
        routes = r.chain.audio_routes
        check(routes.get("system:playback") == [mix], "the output fed by the mix only, never by b and c: %s" % routes)
        check(all(len([s for s in v if s in ("effect_1", "effect_2")]) < 2 for v in routes.values()),
              "no input fed by two members: %s" % routes)
        gains = [S.client().cmd("param_get 3 gain_%d" % k) for k in (1, 2)]
        check(gains == ["resp 0 1.000000"] * 2, "branch gains at 1.0, Zynthian's unity sum: %s" % gains)
        check(r.chain.nudge_processor(c, True), "second nudge of c")
        check(r.order() == [["effect_0"], ["effect_2"], ["effect_1"]], "slots %s" % r.order())
        check(graph() == links(("effect_0", "effect_2"), ("effect_2", "effect_1")), "a>c>b, the mix gone: %s" % graph())
        check(S.client().cmd("instance_info 3") == "resp -3", "the mixer instance removed: %s" % S.client().cmd("instance_info 3"))
        check(r.chain.audio_routes.get("system:playback") == ["effect_1"], "output %s" % r.chain.audio_routes)
    finally:
        r.close()


def parallel_slot_without_a_mixer_is_refused_before_it_forms():
    r = rig(mix=False)
    try:
        a, b, c = r.add("a"), r.add("b"), r.add("c")
        before = graph()
        check(r.chain.nudge_processor(c, True) is False, "the nudge that would form a parallel slot answers False")
        check(r.order() == [["effect_0"], ["effect_1"], ["effect_2"]], "slots unchanged: %s" % r.order())
        check(graph() == before, "graph unchanged: %s" % graph())
        try:
            S.strips[1].check([[a], [b, c]])
            check(False, "check of a parallel slot with no mixer raised nothing")
        except S.plugind_strip_refused as e:
            check(e.code == "MIX_ELEMENT_ABSENT" and e.slot == 1, "code %s slot %s" % (e.code, e.slot))
    finally:
        r.close()


def parallel_slot_with_a_foreign_member_is_refused():
    r = rig()
    try:
        a = r.add("a")
        j = r.add("jalv_x", engine=foreign_engine)
        check(r.order() == [["effect_0"], ["jalv_x"]], "slots %s" % r.order())
        check(graph() == [], "nothing linked to a processor plugin-hostd does not run: %s" % graph())
        check(r.chain.audio_routes.get("jalv_x") == ["effect_0"], "the boundary left to autoconnect: %s" % r.chain.audio_routes)
        check(r.chain.nudge_processor(j, True) is False, "a nudge making [a, jalv_x] is refused")
        try:
            S.strips[1].check([[a, j]])
            check(False, "no refusal")
        except S.plugind_strip_refused as e:
            check(e.code == "PARALLEL_SLOT_FOREIGN", "code %s" % e.code)
    finally:
        r.close()


def too_many_branches_is_refused():
    r = rig()
    try:
        ps = [r.add(n) for n in "abcde"]
        try:
            S.strips[1].check([ps])
            check(False, "no refusal")
        except S.plugind_strip_refused as e:
            check(e.code == "MIX_BRANCHES_EXCEEDED", "code %s" % e.code)
    finally:
        r.close()


def bypass_and_branch_gain_are_values_on_the_daemon():
    r = rig()
    try:
        a, b = r.add("a"), r.add("b")
        check(S.jalv_line(1, ":bypass=1.000000") == "bypass 1 1", "jalv line %r" % S.jalv_line(1, ":bypass=1.000000"))
        S.client().cmd(S.jalv_line(1, ":bypass=1.000000"))
        check(S.client().cmd("param_get 1 :bypass") == "resp 0 1", "b bypassed: %s" % S.client().cmd("param_get 1 :bypass"))
        S.client().cmd(S.jalv_line(1, ":bypass=0.000000"))
        check(S.client().cmd("param_get 1 :bypass") == "resp 0 0", "b inline: %s" % S.client().cmd("param_get 1 :bypass"))
        check(S.jalv_line(1, "cutoff=2000.000000") == "param_set 1 cutoff 2000.000000", "param line")
        c = r.add("c")
        check(r.chain.nudge_processor(c, True), "parallel [b, c]")
        mix = list(S.strips[1].mixes.values())[0]
        S.strips[1].set_branch_gain(mix, 1, 0.5)
        check(S.client().cmd("param_get %d gain_2" % mix.instance) == "resp 0 0.500000", "branch 2 at 0.5")
        S.strips[1].set_mix_bypass(mix, True)
        check(S.client().cmd("param_get %d :bypass" % mix.instance) == "resp 0 1", "mix bypassed")
        check(mix.latency([0, 64]) == 64 and mix.latency([0, None]) is None, "latency is the slowest branch, unknown if any is")
    finally:
        r.close()


SCENARIOS = [series_order_add_at_position, removal_heals_and_replay_keeps_no_stale_link,
             move_relinks_through_the_parallel_step, parallel_slot_without_a_mixer_is_refused_before_it_forms,
             parallel_slot_with_a_foreign_member_is_refused, too_many_branches_is_refused,
             bypass_and_branch_gain_are_values_on_the_daemon]

# ------------------------------------------------------------------------------
# Sabotage: each breaks one guard of the strip; the named scenario must go red
# ------------------------------------------------------------------------------


def sab_no_disconnect():
    orig = S.plugind_strip.realise_links

    def realise_links(self, wanted):
        for l in [l for l in self.links if l not in wanted]:
            self.links.remove(l)   # forgets the link without taking it down
        for src, dst in wanted:
            if (src, dst) not in self.links:
                S.client().cmd("connect %s %s" % (src, dst))
                self.links.append((src, dst))
    S.plugind_strip.realise_links = realise_links
    return lambda: setattr(S.plugind_strip, "realise_links", orig)


def sab_no_mix_source():
    orig = S.plugind_strip.routes

    def routes(self, stages, audio_routes):
        mixes = [st.mix for st in stages]
        for st in stages:
            st.mix = None
        try:
            return orig(self, stages, audio_routes)
        finally:
            for st, m in zip(stages, mixes):
                st.mix = m
    S.plugind_strip.routes = routes
    return lambda: setattr(S.plugind_strip, "routes", orig)


def sab_accept_all():
    orig = S.accepts
    S.accepts = lambda chain, slots: True
    return lambda: setattr(S, "accepts", orig)


def sab_reverse_adjacent():
    orig = S.plugind_strip.link_plan

    def link_plan(self, stages, profile):
        return [(d.replace(":in", ":out"), s.replace(":out", ":in")) for s, d in orig(self, stages, profile)]
    S.plugind_strip.link_plan = link_plan
    return lambda: setattr(S.plugind_strip, "link_plan", orig)


def sab_bypass_as_param():
    orig = S.jalv_line

    def jalv_line(instance, cmd):
        if "=" in cmd and " " not in cmd:
            symbol, value = cmd.split("=", 1)
            return "param_set %s %s %s" % (instance, symbol, value)
        return orig(instance, cmd)
    S.jalv_line = jalv_line
    return lambda: setattr(S, "jalv_line", orig)


def sab_gain_one_over_n():
    orig = S.mix_element.__init__

    def init(self, slot, members, gains=None):
        orig(self, slot, members, gains or [1.0 / len(members)] * len(members))
    S.mix_element.__init__ = init
    return lambda: setattr(S.mix_element, "__init__", orig)


def sab_foreign_allowed():
    orig = S.is_plugind
    S.is_plugind = lambda p: True if p.engine is not None and p.engine.instance is None else orig(p)
    return lambda: setattr(S, "is_plugind", orig)


def sab_no_branch_bound():
    orig = S.mix_profile

    def mix_profile():
        p = orig()
        if p:
            p["branches"] = 99
        return p
    S.mix_profile = mix_profile
    return lambda: setattr(S, "mix_profile", orig)


SABOTAGE = [
    ("a stale link is forgotten, not disconnected", sab_no_disconnect, removal_heals_and_replay_keeps_no_stale_link),
    ("the same, seen on a move", sab_no_disconnect, move_relinks_through_the_parallel_step),
    ("a parallel slot's members stay the next input's sources", sab_no_mix_source, move_relinks_through_the_parallel_step),
    ("the nudge guard accepts every slot", sab_accept_all, parallel_slot_without_a_mixer_is_refused_before_it_forms),
    ("adjacent instances linked backwards", sab_reverse_adjacent, series_order_add_at_position),
    ("the host bypass sent as a parameter", sab_bypass_as_param, bypass_and_branch_gain_are_values_on_the_daemon),
    ("branch gains default to 1/N", sab_gain_one_over_n, move_relinks_through_the_parallel_step),
    ("a foreign member counted as plugin-hostd's", sab_foreign_allowed, parallel_slot_with_a_foreign_member_is_refused),
    ("the mixer's branch count not enforced", sab_no_branch_bound, too_many_branches_is_refused),
]


def run(fn):
    try:
        fn()
        return None
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


def main():
    global S, CHAIN, PROC
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zui", required=True)
    a = ap.parse_args()
    S, CHAIN, PROC = setup(a.zui)
    failed = 0
    for fn in SCENARIOS:
        err = run(fn)
        print(("ok   " if err is None else "FAIL ") + fn.__name__ + ("" if err is None else ": " + err), flush=True)
        failed += err is not None
    for what, sab, fn in SABOTAGE:
        restore = sab()
        try:
            err = run(fn)
        finally:
            restore()
        print(("ok   sabotage red: " if err else "FAIL sabotage stayed green: ") + "%s -> %s%s" % (
            what, fn.__name__, (" (" + err + ")") if err else ""), flush=True)
        failed += err is None
    print("STRIP %s: %d failed" % ("PASS" if not failed else "FAIL", failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

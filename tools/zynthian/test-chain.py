#!/usr/bin/env python3
"""The plugind chain of the Zynthian engine against plugin-hostd: one Zynthian chain as one chain line, read back.

    test-chain.py --zui <zynthian-ui checkout with the spike engine applied: spike-engine.sh>

Environment: PLUGIN_HOSTD (./plugin-hostd, a daemon with chain_get, plugin-hostd#162), FAKE_HOST (tests/fake-host);
PLUGIN_HOSTD_OLD, a daemon without chain_get, adds the floor scenario. The real zynthian_chain, zynthian_processor and
zynthian_plugind_chain are imported; zyncoder, pyliblo3 and zynautoconnect are stubbed as test-path-b.py stubs them.
The engines are stand-ins that add one instance each (the plugind engine itself needs lilv and JACK: test-path-b.py
covers it). The head of every chain is an LV2 member on the adapter row (lv2_worker omx-clap-host), the others CLAP.

With CHAIN_E2E=1 the workers are the real omx-clap-host (CLAP_HOST), the members the plugins CHAIN_LV2_URI and
CHAIN_CLAP_URI, under a running JACK server; FAULT_CLAP_URI is a CLAP plugin that aborts on CHAIN_FAULT_PARAM.

Each scenario is run as is and must pass, then once under each sabotage that breaks the guard it holds, and must fail
on the check the sabotage names. Exit 0 when every scenario passes and every sabotage turns its scenario red on that
check.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", os.path.join(ROOT, "plugin-hostd")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))
OLD = os.environ.get("PLUGIN_HOSTD_OLD")
E2E = os.environ.get("CHAIN_E2E") == "1"
LOCK_WAIT = 2.0


class Fail(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Fail(what)


def wait(cond, what, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    raise Fail("timed out: " + what)


def stubs(root):
    os.makedirs(os.path.join(root, "zyncoder"))
    open(os.path.join(root, "zyncoder", "__init__.py"), "w").close()
    open(os.path.join(root, "zyncoder", "zyncore.py"), "w").write(
        "class _Z:\n    def __getattr__(self, name):\n        return lambda *a, **k: 0\nlib_zyncore = _Z()\n")
    open(os.path.join(root, "pyliblo3.py"), "w").write(
        "UDP = 1\nTCP = 2\nclass AddressError(Exception): pass\nclass ServerError(Exception): pass\n"
        "class Address:\n    def __init__(self, *a, **k): pass\n"
        "class ServerThread:\n    def __init__(self, *a, **k): pass\n")
    # autoconnect's lock is a real one: its acquire_lock waits for ever (zynthian_autoconnect.py:1602), the stub's
    # waits LOCK_WAIT seconds and counts the wait that would never have ended
    open(os.path.join(root, "zynautoconnect.py"), "w").write(
        "import threading\nlock = threading.Lock()\nhung = []\n"
        "def _noop(*a, **k): pass\nadd_sidechain_ports = remove_sidechain_ports = request_audio_connect = "
        "request_midi_connect = _noop\n"
        "def acquire_lock():\n    if lock.acquire(timeout=%r):\n        return True\n    hung.append(1)\n"
        "    return False\n"
        "def release_lock():\n    try:\n        lock.release()\n    except RuntimeError:\n        pass\n"
        "def get_audio_capture_ports(): return []\n" % LOCK_WAIT)


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
    def __init__(self, exe=EXE, port=None):
        self.tmp = tempfile.mkdtemp(prefix="zyn-chain.")
        conf = os.path.join(self.tmp, "plugin-hostd.conf")
        host = os.environ.get("CLAP_HOST", "omx-clap-host") if E2E else FAKE
        settings = {"mod_host": host, "clap_host": host, "lv2_worker": "omx-clap-host", "state_root": self.tmp,
                    "require_pins": 0, "pins_dir": "", "backoff_base_ms": 20, "backoff_max_ms": 80,
                    "ready_timeout_ms": 8000 if E2E else 4000, "rpc_timeout_ms": 3000 if E2E else 1500,
                    "idle_ms": 10, "checkpoint_ms": 600000}
        if E2E:
            # a namespace's root is root: the system directories of descriptors are not this run's to write
            settings["descriptor_dir"] = os.path.join(self.tmp, "descriptors")
            settings["qualification_dir"] = os.path.join(self.tmp, "qualification")
            settings["lv2_path"] = os.environ.get("CHAIN_LV2_PATH", "/usr/lib64/lv2")
        with open(conf, "w") as f:
            for k, v in settings.items():
                f.write("%s %s\n" % (k, v))
        self.port = port or free_pair()
        self.log = open(os.path.join(self.tmp, "daemon.out"), "w+")
        self.proc = subprocess.Popen([exe, "-n", "-p", str(self.port), "-f", str(self.port + 1), "-c", conf],
                                     stdout=self.log, stderr=subprocess.STDOUT)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.log.seek(0)
        raise Fail("the daemon never listened: %s" % self.log.read()[-600:])

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def setup(zui):
    root = tempfile.mkdtemp(prefix="zyn-chain-stubs-")
    stubs(root)
    sys.path[:0] = [root, zui]
    pkg = types.ModuleType("zyngine")
    pkg.__path__ = [os.path.join(zui, "zyngine")]
    sys.modules["zyngine"] = pkg
    from zyngine import zynthian_plugind_chain, zynthian_chain, zynthian_processor
    return zynthian_plugind_chain, zynthian_chain.zynthian_chain, zynthian_processor.zynthian_processor


S = CHAIN = PROC = None


def uri_of(name, lv2):
    if E2E:
        return os.environ["CHAIN_LV2_URI"] if lv2 else os.environ["FAULT_CLAP_URI" if name == "fault" else "CHAIN_CLAP_URI"]
    return ("lv2:urn:zyn:%s" if lv2 else "clap:fake#%s") % name


class fake_engine:
    """what the chain asks of a plugind engine: the mark, an instance the daemon holds, its JACK client"""
    plugind = True

    def __init__(self, name, lv2=False, uri=None):
        self.instance = S.alloc_instance()
        reply = S.client().cmd(S.add_line(uri or uri_of(name, lv2), self.instance))
        check(S.resp_code(reply) == self.instance, "add %s -> %r" % (name, reply))
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


class lv2_engine(fake_engine):
    def __init__(self, name):
        super().__init__(name, lv2=True)


class foreign_engine(fake_engine):
    """a processor plugin-hostd does not run (a jalv one): its links are autoconnect's"""
    plugind = False

    def __init__(self, name):
        self.instance = None
        self.jackname = name
        self.processors = []


def read():
    """chain_get 1: (worker, declared, running)"""
    got = S.read_chain(1)
    check(got is not None, "chain 1 is declared")
    return got


def workers():
    out = {}
    for rec in S.client().cmd("worker_list").split()[2:]:
        head, insts = rec.rsplit(":", 1)
        # the place holds colons: the fields on the left, the instances on the right; a daemon with core placement
        # (docs/placement.md) writes the worker's core, a number or -, before the place, which never is one
        k, pid, fmt, state, place = head.split(":", 4)
        first, _, rest = place.partition(":")
        if rest and (first.isdigit() or first == "-"):
            place = rest
        out[k] = {"pid": int(pid), "fmt": fmt, "state": state, "place": place,
                  "inst": [] if insts == "-" else [int(x) for x in insts.split(",")]}
    return out


def chain_worker():
    w = [(k, v) for k, v in workers().items() if v["place"] == "chain:1"]
    check(len(w) == 1, "one worker runs chain 1: %s" % workers())
    return w[0]


def where(inst):
    for k, w in workers().items():
        if inst in w["inst"]:
            return w
    return None


class rig:
    """a chain of the real zynthian_chain, its plugind chain, a daemon behind it"""

    def __init__(self, exe=EXE):
        os.environ.pop("PLUGIND_PLACEMENT", None)
        # a lock one scenario left held is that scenario's red, not the next one's
        autoconnect = sys.modules["zynautoconnect"]
        autoconnect.release_lock()
        autoconnect.hung.clear()
        S.instances.clear()
        S.chains.clear()
        self.d = daemon(exe)
        # a client the engine opens again after a loss finds this scenario's daemon, never a daemon of its own
        os.environ["PLUGIND_PORT"] = str(self.d.port)
        os.environ["PLUGIND_BIN"] = "/nonexistent/plugin-hostd"
        S.set_client(S.plugind_client(port=self.d.port))
        self.chain = CHAIN(1, None, False, True)
        self.chain.audio_out = ["system:playback"]

    def add(self, name, slot=None, engine=fake_engine):
        """as zynthian_chain_manager.add_processor: insert, then start the engine, then rebuild the graph"""
        p = PROC("PL/" + name, {"TYPE": "Audio Effect", "NAME": name}, len(self.chain.get_processors()) + 10)
        self.chain.insert_processor(p, slot)
        p.set_engine(engine(name))
        self.chain.rebuild_graph()
        return p

    def remove(self, p, between=None):
        """as zynthian_chain_manager.remove_processor: out of the chain (rebuilt), then the unused engine stops"""
        check(self.chain.remove_processor(p), "remove_processor")
        if between:
            between()
        p.engine.stop()

    def order(self):
        return [[p.get_jackname() for p in slot] for slot in self.chain.audio_slots]

    def routes(self):
        """read as autoconnect reads them, under its lock: a rebuild a feedback event asks for builds them in place"""
        autoconnect = sys.modules["zynautoconnect"]
        check(autoconnect.acquire_lock(), "the autoconnect lock is free to read the routes")
        try:
            return dict(self.chain.audio_routes)
        finally:
            autoconnect.release_lock()

    def close(self):
        """the daemon down, then the rebuilds its feedback asked for run out against a closed client, never against
        the next scenario's daemon"""
        S._client.chain_handlers.clear()
        self.d.close()
        S.set_client(closed_client())
        for t in threading.enumerate():
            if t is not threading.current_thread() and t.name.endswith("(<lambda>)"):
                t.join(2 * LOCK_WAIT)
        S.set_client(None)


class closed_client:
    """the client of a scenario that ended"""
    output_handlers, chain_handlers = {}, {}

    def cmd(self, line):
        raise ConnectionError("the scenario's daemon is closed: %s" % line)


def settle():
    """a chain line is answered before its worker replays: wait for the worker to be up"""
    wait(lambda: chain_worker()[1]["state"] == "up", "the chain's worker up")


def nodes():
    """end to end: the nodes of the graph named effect_<n>, the daemon's instances' JACK clients (pw-dump)"""
    import json
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
    return sorted(o["info"]["props"].get("node.name", "") for o in dump if o.get("type") == "PipeWire:Interface:Node"
                  and o.get("info", {}).get("props", {}).get("node.name", "").startswith("effect_"))


def one_node(head, what):
    """end to end: the chain is one node of the graph, its head's client"""
    if E2E:
        wait(lambda: nodes() == [head], "%s: one node %s, have %s" % (what, head, nodes()))

# ------------------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------------------


def series_order_add_at_position():
    r = rig()
    try:
        r.add("a", engine=lv2_engine), r.add("b"), r.add("c")
        settle()
        check(r.order() == [["effect_0"], ["effect_1"], ["effect_2"]], "slots %s" % r.order())
        k, w = chain_worker()
        check(read() == (k, [0, 1, 2], [0, 1, 2]), "an LV2 and two CLAP members, read back: %s" % (read(),))
        check(w["inst"] == [0, 1, 2] and w["fmt"] == "lv2-clap", "one worker on the adapter row: %s" % w)
        one_node("effect_0", "an LV2 and two CLAP members")
        r.add("d", slot=1)
        settle()
        one_node("effect_0", "a member added at slot 1")
        check(r.order() == [["effect_0"], ["effect_3"], ["effect_1"], ["effect_2"]], "slots after add at 1: %s" % r.order())
        check(read() == (k, [0, 3, 1, 2], [0, 3, 1, 2]), "add at slot 1 reads back a,d,b,c: %s" % (read(),))
        check(chain_worker()[1]["pid"] == w["pid"], "the CLAP member joined the running worker: %s" % workers())
        routes = r.routes()
        check(not {"effect_3", "effect_1", "effect_2"} & set(routes), "inner routes left to autoconnect: %s" % routes)
        check(routes.get("system:playback") == ["effect_0"], "the chain's output is the head's client: %s" % routes)
    finally:
        r.close()


def removal_heals_and_replay_keeps_no_stale_member():
    r = rig()
    try:
        a, b, c = r.add("a", engine=lv2_engine), r.add("b"), r.add("c")
        settle()
        k, w = chain_worker()

        def after_the_rebuild():
            check(read() == (k, [0, 2], [0, 2]), "the chain read back without b: %s" % (read(),))
            check(where(1) and where(1)["place"] == "own", "b left the chain's worker: %s" % workers())
        r.remove(b, between=after_the_rebuild)
        check(r.order() == [["effect_0"], ["effect_2"]], "slots %s" % r.order())
        check(where(1) is None, "b is gone: %s" % workers())
        check(r.routes().get("system:playback") == ["effect_0"], "output %s" % r.routes())
        # a kill from outside names no culprit: the daemon splits the members, each replayed in a worker of its own,
        # and b is in none of them; the engine routes the clients one by one, in slot order, until the chain forms again
        os.kill(w["pid"], signal.SIGKILL)
        wait(lambda: read() == ("-", [0, 2], []), "the chain split, read back as declared: %s" % (read(),))
        wait(lambda: where(0) and where(2) and where(0)["state"] == where(2)["state"] == "up", "the members up alone")
        check(where(1) is None and where(0)["place"] == where(2)["place"] == "own", "no stale member: %s" % workers())
        wait(lambda: r.routes().get("effect_2") == ["effect_0"] and r.routes().get("system:playback") == ["effect_2"],
             "the split chain routed client by client: %s" % r.routes())
    finally:
        r.close()


def move_by_nudge_is_one_chain_line():
    """a nudge past a single plugind neighbour swaps the two slots: no parallel step"""
    r = rig()
    try:
        a, b, c = r.add("a", engine=lv2_engine), r.add("b"), r.add("c")
        settle()
        k, w = chain_worker()
        check(r.chain.nudge_processor(c, True), "the nudge of c up is accepted")
        check(r.order() == [["effect_0"], ["effect_2"], ["effect_1"]], "slots %s" % r.order())
        check(read() == (k, [0, 2, 1], [0, 2, 1]), "the move reads back a,c,b: %s" % (read(),))
        check(r.chain.nudge_processor(c, True), "the second nudge of c")
        check(r.order() == [["effect_2"], ["effect_0"], ["effect_1"]], "slots %s" % r.order())
        check(read() == (k, [2, 0, 1], [2, 0, 1]), "c heads the chain: %s" % (read(),))
        check(chain_worker()[1]["pid"] == w["pid"], "a move restarts no member: %s" % workers())
        one_node("effect_2", "the chain moved under its new head")
        check(r.routes().get("system:playback") == ["effect_2"], "the new head's client feeds the output: %s" % r.routes())
    finally:
        r.close()


def parallel_slot_is_refused_by_name_before_it_forms():
    r = rig()
    try:
        a = r.add("a", engine=lv2_engine)
        j = r.add("jalv_x", engine=foreign_engine)
        settle()
        before = read()
        check(r.chain.nudge_processor(j, True) is False, "the nudge that would form [a, jalv_x] answers False")
        check(r.order() == [["effect_0"], ["jalv_x"]], "slots unchanged: %s" % r.order())
        check(read() == before, "the chain unchanged: %s" % (read(),))
        for slots, slot in (([[a, j]], 0), ([[a], [j, a]], 1)):
            try:
                S.chains[1].check(slots)
                check(False, "check of %s raised nothing" % slots)
            except S.plugind_chain_refused as e:
                check(e.code == "PARALLEL_SLOT_REFUSED" and e.slot == slot, "code %s slot %s" % (e.code, e.slot))
    finally:
        r.close()


def a_foreign_processor_ends_the_chain_line():
    r = rig()
    try:
        r.add("a", engine=lv2_engine)
        r.add("jalv_x", engine=foreign_engine)
        r.add("b")
        settle()
        check(r.order() == [["effect_0"], ["jalv_x"], ["effect_1"]], "slots %s" % r.order())
        check(read()[1:] == ([0], [0]), "the chain line ends before the foreign processor: %s" % (read(),))
        check(S.chains[1].refusal == "PLUGIND_RUN_SPLIT", "the split is named: %s" % S.chains[1].refusal)
        check(where(1)["place"] == "own", "b runs outside the line: %s" % workers())
        routes = r.routes()
        check(routes.get("jalv_x") == ["effect_0"] and routes.get("effect_1") == ["jalv_x"] and
              routes.get("system:playback") == ["effect_1"], "the boundaries left to autoconnect: %s" % routes)
    finally:
        r.close()


def a_crashed_member_leaves_the_others_running():
    r = rig()
    try:
        names = ("a", "fault", "c") if E2E else ("a", "b", "c")
        a, b, c = r.add(names[0], engine=lv2_engine), r.add(names[1]), r.add(names[2])
        settle()
        k, w = chain_worker()
        if not E2E:
            for n in (0, 1, 2):
                S.client().cmd("param_set %d gain 0.%d000" % (n, n + 1))
        # against the fake the head is the culprit, so the chain's client becomes the next member's; end to end the
        # culprit is the fault plugin, the second member, aborting on its own parameter
        culprit = 1 if E2E else 0
        if E2E:
            # the fault plugin aborts on its write only once it has run its blocks (omx-clap-core tests/fault_clap.c)
            wait(lambda: float((S.client().cmd("param_get 1 1").split() + ["0"] * 3)[2]) >= 200, "the fault plugin ran")
        S.client().cmd(os.environ["CHAIN_FAULT_PARAM"] % culprit if E2E else "param_set 0 crash 1")
        survivors = [n for n in (0, 1, 2) if n != culprit]
        wait(lambda: read()[2] == survivors and chain_worker()[1]["state"] == "up", "the chain runs %s" % survivors)
        check(read()[1] == [0, 1, 2], "the culprit keeps its declared place: %s" % (read(),))
        check(where(culprit)["place"] == "own", "the culprit runs alone: %s" % workers())
        info = S.client().cmd("instance_info %d" % culprit).split()
        check(info[6] == "1", "the culprit is quarantined: %s" % info)
        if E2E:
            wait(lambda: nodes() == sorted(["effect_%d" % survivors[0], "effect_%d" % culprit]),
                 "the chain one node, the culprit one of its own: %s" % nodes())
        head = "effect_%d" % survivors[0]
        wait(lambda: r.routes().get("system:playback") == [head], "the routes follow the running head %s: %s" % (
            head, r.routes()))
        if not E2E:
            for n in survivors:
                check(S.client().cmd("param_get %d gain" % n) == "resp 0 0.%d000" % (n + 1), "member %d's value" % n)
    finally:
        r.close()


def bypass_and_parameters_name_one_member():
    r = rig()
    try:
        # end to end the third member is the fault plugin, whose parameter 0 is a gain (below 0.9 it never aborts)
        r.add("a", engine=lv2_engine), r.add("b"), r.add("fault" if E2E else "c")
        settle()
        k, w = chain_worker()
        check(S.jalv_line(1, ":bypass=1.000000") == "bypass 1 1", "jalv line %r" % S.jalv_line(1, ":bypass=1.000000"))
        def value(n, symbol):
            words = S.client().cmd("param_get %d %s" % (n, symbol)).split()
            return float(words[2]) if words[:2] == ["resp", "0"] and len(words) == 3 else None
        check(S.resp_code(S.client().cmd(S.jalv_line(1, ":bypass=1.000000"))) == 0, "bypass of b")
        check(value(1, ":bypass") == 1, "b bypassed: %s" % value(1, ":bypass"))
        check(value(2, ":bypass") != 1, "c is not: %s" % value(2, ":bypass"))
        S.client().cmd(S.jalv_line(1, ":bypass=0.000000"))
        check(value(1, ":bypass") == 0, "b inline: %s" % value(1, ":bypass"))
        # a parameter of one member: the fake's gain, the fault plugin's parameter 0 end to end
        symbol = "0" if E2E else "gain"
        check(S.jalv_line(2, "%s=0.250000" % symbol) == "param_set 2 %s 0.250000" % symbol, "param line")
        check(S.resp_code(S.client().cmd(S.jalv_line(2, "%s=0.250000" % symbol))) == 0, "param_set of c")
        check(value(2, symbol) == 0.25 and value(1, symbol) != 0.25, "c's value only: %s %s" % (
            value(2, symbol), value(1, symbol)))
        check(read() == (k, [0, 1, 2], [0, 1, 2]) and chain_worker()[1]["pid"] == w["pid"],
              "bypass and parameters change no chain and restart no worker: %s %s" % (read(), workers()))
    finally:
        r.close()


def the_last_member_removed_clears_the_chain_read_back():
    """the chain cleared when its last plugind processor leaves, read back like every other edit: a clear the daemon
    answered but did not act on is named"""
    r = rig()
    try:
        a, b = r.add("a", engine=lv2_engine), r.add("b")
        settle()
        r.remove(b)
        r.remove(a)
        check(S.read_chain(1) is None, "the chain cleared: %s" % (S.read_chain(1),))
        check(S.chains[1].declared == [] and S.chains[1].running == [] and S.chains[1].refusal is None,
              "the clear read back: %s %s %s" % (S.chains[1].declared, S.chains[1].running, S.chains[1].refusal))
        c, d = r.add("c", engine=lv2_engine), r.add("d")
        settle()
        r.remove(d)
        c_cmd = S.client().cmd
        S.client().cmd = lambda line: "resp 0" if line.startswith("chain_clear ") else c_cmd(line)
        try:
            r.remove(c)
        finally:
            S.client().cmd = c_cmd
        check(S.chains[1].refusal == "PLUGIND_READBACK_MISMATCH",
              "an unacted clear is named: %s, chain_get %s" % (S.chains[1].refusal, S.read_chain(1)))
    finally:
        r.close()


class dying_socket:
    """the command socket of a daemon killed while a command is in flight: the command is sent, then the daemon dies"""

    def __init__(self, sock, kill):
        self.sock, self.kill = sock, kill

    def sendall(self, data):
        self.sock.sendall(data)
        if self.kill:
            self.kill()
            self.kill = None

    def __getattr__(self, name):
        return getattr(self.sock, name)


def a_daemon_gone_mid_command_leaves_no_lock_held():
    """plugin-hostd killed with a rebuild's command in flight (a restart): every later rebuild takes autoconnect's lock
    again, and the chain is routed client by client, as Zynthian builds it"""
    r = rig()
    try:
        r.add("a", engine=lv2_engine), r.add("b")
        settle()
        autoconnect = sys.modules["zynautoconnect"]
        S.client().sock = dying_socket(S.client().sock, lambda: (r.d.proc.kill(), r.d.proc.wait()))
        raised = []
        for n in range(3):
            try:
                r.chain.rebuild_audio_graph()
            except Exception as e:
                raised.append("%s: %s" % (type(e).__name__, e))
            check(autoconnect.acquire_lock(), "the autoconnect lock is taken again after rebuild %d: %s" % (n, raised))
            autoconnect.release_lock()
        check(not raised, "a rebuild raises nothing on a lost daemon: %s" % raised)
        check(S.chains[1].refusal == "PLUGIND_DAEMON_LOST", "the loss is named: %s" % S.chains[1].refusal)
        routes = r.routes()
        check(routes.get("effect_1") == ["effect_0"] and routes.get("system:playback") == ["effect_1"],
              "the chain routed client by client, as Zynthian builds it: %s" % routes)
    finally:
        r.close()


class closing_daemon:
    """a daemon that closes every command connection cleanly after reading a command, with no reply: a FIN before any
    byte. The feedback port accepts and holds."""

    def __init__(self):
        self.port = free_pair()
        self.socks = []
        for port in (self.port, self.port + 1):
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(8)
            self.socks.append(s)
            threading.Thread(target=self.serve, args=(s, port == self.port), daemon=True).start()

    def serve(self, listener, closes):
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            if closes:
                conn.recv(65536)
                conn.close()
            else:
                self.socks.append(conn)

    def close(self):
        for s in self.socks:
            s.close()


def a_clean_close_before_any_reply_is_a_lost_daemon():
    """a daemon that closes the command connection with a FIN and no reply (a restart between the command and its
    answer) is a lost one, never an empty reply: the loss is named, not read as a daemon without chain_get"""
    r = rig()
    stub = closing_daemon()
    try:
        r.add("a", engine=lv2_engine), r.add("b")
        settle()
        S.set_client(S.plugind_client(port=stub.port))
        raised = []
        try:
            r.chain.rebuild_audio_graph()
        except Exception as e:
            raised.append("%s: %s" % (type(e).__name__, e))
        check(not raised, "a rebuild raises nothing on a lost daemon: %s" % raised)
        pc = S.chains[1]
        check(pc.refusal == "PLUGIND_DAEMON_LOST", "the loss is named: %s" % pc.refusal)
        check(pc.declared == [] and pc.running == [], "what the lost daemon held is not known: %s, %s" %
              (pc.declared, pc.running))
        check(S._client.lost and S._client.sock.fileno() == -1, "the lost connection is closed")
    finally:
        stub.close()
        r.close()


def a_restarted_daemon_is_reached_by_the_next_realisation():
    """plugin-hostd killed, then started again on its ports: the realisation after it opens a new connection (one
    attempt per command) and declares the chain line again; the realisation in between names the loss"""
    r = rig()
    try:
        r.add("a", engine=lv2_engine), r.add("b")
        settle()
        port = r.d.port
        r.d.proc.kill()
        r.d.proc.wait()
        r.chain.rebuild_audio_graph()
        check(S.chains[1].refusal == "PLUGIND_DAEMON_LOST", "the loss is named: %s" % S.chains[1].refusal)
        r.d.close()
        r.d = daemon(EXE, port=port)
        # the engines' own instances, put back through a connection of the test's: the realisation opens its own
        again = S.plugind_client(port=port)
        for n, lv2 in ((0, True), (1, False)):
            check(S.resp_code(again.cmd(S.add_line(uri_of("ab"[n], lv2), n))) == n, "instance %d added again" % n)
        again.sock.close()
        again.fb.close()
        r.chain.rebuild_audio_graph()
        check(S.chains[1].refusal is None, "the next realisation succeeds: %s" % S.chains[1].refusal)
        settle()
        check(read()[1:] == ([0, 1], [0, 1]), "the line is declared again: %s" % (read(),))
    finally:
        r.close()


def audio_ports(client, output):
    """end to end: a JACK client's audio ports, in name order (pw-link -o / -i)"""
    listed = subprocess.run(["pw-link", "-o" if output else "-i"], capture_output=True, text=True).stdout.split()
    return sorted(p for p in listed if p.startswith(client + ":") and "midi" not in p.lower() and "event" not in p.lower())


class reference:
    """end to end: the same plugins one client each, in a second omx-clap-host outside the daemon, linked in series"""

    def __init__(self):
        self.port = free_pair()
        env = dict(os.environ, LV2_PATH=os.environ.get("CHAIN_LV2_PATH", "/usr/lib64/lv2"))
        self.proc = subprocess.Popen([os.environ["CLAP_HOST"], "-n", "-p", str(self.port)], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        wait(lambda: "ready" in self.proc.stdout.readline(), "the reference host ready")
        self.sock = socket.create_connection(("127.0.0.1", self.port))

    def cmd(self, line):
        self.sock.sendall(line.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            buf += self.sock.recv(65536)
        return buf[:-1].decode()

    def series(self, first, uris, params=None):
        """the uris as instances first, first + 1, ... one client each, linked in that order; params, one list of
        (symbol, value) per uri, are set as each is added"""
        for k, uri in enumerate(uris):
            check(self.cmd("add %s %d" % (uri, first + k)) == "resp %d" % (first + k), "reference add %s" % uri)
            for symbol, value in (params or [[]] * len(uris))[k]:
                check(self.cmd("param_set %d %s %s" % (first + k, symbol, value)) == "resp 0",
                      "reference param_set %d %s %s" % (first + k, symbol, value))
        for k in range(len(uris)):
            wait(lambda: len(audio_ports("effect_%d" % (first + k), True)) == 2, "reference effect_%d's ports" % (first + k))
        for k in range(len(uris) - 1):
            for src, dst in zip(audio_ports("effect_%d" % (first + k), True), audio_ports("effect_%d" % (first + k + 1), False)):
                check(subprocess.run(["pw-link", src, dst]).returncode == 0, "link %s %s" % (src, dst))

    def close(self):
        self.proc.kill()
        self.proc.wait()


def play(arms, frames=24000, source=False):
    """end to end: one noise into each arm's head (both inputs), each arm's tail recorded, the same cycles; arms are
    (head client, tail client); returns the recordings' bytes, two per arm, and with source the noise of the same
    window and the graph's rate after them"""
    tmp = tempfile.mkdtemp(prefix="zyn-chain-play.")
    files = [os.path.join(tmp, "%d.%s" % (n, side)) for n in range(len(arms)) for side in "lr"]
    feeder = subprocess.Popen([os.environ["JACK_IDENTITY"], str(frames), "4", os.path.join(tmp, "source")] + files,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ready = []
    wait(lambda: ready.append(feeder.stdout.readline()) or ready[-1].startswith("ready"), "the feeder ready")
    recs = iter("abcdef")
    for head, tail in arms:
        for dst in audio_ports(head, False):
            check(subprocess.run(["pw-link", "identity-src:out", dst]).returncode == 0, "link the source to %s" % dst)
        for src in audio_ports(tail, True):
            check(subprocess.run(["pw-link", src, "identity-rec:" + next(recs)]).returncode == 0, "record %s" % src)
    time.sleep(0.5)
    feeder.stdin.write("go\n")
    feeder.stdin.flush()
    check(feeder.wait(60) == 0, "the feeder played and recorded: %s" % feeder.stdout.read())
    out = [open(f, "rb").read() for f in files]
    check(all(len(o) == frames * 4 for o in out), "every recording is %d frames" % frames)
    if source:
        # "ready rate=<rate> quantum=<frames>" (omx-clap-core tests/jack_identity.c)
        return out, open(os.path.join(tmp, "source"), "rb").read(), int(ready[-1].split("rate=")[1].split()[0])
    return out


def peak(b):
    import array
    return max(abs(x) for x in array.array("f", b))


def difference(x, y):
    """the largest difference of two recordings, frame by frame (no shift)"""
    import array
    a, b = array.array("f", x), array.array("f", y)
    return max(abs(a[i] - b[i]) for i in range(len(a)))


def compare(got, what, floor):
    """end to end: the chain's pair is the reference's within floor, the largest difference two references of one
    order show (x42's fil4 is not bit-exact from one instance to another), and the other order's is at least 40 dB
    above that floor; the numbers go in the line either way"""
    import math

    def db(v):
        return "bit for bit" if v == 0 else "%.3g, %.1f dBFS" % (v, 20 * math.log10(v))
    same = max(difference(got[0], got[2]), difference(got[1], got[3]))
    other = min(difference(got[0], got[4]), difference(got[1], got[5]))
    line = "%s: peak %.5f (reference %.5f, other order %.5f); against the reference %s; against the other order %s;" \
           " two references of one order %s" % (what, peak(got[0]), peak(got[2]), peak(got[4]), db(same), db(other),
                                                db(floor))
    print("     " + line, flush=True)
    check(same <= floor and other >= 100 * max(floor, 1e-9), line)


def audio_follows_the_read_back():
    """end to end: after an add at a position, then a move, the chain's output is the order chain_get reads back, the
    same plugins one client each in series bit for bit, and not the other order"""
    comp, pad = os.environ["CHAIN_COMP_URI"], os.environ["CHAIN_CLAP_URI"]
    r = rig()
    ref = reference()
    try:
        r.add("a", engine=lv2_engine)
        pad_p = r.add("pad")
        settle()
        k, w = chain_worker()
        os.environ["CHAIN_CLAP_URI"] = comp
        try:
            r.add("comp", slot=1)
        finally:
            os.environ["CHAIN_CLAP_URI"] = pad
        settle()
        check(read() == (k, [0, 2, 1], [0, 2, 1]) and chain_worker()[1]["pid"] == w["pid"],
              "comp joined at slot 1 in place: %s %s" % (read(), workers()))
        one_node("effect_0", "the chain of fil4, comp, pad")
        lv2 = os.environ["CHAIN_LV2_URI"]
        ref.series(20, [lv2, comp, pad])
        ref.series(30, [lv2, pad, comp])
        ref.series(40, [lv2, comp, pad])
        ref.series(50, [lv2, pad, comp])
        # the floor: two references of each order against each other, the same cycles
        ctl = play([("effect_20", "effect_22"), ("effect_40", "effect_42"), ("effect_30", "effect_32")])
        ctl2 = play([("effect_30", "effect_32"), ("effect_50", "effect_52"), ("effect_20", "effect_22")])
        floor = max(difference(ctl[0], ctl[2]), difference(ctl[1], ctl[3]), difference(ctl2[0], ctl2[2]),
                    difference(ctl2[1], ctl2[3]))
        check(floor <= 1e-5, "two references of one order agree within -100 dBFS: %.3g" % floor)
        got = play([("effect_0", "effect_0"), ("effect_20", "effect_22"), ("effect_30", "effect_32")])
        compare(got, "after the add, the chain plays fil4, comp, pad", floor)
        check(r.chain.nudge_processor(pad_p, True), "pad nudged up past comp")
        check(read() == (k, [0, 1, 2], [0, 1, 2]) and chain_worker()[1]["pid"] == w["pid"],
              "the move read back in place: %s %s" % (read(), workers()))
        got = play([("effect_0", "effect_0"), ("effect_30", "effect_32"), ("effect_20", "effect_22")])
        compare(got, "after the move, the chain plays fil4, pad, comp", floor)
    finally:
        ref.close()
        r.close()


def the_floor_is_chain_get():
    """a daemon without chain_get is never sent a chain line: the engine refuses by name and fakes no read-back. The
    members are two CLAP ones, one row, a line the old daemon would take: what keeps it from being declared is the
    floor, not a refusal of a mixed-row chain"""
    r = rig(exe=OLD)
    try:
        r.add("a"), r.add("b")
        check(not any(w["place"].startswith("chain:") for w in workers().values()), "no chain declared: %s" % workers())
        check(S.chains[1].refusal == "PLUGIND_CHAIN_GET_ABSENT", "the floor is named: %s" % S.chains[1].refusal)
        check(r.routes().get("effect_1") == ["effect_0"], "the processors routed one client each: %s" % r.routes())
    finally:
        r.close()


SCENARIOS = [series_order_add_at_position, removal_heals_and_replay_keeps_no_stale_member,
             move_by_nudge_is_one_chain_line, parallel_slot_is_refused_by_name_before_it_forms,
             a_foreign_processor_ends_the_chain_line, a_crashed_member_leaves_the_others_running,
             bypass_and_parameters_name_one_member, the_last_member_removed_clears_the_chain_read_back,
             a_daemon_gone_mid_command_leaves_no_lock_held, a_clean_close_before_any_reply_is_a_lost_daemon,
             a_restarted_daemon_is_reached_by_the_next_realisation]
if OLD:
    SCENARIOS.append(the_floor_is_chain_get)
if E2E and os.environ.get("JACK_IDENTITY"):
    SCENARIOS.append(audio_follows_the_read_back)

# ------------------------------------------------------------------------------
# Sabotage: each breaks one guard of the chain; the named scenario must go red
# ------------------------------------------------------------------------------


def patch(owner, name, value):
    orig = getattr(owner, name)
    setattr(owner, name, value(orig))
    return lambda: setattr(owner, name, orig)


def sab_reverse_run():
    return patch(S.plugind_chain, "members", lambda orig: lambda self, slots: (
        list(reversed(orig(self, slots)[0])), orig(self, slots)[1]))


def sab_no_shrink():
    def realise(orig):
        def f(self, slots, routes):
            run = self.members(slots)[0]
            ids = [p.engine.instance for p in run]
            if ids and set(ids) < set(self.declared):
                return self.routes(run, routes)   # a member left: the line is not sent again
            return orig(self, slots, routes)
        return f
    return patch(S.plugind_chain, "realise", realise)


def sab_no_move_past():
    return patch(S, "move_past", lambda orig: lambda slots, cur, up: None)


def sab_accept_all():
    return patch(S, "accepts", lambda orig: lambda chain, slots: True)


def sab_foreign_allowed():
    # the run of members passes over a foreign processor's slot instead of ending at it
    return patch(S.plugind_chain, "members", lambda orig: lambda self, slots: orig(
        self, [slot for slot in slots if S.is_plugind(slot[0])]))


def sab_refusals_only():
    # the hook catches the chain's refusals only: a lost daemon's error leaves rebuild_audio_graph holding the lock
    def realise_chain(orig):
        def f(chain, audio_routes):
            pc = S.chain_of(chain)
            try:
                with pc.lock:
                    return pc.realise(chain.audio_slots, audio_routes)
            except S.plugind_chain_refused:
                return audio_routes
        return f
    return patch(S, "realise_chain", realise_chain)


def sab_clear_unread():
    def realise(orig):
        def f(self, slots, routes):
            if self.declared and not self.members(slots)[0]:
                S.client().cmd("chain_clear %d" % self.id)   # the clear is not read back
                self.declared = self.running = []
                return routes
            return orig(self, slots, routes)
        return f
    return patch(S.plugind_chain, "realise", realise)


def sab_declared_head():
    def routes(orig):
        def f(self, run, audio_routes):
            running, self.running = self.running, list(self.declared)
            try:
                return orig(self, run, audio_routes)
            finally:
                self.running = running
        return f
    return patch(S.plugind_chain, "routes", routes)


def sab_no_readback():
    def read_back(orig):
        def f(self):
            self.running = list(self.declared)
        return f
    return patch(S.plugind_chain, "read_back", read_back)


def sab_split_as_running():
    def routes(orig):
        def f(self, run, audio_routes):
            running, self.running = self.running, self.running or list(self.declared)
            try:
                return orig(self, run, audio_routes)
            finally:
                self.running = running
        return f
    return patch(S.plugind_chain, "routes", routes)


def sab_bypass_as_param():
    def jalv_line(orig):
        def f(instance, cmd):
            if "=" in cmd and " " not in cmd:
                symbol, value = cmd.split("=", 1)
                return "param_set %s %s %s" % (instance, symbol, value)
            return orig(instance, cmd)
        return f
    return patch(S, "jalv_line", jalv_line)


def sab_fin_is_a_reply():
    # a FIN before any byte read as an empty reply: the daemon "predates the floor"
    def cmd(orig):
        def f(self, line):
            with self.lock:
                self.sock.sendall(line.encode() + b"\0")
                buf = b""
                while not buf.endswith(b"\0"):
                    data = self.sock.recv(65536)
                    if not data:
                        break
                    buf += data
            return buf.rstrip(b"\0").decode("utf-8", "replace")
        return f
    return patch(S.plugind_client, "cmd", cmd)


def sab_no_reconnect():
    # the client of a lost connection is kept: every later command raises
    return patch(S, "client", lambda orig: lambda: S._client if S._client is not None else orig())


def sab_fake_floor():
    return patch(S, "read_chain", lambda orig: lambda chain_id: None)


# (what the sabotage breaks, the sabotage, the scenario, the start of the message of the check it must trip): a
# scenario that goes red on another check, or on an error no check names, is the sabotage's own failure
SABOTAGE = [
    ("the chain line in reverse slot order", sab_reverse_run, series_order_add_at_position,
     "an LV2 and two CLAP members, read back"),
    ("a chain that lost a member is not declared again", sab_no_shrink, removal_heals_and_replay_keeps_no_stale_member,
     "the chain read back without b"),
    ("a split chain is routed as if its head ran every member", sab_split_as_running,
     removal_heals_and_replay_keeps_no_stale_member, "timed out: the split chain routed client by client"),
    ("a nudge merges two plugind slots as Zynthian's own", sab_no_move_past, move_by_nudge_is_one_chain_line,
     "the nudge of c up is accepted"),
    ("the nudge guard accepts every slot", sab_accept_all, parallel_slot_is_refused_by_name_before_it_forms,
     "the nudge that would form [a, jalv_x] answers False"),
    ("a foreign processor does not end the chain line", sab_foreign_allowed, a_foreign_processor_ends_the_chain_line,
     "the chain line ends before the foreign processor"),
    ("the routes follow the declared head, not the running one", sab_declared_head,
     a_crashed_member_leaves_the_others_running, "timed out: the routes follow the running head"),
    ("the running order is not read back", sab_no_readback, a_crashed_member_leaves_the_others_running,
     "timed out: the routes follow the running head"),
    ("the host bypass sent as a parameter", sab_bypass_as_param, bypass_and_parameters_name_one_member, "jalv line"),
    ("a cleared chain is not read back", sab_clear_unread, the_last_member_removed_clears_the_chain_read_back,
     "an unacted clear is named"),
    ("the hook lets a lost daemon's error through, the autoconnect lock held", sab_refusals_only,
     a_daemon_gone_mid_command_leaves_no_lock_held, "the autoconnect lock is taken again"),
]
SABOTAGE += [
    ("a FIN before any reply read as an empty reply", sab_fin_is_a_reply,
     a_clean_close_before_any_reply_is_a_lost_daemon, "the loss is named"),
    ("the client of a lost connection is kept", sab_no_reconnect, a_restarted_daemon_is_reached_by_the_next_realisation,
     "the next realisation succeeds"),
]
if OLD:
    SABOTAGE.append(("a daemon without chain_get read as one with no chain", sab_fake_floor, the_floor_is_chain_get,
                     "no chain declared"))


def run(fn):
    try:
        fn()
        return None
    except Exception as e:
        return e


def said(e):
    return "%s: %s" % (type(e).__name__, e)


def main():
    global S, CHAIN, PROC
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zui", required=True)
    ap.add_argument("--no-sabotage", action="store_true")
    a = ap.parse_args()
    S, CHAIN, PROC = setup(a.zui)
    failed = 0
    for fn in SCENARIOS:
        err = run(fn)
        print(("ok   " if err is None else "FAIL ") + fn.__name__ + ("" if err is None else ": " + said(err)), flush=True)
        failed += err is not None
    for what, sab, fn, expect in ([] if a.no_sabotage else SABOTAGE):
        restore = sab()
        try:
            err = run(fn)
        finally:
            restore()
        if err is None:
            verdict = "FAIL sabotage stayed green: "
        elif isinstance(err, Fail) and str(err).startswith(expect):
            verdict = "ok   sabotage red: "
        else:
            verdict = "FAIL sabotage red, not on \"%s\": " % expect
        print(verdict + "%s -> %s%s" % (what, fn.__name__, (" (" + said(err) + ")") if err else ""), flush=True)
        failed += not verdict.startswith("ok")
    print("CHAIN %s: %d failed" % ("PASS" if not failed else "FAIL", failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""A Zynthian chain of omx-plugins members, declared over the chain verb and played by the real omx-clap-host: the
values each member leaves on the audio, in the declared order, read back, after a removal and after a crash.

    test-chain-round-trip.py --zui <zynthian-ui checkout with zynthian_engine_plugind.patch applied>

Run by chain-e2e.sh --round-trip, in a PipeWire of its own. The rig is test-chain.py's: the real zynthian_chain,
zynthian_processor and zynthian_plugind_chain, plugin-hostd (PLUGIN_HOSTD) behind them with omx-clap-host (CLAP_HOST)
as its worker. The members are omx-plugins builds, as installed (OMX_CLAP_DIR, CHAIN_LV2_PATH):

    strip    CLAP omx-strip, Trim +12 dB, its compressor off       a gain of +12 dB, no delay
    limiter  CLAP omx-limiter, Ceiling -6 dBFS                     unity below the ceiling, its lookahead's delay
    delay    LV2  omx-delay on the adapter row, 10 ms, no feedback, a tap at 0 and one at 10 ms, each -6 dB
             mix 0.5

Each member's signature is measured alone, in a second omx-clap-host outside the daemon: the impulse response the
noise of tests/jack_identity leaves in its output, as taps (lag, gain). The chain's own signature is then read off the
chain's output and must be the members' in the declared order: the limiter after the strip clamps the noise the strip
raised, so of the six orders of the three only the declared one comes out of the limiter at the ceiling with the
delay's two taps after it. FAULT_CLAP_URI and CHAIN_FAULT_PARAM are the culprit of the crash (omx-clap-core's
tests/fault-14.clap, a gain of 0.1 that aborts on a write of 0.9 or more): not a member of omx-plugins, only what dies.

Each scenario must pass, then the scenario each sabotage names must fail on the check it names. Exit 0 when every
scenario passes and every sabotage turns its scenario red on that check.
"""
import argparse
import array
import importlib.util
import math
import operator
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("test_chain", os.path.join(HERE, "test-chain.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)
check, wait = tc.check, tc.wait

CLAP_DIR = os.environ.get("OMX_CLAP_DIR", "/usr/lib/clap")
TRIM_DB, CEILING_DB, DELAY_MS, MIX = 12.0, -6.0, 10, 0.5
# (uri, the parameters as Zynthian writes them: symbol=value, each said as param_set by the engine)
MEMBERS = {
    # parameter 1 trimDb, 40 compOn (omx-plugins plugins/omx-strip/generated/omx_strip_params.h)
    "strip": ("clap:%s/omx-strip.clap#org.openmixer.strip" % CLAP_DIR, [("1", TRIM_DB), ("40", 0)]),
    # parameter 0 ceilingDb
    "limiter": ("clap:%s/omx-limiter.clap#org.openmixer.limiter" % CLAP_DIR, [("0", CEILING_DB)]),
    "delay": ("lv2:urn:openmixer:delay", [("fxDelayTime", DELAY_MS), ("fxDelayFeedback", 0), ("mix", MIX)]),
}
DECLARED = ["strip", "limiter", "delay"]
# the orders that sound unlike the declared one: the delay before the limiter, the limiter first
OTHERS = [["strip", "delay", "limiter"], ["limiter", "strip", "delay"]]
LAGS = 1024


def member(name):
    uri = MEMBERS[name][0]
    return lambda n: tc.fake_engine(n, uri=uri)


def db(v):
    return 20 * math.log10(abs(v)) if v else -math.inf


def response(x, y):
    """the impulse response the white noise x leaves in y, lag by lag (y lags x)"""
    n = len(x) - LAGS
    xn = x[:n]
    xx = sum(map(operator.mul, xn, xn))
    return [sum(map(operator.mul, y[d:d + n], xn)) / xx for d in range(LAGS)]


def taps(x, y):
    """the response's taps: {lag: gain} for each lag at least a tenth of the largest"""
    h = response(x, y)
    top = max(abs(v) for v in h)
    return {d: v for d, v in enumerate(h) if abs(v) >= 0.1 * top}


def said(t):
    return "{%s}" % ", ".join("%d: %.4f (%.2f dB)" % (d, g, db(g)) for d, g in sorted(t.items()))


def signature(x, rec, what):
    """both channels' taps, which must agree in lag"""
    left, right = taps(x, array.array("f", rec[0])), taps(x, array.array("f", rec[1]))
    check(sorted(left) == sorted(right), "%s: the channels' taps differ: %s %s" % (what, said(left), said(right)))
    return left


def near(a, b, rel):
    return abs(a - b) <= rel * abs(b)


def params(names):
    return [[(s, v) for s, v in MEMBERS[n][1]] for n in names]


def write_params(proc, name):
    """as Zynthian writes a control: the jalv line the engine says to the daemon"""
    for symbol, value in MEMBERS[name][1]:
        line = tc.S.jalv_line(proc.engine.instance, "%s=%f" % (symbol, value))
        check(tc.S.resp_code(tc.S.client().cmd(line)) == 0, "%s: %s" % (name, line))


SIG = {}


def alone():
    """each member alone in the reference host, the same cycles: its signature, and the graph's rate"""
    if SIG:
        return SIG
    ref = tc.reference()
    try:
        for k, name in enumerate(DECLARED):
            ref.series(20 + k, [MEMBERS[name][0]], params([name]))
        got, src, rate = tc.play([("effect_%d" % (20 + k),) * 2 for k in range(3)], source=True)
    finally:
        ref.close()
    x = array.array("f", src)
    s = {name: signature(x, got[2 * k:2 * k + 2], name + " alone") for k, name in enumerate(DECLARED)}
    d = round(DELAY_MS * rate / 1000)
    print("     alone at %d Hz: strip %s, limiter %s, delay %s" % (rate, said(s["strip"]), said(s["limiter"]),
                                                                 said(s["delay"])), flush=True)
    # the oracle's own check: each signature is what its parameters say, before any chain is read with it
    check(list(s["strip"]) == [0] and abs(db(s["strip"][0]) - TRIM_DB) <= 0.05,
          "strip alone is +%.0f dB at lag 0: %s" % (TRIM_DB, said(s["strip"])))
    check(len(s["limiter"]) == 1 and list(s["limiter"])[0] > 0 and near(list(s["limiter"].values())[0], 1, 0.01),
          "limiter alone is unity, delayed, below its ceiling: %s" % said(s["limiter"]))
    check(sorted(s["delay"]) == [0, d] and all(near(g, MIX, 0.01) for g in s["delay"].values()),
          "delay alone taps 0 and %d (%d ms at %d Hz) at %.1f dB: %s" % (d, DELAY_MS, rate, db(MIX), said(s["delay"])))
    SIG.update(s, rate=rate, d=d, lookahead=list(s["limiter"])[0])
    return SIG


def one_node(want, what):
    """the daemon's nodes of the graph, effect_0 to effect_19 (the reference host's are effect_20 and up)"""
    def ours():
        return [n for n in tc.nodes() if int(n.split("_")[1]) < 20]
    wait(lambda: ours() == want, "%s: the nodes %s, have %s" % (what, want, ours()))


def chain_arm(r):
    """the chain's client as the engine routes it: what feeds Zynthian's output, and the chain's input with it"""
    out = r.routes().get("system:playback")
    check(out and len(out) == 1, "one client feeds the output: %s" % r.routes())
    return (out[0], out[0])


def floor_of(ref, first):
    """two references of the declared order, the same cycles: the largest difference between them"""
    ref.series(first, [MEMBERS[n][0] for n in DECLARED], params(DECLARED))
    ref.series(first + 10, [MEMBERS[n][0] for n in DECLARED], params(DECLARED))
    got = tc.play([("effect_%d" % first, "effect_%d" % (first + 2)), ("effect_%d" % (first + 10), "effect_%d" % (
        first + 12))])
    return max(tc.difference(got[0], got[2]), tc.difference(got[1], got[3]))


def plays_declared(r, ref, first, floor, what):
    """the chain's output against the declared order one client each (first), and against each other order: the
    declared one within floor, the others 40 dB above it; then its taps, the members' in order"""
    s = alone()
    arm = chain_arm(r)
    for k, order in enumerate(OTHERS):
        base = first + 20 + 10 * k
        ref.series(base, [MEMBERS[n][0] for n in order], params(order))
        got, src, _ = tc.play([arm, ("effect_%d" % first, "effect_%d" % (first + 2)),
                               ("effect_%d" % base, "effect_%d" % (base + 2))], source=True)
        tc.compare(got, "the chain plays %s (%s), against %s" % (", ".join(DECLARED), what, ", ".join(order)), floor)
    t = signature(array.array("f", src), got[0:2], what)
    lead, d = s["lookahead"], s["d"]
    ratio = s["delay"][d] / s["delay"][0]
    check(sorted(t) == [lead, lead + d], "the chain plays the limiter's lag %d and the delay's %d after it (%s): %s" % (
        lead, d, what, said(t)))
    check(near(t[lead + d] / t[lead], ratio, 0.02), "the chain plays the delay's tap ratio %.4f (%s): %s" % (
        ratio, what, said(t)))
    p = max(tc.peak(got[0]), tc.peak(got[1]))
    check(db(p) <= CEILING_DB + 0.01, "the chain plays at most the limiter's ceiling %.1f dBFS (%s): peak %.2f dBFS" % (
        CEILING_DB, what, db(p)))
    print("     %s: taps %s, peak %.2f dBFS" % (what, said(t), db(p)), flush=True)

# ------------------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------------------


def three_members_play_in_the_declared_order():
    alone()
    r = tc.rig()
    ref = tc.reference()
    try:
        procs = [r.add(n, engine=member(n)) for n in DECLARED]
        tc.settle()
        for p, n in zip(procs, DECLARED):
            write_params(p, n)
        floor = floor_of(ref, 30)
        check(floor <= 1e-5, "two references of one order agree within -100 dBFS: %.3g" % floor)
        plays_declared(r, ref, 30, floor, "as declared")
        k, w = tc.chain_worker()
        check(tc.read() == (k, [0, 1, 2], [0, 1, 2]), "chain_get reads back strip, limiter, delay: %s" % (tc.read(),))
        check(w["inst"] == [0, 1, 2] and w["fmt"] == "lv2-clap", "one worker on the adapter row: %s" % w)
        one_node(["effect_0"], "strip, limiter, delay")
    finally:
        ref.close()
        r.close()


def removing_the_limiter_re_forms_the_chain():
    s = alone()
    r = tc.rig()
    ref = tc.reference()
    try:
        procs = [r.add(n, engine=member(n)) for n in DECLARED]
        tc.settle()
        for p, n in zip(procs, DECLARED):
            write_params(p, n)
        k, w = tc.chain_worker()
        r.remove(procs[1])
        tc.settle()
        floor = floor_of(ref, 30)
        pair = ["strip", "delay"]
        ref.series(60, [MEMBERS[n][0] for n in pair], params(pair))
        ref.series(70, [MEMBERS[n][0] for n in DECLARED], params(DECLARED))
        got, src, _ = tc.play([chain_arm(r), ("effect_60", "effect_61"), ("effect_70", "effect_72")], source=True)
        tc.compare(got, "the re-formed chain plays strip, delay, against strip, limiter, delay", floor)
        t = signature(array.array("f", src), got[0:2], "after the removal")
        d, g = s["d"], s["strip"][0]
        want = {0: g * s["delay"][0], d: g * s["delay"][d]}
        check(sorted(t) == [0, d] and all(near(t[x], want[x], 0.005) for x in want),
              "the re-formed chain plays the strip's gain times the delay's taps, no lookahead: want %s, have %s" % (
                  said(want), said(t)))
        p = max(tc.peak(got[0]), tc.peak(got[1]))
        check(db(p) > CEILING_DB + 3, "no ceiling left on the re-formed chain: peak %.2f dBFS" % db(p))
        print("     after the removal: taps %s (want %s), peak %.2f dBFS" % (said(t), said(want), db(p)), flush=True)
        check(tc.read() == (k, [0, 2], [0, 2]), "chain_get reads back strip, delay: %s" % (tc.read(),))
        one_node(["effect_0"], "strip, delay")
        check(tc.where(1) is None, "the limiter is gone: %s" % tc.workers())
    finally:
        ref.close()
        r.close()


def a_crashed_member_leaves_the_three_playing():
    s = alone()
    r = tc.rig()
    ref = tc.reference()
    fault = os.environ["FAULT_CLAP_URI"]
    try:
        names = ["strip", "fault", "limiter", "delay"]
        procs = [r.add(n, engine=(lambda m: tc.fake_engine(m, uri=fault)) if n == "fault" else member(n))
                 for n in names]
        tc.settle()
        for p, n in zip(procs, names):
            if n != "fault":
                write_params(p, n)
        k, w = tc.chain_worker()
        check(tc.read() == (k, [0, 1, 2, 3], [0, 1, 2, 3]), "chain_get reads back the four: %s" % (tc.read(),))
        gain = float(tc.S.client().cmd("param_get 1 0").split()[2])
        got, src, _ = tc.play([chain_arm(r)], source=True)
        t = signature(array.array("f", src), got[0:2], "the four")
        lead, d = s["lookahead"], s["d"]
        # below the ceiling every member is linear: the taps are the product of the four
        want = {lead: s["strip"][0] * gain * s["delay"][0], lead + d: s["strip"][0] * gain * s["delay"][d]}
        check(sorted(t) == sorted(want) and all(near(t[x], want[x], 0.01) for x in want),
              "the four play strip x fault's %.2f x the limiter's lag x the delay's taps: want %s, have %s" % (
                  gain, said(want), said(t)))
        print("     the four, fault's gain %.2f: taps %s (want %s)" % (gain, said(t), said(want)), flush=True)
        # the fault plugin aborts on its write only once it has run its blocks (omx-clap-core tests/fault_clap.c)
        wait(lambda: float((tc.S.client().cmd("param_get 1 1").split() + ["0"] * 3)[2]) >= 200, "the fault plugin ran")
        tc.S.client().cmd(os.environ["CHAIN_FAULT_PARAM"] % 1)
        wait(lambda: tc.read()[2] == [0, 2, 3] and tc.chain_worker()[1]["state"] == "up", "the chain runs 0, 2, 3")
        check(tc.read()[1] == [0, 1, 2, 3], "the culprit keeps its declared place: %s" % (tc.read(),))
        check(tc.where(1)["place"] == "own", "the culprit runs alone: %s" % tc.workers())
        check(tc.S.client().cmd("instance_info 1").split()[6] == "1", "the culprit is quarantined")
        one_node(["effect_0", "effect_1"], "the chain one node, the culprit one")
        floor = floor_of(ref, 30)
        plays_declared(r, ref, 30, floor, "after the crash")
    finally:
        ref.close()
        r.close()


SCENARIOS = [three_members_play_in_the_declared_order, removing_the_limiter_re_forms_the_chain,
             a_crashed_member_leaves_the_three_playing]

# ------------------------------------------------------------------------------
# Sabotage: each breaks what the audio must show; the named scenario must go red on the check it names
# ------------------------------------------------------------------------------


def sab_reverse_run():
    return tc.patch(tc.S.plugind_chain, "members", lambda orig: lambda self, slots: (
        list(reversed(orig(self, slots)[0])), orig(self, slots)[1]))


def sab_last_left_out():
    return tc.patch(tc.S.plugind_chain, "members", lambda orig: lambda self, slots: (
        orig(self, slots)[0][:2], orig(self, slots)[1]))


def sab_not_re_formed():
    # the line is not sent again and the removed member's engine never stops: the daemon keeps the chain it had
    restore_line = tc.sab_no_shrink()
    restore_stop = tc.patch(tc.fake_engine, "stop", lambda orig: lambda self: None)
    return lambda: (restore_stop(), restore_line())


SABOTAGE = [
    ("the chain line in reverse slot order", sab_reverse_run, three_members_play_in_the_declared_order,
     "the chain plays"),
    ("the chain line without its last member", sab_last_left_out, three_members_play_in_the_declared_order,
     "the chain plays"),
    ("the chain not formed again after a removal", sab_not_re_formed, removing_the_limiter_re_forms_the_chain,
     "the re-formed chain plays"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zui", required=True)
    ap.add_argument("--no-sabotage", action="store_true")
    a = ap.parse_args()
    tc.S, tc.CHAIN, tc.PROC = tc.setup(a.zui)
    failed = 0
    for fn in SCENARIOS:
        err = tc.run(fn)
        print(("ok   " if err is None else "FAIL ") + fn.__name__ + ("" if err is None else ": " + tc.said(err)),
              flush=True)
        failed += err is not None
    for what, sab, fn, expect in ([] if a.no_sabotage else SABOTAGE):
        restore = sab()
        try:
            err = tc.run(fn)
        finally:
            restore()
        if err is None:
            verdict = "FAIL sabotage stayed green: "
        elif isinstance(err, tc.Fail) and str(err).startswith(expect):
            verdict = "ok   sabotage red: "
        else:
            verdict = "FAIL sabotage red, not on \"%s\": " % expect
        print(verdict + "%s -> %s%s" % (what, fn.__name__, (" (" + tc.said(err) + ")") if err else ""), flush=True)
        failed += not verdict.startswith("ok")
    print("ROUND TRIP %s: %d failed" % ("PASS" if not failed else "FAIL", failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

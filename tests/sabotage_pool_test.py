#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# The pool tests/sabotage.py runs its arms in (tests/sabotage_pool.py): what it prints is the table's order, its arms never
# share a tree, a port range or a jack server, and one run side by side prints what one run after another prints.
#
#   sabotage_pool_test.py [<test>]     one test by name, or all; the end-to-end one needs the checkout around this file
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sabotage_pool


def work_dir():
    return tempfile.mkdtemp(prefix="sabotage-pool-test.")


# the arms of these tests are module-level functions: the pool's processes are forks and find them by name
def slow_first(arm):
    started = time.time()
    time.sleep(arm["sleep"])
    return {"n": arm["n"], "start": started, "end": time.time()}


def own_tree(arm):
    tree = sabotage_pool.arm_tree(WORK, arm)
    os.makedirs(tree)
    with open(os.path.join(tree, "marker"), "w") as f:
        f.write(str(arm))
    time.sleep(0.2)     # long enough for every other arm to have written its own
    with open(os.path.join(tree, "marker")) as f:
        mine = f.read()
    return {"tree": tree, "wrote": arm, "read": int(mine), "files": sorted(os.listdir(tree)), "pid": os.getpid()}


def ports(arm):
    time.sleep(0.2)
    return {"base": int(os.environ["PLUGIN_HOSTD_TEST_PORT_BASE"]), "span": int(os.environ["PLUGIN_HOSTD_TEST_PORT_SPAN"]),
            "pid": os.getpid()}


def window(arm):
    started = time.time()
    time.sleep(0.15)
    return (started, time.time())


def boom(arm):
    if arm == 2:
        raise ValueError("arm 2")
    return arm


def run(arms, fn, jobs, **kw):
    got = []
    sabotage_pool.run(arms, fn, jobs, lambda arm, result: got.append((arm, result)), **kw)
    return got


def check(ok, what):
    if not ok:
        raise AssertionError(what)


def a_slow_arm_does_not_reorder_the_output():
    arms = [{"n": 0, "sleep": 0.8}, {"n": 1, "sleep": 0.0}, {"n": 2, "sleep": 0.0}, {"n": 3, "sleep": 0.1}]
    got = run(arms, slow_first, 4)
    check([r["n"] for _, r in got] == [0, 1, 2, 3], "emitted in the order of the table: %s" % [r["n"] for _, r in got])
    check([a["n"] for a, _ in got] == [0, 1, 2, 3], "each result with its own arm")
    done = sorted(got, key=lambda g: g[1]["end"])
    check(done[0][0]["n"] != 0 and done[-1][0]["n"] == 0,
          "the slow first arm finished last, so the run was side by side: %s" % [g[0]["n"] for g in done])
    check(got[1][1]["start"] < got[0][1]["end"], "arm 1 started before arm 0 was done")


def one_job_runs_one_after_the_other():
    got = run([{"n": n, "sleep": 0.05} for n in range(4)], slow_first, 1)
    check([r["n"] for _, r in got] == [0, 1, 2, 3], "in order")
    for (_, a), (_, b) in zip(got, got[1:]):
        check(a["end"] <= b["start"], "arm %d began before arm %d ended" % (b["n"], a["n"]))


def no_two_arms_share_a_tree():
    global WORK
    WORK = work_dir()
    try:
        got = run(list(range(12)), own_tree, 6)
        trees = [r["tree"] for _, r in got]
        check(len(set(trees)) == len(trees), "twelve arms, twelve trees: %s" % trees)
        check(all(os.path.dirname(t) == WORK for t in trees), "all under the work directory")
        for arm, r in got:
            check(r["wrote"] == r["read"] == arm, "arm %d read back what arm %d wrote" % (arm, r["read"]))
            check(r["files"] == ["marker"], "arm %d's tree holds %s" % (arm, r["files"]))
        check(len({r["pid"] for _, r in got}) > 1, "the arms ran in more than one process")
    finally:
        sabotage_pool.remove(WORK)


def the_tree_of_an_arm_is_named_by_its_place_in_the_table():
    check(sabotage_pool.arm_tree("/w", 7) != sabotage_pool.arm_tree("/w", 8), "two places, two trees")
    check(sabotage_pool.arm_tree("/w", 7) == sabotage_pool.arm_tree("/w", 7), "one place, one tree")
    check(os.path.dirname(sabotage_pool.arm_tree("/w", 7)) == "/w", "inside the work directory")


def arms_running_together_draw_their_ports_from_ranges_of_their_own():
    got = run(list(range(16)), ports, 8)
    ranges = {(r["base"], r["span"]) for _, r in got}
    check(len(ranges) == 8, "eight jobs, eight ranges: %s" % sorted(ranges))
    spans = sorted(ranges)
    for (b1, s1), (b2, _) in zip(spans, spans[1:]):
        check(b1 + s1 <= b2, "the ranges %d+%d and %d overlap" % (b1, s1, b2))
    check(spans[0][0] >= sabotage_pool.PORT_BASE and spans[-1][0] + spans[-1][1] <= 32768,
          "below the range the kernel hands out for bind(0)")
    per_process = {}
    for _, r in got:
        per_process.setdefault(r["pid"], set()).add(r["base"])
    check(all(len(v) == 1 for v in per_process.values()), "a process keeps its range")


def an_exclusive_arm_never_runs_beside_another_exclusive_arm():
    arms = list(range(8))
    got = run(arms, window, 8, exclusive=lambda arm: arm % 2 == 0)
    wins = sorted(r for arm, r in got if arm % 2 == 0)
    for (_, e1), (s2, _) in zip(wins, wins[1:]):
        check(e1 <= s2, "two exclusive arms overlapped: %s" % wins)
    others = sorted(r for arm, r in got if arm % 2)
    check(any(o[0] < w[1] and w[0] < o[1] for o in others for w in wins), "the others still ran beside them")


def an_arm_that_raises_ends_the_run_with_its_error():
    try:
        run(list(range(5)), boom, 2)
    except ValueError as e:
        check(str(e) == "arm 2", str(e))
        return
    raise AssertionError("the run went on past an arm that raised")


def the_number_of_jobs_is_the_cores_to_eight_or_what_is_asked():
    check(sabotage_pool.jobs_from({}, cpus=4) == 4, "four cores")
    check(sabotage_pool.jobs_from({}, cpus=24) == 8, "at most eight")
    check(sabotage_pool.jobs_from({}, cpus=1) == 1, "one core")
    check(sabotage_pool.jobs_from({"SABOTAGE_JOBS": "3"}, cpus=24) == 3, "asked for")
    check(sabotage_pool.jobs_from({"SABOTAGE_JOBS": "12"}, cpus=2) == 12, "asked for more than the cores")
    check(sabotage_pool.jobs_from({"SABOTAGE_JOBS": "100000"}, cpus=2) == sabotage_pool.MAX_JOBS, "the ports bound it")
    for bad in ("0", "-1", "many", ""):
        try:
            n = sabotage_pool.jobs_from({"SABOTAGE_JOBS": bad}, cpus=4)
        except SystemExit:
            check(bad != "", "an empty value is no value")
            continue
        check(bad == "" and n == 4, "'%s' gave %s" % (bad, n))


def side_by_side_prints_what_one_after_the_other_prints():
    """tests/sabotage.py itself, over the arms that need no build: the same lines, in the same order, either way"""
    if not os.path.exists(os.path.join(HERE, "sabotage.py")):
        print("skip side_by_side_prints_what_one_after_the_other_prints: no sabotage.py beside this file")
        return
    for kind in ("nopins", "ciguards"):
        outs = []
        for jobs in ("1", "6"):
            env = dict(os.environ, SABOTAGE_KIND=kind, SABOTAGE_JOBS=jobs)
            p = subprocess.run([sys.executable, os.path.join(HERE, "sabotage.py")], env=env, capture_output=True, text=True,
                               timeout=600)
            outs.append((p.returncode, p.stdout))
        check(outs[0] == outs[1], "%s: one job and six print differently:\n%s\n--\n%s" % (kind, outs[0], outs[1]))
        lines = outs[0][1].splitlines()
        check(outs[0][0] == 0 and lines[-1] == "sabotage ok", "%s: %s" % (kind, outs[0]))
        check(len(lines) > 1 and all(l.startswith("ok   sabotage caught: ") for l in lines[:-1]), "%s: %s" % (kind, lines))


def a_port_pair_inside_a_range_comes_from_that_range():
    if not os.path.exists(os.path.join(HERE, "harness.py")):
        print("skip a_port_pair_inside_a_range_comes_from_that_range: no harness.py beside this file")
        return
    env = dict(os.environ, PLUGIN_HOSTD_TEST_PORT_BASE="21000", PLUGIN_HOSTD_TEST_PORT_SPAN="50")
    p = subprocess.run([sys.executable, "-c", "import harness; print(*harness.port_pair())"], cwd=HERE, env=env,
                       capture_output=True, text=True, timeout=60)
    check(p.returncode == 0, p.stderr)
    a, b = map(int, p.stdout.split())
    check(a != b and 21000 <= a < 21050 and 21000 <= b < 21050, "ports %d %d" % (a, b))


TESTS = [a_slow_arm_does_not_reorder_the_output, one_job_runs_one_after_the_other, no_two_arms_share_a_tree,
         the_tree_of_an_arm_is_named_by_its_place_in_the_table,
         arms_running_together_draw_their_ports_from_ranges_of_their_own,
         an_exclusive_arm_never_runs_beside_another_exclusive_arm, an_arm_that_raises_ends_the_run_with_its_error,
         the_number_of_jobs_is_the_cores_to_eight_or_what_is_asked, side_by_side_prints_what_one_after_the_other_prints,
         a_port_pair_inside_a_range_comes_from_that_range]
WORK = None

if __name__ == "__main__":
    wanted = sys.argv[1:]
    chosen = [t for t in TESTS if not wanted or t.__name__ in wanted]
    if wanted and len(chosen) != len(wanted):
        sys.exit("no such test: %s" % wanted)
    failed = 0
    for t in chosen:
        try:
            t()
            print("ok   %s" % t.__name__)
        except Exception as e:
            print("FAIL %s: %s" % (t.__name__, e))
            failed += 1
    sys.exit(1 if failed else 0)

# SPDX-License-Identifier: GPL-3.0-or-later
# The probe runner (plugin-hostd-probe) against the stress plugin: a plugin that crashes, hangs or leaves a process behind
# in process() gives the named outcome, in a document that validates, and the whole tree is gone afterwards.
#   PROBE=<runner> PROBE_CHILD=<tests/probe-child> STRESS_CLAP=<tests/stress.clap> probe_test.py
# ONLY=<test name> runs one test (tests/sabotage.py turns each guard off and runs the test that must go red).
# PLUGIN_QUALIFY_BUILD=<a plugin-qualify checkout's native/build> also runs its real prober and lv2_measure over its own
# instrument fixtures; without it those tests say they skipped.
import json, os, resource, signal, subprocess, sys, tempfile, time

try:
    import jsonschema
except ImportError:
    sys.exit("the probe runner test needs python3-jsonschema (dnf install python3-jsonschema, apt install python3-jsonschema)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.abspath(os.environ.get("PROBE", os.path.join(ROOT, "plugin-hostd-probe")))
CHILD = os.path.abspath(os.environ.get("PROBE_CHILD", os.path.join(ROOT, "tests", "probe-child")))
CLAP = os.path.abspath(os.environ.get("STRESS_CLAP", os.path.join(ROOT, "tests", "stress.clap")))
SCHEMA = json.load(open(os.path.join(ROOT, "protocol", "probe-output.schema.json")))
ID = "org.plugin-hostd.test.stress"
ONLY = os.environ.get("ONLY")
failed = 0
tests = []


def test(fn):
    tests.append(fn)
    return fn


def check(cond, what):
    if not cond:
        raise AssertionError(what)


class Skip(Exception):
    """a test that cannot be taken here: it prints why and counts as neither ok nor failed"""


def run(fault=None, wall=5, extra=(), timeout=30, env=None, rates="48000", child=CHILD, prefix=()):
    """the runner over the stress plugin; returns (exit status, document or None, seconds, the files it used); rates None
    leaves the runner's default rates; prefix is a command the runner is started under (prlimit, setpriv)"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-test.")
    out = os.path.join(work, "probe.json")
    pidfile = os.path.join(work, "forkpid")
    e = dict(os.environ, STRESS_FORK_PIDFILE=pidfile, **(env or {}))
    if fault:
        e["STRESS_FAULT"] = fault
    else:
        e.pop("STRESS_FAULT", None)
    cmd = [*prefix, PROBE, "run", "--child", child, *(("--rates", rates) if rates else ()), "--quantum", "256", "--wall-s", str(wall),
           "--grace-ms", "200", "--log", os.path.join(work, "child.log"), "--out", out, *extra, CLAP, ID]
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_leftover(pidfile)
        raise AssertionError("the runner did not return within %d s" % timeout)
    took = time.monotonic() - start
    doc = json.load(open(out)) if os.path.exists(out) else None
    return p.returncode, doc, took, pidfile, p.stderr


def kill_leftover(pidfile):
    try:
        os.kill(int(open(pidfile).read()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


def floor_rates():
    """omx-contract's ORACLE_FLOOR_RATES, the rates a run measures at by default, read from the installed contract"""
    base = subprocess.run(["pkg-config", "--variable=contractdir", "omx-contract"], capture_output=True, text=True, check=True).stdout.strip()
    for major in sorted(os.listdir(base), reverse=True):
        rates = os.path.join(base, major, "omx-contract", "rates.json")
        if os.path.exists(rates):
            return json.load(open(rates))["ORACLE_FLOOR_RATES"]["values"]
    raise AssertionError("omx-contract declares no ORACLE_FLOOR_RATES")


def valid(doc):
    errors = [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)]
    check(not errors, "the document does not validate: %s" % errors[:3])


@test
def a_run_that_ends_well_is_a_complete_document():
    code, doc, _, pidfile, _ = run()
    check(code == 0, "exit status %d" % code)
    valid(doc)
    check(doc["run"]["outcome"] == "probe.ok" and doc["run"]["complete"], "outcome %s" % doc["run"]["outcome"])
    check([s["step"] for s in doc["steps"]] == ["hash", "instantiate", "latency", "lifecycle"], "steps %s" % [s["step"] for s in doc["steps"]])
    check(doc["binary"]["sha256"] == subprocess.run(["sha256sum", CLAP], capture_output=True, text=True).stdout.split()[0],
          "the binary is pinned by its own hash")


@test
def the_run_id_carries_no_host_name_and_the_runner_names_the_package_version():
    import re, socket
    code, doc, _, _, _ = run()
    rid = doc["run"]["id"]
    check(socket.gethostname() not in rid, "the run id %s carries the host name" % rid)
    check(re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]+-[0-9a-f]{8}", rid) is not None, "the run id %s is not utc-pid-random" % rid)
    want = re.search(r"^Version:\s*(\S+)", open(os.path.join(ROOT, "packaging/plugin-hostd.spec")).read(), re.M).group(1)
    check(doc["run"]["tools"]["runner"] == "plugin-hostd-probe " + want, "runner %s, package %s" % (doc["run"]["tools"]["runner"], want))


@test
def a_crash_keeps_the_steps_before_it():
    code, doc, _, _, _ = run("crash")
    check(code == 1, "exit status %d, a crash is 1" % code)
    check(doc is not None, "no document after a crash")
    valid(doc)
    steps = doc["steps"]
    check([s["step"] for s in steps] == ["hash", "instantiate", "latency", "lifecycle"], "steps %s" % [s["step"] for s in steps])
    check([s["outcome"] for s in steps[:3]] == ["probe.ok"] * 3, "the steps before the crash kept: %s" % steps)
    check(steps[3]["outcome"] == "probe.crashed" and steps[3]["signal"] == "SIGABRT", "the step it died in: %s" % steps[3])
    check(doc["run"]["outcome"] == "probe.crashed" and not doc["run"]["complete"], "the run: %s" % doc["run"])
    check(doc["crash"]["signal"] == "SIGABRT", "the crash block names the signal")


@test
def a_plugin_that_hangs_ends_at_the_wall_clock_and_the_tree_is_killed():
    code, doc, took, _, _ = run("hang", wall=2, timeout=20)
    check(code == 1, "exit status %d" % code)
    valid(doc)
    check(doc["run"]["outcome"] == "probe.timeout", "outcome %s" % doc["run"]["outcome"])
    check(took < 2 + 0.2 + 1.5, "ended in %.1f s, the deadline and the grace being 2.2 s" % took)
    check(doc["steps"][-1]["outcome"] == "probe.timeout" and "wall clock" in doc["steps"][-1]["detail"], "the step says why: %s" % doc["steps"][-1])


@test
def a_process_the_plugin_left_in_its_own_session_is_gone_after_the_run():
    code, doc, _, pidfile, _ = run("fork")
    try:
        check(os.path.exists(pidfile), "the stress plugin did not leave its process")
        pid = int(open(pidfile).read())
        time.sleep(0.2)
        check(not os.path.exists("/proc/%d" % pid), "pid %d, the plugin's own-session process, is still alive" % pid)
        check(code == 0, "exit status %d" % code)
        valid(doc)
        check("left behind were killed" in " ".join(s.get("detail", "") for s in doc["steps"]), "the document says it killed a leftover")
    finally:
        kill_leftover(pidfile)


@test
def every_limit_the_set_asks_for_is_applied_or_listed_unavailable():
    code, doc, _, _, _ = run()
    valid(doc)
    applied = {l["limit"]: l for l in doc["limits"]["applied"]}
    for name, by in (("wall-clock", "supervisor"), ("cpu-time", "rlimit"), ("memory", "rlimit"), ("files", "rlimit"),
                     ("file-size", "rlimit"), ("core-dump", "rlimit"), ("rt-priority", "rlimit"), ("no-new-privs", "prctl")):
        check(name in applied and applied[name]["by"] == by, "%s is applied by %s: %s" % (name, by, sorted(applied)))
    check({u["limit"]: u["code"] for u in doc["limits"]["unavailable"]} == {"tasks": "probe.limit.not-implemented"},
          "tasks is listed unavailable: %s" % doc["limits"]["unavailable"])


@test
def a_limit_that_was_required_and_is_not_applied_refuses_the_run_and_writes_no_document():
    code, doc, _, _, err = run(extra=("--require", "tasks"))
    check(code == 2, "exit status %d, a required limit that is unavailable is 2" % code)
    check(doc is None, "a document was written")
    code, doc, _, _, _ = run(extra=("--require", "memory"))
    check(code == 0 and doc is not None, "a required limit that is applied runs: %d" % code)


@test
def a_plugin_file_that_does_not_exist_is_3_and_has_no_document():
    p = subprocess.run([PROBE, "run", "--child", CHILD, "/nonexistent/none.clap"], capture_output=True, text=True)
    check(p.returncode == 3 and p.stdout == "", "exit %d, stdout %r" % (p.returncode, p.stdout))


@test
def the_limits_reach_the_child():
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-limits.")
    report = os.path.join(work, "limits.json")
    cpus = sorted(os.sched_getaffinity(0))[:1]
    code, doc, _, _, _ = run(extra=("--file-bytes", "4096", "--files", "64", "--cpu-s", "100", "--data-bytes", str(1 << 32),
                                    "--cpus", str(cpus[0])), env={"PROBE_CHILD_LIMITS": report})
    valid(doc)
    seen = json.load(open(report))
    rtprio = next(l["value"] for l in doc["limits"]["applied"] if l["limit"] == "rt-priority")
    want = {"fsize": 4096, "nofile": 64, "cpu": 100, "data": 1 << 32, "core": 0, "rtprio": rtprio, "no_new_privs": 1,
            "pdeathsig": signal.SIGKILL, "own_group": True, "cpus": 1}
    check({k: seen.get(k) for k in want} == want, "the child's own limits are %s, wanted %s" % (seen, want))
    check(doc["machine"]["pinnedCpus"] == str(cpus[0]), "pinnedCpus %s" % doc["machine"]["pinnedCpus"])


@test
def the_notes_an_instrument_holds_reach_the_clap_child():
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-argv.")
    seen = os.path.join(work, "argv")
    code, doc, _, _, _ = run(extra=("--probe-notes", "32", "--hold", "8"), env={"PROBE_CHILD_ARGV": seen})
    check(code == 0, "exit status %d" % code)
    args = open(seen).read().split("\n")
    check(args[args.index("--probe-notes") + 1] == "32" if "--probe-notes" in args else False, "--probe-notes 32 reached the child: %s" % args)
    check(args[args.index("--hold") + 1] == "8" if "--hold" in args else False, "--hold 8 reached the child: %s" % args)
    code, doc, _, _, _ = run(env={"PROBE_CHILD_ARGV": seen})
    args = open(seen).read().split("\n")
    check("--probe-notes" not in args and "--hold" not in args, "no count is given when none was asked for: %s" % args)
    for bad in ("0", "-3", "many"):
        p = subprocess.run([PROBE, "run", "--child", CHILD, "--probe-notes", bad, CLAP], capture_output=True, text=True)
        check(p.returncode == 2 and p.stdout == "", "--probe-notes %s is refused with no document: exit %d" % (bad, p.returncode))


@test
def every_point_carries_the_cost_timed_at_its_own_rate():
    rates = floor_rates()
    code, doc, _, _, _ = run(rates=None)
    check(code == 0, "exit status %d" % code)
    valid(doc)
    check([g["rate"] for g in doc["grid"]] == rates, "a point per rate of omx-contract's floor %s: %s" % (rates, doc["grid"]))
    for g in doc["grid"]:
        c = g.get("cost", {})
        want = {"unit": "ns-per-sample", "median": g["rate"] / 1000, "percentile": {"p": 95, "value": g["rate"] / 1000 + 1},
                "min": g["rate"] / 1000 - 1, "max": g["rate"] / 1000 + 4, "blocks": 256, "warmupBlocks": 64}
        check(c == want, "the point at %d carries the figures timed at %d, and no voices for an effect: %s" % (g["rate"], g["rate"], c))


@test
def a_cost_percentile_other_than_95_is_refused_naming_the_value_and_95_is_read_as_before():
    code, doc, _, _, err = run(env={"PROBE_CHILD_PERCENTILE": "99"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(all("cost" not in g for g in doc["grid"]), "no point carries a cost read from a 99th percentile: %s" % doc["grid"])
    steps = [s for s in doc["steps"] if s["step"] == "cost"]
    check(len(steps) == 1 and steps[0]["outcome"] == "probe.child-protocol" and "99" in steps[0].get("detail", ""),
          "one cost step, coded child-protocol, naming 99: %s" % doc["steps"])
    check(doc["run"]["outcome"] == "probe.child-protocol", "the run says so: %s" % doc["run"])
    code, doc, _, _, err = run(env={"PROBE_CHILD_PERCENTILE": "95"})
    check(all(g["cost"]["percentile"]["p"] == 95 for g in doc["grid"]) and doc["run"]["outcome"] == "probe.ok",
          "the 95th is read: %s" % doc["grid"])


@test
def a_latency_taken_from_a_note_says_so_and_whether_the_note_was_heard():
    rates = floor_rates()
    silent = rates[-1]
    code, doc, _, _, _ = run(rates=None, env={"PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_SILENT_RATE": str(silent)})
    valid(doc)
    for g in doc["grid"]:
        want = {"declaredFrames": 0, "measuredFrames": 1, "method": "note-onset", "heard": g["rate"] != silent}
        check(g["latency"] == want, "the point at %d: %s, wanted %s" % (g["rate"], g["latency"], want))
    code, doc, _, _, _ = run()
    check(doc["grid"][0]["latency"] == {"declaredFrames": 0, "measuredFrames": 0, "method": "impulse-onset"},
          "an effect's latency is an impulse's: %s" % doc["grid"][0]["latency"])

@test
def an_instrument_point_carries_the_notes_it_held_and_an_untimed_rate_has_no_cost():
    rates = floor_rates()
    untimed = rates[1]
    code, doc, _, _, _ = run(rates=None, extra=("--probe-notes", "32"),
                             env={"PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_UNMEASURED_RATE": str(untimed)})
    check(code == 0, "exit status %d" % code)
    valid(doc)
    check(doc["formatVersion"] == "1.2", "formatVersion %s" % doc["formatVersion"])
    check([g["rate"] for g in doc["grid"]] == rates, "a point per rate %s: %s" % (rates, [g["rate"] for g in doc["grid"]]))
    for g in doc["grid"]:
        if g["rate"] == untimed:
            check("cost" not in g, "the rate the child did not time has no cost, not a neighbour's: %s" % g)
            continue
        c = g.get("cost", {})
        check(c.get("median") == g["rate"] / 1000, "the point at %d carries its own median: %s" % (g["rate"], c))
        check(c.get("voices") == {"held": 32, "basis": "probe"}, "the point at %d carries the notes held: %s" % (g["rate"], c))
    code, doc, _, _, _ = run(env={"PROBE_CHILD_INSTRUMENT": "1"})
    valid(doc)
    check(all("cost" not in g for g in doc["grid"]), "an instrument with no count to hold has no cost: %s" % doc["grid"])
    code, doc, _, _, _ = run(extra=("--hold", "8"), env={"PROBE_CHILD_INSTRUMENT": "1"})
    valid(doc)
    check(doc["grid"][0]["cost"]["voices"] == {"held": 8, "basis": "probe"}, "--hold 8 is the count held: %s" % doc["grid"][0])

# ---------------------------------------------------------------- LV2: the runner drives lv2_measure's passes

LV2_CHILD = os.path.abspath(os.environ.get("PROBE_LV2_CHILD", os.path.join(ROOT, "tests", "lv2-probe-child")))
LV2_BUNDLES = os.path.abspath(os.environ.get("LV2_FIXTURE_DIR", os.path.join(ROOT, "tests")))
LV2_STRESS = "urn:plugin-hostd:test:stress"
REAL_LV2_MEASURE = "/usr/libexec/plugin-qualify/lv2_measure"


def run_lv2(fault=None, uri=LV2_STRESS, child=LV2_CHILD, wall=5, timeout=30, rates="48000,96000", env=None, bundles=LV2_BUNDLES):
    """the runner over the LV2 stress fixture with the fake lv2_measure (or the real one)"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-lv2.")
    out = os.path.join(work, "probe.json")
    pidfile = os.path.join(work, "forkpid")
    e = dict(os.environ, STRESS_FORK_PIDFILE=pidfile, LV2_PATH=bundles, **(env or {}))
    if fault:
        e["STRESS_FAULT"] = fault
    else:
        e.pop("STRESS_FAULT", None)
    cmd = [PROBE, "run", "--child", child, "--rates", rates, "--quantum", "256", "--wall-s", str(wall), "--grace-ms", "200",
           "--log", os.path.join(work, "child.log"), "--out", out, "lv2:" + uri]
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_leftover(pidfile)
        raise AssertionError("the runner did not return within %d s" % timeout)
    took = time.monotonic() - start
    doc = json.load(open(out)) if os.path.exists(out) else None
    return p.returncode, doc, took, pidfile, p.stderr


@test
def an_lv2_plugin_is_pinned_then_measured_at_the_highest_rate():
    code, doc, _, _, err = run_lv2()
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(code == 0 and doc["run"]["complete"] and doc["run"]["outcome"] == "probe.ok", "exit %d run %s" % (code, doc["run"]))
    check(doc["plugin"]["format"] == "lv2" and doc["plugin"]["id"] == LV2_STRESS, "plugin %s" % doc["plugin"])
    files = {f["path"] for f in doc["binary"]["files"]}
    check({"manifest.ttl", "plugin-hostd-fixture.so"} <= files, "the bundle's files are pinned: %s" % files)
    check(doc["binary"]["path"] == "plugin-hostd-fixture.so", "binary is the library: %s" % doc["binary"]["path"])
    check([s["step"] for s in doc["steps"]][:1] == ["hash"] and "rt-safety" in [s["step"] for s in doc["steps"]],
          "steps %s" % [s["step"] for s in doc["steps"]])
    check([(g["rate"], g["quantum"]) for g in doc["grid"]] == [(96000, 256)], "one point, the highest rate: %s" % doc["grid"])
    rt = doc["grid"][0]["rtSafety"]
    check(rt["blocks"] > 0 and "allocations" in rt and "locks" in rt and "syscalls" in rt, "rtSafety %s" % rt)
    check(doc["run"]["tools"].get("interposer") == "rt_interpose.so" and rt["interposer"],
          "measured under the interposer beside the child: %s %s" % (doc["run"]["tools"], rt))
    b = doc["behaviour"]
    check(b["lifecycle"]["cycles"] == b["lifecycle"]["instantiated"] > 0 and b["lifecycle"]["failed"] == 0, "lifecycle %s" % b)
    check("threads" in b and "required" in b["features"], "threads and features %s" % b)


@test
def an_lv2_point_carries_the_note_sweep_and_what_run_did_while_the_notes_played():
    code, doc, _, _, err = run_lv2(env={"PROBE_CHILD_NOTE_ALLOCATIONS": "7"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    ns = doc["grid"][0].get("noteSweep")
    check(ns == {"applicable": True, "dialect": "midi", "allocations": 7, "locks": 0, "syscalls": 0}, "noteSweep %s" % ns)
    code, doc, _, _, _ = run_lv2()
    valid(doc)
    check(doc["grid"][0].get("noteSweep") == {"applicable": False}, "an effect's sweep does not apply: %s" % doc["grid"][0])


@test
def an_lv2_point_carries_the_latency_and_cost_the_child_took():
    code, doc, _, _, err = run_lv2(env={"PROBE_CHILD_LATENCY": "480,483"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    point = doc["grid"][0]
    check(point["latency"] == {"declaredFrames": 480, "measuredFrames": 483, "method": "impulse-onset"}, "latency %s" % point)
    check(point["cost"]["median"] == 1.5 and point["cost"]["percentile"] == {"p": 95, "value": 2.5} and point["cost"]["blocks"] == 512
          and point["cost"]["warmupBlocks"] == 64, "cost %s" % point.get("cost"))
    steps = {s["step"]: s for s in doc["steps"]}
    check(steps["latency"]["outcome"] == "probe.ok" and steps["cost"]["outcome"] == "probe.ok", "steps %s" % doc["steps"])


@test
def an_lv2_latency_the_child_could_not_take_is_a_step_with_its_hosting_code_and_no_figure():
    code, doc, _, _, err = run_lv2(env={"PROBE_CHILD_LATENCY": "silent"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(doc["run"]["outcome"] == "probe.ok" and doc["run"]["complete"], "the run still ends well: %s" % doc["run"])
    check("latency" not in doc["grid"][0] and "cost" in doc["grid"][0], "no guessed latency: %s" % doc["grid"][0])
    step = [s for s in doc["steps"] if s["step"] == "latency"][0]
    check(step["outcome"] == "probe.not-attempted" and step["hostingCode"] == "hosting.latency.unmeasured"
          and step["detail"].startswith("silent-output: "), "step %s" % step)


@test
def an_lv2_child_that_prints_no_latency_gets_no_latency_step():
    code, doc, _, _, err = run_lv2()
    check(doc is not None, "no document: exit %d %s" % (code, err))
    check("latency" not in [s["step"] for s in doc["steps"]] and "latency" not in doc["grid"][0], "steps %s" % doc["steps"])


@test
def the_real_lv2_measure_latency_and_cost_reach_the_grid():
    build = pq("the_real_lv2_measure_latency_and_cost_reach_the_grid")
    if not build:
        return
    for kind, want in (("declared", {"declaredFrames": 960, "measuredFrames": 960}), ("undeclared", {"declaredFrames": 0, "measuredFrames": 883}),
                       ("misdeclared", {"declaredFrames": 128, "measuredFrames": 883})):
        code, doc, _, _, err = run_lv2(uri="urn:plugin-qualify:fixture:lv2-latency-" + kind, child=os.path.join(build, "lv2_measure"),
                                       wall=120, timeout=300, bundles=os.path.join(build, "fixtures", "lv2"))
        check(doc is not None, "%s: no document: exit %d %s" % (kind, code, err))
        valid(doc)
        point = doc["grid"][0]
        check(point["rate"] == 96000 and {k: point["latency"][k] for k in want} == want, "%s: %s" % (kind, point))
        check(point["cost"]["median"] > 0 and point["cost"]["blocks"] == 512, "%s cost %s" % (kind, point))
    code, doc, _, _, err = run_lv2(uri="urn:plugin-qualify:fixture:lv2-latency-mute", child=os.path.join(build, "lv2_measure"),
                                   wall=120, timeout=300, bundles=os.path.join(build, "fixtures", "lv2"))
    valid(doc)
    check("latency" not in doc["grid"][0], "a mute has no measured latency: %s" % doc["grid"][0])
    check(any(s["step"] == "latency" and s.get("hostingCode") == "hosting.latency.unmeasured" for s in doc["steps"]), "steps %s" % doc["steps"])


@test
def a_clap_point_carries_the_note_sweep_counts():
    code, doc, _, _, _ = run(extra=("--probe-notes", "4"), env={"PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_NOTE_ALLOCATIONS": "3"})
    valid(doc)
    ns = doc["grid"][0].get("noteSweep")
    check(ns == {"applicable": True, "dialect": "clap", "allocations": 3, "locks": 0, "syscalls": 0}, "noteSweep %s" % ns)

def child_alone(interposer=None):
    """a copy of the fake CLAP child in a directory of its own, with no interposer beside it, or with `interposer`
    (the bytes of a file named rt_interpose.so) beside it"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-alone.")
    child = os.path.join(work, "probe-child")
    with open(CHILD, "rb") as src, open(child, "wb") as dst:
        dst.write(src.read())
    os.chmod(child, 0o755)
    if interposer is not None:
        open(os.path.join(work, "rt_interpose.so"), "wb").write(interposer)
    return work, child


def step(doc, name):
    return next((s for s in doc["steps"] if s["step"] == name), None)


@test
def a_clap_child_runs_under_the_interposer_beside_it():
    code, doc, _, _, err = run(rates=None, extra=("--probe-notes", "4"),
                               env={"PROBE_CHILD_ALLOCATIONS": "5", "PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_NOTE_ALLOCATIONS": "3",
                                    "PROBE_CHILD_NO_RECORDS": "1"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(doc["run"]["tools"].get("interposer") == "rt_interpose.so", "the run names the interposer: %s" % doc["run"]["tools"])
    rt = doc["grid"][0].get("rtSafety", {})
    check(rt.get("interposer") is True and rt.get("allocations") == 5 and rt.get("locks") == 0 and rt.get("syscalls") == 0,
          "the first point carries the counts taken under the interposer: %s" % rt)
    ns = doc["grid"][0].get("noteSweep")
    check(ns == {"applicable": True, "dialect": "clap", "allocations": 3, "locks": 0, "syscalls": 0}, "noteSweep %s" % ns)
    for name in ("rt-safety", "note-sweep"):
        s = step(doc, name)
        check(s is not None and s["outcome"] == "probe.ok", "the %s step: %s" % (name, s))


@test
def a_bare_clap_child_is_found_on_path_and_runs_under_the_interposer_beside_it():
    code, doc, _, _, err = run(child=os.path.basename(CHILD), env={"PATH": os.path.dirname(CHILD) + ":" + os.environ.get("PATH", ""),
                                                                   "PROBE_CHILD_ALLOCATIONS": "2"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    check(doc["run"]["tools"].get("interposer") == "rt_interpose.so" and doc["grid"][0]["rtSafety"].get("allocations") == 2,
          "the child named by PATH counts under the interposer beside it: %s %s" % (doc["run"]["tools"], doc["grid"][0]))


@test
def a_clap_child_with_no_interposer_beside_it_is_unmeasured_and_says_why():
    work, child = child_alone()
    code, doc, _, _, err = run(child=child, extra=("--probe-notes", "4"),
                               env={"PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_NOTE_ALLOCATIONS": "3", "PROBE_CHILD_NO_RECORDS": "1"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check("interposer" not in doc["run"]["tools"], "no interposer is named: %s" % doc["run"]["tools"])
    check(doc["grid"][0].get("rtSafety") == {"interposer": False}, "no counts without the interposer: %s" % doc["grid"][0])
    check(doc["grid"][0].get("noteSweep") == {"applicable": True, "dialect": "clap"},
          "a note sweep the interposer did not count carries no counts, whatever the child printed: %s" % doc["grid"][0].get("noteSweep"))
    rt, ns = step(doc, "rt-safety"), step(doc, "note-sweep")
    why = "no rt_interpose.so beside the child in %s" % work
    check(rt is not None and rt["outcome"] == "probe.not-attempted" and rt.get("detail") == why, "the rt-safety step says why: %s" % rt)
    check(ns is not None and ns["outcome"] == "probe.not-attempted" and why in ns.get("detail", ""), "the note-sweep step says why: %s" % ns)


def child_env(path):
    return dict(l.split("=", 1) for l in open(path).read().split("\n") if "=" in l)


@test
def a_preload_the_runner_had_is_dropped_for_the_measurement_and_recorded():
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-env.")
    seen = os.path.join(work, "env")
    stub = os.path.join(os.path.dirname(CHILD), "rt_interpose.so")
    # a library the runner itself was started under, which is no interposer of the measurement
    foreign = CLAP
    code, doc, _, _, err = run(env={"LD_PRELOAD": foreign, "PROBE_CHILD_ENV": seen, "PROBE_CHILD_NO_RECORDS": "1"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(child_env(seen).get("LD_PRELOAD") == stub, "the measured child gets only the interposer: %s" % child_env(seen).get("LD_PRELOAD"))
    check(doc["run"]["tools"].get("droppedPreload") == foreign, "the run records the preload it dropped: %s" % doc["run"]["tools"])
    rt = step(doc, "rt-safety")
    check(rt is not None and rt["outcome"] == "probe.ok" and ("dropped LD_PRELOAD=%s for the measurement" % foreign) in rt.get("detail", ""),
          "the rt-safety step says what was dropped: %s" % rt)
    # with no interposer beside the child, the foreign preload is dropped all the same
    _, alone = child_alone()
    code, doc, _, _, err = run(child=alone, env={"LD_PRELOAD": foreign, "PROBE_CHILD_ENV": seen, "PROBE_CHILD_NO_RECORDS": "1"})
    check("LD_PRELOAD" not in child_env(seen), "a child with no interposer beside it gets no preload: %s" % child_env(seen).get("LD_PRELOAD"))
    check(doc["run"]["tools"].get("droppedPreload") == foreign and "dropped LD_PRELOAD" in step(doc, "rt-safety").get("detail", ""),
          "and the record says so: %s %s" % (doc["run"]["tools"], step(doc, "rt-safety")))
    # the interposer itself, already preloaded (as plugin-qualify starts the runner), is not dropped
    code, doc, _, _, err = run(env={"LD_PRELOAD": stub, "PROBE_CHILD_ENV": seen, "PROBE_CHILD_NO_RECORDS": "1"})
    check(child_env(seen).get("LD_PRELOAD") == stub and "droppedPreload" not in doc["run"]["tools"],
          "the interposer the child gets is not called dropped: %s" % doc["run"]["tools"])
    code, doc, _, _, err = run_lv2(env={"LD_PRELOAD": foreign})
    valid(doc)
    check(doc["run"]["tools"].get("droppedPreload") == foreign and "dropped LD_PRELOAD" in step(doc, "rt-safety").get("detail", ""),
          "an LV2 measurement records it too: %s %s" % (doc["run"]["tools"], step(doc, "rt-safety")))


@test
def an_interposer_that_does_not_load_is_not_named_and_the_record_says_so():
    work, child = child_alone(interposer=b"not a library\n")
    code, doc, _, _, err = run(child=child, env={"PROBE_CHILD_NO_RECORDS": "1"})
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check("interposer" not in doc["run"]["tools"], "an interposer that did not load is not named: %s" % doc["run"]["tools"])
    check(doc["grid"][0].get("rtSafety") == {"interposer": False}, "no counts: %s" % doc["grid"][0])
    rt = step(doc, "rt-safety")
    want = "%s/rt_interpose.so was preloaded and the child says no interposer was loaded" % work
    check(rt is not None and rt["outcome"] == "probe.not-attempted" and rt.get("detail") == want, "the rt-safety step: %s" % rt)


@test
def an_lv2_crash_keeps_the_pin_and_names_the_signal():
    code, doc, _, _, err = run_lv2("crash")
    check(doc is not None, "no document after a crash: %s" % err)
    valid(doc)
    check(code == 1, "exit status %d, a crash is 1" % code)
    steps = doc["steps"]
    check(steps[0]["step"] == "hash" and steps[0]["outcome"] == "probe.ok", "the pin pass before the crash is kept: %s" % steps)
    check(steps[-1]["outcome"] == "probe.crashed" and steps[-1]["signal"] == "SIGABRT", "the step it died in: %s" % steps[-1])
    check(doc["run"]["outcome"] == "probe.crashed" and not doc["run"]["complete"], "the run: %s" % doc["run"])
    check(doc["crash"]["signal"] == "SIGABRT", "the crash block names the signal")


@test
def an_lv2_plugin_that_hangs_ends_at_the_wall_clock():
    code, doc, took, _, _ = run_lv2("hang", wall=2, timeout=20)
    check(code == 1, "exit status %d" % code)
    valid(doc)
    check(doc["run"]["outcome"] == "probe.timeout", "outcome %s" % doc["run"]["outcome"])
    check(took < 2 + 0.2 + 1.5, "ended in %.1f s, the deadline and the grace being 2.2 s" % took)


@test
def a_process_an_lv2_plugin_left_in_its_own_session_is_gone_after_the_run():
    code, doc, _, pidfile, _ = run_lv2("fork")
    try:
        check(os.path.exists(pidfile), "the stress plugin did not leave its process")
        pid = int(open(pidfile).read())
        time.sleep(0.2)
        check(not os.path.exists("/proc/%d" % pid), "pid %d, the plugin's own-session process, is still alive" % pid)
        valid(doc)
        check("left behind were killed" in " ".join(s.get("detail", "") for s in doc["steps"]), "the document says it killed a leftover")
    finally:
        kill_leftover(pidfile)


@test
def an_lv2_plugin_no_bundle_holds_is_3_and_has_no_document():
    code, doc, _, _, _ = run_lv2(uri="urn:plugin-hostd:test:nowhere")
    check(code == 3 and doc is None, "exit %d, document %s" % (code, doc is not None))


@test
def an_lv2_plugin_of_which_nothing_is_pinned_is_refused_by_code_with_no_document():
    code, doc, _, _, err = run_lv2(uri=LV2_STRESS + "-unpinnable")
    check(code == 2 and doc is None, "exit %d, document %s" % (code, doc is not None))
    check("lv2:%s-unpinnable: probe.unpinnable: " % LV2_STRESS in err, "the refusal names its code: %r" % err)


@test
def the_real_lv2_measure_is_translated_when_it_is_installed():
    if not os.access(REAL_LV2_MEASURE, os.X_OK):
        print("skip the_real_lv2_measure_is_translated_when_it_is_installed: %s is not installed" % REAL_LV2_MEASURE)
        return
    code, doc, _, _, err = run_lv2(uri="urn:plugin-hostd:test:gain", child=REAL_LV2_MEASURE, wall=60, timeout=120)
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(doc["run"]["outcome"] == "probe.ok", "the gain fixture measures: %s %s" % (doc["run"], doc["steps"]))
    check(doc["binary"]["layout"]["scheme"] == "omx-layout/1", "the real child's layout pin is kept: %s" % doc["binary"])
    check(doc["grid"][0]["rtSafety"]["blocks"] > 0, "rtSafety %s" % doc["grid"])
    if os.path.exists(os.path.join(os.path.dirname(REAL_LV2_MEASURE), "rt_interpose.so")):
        check(doc["run"]["tools"].get("interposer") == "rt_interpose.so" and doc["grid"][0]["rtSafety"]["interposer"],
              "the measurement ran under plugin-qualify's interposer: %s %s" % (doc["run"]["tools"], doc["grid"][0]["rtSafety"]))


# ---------------------------------------------------------------- plugin-qualify's own prober and fixtures

PQ_BUILD = os.environ.get("PLUGIN_QUALIFY_BUILD")


def pq(what):
    """a file of the plugin-qualify build, or None (the test says it skipped) when no build is named"""
    if not PQ_BUILD:
        print("skip %s: PLUGIN_QUALIFY_BUILD names no plugin-qualify native/build" % what)
        return None
    return os.path.abspath(PQ_BUILD)


def run_pq_clap(build, plugin, extra=()):
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-pq.")
    out = os.path.join(work, "probe.json")
    p = subprocess.run([PROBE, "run", "--child", os.path.join(build, "clap-qualify"), "--quantum", "512", "--wall-s", "300",
                        "--out", out, *extra, os.path.join(build, "fixtures", plugin)], capture_output=True, text=True, timeout=600)
    return p.returncode, json.load(open(out)) if os.path.exists(out) else None, p.stderr


@test
def the_real_prober_times_an_instrument_holding_the_probe_notes_at_every_floor_rate():
    build = pq("the_real_prober_times_an_instrument_holding_the_probe_notes_at_every_floor_rate")
    if not build:
        return
    rates = floor_rates()
    code, doc, err = run_pq_clap(build, "synth.clap", ("--probe-notes", "32"))
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check([g["rate"] for g in doc["grid"]] == rates, "a point per floor rate %s: %s" % (rates, [g["rate"] for g in doc["grid"]]))
    for g in doc["grid"]:
        c = g.get("cost", {})
        check(c.get("voices") == {"held": 32, "basis": "probe"} and c.get("median", 0) > 0 and c.get("blocks", 0) > 0,
              "the point at %d carries the cost it was timed at, 32 notes held: %s" % (g["rate"], c))
        check(g["latency"].get("method") == "note-onset" and g["latency"].get("heard") is True,
              "the point at %d: a latency from a note that sounded: %s" % (g["rate"], g["latency"]))
    code, doc, err = run_pq_clap(build, "synth.clap")
    valid(doc)
    check(all("cost" not in g for g in doc["grid"]), "with no count to hold, no rate has a cost: %s" % doc["grid"])
    code, doc, err = run_pq_clap(build, "synth-voices.clap", ("--probe-notes", "32"))
    valid(doc)
    for g in doc["grid"]:
        v = g.get("cost", {}).get("voices", {})
        check(v.get("basis") == "declared" and v.get("held") == v.get("capacity"),
              "an instrument declaring its voices holds that many at %d: %s" % (g["rate"], v))


@test
def the_real_prober_counts_under_the_interposer_beside_it_at_every_floor_rate():
    build = pq("the_real_prober_counts_under_the_interposer_beside_it_at_every_floor_rate")
    if not build:
        return
    rates = floor_rates()
    seen = {}
    for plugin, extra in (("rt-safe.clap", ()), ("rt-unsafe.clap", ()), ("synth.clap", ("--probe-notes", "32")),
                          ("synth-alloc.clap", ("--probe-notes", "32"))):
        code, doc, err = run_pq_clap(build, plugin, extra)
        check(doc is not None, "%s: no document: exit %d %s" % (plugin, code, err))
        valid(doc)
        check([g["rate"] for g in doc["grid"]] == rates, "%s: a point per floor rate %s: %s" % (plugin, rates, [g["rate"] for g in doc["grid"]]))
        check(doc["run"]["tools"].get("interposer") == "rt_interpose.so", "%s: the run names the interposer: %s" % (plugin, doc["run"]["tools"]))
        rt = doc["grid"][0].get("rtSafety", {})
        check(rt.get("interposer") is True and rt.get("blocks", 0) > 0 and "allocations" in rt, "%s: rtSafety %s" % (plugin, rt))
        check(step(doc, "rt-safety")["outcome"] == "probe.ok", "%s: the rt-safety step %s" % (plugin, step(doc, "rt-safety")))
        seen[plugin] = (rt, doc["grid"][0].get("noteSweep", {}))
    check(seen["rt-safe.clap"][0]["allocations"] == 0, "the clean effect allocates nothing: %s" % (seen["rt-safe.clap"],))
    check(seen["rt-unsafe.clap"][0]["allocations"] > 0, "the allocating effect is counted: %s" % (seen["rt-unsafe.clap"],))
    for plugin in ("synth.clap", "synth-alloc.clap"):
        ns = seen[plugin][1]
        check(ns.get("applicable") is True and ns.get("dialect") == "clap" and "allocations" in ns, "%s noteSweep %s" % (plugin, ns))
    check(seen["synth.clap"][1]["allocations"] == 0, "the clean synth allocates nothing under the notes: %s" % (seen["synth.clap"],))
    check(seen["synth-alloc.clap"][1]["allocations"] > 0, "the allocating synth is counted under the notes: %s" % (seen["synth-alloc.clap"],))


@test
def the_real_lv2_measure_counts_what_run_does_while_notes_play():
    build = pq("the_real_lv2_measure_counts_what_run_does_while_notes_play")
    if not build:
        return
    seen = {}
    for uri in ("urn:plugin-qualify:fixture:lv2-synth-alloc", "urn:plugin-qualify:fixture:lv2-synth"):
        code, doc, _, _, err = run_lv2(uri=uri, child=os.path.join(build, "lv2_measure"), wall=120, timeout=300,
                                       bundles=os.path.join(build, "fixtures", "lv2"))
        check(doc is not None, "%s: no document: exit %d %s" % (uri, code, err))
        valid(doc)
        seen[uri] = doc["grid"][0].get("noteSweep", {})
        check(seen[uri].get("applicable") is True and seen[uri].get("dialect") == "midi", "%s noteSweep %s" % (uri, seen[uri]))
    check(seen["urn:plugin-qualify:fixture:lv2-synth-alloc"].get("allocations", 0) > 0, "the allocating synth: %s" % seen)
    check(seen["urn:plugin-qualify:fixture:lv2-synth"].get("allocations") == 0, "its clean twin: %s" % seen)


# ---------------------------------------------------------------- real time and the memory lock (#225)

# the lock preload of this checkout: a sabotage arm breaks the runner, never the preload
LOCK = os.path.abspath(os.environ.get("PROBE_LOCK", os.path.join(ROOT, "plugin-hostd-probe-lock.so")))
FIFO_MAX = os.sched_get_priority_max(os.SCHED_FIFO)


def cap_sys_nice():
    for l in open("/proc/self/status"):
        if l.startswith("CapEff:"):
            return bool(int(l.split()[1], 16) >> 23 & 1)
    return False


def without_cap():
    """the prefix that drops CAP_SYS_NICE from what the runner is started with, when this process holds it"""
    return ["setpriv", "--bounding-set", "-sys_nice", "--inh-caps", "-sys_nice"] if cap_sys_nice() else []


def kernel_grants(prefix, priority):
    """None when the kernel gives a process started with `prefix` SCHED_FIFO at `priority`, else why not"""
    p = subprocess.run([*prefix, "chrt", "-f", str(priority), "true"], capture_output=True, text=True)
    return None if p.returncode == 0 else (p.stderr.strip() or "chrt exited %d" % p.returncode)


def rt_run(prefix=(), extra=(), env=None):
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-rt.")
    seen = os.path.join(work, "limits.json")
    code, doc, _, _, err = run(extra=("--lock-preload", LOCK, *extra), env=dict(env or {}, PROBE_CHILD_LIMITS=seen), prefix=prefix)
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    return doc, (json.load(open(seen)) if os.path.exists(seen) else None)


def applied(doc, name):
    return next((l for l in doc["limits"]["applied"] if l["limit"] == name), None)


@test
def with_the_grant_the_measurement_runs_fifo_at_the_highest_priority():
    hard = resource.getrlimit(resource.RLIMIT_RTPRIO)[1]
    if not cap_sys_nice() and hard != resource.RLIM_INFINITY and hard < FIFO_MAX:
        raise Skip("no CAP_SYS_NICE and an RLIMIT_RTPRIO hard limit of %d, below %d; the rlimit arm measures the grant "
                   "there is" % (hard, FIFO_MAX))
    why = kernel_grants((), FIFO_MAX)
    if why:
        raise Skip("the kernel refuses SCHED_FIFO %d here (%s)" % (FIFO_MAX, why))
    doc, seen = rt_run()
    rt = doc["run"]["realtime"]
    check(rt["class"] == "fifo" and rt["priority"] == FIFO_MAX and rt["requested"] == FIFO_MAX
          and rt["grantedBy"] == ("cap" if cap_sys_nice() else "rlimit"), "run.realtime %s" % rt)
    check(rt["observed"] == {"policy": "fifo", "priority": FIFO_MAX}, "the kernel's word: %s" % rt.get("observed"))
    check(seen["policy"] == "fifo" and seen["priority"] == FIFO_MAX, "the child's own scheduler: %s" % seen)
    check(doc["offer"]["realtime"] == "fifo", "offer.realtime %s" % doc["offer"]["realtime"])


@test
def under_an_rtprio_rlimit_the_measurement_runs_fifo_at_the_rlimit_and_keeps_it_as_its_bound():
    hard = resource.getrlimit(resource.RLIMIT_RTPRIO)[1]
    n = min(10, FIFO_MAX - 1) if hard == resource.RLIM_INFINITY else min(10, hard, FIFO_MAX - 1)
    if n < 1:
        raise Skip("the RLIMIT_RTPRIO hard limit is 0, and only a privileged process can raise it")
    prefix = [*without_cap(), "prlimit", "--rtprio=%d:%d" % (n, n), "--"]
    why = kernel_grants(prefix, n)
    if why:
        raise Skip("the kernel refuses SCHED_FIFO %d under the rlimit here (%s)" % (n, why))
    doc, seen = rt_run(prefix)
    rt = doc["run"]["realtime"]
    check(rt == {"class": "fifo", "priority": n, "requested": FIFO_MAX, "grantedBy": "rlimit",
                 "observed": {"policy": "fifo", "priority": n}}, "run.realtime %s" % rt)
    check(seen["policy"] == "fifo" and seen["priority"] == n and seen["rtprio"] == n,
          "the child runs fifo %d bounded by RLIMIT_RTPRIO %d: %s" % (n, n, seen))
    check(applied(doc, "rt-priority") == {"limit": "rt-priority", "value": n, "by": "rlimit"},
          "the document lists the bound: %s" % applied(doc, "rt-priority"))


@test
def without_a_grant_the_measurement_stays_at_none_and_says_why():
    prefix = [*without_cap(), "prlimit", "--rtprio=0:0", "--"]
    doc, seen = rt_run(prefix)
    rt = doc["run"]["realtime"]
    check(rt["class"] == "none" and rt["priority"] == 0 and rt["grantedBy"] == "none" and rt["requested"] == FIFO_MAX,
          "run.realtime %s" % rt)
    check("RLIMIT_RTPRIO" in rt.get("reason", "") and "CAP_SYS_NICE" in rt["reason"], "the reason names the grant: %s" % rt)
    check(rt.get("observed") == {"policy": "other", "priority": 0}, "the kernel's word: %s" % rt.get("observed"))
    check(seen["policy"] == "other" and seen["rtprio"] == 0, "the child: %s" % seen)
    check(doc["offer"]["realtime"] == "none", "offer.realtime %s" % doc["offer"]["realtime"])


@test
def the_rt_time_bound_is_the_wall_budget():
    doc, seen = rt_run()
    check(seen["rttime"] == 5 * 1000000, "the child's RLIMIT_RTTIME is the 5 s wall budget in us: %s" % seen)
    check(applied(doc, "rt-time") == {"limit": "rt-time", "value": 5 * 1000000, "unit": "us", "by": "rlimit"},
          "the document lists it: %s" % applied(doc, "rt-time"))


@test
def a_grant_the_kernel_refuses_is_recorded_as_none_with_the_refusal():
    hard = resource.getrlimit(resource.RLIMIT_RTPRIO)[1]
    if not cap_sys_nice() and hard == 0:
        raise Skip("no grant here (no CAP_SYS_NICE, RLIMIT_RTPRIO hard limit 0), so nothing for the kernel to refuse")
    refuse = os.path.join(os.path.dirname(CHILD), "sched-refuse.so")
    doc, seen = rt_run(env={"LD_PRELOAD": refuse})
    rt = doc["run"]["realtime"]
    check(rt["class"] == "none" and rt["grantedBy"] == "none" and rt["priority"] == 0, "run.realtime %s" % rt)
    check("the kernel refused SCHED_FIFO" in rt.get("reason", "") and rt.get("observed") == {"policy": "other", "priority": 0},
          "the refusal and the kernel's word: %s" % rt)
    check(seen["policy"] == "other" and seen["rtprio"] == 0, "the child runs SCHED_OTHER with no rt bound: %s" % seen)
    check(applied(doc, "rt-priority")["value"] == 0, "the document's rt-priority: %s" % applied(doc, "rt-priority"))


@test
def an_lv2_measurement_is_scheduled_as_a_clap_one_is():
    clap, _ = rt_run()
    code, doc, _, _, err = run_lv2()
    check(doc is not None, "no document: exit %d %s" % (code, err))
    valid(doc)
    check(doc["run"]["realtime"] == clap["run"]["realtime"], "lv2 %s, clap %s" % (doc["run"]["realtime"], clap["run"]["realtime"]))


@test
def the_measured_child_locks_its_memory_or_the_record_says_why_not():
    data = 1 << 30
    hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)[1]
    if hard != resource.RLIM_INFINITY and hard < data:
        print("skip the locked arm of the_measured_child_locks_its_memory_or_the_record_says_why_not: RLIMIT_MEMLOCK %d is "
              "below %d" % (hard, data))
    else:
        env_file = os.path.join(tempfile.mkdtemp(prefix="plugin-hostd-probe-lock."), "env")
        doc, seen = rt_run(extra=("--data-bytes", str(data)), env={"PROBE_CHILD_ENV": env_file})
        check(doc["run"]["memoryLock"] == {"locked": True, "limitBytes": data}, "memoryLock %s" % doc["run"]["memoryLock"])
        check(seen["vmlck_kb"] > 0 and seen["memlock"] == data, "the child holds locked pages under its bound: %s" % seen)
        stub = os.path.join(os.path.dirname(CHILD), "rt_interpose.so")
        got = child_env(env_file)
        check(got.get("LD_PRELOAD") == stub + ":" + LOCK and "PLUGIN_HOSTD_PROBE_LOCK_FD" not in got,
              "the child gets the interposer and the lock preload, which takes its variable: %s" % got.get("LD_PRELOAD"))
    # a bound below the memory limit: no lock, which the record says
    doc, seen = rt_run(prefix=["prlimit", "--memlock=%d:%d" % (1 << 20, 1 << 20), "--"], extra=("--data-bytes", str(data)))
    ml = doc["run"]["memoryLock"]
    check(ml["locked"] is False and "RLIMIT_MEMLOCK" in ml.get("reason", "") and seen["vmlck_kb"] == 0, "memoryLock %s %s" % (ml, seen))
    # no preload: no lock, which the record says
    code, doc, _, _, err = run(extra=("--lock-preload", "/nonexistent/lock.so"))
    valid(doc)
    ml = doc["run"]["memoryLock"]
    check(ml["locked"] is False and "/nonexistent/lock.so" in ml.get("reason", ""), "memoryLock %s" % ml)


for t in tests:
    if ONLY and t.__name__ != ONLY:
        continue
    try:
        t()
        print("ok   " + t.__name__)
    except Skip as e:
        print("skip %s: %s" % (t.__name__, e))
    except AssertionError as e:
        print("FAIL %s: %s" % (t.__name__, e))
        failed += 1
print("plugin-hostd probe tests FAILED (%d)" % failed if failed else "plugin-hostd probe tests ok")
sys.exit(1 if failed else 0)

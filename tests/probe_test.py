# SPDX-License-Identifier: GPL-3.0-or-later
# The probe runner (plugin-hostd-probe) against the stress plugin: a plugin that crashes, hangs or leaves a process behind
# in process() gives the named outcome, in a document that validates, and the whole tree is gone afterwards.
#   PROBE=<runner> PROBE_CHILD=<tests/probe-child> STRESS_CLAP=<tests/stress.clap> probe_test.py
# ONLY=<test name> runs one test (tests/sabotage.py turns each guard off and runs the test that must go red).
import json, os, signal, subprocess, sys, tempfile, time

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


def run(fault=None, wall=5, extra=(), timeout=30, env=None, rates="48000"):
    """the runner over the stress plugin; returns (exit status, document or None, seconds, the files it used); rates None
    leaves the runner's default rates"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-test.")
    out = os.path.join(work, "probe.json")
    pidfile = os.path.join(work, "forkpid")
    e = dict(os.environ, STRESS_FORK_PIDFILE=pidfile, **(env or {}))
    if fault:
        e["STRESS_FAULT"] = fault
    else:
        e.pop("STRESS_FAULT", None)
    cmd = [PROBE, "run", "--child", CHILD, *(("--rates", rates) if rates else ()), "--quantum", "256", "--wall-s", str(wall),
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
    want = {"fsize": 4096, "nofile": 64, "cpu": 100, "data": 1 << 32, "core": 0, "rtprio": 0, "no_new_privs": 1,
            "pdeathsig": signal.SIGKILL, "own_group": True, "cpus": 1}
    check(seen == want, "the child's own limits are %s, wanted %s" % (seen, want))
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
def an_instrument_point_carries_the_notes_it_held_and_an_untimed_rate_has_no_cost():
    rates = floor_rates()
    untimed = rates[1]
    code, doc, _, _, _ = run(rates=None, extra=("--probe-notes", "32"),
                             env={"PROBE_CHILD_INSTRUMENT": "1", "PROBE_CHILD_UNMEASURED_RATE": str(untimed)})
    check(code == 0, "exit status %d" % code)
    valid(doc)
    check(doc["formatVersion"] == "1.1", "formatVersion %s" % doc["formatVersion"])
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


def run_lv2(fault=None, uri=LV2_STRESS, child=LV2_CHILD, wall=5, timeout=30, rates="48000,96000"):
    """the runner over the LV2 stress fixture with the fake lv2_measure (or the real one)"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-lv2.")
    out = os.path.join(work, "probe.json")
    pidfile = os.path.join(work, "forkpid")
    e = dict(os.environ, STRESS_FORK_PIDFILE=pidfile, LV2_PATH=LV2_BUNDLES)
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


for t in tests:
    if ONLY and t.__name__ != ONLY:
        continue
    try:
        t()
        print("ok   " + t.__name__)
    except AssertionError as e:
        print("FAIL %s: %s" % (t.__name__, e))
        failed += 1
print("plugin-hostd probe tests FAILED (%d)" % failed if failed else "plugin-hostd probe tests ok")
sys.exit(1 if failed else 0)

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


def run(fault=None, wall=5, extra=(), timeout=30, env=None):
    """the runner over the stress plugin; returns (exit status, document or None, seconds, the files it used)"""
    work = tempfile.mkdtemp(prefix="plugin-hostd-probe-test.")
    out = os.path.join(work, "probe.json")
    pidfile = os.path.join(work, "forkpid")
    e = dict(os.environ, STRESS_FORK_PIDFILE=pidfile, **(env or {}))
    if fault:
        e["STRESS_FAULT"] = fault
    else:
        e.pop("STRESS_FAULT", None)
    cmd = [PROBE, "run", "--child", CHILD, "--rates", "48000", "--quantum", "256", "--wall-s", str(wall), "--grace-ms", "200",
           "--log", os.path.join(work, "child.log"), "--out", out, *extra, CLAP, ID]
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

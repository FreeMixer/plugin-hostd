# The declaration is the one copy: change values in a scratch copy of include/plugin-hostd/protocol.h, regenerate,
import sys as _s; _s.stdout.reconfigure(line_buffering=True)
# rebuild, and the daemon's behaviour and the docs follow, with no other copy of an old value left in src/, the README
# or the man page. The same behaviour test runs on the tree as it is, so it reads every value from the declared JSON and
# spells none. Nothing but the scratch copy is edited.
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.path.abspath(os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))


def behave(exe, protocol):
    """the daemon's defaults, its reply codes, its pool name limit and its readiness line, as the declaration says"""
    os.environ["PLUGIN_HOSTD_PROTOCOL"] = protocol
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import harness
    from harness import Daemon, check, resp
    conf = {c["key"]: c["default"] for c in harness.DECLARED["config"]}
    placement = harness.DECLARED["placement"]

    # the pool holds pool_max instances, the next one opens a sibling
    d = Daemon(exe, FAKE)
    try:
        d.expect("policy_set lv2 %s" % (placement["pool_prefix"] + "x"), "resp 0")
        for i in range(conf["pool_max"]):
            d.expect("add fake:a %d default" % i, "resp %d" % i)
        check(len(d.workers()) == 1, "pool_max %d instances fit one worker: %s" % (conf["pool_max"], d.workers()))
        d.expect("add fake:a %d default" % conf["pool_max"], "resp %d" % conf["pool_max"])
        check(len(d.workers()) == 2, "the next opens a sibling: %s" % d.workers())
    finally:
        d.close()

    # storm_deaths deaths end respawning, and the refusal is the declared code
    d = Daemon(exe, FAKE)
    try:
        for _ in range(conf["storm_deaths"]):
            d.expect("add fake:crash_on_add 51", "resp -102")
        d.expect("add fake:crash_on_add 51", resp("GAVE_UP"))
    finally:
        d.close()

    # the pool name limit
    d = Daemon(exe, FAKE)
    try:
        longest = placement["pool_prefix"] + "a" * placement["pool_name"]["max"]
        d.expect("add fake:x 9 " + longest, "resp 9")
        d.expect("add fake:x 10 " + longest + "a", resp("PLACEMENT_INVALID"))
    finally:
        d.close()
    print("ok   behaviour follows the declaration: pool_max=%d storm_deaths=%d GAVE_UP=%d pool name max=%d ready=%r" % (
        conf["pool_max"], conf["storm_deaths"], harness.CODE["GAVE_UP"], placement["pool_name"]["max"], harness.READY_LINE))


def grep(pattern, *paths):
    p = subprocess.run(["grep", "-rnE", pattern] + list(paths), capture_output=True, text=True)
    return p.stdout.splitlines()


def make(tree, *args):
    return subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR] + list(args), cwd=tree, capture_output=True, text=True)


# (the definition in the header, the pattern to find it, its replacement, a pattern for an old copy that must be gone)
EDITS = [
    ("the suspect window default", r"(#define PHD_DEFAULT_SUSPECT_WINDOW_MS )500\b", r"\g<1>731", r"\b500\b"),
    ("the storm bound default", r"(#define PHD_DEFAULT_STORM_DEATHS +)5\b", r"\g<1>3", None),
    ("the pool size default", r"(#define PHD_DEFAULT_POOL_MAX +)8\b", r"\g<1>2", None),
    ("an error code", r"(#define PHD_ERR_GAVE_UP +)\(-505\)", r"\g<1>(-595)", r"\b505\b"),
    ("the pool name limit", r"(#define PHD_POOL_NAME_MAX )32\b", r"\g<1>5", None),
    ("the readiness line", r'(#define PHD_READY_LINE )"plugin-hostd ready!"', r'\g<1>"plugin-hostd is up!"', r"plugin.hostd ready!"),
]


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "behave":
        behave(sys.argv[2], sys.argv[3])
        return 0
    exe = os.path.join(ROOT, "plugin-hostd")
    subprocess.run([sys.executable, __file__, "behave", exe, os.path.join(ROOT, "protocol", "plugin-hostd.json")], check=True)

    work = tempfile.mkdtemp(prefix="plugin-hostd-perturbation.")
    try:
        tree = os.path.join(work, "t")
        os.mkdir(tree)
        for name in ("include", "src", "tools", "protocol", "doc", "packaging", "tests", "Makefile", "README.md"):
            src = os.path.join(ROOT, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tree, name))
        header = os.path.join(tree, "include", "plugin-hostd", "protocol.h")
        text = open(header).read()

        # positive control: the greps find the old values where they are declared and documented
        for what, pattern, _, old in EDITS:
            if old:
                found = grep(old, os.path.join(tree, "include"), os.path.join(tree, "README.md"), os.path.join(tree, "doc"))
                assert found, "control: the grep for the old value of %s finds nothing where it is declared" % what
        # and the generated files are current before anything is touched
        r = make(tree, "check-generated")
        assert r.returncode == 0, "the scratch copy is not current before the edit: " + r.stdout + r.stderr

        for what, pattern, repl, _ in EDITS:
            text, n = re.subn(pattern, repl, text)
            assert n == 1, "the edit of %s matched %d times" % (what, n)
        open(header, "w").write(text)

        # the guard: a header changed and not regenerated is drift
        r = make(tree, "check-generated")
        assert r.returncode != 0, "check-generated passed over a changed declaration"
        print("ok   check-generated fails on a changed declaration that was not regenerated")

        for target in ("gen", "check-generated", "plugin-hostd"):
            r = make(tree, target)
            assert r.returncode == 0, "make %s in the scratch copy: %s%s" % (target, r.stdout, r.stderr)

        for what, _, _, old in EDITS:
            if old:
                left = grep(old, os.path.join(tree, "src"), os.path.join(tree, "README.md"), os.path.join(tree, "doc"))
                assert not left, "a copy of the old value of %s remains:\n%s" % (what, "\n".join(left))
        for new in (r"\b731\b", r"\(?-595\b", "plugin-hostd is up!"):
            assert grep(new, os.path.join(tree, "README.md"), os.path.join(tree, "doc"), os.path.join(tree, "protocol")), \
                "the docs did not move to " + new
        print("ok   the docs moved and no copy of an old value remains in src/, README.md or the man page")

        subprocess.run([sys.executable, __file__, "behave", os.path.join(tree, "plugin-hostd"),
                        os.path.join(tree, "protocol", "plugin-hostd.json")], check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("perturbation ok")
    return 0


sys.exit(main())

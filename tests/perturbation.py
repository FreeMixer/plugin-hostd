# The declaration is the one copy: change values in a scratch copy of include/plugin-hostd/protocol.h, regenerate,
import sys as _s; _s.stdout.reconfigure(line_buffering=True)
# rebuild, and the daemon's behaviour and the docs follow, with no other copy of an old value left in src/, the README
# or the man page. The same behaviour test runs on the tree as it is, so it reads every value from the declared JSON and
# spells none. Then the same for mod-host's vocabulary: a verb renamed in a scratch copy of mod-host.h is the verb the
# daemon routes and the worker answers, and the old name is no command. Nothing but the scratch copies is edited.
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.path.abspath(os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))


def behave(exe, protocol, gone):
    """the daemon's defaults, its reply codes, its pool name limit, its readiness line and its verbs, as the declaration
    says; gone is a verb name the declaration does not have"""
    os.environ["PLUGIN_HOSTD_PROTOCOL"] = protocol
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import harness, modhost
    from harness import Daemon, check, resp
    conf = {c["key"]: c["default"] for c in harness.DECLARED["config"]}
    placement = harness.DECLARED["placement"]
    code = modhost.errors(modhost.include_dir(MOD_HOST_DIR))

    # the verb that takes an instance alone answers for it; the name the declaration does not have is no verb of the
    # daemon's, a mod-host command it broadcasts to no worker
    info = next(v["name"] for v in harness.DECLARED["verbs"] if v["arguments"] == "<instance>")
    d = Daemon(exe, FAKE)
    try:
        d.expect("%s 7" % info, "resp %d" % code["ERR_INSTANCE_NON_EXISTS"])
        d.expect("%s 7" % gone, "resp %d" % code["SUCCESS"])
    finally:
        d.close()

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
    print("ok   behaviour follows the declaration: pool_max=%d storm_deaths=%d GAVE_UP=%d pool name max=%d ready=%r "
          "verb=%s, not %s" % (conf["pool_max"], conf["storm_deaths"], harness.CODE["GAVE_UP"], placement["pool_name"]["max"],
                               harness.READY_LINE, info, gone))


def behave_modhost(exe, fake, include, gone):
    """an instance command of the mod-host.h in include is routed by its instance and answered by the worker under the
    verb the header declares; gone, the name it does not declare, is no command: broadcast, and a worker refuses it"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import harness, modhost
    from harness import Daemon
    verb = modhost.commands(include)[MODHOST_EDIT[0]]
    code = modhost.errors(include)
    add = next(v["name"] for v in harness.DECLARED["verbs"] if v["reply"] == "resp <instance>")
    d = Daemon(exe, fake)
    try:
        d.expect("%s 7 1" % verb, "resp %d" % code["ERR_INSTANCE_NON_EXISTS"])
        d.expect("%s 7 1" % gone, "resp %d" % code["SUCCESS"])
        d.expect("%s fake:a 0" % add, "resp 0")
        d.expect("%s 0 1" % verb, "resp %d" % code["SUCCESS"])
        d.expect("%s 0 1" % gone, "resp %d" % code["ERR_INVALID_OPERATION"])
    finally:
        d.close()
    print("ok   mod-host's verb follows mod-host.h: %s is routed by instance and answered, %s is no command" % (verb, gone))


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
    ("a verb", r'(#define PHD_VERB_INSTANCE_INFO +)"instance_info"', r'\g<1>"instance_where"', r"\binstance_info\b"),
]
# the verb the daemon has after the edit, and the one it has before, which the perturbed daemon must not have
VERB_AFTER, VERB_BEFORE = "instance_where", "instance_info"

# the command of mod-host.h renamed in the scratch copy of mod-host's headers, and the suffix that renames its verb
MODHOST_EDIT = ("EFFECT_BYPASS", "2")


def perturb_modhost():
    """mod-host's headers copied, one verb of mod-host.h renamed, the daemon and the worker rebuilt against the copy"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import modhost
    include = modhost.include_dir(MOD_HOST_DIR)
    macro, suffix = MODHOST_EDIT
    before = modhost.commands(include)[macro]
    after = before + suffix
    assert after not in modhost.commands(include).values(), "%s is already a command of mod-host.h" % after
    protocol = os.path.join(ROOT, "protocol", "plugin-hostd.json")

    subprocess.run([sys.executable, __file__, "behave-modhost", os.path.join(ROOT, "plugin-hostd"), FAKE, include, after],
                   check=True, env=dict(os.environ, PLUGIN_HOSTD_PROTOCOL=protocol))

    work = tempfile.mkdtemp(prefix="plugin-hostd-perturbation.")
    try:
        tree = os.path.join(work, "t")
        headers = os.path.join(work, "mod-host")
        os.mkdir(tree)
        for name in ("include", "src", "tests", "Makefile"):
            src = os.path.join(ROOT, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tree, name), ignore=shutil.ignore_patterns("*.o", "fake-host"))
            else:
                shutil.copy(src, os.path.join(tree, name))
        shutil.copytree(include, headers)
        header = os.path.join(headers, "mod-host.h")
        text, n = re.subn(r'(#define\s+%s\s+")%s\b' % (macro, before), r"\g<1>" + after, open(header).read())
        assert n == 1, "the edit of %s matched %d times" % (macro, n)
        open(header, "w").write(text)
        assert modhost.commands(headers)[macro] == after

        r = make(tree, "PROTOCOL_CFLAGS=-I" + headers, "plugin-hostd", "tests/fake-host")
        assert r.returncode == 0, "make against the perturbed mod-host.h: %s%s" % (r.stdout, r.stderr)
        subprocess.run([sys.executable, __file__, "behave-modhost", os.path.join(tree, "plugin-hostd"),
                        os.path.join(tree, "tests", "fake-host"), headers, before],
                       check=True, env=dict(os.environ, PLUGIN_HOSTD_PROTOCOL=protocol))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "behave":
        behave(*sys.argv[2:])
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == "behave-modhost":
        behave_modhost(*sys.argv[2:])
        return 0
    exe = os.path.join(ROOT, "plugin-hostd")
    subprocess.run([sys.executable, __file__, "behave", exe, os.path.join(ROOT, "protocol", "plugin-hostd.json"),
                    VERB_AFTER], check=True)

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
        for new in (r"\b731\b", r"\(?-595\b", "plugin-hostd is up!", r"\binstance_where\b"):
            assert grep(new, os.path.join(tree, "README.md"), os.path.join(tree, "doc"), os.path.join(tree, "protocol")), \
                "the docs did not move to " + new
        print("ok   the docs moved and no copy of an old value remains in src/, README.md or the man page")

        subprocess.run([sys.executable, __file__, "behave", os.path.join(tree, "plugin-hostd"),
                        os.path.join(tree, "protocol", "plugin-hostd.json"), VERB_BEFORE], check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    perturb_modhost()
    print("perturbation ok")
    return 0


sys.exit(main())

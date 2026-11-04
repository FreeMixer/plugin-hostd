# SPDX-License-Identifier: GPL-3.0-or-later
# The declaration is the one copy: change values in a scratch copy of plugin-hostd/protocol.h, and a verb in one of
# verbs.json, the daemon's verbs that omx-contract renders (both plugin-hostd-protocol's, copied from the installed
# library into a scratch tree, where -Iinclude finds them first), render and regenerate,
import sys as _s; _s.stdout.reconfigure(line_buffering=True)
# rebuild, and the daemon's behaviour and the docs follow, with no other copy of an old value left in src/, docs/guide.md
# or the man page. The protocol's JSON is written again by plugin-hostd-protocol's generator (its installed source),
# built against the scratch copy. The same behaviour test runs on the tree as it is, so it reads every value from the declared JSON and
# spells none. Then the same for mod-host's vocabulary: a verb renamed in a scratch copy of mod-host.h is the verb the
# daemon routes and the worker answers, and the old name is no command. Nothing but the scratch copies is edited.
import os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import declared

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOL_DIR = os.path.abspath(os.environ.get("PROTOCOL_DIR", os.path.join(ROOT, "..", "plugin-hostd-protocol")))
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
    code = modhost.errors(modhost.include_dir(PROTOCOL_DIR))

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
    return subprocess.run(["make", "-s", "PROTOCOL_DIR=" + PROTOCOL_DIR] + list(args), cwd=tree, capture_output=True, text=True)


# (the definition in the header, the pattern to find it, its replacement, a pattern for an old copy that must be gone)
EDITS = [
    ("the suspect window default", r"(#define PHD_DEFAULT_SUSPECT_WINDOW_MS )500\b", r"\g<1>731", r"\b500\b"),
    ("the storm bound default", r"(#define PHD_DEFAULT_STORM_DEATHS +)5\b", r"\g<1>3", None),
    ("the pool size default", r"(#define PHD_DEFAULT_POOL_MAX +)8\b", r"\g<1>2", None),
    ("the pool name limit", r"(#define PHD_POOL_NAME_MAX )32\b", r"\g<1>5", None),
    ("the readiness line", r'(#define PHD_READY_LINE )"plugin-hostd ready!"', r'\g<1>"plugin-hostd is up!"', r"plugin.hostd ready!"),
]
# a verb of the daemon is declared in verbs.json and rendered: (what, pattern, replacement, old) on that file
DATA_EDITS = [
    ("a verb", r'"instance_info( %i)?"', lambda m: '"instance_where%s"' % (m.group(1) or ""), r"\binstance_info\b"),
]
# a reply code's number is declared in verbs.json and rendered as OMX_REPLY_<CODE>_RESP, which the daemon, the README
# and the man page follow: (what, pattern, replacement, old) on that file, one match
CODE_EDITS = [
    ("an error code", r'("resp": )-505\b', r"\g<1>-595", r"\b505\b"),
]
# the verb the daemon has after the edit, and the one it has before, which the perturbed daemon must not have
VERB_AFTER, VERB_BEFORE = "instance_where", "instance_info"

# the command of mod-host.h renamed in the scratch copy of mod-host's headers, and the suffix that renames its verb
MODHOST_EDIT = ("EFFECT_BYPASS", "2")


def perturb_modhost():
    """mod-host's headers copied, one verb of mod-host.h renamed, the daemon and the worker rebuilt against the copy"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import modhost
    include = modhost.include_dir(PROTOCOL_DIR)
    macro, suffix = MODHOST_EDIT
    before = modhost.commands(include)[macro]
    after = before + suffix
    assert after not in modhost.commands(include).values(), "%s is already a command of mod-host.h" % after
    protocol = declared.variable("protocoljson")

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


def protocol_json(tree, out):
    """the protocol's JSON written by plugin-hostd-protocol's generator, built against the tree's copy of the headers"""
    gen = os.path.join(tree, "protocol-gen-json")
    cflags = subprocess.run(["pkg-config", "--cflags", "omx-contract"], capture_output=True, text=True).stdout.split()
    subprocess.run(["cc", "-std=gnu99", "-I" + os.path.join(tree, "include"), "-I" + declared.include_dir()] + cflags +
                   ["-o", gen, declared.variable("protocolgen")], check=True)
    with open(out, "w") as f:
        subprocess.run([gen, "json"], stdout=f, check=True)
    return out


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "behave":
        behave(*sys.argv[2:])
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == "behave-modhost":
        behave_modhost(*sys.argv[2:])
        return 0
    exe = os.path.join(ROOT, "plugin-hostd")
    subprocess.run([sys.executable, __file__, "behave", exe, declared.variable("protocoljson"), VERB_AFTER], check=True)

    work = tempfile.mkdtemp(prefix="plugin-hostd-perturbation.")
    try:
        tree = os.path.join(work, "t")
        os.mkdir(tree)
        for name in ("data", "include", "src", "tools", "protocol", "doc", "packaging", "tests", "docs", "Makefile"):
            src = os.path.join(ROOT, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tree, name),
                                                                       **({"ignore": shutil.ignore_patterns("*.o")} if os.path.isdir(src) else {}))
        # the declaration, plugin-hostd-protocol's: a copy of its headers and of its verbs.json in the scratch tree
        declared.overlay(tree)
        header = os.path.join(tree, "include", "plugin-hostd", "protocol.h")
        text = open(header).read()
        os.makedirs(os.path.join(tree, "protocol-data"))
        declaration = os.path.join(tree, "protocol-data", "verbs.json")
        shutil.copy(declared.verbs_json(), declaration)
        verbs = open(declaration).read()

        # positive control: the greps find the old values where they are declared and documented
        for what, pattern, _, old in EDITS + DATA_EDITS + CODE_EDITS:
            if old:
                found = grep(old, os.path.join(tree, "include"), os.path.join(tree, "docs", "guide.md"), os.path.join(tree, "doc"))
                assert found, "control: the grep for the old value of %s finds nothing where it is declared" % what
        # and the generated files are current before anything is touched: this tree's pages, and the JSON the copy
        # gives is the installed one
        r = make(tree, "check-generated")
        assert r.returncode == 0, "the scratch copy is not current before the edit: " + r.stdout + r.stderr
        before = protocol_json(tree, os.path.join(work, "before.json"))
        assert open(before).read() == open(declared.variable("protocoljson")).read(), \
            "control: the JSON the copy of the headers gives is not the installed one"

        for what, pattern, repl, _ in EDITS:
            text, n = re.subn(pattern, repl, text)
            assert n == 1, "the edit of %s matched %d times" % (what, n)
        open(header, "w").write(text)
        for what, pattern, repl, _ in DATA_EDITS:
            verbs, n = re.subn(pattern, repl, verbs)
            assert n == 2, "the edit of %s matched %d times, not its word and its format" % (what, n)
        for what, pattern, repl, _ in CODE_EDITS:
            verbs, n = re.subn(pattern, repl, verbs)
            assert n == 1, "the edit of %s matched %d times" % (what, n)
        open(declaration, "w").write(verbs)
        declared.render_overlay(tree, declaration)
        # the render names a verb's macro after its word, so a renamed verb renames its C name, which every reader of it
        # follows; a reader of the old name does not compile
        for base, _, files in os.walk(tree):
            for f in files:
                if f.endswith((".c", ".h")) and not f.startswith("plugin_hostd_"):
                    path = os.path.join(base, f)
                    old = open(path).read()
                    if "OMX_VERB_INSTANCE_INFO" in old:
                        open(path, "w").write(old.replace("OMX_VERB_INSTANCE_INFO", "OMX_VERB_INSTANCE_WHERE"))

        # the guard: a header changed and the pages not written again is drift
        r = make(tree, "check-generated")
        assert r.returncode != 0, "check-generated passed over a changed declaration"
        print("ok   check-generated fails on a changed declaration whose pages were not written again")

        for target in ("gen", "check-generated", "plugin-hostd"):
            r = make(tree, target)
            assert r.returncode == 0, "make %s in the scratch copy: %s%s" % (target, r.stdout, r.stderr)
        after = protocol_json(tree, os.path.join(tree, "protocol", "plugin-hostd.json"))

        for what, _, _, old in EDITS + DATA_EDITS + CODE_EDITS:
            if old:
                left = grep(old, os.path.join(tree, "src"), os.path.join(tree, "docs", "guide.md"), os.path.join(tree, "doc"))
                assert not left, "a copy of the old value of %s remains:\n%s" % (what, "\n".join(left))
        for new in (r"\b731\b", r"\(?-595\b", "plugin-hostd is up!", r"\binstance_where\b"):
            assert grep(new, os.path.join(tree, "docs", "guide.md"), os.path.join(tree, "doc"), after), \
                "the docs did not move to " + new
        print("ok   the docs moved and no copy of an old value remains in src/, docs/guide.md or the man page")

        subprocess.run([sys.executable, __file__, "behave", os.path.join(tree, "plugin-hostd"), after, VERB_BEFORE],
                       check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    perturb_modhost()
    print("perturbation ok")
    return 0


sys.exit(main())

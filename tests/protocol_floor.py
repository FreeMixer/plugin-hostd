#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# The plugin-hostd-protocol floor is one number. tools/protocol-floor.sh reads it from the spec; the spec's other lines
# and debian/control's, which can read no variable, are held equal to it here, and no workflow types one. And it is high
# enough: the sources use an OMX_VERB_* of the protocol's verb group that carries its own `since`, which is a release of
# plugin-hostd-protocol, so the floor is at or above the largest `since` of what they use. PLUGIN_HOSTD_VERBS is left
# out of that: its `since` counts plugin-hostd's releases, from before the protocol was a package of its own, and all of
# it is in the first one (0.2.0). A missing file is red.
# Usage: protocol_floor.py [root]. The check proves it sees each fault before it trusts the tree.
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import declared

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# a floor and a ceiling: (name >= floor with name < ceiling) in the spec, (>= floor~), (<< ceiling~) in debian/control
SPEC_LINE = re.compile(r"^(?:Build)?Requires:\s*\(\s*(plugin-hostd-protocol(?:-devel|-contract|%\{\?_isa\})?)\s*>=\s*(\S+)\s+with\s+\1\s*<\s*(\S+?)\s*\)\s*$", re.M)
SPEC_BARE = re.compile(r"^(?:Build)?Requires:\s*plugin-hostd-protocol\S*\s*[<>]?=?\s*\S+\s*$", re.M)
CONTROL_ITEM = re.compile(r"((?:lib)?plugin-hostd-protocol(?:0|-dev|-contract))\s*\(>=\s*([^)\s]+?)~?\)(?:\s*,\s*\1\s*\(<<\s*([^)\s]+?)~?\))?")
PC_LINE = re.compile(r"^Requires:.*\bplugin-hostd-protocol >= (\S+?),\s*plugin-hostd-protocol < (\S+?)(?:,|\s*$)", re.M)
# a package name with a typed version, in a workflow; the floor is read there, never typed
WORKFLOW_TYPED = re.compile(r"plugin-hostd-protocol\S*\s*(?:\(>=|>=)\s*\d|libplugin-hostd-protocol\S*\s*\\?\(>=\s*\d")
GROUP = "PLUGIN_HOSTD_PROTOCOL_VERBS"


def version(s):
    return tuple(int(x) for x in s.split("."))


def ceiling_of(floor):
    """below 1.0 the ceiling is the next minor"""
    a, b = version(floor)[:2]
    return "%d.%d" % (a, b + 1)


def macro(verb):
    return "OMX_VERB_" + verb.upper()


def group_since(verbs):
    """{macro of a verb of the group: the protocol release that first declares it}"""
    return {macro(v["verb"]): v["since"] for v in verbs[GROUP]["verbs"].values()}


def problems(floor, spec, control, workflows, sources, since, ceiling=None, pc=None):
    ceiling = ceiling or ceiling_of(floor)
    bad = []
    found = SPEC_LINE.findall(spec)
    lines = [f for _, f, _ in found]
    bad += ["packaging/plugin-hostd.spec: a protocol line with no ceiling: %s" % m.strip()
            for m in SPEC_BARE.findall(spec)]
    bad += ["packaging/plugin-hostd.spec: a ceiling of %s, the ceiling is %s" % (c, ceiling) for _, _, c in found if c != ceiling]
    if len(lines) < 5:
        bad.append("packaging/plugin-hostd.spec: %d plugin-hostd-protocol floors, the build and each package's are 5" % len(lines))
    bad += ["packaging/plugin-hostd.spec: a floor of %s, the floor is %s" % (x, floor) for x in lines if x != floor]
    cfound = CONTROL_ITEM.findall(control)
    items = [f for _, f, _ in cfound]
    if len(items) < 5:
        bad.append("debian/control: %d plugin-hostd-protocol floors, the build and each package's are 5" % len(items))
    bad += ["debian/control: a floor of %s, the floor is %s" % (x, floor) for x in items if x != floor]
    bad += ["debian/control: %s (>= %s~) has no (<< %s~)" % (n, f, ceiling) for n, f, c in cfound if not c]
    bad += ["debian/control: a ceiling of %s, the ceiling is %s" % (c, ceiling) for _, _, c in cfound if c and c != ceiling]
    if pc is not None:
        m = PC_LINE.search(pc)
        if not m:
            bad.append("protocol/plugin-hostd.pc.in: no 'plugin-hostd-protocol >= floor, plugin-hostd-protocol < ceiling'")
        elif (m.group(1), m.group(2)) != (floor, ceiling):
            bad.append("protocol/plugin-hostd.pc.in: %s..%s, the floor and ceiling are %s..%s" % (m.group(1), m.group(2), floor, ceiling))
    for name, text in workflows.items():
        for n, line in enumerate(text.splitlines(), 1):
            if WORKFLOW_TYPED.search(line):
                bad.append("%s:%d: a typed protocol floor; read it with tools/protocol-floor.sh: %s" % (name, n, line.strip()))
    for sym, first in sorted(since.items()):
        users = [name for name, text in sources.items() if re.search(r"\b%s\b" % sym, text)]
        if users and version(floor) < version(first):
            bad.append("%s uses %s, first declared by plugin-hostd-protocol %s: the floor %s is below it"
                       % (users[0], sym, first, floor))
    return bad


def text_of(path):
    with open(path) as f:
        return f.read()


def tree_files(sub, suffixes):
    d = os.path.join(ROOT, sub)
    return {os.path.join(sub, f): text_of(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(suffixes)}


SPEC_OK = "".join("%s: (plugin-hostd-protocol%s >= 0.3.0 with plugin-hostd-protocol%s < 0.4)\n" % (k, s, s) for k, s in
                  (("BuildRequires", "-devel"), ("BuildRequires", "-contract"), ("Requires", "%{?_isa}"),
                   ("Requires", "-devel"), ("Requires", "-contract")))
CTL_OK = ("Build-Depends: libplugin-hostd-protocol-dev (>= 0.3.0~), libplugin-hostd-protocol-dev (<< 0.4~),\n"
          " plugin-hostd-protocol-contract (>= 0.3.0~), plugin-hostd-protocol-contract (<< 0.4~) <!nocheck>\n"
          "Depends: libplugin-hostd-protocol0 (>= 0.3.0~), libplugin-hostd-protocol0 (<< 0.4~)\n"
          "Depends: libplugin-hostd-protocol-dev (>= 0.3.0~), libplugin-hostd-protocol-dev (<< 0.4~)\n"
          "Depends: plugin-hostd-protocol-contract (>= 0.3.0~), plugin-hostd-protocol-contract (<< 0.4~)\n")
PC_OK = "Requires: plugin-hostd-protocol >= 0.3.0, plugin-hostd-protocol < 0.4, libcrypto\n"
WORKFLOW_OK = {"ci.yml": 'floor=$(tools/protocol-floor.sh)\ndnf install "plugin-hostd-protocol-devel >= $floor"\n'}
SRC_OK = {"src/verbs.c": "strcmp(verb, OMX_VERB_HELLO)\n"}
SINCE = {"OMX_VERB_HELLO": "0.3.0", "OMX_VERB_PARAM_SET_MANY": "0.3.0"}


def main():
    # the check sees each fault before it is trusted: (what, floor, spec, control, workflows, sources, findings)
    arms = [
        ("the tree as written", "0.3.0", SPEC_OK, CTL_OK, WORKFLOW_OK, SRC_OK, 0),
        ("a low floor everywhere", "0.2.0", SPEC_OK.replace("0.3.0", "0.2.0"), CTL_OK.replace("0.3.0", "0.2.0"), WORKFLOW_OK, SRC_OK, 1),
        ("one low line in the spec", "0.3.0", SPEC_OK.replace("0.3.0", "0.2.0", 1), CTL_OK, WORKFLOW_OK, SRC_OK, 1),
        ("a floor line gone from the spec", "0.3.0", SPEC_OK.split("\n", 1)[1], CTL_OK, WORKFLOW_OK, SRC_OK, 1),
        ("one low item in debian/control", "0.3.0", SPEC_OK, CTL_OK.replace("0.3.0", "0.2.0", 1), WORKFLOW_OK, SRC_OK, 1),
        ("an item gone from debian/control", "0.3.0", SPEC_OK, CTL_OK.split("\n", 1)[1], WORKFLOW_OK, SRC_OK, 1),
        ("a floor typed in a workflow", "0.3.0", SPEC_OK, CTL_OK, {"ci.yml": "dnf install 'plugin-hostd-protocol-contract >= 0.3.0'\n"}, SRC_OK, 1),
        ("a verb past the floor, used", "0.2.0", SPEC_OK.replace("0.3.0", "0.2.0"), CTL_OK.replace("0.3.0", "0.2.0"), WORKFLOW_OK,
         {"src/supervisor.c": "OMX_VERB_PARAM_SET_MANY\n"}, 1),
        ("a verb past the floor, not used", "0.2.0", SPEC_OK.replace("0.3.0", "0.2.0"), CTL_OK.replace("0.3.0", "0.2.0"), WORKFLOW_OK,
         {"src/verbs.c": "OMX_VERB_PARAM_SET_MANYFOLD\n"}, 0),
        ("no ceiling in one spec line", "0.3.0", SPEC_OK.replace(" with plugin-hostd-protocol-devel < 0.4", "", 1).replace("(plugin-hostd-protocol-devel >= 0.3.0)", "plugin-hostd-protocol-devel >= 0.3.0"), CTL_OK, WORKFLOW_OK, SRC_OK, 2),
        ("a wide ceiling in the spec", "0.3.0", SPEC_OK.replace("< 0.4", "< 0.5", 1), CTL_OK, WORKFLOW_OK, SRC_OK, 1),
        ("no ceiling in one debian/control item", "0.3.0", SPEC_OK, CTL_OK.replace(", libplugin-hostd-protocol0 (<< 0.4~)", ""), WORKFLOW_OK, SRC_OK, 1),
        ("a wide ceiling in debian/control", "0.3.0", SPEC_OK, CTL_OK.replace("<< 0.4~", "<< 1~", 1), WORKFLOW_OK, SRC_OK, 1),
    ]
    for what, floor, spec, ctl, wf, src, want in arms:
        got = problems(floor, spec, ctl, wf, src, SINCE, "0.4", PC_OK.replace("0.3.0", floor))
        if len(got) != want:
            print("FAIL the floor check on %s: want %d findings, got %s" % (what, want, got))
            return 1
    print("ok   the floor check sees a low, a missing and a typed protocol floor, a missing or wide ceiling, and a verb past the floor")

    spec_path = os.path.join(ROOT, "packaging", "plugin-hostd.spec")
    p = subprocess.run([os.path.join(ROOT, "tools", "protocol-floor.sh"), spec_path], capture_output=True, text=True)
    if p.returncode != 0:
        print("FAIL " + p.stderr.strip())
        return 1
    floor = p.stdout.strip()
    p = subprocess.run([os.path.join(ROOT, "tools", "protocol-ceiling.sh"), spec_path], capture_output=True, text=True)
    if p.returncode != 0:
        print("FAIL " + p.stderr.strip())
        return 1
    ceiling = p.stdout.strip()
    since = group_since(json.loads(text_of(declared.verbs_json())))
    sources = tree_files("src", (".c", ".h"))
    bad = problems(floor, text_of(spec_path), text_of(os.path.join(ROOT, "debian", "control")),
                   tree_files(os.path.join(".github", "workflows"), (".yml",)), sources, since, ceiling,
                   text_of(os.path.join(ROOT, "protocol", "plugin-hostd.pc.in")))
    for b in bad:
        print("FAIL %s" % b)
    if bad:
        return 1
    used = sorted(s for s in since if any(re.search(r"\b%s\b" % s, t) for t in sources.values()))
    print("ok   the protocol floor is %s and the ceiling %s everywhere, at or above what the sources use of %s (%s)" % (floor, ceiling, GROUP, ", ".join(used)))
    return 0


sys.exit(main())

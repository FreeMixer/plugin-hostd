#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# omx-clap-core is a dependency with a floor and a ceiling wherever it is declared: its packages omx-clap-core-contract,
# omx-clap-host-tests (the check stage) and omx-clap-host (recommended), each at its floor and below the next minor of
# omx-clap-core, 0.30. A floor with no ceiling, a ceiling other than 0.30 and a declaration that is gone are red.
# Usage: clap_core_floor.py [root]. The check proves it sees each fault before it trusts the tree.
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CEILING = "0.30"
# package: (floor, declarations in the spec, declarations in debian/control)
WANT = {"omx-clap-core-contract": ("0.26.2", 2, 2), "omx-clap-host-tests": ("0.25.0", 1, 1), "omx-clap-host": ("0.29.0", 1, 1)}


def problems(spec, control):
    bad = []
    for pkg, (floor, n_spec, n_ctl) in WANT.items():
        q = re.escape(pkg)
        rich = re.findall(r"^(?:Build)?(?:Requires|Recommends):\s*\(\s*%s\s*>=\s*(\S+)\s+with\s+%s\s*<\s*(\S+?)\s*\)\s*$" % (q, q), spec, re.M)
        named = re.findall(r"^(?:Build)?(?:Requires|Recommends):.*\b%s\b(?!-)" % q, spec, re.M)
        if len(rich) != n_spec or len(named) != n_spec:
            bad.append("packaging/plugin-hostd.spec: %s: %d with a floor and a ceiling, %d name it; there must be %d" % (pkg, len(rich), len(named), n_spec))
        bad += ["packaging/plugin-hostd.spec: %s >= %s and < %s, they are %s and %s" % (pkg, f, c, floor, CEILING)
                for f, c in rich if (f, c) != (floor, CEILING)]
        pairs = re.findall(r"\b%s\s*\(>=\s*([^)\s~]+)~?\),\s*%s\s*\(<<\s*([^)\s~]+)~?\)" % (q, q), control)
        named = len(re.findall(r"\b%s\s*\(>=" % q, control))
        if len(pairs) != n_ctl or named != n_ctl:
            bad.append("debian/control: %s: %d with a floor and a ceiling, %d have a floor; there must be %d" % (pkg, len(pairs), named, n_ctl))
        bad += ["debian/control: %s (>= %s~) (<< %s~), they are %s and %s" % (pkg, f, c, floor, CEILING)
                for f, c in pairs if (f, c) != (floor, CEILING)]
    return bad


def fixture():
    spec, ctl = [], []
    for pkg, (floor, n_spec, n_ctl) in WANT.items():
        spec += ["Requires: (%s >= %s with %s < %s)" % (pkg, floor, pkg, CEILING)] * n_spec
        ctl += ["%s (>= %s~), %s (<< %s~)" % (pkg, floor, pkg, CEILING)] * n_ctl
    return "\n".join(spec) + "\n", ",\n ".join(ctl) + "\n"


def main():
    spec, ctl = fixture()
    arms = [
        ("the tree as written", spec, ctl, 0),
        ("no ceiling in the spec", spec.replace(" with omx-clap-host < 0.30", "").replace("(omx-clap-host >= 0.29.0)", "omx-clap-host >= 0.29.0"), ctl, 1),
        ("a wide ceiling in the spec", spec.replace("< 0.30", "< 1", 1), ctl, 1),
        ("a floor of 0.1.0 in the spec", spec.replace("0.26.2", "0.1.0", 1), ctl, 1),
        ("no ceiling in debian/control", spec, ctl.replace(", omx-clap-host-tests (<< 0.30~)", ""), 1),
        ("a wide ceiling in debian/control", spec, ctl.replace("<< 0.30~", "<< 1~", 1), 1),
    ]
    for what, s, c, want in arms:
        got = problems(s, c)
        if len(got) != want:
            print("FAIL the omx-clap-core check on %s: want %d findings, got %s" % (what, want, got))
            return 1
    print("ok   the omx-clap-core check sees a missing, a wide and a low bound in the spec and debian/control")

    def text(*path):
        with open(os.path.join(ROOT, *path)) as f:
            return f.read()
    bad = problems(text("packaging", "plugin-hostd.spec"), text("debian", "control"))
    for b in bad:
        print("FAIL %s" % b)
    if bad:
        return 1
    print("ok   omx-clap-core's packages are at their floors and below %s everywhere they are declared" % CEILING)
    return 0


sys.exit(main())

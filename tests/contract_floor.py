# SPDX-License-Identifier: GPL-3.0-or-later
# The package that ships plugin-hostd's package of omx-contract's contract directory (contract.d/3/plugin-hostd)
# requires omx-contract at run time, at a floor no lower than the first release whose schema takes every row key of
# the tables: 3.2.0, the first whose source field takes an index (omx_clap_panel_display.meter_ids[0], #150), so an
# older omx-contract never sits beside a table it refuses (#165). The RPM spec's Requires and debian/control's Depends
# both, a floor only.
# Usage: contract_floor.py [root]. The check proves it sees a missing and a low floor before it trusts the tree.
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEP = "omx-contract"
FLOOR = (3, 2, 0)
SHIPS = "omx-contract/contract.d/3/plugin-hostd"


def version(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def spec_sections(text):
    """{subpackage name or '': its lines} for the preamble sections and {name: its %files lines}"""
    pre, files, cur = {}, {}, ""
    into = pre
    for line in text.splitlines():
        m = re.match(r"^%(package|files)\b\s*(\S*)", line)
        if m:
            cur, into = m.group(2), (pre if m.group(1) == "package" else files)
            into.setdefault(cur, [])
            continue
        if re.match(r"^%(description|prep|build|install|check|changelog)\b", line):
            into = {}
            continue
        into.setdefault(cur, []).append(line)
    return pre, files


def spec_floors(text):
    """(the subpackage whose %files ship the contract directory, the omx-contract floors its Requires name)"""
    pre, files = spec_sections(text)
    ships = [n for n, lines in files.items() if any(SHIPS in l for l in lines)]
    if len(ships) != 1:
        return None, []
    rx = re.compile(r"^Requires:\s*%s\s*>=\s*(\S+)\s*$" % re.escape(DEP))
    return ships[0], [m.group(1) for l in pre.get(ships[0], []) for m in [rx.match(l)] if m]


def control_floors(text, ships):
    """the omx-contract floors in the Depends of the binary package `ships`"""
    for para in re.split(r"\n\s*\n", text):
        if re.search(r"^Package:\s*%s\s*$" % re.escape(ships), para, re.M):
            m = re.search(r"^Depends:((?:.*)(?:\n[ \t].*)*)", para, re.M)
            entries = [" ".join(e.split()) for e in m.group(1).split(",")] if m else []
            return [f for e in entries for f in re.findall(r"^%s\s*\(>=\s*([^)~\s]+)~?\)$" % re.escape(DEP), e)]
    return []


def problems(spec, control, deb_install):
    bad = []
    name, floors = spec_floors(spec)
    if name is None:
        return ["packaging/plugin-hostd.spec: no one subpackage's %%files ships %s" % SHIPS]
    where = "packaging/plugin-hostd.spec %%package %s" % name
    if len(floors) != 1:
        bad.append("%s: %d 'Requires: %s >= x.y.z' (one is the rule)" % (where, len(floors), DEP))
    elif version(floors[0]) < FLOOR:
        bad.append("%s: Requires %s >= %s, below %s" % (where, DEP, floors[0], ".".join(map(str, FLOOR))))
    if len(deb_install) != 1:
        return bad + ["debian: %d *.install files ship %s (one is the rule)" % (len(deb_install), SHIPS)]
    pkg = deb_install[0]
    floors = control_floors(control, pkg)
    if len(floors) != 1:
        bad.append("debian/control %s: %d 'Depends: %s (>= x.y.z~)' (one is the rule)" % (pkg, len(floors), DEP))
    elif version(floors[0]) < FLOOR:
        bad.append("debian/control %s: Depends %s (>= %s~), below %s" % (pkg, DEP, floors[0], ".".join(map(str, FLOOR))))
    return bad


def deb_shippers(root):
    d = os.path.join(root, "debian")
    return [f[:-len(".install")] for f in sorted(os.listdir(d))
            if f.endswith(".install") and SHIPS in open(os.path.join(d, f)).read()]


SPEC_OK = "%package contract\nRequires: omx-contract >= 3.2.0\n%description contract\nx\n%files contract\n%{_datadir}/omx-contract/contract.d/3/plugin-hostd/\n"
CTL_OK = "Package: p-contract\nArchitecture: all\nDepends: omx-clap-core-contract (>= 0.23.0~),\n omx-contract (>= 3.2.0~), ${misc:Depends}\n"


def main():
    # the check sees a missing and a low floor in each file before it is trusted
    arms = [
        ("the tree as written", SPEC_OK, CTL_OK, 0),
        ("no Requires in the spec", SPEC_OK.replace("Requires: omx-contract >= 3.2.0\n", ""), CTL_OK, 1),
        ("a 3.1.0 Requires in the spec", SPEC_OK.replace("3.2.0", "3.1.0"), CTL_OK, 1),
        ("the Requires on another subpackage", "%package devel\nRequires: omx-contract >= 3.2.0\n" + SPEC_OK.replace("Requires: omx-contract >= 3.2.0\n", ""), CTL_OK, 1),
        ("no Depends in debian/control", SPEC_OK, CTL_OK.replace(" omx-contract (>= 3.2.0~),", ""), 1),
        ("a 3.1.0 Depends in debian/control", SPEC_OK, CTL_OK.replace("3.2.0~", "3.1.0~"), 1),
    ]
    for what, spec, ctl, want in arms:
        got = problems(spec, ctl, ["p-contract"])
        if len(got) != want:
            print("FAIL the floor check on %s: want %d findings, got %s" % (what, want, got))
            return 1
    print("ok   the floor check sees a missing, a low and a misplaced omx-contract floor in the spec and debian/control")
    spec = open(os.path.join(ROOT, "packaging", "plugin-hostd.spec")).read()
    ctl = open(os.path.join(ROOT, "debian", "control")).read()
    bad = problems(spec, ctl, deb_shippers(ROOT))
    for b in bad:
        print("FAIL %s" % b)
    if bad:
        return 1
    print("ok   the package that ships %s requires %s >= %s at run time, in the spec and debian/control"
          % (SHIPS, DEP, ".".join(map(str, FLOOR))))
    return 0


sys.exit(main())

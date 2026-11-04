# SPDX-License-Identifier: GPL-3.0-or-later
# The package that ships plugin-hostd's package of omx-contract's contract directory (contract.d/<major>/plugin-hostd:
# %{omx_contract_dir}/plugin-hostd in the spec, the literal path in debian/*.install, which expands no macro)
# requires omx-contract at run time, at a floor no lower than the first release whose schema takes every row key of
# the tables: 3.2.0, the first whose source field takes an index (omx_clap_panel_display.meter_ids[0], #150), so an
# older omx-contract never sits beside a table it refuses (#165). The RPM spec's Requires and debian/control's Depends
# both, a floor and a ceiling: the next major (`(omx-contract >= 3.2.0 with omx-contract < 4)`, `omx-contract (<< 4~)`).
# Usage: contract_floor.py [root]. The check proves it sees a missing and a low floor before it trusts the tree.
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEP = "omx-contract"
FLOOR = (3, 2, 0)
CEILING = "4"
SHIPS = "%{omx_contract_dir}/plugin-hostd"
SHIPS_DEB = "omx-contract/contract.d/3/plugin-hostd"


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
    rx = re.compile(r"^Requires:\s*\(\s*%s\s*>=\s*(\S+)\s+with\s+%s\s*<\s*(\S+?)\s*\)\s*$" % (re.escape(DEP), re.escape(DEP)))
    bare = re.compile(r"^Requires:\s*%s\s*[<>]?=?\s*\S+\s*$" % re.escape(DEP))
    lines = pre.get(ships[0], [])
    found = [(m.group(1), m.group(2)) for l in lines for m in [rx.match(l)] if m]
    # a Requires with no ceiling is a floor with the ceiling ""
    return ships[0], found + [(re.findall(r"\S+$", l)[0], "") for l in lines if bare.match(l)]


def control_floors(text, ships):
    """the omx-contract floors in the Depends of the binary package `ships`"""
    for para in re.split(r"\n\s*\n", text):
        if re.search(r"^Package:\s*%s\s*$" % re.escape(ships), para, re.M):
            m = re.search(r"^Depends:((?:.*)(?:\n[ \t].*)*)", para, re.M)
            entries = [" ".join(e.split()) for e in m.group(1).split(",")] if m else []
            floors = [f for e in entries for f in re.findall(r"^%s\s*\(>=\s*([^)~\s]+)~?\)$" % re.escape(DEP), e)]
            ceilings = [c for e in entries for c in re.findall(r"^%s\s*\(<<\s*([^)~\s]+)~?\)$" % re.escape(DEP), e)]
            # one floor, and the ceiling beside it (or "" when there is none)
            return [(f, c) for f in floors for c in (ceilings or [""])] if len(ceilings) <= 1 else [(f, "?") for f in floors]
    return []


def problems(spec, control, deb_install):
    bad = []
    name, floors = spec_floors(spec)
    if name is None:
        return ["packaging/plugin-hostd.spec: no one subpackage's %%files ships %s" % SHIPS]
    where = "packaging/plugin-hostd.spec %%package %s" % name
    if len(floors) != 1:
        bad.append("%s: %d 'Requires: %s >= x.y.z' (one is the rule)" % (where, len(floors), DEP))
    elif version(floors[0][0]) < FLOOR:
        bad.append("%s: Requires %s >= %s, below %s" % (where, DEP, floors[0][0], ".".join(map(str, FLOOR))))
    elif floors[0][1] != CEILING:
        bad.append("%s: Requires %s with a ceiling of %r, the ceiling is < %s" % (where, DEP, floors[0][1], CEILING))
    if len(deb_install) != 1:
        return bad + ["debian: %d *.install files ship %s (one is the rule)" % (len(deb_install), SHIPS_DEB)]
    pkg = deb_install[0]
    floors = control_floors(control, pkg)
    if len(floors) != 1:
        bad.append("debian/control %s: %d 'Depends: %s (>= x.y.z~)' (one is the rule)" % (pkg, len(floors), DEP))
    elif version(floors[0][0]) < FLOOR:
        bad.append("debian/control %s: Depends %s (>= %s~), below %s" % (pkg, DEP, floors[0][0], ".".join(map(str, FLOOR))))
    elif floors[0][1] != CEILING:
        bad.append("debian/control %s: Depends %s with a ceiling of %r, the ceiling is (<< %s~)" % (pkg, DEP, floors[0][1], CEILING))
    return bad


def deb_shippers(root):
    d = os.path.join(root, "debian")
    return [f[:-len(".install")] for f in sorted(os.listdir(d))
            if f.endswith(".install") and SHIPS_DEB in open(os.path.join(d, f)).read()]


SPEC_OK = "%package contract\nRequires: (omx-contract >= 3.2.0 with omx-contract < 4)\n%description contract\nx\n%files contract\n%{omx_contract_dir}/plugin-hostd/\n"
CTL_OK = "Package: p-contract\nArchitecture: all\nDepends: omx-clap-core-contract (>= 0.23.0~),\n omx-contract (>= 3.2.0~), omx-contract (<< 4~), ${misc:Depends}\n"


def main():
    # the check sees a missing and a low floor in each file before it is trusted
    arms = [
        ("the tree as written", SPEC_OK, CTL_OK, 0),
        ("no Requires in the spec", SPEC_OK.replace("Requires: (omx-contract >= 3.2.0 with omx-contract < 4)\n", ""), CTL_OK, 1),
        ("a 3.1.0 Requires in the spec", SPEC_OK.replace("3.2.0", "3.1.0"), CTL_OK, 1),
        ("the Requires on another subpackage", "%package devel\nRequires: (omx-contract >= 3.2.0 with omx-contract < 4)\n" + SPEC_OK.replace("Requires: (omx-contract >= 3.2.0 with omx-contract < 4)\n", ""), CTL_OK, 1),
        ("no Depends in debian/control", SPEC_OK, CTL_OK.replace(" omx-contract (>= 3.2.0~), omx-contract (<< 4~),", ""), 1),
        ("a 3.1.0 Depends in debian/control", SPEC_OK, CTL_OK.replace("3.2.0~", "3.1.0~"), 1),
        ("no ceiling in the spec", SPEC_OK.replace(" with omx-contract < 4", "").replace("(omx-contract >= 3.2.0)", "omx-contract >= 3.2.0"), CTL_OK, 1),
        ("a ceiling of 5 in the spec", SPEC_OK.replace("< 4", "< 5"), CTL_OK, 1),
        ("no ceiling in debian/control", SPEC_OK, CTL_OK.replace(" omx-contract (<< 4~),", ""), 1),
        ("a ceiling of 5 in debian/control", SPEC_OK, CTL_OK.replace("<< 4~", "<< 5~"), 1),
        ("a %files that types the major", SPEC_OK.replace("%{omx_contract_dir}", "%{_datadir}/omx-contract/contract.d/3"), CTL_OK, 1),
    ]
    for what, spec, ctl, want in arms:
        got = problems(spec, ctl, ["p-contract"])
        if len(got) != want:
            print("FAIL the floor check on %s: want %d findings, got %s" % (what, want, got))
            return 1
    print("ok   the floor check sees a missing, a low and a misplaced omx-contract floor in the spec and debian/control, and a typed major")
    spec = open(os.path.join(ROOT, "packaging", "plugin-hostd.spec")).read()
    ctl = open(os.path.join(ROOT, "debian", "control")).read()
    bad = problems(spec, ctl, deb_shippers(ROOT))
    for b in bad:
        print("FAIL %s" % b)
    if bad:
        return 1
    print("ok   the package that ships %s requires %s >= %s and < %s at run time, in the spec and debian/control"
          % (SHIPS, DEP, ".".join(map(str, FLOOR)), CEILING))
    return 0


sys.exit(main())

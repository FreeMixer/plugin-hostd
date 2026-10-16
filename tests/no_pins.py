# SPDX-License-Identifier: GPL-3.0-or-later
# No pins: a dependency is declared in the packaging alone, the RPM spec and debian/control, as a floor only (>= the
# lowest version with the API it uses; no ceiling, operator ruling 2026-10-15), installed from the FreeMixer channel by dnf builddep / apt-get build-dep. No pins file,
# no submodule, no ref or sha a workflow checks a sibling out at, no sibling built from source.
# omx-clap-core is a build dependency of the check stage only (%if %{with check} in the spec, <!nocheck> in
# debian/control), so plugin-hostd builds with none of it present.
# Usage: no_pins.py [root]. The scan proves it can see a planted pin before it trusts an empty result.
import os, re, shutil, sys, tempfile

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEP = "omx-clap-host-tests"

# (what it is, file glob test, line regex): a line in a workflow that pins a dependency
WORKFLOW_PINS = [
    ("a checkout of a sibling repository", re.compile(r"^\s*repository:\s*(FreeMixer|FreeREAC|linuxnow)/(?!\.github\b)\S+")),
    ("a ref variable", re.compile(r"\b[A-Z][A-Z0-9_]*_REF\b")),
    ("a tag ref on a checkout", re.compile(r"^\s*ref:\s*\$\{\{|^\s*ref:\s*v\d")),
    ("a pins file", re.compile(r"\bpins\.txt\b")),
    ("a sibling built from source", re.compile(r"\bmake\s+-C\s+omx-")),
]


def workflow_files(root):
    d = os.path.join(root, ".github", "workflows")
    return [os.path.join(d, f) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []


def scan(root):
    """every finding as 'path:line what'"""
    found = []
    for name in ("pins.txt", ".gitmodules"):
        for base, _, files in os.walk(root):
            if ".git" in base.split(os.sep):
                continue
            if name in files:
                found.append("%s exists" % os.path.relpath(os.path.join(base, name), root))
    for path in workflow_files(root):
        for n, line in enumerate(open(path).read().splitlines(), 1):
            for what, rx in WORKFLOW_PINS:
                if rx.search(line):
                    found.append("%s:%d %s: %s" % (os.path.relpath(path, root), n, what, line.strip()))
    return found


def declared(root):
    """the floors and ceilings of DEP in the spec and in debian/control"""
    out = []
    spec = open(os.path.join(root, "packaging", "plugin-hostd.spec")).read()
    fl = re.findall(r"^BuildRequires:\s*%s\s*>=\s*(\S+)" % re.escape(DEP), spec, re.M)
    ce = re.findall(r"^BuildRequires:\s*%s\s*<\s*(\S+)" % re.escape(DEP), spec, re.M)
    out.append(("packaging/plugin-hostd.spec", fl, ce))
    ctl = open(os.path.join(root, "debian", "control")).read()
    fl = re.findall(r"%s\s*\(>=\s*([^)~\s]+)~?\)" % re.escape(DEP), ctl)
    ce = re.findall(r"%s\s*\(<<\s*([^)~\s]+)~?\)" % re.escape(DEP), ctl)
    out.append(("debian/control", fl, ce))
    return out


def check_declared(root):
    bad = []
    pairs = []
    for where, fl, ce in declared(root):
        if len(fl) != 1:
            bad.append("%s declares %s with %d floors (one is the rule)" % (where, DEP, len(fl)))
            continue
        if ce:
            bad.append("%s caps %s below %s: a dependency is a floor only, never a ceiling" % (where, DEP, ce[0]))
        pairs.append(fl[0])
    if len(set(pairs)) > 1:
        bad.append("the spec and debian/control disagree on the floor: %s" % pairs)
    return bad


CORE = re.compile(r"omx-clap")  # omx-clap-core and everything it ships: omx-clap-host, omx-clap-host-tests, pkgconfig(omx-clap-...)


def spec_edges(text):
    """BuildRequires on omx-clap-core outside an %if %{with check} block, as 'line what'"""
    found, stack = [], []
    for n, line in enumerate(text.splitlines(), 1):
        t = line.strip()
        if re.match(r"%if(n?def|arch|narch|os|nos)?\b", t) or t.startswith("%if "):
            stack.append(t)
        elif t == "%endif" and stack:
            stack.pop()
        elif re.match(r"BuildRequires:", t) and CORE.search(t):
            if not any(re.fullmatch(r"%if\s+%\{with\s+check\}", c) for c in stack):
                found.append("%d %s" % (n, t))
    return found


def control_edges(text):
    """Build-Depends entries on omx-clap-core without <!nocheck>, as 'entry'"""
    found = []
    for m in re.finditer(r"^Build-Depends[A-Za-z-]*:((?:.*)(?:\n[ \t].*)*)", text, re.M):
        for entry in m.group(1).split(","):
            entry = " ".join(entry.split())
            if CORE.search(entry) and "<!nocheck>" not in entry:
                found.append(entry)
    return found


def check_stage_only(root):
    """omx-clap-core is a build dependency of the check stage only (operator ruling 2026-10-16, plugin-hostd#32): a
    build with `rpmbuild --without check` or `dpkg-buildpackage -P nocheck` needs nothing of it, so the two repositories
    do not build-depend on each other"""
    spec = open(os.path.join(root, "packaging", "plugin-hostd.spec")).read()
    ctl = open(os.path.join(root, "debian", "control")).read()
    bad = ["packaging/plugin-hostd.spec:%s is a BuildRequires on omx-clap-core outside %%if %%{with check}" % e for e in spec_edges(spec)]
    bad += ["debian/control: Build-Depends on %r lacks <!nocheck>" % e for e in control_edges(ctl)]
    if not re.search(r"^%bcond_without check\b", spec, re.M):
        bad.append("packaging/plugin-hostd.spec does not declare %bcond_without check")
    if not re.search(r"^%check\n%if %\{with check\}\n", spec, re.M):
        bad.append("packaging/plugin-hostd.spec: %check is not wrapped in %if %{with check}")
    return bad


def main():
    # the check sees a planted edge of each kind before it is trusted
    if len(spec_edges("BuildRequires: omx-clap-host-tests >= 1\n")) != 1 or \
       spec_edges("%if %{with check}\nBuildRequires: omx-clap-host-tests >= 1\n%endif\n") or \
       len(spec_edges("%if %{with check}\n%endif\nBuildRequires: pkgconfig(omx-clap-core)\n")) != 1 or \
       len(control_edges("Build-Depends: a,\n omx-clap-host-tests (>= 1),\n b\n")) != 1 or \
       control_edges("Build-Depends: a,\n omx-clap-host-tests (>= 1) <!nocheck>,\n b\n"):
        print("FAIL the check-stage-only scan misses a planted omx-clap-core edge")
        return 1
    print("ok   the check-stage-only scan sees a planted omx-clap-core edge in the spec and in debian/control")
    # the scan must see a planted pin: one per kind, in a scratch copy
    tmp = tempfile.mkdtemp(prefix="no-pins.", dir=os.environ.get("TMPDIR") or ROOT)
    try:
        scratch = os.path.join(tmp, "t")
        os.makedirs(os.path.join(scratch, ".github", "workflows"))
        plant = ("env:\n  OMX_CLAP_HOST_REF: v0.4.0\n  - uses: actions/checkout@v4\n    with:\n      repository: FreeMixer/omx-clap-core\n"
                 "      ref: v0.4.0\n  - run: make -C omx-clap-host x\n  - run: cat .github/pins.txt\n")
        open(os.path.join(scratch, ".github", "workflows", "ci.yml"), "w").write(plant)
        open(os.path.join(scratch, ".github", "pins.txt"), "w").write("x\n")
        seen = scan(scratch)
        want = len(WORKFLOW_PINS) + 1
        if len(seen) < want:
            print("FAIL the scan misses planted pins: saw %d of at least %d: %s" % (len(seen), want, seen))
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok   the scan sees every planted kind of pin (%d findings in the scratch tree)" % len(seen))
    failed = 0
    for f in scan(ROOT):
        print("FAIL pin: %s" % f)
        failed += 1
    for b in check_declared(ROOT):
        print("FAIL %s" % b)
        failed += 1
    for b in check_stage_only(ROOT):
        print("FAIL %s" % b)
        failed += 1
    if not failed:
        print("ok   omx-clap-core is a build dependency of the check stage only (%if %{with check}, <!nocheck>)")
        print("ok   no pin anywhere; %s has one floor and no ceiling in the spec and in debian/control" % DEP)
    return 1 if failed else 0


sys.exit(main())

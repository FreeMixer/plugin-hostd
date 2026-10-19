# SPDX-License-Identifier: GPL-3.0-or-later
# A step a runner may be unable to run fails where it cannot run it. The JACK scenarios need a private user and pid
# namespace with its own /proc: every `if unshare ...; then` in a workflow has an else branch, and that branch exits 1,
# so a runner that refuses the namespace fails the job instead of passing it with a warning (#107). A step with no
# else at all is an error of its own: the shell takes it as a quiet skip.
# Usage: ci_guards.py [root]. The scan proves it can see a planted warn-only branch before it trusts an empty result.
import os, re, shutil, sys, tempfile

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IF_UNSHARE = re.compile(r"^(\s*)if unshare .*; then\s*$")


def workflow_files(root):
    d = os.path.join(root, ".github", "workflows")
    return [os.path.join(d, f) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []


def branches(lines):
    """every (line number, else lines) of an `if unshare` at the same indent; else lines is None without an else"""
    out = []
    for n, line in enumerate(lines):
        m = IF_UNSHARE.match(line)
        if not m:
            continue
        indent = m.group(1)
        body, in_else = None, False
        for later in lines[n + 1:]:
            if later == indent + "fi" or later.startswith(indent + "fi "):
                break
            if later == indent + "else":
                body, in_else = [], True
            elif in_else:
                body.append(later.strip())
        out.append((n + 1, body))
    return out


def scan(root):
    """every finding as 'path:line what'"""
    found = []
    for path in workflow_files(root):
        lines = open(path).read().split("\n")
        for n, body in branches(lines):
            where = "%s:%d" % (os.path.relpath(path, root), n)
            if body is None:
                found.append("%s an if unshare with no else: a runner that refuses the namespace skips the step quietly" % where)
            elif not any(b == "exit 1" or b.startswith("exit 1 ") for b in body):
                found.append("%s the else branch of an if unshare does not exit 1: a runner that refuses the namespace passes with a warning" % where)
    return found


def main():
    tmp = tempfile.mkdtemp(prefix="ci-guards.", dir=os.environ.get("TMPDIR") or ROOT)
    try:
        scratch = os.path.join(tmp, "t")
        os.makedirs(os.path.join(scratch, ".github", "workflows"))
        plant = ("      run: |\n          if unshare --user --map-root-user true; then\n            make test-jack\n          else\n"
                 "            echo \"::warning::skipped\"\n          fi\n"
                 "          if unshare --user true; then\n            make test-jack2\n          fi\n"
                 "          if unshare --user true; then\n            make x\n          else\n            echo no\n            exit 1\n          fi\n")
        open(os.path.join(scratch, ".github", "workflows", "ci.yml"), "w").write(plant)
        seen = scan(scratch)
        if len(seen) != 2 or "warning" not in seen[0] or "no else" not in seen[1]:
            print("FAIL the scan misses a planted branch: saw %s" % seen)
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok   the scan sees a planted warn-only else and a planted missing else, and passes one that exits 1")
    failed = 0
    for f in scan(ROOT):
        print("FAIL %s" % f)
        failed += 1
    n = sum(len(branches(open(p).read().split("\n"))) for p in workflow_files(ROOT))
    if not failed:
        print("ok   every if unshare in the workflows fails where the runner refuses the namespace (%d of them)" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: GPL-3.0-or-later
# docs/own-host.md is a page whose commands CI runs as written. This reads its ```sh own-host block and either
# prints the script that runs it (`script`), runs it (`run`), or proves the reader catches a broken step (`selftest`).
#
# A line of the block is a command. `send() ...` is a helper and is not counted. A trailing `# resp <text>` says the
# command's output must begin with <text>; `# has <text>` says it must contain <text>. Anything else after `#` is
# a comment. The page promises "nine commands"; the block may not grow past ten.
import os, re, subprocess, sys, tempfile

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "own-host.md")
MAX_COMMANDS = 10


def block(text):
    m = re.search(r"^```sh own-host\n(.*?)^```", text, re.S | re.M)
    if not m:
        sys.exit("own_host_page: no ```sh own-host block in the page")
    return [l for l in m.group(1).splitlines() if l.strip()]


def parse(lines):
    """[(command, kind, expected)] with kind None, 'resp' or 'has'; the helper line and comment lines are not commands"""
    out = []
    for l in lines:
        if l.lstrip().startswith("#"):
            continue
        m = re.match(r"^(.*?)\s+#\s+(resp|has)\s(.*)$", l)
        out.append((m.group(1), m.group(2), ("resp " if m.group(2) == "resp" else "") + m.group(3)) if m else (l, None, None))
    return out


def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def script(lines):
    """the bash script that runs the block, and the number of commands in it"""
    out = ["set -eu"]
    n = 0
    for cmd, kind, want in parse(lines):
        if cmd.startswith("send()"):
            out.append(cmd)
            continue
        n += 1
        if kind is None:
            out.append(cmd)
            continue
        pat = shq(want) + "*" if kind == "resp" else "*" + shq(want) + "*"
        out.append("__out=$(%s)" % cmd)
        out.append('echo "$__out"')
        out.append('case "$__out" in %s) ;; *) echo "own-host page, command %d: expected %s %s, got: $__out" >&2; exit 1;; esac'
                   % (pat, n, kind, want.replace('"', '').replace("$", "").replace("`", "")))
    return "\n".join(out) + "\n", n


def commands_ok(n):
    if n > MAX_COMMANDS:
        sys.exit("own_host_page: %d commands, the page promises under ten (%d at most)" % (n, MAX_COMMANDS))


# The page's block with the network and the daemon replaced by shell functions: the reader must pass on right
# replies and stop on a wrong one, whichever command is wrong.
STUBS = """sudo() { "$@"; }
curl() { :; }
tee() { cat >/dev/null; }
apt-get() { :; }
jackd() { :; }
plugin-hostd() { :; }
sleep() { :; }
"""


def stubbed(sc, lines, add, setp, get, scan):
    send = ('send() { case "$1" in add*) echo "%s";; param_set*) echo "%s";; param_get*) echo "%s";; esac; }' % (add, setp, get))
    return (STUBS + "omx-clap-scan() { echo '%s'; }\n" % scan) + sc.replace(lines[0], send, 1)


def selftest():
    lines = block(open(PAGE).read())
    sc, n = script(lines)
    commands_ok(n)
    right = ("resp 0", "resp 0", "resp 0 8.0000", "    param 1 Ratio [1 .. 20] default 4 automatable")
    cases = [("right replies", right, 0)]
    for i, name in enumerate(("add", "param_set", "param_get", "scan")):
        wrong = list(right)
        wrong[i] = "resp -103" if i < 3 else "    param 1 Wrong"
        cases.append(("a wrong " + name, tuple(wrong), 1))
    failed = 0
    for label, vals, want in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(stubbed(sc, lines, *vals))
        rc = subprocess.run(["bash", f.name], capture_output=True, text=True, cwd=tempfile.gettempdir()).returncode
        os.unlink(f.name)
        if (rc != 0) != (want != 0):
            print("FAIL own_host_page selftest: %s exited %d" % (label, rc))
            failed = 1
    if not failed:
        print("ok   own_host_page: %d commands; the right replies pass and each wrong one stops the script" % n)
    return failed


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    lines = block(open(PAGE).read())
    sc, n = script(lines)
    commands_ok(n)
    if cmd == "script":
        sys.stdout.write(sc)
    elif cmd == "run":
        sys.exit(subprocess.run(["bash", "-c", sc]).returncode)
    elif cmd == "selftest":
        sys.exit(selftest())
    else:
        sys.exit("usage: own_host_page.py script|run|selftest")


main()

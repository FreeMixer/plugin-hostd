# SPDX-License-Identifier: GPL-3.0-or-later
# docs/own-host.md is a page whose commands CI runs as written. This reads its ```sh own-host block and either
# prints the script that runs it (`script`), runs it (`run`), or proves the reader catches a broken step (`selftest`).
#
# A line of the block is a command. `send() ...` is a helper and is not counted. A trailing `# resp <text>` says the
# command's output must begin with <text>; `# has <text>` says it must contain <text>. Anything else after `#` is
# a comment. The page promises "nine commands"; the block may not grow past ten. The page has a second block,
# `sh own-host-lv2`, that continues the first in the same shell (the `send` helper, JACK running); both run as one
# script. `run --audio` then also proves with libjack that the LV2 instance processes audio: it sets the compressor
# to a 6 dB makeup gain and checks the output peak of a sine against the input's.
import os, re, subprocess, sys, tempfile

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "own-host.md")
MAX_COMMANDS = 10


BLOCKS = ("own-host", "own-host-lv2")

# after the page's blocks, with the LV2 instance 0 of the second one running: the sine goes in, the gain must come out
AUDIO = """send "param_set 0 ratio 1" | grep -qx 'resp 0'
send "param_set 0 makeupDb 6" | grep -qx 'resp 0'
python3 "$OWN_HOST_PROBE" effect_0 1.9953 0.03
"""


def block(text, name="own-host"):
    m = re.search(r"^```sh %s\n(.*?)^```" % re.escape(name), text, re.S | re.M)
    if not m:
        sys.exit("own_host_page: no ```sh %s block in the page" % name)
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


def page_script(text):
    """the bash script of every block in order, and the command count of each"""
    parts, counts = [], []
    for name in BLOCKS:
        sc, n = script(block(text, name))
        commands_ok(n)
        parts.append(sc)
        counts.append(n)
    return "\n".join(parts), counts


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


REPLIES = ("add_clap", "set_clap", "get_clap", "scan", "quit", "add_lv2", "set_lv2", "get_lv2", "worker_list")
RIGHT = ("resp 0", "resp 0", "resp 0 8.0000", "    param 1 Ratio [1 .. 20] default 4 automatable",
         "resp 0", "resp 0", "resp 0", "resp 0 8.0000", "resp 1 w1:42:lv2-clap:up:own:0")
WRONG = {"scan": "    param 1 Wrong", "worker_list": "resp 1 w1:42:mod-host:up:own:0"}


def stubbed(sc, lines, replies):
    r = dict(zip(REPLIES, replies))
    send = ('send() { case "$1" in "add clap"*) echo "%(add_clap)s";; "add lv2"*) echo "%(add_lv2)s";; '
            '"param_set 0 ratio"*) echo "%(set_lv2)s";; param_set*) echo "%(set_clap)s";; '
            '"param_get 0 ratio"*) echo "%(get_lv2)s";; param_get*) echo "%(get_clap)s";; '
            'quit*) echo "%(quit)s";; worker_list*) echo "%(worker_list)s";; esac; }' % r)
    return (STUBS + "omx-clap-scan() { echo '%s'; }\n" % r["scan"]) + sc.replace(lines[0], send, 1)


def selftest():
    text = open(PAGE).read()
    lines = block(text)
    sc, counts = page_script(text)
    cases = [("right replies", RIGHT, 0)]
    for i, name in enumerate(REPLIES):
        wrong = list(RIGHT)
        wrong[i] = WRONG.get(name, "resp -103")
        cases.append(("a wrong " + name, tuple(wrong), 1))
    failed = 0
    for label, vals, want in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(stubbed(sc, lines, vals))
        rc = subprocess.run(["bash", f.name], capture_output=True, text=True, cwd=tempfile.gettempdir()).returncode
        os.unlink(f.name)
        if (rc != 0) != (want != 0):
            print("FAIL own_host_page selftest: %s exited %d" % (label, rc))
            failed = 1
    if not failed:
        print("ok   own_host_page: %s commands; the right replies pass and each wrong one stops the script"
              % " + ".join(str(n) for n in counts))
    return failed


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    sc, _ = page_script(open(PAGE).read())
    if cmd == "script":
        sys.stdout.write(sc)
    elif cmd == "run":
        if "--audio" in sys.argv[2:]:
            sc += AUDIO
        env = dict(os.environ, OWN_HOST_PROBE=os.path.join(os.path.dirname(os.path.abspath(__file__)), "own_host_lv2_probe.py"))
        sys.exit(subprocess.run(["bash", "-c", sc], env=env).returncode)
    elif cmd == "selftest":
        sys.exit(selftest())
    else:
        sys.exit("usage: own_host_page.py script|run [--audio]|selftest")


main()

# SPDX-License-Identifier: GPL-3.0-or-later
# issue 238, the sabotage arm of tests/ready_connect_test.py: a daemon built from src/main.c with its ready line moved
# ahead of socket_start() (which then takes 0.3 s to come, so the loss is every start's, not a race's) must fail that test. Without this arm a test that passes against any daemon proves nothing.
import os, re, subprocess, sys, tempfile, shlex

exe, fake, cc, cflags, objs, libs = sys.argv[1:7]
src = open("src/main.c").read()
ready = re.search(r'    printf\("%s\\n", PHD_READY_LINE\);\n    fflush\(stdout\);\n\n', src)
anchor = "    /* the feedback port is the relay's:"
assert ready and anchor in src, "src/main.c no longer has the ready line or the socket start this arm moves"
sabotaged = src.replace(ready.group(0), "").replace(anchor, ready.group(0).rstrip("\n") + "\n    usleep(300000);\n" + anchor, 1)
tmp = tempfile.mkdtemp(prefix="plugin-hostd-sabotage.")
c, out = os.path.join(tmp, "main.c"), os.path.join(tmp, "plugin-hostd")
open(c, "w").write(sabotaged)
others = [o for o in shlex.split(objs) if o != "src/main.o"]
subprocess.run([cc, *shlex.split(cflags), "-Isrc", "-c", "-o", os.path.join(tmp, "main.o"), c], check=True)
subprocess.run([cc, os.path.join(tmp, "main.o"), *others, *shlex.split(libs), "-pthread", "-lm", "-o", out], check=True)
r = subprocess.run([sys.executable, "tests/ready_connect_test.py"], env=dict(os.environ, PLUGIN_HOSTD=out, FAKE_HOST=fake),
                   capture_output=True, text=True)
print(r.stdout.strip())
if r.returncode == 0:
    print("FAIL the ready line before the sockets passed the test: it does not test what it claims")
    sys.exit(1)
print("ok   the daemon with its ready line before its sockets fails the test")

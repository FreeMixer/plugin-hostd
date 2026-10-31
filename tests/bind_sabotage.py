# SPDX-License-Identifier: GPL-3.0-or-later
# The sabotage arms of tests/bind_test.py: each builds the daemon with one guard taken out and the test must fail. Without
# this the test could pass by not reaching anything.
import os, shlex, shutil, subprocess, sys, tempfile

exe, fake, cc, cflags, objs, libs = sys.argv[1:7]

ARMS = [
    ("the default is every address",
     [("include/plugin-hostd/protocol.h", '#define PHD_DEFAULT_BIND_ADDRESS      "127.0.0.1"', '#define PHD_DEFAULT_BIND_ADDRESS      "0.0.0.0"')]),
    ("the library is not told the address",
     [("src/main.c", "socket_set_bind_address(g_conf.bind_address) != 0 ||", "")]),
    ("the feedback port listens on every address",
     [("src/relay.c", "if (inet_pton(AF_INET, address, &addr.sin_addr) != 1)", "if (inet_pton(AF_INET, \"0.0.0.0\", &addr.sin_addr) != 1)")]),
    ("the option is ignored",
     [("src/main.c", "bind_address = optarg;", "(void)optarg;")]),
    ("a command port that cannot listen does not stop the daemon",
     [("src/main.c", "socket_start(socket_port, 0, SOCKET_MSG_BUFFER_SIZE) < 0", "(socket_start(socket_port, 0, SOCKET_MSG_BUFFER_SIZE), 0)")]),
    ("a feedback port that cannot listen does not stop the daemon",
     [("src/main.c", "relay_start(feedback_port, g_conf.bind_address) < 0", "(relay_start(feedback_port, g_conf.bind_address), 0)")]),
]

failures = 0
for name, edits in ARMS:
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-bind-sabotage.")
    changed, header = set(), False
    # the sabotaged header is found first, and the headers beside it with it
    shutil.copytree("include", os.path.join(tmp, "include"))
    for path, old, new in edits:
        target = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        src = open(target if os.path.exists(target) else path).read()
        assert old in src, "%s no longer has: %s" % (path, old)
        open(target, "w").write(src.replace(old, new))
        header = header or path.endswith(".h")
        changed.add(path)
    sources = {o[:-2] + ".c" for o in shlex.split(objs)}
    # a changed header rebuilds what reads the default; every other object is the build's own
    rebuild = {"src/main.c", "src/conf.c"} if header else (changed & sources)
    out = os.path.join(tmp, "plugin-hostd")
    own = []
    for c in sorted(rebuild):
        at = os.path.join(tmp, c) if os.path.exists(os.path.join(tmp, c)) else c
        obj = os.path.join(tmp, os.path.basename(c)[:-2] + ".o")
        subprocess.run([cc, "-I" + os.path.join(tmp, "include"), *shlex.split(cflags), "-Isrc", "-c", "-o", obj, at], check=True)
        own.append(obj)
    kept = [o for o in shlex.split(objs) if o[:-2] + ".c" not in rebuild]
    subprocess.run([cc, *own, *kept, *shlex.split(libs), "-pthread", "-lm", "-o", out], check=True)
    r = subprocess.run([sys.executable, "tests/bind_test.py"], env=dict(os.environ, PLUGIN_HOSTD=out, FAKE_HOST=fake),
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("FAIL %s: tests/bind_test.py passed" % name)
        failures += 1
    else:
        print("ok   %s: tests/bind_test.py fails: %s" % (name, r.stdout.strip().splitlines()[-1]))
sys.exit(1 if failures else 0)

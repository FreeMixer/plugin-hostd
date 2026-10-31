# SPDX-License-Identifier: GPL-3.0-or-later
# The sabotage arms of tests/alloc_sweep.py: a daemon with a check taken out must fail the sweep. Without this the sweep
# could pass by refusing nothing that matters.
import os, shlex, subprocess, sys, tempfile

cc, cflags, libs, objdir = sys.argv[1:5]
ARMS = [
    ("a worker there was no memory for is filled in", "src/supervisor.c",
     "    worker_t *w = calloc(1, sizeof(worker_t));\n\n    if (!w)\n        return NULL;\n",
     "    worker_t *w = calloc(1, sizeof(worker_t));\n\n"),
    ("a pin's file list there was no memory for is written to", "src/pins.c",
     "            if (!paths)\n                goto no_memory;\n", ""),
    ("a parsed value there was no memory for is filled in", "src/json.c",
     "    if (n)\n        n->type = t;\n", "    n->type = t;\n"),
]
failures = 0
for name, path, old, new in ARMS:
    src = open(path).read()
    assert old in src, "%s no longer has: %s" % (path, old)
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-alloc-sabotage.")
    c = os.path.join(tmp, os.path.basename(path))
    obj = os.path.basename(path)[:-2] + ".o"
    open(c, "w").write(src.replace(old, new))
    subprocess.run([cc, *shlex.split(cflags), "-Isrc", "-include", "tests/alloc_fail.h", "-c", "-o", os.path.join(tmp, obj), c], check=True)
    kept = [os.path.join(objdir, o) for o in os.listdir(objdir) if o != obj]
    out = os.path.join(tmp, "plugin-hostd-alloc-fail")
    subprocess.run([cc, os.path.join(tmp, obj), *kept, *shlex.split(libs), "-pthread", "-lm", "-o", out], check=True)
    r = subprocess.run([sys.executable, "tests/alloc_sweep.py"], env=dict(os.environ, ALLOC_SWEEP_DAEMON=out, ALLOC_SWEEP_FIRST_FAILURE="1"), capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    if r.returncode == 0:
        print("FAIL %s: tests/alloc_sweep.py passed" % name)
        failures += 1
    else:
        print("ok   %s: tests/alloc_sweep.py fails: %s | %s" % (name, lines[-2][:60] if len(lines) > 1 else "", lines[-1][:160]))
sys.exit(1 if failures else 0)

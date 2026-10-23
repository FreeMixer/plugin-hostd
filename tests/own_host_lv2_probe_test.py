# SPDX-License-Identifier: GPL-3.0-or-later
# own_host_lv2_probe.py must leave no JACK client half torn down (#110): tests/jack_teardown_stub.c stands in for
# libjack and raises SIGSEGV as the process exits if the probe never called jack_deactivate/jack_client_close. The
# probe is run RUNS times in a row against a target that can never be found, so every run activates the client,
# fails its first connect and exits through the same teardown path; a probe that closes its client never signals.
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = 30


def main():
    tree = sys.argv[1] if len(sys.argv) > 1 else ROOT
    # the stub is never sabotaged: ROOT's own copy, built once, stands in for every tree
    stub = os.environ.get("JACK_TEARDOWN_STUB", os.path.join(ROOT, "tests", "jack_teardown_stub.so"))
    if not os.path.exists(stub):
        sys.exit("own_host_lv2_probe_test: missing %s (make tests/jack_teardown_stub.so)" % stub)
    probe = os.path.join(tree, "tests", "own_host_lv2_probe.py")
    libdir = tempfile.mkdtemp(prefix="own-host-lv2-probe-test.")
    try:
        shutil.copy(stub, os.path.join(libdir, "libjack.so.0"))
        env = dict(os.environ, LD_LIBRARY_PATH=libdir + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))
        for n in range(RUNS):
            p = subprocess.run([sys.executable, probe, "nowhere", "1.0", "1.0"], env=env,
                                capture_output=True, text=True, timeout=10)
            if p.returncode < 0:
                sys.exit("own_host_lv2_probe_test: run %d of %d died on signal %d (the JACK client was not closed):\n%s"
                          % (n + 1, RUNS, -p.returncode, p.stdout + p.stderr))
            if p.returncode != 1:
                sys.exit("own_host_lv2_probe_test: run %d of %d exited %d, wanted 1 (cannot connect):\n%s"
                          % (n + 1, RUNS, p.returncode, p.stdout + p.stderr))
    finally:
        shutil.rmtree(libdir, ignore_errors=True)
    print("ok   own_host_lv2_probe_closes_its_jack_client_30_times_in_a_row")


main()

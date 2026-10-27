# SPDX-License-Identifier: GPL-3.0-or-later
# The pool tests/sabotage.py runs its arms in. An arm is one broken line, one rebuild, one test; arms share nothing but the
# read-only checkout, so they run side by side, and what they print comes out in the order of the table, whichever
# finishes first.
import multiprocessing, os, shutil
from concurrent.futures import ProcessPoolExecutor

# every slot owns this many ports below the range the kernel hands out for bind(0) (32768 and up), starting here:
# two arms never draw the same one, and neither draws one an arm of the unbroken kind already holds
PORT_BASE = 20000
PORTS_PER_SLOT = 200
MAX_JOBS = (32768 - PORT_BASE) // PORTS_PER_SLOT


def jobs_from(env, cpus=None):
    """SABOTAGE_JOBS, else min(the cores this process may run on, 8); never under 1, never over what the ports allow"""
    if cpus is None:
        cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    raw = env.get("SABOTAGE_JOBS")
    if raw:
        if not raw.isdigit() or int(raw) < 1:
            raise SystemExit("SABOTAGE_JOBS must be a whole number of 1 or more, not '%s'" % raw)
        return min(int(raw), MAX_JOBS)
    return max(1, min(cpus, 8))


def arm_tree(work, index):
    """the directory arm number `index` of the table builds and breaks in: its own, never another arm's"""
    return os.path.join(work, "arm%04d" % index)


_slots = None
_exclusive = None


def _start(slots, exclusive):
    global _slots, _exclusive
    _slots, _exclusive = slots, exclusive
    slot = slots.get()
    os.environ["PLUGIN_HOSTD_TEST_PORT_BASE"] = str(PORT_BASE + slot * PORTS_PER_SLOT)
    os.environ["PLUGIN_HOSTD_TEST_PORT_SPAN"] = str(PORTS_PER_SLOT)


def _call(fn, arm, exclusive):
    # an arm that needs a server of its own (the jack arms start a PipeWire) takes the one lock, so two never run at once
    if exclusive:
        with _exclusive:
            return fn(arm)
    return fn(arm)


def run(arms, fn, jobs, emit, exclusive=lambda arm: False):
    """fn(arm) for each arm, `jobs` at a time in processes of their own; emit(arm, result) is called in the order of
    `arms`, each as soon as it and every arm before it is done. An arm that raises ends the run with its exception."""
    ctx = multiprocessing.get_context("fork")
    slots = ctx.Queue()
    for n in range(jobs):
        slots.put(n)
    lock = ctx.Lock()
    pool = ProcessPoolExecutor(max_workers=jobs, mp_context=ctx, initializer=_start, initargs=(slots, lock))
    try:
        futures = [(arm, pool.submit(_call, fn, arm, exclusive(arm))) for arm in arms]
        for arm, future in futures:
            emit(arm, future.result())
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def remove(tree):
    shutil.rmtree(tree, ignore_errors=True)

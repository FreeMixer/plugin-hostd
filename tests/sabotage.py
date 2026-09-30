# Break the daemon on purpose, one guard at a time, and require the named test to go red; the unbroken daemon must
# pass the same test first, or a red proves nothing. A guard whose sabotage leaves its test green is decoration.
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.path.abspath(os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))

# (what is broken, file, text, replacement, the test that must go red[, "jack"]); a "jack" test runs in tests/jack_e2e.sh
# over the real workers and is skipped when OMX_CLAP_HOST is not set
SABOTAGE = [
    ("the verb tail is not replayed", "src/supervisor.c",
     "if (replay_line(w, i->tail[m].line) != RPC_OK)", "if (0 && replay_line(w, i->tail[m].line) != RPC_OK)",
     "own_crash_respawns_only_that_instance_and_replays_it"),
    ("the checkpoint is not loaded", "src/supervisor.c", "    if (any_ckpt)\n", "    if (0 && any_ckpt)\n",
     "replay_is_text_identical_and_state_checkpoint_is_byte_identical"),
    ("connections are not replayed", "src/supervisor.c", "for (m = 0; m < i->nconns; m++)\n        {\n            int code;",
     "for (m = 0; m < 0; m++)\n        {\n            int code;", "connections_are_replayed_and_disconnect_forgets"),
    ("a pool that died in a callback is not split", "src/supervisor.c", "else if (w->ninst > 1)", "else if (0)",
     "pool_callback_crash_splits_the_pool_and_the_culprit_comes_back_own"),
    ("the verb the worker died on is put in the ledger and replayed", "src/supervisor.c",
     "    event(\"instance_verb_dropped %d %s\", i->id, line);\n", "    ledger_verb(i, line);\n",
     "the_verb_the_worker_died_on_is_dropped_and_not_replayed"),
    ("the command in flight is not blamed", "src/supervisor.c", "if (w->inst[n]->id == in_flight)", "if (0)",
     "pool_in_flight_command_names_the_culprit_and_the_pool_stays_a_pool"),
    ("the storm bound never trips for a placement", "src/supervisor.c", "    if (n >= g_conf.storm_deaths)\n    {\n        w->state",
     "    if (0 && n >= g_conf.storm_deaths)\n    {\n        w->state", "crashing_own_instance_is_given_up_alone"),
    ("a failed add is never counted against its instance", "src/supervisor.c",
     "if (recent(m->deaths, &m->ndeaths, now) >= g_conf.storm_deaths)", "if (0)",
     "storm_bound_is_per_placement_and_reset_rearms_it"),
    ("every instance gets a worker of its own", "src/supervisor.c", "if (!strcmp(place, \"own\"))", "if (1)",
     "placement_own_default_and_pool"),
    ("a quarantined instance goes where the hint says", "src/supervisor.c", "    if (m->quarantined)\n        snprintf(place, sizeof(place), \"own\");",
     "", "quarantined_instance_is_placed_own_until_cleared"),
    ("workers outlive a killed daemon", "src/proc.c", "prctl(PR_SET_PDEATHSIG, SIGTERM);", "",
     "sigkill_of_the_daemon_takes_the_workers_with_it"),
    ("a reply is not passed through", "src/supervisor.c", "    return reply;\n}\n\nchar *sup_remove(int id)",
     "    free(reply);\n    return sup_resp(0);\n}\n\nchar *sup_remove(int id)", "plain_verbs_pass_through_unchanged"),
    ("worker_env is not applied to a running worker", "src/supervisor.c", "proc_apply_env(g_workers[n]->pid, &g_env[f]);", ";",
     "worker_env_reaches_new_and_running_workers"),
    ("a refused connect is never asked again", "src/supervisor.c", "        else if (w->state == W_UP && w->npend)\n            pend_retry(w, now);",
     "", "a_connect_the_new_worker_cannot_make_yet_is_asked_again"),
    ("connections are not replayed, so a killed strip never gets its audio back", "src/supervisor.c",
     "for (m = 0; m < i->nconns; m++)\n        {\n            int code;", "for (m = 0; m < 0; m++)\n        {\n            int code;",
     "audio_of_the_other_strip_never_changes_when_one_worker_is_killed", "jack"),
    ("an own lv2 worker keeps the whole bundle set", "src/supervisor.c", "    if (w->fmt != FMT_LV2 || w->pool || !uri)\n        return NULL;",
     "    return NULL;", "lv2_own_worker_sees_one_bundle_and_replays_after_a_kill", "jack"),
    ("the checkpoint is not loaded after a real respawn", "src/supervisor.c", "    if (any_ckpt)\n", "    if (0 && any_ckpt)\n",
     "clap_own_crash_replays_bit_identically_and_the_neighbour_never_notices", "jack"),
]


def build(tree):
    subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "plugin-hostd"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)


def run_test(tree, name, jack=False):
    env = dict(os.environ, ONLY=name, PLUGIN_HOSTD=os.path.join(tree, "plugin-hostd"), FAKE_HOST=FAKE)
    cmd = [os.path.join(ROOT, "tests", "jack_e2e.sh")] if jack else [sys.executable, os.path.join(ROOT, "tests", "daemon_test.py")]
    p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout


failed = 0
work = tempfile.mkdtemp(prefix="plugin-hostd-sabotage.")
try:
    for entry in SABOTAGE:
        what, path, text, repl, name = entry[:5]
        jack = len(entry) > 5
        if jack and not os.environ.get("OMX_CLAP_HOST"):
            print("skip sabotage (no OMX_CLAP_HOST): %s" % what)
            continue
        tree = os.path.join(work, "t")
        shutil.rmtree(tree, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tree, "src"))
        shutil.copy(os.path.join(ROOT, "Makefile"), tree)
        build(tree)
        code, out = run_test(tree, name, jack)
        if code != 0 or "ok   " + name not in out:
            print("FAIL control: %s does not pass on the unbroken daemon:\n%s" % (name, out))
            failed += 1
            continue
        src = open(os.path.join(tree, path)).read()
        if src.count(text) != 1:
            print("FAIL %s: the text to break occurs %d times in %s" % (what, src.count(text), path))
            failed += 1
            continue
        open(os.path.join(tree, path), "w").write(src.replace(text, repl))
        for f in os.listdir(os.path.join(tree, "src")):
            if f.endswith(".o"):
                os.unlink(os.path.join(tree, "src", f))
        build(tree)
        code, out = run_test(tree, name, jack)
        if code == 0:
            print("FAIL sabotage survived: %s (%s still passes)" % (what, name))
            failed += 1
        else:
            print("ok   sabotage caught: %s -> %s red" % (what, name))
finally:
    shutil.rmtree(work, ignore_errors=True)
print("sabotage FAILED (%d)" % failed if failed else "sabotage ok")
sys.exit(1 if failed else 0)

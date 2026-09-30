# Break the daemon on purpose, one guard at a time, and require the named test to go red; the unbroken daemon must
# pass the same test first, or a red proves nothing. A guard whose sabotage leaves its test green is decoration.
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.path.abspath(os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))

# (what is broken, file, text, replacement, the test that must go red[, "jack"]); a "jack" test runs in tests/jack_e2e.sh
# over the real workers and is skipped when OMX_CLAP_HOST is not set; "lv2" is a jack test that also needs mod-host and
# an LV2 bundle (MOD_HOST, LV2_DIR, LV2_URI, LV2_BUNDLE, LV2_PARAM) and is skipped without them; "pin" breaks
# include/plugin-hostd/pin.h and runs tests/pin_test.c
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
     "    event(PHD_EVENT_VERB_DROPPED_FMT, i->id, line);\n", "    ledger_verb(i, line);\n",
     "the_verb_the_worker_died_on_is_dropped_and_not_replayed"),
    ("the suspect window is zero", "src/supervisor.c", "now - i->sus_ms <= g_conf.suspect_window_ms", "0",
     "a_crash_just_after_the_reply_drops_the_verb_it_answered_and_does_not_crash_again"),
    ("the suspect window never ends", "src/supervisor.c", "now - i->sus_ms <= g_conf.suspect_window_ms", "1",
     "a_crash_well_after_the_reply_replays_the_verb_as_before"),
    ("a kill from outside is judged like a crash", "src/supervisor.c", "!(WIFSIGNALED(status) && (WTERMSIG(status) == SIGKILL || WTERMSIG(status) == SIGTERM))",
     "1", "a_kill_from_outside_inside_the_window_drops_nothing"),
    ("a dropped suspect forgets the value it replaced", "src/supervisor.c", "        if (s->sus_prev)\n", "        if (0)\n",
     "a_dropped_suspect_gives_back_the_value_it_replaced"),
    ("the sender of the suspect is not blamed", "src/supervisor.c", "        in_flight = drop_suspect(w, now);", "        drop_suspect(w, now);",
     "pool_crash_just_after_the_reply_names_the_sender_and_the_pool_stays_a_pool"),
    ("the command in flight is not blamed", "src/supervisor.c", "if (w->inst[n]->id == in_flight)", "if (0)",
     "pool_in_flight_command_names_the_culprit_and_the_pool_stays_a_pool"),
    ("the storm bound never trips for a placement", "src/supervisor.c", "    if (n >= g_conf.storm_deaths)\n    {\n        w->state",
     "    if (0 && n >= g_conf.storm_deaths)\n    {\n        w->state", "crashing_own_instance_is_given_up_alone"),
    ("a failed add is never counted against its instance", "src/supervisor.c",
     "if (recent(m->deaths, &m->ndeaths, now) >= g_conf.storm_deaths)", "if (0)",
     "storm_bound_is_per_placement_and_reset_rearms_it"),
    ("every instance gets a worker of its own", "src/supervisor.c", "if (!strcmp(place, PHD_PLACE_OWN))", "if (1)",
     "placement_own_default_and_pool"),
    ("a quarantined instance goes where the hint says", "src/supervisor.c", "    if (m->quarantined)\n        snprintf(place, sizeof(place), PHD_PLACE_OWN);",
     "", "quarantined_instance_is_placed_own_until_cleared"),
    ("workers outlive a killed daemon", "src/proc.c", "prctl(PR_SET_PDEATHSIG, SIGTERM);", "",
     "sigkill_of_the_daemon_takes_the_workers_with_it"),
    ("a command that takes a uri first is routed by instance", "src/verbs.c",
     "EFFECT_PRESET_LOAD, EFFECT_PRESET_SAVE, EFFECT_BYPASS,",
     "EFFECT_PRESET_LOAD, EFFECT_PRESET_SAVE, EFFECT_PRESET_SHOW, EFFECT_BYPASS,",
     "a_command_whose_first_argument_is_a_uri_reaches_every_worker"),
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
     "    return NULL;", "lv2_own_worker_sees_one_bundle_and_replays_after_a_kill", "lv2"),
    ("the checkpoint is not loaded after a real respawn", "src/supervisor.c", "    if (any_ckpt)\n", "    if (0 && any_ckpt)\n",
     "clap_own_crash_replays_bit_identically_and_the_neighbour_never_notices", "jack"),
    ("add checks no pin", "src/supervisor.c", "rc = pins_check(fmt == FMT_CLAP, fwd, g_conf.lv2_path, &layout);", "rc = SUCCESS;",
     "an_unpinned_plugin_is_refused_by_default_and_no_worker_starts"),
    ("a pin in a scheme this version does not know is a pin", "src/pins.c",
     "if (!p || strcmp(p->scheme, PHD_PIN_LAYOUT_SCHEME))", "if (!p)",
     "an_unpinned_plugin_is_refused_by_default_and_no_worker_starts"),
    ("a file whose digest differs passes", "src/pins.c", "else if (phd_pin_fd_digest(fd, hex) != 0 || strcmp(hex, want))",
     "else if (phd_pin_fd_digest(fd, hex) != 0)", "a_swapped_clap_binary_is_refused_before_any_worker_sees_add"),
    ("a pin need not hold the .clap it admits", "src/pins.c", "if (held(p, slash + 1) < 0)", "if (0)",
     "a_swapped_clap_binary_is_refused_before_any_worker_sees_add"),
    ("the layout pin is not handed to the CLAP worker", "src/supervisor.c", "    if (layout && fmt == FMT_CLAP)\n", "    if (0)\n",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("a worker's refusal of the layout pin is not a refusal", "src/supervisor.c",
     "if (rc == RPC_OK && resp_code(reply) >= 0)", "if (rc == RPC_OK)",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("a worker that does not answer pin_expect is a failed instantiation", "src/supervisor.c",
     "            code = PHD_ERR_VERB_DROPPED;\n", "", "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("the pin_expect a worker went with is not named", "src/supervisor.c",
     "            event(PHD_EVENT_VERB_DROPPED_FMT, id, pin_expect_line(id, layout));\n", "",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("the manifest may name a file the pin does not hold", "src/pins.c", "if (held(p, names.name[n]) < 0)", "if (0)",
     "an_lv2_bundle_is_pinned_by_its_manifest_binary_and_seealso"),
    ("the manifest's bytes are not compared with the pin", "src/pins.c", "if (got != st.st_size || strcmp(hex, want))",
     "if (got != st.st_size)", "an_lv2_bundle_is_pinned_by_its_manifest_binary_and_seealso"),
    ("a pinned LV2 plugin may ask for a pool", "src/supervisor.c",
     "            if (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)))\n"
     "                return sup_resp(PHD_ERR_PLACEMENT_INVALID);\n", "", "a_pinned_lv2_plugin_gets_a_worker_of_its_own"),
    ("a pinned LV2 plugin follows a policy into a pool", "src/supervisor.c",
     "            snprintf(place, sizeof(place), PHD_PLACE_OWN);\n        }\n    }\n", "        }\n    }\n",
     "a_pinned_lv2_plugin_gets_a_worker_of_its_own"),
    ("a replayed add is not checked again", "src/supervisor.c", "    i->unreplayed = 0;\n    if (!g_conf.require_pins)",
     "    i->unreplayed = 0;\n    if (1)", "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("the verbs of an instance its pin refused on replay are replayed", "src/supervisor.c",
     "        if (i->unreplayed)\n            continue;\n        for (m = 0; m < i->ntail; m++)",
     "        for (m = 0; m < i->ntail; m++)", "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a refused replay is not announced", "src/supervisor.c", "    event(PHD_EVENT_REPLAY_REFUSED_FMT, i->id, code);\n", "",
     "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a worker's refusal of a replayed add is taken for the instance", "src/supervisor.c",
     "        if (code < 0)\n        {\n            replay_refused(w, i, add, code);\n            continue;\n        }\n", "",
     "a_layout_pinned_again_while_its_worker_was_down_is_refused_by_the_replayed_add"),
    ("a SHA-256 round constant is wrong", "include/plugin-hostd/pin.h", "0x428a2f98, 0x71374491", "0x428a2f98, 0x71374490",
     "pin.h", "pin"),
    ("a tab in a name is not escaped", "include/plugin-hostd/pin.h", "*s == '\\t' ? \"\\\\t\" : ", "", "pin.h", "pin"),
    ("an LV2 port's properties are not sorted", "include/plugin-hostd/pin.h",
     "            qsort(props, p->nproperties, sizeof(*props), phd_layout_bytewise);\n", "", "pin.h", "pin"),
    ("a number declared by no port is written as its bits", "include/plugin-hostd/pin.h",
     "    if (!declared)\n", "    if (0)\n", "pin.h", "pin"),
]


def build(tree):
    subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "plugin-hostd"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)


def run_pin_test(tree):
    exe = os.path.join(tree, "pin-test")
    subprocess.run(["cc", "-I" + os.path.join(tree, "include"), "-std=gnu99", "-o", exe,
                    os.path.join(ROOT, "tests", "pin_test.c")], check=True)
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout


def run_test(tree, name, jack=False):
    if jack == "pin":
        return run_pin_test(tree)
    env = dict(os.environ, ONLY=name, PLUGIN_HOSTD=os.path.join(tree, "plugin-hostd"), FAKE_HOST=FAKE)
    cmd = [os.path.join(ROOT, "tests", "jack_e2e.sh")] if jack else [sys.executable, os.path.join(ROOT, "tests", "daemon_test.py")]
    p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout


failed = 0
work = tempfile.mkdtemp(prefix="plugin-hostd-sabotage.")
try:
    for entry in SABOTAGE:
        what, path, text, repl, name = entry[:5]
        jack = entry[5] if len(entry) > 5 else False
        if jack in ("jack", "lv2") and not os.environ.get("OMX_CLAP_HOST"):
            print("skip sabotage (no OMX_CLAP_HOST): %s" % what)
            continue
        if entry[5:] == ("lv2",) and not all(os.environ.get(v) for v in ("MOD_HOST", "LV2_DIR", "LV2_URI", "LV2_BUNDLE", "LV2_PARAM")):
            print("skip sabotage (no LV2 bundle to drive mod-host with): %s" % what)
            continue
        tree = os.path.join(work, "t")
        shutil.rmtree(tree, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tree, "src"))
        shutil.copytree(os.path.join(ROOT, "include"), os.path.join(tree, "include"))
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

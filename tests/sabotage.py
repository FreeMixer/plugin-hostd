# SPDX-License-Identifier: GPL-3.0-or-later
# Break the daemon on purpose, one guard at a time, and require the named test to go red; the unbroken daemon must
# pass the same test first, or a red proves nothing. A guard whose sabotage leaves its test green is decoration.
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.path.abspath(os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))

# (what is broken, file, text, replacement, the test that must go red[, "jack"]); a "jack" test runs in tests/jack_e2e.sh
# over the real workers and is skipped when OMX_CLAP_HOST is not set; "meters" is a jack test that also needs
# omx-clap-host's FAKE_COMPRESSOR_CLAP and JACK_METER_SOURCE and is skipped without them; "info" one that needs its FAKE_CLAP; "lv2" is a jack test that also needs mod-host and
# an LV2 bundle (MOD_HOST, LV2_DIR, LV2_URI, LV2_BUNDLE, LV2_PARAM) and is skipped without them; "pin" breaks
# include/plugin-hostd/pin.h and runs tests/pin_test.c; "readme" breaks README.md or BUILDING.md and runs
# tests/readme_build.py, with no daemon to build; "probeschema" breaks protocol/probe-output.schema.json and runs
# tests/probe_schema.py; "relay" breaks src/relay.c and runs tests/relay_test.c; "history" breaks src/history.c or src/fsutil.c and runs tests/history_test.c; "proc" breaks src/proc.c and runs tests/proc_test.c; "alloc" breaks src/relay.c or src/lv2.c and runs make test-alloc; "contract" breaks the probe runner or the generator and runs tests/contract_derived.py; "consumer" breaks the header and compiles tests/consumer.c against it; "probe" breaks src/probe.c and runs tests/probe_test.py; "nopins" breaks the packaging or a workflow and runs tests/no_pins.py; "ciguards" breaks a workflow and runs tests/ci_guards.py;
# "vocabulary" breaks the probe schema, its template or a copy of omx-contract's omx-vocabulary.schema.json and runs
# tests/vocabulary_derived.py; "verbtable" breaks the header and runs tests/verb_table.py; "presetschema" breaks
# protocol/preset.schema.json and runs tests/preset_format.py
SABOTAGE = [
    ("a runner that refuses unshare passes build-and-test with a warning", ".github/workflows/ci.yml",
     '            echo "::error::test-jack did not run: this runner refuses a private user and pid namespace with its own /proc"\n            exit 1\n',
     '            echo "::warning::test-jack SKIPPED"\n', "every if unshare in the workflows fails", "ciguards"),
    ("the ready marker is looked for in the first page of the worker's log only", "src/proc.c",
     "while (!found && (n = read(fd, buffer + held, sizeof(buffer) - 1 - held)) > 0)",
     "while (!found && held == 0 && (n = read(fd, buffer + held, sizeof(buffer) - 1 - held)) > 0)",
     "a_worker_that_warns_more_than_a_page_before_ready_still_starts"),
    ("the verb tail is not replayed", "src/supervisor.c",
     "if (replay_line(w, i->tail[m].line) != RPC_OK)", "if (0 && replay_line(w, i->tail[m].line) != RPC_OK)",
     "own_crash_respawns_only_that_instance_and_replays_it"),
    ("the checkpoint is not loaded", "src/supervisor.c", "    if (any_ckpt)\n", "    if (0 && any_ckpt)\n",
     "replay_is_text_identical_and_state_checkpoint_is_byte_identical"),
    ("connections are not replayed", "src/supervisor.c", "for (m = 0; m < i->nconns; m++)\n    {\n        if (replay_line_code(w, i->conns[m]",
     "for (m = 0; m < 0; m++)\n    {\n        if (replay_line_code(w, i->conns[m]", "connections_are_replayed_and_disconnect_forgets"),
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
    ("a nice the daemon could not apply is not logged", "src/proc.c", "    if (errno == 0 && have != env->nice)\n",
     "    if (0)\n", "worker_env_reaches_new_and_running_workers"),
    ("worker_env is not applied to a running worker", "src/supervisor.c", "proc_apply_env(g_workers[n]->pid, &g_env[f]);", ";",
     "worker_env_reaches_new_and_running_workers"),
    ("a refused connect is never asked again", "src/supervisor.c", "        else if (w->state == W_UP && w->npend)\n            pend_retry(w, now);",
     "", "a_connect_the_new_worker_cannot_make_yet_is_asked_again"),
    ("connections are not replayed, so a killed strip never gets its audio back", "src/supervisor.c",
     "for (m = 0; m < i->nconns; m++)\n    {\n        if (replay_line_code(w, i->conns[m]", "for (m = 0; m < 0; m++)\n    {\n        if (replay_line_code(w, i->conns[m]",
     "audio_of_the_other_strip_never_changes_when_one_worker_is_killed", "jack"),
    ("an own lv2 worker keeps the whole bundle set", "src/supervisor.c", "    return f->narrow_world(&g_conf, dir, &uri, 1);",
     "    return NULL;", "lv2_own_worker_sees_one_bundle_and_replays_after_a_kill", "lv2"),
    ("an LV2 strip's parameter writes are not replayed to the respawned mod-host", "src/supervisor.c",
     "    for (m = 0; m < i->ntail; m++)\n        if (replay_line(w, i->tail[m].line) != RPC_OK)",
     "    for (m = 0; m < 0; m++)\n        if (replay_line(w, i->tail[m].line) != RPC_OK)",
     "lv2_own_worker_sees_one_bundle_and_replays_after_a_kill", "lv2"),
    ("the checkpoint is not loaded after a real respawn", "src/supervisor.c", "    if (any_ckpt)\n", "    if (0 && any_ckpt)\n",
     "clap_own_crash_replays_bit_identically_and_the_neighbour_never_notices", "jack"),
    ("add checks no pin", "src/supervisor.c", "rc = pins_check(format, fwd, search_of(fmt), &layout);\n        /* a plugin", "rc = SUCCESS;\n        /* a plugin",
     "an_unpinned_plugin_is_refused_under_strict_and_no_worker_starts"),
    ("a pin in a scheme this version does not know is a pin", "src/pins.c",
     "if (!p || (strcmp(p->layout, PHD_PIN_LAYOUT_UNKNOWN) && strcmp(p->scheme, PHD_PIN_LAYOUT_SCHEME)))", "if (!p)",
     "an_unpinned_plugin_is_refused_under_strict_and_no_worker_starts"),
    ("a file whose digest differs passes", "src/pins.c", "else if (phd_pin_fd_digest(fd, hex) != 0 || strcmp(hex, want))",
     "else if (phd_pin_fd_digest(fd, hex) != 0)", "a_swapped_clap_binary_is_refused_before_any_worker_sees_add"),
    ("a pin need not hold the .clap it admits", "src/pins.c", "        if (held(p, files.name[n]) < 0)\n            rc = pin_refuse(uri, files.name[n], \"is named by the plugin", "        if (0)\n            rc = pin_refuse(uri, files.name[n], \"is named by the plugin",
     "a_swapped_clap_binary_is_refused_before_any_worker_sees_add"),
    ("the layout pin is not handed to the CLAP worker", "src/supervisor.c", "    if (layout && format->layout_check)\n", "    if (0)\n",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("a worker's refusal of the layout pin is not a refusal", "src/supervisor.c",
     "        if (rc == RPC_OK && resp_code(reply) >= 0)\n        {\n            free(reply);", "        if (rc == RPC_OK)\n        {\n            free(reply);",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("a worker that does not answer pin_expect is a failed instantiation", "src/supervisor.c",
     "            code = PHD_ERR_VERB_DROPPED;\n", "", "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("the pin_expect a worker went with is not named", "src/supervisor.c",
     "            event(PHD_EVENT_VERB_DROPPED_FMT, id, pin_expect_line(id, layout));\n", "",
     "a_changed_layout_is_refused_by_the_worker_and_reaches_the_client"),
    ("the manifest may name a file the pin does not hold", "src/pins.c", "        if (held(p, files.name[n]) < 0)\n            rc = pin_refuse(uri, files.name[n], \"is named by the plugin", "        if (0)\n            rc = pin_refuse(uri, files.name[n], \"is named by the plugin",
     "an_lv2_bundle_is_pinned_by_its_manifest_binary_and_seealso"),
    ("the manifest's bytes are not compared with the pin", "src/pins.c", "else if (phd_pin_fd_digest(fd, hex) != 0 || strcmp(hex, want))",
     "else if (phd_pin_fd_digest(fd, hex) != 0)", "an_lv2_bundle_is_pinned_by_its_manifest_binary_and_seealso"),
    ("a pinned LV2 plugin may ask for a pool", "src/supervisor.c",
     "        if (format->pinned_own_only)\n        {\n            if (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)))\n"
     "                return sup_resp(PHD_ERR_PLACEMENT_INVALID);\n", "        if (format->pinned_own_only)\n        {\n", "a_pinned_lv2_plugin_gets_a_worker_of_its_own"),
    ("a pinned LV2 plugin follows a policy into a pool", "src/supervisor.c",
     "            snprintf(place, sizeof(place), PHD_PLACE_OWN);\n        }\n        /* first-use", "        }\n        /* first-use",
     "a_pinned_lv2_plugin_gets_a_worker_of_its_own"),
    ("a pin's path may hold a separator of pin_set's words", "src/pins.c",
     "if (!*path || *path == '/' || strpbrk(path, PHD_PIN_PATH_EXCLUDED))", "if (!*path || *path == '/')",
     "what_cannot_be_pinned_is_refused_and_never_pinned_in_part"),
    ("a pin_set line may be longer than line_max", "src/verbs.c", "|| strlen(line) > PHD_LINE_MAX ||", "|| 0 ||",
     "what_cannot_be_pinned_is_refused_and_never_pinned_in_part"),
    ("a manifest's base is taken for none", "src/lv2.c",
     "        rc = pin_refuse(uri, MANIFEST, \"sets a base the daemon does not resolve\");\n", "        ;\n",
     "what_cannot_be_pinned_is_refused_and_never_pinned_in_part"),
    ("a percent-encoded name is taken as written", "src/lv2.c",
     "        if (strstr(names.name[n], PHD_PIN_PERCENT))\n", "        if (0)\n",
     "what_cannot_be_pinned_is_refused_and_never_pinned_in_part"),
    ("a plugin with no pin is not given one", "src/supervisor.c", "        if (rc == PHD_ERR_PIN_ABSENT && first_use && !pins_known(fwd))",
     "        if (0)", "first_use_pins_an_unpinned_plugin_and_runs_it_isolated"),
    ("a plugin pinned on first use may share a worker", "src/supervisor.c", "        else if (first_use && !pins_in_process(fwd))",
     "        else if (0)", "first_use_pins_an_unpinned_plugin_and_runs_it_isolated"),
    ("a changed plugin is refused and not announced", "src/supervisor.c",
     "    if (code == PHD_ERR_PIN_BINARY_MISMATCH)\n        event(PHD_EVENT_PIN_CHANGED_FMT, uri, PHD_PIN_CHANGED_FILES);\n",
     "    if (code == PHD_ERR_PIN_BINARY_MISMATCH)\n        ;\n", "a_plugin_changed_after_first_use_is_refused_with_an_event_until_accepted"),
    ("pin_accept takes nothing new", "src/pins.c", "    return record(format, uri, search);\n}\n\nint pins_set_layout",
     "    return SUCCESS;\n}\n\nint pins_set_layout", "a_plugin_changed_after_first_use_is_refused_with_an_event_until_accepted"),
    ("the store is not written", "src/pins.c", "    pin.learned = 1;\n    pin_put(&pin);\n    store_save();\n",
     "    pin.learned = 1;\n    pin_put(&pin);\n", "first_use_pins_an_unpinned_plugin_and_runs_it_isolated"),
    ("a corrupt line of the store is dropped by the next save", "src/pins.c",
     "        fprintf(file, \"%s\\n\", g_held[n]);\n", "        ;\n",
     "a_corrupt_store_line_is_kept_announced_and_its_plugin_is_not_learned_again"),
    ("a plugin whose store line is corrupt is learned again", "src/pins.c",
     "(g_store_unreadable || uri_held(uri))", "(0)",
     "a_corrupt_store_line_is_kept_announced_and_its_plugin_is_not_learned_again"),
    ("a store that could not be read is learned into", "src/pins.c",
     "(g_store_unreadable || uri_held(uri))", "(uri_held(uri))",
     "a_store_that_cannot_be_written_is_announced_and_a_store_that_cannot_be_read_blocks_learning"),
    ("a format row with no pin_collect is registered", "src/formats.c",
     "    if (!f->pin_collect)\n        return reject(f,", "    if (0)\n        return reject(f,", "format_test", "format"),
    ("a format row with no worker is registered", "src/formats.c",
     "    if (!f->worker)\n        return reject(f,", "    if (0)\n        return reject(f,", "format_test", "format"),
    ("a format row nobody answers the instance verbs for is registered", "src/formats.c",
     "    if (!f->native_instance_verbs && !f->param_info)\n", "    if (0)\n", "format_test", "format"),
    ("the pin rule of a registered format is the first two formats'", "src/supervisor.c",
     "        rc = pins_check(format, fwd, search_of(fmt), &layout);\n        /* a plugin", "        rc = SUCCESS;\n        /* a plugin", "format_test", "format"),
    ("an overlong store line is kept cut at the read buffer", "src/pins.c", "                held_add(line);", "                held_add(strndup(line, LINE_MAX_PIN - 1));",
     "an_overlong_store_line_is_one_held_line_and_its_tail_is_not_a_pin"),
    ("a learned line may be longer than pin_set takes", "src/pins.c", "line_size(&pin) + LINE_RESERVE > PHD_LINE_MAX", "0",
     "a_pin_line_too_long_for_pin_set_is_refused_when_learned"),
    ("a replayed add is not checked again", "src/supervisor.c", "    i->unreplayed = 0;\n    if (!g_conf.require_pins)",
     "    i->unreplayed = 0;\n    if (1)", "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("the verbs of an instance its pin refused on replay are replayed", "src/supervisor.c",
     "        if (!w->inst[n]->unreplayed && replay_tail(w, w->inst[n]) < 0)",
     "        if (replay_tail(w, w->inst[n]) < 0)", "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a refused replay is not announced", "src/supervisor.c", "    event(PHD_EVENT_REPLAY_REFUSED_FMT, i->id, code);\n", "",
     "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a worker's refusal of a replayed add is taken for the instance", "src/supervisor.c",
     "    if (code < 0)\n    {\n        replay_refused(w, i, add, code);\n        return 0;\n    }\n", "",
     "a_layout_pinned_again_while_its_worker_was_down_is_refused_by_the_replayed_add"),
    ("a worker's feedback is not read", "src/supervisor.c", "    if (relay_add(w->fb_fd) != 0)\n", "    if (0)\n",
     "worker_feedback_reaches_the_controller_verbatim_and_in_order"),
    ("the relay writes nothing to the controller", "src/relay.c",
     "            send_line(start, nul - start + 1);\n", "",
     "worker_feedback_reaches_the_controller_verbatim_and_in_order"),
    ("monitor_output is not in the ledger", "src/supervisor.c", "    { MONITOR_OUTPUT, KIND_HOST, 2 },\n", "",
     "a_respawned_worker_reports_the_same_outputs_once_each"),
    ("a repeated monitor_output is replayed twice", "src/supervisor.c", "    { MONITOR_OUTPUT, KIND_HOST, 2 },",
     "    { MONITOR_OUTPUT, KIND_HOST, 0 },", "a_respawned_worker_reports_the_same_outputs_once_each"),
    ("a worker is read only while a controller listens", "src/relay.c",
     "            i = (first + j) % g_nsrc;\n            if (!g_src[i].eof)\n",
     "            i = (first + j) % g_nsrc;\n            if (!g_src[i].eof && g_client >= 0)\n",
     "a_worker_is_read_when_no_controller_reads_the_feedback"),
    ("an LV2 instance's track_info and queries go to mod-host", "src/supervisor.c", "    else if (format_at(i->fmt)->native_instance_verbs)\n",
     "    else if (1)\n", "an_lv2_instance_is_answered_by_the_daemon_and_its_worker_never_sees_the_verbs"),
    ("an LV2 worker gets track_info on a replay", "src/supervisor.c",
     "if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(", "if (i->track_info && replay_line(",
     "an_lv2_instance_is_answered_by_the_daemon_and_its_worker_never_sees_the_verbs"),
    ("an LV2 param_info answers -511 for a symbol mod-host does not know", "src/lv2.c",
     "code == ERR_HOST_INVALID_PARAM_SYMBOL ? ERR_HOST_INVALID_PARAM_SYMBOL : PHD_ERR_NO_PARAM_CONTRACT",
     "PHD_ERR_NO_PARAM_CONTRACT", "an_lv2_instance_is_answered_by_the_daemon_and_its_worker_never_sees_the_verbs"),
    ("lv2_worker omx-clap-host does not route to the adapter row", "src/lv2.c",
     "    if (!strcmp(worker, PHD_LV2_WORKER_CLAP_HOST))\n        return PHD_FORMAT_LV2_CLAP;\n", "",
     "lv2_worker_omx_clap_host_runs_the_plugin_in_the_clap_program_on_the_adapter_row"),
    ("the adapter worker is given the uri without its lv2: prefix", "src/formats.c", "        .worker_prefix = LV2_PREFIX,\n", "",
     "lv2_worker_omx_clap_host_runs_the_plugin_in_the_clap_program_on_the_adapter_row"),
    ("a plugin's own lv2 worker is ignored", "src/lv2.c", "    return pick ? pick : conf->lv2_worker;", "    return conf->lv2_worker;",
     "a_plugin_can_be_given_its_own_lv2_worker_and_taken_back"),
    ("lv2_worker_set takes any word", "src/lv2.c", "(!worker_is(worker) || strlen(worker) >= CONF_SIZE_word)", "strlen(worker) >= CONF_SIZE_word",
     "a_plugin_can_be_given_its_own_lv2_worker_and_taken_back"),
    ("the adapter row's worker does not answer the instance verbs", "src/formats.c",
     "        .native_instance_verbs = 1,\n        .adapter = 1,", "        .native_instance_verbs = 0,\n        .param_info = lv2_param_info,\n        .adapter = 1,",
     "the_adapter_row_answers_the_instance_verbs_from_its_worker_and_replays_track_info"),
    ("the adapter row checks the layout", "src/formats.c",
     "        .layout_check = 0,\n        .pinned_own_only = 1,\n        .native_instance_verbs = 1,", "        .layout_check = 1,\n        .pinned_own_only = 1,\n        .native_instance_verbs = 1,",
     "the_adapter_row_keeps_the_pin_rules_of_the_lv2_row_and_checks_no_layout"),
    ("the adapter row pools pinned plugins", "src/formats.c",
     "        .layout_check = 0,\n        .pinned_own_only = 1,\n        .native_instance_verbs = 1,", "        .layout_check = 0,\n        .pinned_own_only = 0,\n        .native_instance_verbs = 1,",
     "the_adapter_row_keeps_the_pin_rules_of_the_lv2_row_and_checks_no_layout"),
    ("the adapter row's worker sees every bundle", "src/formats.c",
     "        .narrow_world = lv2_narrow_world,\n        .pin_collect = lv2_pin_collect,\n        .binary = lv2_binary,\n        .layout_check = 0,",
     "        .pin_collect = lv2_pin_collect,\n        .binary = lv2_binary,\n        .layout_check = 0,",
     "the_adapter_row_keeps_the_pin_rules_of_the_lv2_row_and_checks_no_layout"),
    ("the adapter's refusal answers the worker's own error", "src/supervisor.c",
     "    if (!automatic)\n        return sup_resp(PHD_ERR_LV2_ADAPTER_REFUSED);", "    if (!automatic)\n        return sup_resp(ERR_HOST_INSTANTIATION);",
     "a_plugin_the_adapter_refuses_answers_a_named_code_and_the_event_names_the_reason"),
    ("the adapter's reason is not read from its reply", "src/supervisor.c",
     "        if (refused)\n            lv2_refusal_reason(reply, why, sizeof(why));\n", "",
     "a_plugin_the_adapter_refuses_answers_a_named_code_and_the_event_names_the_reason"),
    ("the adapter's reason is the error code, not the word after it", "src/lv2.c", "for (word = 0; word < 2; word++)",
     "for (word = 0; word < 1; word++)", "the_code_of_a_refusal_is_the_one_on_the_reply_of_its_own_add"),
    ("a refusal that names no code is given the last code of the worker's log", "src/lv2.c",
     "    if (len > 0 && len < size)\n        snprintf(buf, size, \"%.*s\", (int)len, at);",
     "    if (len > 0 && len < size)\n        snprintf(buf, size, \"%.*s\", (int)len, at);\n"
     "    else\n        snprintf(buf, size, \"hosting.topology.wider-than-strip\");",
     "the_code_of_a_refusal_is_the_one_on_the_reply_of_its_own_add"),
    ("a plugin the adapter does not find is counted as a refusal", "src/supervisor.c",
     "int refused = format->adapter && resp_code(reply) == ERR_HOST_INSTANTIATION;",
     "int refused = format->adapter && (resp_code(reply) == ERR_HOST_INSTANTIATION || resp_code(reply) == ERR_HOST_INVALID_URI);",
     "a_plugin_the_adapter_does_not_find_is_not_found_and_no_refusal"),
    ("under auto a plugin the adapter does not find is not looked for by mod-host", "src/supervisor.c",
     "        if (absent && lv2_worker_is_auto(&g_conf, fwd))", "        if (0 && absent && lv2_worker_is_auto(&g_conf, fwd))",
     "a_plugin_the_adapter_does_not_find_is_not_found_and_no_refusal"),
    ("under auto a plugin the adapter does not find goes to mod-host for good", "src/supervisor.c",
     "            return add(fwd, id, placement, client, format_by_name(PHD_FORMAT_LV2));",
     "            lv2_adapter_refused(fwd);\n            return sup_add(fwd, id, placement, client);",
     "a_plugin_the_adapter_does_not_find_is_not_found_and_no_refusal"),
    ("auto does not remember what the adapter refused", "src/supervisor.c",
     "    lv2_adapter_refused(uri);\n    return sup_add(uri, id, placement, client);", "    return sup_resp(PHD_ERR_LV2_ADAPTER_REFUSED);",
     "under_auto_a_plugin_the_adapter_refuses_runs_on_mod_host_and_the_adapter_is_not_asked_again"),
    ("auto without the adapter's program fails instead of using mod-host", "src/supervisor.c",
     "    if (format_at(fmt)->adapter && !proc_have_binary(bin_of(fmt)) && lv2_worker_is_auto(&g_conf, fwd))",
     "    if (0 && format_at(fmt)->adapter && !proc_have_binary(bin_of(fmt)) && lv2_worker_is_auto(&g_conf, fwd))",
     "under_auto_a_plugin_the_adapter_refuses_runs_on_mod_host_and_the_adapter_is_not_asked_again"),
    ("lv2_worker takes any word", "src/conf.c", "ok |= !strcmp(conf->lv2_worker, name);", "ok |= 1;",
     "lv2_worker_must_be_one_of_the_declared_values"),
    ("a routed row that claims uris by a prefix is registered", "src/formats.c",
     "    if (f->routed && (f->prefix || f->fallback))\n        return reject(f,", "    if (0)\n        return reject(f,", "format_test", "format"),
    ("a row with an empty worker prefix is registered", "src/formats.c",
     "    if (f->worker_prefix && !*f->worker_prefix)\n        return reject(f,", "    if (0)\n        return reject(f,", "format_test", "format"),
    ("a row's route is ignored", "src/formats.c", "    return name ? format_by_name(name) : format;", "    return format;", "format_test", "format"),
    ("a routed row's worker is not given its prefix", "src/supervisor.c",
     "             format->worker_prefix ? format->worker_prefix : \"\", fwd,", "             \"\", fwd,",
     "lv2_worker_omx_clap_host_runs_the_plugin_in_the_clap_program_on_the_adapter_row"),
    ("track_info's kind is not checked", "include/plugin-hostd/protocol.h",
     "phd_track_kind(count == 5 ? word[4] : NULL) >= 0;", "1;",
     "a_clap_instance_is_routed_to_its_worker_and_its_reply_passed_through"),
    ("track_info is not replayed", "src/supervisor.c",
     "if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(", "if (0 && replay_line(",
     "track_info_is_replayed_once_after_the_add_and_before_the_state"),
    ("a whole worker line too long to relay is sent", "src/relay.c",
     "if (s->skip || (size_t)(nul - start) > LINE_LIMIT)", "if (s->skip)",
     "a_worker_line_too_long_to_relay_is_dropped_whole"),
    ("the end of a worker line too long to relay is sent as a line", "src/relay.c",
     "            s->skip = 1;\n", "",
     "a_worker_line_too_long_to_relay_is_dropped_whole"),
    ("a worker's remote_pages_changed is not relayed", "src/relay.c",
     "            send_line(start, nul - start + 1);\n", "",
     "remote_pages_changed_from_a_worker_reaches_the_controller"),
    ("a CLAP worker is not told track_info again after a kill", "src/supervisor.c",
     "if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(", "if (0 && replay_line(",
     "clap_track_info_and_remote_pages_reach_the_plugin_through_the_daemon", "info"),
    ("meters behind the daemon never reach the controller", "src/supervisor.c", "    if (relay_add(w->fb_fd) != 0)\n", "    if (0)\n",
     "clap_meters_reach_the_controller_through_the_daemon_and_survive_a_kill", "meters"),
    ("a SHA-256 round constant is wrong", "include/plugin-hostd/pin.h", "0x428a2f98, 0x71374491", "0x428a2f98, 0x71374490",
     "pin.h", "pin"),
    ("a tab in a name is not escaped", "include/plugin-hostd/pin.h", "*s == '\\t' ? \"\\\\t\" : ", "", "pin.h", "pin"),
    ("an LV2 port's properties are not sorted", "include/plugin-hostd/pin.h",
     "            qsort(props, p->nproperties, sizeof(*props), phd_layout_bytewise);\n", "", "pin.h", "pin"),
    ("a number declared by no port is written as its bits", "include/plugin-hostd/pin.h",
     "    if (!declared)\n", "    if (0)\n", "pin.h", "pin"),
    ("a plugin the adapter refused goes where the policy says", "src/supervisor.c",
     "&& lv2_refused_under_auto(&g_conf, fmt, fwd))", "&& 0)",
     "under_auto_a_refused_plugin_that_kills_mod_host_on_add_costs_only_its_own_worker"),
    ("an add the worker died on is not named by an event", "src/supervisor.c",
     "        if (code != PHD_ERR_VERB_DROPPED)\n            event(PHD_EVENT_VERB_DROPPED_FMT, id, line);\n", "",
     "under_auto_a_refused_plugin_that_kills_mod_host_on_add_costs_only_its_own_worker"),
    ("a feedback socket the relay has no memory to follow is left open", "src/relay.c",
     "            fprintf(stderr, \"relay: no memory to follow the feedback of fd %d\\n\", fd);\n            close(fd);\n",
     "            fprintf(stderr, \"relay: no memory to follow the feedback of fd %d\\n\", fd);\n", "relay_test", "relay"),
    ("a worker the relay has no memory to read is left to fill its socket", "src/relay.c",
     "                shutdown(s->fd, SHUT_RDWR);\n", "", "relay_test", "relay"),
    ("the relay thread polls a set it had no memory for", "src/relay.c", "        if (cap == 0)\n", "        if (0)\n",
     "relay_test", "relay"),
    ("a pin whose verdict is refused admits the add", "src/pins.c",
     "    if (rc == SUCCESS && !strcmp(p->verdict, PHD_PIN_VERDICT_REFUSED))\n", "    if (0)\n",
     "a_pin_whose_verdict_is_refused_refuses_the_add_with_its_own_code"),
    ("the runner's default rates are typed by hand again", "src/probe.c", ".rates = floor_rates(),",
     ".rates = \"44100,48000,96000,192000\",", "contract", "contract"),
    ("the generator does not hold the scales to the contract's order", "tools/protocol-gen.c",
     "PHD_PARAM_SCALES(X)\n#undef X\n_Static_assert(", "#undef X\n_Static_assert(", "contract", "contract"),
    ("the generator takes a scale word that is not the contract's", "tools/protocol-gen.c",
     "    if (!scales_are_the_contracts())\n        return 1;\n", "", "contract", "contract"),
    ("the generator types the latency methods by hand", "tools/protocol-gen.c", "VOCABULARY(MEASUREMENT_LATENCY_METHODS)\n",
     'static const char *const VOCAB_MEASUREMENT_LATENCY_METHODS[] = { "impulse-onset", "declared-port", "note-onset" };\n',
     "contract", "contract"),
    ("the generator does not hold a word list to its count", "tools/protocol-gen.c",
     '    _Static_assert(sizeof(VOCAB_##item) / sizeof(*VOCAB_##item) == OMX_##item##_COUNT, "omx-contract\'s " #item ": not as many words as its count");\n',
     "\n", "contract", "contract"),
    ("two errors share a code", "include/plugin-hostd/protocol.h", "#define PHD_ERR_NOTE_QUEUE_FULL     (-517)",
     "#define PHD_ERR_NOTE_QUEUE_FULL     (-516)", "consumer", "consumer"),
    ("a gesture the relay has no memory to hold takes the table with it", "src/relay.c",
     "        if (held == NULL)\n            return;\n", "", "alloc_test", "alloc"),
    ("a refusal the lv2 table has no memory for takes the table with it", "src/lv2.c",
     "    if (grown == NULL)\n        return;\n", "", "alloc_test", "alloc"),
    ("a pick the lv2 table has no memory for takes the table with it", "src/lv2.c",
     "        if (grown == NULL)\n            return -1;\n", "", "alloc_test", "alloc"),
    ("the host's pin overrides a pins.d refusal", "src/pins.c", "    pin_t *p = pkg_refusal(uri);\n\n    if (!p)\n",
     "    pin_t *p = NULL;\n\n    if (!p)\n", "a_pins_d_refusal_wins_over_any_other_pins_d_pin_and_over_the_host"),
    ("pin_set overrides a pins.d refusal", "src/pins.c", "    if (pkg_refusal(pin.uri))\n", "    if (0)\n", "a_pins_d_refusal_wins_over_any_other_pins_d_pin_and_over_the_host"),
    ("pin_accept overrides a pins.d refusal", "src/pins.c", "    if (pkg_refusal(bare(uri)))\n", "    if (0)\n", "a_pins_d_refusal_wins_over_any_other_pins_d_pin_and_over_the_host"),
    ("of two pins.d pins of one uri the later wins over a refusal", "src/pins.c",
     "    if (old && refused(old) && !refused(pin))\n", "    if (0)\n", "a_pins_d_refusal_wins_over_any_other_pins_d_pin_and_over_the_host"),
    ("pins.d files are read in reverse name order", "src/pins.c", "    return strcmp((*a)->d_name, (*b)->d_name);",
     "    return strcmp((*b)->d_name, (*a)->d_name);", "a_pins_d_pin_admits_its_plugin_and_of_two_files_the_last_by_name_wins"),
    ("a pins.d file need not end in .pins", "src/pins.c",
     "n > suffix && !strcmp(entry->d_name + n - suffix, PINS_SUFFIX)", "n > 0",
     "a_pins_d_pin_admits_its_plugin_and_of_two_files_the_last_by_name_wins"),
    ("a package pin holds over the host's", "src/pins.c",
     "        p = find_in(g_pins, g_npins, uri);\n    return p ? p : find_in(g_pkg, g_npkg, uri);",
     "        p = find_in(g_pkg, g_npkg, uri);\n    return p ? p : find_in(g_pins, g_npins, uri);",
     "the_host_holds_over_a_pins_d_pin_that_is_not_a_refusal"),
    ("a bad pins.d line ends the start", "src/pins.c", "    int strict = layer == LAYER_FILE,",
     "    int strict = layer != LAYER_STORE,", "a_bad_pins_d_line_or_file_is_skipped_and_the_rest_is_read"),
    ("a hidden pins.d file is read", "src/pins.c", "entry->d_name[0] != '.' && ", "",
     "a_pins_d_pin_admits_its_plugin_and_of_two_files_the_last_by_name_wins"),
    ("pins_dir is not read", "src/pins.c", "    if (*dir)\n        pkg_read(dir);\n", "",
     "a_pins_d_pin_admits_its_plugin_and_of_two_files_the_last_by_name_wins"),
    ("the build steps are back on the README", "README.md", "Building from source: see [BUILDING.md](BUILDING.md).",
     "Building from source:\n\n    make\n\nsee [BUILDING.md](BUILDING.md).", "README.md runs no build tool", "readme"),
    ("BUILDING.md lost its build command", "BUILDING.md", "    make [MOD_HOST_DIR=<mod-host checkout>]\n", "",
     "README.md runs no build tool", "readme"),
    ("the spec lost the floor of omx-clap-host-tests", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.21.0\n", "", "no pin anywhere", "nopins"),
    ("debian/control lost the floor of omx-clap-host-tests", "debian/control",
     "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n", "", "no pin anywhere", "nopins"),
    ("the spec caps omx-clap-host-tests with a ceiling again", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.21.0\n", "BuildRequires: omx-clap-host-tests >= 0.21.0\nBuildRequires: omx-clap-host-tests < 0.8\n",
     "no pin anywhere", "nopins"),
    ("debian/control caps omx-clap-host-tests with a ceiling again", "debian/control",
     "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n", "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n               omx-clap-host-tests (<< 0.8~),\n",
     "no pin anywhere", "nopins"),
    ("the spec caps omx-clap-host-tests with a '<=' ceiling", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.21.0\n", "BuildRequires: omx-clap-host-tests >= 0.21.0\nBuildRequires: omx-clap-host-tests <= 0.9\n",
     "no pin anywhere", "nopins"),
    ("the spec caps omx-clap-host-tests with an exact '=' ceiling", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.21.0\n", "BuildRequires: omx-clap-host-tests >= 0.21.0\nBuildRequires: omx-clap-host-tests = 0.9.0\n",
     "no pin anywhere", "nopins"),
    ("the spec caps omx-clap-host-tests with a '<' ceiling", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.21.0\n", "BuildRequires: omx-clap-host-tests >= 0.21.0\nBuildRequires: omx-clap-host-tests < 0.10\n",
     "no pin anywhere", "nopins"),
    ("debian/control caps omx-clap-host-tests with a '<=' ceiling", "debian/control",
     "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n", "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n               omx-clap-host-tests (<= 0.9) <!nocheck>,\n",
     "no pin anywhere", "nopins"),
    ("debian/control caps omx-clap-host-tests with an exact '=' ceiling", "debian/control",
     "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n", "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n               omx-clap-host-tests (= 0.9.0) <!nocheck>,\n",
     "no pin anywhere", "nopins"),
    ("debian/control caps omx-clap-host-tests with a '<' ceiling", "debian/control",
     "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n", "               omx-clap-host-tests (>= 0.21.0~) <!nocheck>,\n               omx-clap-host-tests (< 0.10) <!nocheck>,\n",
     "no pin anywhere", "nopins"),
    ("a workflow pins omx-clap-core by a ref variable again", ".github/workflows/ci.yml",
     "permissions:\n  contents: read\n", "permissions:\n  contents: read\n\nenv:\n  OMX_CLAP_HOST_REF: v0.4.0\n",
     "no pin anywhere", "nopins"),
    ("a workflow checks omx-clap-core out again", ".github/workflows/ci.yml",
     "      - uses: actions/checkout@v4\n\n      # the OpenMixer channel: where the BuildRequires Fedora does not carry (omx-clap-host-tests) come from\n      - name: Add the OpenMixer channel\n        uses: FreeMixer/.github/.github/actions/add-openmixer@v1\n\n      # the worker and the fixtures",
     "      - uses: actions/checkout@v4\n        with:\n          repository: FreeMixer/omx-clap-core\n\n      # the OpenMixer channel: where the BuildRequires Fedora does not carry (omx-clap-host-tests) come from\n      - name: Add the OpenMixer channel\n        uses: FreeMixer/.github/.github/actions/add-openmixer@v1\n\n      # the worker and the fixtures",
     "no pin anywhere", "nopins"),
    ("lv2_worker_set leaves the adapter's refusal in place", "src/supervisor.c", "    lv2_refusals_forget(fwd);\n", "",
     "lv2_worker_set_makes_the_adapter_be_asked_again_about_that_plugin_only"),
    ("pin_set leaves the adapter's refusals in place", "src/verbs.c", "    if (rc == SUCCESS)\n        lv2_refusals_forget(NULL);\n    return rc;",
     "    return rc;", "pin_set_and_pin_clear_make_the_adapter_be_asked_again"),
    ("pin_clear leaves the adapter's refusals in place", "src/verbs.c", "        if (rc == SUCCESS)\n            lv2_refusals_forget(NULL);\n        return sup_resp(rc);",
     "        return sup_resp(rc);", "pin_set_and_pin_clear_make_the_adapter_be_asked_again"),
    ("the tempo is not handed to a new or a respawned worker", "src/supervisor.c", "    if (host_settings_replay(w) != 0)\n",
     "    if (0)\n", "tempo_and_transport_are_handed_to_a_respawned_worker_before_its_add"),
    ("a repeated host setting does not replace the earlier one", "src/supervisor.c",
     "        if (verb_is(g_host_settings[n], g_host_setting_verbs[v]))\n", "        if (0)\n",
     "tempo_and_transport_are_handed_to_a_respawned_worker_before_its_add"),
    ("a host setting is kept whatever its words", "src/supervisor.c",
     "    if (v == HOST_SETTINGS || !format_words(g_host_setting_verbs[v], tok, ntok))", "    if (v == HOST_SETTINGS)",
     "tempo_and_transport_are_handed_to_a_respawned_worker_before_its_add"),
    ("a worker that refuses the tempo is a failed spawn", "src/supervisor.c",
     "        if (replay_line_code(w, g_host_settings[n], &code) != RPC_OK)",
     "        if (replay_line_code(w, g_host_settings[n], &code) != RPC_OK || code < 0)",
     "a_tempo_the_worker_refuses_is_kept_written_and_the_worker_still_comes_back"),
    ("a note's words are not checked", "src/supervisor.c",
     "    else if (phd_is_note_verb(word[0]) && !phd_note_valid(word, count))\n", "    else if (0)\n",
     "notes_reach_a_clap_worker_unchanged_and_an_effect_refuses_them"),
    ("a negative zero is a number", "include/plugin-hostd/protocol.h", "        if (v == 0)\n            return 0;\n        v = -v;",
     "        v = -v;", "notes_reach_a_clap_worker_unchanged_and_an_effect_refuses_them"),
    ("a note's velocity range is not checked", "include/plugin-hostd/protocol.h",
     "phd_number_in(word[4], on ? 1 : 0, PHD_NOTE_VELOCITY_MAX)", "phd_number_in(word[4], 0, 1000)",
     "notes_reach_a_clap_worker_unchanged_and_an_effect_refuses_them"),
    ("a note on an LV2 instance of mod-host is answered as played", "src/supervisor.c",
     "        reply = sup_resp(PHD_ERR_NOTES_BY_JACK);", "        reply = sup_resp(SUCCESS);",
     "an_lv2_instance_on_mod_host_answers_notes_by_jack_and_mod_host_never_sees_them"),
    ("a note is kept in the ledger and replayed", "include/plugin-hostd/protocol.h",
     'X(NOTE_ON, PHD_VERB_NOTE_ON, "<instance> <channel> <key> <velocity>", "resp 0", NONE,',
     'X(NOTE_ON, PHD_VERB_NOTE_ON, "<instance> <channel> <key> <velocity>", "resp 0", REPLACE,',
     "notes_are_never_replayed"),
    ("a gesture its worker did not end stays held", "src/relay.c",
     "            gestures_end(&g_src[i]);\n            free(g_src[i].buf);", "            free(g_src[i].buf);",
     "a_gesture_its_worker_did_not_end_is_ended_by_the_daemon_before_worker_died"),
    ("a removed instance's gesture stays held while its worker lives", "src/supervisor.c",
     "    relay_instance_gone(id);\n", "",
     "a_gesture_of_a_removed_instance_is_ended_once_though_its_pool_worker_stays"),
    ("an ended gesture is ended again when its worker dies", "src/relay.c",
     "    else if (!begin && n < s->nheld)\n", "    else if (0)\n",
     "a_gesture_the_value_it_moved_and_a_suggested_page_reach_the_controller_unchanged_and_in_order"),
    ("an LV2 instance's preset list goes to mod-host", "src/supervisor.c",
     "    else if (!strcmp(word[0], OMX_VERB_PRESET_LIST) || !strcmp(word[0], OMX_VERB_PRESET_GET))\n        reply = sup_resp(PHD_ERR_NO_PRESET_LIST);",
     "    else if (!strcmp(word[0], OMX_VERB_PRESET_LIST) || !strcmp(word[0], OMX_VERB_PRESET_GET))\n        reply = sup_call(id, line);",
     "presets_are_listed_by_a_clap_worker_and_an_lv2_instance_on_mod_host_answers_no_list"),
    ("pin_accept leaves the adapter's refusals in place", "src/supervisor.c", "    if (rc == SUCCESS)\n        lv2_refusals_forget(NULL);\n    return sup_resp(rc);",
     "    return sup_resp(rc);", "pin_accept_makes_the_adapter_be_asked_again"),
    ("the probe document is written only when the child ended well", "src/probe.c", "    if (o.out)\n    {\n        char tmp[PATH_MAX];",
     "    if (o.out && exit_code == 0)\n    {\n        char tmp[PATH_MAX];", "a_crash_keeps_the_steps_before_it", "probe"),
    ("the wall clock never passes", "src/probe.c", "        if (left <= 0)\n        {\n            r->killed_by_deadline = 1;",
     "        if (0)\n        {\n            r->killed_by_deadline = 1;", "a_plugin_that_hangs_ends_at_the_wall_clock_and_the_tree_is_killed", "probe"),
    ("what the plugin left behind is not killed", "src/probe.c", "            int n = kill_tree(r->pid, SIGKILL);",
     "            int n = 0;", "a_process_the_plugin_left_in_its_own_session_is_gone_after_the_run", "probe"),
    ("a limit not applied is not listed", "src/probe.c", "        note_unavailable(NOT_APPLIED[i], LIMIT_NOT_IMPLEMENTED);",
     "        (void)NOT_APPLIED;", "every_limit_the_set_asks_for_is_applied_or_listed_unavailable", "probe"),
    ("--require is ignored", "src/probe.c", "        if (!met)\n        {\n            fprintf(stderr, RUNNER_NAME \": --require",
     "        if (0)\n        {\n            fprintf(stderr, RUNNER_NAME \": --require",
     "a_limit_that_was_required_and_is_not_applied_refuses_the_run_and_writes_no_document", "probe"),
    ("the child's file size limit is not set", "src/probe.c", "    put_rlimit(RLIMIT_FSIZE, (rlim_t)o->file_bytes, (rlim_t)o->file_bytes);\n",
     "", "the_limits_reach_the_child", "probe"),
    ("the child may gain privileges", "src/probe.c", "    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)\n        _exit(120);\n",
     "", "the_limits_reach_the_child", "probe"),
    ("the child is not made to die with the runner", "src/probe.c", "    prctl(PR_SET_PDEATHSIG, SIGKILL);\n", "",
     "the_limits_reach_the_child", "probe"),
    ("the child is not pinned", "src/probe.c", "    if (pin_option && sched_setaffinity(0, sizeof(*pinned), pinned) != 0)\n        _exit(120);\n",
     "", "the_limits_reach_the_child", "probe"),
    ("an LV2 plugin is pinned and never measured", "src/probe.c", "    if (strcmp(*outcome, OUT_OK))\n        return 0;\n\n    snprintf(rate_s",
     "    return 0;\n\n    snprintf(rate_s", "an_lv2_plugin_is_pinned_then_measured_at_the_highest_rate", "probe"),
    ("an LV2 plugin no bundle holds gets a document", "src/probe.c", "WEXITSTATUS(r->status) == 3 &&\n        !jbool(*pin, \"found\", 1))",
     "WEXITSTATUS(r->status) == 3 &&\n        0)", "an_lv2_plugin_no_bundle_holds_is_3_and_has_no_document", "probe"),
    ("the LV2 passes run past the wall clock", "src/probe.c", "&pinned, pin_option, t0 + o.wall_s * 1000, &r, &pin_line",
     "&pinned, pin_option, t0 + 3600000, &r, &pin_line", "an_lv2_plugin_that_hangs_ends_at_the_wall_clock", "probe"),
    ("the end of the LV2 measurement is not the run's", "src/probe.c", "    *outcome = child_end(\"lifecycle\", o, r, complete);\n    return 0;\n}",
     "    *complete = 1;\n    return 0;\n}", "an_lv2_crash_keeps_the_pin_and_names_the_signal", "probe"),
    ("an LV2 plugin of which nothing is pinned is refused with no code", "src/probe.c",
     "RUNNER_NAME \": %s: %s: %s; no document, it would have no binary\\n\", o.plugin, run_outcome,",
     "RUNNER_NAME \": %s: %s%s; no document, it would have no binary\\n\", o.plugin, \"\",",
     "an_lv2_plugin_of_which_nothing_is_pinned_is_refused_by_code_with_no_document", "probe"),
    ("the LV2 measurement runs without the interposer", "src/probe.c",
     "    preload_for_measurement(o->child);\n", "    interposer_beside(o->child);\n",
     "an_lv2_plugin_is_pinned_then_measured_at_the_highest_rate", "probe"),
    ("the CLAP prober runs without the interposer", "src/probe.c",
     "        preload_for_measurement(o.child);\n", "        interposer_beside(o.child);\n",
     "a_clap_child_runs_under_the_interposer_beside_it", "probe"),
    ("the measured child keeps the preload the runner had", "src/probe.c",
     '        setenv("LD_PRELOAD", g_interposer, 1);\n    else\n        unsetenv("LD_PRELOAD");\n',
     '        setenv("LD_PRELOAD", g_saved_preload[0] ? g_saved_preload : g_interposer, 1);\n    else\n        unsetenv("LD_PRELOAD");\n',
     "a_preload_the_runner_had_is_dropped_for_the_measurement_and_recorded", "probe"),
    ("a dropped preload is not recorded", "src/probe.c",
     '        snprintf(g_dropped_preload, sizeof(g_dropped_preload), "%s", g_saved_preload);\n', "        ;\n",
     "a_preload_the_runner_had_is_dropped_for_the_measurement_and_recorded", "probe"),
    ("a dropped preload is left out of the run's tools", "src/probe.c",
     '        if (g_dropped_preload[0])\n        {\n            sb_printf(&doc, ", \\"droppedPreload\\": ");', '        if (0)\n        {\n            sb_printf(&doc, ", \\"droppedPreload\\": ");',
     "a_preload_the_runner_had_is_dropped_for_the_measurement_and_recorded", "probe"),
    ("the interposer the child gets is called dropped", "src/probe.c",
     "    if (g_saved_preload[0] && strcmp(g_saved_preload, g_interposer))\n", "    if (g_saved_preload[0])\n",
     "a_preload_the_runner_had_is_dropped_for_the_measurement_and_recorded", "probe"),
    ("a bare child is not looked for on PATH", "src/probe.c", "            found = access(exe, X_OK) == 0;\n", "            found = 0;\n",
     "a_bare_clap_child_is_found_on_path_and_runs_under_the_interposer_beside_it", "probe"),
    ("a CLAP point drops the allocations the interposer counted", "src/probe.c",
     '                        if (jnum(rt, "allocationsInRun", &v))\n                            sb_printf(&doc, ", \\"allocations\\": %.0f", v);\n', "",
     "a_clap_child_runs_under_the_interposer_beside_it", "probe"),
    ("a note sweep the interposer did not count keeps the child's counts", "src/probe.c",
     '    if (jbool(ns, "interposer", 0))\n    {\n        put_count', "    if (1)\n    {\n        put_count",
     "a_clap_child_with_no_interposer_beside_it_is_unmeasured_and_says_why", "probe"),
    ("an unmeasured CLAP rt-safety does not say why", "src/probe.c", '                set_detail(x, "%s", with_dropped(no_interposer_reason()));\n',
     '                set_detail(x, "no interposer was loaded");\n', "a_clap_child_with_no_interposer_beside_it_is_unmeasured_and_says_why", "probe"),
    ("an interposer that did not load is named", "src/probe.c",
     '        if (g_interposer[0] && jbool(lv2_uri ? jget(measure_line, "rtSafety") : rt, "interposer", 0))', "        if (g_interposer[0])",
     "an_interposer_that_does_not_load_is_not_named_and_the_record_says_so", "probe"),
    ("the LV2 measurement runs without the noise stimulus", "src/probe.c",
     "    setenv(PROBE_LV2_STIMULUS_ENV, PROBE_LV2_STIMULUS, 1);\n", "",
     "an_lv2_plugin_is_pinned_then_measured_at_the_highest_rate", "probe"),
    ("--probe-notes does not reach the CLAP prober", "src/probe.c", "        if (o->probe_notes)\n        {", "        if (0)\n        {",
     "the_notes_an_instrument_holds_reach_the_clap_child", "probe"),
    ("--hold does not reach the CLAP prober", "src/probe.c", "        if (o->hold)\n        {", "        if (0)\n        {",
     "the_notes_an_instrument_holds_reach_the_clap_child", "probe"),
    ("a point carries no cost", "src/probe.c", "                put_cost(&doc, cost, latency->key[k]);\n", "",
     "every_point_carries_the_cost_timed_at_its_own_rate", "probe"),
    ("every point carries the first rate's cost", "src/probe.c", "                put_cost(&doc, cost, latency->key[k]);\n",
     "                put_cost(&doc, cost, latency->key[0]);\n", "every_point_carries_the_cost_timed_at_its_own_rate", "probe"),
    ("a rate the prober did not time borrows its neighbour's cost", "src/probe.c", "                put_cost(&doc, cost, latency->key[k]);\n",
     "                put_cost(&doc, cost, latency->key[k ? k - 1 : 0]);\n",
     "an_instrument_point_carries_the_notes_it_held_and_an_untimed_rate_has_no_cost", "probe"),
    ("a cost leaves out the notes held", "src/probe.c", '    if (jnum(voices, "held", &held) && jstr(voices, "basis"))', "    if (0)",
     "an_instrument_point_carries_the_notes_it_held_and_an_untimed_rate_has_no_cost", "probe"),
    ("an LV2 point leaves out its note sweep", "src/probe.c",
     '        if (jget(rt, "noteSweep"))\n            put_note_sweep(b, jget(rt, "noteSweep"));\n', "",
     "an_lv2_point_carries_the_note_sweep_and_what_run_did_while_the_notes_played", "probe"),
    ("a note sweep leaves out its allocations", "src/probe.c", '    put_count(b, ns, "allocationsInRun", "allocations");\n', "",
     "a_clap_point_carries_the_note_sweep_counts", "probe"),
    ("a latency from a note is called an impulse's", "src/probe.c", 'from_note ? OMX_MEASUREMENT_LATENCY_METHODS_NOTE_ONSET : OMX_MEASUREMENT_LATENCY_METHODS_IMPULSE_ONSET);',
     'OMX_MEASUREMENT_LATENCY_METHODS_IMPULSE_ONSET);',
     "a_latency_taken_from_a_note_says_so_and_whether_the_note_was_heard", "probe"),
    ("a note that did not sound is heard", "src/probe.c", 'jbool(latency->kid[k], "heard", 1) ? "true" : "false"', '"true"',
     "a_latency_taken_from_a_note_says_so_and_whether_the_note_was_heard", "probe"),
    ("the probe schema has no notes held in a cost", "protocol/probe-output.schema.json", '            "voices": {\n', '            "voices-": {\n',
     "instrument-notes validates", "probeschema"),
    ("the probe schema has no note-onset latency", "protocol/probe-output.schema.json", '"declared-port", "note-onset"]', '"declared-port", "note-guess"]',
     "instrument-notes validates", "probeschema"),
    ("the probe schema accepts a verdict", "protocol/probe-output.schema.json", '          "verdict"\n', '          "verdict-"\n',
     "success-msi validates", "probeschema"),
    ("the probe schema does not require binary.sha256", "protocol/probe-output.schema.json",
     '      "required": [\n        "path",\n        "sha256",\n        "files"\n      ],', '      "required": [\n        "path",\n        "files"\n      ],',
     "success-msi validates", "probeschema"),
    ("the probe schema takes any outcome", "protocol/probe-output.schema.json", '"enum": ["probe.ok", "probe.crashed"',
     '"enum": ["probe.exploded", "probe.ok", "probe.crashed"', "success-msi validates", "probeschema"),
    ("the probe schema takes another major", "protocol/probe-output.schema.json", '"pattern": "^1\\\\.[0-9]+$"', '"pattern": "^[0-9]+\\\\.[0-9]+$"',
     "success-msi validates", "probeschema"),
    ("the probe schema takes a percentile of 50", "protocol/probe-output.schema.json", '"exclusiveMinimum": 50', '"exclusiveMinimum": 0',
     "success-msi validates", "probeschema"),
    ("the generated schema lost a latency method the contract has", "protocol/probe-output.schema.json",
     '"declared-port", "note-onset"]', '"declared-port"]',
     "MEASUREMENT_LATENCY_METHODS at /$defs/point/properties/latency/properties/method is the contract's", "vocabulary"),
    ("the generated schema has the clock bands in an order of its own", "protocol/probe-output.schema.json",
     '"3.5-4.5GHz", "4.5GHz+"]', '"4.5GHz+", "3.5-4.5GHz"]',
     "MACHINE_CLOCK_BANDS at /properties/machine/properties/class/properties/clockBand is the contract's", "vocabulary"),
    ("the contract gives its hosts a scheduling class the schema does not have", "omx-vocabulary.schema.json",
     '        "none",\n        "fifo"\n', '        "none",\n        "fifo",\n        "rr"\n',
     "RESOURCE_THREAD_SCHEDULING at /properties/offer/properties/realtime is the contract's", "vocabulary"),
    ("the template types the latency methods by hand again", "protocol/probe-output.schema.in",
     '"enum": [@OMX_MEASUREMENT_LATENCY_METHODS@]', '"enum": ["impulse-onset", "declared-port", "note-onset"]',
     "the template types no list of the contract's by hand", "vocabulary"),
    ("the template takes the voice basis from nowhere", "protocol/probe-output.schema.in",
     '"enum": [@OMX_MEASUREMENT_VOICE_BASES@]', '"type": "string"',
     "the template takes MEASUREMENT_VOICE_BASES from the contract", "vocabulary"),
    ("a chain declared again is always formed again", "src/supervisor.c",
     "    if (chain_in_place(c))\n        chain_update(c);",
     "    if (0)\n        chain_update(c);",
     "a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor"),
    ("a joining member's state is not loaded", "src/supervisor.c",
     "join[k]->has_ckpt && ckpt_alone(join[k]->id, dir, sizeof(dir))",
     "0 && ckpt_alone(join[k]->id, dir, sizeof(dir))",
     "a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor"),
    ("a joining member's state is loaded with every survivor's", "src/supervisor.c",
     "            snprintf(msg, sizeof(msg), STATE_LOAD, dir);",
     "            snprintf(msg, sizeof(msg), STATE_LOAD, g_ckpt);",
     "a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor"),
    ("a joining member's connections are not replayed", "src/supervisor.c",
     "        if (replay_conns(w, join[k]) < 0)\n            goto out;",
     "        if (0)\n            goto out;",
     "a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor"),
    ("the running worker does not hold the new order", "src/supervisor.c",
     "            w->inst[n++] = g_inst[c->ids[k]];",
     "            n++;",
     "a_chain_declared_again_keeps_its_running_worker_and_restarts_no_survivor"),
    ("two rows of one program are refused together", "src/supervisor.c",
     "    return a == b || (format_at(a)->native_chain",
     "    return a == b || (0 && format_at(a)->native_chain",
     "a_clap_member_and_an_lv2_member_of_the_adapter_row_form_one_chain"),
    ("a chain's worker is of its first member's row", "src/supervisor.c",
     "        if (g_inst[ids[k]] && format_at(g_inst[ids[k]]->fmt)->narrow_world)\n            return g_inst[ids[k]]->fmt;",
     "        if (0)\n            return g_inst[ids[k]]->fmt;",
     "a_clap_member_and_an_lv2_member_of_the_adapter_row_form_one_chain"),
    ("a chain's world is built from every member's uri", "src/supervisor.c",
     "        if (w->inst[k]->fmt == w->fmt)\n            uris[(*n)++]",
     "        if (1)\n            uris[(*n)++]",
     "under_require_pins_a_chain_of_a_clap_and_an_lv2_member_sees_the_lv2_members_bundle_only"),
    ("a chain's world is checked against every member's uri", "src/supervisor.c",
     "        if (g_inst[ids[k]]->fmt == row)\n            uris[m++]",
     "        if (1)\n            uris[m++]",
     "under_require_pins_a_chain_of_a_clap_and_an_lv2_member_sees_the_lv2_members_bundle_only"),
    ("chain_get reads the running members from the declared order", "src/supervisor.c",
     '            put(&buf, &used, &cap, "%s%d", any++ ? "," : "", c->w->inst[k]->id);',
     '            put(&buf, &used, &cap, "%s%d", any++ ? "," : "", c->ids[k]);',
     "chain_get_reads_a_chain_back_as_declared_and_as_it_runs"),
    ('an unknown member of a chain is refused without its named code', "src/supervisor.c",
     '            return sup_resp(PHD_ERR_CHAIN_UNKNOWN_INSTANCE);\n        for (m = 0; m < k; m++)',
     '            return sup_resp(ERR_INSTANCE_NON_EXISTS);\n        for (m = 0; m < k; m++)',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('an instance named twice is a chain', "src/supervisor.c",
     '            if (ids[m] == ids[k])\n                return sup_resp(PHD_ERR_CHAIN_DUPLICATE);',
     '            if (0)\n                return sup_resp(PHD_ERR_CHAIN_DUPLICATE);',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('a member of another chain joins this one', "src/supervisor.c",
     '        if (i->chain && i->chain != c)\n',
     '        if (0)\n',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('members of two formats are one chain', "src/supervisor.c",
     '        if (!chain_rows_together(i->fmt, g_inst[ids[0]]->fmt))\n',
     '        if (0)\n',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ("a member's state is not saved before it leaves its worker", "src/supervisor.c",
     '    if (w->state == W_UP)\n        checkpoint(w);\n    w = i->w;',
     '    w = i->w;',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ("a chain's worker is not sent the order", "src/supervisor.c",
     '    if (w->chain && format_at(w->fmt)->native_chain && chain_line(w, msg, sizeof(msg))',
     '    if (0 && w->chain && format_at(w->fmt)->native_chain && chain_line(w, msg, sizeof(msg))',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('mod-host is sent the order of a chain', "src/supervisor.c",
     '    if (w->chain && format_at(w->fmt)->native_chain && chain_line(w, msg, sizeof(msg))',
     '    if (w->chain && chain_line(w, msg, sizeof(msg))',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('chain_formed is never written', "src/supervisor.c",
     '    if (w->chain)\n        chain_formed(w);\n}',
     '    if (0)\n        chain_formed(w);\n}',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('a removed member stays in the chain', "src/supervisor.c",
     '    chain_leave(i);\n',
     '',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ("the chain's worker is not told the order after a remove", "src/supervisor.c",
     '    else if (w->chain)\n        chain_tell(w);\n',
     '',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('a worker loses the order of its instances when one leaves', "src/supervisor.c",
     '            memmove(&w->inst[n], &w->inst[n + 1], (w->ninst - n - 1) * sizeof(instance_t *));\n            w->ninst--;',
     '            w->inst[n] = w->inst[--w->ninst];',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ("a member a new order leaves out stays in the chain's worker", "src/supervisor.c",
     '        i->chain = NULL;\n        if (c->w && i->w == c->w)\n            to_own(i);\n    }\n    free(c->ids);',
     '        i->chain = NULL;\n    }\n    free(c->ids);',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ("chain_clear leaves the members in the chain's worker", "src/supervisor.c",
     '        if (c->w && i->w == c->w)\n            to_own(i);\n    }\n    chain_free(c);',
     '    }\n    chain_free(c);',
     "a_chain_is_declared_over_existing_instances_and_each_refusal_is_named"),
    ('every member of a chain gets a worker of its own', "src/supervisor.c",
     '        if (!w)\n        {\n            w = worker_new(chain_row_of(c->ids, c->n), place);',
     '        if (1)\n        {\n            w = worker_new(chain_row_of(c->ids, c->n), place);',
     "a_chain_of_three_runs_in_one_worker_and_its_crashed_member_is_quarantined_while_the_others_go_on_in_order"),
    ("a chain's worker is not judged as a pool, so its culprit takes the others down", "src/supervisor.c",
     '            w->pool = 1;\n            w->chain = c;',
     '            w->chain = c;',
     "a_chain_of_three_runs_in_one_worker_and_its_crashed_member_is_quarantined_while_the_others_go_on_in_order"),
    ('a cleared member does not go back into its chain', "src/supervisor.c",
     '    if (g_inst[id] && g_inst[id]->chain)\n        g_inst[id]->chain->rejoin = 1;\n',
     '',
     "a_chain_of_three_runs_in_one_worker_and_its_crashed_member_is_quarantined_while_the_others_go_on_in_order"),
    ('a split chain never rejoins around its culprit', "src/supervisor.c",
     '    if (i->chain && !chain_whole(i->chain))\n        i->chain->rejoin = 1;\n',
     '',
     "a_chain_that_dies_naming_no_culprit_is_split_and_rejoins_without_the_one_that_dies_again"),
    ("a row of the host verb table is dropped", "include/plugin-hostd/protocol.h",
     '    X("cpu_load", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \\\n', "", "verb table", "verbtable"),
    ("a verb is added to the daemon with no row in the host verb table", "include/plugin-hostd/protocol.h",
     '    X(CHAIN_CLEAR, OMX_VERB_CHAIN_CLEAR, "<chain>", OMX_VERB_CHAIN_CLEAR_REPLY, \\\n',
     '    X(SABOTAGE, "verb_table_sabotage", "", "resp 0", "a verb with no row") \\\n'
     '    X(CHAIN_CLEAR, OMX_VERB_CHAIN_CLEAR, "<chain>", OMX_VERB_CHAIN_CLEAR_REPLY, \\\n', "verb table", "verbtable"),
    ("a verb the daemon answers itself is absent from a profile", "include/plugin-hostd/protocol.h",
     "    X(OMX_VERB_CHAIN, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \\\n",
     "    X(OMX_VERB_CHAIN, DAEMON, REQUIRED, REQUIRED, ABSENT, REQUIRED) \\\n", "verb table", "verbtable"),
    ("a verb mod-host never had is required of a profile", "include/plugin-hostd/protocol.h",
     '    X("set_midi_program_change_pedalboard_bank_channel", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \\\n',
     '    X("set_midi_program_change_pedalboard_bank_channel", MOD_UI, ABSENT, REQUIRED, ABSENT, ABSENT) \\\n',
     "verb table", "verbtable"),
    ("the declared floor of a chain is two again", "include/plugin-hostd/protocol.h",
     "#define PHD_CHAIN_MEMBERS_MIN    1\n", "#define PHD_CHAIN_MEMBERS_MIN    2\n",
     "a_chain_of_one_runs_in_a_worker_of_its_own_and_a_chain_of_none_is_refused"),
    ("the grammar of chain asks two members, not the declared floor", "src/verbs.c",
     "if (ntok < 2 + PHD_CHAIN_MEMBERS_MIN || !number(tok[1], &id))\n        return sup_resp(ERR_INVALID_OPERATION);\n    for (n = 2; n < ntok; n++)\n        if (!number(tok[n], &ids[n - 2]))\n            return sup_resp(ERR_INVALID_OPERATION);\n    return sup_chain(",
     "if (ntok < 4 || !number(tok[1], &id))\n        return sup_resp(ERR_INVALID_OPERATION);\n    for (n = 2; n < ntok; n++)\n        if (!number(tok[n], &ids[n - 2]))\n            return sup_resp(ERR_INVALID_OPERATION);\n    return sup_chain(",
     "a_chain_of_one_runs_in_a_worker_of_its_own_and_a_chain_of_none_is_refused"),
    ("the supervisor asks two members of a chain, not the declared floor", "src/supervisor.c",
     "|| n < PHD_CHAIN_MEMBERS_MIN)", "|| n < 2)",
     "a_chain_of_one_runs_in_a_worker_of_its_own_and_a_chain_of_none_is_refused"),
    ("midi_learn is broadcast to every worker, not relayed to the instance's", "src/verbs.c",
     "MONITOR_OUTPUT, MIDI_LEARN, MIDI_MAP,", "MONITOR_OUTPUT, MIDI_MAP,",
     "the_preset_bundle_and_learn_verbs_are_relayed_and_the_workers_answer_comes_back"),
    ("the daemon answers bundle_add itself and no worker hears of it", "src/verbs.c",
     "    reply_text = sup_broadcast(line);\n",
     "    reply_text = verb_is(verb, BUNDLE_ADD) ? sup_resp(SUCCESS) : sup_broadcast(line);\n",
     "the_preset_bundle_and_learn_verbs_are_relayed_and_the_workers_answer_comes_back"),
    ("the relay drops the parameter feedback a worker writes", "src/relay.c",
     "                send_line(start, nul - start + 1);\n                gesture_seen(s, start);",
     "                if (strncmp(start, PHD_EVENT_PARAM_SET \" \", 10))\n                    send_line(start, nul - start + 1);\n"
     "                gesture_seen(s, start);",
     "a_value_the_plugin_moved_by_itself_reaches_the_controller_and_a_controllers_value_writes_no_feedback"),
    ("the daemon echoes a controller's param_set as feedback", "src/supervisor.c",
     "        return sup_resp(ERR_INSTANCE_NON_EXISTS);\n    w = i->w;\n    if (w->state != W_UP)\n        return refuse_worker(w);\n    rc = proc_rpc",
     "        return sup_resp(ERR_INSTANCE_NON_EXISTS);\n    if (verb_is(line, EFFECT_PARAM_SET))\n        event(\"%s\", line);\n"
     "    w = i->w;\n    if (w->state != W_UP)\n        return refuse_worker(w);\n    rc = proc_rpc",
     "a_value_the_plugin_moved_by_itself_reaches_the_controller_and_a_controllers_value_writes_no_feedback"),
    ("a chain with a pinned LV2 member whose bundle is gone forms in a world without it", "src/supervisor.c",
     "    if (!chain_world_found(ids, n))\n", "    if (0)\n",
     "under_require_pins_a_chain_of_lv2_members_runs_in_a_world_of_the_union_of_their_bundles"),
    ("a chain's LV2 world is narrowed to its first member's bundle, not the union", "src/lv2.c",
     "    for (k = 0; k < n; k++)\n    {\n        char *bundle = proc_find_lv2_bundle(conf->lv2_path, uris[k]), *base;",
     "    for (k = 0; k < 1; k++)\n    {\n        char *bundle = proc_find_lv2_bundle(conf->lv2_path, uris[k]), *base;",
     "under_require_pins_a_chain_of_lv2_members_runs_in_a_world_of_the_union_of_their_bundles"),
    ("a chain's worker gets the whole lv2_path", "src/supervisor.c",
     "        world = f->narrow_world(&g_conf, dir, uris, n);\n        free(uris);\n        return world;",
     "        world = NULL;\n        free(uris);\n        return world;",
     "under_require_pins_a_chain_of_lv2_members_runs_in_a_world_of_the_union_of_their_bundles"),
    ("a worker's refusal of the order fails its replay", "src/supervisor.c",
     'w->chain && format_at(w->fmt)->native_chain && chain_line(w, msg, sizeof(msg)) && replay_line(w, msg) != RPC_OK)',
     'w->chain && format_at(w->fmt)->native_chain && chain_line(w, msg, sizeof(msg)) && (replay_line_code(w, msg, &n) != RPC_OK || n < 0))',
     "a_worker_that_runs_no_chain_refuses_the_line_and_the_members_still_share_it"),
    ("a descriptor_dir or qualification_dir that cannot be written is let through", "src/descriptors.c",
     "    if (make_dirs(dir) != 0 || writable(dir) != 0)\n", "    if (make_dirs(dir) != 0 && 0)\n",
     "a_read_only_directory_stops_the_daemon_with_its_code_and_names_the_key"),
    ("an empty descriptor_dir ignores $XDG_STATE_HOME", "src/descriptors.c",
     "    if (state && *state)\n        snprintf(dir, size, \"%s/%s\", state, subdir);",
     "    if (0)\n        snprintf(dir, size, \"%s/%s\", state, subdir);",
     "a_missing_key_falls_to_the_documented_default_and_the_key_holds_over_the_variable"),
    ("the binary of an LV2 plugin is looked for among its data files too", "src/lv2.c",
     "(!binary_only && !strcmp(t.text, RDFS_SEEALSO))", "!strcmp(t.text, RDFS_SEEALSO)",
     "an_add_writes_the_descriptor_by_id_version_and_hash_and_descriptor_get_answers_from_it"),
    ("an add scans a binary that already has a descriptor", "src/descriptors.c",
     "    if ((described = lookup(id, hash, path, sizeof(path)) == 0))\n",
     "    if ((described = lookup(id, hash, path, sizeof(path)) == 0 && 0))\n",
     "an_add_writes_the_descriptor_by_id_version_and_hash_and_descriptor_get_answers_from_it"),
    ("a scan that runs is answered absent", "src/descriptors.c",
     "    {\n        s = scan_of(format, id, hash);\n        return resp_missing(s, s ? s->code : SUCCESS);\n",
     "    {\n        s = scan_of(format, id, hash);\n        return resp_missing(s, SUCCESS);\n",
     "a_scan_that_runs_answers_pending_and_one_that_fails_answers_its_code_while_the_add_stands"),
    ("a directory that turns read-only is answered absent", "src/descriptors.c",
     "        scan_failed(s, PHD_ERR_DIR_NOT_WRITABLE, why);\n        return;\n    }\n    log =",
     "        scan_failed(s, PHD_ERR_DESCRIPTOR_ABSENT, why);\n        return;\n    }\n    log =",
     "a_directory_that_turns_read_only_makes_the_scan_answer_its_code"),
    ("the preset schema takes a format version it does not know", "protocol/preset.schema.json",
     '"enum": ["org.openmixer.preset/1", "org.openmixer.preset/2"]', '"type": "string"',
     "an unknown format version is refused", "presetschema"),
    ("the preset schema takes a fingerprint of any scheme", "protocol/preset.schema.json",
     '"pattern": "^omx-layout/1:[0-9a-f]{64}$"', '"pattern": "^[^:]+:[0-9a-f]{64}$"',
     "a fingerprint of an unknown scheme is refused", "presetschema"),
    ("the preset schema takes params+state with no state body", "protocol/preset.schema.json",
     '"then": {"required": ["params", "state"]}', '"then": {"required": ["params"]}',
     "params+state with the state body dropped is refused", "presetschema"),
    # the declared verbs (data/verbs.json) against the daemon on its socket, and the sources against the declaration
    ("a declared format is not the grammar the daemon answers", "data/verbs.json",
     '"format": "chain_get %i",', '"format": "chain_get %i %i",', "verbs_declared", "verbs"),
    ("a declared code is not the one the daemon answers", "data/verbs.json",
     '"resp": -522,', '"resp": -101,', "verbs_declared", "verbs"),
    ("a number omx-clap-core names is named again by plugin-hostd", "data/verbs.json",
     '    "codes": {\n      "placementInvalid": {',
     '    "codes": {\n      "invalidOperation": {\n        "code": "reply.plugin-hostd.invalid-operation",\n'
     '        "resp": -902,\n        "doc": "a second name for -902"\n      },\n      "placementInvalid": {',
     "verbs_declared", "verbs"),
    ("the handler of a declared verb is deleted", "src/verbs.c",
     "    if (!strcmp(verb, OMX_VERB_CHAIN_GET))\n    {\n        int id;\n\n"
     "        return ntok == 2 && number(tok[1], &id) ? sup_chain_get(id) : sup_resp(ERR_INVALID_OPERATION);\n    }\n",
     "", "verbs_declared", "verbs"),
    ("the daemon answers a verb no declaration holds", "src/verbs.c",
     "    if (!strcmp(verb, OMX_VERB_WORKER_LIST))\n",
     '    if (!strcmp(verb, "verb_sabotage"))\n        return sup_resp(SUCCESS);\n'
     "    if (!strcmp(verb, OMX_VERB_WORKER_LIST))\n", "verbs_declared", "verbs"),
    ("a declared verb is typed by hand in the daemon", "src/verbs.c",
     "if (!strcmp(verb, OMX_VERB_CHAIN_GET))", 'if (!strcmp(verb, "chain_get"))', "verbs_contract", "verbs"),
    ('the history file is left readable by others', 'src/history.c',
     '    ok = fflush(file) == 0 && !ferror(file) && fsync(fileno(file)) == 0;',
     '    fchmod(fileno(file), 0644);\n    ok = fflush(file) == 0 && !ferror(file) && fsync(fileno(file)) == 0;',
     'the_history_file_is_mode_0600_in_a_private_directory_with_no_temporary_beside_it', "history"),
    ("the history's directories are made world readable", 'src/fsutil.c',
     'mkdir(path, 0700)',
     'mkdir(path, 0755)',
     'the_history_file_is_mode_0600_in_a_private_directory_with_no_temporary_beside_it', "history"),
    ('a line this version cannot read is dropped by the next save', 'src/history.c',
     '            held_add(line, n);\n        }\n        else if (rec_at(',
     '        }\n        else if (rec_at(',
     'a_line_outside_the_grammar_is_kept_verbatim_and_not_read', "history"),
    ('a second line of one binary is dropped by the next save', 'src/history.c',
     '            rec_free(&rec);\n            held_add(line, n);',
     '            rec_free(&rec);',
     'a_second_line_of_one_binary_and_class_is_kept_and_not_read', "history"),
    ('a negative count is read', 'src/history.c',
     "if (!*text || *text == '-' || ",
     "if (!*text || ",
     'a_line_outside_the_grammar_is_kept_verbatim_and_not_read', "history"),
    ('a decimal that is not a number is read', 'src/history.c',
     'if (*end || errno || !isfinite(v))',
     'if (*end || errno)',
     'a_line_outside_the_grammar_is_kept_verbatim_and_not_read', "history"),
    ('a key twice in one line is read', 'src/history.c',
     '(seen & (1u << key)) || ',
     '(seen & 0) || ',
     'a_line_outside_the_grammar_is_kept_verbatim_and_not_read', "history"),
    ('a digest that is not a digest is read', 'src/history.c',
     '!phd_pin_hex_valid(tok[2]))',
     '0)',
     'a_line_outside_the_grammar_is_kept_verbatim_and_not_read', "history"),
    ('a file of another version is read', 'src/history.c',
     'if (n != strlen(PHD_HISTORY_HEADER) || strncmp(line, PHD_HISTORY_HEADER, n))',
     'if (0)',
     'a_file_with_an_unknown_version_or_that_cannot_be_read_blocks_the_history_and_is_never_touched', "history"),
    ('a blocked history is cleared', 'src/history.c',
     '    if (!g_started || g_blocked)\n        return -1;',
     '    if (!g_started)\n        return -1;',
     'a_file_with_an_unknown_version_or_that_cannot_be_read_blocks_the_history_and_is_never_touched', "history"),
    ("the file's header is not written", 'src/history.c',
     '    fprintf(file, "%s\\n", PHD_HISTORY_HEADER);\n',
     '',
     'a_record_round_trips_through_its_file_value_for_value', "history"),
    ('the pss is written to two decimals', 'src/history.c',
     '"%c%s=%.1f"',
     '"%c%s=%.2f"',
     'a_record_round_trips_through_its_file_value_for_value', "history"),
    ('a restart of a plugin alone is counted', 'src/history.c',
     'history_rec_t *r = grouped ? rec_get(uri, digest) : NULL;',
     'history_rec_t *r = ((void)grouped, rec_get(uri, digest));',
     'a_record_round_trips_through_its_file_value_for_value', "history"),
    ('the cpu estimate moves up and down by one half', 'src/history.c',
     '0.95 * step : -0.05 * step',
     '0.5 * step : -0.5 * step',
     'windows_fold_alone_and_in_a_group_into_their_own_fields', "history"),
    ("a group's window is folded into the plugin's own cpu", 'src/history.c',
     '    if (grouped)\n    {\n        r->windows_grouped++;',
     '    if (!grouped)\n    {\n        r->windows_grouped++;',
     'windows_fold_alone_and_in_a_group_into_their_own_fields', "history"),
    ('a space in a uri makes a record', 'src/history.c',
     ' || strpbrk(uri, " \\t\\r\\n")',
     '',
     'a_key_that_is_not_a_plugin_binary_makes_no_record', "history"),
    ('a digest that is not one makes a record', 'src/history.c',
     '|| !phd_pin_hex_valid(digest) ',
     '',
     'a_key_that_is_not_a_plugin_binary_makes_no_record', "history"),
    ('a crash 30 days old no longer counts', 'src/history.c',
     'now - last <= (long long)PHD_HISTORY_KEEP_DAYS',
     'now - last < (long long)PHD_HISTORY_KEEP_DAYS',
     'the_summary_marks_crashes_and_raised_xruns_at_the_declared_margins', "history"),
    ('the xrun margin is not strict', 'src/history.c',
     'return 100 * xg * ws > 100 * xs * wg',
     'return 100 * xg * ws >= 100 * xs * wg',
     'the_summary_marks_crashes_and_raised_xruns_at_the_declared_margins', "history"),
    ('thirty windows are too few', 'src/history.c',
     'if (wg < PHD_HISTORY_MIN_WINDOWS)',
     'if (wg <= PHD_HISTORY_MIN_WINDOWS)',
     'the_summary_marks_crashes_and_raised_xruns_at_the_declared_margins', "history"),
    ('the xrun floor of a plugin that never ran alone is not strict', 'src/history.c',
     'return 100 * xg > (long long)PHD_HISTORY_XRUN_MARGIN_PCT * wg;',
     'return 100 * xg >= (long long)PHD_HISTORY_XRUN_MARGIN_PCT * wg;',
     'the_summary_marks_crashes_and_raised_xruns_at_the_declared_margins', "history"),
    ("another host class's record is read as this one's", 'src/history.c',
     '            !strcmp(g_entry[n].rec.klass, klass))',
     '            klass != NULL)',
     'a_record_of_another_host_class_is_kept_and_never_read_as_this_ones', "history"),
    ('a clear leaves the lines it could not read', 'src/history.c',
     'g_entry[n].raw ? raw_names(g_entry[n].raw, uri) :',
     'g_entry[n].raw ? raw_names(g_entry[n].raw, "") :',
     'clear_removes_a_plugins_lines_of_every_binary_and_class_or_all_of_them_at_once', "history"),
    ('the history is saved at every tick', 'src/history.c',
     'if (g_dirty && now - g_saved_at >= g_save_s)',
     'if (g_dirty)',
     'the_history_is_saved_at_most_once_per_interval_and_at_quit', "history"),
    ('a failed save forgets the change', 'src/history.c',
     '    g_saved_at = now;\n    if (file_write() == 0)\n        g_dirty = 0;',
     '    g_saved_at = now;\n    file_write();\n    g_dirty = 0;',
     'a_save_that_fails_leaves_the_old_file_whole_and_is_tried_again', "history"),
    ('the state home is not looked at', 'src/history.c',
     '    else if (state && *state)',
     '    else if (0 && state && *state)',
     'the_default_path_is_the_xdg_state_home_then_home_and_history_file_overrides_both', "history"),
    ('history_file does not override', 'src/history.c',
     '    if (*configured)\n        snprintf(g_path, sizeof(g_path), "%s", configured);\n    else if',
     '    if (0)\n        snprintf(g_path, sizeof(g_path), "%s", configured);\n    else if',
     'the_default_path_is_the_xdg_state_home_then_home_and_history_file_overrides_both', "history"),
    ("the stat line's fields are counted from the first parenthesis", 'src/proc.c',
     "const char *p = strrchr(text, ')');",
     "const char *p = strchr(text, ')');",
     "proc_test", "proc"),
    ('utime is read from the field before it', 'src/proc.c',
     'if (field != 14 && field != 15)',
     'if (field != 13 && field != 14)',
     "proc_test", "proc"),
    ('Pss_Anon is taken for Pss', 'src/proc.c',
     'if (!strncmp(p, "Pss:", 4))',
     'if (!strncmp(p, "Pss", 3))',
     "proc_test", "proc"),
    ('a Pss that is not a number is taken for 0', 'src/proc.c',
     'if (end == p + 4 || v < 0 || strncmp(end, " kB", 3))',
     'if (v < 0 || strncmp(end, " kB", 3))',
     "proc_test", "proc"),
    ('CPU time is counted in ticks, not seconds', 'src/proc.c',
     '*seconds = (double)(u + s) / (double)hz;',
     '*seconds = (double)(u + s);',
     "proc_test", "proc"),
    ('a machine of 8 cores is in the band of 9 to 16', 'src/machine.c',
     'ncpu <= 8 ?',
     'ncpu < 8 ?',
     "the_host_class_is_arch_cores_clock_with_the_contracts_bands_cut_where_the_contract_cuts_them", "history"),
    ('a clock of 2.5 GHz is in the band under it', 'src/machine.c',
     'khz < 2500000 ?',
     'khz <= 2500000 ?',
     "the_host_class_is_arch_cores_clock_with_the_contracts_bands_cut_where_the_contract_cuts_them", "history"),
    ('the class is cores/arch/clock', 'src/machine.c',
     'n = snprintf(out, size, "%s/%s/%s", u.machine, core, clock);',
     'n = snprintf(out, size, "%s/%s/%s", core, u.machine, clock);',
     "the_host_class_is_arch_cores_clock_with_the_contracts_bands_cut_where_the_contract_cuts_them", "history"),
    ('a class that does not fit is cut', 'src/machine.c',
     'return n > 0 && (size_t)n < size ? 0 : -1;',
     'return n > 0 ? 0 : -1;',
     "the_host_class_is_arch_cores_clock_with_the_contracts_bands_cut_where_the_contract_cuts_them", "history"),
    ('the first interval is over before it began', 'src/history.c',
     'if (g_saved_at < 0)\n        g_saved_at = now;',
     'if (g_saved_at < 0)\n        g_saved_at = now - g_save_s;',
     'the_history_is_saved_at_most_once_per_interval_and_at_quit', "history"),
    ('a plugin alone in a worker is counted as a group', 'src/supervisor.c',
     'int n, grouped = w->ninst >= 2;',
     'int n, grouped = w->ninst >= 1;',
     'a_pinned_plugin_leaves_a_record_of_its_windows_alone_and_in_a_group'),
    ('a window never closes', 'src/supervisor.c',
     '    if (now - w->hist_start_ms < window_ms)\n        return;',
     '    if (1)\n        return;',
     'a_pinned_plugin_leaves_a_record_of_its_windows_alone_and_in_a_group'),
    ('the Pss is taken for MiB when it is kB', 'src/supervisor.c',
     '(double)pss_kb / 1024.0',
     '(double)pss_kb',
     'a_pinned_plugin_leaves_a_record_of_its_windows_alone_and_in_a_group'),
    ('a file is written at no save', 'src/supervisor.c',
     '    history_tick(now / 1000);\n',
     '',
     'a_pinned_plugin_leaves_a_record_of_its_windows_alone_and_in_a_group'),
    ('the history is not written at quit', 'src/main.c',
     '    sup_finish();\n    history_finish();',
     '    sup_finish();',
     'the_history_is_written_when_the_daemon_quits_and_found_again_by_the_next_one'),
    ('a crash of a worker of its own is counted as a crash of a group', 'src/supervisor.c',
     'hist_crash(w->inst[0]->uri, 0);',
     'hist_crash(w->inst[0]->uri, 1);',
     'crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them'),
    ('the culprit of a pool is counted as a crash alone', 'src/supervisor.c',
     'hist_crash(culprit->uri, w->ninst >= 2);',
     'hist_crash(culprit->uri, 0);',
     'crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them'),
    ('the culprit is also counted as a restart', 'src/supervisor.c',
     '        if (members[n] != blamed)',
     '        if (1)',
     'crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them'),
    ('the members of a group that went down are not counted', 'src/supervisor.c',
     '            hist_restart(members[n]->uri, 1);',
     '            ;',
     'crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them'),
    ('a quarantine is not counted', 'src/supervisor.c',
     '        hist_quarantine(i->uri);\n    }\n    /* the culprit of a chain',
     '    }\n    /* the culprit of a chain',
     'crashes_restarts_and_quarantines_are_counted_for_the_plugin_that_earned_them'),
    ('a window of less than half counts at a death', 'src/supervisor.c',
     'if (now - w->hist_start_ms >= window_ms / 2 && proc_cpu_seconds(w->pid, &cpu) == 0)',
     'if (proc_cpu_seconds(w->pid, &cpu) == 0)',
     'a_worker_that_dies_after_half_a_window_still_counts_it_and_before_half_does_not'),
    ('a death does not close the window it ended', 'src/supervisor.c',
     '    hist_death(w, now);\n    if (grouped &&',
     '    if (grouped &&',
     'a_worker_that_dies_after_half_a_window_still_counts_it_and_before_half_does_not'),
    ('a window in which the members changed is counted', 'src/supervisor.c',
     'if (w->hist_pid != w->pid || w->hist_ninst != w->ninst)',
     'if (w->hist_pid != w->pid)',
     'a_window_in_which_the_members_of_a_worker_changed_is_not_counted'),
    ('history_window_s 0 keeps a history', 'src/main.c',
     '    if (conf->history_window_s <= 0)\n        return;\n    if (*conf->host_class)',
     '    if (*conf->host_class)',
     'with_history_window_s_zero_nothing_is_kept_and_a_plugin_runs_as_before'),
    ('a blocked history answers history_clear', 'src/supervisor.c',
     'history_clear(bare_uri) == 0 ? SUCCESS : ERR_INVALID_OPERATION',
     'SUCCESS',
     'a_history_file_of_another_version_is_neither_read_nor_overwritten_and_the_daemon_runs_on'),
    ('a blocked history does not say so', 'src/supervisor.c',
     '    if (!history_available())\n        return strdup("resp 0 " PHD_WORD_UNAVAILABLE);\n',
     '',
     'a_history_file_of_another_version_is_neither_read_nor_overwritten_and_the_daemon_runs_on'),
    ('the history is kept under the last file of the pin', 'src/pins.c',
     'memcpy(hex, p->digest[0], PHD_SHA256_HEX_LEN + 1);',
     'memcpy(hex, p->digest[p->nfiles - 1], PHD_SHA256_HEX_LEN + 1);',
     'an_lv2_plugins_record_is_under_the_first_file_its_pin_holds'),
    ('the lv2 prefix is part of the uri history_get is asked for', 'src/supervisor.c',
     '    format_of_uri(uri, &bare_uri);\n    if (!history_available())',
     '    bare_uri = uri;\n    if (!history_available())',
     'an_lv2_plugins_record_is_under_the_first_file_its_pin_holds'),
    ('a host class with white space is taken', 'src/conf.c',
     'if (strpbrk(conf->host_class, " \\t"))',
     'if (0)',
     'the_history_goes_to_the_xdg_state_home_by_default_and_to_the_machines_class_unless_host_class_says_otherwise'),
    ('history_clear of a uri does not strip the lv2 prefix', 'src/supervisor.c',
     '    if (strcmp(uri, PHD_WORD_ALL))\n        format_of_uri(uri, &bare_uri);\n',
     '',
     'an_lv2_plugins_record_is_under_the_first_file_its_pin_holds'),
    ('a refused pin is no reason to stay alone', 'src/planner.c',
     'if (m->pin == PLANNER_PIN_REFUSED)',
     'if (0 && m->pin == PLANNER_PIN_REFUSED)',
     'refused_leaves_the_member_alone', "planner"),
    ('no pin under strict shares', 'src/planner.c',
     'if (m->pin == PLANNER_PIN_NONE && !s->pins_first_use)',
     'if (0 && m->pin == PLANNER_PIN_NONE && !s->pins_first_use)',
     'no_pin_under_strict_leaves_the_member_alone', "planner"),
    ('a pin without a verdict shares under first-use', 'src/planner.c',
     'if ((m->pin == PLANNER_PIN_NONE || m->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)',
     'if (0 && (m->pin == PLANNER_PIN_NONE || m->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)',
     'no_verdict_leaves_the_member_alone', "planner"),
    ('a pin that is gone under first-use shares', 'src/planner.c',
     '(m->pin == PLANNER_PIN_NONE || m->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)',
     '(m->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)',
     'a_pin_that_is_gone_under_first_use_has_no_verdict', "planner"),
    ('a pin without a verdict is alone under strict as well', 'src/planner.c',
     'm->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)',
     'm->pin == PLANNER_PIN_NO_VERDICT))',
     'under_strict_a_pin_without_a_verdict_shares', "planner"),
    ('verdict isolated shares', 'src/planner.c',
     'if (m->pin == PLANNER_PIN_ISOLATED)',
     'if (0 && m->pin == PLANNER_PIN_ISOLATED)',
     'verdict_isolated_leaves_the_member_alone', "planner"),
    ('a format with no world shares', 'src/planner.c',
     'if (!m->world_ok)',
     'if (0)',
     'format_world_leaves_the_member_alone', "planner"),
    ('the world is judged before the verdict', 'src/planner.c',
     '        if (m->pin == PLANNER_PIN_ISOLATED)\n            return PLANNER_REASON_VERDICT_ISOLATED;\n        if (!m->world_ok)\n            return PLANNER_REASON_FORMAT_WORLD;',
     '        if (!m->world_ok)\n            return PLANNER_REASON_FORMAT_WORLD;\n        if (m->pin == PLANNER_PIN_ISOLATED)\n            return PLANNER_REASON_VERDICT_ISOLATED;',
     'the_first_rule_that_matches_decides', "planner"),
    ('the pins are read without require_pins', 'src/planner.c',
     '    if (s->require_pins)\n    {',
     '    if (1)\n    {',
     'without_require_pins_no_pin_is_read', "planner"),
    ('a member over the cost limit shares', 'src/planner.c',
     '        return PLANNER_REASON_COST_OVER;',
     '        return PLANNER_REASON_NONE;',
     'cost_over_leaves_the_member_alone', "planner"),
    ('a cost at the limit is over it', 'src/planner.c',
     'member_cost(m) > s->group_cost_max',
     'member_cost(m) >= s->group_cost_max',
     'a_cost_at_the_limit_is_not_over', "planner"),
    ("a program that runs no chain of the others' joins the segment", 'src/planner.c',
     'if (strcmp(m[first].klass, m[k].klass))',
     'if (0)',
     'format_mixed_starts_a_new_segment', "planner"),
    ('a full segment takes another member', 'src/planner.c',
     'else if (s->group_max > 0 && open >= s->group_max)',
     'else if (0)',
     'group_full_starts_a_new_segment', "planner"),
    ('group_max 0 is a limit of 0', 'src/planner.c',
     'else if (s->group_max > 0 && open >= s->group_max)',
     'else if (open >= s->group_max)',
     'group_max_zero_is_no_limit', "planner"),
    ('a segment over its cost takes another member', 'src/planner.c',
     'else if (s->group_cost_max > 0 && sum + own > s->group_cost_max)',
     'else if (s->group_cost_max > 0 && sum + own > s->group_cost_max * 1e9)',
     'group_cost_starts_a_new_segment', "planner"),
    ('a segment exactly at its cost limit is full', 'src/planner.c',
     'sum + own > s->group_cost_max',
     'sum + own >= s->group_cost_max',
     'the_costs_of_a_segment_add_up', "planner"),
    ('the costs of a segment do not add', 'src/planner.c',
     '                open++;\n                sum += own;',
     '                open++;\n                sum += 0 * own;',
     'the_costs_of_a_segment_add_up', "planner"),
    ('a member of unknown cost counts for nothing', 'src/planner.c',
     'double own = cost == PLANNER_COST_UNKNOWN ? assumed_cost(m, first, open) : cost;',
     'double own = cost == PLANNER_COST_UNKNOWN ? 0 * assumed_cost(m, first, open) : cost;',
     'a_member_of_unknown_cost_counts_as_the_median_of_its_segment', "planner"),
    ('the median of an odd number is the first', 'src/planner.c',
     'return n % 2 ? known[n / 2] :',
     'return n % 2 ? known[0] :',
     'a_member_of_unknown_cost_counts_as_the_median_of_its_segment', "planner"),
    ('the median of an even number is the upper middle', 'src/planner.c',
     '(known[n / 2 - 1] + known[n / 2]) / 2',
     'known[n / 2]',
     'the_median_of_an_even_number_is_the_mean_of_the_middle_two', "planner"),
    ('cost-assumed is never said', 'src/planner.c',
     'out->reason[j] = PLANNER_REASON_COST_ASSUMED;',
     'out->reason[j] = PLANNER_REASON_NONE;',
     'cost_assumed_is_said_of_a_member_that_joined_on_an_assumption', "planner"),
    ('no-neighbour is never said', 'src/planner.c',
     'out->reason[j] = PLANNER_REASON_NO_NEIGHBOUR;',
     'out->reason[j] = PLANNER_REASON_NONE;',
     'no_neighbour_is_said_of_a_member_alone_for_the_members_around_it', "planner"),
    ('grouping-off is never said', 'src/planner.c',
     'else if (!s->grouping_on)',
     'else if (0)',
     'grouping_off_says_what_would_have_shared', "planner"),
    ('group-full is judged before format-mixed', 'src/planner.c',
     'if (strcmp(m[first].klass, m[k].klass))\n                r = PLANNER_REASON_FORMAT_MIXED;\n            else if (s->group_max > 0 && open >= s->group_max)\n                r = PLANNER_REASON_GROUP_FULL;',
     'if (s->group_max > 0 && open >= s->group_max)\n                r = PLANNER_REASON_GROUP_FULL;\n            else if (strcmp(m[first].klass, m[k].klass))\n                r = PLANNER_REASON_FORMAT_MIXED;',
     'format_mixed_comes_before_group_full_and_group_cost', "planner"),
    ('a plan of too many members is planned', 'src/planner.c',
     'if (n < 1 || n > PLANNER_MEMBERS_MAX)',
     'if (n < 1)',
     'a_plan_of_no_member_or_too_many_is_refused', "planner"),
    ('the planner remembers what it planned before', 'src/planner.c',
     'sum + own > s->group_cost_max',
     'sum + own > s->group_cost_max - ({ static double drift; drift += 0.02; drift; })',
     'the_same_members_give_the_same_bytes', "planner"),
    ('the segments are joined by commas', 'src/planner.c',
     '            put(buf, size, &used, ";");',
     '            put(buf, size, &used, ",");',
     'the_text_of_a_plan_is_the_one_the_bench_parses', "planner"),
    ('no reason is the empty text', 'src/planner.c',
     '        put(buf, size, &used, PHD_WORD_NONE);',
     '        put(buf, size, &used, "");',
     'no_reason_is_a_dash', "planner"),
    ('a refused plan is told another way', 'src/planner.c',
     '"%s%d:%s:%d"',
     '"%s%d:%s=%d"',
     'a_refused_plan_gives_every_member_the_refusal', "planner"),
    ('the reasons are not the declared words', 'src/planner.c',
     'const char *planner_reason_word(int reason)\n{',
     'const char *planner_reason_word(int reason)\n{\n    if (reason == PLANNER_REASON_NO_PIN)\n        return "no_pin";',
     'the_reasons_are_the_words_of_the_declaration', "planner"),
    ('the rate is not read', 'src/qualcost.c',
     'r != rate ||',
     '0 ||',
     'a_rate_or_quantum_the_record_lacks_is_unknown', "qualcost"),
    ('the quantum is not read', 'src/qualcost.c',
     'q != quantum)',
     '(q != quantum && 0))',
     'a_rate_or_quantum_the_record_lacks_is_unknown', "qualcost"),
    ('the first record of a plugin stands', 'src/qualcost.c',
     'if (v > best)',
     'if (best < 0)',
     'the_larger_record_stands_whichever_the_directory_lists_first', "qualcost"),
    ('the id inside the record is not read', 'src/qualcost.c',
     'if (!got || strcmp(got, id) || !grid',
     'if (!got || (strcmp(got, id) && 0) || !grid',
     'a_record_of_another_plugin_is_not_this_ones', "qualcost"),
    ('the fraction is nanoseconds over a second', 'src/qualcost.c',
     'return ns * rate / 1e9;',
     'return ns / 1e9;',
     'the_figure_is_the_p95_at_the_rate_and_quantum_as_a_fraction_of_a_core', "qualcost"),
    ('a plan again forms every segment again', 'src/supervisor.c',
     'if (!kept[j] && was[j]->n == pp->seg_len[k]',
     'if (0 && !kept[j] && was[j]->n == pp->seg_len[k]',
     'a_plan_again_keeps_the_worker_of_a_segment_that_did_not_change_and_forms_the_ones_that_did'),
    ('a kept segment keeps the name of its old place', 'src/supervisor.c',
     '                    snprintf(at[k]->w->place, sizeof(at[k]->w->place), PHD_PLACE_CHAIN_PREFIX "%s", word);\n',
     '',
     'a_plan_that_keeps_a_segment_in_another_place_renames_its_worker_and_restarts_nothing'),
    ('a member the new plan leaves out stays in the worker of its old segment', 'src/supervisor.c',
     '                    if (c->w && i->w == c->w)\n                        to_own(i);\n                }\n            }\n            chain_free(c);',
     '                }\n            }\n            chain_free(c);',
     'a_plan_again_keeps_the_worker_of_a_segment_that_did_not_change_and_forms_the_ones_that_did'),
    ('a plan under grouping off is applied', 'src/supervisor.c',
     'if (s.grouping_on && !refused)\n        plan_apply',
     'if (!refused)\n        plan_apply',
     'while_grouping_is_off_a_plan_is_answered_and_kept_and_nothing_moves'),
    ("a member of another chain's plan is the plan's to place", 'src/supervisor.c',
     'if (i->chain && !(i->chain->planned && i->chain->id == id))',
     'if (0)',
     'a_plan_is_refused_for_what_chain_refuses_and_moves_nothing'),
    ("plan_clear leaves the members in the segment's worker", 'src/supervisor.c',
     '            if (c->w && i->w == c->w)\n                to_own(i);\n        }\n        chain_free(c);\n    }\n    /* the members that share',
     '        }\n        chain_free(c);\n    }\n    /* the members that share',
     'plan_clear_gives_every_member_a_worker_of_its_own_and_forgets_the_plan'),
    ('a changed plan is not announced', 'src/supervisor.c',
     '        event(PHD_EVENT_PLAN_REASON_FMT, id, p->reasons);',
     '        ;',
     'a_plan_forms_the_runs_that_may_share_and_leaves_the_member_that_may_not_in_a_worker_of_its_own'),
    ("a segment's worker is named for the plan alone", 'src/supervisor.c',
     '    snprintf(place, sizeof(place), PHD_PLACE_CHAIN_PREFIX "%s", word);',
     '    snprintf(place, sizeof(place), PHD_PLACE_CHAIN_PREFIX "%d", c->id);',
     'a_plan_forms_the_runs_that_may_share_and_leaves_the_member_that_may_not_in_a_worker_of_its_own'),
    ('a cost is never read from a record', 'src/supervisor.c',
     '? qualcost_read(g_conf.qualification_dir, record_id(i->uri), g_conf.group_rate, g_conf.group_quantum)',
     '? PLANNER_COST_UNKNOWN',
     'the_cost_a_qualification_record_holds_decides_the_segments_and_a_missing_one_is_assumed'),
    ('group_cost_max is read as a fraction already', 'src/supervisor.c',
     's.group_cost_max = g_conf.group_cost_max / 100.0;',
     's.group_cost_max = g_conf.group_cost_max / 10.0;',
     'the_cost_a_qualification_record_holds_decides_the_segments_and_a_missing_one_is_assumed'),
    ('a CLAP plugin is found by its path in the records', 'src/supervisor.c',
     'return hash ? hash + 1 : uri;',
     'return uri;',
     'the_cost_a_qualification_record_holds_decides_the_segments_and_a_missing_one_is_assumed'),
    ('a verdict of isolated is read as none', 'src/supervisor.c',
     '    else if (!strcmp(verdict, PHD_PIN_VERDICT_ISOLATED))\n        m->pin = PLANNER_PIN_ISOLATED;\n',
     '',
     'a_plan_forms_the_runs_that_may_share_and_leaves_the_member_that_may_not_in_a_worker_of_its_own'),
    ("any word is a grouping mode", "src/conf.c", "ok |= !strcmp(conf->grouping, name);", "ok |= 1;",
     "a_setting_that_is_none_of_the_grouping_modes_stops_the_daemon_and_names_the_modes"),
    ("the handler of a declared verb is deleted: plan", "src/verbs.c",
     "    if (!strcmp(verb, OMX_VERB_PLAN))\n        return plan_words(tok, ntok);\n", "", "verbs_declared", "verbs"),
]


def build(tree):
    subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "plugin-hostd"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)


def build_probe(tree):
    # the probe has its own rule in the Makefile (its sources, -Isrc, the contract's flags and defines): build it there
    subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "plugin-hostd-probe"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)


def run_pin_test(tree):
    exe = os.path.join(tree, "pin-test")
    subprocess.run(["cc", "-I" + os.path.join(tree, "include"), "-std=gnu99", "-o", exe,
                    os.path.join(ROOT, "tests", "pin_test.c")], check=True)
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout


def run_format_test(tree):
    """tests/format_test.c against the tree's sources; it prints "ok   format_test" when no check failed"""
    os.makedirs(os.path.join(tree, "tests"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "format_test.c"), os.path.join(tree, "tests"))
    for f in os.listdir(os.path.join(tree, "src")):
        if f.endswith(".o"):
            os.unlink(os.path.join(tree, "src", f))
    subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "tests/format-test"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    env = dict(os.environ, PLUGIN_HOSTD_FORMAT_TEST_DIR=tree)
    p = subprocess.run([os.path.join(tree, "tests", "format-test"), FAKE], env=env, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + ("ok   format_test\n" if p.returncode == 0 else "")


def run_relay_test(tree):
    """tests/relay_test.c against the tree's src/relay.c; it prints "ok   relay_test" when no check failed"""
    os.makedirs(os.path.join(tree, "tests"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "relay_test.c"), os.path.join(tree, "tests"))
    subprocess.run(["make", "-s", "-B", "MOD_HOST_DIR=" + MOD_HOST_DIR, "tests/relay-test"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(tree, "tests", "relay-test")], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + ("ok   relay_test\n" if p.returncode == 0 else "")
def run_contract_test(tree):
    """tests/contract_derived.py against the tree's probe runner and generator; "ok   contract" when it passes"""
    subprocess.run(["make", "-s", "-B", "MOD_HOST_DIR=" + MOD_HOST_DIR, "plugin-hostd-probe"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    p = subprocess.run([sys.executable, os.path.join(tree, "tests", "contract_derived.py")], cwd=tree, capture_output=True,
                       text=True, timeout=300, env=dict(os.environ, PROBE=os.path.join(tree, "plugin-hostd-probe")))
    return p.returncode, p.stdout + ("ok   contract\n" if p.returncode == 0 else "")
def run_consumer_test(tree):
    """tests/consumer.c against the tree's header, as a consumer compiles it; "ok   consumer" when it passes"""
    exe = os.path.join(tree, "consumer")
    subprocess.run(["cc", "-I" + os.path.join(tree, "include"), "-std=c99", "-Wall", "-Wextra", "-o", exe,
                    os.path.join(ROOT, "tests", "consumer.c")], check=True)
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + ("ok   consumer\n" if p.returncode == 0 else "")

def run_history_test(tree):
    """tests/history_test.c against the tree's src/history.c; it prints "ok   <group>" for each group that passed"""
    os.makedirs(os.path.join(tree, "tests"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "history_test.c"), os.path.join(tree, "tests"))
    subprocess.run(["make", "-s", "-B", "MOD_HOST_DIR=" + MOD_HOST_DIR, "tests/history-test"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(tree, "tests", "history-test")], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout


def run_proc_test(tree):
    """tests/proc_test.c against the tree's src/proc.c; it prints "ok   proc_test" when no check failed"""
    os.makedirs(os.path.join(tree, "tests"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", "proc_test.c"), os.path.join(tree, "tests"))
    subprocess.run(["make", "-s", "-B", "MOD_HOST_DIR=" + MOD_HOST_DIR, "tests/proc-test"], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(tree, "tests", "proc-test")], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout


def run_alloc_test(tree):
    """make test-alloc: the tables of src/relay.c and src/lv2.c when realloc fails; prints "ok   alloc_test" when no check failed"""
    for f in ("tests/gesture-alloc-test", "tests/lv2-alloc-test", "tests/lv2-alloc-lv2.o"):
        if os.path.exists(os.path.join(tree, f)):
            os.unlink(os.path.join(tree, f))
    p = subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "test-alloc"], cwd=tree, capture_output=True, text=True,
                       timeout=120)
    return p.returncode, p.stdout + p.stderr + ("ok   alloc_test\n" if p.returncode == 0 else "")


def run_verbs_test(tree, name):
    """tests/verbs_declared.py against the tree's daemon and declaration ("ok   verbs_declared"), or the tree's
    tests/verbs_contract.py over its sources ("ok   verbs_contract")"""
    if name == "verbs_contract":
        p = subprocess.run([sys.executable, os.path.join(tree, "tests", "verbs_contract.py")], capture_output=True,
                           text=True, timeout=60, env=dict(os.environ, MOD_HOST_DIR=MOD_HOST_DIR))
    else:
        env = dict(os.environ, PLUGIN_HOSTD=os.path.join(tree, "plugin-hostd"), FAKE_HOST=FAKE,
                   PROBE=os.path.join(tree, "plugin-hostd-probe"), PLUGIN_HOSTD_VERBS=os.path.join(tree, "data", "verbs.json"))
        p = subprocess.run([sys.executable, os.path.join(tree, "tests", "verbs_declared.py")], env=env, capture_output=True,
                           text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr + ("ok   %s\n" % name if p.returncode == 0 else "")


def run_unit_test(tree, target, source, name):
    """a C unit test of the tree's sources, built by the Makefile's rule for `target`; it runs the one test and prints
    "ok   <name>" when it passes"""
    os.makedirs(os.path.join(tree, "tests"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "tests", source), os.path.join(tree, "tests"))
    subprocess.run(["make", "-s", "-B", "MOD_HOST_DIR=" + MOD_HOST_DIR, target], cwd=tree, check=True,
                   stdout=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(tree, target), name], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def run_test(tree, name, jack=False):
    if jack == "planner":
        return run_unit_test(tree, "tests/planner-test", "planner_test.c", name)
    if jack == "qualcost":
        return run_unit_test(tree, "tests/qualcost-test", "qualcost_test.c", name)
    if jack == "verbs":
        return run_verbs_test(tree, name)
    if jack == "consumer":
        return run_consumer_test(tree)
    if jack == "alloc":
        return run_alloc_test(tree)
    if jack == "format":
        return run_format_test(tree)
    if jack == "relay":
        return run_relay_test(tree)
    if jack == "history":
        return run_history_test(tree)
    if jack == "proc":
        return run_proc_test(tree)
    if jack == "contract":
        return run_contract_test(tree)
    if jack == "pin":
        return run_pin_test(tree)
    if jack == "readme":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "readme_build.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    if jack == "probe":
        env = dict(os.environ, ONLY=name, PROBE=os.path.join(tree, "plugin-hostd-probe"))
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "probe_test.py")], env=env, capture_output=True, text=True,
                           timeout=300)
        return p.returncode, p.stdout
    if jack == "probeschema":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "probe_schema.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    if jack == "vocabulary":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "vocabulary_derived.py"), tree], capture_output=True,
                           text=True, timeout=60, env=dict(os.environ, OMX_VOCABULARY=os.path.join(tree, "omx-vocabulary.schema.json")))
        return p.returncode, p.stdout
    if jack == "verbtable":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "verb_table.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    if jack == "presetschema":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "preset_format.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    if jack in ("nopins", "ciguards"):
        script = {"nopins": "no_pins.py", "ciguards": "ci_guards.py"}[jack]
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", script), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    env = dict(os.environ, ONLY=name, PLUGIN_HOSTD=os.path.join(tree, "plugin-hostd"), FAKE_HOST=FAKE)
    cmd = [os.path.join(ROOT, "tests", "jack_e2e.sh")] if jack else [sys.executable, os.path.join(ROOT, "tests", "daemon_test.py")]
    p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout


failed = 0
# the tests that need a directory root cannot be refused, and so skip themselves as root
ROOT_WRITES_READ_ONLY = ("a_read_only_directory_stops_the_daemon_with_its_code_and_names_the_key",
                         "a_directory_that_turns_read_only_makes_the_scan_answer_its_code")
work = tempfile.mkdtemp(prefix="plugin-hostd-sabotage.")
try:
    for entry in SABOTAGE:
        what, path, text, repl, name = entry[:5]
        # SABOTAGE_ONLY=<words>: the arms whose test name holds them, for a change that touches a few guards
        if os.environ.get("SABOTAGE_ONLY") and os.environ["SABOTAGE_ONLY"] not in name:
            continue
        jack = entry[5] if len(entry) > 5 else False
        # SABOTAGE_KIND=<kind>: only the arms of that kind ("history", "pin", ...)
        if os.environ.get("SABOTAGE_KIND") and os.environ["SABOTAGE_KIND"] != jack:
            continue
        if os.geteuid() == 0 and name in ROOT_WRITES_READ_ONLY:
            print("skip sabotage (root writes a 0500 directory, so the test skips itself): %s" % what)
            continue
        if jack == "meters" and not (os.environ.get("FAKE_COMPRESSOR_CLAP") and os.environ.get("JACK_METER_SOURCE")):
            print("skip sabotage (no FAKE_COMPRESSOR_CLAP and JACK_METER_SOURCE of omx-clap-host): %s" % what)
            continue
        if jack == "info" and not os.environ.get("FAKE_CLAP"):
            print("skip sabotage (no FAKE_CLAP of omx-clap-host): %s" % what)
            continue
        if jack in ("jack", "lv2", "meters", "info") and not os.environ.get("OMX_CLAP_HOST"):
            print("skip sabotage (no OMX_CLAP_HOST): %s" % what)
            continue
        if entry[5:] == ("lv2",) and not all(os.environ.get(v) for v in ("MOD_HOST", "LV2_DIR", "LV2_URI", "LV2_BUNDLE", "LV2_PARAM")):
            print("skip sabotage (no LV2 bundle to drive mod-host with): %s" % what)
            continue
        tree = os.path.join(work, "t")
        shutil.rmtree(tree, ignore_errors=True)
        if jack == "readme":
            os.makedirs(tree)
            for f in ("README.md", "BUILDING.md"):
                shutil.copy(os.path.join(ROOT, f), tree)
        elif jack in ("history", "proc"):
            for d in ("src", "include"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tree, d), ignore=shutil.ignore_patterns("*.o"))
            shutil.copy(os.path.join(ROOT, "Makefile"), tree)
        elif jack == "alloc":
            shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tree, "src"))
            shutil.copytree(os.path.join(ROOT, "include"), os.path.join(tree, "include"))
            shutil.copy(os.path.join(ROOT, "Makefile"), tree)
            os.makedirs(os.path.join(tree, "tests"))
            for f in ("gesture_alloc_test.c", "lv2_alloc_test.c"):
                shutil.copy(os.path.join(ROOT, "tests", f), os.path.join(tree, "tests"))
        elif jack == "probe":
            # the probe is built by the Makefile's own rule: its sources, headers and the spec its VERSION is read from
            shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tree, "src"))
            shutil.copytree(os.path.join(ROOT, "include"), os.path.join(tree, "include"))
            shutil.copytree(os.path.join(ROOT, "packaging"), os.path.join(tree, "packaging"))
            shutil.copy(os.path.join(ROOT, "Makefile"), tree)
            build_probe(tree)
        elif jack == "presetschema":
            os.makedirs(os.path.join(tree, "protocol"))
            shutil.copy(os.path.join(ROOT, "protocol", "preset.schema.json"), os.path.join(tree, "protocol"))
        elif jack == "probeschema":
            os.makedirs(os.path.join(tree, "protocol"))
            shutil.copy(os.path.join(ROOT, "protocol", "probe-output.schema.json"), os.path.join(tree, "protocol"))
        elif jack == "vocabulary":
            shutil.copytree(os.path.join(ROOT, "protocol"), os.path.join(tree, "protocol"))
            datadir = subprocess.run(["pkg-config", "--variable=datadir", "omx-contract"], capture_output=True, text=True,
                                     check=True).stdout.strip()
            shutil.copy(os.path.join(datadir, "omx-vocabulary.schema.json"), tree)
        elif jack == "contract":
            for d in ("src", "include", "tools", "protocol"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tree, d))
            os.makedirs(os.path.join(tree, "tests"))
            shutil.copy(os.path.join(ROOT, "tests", "contract_derived.py"), os.path.join(tree, "tests"))
            for f in ("Makefile",):
                shutil.copy(os.path.join(ROOT, f), tree)
            os.makedirs(os.path.join(tree, "packaging"))
            shutil.copy(os.path.join(ROOT, "packaging", "plugin-hostd.spec"), os.path.join(tree, "packaging"))
        elif jack in ("planner", "qualcost"):
            shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tree, "src"))
            shutil.copytree(os.path.join(ROOT, "include"), os.path.join(tree, "include"))
            shutil.copy(os.path.join(ROOT, "Makefile"), tree)
        elif jack in ("consumer", "verbtable"):
            shutil.copytree(os.path.join(ROOT, "include"), os.path.join(tree, "include"))
        elif jack == "nopins":
            for f in ("packaging/plugin-hostd.spec", "debian/control", ".github/workflows/ci.yml"):
                os.makedirs(os.path.dirname(os.path.join(tree, f)), exist_ok=True)
                shutil.copy(os.path.join(ROOT, f), os.path.join(tree, f))
        elif jack == "ciguards":
            shutil.copytree(os.path.join(ROOT, ".github", "workflows"), os.path.join(tree, ".github", "workflows"))
        elif jack == "verbs":
            # the declaration, what renders and builds from it, and the tests that read it
            for d in ("data", "src", "include", "tools", "protocol", "tests", "packaging", "fuzz"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tree, d), ignore=shutil.ignore_patterns("*.o"))
            shutil.copy(os.path.join(ROOT, "Makefile"), tree)
            build(tree)
            build_probe(tree)
        else:
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
        if path.startswith("data/"):
            # a changed declaration is rendered, as make render-verbs does, before the daemon is built from it
            subprocess.run(["make", "-s", "MOD_HOST_DIR=" + MOD_HOST_DIR, "render-verbs"], cwd=tree, check=True,
                           stdout=subprocess.DEVNULL)
        if jack == "probe":
            build_probe(tree)
        elif jack not in ("readme", "nopins", "ciguards", "format", "relay", "history", "proc", "contract", "consumer", "probeschema", "presetschema", "vocabulary", "alloc",
                          "verbtable", "planner", "qualcost"):
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

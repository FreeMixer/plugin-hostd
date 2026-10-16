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
# tests/readme_build.py, with no daemon to build; "nopins" breaks the packaging or a workflow and runs tests/no_pins.py
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
    ("an own lv2 worker keeps the whole bundle set", "src/supervisor.c", "    if (!f->narrow_world || w->pool || !uri)\n        return NULL;",
     "    return NULL;", "lv2_own_worker_sees_one_bundle_and_replays_after_a_kill", "lv2"),
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
     "        if (i->unreplayed)\n            continue;\n        for (m = 0; m < i->ntail; m++)",
     "        for (m = 0; m < i->ntail; m++)", "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a refused replay is not announced", "src/supervisor.c", "    event(PHD_EVENT_REPLAY_REFUSED_FMT, i->id, code);\n", "",
     "a_binary_swapped_while_its_worker_was_down_is_not_replayed"),
    ("a worker's refusal of a replayed add is taken for the instance", "src/supervisor.c",
     "        if (code < 0)\n        {\n            replay_refused(w, i, add, code);\n            continue;\n        }\n", "",
     "a_layout_pinned_again_while_its_worker_was_down_is_refused_by_the_replayed_add"),
    ("a worker's feedback is not read", "src/supervisor.c", "    relay_add(w->fb_fd);\n", "",
     "worker_feedback_reaches_the_controller_verbatim_and_in_order"),
    ("the relay writes nothing to the controller", "src/relay.c",
     "            send_line(start, nul - start + 1);\n", "",
     "worker_feedback_reaches_the_controller_verbatim_and_in_order"),
    ("monitor_output is not in the ledger", "src/supervisor.c", "    { MONITOR_OUTPUT, KIND_HOST, 2 },\n", "",
     "a_respawned_worker_reports_the_same_outputs_once_each"),
    ("a repeated monitor_output is replayed twice", "src/supervisor.c", "    { MONITOR_OUTPUT, KIND_HOST, 2 },",
     "    { MONITOR_OUTPUT, KIND_HOST, 0 },", "a_respawned_worker_reports_the_same_outputs_once_each"),
    ("a worker is read only while a controller listens", "src/relay.c",
     "        for (i = 0; i < g_nsrc; i++)\n            if (!g_src[i].eof)\n",
     "        for (i = 0; i < g_nsrc; i++)\n            if (!g_src[i].eof && g_client >= 0)\n",
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
     "        .narrow_world = lv2_narrow_world,\n        .pin_collect = lv2_pin_collect,\n        .layout_check = 0,",
     "        .pin_collect = lv2_pin_collect,\n        .layout_check = 0,",
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
    ("a worker's remote_pages_changed is not relayed", "src/relay.c",
     "            send_line(start, nul - start + 1);\n", "",
     "remote_pages_changed_from_a_worker_reaches_the_controller"),
    ("a CLAP worker is not told track_info again after a kill", "src/supervisor.c",
     "if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(", "if (0 && replay_line(",
     "clap_track_info_and_remote_pages_reach_the_plugin_through_the_daemon", "info"),
    ("meters behind the daemon never reach the controller", "src/supervisor.c", "    relay_add(w->fb_fd);\n", "",
     "clap_meters_reach_the_controller_through_the_daemon_and_survive_a_kill", "meters"),
    ("a SHA-256 round constant is wrong", "include/plugin-hostd/pin.h", "0x428a2f98, 0x71374491", "0x428a2f98, 0x71374490",
     "pin.h", "pin"),
    ("a tab in a name is not escaped", "include/plugin-hostd/pin.h", "*s == '\\t' ? \"\\\\t\" : ", "", "pin.h", "pin"),
    ("an LV2 port's properties are not sorted", "include/plugin-hostd/pin.h",
     "            qsort(props, p->nproperties, sizeof(*props), phd_layout_bytewise);\n", "", "pin.h", "pin"),
    ("a number declared by no port is written as its bits", "include/plugin-hostd/pin.h",
     "    if (!declared)\n", "    if (0)\n", "pin.h", "pin"),
    ("the build steps are back on the README", "README.md", "Building from source: see [BUILDING.md](BUILDING.md).",
     "Building from source:\n\n    make\n\nsee [BUILDING.md](BUILDING.md).", "README.md runs no build tool", "readme"),
    ("BUILDING.md lost its build command", "BUILDING.md", "    make [MOD_HOST_DIR=<mod-host checkout>]\n", "",
     "README.md runs no build tool", "readme"),
    ("the spec lost the floor of omx-clap-host-tests", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.7.0\n", "", "no pin anywhere", "nopins"),
    ("debian/control lost the floor of omx-clap-host-tests", "debian/control",
     "               omx-clap-host-tests (>= 0.7.0~),\n", "", "no pin anywhere", "nopins"),
    ("the spec caps omx-clap-host-tests with a ceiling again", "packaging/plugin-hostd.spec",
     "BuildRequires: omx-clap-host-tests >= 0.7.0\n", "BuildRequires: omx-clap-host-tests >= 0.7.0\nBuildRequires: omx-clap-host-tests < 0.8\n",
     "no pin anywhere", "nopins"),
    ("debian/control caps omx-clap-host-tests with a ceiling again", "debian/control",
     "               omx-clap-host-tests (>= 0.7.0~),\n", "               omx-clap-host-tests (>= 0.7.0~),\n               omx-clap-host-tests (<< 0.8~),\n",
     "no pin anywhere", "nopins"),
    ("a workflow pins omx-clap-core by a ref variable again", ".github/workflows/ci.yml",
     "permissions:\n  contents: read\n", "permissions:\n  contents: read\n\nenv:\n  OMX_CLAP_HOST_REF: v0.4.0\n",
     "no pin anywhere", "nopins"),
    ("a workflow checks omx-clap-core out again", ".github/workflows/ci.yml",
     "      - uses: actions/checkout@v4\n\n      # the FreeMixer channel: where the BuildRequires Fedora does not carry (omx-clap-host-tests) come from\n      - name: Add the FreeMixer channel\n        run: dnf config-manager addrepo --setopt=retries=10 --from-repofile=https://freemixer.github.io/rpm/freemixer.repo\n\n      # the worker and the fixtures",
     "      - uses: actions/checkout@v4\n        with:\n          repository: FreeMixer/omx-clap-core\n\n      # the FreeMixer channel: where the BuildRequires Fedora does not carry (omx-clap-host-tests) come from\n      - name: Add the FreeMixer channel\n        run: dnf config-manager addrepo --setopt=retries=10 --from-repofile=https://freemixer.github.io/rpm/freemixer.repo\n\n      # the worker and the fixtures",
     "no pin anywhere", "nopins"),
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


def run_test(tree, name, jack=False):
    if jack == "format":
        return run_format_test(tree)
    if jack == "pin":
        return run_pin_test(tree)
    if jack == "readme":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "readme_build.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
    if jack == "nopins":
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "no_pins.py"), tree], capture_output=True,
                           text=True, timeout=60)
        return p.returncode, p.stdout
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
        elif jack == "nopins":
            for f in ("packaging/plugin-hostd.spec", "debian/control", ".github/workflows/ci.yml"):
                os.makedirs(os.path.dirname(os.path.join(tree, f)), exist_ok=True)
                shutil.copy(os.path.join(ROOT, f), os.path.join(tree, f))
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
        if jack not in ("readme", "nopins", "format"):
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

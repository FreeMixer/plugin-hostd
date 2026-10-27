// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#ifndef PLUGIN_HOSTD_VOCABULARY_H
#define PLUGIN_HOSTD_VOCABULARY_H
/*
 * GENERATED — DO NOT EDIT BY HAND.
 * Produced by `omx-contract render --target c` from FreeMixer/plugin-hostd's data/: the vocabulary
 * (docs/data-layout.md). A code is OMX_ and the code in upper snake case, and a reply code that carries a resp has it as that name and _RESP; a word is OMX_<ITEM>_<NAME>, each words
 * item with its _COUNT and an _INIT of its words in their order. A consumer writes and compares these, never a
 * literal of its own.
 */

/* PLUGIN_HOSTD_GROUPING_REASONS (data/grouping.json) */
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_REFUSED "refused" ///< The pin's verdict is refused: the plugin is not run in a group, and an add of it answers -516.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_PIN "no-pin" ///< The plugin has no pin and pin_mode is strict: an add of it answers -508.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_VERDICT "no-verdict" ///< The pin carries no verdict (a pin the daemon learned on first use): the plugin stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_VERDICT_ISOLATED "verdict-isolated" ///< The pin's verdict is isolated: the plugin stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_FORMAT_WORLD "format-world" ///< The plugin's format pins only in a world of its own and no world holding the plugin can be built for a shared worker: it stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_CRASHED "history-crashed" ///< The history marks the plugin as crashed on this host class, a crash within the last 30 days, or the supervisor has quarantined it now: the plugin stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_XRUNS "history-xruns" ///< The history marks the plugin as raising xruns when grouped, its share of xrun windows in a group over its share alone by the margin after enough windows: the plugin stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_COST_OVER "cost-over" ///< The plugin's cost, alone, is over group_cost_max: it stays alone.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_FORMAT_MIXED "format-mixed" ///< No one worker program runs this plugin together with the open segment: it starts a new segment.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUP_FULL "group-full" ///< The open segment holds group_max members: the plugin starts a new segment.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUP_COST "group-cost" ///< Adding the plugin's cost takes the open segment over group_cost_max: it starts a new segment.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_COST_ASSUMED "cost-assumed" ///< The plugin has no known cost and joined a segment at the median of the known costs of that segment, zero when none is known.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_NEIGHBOUR "no-neighbour" ///< The plugin passed every rule but has no neighbour it can share a worker with: it is alone only because of the members around it.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUPING_OFF "grouping-off" ///< The setting grouping is off: the plugin would share a worker, and the plan was answered and not applied.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_UNAVAILABLE "history-unavailable" ///< The history cannot be read, its file is blocked or history_window_s is 0: the plan was made from the pins and the costs alone, as for a plugin with no history, and this plugin had nothing harder to say.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_PLAN_REFUSED "plan-refused" ///< A segment could not be formed: the plan was not applied and nothing moved. The word is followed by a colon and the number of the refusal, plan-refused:-501.
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_COUNT 16u
#define OMX_PLUGIN_HOSTD_GROUPING_REASONS_INIT { "refused", "no-pin", "no-verdict", "verdict-isolated", "format-world", "history-crashed", "history-xruns", "cost-over", "format-mixed", "group-full", "group-cost", "cost-assumed", "no-neighbour", "grouping-off", "history-unavailable", "plan-refused" }

/* PLUGIN_HOSTD_HISTORY_KEYS (data/history.json) */
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_FIRST "first" ///< UTC seconds of the first window.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_LAST "last" ///< UTC seconds of the last window.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_WINDOWS_SOLO "windows_solo" ///< Windows the plugin ran in a worker of its own.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_WINDOWS_GROUPED "windows_grouped" ///< Windows the plugin ran in a worker of two or more.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_CPU_P95_SOLO "cpu_p95_solo" ///< Percent of one core, the worker's utime plus stime over a window, an estimate of the 95th percentile of the windows run alone.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_CPU_MAX_SOLO "cpu_max_solo" ///< Percent of one core, the largest window run alone.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_PSS_MB_SOLO "pss_mb_solo" ///< MiB, the Pss of the worker's smaps_rollup, the largest window run alone.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_XRUN_WINDOWS_SOLO "xrun_windows_solo" ///< Windows run alone in which JACK counted at least one xrun.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_XRUN_WINDOWS_GROUPED "xrun_windows_grouped" ///< Windows run in a group in which JACK counted at least one xrun.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_CRASHES_SOLO "crashes_solo" ///< Worker deaths of a worker of its own that the daemon attributed to the plugin.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_CRASHES_GROUPED "crashes_grouped" ///< Worker deaths of a group that the daemon attributed to the plugin.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_RESTARTS_GROUPED "restarts_grouped" ///< Worker deaths of a group the plugin was a member of and was not the culprit of.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_QUARANTINES "quarantines" ///< Times the supervisor quarantined the plugin.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_LAST_CRASH "last_crash" ///< UTC seconds of the last crash the plugin was blamed for alone.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_LAST_CRASH_GROUPED "last_crash_grouped" ///< UTC seconds of the last crash the plugin was blamed for in a group.
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_COUNT 15u
#define OMX_PLUGIN_HOSTD_HISTORY_KEYS_INIT { "first", "last", "windows_solo", "windows_grouped", "cpu_p95_solo", "cpu_max_solo", "pss_mb_solo", "xrun_windows_solo", "xrun_windows_grouped", "crashes_solo", "crashes_grouped", "restarts_grouped", "quarantines", "last_crash", "last_crash_grouped" }

/* PLUGIN_HOSTD_REPLY_CODES (data/verbs.json) */
#define OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID "reply.plugin-hostd.placement-invalid" ///< PHD_ERR_PLACEMENT_INVALID: not a placement, or not valid here
#define OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP (-501)
#define OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND "reply.plugin-hostd.no-backend" ///< PHD_ERR_NO_BACKEND: no worker program for the scheme
#define OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND_RESP (-502)
#define OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN "reply.plugin-hostd.worker-spawn" ///< PHD_ERR_WORKER_SPAWN: the worker is not up
#define OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP (-503)
#define OMX_REPLY_PLUGIN_HOSTD_REPLAY "reply.plugin-hostd.replay" ///< PHD_ERR_REPLAY: the name of a refused replay on stderr, never a reply
#define OMX_REPLY_PLUGIN_HOSTD_REPLAY_RESP (-504)
#define OMX_REPLY_PLUGIN_HOSTD_GAVE_UP "reply.plugin-hostd.gave-up" ///< PHD_ERR_GAVE_UP: the storm bound is spent for that placement
#define OMX_REPLY_PLUGIN_HOSTD_GAVE_UP_RESP (-505)
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_WORKER "reply.plugin-hostd.no-such-worker" ///< PHD_ERR_NO_SUCH_WORKER: no such worker
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_WORKER_RESP (-506)
#define OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED "reply.plugin-hostd.verb-dropped" ///< PHD_ERR_VERB_DROPPED: the worker died on this very command and the daemon dropped it
#define OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP (-507)
#define OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH "reply.plugin-hostd.pin-binary-mismatch" ///< PHD_ERR_PIN_BINARY_MISMATCH: a pinned file is missing or its SHA-256 differs
#define OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP (-509)
#define OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED "reply.plugin-hostd.lv2-adapter-refused" ///< PHD_ERR_LV2_ADAPTER_REFUSED: the lv2-clap worker's LV2 adapter cannot run this plugin
#define OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED_RESP (-512)
#define OMX_REPLY_PLUGIN_HOSTD_NO_PRESET_LIST "reply.plugin-hostd.no-preset-list" ///< PHD_ERR_NO_PRESET_LIST: the instance's worker cannot list the plugin's presets
#define OMX_REPLY_PLUGIN_HOSTD_NO_PRESET_LIST_RESP (-515)
#define OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED "reply.plugin-hostd.pin-refused" ///< PHD_ERR_PIN_REFUSED: the plugin's pin carries verdict=refused
#define OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP (-516)
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE "reply.plugin-hostd.chain-unknown-instance" ///< PHD_ERR_CHAIN_UNKNOWN_INSTANCE: a member is an instance no add made
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE_RESP (-518)
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE "reply.plugin-hostd.chain-duplicate" ///< PHD_ERR_CHAIN_DUPLICATE: an instance is named twice in one chain
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE_RESP (-519)
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY "reply.plugin-hostd.chain-instance-busy" ///< PHD_ERR_CHAIN_INSTANCE_BUSY: a member is already in another chain
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY_RESP (-520)
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT "reply.plugin-hostd.chain-mixed-format" ///< PHD_ERR_CHAIN_MIXED_FORMAT: no one worker program runs every member
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT_RESP (-521)
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN "reply.plugin-hostd.no-such-chain" ///< PHD_ERR_NO_SUCH_CHAIN: a chain no chain line declared
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN_RESP (-522)
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NOT_OFFERED "reply.plugin-hostd.preset-not-offered" ///< PHD_ERR_PRESET_NOT_OFFERED: a stable name the plugin does not offer
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NOT_OFFERED_RESP (-523)
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_INVALID "reply.plugin-hostd.preset-invalid" ///< PHD_ERR_PRESET_INVALID: a preset file or path that is not the preset format
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_INVALID_RESP (-524)
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NEEDS_STATE "reply.plugin-hostd.preset-needs-state" ///< PHD_ERR_PRESET_NEEDS_STATE: a preset file that carries state for a worker that cannot take state
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NEEDS_STATE_RESP (-525)
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_PLUGIN_CHANGED "reply.plugin-hostd.preset-plugin-changed" ///< PHD_ERR_PRESET_PLUGIN_CHANGED: the preset file's plugin id, version or fingerprint is not the instance's
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_PLUGIN_CHANGED_RESP (-526)
#define OMX_REPLY_PLUGIN_HOSTD_LOAD_REFUSED "reply.plugin-hostd.load-refused" ///< PHD_ERR_LOAD_REFUSED: the plugin refused the preset or the state its file carries
#define OMX_REPLY_PLUGIN_HOSTD_LOAD_REFUSED_RESP (-527)
#define OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE "reply.plugin-hostd.dir-not-writable" ///< PHD_ERR_DIR_NOT_WRITABLE: descriptor_dir or qualification_dir cannot be made or written
#define OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP (-528)
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT "reply.plugin-hostd.descriptor-absent" ///< PHD_ERR_DESCRIPTOR_ABSENT: no descriptor (panel) for the plugin's binary as it is now
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT_RESP (-529)
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING "reply.plugin-hostd.descriptor-pending" ///< PHD_ERR_DESCRIPTOR_PENDING: the scan its add started has not written the descriptor (panel) yet
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING_RESP (-530)
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED "reply.plugin-hostd.descriptor-scan-failed" ///< PHD_ERR_DESCRIPTOR_SCAN_FAILED: the plugin's last scan wrote no descriptor (panel)
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP (-531)
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_PLAN "reply.plugin-hostd.no-such-plan" ///< PHD_ERR_NO_SUCH_PLAN: a chain no plan verb planned
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_PLAN_RESP (-532)

#endif /* PLUGIN_HOSTD_VOCABULARY_H */

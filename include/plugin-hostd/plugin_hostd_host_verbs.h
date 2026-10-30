// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#ifndef PLUGIN_HOSTD_HOST_VERBS_H
#define PLUGIN_HOSTD_HOST_VERBS_H
/*
 * GENERATED: DO NOT EDIT BY HAND.
 * Produced by `omx-contract render --target c` from plugin-hostd's files.
 * The host verbs (docs/contract-dir.md): a verb is OMX_VERB_<VERB>, its word, OMX_VERB_<VERB>_FMT, the line
 * protocol_add_command takes, and OMX_VERB_<VERB>_REPLY; a verb that answers refusals carries their resp numbers
 * in OMX_VERB_<VERB>_CODES_INIT. plugin_hostd_host_verbs() is the table of what each host owes each verb.
 */

#include <string.h>

#ifndef OMX_HOST_VERB_TYPES_H
#define OMX_HOST_VERB_TYPES_H
/* What a host owes a verb: required, answered as its grammar says; optional, answered or refused, never misread;
 * unsupported, refused on purpose. */
enum omx_host_verb_level {
  OMX_HOST_VERB_UNSUPPORTED = 0,
  OMX_HOST_VERB_OPTIONAL = 1,
  OMX_HOST_VERB_REQUIRED = 2,
};
/* The hosts of VERB_HOSTS, a column each of a verb's level, in this order. */
#define OMX_HOST_VERB_HOST_PLUGIN_HOSTD 0u
#define OMX_HOST_VERB_HOST_OMX_CLAP_HOST 1u
#define OMX_HOST_VERB_HOST_MOD_HOST 2u
#define OMX_HOST_VERB_HOST_COUNT 3u
#define OMX_HOST_VERB_HOSTS_INIT { "plugin-hostd", "omx-clap-host", "mod-host" }
struct omx_host_verb {
  const char *verb;
  const char *format;
  const char *reply;
  enum omx_host_verb_level level[OMX_HOST_VERB_HOST_COUNT];
};
#endif /* OMX_HOST_VERB_TYPES_H */

/* PLUGIN_HOSTD_VERBS.workerList (data/verbs.json): The workers, one record each: <core> is the audio core the setting placement pinned the worker to, - for none; <pool> is on for a worker started with the CLAP thread pool (the pin of its plugin carries pool=cores, and no other plugin shares the worker), qualified for every other. */
#define OMX_VERB_WORKER_LIST "worker_list"
#define OMX_VERB_WORKER_LIST_FMT "worker_list"
#define OMX_VERB_WORKER_LIST_REPLY "resp <n> <worker>:<pid>:<format>:<state>:<core>:<pool>:<place>:<i>,<i>,..."
#define OMX_VERB_WORKER_LIST_CODES_COUNT 2u
#define OMX_VERB_WORKER_LIST_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.instanceInfo (data/verbs.json): Where an instance lives and what it has cost. */
#define OMX_VERB_INSTANCE_INFO "instance_info"
#define OMX_VERB_INSTANCE_INFO_FMT "instance_info %i"
#define OMX_VERB_INSTANCE_INFO_REPLY "resp 0 <worker> <pid> <state> <crashes> <quarantined>"
#define OMX_VERB_INSTANCE_INFO_CODES_COUNT 3u
#define OMX_VERB_INSTANCE_INFO_CODES_INIT { -3, -901, -902 } /* reply.host.instance-non-exists, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.supervisorReset (data/verbs.json): Re-arm the storm bound and the backoff of a given-up placement: [<worker> | all]. */
#define OMX_VERB_SUPERVISOR_RESET "supervisor_reset"
#define OMX_VERB_SUPERVISOR_RESET_FMT "supervisor_reset ..."
#define OMX_VERB_SUPERVISOR_RESET_REPLY "resp 0"
#define OMX_VERB_SUPERVISOR_RESET_CODES_COUNT 3u
#define OMX_VERB_SUPERVISOR_RESET_CODES_INIT { -506, -901, -902 } /* reply.plugin-hostd.no-such-worker, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.quarantineClear (data/verbs.json): Let a quarantined instance go back where its placement says: <instance> | all. */
#define OMX_VERB_QUARANTINE_CLEAR "quarantine_clear"
#define OMX_VERB_QUARANTINE_CLEAR_FMT "quarantine_clear %s"
#define OMX_VERB_QUARANTINE_CLEAR_REPLY "resp 0"
#define OMX_VERB_QUARANTINE_CLEAR_CODES_COUNT 3u
#define OMX_VERB_QUARANTINE_CLEAR_CODES_INIT { -3, -901, -902 } /* reply.host.instance-non-exists, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.policySet (data/verbs.json): The placement of an add that says default: <format | *> own | pool:<name>. */
#define OMX_VERB_POLICY_SET "policy_set"
#define OMX_VERB_POLICY_SET_FMT "policy_set %s %s"
#define OMX_VERB_POLICY_SET_REPLY "resp 0"
#define OMX_VERB_POLICY_SET_CODES_COUNT 3u
#define OMX_VERB_POLICY_SET_CODES_INIT { -501, -901, -902 } /* reply.plugin-hostd.placement-invalid, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.poolConfig (data/verbs.json): The instances a pool holds before a sibling opens: <name> <max_instances>. */
#define OMX_VERB_POOL_CONFIG "pool_config"
#define OMX_VERB_POOL_CONFIG_FMT "pool_config %s %i"
#define OMX_VERB_POOL_CONFIG_REPLY "resp 0"
#define OMX_VERB_POOL_CONFIG_CODES_COUNT 3u
#define OMX_VERB_POOL_CONFIG_CODES_INIT { -501, -901, -902 } /* reply.plugin-hostd.placement-invalid, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.workerEnv (data/verbs.json): The cpu list and the nice value of the workers of a format, at spawn and on the ones running: <format | *> <cpu-list | -> <nice | ->. */
#define OMX_VERB_WORKER_ENV "worker_env"
#define OMX_VERB_WORKER_ENV_FMT "worker_env %s %s %s"
#define OMX_VERB_WORKER_ENV_REPLY "resp 0"
#define OMX_VERB_WORKER_ENV_CODES_COUNT 2u
#define OMX_VERB_WORKER_ENV_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinSet (data/verbs.json): The pin of one plugin: <uri> <path>=<sha256>[,<path>=<sha256>...] <scheme>:<sha256> [verdict=<verdict>]. */
#define OMX_VERB_PIN_SET "pin_set"
#define OMX_VERB_PIN_SET_FMT "pin_set %s %s %s ..."
#define OMX_VERB_PIN_SET_REPLY "resp 0"
#define OMX_VERB_PIN_SET_CODES_COUNT 3u
#define OMX_VERB_PIN_SET_CODES_INIT { -516, -901, -902 } /* reply.plugin-hostd.pin-refused, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinClear (data/verbs.json): Forget the pin of one plugin, or of every one: <uri> | all. */
#define OMX_VERB_PIN_CLEAR "pin_clear"
#define OMX_VERB_PIN_CLEAR_FMT "pin_clear %s"
#define OMX_VERB_PIN_CLEAR_REPLY "resp 0"
#define OMX_VERB_PIN_CLEAR_CODES_COUNT 2u
#define OMX_VERB_PIN_CLEAR_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinReload (data/verbs.json): Read the pin_file and the pins_dir files again and put the pins in at once; running instances keep running. */
#define OMX_VERB_PIN_RELOAD "pin_reload"
#define OMX_VERB_PIN_RELOAD_FMT "pin_reload"
#define OMX_VERB_PIN_RELOAD_REPLY "resp 0"
#define OMX_VERB_PIN_RELOAD_CODES_COUNT 1u
#define OMX_VERB_PIN_RELOAD_CODES_INIT { -902 } /* reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinChanged (data/verbs.json): The sync's notice that the pin file was rewritten: the same as pin_reload, with or without the <uri> [files|layout] of the pin_changed event. */
#define OMX_VERB_PIN_CHANGED "pin_changed"
#define OMX_VERB_PIN_CHANGED_FMT "pin_changed ..."
#define OMX_VERB_PIN_CHANGED_REPLY "resp 0"
#define OMX_VERB_PIN_CHANGED_CODES_COUNT 1u
#define OMX_VERB_PIN_CHANGED_CODES_INIT { -902 } /* reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinAccept (data/verbs.json): Under pin_mode first-use, take the plugin's files as they are now as its pin: <uri>. */
#define OMX_VERB_PIN_ACCEPT "pin_accept"
#define OMX_VERB_PIN_ACCEPT_FMT "pin_accept %s"
#define OMX_VERB_PIN_ACCEPT_REPLY "resp 0"
#define OMX_VERB_PIN_ACCEPT_CODES_COUNT 5u
#define OMX_VERB_PIN_ACCEPT_CODES_INIT { -508, -509, -516, -901, -902 } /* reply.host.pin-absent, reply.plugin-hostd.pin-binary-mismatch, reply.plugin-hostd.pin-refused, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.pinLayout (data/verbs.json): Sent by the daemon to a worker that checks layouts, after it accepted an add whose layout pin is unknown: the layout the worker found after init. */
#define OMX_VERB_PIN_LAYOUT "pin_layout"
#define OMX_VERB_PIN_LAYOUT_FMT "pin_layout %i"
#define OMX_VERB_PIN_LAYOUT_REPLY "resp 0 <scheme>:<sha256>"

/* PLUGIN_HOSTD_VERBS.lv2WorkerSet (data/verbs.json): The worker of one LV2 plugin, for its adds from now on: <uri> <mod-host | omx-clap-host | auto | ->. */
#define OMX_VERB_LV2_WORKER_SET "lv2_worker_set"
#define OMX_VERB_LV2_WORKER_SET_FMT "lv2_worker_set %s %s"
#define OMX_VERB_LV2_WORKER_SET_REPLY "resp 0"
#define OMX_VERB_LV2_WORKER_SET_CODES_COUNT 2u
#define OMX_VERB_LV2_WORKER_SET_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.chain (data/verbs.json): The instances, in this order, are one chain run in one worker: <chain> <instance> [<instance> ...]; a worker that runs chains in one client is sent the line with the members it holds. */
#define OMX_VERB_CHAIN "chain"
#define OMX_VERB_CHAIN_FMT "chain %i %i ..."
#define OMX_VERB_CHAIN_REPLY "resp 0"
#define OMX_VERB_CHAIN_CODES_COUNT 7u
#define OMX_VERB_CHAIN_CODES_INIT { -518, -519, -520, -521, -501, -901, -902 } /* reply.plugin-hostd.chain-unknown-instance, reply.plugin-hostd.chain-duplicate, reply.plugin-hostd.chain-instance-busy, reply.plugin-hostd.chain-mixed-format, reply.plugin-hostd.placement-invalid, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.chainClear (data/verbs.json): Forget the chain: each member goes to a worker of its own. */
#define OMX_VERB_CHAIN_CLEAR "chain_clear"
#define OMX_VERB_CHAIN_CLEAR_FMT "chain_clear %i"
#define OMX_VERB_CHAIN_CLEAR_REPLY "resp 0"
#define OMX_VERB_CHAIN_CLEAR_CODES_COUNT 3u
#define OMX_VERB_CHAIN_CLEAR_CODES_INIT { -522, -901, -902 } /* reply.plugin-hostd.no-such-chain, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.chainGet (data/verbs.json): Read a chain back: its worker, its members in the declared order, and the members its worker runs now. */
#define OMX_VERB_CHAIN_GET "chain_get"
#define OMX_VERB_CHAIN_GET_FMT "chain_get %i"
#define OMX_VERB_CHAIN_GET_REPLY "resp 0 <worker> <instance>,... <instance>,..."
#define OMX_VERB_CHAIN_GET_CODES_COUNT 3u
#define OMX_VERB_CHAIN_GET_CODES_INIT { -522, -901, -902 } /* reply.plugin-hostd.no-such-chain, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.descriptorGet (data/verbs.json): The scanned descriptor of the plugin, answered from descriptor_dir: <uri>. */
#define OMX_VERB_DESCRIPTOR_GET "descriptor_get"
#define OMX_VERB_DESCRIPTOR_GET_FMT "descriptor_get %s"
#define OMX_VERB_DESCRIPTOR_GET_REPLY "resp 0 \"<path>\""
#define OMX_VERB_DESCRIPTOR_GET_CODES_COUNT 6u
#define OMX_VERB_DESCRIPTOR_GET_CODES_INIT { -528, -529, -530, -531, -901, -902 } /* reply.plugin-hostd.dir-not-writable, reply.plugin-hostd.descriptor-absent, reply.plugin-hostd.descriptor-pending, reply.plugin-hostd.descriptor-scan-failed, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.panelGet (data/verbs.json): The panel the plugin publishes, answered from descriptor_dir: <uri>. */
#define OMX_VERB_PANEL_GET "panel_get"
#define OMX_VERB_PANEL_GET_FMT "panel_get %s"
#define OMX_VERB_PANEL_GET_REPLY "resp 0 \"<path>\""
#define OMX_VERB_PANEL_GET_CODES_COUNT 6u
#define OMX_VERB_PANEL_GET_CODES_INIT { -528, -529, -530, -531, -901, -902 } /* reply.plugin-hostd.dir-not-writable, reply.plugin-hostd.descriptor-absent, reply.plugin-hostd.descriptor-pending, reply.plugin-hostd.descriptor-scan-failed, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.presetList (data/verbs.json): The plugin's presets, the ones its preset discovery or its bundle lists. */
#define OMX_VERB_PRESET_LIST "preset_list"
#define OMX_VERB_PRESET_LIST_FMT "preset_list %i"
#define OMX_VERB_PRESET_LIST_REPLY "resp <count>"
#define OMX_VERB_PRESET_LIST_CODES_COUNT 4u
#define OMX_VERB_PRESET_LIST_CODES_INIT { -515, -3, -901, -902 } /* reply.plugin-hostd.no-preset-list, reply.host.instance-non-exists, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.presetGet (data/verbs.json): One preset, 0 to count - 1: the key preset_load takes for it, and its name. */
#define OMX_VERB_PRESET_GET "preset_get"
#define OMX_VERB_PRESET_GET_FMT "preset_get %i %i"
#define OMX_VERB_PRESET_GET_REPLY "resp 0 <load_key> <name>"
#define OMX_VERB_PRESET_GET_CODES_COUNT 4u
#define OMX_VERB_PRESET_GET_CODES_INIT { -515, -3, -901, -902 } /* reply.plugin-hostd.no-preset-list, reply.host.instance-non-exists, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.presetShow (data/verbs.json): What a load of the preset would apply, on one line of JSON: the preset file's document with each state body's bytes replaced by its decoded size, or for a listed preset its name, loadKey and location. The instance form; mod-host's preset_show <uri> is its own verb. */
#define OMX_VERB_PRESET_SHOW "preset_show"
#define OMX_VERB_PRESET_SHOW_FMT "preset_show %i %s"
#define OMX_VERB_PRESET_SHOW_REPLY "resp 0 <json>"
#define OMX_VERB_PRESET_SHOW_CODES_COUNT 5u
#define OMX_VERB_PRESET_SHOW_CODES_INIT { -523, -524, -3, -901, -902 } /* reply.plugin-hostd.preset-not-offered, reply.plugin-hostd.preset-invalid, reply.host.instance-non-exists, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.historyGet (data/verbs.json): What the daemon kept of one plugin on this host class, for the binary its pin holds now: <uri>. The history is one word, digest=<sha256>,class=<host class>,crashed=<0|1>,raises_xruns=<0|1> and then every key=value of PLUGIN_HOSTD_HISTORY_KEYS, joined by commas; - when the plugin has no record or no pin, unavailable while the history file is blocked. */
#define OMX_VERB_HISTORY_GET "history_get"
#define OMX_VERB_HISTORY_GET_FMT "history_get %s"
#define OMX_VERB_HISTORY_GET_REPLY "resp 0 <history>"
#define OMX_VERB_HISTORY_GET_CODES_COUNT 2u
#define OMX_VERB_HISTORY_GET_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.historyClear (data/verbs.json): Delete the history of one plugin, every binary and host class, or all of it: <uri> | all. Refused while the history file is blocked. */
#define OMX_VERB_HISTORY_CLEAR "history_clear"
#define OMX_VERB_HISTORY_CLEAR_FMT "history_clear %s"
#define OMX_VERB_HISTORY_CLEAR_REPLY "resp 0"
#define OMX_VERB_HISTORY_CLEAR_CODES_COUNT 2u
#define OMX_VERB_HISTORY_CLEAR_CODES_INIT { -901, -902 } /* reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.plan (data/verbs.json): The instances, in signal order, are planned into the fewest workers their pins and costs allow: <chain> <instance> [<instance> ...]. Each run of consecutive members that may share a worker becomes a chain of place chain:<chain>.<k>, the others stay alone in a worker of their own; the reply names the segments in order, the members of a segment joined by commas and the segments by semicolons, then the same with each member replaced by the audio core of the worker that runs it now, - for one the setting placement did not pin. With the setting grouping off the plan is answered and kept, and nothing moves. */
#define OMX_VERB_PLAN "plan"
#define OMX_VERB_PLAN_FMT "plan %i %i ..."
#define OMX_VERB_PLAN_REPLY "resp 0 <instance>,...;<instance>,...;... <core>,...;<core>,...;..."
#define OMX_VERB_PLAN_CODES_COUNT 6u
#define OMX_VERB_PLAN_CODES_INIT { -518, -519, -520, -501, -901, -902 } /* reply.plugin-hostd.chain-unknown-instance, reply.plugin-hostd.chain-duplicate, reply.plugin-hostd.chain-instance-busy, reply.plugin-hostd.placement-invalid, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.planGet (data/verbs.json): Read the last plan of a chain back: its segments as plan answered them, then the reason of each member that has one (a word of PLUGIN_HOSTD_GROUPING_REASONS, plan-refused followed by the refusal's number), instance:reason joined by commas, - for none, then the cores of the members as plan answers them. */
#define OMX_VERB_PLAN_GET "plan_get"
#define OMX_VERB_PLAN_GET_FMT "plan_get %i"
#define OMX_VERB_PLAN_GET_REPLY "resp 0 <instance>,...;<instance>,...;... <instance>:<reason>,... <core>,...;<core>,...;..."
#define OMX_VERB_PLAN_GET_CODES_COUNT 3u
#define OMX_VERB_PLAN_GET_CODES_INIT { -532, -901, -902 } /* reply.plugin-hostd.no-such-plan, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.planClear (data/verbs.json): Forget the plan: each member goes to a worker of its own, as chain_clear does. */
#define OMX_VERB_PLAN_CLEAR "plan_clear"
#define OMX_VERB_PLAN_CLEAR_FMT "plan_clear %i"
#define OMX_VERB_PLAN_CLEAR_REPLY "resp 0"
#define OMX_VERB_PLAN_CLEAR_CODES_COUNT 3u
#define OMX_VERB_PLAN_CLEAR_CODES_INIT { -532, -901, -902 } /* reply.plugin-hostd.no-such-plan, reply.host.memory-allocation, reply.host.invalid-operation */

/* PLUGIN_HOSTD_VERBS.estimate (data/verbs.json): What a chain of these plugins would cost at a rate and a quantum, read from the qualification records with no plugin loaded: <rate> <quantum> <uri> [<uri> ...], the uris as add takes them, in signal order. The reply is the latency in frames (each member's measured latency, else its declared one, added up), the CPU as percent of one core's cycle (each member's median nanoseconds per sample times the rate, added up), the RAM in bytes (the Pss each member's worker had running alone on this host class, added up; - unless every member has one), the workers plan would place the members in, and how many members have no figure at that rate and quantum; then each of those as its position in the line, from 0, and its code (noRecord, noCell or unknownPlugin), joined by commas, - for none. The latency and the CPU add up only the members that have a figure. Then the memory: what the workers hold now in bytes (- when one cannot be read), what the members would add in bytes from the qualification records, what instances of one plugin share counted once in a segment (- when no member has a figure), the host's ram_budget_mb in bytes (- when none is set), and how many members have no such figure. */
#define OMX_VERB_ESTIMATE "estimate"
#define OMX_VERB_ESTIMATE_FMT "estimate %i %i %s ..."
#define OMX_VERB_ESTIMATE_REPLY "resp 0 <latency_frames> <cpu_percent> <ram_bytes> <workers> <unknown_count> <member>:<code>,... <ram_used_bytes> <ram_added_bytes> <ram_budget_bytes> <ram_unknown_count>"
#define OMX_VERB_ESTIMATE_CODES_COUNT 5u
#define OMX_VERB_ESTIMATE_CODES_INIT { -533, -534, -535, -901, -902 } /* reply.plugin-hostd.no-record, reply.plugin-hostd.no-cell, reply.plugin-hostd.unknown-plugin, reply.host.memory-allocation, reply.host.invalid-operation */

#define PLUGIN_HOSTD_HOST_VERB_COUNT 28u

/* Every verb, in the order of its items, with what each host owes it. */
static inline const struct omx_host_verb *plugin_hostd_host_verbs(void) {
  static const struct omx_host_verb table[PLUGIN_HOSTD_HOST_VERB_COUNT] = {
    { OMX_VERB_WORKER_LIST, OMX_VERB_WORKER_LIST_FMT, OMX_VERB_WORKER_LIST_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_INSTANCE_INFO, OMX_VERB_INSTANCE_INFO_FMT, OMX_VERB_INSTANCE_INFO_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_SUPERVISOR_RESET, OMX_VERB_SUPERVISOR_RESET_FMT, OMX_VERB_SUPERVISOR_RESET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_QUARANTINE_CLEAR, OMX_VERB_QUARANTINE_CLEAR_FMT, OMX_VERB_QUARANTINE_CLEAR_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_POLICY_SET, OMX_VERB_POLICY_SET_FMT, OMX_VERB_POLICY_SET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_POOL_CONFIG, OMX_VERB_POOL_CONFIG_FMT, OMX_VERB_POOL_CONFIG_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_WORKER_ENV, OMX_VERB_WORKER_ENV_FMT, OMX_VERB_WORKER_ENV_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_SET, OMX_VERB_PIN_SET_FMT, OMX_VERB_PIN_SET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_CLEAR, OMX_VERB_PIN_CLEAR_FMT, OMX_VERB_PIN_CLEAR_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_RELOAD, OMX_VERB_PIN_RELOAD_FMT, OMX_VERB_PIN_RELOAD_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_CHANGED, OMX_VERB_PIN_CHANGED_FMT, OMX_VERB_PIN_CHANGED_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_ACCEPT, OMX_VERB_PIN_ACCEPT_FMT, OMX_VERB_PIN_ACCEPT_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PIN_LAYOUT, OMX_VERB_PIN_LAYOUT_FMT, OMX_VERB_PIN_LAYOUT_REPLY, { OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_LV2_WORKER_SET, OMX_VERB_LV2_WORKER_SET_FMT, OMX_VERB_LV2_WORKER_SET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_CHAIN, OMX_VERB_CHAIN_FMT, OMX_VERB_CHAIN_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_CHAIN_CLEAR, OMX_VERB_CHAIN_CLEAR_FMT, OMX_VERB_CHAIN_CLEAR_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_CHAIN_GET, OMX_VERB_CHAIN_GET_FMT, OMX_VERB_CHAIN_GET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_DESCRIPTOR_GET, OMX_VERB_DESCRIPTOR_GET_FMT, OMX_VERB_DESCRIPTOR_GET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PANEL_GET, OMX_VERB_PANEL_GET_FMT, OMX_VERB_PANEL_GET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PRESET_LIST, OMX_VERB_PRESET_LIST_FMT, OMX_VERB_PRESET_LIST_REPLY, { OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PRESET_GET, OMX_VERB_PRESET_GET_FMT, OMX_VERB_PRESET_GET_REPLY, { OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PRESET_SHOW, OMX_VERB_PRESET_SHOW_FMT, OMX_VERB_PRESET_SHOW_REPLY, { OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_OPTIONAL, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_HISTORY_GET, OMX_VERB_HISTORY_GET_FMT, OMX_VERB_HISTORY_GET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_HISTORY_CLEAR, OMX_VERB_HISTORY_CLEAR_FMT, OMX_VERB_HISTORY_CLEAR_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PLAN, OMX_VERB_PLAN_FMT, OMX_VERB_PLAN_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PLAN_GET, OMX_VERB_PLAN_GET_FMT, OMX_VERB_PLAN_GET_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_PLAN_CLEAR, OMX_VERB_PLAN_CLEAR_FMT, OMX_VERB_PLAN_CLEAR_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
    { OMX_VERB_ESTIMATE, OMX_VERB_ESTIMATE_FMT, OMX_VERB_ESTIMATE_REPLY, { OMX_HOST_VERB_REQUIRED, OMX_HOST_VERB_UNSUPPORTED, OMX_HOST_VERB_UNSUPPORTED } },
  };
  return table;
}

/* The verb whose word is `verb`, or NULL. */
static inline const struct omx_host_verb *plugin_hostd_host_verb_find(const char *verb) {
  const struct omx_host_verb *t = plugin_hostd_host_verbs();
  for (unsigned i = 0; i < PLUGIN_HOSTD_HOST_VERB_COUNT; i++)
    if (!strcmp(t[i].verb, verb)) return &t[i];
  return NULL;
}

/* What the host at column `host` (an OMX_HOST_VERB_HOST_* index) owes `verb`: unsupported for a verb not here. */
static inline enum omx_host_verb_level plugin_hostd_host_verb_level(const char *verb, unsigned host) {
  const struct omx_host_verb *v = plugin_hostd_host_verb_find(verb);
  return v && host < OMX_HOST_VERB_HOST_COUNT ? v->level[host] : OMX_HOST_VERB_UNSUPPORTED;
}

#endif /* PLUGIN_HOSTD_HOST_VERBS_H */

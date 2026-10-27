/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * plugin-hostd is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * plugin-hostd is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with plugin-hostd.  If not, see <http://www.gnu.org/licenses/>.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The protocol surface plugin-hostd owns, declared once. The daemon compiles against this header; the tables of
 * README.md, the key list of the man page and protocol/plugin-hostd.json are generated from it by tools/protocol-gen.c
 * (make gen; make check-generated fails on drift). A consumer includes this header and reads nothing else, or reads the
 * JSON when it is not C. The mod-host protocol itself, which the daemon speaks unchanged, is not declared here.
 *
 * The daemon's own verbs are declared in its contract directory (data/verbs.json, docs/contract-dir.md of omx-contract)
 * and rendered into plugin_hostd_host_verbs.h beside this header: a verb is OMX_VERB_<VERB>, its line OMX_VERB_<VERB>_FMT,
 * its reply OMX_VERB_<VERB>_REPLY and its refusals OMX_VERB_<VERB>_CODES_INIT. The tables below take the words and the
 * replies from there and add the prose of the README. */

#ifndef PLUGIN_HOSTD_PROTOCOL_H
#define PLUGIN_HOSTD_PROTOCOL_H

#include <string.h>

#include "plugin_hostd_host_verbs.h"

/* bumped when a name, a code or the shape of a verb or an event changes incompatibly */
#define PLUGIN_HOSTD_PROTOCOL_VERSION 1

/* ---------------------------------------------------------------- readiness */

/* the daemon prints this line once both its ports accept */
#define PHD_READY_LINE "plugin-hostd ready!"
/* a worker prints a line ending with this once its socket accepts */
#define PHD_WORKER_READY_MARKER "ready!"

/* ---------------------------------------------------------------- constants */

/* X(name, value, unit, meaning) */
#define PHD_DEFAULT_COMMAND_PORT 5555
#define PHD_CONNECT_RETRY_MS     5000
#define PHD_LINE_MAX             4096
#define PHD_LINE_WORDS_MAX       64
#define PHD_CHAIN_MEMBERS_MIN    1

#define PHD_CONSTANTS(X) \
    X(default_command_port, PHD_DEFAULT_COMMAND_PORT, "port", \
      "the command port without -p; the feedback port is the next one, unless -n is given") \
    X(connect_retry_ms, PHD_CONNECT_RETRY_MS, "ms", \
      "how long the idle tick asks again for a connect a respawned worker could not make yet") \
    X(line_max, PHD_LINE_MAX, "bytes", "the protocol socket's buffer: the longest pin_set line the daemon takes") \
    X(line_words_max, PHD_LINE_WORDS_MAX, "words", \
      "the words of one command line the daemon reads, the verb included; a word past them is not read") \
    X(chain_members_min, PHD_CHAIN_MEMBERS_MIN, "instances", \
      "the fewest members of a chain: a chain of one is valid, so one isolated plugin is a chain like any other")

/* ---------------------------------------------------------------- placement */

#define PHD_PLACE_OWN           "own"
#define PHD_PLACE_DEFAULT       "default"
#define PHD_PLACE_POOL_PREFIX   "pool:"
/* the place of a chain's worker in worker_list, chain:<chain>; no add names it, chain puts instances there */
#define PHD_PLACE_CHAIN_PREFIX  "chain:"
/* the place of the worker of segment k of a plan, chain:<plan>.<k>, k counting from 0 in the plan's order; only plan
 * puts instances there, and the plan's number is its own, apart from the numbers of the chains chain declares */
#define PHD_PLACE_PLAN_SEPARATOR "."
/* a full pool opens <name><separator><n>, n counting from 2 */
#define PHD_POOL_SIBLING_SEPARATOR "#"

#define PHD_POOL_NAME_MIN 1
#define PHD_POOL_NAME_MAX 32
/* the characters of a pool name: ranges written x-y, a '-' last or first is itself */
#define PHD_POOL_NAME_CLASS "A-Za-z0-9_-"

#define PHD_PLACEMENT_SYNTAX \
    PHD_PLACE_OWN " | " PHD_PLACE_POOL_PREFIX "<name> | " PHD_PLACE_DEFAULT

#define PHD_STR_(x) #x
#define PHD_STR(x)  PHD_STR_(x)
#define PHD_POOL_NAME_PATTERN \
    "^[" PHD_POOL_NAME_CLASS "]{" PHD_STR(PHD_POOL_NAME_MIN) "," PHD_STR(PHD_POOL_NAME_MAX) "}$"

/* the formats a worker holds, and the words a verb takes for "every one", "all" and "none" */
#define PHD_FORMAT_LV2  "lv2"
#define PHD_FORMAT_CLAP "clap"
/* LV2 plugins run by the CLAP worker through its LV2 adapter: a row of its own, reached by lv2_worker and never by a uri */
#define PHD_FORMAT_LV2_CLAP "lv2-clap"
#define PHD_FORMAT_ANY  "*"
#define PHD_FORMAT_ARGUMENT "<format | " PHD_FORMAT_ANY ">"
#define PHD_WORD_ALL    "all"
#define PHD_WORD_NONE   "-"
#define PHD_WORD_UNAVAILABLE "unavailable"

/* the built-in formats, X(id, name) in the order of the daemon's table (src/formats.c): the rest of what a format is
 * (its prefix, its worker, the files its pin holds, whether its pin holds in a shared world, who answers its instance
 * verbs) is a field of its row there, and a format joins with a row */
#define PHD_FORMATS(X) X(LV2, PHD_FORMAT_LV2) X(CLAP, PHD_FORMAT_CLAP) X(LV2_CLAP, PHD_FORMAT_LV2_CLAP)

/* the programs that can run an LV2 plugin, the values of the lv2_worker setting and of lv2_worker_set: X(id, name, meaning) */
#define PHD_LV2_WORKER_MOD_HOST  "mod-host"
#define PHD_LV2_WORKER_CLAP_HOST "omx-clap-host"
#define PHD_LV2_WORKER_AUTO      "auto"
#define PHD_LV2_WORKERS(X) \
    X(MOD_HOST, PHD_LV2_WORKER_MOD_HOST, "the " PHD_FORMAT_LV2 " row: mod_host runs the plugin") \
    X(CLAP_HOST, PHD_LV2_WORKER_CLAP_HOST, "the " PHD_FORMAT_LV2_CLAP " row: clap_host runs the plugin through its LV2 adapter, " \
                                           "a plugin the adapter refuses is refused with a named code, and one it does not " \
                                           "find answers the worker's -101") \
    X(AUTO, PHD_LV2_WORKER_AUTO, "the " PHD_FORMAT_LV2_CLAP " row first; a plugin its adapter refuses is run by the " \
                                 PHD_FORMAT_LV2 " row from then on, and an event says why; one it does not find is looked " \
                                 "for by the " PHD_FORMAT_LV2 " row, for that add only and with no event")

/* X(id, name, meaning) in the order of the daemon's enum */
#define PHD_WORKER_STATES(X) \
    X(UP, "up", "accepting commands") \
    X(STARTING, "starting", "spawned, not yet accepting") \
    X(BACKOFF, "backoff", "dead, waiting to be respawned") \
    X(GIVEN_UP, "given-up", "the storm bound is spent for its placement")

/* ---------------------------------------------------------------- the probe output
 *
 * What plugin-hostd-probe writes about one plugin binary and one offer: facts only, no verdict. The document's schema
 * (protocol/probe-output.schema.json) is generated from the lists below, so a code is declared here once. A code is
 * never reworded: a new one is a minor release of the format, a removed or changed one a major. */

#define PHD_PROBE_FORMAT "plugin-hostd.probe-output"
#define PHD_PROBE_FORMAT_MAJOR 1
#define PHD_PROBE_FORMAT_MINOR 1
#define PHD_PROBE_PROTOCOL_NAME "plugin-hostd.probe-protocol"
#define PHD_PROBE_PROTOCOL_VERSION 1
/* version 1 of the probe protocol runs an LV2 plugin as plugin-qualify's LV2 hosting pass does today
 * (LV2_HOSTING_LIFECYCLES, LV2_HOSTING_REPEATS), so the verdicts from its documents equal today's: this many
 * instantiate/destroy cycles and swept rt-safety runs, at the highest rate asked for */
#define PHD_PROBE_LV2_LIFECYCLES 30
#define PHD_PROBE_LV2_REPEATS 3

/* how a step, a grid point or the whole run ended: X(id, code, meaning) */
#define PHD_PROBE_OUTCOMES(X) \
    X(OK, "probe.ok", "the step ran to its end") \
    X(CRASHED, "probe.crashed", "the child died of a signal not caused by a limit") \
    X(TIMEOUT, "probe.timeout", "the supervisor's wall-clock deadline passed") \
    X(CPU_LIMIT, "probe.cpu-limit", "the CPU-time limit was hit") \
    X(MEMORY_LIMIT, "probe.memory-limit", "the memory limit was hit, known from the cgroup's oom_kill count") \
    X(TASKS_LIMIT, "probe.tasks-limit", "the plugin tried to start more tasks than allowed, known from the cgroup's pids.events") \
    X(OUTPUT_LIMIT, "probe.output-limit", "the plugin wrote a file past the size limit") \
    X(SANDBOX_DENIED, "probe.sandbox-denied", "a syscall on the kill list was made") \
    X(REFUSED_INSTANTIATION, "probe.refused-instantiation", "create, init or instantiate returned failure") \
    X(REFUSED_BY_HOST, "probe.refused-by-host", "the host or its LV2 adapter refused the plugin; hostingCode holds its code unchanged") \
    X(NOT_FOUND, "probe.not-found", "no such plugin in the files named") \
    X(UNPINNABLE, "probe.unpinnable", "the files cannot be pinned") \
    X(NON_FINITE_OUTPUT, "probe.non-finite-output", "NaN or infinity came out") \
    X(SILENT_OUTPUT, "probe.silent-output", "silence under a stimulus that should pass") \
    X(CANCELLED, "probe.cancelled", "stopped by the busy signal, a client or shutdown") \
    X(NOT_ATTEMPTED, "probe.not-attempted", "the protocol did not ask for this step, or it does not apply") \
    X(CHILD_PROTOCOL, "probe.child-protocol", "the child wrote a record outside the step grammar") \
    X(ERROR, "probe.error", "anything else; detail keeps the words")

/* why a run was made, the document's run.reason: X(id, name, meaning) */
#define PHD_PROBE_REASONS(X) \
    X(ADD, "add", "a user added the plugin") \
    X(RESCAN, "rescan", "the plugin was offered for a rescan") \
    X(BINARY_CHANGED, "binary-changed", "the files the host loads changed") \
    X(ON_REQUEST, "on-request", "a client asked") \
    X(AUTO_MEASURE, "auto-measure", "the machine measures what has no figures when it is idle") \
    X(REFERENCE, "reference", "a reference run on the named rig") \
    X(CI, "ci", "a continuous integration run")

/* the limits a set can ask for: X(id, name, meaning) */
#define PHD_PROBE_LIMIT_NAMES(X) \
    X(WALL_CLOCK, "wall-clock", "the supervisor's deadline; the whole process tree is killed at it") \
    X(CPU_TIME, "cpu-time", "RLIMIT_CPU") \
    X(MEMORY, "memory", "cgroup memory.max, else RLIMIT_DATA") \
    X(TASKS, "tasks", "cgroup pids.max") \
    X(FILES, "files", "RLIMIT_NOFILE") \
    X(FILE_SIZE, "file-size", "RLIMIT_FSIZE") \
    X(CORE_DUMP, "core-dump", "RLIMIT_CORE 0") \
    X(RT_PRIORITY, "rt-priority", "RLIMIT_RTPRIO 0") \
    X(RT_TIME, "rt-time", "RLIMIT_RTTIME") \
    X(CPUS, "cpus", "sched_setaffinity") \
    X(NICE, "nice", "the child's nice value") \
    X(NO_NEW_PRIVS, "no-new-privs", "PR_SET_NO_NEW_PRIVS") \
    X(NETWORK, "network", "an unprivileged user and network namespace") \
    X(FILESYSTEM, "filesystem", "Landlock") \
    X(SYSCALLS, "syscalls", "a seccomp kill list")

/* what enforced a limit: X(id, name, meaning) */
#define PHD_PROBE_LIMIT_MECHANISMS(X) \
    X(SUPERVISOR, "supervisor", "the runner's own timer and tree kill") \
    X(RLIMIT, "rlimit", "setrlimit") \
    X(CGROUP, "cgroup", "a cgroup v2 controller") \
    X(AFFINITY, "affinity", "sched_setaffinity") \
    X(PRCTL, "prctl", "prctl") \
    X(NETNS, "netns", "a network namespace") \
    X(USERNS, "userns", "a user namespace") \
    X(LANDLOCK, "landlock", "Landlock") \
    X(SECCOMP, "seccomp", "seccomp-bpf")

/* a limit the set asked for and this machine could not apply: X(id, code, meaning) */
#define PHD_PROBE_LIMIT_CODES(X) \
    X(CGROUP_ABSENT, "probe.limit.cgroup-absent", "no cgroup v2 hierarchy to use") \
    X(CONTROLLER_NOT_DELEGATED, "probe.limit.controller-not-delegated", "the controller is not delegated to this user") \
    X(USERNS_DENIED, "probe.limit.userns-denied", "unprivileged user namespaces are refused") \
    X(LANDLOCK_ABSENT, "probe.limit.landlock-absent", "the kernel offers no Landlock") \
    X(SECCOMP_ABSENT, "probe.limit.seccomp-absent", "the kernel offers no seccomp filter") \
    X(NOT_IMPLEMENTED, "probe.limit.not-implemented", "the runner of this version does not apply the limit")

/* the machine profile read back and not meeting the protocol: X(id, code, meaning) */
#define PHD_PROBE_PROFILE_CODES(X) \
    X(GOVERNOR, "probe.profile.governor", "the cpu governor is not the one the protocol names") \
    X(DEEP_IDLE_ENTERED, "probe.profile.deep-idle-entered", "a deep idle state was entered during the run") \
    X(TURBO_UNKNOWN, "probe.profile.turbo-unknown", "whether turbo is on could not be read") \
    X(SMT_ON, "probe.profile.smt-on", "SMT siblings are on") \
    X(NOT_PINNED, "probe.profile.not-pinned", "the child was not pinned to cpus")

/* the steps of the protocol, in the order they are run: X(id, name, meaning) */
#define PHD_PROBE_STEPS(X) \
    X(HASH, "hash", "the files the host loads, pinned") \
    X(SCAN, "scan", "the plugin's descriptor read") \
    X(INSTANTIATE, "instantiate", "created and initialised") \
    X(LIFECYCLE, "lifecycle", "created, activated, processed and destroyed") \
    X(LATENCY, "latency", "latency per rate") \
    X(COST, "cost", "cost per rate and quantum") \
    X(RT_SAFETY, "rt-safety", "what process() does under the interposer") \
    X(NOTE_SWEEP, "note-sweep", "a note input played") \
    X(SOAK, "soak", "a long render")

/* whether name is a pool name, by PHD_POOL_NAME_CLASS and the limits above */
static inline int phd_pool_name_valid(const char *name)
{
    int n = 0;

    for (; name[n]; n++)
    {
        const char *c = PHD_POOL_NAME_CLASS;
        int ok = 0;

        for (; *c; c++)
        {
            if (c[1] == '-' && c[2])
            {
                if (name[n] >= c[0] && name[n] <= c[2])
                    ok = 1;
                c += 2;
            }
            else if (name[n] == *c)
                ok = 1;
        }
        if (!ok)
            return 0;
    }
    return n >= PHD_POOL_NAME_MIN && n <= PHD_POOL_NAME_MAX;
}

/* ---------------------------------------------------------------- error codes */

/* the codes the supervisor adds to mod-host's, the -5xx hundred; a reply is "resp <code>". Each number has one name in
 * the contract: the ones omx-clap-host answers too are omx-clap-core's reply.host.* codes (its HOST_REPLY_CODES), the
 * others plugin-hostd's reply.plugin-hostd.* (data/verbs.json PLUGIN_HOSTD_REPLY_CODES); tests/verbs_declared.py
 * holds every number below to exactly one of them */
#define PHD_ERR_PLACEMENT_INVALID (-501)
#define PHD_ERR_NO_BACKEND        (-502)
#define PHD_ERR_WORKER_SPAWN      (-503)
#define PHD_ERR_REPLAY            (-504)
#define PHD_ERR_GAVE_UP           (-505)
#define PHD_ERR_NO_SUCH_WORKER    (-506)
#define PHD_ERR_VERB_DROPPED      (-507)
#define PHD_ERR_PIN_ABSENT          (-508)
#define PHD_ERR_PIN_BINARY_MISMATCH (-509)
#define PHD_ERR_PIN_LAYOUT_MISMATCH (-510)
#define PHD_ERR_NO_PARAM_CONTRACT   (-511)
#define PHD_ERR_LV2_ADAPTER_REFUSED (-512)
#define PHD_ERR_NO_NOTE_INPUT       (-513)
#define PHD_ERR_NOTES_BY_JACK       (-514)
#define PHD_ERR_NO_PRESET_LIST      (-515)
#define PHD_ERR_PIN_REFUSED         (-516)
#define PHD_ERR_NOTE_QUEUE_FULL     (-517)
#define PHD_ERR_CHAIN_UNKNOWN_INSTANCE (-518)
#define PHD_ERR_CHAIN_DUPLICATE     (-519)
#define PHD_ERR_CHAIN_INSTANCE_BUSY (-520)
#define PHD_ERR_CHAIN_MIXED_FORMAT  (-521)
#define PHD_ERR_NO_SUCH_CHAIN       (-522)
#define PHD_ERR_PRESET_NOT_OFFERED  (-523)
#define PHD_ERR_PRESET_INVALID      (-524)
#define PHD_ERR_PRESET_NEEDS_STATE  (-525)
#define PHD_ERR_PRESET_PLUGIN_CHANGED (-526)
#define PHD_ERR_LOAD_REFUSED        (-527)
#define PHD_ERR_DIR_NOT_WRITABLE    (-528)
#define PHD_ERR_DESCRIPTOR_ABSENT   (-529)
#define PHD_ERR_DESCRIPTOR_PENDING  (-530)
#define PHD_ERR_DESCRIPTOR_SCAN_FAILED (-531)
#define PHD_ERR_NO_SUCH_PLAN        (-532)

/* X(id, meaning) */
#define PHD_ERRORS(X) \
    X(PLACEMENT_INVALID, "placement invalid: not a placement, or not valid here, as a " PHD_PLACE_POOL_PREFIX \
                         "<name> for a plugin of a format whose pin holds only in a world of the plugin's own, while require_pins is on") \
    X(NO_BACKEND, "no worker program for the scheme") \
    X(WORKER_SPAWN, "the worker is not up: the spawn failed, or it is in backoff; ask again after instance_restored") \
    X(REPLAY, "the name of a refused replay, never a reply: a replayed add that its pin or the worker refuses is " \
              "announced by the instance_replay_refused event with the refusal's own code, and written to stderr " \
              "with this one and the step that refused it") \
    X(GAVE_UP, "the storm bound is spent for that placement") \
    X(NO_SUCH_WORKER, "no such worker") \
    X(VERB_DROPPED, "the worker died on this very command and the daemon dropped it: it is not replayed, " \
                    "and the instance_verb_dropped event names it; or it died on, or did not answer in rpc_timeout_ms, " \
                    "the " PHD_VERB_PIN_EXPECT " of an add, which is then never forwarded") \
    X(PIN_ABSENT, "pin_mode strict and the plugin has no pin, or its layout pin is in a scheme this version does " \
                  "not know: add is refused and no worker sees it") \
    X(PIN_BINARY_MISMATCH, "a pinned file is missing or its SHA-256 differs, or the plugin's manifest names a file the " \
                           "pin does not hold: add is refused and no worker sees it") \
    X(PIN_LAYOUT_MISMATCH, "the worker found the parameter layout after init differs from the layout pin: the " \
                           "instance is destroyed before activate") \
    X(NO_PARAM_CONTRACT, "the host holds no checked unit and scale for this parameter: fall back to qualification") \
    X(LV2_ADAPTER_REFUSED, "the " PHD_FORMAT_LV2_CLAP " worker's LV2 adapter cannot run this plugin (MIDI it does not feed, a " \
                           "required feature it lacks, a layout it does not take): the worker answered the add -102, the " \
                           PHD_EVENT_LV2_ADAPTER_REFUSED " event carries the hosting.* code of that reply, and under lv2_worker " \
                           PHD_LV2_WORKER_AUTO " the plugin is run by the " PHD_FORMAT_LV2 " row instead and this code is never " \
                           "answered; a plugin no bundle of the worker's world holds is no refusal: the worker's -101 is answered") \
    X(NO_NOTE_INPUT, "the instance's plugin takes no notes (an effect): its worker answers " PHD_VERB_NOTE_ON ", " \
                     PHD_VERB_NOTE_OFF " and " PHD_VERB_ALL_NOTES_OFF " with this code") \
    X(NOTES_BY_JACK, "the instance's worker takes no notes on its socket (mod-host): the daemon answers the note verbs " \
                     "and " PHD_VERB_NOTE_INPUT " with this code, and the plugin is played through its jack MIDI input " \
                     "with connect") \
    X(NO_PRESET_LIST, "the instance's worker cannot list the plugin's presets (mod-host): the daemon answers " \
                      OMX_VERB_PRESET_LIST " and " OMX_VERB_PRESET_GET " with this code; preset_load still takes a preset " \
                      "the controller knows") \
    X(PIN_REFUSED, "the plugin's pin carries " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED ": its files are the ones that " \
                   "failed qualification, so add is refused and no worker sees it, and a replayed add is refused the " \
                   "same way; files that differ from the pin answer " PHD_STR(PHD_ERR_PIN_BINARY_MISMATCH) " first. A pins_dir " \
                   "pin of that verdict is never overridden: " OMX_VERB_PIN_SET " and " OMX_VERB_PIN_ACCEPT " of its plugin " \
                   "answer this code") \
    X(NOTE_QUEUE_FULL, "the instance's worker has no room for this " PHD_VERB_NOTE_ON ", " PHD_VERB_NOTE_OFF " or " \
                       PHD_VERB_ALL_NOTES_OFF " before its next block: the line was not taken and nothing of it is kept; the " \
                       "controller may send it again") \
    X(CHAIN_UNKNOWN_INSTANCE, "a member of " OMX_VERB_CHAIN " is an instance no add made: the chain is not declared") \
    X(CHAIN_DUPLICATE, "an instance is named twice in one " OMX_VERB_CHAIN ": the chain is not declared") \
    X(CHAIN_INSTANCE_BUSY, "a member of " OMX_VERB_CHAIN " is already in another chain: the chain is not declared; " \
                           OMX_VERB_CHAIN_CLEAR " of the other chain frees it") \
    X(CHAIN_MIXED_FORMAT, "the members of " OMX_VERB_CHAIN " are not all run by one worker program, or are of two " \
                          "rows of one program and a row does not run chains in one client, so no one worker runs " \
                          "them: the chain is not declared") \
    X(NO_SUCH_CHAIN, OMX_VERB_CHAIN_CLEAR " or " OMX_VERB_CHAIN_GET " of a chain no " OMX_VERB_CHAIN " declared") \
    X(PRESET_NOT_OFFERED, "the worker: preset_load or preset_show of a stable name the plugin does not offer, or of a " \
                          "plugin with no preset system and no state") \
    X(PRESET_INVALID, "preset_save with a file path that is not absolute or with no name, or preset_load or " \
                      "preset_show of a file that cannot be read, is no JSON, is of a format version other than " \
                      PHD_PRESET_FORMAT_1 " and " PHD_PRESET_FORMAT_2 ", or breaks the format (docs/presets.md): the " \
                      "daemon answers it and no worker sees the file") \
    X(PRESET_NEEDS_STATE, "the worker: a preset file that carries state for a worker that cannot take state yet") \
    X(PRESET_PLUGIN_CHANGED, "the worker: the preset file's plugin id, version or fingerprint is not the instance's; " \
                             "nothing of it is applied") \
    X(LOAD_REFUSED, "the worker: the plugin refused the preset or the state its file carries") \
    X(DIR_NOT_WRITABLE, "descriptor_dir or qualification_dir cannot be made or written: the daemon does not start, and " \
                        "says which key and which path on stderr with this code; a directory that turns read-only " \
                        "later makes the scan of an add write nothing, and " OMX_VERB_DESCRIPTOR_GET " and " \
                        OMX_VERB_PANEL_GET " of that plugin answer this code") \
    X(DESCRIPTOR_ABSENT, OMX_VERB_DESCRIPTOR_GET " (" OMX_VERB_PANEL_GET ") of a plugin that has no descriptor (panel) " \
                         "in descriptor_dir for its binary as it is now, and none being written: no add since it " \
                         "changed, or a binary that cannot be found") \
    X(DESCRIPTOR_PENDING, OMX_VERB_DESCRIPTOR_GET " (" OMX_VERB_PANEL_GET ") of a plugin whose scan, started by its " \
                          "add, has not written its descriptor (panel) yet: ask again") \
    X(DESCRIPTOR_SCAN_FAILED, OMX_VERB_DESCRIPTOR_GET " (" OMX_VERB_PANEL_GET ") of a plugin whose last scan wrote no " \
                              "descriptor (panel): the scanner refused the plugin, made no dump or no panel, or is not " \
                              "installed; the add it ran for stands, and stderr and the scan's log say why. The next add " \
                              "scans again") \
    X(NO_SUCH_PLAN, OMX_VERB_PLAN_GET " or " OMX_VERB_PLAN_CLEAR " of a chain no " OMX_VERB_PLAN " planned")

/* ---------------------------------------------------------------- verbs */

/* mod-host's add, which the daemon extends with a placement; every verb of its own is OMX_VERB_<VERB> of
 * plugin_hostd_host_verbs.h */
#define PHD_VERB_ADD              "add"
#define PHD_VERB_PIN_EXPECT       "pin_expect"

/* the words of a pin: <path>=<sha256>, joined by ',', and <scheme>:<sha256> */
#define PHD_PIN_FILE_SEPARATOR   ","
#define PHD_PIN_DIGEST_SEPARATOR "="
#define PHD_PIN_SCHEME_SEPARATOR ":"
/* what a path of a pin cannot hold: the separators of pin_set's words, and whitespace */
#define PHD_PIN_PATH_EXCLUDED    PHD_PIN_FILE_SEPARATOR PHD_PIN_DIGEST_SEPARATOR " \t\r\n"
/* the layout word of a pin whose layout has not been learned yet: a pin of the store, of a pins file or learned by the
 * daemon may hold it, pin_set may not */
#define PHD_PIN_LAYOUT_UNKNOWN   "-"
/* the optional last word of a pin line: the qualification verdict of the pinned bytes */
#define PHD_PIN_VERDICT_KEY      "verdict="

/* the verdicts: X(id, name, meaning); only in-process lets a plugin share a worker under pin_mode first-use */
#define PHD_PIN_VERDICT_IN_PROCESS "in-process"
#define PHD_PIN_VERDICT_ISOLATED   "isolated"
#define PHD_PIN_VERDICT_REFUSED    "refused"
#define PHD_PIN_VERDICTS(X) \
    X(IN_PROCESS, PHD_PIN_VERDICT_IN_PROCESS, "qualified to run in a worker that other plugins share") \
    X(ISOLATED, PHD_PIN_VERDICT_ISOLATED, "qualified to run, in a worker of its own") \
    X(REFUSED, PHD_PIN_VERDICT_REFUSED, "failed qualification: the pin records the bytes, a host should not load them")

/* what pin_changed names as changed */
#define PHD_PIN_CHANGED_FILES  "files"
#define PHD_PIN_CHANGED_LAYOUT "layout"

/* the pin modes: X(id, name, meaning), read while require_pins is 1 */
#define PHD_PIN_MODE_STRICT    "strict"
#define PHD_PIN_MODE_FIRST_USE "first-use"
#define PHD_PIN_MODES(X) \
    X(STRICT, PHD_PIN_MODE_STRICT, "add admits only a plugin that has a pin; a pin comes from pin_set, pin_file or pins_dir") \
    X(FIRST_USE, PHD_PIN_MODE_FIRST_USE, "add of a plugin with no pin records its pin, keeps it in the pin store and places " \
                              "the instance " PHD_PLACE_OWN "; a later change is refused until pin_accept")

/* the grouping modes: X(id, name, meaning) */
#define PHD_GROUPING_OFF "off"
#define PHD_GROUPING_ON  "on"
#define PHD_GROUPING_MODES(X) \
    X(OFF, PHD_GROUPING_OFF, OMX_VERB_PLAN " answers the plan it would make and applies none") \
    X(ON, PHD_GROUPING_ON, OMX_VERB_PLAN " applies its plan")

/* a manifest's IRI that holds this is percent-encoded */
#define PHD_PIN_PERCENT          "%"

/* what cannot be pinned, each a refusal and never a partial pin: X(id, meaning) */
#define PHD_PIN_LIMITS(X) \
    X(PATH, "a path holding '" PHD_PIN_FILE_SEPARATOR "', '" PHD_PIN_DIGEST_SEPARATOR "' or whitespace cannot be pinned: " \
            "they are the separators of " OMX_VERB_PIN_SET "'s words, and " OMX_VERB_PIN_SET " refuses it as a token " \
            "outside its grammar") \
    X(LINE, "a " OMX_VERB_PIN_SET " line is at most line_max, " PHD_STR(PHD_LINE_MAX) " bytes, the protocol socket's " \
            "buffer; a longer one is refused as outside the grammar") \
    X(MANIFEST, "a manifest that uses @base, or names a file of the plugin by a percent-encoded IRI, makes add answer " \
                "PHD_ERR_PIN_BINARY_MISMATCH " PHD_STR(PHD_ERR_PIN_BINARY_MISMATCH) ": the daemon does not resolve " \
                "either, so it cannot know the file the host would load")

/* the verbs the daemon adds to mod-host's, or extends: X(id, name, arguments, reply, meaning) */
#define PHD_VERBS(X) \
    X(ADD, PHD_VERB_ADD, "<uri> <instance> [" PHD_PLACEMENT_SYNTAX "] [client_name]", "resp <instance>", \
      "mod-host's add with a placement; a token after the instance that is not a placement is the jack client name") \
    X(WORKER_LIST, OMX_VERB_WORKER_LIST, "", OMX_VERB_WORKER_LIST_REPLY, "the workers, one record each") \
    X(INSTANCE_INFO, OMX_VERB_INSTANCE_INFO, "<instance>", OMX_VERB_INSTANCE_INFO_REPLY, \
      "where an instance lives and what it has cost") \
    X(SUPERVISOR_RESET, OMX_VERB_SUPERVISOR_RESET, "[<worker> | " PHD_WORD_ALL "]", OMX_VERB_SUPERVISOR_RESET_REPLY, \
      "re-arm the storm bound and the backoff of a given-up placement") \
    X(QUARANTINE_CLEAR, OMX_VERB_QUARANTINE_CLEAR, "<instance> | " PHD_WORD_ALL, OMX_VERB_QUARANTINE_CLEAR_REPLY, \
      "let a quarantined instance go back where its placement says") \
    X(POLICY_SET, OMX_VERB_POLICY_SET, PHD_FORMAT_ARGUMENT " " \
      PHD_PLACE_OWN " | " PHD_PLACE_POOL_PREFIX "<name>", OMX_VERB_POLICY_SET_REPLY, "the placement of an add that says default") \
    X(POOL_CONFIG, OMX_VERB_POOL_CONFIG, "<name> <max_instances>", OMX_VERB_POOL_CONFIG_REPLY, \
      "the instances a pool holds before a sibling opens") \
    X(WORKER_ENV, OMX_VERB_WORKER_ENV, PHD_FORMAT_ARGUMENT " <cpu-list|" \
      PHD_WORD_NONE "> <nice|" PHD_WORD_NONE ">", OMX_VERB_WORKER_ENV_REPLY, \
      "the cpu list and the nice value of the workers of a format, at spawn and on the ones running") \
    X(PIN_SET, OMX_VERB_PIN_SET, "<uri> <path>" PHD_PIN_DIGEST_SEPARATOR "<sha256>[" PHD_PIN_FILE_SEPARATOR "<path>" \
      PHD_PIN_DIGEST_SEPARATOR "<sha256>...] <scheme>" PHD_PIN_SCHEME_SEPARATOR "<sha256> [" PHD_PIN_VERDICT_KEY \
      "<verdict>]", OMX_VERB_PIN_SET_REPLY, \
      "the pin of one plugin: the SHA-256 of every file the host loads for it, a path relative to the bundle (the " \
      "directory of a single-file format's file), its layout fingerprint and, when it is known, the verdict of its qualification; " \
      "it replaces an earlier pin of the uri; -516 for a plugin whose pins_dir pin carries " PHD_PIN_VERDICT_KEY \
      PHD_PIN_VERDICT_REFUSED ", which nothing overrides. The pin store, a pin_file and a pins_dir file hold the same " \
      "line, with or without the verb") \
    X(PIN_CLEAR, OMX_VERB_PIN_CLEAR, "<uri> | " PHD_WORD_ALL, OMX_VERB_PIN_CLEAR_REPLY, "forget the pin of one plugin, or of every one; a pins_dir " \
      "pin is read-only and holds again") \
    X(LV2_WORKER_SET, OMX_VERB_LV2_WORKER_SET, "<uri> <" PHD_LV2_WORKER_MOD_HOST " | " PHD_LV2_WORKER_CLAP_HOST " | " \
      PHD_LV2_WORKER_AUTO " | " PHD_WORD_NONE ">", OMX_VERB_LV2_WORKER_SET_REPLY, \
      "the worker of one LV2 plugin, for its adds from now on: it overrides the lv2_worker setting, " PHD_WORD_NONE " takes the " \
      "override back; -902 for a word that is none of these. Like policy_set it is the controller's, not in the ledger, gone with the daemon") \
    X(PIN_ACCEPT, OMX_VERB_PIN_ACCEPT, "<uri>", OMX_VERB_PIN_ACCEPT_REPLY, \
      "pin_mode " PHD_PIN_MODE_FIRST_USE " only: take the plugin's files as they are now as its pin, after a " \
      PHD_EVENT_PIN_CHANGED " event; the layout is learned again by the next add and the verdict is dropped; -508 when " \
      "the plugin has no pin, -509 when its files cannot be collected, -516 when its pins_dir pin carries " \
      PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED ", -902 under pin_mode strict") \
    X(PIN_LAYOUT, OMX_VERB_PIN_LAYOUT, "<instance>", OMX_VERB_PIN_LAYOUT_REPLY, \
      "sent by the daemon to a worker of a format that checks layouts, after it accepted the add of a plugin whose layout pin is " \
      "still unknown: the layout the worker found after init, which the daemon records in the pin") \
    X(PIN_EXPECT, PHD_VERB_PIN_EXPECT, "<instance> <scheme>" PHD_PIN_SCHEME_SEPARATOR "<sha256>", "resp 0", \
      "sent by the daemon to a worker of a format that checks layouts, just before the instance's add: the layout pin that add " \
      "checks after init and before activate; any other reply than resp 0 refuses the add with that code, and the " \
      "add is never forwarded") \
    X(CHAIN, OMX_VERB_CHAIN, "<chain> <instance> [<instance> ...]", OMX_VERB_CHAIN_REPLY, \
      "the instances, in this order, are one chain, run in one worker of place " PHD_PLACE_CHAIN_PREFIX "<chain>: each " \
      "member's state is saved, it is removed from the worker it was in and replayed in the chain's. A chain already " \
      "declared takes the new order, and a member left out of it goes back to a worker of its own; while its worker " \
      "is up that worker is kept: a new member joins it (its add, the order, its state, its ledger, its connections) " \
      "and no other member is restarted, unless the new member's format narrows the worker's world, which forms " \
      "the chain again. Members of " PHD_FORMAT_CLAP " and " PHD_FORMAT_LV2_CLAP " form one chain. A worker that runs " \
      "chains in one client (" PHD_FORMAT_CLAP ", " PHD_FORMAT_LV2_CLAP ") is sent this line, with the members it holds, " \
      "after the adds of its replay; one that does not (mod-host) never is, and a refusal of it is written to stderr " \
      "and is no failure. Every instance verb still names one member by its own number. A member that crashes the " \
      "worker is quarantined to a worker of its own and the chain goes on without it; quarantine_clear puts it back. " \
      "-518 for an instance no add made, -519 for one named twice, -520 for one in another chain, -521 for members no " \
      "one worker program runs together, -501 for a plugin that may not share a worker while require_pins is on (a CLAP plugin " \
      "whose first-use pin is not in-process; an LV2 member whose bundle is not found, since a chain's worker sees " \
      "a world narrowed to the union of its members' bundles), -902 for a chain " \
      "or an instance that is not a number, or fewer than chain_members_min (" PHD_STR(PHD_CHAIN_MEMBERS_MIN) ") instances") \
    X(CHAIN_CLEAR, OMX_VERB_CHAIN_CLEAR, "<chain>", OMX_VERB_CHAIN_CLEAR_REPLY, \
      "forget the chain: each member goes to a worker of its own; -522 for a chain no " OMX_VERB_CHAIN " declared") \
    X(CHAIN_GET, OMX_VERB_CHAIN_GET, "<chain>", OMX_VERB_CHAIN_GET_REPLY, \
      "read a chain back: its worker (" PHD_WORD_NONE " when it has none), its members in the declared order, and the " \
      "members its worker runs now in their order (" PHD_WORD_NONE " for none); a quarantined member is declared and " \
      "not running; -522 for a chain no " OMX_VERB_CHAIN " declared, -902 for a chain that is not a number") \
    X(PLAN, OMX_VERB_PLAN, "<chain> <instance> [<instance> ...]", OMX_VERB_PLAN_REPLY, \
      "the instances, in signal order, are planned (the grouping-planner design note): the daemon decides, from the " \
      "pin and the cost of each, which runs of consecutive members share a worker. A run of two or more is declared " \
      "as a chain of place " PHD_PLACE_CHAIN_PREFIX "<chain>" PHD_PLACE_PLAN_SEPARATOR "<k>, k counting segments from 0; " \
      "a member that shares with no neighbour is placed " PHD_PLACE_OWN ". The reply names the segments in order, " \
      "the members of one joined by commas and the segments by semicolons. A chain planned again keeps the running " \
      "worker of every segment that did not change, and the daemon plans it again by itself when a member is " \
      "quarantined and, history_regroup_s after a death that split its group, to gather it. The plan numbers are its " \
      "own, apart from chain's. While the setting grouping is off the plan is answered and kept for " OMX_VERB_PLAN_GET " and nothing moves. A segment " \
      "that cannot be formed refuses the whole plan with its own code, moves nothing and is told by " OMX_VERB_PLAN_GET \
      " as plan-refused:<code>. -518 for an instance no add made, -519 for one named twice, -520 for one in a chain " \
      "or in the plan of another chain, -501 for a segment no world can be built for, -902 for a chain or an " \
      "instance that is not a number, or fewer than chain_members_min (" PHD_STR(PHD_CHAIN_MEMBERS_MIN) ") instances") \
    X(PLAN_GET, OMX_VERB_PLAN_GET, "<chain>", OMX_VERB_PLAN_GET_REPLY, \
      "read the last plan of a chain back: its segments as " OMX_VERB_PLAN " answered them, then the members that have " \
      "a reason, instance:reason joined by commas (" PHD_WORD_NONE " for none); the reasons are the words of " \
      "PLUGIN_HOSTD_GROUPING_REASONS (data/grouping.json); -532 for a chain no " OMX_VERB_PLAN " planned, -902 for " \
      "a chain that is not a number") \
    X(PLAN_CLEAR, OMX_VERB_PLAN_CLEAR, "<chain>", OMX_VERB_PLAN_CLEAR_REPLY, \
      "forget the plan: each member goes to a worker of its own; -532 for a chain no " OMX_VERB_PLAN " planned") \
    X(DESCRIPTOR_GET, OMX_VERB_DESCRIPTOR_GET, "<uri>", OMX_VERB_DESCRIPTOR_GET_REPLY, \
      "the scanned descriptor of the plugin, answered from descriptor_dir: the file named for its binary as it is now " \
      "(" PHD_DESCRIPTOR_NAME_SYNTAX "), written by the scan the plugin's add ran. -529 when there is none, -530 while " \
      "its scan runs, -531 when its last scan wrote nothing, -528 when the directory could not be written") \
    X(PANEL_GET, OMX_VERB_PANEL_GET, "<uri>", OMX_VERB_PANEL_GET_REPLY, \
      "the panel the plugin publishes (org.openmixer.panel-description/1), answered from descriptor_dir: the file " \
      PHD_PANEL_NAME_SYNTAX ", named as its descriptor, which the same scan writes once the descriptor is in place, " \
      "{\"plugin\": {\"format\", \"id\"}, \"panel\": <the panel object omx-clap-scan --json prints for the plugin, " \
      "null when it serves none>}; an LV2 plugin's panel is null. The codes are " OMX_VERB_DESCRIPTOR_GET "'s: -529 " \
      "when there is none, -530 while its scan runs, -531 when its last scan wrote nothing, -528 when the directory " \
      "could not be written") \
    X(HISTORY_GET, OMX_VERB_HISTORY_GET, "<uri>", OMX_VERB_HISTORY_GET_REPLY, \
      "what the daemon kept of the plugin on this host class, for the binary its pin holds now (the running history: " \
      "the windows it ran alone and in a group, its crashes, restarts and quarantines): one word of comma-joined " \
      "digest=<sha256>, class=<host class>, crashed=<0|1>, raises_xruns=<0|1> and then every key=value of the record " \
      "(data/history.json); " PHD_WORD_NONE " when the plugin has no pin or no record, " PHD_WORD_UNAVAILABLE " while the " \
      "history file is blocked or history_window_s is 0, -902 for a line that is not one word") \
    X(HISTORY_CLEAR, OMX_VERB_HISTORY_CLEAR, "<uri> | " PHD_WORD_ALL, OMX_VERB_HISTORY_CLEAR_REPLY, \
      "delete the history of one plugin (every binary and host class of it), or all of it, from memory and from the " \
      "file at once; -902 while the history is blocked or off, or for a line that is not one word")

/* ---------------------------------------------------------------- instance verbs */

/* What a host knows of a strip and of a plugin's controls, asked by instance. The daemon routes them to a
 * worker of a format whose workers answer them from the plugin; for a format whose worker does not, it answers them
 * itself and never forwards them. A string word is quoted when it is not a plain word, and always in a reply, with \" inside it
 * for a quote: mod-host's own tokenizer reads them. */
#define PHD_VERB_TRACK_INFO      "track_info"
#define PHD_VERB_REMOTE_PAGES    "remote_pages"
#define PHD_VERB_REMOTE_PAGE_GET "remote_page_get"
#define PHD_VERB_PARAM_INFO      "param_info"

/* the same verbs as a host registers them with protocol_add_command; preset_list and preset_get are the daemon's,
 * OMX_VERB_PRESET_LIST and OMX_VERB_PRESET_GET */
#define PHD_VERB_TRACK_INFO_FMT      PHD_VERB_TRACK_INFO " %i %s %s ..."
#define PHD_VERB_REMOTE_PAGES_FMT    PHD_VERB_REMOTE_PAGES " %i"
#define PHD_VERB_REMOTE_PAGE_GET_FMT PHD_VERB_REMOTE_PAGE_GET " %i %i"
#define PHD_VERB_PARAM_INFO_FMT      PHD_VERB_PARAM_INFO " %i %s"

/* Notes, played on an instance by a controller that is not a jack client: the worker delivers each one as a MIDI
 * message at the start of its next cycle, on the plugin's note input. Nothing of them is kept: a note is an act, not a
 * setting, and a respawned instance starts silent. */
#define PHD_VERB_NOTE_INPUT     "note_input"
#define PHD_VERB_NOTE_ON        "note_on"
#define PHD_VERB_NOTE_OFF       "note_off"
#define PHD_VERB_ALL_NOTES_OFF  "all_notes_off"

#define PHD_VERB_NOTE_INPUT_FMT    PHD_VERB_NOTE_INPUT " %i"
#define PHD_VERB_NOTE_ON_FMT       PHD_VERB_NOTE_ON " %i %i %i %i"
#define PHD_VERB_NOTE_OFF_FMT      PHD_VERB_NOTE_OFF " %i %i %i %i"
#define PHD_VERB_ALL_NOTES_OFF_FMT PHD_VERB_ALL_NOTES_OFF " %i"

/* the ranges of a note's words: MIDI's */
#define PHD_NOTE_CHANNEL_MAX  15
#define PHD_NOTE_KEY_MAX      127
#define PHD_NOTE_VELOCITY_MAX 127
/* the word note_input answers for a plugin that takes no notes */
#define PHD_NO_NOTE_INPUT     PHD_WORD_NONE

/* the longest string word, in bytes: CLAP_NAME_SIZE - 1 */
#define PHD_STRING_MAX 255

/* the user-preset file a worker writes for preset_save and reads for preset_load and preset_show (docs/presets.md,
 * protocol/preset.schema.json): /1 is params-only, /2 adds the state body */
#define PHD_PRESET_FORMAT_1   "org.openmixer.preset/1"
#define PHD_PRESET_FORMAT_2   "org.openmixer.preset/2"
#define PHD_PRESET_ALIAS_MAX  12
#define PHD_PRESET_FILE_MAX   (64 * 1024 * 1024)
/* the parameters on one remote page, and the word of an empty slot */
#define PHD_REMOTE_PAGE_SLOTS 8
#define PHD_EMPTY_SLOT        PHD_WORD_NONE
/* the colour of a strip that has none */
#define PHD_NO_COLOR          PHD_WORD_NONE

/* the kind of strip, the fourth word of track_info; none for an input channel: X(id, name) */
#define PHD_TRACK_KINDS(X) X(BUS, "bus") X(RETURN, "return") X(MASTER, "master")

/* how a parameter's plain value maps to a control's travel: X(id, name, meaning) */
#define PHD_PARAM_SCALES(X) \
    X(LINEAR, "linear", "the value is linear in position") \
    X(LOG, "log", "the value is geometric in position; both bounds are positive") \
    X(STEPPED, "stepped", "the whole numbers from min to max, step 1")

/* what the ledger keeps of a verb: nothing, or the latest one per instance, replayed after the add */
#define PHD_LEDGER_NONE    0
#define PHD_LEDGER_REPLACE 1

/* X(id, name, arguments, reply, ledger, meaning) */
#define PHD_INSTANCE_VERBS(X) \
    X(TRACK_INFO, PHD_VERB_TRACK_INFO, "<instance> <name> <#RRGGBB | " PHD_NO_COLOR "> [bus | return | master]", \
      "resp 0", REPLACE, \
      "the strip's name (\"\" for none), colour and kind, absent for an input channel; a worker whose plugin format " \
      "has a track-info extension passes them on; any other word is -902") \
    X(REMOTE_PAGES, PHD_VERB_REMOTE_PAGES, "<instance>", "resp <count>", NONE, \
      "the plugin's remote-control pages, from clap.remote-controls; 0 for an instance of a format whose worker has none") \
    X(REMOTE_PAGE_GET, PHD_VERB_REMOTE_PAGE_GET, "<instance> <page>", \
      "resp 0 <page_id> <section> <page_name> <s1> <s2> <s3> <s4> <s5> <s6> <s7> <s8>", NONE, \
      "one page, 0 to count - 1: each slot the symbol param_set takes, " PHD_EMPTY_SLOT " for an empty one; -902 " \
      "for a page that is not one") \
    X(PARAM_INFO, PHD_VERB_PARAM_INFO, "<instance> <symbol>", \
      "resp 0 <unit> <scale> <min> <max> <default> <step> <stable_symbol>", NONE, \
      "what a parameter's value means: its unit, its scale, and the symbol it keeps across hosts and versions; -103 " \
      "for a symbol that is not a parameter, the plugin's own bypass and :bypass included; " \
      "-511 for a parameter whose unit and scale the worker holds no checked contract for") \
    X(PRESET_LIST, OMX_VERB_PRESET_LIST, "<instance>", OMX_VERB_PRESET_LIST_REPLY, NONE, \
      "the plugin's presets, the ones its preset discovery or its bundle lists; " PHD_STR(PHD_ERR_NO_PRESET_LIST) \
      " for an instance of a worker that cannot list them") \
    X(PRESET_GET, OMX_VERB_PRESET_GET, "<instance> <index>", OMX_VERB_PRESET_GET_REPLY, NONE, \
      "one preset, 0 to count - 1: the key preset_load takes for it, and its name; -902 for an index that is not one") \
    X(NOTE_INPUT, PHD_VERB_NOTE_INPUT, "<instance>", "resp 0 <port | " PHD_NO_NOTE_INPUT ">", NONE, \
      "whether the instance takes notes: the name of its note input on its worker's jack client, " PHD_NO_NOTE_INPUT \
      " for a plugin that takes none; " PHD_STR(PHD_ERR_NOTES_BY_JACK) " for an instance of a worker that cannot say") \
    X(NOTE_ON, PHD_VERB_NOTE_ON, "<instance> <channel> <key> <velocity>", "resp 0", NONE, \
      "play a key: channel 0 to " PHD_STR(PHD_NOTE_CHANNEL_MAX) ", key 0 to " PHD_STR(PHD_NOTE_KEY_MAX) ", velocity 1 to " \
      PHD_STR(PHD_NOTE_VELOCITY_MAX) ", a MIDI note on at the start of the worker's next cycle; " \
      PHD_STR(PHD_ERR_NO_NOTE_INPUT) " for a plugin that takes no notes, " PHD_STR(PHD_ERR_NOTES_BY_JACK) \
      " for an instance of a worker that takes none on its socket, -902 for a word out of its range") \
    X(NOTE_OFF, PHD_VERB_NOTE_OFF, "<instance> <channel> <key> <velocity>", "resp 0", NONE, \
      "release a key, velocity 0 to " PHD_STR(PHD_NOTE_VELOCITY_MAX) ", a MIDI note off; answered as " PHD_VERB_NOTE_ON " is") \
    X(ALL_NOTES_OFF, PHD_VERB_ALL_NOTES_OFF, "<instance>", "resp 0", NONE, \
      "release every key of every channel, MIDI's all notes off (controller 123) on each; answered as " PHD_VERB_NOTE_ON " is")

/* whether s is a string word: valid UTF-8, at most PHD_STRING_MAX bytes, no byte below 0x20 */
static inline int phd_string_valid(const char *s)
{
    const unsigned char *p = (const unsigned char *)s;
    int n = 0;

    while (p[n])
    {
        unsigned c = p[n], cp;
        int more, k;

        if (c < 0x20)
            return 0;
        if (c < 0x80)
        {
            n++;
            continue;
        }
        if (c >= 0xc2 && c <= 0xdf)
            more = 1, cp = c & 0x1f;
        else if (c >= 0xe0 && c <= 0xef)
            more = 2, cp = c & 0x0f;
        else if (c >= 0xf0 && c <= 0xf4)
            more = 3, cp = c & 0x07;
        else
            return 0;
        for (k = 1; k <= more; k++)
        {
            if ((p[n + k] & 0xc0) != 0x80)
                return 0;
            cp = (cp << 6) | (p[n + k] & 0x3f);
        }
        if ((more == 2 && (cp < 0x800 || (cp >= 0xd800 && cp <= 0xdfff))) || (more == 3 && (cp < 0x10000 || cp > 0x10ffff)))
            return 0;
        n += more + 1;
    }
    return n <= PHD_STRING_MAX;
}

/* whether c is a colour of track_info: #RRGGBB, either case, or PHD_NO_COLOR */
static inline int phd_color_valid(const char *c)
{
    int n;

    if (!strcmp(c, PHD_NO_COLOR))
        return 1;
    if (c[0] != '#')
        return 0;
    for (n = 1; n <= 6; n++)
        if (!((c[n] >= '0' && c[n] <= '9') || (c[n] >= 'a' && c[n] <= 'f') || (c[n] >= 'A' && c[n] <= 'F')))
            return 0;
    return c[7] == '\0';
}

/* the kind of strip a fourth word of track_info names, 1 for the first row of PHD_TRACK_KINDS; 0 for NULL (an
 * input channel); -1 for a word that is not one */
static inline int phd_track_kind(const char *word)
{
    int n = 0;

    if (!word)
        return 0;
#define X(id, name) n++; if (!strcmp(word, name)) return n;
    PHD_TRACK_KINDS(X)
#undef X
    return -1;
}

/* whether the words of a track_info line, the verb first, are its grammar */
static inline int phd_track_info_valid(char *const *word, int count)
{
    return (count == 4 || count == 5) && phd_string_valid(word[2]) && phd_color_valid(word[3]) &&
           phd_track_kind(count == 5 ? word[4] : NULL) >= 0;
}

/* whether word is a whole number from lo to hi, in decimal with no sign but a leading '-' ('-0' is not a number: zero has one spelling) */
static inline int phd_number_in(const char *word, int lo, int hi)
{
    long v = 0;
    int n = word[0] == '-' ? 1 : 0;

    if (!word[n])
        return 0;
    for (; word[n]; n++)
    {
        if (word[n] < '0' || word[n] > '9' || v > 100000)
            return 0;
        v = v * 10 + (word[n] - '0');
    }
    if (word[0] == '-')
    {
        if (v == 0)
            return 0;
        v = -v;
    }
    return v >= lo && v <= hi;
}

/* whether the words of a note verb's line, the verb first, are its grammar; 0 for a line of another verb */
static inline int phd_note_valid(char *const *word, int count)
{
    int on = !strcmp(word[0], PHD_VERB_NOTE_ON);

    if (count < 2 || !phd_number_in(word[1], 0, 1 << 20))
        return 0;
    if (on || !strcmp(word[0], PHD_VERB_NOTE_OFF))
        return count == 5 && phd_number_in(word[2], 0, PHD_NOTE_CHANNEL_MAX) && phd_number_in(word[3], 0, PHD_NOTE_KEY_MAX) &&
               phd_number_in(word[4], on ? 1 : 0, PHD_NOTE_VELOCITY_MAX);
    if (!strcmp(word[0], PHD_VERB_ALL_NOTES_OFF) || !strcmp(word[0], PHD_VERB_NOTE_INPUT))
        return count == 2;
    return 0;
}

/* whether a verb is one of the note verbs */
static inline int phd_is_note_verb(const char *verb)
{
    return !strcmp(verb, PHD_VERB_NOTE_ON) || !strcmp(verb, PHD_VERB_NOTE_OFF) || !strcmp(verb, PHD_VERB_ALL_NOTES_OFF) ||
           !strcmp(verb, PHD_VERB_NOTE_INPUT);
}

/* ---------------------------------------------------------------- the host verb table */

/* What each host profile owes every verb a controller sends the daemon: the commands of mod-host's protocol, the two
 * that Zynthian's mod-ui still names and mod-host never had, and the verbs this daemon adds. tests/verb_table.py holds
 * the table to that list, no more and no fewer, so a verb cannot be added to the daemon without its row.
 *
 * required: answered as its grammar says. optional: answered, or refused with -902; never misread. absent: refused on
 * purpose, and no client of the profile may need it. */
#define PHD_LEVEL_REQUIRED "required"
#define PHD_LEVEL_OPTIONAL "optional"
#define PHD_LEVEL_ABSENT   "absent"
#define PHD_LEVELS(X) X(REQUIRED, PHD_LEVEL_REQUIRED) X(OPTIONAL, PHD_LEVEL_OPTIONAL) X(ABSENT, PHD_LEVEL_ABSENT)

/* the profiles, a column each: X(id, name, meaning) */
#define PHD_HOST_PROFILES(X) \
    X(LV2, "lv2-worker", "an LV2 plugin's worker: mod-host, or omx-clap-host's LV2 adapter") \
    X(CLAP, "clap-worker", "a CLAP plugin's worker, omx-clap-host") \
    X(CONSOLE, "console", "the openmixer console as a controller of the daemon") \
    X(ZYNTHIAN, "zynthian", "Zynthian's mod-ui and its plugind engine as a controller of the daemon")

/* who sends the verb: mod-ui (Zynthian's mod-ui sends it to its host), mod-host (a command of mod-host.h that mod-ui
 * does not send), daemon (a verb this daemon adds: it answers it itself, whatever the worker) */
#define PHD_HOST_VERB_SOURCE_MOD_UI   "mod-ui"
#define PHD_HOST_VERB_SOURCE_MOD_HOST "mod-host"
#define PHD_HOST_VERB_SOURCE_DAEMON   "daemon"

/* X(name, source, lv2-worker, clap-worker, console, zynthian). The mod-ui rows are the operator's ruling of
 * 2026-10-21 (FreeMixer/plugin-hostd#131), read from Zynthian's verbs.tsv, with the rulings of 2026-10-22: presets
 * and bundles are required of the CLAP worker and of Zynthian; MIDI learn and CV addressing are policy of the surfaces,
 * so the host answers them only as the mechanism and they stay optional for every profile ("PRESETS IN THE HOST",
 * docs/presets.md). The others are this tree's.
 * The daemon relays a worker's verb (an instance verb to the worker that holds the instance, any other to every worker)
 * and passes its answer back, so a required verb answers -902 only while the worker does. */
#define PHD_HOST_VERBS(X) \
    X("add", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("remove", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("bypass", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("connect", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("param_set", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("state_load", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("state_save", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("state_tmpdir", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("feature_enable", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("bundle_add", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("bundle_remove", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("preset_load", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("preset_save", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("preset_show", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("transport", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("transport_sync", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("cpu_load", MOD_UI, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("midi_learn", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("midi_map", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("midi_unmap", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("cv_map", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("cv_unmap", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("monitor_midi_program", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("monitor_output", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("output_data_ready", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("patch_get", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("patch_set", MOD_UI, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("cc_map", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("cc_value_set", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("cc_unmap", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("hmi_map", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("hmi_unmap", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("show_external_ui", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("set_midi_program_change_pedalboard_bank_channel", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("set_midi_program_change_pedalboard_snapshot_channel", MOD_UI, ABSENT, ABSENT, ABSENT, ABSENT) \
    X("disconnect", MOD_HOST, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("set_bpm", MOD_HOST, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("set_bpb", MOD_HOST, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("quit", MOD_HOST, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X("param_get", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("param_monitor", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("licensee", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("monitor", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("load", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("save", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X("help", MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_TRACK_INFO, MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_REMOTE_PAGES, MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_REMOTE_PAGE_GET, MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_PARAM_INFO, MOD_HOST, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(OMX_VERB_PRESET_LIST, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(OMX_VERB_PRESET_GET, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_NOTE_INPUT, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_NOTE_ON, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_NOTE_OFF, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(PHD_VERB_ALL_NOTES_OFF, DAEMON, OPTIONAL, OPTIONAL, OPTIONAL, OPTIONAL) \
    X(OMX_VERB_WORKER_LIST, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_INSTANCE_INFO, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_SUPERVISOR_RESET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_QUARANTINE_CLEAR, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_POLICY_SET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_POOL_CONFIG, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_WORKER_ENV, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PIN_SET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PIN_CLEAR, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PIN_ACCEPT, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_LV2_WORKER_SET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_CHAIN, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_CHAIN_CLEAR, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_CHAIN_GET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PLAN, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PLAN_GET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PLAN_CLEAR, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_DESCRIPTOR_GET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_PANEL_GET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_HISTORY_GET, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED) \
    X(OMX_VERB_HISTORY_CLEAR, DAEMON, REQUIRED, REQUIRED, REQUIRED, REQUIRED)

/* ---------------------------------------------------------------- host settings */

/* what the daemon keeps of a command that names no instance and is broadcast to every worker: X(id, meaning) */
#define PHD_HOST_SETTINGS(X) \
    X(TEMPO, "the tempo, the metre and the transport a controller sets (mod-host's set_bpm, set_bpb, transport and " \
             "transport_sync) are kept, the latest line of each as it was sent, in the order they were last sent") \
    X(REPLAY, "a worker is handed them before anything else: a respawned one before its first add, and a worker " \
              "started later, of a new placement, as well; a worker's refusal of one is written to stderr and is no failure") \
    X(GRAMMAR, "a line whose words are not that command's grammar is passed on and not kept")

/* ---------------------------------------------------------------- feedback events */

/* one NUL-terminated line each on the feedback port; a worker is "w<k>" */
#define PHD_EVENT_WORKER_DIED             "worker_died"
#define PHD_EVENT_INSTANCE_VERB_DROPPED   "instance_verb_dropped"
#define PHD_EVENT_WORKER_BACKOFF          "worker_backoff"
#define PHD_EVENT_WORKER_RESPAWNED        "worker_respawned"
#define PHD_EVENT_INSTANCE_RESTORED       "instance_restored"
#define PHD_EVENT_INSTANCE_REPLAY_REFUSED "instance_replay_refused"
#define PHD_EVENT_INSTANCE_QUARANTINED    "instance_quarantined"
#define PHD_EVENT_SUPERVISOR_GAVE_UP      "supervisor_gave_up"
#define PHD_EVENT_PIN_CHANGED             "pin_changed"
#define PHD_EVENT_LV2_ADAPTER_REFUSED     "lv2_adapter_refused"
#define PHD_EVENT_CHAIN_FORMED            "chain_formed"
#define PHD_EVENT_PLAN_REASON             "plan_reason"
/* written by a worker, relayed as it wrote it */
#define PHD_EVENT_REMOTE_PAGES_CHANGED    "remote_pages_changed"
#define PHD_EVENT_REMOTE_PAGE_SUGGEST     "remote_page_suggest"
#define PHD_EVENT_PARAM_GESTURE           "param_gesture"
/* mod-host's own feedback line for a parameter, the same word as its command */
#define PHD_EVENT_PARAM_SET               "param_set"

/* the last word of a param_gesture line */
#define PHD_GESTURE_BEGIN "begin"
#define PHD_GESTURE_END   "end"

#define PHD_EVENT_SUSPECT_PREFIX "suspect:"

/* the same line, as the daemon formats it: name and format in one literal */
#define PHD_EVENT_WORKER_DIED_FMT           PHD_EVENT_WORKER_DIED " w%d %d %s %s"
#define PHD_EVENT_VERB_DROPPED_FMT          PHD_EVENT_INSTANCE_VERB_DROPPED " %d %s"
#define PHD_EVENT_VERB_DROPPED_SUSPECT_FMT  PHD_EVENT_INSTANCE_VERB_DROPPED " %d " PHD_EVENT_SUSPECT_PREFIX "%d %s"
#define PHD_EVENT_WORKER_BACKOFF_FMT        PHD_EVENT_WORKER_BACKOFF " w%d %d"
#define PHD_EVENT_WORKER_RESPAWNED_FMT      PHD_EVENT_WORKER_RESPAWNED " w%d %d %d %d"
#define PHD_EVENT_INSTANCE_RESTORED_FMT     PHD_EVENT_INSTANCE_RESTORED " %d w%d"
#define PHD_EVENT_REPLAY_REFUSED_FMT        PHD_EVENT_INSTANCE_REPLAY_REFUSED " %d %d"
#define PHD_EVENT_INSTANCE_QUARANTINED_FMT  PHD_EVENT_INSTANCE_QUARANTINED " %d w%d"
#define PHD_EVENT_SUPERVISOR_GAVE_UP_FMT    PHD_EVENT_SUPERVISOR_GAVE_UP " w%d %d %d"
#define PHD_EVENT_REMOTE_PAGES_CHANGED_FMT  PHD_EVENT_REMOTE_PAGES_CHANGED " %d"
#define PHD_EVENT_REMOTE_PAGE_SUGGEST_FMT   PHD_EVENT_REMOTE_PAGE_SUGGEST " %d %u"
#define PHD_EVENT_PARAM_GESTURE_FMT         PHD_EVENT_PARAM_GESTURE " %d %s %s"
#define PHD_EVENT_PARAM_SET_FMT             PHD_EVENT_PARAM_SET " %d %s %s"
#define PHD_EVENT_PIN_CHANGED_FMT           PHD_EVENT_PIN_CHANGED " %s %s"
#define PHD_EVENT_LV2_ADAPTER_REFUSED_FMT   PHD_EVENT_LV2_ADAPTER_REFUSED " %s %s %s"
#define PHD_EVENT_CHAIN_FORMED_FMT          PHD_EVENT_CHAIN_FORMED " %s w%d %s"
#define PHD_EVENT_PLAN_REASON_FMT           PHD_EVENT_PLAN_REASON " %d %s"

/* the table of the docs: X(name, fields, meaning), one row per shape of a line */
#define PHD_EVENTS(X) \
    X(PHD_EVENT_WORKER_DIED, "<worker> <pid> <exit:N | signal:N> <instance>,...", \
      "a worker died; the instances it held, or - for none") \
    X(PHD_EVENT_INSTANCE_VERB_DROPPED, "<instance> <the command as sent>", \
      "the command a worker died on, dropped from the ledger; or the add it died on, the add as the worker was given it, " \
      "which names the plugin, or the " PHD_VERB_PIN_EXPECT " of that add") \
    X(PHD_EVENT_INSTANCE_VERB_DROPPED, "<instance> " PHD_EVENT_SUSPECT_PREFIX "<ms> <the command as sent>", \
      "the last verb a worker answered when it died inside suspect_window_ms, <ms> the age of the reply") \
    X(PHD_EVENT_WORKER_BACKOFF, "<worker> <ms>", "the respawn waits this long") \
    X(PHD_EVENT_WORKER_RESPAWNED, "<worker> <pid> <replayed_count> <ms>", "a worker is back and its ledger replayed") \
    X(PHD_EVENT_INSTANCE_RESTORED, "<instance> <worker>", "an instance is back in a worker") \
    X(PHD_EVENT_INSTANCE_REPLAY_REFUSED, "<instance> <code>", \
      "a replayed add was refused, by its pin or by the worker, <code> the refusal's own: no worker holds the " \
      "instance until the next replay") \
    X(PHD_EVENT_INSTANCE_QUARANTINED, "<instance> <worker>", \
      "the culprit of a pool or a chain death, placed own until cleared; a chain goes on without it") \
    X(PHD_EVENT_CHAIN_FORMED, "<chain> <worker> <instance>,...", \
      "a chain's worker is up with these members, in this order, after its declaration, a respawn or a member's " \
      "quarantine; " PHD_WORD_NONE " for none. <chain> is the number chain declared, or <plan>" PHD_PLACE_PLAN_SEPARATOR \
      "<k> for segment k of a plan") \
    X(PHD_EVENT_PLAN_REASON, "<chain> <instance>:<reason>,...", \
      "a plan of the chain changed: what " OMX_VERB_PLAN_GET " answers now after the segments, " PHD_WORD_NONE " for none") \
    X(PHD_EVENT_SUPERVISOR_GAVE_UP, "<worker> <deaths> <window_ms>", "the storm bound is spent; respawning ends") \
    X(PHD_EVENT_PIN_CHANGED, "<uri> " PHD_PIN_CHANGED_FILES " | " PHD_PIN_CHANGED_LAYOUT, \
      "an add or a replay of a plugin was refused because its files, or the layout the worker found, differ from its " \
      "pin; the pin is as it was until pin_accept or pin_set") \
    X(PHD_EVENT_LV2_ADAPTER_REFUSED, "<uri> <reason> " PHD_LV2_WORKER_AUTO " | " PHD_LV2_WORKER_CLAP_HOST, \
      "the LV2 adapter of the " PHD_FORMAT_LV2_CLAP " worker refused a plugin: <reason> is the hosting.* code after -102 on the " \
      "worker's reply to that add (" PHD_WORD_NONE " when it named none); the last word is the lv2_worker in force, " PHD_LV2_WORKER_AUTO " for a plugin " \
      "the " PHD_FORMAT_LV2 " row runs from now on, " PHD_LV2_WORKER_CLAP_HOST " for an add answered " \
      PHD_STR(PHD_ERR_LV2_ADAPTER_REFUSED)) \
    X(PHD_EVENT_REMOTE_PAGES_CHANGED, "<instance>", \
      "relayed from a worker: the plugin changed its remote pages; read them again") \
    X(PHD_EVENT_REMOTE_PAGE_SUGGEST, "<instance> <page_id>", \
      "relayed from a worker: the plugin suggests the remote page of that id (a page_id of " PHD_VERB_REMOTE_PAGE_GET \
      "); a surface may follow it") \
    X(PHD_EVENT_PARAM_GESTURE, "<instance> <symbol> " PHD_GESTURE_BEGIN " | " PHD_GESTURE_END, \
      "relayed from a worker: the user took hold of a control of the plugin's own, or let it go; a controller writes no " \
      "automation of that parameter in between. The values the plugin moves meanwhile, or at any time by itself, are " \
      "mod-host's param_set feedback lines, relayed as written. A gesture whose worker died, or whose instance was " \
      "removed, before its " PHD_GESTURE_END " is ended by the daemon, before the worker_died event") \
    X(PHD_EVENT_PARAM_SET, "<instance> <symbol> <value>", \
      "relayed from a worker: parameter feedback, a value the plugin moved by itself (its automation, an LFO, a " \
      "preset load, a MIDI map, the user's knob of the plugin's own), as mod-host writes it; a controller updates its " \
      "control to it. A worker never writes it for a value a controller's param_set gave it, and a worker that writes " \
      "none changes nothing: the daemon adds no line of its own")

/* ---------------------------------------------------------------- worker feedback, relayed */

/* a worker is started with a command port and a feedback port of its own, both on loopback and private to it */
#define PHD_WORKER_ARGUMENTS "-n -p <command port> -f <feedback port>"

/* what the daemon does with the lines a worker writes on its feedback port: X(id, meaning) */
#define PHD_RELAY(X) \
    X(VERBATIM, "every line a worker writes on its feedback port goes out on the daemon's feedback port as the worker " \
                "wrote it: output_set, param_set, data_finish and the rest of mod-host's feedback, and a line the daemon " \
                "does not know") \
    X(INSTANCE, "the instance number in a relayed line is already the controller's: " PHD_VERB_ADD " hands it to the " \
                "worker unchanged, so nothing in a line is rewritten") \
    X(ORDER, "a worker's lines go out in the order it wrote them, and what a worker wrote before it died goes out " \
             "before its " PHD_EVENT_WORKER_DIED " event; an instance lives in one worker at a time, so its lines keep " \
             "their order across a respawn; the lines of different workers interleave") \
    X(SUBSCRIPTION, "monitor_output is in the ledger, one line per output, and param_monitor as it was sent; a " \
                    "respawn replays them after the " PHD_VERB_ADD ", so a respawned instance reports the same outputs, " \
                    "each once, starting again from its first value") \
    X(HANDSHAKE, "output_data_ready names no instance and goes to every worker; each worker's data_finish is relayed") \
    X(NO_CONTROLLER, "with no feedback port, or no controller on it, a line is dropped, as mod-host drops it; the " \
                     "daemon reads every worker's feedback all the time, so no worker waits on it")

/* ---------------------------------------------------------------- settings */

#define PHD_DEFAULT_MOD_HOST          "mod-host"
#define PHD_DEFAULT_CLAP_HOST         "omx-clap-host"
#define PHD_DEFAULT_LV2_WORKER        PHD_LV2_WORKER_AUTO
#define PHD_DEFAULT_LV2_PATH          "/usr/lib64/lv2:/usr/lib/lv2:/usr/local/lib/lv2"
#define PHD_DEFAULT_STATE_ROOT        "/tmp"
#define PHD_DEFAULT_READY_TIMEOUT_MS  5000
#define PHD_DEFAULT_RPC_TIMEOUT_MS    5000
#define PHD_DEFAULT_BACKOFF_BASE_MS   250
#define PHD_DEFAULT_BACKOFF_MAX_MS    5000
#define PHD_DEFAULT_STORM_DEATHS      5
#define PHD_DEFAULT_STORM_WINDOW_MS   60000
#define PHD_DEFAULT_SUSPECT_WINDOW_MS 500
#define PHD_DEFAULT_CHECKPOINT_MS     5000
#define PHD_DEFAULT_IDLE_MS           25
#define PHD_DEFAULT_POOL_MAX          8
#define PHD_DEFAULT_GROUPING          PHD_GROUPING_OFF
/* starting values of the planner's limits; the benchmark sets the ones a release ships (the design note, The benchmark) */
#define PHD_DEFAULT_GROUP_MAX         8
#define PHD_DEFAULT_GROUP_COST_MAX    60
#define PHD_DEFAULT_GROUP_RATE        48000
#define PHD_DEFAULT_GROUP_QUANTUM     128
#define PHD_DEFAULT_REQUIRE_PINS      1
#define PHD_DEFAULT_PIN_MODE          PHD_PIN_MODE_FIRST_USE
#define PHD_DEFAULT_PINS_DIR          "/usr/share/plugin-hostd/pins.d"
#define PHD_DEFAULT_PROBE             "plugin-hostd-probe"
#define PHD_DEFAULT_HISTORY_WINDOW_S  60
#define PHD_DEFAULT_HISTORY_SAVE_S    300
#define PHD_DEFAULT_HISTORY_REGROUP_S 600

/* The running history (the grouping-planner design note, The history record): what each plugin did on
 * this machine, one line per <uri> <binary digest> <host class> in a file of the daemon's own, whose keys are the words
 * of PLUGIN_HOSTD_HISTORY_KEYS (data/history.json). The first line is PHD_HISTORY_HEADER; the file is local, mode 0600,
 * and only the daemon writes it. The summary history_get answers reads crashes within PHD_HISTORY_KEEP_DAYS of
 * last_crash, and marks a plugin raises_xruns once it has PHD_HISTORY_MIN_WINDOWS grouped windows and its share of xrun
 * windows grouped exceeds its share solo by PHD_HISTORY_XRUN_MARGIN_PCT percentage points, or exceeds
 * PHD_HISTORY_XRUN_MARGIN_PCT percent when it never ran alone. */
#define PHD_HISTORY_NAME              "plugin-hostd/history"
#define PHD_HISTORY_HEADER            "# plugin-hostd history/1"
#define PHD_HISTORY_RECORD            "history"
#define PHD_HISTORY_KEEP_DAYS         30
#define PHD_HISTORY_MIN_WINDOWS       30
#define PHD_HISTORY_XRUN_MARGIN_PCT   5

/* The directories of what the scan of an add gathers: state, kept across a reboot. An empty setting is the default:
 * <state home>/<subdir>, where the state home is $XDG_STATE_HOME, else /var/lib for a daemon run as root (a system
 * service), else $HOME/.local/state. A missing directory is made, mode 0700; one that cannot be written stops the daemon with PHD_ERR_DIR_NOT_WRITABLE. */
#define PHD_DIR_DESCRIPTORS_SUBDIR    "omx/descriptors"
#define PHD_DIR_QUALIFICATION_SUBDIR  "omx/qualification"
#define PHD_DIR_SYSTEM_STATE_HOME     "/var/lib"
#define PHD_DIR_USER_STATE_HOME       ".local/state"
#define PHD_DIR_MODE                  0700
#define PHD_DIR_DEFAULT_TEXT(subdir) \
    "empty is $XDG_STATE_HOME/" subdir ", else " PHD_DIR_SYSTEM_STATE_HOME "/" subdir " run as root (a system " \
    "service), else $HOME/" PHD_DIR_USER_STATE_HOME "/" subdir

/* A scanned descriptor's file in descriptor_dir: <id>@<version>-<hash>.json, the rule plugin-qualify's scanners name
 * theirs by. The id is the CLAP plugin id or the LV2 URI, the version the one the descriptor states
 * (PHD_DESCRIPTOR_NO_VERSION when it states none), each character outside [A-Za-z0-9._-] of both written
 * PHD_DESCRIPTOR_SAFE_CHAR; the hash is the first PHD_DESCRIPTOR_HASH_LEN hex digits of the SHA-256 of the plugin's
 * binary (the .clap, or the file the LV2 bundle's manifest names with lv2:binary). Written once, atomically; a changed
 * binary gets a new name and the old file stays. */
#define PHD_DESCRIPTOR_NAME_SYNTAX    "<id>@<version>-<hash>.json"
#define PHD_DESCRIPTOR_NO_VERSION     "unversioned"
#define PHD_DESCRIPTOR_SAFE_CHAR      '_'
#define PHD_DESCRIPTOR_HASH_LEN       12

/* A plugin's panel file: in PHD_PANEL_SUBDIR of descriptor_dir, under its descriptor's name, written by the same scan
 * after the descriptor, once and atomically (docs/panel.md) */
#define PHD_PANEL_SUBDIR              "panels"
#define PHD_PANEL_NAME_SYNTAX         PHD_PANEL_SUBDIR "/" PHD_DESCRIPTOR_NAME_SYNTAX

/* the settings file: one "key value" per line, '#' starts a comment.
 * A string setting: X(key, size, default, env, meaning); env names the variable that stands in for the default when
 * it is set and not empty, "" for none; size is path or pathlist, the storage class of the daemon's copy. */
#define PHD_CONF_STRINGS(X) \
    X(mod_host, path, PHD_DEFAULT_MOD_HOST, "", "worker for " PHD_FORMAT_LV2 " (a name on PATH or a path)") \
    X(clap_host, path, PHD_DEFAULT_CLAP_HOST, "", "worker for " PHD_FORMAT_CLAP) \
    X(lv2_worker, word, PHD_DEFAULT_LV2_WORKER, "", "who runs an LV2 plugin: mod-host (the mod_host program), omx-clap-host " \
      "(the clap_host program, through its LV2 adapter, a plugin it cannot run refused with a code) or auto (the adapter " \
      "first, mod-host for what it refuses, each such plugin in a worker of its own unless its add names a placement); " \
      OMX_VERB_LV2_WORKER_SET " overrides it for one plugin") \
    X(lv2_path, pathlist, PHD_DEFAULT_LV2_PATH, "LV2_PATH", "where bundles are searched") \
    X(state_root, path, PHD_DEFAULT_STATE_ROOT, "XDG_RUNTIME_DIR", "the daemon's checkpoints and worker logs") \
    X(pin_mode, word, PHD_DEFAULT_PIN_MODE, "", "strict or first-use, while require_pins is 1: first-use records the pin " \
      "of a plugin on its first add, strict admits only a plugin a controller, a pin_file or pins_dir pinned") \
    X(grouping, word, PHD_DEFAULT_GROUPING, "", "off or on: whether plan applies its plan (a run of consecutive members " \
      "that may share a worker is declared as a chain), or only answers it; the default stays off until the benchmark " \
      "has published a win") \
    X(pin_store, path, "", "", "the file first-use pins are kept in; empty is $XDG_STATE_HOME/plugin-hostd/pins, " \
      "else $HOME/.local/state/plugin-hostd/pins") \
    X(pin_file, path, "", "", "a file of pin lines loaded at start, as plugin-qualify --all --pins writes it; empty is none") \
    X(pins_dir, path, PHD_DEFAULT_PINS_DIR, "", "the read-only pins of packages: every file in it whose name ends in .pins, read at start " \
      "in name order, under the store, the pin_file and pin_set, except that a pin of verdict=refused there always holds; " \
      "empty is none") \
    X(descriptor_dir, path, "", "OMX_DESCRIPTOR_DIR", "the scanned descriptors, one file per plugin binary (" \
      PHD_DESCRIPTOR_NAME_SYNTAX ", the hash the binary's SHA-256), written by the scan of an add and read by " OMX_VERB_DESCRIPTOR_GET "; " \
      PHD_DIR_DEFAULT_TEXT(PHD_DIR_DESCRIPTORS_SUBDIR) "; its variable is for tests only") \
    X(qualification_dir, path, "", "OMX_QUALIFICATION_DIR", "plugin-qualify's qualification records (verdict, cost, " \
      "version tested), kept apart from the descriptors; " PHD_DIR_DEFAULT_TEXT(PHD_DIR_QUALIFICATION_SUBDIR) \
      "; its variable is for tests only") \
    X(probe, path, PHD_DEFAULT_PROBE, "", "the scanner an add runs, as <probe> describe <target>, in a child of its " \
      "own once per plugin binary; its stdout is the descriptor") \
    X(history_file, path, "", "", "the running history: what each plugin did on this machine, kept per plugin, binary and " \
      "host class; empty is $XDG_STATE_HOME/" PHD_HISTORY_NAME ", else $HOME/.local/state/" PHD_HISTORY_NAME "; local to " \
      "this machine, mode 0600, written by the daemon alone, and deleted by history_clear") \
    X(host_class, word, "", "", "the host class the history is kept under, as arch/cores/clock (x86_64/5-8/2.5-3.5GHz); " \
      "empty is the class of this machine, as the probe writes it; no white space")

/* A whole-number setting: X(key, default, unit, meaning); 0 turns off where the meaning says so */
#define PHD_CONF_INTS(X) \
    X(ready_timeout_ms, PHD_DEFAULT_READY_TIMEOUT_MS, "ms", "a worker that does not accept in this long is a failed spawn") \
    X(rpc_timeout_ms, PHD_DEFAULT_RPC_TIMEOUT_MS, "ms", "a worker that does not answer in this long is killed") \
    X(backoff_base_ms, PHD_DEFAULT_BACKOFF_BASE_MS, "ms", "respawn backoff, doubling per death in the window") \
    X(backoff_max_ms, PHD_DEFAULT_BACKOFF_MAX_MS, "ms", "the most a respawn backoff grows to") \
    X(storm_deaths, PHD_DEFAULT_STORM_DEATHS, "deaths", "deaths inside the window that end respawning of a placement") \
    X(storm_window_ms, PHD_DEFAULT_STORM_WINDOW_MS, "ms", "the window storm_deaths are counted in") \
    X(suspect_window_ms, PHD_DEFAULT_SUSPECT_WINDOW_MS, "ms", \
      "a worker that dies this soon after a reply drops the verb it answered; 0 turns it off") \
    X(checkpoint_ms, PHD_DEFAULT_CHECKPOINT_MS, "ms", "a quiet interval with a changed ledger writes a checkpoint") \
    X(idle_ms, PHD_DEFAULT_IDLE_MS, "ms", "the period of the idle tick: reap, respawn, checkpoint") \
    X(pool_max, PHD_DEFAULT_POOL_MAX, "instances", "instances in a pool before a sibling opens") \
    X(history_window_s, PHD_DEFAULT_HISTORY_WINDOW_S, "s", \
      "the length of one history window: a worker's CPU and memory are read and folded into the history of its plugins " \
      "once per window, and a window the plugin was up less than half of is not counted; 0 keeps no history") \
    X(history_save_s, PHD_DEFAULT_HISTORY_SAVE_S, "s", "the history is written at most once this often when it changed, " \
      "and at quit") \
    X(history_regroup_s, PHD_DEFAULT_HISTORY_REGROUP_S, "s", \
      "a plan whose group was split by a death that named no culprit is made again after this many seconds without " \
      "another death of its members, and the members that share are gathered in a worker again; 0 never makes it again " \
      "by itself") \
    X(group_max, PHD_DEFAULT_GROUP_MAX, "instances", "most members of one segment of a plan; 0 sets no limit") \
    X(group_cost_max, PHD_DEFAULT_GROUP_COST_MAX, "percent of a core", \
      "most the costs of the members of one segment of a plan add to, each a member's coreFractionP95 of its " \
      "qualification record at group_rate and group_quantum; a member over it alone stays alone; 0 sets no limit") \
    X(group_rate, PHD_DEFAULT_GROUP_RATE, "Hz", "the sample rate the cost of a member is read at") \
    X(group_quantum, PHD_DEFAULT_GROUP_QUANTUM, "frames", "the quantum the cost of a member is read at") \
    X(require_pins, PHD_DEFAULT_REQUIRE_PINS, "", \
      "1: add admits only a plugin that has a pin (see pin_mode), its files hashed before any worker sees it, and a plugin of a " \
      "format whose pin holds only in a world of its own gets a worker of its own, its world the plugin's files (a " \
      PHD_PLACE_DEFAULT " that resolves to a pool is placed " PHD_PLACE_OWN "); 0: no pin is checked")

#endif

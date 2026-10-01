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
 * JSON when it is not C. The mod-host protocol itself, which the daemon speaks unchanged, is not declared here. */

#ifndef PLUGIN_HOSTD_PROTOCOL_H
#define PLUGIN_HOSTD_PROTOCOL_H

#include <string.h>

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

#define PHD_CONSTANTS(X) \
    X(default_command_port, PHD_DEFAULT_COMMAND_PORT, "port", \
      "the command port without -p; the feedback port is the next one, unless -n is given") \
    X(connect_retry_ms, PHD_CONNECT_RETRY_MS, "ms", \
      "how long the idle tick asks again for a connect a respawned worker could not make yet") \
    X(line_max, PHD_LINE_MAX, "bytes", "the protocol socket's buffer: the longest pin_set line the daemon takes")

/* ---------------------------------------------------------------- placement */

#define PHD_PLACE_OWN           "own"
#define PHD_PLACE_DEFAULT       "default"
#define PHD_PLACE_POOL_PREFIX   "pool:"
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
#define PHD_FORMAT_ANY  "*"
#define PHD_WORD_ALL    "all"
#define PHD_WORD_NONE   "-"

/* X(id, name) in the order of the daemon's enum */
#define PHD_FORMATS(X) X(LV2, PHD_FORMAT_LV2) X(CLAP, PHD_FORMAT_CLAP)

/* X(id, name, meaning) in the order of the daemon's enum */
#define PHD_WORKER_STATES(X) \
    X(UP, "up", "accepting commands") \
    X(STARTING, "starting", "spawned, not yet accepting") \
    X(BACKOFF, "backoff", "dead, waiting to be respawned") \
    X(GIVEN_UP, "given-up", "the storm bound is spent for its placement")

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

/* the codes the supervisor adds to mod-host's, the -5xx hundred; a reply is "resp <code>" */
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

/* X(id, meaning) */
#define PHD_ERRORS(X) \
    X(PLACEMENT_INVALID, "placement invalid: not a placement, or not valid here, as a " PHD_PLACE_POOL_PREFIX \
                         "<name> for an " PHD_FORMAT_LV2 " plugin while require_pins is on") \
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
    X(PIN_ABSENT, "require_pins is on and the plugin has no pin, or its layout pin is in a scheme this version does " \
                  "not know: add is refused and no worker sees it") \
    X(PIN_BINARY_MISMATCH, "a pinned file is missing or its SHA-256 differs, or the plugin's manifest names a file the " \
                           "pin does not hold: add is refused and no worker sees it") \
    X(PIN_LAYOUT_MISMATCH, "the worker found the parameter layout after init differs from the layout pin: the " \
                           "instance is destroyed before activate") \
    X(NO_PARAM_CONTRACT, "the host holds no checked unit and scale for this parameter: fall back to qualification")

/* ---------------------------------------------------------------- verbs */

#define PHD_VERB_ADD              "add"
#define PHD_VERB_WORKER_LIST      "worker_list"
#define PHD_VERB_INSTANCE_INFO    "instance_info"
#define PHD_VERB_SUPERVISOR_RESET "supervisor_reset"
#define PHD_VERB_QUARANTINE_CLEAR "quarantine_clear"
#define PHD_VERB_POLICY_SET       "policy_set"
#define PHD_VERB_POOL_CONFIG      "pool_config"
#define PHD_VERB_WORKER_ENV       "worker_env"
#define PHD_VERB_PIN_SET          "pin_set"
#define PHD_VERB_PIN_CLEAR        "pin_clear"
#define PHD_VERB_PIN_EXPECT       "pin_expect"

/* the words of a pin: <path>=<sha256>, joined by ',', and <scheme>:<sha256> */
#define PHD_PIN_FILE_SEPARATOR   ","
#define PHD_PIN_DIGEST_SEPARATOR "="
#define PHD_PIN_SCHEME_SEPARATOR ":"
/* what a path of a pin cannot hold: the separators of pin_set's words, and whitespace */
#define PHD_PIN_PATH_EXCLUDED    PHD_PIN_FILE_SEPARATOR PHD_PIN_DIGEST_SEPARATOR " \t\r\n"
/* a manifest's IRI that holds this is percent-encoded */
#define PHD_PIN_PERCENT          "%"

/* what cannot be pinned, each a refusal and never a partial pin: X(id, meaning) */
#define PHD_PIN_LIMITS(X) \
    X(PATH, "a path holding '" PHD_PIN_FILE_SEPARATOR "', '" PHD_PIN_DIGEST_SEPARATOR "' or whitespace cannot be pinned: " \
            "they are the separators of " PHD_VERB_PIN_SET "'s words, and " PHD_VERB_PIN_SET " refuses it as a token " \
            "outside its grammar") \
    X(LINE, "a " PHD_VERB_PIN_SET " line is at most line_max, " PHD_STR(PHD_LINE_MAX) " bytes, the protocol socket's " \
            "buffer; a longer one is refused as outside the grammar") \
    X(MANIFEST, "a manifest that uses @base, or names a file of the plugin by a percent-encoded IRI, makes add answer " \
                "PHD_ERR_PIN_BINARY_MISMATCH " PHD_STR(PHD_ERR_PIN_BINARY_MISMATCH) ": the daemon does not resolve " \
                "either, so it cannot know the file the host would load")

/* the verbs the daemon adds to mod-host's, or extends: X(id, name, arguments, reply, meaning) */
#define PHD_VERBS(X) \
    X(ADD, PHD_VERB_ADD, "<uri> <instance> [" PHD_PLACEMENT_SYNTAX "] [client_name]", "resp <instance>", \
      "mod-host's add with a placement; a token after the instance that is not a placement is the jack client name") \
    X(WORKER_LIST, PHD_VERB_WORKER_LIST, "", \
      "resp <n> <worker>:<pid>:<format>:<state>:<place>:<i>,<i>,...", "the workers, one record each") \
    X(INSTANCE_INFO, PHD_VERB_INSTANCE_INFO, "<instance>", "resp 0 <worker> <pid> <state> <crashes> <quarantined>", \
      "where an instance lives and what it has cost") \
    X(SUPERVISOR_RESET, PHD_VERB_SUPERVISOR_RESET, "[<worker> | " PHD_WORD_ALL "]", "resp 0", \
      "re-arm the storm bound and the backoff of a given-up placement") \
    X(QUARANTINE_CLEAR, PHD_VERB_QUARANTINE_CLEAR, "<instance> | " PHD_WORD_ALL, "resp 0", \
      "let a quarantined instance go back where its placement says") \
    X(POLICY_SET, PHD_VERB_POLICY_SET, "<" PHD_FORMAT_LV2 " | " PHD_FORMAT_CLAP " | " PHD_FORMAT_ANY "> " \
      PHD_PLACE_OWN " | " PHD_PLACE_POOL_PREFIX "<name>", "resp 0", "the placement of an add that says default") \
    X(POOL_CONFIG, PHD_VERB_POOL_CONFIG, "<name> <max_instances>", "resp 0", \
      "the instances a pool holds before a sibling opens") \
    X(WORKER_ENV, PHD_VERB_WORKER_ENV, "<" PHD_FORMAT_LV2 " | " PHD_FORMAT_CLAP " | " PHD_FORMAT_ANY "> <cpu-list|" \
      PHD_WORD_NONE "> <nice|" PHD_WORD_NONE ">", "resp 0", \
      "the cpu list and the nice value of the workers of a format, at spawn and on the ones running") \
    X(PIN_SET, PHD_VERB_PIN_SET, "<uri> <path>" PHD_PIN_DIGEST_SEPARATOR "<sha256>[" PHD_PIN_FILE_SEPARATOR "<path>" \
      PHD_PIN_DIGEST_SEPARATOR "<sha256>...] <scheme>" PHD_PIN_SCHEME_SEPARATOR "<sha256>", "resp 0", \
      "the pin of one plugin: the SHA-256 of every file the host loads for it, a path relative to the bundle (the " \
      ".clap's directory for a CLAP), and its layout fingerprint; it replaces an earlier pin of the uri") \
    X(PIN_CLEAR, PHD_VERB_PIN_CLEAR, "<uri> | " PHD_WORD_ALL, "resp 0", "forget the pin of one plugin, or of every one") \
    X(PIN_EXPECT, PHD_VERB_PIN_EXPECT, "<instance> <scheme>" PHD_PIN_SCHEME_SEPARATOR "<sha256>", "resp 0", \
      "sent by the daemon to a " PHD_FORMAT_CLAP " worker just before the instance's add: the layout pin that add " \
      "checks after init and before activate; any other reply than resp 0 refuses the add with that code, and the " \
      "add is never forwarded")

/* ---------------------------------------------------------------- instance verbs */

/* What a host knows of a strip and of a plugin's controls, asked by instance. The daemon routes them to a
 * PHD_FORMAT_CLAP worker, which answers them from the plugin; for a PHD_FORMAT_LV2 instance it answers them itself and
 * never forwards them. A string word is quoted when it is not a plain word, and always in a reply, with \" inside it
 * for a quote: mod-host's own tokenizer reads them. */
#define PHD_VERB_TRACK_INFO      "track_info"
#define PHD_VERB_REMOTE_PAGES    "remote_pages"
#define PHD_VERB_REMOTE_PAGE_GET "remote_page_get"
#define PHD_VERB_PARAM_INFO      "param_info"

/* the same verbs as a host registers them with protocol_add_command */
#define PHD_VERB_TRACK_INFO_FMT      PHD_VERB_TRACK_INFO " %i %s %s ..."
#define PHD_VERB_REMOTE_PAGES_FMT    PHD_VERB_REMOTE_PAGES " %i"
#define PHD_VERB_REMOTE_PAGE_GET_FMT PHD_VERB_REMOTE_PAGE_GET " %i %i"
#define PHD_VERB_PARAM_INFO_FMT      PHD_VERB_PARAM_INFO " %i %s"

/* the longest string word, in bytes: CLAP_NAME_SIZE - 1 */
#define PHD_STRING_MAX 255
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
      "the strip's name (\"\" for none), colour and kind, absent for an input channel; a " PHD_FORMAT_CLAP \
      " plugin reads them through clap.track-info; any other word is -902") \
    X(REMOTE_PAGES, PHD_VERB_REMOTE_PAGES, "<instance>", "resp <count>", NONE, \
      "the plugin's remote-control pages, from clap.remote-controls; 0 for an " PHD_FORMAT_LV2 " instance") \
    X(REMOTE_PAGE_GET, PHD_VERB_REMOTE_PAGE_GET, "<instance> <page>", \
      "resp 0 <page_id> <section> <page_name> <s1> <s2> <s3> <s4> <s5> <s6> <s7> <s8>", NONE, \
      "one page, 0 to count - 1: each slot the symbol param_set takes, " PHD_EMPTY_SLOT " for an empty one; -902 " \
      "for a page that is not one") \
    X(PARAM_INFO, PHD_VERB_PARAM_INFO, "<instance> <symbol>", \
      "resp 0 <unit> <scale> <min> <max> <default> <step> <stable_symbol>", NONE, \
      "what a parameter's value means: its unit, its scale, and the symbol it keeps across hosts and versions; -103 " \
      "for a symbol that is not a parameter, the plugin's own bypass and :bypass included")

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
/* written by a worker, relayed as it wrote it */
#define PHD_EVENT_REMOTE_PAGES_CHANGED    "remote_pages_changed"

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

/* the table of the docs: X(name, fields, meaning), one row per shape of a line */
#define PHD_EVENTS(X) \
    X(PHD_EVENT_WORKER_DIED, "<worker> <pid> <exit:N | signal:N> <instance>,...", \
      "a worker died; the instances it held, or - for none") \
    X(PHD_EVENT_INSTANCE_VERB_DROPPED, "<instance> <the command as sent>", \
      "the command a worker died on, dropped from the ledger, or the " PHD_VERB_PIN_EXPECT " of an add it died on") \
    X(PHD_EVENT_INSTANCE_VERB_DROPPED, "<instance> " PHD_EVENT_SUSPECT_PREFIX "<ms> <the command as sent>", \
      "the last verb a worker answered when it died inside suspect_window_ms, <ms> the age of the reply") \
    X(PHD_EVENT_WORKER_BACKOFF, "<worker> <ms>", "the respawn waits this long") \
    X(PHD_EVENT_WORKER_RESPAWNED, "<worker> <pid> <replayed_count> <ms>", "a worker is back and its ledger replayed") \
    X(PHD_EVENT_INSTANCE_RESTORED, "<instance> <worker>", "an instance is back in a worker") \
    X(PHD_EVENT_INSTANCE_REPLAY_REFUSED, "<instance> <code>", \
      "a replayed add was refused, by its pin or by the worker, <code> the refusal's own: no worker holds the " \
      "instance until the next replay") \
    X(PHD_EVENT_INSTANCE_QUARANTINED, "<instance> <worker>", "the culprit of a pool death, placed own until cleared") \
    X(PHD_EVENT_SUPERVISOR_GAVE_UP, "<worker> <deaths> <window_ms>", "the storm bound is spent; respawning ends") \
    X(PHD_EVENT_REMOTE_PAGES_CHANGED, "<instance>", \
      "relayed from a " PHD_FORMAT_CLAP " worker: the plugin changed its remote pages; read them again")

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
#define PHD_DEFAULT_REQUIRE_PINS      1

/* the settings file: one "key value" per line, '#' starts a comment.
 * A string setting: X(key, size, default, env, meaning); env names the variable that stands in for the default when
 * it is set and not empty, "" for none; size is path or pathlist, the storage class of the daemon's copy. */
#define PHD_CONF_STRINGS(X) \
    X(mod_host, path, PHD_DEFAULT_MOD_HOST, "", "worker for " PHD_FORMAT_LV2 " (a name on PATH or a path)") \
    X(clap_host, path, PHD_DEFAULT_CLAP_HOST, "", "worker for " PHD_FORMAT_CLAP) \
    X(lv2_path, pathlist, PHD_DEFAULT_LV2_PATH, "LV2_PATH", "where bundles are searched") \
    X(state_root, path, PHD_DEFAULT_STATE_ROOT, "XDG_RUNTIME_DIR", "the daemon's checkpoints and worker logs")

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
    X(require_pins, PHD_DEFAULT_REQUIRE_PINS, "", \
      "1: add admits only a plugin pin_set pinned, its files hashed before any worker sees it, and an " PHD_FORMAT_LV2 \
      " plugin gets a worker of its own, its world the one bundle the pin holds (a " PHD_PLACE_DEFAULT " that resolves " \
      "to a pool is placed " PHD_PLACE_OWN "); 0: no pin is checked")

#endif

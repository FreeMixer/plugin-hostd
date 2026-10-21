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

/* A worker that is not a plugin host: it answers mod-host's protocol for the verbs the daemon routes, keeps
 * its parameters as text, saves and loads them as state, and dies or hangs on cue.
 *
 *   add <uri> <n> [client]      "crash_on_add" in the uri aborts, "refuse" in it answers -101,
 *                               "nostate" in it makes an instance that never writes state; an lv2: uri is the
 *                               adapter's (mod-host is given it bare), and the fake answers it as omx-clap-host does:
 *                               "adapter_midi", "adapter_missing", "adapter_wide" or "adapter_unrealised" in it is a
 *                               plugin the adapter refuses, "resp -102 <hosting code>" and "<uri>: <hosting code>" on
 *                               stderr; "adapter_nocode" is a refusal that names no code, "resp -102" alone;
 *                               "absent" in it is a plugin no bundle of the world holds, "resp -101" and no code;
 *                               "abort_on_mod_host" in a bare uri aborts, as a plugin that dies in instantiate does
 *   param_set <n> crash <v>     v other than 0 aborts 30 ms after the reply (FAKE_CRASH_AFTER_MS to say another), as a
 *                               plugin does in a callback
 *                               (once only when FAKE_CRASH_ONCE names a file: it is created by the crash)
 *   param_set <n> crashnow <v>  v other than 0 aborts before the reply, with the command on the wire
 *   param_set <n> hang <v>      v other than 0 never answers
 *   connect <a> <b>             with FAKE_CONNECT_AFTER_MS set, answers -205 until that long after the worker started,
 *                               as a jack client does for a port it has not been told of yet
 *   list_connections            "resp 0 <a>><b> ..."
 *   pin_layout <n>              resp 0 <the layout pin>, the layout of the instance n (FAKE_NO_PIN_LAYOUT: the verb
 *                               is unknown, -902)
 *   pin_expect <n> <pin>        the layout pin of the next add of <n>: that add answers PHD_ERR_PIN_LAYOUT_MISMATCH
 *                               when the fake's own layout differs (FAKE_NO_PIN_EXPECT: the verb is unknown, -902;
 *                               FAKE_PIN_EXPECT_HANG: it is never answered)
 *   param_set <n> pages_changed <v>   v other than 0 writes "remote_pages_changed <n>" on the feedback port, as a CLAP
 *                               worker does when its plugin changes its remote pages
 *   param_set <n> long_line <v>   writes a feedback line of v bytes of 'x' (v > 0), then "remote_pages_changed <n>"
 *   param_set <n> gesture <v>   v other than 0 writes what a CLAP worker relays when the user turns a knob of the plugin's
 *                               own: "param_gesture <n> 0 begin", "param_set <n> 0 <v>" (v as sent), "param_gesture <n> 0 end", then
 *                               "remote_page_suggest <n> 8", in that order
 *   param_set <n> hold <v>      v other than 0 writes "param_gesture <n> 0 begin" and never its end
 *   preset_list <n>             "resp 2", and preset_get <n> <0|1> one preset each, -902 for any other index
 *   track_info <n> ...          "resp 0"; the fake keeps nothing of it (FAKE_LOG shows what it was sent)
 *   note_input <n>              "resp 0 midi_in" for an instance whose uri holds "synth", "resp 0 -" for any other
 *   note_on, note_off, all_notes_off <n> ...   "resp 0" for a synth, PHD_ERR_NOTE_QUEUE_FULL for one whose uri holds
 *                               "synth_full", PHD_ERR_NO_NOTE_INPUT for any other; the fake
 *                               plays nothing (FAKE_LOG shows what it was sent)
 *   chain <chain> <n> ...       "resp 0" when it holds every <n>, -3 when not, -902 with FAKE_REFUSE_CHAIN, as an
 *                               omx-clap-host that runs no chain answers it; the fake runs nothing in order (FAKE_LOG
 *                               shows what it was sent)
 *   set_bpm, set_bpb, transport, transport_sync   "resp 0", as mod-host answers them, -902 with FAKE_REFUSE_SETTINGS, as
 *                               omx-clap-host answers them; the fake keeps nothing of them
 *   remote_pages <n>            "resp 2", and remote_page_get <n> <0|1> one page each, -902 for any other page
 *   param_info <n> <sym>        for the symbol 0 the worked vector of the param contract, for the symbol 1 -511 (a parameter
 *                               the worker holds no contract for, as the released omx-clap-host answers every one), -103 for any other
 *   monitor_output <n> <sym>    "resp 1", or "resp 0" for the symbol "none"; from then on, every 20 ms, the feedback port
 *                               carries "output_set <n> <sym> <k>", k counting 0, 1, 2 ... for that output of this
 *                               process: a line lost, doubled or out of order shows as a gap or a repeat in k.
 *                               FAKE_FEEDBACK_BURST sends that many lines per output every 20 ms instead of one, and
 *                               a feedback port no one reads then fills and stops the fake, as it stops a real host
 *
 * Its layout is one CLAP parameter whose default is FAKE_LAYOUT_DEFAULT (0.5 without it); "fake-host -L" prints its
 * layout pin. With FAKE_LOG set, every command received is appended to that file as "<pid> <command>".
 * FAKE_WARN_BEFORE_READY=<n> writes n warning lines to stderr before "ready!", as lilv writes one for every entry of
 * a world that is no bundle (plugin-hostd#105: a world of a few dozen stray files buries the marker under 5 KB).
 */

#include <dirent.h>
#include <getopt.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <sys/time.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <host-errors.h>
#include <mod-host.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>
#include <socket.h>
#include <utils.h>

#include "../src/verbs.h"

#define MAX_INST    10000
#define MAX_PARAMS  32
#define MAX_CONNS   64
#define MAX_OUTPUTS 64

typedef struct INST_T {
    int exists;
    int nostate;
    int synth;
    int full;   /* a synth whose note queue is always full */
    char client[64];
    char name[MAX_PARAMS][64];
    char text[MAX_PARAMS][128];
    int count;
} inst_t;

static char g_expect[MAX_INST][PHD_SHA256_HEX_LEN + 64];

static inst_t g_inst[MAX_INST];
static struct { int inst; char sym[64]; long k; } g_out[MAX_OUTPUTS];
static int g_nout;
static char g_conns[MAX_CONNS][256];
static int g_nconns;
static volatile int running = 1;
static struct timespec g_start;

static long since_start_ms(void)
{
    struct timespec t;

    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - g_start.tv_sec) * 1000 + (t.tv_nsec - g_start.tv_nsec) / 1000000;
}

/* the crashes of this fixture are deliberate: the process is made non-dumpable first, so that they leave no
 * core dump and no coredumpctl entry */
static void crash(void)
{
    prctl(PR_SET_DUMPABLE, 0);
    abort();
}

static void crash_alarm(int sig)
{
    (void)sig;
    crash();
}

static void term_signal(int sig)
{
    (void)sig;
    running = 0;
    socket_finish();
}

static void set_param(inst_t *i, const char *name, const char *text)
{
    int n;

    for (n = 0; n < i->count; n++)
        if (!strcmp(i->name[n], name))
        {
            snprintf(i->text[n], sizeof(i->text[n]), "%s", text);
            return;
        }
    if (i->count < MAX_PARAMS)
    {
        snprintf(i->name[i->count], sizeof(i->name[0]), "%s", name);
        snprintf(i->text[i->count], sizeof(i->text[0]), "%s", text);
        i->count++;
    }
}

static const char *get_param(inst_t *i, const char *name)
{
    int n;

    for (n = 0; n < i->count; n++)
        if (!strcmp(i->name[n], name))
            return i->text[n];
    return NULL;
}

/* the layout pin of this fake's one parameter, as a host computes it from clap_param_info */
static void layout_pin(char *out, size_t size)
{
    const char *def = getenv("FAKE_LAYOUT_DEFAULT");
    phd_layout_clap_param_t param = { 0, "gain", 0.0, 1.0, def ? atof(def) : 0.5, 0 };
    char hex[PHD_SHA256_HEX_LEN + 1];

    phd_layout_clap_digest(&param, 1, hex);
    snprintf(out, size, PHD_PIN_LAYOUT_SCHEME ":%s", hex);
}

static void log_command(const char *line)
{
    const char *path = getenv("FAKE_LOG");
    FILE *f;

    if (!path || !(f = fopen(path, "a")))
        return;
    fprintf(f, "%d %s\n", (int)getpid(), line);
    fclose(f);
}

static void state_path(char *out, size_t size, const char *dir, int n)
{
    snprintf(out, size, "%s/effect_%d.fakestate", dir, n);
}

static void answer(int fd, const char *fmt, ...)
{
    char buffer[2048];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, ap);
    va_end(ap);
    socket_send(fd, buffer, strlen(buffer) + 1);
}

/* the hosting code omx-clap-host's LV2 adapter refuses a plugin with, by a word in its uri: "" for a refusal that
 * names none, NULL for a plugin it takes */
static const char *adapter_refusal(const char *uri)
{
    static const char *const refusal[][2] = {
        { "adapter_midi", "hosting.features.midi-in-fed-empty" },
        { "adapter_missing", "hosting.features.missing" },
        { "adapter_wide", "hosting.topology.wider-than-strip" },
        { "adapter_unrealised", "hosting.no-realisation" },
        { "adapter_nocode", "" },
    };
    size_t n;

    for (n = 0; n < sizeof(refusal) / sizeof(refusal[0]); n++)
        if (strstr(uri, refusal[n][0]))
            return refusal[n][1];
    return NULL;
}

static void receive(msg_t *msg)
{
    char *line = strndup(msg->data, msg->data_size), *copy = strdup(line), *tok[16], *save = NULL, *t;
    int ntok = 0, fd = msg->sender_id, n, k;
    const char *verb;

    log_command(line);
    for (t = strtok_r(copy, " \t\n", &save); t && ntok < 16; t = strtok_r(NULL, " \t\n", &save))
        tok[ntok++] = t;
    if (!ntok)
    {
        answer(fd, "resp -902");
        goto out;
    }
    verb = tok[0];
    n = ntok > 1 ? atoi(tok[1]) : -1;

    if (verb_is(verb, PHD_VERB_PIN_EXPECT) && getenv("FAKE_NO_PIN_EXPECT"))
        answer(fd, "resp -902");
    else if (verb_is(verb, PHD_VERB_PIN_EXPECT) && getenv("FAKE_PIN_EXPECT_HANG"))
        sleep(60);
    else if (verb_is(verb, PHD_VERB_PIN_EXPECT) && ntok == 3 && n >= 0 && n < MAX_INST)
    {
        snprintf(g_expect[n], sizeof(g_expect[n]), "%s", tok[2]);
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, PHD_VERB_PIN_LAYOUT) && getenv("FAKE_NO_PIN_LAYOUT"))
        answer(fd, "resp -902");
    else if (verb_is(verb, PHD_VERB_PIN_LAYOUT) && ntok == 2 && n >= 0 && n < MAX_INST && g_inst[n].exists)
    {
        char mine[PHD_SHA256_HEX_LEN + 64];

        layout_pin(mine, sizeof(mine));
        answer(fd, "resp 0 %s", mine);
    }
    else if (verb_is(verb, EFFECT_ADD) && ntok >= 3)
    {
        int id = atoi(tok[2]);
        char mine[PHD_SHA256_HEX_LEN + 64];

        layout_pin(mine, sizeof(mine));
        /* a plugin that aborts in instantiate on mod-host (a Qt body with no display): the adapter refuses it first */
        if (strstr(tok[1], "crash_on_add") || (strncmp(tok[1], "lv2:", 4) && strstr(tok[1], "abort_on_mod_host")))
            crash();
        if (!strncmp(tok[1], "lv2:", 4) && adapter_refusal(tok[1]))
        {
            /* what omx-clap-host does for a plugin its LV2 adapter cannot run: the code on stderr and after the error */
            const char *code = adapter_refusal(tok[1]);

            fprintf(stderr, "%s: %s\n", tok[1] + 4, *code ? code : "its parameters cannot be read");
            fflush(stderr);
            if (*code)
                answer(fd, "resp %d %s", ERR_HOST_INSTANTIATION, code);
            else
                answer(fd, "resp %d", ERR_HOST_INSTANTIATION);
        }
        else if (!strncmp(tok[1], "lv2:", 4) && strstr(tok[1], "absent"))
        {
            /* and for a uri no bundle on its LV2_PATH holds: the invalid uri, with no code */
            fprintf(stderr, "%s: no bundle on the LV2 path holds it\n", tok[1] + 4);
            fflush(stderr);
            answer(fd, "resp %d", ERR_HOST_INVALID_URI);
        }
        else if (strstr(tok[1], "refuse"))
            answer(fd, "resp -101");
        else if (id >= 0 && id < MAX_INST && g_expect[id][0] && strcmp(g_expect[id], mine))
        {
            g_expect[id][0] = '\0';
            answer(fd, "resp %d", PHD_ERR_PIN_LAYOUT_MISMATCH);
        }
        else if (id < 0 || id >= MAX_INST || g_inst[id].exists)
            answer(fd, "resp -2");
        else
        {
            memset(&g_inst[id], 0, sizeof(inst_t));
            g_inst[id].exists = 1;
            g_expect[id][0] = '\0';
            g_inst[id].nostate = strstr(tok[1], "nostate") != NULL;
            g_inst[id].synth = strstr(tok[1], "synth") != NULL;
            g_inst[id].full = strstr(tok[1], "synth_full") != NULL;
            snprintf(g_inst[id].client, sizeof(g_inst[id].client), "%s", ntok > 3 ? tok[3] : "");
            answer(fd, "resp %d", id);
        }
    }
    else if (verb_is(verb, EFFECT_REMOVE) && ntok == 2)
    {
        if (n == -1)
            memset(g_inst, 0, sizeof(g_inst));
        else if (n >= 0 && n < MAX_INST && g_inst[n].exists)
            g_inst[n].exists = 0;
        else
        {
            answer(fd, "resp -3");
            goto out;
        }
        for (k = 0; k < g_nout; k++)
            if (n == -1 || g_out[k].inst == n)
                g_out[k--] = g_out[--g_nout];
        answer(fd, "resp 0");
    }
    else if (!strcmp(verb, PHD_VERB_CHAIN) && getenv("FAKE_REFUSE_CHAIN"))
        answer(fd, "resp -902");
    else if (!strcmp(verb, PHD_VERB_CHAIN))
    {
        int held = ntok >= 3;

        for (k = 2; k < ntok; k++)
            held &= atoi(tok[k]) >= 0 && atoi(tok[k]) < MAX_INST && g_inst[atoi(tok[k])].exists;
        answer(fd, held ? "resp 0" : "resp -3");
    }
    else if (verb_is(verb, EFFECT_SET_BPM) || verb_is(verb, EFFECT_SET_BPB) || verb_is(verb, TRANSPORT) ||
             verb_is(verb, TRANSPORT_SYNC))
        answer(fd, getenv("FAKE_REFUSE_SETTINGS") ? "resp -902" : "resp 0");
    else if (n >= 0 && n < MAX_INST && !g_inst[n].exists && !verb_is(verb, STATE_SAVE) && !verb_is(verb, STATE_LOAD) &&
             !verb_is(verb, EFFECT_CONNECT) && !verb_is(verb, EFFECT_DISCONNECT) && strcmp(verb, "list_connections") &&
             !verb_is(verb, QUIT))
        answer(fd, "resp -3");
    else if (verb_is(verb, EFFECT_PARAM_SET) && ntok == 4)
    {
        if (!strcmp(tok[2], "hang") && strcmp(tok[3], "0"))
            sleep(60);
        if (!strcmp(tok[2], "crashnow") && atof(tok[3]) != 0.0)
            crash();
        set_param(&g_inst[n], tok[2], tok[3]);
        if (!strcmp(tok[2], "pages_changed") && atof(tok[3]) != 0.0)
        {
            char event[64];

            snprintf(event, sizeof(event), PHD_EVENT_REMOTE_PAGES_CHANGED_FMT, n);
            socket_send_feedback(event);
        }
        if (!strcmp(tok[2], "long_line") && atof(tok[3]) > 0.0)
        {
            size_t size = (size_t)atof(tok[3]);
            char *line = malloc(size + 1), event[64];

            memset(line, 'x', size);
            line[size] = '\0';
            socket_send_feedback(line);
            free(line);
            snprintf(event, sizeof(event), PHD_EVENT_REMOTE_PAGES_CHANGED_FMT, n);
            socket_send_feedback(event);
        }
        if (!strcmp(tok[2], "gesture") && atof(tok[3]) != 0.0)
        {
            char event[128];

            snprintf(event, sizeof(event), PHD_EVENT_PARAM_GESTURE_FMT, n, "0", PHD_GESTURE_BEGIN);
            socket_send_feedback(event);
            snprintf(event, sizeof(event), EFFECT_PARAM_SET, n, "0", tok[3]);
            socket_send_feedback(event);
            snprintf(event, sizeof(event), PHD_EVENT_PARAM_GESTURE_FMT, n, "0", PHD_GESTURE_END);
            socket_send_feedback(event);
            snprintf(event, sizeof(event), PHD_EVENT_REMOTE_PAGE_SUGGEST_FMT, n, 8u);
            socket_send_feedback(event);
        }
        if (!strcmp(tok[2], "hold") && atof(tok[3]) != 0.0)
        {
            char event[128];

            snprintf(event, sizeof(event), PHD_EVENT_PARAM_GESTURE_FMT, n, "0", PHD_GESTURE_BEGIN);
            socket_send_feedback(event);
        }
        if (!strcmp(tok[2], "crash") && atof(tok[3]) != 0.0)
        {
            const char *once = getenv("FAKE_CRASH_ONCE");

            if (once && access(once, F_OK) == 0)
                ;
            else
            {
                const char *after = getenv("FAKE_CRASH_AFTER_MS");
                long ms = after ? atol(after) : 30;
                struct itimerval timer = { { 0, 0 }, { ms / 1000, (ms % 1000) * 1000 } };

                if (once)
                    close(open(once, O_CREAT | O_WRONLY, 0644));
                signal(SIGALRM, crash_alarm);
                setitimer(ITIMER_REAL, &timer, NULL);
            }
        }
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, EFFECT_PARAM_GET) && ntok == 3)
    {
        const char *value = get_param(&g_inst[n], tok[2]);

        if (value)
            answer(fd, "resp 0 %s", value);
        else
            answer(fd, "resp -103");
    }
    else if (verb_is(verb, EFFECT_BYPASS) && ntok == 3)
    {
        set_param(&g_inst[n], ":bypass", tok[2]);
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, EFFECT_PRESET_LOAD) && ntok == 3)
    {
        const char *bypass = get_param(&g_inst[n], ":bypass");
        char keep[128] = "";

        if (bypass)
            snprintf(keep, sizeof(keep), "%s", bypass);
        g_inst[n].count = 0;
        if (keep[0])
            set_param(&g_inst[n], ":bypass", keep);
        set_param(&g_inst[n], "preset", tok[2]);
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, MONITOR_OUTPUT) && ntok == 3)
    {
        int found = !strcmp(tok[2], "none");

        for (k = 0; k < g_nout && !found; k++)
            found = g_out[k].inst == n && !strcmp(g_out[k].sym, tok[2]);
        if (!found && g_nout < MAX_OUTPUTS)
        {
            g_out[g_nout].inst = n;
            snprintf(g_out[g_nout].sym, sizeof(g_out[0].sym), "%s", tok[2]);
            g_out[g_nout++].k = 0;
        }
        answer(fd, "resp %d", strcmp(tok[2], "none") ? 1 : 0);
    }
    else if (!strcmp(verb, PHD_VERB_TRACK_INFO))
        answer(fd, "resp 0");
    else if (!strcmp(verb, PHD_VERB_NOTE_INPUT) && ntok == 2)
        answer(fd, "resp 0 %s", g_inst[n].synth ? "midi_in" : PHD_NO_NOTE_INPUT);
    else if (!strcmp(verb, PHD_VERB_NOTE_ON) || !strcmp(verb, PHD_VERB_NOTE_OFF) || !strcmp(verb, PHD_VERB_ALL_NOTES_OFF))
        answer(fd, "resp %d", !g_inst[n].synth ? PHD_ERR_NO_NOTE_INPUT : g_inst[n].full ? PHD_ERR_NOTE_QUEUE_FULL : 0);
    else if (!strcmp(verb, PHD_VERB_REMOTE_PAGES) && ntok == 2)
        answer(fd, "resp 2");
    else if (!strcmp(verb, PHD_VERB_REMOTE_PAGE_GET) && ntok == 3 && !strcmp(tok[2], "0"))
        answer(fd, "resp 0 7 \"Main\" \"Page \\\"A\\\"\" 0 2 - - - - - -");
    else if (!strcmp(verb, PHD_VERB_REMOTE_PAGE_GET) && ntok == 3 && !strcmp(tok[2], "1"))
        answer(fd, "resp 0 8 \"\" \"Two\" 2 - - - - - - -");
    else if (!strcmp(verb, PHD_VERB_REMOTE_PAGE_GET) && ntok == 3)
        answer(fd, "resp -902");
    else if (!strcmp(verb, PHD_VERB_PRESET_LIST) && ntok == 2)
        answer(fd, "resp 2");
    else if (!strcmp(verb, PHD_VERB_PRESET_GET) && ntok == 3 && !strcmp(tok[2], "0"))
        answer(fd, "resp 0 \"file:///presets/warm.clap-preset\" \"Warm\"");
    else if (!strcmp(verb, PHD_VERB_PRESET_GET) && ntok == 3 && !strcmp(tok[2], "1"))
        answer(fd, "resp 0 urn:fake:bright \"Bright \\\"B\\\"\"");
    else if (!strcmp(verb, PHD_VERB_PRESET_GET) && ntok == 3)
        answer(fd, "resp -902");
    else if (!strcmp(verb, PHD_VERB_PARAM_INFO) && ntok == 3)
        answer(fd, !strcmp(tok[2], "0") ? "resp 0 ms linear 1 2000 350 1 time_ms" : !strcmp(tok[2], "1") ? "resp -511" : "resp -103");
    else if (verb_is(verb, EFFECT_PATCH_SET) && ntok == 4)
    {
        char key[80];

        snprintf(key, sizeof(key), "patch:%s", tok[2]);
        set_param(&g_inst[n], key, tok[3]);
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, STATE_SAVE) && ntok == 2)
    {
        mkdir(tok[1], 0755);
        for (k = 0; k < MAX_INST; k++)
        {
            char path[1024];
            FILE *f;
            int p;

            if (!g_inst[k].exists || g_inst[k].nostate)
                continue;
            state_path(path, sizeof(path), tok[1], k);
            f = fopen(path, "w");
            if (!f)
                continue;
            for (p = 0; p < g_inst[k].count; p++)
                if (g_inst[k].name[p][0] != ':')
                    fprintf(f, "%s %s\n", g_inst[k].name[p], g_inst[k].text[p]);
            fclose(f);
        }
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, STATE_LOAD) && ntok == 2)
    {
        for (k = 0; k < MAX_INST; k++)
        {
            char path[1024], name[64], text[128], bypass[128] = "";
            const char *b;
            FILE *f;

            if (!g_inst[k].exists)
                continue;
            state_path(path, sizeof(path), tok[1], k);
            f = fopen(path, "r");
            if (!f)
                continue;
            b = get_param(&g_inst[k], ":bypass");
            if (b)
                snprintf(bypass, sizeof(bypass), "%s", b);
            g_inst[k].count = 0;
            if (bypass[0])
                set_param(&g_inst[k], ":bypass", bypass);
            while (fscanf(f, "%63s %127s", name, text) == 2)
                set_param(&g_inst[k], name, text);
            fclose(f);
        }
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, EFFECT_CONNECT) && ntok == 3 && getenv("FAKE_CONNECT_AFTER_MS") &&
             since_start_ms() < atol(getenv("FAKE_CONNECT_AFTER_MS")))
        answer(fd, "resp -205");
    else if (verb_is(verb, EFFECT_CONNECT) && ntok == 3)
    {
        if (g_nconns < MAX_CONNS)
            snprintf(g_conns[g_nconns++], sizeof(g_conns[0]), "%s>%s", tok[1], tok[2]);
        answer(fd, "resp 0");
    }
    else if (verb_is(verb, EFFECT_DISCONNECT) && ntok == 3)
    {
        char want[256];

        snprintf(want, sizeof(want), "%s>%s", tok[1], tok[2]);
        for (k = 0; k < g_nconns; k++)
            if (!strcmp(g_conns[k], want))
            {
                memcpy(g_conns[k], g_conns[--g_nconns], sizeof(g_conns[0]));
                break;
            }
        answer(fd, "resp 0");
    }
    else if (!strcmp(verb, "list_connections"))
    {
        char out[2048] = "resp 0";

        for (k = 0; k < g_nconns; k++)
            snprintf(out + strlen(out), sizeof(out) - strlen(out), " %s", g_conns[k]);
        answer(fd, "%s", out);
    }
    else if (verb_is(verb, QUIT))
    {
        answer(fd, "resp 0");
        running = 0;
        socket_finish();
    }
    else
        answer(fd, "resp -902");
out:
    free(copy);
    free(line);
}

/* every monitored output, once a tick (FAKE_FEEDBACK_BURST times), its counter the value */
static void idle(void)
{
    const char *burst = getenv("FAKE_FEEDBACK_BURST");
    int n, times = burst ? atoi(burst) : 1, t;
    char line[256];

    for (n = 0; n < g_nout; n++)
        for (t = 0; t < times; t++)
        {
            snprintf(line, sizeof(line), OUTPUT_SET, g_out[n].inst, g_out[n].sym, (float)g_out[n].k++);
            socket_send_feedback(line);
        }
}

int main(int argc, char **argv)
{
    int opt, port = 5555, fb_port = 0;
    struct sigaction sig;

    clock_gettime(CLOCK_MONOTONIC, &g_start);
    while ((opt = getopt(argc, argv, "np:f:L")) != -1)
        if (opt == 'p')
            port = atoi(optarg);
        else if (opt == 'f')
            fb_port = atoi(optarg);
        else if (opt == 'L')
        {
            char pin[PHD_SHA256_HEX_LEN + 64];

            layout_pin(pin, sizeof(pin));
            printf("%s\n", pin);
            return 0;
        }
    /* the ports a daemon hands a worker were free when it picked them, not when the worker binds: a worker that
     * finds one taken exits before it listens. FAKE_BIND_FAIL_ONCE=<file> is that, once; FAKE_BIND_FAIL_ALWAYS, always */
    if (getenv("FAKE_BIND_FAIL_ALWAYS"))
        return EXIT_FAILURE;
    if (getenv("FAKE_BIND_FAIL_ONCE") && access(getenv("FAKE_BIND_FAIL_ONCE"), F_OK) != 0)
    {
        FILE *mark = fopen(getenv("FAKE_BIND_FAIL_ONCE"), "w");

        if (mark)
            fclose(mark);
        return EXIT_FAILURE;
    }
    if (socket_start(port, fb_port, 4096) < 0)
        return EXIT_FAILURE;
    socket_set_receive_cb(receive);
    socket_set_idle_cb(idle);
    socket_set_idle_interval(20);
    memset(&sig, 0, sizeof(sig));
    sig.sa_handler = term_signal;
    sigemptyset(&sig.sa_mask);
    sigaction(SIGTERM, &sig, NULL);
    if (getenv("FAKE_WARN_BEFORE_READY"))
    {
        int n = atoi(getenv("FAKE_WARN_BEFORE_READY")), i;

        for (i = 0; i < n; i++)
            fprintf(stderr, "load_dir_entry(): warning: Skipping non-directory `/a/world/of/stray/files/entry-%d.c' within path entry\n", i);
        fflush(stderr);
    }
    printf("fake-host ready!\n");
    fflush(stdout);
    while (running)
        socket_run(0);
    socket_finish();
    return 0;
}

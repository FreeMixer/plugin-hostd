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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

#include <host-errors.h>
#include <mod-host.h>
#include <protocol.h>
#include <socket.h>

#include "descriptors.h"
#include "formats.h"
#include "pins.h"
#include "session.h"
#include "supervisor.h"
#include "verbs.h"
#include "words.h"
#include "writer.h"

#define MAX_TOKENS PHD_LINE_WORDS_MAX

volatile int g_quitting;

/* the commands of mod-host.h whose first argument is an instance number: mod-host's grammar, README
 * "<verb> <instance_number>"; tests/verbs_contract.py holds this list to it, and to a format that takes a number first */
static const char *const g_instance_verbs[] = {
    EFFECT_PRESET_LOAD, EFFECT_PRESET_SAVE, EFFECT_BYPASS, EFFECT_PARAM_SET, EFFECT_PARAM_GET,
    EFFECT_PARAM_MON, EFFECT_PATCH_SET, EFFECT_PATCH_GET, EFFECT_LICENSEE, MONITOR_OUTPUT, MIDI_LEARN, MIDI_MAP,
    MIDI_UNMAP, CC_MAP, CC_UNMAP, CC_VALUE_SET, CV_MAP, CV_UNMAP,
};

static int is_instance_verb(const char *verb)
{
    size_t n;

    for (n = 0; n < sizeof(g_instance_verbs) / sizeof(g_instance_verbs[0]); n++)
        if (verb_is(verb, g_instance_verbs[n]))
            return 1;
    return 0;
}

/* the verbs a worker answers by instance, and what the ledger keeps of each */
static const struct { const char *name; int ledger; } g_instance_info_verbs[] = {
#define X(id, name, arguments, reply, ledger, meaning) { name, PHD_LEDGER_##ledger },
    PHD_INSTANCE_VERBS(X)
#undef X
};

static int is_placement(const char *token)
{
    return !strcmp(token, PHD_PLACE_OWN) || !strcmp(token, PHD_PLACE_DEFAULT) ||
           !strncmp(token, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)) ||
           !strncmp(token, PHD_PLACE_CHAIN_PREFIX, strlen(PHD_PLACE_CHAIN_PREFIX));
}

/* pin_set <uri> <files> <layout> [verdict=<word>] [pool=<word>]; the layout of a pin the controller sets is known */
static int pin_set_words(const char *line, char **tok, int ntok)
{
    const char *verdict = NULL, *pool = NULL;

    if (ntok < 4 || ntok > 6 || strlen(line) > PHD_LINE_MAX || !strcmp(tok[3], PHD_PIN_LAYOUT_UNKNOWN))
        return ERR_INVALID_OPERATION;
    if (pins_words(tok + 4, ntok - 4, &verdict, &pool) != SUCCESS)
        return ERR_INVALID_OPERATION;
    return pins_set(tok[1], tok[2], tok[3], verdict, pool);
}

/* a word that is a whole number and nothing else */
static int number(const char *word, int *out)
{
    char *end;
    long v = strtol(word, &end, 10);

    if (!*word || *end || v < -1000000 || v > 1000000)
        return 0;
    *out = (int)v;
    return 1;
}

/* chain <chain> <instance> [<instance> ...]: at least PHD_CHAIN_MEMBERS_MIN members */
static char *chain_words(char **tok, int ntok)
{
    int id, ids[MAX_TOKENS], n;

    if (ntok < 2 + PHD_CHAIN_MEMBERS_MIN || !number(tok[1], &id))
        return sup_resp(ERR_INVALID_OPERATION);
    for (n = 2; n < ntok; n++)
        if (!number(tok[n], &ids[n - 2]))
            return sup_resp(ERR_INVALID_OPERATION);
    return sup_chain(id, ids, ntok - 2);
}

/* plan <chain> <instance> [<instance> ...]: at least PHD_CHAIN_MEMBERS_MIN members */
static char *plan_words(char **tok, int ntok)
{
    int id, ids[MAX_TOKENS], n;

    if (ntok < 2 + PHD_CHAIN_MEMBERS_MIN || !number(tok[1], &id))
        return sup_resp(ERR_INVALID_OPERATION);
    for (n = 2; n < ntok; n++)
        if (!number(tok[n], &ids[n - 2]))
            return sup_resp(ERR_INVALID_OPERATION);
    return sup_plan(id, ids, ntok - 2);
}

/* estimate <rate> <quantum> <uri> [<uri> ...] */
static char *estimate_words(char **tok, int ntok)
{
    int rate, quantum;

    if (ntok < 4 || !number(tok[1], &rate) || !number(tok[2], &quantum))
        return sup_resp(ERR_INVALID_OPERATION);
    return sup_estimate(rate, quantum, (const char *const *)tok + 3, ntok - 3);
}

static void reply(int fd, char *text, const char *tag, size_t tag_len)
{
    char refusal[32];

    /* the session's words on the answer: the error word of a refusal, the request's tag */
    text = session_answer(text, tag, tag_len);

    /* an answer there was no memory for: mod-host's refusal, written on the stack */
    if (!text)
    {
        snprintf(refusal, sizeof(refusal), "resp %d", ERR_MEMORY_ALLOCATION);
        socket_send(fd, refusal, strlen(refusal) + 1);
        return;
    }
    socket_send(fd, text, strlen(text) + 1);
    free(text);
}

static char *handle(char *line, char **tok, int ntok)
{
    const char *verb = tok[0];
    char *reply_text;

    /* hello and request tags are the session's (session.c; plugin-hostd-protocol, doc/protocol.md, Sessions): the daemon
     * answers hello itself and grants tags, errors and seq to its controller, and never relays one to a worker, which
     * is spoken to in mod-host mode. A line that starts with "@" and is no tag of a session granted tags names no verb,
     * as mod-host answers a word that is no verb. */
    if (!strcmp(verb, OMX_VERB_HELLO))
        return ntok < 2 ? strdup(MESSAGE_FEW_ARGUMENTS) : session_hello(tok, ntok);
    if (verb[0] == '@')
        return strdup(MESSAGE_COMMAND_NOT_FOUND);
    /* the bulk verbs: several parameters of one instance, which the worker that holds it answers alone */
    if (!strcmp(verb, OMX_VERB_PARAM_GET_MANY) || !strcmp(verb, OMX_VERB_PARAM_SET_MANY))
        return ntok > 2 ? sup_call(atoi(tok[1]), line) : sup_resp(ERR_INVALID_OPERATION);

    if (!strcmp(verb, PHD_VERB_ADD))
    {
        const char *placement = NULL, *client = NULL;
        int next = 3;

        if (ntok < 3)
            return sup_resp(ERR_INVALID_OPERATION);
        if (ntok > next && is_placement(tok[next]))
            placement = tok[next++];
        if (ntok > next)
            client = tok[next++];
        if (ntok > next)
            return sup_resp(ERR_INVALID_OPERATION);
        reply_text = sup_add(tok[1], atoi(tok[2]), placement, client);
        /* the plugin is running: its files are scanned after the reply, never before it */
        if (reply_text && sup_reply_code(reply_text) >= 0)
            descriptors_add(tok[1]);
        return reply_text;
    }
    if (!strcmp(verb, OMX_VERB_DESCRIPTOR_GET))
        return ntok == 2 ? descriptors_get(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_PANEL_GET))
        return ntok == 2 ? descriptors_panel_get(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (verb_is(verb, EFFECT_REMOVE))
    {
        if (ntok != 2)
            return sup_resp(ERR_INVALID_OPERATION);
        return atoi(tok[1]) == -1 ? sup_remove_all() : sup_remove(atoi(tok[1]));
    }
    if (!strcmp(verb, OMX_VERB_WORKER_LIST))
        return ntok == 1 ? sup_worker_list() : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_INSTANCE_INFO))
        return ntok == 2 ? sup_instance_info(atoi(tok[1])) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_SUPERVISOR_RESET))
    {
        if (ntok > 2)
            return sup_resp(ERR_INVALID_OPERATION);
        return sup_reset(ntok > 1 ? tok[1] : PHD_WORD_ALL);
    }
    if (!strcmp(verb, OMX_VERB_QUARANTINE_CLEAR))
        return ntok == 2 ? sup_quarantine_clear(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_POLICY_SET))
        return ntok == 3 ? sup_policy_set(tok[1], tok[2]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_LV2_WORKER_SET))
        return ntok == 3 ? sup_lv2_worker_set(tok[1], tok[2]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_POOL_CONFIG))
        return ntok == 3 ? sup_pool_config(tok[1], atoi(tok[2])) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_WORKER_ENV))
        return ntok == 4 ? sup_worker_env(tok[1], tok[2], tok[3]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_CHAIN))
        return chain_words(tok, ntok);
    if (!strcmp(verb, OMX_VERB_CHAIN_CLEAR))
    {
        int id;

        return ntok == 2 && number(tok[1], &id) ? sup_chain_clear(id) : sup_resp(ERR_INVALID_OPERATION);
    }
    if (!strcmp(verb, OMX_VERB_CHAIN_GET))
    {
        int id;

        return ntok == 2 && number(tok[1], &id) ? sup_chain_get(id) : sup_resp(ERR_INVALID_OPERATION);
    }
    if (!strcmp(verb, OMX_VERB_PLAN))
        return plan_words(tok, ntok);
    if (!strcmp(verb, OMX_VERB_PLAN_GET))
    {
        int id;

        return ntok == 2 && number(tok[1], &id) ? sup_plan_get(id) : sup_resp(ERR_INVALID_OPERATION);
    }
    if (!strcmp(verb, OMX_VERB_PLAN_CLEAR))
    {
        int id;

        return ntok == 2 && number(tok[1], &id) ? sup_plan_clear(id) : sup_resp(ERR_INVALID_OPERATION);
    }
    if (!strcmp(verb, OMX_VERB_ESTIMATE))
        return estimate_words(tok, ntok);
    if (!strcmp(verb, OMX_VERB_PIN_SET))
        return sup_resp(pin_set_words(line, tok, ntok));
    if (!strcmp(verb, OMX_VERB_PIN_ACCEPT))
        return ntok == 2 ? sup_pin_accept(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_PIN_RELOAD))
        return ntok == 1 ? sup_pin_reload() : sup_resp(ERR_INVALID_OPERATION);
    /* the sync's notice, bare or with the words of the event of the same name: the pin file is read again */
    if (!strcmp(verb, OMX_VERB_PIN_CHANGED))
        return ntok <= 3 ? sup_pin_reload() : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_PIN_CLEAR))
    {
        return sup_resp(ntok == 2 ? pins_clear(tok[1]) : ERR_INVALID_OPERATION);
    }
    if (!strcmp(verb, OMX_VERB_HISTORY_GET))
        return ntok == 2 ? sup_history_get(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_HISTORY_CLEAR))
        return ntok == 2 ? sup_history_clear(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (verb_is(verb, QUIT))
    {
        if (ntok != 1)
            return sup_resp(ERR_INVALID_OPERATION);
        g_quitting = 1;
        return sup_resp(SUCCESS);
    }
    for (size_t n = 0; n < sizeof(g_instance_info_verbs) / sizeof(g_instance_info_verbs[0]); n++)
        if (!strcmp(verb, g_instance_info_verbs[n].name))
            return sup_instance_verb(line, g_instance_info_verbs[n].ledger);
    /* preset_show's forms are told apart by their words as the worker reads them, which these tokens are not */
    if (verb_is(verb, EFFECT_PRESET_SHOW))
        return sup_preset_show(line);
    if (is_instance_verb(verb) && ntok > 1)
        return sup_call(atoi(tok[1]), line);
    if ((verb_is(verb, EFFECT_CONNECT) || verb_is(verb, EFFECT_DISCONNECT)) && ntok == 3)
        return sup_connect(verb, line, tok[1], tok[2]);
    reply_text = sup_broadcast(line);
    sup_host_setting(line, tok, ntok);
    return reply_text;
}

/* ---------------------------------------------------------------- the controller's answers, in order */

/* An answer that waits: the reply of a verb whose writes have not landed (group), or a command that came while one
 * waited, run in its turn (line), or replies refused because too many waited (refusals). A controller reads its answers
 * in the order it sent the commands, so nothing is answered past one that waits. */
typedef struct out
{
    struct out *next;
    int fd, group, refusals, reads;
    char *text, *tag, *line;
    size_t tag_len, size;
} out_t;

#define OUTBOX_MAX 256

static out_t *g_out, *g_out_tail;
static int g_nout;

/* the verbs that read the daemon's own files back: they run once no write of the writer waits, so they never read a
 * file older than one already handed over */
static int reads_files(const char *verb)
{
    return !strcmp(verb, OMX_VERB_PIN_RELOAD) || !strcmp(verb, OMX_VERB_PIN_CHANGED) ||
           !strcmp(verb, OMX_VERB_DESCRIPTOR_GET) || !strcmp(verb, OMX_VERB_PANEL_GET);
}

/* the verbs whose reply says their change is on disk: it goes when the write lands, and says so when it did not */
static int promises_writes(const char *verb)
{
    return !strcmp(verb, OMX_VERB_HISTORY_CLEAR) || !strcmp(verb, OMX_VERB_PIN_SET) ||
           !strcmp(verb, OMX_VERB_PIN_CLEAR) || !strcmp(verb, OMX_VERB_PIN_ACCEPT);
}

static void out_free(out_t *o)
{
    free(o->text);
    free(o->tag);
    free(o->line);
    free(o);
}

static void out_push_front(out_t *o)
{
    o->next = g_out;
    g_out = o;
    if (!g_out_tail)
        g_out_tail = o;
    g_nout++;
}

static void out_push_back(out_t *o)
{
    o->next = NULL;
    if (g_out_tail)
        g_out_tail->next = o;
    else
        g_out = o;
    g_out_tail = o;
    g_nout++;
}

static out_t *out_pop(void)
{
    out_t *o = g_out;

    if (o)
    {
        g_out = o->next;
        if (!g_out)
            g_out_tail = NULL;
        g_nout--;
    }
    return o;
}

/* the line's command, past its tag: its first word, in verb[size] */
static void first_word(const char *data, size_t size, char *verb, size_t vsize)
{
    char line[PHD_LINE_MAX + 1];
    size_t n = size < sizeof(line) - 1 ? size : sizeof(line) - 1, t, w = 0;
    const char *p;

    memcpy(line, data, n);
    line[n] = '\0';
    t = session_tag_len(line);
    p = line + t;
    while (*p == ' ')
        p++;
    while (p[w] && p[w] != ' ' && p[w] != '\n' && p[w] != '\r' && p[w] != '\0' && w < vsize - 1)
        w++;
    memcpy(verb, p, w);
    verb[w] = '\0';
}

static out_t *out_command(int fd, const char *data, size_t size)
{
    out_t *o = calloc(1, sizeof(*o));
    char verb[64];

    if (!o || !(o->line = malloc(size + 1)))
    {
        free(o);
        return NULL;
    }
    memcpy(o->line, data, size);
    o->line[size] = '\0';
    o->size = size;
    o->fd = fd;
    first_word(data, size, verb, sizeof(verb));
    o->reads = reads_files(verb);
    return o;
}

/* one command, run now: answered at once, or the answer that waits for its writes */
static out_t *run(int fd, const char *data, size_t size)
{
    char *line = strndup(data, size), *tok[MAX_TOKENS], *copy, *end, *text;
    const char *tag = NULL, *command;
    size_t tag_len = 0;
    int ntok = 0, group;
    out_t *o = NULL;

    /* a message there is no memory to copy is refused, and not read */
    if (!line)
    {
        reply(fd, NULL, NULL, 0);
        return NULL;
    }
    end = line + strlen(line);
    while (end > line && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' ' || end[-1] == '\t'))
        *--end = '\0';
    /* a session granted tags: a first word "@<tag>" is the request's tag and the command follows it */
    tag_len = session_tag_len(line);
    command = line;
    if (tag_len)
    {
        tag = line;
        command = line + tag_len + (line[tag_len] == ' ');
    }
    copy = strdup(command);
    if (!copy)
    {
        reply(fd, NULL, NULL, 0);
        free(line);
        return NULL;
    }
    /* the words as the protocol reads them: a word in quotes may hold spaces, and the quotes are not its value */
    ntok = words_read(copy, tok, MAX_TOKENS);
    if (ntok < 0)
        reply(fd, NULL, NULL, 0);
    else if (ntok == 0 && tag)
        reply(fd, strdup(MESSAGE_COMMAND_NOT_FOUND), tag, tag_len);
    else if (ntok == 0)
        reply(fd, sup_resp(ERR_INVALID_OPERATION), NULL, 0);
    else
    {
        /* the writes of a verb that promises them are its group: its reply goes when they have landed */
        writer_verb_begin(promises_writes(tok[0]));
        text = handle((char *)command, tok, ntok);
        group = writer_verb_end();
        if (group < 0)
        {
            /* a write the writer had no room for: the verb is refused, and nothing waits for it */
            free(text);
            text = sup_resp(ERR_MEMORY_ALLOCATION);
            group = 0;
        }
        if (group > 0 && text && (o = calloc(1, sizeof(*o))) != NULL &&
            (!tag || (o->tag = strndup(tag, tag_len)) != NULL))
        {
            o->fd = fd;
            o->group = group;
            o->text = text;
            o->tag_len = tag ? tag_len : 0;
        }
        else
        {
            if (o)
            {
                free(o);
                o = NULL;
            }
            if (group > 0)
            {
                /* no memory to hold the answer back: it goes at once, and the group is nobody's */
                writer_forget(group);
            }
            reply(fd, text, tag, tag_len);
            if (ntok > 1 && (verb_is(tok[0], EFFECT_PRESET_LOAD) || verb_is(tok[0], EFFECT_PATCH_SET)))
                sup_after_reply(atoi(tok[1]), tok[0]);
        }
    }
    free(copy);
    free(line);
    return o;
}

void verbs_flush(void)
{
    char refusal[32];
    out_t *o;
    int err;

    while ((o = g_out) != NULL)
    {
        if (o->line)
        {
            out_t *answer;

            if (o->reads && writer_busy())
                return;
            o = out_pop();
            answer = run(o->fd, o->line, o->size);
            out_free(o);
            if (answer)
                out_push_front(answer);
            continue;
        }
        if (o->refusals)
        {
            o = out_pop();
            snprintf(refusal, sizeof(refusal), "resp %d", ERR_MEMORY_ALLOCATION);
            while (o->refusals-- > 0)
                socket_send(o->fd, refusal, strlen(refusal) + 1);
            out_free(o);
            continue;
        }
        if (!writer_group(o->group, &err))
            return;
        o = out_pop();
        /* a write that did not land: a verb that would have succeeded says so, with the code of a refused operation */
        if (err && sup_reply_code(o->text) >= 0)
        {
            free(o->text);
            o->text = sup_resp(ERR_INVALID_OPERATION);
        }
        reply(o->fd, o->text, o->tag, o->tag_len);
        o->text = NULL;
        out_free(o);
    }
}

int verbs_waiting(void)
{
    return g_out != NULL;
}

void verbs_drop(void)
{
    out_t *o;

    while ((o = out_pop()) != NULL)
    {
        if (o->group)
            writer_forget(o->group);
        out_free(o);
    }
}

void verbs_receive(msg_t *msg)
{
    out_t *o;

    /* an answer waits: this command runs in its turn, after it */
    if (g_out)
    {
        if (g_nout >= OUTBOX_MAX || !(o = out_command(msg->sender_id, msg->data, (size_t)msg->data_size)))
        {
            /* too many wait: refused in its place, in order, counted on one entry so the queue stays bounded */
            if (g_out_tail->refusals)
                g_out_tail->refusals++;
            else if ((o = calloc(1, sizeof(*o))) != NULL)
            {
                o->fd = msg->sender_id;
                o->refusals = 1;
                out_push_back(o);
            }
            return;
        }
        out_push_back(o);
        verbs_flush();
        return;
    }
    {
        char verb[64];

        first_word(msg->data, (size_t)msg->data_size, verb, sizeof(verb));
        if (reads_files(verb) && writer_busy())
        {
            if ((o = out_command(msg->sender_id, msg->data, (size_t)msg->data_size)) != NULL)
            {
                out_push_back(o);
                return;
            }
        }
    }
    if ((o = run(msg->sender_id, msg->data, (size_t)msg->data_size)) != NULL)
        out_push_back(o);
}

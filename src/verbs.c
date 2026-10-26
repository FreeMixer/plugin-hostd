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
#include <socket.h>

#include "descriptors.h"
#include "formats.h"
#include "pins.h"
#include "supervisor.h"
#include "verbs.h"

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
           !strncmp(token, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX));
}

/* pin_set <uri> <files> <layout> [verdict=<word>]; the layout of a pin the controller sets is known */
static int pin_set_words(const char *line, char **tok, int ntok)
{
    const char *verdict = NULL;
    size_t key = strlen(PHD_PIN_VERDICT_KEY);
    int rc;

    if ((ntok != 4 && ntok != 5) || strlen(line) > PHD_LINE_MAX || !strcmp(tok[3], PHD_PIN_LAYOUT_UNKNOWN))
        return ERR_INVALID_OPERATION;
    if (ntok == 5)
    {
        if (strncmp(tok[4], PHD_PIN_VERDICT_KEY, key))
            return ERR_INVALID_OPERATION;
        verdict = tok[4] + key;
    }
    rc = pins_set(tok[1], tok[2], tok[3], verdict);
    /* the files of the plugin changed: the adapter may now take one it refused */
    if (rc == SUCCESS)
        lv2_refusals_forget(NULL);
    return rc;
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

static void reply(int fd, char *text)
{
    socket_send(fd, text, strlen(text) + 1);
    free(text);
}

static char *handle(char *line, char **tok, int ntok)
{
    const char *verb = tok[0];
    char *reply_text;

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
    if (!strcmp(verb, OMX_VERB_PIN_SET))
        return sup_resp(pin_set_words(line, tok, ntok));
    if (!strcmp(verb, OMX_VERB_PIN_ACCEPT))
        return ntok == 2 ? sup_pin_accept(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, OMX_VERB_PIN_CLEAR))
    {
        int rc = ntok == 2 ? pins_clear(tok[1]) : ERR_INVALID_OPERATION;

        if (rc == SUCCESS)
            lv2_refusals_forget(NULL);
        return sup_resp(rc);
    }
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
    if (is_instance_verb(verb) && ntok > 1)
        return sup_call(atoi(tok[1]), line);
    if ((verb_is(verb, EFFECT_CONNECT) || verb_is(verb, EFFECT_DISCONNECT)) && ntok == 3)
        return sup_connect(verb, line, tok[1], tok[2]);
    reply_text = sup_broadcast(line);
    sup_host_setting(line, tok, ntok);
    return reply_text;
}

void verbs_receive(msg_t *msg)
{
    char *line = strndup(msg->data, msg->data_size), *tok[MAX_TOKENS], *save = NULL, *t, *copy, *end;
    int ntok = 0;

    end = line + strlen(line);
    while (end > line && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' ' || end[-1] == '\t'))
        *--end = '\0';
    copy = strdup(line);
    for (t = strtok_r(copy, " \t", &save); t && ntok < MAX_TOKENS; t = strtok_r(NULL, " \t", &save))
        tok[ntok++] = t;
    if (ntok == 0)
        reply(msg->sender_id, sup_resp(ERR_INVALID_OPERATION));
    else
    {
        reply(msg->sender_id, handle(line, tok, ntok));
        if (ntok > 1 && (verb_is(tok[0], EFFECT_PRESET_LOAD) || verb_is(tok[0], EFFECT_PATCH_SET)))
            sup_after_reply(atoi(tok[1]), tok[0]);
    }
    free(copy);
    free(line);
}

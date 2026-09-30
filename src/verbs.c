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
#include <socket.h>

#include "pins.h"
#include "supervisor.h"
#include "verbs.h"

#define MAX_TOKENS 64

volatile int g_quitting;

/* the verbs whose first argument is an instance number: mod-host's grammar, README "<verb> <instance_number>";
 * tests/verbs_contract.sh holds this list to it */
static const char *const g_instance_verbs[] = {
    "preset_load", "preset_save", "preset_show", "bypass", "param_set", "param_get", "param_monitor",
    "patch_set", "patch_get", "licensee", "monitor_output", "midi_learn", "midi_map", "midi_unmap",
    "cc_map", "cc_unmap", "cc_value_set", "cv_map", "cv_unmap",
};

static int is_instance_verb(const char *verb)
{
    size_t n;

    for (n = 0; n < sizeof(g_instance_verbs) / sizeof(g_instance_verbs[0]); n++)
        if (!strcmp(verb, g_instance_verbs[n]))
            return 1;
    return 0;
}

static int is_placement(const char *token)
{
    return !strcmp(token, PHD_PLACE_OWN) || !strcmp(token, PHD_PLACE_DEFAULT) ||
           !strncmp(token, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX));
}

static void reply(int fd, char *text)
{
    socket_send(fd, text, strlen(text) + 1);
    free(text);
}

static char *handle(char *line, char **tok, int ntok)
{
    const char *verb = tok[0];

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
        return sup_add(tok[1], atoi(tok[2]), placement, client);
    }
    if (!strcmp(verb, "remove"))
    {
        if (ntok != 2)
            return sup_resp(ERR_INVALID_OPERATION);
        return atoi(tok[1]) == -1 ? sup_remove_all() : sup_remove(atoi(tok[1]));
    }
    if (!strcmp(verb, PHD_VERB_WORKER_LIST))
        return sup_worker_list();
    if (!strcmp(verb, PHD_VERB_INSTANCE_INFO))
        return ntok == 2 ? sup_instance_info(atoi(tok[1])) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_SUPERVISOR_RESET))
        return sup_reset(ntok > 1 ? tok[1] : PHD_WORD_ALL);
    if (!strcmp(verb, PHD_VERB_QUARANTINE_CLEAR))
        return ntok == 2 ? sup_quarantine_clear(tok[1]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_POLICY_SET))
        return ntok == 3 ? sup_policy_set(tok[1], tok[2]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_POOL_CONFIG))
        return ntok == 3 ? sup_pool_config(tok[1], atoi(tok[2])) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_WORKER_ENV))
        return ntok == 4 ? sup_worker_env(tok[1], tok[2], tok[3]) : sup_resp(ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_PIN_SET))
        return sup_resp(ntok == 4 ? pins_set(tok[1], tok[2], tok[3]) : ERR_INVALID_OPERATION);
    if (!strcmp(verb, PHD_VERB_PIN_CLEAR))
        return sup_resp(ntok == 2 ? pins_clear(tok[1]) : ERR_INVALID_OPERATION);
    if (!strcmp(verb, "quit"))
    {
        g_quitting = 1;
        return sup_resp(SUCCESS);
    }
    if (is_instance_verb(verb) && ntok > 1)
        return sup_call(atoi(tok[1]), line);
    if ((!strcmp(verb, "connect") || !strcmp(verb, "disconnect")) && ntok == 3)
        return sup_connect(verb, line, tok[1], tok[2]);
    return sup_broadcast(line);
}

void verbs_receive(msg_t *msg)
{
    char *line = strndup(msg->data, msg->data_size), *tok[MAX_TOKENS], *save = NULL, *t, *copy, *end;
    int ntok = 0;

    end = line + strlen(line);
    while (end > line && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' '))
        *--end = '\0';
    copy = strdup(line);
    for (t = strtok_r(copy, " \t", &save); t && ntok < MAX_TOKENS; t = strtok_r(NULL, " \t", &save))
        tok[ntok++] = t;
    if (ntok == 0)
        reply(msg->sender_id, sup_resp(ERR_INVALID_OPERATION));
    else
    {
        reply(msg->sender_id, handle(line, tok, ntok));
        if (ntok > 1 && (!strcmp(tok[0], "preset_load") || !strcmp(tok[0], "patch_set")))
            sup_after_reply(atoi(tok[1]), tok[0]);
    }
    free(copy);
    free(line);
}

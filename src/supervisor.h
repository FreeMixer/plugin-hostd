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

#ifndef SUPERVISOR_H
#define SUPERVISOR_H

#include <stdint.h>

#include "conf.h"
#include "proc.h"

#define MAX_INSTANCE 10000

/* error codes the supervisor adds to mod-host's, the -5xx hundred */
#define ERR_SUPERVISOR_PLACEMENT_INVALID (-501)
#define ERR_SUPERVISOR_NO_BACKEND        (-502)
#define ERR_SUPERVISOR_WORKER_SPAWN      (-503)
#define ERR_SUPERVISOR_REPLAY            (-504)
#define ERR_SUPERVISOR_GAVE_UP           (-505)
#define ERR_SUPERVISOR_NO_SUCH_WORKER    (-506)
#define ERR_SUPERVISOR_VERB_DROPPED      (-507)

enum { FMT_LV2, FMT_CLAP, FMT_COUNT };
enum { W_UP, W_STARTING, W_BACKOFF, W_GIVEN_UP };

/* what a recorded verb is, for the checkpoint: STATE is what the plugin's own state holds and a checkpoint
 * replaces; HOST is what only the host knows and the ledger always keeps */
enum { KIND_STATE, KIND_HOST };

typedef struct ENTRY_T {
    char *line;
    char *key;
    int kind;
} entry_t;

struct WORKER_T;

typedef struct INSTANCE_T {
    int id;
    int fmt;
    char *uri;                  /* as it goes to a worker, no lv2: prefix */
    char *add_line;             /* the line as it goes to a worker */
    char *client;               /* the jack client the worker makes */
    struct WORKER_T *w;
    entry_t *tail;
    int ntail, captail;
    char **conns;
    int nconns, capconns;
    int dirty;
    int64_t changed_ms;
    int has_ckpt;
} instance_t;

typedef struct WORKER_T {
    int k;
    int fmt;
    pid_t pid;
    int fd;
    int port;
    int state;
    int pool;                   /* 1 when place is a pool */
    char place[48];             /* own | pool:<name> */
    int from_split;             /* an own worker born of a pool that died without a culprit */
    instance_t **inst;
    int ninst, capinst;
    int64_t deaths[64];
    int ndeaths;
    int backoff_ms;
    int64_t next_try_ms;
    char **pend;                /* connects a replay could not make yet: the peer port may not be visible to the new client */
    int npend;
    int64_t pend_until_ms;
} worker_t;

void sup_init(const conf_t *conf);
void sup_finish(void);

/* mod-host's own "resp <code>" text for a refusal; malloc'd */
char *sup_resp(int code);

/* add: `line` is the whole verb, `uri` `id` and the optional placement/client token already parsed */
char *sup_add(const char *uri, int id, const char *placement, const char *client);

/* a command that names one instance; the ledger sees it when it succeeds */
char *sup_call(int id, const char *line);
char *sup_remove(int id);
char *sup_remove_all(void);
char *sup_connect(const char *verb, const char *line, const char *port_a, const char *port_b);
char *sup_broadcast(const char *line);

char *sup_worker_list(void);
char *sup_instance_info(int id);
char *sup_reset(const char *which);
char *sup_quarantine_clear(const char *which);
char *sup_policy_set(const char *format, const char *place);
char *sup_pool_config(const char *name, int max);
char *sup_worker_env(const char *format, const char *cpus, const char *nice);

/* the idle tick: reap the dead, respawn the due, checkpoint the quiet */
void sup_tick(void);

/* after a reply has gone to the controller: checkpoint what a preset or patch just changed */
void sup_after_reply(int id, const char *verb);

int sup_worker_count(void);

#endif

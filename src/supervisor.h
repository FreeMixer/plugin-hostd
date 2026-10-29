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

#ifndef SUPERVISOR_H
#define SUPERVISOR_H

#include <stdint.h>

#include "conf.h"
#include "formats.h"
#include "proc.h"
#include <plugin-hostd/protocol.h>

#define MAX_INSTANCE 10000

enum {
#define X(id, name, meaning) W_##id,
    PHD_WORKER_STATES(X)
#undef X
    W_COUNT
};

/* what a recorded verb is, for the checkpoint: STATE is what the plugin's own state holds and a checkpoint
 * replaces; HOST is what only the host knows and the ledger always keeps */
enum { KIND_STATE, KIND_HOST };

typedef struct ENTRY_T {
    char *line;
    char *key;
    int kind;
} entry_t;

struct WORKER_T;
struct CHAIN_T;

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
    char *sus_line;             /* the last verb it answered and the ledger kept, the suspect of a death that follows soon */
    char *sus_prev;             /* the ledger line that verb replaced, put back when it is dropped */
    int64_t sus_ms;
    int64_t sus_seq;            /* the order of the verbs across instances, which the millisecond clock cannot give */
    int has_ckpt;
    int unreplayed;             /* its pin refused the add of the last replay: the worker does not hold it */
    char *track_info;           /* the latest track_info it took, replayed after its add, never to an LV2 worker */
    struct CHAIN_T *chain;      /* the chain it is a member of, NULL for none */
} instance_t;

typedef struct WORKER_T {
    int k;
    int fmt;
    pid_t pid;
    int fd;
    int port;
    int fb_fd;                  /* its feedback socket, read by the relay */
    int fb_port;
    int state;
    int pool;                   /* 1 when place is a pool */
    int thread_pool;            /* 1 when the process was started with --thread-pool=on (its pin: pool=cores) */
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
    struct CHAIN_T *chain;      /* the chain this worker runs, its members in w->inst in the chain's order */
    int core;                   /* the audio core the placement pinned it to (docs/placement.md), kept across respawns;
                                 * -1 for none */
    /* the running history's window of this worker (src/history.c): what it has used since hist_start_ms */
    pid_t hist_pid;             /* the process the window belongs to, 0 for none */
    int64_t hist_start_ms;
    double hist_cpu0;           /* its CPU seconds when the window began */
    int hist_ninst;             /* its members then: a window in which they changed is not counted */
    int64_t hist_half_ms;       /* the mid-window sample, 0 before it: what a window that ends in a death is counted from */
    double hist_half_cpu;
    long long hist_half_pss_kb;
    /* its xruns (PHD_EVENT_XRUNS): the count the last window ended at, the baseline of the next; the first count a
     * process writes is only that baseline */
    pid_t xr_pid;               /* the process xr_base is of */
    int xr_known;
    unsigned long long xr_base;
} worker_t;

/* the instances a chain verb declared, in order; the ones not quarantined run in its worker */
typedef struct CHAIN_T {
    int id;
    int *ids;
    int n;
    worker_t *w;                /* NULL while no worker holds it */
    int rejoin;                 /* its members are to be gathered in one worker again, by the tick */
    int planned;                /* a segment of a plan, not a chain the controller declared: id is the plan's number, seg the
                                 * segment's place in the plan, and no g_chain row holds it */
    int seg;
} chain_t;

void sup_init(const conf_t *conf);
/* placement spread: the audio cores, and every thread of the daemon on the reserved ones; 0, or -1 with the reason on
 * stderr for an audio_cores outside the daemon's cpus */
int sup_placement_init(void);
/* this daemon's own directory under state_root: its checkpoints and the logs of its workers and scans */
const char *sup_root(void);
void sup_finish(void);

/* mod-host's own "resp <code>" text for a refusal; malloc'd */
char *sup_resp(int code);
/* the code of a "resp <code> ..." reply */
int sup_reply_code(const char *reply);

/* add: `line` is the whole verb, `uri` `id` and the optional placement/client token already parsed */
char *sup_add(const char *uri, int id, const char *placement, const char *client);

/* a command that names one instance; the ledger sees it when it succeeds */
char *sup_call(int id, const char *line);
char *sup_remove(int id);
char *sup_remove_all(void);
char *sup_connect(const char *verb, const char *line, const char *port_a, const char *port_b);
char *sup_broadcast(const char *line);
/* a command every worker shares: kept when it is one of PHD_HOST_SETTINGS and its words are its grammar */
void sup_host_setting(const char *line, char **tok, int ntok);
/* a verb of PHD_INSTANCE_VERBS: routed to a CLAP worker, answered here for an LV2 instance */
char *sup_instance_verb(const char *line, int ledger);

char *sup_worker_list(void);
char *sup_instance_info(int id);
char *sup_reset(const char *which);
char *sup_quarantine_clear(const char *which);
char *sup_policy_set(const char *format, const char *place);
/* pin_accept: the plugin's files as they are now become its pin; only under pin_mode first-use */
char *sup_pin_accept(const char *uri);
char *sup_pool_config(const char *name, int max);
/* lv2_worker_set: the worker of one LV2 plugin, for its adds from now on */
char *sup_lv2_worker_set(const char *uri, const char *worker);
char *sup_worker_env(const char *format, const char *cpus, const char *nice);
/* chain: the instances ids, in order, are one chain run in one worker; chain_clear gives each a worker of its own */
char *sup_chain(int id, const int *ids, int n);
char *sup_chain_clear(int id);
/* chain_get: the chain's worker, its members as declared and the ones its worker runs, each in order */
char *sup_chain_get(int id);
/* plan: the instances ids, in signal order, planned into segments (src/planner.c); applied as chains of place
 * chain:<id>.<k> and workers of their own while grouping is on, answered and kept while it is off. plan_get reads the
 * last plan back, plan_clear gives each member a worker of its own */
char *sup_plan(int id, const int *ids, int n);
char *sup_plan_get(int id);
char *sup_plan_clear(int id);

/* estimate: what the n plugins, in signal order, would cost at the rate and quantum, from the qualification records and
 * the history, and how many workers plan would place them in; nothing is loaded and nothing moves */
char *sup_estimate(int rate, int quantum, const char *const *uris, int n);

/* history_get: the summary of the binary the uri's pin holds, on this host class (src/history.c); history_clear: the
 * lines of one uri or all of them. Both answer as the verbs do */
char *sup_history_get(const char *uri);
char *sup_history_clear(const char *uri);

/* the idle tick: reap the dead, respawn the due, checkpoint the quiet */
void sup_tick(void);

/* after a reply has gone to the controller: checkpoint what a preset or patch just changed */
void sup_after_reply(int id, const char *verb);

int sup_worker_count(void);

#endif

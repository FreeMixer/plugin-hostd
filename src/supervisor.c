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

#include <ctype.h>
#include <dirent.h>
#include <ftw.h>
#include <limits.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <host-errors.h>
#include <mod-host.h>
#include <plugin-hostd/pin.h>
#include <utils.h>

/* mod-host's pseudo port of the host's own bypass, which param_info names no parameter */

#include "history.h"
#include "pins.h"
#include "placement.h"
#include "planner.h"
#include "qualcost.h"
#include "relay.h"
#include "supervisor.h"
#include "verbs.h"

#define ATTRIBUTED  (-2)    /* on_death: the culprit is already dealt with, only schedule */
#define POOL_NAMES  32
#define CONNECT_RETRY_MS PHD_CONNECT_RETRY_MS
#define PIN_REFUSED (-3)    /* replay_pin: the pin refused the add, the worker is alive */

typedef struct META_T {
    int crashes;
    int quarantined;
    int64_t deaths[64];
    int ndeaths;
} meta_t;

typedef struct POOLCFG_T {
    char name[40];
    int max;
} poolcfg_t;

static conf_t g_conf;
static worker_t **g_workers;
static int g_nworkers, g_capworkers, g_next_k = 1;
static instance_t *g_inst[MAX_INSTANCE];
/* zero pages until an instance touches its entry, and nothing that can run out */
static meta_t g_meta[MAX_INSTANCE];
static char g_root[PATH_MAX], g_ckpt[PATH_MAX];
static char g_policy[FORMATS_MAX][48];
static poolcfg_t g_pools[POOL_NAMES];
static int g_npools;
static worker_env_t g_env[FORMATS_MAX];
static chain_t *g_chain[MAX_INSTANCE];
static int g_nchains;
/* the audio cores in order, while placement spread found any (docs/placement.md): a new worker is pinned to one */
static int g_cores[CPU_SETSIZE];
static int g_ncores;

/* what plan last answered for a chain: its segments, and the chain of each segment of two or more that runs */
typedef struct PLAN_T {
    int id;
    int n;
    int *ids;                   /* the members, in the order plan was given them */
    chain_t **seg;              /* the segments of two or more members that run, in plan order */
    int nseg;
    char *segments;             /* plan's answer after resp 0 */
    char *reasons;              /* plan_get's second word */
    int replan;                 /* a member was quarantined: the tick plans it again */
    int64_t regroup_ms;         /* when a plan whose group a death split is made again, 0 for never */
} plan_t;
static plan_t *g_plan[MAX_INSTANCE];
static int g_nplans;

static int chain_form(chain_t *c);
static void chain_refused(chain_t *c);
static int plan_worker_refused(plan_t *p);
static void plans_replan_for(int id);
static void plans_regroup(int id, int64_t now, int arm);
static void plan_again(int id);
static const char *record_id(const char *uri);

/* a chain as the controller names it: the number chain declared, or <plan>.<k> for segment k of a plan */
static void chain_word(const chain_t *c, char *word, size_t size)
{
    if (c->planned)
        snprintf(word, size, "%d" PHD_PLACE_PLAN_SEPARATOR "%d", c->id, c->seg);
    else
        snprintf(word, size, "%d", c->id);
}

static const char *const g_state_states[W_COUNT] = {
#define X(id, name, meaning) name,
    PHD_WORKER_STATES(X)
#undef X
};

/* the instance verbs the ledger keeps; the key compacts repeats of the same setting */
/* the instance commands of mod-host.h the ledger keeps; the key compacts repeats of the same setting */
static const struct { const char *format; int kind; int key_arg; } g_recorded[] = {
    { EFFECT_PARAM_SET, KIND_STATE, 2 },
    { EFFECT_PATCH_SET, KIND_STATE, 2 },
    { EFFECT_PRESET_LOAD, KIND_STATE, 0 },
    { EFFECT_BYPASS, KIND_HOST, 1 },
    { EFFECT_PARAM_MON, KIND_HOST, 0 },
    { MONITOR_OUTPUT, KIND_HOST, 2 },
    { MIDI_LEARN, KIND_HOST, 0 },
    { MIDI_MAP, KIND_HOST, 0 },
    { MIDI_UNMAP, KIND_HOST, 0 },
    { CC_MAP, KIND_HOST, 0 },
    { CC_UNMAP, KIND_HOST, 0 },
    { CC_VALUE_SET, KIND_HOST, 0 },
    { CV_MAP, KIND_HOST, 0 },
    { CV_UNMAP, KIND_HOST, 0 },
};

/* the commands every worker shares that the daemon keeps (PHD_HOST_SETTINGS), and the latest line of each, in the order
 * they were last sent: a transport line after a set_bpm wins over it, and a set_bpm after that wins again */
static const char *const g_host_setting_verbs[] = { EFFECT_SET_BPM, EFFECT_SET_BPB, TRANSPORT, TRANSPORT_SYNC };
#define HOST_SETTINGS (sizeof(g_host_setting_verbs) / sizeof(g_host_setting_verbs[0]))
static char *g_host_settings[HOST_SETTINGS];
static int g_nhost_settings;

static void event(const char *fmt, ...)
{
    char line[1024];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    relay_event(line);
}

char *sup_resp(int code)
{
    char buffer[32];

    snprintf(buffer, sizeof(buffer), "resp %d", code);
    return strdup(buffer);
}

static int resp_code(const char *reply)
{
    /* an answer there was no memory for is the refusal the controller is given for it */
    if (!reply)
        return ERR_MEMORY_ALLOCATION;
    return strncmp(reply, "resp ", 5) == 0 ? atoi(reply + 5) : -999;
}

int sup_reply_code(const char *reply)
{
    return resp_code(reply);
}

static meta_t *meta_of(int id)
{
    return &g_meta[id];
}

static int recent(int64_t *deaths, int *n, int64_t now)
{
    int i, kept = 0;

    for (i = 0; i < *n; i++)
        if (now - deaths[i] < g_conf.storm_window_ms)
            deaths[kept++] = deaths[i];
    *n = kept;
    return kept;
}

static void note_death(int64_t *deaths, int *n, int64_t now)
{
    recent(deaths, n, now);
    if (*n >= 64)
        memmove(deaths, deaths + 1, 63 * sizeof(*deaths)), *n = 63;
    deaths[(*n)++] = now;
}

static int valid_place(const char *place)
{
    return !strcmp(place, PHD_PLACE_OWN) ||
           (!strncmp(place, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)) &&
            phd_pool_name_valid(place + strlen(PHD_PLACE_POOL_PREFIX)));
}

/* ---------------------------------------------------------------- ledger */

/* *replaced is the line a keyed entry gave up, NULL when the entry is new; the caller owns it. -1, the ledger as it was,
 * when memory runs out */
static int tail_add(instance_t *i, const char *line, const char *key, int kind, char **replaced)
{
    char *copy = strdup(line), *key_copy;
    int n;

    *replaced = NULL;
    if (!copy)
        return -1;
    if (key)
        for (n = 0; n < i->ntail; n++)
            if (i->tail[n].key && !strcmp(i->tail[n].key, key))
            {
                *replaced = i->tail[n].line;
                i->tail[n].line = copy;
                return 0;
            }
    key_copy = key ? strdup(key) : NULL;
    if (key && !key_copy)
    {
        free(copy);
        return -1;
    }
    if (i->ntail == i->captail)
    {
        int cap = i->captail ? i->captail * 2 : 16;
        entry_t *grown = realloc(i->tail, cap * sizeof(entry_t));

        if (!grown)
        {
            free(copy);
            free(key_copy);
            return -1;
        }
        i->tail = grown;
        i->captail = cap;
    }
    i->tail[i->ntail].line = copy;
    i->tail[i->ntail].key = key_copy;
    i->tail[i->ntail].kind = kind;
    i->ntail++;
    return 0;
}

static void tail_drop_state(instance_t *i)
{
    int n, kept = 0;

    for (n = 0; n < i->ntail; n++)
    {
        if (i->tail[n].kind == KIND_STATE)
        {
            free(i->tail[n].line);
            free(i->tail[n].key);
        }
        else
            i->tail[kept++] = i->tail[n];
    }
    i->ntail = kept;
}

/* 0, or -1 with the list as it was when memory runs out */
static int conn_add(instance_t *i, const char *line)
{
    char *copy;
    int n;

    for (n = 0; n < i->nconns; n++)
        if (!strcmp(i->conns[n], line))
            return 0;
    copy = strdup(line);
    if (!copy)
        return -1;
    if (i->nconns == i->capconns)
    {
        int cap = i->capconns ? i->capconns * 2 : 8;
        char **grown = realloc(i->conns, cap * sizeof(char *));

        if (!grown)
        {
            free(copy);
            return -1;
        }
        i->conns = grown;
        i->capconns = cap;
    }
    i->conns[i->nconns++] = copy;
    return 0;
}

static void conn_del(instance_t *i, const char *line)
{
    int n;

    for (n = 0; n < i->nconns; n++)
        if (!strcmp(i->conns[n], line))
        {
            free(i->conns[n]);
            i->conns[n] = i->conns[--i->nconns];
            return;
        }
}

static void instance_free(instance_t *i)
{
    int n;

    for (n = 0; n < i->ntail; n++)
    {
        free(i->tail[n].line);
        free(i->tail[n].key);
    }
    for (n = 0; n < i->nconns; n++)
        free(i->conns[n]);
    free(i->tail);
    free(i->conns);
    free(i->uri);
    free(i->add_line);
    free(i->client);
    free(i->sus_line);
    free(i->sus_prev);
    free(i->track_info);
    free(i);
}

/* whether an entry of the checkpoint directory is instance id's: effect_<id>, or effect_<id>.<anything> */
static int ckpt_entry_of(const char *name, int id)
{
    char prefix[32];
    size_t n = snprintf(prefix, sizeof(prefix), "effect_%d", id);

    return !strncmp(name, prefix, n) && (name[n] == '\0' || name[n] == '.');
}

static int ckpt_exists(int id)
{
    DIR *dir = opendir(g_ckpt);
    struct dirent *entry;
    int found = 0;

    if (!dir)
        return 0;
    while (!found && (entry = readdir(dir)))
        found = ckpt_entry_of(entry->d_name, id);
    closedir(dir);
    return found;
}

static int rm_entry(const char *path, const struct stat *sb, int flag, struct FTW *ftw)
{
    (void)sb; (void)flag; (void)ftw;
    return remove(path);
}

static void rm_tree(const char *path)
{
    nftw(path, rm_entry, 16, FTW_DEPTH | FTW_PHYS);
}

static void ckpt_forget(int id)
{
    char path[PATH_MAX];
    DIR *dir = opendir(g_ckpt);
    struct dirent *entry;

    if (!dir)
        return;
    while ((entry = readdir(dir)))
        if (ckpt_entry_of(entry->d_name, id))
        {
            snprintf(path, sizeof(path), "%s/%s", g_ckpt, entry->d_name);
            rm_tree(path);
        }
    closedir(dir);
}

/* the checkpoint of one instance alone, linked into dir (under the daemon's own directory): a state_load of dir loads
 * that instance and touches no other the worker holds. 0 when the instance has no checkpoint */
static int ckpt_alone(int id, char *dir, size_t size)
{
    char from[PATH_MAX], to[PATH_MAX];
    DIR *ckpt = opendir(g_ckpt);
    struct dirent *entry;
    int found = 0;

    snprintf(dir, size, "%s/alone-%d", g_root, id);
    rm_tree(dir);
    if (!ckpt)
        return 0;
    if (mkdir(dir, 0700) == 0)
        while ((entry = readdir(ckpt)))
            if (ckpt_entry_of(entry->d_name, id))
            {
                snprintf(from, sizeof(from), "%s/%s", g_ckpt, entry->d_name);
                snprintf(to, sizeof(to), "%s/%s", dir, entry->d_name);
                found |= symlink(from, to) == 0;
            }
    closedir(ckpt);
    if (!found)
        rm_tree(dir);
    return found;
}

/* ---------------------------------------------------------------- workers */

/* room for `n` members; 0, or -1 with the worker as it was when memory runs out */
static int worker_reserve(worker_t *w, int n)
{
    instance_t **grown;
    int cap = w->capinst ? w->capinst : 8;

    if (n <= w->capinst)
        return 0;
    while (cap < n)
        cap *= 2;
    grown = realloc(w->inst, cap * sizeof(instance_t *));
    if (!grown)
        return -1;
    w->inst = grown;
    w->capinst = cap;
    return 0;
}

/* a worker with room for its first member and a row in the table to take, not yet a worker of the daemon: what a move
 * asks for before it takes an instance out of the worker it runs in. NULL when memory runs out */
static worker_t *worker_alloc(int fmt, const char *place)
{
    worker_t *w = calloc(1, sizeof(worker_t));

    if (!w)
        return NULL;
    if (worker_reserve(w, 1) != 0)
    {
        free(w);
        return NULL;
    }
    if (g_nworkers == g_capworkers)
    {
        int cap = g_capworkers ? g_capworkers * 2 : 16;
        worker_t **grown = realloc(g_workers, cap * sizeof(worker_t *));

        if (!grown)
        {
            free(w->inst);
            free(w);
            return NULL;
        }
        g_workers = grown;
        g_capworkers = cap;
    }
    w->fmt = fmt;
    w->fd = -1;
    w->fb_fd = -1;
    w->state = W_BACKOFF;
    w->core = -1;
    snprintf(w->place, sizeof(w->place), "%s", place);
    w->pool = strncmp(place, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)) == 0;
    return w;
}

/* the worker worker_alloc made joins the daemon's; the room for it is there, unless another joined since */
static int worker_join(worker_t *w)
{
    if (g_nworkers == g_capworkers)
    {
        int cap = g_capworkers ? g_capworkers * 2 : 16;
        worker_t **grown = realloc(g_workers, cap * sizeof(worker_t *));

        if (!grown)
            return -1;
        g_workers = grown;
        g_capworkers = cap;
    }
    w->k = g_next_k++;
    g_workers[g_nworkers++] = w;
    return 0;
}

static void worker_unused(worker_t *w)
{
    free(w->inst);
    free(w);
}

static worker_t *worker_new(int fmt, const char *place)
{
    worker_t *w = worker_alloc(fmt, place);

    if (w && worker_join(w) != 0)
    {
        worker_unused(w);
        return NULL;
    }
    return w;
}

/* the room is there: worker_new gave a worker room for one, and worker_reserve made it for more */
static void worker_attach(worker_t *w, instance_t *i)
{
    w->inst[w->ninst++] = i;
    i->w = w;
}

static void worker_detach(worker_t *w, instance_t *i)
{
    int n;

    /* the order is kept: a chain's worker holds its members in the chain's order */
    for (n = 0; n < w->ninst; n++)
        if (w->inst[n] == i)
        {
            memmove(&w->inst[n], &w->inst[n + 1], (w->ninst - n - 1) * sizeof(instance_t *));
            w->ninst--;
            break;
        }
    i->w = NULL;
}

static void worker_free(worker_t *w)
{
    int n;
    char path[PATH_MAX];

    for (n = 0; n < g_nworkers; n++)
        if (g_workers[n] == w)
        {
            g_workers[n] = g_workers[--g_nworkers];
            break;
        }
    if (w->chain && w->chain->w == w)
        w->chain->w = NULL;
    snprintf(path, sizeof(path), "%s/world-w%d", g_root, w->k);
    rm_tree(path);
    snprintf(path, sizeof(path), "%s/w%d.log", g_root, w->k);
    unlink(path);
    if (w->fd >= 0)
        close(w->fd);
    relay_remove(w->fb_fd);
    for (n = 0; n < w->npend; n++)
        free(w->pend[n]);
    free(w->pend);
    free(w->inst);
    free(w);
}

/* stop the process behind a worker and drop the worker; its instances must already be gone or moved */
static void worker_retire(worker_t *w)
{
    if (w->pid > 0)
        proc_stop(w->pid);
    w->pid = 0;
    worker_free(w);
}

static const char *bin_of(int fmt)
{
    return format_at(fmt)->worker(&g_conf);
}

/* where the plugins of a format are searched, NULL for nowhere */
static const char *search_of(int fmt)
{
    const format_t *f = format_at(fmt);

    return f->search ? f->search(&g_conf) : NULL;
}

/* the uris of a chain's members of the worker's own row that run in it, in order (a CLAP member of an adapter-row
 * chain is found by its path, not in the world); malloc'd, *n of them */
static const char **chain_uris(const worker_t *w, int *n)
{
    const char **uris = malloc((w->ninst ? w->ninst : 1) * sizeof(char *));
    int k;

    *n = 0;
    if (!uris)
        return NULL;
    for (k = 0; k < w->ninst; k++)
        if (w->inst[k]->fmt == w->fmt)
            uris[(*n)++] = w->inst[k]->uri;
    return uris;
}

/* whether one chain's worker runs members of rows a and b: one row, or two rows of one worker program that both run
 * chains in one client (clap and lv2-clap, both omx-clap-host) */
static int chain_rows_together(int a, int b)
{
    const char *pa = bin_of(a), *pb = bin_of(b);

    return a == b || (format_at(a)->native_chain && format_at(b)->native_chain && pa && pb && !strcmp(pa, pb));
}

/* the row of a chain's worker: the first member's row that narrows its world (the LV2 members' world is the one to
 * build), else the first member's */
static int chain_row_of(const int *ids, int n)
{
    int k;

    for (k = 0; k < n; k++)
        if (g_inst[ids[k]] && format_at(g_inst[ids[k]]->fmt)->narrow_world)
            return g_inst[ids[k]]->fmt;
    for (k = 0; k < n; k++)
        if (g_inst[ids[k]])
            return g_inst[ids[k]]->fmt;
    return 0;
}

/* a format that can narrow its worker's world gives an own worker the world of the one plugin and a chain's worker the
 * union of its members'; a pool, and a plugin the format cannot find, gets the whole search path */
static char *narrow_world(worker_t *w, const char *uri)
{
    const format_t *f = format_at(w->fmt);
    char dir[PATH_MAX], *world;
    const char **uris;
    int n;

    if (!f->narrow_world)
        return NULL;
    snprintf(dir, sizeof(dir), "%s/world-w%d", g_root, w->k);
    if (w->chain && w->ninst)
    {
        uris = chain_uris(w, &n);
        if (!uris)
            return NULL;
        world = f->narrow_world(&g_conf, dir, uris, n);
        free(uris);
        return world;
    }
    if (w->pool || !uri)
        return NULL;
    return f->narrow_world(&g_conf, dir, &uri, 1);
}

/* how many times one start asks for ports before it is a failed spawn */
#define SPAWN_ATTEMPTS 3

static int replay_line_code(worker_t *w, const char *line, int *code);

/* whether the words of a line are the grammar of a mod-host format: as many, a %i a whole number, a %f a number */
static int format_words(const char *format, char **tok, int ntok)
{
    char *copy = strdup(format), *save = NULL, *t;
    int n = 0, ok = 1;

    if (!copy)
        return 0;
    for (t = strtok_r(copy, " ", &save); t && ok; t = strtok_r(NULL, " ", &save), n++)
    {
        char *end;

        if (n >= ntok)
            ok = 0;
        else if (!strcmp(t, "%i"))
            ok = (strtol(tok[n], &end, 10), *tok[n] && !*end);
        else if (!strcmp(t, "%f"))
            ok = (strtod(tok[n], &end), *tok[n] && !*end);
    }
    free(copy);
    return ok && n == ntok;
}

void sup_host_setting(const char *line, char **tok, int ntok)
{
    size_t v;
    char *copy;
    int n;

    for (v = 0; v < HOST_SETTINGS; v++)
        if (verb_is(tok[0], g_host_setting_verbs[v]))
            break;
    if (v == HOST_SETTINGS || !format_words(g_host_setting_verbs[v], tok, ntok))
        return;
    copy = strdup(line);
    if (!copy)
    {
        fprintf(stderr, "plugin-hostd: out of memory, a worker started from now on will not be handed: %s\n", line);
        return;
    }
    for (n = 0; n < g_nhost_settings; n++)
        if (verb_is(g_host_settings[n], g_host_setting_verbs[v]))
        {
            free(g_host_settings[n]);
            memmove(&g_host_settings[n], &g_host_settings[n + 1], (g_nhost_settings - n - 1) * sizeof(char *));
            g_nhost_settings--;
            break;
        }
    if (g_nhost_settings < (int)HOST_SETTINGS)
        g_host_settings[g_nhost_settings++] = copy;
    else
        free(copy);
}

/* a worker that just started is handed the host settings before anything else; its refusal of one is only written */
static int host_settings_replay(worker_t *w)
{
    int n, code;

    for (n = 0; n < g_nhost_settings; n++)
        if (replay_line_code(w, g_host_settings[n], &code) != RPC_OK)
            return -1;
    return 0;
}

/* ---------------------------------------------------------------- core placement (docs/placement.md) */

/* the cost of a plugin as the planner reads it, its qualification record's at group_rate and group_quantum: a fraction
 * of one core, below 0 for none */
static double place_cost(const char *uri)
{
    if (g_conf.group_rate <= 0 || g_conf.group_quantum <= 0)
        return -1;
    return qualcost_read(g_conf.qualification_dir, record_id(uri), g_conf.group_rate, g_conf.group_quantum);
}

/* what a worker costs, the sum of its members' costs, and in *known whether every member has one */
static double worker_cost(const worker_t *w, int *known)
{
    double sum = 0, c;
    int m;

    *known = 1;
    for (m = 0; m < w->ninst; m++)
    {
        c = place_cost(w->inst[m]->uri);
        if (c < 0)
            *known = 0;
        else
            sum += c;
    }
    return sum;
}

/* the audio core of a new worker: the least loaded by the workers already placed (src/placement.c) */
static int place_core(const worker_t *w)
{
    static placement_load_t load[CPU_SETSIZE];
    int n, k, known;

    for (k = 0; k < g_ncores; k++)
    {
        load[k].core = g_cores[k];
        load[k].workers = load[k].unknown = 0;
        load[k].cost = 0;
    }
    for (n = 0; n < g_nworkers; n++)
    {
        const worker_t *v = g_workers[n];

        if (v == w || v->core < 0)
            continue;
        for (k = 0; k < g_ncores && g_cores[k] != v->core; k++)
            ;
        if (k == g_ncores)
            continue;
        load[k].workers++;
        load[k].cost += worker_cost(v, &known);
        load[k].unknown += !known;
    }
    return g_cores[placement_pick(load, g_ncores)];
}

/* every thread of the daemon on the set; the processes it forks from now on inherit it */
static void pin_self(const cpu_set_t *set)
{
    DIR *dir = opendir("/proc/self/task");
    struct dirent *e;

    if (!dir)
    {
        sched_setaffinity(0, sizeof(*set), set);
        return;
    }
    while ((e = readdir(dir)))
        if (e->d_name[0] >= '0' && e->d_name[0] <= '9')
            sched_setaffinity((pid_t)atoi(e->d_name), sizeof(*set), set);
    closedir(dir);
}

int sup_placement_init(void)
{
    cpu_set_t allowed, audio, reserved;
    char a[512], r[512];
    int c;

    g_ncores = 0;
    if (!conf_spread(&g_conf))
        return 0;
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0)
    {
        perror("placement spread: sched_getaffinity");
        return -1;
    }
    if (placement_cores(&allowed, g_conf.audio_cores, &audio, &reserved) != 0)
    {
        placement_list_text(&allowed, a, sizeof(a));
        fprintf(stderr, "audio_cores '%s' is not a cpu list inside the cpus the daemon may run on, %s\n", g_conf.audio_cores, a);
        return -1;
    }
    for (c = 0; c < CPU_SETSIZE; c++)
        if (CPU_ISSET(c, &audio))
            g_cores[g_ncores++] = c;
    placement_list_text(&audio, a, sizeof(a));
    placement_list_text(&reserved, r, sizeof(r));
    if (!g_ncores)
        fprintf(stderr, "placement spread: the daemon may run on one cpu, %s, and no audio core is left: nothing is pinned\n", r);
    else if (!CPU_COUNT(&reserved))
        fprintf(stderr, "placement spread: workers on the audio cores %s; no cpu is left for the daemon, which is not pinned\n", a);
    else
    {
        pin_self(&reserved);
        fprintf(stderr, "placement spread: workers on the audio cores %s, the daemon on %s\n", a, r);
    }
    return 0;
}

static int worker_start(worker_t *w, const char *uri)
{
    char logfile[PATH_MAX];
    char *world;
    int rc, attempt;
    worker_env_t env = g_env[w->fmt];

    if (!proc_have_binary(bin_of(w->fmt)))
        return OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND_RESP;
    snprintf(logfile, sizeof(logfile), "%s/w%d.log", g_root, w->k);
    world = narrow_world(w, uri);
    w->state = W_STARTING;
    /* the CLAP thread pool is granted by the plugin's qualification, in its pin, and only to a worker that holds that
     * plugin alone: a worker of a pool or a chain keeps the option away, and so does a plugin with no word */
    w->thread_pool = g_conf.require_pins && format_at(w->fmt)->thread_pool && !w->pool && !w->chain && uri &&
                     pins_pool_cores(uri);
    env.thread_pool = w->thread_pool;
    /* the policy pins a worker whose format worker_env gave no cpus: to the core it has, which a respawn keeps, or to the
     * least-loaded one; the child is pinned before it runs the worker, so every thread it makes is there too */
    if (g_ncores && !env.cpus[0])
    {
        if (w->core < 0)
            w->core = place_core(w);
        snprintf(env.cpus, sizeof(env.cpus), "%d", w->core);
    }
    else
        w->core = -1;
    for (attempt = 0;; attempt++)
    {
        rc = proc_spawn(&g_conf, bin_of(w->fmt), format_at(w->fmt)->world_env, world ? world : search_of(w->fmt),
                        &env, logfile, &w->pid, &w->port, &w->fb_port);
        if (rc != 0)
        {
            free(world);
            w->pid = 0;
            return OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP;
        }
        w->fd = proc_connect(&g_conf, w->pid, w->port, w->fb_port, logfile, &w->fb_fd);
        /* a worker that was gone before it listened lost the race for its ports: ask for fresh ones, a bounded few times */
        if (w->fd != PROC_EXITED || attempt + 1 >= SPAWN_ATTEMPTS)
            break;
        w->pid = 0;
    }
    free(world);
    if (w->fd < 0)
    {
        proc_stop(w->pid);
        w->pid = 0;
        return OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP;
    }
    if (host_settings_replay(w) != 0)
    {
        close(w->fd);
        close(w->fb_fd);
        proc_stop(w->pid);
        w->pid = 0;
        return OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP;
    }
    proc_env_report(w->pid, &g_env[w->fmt]);
    /* what the worker reports goes to the controller from now on, the lines of its replay among them; with no memory
     * to follow it the relay has closed its feedback socket, and a worker whose reports go nowhere is not started */
    if (relay_add(w->fb_fd) != 0)
    {
        w->fb_fd = -1;
        close(w->fd);
        w->fd = -1;
        proc_stop(w->pid);
        w->pid = 0;
        return OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP;
    }
    w->state = W_UP;
    return SUCCESS;
}

static void instances_of(worker_t *w, char *out, size_t size)
{
    int n;
    size_t used = 0;

    out[0] = '\0';
    for (n = 0; n < w->ninst && used + 8 < size; n++)
        used += snprintf(out + used, size - used, "%s%d", n ? "," : "", w->inst[n]->id);
}

static void schedule(worker_t *w, int64_t now)
{
    int n = recent(w->deaths, &w->ndeaths, now), backoff, shift;

    if (n >= g_conf.storm_deaths)
    {
        w->state = W_GIVEN_UP;
        event(PHD_EVENT_SUPERVISOR_GAVE_UP_FMT, w->k, n, g_conf.storm_window_ms);
        return;
    }
    shift = n > 0 ? n - 1 : 0;
    backoff = shift < 16 ? g_conf.backoff_base_ms << shift : g_conf.backoff_max_ms;
    if (backoff > g_conf.backoff_max_ms)
        backoff = g_conf.backoff_max_ms;
    w->backoff_ms = backoff;
    w->next_try_ms = now + backoff;
    w->state = W_BACKOFF;
    event(PHD_EVENT_WORKER_BACKOFF_FMT, w->k, backoff);
}

/* a named culprit leaves its pool for a worker of its own */
static worker_t *move_to_own(instance_t *i, int64_t now, int from_split)
{
    worker_t *own = worker_new(i->fmt, PHD_PLACE_OWN);

    if (!own)
    {
        fprintf(stderr, "plugin-hostd: out of memory, instance %d stays in worker %d\n", i->id, i->w->k);
        return NULL;
    }
    worker_detach(i->w, i);
    worker_attach(own, i);
    own->from_split = from_split;
    own->state = W_BACKOFF;
    own->backoff_ms = g_conf.backoff_base_ms;
    own->next_try_ms = now + g_conf.backoff_base_ms;
    return own;
}

/* every member that is not quarantined runs in the chain's worker */
static int chain_whole(const chain_t *c)
{
    int n;

    for (n = 0; n < c->n; n++)
    {
        instance_t *i = g_inst[c->ids[n]];

        if (i && !meta_of(i->id)->quarantined && (!c->w || i->w != c->w))
            return 0;
    }
    return 1;
}

/* every member that is not quarantined runs in the chain's worker and was replayed there: the chain has formed */
static int chain_running(const chain_t *c)
{
    int n;

    if (!chain_whole(c))
        return 0;
    for (n = 0; n < c->n; n++)
    {
        instance_t *i = g_inst[c->ids[n]];

        if (i && !meta_of(i->id)->quarantined && i->unreplayed)
            return 0;
    }
    return 1;
}

/* a chain begins to form, or forms again: the time is kept from its first attempt until it has formed */
static void chain_forming(chain_t *c)
{
    if (!c->forming_ms)
    {
        c->forming_ms = proc_now_ms();
        c->stall_said = 0;
    }
    c->stall_member = -1;
    c->stall_code = 0;
    snprintf(c->stall_step, sizeof(c->stall_step), "spawn");
}

/* what holds a forming chain: the first member (-1 for none), step and code of this attempt that answered something
 * other than the waiting for its worker; the ones after it follow from it and are not kept */
static void chain_stall_note(chain_t *c, int member, const char *step, int code)
{
    if (!c || !c->forming_ms || c->stall_member >= 0 || c->stall_code != 0)
        return;
    c->stall_member = member;
    c->stall_code = code;
    snprintf(c->stall_step, sizeof(c->stall_step), "%s", step);
}

/* the tick: a chain still forming past chain_form_timeout_ms is said once, with what held it */
static void chain_stall_check(chain_t *c, int64_t now)
{
    char word[24], member[16];

    if (!c || !c->forming_ms || c->stall_said || !g_conf.chain_form_timeout_ms)
        return;
    if (chain_running(c))
    {
        c->forming_ms = 0;
        return;
    }
    if (now - c->forming_ms < g_conf.chain_form_timeout_ms)
        return;
    chain_word(c, word, sizeof(word));
    if (c->stall_member >= 0)
        snprintf(member, sizeof(member), "%d", c->stall_member);
    else
        snprintf(member, sizeof(member), "%s", PHD_WORD_NONE);
    event(PHD_EVENT_CHAIN_STALLED_FMT, word, member, c->stall_step, c->stall_code);
    c->stall_said = 1;
}

/* ---------------------------------------------------------------- the running history */

/* The history is kept by plugin binary: the first file its pin holds. A plugin with no pin (require_pins off, or never
 * pinned) has none, and nothing is kept of it. src/history.c does nothing when the history is off or unavailable. */
static long long utc_now(void)
{
    return (long long)time(NULL);
}

static void hist_quarantine(const char *uri)
{
    char digest[PHD_SHA256_HEX_LEN + 1];

    if (pins_digest(uri, digest) == 0)
        history_quarantine(uri, digest, utc_now());
}

static void hist_crash(const char *uri, int grouped)
{
    char digest[PHD_SHA256_HEX_LEN + 1];

    if (pins_digest(uri, digest) == 0)
        history_crash(uri, digest, grouped, utc_now());
}

static void hist_restart(const char *uri, int grouped)
{
    char digest[PHD_SHA256_HEX_LEN + 1];

    if (pins_digest(uri, digest) == 0)
        history_restart(uri, digest, grouped, utc_now());
}

/* the xruns the worker's process counted since the last time this was asked, and 0 when it counted none, wrote no count
 * yet or restarted. A process writes its count from the start and nothing while it is 0, so the first count seen is
 * where the daemon begins to look, never xruns of the window it arrives in; a count below the last is a counter that began
 * again, and begins the baseline again */
static long hist_xruns(worker_t *w)
{
    unsigned long long count, rose = 0;

    if (w->xr_pid != w->pid)
    {
        w->xr_pid = w->pid;
        w->xr_known = 0;
    }
    if (w->fb_fd < 0 || !relay_xruns(w->fb_fd, &count))
        return 0;
    if (w->xr_known && count > w->xr_base)
        rose = count - w->xr_base;
    w->xr_known = 1;
    w->xr_base = count;
    return rose > (unsigned long long)LONG_MAX ? LONG_MAX : (long)rose;
}

/* the window [hist_start_ms, at_ms] of a worker, its CPU over it as percent of one core, folded into every member */
static void hist_fold(worker_t *w, int64_t at_ms, double cpu1, long long pss_kb)
{
    double seconds = (double)(at_ms - w->hist_start_ms) / 1000.0, pct = 0;
    int n, grouped = w->ninst >= 2;
    long xruns = hist_xruns(w);

    if (seconds > 0 && cpu1 > w->hist_cpu0)
        pct = (cpu1 - w->hist_cpu0) / seconds * 100.0;
    for (n = 0; n < w->ninst; n++)
    {
        char digest[PHD_SHA256_HEX_LEN + 1];

        if (pins_digest(w->inst[n]->uri, digest) == 0)
            history_window(w->inst[n]->uri, digest, grouped, pct, (double)pss_kb / 1024.0, xruns, utc_now());
    }
}

static void hist_begin(worker_t *w, int64_t now)
{
    w->hist_pid = 0;
    if (proc_cpu_seconds(w->pid, &w->hist_cpu0) != 0)
        return;
    hist_xruns(w);              /* what rose before this window is not its */
    w->hist_pid = w->pid;
    w->hist_start_ms = now;
    w->hist_ninst = w->ninst;
    w->hist_half_ms = 0;
}

/* the idle tick of one worker: a window opens when it is up, takes its mid-window sample, and closes after
 * history_window_s; members that came or went open it again, uncounted */
static void hist_tick(worker_t *w, int64_t now)
{
    int64_t window_ms = (int64_t)g_conf.history_window_s * 1000;
    double cpu;
    long long pss = 0;

    if (g_conf.history_window_s <= 0)
        return;
    if (w->state != W_UP || w->pid <= 0)
    {
        w->hist_pid = 0;
        return;
    }
    if (w->hist_pid != w->pid || w->hist_ninst != w->ninst)
    {
        hist_begin(w, now);
        return;
    }
    if (!w->hist_half_ms && now - w->hist_start_ms >= window_ms / 2)
    {
        if (proc_cpu_seconds(w->pid, &w->hist_half_cpu) != 0)
        {
            w->hist_pid = 0;
            return;
        }
        proc_pss_kb(w->pid, &w->hist_half_pss_kb);
        w->hist_half_ms = now;
    }
    if (now - w->hist_start_ms < window_ms)
        return;
    if (proc_cpu_seconds(w->pid, &cpu) != 0)
    {
        w->hist_pid = 0;
        return;
    }
    proc_pss_kb(w->pid, &pss);
    if (w->hist_half_pss_kb > pss)
        pss = w->hist_half_pss_kb;
    hist_fold(w, now, cpu, pss);
    w->hist_half_pss_kb = 0;
    hist_begin(w, now);
}

/* a worker that died: its window counts if it was up for half of it. The dead process is not yet reaped, so its CPU is
 * still readable; when it is not, the mid-window sample stands for the window */
static void hist_death(worker_t *w, int64_t now)
{
    double cpu;
    long long pss = w->hist_half_pss_kb;

    if (g_conf.history_window_s > 0 && w->hist_pid && w->hist_pid == w->pid)
    {
        int64_t window_ms = (int64_t)g_conf.history_window_s * 1000;

        if (now - w->hist_start_ms >= window_ms / 2 && proc_cpu_seconds(w->pid, &cpu) == 0)
            hist_fold(w, now, cpu, pss);
        else if (w->hist_half_ms)
            hist_fold(w, w->hist_half_ms, w->hist_half_cpu, pss);
    }
    w->hist_pid = 0;
    w->hist_half_ms = 0;
    w->hist_half_pss_kb = 0;
}

static void quarantine(instance_t *i, worker_t *w)
{
    meta_t *m = meta_of(i->id);

    if (!m->quarantined)
    {
        m->quarantined = 1;
        event(PHD_EVENT_INSTANCE_QUARANTINED_FMT, i->id, w->k);
        plans_replan_for(i->id);
        hist_quarantine(i->uri);
    }
    /* the culprit of a chain that was split: the others are gathered again, without it, by the tick */
    if (i->chain && !chain_whole(i->chain))
        i->chain->rejoin = 1;
}

/* the verb a worker answered and then died on, inside the suspect window: out of the ledger, so the respawn does not
 * play it again; what it replaced comes back. Returns the instance that sent it, -1 when there is none */
static int drop_suspect(worker_t *w, int64_t now)
{
    instance_t *s = NULL;
    int n, m;

    for (n = 0; n < w->ninst; n++)
    {
        instance_t *i = w->inst[n];

        if (i->sus_line && g_conf.suspect_window_ms > 0 && now - i->sus_ms <= g_conf.suspect_window_ms &&
            (!s || i->sus_seq > s->sus_seq))
            s = i;
    }
    if (!s)
        return -1;
    for (m = s->ntail - 1; m >= 0; m--)
        if (!strcmp(s->tail[m].line, s->sus_line))
            break;
    if (m >= 0)
    {
        if (s->sus_prev)
        {
            free(s->tail[m].line);
            s->tail[m].line = s->sus_prev;
            s->sus_prev = NULL;
        }
        else
        {
            free(s->tail[m].line);
            free(s->tail[m].key);
            memmove(&s->tail[m], &s->tail[m + 1], (s->ntail - m - 1) * sizeof(entry_t));
            s->ntail--;
        }
    }
    event(PHD_EVENT_VERB_DROPPED_SUSPECT_FMT, s->id, (int)(now - s->sus_ms), s->sus_line);
    return s->id;
}

static void clear_suspects(worker_t *w)
{
    int n;

    for (n = 0; n < w->ninst; n++)
    {
        free(w->inst[n]->sus_line);
        free(w->inst[n]->sus_prev);
        w->inst[n]->sus_line = w->inst[n]->sus_prev = NULL;
    }
}

static void on_death(worker_t *w, int in_flight)
{
    int status = 0, n, done = 0, grouped = w->ninst >= 2, nmembers = w->ninst;
    char ids[1024], how[32];
    int64_t now = proc_now_ms();
    instance_t **members = NULL, *blamed = NULL;

    /* a plan waiting to gather its group again waits for steady running: this death puts it off */
    for (n = 0; n < w->ninst; n++)
        plans_regroup(w->inst[n]->id, now, 0);
    /* the history: the window it was in, and who was in the worker; before the process is reaped */
    hist_death(w, now);
    if (grouped && (members = malloc(nmembers * sizeof(instance_t *))))
        memcpy(members, w->inst, nmembers * sizeof(instance_t *));
    for (n = 0; n < 50 && !(done = proc_exited(w->pid, &status)); n++)
        usleep(10000);
    if (!done)
    {
        kill(w->pid, SIGKILL);
        waitpid(w->pid, &status, 0);
    }
    if (WIFSIGNALED(status))
        snprintf(how, sizeof(how), "signal:%d", WTERMSIG(status));
    else
        snprintf(how, sizeof(how), "exit:%d", WEXITSTATUS(status));
    /* what it wrote before it died goes out before the news of its death */
    relay_remove(w->fb_fd);
    w->fb_fd = -1;
    instances_of(w, ids, sizeof(ids));
    event(PHD_EVENT_WORKER_DIED_FMT, w->k, (int)w->pid, how, ids[0] ? ids : PHD_WORD_NONE);
    if (w->fd >= 0)
        close(w->fd);
    w->fd = -1;
    w->pid = 0;
    while (w->npend)
        free(w->pend[--w->npend]);
    note_death(w->deaths, &w->ndeaths, now);
    /* a kill from outside says nothing about the last verb */
    if (in_flight == -1 && !(WIFSIGNALED(status) && (WTERMSIG(status) == SIGKILL || WTERMSIG(status) == SIGTERM)))
        in_flight = drop_suspect(w, now);
    clear_suspects(w);

    if (in_flight != ATTRIBUTED)
    {
        if (!w->pool)
        {
            if (w->ninst == 1)
            {
                meta_of(w->inst[0]->id)->crashes++;
                hist_crash(w->inst[0]->uri, 0);
                if (w->from_split)
                    quarantine(w->inst[0], w);
            }
        }
        else
        {
            instance_t *culprit = NULL;

            for (n = 0; n < w->ninst; n++)
                if (w->inst[n]->id == in_flight)
                    culprit = w->inst[n];
            if (!culprit && w->ninst == 1)
                culprit = w->inst[0];
            if (culprit)
            {
                meta_of(culprit->id)->crashes++;
                hist_crash(culprit->uri, w->ninst >= 2);
                blamed = culprit;
                quarantine(culprit, w);
                move_to_own(culprit, now, 0);
            }
            else if (w->ninst > 1)
            {
                /* the group is split, and the plan that holds it gathers it again after history_regroup_s of steady
                 * running */
                for (n = 0; n < w->ninst; n++)
                    plans_regroup(w->inst[n]->id, now, 1);
                while (w->ninst && move_to_own(w->inst[0], now, 1))
                    ;
            }
        }
    }
    /* the members of a group that went down with it and were not the culprit */
    for (n = 0; members && n < nmembers; n++)
        if (members[n] != blamed)
            hist_restart(members[n]->uri, 1);
    free(members);
    if (w->ninst == 0)
    {
        worker_free(w);
        return;
    }
    schedule(w, now);
}

/* ---------------------------------------------------------------- checkpoint and replay */

static void checkpoint(worker_t *w)
{
    char msg[PATH_MAX + 16], *reply = NULL;
    int rc, n;

    if (w->state != W_UP)
        return;
    snprintf(msg, sizeof(msg), STATE_SAVE, g_ckpt);
    rc = proc_rpc(&g_conf, w->pid, w->fd, msg, &reply);
    if (rc != RPC_OK)
    {
        on_death(w, -1);
        return;
    }
    free(reply);
    for (n = 0; n < w->ninst; n++)
    {
        instance_t *i = w->inst[n];

        i->dirty = 0;
        i->has_ckpt = ckpt_exists(i->id);
        if (i->has_ckpt)
            tail_drop_state(i);
    }
}

/* one replayed line: the reply is read and dropped, the death is the caller's; *code is the worker's answer */
/* the line that hands a CLAP worker the layout pin of the instance it is about to add */
static const char *pin_expect_line(int id, const char *layout)
{
    static char line[PHD_SHA256_HEX_LEN + 128];

    snprintf(line, sizeof(line), OMX_VERB_PIN_EXPECT " %d %s", id, layout);
    return line;
}

static int replay_line_code(worker_t *w, const char *line, int *code)
{
    char *reply = NULL;
    int rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);

    *code = 0;
    if (rc == RPC_OK)
    {
        *code = resp_code(reply);
        if (*code < 0)
            fprintf(stderr, "plugin-hostd: w%d refused '%s': %s\n", w->k, line, reply);
        free(reply);
    }
    return rc;
}

static int replay_line(worker_t *w, const char *line)
{
    int code;

    return replay_line_code(w, line, &code);
}

/* a jack port is announced to a new client a moment after it is registered: a connect that is refused is asked again
 * by the tick for a few seconds, and dropped after that (the peer is down, and its own replay makes the connection) */
static void pend_add(worker_t *w, const char *line)
{
    char **grown = realloc(w->pend, (w->npend + 1) * sizeof(char *));
    char *copy = strdup(line);

    if (grown)
        w->pend = grown;
    if (!grown || !copy)
    {
        fprintf(stderr, "plugin-hostd: out of memory, a refused connect is not asked again: %s\n", line);
        free(copy);
        return;
    }
    w->pend[w->npend++] = copy;
    w->pend_until_ms = proc_now_ms() + CONNECT_RETRY_MS;
}

static void pend_retry(worker_t *w, int64_t now)
{
    int n = 0;

    while (n < w->npend && w->state == W_UP)
    {
        int code;

        if (replay_line_code(w, w->pend[n], &code) != RPC_OK)
        {
            on_death(w, -1);
            return;
        }
        if (code >= 0 || now > w->pend_until_ms)
        {
            free(w->pend[n]);
            w->pend[n] = w->pend[--w->npend];
        }
        else
            n++;
    }
}

/* the event of a refusal that says the plugin is not the one that was pinned */
static void pin_changed_event(const char *uri, int code)
{
    if (code == OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP)
        event(PHD_EVENT_PIN_CHANGED_FMT, uri, PHD_PIN_CHANGED_FILES);
    else if (code == OMX_REPLY_HOST_PIN_LAYOUT_MISMATCH_RESP)
        event(PHD_EVENT_PIN_CHANGED_FMT, uri, PHD_PIN_CHANGED_LAYOUT);
}

/* a replayed add refused, by its pin or by the worker: announced with the refusal's own code, written with
 * OMX_REPLY_PLUGIN_HOSTD_REPLAY_RESP and the step that refused it, and the worker does not hold the instance until it is replayed again */
static void replay_refused(worker_t *w, instance_t *i, const char *step, int code)
{
    fprintf(stderr, "plugin-hostd: w%d did not replay instance %d: resp %d, its %s resp %d\n", w->k, i->id, OMX_REPLY_PLUGIN_HOSTD_REPLAY_RESP,
            step, code);
    event(PHD_EVENT_REPLAY_REFUSED_FMT, i->id, code);
    pin_changed_event(i->uri, code);
    i->unreplayed = 1;
    chain_stall_note(w->chain, i->id, step, code);
}

/* the pin of a replayed add, checked again: a binary swapped while its worker was down is refused on respawn.
 * RPC_OK, PIN_REFUSED, or the worker's death. */
static int replay_pin(worker_t *w, instance_t *i)
{
    const char *layout = NULL;
    int code, rc;

    i->unreplayed = 0;
    if (!g_conf.require_pins)
        return RPC_OK;
    code = pins_check(format_at(i->fmt), i->uri, search_of(i->fmt), &layout);
    if (code != SUCCESS)
    {
        replay_refused(w, i, "pin", code);
        return PIN_REFUSED;
    }
    if (format_at(i->fmt)->layout_check && layout)
    {
        rc = replay_line_code(w, pin_expect_line(i->id, layout), &code);
        if (rc != RPC_OK)
            return rc;
        if (code < 0)
        {
            replay_refused(w, i, OMX_VERB_PIN_EXPECT, code);
            return PIN_REFUSED;
        }
    }
    return RPC_OK;
}

/* "chain <chain> <instance> ...": the members a chain's worker holds and replayed, in order; 0 when it holds none */
static int chain_line(worker_t *w, char *line, size_t size)
{
    size_t used = snprintf(line, size, OMX_VERB_CHAIN " %d", w->chain->id);
    int n, count = 0;

    for (n = 0; n < w->ninst && used + 12 < size; n++)
        if (!w->inst[n]->unreplayed)
        {
            used += snprintf(line + used, size - used, " %d", w->inst[n]->id);
            count++;
        }
    return count;
}

/* an instance's add as a replay gives it: its pin checked again, its add, its track_info. 1 when the worker holds it,
 * 0 when its pin or the worker refused it, -1 when the worker died on it (the death is handled) */
static int replay_add(worker_t *w, instance_t *i)
{
    char add[32];
    int code;

    snprintf(add, sizeof(add), "%.*s", verb_len(EFFECT_ADD), EFFECT_ADD);
    switch (replay_pin(w, i))
    {
    case RPC_OK:
        break;
    case PIN_REFUSED:
        return 0;
    default:
        on_death(w, i->id);
        return -1;
    }
    if (replay_line_code(w, i->add_line, &code) != RPC_OK)
    {
        on_death(w, i->id);
        return -1;
    }
    if (code < 0)
    {
        replay_refused(w, i, add, code);
        return 0;
    }
    /* before the state: what the plugin does on hearing it is overwritten by the state it saved; mod-host
     * has no track_info, so a worker that does not answer the instance verbs never gets it */
    if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(w, i->track_info) != RPC_OK)
    {
        on_death(w, i->id);
        return -1;
    }
    i->has_ckpt = ckpt_exists(i->id);
    return 1;
}

/* an instance's verb ledger, after the state; -1 when the worker died on it */
static int replay_tail(worker_t *w, instance_t *i)
{
    int m;

    for (m = 0; m < i->ntail; m++)
        if (replay_line(w, i->tail[m].line) != RPC_OK)
        {
            on_death(w, i->id);
            return -1;
        }
    return 0;
}

/* an instance's connections, last: one the worker cannot make yet is asked again by the tick; -1 when it died */
static int replay_conns(worker_t *w, instance_t *i)
{
    int m, code;

    for (m = 0; m < i->nconns; m++)
    {
        if (replay_line_code(w, i->conns[m], &code) != RPC_OK)
        {
            on_death(w, i->id);
            return -1;
        }
        if (code < 0)
            pend_add(w, i->conns[m]);
    }
    return 0;
}

/* the order of a chain, to a worker that runs one in one client: the members it holds. Its refusal is kept on the chain,
 * which ends as soon as nothing is being replayed. RPC_OK, or the worker's death for the caller to handle */
static int chain_order_send(worker_t *w)
{
    char line[PATH_MAX + 16];
    int rc, code;

    if (!format_at(w->fmt)->native_chain || !chain_line(w, line, sizeof(line)))
        return RPC_OK;
    rc = replay_line_code(w, line, &code);
    if (rc == RPC_OK && code < 0)
        w->chain->refused = code;
    return rc;
}

/* chain_formed: the order a chain's worker runs now, the members it holds and replayed */
static void chain_formed(worker_t *w)
{
    char ids[1024], word[24];
    size_t used = 0;
    int n;

    ids[0] = '\0';
    for (n = 0; n < w->ninst && used + 8 < sizeof(ids); n++)
        if (!w->inst[n]->unreplayed)
            used += snprintf(ids + used, sizeof(ids) - used, "%s%d", used ? "," : "", w->inst[n]->id);
    chain_word(w->chain, word, sizeof(word));
    event(PHD_EVENT_CHAIN_FORMED_FMT, word, w->k, used ? ids : PHD_WORD_NONE);
    if (chain_running(w->chain))
        w->chain->forming_ms = 0;
}

static void replay(worker_t *w, int64_t started)
{
    int n, added, any_ckpt = 0, count = 0;
    char msg[PATH_MAX + 16];

    for (n = 0; n < w->ninst; n++)
    {
        added = replay_add(w, w->inst[n]);
        if (added < 0)
            return;
        any_ckpt |= added && w->inst[n]->has_ckpt;
    }
    /* the order of a chain, to a worker that runs one in one client, before the state: the members it holds */
    if (w->chain && chain_order_send(w) != RPC_OK)
    {
        on_death(w, -1);
        return;
    }
    if (any_ckpt)
    {
        snprintf(msg, sizeof(msg), STATE_LOAD, g_ckpt);
        if (replay_line(w, msg) != RPC_OK)
        {
            on_death(w, -1);
            return;
        }
    }
    for (n = 0; n < w->ninst; n++)
        if (!w->inst[n]->unreplayed && replay_tail(w, w->inst[n]) < 0)
            return;
    for (n = 0; n < w->ninst; n++)
    {
        if (w->inst[n]->unreplayed)
            continue;
        if (replay_conns(w, w->inst[n]) < 0)
            return;
        count++;
    }
    w->state = W_UP;
    event(PHD_EVENT_WORKER_RESPAWNED_FMT, w->k, (int)w->pid, count, (int)(proc_now_ms() - started));
    for (n = 0; n < w->ninst; n++)
        if (!w->inst[n]->unreplayed)
            event(PHD_EVENT_INSTANCE_RESTORED_FMT, w->inst[n]->id, w->k);
    if (w->chain && !w->chain->refused)
        chain_formed(w);
}

static void respawn(worker_t *w)
{
    int64_t started = proc_now_ms();
    int rc = worker_start(w, w->ninst == 1 ? w->inst[0]->uri : NULL);

    if (rc != SUCCESS)
    {
        chain_stall_note(w->chain, -1, "spawn", rc);
        note_death(w->deaths, &w->ndeaths, started);
        schedule(w, started);
        return;
    }
    replay(w, started);
}

void sup_tick(void)
{
    int n;
    int64_t now = proc_now_ms();
    worker_t *list[1024];
    int count = g_nworkers < 1024 ? g_nworkers : 1024;

    sup_pins_poll();
    memcpy(list, g_workers, count * sizeof(worker_t *));
    for (n = 0; n < count; n++)
    {
        worker_t *w = list[n];
        int i, found = 0;

        for (i = 0; i < g_nworkers; i++)
            found |= g_workers[i] == w;
        if (!found)
            continue;
        if (w->state == W_UP && proc_dead(w->pid))
            on_death(w, -1);
        else if (w->state == W_BACKOFF && now >= w->next_try_ms)
            respawn(w);
        else if (w->state == W_UP && w->npend)
            pend_retry(w, now);
    }
    for (n = 0; n < g_nworkers; n++)
    {
        worker_t *w = g_workers[n];
        int i, due = 0;

        if (w->state != W_UP)
            continue;
        for (i = 0; i < w->ninst; i++)
            due |= w->inst[i]->dirty && now - w->inst[i]->changed_ms >= g_conf.checkpoint_ms;
        if (due)
            checkpoint(w);
    }
    for (n = 0; n < g_nworkers; n++)
        hist_tick(g_workers[n], now);
    history_tick(now / 1000);
    /* a plan is made again at a quarantine of a member and when its regroup timer is due, here and never mid-cycle of a
     * worker: before the chains are gathered, so that a segment the new plan dissolves is not formed first */
    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
        if (g_plan[n] && (g_plan[n]->replan || (g_plan[n]->regroup_ms && now >= g_plan[n]->regroup_ms)))
            plan_again(n);
    for (n = 0; g_nchains && n < MAX_INSTANCE; n++)
        if (g_chain[n] && g_chain[n]->rejoin)
        {
            g_chain[n]->rejoin = 0;
            if (!chain_whole(g_chain[n]))
                chain_form(g_chain[n]);
        }
    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
    {
        int k;

        /* chain_form retires and makes workers, not segments: the list holds while it runs */
        for (k = 0; g_plan[n] && k < g_plan[n]->nseg; k++)
            if (g_plan[n]->seg[k]->rejoin)
            {
                g_plan[n]->seg[k]->rejoin = 0;
                if (!chain_whole(g_plan[n]->seg[k]))
                    chain_form(g_plan[n]->seg[k]);
            }
    }
    /* a chain still forming past chain_form_timeout_ms is said once, with what held it */
    for (n = 0; g_nchains && n < MAX_INSTANCE; n++)
        chain_stall_check(g_chain[n], now);
    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
    {
        int k;

        for (k = 0; g_plan[n] && k < g_plan[n]->nseg; k++)
            chain_stall_check(g_plan[n]->seg[k], now);
    }
    /* a worker that refused a chain on a respawn or a rejoin: no one is waiting for a reply, the event says it */
    for (n = 0; g_nchains && n < MAX_INSTANCE; n++)
        if (g_chain[n] && g_chain[n]->refused)
            chain_refused(g_chain[n]);
    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
        if (g_plan[n])
            plan_worker_refused(g_plan[n]);
}

/* ---------------------------------------------------------------- init and finish */

void sup_init(const conf_t *conf)
{
    int f;

    g_conf = *conf;
    mkdir(g_conf.state_root, 0755);
    snprintf(g_root, sizeof(g_root), "%s/plugin-hostd", g_conf.state_root);
    mkdir(g_root, 0755);
    snprintf(g_root, sizeof(g_root), "%s/plugin-hostd/%d", g_conf.state_root, (int)getpid());
    rm_tree(g_root);
    mkdir(g_root, 0755);
    snprintf(g_ckpt, sizeof(g_ckpt), "%s/ckpt", g_root);
    mkdir(g_ckpt, 0755);
    for (f = 0; f < FORMATS_MAX; f++)
    {
        snprintf(g_policy[f], sizeof(g_policy[f]), PHD_PLACE_OWN);
        proc_env_clear(&g_env[f]);
    }
}

const char *sup_root(void)
{
    return g_root;
}

void sup_finish(void)
{
    int n;

    for (n = g_nworkers - 1; n >= 0; n--)
        if (g_workers[n]->pid > 0)
            kill(g_workers[n]->pid, SIGTERM);
    for (n = g_nworkers - 1; n >= 0; n--)
        proc_stop(g_workers[n]->pid);
    rm_tree(g_root);
    pins_finish();
}

int sup_worker_count(void)
{
    return g_nworkers;
}

/* ---------------------------------------------------------------- verbs */

static instance_t *by_client(const char *port)
{
    const char *colon = strchr(port, ':');
    size_t n = colon ? (size_t)(colon - port) : 0;
    int id;

    if (!n)
        return NULL;
    for (id = 0; id < MAX_INSTANCE; id++)
        if (g_inst[id] && strlen(g_inst[id]->client) == n && !strncmp(g_inst[id]->client, port, n))
            return g_inst[id];
    return NULL;
}

static worker_t *pool_worker(int fmt, const char *name, int *full, int *unavailable)
{
    int n, max = g_conf.pool_max;
    char base[48];

    for (n = 0; n < g_npools; n++)
        if (!strcmp(g_pools[n].name, name))
            max = g_pools[n].max;
    snprintf(base, sizeof(base), PHD_PLACE_POOL_PREFIX "%s", name);
    *full = *unavailable = 0;
    for (n = 0; n < g_nworkers; n++)
    {
        worker_t *w = g_workers[n];
        size_t len = strlen(base);

        if (w->fmt != fmt || !w->pool || strncmp(w->place, base, len) != 0 || (w->place[len] && w->place[len] != '#'))
            continue;
        if (w->state == W_GIVEN_UP)
        {
            *unavailable = OMX_REPLY_PLUGIN_HOSTD_GAVE_UP_RESP;
            continue;
        }
        if (w->state != W_UP)
        {
            *unavailable = OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP;
            continue;
        }
        if (w->ninst < max)
            return w;
        *full = 1;
    }
    return NULL;
}

static int pool_siblings(int fmt, const char *name)
{
    int n, count = 0;
    char base[48];
    size_t len;

    snprintf(base, sizeof(base), PHD_PLACE_POOL_PREFIX "%s", name);
    len = strlen(base);
    for (n = 0; n < g_nworkers; n++)
        if (g_workers[n]->fmt == fmt && g_workers[n]->pool && !strncmp(g_workers[n]->place, base, len) &&
            (g_workers[n]->place[len] == '\0' || g_workers[n]->place[len] == '#'))
            count++;
    return count;
}

/* the layout a worker found after init, recorded in the pin that has none yet. A worker that does not know the verb, or
 * a reply that is not a layout, leaves the pin as it is: its files are still checked on every add */
static void learn_layout(worker_t *w, int id, const char *uri)
{
    char line[64], *reply = NULL, *save = NULL, *word;
    int rc;

    snprintf(line, sizeof(line), OMX_VERB_PIN_LAYOUT " %d", id);
    rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc == RPC_OK && resp_code(reply) >= 0)
    {
        strtok_r(reply, " \t\r\n", &save);
        strtok_r(NULL, " \t\r\n", &save);
        word = strtok_r(NULL, " \t\r\n", &save);
        if (word)
            pins_set_layout(uri, word);
    }
    free(reply);
}

static char *add(const char *uri, int id, const char *placement, const char *client, int row);
static int chain_order_send(worker_t *w);
static void chain_formed(worker_t *w);

/* the chain an add names, chain:<number> (#348): its number, -2 when the placement names a chain that is no number, -1
 * when it names none */
static int add_chain_id(const char *placement)
{
    const char *p;
    char *end;
    long v;

    if (!placement || strncmp(placement, PHD_PLACE_CHAIN_PREFIX, strlen(PHD_PLACE_CHAIN_PREFIX)))
        return -1;
    p = placement + strlen(PHD_PLACE_CHAIN_PREFIX);
    if (!*p || !isdigit((unsigned char)*p))
        return -2;
    v = strtol(p, &end, 10);
    return *end || v >= MAX_INSTANCE ? -2 : (int)v;
}

/* the adapter of a worker refused the add of `uri`, for the reason `why`: say so on the feedback port; under auto the plugin
 * goes to the lv2 row from now on and this add is made again there, otherwise the add answers OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED_RESP */
static char *adapter_refused(const char *uri, const char *why, int id, const char *placement, const char *client)
{
    int automatic = lv2_worker_is_auto(&g_conf, uri);

    event(PHD_EVENT_LV2_ADAPTER_REFUSED_FMT, uri, why, automatic ? PHD_LV2_WORKER_AUTO : PHD_LV2_WORKER_CLAP_HOST);
    if (!automatic)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED_RESP);
    lv2_adapter_refused(uri);
    return sup_add(uri, id, placement, client);
}

/* the member an add put in a chain's worker joins the chain, at its end, and the worker is told the order. A worker that
 * refuses the order (a member not as wide as the head's output) has the member taken out again and the order without it
 * sent again; the add is then refused. 0, or -1 when the member was refused */
static int add_to_chain(int chain_id, worker_t *w, instance_t *i)
{
    chain_t *c = g_chain[chain_id];
    int *ids, rc;
    char line[64], *gone = NULL;

    if (!c)
    {
        c = calloc(1, sizeof(chain_t));
        if (!c)
            goto out_of_memory;
        c->id = chain_id;
        g_chain[chain_id] = c;
        g_nchains++;
    }
    ids = realloc(c->ids, (c->n + 1) * sizeof(int));
    if (!ids)
        goto out_of_memory;
    c->ids = ids;
    c->ids[c->n++] = i->id;
    i->chain = c;
    c->w = w;
    w->chain = c;
    c->refused = 0;
    rc = chain_order_send(w);
    if (rc != RPC_OK)
    {
        on_death(w, -1);
        return 0;
    }
    if (!c->refused)
    {
        chain_formed(w);
        return 0;
    }
    /* refused: out of the worker and out of the chain, and the order as it was before it */
    c->refused = 0;
    c->n--;
    i->chain = NULL;
    snprintf(line, sizeof(line), EFFECT_REMOVE, i->id);
    if (proc_rpc(&g_conf, w->pid, w->fd, line, &gone) != RPC_OK)
    {
        free(gone);
        on_death(w, -1);
        return -1;
    }
    free(gone);
    worker_detach(w, i);
    g_inst[i->id] = NULL;
    instance_free(i);
    if (c->n)
    {
        if (chain_order_send(w) != RPC_OK)
            on_death(w, -1);
        else if (c->refused)
            chain_refused(c);   /* the order it took before is refused now too: the chain ends as a refused one does */
    }
    else
    {
        w->chain = NULL;
        g_chain[chain_id] = NULL;
        g_nchains--;
        free(c->ids);
        free(c);
        if (w->ninst == 0)
            worker_retire(w);
    }
    return -1;
out_of_memory:
    /* no memory to keep the chain's books: the member runs in the worker as a pool's member, outside any chain */
    fprintf(stderr, "plugin-hostd: out of memory, instance %d is in chain %d's worker outside its order\n", i->id, chain_id);
    return 0;
}

char *sup_add(const char *uri, int id, const char *placement, const char *client)
{
    return add(uri, id, placement, client, -1);
}

/* the add on the row `row`, or on the row the uri is routed to when it is -1 */
static char *add(const char *uri, int id, const char *placement, const char *client, int row)
{
    const char *fwd;
    int fmt = format_of_uri(uri, &fwd);
    const format_t *format;
    char place[48], line[PATH_MAX + 640], word[PATH_MAX + 512], *reply = NULL;
    const char *layout = NULL;
    worker_t *w = NULL;
    meta_t *m;
    int64_t now = proc_now_ms();
    int rc, is_new = 0, full, unavailable, code = ERR_HOST_INSTANTIATION, expected = 0;
    instance_t *i;
    int chain_id = add_chain_id(placement);
    chain_t *c = chain_id >= 0 ? g_chain[chain_id] : NULL;

    /* the format may hand the uri to another row: which worker runs an LV2 plugin is a setting, not the uri's */
    fmt = row >= 0 ? row : format_route(&g_conf, fmt, fwd);
    /* auto without the adapter's worker installed is the lv2 row, for this add only */
    if (format_at(fmt)->adapter && !proc_have_binary(bin_of(fmt)) && lv2_worker_is_auto(&g_conf, fwd))
        fmt = format_by_name(PHD_FORMAT_LV2);
    format = format_at(fmt);
    if (id < 0 || id >= MAX_INSTANCE)
        return sup_resp(ERR_INSTANCE_INVALID);
    if (g_inst[id])
        return sup_resp(ERR_INSTANCE_ALREADY_EXISTS);
    /* a plugin upgraded since the pins were read is hosted by the pins as the file says now, not by a restart */
    sup_pins_poll();
    if (chain_id == -2 || (placement && chain_id < 0 && strcmp(placement, PHD_PLACE_DEFAULT) && !valid_place(placement)))
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    /* into a chain's worker (#348): a planned chain is the planner's, a chain whose members run elsewhere is formed by
     * chain, and a worker of another row cannot take the plugin; each is refused here, and the controller adds it own */
    if (chain_id >= 0 && c)
    {
        if (c->planned || (c->n && (!c->w || c->w->state != W_UP)))
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
        if (c->n && !chain_rows_together(fmt, chain_row_of(c->ids, c->n)))
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT_RESP);
    }
    if (!placement || !strcmp(placement, PHD_PLACE_DEFAULT))
        snprintf(place, sizeof(place), "%s", g_policy[fmt]);
    else
        snprintf(place, sizeof(place), "%s", placement);
    /* a plugin the adapter refused under auto was never run by it: one that dies in instantiate (a Qt body with no
     * display) must not take a shared worker with it, so unless the caller named a placement it gets one of its own */
    if ((!placement || !strcmp(placement, PHD_PLACE_DEFAULT)) && lv2_refused_under_auto(&g_conf, fmt, fwd))
        snprintf(place, sizeof(place), PHD_PLACE_OWN);
    m = meta_of(id);
    if (chain_id >= 0 && (m->quarantined || lv2_refused_under_auto(&g_conf, fmt, fwd)))
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    if (m->quarantined)
        snprintf(place, sizeof(place), PHD_PLACE_OWN);
    if (!proc_have_binary(bin_of(fmt)))
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND_RESP);
    if (recent(m->deaths, &m->ndeaths, now) >= g_conf.storm_deaths)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_GAVE_UP_RESP);
    if (g_conf.require_pins)
    {
        int first_use = conf_pins_first_use(&g_conf);

        rc = pins_check(format, fwd, search_of(fmt), &layout);
        /* a plugin that has no pin gets one, from the files as they are now; it is not asked about again */
        if (rc == OMX_REPLY_HOST_PIN_ABSENT_RESP && first_use && !pins_known(fwd))
        {
            rc = pins_learn(format, fwd, search_of(fmt));
            if (rc == SUCCESS)
                rc = pins_check(format, fwd, search_of(fmt), &layout);
        }
        pin_changed_event(fwd, rc);
        if (rc != SUCCESS)
            return sup_resp(rc);
        /* a pool's world holds every member's files: what a format pins holds only in a world of the plugin's own */
        if (format->pinned_own_only)
        {
            if (chain_id >= 0 || (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX))))
                return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
            snprintf(place, sizeof(place), PHD_PLACE_OWN);
        }
        /* first-use: only a plugin qualified for a shared worker is placed in one */
        else if ((first_use && !pins_in_process(fwd)) || (format->thread_pool && pins_pool_cores(fwd)))
        {
            if (chain_id >= 0 || (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX))))
                return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
            snprintf(place, sizeof(place), PHD_PLACE_OWN);
        }
    }

    if (chain_id >= 0 && c && c->w)
        w = c->w;
    else if (chain_id >= 0)
    {
        /* the chain's first member starts its worker: a pool's, so its world is the whole search path until it has
         * members (narrow_world), and the next members are found in it without a start */
        snprintf(place, sizeof(place), PHD_PLACE_CHAIN_PREFIX "%d", chain_id);
        w = worker_new(fmt, place);
        if (!w)
            return sup_resp(ERR_MEMORY_ALLOCATION);
        w->pool = 1;
        is_new = 1;
    }
    else if (!strcmp(place, PHD_PLACE_OWN))
    {
        w = worker_new(fmt, PHD_PLACE_OWN);
        if (!w)
            return sup_resp(ERR_MEMORY_ALLOCATION);
        is_new = 1;
    }
    else
    {
        w = pool_worker(fmt, place + 5, &full, &unavailable);
        if (!w && unavailable && !full)
            return sup_resp(unavailable);
        if (!w)
        {
            char name[64];
            int siblings = pool_siblings(fmt, place + 5);

            if (siblings)
                snprintf(name, sizeof(name), "%s" PHD_POOL_SIBLING_SEPARATOR "%d", place, siblings + 1);
            else
                snprintf(name, sizeof(name), "%s", place);
            w = worker_new(fmt, name);
            if (!w)
                return sup_resp(ERR_MEMORY_ALLOCATION);
            is_new = 1;
        }
    }
    /* room for it in a pool that holds others, before the worker is asked to take it */
    if (worker_reserve(w, w->ninst + 1) != 0)
        return sup_resp(ERR_MEMORY_ALLOCATION);
    if (is_new)
    {
        rc = worker_start(w, fwd);
        if (rc != SUCCESS)
        {
            w->pid = 0;
            worker_free(w);
            return sup_resp(rc);
        }
    }
    rc = RPC_OK;
    if (layout && format->layout_check)
    {
        rc = proc_rpc(&g_conf, w->pid, w->fd, pin_expect_line(id, layout), &reply);
        if (rc == RPC_OK && resp_code(reply) >= 0)
        {
            free(reply);
            reply = NULL;
        }
        else if (rc != RPC_OK)
        {
            /* the worker went with pin_expect on the wire: the add is never forwarded */
            event(PHD_EVENT_VERB_DROPPED_FMT, id, pin_expect_line(id, layout));
            code = OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP;
        }
    }
    /* a member after a chain's first joins the walk at its add, in the head's client, with no client of its own
     * (chain_expect): a worker that refuses the verb takes the add and the order line instead, from then on */
    if (rc == RPC_OK && !reply && c && c->n && c->w == w && !w->no_chain_expect)
    {
        char expect[64];

        snprintf(expect, sizeof(expect), OMX_VERB_CHAIN_EXPECT " %d %d", id, chain_id);
        rc = proc_rpc(&g_conf, w->pid, w->fd, expect, &reply);
        if (rc == RPC_OK)
        {
            expected = resp_code(reply) >= 0;
            w->no_chain_expect = !expected;
            free(reply);
            reply = NULL;
        }
        else
        {
            event(PHD_EVENT_VERB_DROPPED_FMT, id, expect);
            code = OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP;
        }
    }
    if (format->worker_word)
        format->worker_word(fwd, word, sizeof(word));
    else
        snprintf(word, sizeof(word), "%s", fwd);
    snprintf(line, sizeof(line), "%.*s %s%s %d%s%s", verb_len(EFFECT_ADD), EFFECT_ADD,
             format->worker_prefix ? format->worker_prefix : "", word, id, client ? " " : "", client ? client : "");
    if (rc == RPC_OK && !reply)
        rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc != RPC_OK)
    {
        /* the worker went with `add` or its pin_expect on the wire: the instance is the suspect, and the event names
         * the plugin it died adding (the pin_expect's own was sent above) */
        if (code != OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP)
            event(PHD_EVENT_VERB_DROPPED_FMT, id, line);
        m->crashes++;
        note_death(m->deaths, &m->ndeaths, now);
        /* the plugin it was adding is not in the worker yet: it joins the members that are */
        hist_crash(fwd, w->ninst >= 1);
        if (w->pool)
        {
            m->quarantined = 1;
            event(PHD_EVENT_INSTANCE_QUARANTINED_FMT, id, w->k);
            hist_quarantine(fwd);
        }
        on_death(w, ATTRIBUTED);
        return sup_resp(code);
    }
    /* the worker could not put it in the chain (a plugin not as wide as the head's output): nothing of it is there, and
     * the controller adds it own */
    if (expected && resp_code(reply) == ERR_INVALID_OPERATION)
    {
        free(reply);
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    }
    if (resp_code(reply) < 0)
    {
        /* the adapter refuses a plugin with the instantiation error and the hosting.* code after it on the reply line; the
         * invalid uri is a plugin no bundle of its world holds, which is no refusal and carries no code */
        int refused = format->adapter && resp_code(reply) == ERR_HOST_INSTANTIATION;
        int absent = format->adapter && resp_code(reply) == ERR_HOST_INVALID_URI;
        char why[128] = PHD_WORD_NONE;

        if (refused)
            lv2_refusal_reason(reply, why, sizeof(why));
        pin_changed_event(fwd, resp_code(reply));
        if (w->ninst == 0)
            worker_retire(w);
        if (refused)
        {
            free(reply);
            return adapter_refused(fwd, why, id, placement, client);
        }
        /* under auto, a plugin the adapter does not find is looked for by mod-host, for this add only */
        if (absent && lv2_worker_is_auto(&g_conf, fwd))
        {
            free(reply);
            return add(fwd, id, placement, client, format_by_name(PHD_FORMAT_LV2));
        }
        return reply;
    }
    if (g_conf.require_pins && !layout && format->layout_check)
        learn_layout(w, id, fwd);
    i = calloc(1, sizeof(instance_t));
    if (i)
    {
        char name[32];

        snprintf(name, sizeof(name), "effect_%d", id);
        i->id = id;
        i->fmt = fmt;
        i->uri = strdup(fwd);
        i->add_line = strdup(line);
        i->client = strdup(client ? client : name);
    }
    if (!i || !i->uri || !i->add_line || !i->client)
    {
        /* the worker holds a plugin the daemon has no memory to keep the books of: it is taken out again */
        char *gone = NULL;

        if (i)
            instance_free(i);
        snprintf(line, sizeof(line), EFFECT_REMOVE, id);
        if (proc_rpc(&g_conf, w->pid, w->fd, line, &gone) != RPC_OK)
            on_death(w, -1);
        else if (w->ninst == 0)
            worker_retire(w);
        free(gone);
        free(reply);
        return sup_resp(ERR_MEMORY_ALLOCATION);
    }
    g_inst[id] = i;
    worker_attach(w, i);
    if (chain_id >= 0 && add_to_chain(chain_id, w, i) != 0)
    {
        free(reply);
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    }
    return reply;
}

static void chain_free(chain_t *c)
{
    int n;

    for (n = 0; n < c->n; n++)
        if (g_inst[c->ids[n]] && g_inst[c->ids[n]]->chain == c)
            g_inst[c->ids[n]]->chain = NULL;
    if (c->w)
        c->w->chain = NULL;
    if (c->planned)
    {
        plan_t *p = g_plan[c->id];
        int k;

        for (k = 0; p && k < p->nseg; k++)
            if (p->seg[k] == c)
                p->seg[k] = p->seg[--p->nseg];
    }
    else
    {
        g_chain[c->id] = NULL;
        g_nchains--;
    }
    free(c->ids);
    free(c);
}

/* a member that is gone leaves the order; a chain with no member left is forgotten */
static void chain_leave(instance_t *i)
{
    chain_t *c = i->chain;
    int n, kept = 0;

    if (!c)
        return;
    i->chain = NULL;
    for (n = 0; n < c->n; n++)
        if (c->ids[n] != i->id)
            c->ids[kept++] = c->ids[n];
    c->n = kept;
    if (!c->n)
        chain_free(c);
}

/* a chain's worker that is up and runs chains is told the order it holds now */
static void chain_tell(worker_t *w)
{
    if (w->state == W_UP && chain_order_send(w) != RPC_OK)
        on_death(w, -1);
}

static char *refuse_worker(worker_t *w)
{
    return sup_resp(w->state == W_GIVEN_UP ? OMX_REPLY_PLUGIN_HOSTD_GAVE_UP_RESP : OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP);
}

static int64_t g_sus_seq;

/* 0, or -1 with the ledger as it was when memory runs out */
static int record(instance_t *i, const char *line, char **tok, int ntok)
{
    size_t v;

    for (v = 0; v < sizeof(g_recorded) / sizeof(g_recorded[0]); v++)
        if (verb_is(tok[0], g_recorded[v].format))
        {
            const char *key = NULL;
            char keybuf[160], *prev;

            if (g_recorded[v].key_arg && ntok > g_recorded[v].key_arg)
            {
                snprintf(keybuf, sizeof(keybuf), "%s %s", tok[0], tok[g_recorded[v].key_arg]);
                key = keybuf;
            }
            else if (g_recorded[v].key_arg)
                return 0;
            if (verb_is(tok[0], EFFECT_PRESET_LOAD))
                tail_drop_state(i);
            if (tail_add(i, line, key, g_recorded[v].kind, &prev) != 0)
                return -1;
            free(i->sus_line);
            free(i->sus_prev);
            i->sus_line = strdup(line);
            i->sus_prev = prev;
            i->sus_ms = proc_now_ms();
            i->sus_seq = ++g_sus_seq;
            if (g_recorded[v].kind == KIND_STATE)
            {
                i->dirty = 1;
                i->changed_ms = proc_now_ms();
            }
            return 0;
        }
    return 0;
}

/* the ledger takes the verb of one forwarded line, if it is one it keeps; 0, or -1 when memory runs out */
static int ledger_verb(instance_t *i, const char *line)
{
    char *save = NULL, *t, *copy = strdup(line), *tok[16];
    int ntok = 0, rc = 0;

    if (!copy)
        return -1;
    for (t = strtok_r(copy, " \t", &save); t && ntok < 16; t = strtok_r(NULL, " \t", &save))
        tok[ntok++] = t;
    if (ntok)
        rc = record(i, line, tok, ntok);
    free(copy);
    return rc;
}

/* the verb the worker died on is not replayed: it never entered the ledger, and the controller is told so */
static char *verb_dropped(instance_t *i, const char *line)
{
    event(PHD_EVENT_VERB_DROPPED_FMT, i->id, line);
    return sup_resp(OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP);
}

char *sup_call(int id, const char *line)
{
    instance_t *i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL;
    worker_t *w;
    char *reply = NULL;
    int rc;

    if (!i)
        return sup_resp(ERR_INSTANCE_NON_EXISTS);
    w = i->w;
    if (w->state != W_UP)
        return refuse_worker(w);
    rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc == RPC_WAS_DEAD)
    {
        on_death(w, -1);
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP);
    }
    if (rc == RPC_DIED)
    {
        char *dropped = verb_dropped(i, line);

        on_death(w, id);
        return dropped;
    }
    /* the worker did it and the ledger cannot say so, so a restart would lose it: the controller hears */
    if (resp_code(reply) >= 0 && ledger_verb(i, line) != 0)
    {
        free(reply);
        return sup_resp(ERR_MEMORY_ALLOCATION);
    }
    return reply;
}

char *sup_remove(int id)
{
    instance_t *i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL;
    worker_t *w;
    char line[32], *reply = NULL;
    int rc;

    if (!i)
        return sup_resp(SUCCESS);   /* mod-host's remove of an instance it does not hold is not an error */
    w = i->w;
    if (w->state == W_UP)
    {
        snprintf(line, sizeof(line), EFFECT_REMOVE, id);
        rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
        if (rc != RPC_OK)
        {
            on_death(w, rc == RPC_DIED ? id : -1);
            /* the worker is gone with the instance in it: the removal stands, whoever else it held is back later */
            if (g_inst[id] == NULL || g_inst[id]->w == NULL)
                return sup_resp(SUCCESS);
            w = i->w;
        }
        else if (resp_code(reply) < 0)
            return reply;
        else
            free(reply);
    }
    relay_instance_gone(id);
    worker_detach(w, i);
    g_inst[id] = NULL;
    chain_leave(i);
    ckpt_forget(id);
    instance_free(i);
    if (w->ninst == 0)
        worker_retire(w);
    else if (w->chain)
        chain_tell(w);
    return sup_resp(SUCCESS);
}

char *sup_remove_all(void)
{
    int id;

    for (id = 0; id < MAX_INSTANCE; id++)
        if (g_inst[id])
        {
            free(sup_remove(id));
        }
    return sup_resp(SUCCESS);
}

char *sup_connect(const char *verb, const char *line, const char *port_a, const char *port_b)
{
    instance_t *a = by_client(port_a), *b = by_client(port_b);
    worker_t *w = NULL;
    char *reply = NULL, ledger[512];
    int rc, n;

    if (a && a->w->state == W_UP)
        w = a->w;
    else if (b && b->w->state == W_UP)
        w = b->w;
    else if (!a && !b)
        for (n = 0; n < g_nworkers && !w; n++)
            if (g_workers[n]->state == W_UP)
                w = g_workers[n];
    if (!w)
        return (a || b) ? refuse_worker((a ? a : b)->w) : sup_resp(ERR_INVALID_OPERATION);
    rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc != RPC_OK)
    {
        on_death(w, -1);
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP);
    }
    if (resp_code(reply) >= 0)
    {
        snprintf(ledger, sizeof(ledger), EFFECT_CONNECT, port_a, port_b);
        if (verb_is(verb, EFFECT_CONNECT))
        {
            /* connected, and the books cannot say so, so a restart would lose it: the controller hears */
            if ((a && conn_add(a, ledger) != 0) || (b && conn_add(b, ledger) != 0))
            {
                free(reply);
                return sup_resp(ERR_MEMORY_ALLOCATION);
            }
        }
        else
        {
            if (a)
                conn_del(a, ledger);
            if (b)
                conn_del(b, ledger);
        }
    }
    return reply;
}

char *sup_broadcast(const char *line)
{
    char *first = NULL, *reply = NULL;
    int n, rc, id;
    worker_t *list[1024];
    int count = g_nworkers < 1024 ? g_nworkers : 1024;

    memcpy(list, g_workers, count * sizeof(worker_t *));
    for (n = 0; n < count; n++)
    {
        worker_t *w = list[n];

        if (w->state != W_UP)
            continue;
        rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
        if (rc != RPC_OK)
        {
            on_death(w, -1);
            continue;
        }
        if (!first || (resp_code(first) >= 0 && resp_code(reply) < 0))
        {
            free(first);
            first = reply;
        }
        else
            free(reply);
    }
    if (verb_is(line, STATE_LOAD) && first && resp_code(first) >= 0)
        for (id = 0; id < MAX_INSTANCE; id++)
            if (g_inst[id])
            {
                g_inst[id]->dirty = 1;
                g_inst[id]->changed_ms = proc_now_ms();
            }
    return first ? first : sup_resp(SUCCESS);
}

/* the words of a line by mod-host's own tokenizer, quotes and \" read as the worker reads them; the count in *count */
static char **words(char *copy, int *count)
{
    char **word = strarr_split(copy);

    for (*count = 0; word && word[*count]; (*count)++)
        ;
    return word;
}

const char *sup_instance_uri(int id)
{
    return (id >= 0 && id < MAX_INSTANCE && g_inst[id]) ? g_inst[id]->uri : NULL;
}

const char *sup_instance_search(int id)
{
    return (id >= 0 && id < MAX_INSTANCE && g_inst[id]) ? search_of(g_inst[id]->fmt) : NULL;
}

char *sup_instance_verb(const char *line, int ledger)
{
    char *copy = strdup(line), **word, *end, *reply;
    instance_t *i = NULL;
    int count;
    long id;

    if (!copy)
        return sup_resp(ERR_MEMORY_ALLOCATION);
    word = words(copy, &count);
    id = count > 1 ? strtol(word[1], &end, 10) : -1;
    if (count < 2 || *end || end == word[1])
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (!(i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL))
        reply = sup_resp(ERR_INSTANCE_NON_EXISTS);
    else if (!strcmp(word[0], OMX_VERB_TRACK_INFO) && !phd_track_info_valid(word, count))
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (phd_is_note_verb(word[0]) && !phd_note_valid(word, count))
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (format_at(i->fmt)->native_instance_verbs)
    {
        reply = sup_call(id, line);
        if (ledger == PHD_LEDGER_REPLACE && resp_code(reply) >= 0 && g_inst[id] == i)
        {
            char *kept = strdup(line);

            if (kept)
            {
                free(i->track_info);
                i->track_info = kept;
            }
            else
            {
                free(reply);
                reply = sup_resp(ERR_MEMORY_ALLOCATION);
            }
        }
    }
    /* a format whose worker has none of these: the daemon answers, and nothing goes to the worker */
    else if (!strcmp(word[0], OMX_VERB_TRACK_INFO))
    {
        char *kept = strdup(line);

        if (kept)
        {
            free(i->track_info);
            i->track_info = kept;
        }
        reply = sup_resp(kept ? SUCCESS : ERR_MEMORY_ALLOCATION);
    }
    else if (!strcmp(word[0], OMX_VERB_REMOTE_PAGES))
        reply = count != 2 ? sup_resp(ERR_INVALID_OPERATION) :
                format_at(i->fmt)->remote_pages ? format_at(i->fmt)->remote_pages(id) : sup_resp(0);
    else if (!strcmp(word[0], OMX_VERB_REMOTE_PAGE_GET) && format_at(i->fmt)->remote_page_get)
    {
        long page = count == 3 ? strtol(word[2], &end, 10) : -1;

        reply = count == 3 && !*end && end != word[2] && page >= 0 && page < INT_MAX ?
                format_at(i->fmt)->remote_page_get(id, (int)page) : sup_resp(ERR_INVALID_OPERATION);
    }
    else if (!strcmp(word[0], OMX_VERB_PARAM_INFO))
        reply = count == 3 ? format_at(i->fmt)->param_info(id, word[2]) : sup_resp(ERR_INVALID_OPERATION);
    else if (phd_is_note_verb(word[0]))
        reply = sup_resp(OMX_REPLY_HOST_NOTES_BY_JACK_RESP);
    else if (!strcmp(word[0], OMX_VERB_PRESET_LIST) || !strcmp(word[0], OMX_VERB_PRESET_GET))
        reply = sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_PRESET_LIST_RESP);
    else
        reply = sup_resp(ERR_INVALID_OPERATION);
    free(word);
    free(copy);
    return reply;
}

void sup_after_reply(int id, const char *verb)
{
    instance_t *i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL;

    if (i && i->w && i->w->state == W_UP && i->dirty &&
        (verb_is(verb, EFFECT_PRESET_LOAD) || verb_is(verb, EFFECT_PATCH_SET)))
        checkpoint(i->w);
}

/* what is put goes after what the text holds; when memory runs out the text is freed, *buf is NULL, and every later put
 * does nothing, so a caller asks once, at the end */
static void put(char **buf, size_t *used, size_t *cap, const char *fmt, ...)
{
    va_list ap;
    int n;

    while (*buf)
    {
        va_start(ap, fmt);
        n = vsnprintf(*buf + *used, *cap - *used, fmt, ap);
        va_end(ap);
        if (n >= 0 && (size_t)n < *cap - *used)
        {
            *used += n;
            return;
        }
        {
            char *grown = realloc(*buf, *cap * 2);

            if (!grown)
                free(*buf);
            *buf = grown;
            *cap *= 2;
        }
    }
}

static int by_k(const void *a, const void *b)
{
    return (*(worker_t *const *)a)->k - (*(worker_t *const *)b)->k;
}

char *sup_worker_list(void)
{
    size_t used = 0, cap = 256;
    char *buf = malloc(cap);
    int n, m;
    worker_t **sorted = malloc((g_nworkers + 1) * sizeof(worker_t *));

    if (!buf || !sorted)
    {
        free(buf);
        free(sorted);
        return NULL;
    }
    memcpy(sorted, g_workers, g_nworkers * sizeof(worker_t *));
    qsort(sorted, g_nworkers, sizeof(worker_t *), by_k);
    put(&buf, &used, &cap, "resp %d", g_nworkers);
    for (n = 0; n < g_nworkers; n++)
    {
        worker_t *w = sorted[n];

        put(&buf, &used, &cap, " w%d:%d:%s:%s:", w->k, (int)w->pid, format_at(w->fmt)->name, g_state_states[w->state]);
        if (w->core >= 0)
            put(&buf, &used, &cap, "%d:", w->core);
        else
            put(&buf, &used, &cap, PHD_WORD_NONE ":");
        put(&buf, &used, &cap, "%s:%s:", w->thread_pool ? PHD_WORKER_POOL_ON : PHD_WORKER_POOL_QUALIFIED, w->place);
        if (!w->ninst)
            put(&buf, &used, &cap, PHD_WORD_NONE);
        for (m = 0; m < w->ninst; m++)
            put(&buf, &used, &cap, "%s%d%s", m ? "," : "", w->inst[m]->id, w->inst[m]->pin_refused ? PHD_WORKER_PIN_REFUSED : "");
    }
    free(sorted);
    return buf;
}

char *sup_instance_info(int id)
{
    instance_t *i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL;
    meta_t *m;
    char buffer[160];

    if (!i)
        return sup_resp(ERR_INSTANCE_NON_EXISTS);
    m = meta_of(id);
    snprintf(buffer, sizeof(buffer), "resp 0 w%d %d %s %d %d", i->w->k, (int)i->w->pid, g_state_states[i->w->state],
             m->crashes, m->quarantined);
    return strdup(buffer);
}

char *sup_history_get(const char *uri)
{
    char digest[PHD_SHA256_HEX_LEN + 1], *summary, *text;
    const char *bare_uri;

    format_of_uri(uri, &bare_uri);
    if (!history_available())
        return strdup("resp 0 " PHD_WORD_UNAVAILABLE);
    if (pins_digest(bare_uri, digest) != 0 || !(summary = history_summary(bare_uri, digest, utc_now())))
        return strdup("resp 0 " PHD_WORD_NONE);
    text = malloc(strlen(summary) + 8);
    if (text)
        sprintf(text, "resp 0 %s", summary);
    free(summary);
    return text ? text : sup_resp(ERR_MEMORY_ALLOCATION);
}

char *sup_history_clear(const char *uri)
{
    const char *bare_uri = uri;

    if (strcmp(uri, PHD_WORD_ALL))
        format_of_uri(uri, &bare_uri);
    return sup_resp(history_clear(bare_uri) == 0 ? SUCCESS : ERR_INVALID_OPERATION);
}

char *sup_reset(const char *which)
{
    int n, all = !which || !*which || !strcmp(which, PHD_WORD_ALL), found = 0, id;
    int64_t now = proc_now_ms();

    for (n = 0; n < g_nworkers; n++)
    {
        worker_t *w = g_workers[n];
        char name[16];

        snprintf(name, sizeof(name), "w%d", w->k);
        if (!all && strcmp(which, name))
            continue;
        found = 1;
        w->ndeaths = 0;
        if (w->state == W_GIVEN_UP)
        {
            w->state = W_BACKOFF;
            w->next_try_ms = now;
        }
    }
    if (all)
        for (id = 0; id < MAX_INSTANCE; id++)
            g_meta[id].ndeaths = 0;
    return sup_resp(all || found ? SUCCESS : OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_WORKER_RESP);
}

char *sup_quarantine_clear(const char *which)
{
    int id;

    if (!strcmp(which, PHD_WORD_ALL))
    {
        for (id = 0; id < MAX_INSTANCE; id++)
        {
            /* the plans that held a member back for its quarantine are made again, by the tick */
            if (g_meta[id].quarantined)
                plans_replan_for(id);
            g_meta[id].quarantined = 0;
        }
        for (id = 0; id < MAX_INSTANCE; id++)
        {
            int k;

            if (g_chain[id])
                g_chain[id]->rejoin = 1;
            for (k = 0; g_plan[id] && k < g_plan[id]->nseg; k++)
                g_plan[id]->seg[k]->rejoin = 1;
        }
        return sup_resp(SUCCESS);
    }
    id = atoi(which);
    if (id < 0 || id >= MAX_INSTANCE || (!g_inst[id] && !g_meta[id].quarantined))
        return sup_resp(ERR_INSTANCE_NON_EXISTS);
    if (meta_of(id)->quarantined)
        plans_replan_for(id);
    meta_of(id)->quarantined = 0;
    /* a chain's member goes back to its chain: the tick gathers the chain again */
    if (g_inst[id] && g_inst[id]->chain)
        g_inst[id]->chain->rejoin = 1;
    return sup_resp(SUCCESS);
}

char *sup_pin_accept(const char *uri)
{
    const char *fwd;
    int rc;
    int fmt = format_of_uri(uri, &fwd);

    if (!g_conf.require_pins || !conf_pins_first_use(&g_conf))
        return sup_resp(ERR_INVALID_OPERATION);
    rc = pins_accept(format_at(fmt), fwd, search_of(fmt));
    /* the files of an accepted plugin may now be ones the adapter takes */
    if (rc == SUCCESS)
        lv2_refusals_forget(NULL);
    return sup_resp(rc);
}

/* the running instances against the pins just read: one the new pins refuse is not stopped, its worker holds it as it
 * did; it is logged here and marked in worker_list until a pin that holds it is read */
static void pins_recheck(void)
{
    int n, m;

    for (n = 0; n < g_nworkers; n++)
        for (m = 0; m < g_workers[n]->ninst; m++)
        {
            instance_t *i = g_workers[n]->inst[m];
            const char *layout = NULL;
            int code = pins_check(format_at(i->fmt), i->uri, search_of(i->fmt), &layout);

            if (code != SUCCESS && !i->pin_refused)
                fprintf(stderr, "plugin-hostd: instance %d (%s): the reloaded pins refuse it (resp %d); it keeps running\n",
                        i->id, i->uri, code);
            i->pin_refused = code != SUCCESS;
        }
}

char *sup_pin_reload(void)
{
    int rc;

    if (!g_conf.require_pins)
        return sup_resp(ERR_INVALID_OPERATION);
    rc = pins_reload();
    if (rc != SUCCESS)
        return sup_resp(ERR_INVALID_OPERATION);
    /* the files of a plugin changed: the adapter may now take one it refused */
    lv2_refusals_forget(NULL);
    pins_recheck();
    return sup_resp(SUCCESS);
}

void sup_pins_poll(void)
{
    if (g_conf.require_pins && pins_changed())
        free(sup_pin_reload());
}

char *sup_policy_set(const char *format, const char *place)
{
    int f;

    if (!valid_place(place))
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    if (!strcmp(format, PHD_FORMAT_ANY))
    {
        for (f = 0; f < formats_count(); f++)
            snprintf(g_policy[f], sizeof(g_policy[f]), "%s", place);
        return sup_resp(SUCCESS);
    }
    f = format_by_name(format);
    if (f < 0)
        return sup_resp(ERR_INVALID_OPERATION);
    snprintf(g_policy[f], sizeof(g_policy[f]), "%s", place);
    return sup_resp(SUCCESS);
}

char *sup_lv2_worker_set(const char *uri, const char *worker)
{
    const char *fwd;

    format_of_uri(uri, &fwd);
    if (lv2_worker_pick(fwd, worker) != 0)
        return sup_resp(ERR_INVALID_OPERATION);
    lv2_refusals_forget(fwd);
    return sup_resp(SUCCESS);
}

char *sup_pool_config(const char *name, int max)
{
    int n;

    if (!phd_pool_name_valid(name))
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    if (max < 1)
        return sup_resp(ERR_INVALID_OPERATION);
    for (n = 0; n < g_npools; n++)
        if (!strcmp(g_pools[n].name, name))
        {
            g_pools[n].max = max;
            return sup_resp(SUCCESS);
        }
    if (g_npools == POOL_NAMES)
        return sup_resp(ERR_INVALID_OPERATION);
    snprintf(g_pools[g_npools].name, sizeof(g_pools[g_npools].name), "%s", name);
    g_pools[g_npools++].max = max;
    return sup_resp(SUCCESS);
}

char *sup_worker_env(const char *format, const char *cpus, const char *nice)
{
    int f, lo = 0, hi = formats_count() - 1, n;
    worker_env_t env;
    size_t i;

    if (strcmp(format, PHD_FORMAT_ANY))
    {
        lo = hi = format_by_name(format);
        if (lo < 0)
            return sup_resp(ERR_INVALID_OPERATION);
    }
    for (i = 0; strcmp(cpus, PHD_WORD_NONE) && i < strlen(cpus); i++)
        if (!((cpus[i] >= '0' && cpus[i] <= '9') || cpus[i] == ',' || cpus[i] == '-'))
            return sup_resp(ERR_INVALID_OPERATION);
    if (strlen(cpus) >= sizeof(env.cpus) || (strcmp(nice, PHD_WORD_NONE) && (atoi(nice) < -20 || atoi(nice) > 19)))
        return sup_resp(ERR_INVALID_OPERATION);
    for (f = lo; f <= hi; f++)
    {
        if (strcmp(cpus, PHD_WORD_NONE))
        {
            snprintf(g_env[f].cpus, sizeof(g_env[f].cpus), "%s", cpus);
            /* the format's workers run on these cpus now: the policy no longer places them */
            for (n = 0; n < g_nworkers; n++)
                if (g_workers[n]->fmt == f)
                    g_workers[n]->core = -1;
        }
        if (strcmp(nice, PHD_WORD_NONE))
            g_env[f].nice = atoi(nice);
        for (n = 0; n < g_nworkers; n++)
            if (g_workers[n]->fmt == f && g_workers[n]->state == W_UP)
            {
                proc_apply_env(g_workers[n]->pid, &g_env[f]);
                proc_env_report(g_workers[n]->pid, &g_env[f]);
            }
    }
    return sup_resp(SUCCESS);
}

/* ---------------------------------------------------------------- chains */

/* an instance leaves the worker it is in, which is told to remove it once its state is saved; the worker is retired
 * when it holds no one else. The instance is in no worker after it */
static void evict(instance_t *i)
{
    worker_t *w = i->w;
    char line[32], *reply = NULL;
    int rc;

    if (w->state == W_UP)
        checkpoint(w);
    w = i->w;
    if (w->state == W_UP)
    {
        snprintf(line, sizeof(line), EFFECT_REMOVE, i->id);
        rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
        if (rc != RPC_OK)
            on_death(w, -1);
        free(reply);
        w = i->w;
    }
    relay_instance_gone(i->id);
    worker_detach(w, i);
    if (w->ninst == 0)
        worker_retire(w);
}

/* an instance into a fresh worker of its own, started now */
static void to_own(instance_t *i)
{
    worker_t *own = worker_new(i->fmt, PHD_PLACE_OWN);

    /* no memory for a new worker: it goes on running where it is */
    if (!own)
    {
        fprintf(stderr, "plugin-hostd: out of memory, instance %d stays in worker %d\n", i->id, i->w ? i->w->k : -1);
        return;
    }
    evict(i);
    worker_attach(own, i);
    respawn(own);
}

/* an instance that the checkpoint of its eviction found quarantined (its worker died saving its state): it is in no
 * worker, and goes where a quarantined instance goes, a worker of its own that starts after the backoff */
static void park_quarantined(instance_t *i, worker_t *own)
{
    if (worker_join(own) != 0)
        fprintf(stderr, "plugin-hostd: out of memory, instance %d has no worker until it is removed or cleared\n", i->id);
    worker_attach(own, i);
    own->state = W_BACKOFF;
    own->backoff_ms = g_conf.backoff_base_ms;
    own->next_try_ms = proc_now_ms() + g_conf.backoff_base_ms;
}

/* the chain's members that are not quarantined, gathered in order in one new worker and replayed there. The memory
 * comes first: a member moves only when it has somewhere to go, so when memory runs out, -1, each stays where it runs and
 * the tick tries again */
static int chain_form(chain_t *c)
{
    char place[48], word[24];
    worker_t *w = NULL;
    int n, wanted = 0, short_of_memory = 0;

    chain_forming(c);
    chain_word(c, word, sizeof(word));
    snprintf(place, sizeof(place), PHD_PLACE_CHAIN_PREFIX "%s", word);
    for (n = 0; n < c->n; n++)
        wanted += g_inst[c->ids[n]] && !meta_of(c->ids[n])->quarantined;
    if (wanted)
    {
        w = worker_new(chain_row_of(c->ids, c->n), place);
        if (w && worker_reserve(w, wanted) != 0)
        {
            worker_free(w);
            w = NULL;
        }
        if (!w)
        {
            chain_stall_note(c, -1, "memory", ERR_MEMORY_ALLOCATION);
            c->rejoin = 1;
            return -1;
        }
        w->pool = 1;
        w->chain = c;
    }
    for (n = 0; n < c->n; n++)
    {
        instance_t *i = g_inst[c->ids[n]];
        worker_t *spare;

        if (!i || meta_of(i->id)->quarantined)
            continue;
        /* evict can find the member quarantined, and then it needs a worker of its own */
        spare = worker_alloc(i->fmt, PHD_PLACE_OWN);
        if (!spare)
        {
            short_of_memory = 1;
            continue;
        }
        evict(i);
        /* its worker may have died in the checkpoint evict took, and quarantined it */
        if (meta_of(i->id)->quarantined)
        {
            park_quarantined(i, spare);
            continue;
        }
        worker_unused(spare);
        worker_attach(w, i);
    }
    if (c->w && c->w != w)
        c->w->chain = NULL;
    /* every member was found quarantined on its way, or had no memory to move */
    if (w && !w->ninst)
    {
        w->chain = NULL;
        worker_free(w);
        w = NULL;
    }
    c->w = w;
    c->rejoin = short_of_memory;
    if (w)
        respawn(w);
    return 0;
}

/* whether a chain declared again takes its new order (c->ids) in the worker that runs it now: that worker is up, no
 * rejoin is pending, and every member that joins it is in a worker that is up, to save its state, and is of a format
 * whose world the running worker need not be started again for */
static int chain_in_place(const chain_t *c)
{
    int k;

    if (!c->w || c->w->state != W_UP || c->rejoin)
        return 0;
    for (k = 0; k < c->n; k++)
    {
        instance_t *i = g_inst[c->ids[k]];

        if (i->w == c->w || meta_of(i->id)->quarantined)
            continue;
        if (!i->w || i->w->state != W_UP || format_at(i->fmt)->narrow_world)
            return 0;
    }
    return 1;
}

/* the new order in the running worker: each member that joins leaves its worker and is replayed into this one (its
 * add, then the order, then its state alone, its ledger and its connections); no other member is restarted */
static int chain_update(chain_t *c)
{
    worker_t *w = c->w;
    instance_t **join = (chain_forming(c), malloc(c->n * sizeof(instance_t *)));
    char msg[PATH_MAX + 16], dir[PATH_MAX];
    int k, n = 0, nj = 0, rc;

    /* the memory comes first: nothing has moved */
    if (!join || worker_reserve(w, w->ninst + c->n) != 0)
    {
        free(join);
        c->rejoin = 1;
        return -1;
    }
    for (k = 0; k < c->n; k++)
    {
        instance_t *i = g_inst[c->ids[k]];
        worker_t *spare;

        if (i->w == w || meta_of(i->id)->quarantined)
            continue;
        /* evict can find the member quarantined, and then it needs a worker of its own */
        spare = worker_alloc(i->fmt, PHD_PLACE_OWN);
        if (!spare)
        {
            c->rejoin = 1;
            continue;
        }
        evict(i);
        /* its worker may have died in the checkpoint evict took, and quarantined it: it is not replayed here */
        if (meta_of(i->id)->quarantined)
        {
            park_quarantined(i, spare);
            continue;
        }
        worker_unused(spare);
        worker_attach(w, i);
        join[nj++] = i;
    }
    /* the worker holds its members in the chain's order */
    for (k = 0; k < c->n; k++)
        if (g_inst[c->ids[k]]->w == w)
            w->inst[n++] = g_inst[c->ids[k]];
    for (k = 0; k < nj; k++)
        if (replay_add(w, join[k]) < 0)
            goto out;
    if (chain_order_send(w) != RPC_OK)
    {
        on_death(w, -1);
        goto out;
    }
    for (k = 0; k < nj; k++)
        if (!join[k]->unreplayed && join[k]->has_ckpt && ckpt_alone(join[k]->id, dir, sizeof(dir)))
        {
            snprintf(msg, sizeof(msg), STATE_LOAD, dir);
            rc = replay_line(w, msg);
            rm_tree(dir);
            if (rc != RPC_OK)
            {
                on_death(w, join[k]->id);
                goto out;
            }
        }
    for (k = 0; k < nj; k++)
        if (!join[k]->unreplayed && replay_tail(w, join[k]) < 0)
            goto out;
    for (k = 0; k < nj; k++)
    {
        if (join[k]->unreplayed)
            continue;
        if (replay_conns(w, join[k]) < 0)
            goto out;
        event(PHD_EVENT_INSTANCE_RESTORED_FMT, join[k]->id, w->k);
    }
    if (!c->refused)
        chain_formed(w);
out:
    free(join);
    return 0;
}

/* a plugin that may not share a worker: the rule of a pool, while require_pins is on; a chain's worker sees the union of
 * its members' worlds, so what a format pins in a world of its own holds there and is judged by chain_world_found */
static int must_run_own(const instance_t *i)
{
    if (g_conf.require_pins && format_at(i->fmt)->thread_pool && pins_pool_cores(i->uri))
        return 1;
    return g_conf.require_pins && !format_at(i->fmt)->pinned_own_only && conf_pins_first_use(&g_conf) &&
           !pins_in_process(i->uri);
}

/* whether a world holding the m uris of the row can be built for one worker, or none needs building */
static int world_found(int row, const char **uris, int m)
{
    const format_t *f = format_at(row);
    char dir[PATH_MAX], *world;
    int found;

    if (!g_conf.require_pins || !f->pinned_own_only)
        return 1;
    if (!f->narrow_world)
        return 0;
    snprintf(dir, sizeof(dir), "%s/world-check", g_root);
    world = f->narrow_world(&g_conf, dir, uris, m);
    rm_tree(dir);
    found = world != NULL;
    free(world);
    return found;
}

/* while require_pins is on, a chain whose worker's row pins in a world of its own forms only if the row can narrow the
 * worker's world to the union of its members of that row: it is built once in a scratch directory, every one found.
 * -1 when memory runs out */
static int chain_world_found(const int *ids, int n)
{
    int row = chain_row_of(ids, n);
    const format_t *f = format_at(row);
    const char **uris;
    int k, m = 0, found;

    if (!g_conf.require_pins || !f->pinned_own_only)
        return 1;
    if (!f->narrow_world)
        return 0;
    uris = malloc(n * sizeof(char *));
    if (!uris)
        return -1;
    for (k = 0; k < n; k++)
        if (g_inst[ids[k]]->fmt == row)
            uris[m++] = g_inst[ids[k]]->uri;
    found = world_found(row, uris, m);
    free(uris);
    return found;
}

char *sup_chain(int id, const int *ids, int n)
{
    chain_t *c = (id >= 0 && id < MAX_INSTANCE) ? g_chain[id] : NULL;
    int *new_ids, k, m, found, rc;

    if (id < 0 || id >= MAX_INSTANCE || n < PHD_CHAIN_MEMBERS_MIN)
        return sup_resp(ERR_INVALID_OPERATION);
    for (k = 0; k < n; k++)
    {
        instance_t *i = (ids[k] >= 0 && ids[k] < MAX_INSTANCE) ? g_inst[ids[k]] : NULL;

        if (!i)
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE_RESP);
        for (m = 0; m < k; m++)
            if (ids[m] == ids[k])
                return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE_RESP);
        if (i->chain && i->chain != c)
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY_RESP);
        if (!chain_rows_together(i->fmt, g_inst[ids[0]]->fmt))
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT_RESP);
        if (must_run_own(i))
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    }
    found = chain_world_found(ids, n);
    if (found < 0)
        return sup_resp(ERR_MEMORY_ALLOCATION);
    if (!found)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    /* the memory comes first: nothing has moved */
    new_ids = malloc(n * sizeof(int));
    if (!new_ids)
        return sup_resp(ERR_MEMORY_ALLOCATION);
    if (!c)
    {
        c = calloc(1, sizeof(chain_t));
        if (!c)
        {
            free(new_ids);
            return sup_resp(ERR_MEMORY_ALLOCATION);
        }
        c->id = id;
        g_chain[id] = c;
        g_nchains++;
    }
    /* a member the new order leaves out goes back to a worker of its own */
    for (k = 0; k < c->n; k++)
    {
        instance_t *i = g_inst[c->ids[k]];

        for (m = 0; m < n && ids[m] != c->ids[k]; m++)
            ;
        if (m < n || !i)
            continue;
        i->chain = NULL;
        if (c->w && i->w == c->w)
            to_own(i);
    }
    free(c->ids);
    c->ids = new_ids;
    memcpy(c->ids, ids, n * sizeof(int));
    c->n = n;
    for (k = 0; k < n; k++)
        g_inst[ids[k]]->chain = c;
    /* a chain with no memory to form yet is the tick's to try again */
    rc = (chain_in_place(c) ? chain_update(c) : chain_form(c)) == 0 ? SUCCESS : ERR_MEMORY_ALLOCATION;
    /* the worker may have died forming it, and the chain have gone with its members */
    c = g_chain[id];
    if (c && c->refused)
    {
        chain_refused(c);
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP);
    }
    return sup_resp(rc);
}

/* the chain is forgotten, each member in a worker of its own */
static void chain_end(chain_t *c)
{
    int k;

    for (k = 0; k < c->n; k++)
    {
        instance_t *i = g_inst[c->ids[k]];

        if (!i)
            continue;
        i->chain = NULL;
        /* one already alone, quarantined or split, stays where it is */
        if (c->w && i->w == c->w)
            to_own(i);
    }
    chain_free(c);
}

/* the worker would not run the chain as one (its stderr says why): every member had a client of its own in it, which
 * the chain's place does not say. So the chain ends as chain_clear ends it, and nothing is left to read as formed */
static void chain_refused(chain_t *c)
{
    char word[24];

    chain_word(c, word, sizeof(word));
    fprintf(stderr, "plugin-hostd: chain %s: its worker refused it (resp %d); each member runs in a worker of its own\n", word,
            c->refused);
    event(PHD_EVENT_CHAIN_REFUSED_FMT, word, c->refused);
    chain_end(c);
}

char *sup_chain_clear(int id)
{
    chain_t *c = (id >= 0 && id < MAX_INSTANCE) ? g_chain[id] : NULL;

    if (!c)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN_RESP);
    chain_end(c);
    return sup_resp(SUCCESS);
}

char *sup_chain_get(int id)
{
    chain_t *c = (id >= 0 && id < MAX_INSTANCE) ? g_chain[id] : NULL;
    size_t used = 0, cap = 64;
    char *buf;
    int k, any = 0;

    if (!c)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN_RESP);
    buf = malloc(cap);
    if (!buf)
        return NULL;
    if (c->w)
        put(&buf, &used, &cap, "resp 0 w%d ", c->w->k);
    else
        put(&buf, &used, &cap, "resp 0 " PHD_WORD_NONE " ");
    for (k = 0; k < c->n; k++)
        put(&buf, &used, &cap, "%s%d", k ? "," : "", c->ids[k]);
    put(&buf, &used, &cap, " ");
    /* a worker waiting to restart runs none of its members */
    for (k = 0; c->w && c->w->state == W_UP && !c->refused && k < c->w->ninst; k++)
        if (!c->w->inst[k]->unreplayed)
            put(&buf, &used, &cap, "%s%d", any++ ? "," : "", c->w->inst[k]->id);
    if (!any)
        put(&buf, &used, &cap, PHD_WORD_NONE);
    return buf;
}

/* ---------------------------------------------------------------- plans */

/* the id the qualification records name a plugin by: the CLAP id after the '#' of clap:<path>#<id>, else the uri */
static const char *record_id(const char *uri)
{
    const char *hash = strrchr(uri, '#');

    return hash ? hash + 1 : uri;
}

/* What the planner is told of the history of a plugin: the verdicts and the solo cost of its record on this host
 * class, by the rules of src/history.c, and a crash the daemon has seen itself, a quarantine, which no record of a
 * history that is off or blocked can hold. NULL for neither: a plugin with no history is judged by its pin alone. */
static const planner_history_t *plan_history(const char *uri, int quarantined, planner_history_t *h)
{
    char digest[PHD_SHA256_HEX_LEN + 1];
    const history_rec_t *r = pins_digest(uri, digest) == 0 ? history_find(uri, digest) : NULL;
    int any = 0;

    memset(h, 0, sizeof(*h));
    h->cpu_p95_solo = PLANNER_COST_UNKNOWN;
    if (r)
    {
        h->crashed = history_crashed(r, utc_now());
        h->raises_xruns = history_raises_xruns(r);
        /* percent of one core in the record, a fraction of one in the plan; none while it never ran alone */
        if (r->windows_solo > 0)
            h->cpu_p95_solo = r->cpu_p95_solo / 100.0;
        any = 1;
    }
    if (quarantined)
    {
        h->crashed = 1;
        any = 1;
    }
    return any ? h : NULL;
}

/* what a pin's verdict is to the planner */
static int plan_pin(const char *uri)
{
    const char *verdict = pins_verdict(uri);

    if (!verdict)
        return PLANNER_PIN_NONE;
    if (!strcmp(verdict, PHD_PIN_VERDICT_IN_PROCESS))
        return pins_pool_cores(uri) ? PLANNER_PIN_ISOLATED : PLANNER_PIN_IN_PROCESS;
    if (!strcmp(verdict, PHD_PIN_VERDICT_ISOLATED))
        return PLANNER_PIN_ISOLATED;
    if (!strcmp(verdict, PHD_PIN_VERDICT_REFUSED))
        return PLANNER_PIN_REFUSED;
    return PLANNER_PIN_NO_VERDICT;
}

/* the cost the planner reads for a plugin: its record's at group_rate and group_quantum, PLANNER_COST_UNKNOWN for none */
static double plan_cost(const char *uri)
{
    double cost = g_conf.group_rate > 0 && g_conf.group_quantum > 0
                      ? qualcost_read(g_conf.qualification_dir, record_id(uri), g_conf.group_rate, g_conf.group_quantum)
                      : PLANNER_COST_UNKNOWN;

    return cost < 0 ? PLANNER_COST_UNKNOWN : cost;
}

/* the class of the planner of a row: the worker program that runs chains in one client, else the row alone */
static const char *plan_class(int fmt)
{
    const format_t *f = format_at(fmt);
    const char *bin = bin_of(fmt);

    return f->native_chain && bin ? bin : f->name;
}

/* what the planner is told of an instance: its worker program's class, its pin, whether a world can be built for it,
 * its cost and its history */
static void plan_member(const instance_t *i, planner_member_t *m, planner_history_t *h)
{
    memset(m, 0, sizeof(*m));
    m->id = i->id;
    m->klass = plan_class(i->fmt);
    m->pin = plan_pin(i->uri);
    m->world_ok = chain_world_found(&m->id, 1);
    m->cost = plan_cost(i->uri);
    m->history = plan_history(i->uri, meta_of(i->id)->quarantined, h);
}

/* the refusal chain would give the members of a segment of two or more, apart from the ones of the numbers: 0 for none */
static int segment_refusal(const int *ids, int n)
{
    int k;

    for (k = 0; k < n; k++)
    {
        if (!chain_rows_together(g_inst[ids[k]]->fmt, g_inst[ids[0]]->fmt))
            return OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT_RESP;
        if (must_run_own(g_inst[ids[k]]))
            return OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP;
    }
    return chain_world_found(ids, n) ? 0 : OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP;
}

static void plan_free(plan_t *p)
{
    if (!p)
        return;
    free(p->ids);
    free(p->seg);
    free(p->segments);
    free(p->reasons);
    free(p);
}

/* a member is alone in a worker of its own, or is made so */
static void make_alone(instance_t *i)
{
    if (i->w && i->w->ninst == 1 && !i->w->pool && !i->w->chain)
        return;
    to_own(i);
}

/* a text of the planner's, malloc'd */
static char *plan_text(size_t (*format)(const planner_member_t *, const planner_plan_t *, int, char *, size_t),
                       const planner_member_t *m, const planner_plan_t *pp, int refused)
{
    size_t need = format(m, pp, refused, NULL, 0);
    char *text = malloc(need + 1);

    if (text)
        format(m, pp, refused, text, need + 1);
    return text;
}

static size_t segments_text(const planner_member_t *m, const planner_plan_t *pp, int refused, char *buf, size_t size)
{
    (void)refused;
    return planner_format_segments(m, pp, buf, size);
}

/* the plan p, made over the ids, is applied: the running segment of the old plan that did not change is kept, wherever
 * it now stands, the others are dissolved, a member that shares with no one gets a worker of its own, and a segment that
 * is new forms in a worker of its own. p->seg holds the segments of two or more, in plan order. */
static int plan_apply(plan_t *old, plan_t *p, const planner_plan_t *pp, const int *ids)
{
    chain_t **at = calloc(pp->nseg, sizeof(chain_t *)), **was = NULL, **fresh = calloc(pp->nseg, sizeof(chain_t *));
    char *kept = NULL, *formed = calloc(pp->nseg, 1);
    int k, j, first, nwas = old ? old->nseg : 0;

    if (nwas)
    {
        was = malloc(nwas * sizeof(chain_t *));
        kept = calloc(nwas, 1);
        if (was)
            memcpy(was, old->seg, nwas * sizeof(chain_t *));
    }
    if (!at || !fresh || !formed || (nwas && (!was || !kept)))
        goto no_memory;
    /* the memory comes first: nothing has moved. A segment that turns out to be a running one gives its chain back below */
    for (k = 0; k < pp->nseg; k++)
        if (pp->seg_len[k] > 1)
        {
            chain_t *c = calloc(1, sizeof(chain_t));

            fresh[k] = c;
            if (c)
            {
                c->id = p->id;
                c->planned = 1;
                c->seg = k;
                c->n = pp->seg_len[k];
                c->ids = malloc(c->n * sizeof(int));
            }
            if (!c || !c->ids)
                goto no_memory;
        }
    for (k = 0, first = 0; k < pp->nseg; first += pp->seg_len[k++])
        for (j = 0; pp->seg_len[k] > 1 && j < nwas && !at[k]; j++)
            if (!kept[j] && was[j]->n == pp->seg_len[k] && !memcmp(was[j]->ids, ids + first, pp->seg_len[k] * sizeof(int)))
            {
                kept[j] = 1;
                at[k] = was[j];
                at[k]->seg = k;
                if (at[k]->w)
                {
                    char word[24];

                    chain_word(at[k], word, sizeof(word));
                    snprintf(at[k]->w->place, sizeof(at[k]->w->place), PHD_PLACE_CHAIN_PREFIX "%s", word);
                }
            }
    for (j = 0; j < nwas; j++)
        if (!kept[j])
        {
            chain_t *c = was[j];

            /* a member the new plan leaves out goes back to a worker of its own, as one chain leaves out does */
            for (k = 0; k < c->n; k++)
            {
                instance_t *i = g_inst[c->ids[k]];
                int in_plan = 0, u;

                for (u = 0; u < p->n; u++)
                    in_plan |= ids[u] == c->ids[k];
                if (i && !in_plan)
                {
                    i->chain = NULL;
                    if (c->w && i->w == c->w)
                        to_own(i);
                }
            }
            chain_free(c);
        }
    free(was);
    free(kept);
    for (k = 0, first = 0; k < pp->nseg; first += pp->seg_len[k++])
        if (pp->seg_len[k] == 1)
            make_alone(g_inst[ids[first]]);
    for (k = 0, first = 0; k < pp->nseg; first += pp->seg_len[k++])
        if (pp->seg_len[k] > 1 && !at[k])
        {
            chain_t *c = fresh[k];

            memcpy(c->ids, ids + first, c->n * sizeof(int));
            for (j = 0; j < c->n; j++)
                g_inst[c->ids[j]]->chain = c;
            at[k] = c;
            formed[k] = 1;
        }
    for (k = 0; k < pp->nseg; k++)
        if (fresh[k] && at[k] != fresh[k])
        {
            free(fresh[k]->ids);
            free(fresh[k]);
        }
    for (k = 0; k < pp->nseg; k++)
        if (at[k])
            p->seg[p->nseg++] = at[k];
    /* a segment that did not change but whose members a death split is gathered again: that is what a plan made again
     * after the regroup timer is for */
    for (k = 0; k < pp->nseg; k++)
        if (at[k] && !formed[k] && !chain_whole(at[k]))
            formed[k] = 1;
    /* the new plan stands before its segments form: a member that leaves one finds it there */
    g_plan[p->id] = p;
    for (k = 0; k < pp->nseg; k++)
        if (formed[k])
            chain_form(at[k]);
    free(formed);
    free(at);
    free(fresh);
    return 0;

no_memory:
    for (k = 0; fresh && k < pp->nseg; k++)
        if (fresh[k])
        {
            free(fresh[k]->ids);
            free(fresh[k]);
        }
    free(fresh);
    free(was);
    free(kept);
    free(formed);
    free(at);
    return -1;
}

/* a worker refused a segment of the plan: the plan is refused as a whole, as a segment the daemon can see beforehand
 * refuses it, but its members have moved, so every segment ends and each member runs in a worker of its own. The plan is
 * kept to be read back, every member's reason plan-refused:<code>. The code, 0 when no worker refused. */
static int plan_worker_refused(plan_t *p)
{
    const int code = OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP;
    size_t used = 0, cap = 64;
    char *reasons;
    int k, refused = 0;

    for (k = 0; k < p->nseg; k++)
        refused |= p->seg[k]->refused != 0;
    if (!refused)
        return 0;
    while (p->nseg)
    {
        chain_t *c = p->seg[0];

        if (c->refused)
            chain_refused(c);
        else
            chain_end(c);
    }
    reasons = malloc(cap);
    if (reasons)
    {
        reasons[0] = '\0';
        for (k = 0; k < p->n; k++)
            put(&reasons, &used, &cap, "%s%d:%s:%d", k ? "," : "", p->ids[k], planner_reason_word(PLANNER_REASON_PLAN_REFUSED), code);
        free(p->reasons);
        p->reasons = reasons;
        event(PHD_EVENT_PLAN_REASON_FMT, p->id, p->reasons);
    }
    return code;
}

/* the planner's settings, the daemon's */
static void plan_settings(planner_settings_t *s)
{
    s->require_pins = g_conf.require_pins;
    s->pins_first_use = conf_pins_first_use(&g_conf);
    s->grouping_on = conf_grouping_on(&g_conf);
    s->group_max = g_conf.group_max;
    s->group_cost_max = g_conf.group_cost_max / 100.0;
    s->history_unavailable = !history_available();
}

/* the members are planned and the plan is applied, or only kept while grouping is off or a segment cannot be formed; the
 * plan before it is dropped, its segments that did not change are the new plan's. *refused is the code of the refusal, 0
 * for none. The members are checked by the caller. */
static plan_t *plan_run(int id, const int *ids, int n, int *code)
{
    plan_t *old = g_plan[id], *p;
    planner_member_t m[PLANNER_MEMBERS_MAX];
    planner_history_t h[PLANNER_MEMBERS_MAX];
    planner_settings_t s;
    planner_plan_t pp;
    int k, first, refused = 0;

    for (k = 0; k < n; k++)
        plan_member(g_inst[ids[k]], &m[k], &h[k]);
    plan_settings(&s);
    planner_plan(&s, m, n, &pp);

    /* every segment is checked before any is made: a plan that cannot be formed moves nothing */
    for (k = 0, first = 0; s.grouping_on && !refused && k < pp.nseg; first += pp.seg_len[k++])
        if (pp.seg_len[k] > 1)
            refused = segment_refusal(ids + first, pp.seg_len[k]);

    p = calloc(1, sizeof(*p));
    if (!p)
    {
        *code = ERR_MEMORY_ALLOCATION;
        return NULL;
    }
    p->id = id;
    p->n = n;
    p->ids = malloc(n * sizeof(int));
    if (p->ids)
        memcpy(p->ids, ids, n * sizeof(int));
    p->seg = calloc(pp.nseg, sizeof(chain_t *));
    p->segments = plan_text(segments_text, m, &pp, 0);
    p->reasons = plan_text(planner_format_reasons, m, &pp, refused);

    /* no memory for the plan: nothing has moved, and the plan before it stands */
    if (!p->ids || !p->seg || !p->segments || !p->reasons ||
        (s.grouping_on && !refused && plan_apply(old, p, &pp, ids) != 0))
    {
        plan_free(p);
        *code = ERR_MEMORY_ALLOCATION;
        return NULL;
    }
    if (!s.grouping_on || refused)
    {
        /* nothing moves: the segments that run stay as they are, and the plan is kept to be read back */
        if (old)
        {
            memcpy(p->seg, old->seg, old->nseg * sizeof(chain_t *));
            p->nseg = old->nseg;
        }
        g_plan[id] = p;
    }
    if (!old || strcmp(old->segments, p->segments) || strcmp(old->reasons, p->reasons))
        event(PHD_EVENT_PLAN_REASON_FMT, id, p->reasons);
    if (old)
    {
        /* the old plan's list is dropped, not its chains: they are p's now, or were freed */
        old->nseg = 0;
        plan_free(old);
    }
    else
        g_nplans++;
    *code = refused ? refused : plan_worker_refused(p);
    return p;
}

/* the cores word of plan and plan_get: the segments with each member replaced by the core of the worker that runs it now,
 * - for one the placement did not pin; malloc'd */
static char *plan_cores(const char *segments)
{
    size_t used = 0, cap = 64;
    char *buf = malloc(cap), *end;
    const char *p = segments;

    if (!buf)
        return NULL;
    buf[0] = '\0';
    while (*p)
    {
        if (*p >= '0' && *p <= '9')
        {
            long id = strtol(p, &end, 10);
            const instance_t *i = id < MAX_INSTANCE ? g_inst[id] : NULL;

            if (i && i->w && i->w->core >= 0)
                put(&buf, &used, &cap, "%d", i->w->core);
            else
                put(&buf, &used, &cap, PHD_WORD_NONE);
            p = end;
        }
        else
            put(&buf, &used, &cap, "%c", *p++);
    }
    return buf;
}

char *sup_plan(int id, const int *ids, int n)
{
    plan_t *p;
    int k, j, refused;
    char *reply, *cores;
    size_t used = 0, cap = 64;

    if (id < 0 || id >= MAX_INSTANCE || n < PHD_CHAIN_MEMBERS_MIN || n > PLANNER_MEMBERS_MAX)
        return sup_resp(ERR_INVALID_OPERATION);
    for (k = 0; k < n; k++)
    {
        instance_t *i = (ids[k] >= 0 && ids[k] < MAX_INSTANCE) ? g_inst[ids[k]] : NULL;

        if (!i)
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE_RESP);
        for (j = 0; j < k; j++)
            if (ids[j] == ids[k])
                return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE_RESP);
        /* the member of a chain, or of the plan of another chain, is not this plan's to place */
        if (i->chain && !(i->chain->planned && i->chain->id == id))
            return sup_resp(OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY_RESP);
    }
    p = plan_run(id, ids, n, &refused);
    if (refused)
        return sup_resp(refused);
    cores = plan_cores(p->segments);
    reply = cores ? malloc(cap) : NULL;
    if (reply)
        put(&reply, &used, &cap, "resp 0 %s %s", p->segments, cores);
    free(cores);
    return reply;
}

/* the plan of a chain is made again over the members it was given: after a quarantine, which the history now knows, or
 * when the regroup timer is due. A member that is gone, or taken by a chain of the controller's, leaves the plan as it
 * was: it is the controller's to declare again. */
static void plan_again(int id)
{
    plan_t *p = g_plan[id];
    int *ids, k, refused;

    p->replan = 0;
    p->regroup_ms = 0;
    for (k = 0; k < p->n; k++)
    {
        instance_t *i = g_inst[p->ids[k]];

        if (!i || (i->chain && !(i->chain->planned && i->chain->id == id)))
            return;
    }
    ids = malloc(p->n * sizeof(int));
    if (!ids)
    {
        p->replan = 1;
        return;
    }
    memcpy(ids, p->ids, p->n * sizeof(int));
    plan_run(id, ids, p->n, &refused);
    free(ids);
}

/* every plan that holds the instance is to be made again by the tick */
static void plans_replan_for(int id)
{
    int n, k;

    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
        for (k = 0; g_plan[n] && k < g_plan[n]->n; k++)
            if (g_plan[n]->ids[k] == id)
                g_plan[n]->replan = 1;
}

/* the regroup timer of every plan that holds the instance: armed (arm), or put off when it is already running; a
 * history_regroup_s of 0 keeps it off */
static void plans_regroup(int id, int64_t now, int arm)
{
    int n, k;

    if (g_conf.history_regroup_s <= 0)
        return;
    for (n = 0; g_nplans && n < MAX_INSTANCE; n++)
        for (k = 0; g_plan[n] && k < g_plan[n]->n; k++)
            if (g_plan[n]->ids[k] == id && (arm || g_plan[n]->regroup_ms))
                g_plan[n]->regroup_ms = now + (int64_t)g_conf.history_regroup_s * 1000;
}

char *sup_plan_get(int id)
{
    plan_t *p = (id >= 0 && id < MAX_INSTANCE) ? g_plan[id] : NULL;
    size_t used = 0, cap = 64;
    char *buf, *cores;

    if (!p)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_PLAN_RESP);
    cores = plan_cores(p->segments);
    buf = cores ? malloc(cap) : NULL;
    if (buf)
        put(&buf, &used, &cap, "resp 0 %s %s %s", p->segments, p->reasons, cores);
    free(cores);
    return buf;
}

char *sup_plan_clear(int id)
{
    plan_t *p = (id >= 0 && id < MAX_INSTANCE) ? g_plan[id] : NULL;
    int j;

    if (!p)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_PLAN_RESP);
    while (p->nseg)
    {
        chain_t *c = p->seg[p->nseg - 1];

        for (j = 0; j < c->n; j++)
        {
            instance_t *i = g_inst[c->ids[j]];

            if (!i)
                continue;
            i->chain = NULL;
            /* one already alone, quarantined or split, stays where it is */
            if (c->w && i->w == c->w)
                to_own(i);
        }
        chain_free(c);
    }
    /* the members that share with no one are alone already: a plan that is cleared leaves them where they stand */
    g_plan[id] = NULL;
    g_nplans--;
    plan_free(p);
    return sup_resp(SUCCESS);
}

/* ---------------------------------------------------------------- estimate */

/* the row an add of the uri would run on, and in *fwd the uri as its worker is given it; -1 for none */
static int estimate_row(const char *uri, const char **fwd)
{
    int fmt = format_of_uri(uri, fwd);

    if (fmt < 0 || (fmt = format_route(&g_conf, fmt, *fwd)) < 0)
        return -1;
    if (format_at(fmt)->adapter && !proc_have_binary(bin_of(fmt)) && lv2_worker_is_auto(&g_conf, *fwd))
        fmt = format_by_name(PHD_FORMAT_LV2);
    return fmt;
}

/* the plugin is installed: its format tells its binary and the binary is there; a format that tells none is believed */
static int estimate_installed(int fmt, const char *uri)
{
    const format_t *f = format_at(fmt);
    char path[PATH_MAX];

    if (!f->binary)
        return 1;
    return f->binary(uri, search_of(fmt), path, sizeof(path)) == 0 && access(path, F_OK) == 0;
}

/* the Pss in bytes of the worker the plugin ran alone in, on this host class, for the binary its pin holds; -1 for none */
static double estimate_ram(const char *uri)
{
    char digest[PHD_SHA256_HEX_LEN + 1];
    const history_rec_t *r = pins_digest(uri, digest) == 0 ? history_find(uri, digest) : NULL;

    return r && r->windows_solo > 0 && r->pss_mb_solo > 0 ? r->pss_mb_solo * 1024.0 * 1024.0 : -1.0;
}

/* what the plugins running now hold, in bytes: the Pss of every worker; -1 when one cannot be read, which is unknown */
static double estimate_ram_used(void)
{
    double bytes = 0;
    int k;

    for (k = 0; k < g_nworkers; k++)
    {
        long long kb;

        if (g_workers[k]->pid <= 0)
            continue;
        if (proc_pss_kb(g_workers[k]->pid, &kb) != 0)
            return -1.0;
        bytes += (double)kb * 1024.0;
    }
    return bytes;
}

/* What these members would add, in bytes, and in *unknown how many have no figure. A plan's segment is one process, so
 * what instances of one plugin share is counted once in a segment: the first instance there takes its whole figure and a
 * later one its own part. Two segments are two processes, each loading it again. Members with no figure add nothing here
 * and are counted, so a client says what is missing rather than read it as 0. */
static double estimate_ram_added(int rate, int quantum, const char *const *uris, const planner_member_t *m, const planner_plan_t *pp,
                                 int n, int *unknown)
{
    double kb = 0;
    int seg, at = 0, placed = 0;

    for (seg = 0; seg < pp->nseg; seg++)
    {
        int first = at, end = at + pp->seg_len[seg];

        for (; at < end; at++, placed++)
        {
            const char *fwd = uris[m[at].id];
            qualcost_memory_t mem;
            int j, shared = 0;

            format_of_uri(uris[m[at].id], &fwd);
            if (qualcost_memory(g_conf.qualification_dir, record_id(fwd), rate, quantum, &mem) != 0)
            {
                (*unknown)++;
                continue;
            }
            for (j = first; j < at; j++)
                if (!strcmp(uris[m[j].id], uris[m[at].id]))
                    shared = 1;
            kb += shared ? mem.per_instance_kb : mem.first_kb;
        }
    }
    /* a member that is placed nowhere has no figure either */
    *unknown += n - placed;
    return kb * 1024.0;
}

char *sup_estimate(int rate, int quantum, const char *const *uris, int n)
{
    planner_member_t m[PLANNER_MEMBERS_MAX];
    planner_history_t h[PLANNER_MEMBERS_MAX];
    planner_settings_t s;
    planner_plan_t pp;
    double latency = 0, median_ns = 0, ram = 0;
    int k, planned = 0, unknown = 0, ram_every = 1, workers = 0, ram_unknown = 0;
    size_t used = 0, cap = 128, lused = 0, lcap = 64;
    char ram_word[32], used_word[32], added_word[32], budget_word[32], *list, *reply;
    double ram_used, ram_added = 0;

    if (rate <= 0 || quantum <= 0 || n < 1 || n > PLANNER_MEMBERS_MAX)
        return sup_resp(ERR_INVALID_OPERATION);
    list = malloc(lcap);
    if (!list)
        return NULL;
    list[0] = '\0';
    for (k = 0; k < n; k++)
    {
        const char *fwd = uris[k];
        int fmt = estimate_row(uris[k], &fwd), code = 0;
        qualcost_cell_t cell;
        double bytes;

        if (fmt < 0 || !estimate_installed(fmt, fwd))
            code = OMX_REPLY_PLUGIN_HOSTD_UNKNOWN_PLUGIN_RESP;
        else
            switch (qualcost_cell(g_conf.qualification_dir, record_id(fwd), rate, quantum, &cell))
            {
            case QUALCOST_CELL_FOUND:
                latency += cell.latency_frames;
                median_ns += cell.median_ns;
                break;
            case QUALCOST_CELL_NO_RECORD:
                code = OMX_REPLY_PLUGIN_HOSTD_NO_RECORD_RESP;
                break;
            default:
                code = OMX_REPLY_PLUGIN_HOSTD_NO_CELL_RESP;
            }
        if (code)
            put(&list, &lused, &lcap, "%s%d:%d", unknown++ ? "," : "", k, code);
        bytes = fmt < 0 ? -1.0 : estimate_ram(fwd);
        if (bytes < 0)
            ram_every = 0;
        else
            ram += bytes;
        /* a plugin that is not installed is placed nowhere: it cannot be added */
        if (code == OMX_REPLY_PLUGIN_HOSTD_UNKNOWN_PLUGIN_RESP)
            continue;
        memset(&m[planned], 0, sizeof(m[planned]));
        m[planned].id = k;
        m[planned].klass = plan_class(fmt);
        m[planned].pin = plan_pin(fwd);
        m[planned].world_ok = world_found(fmt, &fwd, 1);
        m[planned].cost = plan_cost(fwd);
        m[planned].history = plan_history(fwd, 0, &h[planned]);
        planned++;
    }
    if (planned)
    {
        plan_settings(&s);
        planner_plan(&s, m, planned, &pp);
        workers = pp.nseg;
        ram_added = estimate_ram_added(rate, quantum, uris, m, &pp, n, &ram_unknown);
    }
    else
        ram_unknown = n;
    ram_used = estimate_ram_used();
    if (ram_used < 0)
        snprintf(used_word, sizeof(used_word), PHD_WORD_NONE);
    else
        snprintf(used_word, sizeof(used_word), "%.0f", ram_used);
    /* no member has a figure: nothing is known, which is not the same as nothing added */
    if (ram_unknown == n)
        snprintf(added_word, sizeof(added_word), PHD_WORD_NONE);
    else
        snprintf(added_word, sizeof(added_word), "%.0f", ram_added);
    if (g_conf.ram_budget_mb > 0)
        snprintf(budget_word, sizeof(budget_word), "%lld", (long long)g_conf.ram_budget_mb * 1024LL * 1024LL);
    else
        snprintf(budget_word, sizeof(budget_word), PHD_WORD_NONE);
    if (ram_every)
        snprintf(ram_word, sizeof(ram_word), "%.0f", ram);
    else
        snprintf(ram_word, sizeof(ram_word), PHD_WORD_NONE);
    /* a member's cost per block over the block's duration is its nanoseconds per sample times the rate, over 1e9 */
    reply = list ? malloc(cap) : NULL;
    if (reply)
        put(&reply, &used, &cap, "resp 0 %.0f %.2f %s %d %d %s %s %s %s %d", latency, median_ns * rate / 1e9 * 100.0, ram_word, workers,
        unknown, unknown ? list : PHD_WORD_NONE, used_word, added_word, budget_word, ram_unknown);
    free(list);
    return reply;
}

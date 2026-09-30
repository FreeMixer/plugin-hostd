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

#include <dirent.h>
#include <ftw.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <host-errors.h>
#include <mod-host.h>
#include <socket.h>

#include "supervisor.h"
#include "verbs.h"

#define ATTRIBUTED  (-2)    /* on_death: the culprit is already dealt with, only schedule */
#define POOL_NAMES  32
#define CONNECT_RETRY_MS PHD_CONNECT_RETRY_MS

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
static meta_t *g_meta[MAX_INSTANCE];
static char g_root[PATH_MAX], g_ckpt[PATH_MAX];
static char g_policy[FMT_COUNT][48];
static poolcfg_t g_pools[POOL_NAMES];
static int g_npools;
static worker_env_t g_env[FMT_COUNT];

static const char *const g_fmt_name[FMT_COUNT] = {
#define X(id, name) name,
    PHD_FORMATS(X)
#undef X
};
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
    { MIDI_LEARN, KIND_HOST, 0 },
    { MIDI_MAP, KIND_HOST, 0 },
    { MIDI_UNMAP, KIND_HOST, 0 },
    { CC_MAP, KIND_HOST, 0 },
    { CC_UNMAP, KIND_HOST, 0 },
    { CC_VALUE_SET, KIND_HOST, 0 },
    { CV_MAP, KIND_HOST, 0 },
    { CV_UNMAP, KIND_HOST, 0 },
};

static void event(const char *fmt, ...)
{
    char line[1024];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    socket_send_feedback(line);
}

char *sup_resp(int code)
{
    char buffer[32];

    snprintf(buffer, sizeof(buffer), "resp %d", code);
    return strdup(buffer);
}

static int resp_code(const char *reply)
{
    return strncmp(reply, "resp ", 5) == 0 ? atoi(reply + 5) : -999;
}

static meta_t *meta_of(int id)
{
    if (!g_meta[id])
        g_meta[id] = calloc(1, sizeof(meta_t));
    return g_meta[id];
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

/* *replaced is the line a keyed entry gave up, NULL when the entry is new; the caller owns it */
static void tail_add(instance_t *i, const char *line, const char *key, int kind, char **replaced)
{
    int n;

    *replaced = NULL;
    if (key)
        for (n = 0; n < i->ntail; n++)
            if (i->tail[n].key && !strcmp(i->tail[n].key, key))
            {
                *replaced = i->tail[n].line;
                i->tail[n].line = strdup(line);
                return;
            }
    if (i->ntail == i->captail)
    {
        i->captail = i->captail ? i->captail * 2 : 16;
        i->tail = realloc(i->tail, i->captail * sizeof(entry_t));
    }
    i->tail[i->ntail].line = strdup(line);
    i->tail[i->ntail].key = key ? strdup(key) : NULL;
    i->tail[i->ntail].kind = kind;
    i->ntail++;
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

static void conn_add(instance_t *i, const char *line)
{
    int n;

    for (n = 0; n < i->nconns; n++)
        if (!strcmp(i->conns[n], line))
            return;
    if (i->nconns == i->capconns)
    {
        i->capconns = i->capconns ? i->capconns * 2 : 8;
        i->conns = realloc(i->conns, i->capconns * sizeof(char *));
    }
    i->conns[i->nconns++] = strdup(line);
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
    free(i);
}

static int ckpt_exists(int id)
{
    char prefix[32];
    size_t n;
    DIR *dir = opendir(g_ckpt);
    struct dirent *entry;
    int found = 0;

    if (!dir)
        return 0;
    n = snprintf(prefix, sizeof(prefix), "effect_%d", id);
    while (!found && (entry = readdir(dir)))
        found = !strncmp(entry->d_name, prefix, n) && (entry->d_name[n] == '\0' || entry->d_name[n] == '.');
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
    char prefix[32], path[PATH_MAX];
    size_t n;
    DIR *dir = opendir(g_ckpt);
    struct dirent *entry;

    if (!dir)
        return;
    n = snprintf(prefix, sizeof(prefix), "effect_%d", id);
    while ((entry = readdir(dir)))
        if (!strncmp(entry->d_name, prefix, n) && (entry->d_name[n] == '\0' || entry->d_name[n] == '.'))
        {
            snprintf(path, sizeof(path), "%s/%s", g_ckpt, entry->d_name);
            rm_tree(path);
        }
    closedir(dir);
}

/* ---------------------------------------------------------------- workers */

static worker_t *worker_new(int fmt, const char *place)
{
    worker_t *w = calloc(1, sizeof(worker_t));

    w->k = g_next_k++;
    w->fmt = fmt;
    w->fd = -1;
    w->state = W_BACKOFF;
    snprintf(w->place, sizeof(w->place), "%s", place);
    w->pool = strncmp(place, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)) == 0;
    if (g_nworkers == g_capworkers)
    {
        g_capworkers = g_capworkers ? g_capworkers * 2 : 16;
        g_workers = realloc(g_workers, g_capworkers * sizeof(worker_t *));
    }
    g_workers[g_nworkers++] = w;
    return w;
}

static void worker_attach(worker_t *w, instance_t *i)
{
    if (w->ninst == w->capinst)
    {
        w->capinst = w->capinst ? w->capinst * 2 : 8;
        w->inst = realloc(w->inst, w->capinst * sizeof(instance_t *));
    }
    w->inst[w->ninst++] = i;
    i->w = w;
}

static void worker_detach(worker_t *w, instance_t *i)
{
    int n;

    for (n = 0; n < w->ninst; n++)
        if (w->inst[n] == i)
        {
            w->inst[n] = w->inst[--w->ninst];
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
    snprintf(path, sizeof(path), "%s/lv2-w%d", g_root, w->k);
    rm_tree(path);
    snprintf(path, sizeof(path), "%s/w%d.log", g_root, w->k);
    unlink(path);
    if (w->fd >= 0)
        close(w->fd);
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
    return fmt == FMT_CLAP ? g_conf.clap_host : g_conf.mod_host;
}

/* an own LV2 worker sees a world of one bundle: LV2_PATH is a directory holding a link to the bundle
 * that names the URI; a pool, and a URI no bundle names, gets the whole set of the settings' lv2_path */
static char *narrow_world(worker_t *w, const char *uri)
{
    char *bundle, *base, dir[PATH_MAX], link_path[PATH_MAX];

    if (w->fmt != FMT_LV2 || w->pool || !uri)
        return NULL;
    bundle = proc_find_lv2_bundle(g_conf.lv2_path, uri);
    if (!bundle)
        return NULL;
    snprintf(dir, sizeof(dir), "%s/lv2-w%d", g_root, w->k);
    mkdir(dir, 0755);
    base = strrchr(bundle, '/');
    snprintf(link_path, sizeof(link_path), "%s/%s", dir, base ? base + 1 : bundle);
    unlink(link_path);
    if (symlink(bundle, link_path) != 0)
    {
        free(bundle);
        return NULL;
    }
    free(bundle);
    return strdup(dir);
}

static int worker_start(worker_t *w, const char *uri)
{
    char logfile[PATH_MAX];
    char *world;
    int rc;

    if (!proc_have_binary(bin_of(w->fmt)))
        return PHD_ERR_NO_BACKEND;
    snprintf(logfile, sizeof(logfile), "%s/w%d.log", g_root, w->k);
    world = narrow_world(w, uri);
    w->state = W_STARTING;
    rc = proc_spawn(&g_conf, bin_of(w->fmt), world ? world : (w->fmt == FMT_LV2 ? g_conf.lv2_path : NULL), &g_env[w->fmt],
                    logfile, &w->pid, &w->port);
    free(world);
    if (rc != 0)
    {
        w->pid = 0;
        return PHD_ERR_WORKER_SPAWN;
    }
    w->fd = proc_connect(&g_conf, w->pid, w->port, logfile);
    if (w->fd < 0)
    {
        proc_stop(w->pid);
        w->pid = 0;
        return PHD_ERR_WORKER_SPAWN;
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

    worker_detach(i->w, i);
    worker_attach(own, i);
    own->from_split = from_split;
    own->state = W_BACKOFF;
    own->backoff_ms = g_conf.backoff_base_ms;
    own->next_try_ms = now + g_conf.backoff_base_ms;
    return own;
}

static void quarantine(instance_t *i, worker_t *w)
{
    meta_t *m = meta_of(i->id);

    if (!m->quarantined)
    {
        m->quarantined = 1;
        event(PHD_EVENT_INSTANCE_QUARANTINED_FMT, i->id, w->k);
    }
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
    int status = 0, n, done = 0;
    char ids[1024], how[32];
    int64_t now = proc_now_ms();

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
                quarantine(culprit, w);
                move_to_own(culprit, now, 0);
            }
            else if (w->ninst > 1)
            {
                while (w->ninst)
                    move_to_own(w->inst[0], now, 1);
            }
        }
    }
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
    w->pend = realloc(w->pend, (w->npend + 1) * sizeof(char *));
    w->pend[w->npend++] = strdup(line);
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

static void replay(worker_t *w, int64_t started)
{
    int n, m, any_ckpt = 0, count = 0;
    char msg[PATH_MAX + 16];

    for (n = 0; n < w->ninst; n++)
    {
        instance_t *i = w->inst[n];

        if (replay_line(w, i->add_line) != RPC_OK)
        {
            on_death(w, i->id);
            return;
        }
        i->has_ckpt = ckpt_exists(i->id);
        any_ckpt |= i->has_ckpt;
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
    {
        instance_t *i = w->inst[n];

        for (m = 0; m < i->ntail; m++)
            if (replay_line(w, i->tail[m].line) != RPC_OK)
            {
                on_death(w, i->id);
                return;
            }
    }
    for (n = 0; n < w->ninst; n++)
    {
        instance_t *i = w->inst[n];

        for (m = 0; m < i->nconns; m++)
        {
            int code;

            if (replay_line_code(w, i->conns[m], &code) != RPC_OK)
            {
                on_death(w, i->id);
                return;
            }
            if (code < 0)
                pend_add(w, i->conns[m]);
        }
        count++;
    }
    w->state = W_UP;
    event(PHD_EVENT_WORKER_RESPAWNED_FMT, w->k, (int)w->pid, count, (int)(proc_now_ms() - started));
    for (n = 0; n < w->ninst; n++)
        event(PHD_EVENT_INSTANCE_RESTORED_FMT, w->inst[n]->id, w->k);
}

static void respawn(worker_t *w)
{
    int64_t started = proc_now_ms();
    int rc = worker_start(w, w->ninst == 1 ? w->inst[0]->uri : NULL);

    if (rc != SUCCESS)
    {
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
}

/* ---------------------------------------------------------------- init and finish */

void sup_init(const conf_t *conf)
{
    int f;

    g_conf = *conf;
    snprintf(g_root, sizeof(g_root), "%s/plugin-hostd", g_conf.state_root);
    mkdir(g_root, 0755);
    snprintf(g_root, sizeof(g_root), "%s/plugin-hostd/%d", g_conf.state_root, (int)getpid());
    rm_tree(g_root);
    mkdir(g_root, 0755);
    snprintf(g_ckpt, sizeof(g_ckpt), "%s/ckpt", g_root);
    mkdir(g_ckpt, 0755);
    for (f = 0; f < FMT_COUNT; f++)
    {
        snprintf(g_policy[f], sizeof(g_policy[f]), PHD_PLACE_OWN);
        proc_env_clear(&g_env[f]);
    }
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
            *unavailable = PHD_ERR_GAVE_UP;
            continue;
        }
        if (w->state != W_UP)
        {
            *unavailable = PHD_ERR_WORKER_SPAWN;
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

char *sup_add(const char *uri, int id, const char *placement, const char *client)
{
    int fmt = strncmp(uri, "clap:", 5) == 0 ? FMT_CLAP : FMT_LV2;
    const char *fwd = (fmt == FMT_LV2 && strncmp(uri, "lv2:", 4) == 0) ? uri + 4 : uri;
    char place[48], line[PATH_MAX + 128], *reply = NULL;
    worker_t *w = NULL;
    meta_t *m;
    int64_t now = proc_now_ms();
    int rc, is_new = 0, full, unavailable;
    instance_t *i;

    if (id < 0 || id >= MAX_INSTANCE)
        return sup_resp(ERR_INSTANCE_INVALID);
    if (g_inst[id])
        return sup_resp(ERR_INSTANCE_ALREADY_EXISTS);
    if (placement && strcmp(placement, PHD_PLACE_DEFAULT) && !valid_place(placement))
        return sup_resp(PHD_ERR_PLACEMENT_INVALID);
    if (!placement || !strcmp(placement, PHD_PLACE_DEFAULT))
        snprintf(place, sizeof(place), "%s", g_policy[fmt]);
    else
        snprintf(place, sizeof(place), "%s", placement);
    m = meta_of(id);
    if (m->quarantined)
        snprintf(place, sizeof(place), PHD_PLACE_OWN);
    if (!proc_have_binary(bin_of(fmt)))
        return sup_resp(PHD_ERR_NO_BACKEND);
    if (recent(m->deaths, &m->ndeaths, now) >= g_conf.storm_deaths)
        return sup_resp(PHD_ERR_GAVE_UP);

    if (!strcmp(place, PHD_PLACE_OWN))
    {
        w = worker_new(fmt, PHD_PLACE_OWN);
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
            is_new = 1;
        }
    }
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
    snprintf(line, sizeof(line), "%.*s %s %d%s%s", verb_len(EFFECT_ADD), EFFECT_ADD, fwd, id, client ? " " : "",
             client ? client : "");
    rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc != RPC_OK)
    {
        /* the worker went with `add` on the wire: the instance is the suspect */
        m->crashes++;
        note_death(m->deaths, &m->ndeaths, now);
        if (w->pool)
        {
            m->quarantined = 1;
            event(PHD_EVENT_INSTANCE_QUARANTINED_FMT, id, w->k);
        }
        on_death(w, ATTRIBUTED);
        return sup_resp(ERR_HOST_INSTANTIATION);
    }
    if (resp_code(reply) < 0)
    {
        if (w->ninst == 0)
            worker_retire(w);
        return reply;
    }
    i = calloc(1, sizeof(instance_t));
    i->id = id;
    i->fmt = fmt;
    i->uri = strdup(fwd);
    i->add_line = strdup(line);
    if (client)
        i->client = strdup(client);
    else
    {
        char name[32];

        snprintf(name, sizeof(name), "effect_%d", id);
        i->client = strdup(name);
    }
    g_inst[id] = i;
    worker_attach(w, i);
    return reply;
}

static char *refuse_worker(worker_t *w)
{
    return sup_resp(w->state == W_GIVEN_UP ? PHD_ERR_GAVE_UP : PHD_ERR_WORKER_SPAWN);
}

static int64_t g_sus_seq;

static void record(instance_t *i, const char *line, char **tok, int ntok)
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
                return;
            if (verb_is(tok[0], EFFECT_PRESET_LOAD))
                tail_drop_state(i);
            tail_add(i, line, key, g_recorded[v].kind, &prev);
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
            return;
        }
}

/* the ledger takes the verb of one forwarded line, if it is one it keeps */
static void ledger_verb(instance_t *i, const char *line)
{
    char *save = NULL, *t, *copy = strdup(line), *tok[16];
    int ntok = 0;

    for (t = strtok_r(copy, " \t", &save); t && ntok < 16; t = strtok_r(NULL, " \t", &save))
        tok[ntok++] = t;
    if (ntok)
        record(i, line, tok, ntok);
    free(copy);
}

/* the verb the worker died on is not replayed: it never entered the ledger, and the controller is told so */
static char *verb_dropped(instance_t *i, const char *line)
{
    event(PHD_EVENT_VERB_DROPPED_FMT, i->id, line);
    return sup_resp(PHD_ERR_VERB_DROPPED);
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
        return sup_resp(PHD_ERR_WORKER_SPAWN);
    }
    if (rc == RPC_DIED)
    {
        char *dropped = verb_dropped(i, line);

        on_death(w, id);
        return dropped;
    }
    if (resp_code(reply) >= 0)
        ledger_verb(i, line);
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
    worker_detach(w, i);
    g_inst[id] = NULL;
    ckpt_forget(id);
    instance_free(i);
    if (w->ninst == 0)
        worker_retire(w);
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
        return sup_resp(PHD_ERR_WORKER_SPAWN);
    }
    if (resp_code(reply) >= 0)
    {
        snprintf(ledger, sizeof(ledger), EFFECT_CONNECT, port_a, port_b);
        if (verb_is(verb, EFFECT_CONNECT))
        {
            if (a)
                conn_add(a, ledger);
            if (b)
                conn_add(b, ledger);
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

void sup_after_reply(int id, const char *verb)
{
    instance_t *i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL;

    if (i && i->w && i->w->state == W_UP && i->dirty &&
        (verb_is(verb, EFFECT_PRESET_LOAD) || verb_is(verb, EFFECT_PATCH_SET)))
        checkpoint(i->w);
}

static void put(char **buf, size_t *used, size_t *cap, const char *fmt, ...)
{
    va_list ap;
    int n;

    for (;;)
    {
        va_start(ap, fmt);
        n = vsnprintf(*buf + *used, *cap - *used, fmt, ap);
        va_end(ap);
        if (n >= 0 && (size_t)n < *cap - *used)
        {
            *used += n;
            return;
        }
        *buf = realloc(*buf, *cap *= 2);
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

    memcpy(sorted, g_workers, g_nworkers * sizeof(worker_t *));
    qsort(sorted, g_nworkers, sizeof(worker_t *), by_k);
    put(&buf, &used, &cap, "resp %d", g_nworkers);
    for (n = 0; n < g_nworkers; n++)
    {
        worker_t *w = sorted[n];

        put(&buf, &used, &cap, " w%d:%d:%s:%s:%s:", w->k, (int)w->pid, g_fmt_name[w->fmt], g_state_states[w->state], w->place);
        if (!w->ninst)
            put(&buf, &used, &cap, PHD_WORD_NONE);
        for (m = 0; m < w->ninst; m++)
            put(&buf, &used, &cap, "%s%d", m ? "," : "", w->inst[m]->id);
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
            if (g_meta[id])
                g_meta[id]->ndeaths = 0;
    return sup_resp(all || found ? SUCCESS : PHD_ERR_NO_SUCH_WORKER);
}

char *sup_quarantine_clear(const char *which)
{
    int id;

    if (!strcmp(which, PHD_WORD_ALL))
    {
        for (id = 0; id < MAX_INSTANCE; id++)
            if (g_meta[id])
                g_meta[id]->quarantined = 0;
        return sup_resp(SUCCESS);
    }
    id = atoi(which);
    if (id < 0 || id >= MAX_INSTANCE || (!g_inst[id] && !(g_meta[id] && g_meta[id]->quarantined)))
        return sup_resp(ERR_INSTANCE_NON_EXISTS);
    meta_of(id)->quarantined = 0;
    return sup_resp(SUCCESS);
}

static int format_of(const char *name)
{
    if (!strcmp(name, PHD_FORMAT_LV2))
        return FMT_LV2;
    if (!strcmp(name, PHD_FORMAT_CLAP))
        return FMT_CLAP;
    return -1;
}

char *sup_policy_set(const char *format, const char *place)
{
    int f;

    if (!valid_place(place))
        return sup_resp(PHD_ERR_PLACEMENT_INVALID);
    if (!strcmp(format, PHD_FORMAT_ANY))
    {
        for (f = 0; f < FMT_COUNT; f++)
            snprintf(g_policy[f], sizeof(g_policy[f]), "%s", place);
        return sup_resp(SUCCESS);
    }
    f = format_of(format);
    if (f < 0)
        return sup_resp(ERR_INVALID_OPERATION);
    snprintf(g_policy[f], sizeof(g_policy[f]), "%s", place);
    return sup_resp(SUCCESS);
}

char *sup_pool_config(const char *name, int max)
{
    int n;

    if (!phd_pool_name_valid(name))
        return sup_resp(PHD_ERR_PLACEMENT_INVALID);
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
    int f, lo = 0, hi = FMT_COUNT - 1, n;
    worker_env_t env;
    size_t i;

    if (strcmp(format, PHD_FORMAT_ANY))
    {
        lo = hi = format_of(format);
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
            snprintf(g_env[f].cpus, sizeof(g_env[f].cpus), "%s", cpus);
        if (strcmp(nice, PHD_WORD_NONE))
            g_env[f].nice = atoi(nice);
        for (n = 0; n < g_nworkers; n++)
            if (g_workers[n]->fmt == f && g_workers[n]->state == W_UP)
                proc_apply_env(g_workers[n]->pid, &g_env[f]);
    }
    return sup_resp(SUCCESS);
}

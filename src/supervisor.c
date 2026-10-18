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
#include <plugin-hostd/pin.h>
#include <utils.h>

/* mod-host's pseudo port of the host's own bypass, which param_info names no parameter */

#include "pins.h"
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
static meta_t *g_meta[MAX_INSTANCE];
static char g_root[PATH_MAX], g_ckpt[PATH_MAX];
static char g_policy[FORMATS_MAX][48];
static poolcfg_t g_pools[POOL_NAMES];
static int g_npools;
static worker_env_t g_env[FORMATS_MAX];

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
    return strncmp(reply, "resp ", 5) == 0 ? atoi(reply + 5) : -999;
}

int sup_reply_code(const char *reply)
{
    return resp_code(reply);
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
    free(i->track_info);
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
    w->fb_fd = -1;
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

/* a format that can narrow its worker's world gives an own worker the world of the one plugin; a pool, and a plugin the
 * format cannot find, gets the whole search path */
static char *narrow_world(worker_t *w, const char *uri)
{
    const format_t *f = format_at(w->fmt);
    char dir[PATH_MAX];

    if (!f->narrow_world || w->pool || !uri)
        return NULL;
    snprintf(dir, sizeof(dir), "%s/world-w%d", g_root, w->k);
    return f->narrow_world(&g_conf, dir, uri);
}

/* how many times one start asks for ports before it is a failed spawn */
#define SPAWN_ATTEMPTS 3

static int replay_line_code(worker_t *w, const char *line, int *code);

/* whether the words of a line are the grammar of a mod-host format: as many, a %i a whole number, a %f a number */
static int format_words(const char *format, char **tok, int ntok)
{
    char *copy = strdup(format), *save = NULL, *t;
    int n = 0, ok = 1;

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
    int n;

    for (v = 0; v < HOST_SETTINGS; v++)
        if (verb_is(tok[0], g_host_setting_verbs[v]))
            break;
    if (v == HOST_SETTINGS || !format_words(g_host_setting_verbs[v], tok, ntok))
        return;
    for (n = 0; n < g_nhost_settings; n++)
        if (verb_is(g_host_settings[n], g_host_setting_verbs[v]))
        {
            free(g_host_settings[n]);
            memmove(&g_host_settings[n], &g_host_settings[n + 1], (g_nhost_settings - n - 1) * sizeof(char *));
            g_nhost_settings--;
            break;
        }
    if (g_nhost_settings < (int)HOST_SETTINGS)
        g_host_settings[g_nhost_settings++] = strdup(line);
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

static int worker_start(worker_t *w, const char *uri)
{
    char logfile[PATH_MAX];
    char *world;
    int rc, attempt;

    if (!proc_have_binary(bin_of(w->fmt)))
        return PHD_ERR_NO_BACKEND;
    snprintf(logfile, sizeof(logfile), "%s/w%d.log", g_root, w->k);
    world = narrow_world(w, uri);
    w->state = W_STARTING;
    for (attempt = 0;; attempt++)
    {
        rc = proc_spawn(&g_conf, bin_of(w->fmt), format_at(w->fmt)->world_env, world ? world : search_of(w->fmt),
                        &g_env[w->fmt], logfile, &w->pid, &w->port, &w->fb_port);
        if (rc != 0)
        {
            free(world);
            w->pid = 0;
            return PHD_ERR_WORKER_SPAWN;
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
        return PHD_ERR_WORKER_SPAWN;
    }
    if (host_settings_replay(w) != 0)
    {
        close(w->fd);
        close(w->fb_fd);
        proc_stop(w->pid);
        w->pid = 0;
        return PHD_ERR_WORKER_SPAWN;
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
/* the line that hands a CLAP worker the layout pin of the instance it is about to add */
static const char *pin_expect_line(int id, const char *layout)
{
    static char line[PHD_SHA256_HEX_LEN + 128];

    snprintf(line, sizeof(line), PHD_VERB_PIN_EXPECT " %d %s", id, layout);
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

/* the event of a refusal that says the plugin is not the one that was pinned */
static void pin_changed_event(const char *uri, int code)
{
    if (code == PHD_ERR_PIN_BINARY_MISMATCH)
        event(PHD_EVENT_PIN_CHANGED_FMT, uri, PHD_PIN_CHANGED_FILES);
    else if (code == PHD_ERR_PIN_LAYOUT_MISMATCH)
        event(PHD_EVENT_PIN_CHANGED_FMT, uri, PHD_PIN_CHANGED_LAYOUT);
}

/* a replayed add refused, by its pin or by the worker: announced with the refusal's own code, written with
 * PHD_ERR_REPLAY and the step that refused it, and the worker does not hold the instance until it is replayed again */
static void replay_refused(worker_t *w, instance_t *i, const char *step, int code)
{
    fprintf(stderr, "plugin-hostd: w%d did not replay instance %d: resp %d, its %s resp %d\n", w->k, i->id, PHD_ERR_REPLAY,
            step, code);
    event(PHD_EVENT_REPLAY_REFUSED_FMT, i->id, code);
    pin_changed_event(i->uri, code);
    i->unreplayed = 1;
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
            replay_refused(w, i, PHD_VERB_PIN_EXPECT, code);
            return PIN_REFUSED;
        }
    }
    return RPC_OK;
}

static void replay(worker_t *w, int64_t started)
{
    int n, m, any_ckpt = 0, count = 0, code;
    char msg[PATH_MAX + 16], add[32];

    snprintf(add, sizeof(add), "%.*s", verb_len(EFFECT_ADD), EFFECT_ADD);

    for (n = 0; n < w->ninst; n++)
    {
        instance_t *i = w->inst[n];

        switch (replay_pin(w, i))
        {
        case RPC_OK:
            break;
        case PIN_REFUSED:
            continue;
        default:
            on_death(w, i->id);
            return;
        }
        if (replay_line_code(w, i->add_line, &code) != RPC_OK)
        {
            on_death(w, i->id);
            return;
        }
        if (code < 0)
        {
            replay_refused(w, i, add, code);
            continue;
        }
        /* before the state: what the plugin does on hearing it is overwritten by the state it saved; mod-host
         * has no track_info, so a worker that does not answer the instance verbs never gets it */
        if (i->track_info && format_at(i->fmt)->native_instance_verbs && replay_line(w, i->track_info) != RPC_OK)
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

        if (i->unreplayed)
            continue;
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

        if (i->unreplayed)
            continue;
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
        if (!w->inst[n]->unreplayed)
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
    for (f = 0; f < FORMATS_MAX; f++)
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

/* the layout a worker found after init, recorded in the pin that has none yet. A worker that does not know the verb, or
 * a reply that is not a layout, leaves the pin as it is: its files are still checked on every add */
static void learn_layout(worker_t *w, int id, const char *uri)
{
    char line[64], *reply = NULL, *save = NULL, *word;
    int rc;

    snprintf(line, sizeof(line), PHD_VERB_PIN_LAYOUT " %d", id);
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

/* the adapter of a worker refused the add of `uri`, for the reason `why`: say so on the feedback port; under auto the plugin
 * goes to the lv2 row from now on and this add is made again there, otherwise the add answers PHD_ERR_LV2_ADAPTER_REFUSED */
static char *adapter_refused(const char *uri, const char *why, int id, const char *placement, const char *client)
{
    int automatic = lv2_worker_is_auto(&g_conf, uri);

    event(PHD_EVENT_LV2_ADAPTER_REFUSED_FMT, uri, why, automatic ? PHD_LV2_WORKER_AUTO : PHD_LV2_WORKER_CLAP_HOST);
    if (!automatic)
        return sup_resp(PHD_ERR_LV2_ADAPTER_REFUSED);
    lv2_adapter_refused(uri);
    return sup_add(uri, id, placement, client);
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
    char place[48], line[PATH_MAX + 128], *reply = NULL;
    const char *layout = NULL;
    worker_t *w = NULL;
    meta_t *m;
    int64_t now = proc_now_ms();
    int rc, is_new = 0, full, unavailable, code = ERR_HOST_INSTANTIATION;
    instance_t *i;

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
    if (placement && strcmp(placement, PHD_PLACE_DEFAULT) && !valid_place(placement))
        return sup_resp(PHD_ERR_PLACEMENT_INVALID);
    if (!placement || !strcmp(placement, PHD_PLACE_DEFAULT))
        snprintf(place, sizeof(place), "%s", g_policy[fmt]);
    else
        snprintf(place, sizeof(place), "%s", placement);
    /* a plugin the adapter refused under auto was never run by it: one that dies in instantiate (a Qt body with no
     * display) must not take a shared worker with it, so unless the caller named a placement it gets one of its own */
    if ((!placement || !strcmp(placement, PHD_PLACE_DEFAULT)) && lv2_refused_under_auto(&g_conf, fmt, fwd))
        snprintf(place, sizeof(place), PHD_PLACE_OWN);
    m = meta_of(id);
    if (m->quarantined)
        snprintf(place, sizeof(place), PHD_PLACE_OWN);
    if (!proc_have_binary(bin_of(fmt)))
        return sup_resp(PHD_ERR_NO_BACKEND);
    if (recent(m->deaths, &m->ndeaths, now) >= g_conf.storm_deaths)
        return sup_resp(PHD_ERR_GAVE_UP);
    if (g_conf.require_pins)
    {
        int first_use = conf_pins_first_use(&g_conf);

        rc = pins_check(format, fwd, search_of(fmt), &layout);
        /* a plugin that has no pin gets one, from the files as they are now; it is not asked about again */
        if (rc == PHD_ERR_PIN_ABSENT && first_use && !pins_known(fwd))
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
            if (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)))
                return sup_resp(PHD_ERR_PLACEMENT_INVALID);
            snprintf(place, sizeof(place), PHD_PLACE_OWN);
        }
        /* first-use: only a plugin qualified for a shared worker is placed in one */
        else if (first_use && !pins_in_process(fwd))
        {
            if (placement && !strncmp(placement, PHD_PLACE_POOL_PREFIX, strlen(PHD_PLACE_POOL_PREFIX)))
                return sup_resp(PHD_ERR_PLACEMENT_INVALID);
            snprintf(place, sizeof(place), PHD_PLACE_OWN);
        }
    }

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
            code = PHD_ERR_VERB_DROPPED;
        }
    }
    snprintf(line, sizeof(line), "%.*s %s%s %d%s%s", verb_len(EFFECT_ADD), EFFECT_ADD,
             format->worker_prefix ? format->worker_prefix : "", fwd, id, client ? " " : "", client ? client : "");
    if (rc == RPC_OK && !reply)
        rc = proc_rpc(&g_conf, w->pid, w->fd, line, &reply);
    if (rc != RPC_OK)
    {
        /* the worker went with `add` or its pin_expect on the wire: the instance is the suspect, and the event names
         * the plugin it died adding (the pin_expect's own was sent above) */
        if (code != PHD_ERR_VERB_DROPPED)
            event(PHD_EVENT_VERB_DROPPED_FMT, id, line);
        m->crashes++;
        note_death(m->deaths, &m->ndeaths, now);
        if (w->pool)
        {
            m->quarantined = 1;
            event(PHD_EVENT_INSTANCE_QUARANTINED_FMT, id, w->k);
        }
        on_death(w, ATTRIBUTED);
        return sup_resp(code);
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
    relay_instance_gone(id);
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

/* the words of a line by mod-host's own tokenizer, quotes and \" read as the worker reads them; the count in *count */
static char **words(char *copy, int *count)
{
    char **word = strarr_split(copy);

    for (*count = 0; word && word[*count]; (*count)++)
        ;
    return word;
}

char *sup_instance_verb(const char *line, int ledger)
{
    char *copy = strdup(line), **word, *end, *reply;
    instance_t *i = NULL;
    int count;
    long id;

    word = words(copy, &count);
    id = count > 1 ? strtol(word[1], &end, 10) : -1;
    if (count < 2 || *end || end == word[1])
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (!(i = (id >= 0 && id < MAX_INSTANCE) ? g_inst[id] : NULL))
        reply = sup_resp(ERR_INSTANCE_NON_EXISTS);
    else if (!strcmp(word[0], PHD_VERB_TRACK_INFO) && !phd_track_info_valid(word, count))
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (phd_is_note_verb(word[0]) && !phd_note_valid(word, count))
        reply = sup_resp(ERR_INVALID_OPERATION);
    else if (format_at(i->fmt)->native_instance_verbs)
    {
        reply = sup_call(id, line);
        if (ledger == PHD_LEDGER_REPLACE && resp_code(reply) >= 0 && g_inst[id] == i)
        {
            free(i->track_info);
            i->track_info = strdup(line);
        }
    }
    /* a format whose worker has none of these: the daemon answers, and nothing goes to the worker */
    else if (!strcmp(word[0], PHD_VERB_TRACK_INFO))
    {
        free(i->track_info);
        i->track_info = strdup(line);
        reply = sup_resp(SUCCESS);
    }
    else if (!strcmp(word[0], PHD_VERB_REMOTE_PAGES))
        reply = sup_resp(count == 2 ? 0 : ERR_INVALID_OPERATION);
    else if (!strcmp(word[0], PHD_VERB_PARAM_INFO))
        reply = count == 3 ? format_at(i->fmt)->param_info(id, word[2]) : sup_resp(ERR_INVALID_OPERATION);
    else if (phd_is_note_verb(word[0]))
        reply = sup_resp(PHD_ERR_NOTES_BY_JACK);
    else if (!strcmp(word[0], PHD_VERB_PRESET_LIST) || !strcmp(word[0], PHD_VERB_PRESET_GET))
        reply = sup_resp(PHD_ERR_NO_PRESET_LIST);
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

        put(&buf, &used, &cap, " w%d:%d:%s:%s:%s:", w->k, (int)w->pid, format_at(w->fmt)->name, g_state_states[w->state], w->place);
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

char *sup_policy_set(const char *format, const char *place)
{
    int f;

    if (!valid_place(place))
        return sup_resp(PHD_ERR_PLACEMENT_INVALID);
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
            snprintf(g_env[f].cpus, sizeof(g_env[f].cpus), "%s", cpus);
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

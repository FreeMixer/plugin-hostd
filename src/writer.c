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

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fsutil.h"
#include "writer.h"

enum { KIND_PUT, KIND_PLACE };

typedef struct job
{
    struct job *next;
    int kind, flags, group, err;
    char *path, *from, *bytes;
    size_t len;
    writer_done_fn done;
    void *arg;
    const char *what;
} job_t;

typedef struct
{
    int id, waiting, err, orphan;
} group_t;

/* shared with the thread, under g_lock: what waits, what has ended, and the counts that bound them */
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_wake = PTHREAD_COND_INITIALIZER, g_idle = PTHREAD_COND_INITIALIZER;
static job_t *g_head, *g_tail, *g_ended, *g_ended_tail;
static int g_jobs, g_outstanding, g_stop;
static size_t g_bytes;
static pthread_t g_thread;
static int g_running;

/* the loop's own: the groups of the verbs and the one a verb is in */
static group_t *g_groups;
static int g_ngroups, g_next_group, g_verb_group, g_verb_refused;

static void job_free(job_t *j)
{
    free(j->path);
    free(j->from);
    free(j->bytes);
    free(j);
}

/* the line of a write that failed, in the words its caller gave */
static void said(const job_t *j, const char *why)
{
    fputs("plugin-hostd: can't write ", stderr);
    if (j->what)
        fprintf(stderr, j->what, j->path, why);
    else
        fprintf(stderr, "%s: %s", j->path, why);
    fputc('\n', stderr);
}

static void job_run(job_t *j)
{
    j->err = j->kind == KIND_PUT ? fs_write_atomic(j->path, j->bytes, j->len) : fs_into_place(j->from, j->path);
}

static group_t *group_of(int id)
{
    int n;

    for (n = 0; n < g_ngroups; n++)
        if (g_groups[n].id == id)
            return &g_groups[n];
    return NULL;
}

/* on the loop: one end, said */
static void ended(job_t *j)
{
    group_t *g = j->group ? group_of(j->group) : NULL;

    if (j->err)
        said(j, strerror(j->err));
    if (g)
    {
        g->waiting--;
        if (j->err && !g->err)
            g->err = j->err;
        /* the group of a verb already answered (a write of it was refused) is nobody's once its last write ends */
        if (g->orphan && g->waiting == 0)
            *g = g_groups[--g_ngroups];
    }
    if (j->done)
        j->done(j->arg, j->err);
    job_free(j);
}

static void *thread_main(void *unused)
{
    (void)unused;
    pthread_mutex_lock(&g_lock);
    for (;;)
    {
        job_t *j;

        while (!g_head && !g_stop)
            pthread_cond_wait(&g_wake, &g_lock);
        /* told to stop: what is left is not written. writer_finish drains before it tells */
        if (g_stop)
            break;
        j = g_head;
        g_head = j->next;
        if (!g_head)
            g_tail = NULL;
        g_jobs--;
        pthread_mutex_unlock(&g_lock);
        job_run(j);
        pthread_mutex_lock(&g_lock);
        g_bytes -= j->len;
        j->next = NULL;
        if (g_ended_tail)
            g_ended_tail->next = j;
        else
            g_ended = j;
        g_ended_tail = j;
        if (--g_outstanding == 0)
            pthread_cond_broadcast(&g_idle);
    }
    pthread_mutex_unlock(&g_lock);
    return NULL;
}

int writer_start(void)
{
    sigset_t all, old;
    int rc;

    if (g_running)
        return 0;
    g_stop = 0;
    /* the signals are the loop's: SIGTERM ends the loop, never this thread */
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, &old);
    rc = pthread_create(&g_thread, NULL, thread_main, NULL);
    pthread_sigmask(SIG_SETMASK, &old, NULL);
    if (rc != 0)
    {
        fprintf(stderr, "plugin-hostd: can't start the writer: %s\n", strerror(rc));
        return -1;
    }
    g_running = 1;
    return 0;
}

void writer_poll(void)
{
    job_t *list;

    pthread_mutex_lock(&g_lock);
    list = g_ended;
    g_ended = g_ended_tail = NULL;
    pthread_mutex_unlock(&g_lock);
    while (list)
    {
        job_t *next = list->next;

        ended(list);
        list = next;
    }
}

int writer_busy(void)
{
    int busy;

    /* a write that ended and is not told yet counts: what waits for it waits for its end to be said */
    pthread_mutex_lock(&g_lock);
    busy = g_outstanding > 0 || g_ended != NULL;
    pthread_mutex_unlock(&g_lock);
    return busy;
}

void writer_drain(void)
{
    pthread_mutex_lock(&g_lock);
    while (g_outstanding > 0)
        pthread_cond_wait(&g_idle, &g_lock);
    pthread_mutex_unlock(&g_lock);
    writer_poll();
}

void writer_finish(void)
{
    if (!g_running)
        return;
    writer_drain();
    pthread_mutex_lock(&g_lock);
    g_stop = 1;
    pthread_cond_signal(&g_wake);
    pthread_mutex_unlock(&g_lock);
    pthread_join(g_thread, NULL);
    g_running = 0;
    writer_poll();
    /* nothing is left after a drain; were anything, it is said as not written and freed */
    while (g_head)
    {
        job_t *j = g_head;

        g_head = j->next;
        j->err = ECANCELED;
        ended(j);
    }
    g_tail = NULL;
}

/* a group of the verb now, counted one more write; 0 outside a verb */
static int group_take(void)
{
    group_t *g;

    if (!g_verb_group)
        return 0;
    g = group_of(g_verb_group);
    if (!g)
    {
        group_t *grown = realloc(g_groups, (size_t)(g_ngroups + 1) * sizeof(*grown));

        if (!grown)
            return 0;
        g_groups = grown;
        g = &g_groups[g_ngroups++];
        g->id = g_verb_group;
        g->waiting = g->err = g->orphan = 0;
    }
    g->waiting++;
    return g->id;
}

static int submit(job_t *j)
{
    job_t *last = NULL, *p;

    if (!g_running)
    {
        j->group = group_take();
        job_run(j);
        ended(j);
        return 0;
    }
    pthread_mutex_lock(&g_lock);
    /* a periodic snapshot replaces the one of the same file still waiting, when that is the last write of the file */
    if (j->kind == KIND_PUT && (j->flags & WRITER_COALESCE))
    {
        for (p = g_head; p; p = p->next)
            if (p->kind == KIND_PUT && !strcmp(p->path, j->path))
                last = p;
        if (last && (last->flags & WRITER_COALESCE) && g_bytes - last->len + j->len <= WRITER_BYTES_MAX)
        {
            g_bytes = g_bytes - last->len + j->len;
            free(last->bytes);
            last->bytes = j->bytes;
            last->len = j->len;
            j->bytes = NULL;
            pthread_mutex_unlock(&g_lock);
            job_free(j);
            return 0;
        }
    }
    if (g_jobs >= WRITER_JOBS_MAX || g_bytes + j->len > WRITER_BYTES_MAX)
    {
        pthread_mutex_unlock(&g_lock);
        said(j, "too many writes wait");
        if (g_verb_group)
            g_verb_refused = 1;
        job_free(j);
        return -1;
    }
    pthread_mutex_unlock(&g_lock);
    j->group = group_take();
    pthread_mutex_lock(&g_lock);
    j->next = NULL;
    if (g_tail)
        g_tail->next = j;
    else
        g_head = j;
    g_tail = j;
    g_jobs++;
    g_outstanding++;
    g_bytes += j->len;
    pthread_cond_signal(&g_wake);
    pthread_mutex_unlock(&g_lock);
    return 0;
}

static job_t *job_new(int kind, const char *path, const char *from, writer_done_fn done, void *arg, const char *what)
{
    job_t *j = calloc(1, sizeof(*j));

    if (!j)
        return NULL;
    j->kind = kind;
    j->done = done;
    j->arg = arg;
    j->what = what;
    j->path = strdup(path);
    j->from = from ? strdup(from) : NULL;
    if (!j->path || (from && !j->from))
    {
        job_free(j);
        return NULL;
    }
    return j;
}

int writer_put(const char *path, char *bytes, size_t len, int flags, writer_done_fn done, void *arg, const char *what)
{
    job_t *j = job_new(KIND_PUT, path, NULL, done, arg, what);

    if (!j)
    {
        free(bytes);
        if (g_verb_group)
            g_verb_refused = 1;
        return -1;
    }
    j->bytes = bytes;
    j->len = len;
    j->flags = flags;
    return submit(j);
}

int writer_place(const char *tmp, const char *final, writer_done_fn done, void *arg, const char *what)
{
    job_t *j = job_new(KIND_PLACE, final, tmp, done, arg, what);

    if (!j)
    {
        if (g_verb_group)
            g_verb_refused = 1;
        return -1;
    }
    return submit(j);
}

void writer_verb_begin(int promises)
{
    g_verb_refused = 0;
    g_verb_group = 0;
    if (!promises)
        return;
    if (++g_next_group <= 0)
        g_next_group = 1;
    g_verb_group = g_next_group;
}

int writer_verb_end(void)
{
    int id = g_verb_group, refused = g_verb_refused;
    group_t *g = group_of(id);

    g_verb_group = g_verb_refused = 0;
    if (refused)
    {
        if (g && g->waiting > 0)
            g->orphan = 1;
        else if (g)
            *g = g_groups[--g_ngroups];
        return -1;
    }
    return g ? id : 0;
}

int writer_group(int id, int *err)
{
    group_t *g = group_of(id);

    *err = 0;
    if (!g)
        return 1;
    if (g->waiting > 0)
        return 0;
    *err = g->err;
    *g = g_groups[--g_ngroups];
    return 1;
}

void writer_forget(int id)
{
    group_t *g = group_of(id);

    if (!g)
        return;
    if (g->waiting > 0)
        g->orphan = 1;
    else
        *g = g_groups[--g_ngroups];
}

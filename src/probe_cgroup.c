/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "probe_cgroup.h"

static int write_text(const char *dir, const char *file, const char *text)
{
    char path[PATH_MAX + 64];
    int fd, ok;

    snprintf(path, sizeof(path), "%s/%s", dir, file);
    if ((fd = open(path, O_WRONLY | O_CLOEXEC)) < 0)
        return -1;
    ok = write(fd, text, strlen(text)) == (ssize_t)strlen(text);
    if (!ok)
    {
        int e = errno;

        close(fd);
        errno = e;
        return -1;
    }
    close(fd);
    return 0;
}

static int read_text(const char *dir, const char *file, char *buf, size_t size)
{
    char path[PATH_MAX + 64];
    int fd;
    ssize_t n;

    snprintf(path, sizeof(path), "%s/%s", dir, file);
    if ((fd = open(path, O_RDONLY | O_CLOEXEC)) < 0)
        return -1;
    n = read(fd, buf, size - 1);
    close(fd);
    if (n < 0)
        return -1;
    buf[n] = '\0';
    return 0;
}

/* whether this space-separated controller list names memory */
static int names_memory(const char *list)
{
    const char *p = list;

    while ((p = strstr(p, "memory")) != NULL)
    {
        if ((p == list || p[-1] == ' ') && (p[6] == '\0' || p[6] == ' ' || p[6] == '\n'))
            return 1;
        p += 6;
    }
    return 0;
}

/* this process's cgroup, /... as the unified hierarchy names it; -1 for none */
static int own_cgroup(char *out, size_t size)
{
    char text[PATH_MAX + 64], *line;
    FILE *f = fopen("/proc/self/cgroup", "r");
    int found = -1;

    if (!f)
        return -1;
    while (found < 0 && (line = fgets(text, sizeof(text), f)) != NULL)
        if (!strncmp(line, "0::", 3))
        {
            line[strcspn(line, "\n")] = '\0';
            snprintf(out, size, "%s", line + 3);
            found = 0;
        }
    fclose(f);
    return found;
}

/* a cgroup of this run's under base, with the limit set; base's subtree_control must already hold memory */
static int make_child(probe_cgroup_t *cg, const char *base, long long max_bytes)
{
    char dir[PATH_MAX], value[32];
    static unsigned serial;
    int n = snprintf(dir, sizeof(dir), "%s/plugin-hostd-probe.%d.%u", base, (int)getpid(), serial++);

    if (n < 0 || (size_t)n >= sizeof(dir) || mkdir(dir, 0755) != 0)
        return -1;
    snprintf(value, sizeof(value), "%lld", max_bytes);
    if (write_text(dir, "memory.max", value) != 0)
    {
        rmdir(dir);
        return -1;
    }
    /* swap would let the plugin past the limit, and the whole tree goes at the limit rather than one member of it: where
     * the kernel has neither file the limit itself still holds */
    (void)write_text(dir, "memory.swap.max", "0");
    (void)write_text(dir, "memory.oom.group", "1");
    snprintf(cg->dir, sizeof(cg->dir), "%s", dir);
    return 0;
}

/* only this process in the cgroup: it can leave for a leaf of its own, which lets the controller on (the kernel refuses a
 * controller on a cgroup that holds processes itself) */
static int alone_in(const char *base)
{
    char procs[256], *end;
    long pid;

    if (read_text(base, "cgroup.procs", procs, sizeof(procs)) != 0)
        return 0;
    pid = strtol(procs, &end, 10);
    return pid == (long)getpid() && (*end == '\0' || (end[0] == '\n' && end[1] == '\0'));
}

static int leave_for_a_leaf(probe_cgroup_t *cg, const char *base, long long max_bytes)
{
    char leaf[PATH_MAX];
    char pid[32];
    int n = snprintf(leaf, sizeof(leaf), "%s/plugin-hostd-probe.%d.runner", base, (int)getpid());

    if (n < 0 || (size_t)n >= sizeof(leaf) || !alone_in(base) || mkdir(leaf, 0755) != 0)
        return -1;
    snprintf(pid, sizeof(pid), "%d", (int)getpid());
    if (write_text(leaf, "cgroup.procs", pid) != 0)
    {
        rmdir(leaf);
        return -1;
    }
    snprintf(cg->own, sizeof(cg->own), "%s", base);
    snprintf(cg->self_leaf, sizeof(cg->self_leaf), "%s", leaf);
    if (write_text(base, "cgroup.subtree_control", "+memory") == 0 && make_child(cg, base, max_bytes) == 0)
        return 0;
    probe_cgroup_close(cg);
    return -1;
}

int probe_cgroup_open(probe_cgroup_t *cg, const char *root, long long max_bytes)
{
    char own[PATH_MAX], base[PATH_MAX + PATH_MAX], text[256];
    char *slash;

    memset(cg, 0, sizeof(*cg));
    if (own_cgroup(own, sizeof(own)) != 0)
        return PROBE_CGROUP_ABSENT;
    snprintf(base, sizeof(base), "%s%s", root, !strcmp(own, "/") ? "" : own);
    if (read_text(base, "cgroup.controllers", text, sizeof(text)) != 0)
        return PROBE_CGROUP_ABSENT;
    if (!names_memory(text))
    {
        /* the root of a machine or a container may list it only on its own subtree */
        return PROBE_CGROUP_NOT_DELEGATED;
    }
    /* 1: a cgroup of ours already hands the controller down */
    if (read_text(base, "cgroup.subtree_control", text, sizeof(text)) == 0 && names_memory(text) &&
        make_child(cg, base, max_bytes) == 0)
        return PROBE_CGROUP_OK;
    /* 2: a sibling. The controller is on at the parent, since this cgroup has it; the runner's own scope stays as it is */
    if ((slash = strrchr(own, '/')) != NULL && slash != own)
    {
        char parent[PATH_MAX + PATH_MAX];

        *slash = '\0';
        snprintf(parent, sizeof(parent), "%s%s", root, own);
        if (make_child(cg, parent, max_bytes) == 0)
            return PROBE_CGROUP_OK;
    }
    /* 3: turn it on here: the machine's root allows that outright, a delegated cgroup once the runner is out of it */
    if (write_text(base, "cgroup.subtree_control", "+memory") == 0 && make_child(cg, base, max_bytes) == 0)
        return PROBE_CGROUP_OK;
    if (leave_for_a_leaf(cg, base, max_bytes) == 0)
        return PROBE_CGROUP_OK;
    return PROBE_CGROUP_NOT_DELEGATED;
}

int probe_cgroup_enter(const probe_cgroup_t *cg)
{
    return write_text(cg->dir, "cgroup.procs", "0");
}

long long probe_cgroup_oom_kills(const probe_cgroup_t *cg)
{
    char text[512];
    const char *p;

    if (!cg->dir[0] || read_text(cg->dir, "memory.events", text, sizeof(text)) != 0 || (p = strstr(text, "oom_kill ")) == NULL)
        return -1;
    return atoll(p + strlen("oom_kill "));
}

void probe_cgroup_close(probe_cgroup_t *cg)
{
    if (cg->dir[0])
    {
        int tries;

        (void)write_text(cg->dir, "cgroup.kill", "1");
        /* the kernel lets go of a cgroup a moment after its last process is reaped */
        for (tries = 0; tries < 200 && rmdir(cg->dir) != 0 && errno == EBUSY; tries++)
        {
            struct timespec t = { 0, 5000000 };

            nanosleep(&t, NULL);
        }
        cg->dir[0] = '\0';
    }
    if (cg->self_leaf[0])
    {
        char pid[32];

        /* a cgroup that hands a controller down holds no process: off, then home */
        (void)write_text(cg->own, "cgroup.subtree_control", "-memory");
        snprintf(pid, sizeof(pid), "%d", (int)getpid());
        (void)write_text(cg->own, "cgroup.procs", pid);
        rmdir(cg->self_leaf);
        cg->self_leaf[0] = '\0';
        cg->own[0] = '\0';
    }
}

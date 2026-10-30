/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The cgroup a measured child runs in, with memory.max as its memory limit. The kernel then counts what the plugin really
 * holds, page by page, and kills the whole tree at the limit; memory.events says it did, so hitting the limit is told from
 * a crash by a count. A machine that does not delegate the memory controller to this user gets no cgroup: the open answers
 * the code that says why, and the runner lists it and falls back to RLIMIT_DATA. */

#ifndef PLUGIN_HOSTD_PROBE_CGROUP_H
#define PLUGIN_HOSTD_PROBE_CGROUP_H

#include <limits.h>

#define PROBE_CGROUP_ROOT "/sys/fs/cgroup"

typedef struct PROBE_CGROUP_T {
    char dir[PATH_MAX];        /* the child's cgroup; empty when none */
    char own[PATH_MAX];        /* the cgroup the runner was in, when it moved itself to enable the controller */
    char self_leaf[PATH_MAX];  /* where the runner moved itself, under own */
} probe_cgroup_t;

/* Make the cgroup under root (PROBE_CGROUP_ROOT, or a test's tree) with this memory.max. 0 and *cg ready; else *cg is
 * empty and the answer is PROBE_CGROUP_ABSENT or PROBE_CGROUP_NOT_DELEGATED. */
enum { PROBE_CGROUP_OK, PROBE_CGROUP_ABSENT, PROBE_CGROUP_NOT_DELEGATED };
int probe_cgroup_open(probe_cgroup_t *cg, const char *root, long long max_bytes);

/* Move the calling process into the cgroup, before its exec: 0, or -1. */
int probe_cgroup_enter(const probe_cgroup_t *cg);

/* How many processes the kernel killed at the limit: memory.events' oom_kill. -1 when it cannot be read. */
long long probe_cgroup_oom_kills(const probe_cgroup_t *cg);

/* Kill what is left in it, remove it, and put the runner back where it was. Safe on an empty *cg and a second time. */
void probe_cgroup_close(probe_cgroup_t *cg);

#endif

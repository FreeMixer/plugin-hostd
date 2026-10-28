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

/* Core placement (docs/placement.md): which cpus are the audio cores and which are kept for the daemon, and the audio
 * core a new worker is pinned to. Pure functions: they read no file, no clock and no global, so the same mask and the
 * same loads give the same core. The supervisor (src/supervisor.c) gathers the loads and applies the answer. */

#ifndef PLACEMENT_H
#define PLACEMENT_H

#include <sched.h>
#include <stddef.h>

/* what the workers already placed on one audio core come to */
typedef struct PLACEMENT_LOAD_T {
    int core;                   /* the cpu */
    int workers;                /* the workers placed on it */
    double cost;                /* the sum of their known costs, fractions of one core */
    int unknown;                /* how many of them have a member without a known cost */
} placement_load_t;

/* a cpu list as the kernel writes one, "0-2,5": numbers below CPU_SETSIZE and ranges low-high, joined by commas, nothing
 * else; 0, or -1 for anything that is not one */
int placement_parse(const char *list, cpu_set_t *set);

/* the list of a set, "0-2,5", "" for none; the length the text needs, truncated to size like snprintf */
size_t placement_list_text(const cpu_set_t *set, char *buf, size_t size);

/* The audio cores and the reserved ones of a daemon whose cpus are `allowed`: audio_cores when it is not empty, which
 * must be a list inside allowed, else allowed less its lowest cpu; reserved is the rest of allowed. 0, or -1 for an
 * audio_cores that is no list or names a cpu outside allowed. */
int placement_cores(const cpu_set_t *allowed, const char *audio_cores, cpu_set_t *audio, cpu_set_t *reserved);

/* The index in loads[0..n), in the order of the cores, of the least-loaded core: by the sum of the costs when no core
 * holds a worker of unknown cost, else by the count of workers; a tie by the other measure, then the first. -1 for no
 * core. */
int placement_pick(const placement_load_t *loads, int n);

#endif

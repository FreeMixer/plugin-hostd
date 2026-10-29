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

#include <stdio.h>
#include <string.h>

#include "placement.h"

/* two costs this close are equal: they are sums of a few fractions read from text */
#define COST_EPSILON 1e-9

/* a whole number of one or more digits at *p, below CPU_SETSIZE; the end in *p; -1 for none */
static int number(const char **p)
{
    long v = 0;
    int digits = 0;

    while (**p >= '0' && **p <= '9')
    {
        v = v * 10 + (**p - '0');
        if (v >= CPU_SETSIZE)
            return -1;
        (*p)++;
        digits++;
    }
    return digits ? (int)v : -1;
}

int placement_parse(const char *list, cpu_set_t *set)
{
    const char *p = list;

    CPU_ZERO(set);
    for (;;)
    {
        int a = number(&p), b;

        if (a < 0)
            return -1;
        b = a;
        if (*p == '-')
        {
            p++;
            b = number(&p);
            if (b < a)
                return -1;
        }
        while (a <= b)
            CPU_SET(a++, set);
        if (*p == '\0')
            return 0;
        if (*p++ != ',')
            return -1;
    }
}

size_t placement_list_text(const cpu_set_t *set, char *buf, size_t size)
{
    size_t used = 0;
    int c, first;

    if (size)
        buf[0] = '\0';
    for (c = 0; c < CPU_SETSIZE; c++)
    {
        int w;

        if (!CPU_ISSET(c, set))
            continue;
        for (first = c; c + 1 < CPU_SETSIZE && CPU_ISSET(c + 1, set); c++)
            ;
        if (first == c)
            w = snprintf(used < size ? buf + used : NULL, used < size ? size - used : 0, "%s%d", used ? "," : "", c);
        else
            w = snprintf(used < size ? buf + used : NULL, used < size ? size - used : 0, "%s%d-%d", used ? "," : "", first, c);
        if (w > 0)
            used += (size_t)w;
    }
    return used;
}

int placement_cores(const cpu_set_t *allowed, const char *audio_cores, cpu_set_t *audio, cpu_set_t *reserved)
{
    int c;

    if (audio_cores && *audio_cores)
    {
        cpu_set_t inside;

        if (placement_parse(audio_cores, audio) != 0)
            return -1;
        CPU_AND(&inside, audio, allowed);
        if (!CPU_EQUAL(&inside, audio))
            return -1;
    }
    else
    {
        *audio = *allowed;
        for (c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, audio))
            {
                CPU_CLR(c, audio);
                break;
            }
    }
    CPU_XOR(reserved, allowed, audio);
    return 0;
}

/* whether a is less loaded than b: the first measure, then the other */
static int lighter(const placement_load_t *a, const placement_load_t *b, int by_cost)
{
    if (by_cost)
    {
        if (a->cost < b->cost - COST_EPSILON || a->cost > b->cost + COST_EPSILON)
            return a->cost < b->cost;
        return a->workers < b->workers;
    }
    if (a->workers != b->workers)
        return a->workers < b->workers;
    return a->cost < b->cost - COST_EPSILON;
}

int placement_pick(const placement_load_t *loads, int n)
{
    int k, best = 0, by_cost = 1;

    if (n < 1)
        return -1;
    for (k = 0; k < n; k++)
        if (loads[k].unknown)
            by_cost = 0;
    for (k = 1; k < n; k++)
        if (lighter(&loads[k], &loads[best], by_cost))
            best = k;
    return best;
}

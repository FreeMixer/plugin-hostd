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

/* a whole number in the file dir/cpu<c>/<name>, above 0; 0 for none */
static long read_cpu_number(const char *dir, int c, const char *name)
{
    char path[512];
    long v = 0;
    FILE *f;

    snprintf(path, sizeof(path), "%s/cpu%d/%s", dir, c, name);
    if (!(f = fopen(path, "r")))
        return 0;
    if (fscanf(f, "%ld", &v) != 1 || v < 0)
        v = 0;
    fclose(f);
    return v;
}

int placement_capacities(const char *dir, const cpu_set_t *allowed, long *capacity)
{
    static const char *const source[] = { "cpu_capacity", "cpufreq/cpuinfo_max_freq" };
    size_t k;
    int c, all;

    for (k = 0; k < sizeof(source) / sizeof(source[0]); k++)
    {
        all = 1;
        for (c = 0; c < CPU_SETSIZE; c++)
        {
            capacity[c] = CPU_ISSET(c, allowed) ? read_cpu_number(dir, c, source[k]) : 0;
            if (CPU_ISSET(c, allowed) && capacity[c] <= 0)
                all = 0;
        }
        if (all)
            return 1;
    }
    for (c = 0; c < CPU_SETSIZE; c++)
        capacity[c] = 0;
    return 0;
}

int placement_cores(const cpu_set_t *allowed, const char *audio_cores, const long *capacity, cpu_set_t *audio,
                    cpu_set_t *reserved)
{
    int c, least = -1;

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
        /* the reserved cpu is the one of least capacity, the lowest of a tie: on a hybrid cpu an efficiency core, so
         * every performance core is left to the audio; with no capacity known, or all equal, the lowest cpu */
        *audio = *allowed;
        for (c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, audio) && (least < 0 || (capacity && capacity[c] < capacity[least])))
                least = c;
        if (least >= 0)
            CPU_CLR(least, audio);
    }
    CPU_XOR(reserved, allowed, audio);
    return 0;
}

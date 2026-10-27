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

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include <plugin-hostd/plugin_hostd_vocabulary.h>
#include <plugin-hostd/protocol.h>

#include "planner.h"

static const char *const g_reason_words[] = OMX_PLUGIN_HOSTD_GROUPING_REASONS_INIT;

const char *planner_reason_word(int reason)
{
    if (reason < 0 || reason >= PLANNER_REASON_COUNT || (size_t)reason >= sizeof(g_reason_words) / sizeof(g_reason_words[0]))
        return NULL;
    return g_reason_words[reason];
}

/* ---------------------------------------------------------------- the seams the history record fills in */

/* The cost a member counts for in a segment. Today it is the qualification cost the supervisor read. With the history
 * it is the larger of that and the member's cpu_p95_solo (the design note, The history record), which is this
 * function's one line to change. PLANNER_COST_UNKNOWN when nobody measured it. */
static double member_cost(const planner_member_t *m)
{
    return m->cost;
}

/* The reason the history keeps a member alone, or PLANNER_REASON_NONE. history-crashed and history-xruns are the rules
 * of the history lane: until they exist a history is neutral, whatever it holds, so a plugin with none and a plugin
 * with some are judged alike. */
static int history_reason(const planner_member_t *m)
{
    (void)m;
    return PLANNER_REASON_NONE;
}

/* ---------------------------------------------------------------- the rules */

/* The rules that leave a member alone, in the order of the design note's table, the first that matches deciding. The
 * pin rules are read only while require_pins is on, as the daemon reads a pin only then. */
static int alone_reason(const planner_settings_t *s, const planner_member_t *m)
{
    int r;

    if (s->require_pins)
    {
        if (m->pin == PLANNER_PIN_REFUSED)
            return PLANNER_REASON_REFUSED;
        if (m->pin == PLANNER_PIN_NONE && !s->pins_first_use)
            return PLANNER_REASON_NO_PIN;
        /* a pin of first use has no verdict, and neither has a pin that was cleared after the add */
        if ((m->pin == PLANNER_PIN_NONE || m->pin == PLANNER_PIN_NO_VERDICT) && s->pins_first_use)
            return PLANNER_REASON_NO_VERDICT;
        if (m->pin == PLANNER_PIN_ISOLATED)
            return PLANNER_REASON_VERDICT_ISOLATED;
        if (!m->world_ok)
            return PLANNER_REASON_FORMAT_WORLD;
    }
    r = history_reason(m);
    if (r != PLANNER_REASON_NONE)
        return r;
    if (s->group_cost_max > 0 && member_cost(m) != PLANNER_COST_UNKNOWN && member_cost(m) > s->group_cost_max)
        return PLANNER_REASON_COST_OVER;
    return PLANNER_REASON_NONE;
}

/* the median of the costs the segment holds that are known; 0 when none is: a member of unknown cost counts as that */
static double assumed_cost(const planner_member_t *m, int first, int count)
{
    double known[PLANNER_MEMBERS_MAX];
    int k, j, n = 0;

    for (k = first; k < first + count; k++)
        if (member_cost(&m[k]) != PLANNER_COST_UNKNOWN)
        {
            for (j = n++; j > 0 && known[j - 1] > member_cost(&m[k]); j--)
                known[j] = known[j - 1];
            known[j] = member_cost(&m[k]);
        }
    if (!n)
        return 0;
    return n % 2 ? known[n / 2] : (known[n / 2 - 1] + known[n / 2]) / 2;
}

int planner_plan(const planner_settings_t *s, const planner_member_t *m, int n, planner_plan_t *out)
{
    int k, first = 0, open = 0;     /* the open segment: m[first .. first + open) */
    double sum = 0;                 /* what its members' costs add to, the assumed ones included */

    if (n < 1 || n > PLANNER_MEMBERS_MAX)
        return -1;
    memset(out, 0, sizeof(*out));
    for (k = 0; k < n; k++)
        out->reason[k] = PLANNER_REASON_NONE;

    for (k = 0; k < n; k++)
    {
        int r = alone_reason(s, &m[k]);
        double cost = member_cost(&m[k]);

        if (r != PLANNER_REASON_NONE)
        {
            /* it shares with no one: the open segment ends before it, and it is a segment of one */
            if (open)
                out->seg_len[out->nseg++] = open;
            out->seg_len[out->nseg++] = 1;
            out->reason[k] = r;
            first = k + 1;
            open = 0;
            sum = 0;
            continue;
        }
        if (open)
        {
            double own = cost == PLANNER_COST_UNKNOWN ? assumed_cost(m, first, open) : cost;

            if (strcmp(m[first].klass, m[k].klass))
                r = PLANNER_REASON_FORMAT_MIXED;
            else if (s->group_max > 0 && open >= s->group_max)
                r = PLANNER_REASON_GROUP_FULL;
            else if (s->group_cost_max > 0 && sum + own > s->group_cost_max)
                r = PLANNER_REASON_GROUP_COST;
            if (r == PLANNER_REASON_NONE)
            {
                open++;
                sum += own;
                continue;
            }
            /* it starts a new segment, and says why */
            out->seg_len[out->nseg++] = open;
            out->reason[k] = r;
            first = k;
            open = 0;
            sum = 0;
        }
        if (!open)
        {
            first = k;
            open = 1;
            sum = cost == PLANNER_COST_UNKNOWN ? 0 : cost;
        }
    }
    if (open)
        out->seg_len[out->nseg++] = open;

    /* what the members that said nothing have to say */
    for (k = 0, first = 0; first < out->nseg; first++)
    {
        int len = out->seg_len[first], j;

        for (j = k; j < k + len; j++)
        {
            if (out->reason[j] != PLANNER_REASON_NONE)
                continue;
            if (len == 1)
                out->reason[j] = PLANNER_REASON_NO_NEIGHBOUR;
            else if (!s->grouping_on)
                out->reason[j] = PLANNER_REASON_GROUPING_OFF;
            else if (member_cost(&m[j]) == PLANNER_COST_UNKNOWN)
                out->reason[j] = PLANNER_REASON_COST_ASSUMED;
        }
        k += len;
    }
    return 0;
}

/* ---------------------------------------------------------------- the text of a plan */

static void put(char *buf, size_t size, size_t *used, const char *fmt, ...)
{
    va_list ap;
    int w;

    va_start(ap, fmt);
    w = vsnprintf(*used < size ? buf + *used : NULL, *used < size ? size - *used : 0, fmt, ap);
    va_end(ap);
    if (w > 0)
        *used += (size_t)w;
}

size_t planner_format_segments(const planner_member_t *m, const planner_plan_t *p, char *buf, size_t size)
{
    size_t used = 0;
    int s, k = 0, j;

    for (s = 0; s < p->nseg; s++)
    {
        if (s)
            put(buf, size, &used, ";");
        for (j = 0; j < p->seg_len[s]; j++, k++)
            put(buf, size, &used, "%s%d", j ? "," : "", m[k].id);
    }
    return used;
}

size_t planner_format_reasons(const planner_member_t *m, const planner_plan_t *p, int refused_code, char *buf, size_t size)
{
    size_t used = 0;
    int k, n = 0, count = 0;

    for (k = 0; k < p->nseg; k++)
        n += p->seg_len[k];
    for (k = 0; k < n; k++)
    {
        if (refused_code)
            put(buf, size, &used, "%s%d:%s:%d", count++ ? "," : "", m[k].id,
                g_reason_words[PLANNER_REASON_PLAN_REFUSED], refused_code);
        else if (p->reason[k] != PLANNER_REASON_NONE)
            put(buf, size, &used, "%s%d:%s", count++ ? "," : "", m[k].id, g_reason_words[p->reason[k]]);
    }
    if (!count)
        put(buf, size, &used, PHD_WORD_NONE);
    return used;
}

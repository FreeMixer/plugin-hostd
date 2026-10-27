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

/* The grouping planner (the grouping-planner design note, The planner): given plugins in signal order, which runs of
 * consecutive ones may share a worker. A pure function: the same members and settings give the same plan, byte for
 * byte; it reads no clock, no file, no pin store and no global, and allocates nothing. What it is given is gathered
 * by the supervisor (src/supervisor.c), what it answers is applied there. */

#ifndef PLANNER_H
#define PLANNER_H

#include <stddef.h>

/* the most members of one plan: the words of a plan line less the verb and the chain */
#define PLANNER_MEMBERS_MAX 62

/* a cost nobody measured */
#define PLANNER_COST_UNKNOWN (-1.0)

/* what a member's pin says, as far as the rules read it */
enum {
    PLANNER_PIN_NONE,           /* no pin */
    PLANNER_PIN_NO_VERDICT,     /* a pin without a verdict: one the daemon learned on first use */
    PLANNER_PIN_IN_PROCESS,
    PLANNER_PIN_ISOLATED,
    PLANNER_PIN_REFUSED
};

/* The reasons, in the order of PLUGIN_HOSTD_GROUPING_REASONS (data/grouping.json): the test holds each to its word.
 * PLANNER_REASON_NONE is a member with nothing to say. */
enum {
    PLANNER_REASON_NONE = -1,
    PLANNER_REASON_REFUSED,
    PLANNER_REASON_NO_PIN,
    PLANNER_REASON_NO_VERDICT,
    PLANNER_REASON_VERDICT_ISOLATED,
    PLANNER_REASON_FORMAT_WORLD,
    PLANNER_REASON_COST_OVER,
    PLANNER_REASON_FORMAT_MIXED,
    PLANNER_REASON_GROUP_FULL,
    PLANNER_REASON_GROUP_COST,
    PLANNER_REASON_COST_ASSUMED,
    PLANNER_REASON_NO_NEIGHBOUR,
    PLANNER_REASON_GROUPING_OFF,
    PLANNER_REASON_PLAN_REFUSED,
    PLANNER_REASON_COUNT
};

/* What the history of a plugin on this host class comes to (the design note, The history record), for the rules that
 * read it. Nothing reads it yet: the history record and the rules that use it are the next lane's. A member's history
 * is NULL when there is none, which is neutral. */
typedef struct PLANNER_HISTORY_T {
    int crashed;                /* a crash within history_keep_days */
    int raises_xruns;           /* more xrun windows grouped than alone */
    double cpu_p95_solo;        /* fraction of one core over the windows run alone, PLANNER_COST_UNKNOWN for none */
} planner_history_t;

typedef struct PLANNER_MEMBER_T {
    int id;                     /* the instance */
    const char *klass;          /* two members share a segment only when their classes are equal: the worker program that
                                 * runs chains in one client, else the row alone */
    int pin;                    /* PLANNER_PIN_* */
    int world_ok;               /* a world holding this plugin can be built for a shared worker, or none needs building */
    double cost;                /* a fraction of one core at the daemon's rate and quantum, PLANNER_COST_UNKNOWN for none */
    const planner_history_t *history;
} planner_member_t;

typedef struct PLANNER_SETTINGS_T {
    int require_pins;           /* the pin rules are read only while this is set */
    int pins_first_use;         /* pin_mode is first-use, else strict */
    int grouping_on;            /* off: the plan is the plan the daemon would apply */
    int group_max;              /* most members of a segment, 0 for no limit */
    double group_cost_max;      /* most the costs of a segment add to, a fraction of one core, 0 for no limit */
} planner_settings_t;

/* seg_len[0..nseg) are the lengths of the segments, which are consecutive runs of the members in the order given;
 * reason[k] is the reason of member k, PLANNER_REASON_NONE for none */
typedef struct PLANNER_PLAN_T {
    int nseg;
    int seg_len[PLANNER_MEMBERS_MAX];
    int reason[PLANNER_MEMBERS_MAX];
} planner_plan_t;

/* plans n members (1 to PLANNER_MEMBERS_MAX) into *out; 0, or -1 for a number of members outside that */
int planner_plan(const planner_settings_t *s, const planner_member_t *m, int n, planner_plan_t *out);

/* The word of a reason: the one of data/grouping.json, NULL outside PLANNER_REASON_* */
const char *planner_reason_word(int reason);

/* The segments as plan and plan_get answer them: the members of a segment joined by commas, the segments by
 * semicolons, "1,2;3". Returns the length the text needs; truncates to size like snprintf. */
size_t planner_format_segments(const planner_member_t *m, const planner_plan_t *p, char *buf, size_t size);

/* The reasons as plan_get answers them: instance:reason joined by commas for the members that have one, "-" for none.
 * A refused plan (refused_code is not 0) gives every member plan-refused:<refused_code>. Returns the length the text
 * needs. */
size_t planner_format_reasons(const planner_member_t *m, const planner_plan_t *p, int refused_code, char *buf, size_t size);

#endif

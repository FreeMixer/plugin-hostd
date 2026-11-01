/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* What a plugin costs, as plugin-qualify measured it: the qualification records of qualification_dir, one file per
 * binary and offer (<id>@<version>-<hash>.<offer>.qualification.json), each holding the figures of the probe's grid
 * per rate and quantum. The daemon reads them and writes none; a record gates no add. */

#ifndef PLUGIN_HOSTD_QUALCOST_H
#define PLUGIN_HOSTD_QUALCOST_H

/* The cost of the plugin with this id (the CLAP id, or the LV2 URI) at this rate and quantum, as a fraction of one core:
 * the 95th-percentile nanoseconds per sample of the record's grid point, times the rate, over 1e9. When several records
 * hold the point (a plugin tested in several versions) the largest wins, since the planner must not be optimistic. -1.0
 * when no record holds the point, the directory cannot be read, or a record is not one. */
double qualcost_read(const char *dir, const char *id, int rate, int quantum);

/* What the records of a plugin hold at one rate and quantum, as the estimate verb reads them: the grid point's cost
 * median, in nanoseconds per sample, and its latency, the measured frames, else the declared ones. */
typedef struct QUALCOST_CELL_T {
    double median_ns;
    double latency_frames;
} qualcost_cell_t;

/* What the records of a plugin say it holds at one rate and quantum, in KB, as plugin-qualify worked it out from the
 * measured footprint: firstInstanceKb, one instance and what all its instances share; perInstanceKb, one more instance
 * beside it. */
typedef struct QUALCOST_MEMORY_T {
    double first_kb;
    double per_instance_kb;
} qualcost_memory_t;

enum {
    QUALCOST_CELL_FOUND,        /* a record holds the point with both figures */
    QUALCOST_CELL_NO_RECORD,    /* no record names the plugin (or the directory cannot be read) */
    QUALCOST_CELL_NO_POINT      /* a record names it, none holds the point with both figures */
};

/* The cell of the plugin with this id at this rate and quantum into *out, QUALCOST_CELL_*. When several records hold
 * the point the largest of each figure stands, as qualcost_read takes the largest cost. */
int qualcost_cell(const char *dir, const char *id, int rate, int quantum, qualcost_cell_t *out);

/* The memory of the plugin at this rate and quantum into *out: 0, or -1 when no record holds both figures there, which is
 * unknown and never 0. When several records hold them the largest of each stands. */
int qualcost_memory(const char *dir, const char *id, int rate, int quantum, qualcost_memory_t *out);

/* how many times the record lookups have listed a directory and parsed a record: what a test counts to see a repeat
 * read answered from memory */
extern unsigned long qualcost_dir_scans, qualcost_record_parses;

#endif

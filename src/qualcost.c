/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

#include <dirent.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"
#include "qualcost.h"

#define RECORD_SUFFIX ".qualification.json"
#define RECORD_MAX    (4u << 20)

/* the id as plugin-qualify spells it in a file name: each character outside [A-Za-z0-9._-] is an underscore */
static void safe(const char *id, char *out, size_t size)
{
    size_t n;

    for (n = 0; id[n] && n + 1 < size; n++)
        out[n] = (id[n] >= 'a' && id[n] <= 'z') || (id[n] >= 'A' && id[n] <= 'Z') || (id[n] >= '0' && id[n] <= '9') ||
                 id[n] == '.' || id[n] == '_' || id[n] == '-' ? id[n] : '_';
    out[n] = '\0';
}

static char *slurp(const char *path)
{
    FILE *f = fopen(path, "r");
    char *text;
    long size;

    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0 || (size = ftell(f)) < 0 || (unsigned long)size > RECORD_MAX || fseek(f, 0, SEEK_SET) != 0)
    {
        fclose(f);
        return NULL;
    }
    text = malloc((size_t)size + 1);
    if (text && fread(text, 1, (size_t)size, f) != (size_t)size)
    {
        free(text);
        text = NULL;
    }
    else if (text)
        text[size] = '\0';
    fclose(f);
    return text;
}

/* the grid point of the record at the rate and quantum, NULL for none; the record must name the id */
static const jnode_t *point_at(const jnode_t *record, const char *id, int rate, int quantum, size_t *from)
{
    const jnode_t *plugin = jget(record, "plugin"), *grid = jget(jget(record, "measurements"), "grid");
    const char *got = plugin ? jstr(plugin, "id") : NULL;

    if (!got || strcmp(got, id) || !grid || grid->type != J_ARR)
        return NULL;
    for (; *from < grid->n; (*from)++)
    {
        const jnode_t *point = grid->kid[*from];
        double r, q;

        if (!point || !jnum(point, "rate", &r) || !jnum(point, "quantum", &q) || r != rate || q != quantum)
            continue;
        (*from)++;
        return point;
    }
    return NULL;
}

/* whether the record names the id */
static int names(const jnode_t *record, const char *id)
{
    const char *got = jget(record, "plugin") ? jstr(jget(record, "plugin"), "id") : NULL;

    return got && !strcmp(got, id);
}

/* the fraction of one core of the record's grid point, or -1.0 */
static double point_of(const jnode_t *record, const char *id, int rate, int quantum)
{
    const jnode_t *point;
    size_t k = 0;

    while ((point = point_at(record, id, rate, quantum, &k)) != NULL)
    {
        const jnode_t *percentile = jget(jget(point, "cost"), "percentile");
        double ns;

        if (percentile && jnum(percentile, "value", &ns) && ns >= 0)
            return ns * rate / 1e9;
    }
    return -1.0;
}

/* calls each(record, ctx) for every record of qualification_dir whose file name is the id's */
static void each_record(const char *dir, const char *id, void (*each)(const jnode_t *, void *), void *ctx)
{
    char prefix[PATH_MAX], path[PATH_MAX * 2];
    struct dirent *e;
    size_t plen, slen = strlen(RECORD_SUFFIX);
    DIR *d;

    if (!dir || !*dir || !id || !*id || !(d = opendir(dir)))
        return;
    safe(id, prefix, sizeof(prefix) - 2);
    strcat(prefix, "@");
    plen = strlen(prefix);
    while ((e = readdir(d)) != NULL)
    {
        size_t len = strlen(e->d_name);
        char *text;
        jnode_t *record;

        if (len <= plen + slen || strncmp(e->d_name, prefix, plen) || strcmp(e->d_name + len - slen, RECORD_SUFFIX))
            continue;
        snprintf(path, sizeof(path), "%s/%s", dir, e->d_name);
        if (!(text = slurp(path)))
            continue;
        record = jparse(text);
        free(text);
        if (!record)
            continue;
        each(record, ctx);
        jfree(record);
    }
    closedir(d);
}

struct cost_ctx {
    const char *id;
    int rate, quantum;
    double best;
};

static void cost_of(const jnode_t *record, void *ctx)
{
    struct cost_ctx *c = ctx;
    double v = point_of(record, c->id, c->rate, c->quantum);

    if (v > c->best)
        c->best = v;
}

double qualcost_read(const char *dir, const char *id, int rate, int quantum)
{
    struct cost_ctx c = { id, rate, quantum, -1.0 };

    each_record(dir, id, cost_of, &c);
    return c.best;
}

struct cell_ctx {
    const char *id;
    int rate, quantum;
    int status;
    qualcost_cell_t cell;
};

static void cell_of(const jnode_t *record, void *ctx)
{
    struct cell_ctx *c = ctx;
    const jnode_t *point;
    size_t k = 0;

    if (!names(record, c->id))
        return;
    if (c->status == QUALCOST_CELL_NO_RECORD)
        c->status = QUALCOST_CELL_NO_POINT;
    while ((point = point_at(record, c->id, c->rate, c->quantum, &k)) != NULL)
    {
        const jnode_t *latency = jget(point, "latency");
        double median, frames;

        if (!jnum(jget(point, "cost"), "median", &median) || median < 0 ||
            (!jnum(latency, "measuredFrames", &frames) && !jnum(latency, "declaredFrames", &frames)) || frames < 0)
            continue;
        if (c->status != QUALCOST_CELL_FOUND)
        {
            c->status = QUALCOST_CELL_FOUND;
            c->cell.median_ns = median;
            c->cell.latency_frames = frames;
            continue;
        }
        if (median > c->cell.median_ns)
            c->cell.median_ns = median;
        if (frames > c->cell.latency_frames)
            c->cell.latency_frames = frames;
    }
}

int qualcost_cell(const char *dir, const char *id, int rate, int quantum, qualcost_cell_t *out)
{
    struct cell_ctx c = { id, rate, quantum, QUALCOST_CELL_NO_RECORD, { 0, 0 } };

    each_record(dir, id, cell_of, &c);
    *out = c.cell;
    return c.status;
}

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

/* the fraction of one core of the record's grid point, or -1.0 */
static double point_of(const jnode_t *record, const char *id, int rate, int quantum)
{
    const jnode_t *plugin = jget(record, "plugin"), *grid = jget(jget(record, "measurements"), "grid");
    const char *got = plugin ? jstr(plugin, "id") : NULL;
    size_t k;

    if (!got || strcmp(got, id) || !grid || grid->type != J_ARR)
        return -1.0;
    for (k = 0; k < grid->n; k++)
    {
        const jnode_t *point = grid->kid[k], *percentile = jget(jget(point, "cost"), "percentile");
        double r, q, ns;

        if (!point || !jnum(point, "rate", &r) || !jnum(point, "quantum", &q) || r != rate || q != quantum)
            continue;
        if (percentile && jnum(percentile, "value", &ns) && ns >= 0)
            return ns * rate / 1e9;
    }
    return -1.0;
}

double qualcost_read(const char *dir, const char *id, int rate, int quantum)
{
    char prefix[PATH_MAX], path[PATH_MAX * 2];
    double best = -1.0;
    struct dirent *e;
    size_t plen, slen = strlen(RECORD_SUFFIX);
    DIR *d;

    if (!dir || !*dir || !id || !*id || !(d = opendir(dir)))
        return -1.0;
    safe(id, prefix, sizeof(prefix) - 2);
    strcat(prefix, "@");
    plen = strlen(prefix);
    while ((e = readdir(d)) != NULL)
    {
        size_t len = strlen(e->d_name);
        char *text;
        jnode_t *record;
        double v;

        if (len <= plen + slen || strncmp(e->d_name, prefix, plen) || strcmp(e->d_name + len - slen, RECORD_SUFFIX))
            continue;
        snprintf(path, sizeof(path), "%s/%s", dir, e->d_name);
        if (!(text = slurp(path)))
            continue;
        record = jparse(text);
        free(text);
        if (!record)
            continue;
        v = point_of(record, id, rate, quantum);
        if (v > best)
            best = v;
        jfree(record);
    }
    closedir(d);
    return best;
}

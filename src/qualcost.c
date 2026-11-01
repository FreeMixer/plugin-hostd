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
#include <sys/stat.h>

#include "json.h"
#include "qualcost.h"

#define RECORD_SUFFIX ".qualification.json"

unsigned long qualcost_dir_scans, qualcost_record_parses;
#define RECORD_MAX    (4u << 20)

static int hexval(int c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* the id as plugin-qualify spells it in a file name: each character outside [A-Za-z0-9._-] is an underscore */
static void safe(const char *id, char *out, size_t size)
{
    size_t n;

    for (n = 0; id[n] && n + 1 < size; n++)
        out[n] = (id[n] >= 'a' && id[n] <= 'z') || (id[n] >= 'A' && id[n] <= 'Z') || (id[n] >= '0' && id[n] <= '9') ||
                 id[n] == '.' || id[n] == '_' || id[n] == '-' ? id[n] : '_';
    out[n] = '\0';
}

/* the id with each %XX escape of an IRI replaced by its byte: LV2 URIs reach the daemon percent-encoded as often as not,
 * and a record may name the plugin in either spelling. An escape that is not two hex digits is kept as it stands. */
static void decode(const char *id, char *out, size_t size)
{
    size_t n = 0;

    while (*id && n + 1 < size)
    {
        int hi, lo;

        if (id[0] == '%' && (hi = hexval(id[1])) >= 0 && (lo = hexval(id[2])) >= 0 && (hi || lo))
        {
            out[n++] = (char)(hi << 4 | lo);
            id += 3;
        }
        else
            out[n++] = *id++;
    }
    out[n] = '\0';
}

/* whether two ids are one plugin's, in either spelling */
static int same_id(const char *a, const char *b)
{
    char da[PATH_MAX], db[PATH_MAX];

    decode(a, da, sizeof(da));
    decode(b, db, sizeof(db));
    return !strcmp(da, db);
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

    if (!got || !same_id(got, id) || !grid || grid->type != J_ARR)
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

    return got && same_id(got, id);
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

/* the records of an id, remembered with the directory's time and each file's time and size: a repeat read lists the
 * directory again only when an entry was added, removed or renamed (the directory's time moves), and parses a record
 * again only when its own time or size moved. Without memory to remember, a read is as it always was. The daemon reads
 * records on its one control thread. */
#define RECORD_MEMO_MAX 1024
typedef struct
{
    char *path;
    struct timespec mtime;
    off_t size;
    jnode_t *record;
} memo_file_t;
static struct record_memo
{
    char *dir, *id;
    struct timespec mtime;
    int n;
    memo_file_t *files;
} g_record_memo[RECORD_MEMO_MAX];
static int g_record_memos;

static int same_time(struct timespec a, struct timespec b)
{
    return a.tv_sec == b.tv_sec && a.tv_nsec == b.tv_nsec;
}

static jnode_t *parse_file(const char *path)
{
    char *text = slurp(path);
    jnode_t *record;

    if (!text)
        return NULL;
    record = jparse(text);
    qualcost_record_parses++;
    free(text);
    return record;
}

static void memo_files_free(memo_file_t *files, int n)
{
    int k;

    for (k = 0; k < n; k++)
    {
        free(files[k].path);
        jfree(files[k].record);
    }
    free(files);
}

/* the records whose file name is the id's, listed and parsed: n files, NULL with *n 0 when none or no memory */
static memo_file_t *list_records(const char *dir, const char *id, int *n)
{
    char prefix[PATH_MAX], plain[PATH_MAX], path[PATH_MAX * 2];
    struct dirent *e;
    size_t plen, plain_len, slen = strlen(RECORD_SUFFIX);
    memo_file_t *files = NULL, *grown;
    DIR *d;

    *n = 0;
    if (!(d = opendir(dir)))
        return NULL;
    qualcost_dir_scans++;
    safe(id, prefix, sizeof(prefix) - 2);
    strcat(prefix, "@");
    plen = strlen(prefix);
    decode(id, plain, sizeof(plain));
    safe(plain, plain, sizeof(plain) - 2);
    strcat(plain, "@");
    plain_len = strlen(plain);
    while ((e = readdir(d)) != NULL)
    {
        size_t len = strlen(e->d_name);
        struct stat st;
        jnode_t *record;

        if (len <= slen || (strncmp(e->d_name, prefix, plen) && strncmp(e->d_name, plain, plain_len)) ||
            len <= (strncmp(e->d_name, prefix, plen) ? plain_len : plen) + slen || strcmp(e->d_name + len - slen, RECORD_SUFFIX))
            continue;
        snprintf(path, sizeof(path), "%s/%s", dir, e->d_name);
        if (stat(path, &st) != 0 || !(record = parse_file(path)))
            continue;
        grown = realloc(files, (*n + 1) * sizeof(*files));
        if (!grown || !(grown[*n].path = strdup(path)))
        {
            jfree(record);
            files = grown ? grown : files;
            continue;
        }
        files = grown;
        files[*n].mtime = st.st_mtim;
        files[*n].size = st.st_size;
        files[*n].record = record;
        (*n)++;
    }
    closedir(d);
    return files;
}

static struct record_memo *record_memo_find(const char *dir, const char *id)
{
    int k;

    for (k = 0; k < g_record_memos; k++)
        if (!strcmp(g_record_memo[k].id, id) && !strcmp(g_record_memo[k].dir, dir))
            return &g_record_memo[k];
    return NULL;
}

/* calls each(record, ctx) for every record of qualification_dir whose file name is the id's */
static void each_record(const char *dir, const char *id, void (*each)(const jnode_t *, void *), void *ctx)
{
    struct record_memo *m;
    struct stat st;
    int k, n;
    memo_file_t *files;

    if (!dir || !*dir || !id || !*id || stat(dir, &st) != 0)
        return;
    m = record_memo_find(dir, id);
    if (m && same_time(m->mtime, st.st_mtim))
    {
        for (k = 0; k < m->n; k++)
        {
            struct stat fs;

            if (stat(m->files[k].path, &fs) != 0)
                break;
            if (!same_time(fs.st_mtim, m->files[k].mtime) || fs.st_size != m->files[k].size)
            {
                jnode_t *record = parse_file(m->files[k].path);

                if (!record)
                    break;
                jfree(m->files[k].record);
                m->files[k].record = record;
                m->files[k].mtime = fs.st_mtim;
                m->files[k].size = fs.st_size;
            }
        }
        if (k == m->n)
        {
            for (k = 0; k < m->n; k++)
                each(m->files[k].record, ctx);
            return;
        }
    }
    files = list_records(dir, id, &n);
    for (k = 0; k < n; k++)
        each(files[k].record, ctx);
    if (m)
    {
        memo_files_free(m->files, m->n);
        m->files = files;
        m->n = n;
        m->mtime = st.st_mtim;
        return;
    }
    if (g_record_memos < RECORD_MEMO_MAX)
    {
        m = &g_record_memo[g_record_memos];
        m->dir = strdup(dir);
        m->id = strdup(id);
        if (m->dir && m->id)
        {
            m->files = files;
            m->n = n;
            m->mtime = st.st_mtim;
            g_record_memos++;
            return;
        }
        free(m->dir);
        free(m->id);
    }
    memo_files_free(files, n);
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

struct memory_ctx {
    const char *id;
    int rate, quantum, found;
    qualcost_memory_t memory;
};

static void memory_of(const jnode_t *record, void *ctx)
{
    struct memory_ctx *c = ctx;
    const jnode_t *point;
    size_t k = 0;

    while ((point = point_at(record, c->id, c->rate, c->quantum, &k)) != NULL)
    {
        const jnode_t *mem = jget(point, "memory");
        double first, per;

        if (!jnum(mem, "firstInstanceKb", &first) || !jnum(mem, "perInstanceKb", &per) || first < 0 || per < 0)
            continue;
        if (!c->found || first > c->memory.first_kb)
            c->memory.first_kb = first;
        if (!c->found || per > c->memory.per_instance_kb)
            c->memory.per_instance_kb = per;
        c->found = 1;
    }
}

int qualcost_memory(const char *dir, const char *id, int rate, int quantum, qualcost_memory_t *out)
{
    struct memory_ctx c = { id, rate, quantum, 0, { 0, 0 } };

    each_record(dir, id, memory_of, &c);
    *out = c.memory;
    return c.found ? 0 : -1;
}

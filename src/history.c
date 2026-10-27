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

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <plugin-hostd/plugin_hostd_vocabulary.h>
#include <plugin-hostd/protocol.h>

#include "fsutil.h"
#include "history.h"

#define HISTORY_LINE_MAX 8192
#define VERSION_PREFIX   "# plugin-hostd history/"
#define SECONDS_PER_DAY  86400

/* The keys are the words of PLUGIN_HOSTD_HISTORY_KEYS in their order; what each holds is the type here, one row per
 * word (tests/history_test.c holds the two to each other). */
typedef enum { K_COUNT, K_TIME, K_PERCENT, K_MIB } kind_t;

static const char *const g_words[] = OMX_PLUGIN_HOSTD_HISTORY_KEYS_INIT;
#define NKEYS OMX_PLUGIN_HOSTD_HISTORY_KEYS_COUNT

static const struct { kind_t kind; size_t offset; } g_keys[] = {
    { K_TIME, offsetof(history_rec_t, first) },
    { K_TIME, offsetof(history_rec_t, last) },
    { K_COUNT, offsetof(history_rec_t, windows_solo) },
    { K_COUNT, offsetof(history_rec_t, windows_grouped) },
    { K_PERCENT, offsetof(history_rec_t, cpu_p95_solo) },
    { K_PERCENT, offsetof(history_rec_t, cpu_max_solo) },
    { K_MIB, offsetof(history_rec_t, pss_mb_solo) },
    { K_COUNT, offsetof(history_rec_t, xrun_windows_solo) },
    { K_COUNT, offsetof(history_rec_t, xrun_windows_grouped) },
    { K_COUNT, offsetof(history_rec_t, crashes_solo) },
    { K_COUNT, offsetof(history_rec_t, crashes_grouped) },
    { K_COUNT, offsetof(history_rec_t, restarts_grouped) },
    { K_COUNT, offsetof(history_rec_t, quarantines) },
    { K_TIME, offsetof(history_rec_t, last_crash) },
    { K_TIME, offsetof(history_rec_t, last_crash_grouped) },
};

_Static_assert(sizeof(g_keys) / sizeof(g_keys[0]) == NKEYS, "one type per word of PLUGIN_HOSTD_HISTORY_KEYS");

/* one line of the file, in the file's order: a record, or a line this version keeps and does not read */
typedef struct ENTRY_T {
    history_rec_t rec;
    char *raw;                  /* the line as it was, NULL for a record */
} entry_t;

static entry_t *g_entry;
static int g_n;
static char g_path[PATH_MAX];
static char *g_class;
static int g_save_s;
static int g_dirty, g_blocked, g_started;
static long long g_saved_at = -1;   /* when the interval between two saves began; -1 until the first tick */

/* ---------------------------------------------------------------- the line grammar */

static void rec_free(history_rec_t *r)
{
    free(r->uri);
    free(r->klass);
}

static void entry_free(entry_t *e)
{
    rec_free(&e->rec);
    free(e->raw);
}

static void *field(history_rec_t *r, int key)
{
    return (char *)r + g_keys[key].offset;
}

static int key_of(const char *word)
{
    int n;

    for (n = 0; n < (int)NKEYS; n++)
        if (!strcmp(word, g_words[n]))
            return n;
    return -1;
}

/* a value as the file writes it: a whole number, or a decimal; never negative, never a word */
static int number_ok(const char *text, kind_t kind, void *out)
{
    char *end;

    if (!*text || *text == '-' || *text == '+' || isspace((unsigned char)*text))
        return 0;
    errno = 0;
    if (kind == K_COUNT || kind == K_TIME)
    {
        long long v = strtoll(text, &end, 10);

        if (*end || errno)
            return 0;
        *(long long *)out = v;
    }
    else
    {
        double v = strtod(text, &end);

        if (*end || errno || !isfinite(v))
            return 0;
        *(double *)out = v;
    }
    return 1;
}

/* a record from the words of a line; 0, or -1 when the line is outside the grammar or holds a key this version does
 * not know. `line` is cut up. */
static int rec_parse(char *line, history_rec_t *r)
{
    char *tok[4 + NKEYS], *save = NULL, *t;
    unsigned seen = 0;
    int ntok = 0, n;

    memset(r, 0, sizeof(*r));
    for (t = strtok_r(line, " \t\r\n", &save); t && ntok < (int)(sizeof(tok) / sizeof(tok[0])); t = strtok_r(NULL, " \t\r\n", &save))
        tok[ntok++] = t;
    if (t || ntok < 4 || strcmp(tok[0], PHD_HISTORY_RECORD) || !phd_pin_hex_valid(tok[2]))
        return -1;
    for (n = 4; n < ntok; n++)
    {
        char *eq = strchr(tok[n], '=');
        int key;

        if (!eq)
            return -1;
        *eq = '\0';
        key = key_of(tok[n]);
        if (key < 0 || (seen & (1u << key)) || !number_ok(eq + 1, g_keys[key].kind, field(r, key)))
            return -1;
        seen |= 1u << key;
    }
    r->uri = strdup(tok[1]);
    r->klass = strdup(tok[3]);
    memcpy(r->digest, tok[2], PHD_SHA256_HEX_LEN + 1);
    if (!r->uri || !r->klass)
    {
        rec_free(r);
        return -1;
    }
    return 0;
}

/* "<sep>key=value" for every key, in the order of the words */
static void keys_write(FILE *out, const history_rec_t *r, char sep)
{
    int n;

    for (n = 0; n < (int)NKEYS; n++)
    {
        const void *v = (const char *)r + g_keys[n].offset;

        switch (g_keys[n].kind)
        {
        case K_PERCENT:
            fprintf(out, "%c%s=%.2f", sep, g_words[n], *(const double *)v);
            break;
        case K_MIB:
            fprintf(out, "%c%s=%.1f", sep, g_words[n], *(const double *)v);
            break;
        default:
            fprintf(out, "%c%s=%lld", sep, g_words[n], *(const long long *)v);
        }
    }
}

char *history_line(const history_rec_t *r)
{
    char *buf = NULL;
    size_t size = 0;
    FILE *mem = open_memstream(&buf, &size);

    if (!mem)
        return NULL;
    fprintf(mem, "%s %s %s %s", PHD_HISTORY_RECORD, r->uri, r->digest, r->klass);
    keys_write(mem, r, ' ');
    fputc('\n', mem);
    fclose(mem);
    return buf;
}

/* ---------------------------------------------------------------- the table */

static entry_t *entry_add(void)
{
    entry_t *grown = realloc(g_entry, (g_n + 1) * sizeof(entry_t));

    if (!grown)
        return NULL;
    g_entry = grown;
    memset(&g_entry[g_n], 0, sizeof(entry_t));
    return &g_entry[g_n++];
}

static history_rec_t *rec_at(const char *uri, const char *digest, const char *klass)
{
    int n;

    for (n = 0; n < g_n; n++)
        if (!g_entry[n].raw && !strcmp(g_entry[n].rec.uri, uri) && !strcmp(g_entry[n].rec.digest, digest) &&
            !strcmp(g_entry[n].rec.klass, klass))
            return &g_entry[n].rec;
    return NULL;
}

/* the record of this class, made when there is none; NULL when the history is unavailable or out of memory */
static history_rec_t *rec_get(const char *uri, const char *digest)
{
    history_rec_t *r;
    entry_t *e;

    if (!g_started || g_blocked || !uri || !*uri || !phd_pin_hex_valid(digest) || strpbrk(uri, " \t\r\n"))
        return NULL;
    if ((r = rec_at(uri, digest, g_class)))
        return r;
    if (!(e = entry_add()))
        return NULL;
    e->rec.uri = strdup(uri);
    e->rec.klass = strdup(g_class);
    memcpy(e->rec.digest, digest, PHD_SHA256_HEX_LEN + 1);
    if (!e->rec.uri || !e->rec.klass)
    {
        entry_free(e);
        g_n--;
        return NULL;
    }
    return &e->rec;
}

const history_rec_t *history_find(const char *uri, const char *digest)
{
    return g_started && !g_blocked && uri && digest ? rec_at(uri, digest, g_class) : NULL;
}

int history_available(void)
{
    return g_started && !g_blocked;
}

/* ---------------------------------------------------------------- reading and writing the file */

static const char *path_of(const char *configured)
{
    const char *state = getenv("XDG_STATE_HOME"), *home = getenv("HOME");

    if (*configured)
        snprintf(g_path, sizeof(g_path), "%s", configured);
    else if (state && *state)
        snprintf(g_path, sizeof(g_path), "%s/" PHD_HISTORY_NAME, state);
    else if (home && *home)
        snprintf(g_path, sizeof(g_path), "%s/.local/state/" PHD_HISTORY_NAME, home);
    else
        g_path[0] = '\0';
    return g_path;
}

static void block(const char *why)
{
    fprintf(stderr, "plugin-hostd: the history %s %s; it is neither read nor overwritten, and none is kept until the "
                    "operator repairs or removes it\n", g_path, why);
    g_blocked = 1;
}

static void held_add(const char *line, size_t n)
{
    entry_t *e = entry_add();

    if (e && !(e->raw = strndup(line, n)))
        g_n--;
}

static void file_read(void)
{
    char *line = NULL;
    size_t cap = 0;
    ssize_t len;
    FILE *file = fopen(g_path, "r");
    int lineno = 0, header = 0;

    if (!file)
    {
        if (errno != ENOENT && errno != ENOTDIR)
        {
            char why[160];

            snprintf(why, sizeof(why), "can't be read: %s", strerror(errno));
            block(why);
        }
        return;
    }
    while ((len = getline(&line, &cap, file)) >= 0)
    {
        size_t n = len;
        char copy[HISTORY_LINE_MAX];
        history_rec_t rec;

        lineno++;
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            n--;
        if (!header)
        {
            if (!n)
                continue;
            if (n != strlen(PHD_HISTORY_HEADER) || strncmp(line, PHD_HISTORY_HEADER, n))
            {
                block(!strncmp(line, VERSION_PREFIX, strlen(VERSION_PREFIX)) ? "has a version this daemon does not know"
                                                                              : "is not a history file");
                break;
            }
            header = 1;
            continue;
        }
        if (!n)
            continue;
        if (line[0] == '#')
        {
            held_add(line, n);
            continue;
        }
        if (n >= sizeof(copy))
        {
            fprintf(stderr, "plugin-hostd: %s:%d: the line is too long; it is kept as it is and not read\n", g_path, lineno);
            held_add(line, n);
            continue;
        }
        memcpy(copy, line, n);
        copy[n] = '\0';
        if (rec_parse(copy, &rec) != 0)
        {
            fprintf(stderr, "plugin-hostd: %s:%d: not a history line, or a key this version does not know; it is kept as "
                            "it is and not read\n", g_path, lineno);
            held_add(line, n);
        }
        else if (rec_at(rec.uri, rec.digest, rec.klass))
        {
            fprintf(stderr, "plugin-hostd: %s:%d: a second line of one plugin binary on one host class; it is kept as it "
                            "is and not read\n", g_path, lineno);
            rec_free(&rec);
            held_add(line, n);
        }
        else
        {
            entry_t *e = entry_add();

            if (e)
                e->rec = rec;
            else
                rec_free(&rec);
        }
    }
    if (!g_blocked && ferror(file))
    {
        char why[160];

        snprintf(why, sizeof(why), "can't be read: %s", strerror(errno));
        block(why);
    }
    free(line);
    fclose(file);
}

/* the history to the file: a temporary file of its own beside it (mkstemp, mode 0600), written, fsynced and renamed over
 * it, then the directory fsynced. A failure is announced and leaves the history in memory */
static int file_write(void)
{
    char tmp[PATH_MAX + 16];
    FILE *file;
    int n, fd = -1, ok;

    if (!*g_path)
        return -1;
    snprintf(tmp, sizeof(tmp), "%s.XXXXXX", g_path);
    if (fs_mkdir_parents(tmp) != 0 || (fd = mkstemp(tmp)) < 0 || !(file = fdopen(fd, "w")))
    {
        int err = errno;

        if (fd >= 0)
        {
            close(fd);
            unlink(tmp);
        }
        fprintf(stderr, "plugin-hostd: can't write the history %s: %s; it is kept in memory and written again at the next "
                        "save\n", g_path, strerror(err));
        return -1;
    }
    fprintf(file, "%s\n", PHD_HISTORY_HEADER);
    for (n = 0; n < g_n; n++)
    {
        char *line = g_entry[n].raw ? NULL : history_line(&g_entry[n].rec);

        if (g_entry[n].raw)
            fprintf(file, "%s\n", g_entry[n].raw);
        else if (line)
            fputs(line, file);
        free(line);
    }
    ok = fflush(file) == 0 && !ferror(file) && fsync(fileno(file)) == 0;
    ok = fclose(file) == 0 && ok;
    if (!ok || rename(tmp, g_path) != 0)
    {
        fprintf(stderr, "plugin-hostd: can't write the history %s: %s; it is kept in memory and written again at the next "
                        "save\n", g_path, strerror(errno));
        unlink(tmp);
        return -1;
    }
    fs_sync_dir(g_path);
    return 0;
}

static void save(long long now)
{
    g_saved_at = now;
    if (file_write() == 0)
        g_dirty = 0;
}

int history_init(const char *file, const char *klass, int save_s)
{
    history_finish();
    g_started = 1;
    g_class = strdup(klass);
    g_save_s = save_s;
    if (!g_class || !*path_of(file))
    {
        if (!g_class)
            g_started = 0;
        else
            fprintf(stderr, "plugin-hostd: no history file: neither history_file, $XDG_STATE_HOME nor $HOME is set; no "
                            "history is kept\n"), g_blocked = 1;
        return 0;
    }
    file_read();
    return 0;
}

void history_tick(long long now)
{
    if (!g_started || g_blocked)
        return;
    if (g_saved_at < 0)
        g_saved_at = now;
    if (g_dirty && now - g_saved_at >= g_save_s)
        save(now);
}

void history_finish(void)
{
    int n;

    if (g_started && !g_blocked && g_dirty)
        file_write();
    for (n = 0; n < g_n; n++)
        entry_free(&g_entry[n]);
    free(g_entry);
    g_entry = NULL;
    g_n = 0;
    free(g_class);
    g_class = NULL;
    g_dirty = g_blocked = g_started = 0;
    g_saved_at = -1;
}

/* ---------------------------------------------------------------- what is counted */

static void touch(history_rec_t *r, long long now)
{
    if (!r->first)
        r->first = now;
    r->last = now;
    g_dirty = 1;
}

/* An estimate of the 95th percentile of the windows run alone that needs no list of them: each window moves the
 * estimate up by 95 parts, or down by 5, of a step that is 2 percent of the estimate (a core's percent never below 1):
 * it rests where one window in twenty is above it. The first window is the estimate. */
static void p95_fold(history_rec_t *r, double cpu)
{
    double step;

    if (r->windows_solo == 0)
    {
        r->cpu_p95_solo = cpu;
        return;
    }
    step = 0.02 * (r->cpu_p95_solo > 1.0 ? r->cpu_p95_solo : 1.0);
    r->cpu_p95_solo += cpu > r->cpu_p95_solo ? 0.95 * step : -0.05 * step;
    if (r->cpu_p95_solo < 0)
        r->cpu_p95_solo = 0;
}

void history_window(const char *uri, const char *digest, int grouped, double cpu_pct, double pss_mb, long xruns,
                    long long now)
{
    history_rec_t *r = rec_get(uri, digest);

    if (!r)
        return;
    touch(r, now);
    if (grouped)
    {
        r->windows_grouped++;
        r->xrun_windows_grouped += xruns > 0;
        return;
    }
    if (!(cpu_pct >= 0))
        cpu_pct = 0;
    p95_fold(r, cpu_pct);
    if (r->windows_solo == 0 || cpu_pct > r->cpu_max_solo)
        r->cpu_max_solo = cpu_pct;
    if (pss_mb > r->pss_mb_solo)
        r->pss_mb_solo = pss_mb;
    r->windows_solo++;
    r->xrun_windows_solo += xruns > 0;
}

void history_crash(const char *uri, const char *digest, int grouped, long long now)
{
    history_rec_t *r = rec_get(uri, digest);

    if (!r)
        return;
    touch(r, now);
    if (grouped)
    {
        r->crashes_grouped++;
        r->last_crash_grouped = now;
    }
    else
    {
        r->crashes_solo++;
        r->last_crash = now;
    }
}

void history_restart(const char *uri, const char *digest, int grouped, long long now)
{
    history_rec_t *r = grouped ? rec_get(uri, digest) : NULL;

    if (!r)
        return;
    touch(r, now);
    r->restarts_grouped++;
}

void history_quarantine(const char *uri, const char *digest, long long now)
{
    history_rec_t *r = rec_get(uri, digest);

    if (!r)
        return;
    touch(r, now);
    r->quarantines++;
}

/* ---------------------------------------------------------------- what is read */

static int crashed(const history_rec_t *r, long long now)
{
    long long last = r->last_crash > r->last_crash_grouped ? r->last_crash : r->last_crash_grouped;

    return r->crashes_solo + r->crashes_grouped > 0 && now - last <= (long long)PHD_HISTORY_KEEP_DAYS * SECONDS_PER_DAY;
}

/* the share of xrun windows grouped exceeds the share alone by the margin: xg/wg > xs/ws + m/100, cross-multiplied */
static int raises_xruns(const history_rec_t *r)
{
    long long wg = r->windows_grouped, xg = r->xrun_windows_grouped, ws = r->windows_solo, xs = r->xrun_windows_solo;

    if (wg < PHD_HISTORY_MIN_WINDOWS)
        return 0;
    if (ws == 0)
        return 100 * xg > (long long)PHD_HISTORY_XRUN_MARGIN_PCT * wg;
    return 100 * xg * ws > 100 * xs * wg + (long long)PHD_HISTORY_XRUN_MARGIN_PCT * wg * ws;
}

char *history_summary(const char *uri, const char *digest, long long now)
{
    const history_rec_t *r = history_find(uri, digest);
    char *buf = NULL;
    size_t size = 0;
    FILE *mem;

    if (!r || !(mem = open_memstream(&buf, &size)))
        return NULL;
    fprintf(mem, "digest=%s,class=%s,crashed=%d,raises_xruns=%d", r->digest, r->klass, crashed(r, now), raises_xruns(r));
    keys_write(mem, r, ',');
    fclose(mem);
    return buf;
}

/* ---------------------------------------------------------------- clear */

/* the uri a held line names: its second word, after history */
static int raw_names(const char *raw, const char *uri)
{
    char copy[HISTORY_LINE_MAX], *save = NULL, *t;

    snprintf(copy, sizeof(copy), "%s", raw);
    t = strtok_r(copy, " \t", &save);
    if (!t || strcmp(t, PHD_HISTORY_RECORD))
        return 0;
    t = strtok_r(NULL, " \t", &save);
    return t && !strcmp(t, uri);
}

int history_clear(const char *uri)
{
    int n, keep = 0, all = !strcmp(uri, PHD_WORD_ALL);

    if (!g_started || g_blocked)
        return -1;
    for (n = 0; n < g_n; n++)
    {
        int gone = all || (g_entry[n].raw ? raw_names(g_entry[n].raw, uri) : !strcmp(g_entry[n].rec.uri, uri));

        if (gone)
            entry_free(&g_entry[n]);
        else
            g_entry[keep++] = g_entry[n];
    }
    if (keep != g_n)
    {
        g_n = keep;
        g_dirty = 1;
        if (file_write() == 0)
            g_dirty = 0;
    }
    return 0;
}

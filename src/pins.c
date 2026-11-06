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

#include <dirent.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <host-errors.h>
#include <plugin-db/pin.h>
#include <plugin-hostd/protocol.h>

#include "formats.h"
#include "fsutil.h"
#include "pins.h"
#include "words.h"
#include "writer.h"

#define SCHEME_MAX   32
#define STORE_NAME   "plugin-hostd/pins"
#define LINE_MAX_PIN (PHD_LINE_MAX * 2)
/* what a line grows by when its layout (omx-layout/1:<sha256>) and a verdict are added */
#define LINE_RESERVE 128
#define PINS_SUFFIX  ".pins"

typedef struct PIN_T {
    char *uri;
    char **path;
    char (*digest)[PHD_SHA256_HEX_LEN + 1];
    int nfiles;
    char scheme[SCHEME_MAX];
    char *layout;
    char verdict[16];           /* one of PHD_PIN_VERDICTS, or empty */
    char pool[8];               /* one of PHD_PIN_POOLS, or empty */
    int learned;                /* the daemon recorded it: the store keeps it */
    int from_set;               /* a controller's pin_set: a reload keeps it */
} pin_t;

/* The host's pins: the store, the pin_file and pin_set, the one table the daemon writes and saves from */
static pin_t *g_pins;
static int g_npins;
static char g_store[PATH_MAX];

/* The packages' pins: the *.pins files of pins_dir, read at start and never written */
static pin_t *g_pkg;
static int g_npkg;

/* the uri as the worker is given it: the key of a pin, whichever way a controller wrote it */
static const char *bare(const char *uri)
{
    const char *worker_uri;

    format_of_uri(uri, &worker_uri);
    return worker_uri;
}

static void pin_free(pin_t *p)
{
    int n;

    for (n = 0; n < p->nfiles; n++)
        free(p->path[n]);
    free(p->path);
    free(p->digest);
    free(p->uri);
    free(p->layout);
}

static pin_t *find_in(pin_t *table, int count, const char *uri)
{
    int n;

    for (n = 0; n < count; n++)
        if (!strcmp(table[n].uri, uri))
            return &table[n];
    return NULL;
}

static int refused(const pin_t *p)
{
    return !strcmp(p->verdict, PHD_PIN_VERDICT_REFUSED);
}

/* The plugins the user chose to load although their pin carries verdict=refused, from a pins.d file or the pin_file
 * (pin_accept under first-use). A failed qualification is our advice, not a wall: the user decides. The choice is kept
 * beside the store, one uri per line, and counts only under first-use (g_accepting): strict admits what passed and
 * nothing else. An accepted plugin is admitted with the files its pin holds and is never qualified for a shared
 * worker, so it runs alone. */
static char **g_accepted;
static int g_naccepted;
static int g_accepting;
static char g_accepted_path[PATH_MAX + 16];

static int accepted(const char *uri)
{
    int n;

    if (!g_accepting)
        return 0;
    for (n = 0; n < g_naccepted; n++)
        if (!strcmp(g_accepted[n], uri))
            return 1;
    return 0;
}

/* the package pin of the uri when it carries verdict=refused, whether or not the user accepted it */
static pin_t *pkg_refused(const char *uri)
{
    pin_t *p = find_in(g_pkg, g_npkg, uri);

    return p && refused(p) ? p : NULL;
}

/* the package pin of the uri when it carries verdict=refused and the user has not chosen to load it: nothing of the
 * host's overrides it */
static pin_t *pkg_refusal(const char *uri)
{
    return accepted(uri) ? NULL : pkg_refused(uri);
}

/* the pin that holds for a uri: a package refusal, else the host's pin, else the package's */
static pin_t *find(const char *uri)
{
    pin_t *p = pkg_refusal(uri);

    if (!p)
        p = find_in(g_pins, g_npins, uri);
    return p ? p : find_in(g_pkg, g_npkg, uri);
}

/* a path of a pin: relative to the bundle, never out of it, and none of the separators of pin_set's words */
static int path_valid(const char *path)
{
    const char *c = path;

    if (!*path || *path == '/' || strpbrk(path, PHD_PIN_PATH_EXCLUDED))
        return 0;
    while (*c)
    {
        size_t n = strcspn(c, "/");

        if (n == 0 || (n == 2 && !strncmp(c, "..", 2)))
            return 0;
        c += n;
        if (*c == '/')
            c++;
    }
    return c[-1] != '/';
}

static int held(const pin_t *p, const char *path)
{
    int n;

    for (n = 0; n < p->nfiles; n++)
        if (!strcmp(p->path[n], path))
            return n;
    return -1;
}

/* a pin from its words; the pin is not in the table yet. `unknown_ok` lets the layout be PHD_PIN_LAYOUT_UNKNOWN */
static int pin_build(pin_t *pin, const char *uri, const char *files, const char *layout, const char *verdict,
                     const char *pool, int unknown_ok)
{
    char *copy = strdup(files), *item, *save = NULL, hex[PHD_SHA256_HEX_LEN + 1];

    memset(pin, 0, sizeof(*pin));
    if (!copy)
        return ERR_MEMORY_ALLOCATION;
    if (unknown_ok && !strcmp(layout, PHD_PIN_LAYOUT_UNKNOWN))
        ;
    else if (phd_pin_layout_parse(layout, pin->scheme, sizeof(pin->scheme), hex) != 0)
        goto invalid;
    if (verdict && (!phd_pin_verdict_valid(verdict) || strlen(verdict) >= sizeof(pin->verdict)))
        goto invalid;
    if (pool && (!phd_pin_pool_valid(pool) || strlen(pool) >= sizeof(pin->pool)))
        goto invalid;
    for (item = strtok_r(copy, PHD_PIN_FILE_SEPARATOR, &save); item; item = strtok_r(NULL, PHD_PIN_FILE_SEPARATOR, &save))
    {
        char *eq = strrchr(item, PHD_PIN_DIGEST_SEPARATOR[0]);

        if (!eq)
            goto invalid;
        *eq = '\0';
        if (!path_valid(item) || !phd_pin_hex_valid(eq + 1) || held(pin, item) >= 0)
            goto invalid;
        {
            char **paths = realloc(pin->path, (pin->nfiles + 1) * sizeof(char *));
            char (*digests)[PHD_SHA256_HEX_LEN + 1];

            if (!paths)
                goto no_memory;
            pin->path = paths;
            digests = realloc(pin->digest, (pin->nfiles + 1) * sizeof(*pin->digest));
            if (!digests)
                goto no_memory;
            pin->digest = digests;
        }
        pin->path[pin->nfiles] = strdup(item);
        if (!pin->path[pin->nfiles])
            goto no_memory;
        memcpy(pin->digest[pin->nfiles], eq + 1, PHD_SHA256_HEX_LEN + 1);
        pin->nfiles++;
    }
    if (!pin->nfiles)
        goto invalid;
    pin->uri = strdup(bare(uri));
    pin->layout = strdup(layout);
    if (!pin->uri || !pin->layout)
        goto no_memory;
    free(copy);
    if (verdict)
        snprintf(pin->verdict, sizeof(pin->verdict), "%s", verdict);
    if (pool)
        snprintf(pin->pool, sizeof(pin->pool), "%s", pool);
    return SUCCESS;

invalid:
    free(copy);
    pin_free(pin);
    return ERR_INVALID_OPERATION;

no_memory:
    free(copy);
    pin_free(pin);
    return ERR_MEMORY_ALLOCATION;
}

/* the pin in the host's table, replacing the one of its uri; -1, the table as it was and the pin still the caller's,
 * when memory runs out */
static int pin_put(pin_t *pin)
{
    pin_t *old = find_in(g_pins, g_npins, pin->uri);

    if (old)
    {
        pin_free(old);
        *old = *pin;
    }
    else
    {
        pin_t *grown = realloc(g_pins, (g_npins + 1) * sizeof(pin_t));

        if (!grown)
            return -1;
        g_pins = grown;
        g_pins[g_npins++] = *pin;
    }
    return 0;
}

/* the pin in the packages' table: of two pins of one uri a refusal wins, else the later one, read from the file later in
 * name order or the later line of one file */
static void pkg_put(pin_t *pin, const char *path, int lineno)
{
    pin_t *old = find_in(g_pkg, g_npkg, pin->uri);

    if (old && refused(old) && !refused(pin))
    {
        fprintf(stderr, "plugin-hostd: %s:%d: %s keeps the " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED " of an earlier "
                        "pins.d line\n", path, lineno, pin->uri);
        pin_free(pin);
    }
    else if (old)
    {
        pin_free(old);
        *old = *pin;
    }
    else
    {
        g_pkg = realloc(g_pkg, (g_npkg + 1) * sizeof(pin_t));
        g_pkg[g_npkg++] = *pin;
    }
}

/* ---------------------------------------------------------------- the store and the pin lines */

static const char *store_path(const char *configured)
{
    const char *state = getenv("XDG_STATE_HOME"), *home = getenv("HOME");

    if (*configured)
        snprintf(g_store, sizeof(g_store), "%s", configured);
    else if (state && *state)
        snprintf(g_store, sizeof(g_store), "%s/" STORE_NAME, state);
    else if (home && *home)
        snprintf(g_store, sizeof(g_store), "%s/.local/state/" STORE_NAME, home);
    else
        g_store[0] = '\0';
    return g_store;
}

static void line_write(FILE *file, const pin_t *p)
{
    char uri[LINE_MAX_PIN];
    int n;

    /* a uri with a blank in it is one word only in quotes */
    words_write(p->uri, uri, sizeof(uri));
    fprintf(file, "%s %s ", OMX_VERB_PIN_SET, uri);
    for (n = 0; n < p->nfiles; n++)
        fprintf(file, "%s%s" PHD_PIN_DIGEST_SEPARATOR "%s", n ? PHD_PIN_FILE_SEPARATOR : "", p->path[n], p->digest[n]);
    fprintf(file, " %s", p->layout);
    if (*p->verdict)
        fprintf(file, " " PHD_PIN_VERDICT_KEY "%s", p->verdict);
    if (*p->pool)
        fprintf(file, " " PHD_PIN_POOL_KEY "%s", p->pool);
    fprintf(file, "\n");
}

/* the bytes of the pin's line */
static size_t line_size(const pin_t *p)
{
    char *buf = NULL;
    size_t size = 0;
    FILE *mem = open_memstream(&buf, &size);

    if (!mem)
        return SIZE_MAX;
    line_write(mem, p);
    fclose(mem);
    free(buf);
    return size;
}

/* Lines of the store this version could not parse. They are kept verbatim and written back by every save, so a corrupt
 * line is never dropped by the next save, and the uri they name (when one can be read) is never learned again: the pin
 * that line held is the operator's to repair or remove by hand. A store that could not be read at all blocks every
 * write and every learning for the same reason. */
static char **g_held;
static int g_nheld;
static int g_store_unreadable;

static void held_add(const char *line)
{
    size_t n = strlen(line);

    while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
        n--;
    if (!n)
        return;
    g_held = realloc(g_held, (g_nheld + 1) * sizeof(char *));
    g_held[g_nheld] = strndup(line, n);
    g_nheld++;
}

/* the uri a held line names: its first word, or the second after the verb */
static int held_names(const char *line, const char *uri)
{
    char copy[LINE_MAX_PIN], *tok[2];
    int ntok;

    snprintf(copy, sizeof(copy), "%s", line);
    ntok = words_read(copy, tok, 2);
    if (ntok > 1 && !strcmp(tok[0], OMX_VERB_PIN_SET))
        return !strcmp(bare(tok[1]), uri);
    return ntok > 0 && !strcmp(bare(tok[0]), uri);
}

static int uri_held(const char *uri)
{
    int n;

    for (n = 0; n < g_nheld; n++)
        if (held_names(g_held[n], bare(uri)))
            return 1;
    return 0;
}

static void held_free(void)
{
    while (g_nheld)
        free(g_held[--g_nheld]);
    free(g_held);
    g_held = NULL;
    g_store_unreadable = 0;
}

/* the pins the daemon learned, to the store, through the writer (writer.h): a temporary file of its own beside it
 * (mkstemp, so two daemons on one store never share a name), written, fsynced and renamed over it, then the directory
 * fsynced. A failure is announced on stderr, with what it costs, and leaves the pins in memory */
static void store_save(void)
{
    char *bytes = NULL;
    size_t len = 0;
    FILE *file;
    int n;

    if (!*g_store)
        return;
    if (g_store_unreadable)
    {
        fprintf(stderr, "plugin-hostd: the pin store %s could not be read: NOT overwriting it; the pins learned this run "
                        "are NOT persisted until the operator repairs it\n", g_store);
        return;
    }
    /* the bytes of now, handed to the writer: the command loop never waits on the disk */
    if (!(file = open_memstream(&bytes, &len)))
    {
        fprintf(stderr, "plugin-hostd: can't write the pin store %s: out of memory; the pins learned this run are NOT "
                        "persisted and the next start learns them again\n", g_store);
        return;
    }
    for (n = 0; n < g_nheld; n++)
        fprintf(file, "%s\n", g_held[n]);
    for (n = 0; n < g_npins; n++)
        if (g_pins[n].learned)
            line_write(file, &g_pins[n]);
    if (fclose(file) != 0)
    {
        free(bytes);
        return;
    }
    writer_put(g_store, bytes, len, 0, NULL, NULL, "the pin store %s: %s; the pins learned this run are NOT persisted and the next start learns them again");
}

/* ---------------------------------------------------------------- the user's choices */

static void accepted_free(void)
{
    while (g_naccepted)
        free(g_accepted[--g_naccepted]);
    free(g_accepted);
    g_accepted = NULL;
}

static int accepted_add(const char *uri)
{
    char **grown, *copy;
    int n;

    for (n = 0; n < g_naccepted; n++)
        if (!strcmp(g_accepted[n], uri))
            return 0;
    grown = realloc(g_accepted, (g_naccepted + 1) * sizeof(*g_accepted));
    if (!grown)
        return -1;
    g_accepted = grown;
    copy = strdup(uri);
    if (!copy)
        return -1;
    g_accepted[g_naccepted++] = copy;
    return 0;
}

/* forget the user's choice of `uri`, or of every plugin when it is PHD_WORD_ALL; 1 when one was forgotten */
static int accepted_drop(const char *uri)
{
    int n = 0, dropped = 0;

    while (n < g_naccepted)
        if (!strcmp(uri, PHD_WORD_ALL) || !strcmp(g_accepted[n], uri))
        {
            free(g_accepted[n]);
            g_accepted[n] = g_accepted[--g_naccepted];
            dropped = 1;
        }
        else
            n++;
    return dropped;
}

/* the file of the user's choices, beside the store: none when the store has no path */
static const char *accepted_file(void)
{
    if (!*g_store)
        return NULL;
    snprintf(g_accepted_path, sizeof(g_accepted_path), "%s.accepted", g_store);
    return g_accepted_path;
}

static void accepted_read(void)
{
    const char *path = accepted_file();
    char line[PHD_LINE_MAX + 2];
    FILE *file;

    if (!path || !(file = fopen(path, "r")))
        return;
    while (fgets(line, sizeof(line), file))
    {
        line[strcspn(line, "\r\n")] = '\0';
        if (*line && *line != '#' && accepted_add(line) != 0)
            fprintf(stderr, "plugin-hostd: %s: out of memory, the user's choice of %s is not read\n", path, line);
    }
    fclose(file);
}

/* through the writer, as the store is; a failure is said and costs the choice after a restart only */
static void accepted_save(void)
{
    const char *path = accepted_file();
    char *bytes = NULL;
    size_t len = 0;
    FILE *file;
    int n;

    if (!path)
        return;
    if (!(file = open_memstream(&bytes, &len)))
    {
        fprintf(stderr, "plugin-hostd: can't write %s: out of memory; the user's choices are NOT kept past a restart\n", path);
        return;
    }
    fprintf(file, "# plugins the user chose to load although their qualification refused them (pin_accept)\n");
    for (n = 0; n < g_naccepted; n++)
        fprintf(file, "%s\n", g_accepted[n]);
    if (fclose(file) != 0)
    {
        free(bytes);
        return;
    }
    writer_put(path, bytes, len, 0, NULL, NULL, "%s: %s; the user's choices are NOT kept past a restart");
}

void pins_accepting(int on)
{
    g_accepting = on;
}

/* where a file of pin lines goes, and what a line outside the grammar costs there */
typedef enum { LAYER_STORE, LAYER_FILE, LAYER_PKG } layer_t;

/* the optional words after the layout, each once and in either order: verdict=<word>, pool=<word>; their values, NULL for
 * a word that is not there. SUCCESS, or ERR_INVALID_OPERATION for any other word or a repeated one */
/* one line: the words of pin_set, the verb in front or not; a blank or comment line is SUCCESS and records nothing */
static int line_read(char *line, layer_t layer, const char *path, int lineno)
{
    char *tok[8];
    const char *verdict, *pool;
    int ntok = 0, first = 0, rc;
    pin_t pin;

    ntok = words_read(line, tok, 8);
    if (ntok < 0)
        return ERR_MEMORY_ALLOCATION;
    if (ntok == 0 || tok[0][0] == '#')
        return SUCCESS;
    if (!strcmp(tok[0], OMX_VERB_PIN_SET))
        first = 1;
    if (ntok - first < 3 || ntok - first > 5)
        return ERR_INVALID_OPERATION;
    if (pins_words(tok + first + 3, ntok - first - 3, &verdict, &pool) != SUCCESS)
        return ERR_INVALID_OPERATION;
    rc = pin_build(&pin, tok[first], tok[first + 1], tok[first + 2], verdict, pool, 1);
    if (rc != SUCCESS)
        return rc;
    if (layer == LAYER_PKG)
    {
        pkg_put(&pin, path, lineno);
        return SUCCESS;
    }
    pin.learned = layer == LAYER_STORE;
    if (pin_put(&pin) != 0)
    {
        pin_free(&pin);
        return ERR_MEMORY_ALLOCATION;
    }
    return SUCCESS;
}

/* a pin_file is strict: a bad line ends the start. The store keeps a bad line verbatim and blocks its uri; a pins.d file
 * skips it. Either names it on stderr */
static int file_read(const char *path, layer_t layer)
{
    int strict = layer == LAYER_FILE, learned = layer == LAYER_STORE;

    char *line = NULL;
    size_t cap = 0;
    ssize_t len;
    FILE *file = fopen(path, "r");
    int lineno = 0;

    if (!file)
    {
        if (strict)
            fprintf(stderr, "plugin-hostd: can't open the pin file %s: %s\n", path, strerror(errno));
        else if (layer == LAYER_PKG)
            fprintf(stderr, "plugin-hostd: can't open the pins.d file %s: %s; its pins are skipped\n", path,
                    strerror(errno));
        else if (errno != ENOENT && errno != ENOTDIR)
        {
            /* a store that exists and can't be opened is not a first run */
            fprintf(stderr, "plugin-hostd: can't read the pin store %s: %s; learning and saving are blocked until it "
                            "is repaired\n", path, strerror(errno));
            g_store_unreadable = 1;
        }
        return strict ? -1 : 0;
    }
    while ((len = getline(&line, &cap, file)) >= 0)
    {
        char buf[LINE_MAX_PIN];
        int too_long = (size_t)len >= sizeof(buf);

        lineno++;
        /* a line longer than the buffer is one line: never cut into pieces that parse on their own */
        if (!too_long)
            memcpy(buf, line, len + 1);
        if (too_long || line_read(buf, layer, path, lineno) != SUCCESS)
        {
            fprintf(stderr, "plugin-hostd: %s:%d: not a pin%s%s\n", path, lineno, too_long ? " (the line is too long)" : "",
                    strict ? "" : layer == LAYER_PKG ? "; the line is skipped"
                    : "; the line is kept as it is and its plugin is not learned again until the operator repairs or "
                      "removes it");
            if (strict)
            {
                free(line);
                fclose(file);
                return -1;
            }
            if (learned)
                held_add(line);
        }
    }
    free(line);
    if (ferror(file) && layer == LAYER_PKG)
        fprintf(stderr, "plugin-hostd: can't read the pins.d file %s: %s; the pins after line %d are skipped\n", path,
                strerror(errno), lineno);
    else if (ferror(file) && !strict)
    {
        fprintf(stderr, "plugin-hostd: can't read the pin store %s: %s; learning and saving are blocked until it is "
                        "repaired\n", path, strerror(errno));
        g_store_unreadable = 1;
    }
    fclose(file);
    return 0;
}

/* a *.pins file, by its name: a hidden one (an editor's or a package manager's temporary) is not one */
static int pins_name(const struct dirent *entry)
{
    size_t n = strlen(entry->d_name), suffix = strlen(PINS_SUFFIX);

    return entry->d_name[0] != '.' && n > suffix && !strcmp(entry->d_name + n - suffix, PINS_SUFFIX);
}

/* byte order, whatever the locale */
static int name_order(const struct dirent **a, const struct dirent **b)
{
    return strcmp((*a)->d_name, (*b)->d_name);
}

static void pkg_read(const char *dir)
{
    struct dirent **names;
    char path[PATH_MAX * 2];
    int n, count = scandir(dir, &names, pins_name, name_order);

    if (count < 0)
    {
        if (errno != ENOENT && errno != ENOTDIR)
            fprintf(stderr, "plugin-hostd: can't read the pins directory %s: %s; its pins are skipped\n", dir,
                    strerror(errno));
        return;
    }
    for (n = 0; n < count; n++)
    {
        snprintf(path, sizeof(path), "%s/%s", dir, names[n]->d_name);
        file_read(path, LAYER_PKG);
        free(names[n]);
    }
    free(names);
}

static void pkg_free(void)
{
    while (g_npkg)
        pin_free(&g_pkg[--g_npkg]);
    free(g_pkg);
    g_pkg = NULL;
}

/* where the pins came from at start, and what the files of them looked like then: a reload reads the same places */
static char g_cfg_store[PATH_MAX], g_cfg_file[PATH_MAX], g_cfg_dir[PATH_MAX];
static uint64_t g_signature;

static uint64_t mix(uint64_t h, uint64_t v)
{
    return (h ^ v) * 1099511628211ULL;
}

static uint64_t stat_mix(uint64_t h, const char *path)
{
    struct stat st;

    if (stat(path, &st) != 0)
        return mix(h, 1);
    h = mix(h, (uint64_t)st.st_ino);
    h = mix(h, (uint64_t)st.st_size);
    h = mix(h, (uint64_t)st.st_mtim.tv_sec);
    return mix(h, (uint64_t)st.st_mtim.tv_nsec);
}

/* what the pin_file and the pins_dir files are now: inode, size and mtime of each, so a rewrite in place and a rename
 * over it both show. The store is the daemon's own and is not looked at */
static uint64_t signature(void)
{
    uint64_t h = 14695981039346656037ULL;
    struct dirent **names;
    char path[PATH_MAX * 2];
    int n, count;

    if (*g_cfg_file)
        h = stat_mix(h, g_cfg_file);
    if (!*g_cfg_dir)
        return h;
    h = stat_mix(h, g_cfg_dir);
    count = scandir(g_cfg_dir, &names, pins_name, name_order);
    for (n = 0; n < count; n++)
    {
        snprintf(path, sizeof(path), "%s/%s", g_cfg_dir, names[n]->d_name);
        h = stat_mix(mix(h, (uint64_t)n), path);
        free(names[n]);
    }
    if (count >= 0)
        free(names);
    return h;
}

static int load(void)
{
    int n, rc;

    if (*g_cfg_dir)
        pkg_read(g_cfg_dir);
    accepted_free();
    if (*store_path(g_cfg_store))
    {
        file_read(g_store, LAYER_STORE);
        accepted_read();
    }
    rc = *g_cfg_file ? file_read(g_cfg_file, LAYER_FILE) : 0;
    for (n = 0; n < g_npins; n++)
        if (pkg_refusal(g_pins[n].uri))
            fprintf(stderr, "plugin-hostd: %s: its pins.d pin carries " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED
                            ", which the pin of the %s does not override\n", g_pins[n].uri,
                    g_pins[n].learned ? "pin store" : "pin_file");
    return rc;
}

int pins_init(const char *store, const char *file, const char *dir)
{
    held_free();
    pkg_free();
    snprintf(g_cfg_store, sizeof(g_cfg_store), "%s", store);
    snprintf(g_cfg_file, sizeof(g_cfg_file), "%s", file);
    snprintf(g_cfg_dir, sizeof(g_cfg_dir), "%s", dir);
    g_signature = signature();
    return load();
}

static void table_free(pin_t *table, int count)
{
    while (count)
        pin_free(&table[--count]);
    free(table);
}

int pins_reload(void)
{
    pin_t *old_pins = g_pins, *old_pkg = g_pkg;
    int old_npins = g_npins, old_npkg = g_npkg, n, rc;
    char **old_held = g_held;
    int old_nheld = g_nheld, old_unreadable = g_store_unreadable;

    /* the new tables are made on the side and put in at once: a bad pin_file leaves the pins as they were */
    g_signature = signature();
    g_pins = g_pkg = NULL;
    g_npins = g_npkg = 0;
    g_held = NULL;
    g_nheld = g_store_unreadable = 0;
    rc = load();
    if (rc != 0)
    {
        table_free(g_pins, g_npins);
        table_free(g_pkg, g_npkg);
        held_free();
        g_pins = old_pins;
        g_pkg = old_pkg;
        g_npins = old_npins;
        g_npkg = old_npkg;
        g_held = old_held;
        g_nheld = old_nheld;
        g_store_unreadable = old_unreadable;
        fprintf(stderr, "plugin-hostd: the pins are NOT reloaded; the earlier ones hold\n");
        return rc;
    }
    /* a controller's pin_set is not in any file: it holds over what was read, as it held over it at start */
    for (n = 0; n < old_npins; n++)
        if (old_pins[n].from_set && !pkg_refusal(old_pins[n].uri))
        {
            if (pin_put(&old_pins[n]) == 0)
                memset(&old_pins[n], 0, sizeof(old_pins[n]));
            else
                fprintf(stderr, "plugin-hostd: %s: out of memory, its pin_set does not hold over the reload\n", old_pins[n].uri);
        }
    table_free(old_pins, old_npins);
    table_free(old_pkg, old_npkg);
    while (old_nheld)
        free(old_held[--old_nheld]);
    free(old_held);
    return SUCCESS;
}

int pins_changed(void)
{
    return (*g_cfg_file || *g_cfg_dir) && signature() != g_signature;
}

int pins_set(const char *uri, const char *files, const char *layout, const char *verdict, const char *pool)
{
    pin_t pin;
    int rc = pin_build(&pin, uri, files, layout, verdict, pool, 0);

    if (rc != SUCCESS)
        return rc;
    if (pkg_refusal(pin.uri))
    {
        fprintf(stderr, "plugin-hostd: %s: its pins.d pin carries " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED
                        ", which pin_set does not override\n", pin.uri);
        pin_free(&pin);
        return OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP;
    }
    pin.from_set = 1;
    if (pin_put(&pin) != 0)
    {
        pin_free(&pin);
        return ERR_MEMORY_ALLOCATION;
    }
    return SUCCESS;
}

static void own_free(void)
{
    while (g_npins)
        pin_free(&g_pins[--g_npins]);
    free(g_pins);
    g_pins = NULL;
}

int pins_known(const char *uri)
{
    return find(bare(uri)) != NULL;
}

int pins_digest(const char *uri, char hex[PHD_SHA256_HEX_LEN + 1])
{
    const pin_t *p = find(bare(uri));

    if (!p || p->nfiles < 1)
        return -1;
    memcpy(hex, p->digest[0], PHD_SHA256_HEX_LEN + 1);
    return 0;
}

int pins_in_process(const char *uri)
{
    const pin_t *p = find(bare(uri));

    return p && !strcmp(p->verdict, PHD_PIN_VERDICT_IN_PROCESS);
}

int pins_pool_cores(const char *uri)
{
    const pin_t *p = find(bare(uri));

    return p && !strcmp(p->pool, PHD_PIN_POOL_CORES) && strcmp(p->verdict, PHD_PIN_VERDICT_REFUSED);
}

const char *pins_verdict(const char *uri)
{
    const pin_t *p = find(bare(uri));

    return p ? p->verdict : NULL;
}

int pins_clear(const char *uri)
{
    pin_t *p;
    int learned = 0;

    if (accepted_drop(strcmp(uri, PHD_WORD_ALL) ? bare(uri) : uri))
        accepted_save();
    if (!strcmp(uri, PHD_WORD_ALL))
    {
        for (p = g_pins; p < g_pins + g_npins; p++)
            learned |= p->learned;
        own_free();
        if (learned)
            store_save();
        return SUCCESS;
    }
    /* the host's pin: a package pin is read-only and holds again */
    p = find_in(g_pins, g_npins, bare(uri));
    if (p)
    {
        learned = p->learned;
        pin_free(p);
        *p = g_pins[--g_npins];
        if (learned)
            store_save();
    }
    return SUCCESS;
}

void pins_finish(void)
{
    own_free();
    pkg_free();
    accepted_free();
}

/* ---------------------------------------------------------------- the check */

int pin_refuse(const char *uri, const char *path, const char *why)
{
    fprintf(stderr, "plugin-hostd: %s: %s %s\n", uri, path, why);
    return OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP;
}

int pin_percent_decode(const char *in, char *out, size_t size)
{
    size_t o = 0;

    for (; *in; in++, o++)
    {
        int hi, lo;

        if (o + 1 >= size)
            return -1;
        if (*in != '%')
        {
            out[o] = *in;
            continue;
        }
        hi = isxdigit((unsigned char)in[1]) ? in[1] : -1;
        lo = hi >= 0 && isxdigit((unsigned char)in[2]) ? in[2] : -1;
        if (lo < 0)
            return -1;
        hi = hi <= '9' ? hi - '0' : (hi | 0x20) - 'a' + 10;
        lo = lo <= '9' ? lo - '0' : (lo | 0x20) - 'a' + 10;
        if (!(hi * 16 + lo))
            return -1;
        out[o] = (char)(hi * 16 + lo);
        in += 2;
    }
    out[o] = '\0';
    return 0;
}

/* root/path as a file name: a pin names its files percent-encoded, whatever its path holds of whitespace */
static int full_path(const char *root, const char *path, char *full, size_t size)
{
    char name[PATH_MAX];
    const char *c;
    int slashes = 0, decoded = 0;

    if (pin_percent_decode(path, name, sizeof(name)) != 0)
        return -1;
    for (c = path; *c; c++)
        slashes += *c == '/';
    for (c = name; *c; c++)
        decoded += *c == '/';
    if (slashes != decoded)
        return -1;
    return snprintf(full, size, "%s/%s", root, name) >= (int)size ? -1 : 0;
}

/* the file of a pin hashed over one open descriptor */
static int hash_file(const char *root, const char *path, const char *want, const char *uri)
{
    char full[PATH_MAX * 2], hex[PHD_SHA256_HEX_LEN + 1];
    struct stat st;
    int fd, rc = SUCCESS;

    if (full_path(root, path, full, sizeof(full)) != 0)
        return pin_refuse(uri, path, "is not a file name");
    fd = open(full, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return pin_refuse(uri, path, "is missing");
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode))
        rc = pin_refuse(uri, path, "is not a file");
    else if (phd_pin_fd_digest(fd, hex) != 0 || strcmp(hex, want))
        rc = pin_refuse(uri, path, "differs from its pin");
    close(fd);
    return rc;
}

/* ---------------------------------------------------------------- first use */

static int digest_of(const char *root, const char *path, char hex[PHD_SHA256_HEX_LEN + 1])
{
    char full[PATH_MAX * 2];
    struct stat st;
    int fd, rc = -1;

    if (full_path(root, path, full, sizeof(full)) != 0)
        return -1;
    fd = open(full, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    if (fstat(fd, &st) == 0 && S_ISREG(st.st_mode))
        rc = phd_pin_fd_digest(fd, hex);
    close(fd);
    return rc;
}

/* the pin of a uri from the files on disk now, layout unknown, learned */
static int record(const format_t *format, const char *uri, const char *search)
{
    char root[PATH_MAX], hex[PHD_SHA256_HEX_LEN + 1], *words;
    names_t files = { NULL, 0 };
    size_t cap = 1;
    int n, rc = format->pin_collect(uri, search, root, sizeof(root), &files);
    pin_t pin;

    memset(&pin, 0, sizeof(pin));

    if (rc == SUCCESS && (g_store_unreadable || uri_held(uri)))
    {
        fprintf(stderr, "plugin-hostd: %s: %s; not learned\n", uri, g_store_unreadable
                ? "the pin store could not be read" : "its line in the pin store is corrupt");
        rc = OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP;
    }
    if (rc != SUCCESS)
    {
        names_free(&files);
        return rc;
    }
    for (n = 0; n < files.n; n++)
        cap += strlen(files.name[n]) + PHD_SHA256_HEX_LEN + 2;
    words = calloc(1, cap);
    if (!words)
    {
        names_free(&files);
        return ERR_MEMORY_ALLOCATION;
    }
    for (n = 0; n < files.n && rc == SUCCESS; n++)
    {
        if (digest_of(root, files.name[n], hex) != 0)
            rc = pin_refuse(uri, files.name[n], "is missing or not a file");
        else
            sprintf(words + strlen(words), "%s%s" PHD_PIN_DIGEST_SEPARATOR "%s", n ? PHD_PIN_FILE_SEPARATOR : "",
                    files.name[n], hex);
    }
    if (rc == SUCCESS && pin_build(&pin, uri, words, PHD_PIN_LAYOUT_UNKNOWN, NULL, NULL, 1) != SUCCESS)
        rc = pin_refuse(uri, root, "can't be pinned");
    /* the line must fit what pin_set takes, with room for the layout and the verdict that are added later */
    if (rc == SUCCESS && line_size(&pin) + LINE_RESERVE > PHD_LINE_MAX)
    {
        pin_free(&pin);
        rc = pin_refuse(uri, root, "holds too many files for one pin line");
    }
    names_free(&files);
    free(words);
    if (rc != SUCCESS)
        return rc;
    pin.learned = 1;
    if (pin_put(&pin) != 0)
    {
        pin_free(&pin);
        return ERR_MEMORY_ALLOCATION;
    }
    store_save();
    return SUCCESS;
}

int pins_learn(const format_t *format, const char *uri, const char *search)
{
    return record(format, uri, search);
}

int pins_accept(const format_t *format, const char *uri, const char *search)
{
    const pin_t *p = find(bare(uri));
    int rc, chosen;

    if (!p)
        return OMX_REPLY_HOST_PIN_ABSENT_RESP;
    /* its qualification refused it: the user's choice, kept, and the files as they are now its pin with no verdict, so
     * it runs in a worker of its own like any plugin not qualified for a shared one */
    chosen = pkg_refused(bare(uri)) != NULL || refused(p);
    if (chosen && (!g_accepting || accepted_add(bare(uri)) != 0))
        return g_accepting ? ERR_MEMORY_ALLOCATION : OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP;
    rc = record(format, uri, search);
    if (chosen && rc != SUCCESS)
        accepted_drop(bare(uri));
    if (chosen)
    {
        accepted_save();
        if (rc == SUCCESS)
            fprintf(stderr, "plugin-hostd: %s: its pin carries " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED
                            "; the user chose to load it, alone in a worker of its own\n", uri);
    }
    return rc;
}

int pins_set_layout(const char *uri, const char *layout)
{
    char scheme[SCHEME_MAX], hex[PHD_SHA256_HEX_LEN + 1], *copy;
    pin_t *p = find(bare(uri));

    if (!p || phd_pin_layout_parse(layout, scheme, sizeof(scheme), hex) != 0 || strcmp(scheme, PHD_PIN_LAYOUT_SCHEME))
        return ERR_INVALID_OPERATION;
    copy = strdup(layout);
    if (!copy)
        return ERR_MEMORY_ALLOCATION;
    free(p->layout);
    p->layout = copy;
    snprintf(p->scheme, sizeof(p->scheme), "%s", scheme);
    if (p->learned)
        store_save();
    return SUCCESS;
}

int pins_check(const format_t *format, const char *uri, const char *search, const char **layout)
{
    const pin_t *p = find(bare(uri));
    char root[PATH_MAX];
    names_t files = { NULL, 0 };
    int n, rc;

    if (!p || (strcmp(p->layout, PHD_PIN_LAYOUT_UNKNOWN) && strcmp(p->scheme, PHD_PIN_LAYOUT_SCHEME)))
    {
        fprintf(stderr, "plugin-hostd: %s: %s\n", uri, p ? "its layout pin is in a scheme this version does not know"
                                                          : "no pin");
        return OMX_REPLY_HOST_PIN_ABSENT_RESP;
    }
    /* what the format says the host loads for the plugin, each held by the pin, then every file the pin holds hashed */
    rc = format->pin_collect(uri, search, root, sizeof(root), &files);
    for (n = 0; n < files.n && rc == SUCCESS; n++)
        if (held(p, files.name[n]) < 0)
            rc = pin_refuse(uri, files.name[n], "is named by the plugin and not held by the pin");
    names_free(&files);
    for (n = 0; n < p->nfiles && rc == SUCCESS; n++)
        rc = hash_file(root, p->path[n], p->digest[n], uri);
    /* the verdict is about these very files: only once they are the pinned ones does a refused one refuse the add */
    if (rc == SUCCESS && !strcmp(p->verdict, PHD_PIN_VERDICT_REFUSED) && !accepted(bare(uri)))
    {
        fprintf(stderr, "plugin-hostd: %s: its pin carries " PHD_PIN_VERDICT_KEY PHD_PIN_VERDICT_REFUSED "\n", uri);
        rc = OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP;
    }
    if (rc == SUCCESS)
        *layout = strcmp(p->layout, PHD_PIN_LAYOUT_UNKNOWN) ? p->layout : NULL;
    return rc;
}

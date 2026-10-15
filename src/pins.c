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

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include <host-errors.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "formats.h"
#include "pins.h"

#define SCHEME_MAX   32
#define STORE_NAME   "plugin-hostd/pins"
#define LINE_MAX_PIN (PHD_LINE_MAX * 2)

typedef struct PIN_T {
    char *uri;
    char **path;
    char (*digest)[PHD_SHA256_HEX_LEN + 1];
    int nfiles;
    char scheme[SCHEME_MAX];
    char *layout;
    char verdict[16];           /* one of PHD_PIN_VERDICTS, or empty */
    int learned;                /* the daemon recorded it: the store keeps it */
} pin_t;

static pin_t *g_pins;
static int g_npins;
static char g_store[PATH_MAX];

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

static pin_t *find(const char *uri)
{
    int n;

    for (n = 0; n < g_npins; n++)
        if (!strcmp(g_pins[n].uri, uri))
            return &g_pins[n];
    return NULL;
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

static int verdict_valid(const char *verdict)
{
    int ok = 0;

#define X(id, name, meaning) ok |= !strcmp(verdict, name);
    PHD_PIN_VERDICTS(X)
#undef X
    return ok;
}

/* a pin from its words; the pin is not in the table yet. `unknown_ok` lets the layout be PHD_PIN_LAYOUT_UNKNOWN */
static int pin_build(pin_t *pin, const char *uri, const char *files, const char *layout, const char *verdict,
                     int unknown_ok)
{
    char *copy = strdup(files), *item, *save = NULL, hex[PHD_SHA256_HEX_LEN + 1];

    memset(pin, 0, sizeof(*pin));
    if (unknown_ok && !strcmp(layout, PHD_PIN_LAYOUT_UNKNOWN))
        ;
    else if (phd_pin_layout_parse(layout, pin->scheme, sizeof(pin->scheme), hex) != 0)
        goto invalid;
    if (verdict && (!verdict_valid(verdict) || strlen(verdict) >= sizeof(pin->verdict)))
        goto invalid;
    for (item = strtok_r(copy, PHD_PIN_FILE_SEPARATOR, &save); item; item = strtok_r(NULL, PHD_PIN_FILE_SEPARATOR, &save))
    {
        char *eq = strrchr(item, PHD_PIN_DIGEST_SEPARATOR[0]);

        if (!eq)
            goto invalid;
        *eq = '\0';
        if (!path_valid(item) || !phd_pin_hex_valid(eq + 1) || held(pin, item) >= 0)
            goto invalid;
        pin->path = realloc(pin->path, (pin->nfiles + 1) * sizeof(char *));
        pin->digest = realloc(pin->digest, (pin->nfiles + 1) * sizeof(*pin->digest));
        pin->path[pin->nfiles] = strdup(item);
        memcpy(pin->digest[pin->nfiles], eq + 1, PHD_SHA256_HEX_LEN + 1);
        pin->nfiles++;
    }
    if (!pin->nfiles)
        goto invalid;
    free(copy);
    pin->uri = strdup(bare(uri));
    pin->layout = strdup(layout);
    if (verdict)
        snprintf(pin->verdict, sizeof(pin->verdict), "%s", verdict);
    return SUCCESS;

invalid:
    free(copy);
    pin_free(pin);
    return ERR_INVALID_OPERATION;
}

/* the pin in the table, replacing the one of its uri */
static void pin_put(pin_t *pin)
{
    pin_t *old = find(pin->uri);

    if (old)
    {
        pin_free(old);
        *old = *pin;
    }
    else
    {
        g_pins = realloc(g_pins, (g_npins + 1) * sizeof(pin_t));
        g_pins[g_npins++] = *pin;
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
    int n;

    fprintf(file, "%s %s ", PHD_VERB_PIN_SET, p->uri);
    for (n = 0; n < p->nfiles; n++)
        fprintf(file, "%s%s" PHD_PIN_DIGEST_SEPARATOR "%s", n ? PHD_PIN_FILE_SEPARATOR : "", p->path[n], p->digest[n]);
    fprintf(file, " %s", p->layout);
    if (*p->verdict)
        fprintf(file, " " PHD_PIN_VERDICT_KEY "%s", p->verdict);
    fprintf(file, "\n");
}

static int mkdir_parents(char *path)
{
    char *slash;

    for (slash = path + 1; (slash = strchr(slash, '/')); slash++)
    {
        *slash = '\0';
        if (mkdir(path, 0700) != 0 && errno != EEXIST)
        {
            *slash = '/';
            return -1;
        }
        *slash = '/';
    }
    return 0;
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
    char copy[LINE_MAX_PIN], *save = NULL, *t;

    snprintf(copy, sizeof(copy), "%s", line);
    t = strtok_r(copy, " \t", &save);
    if (t && !strcmp(t, PHD_VERB_PIN_SET))
        t = strtok_r(NULL, " \t", &save);
    return t && !strcmp(bare(t), uri);
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

static void sync_dir(const char *path)
{
    char dir[PATH_MAX + 8], *slash;
    int fd;

    snprintf(dir, sizeof(dir), "%s", path);
    slash = strrchr(dir, '/');
    if (!slash)
        snprintf(dir, sizeof(dir), ".");
    else if (slash == dir)
        dir[1] = '\0';
    else
        *slash = '\0';
    fd = open(dir, O_RDONLY | O_DIRECTORY);
    if (fd >= 0)
    {
        fsync(fd);
        close(fd);
    }
}

/* the pins the daemon learned, to the store: a temporary file of its own beside it (mkstemp, so two daemons on one
 * store never share a name), written, fsynced and renamed over it, then the directory fsynced. A failure is announced
 * on stderr, with what it costs, and leaves the pins in memory */
static void store_save(void)
{
    char tmp[PATH_MAX + 16];
    FILE *file;
    int n, fd, ok;

    if (!*g_store)
        return;
    if (g_store_unreadable)
    {
        fprintf(stderr, "plugin-hostd: the pin store %s could not be read: NOT overwriting it; the pins learned this run "
                        "are NOT persisted until the operator repairs it\n", g_store);
        return;
    }
    snprintf(tmp, sizeof(tmp), "%s.XXXXXX", g_store);
    if (mkdir_parents(tmp) != 0 || (fd = mkstemp(tmp)) < 0 || !(file = fdopen(fd, "w")))
    {
        fprintf(stderr, "plugin-hostd: can't write the pin store %s: %s; the pins learned this run are NOT persisted and "
                        "the next start learns them again\n", g_store, strerror(errno));
        return;
    }
    for (n = 0; n < g_nheld; n++)
        fprintf(file, "%s\n", g_held[n]);
    for (n = 0; n < g_npins; n++)
        if (g_pins[n].learned)
            line_write(file, &g_pins[n]);
    ok = fflush(file) == 0 && !ferror(file) && fsync(fileno(file)) == 0;
    ok = fclose(file) == 0 && ok;
    if (!ok || rename(tmp, g_store) != 0)
    {
        fprintf(stderr, "plugin-hostd: can't write the pin store %s: %s; the pins learned this run are NOT persisted and "
                        "the next start learns them again\n", g_store, strerror(errno));
        unlink(tmp);
        return;
    }
    sync_dir(g_store);
}

/* one line: the words of pin_set, the verb in front or not; a blank or comment line is SUCCESS and records nothing */
static int line_read(char *line, int learned)
{
    char *tok[8], *save = NULL, *t;
    int ntok = 0, first = 0, rc;
    pin_t pin;

    for (t = strtok_r(line, " \t\r\n", &save); t && ntok < 8; t = strtok_r(NULL, " \t\r\n", &save))
        tok[ntok++] = t;
    if (ntok == 0 || tok[0][0] == '#')
        return SUCCESS;
    if (!strcmp(tok[0], PHD_VERB_PIN_SET))
        first = 1;
    if (ntok - first != 3 && ntok - first != 4)
        return ERR_INVALID_OPERATION;
    if (ntok - first == 4 && strncmp(tok[first + 3], PHD_PIN_VERDICT_KEY, strlen(PHD_PIN_VERDICT_KEY)))
        return ERR_INVALID_OPERATION;
    rc = pin_build(&pin, tok[first], tok[first + 1], tok[first + 2],
                   ntok - first == 4 ? tok[first + 3] + strlen(PHD_PIN_VERDICT_KEY) : NULL, 1);
    if (rc != SUCCESS)
        return rc;
    pin.learned = learned;
    pin_put(&pin);
    return SUCCESS;
}

static int file_read(const char *path, int learned, int strict)
{
    char line[LINE_MAX_PIN];
    FILE *file = fopen(path, "r");
    int lineno = 0;

    if (!file)
    {
        if (strict)
            fprintf(stderr, "plugin-hostd: can't open the pin file %s: %s\n", path, strerror(errno));
        else if (errno != ENOENT && errno != ENOTDIR)
        {
            /* a store that exists and can't be opened is not a first run */
            fprintf(stderr, "plugin-hostd: can't read the pin store %s: %s; learning and saving are blocked until it "
                            "is repaired\n", path, strerror(errno));
            g_store_unreadable = 1;
        }
        return strict ? -1 : 0;
    }
    while (fgets(line, sizeof(line), file))
    {
        char original[LINE_MAX_PIN];

        lineno++;
        snprintf(original, sizeof(original), "%s", line);
        if (line_read(line, learned) != SUCCESS)
        {
            fprintf(stderr, "plugin-hostd: %s:%d: not a pin%s\n", path, lineno,
                    strict ? "" : "; the line is kept as it is and its plugin is not learned again until the operator "
                                  "repairs or removes it");
            if (strict)
            {
                fclose(file);
                return -1;
            }
            if (learned)
                held_add(original);
        }
    }
    if (ferror(file) && !strict)
    {
        fprintf(stderr, "plugin-hostd: can't read the pin store %s: %s; learning and saving are blocked until it is "
                        "repaired\n", path, strerror(errno));
        g_store_unreadable = 1;
    }
    fclose(file);
    return 0;
}

int pins_init(const char *store, const char *file)
{
    held_free();
    if (*store_path(store))
        file_read(g_store, 1, 0);
    return *file ? file_read(file, 0, 1) : 0;
}

int pins_set(const char *uri, const char *files, const char *layout, const char *verdict)
{
    pin_t pin;
    int rc = pin_build(&pin, uri, files, layout, verdict, 0);

    if (rc != SUCCESS)
        return rc;
    pin_put(&pin);
    return SUCCESS;
}

int pins_known(const char *uri)
{
    return find(bare(uri)) != NULL;
}

int pins_in_process(const char *uri)
{
    const pin_t *p = find(bare(uri));

    return p && !strcmp(p->verdict, PHD_PIN_VERDICT_IN_PROCESS);
}

int pins_clear(const char *uri)
{
    pin_t *p;
    int learned = 0;

    if (!strcmp(uri, PHD_WORD_ALL))
    {
        for (p = g_pins; p < g_pins + g_npins; p++)
            learned |= p->learned;
        pins_finish();
        if (learned)
            store_save();
        return SUCCESS;
    }
    p = find(bare(uri));
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
    while (g_npins)
        pin_free(&g_pins[--g_npins]);
    free(g_pins);
    g_pins = NULL;
}

/* ---------------------------------------------------------------- the check */

int pin_refuse(const char *uri, const char *path, const char *why)
{
    fprintf(stderr, "plugin-hostd: %s: %s %s\n", uri, path, why);
    return PHD_ERR_PIN_BINARY_MISMATCH;
}

/* the file of a pin hashed over one open descriptor */
static int hash_file(const char *root, const char *path, const char *want, const char *uri)
{
    char full[PATH_MAX * 2], hex[PHD_SHA256_HEX_LEN + 1];
    struct stat st;
    int fd, rc = SUCCESS;

    snprintf(full, sizeof(full), "%s/%s", root, path);
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

    snprintf(full, sizeof(full), "%s/%s", root, path);
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
        rc = PHD_ERR_PIN_BINARY_MISMATCH;
    }
    if (rc != SUCCESS)
    {
        names_free(&files);
        return rc;
    }
    for (n = 0; n < files.n; n++)
        cap += strlen(files.name[n]) + PHD_SHA256_HEX_LEN + 2;
    words = calloc(1, cap);
    for (n = 0; n < files.n && rc == SUCCESS; n++)
    {
        if (digest_of(root, files.name[n], hex) != 0)
            rc = pin_refuse(uri, files.name[n], "is missing or not a file");
        else
            sprintf(words + strlen(words), "%s%s" PHD_PIN_DIGEST_SEPARATOR "%s", n ? PHD_PIN_FILE_SEPARATOR : "",
                    files.name[n], hex);
    }
    if (rc == SUCCESS && pin_build(&pin, uri, words, PHD_PIN_LAYOUT_UNKNOWN, NULL, 1) != SUCCESS)
        rc = pin_refuse(uri, root, "can't be pinned");
    names_free(&files);
    free(words);
    if (rc != SUCCESS)
        return rc;
    pin.learned = 1;
    pin_put(&pin);
    store_save();
    return SUCCESS;
}

int pins_learn(const format_t *format, const char *uri, const char *search)
{
    return record(format, uri, search);
}

int pins_accept(const format_t *format, const char *uri, const char *search)
{
    if (!find(bare(uri)))
        return PHD_ERR_PIN_ABSENT;
    return record(format, uri, search);
}

int pins_set_layout(const char *uri, const char *layout)
{
    char scheme[SCHEME_MAX], hex[PHD_SHA256_HEX_LEN + 1];
    pin_t *p = find(bare(uri));

    if (!p || phd_pin_layout_parse(layout, scheme, sizeof(scheme), hex) != 0 || strcmp(scheme, PHD_PIN_LAYOUT_SCHEME))
        return ERR_INVALID_OPERATION;
    free(p->layout);
    p->layout = strdup(layout);
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
        return PHD_ERR_PIN_ABSENT;
    }
    /* what the format says the host loads for the plugin, each held by the pin, then every file the pin holds hashed */
    rc = format->pin_collect(uri, search, root, sizeof(root), &files);
    for (n = 0; n < files.n && rc == SUCCESS; n++)
        if (held(p, files.name[n]) < 0)
            rc = pin_refuse(uri, files.name[n], "is named by the plugin and not held by the pin");
    names_free(&files);
    for (n = 0; n < p->nfiles && rc == SUCCESS; n++)
        rc = hash_file(root, p->path[n], p->digest[n], uri);
    if (rc == SUCCESS)
        *layout = strcmp(p->layout, PHD_PIN_LAYOUT_UNKNOWN) ? p->layout : NULL;
    return rc;
}

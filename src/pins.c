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

#include "pins.h"
#include "proc.h"

#define SCHEME_MAX   32
#define MANIFEST     "manifest.ttl"
#define MANIFEST_MAX (4 * 1024 * 1024)
#define LV2_BINARY   "http://lv2plug.in/ns/lv2core#binary"
#define RDFS_SEEALSO "http://www.w3.org/2000/01/rdf-schema#seeAlso"
#define LV2_PREFIX   "lv2:"
#define CLAP_PREFIX  "clap:"

typedef struct PIN_T {
    char *uri;
    char **path;
    char (*digest)[PHD_SHA256_HEX_LEN + 1];
    int nfiles;
    char scheme[SCHEME_MAX];
    char *layout;
} pin_t;

static pin_t *g_pins;
static int g_npins;

static const char *bare(const char *uri)
{
    return strncmp(uri, LV2_PREFIX, strlen(LV2_PREFIX)) ? uri : uri + strlen(LV2_PREFIX);
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

int pins_set(const char *uri, const char *files, const char *layout)
{
    char *copy = strdup(files), *item, *save = NULL, hex[PHD_SHA256_HEX_LEN + 1];
    pin_t pin, *old;

    memset(&pin, 0, sizeof(pin));
    if (phd_pin_layout_parse(layout, pin.scheme, sizeof(pin.scheme), hex) != 0)
        goto invalid;
    for (item = strtok_r(copy, PHD_PIN_FILE_SEPARATOR, &save); item; item = strtok_r(NULL, PHD_PIN_FILE_SEPARATOR, &save))
    {
        char *eq = strrchr(item, PHD_PIN_DIGEST_SEPARATOR[0]);

        if (!eq)
            goto invalid;
        *eq = '\0';
        if (!path_valid(item) || !phd_pin_hex_valid(eq + 1) || held(&pin, item) >= 0)
            goto invalid;
        pin.path = realloc(pin.path, (pin.nfiles + 1) * sizeof(char *));
        pin.digest = realloc(pin.digest, (pin.nfiles + 1) * sizeof(*pin.digest));
        pin.path[pin.nfiles] = strdup(item);
        memcpy(pin.digest[pin.nfiles], eq + 1, PHD_SHA256_HEX_LEN + 1);
        pin.nfiles++;
    }
    if (!pin.nfiles)
        goto invalid;
    free(copy);
    pin.uri = strdup(bare(uri));
    pin.layout = strdup(layout);
    old = find(pin.uri);
    if (old)
    {
        pin_free(old);
        *old = pin;
    }
    else
    {
        g_pins = realloc(g_pins, (g_npins + 1) * sizeof(pin_t));
        g_pins[g_npins++] = pin;
    }
    return SUCCESS;

invalid:
    free(copy);
    pin_free(&pin);
    return ERR_INVALID_OPERATION;
}

int pins_clear(const char *uri)
{
    pin_t *p;

    if (!strcmp(uri, PHD_WORD_ALL))
    {
        pins_finish();
        return SUCCESS;
    }
    p = find(bare(uri));
    if (p)
    {
        pin_free(p);
        *p = g_pins[--g_npins];
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

/* ---------------------------------------------------------------- the manifest's files of a plugin */

/* Turtle as a manifest writes it, enough to find the objects of lv2:binary and rdfs:seeAlso whose subject is the
 * plugin: prefixes, IRIs, prefixed names, "a", literals skipped, nested [ ] and ( ) skipped. A name the pin cannot
 * hold (an absolute IRI outside the bundle, a relative one that climbs out of it, an @base) is kept as it is, and no
 * pinned path matches it. */

enum { T_END, T_IRI, T_NAME, T_PUNCT, T_LITERAL, T_DIRECTIVE };

typedef struct SCAN_T {
    const char *p, *end;
    char prefix[64][2][256];
    int nprefix;
    int based;
} scan_t;

typedef struct TOKEN_T {
    int kind;
    char text[PATH_MAX];
} token_t;

static void skip_space(scan_t *s)
{
    while (s->p < s->end)
    {
        if (*s->p == '#')
            while (s->p < s->end && *s->p != '\n')
                s->p++;
        else if (*s->p == ' ' || *s->p == '\t' || *s->p == '\n' || *s->p == '\r')
            s->p++;
        else
            return;
    }
}

static void skip_literal(scan_t *s)
{
    char q = *s->p;
    int triple = s->end - s->p >= 3 && s->p[1] == q && s->p[2] == q;

    s->p += triple ? 3 : 1;
    while (s->p < s->end)
    {
        if (*s->p == '\\')
            s->p += 2;
        else if (*s->p == q && (!triple || (s->end - s->p >= 3 && s->p[1] == q && s->p[2] == q)))
        {
            s->p += triple ? 3 : 1;
            break;
        }
        else
            s->p++;
    }
    if (s->p < s->end && *s->p == '@')
        while (s->p < s->end && *s->p != ' ' && *s->p != '\t' && *s->p != '\n' && !strchr(";,.])", *s->p))
            s->p++;
    else if (s->end - s->p >= 2 && s->p[0] == '^' && s->p[1] == '^')
        s->p += 2;
}

static void copy_text(token_t *t, const char *from, size_t n)
{
    if (n >= sizeof(t->text))
        n = sizeof(t->text) - 1;
    memcpy(t->text, from, n);
    t->text[n] = '\0';
}

static void next(scan_t *s, token_t *t)
{
    const char *start;

    skip_space(s);
    t->text[0] = '\0';
    if (s->p >= s->end)
    {
        t->kind = T_END;
        return;
    }
    start = s->p;
    if (*s->p == '<')
    {
        while (s->p < s->end && *s->p != '>')
            s->p++;
        copy_text(t, start + 1, s->p - start - 1);
        if (s->p < s->end)
            s->p++;
        t->kind = T_IRI;
        return;
    }
    if (*s->p == '"' || *s->p == '\'')
    {
        skip_literal(s);
        t->kind = T_LITERAL;
        return;
    }
    if (strchr(".;,[]()", *s->p))
    {
        copy_text(t, s->p++, 1);
        t->kind = T_PUNCT;
        return;
    }
    while (s->p < s->end && !strchr(" \t\r\n<>\"';,[]()#", *s->p))
        s->p++;
    /* a prefixed name never ends with '.': that one ends the statement */
    if (s->p > start + 1 && s->p[-1] == '.')
        s->p--;
    copy_text(t, start, s->p - start);
    t->kind = *start == '@' ? T_DIRECTIVE : T_NAME;
    if (!strcasecmp(t->text, "PREFIX") || !strcasecmp(t->text, "BASE"))
        t->kind = T_DIRECTIVE;
}

/* a prefixed name or "a" as a full IRI */
static void expand(scan_t *s, token_t *t)
{
    char *colon;
    int n;

    if (t->kind != T_NAME)
        return;
    if (!strcmp(t->text, "a"))
    {
        snprintf(t->text, sizeof(t->text), "http://www.w3.org/1999/02/22-rdf-syntax-ns#type");
        t->kind = T_IRI;
        return;
    }
    colon = strchr(t->text, ':');
    if (!colon)
        return;
    for (n = 0; n < s->nprefix; n++)
        if (strlen(s->prefix[n][0]) == (size_t)(colon - t->text) && !strncmp(s->prefix[n][0], t->text, colon - t->text))
        {
            char full[PATH_MAX];

            snprintf(full, sizeof(full), "%s%s", s->prefix[n][1], colon + 1);
            snprintf(t->text, sizeof(t->text), "%s", full);
            t->kind = T_IRI;
            return;
        }
}

static void directive(scan_t *s, token_t *t)
{
    int sparql = t->text[0] != '@';
    token_t name, iri;

    if (!strcasecmp(t->text + !sparql, "base"))
    {
        s->based = 1;
        next(s, &iri);
    }
    else
    {
        next(s, &name);
        next(s, &iri);
        if (name.kind == T_NAME && iri.kind == T_IRI && s->nprefix < 64 && name.text[0] &&
            name.text[strlen(name.text) - 1] == ':')
        {
            name.text[strlen(name.text) - 1] = '\0';
            snprintf(s->prefix[s->nprefix][0], sizeof(s->prefix[0][0]), "%s", name.text);
            snprintf(s->prefix[s->nprefix][1], sizeof(s->prefix[0][1]), "%s", iri.text);
            s->nprefix++;
        }
    }
    if (!sparql)
    {
        skip_space(s);
        if (s->p < s->end && *s->p == '.')
            s->p++;
    }
}

/* the object of lv2:binary or rdfs:seeAlso as a path in the bundle, or the IRI as written when it is not one */
static void bundle_path(const scan_t *s, const char *bundle, const char *iri, char *out, size_t size)
{
    char file[PATH_MAX + 8];

    snprintf(file, sizeof(file), "file://%s/", bundle);
    if (!strncmp(iri, file, strlen(file)))
        iri += strlen(file);
    else if (strchr(iri, ':') || s->based)
    {
        snprintf(out, size, "%s", iri);
        return;
    }
    while (!strncmp(iri, "./", 2))
        iri += 2;
    snprintf(out, size, "%s", iri);
}

typedef struct NAMES_T {
    char **name;
    int n;
} names_t;

static void names_add(names_t *names, const char *name)
{
    names->name = realloc(names->name, (names->n + 1) * sizeof(char *));
    names->name[names->n++] = strdup(name);
}

static void names_free(names_t *names)
{
    while (names->n)
        free(names->name[--names->n]);
    free(names->name);
}

enum { WANT_SUBJECT, WANT_PREDICATE, WANT_OBJECT, AFTER_OBJECT };

/* the files the manifest names with lv2:binary and rdfs:seeAlso for the plugin; whether it sets a base */
static int manifest_files(const char *text, size_t size, const char *bundle, const char *uri, names_t *names)
{
    scan_t *s = calloc(1, sizeof(scan_t));
    token_t t;
    int state = WANT_SUBJECT, ours = 0, depth = 0, pred = 0, based;

    s->p = text;
    s->end = text + size;
    for (next(s, &t); t.kind != T_END; next(s, &t))
    {
        if (t.kind == T_PUNCT && (t.text[0] == '[' || t.text[0] == '('))
        {
            if (depth++ == 0 && state == WANT_SUBJECT)
                ours = 0;
            continue;
        }
        if (t.kind == T_PUNCT && (t.text[0] == ']' || t.text[0] == ')'))
        {
            if (depth && --depth == 0)
                state = state == WANT_SUBJECT ? WANT_PREDICATE : AFTER_OBJECT;
            continue;
        }
        if (depth)
            continue;
        if (t.kind == T_DIRECTIVE && state == WANT_SUBJECT)
        {
            directive(s, &t);
            continue;
        }
        expand(s, &t);
        if (t.kind == T_PUNCT && t.text[0] == '.')
            state = WANT_SUBJECT;
        else if (t.kind == T_PUNCT && t.text[0] == ';')
            state = WANT_PREDICATE;
        else if (t.kind == T_PUNCT && t.text[0] == ',')
            state = WANT_OBJECT;
        else if (state == WANT_SUBJECT)
        {
            ours = t.kind == T_IRI && !strcmp(t.text, uri);
            state = WANT_PREDICATE;
        }
        else if (state == WANT_PREDICATE)
        {
            pred = t.kind == T_IRI && (!strcmp(t.text, LV2_BINARY) || !strcmp(t.text, RDFS_SEEALSO));
            state = WANT_OBJECT;
        }
        else if (state == WANT_OBJECT)
        {
            if (ours && pred)
            {
                char path[PATH_MAX];

                bundle_path(s, bundle, t.text, path, sizeof(path));
                names_add(names, path);
            }
            state = AFTER_OBJECT;
        }
    }
    based = s->based;
    free(s);
    return based;
}

/* ---------------------------------------------------------------- the check */

static int refuse(const char *uri, const char *path, const char *why)
{
    fprintf(stderr, "plugin-hostd: %s: %s %s\n", uri, path, why);
    return PHD_ERR_PIN_BINARY_MISMATCH;
}

/* the file of a pin hashed over one open descriptor; the manifest's bytes are kept for reading when asked */
static int hash_file(const char *root, const char *path, const char *want, const char *uri, char **bytes, size_t *size)
{
    char full[PATH_MAX * 2], hex[PHD_SHA256_HEX_LEN + 1];
    struct stat st;
    int fd, rc = SUCCESS;

    snprintf(full, sizeof(full), "%s/%s", root, path);
    fd = open(full, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return refuse(uri, path, "is missing");
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode))
        rc = refuse(uri, path, "is not a file");
    else if (bytes)
    {
        ssize_t got = 0, r;

        if (st.st_size > MANIFEST_MAX)
            rc = refuse(uri, path, "is too large to be a manifest");
        else
        {
            *bytes = malloc(st.st_size + 1);
            while (got < st.st_size && (r = read(fd, *bytes + got, st.st_size - got)) > 0)
                got += r;
            *size = got;
            phd_sha256_hex(*bytes, got, hex);
            if (got != st.st_size || strcmp(hex, want))
                rc = refuse(uri, path, "differs from its pin");
        }
    }
    else if (phd_pin_fd_digest(fd, hex) != 0 || strcmp(hex, want))
        rc = refuse(uri, path, "differs from its pin");
    close(fd);
    return rc;
}

int pins_check(int clap, const char *uri, const char *lv2_path, const char **layout)
{
    const pin_t *p = find(bare(uri));
    char root[PATH_MAX], *manifest = NULL, *bundle = NULL;
    size_t manifest_size = 0;
    int n, rc = SUCCESS, skip = -1;

    if (!p || strcmp(p->scheme, PHD_PIN_LAYOUT_SCHEME))
    {
        fprintf(stderr, "plugin-hostd: %s: %s\n", uri, p ? "its layout pin is in a scheme this version does not know"
                                                          : "no pin");
        return PHD_ERR_PIN_ABSENT;
    }
    if (clap)
    {
        const char *path = uri + strlen(CLAP_PREFIX), *hash = strrchr(path, '#'), *slash;
        size_t len = hash ? (size_t)(hash - path) : strlen(path);

        snprintf(root, sizeof(root), "%.*s", (int)len, path);
        slash = strrchr(root, '/');
        if (!slash)
            return refuse(uri, root, "is not a path");
        if (held(p, slash + 1) < 0)
            return refuse(uri, slash + 1, "is not held by the pin");
        root[slash - root] = '\0';
    }
    else
    {
        names_t names = { NULL, 0 };

        bundle = proc_find_lv2_bundle(lv2_path, bare(uri));
        if (!bundle)
            return refuse(uri, MANIFEST, "is in no bundle of lv2_path naming the plugin");
        snprintf(root, sizeof(root), "%s", bundle);
        free(bundle);
        skip = held(p, MANIFEST);
        if (skip < 0)
            return refuse(uri, MANIFEST, "is not held by the pin");
        rc = hash_file(root, MANIFEST, p->digest[skip], uri, &manifest, &manifest_size);
        if (rc == SUCCESS)
        {
            /* the host resolves a base and decodes a percent-encoded name; the daemon does neither, so it cannot
             * know the file the host would load */
            if (manifest_files(manifest, manifest_size, root, bare(uri), &names))
                rc = refuse(uri, MANIFEST, "sets a base the daemon does not resolve");
            for (n = 0; n < names.n && rc == SUCCESS; n++)
                if (strstr(names.name[n], PHD_PIN_PERCENT))
                    rc = refuse(uri, names.name[n], "is percent-encoded, which the daemon does not decode");
                else if (held(p, names.name[n]) < 0)
                    rc = refuse(uri, names.name[n], "is named by the manifest and not held by the pin");
        }
        names_free(&names);
        free(manifest);
        if (rc != SUCCESS)
            return rc;
    }
    for (n = 0; n < p->nfiles && rc == SUCCESS; n++)
        if (n != skip)
            rc = hash_file(root, p->path[n], p->digest[n], uri, NULL, NULL);
    if (rc == SUCCESS)
        *layout = p->layout;
    return rc;
}

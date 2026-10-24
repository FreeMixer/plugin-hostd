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


/* The LV2 format: how a bundle's files are found for a pin, how a worker's world is narrowed to one bundle, and what the
 * daemon answers for the instance verbs mod-host does not have. */

#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include <host-errors.h>
#include <mod-host.h>
#include <plugin-hostd/protocol.h>

#include "formats.h"
#include "pins.h"
#include "proc.h"
#include "supervisor.h"

#define MANIFEST     "manifest.ttl"
#define MANIFEST_MAX (4 * 1024 * 1024)
#define LV2_BINARY   "http://lv2plug.in/ns/lv2core#binary"
#define RDFS_SEEALSO "http://www.w3.org/2000/01/rdf-schema#seeAlso"
#define LV2_PREFIX   "lv2:"
#define LV2_BYPASS_SYMBOL ":bypass"

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

enum { WANT_SUBJECT, WANT_PREDICATE, WANT_OBJECT, AFTER_OBJECT };

/* the files the manifest names with lv2:binary and rdfs:seeAlso for the plugin, or with lv2:binary alone when
 * binary_only; whether it sets a base */
static int manifest_files(const char *text, size_t size, const char *bundle, const char *uri, names_t *names,
                          int binary_only)
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
            pred = t.kind == T_IRI && (!strcmp(t.text, LV2_BINARY) || (!binary_only && !strcmp(t.text, RDFS_SEEALSO)));
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


static int read_manifest(const char *root, char **bytes, size_t *size)
{
    char full[PATH_MAX * 2];
    struct stat st;
    ssize_t got = 0, r;
    int fd;

    snprintf(full, sizeof(full), "%s/" MANIFEST, root);
    fd = open(full, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size > MANIFEST_MAX)
    {
        close(fd);
        return -1;
    }
    *bytes = malloc(st.st_size + 1);
    while (got < st.st_size && (r = read(fd, *bytes + got, st.st_size - got)) > 0)
        got += r;
    close(fd);
    *size = got;
    return got == st.st_size ? 0 : -1;
}

/* the uri as the manifest names the plugin: without a prefix */
static const char *bare(const char *uri)
{
    return strncmp(uri, LV2_PREFIX, strlen(LV2_PREFIX)) ? uri : uri + strlen(LV2_PREFIX);
}

/* the bundle of lv2_path whose manifest names the plugin, and the manifest with the files it names for it */
int lv2_pin_collect(const char *uri, const char *search, char *root, size_t size, names_t *files)
{
    names_t names = { NULL, 0 };
    char *bundle = proc_find_lv2_bundle(search, bare(uri)), *manifest = NULL;
    size_t manifest_size = 0;
    int n, rc = SUCCESS;

    if (!bundle)
        return pin_refuse(uri, MANIFEST, "is in no bundle of lv2_path naming the plugin");
    snprintf(root, size, "%s", bundle);
    free(bundle);
    if (read_manifest(root, &manifest, &manifest_size) != 0)
        return pin_refuse(uri, MANIFEST, "can't be read as a manifest");
    /* the host resolves a base and decodes a percent-encoded name; the daemon does neither, so it cannot know the file
     * the host would load */
    if (manifest_files(manifest, manifest_size, root, bare(uri), &names, 0))
        rc = pin_refuse(uri, MANIFEST, "sets a base the daemon does not resolve");
    names_add(files, MANIFEST);
    for (n = 0; n < names.n && rc == SUCCESS; n++)
    {
        if (strstr(names.name[n], PHD_PIN_PERCENT))
            rc = pin_refuse(uri, names.name[n], "is percent-encoded, which the daemon does not decode");
        else if (!names_has(files, names.name[n]))
            names_add(files, names.name[n]);
    }
    names_free(&names);
    free(manifest);
    return rc;
}

/* the one lv2:binary the manifest of the plugin's bundle names for it */
int lv2_binary(const char *uri, const char *search, char *path, size_t size)
{
    names_t names = { NULL, 0 };
    char *bundle = proc_find_lv2_bundle(search, bare(uri)), *manifest = NULL;
    size_t manifest_size = 0;
    int rc = -1;

    if (!bundle)
        return -1;
    if (read_manifest(bundle, &manifest, &manifest_size) == 0 &&
        !manifest_files(manifest, manifest_size, bundle, bare(uri), &names, 1) && names.n == 1 &&
        !strstr(names.name[0], PHD_PIN_PERCENT))
    {
        snprintf(path, size, "%s/%s", bundle, names.name[0]);
        rc = 0;
    }
    names_free(&names);
    free(manifest);
    free(bundle);
    return rc;
}

/* an own LV2 worker sees a world of one bundle, a chain's worker the union of its members': a directory holding a link
 * to each bundle that names one of the URIs, once; NULL when a URI's bundle is not found */
char *lv2_narrow_world(const conf_t *conf, const char *dir, const char *const *uris, int n)
{
    char link_path[PATH_MAX];
    int k;

    mkdir(dir, 0755);
    for (k = 0; k < n; k++)
    {
        char *bundle = proc_find_lv2_bundle(conf->lv2_path, uris[k]), *base;
        int ok;

        if (!bundle)
            return NULL;
        base = strrchr(bundle, '/');
        snprintf(link_path, sizeof(link_path), "%s/%s", dir, base ? base + 1 : bundle);
        unlink(link_path);
        ok = symlink(bundle, link_path) == 0;
        free(bundle);
        if (!ok)
            return NULL;
    }
    return strdup(dir);
}

/* param_info of an LV2 instance: -103 for what is no parameter, asked of mod-host with its own param_get, and for the
 * host's bypass; -511 for a parameter, whose unit and scale the daemon does not hold */
char *lv2_param_info(int id, const char *symbol)
{
    char line[PATH_MAX], *reply;
    int code;

    if (!strcmp(symbol, LV2_BYPASS_SYMBOL))
        return sup_resp(ERR_HOST_INVALID_PARAM_SYMBOL);
    snprintf(line, sizeof(line), EFFECT_PARAM_GET, id, symbol);
    reply = sup_call(id, line);
    code = sup_reply_code(reply);
    free(reply);
    return sup_resp(code == ERR_HOST_INVALID_PARAM_SYMBOL ? ERR_HOST_INVALID_PARAM_SYMBOL : PHD_ERR_NO_PARAM_CONTRACT);
}

/* ---------------------------------------------------------------- which worker runs a plugin */

typedef struct PICK_T {
    char *uri;
    char worker[CONF_SIZE_word];
} pick_t;

static pick_t *g_pick;
static int g_npick;
static char **g_refused;
static int g_nrefused;

static int worker_is(const char *word)
{
    int ok = 0;

#define X(id, name, meaning) ok |= !strcmp(word, name);
    PHD_LV2_WORKERS(X)
#undef X
    return ok;
}

static const char *picked(const char *uri)
{
    int n;

    for (n = 0; n < g_npick; n++)
        if (!strcmp(g_pick[n].uri, uri))
            return g_pick[n].worker;
    return NULL;
}

static const char *worker_in_force(const conf_t *conf, const char *uri)
{
    const char *pick = picked(uri);

    return pick ? pick : conf->lv2_worker;
}

static int refused(const char *uri)
{
    int n;

    for (n = 0; n < g_nrefused; n++)
        if (!strcmp(g_refused[n], uri))
            return 1;
    return 0;
}

const char *lv2_route(const conf_t *conf, const char *uri)
{
    const char *worker = worker_in_force(conf, uri);

    if (!strcmp(worker, PHD_LV2_WORKER_CLAP_HOST))
        return PHD_FORMAT_LV2_CLAP;
    if (!strcmp(worker, PHD_LV2_WORKER_AUTO) && !refused(uri))
        return PHD_FORMAT_LV2_CLAP;
    return NULL;
}

int lv2_worker_is_auto(const conf_t *conf, const char *uri)
{
    return !strcmp(worker_in_force(conf, uri), PHD_LV2_WORKER_AUTO);
}

int lv2_refused_under_auto(const conf_t *conf, int format, const char *uri)
{
    return format == format_by_name(PHD_FORMAT_LV2) && lv2_worker_is_auto(conf, uri) && refused(uri);
}

int lv2_worker_pick(const char *uri, const char *worker)
{
    int n;

    if (strcmp(worker, PHD_WORD_NONE) && (!worker_is(worker) || strlen(worker) >= CONF_SIZE_word))
        return -1;
    for (n = 0; n < g_npick; n++)
        if (!strcmp(g_pick[n].uri, uri))
            break;
    if (!strcmp(worker, PHD_WORD_NONE))
    {
        if (n < g_npick)
        {
            free(g_pick[n].uri);
            g_pick[n] = g_pick[--g_npick];
        }
        return 0;
    }
    if (n == g_npick)
    {
        pick_t *grown = realloc(g_pick, (g_npick + 1) * sizeof(*g_pick));
        char *copy;

        /* no memory for one more: the table keeps what it holds and this override is refused */
        if (grown == NULL)
            return -1;
        g_pick = grown;
        copy = strdup(uri);
        if (copy == NULL)
            return -1;
        g_pick[n].uri = copy;
        g_npick++;
    }
    snprintf(g_pick[n].worker, sizeof(g_pick[n].worker), "%s", worker);
    return 0;
}

void lv2_adapter_refused(const char *uri)
{
    char **grown;
    char *copy;

    if (refused(uri))
        return;
    /* no memory for one more: the table keeps what it holds and this refusal is not remembered, so the adapter is asked again */
    grown = realloc(g_refused, (g_nrefused + 1) * sizeof(*g_refused));
    if (grown == NULL)
        return;
    g_refused = grown;
    copy = strdup(uri);
    if (copy != NULL)
        g_refused[g_nrefused++] = copy;
}

/* the adapter may be asked again: about `uri`, or about every plugin when it is NULL */
void lv2_refusals_forget(const char *uri)
{
    int n = 0;

    while (n < g_nrefused)
        if (!uri || !strcmp(g_refused[n], uri))
        {
            free(g_refused[n]);
            g_refused[n] = g_refused[--g_nrefused];
        }
        else
            n++;
}

/* the adapter answers its refusal "resp <code> <hosting code>": the word after the code, PHD_WORD_NONE when there is none */
void lv2_refusal_reason(const char *reply, char *buf, size_t size)
{
    const char *at = reply;
    size_t len;
    int word;

    snprintf(buf, size, "%s", PHD_WORD_NONE);
    for (word = 0; word < 2; word++)
    {
        at += strspn(at, " \t");
        at += strcspn(at, " \t\r\n");
    }
    at += strspn(at, " \t");
    len = strcspn(at, " \t\r\n");
    if (len > 0 && len < size)
        snprintf(buf, size, "%.*s", (int)len, at);
}

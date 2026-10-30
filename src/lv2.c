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
    int typed;                  /* the literal just read carries a ^^ datatype, whose name is the next token */
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

/* past the literal at s->p; *body and *len are its text between the quotes, escapes not undone */
static void skip_literal(scan_t *s, const char **body, size_t *len)
{
    char q = *s->p;
    int triple = s->end - s->p >= 3 && s->p[1] == q && s->p[2] == q;

    s->p += triple ? 3 : 1;
    *body = s->p;
    *len = 0;
    while (s->p < s->end)
    {
        if (*s->p == '\\')
            s->p += 2;
        else if (*s->p == q && (!triple || (s->end - s->p >= 3 && s->p[1] == q && s->p[2] == q)))
        {
            *len = s->p - *body;
            s->p += triple ? 3 : 1;
            break;
        }
        else
            s->p++;
    }
    if (s->p > s->end)
        s->p = s->end;
    if (s->p < s->end && *s->p == '@')
        while (s->p < s->end && *s->p != ' ' && *s->p != '\t' && *s->p != '\n' && !strchr(";,.])", *s->p))
            s->p++;
    else if (s->end - s->p >= 2 && s->p[0] == '^' && s->p[1] == '^')
    {
        s->p += 2;
        s->typed = 1;
    }
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
        const char *body;
        size_t len, used = 0;

        skip_literal(s, &body, &len);
        /* the text with its escapes undone */
        for (; len && used + 1 < sizeof(t->text); body++, len--)
        {
            char c = *body;

            if (c == '\\' && len > 1)
            {
                body++;
                len--;
                c = *body == 'n' ? '\n' : *body == 't' ? '\t' : *body;
            }
            t->text[used++] = c;
        }
        t->text[used] = '\0';
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

/* ---------------------------------------------------------------- the ports of a bundle */

/* What the bundle's Turtle says of a plugin's control ports: the statements of the manifest and of the files it names with
 * rdfs:seeAlso, as subject, predicate and object, read by the tokenizer above. A nested [ ] is a blank node of its own; a
 * ( ) list is skipped. A name is compared as written once its prefix is expanded, so `<#group>` in a port and in the
 * group's own statement are one node. */

#define NS_CORE   "http://lv2plug.in/ns/lv2core#"
#define NS_PPROPS "http://lv2plug.in/ns/ext/port-props#"
#define NS_UNITS  "http://lv2plug.in/ns/extensions/units#"
#define NS_PG     "http://lv2plug.in/ns/ext/port-groups#"
#define NS_RDFS   "http://www.w3.org/2000/01/rdf-schema#"
#define RDF_TYPE  "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
#define TRIPLES_MAX   200000
#define PARSE_DEPTH   16
#define PAGE_SLOTS    8
#define WORD_MAX      255

typedef struct TRIPLE_T {
    char *s, *p, *o;
    int literal;
} triple_t;

typedef struct GRAPH_T {
    triple_t *t;
    int n, cap, blank;
} graph_t;

static void graph_add(graph_t *g, const char *s, const char *p, const char *o, int literal)
{
    triple_t *grown;

    if (g->n >= TRIPLES_MAX)
        return;
    if (g->n == g->cap)
    {
        grown = realloc(g->t, (g->cap ? g->cap * 2 : 256) * sizeof(*g->t));
        if (grown == NULL)
            return;
        g->t = grown;
        g->cap = g->cap ? g->cap * 2 : 256;
    }
    g->t[g->n].s = strdup(s);
    g->t[g->n].p = strdup(p);
    g->t[g->n].o = strdup(o);
    g->t[g->n].literal = literal;
    g->n++;
}

static void graph_free(graph_t *g)
{
    int n;

    for (n = 0; n < g->n; n++)
    {
        free(g->t[n].s);
        free(g->t[n].p);
        free(g->t[n].o);
    }
    free(g->t);
    memset(g, 0, sizeof(*g));
}

static void parse_pol(scan_t *s, graph_t *g, const char *subject, int depth);

/* the list at the "(" just read, to its ")" */
static void skip_list(scan_t *s)
{
    token_t t;
    int open = 1;

    while (open && (next(s, &t), t.kind != T_END))
        if (t.kind == T_PUNCT && t.text[0] == '(')
            open++;
        else if (t.kind == T_PUNCT && t.text[0] == ')')
            open--;
}

static void parse_object(scan_t *s, graph_t *g, const char *subject, const char *predicate, token_t *t, int depth)
{
    if (t->kind == T_PUNCT && t->text[0] == '[')
    {
        char blank[32];

        snprintf(blank, sizeof(blank), "_:b%d", g->blank++);
        graph_add(g, subject, predicate, blank, 0);
        if (depth < PARSE_DEPTH)
            parse_pol(s, g, blank, depth + 1);
    }
    else if (t->kind == T_PUNCT && t->text[0] == '(')
        skip_list(s);
    else if (t->kind == T_LITERAL)
    {
        graph_add(g, subject, predicate, t->text, 1);
        if (s->typed)
        {
            token_t datatype;

            s->typed = 0;
            next(s, &datatype);
        }
    }
    else if (t->kind == T_IRI || t->kind == T_NAME)
        graph_add(g, subject, predicate, t->text, 0);
}

/* the predicates and objects of one subject, to the "." that ends the statement or the "]" that ends the blank node (a
 * token that is neither a predicate nor a ";" ends it) */
static void parse_pol(scan_t *s, graph_t *g, const char *subject, int depth)
{
    for (;;)
    {
        token_t predicate, object, after;

        next(s, &predicate);
        if (predicate.kind == T_END)
            return;
        if (predicate.kind == T_PUNCT && predicate.text[0] == ';')
            continue;
        if (predicate.kind != T_IRI && predicate.kind != T_NAME)
            return;
        expand(s, &predicate);
        for (;;)
        {
            next(s, &object);
            if (object.kind == T_END)
                return;
            expand(s, &object);
            parse_object(s, g, subject, predicate.text, &object, depth);
            next(s, &after);
            if (after.kind == T_PUNCT && after.text[0] == ',')
                continue;
            if (after.kind == T_PUNCT && after.text[0] == ';')
                break;
            return;
        }
    }
}

static void graph_parse(graph_t *g, const char *text, size_t size)
{
    scan_t *s = calloc(1, sizeof(scan_t));
    token_t t;

    if (s == NULL)
        return;
    s->p = text;
    s->end = text + size;
    for (next(s, &t); t.kind != T_END; next(s, &t))
    {
        if (t.kind == T_DIRECTIVE)
            directive(s, &t);
        else if (t.kind == T_PUNCT && t.text[0] == '[')
        {
            char blank[32];

            snprintf(blank, sizeof(blank), "_:b%d", g->blank++);
            parse_pol(s, g, blank, 1);
            parse_pol(s, g, blank, 1);
        }
        else if (t.kind == T_PUNCT && t.text[0] == '(')
            skip_list(s);
        else if (t.kind == T_IRI || t.kind == T_NAME)
        {
            expand(s, &t);
            parse_pol(s, g, t.text, 0);
        }
    }
    free(s);
}

static const char *first_object(const graph_t *g, const char *s, const char *p)
{
    int n;

    for (n = 0; n < g->n; n++)
        if (!strcmp(g->t[n].s, s) && !strcmp(g->t[n].p, p))
            return g->t[n].o;
    return NULL;
}

static int has_object(const graph_t *g, const char *s, const char *p, const char *o)
{
    int n;

    for (n = 0; n < g->n; n++)
        if (!strcmp(g->t[n].s, s) && !strcmp(g->t[n].p, p) && !strcmp(g->t[n].o, o))
            return 1;
    return 0;
}

static int has_property(const graph_t *g, const char *port, const char *iri)
{
    return has_object(g, port, NS_CORE "portProperty", iri);
}

/* a number the Turtle writes (the object of lv2:minimum and the like), 0 when it is none */
static int number(const char *text, double *out)
{
    char *end;

    if (text == NULL || !*text)
        return 0;
    *out = strtod(text, &end);
    return *end == '\0';
}

typedef struct PORT_T {
    char *symbol;
    char *name;
    char *group;                /* the group's node, NULL for a port in none */
    const char *unit;           /* the unit's word; NULL when the port names a unit with no word */
    int unit_named;             /* the port names a unit */
    long index;
    int input;
    int hidden;
    int integer, toggled, enumeration, logarithmic;
    int ranged;                 /* minimum and maximum are both given */
    double min, max, def;
} port_t;

typedef struct PORTS_T {
    graph_t g;
    port_t *port;
    int n;
} ports_t;

/* units: the words param_info answers, as data/formats/lv2.json maps them */
static const struct { const char *iri; const char *word; } g_unit[] = {
    { NS_UNITS "bpm", "bpm" },          { NS_UNITS "cent", "cents" },   { NS_UNITS "coef", "x" },
    { NS_UNITS "db", "dB" },            { NS_UNITS "degree", "deg" },   { NS_UNITS "frame", "frames" },
    { NS_UNITS "hz", "Hz" },            { NS_UNITS "midiNote", "midiNote" }, { NS_UNITS "min", "min" },
    { NS_UNITS "ms", "ms" },            { NS_UNITS "oct", "oct" },      { NS_UNITS "pc", "%" },
    { NS_UNITS "s", "s" },              { NS_UNITS "semitone12TET", "st" },
    { "urn:openmixer:unit#dBFS", "dBFS" }, { "urn:openmixer:unit#LUFS", "LUFS" },
};

static const char *unit_word(const char *iri)
{
    size_t n;

    for (n = 0; n < sizeof(g_unit) / sizeof(*g_unit); n++)
        if (!strcmp(iri, g_unit[n].iri))
            return g_unit[n].word;
    return NULL;
}

static void ports_free(ports_t *ports)
{
    int n;

    for (n = 0; n < ports->n; n++)
    {
        free(ports->port[n].symbol);
        free(ports->port[n].name);
        free(ports->port[n].group);
    }
    free(ports->port);
    graph_free(&ports->g);
    free(ports);
}

static int by_index(const void *a, const void *b)
{
    long x = ((const port_t *)a)->index, y = ((const port_t *)b)->index;

    return x < y ? -1 : x > y;
}

/* an LV2 symbol is a C identifier; one that is not, or is too long for a word, names no port */
static int symbol_valid(const char *symbol)
{
    size_t n;

    if (symbol == NULL || !*symbol || strlen(symbol) > WORD_MAX)
        return 0;
    for (n = 0; symbol[n]; n++)
        if (!((symbol[n] >= 'a' && symbol[n] <= 'z') || (symbol[n] >= 'A' && symbol[n] <= 'Z') || symbol[n] == '_' ||
              (n && symbol[n] >= '0' && symbol[n] <= '9')))
            return 0;
    return 1;
}

static void port_read(const graph_t *g, const char *node, port_t *p)
{
    const char *symbol = first_object(g, node, NS_CORE "symbol"), *name = first_object(g, node, NS_CORE "name");
    const char *group = first_object(g, node, NS_PG "group"), *unit = first_object(g, node, NS_UNITS "unit");
    double lo, hi, def, index = 0;

    memset(p, 0, sizeof(*p));
    p->symbol = strdup(symbol);
    p->name = strdup(name ? name : symbol);
    p->group = group ? strdup(group) : NULL;
    if (number(first_object(g, node, NS_CORE "index"), &index))
        p->index = (long)index;
    p->input = has_object(g, node, RDF_TYPE, NS_CORE "InputPort");
    p->integer = has_property(g, node, NS_CORE "integer");
    p->toggled = has_property(g, node, NS_CORE "toggled");
    p->enumeration = has_property(g, node, NS_CORE "enumeration");
    p->logarithmic = has_property(g, node, NS_PPROPS "logarithmic");
    p->hidden = has_property(g, node, NS_PPROPS "notOnGUI");
    p->unit_named = unit != NULL;
    p->unit = unit ? unit_word(unit) : NULL;
    p->min = p->max = p->def = 0;
    if (number(first_object(g, node, NS_CORE "minimum"), &lo) && number(first_object(g, node, NS_CORE "maximum"), &hi))
    {
        p->ranged = 1;
        p->min = lo;
        p->max = hi;
    }
    else if (p->toggled)
    {
        p->ranged = 1;
        p->max = 1;
    }
    p->def = number(first_object(g, node, NS_CORE "default"), &def) ? def : p->min;
}

/* the control ports of a bundle's plugin, by index: NULL when the plugin's files cannot be found or read, or when they
 * name no control port */
static ports_t *ports_load(const char *uri, const char *search)
{
    names_t names = { NULL, 0 };
    char *bundle = proc_find_lv2_bundle(search, bare(uri)), *manifest = NULL;
    size_t size = 0;
    ports_t *ports = NULL;
    int n, k, ok = 0;

    if (!bundle || read_manifest(bundle, &manifest, &size) != 0)
    {
        free(bundle);
        return NULL;
    }
    ports = calloc(1, sizeof(*ports));
    if (ports == NULL)
    {
        free(bundle);
        free(manifest);
        return NULL;
    }
    graph_parse(&ports->g, manifest, size);
    manifest_files(manifest, size, bundle, bare(uri), &names, 0);
    free(manifest);
    for (n = 0; n < names.n; n++)
    {
        size_t len = strlen(names.name[n]);
        char path[PATH_MAX * 2], *bytes;
        struct stat st;
        ssize_t got = 0, r;
        int fd;

        if (len < 5 || strcmp(names.name[n] + len - 4, ".ttl") || strstr(names.name[n], "..") || names.name[n][0] == '/' ||
            strchr(names.name[n], ':'))
            continue;
        snprintf(path, sizeof(path), "%s/%s", bundle, names.name[n]);
        fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0)
            continue;
        if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size > MANIFEST_MAX || !(bytes = malloc(st.st_size + 1)))
        {
            close(fd);
            continue;
        }
        while (got < st.st_size && (r = read(fd, bytes + got, st.st_size - got)) > 0)
            got += r;
        close(fd);
        graph_parse(&ports->g, bytes, got);
        free(bytes);
    }
    names_free(&names);
    free(bundle);
    for (k = 0; k < ports->g.n; k++)
    {
        const triple_t *t = &ports->g.t[k];
        port_t *grown;

        if (strcmp(t->s, bare(uri)) || strcmp(t->p, NS_CORE "port") || t->literal)
            continue;
        if (!symbol_valid(first_object(&ports->g, t->o, NS_CORE "symbol")) || !has_object(&ports->g, t->o, RDF_TYPE, NS_CORE "ControlPort"))
            continue;
        grown = realloc(ports->port, (ports->n + 1) * sizeof(*grown));
        if (grown == NULL)
            break;
        ports->port = grown;
        port_read(&ports->g, t->o, &ports->port[ports->n++]);
        ok = 1;
    }
    if (!ok)
    {
        ports_free(ports);
        return NULL;
    }
    qsort(ports->port, ports->n, sizeof(*ports->port), by_index);
    return ports;
}

static ports_t *ports_of_instance(int id)
{
    const char *uri = sup_instance_uri(id), *search = sup_instance_search(id);

    return uri && search ? ports_load(uri, search) : NULL;
}

static const port_t *port_named(const ports_t *ports, const char *symbol)
{
    int n;

    for (n = 0; n < ports->n; n++)
        if (!strcmp(ports->port[n].symbol, symbol))
            return &ports->port[n];
    return NULL;
}

/* a word of the reply: quoted, in the daemon's limit, with no control character */
static void quoted(char *out, size_t size, const char *text)
{
    size_t used = 0;

    if (size < 3)
        return;
    out[used++] = '"';
    for (; *text && used < size - 2 && used < WORD_MAX; text++)
    {
        unsigned char c = *text;

        if (c < 0x20 || c == 0x7f)
            c = ' ';
        if ((c == '"' || c == '\\') && used + 2 < size - 1)
            out[used++] = '\\';
        out[used++] = c;
    }
    out[used++] = '"';
    out[used] = '\0';
}

/* param_info of an LV2 instance, from the control ports of its bundle: the unit and scale its port states, the range and
 * default, and the port's symbol, which is stable across hosts. -103 for what is no control port, and for the host's
 * bypass; -511 for a port whose unit the daemon has no word for or whose range it does not state. A bundle that cannot be
 * read leaves the answer to mod-host's param_get: -103 for what is no parameter, -511 for a parameter. */
char *lv2_param_info(int id, const char *symbol)
{
    ports_t *ports;
    const port_t *p;
    char line[PATH_MAX], *reply, unit[WORD_MAX + 8];
    const char *scale;
    int code;

    if (!strcmp(symbol, LV2_BYPASS_SYMBOL))
        return sup_resp(ERR_HOST_INVALID_PARAM_SYMBOL);
    ports = ports_of_instance(id);
    if (ports != NULL)
    {
        p = port_named(ports, symbol);
        if (p == NULL)
            reply = sup_resp(ERR_HOST_INVALID_PARAM_SYMBOL);
        else if (!p->ranged || (p->unit_named && !p->unit))
            reply = sup_resp(OMX_REPLY_HOST_NO_PARAM_CONTRACT_RESP);
        else
        {
            scale = p->integer || p->toggled || p->enumeration ? "stepped" :
                    p->logarithmic && p->min > 0 && p->max > 0 ? "log" : "linear";
            quoted(unit, sizeof(unit), p->unit ? p->unit : "");
            reply = NULL;
            if (asprintf(&reply, "resp 0 %s %s %.9g %.9g %.9g %d %s", unit, scale, p->min, p->max, p->def,
                         !strcmp(scale, "stepped"), p->symbol) < 0)
                reply = NULL;
            if (reply == NULL)
                reply = sup_resp(OMX_REPLY_HOST_NO_PARAM_CONTRACT_RESP);
        }
        ports_free(ports);
        return reply;
    }
    snprintf(line, sizeof(line), EFFECT_PARAM_GET, id, symbol);
    reply = sup_call(id, line);
    code = sup_reply_code(reply);
    free(reply);
    return sup_resp(code == ERR_HOST_INVALID_PARAM_SYMBOL ? ERR_HOST_INVALID_PARAM_SYMBOL : OMX_REPLY_HOST_NO_PARAM_CONTRACT_RESP);
}

/* the pages of 8 a bundle's groups make: a pg:group gives its control inputs a page (a further page for each 8 past the
 * first, the group's name and the number), the ports in no group one named Controls, the pages in the order their group
 * first appears among the ports */
typedef struct PAGE_T {
    const char *group;          /* the group's node, NULL for the ports in none */
    int chunk;                  /* 0 for the first page of the group */
    int slot[PAGE_SLOTS];       /* indexes into ports->port, -1 for an empty slot */
} page_t;

static int group_eq(const char *a, const char *b)
{
    return (a == NULL && b == NULL) || (a != NULL && b != NULL && !strcmp(a, b));
}

static page_t *pages_of(const ports_t *ports, int *count)
{
    page_t *page = NULL;
    int n, k, m, pages = 0;

    *count = 0;
    for (n = 0; n < ports->n; n++)
    {
        const port_t *p = &ports->port[n];
        int seen = 0, taken = 0;

        if (!p->input || p->hidden)
            continue;
        for (k = 0; k < n && !seen; k++)
            seen = ports->port[k].input && !ports->port[k].hidden && group_eq(ports->port[k].group, p->group);
        if (seen)
            continue;
        for (k = 0; k < ports->n; k++)
        {
            const port_t *q = &ports->port[k];
            page_t *grown;

            if (!q->input || q->hidden || !group_eq(q->group, p->group))
                continue;
            if (taken % PAGE_SLOTS == 0)
            {
                grown = realloc(page, (pages + 1) * sizeof(*page));
                if (grown == NULL)
                {
                    free(page);
                    return NULL;
                }
                page = grown;
                page[pages].group = p->group;
                page[pages].chunk = taken / PAGE_SLOTS;
                for (m = 0; m < PAGE_SLOTS; m++)
                    page[pages].slot[m] = -1;
                pages++;
            }
            page[pages - 1].slot[taken % PAGE_SLOTS] = k;
            taken++;
        }
    }
    *count = pages;
    return page;
}

/* remote_pages of an LV2 instance: the pages its bundle's groups make; 0 for a bundle that cannot be read */
char *lv2_remote_pages(int id)
{
    ports_t *ports = ports_of_instance(id);
    page_t *page;
    char *reply = NULL;
    int count = 0;

    if (ports == NULL)
        return sup_resp(0);
    page = pages_of(ports, &count);
    free(page);
    ports_free(ports);
    if (asprintf(&reply, "resp %d", count) < 0)
        return sup_resp(0);
    return reply;
}

/* remote_page_get of an LV2 instance: -902 for a page that is not one */
char *lv2_remote_page_get(int id, int index)
{
    ports_t *ports = ports_of_instance(id);
    page_t *page;
    char name[WORD_MAX + 8], label[WORD_MAX + 16], slots[PAGE_SLOTS * (WORD_MAX + 1) + 1] = "", *reply = NULL;
    const char *title;
    int count = 0, k;

    if (ports == NULL)
        return sup_resp(ERR_INVALID_OPERATION);
    page = pages_of(ports, &count);
    if (page == NULL || index < 0 || index >= count)
    {
        free(page);
        ports_free(ports);
        return sup_resp(ERR_INVALID_OPERATION);
    }
    title = page[index].group ? first_object(&ports->g, page[index].group, NS_CORE "name") : NULL;
    if (page[index].group && !title)
        title = first_object(&ports->g, page[index].group, NS_RDFS "label");
    if (page[index].group && !title)
        title = first_object(&ports->g, page[index].group, NS_CORE "symbol");
    if (!title)
        title = page[index].group ? page[index].group : "Controls";
    if (page[index].chunk)
        snprintf(label, sizeof(label), "%s %d", title, page[index].chunk + 1);
    else
        snprintf(label, sizeof(label), "%s", title);
    quoted(name, sizeof(name), label);
    for (k = 0; k < PAGE_SLOTS; k++)
    {
        strcat(slots, k ? " " : "");
        strcat(slots, page[index].slot[k] < 0 ? "-" : ports->port[page[index].slot[k]].symbol);
    }
    if (asprintf(&reply, "resp 0 %d \"\" %s %s", index, name, slots) < 0)
        reply = sup_resp(ERR_INVALID_OPERATION);
    free(page);
    ports_free(ports);
    return reply;
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

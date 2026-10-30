/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* A field dump through a format table (describe.h, docs/formats.md). The table says what each field becomes; what is
 * left here is the shape of a descriptor: which scope is a control or a port, the LV2 channels gathered into ports, and
 * the defaults docs/formats.md#the-descriptor-describe-writes names. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "describe.h"
#include "transforms.h"

/* a literal into a string that grows */
#define SBL(b, lit) sb_put(b, lit, sizeof(lit) - 1)

#define DUMP_VERSION_LINE "# omx-clap-scan --fields 1"
#define SCHEMA_URL "https://github.com/FreeMixer/omx-contract/raw/v3/schema/omx-contract.schema.json"
#define SCHEMA_FLOOR ">= 3.0.0"

static char *g_why;
static size_t g_why_size;

static int refuse(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static int refuse(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(g_why, g_why_size, fmt, ap);
    va_end(ap);
    return -1;
}

/* ---------------------------------------------------------------- the words describe writes */

typedef enum { W_STR, W_NUM, W_BOOL, W_HANDLE, W_LIST, W_POINTS, W_GROUP } wtype_t;

static const struct
{
    const char *word;
    wtype_t type;
} WORDS[] = {
    { "plugin.id", W_STR }, { "plugin.name", W_STR }, { "plugin.vendor", W_STR }, { "plugin.version", W_STR },
    { "plugin.doc", W_STR }, { "plugin.features", W_LIST },
    { "controls[].id", W_HANDLE }, { "controls[].name", W_STR }, { "controls[].kind", W_STR },
    { "controls[].travel.min", W_NUM }, { "controls[].travel.max", W_NUM }, { "controls[].travel.default", W_NUM },
    { "controls[].travel.unit", W_STR }, { "controls[].travel.scale", W_STR }, { "controls[].group", W_GROUP },
    { "controls[].labels", W_POINTS }, { "controls[].meaning", W_STR }, { "controls[].hidden", W_BOOL },
    { "controls[].readonly", W_BOOL }, { "controls[].automatable", W_BOOL },
    { "ports[].id", W_HANDLE }, { "ports[].name", W_STR }, { "ports[].kind", W_STR }, { "ports[].direction", W_STR },
    { "ports[].role", W_STR }, { "ports[].channels", W_NUM }, { "ports[].layout", W_STR }, { "ports[].dialects", W_LIST },
    { "needs.transport", W_BOOL }, { "needs.tempo", W_BOOL }, { "needs.extensions.required", W_LIST },
    { "needs.extensions.optional", W_LIST }, { "latency.reports", W_BOOL }, { "instrument.voices", W_NUM },
    { "source.from", W_STR },
};

static int word_index(const char *word)
{
    size_t i;

    for (i = 0; i < sizeof(WORDS) / sizeof(WORDS[0]); i++)
        if (!strcmp(WORDS[i].word, word))
            return (int)i;
    return -1;
}

/* ---------------------------------------------------------------- the table */

enum { C_WORD, C_EXTENSION, C_DROPPED };

typedef struct
{
    const char *key;
    int cls;
    int word; /* WORDS index */
    const transforms_entry_t *t;
    transforms_data_t d;
} row_t;

typedef struct
{
    const char *format;
    row_t *rows;
    size_t n;
} table_t;

/* a JSON value as the literal a transform reads and writes */
static char *literal(const jnode_t *v)
{
    sb_t b = { 0 };

    if (v->type == J_STR)
        sb_str(&b, v->str);
    else if (v->type == J_BOOL)
        sb_printf(&b, "%s", v->boolean ? "true" : "false");
    else if (v->type == J_NUM)
    {
        int prec;
        char tmp[40];

        for (prec = 15; prec <= 17; prec++)
        {
            snprintf(tmp, sizeof(tmp), "%.*g", prec, v->num);
            if (strtod(tmp, NULL) == v->num)
                break;
        }
        sb_printf(&b, "%s", tmp);
    }
    else
        return NULL;
    return b.s;
}

static int load_table(const char *text, table_t *t)
{
    jnode_t *doc = jparse(text), *item = NULL, *rows;
    size_t i, k;

    if (doc == NULL || doc->type != J_OBJ)
        return refuse("the table is not one JSON object");
    for (i = 0; i < doc->n && item == NULL; i++)
        if (doc->kid[i]->type == J_OBJ && jstr(doc->kid[i], "kind") && !strcmp(jstr(doc->kid[i], "kind"), "formatMap"))
            item = doc->kid[i];
    if (item == NULL || (rows = jget(item, "rows")) == NULL || rows->type != J_OBJ)
        return refuse("the table holds no formatMap item with rows");
    t->format = jstr(item, "format");
    if (t->format == NULL || (strcmp(t->format, "clap") && strcmp(t->format, "lv2")))
        return refuse("the table's format is neither clap nor lv2");
    t->rows = calloc(rows->n, sizeof(row_t));
    t->n = rows->n;
    for (i = 0; i < rows->n; i++)
    {
        row_t *r = &t->rows[i];
        const jnode_t *row = rows->kid[i], *w = jget(row, "word");

        r->key = rows->key[i];
        if (w != NULL)
        {
            const char *word = jstr(w, "word"), *tr = jstr(w, "transform");
            const jnode_t *values = jget(w, "values");
            double factor;

            r->cls = C_WORD;
            if (word == NULL || (r->word = word_index(word)) < 0)
                return refuse("row %s: describe writes no word %s", r->key, word ? word : "(none)");
            if (tr == NULL || (r->t = transforms_find(tr)) == NULL)
                return refuse("row %s: transform %s is not in TRANSFORMS(X)", r->key, tr ? tr : "(none)");
            r->d.key = r->key;
            if (jnum(w, "factor", &factor))
                r->d.factor = factor;
            if (values != NULL && values->type == J_OBJ)
            {
                const char **from = calloc(values->n, sizeof(char *)), **to = calloc(values->n, sizeof(char *));

                for (k = 0; k < values->n; k++)
                {
                    from[k] = values->key[k];
                    if ((to[k] = literal(values->kid[k])) == NULL)
                        return refuse("row %s: a lookup value is no string, number or boolean", r->key);
                }
                r->d.from = from, r->d.to = to, r->d.n = values->n;
                if (transforms_lookup_check(&r->d) != 0)
                    return refuse("row %s: a lookup whose values are not one to one", r->key);
            }
            else if (!strcmp(tr, "lookup"))
                return refuse("row %s: a lookup with no values", r->key);
        }
        else if (jget(row, "extension") != NULL)
            r->cls = C_EXTENSION;
        else if (jget(row, "dropped") != NULL)
            r->cls = C_DROPPED;
        else
            return refuse("row %s: no class", r->key);
    }
    return 0;
}

static const row_t *find_row(const table_t *t, const char *key)
{
    size_t i;

    for (i = 0; i < t->n; i++)
        if (!strcmp(t->rows[i].key, key))
            return &t->rows[i];
    return NULL;
}

/* ---------------------------------------------------------------- what the dump says, per scope */

typedef struct
{
    int word;
    char *value; /* a JSON literal */
} assign_t;

typedef struct
{
    char scope[48];
    char kind; /* 'g' the descriptor, 'p' a CLAP param, 'i' 'o' CLAP audio in/out, 'n' 'N' note in/out, 'l' an LV2 port */
    long index;
    assign_t *a;
    size_t n, cap;
    int latency; /* a record of this scope set latency.reports */
} entry_t;

typedef struct
{
    char *key;
    char **v;
    size_t n;
} bag_t;

typedef struct
{
    entry_t *e;
    size_t n;
    bag_t *bag;
    size_t nbag;
} scan_t;

static entry_t *entry(scan_t *s, const char *scope, char kind, long index)
{
    size_t i;

    for (i = 0; i < s->n; i++)
        if (!strcmp(s->e[i].scope, scope))
            return &s->e[i];
    s->e = realloc(s->e, (s->n + 1) * sizeof(entry_t));
    memset(&s->e[s->n], 0, sizeof(entry_t));
    snprintf(s->e[s->n].scope, sizeof(s->e[s->n].scope), "%s", scope);
    s->e[s->n].kind = kind;
    s->e[s->n].index = index;
    return &s->e[s->n++];
}

static void assign(entry_t *e, int word, const char *value)
{
    if (e->n == e->cap)
    {
        e->cap = e->cap ? e->cap * 2 : 8;
        e->a = realloc(e->a, e->cap * sizeof(assign_t));
    }
    e->a[e->n].word = word;
    e->a[e->n++].value = strdup(value);
}

/* the last value of a word, or NULL */
static const char *get(const entry_t *e, const char *word)
{
    int w = word_index(word);
    size_t i;

    for (i = e->n; i-- > 0;)
        if (e->a[i].word == w)
            return e->a[i].value;
    return NULL;
}

static void carry(scan_t *s, const char *scope, const char *field, const char *value)
{
    char key[256];
    size_t i;
    bag_t *b = NULL;

    if (!strcmp(scope, "plugin"))
        snprintf(key, sizeof(key), "%s", field);
    else
        snprintf(key, sizeof(key), "%s/%s", scope, field);
    for (i = 0; i < s->nbag && b == NULL; i++)
        if (!strcmp(s->bag[i].key, key))
            b = &s->bag[i];
    if (b == NULL)
    {
        s->bag = realloc(s->bag, (s->nbag + 1) * sizeof(bag_t));
        b = &s->bag[s->nbag++];
        memset(b, 0, sizeof(*b));
        b->key = strdup(key);
    }
    b->v = realloc(b->v, (b->n + 1) * sizeof(char *));
    b->v[b->n++] = strdup(value);
}

/* a literal checked against its word's type, a number made a string where the word is one; NULL when it does not fit */
static char *typed(int word, const char *v)
{
    sb_t b = { 0 };
    int str = v[0] == '"', num = !str && v[0] != 't' && v[0] != 'f' && v[0] != '[';

    switch (WORDS[word].type)
    {
    case W_STR:
    case W_LIST:
        if (num)
        {
            sb_str(&b, v);
            return b.s;
        }
        return str ? strdup(v) : NULL;
    case W_NUM: return num ? strdup(v) : NULL;
    case W_BOOL: return !strcmp(v, "true") || !strcmp(v, "false") ? strdup(v) : NULL;
    case W_HANDLE: return str || num ? strdup(v) : NULL;
    case W_POINTS:
    case W_GROUP: return v[0] == '[' ? strdup(v) : NULL;
    }
    return NULL;
}

static int apply(scan_t *s, entry_t *e, const row_t *r, const char *field, const char *value)
{
    char out[4096], *v;
    int rc = r->t->inbound(&r->d, value, out, sizeof(out));
    entry_t *to = e;

    if (rc == TRANSFORMS_REFUSED)
        return refuse("%s %s %s: %s refuses the value", e->scope, field, value, r->t->name);
    if (rc == TRANSFORMS_NONE)
    {
        carry(s, e->scope, field, value);
        return 0;
    }
    if ((v = typed(r->word, out)) == NULL)
        return refuse("%s %s %s: %s gives %s, which %s does not take", e->scope, field, value, r->t->name, out,
                      WORDS[r->word].word);
    if (strncmp(WORDS[r->word].word, "controls[]", 10) && strncmp(WORDS[r->word].word, "ports[]", 7))
    {
        to = &s->e[0];
        if (!strcmp(WORDS[r->word].word, "latency.reports"))
            e->latency = 1;
    }
    else if (e->kind == 'g')
        return refuse("%s %s: %s is a control's or a port's word, and the scope is the plugin", e->scope, field,
                      WORDS[r->word].word);
    if (!strcmp(r->key, "pg:subGroupOf"))
    {
        /* one level above the group read so far: the path is read outermost first */
        const char *below = get(e, "controls[].group");
        sb_t b = { 0 };

        if (below == NULL || below[0] != '[' || v[0] != '[')
            return refuse("%s %s %s: a pg:subGroupOf with no pg:group before it", e->scope, field, value);
        sb_printf(&b, "[%.*s, %s", (int)strlen(v) - 2, v + 1, below + 1);
        free(v);
        v = b.s;
    }
    assign(to, r->word, v);
    free(v);
    return 0;
}

/* one record: its value's row when that row is a word or a drop, else its field's row (docs/formats.md) */
static int record(scan_t *s, const table_t *t, entry_t *e, const char *field, const char *value)
{
    const row_t *vr = find_row(t, value), *fr;

    if (vr != NULL && vr->cls == C_WORD)
        return apply(s, e, vr, field, value);
    if (vr != NULL && vr->cls == C_DROPPED)
        return 0;
    if ((fr = find_row(t, field)) == NULL)
        return refuse("%s %s: the field has no row in the %s table", e->scope, field, t->format);
    if (fr->cls == C_WORD)
        return apply(s, e, fr, field, value);
    if (fr->cls == C_EXTENSION)
        carry(s, e->scope, field, value);
    return 0;
}

static int parse_scope(const char *format, const char *scope, char *kind, long *index)
{
    static const struct
    {
        const char *name;
        char kind;
        const char *format;
    } SCOPES[] = { { "param", 'p', "clap" },    { "audio_in", 'i', "clap" }, { "audio_out", 'o', "clap" },
                   { "note_in", 'n', "clap" },  { "note_out", 'N', "clap" }, { "port", 'l', "lv2" },
                   { "section", 'd', "clap" },  { "control", 'd', "clap" },  { "role", 'd', "clap" },
                   { "display", 'd', "clap" },  { "placement_default", 'd', "clap" } };
    const char *colon = strchr(scope, ':');
    size_t i;
    char *end;

    if (!strcmp(scope, "plugin"))
    {
        *kind = 'g', *index = -1;
        return 0;
    }
    if (!strcmp(scope, "panel") && !strcmp(format, "clap"))
    {
        *kind = 'd', *index = -1;
        return 0;
    }
    if (colon == NULL)
        return -1;
    for (i = 0; i < sizeof(SCOPES) / sizeof(SCOPES[0]); i++)
        if (strlen(SCOPES[i].name) == (size_t)(colon - scope) && !strncmp(scope, SCOPES[i].name, (size_t)(colon - scope))
            && !strcmp(SCOPES[i].format, format))
        {
            *index = strtol(colon + 1, &end, 10);
            if (end == colon + 1 || *end || *index < 0)
                return -1;
            *kind = SCOPES[i].kind;
            return 0;
        }
    return -1;
}

static int read_dump(const table_t *t, const char *text, scan_t *s)
{
    char *copy = strdup(text), *line, *save = NULL;
    int n = 0;

    entry(s, "descriptor", 'g', -1);
    for (line = strtok_r(copy, "\n", &save); line; line = strtok_r(NULL, "\n", &save))
    {
        char *scope = line, *field, *value, kind;
        long index;
        size_t len = strlen(line);

        if (len && line[len - 1] == '\r')
            line[len - 1] = '\0';
        if (n++ == 0)
        {
            if (strcmp(line, DUMP_VERSION_LINE))
                return refuse("the dump does not start with '%s'", DUMP_VERSION_LINE);
            continue;
        }
        if (*line == '\0')
            continue;
        if ((field = strchr(scope, '\t')) == NULL || (value = strchr(field + 1, '\t')) == NULL)
            return refuse("dump line %d is not <scope> TAB <field> TAB <value>", n);
        *field++ = '\0';
        *value++ = '\0';
        if (parse_scope(t->format, scope, &kind, &index) != 0)
            return refuse("dump line %d: %s is no %s scope", n, scope, t->format);
        /* the panel description: a scope of no entry, each field's row a drop (docs/formats.md#what-a-table-drops) */
        if (kind == 'd')
        {
            const row_t *r = find_row(t, field);

            if (r == NULL)
                return refuse("%s %s: the field has no row in the %s table", scope, field, t->format);
            if (r->cls != C_DROPPED)
                return refuse("%s %s: a field of the panel description is dropped, never a word or the bag", scope, field);
            continue;
        }
        if (record(s, t, kind == 'g' ? entry(s, "plugin", 'g', -1) : entry(s, scope, kind, index), field, value))
            return -1;
    }
    if (n == 0)
        return refuse("the dump is empty");
    return 0;
}

/* ---------------------------------------------------------------- the descriptor */

static int lit_true(const char *v)
{
    return v && !strcmp(v, "true");
}

static void put_list(sb_t *b, const entry_t *e, const char *word)
{
    int w = word_index(word), k = 0;
    size_t i, j;

    SBL(b, "[");
    for (i = 0; i < e->n; i++)
    {
        int seen = 0;

        if (e->a[i].word != w)
            continue;
        for (j = 0; j < i; j++)
            seen |= e->a[j].word == w && !strcmp(e->a[j].value, e->a[i].value);
        if (seen)
            continue;
        sb_printf(b, "%s%s", k++ ? ", " : "", e->a[i].value);
    }
    SBL(b, "]");
}

static int has_list(const entry_t *e, const char *word)
{
    return get(e, word) != NULL;
}

static int list_has(const entry_t *e, const char *word, const char *lit)
{
    int w = word_index(word);
    size_t i;

    for (i = 0; i < e->n; i++)
        if (e->a[i].word == w && !strcmp(e->a[i].value, lit))
            return 1;
    return 0;
}

/* a link, <path>#<symbol>: the path of a string literal with each character a link cannot hold made _ and no empty
 * segment, and the symbol */
static void put_link(sb_t *b, const char *path_lit, const char *symbol)
{
    jnode_t *v = jparse(path_lit);
    const char *p = v && v->type == J_STR ? v->str : "";
    int seg = 0, any = 0;

    SBL(b, "\"");
    for (; *p; p++)
    {
        if (*p == '/')
        {
            seg = 0;
            continue;
        }
        if (!seg && any)
            SBL(b, "/");
        seg = any = 1;
        sb_put(b, isalnum((unsigned char)*p) || strchr("_+.-", *p) ? p : "_", 1);
    }
    if (!any)
        SBL(b, "plugin");
    sb_printf(b, "#%s\"", symbol);
}

typedef struct
{
    double v;
    char *label;
} point_t;

static int by_value(const void *a, const void *b)
{
    double x = ((const point_t *)a)->v, y = ((const point_t *)b)->v;

    return x < y ? -1 : x > y;
}

static int by_index(const void *a, const void *b)
{
    long x = (*(entry_t *const *)a)->index, y = (*(entry_t *const *)b)->index;

    return x < y ? -1 : x > y;
}

static int put_control(sb_t *b, const entry_t *e, const char *format, const char *from, int first)
{
    const char *id = get(e, "controls[].id"), *name = get(e, "controls[].name"), *kind = get(e, "controls[].kind");
    const char *def = get(e, "controls[].travel.default"), *min = get(e, "controls[].travel.min");
    const char *max = get(e, "controls[].travel.max"), *v;
    int w = word_index("controls[].labels");
    point_t pts[256];
    size_t np = 0, i;

    if (id == NULL)
        return refuse("%s states no id", e->scope);
    for (i = 0; i < e->n && np < 256; i++)
        if (e->a[i].word == w)
        {
            jnode_t *p = jparse(e->a[i].value);

            if (p && p->type == J_ARR && p->n == 2 && p->kid[0]->type == J_NUM && p->kid[1]->type == J_STR)
                pts[np].v = p->kid[0]->num, pts[np++].label = p->kid[1]->str;
        }
    if (np)
        kind = "\"choice\"";
    if (kind == NULL)
        kind = "\"travel\"";
    sb_printf(b, "%s\n    {\"id\": %s, \"name\": ", first ? "" : ",", id);
    if (name)
        sb_printf(b, "%s", name);
    else if (id[0] == '"')
        sb_printf(b, "%s", id);
    else
        sb_printf(b, "\"%s\"", id);
    sb_printf(b, ", \"kind\": %s", kind);
    if (!strcmp(kind, "\"choice\""))
    {
        char ids[256][64];
        double dv = def ? strtod(def, NULL) : pts[0].v;
        size_t j, d = 0;

        if (np == 0)
            return refuse("%s is a choice with no points", e->scope);
        qsort(pts, np, sizeof(point_t), by_value);
        for (i = 0; i < np; i++)
        {
            size_t o = 0;
            const char *p;
            int dup = 0;

            for (p = pts[i].label; *p && o < sizeof(ids[0]) - 1; p++)
                if (isalnum((unsigned char)*p))
                    ids[i][o++] = *p;
            ids[i][o] = '\0';
            for (j = 0; j < i; j++)
                dup |= !strcmp(ids[i], ids[j]);
            if (o == 0 || dup)
                snprintf(ids[i], sizeof(ids[i]), "v%zu", i);
            if (pts[i].v == dv)
                d = i;
        }
        SBL(b, ", \"ids\": [");
        for (i = 0; i < np; i++)
            sb_printf(b, "%s\"%s\"", i ? ", " : "", ids[i]);
        SBL(b, "], \"labels\": [");
        for (i = 0; i < np; i++)
        {
            if (i)
                SBL(b, ", ");
            sb_str(b, pts[i].label);
        }
        SBL(b, "], \"values\": [");
        for (i = 0; i < np; i++)
            sb_printf(b, "%s%.17g", i ? ", " : "", pts[i].v);
        sb_printf(b, "], \"default\": \"%s\"", ids[d]);
    }
    else if (!strcmp(kind, "\"toggle\""))
        sb_printf(b, ", \"default\": %s", def && strtod(def, NULL) != 0 ? "true" : "false");
    else if (!strcmp(kind, "\"travel\""))
    {
        const char *unit = get(e, "controls[].travel.unit"), *scale = get(e, "controls[].travel.scale");

        if (min == NULL || max == NULL)
            return refuse("%s is a travel that states no %s", e->scope, min ? "maximum" : "minimum");
        sb_printf(b, ", \"travel\": {\"min\": %s, \"max\": %s, \"unit\": %s", min, max, unit ? unit : "\"unknown\"");
        if (def)
            sb_printf(b, ", \"default\": %s", def);
        sb_printf(b, ", \"scale\": %s}", scale ? scale : !strcmp(format, "lv2") ? "\"linear\"" : "\"unknown\"");
    }
    if ((v = get(e, "controls[].group")) != NULL)
        sb_printf(b, ", \"group\": %s", v);
    v = get(e, "controls[].meaning");
    sb_printf(b, ", \"meaning\": %s", v ? v : "\"unknown\"");
    if (lit_true(get(e, "controls[].hidden")))
        sb_printf(b, ", \"hidden\": true");
    v = get(e, "ports[].direction");
    if (lit_true(get(e, "controls[].readonly")) || (v && !strcmp(v, "\"out\"")))
        sb_printf(b, ", \"readonly\": true");
    if (lit_true(get(e, "controls[].automatable")))
        sb_printf(b, ", \"automatable\": true");
    if (!strcmp(format, "lv2"))
    {
        jnode_t *sym = jparse(id);

        SBL(b, ", \"source\": {\"from\": ");
        put_link(b, from, sym && sym->type == J_STR ? sym->str : "port");
        SBL(b, "}");
    }
    SBL(b, "}");
    return 0;
}

/* a port: an entry, or for LV2 a run of channels n entries long */
static int put_port(sb_t *b, entry_t *const *run, size_t n, int first)
{
    const entry_t *e = run[0];
    const char *id = get(e, "ports[].id"), *name = get(e, "ports[].name"), *kind = get(e, "ports[].kind");
    const char *dir = get(e, "ports[].direction"), *role = get(e, "ports[].role"), *layout = get(e, "ports[].layout");
    const char *group = get(e, "controls[].group"), *channels = get(e, "ports[].channels");
    char num[24];

    if (e->kind == 'l')
    {
        id = get(e, "controls[].id");
        name = group ? NULL : get(e, "controls[].name");
    }
    else
    {
        kind = e->kind == 'i' || e->kind == 'o' ? "\"audio\"" : "\"note\"";
        dir = e->kind == 'i' || e->kind == 'n' ? "\"in\"" : "\"out\"";
    }
    if (id == NULL || dir == NULL)
        return refuse("%s states no %s", e->scope, id ? "direction" : "id");
    sb_printf(b, "%s\n    {\"id\": %s, \"name\": ", first ? "" : ",", id);
    if (name)
        sb_printf(b, "%s", name);
    else if (group)
    {
        jnode_t *g = jparse(group);

        sb_str(b, g && g->type == J_ARR && g->n ? g->kid[g->n - 1]->str : "port");
    }
    else
        sb_printf(b, "%s", id[0] == '"' ? id : "\"port\"");
    sb_printf(b, ", \"kind\": %s, \"direction\": %s", kind, dir);
    if (!strcmp(kind, "\"audio\""))
    {
        if (e->kind == 'l')
        {
            snprintf(num, sizeof(num), "%zu", n);
            channels = num;
            layout = n == 1 ? "\"mono\"" : n == 2 ? "\"stereo\"" : NULL;
        }
        sb_printf(b, ", \"role\": %s", role ? role : e->kind == 'l' ? "\"main\"" : "\"aux\"");
        if (channels)
            sb_printf(b, ", \"channels\": %s", channels);
        if (layout)
            sb_printf(b, ", \"layout\": %s", layout);
    }
    if (!strcmp(kind, "\"note\"") && has_list(e, "ports[].dialects"))
    {
        SBL(b, ", \"dialects\": ");
        put_list(b, e, "ports[].dialects");
    }
    SBL(b, "}");
    return 0;
}

static int same_run(const entry_t *a, const entry_t *b)
{
    const char *keys[] = { "ports[].kind", "ports[].direction", "ports[].role", "controls[].group" };
    size_t i;

    for (i = 0; i < sizeof(keys) / sizeof(keys[0]); i++)
    {
        const char *x = get(a, keys[i]), *y = get(b, keys[i]);

        if ((x == NULL) != (y == NULL) || (x && strcmp(x, y)))
            return 0;
    }
    return 1;
}

static int write_descriptor(const table_t *t, scan_t *s, const char *target, sb_t *b)
{
    entry_t *g = &s->e[0], *plugin = NULL, **controls = calloc(s->n, sizeof(entry_t *)), **ports = calloc(s->n, sizeof(entry_t *));
    size_t i, nc = 0, np = 0;
    const char *v, *from, *uri = !strcmp(t->format, "lv2") ? target + 4 : NULL;
    int first;

    for (i = 1; i < s->n; i++)
    {
        entry_t *e = &s->e[i];

        if (e->kind == 'g')
            plugin = e;
        else if (e->kind == 'p')
            controls[nc++] = e;
        else if (e->kind != 'l')
            ports[np++] = e;
        else if (get(e, "controls[].kind") && !e->latency)
            controls[nc++] = e;
        else if (get(e, "ports[].kind") && !get(e, "controls[].kind"))
            ports[np++] = e;
    }
    (void)plugin;
    qsort(controls, nc, sizeof(entry_t *), by_index);
    if ((from = get(g, "source.from")) == NULL)
        return refuse("the dump states no %s", uri ? "data file (rdfs:seeAlso)" : "file (clap_entry)");
    if (uri == NULL && (v = get(g, "plugin.id")) == NULL)
        return refuse("the dump states no plugin id (clap_plugin_descriptor.id)");
    sb_printf(b, "{\n  \"$schema\": \"%s\",\n  \"requires\": {\"omx-contract-schema\": \"%s\"},\n  \"origin\": \"scanned\",\n",
              SCHEMA_URL, SCHEMA_FLOOR);
    SBL(b, "  \"plugin\": {\"id\": ");
    if (uri)
        sb_str(b, uri);
    else
        sb_printf(b, "%s", get(g, "plugin.id"));
    sb_printf(b, ", \"format\": \"%s\"", t->format);
    if (uri)
    {
        SBL(b, ", \"uri\": ");
        sb_str(b, uri);
    }
    if ((v = get(g, "plugin.name")) == NULL)
        return refuse("the dump states no plugin name");
    sb_printf(b, ", \"name\": %s", v);
    if ((v = get(g, "plugin.vendor")) != NULL)
        sb_printf(b, ", \"vendor\": %s", v);
    if ((v = get(g, "plugin.version")) != NULL)
        sb_printf(b, ", \"version\": %s", v);
    if ((v = get(g, "plugin.doc")) != NULL)
        sb_printf(b, ", \"doc\": %s", v);
    if (!has_list(g, "plugin.features"))
        assign(g, word_index("plugin.features"), "\"audio-effect\"");
    SBL(b, ", \"features\": ");
    put_list(b, g, "plugin.features");
    SBL(b, "},\n  \"controls\": [");
    for (i = 0, first = 1; i < nc; i++, first = 0)
        if (put_control(b, controls[i], t->format, from, first))
            return -1;
    sb_printf(b, "%s,\n  \"ports\": [", nc ? "\n  ]" : "]");
    if (!strcmp(t->format, "lv2"))
    {
        qsort(ports, np, sizeof(entry_t *), by_index);
        for (i = 0, first = 1; i < np; first = 0)
        {
            size_t n = 1;
            const char *kind = get(ports[i], "ports[].kind");

            while (kind && !strcmp(kind, "\"audio\"") && i + n < np && ports[i + n]->index == ports[i + n - 1]->index + 1
                   && same_run(ports[i], ports[i + n]))
                n++;
            if (put_port(b, &ports[i], n, first))
                return -1;
            i += n;
        }
    }
    else
    {
        static const char ORDER[] = "ionN";
        const char *o;

        for (o = ORDER, first = 1; *o; o++)
        {
            entry_t *run[1];

            qsort(ports, np, sizeof(entry_t *), by_index);
            for (i = 0; i < np; i++)
                if (ports[i]->kind == *o)
                {
                    run[0] = ports[i];
                    if (put_port(b, run, 1, first))
                        return -1;
                    first = 0;
                }
        }
    }
    sb_printf(b, "%s", np ? "\n  ]" : "]");
    if (list_has(g, "plugin.features", "\"instrument\""))
    {
        v = get(g, "instrument.voices");
        SBL(b, ",\n  \"instrument\": {");
        if (v)
            sb_printf(b, "\"voices\": %s, ", v);
        sb_printf(b, "\"polyphonic\": %s}", v && strtod(v, NULL) > 1 ? "true" : "false");
    }
    if (get(g, "needs.transport") || get(g, "needs.tempo") || get(g, "needs.extensions.required")
        || get(g, "needs.extensions.optional"))
    {
        const char *sep = "";

        SBL(b, ",\n  \"needs\": {");
        if (lit_true(get(g, "needs.transport")))
            sb_printf(b, "%s\"transport\": true", sep), sep = ", ";
        if (lit_true(get(g, "needs.tempo")))
            sb_printf(b, "%s\"tempo\": true", sep), sep = ", ";
        if (get(g, "needs.extensions.required") || get(g, "needs.extensions.optional"))
        {
            const char *sep2 = "";

            sb_printf(b, "%s\"extensions\": {", sep);
            if (get(g, "needs.extensions.required"))
            {
                SBL(b, "\"required\": ");
                put_list(b, g, "needs.extensions.required");
                sep2 = ", ";
            }
            if (get(g, "needs.extensions.optional"))
            {
                sb_printf(b, "%s\"optional\": ", sep2);
                put_list(b, g, "needs.extensions.optional");
            }
            SBL(b, "}");
        }
        SBL(b, "}");
    }
    sb_printf(b, ",\n  \"latency\": {\"reports\": %s}", lit_true(get(g, "latency.reports")) ? "true" : "false");
    if (uri == NULL)
    {
        SBL(b, ",\n  \"source\": {\"from\": ");
        put_link(b, from, "clap_entry");
        SBL(b, "}");
    }
    if (s->nbag)
    {
        sb_printf(b, ",\n  \"extensions\": {\"%s\": {", t->format);
        for (i = 0; i < s->nbag; i++)
        {
            size_t k;

            sb_printf(b, "%s\n    ", i ? "," : "");
            sb_str(b, s->bag[i].key);
            SBL(b, ": ");
            if (s->bag[i].n == 1)
                sb_str(b, s->bag[i].v[0]);
            else
            {
                SBL(b, "[");
                for (k = 0; k < s->bag[i].n; k++)
                {
                    if (k)
                        SBL(b, ", ");
                    sb_str(b, s->bag[i].v[k]);
                }
                SBL(b, "]");
            }
        }
        SBL(b, "\n  }}");
    }
    SBL(b, "\n}\n");
    return 0;
}

/* ---------------------------------------------------------------- the entry points */

const char *describe_format(const char *target)
{
    if (!strncmp(target, "clap:", 5) && strchr(target + 5, '#') && target[5] != '#' && strchr(target, '#')[1])
        return "clap";
    if (!strncmp(target, "lv2:", 4) && target[4])
        return "lv2";
    return NULL;
}

const char *describe_id(const char *target)
{
    const char *format = describe_format(target);

    if (format == NULL)
        return NULL;
    return !strcmp(format, "clap") ? strrchr(target, '#') + 1 : target + 4;
}

int describe_dump(const char *table_text, const char *dump_text, const char *target, sb_t *out, char *why,
                  size_t why_size)
{
    table_t t = { 0 };
    scan_t s = { 0 };
    const char *format = describe_format(target);

    g_why = why, g_why_size = why_size;
    if (format == NULL)
        return refuse("%s is neither clap:<path>#<id> nor lv2:<uri>", target);
    if (load_table(table_text, &t))
        return -1;
    if (strcmp(t.format, format))
        return refuse("%s is a %s plugin, and the table is %s's", target, format, t.format);
    if (read_dump(&t, dump_text, &s))
        return -1;
    return write_descriptor(&t, &s, target, out);
}

/* the plugin of the scan's files whose id is the target's: files[].plugins[], or NULL */
static const jnode_t *scanned_plugin(const jnode_t *scan, const char *id)
{
    const jnode_t *files = jget(scan, "files"), *plugins;
    const char *pid;
    size_t f, p;

    for (f = 0; files && files->type == J_ARR && f < files->n; f++)
        for (p = 0, plugins = jget(files->kid[f], "plugins"); plugins && plugins->type == J_ARR && p < plugins->n; p++)
            if ((pid = jstr(plugins->kid[p], "id")) != NULL && !strcmp(pid, id))
                return plugins->kid[p];
    return NULL;
}

int describe_panel(const char *scan_json, const char *target, sb_t *out, char *why, size_t why_size)
{
    const char *format = describe_format(target), *id = describe_id(target), *error;
    const jnode_t *plugin, *panel;
    jnode_t *scan;

    g_why = why, g_why_size = why_size;
    if (format == NULL)
        return refuse("%s is neither clap:<path>#<id> nor lv2:<uri>", target);
    SBL(out, "{\"plugin\": {\"format\": ");
    sb_str(out, format);
    SBL(out, ", \"id\": ");
    sb_str(out, id);
    SBL(out, "}, \"panel\": ");
    /* the panel description is a CLAP extension: an LV2 plugin serves none */
    if (!strcmp(format, "lv2"))
    {
        SBL(out, "null}\n");
        return 0;
    }
    if ((scan = jparse(scan_json)) == NULL || scan->type != J_OBJ)
    {
        jfree(scan);
        return refuse("the scan's output is no JSON object");
    }
    if ((plugin = scanned_plugin(scan, id)) == NULL)
    {
        jfree(scan);
        return refuse("the scan lists no plugin %s", id);
    }
    if ((panel = jget(plugin, "panel")) == NULL)
    {
        error = jstr(plugin, "error");
        refuse("the scan states no panel for %s (%s)", id, error ? error : "a scanner before omx-clap-scan 0.20.0");
        jfree(scan);
        return -1;
    }
    sb_put(out, panel->at, panel->len);
    SBL(out, "}\n");
    jfree(scan);
    return 0;
}

/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The transforms of the format tables (transforms.h, docs/formats.md). */

#include "transforms.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------- text and JSON literals */

typedef struct
{
    char *s;
    size_t len, size;
    int full;
} out_t;

static void put(out_t *o, const char *data, size_t n)
{
    if (o->full || o->len + n + 1 > o->size)
    {
        o->full = 1;
        return;
    }
    memcpy(o->s + o->len, data, n);
    o->len += n;
    o->s[o->len] = '\0';
}

static void putf(out_t *o, const char *fmt, ...)
{
    char tmp[64];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n < 0 || (size_t)n >= sizeof(tmp))
        o->full = 1;
    else
        put(o, tmp, (size_t)n);
}

static int done(out_t *o)
{
    return o->full ? TRANSFORMS_REFUSED : TRANSFORMS_OK;
}

/* a JSON number, the whole text and nothing else (RFC 8259 section 6) */
static int is_number(const char *s)
{
    const char *p = s;

    if (*p == '-')
        p++;
    if (*p == '0')
        p++;
    else if (*p >= '1' && *p <= '9')
        while (*p >= '0' && *p <= '9')
            p++;
    else
        return 0;
    if (*p == '.')
    {
        p++;
        if (!(*p >= '0' && *p <= '9'))
            return 0;
        while (*p >= '0' && *p <= '9')
            p++;
    }
    if (*p == 'e' || *p == 'E')
    {
        p++;
        if (*p == '+' || *p == '-')
            p++;
        if (!(*p >= '0' && *p <= '9'))
            return 0;
        while (*p >= '0' && *p <= '9')
            p++;
    }
    return *p == '\0' && isfinite(strtod(s, NULL));
}

/* a number in its shortest spelling that reads back the same; -0 is spelt 0 */
static void put_number(out_t *o, double v)
{
    char tmp[40];
    int prec;

    if (v == 0)
        v = 0;
    for (prec = 15; prec <= 17; prec++)
    {
        snprintf(tmp, sizeof(tmp), "%.*g", prec, v);
        if (strtod(tmp, NULL) == v)
            break;
    }
    put(o, tmp, strlen(tmp));
}

static void put_quoted(out_t *o, const char *s, size_t n)
{
    size_t i;

    put(o, "\"", 1);
    for (i = 0; i < n; i++)
    {
        unsigned char c = (unsigned char)s[i];

        if (c == '"' || c == '\\')
        {
            put(o, "\\", 1);
            put(o, s + i, 1);
        }
        else if (c < 0x20)
            putf(o, "\\u%04x", c);
        else
            put(o, s + i, 1);
    }
    put(o, "\"", 1);
}

static const char *skip(const char *p)
{
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')
        p++;
    return p;
}

/* a JSON string literal at p into o (its text, unescaped); the byte after it, or NULL when p holds none */
static const char *read_string(const char *p, out_t *o)
{
    if (*p != '"')
        return NULL;
    for (p++; *p && *p != '"'; p++)
    {
        if ((unsigned char)*p < 0x20)
            return NULL;
        if (*p != '\\')
        {
            put(o, p, 1);
            continue;
        }
        p++;
        switch (*p)
        {
        case '"': case '\\': case '/': put(o, p, 1); break;
        case 'b': put(o, "\b", 1); break;
        case 'f': put(o, "\f", 1); break;
        case 'n': put(o, "\n", 1); break;
        case 'r': put(o, "\r", 1); break;
        case 't': put(o, "\t", 1); break;
        case 'u':
        {
            unsigned v = 0;
            int k;
            char u[3];

            for (k = 1; k <= 4; k++)
            {
                char c = p[k];

                v = v * 16 + (unsigned)(c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                                                                    : c >= 'A' && c <= 'F' ? c - 'A' + 10 : 99);
                if (v > 0xffff)
                    return NULL;
            }
            p += 4;
            /* the basic plane only, as UTF-8; a surrogate is refused */
            if (v >= 0xd800 && v <= 0xdfff)
                return NULL;
            if (v < 0x80)
                put(o, (char[]){ (char)v }, 1);
            else if (v < 0x800)
            {
                u[0] = (char)(0xc0 | (v >> 6)), u[1] = (char)(0x80 | (v & 0x3f));
                put(o, u, 2);
            }
            else
            {
                u[0] = (char)(0xe0 | (v >> 12)), u[1] = (char)(0x80 | ((v >> 6) & 0x3f)), u[2] = (char)(0x80 | (v & 0x3f));
                put(o, u, 3);
            }
            break;
        }
        default: return NULL;
        }
    }
    return *p == '"' ? p + 1 : NULL;
}

/* the one JSON string literal that is the whole of value, unescaped into o */
static int whole_string(const char *value, out_t *o)
{
    const char *end = read_string(skip(value), o);

    return end != NULL && *skip(end) == '\0' && !o->full;
}

/* a JSON array of strings, the whole of value: each item through each(); the item count, or -1 */
static int string_array(const char *value, int (*each)(void *ctx, int k, const char *s), void *ctx)
{
    const char *p = skip(value);
    int k = 0;

    if (*p++ != '[')
        return -1;
    p = skip(p);
    if (*p == ']')
        return *skip(p + 1) == '\0' ? 0 : -1;
    for (;;)
    {
        char buf[1024];
        out_t item = { buf, 0, sizeof(buf), 0 };

        buf[0] = '\0';
        p = read_string(p, &item);
        if (p == NULL || item.full || each(ctx, k++, buf))
            return -1;
        p = skip(p);
        if (*p == ']')
            return *skip(p + 1) == '\0' ? k : -1;
        if (*p++ != ',')
            return -1;
        p = skip(p);
    }
}

/* ---------------------------------------------------------------- identity */

int transforms_identity(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d;
    if (is_number(value))
        put_number(&o, strtod(value, NULL));
    else
        put_quoted(&o, value, strlen(value));
    return done(&o);
}

int transforms_identity_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d;
    out[0] = '\0';
    if (is_number(value))
        put_number(&o, strtod(value, NULL));
    else if (!whole_string(value, &o))
        return TRANSFORMS_REFUSED;
    return done(&o);
}

/* ---------------------------------------------------------------- lookup */

int transforms_lookup(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    size_t i;

    for (i = 0; i < d->n; i++)
        if (strcmp(d->from[i], value) == 0)
        {
            put(&o, d->to[i], strlen(d->to[i]));
            return done(&o);
        }
    return TRANSFORMS_NONE;
}

int transforms_lookup_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    size_t i;

    for (i = 0; i < d->n; i++)
        if (strcmp(d->to[i], value) == 0)
        {
            put(&o, d->from[i], strlen(d->from[i]));
            return done(&o);
        }
    return TRANSFORMS_NONE;
}

int transforms_lookup_check(const transforms_data_t *d)
{
    size_t i, j;

    for (i = 0; i < d->n; i++)
        for (j = i + 1; j < d->n; j++)
            if (strcmp(d->from[i], d->from[j]) == 0 || strcmp(d->to[i], d->to[j]) == 0)
                return -1;
    return 0;
}

/* ---------------------------------------------------------------- scale-by */

static int scale(const transforms_data_t *d, const char *value, char *out, size_t size, int inverse)
{
    out_t o = { out, 0, size, 0 };
    double v;

    if (d->factor == 0 || !isfinite(d->factor) || !is_number(value))
        return TRANSFORMS_REFUSED;
    v = strtod(value, NULL);
    v = inverse ? v / d->factor : v * d->factor;
    if (!isfinite(v))
        return TRANSFORMS_REFUSED;
    put_number(&o, v);
    return done(&o);
}

int transforms_scale_by(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    return scale(d, value, out, size, 0);
}

int transforms_scale_by_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    return scale(d, value, out, size, 1);
}

/* ---------------------------------------------------------------- flag */

int transforms_flag(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d, (void)value;
    put(&o, "true", 4);
    return done(&o);
}

int transforms_flag_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    const char *v = skip(value);

    if (strncmp(v, "false", 5) == 0 && *skip(v + 5) == '\0')
        return TRANSFORMS_NONE;
    if (strncmp(v, "true", 4) != 0 || *skip(v + 4) != '\0' || d->key == NULL)
        return TRANSFORMS_REFUSED;
    put(&o, d->key, strlen(d->key));
    return done(&o);
}

/* ---------------------------------------------------------------- scale-points */

/* "<number> <label>" -> [<number>,"<label>"] */
int transforms_scale_points(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    const char *sp = strchr(value, ' ');
    char num[64];

    (void)d;
    if (sp == NULL || sp == value || (size_t)(sp - value) >= sizeof(num) || sp[1] == '\0')
        return TRANSFORMS_REFUSED;
    memcpy(num, value, (size_t)(sp - value));
    num[sp - value] = '\0';
    if (!is_number(num))
        return TRANSFORMS_REFUSED;
    put(&o, "[", 1);
    put_number(&o, strtod(num, NULL));
    put(&o, ",", 1);
    put_quoted(&o, sp + 1, strlen(sp + 1));
    put(&o, "]", 1);
    return done(&o);
}

int transforms_scale_points_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    const char *p = skip(value), *end;
    char num[64], label[1024];
    out_t lo = { label, 0, sizeof(label), 0 };
    size_t n;

    (void)d;
    if (*p++ != '[')
        return TRANSFORMS_REFUSED;
    p = skip(p);
    for (end = p; *end && *end != ',' && *end != ' ' && *end != ']'; end++)
        ;
    n = (size_t)(end - p);
    if (n == 0 || n >= sizeof(num))
        return TRANSFORMS_REFUSED;
    memcpy(num, p, n);
    num[n] = '\0';
    p = skip(end);
    if (!is_number(num) || *p++ != ',')
        return TRANSFORMS_REFUSED;
    label[0] = '\0';
    p = read_string(skip(p), &lo);
    if (p == NULL || lo.full || lo.len == 0)
        return TRANSFORMS_REFUSED;
    p = skip(p);
    if (*p != ']' || *skip(p + 1) != '\0')
        return TRANSFORMS_REFUSED;
    put_number(&o, strtod(num, NULL));
    put(&o, " ", 1);
    put(&o, label, lo.len);
    return done(&o);
}

/* ---------------------------------------------------------------- group-path, port-group */

/* "a/b" -> ["a","b"]; an empty segment is no level */
int transforms_group_path(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };
    const char *p = value;
    int k = 0;

    (void)d;
    put(&o, "[", 1);
    while (*p)
    {
        size_t n = strcspn(p, "/");

        if (n > 0)
        {
            if (k++)
                put(&o, ",", 1);
            put_quoted(&o, p, n);
        }
        p += n;
        if (*p == '/')
            p++;
    }
    put(&o, "]", 1);
    return k == 0 ? TRANSFORMS_NONE : done(&o);
}

static int join_item(void *ctx, int k, const char *s)
{
    out_t *o = ctx;

    if (*s == '\0' || strchr(s, '/') != NULL)
        return -1;
    if (k)
        put(o, "/", 1);
    put(o, s, strlen(s));
    return 0;
}

int transforms_group_path_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d;
    out[0] = '\0';
    if (string_array(value, join_item, &o) < 1)
        return TRANSFORMS_REFUSED;
    return done(&o);
}

/* an LV2 group's label -> ["label"]; a pg:subGroupOf record is one level above, which describe puts before the rest */
int transforms_port_group(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d;
    if (*value == '\0')
        return TRANSFORMS_NONE;
    put(&o, "[", 1);
    put_quoted(&o, value, strlen(value));
    put(&o, "]", 1);
    return done(&o);
}

/* the path's last level is the group a port names (pg:group); the levels before it are its pg:subGroupOf chain */
static int last_item(void *ctx, int k, const char *s)
{
    out_t *o = ctx;

    (void)k;
    if (*s == '\0')
        return -1;
    o->len = 0;
    put(o, s, strlen(s));
    return 0;
}

int transforms_port_group_inverse(const transforms_data_t *d, const char *value, char *out, size_t size)
{
    out_t o = { out, 0, size, 0 };

    (void)d;
    out[0] = '\0';
    if (string_array(value, last_item, &o) < 1)
        return TRANSFORMS_REFUSED;
    return done(&o);
}

/* ---------------------------------------------------------------- the list */

#define TRANSFORMS_ENTRY(name, in, inverse) { name, in, inverse },
const transforms_entry_t transforms_list[] = { TRANSFORMS(TRANSFORMS_ENTRY) };
#undef TRANSFORMS_ENTRY
const size_t transforms_count = sizeof(transforms_list) / sizeof(transforms_list[0]);

const transforms_entry_t *transforms_find(const char *name)
{
    size_t i;

    for (i = 0; i < transforms_count; i++)
        if (strcmp(transforms_list[i].name, name) == 0)
            return &transforms_list[i];
    return NULL;
}

/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* Strings that grow and a small JSON reader: the probe runner's child lines and the format tables describe reads. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"

/* ---------------------------------------------------------------- strings that grow */

void sb_put(sb_t *b, const char *data, size_t n)
{
    if (b->len + n + 1 > b->cap)
    {
        b->cap = (b->len + n + 1) * 2;
        b->s = realloc(b->s, b->cap);
        if (b->s == NULL)
        {
            fprintf(stderr, "plugin-hostd-probe: out of memory\n");
            exit(2);
        }
    }
    memcpy(b->s + b->len, data, n);
    b->len += n;
    b->s[b->len] = '\0';
}

void sb_printf(sb_t *b, const char *fmt, ...)
{
    char tmp[512];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n < sizeof(tmp))
    {
        sb_put(b, tmp, (size_t)n);
        return;
    }
    {
        char *big = malloc((size_t)n + 1);

        va_start(ap, fmt);
        vsnprintf(big, (size_t)n + 1, fmt, ap);
        va_end(ap);
        sb_put(b, big, (size_t)n);
        free(big);
    }
}

/* a JSON string: the bytes of a valid UTF-8 text as they are, a control character or a byte that is not UTF-8 escaped */
void sb_str(sb_t *b, const char *s)
{
    const unsigned char *p = (const unsigned char *)s;

    sb_put(b, "\"", 1);
    for (; *p; p++)
    {
        if (*p == '"' || *p == '\\')
        {
            sb_put(b, "\\", 1);
            sb_put(b, (const char *)p, 1);
        }
        else if (*p < 0x20 || *p == 0x7f)
            sb_printf(b, "\\u%04x", *p);
        else if (*p < 0x80)
            sb_put(b, (const char *)p, 1);
        else
        {
            int n = *p >= 0xf0 ? 4 : *p >= 0xe0 ? 3 : *p >= 0xc0 ? 2 : 0, k, ok = n > 0;

            for (k = 1; ok && k < n; k++)
                ok = (p[k] & 0xc0) == 0x80;
            if (ok)
            {
                sb_put(b, (const char *)p, (size_t)n);
                p += n - 1;
            }
            else
                sb_printf(b, "\\u%04x", *p);
        }
    }
    sb_put(b, "\"", 1);
}

/* ---------------------------------------------------------------- a small JSON reader for the child's line */

static jnode_t *jparse_value(const char **p, int depth);

static void jskip(const char **p)
{
    while (**p == ' ' || **p == '\t' || **p == '\n' || **p == '\r')
        (*p)++;
}

static char *jparse_string(const char **p)
{
    sb_t b = { 0 };

    (*p)++;
    while (**p && **p != '"')
    {
        if (**p == '\\' && (*p)[1])
        {
            char c = (*p)[1];

            (*p) += 2;
            if (c == 'n')
                sb_put(&b, "\n", 1);
            else if (c == 't')
                sb_put(&b, "\t", 1);
            else if (c == 'u')
            {
                unsigned v = 0;
                int k;

                for (k = 0; k < 4 && isxdigit((unsigned char)**p); k++, (*p)++)
                    v = v * 16 + (unsigned)(isdigit((unsigned char)**p) ? **p - '0' : (tolower((unsigned char)**p) - 'a' + 10));
                if (v < 0x80)
                    sb_put(&b, (const char *)&(char){ (char)v }, 1);
                else
                    sb_put(&b, "?", 1);
            }
            else
                sb_put(&b, &c, 1);
        }
        else
        {
            sb_put(&b, *p, 1);
            (*p)++;
        }
    }
    if (**p != '"')
    {
        free(b.s);
        return NULL;
    }
    (*p)++;
    return b.s ? b.s : strdup("");
}

static jnode_t *jnew(jtype_t t)
{
    jnode_t *n = calloc(1, sizeof(*n));

    n->type = t;
    return n;
}

static jnode_t *jparse_value(const char **p, int depth)
{
    jnode_t *n;

    if (depth > 32)
        return NULL;
    jskip(p);
    if (**p == '{')
    {
        n = jnew(J_OBJ);
        (*p)++;
        jskip(p);
        if (**p == '}')
        {
            (*p)++;
            return n;
        }
        for (;;)
        {
            char *key;
            jnode_t *v;

            jskip(p);
            if (**p != '"' || (key = jparse_string(p)) == NULL)
                return NULL;
            jskip(p);
            if (*(*p)++ != ':' || (v = jparse_value(p, depth + 1)) == NULL)
                return NULL;
            n->kid = realloc(n->kid, (n->n + 1) * sizeof(*n->kid));
            n->key = realloc(n->key, (n->n + 1) * sizeof(*n->key));
            n->key[n->n] = key;
            n->kid[n->n++] = v;
            jskip(p);
            if (**p == ',')
            {
                (*p)++;
                continue;
            }
            if (**p == '}')
            {
                (*p)++;
                return n;
            }
            return NULL;
        }
    }
    if (**p == '[')
    {
        n = jnew(J_ARR);
        (*p)++;
        jskip(p);
        if (**p == ']')
        {
            (*p)++;
            return n;
        }
        for (;;)
        {
            jnode_t *v = jparse_value(p, depth + 1);

            if (v == NULL)
                return NULL;
            n->kid = realloc(n->kid, (n->n + 1) * sizeof(*n->kid));
            n->kid[n->n++] = v;
            jskip(p);
            if (**p == ',')
            {
                (*p)++;
                continue;
            }
            if (**p == ']')
            {
                (*p)++;
                return n;
            }
            return NULL;
        }
    }
    if (**p == '"')
    {
        n = jnew(J_STR);
        n->str = jparse_string(p);
        return n->str ? n : NULL;
    }
    if (!strncmp(*p, "true", 4) || !strncmp(*p, "false", 5))
    {
        n = jnew(J_BOOL);
        n->boolean = **p == 't';
        *p += n->boolean ? 4 : 5;
        return n;
    }
    if (!strncmp(*p, "null", 4))
    {
        *p += 4;
        return jnew(J_NULL);
    }
    {
        char *end;
        double v = strtod(*p, &end);

        if (end == *p)
            return NULL;
        n = jnew(J_NUM);
        n->num = v;
        *p = end;
        return n;
    }
}

/* the whole text is one value */
jnode_t *jparse(const char *text)
{
    const char *p = text;
    jnode_t *n = jparse_value(&p, 0);

    if (n == NULL)
        return NULL;
    jskip(&p);
    return *p == '\0' ? n : NULL;
}

void jfree(jnode_t *n)
{
    size_t k;

    if (!n)
        return;
    for (k = 0; k < n->n; k++)
    {
        jfree(n->kid[k]);
        if (n->key)
            free(n->key[k]);
    }
    free(n->kid);
    free(n->key);
    free(n->str);
    free(n);
}

jnode_t *jget(const jnode_t *o, const char *key)
{
    size_t i;

    if (o == NULL || o->type != J_OBJ)
        return NULL;
    for (i = 0; i < o->n; i++)
        if (!strcmp(o->key[i], key))
            return o->kid[i];
    return NULL;
}

const char *jstr(const jnode_t *o, const char *key)
{
    jnode_t *v = jget(o, key);

    return v && v->type == J_STR ? v->str : NULL;
}

int jnum(const jnode_t *o, const char *key, double *out)
{
    jnode_t *v = jget(o, key);

    if (v == NULL || v->type != J_NUM)
        return 0;
    *out = v->num;
    return 1;
}

int jbool(const jnode_t *o, const char *key, int def)
{
    jnode_t *v = jget(o, key);

    return v && v->type == J_BOOL ? v->boolean : def;
}

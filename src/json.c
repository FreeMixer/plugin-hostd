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

#include <omxcontract/omx_json_write.h>

/* ---------------------------------------------------------------- strings that grow */

static void sb_out_of_memory(sb_t *b)
{
    if (!b->keep_going)
    {
        fprintf(stderr, "plugin-hostd-probe: out of memory\n");
        exit(2);
    }
    free(b->s);
    b->s = NULL;
    b->len = b->cap = 0;
    b->failed = 1;
}

void sb_put(sb_t *b, const char *data, size_t n)
{
    if (b->failed)
        return;
    if (b->len + n + 1 > b->cap)
    {
        size_t cap = (b->len + n + 1) * 2;
        char *grown = realloc(b->s, cap);

        if (grown == NULL)
        {
            sb_out_of_memory(b);
            return;
        }
        b->s = grown;
        b->cap = cap;
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

        if (big == NULL)
        {
            sb_out_of_memory(b);
            return;
        }
        va_start(ap, fmt);
        vsnprintf(big, (size_t)n + 1, fmt, ap);
        va_end(ap);
        sb_put(b, big, (size_t)n);
        free(big);
    }
}

/* a JSON string: the bytes of a valid UTF-8 text as they are, each one spelled by omx-contract's one JSON writer
 * (<omxcontract/omx_json_write.h>: a quote and a backslash backslashed, a control character \n or \u00XX, 0x7f and every
 * byte above it as it is); a byte that is not UTF-8 becomes U+FFFD, so the document stays a UTF-8 text */
void sb_str(sb_t *b, const char *s)
{
    const unsigned char *p = (const unsigned char *)s;
    char esc[OMX_JSON_ESCAPE_MAX];

    sb_put(b, "\"", 1);
    for (; *p; p++)
    {
        if (*p < 0x80)
            sb_put(b, esc, omx_json_escape_byte(*p, esc));
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
                sb_put(b, "\xef\xbf\xbd", 3);
        }
    }
    sb_put(b, "\"", 1);
}

/* ---------------------------------------------------------------- reading: cJSON */

/* the whole text is one value */
cJSON *jparse(const char *text)
{
    return cJSON_ParseWithOpts(text, NULL, 1);
}

cJSON *jget(const cJSON *o, const char *key)
{
    return cJSON_IsObject(o) ? cJSON_GetObjectItemCaseSensitive(o, key) : NULL;
}

const char *jstr(const cJSON *o, const char *key)
{
    cJSON *v = jget(o, key);

    return cJSON_IsString(v) ? v->valuestring : NULL;
}

int jnum(const cJSON *o, const char *key, double *out)
{
    cJSON *v = jget(o, key);

    if (!cJSON_IsNumber(v))
        return 0;
    *out = v->valuedouble;
    return 1;
}

int jbool(const cJSON *o, const char *key, int def)
{
    cJSON *v = jget(o, key);

    return cJSON_IsBool(v) ? cJSON_IsTrue(v) : def;
}

size_t jcount(const cJSON *o)
{
    return cJSON_IsArray(o) || cJSON_IsObject(o) ? (size_t)cJSON_GetArraySize(o) : 0;
}

cJSON *jkid(const cJSON *o, size_t k)
{
    return cJSON_IsArray(o) || cJSON_IsObject(o) ? cJSON_GetArrayItem(o, (int)k) : NULL;
}

const char *jkey(const cJSON *o, size_t k)
{
    cJSON *v = jkid(o, k);

    return v ? v->string : NULL;
}

/* ---------------------------------------------------------------- the bytes of a value, as written */

static const char *raw_skip_space(const char *p)
{
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')
        p++;
    return p;
}

/* past the string that starts at p (a quote) */
static const char *raw_string_end(const char *p)
{
    for (p++; *p && *p != '"'; p++)
        if (*p == '\\' && p[1])
            p++;
    return *p ? p + 1 : p;
}

/* past the value that starts at p; the text is valid JSON, cJSON has read it */
static const char *raw_value_end(const char *p)
{
    int depth = 0;

    p = raw_skip_space(p);
    if (*p == '"')
        return raw_string_end(p);
    if (*p != '{' && *p != '[')
    {
        while (*p && !strchr(" \t\n\r,]}", *p))
            p++;
        return p;
    }
    for (; *p; p++)
    {
        if (*p == '"')
            p = raw_string_end(p) - 1;
        else if (*p == '{' || *p == '[')
            depth++;
        else if ((*p == '}' || *p == ']') && --depth == 0)
            return p + 1;
    }
    return p;
}

const char *jraw(const char *text, const jstep_t *path, size_t steps, size_t *len)
{
    const char *p = raw_skip_space(text);
    size_t s;

    for (s = 0; s < steps; s++)
    {
        size_t at = 0;
        char open = path[s].key ? '{' : '[';

        if (*p != open)
            return NULL;
        p = raw_skip_space(p + 1);
        for (;;)
        {
            int match;

            if (*p == '\0' || *p == '}' || *p == ']')
                return NULL;
            if (path[s].key)
            {
                const char *end = raw_string_end(p);

                match = (size_t)(end - p) == strlen(path[s].key) + 2 && !strncmp(p + 1, path[s].key, strlen(path[s].key));
                p = raw_skip_space(end);
                p = raw_skip_space(p + 1); /* the colon */
            }
            else
                match = at++ == path[s].index;
            if (match)
                break;
            p = raw_skip_space(raw_value_end(p));
            if (*p == ',')
                p = raw_skip_space(p + 1);
        }
    }
    p = raw_skip_space(p);
    *len = (size_t)(raw_value_end(p) - p);
    return p;
}

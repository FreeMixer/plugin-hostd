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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "json.h"
#include "presets.h"

static int is_str(const jnode_t *n)
{
    return n && n->type == J_STR;
}

/* a key that may be absent, and is of the type when present */
static int maybe(const jnode_t *o, const char *key, jtype_t type)
{
    const jnode_t *n = jget(o, key);

    return !n || n->type == type;
}

static int base64(const char *s)
{
    size_t n = strspn(s, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"), pad = strspn(s + n, "=");

    return pad <= 2 && !s[n + pad];
}

static int digits(const char *s, int n)
{
    while (n--)
        if (*s < '0' || *s++ > '9')
            return 0;
    return 1;
}

/* YYYY-MM-DDTHH:MM:SS(.fraction)?Z */
static int utc(const char *s)
{
    if (strlen(s) < 20 || !digits(s, 4) || s[4] != '-' || !digits(s + 5, 2) || s[7] != '-' || !digits(s + 8, 2) ||
        s[10] != 'T' || !digits(s + 11, 2) || s[13] != ':' || !digits(s + 14, 2) || s[16] != ':' || !digits(s + 17, 2))
        return 0;
    s += 19;
    if (*s == '.')
    {
        size_t n = strspn(++s, "0123456789");

        if (!n)
            return 0;
        s += n;
    }
    return !strcmp(s, "Z");
}

/* omx-layout/1:<sha256 hex>, the only scheme this version knows */
static int fingerprint(const char *s)
{
    size_t scheme = strlen(PHD_PIN_LAYOUT_SCHEME);

    return !strncmp(s, PHD_PIN_LAYOUT_SCHEME, scheme) && s[scheme] == ':' &&
           strlen(s + scheme + 1) == PHD_SHA256_HEX_LEN &&
           strspn(s + scheme + 1, "0123456789abcdef") == PHD_SHA256_HEX_LEN;
}

static int nonempty(const jnode_t *n)
{
    return is_str(n) && n->str[0];
}

static int params_ok(const jnode_t *a)
{
    size_t k;

    if (a->type != J_ARR)
        return 0;
    for (k = 0; k < a->n; k++)
    {
        const jnode_t *p = a->kid[k], *v;

        if (p->type != J_OBJ || !nonempty(jget(p, "symbol")) || !maybe(p, "unit", J_STR) ||
            !(v = jget(p, "value")) || v->type != J_NUM)
            return 0;
    }
    return 1;
}

static int state_ok(const jnode_t *s)
{
    const jnode_t *ctx, *bytes, *files;
    size_t k;

    if (s->type != J_OBJ || !is_str(jget(s, "encoding")) || strcmp(jstr(s, "encoding"), "base64") ||
        !is_str(ctx = jget(s, "context")) || !is_str(bytes = jget(s, "bytes")) || !base64(bytes->str))
        return 0;
    if (strcmp(ctx->str, "preset") && strcmp(ctx->str, "project") && strcmp(ctx->str, "lv2"))
        return 0;
    if (!(files = jget(s, "files")))
        return 1;
    if (files->type != J_ARR)
        return 0;
    for (k = 0; k < files->n; k++)
    {
        const jnode_t *f = files->kid[k];

        if (f->type != J_OBJ || !nonempty(jget(f, "name")) || strchr(jstr(f, "name"), '/') ||
            !is_str(jget(f, "encoding")) || strcmp(jstr(f, "encoding"), "base64") || !is_str(jget(f, "bytes")) ||
            !base64(jstr(f, "bytes")))
            return 0;
    }
    return 1;
}

static int doc_ok(const jnode_t *d)
{
    const jnode_t *plugin, *n, *carries, *params, *state;
    int v2;
    size_t k;

    if (!d || d->type != J_OBJ || !is_str(n = jget(d, "format")))
        return 0;
    if (!strcmp(n->str, PHD_PRESET_FORMAT_2))
        v2 = 1;
    else if (!strcmp(n->str, PHD_PRESET_FORMAT_1))
        v2 = 0;
    else
        return 0;   /* an unknown version is refused, never guessed */
    plugin = jget(d, "plugin");
    if (!v2 && nonempty(plugin))
        plugin = NULL;  /* a /1 may name its plugin by its id alone, as omx-plugins' factory presets do */
    else if (!plugin || plugin->type != J_OBJ || !nonempty(jget(plugin, "id")))
        return 0;
    if (plugin && (n = jget(plugin, "version")) && !nonempty(n))
        return 0;
    if (plugin && (n = jget(plugin, "fingerprint")) && !(is_str(n) && fingerprint(n->str)))
        return 0;
    if (!nonempty(jget(d, "id")) || !is_str(jget(d, "name")))
        return 0;
    if ((n = jget(d, "alias")) && !(is_str(n) && n->str[0] && strlen(n->str) <= PHD_PRESET_ALIAS_MAX))
        return 0;
    if (!maybe(d, "bank", J_STR) || !maybe(d, "description", J_STR) || !maybe(d, "tags", J_ARR))
        return 0;
    if ((n = jget(d, "tags")))
        for (k = 0; k < n->n; k++)
            if (!is_str(n->kid[k]))
                return 0;
    if (((n = jget(d, "createdAt")) && !(is_str(n) && utc(n->str))) ||
        ((n = jget(d, "modifiedAt")) && !(is_str(n) && utc(n->str))))
        return 0;
    params = jget(d, "params");
    state = jget(d, "state");
    if ((params && !params_ok(params)) || (state && !state_ok(state)))
        return 0;
    carries = jget(d, "carries");
    if (carries && !(is_str(carries) && (!strcmp(carries->str, "params") || !strcmp(carries->str, "params+state") ||
                                         !strcmp(carries->str, "state"))))
        return 0;
    if (!v2 && (!params || state || (carries && strcmp(carries->str, "params"))))
        return 0;
    if (v2 && (!carries || !jget(plugin, "version") || !jget(plugin, "fingerprint")))
        return 0;
    /* carries and the body agree */
    if (carries && !strcmp(carries->str, "params") && (!params || state))
        return 0;
    if (carries && !strcmp(carries->str, "params+state") && (!params || !state))
        return 0;
    if (carries && !strcmp(carries->str, "state") && !state)
        return 0;
    return 1;
}

int preset_text_check(const char *text, char **plugin_id, char **fp)
{
    jnode_t *d = jparse(text);
    int ok = doc_ok(d);

    const jnode_t *plugin = ok ? jget(d, "plugin") : NULL;

    if (ok && plugin_id)
        *plugin_id = strdup(plugin->type == J_STR ? plugin->str : jstr(plugin, "id"));
    if (ok && fp)
    {
        const char *s = plugin->type == J_OBJ ? jstr(plugin, "fingerprint") : NULL;

        *fp = s ? strdup(s) : NULL;
    }
    jfree(d);
    return ok ? 0 : PHD_ERR_PRESET_INVALID;
}

int preset_file_check(const char *path, char **plugin_id, char **fp)
{
    struct stat st;
    FILE *f;
    char *text;
    size_t got;
    int rc;

    if (path[0] != '/' || stat(path, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > PHD_PRESET_FILE_MAX)
        return PHD_ERR_PRESET_INVALID;
    if (!(f = fopen(path, "rb")))
        return PHD_ERR_PRESET_INVALID;
    text = malloc(st.st_size + 1);
    got = fread(text, 1, st.st_size, f);
    fclose(f);
    text[got] = '\0';
    rc = got == (size_t)st.st_size && strlen(text) == got ? preset_text_check(text, plugin_id, fp) : PHD_ERR_PRESET_INVALID;
    free(text);
    return rc;
}

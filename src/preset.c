/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The daemon's reading of a preset file: what protocol/preset.schema.json says of it, so that no worker is handed a
 * file of a version it would have to guess at. The plugin it names is the worker's to compare with its instance. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <host-errors.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "json.h"
#include "preset.h"

int preset_is_path(const char *word)
{
    return word[0] == '/';
}

static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    char *text = NULL;
    long size;

    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) == 0 && (size = ftell(f)) >= 0 && size <= PHD_PRESET_FILE_MAX &&
        fseek(f, 0, SEEK_SET) == 0 && (text = malloc(size + 1)) && fread(text, 1, size, f) == (size_t)size)
        text[size] = '\0';
    else
    {
        free(text);
        text = NULL;
    }
    fclose(f);
    return text;
}

/* a string member: present and a string, or absent when it may be */
static int string_at(const jnode_t *o, const char *key, int required)
{
    jnode_t *v = jget(o, key);

    return v ? v->type == J_STR : !required;
}

static size_t utf8_chars(const char *s)
{
    size_t n = 0;

    for (; *s; s++)
        n += ((unsigned char)*s & 0xc0) != 0x80;
    return n;
}

static int base64_word(const char *s)
{
    size_t n = strspn(s, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/");

    return strspn(s + n, "=") <= 2 && s[n + strspn(s + n, "=")] == '\0';
}

/* the layout pin of a scheme this version knows */
static int fingerprint_known(const char *s)
{
    size_t scheme = strlen(PHD_PIN_LAYOUT_SCHEME);

    return !strncmp(s, PHD_PIN_LAYOUT_SCHEME, scheme) && s[scheme] == ':' &&
           strspn(s + scheme + 1, "0123456789abcdef") == 64 && s[scheme + 65] == '\0';
}

static int params_valid(const jnode_t *params)
{
    size_t n;

    if (params->type != J_ARR)
        return 0;
    for (n = 0; n < params->n; n++)
    {
        const jnode_t *p = params->kid[n], *value = jget(p, "value");
        const char *symbol = jstr(p, "symbol");

        if (p->type != J_OBJ || !symbol || !*symbol || !value || value->type != J_NUM || !string_at(p, "unit", 0))
            return 0;
    }
    return 1;
}

static int state_valid(const jnode_t *state)
{
    const char *encoding = jstr(state, "encoding"), *context = jstr(state, "context"), *bytes = jstr(state, "bytes");
    const jnode_t *files = jget(state, "files");
    size_t n;

    if (state->type != J_OBJ || !encoding || strcmp(encoding, "base64") || !context || !bytes || !base64_word(bytes))
        return 0;
    if (strcmp(context, "preset") && strcmp(context, "project") && strcmp(context, "lv2"))
        return 0;
    if (!files)
        return 1;
    if (files->type != J_ARR)
        return 0;
    for (n = 0; n < files->n; n++)
    {
        const char *name = jstr(files->kid[n], "name"), *fenc = jstr(files->kid[n], "encoding"),
                   *fbytes = jstr(files->kid[n], "bytes");

        if (!name || !*name || strchr(name, '/') || !fenc || strcmp(fenc, "base64") || !fbytes || !base64_word(fbytes))
            return 0;
    }
    return 1;
}

static int preset_valid(const jnode_t *doc)
{
    const char *format = jstr(doc, "format"), *carries = jstr(doc, "carries"), *alias = jstr(doc, "alias"),
               *fingerprint;
    const jnode_t *plugin = jget(doc, "plugin"), *params = jget(doc, "params"), *state = jget(doc, "state");
    int v2, want_params, want_state;

    if (!doc || doc->type != J_OBJ || !format)
        return 0;
    if (!strcmp(format, PHD_PRESET_FORMAT_2))
        v2 = 1;
    else if (!strcmp(format, PHD_PRESET_FORMAT_1))
        v2 = 0;
    else
        return 0;
    if (!plugin || plugin->type != J_OBJ || !jstr(plugin, "id") || !*jstr(plugin, "id") ||
        !string_at(plugin, "version", v2) || !string_at(plugin, "fingerprint", v2))
        return 0;
    if ((fingerprint = jstr(plugin, "fingerprint")) && !fingerprint_known(fingerprint))
        return 0;
    if (!jstr(doc, "id") || !*jstr(doc, "id") || !string_at(doc, "name", 1))
        return 0;
    if (jget(doc, "alias") && (!alias || !*alias || utf8_chars(alias) > PHD_PRESET_ALIAS_MAX))
        return 0;
    if (!carries)
    {
        if (v2 || jget(doc, "carries"))
            return 0;
        carries = "params";
    }
    if (!v2 && strcmp(carries, "params"))
        return 0;
    if (!strcmp(carries, "params"))
        want_params = 1, want_state = 0;
    else if (!strcmp(carries, "params+state"))
        want_params = 1, want_state = 1;
    else if (!strcmp(carries, "state"))
        want_params = 0, want_state = 1;
    else
        return 0;
    /* carries and the body agree: a state body dropped, or one the format does not carry, is refused */
    if ((want_params && !params) || (want_state && !state) || (!want_state && state))
        return 0;
    if (params && !params_valid(params))
        return 0;
    return !state || state_valid(state);
}

int preset_file_check(const char *path)
{
    char *text = slurp(path);
    jnode_t *doc = text ? jparse(text) : NULL;
    int ok = doc && preset_valid(doc);

    jfree(doc);
    free(text);
    return ok ? SUCCESS : PHD_ERR_PRESET_INVALID;
}

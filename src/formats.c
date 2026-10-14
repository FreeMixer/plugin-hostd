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

#include <limits.h>
#include <stdio.h>
#include <string.h>

#include <host-errors.h>
#include <plugin-hostd/protocol.h>

#include "formats.h"
#include "pins.h"

#define CLAP_PREFIX "clap:"
#define LV2_PREFIX  "lv2:"

static const char *clap_worker(const conf_t *conf)
{
    return conf->clap_host;
}

static const char *lv2_worker(const conf_t *conf)
{
    return conf->mod_host;
}

static const char *lv2_search(const conf_t *conf)
{
    return conf->lv2_path;
}

/* clap:<path>#<id>: the .clap file is what a host loads, and a pin holds the files beside it that it names */
int clap_pin_collect(const char *uri, const char *search, char *root, size_t size, names_t *files)
{
    const char *path = uri + strlen(CLAP_PREFIX), *hash = strrchr(path, '#'), *slash;
    size_t len = hash ? (size_t)(hash - path) : strlen(path);

    (void)search;
    snprintf(root, size, "%.*s", (int)len, path);
    slash = strrchr(root, '/');
    if (!slash)
        return pin_refuse(uri, root, "is not a path");
    names_add(files, slash + 1);
    root[slash - root] = '\0';
    return SUCCESS;
}

/* The built-in rows, in the order of PHD_FORMATS. */
static const format_t g_builtin[] = {
    {
        .name = PHD_FORMAT_LV2,
        .prefix = LV2_PREFIX,
        .strip_prefix = 1,
        .fallback = 1,
        .worker = lv2_worker,
        .search = lv2_search,
        .world_env = "LV2_PATH",
        .narrow_world = lv2_narrow_world,
        .pin_collect = lv2_pin_collect,
        .layout_check = 0,
        .pinned_own_only = 1,
        .native_instance_verbs = 0,
        .param_info = lv2_param_info,
    },
    {
        .name = PHD_FORMAT_CLAP,
        .prefix = CLAP_PREFIX,
        .strip_prefix = 0,
        .fallback = 0,
        .worker = clap_worker,
        .pin_collect = clap_pin_collect,
        .layout_check = 1,
        .pinned_own_only = 0,
        .native_instance_verbs = 1,
    },
};

static format_t g_format[FORMATS_MAX];
static int g_count;

static void builtin(void)
{
    size_t n;

    if (g_count)
        return;
    for (n = 0; n < sizeof(g_builtin) / sizeof(g_builtin[0]); n++)
        g_format[g_count++] = g_builtin[n];
}

static int reject(const format_t *f, const char *why)
{
    fprintf(stderr, "plugin-hostd: format %s: %s\n", f->name ? f->name : "(no name)", why);
    return -1;
}

int formats_register(const format_t *f)
{
    int n;

    builtin();
    if (!f->name || !*f->name || !strcmp(f->name, PHD_FORMAT_ANY) || !strcmp(f->name, PHD_WORD_ALL) ||
        !strcmp(f->name, PHD_WORD_NONE))
        return reject(f, "has no name, or one that a verb reads as a word of its own");
    if (g_count == FORMATS_MAX)
        return reject(f, "the table is full");
    if (!f->worker)
        return reject(f, "has no worker program");
    if (!f->pin_collect)
        return reject(f, "has no pin_collect: it does not say which files a pin holds");
    if (!f->prefix && !f->fallback)
        return reject(f, "has no prefix and is not the fallback: no uri could reach it");
    if (f->prefix && !*f->prefix)
        return reject(f, "has an empty prefix");
    if (f->narrow_world && !f->world_env)
        return reject(f, "narrows its world but names no world_env to carry it");
    if (!f->native_instance_verbs && !f->param_info)
        return reject(f, "does not answer the instance verbs and has no param_info for the daemon to answer with");
    for (n = 0; n < g_count; n++)
    {
        if (!strcmp(g_format[n].name, f->name))
            return reject(f, "is already in the table");
        if (f->fallback && g_format[n].fallback)
            return reject(f, "is a second fallback");
        if (f->prefix && g_format[n].prefix &&
            (!strncmp(f->prefix, g_format[n].prefix, strlen(g_format[n].prefix)) ||
             !strncmp(f->prefix, g_format[n].prefix, strlen(f->prefix))))
            return reject(f, "has a prefix another row's prefix starts with, or the other way round");
    }
    g_format[g_count] = *f;
    return g_count++;
}

int formats_count(void)
{
    builtin();
    return g_count;
}

const format_t *format_at(int index)
{
    builtin();
    return index >= 0 && index < g_count ? &g_format[index] : NULL;
}

int format_by_name(const char *name)
{
    int n;

    builtin();
    for (n = 0; n < g_count; n++)
        if (!strcmp(g_format[n].name, name))
            return n;
    return -1;
}

int format_of_uri(const char *uri, const char **worker_uri)
{
    int n, found = -1;

    builtin();
    for (n = 0; n < g_count; n++)
    {
        if (g_format[n].prefix && !strncmp(uri, g_format[n].prefix, strlen(g_format[n].prefix)))
        {
            found = n;
            break;
        }
        if (g_format[n].fallback)
            found = n;
    }
    if (worker_uri)
        *worker_uri = found >= 0 && g_format[found].strip_prefix && g_format[found].prefix &&
                              !strncmp(uri, g_format[found].prefix, strlen(g_format[found].prefix))
                          ? uri + strlen(g_format[found].prefix)
                          : uri;
    return found;
}

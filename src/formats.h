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

#ifndef FORMATS_H
#define FORMATS_H

#include <stddef.h>

#include "conf.h"
#include "names.h"

#define FORMATS_MAX 8

/* One row per plugin format. Everything the daemon does differently for a format is a field of its row: the protocol, the
 * supervisor and the pins read the row and never ask which format it is. A format joins with a row and its worker. */
typedef struct FORMAT_T {
    const char *name;               /* the word of policy_set, worker_env and worker_list; not "*", "all" or "-" */
    const char *prefix;             /* the uri says it is this format with this prefix; NULL for none */
    int strip_prefix;               /* the worker is given the uri without the prefix */
    int fallback;                   /* the format of a uri no prefix claims; one format only */

    const char *(*worker)(const conf_t *conf);  /* the program that serves it */
    const char *(*search)(const conf_t *conf);  /* where its plugins are searched, NULL for nowhere */
    const char *world_env;                      /* the worker's variable for the search path, NULL for none */
    /* a directory under `dir` that makes the worker's world the one plugin's, malloc'd; NULL for the whole search path */
    char *(*narrow_world)(const conf_t *conf, const char *dir, const char *uri);

    /* the root and the relative files a host loads for the uri: what a pin holds. SUCCESS, or
     * PHD_ERR_PIN_BINARY_MISMATCH with the reason on stderr for what cannot be pinned */
    int (*pin_collect)(const char *uri, const char *search, char *root, size_t size, names_t *files);
    int layout_check;               /* the worker takes pin_expect before the add and pin_layout after it */
    int pinned_own_only;            /* a pinned plugin runs in a worker of its own: the pin holds in no shared world */

    int native_instance_verbs;      /* the worker answers PHD_INSTANCE_VERBS; 0: the daemon does */
    char *(*param_info)(int id, const char *symbol);    /* the daemon's param_info, needed when it answers */
} format_t;

/* The two built-in rows are in the table from the start. A row added later is copied; its index is returned, or -1 with
 * the missing or wrong field named on stderr: a row without a capability is refused, never half-registered. */
int formats_register(const format_t *format);

int formats_count(void);
const format_t *format_at(int index);

/* the format of a name of the table, or -1 */
int format_by_name(const char *name);

/* the format a uri belongs to, and in *worker_uri the uri as the worker is given it */
int format_of_uri(const char *uri, const char **worker_uri);

/* the pin root and files of a CLAP: the directory of the .clap and the file */
int clap_pin_collect(const char *uri, const char *search, char *root, size_t size, names_t *files);

/* the LV2 format's parts, in lv2.c */
int lv2_pin_collect(const char *uri, const char *search, char *root, size_t size, names_t *files);
char *lv2_narrow_world(const conf_t *conf, const char *dir, const char *uri);
char *lv2_param_info(int id, const char *symbol);

#endif

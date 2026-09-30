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

#ifndef CONF_H
#define CONF_H

#include <limits.h>

typedef struct CONF_T {
    char mod_host[PATH_MAX];
    char clap_host[PATH_MAX];
    char lv2_path[PATH_MAX * 2];
    char state_root[PATH_MAX];
    int ready_timeout_ms;
    int rpc_timeout_ms;
    int backoff_base_ms;
    int backoff_max_ms;
    int storm_deaths;
    int storm_window_ms;
    int suspect_window_ms;
    int checkpoint_ms;
    int idle_ms;
    int pool_max;
} conf_t;

/* Defaults, then the file: one "key value" per line, '#' starts a comment.
 * A missing file is an error only when the path was asked for. */
void conf_defaults(conf_t *conf);
int conf_load(conf_t *conf, const char *path, int required);

#endif

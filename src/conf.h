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

#ifndef CONF_H
#define CONF_H

#include <limits.h>
#include <stdio.h>
#include <string.h>

#include <plugin-hostd/protocol.h>

#define CONF_SIZE_word 32
#define CONF_SIZE_path PATH_MAX
#define CONF_SIZE_pathlist (PATH_MAX * 2)

typedef struct CONF_T {
#define X(key, size, def, env, meaning) char key[CONF_SIZE_##size];
    PHD_CONF_STRINGS(X)
#undef X
#define X(key, def, unit, meaning) int key;
    PHD_CONF_INTS(X)
#undef X
} conf_t;

/* Defaults, then the file: one "key value" per line, '#' starts a comment.
 * A missing file is an error only when the path was asked for. */
void conf_defaults(conf_t *conf);
int conf_load(conf_t *conf, const char *path, int required);
/* once, after the file: lv2_extra is searched after lv2_path, so lv2_path becomes both */
int conf_merge_extra(conf_t *conf);

/* whether the settings are consistent: pin_mode is one of PHD_PIN_MODES, placement one of PHD_CORE_PLACEMENTS; 0, or -1 with the reason on stderr */
int conf_check(const conf_t *conf);
/* whether pin_mode is first-use */
int conf_pins_first_use(const conf_t *conf);
/* whether placement is spread */
int conf_spread(const conf_t *conf);
/* whether grouping is on */
int conf_grouping_on(const conf_t *conf);

/* The programs a user can name to run LV2 plugins (lv2_worker, lv2_worker_set): mod-host or omx-clap-host. A plugin one
 * of them refuses is reported with its code and never handed to the other: the user chooses the program, the daemon
 * does not. There is no third word that picks one for the user. */
static const char *const conf_lv2_workers[] = { PHD_LV2_WORKER_MOD_HOST, PHD_LV2_WORKER_CLAP_HOST };

/* whether `word` names one of them */
static inline int conf_lv2_worker_valid(const char *word)
{
    size_t n;

    for (n = 0; n < sizeof(conf_lv2_workers) / sizeof(*conf_lv2_workers); n++)
        if (!strcmp(word, conf_lv2_workers[n]))
            return 1;
    return 0;
}

/* those words, each after a blank, on `out` */
static inline void conf_lv2_workers_print(FILE *out)
{
    size_t n;

    for (n = 0; n < sizeof(conf_lv2_workers) / sizeof(*conf_lv2_workers); n++)
        fprintf(out, " %s", conf_lv2_workers[n]);
}

#endif

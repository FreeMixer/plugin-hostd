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

#include "conf.h"

void conf_defaults(conf_t *conf)
{
    const char *env;

    memset(conf, 0, sizeof(*conf));
#define X(key, size, def, envname, meaning) \
    env = *(envname) ? getenv(envname) : NULL; \
    snprintf(conf->key, sizeof(conf->key), "%s", env && *env ? env : def);
    PHD_CONF_STRINGS(X)
#undef X
#define X(key, def, unit, meaning) conf->key = def;
    PHD_CONF_INTS(X)
#undef X
}

static int set_string(char *dest, size_t size, const char *value)
{
    if (strlen(value) >= size)
        return -1;
    strcpy(dest, value);
    return 0;
}

static int set_key(conf_t *conf, const char *key, const char *value)
{
#define X(name, size, def, env, meaning) \
    if (!strcmp(key, #name)) \
        return set_string(conf->name, sizeof(conf->name), value);
    PHD_CONF_STRINGS(X)
#undef X
#define X(name, def, unit, meaning) \
    if (!strcmp(key, #name)) \
    { \
        conf->name = atoi(value); \
        return 0; \
    }
    PHD_CONF_INTS(X)
#undef X
    return -1;
}

int conf_load(conf_t *conf, const char *path, int required)
{
    char line[PATH_MAX * 2 + 64];
    FILE *file = fopen(path, "r");
    int lineno = 0;

    if (!file)
    {
        if (required)
            fprintf(stderr, "can't open %s\n", path);
        return required ? -1 : 0;
    }
    while (fgets(line, sizeof(line), file))
    {
        char *key = line, *value, *end;

        lineno++;
        while (*key == ' ' || *key == '\t')
            key++;
        if (*key == '#' || *key == '\n' || *key == '\0')
            continue;
        value = key;
        while (*value && *value != ' ' && *value != '\t' && *value != '\n')
            value++;
        if (*value)
            *value++ = '\0';
        while (*value == ' ' || *value == '\t')
            value++;
        end = value + strlen(value);
        while (end > value && (end[-1] == '\n' || end[-1] == ' ' || end[-1] == '\t'))
            *--end = '\0';
        if (set_key(conf, key, value) != 0)
        {
            fprintf(stderr, "%s:%d: bad setting '%s'\n", path, lineno, key);
            fclose(file);
            return -1;
        }
    }
    fclose(file);
    return 0;
}

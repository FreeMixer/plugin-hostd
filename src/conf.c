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
    const char *lv2 = getenv("LV2_PATH");
    const char *runtime = getenv("XDG_RUNTIME_DIR");

    memset(conf, 0, sizeof(*conf));
    snprintf(conf->mod_host, sizeof(conf->mod_host), "mod-host");
    snprintf(conf->clap_host, sizeof(conf->clap_host), "omx-clap-host");
    snprintf(conf->lv2_path, sizeof(conf->lv2_path), "%s",
             lv2 && *lv2 ? lv2 : "/usr/lib64/lv2:/usr/lib/lv2:/usr/local/lib/lv2");
    snprintf(conf->state_root, sizeof(conf->state_root), "%s", runtime && *runtime ? runtime : "/tmp");
    conf->ready_timeout_ms = 5000;
    conf->rpc_timeout_ms = 5000;
    conf->backoff_base_ms = 250;
    conf->backoff_max_ms = 5000;
    conf->storm_deaths = 5;
    conf->storm_window_ms = 60000;
    conf->checkpoint_ms = 5000;
    conf->idle_ms = 25;
    conf->pool_max = 8;
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
    if (!strcmp(key, "mod_host"))
        return set_string(conf->mod_host, sizeof(conf->mod_host), value);
    if (!strcmp(key, "clap_host"))
        return set_string(conf->clap_host, sizeof(conf->clap_host), value);
    if (!strcmp(key, "lv2_path"))
        return set_string(conf->lv2_path, sizeof(conf->lv2_path), value);
    if (!strcmp(key, "state_root"))
        return set_string(conf->state_root, sizeof(conf->state_root), value);
    if (!strcmp(key, "ready_timeout_ms"))
        conf->ready_timeout_ms = atoi(value);
    else if (!strcmp(key, "rpc_timeout_ms"))
        conf->rpc_timeout_ms = atoi(value);
    else if (!strcmp(key, "backoff_base_ms"))
        conf->backoff_base_ms = atoi(value);
    else if (!strcmp(key, "backoff_max_ms"))
        conf->backoff_max_ms = atoi(value);
    else if (!strcmp(key, "storm_deaths"))
        conf->storm_deaths = atoi(value);
    else if (!strcmp(key, "storm_window_ms"))
        conf->storm_window_ms = atoi(value);
    else if (!strcmp(key, "checkpoint_ms"))
        conf->checkpoint_ms = atoi(value);
    else if (!strcmp(key, "idle_ms"))
        conf->idle_ms = atoi(value);
    else if (!strcmp(key, "pool_max"))
        conf->pool_max = atoi(value);
    else
        return -1;
    return 0;
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

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

#ifndef NAMES_H
#define NAMES_H

#include <stdlib.h>
#include <string.h>

/* a list of names: the files a format loads for a plugin */
typedef struct NAMES_T {
    char **name;
    int n;
} names_t;

/* 0, or -1 with the list as it was when memory runs out */
static inline int names_add(names_t *names, const char *name)
{
    char **grown = realloc(names->name, (names->n + 1) * sizeof(char *));
    char *copy;

    if (!grown)
        return -1;
    names->name = grown;
    copy = strdup(name);
    if (!copy)
        return -1;
    names->name[names->n++] = copy;
    return 0;
}

static inline int names_has(const names_t *names, const char *name)
{
    int n;

    for (n = 0; n < names->n; n++)
        if (!strcmp(names->name[n], name))
            return 1;
    return 0;
}

static inline void names_free(names_t *names)
{
    while (names->n)
        free(names->name[--names->n]);
    free(names->name);
    names->name = NULL;
}

#endif

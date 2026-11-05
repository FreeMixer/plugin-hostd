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

#include <stdlib.h>
#include <string.h>

#include <utils.h>

#include "words.h"

int words_read(char *line, char **tok, int max)
{
    char *p, **list;
    int n = 0, quote = 0;

    while (*line == ' ' || *line == '\t' || *line == '\r' || *line == '\n')
        line++;
    /* blanks outside quotes are spaces, which the protocol's reader splits at; inside quotes they are the word's own */
    for (p = line; *p; p++)
    {
        if (*p == '\\' && p[1] == '"')
            p++;
        else if (*p == '"')
            quote = !quote;
        else if (!quote && (*p == '\t' || *p == '\r' || *p == '\n'))
            *p = ' ';
    }
    if (!*line)
        return 0;
    list = strarr_split(line);
    if (!list)
        return -1;
    for (n = 0; list[n] && n < max; n++)
        tok[n] = list[n];
    free(list);
    return n;
}

int words_need_quotes(const char *word)
{
    return !*word || strpbrk(word, " \t\r\n\"") != NULL;
}

size_t words_write(const char *word, char *buf, size_t size)
{
    size_t need = 0, used = 0;
    const char *p;
    int quoted = words_need_quotes(word);

    if (quoted)
        need++;
    for (p = word; *p; p++)
        need += (quoted && *p == '"') ? 2 : 1;
    if (quoted)
        need++;
    if (!size)
        return need;
    if (quoted && used + 1 < size)
        buf[used++] = '"';
    for (p = word; *p && used + 1 < size; p++)
    {
        if (quoted && *p == '"' && used + 2 < size)
            buf[used++] = '\\';
        buf[used++] = *p;
    }
    if (quoted && used + 1 < size)
        buf[used++] = '"';
    buf[used] = '\0';
    return need;
}

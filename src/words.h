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

#ifndef WORDS_H
#define WORDS_H

#include <stddef.h>

/* The words of a line, as the protocol reads them (plugin-hostd-protocol, grammar: word = quoted / bare-word): split at
 * spaces and tabs, a word in double quotes may hold spaces and has \" for a quote, and the quotes are not part of the
 * value. The reading is the protocol library's (strarr_split); this only makes tabs and line ends spaces first. */

/* Cut `line` into at most `max` words, tok[n] pointing into it, and answer how many; -1 when there is no memory. The
 * line is changed. Leading and trailing blanks are no words. */
int words_read(char *line, char **tok, int max);

/* Whether a word has to be quoted to be read back as one: it is empty, or holds a blank or a quote. */
int words_need_quotes(const char *word);

/* `word` as it is written in a line: itself, or in quotes with \" for a quote when it needs them. Written in buf,
 * NUL-terminated; answers the length it needs (NUL excluded), the word cut when buf is too small. */
size_t words_write(const char *word, char *buf, size_t size);

#endif

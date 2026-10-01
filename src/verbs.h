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

#ifndef VERBS_H
#define VERBS_H

#include <string.h>

#include <utils.h>

/* mod-host.h declares each command as a format; its verb is the first word of the format */
static inline int verb_len(const char *format)
{
    return (int)strcspn(format, " ");
}

/* whether the first word of text, a token or a whole command line, is the verb of format */
static inline int verb_is(const char *text, const char *format)
{
    size_t n = strcspn(format, " ");

    return strcspn(text, " \t") == n && !strncmp(text, format, n);
}

/* the socket's receive callback: one message in, one reply out */
void verbs_receive(msg_t *msg);

/* set by QUIT: the main loop stops */
extern volatile int g_quitting;

#endif

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

#ifndef SESSION_H
#define SESSION_H

#include <stddef.h>

/* The controller's session (plugin-hostd-protocol, doc/protocol.md, Sessions): what its last hello granted of the
 * extensions tags, errors and seq. A controller that never sends hello is answered as mod-host answers it. */

/* a new controller: nothing is granted */
void session_reset(void);

/* hello <version> [<extension> ...]: the answer, malloc'd; NULL when there is no memory */
char *session_hello(char **tok, int ntok);

/* the length of the request tag a line starts with ("@" and tag characters, then a space or the end), 0 when the line
 * has none or the session was not granted tags */
size_t session_tag_len(const char *line);

/* the text of an answer, taken and freed, as the session sends it: a refusal alone followed by its error word under
 * errors, after the tag (its first tag_len bytes) and one space under tags. NULL when there is no memory. */
char *session_answer(char *text, const char *tag, size_t tag_len);

/* what a feedback line starts with, "#<n> " under seq, else nothing; written NUL-terminated in buf, its length */
size_t session_feedback_prefix(char *buf, size_t size);

#endif

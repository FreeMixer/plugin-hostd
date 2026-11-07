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

#ifndef WRITER_H
#define WRITER_H

#include <stddef.h>

/* The daemon's files on disk (the history, the pin store and its accepted list, the descriptors) are written by one
 * thread of their own, first in first out, so the command loop never waits on the disk. The loop hands over a copy of
 * the bytes and goes on; nothing the loop changes afterwards is read by the writer. docs/durable-writes.md has the rules
 * and why. */

/* what the loop is told when a write ends: on the loop's thread, in the order the writes were handed over; err is 0 or
 * the errno of the step that failed */
typedef void (*writer_done_fn)(void *arg, int err);

/* a periodic snapshot: while it waits it is replaced by a later one of the same file, the latest wins */
#define WRITER_COALESCE 1

/* at most this many writes wait, holding at most this many bytes; a write past either is refused */
#define WRITER_JOBS_MAX  64
#define WRITER_BYTES_MAX (64u << 20)

/* the thread; before it starts, and after writer_finish, a write is done at once on the caller's thread */
int writer_start(void);

/* drains what is queued, says each end, and stops the thread */
void writer_finish(void);

/* bytes as the whole of path; the writer owns bytes (malloc'd) from here, also on a refusal. 0, or -1 when the queue
 * is full (WRITER_JOBS_MAX or WRITER_BYTES_MAX), in which case nothing is written and done is not called. what is the
 * line said when the write fails, after "plugin-hostd: can't write ": a format of the path and the reason, in that
 * order (two %s), as "the history %s: %s; it is kept in memory" */
int writer_put(const char *path, char *bytes, size_t len, int flags, writer_done_fn done, void *arg, const char *what);

/* tmp fsynced and renamed to final, final kept if it is there; the same refusal and the same end as writer_put */
int writer_place(const char *tmp, const char *final, writer_done_fn done, void *arg, const char *what);

/* on the loop: the ends the thread has reached since the last call, each told to its done */
void writer_poll(void);

/* writes handed over whose end the loop has not been told yet (writer_poll) */
int writer_busy(void);

/* blocks the loop until nothing waits (quit only), then says the ends */
void writer_drain(void);

/* the writes a verb that promises them hands over are a group: begin before the verb, end after it. end answers 0
 * when the verb handed over nothing or promises nothing (its writes are best effort, said on failure, and its reply does
 * not wait), -1 when one of its writes was refused, else the group, whose state writer_group asks */
void writer_verb_begin(int promises);
int writer_verb_end(void);

/* 0 while a write of the group waits, else 1 with *err the errno of its first failure (0 when all landed); a group
 * answered 1 is forgotten */
int writer_group(int group, int *err);

/* a group nobody will ask about again (its controller is gone): forgotten once its writes end */
void writer_forget(int group);

#endif

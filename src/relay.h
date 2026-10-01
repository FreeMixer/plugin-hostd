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

#ifndef RELAY_H
#define RELAY_H

/* The daemon's feedback port, and the workers' feedback read on a thread of its own and written to it (PHD_RELAY in
 * include/plugin-hostd/protocol.h). The daemon's own events and the workers' lines share one writer, so no two lines
 * are ever cut into each other. */

/* Listen on `port`, 0 for none, and start the thread that reads the workers. */
int relay_start(int port);
void relay_finish(void);

/* Before the first command of a controller: wait for it to open the feedback port, as mod-host does, until *running
 * goes to 0. Returns at once when there is no feedback port or a controller is on it already. */
void relay_await_controller(volatile int *running);

/* The controller went away: its feedback connection is closed, and the next controller opens its own. */
void relay_controller_gone(void);

/* One line of the daemon's own, an event, to the controller. */
void relay_event(const char *line);

/* A worker's feedback socket: read from now on. */
void relay_add(int fd);

/* A worker's feedback socket, closed: what the worker wrote before it is read and sent first. */
void relay_remove(int fd);

#endif

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

/* Between plugin-hostd-probe and its lock preload (src/probe_lock.c): memory locks do not survive an exec, so the
 * measured child takes its own, in the constructor of a library the runner preloads into it and into nothing else.
 * The runner names a pipe in PROBE_LOCK_FD_ENV; the preload writes one probe_lock_report_t on it and closes it. */

#ifndef PLUGIN_HOSTD_PROBE_LOCK_H
#define PLUGIN_HOSTD_PROBE_LOCK_H

#define PROBE_LOCK_FD_ENV "PLUGIN_HOSTD_PROBE_LOCK_FD"
/* the descriptor the runner gives the child for it, beside the step records on 3 */
#define PROBE_LOCK_FD 4

typedef struct
{
    int locked; /* 1 when mlockall(MCL_CURRENT | MCL_FUTURE) returned 0 */
    int error;  /* its errno otherwise */
} probe_lock_report_t;

#endif

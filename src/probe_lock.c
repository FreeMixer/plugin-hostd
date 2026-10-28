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

/* The lock preload of plugin-hostd-probe: the runner preloads it into the measured child only, beside the interposer,
 * with PROBE_LOCK_FD_ENV naming a pipe. Before the child's main, it locks every page the process has and will have,
 * mlockall(MCL_CURRENT | MCL_FUTURE), within the RLIMIT_MEMLOCK the runner left it, so no page fault enters the timed
 * blocks; and it writes the result on the pipe. It interposes no symbol. A process the child starts later inherits the
 * preload but not the variable, so it does nothing there. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

#include "probe_lock.h"

__attribute__((constructor)) static void probe_lock(void)
{
    const char *fd_text = getenv(PROBE_LOCK_FD_ENV);
    probe_lock_report_t report = { 0, 0 };
    char *end;
    long fd;

    if (fd_text == NULL)
        return;
    fd = strtol(fd_text, &end, 10);
    unsetenv(PROBE_LOCK_FD_ENV);
    if (*end || fd < 0)
        return;
    if (mlockall(MCL_CURRENT | MCL_FUTURE) == 0)
        report.locked = 1;
    else
        report.error = errno;
    if (write((int)fd, &report, sizeof(report)) < 0)
        report.error = errno;
    close((int)fd);
}

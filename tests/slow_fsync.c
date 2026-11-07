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

/* LD_PRELOAD into the daemon: every fsync and fdatasync takes FSYNC_DELAY_MS milliseconds, as a disk under contention
 * can, and FSYNC_MARK (a file) gets "begin" when one starts and "end" when it returns, so a test can tell a write is in
 * flight. With neither set it changes nothing. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static void mark(const char *word)
{
    const char *path = getenv("FSYNC_MARK");
    int fd;

    if (!path || !*path || (fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644)) < 0)
        return;
    if (write(fd, word, strlen(word)) < 0)
        (void)0;
    close(fd);
}

static void slow(void)
{
    const char *ms = getenv("FSYNC_DELAY_MS");
    long n = ms ? atol(ms) : 0;
    struct timespec t;

    if (n <= 0)
        return;
    t.tv_sec = n / 1000;
    t.tv_nsec = (n % 1000) * 1000000L;
    while (nanosleep(&t, &t) != 0)
        ;
}

/* exported whatever -fvisibility the build uses: an interposer that is hidden interposes nothing */
__attribute__((visibility("default"))) int fsync(int fd)
{
    static int (*real)(int);
    int rc;

    if (!real)
        real = (int (*)(int))dlsym(RTLD_NEXT, "fsync");
    mark("begin\n");
    slow();
    rc = real(fd);
    mark("end\n");
    return rc;
}

__attribute__((visibility("default"))) int fdatasync(int fd)
{
    static int (*real)(int);
    int rc;

    if (!real)
        real = (int (*)(int))dlsym(RTLD_NEXT, "fdatasync");
    mark("begin\n");
    slow();
    rc = real(fd);
    mark("end\n");
    return rc;
}

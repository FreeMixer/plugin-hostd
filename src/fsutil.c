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

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "fsutil.h"

int fs_mkdir_parents(char *path)
{
    char *slash;

    for (slash = path + 1; (slash = strchr(slash, '/')); slash++)
    {
        *slash = '\0';
        if (mkdir(path, 0700) != 0 && errno != EEXIST)
        {
            *slash = '/';
            return -1;
        }
        *slash = '/';
    }
    return 0;
}

void fs_sync_dir(const char *path)
{
    char dir[PATH_MAX + 8], *slash;
    int fd;

    snprintf(dir, sizeof(dir), "%s", path);
    slash = strrchr(dir, '/');
    if (!slash)
        snprintf(dir, sizeof(dir), ".");
    else if (slash == dir)
        dir[1] = '\0';
    else
        *slash = '\0';
    fd = open(dir, O_RDONLY | O_DIRECTORY);
    if (fd >= 0)
    {
        fsync(fd);
        close(fd);
    }
}

int fs_write_atomic(const char *path, const char *bytes, size_t len)
{
    char tmp[PATH_MAX + 16];
    size_t done = 0;
    int fd, err = 0;

    if (snprintf(tmp, sizeof(tmp), "%s.XXXXXX", path) >= (int)sizeof(tmp))
        return ENAMETOOLONG;
    if (fs_mkdir_parents(tmp) != 0 || (fd = mkstemp(tmp)) < 0)
        return errno;
    while (done < len)
    {
        ssize_t n = write(fd, bytes + done, len - done);

        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
        {
            err = n < 0 ? errno : EIO;
            break;
        }
        done += (size_t)n;
    }
    if (!err && fsync(fd) != 0)
        err = errno;
    if (close(fd) != 0 && !err)
        err = errno;
    if (!err && rename(tmp, path) != 0)
        err = errno;
    if (err)
    {
        unlink(tmp);
        return err;
    }
    fs_sync_dir(path);
    return 0;
}

int fs_into_place(const char *tmp, const char *final)
{
    int fd, err = 0;

    if ((fd = open(tmp, O_RDONLY | O_CLOEXEC)) < 0)
        return errno;
    if (fsync(fd) != 0)
        err = errno;
    close(fd);
    if (err)
        return err;
    if (access(final, F_OK) == 0)
    {
        unlink(tmp);
        return 0;
    }
    if (rename(tmp, final) != 0)
        return errno;
    fs_sync_dir(final);
    return 0;
}

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

#include <arpa/inet.h>
#include <netinet/in.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "listen.h"

static int g_port;
static struct in_addr g_address;

int listen_set_command_port(int port, const char *address)
{
    if (inet_pton(AF_INET, address, &g_address) != 1)
        return -1;
    g_port = port;
    return 0;
}

/* libmod-host-protocol opens the command port and takes no address in the releases this daemon runs against (the floor in
 * packaging/plugin-hostd.spec), so the library's call to bind() comes here: an executable's definition is found ahead of
 * the C library's. Nothing else in this process binds that port. main() checks the outcome against /proc/net/tcp before
 * its ready line, so a library that reaches bind() some other way is a daemon that does not start. */
__attribute__((visibility("default")))
int bind(int fd, const struct sockaddr *addr, socklen_t len)
{
    if (g_port && addr->sa_family == AF_INET && len >= sizeof(struct sockaddr_in))
    {
        struct sockaddr_in in;

        memcpy(&in, addr, sizeof(in));
        if (ntohs(in.sin_port) == g_port)
        {
            in.sin_addr = g_address;
            return (int)syscall(SYS_bind, fd, &in, sizeof(in));
        }
    }
    return (int)syscall(SYS_bind, fd, addr, len);
}

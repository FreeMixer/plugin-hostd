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

/* src/relay.c when memory runs out. The relay is built for this test with its realloc calls renamed to
 * relay_test_realloc (see the Makefile), so the test decides which allocation fails. A worker's feedback socket the
 * relay cannot follow must not stay open and unread: the worker would block on its next write into a full socket. */

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/sockios.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "relay.h"

static int failures, checks;

/* how many reallocs succeed before the next one fails; -1 is never */
static volatile int g_fail_after = -1;
/* how many reallocs were refused */
static volatile int g_refused;

void *relay_test_realloc(void *ptr, size_t size);

void *relay_test_realloc(void *ptr, size_t size)
{
    if (g_fail_after == 0)
    {
        __atomic_add_fetch(&g_refused, 1, __ATOMIC_SEQ_CST);
        return NULL;
    }
    if (g_fail_after > 0)
        g_fail_after--;
    return realloc(ptr, size);
}

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL relay: %s\n", what);
    }
}

static int fd_open(int fd)
{
    return fcntl(fd, F_GETFD) != -1 || errno != EBADF;
}

/* the worker's end of its feedback socket: write until the relay's end is gone (EPIPE or ECONNRESET), or until the
 * socket is full and stays full (EAGAIN for `ms`), which is the worker blocked */
static int worker_writes_until(int fd, int ms)
{
    char chunk[4096];
    struct timespec start, now;

    memset(chunk, 'x', sizeof(chunk));
    chunk[sizeof(chunk) - 1] = '\0';
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (;;)
    {
        ssize_t n = send(fd, chunk, sizeof(chunk), MSG_NOSIGNAL | MSG_DONTWAIT);

        if (n < 0 && (errno == EPIPE || errno == ECONNRESET))
            return 0;
        if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK)
            return -2;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if ((now.tv_sec - start.tv_sec) * 1000 + (now.tv_nsec - start.tv_nsec) / 1000000 > ms)
            return -1;
        if (n < 0)
            usleep(1000);
    }
}

/* the relay has read everything the worker wrote to `fd`'s peer, within `ms` */
static int read_within(int fd, int ms)
{
    int waited, queued = -1;

    for (waited = 0; waited <= ms; waited++)
    {
        if (ioctl(fd, SIOCOUTQ, &queued) == 0 && queued == 0)
            return 1;
        usleep(1000);
    }
    return 0;
}

/* no memory for the relay's table (the caller has armed the failure): relay_add says so, and the socket is closed, so the worker is not left writing
 * into a socket no one reads */
static void table_allocation_fails(void)
{
    int sv[2], waited;

    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sv) != 0)
    {
        check(0, "socketpair");
        return;
    }
    check(relay_add(sv[0]) != 0, "relay_add answers a failure when its table cannot grow");
    /* the thread is refused its poll set too before memory comes back: one refusal is relay_add's, the next its */
    for (waited = 0; waited < 2000 && __atomic_load_n(&g_refused, __ATOMIC_SEQ_CST) < 2; waited++)
        usleep(1000);
    check(g_refused >= 2, "the relay's thread asked for its poll set while there was no memory");
    g_fail_after = -1;
    check(!fd_open(sv[0]), "the feedback socket it could not follow is closed");
    check(worker_writes_until(sv[1], 500) == 0, "the worker's write fails at once instead of filling the socket");
    close(sv[1]);
}

/* positive control: with memory, the socket is followed and stays open, and the worker can write to it */
static void table_allocation_succeeds(int *kept)
{
    int sv[2];

    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sv) != 0)
    {
        check(0, "socketpair");
        return;
    }
    check(relay_add(sv[0]) == 0, "positive control: relay_add follows a socket when it has the memory");
    check(fd_open(sv[0]), "positive control: the socket it follows stays open");
    check(send(sv[1], "ok", 3, MSG_NOSIGNAL | MSG_DONTWAIT) == 3, "positive control: the worker's write goes through");
    check(read_within(sv[1], 2000), "positive control: the relay's thread, given memory again, reads what the worker wrote");
    kept[0] = sv[0];
    kept[1] = sv[1];
}

/* no memory to read the worker into: the relay stops reading it and says so to the worker, whose writes fail
 * instead of blocking; the socket itself stays the supervisor's to close */
static void read_buffer_allocation_fails(void)
{
    int sv[2];

    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sv) != 0)
    {
        check(0, "socketpair");
        return;
    }
    /* the table and the thread's poll set have room from the control above, so the next realloc is the read
     * buffer's; reaching it also shows the thread came back once there was memory */
    g_fail_after = 0;
    check(relay_add(sv[0]) == 0, "relay_add follows the socket (its table needs no memory)");
    check(worker_writes_until(sv[1], 2000) == 0, "the worker's writes fail once the relay cannot read it, they do not block");
    g_fail_after = -1;
    check(fd_open(sv[0]), "the socket stays open until the supervisor removes it");
    relay_remove(sv[0]);
    close(sv[1]);
}

int main(void)
{
    int kept[2] = { -1, -1 };

    /* no memory from the start: the relay's thread gets none for its poll set either, and must wait for some */
    g_fail_after = 0;
    if (relay_start(0, NULL) != 0)
    {
        printf("FAIL relay: relay_start\n");
        return 1;
    }
    table_allocation_fails();
    table_allocation_succeeds(kept);
    read_buffer_allocation_fails();
    if (kept[0] >= 0)
    {
        relay_remove(kept[0]);
        close(kept[1]);
    }
    relay_finish();
    printf("relay: %d checks, %s\n", checks, failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}

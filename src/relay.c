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
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "relay.h"

/* a worker line longer than this, with no NUL in it, is not a line of the protocol: it is dropped */
#define LINE_LIMIT (1024 * 1024)

typedef struct SOURCE_T {
    int fd;
    int eof;                    /* the worker closed it: not polled again, closed when the supervisor says so */
    char *buf;
    size_t used, cap;
} source_t;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_t g_thread;
static int g_thread_up;
static volatile int g_stop;
static int g_listen = -1;
static int g_client = -1;
static int g_client_broken;
static int g_wake[2] = { -1, -1 };
static source_t *g_src;
static int g_nsrc, g_capsrc;

/* one NUL-terminated line to the controller, whole or not at all; g_lock is held */
static void send_line(const char *line, size_t len)
{
    size_t sent = 0;

    if (g_client < 0 || g_client_broken)
        return;
    while (sent < len)
    {
        ssize_t n = send(g_client, line + sent, len - sent, MSG_NOSIGNAL);

        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
        {
            /* the controller closed its feedback port: nothing more goes to it until the next one opens its own */
            g_client_broken = 1;
            return;
        }
        sent += n;
    }
}

/* everything the worker has written so far, its complete lines sent in order; g_lock is held */
static void drain(source_t *s)
{
    for (;;)
    {
        ssize_t n;
        char *start, *nul;

        if (s->cap - s->used < 4096)
        {
            s->cap = s->cap ? s->cap * 2 : 8192;
            s->buf = realloc(s->buf, s->cap);
        }
        n = recv(s->fd, s->buf + s->used, s->cap - s->used, MSG_DONTWAIT);
        if (n < 0 && errno == EINTR)
            continue;
        if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK))
            s->eof = 1;
        if (n <= 0)
            return;
        s->used += n;
        start = s->buf;
        while ((nul = memchr(start, '\0', s->used - (start - s->buf))))
        {
            send_line(start, nul - start + 1);
            start = nul + 1;
        }
        s->used -= start - s->buf;
        memmove(s->buf, start, s->used);
        if (s->used > LINE_LIMIT)
            s->used = 0;
    }
}

static void wake(void)
{
    char c = 0;

    /* a full pipe means the thread is awake already */
    if (g_wake[1] >= 0 && write(g_wake[1], &c, 1) < 0)
        return;
}

static void *relay_thread(void *arg)
{
    struct pollfd *pfd = NULL;
    int cap = 0;

    (void)arg;
    while (!g_stop)
    {
        int n, count = 1, i;

        pthread_mutex_lock(&g_lock);
        if (cap < g_nsrc + 1)
        {
            cap = g_nsrc + 16;
            pfd = realloc(pfd, cap * sizeof(*pfd));
        }
        pfd[0].fd = g_wake[0];
        pfd[0].events = POLLIN;
        for (i = 0; i < g_nsrc; i++)
            if (!g_src[i].eof)
            {
                pfd[count].fd = g_src[i].fd;
                pfd[count].events = POLLIN;
                count++;
            }
        pthread_mutex_unlock(&g_lock);

        n = poll(pfd, count, -1);
        if (n < 0)
            continue;
        if (pfd[0].revents)
        {
            char junk[64];

            while (read(g_wake[0], junk, sizeof(junk)) > 0)
                ;
        }
        pthread_mutex_lock(&g_lock);
        for (i = 1; i < count; i++)
        {
            int k;

            if (!pfd[i].revents)
                continue;
            /* the supervisor may have closed it since: only a socket still in the table is read */
            for (k = 0; k < g_nsrc; k++)
                if (g_src[k].fd == pfd[i].fd && !g_src[k].eof)
                {
                    drain(&g_src[k]);
                    break;
                }
        }
        pthread_mutex_unlock(&g_lock);
    }
    free(pfd);
    return NULL;
}

int relay_start(int port)
{
    if (pipe2(g_wake, O_NONBLOCK | O_CLOEXEC) != 0)
        return -1;
    if (port)
    {
        struct sockaddr_in addr;
        int one = 1;

        g_listen = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (g_listen < 0)
            return -1;
        setsockopt(g_listen, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        addr.sin_port = htons(port);
        if (bind(g_listen, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(g_listen, 4) < 0)
        {
            perror("feedback port");
            return -1;
        }
    }
    if (pthread_create(&g_thread, NULL, relay_thread, NULL) != 0)
        return -1;
    g_thread_up = 1;
    return 0;
}

void relay_finish(void)
{
    int i;

    if (g_thread_up)
    {
        g_stop = 1;
        wake();
        pthread_join(g_thread, NULL);
        g_thread_up = 0;
    }
    pthread_mutex_lock(&g_lock);
    for (i = 0; i < g_nsrc; i++)
    {
        close(g_src[i].fd);
        free(g_src[i].buf);
    }
    g_nsrc = 0;
    if (g_client >= 0)
        close(g_client);
    g_client = -1;
    if (g_listen >= 0)
        close(g_listen);
    g_listen = -1;
    pthread_mutex_unlock(&g_lock);
}

void relay_await_controller(volatile int *running)
{
    int have;

    if (g_listen < 0)
        return;
    pthread_mutex_lock(&g_lock);
    have = g_client >= 0;
    pthread_mutex_unlock(&g_lock);
    while (!have && *running)
    {
        struct pollfd p = { g_listen, POLLIN, 0 };
        int fd;

        if (poll(&p, 1, 100) <= 0)
            continue;
        fd = accept4(g_listen, NULL, NULL, SOCK_CLOEXEC);
        if (fd < 0)
            continue;
        pthread_mutex_lock(&g_lock);
        g_client = fd;
        g_client_broken = 0;
        pthread_mutex_unlock(&g_lock);
        have = 1;
    }
}

void relay_controller_gone(void)
{
    pthread_mutex_lock(&g_lock);
    if (g_client >= 0)
        close(g_client);
    g_client = -1;
    pthread_mutex_unlock(&g_lock);
}

void relay_event(const char *line)
{
    pthread_mutex_lock(&g_lock);
    send_line(line, strlen(line) + 1);
    pthread_mutex_unlock(&g_lock);
}

void relay_add(int fd)
{
    if (fd < 0)
        return;
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
    pthread_mutex_lock(&g_lock);
    if (g_nsrc == g_capsrc)
    {
        g_capsrc = g_capsrc ? g_capsrc * 2 : 16;
        g_src = realloc(g_src, g_capsrc * sizeof(source_t));
    }
    memset(&g_src[g_nsrc], 0, sizeof(source_t));
    g_src[g_nsrc++].fd = fd;
    pthread_mutex_unlock(&g_lock);
    wake();
}

void relay_remove(int fd)
{
    int i;

    if (fd < 0)
        return;
    pthread_mutex_lock(&g_lock);
    for (i = 0; i < g_nsrc; i++)
        if (g_src[i].fd == fd)
        {
            if (!g_src[i].eof)
                drain(&g_src[i]);
            free(g_src[i].buf);
            g_src[i] = g_src[--g_nsrc];
            break;
        }
    close(fd);
    pthread_mutex_unlock(&g_lock);
    wake();
}

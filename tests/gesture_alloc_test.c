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


/* src/relay.c's gesture table when memory runs out. The test includes the relay with its realloc calls renamed to
 * alloc_test_realloc (the Makefile's -Drealloc), so it decides which allocation fails. A begin that cannot be recorded
 * is dropped; what the table already holds stays. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../src/relay.c"

/* the C library's realloc, by its own symbol: the name realloc is renamed in this file */
void *libc_realloc(void *ptr, size_t size) __asm__("realloc");

static int failures, checks;

/* how many reallocs succeed before the next one fails; -1 is never */
static int g_fail_after = -1;

void *alloc_test_realloc(void *ptr, size_t size);

void *alloc_test_realloc(void *ptr, size_t size)
{
    if (g_fail_after == 0)
        return NULL;
    if (g_fail_after > 0)
        g_fail_after--;
    return libc_realloc(ptr, size);
}

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL gesture table: %s\n", what);
    }
}

int main(void)
{
    source_t s;

    memset(&s, 0, sizeof(s));
    gesture_seen(&s, "param_gesture 1 a begin");
    check(s.nheld == 1 && s.held && !strcmp(s.held[0], "param_gesture 1 a"), "positive control: a begin is held with memory");

    g_fail_after = 0;
    gesture_seen(&s, "param_gesture 1 b begin");
    g_fail_after = -1;
    check(s.nheld == 1, "a begin with no memory is dropped, the table does not grow");
    check(s.held && !strcmp(s.held[0], "param_gesture 1 a"), "the gesture held before is still there, whole");

    gesture_seen(&s, "param_gesture 1 a end");
    check(s.nheld == 0, "the held gesture still ends");

    memset(&s, 0, sizeof(s));
    g_fail_after = 0;
    gesture_seen(&s, "param_gesture 1 c begin");
    g_fail_after = -1;
    check(s.nheld == 0 && s.held == NULL, "a begin with no memory into an empty table holds nothing");
    gesture_seen(&s, "param_gesture 1 c end");
    check(s.nheld == 0, "the end of a gesture never held is none");

    gestures_end(&s);

    /* a held gesture longer than any fixed buffer is ended whole: its line up to the last word, then " end" */
    {
        char line[3000], want[3000], got[4096];
        int sv[2];
        ssize_t n;

        memset(&s, 0, sizeof(s));
        snprintf(line, sizeof(line), "param_gesture 1 %02000d begin", 0);
        gesture_seen(&s, line);
        check(s.nheld == 1, "positive control: a long begin is held");
        snprintf(want, sizeof(want), "param_gesture 1 %02000d end", 0);
        if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0)
        {
            perror("socketpair");
            return 1;
        }
        g_client = sv[0];
        g_client_broken = 0;
        gestures_end(&s);
        g_client = -1;
        n = recv(sv[1], got, sizeof(got), MSG_DONTWAIT);
        check(n == (ssize_t)strlen(want) + 1 && !memcmp(got, want, strlen(want) + 1),
              "the end of a 2000-byte gesture reaches the controller whole, with its end word and one NUL");
        close(sv[0]);
        close(sv[1]);
    }
    printf("gesture table: %d checks, %s\n", checks, failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}

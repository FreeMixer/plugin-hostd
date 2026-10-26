/* SPDX-License-Identifier: GPL-3.0-or-later */
/* src/verbs.c when memory runs out. The test includes the verbs with their strndup, strdup and free calls renamed to
 * alloc_test_strndup, alloc_test_strdup and alloc_test_free (the Makefile's -D), so it decides which copy fails and
 * sees which copies are freed; the rest of the daemon is linked as it is. A message the daemon has no memory to copy,
 * and an answer it has no memory for, are each answered once, with mod-host's ERR_MEMORY_ALLOCATION. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../src/verbs.c"

/* the C library's strndup, strdup and free, by their symbols: the names are renamed in this file */
char *libc_strndup(const char *s, size_t n) __asm__("strndup");
char *libc_strdup(const char *s) __asm__("strdup");
void libc_free(void *p) __asm__("free");

static int failures, checks;

/* how many copies succeed before the next one fails; -1 is never */
static int g_fail_after = -1;

/* the controller's end of the command socket, and the daemon's */
static int g_sv[2];

/* the copies the verbs made and have not freed */
static void *g_held[4];

static char *hold(char *p)
{
    size_t n;

    for (n = 0; p && n < sizeof(g_held) / sizeof(g_held[0]); n++)
        if (!g_held[n])
        {
            g_held[n] = p;
            break;
        }
    return p;
}

static int held(void)
{
    size_t n;
    int k = 0;

    for (n = 0; n < sizeof(g_held) / sizeof(g_held[0]); n++)
        k += g_held[n] != NULL;
    return k;
}

static int copy_fails(void)
{
    if (g_fail_after == 0)
        return 1;
    if (g_fail_after > 0)
        g_fail_after--;
    return 0;
}

char *alloc_test_strndup(const char *s, size_t n);
char *alloc_test_strdup(const char *s);
void alloc_test_free(void *p);

char *alloc_test_strndup(const char *s, size_t n)
{
    return copy_fails() ? NULL : hold(libc_strndup(s, n));
}

char *alloc_test_strdup(const char *s)
{
    return copy_fails() ? NULL : hold(libc_strdup(s));
}

void alloc_test_free(void *p)
{
    size_t n;

    for (n = 0; n < sizeof(g_held) / sizeof(g_held[0]); n++)
        if (g_held[n] == p)
            g_held[n] = NULL;
    libc_free(p);
}

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL verbs: %s\n", what);
    }
}

/* whether the controller has exactly `want` and its NUL to read, and nothing after it */
static int answered(const char *want)
{
    char got[64];
    ssize_t n = recv(g_sv[0], got, sizeof(got), MSG_DONTWAIT);

    return n == (ssize_t)strlen(want) + 1 && !memcmp(got, want, (size_t)n) && recv(g_sv[0], got, 1, MSG_DONTWAIT) < 0;
}

/* `text` sent by the controller, with `copies` copies of it made before the next one fails */
static void receive(const char *text, int copies)
{
    msg_t msg;

    msg.sender_id = g_sv[1];
    msg.data = (char *)text;
    msg.data_size = strlen(text);
    g_fail_after = copies;
    verbs_receive(&msg);
    g_fail_after = -1;
}

int main(void)
{
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, g_sv) != 0)
    {
        perror("socketpair");
        return 1;
    }

    receive(" \t\r\n", -1);
    check(answered("resp -902"), "positive control: a message of no words is refused with memory");
    check(!held(), "positive control: a message read whole frees both its copies");

    receive("quit", 0);
    check(answered("resp -901"), "a message with no memory for its line is answered once, with -901");
    check(!g_quitting, "a quit with no memory for its line does not quit");

    receive("quit", 1);
    check(answered("resp -901"), "a message with no memory for its words is answered once, with -901");
    check(!g_quitting, "a quit with no memory for its words does not quit");
    check(!held(), "a message with no memory for its words frees its line");

    reply(g_sv[1], NULL);
    check(answered("resp -901"), "an answer there was no memory for is sent once, as -901");

    receive(" \t\r\n", -1);
    check(answered("resp -902"), "the next message is read as before");

    close(g_sv[0]);
    close(g_sv[1]);
    printf("verbs: %d checks, %s\n", checks, failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}

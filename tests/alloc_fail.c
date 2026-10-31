/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The allocator of the daemon tests/alloc_sweep.py runs. A site is the place in the daemon that asks for memory, named by
 * its offset in the program so it holds across runs. ALLOC_FAIL_SITE=<site> refuses that site's ALLOC_FAIL_NTH-th asking
 * (the first by default); with ALLOC_FAIL_ALL=1 every allocation of the daemon from there on. ALLOC_FAIL_LOG names a file:
 * "site <site>" goes in it the first time a site asks, and "fail <site>" when the refusal happens. A fork's child writes
 * nothing: it execs. */
#include <fcntl.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define SITES 4096

static _Atomic uintptr_t g_seen[SITES];
static uintptr_t g_site;
static long g_nth = 1;
static atomic_long g_asked;
static atomic_int g_failing;
static int g_all;
static const char *g_log;
static pid_t g_owner;

static void note(const char *what, uintptr_t site)
{
    char line[64];
    int fd, len;

    if (!g_log || getpid() != g_owner)
        return;
    len = snprintf(line, sizeof(line), "%s %lx\n", what, (unsigned long)site);
    fd = open(g_log, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (fd >= 0)
    {
        if (write(fd, line, (size_t)len) < 0)
            len = 0;
        close(fd);
    }
}

__attribute__((constructor)) static void setup(void)
{
    const char *site = getenv("ALLOC_FAIL_SITE"), *nth = getenv("ALLOC_FAIL_NTH"), *all = getenv("ALLOC_FAIL_ALL");

    g_site = site ? (uintptr_t)strtoul(site, NULL, 16) : 0;
    g_nth = nth ? atol(nth) : 1;
    g_all = all && *all == '1';
    g_log = getenv("ALLOC_FAIL_LOG");
    g_owner = getpid();
}

/* the first time a site asks it goes in the log */
static void seen(uintptr_t site)
{
    size_t k = site % SITES, n;

    for (n = 0; n < SITES; n++, k = (k + 1) % SITES)
    {
        uintptr_t none = 0;

        if (atomic_load(&g_seen[k]) == site)
            return;
        if (atomic_compare_exchange_strong(&g_seen[k], &none, site))
        {
            note("site", site);
            return;
        }
        if (none == site)
            return;
    }
}

static int refused(void *caller)
{
    const uintptr_t site = (uintptr_t)caller - (uintptr_t)&setup;

    seen(site);
    if (atomic_load(&g_failing))
        return 1;
    if (!g_site || site != g_site || atomic_fetch_add(&g_asked, 1) + 1 != g_nth)
        return 0;
    note("fail", site);
    if (g_all)
        atomic_store(&g_failing, 1);
    return 1;
}

void *alloc_fail_malloc(size_t size);
void *alloc_fail_calloc(size_t n, size_t size);
void *alloc_fail_realloc(void *p, size_t size);
char *alloc_fail_strdup(const char *s);
char *alloc_fail_strndup(const char *s, size_t n);

void *alloc_fail_malloc(size_t size)
{
    return refused(__builtin_return_address(0)) ? NULL : malloc(size);
}

void *alloc_fail_calloc(size_t n, size_t size)
{
    return refused(__builtin_return_address(0)) ? NULL : calloc(n, size);
}

void *alloc_fail_realloc(void *p, size_t size)
{
    return refused(__builtin_return_address(0)) ? NULL : realloc(p, size);
}

char *alloc_fail_strdup(const char *s)
{
    return refused(__builtin_return_address(0)) ? NULL : strdup(s);
}

char *alloc_fail_strndup(const char *s, size_t n)
{
    return refused(__builtin_return_address(0)) ? NULL : strndup(s, n);
}

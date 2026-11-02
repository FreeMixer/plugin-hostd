/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

#define GUARDED 256

static _Thread_local void *g_guarded[GUARDED];

void *guard_calloc(size_t n, size_t size)
{
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    char *base;
    int k;

    if (n * size != sizeof(void *))
        return calloc(n, size);
    for (k = 0; k < GUARDED && g_guarded[k]; k++)
        ;
    if (k == GUARDED)
        return calloc(n, size);
    base = mmap(NULL, 2 * page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED)
        return NULL;
    mprotect(base + page, page, PROT_NONE);
    g_guarded[k] = base + page - sizeof(void *);
    return g_guarded[k];
}

void guard_free(void *p)
{
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    int k;

    for (k = 0; p && k < GUARDED; k++)
        if (g_guarded[k] == p)
        {
            g_guarded[k] = NULL;
            munmap((char *)p + sizeof(void *) - page, 2 * page);
            return;
        }
    free(p);
}

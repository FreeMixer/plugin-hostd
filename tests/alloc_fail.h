/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Forced into every source of the daemon that tests/alloc_sweep.py runs (gcc -include): the daemon's own allocations go
 * through tests/alloc_fail.c, which decides which of them fails. The system headers come first so their declarations
 * keep the real names. */
#ifndef ALLOC_FAIL_H
#define ALLOC_FAIL_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void *alloc_fail_malloc(size_t size);
void *alloc_fail_calloc(size_t n, size_t size);
void *alloc_fail_realloc(void *p, size_t size);
char *alloc_fail_strdup(const char *s);
char *alloc_fail_strndup(const char *s, size_t n);

#undef strdup
#undef strndup
#define malloc alloc_fail_malloc
#define calloc alloc_fail_calloc
#define realloc alloc_fail_realloc
#define strdup alloc_fail_strdup
#define strndup alloc_fail_strndup

#endif

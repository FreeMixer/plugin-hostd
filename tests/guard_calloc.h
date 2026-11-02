/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Forced into the sources of the daemon of `make test-plan-refused` (gcc -include): a one-pointer array from calloc ends
 * against a page nothing can touch, so a write past it kills the daemon with SIGSEGV, with no sanitizer to install. */
#ifndef GUARD_CALLOC_H
#define GUARD_CALLOC_H

#include <stdlib.h>
#include <string.h>

void *guard_calloc(size_t n, size_t size);
void guard_free(void *p);

#define calloc guard_calloc
#define free guard_free

#endif

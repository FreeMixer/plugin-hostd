/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* Strings that grow (json.c), which the probe runner writes its documents with, and the lookups of the JSON
 * the probe runner reads of its child and describe reads of the format tables. Out of memory, the program says so and exits 2. */

#ifndef PLUGIN_HOSTD_JSON_H
#define PLUGIN_HOSTD_JSON_H

#include <stddef.h>

#include <cjson/cJSON.h>

typedef struct
{
    char *s;
    size_t len, cap;
    /* when memory runs out: 0 ends the program (a scanner has nothing to save); 1 drops the text and sets failed, and every
     * later put does nothing, so the owner asks once, at the end */
    int keep_going, failed;
} sb_t;

void sb_put(sb_t *b, const char *data, size_t n);
void sb_printf(sb_t *b, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
/* a JSON string: the bytes of a valid UTF-8 text as they are, a control character or a byte that is not UTF-8 escaped */
void sb_str(sb_t *b, const char *s);

/* Reading is cJSON's (libcjson); these are the lookups every reader here makes of a value, and each takes NULL, or a value
 * of another type, for "not there". */

/* the whole text is one value, or NULL; free it with cJSON_Delete */
cJSON *jparse(const char *text);
cJSON *jget(const cJSON *o, const char *key);
const char *jstr(const cJSON *o, const char *key);
int jnum(const cJSON *o, const char *key, double *out);
int jbool(const cJSON *o, const char *key, int def);
/* the number of items of an array or object, and the k-th of them (for an object its key is jkey(o, k)) */
size_t jcount(const cJSON *o);
cJSON *jkid(const cJSON *o, size_t k);
const char *jkey(const cJSON *o, size_t k);

/* The bytes of one value of a text jparse has accepted, as they are written there: the object member `key` (keys as
 * plain bytes, no escapes) or the array item `index` of each step, from the text's own value. NULL when a step is not there. */
typedef struct
{
    const char *key; /* NULL for an array item */
    size_t index;
} jstep_t;
const char *jraw(const char *text, const jstep_t *path, size_t steps, size_t *len);

#endif

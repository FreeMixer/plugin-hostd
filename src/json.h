/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* Strings that grow and a small JSON reader (json.c): what the probe runner reads of its child and writes, and the
 * format tables describe reads. Out of memory, the program says so and exits 2. */

#ifndef PLUGIN_HOSTD_JSON_H
#define PLUGIN_HOSTD_JSON_H

#include <stddef.h>

typedef struct
{
    char *s;
    size_t len, cap;
} sb_t;

void sb_put(sb_t *b, const char *data, size_t n);
void sb_printf(sb_t *b, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
/* a JSON string: the bytes of a valid UTF-8 text as they are, a control character or a byte that is not UTF-8 escaped */
void sb_str(sb_t *b, const char *s);

typedef enum { J_NULL, J_BOOL, J_NUM, J_STR, J_ARR, J_OBJ } jtype_t;

typedef struct jnode
{
    jtype_t type;
    double num;
    int boolean;
    char *str;
    struct jnode **kid; /* array items, or object values */
    char **key;         /* object keys */
    size_t n;
} jnode_t;

/* the whole text is one value, or NULL */
jnode_t *jparse(const char *text);
jnode_t *jget(const jnode_t *o, const char *key);
const char *jstr(const jnode_t *o, const char *key);
int jnum(const jnode_t *o, const char *key, double *out);
int jbool(const jnode_t *o, const char *key, int def);
/* a value jparse gave, and all it holds */
void jfree(jnode_t *o);

#endif

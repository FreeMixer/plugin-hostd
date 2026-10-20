/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The transforms a format table names (docs/formats.md): a closed list, each a function from a field's text in a scan
 * to a descriptor word's value (inbound) and its inverse. A table refers to one by name and gives its data (the values
 * of a lookup, the factor of a scale-by); it never defines one. A new transform is added when a row needs it.
 *
 * A value crosses as text: the dump's text on the format side, a JSON literal on the descriptor side. Every function
 * returns TRANSFORMS_OK with the result in out, TRANSFORMS_NONE when the value gives nothing (a lookup with no entry
 * for it, a flag that is false), or TRANSFORMS_REFUSED (a value the transform cannot read, or out too small). */

#ifndef PLUGIN_HOSTD_TRANSFORMS_H
#define PLUGIN_HOSTD_TRANSFORMS_H

#include <stddef.h>

#define TRANSFORMS_OK 0
#define TRANSFORMS_NONE 1
#define TRANSFORMS_REFUSED (-1)

/* a row's data: its key (what flag's inverse writes), a lookup's values (from: the format side, to: JSON literals),
 * a scale-by's factor */
typedef struct
{
    const char *key;
    const char *const *from;
    const char *const *to;
    size_t n;
    double factor;
} transforms_data_t;

typedef int (*transforms_fn_t)(const transforms_data_t *d, const char *in, char *out, size_t size);

/* X(name, inbound, inverse): the closed list */
#define TRANSFORMS(X)                                                                                                  \
    X("identity", transforms_identity, transforms_identity_inverse)                                                    \
    X("lookup", transforms_lookup, transforms_lookup_inverse)                                                          \
    X("scale-by", transforms_scale_by, transforms_scale_by_inverse)                                                    \
    X("flag", transforms_flag, transforms_flag_inverse)                                                                \
    X("scale-points", transforms_scale_points, transforms_scale_points_inverse)                                        \
    X("group-path", transforms_group_path, transforms_group_path_inverse)                                              \
    X("port-group", transforms_port_group, transforms_port_group_inverse)

#define TRANSFORMS_DECLARE(name, in, inverse)                                                                          \
    int in(const transforms_data_t *d, const char *value, char *out, size_t size);                                     \
    int inverse(const transforms_data_t *d, const char *value, char *out, size_t size);
TRANSFORMS(TRANSFORMS_DECLARE)
#undef TRANSFORMS_DECLARE

typedef struct
{
    const char *name;
    transforms_fn_t inbound;
    transforms_fn_t inverse;
} transforms_entry_t;

/* the list, in TRANSFORMS(X) order, and its length */
extern const transforms_entry_t transforms_list[];
extern const size_t transforms_count;

/* the transform of that name, or NULL */
const transforms_entry_t *transforms_find(const char *name);

/* 0 when a lookup's values are one to one (no key and no entry twice), -1 otherwise: a table with such a lookup is
 * refused, since its inverse would have to choose */
int transforms_lookup_check(const transforms_data_t *d);

#endif

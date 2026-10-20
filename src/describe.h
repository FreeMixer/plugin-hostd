/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* plugin-hostd-probe describe: a plugin's field dump (omx-clap-scan --fields) through its format's table and the
 * transforms it names, written as a scanned descriptor (docs/formats.md). */

#ifndef PLUGIN_HOSTD_DESCRIBE_H
#define PLUGIN_HOSTD_DESCRIBE_H

#include <stddef.h>

#include "json.h"

/* the format of a target, clap:<path>#<id> or lv2:<uri>: "clap", "lv2", or NULL */
const char *describe_format(const char *target);

/* the scanned descriptor of a dump: the format table's text, the dump's text and the target asked for; 0 with the
 * descriptor in out, -1 refused (a table it cannot read, a dump it refuses) with why */
int describe_dump(const char *table_text, const char *dump_text, const char *target, sb_t *out, char *why,
                  size_t why_size);

#endif

/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The user-preset file (docs/presets.md, protocol/preset.schema.json) as the daemon reads it before a worker does. */

#ifndef PLUGIN_HOSTD_PRESET_H
#define PLUGIN_HOSTD_PRESET_H

/* a word preset_load and preset_show take as a file, not as a stable name */
int preset_is_path(const char *word);

/* SUCCESS when the file at path is an org.openmixer.preset of a format version this one knows and holds to its
 * format; PHD_ERR_PRESET_INVALID when it cannot be read, is no JSON, is of another version or breaks the format */
int preset_file_check(const char *path);

#endif

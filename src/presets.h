/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * plugin-hostd is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * plugin-hostd is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with plugin-hostd.  If not, see <http://www.gnu.org/licenses/>.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

#ifndef PRESETS_H
#define PRESETS_H

/* the org.openmixer.preset file (docs/presets.md, protocol/preset.schema.json), as the daemon reads it before a worker
 * sees it */

/* the text of a preset file against the format: 0, or PHD_ERR_PRESET_INVALID; when it holds and the pointers are
 * given, *plugin_id and *fingerprint are the file's (malloc'd, *fingerprint NULL for a /1 that has none) */
int preset_text_check(const char *text, char **plugin_id, char **fingerprint);

/* the same for the file at path: one that cannot be read, is empty or is over PHD_PRESET_FILE_MAX is invalid */
int preset_file_check(const char *path, char **plugin_id, char **fingerprint);

#endif

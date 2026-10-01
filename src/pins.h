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

#ifndef PINS_H
#define PINS_H

/* The pins the controller set, by URI: policy, like placement, and not in the ledger. */

/* pin_set: SUCCESS, or ERR_INVALID_OPERATION for a word outside the grammar; it replaces an earlier pin of the uri */
int pins_set(const char *uri, const char *files, const char *layout);

/* pin_clear of one uri, or of every one for "all"; SUCCESS */
int pins_clear(const char *uri);

/* The pin and the binary of an add, before any worker sees it: the pin of the uri, then every file it names hashed
 * over one open descriptor, and for an LV2 the manifest's binary and seeAlso files of the plugin held by the pin.
 * `clap` says the uri is clap:<path>#<id>; an LV2's bundle is searched in `lv2_path`. SUCCESS, with *layout the
 * layout pin "<scheme>:<sha256>" (the table's, valid until the next pin verb), or PHD_ERR_PIN_ABSENT or
 * PHD_ERR_PIN_BINARY_MISMATCH. */
int pins_check(int clap, const char *uri, const char *lv2_path, const char **layout);

void pins_finish(void);

#endif

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

/* The pins by URI: policy, like placement, and not in the ledger. They come from pin_set, from a pin file at start, and
 * (pin_mode first-use) from the daemon itself, which keeps what it learned in the pin store. One line format for the
 * three: <uri> <path>=<sha256>[,...] <scheme>:<sha256> [verdict=<word>], the verb pin_set in front or not. */

/* start: the store (empty is the XDG default) is read, then `file` (empty is none), which wins. -1 with the line named on
 * stderr when `file` has a line outside the grammar; a bad line of the store is kept verbatim by every save, announced on
 * stderr, and its uri is not learned again; a store that can't be read blocks learning and saving */
int pins_init(const char *store, const char *file);

/* pin_set: SUCCESS, or ERR_INVALID_OPERATION for a word outside the grammar; it replaces an earlier pin of the uri.
 * `verdict` is NULL, or one of PHD_PIN_VERDICTS */
int pins_set(const char *uri, const char *files, const char *layout, const char *verdict);

/* pin_clear of one uri, or of every one for "all"; SUCCESS */
int pins_clear(const char *uri);

/* whether the uri has a pin, and whether it is one a verdict of in-process qualified */
int pins_known(const char *uri);
int pins_in_process(const char *uri);

/* first use: the files the format loads for the uri, hashed, recorded with an unknown layout and written to the store.
 * SUCCESS, or PHD_ERR_PIN_BINARY_MISMATCH when they cannot be collected (nothing is recorded) */
int pins_learn(int clap, const char *uri, const char *lv2_path);

/* pin_accept: the same collection for a uri that has a pin, which it replaces; the layout is unknown again and the
 * verdict gone. PHD_ERR_PIN_ABSENT when there is no pin to replace */
int pins_accept(int clap, const char *uri, const char *lv2_path);

/* the layout a worker found after init, for a pin that has none; false for a layout that is not omx-layout/1 */
int pins_set_layout(const char *uri, const char *layout);

/* The pin and the binary of an add, before any worker sees it: the pin of the uri, then every file it names hashed
 * over one open descriptor, and for an LV2 the manifest's binary and seeAlso files of the plugin held by the pin.
 * `clap` says the uri is clap:<path>#<id>; an LV2's bundle is searched in `lv2_path`. SUCCESS, with *layout the
 * layout pin "<scheme>:<sha256>" (the table's, valid until the next pin verb) or NULL while the pin's layout is
 * unknown, or PHD_ERR_PIN_ABSENT or PHD_ERR_PIN_BINARY_MISMATCH. */
int pins_check(int clap, const char *uri, const char *lv2_path, const char **layout);

void pins_finish(void);

#endif

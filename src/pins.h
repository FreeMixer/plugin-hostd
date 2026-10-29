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

#include <plugin-hostd/pin.h>

#include "formats.h"

/* The pins by URI: policy, like placement, and not in the ledger. Two layers. The host's: pin_set, a pin file at start,
 * and (pin_mode first-use) the daemon itself, which keeps what it learned in the pin store. The packages': the *.pins
 * files of a directory, read at start and never written. The host's pin of a uri holds over the package's, except a
 * package pin of verdict=refused, which always holds. One line format for all: <uri> <path>=<sha256>[,...]
 * <scheme>:<sha256> [verdict=<word>], the verb pin_set in front or not. */

/* start: the *.pins files of `dir` (empty is none) in byte order of their names, of two pins of one uri a refusal
 * winning, else the later; then the store (empty is the XDG default), then `file` (empty is none), which wins over the
 * store. -1 with the line named on stderr when `file` has a line outside the grammar; a bad line of the store is kept
 * verbatim by every save, announced on stderr, and its uri is not learned again; a store that can't be read blocks
 * learning and saving; a bad line or an unreadable file of `dir` is announced and skipped, and a missing `dir` holds
 * no pins */
int pins_init(const char *store, const char *file, const char *dir);

/* the optional words of a pin line after its layout, each once and in either order: verdict=<word>, pool=<word>. Their
 * values (NULL for a word that is not there), and SUCCESS, or ERR_INVALID_OPERATION for another word or a repeated one */
int pins_words(char **word, int n, const char **verdict, const char **pool);

/* pin_set: SUCCESS, or ERR_INVALID_OPERATION for a word outside the grammar, or OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP when the package pin
 * of the uri carries verdict=refused; it replaces an earlier pin of the uri. `verdict` is NULL, or one of
 * PHD_PIN_VERDICTS; `pool` likewise, one of PHD_PIN_POOLS */
int pins_set(const char *uri, const char *files, const char *layout, const char *verdict, const char *pool);

/* pin_clear of the host's pin of one uri, or of every one for "all"; a package pin holds again. SUCCESS */
int pins_clear(const char *uri);

/* whether the uri has a pin, and whether it is one a verdict of in-process qualified */
int pins_known(const char *uri);
/* the SHA-256 of the first file the pin of the uri holds, as the pin holds it: the binary the running history is kept
 * under. -1 when the uri has no pin */
int pins_digest(const char *uri, char hex[PHD_SHA256_HEX_LEN + 1]);
int pins_in_process(const char *uri);
/* whether the pin of the uri grants it the CLAP thread pool: it carries pool=cores and is not a refusal (the pool is the
 * plugin's qualification's to give, never a global switch) */
int pins_pool_cores(const char *uri);
/* the verdict of the uri's pin as the pin line spells it (one of PHD_PIN_VERDICTS), "" for a pin without one, NULL when
 * there is no pin; valid until the next pin verb */
const char *pins_verdict(const char *uri);

/* first use: the files the format loads for the uri, hashed, recorded with an unknown layout and written to the store.
 * SUCCESS, or OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP when they cannot be collected (nothing is recorded) */
int pins_learn(const format_t *format, const char *uri, const char *search);

/* pin_accept: the same collection for a uri that has a pin, which it replaces; the layout is unknown again and the
 * verdict gone; over a package pin it is the host's that then holds. OMX_REPLY_HOST_PIN_ABSENT_RESP when there is no pin to replace,
 * OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP when the package pin carries verdict=refused */
int pins_accept(const format_t *format, const char *uri, const char *search);

/* the layout a worker found after init, for a pin that has none; false for a layout that is not omx-layout/1 */
int pins_set_layout(const char *uri, const char *layout);

/* The pin and the binary of an add, before any worker sees it: the pin of the uri, the files the format says the host
 * loads for it (format->pin_collect, searched in `search`) all held by the pin, then every file the pin names hashed
 * over one open descriptor. SUCCESS, with *layout the
 * layout pin "<scheme>:<sha256>" (the table's, valid until the next pin verb) or NULL while the pin's layout is
 * unknown, or OMX_REPLY_HOST_PIN_ABSENT_RESP or OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP, or OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP for the pinned files under a
 * verdict of refused. */
int pins_check(const format_t *format, const char *uri, const char *search, const char **layout);

/* a refusal of a pin, with the reason on stderr: OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP */
int pin_refuse(const char *uri, const char *path, const char *why);

void pins_finish(void);

#endif

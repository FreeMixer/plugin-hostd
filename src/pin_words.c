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


/* the optional words of a pin line, in a file of its own so the command fuzzer (fuzz/fuzz_command.c) runs this very
 * grammar and not a copy of it */

#include <string.h>

#include <host-errors.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "pins.h"

int pins_words(char **word, int n, const char **verdict, const char **pool)
{
    *verdict = *pool = NULL;
    for (int k = 0; k < n; k++)
    {
        const char **into;
        size_t key;

        if (!strncmp(word[k], PHD_PIN_VERDICT_KEY, strlen(PHD_PIN_VERDICT_KEY)))
            into = verdict, key = strlen(PHD_PIN_VERDICT_KEY);
        else if (!strncmp(word[k], PHD_PIN_POOL_KEY, strlen(PHD_PIN_POOL_KEY)))
            into = pool, key = strlen(PHD_PIN_POOL_KEY);
        else
            return ERR_INVALID_OPERATION;
        if (*into)
            return ERR_INVALID_OPERATION;
        *into = word[k] + key;
    }
    return SUCCESS;
}

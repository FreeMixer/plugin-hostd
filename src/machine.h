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

#ifndef MACHINE_H
#define MACHINE_H

#include <stddef.h>

/* The machine class the daemon's probe writes (omx-contract's MACHINE_CORE_BANDS and MACHINE_CLOCK_BANDS): the band of
 * `ncpu` cores and of `khz` kHz, the highest clock the first core states (0 when it states none). The words are the
 * contract's. */
void machine_bands(long ncpu, long khz, const char **core_band, const char **clock_band);

/* arch/cores/clock of this machine, as one word (x86_64/5-8/2.5-3.5GHz): uname's machine, the online cores' band and
 * cpu0's cpuinfo_max_freq's band. 0, or -1 when `size` is too small */
int machine_class(char *out, size_t size);

#endif

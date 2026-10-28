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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <omxcontract/omx_vocabulary.h>

#include "machine.h"

void machine_bands(long ncpu, long khz, const char **core_band, const char **clock_band)
{
    *core_band = ncpu <= 2 ? OMX_MACHINE_CORE_BANDS_CORES1_TO2 : ncpu <= 4 ? OMX_MACHINE_CORE_BANDS_CORES3_TO4 :
                 ncpu <= 8 ? OMX_MACHINE_CORE_BANDS_CORES5_TO8 : ncpu <= 16 ? OMX_MACHINE_CORE_BANDS_CORES9_TO16 :
                 ncpu <= 32 ? OMX_MACHINE_CORE_BANDS_CORES17_TO32 : OMX_MACHINE_CORE_BANDS_CORES33_UP;
    *clock_band = khz < 1500000 ? OMX_MACHINE_CLOCK_BANDS_UNDER1500_MHZ :
                  khz < 2500000 ? OMX_MACHINE_CLOCK_BANDS_FROM1500_TO2500_MHZ :
                  khz < 3500000 ? OMX_MACHINE_CLOCK_BANDS_FROM2500_TO3500_MHZ :
                  khz < 4500000 ? OMX_MACHINE_CLOCK_BANDS_FROM3500_TO4500_MHZ : OMX_MACHINE_CLOCK_BANDS_FROM4500_MHZ;
}

int machine_class(char *out, size_t size)
{
    struct utsname u;
    char text[64] = "";
    const char *core, *clock;
    long khz = 0;
    FILE *f;
    int n;

    if (uname(&u) != 0)
        snprintf(u.machine, sizeof(u.machine), "unknown");
    if ((f = fopen("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "r")))
    {
        if (fgets(text, sizeof(text), f))
            khz = atol(text);
        fclose(f);
    }
    machine_bands(sysconf(_SC_NPROCESSORS_ONLN), khz, &core, &clock);
    n = snprintf(out, size, "%s/%s/%s", u.machine, core, clock);
    return n > 0 && (size_t)n < size ? 0 : -1;
}

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

/* src/proc.c's readers of /proc against text written out by hand, in the shape the kernel writes it: a stat line whose
 * command name holds spaces and parentheses, an smaps_rollup with its Pss_ lines, and then the two files of this very
 * process, whose CPU time is spent here and counted by the CPU it used, not by the clock. */

#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <unistd.h>

#include "proc.h"

static int failures;

static void check(int ok, const char *what)
{
    if (!ok)
    {
        failures++;
        printf("FAIL proc: %s\n", what);
    }
}

int main(void)
{
    long long u = -1, s = -1, kb = -1;
    double cpu = 0, later;
    volatile unsigned long spin = 0;
    unsigned long spun;

    check(proc_parse_stat("1234 (plain) S 1 1234 1234 0 -1 4194560 100 0 0 0 7 3 0 0 20 0 1 0 100 1000000 50\n", &u, &s) == 0 &&
          u == 7 && s == 3, "utime 7 and stime 3 of a plain stat line");
    u = s = -1;
    check(proc_parse_stat("42 (my (odd) name) R 1 42 42 0 -1 4194560 9 0 1 0 123456 654321 0 0 20 0 1 0 100 1000000 50\n", &u, &s) == 0 &&
          u == 123456 && s == 654321, "a name with spaces and parentheses does not move the fields");
    check(proc_parse_stat("42 (x) R 1 42", &u, &s) == -1, "a line that ends before stime is refused");
    check(proc_parse_stat("42 (x) R 1 42 42 0 -1 4194560 9 0 1 0 abc 5 0\n", &u, &s) == -1, "a utime that is not a number is refused");
    check(proc_parse_stat("no name here", &u, &s) == -1, "a line with no name is refused");

    check(proc_parse_pss("Rss: 900 kB\nPss_Anon: 99 kB\nPss_File: 7 kB\nPss: 1234 kB\n", &kb) == 0 && kb == 1234,
          "Pss, not Pss_Anon or Pss_File");
    kb = -1;
    check(proc_parse_pss("Pss_Anon: 99 kB\nPss_File: 7 kB\n", &kb) == -1, "no Pss line: refused");
    check(proc_parse_pss("Pss: kB\n", &kb) == -1, "a Pss that is not a number is refused");

    check(proc_cpu_seconds(getpid(), &cpu) == 0, "this process's CPU time is read");
    /* spin in batches, reading the CPU time between them; a reader that never sees it grow ends the loop at the bound */
    for (int batch = 0; batch < 3000 && proc_cpu_seconds(getpid(), &later) == 0 && later < cpu + 0.03; batch++)
        for (int n = 0; n < 1000000; n++)
            spin++;
    spun = spin;
    check(spun > 0, "the loop ran");
    check(later >= cpu + 0.03, "the CPU time of a process that spins grows by what it spun");
    {
        struct rusage ru;
        double own;

        getrusage(RUSAGE_SELF, &ru);
        own = ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
        proc_cpu_seconds(getpid(), &later);
        check(later > own - 0.05 && later < own + 0.05, "the CPU time is in seconds, and is what getrusage says of this process");
    }
    if (proc_pss_kb(getpid(), &kb) == 0)
        check(kb > 100 && kb < 100000000, "this process's Pss is a believable number of kB");
    else
        printf("skip proc: no smaps_rollup for this process\n");
    check(proc_cpu_seconds(2147483000, &cpu) == -1, "a process that is not there answers -1");
    if (failures)
        printf("proc: %d failed\n", failures);
    else
        printf("ok   proc_test\n");
    return failures ? 1 : 0;
}

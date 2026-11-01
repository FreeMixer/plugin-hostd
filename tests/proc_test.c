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

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
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

static void write_manifest(const char *dir, const char *bundle, const char *text)
{
    char path[PATH_MAX];
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", dir, bundle);
    mkdir(path, 0755);
    snprintf(path, sizeof(path), "%s/%s/manifest.ttl", dir, bundle);
    f = fopen(path, "w");
    fputs(text, f);
    fclose(f);
}

/* omx-modgui-sync writes a bundle that names the plugin and holds only its GUI; it may come first on the path */
static void test_bundle_lookup(void)
{
    static const char *const uri = "http://example.org/fil#stereo";
    static const char *const gui = "<http://example.org/fil#stereo>\n    modgui:gui [ ] .\n";
    static const char *const real =
        "@prefix fil: <http://example.org/fil#> .\nfil:stereo a lv2:Plugin ; lv2:binary <fil.so> .\n";
    char root[] = "/tmp/proc_test.XXXXXX", first[PATH_MAX], second[PATH_MAX], path[PATH_MAX * 2 + 1], *found;

    check(mkdtemp(root) != NULL, "a scratch directory");
    snprintf(first, sizeof(first), "%s/a", root);
    snprintf(second, sizeof(second), "%s/b", root);
    mkdir(first, 0755);
    mkdir(second, 0755);
    write_manifest(first, "omx-modgui-fil.lv2", gui);
    snprintf(path, sizeof(path), "%s:%s", first, second);
    found = proc_find_lv2_bundle(path, uri);
    check(found && strstr(found, "omx-modgui-fil.lv2"), "with no other bundle, the one that names the plugin");
    free(found);
    write_manifest(second, "fil.lv2", real);
    found = proc_find_lv2_bundle(path, uri);
    check(found && strstr(found, "/fil.lv2"), "the bundle with the binary, not the GUI bundle earlier on the path");
    free(found);
    write_manifest(first, "aaa-gui.lv2", gui);
    write_manifest(first, "zzz-gui.lv2", gui);
    found = proc_find_lv2_bundle(path, uri);
    check(found && strstr(found, "/fil.lv2"), "the binary's bundle whichever order the directory lists them");
    free(found);
    check(proc_find_lv2_bundle(path, "http://example.org/other") == NULL, "a plugin no manifest names has no bundle");
}


/* a plugin found once is found again with one manifest read, not a walk of the path: the daemon looks a plugin up on every
 * add, and a Zynthian's path holds hundreds of bundles. A bundle that moved, or no longer holds the plugin, is not
 * answered from memory; a bundle that only names it (a GUI bundle) is never remembered, so a binary installed later
 * still wins */
static void test_bundle_lookup_remembers(void)
{
    static const char *const uri = "http://example.org/late#mono";
    static const char *const real =
        "@prefix late: <http://example.org/late#> .\nlate:mono a lv2:Plugin ; lv2:binary <late.so> .\n";
    static const char *const other = "<http://example.org/other> a lv2:Plugin ; lv2:binary <o.so> .\n";
    char root[] = "/tmp/proc_test.XXXXXX", dir[PATH_MAX], moved[PATH_MAX * 2], from[PATH_MAX * 2], name[64], *found;
    unsigned long reads;
    int k;

    check(mkdtemp(root) != NULL, "a scratch directory");
    snprintf(dir, sizeof(dir), "%s/lv2", root);
    mkdir(dir, 0755);
    for (k = 0; k < 40; k++)
    {
        snprintf(name, sizeof(name), "other%02d.lv2", k);
        write_manifest(dir, name, other);
    }
    write_manifest(dir, "late.lv2", real);
    found = proc_find_lv2_bundle(dir, uri);
    check(found && strstr(found, "/late.lv2"), "the plugin's bundle among forty others");
    free(found);
    reads = proc_manifest_reads;
    found = proc_find_lv2_bundle(dir, uri);
    check(found && strstr(found, "/late.lv2") && proc_manifest_reads - reads == 1,
          "found again with one manifest read, not a walk of the path");
    free(found);
    /* the bundle moves: the remembered one is gone, and the walk finds where it is now */
    snprintf(from, sizeof(from), "%s/late.lv2", dir);
    snprintf(moved, sizeof(moved), "%s/zz-late.lv2", dir);
    check(rename(from, moved) == 0, "the bundle moved");
    found = proc_find_lv2_bundle(dir, uri);
    check(found && strstr(found, "/zz-late.lv2"), "a moved bundle is found where it is now, not where it was");
    free(found);
    /* the bundle no longer holds the plugin: no bundle, not the remembered one */
    write_manifest(dir, "zz-late.lv2", other);
    found = proc_find_lv2_bundle(dir, uri);
    check(found == NULL, "a bundle that no longer names the plugin is not answered from memory");
    free(found);
}

int main(void)
{
    long long u = -1, s = -1, kb = -1;
    double cpu = 0, later;
    volatile unsigned long spin = 0;
    unsigned long spun;

    test_bundle_lookup();
    test_bundle_lookup_remembers();
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

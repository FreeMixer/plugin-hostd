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

/* src/history.c against records and files written out by hand: the line a record becomes, what a load gives back, the
 * lines and files it must keep and refuse, what the counts and the summary come to. Nothing here reads a clock: every
 * time is a number the test passes in. Each group prints "ok   <name>" when none of its checks failed. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <plugin-hostd/protocol.h>
#include <plugin-hostd/plugin_hostd_vocabulary.h>

#include "history.h"
#include "machine.h"

#define CLASS  "x86_64/5-8/2.5-3.5GHz"
#define URI    "clap:/p/a.clap#org.test.a"
#define DIGEST "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
#define OTHER  "cb7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
#define DAY    86400LL

static int failures, group_failures;
static char dir[256], file[300];

static void check(int ok, const char *what)
{
    if (!ok)
    {
        group_failures++;
        printf("FAIL history: %s\n", what);
    }
}

static void check_str(const char *got, const char *want, const char *what)
{
    if (!got || strcmp(got, want))
    {
        group_failures++;
        printf("FAIL history: %s\n     got  %s\n     want %s\n", what, got ? got : "(null)", want);
    }
}

static void group(const char *name)
{
    if (group_failures)
        failures += group_failures;
    else if (name)
        printf("ok   %s\n", name);
    group_failures = 0;
}

static char *slurp(const char *path)
{
    char *buf;
    FILE *f = fopen(path, "r");
    size_t n;

    if (!f)
        return NULL;
    buf = calloc(1, 65536);
    n = fread(buf, 1, 65535, f);
    buf[n] = '\0';
    fclose(f);
    return buf;
}

static void put(const char *path, const char *text)
{
    FILE *f = fopen(path, "w");

    if (!f)
    {
        printf("FAIL history: test can't write %s\n", path);
        exit(2);
    }
    fputs(text, f);
    fclose(f);
}

/* the file as text, "" when there is none */
static char *file_text(void)
{
    char *t = slurp(file);

    return t ? t : strdup("");
}

static void fresh(void)
{
    char cmd[400];

    snprintf(cmd, sizeof(cmd), "rm -rf '%s'/*", dir);
    if (system(cmd) != 0)
        exit(2);
}

static void start(void)
{
    history_init(file, CLASS, 300);
}

#define HEADER PHD_HISTORY_HEADER "\n"

static void count_everything(void)
{
    history_window(URI, DIGEST, 0, 10.0, 12.3, 0, 1000);
    history_window(URI, DIGEST, 0, 20.0, 8.0, 1, 1060);
    history_window(URI, DIGEST, 1, 99.0, 99.0, 2, 1120);
    history_crash(URI, DIGEST, 0, 1180);
    history_crash(URI, DIGEST, 1, 1240);
    history_restart(URI, DIGEST, 1, 1300);
    history_restart(URI, DIGEST, 0, 1310);          /* alone: not a restart of a group, not counted */
    history_quarantine(URI, DIGEST, 1360);
}

static void test_the_keys_are_the_contracts_words(void)
{
    history_rec_t r = { .uri = URI, .klass = CLASS };
    const char *const words[] = OMX_PLUGIN_HOSTD_HISTORY_KEYS_INIT;
    char *line, *p;
    unsigned n;

    memcpy(r.digest, DIGEST, sizeof(r.digest));
    line = history_line(&r);
    p = strchr(strchr(strchr(strchr(line, ' ') + 1, ' ') + 1, ' ') + 1, ' ');
    for (n = 0; n < OMX_PLUGIN_HOSTD_HISTORY_KEYS_COUNT; n++)
    {
        char want[64];

        snprintf(want, sizeof(want), " %s=", words[n]);
        check(p && !strncmp(p, want, strlen(want)), words[n]);
        p = p ? strchr(p + 1, ' ') : NULL;
    }
    check(p == NULL || *p == '\n', "no key of the line is outside the words");
    free(line);
    group("the_line_holds_the_contracts_keys_in_the_contracts_order");
}

static void test_round_trip(void)
{
    char *text, *again;
    const history_rec_t *r;
    char *summary;

    fresh();
    start();
    count_everything();
    history_finish();
    text = file_text();
    check_str(text, HEADER "history " URI " " DIGEST " " CLASS
              " first=1000 last=1360 windows_solo=2 windows_grouped=1 cpu_p95_solo=10.19 cpu_max_solo=20.00 pss_mb_solo=12.3"
              " xrun_windows_solo=1 xrun_windows_grouped=1 crashes_solo=1 crashes_grouped=1 restarts_grouped=1"
              " quarantines=1 last_crash=1180 last_crash_grouped=1240\n", "the file a record is written as");
    start();
    r = history_find(URI, DIGEST);
    check(r != NULL, "the record is found after a restart");
    if (r)
    {
        check(r->first == 1000 && r->last == 1360 && r->windows_solo == 2 && r->windows_grouped == 1, "windows and times");
        check(r->cpu_p95_solo > 10.189 && r->cpu_p95_solo < 10.191 && r->cpu_max_solo == 20.0, "cpu");
        check(r->pss_mb_solo > 12.29 && r->pss_mb_solo < 12.31, "pss");
        check(r->xrun_windows_solo == 1 && r->xrun_windows_grouped == 1, "xrun windows");
        check(r->crashes_solo == 1 && r->crashes_grouped == 1 && r->restarts_grouped == 1 && r->quarantines == 1,
              "crashes, restarts and quarantines");
        check(r->last_crash == 1180 && r->last_crash_grouped == 1240, "last crashes");
    }
    summary = history_summary(URI, DIGEST, 1400);
    check_str(summary, "digest=" DIGEST ",class=" CLASS ",crashed=1,raises_xruns=0,first=1000,last=1360,windows_solo=2,"
              "windows_grouped=1,cpu_p95_solo=10.19,cpu_max_solo=20.00,pss_mb_solo=12.3,xrun_windows_solo=1,"
              "xrun_windows_grouped=1,crashes_solo=1,crashes_grouped=1,restarts_grouped=1,quarantines=1,last_crash=1180,"
              "last_crash_grouped=1240",
              "the summary history_get answers");
    free(summary);
    history_finish();
    again = file_text();
    check_str(again, text, "a load and a save of an untouched history is byte for byte the same file");
    free(text);
    free(again);
    group("a_record_round_trips_through_its_file_value_for_value");
}

static void test_windows(void)
{
    const history_rec_t *r;

    fresh();
    start();
    history_window(URI, DIGEST, 0, 10.0, 5.0, 0, 100);
    history_window(URI, DIGEST, 0, 10.0, 7.5, 0, 160);
    r = history_find(URI, DIGEST);
    check(r->cpu_p95_solo > 9.9899 && r->cpu_p95_solo < 9.9901, "a window that is not above the estimate moves it down 5 parts of 0.2: 9.99");
    history_window(URI, DIGEST, 0, 20.0, 6.0, 0, 220);      /* above: 9.99 + 0.95 * 0.02 * 9.99 = 10.17981 */
    check(r->cpu_p95_solo > 10.1797 && r->cpu_p95_solo < 10.1799, "above the estimate moves it up 95 parts of a step of 2 percent of it");
    history_window(URI, DIGEST, 0, 5.0, 6.0, 0, 280);       /* below: 10.17981 - 0.05 * 0.02 * 10.17981 = 10.16963 */
    check(r->cpu_p95_solo > 10.1695 && r->cpu_p95_solo < 10.1697, "below it moves it down 5 parts");
    check(r->cpu_max_solo == 20.0, "cpu max is the largest solo window");
    check(r->pss_mb_solo == 7.5, "pss is the largest solo window");
    check(r->windows_solo == 4 && r->windows_grouped == 0, "four solo windows");
    check(r->first == 100 && r->last == 280, "first and last window");
    history_window(URI, DIGEST, 1, 90.0, 900.0, 0, 340);
    check(r->windows_grouped == 1 && r->windows_solo == 4, "a group's window is counted apart");
    check(r->cpu_max_solo == 20.0 && r->pss_mb_solo == 7.5 && r->cpu_p95_solo < 10.2,
          "a group's worker time is never taken for the plugin's own: cpu and pss stay those of the solo windows");
    check(r->xrun_windows_solo == 0 && r->xrun_windows_grouped == 0, "no xrun reported, none counted");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 3, 400);
    history_window(URI, DIGEST, 1, 1.0, 1.0, 1, 460);
    history_window(URI, DIGEST, 1, 1.0, 1.0, 5, 520);
    check(r->xrun_windows_solo == 1 && r->xrun_windows_grouped == 2, "a window counts once however many xruns it saw");
    history_finish();
    group("windows_fold_alone_and_in_a_group_into_their_own_fields");
}

static void test_no_record_for_what_is_not_a_plugin(void)
{
    fresh();
    start();
    history_window("", DIGEST, 0, 1, 1, 0, 1);
    history_window("clap:/with space#x", DIGEST, 0, 1, 1, 0, 1);
    history_window(URI, "nothex", 0, 1, 1, 0, 1);
    history_window(URI, "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD", 0, 1, 1, 0, 1);
    history_crash(NULL, DIGEST, 0, 1);
    history_finish();
    check_str(file_text(), "", "nothing is written for a uri that is empty or holds a space, or a digest that is not 64 lowercase hex");
    group("a_key_that_is_not_a_plugin_binary_makes_no_record");
}

static void test_summary(void)
{
    char *s;

    /* crashed: within 30 days of the last crash, the later of the two */
    fresh();
    start();
    history_crash(URI, DIGEST, 0, 1000);
    s = history_summary(URI, DIGEST, 1000 + 30 * DAY);
    check(s && strstr(s, ",crashed=1,"), "a crash exactly 30 days ago still counts");
    free(s);
    s = history_summary(URI, DIGEST, 1000 + 30 * DAY + 1);
    check(s && strstr(s, ",crashed=0,"), "a crash 30 days and a second ago does not");
    free(s);
    history_crash(URI, DIGEST, 1, 1000 + 20 * DAY);
    s = history_summary(URI, DIGEST, 1000 + 30 * DAY + 1);
    check(s && strstr(s, ",crashed=1,"), "a recent grouped crash counts though the solo one is old");
    free(s);
    history_finish();

    /* raises_xruns, with no solo windows: more than 5 percent of the grouped windows, from 30 windows */
    fresh();
    start();
    for (int w = 0; w < 29; w++)
        history_window(URI, DIGEST, 1, 1, 1, w < 29 ? 1 : 0, 100 + w);
    s = history_summary(URI, DIGEST, 200);
    check(s && strstr(s, ",raises_xruns=0,"), "29 grouped windows, all with xruns, are too few to say");
    free(s);
    history_window(URI, DIGEST, 1, 1, 1, 1, 200);
    s = history_summary(URI, DIGEST, 200);
    check(s && strstr(s, ",raises_xruns=1,"), "30 grouped windows, all with xruns, are enough");
    free(s);
    history_finish();

    fresh();
    start();
    for (int w = 0; w < 30; w++)
        history_window(URI, DIGEST, 1, 1, 1, w < 1 ? 1 : 0, 100 + w);
    s = history_summary(URI, DIGEST, 200);
    check(s && strstr(s, ",raises_xruns=0,"), "1 of 30 grouped windows is 3.3 percent: under the 5 percent");
    free(s);
    history_finish();
    fresh();
    start();
    for (int w = 0; w < 30; w++)
        history_window(URI, DIGEST, 1, 1, 1, w < 2 ? 1 : 0, 100 + w);
    s = history_summary(URI, DIGEST, 200);
    check(s && strstr(s, ",raises_xruns=1,"), "2 of 30 grouped windows is 6.7 percent: over it");
    free(s);
    history_finish();
    fresh();
    start();
    for (int w = 0; w < 40; w++)
        history_window(URI, DIGEST, 1, 1, 1, w < 2 ? 1 : 0, 100 + w);
    s = history_summary(URI, DIGEST, 200);
    check(s && strstr(s, ",raises_xruns=0,"), "2 of 40 grouped windows is exactly 5 percent: not over it");
    free(s);
    history_finish();

    /* with solo windows: the grouped share must exceed the solo share by 5 points, strictly */
    fresh();
    start();
    for (int w = 0; w < 100; w++)
        history_window(URI, DIGEST, 0, 1, 1, w < 10 ? 1 : 0, 100 + w);          /* solo: 10 of 100 = 10 % */
    for (int w = 0; w < 40; w++)
        history_window(URI, DIGEST, 1, 1, 1, w < 6 ? 1 : 0, 300 + w);           /* grouped: 6 of 40 = 15 %: exactly +5 */
    s = history_summary(URI, DIGEST, 400);
    check(s && strstr(s, ",raises_xruns=0,"), "exactly 5 points over the solo share does not exceed it");
    free(s);
    history_window(URI, DIGEST, 1, 1, 1, 1, 500);                               /* 7 of 41 = 17.07 % */
    s = history_summary(URI, DIGEST, 600);
    check(s && strstr(s, ",raises_xruns=1,"), "more than 5 points over the solo share is a plugin that raises xruns");
    free(s);
    s = history_summary(URI, OTHER, 600);
    check(s == NULL, "no record of another binary");
    history_finish();
    group("the_summary_marks_crashes_and_raised_xruns_at_the_declared_margins");
}

static void test_another_host_class_is_kept_and_not_mixed(void)
{
    char *text;

    fresh();
    put(file, HEADER "history " URI " " DIGEST " aarch64/5-8/<1.5GHz first=5 last=6 windows_solo=7 windows_grouped=0 "
              "cpu_p95_solo=1.00 cpu_max_solo=2.00 pss_mb_solo=3.0 xrun_windows_solo=0 xrun_windows_grouped=0 "
              "crashes_solo=9 crashes_grouped=0 restarts_grouped=0 quarantines=0 last_crash=6 last_crash_grouped=0\n");
    start();
    check(history_find(URI, DIGEST) == NULL, "the record of another host class is not this class's");
    history_window(URI, DIGEST, 0, 4.0, 4.0, 0, 50);
    history_finish();
    text = file_text();
    check(strstr(text, "aarch64/5-8/<1.5GHz first=5 last=6 windows_solo=7") != NULL, "the other class's line is kept as it was");
    check(strstr(text, CLASS " first=50 last=50 windows_solo=1") != NULL, "this class has a line of its own");
    free(text);
    group("a_record_of_another_host_class_is_kept_and_never_read_as_this_ones");
}

static void test_lines_this_version_cannot_read(void)
{
    const char *bad[] = {
        "history clap:/bad/1 " DIGEST " " CLASS " first=1 last=2 future_key=5",                  /* a key it does not know */
        "history clap:/bad/2 " DIGEST " " CLASS " first=-1",                                     /* negative */
        "history clap:/bad/3 " DIGEST " " CLASS " cpu_max_solo=nan",                             /* not a number */
        "history clap:/bad/4 " DIGEST " " CLASS " cpu_max_solo=inf",
        "history clap:/bad/5 " DIGEST " " CLASS " windows_solo=1.5",                             /* a count that is not whole */
        "history clap:/bad/6 " DIGEST " " CLASS " windows_solo=3 windows_solo=4",                /* one key twice */
        "history clap:/bad/7 nothex " CLASS " first=1",                                          /* a digest that is not one */
        "history clap:/bad/8 " DIGEST,                                                           /* too few words */
        "plugin clap:/bad/9 " DIGEST " " CLASS " first=1",                                       /* not a history line */
        "history clap:/bad/10 " DIGEST " " CLASS " first",                                       /* no value */
        "garbage",
    };
    char all[8192] = HEADER, *text;
    unsigned n;
    const history_rec_t *r;

    fresh();
    strcat(all, "history " URI " " DIGEST " " CLASS " first=10 last=20 windows_solo=3\n");
    for (n = 0; n < sizeof(bad) / sizeof(bad[0]); n++)
    {
        strcat(all, bad[n]);
        strcat(all, "\n");
    }
    put(file, all);
    start();
    check(history_available(), "bad lines do not block the file");
    r = history_find(URI, DIGEST);
    check(r && r->windows_solo == 3 && r->first == 10, "the good line is read");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 30);
    history_finish();
    text = file_text();
    for (n = 0; n < sizeof(bad) / sizeof(bad[0]); n++)
    {
        char want[400];

        snprintf(want, sizeof(want), "\n%s\n", bad[n]);
        check(strstr(text, want) != NULL, bad[n]);
    }
    check(strstr(text, "windows_solo=4") != NULL, "the good line is updated beside them");
    free(text);
    group("a_line_outside_the_grammar_is_kept_verbatim_and_not_read");
}

static void test_a_second_line_of_one_binary(void)
{
    char *text;
    const history_rec_t *r;

    fresh();
    put(file, HEADER "history " URI " " DIGEST " " CLASS " windows_solo=1\n"
                     "history " URI " " DIGEST " " CLASS " windows_solo=9\n");
    start();
    r = history_find(URI, DIGEST);
    check(r && r->windows_solo == 1, "the first line holds");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    text = file_text();
    check(strstr(text, "windows_solo=9\n") != NULL, "the second is kept as it was");
    free(text);
    group("a_second_line_of_one_binary_and_class_is_kept_and_not_read");
}

static void test_comments_and_blanks(void)
{
    char *text;

    fresh();
    put(file, HEADER "# kept\n\nhistory " URI " " DIGEST " " CLASS " windows_solo=1\n");
    start();
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    text = file_text();
    check(strstr(text, HEADER "# kept\nhistory " URI) != NULL, "a comment stays where it was, a blank line goes");
    free(text);
    group("a_comment_line_is_kept_in_its_place");
}

static void test_blocked_files(void)
{
    struct { const char *name, *content; } cases[] = {
        { "an unknown version", "# plugin-hostd history/2\nhistory " URI " " DIGEST " " CLASS " windows_solo=1\n" },
        { "not a history file", "something else entirely\nhistory " URI " " DIGEST " " CLASS " windows_solo=1\n" },
        { "a header with a suffix", "# plugin-hostd history/1 extra\nhistory " URI " " DIGEST " " CLASS " windows_solo=1\n" },
    };
    unsigned n;

    for (n = 0; n < sizeof(cases) / sizeof(cases[0]); n++)
    {
        char *text;

        fresh();
        put(file, cases[n].content);
        start();
        check(!history_available(), cases[n].name);
        check(history_find(URI, DIGEST) == NULL, "a blocked history reads nothing");
        history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
        history_crash(URI, DIGEST, 0, 4);
        check(history_clear("all") == -1, "a blocked history is not cleared");
        history_tick(100000);
        history_tick(200000);
        history_finish();
        text = file_text();
        check_str(text, cases[n].content, "a blocked history is never overwritten");
        free(text);
    }
    /* a file that cannot be read: a directory where it should be */
    fresh();
    mkdir(file, 0700);
    start();
    check(!history_available(), "a history that is a directory can't be read");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    check(access(file, F_OK) == 0, "and is left where it was");
    group("a_file_with_an_unknown_version_or_that_cannot_be_read_blocks_the_history_and_is_never_touched");
}

static void test_missing_and_empty_files(void)
{
    fresh();
    start();
    check(history_available(), "a missing file is an empty history");
    history_finish();
    check_str(file_text(), "", "and nothing is written for it");
    put(file, "");
    start();
    check(history_available(), "an empty file is an empty history");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    check(strncmp(file_text(), HEADER, strlen(HEADER)) == 0, "which gets its header");
    group("a_missing_or_empty_file_is_an_empty_history");
}

static void test_the_file(void)
{
    struct stat st;
    char sub[400], listing[600], *l;
    FILE *p;

    fresh();
    snprintf(sub, sizeof(sub), "%s/a/b/history", dir);
    history_init(sub, CLASS, 300);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    check(stat(sub, &st) == 0 && (st.st_mode & 0777) == 0600, "the file is mode 0600");
    snprintf(sub, sizeof(sub), "%s/a/b", dir);
    check(stat(sub, &st) == 0 && (st.st_mode & 0777) == 0700, "its missing directories are made mode 0700");
    snprintf(listing, sizeof(listing), "ls -A '%s/a/b'", dir);
    p = popen(listing, "r");
    l = calloc(1, 256);
    if (p)
    {
        size_t n = fread(l, 1, 255, p);

        l[n] = '\0';
        pclose(p);
    }
    check_str(l, "history\n", "no temporary file is left beside it");
    free(l);
    group("the_history_file_is_mode_0600_in_a_private_directory_with_no_temporary_beside_it");
}

/* A save that fails has to fail for root too, so the directory is not made unwritable (root writes it anyway): the name
 * of the history file is taken by a directory that is not empty, and renaming the finished temporary file over it is
 * refused. */
static void test_a_failed_save(void)
{
    char *before, *after, stray[420], cmd[900], l[32] = "";
    struct stat st;
    FILE *p;

    fresh();
    start();
    history_tick(0);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_tick(300);
    before = file_text();
    check(strlen(before) > strlen(HEADER), "the first save wrote the record");
    history_window(URI, DIGEST, 0, 2.0, 2.0, 0, 70);
    snprintf(stray, sizeof(stray), "%s/stray", file);
    if (unlink(file) != 0 || mkdir(file, 0700) != 0)
    {
        printf("FAIL history: test can't put a directory in the history's place\n");
        exit(2);
    }
    put(stray, "x");
    history_tick(1000);
    check(stat(file, &st) == 0 && S_ISDIR(st.st_mode), "a save that can't write leaves what was there as it was");
    snprintf(cmd, sizeof(cmd), "ls -A '%s' | wc -l", dir);
    p = popen(cmd, "r");
    if (p && fgets(l, sizeof(l), p))
        check(atoi(l) == 1, "a failed save leaves no temporary file behind");
    if (p)
        pclose(p);
    unlink(stray);
    rmdir(file);
    put(file, before);
    history_tick(1299);
    after = file_text();
    check_str(after, before, "a failed save is tried again after the interval, not at every tick");
    free(after);
    history_tick(1300);
    after = file_text();
    check(strstr(after, "windows_solo=2") != NULL, "the change was not forgotten: the next tick writes it");
    free(before);
    free(after);
    history_finish();
    group("a_save_that_fails_leaves_the_old_file_whole_and_is_tried_again");
}

static void test_save_interval(void)
{
    char *t;

    fresh();
    history_init(file, CLASS, 300);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_tick(1000);                 /* the first tick opens the first interval */
    check_str(file_text(), "", "the first interval has not passed: nothing written");
    history_tick(1299);
    check_str(file_text(), "", "299 s into it: still nothing");
    history_tick(1300);
    t = file_text();
    check(strstr(t, "windows_solo=1") != NULL, "300 s into it the change is written");
    free(t);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 70);
    history_tick(1599);
    t = file_text();
    check(strstr(t, "windows_solo=1") != NULL, "299 s after a save the next change is not written");
    free(t);
    history_tick(1600);
    t = file_text();
    check(strstr(t, "windows_solo=2") != NULL, "300 s after it is");
    free(t);
    history_tick(5000);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 130);
    history_finish();
    t = file_text();
    check(strstr(t, "windows_solo=3") != NULL, "and quitting writes what the interval had not");
    free(t);
    group("the_history_is_saved_at_most_once_per_interval_and_at_quit");
}

static void test_clear(void)
{
    char *text;

    fresh();
    put(file, HEADER
        "history " URI " " DIGEST " " CLASS " windows_solo=1\n"
        "history " URI " " OTHER " " CLASS " windows_solo=2\n"
        "history " URI " " DIGEST " aarch64/1-2/<1.5GHz windows_solo=3\n"
        "history " URI " " DIGEST " " CLASS " windows_solo=4 future=1\n"
        "history clap:/p/b.clap#org.test.b " DIGEST " " CLASS " windows_solo=5\n");
    start();
    check(history_clear(URI) == 0, "clear of a uri answers");
    text = file_text();
    check_str(text, HEADER "history clap:/p/b.clap#org.test.b " DIGEST " " CLASS " first=0 last=0 windows_solo=5 "
              "windows_grouped=0 cpu_p95_solo=0.00 cpu_max_solo=0.00 pss_mb_solo=0.0 xrun_windows_solo=0 "
              "xrun_windows_grouped=0 crashes_solo=0 crashes_grouped=0 restarts_grouped=0 quarantines=0 last_crash=0 "
              "last_crash_grouped=0\n",
              "every binary, class and unreadable line of the uri is gone at once, the other plugin stays");
    free(text);
    check(history_find(URI, DIGEST) == NULL, "and the memory too");
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    check(history_clear("all") == 0, "clear all");
    text = file_text();
    check_str(text, HEADER, "empties the file but for its header");
    free(text);
    history_finish();
    group("clear_removes_a_plugins_lines_of_every_binary_and_class_or_all_of_them_at_once");
}

static void test_the_path(void)
{
    char want[400], *text;

    fresh();
    snprintf(want, sizeof(want), "%s/state", dir);
    setenv("XDG_STATE_HOME", want, 1);
    history_init("", CLASS, 300);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    snprintf(want, sizeof(want), "%s/state/plugin-hostd/history", dir);
    check(access(want, F_OK) == 0, "$XDG_STATE_HOME/plugin-hostd/history");
    unsetenv("XDG_STATE_HOME");
    snprintf(want, sizeof(want), "%s/home", dir);
    setenv("HOME", want, 1);
    history_init("", CLASS, 300);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    snprintf(want, sizeof(want), "%s/home/.local/state/plugin-hostd/history", dir);
    check(access(want, F_OK) == 0, "$HOME/.local/state/plugin-hostd/history");
    snprintf(want, sizeof(want), "%s/elsewhere", dir);
    history_init(want, CLASS, 300);
    history_window(URI, DIGEST, 0, 1.0, 1.0, 0, 3);
    history_finish();
    text = slurp(want);
    check(text != NULL, "history_file names another");
    free(text);
    group("the_default_path_is_the_xdg_state_home_then_home_and_history_file_overrides_both");
}

static void test_host_class(void)
{
    static const struct { long ncpu; const char *want; } cores[] = {
        { 1, "1-2" }, { 2, "1-2" }, { 3, "3-4" }, { 4, "3-4" }, { 5, "5-8" }, { 8, "5-8" }, { 9, "9-16" }, { 16, "9-16" },
        { 17, "17-32" }, { 32, "17-32" }, { 33, "33+" }, { 256, "33+" },
    };
    static const struct { long khz; const char *want; } clocks[] = {
        { 0, "<1.5GHz" }, { 1499999, "<1.5GHz" }, { 1500000, "1.5-2.5GHz" }, { 2499999, "1.5-2.5GHz" },
        { 2500000, "2.5-3.5GHz" }, { 3499999, "2.5-3.5GHz" }, { 3500000, "3.5-4.5GHz" }, { 4499999, "3.5-4.5GHz" },
        { 4500000, "4.5GHz+" }, { 5800000, "4.5GHz+" },
    };
    const char *core, *clock;
    char klass[64], want[96];
    struct utsname u;
    unsigned n;

    for (n = 0; n < sizeof(cores) / sizeof(cores[0]); n++)
    {
        char what[48];

        machine_bands(cores[n].ncpu, 3000000, &core, &clock);
        snprintf(what, sizeof(what), "%ld cores", cores[n].ncpu);
        check_str(core, cores[n].want, what);
    }
    for (n = 0; n < sizeof(clocks) / sizeof(clocks[0]); n++)
    {
        char what[48];

        machine_bands(4, clocks[n].khz, &core, &clock);
        snprintf(what, sizeof(what), "%ld kHz", clocks[n].khz);
        check_str(clock, clocks[n].want, what);
    }
    check(machine_class(klass, sizeof(klass)) == 0, "this machine has a class");
    uname(&u);
    snprintf(want, sizeof(want), "%s/", u.machine);
    check(!strncmp(klass, want, strlen(want)), "it starts with uname's machine");
    check(strchr(klass, '/') && strchr(strchr(klass, '/') + 1, '/') && !strchr(strchr(strchr(klass, '/') + 1, '/') + 1, '/'),
          "arch/cores/clock: two slashes");
    check(!strpbrk(klass, " \t\n"), "and no white space");
    check(machine_class(klass, 5) == -1, "a buffer that is too small is refused, not cut");
    group("the_host_class_is_arch_cores_clock_with_the_contracts_bands_cut_where_the_contract_cuts_them");
}

int main(void)
{
    snprintf(dir, sizeof(dir), "/tmp/plugin-hostd-history-test.XXXXXX");
    if (!mkdtemp(dir))
        return 2;
    snprintf(file, sizeof(file), "%s/history", dir);
    test_the_keys_are_the_contracts_words();
    test_round_trip();
    test_windows();
    test_no_record_for_what_is_not_a_plugin();
    test_summary();
    test_another_host_class_is_kept_and_not_mixed();
    test_lines_this_version_cannot_read();
    test_a_second_line_of_one_binary();
    test_comments_and_blanks();
    test_blocked_files();
    test_missing_and_empty_files();
    test_the_file();
    test_a_failed_save();
    test_save_interval();
    test_clear();
    test_the_path();
    test_host_class();
    group(NULL);
    fresh();
    rmdir(dir);
    printf(failures ? "history: %d failed\n" : "history: ok\n", failures);
    return failures ? 1 : 0;
}

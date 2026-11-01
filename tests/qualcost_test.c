/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The cost the daemon reads from qualification records (src/qualcost.c), against records written out by hand: the
 * figure of the right rate and quantum, the larger of two records, the records that are not the plugin's, and the files
 * that are no records; and the cell the estimate verb reads, a cost median and a latency at one rate and quantum.
 * tests/sabotage.py breaks one rule at a time.
 *
 * Usage: qualcost-test [<test name>]
 */

#include <fcntl.h>
#include <math.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "qualcost.h"

static int g_failed;
static char g_dir[256];

#define CHECK(cond, ...) \
    do { \
        if (!(cond)) \
        { \
            fprintf(stderr, "FAIL %s:%d: ", __func__, __LINE__); \
            fprintf(stderr, __VA_ARGS__); \
            fprintf(stderr, "\n"); \
            g_failed = 1; \
            return; \
        } \
    } while (0)

static void put(const char *name, const char *text)
{
    char path[512];
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", g_dir, name);
    f = fopen(path, "w");
    if (!f || fputs(text, f) < 0)
        exit(2);
    fclose(f);
}

static void record(const char *name, const char *id, int rate, int quantum, double ns)
{
    char text[1024];

    snprintf(text, sizeof(text),
             "{\"schema\":\"plugin-qualify.qualification-record/1\",\"plugin\":{\"format\":\"clap\",\"id\":\"%s\"},"
             "\"measurements\":{\"grid\":[{\"rate\":96000,\"quantum\":64,\"outcome\":\"probe.ok\",\"cost\":{\"median\":1,"
             "\"percentile\":{\"p\":95,\"value\":1},\"blocks\":1,\"warmupBlocks\":0}},{\"rate\":%d,\"quantum\":%d,"
             "\"outcome\":\"probe.ok\",\"cost\":{\"median\":1,\"percentile\":{\"p\":95,\"value\":%.1f},\"blocks\":1,"
             "\"warmupBlocks\":0}}]}}",
             id, rate, quantum, ns);
    put(name, text);
}

/* a record of one grid point with a cost median and a latency: declared < 0 leaves the latency out, measured < 0 its
 * measuredFrames */
static void cell_record(const char *name, const char *id, int rate, int quantum, double median, int declared, int measured)
{
    char text[1024], latency[128] = "";

    if (declared >= 0 && measured >= 0)
        snprintf(latency, sizeof(latency), ",\"latency\":{\"declaredFrames\":%d,\"measuredFrames\":%d}", declared, measured);
    else if (declared >= 0)
        snprintf(latency, sizeof(latency), ",\"latency\":{\"declaredFrames\":%d}", declared);
    snprintf(text, sizeof(text),
             "{\"schema\":\"plugin-qualify.qualification-record/1\",\"plugin\":{\"format\":\"clap\",\"id\":\"%s\"},"
             "\"measurements\":{\"grid\":[{\"rate\":%d,\"quantum\":%d,\"outcome\":\"probe.ok\"%s,\"cost\":{\"median\":%.1f,"
             "\"percentile\":{\"p\":95,\"value\":%.1f},\"blocks\":1,\"warmupBlocks\":0}}]}}",
             id, rate, quantum, latency, median, median * 2);
    put(name, text);
}

static void the_cell_is_the_median_and_the_measured_latency(void)
{
    qualcost_cell_t c;

    CHECK(qualcost_cell(g_dir, "org.example.e", 48000, 128, &c) == QUALCOST_CELL_FOUND, "e has the cell");
    CHECK(c.median_ns == 3000 && c.latency_frames == 70, "the median and the measured frames: %g %g", c.median_ns,
          c.latency_frames);
}

static void a_cell_without_a_measured_latency_takes_the_declared_one(void)
{
    qualcost_cell_t c;

    CHECK(qualcost_cell(g_dir, "org.example.f", 48000, 128, &c) == QUALCOST_CELL_FOUND, "f has the cell");
    CHECK(c.latency_frames == 32, "the declared frames: %g", c.latency_frames);
}

static void a_point_without_a_latency_or_at_another_rate_is_no_cell(void)
{
    qualcost_cell_t c;

    CHECK(qualcost_cell(g_dir, "org.example.g", 48000, 128, &c) == QUALCOST_CELL_NO_POINT, "g has a cost, no latency");
    CHECK(qualcost_cell(g_dir, "org.example.a", 48000, 128, &c) == QUALCOST_CELL_NO_POINT, "a has no latency");
    CHECK(qualcost_cell(g_dir, "org.example.e", 44100, 128, &c) == QUALCOST_CELL_NO_POINT, "no such rate");
    CHECK(qualcost_cell(g_dir, "org.example.e", 48000, 256, &c) == QUALCOST_CELL_NO_POINT, "no such quantum");
}

static void a_plugin_no_record_names_has_no_record(void)
{
    qualcost_cell_t c;

    CHECK(qualcost_cell(g_dir, "org.example.c", 48000, 128, &c) == QUALCOST_CELL_NO_RECORD, "c has no record");
    CHECK(qualcost_cell(g_dir, "org.example.liar", 48000, 128, &c) == QUALCOST_CELL_NO_RECORD, "the id inside decides");
    CHECK(qualcost_cell(g_dir, "org.example.junk", 48000, 128, &c) == QUALCOST_CELL_NO_RECORD, "junk is no record");
    CHECK(qualcost_cell("/nonexistent/qualification", "org.example.e", 48000, 128, &c) == QUALCOST_CELL_NO_RECORD,
          "no directory");
}

static void the_larger_of_each_figure_of_two_records_stands(void)
{
    qualcost_cell_t c;

    CHECK(qualcost_cell(g_dir, "org.example.h", 48000, 128, &c) == QUALCOST_CELL_FOUND, "h has the cell");
    CHECK(c.median_ns == 2000 && c.latency_frames == 10, "2000 ns of one record, 10 frames of the other: %g %g",
          c.median_ns, c.latency_frames);
}

static void the_figure_is_the_p95_at_the_rate_and_quantum_as_a_fraction_of_a_core(void)
{
    double c = qualcost_read(g_dir, "org.example.a", 48000, 128);

    CHECK(fabs(c - 0.24) < 1e-12, "5000 ns per sample at 48 kHz is 0.24 of a core, not %g", c);
    c = qualcost_read(g_dir, "org.example.a", 96000, 64);
    CHECK(fabs(c - 96000.0 / 1e9) < 1e-12, "the other grid point of the record is its own figure: %g", c);
}

static void a_rate_or_quantum_the_record_lacks_is_unknown(void)
{
    CHECK(qualcost_read(g_dir, "org.example.a", 44100, 128) == -1.0, "no such rate");
    CHECK(qualcost_read(g_dir, "org.example.a", 48000, 256) == -1.0, "no such quantum");
}

static void the_larger_of_two_records_of_one_plugin_stands(void)
{
    double c = qualcost_read(g_dir, "org.example.b", 48000, 128);

    CHECK(fabs(c - 0.48) < 1e-12, "10000 ns beats 2000 ns: %g", c);
}

/* whichever of the two files the directory lists first holds the smaller figure, so a reader that keeps the first record
 * it meets gives 2000 ns and not 10000 */
static void the_larger_record_stands_whichever_the_directory_lists_first(void)
{
    double c = qualcost_read(g_dir, "org.example.d", 48000, 128);

    CHECK(fabs(c - 0.48) < 1e-12, "10000 ns beats 2000 ns, listed first or last: %g", c);
}

static void a_record_of_another_plugin_is_not_this_ones(void)
{
    CHECK(qualcost_read(g_dir, "org.example.c", 48000, 128) == -1.0, "c has no record");
    /* the file name begins with the id, the id inside is another */
    CHECK(qualcost_read(g_dir, "org.example.liar", 48000, 128) == -1.0, "the id inside the record decides");
}

static void a_file_that_is_no_record_is_skipped(void)
{
    CHECK(qualcost_read(g_dir, "org.example.junk", 48000, 128) == -1.0, "junk");
    CHECK(qualcost_read(g_dir, "org.example.empty", 48000, 128) == -1.0, "empty");
}

static void a_directory_that_is_not_there_gives_no_figure(void)
{
    CHECK(qualcost_read("/nonexistent/qualification", "org.example.a", 48000, 128) == -1.0, "no directory");
    CHECK(qualcost_read(NULL, "org.example.a", 48000, 128) == -1.0, "no name");
}

static void a_percent_encoded_iri_finds_the_record_of_its_decoded_spelling(void)
{
    record("urn_a_b@1-x.lv2.qualification.json", "urn:a b", 48000, 128, 5000);
    CHECK(fabs(qualcost_read(g_dir, "urn:a%20b", 48000, 128) - 0.24) < 1e-12, "encoded id, decoded record");
    record("urn_a_20c@1-x.lv2.qualification.json", "urn:a%20c", 48000, 128, 5000);
    CHECK(fabs(qualcost_read(g_dir, "urn:a%20c", 48000, 128) - 0.24) < 1e-12, "same spelling still finds it");
    CHECK(qualcost_read(g_dir, "urn:a%2", 48000, 128) == -1.0, "a stray percent is no escape");
}


/* the daemon reads a plugin's records on every add, from a directory of thousands: a repeat read neither lists the
 * directory again nor parses a record it parsed, while a record replaced (written and renamed in, as plugin-qualify
 * writes), rewritten in place, or added is read as a fresh read reads it */
static void a_repeat_read_lists_and_parses_once_and_a_change_is_read(void)
{
    static const char *const name = "org.example.m@1.0-eeeeeeeeeeee.default.qualification.json";
    char path[512], tmp[512];
    struct timespec t[2] = { { 0, 0 }, { 1700000000, 0 } };
    unsigned long scans, parses;
    double c;

    record(name, "org.example.m", 48000, 128, 3000);
    c = qualcost_read(g_dir, "org.example.m", 48000, 128);
    CHECK(c > 0, "the record is read: %g", c);
    scans = qualcost_dir_scans;
    parses = qualcost_record_parses;
    c = qualcost_read(g_dir, "org.example.m", 48000, 128);
    CHECK(qualcost_dir_scans == scans && qualcost_record_parses == parses,
          "a repeat read lists the directory %lu more times and parses %lu more records", qualcost_dir_scans - scans,
          qualcost_record_parses - parses);
    /* replaced: written beside it and renamed over it */
    snprintf(path, sizeof(path), "%s/%s", g_dir, name);
    snprintf(tmp, sizeof(tmp), "%s/.tmp-m", g_dir);
    record(".tmp-m", "org.example.m", 48000, 128, 6000);
    CHECK(rename(tmp, path) == 0, "renamed in");
    CHECK(qualcost_read(g_dir, "org.example.m", 48000, 128) > 1.9 * c, "a replaced record is read again");
    /* rewritten in place, the directory unchanged: its own time says so */
    c = qualcost_read(g_dir, "org.example.m", 48000, 128);
    record(name, "org.example.m", 48000, 128, 12000);
    t[0].tv_sec = 1700000000;
    t[0].tv_nsec = t[1].tv_nsec = 123;
    CHECK(utimensat(AT_FDCWD, path, t, 0) == 0, "its time set apart");
    CHECK(qualcost_read(g_dir, "org.example.m", 48000, 128) > 1.9 * c, "a record rewritten in place is read again");
    /* another record of the plugin added: the larger stands */
    c = qualcost_read(g_dir, "org.example.m", 48000, 128);
    record("org.example.m@2.0-ffffffffffff.default.qualification.json", "org.example.m", 48000, 128, 50000);
    CHECK(qualcost_read(g_dir, "org.example.m", 48000, 128) > 3.9 * c, "a record added is read");
}

static const struct { const char *name; void (*fn)(void); } g_tests[] = {
#define T(f) { #f, f }
    T(a_percent_encoded_iri_finds_the_record_of_its_decoded_spelling),
    T(the_figure_is_the_p95_at_the_rate_and_quantum_as_a_fraction_of_a_core),
    T(a_rate_or_quantum_the_record_lacks_is_unknown),
    T(the_larger_of_two_records_of_one_plugin_stands),
    T(the_larger_record_stands_whichever_the_directory_lists_first),
    T(a_record_of_another_plugin_is_not_this_ones),
    T(a_file_that_is_no_record_is_skipped),
    T(a_directory_that_is_not_there_gives_no_figure),
    T(the_cell_is_the_median_and_the_measured_latency),
    T(a_cell_without_a_measured_latency_takes_the_declared_one),
    T(a_point_without_a_latency_or_at_another_rate_is_no_cell),
    T(a_plugin_no_record_names_has_no_record),
    T(the_larger_of_each_figure_of_two_records_stands),
    T(a_repeat_read_lists_and_parses_once_and_a_change_is_read),
#undef T
};

int main(int argc, char **argv)
{
    size_t n, ran = 0;
    int bad = 0;
    char cmd[300];

    snprintf(g_dir, sizeof(g_dir), "/tmp/qualcost-test.%d", (int)getpid());
    if (mkdir(g_dir, 0700) != 0)
        return 2;
    record("org.example.a@1.0-aaaaaaaaaaaa.default.qualification.json", "org.example.a", 48000, 128, 5000);
    record("org.example.b@1.0-bbbbbbbbbbbb.default.qualification.json", "org.example.b", 48000, 128, 2000);
    record("org.example.b@2.0-cccccccccccc.default.qualification.json", "org.example.b", 48000, 128, 10000);
    record("org.example.liar@1.0-dddddddddddd.default.qualification.json", "org.example.other", 48000, 128, 5000);
    {
        /* two records of one plugin: the one the directory lists first is made the smaller */
        const char *names[2] = { "org.example.d@1.0-111111111111.default.qualification.json",
                                 "org.example.d@2.0-222222222222.default.qualification.json" };
        char first[300] = "";
        struct dirent *e;
        DIR *d;
        int k;

        record(names[0], "org.example.d", 48000, 128, 2000);
        record(names[1], "org.example.d", 48000, 128, 2000);
        if (!(d = opendir(g_dir)))
            return 2;
        while ((e = readdir(d)) != NULL)
            if (!strncmp(e->d_name, "org.example.d@", 14))
            {
                snprintf(first, sizeof(first), "%s", e->d_name);
                break;
            }
        closedir(d);
        for (k = 0; k < 2; k++)
            if (strcmp(first, names[k]))
                record(names[k], "org.example.d", 48000, 128, 10000);
    }
    cell_record("org.example.e@1.0-eeeeeeeeeee1.default.qualification.json", "org.example.e", 48000, 128, 3000, 64, 70);
    cell_record("org.example.f@1.0-fffffffffff1.default.qualification.json", "org.example.f", 48000, 128, 1000, 32, -1);
    cell_record("org.example.g@1.0-999999999999.default.qualification.json", "org.example.g", 48000, 128, 1000, -1, -1);
    cell_record("org.example.h@1.0-888888888888.default.qualification.json", "org.example.h", 48000, 128, 1000, 0, 10);
    cell_record("org.example.h@2.0-777777777777.default.qualification.json", "org.example.h", 48000, 128, 2000, 0, 5);
    put("org.example.junk@1.0-eeeeeeeeeeee.default.qualification.json", "{not json");
    put("org.example.empty@1.0-ffffffffffff.default.qualification.json", "");
    for (n = 0; n < sizeof(g_tests) / sizeof(g_tests[0]); n++)
    {
        if (argc > 1 && strcmp(argv[1], g_tests[n].name))
            continue;
        g_failed = 0;
        g_tests[n].fn();
        ran++;
        if (g_failed)
            bad++;
        else
            printf("ok   %s\n", g_tests[n].name);
    }
    snprintf(cmd, sizeof(cmd), "rm -rf %s", g_dir);
    if (system(cmd) != 0)
        bad++;
    if (!ran)
        return 2;
    printf("qualcost tests %s (%zu run, %d failed)\n", bad ? "FAILED" : "ok", ran, bad);
    return bad ? 1 : 0;
}

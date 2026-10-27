/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The cost the daemon reads from qualification records (src/qualcost.c), against records written out by hand: the
 * figure of the right rate and quantum, the larger of two records, the records that are not the plugin's, and the files
 * that are no records. tests/sabotage.py breaks one rule at a time.
 *
 * Usage: qualcost-test [<test name>]
 */

#include <math.h>
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

static const struct { const char *name; void (*fn)(void); } g_tests[] = {
#define T(f) { #f, f }
    T(the_figure_is_the_p95_at_the_rate_and_quantum_as_a_fraction_of_a_core),
    T(a_rate_or_quantum_the_record_lacks_is_unknown),
    T(the_larger_of_two_records_of_one_plugin_stands),
    T(a_record_of_another_plugin_is_not_this_ones),
    T(a_file_that_is_no_record_is_skipped),
    T(a_directory_that_is_not_there_gives_no_figure),
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

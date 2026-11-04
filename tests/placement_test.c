/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The core placement (src/placement.c, docs/placement.md) on its own, against answers worked out by hand: the cpu lists
 * it reads and the audio and reserved cores it makes of a mask and of audio_cores. Every worker is pinned to all the
 * audio cores, which tests/daemon_test.py checks on the processes. tests/sabotage.py breaks a rule and names the test
 * that must go red.
 *
 * Usage: placement-test [<test name>]   one test, or all of them; "ok   <name>" for each that passes, exit 1 if one fails
 */

#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "placement.h"

static int g_failed;

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

static cpu_set_t set_of(const char *list)
{
    cpu_set_t s;

    if (placement_parse(list, &s) != 0)
        CPU_ZERO(&s);
    return s;
}

static const char *text_of(const cpu_set_t *s)
{
    static char buf[4][256];
    static int k;

    k = (k + 1) % 4;
    placement_list_text(s, buf[k], sizeof(buf[k]));
    return buf[k];
}

/* ---------------------------------------------------------------- cpu lists */

static void a_cpu_list_is_read_as_the_kernel_writes_it_and_anything_else_is_refused(void)
{
    static const char *const bad[] = { "", "x", "1-", "-1", "3-1", "1,,2", "1,", "1 2", "0x1", "1024", "1-1024", "+1" };
    cpu_set_t s;
    size_t k;

    CHECK(placement_parse("0-2,5,7-8", &s) == 0, "a list");
    CHECK(!strcmp(text_of(&s), "0-2,5,7-8"), "read back as %s", text_of(&s));
    CHECK(CPU_COUNT(&s) == 6, "six cpus, %d", CPU_COUNT(&s));
    CHECK(placement_parse("3", &s) == 0 && !strcmp(text_of(&s), "3"), "one cpu");
    for (k = 0; k < sizeof(bad) / sizeof(bad[0]); k++)
        CHECK(placement_parse(bad[k], &s) != 0, "'%s' is no cpu list", bad[k]);
}

/* ---------------------------------------------------------------- the cores */

static void the_default_audio_cores_are_the_mask_less_its_lowest_cpu_which_is_reserved(void)
{
    cpu_set_t allowed = set_of("0-3"), audio, reserved;

    CHECK(placement_cores(&allowed, "", NULL, &audio, &reserved) == 0, "a 4-core mask");
    CHECK(!strcmp(text_of(&audio), "1-3") && !strcmp(text_of(&reserved), "0"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* a mask a taskset or a cgroup gave: its own lowest cpu */
    allowed = set_of("4-7,12");
    CHECK(placement_cores(&allowed, "", NULL, &audio, &reserved) == 0, "a mask from 4");
    CHECK(!strcmp(text_of(&audio), "5-7,12") && !strcmp(text_of(&reserved), "4"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* one cpu: no audio core is left */
    allowed = set_of("2");
    CHECK(placement_cores(&allowed, "", NULL, &audio, &reserved) == 0, "one cpu");
    CHECK(CPU_COUNT(&audio) == 0 && !strcmp(text_of(&reserved), "2"), "audio %s, reserved %s", text_of(&audio), text_of(&reserved));
}

static void audio_cores_names_the_audio_cores_inside_the_mask_and_the_rest_is_reserved(void)
{
    cpu_set_t allowed = set_of("0-3"), audio, reserved;

    CHECK(placement_cores(&allowed, "2,3", NULL, &audio, &reserved) == 0, "two of four");
    CHECK(!strcmp(text_of(&audio), "2-3") && !strcmp(text_of(&reserved), "0-1"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* every cpu: nothing is reserved */
    CHECK(placement_cores(&allowed, "0-3", NULL, &audio, &reserved) == 0, "all four");
    CHECK(!strcmp(text_of(&audio), "0-3") && CPU_COUNT(&reserved) == 0, "audio %s, reserved %s", text_of(&audio),
          text_of(&reserved));
    CHECK(placement_cores(&allowed, "3-4", NULL, &audio, &reserved) != 0, "a cpu outside the mask refuses");
    CHECK(placement_cores(&allowed, "two", NULL, &audio, &reserved) != 0, "a word that is no list refuses");
}

/* ---------------------------------------------------------------- the capacity of the cpus */

/* a fake /sys/devices/system/cpu: for cpu n, files[n] of `name` holding values[n] (0 writes none); its path */
static char *fake_sysfs(const char *name, const long *values, int n)
{
    static char dir[64];
    char path[256], sub[256];
    int c;
    FILE *f;

    snprintf(dir, sizeof(dir), "/tmp/placement-test.XXXXXX");
    if (!mkdtemp(dir))
        return NULL;
    for (c = 0; c < n; c++)
    {
        snprintf(path, sizeof(path), "%s/cpu%d", dir, c);
        mkdir(path, 0755);
        snprintf(sub, sizeof(sub), "%s/cpufreq", path);
        mkdir(sub, 0755);
        if (!values[c])
            continue;
        snprintf(path, sizeof(path), "%s/cpu%d/%s", dir, c, name);
        if ((f = fopen(path, "w")))
        {
            fprintf(f, "%ld\n", values[c]);
            fclose(f);
        }
    }
    return dir;
}

static void add_file(const char *dir, int c, const char *name, long value)
{
    char path[256];
    FILE *f;

    snprintf(path, sizeof(path), "%s/cpu%d/%s", dir, c, name);
    if ((f = fopen(path, "w")))
    {
        fprintf(f, "%ld\n", value);
        fclose(f);
    }
}

static void rm_tree(const char *dir)
{
    char cmd[300];

    snprintf(cmd, sizeof(cmd), "rm -rf '%s'", dir);
    if (system(cmd) != 0)
        fprintf(stderr, "could not remove %s\n", dir);
}

static void on_a_hybrid_cpu_the_reserved_core_is_the_one_of_least_capacity(void)
{
    /* two performance cores of 1000 and two efficiency cores of 765, as cpu_capacity says on an Intel hybrid */
    long values[4] = { 1000, 1000, 765, 765 }, capacity[CPU_SETSIZE];
    cpu_set_t allowed = set_of("0-3"), audio, reserved;
    char *dir = fake_sysfs("cpu_capacity", values, 4);

    CHECK(dir, "a fake sysfs");
    CHECK(placement_capacities(dir, &allowed, capacity) == 1, "the capacities are read");
    rm_tree(dir);
    CHECK(placement_cores(&allowed, "", capacity, &audio, &reserved) == 0, "a hybrid 4-core mask");
    CHECK(!strcmp(text_of(&reserved), "2") && !strcmp(text_of(&audio), "0-1,3"),
          "the lowest efficiency core is reserved, every performance core is audio: audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
}

static void with_no_cpu_capacity_the_maximum_frequency_decides_and_a_partial_capacity_is_not_read(void)
{
    /* cpu_capacity on three cpus only, so it is not read; the maximum frequencies name cpu 3 the least */
    long caps[4] = { 1024, 1024, 979, 0 }, capacity[CPU_SETSIZE];
    cpu_set_t allowed = set_of("0-3"), audio, reserved;
    char *dir = fake_sysfs("cpu_capacity", caps, 4);

    CHECK(dir, "a fake sysfs");
    add_file(dir, 0, "cpufreq/cpuinfo_max_freq", 5300000);
    add_file(dir, 1, "cpufreq/cpuinfo_max_freq", 5300000);
    add_file(dir, 2, "cpufreq/cpuinfo_max_freq", 5300000);
    add_file(dir, 3, "cpufreq/cpuinfo_max_freq", 4700000);
    CHECK(placement_capacities(dir, &allowed, capacity) == 1 && capacity[2] == 5300000, "the frequencies are read");
    rm_tree(dir);
    CHECK(placement_cores(&allowed, "", capacity, &audio, &reserved) == 0 && !strcmp(text_of(&reserved), "3"),
          "the slowest cpu is reserved: %s", text_of(&reserved));
}

static void on_a_homogeneous_cpu_or_with_nothing_read_the_lowest_cpu_is_reserved_as_before(void)
{
    long values[4] = { 1024, 1024, 1024, 1024 }, capacity[CPU_SETSIZE];
    cpu_set_t allowed = set_of("0-3"), audio, reserved;
    char *dir = fake_sysfs("cpu_capacity", values, 4);

    CHECK(dir, "a fake sysfs");
    CHECK(placement_capacities(dir, &allowed, capacity) == 1, "the capacities are read");
    rm_tree(dir);
    CHECK(placement_cores(&allowed, "", capacity, &audio, &reserved) == 0 && !strcmp(text_of(&reserved), "0"),
          "a tie keeps the lowest cpu: %s", text_of(&reserved));
    CHECK(placement_capacities("/nonexistent", &allowed, capacity) == 0 && capacity[0] == 0, "no sysfs, nothing read");
    CHECK(placement_cores(&allowed, "", capacity, &audio, &reserved) == 0 && !strcmp(text_of(&reserved), "0"),
          "nothing known keeps the lowest cpu: %s", text_of(&reserved));
    /* audio_cores, when given, is the list whatever the capacities */
    capacity[2] = -1;
    CHECK(placement_cores(&allowed, "1-3", capacity, &audio, &reserved) == 0 && !strcmp(text_of(&reserved), "0"),
          "audio_cores decides: %s", text_of(&reserved));
}

/* ---------------------------------------------------------------- the run */

static const struct {
    const char *name;
    void (*fn)(void);
} g_tests[] = {
#define T(f) { #f, f }
    T(a_cpu_list_is_read_as_the_kernel_writes_it_and_anything_else_is_refused),
    T(the_default_audio_cores_are_the_mask_less_its_lowest_cpu_which_is_reserved),
    T(audio_cores_names_the_audio_cores_inside_the_mask_and_the_rest_is_reserved),
    T(on_a_hybrid_cpu_the_reserved_core_is_the_one_of_least_capacity),
    T(with_no_cpu_capacity_the_maximum_frequency_decides_and_a_partial_capacity_is_not_read),
    T(on_a_homogeneous_cpu_or_with_nothing_read_the_lowest_cpu_is_reserved_as_before),
#undef T
};

int main(int argc, char **argv)
{
    size_t n, ran = 0;
    int bad = 0;

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
    if (!ran)
    {
        fprintf(stderr, "no test named %s\n", argc > 1 ? argv[1] : "");
        return 2;
    }
    printf("placement tests %s (%zu run, %d failed)\n", bad ? "FAILED" : "ok", ran, bad);
    return bad ? 1 : 0;
}

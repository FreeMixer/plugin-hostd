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

    CHECK(placement_cores(&allowed, "", &audio, &reserved) == 0, "a 4-core mask");
    CHECK(!strcmp(text_of(&audio), "1-3") && !strcmp(text_of(&reserved), "0"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* a mask a taskset or a cgroup gave: its own lowest cpu */
    allowed = set_of("4-7,12");
    CHECK(placement_cores(&allowed, "", &audio, &reserved) == 0, "a mask from 4");
    CHECK(!strcmp(text_of(&audio), "5-7,12") && !strcmp(text_of(&reserved), "4"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* one cpu: no audio core is left */
    allowed = set_of("2");
    CHECK(placement_cores(&allowed, "", &audio, &reserved) == 0, "one cpu");
    CHECK(CPU_COUNT(&audio) == 0 && !strcmp(text_of(&reserved), "2"), "audio %s, reserved %s", text_of(&audio), text_of(&reserved));
}

static void audio_cores_names_the_audio_cores_inside_the_mask_and_the_rest_is_reserved(void)
{
    cpu_set_t allowed = set_of("0-3"), audio, reserved;

    CHECK(placement_cores(&allowed, "2,3", &audio, &reserved) == 0, "two of four");
    CHECK(!strcmp(text_of(&audio), "2-3") && !strcmp(text_of(&reserved), "0-1"), "audio %s, reserved %s",
          text_of(&audio), text_of(&reserved));
    /* every cpu: nothing is reserved */
    CHECK(placement_cores(&allowed, "0-3", &audio, &reserved) == 0, "all four");
    CHECK(!strcmp(text_of(&audio), "0-3") && CPU_COUNT(&reserved) == 0, "audio %s, reserved %s", text_of(&audio),
          text_of(&reserved));
    CHECK(placement_cores(&allowed, "3-4", &audio, &reserved) != 0, "a cpu outside the mask refuses");
    CHECK(placement_cores(&allowed, "two", &audio, &reserved) != 0, "a word that is no list refuses");
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

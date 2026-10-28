/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The core placement (src/placement.c, docs/placement.md) on its own, against answers worked out by hand: the cpu lists
 * it reads, the audio and reserved cores it makes of a mask and of audio_cores, and the core it picks for a new worker by
 * the least-loaded rule. tests/sabotage.py breaks a rule and names the test that must go red.
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

/* ---------------------------------------------------------------- the pick */

static placement_load_t load(int core, int workers, double cost, int unknown)
{
    placement_load_t l = { core, workers, cost, unknown };

    return l;
}

static void with_no_cost_known_the_core_with_the_fewest_workers_is_picked_the_lowest_of_a_tie(void)
{
    placement_load_t l[3] = { load(1, 0, 0, 0), load(2, 0, 0, 0), load(3, 0, 0, 0) };
    int k, want[] = { 1, 2, 3, 1, 2, 3, 1 };

    /* four workers on a 4-core mask: 1, 2, 3, then 1 again; the next three follow round */
    for (k = 0; k < 7; k++)
    {
        int at = placement_pick(l, 3);

        CHECK(at >= 0 && l[at].core == want[k], "worker %d on core %d, wanted %d", k, at >= 0 ? l[at].core : -1, want[k]);
        l[at].workers++;
        l[at].unknown++;
    }
    CHECK(placement_pick(l, 0) == -1, "no core, no pick");
}

static void with_every_cost_known_the_cheapest_core_is_picked_whatever_it_holds(void)
{
    /* 60 % on core 1, 10 % on 2 and on 3: the next goes to 2, the count would say 1 */
    placement_load_t l[3] = { load(1, 1, 0.6, 0), load(2, 1, 0.1, 0), load(3, 1, 0.1, 0) };

    CHECK(l[placement_pick(l, 3)].core == 2, "the cheapest, the lowest of a tie: %d", l[placement_pick(l, 3)].core);
    l[1].workers++;
    l[1].cost += 0.1;
    CHECK(l[placement_pick(l, 3)].core == 3, "then the other cheap one: %d", l[placement_pick(l, 3)].core);
    /* two workers of 5 % weigh less than one of 20 % */
    l[0] = load(1, 2, 0.1, 0);
    l[1] = load(2, 1, 0.2, 0);
    l[2] = load(3, 1, 0.2, 0);
    CHECK(l[placement_pick(l, 3)].core == 1, "by cost, not count: %d", l[placement_pick(l, 3)].core);
}

static void one_placed_worker_of_unknown_cost_makes_the_count_decide(void)
{
    placement_load_t l[3] = { load(1, 1, 0.1, 0), load(2, 2, 0.0, 2), load(3, 2, 0.1, 1) };

    CHECK(l[placement_pick(l, 3)].core == 1, "the fewest workers: %d", l[placement_pick(l, 3)].core);
    /* a tie of the count goes to the cheaper known cost, then to the lower core */
    l[0] = load(1, 2, 0.3, 0);
    l[1] = load(2, 2, 0.1, 1);
    l[2] = load(3, 2, 0.1, 1);
    CHECK(l[placement_pick(l, 3)].core == 2, "a tie of the count: %d", l[placement_pick(l, 3)].core);
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
    T(with_no_cost_known_the_core_with_the_fewest_workers_is_picked_the_lowest_of_a_tie),
    T(with_every_cost_known_the_cheapest_core_is_picked_whatever_it_holds),
    T(one_placed_worker_of_unknown_cost_makes_the_count_decide),
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

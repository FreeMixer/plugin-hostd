/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The grouping planner (src/planner.c) on its own, against plans worked out by hand: one test for each reason it gives,
 * the order the rules decide in, the median a member of unknown cost counts as, the text of a plan, and that the same
 * members give the same bytes. tests/sabotage.py breaks one rule at a time and names the test that must go red.
 *
 * Usage: planner-test [<test name>]   one test, or all of them; "ok   <name>" for each that passes, exit 1 if one fails
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <plugin-hostd/plugin_hostd_vocabulary.h>
#include <plugin-hostd/protocol.h>

#include "planner.h"

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

#define MEMBERS(a) ((int)(sizeof(a) / sizeof((a)[0])))

/* a member of the CLAP program's chain class with a pin that lets it share and a small cost */
static planner_member_t member(int id)
{
    planner_member_t m = { id, "omx-clap-host", PLANNER_PIN_IN_PROCESS, 1, 0.01, NULL };

    return m;
}

static planner_member_t unknown(int id)
{
    planner_member_t m = member(id);

    m.cost = PLANNER_COST_UNKNOWN;
    return m;
}

static planner_member_t costed(int id, double cost)
{
    planner_member_t m = member(id);

    m.cost = cost;
    return m;
}

/* require_pins, first-use pins, grouping on, no limits */
static planner_settings_t settings(void)
{
    planner_settings_t s = { 1, 1, 1, 0, 0, 0 };

    return s;
}

static char *segments(const planner_member_t *m, const planner_plan_t *p)
{
    static char text[256];

    planner_format_segments(m, p, text, sizeof(text));
    return text;
}

static char *reasons(const planner_member_t *m, const planner_plan_t *p)
{
    static char text[512];

    planner_format_reasons(m, p, 0, text, sizeof(text));
    return text;
}

static int plan(const planner_settings_t *s, const planner_member_t *m, int n, planner_plan_t *p)
{
    memset(p, 0xaa, sizeof(*p));
    return planner_plan(s, m, n, p);
}

/* ---------------------------------------------------------------- the words are the declaration's */

static void the_reasons_are_the_words_of_the_declaration(void)
{
    static const char *const want[] = {
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_REFUSED, OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_PIN,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_VERDICT, OMX_PLUGIN_HOSTD_GROUPING_REASONS_VERDICT_ISOLATED,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_FORMAT_WORLD, OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_CRASHED,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_XRUNS, OMX_PLUGIN_HOSTD_GROUPING_REASONS_COST_OVER,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_FORMAT_MIXED, OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUP_FULL,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUP_COST, OMX_PLUGIN_HOSTD_GROUPING_REASONS_COST_ASSUMED,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_NO_NEIGHBOUR, OMX_PLUGIN_HOSTD_GROUPING_REASONS_GROUPING_OFF,
        OMX_PLUGIN_HOSTD_GROUPING_REASONS_HISTORY_UNAVAILABLE, OMX_PLUGIN_HOSTD_GROUPING_REASONS_PLAN_REFUSED,
    };
    int r;

    CHECK(MEMBERS(want) == PLANNER_REASON_COUNT && OMX_PLUGIN_HOSTD_GROUPING_REASONS_COUNT == PLANNER_REASON_COUNT,
          "the declaration has %u reasons, the planner %d", OMX_PLUGIN_HOSTD_GROUPING_REASONS_COUNT, PLANNER_REASON_COUNT);
    for (r = 0; r < PLANNER_REASON_COUNT; r++)
        CHECK(planner_reason_word(r) && !strcmp(planner_reason_word(r), want[r]), "reason %d is %s, not %s", r,
              planner_reason_word(r), want[r]);
    CHECK(planner_reason_word(PLANNER_REASON_NONE) == NULL && planner_reason_word(PLANNER_REASON_COUNT) == NULL,
          "a number that is no reason has no word");
}

/* ---------------------------------------------------------------- one test per reason */

/* A B C D E with the middle one unfit becomes [A B] [C] [D E]: C is alone for `reason`, the others have nothing to say */
static void unfit_middle(const char *what, planner_member_t c, const planner_settings_t *s, int reason, const char *word)
{
    planner_member_t m[5] = { member(1), member(2), c, member(4), member(5) };
    planner_plan_t p;
    char want[64];

    c.id = 3;
    m[2] = c;
    CHECK(plan(s, m, 5, &p) == 0, "%s: planned", what);
    CHECK(!strcmp(segments(m, &p), "1,2;3;4,5"), "%s: the segments are %s", what, segments(m, &p));
    snprintf(want, sizeof(want), "3:%s", word);
    CHECK(p.reason[2] == reason, "%s: member 3 has reason %d, not %d", what, p.reason[2], reason);
    CHECK(!strcmp(reasons(m, &p), want), "%s: the reasons are %s, not %s", what, reasons(m, &p), want);
    CHECK(p.nseg == 3 && p.seg_len[0] == 2 && p.seg_len[1] == 1 && p.seg_len[2] == 2, "%s: the lengths", what);
}

static void refused_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    c.pin = PLANNER_PIN_REFUSED;
    unfit_middle("a refused pin", c, &s, PLANNER_REASON_REFUSED, "refused");
}

static void no_pin_under_strict_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    s.pins_first_use = 0;
    c.pin = PLANNER_PIN_NONE;
    unfit_middle("no pin under strict", c, &s, PLANNER_REASON_NO_PIN, "no-pin");
}

static void no_verdict_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    c.pin = PLANNER_PIN_NO_VERDICT;
    unfit_middle("a learned pin", c, &s, PLANNER_REASON_NO_VERDICT, "no-verdict");
}

static void a_pin_that_is_gone_under_first_use_has_no_verdict(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    c.pin = PLANNER_PIN_NONE;
    unfit_middle("no pin under first-use", c, &s, PLANNER_REASON_NO_VERDICT, "no-verdict");
}

static void verdict_isolated_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    c.pin = PLANNER_PIN_ISOLATED;
    unfit_middle("verdict isolated", c, &s, PLANNER_REASON_VERDICT_ISOLATED, "verdict-isolated");
}

static void format_world_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);

    c.world_ok = 0;
    unfit_middle("no world for the format", c, &s, PLANNER_REASON_FORMAT_WORLD, "format-world");
}

static void cost_over_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();

    s.group_cost_max = 0.5;
    unfit_middle("one member over the limit", costed(3, 0.51), &s, PLANNER_REASON_COST_OVER, "cost-over");
}

/* a member that exactly meets the limit is not over it */
static void a_cost_at_the_limit_is_not_over(void)
{
    planner_settings_t s = settings();
    planner_member_t m[2] = { costed(1, 0.5), costed(2, 0.0) };
    planner_plan_t p;

    s.group_cost_max = 0.5;
    CHECK(plan(&s, m, 2, &p) == 0 && !strcmp(segments(m, &p), "1,2"), "0.5 against 0.5 joins: %s", segments(m, &p));
}

static void format_mixed_starts_a_new_segment(void)
{
    planner_settings_t s = settings();
    planner_member_t m[4] = { member(1), member(2), member(3), member(4) };
    planner_plan_t p;

    m[2].klass = "mod-host";
    m[3].klass = "mod-host";
    CHECK(plan(&s, m, 4, &p) == 0, "planned");
    CHECK(!strcmp(segments(m, &p), "1,2;3,4"), "a program that does not run the others' chains starts a segment: %s", segments(m, &p));
    CHECK(p.reason[2] == PLANNER_REASON_FORMAT_MIXED && p.reason[0] == PLANNER_REASON_NONE &&
          p.reason[1] == PLANNER_REASON_NONE && p.reason[3] == PLANNER_REASON_NONE, "member 3 says why, the others nothing");
    CHECK(!strcmp(reasons(m, &p), "3:format-mixed"), "the reasons are %s", reasons(m, &p));
}

static void group_full_starts_a_new_segment(void)
{
    planner_settings_t s = settings();
    planner_member_t m[5] = { member(1), member(2), member(3), member(4), member(5) };
    planner_plan_t p;

    s.group_max = 2;
    CHECK(plan(&s, m, 5, &p) == 0, "planned");
    CHECK(!strcmp(segments(m, &p), "1,2;3,4;5"), "two to a segment: %s", segments(m, &p));
    CHECK(p.reason[2] == PLANNER_REASON_GROUP_FULL && p.reason[3] == PLANNER_REASON_NONE &&
          p.reason[4] == PLANNER_REASON_GROUP_FULL, "the members that start a segment say why: %s", reasons(m, &p));
    CHECK(!strcmp(reasons(m, &p), "3:group-full,5:group-full"), "the reasons are %s", reasons(m, &p));
}

static void group_max_zero_is_no_limit(void)
{
    planner_settings_t s = settings();
    planner_member_t m[PLANNER_MEMBERS_MAX];
    planner_plan_t p;
    int k;

    for (k = 0; k < PLANNER_MEMBERS_MAX; k++)
        m[k] = member(k + 1);
    CHECK(plan(&s, m, PLANNER_MEMBERS_MAX, &p) == 0 && p.nseg == 1 && p.seg_len[0] == PLANNER_MEMBERS_MAX,
          "all %d in one segment, not %d", PLANNER_MEMBERS_MAX, p.nseg);
}

static void group_cost_starts_a_new_segment(void)
{
    planner_settings_t s = settings();
    planner_member_t m[4] = { costed(1, 0.25), costed(2, 0.25), costed(3, 0.25), costed(4, 0.25) };
    planner_plan_t p;

    s.group_cost_max = 0.6;
    CHECK(plan(&s, m, 4, &p) == 0, "planned");
    CHECK(!strcmp(segments(m, &p), "1,2;3,4"), "0.5 fits under 0.6, 0.75 does not: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "3:group-cost"), "the reasons are %s", reasons(m, &p));
}

/* a segment's costs add: three of 0.25 are over 0.7 on the third, though each is far under it alone */
static void the_costs_of_a_segment_add_up(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { costed(1, 0.25), costed(2, 0.25), costed(3, 0.25) };
    planner_plan_t p;

    s.group_cost_max = 0.7;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2;3"), "the third is over: %s", segments(m, &p));
    CHECK(p.reason[2] == PLANNER_REASON_GROUP_COST, "and says group-cost");
    s.group_cost_max = 0.75;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "0.75 holds all three: %s", segments(m, &p));
}

/* a member of unknown cost counts as the median of the known costs of its segment: three known at 1/8, 1/2 and 1/4 add
 * 7/8 and have the median 1/4, so the first unknown member makes 9/8 and the second 11/8, which is over 5/4 (the costs
 * are halves and quarters, so the sums are exact) */
static void a_member_of_unknown_cost_counts_as_the_median_of_its_segment(void)
{
    planner_settings_t s = settings();
    planner_member_t m[5] = { costed(1, 0.125), costed(2, 0.5), costed(3, 0.25), unknown(4), unknown(5) };
    planner_plan_t p;

    s.group_cost_max = 1.25;
    CHECK(plan(&s, m, 5, &p) == 0, "planned");
    CHECK(!strcmp(segments(m, &p), "1,2,3,4;5"), "9/8 fits 5/4, 11/8 does not: %s", segments(m, &p));
    CHECK(p.reason[3] == PLANNER_REASON_COST_ASSUMED && p.reason[4] == PLANNER_REASON_GROUP_COST, "the reasons: %s", reasons(m, &p));
    CHECK(!strcmp(reasons(m, &p), "4:cost-assumed,5:group-cost"), "the reasons are %s", reasons(m, &p));
}

/* the median of an even number is the mean of the middle two */
static void the_median_of_an_even_number_is_the_mean_of_the_middle_two(void)
{
    planner_settings_t s = settings();
    planner_member_t m[4] = { costed(1, 0.0625), costed(2, 0.1875), unknown(3), unknown(4) };
    planner_plan_t p;

    /* 1/16 and 3/16 known: the median is 1/8, so the third makes 3/8 and the fourth 1/2 */
    s.group_cost_max = 0.45;
    CHECK(plan(&s, m, 4, &p) == 0 && !strcmp(segments(m, &p), "1,2,3;4"), "1/8 more is over 0.45 on the fourth: %s", segments(m, &p));
    s.group_cost_max = 0.5;
    CHECK(plan(&s, m, 4, &p) == 0 && !strcmp(segments(m, &p), "1,2,3,4"), "1/2 holds all four: %s", segments(m, &p));
}

/* with no cost known in the segment a member counts for nothing, and says so */
static void members_of_unknown_cost_alone_in_a_segment_count_for_nothing(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { unknown(1), unknown(2), unknown(3) };
    planner_plan_t p;

    s.group_cost_max = 0.01;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "no cost, no limit reached: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "1:cost-assumed,2:cost-assumed,3:cost-assumed"), "each says so: %s", reasons(m, &p));
}

static void cost_assumed_is_said_of_a_member_that_joined_on_an_assumption(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { costed(1, 0.1), unknown(2), costed(3, 0.1) };
    planner_plan_t p;

    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "one segment: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "2:cost-assumed"), "only the member without a cost says so: %s", reasons(m, &p));
}

static void no_neighbour_is_said_of_a_member_alone_for_the_members_around_it(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { member(1), member(2), member(3) };
    planner_plan_t p;

    m[1].pin = PLANNER_PIN_ISOLATED;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1;2;3"), "all alone: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "1:no-neighbour,2:verdict-isolated,3:no-neighbour"),
          "the unfit one says why, its neighbours that they have no one: %s", reasons(m, &p));
    CHECK(plan(&s, m, 1, &p) == 0 && !strcmp(segments(m, &p), "1") && !strcmp(reasons(m, &p), "1:no-neighbour"),
          "a plan of one member is a member with no neighbour: %s", reasons(m, &p));
}

static void grouping_off_says_what_would_have_shared(void)
{
    planner_settings_t s = settings();
    planner_member_t m[4] = { member(1), member(2), member(3), costed(4, 0.1) };
    planner_plan_t p;

    m[2].pin = PLANNER_PIN_ISOLATED;
    s.grouping_on = 0;
    CHECK(plan(&s, m, 4, &p) == 0, "planned");
    CHECK(!strcmp(segments(m, &p), "1,2;3;4"), "the plan is the one grouping on would make: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "1:grouping-off,2:grouping-off,3:verdict-isolated,4:no-neighbour"),
          "the members of a segment that is not applied say so, the others as before: %s", reasons(m, &p));
    s.grouping_on = 1;
    CHECK(plan(&s, m, 4, &p) == 0 && !strcmp(segments(m, &p), "1,2;3;4"), "on: the same segments");
    CHECK(!strcmp(reasons(m, &p), "3:verdict-isolated,4:no-neighbour"), "on: %s", reasons(m, &p));
}

static void a_refused_plan_gives_every_member_the_refusal(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { member(7), member(8), member(9) };
    planner_plan_t p;
    char text[128];

    CHECK(plan(&s, m, 3, &p) == 0, "planned");
    planner_format_reasons(m, &p, OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP, text, sizeof(text));
    CHECK(!strcmp(text, "7:plan-refused:-501,8:plan-refused:-501,9:plan-refused:-501"), "the reasons are %s", text);
    CHECK(!strncmp(text + 2, planner_reason_word(PLANNER_REASON_PLAN_REFUSED), strlen(planner_reason_word(PLANNER_REASON_PLAN_REFUSED))),
          "and the word is the declared one");
}

/* ---------------------------------------------------------------- the rules together */

static void the_first_rule_that_matches_decides(void)
{
    planner_settings_t s = settings();
    planner_member_t m[1];
    planner_plan_t p;

    s.group_cost_max = 0.1;
    m[0] = costed(1, 0.9);
    m[0].pin = PLANNER_PIN_REFUSED;
    m[0].world_ok = 0;
    CHECK(plan(&s, m, 1, &p) == 0 && p.reason[0] == PLANNER_REASON_REFUSED, "refused before the world and the cost");
    m[0].pin = PLANNER_PIN_ISOLATED;
    CHECK(plan(&s, m, 1, &p) == 0 && p.reason[0] == PLANNER_REASON_VERDICT_ISOLATED, "isolated before the world and the cost");
    m[0].pin = PLANNER_PIN_NO_VERDICT;
    CHECK(plan(&s, m, 1, &p) == 0 && p.reason[0] == PLANNER_REASON_NO_VERDICT, "no verdict before isolated and the world");
    m[0].pin = PLANNER_PIN_IN_PROCESS;
    CHECK(plan(&s, m, 1, &p) == 0 && p.reason[0] == PLANNER_REASON_FORMAT_WORLD, "the world before the cost");
    m[0].world_ok = 1;
    CHECK(plan(&s, m, 1, &p) == 0 && p.reason[0] == PLANNER_REASON_COST_OVER, "then the cost");
}

/* a member that meets format-mixed, group-full and group-cost at once is told the first of them */
static void format_mixed_comes_before_group_full_and_group_cost(void)
{
    planner_settings_t s = settings();
    planner_member_t m[2] = { costed(1, 0.5), costed(2, 0.5) };
    planner_plan_t p;

    s.group_max = 1;
    s.group_cost_max = 0.6;
    CHECK(plan(&s, m, 2, &p) == 0 && p.reason[1] == PLANNER_REASON_GROUP_FULL, "full before cost: %s", reasons(m, &p));
    m[1].klass = "mod-host";
    CHECK(plan(&s, m, 2, &p) == 0 && p.reason[1] == PLANNER_REASON_FORMAT_MIXED, "mixed before full: %s", reasons(m, &p));
}

static void without_require_pins_no_pin_is_read(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { member(1), member(2), member(3) };
    planner_plan_t p;

    s.require_pins = 0;
    m[0].pin = PLANNER_PIN_REFUSED;
    m[1].pin = PLANNER_PIN_NONE;
    m[2].pin = PLANNER_PIN_ISOLATED;
    m[2].world_ok = 0;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "pins and worlds are not read: %s", segments(m, &p));
}

/* under strict a pin the daemon did not learn needs no verdict to share: the chain verb lets it */
static void under_strict_a_pin_without_a_verdict_shares(void)
{
    planner_settings_t s = settings();
    planner_member_t m[2] = { member(1), member(2) };
    planner_plan_t p;

    s.pins_first_use = 0;
    m[0].pin = PLANNER_PIN_NO_VERDICT;
    CHECK(plan(&s, m, 2, &p) == 0 && !strcmp(segments(m, &p), "1,2"), "shares: %s", segments(m, &p));
}

static void a_plan_of_unfit_members_is_all_segments_of_one(void)
{
    planner_settings_t s = settings();
    planner_member_t m[3] = { member(1), member(2), member(3) };
    planner_plan_t p;
    int k;

    for (k = 0; k < 3; k++)
        m[k].pin = PLANNER_PIN_NO_VERDICT;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1;2;3") && p.nseg == 3, "three alone: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "1:no-verdict,2:no-verdict,3:no-verdict"), "each says why: %s", reasons(m, &p));
}

static void the_plan_keeps_the_signal_order(void)
{
    planner_settings_t s = settings();
    planner_member_t m[4] = { member(40), member(7), member(23), member(1) };
    planner_plan_t p;

    m[1].pin = PLANNER_PIN_ISOLATED;
    CHECK(plan(&s, m, 4, &p) == 0 && !strcmp(segments(m, &p), "40;7;23,1"), "the order given, not the numbers': %s", segments(m, &p));
}

static void a_plan_of_no_member_or_too_many_is_refused(void)
{
    planner_settings_t s = settings();
    planner_member_t m[PLANNER_MEMBERS_MAX + 1];
    planner_plan_t p;
    int k;

    for (k = 0; k <= PLANNER_MEMBERS_MAX; k++)
        m[k] = member(k);
    CHECK(planner_plan(&s, m, 0, &p) == -1, "none");
    CHECK(planner_plan(&s, m, PLANNER_MEMBERS_MAX + 1, &p) == -1, "too many");
    CHECK(planner_plan(&s, m, PLANNER_MEMBERS_MAX, &p) == 0, "the most");
}

/* ---------------------------------------------------------------- the text */

static void the_text_of_a_plan_is_the_one_the_bench_parses(void)
{
    planner_settings_t s = settings();
    planner_member_t m[5] = { member(1), member(2), member(3), member(4), member(5) };
    planner_plan_t p;
    char text[64];
    size_t need;

    m[2].pin = PLANNER_PIN_NO_VERDICT;
    CHECK(plan(&s, m, 5, &p) == 0, "planned");
    snprintf(text, sizeof(text), "resp 0 %s", segments(m, &p));
    CHECK(!strcmp(text, "resp 0 1,2;3;4,5"), "the reply is resp 0 i,i;i: %s", text);
    need = planner_format_segments(m, &p, text, 4);
    CHECK(need == strlen("1,2;3;4,5") && !strcmp(text, "1,2"), "a short buffer is cut and the need said: %zu '%s'", need, text);
    need = planner_format_reasons(m, &p, 0, NULL, 0);
    CHECK(need == strlen("3:no-verdict"), "the reasons can be measured: %zu", need);
}

static void no_reason_is_a_dash(void)
{
    planner_settings_t s = settings();
    planner_member_t m[2] = { costed(1, 0.1), costed(2, 0.1) };
    planner_plan_t p;

    CHECK(plan(&s, m, 2, &p) == 0 && !strcmp(reasons(m, &p), "-"), "nothing to say is -: %s", reasons(m, &p));
}

/* ---------------------------------------------------------------- the same members, the same plan */

static void the_same_members_give_the_same_bytes(void)
{
    planner_settings_t s = settings();
    planner_member_t a[6] = { costed(10, 0.2), member(11), costed(12, 0.3), costed(13, 0.35), member(14), costed(15, 0.1) };
    planner_member_t b[3] = { member(1), member(2), member(3) };
    planner_plan_t first, again, other;
    char seg[128], why[256], seg2[128], why2[256];
    int round;

    s.group_max = 3;
    s.group_cost_max = 0.7;
    a[1].pin = PLANNER_PIN_ISOLATED;
    a[4].pin = PLANNER_PIN_NO_VERDICT;
    memset(&first, 0x00, sizeof(first));
    CHECK(planner_plan(&s, a, 6, &first) == 0, "planned");
    planner_format_segments(a, &first, seg, sizeof(seg));
    planner_format_reasons(a, &first, 0, why, sizeof(why));
    for (round = 0; round < 50; round++)
    {
        /* the output starts as other bytes, and other plans were made between: nothing carries over */
        memset(&again, round % 2 ? 0xff : 0x5a, sizeof(again));
        CHECK(planner_plan(&s, b, 3, &other) == 0, "another plan");
        CHECK(planner_plan(&s, a, 6, &again) == 0, "planned again");
        planner_format_segments(a, &again, seg2, sizeof(seg2));
        planner_format_reasons(a, &again, 0, why2, sizeof(why2));
        CHECK(!strcmp(seg, seg2) && !strcmp(why, why2), "round %d: '%s' '%s' against '%s' '%s'", round, seg, why, seg2, why2);
        CHECK(again.nseg == first.nseg && !memcmp(again.seg_len, first.seg_len, sizeof(int) * (size_t)first.nseg) &&
              !memcmp(again.reason, first.reason, sizeof(int) * 6), "round %d: the plan itself differs", round);
    }
    CHECK(!strcmp(seg, "10;11;12,13;14;15"), "and the plan is the worked one: %s (%s)", seg, why);
}

/* ---------------------------------------------------------------- the history */

/* what the supervisor tells the planner of a history: crashed, raises xruns, the solo cost (a fraction of a core) */
static planner_history_t hist(int crashed, int xruns, double cpu)
{
    planner_history_t h = { crashed, xruns, cpu };

    return h;
}

static void history_crashed_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);
    planner_history_t h = hist(1, 0, PLANNER_COST_UNKNOWN);

    c.history = &h;
    unfit_middle("a plugin the history marks crashed", c, &s, PLANNER_REASON_HISTORY_CRASHED, "history-crashed");
}

static void history_xruns_leaves_the_member_alone(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);
    planner_history_t h = hist(0, 1, PLANNER_COST_UNKNOWN);

    c.history = &h;
    unfit_middle("a plugin the history marks as raising xruns", c, &s, PLANNER_REASON_HISTORY_XRUNS, "history-xruns");
}

/* a history that marks nothing is a history that is not there: the same segments, the same reasons */
static void a_history_that_marks_nothing_changes_nothing(void)
{
    planner_settings_t s = settings();
    planner_member_t with[4] = { member(1), member(2), unknown(3), member(4) };
    planner_member_t without[4] = { member(1), member(2), unknown(3), member(4) };
    planner_history_t clean = hist(0, 0, PLANNER_COST_UNKNOWN);
    planner_plan_t a, b;
    int k;

    for (k = 0; k < 4; k++)
        with[k].history = &clean;
    s.group_max = 3;
    CHECK(plan(&s, with, 4, &a) == 0 && plan(&s, without, 4, &b) == 0, "planned");
    CHECK(!strcmp(segments(with, &a), "1,2,3;4") && !strcmp(segments(without, &b), "1,2,3;4"), "the segments: %s, %s",
          segments(with, &a), segments(without, &b));
    CHECK(!strcmp(reasons(with, &a), "3:cost-assumed,4:group-full") && !strcmp(reasons(with, &a), reasons(without, &b)),
          "and the reasons: %s", reasons(with, &a));
}

/* a crash is the stronger evidence, and says so first */
static void history_crashed_comes_before_history_xruns(void)
{
    planner_settings_t s = settings();
    planner_member_t c = member(3);
    planner_history_t h = hist(1, 1, PLANNER_COST_UNKNOWN);

    c.history = &h;
    unfit_middle("both marked", c, &s, PLANNER_REASON_HISTORY_CRASHED, "history-crashed");
}

/* the pin rules decide first: a history can make the plan more careful than the pin, never less, and never says what the
 * pin already said */
static void the_pin_rules_come_before_the_history_rules(void)
{
    planner_settings_t s = settings();
    planner_history_t h = hist(1, 1, PLANNER_COST_UNKNOWN);
    planner_member_t c = member(3);

    c.history = &h;
    c.pin = PLANNER_PIN_ISOLATED;
    unfit_middle("isolated and crashed", c, &s, PLANNER_REASON_VERDICT_ISOLATED, "verdict-isolated");
    c.pin = PLANNER_PIN_NO_VERDICT;
    unfit_middle("no verdict and crashed", c, &s, PLANNER_REASON_NO_VERDICT, "no-verdict");
    c.pin = PLANNER_PIN_IN_PROCESS;
    c.world_ok = 0;
    unfit_middle("no world and crashed", c, &s, PLANNER_REASON_FORMAT_WORLD, "format-world");
}

/* and the history rules before the cost rule */
static void the_history_rules_come_before_cost_over(void)
{
    planner_settings_t s = settings();
    planner_history_t h = hist(0, 1, PLANNER_COST_UNKNOWN);
    planner_member_t c = costed(3, 0.9);

    s.group_cost_max = 0.5;
    c.history = &h;
    unfit_middle("raises xruns and over the cost", c, &s, PLANNER_REASON_HISTORY_XRUNS, "history-xruns");
}

/* the pins are read only while require_pins is on, the history always: a quarantine needs no pin */
static void the_history_is_read_without_require_pins(void)
{
    planner_settings_t s = settings();
    planner_history_t h = hist(1, 0, PLANNER_COST_UNKNOWN);
    planner_member_t c = member(3);

    s.require_pins = 0;
    c.history = &h;
    unfit_middle("crashed, no pins read", c, &s, PLANNER_REASON_HISTORY_CRASHED, "history-crashed");
}

/* a plan with the member left out of the middle keeps the order: A B C D E with C crashed is [A B] [C] [D E], and the
 * members next to it say nothing, as for any unfit member */
static void a_crashed_member_leaves_its_neighbours_in_their_segments(void)
{
    planner_settings_t s = settings();
    planner_history_t h = hist(1, 0, PLANNER_COST_UNKNOWN);
    planner_member_t m[5] = { member(1), member(2), member(3), member(4), member(5) };
    planner_plan_t p;

    m[1].history = &h;
    CHECK(plan(&s, m, 5, &p) == 0 && !strcmp(segments(m, &p), "1;2;3,4,5"), "the second one alone: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "1:no-neighbour,2:history-crashed"), "the reasons: %s", reasons(m, &p));
}

/* the cost of a member is the larger of what plugin-qualify measured and what the plugin did alone on this machine */
static void a_member_costs_the_larger_of_its_qualified_cost_and_its_solo_cost(void)
{
    planner_settings_t s = settings();
    planner_history_t heavy = hist(0, 0, 0.5), light = hist(0, 0, 0.0625);
    planner_member_t m[3] = { costed(1, 0.25), costed(2, 0.25), costed(3, 0.25) };
    planner_plan_t p;

    s.group_cost_max = 0.875;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "0.75 fits 0.875: %s", segments(m, &p));
    m[1].history = &heavy;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2;3"), "the second counts 0.5, not 0.25, and the third is over: %s",
          segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "3:group-cost"), "the reasons: %s", reasons(m, &p));
    m[1].history = &light;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2,3"), "a solo cost under the qualified one does not lower it: %s",
          segments(m, &p));
    s.group_cost_max = 0.7;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2;3"), "the qualified 0.25 still counts: %s", segments(m, &p));
}

/* a plugin whose qualification nobody has can still be known by the machine it runs on */
static void a_solo_cost_stands_for_a_cost_nobody_qualified(void)
{
    planner_settings_t s = settings();
    planner_history_t known = hist(0, 0, 0.5);
    planner_member_t m[3] = { costed(1, 0.25), unknown(2), costed(3, 0.25) };
    planner_plan_t p;

    s.group_cost_max = 0.875;
    m[1].history = &known;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2;3"), "0.25 + 0.5 and 0.25 more is over 0.875: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p), "3:group-cost"), "and the member is no longer an assumption: %s", reasons(m, &p));
    s.group_cost_max = 0.4;
    m[1].history = &known;
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1;2;3"), "0.5 alone is over 0.4: %s", segments(m, &p));
    CHECK(p.reason[1] == PLANNER_REASON_COST_OVER, "cost-over, from the solo cost: %s", reasons(m, &p));
}

/* it is also what the median of an unknown member is made from */
static void the_solo_cost_of_a_member_enters_the_median_of_the_unknown_ones(void)
{
    planner_settings_t s = settings();
    planner_history_t known = hist(0, 0, 0.5);
    planner_member_t m[3] = { costed(1, 0.125), unknown(2), unknown(3) };
    planner_plan_t p;

    m[0].history = &known;
    s.group_cost_max = 1.4;
    /* the first counts 0.5 (not 0.125); the unknown ones count 0.5 each: 1.5 is over 1.4 on the third */
    CHECK(plan(&s, m, 3, &p) == 0 && !strcmp(segments(m, &p), "1,2;3"), "%s", segments(m, &p));
}

/* a plan made without the history says so, of every member that has nothing harder to say */
static void history_unavailable_is_said_of_every_member_with_nothing_harder_to_say(void)
{
    planner_settings_t s = settings();
    planner_member_t m[5] = { member(1), unknown(2), member(3), member(4), member(5) };
    planner_plan_t p;

    s.history_unavailable = 1;
    m[2].pin = PLANNER_PIN_ISOLATED;
    CHECK(plan(&s, m, 5, &p) == 0 && !strcmp(segments(m, &p), "1,2;3;4,5"), "the segments: %s", segments(m, &p));
    CHECK(!strcmp(reasons(m, &p),
                  "1:history-unavailable,2:history-unavailable,3:verdict-isolated,4:history-unavailable,5:history-unavailable"),
          "the members that share say it, in place of cost-assumed: %s", reasons(m, &p));
    s.grouping_on = 0;
    CHECK(plan(&s, m, 5, &p) == 0 && !strcmp(segments(m, &p), "1,2;3;4,5"), "grouping off: the same segments");
    CHECK(p.reason[0] == PLANNER_REASON_HISTORY_UNAVAILABLE && p.reason[2] == PLANNER_REASON_VERDICT_ISOLATED,
          "it is the history that is missing, said before the setting: %s", reasons(m, &p));
    s.grouping_on = 1;
    CHECK(plan(&s, m, 1, &p) == 0 && !strcmp(reasons(m, &p), "1:history-unavailable"), "a lone member too: %s", reasons(m, &p));
}

/* with the history gone the plan is the pins' and the costs': the segments are those of a plugin with no history */
static void a_plan_without_the_history_has_the_segments_of_a_plan_with_none(void)
{
    planner_settings_t s = settings();
    planner_member_t m[6] = { costed(1, 0.2), member(2), costed(3, 0.3), costed(4, 0.35), member(5), costed(6, 0.1) };
    planner_plan_t on, off;

    s.group_max = 3;
    s.group_cost_max = 0.7;
    m[1].pin = PLANNER_PIN_ISOLATED;
    CHECK(plan(&s, m, 6, &on) == 0, "planned with the history");
    s.history_unavailable = 1;
    CHECK(plan(&s, m, 6, &off) == 0, "planned without it");
    CHECK(on.nseg == off.nseg && !memcmp(on.seg_len, off.seg_len, sizeof(int) * (size_t)on.nseg), "the segments are the same");
    CHECK(!strcmp(segments(m, &on), "1;2;3,4,5;6"), "and they are the worked ones: %s", segments(m, &on));
}

static void the_same_members_with_a_history_give_the_same_bytes(void)
{
    planner_settings_t s = settings();
    planner_history_t crashed = hist(1, 0, PLANNER_COST_UNKNOWN), slow = hist(0, 0, 0.4), bad = hist(0, 1, 0.1);
    planner_member_t a[6] = { costed(10, 0.2), member(11), costed(12, 0.3), costed(13, 0.35), member(14), costed(15, 0.1) };
    planner_plan_t first, again;
    char seg[128], why[256], seg2[128], why2[256];
    int round;

    s.group_cost_max = 0.8;
    a[1].history = &crashed;
    a[3].history = &slow;
    a[4].history = &bad;
    s.history_unavailable = 0;
    CHECK(planner_plan(&s, a, 6, &first) == 0, "planned");
    planner_format_segments(a, &first, seg, sizeof(seg));
    planner_format_reasons(a, &first, 0, why, sizeof(why));
    for (round = 0; round < 20; round++)
    {
        memset(&again, round % 2 ? 0xff : 0x5a, sizeof(again));
        CHECK(planner_plan(&s, a, 6, &again) == 0, "planned again");
        planner_format_segments(a, &again, seg2, sizeof(seg2));
        planner_format_reasons(a, &again, 0, why2, sizeof(why2));
        CHECK(!strcmp(seg, seg2) && !strcmp(why, why2), "round %d: '%s' '%s' against '%s' '%s'", round, seg, why, seg2, why2);
    }
    CHECK(!strcmp(seg, "10;11;12,13;14;15") && !strcmp(why, "10:no-neighbour,11:history-crashed,14:history-xruns,15:no-neighbour"),
          "and the plan is the worked one: %s (%s)", seg, why);
}

static const struct { const char *name; void (*fn)(void); } g_tests[] = {
#define T(f) { #f, f }
    T(the_reasons_are_the_words_of_the_declaration),
    T(refused_leaves_the_member_alone),
    T(no_pin_under_strict_leaves_the_member_alone),
    T(no_verdict_leaves_the_member_alone),
    T(a_pin_that_is_gone_under_first_use_has_no_verdict),
    T(verdict_isolated_leaves_the_member_alone),
    T(format_world_leaves_the_member_alone),
    T(cost_over_leaves_the_member_alone),
    T(a_cost_at_the_limit_is_not_over),
    T(format_mixed_starts_a_new_segment),
    T(group_full_starts_a_new_segment),
    T(group_max_zero_is_no_limit),
    T(group_cost_starts_a_new_segment),
    T(the_costs_of_a_segment_add_up),
    T(a_member_of_unknown_cost_counts_as_the_median_of_its_segment),
    T(the_median_of_an_even_number_is_the_mean_of_the_middle_two),
    T(members_of_unknown_cost_alone_in_a_segment_count_for_nothing),
    T(cost_assumed_is_said_of_a_member_that_joined_on_an_assumption),
    T(no_neighbour_is_said_of_a_member_alone_for_the_members_around_it),
    T(grouping_off_says_what_would_have_shared),
    T(a_refused_plan_gives_every_member_the_refusal),
    T(the_first_rule_that_matches_decides),
    T(format_mixed_comes_before_group_full_and_group_cost),
    T(without_require_pins_no_pin_is_read),
    T(under_strict_a_pin_without_a_verdict_shares),
    T(a_plan_of_unfit_members_is_all_segments_of_one),
    T(the_plan_keeps_the_signal_order),
    T(a_plan_of_no_member_or_too_many_is_refused),
    T(the_text_of_a_plan_is_the_one_the_bench_parses),
    T(no_reason_is_a_dash),
    T(the_same_members_give_the_same_bytes),
    T(history_crashed_leaves_the_member_alone),
    T(history_xruns_leaves_the_member_alone),
    T(a_history_that_marks_nothing_changes_nothing),
    T(history_crashed_comes_before_history_xruns),
    T(the_pin_rules_come_before_the_history_rules),
    T(the_history_rules_come_before_cost_over),
    T(the_history_is_read_without_require_pins),
    T(a_crashed_member_leaves_its_neighbours_in_their_segments),
    T(a_member_costs_the_larger_of_its_qualified_cost_and_its_solo_cost),
    T(a_solo_cost_stands_for_a_cost_nobody_qualified),
    T(the_solo_cost_of_a_member_enters_the_median_of_the_unknown_ones),
    T(history_unavailable_is_said_of_every_member_with_nothing_harder_to_say),
    T(a_plan_without_the_history_has_the_segments_of_a_plan_with_none),
    T(the_same_members_with_a_history_give_the_same_bytes),
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
    printf("planner tests %s (%zu run, %d failed)\n", bad ? "FAILED" : "ok", ran, bad);
    return bad ? 1 : 0;
}

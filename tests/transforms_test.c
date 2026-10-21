/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* src/transforms.c over its vectors: every transform of TRANSFORMS(X) has vectors, and for each one the inbound
 * function takes the format's text to the descriptor's value and the inverse takes it back to the same text (in, out,
 * back in, equal). Values a transform cannot read are refused, and a lookup that is not one to one is refused. */

#include <stdio.h>
#include <string.h>

#include "transforms.h"

static int g_failed;

#define CHECK(cond, ...)                                                                                               \
    do                                                                                                                 \
    {                                                                                                                  \
        if (!(cond))                                                                                                   \
        {                                                                                                              \
            printf("FAIL ");                                                                                           \
            printf(__VA_ARGS__);                                                                                       \
            printf("\n");                                                                                              \
            g_failed++;                                                                                                \
        }                                                                                                              \
    } while (0)

static const char *const UNIT_FROM[] = { "units:db", "units:hz", "units:pc" };
static const char *const UNIT_TO[] = { "\"dB\"", "\"Hz\"", "\"%\"" };
static const char *const BOOL_FROM[] = { "CLAP_PARAM_IS_AUTOMATABLE" };
static const char *const BOOL_TO[] = { "true" };

static const transforms_data_t NONE = { 0 };
static const transforms_data_t UNITS = { "units:unit", UNIT_FROM, UNIT_TO, 3, 0 };
static const transforms_data_t AUTOMATABLE = { "CLAP_PARAM_IS_AUTOMATABLE", BOOL_FROM, BOOL_TO, 1, 0 };
static const transforms_data_t KHZ = { "units:khz", NULL, NULL, 0, 1000 };
static const transforms_data_t HIDDEN = { "CLAP_PARAM_IS_HIDDEN", NULL, NULL, 0, 0 };

/* one vector: through transform name with data d, the format's text in becomes the descriptor's value out, and back */
typedef struct
{
    const char *name;
    const transforms_data_t *d;
    const char *in, *out;
} vector_t;

static const vector_t VECTORS[] = {
    { "identity", &NONE, "Threshold", "\"Threshold\"" },
    { "identity", &NONE, "-60", "-60" },
    { "identity", &NONE, "0.25", "0.25" },
    { "identity", &NONE, "say \"hi\"\\", "\"say \\\"hi\\\"\\\\\"" },
    { "identity", &NONE, "org.openmixer.delay", "\"org.openmixer.delay\"" },
    { "lookup", &UNITS, "units:db", "\"dB\"" },
    { "lookup", &UNITS, "units:pc", "\"%\"" },
    { "lookup", &AUTOMATABLE, "CLAP_PARAM_IS_AUTOMATABLE", "true" },
    { "scale-by", &KHZ, "2.5", "2500" },
    { "scale-by", &KHZ, "-0.02", "-20" },
    { "flag", &HIDDEN, "CLAP_PARAM_IS_HIDDEN", "true" },
    { "scale-points", &NONE, "0 Sine", "[0,\"Sine\"]" },
    { "scale-points", &NONE, "-1.5 Very low (sub)", "[-1.5,\"Very low (sub)\"]" },
    { "group-path", &NONE, "Filter/Envelope", "[\"Filter\",\"Envelope\"]" },
    { "group-path", &NONE, "Delay", "[\"Delay\"]" },
    { "port-group", &NONE, "Detector", "[\"Detector\"]" },
    { "port-group", &NONE, "Main in", "[\"Main in\"]" },
};

/* what a transform refuses (inbound unless inverse is set), or reads as no value */
typedef struct
{
    const char *name;
    const transforms_data_t *d;
    int inverse;
    const char *in;
    int want;
} edge_t;

static const transforms_data_t ZERO = { "units:x", NULL, NULL, 0, 0 };

static const edge_t EDGES[] = {
    { "identity", &NONE, 1, "dB", TRANSFORMS_REFUSED },               /* not a JSON literal */
    { "identity", &NONE, 1, "\"dB\" x", TRANSFORMS_REFUSED },         /* more than one */
    { "lookup", &UNITS, 0, "units:furlong", TRANSFORMS_NONE },       /* no entry */
    { "lookup", &UNITS, 1, "\"furlongs\"", TRANSFORMS_NONE },        /* no key */
    { "scale-by", &KHZ, 0, "fast", TRANSFORMS_REFUSED },              /* not a number */
    { "scale-by", &ZERO, 0, "1", TRANSFORMS_REFUSED },                /* no factor */
    { "flag", &HIDDEN, 1, "false", TRANSFORMS_NONE },                 /* false writes nothing */
    { "flag", &HIDDEN, 1, "1", TRANSFORMS_REFUSED },                  /* not a boolean */
    { "scale-points", &NONE, 0, "Sine", TRANSFORMS_REFUSED },         /* no number */
    { "scale-points", &NONE, 0, "x Sine", TRANSFORMS_REFUSED },       /* not a number */
    { "scale-points", &NONE, 0, "1 ", TRANSFORMS_REFUSED },           /* no label */
    { "scale-points", &NONE, 1, "[1]", TRANSFORMS_REFUSED },          /* no label */
    { "group-path", &NONE, 0, "", TRANSFORMS_NONE },                  /* no group */
    { "group-path", &NONE, 0, "//", TRANSFORMS_NONE },                /* no level */
    { "group-path", &NONE, 1, "[\"a/b\"]", TRANSFORMS_REFUSED },      /* a level holding the separator */
    { "group-path", &NONE, 1, "[]", TRANSFORMS_REFUSED },             /* no level */
    { "port-group", &NONE, 0, "", TRANSFORMS_NONE },                  /* no group */
    { "port-group", &NONE, 1, "[\"a\",\"b\"]", TRANSFORMS_REFUSED },  /* LV2 groups have one level */
};

int main(void)
{
    size_t i, k;
    char out[256], back[256];

    /* every transform of the list has vectors, and every vector names one of the list */
    for (i = 0; i < transforms_count; i++)
    {
        int n = 0;

        for (k = 0; k < sizeof(VECTORS) / sizeof(VECTORS[0]); k++)
            n += strcmp(VECTORS[k].name, transforms_list[i].name) == 0;
        CHECK(n > 0, "%s: no vector", transforms_list[i].name);
    }
    for (k = 0; k < sizeof(VECTORS) / sizeof(VECTORS[0]); k++)
    {
        const vector_t *v = &VECTORS[k];
        const transforms_entry_t *t = transforms_find(v->name);
        int r;

        CHECK(t != NULL, "%s: not in TRANSFORMS(X)", v->name);
        if (t == NULL)
            continue;
        r = t->inbound(v->d, v->in, out, sizeof(out));
        CHECK(r == TRANSFORMS_OK && strcmp(out, v->out) == 0, "%s in %s: %d %s, want %s", v->name, v->in, r,
              r == TRANSFORMS_OK ? out : "-", v->out);
        r = t->inverse(v->d, v->out, back, sizeof(back));
        CHECK(r == TRANSFORMS_OK && strcmp(back, v->in) == 0, "%s back %s: %d %s, want %s", v->name, v->out, r,
              r == TRANSFORMS_OK ? back : "-", v->in);
        if (r == TRANSFORMS_OK)
        {
            r = t->inbound(v->d, back, out, sizeof(out));
            CHECK(r == TRANSFORMS_OK && strcmp(out, v->out) == 0, "%s in again %s: %s", v->name, back, out);
        }
        printf("ok   %s: %s -> %s -> %s\n", v->name, v->in, v->out, v->in);
    }
    for (k = 0; k < sizeof(EDGES) / sizeof(EDGES[0]); k++)
    {
        const edge_t *e = &EDGES[k];
        const transforms_entry_t *t = transforms_find(e->name);
        int r = (e->inverse ? t->inverse : t->inbound)(e->d, e->in, out, sizeof(out));

        CHECK(r == e->want, "%s %s %s: %d, want %d", e->name, e->inverse ? "inverse" : "in", e->in, r, e->want);
        printf("ok   %s %s '%s': %s\n", e->name, e->inverse ? "inverse" : "in", e->in,
               e->want == TRANSFORMS_NONE ? "no value" : "refused");
    }
    /* a result that does not fit is refused, never cut */
    CHECK(transforms_find("identity")->inbound(&NONE, "Threshold", out, 5) == TRANSFORMS_REFUSED, "identity: cut");
    CHECK(transforms_find("no-such") == NULL, "a name outside the list is found");

    /* a lookup is one to one: a repeated entry or a repeated key is refused */
    {
        static const char *const from[] = { "units:db", "units:dB" }, *const to[] = { "\"dB\"", "\"dB\"" };
        static const char *const from2[] = { "units:db", "units:db" }, *const to2[] = { "\"dB\"", "\"dBFS\"" };
        const transforms_data_t many_to_one = { "units:unit", from, to, 2, 0 };
        const transforms_data_t one_to_many = { "units:unit", from2, to2, 2, 0 };

        CHECK(transforms_lookup_check(&UNITS) == 0, "a one to one lookup refused");
        CHECK(transforms_lookup_check(&many_to_one) == -1, "a lookup whose values repeat is accepted");
        CHECK(transforms_lookup_check(&one_to_many) == -1, "a lookup whose keys repeat is accepted");
        printf("ok   lookup: values not one to one are refused\n");
    }
    if (g_failed)
    {
        printf("transforms: %d failed\n", g_failed);
        return 1;
    }
    printf("transforms: %zu transforms, %zu vectors and %zu edges pass\n", transforms_count,
           sizeof(VECTORS) / sizeof(VECTORS[0]), sizeof(EDGES) / sizeof(EDGES[0]));
    return 0;
}

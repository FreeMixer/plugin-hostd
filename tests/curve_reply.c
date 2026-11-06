/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * curve_reply: the reply curve_points must give for a request, written from omx-dsp's omx_curve_points over the values
 * the test read with param_get_many, so the real worker's answer can be held to it bit for bit (tests/jack_e2e.py).
 *
 *   curve_reply <kind> <family> <rate> <points> <term> ...
 *
 * each term <role>[.<index>]=<value>[:<unit>][@<shape>], the value as param_get wrote it and the band shape already
 * resolved. Prints "resp 0 <count> <x>,<y> ..." (x to four significant digits, y to 0.01 dB, as the protocol page says)
 * or "code <n>"; exit 2 for a line it cannot read.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <omxdsp/omx_curve.h>

static int word(const char *const *words, uint32_t n, const char *s, size_t len)
{
    char buf[32];

    if (len >= sizeof(buf))
        return -1;
    memcpy(buf, s, len);
    buf[len] = '\0';
    return omx_curve_word(words, n, buf);
}

int main(int argc, char **argv)
{
    static struct omx_curve_term t[512];
    double x[OMX_CURVE_POINTS_MAX], y[OMX_CURVE_POINTS_MAX];
    struct omx_curve_request rq;
    int code = -1, k, v;

    if (argc < 6 || argc - 5 > 512)
        return 2;
    memset(&rq, 0, sizeof(rq));
    if ((v = omx_curve_word(OMX_CURVE_DISPLAY_WORDS, OMX_CURVE_DISPLAYS_COUNT, argv[1])) < 0)
        return 2;
    rq.kind = (enum omx_curve_displays)v;
    if ((v = omx_curve_word(OMX_CURVE_FAMILY_WORDS, OMX_CURVE_FAMILIES_COUNT, argv[2])) < 0)
        return 2;
    rq.family = (enum omx_curve_families)v;
    rq.sample_rate = atof(argv[3]);
    rq.points = (uint32_t)atoi(argv[4]);
    for (k = 5; k < argc; k++)
    {
        struct omx_curve_term *u = &t[k - 5];
        const char *w = argv[k], *eq = strchr(w, '='), *dot = strchr(w, '.'), *colon, *at;
        char *end;

        if (!eq)
            return 2;
        if (!dot || dot > eq)
            dot = eq;
        if ((v = word(OMX_CURVE_ROLE_WORDS, OMX_CURVE_ROLES_COUNT, w, (size_t)(dot - w))) < 0)
            return 2;
        u->role = (enum omx_curve_roles)v;
        u->index = dot < eq ? (uint32_t)atoi(dot + 1) : 0u;
        u->value = (double)(float)strtod(eq + 1, &end);
        colon = *end == ':' ? end : NULL;
        at = strchr(end, '@');
        u->unit = OMX_CURVE_UNITS_NONE;
        if (colon && (v = word(OMX_CURVE_UNIT_WORDS, OMX_CURVE_UNITS_COUNT, colon + 1,
                               at ? (size_t)(at - colon - 1) : strlen(colon + 1))) >= 0)
            u->unit = (enum omx_curve_units)v;
        u->shape = at ? omx_curve_word(OMX_CURVE_SHAPE_WORDS, OMX_CURVE_SHAPES_COUNT, at + 1) : OMX_CURVE_NO_SHAPE;
        u->origin = OMX_CURVE_ORIGINS_USER;
    }
    rq.terms = t;
    rq.nterms = (uint32_t)(argc - 5);
    const uint32_t n = omx_curve_points(&rq, x, y, OMX_CURVE_POINTS_MAX, &code);
    if (code != OMX_CURVE_OK)
    {
        printf("code %d\n", code);
        return 0;
    }
    printf("resp 0 %u", n);
    for (uint32_t i = 0; i < n; i++)
    {
        double xv = x[i];
        int decimals = x[i] == 0.0 ? 0 : 3 - (int)floor(log10(fabs(x[i])));

        if (x[i] == 0.0)
            printf(" 0");
        else
        {
            if (decimals < 0)
                xv = round(x[i] / pow(10.0, -decimals)) * pow(10.0, -decimals), decimals = 0;
            printf(" %.*f", decimals, xv);
        }
        printf(",%.2f", fabs(y[i]) < 0.005 ? 0.0 : y[i]);
    }
    printf("\n");
    return 0;
}

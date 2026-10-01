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

/* The pin of a plugin, computed once: the SHA-256 of a file over an open descriptor, and the fingerprint of a
 * parameter layout in the omx-layout/1 serialisation. Header-only, libc only. A host fills the neutral records below
 * from its own standard interface (CLAP params, LV2 control ports) and calls the digest; nothing else writes these
 * bytes. A change to the serialisation is a new scheme, never an edit of this one.
 *
 * omx-layout/1, UTF-8, one '\n' after every line:
 *   line 1: "omx-layout/1 clap" or "omx-layout/1 lv2"
 *   CLAP: every parameter, sorted by id: <id>\t<name>\t<min>\t<max>\t<default>\t<flags>, flags 8 lowercase hex digits
 *   LV2: every control port, sorted by index: <index>\t<symbol>\t<in|out>\t<min>\t<max>\t<default>\t<properties>,
 *        properties the full URIs sorted bytewise and joined by one space, "-" when none
 *   a number: 16 lowercase hex digits of its IEEE-754 binary64 bits, "-" when none is declared
 *   in a name or symbol: '\' is "\\", a tab "\t", a newline "\n", every other byte as given */

#ifndef PLUGIN_HOSTD_PIN_H
#define PLUGIN_HOSTD_PIN_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define PHD_PIN_LAYOUT_SCHEME "omx-layout/1"
#define PHD_PIN_LAYOUT_CLAP   "clap"
#define PHD_PIN_LAYOUT_LV2    "lv2"
#define PHD_SHA256_HEX_LEN    64

/* ---------------------------------------------------------------- SHA-256 (FIPS 180-4) */

typedef struct PHD_SHA256_T {
    uint32_t h[8];
    uint64_t bytes;
    unsigned char block[64];
    size_t used;
} phd_sha256_t;

static const uint32_t phd_sha256_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define PHD_ROTR32(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static inline void phd_sha256_block(phd_sha256_t *c, const unsigned char *p)
{
    uint32_t w[64], a, b, d, e, f, g, h, cc, t1, t2;
    int n;

    for (n = 0; n < 16; n++)
        w[n] = (uint32_t)p[n * 4] << 24 | (uint32_t)p[n * 4 + 1] << 16 | (uint32_t)p[n * 4 + 2] << 8 | p[n * 4 + 3];
    for (n = 16; n < 64; n++)
    {
        uint32_t s0 = PHD_ROTR32(w[n - 15], 7) ^ PHD_ROTR32(w[n - 15], 18) ^ (w[n - 15] >> 3);
        uint32_t s1 = PHD_ROTR32(w[n - 2], 17) ^ PHD_ROTR32(w[n - 2], 19) ^ (w[n - 2] >> 10);

        w[n] = w[n - 16] + s0 + w[n - 7] + s1;
    }
    a = c->h[0]; b = c->h[1]; cc = c->h[2]; d = c->h[3];
    e = c->h[4]; f = c->h[5]; g = c->h[6]; h = c->h[7];
    for (n = 0; n < 64; n++)
    {
        t1 = h + (PHD_ROTR32(e, 6) ^ PHD_ROTR32(e, 11) ^ PHD_ROTR32(e, 25)) + ((e & f) ^ (~e & g)) + phd_sha256_k[n] + w[n];
        t2 = (PHD_ROTR32(a, 2) ^ PHD_ROTR32(a, 13) ^ PHD_ROTR32(a, 22)) + ((a & b) ^ (a & cc) ^ (b & cc));
        h = g; g = f; f = e; e = d + t1;
        d = cc; cc = b; b = a; a = t1 + t2;
    }
    c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d;
    c->h[4] += e; c->h[5] += f; c->h[6] += g; c->h[7] += h;
}

static inline void phd_sha256_init(phd_sha256_t *c)
{
    static const uint32_t h0[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    };

    memcpy(c->h, h0, sizeof(h0));
    c->bytes = 0;
    c->used = 0;
}

static inline void phd_sha256_update(phd_sha256_t *c, const void *data, size_t size)
{
    const unsigned char *p = (const unsigned char *)data;

    c->bytes += size;
    while (size)
    {
        size_t take = 64 - c->used < size ? 64 - c->used : size;

        memcpy(c->block + c->used, p, take);
        c->used += take;
        p += take;
        size -= take;
        if (c->used == 64)
        {
            phd_sha256_block(c, c->block);
            c->used = 0;
        }
    }
}

/* the digest as 64 lowercase hex digits and a NUL */
static inline void phd_sha256_final(phd_sha256_t *c, char hex[PHD_SHA256_HEX_LEN + 1])
{
    static const char digits[] = "0123456789abcdef";
    uint64_t bits = c->bytes * 8;
    unsigned char pad = 0x80, len[8];
    int n;

    phd_sha256_update(c, &pad, 1);
    pad = 0;
    while (c->used != 56)
        phd_sha256_update(c, &pad, 1);
    for (n = 0; n < 8; n++)
        len[n] = (unsigned char)(bits >> (56 - 8 * n));
    phd_sha256_update(c, len, 8);
    for (n = 0; n < 32; n++)
    {
        unsigned char byte = (unsigned char)(c->h[n / 4] >> (24 - 8 * (n % 4)));

        hex[n * 2] = digits[byte >> 4];
        hex[n * 2 + 1] = digits[byte & 15];
    }
    hex[PHD_SHA256_HEX_LEN] = '\0';
}

static inline void phd_sha256_hex(const void *data, size_t size, char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    phd_sha256_update(&c, data, size);
    phd_sha256_final(&c, hex);
}

/* the SHA-256 of everything an open descriptor holds, read from its start; 0, or -1 when it cannot be read */
static inline int phd_pin_fd_digest(int fd, char hex[PHD_SHA256_HEX_LEN + 1])
{
    unsigned char buffer[65536];
    phd_sha256_t c;
    ssize_t got;

    if (lseek(fd, 0, SEEK_SET) != 0)
        return -1;
    phd_sha256_init(&c);
    while ((got = read(fd, buffer, sizeof(buffer))) != 0)
    {
        if (got < 0)
            return -1;
        phd_sha256_update(&c, buffer, (size_t)got);
    }
    phd_sha256_final(&c, hex);
    return 0;
}

/* whether s is a digest as a pin writes it: 64 lowercase hex digits */
static inline int phd_pin_hex_valid(const char *s)
{
    int n;

    for (n = 0; n < PHD_SHA256_HEX_LEN; n++)
        if (!((s[n] >= '0' && s[n] <= '9') || (s[n] >= 'a' && s[n] <= 'f')))
            return 0;
    return s[n] == '\0';
}

/* a layout pin "<scheme>:<sha256>" split at its last ':'; 0, or -1 when it is not one */
static inline int phd_pin_layout_parse(const char *token, char *scheme, size_t scheme_size,
                                       char hex[PHD_SHA256_HEX_LEN + 1])
{
    const char *colon = strrchr(token, ':');
    size_t n;

    if (!colon || colon == token || !phd_pin_hex_valid(colon + 1))
        return -1;
    n = (size_t)(colon - token);
    if (n >= scheme_size)
        return -1;
    memcpy(scheme, token, n);
    scheme[n] = '\0';
    memcpy(hex, colon + 1, PHD_SHA256_HEX_LEN + 1);
    return 0;
}

/* ---------------------------------------------------------------- omx-layout/1 */

/* one CLAP parameter as clap_param_info gives it */
typedef struct PHD_LAYOUT_CLAP_PARAM_T {
    uint32_t id;
    const char *name;
    double min, max, def;
    uint32_t flags;
} phd_layout_clap_param_t;

/* which numbers an LV2 port declares */
#define PHD_LAYOUT_HAS_MIN 1u
#define PHD_LAYOUT_HAS_MAX 2u
#define PHD_LAYOUT_HAS_DEF 4u

/* one LV2 control port as the loaded world describes it; a float is widened to double, which is exact */
typedef struct PHD_LAYOUT_LV2_PORT_T {
    uint32_t index;
    const char *symbol;
    int output;
    unsigned has;
    double min, max, def;
    const char *const *properties;
    size_t nproperties;
} phd_layout_lv2_port_t;

/* where the bytes go: a digest, a buffer, or both */
typedef void (*phd_layout_sink_t)(void *ctx, const char *data, size_t size);

static inline void phd_layout_put(phd_layout_sink_t sink, void *ctx, const char *s)
{
    sink(ctx, s, strlen(s));
}

static inline void phd_layout_number(phd_layout_sink_t sink, void *ctx, double value, int declared)
{
    static const char digits[] = "0123456789abcdef";
    char text[17];
    uint64_t bits;
    int n;

    if (!declared)
    {
        sink(ctx, "-", 1);
        return;
    }
    memcpy(&bits, &value, sizeof(bits));
    for (n = 0; n < 16; n++)
        text[n] = digits[(bits >> (60 - 4 * n)) & 15];
    sink(ctx, text, 16);
}

static inline void phd_layout_text(phd_layout_sink_t sink, void *ctx, const char *s)
{
    const char *run = s;

    for (; *s; s++)
    {
        const char *esc = *s == '\\' ? "\\\\" : *s == '\t' ? "\\t" : *s == '\n' ? "\\n" : NULL;

        if (!esc)
            continue;
        sink(ctx, run, (size_t)(s - run));
        sink(ctx, esc, 2);
        run = s + 1;
    }
    sink(ctx, run, (size_t)(s - run));
}

static inline void phd_layout_uint(phd_layout_sink_t sink, void *ctx, uint32_t value, int hex8)
{
    char text[16];
    int n = 0, k;

    if (hex8)
    {
        static const char digits[] = "0123456789abcdef";

        for (k = 0; k < 8; k++)
            text[k] = digits[(value >> (28 - 4 * k)) & 15];
        sink(ctx, text, 8);
        return;
    }
    do
    {
        text[15 - n++] = (char)('0' + value % 10);
        value /= 10;
    } while (value);
    sink(ctx, text + 16 - n, (size_t)n);
}

static inline int phd_layout_clap_order(const void *a, const void *b)
{
    const phd_layout_clap_param_t *x = *(const phd_layout_clap_param_t *const *)a;
    const phd_layout_clap_param_t *y = *(const phd_layout_clap_param_t *const *)b;

    return x->id != y->id ? (x->id < y->id ? -1 : 1) : (x < y ? -1 : x > y);
}

static inline int phd_layout_lv2_order(const void *a, const void *b)
{
    const phd_layout_lv2_port_t *x = *(const phd_layout_lv2_port_t *const *)a;
    const phd_layout_lv2_port_t *y = *(const phd_layout_lv2_port_t *const *)b;

    return x->index != y->index ? (x->index < y->index ? -1 : 1) : (x < y ? -1 : x > y);
}

static inline int phd_layout_bytewise(const void *a, const void *b)
{
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* the omx-layout/1 bytes of a CLAP layout into sink; 0, or -1 when memory runs out */
static inline int phd_layout_clap_write(const phd_layout_clap_param_t *params, size_t count, phd_layout_sink_t sink,
                                        void *ctx)
{
    const phd_layout_clap_param_t **order = (const phd_layout_clap_param_t **)malloc((count ? count : 1) * sizeof(*order));
    size_t n;

    if (!order)
        return -1;
    for (n = 0; n < count; n++)
        order[n] = &params[n];
    qsort(order, count, sizeof(*order), phd_layout_clap_order);
    phd_layout_put(sink, ctx, PHD_PIN_LAYOUT_SCHEME " " PHD_PIN_LAYOUT_CLAP "\n");
    for (n = 0; n < count; n++)
    {
        const phd_layout_clap_param_t *p = order[n];

        phd_layout_uint(sink, ctx, p->id, 0);
        sink(ctx, "\t", 1);
        phd_layout_text(sink, ctx, p->name ? p->name : "");
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->min, 1);
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->max, 1);
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->def, 1);
        sink(ctx, "\t", 1);
        phd_layout_uint(sink, ctx, p->flags, 1);
        sink(ctx, "\n", 1);
    }
    free(order);
    return 0;
}

/* the omx-layout/1 bytes of an LV2 layout into sink; 0, or -1 when memory runs out */
static inline int phd_layout_lv2_write(const phd_layout_lv2_port_t *ports, size_t count, phd_layout_sink_t sink,
                                       void *ctx)
{
    const phd_layout_lv2_port_t **order = (const phd_layout_lv2_port_t **)malloc((count ? count : 1) * sizeof(*order));
    size_t n, k;

    if (!order)
        return -1;
    for (n = 0; n < count; n++)
        order[n] = &ports[n];
    qsort(order, count, sizeof(*order), phd_layout_lv2_order);
    phd_layout_put(sink, ctx, PHD_PIN_LAYOUT_SCHEME " " PHD_PIN_LAYOUT_LV2 "\n");
    for (n = 0; n < count; n++)
    {
        const phd_layout_lv2_port_t *p = order[n];
        const char **props = NULL;

        if (p->nproperties)
        {
            props = (const char **)malloc(p->nproperties * sizeof(*props));
            if (!props)
            {
                free(order);
                return -1;
            }
            memcpy(props, p->properties, p->nproperties * sizeof(*props));
            qsort(props, p->nproperties, sizeof(*props), phd_layout_bytewise);
        }
        phd_layout_uint(sink, ctx, p->index, 0);
        sink(ctx, "\t", 1);
        phd_layout_text(sink, ctx, p->symbol ? p->symbol : "");
        sink(ctx, "\t", 1);
        phd_layout_put(sink, ctx, p->output ? "out" : "in");
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->min, (p->has & PHD_LAYOUT_HAS_MIN) != 0);
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->max, (p->has & PHD_LAYOUT_HAS_MAX) != 0);
        sink(ctx, "\t", 1);
        phd_layout_number(sink, ctx, p->def, (p->has & PHD_LAYOUT_HAS_DEF) != 0);
        sink(ctx, "\t", 1);
        if (!p->nproperties)
            sink(ctx, "-", 1);
        for (k = 0; k < p->nproperties; k++)
        {
            if (k)
                sink(ctx, " ", 1);
            phd_layout_put(sink, ctx, props[k]);
        }
        sink(ctx, "\n", 1);
        free(props);
    }
    free(order);
    return 0;
}

static inline void phd_layout_hash_sink(void *ctx, const char *data, size_t size)
{
    phd_sha256_update((phd_sha256_t *)ctx, data, size);
}

/* the fingerprint of a CLAP layout, 64 hex digits; 0, or -1 when memory runs out */
static inline int phd_layout_clap_digest(const phd_layout_clap_param_t *params, size_t count,
                                         char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    if (phd_layout_clap_write(params, count, phd_layout_hash_sink, &c) != 0)
        return -1;
    phd_sha256_final(&c, hex);
    return 0;
}

/* the fingerprint of an LV2 layout, 64 hex digits; 0, or -1 when memory runs out */
static inline int phd_layout_lv2_digest(const phd_layout_lv2_port_t *ports, size_t count,
                                        char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    if (phd_layout_lv2_write(ports, count, phd_layout_hash_sink, &c) != 0)
        return -1;
    phd_sha256_final(&c, hex);
    return 0;
}

#endif

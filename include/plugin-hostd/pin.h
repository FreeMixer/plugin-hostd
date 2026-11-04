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

#include <openssl/evp.h>

#define PHD_PIN_LAYOUT_SCHEME "omx-layout/1"
#define PHD_PIN_LAYOUT_CLAP   "clap"
#define PHD_PIN_LAYOUT_LV2    "lv2"
#define PHD_SHA256_HEX_LEN    64

/* ---------------------------------------------------------------- SHA-256 (OpenSSL's libcrypto) */

/* one digest under way: libcrypto's context, and whether every step so far succeeded */
typedef struct PHD_SHA256_T {
    EVP_MD_CTX *ctx;
    int ok;
} phd_sha256_t;

static inline void phd_sha256_init(phd_sha256_t *c)
{
    c->ctx = EVP_MD_CTX_new();
    c->ok = c->ctx && EVP_DigestInit_ex(c->ctx, EVP_sha256(), NULL) == 1;
}

static inline void phd_sha256_update(phd_sha256_t *c, const void *data, size_t size)
{
    c->ok = c->ok && EVP_DigestUpdate(c->ctx, data, size) == 1;
}

/* a digest given up before its end: its context freed */
static inline void phd_sha256_abandon(phd_sha256_t *c)
{
    EVP_MD_CTX_free(c->ctx);
    c->ctx = NULL;
    c->ok = 0;
}

/* the digest as 64 lowercase hex digits and a NUL: 0, or -1 (and an empty string) when libcrypto failed */
static inline int phd_sha256_final(phd_sha256_t *c, char hex[PHD_SHA256_HEX_LEN + 1])
{
    static const char digits[] = "0123456789abcdef";
    unsigned char md[EVP_MAX_MD_SIZE];
    unsigned int got = 0, n;

    c->ok = c->ok && EVP_DigestFinal_ex(c->ctx, md, &got) == 1 && got == 32;
    EVP_MD_CTX_free(c->ctx);
    c->ctx = NULL;
    hex[0] = '\0';
    if (!c->ok)
        return -1;
    for (n = 0; n < 32; n++)
    {
        hex[n * 2] = digits[md[n] >> 4];
        hex[n * 2 + 1] = digits[md[n] & 15];
    }
    hex[PHD_SHA256_HEX_LEN] = '\0';
    return 0;
}

static inline int phd_sha256_hex(const void *data, size_t size, char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    phd_sha256_update(&c, data, size);
    return phd_sha256_final(&c, hex);
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
        {
            phd_sha256_abandon(&c);
            return -1;
        }
        phd_sha256_update(&c, buffer, (size_t)got);
    }
    return phd_sha256_final(&c, hex);
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

/* the fingerprint of a CLAP layout, 64 hex digits; 0, or -1 when memory runs out or libcrypto fails */
static inline int phd_layout_clap_digest(const phd_layout_clap_param_t *params, size_t count,
                                         char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    if (phd_layout_clap_write(params, count, phd_layout_hash_sink, &c) != 0)
    {
        phd_sha256_abandon(&c);
        return -1;
    }
    return phd_sha256_final(&c, hex);
}

/* the fingerprint of an LV2 layout, 64 hex digits; 0, or -1 when memory runs out or libcrypto fails */
static inline int phd_layout_lv2_digest(const phd_layout_lv2_port_t *ports, size_t count,
                                        char hex[PHD_SHA256_HEX_LEN + 1])
{
    phd_sha256_t c;

    phd_sha256_init(&c);
    if (phd_layout_lv2_write(ports, count, phd_layout_hash_sink, &c) != 0)
    {
        phd_sha256_abandon(&c);
        return -1;
    }
    return phd_sha256_final(&c, hex);
}

#endif

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


/* src/lv2.c's refusal and pick tables when memory runs out. lv2.c is built for this test with its realloc calls renamed
 * to alloc_test_realloc (the Makefile's -Drealloc), so the test decides which allocation fails. The stubs below stand for
 * the daemon parts lv2.c calls and these tables never reach. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <plugin-hostd/protocol.h>

#include "conf.h"
#include "formats.h"
#include "pins.h"
#include "proc.h"
#include "supervisor.h"

static int failures, checks;

/* how many reallocs succeed before the next one fails; -1 is never */
static int g_fail_after = -1;

void *alloc_test_realloc(void *ptr, size_t size);

void *alloc_test_realloc(void *ptr, size_t size)
{
    if (g_fail_after == 0)
        return NULL;
    if (g_fail_after > 0)
        g_fail_after--;
    return realloc(ptr, size);
}

int format_by_name(const char *name)
{
    (void)name;
    return 0;
}

int pin_percent_decode(const char *in, char *out, size_t size)
{
    snprintf(out, size, "%s", in);
    return 0;
}

int pin_refuse(const char *uri, const char *path, const char *why)
{
    (void)uri;
    (void)path;
    (void)why;
    return 0;
}

char *proc_find_lv2_bundle(const char *lv2_path, const char *uri)
{
    (void)lv2_path;
    (void)uri;
    return NULL;
}

const char *sup_instance_uri(int id)
{
    (void)id;
    return NULL;
}

const char *sup_instance_search(int id)
{
    (void)id;
    return NULL;
}

char *sup_call(int id, const char *line)
{
    (void)id;
    (void)line;
    return NULL;
}

int sup_reply_code(const char *reply)
{
    (void)reply;
    return 0;
}

char *sup_resp(int code)
{
    (void)code;
    return NULL;
}

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL lv2 tables: %s\n", what);
    }
}

static const char *route(const char *uri, const char *worker)
{
    conf_t conf;

    memset(&conf, 0, sizeof(conf));
    snprintf(conf.lv2_worker, sizeof(conf.lv2_worker), "%s", worker);
    return lv2_route(&conf, uri);
}

int main(void)
{
    const char *u1 = "urn:test:one", *u2 = "urn:test:two";
    const char *clap = "omx-clap-host";

    /* the refusal table */
    lv2_adapter_refused(u1);
    check(route(u1, "auto") == NULL, "positive control: a refusal is remembered with memory");
    g_fail_after = 0;
    lv2_adapter_refused(u2);
    g_fail_after = -1;
    check(route(u2, "auto") != NULL, "a refusal with no memory is not remembered (the adapter is asked again)");
    check(route(u1, "auto") == NULL, "the refusal held before is still there");
    lv2_adapter_refused(u2);
    check(route(u2, "auto") == NULL, "with memory again the refusal is remembered");
    lv2_refusals_forget(NULL);

    /* the pick table: under mod-host a uri is on the lv2 row (no route) unless a pick sends it to the CLAP worker */
    check(lv2_worker_pick(u1, clap) == 0 && route(u1, "mod-host") != NULL, "positive control: a pick is kept with memory");
    g_fail_after = 0;
    check(lv2_worker_pick(u2, clap) == -1, "a pick with no memory is refused");
    g_fail_after = -1;
    check(route(u2, "mod-host") == NULL, "the refused pick left no entry: the uri still follows the lv2_worker setting");
    check(route(u1, "mod-host") != NULL, "the pick held before is still there");
    check(lv2_worker_pick(u2, clap) == 0 && route(u2, "mod-host") != NULL, "with memory again the pick is kept");
    check(lv2_worker_pick(u1, PHD_WORD_NONE) == 0 && route(u1, "mod-host") == NULL, "a pick is taken back");

    printf("lv2 tables: %d checks, %s\n", checks, failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}

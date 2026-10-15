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

/* A format the daemon has never heard of, registered here and nowhere else, goes through add, param_set, pin and remove with
 * no change to the protocol: the table's row is all it needs. And a row with a capability missing is refused by
 * formats_register, with the missing one named, so a half-written format is a red test and not a daemon that starts.
 *
 * The third format is "fake3": uri prefix "fake3:" kept for the worker, one file beside the plugin pinned (as a
 * single-file format does), no layout check, pools allowed, the worker answers the instance verbs. It is served by
 * tests/fake-host, given on the command line. */

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <host-errors.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "conf.h"
#include "formats.h"
#include "pins.h"
#include "supervisor.h"

static int failures, checks;

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL format: %s\n", what);
    }
}

static void check_reply(char *got, const char *want, const char *what)
{
    char text[256];

    checks++;
    if (strcmp(got, want))
    {
        failures++;
        snprintf(text, sizeof(text), "%s: got '%s', wanted '%s'", what, got, want);
        printf("FAIL format: %s\n", text);
    }
    free(got);
}

static char g_worker[PATH_MAX];

static const char *fake3_worker(const conf_t *conf)
{
    (void)conf;
    return g_worker;
}

/* fake3:<path>: the file at <path> is what the host loads; a pin holds its basename */
static int fake3_collect(const char *uri, const char *search, char *root, size_t size, names_t *files)
{
    const char *path = uri + strlen("fake3:"), *slash = strrchr(path, '/');

    (void)search;
    if (!slash)
        return pin_refuse(uri, path, "is not a path");
    snprintf(root, size, "%.*s", (int)(slash - path), path);
    names_add(files, slash + 1);
    return SUCCESS;
}

static char *fake3_narrow(const conf_t *conf, const char *dir, const char *uri)
{
    (void)conf;
    (void)uri;
    return strdup(dir);
}

static format_t fake3(void)
{
    format_t f;

    memset(&f, 0, sizeof(f));
    f.name = "fake3";
    f.prefix = "fake3:";
    f.worker = fake3_worker;
    f.pin_collect = fake3_collect;
    f.native_instance_verbs = 1;
    return f;
}

static void rejected_row(const format_t *f, const char *what)
{
    int before = formats_count();

    check(formats_register(f) == -1, what);
    check(formats_count() == before, "a refused row leaves the table as it was");
}

static void capabilities_are_required(void)
{
    format_t f;

    f = fake3();
    f.name = NULL;
    rejected_row(&f, "a format with no name is refused");
    f = fake3();
    f.name = PHD_FORMAT_ANY;
    rejected_row(&f, "a format named like the word for every format is refused");
    f = fake3();
    f.worker = NULL;
    rejected_row(&f, "a format with no worker is refused");
    f = fake3();
    f.pin_collect = NULL;
    rejected_row(&f, "a format that does not say which files its pin holds is refused");
    f = fake3();
    f.prefix = NULL;
    rejected_row(&f, "a format no uri can reach is refused");
    f = fake3();
    f.native_instance_verbs = 0;
    rejected_row(&f, "a format whose instance verbs nobody answers is refused");
    f = fake3();
    f.narrow_world = fake3_narrow;
    rejected_row(&f, "a format that narrows its world with nowhere to carry it is refused");
    f = fake3();
    f.name = PHD_FORMAT_CLAP;
    rejected_row(&f, "a name that is taken is refused");
    f = fake3();
    f.prefix = "cl";
    rejected_row(&f, "a prefix that another prefix starts with is refused");
    f = fake3();
    f.fallback = 1;
    rejected_row(&f, "a second fallback is refused");
}

static void write_file(const char *path, const char *text)
{
    FILE *file = fopen(path, "w");

    if (file)
    {
        fputs(text, file);
        fclose(file);
    }
}

static int contains(char *text, const char *needle)
{
    int found = strstr(text, needle) != NULL;

    free(text);
    return found;
}

int main(int argc, char **argv)
{
    char root[PATH_MAX], plugin[PATH_MAX], uri[PATH_MAX + 16], store[PATH_MAX], files[PATH_MAX + 128], hex[PHD_SHA256_HEX_LEN + 1];
    char layout[PHD_SHA256_HEX_LEN + 64], good_hex[PHD_SHA256_HEX_LEN + 1];
    const char *base = getenv("PLUGIN_HOSTD_FORMAT_TEST_DIR");
    format_t f = fake3();
    conf_t conf;
    int index;

    if (argc != 2 || !base)
    {
        fprintf(stderr, "usage: PLUGIN_HOSTD_FORMAT_TEST_DIR=<scratch> %s <fake-host>\n", argv[0]);
        return 2;
    }
    snprintf(g_worker, sizeof(g_worker), "%s", argv[1]);
    snprintf(root, sizeof(root), "%s/format-test.%d", base, (int)getpid());
    mkdir(root, 0700);
    snprintf(plugin, sizeof(plugin), "%s/plugin.f3", root);
    snprintf(uri, sizeof(uri), "fake3:%s", plugin);
    snprintf(store, sizeof(store), "%s/pins", root);

    capabilities_are_required();

    index = formats_register(&f);
    check(index == formats_count() - 1 && index >= 2, "the third format joins the table");
    check(format_by_name("fake3") == index, "it is found by its name");
    check(format_of_uri(uri, NULL) == index, "its uri reaches it");
    check(format_of_uri("urn:some:lv2", NULL) == format_by_name(PHD_FORMAT_LV2), "a bare uri is still the fallback's");

    conf_defaults(&conf);
    snprintf(conf.state_root, sizeof(conf.state_root), "%s", root);
    snprintf(conf.mod_host, sizeof(conf.mod_host), "%s", g_worker);
    snprintf(conf.clap_host, sizeof(conf.clap_host), "%s", g_worker);
    snprintf(conf.pin_mode, sizeof(conf.pin_mode), "%s", PHD_PIN_MODE_STRICT);
    snprintf(conf.pin_store, sizeof(conf.pin_store), "%s", store);
    conf.require_pins = 1;
    conf.ready_timeout_ms = 4000;
    check(conf_check(&conf) == 0, "the settings are consistent");
    check(pins_init(conf.pin_store, "") == 0, "the pin store starts empty");
    sup_init(&conf);

    write_file(plugin, "third format, build one");
    {
        FILE *file = fopen(plugin, "rb");
        char bytes[64];
        size_t got = file ? fread(bytes, 1, sizeof(bytes), file) : 0;

        if (file)
            fclose(file);
        phd_sha256_hex(bytes, got, good_hex);
    }
    snprintf(hex, sizeof(hex), "%s", good_hex);
    snprintf(layout, sizeof(layout), PHD_PIN_LAYOUT_SCHEME PHD_PIN_SCHEME_SEPARATOR "%s", good_hex);
    snprintf(files, sizeof(files), "plugin.f3" PHD_PIN_DIGEST_SEPARATOR "%s", hex);

    /* add: no pin, no worker */
    check_reply(sup_add(uri, 0, NULL, NULL), "resp -508", "an unpinned plugin of the new format is refused");
    check(pins_set(uri, files, layout, NULL) == SUCCESS, "pin: the pin of the new format's plugin is taken");
    check_reply(sup_add(uri, 0, NULL, NULL), "resp 0", "add: the pinned plugin is added");
    check(contains(sup_worker_list(), ":fake3:"), "the worker list names the new format");

    /* param */
    check_reply(sup_call(0, "param_set 0 gain 0.5"), "resp 0", "param: the worker answers a parameter set");

    /* pin: a changed file is refused by the rule of the table's row, with no worker for it */
    write_file(plugin, "third format, build two");
    check_reply(sup_add(uri, 1, NULL, NULL), "resp -509", "pin: a changed file of the new format is refused");
    write_file(plugin, "third format, build one");
    check_reply(sup_add(uri, 1, NULL, NULL), "resp 1", "pin: the file back, the add passes");

    /* policy and environment resolve the new name through the table */
    check_reply(sup_policy_set("fake3", "pool:shared"), "resp 0", "policy: the new format's name is accepted");
    check_reply(sup_worker_env("fake3", "-", "5"), "resp 0", "env: the new format's name is accepted");
    check_reply(sup_policy_set("nothing", "own"), "resp -902", "policy: a name outside the table is refused");

    /* remove */
    check_reply(sup_remove(1), "resp 0", "remove: the second instance goes");
    check_reply(sup_remove(0), "resp 0", "remove: the first instance goes");
    check_reply(sup_worker_list(), "resp 0", "remove: no worker is left");

    sup_finish();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

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

/* The smallest child the probe runner's LV2 tests can run a plugin with: it takes plugin-qualify's lv2_measure
 * arguments and prints lines of the same shape, with no lilv and no interposer.
 *
 *   lv2-probe-child --pin <uri>                                 the integrity block; exit 3 for no such plugin
 *   lv2-probe-child <uri> [rate] [block] [cycles] [repeats]     one measurement line
 *
 * The bundle is the directory on LV2_PATH whose manifest.ttl names <uri>; its library is the manifest's lv2:binary,
 * loaded with dlopen. The plugin's own code runs here: a plugin that crashes, hangs or leaves a process behind in run()
 * (tests/lv2_fixture.c's "stress", STRESS_FAULT) does it in this process, as it would in lv2_measure. The layout pin is
 * a fixed digest: the runner copies it and computes none. A measurement refuses to run without OMX_STIM=noise, and
 * reports the interposer as loaded when LD_PRELOAD names rt_interpose.so, so a test sees what the runner set. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dirent.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <lv2/core/lv2.h>
#include <plugin-hostd/pin.h>

#define FILES_MAX 16

static char g_bundle[PATH_MAX], g_library[PATH_MAX];

static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    char *text;
    long size;

    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    text = calloc(1, (size_t)size + 1);
    if (text && fread(text, 1, (size_t)size, f) != (size_t)size)
    {
        free(text);
        text = NULL;
    }
    fclose(f);
    return text;
}

/* the bundle on LV2_PATH whose manifest names <uri>, and the library its lv2:binary names */
static int find(const char *uri)
{
    char *path = strdup(getenv("LV2_PATH") ? getenv("LV2_PATH") : ""), *dir, *save = NULL, needle[1024];
    int found = 0;

    snprintf(needle, sizeof(needle), "<%s>", uri);
    for (dir = strtok_r(path, ":", &save); dir && !found; dir = strtok_r(NULL, ":", &save))
    {
        DIR *d = opendir(dir);
        struct dirent *e;

        while (d && !found && (e = readdir(d)))
        {
            char manifest[PATH_MAX], *text, *at, *bin;

            if (e->d_name[0] == '.')
                continue;
            snprintf(manifest, sizeof(manifest), "%s/%s/manifest.ttl", dir, e->d_name);
            text = slurp(manifest);
            if (text && (at = strstr(text, needle)) && (bin = strstr(at, "lv2:binary <")))
            {
                char *end = strchr(bin + 12, '>');

                if (end)
                {
                    snprintf(g_bundle, sizeof(g_bundle), "%s/%s", dir, e->d_name);
                    snprintf(g_library, sizeof(g_library), "%.*s", (int)(end - bin - 12), bin + 12);
                    found = 1;
                }
            }
            free(text);
        }
        if (d)
            closedir(d);
    }
    free(path);
    return found;
}

static int by_name(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static int pin_only(const char *uri)
{
    DIR *d;
    struct dirent *e;
    char *names[FILES_MAX];
    int n = 0, i;

    char base[1024];
    const char *cut = strstr(uri, "-unpinnable");

    /* "<uri>-unpinnable" is <uri>'s bundle, of which lv2_measure could pin nothing */
    snprintf(base, sizeof(base), "%.*s", cut ? (int)(cut - uri) : (int)strlen(uri), uri);
    printf("{\"uri\":\"%s\",\"found\":%s", uri, find(base) ? "true" : "false");
    if (!g_bundle[0])
    {
        printf("}\n");
        return 3;
    }
    if (cut)
    {
        printf(",\"integrity\":{\"unmeasuredReason\":\"unpinnable\",\"unmeasuredDetail\":\"the manifest sets @base\"}}\n");
        return 0;
    }
    d = opendir(g_bundle);
    while (d && (e = readdir(d)) && n < FILES_MAX)
        if (strstr(e->d_name, ".ttl") || !strcmp(e->d_name, g_library))
            names[n++] = strdup(e->d_name);
    if (d)
        closedir(d);
    qsort(names, (size_t)n, sizeof(names[0]), by_name);
    printf(",\"integrity\":{\"files\":[");
    for (i = 0; i < n; i++)
    {
        char path[PATH_MAX], sha[PHD_SHA256_HEX_LEN + 1] = "";
        int fd;

        snprintf(path, sizeof(path), "%s/%s", g_bundle, names[i]);
        fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd >= 0)
        {
            phd_pin_fd_digest(fd, sha);
            close(fd);
        }
        printf("%s{\"path\":\"%s\",\"sha256\":\"%s\"}", i ? "," : "", names[i], sha);
        free(names[i]);
    }
    printf("],\"layout\":{\"scheme\":\"%s\",\"sha256\":\"%064d\"}}}\n", PHD_PIN_LAYOUT_SCHEME, 0);
    return 0;
}

static int threads(void)
{
    DIR *d = opendir("/proc/self/task");
    struct dirent *e;
    int n = 0;

    while (d && (e = readdir(d)))
        if (e->d_name[0] != '.')
            n++;
    if (d)
        closedir(d);
    return n;
}

int main(int argc, char **argv)
{
    const char *uri;
    double rate;
    unsigned block;
    int cycles, repeats, c, r, b, instantiated = 0, before = threads(), after_first = 0;
    char library[PATH_MAX * 2];
    void *lib;
    const LV2_Descriptor *(*entry)(uint32_t);
    const LV2_Descriptor *desc = NULL;
    static float in[8192], out[8192];
    float gain = 1.0f;
    uint32_t i;

    if (argc == 3 && !strcmp(argv[1], "--pin"))
        return pin_only(argv[2]);
    if (argc < 2 || argv[1][0] == '-')
        return 1;
    uri = argv[1];
    rate = argc > 2 ? atof(argv[2]) : 192000.0;
    block = argc > 3 ? (unsigned)atoi(argv[3]) : 512;
    cycles = argc > 4 ? atoi(argv[4]) : 20;
    repeats = argc > 5 ? atoi(argv[5]) : 3;
    /* the runner measures as plugin-qualify does: the noise stimulus, under the interposer beside this program */
    if (!getenv("OMX_STIM") || strcmp(getenv("OMX_STIM"), "noise"))
    {
        fprintf(stderr, "lv2-probe-child: OMX_STIM is not noise\n");
        return 1;
    }
    if (block == 0 || block > 8192 || !find(uri))
    {
        printf("{\"uri\":\"%s\",\"found\":false}\n", uri);
        return 3;
    }
    snprintf(library, sizeof(library), "%s/%s", g_bundle, g_library);
    lib = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    entry = lib ? (const LV2_Descriptor *(*)(uint32_t))dlsym(lib, "lv2_descriptor") : NULL;
    for (i = 0; entry && (desc = entry(i)); i++)
        if (!strcmp(desc->URI, uri))
            break;
    if (!desc)
    {
        printf("{\"uri\":\"%s\",\"found\":true,\"instantiated\":false,\"cyclesAttempted\":%d}\n", uri, cycles);
        return 2;
    }
    for (c = 0; c < cycles; c++)
    {
        LV2_Handle h = desc->instantiate(desc, rate, g_bundle, NULL);

        if (h)
        {
            instantiated++;
            if (c == 0)
                after_first = threads();
            desc->cleanup(h);
        }
    }
    for (r = 0; r < repeats; r++)
    {
        LV2_Handle h = desc->instantiate(desc, rate, g_bundle, NULL);

        if (!h)
            break;
        desc->connect_port(h, 0, in);
        desc->connect_port(h, 1, out);
        desc->connect_port(h, 2, &gain);
        if (desc->activate)
            desc->activate(h);
        for (b = 0; b < 64; b++)
            desc->run(h, block);
        if (desc->deactivate)
            desc->deactivate(h);
        desc->cleanup(h);
    }
    printf("{\"uri\":\"%s\",\"found\":true,\"instantiated\":true,\"rate\":%.0f,\"block\":%u,\"audioInputs\":1,\"audioOutputs\":1,"
           "\"cvPorts\":0,\"controlInputs\":1,\"requiredFeatures\":[],\"optionalFeatures\":[],"
           "\"lifecycle\":{\"cycles\":%d,\"instantiated\":%d,\"failed\":%d},"
           "\"threads\":{\"before\":%d,\"afterFirstInstantiate\":%d,\"afterAllFreed\":%d,\"leaked\":0},"
           "\"rtSafety\":{\"interposer\":%s,\"blocks\":64,\"repeats\":%d,\"swept\":false,\"sweepApplicable\":true,"
           "\"allocationsInRun\":0,\"allocationsMin\":0,\"variable\":false,\"locksInRun\":0,\"locksMin\":0,"
           "\"syscallsInRun\":0,\"syscallsMin\":0,\"events\":[]}}\n",
           uri, rate, block, cycles, instantiated, cycles - instantiated, before, after_first, threads(),
           getenv("LD_PRELOAD") && strstr(getenv("LD_PRELOAD"), "rt_interpose.so") ? "true" : "false", repeats);
    return 0;
}

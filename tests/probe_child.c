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

/* The smallest child the probe runner's tests can run a plugin with: it takes clap-qualify's arguments, loads the
 * .clap, creates and activates the plugin, writes a step record on file descriptor 3 after each step, runs one block
 * through process() and prints one JSON line of facts. A plugin that crashes, hangs or leaves a process behind in
 * process() (tests/stress_plugin.c, STRESS_FAULT) leaves the records written before. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <sched.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <clap/clap.h>

/* PROBE_CHILD_LIMITS names a file to write what the limits of this process are, as the runner left them */
static void report_limits(const char *file)
{
    FILE *f = fopen(file, "w");
    struct rlimit r;
    cpu_set_t set;
    int sig = 0;

    if (!f)
        return;
    getrlimit(RLIMIT_FSIZE, &r);
    fprintf(f, "{\"fsize\":%llu", (unsigned long long)r.rlim_cur);
    getrlimit(RLIMIT_NOFILE, &r);
    fprintf(f, ",\"nofile\":%llu", (unsigned long long)r.rlim_cur);
    getrlimit(RLIMIT_CPU, &r);
    fprintf(f, ",\"cpu\":%llu", (unsigned long long)r.rlim_cur);
    getrlimit(RLIMIT_DATA, &r);
    fprintf(f, ",\"data\":%llu", (unsigned long long)r.rlim_cur);
    getrlimit(RLIMIT_CORE, &r);
    fprintf(f, ",\"core\":%llu", (unsigned long long)r.rlim_cur);
    getrlimit(RLIMIT_RTPRIO, &r);
    fprintf(f, ",\"rtprio\":%llu", (unsigned long long)r.rlim_cur);
    prctl(PR_GET_PDEATHSIG, &sig);
    fprintf(f, ",\"no_new_privs\":%d,\"pdeathsig\":%d,\"own_group\":%s", prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0), sig,
            getpgrp() == getpid() ? "true" : "false");
    sched_getaffinity(0, sizeof(set), &set);
    fprintf(f, ",\"cpus\":%d}\n", CPU_COUNT(&set));
    fclose(f);
}

static long now_ms(void)
{
    struct timespec t;

    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long)(t.tv_sec * 1000 + t.tv_nsec / 1000000);
}

static uint32_t no_events_size(const clap_input_events_t *list)
{
    (void)list;
    return 0;
}

static const clap_event_header_t *no_events_get(const clap_input_events_t *list, uint32_t index)
{
    (void)list; (void)index;
    return NULL;
}

static bool no_events_push(const clap_output_events_t *list, const clap_event_header_t *event)
{
    (void)list; (void)event;
    return true;
}

static void record(const char *step, long rate, long quantum, long since)
{
    char line[256];
    int n = snprintf(line, sizeof(line), "{\"step\":\"%s\",\"outcome\":\"probe.ok\",\"elapsedMs\":%ld", step, now_ms() - since);

    if (rate)
        n += snprintf(line + n, sizeof(line) - (size_t)n, ",\"rate\":%ld,\"quantum\":%ld", rate, quantum);
    snprintf(line + n, sizeof(line) - (size_t)n, "}\n");
    if (write(3, line, strlen(line)) < 0)
        _exit(2);
}

int main(int argc, char **argv)
{
    const char *rates = "48000", *path = NULL, *id = NULL;
    long rate, quantum = 256, t0 = now_ms();
    void *lib;
    const clap_plugin_entry_t *entry;
    const clap_plugin_factory_t *factory;
    const clap_plugin_t *plugin;
    static float in_l[4096], in_r[4096], out_l[4096], out_r[4096];
    float *in_ch[2] = { in_l, in_r }, *out_ch[2] = { out_l, out_r };
    int a;

    for (a = 1; a < argc; a++)
    {
        if (!strcmp(argv[a], "--rates") && a + 1 < argc)
            rates = argv[++a];
        else if (!strcmp(argv[a], "--block") && a + 1 < argc)
            quantum = atol(argv[++a]);
        else if ((!strcmp(argv[a], "--blocks") || !strcmp(argv[a], "--offer")) && a + 1 < argc)
            a++;
        else if (!path)
            path = argv[a];
        else
            id = argv[a];
    }
    if (!path || quantum < 1 || quantum > 4096)
        return 2;
    if (getenv("PROBE_CHILD_LIMITS"))
        report_limits(getenv("PROBE_CHILD_LIMITS"));
    rate = atol(rates);
    lib = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    entry = lib ? dlsym(lib, "clap_entry") : NULL;
    if (!entry || !entry->init(path))
        return 2;
    factory = entry->get_factory(CLAP_PLUGIN_FACTORY_ID);
    if (!factory || factory->get_plugin_count(factory) == 0)
        return 2;
    if (!id)
        id = factory->get_plugin_descriptor(factory, 0)->id;
    {
        static clap_host_t host = { CLAP_VERSION_INIT, NULL, "probe-child", "plugin-hostd", "", "0", NULL, NULL, NULL, NULL };

        plugin = factory->create_plugin(factory, &host, id);
    }
    if (!plugin || !plugin->init(plugin))
        return 2;
    record("instantiate", 0, 0, t0);
    plugin->activate(plugin, (double)rate, 1, (uint32_t)quantum);
    plugin->start_processing(plugin);
    record("latency", rate, quantum, t0);
    {
        clap_audio_buffer_t in = { in_ch, NULL, 2, 0, 0 }, out = { out_ch, NULL, 2, 0, 0 };
        clap_input_events_t events_in = { NULL, no_events_size, no_events_get };
        clap_output_events_t events_out = { NULL, no_events_push };
        clap_process_t p = { 0, (uint32_t)quantum, NULL, &in, &out, 1, 1, &events_in, &events_out };

        plugin->process(plugin, &p);
    }
    plugin->stop_processing(plugin);
    plugin->deactivate(plugin);
    plugin->destroy(plugin);
    printf("{\"id\":\"%s\",\"format\":\"clap\",\"hostExtensions\":[],\"clap\":{\"headlessOk\":true,\"latency\":{\"%ld\":"
           "{\"declaredFrames\":0,\"measuredFrames\":0}},\"threadViolations\":0,\"processErrors\":0},\"rtSafety\":{\"interposer\":false}}\n",
           id, rate);
    return 0;
}

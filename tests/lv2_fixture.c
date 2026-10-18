/* SPDX-License-Identifier: GPL-3.0-or-later */

/* The LV2 plugin of the real-worker test of the adapter (tests/lv2_adapter_e2e.py): a mono gain that every LV2 host
 * runs, under these URIs. "gain" is the one omx-clap-host's adapter takes; "atom-in" adds an atom input that supports
 * no MIDI, which the adapter takes too (it feeds the input empty sequences) and mod-host runs with the notes by jack;
 * "fixed-block" requires the host feature buf-size#fixedBlockLength, which the adapter lacks and refuses
 * (hosting.features.missing) and mod-host provides; "based" is "gain" again
 * under http://plugin-hostd.invalid/fixture/based, named in a manifest the test writes with an @base, so lilv finds it
 * and the adapter's search of the manifest text does not (resp -101). "stress" is "gain" that breaks on cue, for the
 * probe runner's LV2 tests (tests/probe_test.py). The ports, by index: 0 in, 1 out, 2 gain (a factor), 3 events
 * (atom-in only). */

#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <lv2/core/lv2.h>

#define FIXTURE_URI "urn:plugin-hostd:test:"
/* a hierarchical uri, so that a relative <based> resolves against it as an @base */
#define FIXTURE_BASE "http://plugin-hostd.invalid/fixture/"

typedef struct {
    const float *in;
    float *out;
    const float *gain;
} fixture_t;

static LV2_Handle instantiate(const LV2_Descriptor *descriptor, double rate, const char *bundle, const LV2_Feature *const *features)
{
    (void)descriptor;
    (void)rate;
    (void)bundle;
    (void)features;
    return calloc(1, sizeof(fixture_t));
}

static void connect_port(LV2_Handle instance, uint32_t port, void *data)
{
    fixture_t *f = instance;

    if (port == 0)
        f->in = data;
    else if (port == 1)
        f->out = data;
    else if (port == 2)
        f->gain = data;
}

static void run(LV2_Handle instance, uint32_t frames)
{
    fixture_t *f = instance;
    float gain = f->gain ? *f->gain : 1.0f;
    uint32_t n;

    if (!f->in || !f->out)
        return;
    for (n = 0; n < frames; n++)
        f->out[n] = f->in[n] * gain;
}

/* stress: the gain, with the fault STRESS_FAULT names on its first run() in the process, as tests/stress_plugin.c does
 * for CLAP: crash aborts, hang spins forever, fork leaves a process of its own session behind (its pid written to the
 * file STRESS_FORK_PIDFILE names) */
static void fault_once(void)
{
    static int done;
    const char *fault = getenv("STRESS_FAULT");

    if (done || !fault)
        return;
    done = 1;
    if (!strcmp(fault, "crash"))
        abort();
    if (!strcmp(fault, "hang"))
        for (;;)
            ;
    if (!strcmp(fault, "fork") && fork() == 0)
    {
        const char *pidfile = getenv("STRESS_FORK_PIDFILE");

        setsid();
        if (pidfile)
        {
            FILE *f = fopen(pidfile, "w");

            if (f)
            {
                fprintf(f, "%d\n", (int)getpid());
                fclose(f);
            }
        }
        sleep(60);
        _exit(0);
    }
}

static void run_stress(LV2_Handle instance, uint32_t frames)
{
    fault_once();
    run(instance, frames);
}

static void cleanup(LV2_Handle instance)
{
    free(instance);
}

static const LV2_Descriptor DESCRIPTORS[] = {
    { FIXTURE_URI "gain", instantiate, connect_port, NULL, run, NULL, cleanup, NULL },
    { FIXTURE_URI "atom-in", instantiate, connect_port, NULL, run, NULL, cleanup, NULL },
    { FIXTURE_URI "fixed-block", instantiate, connect_port, NULL, run, NULL, cleanup, NULL },
    { FIXTURE_URI "stress", instantiate, connect_port, NULL, run_stress, NULL, cleanup, NULL },
    { FIXTURE_BASE "based", instantiate, connect_port, NULL, run, NULL, cleanup, NULL },
};

LV2_SYMBOL_EXPORT const LV2_Descriptor *lv2_descriptor(uint32_t index)
{
    return index < sizeof(DESCRIPTORS) / sizeof(DESCRIPTORS[0]) ? &DESCRIPTORS[index] : NULL;
}

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

/* A stereo passthrough .clap the daemon's tests break on purpose:
 *   org.plugin-hostd.test.stress        parameters
 *                                         0 crash   a write above 0.5 aborts inside process; with STRESS_CRASH_ONCE
 *                                                   naming a file, only when the file is not there yet, and the
 *                                                   crash creates it
 *                                         1 hog     microseconds spun inside every process call
 *                                         2 thread  above 0.5 starts a thread that burns a core, from the main thread
 *                                         3 level   a plain value, and the whole of the state
 *   org.plugin-hostd.test.crash_on_add  aborts when it is created */

#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <time.h>
#include <unistd.h>
#include <clap/clap.h>

#define ID_STRESS       "org.plugin-hostd.test.stress"
#define ID_CRASH_ON_ADD "org.plugin-hostd.test.crash_on_add"
#define PARAM_COUNT     4
#define STATE_MAGIC     0x50485354u

typedef struct STRESS_T {
    clap_plugin_t plugin;
    const clap_host_t *host;
    double value[PARAM_COUNT];
    volatile int burning;
    volatile int want_thread;
    pthread_t thread;
    int thread_started;
} stress_t;

/* the crashes of this fixture are deliberate: the process is made non-dumpable first, so that they leave no
 * core dump and no coredumpctl entry */
static void crash(void)
{
    prctl(PR_SET_DUMPABLE, 0);
    abort();
}

static const char *const g_features[] = { CLAP_PLUGIN_FEATURE_AUDIO_EFFECT, NULL };
static const char *const g_names[PARAM_COUNT] = { "crash", "hog", "thread", "level" };
static const double g_max[PARAM_COUNT] = { 1.0, 20000.0, 1.0, 1000.0 };

static const clap_plugin_descriptor_t g_descriptors[] = {
    { CLAP_VERSION_INIT, ID_STRESS, "stress", "plugin-hostd", "", "", "", "0", "stress", g_features },
    { CLAP_VERSION_INIT, ID_CRASH_ON_ADD, "crash_on_add", "plugin-hostd", "", "", "", "0", "crash_on_add", g_features },
};

#define DESCRIPTOR_COUNT (sizeof(g_descriptors) / sizeof(g_descriptors[0]))

static uint32_t audio_ports_count(const clap_plugin_t *plugin, bool is_input)
{
    (void)plugin; (void)is_input;
    return 1;
}

static bool audio_ports_get(const clap_plugin_t *plugin, uint32_t index, bool is_input, clap_audio_port_info_t *info)
{
    (void)plugin;
    if (index != 0)
        return false;
    memset(info, 0, sizeof(*info));
    info->id = 0;
    snprintf(info->name, sizeof(info->name), "%s", is_input ? "in" : "out");
    info->flags = CLAP_AUDIO_PORT_IS_MAIN;
    info->channel_count = 2;
    info->port_type = CLAP_PORT_STEREO;
    info->in_place_pair = CLAP_INVALID_ID;
    return true;
}

static const clap_plugin_audio_ports_t g_audio_ports = { audio_ports_count, audio_ports_get };

static uint32_t params_count(const clap_plugin_t *plugin)
{
    (void)plugin;
    return PARAM_COUNT;
}

static bool params_get_info(const clap_plugin_t *plugin, uint32_t index, clap_param_info_t *info)
{
    (void)plugin;
    if (index >= PARAM_COUNT)
        return false;
    memset(info, 0, sizeof(*info));
    info->id = index;
    info->min_value = 0.0;
    info->max_value = g_max[index];
    info->default_value = 0.0;
    snprintf(info->name, sizeof(info->name), "%s", g_names[index]);
    return true;
}

static bool params_get_value(const clap_plugin_t *plugin, clap_id id, double *value)
{
    const stress_t *stress = plugin->plugin_data;
    if (id >= PARAM_COUNT)
        return false;
    *value = stress->value[id];
    return true;
}

static bool params_value_to_text(const clap_plugin_t *plugin, clap_id id, double value, char *out, uint32_t size)
{
    (void)plugin;
    if (id >= PARAM_COUNT)
        return false;
    snprintf(out, size, "%.4f", value);
    return true;
}

static bool params_text_to_value(const clap_plugin_t *plugin, clap_id id, const char *text, double *value)
{
    (void)plugin;
    if (id >= PARAM_COUNT)
        return false;
    *value = atof(text);
    return true;
}

static void *burn(void *arg)
{
    stress_t *stress = arg;
    volatile double x = 1.0;

    while (stress->burning)
        x = x * 1.0000001 + 0.5;
    return NULL;
}

static void set_thread(stress_t *stress, int on)
{
    if (on && !stress->thread_started)
    {
        stress->burning = 1;
        stress->thread_started = pthread_create(&stress->thread, NULL, burn, stress) == 0;
    }
    else if (!on && stress->thread_started)
    {
        stress->burning = 0;
        pthread_join(stress->thread, NULL);
        stress->thread_started = 0;
    }
}

static void take_events(stress_t *stress, const clap_input_events_t *in)
{
    uint32_t i, n = in->size(in);

    for (i = 0; i < n; i++)
    {
        const clap_event_header_t *header = in->get(in, i);
        if (header->space_id == CLAP_CORE_EVENT_SPACE_ID && header->type == CLAP_EVENT_PARAM_VALUE)
        {
            const clap_event_param_value_t *event = (const clap_event_param_value_t *)header;
            if (event->param_id >= PARAM_COUNT)
                continue;
            stress->value[event->param_id] = event->value;
            if (event->param_id == 0 && event->value > 0.5)
            {
                const char *once = getenv("STRESS_CRASH_ONCE");

                if (!once || access(once, F_OK) != 0)
                {
                    if (once)
                        close(open(once, O_CREAT | O_WRONLY, 0644));
                    crash();
                }
            }
            if (event->param_id == 2)
            {
                stress->want_thread = event->value > 0.5;
                stress->host->request_callback(stress->host);
            }
        }
    }
}

static void params_flush(const clap_plugin_t *plugin, const clap_input_events_t *in, const clap_output_events_t *out)
{
    (void)out;
    take_events(plugin->plugin_data, in);
}

static const clap_plugin_params_t g_params = {
    params_count, params_get_info, params_get_value, params_value_to_text, params_text_to_value, params_flush
};

static bool state_save(const clap_plugin_t *plugin, const clap_ostream_t *stream)
{
    const stress_t *stress = plugin->plugin_data;
    uint32_t magic = STATE_MAGIC;

    return stream->write(stream, &magic, sizeof(magic)) == sizeof(magic)
        && stream->write(stream, stress->value, sizeof(stress->value)) == (int64_t)sizeof(stress->value);
}

static bool state_load(const clap_plugin_t *plugin, const clap_istream_t *stream)
{
    stress_t *stress = plugin->plugin_data;
    uint32_t magic = 0;
    double value[PARAM_COUNT];

    if (stream->read(stream, &magic, sizeof(magic)) != sizeof(magic) || magic != STATE_MAGIC)
        return false;
    if (stream->read(stream, value, sizeof(value)) != (int64_t)sizeof(value))
        return false;
    memcpy(stress->value, value, sizeof(value));
    return true;
}

static const clap_plugin_state_t g_state = { state_save, state_load };

static bool plugin_init(const clap_plugin_t *plugin)
{
    (void)plugin;
    return true;
}

static void plugin_destroy(const clap_plugin_t *plugin)
{
    stress_t *stress = plugin->plugin_data;

    set_thread(stress, 0);
    free(stress);
}

static bool plugin_activate(const clap_plugin_t *plugin, double sample_rate, uint32_t min_frames, uint32_t max_frames)
{
    (void)plugin; (void)sample_rate; (void)min_frames; (void)max_frames;
    return true;
}

static void plugin_deactivate(const clap_plugin_t *plugin)
{
    (void)plugin;
}

static bool plugin_start_processing(const clap_plugin_t *plugin)
{
    (void)plugin;
    return true;
}

static void plugin_stop_processing(const clap_plugin_t *plugin)
{
    (void)plugin;
}

static void plugin_reset(const clap_plugin_t *plugin)
{
    (void)plugin;
}

static void spin_us(double us)
{
    struct timespec t0, t;
    volatile double x = 1.0;

    clock_gettime(CLOCK_MONOTONIC, &t0);
    do
    {
        x = x * 1.0000001 + 0.5;
        clock_gettime(CLOCK_MONOTONIC, &t);
    } while ((t.tv_sec - t0.tv_sec) * 1e6 + (t.tv_nsec - t0.tv_nsec) / 1e3 < us);
}

static clap_process_status plugin_process(const clap_plugin_t *plugin, const clap_process_t *process)
{
    stress_t *stress = plugin->plugin_data;
    const clap_audio_buffer_t *in = &process->audio_inputs[0];
    clap_audio_buffer_t *out = &process->audio_outputs[0];
    uint32_t c;

    take_events(stress, process->in_events);
    if (stress->value[1] > 0.0)
        spin_us(stress->value[1]);
    for (c = 0; c < out->channel_count; c++)
        memcpy(out->data32[c], in->data32[c < in->channel_count ? c : 0], sizeof(float) * process->frames_count);
    return CLAP_PROCESS_CONTINUE;
}

static const void *plugin_get_extension(const clap_plugin_t *plugin, const char *id)
{
    (void)plugin;
    if (!strcmp(id, CLAP_EXT_AUDIO_PORTS))
        return &g_audio_ports;
    if (!strcmp(id, CLAP_EXT_PARAMS))
        return &g_params;
    if (!strcmp(id, CLAP_EXT_STATE))
        return &g_state;
    return NULL;
}

/* the thread is started from the main thread, so it inherits the host's scheduling and not the audio thread's */
static void plugin_on_main_thread(const clap_plugin_t *plugin)
{
    stress_t *stress = plugin->plugin_data;

    set_thread(stress, stress->want_thread);
}

static uint32_t factory_get_plugin_count(const clap_plugin_factory_t *factory)
{
    (void)factory;
    return DESCRIPTOR_COUNT;
}

static const clap_plugin_descriptor_t *factory_get_plugin_descriptor(const clap_plugin_factory_t *factory, uint32_t index)
{
    (void)factory;
    return index < DESCRIPTOR_COUNT ? &g_descriptors[index] : NULL;
}

static const clap_plugin_t *factory_create_plugin(const clap_plugin_factory_t *factory, const clap_host_t *host, const char *plugin_id)
{
    stress_t *stress;

    (void)factory;
    if (!strcmp(plugin_id, ID_CRASH_ON_ADD))
        crash();
    if (strcmp(plugin_id, ID_STRESS))
        return NULL;

    stress = calloc(1, sizeof(stress_t));
    stress->host = host;
    stress->plugin.desc = &g_descriptors[0];
    stress->plugin.plugin_data = stress;
    stress->plugin.init = plugin_init;
    stress->plugin.destroy = plugin_destroy;
    stress->plugin.activate = plugin_activate;
    stress->plugin.deactivate = plugin_deactivate;
    stress->plugin.start_processing = plugin_start_processing;
    stress->plugin.stop_processing = plugin_stop_processing;
    stress->plugin.reset = plugin_reset;
    stress->plugin.process = plugin_process;
    stress->plugin.get_extension = plugin_get_extension;
    stress->plugin.on_main_thread = plugin_on_main_thread;
    return &stress->plugin;
}

static const clap_plugin_factory_t g_factory = {
    factory_get_plugin_count, factory_get_plugin_descriptor, factory_create_plugin
};

static bool entry_init(const char *path)
{
    (void)path;
    return true;
}

static void entry_deinit(void)
{
}

static const void *entry_get_factory(const char *factory_id)
{
    return !strcmp(factory_id, CLAP_PLUGIN_FACTORY_ID) ? &g_factory : NULL;
}

CLAP_EXPORT const clap_plugin_entry_t clap_entry = {
    CLAP_VERSION_INIT, entry_init, entry_deinit, entry_get_factory
};

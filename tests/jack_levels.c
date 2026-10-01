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

/* Two tones through two chains, and the peak that comes out of each, every 50 ms:
 *   jack_levels <ms>
 * lv_src:out_1 and lv_src:out_2 are 1 kHz at 0.3; lv_sink:in_1 and lv_sink:in_2 print "<ms> <peak_1> <peak_2>"
 * (ms from the start) one line per 50 ms window, for <ms> milliseconds. The links are the caller's. */

#include <jack/jack.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static jack_port_t *g_out[2], *g_in[2];
static double g_phase;
static volatile float g_peak[2];

static int src_process(jack_nframes_t n, void *arg)
{
    jack_nframes_t i;
    int c;

    (void)arg;
    for (c = 0; c < 2; c++)
    {
        float *o = jack_port_get_buffer(g_out[c], n);
        double p = g_phase;

        for (i = 0; i < n; i++, p += 2 * M_PI * 1000.0 / 48000.0)
            o[i] = 0.3f * sinf((float)p);
        if (c == 1)
            g_phase = fmod(p, 2 * M_PI);
    }
    return 0;
}

static int sink_process(jack_nframes_t n, void *arg)
{
    jack_nframes_t i;
    int c;

    (void)arg;
    for (c = 0; c < 2; c++)
    {
        float *in = jack_port_get_buffer(g_in[c], n);

        for (i = 0; i < n; i++)
            if (fabsf(in[i]) > g_peak[c])
                g_peak[c] = fabsf(in[i]);
    }
    return 0;
}

int main(int argc, char **argv)
{
    jack_client_t *src = jack_client_open("lv_src", JackNoStartServer, NULL);
    jack_client_t *sink = jack_client_open("lv_sink", JackNoStartServer, NULL);
    int total = argc > 1 ? atoi(argv[1]) : 5000, t;

    if (!src || !sink)
        return 3;
    g_out[0] = jack_port_register(src, "out_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
    g_out[1] = jack_port_register(src, "out_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
    g_in[0] = jack_port_register(sink, "in_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    g_in[1] = jack_port_register(sink, "in_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    jack_set_process_callback(src, src_process, NULL);
    jack_set_process_callback(sink, sink_process, NULL);
    jack_activate(src);
    jack_activate(sink);
    printf("ready\n");
    fflush(stdout);
    for (t = 0; t < total; t += 50)
    {
        float a, b;

        g_peak[0] = g_peak[1] = 0;
        usleep(50000);
        a = g_peak[0];
        b = g_peak[1];
        printf("%d %.4f %.4f\n", t + 50, a, b);
        fflush(stdout);
    }
    return 0;
}

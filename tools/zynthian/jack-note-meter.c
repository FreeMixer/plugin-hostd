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

/* A note in, the peak that comes back out, before and after it:
 *   jack-note-meter <channel 0-15> <note> <ms>
 * Opens JACK client zyn_probe with midi_out, in_1 and in_2, and prints "ready" once active; the caller links them. After
 * <ms>/2 it sends note-on <note> velocity 100 on <channel>, and at the end prints
 *   before <peak dBFS of in_1+in_2 before the note> after <peak after it>
 * A silent window prints -inf. */

#include <jack/jack.h>
#include <jack/midiport.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static jack_port_t *g_midi, *g_in[2];
static volatile int g_send, g_sent;
static volatile float g_peak[2];

static int process(jack_nframes_t n, void *arg)
{
    void *buf = jack_port_get_buffer(g_midi, n);
    int which = g_sent ? 1 : 0;

    (void)arg;
    jack_midi_clear_buffer(buf);
    if (g_send && !g_sent)
    {
        unsigned char *ev = jack_midi_event_reserve(buf, 0, 3);

        if (ev)
        {
            ev[0] = 0x90 | (g_send >> 8);
            ev[1] = g_send & 0x7f;
            ev[2] = 100;
            g_sent = 1;
        }
    }
    for (int c = 0; c < 2; c++)
    {
        const float *s = jack_port_get_buffer(g_in[c], n);

        for (jack_nframes_t i = 0; i < n; i++)
            if (fabsf(s[i]) > g_peak[which])
                g_peak[which] = fabsf(s[i]);
    }
    return 0;
}

int main(int argc, char **argv)
{
    int chan = argc > 1 ? atoi(argv[1]) & 15 : 0, note = argc > 2 ? atoi(argv[2]) : 60, ms = argc > 3 ? atoi(argv[3]) : 2000;
    jack_client_t *c = jack_client_open("zyn_probe", JackNoStartServer | JackUseExactName, NULL);

    if (!c)
    {
        fprintf(stderr, "no JACK server\n");
        return 1;
    }
    g_midi = jack_port_register(c, "midi_out", JACK_DEFAULT_MIDI_TYPE, JackPortIsOutput, 0);
    g_in[0] = jack_port_register(c, "in_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    g_in[1] = jack_port_register(c, "in_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    jack_set_process_callback(c, process, NULL);
    if (jack_activate(c))
        return 1;
    printf("ready\n");
    fflush(stdout);
    usleep(ms * 500);
    g_send = (chan << 8) | note;
    usleep(ms * 500);
    printf("before %.1f after %.1f\n", 20 * log10f(g_peak[0]), 20 * log10f(g_peak[1]));
    jack_client_close(c);
    return 0;
}

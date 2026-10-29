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

/* A MIDI scenario played into an instrument, and what comes back out of it, window by window:
 *   jack-instrument-probe <scenario> [client name, default inst_probe]
 * Opens a JACK client with midi_out, in_1 and in_2, prints "ready" once active and waits for a line "go" on stdin
 * (the caller links the ports in between). The scenario is one step per line, played from the first cycle after "go":
 *   wait <ms>               the time moves on
 *   midi <b0> <b1> [<b2>]   a MIDI message (hex bytes) at the current time
 *   mark <label>            a measured window starts here (and the previous one ends)
 *   end                     the open window ends here
 * A window prints, when it starts, "mark <label>", and when it ends
 *   window <label> peak <dBFS> rms <dBFS> hz <f> bright <r> frames <n> xruns <k>
 * where peak and rms are over in_1 and in_2, hz is in_1's rising zero crossings per second (a pitch for one note),
 * bright is the RMS of in_1's first difference over its RMS (it grows with the high partials), and xruns counts the
 * server's xruns while the window was open. A silent window prints -inf. "done" ends the run. */

#include <jack/jack.h>
#include <jack/midiport.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_EVENTS 8192
#define MAX_WINDOWS 256

struct event {
    jack_nframes_t at;
    unsigned char b[3];
    int len;
};

struct window {
    char label[64];
    jack_nframes_t from, to;
    double sumsq, sumdiff;
    float peak;
    unsigned long frames, zc;
    int xrun_from, xrun_to;
};

static struct event g_ev[MAX_EVENTS];
static struct window g_win[MAX_WINDOWS];
static int g_nev, g_nwin;
static jack_port_t *g_midi, *g_in[2];
static volatile int g_go, g_xruns;
static volatile jack_nframes_t g_now;
static int g_next_ev;
static float g_prev = 0.0f;
static int g_zstate = 0;

static int xrun(void *arg)
{
    (void)arg;
    g_xruns++;
    return 0;
}

static int process(jack_nframes_t n, void *arg)
{
    void *buf = jack_port_get_buffer(g_midi, n);
    const float *s[2] = {jack_port_get_buffer(g_in[0], n), jack_port_get_buffer(g_in[1], n)};
    jack_nframes_t t0 = g_now;

    (void)arg;
    jack_midi_clear_buffer(buf);
    if (!g_go)
        return 0;
    while (g_next_ev < g_nev && g_ev[g_next_ev].at < t0 + n)
    {
        struct event *e = &g_ev[g_next_ev++];
        jack_nframes_t off = e->at > t0 ? e->at - t0 : 0;
        unsigned char *p = jack_midi_event_reserve(buf, off, e->len);

        if (p)
            memcpy(p, e->b, e->len);
    }
    for (int w = 0; w < g_nwin; w++)
    {
        struct window *W = &g_win[w];

        if (W->to <= t0 || W->from >= t0 + n)
            continue;
        for (jack_nframes_t i = 0; i < n; i++)
        {
            jack_nframes_t t = t0 + i;

            if (t < W->from || t >= W->to)
                continue;
            for (int c = 0; c < 2; c++)
            {
                float a = fabsf(s[c][i]);

                if (a > W->peak)
                    W->peak = a;
                W->sumsq += (double)s[c][i] * s[c][i];
            }
            W->sumdiff += (double)(s[0][i] - g_prev) * (s[0][i] - g_prev);
            if (g_zstate <= 0 && s[0][i] > 1e-3f)
            {
                if (g_zstate < 0)
                    W->zc++;
                g_zstate = 1;
            }
            else if (g_zstate >= 0 && s[0][i] < -1e-3f)
                g_zstate = -1;
            W->frames++;
            g_prev = s[0][i];
        }
    }
    g_now = t0 + n;
    return 0;
}

static double db(double v)
{
    return v > 0 ? 20 * log10(v) : -INFINITY;
}

int main(int argc, char **argv)
{
    const char *name = argc > 2 ? argv[2] : "inst_probe";
    FILE *f = argc > 1 ? fopen(argv[1], "r") : NULL;
    jack_client_t *c;
    jack_nframes_t sr, at = 0;
    char line[256];
    int open = -1;

    if (!f)
    {
        fprintf(stderr, "usage: jack-instrument-probe <scenario> [client name]\n");
        return 2;
    }
    c = jack_client_open(name, JackNoStartServer | JackUseExactName, NULL);
    if (!c)
    {
        fprintf(stderr, "no JACK server\n");
        return 1;
    }
    sr = jack_get_sample_rate(c);
    while (fgets(line, sizeof line, f))
    {
        char word[32], label[64];
        double ms;
        unsigned b[3];
        int k;

        if (sscanf(line, "%31s", word) != 1 || word[0] == '#')
            continue;
        if (!strcmp(word, "wait") && sscanf(line, "%*s %lf", &ms) == 1)
            at += (jack_nframes_t)(ms * sr / 1000.0);
        else if (!strcmp(word, "midi") && (k = sscanf(line, "%*s %x %x %x", &b[0], &b[1], &b[2])) >= 2 &&
                 g_nev < MAX_EVENTS)
        {
            g_ev[g_nev].at = at;
            g_ev[g_nev].len = k;
            for (int i = 0; i < k; i++)
                g_ev[g_nev].b[i] = (unsigned char)b[i];
            g_nev++;
        }
        else if ((!strcmp(word, "mark") || !strcmp(word, "end")) && g_nwin < MAX_WINDOWS)
        {
            if (open >= 0)
                g_win[open].to = at;
            open = -1;
            if (!strcmp(word, "mark") && sscanf(line, "%*s %63s", label) == 1)
            {
                open = g_nwin++;
                snprintf(g_win[open].label, sizeof g_win[open].label, "%s", label);
                g_win[open].from = at;
                g_win[open].to = (jack_nframes_t)-1;
            }
        }
        else
        {
            fprintf(stderr, "scenario: cannot read: %s", line);
            return 2;
        }
    }
    if (open >= 0)
        g_win[open].to = at;
    fclose(f);
    g_midi = jack_port_register(c, "midi_out", JACK_DEFAULT_MIDI_TYPE, JackPortIsOutput, 0);
    g_in[0] = jack_port_register(c, "in_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    g_in[1] = jack_port_register(c, "in_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    jack_set_process_callback(c, process, NULL);
    jack_set_xrun_callback(c, xrun, NULL);
    if (jack_activate(c))
        return 1;
    printf("ready\n");
    fflush(stdout);
    while (fgets(line, sizeof line, stdin) && strncmp(line, "go", 2))
        ;
    g_go = 1;
    for (int w = 0, started = 0; w < g_nwin;)
    {
        jack_nframes_t now = g_now;

        if (!started && now >= g_win[w].from)
        {
            g_win[w].xrun_from = g_xruns;
            printf("mark %s\n", g_win[w].label);
            fflush(stdout);
            started = 1;
        }
        if (started && now >= g_win[w].to)
        {
            struct window *W = &g_win[w];
            double secs = W->frames / (double)sr;
            double rms0 = W->frames ? sqrt(W->sumsq / (2.0 * W->frames)) : 0;

            W->xrun_to = g_xruns;
            printf("window %s peak %.1f rms %.1f hz %.1f bright %.4f frames %lu xruns %d\n", W->label, db(W->peak),
                   db(rms0), secs > 0 ? W->zc / secs : 0, rms0 > 0 ? sqrt(W->sumdiff / W->frames) / rms0 : 0,
                   W->frames, W->xrun_to - W->xrun_from);
            fflush(stdout);
            w++;
            started = 0;
            continue;
        }
        usleep(2000);
    }
    while (g_now < at)
        usleep(2000);
    printf("done\n");
    jack_client_close(c);
    return 0;
}

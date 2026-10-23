/* SPDX-License-Identifier: GPL-3.0-or-later */
/* A fake libjack.so.0 that tests/own_host_lv2_probe_test.py puts ahead of the real one on LD_LIBRARY_PATH: it runs
 * the registered process callback on a thread of its own, the way JACK's realtime thread does, and raises SIGSEGV
 * from the library's destructor -- run as the process tears down -- if that thread is still going. jack_deactivate
 * joins the thread first and marks it quiet; a probe that never calls it (#110) hits the signal every time. */
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

typedef int (*phd_jack_process_t)(uint32_t, void *);

static int g_handle;
static volatile int g_active;
static volatile int g_quiet;
static pthread_t g_thread;
static phd_jack_process_t g_cb;
static void *g_arg;
static float g_port_buf[4][8192];
static int g_nports;

static void *audio_thread(void *unused)
{
    (void)unused;
    while (g_active)
    {
        if (g_cb)
            g_cb(256, g_arg);
        usleep(200);
    }
    return NULL;
}

__attribute__((visibility("default"))) void *jack_client_open(const char *name, int options, void *status)
{
    (void)name; (void)options; (void)status;
    return &g_handle;
}

__attribute__((visibility("default"))) void *jack_port_register(void *client, const char *name, const char *type,
                                                                  unsigned long flags, unsigned long bufsize)
{
    (void)client; (void)name; (void)type; (void)flags; (void)bufsize;
    return &g_port_buf[g_nports++ % 4];
}

__attribute__((visibility("default"))) void *jack_port_get_buffer(void *port, uint32_t nframes)
{
    (void)nframes;
    return port;
}

__attribute__((visibility("default"))) int jack_set_process_callback(void *client, phd_jack_process_t cb, void *arg)
{
    (void)client;
    g_cb = cb;
    g_arg = arg;
    return 0;
}

__attribute__((visibility("default"))) int jack_get_sample_rate(void *client)
{
    (void)client;
    return 48000;
}

__attribute__((visibility("default"))) int jack_activate(void *client)
{
    (void)client;
    g_active = 1;
    pthread_create(&g_thread, NULL, audio_thread, NULL);
    return 0;
}

__attribute__((visibility("default"))) int jack_connect(void *client, const char *a, const char *b)
{
    (void)client; (void)a; (void)b;
    return 1;
}

__attribute__((visibility("default"))) int jack_deactivate(void *client)
{
    (void)client;
    if (g_active)
    {
        g_active = 0;
        pthread_join(g_thread, NULL);
    }
    g_quiet = 1;
    return 0;
}

__attribute__((visibility("default"))) int jack_client_close(void *client)
{
    (void)client;
    return 0;
}

__attribute__((destructor)) static void teardown_signal(void)
{
    if (g_active && !g_quiet)
        raise(SIGSEGV);
}

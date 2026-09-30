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

#include <getopt.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <socket.h>

#include "conf.h"
#include "relay.h"
#include "supervisor.h"
#include "verbs.h"

#ifndef VERSION
#define VERSION "0.1.1"
#endif

#define SOCKET_DEFAULT_PORT     PHD_DEFAULT_COMMAND_PORT
#define SOCKET_MSG_BUFFER_SIZE  PHD_LINE_MAX

static volatile int running;
static conf_t g_conf;

static void idle_cb(void)
{
    sup_tick();
    if (g_quitting)
    {
        running = 0;
        socket_finish();
    }
}

/* the first command of a controller waits for it to open the feedback port too, as mod-host's does */
static void receive(msg_t *msg)
{
    relay_await_controller(&running);
    verbs_receive(msg);
}

static void term_signal(int sig)
{
    (void)sig;
    running = 0;
    socket_finish();
}

int main(int argc, char **argv)
{
    static const struct option long_options[] = {
        {"socket-port", required_argument, 0, 'p'},
        {"feedback-port", required_argument, 0, 'f'},
        {"config", required_argument, 0, 'c'},
        {"nofork", no_argument, 0, 'n'},
        {"version", no_argument, 0, 'V'},
        {"help", no_argument, 0, 'h'},
        {0, 0, 0, 0}
    };
    int opt, opt_index = 0, socket_port = SOCKET_DEFAULT_PORT, feedback_port = 0, nofork = 0;
    const char *config = getenv("PLUGIN_HOSTD_CONF");
    char default_config[4096];
    struct sigaction sig;

    conf_defaults(&g_conf);
    while ((opt = getopt_long(argc, argv, "np:f:c:Vh", long_options, &opt_index)) != -1)
    {
        switch (opt)
        {
            case 'n':
                nofork = 1;
                break;
            case 'p':
                socket_port = atoi(optarg);
                break;
            case 'f':
                feedback_port = atoi(optarg);
                break;
            case 'c':
                config = optarg;
                break;
            case 'V':
                printf("%s version: %s\n", argv[0], VERSION);
                return EXIT_SUCCESS;
            case 'h':
            default:
                printf("Usage: %s [-n] [-p <port>] [-f <port>] [-c <file>]\n"
                       "  -p, --socket-port=<port>       command port (default %d)\n"
                       "  -f, --feedback-port=<port>     feedback port (default port+1 unless -n)\n"
                       "  -c, --config=<file>            settings, one \"key value\" per line\n"
                       "  -n, --nofork                   accepted; the daemon never forks\n"
                       "  -V, --version                  print program version and exit\n"
                       "  -h, --help                     print this help and exit\n",
                       argv[0], SOCKET_DEFAULT_PORT);
                return opt == 'h' ? EXIT_SUCCESS : EXIT_FAILURE;
        }
    }
    if (!feedback_port && !nofork)
        feedback_port = socket_port + 1;

    if (config)
    {
        if (conf_load(&g_conf, config, 1) != 0)
            return EXIT_FAILURE;
    }
    else
    {
        const char *home = getenv("XDG_CONFIG_HOME"), *user = getenv("HOME");

        if (home && *home)
            snprintf(default_config, sizeof(default_config), "%s/plugin-hostd.conf", home);
        else
            snprintf(default_config, sizeof(default_config), "%s/.config/plugin-hostd.conf", user ? user : "");
        if (conf_load(&g_conf, default_config, 0) != 0)
            return EXIT_FAILURE;
    }

    signal(SIGPIPE, SIG_IGN);
    sup_init(&g_conf);
    /* the feedback port is the relay's: the daemon's events and the workers' lines go out on it through one writer */
    if (socket_start(socket_port, 0, SOCKET_MSG_BUFFER_SIZE) < 0 || relay_start(feedback_port) < 0)
        return EXIT_FAILURE;
    socket_set_receive_cb(receive);
    socket_set_idle_cb(idle_cb);
    socket_set_idle_interval(g_conf.idle_ms);

    memset(&sig, 0, sizeof(sig));
    sig.sa_handler = term_signal;
    sig.sa_flags = SA_RESTART;
    sigemptyset(&sig.sa_mask);
    sigaction(SIGTERM, &sig, NULL);
    sigaction(SIGINT, &sig, NULL);

    printf("%s\n", PHD_READY_LINE);
    fflush(stdout);

    running = 1;
    while (running)
    {
        socket_run(0);
        relay_controller_gone();
    }

    socket_finish();
    sup_finish();
    relay_finish();
    return 0;
}

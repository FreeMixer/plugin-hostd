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

#ifndef PROC_H
#define PROC_H

#include <sys/types.h>

#include "conf.h"

#define RPC_OK          0
#define RPC_DIED        (-1)    /* the worker went away while the command was on the wire */
#define RPC_WAS_DEAD    (-2)    /* it had already gone before the command was sent */

typedef struct WORKER_ENV_T {
    char cpus[128];             /* cpu list, "" leaves the mask alone */
    int nice;                   /* INT_MIN leaves it alone */
    int thread_pool;            /* 1 starts the worker with --thread-pool=on; 0 passes no option, the worker's `qualified` */
} worker_env_t;

void proc_env_clear(worker_env_t *env);

/* Start `bin` as "<bin> -n -p <port> -f <fb_port>" (PHD_WORKER_ARGUMENTS), with env->thread_pool PHD_WORKER_THREAD_POOL_ON after
 * them, on two free ports, its stdout and stderr
 * in `logfile`. `world` is set in the worker's environment as `world_env`, when neither is NULL. */
int proc_spawn(const conf_t *conf, const char *bin, const char *world_env, const char *world, const worker_env_t *env,
               const char *logfile, pid_t *pid, int *port, int *fb_port);

/* Wait for the worker's socket to accept and its "ready!" line, then open its feedback port; returns the command
 * socket, and the feedback socket in *fb_fd; -1 when it never became ready, PROC_EXITED when the process was gone
 * before it was (it could not bind its ports: they are picked free, then released, and another process can take
 * one in between, so a caller may spawn again on fresh ports). */
#define PROC_EXITED (-2)
int proc_connect(const conf_t *conf, pid_t pid, int port, int fb_port, const char *logfile, int *fb_fd);

/* One command, one reply. On RPC_OK *reply is a malloc'd string. A worker that does not answer within the
 * timeout is killed, and counts as having died with the command on the wire. */
int proc_rpc(const conf_t *conf, pid_t pid, int fd, const char *msg, char **reply);

/* Has `pid` exited, without reaping it: the status stays for proc_exited. */
int proc_dead(pid_t pid);

/* Reap `pid` if it has exited; returns 1 and its wait status when it has. */
int proc_exited(pid_t pid, int *status);

/* SIGTERM, then SIGKILL after a grace period; the process is reaped. */
void proc_stop(pid_t pid);

void proc_apply_env(pid_t pid, const worker_env_t *env);

/* Logs on stderr a nice of `env` that the worker `pid` does not have: setpriority is refused to a process without
 * privilege that lowers a nice below its own. */
void proc_env_report(pid_t pid, const worker_env_t *env);

/* The directory of LV2_PATH holding the bundle whose manifest names `uri`; malloc'd, NULL if none. */
char *proc_find_lv2_bundle(const char *lv2_path, const char *uri);

/* Is `bin` executable, by path or on PATH. */
int proc_have_binary(const char *bin);

int64_t proc_now_ms(void);

/* What the kernel says of a worker: the CPU time it has used and its memory, for the running history. The first two
 * read the text of /proc/<pid>/stat and /proc/<pid>/smaps_rollup. 0, or -1 when the text is not what the kernel writes. */

/* utime and stime of a stat line, in clock ticks: the fields after the last ')', since the command name before it may
 * hold spaces and parentheses */
int proc_parse_stat(const char *text, long long *utime, long long *stime);
/* the Pss line of smaps_rollup, in kB */
int proc_parse_pss(const char *text, long long *kb);
/* seconds of CPU (utime + stime) the process has used, and its Pss in kB; -1 when the process or the file is gone */
int proc_cpu_seconds(pid_t pid, double *seconds);
int proc_pss_kb(pid_t pid, long long *kb);

#endif

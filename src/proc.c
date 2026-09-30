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

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "proc.h"

#define MANIFEST_MAX (4 * 1024 * 1024)

int64_t proc_now_ms(void)
{
    struct timespec t;

    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

void proc_env_clear(worker_env_t *env)
{
    memset(env, 0, sizeof(*env));
    env->nice = INT_MIN;
}

static int parse_cpus(const char *list, cpu_set_t *set)
{
    char copy[128], *tok, *save = NULL;

    CPU_ZERO(set);
    snprintf(copy, sizeof(copy), "%s", list);
    for (tok = strtok_r(copy, ",", &save); tok; tok = strtok_r(NULL, ",", &save))
    {
        int a, b;
        char *dash = strchr(tok, '-');

        a = atoi(tok);
        b = dash ? atoi(dash + 1) : a;
        if (a < 0 || b < a || b >= CPU_SETSIZE)
            return -1;
        while (a <= b)
            CPU_SET(a++, set);
    }
    return 0;
}

static void apply_thread(pid_t tid, const worker_env_t *env)
{
    cpu_set_t set;

    if (env->cpus[0] && parse_cpus(env->cpus, &set) == 0)
        sched_setaffinity(tid, sizeof(set), &set);
    if (env->nice != INT_MIN)
        setpriority(PRIO_PROCESS, tid, env->nice);
}

void proc_apply_env(pid_t pid, const worker_env_t *env)
{
    char path[64];
    DIR *dir;
    struct dirent *entry;

    snprintf(path, sizeof(path), "/proc/%d/task", (int)pid);
    dir = opendir(path);
    if (!dir)
    {
        apply_thread(pid, env);
        return;
    }
    while ((entry = readdir(dir)))
        if (entry->d_name[0] >= '0' && entry->d_name[0] <= '9')
            apply_thread((pid_t)atoi(entry->d_name), env);
    closedir(dir);
}

int proc_have_binary(const char *bin)
{
    char *path, *copy, *dir, *save = NULL;
    char full[PATH_MAX];
    int found = 0;

    if (strchr(bin, '/'))
        return access(bin, X_OK) == 0;
    path = getenv("PATH");
    if (!path)
        return 0;
    copy = strdup(path);
    for (dir = strtok_r(copy, ":", &save); dir && !found; dir = strtok_r(NULL, ":", &save))
    {
        snprintf(full, sizeof(full), "%s/%s", dir, bin);
        found = access(full, X_OK) == 0;
    }
    free(copy);
    return found;
}

static int free_port(void)
{
    struct sockaddr_in addr;
    socklen_t len = sizeof(addr);
    int fd = socket(AF_INET, SOCK_STREAM, 0), port = -1;

    if (fd < 0)
        return -1;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0 && getsockname(fd, (struct sockaddr *)&addr, &len) == 0)
        port = ntohs(addr.sin_port);
    close(fd);
    return port;
}

int proc_spawn(const conf_t *conf, const char *bin, const char *lv2_path, const worker_env_t *env,
               const char *logfile, pid_t *pid, int *port)
{
    char port_arg[16];
    pid_t child;
    int log;

    (void)conf;
    *port = free_port();
    if (*port < 0)
        return -1;
    snprintf(port_arg, sizeof(port_arg), "%d", *port);
    log = open(logfile, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (log < 0)
        return -1;
    child = fork();
    if (child < 0)
    {
        close(log);
        return -1;
    }
    if (child == 0)
    {
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (getppid() == 1)
            _exit(127);
        dup2(log, STDOUT_FILENO);
        dup2(log, STDERR_FILENO);
        if (log > STDERR_FILENO)
            close(log);
        signal(SIGPIPE, SIG_DFL);
        if (lv2_path)
            setenv("LV2_PATH", lv2_path, 1);
        if (env)
            apply_thread(0, env);
        execlp(bin, bin, "-n", "-p", port_arg, (char *)NULL);
        _exit(127);
    }
    close(log);
    *pid = child;
    return 0;
}

static int log_has_ready(const char *logfile)
{
    char buffer[4096];
    ssize_t n;
    int fd = open(logfile, O_RDONLY);

    if (fd < 0)
        return 0;
    n = read(fd, buffer, sizeof(buffer) - 1);
    close(fd);
    if (n <= 0)
        return 0;
    buffer[n] = '\0';
    return strstr(buffer, "ready!") != NULL;
}

int proc_connect(const conf_t *conf, pid_t pid, int port, const char *logfile)
{
    int64_t start = proc_now_ms();
    int fd = -1, status;

    while (proc_now_ms() - start < conf->ready_timeout_ms)
    {
        struct sockaddr_in addr;

        if (proc_exited(pid, &status))
            return -1;
        if (fd < 0)
        {
            fd = socket(AF_INET, SOCK_STREAM, 0);
            memset(&addr, 0, sizeof(addr));
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0)
            {
                close(fd);
                fd = -1;
            }
        }
        if (fd >= 0 && log_has_ready(logfile))
            return fd;
        usleep(2000);
    }
    if (fd >= 0)
        close(fd);
    return -1;
}

int proc_dead(pid_t pid)
{
    siginfo_t info;

    if (pid <= 0)
        return 1;
    memset(&info, 0, sizeof(info));
    if (waitid(P_PID, pid, &info, WEXITED | WNOHANG | WNOWAIT) < 0)
        return errno == ECHILD;
    return info.si_pid == pid;
}

int proc_exited(pid_t pid, int *status)
{
    pid_t r;

    if (pid <= 0)
        return 1;
    r = waitpid(pid, status, WNOHANG);
    return r == pid || (r < 0 && errno == ECHILD);
}

void proc_stop(pid_t pid)
{
    int status, i;

    if (pid <= 0)
        return;
    kill(pid, SIGTERM);
    for (i = 0; i < 200; i++)
    {
        if (proc_exited(pid, &status))
            return;
        usleep(10000);
    }
    kill(pid, SIGKILL);
    waitpid(pid, &status, 0);
}

int proc_rpc(const conf_t *conf, pid_t pid, int fd, const char *msg, char **reply)
{
    size_t len = strlen(msg) + 1, used = 0, cap = 256;
    char *buffer;
    int64_t start;

    if (proc_dead(pid))
        return RPC_WAS_DEAD;
    if (send(fd, msg, len, MSG_NOSIGNAL) != (ssize_t)len)
        return RPC_DIED;
    buffer = malloc(cap);
    start = proc_now_ms();
    for (;;)
    {
        struct pollfd pfd = { fd, POLLIN, 0 };
        int left = conf->rpc_timeout_ms - (int)(proc_now_ms() - start);
        ssize_t n;

        if (left <= 0 || poll(&pfd, 1, left) <= 0)
        {
            free(buffer);
            kill(pid, SIGKILL);
            return RPC_DIED;
        }
        if (used + 1024 > cap)
            buffer = realloc(buffer, cap *= 2);
        n = recv(fd, buffer + used, cap - used, 0);
        if (n <= 0)
        {
            free(buffer);
            return RPC_DIED;
        }
        used += n;
        if (memchr(buffer, '\0', used))
            break;
    }
    *reply = buffer;
    return RPC_OK;
}

static int manifest_names(const char *bundle, const char *uri)
{
    char path[PATH_MAX], *text, needle[2048];
    FILE *file;
    long size;
    size_t got;
    int found;

    snprintf(path, sizeof(path), "%s/manifest.ttl", bundle);
    file = fopen(path, "rb");
    if (!file)
        return 0;
    fseek(file, 0, SEEK_END);
    size = ftell(file);
    if (size <= 0 || size > MANIFEST_MAX)
    {
        fclose(file);
        return 0;
    }
    rewind(file);
    text = malloc(size + 1);
    got = fread(text, 1, size, file);
    fclose(file);
    text[got] = '\0';
    snprintf(needle, sizeof(needle), "<%s>", uri);
    found = strstr(text, needle) != NULL;
    free(text);
    return found;
}

char *proc_find_lv2_bundle(const char *lv2_path, const char *uri)
{
    char *copy = strdup(lv2_path), *dir, *save = NULL, *result = NULL;

    for (dir = strtok_r(copy, ":", &save); dir && !result; dir = strtok_r(NULL, ":", &save))
    {
        DIR *d = opendir(dir);
        struct dirent *entry;

        if (!d)
            continue;
        while (!result && (entry = readdir(d)))
        {
            size_t n = strlen(entry->d_name);
            char bundle[PATH_MAX];

            if (n < 5 || strcmp(entry->d_name + n - 4, ".lv2") != 0)
                continue;
            snprintf(bundle, sizeof(bundle), "%s/%s", dir, entry->d_name);
            if (manifest_names(bundle, uri))
                result = strdup(bundle);
        }
        closedir(d);
    }
    free(copy);
    return result;
}

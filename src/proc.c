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
#include <linux/sockios.h>
#include <sys/ioctl.h>
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

void proc_env_report(pid_t pid, const worker_env_t *env)
{
    int have;

    if (env->nice == INT_MIN)
        return;
    errno = 0;
    have = getpriority(PRIO_PROCESS, pid);
    if (errno == 0 && have != env->nice)
        fprintf(stderr, "worker_env: worker %d keeps nice %d, the nice %d was not applied (a daemon without privilege cannot lower "
                "a worker's nice below its own)\n", (int)pid, have, env->nice);
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
    if (!copy)
        return 0;
    for (dir = strtok_r(copy, ":", &save); dir && !found; dir = strtok_r(NULL, ":", &save))
    {
        snprintf(full, sizeof(full), "%s/%s", dir, bin);
        found = access(full, X_OK) == 0;
    }
    free(copy);
    return found;
}

static int free_port(int other)
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
    /* the kernel may hand the same ephemeral port out twice in a row */
    return port == other ? free_port(other) : port;
}

int proc_spawn(const conf_t *conf, const char *bin, const char *world_env, const char *world, const worker_env_t *env,
               const char *logfile, pid_t *pid, int *port, int *fb_port)
{
    char port_arg[16], fb_arg[16];
    pid_t child;
    int log;

    (void)conf;
    *port = free_port(-1);
    *fb_port = *port < 0 ? -1 : free_port(*port);
    if (*port < 0 || *fb_port < 0)
        return -1;
    snprintf(port_arg, sizeof(port_arg), "%d", *port);
    snprintf(fb_arg, sizeof(fb_arg), "%d", *fb_port);
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
        if (world_env && world)
            setenv(world_env, world, 1);
        if (env)
            apply_thread(0, env);
        if (env && env->thread_pool)
            execlp(bin, bin, "-n", "-p", port_arg, "-f", fb_arg, PHD_WORKER_THREAD_POOL_ON, (char *)NULL);
        else
            execlp(bin, bin, "-n", "-p", port_arg, "-f", fb_arg, (char *)NULL);
        _exit(127);
    }
    close(log);
    *pid = child;
    return 0;
}

/* whether the worker's log carries the ready marker yet: the whole log, a page at a time, the tail of each page kept in
 * front of the next so that a marker split across two reads is still found. A worker says ready after it has set up
 * its world, and what it says about the world comes first: mod-host's lilv writes a warning line for every entry of
 * LV2_PATH that is no bundle, so a world of a few dozen stray files puts the marker past the first page (#105) */
static int log_has_ready(const char *logfile)
{
    char buffer[4096];
    size_t keep = strlen(PHD_WORKER_READY_MARKER) - 1, held = 0;
    ssize_t n;
    int fd = open(logfile, O_RDONLY), found = 0;

    if (fd < 0)
        return 0;
    while (!found && (n = read(fd, buffer + held, sizeof(buffer) - 1 - held)) > 0)
    {
        held += n;
        buffer[held] = '\0';
        /* a NUL inside the page would stop strstr short of the rest of it */
        for (size_t i = 0; i < held; i++)
            if (buffer[i] == '\0')
                buffer[i] = ' ';
        found = strstr(buffer, PHD_WORKER_READY_MARKER) != NULL;
        if (held > keep)
        {
            memmove(buffer, buffer + held - keep, keep);
            held = keep;
        }
    }
    close(fd);
    return found;
}

static int connect_loopback(int port)
{
    struct sockaddr_in addr;
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);

    if (fd < 0)
        return -1;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0)
    {
        close(fd);
        return -1;
    }
    return fd;
}

int proc_connect(const conf_t *conf, pid_t pid, int port, int fb_port, const char *logfile, int *fb_fd)
{
    int64_t start = proc_now_ms();
    int fd = -1, status, exited = 0;

    *fb_fd = -1;

    while (proc_now_ms() - start < conf->ready_timeout_ms)
    {
        if (proc_exited(pid, &status))
        {
            exited = 1;
            break;
        }
        if (fd < 0)
            fd = connect_loopback(port);
        /* the worker takes the command connection first, then the feedback one: both listen before "ready!" */
        if (fd >= 0 && log_has_ready(logfile))
        {
            *fb_fd = connect_loopback(fb_port);
            if (*fb_fd >= 0)
                return fd;
        }
        usleep(2000);
    }
    if (fd >= 0)
        close(fd);
    return exited ? PROC_EXITED : -1;
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

/* one thread as the kernel sees it: its id, its state letter, what it waits in (wchan), and the top of its kernel stack
 * when the daemon may read it (root, or ptrace rights) */
static size_t say_thread(char *out, size_t size, const char *task, const char *tid)
{
    char path[PATH_MAX], stat[512], wchan[64] = "-", frame[96] = "", state = '?';
    FILE *f;
    char *close;

    snprintf(path, sizeof(path), "%s/%s/stat", task, tid);
    if ((f = fopen(path, "r")) != NULL)
    {
        if (fgets(stat, sizeof(stat), f) && (close = strrchr(stat, ')')) != NULL && close[1] == ' ')
            state = close[2];
        fclose(f);
    }
    snprintf(path, sizeof(path), "%s/%s/wchan", task, tid);
    if ((f = fopen(path, "r")) != NULL)
    {
        if (!fgets(wchan, sizeof(wchan), f) || !*wchan || !strcmp(wchan, "0"))
            snprintf(wchan, sizeof(wchan), "-");
        fclose(f);
    }
    snprintf(path, sizeof(path), "%s/%s/stack", task, tid);
    if ((f = fopen(path, "r")) != NULL)
    {
        char line[160], *sym;

        if (fgets(line, sizeof(line), f) && (sym = strchr(line, ' ')) != NULL)
        {
            sym[strcspn(sym, "\n")] = '\0';
            snprintf(frame, sizeof(frame), " (%s)", sym + 1);
        }
        fclose(f);
    }
    return (size_t)snprintf(out, size, " %s %c %s%s,", tid, state, wchan, frame);
}

/* the threads of a task directory, each as say_thread has it, into out */
static void say_threads(char *out, size_t size, const char *task)
{
    DIR *dir = opendir(task);
    struct dirent *e;
    size_t used = 0;

    out[0] = '\0';
    if (!dir)
        return;
    while ((e = readdir(dir)) && used + 1 < size)
        if (e->d_name[0] >= '0' && e->d_name[0] <= '9')
        {
            size_t n = say_thread(out + used, size - used, task, e->d_name);

            used = n < size - used ? used + n : size - 1;
        }
    closedir(dir);
    if (used && out[used - 1] == ',')
        out[used - 1] = '\0';
}

/* a worker that did not answer in rpc_timeout_ms is said before it is killed: the command, how long it waited, how much
 * of the command it had not read, where each of its threads was, and the daemon's own threads, so a slow machine and a
 * worker stuck behind something each say which */
static void say_unanswered(pid_t pid, int fd, const char *msg, int64_t waited)
{
    char task[64], worker[1024], daemon[512];
    int unread = -1;

    snprintf(task, sizeof(task), "/proc/%d/task", (int)pid);
    say_threads(worker, sizeof(worker), task);
    say_threads(daemon, sizeof(daemon), "/proc/self/task");
    if (ioctl(fd, SIOCOUTQ, &unread) != 0)
        unread = -1;
    fprintf(stderr, "plugin-hostd: worker %d did not answer '%.80s' in %lld ms, %d bytes of it unread; killed. its threads:%s; "
                    "the daemon's:%s\n", (int)pid, msg, (long long)waited, unread, worker, daemon);
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
    if (buffer == NULL)
    {
        kill(pid, SIGKILL);
        return RPC_DIED;
    }
    start = proc_now_ms();
    for (;;)
    {
        struct pollfd pfd = { fd, POLLIN, 0 };
        int left = conf->rpc_timeout_ms - (int)(proc_now_ms() - start);
        ssize_t n;

        if (left <= 0 || poll(&pfd, 1, left) <= 0)
        {
            free(buffer);
            say_unanswered(pid, fd, msg, proc_now_ms() - start);
            kill(pid, SIGKILL);
            return RPC_DIED;
        }
        if (used + 1024 > cap)
        {
            char *bigger = realloc(buffer, cap * 2);

            if (bigger == NULL)
            {
                /* no memory for the rest of the reply: the worker cannot be followed any more, as on a timeout */
                free(buffer);
                kill(pid, SIGKILL);
                return RPC_DIED;
            }
            buffer = bigger;
            cap *= 2;
        }
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

/* a name character of a Turtle prefixed name: the byte after or before one is no boundary */
static int name_char(int c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c == '-' || c == '.' ||
           c == ':' || (c & 0x80);
}

/* whether the manifest names the plugin as a prefixed name: `@prefix mda: <http://example.org/mda/> .` with the uri
 * http://example.org/mda/Piano is written mda:Piano (mda-lv2's bundles do so, and so do most LV2 manifests) */
static int manifest_prefixed(const char *text, const char *uri)
{
    const char *p = text;

    while ((p = strstr(p, "prefix")) != NULL)
    {
        const char *name, *colon, *open, *close;
        char prefix[128], full[2048];
        size_t n, ns_len, uri_len = strlen(uri);
        const char *at;

        p += 6;
        name = p;
        while (*name == ' ' || *name == '\t')
            name++;
        colon = name;
        while (*colon && *colon != ':' && *colon != ' ' && *colon != '\t' && *colon != '\n' && *colon != '<')
            colon++;
        if (*colon != ':' || (size_t)(colon - name) >= sizeof(prefix))
            continue;
        snprintf(prefix, sizeof(prefix), "%.*s", (int)(colon - name), name);
        open = colon + 1;
        while (*open == ' ' || *open == '\t')
            open++;
        if (*open != '<' || !(close = strchr(open, '>')))
            continue;
        ns_len = (size_t)(close - open - 1);
        if (ns_len == 0 || ns_len >= uri_len || strncmp(open + 1, uri, ns_len) != 0 || strchr(uri + ns_len, '/') ||
            strchr(uri + ns_len, '#'))
            continue;
        n = (size_t)snprintf(full, sizeof(full), "%s:%s", prefix, uri + ns_len);
        if (n >= sizeof(full))
            continue;
        for (at = text; (at = strstr(at, full)) != NULL; at += n)
            if ((at == text || !name_char((unsigned char)at[-1])) && !(name_char((unsigned char)at[n]) && !(at[n] == '.' && !name_char((unsigned char)at[n + 1]))))
                return 1;
    }
    return 0;
}

/* MANIFEST_NAMES when the bundle's manifest names the plugin, and MANIFEST_REALISES when it also holds a binary: a bundle
 * that only adds to a plugin, such as a generated MOD GUI, names it too and cannot run it */
enum { MANIFEST_NOT, MANIFEST_NAMES, MANIFEST_REALISES };

unsigned long proc_manifest_reads;

static int manifest_names(const char *bundle, const char *uri)
{
    char path[PATH_MAX], *text, needle[2048];
    FILE *file;
    long size;
    size_t got;
    int found;

    snprintf(path, sizeof(path), "%s/manifest.ttl", bundle);
    proc_manifest_reads++;
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
    if (!text)
    {
        fclose(file);
        return 0;
    }
    got = fread(text, 1, size, file);
    fclose(file);
    text[got] = '\0';
    snprintf(needle, sizeof(needle), "<%s>", uri);
    found = MANIFEST_NOT;
    if (strstr(text, needle) != NULL || manifest_prefixed(text, uri))
        found = strstr(text, "binary") != NULL ? MANIFEST_REALISES : MANIFEST_NAMES;
    free(text);
    return found;
}

/* the bundles found holding a plugin's binary, by search path and uri: a repeat lookup reads that one manifest again
 * instead of walking the path. Only an answer that holds the binary is kept, and only while its manifest still holds it,
 * so a plugin installed, moved or removed while the daemon runs is found as a walk finds it. The daemon's lookups run
 * on its one control thread. */
#define BUNDLE_MEMO_MAX 4096
static struct bundle_memo
{
    char *path, *uri, *bundle;
} g_bundle_memo[BUNDLE_MEMO_MAX];
static int g_bundle_memos;

static struct bundle_memo *bundle_memo_find(const char *lv2_path, const char *uri)
{
    int k;

    for (k = 0; k < g_bundle_memos; k++)
        if (!strcmp(g_bundle_memo[k].uri, uri) && !strcmp(g_bundle_memo[k].path, lv2_path))
            return &g_bundle_memo[k];
    return NULL;
}

/* remembers a bundle that holds the plugin's binary; with no memory for it, nothing is remembered and the next lookup
 * walks the path */
static void bundle_memo_keep(const char *lv2_path, const char *uri, const char *bundle)
{
    struct bundle_memo *m = bundle_memo_find(lv2_path, uri);
    char *copy = strdup(bundle);

    if (!copy)
        return;
    if (m)
    {
        free(m->bundle);
        m->bundle = copy;
        return;
    }
    if (g_bundle_memos == BUNDLE_MEMO_MAX)
    {
        free(copy);
        return;
    }
    m = &g_bundle_memo[g_bundle_memos];
    m->path = strdup(lv2_path);
    m->uri = strdup(uri);
    if (!m->path || !m->uri)
    {
        free(m->path);
        free(m->uri);
        free(copy);
        return;
    }
    m->bundle = copy;
    g_bundle_memos++;
}

char *proc_find_lv2_bundle(const char *lv2_path, const char *uri)
{
    struct bundle_memo *m = bundle_memo_find(lv2_path, uri);
    char *copy, *dir, *save = NULL, *result = NULL, *named = NULL;

    if (m && manifest_names(m->bundle, uri) == MANIFEST_REALISES)
        return strdup(m->bundle);
    copy = strdup(lv2_path);
    if (!copy)
        return NULL;
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
            switch (manifest_names(bundle, uri))
            {
            case MANIFEST_REALISES:
                result = strdup(bundle);
                break;
            case MANIFEST_NAMES:
                /* a manifest may leave the binary to a file it links: the first that names the plugin, when none holds one */
                if (!named)
                    named = strdup(bundle);
                break;
            }
        }
        closedir(d);
    }
    free(copy);
    if (result)
    {
        free(named);
        bundle_memo_keep(lv2_path, uri, result);
        return result;
    }
    return named;
}

/* the data bundles of a plugin by search path and uri, as the last walk found them, with the time each directory of the
 * path was last changed then: a bundle added to or removed from a directory changes it, so while none has changed the
 * walk would find the same bundles, and no manifest is read. A memo that cannot be kept is no memo: the next call walks. */
#define PRESET_MEMO_MAX 1024
static struct preset_memo
{
    char *path, *uri;
    char **bundles;
    int n;
    struct timespec *dirs;      // each directory of the path, in order: its st_mtim, or tv_sec -1 when it is not there
    int ndirs;
} g_preset_memo[PRESET_MEMO_MAX];
static int g_preset_memos;

/* the change times of the directories of lv2_path into *out (malloc'd), their count, or -1 short of memory */
static int path_dir_times(const char *lv2_path, struct timespec **out)
{
    char *copy = strdup(lv2_path), *dir, *save = NULL;
    struct timespec *t = NULL, *grown;
    int n = 0;

    if (!copy)
        return -1;
    for (dir = strtok_r(copy, ":", &save); dir; dir = strtok_r(NULL, ":", &save))
    {
        struct stat st;

        if (!(grown = realloc(t, (n + 1) * sizeof(*t))))
        {
            free(t);
            free(copy);
            return -1;
        }
        t = grown;
        if (stat(dir, &st) == 0)
            t[n] = st.st_mtim;
        else
            t[n].tv_sec = -1, t[n].tv_nsec = 0;
        n++;
    }
    free(copy);
    *out = t;
    return n;
}

static void preset_memo_clear(struct preset_memo *m)
{
    int k;

    for (k = 0; k < m->n; k++)
        free(m->bundles[k]);
    free(m->bundles);
    free(m->dirs);
    m->bundles = NULL;
    m->dirs = NULL;
    m->n = m->ndirs = 0;
}

struct preset_walk
{
    char **bundles;
    int n, short_of_memory;
};

static int preset_walk_keep(void *ctx, const char *bundle)
{
    struct preset_walk *w = ctx;
    char **grown = realloc(w->bundles, (w->n + 1) * sizeof(char *));

    if (!grown || !(grown[w->n] = strdup(bundle)))
    {
        if (grown)
            w->bundles = grown;
        w->short_of_memory = 1;
        return 1;
    }
    w->bundles = grown;
    w->n++;
    return 0;
}

/* every bundle of LV2_PATH whose manifest names the plugin and holds no binary, by a walk of the path */
static int preset_bundles_walk(const char *lv2_path, const char *uri, int (*fn)(void *ctx, const char *bundle), void *ctx)
{
    char *copy = strdup(lv2_path), *dir, *save = NULL;
    int found = 0, stop = 0;

    if (!copy)
        return -1;
    for (dir = strtok_r(copy, ":", &save); dir && !stop; dir = strtok_r(NULL, ":", &save))
    {
        DIR *d = opendir(dir);
        struct dirent *entry;

        if (!d)
            continue;
        while (!stop && (entry = readdir(d)))
        {
            size_t n = strlen(entry->d_name);
            char bundle[PATH_MAX];

            if (n < 5 || strcmp(entry->d_name + n - 4, ".lv2") != 0)
                continue;
            snprintf(bundle, sizeof(bundle), "%s/%s", dir, entry->d_name);
            /* a manifest that names the plugin and holds no binary: presets, a MOD GUI, data for it; never code */
            if (manifest_names(bundle, uri) == MANIFEST_NAMES)
            {
                found++;
                stop = fn(ctx, bundle) != 0;
            }
        }
        closedir(d);
    }
    free(copy);
    return stop ? -1 : found;
}

int proc_lv2_preset_bundles(const char *lv2_path, const char *uri, int (*fn)(void *ctx, const char *bundle), void *ctx)
{
    struct preset_memo *m = NULL;
    struct preset_walk w = { NULL, 0, 0 };
    struct timespec *now = NULL;
    int ndirs = path_dir_times(lv2_path, &now), k, same;

    for (k = 0; k < g_preset_memos && !m; k++)
        if (!strcmp(g_preset_memo[k].uri, uri) && !strcmp(g_preset_memo[k].path, lv2_path))
            m = &g_preset_memo[k];
    same = m && m->dirs && ndirs == m->ndirs;
    for (k = 0; same && k < ndirs; k++)
        same = now[k].tv_sec == m->dirs[k].tv_sec && now[k].tv_nsec == m->dirs[k].tv_nsec;
    if (same)
    {
        free(now);
        for (k = 0; k < m->n; k++)
            if (fn(ctx, m->bundles[k]) != 0)
                return -1;
        return m->n;
    }
    if (preset_bundles_walk(lv2_path, uri, preset_walk_keep, &w) < 0 || w.short_of_memory)
    {
        for (k = 0; k < w.n; k++)
            free(w.bundles[k]);
        free(w.bundles);
        free(now);
        /* no memory for the list: the walk again, handing each bundle on as it is found */
        return preset_bundles_walk(lv2_path, uri, fn, ctx);
    }
    if (!m && g_preset_memos < PRESET_MEMO_MAX && ndirs >= 0)
    {
        m = &g_preset_memo[g_preset_memos];
        memset(m, 0, sizeof(*m));
        if ((m->path = strdup(lv2_path)) && (m->uri = strdup(uri)))
            g_preset_memos++;
        else
        {
            free(m->path);
            m = NULL;
        }
    }
    if (m)
    {
        preset_memo_clear(m);
        m->bundles = w.bundles;
        m->n = w.n;
        m->dirs = ndirs >= 0 ? now : NULL;
        m->ndirs = ndirs >= 0 ? ndirs : 0;
        now = NULL;
    }
    for (k = 0; k < w.n && fn(ctx, w.bundles[k]) == 0; k++)
        ;
    same = k < w.n ? -1 : w.n;
    if (!m)
    {
        for (k = 0; k < w.n; k++)
            free(w.bundles[k]);
        free(w.bundles);
    }
    free(now);
    return same;
}

int proc_parse_stat(const char *text, long long *utime, long long *stime)
{
    const char *p = strrchr(text, ')');
    char copy[1024], *save = NULL, *t, *end;
    int field = 3;

    if (!p || strlen(p + 1) >= sizeof(copy))
        return -1;
    snprintf(copy, sizeof(copy), "%s", p + 1);
    /* the words after the name: state is field 3, utime field 14, stime field 15 */
    for (t = strtok_r(copy, " \n", &save); t; t = strtok_r(NULL, " \n", &save), field++)
    {
        if (field != 14 && field != 15)
            continue;
        long long v = strtoll(t, &end, 10);

        if (end == t || *end || v < 0)
            return -1;
        if (field == 14)
            *utime = v;
        else
        {
            *stime = v;
            return 0;
        }
    }
    return -1;
}

int proc_parse_pss(const char *text, long long *kb)
{
    const char *p = text;

    /* "Pss:" at the start of a line: not Pss_Anon, Pss_File or Pss_Shmem */
    while (p && *p)
    {
        if (!strncmp(p, "Pss:", 4))
        {
            char *end;
            long long v = strtoll(p + 4, &end, 10);

            if (end == p + 4 || v < 0 || strncmp(end, " kB", 3))
                return -1;
            *kb = v;
            return 0;
        }
        p = strchr(p, '\n');
        if (p)
            p++;
    }
    return -1;
}

static int read_proc(pid_t pid, const char *name, char *buf, size_t size)
{
    char path[64];
    int fd, n;

    snprintf(path, sizeof(path), "/proc/%d/%s", (int)pid, name);
    if ((fd = open(path, O_RDONLY | O_CLOEXEC)) < 0)
        return -1;
    n = read(fd, buf, size - 1);
    close(fd);
    if (n <= 0)
        return -1;
    buf[n] = '\0';
    return 0;
}

int proc_cpu_seconds(pid_t pid, double *seconds)
{
    char text[1024];
    long long u = 0, s = 0;
    long hz = sysconf(_SC_CLK_TCK);

    if (hz <= 0 || read_proc(pid, "stat", text, sizeof(text)) != 0 || proc_parse_stat(text, &u, &s) != 0)
        return -1;
    *seconds = (double)(u + s) / (double)hz;
    return 0;
}

int proc_pss_kb(pid_t pid, long long *kb)
{
    char text[4096];

    return read_proc(pid, "smaps_rollup", text, sizeof(text)) == 0 ? proc_parse_pss(text, kb) : -1;
}

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

/* plugin-hostd-probe: runs a program that loads a plugin (today clap-qualify) under limits, and writes what happened as
 * the probe output (protocol/probe-output.schema.json): facts only, no verdict.
 *
 *   plugin-hostd-probe run [options] <plugin.clap> [<clap id>]
 *   plugin-hostd-probe run [options] lv2:<uri>          plugin-qualify's lv2_measure, its pin pass then its measurement
 *
 * The runner never loads plugin code. It starts the child in its own process group, with the portable limits below
 * applied before the exec, keeps the wall clock, and on the deadline, on a cancel or when the child is done kills the
 * whole tree: the runner is the child subreaper, so a process the plugin started and orphaned, in its own session or
 * not, comes back to it and is found and killed. A child that dies leaves every record it wrote.
 *
 * The child writes its facts on stdout (clap-qualify's one JSON line) and may write step records, one JSON object per
 * line, on file descriptor 3; its stderr goes to the log. Nothing a plugin prints can enter the document.
 *
 * Limits applied here, on every Linux: the wall clock with the tree kill, RLIMIT_CPU, RLIMIT_DATA, RLIMIT_NOFILE,
 * RLIMIT_FSIZE, RLIMIT_CORE 0, RLIMIT_RTPRIO 0, PR_SET_NO_NEW_PRIVS, PR_SET_PDEATHSIG and cpu affinity. A limit the
 * set asks for and this version does not apply (cgroup tasks, namespaces, Landlock, seccomp) is listed in the
 * document, never skipped in silence; --require turns it into a refusal.
 *
 * Exit: 0 a document, the run complete, every step ok or not attempted; 1 a document, some step ended otherwise;
 * 2 no document (usage, a required limit unavailable, the output not writable); 3 no such plugin. */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/random.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include <omxcontract/omx_contract_limits.h>
#include <omxcontract/omx_vocabulary.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#define RUNNER_NAME "plugin-hostd-probe"
#ifndef PROBE_VERSION
#define PROBE_VERSION "unknown"
#endif
#define LINE_MAX_BYTES (4 * 1024 * 1024)
#define MAX_STEPS 256
#define MAX_POINTS 64

/* ---------------------------------------------------------------- strings that grow */

typedef struct
{
    char *s;
    size_t len, cap;
} sb_t;

static void sb_put(sb_t *b, const char *data, size_t n)
{
    if (b->len + n + 1 > b->cap)
    {
        b->cap = (b->len + n + 1) * 2;
        b->s = realloc(b->s, b->cap);
        if (b->s == NULL)
        {
            fprintf(stderr, RUNNER_NAME ": out of memory\n");
            exit(2);
        }
    }
    memcpy(b->s + b->len, data, n);
    b->len += n;
    b->s[b->len] = '\0';
}

static void sb_printf(sb_t *b, const char *fmt, ...)
{
    char tmp[512];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n < sizeof(tmp))
    {
        sb_put(b, tmp, (size_t)n);
        return;
    }
    {
        char *big = malloc((size_t)n + 1);

        va_start(ap, fmt);
        vsnprintf(big, (size_t)n + 1, fmt, ap);
        va_end(ap);
        sb_put(b, big, (size_t)n);
        free(big);
    }
}

/* a JSON string: the bytes of a valid UTF-8 text as they are, a control character or a byte that is not UTF-8 escaped */
static void sb_str(sb_t *b, const char *s)
{
    const unsigned char *p = (const unsigned char *)s;

    sb_put(b, "\"", 1);
    for (; *p; p++)
    {
        if (*p == '"' || *p == '\\')
        {
            sb_put(b, "\\", 1);
            sb_put(b, (const char *)p, 1);
        }
        else if (*p < 0x20 || *p == 0x7f)
            sb_printf(b, "\\u%04x", *p);
        else if (*p < 0x80)
            sb_put(b, (const char *)p, 1);
        else
        {
            int n = *p >= 0xf0 ? 4 : *p >= 0xe0 ? 3 : *p >= 0xc0 ? 2 : 0, k, ok = n > 0;

            for (k = 1; ok && k < n; k++)
                ok = (p[k] & 0xc0) == 0x80;
            if (ok)
            {
                sb_put(b, (const char *)p, (size_t)n);
                p += n - 1;
            }
            else
                sb_printf(b, "\\u%04x", *p);
        }
    }
    sb_put(b, "\"", 1);
}

/* ---------------------------------------------------------------- a small JSON reader for the child's line */

typedef enum { J_NULL, J_BOOL, J_NUM, J_STR, J_ARR, J_OBJ } jtype_t;

typedef struct jnode
{
    jtype_t type;
    double num;
    int boolean;
    char *str;
    struct jnode **kid; /* array items, or object values */
    char **key;         /* object keys */
    size_t n;
} jnode_t;

static jnode_t *jparse_value(const char **p, int depth);

static void jskip(const char **p)
{
    while (**p == ' ' || **p == '\t' || **p == '\n' || **p == '\r')
        (*p)++;
}

static char *jparse_string(const char **p)
{
    sb_t b = { 0 };

    (*p)++;
    while (**p && **p != '"')
    {
        if (**p == '\\' && (*p)[1])
        {
            char c = (*p)[1];

            (*p) += 2;
            if (c == 'n')
                sb_put(&b, "\n", 1);
            else if (c == 't')
                sb_put(&b, "\t", 1);
            else if (c == 'u')
            {
                unsigned v = 0;
                int k;

                for (k = 0; k < 4 && isxdigit((unsigned char)**p); k++, (*p)++)
                    v = v * 16 + (unsigned)(isdigit((unsigned char)**p) ? **p - '0' : (tolower((unsigned char)**p) - 'a' + 10));
                if (v < 0x80)
                    sb_put(&b, (const char *)&(char){ (char)v }, 1);
                else
                    sb_put(&b, "?", 1);
            }
            else
                sb_put(&b, &c, 1);
        }
        else
        {
            sb_put(&b, *p, 1);
            (*p)++;
        }
    }
    if (**p != '"')
    {
        free(b.s);
        return NULL;
    }
    (*p)++;
    return b.s ? b.s : strdup("");
}

static jnode_t *jnew(jtype_t t)
{
    jnode_t *n = calloc(1, sizeof(*n));

    n->type = t;
    return n;
}

static jnode_t *jparse_value(const char **p, int depth)
{
    jnode_t *n;

    if (depth > 32)
        return NULL;
    jskip(p);
    if (**p == '{')
    {
        n = jnew(J_OBJ);
        (*p)++;
        jskip(p);
        if (**p == '}')
        {
            (*p)++;
            return n;
        }
        for (;;)
        {
            char *key;
            jnode_t *v;

            jskip(p);
            if (**p != '"' || (key = jparse_string(p)) == NULL)
                return NULL;
            jskip(p);
            if (*(*p)++ != ':' || (v = jparse_value(p, depth + 1)) == NULL)
                return NULL;
            n->kid = realloc(n->kid, (n->n + 1) * sizeof(*n->kid));
            n->key = realloc(n->key, (n->n + 1) * sizeof(*n->key));
            n->key[n->n] = key;
            n->kid[n->n++] = v;
            jskip(p);
            if (**p == ',')
            {
                (*p)++;
                continue;
            }
            if (**p == '}')
            {
                (*p)++;
                return n;
            }
            return NULL;
        }
    }
    if (**p == '[')
    {
        n = jnew(J_ARR);
        (*p)++;
        jskip(p);
        if (**p == ']')
        {
            (*p)++;
            return n;
        }
        for (;;)
        {
            jnode_t *v = jparse_value(p, depth + 1);

            if (v == NULL)
                return NULL;
            n->kid = realloc(n->kid, (n->n + 1) * sizeof(*n->kid));
            n->kid[n->n++] = v;
            jskip(p);
            if (**p == ',')
            {
                (*p)++;
                continue;
            }
            if (**p == ']')
            {
                (*p)++;
                return n;
            }
            return NULL;
        }
    }
    if (**p == '"')
    {
        n = jnew(J_STR);
        n->str = jparse_string(p);
        return n->str ? n : NULL;
    }
    if (!strncmp(*p, "true", 4) || !strncmp(*p, "false", 5))
    {
        n = jnew(J_BOOL);
        n->boolean = **p == 't';
        *p += n->boolean ? 4 : 5;
        return n;
    }
    if (!strncmp(*p, "null", 4))
    {
        *p += 4;
        return jnew(J_NULL);
    }
    {
        char *end;
        double v = strtod(*p, &end);

        if (end == *p)
            return NULL;
        n = jnew(J_NUM);
        n->num = v;
        *p = end;
        return n;
    }
}

/* the whole text is one value */
static jnode_t *jparse(const char *text)
{
    const char *p = text;
    jnode_t *n = jparse_value(&p, 0);

    if (n == NULL)
        return NULL;
    jskip(&p);
    return *p == '\0' ? n : NULL;
}

static jnode_t *jget(const jnode_t *o, const char *key)
{
    size_t i;

    if (o == NULL || o->type != J_OBJ)
        return NULL;
    for (i = 0; i < o->n; i++)
        if (!strcmp(o->key[i], key))
            return o->kid[i];
    return NULL;
}

static const char *jstr(const jnode_t *o, const char *key)
{
    jnode_t *v = jget(o, key);

    return v && v->type == J_STR ? v->str : NULL;
}

static int jnum(const jnode_t *o, const char *key, double *out)
{
    jnode_t *v = jget(o, key);

    if (v == NULL || v->type != J_NUM)
        return 0;
    *out = v->num;
    return 1;
}

static int jbool(const jnode_t *o, const char *key, int def)
{
    jnode_t *v = jget(o, key);

    return v && v->type == J_BOOL ? v->boolean : def;
}

/* ---------------------------------------------------------------- options */

typedef struct
{
    const char *child;
    const char *plugin;
    const char *id;
    const char *out;
    const char *log;
    const char *rates;
    const char *cpus;
    const char *reason;
    const char *offer;
    const char *set;
    unsigned quantum, blocks;
    /* the notes a CLAP instrument is timed holding: when it declares no voice capacity, and whatever it declares */
    unsigned probe_notes, hold;
    long wall_s, cpu_s, files;
    long long data_bytes, file_bytes;
    long grace_ms;
    char require[16][32];
    int nrequire;
} options_t;

/* the outcome codes of the header, by id */
#define X(id, code, meaning) static const char OUT_##id[] __attribute__((unused)) = code;
PHD_PROBE_OUTCOMES(X)
#undef X

#define X(id, code, meaning) static const char LIMIT_##id[] __attribute__((unused)) = code;
PHD_PROBE_LIMIT_CODES(X)
#undef X

static int outcome_known(const char *code)
{
    static const char *const ALL[] = {
#define X(id, code, meaning) code,
        PHD_PROBE_OUTCOMES(X)
#undef X
    };
    size_t i;

    for (i = 0; i < sizeof(ALL) / sizeof(*ALL); i++)
        if (!strcmp(ALL[i], code))
            return 1;
    return 0;
}

static int reason_known(const char *name)
{
    static const char *const ALL[] = {
#define X(id, code, meaning) code,
        PHD_PROBE_REASONS(X)
#undef X
    };
    size_t i;

    for (i = 0; i < sizeof(ALL) / sizeof(*ALL); i++)
        if (!strcmp(ALL[i], name))
            return 1;
    return 0;
}

static int step_known(const char *name)
{
    static const char *const ALL[] = {
#define X(id, code, meaning) code,
        PHD_PROBE_STEPS(X)
#undef X
    };
    size_t i;

    for (i = 0; i < sizeof(ALL) / sizeof(*ALL); i++)
        if (!strcmp(ALL[i], name))
            return 1;
    return 0;
}

/* ---------------------------------------------------------------- the record of a run */

typedef struct
{
    char step[24];
    long rate, quantum;
    const char *outcome;
    long elapsed_ms;
    char signal[16];
    int exit_status; /* -1 none */
    char detail[256];
} step_t;

typedef struct
{
    char name[32];
    long long value;
    int has_value;
    char str[64];
    const char *unit;
    const char *by;
} applied_t;

typedef struct
{
    char name[32];
    const char *code;
} unavailable_t;

typedef struct
{
    int cpu;
    char state[32];
    long latency_us;
    int disabled;
    long long usage;
} idle_t;

static step_t g_steps[MAX_STEPS];
static int g_nsteps;
static applied_t g_applied[24];
static int g_napplied;
static unavailable_t g_unavailable[24];
static int g_nunavailable;
#define IDLE_MAX 512
static idle_t g_idle_before[IDLE_MAX], g_idle_after[IDLE_MAX];
static int g_nidle;

static volatile sig_atomic_t g_cancel;

static void on_cancel(int sig)
{
    (void)sig;
    g_cancel = 1;
}

static long now_ms(void)
{
    struct timespec t;

    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long)(t.tv_sec * 1000 + t.tv_nsec / 1000000);
}

static step_t *add_step(const char *step, const char *outcome, long elapsed_ms)
{
    step_t *s;

    if (g_nsteps == MAX_STEPS)
        return &g_steps[MAX_STEPS - 1];
    s = &g_steps[g_nsteps++];
    memset(s, 0, sizeof(*s));
    snprintf(s->step, sizeof(s->step), "%s", step);
    s->outcome = outcome;
    s->elapsed_ms = elapsed_ms;
    s->exit_status = -1;
    return s;
}

static void set_detail(step_t *s, const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(s->detail, sizeof(s->detail), fmt, ap);
    va_end(ap);
}

static void note_applied(const char *name, const char *by, const char *unit, long long value, int has_value, const char *str)
{
    applied_t *a = &g_applied[g_napplied++];

    snprintf(a->name, sizeof(a->name), "%s", name);
    a->by = by;
    a->unit = unit;
    a->value = value;
    a->has_value = has_value;
    snprintf(a->str, sizeof(a->str), "%s", str ? str : "");
}

static void note_unavailable(const char *name, const char *code)
{
    unavailable_t *u = &g_unavailable[g_nunavailable++];

    snprintf(u->name, sizeof(u->name), "%s", name);
    u->code = code;
}

/* ---------------------------------------------------------------- the machine */

static int read_text(const char *path, char *buf, size_t size)
{
    FILE *f = fopen(path, "r");
    size_t n;

    if (f == NULL)
        return -1;
    n = fread(buf, 1, size - 1, f);
    fclose(f);
    buf[n] = '\0';
    while (n && (buf[n - 1] == '\n' || buf[n - 1] == ' '))
        buf[--n] = '\0';
    return 0;
}

/* "0-3,8" into the cpu numbers; returns how many */
static int parse_cpu_list(const char *list, int *cpus, int max)
{
    int n = 0;
    const char *p = list;

    while (*p)
    {
        char *end;
        long a = strtol(p, &end, 10), b;

        if (end == p)
            return -1;
        b = a;
        if (*end == '-')
        {
            p = end + 1;
            b = strtol(p, &end, 10);
            if (end == p)
                return -1;
        }
        for (; a <= b; a++)
            if (n < max && a >= 0 && a < CPU_SETSIZE)
                cpus[n++] = (int)a;
        if (*end == ',')
            end++;
        else if (*end)
            return -1;
        p = end;
    }
    return n;
}

/* the cpu numbers of a set as the shortest list: "0-3,8" */
static void cpu_list_text(const cpu_set_t *set, char *out, size_t size)
{
    int c, first = -1, last = -1;
    size_t len = 0;

    out[0] = '\0';
    for (c = 0; c <= CPU_SETSIZE; c++)
    {
        int in = c < CPU_SETSIZE && CPU_ISSET(c, set);

        if (in && first < 0)
            first = c;
        if (in)
            last = c;
        if (!in && first >= 0)
        {
            len += (size_t)snprintf(out + len, size - len, "%s%d", len ? "," : "", first);
            if (last > first)
                len += (size_t)snprintf(out + len, size - len, "-%d", last);
            first = -1;
        }
        if (len >= size - 16)
            break;
    }
}

static void read_idle(idle_t *rows, int *count, const cpu_set_t *pinned)
{
    int c, n = 0;

    for (c = 0; c < CPU_SETSIZE && n < IDLE_MAX; c++)
    {
        int s;

        if (!CPU_ISSET(c, pinned))
            continue;
        for (s = 0; s < 16 && n < IDLE_MAX; s++)
        {
            char path[160], text[64];
            idle_t *r = &rows[n];

            snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/name", c, s);
            if (read_text(path, r->state, sizeof(r->state)) != 0)
                break;
            r->cpu = c;
            snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/latency", c, s);
            r->latency_us = read_text(path, text, sizeof(text)) == 0 ? atol(text) : 0;
            snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/disable", c, s);
            r->disabled = read_text(path, text, sizeof(text)) == 0 && atoi(text) != 0;
            snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/usage", c, s);
            r->usage = read_text(path, text, sizeof(text)) == 0 ? atoll(text) : 0;
            n++;
        }
    }
    *count = n;
}

/* the idle state that counts as deep: its exit latency is above this many microseconds */
#define DEEP_IDLE_US 20

static void put_machine(sb_t *b, const cpu_set_t *pinned, int pinned_by_option)
{
    struct utsname u;
    char text[256], cpus[256], vendor[64] = "", family[32] = "unknown", governor[64] = "";
    const char *core_band, *clock_band;
    long ncpu = sysconf(_SC_NPROCESSORS_ONLN), khz = 0;
    int preempt_rt = 0, deep_entered = 0, deep_enabled = 0, i;
    FILE *f;

    uname(&u);
    if ((f = fopen("/proc/cpuinfo", "r")))
    {
        char line[256];

        while (fgets(line, sizeof(line), f))
            if (!strncmp(line, "vendor_id", 9) && (vendor[0] == '\0'))
            {
                const char *v = strchr(line, ':');

                if (v)
                    snprintf(vendor, sizeof(vendor), "%s", v + 2);
                vendor[strcspn(vendor, "\n")] = '\0';
            }
        fclose(f);
    }
    if (strstr(vendor, "Intel"))
        snprintf(family, sizeof(family), "intel");
    else if (strstr(vendor, "AMD"))
        snprintf(family, sizeof(family), "amd");
    else if (!strncmp(u.machine, "aarch64", 7) || !strncmp(u.machine, "arm", 3))
        snprintf(family, sizeof(family), "arm");
    if (read_text("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", text, sizeof(text)) == 0)
        khz = atol(text);
    if (read_text("/sys/kernel/realtime", text, sizeof(text)) == 0)
        preempt_rt = atoi(text) == 1;
    /* the bands are omx-contract's MACHINE_CORE_BANDS and MACHINE_CLOCK_BANDS */
    core_band = ncpu <= 2 ? OMX_MACHINE_CORE_BANDS_CORES1_TO2 : ncpu <= 4 ? OMX_MACHINE_CORE_BANDS_CORES3_TO4 :
                ncpu <= 8 ? OMX_MACHINE_CORE_BANDS_CORES5_TO8 : ncpu <= 16 ? OMX_MACHINE_CORE_BANDS_CORES9_TO16 :
                ncpu <= 32 ? OMX_MACHINE_CORE_BANDS_CORES17_TO32 : OMX_MACHINE_CORE_BANDS_CORES33_UP;
    clock_band = khz < 1500000 ? OMX_MACHINE_CLOCK_BANDS_UNDER1500_MHZ : khz < 2500000 ? OMX_MACHINE_CLOCK_BANDS_FROM1500_TO2500_MHZ :
                 khz < 3500000 ? OMX_MACHINE_CLOCK_BANDS_FROM2500_TO3500_MHZ :
                 khz < 4500000 ? OMX_MACHINE_CLOCK_BANDS_FROM3500_TO4500_MHZ : OMX_MACHINE_CLOCK_BANDS_FROM4500_MHZ;
    for (i = 0; i < g_nidle; i++)
    {
        if (g_idle_after[i].latency_us > DEEP_IDLE_US && !g_idle_after[i].disabled)
            deep_enabled = 1;
        if (g_idle_after[i].latency_us > DEEP_IDLE_US && g_idle_after[i].usage > g_idle_before[i].usage)
            deep_entered = 1;
    }
    {
        int cpu0 = -1;

        for (i = 0; i < CPU_SETSIZE && cpu0 < 0; i++)
            if (CPU_ISSET(i, pinned))
                cpu0 = i;
        snprintf(text, sizeof(text), "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_governor", cpu0 < 0 ? 0 : cpu0);
        if (read_text(text, governor, sizeof(governor)) != 0)
            governor[0] = '\0';
    }
    cpu_list_text(pinned, cpus, sizeof(cpus));

    sb_printf(b, ",\n  \"machine\": {\n    \"class\": {\"arch\": ");
    sb_str(b, u.machine);
    sb_printf(b, ", \"family\": ");
    sb_str(b, family);
    sb_printf(b, ", \"coreBand\": \"%s\", \"clockBand\": \"%s\", \"preemptRt\": %s, \"cstatesLimited\": %s},\n", core_band, clock_band,
              preempt_rt ? "true" : "false", g_nidle > 0 && !deep_enabled ? "true" : "false");
    sb_printf(b, "    \"profile\": {\"governor\": ");
    if (governor[0])
        sb_str(b, governor);
    else
        sb_put(b, "null", 4);
    sb_printf(b, ", \"turbo\": ");
    if (read_text("/sys/devices/system/cpu/intel_pstate/no_turbo", text, sizeof(text)) == 0)
        sb_printf(b, "%s", atoi(text) ? "false" : "true");
    else if (read_text("/sys/devices/system/cpu/cpufreq/boost", text, sizeof(text)) == 0)
        sb_printf(b, "%s", atoi(text) ? "true" : "false");
    else
        sb_put(b, "null", 4);
    sb_printf(b, ", \"smt\": ");
    if (read_text("/sys/devices/system/cpu/smt/active", text, sizeof(text)) == 0)
        sb_printf(b, "%s", atoi(text) ? "true" : "false");
    else
        sb_put(b, "null", 4);
    sb_printf(b, ", \"preempt\": ");
    if (read_text("/proc/version", text, sizeof(text)) == 0 && strstr(text, "PREEMPT_RT"))
        sb_str(b, "PREEMPT_RT");
    else if (text[0] && strstr(text, "PREEMPT_DYNAMIC"))
        sb_str(b, "PREEMPT_DYNAMIC");
    else if (text[0] && strstr(text, "PREEMPT"))
        sb_str(b, "PREEMPT");
    else
        sb_put(b, "null", 4);
    sb_printf(b, ",\n      \"cpuidle\": [");
    for (i = 0; i < g_nidle; i++)
    {
        sb_printf(b, "%s\n        {\"cpu\": %d, \"state\": ", i ? "," : "", g_idle_after[i].cpu);
        sb_str(b, g_idle_after[i].state);
        sb_printf(b, ", \"latencyUs\": %ld, \"disabled\": %s, \"usageDelta\": %lld}", g_idle_after[i].latency_us,
                  g_idle_after[i].disabled ? "true" : "false",
                  g_idle_after[i].usage > g_idle_before[i].usage ? g_idle_after[i].usage - g_idle_before[i].usage : 0);
    }
    sb_printf(b, "%s],\n", g_nidle ? "\n      " : "");
    /* what the protocol's optimised profile asks (rules of this runner until the protocol document states them): the
     * performance governor, no deep idle state entered while the child ran, and the child pinned */
    {
        int governor_ok = !strcmp(governor, "performance"), pinned_ok = pinned_by_option, meets;
        const char *sep = "";

        meets = governor_ok && !deep_entered && pinned_ok;
        sb_printf(b, "      \"meetsProtocol\": %s, \"unmet\": [", meets ? "true" : "false");
        if (!governor_ok)
            sb_printf(b, "%s\"probe.profile.governor\"", sep), sep = ", ";
        if (deep_entered)
            sb_printf(b, "%s\"probe.profile.deep-idle-entered\"", sep), sep = ", ";
        if (!pinned_ok)
            sb_printf(b, "%s\"probe.profile.not-pinned\"", sep), sep = ", ";
        sb_printf(b, "]},\n");
    }
    sb_printf(b, "    \"pinnedCpus\": \"%s\"\n  }", cpus[0] ? cpus : "0");
}

/* ---------------------------------------------------------------- the process tree */

/* every process that descends from `root` now, found through /proc (a parent of 0 or 1 ends the chain) */
static int descendants(pid_t root, pid_t *out, int max)
{
    static pid_t pid_of[32768], ppid_of[32768];
    int n = 0, count = 0, i, grew = 1;
    DIR *d = opendir("/proc");
    struct dirent *e;

    if (d == NULL)
        return 0;
    while ((e = readdir(d)) && n < 32768)
    {
        char path[64], line[512];
        FILE *f;
        pid_t pid = (pid_t)atoi(e->d_name);

        if (pid <= 0)
            continue;
        snprintf(path, sizeof(path), "/proc/%d/stat", pid);
        if ((f = fopen(path, "r")) == NULL)
            continue;
        if (fgets(line, sizeof(line), f))
        {
            const char *rp = strrchr(line, ')');
            int ppid = 0;
            char state;

            if (rp && sscanf(rp + 1, " %c %d", &state, &ppid) == 2)
            {
                pid_of[n] = pid;
                ppid_of[n++] = ppid;
            }
        }
        fclose(f);
    }
    closedir(d);
    while (grew)
    {
        grew = 0;
        for (i = 0; i < n; i++)
        {
            int k, known = pid_of[i] == root;

            for (k = 0; k < count && !known; k++)
                known = out[k] == pid_of[i];
            if (known)
                continue;
            if (ppid_of[i] == root)
                known = 1;
            for (k = 0; k < count && !known; k++)
                known = out[k] == ppid_of[i];
            if (known && count < max)
            {
                out[count++] = pid_of[i];
                grew = 1;
            }
        }
    }
    return count;
}

/* kill the child's group and every descendant of the runner, however far from the group it has gone; returns how many
 * processes were found alive besides the child's group's leader */
static int kill_tree(pid_t group, int sig)
{
    pid_t list[512];
    int n = descendants(getpid(), list, 512), i;

    if (group > 0)
        kill(-group, sig);
    for (i = 0; i < n; i++)
        kill(list[i], sig);
    return n;
}

/* reap what the runner has as children for up to `ms`; returns when none is left */
static void reap_all(long ms)
{
    long end = now_ms() + ms;

    for (;;)
    {
        pid_t r = waitpid(-1, NULL, WNOHANG);

        if (r > 0)
            continue;
        if (r < 0 && errno == ECHILD)
            return;
        if (now_ms() >= end)
            return;
        usleep(5000);
    }
}

/* ---------------------------------------------------------------- limits */

static const char *signal_name(int sig)
{
    switch (sig)
    {
    case SIGSEGV: return "SIGSEGV";
    case SIGABRT: return "SIGABRT";
    case SIGBUS: return "SIGBUS";
    case SIGFPE: return "SIGFPE";
    case SIGILL: return "SIGILL";
    case SIGKILL: return "SIGKILL";
    case SIGTERM: return "SIGTERM";
    case SIGXCPU: return "SIGXCPU";
    case SIGXFSZ: return "SIGXFSZ";
    case SIGSYS: return "SIGSYS";
    case SIGPIPE: return "SIGPIPE";
    case SIGINT: return "SIGINT";
    case SIGHUP: return "SIGHUP";
    default: return "SIGNAL";
    }
}

static void put_rlimit(int resource, rlim_t soft, rlim_t hard)
{
    struct rlimit r = { soft, hard };

    if (setrlimit(resource, &r) != 0)
        _exit(120);
}

/* in the child, before the exec: the limits of the set; exits 120 when one cannot be applied */
static void apply_limits(const options_t *o, const cpu_set_t *pinned, int pin_option)
{
    setpgid(0, 0);
    prctl(PR_SET_PDEATHSIG, SIGKILL);
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)
        _exit(120);
    put_rlimit(RLIMIT_CPU, (rlim_t)o->cpu_s, (rlim_t)o->cpu_s + 5);
    put_rlimit(RLIMIT_DATA, (rlim_t)o->data_bytes, (rlim_t)o->data_bytes);
    put_rlimit(RLIMIT_NOFILE, (rlim_t)o->files, (rlim_t)o->files);
    put_rlimit(RLIMIT_FSIZE, (rlim_t)o->file_bytes, (rlim_t)o->file_bytes);
    put_rlimit(RLIMIT_CORE, 0, 0);
    put_rlimit(RLIMIT_RTPRIO, 0, 0);
    if (pin_option && sched_setaffinity(0, sizeof(*pinned), pinned) != 0)
        _exit(120);
}

/* the limits of the default set, as the document lists them */
static int list_limits(const options_t *o, int pin_option, const char *cpus)
{
    unsigned i;
    static const char *const NOT_APPLIED[] = { "tasks" };

    note_applied("wall-clock", "supervisor", "s", o->wall_s, 1, NULL);
    note_applied("cpu-time", "rlimit", "s", o->cpu_s, 1, NULL);
    note_applied("memory", "rlimit", "bytes", o->data_bytes, 1, NULL);
    note_applied("files", "rlimit", "count", o->files, 1, NULL);
    note_applied("file-size", "rlimit", "bytes", o->file_bytes, 1, NULL);
    note_applied("core-dump", "rlimit", "bytes", 0, 1, NULL);
    note_applied("rt-priority", "rlimit", NULL, 0, 1, NULL);
    if (pin_option)
        note_applied("cpus", "affinity", NULL, 0, 0, cpus);
    note_applied("no-new-privs", "prctl", NULL, 0, 0, NULL);
    for (i = 0; i < sizeof(NOT_APPLIED) / sizeof(*NOT_APPLIED); i++)
        note_unavailable(NOT_APPLIED[i], LIMIT_NOT_IMPLEMENTED);
    for (i = 0; i < (unsigned)o->nrequire; i++)
    {
        int k, met = 0;

        for (k = 0; k < g_napplied; k++)
            if (!strcmp(g_applied[k].name, o->require[i]))
                met = 1;
        if (!met)
        {
            fprintf(stderr, RUNNER_NAME ": --require %s: the limit is not applied by this runner\n", o->require[i]);
            return -1;
        }
    }
    return 0;
}

/* ---------------------------------------------------------------- the run */

typedef struct
{
    pid_t pid;
    int out_fd, steps_fd;
    sb_t out, steps;
    int out_eof, steps_eof;
    int status, exited;
    int killed_by_deadline, cancelled;
    int leftovers;
    int protocol_error;
    int records; /* step records the child wrote on fd 3: when it wrote any, its line adds none */
    long started_ms;
} run_t;

static void set_nonblock(int fd)
{
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
}

static void pump(int *fd, int *eof, sb_t *b)
{
    char buf[8192];

    while (*fd >= 0 && !*eof)
    {
        ssize_t n = read(*fd, buf, sizeof(buf));

        if (n > 0)
        {
            if (b->len + (size_t)n <= LINE_MAX_BYTES)
                sb_put(b, buf, (size_t)n);
            continue;
        }
        if (n == 0)
            *eof = 1;
        break;
    }
}

/* the child's step records: lines of JSON on fd 3; one outside the grammar ends the run with probe.child-protocol */
static void take_step_records(run_t *r)
{
    char *line = r->steps.s, *end;
    size_t used = 0;

    if (line == NULL)
        return;
    while ((end = memchr(line, '\n', r->steps.len - used)))
    {
        jnode_t *n;
        const char *name, *outcome;
        double rate = 0, quantum = 0, elapsed = 0;

        *end = '\0';
        n = *line ? jparse(line) : NULL;
        name = jstr(n, "step");
        outcome = jstr(n, "outcome");
        if (n == NULL || n->type != J_OBJ || name == NULL || outcome == NULL || !step_known(name) || !outcome_known(outcome))
            r->protocol_error = 1;
        else
        {
            step_t *s;

            jnum(n, "rate", &rate);
            jnum(n, "quantum", &quantum);
            jnum(n, "elapsedMs", &elapsed);
            s = add_step(name, outcome, (long)elapsed);
            r->records++;
            s->rate = (long)rate;
            s->quantum = (long)quantum;
            if (jstr(n, "detail"))
                set_detail(s, "%s", jstr(n, "detail"));
        }
        used += (size_t)(end - line) + 1;
        line = end + 1;
    }
    memmove(r->steps.s, r->steps.s + used, r->steps.len - used);
    r->steps.len -= used;
    r->steps.s[r->steps.len] = '\0';
}

/* clap-qualify's arguments: the rates, the block, the offer, the notes an instrument holds, the file and the id */
static void clap_argv(const options_t *o, char **argv)
{
    int argc = 0;

    argv[argc++] = (char *)o->child;
    argv[argc++] = "--rates";
    argv[argc++] = (char *)o->rates;
    {
        static char block[32], blocks[32];

        snprintf(block, sizeof(block), "%u", o->quantum);
        argv[argc++] = "--block";
        argv[argc++] = block;
        if (o->blocks)
        {
            snprintf(blocks, sizeof(blocks), "%u", o->blocks);
            argv[argc++] = "--blocks";
            argv[argc++] = blocks;
        }
    }
    if (o->offer)
    {
        argv[argc++] = "--offer";
        argv[argc++] = (char *)o->offer;
    }
    {
        static char notes[32], hold[32];

        if (o->probe_notes)
        {
            snprintf(notes, sizeof(notes), "%u", o->probe_notes);
            argv[argc++] = "--probe-notes";
            argv[argc++] = notes;
        }
        if (o->hold)
        {
            snprintf(hold, sizeof(hold), "%u", o->hold);
            argv[argc++] = "--hold";
            argv[argc++] = hold;
        }
    }
    argv[argc++] = (char *)o->plugin;
    if (o->id)
        argv[argc++] = (char *)o->id;
    argv[argc] = NULL;
}

/* the child `argv` under the limits, until it ends or `deadline` (ms of now_ms) passes; its log is appended to */
static void run_child(const options_t *o, char **argv, const cpu_set_t *pinned, int pin_option, run_t *r, long deadline)
{
    int out_pipe[2], steps_pipe[2], status_pipe[2];
    int devnull;
    int log_fd = -1;

    if (pipe2(out_pipe, O_CLOEXEC) || pipe2(steps_pipe, O_CLOEXEC) || pipe2(status_pipe, O_CLOEXEC))
    {
        perror("pipe");
        exit(2);
    }
    if (o->log)
        log_fd = open(o->log, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);

    r->started_ms = now_ms();
    r->pid = fork();
    if (r->pid < 0)
    {
        perror("fork");
        exit(2);
    }
    if (r->pid == 0)
    {
        devnull = open("/dev/null", O_RDONLY);
        dup2(devnull, 0);
        dup2(out_pipe[1], 1);
        dup2(log_fd >= 0 ? log_fd : open("/dev/null", O_WRONLY), 2);
        if (steps_pipe[1] != 3)
            dup2(steps_pipe[1], 3);
        fcntl(3, F_SETFD, 0);
        close(status_pipe[0]);
        apply_limits(o, pinned, pin_option);
        execvp(o->child, argv);
        {
            int e = errno;

            if (write(status_pipe[1], &e, sizeof(e)) < 0)
                _exit(127);
        }
        _exit(127);
    }
    close(out_pipe[1]);
    close(steps_pipe[1]);
    close(status_pipe[1]);
    if (log_fd >= 0)
        close(log_fd);
    r->out_fd = out_pipe[0];
    r->steps_fd = steps_pipe[0];
    set_nonblock(r->out_fd);
    set_nonblock(r->steps_fd);
    {
        int e = 0;

        if (read(status_pipe[0], &e, sizeof(e)) == (ssize_t)sizeof(e))
        {
            fprintf(stderr, RUNNER_NAME ": cannot run %s: %s\n", o->child, strerror(e));
            waitpid(r->pid, NULL, 0);
            exit(2);
        }
        close(status_pipe[0]);
    }

    while (!r->exited)
    {
        struct pollfd p[2];
        int np = 0, rc;
        long left = deadline - now_ms();
        pid_t w;

        if (g_cancel)
        {
            r->cancelled = 1;
            break;
        }
        if (left <= 0)
        {
            r->killed_by_deadline = 1;
            break;
        }
        if (!r->out_eof)
            p[np].fd = r->out_fd, p[np++].events = POLLIN;
        if (!r->steps_eof)
            p[np].fd = r->steps_fd, p[np++].events = POLLIN;
        rc = poll(p, (nfds_t)np, np ? (int)(left < 50 ? left : 50) : 20);
        (void)rc;
        pump(&r->out_fd, &r->out_eof, &r->out);
        pump(&r->steps_fd, &r->steps_eof, &r->steps);
        take_step_records(r);
        w = waitpid(r->pid, &r->status, WNOHANG);
        if (w == r->pid)
            r->exited = 1;
    }
    if (!r->exited)
    {
        /* the deadline or a cancel: the tree gets a SIGTERM, then after the grace a SIGKILL */
        long end;

        kill_tree(r->pid, SIGTERM);
        end = now_ms() + o->grace_ms;
        while (now_ms() < end && waitpid(r->pid, &r->status, WNOHANG) != r->pid)
            usleep(5000);
        if (waitpid(r->pid, &r->status, WNOHANG) == r->pid || kill(r->pid, 0) != 0)
            r->exited = 1;
        if (!r->exited)
        {
            kill_tree(r->pid, SIGKILL);
            waitpid(r->pid, &r->status, 0);
            r->exited = 1;
        }
    }
    pump(&r->out_fd, &r->out_eof, &r->out);
    pump(&r->steps_fd, &r->steps_eof, &r->steps);
    take_step_records(r);
    /* whatever the plugin left behind goes now, in its own session or not */
    {
        int pass;

        for (pass = 0; pass < 10; pass++)
        {
            int n = kill_tree(r->pid, SIGKILL);

            if (n == 0)
                break;
            if (pass == 0)
                r->leftovers = n;
            reap_all(50);
        }
        reap_all(200);
    }
    pump(&r->out_fd, &r->out_eof, &r->out);
    close(r->out_fd);
    close(r->steps_fd);
}

/* ---------------------------------------------------------------- the document */

static void iso_time(time_t t, char *out, size_t size)
{
    struct tm tm;
    char zone[16];

    localtime_r(&t, &tm);
    strftime(out, size, "%Y-%m-%dT%H:%M:%S", &tm);
    strftime(zone, sizeof(zone), "%z", &tm);
    snprintf(out + strlen(out), size - strlen(out), "%.3s:%.2s", zone, zone + 3);
}

static void put_step(sb_t *b, const step_t *s)
{
    sb_printf(b, "{\"step\": \"%s\"", s->step);
    if (s->rate)
        sb_printf(b, ", \"rate\": %ld", s->rate);
    if (s->quantum)
        sb_printf(b, ", \"quantum\": %ld", s->quantum);
    sb_printf(b, ", \"outcome\": \"%s\", \"elapsedMs\": %ld", s->outcome, s->elapsed_ms);
    if (s->signal[0])
        sb_printf(b, ", \"signal\": \"%s\"", s->signal);
    if (s->exit_status >= 0)
        sb_printf(b, ", \"exitStatus\": %d", s->exit_status);
    if (s->detail[0])
    {
        sb_printf(b, ", \"detail\": ");
        sb_str(b, s->detail);
    }
    sb_printf(b, "}");
}

static int outcome_ok(const char *code)
{
    return !strcmp(code, OUT_OK) || !strcmp(code, OUT_NOT_ATTEMPTED);
}

/* how the child ended, as the step `name`: its outcome, and whether the run may still be complete */
static const char *child_end(const char *name, const options_t *o, const run_t *r, int *complete)
{
    {
        const char *code = OUT_OK;
        step_t *s = add_step(name, OUT_OK, now_ms() - r->started_ms);

        if (r->protocol_error)
            code = OUT_CHILD_PROTOCOL;
        else if (r->cancelled)
            code = OUT_CANCELLED;
        else if (r->killed_by_deadline)
            code = OUT_TIMEOUT;
        else if (WIFSIGNALED(r->status))
        {
            int sig = WTERMSIG(r->status);

            snprintf(s->signal, sizeof(s->signal), "%s", signal_name(sig));
            code = sig == SIGXCPU ? OUT_CPU_LIMIT : sig == SIGXFSZ ? OUT_OUTPUT_LIMIT : sig == SIGSYS ? OUT_SANDBOX_DENIED : OUT_CRASHED;
        }
        else if (WIFEXITED(r->status))
        {
            s->exit_status = WEXITSTATUS(r->status);
            if (s->exit_status == 120)
            {
                code = OUT_ERROR;
                set_detail(s, "a limit could not be applied in the child");
            }
            else if (s->exit_status != 0 && r->out.len == 0)
                code = OUT_ERROR;
        }
        s->outcome = code;
        if (r->killed_by_deadline)
            set_detail(s, "the wall clock of %ld s passed; the process tree was killed", o->wall_s);
        if (r->cancelled)
            set_detail(s, "the runner was told to stop; the process tree was killed");
        if (r->leftovers && !s->detail[0])
            set_detail(s, "%d process(es) left behind were killed", r->leftovers);
        else if (r->leftovers)
            snprintf(s->detail + strlen(s->detail), sizeof(s->detail) - strlen(s->detail), "; %d process(es) left behind were killed", r->leftovers);
        /* a crash keeps the steps before it; the run is complete only when the child finished */
        *complete = !strcmp(code, OUT_OK) && WIFEXITED(r->status);
        return code;
    }
}

/* an LV2 plugin is named lv2:<uri>, and measured by plugin-qualify's lv2_measure, looked up where plugin-qualify installs
 * it; plugin-qualify is no dependency of this package (it builds against it), so the program is looked for at run time */
#define PROBE_LV2_PREFIX "lv2:"
#define PROBE_LV2_CHILD "/usr/libexec/plugin-qualify/lv2_measure"
/* both measurements run as plugin-qualify runs them: under its allocation-and-syscall interposer, the file of this name
 * beside the child (none beside it: rtSafety says interposer false, and the rt-safety step says why); an LV2 one also
 * under the noise stimulus */
#define PROBE_INTERPOSER "rt_interpose.so"
#define PROBE_LV2_STIMULUS_ENV "OMX_STIM"
#define PROBE_LV2_STIMULUS "noise"

/* the interposer preloaded into the measuring child, or empty; when empty, why none was */
static char g_interposer[PATH_MAX];
static char g_no_interposer[PATH_MAX + 128];

/* the interposer beside `child`, the child found as execvp finds it (a bare name on PATH): 1 with g_interposer its path,
 * else 0 with g_no_interposer saying where none was found */
static int interposer_beside(const char *child)
{
    char dir[PATH_MAX];
    const char *slash = strrchr(child, '/');

    g_interposer[0] = '\0';
    if (slash)
        snprintf(dir, sizeof(dir), "%.*s", (int)(slash - child), child);
    else
    {
        const char *path = getenv("PATH"), *p;
        int found = 0;

        for (p = path ? path : ""; !found && *p;)
        {
            size_t n = strcspn(p, ":");
            char exe[PATH_MAX];

            snprintf(dir, sizeof(dir), "%.*s", (int)(n ? n : 1), n ? p : ".");
            snprintf(exe, sizeof(exe), "%s/%s", dir, child);
            found = access(exe, X_OK) == 0;
            p += n + (p[n] == ':');
        }
        if (!found)
        {
            snprintf(g_no_interposer, sizeof(g_no_interposer), "%s is not on PATH, so no " PROBE_INTERPOSER " beside it was preloaded", child);
            return 0;
        }
    }
    snprintf(g_interposer, sizeof(g_interposer), "%s/" PROBE_INTERPOSER, dir);
    if (access(g_interposer, R_OK) == 0)
        return 1;
    snprintf(g_no_interposer, sizeof(g_no_interposer), "no " PROBE_INTERPOSER " beside the child in %s", dir[0] ? dir : "/");
    g_interposer[0] = '\0';
    return 0;
}

/* The measured child gets the interposer and nothing else: a preload the runner was started with (another malloc
 * interposer would hide the allocations) is dropped for the measurement, the record says so, and the runner's own
 * LD_PRELOAD is put back after the child */
static int g_had_preload;
static char g_saved_preload[PATH_MAX * 4];
static char g_dropped_preload[PATH_MAX * 4];

static void preload_for_measurement(const char *child)
{
    const char *was = getenv("LD_PRELOAD");

    g_had_preload = was != NULL;
    snprintf(g_saved_preload, sizeof(g_saved_preload), "%s", was ? was : "");
    g_dropped_preload[0] = '\0';
    if (interposer_beside(child))
        setenv("LD_PRELOAD", g_interposer, 1);
    else
        unsetenv("LD_PRELOAD");
    /* what the runner had and the child does not get is dropped */
    if (g_saved_preload[0] && strcmp(g_saved_preload, g_interposer))
        snprintf(g_dropped_preload, sizeof(g_dropped_preload), "%s", g_saved_preload);
}

static void preload_restore(void)
{
    if (g_had_preload)
        setenv("LD_PRELOAD", g_saved_preload, 1);
    else
        unsetenv("LD_PRELOAD");
}

/* an rt-safety detail, with the preload that was dropped for the measurement when there was one */
static const char *with_dropped(const char *text)
{
    static char out[512];

    if (!g_dropped_preload[0])
        return text;
    snprintf(out, sizeof(out), "%s; dropped LD_PRELOAD=%s for the measurement", text, g_dropped_preload);
    return out;
}

/* why a child's line says no interposer counted: none was found beside it, or the one preloaded did not load */
static const char *no_interposer_reason(void)
{
    static char text[PATH_MAX + 128];

    if (!g_interposer[0])
        return g_no_interposer[0] ? g_no_interposer : "no interposer was preloaded";
    snprintf(text, sizeof(text), "%s was preloaded and the child says no interposer was loaded", g_interposer);
    return text;
}

static jnode_t *first_line(sb_t *out)
{
    if (out->len == 0)
        return NULL;
    out->s[strcspn(out->s, "\n")] = '\0';
    return jparse(out->s);
}

static int has_suffix(const char *s, const char *suffix)
{
    size_t n = strlen(s), m = strlen(suffix);

    return n >= m && !strcmp(s + n - m, suffix);
}

/* lv2_measure's passes as today's LV2 hosting pass runs them: the pin (--pin, nothing instantiated), then one measurement
 * at `rate` in blocks of the run's quantum, PHD_PROBE_LV2_LIFECYCLES instantiate/destroy cycles and
 * PHD_PROBE_LV2_REPEATS swept rt-safety runs. Each pass is a child of its own under the same limits and the one wall
 * clock. 3 when no bundle holds the plugin (no document); else 0, with *library the pinned file that is the plugin's
 * library, NULL when nothing was pinned. */
static int run_lv2(const options_t *o, const char *uri, long rate, const cpu_set_t *pinned, int pin_option, long deadline, run_t *r,
                   jnode_t **pin, jnode_t **measure, const jnode_t **library, const char **outcome, int *complete)
{
    char *argv[8], rate_s[24], block_s[24], cycles_s[24], repeats_s[24];
    const jnode_t *integrity, *files;
    size_t k;

    argv[0] = (char *)o->child;
    argv[1] = "--pin";
    argv[2] = (char *)uri;
    argv[3] = NULL;
    run_child(o, argv, pinned, pin_option, r, deadline);
    *pin = first_line(&r->out);
    if (!r->killed_by_deadline && !r->cancelled && WIFEXITED(r->status) && WEXITSTATUS(r->status) == 3 &&
        !jbool(*pin, "found", 1))
    {
        fprintf(stderr, RUNNER_NAME ": %s%s: %s\n", PROBE_LV2_PREFIX, uri, OUT_NOT_FOUND);
        return 3;
    }
    *outcome = child_end("hash", o, r, complete);
    integrity = jget(*pin, "integrity");
    files = jget(integrity, "files");
    for (k = 0; files && files->type == J_ARR && k < files->n; k++)
        if (jstr(files->kid[k], "path") && !has_suffix(jstr(files->kid[k], "path"), ".ttl"))
        {
            *library = files->kid[k];
            break;
        }
    if (!strcmp(*outcome, OUT_OK) && *library == NULL)
    {
        step_t *s = &g_steps[g_nsteps - 1];
        const char *reason = jstr(integrity, "unmeasuredReason"), *detail = jstr(integrity, "unmeasuredDetail");

        s->outcome = *outcome = reason && !strcmp(reason, "unpinnable") ? OUT_UNPINNABLE : OUT_ERROR;
        set_detail(s, "%s", detail ? detail : "the child pinned no library of the plugin");
        *complete = 0;
    }
    if (strcmp(*outcome, OUT_OK))
        return 0;

    snprintf(rate_s, sizeof(rate_s), "%ld", rate);
    snprintf(block_s, sizeof(block_s), "%u", o->quantum);
    snprintf(cycles_s, sizeof(cycles_s), "%d", PHD_PROBE_LV2_LIFECYCLES);
    snprintf(repeats_s, sizeof(repeats_s), "%d", PHD_PROBE_LV2_REPEATS);
    argv[1] = (char *)uri;
    argv[2] = rate_s;
    argv[3] = block_s;
    argv[4] = cycles_s;
    argv[5] = repeats_s;
    argv[6] = NULL;
    preload_for_measurement(o->child);
    setenv(PROBE_LV2_STIMULUS_ENV, PROBE_LV2_STIMULUS, 1);
    memset(r, 0, sizeof(*r));
    run_child(o, argv, pinned, pin_option, r, deadline);
    preload_restore();
    *measure = first_line(&r->out);
    if (*measure && jbool(*measure, "instantiated", 0))
    {
        const jnode_t *rt = jget(*measure, "rtSafety");
        step_t *s = add_step("instantiate", OUT_OK, 0);

        set_detail(s, "read from the child's line");
        s = add_step("rt-safety", jbool(rt, "interposer", 0) ? OUT_OK : OUT_NOT_ATTEMPTED, 0);
        s->rate = rate;
        s->quantum = o->quantum;
        set_detail(s, "%s", with_dropped(jbool(rt, "interposer", 0) ? "read from the child's line" : no_interposer_reason()));
    }
    else if (*measure && jbool(*measure, "found", 0))
    {
        step_t *s = add_step("instantiate", OUT_REFUSED_INSTANTIATION, 0);

        set_detail(s, "the child could not instantiate the plugin");
    }
    *outcome = child_end("lifecycle", o, r, complete);
    return 0;
}

static void put_count(sb_t *b, const jnode_t *o, const char *from, const char *to)
{
    double v;

    if (jnum(o, from, &v))
        sb_printf(b, ", \"%s\": %.0f", to, v);
}

/* a prober's note sweep, as a point carries it: whether it applied, the dialect it played in, and what process() or run()
 * did while it played when the interposer counted; a sweep the interposer did not count carries no counts */
static void put_note_sweep(sb_t *b, const jnode_t *ns)
{
    sb_printf(b, ", \"noteSweep\": {\"applicable\": %s", jbool(ns, "applicable", 0) ? "true" : "false");
    if (jstr(ns, "dialect"))
    {
        sb_printf(b, ", \"dialect\": ");
        sb_str(b, jstr(ns, "dialect"));
    }
    if (jbool(ns, "interposer", 0))
    {
        put_count(b, ns, "allocationsInRun", "allocations");
        put_count(b, ns, "locksInRun", "locks");
        put_count(b, ns, "syscallsInRun", "syscalls");
    }
    sb_printf(b, "}");
}

/* lv2_measure's measurement line: the grid point of its rate and block, with what run() did under the interposer, and
 * its note sweep, and the plugin's behaviour over the pass (lifecycles, threads, the features it requires); a
 * translation, no judgement */
static void put_lv2_measure(sb_t *b, const jnode_t *m, long rate, unsigned quantum)
{
    const jnode_t *rt = jget(m, "rtSafety"), *ev = jget(rt, "events"), *life = jget(m, "lifecycle"), *th = jget(m, "threads"),
                  *req = jget(m, "requiredFeatures");
    size_t k;

    sb_printf(b, ",\n  \"grid\": [\n    {\"rate\": %ld, \"quantum\": %u, \"outcome\": \"%s\"", rate, quantum, OUT_OK);
    if (rt)
    {
        sb_printf(b, ", \"rtSafety\": {\"interposer\": %s", jbool(rt, "interposer", 0) ? "true" : "false");
        sb_printf(b, ", \"swept\": %s, \"sweepApplicable\": %s", jbool(rt, "swept", 0) ? "true" : "false",
                  jbool(rt, "sweepApplicable", 0) ? "true" : "false");
        put_count(b, rt, "blocks", "blocks");
        put_count(b, rt, "allocationsInRun", "allocations");
        put_count(b, rt, "locksInRun", "locks");
        put_count(b, rt, "syscallsInRun", "syscalls");
        if (ev && ev->type == J_ARR)
        {
            sb_printf(b, ", \"events\": [");
            for (k = 0; k < ev->n; k++)
            {
                char text[512];
                const char *kind = jstr(ev->kid[k], "kind"), *module = jstr(ev->kid[k], "module"), *symbol = jstr(ev->kid[k], "symbol");

                snprintf(text, sizeof(text), "%s %s %s", kind ? kind : "?", module ? module : "?", symbol ? symbol : "?");
                sb_printf(b, "%s", k ? ", " : "");
                sb_str(b, text);
            }
            sb_printf(b, "]");
        }
        sb_printf(b, "}");
        if (jget(rt, "noteSweep"))
            put_note_sweep(b, jget(rt, "noteSweep"));
    }
    sb_printf(b, "}\n  ],\n  \"behaviour\": {");
    if (life)
    {
        double c = 0, i = 0, f = 0;

        jnum(life, "cycles", &c);
        jnum(life, "instantiated", &i);
        jnum(life, "failed", &f);
        sb_printf(b, "\"lifecycle\": {\"cycles\": %.0f, \"instantiated\": %.0f, \"failed\": %.0f}, ", c, i, f);
    }
    sb_printf(b, "\"threads\": {");
    {
        sb_t t = { 0 };

        put_count(&t, th, "before", "before");
        put_count(&t, th, "afterFirstInstantiate", "afterFirstInstantiate");
        put_count(&t, th, "afterAllFreed", "afterAllFreed");
        sb_printf(b, "%s", t.len > 2 ? t.s + 2 : "");
        free(t.s);
    }
    sb_printf(b, "}, \"features\": {\"required\": [");
    for (k = 0; req && req->type == J_ARR && k < req->n; k++)
    {
        sb_printf(b, "%s", k ? ", " : "");
        sb_str(b, req->kid[k]->str ? req->kid[k]->str : "");
    }
    sb_printf(b, "]}}");
}

/* the cost arm's figures at one rate, as that rate's point carries them: nanoseconds per sample, and for an instrument
 * the notes it held; a rate the arm did not time (an unmeasuredReason in place of the figures) gets no cost, never a
 * neighbour's */
static void put_cost(sb_t *b, const jnode_t *cost, const char *rate)
{
    const jnode_t *at = jget(jget(cost, "perRate"), rate), *voices = jget(at, "voices");
    double median, p95, min, max, blocks, warmup, percentile, held, capacity;

    if (!jnum(at, "nsPerSampleMedian", &median) || !jnum(at, "nsPerSampleP95", &p95) ||
        !jnum(at, "nsPerSampleMin", &min) || !jnum(at, "nsPerSampleMax", &max) || !jnum(at, "blocks", &blocks) ||
        !jnum(cost, "warmupBlocks", &warmup) || !jnum(cost, "percentile", &percentile))
        return;
    sb_printf(b, ", \"cost\": {\"unit\": \"ns-per-sample\", \"median\": %.9g, \"percentile\": {\"p\": %.9g, \"value\": %.9g}, "
                 "\"min\": %.9g, \"max\": %.9g, \"blocks\": %.0f, \"warmupBlocks\": %.0f",
              median, percentile, p95, min, max, blocks, warmup);
    if (jnum(voices, "held", &held) && jstr(voices, "basis"))
    {
        sb_printf(b, ", \"voices\": {\"held\": %.0f, \"basis\": ", held);
        sb_str(b, jstr(voices, "basis"));
        if (jnum(voices, "capacity", &capacity))
            sb_printf(b, ", \"capacity\": %.0f", capacity);
        sb_printf(b, "}");
    }
    sb_printf(b, "}");
}

/* the rates a run measures at when it is given none: omx-contract's ORACLE_FLOOR_RATES, every kernel oracle's floor */
static const unsigned g_floor_rates[] = OMX_ORACLE_FLOOR_RATES_INIT;

static const char *floor_rates(void)
{
    static char text[16 * sizeof(g_floor_rates) / sizeof(g_floor_rates[0])];
    size_t n, used = 0;

    for (n = 0; n < sizeof(g_floor_rates) / sizeof(g_floor_rates[0]) && used < sizeof(text); n++)
        used += snprintf(text + used, sizeof(text) - used, "%s%u", n ? "," : "", g_floor_rates[n]);
    return text;
}

static const char *base_name(const char *path)
{
    const char *s = strrchr(path, '/');

    return s ? s + 1 : path;
}

int main(int argc, char **argv)
{
    options_t o = { .child = "clap-qualify", .rates = floor_rates(), .quantum = 512, .reason = "on-request",
                    .set = "default", .wall_s = 600, .cpu_s = 540, .files = 256, .data_bytes = 4LL << 30,
                    .file_bytes = 64LL << 20, .grace_ms = 300 };
    int a = 1, pin_option = 0, exit_code = 0, i, rc;
    cpu_set_t pinned;
    char realpath_buf[PATH_MAX], sha[PHD_SHA256_HEX_LEN + 1], cpus_text[256] = "", run_id[96], started[40];
    struct stat st;
    time_t started_at;
    long t0;
    run_t r;
    sb_t doc = { 0 };
    jnode_t *line = NULL;
    const char *run_outcome = OUT_OK;
    /* an LV2 plugin, lv2:<uri>: the runner runs lv2_measure's passes, the pin then the measurement */
    const char *lv2_uri = NULL;
    jnode_t *pin_line = NULL, *measure_line = NULL;
    const jnode_t *lv2_library = NULL;
    long lv2_rate = 0;
    int child_set = 0;
    int complete = 1, fd;

    if (argc < 2 || strcmp(argv[1], "run"))
    {
        fprintf(stderr, "usage: " RUNNER_NAME " run [options] <plugin.clap> [<clap id>]\n"
                        "       " RUNNER_NAME " run [options] lv2:<uri>\n"
                        "  --child PROGRAM      the program that loads the plugin (default clap-qualify; " PROBE_LV2_CHILD " for lv2:)\n"
                        "  --rates R,R,...      sample rates (default %s)\n"
                        "  --quantum N          block size in frames (default 512)     --blocks N   blocks per rate\n"
                        "  --offer EXT,...      host extensions to offer on top of the child's own\n"
                        "  --probe-notes N      notes a CLAP instrument declaring no voice capacity is timed holding\n"
                        "  --hold N             notes a CLAP instrument is timed holding, whatever it declares\n"
                        "  --out FILE           the document, written atomically (default stdout)\n"
                        "  --log FILE           the child's stderr (default discarded)\n"
                        "  --reason WHY         add, rescan, binary-changed, on-request, auto-measure, reference, ci\n"
                        "  --wall-s N  --cpu-s N  --data-bytes N  --files N  --file-bytes N  --grace-ms N\n"
                        "  --cpus LIST          pin the child to these cpus (\"0-3,8\")\n"
                        "  --require LIMIT      refuse to run unless the limit is applied (repeatable)\n", floor_rates());
        return 2;
    }
    for (a = 2; a < argc; a++)
    {
        const char *k = argv[a];
        const char *v = a + 1 < argc ? argv[a + 1] : NULL;

        if (k[0] != '-')
            break;
        if (v == NULL)
        {
            fprintf(stderr, RUNNER_NAME ": %s needs a value\n", k);
            return 2;
        }
        a++;
        if (!strcmp(k, "--child")) o.child = v, child_set = 1;
        else if (!strcmp(k, "--rates")) o.rates = v;
        else if (!strcmp(k, "--quantum")) o.quantum = (unsigned)atoi(v);
        else if (!strcmp(k, "--blocks")) o.blocks = (unsigned)atoi(v);
        else if (!strcmp(k, "--offer")) o.offer = v;
        else if (!strcmp(k, "--probe-notes") || !strcmp(k, "--hold"))
        {
            char *end;
            long n = strtol(v, &end, 10);

            /* how many the prober can hold is the prober's to say: a count it refuses ends its run as any refusal does */
            if (*end || n < 1 || n > INT_MAX)
            {
                fprintf(stderr, RUNNER_NAME ": %s takes a positive count of notes\n", k);
                return 2;
            }
            *(k[2] == 'p' ? &o.probe_notes : &o.hold) = (unsigned)n;
        }
        else if (!strcmp(k, "--out")) o.out = v;
        else if (!strcmp(k, "--log")) o.log = v;
        else if (!strcmp(k, "--reason")) o.reason = v;
        else if (!strcmp(k, "--wall-s")) o.wall_s = atol(v);
        else if (!strcmp(k, "--cpu-s")) o.cpu_s = atol(v);
        else if (!strcmp(k, "--data-bytes")) o.data_bytes = atoll(v);
        else if (!strcmp(k, "--files")) o.files = atol(v);
        else if (!strcmp(k, "--file-bytes")) o.file_bytes = atoll(v);
        else if (!strcmp(k, "--grace-ms")) o.grace_ms = atol(v);
        else if (!strcmp(k, "--cpus")) o.cpus = v;
        else if (!strcmp(k, "--require"))
        {
            if (o.nrequire == 16)
                return 2;
            snprintf(o.require[o.nrequire++], sizeof(o.require[0]), "%s", v);
        }
        else
        {
            fprintf(stderr, RUNNER_NAME ": unknown option %s\n", k);
            return 2;
        }
    }
    if (a >= argc || o.quantum == 0 || o.wall_s <= 0 || o.cpu_s <= 0)
    {
        fprintf(stderr, RUNNER_NAME ": a plugin file and positive limits are needed\n");
        return 2;
    }
    o.plugin = argv[a++];
    if (a < argc)
        o.id = argv[a++];
    if (!reason_known(o.reason))
    {
        fprintf(stderr, RUNNER_NAME ": --reason %s is not one of the reasons of the format\n", o.reason);
        return 2;
    }
    if (!strncmp(o.plugin, PROBE_LV2_PREFIX, strlen(PROBE_LV2_PREFIX)))
    {
        char *end;

        lv2_uri = o.plugin + strlen(PROBE_LV2_PREFIX);
        if (!child_set)
            o.child = PROBE_LV2_CHILD;
        /* today's LV2 pass measures at the highest rate asked for */
        for (end = (char *)o.rates; *end;)
        {
            long v = strtol(end, &end, 10);

            if (v > lv2_rate)
                lv2_rate = v;
            if (*end == ',')
                end++;
            else if (*end)
                break;
        }
        if (!*lv2_uri || lv2_rate <= 0)
        {
            fprintf(stderr, RUNNER_NAME ": %s: an LV2 plugin is lv2:<uri>, measured at a positive rate\n", o.plugin);
            return 2;
        }
    }
    else if (stat(o.plugin, &st) != 0 || !S_ISREG(st.st_mode) || realpath(o.plugin, realpath_buf) == NULL)
    {
        fprintf(stderr, RUNNER_NAME ": %s: " "%s\n", o.plugin, OUT_NOT_FOUND);
        return 3;
    }
    fd = lv2_uri ? -1 : open(realpath_buf, O_RDONLY | O_CLOEXEC);
    if (!lv2_uri && (fd < 0 || phd_pin_fd_digest(fd, sha) != 0))
    {
        fprintf(stderr, RUNNER_NAME ": %s: cannot be read\n", realpath_buf);
        return 2;
    }
    if (fd >= 0)
        close(fd);

    sched_getaffinity(0, sizeof(pinned), &pinned);
    if (o.cpus)
    {
        int list[CPU_SETSIZE], n = parse_cpu_list(o.cpus, list, CPU_SETSIZE), k;
        cpu_set_t want;

        if (n <= 0)
        {
            fprintf(stderr, RUNNER_NAME ": --cpus %s is not a cpu list\n", o.cpus);
            return 2;
        }
        CPU_ZERO(&want);
        for (k = 0; k < n; k++)
            CPU_SET(list[k], &want);
        pinned = want;
        pin_option = 1;
    }
    cpu_list_text(&pinned, cpus_text, sizeof(cpus_text));
    if (list_limits(&o, pin_option, cpus_text) != 0)
        return 2;

    signal(SIGPIPE, SIG_IGN);
    {
        struct sigaction sa = { .sa_handler = on_cancel };

        sigaction(SIGTERM, &sa, NULL);
        sigaction(SIGINT, &sa, NULL);
    }
    prctl(PR_SET_CHILD_SUBREAPER, 1);

    started_at = time(NULL);
    iso_time(started_at, started, sizeof(started));
    {
        struct tm tm;
        char compact[24];
        unsigned salt = 0;

        gmtime_r(&started_at, &tm);
        strftime(compact, sizeof(compact), "%Y%m%dT%H%M%SZ", &tm);
        /* no host name: the id leaves the machine in the document */
        if (getrandom(&salt, sizeof(salt), 0) != (ssize_t)sizeof(salt))
            salt = (unsigned)now_ms();
        snprintf(run_id, sizeof(run_id), "%s-%x-%08x", compact, (unsigned)getpid(), salt);
    }

    t0 = now_ms();
    if (o.log)
    {
        int lfd = open(o.log, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);

        if (lfd >= 0)
            close(lfd);
    }
    memset(&r, 0, sizeof(r));
    read_idle(g_idle_before, &g_nidle, &pinned);
    if (lv2_uri)
    {
        if (run_lv2(&o, lv2_uri, lv2_rate, &pinned, pin_option, t0 + o.wall_s * 1000, &r, &pin_line, &measure_line,
                    &lv2_library, &run_outcome, &complete) == 3)
            return 3;
        if (lv2_library == NULL)
        {
            /* the document needs a binary with its digest and none can be named: refused by its code, never a guess */
            fprintf(stderr, RUNNER_NAME ": %s: %s: %s; no document, it would have no binary\n", o.plugin, run_outcome,
                    g_nsteps && g_steps[g_nsteps - 1].detail[0] ? g_steps[g_nsteps - 1].detail : "nothing was pinned");
            return 2;
        }
    }
    else
    {
        char *argv_child[32];

        add_step("hash", OUT_OK, now_ms() - t0);
        clap_argv(&o, argv_child);
        /* the CLAP prober counts under the interposer beside it, as the LV2 measurement does */
        preload_for_measurement(o.child);
        run_child(&o, argv_child, &pinned, pin_option, &r, t0 + o.wall_s * 1000);
        preload_restore();
        run_outcome = child_end("lifecycle", &o, &r, &complete);
    }
    read_idle(g_idle_after, &g_nidle, &pinned);

    /* the child's facts, when it printed them */
    if (!lv2_uri && r.out.len > 0)
    {
        r.out.s[strcspn(r.out.s, "\n")] = '\0';
        line = jparse(r.out.s);
    }

    /* the document */
    {
        const char *plugin_id = line ? jstr(line, "id") : NULL;
        const jnode_t *clap = jget(line, "clap"), *integ = jget(line, "integrity"), *rt = jget(line, "rtSafety"),
                      *notes = jget(line, "noteSweep"), *latency = jget(clap, "latency"), *ext = jget(line, "hostExtensions"),
                      *cost = jget(line, "cost");
        const char *layout_sha = NULL, *unmeasured = NULL;
        int firstpoint = 1;
        size_t k;

        if (integ)
        {
            const jnode_t *layout = jget(integ, "layout");

            layout_sha = jstr(layout, "sha256");
            unmeasured = jstr(integ, "unmeasuredReason");
        }
        /* what the child's line says about the plugin, as steps and grid points */
        if (line && clap && r.records == 0)
        {
            step_t *s = add_step("instantiate", jbool(clap, "headlessOk", 0) ? OUT_OK : OUT_REFUSED_INSTANTIATION, 0);

            set_detail(s, "read from the child's line");
            if (!jbool(clap, "headlessOk", 0) || (unmeasured && !strcmp(unmeasured, "refused-instantiation")))
                s->outcome = OUT_REFUSED_INSTANTIATION;
            else if (unmeasured && !strcmp(unmeasured, "not-installed"))
                s->outcome = OUT_NOT_FOUND;
            if (latency)
                for (k = 0; k < latency->n; k++)
                {
                    double decl = 0, meas = 0;
                    step_t *l = add_step("latency", OUT_OK, 0);

                    l->rate = atol(latency->key[k]);
                    l->quantum = o.quantum;
                    set_detail(l, "read from the child's line");
                    jnum(latency->kid[k], "declaredFrames", &decl);
                    jnum(latency->kid[k], "measuredFrames", &meas);
                }
            if (rt && jbool(rt, "interposer", 0))
            {
                step_t *x = add_step("rt-safety", OUT_OK, 0);

                set_detail(x, "%s", with_dropped("counts are totals over every rate, read from the child's line"));
            }
            else if (rt)
            {
                step_t *x = add_step("rt-safety", OUT_NOT_ATTEMPTED, 0);

                set_detail(x, "%s", with_dropped(no_interposer_reason()));
            }
            {
                int counted = jbool(notes, "applicable", 0) && jbool(notes, "interposer", 0);
                step_t *x = add_step("note-sweep", counted ? OUT_OK : OUT_NOT_ATTEMPTED, 0);

                if (!jbool(notes, "applicable", 0))
                    set_detail(x, "no note input");
                else if (counted)
                    set_detail(x, "counts are totals over every rate, read from the child's line");
                else
                    set_detail(x, "the notes played uncounted: %s", no_interposer_reason());
            }
        }
        for (i = 0; i < g_nsteps; i++)
            if (!outcome_ok(g_steps[i].outcome) && !strcmp(run_outcome, OUT_OK))
            {
                run_outcome = g_steps[i].outcome;
                complete = 0;
            }

        sb_printf(&doc, "{\n  \"format\": \"%s\",\n  \"formatVersion\": \"%d.%d\",\n  \"run\": {\n", PHD_PROBE_FORMAT, PHD_PROBE_FORMAT_MAJOR,
                  PHD_PROBE_FORMAT_MINOR);
        sb_printf(&doc, "    \"id\": ");
        sb_str(&doc, run_id);
        sb_printf(&doc, ",\n    \"startedAt\": \"%s\",\n    \"elapsedMs\": %ld,\n    \"complete\": %s,\n    \"outcome\": \"%s\",\n", started,
                  now_ms() - t0, complete ? "true" : "false", run_outcome);
        if (r.cancelled)
            sb_printf(&doc, "    \"cancelledBy\": \"client\",\n");
        sb_printf(&doc, "    \"reason\": \"%s\",\n    \"protocol\": {\"name\": \"%s\", \"version\": %d},\n", o.reason, PHD_PROBE_PROTOCOL_NAME,
                  PHD_PROBE_PROTOCOL_VERSION);
        sb_printf(&doc, "    \"tools\": {\"runner\": \"" RUNNER_NAME " %s\", \"child\": ", PROBE_VERSION);
        sb_str(&doc, base_name(o.child));
        /* the interposer is named when it was preloaded and the child says it counted under it */
        if (g_interposer[0] && jbool(lv2_uri ? jget(measure_line, "rtSafety") : rt, "interposer", 0))
        {
            sb_printf(&doc, ", \"interposer\": ");
            sb_str(&doc, base_name(g_interposer));
        }
        if (g_dropped_preload[0])
        {
            sb_printf(&doc, ", \"droppedPreload\": ");
            sb_str(&doc, g_dropped_preload);
        }
        sb_printf(&doc, "},\n    \"via\": \"runner\"\n  },\n  \"plugin\": {\"format\": \"%s\", \"id\": ", lv2_uri ? "lv2" : "clap");
        if (lv2_uri)
        {
            const jnode_t *integ_lv2 = jget(pin_line, "integrity"), *files = jget(integ_lv2, "files");

            sb_str(&doc, lv2_uri);
            if (jstr(pin_line, "version"))
            {
                sb_printf(&doc, ", \"version\": ");
                sb_str(&doc, jstr(pin_line, "version"));
            }
            /* the plugin's library is the binary; every file of the pin is listed, each with its digest */
            sb_printf(&doc, "},\n  \"binary\": {\"path\": ");
            sb_str(&doc, jstr(lv2_library, "path"));
            sb_printf(&doc, ", \"sha256\": ");
            sb_str(&doc, jstr(lv2_library, "sha256"));
            sb_printf(&doc, ", \"files\": [");
            for (k = 0; files && k < files->n; k++)
            {
                sb_printf(&doc, "%s{\"path\": ", k ? ", " : "");
                sb_str(&doc, jstr(files->kid[k], "path") ? jstr(files->kid[k], "path") : "");
                sb_printf(&doc, ", \"sha256\": ");
                sb_str(&doc, jstr(files->kid[k], "sha256") ? jstr(files->kid[k], "sha256") : "");
                sb_printf(&doc, "}");
            }
            sb_printf(&doc, "]");
            layout_sha = jstr(jget(integ_lv2, "layout"), "sha256");
        }
        else
        {
            sb_str(&doc, plugin_id ? plugin_id : o.id ? o.id : base_name(realpath_buf));
            sb_printf(&doc, "},\n  \"binary\": {\"path\": ");
            sb_str(&doc, realpath_buf);
            sb_printf(&doc, ", \"sha256\": \"%s\", \"files\": [{\"path\": ", sha);
            sb_str(&doc, base_name(o.plugin));
            sb_printf(&doc, ", \"sha256\": \"%s\"}]", sha);
        }
        if (layout_sha && strlen(layout_sha) == PHD_SHA256_HEX_LEN)
            sb_printf(&doc, ", \"layout\": {\"scheme\": \"%s\", \"sha256\": \"%s\"}", PHD_PIN_LAYOUT_SCHEME, layout_sha);
        if (unmeasured && !strcmp(unmeasured, "unpinnable"))
        {
            const char *detail = jstr(integ, "unmeasuredDetail");

            sb_printf(&doc, ", \"unpinnable\": ");
            sb_str(&doc, detail ? detail : "the files cannot be pinned");
        }
        sb_printf(&doc, "}");
        put_machine(&doc, &pinned, pin_option);
        sb_printf(&doc, ",\n  \"offer\": {\"id\": \"%s\"", o.offer ? "custom" : "default");
        if (ext && ext->type == J_ARR)
        {
            sb_printf(&doc, ", \"clapExtensions\": [");
            for (k = 0; k < ext->n; k++)
            {
                sb_printf(&doc, "%s", k ? ", " : "");
                sb_str(&doc, ext->kid[k]->str ? ext->kid[k]->str : "");
            }
            sb_printf(&doc, "]");
        }
        sb_printf(&doc, ", \"realtime\": \"" OMX_RESOURCE_THREAD_SCHEDULING_NONE "\"},\n  \"limits\": {\"set\": ");
        sb_str(&doc, o.set);
        sb_printf(&doc, ",\n    \"applied\": [");
        for (i = 0; i < g_napplied; i++)
        {
            const applied_t *ap = &g_applied[i];

            sb_printf(&doc, "%s\n      {\"limit\": \"%s\"", i ? "," : "", ap->name);
            if (ap->has_value)
                sb_printf(&doc, ", \"value\": %lld", ap->value);
            else if (ap->str[0])
            {
                sb_printf(&doc, ", \"value\": ");
                sb_str(&doc, ap->str);
            }
            if (ap->unit)
                sb_printf(&doc, ", \"unit\": \"%s\"", ap->unit);
            sb_printf(&doc, ", \"by\": \"%s\"}", ap->by);
        }
        sb_printf(&doc, "\n    ],\n    \"unavailable\": [");
        for (i = 0; i < g_nunavailable; i++)
            sb_printf(&doc, "%s\n      {\"limit\": \"%s\", \"code\": \"%s\"}", i ? "," : "", g_unavailable[i].name, g_unavailable[i].code);
        sb_printf(&doc, "%s]\n  },\n  \"steps\": [", g_nunavailable ? "\n    " : "");
        for (i = 0; i < g_nsteps; i++)
        {
            sb_printf(&doc, "%s\n    ", i ? "," : "");
            put_step(&doc, &g_steps[i]);
        }
        sb_printf(&doc, "\n  ]");
        /* the grid: one point per rate the child reported a latency for, with the cost the child timed at that rate */
        if (latency && latency->n)
        {
            sb_printf(&doc, ",\n  \"grid\": [");
            for (k = 0; k < latency->n && k < MAX_POINTS; k++)
            {
                double decl = 0, meas = 0;
                int from_note;

                jnum(latency->kid[k], "declaredFrames", &decl);
                jnum(latency->kid[k], "measuredFrames", &meas);
                /* an instrument has no input for the impulse: its onset is measured from a note, which may not sound */
                from_note = jstr(latency->kid[k], "from") && !strcmp(jstr(latency->kid[k], "from"), "note");
                sb_printf(&doc, "%s\n    {\"rate\": %ld, \"quantum\": %u, \"outcome\": \"%s\", \"latency\": {\"declaredFrames\": %.0f, "
                                "\"measuredFrames\": %.0f, \"method\": \"%s\"",
                          k ? "," : "", atol(latency->key[k]), o.quantum, OUT_OK, decl, meas,
                          from_note ? OMX_MEASUREMENT_LATENCY_METHODS_NOTE_ONSET : OMX_MEASUREMENT_LATENCY_METHODS_IMPULSE_ONSET);
                if (from_note)
                    sb_printf(&doc, ", \"heard\": %s", jbool(latency->kid[k], "heard", 1) ? "true" : "false");
                sb_printf(&doc, "}");
                put_cost(&doc, cost, latency->key[k]);
                if (firstpoint && rt)
                {
                    double v = 0;
                    const jnode_t *ev = jget(rt, "events");

                    sb_printf(&doc, ", \"rtSafety\": {\"interposer\": %s", jbool(rt, "interposer", 0) ? "true" : "false");
                    if (jbool(rt, "interposer", 0))
                    {
                        sb_printf(&doc, ", \"swept\": %s, \"sweepApplicable\": %s", jbool(rt, "swept", 0) ? "true" : "false",
                                  jbool(rt, "sweepApplicable", 0) ? "true" : "false");
                        if (jnum(rt, "blocks", &v))
                            sb_printf(&doc, ", \"blocks\": %.0f", v);
                        if (jnum(rt, "allocationsInRun", &v))
                            sb_printf(&doc, ", \"allocations\": %.0f", v);
                        if (jnum(rt, "locksInRun", &v))
                            sb_printf(&doc, ", \"locks\": %.0f", v);
                        if (jnum(rt, "syscallsInRun", &v))
                            sb_printf(&doc, ", \"syscalls\": %.0f", v);
                        if (jnum(clap, "threadViolations", &v))
                            sb_printf(&doc, ", \"threadViolations\": %.0f", v);
                        if (jnum(clap, "processErrors", &v))
                            sb_printf(&doc, ", \"processErrors\": %.0f", v);
                        if (ev && ev->type == J_ARR)
                        {
                            size_t e;

                            sb_printf(&doc, ", \"events\": [");
                            for (e = 0; e < ev->n; e++)
                            {
                                sb_printf(&doc, "%s", e ? ", " : "");
                                sb_str(&doc, ev->kid[e]->str ? ev->kid[e]->str : "");
                            }
                            sb_printf(&doc, "]");
                        }
                    }
                    sb_printf(&doc, "}");
                    if (notes)
                        put_note_sweep(&doc, notes);
                    firstpoint = 0;
                }
                sb_printf(&doc, "}");
            }
            sb_printf(&doc, "\n  ]");
        }
        if (lv2_uri && measure_line && jbool(measure_line, "instantiated", 0))
            put_lv2_measure(&doc, measure_line, lv2_rate, o.quantum);
        if (WIFSIGNALED(r.status) && !r.killed_by_deadline && !r.cancelled)
        {
            sb_printf(&doc, ",\n  \"crash\": {\"signal\": \"%s\"}", signal_name(WTERMSIG(r.status)));
        }
        if (o.log)
        {
            struct stat ls;
            char lsha[PHD_SHA256_HEX_LEN + 1];
            int lfd = open(o.log, O_RDONLY | O_CLOEXEC);

            if (lfd >= 0 && fstat(lfd, &ls) == 0 && phd_pin_fd_digest(lfd, lsha) == 0)
            {
                sb_printf(&doc, ",\n  \"logs\": [{\"name\": \"stderr\", \"path\": ");
                sb_str(&doc, o.log);
                sb_printf(&doc, ", \"sha256\": \"%s\", \"bytes\": %lld}]", lsha, (long long)ls.st_size);
            }
            if (lfd >= 0)
                close(lfd);
        }
        sb_printf(&doc, "\n}\n");
    }

    for (i = 0; i < g_nsteps; i++)
        if (!outcome_ok(g_steps[i].outcome))
            exit_code = 1;
    if (!complete)
        exit_code = 1;

    if (o.out)
    {
        char tmp[PATH_MAX];
        FILE *f;

        snprintf(tmp, sizeof(tmp), "%s.%d.tmp", o.out, (int)getpid());
        f = fopen(tmp, "w");
        if (f == NULL || fwrite(doc.s, 1, doc.len, f) != doc.len || fclose(f) != 0 || rename(tmp, o.out) != 0)
        {
            fprintf(stderr, RUNNER_NAME ": cannot write %s: %s\n", o.out, strerror(errno));
            unlink(tmp);
            return 2;
        }
    }
    else
        fwrite(doc.s, 1, doc.len, stdout);
    rc = exit_code;
    return rc;
}

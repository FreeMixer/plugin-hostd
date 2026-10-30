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

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <host-errors.h>
#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

#include "describe.h"
#include "descriptors.h"
#include "formats.h"
#include "json.h"
#include "pins.h"
#include "proc.h"
#include "supervisor.h"

/* one scan, by the files it describes, in two stages: the descriptor (describe), then, once it is in place, the panel
 * filed under its name (panel). Running while pid > 0; code is the descriptor's SUCCESS or the code it ended with,
 * panel_code the panel's */
typedef struct SCAN_T {
    char format[16];
    char *id;
    char hash[PHD_DESCRIPTOR_HASH_LEN + 1];
    char *uri;
    char *target;
    char name[PATH_MAX];
    char tmp[PATH_MAX];
    char log[PATH_MAX];
    pid_t pid;
    int panel;
    int code, panel_code;
} scan_t;

static conf_t *g_conf;
static scan_t *g_scans;
static int g_nscans;
static unsigned g_seq;

/* ---------------------------------------------------------------- the directories */

static void state_default(char *dir, size_t size, const char *subdir)
{
    const char *state = getenv("XDG_STATE_HOME"), *home = getenv("HOME");

    if (state && *state)
        snprintf(dir, size, "%s/%s", state, subdir);
    else if (geteuid() == 0 || !home || !*home)
        snprintf(dir, size, PHD_DIR_SYSTEM_STATE_HOME "/%s", subdir);
    else
        snprintf(dir, size, "%s/" PHD_DIR_USER_STATE_HOME "/%s", home, subdir);
}

/* the directory and its parents, each made PHD_DIR_MODE when missing; 0, or -1 with errno */
static int make_dirs(const char *path)
{
    char buf[PATH_MAX], *slash;
    struct stat st;

    if (snprintf(buf, sizeof(buf), "%s", path) >= (int)sizeof(buf))
    {
        errno = ENAMETOOLONG;
        return -1;
    }
    for (slash = buf + 1; (slash = strchr(slash, '/')); slash++)
    {
        *slash = '\0';
        if (mkdir(buf, PHD_DIR_MODE) != 0 && errno != EEXIST)
            return -1;
        *slash = '/';
    }
    if (mkdir(buf, PHD_DIR_MODE) != 0 && errno != EEXIST)
        return -1;
    if (stat(buf, &st) != 0)
        return -1;
    if (!S_ISDIR(st.st_mode))
    {
        errno = ENOTDIR;
        return -1;
    }
    return 0;
}

/* whether a file can be made in the directory: a write is tried, which a read-only mount refuses even to root */
static int writable(const char *dir)
{
    char probe[PATH_MAX];
    int fd;

    snprintf(probe, sizeof(probe), "%s/.plugin-hostd-write.%d", dir, (int)getpid());
    fd = open(probe, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0)
        return -1;
    close(fd);
    unlink(probe);
    return 0;
}

static int dir_ready(const char *key, char *dir, size_t size, const char *subdir)
{
    if (!*dir)
        state_default(dir, size, subdir);
    if (make_dirs(dir) != 0 || writable(dir) != 0)
    {
        fprintf(stderr, "plugin-hostd: %s %s: %s: resp %d\n", key, dir, strerror(errno), OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP);
        return OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP;
    }
    return SUCCESS;
}

int descriptors_init(conf_t *conf)
{
    g_conf = conf;
    if (dir_ready("descriptor_dir", conf->descriptor_dir, sizeof(conf->descriptor_dir), PHD_DIR_DESCRIPTORS_SUBDIR))
        return OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP;
    if (dir_ready("qualification_dir", conf->qualification_dir, sizeof(conf->qualification_dir),
                  PHD_DIR_QUALIFICATION_SUBDIR))
        return OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP;
    return SUCCESS;
}

/* ---------------------------------------------------------------- what a plugin's files are */

/* every character outside [A-Za-z0-9._-] as PHD_DESCRIPTOR_SAFE_CHAR, as plugin-qualify's scanners write it */
static void encode(const char *in, char *out, size_t size)
{
    size_t o = 0;

    for (; *in && o + 1 < size; in++)
    {
        unsigned char c = (unsigned char)*in;

        out[o++] = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' ||
                   c == '_' || c == '-' ? (char)c : PHD_DESCRIPTOR_SAFE_CHAR;
    }
    out[o] = '\0';
}

/* The scan's target (describe's clap:<path>#<id> or lv2:<uri>), its format, id and the hash of its binary as it is
 * now. 0, or -1 for a plugin whose binary cannot be found or read, or a format with no binary or that describe does
 * not know. */
static int identify(const char *uri, char *target, size_t tsize, const char **format, const char **id,
                    char hash[PHD_DESCRIPTOR_HASH_LEN + 1])
{
    const char *fwd;
    int fmt = format_of_uri(uri, &fwd), fd, rc = -1;
    const format_t *f = fmt >= 0 ? format_at(fmt) : NULL;
    char binary[PATH_MAX], hex[PHD_SHA256_HEX_LEN + 1];
    struct stat st;

    if (!f || !f->binary)
        return -1;
    if (f->prefix && strncmp(fwd, f->prefix, strlen(f->prefix)))
        snprintf(target, tsize, "%s%s", f->prefix, fwd);
    else
        snprintf(target, tsize, "%s", fwd);
    if ((*format = describe_format(target)) == NULL || (*id = describe_id(target)) == NULL)
        return -1;
    if (f->binary(fwd, f->search ? f->search(g_conf) : NULL, binary, sizeof(binary)) != 0)
        return -1;
    if ((fd = open(binary, O_RDONLY | O_CLOEXEC)) < 0)
        return -1;
    if (fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && phd_pin_fd_digest(fd, hex) == 0)
    {
        snprintf(hash, PHD_DESCRIPTOR_HASH_LEN + 1, "%s", hex);
        rc = 0;
    }
    close(fd);
    return rc;
}

/* the descriptor of the binary, by its name's id and hash, into path; 0, or -1 when there is none */
static int lookup(const char *id, const char *hash, char *path, size_t size)
{
    const char *dir = g_conf->descriptor_dir;
    char prefix[PATH_MAX], suffix[PHD_DESCRIPTOR_HASH_LEN + 8];
    size_t plen, slen;
    struct dirent *e;
    DIR *d;
    int found = -1;

    encode(id, prefix, sizeof(prefix) - 1);
    strcat(prefix, "@");
    snprintf(suffix, sizeof(suffix), "-%s.json", hash);
    plen = strlen(prefix);
    slen = strlen(suffix);
    if ((d = opendir(dir)) == NULL)
        return -1;
    while (found && (e = readdir(d)) != NULL)
    {
        size_t len = strlen(e->d_name);

        if (len > plen + slen && !strncmp(e->d_name, prefix, plen) && !strcmp(e->d_name + len - slen, suffix))
        {
            snprintf(path, size, "%s/%s", dir, e->d_name);
            found = 0;
        }
    }
    closedir(d);
    return found;
}

static scan_t *scan_of(const char *format, const char *id, const char *hash)
{
    int n;

    for (n = 0; n < g_nscans; n++)
        if (!strcmp(g_scans[n].format, format) && !strcmp(g_scans[n].id, id) && !strcmp(g_scans[n].hash, hash))
            return &g_scans[n];
    return NULL;
}

/* the panel file of a descriptor's name: <descriptor_dir>/panels/<name> */
static void panel_path(const char *name, char *path, size_t size)
{
    snprintf(path, size, "%s/" PHD_PANEL_SUBDIR "/%s", g_conf->descriptor_dir, name);
}

/* ---------------------------------------------------------------- the scan */

static void scan_failed(scan_t *s, int code, const char *why)
{
    fprintf(stderr, "plugin-hostd: %s: the scan wrote no %s (%s), its log %s: resp %d\n", s->uri,
            s->panel ? "panel" : "descriptor", why, s->log, code);
    if (*s->tmp)
        unlink(s->tmp);
    s->tmp[0] = '\0';
    s->pid = 0;
    if (!s->panel)
        s->code = code;
    s->panel_code = code;
}

/* the stage's child, <probe> describe|panel <target>, its stdout into a file of the directory it is filed in */
static void scan_start(scan_t *s, int panel)
{
    char dir[PATH_MAX];
    int out, log, null;
    pid_t pid;

    s->panel = panel;
    if (!panel)
        s->code = OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING_RESP;
    s->panel_code = OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING_RESP;
    s->tmp[0] = '\0';
    if (panel)
        snprintf(dir, sizeof(dir), "%s/" PHD_PANEL_SUBDIR, g_conf->descriptor_dir);
    else
        snprintf(dir, sizeof(dir), "%s", g_conf->descriptor_dir);
    snprintf(s->log, sizeof(s->log), "%s/scan-%s-%s%s.log", sup_root(), s->format, s->hash, panel ? "-panel" : "");
    if (!proc_have_binary(g_conf->probe))
    {
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP, "the probe is not installed");
        return;
    }
    snprintf(s->tmp, sizeof(s->tmp), "%s/.%s.%d.%u.tmp", dir, s->hash, (int)getpid(), g_seq++);
    if (make_dirs(dir) != 0 || (out = open(s->tmp, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600)) < 0)
    {
        char why[PATH_MAX + 64];

        snprintf(why, sizeof(why), "descriptor_dir %s: %s", dir, strerror(errno));
        s->tmp[0] = '\0';
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP, why);
        return;
    }
    log = open(s->log, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    null = open("/dev/null", O_RDONLY | O_CLOEXEC);
    pid = fork();
    if (pid == 0)
    {
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (getppid() == 1)
            _exit(127);
        dup2(null >= 0 ? null : out, STDIN_FILENO);
        dup2(out, STDOUT_FILENO);
        dup2(log >= 0 ? log : out, STDERR_FILENO);
        signal(SIGPIPE, SIG_DFL);
        execlp(g_conf->probe, g_conf->probe, panel ? "panel" : "describe", s->target, (char *)NULL);
        _exit(127);
    }
    close(out);
    if (log >= 0)
        close(log);
    if (null >= 0)
        close(null);
    if (pid < 0)
    {
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP, strerror(errno));
        return;
    }
    s->pid = pid;
}

/* the target as the probe takes it: a CLAP's path decoded, the id after its # as it is; malloc'd */
static char *probe_target(const char *target)
{
    const char *hash = strrchr(target, '#');
    char encoded[PATH_MAX], path[PATH_MAX], *out;

    if (strncmp(target, "clap:", 5) || !hash || hash - target - 5 >= (long)sizeof(encoded))
        return strdup(target);
    snprintf(encoded, sizeof(encoded), "%.*s", (int)(hash - target - 5), target + 5);
    if (pin_percent_decode(encoded, path, sizeof(path)) != 0)
        return strdup(target);
    out = malloc(strlen(path) + strlen(hash) + 6);
    sprintf(out, "clap:%s%s", path, hash);
    return out;
}

void descriptors_add(const char *uri)
{
    char target[PATH_MAX + 16], hash[PHD_DESCRIPTOR_HASH_LEN + 1], path[PATH_MAX];
    const char *format, *id;
    scan_t *s;

    char panel[PATH_MAX];
    int described;

    if (!g_conf || identify(uri, target, sizeof(target), &format, &id, hash) != 0)
        return;
    /* a descriptor in place with its panel is done; one without (written before the panel stage, or its panel stage
     * failed) has only its panel scanned */
    if ((described = lookup(id, hash, path, sizeof(path)) == 0))
    {
        panel_path(strrchr(path, '/') + 1, panel, sizeof(panel));
        if (access(panel, F_OK) == 0)
            return;
    }
    s = scan_of(format, id, hash);
    if (s && s->pid > 0)
        return;
    if (!s)
    {
        g_scans = realloc(g_scans, (size_t)(g_nscans + 1) * sizeof(scan_t));
        s = &g_scans[g_nscans++];
        memset(s, 0, sizeof(*s));
        snprintf(s->format, sizeof(s->format), "%s", format);
        snprintf(s->hash, sizeof(s->hash), "%s", hash);
        s->id = strdup(id);
    }
    free(s->uri);
    s->uri = strdup(uri);
    free(s->target);
    s->target = probe_target(target);
    if (described)
    {
        snprintf(s->name, sizeof(s->name), "%s", strrchr(path, '/') + 1);
        s->code = SUCCESS;
    }
    scan_start(s, described);
}

/* the scan's stdout as a document of its stage, or NULL: read back, fsync'd */
static jnode_t *scan_output(scan_t *s)
{
    sb_t text = { 0 };
    jnode_t *doc;
    int fd;

    if ((fd = open(s->tmp, O_RDONLY | O_CLOEXEC)) >= 0)
    {
        char buf[65536];
        ssize_t n;

        while ((n = read(fd, buf, sizeof(buf))) > 0)
            sb_put(&text, buf, (size_t)n);
        if (fsync(fd) != 0)
            text.len = 0;
        close(fd);
    }
    doc = text.len ? jparse(text.s) : NULL;
    free(text.s);
    if (doc && (doc->type != J_OBJ || !jget(doc, "plugin") || (s->panel && !jget(doc, "panel"))))
    {
        jfree(doc);
        doc = NULL;
    }
    return doc;
}

/* the scan's file moved into place as final, written once; 0, or -1 with the scan failed */
static int scan_file(scan_t *s, const char *final)
{
    char dir[PATH_MAX], why[64], *slash;
    int fd;

    if (access(final, F_OK) == 0)
        unlink(s->tmp);
    else if (rename(s->tmp, final) != 0)
    {
        snprintf(why, sizeof(why), "%s", strerror(errno));
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP, why);
        return -1;
    }
    else
    {
        snprintf(dir, sizeof(dir), "%s", final);
        if ((slash = strrchr(dir, '/')) != NULL)
            *slash = '\0';
        if ((fd = open(dir, O_RDONLY | O_DIRECTORY | O_CLOEXEC)) >= 0)
        {
            fsync(fd);
            close(fd);
        }
    }
    s->tmp[0] = '\0';
    unlink(s->log);
    return 0;
}

/* the scan's stdout is a descriptor: named for its version and moved into place, written once; then the panel stage
 * starts. The panel stage's stdout is the panel, filed under the descriptor's name. */
static void scan_ended(scan_t *s, int status)
{
    char final[PATH_MAX], enc_id[PATH_MAX / 2], enc_version[256], why[64];
    const char *dir = g_conf->descriptor_dir;
    jnode_t *doc;
    const char *version;

    s->pid = 0;
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
    {
        if (WIFSIGNALED(status))
            snprintf(why, sizeof(why), "killed by signal %d", WTERMSIG(status));
        else
            snprintf(why, sizeof(why), "the probe exited %d", WEXITSTATUS(status));
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP, why);
        return;
    }
    if ((doc = scan_output(s)) == NULL)
    {
        scan_failed(s, OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP, s->panel ? "its output is no panel" : "its output is no descriptor");
        return;
    }
    if (s->panel)
    {
        jfree(doc);
        panel_path(s->name, final, sizeof(final));
        if (scan_file(s, final) == 0)
            s->panel_code = SUCCESS;
        return;
    }
    version = jstr(jget(doc, "plugin"), "version");
    encode(s->id, enc_id, sizeof(enc_id));
    encode(version && *version ? version : PHD_DESCRIPTOR_NO_VERSION, enc_version, sizeof(enc_version));
    jfree(doc);
    snprintf(s->name, sizeof(s->name), "%s@%s-%s.json", enc_id, enc_version, s->hash);
    snprintf(final, sizeof(final), "%s/%s", dir, s->name);
    if (scan_file(s, final) != 0)
        return;
    s->code = SUCCESS;
    scan_start(s, 1);
}

void descriptors_tick(void)
{
    int n, status;

    for (n = 0; n < g_nscans; n++)
        if (g_scans[n].pid > 0 && waitpid(g_scans[n].pid, &status, WNOHANG) == g_scans[n].pid)
            scan_ended(&g_scans[n], status);
}

/* ---------------------------------------------------------------- descriptor_get and panel_get */

/* resp 0 "<path>": the path is one quoted word, as mod-host's tokenizer reads it */
static char *resp_path(const char *path)
{
    char *r, *o;
    const char *p;

    r = malloc(strlen(path) * 2 + 16);
    if (!r)
        return NULL;
    o = r + sprintf(r, "resp 0 \"");
    for (p = path; *p; p++)
    {
        if (*p == '"' || *p == '\\')
            *o++ = '\\';
        *o++ = *p;
    }
    strcpy(o, "\"");
    return r;
}

/* what a scan ended with, for a file that is not there: a scan that wrote one that is gone since wrote none */
static char *resp_missing(const scan_t *s, int code)
{
    return sup_resp(s && code != SUCCESS ? code : OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT_RESP);
}

char *descriptors_get(const char *uri)
{
    char target[PATH_MAX + 16], hash[PHD_DESCRIPTOR_HASH_LEN + 1], path[PATH_MAX];
    const char *format, *id;
    scan_t *s;

    if (!g_conf || identify(uri, target, sizeof(target), &format, &id, hash) != 0)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT_RESP);
    if (lookup(id, hash, path, sizeof(path)) != 0)
    {
        s = scan_of(format, id, hash);
        return resp_missing(s, s ? s->code : SUCCESS);
    }
    return resp_path(path);
}

/* the panel of a descriptor in place, else what its descriptor answers: no panel without a descriptor */
char *descriptors_panel_get(const char *uri)
{
    char target[PATH_MAX + 16], hash[PHD_DESCRIPTOR_HASH_LEN + 1], path[PATH_MAX], panel[PATH_MAX];
    const char *format, *id;
    scan_t *s;

    if (!g_conf || identify(uri, target, sizeof(target), &format, &id, hash) != 0)
        return sup_resp(OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT_RESP);
    s = scan_of(format, id, hash);
    if (lookup(id, hash, path, sizeof(path)) != 0)
        return resp_missing(s, s ? s->code : SUCCESS);
    panel_path(strrchr(path, '/') + 1, panel, sizeof(panel));
    if (access(panel, F_OK) != 0)
        return resp_missing(s, s ? s->panel_code : SUCCESS);
    return resp_path(panel);
}

void descriptors_finish(void)
{
    int n;

    for (n = 0; n < g_nscans; n++)
    {
        if (g_scans[n].pid > 0)
        {
            kill(g_scans[n].pid, SIGTERM);
            waitpid(g_scans[n].pid, NULL, 0);
        }
        if (*g_scans[n].tmp)
            unlink(g_scans[n].tmp);
        free(g_scans[n].id);
        free(g_scans[n].uri);
        free(g_scans[n].target);
    }
    free(g_scans);
    g_scans = NULL;
    g_nscans = 0;
}

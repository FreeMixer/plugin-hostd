/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Linked into the daemon of `make test-plan-refused`: the world check of two or more members cannot be built, while the
 * world of one still can, so a plan the planner forms is refused by segment_refusal. A world links a bundle once, so two
 * members of one plugin would make one link: in the world check no link is ever found made, and each member links. */
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int g_links;

int mkdir(const char *path, mode_t mode)
{
    int (*real)(const char *, mode_t) = (int (*)(const char *, mode_t))dlsym(RTLD_NEXT, "mkdir");

    if (strstr(path, "/world-check"))
        g_links = 0;
    return real(path, mode);
}

int symlink(const char *target, const char *linkpath)
{
    int (*real)(const char *, const char *) = (int (*)(const char *, const char *))dlsym(RTLD_NEXT, "symlink");

    if (strstr(linkpath, "/world-check/") && g_links++)
    {
        errno = EACCES;
        return -1;
    }
    return real(target, linkpath);
}

ssize_t readlink(const char *path, char *buf, size_t size)
{
    ssize_t (*real)(const char *, char *, size_t) = (ssize_t (*)(const char *, char *, size_t))dlsym(RTLD_NEXT, "readlink");

    if (strstr(path, "/world-check/"))
    {
        errno = ENOENT;
        return -1;
    }
    return real(path, buf, size);
}

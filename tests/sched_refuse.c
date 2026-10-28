/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Preloaded into plugin-hostd-probe by tests/probe_test.py: sched_setscheduler fails with EPERM, as it does under a
 * seccomp filter such as systemd's RestrictRealtime=yes, whatever the grant. The runner's forked child calls it before
 * its exec, so the runner must record the refusal and the kernel's word, never the grant. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <sched.h>

__attribute__((visibility("default"))) int sched_setscheduler(pid_t pid, int policy, const struct sched_param *param)
{
    (void)pid;
    (void)policy;
    (void)param;
    errno = EPERM;
    return -1;
}

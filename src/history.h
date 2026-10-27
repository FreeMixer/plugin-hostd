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

#ifndef HISTORY_H
#define HISTORY_H

#include <stddef.h>

#include <plugin-hostd/pin.h>

/* The running history: what each plugin did on this machine, per plugin, per binary and per host class
 * (docs/design/notes/2026-10-27-grouping-planner.md, The history record). One line per <uri> <binary digest> <host
 * class>: history <uri> <digest> <class> key=value ...; the keys are PLUGIN_HOSTD_HISTORY_KEYS (data/history.json), the
 * first line PHD_HISTORY_HEADER. Written only by the daemon, atomically, mode 0600; local to the machine.
 *
 * Nothing here reads a clock or a /proc file: the caller says what the window measured and what time it is. */

typedef struct HISTORY_REC_T {
    char *uri;
    char digest[PHD_SHA256_HEX_LEN + 1];
    char *klass;
    long long first, last, last_crash, last_crash_grouped;     /* UTC seconds */
    long long windows_solo, windows_grouped;
    long long xrun_windows_solo, xrun_windows_grouped;
    long long crashes_solo, crashes_grouped, restarts_grouped, quarantines;
    double cpu_p95_solo, cpu_max_solo;                           /* percent of one core */
    double pss_mb_solo;                                          /* MiB */
} history_rec_t;

/* start: read `file` (empty is $XDG_STATE_HOME/plugin-hostd/history, else $HOME/.local/state/plugin-hostd/history),
 * `klass` the host class this daemon records under, `save_s` the least seconds between two saves. A missing file is
 * an empty history. A file that cannot be read, or whose first line is not PHD_HISTORY_HEADER (an unknown version
 * among them), blocks reading and saving it: stderr says why, the history is unavailable, and the file is not touched.
 * A line outside the grammar, or with a key this version does not know, is kept verbatim by every save and not read.
 * Always 0: the daemon runs without a history. */
int history_init(const char *file, const char *klass, int save_s);

/* the history is readable and writable */
int history_available(void);

/* the record of a plugin binary on this host class; NULL when there is none or the history is unavailable */
const history_rec_t *history_find(const char *uri, const char *digest);

/* a closed window of the worker that ran the plugin: alone, or in a group of two or more; its CPU as percent of one
 * core over the window, its Pss in MiB, the xruns JACK counted in it (the worker's report; 0 when it makes none) */
void history_window(const char *uri, const char *digest, int grouped, double cpu_pct, double pss_mb, long xruns,
                    long long now);

/* the supervisor's counts: a worker death the daemon blamed on the plugin, a death of its group that was not its own
 * fault, a quarantine */
void history_crash(const char *uri, const char *digest, int grouped, long long now);
void history_restart(const char *uri, const char *digest, int grouped, long long now);
void history_quarantine(const char *uri, const char *digest, long long now);

/* the summary the planner reads: crashed when a crash is within PHD_HISTORY_KEEP_DAYS of `now`, raises_xruns by the
 * margin of protocol.h; malloc'd "<digest> <class> crashed=<0|1> raises_xruns=<0|1> key=value ...", NULL for no record */
char *history_summary(const char *uri, const char *digest, long long now);

/* the idle tick: write the history when it changed and `save_s` have passed since the last write (`now` seconds,
 * any steady origin) */
void history_tick(long long now);

/* history_clear: the lines of one uri (every binary, class, and a held line that names it), or all of them, at once and
 * saved. 0, or -1 when the history is unavailable */
int history_clear(const char *uri);

/* write the history now if it changed, and free it */
void history_finish(void);

/* the line of a record, "history <uri> <digest> <class> key=value ...\n"; for the tests of the grammar. NULL on
 * a failure of memory; malloc'd */
char *history_line(const history_rec_t *rec);

#endif

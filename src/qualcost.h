/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* What a plugin costs, as plugin-qualify measured it: the qualification records of qualification_dir, one file per
 * binary and offer (<id>@<version>-<hash>.<offer>.qualification.json), each holding the figures of the probe's grid
 * per rate and quantum. The daemon reads them and writes none; a record gates no add. */

#ifndef PLUGIN_HOSTD_QUALCOST_H
#define PLUGIN_HOSTD_QUALCOST_H

/* The cost of the plugin with this id (the CLAP id, or the LV2 URI) at this rate and quantum, as a fraction of one core:
 * the 95th-percentile nanoseconds per sample of the record's grid point, times the rate, over 1e9. When several records
 * hold the point (a plugin tested in several versions) the largest wins, since the planner must not be optimistic. -1.0
 * when no record holds the point, the directory cannot be read, or a record is not one. */
double qualcost_read(const char *dir, const char *id, int rate, int quantum);

#endif

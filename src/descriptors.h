/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * This file is part of plugin-hostd.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* The scanned descriptors of the plugins a controller adds: descriptor_dir and qualification_dir, the scan an add runs
 * in a child of its own, and descriptor_get; the panel the same scan files under the descriptor's name, and panel_get.
 * A descriptor describes a plugin; it gates no load, so no add waits for its scan or is refused by it. */

#ifndef PLUGIN_HOSTD_DESCRIPTORS_H
#define PLUGIN_HOSTD_DESCRIPTORS_H

#include "conf.h"

/* descriptor_dir and qualification_dir resolved (an empty setting is the default of protocol.h), made when missing
 * and tried for a write; SUCCESS, or OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP with the key, the path and why on stderr. The resolved
 * paths are written back into conf, which is kept for the scans. */
int descriptors_init(conf_t *conf);

/* the add of uri was answered: unless its files already have a descriptor or a scan of them runs, start one */
void descriptors_add(const char *uri);

/* reap the scans that ended: a descriptor is named and moved into place, a failure is recorded */
void descriptors_tick(void);

/* descriptor_get <uri>: resp 0 "<path>", or the code of protocol.h; malloc'd */
char *descriptors_get(const char *uri);

/* panel_get <uri>: resp 0 "<path>" of the panel filed under the descriptor's name, or the code of protocol.h;
 * malloc'd */
char *descriptors_panel_get(const char *uri);

/* stop the scans still running and remove what they were writing */
void descriptors_finish(void);

#endif

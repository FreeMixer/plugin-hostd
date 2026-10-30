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

#ifndef PLUGIN_HOSTD_SEARCH_PATHS_H
#define PLUGIN_HOSTD_SEARCH_PATHS_H

/* Where plugins are looked for when nothing says otherwise: the only place these lists are written. protocol.h takes
 * the defaults of lv2_path and clap_path from here, and tools/search-paths.py prints them (one directory per line) for
 * the benchmark, the Zynthian scripts and the tests; plugin-qualify and omx-panel read the plugin-hostd settings
 * (lv2_path, lv2_extra, clap_path) or run that script, and keep no list of their own (#212).
 *
 * LV2 is Zynthian's own LV2_PATH (zynthian-sys, scripts/update_zynthian_sys.sh), the folders of the image apart:
 * /usr/lib/lv2, /usr/lib/<multiarch>/lv2, /usr/local/lib/lv2 and /usr/local/lib/<multiarch>/lv2, in that order; then the
 * lib64 folders of the distributions that have them. A multiarch folder that does not exist on a machine is skipped by
 * every reader, so the triplets of all the architectures Debian ships a Pi on are listed instead of asking the machine
 * for one. The folders of one image (Zynthian's plugins and presets) are the site's: lv2_extra.
 *
 * CLAP is the standard search of clap/entry.h on Linux: $CLAP_PATH, then ~/.clap, then /usr/lib/clap. */

#define PHD_DEFAULT_LV2_PATH \
    "/usr/lib/lv2" \
    ":/usr/lib/x86_64-linux-gnu/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/lib/arm-linux-gnueabihf/lv2" \
    ":/usr/local/lib/lv2" \
    ":/usr/local/lib/x86_64-linux-gnu/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/usr/local/lib/arm-linux-gnueabihf/lv2" \
    ":/usr/lib64/lv2:/usr/local/lib64/lv2"

/* a leading ~ is the home of whoever reads the list */
#define PHD_DEFAULT_CLAP_PATH "~/.clap:/usr/lib/clap"

#endif

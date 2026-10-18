/* SPDX-License-Identifier: GPL-3.0-or-later */
/* An empty library under the name of plugin-qualify's interposer, rt_interpose.so, built beside tests/lv2-probe-child:
 * the runner preloads the file of that name beside its LV2 child, and the fake child reports whether it was. */
int plugin_hostd_rt_interpose_stub;

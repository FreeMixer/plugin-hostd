/* SPDX-License-Identifier: GPL-3.0-or-later */
/* An empty library under the name of plugin-qualify's interposer, rt_interpose.so, built beside tests/lv2-probe-child and
 * tests/probe-child: the runner preloads the file of that name beside its LV2 or CLAP child, and the fake children report
 * whether it was. The CLAP child looks for this symbol, as clap-qualify looks for the interposer's own, so a file of
 * the name that did not load is seen not to have. */
__attribute__((visibility("default"))) int plugin_hostd_rt_interpose_stub;

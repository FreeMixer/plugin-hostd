#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the plugin search lists, one directory per line, from include/plugin-hostd/search_paths.h: the one place they
are written (#212). Usage: search-paths.py lv2|clap [--existing] [--env]

--env puts the search variable first, as the daemon does for CLAP ($CLAP_PATH is searched before the defaults) and
for LV2 ($LV2_PATH stands in for the defaults); --existing drops what is not a directory; a leading ~ is the home."""
import os
import re
import sys

HEADER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "include", "plugin-hostd", "search_paths.h")


def default(name):
    text = open(HEADER).read()
    m = re.search(r"#define PHD_DEFAULT_%s_PATH((?:[ \t]*\\?\n?[ \t]*\"[^\"]*\")+)" % name.upper(), text)
    if not m:
        sys.exit("search-paths.py: %s declares no PHD_DEFAULT_%s_PATH" % (HEADER, name.upper()))
    return "".join(re.findall(r'"([^"]*)"', m.group(1))).split(":")


def search(name, env=False, existing=False):
    dirs = default(name)
    var = os.environ.get(name.upper() + "_PATH", "") if env else ""
    given = [d for d in var.split(":") if d]
    # LV2_PATH stands in for the defaults; CLAP_PATH is searched before them
    dirs = given if given and name == "lv2" else given + dirs
    dirs = [os.path.expanduser(d) for d in dirs]
    return [d for d in dirs if not existing or os.path.isdir(d)]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("lv2", "clap") or set(args[1:]) - {"--existing", "--env"}:
        sys.exit(__doc__)
    print("\n".join(search(args[0], "--env" in args, "--existing" in args)))

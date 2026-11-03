# SPDX-License-Identifier: GPL-3.0-or-later
# The plugin search lists are written once, in plugin-hostd/search_paths.h (#212), a header of plugin-hostd-protocol:
# the settings' defaults (its JSON of the protocol, this README.md) and the readers of the list (tools/search-paths.py,
# the benchmark, the Zynthian scripts) show what the header says, and no source spells a list of its own. The header is
# read where the compiler finds it (tests/declared.py): the tree's own copy first. Usage: search_paths_once.py [tree]
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import declared as protocol_files

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
failures = 0


def check(ok, what):
    global failures
    if not ok:
        failures += 1
        print("FAIL search_paths_once: " + what)


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def printed(*args):
    env = dict(os.environ)
    env.pop("LV2_PATH", None)
    env.pop("CLAP_PATH", None)
    return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "search-paths.py")] + list(args), env=env,
                          capture_output=True, text=True).stdout.split()


header = protocol_files.read_header("search_paths.h", ROOT)
paths = {}
for name in ("LV2", "CLAP"):
    m = re.search(r"#define PHD_DEFAULT_%s_PATH((?:\s*\\?\s*\"[^\"]*\")+)" % name, header)
    check(m is not None, "the header declares PHD_DEFAULT_%s_PATH" % name)
    paths[name] = "".join(re.findall(r'"([^"]*)"', m.group(1))) if m else ""

lv2 = paths["LV2"].split(":")
check(lv2[:1] == ["/usr/lib/lv2"] and "/usr/local/lib/aarch64-linux-gnu/lv2" in lv2 and "/usr/lib64/lv2" in lv2,
      "the LV2 list holds Zynthian's folders and the lib64 ones")
check(paths["CLAP"] == "~/.clap:/usr/lib/clap", "the CLAP list is ~/.clap, then /usr/lib/clap")

# what the tool prints is the header's lists
check(printed("lv2") == lv2, "tools/search-paths.py lv2 prints the header's list")
check(printed("clap") == [os.path.expanduser(d) for d in paths["CLAP"].split(":")],
      "tools/search-paths.py clap prints the header's list")

# the generated outputs carry the header's defaults; the protocol's JSON is plugin-hostd-protocol's, written from the
# installed header, so it is held to it only when the header is not a scratch copy of this tree
if not os.path.exists(os.path.join(ROOT, "include", "plugin-hostd", "search_paths.h")):
    text = open(protocol_files.variable("protocoljson")).read()
    check('"default": "%s"' % paths["LV2"] in text, "the protocol's JSON holds the header's LV2 default")
    check('"default": "%s"' % paths["CLAP"] in text, "the protocol's JSON holds the header's CLAP default")
check("`%s`" % paths["LV2"] in read("README.md"), "README.md holds the header's LV2 default")

# no other source keeps a list of its own
for rel in ("bench/lib/bench.py", "tools/zynthian/test-chain.py", "tools/zynthian/stress-pi5.py", "tools/zynthian/image-inspect.sh"):
    body = read(rel)
    check("search-paths" in body or "search_paths" in body, rel + " reads the list from tools/search-paths.py")
    check(not re.search(r"/usr/(local/)?lib(64)?/(lv2|clap)", body), rel + " spells no search folder of its own")
check("#include <plugin-hostd/search_paths.h>" in protocol_files.read_header("protocol.h", ROOT), "protocol.h takes the header's lists")
check(re.search(r"conf_merge_extra\(&g_conf\)[^;]*conf_check\(&g_conf\)", read("src/main.c")) is not None,
      "the daemon merges lv2_extra into lv2_path before it checks the settings")
check(not re.search(r'#define PHD_DEFAULT_(LV2|CLAP)_PATH', protocol_files.read_header("protocol.h", ROOT)),
      "protocol.h defines neither list itself")

print("search_paths_once: %d failed" % failures if failures else "ok   search_paths_once")
sys.exit(1 if failures else 0)

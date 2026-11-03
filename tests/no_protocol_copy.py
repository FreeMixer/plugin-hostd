# SPDX-License-Identifier: GPL-3.0-or-later
# The declared protocol is plugin-hostd-protocol's, and this tree keeps no copy of it: none of the files that moved there
# (the verb tables, the JSON of protocol.h and mod-host's, the headers and their generators) is back under any name it had
# here, and no file of this tree declares what protocol.h declares (its guard, or the macros of its tables) or holds a
# rendered verb table of the protocol. A copy that comes back drifts from the one the daemon is built against.
#
#   python3 tests/no_protocol_copy.py [<tree>]     red on any copy in the tree (default: this one)
#   python3 tests/no_protocol_copy.py --self-test  each kind of copy planted in a scratch tree must be red
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the paths that moved to plugin-hostd-protocol
MOVED = [
    "protocol/plugin-hostd.json", "protocol/mod-host.json", "protocol/plugin-hostd.schema.json",
    "protocol/plugin-hostd-protocol.json", "data/verbs.json", "docs/protocol.md", "docs/zynthian/verbs.tsv",
    "include/plugin-hostd/protocol.h", "include/plugin-hostd/search_paths.h",
    "include/plugin-hostd/plugin_hostd_host_verbs.h", "include/plugin-hostd/plugin_hostd_protocol_host_verbs.h",
    "include/plugin-hostd/plugin_hostd_protocol_vocabulary.h", "include/plugin-hostd/omx_clap_core_host_verbs.h",
    "include/plugin-hostd/omx_clap_core_vocabulary.h", "tools/mod-host-json.py", "tools/protocol-doc.py",
    "tools/protocol-table.py", "tools/abnf-gen.py", "tests/verb_table.py", "tests/mod_host_json.py",
    "tests/protocol_schema.py",
]
# what only a copy of a declaration holds, in a file of any name
MARKS = [
    (re.compile(r"^#\s*define\s+PLUGIN_HOSTD_PROTOCOL_H\b", re.M), "protocol.h's include guard"),
    (re.compile(r"^#\s*define\s+PHD_(VERBS|EVENTS|ERRORS|HOST_VERBS|INSTANCE_VERBS|CONF_STRINGS)\(X\)", re.M),
     "a table of protocol.h"),
    (re.compile(r"^#\s*define\s+PHD_DEFAULT_(LV2|CLAP)_PATH\b", re.M), "a search list of search_paths.h"),
    (re.compile(r"^#\s*define\s+OMX_VERB_[A-Z0-9_]+_FMT\b", re.M), "a rendered verb table"),
    (re.compile(r'"kind":\s*"verbs"'), "a verbs item of the contract"),
    (re.compile(r'^\s*"protocol":\s*"(plugin-hostd|mod-host|plugin-hostd-protocol)",?\s*$', re.M), "a protocol JSON"),
]
# where the marks are looked for: the sources, the headers, the tables and the tools; the docs and the recorded
# evidence quote the protocol, and the fuzz harnesses type mod-host's words on purpose
SCANNED = ("src", "include", "data", "protocol", "tools", "tests", "fuzz")
SUFFIXES = (".c", ".h", ".json", ".py", ".in")
SKIP = {os.path.join("tests", "no_protocol_copy.py")}


def tracked(tree):
    p = subprocess.run(["git", "-C", tree, "ls-files"], capture_output=True, text=True)
    if p.returncode == 0 and p.stdout:
        return p.stdout.splitlines()
    out = []
    for base, _, files in os.walk(tree):
        out += [os.path.relpath(os.path.join(base, f), tree) for f in files]
    return out


def copies(tree):
    found = []
    files = tracked(tree)
    for rel in MOVED:
        if os.path.exists(os.path.join(tree, rel)):
            found.append("%s: moved to plugin-hostd-protocol, and back here" % rel)
    for rel in files:
        if rel in SKIP or not rel.startswith(SCANNED) or not rel.endswith(SUFFIXES):
            continue
        try:
            with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for pattern, what in MARKS:
            if pattern.search(text):
                found.append("%s: holds %s" % (rel, what))
    return found


def self_test():
    plants = [
        ("protocol/plugin-hostd.json", '{\n  "protocol": "plugin-hostd",\n  "version": 1\n}\n'),
        ("include/plugin-hostd/protocol.h", "#ifndef PLUGIN_HOSTD_PROTOCOL_H\n#define PLUGIN_HOSTD_PROTOCOL_H\n#endif\n"),
        ("src/verbs_copy.h", "#define PHD_VERBS(X) \\\n    X(A, \"a\", \"\", \"\", \"\")\n"),
        ("include/plugin-hostd/old_verbs.h", '#define OMX_VERB_CHAIN_FMT "chain %i %i ..."\n'),
        ("data/more.json", '{\n  "V": {\n    "kind": "verbs",\n    "verbs": {}\n  }\n}\n'),
        ("tools/paths.h", '#define PHD_DEFAULT_LV2_PATH "/usr/lib/lv2"\n'),
    ]
    failed = 0
    work = tempfile.mkdtemp(prefix="no-protocol-copy.")
    try:
        tree = os.path.join(work, "t")
        for d in SCANNED:
            if os.path.isdir(os.path.join(ROOT, d)):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tree, d),
                                ignore=shutil.ignore_patterns("*.o", "corpus", "__pycache__"))
        if copies(tree):
            print("FAIL self-test: the copy of the tree as it is is red: %s" % copies(tree))
            return 1
        for rel, text in plants:
            path = os.path.join(tree, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            if any(c.startswith(rel + ":") for c in copies(tree)):
                print("ok   self-test: a copy planted as %s is red" % rel)
            else:
                print("FAIL self-test: a copy planted as %s is not seen" % rel)
                failed += 1
            os.unlink(path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    tree = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    found = copies(tree)
    for c in found:
        print("FAIL no protocol copy: " + c)
    if found:
        return 1
    print("ok   no copy of plugin-hostd-protocol's declarations: %d moved paths absent, %d files scanned"
          % (len(MOVED), len([f for f in tracked(tree) if f.startswith(SCANNED) and f.endswith(SUFFIXES)])))
    return 0


sys.exit(main())

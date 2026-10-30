#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""Did a Zynthian snapshot come back as it went: two snapshot files, every value compared.

    snapshot-compare.py A.zss B.zss [--ignore key,key] [--self-test]

The round trip is: save a snapshot (A), load it back, save it again (B). A and B are JSON files (Zynthian's .zss); both
are flattened to path = value and compared. A path in only one file, or with a different value, is printed and makes
the exit status 1. Keys that change on every save (default: the timestamp-like ones in IGNORE) are skipped and named in the output, so a
skipped key is never silent. It also prints the plugin names found in A (any value under a key named engine_name,
plugin_name, uri or title), so a snapshot that holds no plugin cannot pass as a round trip: with none found it exits 2.
"""
import json
import sys

IGNORE = {"last_snapshot", "timestamp", "date", "time", "saved", "created"}
NAME_KEYS = {"engine_name", "plugin_name", "uri", "title", "engine_nick"}


def flat(node, path=""):
    if isinstance(node, dict):
        for k in sorted(node):
            yield from flat(node[k], f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from flat(v, f"{path}[{i}]")
    else:
        yield path, node


def leaf_key(path):
    return path.rsplit("/", 1)[-1].split("[")[0]


def names(node, found):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in NAME_KEYS and isinstance(v, str) and v:
                found.add(v)
            names(v, found)
    elif isinstance(node, list):
        for v in node:
            names(v, found)
    return found


def compare(a, b, ignore):
    fa, fb = dict(flat(a)), dict(flat(b))
    skipped, diffs = set(), []
    for p in sorted(set(fa) | set(fb)):
        if leaf_key(p) in ignore:
            skipped.add(leaf_key(p))
            continue
        if p not in fa:
            diffs.append(f"only in B  {p} = {fb[p]!r}")
        elif p not in fb:
            diffs.append(f"only in A  {p} = {fa[p]!r}")
        elif fa[p] != fb[p]:
            diffs.append(f"differs    {p}: A {fa[p]!r}  B {fb[p]!r}")
    return diffs, skipped, len(fa)


def run(pa, pb, ignore):
    with open(pa) as f:
        a = json.load(f)
    with open(pb) as f:
        b = json.load(f)
    found = names(a, set())
    diffs, skipped, n = compare(a, b, ignore)
    print(f"{n} values in A; plugins named in A: {', '.join(sorted(found)) or 'none'}")
    if skipped:
        print("skipped keys (change on every save): " + ", ".join(sorted(skipped)))
    for d in diffs:
        print(d)
    if not found:
        print("FAIL no plugin named in A: this is not a plugin snapshot")
        return 2
    print("FAIL %d difference(s)" % len(diffs) if diffs else "PASS every value came back")
    return 1 if diffs else 0


def self_test():
    import os
    import tempfile
    a = {"chains": {"1": {"slots": [{"engine_name": "mda Piano", "controllers": {"cutoff": 0.5}}]}}, "last_snapshot": "x"}
    b = json.loads(json.dumps(a))
    b["last_snapshot"] = "y"
    d = tempfile.mkdtemp()
    pa, pb = os.path.join(d, "a"), os.path.join(d, "b")
    json.dump(a, open(pa, "w"))
    json.dump(b, open(pb, "w"))
    assert run(pa, pb, IGNORE) == 0, "a save that differs only in its timestamp must pass"
    b["chains"]["1"]["slots"][0]["controllers"]["cutoff"] = 0.6
    json.dump(b, open(pb, "w"))
    assert run(pa, pb, IGNORE) == 1, "a changed control value must fail"
    b["chains"]["1"]["slots"] = []
    json.dump(b, open(pb, "w"))
    assert run(pa, pb, IGNORE) == 1, "a lost plugin must fail"
    json.dump({"chains": {}}, open(pa, "w"))
    json.dump({"chains": {}}, open(pb, "w"))
    assert run(pa, pb, IGNORE) == 2, "an empty snapshot must not pass"
    print("self-test ok")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-test" in args:
        sys.exit(self_test())
    ign = set(IGNORE)
    if "--ignore" in args:
        i = args.index("--ignore")
        ign |= set(args[i + 1].split(","))
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    sys.exit(run(args[0], args[1], ign))

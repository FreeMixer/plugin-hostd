#!/usr/bin/env python3
"""Compare two verb logs of verb-proxy.py: the same mod-ui session against a reference daemon and against another.

Pairs each command with its reply, aligns the two command sequences (difflib, on the command text) and prints, per
verb: the count in each session, the replies seen, and every aligned command whose reply differs; then the commands
only one session sent, and the feedback messages by first word.

Usage: verb-diff.py <reference verbs.jsonl> <other verbs.jsonl> [--json out.json]
"""
import argparse
import collections
import difflib
import json
import os
import re


def load(path):
    """[(verb, command, reply)] from the command port, and a Counter of feedback words.

    The session's directory is written <out> and the number mod-ui appends to a preset bundle that exists already is
    dropped, so the two sessions' paths compare equal."""
    pairs, pending, fb = [], {}, collections.Counter()
    out = os.path.dirname(os.path.abspath(path))

    def norm(m):
        return re.sub(r"(_preset)-\d+\.lv2", r"\1.lv2", m.replace(out, "<out>"))
    for line in open(path):
        d = json.loads(line)
        d["msg"] = norm(d["msg"])
        if d["port"] == "fb" and d["dir"] == "s2c":
            fb[d["msg"].split(" ")[0]] += 1
        if d["port"] != "cmd":
            continue
        if d["dir"] == "c2s":
            pending[d["conn"]] = d["msg"]
        elif d["dir"] == "s2c" and d["conn"] in pending:
            cmd = pending.pop(d["conn"])
            pairs.append((cmd.split(" ")[0], cmd, d["msg"]))
    for cmd in pending.values():
        pairs.append((cmd.split(" ")[0], cmd, "<no reply>"))
    return pairs, fb


def code(reply):
    w = reply.split(" ")
    return " ".join(w[:2]) if w[0] == "resp" else reply


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref")
    ap.add_argument("other")
    ap.add_argument("--json")
    a = ap.parse_args()
    ref, ref_fb = load(a.ref)
    oth, oth_fb = load(a.other)
    sm = difflib.SequenceMatcher(a=[p[1] for p in ref], b=[p[1] for p in oth], autojunk=False)
    verbs = collections.OrderedDict()

    def row(v):
        return verbs.setdefault(v, {"ref": 0, "other": 0, "ref_replies": collections.Counter(),
                                    "other_replies": collections.Counter(), "differs": [], "only_ref": [],
                                    "only_other": []})
    for v, _, r in ref:
        row(v)["ref"] += 1
        row(v)["ref_replies"][code(r)] += 1
    for v, _, r in oth:
        row(v)["other"] += 1
        row(v)["other_replies"][code(r)] += 1
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rv, rc, rr = ref[i1 + k]
                ov, oc, orr = oth[j1 + k]
                if rr != orr:
                    row(rv)["differs"].append((rc, rr, orr))
        else:
            for v, c, r in ref[i1:i2]:
                row(v)["only_ref"].append((c, r))
            for v, c, r in oth[j1:j2]:
                row(v)["only_other"].append((c, r))
    # a command both sent, with the same reply, in another order (mod-ui walks a dict) is not a difference
    for d in verbs.values():
        for item in list(d["only_ref"]):
            if item in d["only_other"]:
                d["only_ref"].remove(item)
                d["only_other"].remove(item)
                d.setdefault("reordered", 0)
                d["reordered"] = d.get("reordered", 0) + 1
    print("verb\tref\tother\tref replies\tother replies\taligned replies differing\tonly in ref\tonly in other")
    for v, d in sorted(verbs.items()):
        print("%s\t%d\t%d\t%s\t%s\t%d\t%d\t%d" % (v, d["ref"], d["other"], dict(d["ref_replies"]),
                                                  dict(d["other_replies"]), len(d["differs"]), len(d["only_ref"]),
                                                  len(d["only_other"])))
    for v, d in sorted(verbs.items()):
        for c, rr, orr in d["differs"]:
            print("DIFF %s | ref: %s | other: %s" % (c, rr, orr))
        for c, r in d["only_ref"]:
            print("ONLY-REF %s | %s" % (c, r))
        for c, r in d["only_other"]:
            print("ONLY-OTHER %s | %s" % (c, r))
    print("feedback words: ref %s; other %s" % (dict(ref_fb), dict(oth_fb)))
    if a.json:
        json.dump({v: {k: (dict(x) if isinstance(x, collections.Counter) else x) for k, x in d.items()}
                   for v, d in verbs.items()} | {"_feedback": {"ref": dict(ref_fb), "other": dict(oth_fb)}},
                  open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()

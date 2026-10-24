#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# The seed corpus of the two fuzz harnesses (make fuzz-corpus), written from what the repository declares:
# protocol/plugin-hostd.json and protocol/mod-host.json for the command harness, every verb with sample arguments, and
# the send lines of README.md and docs/own-host.md; and, for the reply harness, worker feedback cut every way the
# reader has a branch for. Nothing is fetched and nothing is random: the same tree writes the same files.
#
# Usage: gen_corpus.py <dir>   (writes <dir>/command/ and <dir>/reply/)
import json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------------------------------------------------------------- the command harness: [flags] [u16 LE len] [bytes]

SAMPLE = {
    "uri": "urn:fuzz:plugin", "instance": "0", "chain": "1", "name": "p", "max_instances": "4", "format": "clap",
    "cpu-list": "0-1", "nice": "-", "path": "lib/fuzz.so", "sha256": "0" * 64, "scheme": "omx-layout/1",
    "verdict": "isolated", "worker": "w1", "page": "0", "symbol": "gain", "index": "0", "channel": "0", "key": "60",
    "velocity": "100", "#RRGGBB": "#336699", "client_name": "fuzz_client",
}
MOD_HOST_SAMPLE = {"%i": "0", "%s": "x", "%f": "0.5"}


def items(syntax):
    """the items of a declared syntax: runs with no space outside <...> and [...]"""
    out, cur, depth = [], "", 0
    for c in syntax:
        if c == " " and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
            continue
        if c in "<[":
            depth += 1
        elif c in ">]" and depth:
            depth -= 1
        cur += c
    if cur:
        out.append(cur)
    return out


def placeholder(m):
    """a sample for <name>; of <a | b> the sample for a, or a itself when it is a word of the protocol"""
    alternatives = [a.strip() for a in m.group(1).split("|")]
    if alternatives[0] in SAMPLE:
        return SAMPLE[alternatives[0]]
    return alternatives[0] if len(alternatives) > 1 else "x"


def word(item, full):
    """one sample word for an item of a syntax"""
    item = re.sub(r"\[([^\[\]]*)\]", (lambda m: m.group(1).replace("...", "")) if full else "", item)
    return re.sub(r"<([^<>]*)>", placeholder, item)


def sample(syntax, full):
    """sample arguments for a declared syntax: every required word, and with `full` every optional one"""
    words, its = [], items(syntax)
    i = 0
    while i < len(its):
        it = its[i]
        i += 1
        if it == "|":
            i += 1
            continue
        if it.startswith("[") and it.endswith("]"):
            if full:
                inner = items(it[1:-1])
                words.append(word(inner[0], full))
            continue
        words.append(word(it, full))
    return words


def message(text, flags=0):
    b = text.encode() if isinstance(text, str) else text
    return bytes([flags]) + len(b).to_bytes(2, "little") + b


def command_corpus(out):
    seeds = {}
    phd = json.load(open(os.path.join(ROOT, "protocol", "plugin-hostd.json")))
    mod = json.load(open(os.path.join(ROOT, "protocol", "mod-host.json")))
    lines = []
    for v in phd["verbs"] + phd["instance_verbs"]:
        lines.append(("plugin-hostd-" + v["name"], [v["name"]] + sample(v["arguments"], False),
                      [v["name"]] + sample(v["arguments"], True)))
    for c in mod["commands"]:
        args = [MOD_HOST_SAMPLE.get(a, "x") for a in c["args"]]
        lines.append(("mod-host-" + c["verb"], [c["verb"]] + args, [c["verb"]] + args + (["tail"] if c["optional_tail"] else [])))
    for name, short, full in lines:
        seeds[name] = message(" ".join(short))
        if full != short:
            seeds[name + "-full"] = message(" ".join(full))
        # one word too many, the supervisor refusing, and the words split by tabs
        seeds[name + "-extra"] = message(" ".join(full + ["extra"]))
        seeds[name + "-refused"] = message(" ".join(short), flags=1 | (2 << 1))
        seeds[name + "-tabs"] = message("\t".join(short) + "\r\n")
    # the placements of add, one by one
    for p in ("own", "default", "pool:p", "pool:p fuzz_client", "fuzz_client", "own fuzz_client extra"):
        seeds["add-" + re.sub(r"[^a-z_]", "-", p)] = message("add urn:fuzz:plugin 0 " + p)
    seeds["add-instance-past-the-table"] = message("add urn:fuzz:plugin 10000")
    seeds["remove-all"] = message("remove -1")
    seeds["chain-of-many"] = message("chain 1 " + " ".join(str(i) for i in range(70)))
    seeds["chain-not-a-number"] = message("chain 1 0 x")
    seeds["chain-id-not-a-number"] = message("chain x 0")
    seeds["add-too-few"] = message("add urn:fuzz:plugin")
    seeds["pin-set-long"] = message("pin_set urn:fuzz:plugin lib/fuzz.so=%s %s:%s%s" %
                                    ("0" * 64, "omx-layout/1", "0" * 64, " " * 4100))
    seeds["pin-set-layout-unknown"] = message("pin_set urn:fuzz:plugin lib/fuzz.so=%s -" % ("0" * 64))
    seeds["pin-set-bad-verdict-key"] = message("pin_set urn:fuzz:plugin lib/fuzz.so=%s omx-layout/1:%s isolated" %
                                               ("0" * 64, "0" * 64))
    seeds["pin-clear-refused"] = message("pin_clear all", flags=1)
    seeds["empty"] = message("")
    seeds["only-spaces"] = message("  \r\n")
    seeds["nul-inside"] = message(b"remove 0\0remove 1")
    seeds["trailing-cr-tab"] = message("param_set 0 gain 6\r\t")
    seeds["leading-space"] = message("  param_set 0 gain 6")
    seeds["many-words"] = message("param_set 0 " + " ".join("w%d" % i for i in range(80)))
    seeds["quit-refused-then-quit"] = message("quit now") + message("quit")
    # the send lines of the README and of the own-host page, each alone and as one session
    for doc, tag in (("README.md", "readme"), (os.path.join("docs", "own-host.md"), "own-host")):
        sends = re.findall(r'^\s*send "([^"]*)"', open(os.path.join(ROOT, doc)).read(), re.M)
        for n, line in enumerate(sends):
            seeds["%s-%d" % (tag, n + 1)] = message(line)
        seeds[tag + "-session"] = b"".join(message(line) for line in sends)
    write(out, seeds)


# ---------------------------------------------------------------- the reply harness: operations, fuzz/fuzz_reply.c

def line_limit():
    src = open(os.path.join(HERE, "fuzz_reply.c")).read()
    return int(re.search(r"^#define LINE_LIMIT (\d+)$", src, re.M).group(1))


def add():
    return b"\x00"


def write_(s, data):
    return b"\x01" + bytes([s]) + len(data).to_bytes(2, "little") + data


def drain(s):
    return b"\x02" + bytes([s])


def closed(s):
    return b"\x03" + bytes([s])


def remove(s):
    return b"\x04" + bytes([s])


def gone(i):
    return b"\x05" + bytes([i])


def eintr(s):
    return b"\x06" + bytes([s])


def event(text):
    return b"\x07" + len(text).to_bytes(2, "little") + text


def short_sends(k):
    return b"\x08" + bytes([k])


def controller_gone(closes):
    return b"\x09" + bytes([1 if closes else 0])


def reply_corpus(out):
    limit = line_limit()
    feedback = b"param_set 0 gain 0.5000\0output_set 0 out 0.2500\0data_finish\0"
    begin = b"param_gesture 1 gain begin\0"
    seeds = {
        "lines": write_(0, feedback) + drain(0),
        "split-at-every-byte": b"".join(write_(0, feedback[i:i + 1]) for i in range(len(feedback))) + drain(0),
        "split-before-every-nul": b"".join(write_(0, part + b"\0") for part in feedback.split(b"\0")[:-1]) + drain(0),
        "truncated-tail": write_(0, feedback + b"param_set 0 ga") + drain(0) + closed(0) + drain(0) + remove(0),
        "interrupted": eintr(0) + write_(0, feedback) + drain(0),
        "gesture-held-then-removed": write_(0, begin) + drain(0) + remove(0),
        "gesture-ended-by-its-worker": write_(0, begin + b"param_gesture 1 gain end\0") + drain(0) + remove(0),
        "gesture-begun-twice": write_(0, begin + begin) + drain(0) + remove(0),
        "gesture-not-a-gesture": write_(0, b"param_gesture begin\0param_gesture_x 1 a begin\0param_gesture 1 a b\0") +
        drain(0) + remove(0),
        "gesture-of-a-removed-instance": add() + write_(0, begin + b"param_gesture 2 gain begin\0") + drain(0) +
        write_(1, b"param_gesture 1 freq begin\0") + drain(1) + gone(1) + remove(0),
        "gesture-held-at-the-end": write_(0, begin) + drain(0),
        "gesture-long": write_(0, b"param_gesture 1 " + b"s" * 2000 + b" begin\0") + drain(0) + remove(0),
        "line-at-the-limit": write_(0, b"x" * limit + b"\0") + drain(0),
        "line-past-the-limit": write_(0, b"x" * (limit + 1) + b"\0" + feedback) + drain(0),
        "line-past-the-limit-in-parts": write_(0, b"x" * (limit + 1000)) + drain(0) + write_(0, b"y" * 10 + b"\0") +
        write_(0, feedback) + drain(0),
        "buffer-grows": write_(0, b"x" * 5000) + drain(0) + write_(0, b"x" * 500 + b"\0" + feedback) + drain(0),
        "worker-closed": write_(0, feedback) + closed(0) + drain(0) + remove(0),
        "two-workers-interleaved": add() + write_(0, feedback[:10]) + write_(1, feedback) + drain(1) +
        write_(0, feedback[10:]) + drain(0) + remove(1) + remove(0),
        "workers-past-the-table": add() * 6 + write_(3, feedback) + drain(3),
        "event": event(b"worker_died w1 1234 signal:9 0"),
        "event-cut-at-nul": event(b"instance_restored 0 w1\0junk"),
        "controller-takes-a-few-bytes-a-send": short_sends(3) + write_(0, feedback + begin) + drain(0) + remove(0),
        "controller-closes": write_(0, begin) + drain(0) + controller_gone(True) + write_(0, feedback) + drain(0) +
        event(b"worker_died w1 1 exit:0 0") + remove(0),
        "controller-connection-reset": controller_gone(False) + write_(0, feedback + begin) + drain(0) + gone(1),
    }
    write(out, seeds)


def write(out, seeds):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for name, data in sorted(seeds.items()):
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: gen_corpus.py <dir>")
    command_corpus(os.path.join(sys.argv[1], "command"))
    reply_corpus(os.path.join(sys.argv[1], "reply"))


main()

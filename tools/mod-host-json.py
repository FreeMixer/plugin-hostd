#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# mod-host's protocol, written out as JSON for readers that are not C: the command and feedback
# templates of mod-host.h, the protocol_parse() refusals of protocol.h and the reply codes of
# host-errors.h, read from the headers this daemon compiles against (the include directory given,
# which the Makefile takes from pkg-config mod-host-protocol or MOD_HOST_DIR/src).
#
#   tools/mod-host-json.py <include dir>      prints protocol/mod-host.json
import json
import re
import sys

HEADERS = ["mod-host.h", "protocol.h", "host-errors.h"]


def fail(msg):
    sys.exit(f"mod-host-json: {msg}")


def string_defines(text):
    return re.findall(r'^#define\s+([A-Z][A-Z0-9_]*)\s+"([^"]*)"', text, re.M)


def template(name, value):
    tokens = value.split(" ")
    verb = tokens.pop(0)
    optional_tail = bool(tokens) and tokens[-1] == "..."
    if optional_tail:
        tokens.pop()
    for t in tokens:
        if not re.fullmatch(r"%[isf]", t):
            fail(f'{name} "{value}": token "{t}" is not %i, %s or %f')
    if not re.fullmatch(r"[a-z_]+", verb):
        fail(f'{name} "{value}": no verb word')
    return {"name": name, "verb": verb, "args": tokens, "optional_tail": optional_tail}


def commands(text):
    start = text.find("Protocol commands definition")
    cut = text.find("Feedback messages definition")
    if start < 0 or cut < start:
        fail('mod-host.h has no "Protocol commands" block followed by a "Feedback messages" block')
    cmds = [template(n, v) for n, v in string_defines(text[start:cut])]
    if not cmds:
        fail("mod-host.h declares no command template")
    return cmds, [template(n, v) for n, v in string_defines(text[cut:])]


def protocol_errors(text):
    messages = [(n, v) for n, v in string_defines(text) if n.startswith("MESSAGE_")]
    codes = re.findall(r"^#define\s+PROTOCOL_([A-Z][A-Z0-9_]*)\s+\((-\d+)\)", text, re.M)
    if not codes:
        fail("protocol.h declares no PROTOCOL_* code")
    out = []
    for suffix, code in codes:
        hit = [v for n, v in messages if n == f"MESSAGE_{suffix}" or n.endswith(f"_{suffix}")]
        if len(hit) != 1:
            fail(f"PROTOCOL_{suffix} pairs with {len(hit)} MESSAGE_* lines, not one")
        out.append({"name": f"PROTOCOL_{suffix}", "code": int(code), "message": hit[0]})
    return out


def host_errors(text):
    m = re.search(r"enum\s*\{([\s\S]*?)\};", text)
    if not m:
        fail("host-errors.h has no enum")
    values = {}
    out = []
    for raw in re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", m.group(1)).split(","):
        e = re.fullmatch(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+|[A-Z][A-Z0-9_]*)\s*", raw)
        if not e:
            if raw.strip():
                fail(f'host-errors.h member "{raw.strip()}" has no value')
            continue
        name, v = e.groups()
        if re.fullmatch(r"-?\d+", v):
            value = int(v)
        elif v in values:
            value = values[v]
        else:
            fail(f"host-errors.h {name} names {v}, not declared above it")
        values[name] = value
        out.append({"name": name, "value": value})
    return out


def line(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def main():
    if len(sys.argv) != 2 or not sys.argv[1]:
        sys.exit("usage: tools/mod-host-json.py <include dir> (make: no -I in the mod-host protocol flags; set MOD_HOST_INCLUDE)")
    read = lambda f: open(f"{sys.argv[1]}/{f}", encoding="utf-8").read()
    cmds, feedback = commands(read("mod-host.h"))
    sections = [
        ("commands", cmds),
        ("feedback", feedback),
        ("protocol_errors", protocol_errors(read("protocol.h"))),
        ("host_errors", host_errors(read("host-errors.h"))),
    ]
    out = ["{", '  "protocol": "mod-host",', '  "version": 1,', f'  "headers": {line(HEADERS)},']
    for i, (key, rows) in enumerate(sections):
        out.append(f'  "{key}": [')
        out.extend(f"    {line(r)}{',' if j < len(rows) - 1 else ''}" for j, r in enumerate(rows))
        out.append("  ]" + ("," if i < len(sections) - 1 else ""))
    out.append("}")
    print("\n".join(out))


if __name__ == "__main__":
    main()

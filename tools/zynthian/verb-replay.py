#!/usr/bin/env python3
"""Replay the commands of a verb-proxy.py log against a daemon, with every LV2 add turned into a CLAP add.

Answers "which of the verbs mod-ui sent would a CLAP worker (omx-clap-host) answer": the commands are sent as mod-ui
sent them, in order, but each `add <lv2 uri> <n>` becomes `add <CLAP> <n>`; everything else (LV2 port symbols, JACK port
names, preset URIs) is left as mod-ui wrote it, which is what a CLAP plugin behind mod-ui would receive. Prints one TSV
line per command: verb, command, reply; then a count of replies per verb.

Usage: MH_PORT=5555 verb-replay.py <verbs.jsonl> <clap uri, e.g. clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp>
"""
import collections
import json
import os
import socket
import sys
import threading

log, clap = sys.argv[1], sys.argv[2]
port = int(os.environ.get("MH_PORT", "5555"))
fb = socket.create_connection(("127.0.0.1", port + 1), timeout=60)
threading.Thread(target=lambda: [None for _ in iter(lambda: fb.recv(65536), b"")], daemon=True).start()
s = socket.create_connection(("127.0.0.1", port), timeout=60)
counts = collections.defaultdict(collections.Counter)
for line in open(log):
    d = json.loads(line)
    if d["port"] != "cmd" or d["dir"] != "c2s":
        continue
    words = d["msg"].split(" ")
    if words[0] == "add" and len(words) == 3:
        words[1] = clap
    cmd = " ".join(words)
    s.sendall(cmd.encode() + b"\0")
    buf = b""
    while not buf.endswith(b"\0"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    reply = buf.rstrip(b"\0").decode("utf-8", "replace")
    code = " ".join(reply.split(" ")[:2]) if reply.startswith("resp") else "<text %d bytes>" % len(reply)
    counts[words[0]][code] += 1
    print("%s\t%s\t%s" % (words[0], cmd[:160], code))
for verb, c in sorted(counts.items()):
    print("COUNT\t%s\t%s" % (verb, dict(c)))

#!/usr/bin/env python3
"""Send mod-host protocol messages, one per argument, to 127.0.0.1:$MH_PORT (5555); print each reply.

The feedback port ($MH_PORT + 1) is opened first and drained, as a controller does: mod-host holds the first command
until it is open. MH_FEEDBACK=<file> keeps what it says.
"""
import os
import socket
import sys
import threading

port = int(os.environ.get("MH_PORT", "5555"))
fb = socket.create_connection(("127.0.0.1", port + 1), timeout=60)
fb_log = open(os.environ["MH_FEEDBACK"], "ab") if os.environ.get("MH_FEEDBACK") else None


def drain():
    while True:
        try:
            d = fb.recv(65536)
        except OSError:
            return
        if not d:
            return
        if fb_log:
            fb_log.write(d.replace(b"\0", b"\n"))
            fb_log.flush()


threading.Thread(target=drain, daemon=True).start()
s = socket.create_connection(("127.0.0.1", port), timeout=60)
for m in sys.argv[1:]:
    s.sendall(m.encode() + b"\0")
    buf = b""
    while not buf.endswith(b"\0"):
        d = s.recv(65536)
        if not d:
            break
        buf += d
    print(buf.rstrip(b"\0").decode())

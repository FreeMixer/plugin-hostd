#!/usr/bin/env python3
"""Log every message between a mod-host client (mod-ui) and a mod-host-protocol daemon.

Listens on the command and feedback ports the client expects and forwards each connection to the daemon on other
ports, writing one JSON line per NUL-terminated message:

    {"t": <seconds since start>, "conn": <n>, "port": "cmd"|"fb", "dir": "c2s"|"s2c", "msg": "<text>"}

Usage: verb-proxy.py --listen 5555 --backend 6555 --fb-listen 5556 --fb-backend 6556 --log session.jsonl
"""
import argparse
import asyncio
import json
import sys
import time

START = time.monotonic()
CONN = 0


def log_line(out, conn, port, direction, msg):
    out.write(json.dumps({"t": round(time.monotonic() - START, 4), "conn": conn, "port": port,
                          "dir": direction, "msg": msg}) + "\n")
    out.flush()


async def pump(reader, writer, out, conn, port, direction):
    buf = b""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
            buf += data
            *msgs, buf = buf.split(b"\0")
            for m in msgs:
                log_line(out, conn, port, direction, m.decode("utf-8", "replace"))
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        if buf:
            log_line(out, conn, port, direction, buf.decode("utf-8", "replace") + "<unterminated>")
        try:
            writer.close()
        except Exception:
            pass


def handler(backend_port, port_name, out):
    async def handle(c_reader, c_writer):
        global CONN
        CONN += 1
        conn = CONN
        for attempt in range(100):
            try:
                s_reader, s_writer = await asyncio.open_connection("127.0.0.1", backend_port)
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            log_line(out, conn, port_name, "err", "backend %d refused" % backend_port)
            c_writer.close()
            return
        log_line(out, conn, port_name, "open", "")
        await asyncio.gather(pump(c_reader, s_writer, out, conn, port_name, "c2s"),
                             pump(s_reader, c_writer, out, conn, port_name, "s2c"))
        log_line(out, conn, port_name, "close", "")
    return handle


async def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", type=int, default=5555)
    ap.add_argument("--backend", type=int, default=6555)
    ap.add_argument("--fb-listen", type=int, default=5556)
    ap.add_argument("--fb-backend", type=int, default=6556)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    out = open(a.log, "a")
    s1 = await asyncio.start_server(handler(a.backend, "cmd", out), "127.0.0.1", a.listen)
    s2 = await asyncio.start_server(handler(a.fb_backend, "fb", out), "127.0.0.1", a.fb_listen)
    print("verb-proxy ready", flush=True)
    async with s1, s2:
        await asyncio.gather(s1.serve_forever(), s2.serve_forever())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)

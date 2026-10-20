#!/usr/bin/env python3
"""Drive a running mod-ui (Zynthian's fork) the way its browser page does: build two pedalboards, save them, load them
back, move parameters, bypass, load presets, take snapshots and run the transport.

Writes one JSON line per step to --log: {"step", "request", "status", "body"} so two sessions (mod-host and
plugin-hostd behind the same mod-ui) can be compared on what mod-ui itself saw, beside the verb log of verb-proxy.py.

Usage: modui-drive.py --url http://127.0.0.1:8888 --log drive.jsonl [--pedalboards a.json,b.json]
A pedalboard is a list of plugin URIs, chained: capture_1 into the first, each plugin's audio outputs into the next
one's inputs, the last into playback_1/2.
"""
import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request

PEDALBOARDS = [
    ("spike-a", ["http://moddevices.com/plugins/caps/AmpVTS", "http://moddevices.com/plugins/caps/PlateX2"]),
    ("spike-b", ["http://calf.sourceforge.net/plugins/Monosynth", "http://gareus.org/oss/lv2/fil4#stereo",
                 "http://calf.sourceforge.net/plugins/Reverb"]),
]


class Ws:
    """The smallest websocket client mod-ui's /websocket needs: text frames, client masking, pings answered."""

    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (u.path, u.netloc, key)).encode())
        hdr = b""
        while b"\r\n\r\n" not in hdr:
            hdr += self.s.recv(1)
        if b" 101 " not in hdr.split(b"\r\n")[0]:
            raise RuntimeError("websocket refused: %r" % hdr[:80])
        self.s.setblocking(False)
        self.buf = b""
        self.received = []

    def send(self, text):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big"))
        self.s.setblocking(True)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        self.s.setblocking(False)

    def poll(self):
        try:
            while True:
                d = self.s.recv(65536)
                if not d:
                    break
                self.buf += d
        except BlockingIOError:
            pass
        while len(self.buf) >= 2:
            n = self.buf[1] & 0x7f
            off = 2
            if n == 126:
                n, off = int.from_bytes(self.buf[2:4], "big"), 4
            elif n == 127:
                n, off = int.from_bytes(self.buf[2:10], "big"), 10
            if len(self.buf) < off + n:
                break
            msg = self.buf[off:off + n].decode("utf-8", "replace")
            self.buf = self.buf[off + n:]
            self.received.append(msg)
            if msg == "ping":
                self.send("pong")


class Driver:
    def __init__(self, url, log):
        self.url = url.rstrip("/")
        self.log = open(log, "a")
        self.ws = None

    def record(self, step, request, status, body):
        self.log.write(json.dumps({"step": step, "request": request, "status": status, "body": body}) + "\n")
        self.log.flush()

    def http(self, step, path, data=None, raw=None):
        req = urllib.request.Request(self.url + path, method="POST" if data is not None or raw is not None else "GET",
                                     data=raw.encode() if raw is not None else
                                     urllib.parse.urlencode(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception as e:  # a timeout or a dropped connection is a result, not a crash of the driver
            status, body = -1, repr(e)
        try:
            body = json.loads(body)
        except ValueError:
            pass
        self.record(step, path, status, body if len(json.dumps(body)) < 4000 else "<%d bytes>" % len(json.dumps(body)))
        if self.ws:
            self.ws.poll()
        return status, body

    def wsend(self, step, text, settle=0.3):
        self.ws.send(text)
        time.sleep(settle)
        self.ws.poll()
        self.record(step, "ws " + text, 0, None)

    def wait_up(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urllib.request.urlopen(self.url + "/pedalboard/list", timeout=5) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(1)
        return False

    def plugin(self, uri):
        status, info = self.http("plugin_info", "/effect/get?" + urllib.parse.urlencode({"uri": uri}))
        return info if status == 200 and isinstance(info, dict) else None

    def build(self, title, uris):
        self.http("reset", "/reset")
        infos = {}
        names = []
        for i, uri in enumerate(uris):
            name = "/graph/p%d" % i
            st, ok = self.http("add", "/effect/add%s?%s" % (name, urllib.parse.urlencode({"uri": uri, "x": 100 * i,
                                                                                         "y": 100})))
            info = self.plugin(uri)
            if st != 200 or ok is False or not info:
                continue
            names.append(name)
            infos[name] = info
        prev = ["/graph/capture_1"]
        for name in names:
            ins = [p["symbol"] for p in infos[name]["ports"]["audio"]["input"]]
            outs = [p["symbol"] for p in infos[name]["ports"]["audio"]["output"]]
            for k, sym in enumerate(ins):
                if prev:
                    self.http("connect", "/effect/connect%s,%s/%s" % (prev[k % len(prev)], name, sym))
            if outs:
                prev = ["%s/%s" % (name, o) for o in outs]
        for k, port in enumerate(prev):
            self.http("connect", "/effect/connect%s,/graph/playback_%d" % (port, k + 1))
        for name in names:
            ctl = [p for p in infos[name]["ports"]["control"]["input"]
                   if "toggled" not in p.get("properties", []) and "enumeration" not in p.get("properties", [])]
            if ctl:
                p = ctl[0]
                lo, hi = p["ranges"]["minimum"], p["ranges"]["maximum"]
                self.wsend("param_set", "param_set %s/%s %f" % (name, p["symbol"], lo + 0.25 * (hi - lo)))
            self.wsend("bypass_on", "param_set %s/:bypass 1" % name)
            self.wsend("bypass_off", "param_set %s/:bypass 0" % name)
            presets = infos[name].get("presets") or []
            if presets:
                self.http("preset_load", "/effect/preset/load%s?%s" % (name, urllib.parse.urlencode(
                    {"uri": presets[0]["uri"]})))
        if names:
            self.http("preset_save_new", "/effect/preset/save_new%s?%s" % (names[0], urllib.parse.urlencode(
                {"name": title + "-preset"})))
        st, saved = self.http("save", "/pedalboard/save", {"title": title, "asNew": 1})
        return saved.get("bundlepath") if isinstance(saved, dict) else None, names, infos

    def run(self, pedalboards):
        if not self.wait_up():
            self.record("wait_up", "/pedalboard/list", -1, "mod-ui did not answer")
            return 1
        try:
            self.ws = Ws(self.url.replace("http", "ws") + "/websocket")
            time.sleep(2)
            self.ws.poll()
            self.record("websocket", "/websocket", 101, len(self.ws.received))
        except Exception as e:
            self.record("websocket", "/websocket", -1, repr(e))
            self.ws = None
            return 1
        bundles = []
        for title, uris in pedalboards:
            bundle, names, infos = self.build(title, uris)
            bundles.append((bundle, names, infos))
            self.http("snapshot_saveas", "/snapshot/saveas?" + urllib.parse.urlencode({"title": title + "-s1"}))
        self.wsend("transport_bpm", "transport-bpm 100")
        self.wsend("transport_rolling", "transport-rolling 1")
        self.wsend("transport_stop", "transport-rolling 0")
        for bundle, names, infos in bundles:
            if not bundle:
                continue
            self.http("reset", "/reset")
            self.http("load_bundle", "/pedalboard/load_bundle/", {"bundlepath": bundle, "isDefault": 0})
            time.sleep(2)
            for name in names:
                ctl = [p for p in infos[name]["ports"]["control"]["input"]
                       if "toggled" not in p.get("properties", []) and "enumeration" not in p.get("properties", [])]
                if ctl:
                    p = ctl[0]
                    self.wsend("param_set_loaded", "param_set %s/%s %f" % (name, p["symbol"], p["ranges"]["default"]))
            self.http("snapshot_list", "/snapshot/list")
            self.http("snapshot_load", "/snapshot/load?id=0")
            self.http("cpu_load", "/pedalboard/list")
        time.sleep(1)
        self.ws.poll()
        self.record("ws_received", "/websocket", 0, sorted({m.split(" ")[0] for m in self.ws.received}))
        self.http("reset", "/reset")
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--log", required=True)
    ap.add_argument("--pedalboards", help="comma-separated JSON files, each {\"title\": ..., \"uris\": [...]}")
    a = ap.parse_args()
    pbs = PEDALBOARDS
    if a.pedalboards:
        pbs = []
        for f in a.pedalboards.split(","):
            d = json.load(open(f))
            pbs.append((d["title"], d["uris"]))
    sys.exit(Driver(a.url, a.log).run(pbs))


if __name__ == "__main__":
    main()

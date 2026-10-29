#!/usr/bin/env python3
"""Send each of the 33 verbs mod-ui sends once, well formed, to a daemon holding one plugin; print the replies.

Covers the verbs a two-pedalboard session does not reach (MIDI learn and maps, Control Chain, CV, HMI, patch, monitor
output, external UI). Each line follows the argument formats of protocol/mod-host.json, the way mod-ui writes it
(zynthian/mod-ui mod/host.py). Output: TSV verb, command, reply code.

Usage: MH_PORT=5555 verb-probe.py --uri <plugin> --sym <control input> --osym <control output> --dir <scratch dir>
"""
import argparse
import os
import socket
import subprocess
import threading


def ports(client):
    """The client's JACK audio ports as (inputs, outputs), from jack_lsp -p."""
    out = subprocess.run(["jack_lsp", "-p", "-t"], capture_output=True, text=True).stdout.splitlines()
    ins, outs = [], []
    name = None
    for line in out:
        if not line.startswith(("\t", " ")):
            name = line.strip()
        elif "properties:" in line and name and name.startswith(client + ":"):
            (ins if "input" in line else outs).append(name)
    return ins, outs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uri", required=True)
    ap.add_argument("--sym", required=True)
    ap.add_argument("--osym", required=True)
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    port = int(os.environ.get("MH_PORT", "5555"))
    fb = socket.create_connection(("127.0.0.1", port + 1), timeout=60)
    threading.Thread(target=lambda: [None for _ in iter(lambda: fb.recv(65536), b"")], daemon=True).start()
    s = socket.create_connection(("127.0.0.1", port), timeout=60)

    def send(cmd):
        s.sendall(cmd.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        reply = buf.rstrip(b"\0").decode("utf-8", "replace")
        code = " ".join(reply.split(" ")[:2]) if reply.startswith("resp") else "<text %d bytes>" % len(reply)
        print("%s\t%s\t%s" % (cmd.split(" ")[0], cmd, code), flush=True)
        return code

    d, sym, osym = a.dir, a.sym, a.osym
    send("add %s 0" % a.uri)
    ins, outs = ports("effect_0")
    for cmd in [
        "bypass 0 1", "bypass 0 0",
        "param_set 0 %s 0.5" % sym,
        "patch_get 0 urn:spike:property", "patch_set 0 urn:spike:property 1",
        "monitor_output 0 %s" % osym,
        "midi_learn 0 %s 0 1" % sym, "midi_map 0 %s 0 7 0 1" % sym, "midi_unmap 0 %s" % sym,
        "cc_map 0 %s 1 1 Knob 0.5 0 1 32 0 none 0" % sym, "cc_value_set 0 %s 0.5" % sym, "cc_unmap 0 %s" % sym,
        "cv_map 0 %s system:capture_1 0 1 +" % sym, "cv_unmap 0 %s" % sym,
        "hmi_map 0 %s 0 0 0 0 0 Knob 0 1 32" % sym, "hmi_unmap 0 %s" % sym,
        'preset_save 0 "spike" %s/spike.lv2 spike.ttl' % d,
        'bundle_add "%s/spike.lv2"' % d,
        "preset_load 0 file://%s/spike.lv2/spike.ttl" % d,
        "preset_show file://%s/spike.lv2/spike.ttl" % d,
        'bundle_remove "%s/spike.lv2" ""' % d,
        "state_tmpdir %s/tmp" % d, "state_save %s/state" % d, "state_load %s/state" % d,
        "feature_enable processing 1", "feature_enable aggregated-midi 1",
        "transport 1 4 120", "transport_sync none",
        "monitor_midi_program 0 1",
        "connect system:capture_1 %s" % (ins[0] if ins else "effect_0:in"),
        "connect %s system:playback_1" % (outs[0] if outs else "effect_0:out"),
        "connect system:capture_1 mod-monitor:in_1",
        "cpu_load", "output_data_ready", "show_external_ui 0",
        "remove 0",
    ]:
        send(cmd)


if __name__ == "__main__":
    main()

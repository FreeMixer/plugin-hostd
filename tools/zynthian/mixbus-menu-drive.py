#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""A Mixbus built from Zynthian's own menu, measured with Zynthian's mixer in the path: run on the Zynthian itself.

    mixbus-menu-drive.py --out DIR [--arms hostd,mod-host] [--topologies shared,perchain] [--repeats 3] [--window 15]

For each repeat, topology and arm, in that order, it cleans every chain from the main menu and builds the set again from
the menu, as a user does on the touch screen (taps and keys on Zynthian's own display, read back from a screenshot of
every step into DIR/shots):

  hostd     four MDA ePiano chains (the menu's "(LV2 PH)" entry), and a Mixbus whose effects are omx reverb then omx
            delay (the menu's "(CLAP PH)" entries); perchain is a Mixbus each.
  mod-host  four Audio Input chains with their capture inputs cleared, and a Mixbus with no effect (a Mixbus each for
            perchain): the strips and sends Zynthian makes. One mod-host on the same JACK server then runs four MDA
            ePiano and an omx reverb and delay per Mixbus (LV2), wired into those strips; the link Zynthian makes from a
            send straight to its Mixbus's strip is replaced by the reverb and delay (mixbus-menu-bench.py modhost).

Every chain's send to its Mixbus is raised to 1.000 (post fader, the default), the faders left at Zynthian's 0.800.
Then mixbus-menu-bench.py measure reads the row (JACK DSP, PSS, xruns, level at main). The rows go to
DIR/mixbus-menu.tsv, the graph after each row to DIR/graph-<label>.json.

The screen positions are those of Zynthian's 1024x768 layout as of zynthian-ui vangelis: a changed layout shows in the
screenshots, and in a chain or effect that is not there (the run stops). It does not restore Zynthian's state: snapshot
it before (zynthian-my-data/snapshots, config) and put it back after, and do not touch the device while it runs (a UI
action makes Zynthian link again, which the measure of a mod-host row refuses).
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "mixbus-menu-bench.py")
EPIANO_LV2 = "http://moddevices.com/plugins/mda/EPiano"
REVERB_LV2, DELAY_LV2 = "urn:openmixer:reverb", "urn:openmixer:delay"
STRIP_W, STRIP_X0, STRIP_LABEL_Y = 83, 41, 740


def env():
    auth = sorted(glob.glob("/tmp/serverauth.*"))
    return dict(os.environ, DISPLAY=":0", XAUTHORITY=auth[0] if auth else "")


class ui:
    def __init__(self, out):
        self.shots = os.path.join(out, "shots")
        os.makedirs(self.shots, exist_ok=True)
        self.n = 0

    def x(self, *args, wait=1.2):
        subprocess.run(["xdotool", *map(str, args)], env=env(), check=True)
        time.sleep(wait)

    def click(self, x, y, wait=1.2):
        self.x("mousemove", x, y, "click", 1, wait=wait)

    def key(self, k, wait=0.6):
        self.x("key", k, wait=wait)

    def wheel_up(self, x, y, n):
        self.x("mousemove", x, y, "click", "--repeat", n, "--delay", 30, 4, wait=1.0)

    def cuia(self, name, wait=0.8):
        subprocess.run(["oscsend", "localhost", "1370", "/CUIA/" + name], check=True)
        time.sleep(wait)

    def shot(self, what):
        self.n += 1
        subprocess.run(["scrot", "-o", os.path.join(self.shots, "%03d-%s.png" % (self.n, what))], env=env(), check=True)


def strip_x(i):
    return STRIP_X0 + STRIP_W * i


def jack_ports():
    return subprocess.run(["jack_lsp"], capture_output=True, text=True, check=True).stdout.split()


def home(u):
    """back out of whatever is open, then the mixer"""
    for _ in range(4):
        u.key("Escape", wait=0.8)
    u.cuia("SCREEN_MIXER", wait=1.5)


def clean_all(u):
    for attempt in (1, 2):
        home(u)
        u.cuia("MAIN_MENU", wait=1.5)
        u.shot("main-menu")
        u.click(886, 160)           # Clean
        u.click(180, 190, wait=6)   # Clean All Chains
        u.shot("clean")
        if not [p for p in jack_ports() if p.startswith("zynmixer_chan:input_")]:
            return
    raise SystemExit("Clean All Chains left a channel strip: see %s" % u.shots)


def add_epiano(u, midi_chan):
    home(u)
    u.cuia("ADD_CHAIN")
    u.click(180, 190, wait=3)       # Instrument: the list takes a while the first time after a restart
    u.click(40, 146, wait=2)        # Piano
    u.shot("piano-%d" % midi_chan)
    u.click(350, 86, wait=4)        # MDA ePiano (LV2 PH)
    u.click(200, 116 + 30 * (midi_chan - 1), wait=6)
    u.shot("epiano-%d" % midi_chan)


def add_audio_in(u, i):
    home(u)
    u.cuia("ADD_CHAIN")
    u.click(510, 190, wait=2)       # Audio Input
    u.click(350, 86, wait=3)        # no effect
    u.shot("audio-in-%d" % i)


def chain_view_at(u, column, row):
    """the chain view with the node at column (chains left to right) and row (0 is the chain's header) selected"""
    home(u)
    u.x("mousemove", strip_x(0), STRIP_LABEL_Y, "mousedown", 1, wait=1.0)
    u.x("mouseup", 1, wait=1.5)     # a held label: the chain view
    for _ in range(6):
        u.key("Up", wait=0.3)
    for _ in range(12):
        u.key("Left", wait=0.3)
    for _ in range(column):
        u.key("Right", wait=0.3)
    for _ in range(row):
        u.key("Down", wait=0.3)


def clear_capture(u, column):
    chain_view_at(u, column, 1)     # the chain's Audio Input node
    u.key("Return", wait=1.5)
    u.shot("capture-%d-before" % column)
    u.click(200, 86, wait=0.8)      # untick capture 1
    u.click(200, 116, wait=0.8)     # untick capture 2
    u.shot("capture-%d-after" % column)
    u.key("Escape")


def add_mixbus(u, column, effects):
    home(u)
    u.cuia("ADD_CHAIN")
    u.click(510, 637, wait=3)       # Mixbus
    if not effects:
        u.click(350, 86, wait=3)    # no effect
        u.shot("mixbus-%d" % column)
        return
    u.click(50, 326)                # Reverb
    u.click(350, 386, wait=5)       # omx reverb (CLAP PH)
    chain_view_at(u, column, 0)
    u.key("Return", wait=1.5)       # the chain's options
    u.shot("mixbus-%d-options" % column)
    u.click(150, 146, wait=2)       # Add Audio-FX processor (under the chain's figures line)
    u.click(50, 116)                # Delay
    u.click(350, 536, wait=5)       # omx delay (CLAP PH)
    u.shot("mixbus-%d" % column)


def hostd_worlds(since):
    """the LV2 bundles of the plugin-hostd workers started since the time given (each worker has a world directory
    named for its bundle under the daemon's state root; a CLAP member has none)"""
    found = []
    for d in glob.glob("/run/plugin-hostd/plugin-hostd/*/world-w*"):
        if os.stat(d).st_mtime >= since:
            found += [os.path.basename(b) for b in glob.glob(os.path.join(d, "*.lv2"))]
    return sorted(found)


def check_build(arm, topology, g, since):
    """four strips fed, and every Mixbus fed by what the arm puts there: the delay for hostd, the send for mod-host;
    for hostd, the four instruments are MDA ePiano (a tap that lands on another entry builds another instrument)"""
    if arm == "hostd":
        worlds = hostd_worlds(since)
        if worlds != ["mod-mda-EPiano.lv2"] * 4:
            raise SystemExit("the hostd build's LV2 workers hold %s, not four MDA ePiano" % worlds)
    buses = 1 if topology == "shared" else 4
    feeders = {s.split(":")[0] for s, d in g["edges"] if d.startswith("zynmixer_chan:input_") and not s.startswith("system")}
    into_bus = {d[:-1] for s, d in g["edges"] if d.startswith("zynmixer_bus:input_") and not d.startswith(("zynmixer_bus:input_00", "zynmixer_bus:input_01"))
                and (s.startswith("zynmixer_chan:send_") if arm == "mod-host" else not s.startswith("zynmixer"))}
    strips = {p[:-1] for p in g["ports"] if p.startswith("zynmixer_chan:input_")}
    if len(strips) != 4 or len(into_bus) != buses or (arm == "hostd" and len(feeders) != 4):
        raise SystemExit("the %s %s build has %d strips, %d instruments and %d Mixbus inputs fed, not 4, 4 and %d" % (
            arm, topology, len(strips), len(feeders), len(into_bus), buses))


def raise_send(u, strip, send, instrument):
    """the strip's control page (a tap selects the strip, a second opens it), the send's row, and the level to 1.000"""
    home(u)
    u.click(strip_x(strip), STRIP_LABEL_Y)
    u.click(strip_x(strip), STRIP_LABEL_Y)
    first = 356 if instrument else 236
    u.click(200, first + 30 * (send - 1))
    u.wheel_up(900, 150, 110)
    u.shot("send-%d-%d" % (strip, send))


def build(u, arm, topology):
    clean_all(u)
    for i in range(4):
        if arm == "hostd":
            add_epiano(u, i + 1)
        else:
            add_audio_in(u, i + 1)
    if arm == "mod-host":
        for i in range(4):
            clear_capture(u, i)
    buses = 1 if topology == "shared" else 4
    for b in range(buses):
        add_mixbus(u, 4 + b, arm == "hostd")
    for i in range(4):
        raise_send(u, i, 1 if topology == "shared" else i + 1, arm == "hostd")
    home(u)
    u.shot("built-%s-%s" % (arm, topology))


def graph(out, name):
    path = os.path.join(out, name)
    subprocess.run([sys.executable, BENCH, "graph", "--out", path], check=True)
    with open(path) as f:
        return json.load(f)


def modhost_args(g):
    """the mod-host arm's plugins and links from the graph Zynthian built: the strips' inputs in order, and every link
    from a send straight to a Mixbus's strip, which a reverb and delay take the place of"""
    strips = sorted({d[:-1] for s, d in g["edges"] if d.startswith("zynmixer_chan:input_")} |
                    {p[:-1] for p in g["ports"] if p.startswith("zynmixer_chan:input_")})
    args = []
    for i, strip in enumerate(strips[:4]):
        args += ["--add", "p%d=%s" % (i, EPIANO_LV2), "--link", "p%d:out1=%sa" % (i, strip), "--link", "p%d:out2=%sb" % (i, strip)]
    direct = sorted((s[:-1], d[:-1]) for s, d in g["edges"]
                    if s.startswith("zynmixer_chan:send_") and d.startswith("zynmixer_bus:input_") and s.endswith("a"))
    cuts = []
    for k, (send, bus) in enumerate(direct):
        args += ["--add", "rev%d=%s" % (k, REVERB_LV2), "--add", "dly%d=%s" % (k, DELAY_LV2)]
        for side, n in (("a", 1), ("b", 2)):
            args += ["--link", "%s%s=rev%d:in%d" % (send, side, k, n), "--link", "rev%d:out%d=dly%d:in%d" % (k, n, k, n),
                     "--link", "dly%d:out%d=%s%s" % (k, n, bus, side)]
            cuts += ["--cut", "%s%s=%s%s" % (send, side, bus, side)]
    return args + cuts, cuts, len(strips), len(direct)


def lv2_path():
    for pid in subprocess.run(["pgrep", "-f", "zynthian_main.py"], capture_output=True, text=True).stdout.split():
        with open("/proc/%s/environ" % pid, "rb") as f:
            for item in f.read().split(b"\0"):
                if item.startswith(b"LV2_PATH="):
                    return item.split(b"=", 1)[1].decode()
    raise SystemExit("no LV2_PATH: Zynthian's UI is not running")


def run_row(a, u, arm, topology, rep):
    label = "%s-%s" % (topology, arm)
    since = time.time()
    build(u, arm, topology)
    g = graph(a.out, "graph-built-%s-%d.json" % (label, rep))
    check_build(arm, topology, g, since)
    measure = [sys.executable, BENCH, "measure", "--out", a.out, "--label", label, "--host", arm, "--repeat", str(rep),
               "--window", str(a.window), "--instruments", "auto", "--graph-after", os.path.join(a.out, "graph-%s-%d.json" % (label, rep))]
    host = None
    try:
        if arm == "mod-host":
            args, cuts, strips, sends = modhost_args(g)
            want = 1 if topology == "shared" else 4
            if strips != 4 or sends != want:
                raise SystemExit("the build has %d strips and %d sends to a Mixbus, not 4 and %d: see %s" % (strips, sends, want, u.shots))
            mh_out = os.path.join(a.out, "mod-host-%s-%d" % (label, rep))
            host = subprocess.Popen([sys.executable, BENCH, "modhost", "--out", mh_out, "--port", str(a.modhost_port)] + args,
                                    env=dict(os.environ, LV2_PATH=lv2_path()), stdout=subprocess.PIPE, text=True)
            line = host.stdout.readline()
            if not line.startswith("modhost: up"):
                raise SystemExit("mod-host did not come up: %s" % line)
            measure += ["--modhost-port", str(a.modhost_port)] + cuts
        subprocess.run(measure, check=False)
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(20)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", default="hostd,mod-host")
    ap.add_argument("--topologies", default="shared,perchain")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--window", type=int, default=15)
    ap.add_argument("--modhost-port", type=int, default=5580)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    u = ui(a.out)
    for rep in range(1, a.repeats + 1):
        for topology in a.topologies.split(","):
            for arm in a.arms.split(","):
                run_row(a, u, arm, topology, rep)
    clean_all(u)
    return 0


if __name__ == "__main__":
    sys.exit(main())

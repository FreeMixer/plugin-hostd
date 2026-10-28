#!/usr/bin/env python3
"""Path B of the Zynthian spike (FreeMixer/plugin-hostd#124): zynthian_engine_plugind against Zynthian's own engine
classes, with plugin-hostd and JACK running.

    test-path-b.py --zui <zynthian-ui checkout with the spike engine applied: spike-engine.sh>

The real zyngine modules are imported (zynthian_engine, zynthian_engine_jalv_base, zynthian_controller, zynthian_lv2);
what talks to Zynthian's hardware is stubbed: zyncoder (not vendored in zynthian-ui), pyliblo3 and zynautoconnect, and the
state manager is a mock holding the engine_info rows a chain manager would. The daemon must answer on PLUGIND_PORT (5555)
and jack-note-meter must be on PATH. Three processors: an LV2 synth (calf Monosynth), an LV2 compressor with meters (calf
Compressor) and a CLAP compressor (omx-comp), chained synth -> LV2 compressor -> CLAP compressor -> the probe.

Checks, each printed as "ok <what> <numbers>" or "FAIL ...":
 1. each engine starts and reports its JACK client (effect_<n>), and the client exists in JACK;
 2. the controllers: LV2 ones from lilv as the jalv engine builds them (count, a symbol), CLAP ones from omx-clap-scan;
 3. a control moved through zynthian_controller.set_value lands (param_get reads it back) on LV2 and on CLAP;
 4. a preset of the LV2 synth listed and loaded;
 5. a note played into the synth's MIDI input comes out of the CLAP compressor's output: peak before vs after (dBFS);
 6. the LV2 compressor's meters reach get_monitors_dict through output_set feedback.
Exit 0 when every check passes.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import types

CLAP = os.environ.get("CLAP_URI", "clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp")
SYNTH = "http://calf.sourceforge.net/plugins/Monosynth"
LV2_COMP = "http://calf.sourceforge.net/plugins/Compressor"
FAILED = []


def check(ok, what):
    print(("ok " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILED.append(what)


def stubs(root):
    """The modules that need Zynthian's hardware or a sibling checkout, as the least that lets the engines load."""
    os.makedirs(os.path.join(root, "zyncoder"))
    open(os.path.join(root, "zyncoder", "__init__.py"), "w").close()
    open(os.path.join(root, "zyncoder", "zyncore.py"), "w").write(
        "class _Z:\n    def __getattr__(self, name):\n        return lambda *a, **k: 0\nlib_zyncore = _Z()\n")
    open(os.path.join(root, "pyliblo3.py"), "w").write(
        "UDP = 1\nTCP = 2\nclass AddressError(Exception): pass\nclass ServerError(Exception): pass\n"
        "class Address:\n    def __init__(self, *a, **k): pass\n"
        "class ServerThread:\n    def __init__(self, *a, **k): pass\n")
    open(os.path.join(root, "zynautoconnect.py"), "w").write(
        "def _noop(*a, **k): pass\nadd_sidechain_ports = remove_sidechain_ports = request_audio_connect = "
        "request_midi_connect = _noop\n")


def jack_ports(client):
    out = subprocess.run(["jack_lsp", "-t", "-p"], capture_output=True, text=True).stdout.splitlines()
    ports, name = [], None
    for line in out:
        if not line.startswith(("\t", " ")):
            name = line.strip()
            ports.append([name, "", ""])
        elif "properties:" in line:
            ports[-1][1] = "input" if "input" in line else "output"
        else:
            ports[-1][2] = line.strip()
    return [p for p in ports if p[0].startswith(client + ":")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zui", required=True)
    a = ap.parse_args()
    root = tempfile.mkdtemp(prefix="zyn-stubs-")
    stubs(root)
    os.environ.setdefault("ZYNTHIAN_CONFIG_DIR", os.path.join(root, "config"))
    os.environ.setdefault("ZYNTHIAN_DATA_DIR", os.path.join(root, "data"))
    os.environ.setdefault("ZYNTHIAN_MY_DATA_DIR", os.path.join(root, "my-data"))
    # zynthian_engine_jalv reads the board at import (its broken_ui table); the spike's target class
    os.environ.setdefault("RBPI_VERSION", "Raspberry Pi 4 Model B")
    for d in ("config/jalv", "data", "my-data/presets/lv2"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    sys.path[:0] = [root, a.zui]
    # load zyngine's modules without its __init__, which imports every engine and their programs
    pkg = types.ModuleType("zyngine")
    pkg.__path__ = [os.path.join(a.zui, "zyngine")]
    sys.modules["zyngine"] = pkg
    from zyngine import zynthian_lv2
    from zyngine.zynthian_engine_plugind import zynthian_engine_plugind
    zynthian_lv2.init_lilv()

    info = {
        "PL/synth": {"NAME": "Monosynth", "TITLE": "Monosynth", "TYPE": "MIDI Synth", "URL": SYNTH, "UI": False},
        "PL/comp": {"NAME": "Compressor", "TITLE": "Compressor", "TYPE": "Audio Effect", "URL": LV2_COMP, "UI": False},
        "PL/clap": {"NAME": "omx comp", "TITLE": "omx comp", "TYPE": "Audio Effect", "URL": CLAP, "UI": False},
    }
    chain_manager = types.SimpleNamespace(engine_info=info, get_next_jackname=lambda name: name,
                                          reload_engine_preset_info=lambda *a: None,
                                          add_midi_learn=lambda *a, **k: None,
                                          remove_midi_learn_from_zctrl=lambda *a, **k: None)
    state_manager = types.SimpleNamespace(chain_manager=chain_manager)

    engines, procs = {}, {}
    for code in ("PL/synth", "PL/comp", "PL/clap"):
        eng = zynthian_engine_plugind(code, state_manager)
        proc = types.SimpleNamespace(midi_chan=0, chain=types.SimpleNamespace(zmop_index=0), jackname=None, controllers_dict={},
                                     refresh_controllers=lambda: None, get_jackname=lambda: None)
        eng.add_processor(proc)
        engines[code], procs[code] = eng, proc
        check(re.fullmatch(r"effect_\d+", eng.jackname) is not None and bool(jack_ports(eng.jackname)),
              "%s starts as JACK client %s with %d ports" % (code, eng.jackname, len(jack_ports(eng.jackname))))

    synth, comp, clap = engines["PL/synth"], engines["PL/comp"], engines["PL/clap"]
    zs = synth.get_controllers_dict(procs["PL/synth"])
    zc = clap.get_controllers_dict(procs["PL/clap"])
    check(len(synth.lv2_zctrl_dict) > 10 and "cutoff" in zs, "LV2 controllers from lilv: %d, cutoff [%s .. %s]" % (
        len(synth.lv2_zctrl_dict), zs["cutoff"].value_min, zs["cutoff"].value_max))
    check("1" in zc and zc["1"].name == "Ratio", "CLAP controllers from omx-clap-scan: %d, 1 is %s [%s .. %s]" % (
        len(clap.lv2_zctrl_dict), zc["1"].name, zc["1"].value_min, zc["1"].value_max))

    zs["cutoff"].set_value(2000.0, True)
    zc["1"].set_value(8.0, True)
    time.sleep(0.3)
    lv2_back, clap_back = synth.get_param("cutoff"), clap.get_param("1")
    check(lv2_back is not None and abs(lv2_back - 2000.0) < 1, "LV2 control moved: cutoff 2000 -> param_get %s" % lv2_back)
    check(clap_back is not None and abs(clap_back - 8.0) < 1e-3, "CLAP control moved: Ratio 8 -> param_get %s" % clap_back)

    presets = synth.get_preset_list(None)
    loaded = bool(presets) and synth.set_preset(procs["PL/synth"], presets[0])
    check(loaded, "LV2 preset: %d listed, '%s' loaded" % (len(presets), presets[0][2] if presets else None))

    # the graph Zynthian's autoconnect would make: probe MIDI -> synth -> LV2 compressor -> CLAP compressor -> probe
    meter = subprocess.Popen(["jack-note-meter", "0", "60", "3000"], stdout=subprocess.PIPE, text=True)
    assert meter.stdout.readline().strip() == "ready"

    def link(src, dst):
        subprocess.run(["jack_connect", src, dst], capture_output=True)
    midi_in = [p[0] for p in jack_ports(synth.jackname) if p[1] == "input" and "midi" in p[2]]
    link("zyn_probe:midi_out", midi_in[0])
    stages = [synth.jackname, comp.jackname, clap.jackname]
    for src, dst in zip(stages, stages[1:]):
        outs = [p[0] for p in jack_ports(src) if p[1] == "output" and "audio" in p[2]]
        ins = [p[0] for p in jack_ports(dst) if p[1] == "input" and "audio" in p[2]]
        for k, o in enumerate(outs[:2]):
            link(o, ins[min(k, len(ins) - 1)])
    outs = [p[0] for p in jack_ports(clap.jackname) if p[1] == "output" and "audio" in p[2]]
    for k, o in enumerate(outs[:2]):
        link(o, "zyn_probe:in_%d" % (k + 1))
    result = meter.stdout.readline().split()
    meter.wait()
    before, after = float(result[1]), float(result[3])
    check(after > -40 and after - before > 40, "note 60 on channel 1 through synth -> LV2 comp -> CLAP comp: peak %.1f dBFS "
          "before, %.1f dBFS after" % (before, after))

    time.sleep(1)
    mons = comp.get_monitors_dict()
    check(bool(mons), "LV2 meters through output_set: %s" % ", ".join("%s=%.3f" % kv for kv in sorted(mons.items())[:4]))

    for eng in engines.values():
        eng.stop()
    print("PATH-B %s: %d checks failed" % ("PASS" if not FAILED else "FAIL", len(FAILED)))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
# panel_get on the wire, against the installed scanner and real plugins (docs/panel.md): the daemon, this tree's probe
# and the installed omx-clap-scan (omx-clap-core 0.20.0 or later), the add answered by the fake worker. For a plugin that
# publishes a panel (PANEL_CLAP, default omx-plugins' omx-delay) panel_get answers the path of a file whose panel is the
# object omx-clap-scan --json prints for it, its bytes as the scan wrote them; for one that publishes none (NO_PANEL_CLAP,
# default omx-clap-host-tests' fake compressor) the panel is null. descriptor_get answers beside it for both. The
# probe reads this tree's clap table (a wrapper adds --table), since the installed one may predate the panel rows.
#
#   panel_wire.py   PLUGIN_HOSTD, FAKE_HOST, PROBE (default ./plugin-hostd, ./tests/fake-host, ./plugin-hostd-probe);
#                   OMX_CLAP_SCAN (default omx-clap-scan on PATH); PANEL_CLAP and NO_PANEL_CLAP as <file>#<id>
import json, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from harness import Daemon, check, resp, run_tests, wait_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", os.path.join(ROOT, "plugin-hostd")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))
PROBE = os.path.abspath(os.environ.get("PROBE", os.path.join(ROOT, "plugin-hostd-probe")))
SCAN = os.environ.get("OMX_CLAP_SCAN", "omx-clap-scan")
PANEL_CLAP = os.environ.get("PANEL_CLAP", "/usr/lib/clap/omx-delay.clap#org.openmixer.delay")
NO_PANEL_CLAP = os.environ.get("NO_PANEL_CLAP", "/usr/libexec/omx-clap-host/tests/fake_compressor.clap"
                               "#org.omx-clap-host.test.compressor")
SCANNER_FLOOR = (0, 20, 0)
WRAPPER = """#!/bin/sh
# this tree's probe; describe reads this tree's clap table
if [ "$1" = describe ]; then shift; exec %(probe)s describe --table %(table)s "$@"; fi
exec %(probe)s "$@"
"""
TESTS = []


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


def scanned(target):
    """omx-clap-scan --json of the target's file: (the text, the plugin's object)"""
    path, pid = target.rsplit("#", 1)
    text = subprocess.run([SCAN, "--json", path], capture_output=True, text=True, check=True, timeout=60).stdout
    doc = json.loads(text)
    version = tuple(int(x) for x in doc["version"].split(".")[:3])
    check(version >= SCANNER_FLOOR, "the scanner is omx-clap-scan %s, the floor is %s"
          % (doc["version"], ".".join(map(str, SCANNER_FLOOR))))
    plugins = [p for f in doc["files"] for p in f.get("plugins", []) if p.get("id") == pid]
    check(len(plugins) == 1, "the scan lists %s once" % pid)
    return text, plugins[0]


def answered_path(d, verb, uri):
    """the quoted path of resp 0 "<path>", or None while the reply is no such answer"""
    r = d.send("%s %s" % (verb, uri))
    if r == resp("DESCRIPTOR_PENDING") or r == resp("DESCRIPTOR_ABSENT"):
        return None
    check(r.startswith('resp 0 "') and r.endswith('"'), "%s %s answers a path: %s" % (verb, uri, r))
    return r[len('resp 0 "'):-1].replace('\\"', '"').replace("\\\\", "\\")


@test
def panel_get_answers_the_scans_panel_and_null_for_a_plugin_that_publishes_none():
    tmp = tempfile.mkdtemp(prefix="plugin-hostd-panel.")
    wrapper = os.path.join(tmp, "probe")
    with open(wrapper, "w") as f:
        f.write(WRAPPER % {"probe": PROBE, "table": os.path.join(ROOT, "data", "formats", "clap.json")})
    os.chmod(wrapper, 0o755)
    descriptors = os.path.join(tmp, "descriptors")
    d = Daemon(EXE, FAKE, conf={"probe": wrapper, "descriptor_dir": descriptors})
    try:
        with_panel, without = "clap:" + PANEL_CLAP, "clap:" + NO_PANEL_CLAP
        text, plugin = scanned(PANEL_CLAP)
        check(isinstance(plugin.get("panel"), dict), "the scan prints a panel for %s" % PANEL_CLAP)
        _, bare = scanned(NO_PANEL_CLAP)
        check("panel" in bare and bare["panel"] is None, "the scan prints a null panel for %s" % NO_PANEL_CLAP)

        d.expect("panel_get %s" % with_panel, resp("DESCRIPTOR_ABSENT"))
        d.expect("add %s 0" % with_panel, "resp 0")
        d.expect("add %s 1" % without, "resp 1")
        path = wait_for(lambda: answered_path(d, "panel_get", with_panel), "panel_get of %s" % with_panel, timeout=60)
        descriptor = answered_path(d, "descriptor_get", with_panel)
        check(descriptor is not None and os.path.basename(path) == os.path.basename(descriptor)
              and os.path.dirname(path) == os.path.join(os.path.dirname(descriptor), "panels"),
              "the panel is filed under the descriptor's name in panels/: %s, %s" % (path, descriptor))
        raw = open(path).read()
        doc = json.loads(raw)
        check(doc["plugin"] == {"format": "clap", "id": PANEL_CLAP.rsplit("#", 1)[1]}, "it names its plugin: %s"
              % doc["plugin"])
        check(doc["panel"] == plugin["panel"], "the panel is the object omx-clap-scan --json prints")
        prefix = '{"plugin": {"format": "clap", "id": "%s"}, "panel": ' % PANEL_CLAP.rsplit("#", 1)[1]
        check(raw.startswith(prefix) and raw.endswith("}\n") and raw[len(prefix):-2] in text,
              "its bytes are the scan's, as written")
        controls = doc["panel"]["controls"]
        check(controls and all({"paramId", "section", "widget", "visibleParamId", "visibleMask"} <= set(c)
                               for c in controls),
              "each control carries its parameter, section, widget and visibility: %d controls" % len(controls))
        check(doc["panel"]["sections"] and isinstance(doc["panel"]["roles"], (list, dict)),
              "sections and roles: %d sections" % len(doc["panel"]["sections"]))

        path = wait_for(lambda: answered_path(d, "panel_get", without), "panel_get of %s" % without, timeout=60)
        doc = json.load(open(path))
        check(doc == {"plugin": {"format": "clap", "id": NO_PANEL_CLAP.rsplit("#", 1)[1]}, "panel": None},
              "a plugin that publishes no panel answers a null panel: %s" % doc)
        check(answered_path(d, "descriptor_get", without) is not None, "and its descriptor beside it")
        d.expect("panel_get", "resp -902")
    finally:
        d.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_tests(TESTS))

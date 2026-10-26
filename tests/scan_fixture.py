# SPDX-License-Identifier: GPL-3.0-or-later
# What the scan of an add runs over, for the tests that drive a daemon: a CLAP file and an LV2 bundle of the compressor
# on disk, and a scanner that runs the real describe and panel over the recorded field dumps and logs every target it
# is run for. tests/daemon_test.py and tests/verbs_declared.py both read it.
import hashlib, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.abspath(os.environ.get("PROBE", os.path.join(ROOT, "plugin-hostd-probe")))
FIELDS = os.path.join(ROOT, "tests", "fixtures", "fields")
CLAP_ID = "org.freemixer.plugin-qualify.fixture.controls"
LV2_COMPRESSOR = "urn:example:compressor"
SCANNER = """#!/bin/sh
# a stand-in for the probe: the real describe, over the recorded dump of the target's format, and the real panel over
# the recorded scan of the CLAP fixture; the panel stage logs to $SCAN_LOG.panel
if [ "$1" = panel ]; then
  echo "$2" >> "$SCAN_LOG.panel"
  if [ -n "$PANEL_EXIT" ]; then exit "$PANEL_EXIT"; fi
  exec %(probe)s panel --json-from %(fields)s/clap-panel-scan.json "$2"
fi
echo "$2" >> "$SCAN_LOG"
if [ -n "$SCAN_HOLD" ]; then while [ ! -e "$SCAN_HOLD" ]; do sleep 0.02; done; fi
if [ -n "$SCAN_EXIT" ]; then exit "$SCAN_EXIT"; fi
case "$2" in
  clap:*) exec %(probe)s describe --table %(tables)s/clap.json --fields-from %(fields)s/clap-controls.tsv "$2" ;;
  *) exec %(probe)s describe --table %(tables)s/lv2.json --fields-from %(fields)s/lv2-compressor.tsv "$2" ;;
esac
"""
MANIFEST = """@prefix lv2: <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<%s>
    a lv2:Plugin ;
    lv2:binary <pinned.so> ;
    rdfs:seeAlso <pinned.ttl> .
"""


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def safe(text):
    """protocol.h's PHD_DESCRIPTOR_NAME_SYNTAX, plugin-qualify's rule: every character outside [A-Za-z0-9._-] as _"""
    return "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in text)


def descriptor_name(root, plugin_id, version, binary):
    """<id>@<version>-<the first 12 hex digits of the binary's SHA-256>.json"""
    return os.path.join(root, "%s@%s-%s.json" % (safe(plugin_id), safe(version), sha(binary)[:12]))


class Scan:
    """a CLAP file, an LV2 bundle of the compressor, and a scanner that logs every target it is run for; daemon makes
    the daemon under test from its settings and its environment"""

    def __init__(self, daemon):
        self.make_daemon = daemon
        self.dir = tempfile.mkdtemp(prefix="plugin-hostd-scan.")
        self.clap = os.path.join(self.dir, "clap", "controls.clap")
        os.makedirs(os.path.dirname(self.clap))
        write(self.clap, b"a clap build")
        self.clap_uri = "clap:%s#%s" % (self.clap, CLAP_ID)
        self.lv2_dir = os.path.join(self.dir, "lv2")
        self.bundle = os.path.join(self.lv2_dir, "compressor.lv2")
        os.makedirs(self.bundle)
        write(os.path.join(self.bundle, "manifest.ttl"), (MANIFEST % LV2_COMPRESSOR).encode())
        write(os.path.join(self.bundle, "pinned.so"), b"lv2 binary")
        write(os.path.join(self.bundle, "pinned.ttl"), b"lv2:port [ lv2:index 0 ] .")
        self.scanner = os.path.join(self.dir, "scanner")
        write(self.scanner, (SCANNER % {"probe": PROBE, "tables": os.path.join(ROOT, "data", "formats"),
                                        "fields": FIELDS}).encode())
        os.chmod(self.scanner, 0o755)
        self.log = os.path.join(self.dir, "scans.log")
        self.descriptors = os.path.join(self.dir, "descriptors")
        self.qualification = os.path.join(self.dir, "qualification")

    def daemon(self, conf=None, env=None):
        c = {"probe": self.scanner, "lv2_path": self.lv2_dir, "descriptor_dir": self.descriptors,
             "qualification_dir": self.qualification}
        c.update(conf or {})
        e = {"SCAN_LOG": self.log}
        e.update(env or {})
        return self.make_daemon(conf=c, env=e)

    def scans(self, stage=""):
        if not os.path.exists(self.log + stage):
            return []
        with open(self.log + stage) as f:
            return [l.strip() for l in f if l.strip()]

    def clap_name(self, root=None):
        return descriptor_name(root or self.descriptors, CLAP_ID, "1", self.clap)

    def lv2_name(self):
        # the compressor states no version; its binary is the file its manifest names with lv2:binary
        return descriptor_name(self.descriptors, LV2_COMPRESSOR, "unversioned", os.path.join(self.bundle, "pinned.so"))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def panel_name(descriptor):
    """protocol.h's PHD_PANEL_NAME_SYNTAX: the descriptor's name under panels/ of descriptor_dir"""
    return os.path.join(os.path.dirname(descriptor), "panels", os.path.basename(descriptor))

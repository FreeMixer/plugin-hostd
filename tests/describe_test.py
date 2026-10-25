# SPDX-License-Identifier: GPL-3.0-or-later
# plugin-hostd-probe describe over recorded field dumps (tests/fixtures/fields/*.tsv, docs/formats.md#the-field-dump):
# each dump through this tree's table of its format gives the descriptor recorded beside it (<name>.json), which
# validates against omx-contract's descriptor schema. A field with no row, a dump of another version, a target of the
# other format, a dump that names no file, a table whose lookup is not one to one or names a transform outside
# TRANSFORMS(X), and a value a transform cannot read are each refused (exit 2, naming what). The child path runs a stand-in for omx-clap-scan
# --fields under the runner's limits: its dump gives the same descriptor, and a child that fails gives exit 3.
#   describe_test.py   PROBE is the runner (default ./plugin-hostd-probe); the schema is $OMX_CONTRACT_SCHEMA, or
#                      omx-contract.schema.json in pkg-config's datadir of omx-contract
import json, os, stat, subprocess, sys, tempfile

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.environ.get("PROBE", os.path.join(ROOT, "plugin-hostd-probe"))
FIELDS = os.path.join(ROOT, "tests", "fixtures", "fields")
TABLES = os.path.join(ROOT, "data", "formats")
CASES = {"clap-controls": "clap:controls.clap#org.freemixer.plugin-qualify.fixture.controls",
         "lv2-compressor": "lv2:urn:example:compressor"}
# omx-contract's reader and a data tree it reads (an omx-contract checkout's data/), when OMX_CONTRACT_CLI and
# OMX_CONTRACT_DATA name them; READER_VERSION, the reader's schema, stands for the floor the descriptor states, which a
# reader older than 3.0.0 refuses
CLI = os.environ.get("OMX_CONTRACT_CLI")
CLI_DATA = os.environ.get("OMX_CONTRACT_DATA")
READER_VERSION = os.environ.get("OMX_CONTRACT_READER_VERSION")
failed = 0


def check(cond, what):
    global failed
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failed += 1


def schema_path():
    if os.environ.get("OMX_CONTRACT_SCHEMA"):
        return os.environ["OMX_CONTRACT_SCHEMA"]
    datadir = subprocess.run([os.environ.get("PKG_CONFIG", "pkg-config"), "--variable=datadir", "omx-contract"],
                             capture_output=True, text=True).stdout.strip()
    return os.path.join(datadir, "omx-contract.schema.json")


def describe(target, dump=None, table=None, extra=()):
    fmt = target.split(":", 1)[0]
    cmd = [PROBE, "describe", "--table", table or os.path.join(TABLES, fmt + ".json")] + list(extra)
    if dump is not None:
        cmd += ["--fields-from", dump]
    return subprocess.run(cmd + [target], capture_output=True, text=True, timeout=60)


def scratch(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def main():
    if not (CLI and CLI_DATA):
        print("skip omx-contract validate: OMX_CONTRACT_CLI and OMX_CONTRACT_DATA name no reader and data tree")
    schema = json.load(open(schema_path()))
    validator = jsonschema.validators.validator_for(schema)({"$defs": schema["$defs"], "$ref": "#/$defs/descriptor"})
    with tempfile.TemporaryDirectory() as tmp:
        for name, target in CASES.items():
            dump = os.path.join(FIELDS, name + ".tsv")
            r = describe(target, dump)
            check(r.returncode == 0, "%s: describe exits 0 (%s)" % (name, r.stderr.strip()))
            if r.returncode:
                continue
            got = json.loads(r.stdout)
            want = json.load(open(os.path.join(FIELDS, name + ".json")))
            check(got == want, "%s: the descriptor is the one recorded" % name)
            errors = sorted(validator.iter_errors(got), key=lambda e: list(e.path))
            check(not errors, "%s: the descriptor validates against omx-contract's schema%s"
                  % (name, "".join("\n     %s: %s" % (list(e.path), e.message) for e in errors)))
            if CLI:
                # omx-contract's own reader, its rules beside the schema's (origin-source, port-words, instrument): the
                # descriptor in a scratch data tree of the reader's schema, as an in-tree file names it
                data = os.path.join(tmp, "data-" + name)
                subprocess.run(["cp", "-r", CLI_DATA, data], check=True)
                os.makedirs(os.path.join(data, "descriptors"))
                doc = dict(got, **{"$schema": "../../schema/omx-contract.schema.json"})
                if READER_VERSION:
                    doc["requires"] = {"omx-contract-schema": ">= " + READER_VERSION}
                scratch(data, os.path.join("descriptors", name + ".json"), json.dumps(doc, indent=2))
                r2 = subprocess.run([CLI, "validate", "--data", data], capture_output=True, text=True)
                check(r2.returncode == 0, "%s: omx-contract validate reads it: %s" % (name, (r2.stdout + r2.stderr).strip()))
            fmt = target.split(":", 1)[0]
            check(got["origin"] == "scanned" and got["plugin"]["format"] == fmt and got.get("extensions", {}).get(fmt),
                  "%s: scanned, format %s, the bag carries what the table classes extension" % (name, fmt))

        # refusals: each exits 2 and names what it refuses
        lv2 = open(os.path.join(FIELDS, "lv2-compressor.tsv")).read()
        clap = open(os.path.join(FIELDS, "clap-controls.tsv")).read()
        table = json.load(open(os.path.join(TABLES, "clap.json")))

        def refused(what, target, dump_text, want, table_doc=None):
            t = scratch(tmp, "table.json", json.dumps(table_doc)) if table_doc else None
            r = describe(target, scratch(tmp, "dump.tsv", dump_text), t)
            check(r.returncode == 2 and want in r.stderr and not r.stdout,
                  "%s: refused, exit 2, naming %s (%d: %s)" % (what, want, r.returncode, r.stderr.strip()))

        refused("a field with no row", CASES["lv2-compressor"], lv2 + "port:5\tlv2:furlong\t1\n", "lv2:furlong")
        refused("a dump that names no file", CASES["clap-controls"],
                "".join(l for l in clap.splitlines(True) if "\tclap_entry\t" not in l), "clap_entry")
        refused("a dump of another version", CASES["lv2-compressor"], lv2.replace("--fields 1", "--fields 2", 1),
                "# omx-clap-scan --fields 1")
        refused("a scope of the other format", CASES["lv2-compressor"], lv2 + "param:0\tlv2:name\tx\n", "param:0")
        refused("a value a transform cannot read", CASES["clap-controls"],
                clap + "param:0\tclap_plugin_params.value_to_text\tSine\n", "scale-points refuses")
        refused("a target of the other format", "clap:x.clap#id", lv2, "the table is lv2's",
                json.load(open(os.path.join(TABLES, "lv2.json"))))
        bad = json.loads(json.dumps(table))
        bad["PLUGIN_HOSTD_CLAP_MAP"]["rows"]["CLAP_PORT_MONO"]["word"]["values"] = {"CLAP_PORT_MONO": "stereo"}
        bad["PLUGIN_HOSTD_CLAP_MAP"]["rows"]["CLAP_PORT_STEREO"]["word"]["values"] = {"CLAP_PORT_STEREO": "stereo",
                                                                                     "CLAP_PORT_X": "stereo"}
        refused("a lookup not one to one", CASES["clap-controls"], clap, "CLAP_PORT_STEREO: a lookup whose values", bad)
        bad = json.loads(json.dumps(table))
        bad["PLUGIN_HOSTD_CLAP_MAP"]["rows"]["clap_param_info.module"]["word"]["transform"] = "module-path"
        refused("a transform outside TRANSFORMS(X)", CASES["clap-controls"], clap, "module-path", bad)

        # the panel description of omx-clap-scan 0.20.0's dump: every field dropped, the descriptor as without it
        panel = open(os.path.join(FIELDS, "clap-panel.tsv")).read()
        r = describe(CASES["clap-controls"], scratch(tmp, "panel.tsv", clap + panel))
        check(r.returncode == 0 and json.loads(r.stdout or "null") == json.load(open(os.path.join(FIELDS, "clap-controls.json"))),
              "a dump with a panel gives the descriptor without one (%d: %s)" % (r.returncode, r.stderr.strip()))
        refused("a panel field with no row", CASES["clap-controls"], clap + "control:0\tomx_clap_panel_control.colour\tred\n",
                "omx_clap_panel_control.colour")
        refused("a panel scope of the other format", CASES["lv2-compressor"], lv2 + "section:0\tlv2:name\tx\n", "section:0")
        bad = json.loads(json.dumps(table))
        bad["PLUGIN_HOSTD_CLAP_MAP"]["rows"]["omx_clap_panel_control.widget"] = {
            "from": "omx_clap_ext.h#omx_clap_panel_control.widget", "extension": True}
        refused("a panel field the table carries", CASES["clap-controls"], clap + panel, "is dropped, never", bad)

        # the child path: a stand-in for omx-clap-scan --fields, run under the runner's limits
        child = scratch(tmp, "omx-clap-scan", "#!/bin/sh\n[ \"$1\" = --fields ] || exit 9\n"
                        "case $2 in lv2:urn:example:compressor) cat '%s' ;; *) echo 'no such plugin' >&2; exit 1 ;; esac\n"
                        % os.path.join(FIELDS, "lv2-compressor.tsv"))
        os.chmod(child, stat.S_IRWXU)
        r = describe(CASES["lv2-compressor"], extra=["--child", child])
        check(r.returncode == 0 and json.loads(r.stdout or "null") == json.load(open(os.path.join(FIELDS, "lv2-compressor.json"))),
              "the child's dump gives the recorded descriptor (%d: %s)" % (r.returncode, r.stderr.strip()))
        r = describe("lv2:urn:example:missing", extra=["--child", child])
        check(r.returncode == 3 and "made no dump" in r.stderr and not r.stdout,
              "a child that fails: exit 3, no descriptor (%d: %s)" % (r.returncode, r.stderr.strip()))
    if failed:
        print("describe: %d failed" % failed)
        sys.exit(1)
    print("describe: ok")


if __name__ == "__main__":
    main()

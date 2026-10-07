# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# protocol/mod-host.json follows mod-host's headers: copy them, move a verb, a protocol_parse() code and message and a
# reply code, and the JSON written from the copy carries the moved values; a header the reader cannot parse is refused.
#
#   python3 tests/mod_host_json.py <mod-host include dir>
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "mod-host-json.py")


def gen(include):
    r = subprocess.run([sys.executable, TOOL, include], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def edit(path, pattern, repl):
    text = open(path, encoding="utf-8").read()
    if not re.search(pattern, text):
        sys.exit(f"mod_host_json: perturbation target {pattern} not in {path}")
    open(path, "w", encoding="utf-8").write(re.sub(pattern, repl, text, count=1))


def main():
    include = sys.argv[1]
    rc, base, err = gen(include)
    assert rc == 0, err
    doc = json.loads(base)
    assert doc["protocol"] == "mod-host" and doc["commands"] and doc["protocol_errors"] and doc["host_errors"]
    with tempfile.TemporaryDirectory() as tmp:
        for f in ("mod-host.h", "protocol.h", "host-errors.h"):
            shutil.copy(os.path.join(include, f), tmp)
        edit(os.path.join(tmp, "mod-host.h"), r'"remove %i"', '"destroy %i"')
        edit(os.path.join(tmp, "protocol.h"), r"PROTOCOL_MANY_ARGUMENTS\s+\(-2\)", "PROTOCOL_MANY_ARGUMENTS     (-7)")
        edit(os.path.join(tmp, "protocol.h"), r'"many arguments"', '"too many arguments"')
        edit(os.path.join(tmp, "host-errors.h"), r"ERR_INVALID_OPERATION = -902", "ERR_INVALID_OPERATION = -909")
        rc, moved, err = gen(tmp)
        assert rc == 0, err
        m = json.loads(moved)
        assert moved != base
        assert {c["name"]: c["verb"] for c in m["commands"]}["EFFECT_REMOVE"] == "destroy"
        assert {e["name"]: (e["code"], e["message"]) for e in m["protocol_errors"]}["PROTOCOL_MANY_ARGUMENTS"] == (-7, "too many arguments")
        assert {e["name"]: e["value"] for e in m["host_errors"]}["ERR_INVALID_OPERATION"] == -909
        edit(os.path.join(tmp, "mod-host.h"), r'"destroy %i"', '"destroy %x"')
        rc, _, err = gen(tmp)
        assert rc != 0 and "is not %i, %s or %f" in err, err
    print("mod-host.json follows its headers")


if __name__ == "__main__":
    main()

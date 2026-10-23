# SPDX-License-Identifier: GPL-3.0-or-later
# The daemon's check of a preset file (src/presets.c, through tests/preset-check) against protocol/preset.schema.json:
# the same verdict on every file of tests/fixtures/presets and on every broken copy tests/preset_format.py refuses, and
# PRESET_INVALID for a file the schema never sees (no JSON, empty, over PHD_PRESET_FILE_MAX, a relative path). Then the
# preset files of omx-plugins, the producer of our own factory presets: each holds to the schema and to the daemon. They
# are read from OMX_PLUGINS_DIR, else a checkout beside this one, else fetched; with none of them the step is skipped
# with its reason, never failed.
#
#   PRESET_CHECK=tests/preset-check python3 tests/preset_conformance.py
import json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preset_format
from preset_format import REFUSED, ROOT, broken, good, validator

CHECK = os.path.abspath(os.environ.get("PRESET_CHECK", os.path.join(ROOT, "tests", "preset-check")))
OMX_PLUGINS_URL = os.environ.get("OMX_PLUGINS_URL", "https://github.com/FreeMixer/omx-plugins.git")
INVALID = -524
FILE_MAX = 64 * 1024 * 1024
failed = 0


def verdicts(paths):
    out = subprocess.run([CHECK] + paths, check=True, capture_output=True, text=True).stdout.splitlines()
    return {line.split(" ", 2)[2]: int(line.split(" ", 1)[0]) for line in out}


def say(ok, what):
    global failed
    failed += not ok
    print("%s %s" % ("ok  " if ok else "FAIL", what))


def write(tmp, name, data):
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def omx_plugins(tmp):
    """the omx-plugins tree, or (None, why)"""
    here = os.environ.get("OMX_PLUGINS_DIR") or os.path.join(os.path.dirname(ROOT), "omx-plugins")
    if os.path.isdir(here):
        return here, None
    if os.environ.get("OMX_PLUGINS_DIR"):
        return None, "OMX_PLUGINS_DIR=%s is no directory" % here
    dest = os.path.join(tmp, "omx-plugins")
    try:
        subprocess.run(["git", "clone", "-q", "--depth", "1", OMX_PLUGINS_URL, dest], check=True, timeout=120,
                       capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.SubprocessError) as e:
        return None, "omx-plugins cannot be fetched from %s (%s)" % (OMX_PLUGINS_URL, type(e).__name__)
    return dest, None


def preset_files(tree):
    for top, dirs, files in os.walk(tree):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            if not name.endswith(".json"):
                continue
            path = os.path.join(top, name)
            try:
                with open(path) as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and str(doc.get("format", "")).startswith("org.openmixer.preset/"):
                yield path, doc


with tempfile.TemporaryDirectory(prefix="preset-conformance.") as tmp:
    cases = [("%s holds" % name, write(tmp, "good-%s" % name, doc), True) for name, doc in good.items()]
    for k, (what, name, change) in enumerate(REFUSED):
        doc = broken(name, change)
        cases.append((what, write(tmp, "broken-%d.json" % k, doc), validator.is_valid(doc)))
    cases.append(("a file that is no JSON", write(tmp, "nojson.json", b"{\"format\": "), False))
    cases.append(("an empty file", write(tmp, "empty.json", b""), False))
    cases.append(("a file that is not there", os.path.join(tmp, "absent.json"), False))
    big = dict(good["v2-params.json"], description="x" * FILE_MAX)
    cases.append(("a file over PHD_PRESET_FILE_MAX", write(tmp, "big.json", big), False))
    got = verdicts([path for _, path, _ in cases])
    for what, path, valid in cases:
        say((got[path] == 0) == valid, "%s: the daemon %s it as the schema does" % (what, "takes" if valid else "refuses"))
        say(got[path] in (0, INVALID), "%s: answered 0 or PRESET_INVALID, not %d" % (what, got[path]))
    rel = verdicts(["tests/fixtures/presets/v2-params.json"])
    say(list(rel.values()) == [INVALID], "a relative path is PRESET_INVALID")

    tree, why = omx_plugins(tmp)
    if not tree:
        print("skip omx-plugins presets: %s" % why)
    else:
        found = list(preset_files(tree))
        if not found:
            print("skip omx-plugins presets: %s holds no org.openmixer.preset file" % tree)
        got = verdicts([path for path, _ in found]) if found else {}
        for path, doc in found:
            rel = os.path.relpath(path, tree)
            errors = list(validator.iter_errors(doc))
            say(not errors, "omx-plugins %s holds to the schema%s" % (rel, ": " + errors[0].message if errors else ""))
            say(got[path] == 0, "omx-plugins %s is taken by the daemon" % rel)

sys.exit(1 if failed else 0)

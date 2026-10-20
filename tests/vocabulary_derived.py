# SPDX-License-Identifier: GPL-3.0-or-later
# The words the probe output shares with omx-contract are declared once, in the contract: protocol/probe-output.schema.in
# names each as an @OMX_<ITEM>@ token, the generator writes the item's words from omx_vocabulary.h, and every enum the
# generated schema holds at a token's place must be the contract's omx-vocabulary.schema.json $defs.<ITEM>.enum, the
# same words in the same order. A list of the template that is the whole of a contract item, typed by hand, is refused
# even when its words are right today: it is the second copy that drifts.
#   vocabulary_derived.py [tree]   tree holds protocol/ (default: this checkout); the contract's schema is
#                                  $OMX_VOCABULARY, or omx-vocabulary.schema.json in pkg-config's datadir of omx-contract
import copy, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
TOKEN = re.compile(r"@((?:OMX|PHD)_[A-Z0-9_]+)@")
# the items the probe output must take from the contract (#115); any other @OMX_<ITEM>@ the template names is held to
# the contract all the same
REQUIRED = ("MEASUREMENT_LATENCY_METHODS", "MEASUREMENT_VOICE_BASES", "MACHINE_CORE_BANDS", "MACHINE_CLOCK_BANDS",
            "RESOURCE_THREAD_SCHEDULING")
failed = 0


def check(cond, what):
    global failed
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failed += 1


def vocabulary_path():
    if os.environ.get("OMX_VOCABULARY"):
        return os.environ["OMX_VOCABULARY"]
    datadir = subprocess.run([PKG_CONFIG, "--variable=datadir", "omx-contract"], capture_output=True, text=True,
                             check=True).stdout.strip()
    path = os.path.join(datadir, "omx-vocabulary.schema.json")
    if not os.path.exists(path):
        sys.exit("omx-contract's %s is not installed (omx-contract-devel, libomx-contract-dev >= 2.18.0)" % path)
    return path


def enums(node, pointer=""):
    """(JSON pointer, enum list) of every enum under node"""
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            yield pointer, node["enum"]
        for k, v in node.items():
            yield from enums(v, pointer + "/" + k.replace("~", "~0").replace("/", "~1"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from enums(v, "%s/%d" % (pointer, i))


def at(document, pointer):
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def template(path):
    """the template as JSON, each token a string of its own"""
    return json.loads(TOKEN.sub(lambda m: '"@%s@"' % m.group(1), open(path).read()))


def derived(tmpl):
    """{pointer: item} of every enum of the template that is one @OMX_<ITEM>@ token"""
    out = {}
    for pointer, values in enums(tmpl):
        m = TOKEN.fullmatch(values[0]) if len(values) == 1 and isinstance(values[0], str) else None
        if m and m.group(1).startswith("OMX_"):
            out[pointer] = m.group(1)[len("OMX_"):]
    return out


def differences(generated, places, core):
    """what the generated schema holds at each token's place that is not the contract's item"""
    out = []
    for pointer, item in sorted(places.items()):
        want = core.get(item, {}).get("enum")
        try:
            have = at(generated, pointer)["enum"]
        except (KeyError, IndexError, TypeError):
            have = None
        if want is None or have != want:
            out.append((pointer, item, have, want))
    return out


def main():
    core = json.load(open(vocabulary_path()))["$defs"]
    tmpl = template(os.path.join(TREE, "protocol", "probe-output.schema.in"))
    generated = json.load(open(os.path.join(TREE, "protocol", "probe-output.schema.json")))
    places = derived(tmpl)

    for item in REQUIRED:
        check(item in places.values(), "the template takes %s from the contract" % item)

    hand = [(p, k) for p, values in enums(tmpl) if all(isinstance(v, str) and not TOKEN.fullmatch(v) for v in values)
            for k, d in core.items() if isinstance(d.get("enum"), list) and sorted(set(values)) == sorted(set(d["enum"]))]
    check(not hand, "the template types no list of the contract's by hand%s" %
          "".join("; %s is %s" % h for h in hand))

    found = {(p, i): (h, w) for p, i, h, w in differences(generated, places, core)}
    for pointer, item in sorted(places.items()):
        check((pointer, item) not in found, "%s at %s is the contract's%s" % (item, pointer, "" if (pointer, item) not in found
              else ": the schema has %s, the contract %s" % found[(pointer, item)]))

    methods = [at(generated, p)["enum"] for p, i in places.items() if i == "MEASUREMENT_LATENCY_METHODS"]
    check(any("note-onset" in m for m in methods), "the latency methods include note-onset: %s" % methods)

    # positive control: a contract whose item has one word more, or its words in another order, is told apart
    moved = copy.deepcopy(core)
    moved["MEASUREMENT_LATENCY_METHODS"]["enum"] = moved["MEASUREMENT_LATENCY_METHODS"]["enum"] + ["x-onset"]
    moved["MACHINE_CLOCK_BANDS"]["enum"] = list(reversed(moved["MACHINE_CLOCK_BANDS"]["enum"]))
    told = {i for _, i, _, _ in differences(generated, places, moved)}
    check(told == {"MEASUREMENT_LATENCY_METHODS", "MACHINE_CLOCK_BANDS"},
          "positive control: a contract with a word more and one in another order differs there only: %s" % sorted(told))

    print("vocabulary: %s" % ("FAILED (%d)" % failed if failed else "ok"))
    return 1 if failed else 0


sys.exit(main())

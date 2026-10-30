# SPDX-License-Identifier: GPL-3.0-or-later
# The format tables cover their format, every field once (docs/formats.md#the-coverage-test). The field list of a format
# is every term of omx-contract's installed TERM files of that format plus every row of the table with a `from`; each
# field has exactly one row. Per field it prints `mapped <word> <transform>`, `extension <format>` or
# `dropped <decision>`, then the count per class, and it is red, naming the field, for: a field with no row or with two; a
# row that covers no field; a row keyed other than its field; a word the descriptor schema lacks, or a lookup entry that
# is no value the word takes; a transform that is not in TRANSFORMS(X), a lookup with no values or not one to one, a
# scale-by with no factor, data a transform takes none of; a used TERM that is dropped, a drop with no decision; an
# outbound-read row whose transform is neither identity nor lookup; a unit row that does not map to its TERM's word.
#
#   format_coverage.py [--contract-dir <dir>] [--major <n>] [--schema <file>] <format>...
#   format_coverage.py --self-test [the same options]   each sabotage arm (a row removed, a word misspelt, a transform
#                                                       renamed) red naming its field, then the tables as they are green
#
# The TERM files are <contract-dir>/<major>/omx-contract/formats/<format>/**; contract-dir is pkg-config's contractdir
# of omx-contract, the schema omx-contract.schema.json in its datadir; the tables are this tree's data/formats/.
import argparse, copy, glob, json, os, re, subprocess, sys

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
MAPS = {"clap": "PLUGIN_HOSTD_CLAP_MAP", "lv2": "PLUGIN_HOSTD_LV2_MAP"}
OUTBOUND = ("identity", "lookup")


def pkg_var(name):
    r = subprocess.run([PKG_CONFIG, "--variable=" + name, "omx-contract"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def transforms(path):
    """The names of TRANSFORMS(X), read from the header."""
    text = open(path).read()
    body = re.search(r"#define TRANSFORMS\(X\)(.*?)\n\n", text, re.S)
    if not body:
        sys.exit("format_coverage: no TRANSFORMS(X) in %s" % path)
    return set(re.findall(r'X\("([a-z0-9-]+)"', body.group(1)))


def terms(contract_dir, major, fmt):
    """Every term of the installed TERM files of a format: <ITEM>#<term> -> (term name, term)."""
    base = os.path.join(contract_dir, str(major), "omx-contract", "formats", fmt)
    out = {}
    for path in sorted(glob.glob(os.path.join(base, "**", "*.json"), recursive=True)):
        for name, item in json.load(open(path)).items():
            if isinstance(item, dict) and item.get("kind") == "terms" and item.get("format") == fmt:
                for t, v in item["terms"].items():
                    out["%s#%s" % (name, t)] = (t, v)
    if not out:
        sys.exit("format_coverage: no %s TERM file under %s (omx-contract-devel installed?)" % (fmt, base))
    return out


class Schema:
    """The descriptor's words, walked in omx-contract's schema."""

    def __init__(self, path):
        self.doc = json.load(open(path))
        self.defs = self.doc["$defs"]
        self.cls = jsonschema.validators.validator_for(self.doc)

    def resolve(self, node):
        while isinstance(node, dict) and "$ref" in node:
            node = self.defs[node["$ref"].rsplit("/", 1)[1]]
        return node

    def word(self, path):
        """The schema of a word (`controls[].travel.unit`), or None when the descriptor has no such word."""
        node = self.resolve(self.defs["descriptor"])
        for seg in path.split("."):
            many = seg.endswith("[]")
            node = self.resolve((node.get("properties") or {}).get(seg[:-2] if many else seg))
            if not isinstance(node, dict):
                return None
            if many:
                if node.get("type") != "array":
                    return None
                node = self.resolve(node.get("items"))
        return node

    def takes(self, node, value):
        """Whether a word takes the value: an item of it when the word is a list."""
        if node.get("type") == "array" and not isinstance(value, list):
            node = self.resolve(node.get("items", {}))
        return self.cls({"$defs": self.defs, **node}).is_valid(value)


def check(fmt, table, installed, schema, names):
    """(lines, reds, counts): every field of the format with its row's class, and what is red."""
    item = table.get(MAPS[fmt])
    if not isinstance(item, dict) or item.get("kind") != "formatMap" or item.get("format") != fmt:
        return [], ["%s: no formatMap %s of format %s" % (fmt, MAPS[fmt], fmt)], {}
    rows = item.get("rows", {})
    lines, reds, counts = [], [], {"mapped": 0, "extension": 0, "dropped": 0}
    red = lambda field, why: reds.append("RED %s %s: %s" % (fmt, field, why))
    covers = {}
    for key, row in rows.items():
        field = row.get("term") if "term" in row else key
        covers.setdefault(field, []).append(key)
        if "term" in row and row["term"] not in installed:
            red(key, "covers no field: %s is no installed term" % row["term"])
    fields = list(installed) + [k for k, r in rows.items() if "from" in r]
    for field in fields:
        keys = covers.get(field, [])
        if not keys:
            red(field, "no row")
            continue
        if len(keys) > 1:
            red(field, "%d rows: %s" % (len(keys), ", ".join(sorted(keys))))
        key = keys[0]
        row = rows[key]
        term = installed.get(row.get("term"))
        if term:
            name, t = term
            want = t["id"] if fmt == "clap" else None
            if (want is not None and key != want) or (want is None and key.split(":", 1)[-1] != name):
                red(key, "keyed other than its field %s" % row["term"])
        classes = [c for c in ("word", "extension", "dropped") if c in row]
        if len(classes) != 1:
            red(key, "%d classes" % len(classes))
            continue
        if "word" in row:
            w = row["word"]
            word, tr = w.get("word", ""), w.get("transform", "")
            lines.append("%s: mapped %s %s" % (key, word, tr))
            counts["mapped"] += 1
            node = schema.word(word)
            if node is None:
                red(key, "word %s: the descriptor schema has no such word" % word)
            if tr not in names:
                red(key, "transform %s: not in TRANSFORMS(X)" % tr)
            if tr == "lookup":
                values = w.get("values")
                if not values:
                    red(key, "lookup with no values")
                else:
                    seen = [json.dumps(v) for v in values.values()]
                    if len(set(seen)) != len(seen):
                        red(key, "lookup not one to one: %s" % json.dumps(values))
                    for v in values.values():
                        if node is not None and not schema.takes(node, v):
                            red(key, "lookup entry %s: no value %s takes" % (json.dumps(v), word))
            elif "values" in w:
                red(key, "values on %s, which takes none" % tr)
            if tr == "scale-by":
                if not w.get("factor"):
                    red(key, "scale-by with no factor")
            elif "factor" in w:
                red(key, "factor on %s, which takes none" % tr)
            if term:
                name, t = term
                if t.get("kind") != "property" and any(str(b).startswith("omx-plugins:") for b in t.get("by", [])) \
                        and tr not in OUTBOUND:
                    red(key, "outbound-read (%s writes it) with transform %s, neither identity nor lookup"
                        % ("omx-plugins", tr))
                if fmt == "lv2" and t.get("kind") == "unit" and t.get("word") is not None \
                        and w.get("values") != {key: t["word"]}:
                    red(key, "unit row %s: its TERM names the word %s" % (json.dumps(w.get("values")), t["word"]))
        elif "extension" in row:
            lines.append("%s: extension %s" % (key, fmt))
            counts["extension"] += 1
        else:
            ruling = (row["dropped"] or {}).get("ruling", "") if isinstance(row["dropped"], dict) else ""
            lines.append("%s: dropped %s" % (key, decision))
            counts["dropped"] += 1
            if not ruling:
                red(key, "dropped by no decision")
            if term and term[1].get("status") == "used":
                red(key, "a used TERM (%s) dropped" % row["term"])
    return lines, reds, counts


def run(fmt, table, opts, quiet=False):
    lines, reds, counts = check(fmt, table, opts.installed[fmt], opts.schema, opts.names)
    if not quiet:
        for line in lines:
            print("%s %s" % (fmt, line))
        print("%s: %d fields: mapped %d, extension %d, dropped %d" % (fmt, sum(counts.values()), counts.get("mapped", 0),
                                                                     counts.get("extension", 0), counts.get("dropped", 0)))
    for r in reds:
        print(r)
    return reds


def self_test(opts):
    failed = 0
    for fmt in ("clap", "lv2"):
        table = opts.tables[fmt]
        rows = table[MAPS[fmt]]["rows"]
        mapped = [k for k, r in rows.items() if "word" in r and "term" in r]
        lookup = next(k for k in mapped if rows[k]["word"]["transform"] == "lookup")
        removed, misspelt, renamed = mapped[0], mapped[len(mapped) // 2], lookup

        def arm(what, edit, names):
            nonlocal failed
            broken = copy.deepcopy(table)
            edit(broken[MAPS[fmt]]["rows"])
            reds = run(fmt, broken, opts, quiet=True)
            ok = reds and all(any(n in r for r in reds) for n in names)
            print("self-test %s %s: %s" % (fmt, what, "red, naming %s" % " ".join(names) if ok else "NOT RED"))
            failed += not ok

        arm("one row removed", lambda r: r.pop(removed), [rows[removed]["term"]])
        arm("one word misspelt", lambda r: r[misspelt]["word"].update(word=r[misspelt]["word"]["word"] + "x"), [misspelt])
        arm("one transform renamed", lambda r: r[renamed]["word"].update(transform="look-up"), [renamed])
        reds = run(fmt, table, opts, quiet=True)
        print("self-test %s as it is: %s" % (fmt, "green" if not reds else "RED"))
        failed += bool(reds)
    print("FORMAT-COVERAGE SELF-TEST %s" % ("OK" if not failed else "FAILED"))
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--contract-dir", default=os.environ.get("CONTRACTDIR") or pkg_var("contractdir"))
    ap.add_argument("--major", default=os.environ.get("CONTRACT_SCHEMA_MAJOR", "3"))
    ap.add_argument("--schema", default=os.environ.get("OMX_CONTRACT_SCHEMA")
                    or os.path.join(pkg_var("datadir"), "omx-contract.schema.json"))
    ap.add_argument("--transforms", default=os.path.join(ROOT, "src", "transforms.h"))
    ap.add_argument("formats", nargs="*", metavar="clap|lv2")
    opts = ap.parse_args()
    if any(f not in MAPS for f in opts.formats):
        ap.error("a format is clap or lv2")
    if not opts.contract_dir:
        sys.exit("format_coverage: no contract directory: install omx-contract-devel or pass --contract-dir")
    opts.schema = Schema(opts.schema)
    opts.names = transforms(opts.transforms)
    opts.tables = {f: json.load(open(os.path.join(ROOT, "data", "formats", f + ".json"))) for f in MAPS}
    opts.installed = {f: terms(opts.contract_dir, opts.major, f) for f in MAPS}
    if opts.self_test:
        sys.exit(1 if self_test(opts) else 0)
    failed = 0
    for fmt in opts.formats or ["clap", "lv2"]:
        reds = run(fmt, opts.tables[fmt], opts)
        print("FORMAT-COVERAGE %s %s" % (fmt, "OK" if not reds else "RED (%d)" % len(reds)))
        failed += bool(reds)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

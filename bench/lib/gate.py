"""bench/gate.sh: the soundness gate over the documents of a run taken together (the twins at other period counts, the
repeat documents of one cell). Prints each cell that breaks a check with its reasons and the run.sh arguments that
measure it alone; exit 1 when there is one, 0 when every cell agrees with its neighbours."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soundness  # noqa: E402


def main():
    names = sys.argv[1:]
    if not names:
        print("usage: gate.sh <omx-bench/1 document>...", file=sys.stderr)
        sys.exit(2)
    docs = []
    for name in names:
        with open(name) as f:
            docs.append(json.load(f))
    bad = soundness.check(docs)
    marked = soundness.unstable(docs) - set(bad)
    for (d, n), reasons in sorted(bad.items()):
        row = docs[d]["scenarios"][n]
        print("%s: UNSTABLE %s %s %s %d/%d%s dsp %.2f" % (
            names[d], row["id"], row["host"], row.get("mode", "-"), row["rate"], row["frames"],
            "" if row.get("stress", "none") == "none" else " " + row["stress"], row["dsp_load_avg"]))
        for why in reasons:
            print("    " + why)
        print("    rerun alone: " + soundness.rerun_hint(row, docs[d]))
    for d, n in sorted(marked):
        row = docs[d]["scenarios"][n]
        print("%s: marked unstable %s %s %s %d/%d (no ratio is made from it)" % (
            names[d], row["id"], row["host"], row.get("mode", "-"), row["rate"], row["frames"]))
    cells = len(soundness.entries(docs))
    print("gate: %d cells, %d break a check, %d more are marked unstable" % (cells, len(bad), len(marked)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

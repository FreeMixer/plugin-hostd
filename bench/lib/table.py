"""Markdown tables from omx-bench/1 documents: one row per scenario row of the families that compare ways of running
the same plugins (cvp and grp scenarios), the ratios of one process per plugin to one chain, and the xruns summed
over the rows of each mode. A figure with a spread shows its median and [min, max]; a row that did not run is shown,
with its status and its note."""

import json
import re
import sys


def label(row):
    """the mode as the table names it: plugin-hostd's modes bare, the other hosts' with the host"""
    mode = row.get("mode", "-")
    return mode if row["host"] == "H2" else "%s %s" % (row["host"], mode)


def figure(row, key, digits=None):
    if row.get(key) is None:
        return "-"
    v = row[key]
    text = ("%.*f" % (digits, v)) if digits is not None else str(v)
    if "spread" in row and key in row["spread"]:
        lo, hi = row["spread"][key]
        if lo != hi:
            text += " [%s-%s]" % (("%.*f" % (digits, lo)) if digits is not None else lo,
                                  ("%.*f" % (digits, hi)) if digits is not None else hi)
    return text


def family_rows(doc):
    """the rows of the scenarios that compare ways of running the same strip: cvp<N> and grp<N>"""
    return [r for r in doc["scenarios"] if re.match(r"^(cvp|grp)[0-9]+$", r["id"]) and "mode" in r]


def order(row):
    modes = {"individual": 0, "chain": 1, "plan": 2, "pool": 3}
    return (row["id"], row["rate"], row["frames"], row.get("stress", "none") != "none", row["host"] != "H2",
            modes.get(row["mode"], 4), row["host"])


def table(doc):
    out = ["| scenario | rate/frames | N | stress | mode | procs | RSS MB | PSS MB | cpu_pct | ctx | DSP avg/max % | xruns |"
           " latency frames | repeats |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(family_rows(doc), key=order):
        head = "| %s | %d/%d | %d | %s | %s |" % (r["id"], r["rate"], r["frames"], len(r["plugins"]),
                                                 r.get("stress", "none"), label(r))
        if r["status"] != "ok":
            out.append("%s %s: %s |" % (head, r["status"], r["note"]))
            continue
        dsp = "%s / %s" % (figure(r, "dsp_load_avg", 2), figure(r, "dsp_load_max", 2))
        out.append("%s %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            head, figure(r, "processes"), figure(r, "rss_mb_total", 1), figure(r, "pss_mb_total", 1),
            figure(r, "cpu_pct", 2), figure(r, "ctx_switches"), dsp, figure(r, "xruns"),
            figure(r, "latency_frames"), r.get("repeats", 1)))
    return out


def ratios(doc):
    """one process per plugin over one chain, plugin-hostd, no stress: how many times more each measure is"""
    rows = {(r["id"], r["rate"], r["frames"], r["mode"]): r for r in family_rows(doc)
            if r["host"] == "H2" and r["status"] == "ok" and r.get("stress", "none") == "none"}
    out = ["| scenario | rate/frames | N | processes | RSS | PSS | cpu_pct | ctx | DSP avg |",
           "|---|---|---|---|---|---|---|---|---|"]
    for (sid, rate, frames, mode), ind in sorted(rows.items()):
        grp = rows.get((sid, rate, frames, "chain"))
        if mode != "individual" or not grp:
            continue

        def x(key):
            return "%.2fx" % (ind[key] / grp[key]) if grp.get(key) else "-"
        out.append("| %s | %d/%d | %d | %d vs %d | %s | %s | %s | %s | %s |" % (
            sid, rate, frames, len(ind["plugins"]), ind["processes"], grp["processes"], x("rss_mb_total"),
            x("pss_mb_total"), x("cpu_pct"), x("ctx_switches"), x("dsp_load_avg")))
    return out


def xrun_sums(doc):
    """xruns summed over the rows of each mode, with and without stress, and how many rows that was"""
    sums = {}
    for r in family_rows(doc):
        if r["status"] == "ok" and r.get("xruns") is not None:
            key = (label(r), r.get("stress", "none") != "none")
            n, total = sums.get(key, (0, 0))
            sums[key] = (n + 1, total + r["xruns"])
    out = ["| mode | stress | rows | xruns summed |", "|---|---|---|---|"]
    for (mode, stressed), (n, total) in sorted(sums.items()):
        out.append("| %s | %s | %d | %d |" % (mode, "yes" if stressed else "no", n, total))
    return out


def render(doc):
    m = doc["machine"]
    out = ["## %s: %s, %s, %d cores, governor %s" % (doc["id"], m["model"], m["cpu"], m["cores"], m["governor"]),
           "", "Medians; [min-max] where the repeats differ.", ""]
    out += table(doc) + ["", "### One process per plugin over one chain, no stress", ""] + ratios(doc)
    out += ["", "### Xruns summed over the rows of each mode", ""] + xrun_sums(doc)
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) < 2:
        print("usage: table.sh <omx-bench/1 document>...", file=sys.stderr)
        sys.exit(2)
    for name in sys.argv[1:]:
        with open(name) as f:
            doc = json.load(f)
        if doc.get("schema") != "omx-bench/1":
            print("%s: not an omx-bench/1 document" % name, file=sys.stderr)
            sys.exit(1)
        print(render(doc))


if __name__ == "__main__":
    main()

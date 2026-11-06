"""Markdown tables from omx-bench/1 documents: one row per scenario row of the families that compare ways of running
the same plugins (cvp and grp scenarios), the ratios of one process per plugin to one chain, and the xruns summed
over the rows of each mode. A figure with a spread shows its median and [min, max]; a row that did not run is shown,
with its status and its note."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soundness  # noqa: E402

WINDOW_S = 10  # the window of a document that does not say its cycles: the runner's default


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
    """the rows of the scenarios that compare ways of running the same strip: cvp<N>, cvc<N>, cvl<N> and grp<N>"""
    return [r for r in doc["scenarios"] if re.match(r"^(cvp|cvc|cvl|grp)[0-9]+$", r["id"]) and "mode" in r]


def unstable_rows(docs):
    """the ids (object ids) of the rows no figure is made from: marked unstable by the run, or breaking a check of the
    soundness gate now, against the other documents given"""
    return {id(docs[d]["scenarios"][n]) for d, n in soundness.unstable(docs)}


def per_cycle(row, key):
    """a count of the window over the cycles of the window, with `~` when the document does not say its cycles and the
    runner's default window is assumed; None without the count"""
    if row.get(key) is None:
        return None, False
    cycles = row.get("cycles")
    est = not cycles
    if est:
        cycles = WINDOW_S * row["rate"] / row["frames"]
    return row[key] / cycles, est


def cycle_figure(row, key):
    v, est = per_cycle(row, key)
    return "-" if v is None else ("~" if est else "") + "%.1f" % v


def order(row):
    modes = {"individual": 0, "chain": 1, "chain-add": 2, "plan": 3, "pool": 4}
    return (row["id"], row["rate"], row["frames"], row.get("stress", "none") != "none", row["host"] != "H2",
            modes.get(row["mode"], 4), row["host"])


def table(doc, bad=frozenset()):
    out = ["| scenario | rate/frames | N | stress | mode | procs | RSS MB | PSS MB | cpu_pct | ctx/cycle | invol/cycle |"
           " jackd/cycle | DSP avg/max % | xruns | latency frames | repeats |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(family_rows(doc), key=order):
        head = "| %s | %d/%d | %d | %s | %s |" % (r["id"], r["rate"], r["frames"], len(r["plugins"]),
                                                 r.get("stress", "none"), label(r))
        if r["status"] != "ok":
            out.append("%s %s: %s |" % (head, r["status"], r["note"]))
            continue
        dsp = "%s / %s" % (figure(r, "dsp_load_avg", 2), figure(r, "dsp_load_max", 2))
        if id(r) in bad:
            dsp += " UNSTABLE"
        out.append("%s %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            head, figure(r, "processes"), figure(r, "rss_mb_total", 1), figure(r, "pss_mb_total", 1),
            figure(r, "cpu_pct", 2), cycle_figure(r, "ctx_switches"), cycle_figure(r, "ctx_involuntary"),
            cycle_figure(r, "ctx_jackd"), dsp, figure(r, "xruns"), figure(r, "latency_frames"), r.get("repeats", 1)))
    return out


def ratios(doc, bad=frozenset()):
    """one process per plugin over one chain, plugin-hostd, no stress: how many times more each measure is. A pair with
    an unstable row is left out"""
    rows = {(r["id"], r["rate"], r["frames"], r["mode"]): r for r in family_rows(doc)
            if r["host"] == "H2" and r["status"] == "ok" and r.get("stress", "none") == "none" and id(r) not in bad}
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


def format_pairs(docs, bad=frozenset()):
    """the same plugins as CLAP and as LV2 on the same host (cvc<N> against cvl<N>, H1 and H2): one host, one DSP code,
    two wrappers, so the difference is the format and nothing else. A cell either side of which is unstable is left out"""
    cells = {}
    for doc in docs:
        periods = (doc.get("jack") or {}).get("periods")
        for r in family_rows(doc):
            m = re.match(r"^(cvc|cvl)([0-9]+)$", r["id"])
            if m and r["host"] in ("H1", "H2") and r["status"] == "ok" and id(r) not in bad:
                cells[(int(m.group(2)), r["host"], r["mode"], r["rate"], r["frames"], periods,
                       r.get("stress", "none"), m.group(1))] = r
    out = ["| N | host | mode | rate/frames | periods | stress | CLAP DSP % | LV2 DSP % | LV2/CLAP | CLAP ctx/cycle |"
           " LV2 ctx/cycle |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(k for k in cells if k[7] == "cvc" and k[:7] + ("cvl",) in cells):
        c, l = cells[key], cells[key[:7] + ("cvl",)]
        out.append("| %d | %s | %s | %d/%d | %s | %s | %.2f | %.2f | %.2fx | %s | %s |" % (
            key[0], key[1], key[2], key[3], key[4], key[5] if key[5] else "-", key[6], c["dsp_load_avg"],
            l["dsp_load_avg"], l["dsp_load_avg"] / c["dsp_load_avg"] if c["dsp_load_avg"] else 0,
            cycle_figure(c, "ctx_switches"), cycle_figure(l, "ctx_switches")))
    return out


def rate_ratios(docs, bad=frozenset()):
    """the DSP load at the higher rate over the lower one, for the same cell, from cells that passed the gate only"""
    cells = {}
    for doc in docs:
        periods = (doc.get("jack") or {}).get("periods")
        for r in family_rows(doc):
            if r["status"] == "ok" and id(r) not in bad and r.get("dsp_load_avg"):
                cells[(r["id"], r["host"], r["mode"], r["frames"], periods, r.get("stress", "none"), r["rate"])] = r
    out = ["| scenario | host | mode | frames | periods | stress | rates | DSP % | ratio |", "|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(cells):
        lo = key[:6] + (min(k[6] for k in cells if k[:6] == key[:6]),)
        if key == lo:
            continue
        a, b = cells[lo], cells[key]
        out.append("| %s | %s | %s | %d | %s | %s | %d/%d | %.2f/%.2f | %.2fx |" % (
            key[0], key[1], key[2], key[3], key[4] if key[4] else "-", key[5], key[6], lo[6], b["dsp_load_avg"],
            a["dsp_load_avg"], b["dsp_load_avg"] / a["dsp_load_avg"]))
    return out


def unstable_list(docs, bad):
    out = []
    for doc in docs:
        for r in doc["scenarios"]:
            if id(r) in bad:
                out.append("| %s | %s | %s | %d/%d | %s | %.2f |" % (
                    r["id"], r["host"], r.get("mode", "-"), r["rate"], r["frames"], r.get("stress", "none"),
                    r["dsp_load_avg"]))
    return ["| scenario | host | mode | rate/frames | stress | DSP % |", "|---|---|---|---|---|---|"] + out if out else []


def render(doc, others=()):
    docs = [doc] + list(others)
    bad = unstable_rows(docs)
    m = doc["machine"]
    out = ["## %s: %s, %s, %d cores, governor %s" % (doc["id"], m["model"], m["cpu"], m["cores"], m["governor"]),
           "", "Medians; [min-max] where the repeats differ. ctx/cycle is the context switches of the window over its "
           "cycles (`~` where the document does not say its cycles). A figure marked UNSTABLE failed the soundness "
           "gate: it is shown, and no ratio is made from it.", ""]
    out += table(doc, bad) + ["", "### One process per plugin over one chain, no stress", ""] + ratios(doc, bad)
    out += ["", "### Xruns summed over the rows of each mode", ""] + xrun_sums(doc)
    pairs = format_pairs([doc], bad)
    if len(pairs) > 2:
        out += ["", "### CLAP against LV2, the same plugins on the same host", ""] + pairs
    lst = unstable_list([doc], bad)
    if lst:
        out += ["", "### Unstable cells (not to be quoted)", ""] + lst
    return "\n".join(out) + "\n"


def render_all(docs):
    """each document, then what is read across them: the rate scaling, from the cells that passed the gate"""
    bad = unstable_rows(docs)
    out = [render(d, [x for x in docs if x is not d]) for d in docs]
    if len(docs) > 1:
        rr = rate_ratios(docs, bad)
        if len(rr) > 2:
            out.append("### Rate scaling, from cells that passed the gate\n\n" + "\n".join(rr) + "\n")
    return out


def main():
    if len(sys.argv) < 2:
        print("usage: table.sh <omx-bench/1 document>...", file=sys.stderr)
        sys.exit(2)
    docs = []
    for name in sys.argv[1:]:
        with open(name) as f:
            doc = json.load(f)
        if doc.get("schema") != "omx-bench/1":
            print("%s: not an omx-bench/1 document" % name, file=sys.stderr)
            sys.exit(1)
        docs.append(doc)
    for text in render_all(docs):
        print(text)


if __name__ == "__main__":
    main()

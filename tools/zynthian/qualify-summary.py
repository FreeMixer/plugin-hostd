#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""Summarise a plugin-qualify --all run: verdicts per host, RT safety, cost percentiles, the grid it measured.

    tools/zynthian/qualify-summary.py --qualify qualify.json [--records DIR] [--pins FILE] [--system-pins FILE]
        [--sync-log FILE] [--run-log FILE] [--requested-rates 44100,48000,96000,192000]
        [--requested-quanta 128,256,512,1024] --out summary.json [--markdown tables.md]

qualify.json is plugin-qualify's standard output (a list of plugin-qualify.qualification-record/1); --records is the
directory its --out wrote, read for the probe documents' crash signals and the machine profile. Every input file is
named in the summary with its sha256. Nothing is estimated: a figure the files do not hold is absent from the summary.

Cost is the probe's own unit, nanoseconds per sample (one frame of one block, a warm-up head dropped), the median over
the timed blocks; the per-block figure is that times the block's frames.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys

OURS = re.compile(r"^(org\.openmixer\.|urn:openmixer:)")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(sorted_vals, p):
    """numpy's linear interpolation, the one plugin-qualify uses."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def r4(v):
    return None if v is None else float("%.4g" % v)


def summarise(a):
    with open(a.qualify) as fh:
        recs = json.load(fh)
    inputs = {"qualify": {"name": os.path.basename(a.qualify), "sha256": sha256(a.qualify), "bytes": os.path.getsize(a.qualify)}}
    for key in ("pins", "system_pins", "sync_log", "run_log"):
        p = getattr(a, key)
        if p:
            inputs[key] = {"name": os.path.basename(p), "sha256": sha256(p), "bytes": os.path.getsize(p)}

    s = {"schema": "zynthian-qualify-summary/1", "inputs": inputs}
    s["records"] = len(recs)
    s["by_format"] = dict(collections.Counter(r["plugin"]["format"] for r in recs))
    s["by_offer"] = dict(collections.Counter(r["probe"]["file"].rsplit(".", 3)[-3] for r in recs))
    s["probe_outcome"] = dict(collections.Counter(r["probe"].get("outcome") for r in recs))
    s["runner"] = sorted({r["tool"]["runner"] for r in recs})
    times = sorted(r["measuredAt"] for r in recs)
    s["measured_from"], s["measured_to"] = times[0], times[-1]
    s["machine_class"] = sorted({json.dumps(r["probe"].get("machineClass"), sort_keys=True) for r in recs})

    # verdicts: one per host profile in each record
    hv = collections.defaultdict(collections.Counter)
    hf = collections.defaultdict(collections.Counter)
    deciding = collections.defaultdict(collections.Counter)
    hosting = collections.defaultdict(collections.Counter)
    for r in recs:
        fmt = r["plugin"]["format"]
        for v in r["verdicts"]:
            hv[v["host"]][v["rating"]] += 1
            hf[v["host"]]["%s:%s" % (fmt, v["rating"])] += 1
            hosting[v["host"]][v.get("hosting")] += 1
            if v["rating"] != "suitable":
                code = v.get("deciding") or (v["reasons"][0]["code"] if v.get("reasons") else "none")
                deciding[v["host"]][code] += 1
    s["verdicts"] = {h: dict(c) for h, c in sorted(hv.items())}
    s["verdicts_by_format"] = {h: dict(c) for h, c in sorted(hf.items())}
    s["hosting"] = {h: {str(k): n for k, n in c.items()} for h, c in sorted(hosting.items())}
    s["not_suitable_reasons"] = {h: dict(c.most_common()) for h, c in sorted(deciding.items())}

    # the grid: what was measured, and RT safety per point. The probe document a record names holds the RT sweep of
    # every grid point; the record keeps it for some points only, so the probe document is read when it is there.
    probe_grid = {}
    if a.records:
        for r in recs:
            f = os.path.join(a.records, r["probe"]["file"])
            if os.path.isfile(f):
                with open(f) as fh:
                    probe_grid[r["probe"]["file"]] = {(m["rate"], m["quantum"]): m for m in json.load(fh).get("grid", [])}
    s["rt_safety_source"] = "probe documents" if probe_grid else "qualification records"

    def rt_of(r, m):
        pm = probe_grid.get(r["probe"]["file"], {}).get((m["rate"], m["quantum"]))
        return (pm or m).get("rtSafety") or {}

    grid = collections.Counter()
    rt = collections.Counter()
    rtf = collections.Counter()
    viol = collections.Counter()
    costs = collections.defaultdict(list)
    for r in recs:
        fmt = r["plugin"]["format"]
        for m in r["measurements"].get("grid", []):
            grid["%s:%d:%d" % (fmt, m["rate"], m["quantum"])] += 1
            x = rt_of(r, m)
            if not x.get("swept"):
                rt["not swept"] += 1
                rtf["%s:not swept" % fmt] += 1
            elif x.get("allocations") or x.get("locks") or x.get("syscalls"):
                rt["violations"] += 1
                rtf["%s:violations" % fmt] += 1
                for k in ("allocations", "locks", "syscalls"):
                    if x.get(k):
                        viol[k] += 1
            else:
                rt["clean"] += 1
                rtf["%s:clean" % fmt] += 1
            c = m.get("cost") or {}
            if c.get("median") is not None:
                costs[(fmt, m["rate"], m["quantum"])].append(c["median"])
    # per record: the RT outcome of its swept points, or the probe outcome when it has no grid point
    per = collections.Counter()
    for r in recs:
        fmt = r["plugin"]["format"]
        swept = [rt_of(r, m) for m in r["measurements"].get("grid", [])]
        swept = [x for x in swept if x.get("swept")]
        if not r["measurements"].get("grid"):
            what = r["probe"].get("outcome")
        elif not swept:
            what = "not swept"
        elif any(x.get("allocations") or x.get("locks") or x.get("syscalls") for x in swept):
            what = "violations"
        else:
            what = "clean"
        per["%s:%s:%s" % (fmt, r["probe"]["file"].rsplit(".", 3)[-3], what)] += 1
    s["rt_safety_records"] = dict(sorted(per.items()))
    s["grid_points"] = dict(sorted(grid.items()))
    s["rt_safety_points"] = dict(rt)
    s["rt_safety_points_by_format"] = dict(sorted(rtf.items()))
    s["rt_safety_violation_kind"] = dict(viol)
    s["requested"] = {"rates": [int(x) for x in a.requested_rates.split(",")] if a.requested_rates else None,
                      "quanta": [int(x) for x in a.requested_quanta.split(",")] if a.requested_quanta else None}
    s["cost_unit"] = "ns per sample, median of the timed blocks"
    s["cost"] = {}
    for (fmt, rate, q), vals in sorted(costs.items()):
        vals.sort()
        s["cost"]["%s:%d:%d" % (fmt, rate, q)] = {
            "n": len(vals),
            "p50": r4(pct(vals, 50)), "p90": r4(pct(vals, 90)), "p95": r4(pct(vals, 95)), "p99": r4(pct(vals, 99)),
            "max": r4(vals[-1]), "min": r4(vals[0]),
            "sorted": [r4(v) for v in vals],
        }

    # our plugins
    ours = []
    for r in recs:
        if not OURS.match(r["plugin"]["id"]):
            continue
        row = {"id": r["plugin"]["id"], "format": r["plugin"]["format"], "offer": r["probe"]["file"].rsplit(".", 3)[-3],
               "outcome": r["probe"].get("outcome"),
               "verdicts": {v["host"]: v["rating"] for v in r["verdicts"]}, "grid": {}}
        for m in r["measurements"].get("grid", []):
            c = m.get("cost") or {}
            x = rt_of(r, m)
            row["grid"]["%d:%d" % (m["rate"], m["quantum"])] = {
                "median": c.get("median"), "p95": (c.get("percentile") or {}).get("value"),
                "rt": {k: x.get(k) for k in ("swept", "allocations", "locks", "syscalls")}}
        ours.append(row)
    s["ours"] = sorted(ours, key=lambda o: (o["format"], o["id"], o["offer"]))

    # the probe documents: crash signals by step, the machine profile
    if a.records:
        sig = collections.Counter()
        gov = collections.Counter()
        for f in glob.glob(os.path.join(a.records, "*.probe.json")):
            with open(f) as fh:
                d = json.load(fh)
            sg = (d.get("crash") or {}).get("signal")
            if sg:
                step = next((st["step"] for st in d.get("steps", []) if st.get("signal") == sg), "?")
                sig["%s in %s" % (sg, step)] += 1
            prof = (d.get("machine") or {}).get("profile") or {}
            gov["governor=%s pinned=%s" % (prof.get("governor"), "probe.profile.not-pinned" not in prof.get("unmet", []))] += 1
        s["probe_documents"] = len(glob.glob(os.path.join(a.records, "*.probe.json")))
        s["crash_signals"] = dict(sig.most_common())
        s["machine_profile"] = dict(gov)

    def pins(path):
        out = collections.Counter()
        with open(path) as fh:
            for line in fh:
                if line.startswith("pin_set "):
                    m = re.search(r"verdict=(\S+)", line)
                    out[m.group(1) if m else "(no verdict)"] += 1
        return dict(out)
    if a.pins:
        s["pins"] = pins(a.pins)
    if a.system_pins:
        s["system_pins"] = pins(a.system_pins)
        ids = collections.Counter()
        with open(a.system_pins) as fh:
            for line in fh:
                m = re.match(r"pin_set clap:\S+#(\S+) ", line)
                if m:
                    ids[m.group(1)] += 1
        s["system_pins_clap_ids_shared"] = {k: n for k, n in ids.items() if n > 1}
    if a.sync_log:
        out = collections.Counter()
        codes = collections.Counter()
        with open(a.sync_log) as fh:
            for line in fh:
                m = re.match(r"plugin-qualify-sync: \S+: (qualified|refused|crashed)(?: \(([^)]*)\))?", line)
                if m:
                    out[m.group(1)] += 1
                    if m.group(2):
                        codes[m.group(2)] += 1
        s["sync"] = {"outcomes": dict(out), "codes": dict(codes.most_common())}
    if a.run_log:
        with open(a.run_log) as fh:
            m = re.search(r"plugin-qualify rc=(\d+)", fh.read())
        s["plugin_qualify_exit"] = int(m.group(1)) if m else None
    return s


def markdown(s):
    L = []
    hosts = list(s["verdicts"])
    L.append("| host profile | suitable | unsuitable | unknown | of |")
    L.append("|---|---|---|---|---|")
    for h in hosts:
        c = s["verdicts"][h]
        L.append("| %s | %d | %d | %d | %d |" % (h, c.get("suitable", 0), c.get("unsuitable", 0), c.get("unknown", 0), sum(c.values())))
    L.append("")
    L.append("| cost cell (format:rate:quantum) | points | p50 | p90 | p95 | p99 | max |")
    L.append("|---|---|---|---|---|---|---|")
    for k, c in s["cost"].items():
        L.append("| %s | %d | %s | %s | %s | %s | %s |" % (k, c["n"], c["p50"], c["p90"], c["p95"], c["p99"], c["max"]))
    L.append("")
    L.append("| plugin | format | 48000/512 median | 48000/512 p95 | 192000/512 median | 192000/512 p95 | per 512-frame block at 48000, median (us) | RT sweep (rate swept) |")
    L.append("|---|---|---|---|---|---|---|---|")

    def f(v):
        return "-" if v is None else "%.4g" % v
    for o in s["ours"]:
        if o["format"] == "clap" and o["offer"] != "default":
            continue
        g48 = o["grid"].get("48000:512") or {}
        g192 = o["grid"].get("192000:512") or {}
        if not g48 and not g192:
            L.append("| %s | %s | no grid point (%s) | | | | | |" % (o["id"], o["format"], o["outcome"]))
            continue
        rts = []
        for cell, g in sorted(o["grid"].items()):
            rt = g.get("rt")
            if not rt or not rt["swept"]:
                continue        # a CLAP probe sweeps at its first rate only, an LV2 probe at the one it measures
            rate = cell.split(":")[0]
            if rt["allocations"] or rt["locks"] or rt["syscalls"]:
                rts.append("%s: allocations %s, locks %s, syscalls %s" % (rate, rt["allocations"], rt["locks"], rt["syscalls"]))
            else:
                rts.append("clean at %s" % rate)
        blk = "%.2f" % (g48["median"] * 512 / 1000.0) if g48.get("median") is not None else "not measured"
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (o["id"], o["format"], f(g48.get("median")), f(g48.get("p95")),
                                                        f(g192.get("median")), f(g192.get("p95")), blk, "; ".join(rts) or "not swept"))
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qualify", required=True)
    ap.add_argument("--records")
    ap.add_argument("--pins")
    ap.add_argument("--system-pins")
    ap.add_argument("--sync-log")
    ap.add_argument("--run-log")
    ap.add_argument("--requested-rates")
    ap.add_argument("--requested-quanta")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown")
    a = ap.parse_args(argv)
    s = summarise(a)
    with open(a.out, "w") as fh:
        json.dump(s, fh, indent=1, sort_keys=False)
        fh.write("\n")
    if a.markdown:
        with open(a.markdown, "w") as fh:
            fh.write(markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())

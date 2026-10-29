#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""Draw the figures of docs/zynthian/benchmarks.md as SVG, from the summary qualify-summary.py writes.

    tools/zynthian/figures.py <summary.json> <out-dir> --date 2026-10-28 --source <path the caption cites>

No plotting library: the SVG is written directly, so the figures redraw on any machine with python3. Every figure
carries its data file and date in its caption. Four figures, one claim each:

  suitability.svg   verdicts per host profile and plugin format (stacked bars)
  cost-48k.svg      per-block cost of every CLAP plugin measured at 48000 Hz / 512 frames, sorted, ours marked
  rt-safety.svg     RT-safety outcome per qualification record, LV2 and CLAP (stacked bars)
  grid.svg          the grid: points measured per rate and quantum, against the grid the run asked for
  matrix-<scenario>-<measure>.svg   with --matrix: the matrix CSV of tools/zynthian/matrix.py, one panel per rate,
                    the measure per quantum, one line per host mode; a scenario with no measured cell says so
  grouped-vs-alone.svg   with --bench: the chains-vs-processes rows of an omx-bench/1 document at one rate: CPU, PSS,
                    processes and add time per host and mode, for 3, 8 and 16 plugins
"""
import argparse
import html
import json
import math
import os
import sys

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3de"
BLUE = "#2a78d6"     # suitable, clean
ORANGE = "#eb6834"   # unsuitable, violations
VIOLET = "#6250d6"   # crashed, timed out, refused instantiation
GREY = "#bdbcb4"     # unknown, not swept
RAMP = ["#e8f1fc", "#b9d4f4", "#7fb0ea", "#3f88dd", "#1f5fae"]   # one hue, light to dark
FONT = "font-family='DejaVu Sans, Helvetica, Arial, sans-serif'"


def esc(s):
    return html.escape(str(s), quote=True)


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h = w, h
        self.parts = ["<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' viewBox='0 0 %d %d' role='img' %s>"
                      % (w, h, w, h, FONT), "<title>%s</title>" % esc(title),
                      "<rect x='0' y='0' width='%d' height='%d' fill='%s'/>" % (w, h, SURFACE)]

    def text(self, x, y, s, size=12, fill=INK, anchor="start", weight="normal"):
        self.parts.append("<text x='%.1f' y='%.1f' font-size='%d' fill='%s' text-anchor='%s' font-weight='%s'>%s</text>"
                          % (x, y, size, fill, anchor, weight, esc(s)))

    def rect(self, x, y, w, h, fill, title=None, rx=0):
        t = "<title>%s</title>" % esc(title) if title else ""
        self.parts.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' rx='%d' fill='%s'>%s</rect>"
                          % (x, y, max(w, 0), max(h, 0), rx, fill, t))

    def line(self, x1, y1, x2, y2, stroke=GRID, width=1, dash=None):
        d = " stroke-dasharray='%s'" % dash if dash else ""
        self.parts.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='%s' stroke-width='%s'%s/>"
                          % (x1, y1, x2, y2, stroke, width, d))

    def raw(self, s):
        self.parts.append(s)

    def caption(self, lines):
        y = self.h - 14 * len(lines) + 2
        for ln in lines:
            self.text(16, y, ln, size=11, fill=INK2)
            y += 14

    def write(self, path):
        with open(path, "w") as fh:
            fh.write("\n".join(self.parts + ["</svg>"]) + "\n")


def legend(svg, x, y, items):
    for label, color in items:
        svg.rect(x, y - 10, 12, 12, color, rx=2)
        svg.text(x + 18, y, label, size=12, fill=INK)
        x += 18 + 7.2 * len(label) + 22


def stacked(svg, rows, cats, x0, y0, bar_w, bar_h, gap, label_w):
    """rows: [(label, {cat: n})]; one horizontal bar each, segments in the order of cats, counts written inside."""
    total = max(sum(c.values()) for _l, c in rows)
    for i, (label, counts) in enumerate(rows):
        y = y0 + i * (bar_h + gap)
        svg.text(x0 - 10, y + bar_h / 2 + 4, label, size=12, anchor="end")
        x = x0
        for cat, color in cats:
            n = counts.get(cat, 0)
            if not n:
                continue
            w = bar_w * n / total
            svg.rect(x, y, w - 2, bar_h, color, title="%s, %s: %d" % (label, cat, n))
            if w > 28:
                svg.text(x + w / 2 - 1, y + bar_h / 2 + 4, str(n), size=11, fill="#ffffff" if color != GREY else INK, anchor="middle")
            x += w
        svg.text(x + 6, y + bar_h / 2 + 4, "%d" % sum(counts.values()), size=11, fill=INK2)


CLASSES = [("suitable", BLUE), ("isolated", ORANGE), ("unsuitable", VIOLET), ("format not hosted", GREY), ("unknown", "#e4e3de")]
RULE = "isolated = fails the RT-safety sweep, runs in its own worker, never grouped; unsuitable = crashes, hangs, load failures (plugin-qualify#196)."


def fig_suitability(s, out, cap):
    hosts = list(s["classes_by_format"])
    rows = []
    for fmt in ("lv2", "clap"):
        for h in hosts:
            c = s["classes_by_format"][h]
            rows.append(("%s, %s" % (fmt.upper(), h), {k.split(":", 1)[1]: v for k, v in c.items() if k.startswith(fmt + ":")}))
    svg = Svg(860, 80 + len(rows) * 34 + 84, "Classes per host profile")
    svg.text(16, 28, "Suitable, isolated, unsuitable per host profile and plugin format, Raspberry Pi 5", size=15, weight="bold")
    legend(svg, 16, 54, CLASSES)
    stacked(svg, rows, CLASSES, 230, 72, 560, 24, 10, 210)
    svg.caption(cap + [RULE, "omx-clap-host is the profile of plugin-hostd's worker; jalv and mod-host do not load CLAP."])
    svg.write(os.path.join(out, "suitability.svg"))


def fig_cost(s, out, cap):
    cell = s["cost"].get("clap:48000:512")
    vals = cell["sorted"]
    ours = sorted([o for o in s["ours"] if o["format"] == "clap" and o["offer"] == "default" and (o["grid"].get("48000:512") or {}).get("median") is not None],
                  key=lambda o: o["grid"]["48000:512"]["median"])
    W, H = 860, 520
    L, R, T, B = 80, 220, 60, 120
    pw, ph = W - L - R, H - T - B
    us = [v * 512 / 1000.0 for v in vals]
    lo, hi = 0.1, 10 ** math.ceil(math.log10(max(us)))
    def X(i):
        return L + pw * i / max(len(us) - 1, 1)
    def Y(v):
        v = max(v, lo)
        return T + ph * (1 - (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)))
    svg = Svg(W, H, "Per-block cost at 48 kHz, 512 frames")
    svg.text(16, 28, "Per-block cost of the CLAP plugins at 48000 Hz, 512 frames (median of 512 blocks)", size=15, weight="bold")
    budget = 512 / 48000.0 * 1e6
    d = 0.1
    while d <= hi:
        svg.line(L, Y(d), L + pw, Y(d))
        svg.text(L - 8, Y(d) + 4, ("%g" % d), size=11, fill=INK2, anchor="end")
        d *= 10
    svg.text(20, T + ph / 2, "us per block", size=11, fill=INK2)
    if budget <= hi:
        svg.line(L, Y(budget), L + pw, Y(budget), stroke=INK2, width=1, dash="4 3")
        svg.text(L + 4, Y(budget) - 5, "the block's own duration, %.0f us" % budget, size=11, fill=INK2)
    pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(us))
    svg.raw("<polyline points='%s' fill='none' stroke='%s' stroke-width='2'/>" % (pts, BLUE))
    svg.line(L, T + ph, L + pw, T + ph, stroke=INK2)
    svg.text(L + pw / 2, T + ph + 30, "CLAP plugins measured at this cell, cheapest to dearest (%d)" % len(us), size=11, fill=INK2, anchor="middle")
    for q, label in ((0.5, "p50"), (0.95, "p95")):
        i = int(round(q * (len(us) - 1)))
        svg.line(X(i), T + ph, X(i), T + ph + 6, stroke=INK2)
        svg.text(X(i), T + ph + 18, label, size=10, fill=INK2, anchor="middle")
    # our plugins: a marker on the curve at their rank, named at the right
    ly = T + 4
    step = min(18, ph / max(len(ours), 1))
    for o in ours:
        v = o["grid"]["48000:512"]["median"] * 512 / 1000.0
        i = min(range(len(us)), key=lambda k: abs(us[k] - v))
        cx, cy = X(i), Y(v)
        svg.raw("<circle cx='%.1f' cy='%.1f' r='4.5' fill='%s' stroke='%s' stroke-width='2'><title>%s: %.2f us</title></circle>"
                % (cx, cy, ORANGE, SURFACE, esc(o["id"]), v))
        svg.text(L + pw + 14, ly + 4, "%s %.2f" % (o["id"].replace("org.openmixer.", "omx-"), v), size=10, fill=INK)
        svg.raw("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='%s' stroke-width='0.6'/>" % (cx, cy, L + pw + 10, ly, GREY))
        ly += step
    legend(svg, L, 50, [("all CLAP plugins with a cost at this cell", BLUE), ("our plugins (omx-*)", ORANGE)])
    svg.caption(cap + ["cost = probe median in ns per sample x 512 / 1000; no LV2 plugin was measured at 48000 Hz in this run (LV2: 192000 Hz only)."])
    svg.write(os.path.join(out, "cost-48k.svg"))


def fig_rt(s, out, cap):
    rows = []
    for key, label in (("lv2:default", "LV2"), ("clap:custom", "CLAP, plugin-hostd offer")):
        c = {}
        for k, n in s["rt_safety_records"].items():
            if k.startswith(key + ":"):
                what = k.split(":", 2)[2]
                what = {"clean": "suitable (clean)", "violations": "isolated (violations)"}.get(
                    what, "unsuitable (crashed, timed out, refused)" if what.startswith("probe.") else what)
                c[what] = c.get(what, 0) + n
        rows.append((label, c))
    cats = [("suitable (clean)", BLUE), ("isolated (violations)", ORANGE), ("unsuitable (crashed, timed out, refused)", VIOLET),
            ("not swept", GREY)]
    svg = Svg(860, 246, "RT-safety outcome per record")
    svg.text(16, 28, "RT-safety sweep outcome per qualification record, Raspberry Pi 5", size=15, weight="bold")
    legend(svg, 16, 54, cats)
    stacked(svg, rows, cats, 200, 74, 590, 28, 12, 180)
    svg.caption(cap + ["violations = an allocation, lock or syscall the interposer saw in the audio thread; not swept = measured with no sweep.", RULE])
    svg.write(os.path.join(out, "rt-safety.svg"))


def fig_grid(s, out, cap):
    rates = s["requested"]["rates"]
    quanta = s["requested"]["quanta"]
    W, H = 860, 330
    svg = Svg(W, H, "Grid measured against grid asked")
    svg.text(16, 28, "Grid points measured per rate and quantum, against the grid the run asked for", size=15, weight="bold")
    cw, chh = 74, 30
    top = {}
    for fi, fmt in enumerate(("lv2", "clap")):
        x0 = 120 + fi * 380
        y0 = 80
        svg.text(x0 + cw * len(quanta) / 2, y0 - 22, fmt.upper() + " records", size=13, weight="bold", anchor="middle")
        for qi, q in enumerate(quanta):
            svg.text(x0 + qi * cw + cw / 2, y0 - 6, str(q), size=11, fill=INK2, anchor="middle")
        mx = max(s["grid_points"].values())
        for ri, r in enumerate(rates):
            svg.text(x0 - 8, y0 + ri * chh + chh / 2 + 4, "%g kHz" % (r / 1000.0), size=11, fill=INK2, anchor="end")
            for qi, q in enumerate(quanta):
                n = s["grid_points"].get("%s:%d:%d" % (fmt, r, q), 0)
                if n:
                    color = RAMP[min(len(RAMP) - 1, 1 + int((len(RAMP) - 2) * n / mx))]
                else:
                    color = SURFACE
                svg.rect(x0 + qi * cw + 1, y0 + ri * chh + 1, cw - 2, chh - 2, color, title="%s %d Hz / %d: %d points" % (fmt, r, q, n))
                svg.raw("<rect x='%.1f' y='%.1f' width='%d' height='%d' fill='none' stroke='%s'/>" % (x0 + qi * cw + 1, y0 + ri * chh + 1, cw - 2, chh - 2, GRID))
                svg.text(x0 + qi * cw + cw / 2, y0 + ri * chh + chh / 2 + 4, str(n), size=11,
                         fill="#ffffff" if n and color in RAMP[3:] else INK, anchor="middle")
        svg.text(x0 + cw * len(quanta) / 2, y0 + len(rates) * chh + 18, "quantum (frames) across, rate down", size=10, fill=INK2, anchor="middle")
    svg.caption(cap + ["0 = asked for and not measured. The host profiles ask: jalv 48000/256, mod-host and omx-clap-host 48000/128, openmixer-console 96000/1024."])
    svg.write(os.path.join(out, "grid.svg"))


MODES = [(("H2", "chain"), "plugin-hostd, one worker for the chain", BLUE),
         (("H2", "individual"), "plugin-hostd, one worker per plugin", ORANGE),
         (("H1", "shared-process"), "omx-clap-host alone, one process", "#1baf7a"),
         (("H3", "shared-process"), "mod-host, one process", VIOLET),
         (("H4", "individual"), "jalv, one process per plugin", "#e87ba4")]


def fig_grouped(doc, bench_name, rate, out, date):
    rows = {}
    for r in doc["scenarios"]:
        if r["id"] in ("cvp3", "cvp8", "cvp16") and r["rate"] == rate and r.get("status") == "ok" \
                and r.get("stress", "none") in ("none", None):
            rows[(r["id"], r["host"], r.get("mode"))] = r
    sets = [x for x in ("cvp3", "cvp8", "cvp16") if any(k[0] == x for k in rows)]
    frames = sorted({r["frames"] for r in rows.values()})
    panels = [("cpu_pct", "CPU, percent of one core"), ("pss_mb_total", "proportional memory (PSS), MB"),
              ("processes", "processes"), ("add_ms", "time to add the plugins until they run, ms")]
    W, H = 900, 640
    svg = Svg(W, H, "Grouped versus alone")
    svg.text(16, 28, "Grouped versus alone: plugin-hostd, jalv, mod-host, at %d Hz, %s frames" % (rate, "/".join(map(str, frames))), size=15, weight="bold")
    lx, ly = 16, 52
    for _k, label, color in MODES:
        svg.rect(lx, ly - 10, 12, 12, color, rx=2)
        svg.text(lx + 17, ly, label, size=11)
        lx += 17 + 6.2 * len(label) + 18
        if lx > W - 200:
            lx, ly = 16, ly + 18
    pw, ph = 420, 210
    for pi, (key, title) in enumerate(panels):
        x0 = 40 + (pi % 2) * (pw + 30)
        y0 = 110 + (pi // 2) * (ph + 60)
        svg.text(x0, y0 - 8, title, size=12, weight="bold")
        vals = [rows[(sid, k[0], k[1])].get(key) for sid in sets for (k, _l, _c) in MODES if (sid, k[0], k[1]) in rows]
        vals = [v for v in vals if v is not None]
        top = max(vals) * 1.15 if vals else 1
        svg.line(x0, y0 + ph, x0 + pw, y0 + ph, stroke=INK2)
        gw = pw / max(len(sets), 1)
        bw = (gw - 24) / len(MODES)
        for si, sid in enumerate(sets):
            gx = x0 + si * gw + 12
            svg.text(gx + (gw - 24) / 2, y0 + ph + 16, "%s plugins" % sid[3:], size=11, fill=INK2, anchor="middle")
            for mi, (k, label, color) in enumerate(MODES):
                r = rows.get((sid, k[0], k[1]))
                v = r.get(key) if r else None
                bx = gx + mi * bw
                if v is None:
                    svg.text(bx + bw / 2, y0 + ph - 4, "n/a", size=9, fill=INK2, anchor="middle")
                    continue
                h = ph * v / top
                svg.rect(bx + 1, y0 + ph - h, bw - 2, h, color, title="%s, %s plugins: %s" % (label, sid[3:], v), rx=2)
                svg.text(bx + bw / 2, y0 + ph - h - 3, ("%.0f" % v) if v >= 100 else ("%.3g" % v), size=9, fill=INK, anchor="middle")
    svg.caption(["Data: %s, rows cvp3, cvp8, cvp16 without stress, measured %s (bench/run.sh, private JACK server on the dummy driver)." % (bench_name, date),
                 "Same plugins in each mode (omx-comp, Calf Compressor, omx-delay, omx-drive cycled; LV2 builds under mod-host and jalv). JACK clients and latency: see the table."])
    svg.write(os.path.join(out, "grouped-vs-alone.svg"))


MATRIX_MODES = [("plugin-hostd grouped", BLUE), ("plugin-hostd single", ORANGE), ("mod-host", VIOLET), ("jalv", "#e87ba4")]
MATRIX_MEASURES = {"cpu_pct": "CPU of the host processes, % of one core", "pss_mb_total": "proportional memory (PSS), MB",
                   "xruns": "xruns in the hold", "add_ms": "time to add the plugins until they run, ms",
                   "jack_clients": "JACK clients the host put on the graph"}


def fig_matrix(csv_path, scenario, measure, out, date, command):
    import csv as _csv
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path) as fh:
            rows = [r for r in _csv.DictReader(fh) if r["scenario"] == scenario and r["status"] == "ok" and r.get(measure) not in ("", None)]
    rates = [44100, 48000, 96000, 192000]
    quanta = [128, 256, 512, 1024]
    W, H = 900, 400
    svg = Svg(W, H, "Matrix %s %s" % (scenario, measure))
    svg.text(16, 28, "%s: %s, per rate and quantum" % (scenario, MATRIX_MEASURES[measure]), size=15, weight="bold")
    lx = 16
    for label, color in MATRIX_MODES:
        svg.rect(lx, 42, 12, 12, color, rx=2)
        svg.text(lx + 17, 52, label, size=11)
        lx += 17 + 6.2 * len(label) + 18
    if not rows:
        svg.text(W / 2, H / 2 - 10, "not measured yet", size=18, fill=INK2, anchor="middle", weight="bold")
        svg.text(W / 2, H / 2 + 16, command, size=11, fill=INK2, anchor="middle")
    else:
        vals = [float(r[measure]) for r in rows]
        top = max(vals) * 1.15 or 1
        pw, ph = 190, 220
        window = sorted({r["window_s"] for r in rows})
        for ri, rate in enumerate(rates):
            x0 = 50 + ri * (pw + 25)
            y0 = 90
            svg.text(x0 + pw / 2, y0 - 8, "%g kHz" % (rate / 1000.0), size=12, weight="bold", anchor="middle")
            svg.line(x0, y0 + ph, x0 + pw, y0 + ph, stroke=INK2)
            for frac in (0.5, 1.0):
                yv = top * frac / 1.15
                svg.line(x0, y0 + ph - ph * yv / top, x0 + pw, y0 + ph - ph * yv / top)
                if ri == 0:
                    svg.text(x0 - 4, y0 + ph - ph * yv / top + 4, "%.3g" % yv, size=10, fill=INK2, anchor="end")
            def X(q):
                return x0 + 12 + (pw - 24) * quanta.index(q) / (len(quanta) - 1)
            for q in quanta:
                svg.text(X(q), y0 + ph + 14, str(q), size=10, fill=INK2, anchor="middle")
            for label, color in MATRIX_MODES:
                pts = []
                for q in quanta:
                    m = [float(r[measure]) for r in rows if int(r["rate"]) == rate and int(r["frames"]) == q and r["host_mode"] == label]
                    if m:
                        pts.append((X(q), y0 + ph - ph * m[0] / top, m[0], q))
                if len(pts) > 1:
                    svg.raw("<polyline points='%s' fill='none' stroke='%s' stroke-width='2'/>" % (" ".join("%.1f,%.1f" % (x, y) for x, y, _v, _q in pts), color))
                for x, y, v, q in pts:
                    svg.raw("<circle cx='%.1f' cy='%.1f' r='4' fill='%s' stroke='%s' stroke-width='1.5'><title>%s, %d Hz / %d: %s</title></circle>"
                            % (x, y, color, SURFACE, esc(label), rate, q, v))
            missing = [q for q in quanta if not any(int(r["rate"]) == rate and int(r["frames"]) == q for r in rows)]
            if missing:
                svg.text(x0 + pw / 2, y0 + ph + 30, "not measured: %s" % ", ".join(map(str, missing)), size=9, fill=INK2, anchor="middle")
        svg.text(W / 2, 90 + ph + 46, "quantum (frames)", size=11, fill=INK2, anchor="middle")
    first = ("Data: %s, measured %s (tools/zynthian/matrix.py, private JACK server on the dummy driver, no sound card)." % (csv_path, date)
             if rows else "No cell of %s measured yet: %s holds none (tools/zynthian/matrix.py)." % (scenario, csv_path))
    svg.caption([first,
                 "One %s s hold per cell, one run per cell. Every mod-host row is the stock binary started by the bench on a private port." % (
                     "/".join(window) if rows else "60")])
    svg.write(os.path.join(out, "matrix-%s-%s.svg" % (scenario, measure)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("summary")
    ap.add_argument("out")
    ap.add_argument("--date", required=True, help="the date of the run the summary is of")
    ap.add_argument("--source", required=True, help="the data file the caption names")
    ap.add_argument("--bench", help="an omx-bench/1 document with the cvp3, cvp8, cvp16 rows")
    ap.add_argument("--bench-name", help="the path the caption names for --bench")
    ap.add_argument("--bench-date", help="the date of the --bench run")
    ap.add_argument("--bench-rate", type=int, default=48000)
    ap.add_argument("--matrix", help="the matrix.csv of tools/zynthian/matrix.py")
    ap.add_argument("--matrix-name", help="the path the caption names for --matrix")
    ap.add_argument("--matrix-date", help="the date of the matrix run")
    a = ap.parse_args(argv)
    with open(a.summary) as fh:
        s = json.load(fh)
    os.makedirs(a.out, exist_ok=True)
    q = s["inputs"]["qualify"]
    cap = ["Data: %s, from %s (sha256 %s...), measured %s." % (a.source, q["name"], q["sha256"][:16], a.date)]
    fig_suitability(s, a.out, cap)
    fig_cost(s, a.out, cap)
    fig_rt(s, a.out, cap)
    fig_grid(s, a.out, cap)
    if a.bench:
        with open(a.bench) as fh:
            fig_grouped(json.load(fh), a.bench_name or a.bench, a.bench_rate, a.out, a.bench_date or "")
    if a.matrix:
        command = "tools/zynthian/matrix.py --out <dir> --only chains"
        for scenario in ("chain-omx", "chain-tp"):
            for measure in ("cpu_pct", "pss_mb_total", "xruns", "jack_clients"):
                fig_matrix(a.matrix, scenario, measure, a.out, a.matrix_date or "", command)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The figures and the table of a Pi 5 stress run (tools/zynthian/stress-pi5.sh), from its summary.json alone.

    stress-figures.py <figure dir> <run dir> [<run dir> ...]

With several runs, each host mode is taken from the last run that holds it, and every run's idle baseline is kept;
the table names the run of each row.

Writes cpu.svg (busiest core and mean, percent), host-cpu.svg (the hosting processes, percent of one core), memory.svg (PSS and RSS of the hosting processes, MB),
creation.svg (seconds to build one chain) and xruns.svg, one line per host mode against the number of chains, and
prints the Markdown table of every level. Plain SVG: no plotting library is needed.
"""
import json
import os
import sys

MODES = ["grouped", "alone", "jalv"]
COLOURS = {"grouped": "#1f77b4", "alone": "#d62728", "jalv": "#2ca02c"}
W, H, L, R, T, B = 640, 360, 70, 140, 40, 50


def host_mem(rec, key):
    """the hosting processes only: the daemon and its workers, or the jalv processes"""
    m = rec.get("memory", {})
    return round(sum(m.get(g, {}).get(key, 0.0) for g in ("plugin-hostd", "workers", "jalv")), 1)


def host_cpu(rec):
    """CPU of the hosting processes over the hold, percent of one core (the scheduler's ns counters)"""
    g = rec.get("cpu_groups_pct_of_core", {})
    return round(sum(g.get(k, 0.0) for k in ("plugin-hostd", "workers", "jalv")), 1)


def svg(path, title, ylabel, series, xs):
    """series: [(label, colour, dash, [(x, y)])]; x on a log2 axis"""
    import math
    ymax = max([y for _, _, _, pts in series for _, y in pts] + [1.0]) * 1.1
    lx = [math.log2(x) for x in xs]
    x0, x1 = min(lx), max(lx) if max(lx) > min(lx) else min(lx) + 1

    def px(x):
        return L + (math.log2(x) - x0) / (x1 - x0) * (W - L - R)

    def py(y):
        return H - B - y / ymax * (H - T - B)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         f'<text x="{W / 2}" y="20" text-anchor="middle" font-size="14">{title}</text>',
         f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="black"/>',
         f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="black"/>',
         f'<text x="{(L + W - R) / 2}" y="{H - 12}" text-anchor="middle">chains of 4 plugins</text>',
         f'<text x="16" y="{(T + H - B) / 2}" text-anchor="middle" transform="rotate(-90 16 {(T + H - B) / 2})">'
         f'{ylabel}</text>']
    for x in xs:
        o.append(f'<text x="{px(x):.1f}" y="{H - B + 16}" text-anchor="middle">{x}</text>')
    for k in range(6):
        y = ymax * k / 5
        o.append(f'<line x1="{L - 4}" y1="{py(y):.1f}" x2="{W - R}" y2="{py(y):.1f}" stroke="#ddd"/>')
        o.append(f'<text x="{L - 6}" y="{py(y) + 4:.1f}" text-anchor="end">{y:.0f}</text>')
    for i, (label, colour, dash, pts) in enumerate(series):
        if pts:
            d = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in pts)
            o.append(f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="2"'
                     f'{" stroke-dasharray=" + chr(34) + dash + chr(34) if dash else ""}/>')
            for x, y in pts:
                o.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="{colour}"/>')
        ly = T + 10 + 18 * i
        o.append(f'<line x1="{W - R + 10}" y1="{ly}" x2="{W - R + 30}" y2="{ly}" stroke="{colour}" stroke-width="2"'
                 f'{" stroke-dasharray=" + chr(34) + dash + chr(34) if dash else ""}/>')
        o.append(f'<text x="{W - R + 34}" y="{ly + 4}">{label}</text>')
    o.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(o) + "\n")


def main():
    figs, runs = sys.argv[1], sys.argv[2:]
    os.makedirs(figs, exist_ok=True)
    rows, by = [], {}
    for run in runs:
        s = json.load(open(os.path.join(run, "summary.json")))
        name = os.path.basename(os.path.normpath(run))
        for r in s["levels"]:
            r["run"] = name
        rows += [r for r in s["levels"] if r["mode"] == "baseline"]
        for m in MODES:
            mine = sorted([r for r in s["levels"] if r["mode"] == m], key=lambda r: r["chains_asked"])
            if mine:
                by[m] = mine
    for m in MODES:
        by.setdefault(m, [])
        rows += by[m]
    xs = sorted({r["chains_asked"] for m in MODES for r in by[m]})

    def pts(m, f):
        return [(r["chains_asked"], f(r)) for r in by[m] if f(r) is not None]

    svg(os.path.join(figs, "cpu.svg"), "CPU over the hold: busiest core (solid) and mean of 4 (dashed)", "percent",
        [(f"{m} busiest", COLOURS[m], "", pts(m, lambda r: r["cpu_busiest_core"])) for m in MODES] +
        [(f"{m} mean", COLOURS[m], "5,4", pts(m, lambda r: r["cpu_mean"])) for m in MODES], xs)
    svg(os.path.join(figs, "host-cpu.svg"), "CPU of the hosting processes (daemon and workers, or jalv)",
        "percent of one core", [(m, COLOURS[m], "", pts(m, host_cpu)) for m in MODES], xs)
    svg(os.path.join(figs, "memory.svg"), "Memory of the hosting processes: PSS (solid) and RSS (dashed)", "MB",
        [(f"{m} PSS", COLOURS[m], "", pts(m, lambda r: host_mem(r, "pss_mb"))) for m in MODES] +
        [(f"{m} RSS", COLOURS[m], "5,4", pts(m, lambda r: host_mem(r, "rss_mb"))) for m in MODES], xs)
    svg(os.path.join(figs, "creation.svg"), "Seconds to build one chain of 4", "seconds",
        [(m, COLOURS[m], "", pts(m, lambda r: r["creation_s_per_chain"])) for m in MODES], xs)
    svg(os.path.join(figs, "xruns.svg"), "Xruns during the hold (the run's own JACK client)", "xruns",
        [(m, COLOURS[m], "", pts(m, lambda r: r["xruns_meter"])) for m in MODES], xs)

    print("| run | level | host mode | plugins | busiest core % | mean % | host CPU % of a core | JACK DSP % mean / max | host PSS MB | host RSS MB "
          "| RSS total MB | xruns (meter / Zynthian) | JACK clients | workers | build s (per chain) | limit |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        m = r["mode"]
        lvl = "idle" if m == "baseline" else str(r["chains_asked"])
        build = "-" if r.get("creation_s_total") is None else f'{r["creation_s_total"]} ({r["creation_s_per_chain"]})'
        workers = "-" if m in ("baseline", "jalv") else str(r["workers_mine"])
        print(f'| {r["run"]} | {lvl} | {m} | {r["plugins_running"]} | {r["cpu_busiest_core"]} | {r["cpu_mean"]} '
              f'| {host_cpu(r)} | {r["jack_dsp_mean"]} / {r["jack_dsp_max"]} | {host_mem(r, "pss_mb")} | {host_mem(r, "rss_mb")} '
              f'| {r["rss_total_mb"]} | {r["xruns_meter"]} / {r["xruns_zynthian"]} | {r["jack_clients"]} | {workers} '
              f'| {build} | {r.get("limit") or "-"} |')


if __name__ == "__main__":
    main()

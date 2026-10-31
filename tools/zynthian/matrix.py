#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
"""The Zynthian benchmark matrix: every rate and quantum, under jalv, mod-host, omx-clap-host (CLAP, and LV2 through
its adapter), plugin-hostd single and grouped.

    tools/zynthian/matrix.py --out DIR [--rates 44100,48000,96000,192000] [--frames 128,256,512,1024]
        [--window 60] [--only chains|singles|all] [--wait-idle] [--wait-update] [--after-stress] [--dry-run]

Runs bench/lib/bench.py (bench/README.md) once per cell, a cell being one scenario at one rate and one quantum on a
private JACK server of its own (the device's JACK and its chains are never touched), and appends one CSV row per
host and mode to DIR/matrix.csv. A cell already in the CSV with its document is not run again, so a stopped run resumes where it stopped; a cell
whose bench.py wrote no document is run again, and three such cells in a row stop the run. Resuming is per host: a cell
measured before a host joined the matrix is run again under that host alone, and its document is kept beside the
first one.
Each cell's omx-bench/1 document is kept under DIR/docs/ and every host's log under DIR/logs/.

The plugins are those of tools/zynthian/matrix/plugins.json: our omx-plugins in both forms and ten third-party LV2
effects. Host modes, as bench.py names them:

  jalv                      H4, one process per plugin (LV2)
  mod-host                  H3, the stock mod-host the image ships, started by the bench on a private port (LV2)
  omx-clap-host             H1, one omx-clap-host process for the scenario, CLAP forms
  omx-clap-host LV2         H1, the same, LV2 forms through its LV2 adapter
  plugin-hostd single       H2 individual, one worker per plugin, no chain declared
  plugin-hostd grouped      H2 chain, one worker for the chain

Scenarios, in the order they run: the two chains (all our plugins in series, CLAP forms under plugin-hostd and LV2 forms
under jalv and mod-host; the ten third-party plugins in series) over every rate and quantum, then each plugin alone
(our plugins once as CLAP and once as LV2 under omx-clap-host and plugin-hostd, as LV2 under jalv and mod-host) over
every rate and quantum.

--wait-update polls every 5 minutes before each cell until the device's mod-host unit starts plugin-hostd (the fork's
update script applied); the mod-host rows still run the stock binary, which the bench starts itself on a private port.
--after-stress waits until another lane's stress run has left a /root/omx-stress-* directory besides its -pre
snapshot, so the matrix starts only after that run. --wait-idle polls every 5 minutes before each cell while a process named stress-pi5 runs or a file under
/root/omx-stress-* was written in the last 10 minutes, so the run never overlaps another lane's measurement.

What a cell does not measure: the per-block cost of the plugin at that rate and quantum (the probe measures 512-frame
blocks only, plugin-qualify#193); the CSV holds JACK's DSP load and the host processes' CPU instead.
"""
import argparse
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BENCH = os.path.join(REPO, "bench")
COLUMNS = ["cell", "scenario", "kind", "host", "mode", "host_mode", "rate", "frames", "window_s", "status", "plugins",
           "dsp_load_avg", "dsp_load_max", "cpu_pct", "rss_mb_total", "pss_mb_total", "processes", "jack_clients",
           "xruns", "latency_frames", "add_ms", "ctx_switches", "note", "doc", "finished_at"]
HOST_MODE = {("H4", "individual"): "jalv", ("H4", None): "jalv", ("H3", "shared-process"): "mod-host",
             ("H3", None): "mod-host", ("H2", "individual"): "plugin-hostd single", ("H2", "chain"): "plugin-hostd grouped",
             ("H2", None): "plugin-hostd single", ("H1", "shared-process"): "omx-clap-host", ("H1", None): "omx-clap-host"}


def lv2_form(s, cat):
    """whether omx-clap-host and plugin-hostd run the scenario's LV2 forms: asked for, or no plugin of it has a CLAP one"""
    if s.get("format"):
        return s["format"] == "lv2"
    return not any("clap" in cat[k] for k in s["plugins"])


def host_mode(host, mode, s, cat):
    """the row's host and mode as the CSV names it; omx-clap-host's LV2 rows are its LV2 adapter's"""
    label = HOST_MODE.get((host, mode), host)
    return label + " LV2" if host == "H1" and lv2_form(s, cat) else label


def table(plugins):
    """the scenarios.json bench.py reads: the catalog of plugins and the matrix's scenarios"""
    base = json.load(open(os.path.join(BENCH, "scenarios.json")))
    cat = {}
    for p in plugins["ours"]:
        cat["omx-" + p] = {"name": "omx-" + p, "clap": "omx-%s.clap#org.openmixer.%s" % (p, p), "lv2": "urn:openmixer:" + p}
    for k, v in plugins["third_party"].items():
        cat[k] = {"name": v["name"], "lv2": v["lv2"]}
    ours = ["omx-" + p for p in plugins["ours"]]
    tp = list(plugins["third_party"])
    chain_modes = list(base["modes"]["chains-vs-processes"])
    scen = [
        {"id": "chain-omx", "kind": "chain", "title": "our %d plugins in series" % len(ours), "plugins": ours,
         "count": len(ours), "family": "matrix-chain"},
        {"id": "chain-tp", "kind": "chain", "title": "%d third-party LV2 plugins in series" % len(tp), "plugins": tp,
         "count": len(tp), "family": "matrix-chain"},
    ]
    for k in ours:
        scen.append({"id": "one-%s-clap" % k, "kind": "single", "title": "%s alone, CLAP" % k, "plugins": [k], "format": "clap",
                     "hosts": ["H1", "H2"]})
        scen.append({"id": "one-%s-lv2" % k, "kind": "single", "title": "%s alone, LV2" % k, "plugins": [k], "format": "lv2",
                     "hosts": ["H1", "H2", "H3", "H4"]})
    for k in tp:
        scen.append({"id": "one-%s" % k, "kind": "single", "title": "%s alone" % cat[k]["name"], "plugins": [k],
                     "hosts": ["H1", "H2", "H3", "H4"]})
    return {"plugins": cat, "midi": base["midi"], "scenarios": scen,
            "modes": {"matrix-chain": chain_modes, **base["modes"]}}


def bench_copy(work, tbl):
    """bench/ copied with the matrix's scenarios.json, so bench.py reads it as its own"""
    dst = os.path.join(work, "bench")
    shutil.copytree(BENCH, dst, ignore=shutil.ignore_patterns("examples", "tests", "report", "__pycache__"))
    with open(os.path.join(dst, "scenarios.json"), "w") as fh:
        json.dump({k: v for k, v in tbl.items()}, fh, indent=1)
    return dst


def bench_env():
    """what the copy of bench/ needs to find outside itself: bench.py reads the search lists through the repository's tool"""
    return {"SEARCH_PATHS_TOOL": os.path.join(REPO, "tools", "search-paths.py")}


def cells(tbl, rates, frames, only):
    out = []
    for kind in ("chain", "single"):
        if only not in ("all", kind + "s"):
            continue
        for rate in rates:
            for fr in frames:
                for s in tbl["scenarios"]:
                    if s["kind"] == kind:
                        out.append((s, rate, fr))
    return out


def cell_id(s, rate, fr):
    return "%s@%d/%d" % (s["id"], rate, fr)


def hosts_of(s, tbl):
    """the hosts a scenario runs under: its own list, else the hosts of the chain modes"""
    return s.get("hosts") or sorted({m["host"] for m in tbl["modes"]["matrix-chain"]})


def done_hosts(path):
    """cell -> the hosts measured in it; a row with no document did not measure (bench.py could not start)"""
    done = {}
    if not os.path.exists(path):
        return done
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row.get("doc") and row.get("host"):
                done.setdefault(row["cell"], set()).add(row["host"])
    return done


def left(tbl, rates, frames, only, done):
    """(scenario, rate, quantum, hosts not yet measured) for each cell with any host left"""
    out = []
    for s, rate, fr in cells(tbl, rates, frames, only):
        missing = [h for h in hosts_of(s, tbl) if h not in done.get(cell_id(s, rate, fr), set())]
        if missing:
            out.append((s, rate, fr, missing))
    return out


def doc_name(s, rate, fr, hosts, all_hosts):
    """a cell's document file; one measuring some of its hosts names them, so it never replaces the first"""
    base = cell_id(s, rate, fr).replace("/", "-").replace("@", "-")
    return "%s.json" % (base if list(hosts) == list(all_hosts) else base + "-" + "-".join(hosts))


def busy():
    """another lane's measurement on the device: a stress-pi5 process, or a /root/omx-stress-* file written lately"""
    if subprocess.run(["pgrep", "-f", "stress-pi5"], stdout=subprocess.DEVNULL).returncode == 0:
        return "a stress-pi5 process runs"
    now = time.time()
    for d in glob.glob("/root/omx-stress-*"):
        for root, _dirs, names in os.walk(d):
            for n in names:
                try:
                    if now - os.path.getmtime(os.path.join(root, n)) < 600:
                        return "%s was written in the last 10 minutes" % os.path.join(root, n)
                except OSError:
                    pass
    return None


def stress_pending():
    """the other lane's stress measurement has not run yet: no /root/omx-stress-* directory but its -pre snapshot"""
    runs = [d for d in glob.glob("/root/omx-stress-*") if os.path.isdir(d) and not d.endswith("-pre")]
    return None if runs else "no stress run under /root/omx-stress-* yet (only its -pre snapshot)"


def update_pending():
    """the device's mod-host unit does not start plugin-hostd yet: the fork's update script has not been applied"""
    p = subprocess.run(["systemctl", "cat", "mod-host"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return None if "plugin-hostd" in p.stdout else "the mod-host unit does not start plugin-hostd yet"


def log(msg):
    print("matrix: %s %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg), flush=True)


def run_cell(bench_dir, s, rate, fr, a, docs, logs, hosts, all_hosts):
    with tempfile.TemporaryDirectory(dir=a.out) as tmp:
        argv = [sys.executable, "-I", os.path.join(bench_dir, "lib", "bench.py"), "--class", "rpi5", "--out", tmp,
                "--rates", str(rate), "--frames", str(fr), "--scenarios", s["id"], "--hosts", ",".join(hosts),
                "--repeats", "1", "--window", str(a.window), "--stress", "none", "--keep-governor",
                "--logs", os.path.join(logs, cell_id(s, rate, fr).replace("/", "-"))]
        # bench.py's work directory goes under the cell's own temporary directory, removed with it
        env = dict(os.environ, TMPDIR=tmp, **bench_env())
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        with open(os.path.join(logs, "bench.out"), "a") as fh:
            fh.write("$ %s\n%s\nexit %d\n" % (" ".join(argv), p.stdout, p.returncode))
        found = [f for f in glob.glob(os.path.join(tmp, "*.json")) if os.path.isfile(f)]
        if not found:
            return None, "bench.py exited %d and wrote no document" % p.returncode
        name = doc_name(s, rate, fr, hosts, all_hosts)
        shutil.move(found[0], os.path.join(docs, name))
        return os.path.join(docs, name), None


def rows_of(doc_path, s, rate, fr, window, cat):
    with open(doc_path) as fh:
        doc = json.load(fh)
    out = []
    for r in doc["scenarios"]:
        out.append({
            "cell": cell_id(s, rate, fr), "scenario": s["id"], "kind": s["kind"], "host": r["host"], "mode": r.get("mode", ""),
            "host_mode": host_mode(r["host"], r.get("mode"), s, cat), "rate": rate, "frames": fr, "window_s": window,
            "status": r["status"], "plugins": len(r.get("plugins", [])),
            **{k: r.get(k, "") if r.get(k) is not None else "" for k in ("dsp_load_avg", "dsp_load_max", "cpu_pct", "rss_mb_total",
                                                                         "pss_mb_total", "processes", "jack_clients", "xruns",
                                                                         "latency_frames", "add_ms", "ctx_switches")},
            "note": r.get("note", ""), "doc": os.path.basename(doc_path),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rates", default="44100,48000,96000,192000")
    ap.add_argument("--frames", default="128,256,512,1024")
    ap.add_argument("--window", type=int, default=60, help="seconds each cell holds the plugins running (60)")
    ap.add_argument("--only", choices=["chains", "singles", "all"], default="all")
    ap.add_argument("--plugins", default=os.path.join(HERE, "matrix", "plugins.json"))
    ap.add_argument("--wait-idle", action="store_true", help="wait while another lane measures on the device")
    ap.add_argument("--wait-update", action="store_true",
                    help="wait until the mod-host unit starts plugin-hostd (the fork's update script applied)")
    ap.add_argument("--after-stress", action="store_true",
                    help="wait until another lane's stress run has a /root/omx-stress-* directory of its own (not -pre)")
    ap.add_argument("--quiet-polls", type=int, default=4,
                    help="polls in a row, 5 minutes apart, the device must be quiet before the first cell (4)")
    ap.add_argument("--dry-run", action="store_true", help="list the cells left to run and exit")
    a = ap.parse_args(argv)
    rates = [int(x) for x in a.rates.split(",")]
    frames = [int(x) for x in a.frames.split(",")]
    tbl = table(json.load(open(a.plugins)))
    os.makedirs(a.out, exist_ok=True)
    csv_path = os.path.join(a.out, "matrix.csv")
    done = done_hosts(csv_path)
    todo = left(tbl, rates, frames, a.only, done)
    if a.dry_run:
        for s, rate, fr, hosts in todo:
            print("%s %s" % (cell_id(s, rate, fr), ",".join(hosts)))
        print("%d cells left, %d done" % (len(todo), len(done)), file=sys.stderr)
        return 0
    docs, logs = os.path.join(a.out, "docs"), os.path.join(a.out, "logs")
    os.makedirs(docs, exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    work = tempfile.mkdtemp(prefix="omx-matrix-")
    try:
        bench_dir = bench_copy(work, tbl)
        log("%d cells left, %d done" % (len(todo), len(done)))
        lost = 0
        quiet = 0
        quiet_needed = True
        for s, rate, fr, hosts in todo:
            # before the first cell the device must have been quiet for --quiet-polls polls in a row; between cells one
            while a.wait_idle or a.wait_update or a.after_stress:
                why = (a.wait_update and update_pending()) or (a.after_stress and stress_pending()) or (a.wait_idle and busy())
                quiet = 0 if why else quiet + 1
                if not why and quiet >= (a.quiet_polls if quiet_needed else 1):
                    break
                log("waiting: %s" % (why or "quiet for %d of %d polls" % (quiet, a.quiet_polls)))
                time.sleep(300)
            quiet_needed = False
            log("cell %s %s" % (cell_id(s, rate, fr), ",".join(hosts)))
            doc, err = run_cell(bench_dir, s, rate, fr, a, docs, logs, hosts, hosts_of(s, tbl))
            lost = lost + 1 if err else 0
            if lost >= 3:
                log("three cells in a row wrote no document: stopping (see %s)" % os.path.join(logs, "bench.out"))
                return 1
            if err:
                log("cell %s: %s" % (cell_id(s, rate, fr), err))
                rows = [{"cell": cell_id(s, rate, fr), "scenario": s["id"], "kind": s["kind"], "rate": rate, "frames": fr,
                         "window_s": a.window, "status": "failed", "note": err,
                         "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]
            else:
                rows = rows_of(doc, s, rate, fr, a.window, tbl["plugins"])
            new = not os.path.exists(csv_path)
            with open(csv_path, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                for r in rows:
                    w.writerow(r)
            for r in rows:
                log("  %-22s %-6s dsp %s cpu %s pss %s clients %s xruns %s add %s %s" % (
                    r.get("host_mode", ""), r["status"], r.get("dsp_load_avg"), r.get("cpu_pct"), r.get("pss_mb_total"),
                    r.get("jack_clients"), r.get("xruns"), r.get("add_ms"), r.get("note", "")))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

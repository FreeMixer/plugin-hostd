#!/usr/bin/env python3
"""Writes the Zynthian acceptance report (report.md and report.html) from measurement files.

Every number in the report is read from a file named below; the prose only holds
facts listed in facts.json with their source. A section whose data does not exist
prints "not measured yet". With --strict the exit code is 1 when any section is
missing, so nothing unmeasured is published.

Inputs (all arguments, none has a default location; see --help):
  --bench PATH       omx-bench/1 documents (files or directories); the newest of class rpi5 is used
  --results DIR      the device notes (grouped-vs-processes.md is read, never written)
  --earlier DIR      hand-run outputs (zy-96test*.out, zy-qpilot.out) from the Pi 5
  --qualification DIR  plugin-qualify interchange documents (lv2-plugin-measurements)
  --coverage FILE    LV2 coverage summary.txt
  --prs FILE         pull request states (written by --fetch-prs)
"""
import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys
import time

NOT_YET = "not measured yet"
HOSTS = [("H1", "omx-clap-host alone"), ("H2", "plugin-hostd"), ("H3", "mod-host"), ("H4", "jalv")]
HOST_FAMILY = ["idle", "clap1", "lv2-1", "chain3", "clap16"]


# ---------------------------------------------------------------- readers

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(REPO, "bench", "schema", "omx-bench.v1.schema.json")


def _need(obj, keys, where, errs):
    """Every key of keys must be in obj; each missing one is an error naming the key and the file."""
    if not isinstance(obj, dict):
        errs.append("%s: expected an object" % where)
        return False
    ok = True
    for k in keys:
        if k not in obj:
            errs.append("%s: missing key '%s'" % (where, k))
            ok = False
    return ok


def validate_bench(d, path, errs):
    """The required keys of the omx-bench/1 schema, read from the schema file, in the document and in each row."""
    with open(SCHEMA) as fh:
        sch = json.load(fh)
    n = len(errs)
    _need(d, sch["required"], path, errs)
    if "machine" in d:
        _need(d["machine"], sch["properties"]["machine"]["required"], path + ": machine", errs)
    if "software" in d:
        _need(d["software"], sch["properties"]["software"]["required"], path + ": software", errs)
    row_keys = sch["properties"]["scenarios"]["items"]["required"]
    for i, r in enumerate(d.get("scenarios", [])):
        where = "%s: scenarios[%d]" % (path, i)
        if _need(r, ["id", "host"], where, errs):
            where += " (%s %s)" % (r["id"], r["host"])
            _need(r, row_keys, where, errs)
            if r.get("status") == "ok":
                for k in ("dsp_load_avg", "dsp_load_max", "rss_mb"):
                    if r.get(k) is None:
                        errs.append("%s: status ok but '%s' is null or missing" % (where, k))
    return len(errs) == n


def load_bench(paths, errs):
    docs = []
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in names if n.endswith(".json")]
        elif os.path.isfile(p):
            files.append(p)
        else:
            errs.append("%s: no such file or directory" % p)
    for f in sorted(set(files)):
        try:
            with open(f) as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            errs.append("%s: not readable JSON: %s" % (f, e))
            continue
        if isinstance(d, dict) and d.get("schema") == "omx-bench/1":
            if isinstance(d.get("scenarios"), list) and validate_bench(d, f, errs):
                d["_file"] = f
                docs.append(d)
            elif not isinstance(d.get("scenarios"), list):
                errs.append("%s: missing key 'scenarios' (a list)" % f)
    return docs


def latest_of_class(docs, cls):
    sel = [d for d in docs if d["machine"]["class"] == cls]
    return max(sel, key=_id_order) if sel else None


def _id_order(d):
    """rpi5-20261027-10 is newer than rpi5-20261027-9: order by the date, then the number as a number."""
    m = re.fullmatch(r"[a-z0-9]+-([0-9]{8})-([0-9]+)", d["id"])
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def _read(path):
    try:
        with open(path, errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def parse_earlier(dirpath):
    """Hand runs on the Pi 5: per rate the 3-plugin chain and Pianoteq, with the file they came from."""
    runs = {}
    for f in sorted(glob.glob(os.path.join(dirpath, "zy-96test*.out"))):
        text = _read(f)
        if not text:
            continue
        m = re.search(r"uri: (\S+)", text)
        uri = m.group(1) if m else None
        g = re.search(r"governor: \w+ -> (\w+)", text)
        gov = g.group(1) if g else "not recorded in the file"
        for block in re.split(r"(?m)^=== ", text)[1:]:
            h = re.match(r"(\d+) Hz, (\d+) frames", block)
            if not h:
                continue
            rate, frames = int(h.group(1)), int(h.group(2))
            r = runs.setdefault(rate, {"frames": frames})
            c = re.search(r"3-plugin chain \+ sine:\s+avg ([\d.]+)% max ([\d.]+)% \((\d+) samples\)", block)
            if c:
                r["chain3"] = {"avg": float(c.group(1)), "max": float(c.group(2)), "n": int(c.group(3)), "src": os.path.basename(f), "gov": gov}
            add = re.search(r"add PIANOTEQ lv2 \(\d+\): resp (-?\d+)", block)
            p = re.search(r"Pianoteq 5-note chords:\s+avg ([\d.]+)% max ([\d.]+)% \((\d+) samples\)", block)
            if add and p and int(add.group(1)) >= 0:
                r["pianoteq"] = {"avg": float(p.group(1)), "max": float(p.group(2)), "n": int(p.group(3)), "src": os.path.basename(f), "uri": uri}
    return {"runs": runs} if runs else None


def parse_qpilot(dirpath):
    text = _read(os.path.join(dirpath, "zy-qpilot.out"))
    if not text:
        return None
    sec = re.search(r"seconds=(\d+)", text)
    ex = re.search(r"exit=(-?\d+)", text)
    counts = {}
    summary = text.split("-- verdict summary", 1)[-1].split("-- sample", 1)[0]
    for m in re.finditer(r"(?m)^\s+(\d+) (suitable|unsuitable|conditional|unknown)\s*$", summary):
        counts[m.group(2)] = int(m.group(1))
    reasons = {}
    sample = text.split("-- sample", 1)[-1].split("-- stderr", 1)[0]
    for line in sample.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] in ("unsuitable", "conditional", "unknown"):
            reasons[parts[2]] = reasons.get(parts[2], 0) + 1
    if not counts:
        return None
    return {"seconds": int(sec.group(1)) if sec else None, "exit": int(ex.group(1)) if ex else None, "counts": counts, "sample_reasons": reasons}


def parse_qdocs(dirpath, errs):
    """Verdict counts and deciding reasons from plugin-qualify interchange documents."""
    counts, reasons, n, ndocs, hosts = {}, {}, 0, 0, set()
    for f in sorted(glob.glob(os.path.join(dirpath, "**", "*.json"), recursive=True)):
        try:
            with open(f) as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            errs.append("%s: not readable JSON: %s" % (f, e))
            continue
        if not isinstance(d, dict) or "verdicts" not in d:
            errs.append("%s: missing key 'verdicts'" % f)
            continue
        ndocs += 1
        for i, v in enumerate(d["verdicts"]):
            where = "%s: verdicts[%d]" % (f, i)
            if not _need(v, ["rating"], where, errs):
                continue
            if v["rating"] != "suitable" and not _need(v, ["deciding"], where + " (%s)" % v["rating"], errs):
                continue
            n += 1
            if isinstance(v, dict) and v.get("host"):
                hosts.add(v["host"])
            counts[v["rating"]] = counts.get(v["rating"], 0) + 1
            if v["rating"] != "suitable":
                reasons[v["deciding"]] = reasons.get(v["deciding"], 0) + 1
    return {"counts": counts, "reasons": reasons, "verdicts": n, "documents": ndocs, "hosts": sorted(hosts)} if n else None


def parse_coverage(path):
    text = _read(path)
    if not text:
        return None
    out = {}
    m = re.search(r"jalv [\d.]+ .*?\n\s+hosted (\d+) of (\d+)", text, re.S)
    if m:
        out["jalv"] = (int(m.group(1)), int(m.group(2)))
    m = re.search(r"mod-host [\d.]+ .*?\n\s+hosted (\d+) of (\d+)", text, re.S)
    if m:
        out["mod-host"] = (int(m.group(1)), int(m.group(2)))
    m = re.search(r"omx-clap-core: (\d+) of (\d+)", text)
    if m:
        out["omx-clap-core"] = (int(m.group(1)), int(m.group(2)))
    return out if len(out) == 3 else None


def fetch_prs(facts, out_path, run=subprocess.run):
    rows = []
    for p in facts["prs"]:
        r = run(["gh", "pr", "view", str(p["number"]), "-R", p["repo"], "--json",
                 "number,title,state,baseRefName,headRefName,url"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("gh failed for %s#%s: %s" % (p["repo"], p["number"], r.stderr.strip()))
        d = json.loads(r.stdout)
        d["repo"] = p["repo"]
        rows.append(d)
    with open(out_path, "w") as fh:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "prs": rows}, fh, indent=1)


# ---------------------------------------------------------------- model

class Doc:
    def __init__(self):
        self.blocks = []
        self.missing = []
        self.errors = []
        self.partial = []
        self.section = ""

    def h1(self, t): self.blocks.append(("h1", t))
    def h2(self, t): self.section = t; self.blocks.append(("h2", t))
    def h3(self, t): self.blocks.append(("h3", t))
    def p(self, t): self.blocks.append(("p", t))
    def quote(self, t): self.blocks.append(("quote", t))
    def table(self, head, rows): self.blocks.append(("table", head, rows))
    def bars(self, title, items, unit): self.blocks.append(("bars", title, items, unit))
    def ul(self, items): self.blocks.append(("ul", items))

    def na(self, what):
        self.missing.append("%s: %s" % (self.section, what))
        self.blocks.append(("na", "%s: %s." % (what, NOT_YET)))


def opt(s, key):
    """An optional schema key of a row: its value, or n/a when the run did not record it."""
    return str(s[key]) if s.get(key) is not None else "n/a"


def num(v, d=1):
    if v is None:
        return "n/a"
    s = ("%." + str(d) + "f") % v
    return s


# ---------------------------------------------------------------- sections

def stated(doc, facts, key):
    """A section of statements: each is a line of facts.json with the public pull request it restates."""
    doc.ul(["%s (%s)" % (s["text"], s["source"]) for s in facts["statements"][key]])


def sec_change(doc, facts, prs):
    doc.h2("1. What we change")
    doc.p("Sections 1, 2, 5 and 6 restate what the pull requests below say; each line names its pull request. "
          "They are not measurements. Sections 3 and 4 hold the measurements, every number read from the files named in the tool's help.")
    stated(doc, facts, "change")


def sec_user(doc, facts):
    doc.h2("2. What the user gets")
    stated(doc, facts, "user")


SCENARIOS = os.path.join(REPO, "bench", "scenarios.json")
# the grid of the acceptance run: the defaults of bench/run.sh
GRID_RATES = (48000, 96000)
GRID_FRAMES = (128, 256)
GRID_HOSTS = tuple(h for h, _n in HOSTS)


def expected_cells():
    """Every row the bench writes for a full run of its scenarios.json over the grid, as
    (scenario id, host, mode, rate, frames, stressed)."""
    with open(SCENARIOS) as fh:
        table = json.load(fh)
    cells = []
    for sc in table["scenarios"]:
        for stressed in ((False, True) if sc.get("stress") else (False,)):
            if sc.get("family"):
                combos = [(m["host"], m["mode"]) for m in table["modes"][sc["family"]]]
            else:
                combos = [(h, None) for h in GRID_HOSTS]
            for host, mode in combos:
                for rate in GRID_RATES:
                    for frames in GRID_FRAMES:
                        cells.append((sc["id"], host, mode, rate, frames, stressed))
    return cells


def completeness(rpi):
    """Why a run is partial: absent rows, a host or scenario with no measured row, measured rows without xruns or latency.
    An empty list is a complete run."""
    cells = expected_cells()
    moded = {c[0] for c in cells if c[2]}      # the families: their rows are told apart by mode
    have = {(s["id"], s["host"], s.get("mode") if s["id"] in moded else None, s["rate"], s["frames"],
             s.get("stress") not in (None, "none")): s for s in rpi["scenarios"]}
    why = []
    absent = {}
    for c in cells:
        if c not in have:
            absent.setdefault((c[0], c[1], c[2], c[5]), []).append("%d/%d" % (c[3], c[4]))
    for (sid, host, mode, stressed), where in sorted(absent.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        why.append("%s %s%s%s: no row at %s" % (sid, host, " " + mode if mode else "", " under stress" if stressed else "", ", ".join(where)))
    for host in GRID_HOSTS:
        if not any(s["host"] == host and s["status"] == "ok" for s in rpi["scenarios"]):
            why.append("host %s: no row with status ok" % host)
    for sid in sorted({c[0] for c in cells}):
        if not any(s["id"] == sid and s["status"] == "ok" for s in rpi["scenarios"]):
            why.append("scenario %s: no row with status ok" % sid)
    for c in cells:
        s = have.get(c)
        if s is not None and s["status"] == "ok":
            if "xruns" not in s:
                why.append("%s %s %s %d/%d: ok row without xruns" % (c[0], c[1], c[2] or "", c[3], c[4]))
            if c[0] == "kill1" and s["recover_ms"] is None:
                why.append("kill1 %s %d/%d: ok row without recover_ms" % (c[1], c[3], c[4]))
            if s.get("latency_frames") is None:
                why.append("%s %s %s %d/%d: ok row without latency_frames" % (c[0], c[1], c[2] or "", c[3], c[4]))
    return why


def host_cell(s):
    if s is None:
        return "-"
    if s["status"] != "ok":
        return "%s (%s)" % (s["status"], s["note"])
    return None


def sec_measure(doc, facts, rpi, earlier, results_dir, ci_docs):
    doc.h2("3. Measurements")
    doc.p("DSP load is the JACK DSP load read with jack_cpu_load; memory is resident (RSS) and proportional (PSS) from /proc.")
    if rpi is None:
        doc.p("No omx-bench/1 run of class rpi5 exists yet.")
        if ci_docs:
            doc.p("Runs of other classes (%s) are not shown: they are not Pi 5 numbers." %
                  ", ".join(sorted(d["id"] for d in ci_docs)))
        meta = None
    else:
        meta = rpi
        m = rpi["machine"]
        sw = ", ".join("%s %s" % (k, v) for k, v in rpi["software"].items() if v)
        doc.p("Run %s on %s (%s, %d cores, %d MB RAM, %s, kernel %s), governor %s. Software: %s." % (
            rpi["id"], m["model"], m["cpu"], m["cores"], m["ram_mb"], m["os"], m["kernel"], m["governor"], sw))
    scen = rpi["scenarios"] if rpi else []
    if rpi is not None:
        for why in completeness(rpi):
            doc.partial.append(why)

    def pick(sid, host, rate, frames):
        for s in scen:
            if s["id"] == sid and s["host"] == host and s["rate"] == rate and s["frames"] == frames:
                return s
        return None

    # 3a four hosts
    doc.h3("The four hosts")
    keys = sorted({(s["id"], s["rate"], s["frames"], s["title"]) for s in scen if s["id"] in HOST_FAMILY},
                  key=lambda k: (HOST_FAMILY.index(k[0]), k[1], k[2]))
    if not keys:
        doc.na("CPU, RAM and process count for H1 omx-clap-host alone, H2 plugin-hostd, H3 mod-host, H4 jalv")
    else:
        head = ["scenario", "rate", "frames"] + [n for _h, n in HOSTS]
        for title, fn in (("CPU: DSP load, average (maximum), percent", lambda s: "%s (%s)" % (num(s["dsp_load_avg"], 2), num(s["dsp_load_max"], 2))),
                          ("RAM: resident memory of the host processes, MB (PSS in brackets when measured)",
                           lambda s: "%s%s" % (num(s.get("rss_mb_total")), (" (%s)" % num(s["pss_mb_total"])) if s.get("pss_mb_total") is not None else "")),
                          ("Processes", lambda s: str(s["processes"]) if s.get("processes") is not None else "n/a")):
            rows = []
            for sid, rate, frames, t in keys:
                row = [t, str(rate), str(frames)]
                for h, _n in HOSTS:
                    s = pick(sid, h, rate, frames)
                    c = host_cell(s)
                    row.append(fn(s) if c is None else c)
                rows.append(row)
            doc.h3(title)
            doc.table(head, rows)
        # bars for the CPU of the busiest scenario family
        items = []
        for sid, rate, frames, t in keys:
            for h, n in HOSTS:
                s = pick(sid, h, rate, frames)
                if s and s["status"] == "ok" and s["dsp_load_avg"] is not None:
                    items.append(("%s, %d Hz/%d, %s" % (sid, rate, frames, n), s["dsp_load_avg"]))
        doc.bars("DSP load, average", items, "%")
        if any(s["id"] == "kill1" for s in scen):
            doc.h3("Recovery after kill -9 of the process holding one plugin")
            doc.table(["host", "rate", "frames", "recover ms", "status", "note"],
                      [[dict(HOSTS)[s["host"]], str(s["rate"]), str(s["frames"]), num(s["recover_ms"], 0), s["status"], s["note"]]
                       for s in scen if s["id"] == "kill1"])
        else:
            doc.na("recovery time after a killed worker")
    # xruns and latency
    doc.h3("Xruns and latency")
    xr = [s for s in scen if s.get("xruns") is not None]
    if xr:
        doc.table(["scenario", "host", "rate", "frames", "xruns"],
                  [[s["id"], s["host"], str(s["rate"]), str(s["frames"]), str(s["xruns"])] for s in xr])
    else:
        doc.na("xruns per host")
    la = [s for s in scen if s.get("latency_frames") is not None]
    if la:
        doc.table(["scenario", "host", "rate", "frames", "declared latency to system:playback_1, frames", "ms (frames / rate)"],
                  [[s["id"], s["host"], str(s["rate"]), str(s["frames"]), str(s["latency_frames"]),
                    num(1000.0 * s["latency_frames"] / s["rate"], 2)] for s in la])
    else:
        doc.na("declared latency to system:playback_1 per host")

    # 3b grouped vs processes, without and with the stress load
    fam = [s for s in scen if s.get("mode") and s["id"][:3] in ("cvp", "grp")]
    head = ["set", "stress", "rate", "frames", "mode", "processes", "RSS MB", "PSS MB", "CPU % of a core", "DSP load %", "add ms"]

    def fam_rows(rows_in):
        out = []
        for s in sorted(rows_in, key=lambda x: (x["id"][:3], int(re.sub(r"\D", "", x["id"]) or 0), x["rate"], x["frames"], x["host"], x["mode"])):
            lead = [s["title"], s.get("stress", "not recorded"), str(s["rate"]), str(s["frames"]), s["host"] + " " + s["mode"]]
            if s["status"] != "ok":
                out.append(lead + [s["status"] + ": " + s["note"], "", "", "", "", ""])
            else:
                out.append(lead + [opt(s, "processes"), num(s.get("rss_mb_total")), num(s.get("pss_mb_total")),
                                   num(s.get("cpu_pct"), 2), num(s["dsp_load_avg"], 2), num(s["add_ms"], 0)])
        return out

    doc.h3("One worker for a chain against one process per plugin")
    calm = [s for s in fam if s.get("stress") in (None, "none")]
    if not calm:
        doc.na("grouped against individual processes (3, 8 and 16 plugins)")
    else:
        doc.table(head, fam_rows(calm))
    doc.h3("Under stress")
    loaded = [s for s in fam if s.get("stress") not in (None, "none")]
    if not loaded:
        doc.na("grouped against individual processes under stress")
    else:
        doc.table(head, fam_rows(loaded))
    for group in (calm, loaded):
        for key in sorted({(s["id"], s["rate"], s["frames"], s.get("stress", "not recorded")) for s in group}):
            pick2 = lambda mode: next((s for s in group if (s["id"], s["rate"], s["frames"], s.get("stress", "not recorded")) == key and s["host"] == "H2"
                                       and s["mode"] == mode and s["status"] == "ok"), None)
            ind, ch = pick2("individual"), pick2("chain")
            if ind and ch and ind.get("processes") and ch.get("processes") and ind.get("pss_mb_total") and ch.get("pss_mb_total"):
                doc.p("%s at %d Hz, %d frames, stress %s: the chain runs in %d process%s against %d, and uses %.2f times the proportional memory of the individual mode."
                      % (ind["title"], key[1], key[2], key[3], ch["processes"], "" if ch["processes"] == 1 else "es", ind["processes"],
                         ch["pss_mb_total"] / ind["pss_mb_total"]))
    gp = _read(os.path.join(results_dir, "grouped-vs-processes.md")) if results_dir else None
    if gp:
        doc.p("Device notes, read as written from grouped-vs-processes.md:")
        doc.quote(gp.strip())

    # 3c Pianoteq
    doc.h3("Pianoteq 9 at 48 and 96 kHz")
    rows = []
    for rate in (48000, 96000):
        mine = sorted([x for x in scen if x["id"] == "pianoteq" and x["rate"] == rate and x["status"] == "ok"], key=lambda x: (x["frames"], x["host"]))
        for s in mine:
            rows.append([str(rate), str(s["frames"]), dict(HOSTS)[s["host"]], num(s["dsp_load_avg"]), num(s["dsp_load_max"]), str(s["samples"]), rpi["id"]])
        if not mine and earlier and earlier["runs"].get(rate, {}).get("pianoteq"):
            e = earlier["runs"][rate]
            q = e["pianoteq"]
            rows.append([str(rate), str(e["frames"]), "plugin-hostd (hand run)", num(q["avg"]), num(q["max"]), str(q["n"]), q["src"]])
    if {r[0] for r in rows} == {"48000", "96000"}:
        doc.table(["rate", "frames", "host", "DSP load avg %", "max %", "samples", "source"], rows)
    else:
        doc.na("Pianoteq 9 at both rates")
    # hand-run chain3 when the bench doc has none
    if earlier and not any(s["id"] == "chain3" and s["host"] == "H2" for s in scen):
        r = [[str(rate), str(e["frames"]), e["chain3"]["gov"], num(e["chain3"]["avg"]), num(e["chain3"]["max"]), str(e["chain3"]["n"]), e["chain3"]["src"]]
             for rate, e in sorted(earlier["runs"].items()) if e.get("chain3")]
        if r:
            doc.p("Hand run of the three-plugin chain under plugin-hostd:")
            doc.table(["rate", "frames", "governor", "DSP load avg %", "max %", "samples", "source"], r)


def sec_qual(doc, facts, rpi, qpilot, qdocs, coverage):
    doc.h2("4. Qualification coverage")
    counts = reasons = None
    seconds = None
    src = None
    if qdocs:
        counts, reasons, src = qdocs["counts"], qdocs["reasons"], "plugin-qualify documents (%d verdicts)" % qdocs["verdicts"]
    elif qpilot:
        counts, reasons, src = qpilot["counts"], None, "qualification run on the Pi 5, host profile openmixer-console (zy-qpilot.out)"
    if qpilot and not qdocs:
        seconds = qpilot["seconds"]     # the pilot's time is not the time of the documents' run
    elif rpi and "qualification" in rpi and not qdocs:
        seconds = rpi["qualification"]["seconds"]
    if not counts:
        doc.na("verdict counts")
    else:
        total = sum(counts.values())
        q = rpi["qualification"] if rpi and "qualification" in rpi and not qdocs else None
        extra = ""
        if q:
            extra = ", %s s, rates %s, quanta %s%s" % (num(seconds, 0), q["rates"], q["quanta"],
                                                      (", %d files" % q["files"]) if "files" in q else "")
        elif seconds is not None:
            extra = ", %s s" % num(seconds, 0)
        # a qualification record holds one verdict per host profile: then the counts are of verdicts, not of plugins
        unit = "verdicts" if qdocs and qdocs.get("hosts") else "plugins"
        if unit == "verdicts":
            doc.p("Source: %s. %d verdicts in %d documents, one per host profile (%s)%s." % (
                src, total, qdocs["documents"], ", ".join(qdocs["hosts"]), extra))
        else:
            doc.p("Source: %s. %d plugins judged%s." % (src, total, extra))
        if not qdocs and qpilot:
            if qpilot["exit"] is None:
                doc.missing.append("4. Qualification coverage: zy-qpilot.out records no exit status")
            elif qpilot["exit"] != 0:
                doc.p("The qualification run exited with status %d: these counts are of an aborted run." % qpilot["exit"])
                doc.missing.append("4. Qualification coverage: the qualification run exited with status %d" % qpilot["exit"])
        doc.table(["verdict", unit, "share"], [[k, str(v), "%.1f%%" % (100.0 * v / total)] for k, v in sorted(counts.items(), key=lambda kv: -kv[1])])
    doc.h3("Refused, with reasons")
    if reasons:
        doc.table(["deciding reason", "verdicts" if qdocs and qdocs.get("hosts") else "plugins"], [[k, str(v)] for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])])
    elif qpilot and qpilot["sample_reasons"]:
        doc.table(["deciding reason (first lines of the run's sample only)", "plugins in sample"], [[k, str(v)] for k, v in qpilot["sample_reasons"].items()])
        doc.na("the full reason breakdown of the unsuitable plugins (needs the interchange documents from the Pi 5)")
    else:
        doc.na("reasons for refused plugins")
    doc.h3("LV2 hosting coverage of the installed set")
    if coverage:
        doc.table(["host", "hosted", "of"], [[k, str(v[0]), str(v[1])] for k, v in coverage.items()])
    else:
        doc.na("LV2 coverage")


def sec_risk(doc, facts):
    doc.h2("5. Risk and how to revert")
    stated(doc, facts, "revert")


def sec_try(doc, facts):
    doc.h2("6. How to try it")
    stated(doc, facts, "try")


def sec_ask(doc, facts, prs, fetched_at):
    doc.h2("7. The pull requests")
    if not prs:
        doc.na("pull request states")
        return
    role = {(p["repo"], p["number"]): p["role"] for p in facts["prs"]}
    for p in prs:
        if (p["repo"], p["number"]) not in role:
            doc.errors.append("pull request file: %s#%s is not listed in facts.json" % (p["repo"], p["number"]))
            return
    doc.table(["repository", "PR", "what", "state", "base"],
              [[p["repo"], "#%d" % p["number"], role[(p["repo"], p["number"])], p["state"].lower(), p["baseRefName"]] for p in prs])
    doc.p("States as fetched at %s." % fetched_at)


def load_json(path, errs):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        errs.append("%s: not readable JSON: %s" % (path, e))
        return None


def build(args):
    errs = []
    facts = load_json(args.facts, errs)
    if facts is not None and _need(facts, ["prs", "statements"], args.facts, errs):
        for sec in ("change", "user", "revert", "try"):
            if _need(facts["statements"], [sec], args.facts + ": statements", errs):
                for i, st in enumerate(facts["statements"][sec]):
                    _need(st, ["text", "source"], "%s: statements.%s[%d]" % (args.facts, sec, i), errs)
        for i, p in enumerate(facts["prs"]):
            _need(p, ["repo", "number", "role"], "%s: prs[%d]" % (args.facts, i), errs)
    docs = load_bench(args.bench, errs)
    rpi = latest_of_class(docs, "rpi5")
    others = [d for d in docs if d is not rpi and d["machine"]["class"] != "rpi5"]
    earlier = parse_earlier(args.earlier) if args.earlier else None
    qpilot = parse_qpilot(args.earlier) if args.earlier else None
    qdocs = parse_qdocs(args.qualification, errs) if args.qualification and os.path.isdir(args.qualification) else None
    coverage = parse_coverage(args.coverage) if args.coverage else None
    prs = fetched_at = None
    if args.prs and os.path.isfile(args.prs):
        pr_doc = load_json(args.prs, errs)
        if pr_doc is not None and _need(pr_doc, ["prs", "fetched_at"], args.prs, errs):
            prs, fetched_at = pr_doc["prs"], pr_doc["fetched_at"]
            for i, p in enumerate(prs):
                _need(p, ["repo", "number", "title", "state", "baseRefName"], "%s: prs[%d]" % (args.prs, i), errs)
    if errs:
        doc = Doc()
        doc.errors = errs
        return doc
    doc = Doc()
    doc.h1("plugin-hostd, the PH engine, qualified menus and OpenMixer by default in Zynthian")
    sec_change(doc, facts, prs)
    sec_user(doc, facts)
    sec_measure(doc, facts, rpi, earlier, args.results, others)
    sec_qual(doc, facts, rpi, qpilot, qdocs, coverage)
    if doc.partial:
        doc.missing += ["3. Measurements: partial run: " + w for w in doc.partial]
        shown = doc.partial[:20]
        notice = ["This report is built from a partial run: %d reasons%s." % (len(doc.partial), "" if len(shown) == len(doc.partial) else ", the first %d listed" % len(shown))]
        doc.blocks.insert(1, ("p", notice[0]))
        doc.blocks.insert(2, ("ul", shown))
    sec_risk(doc, facts)
    sec_try(doc, facts)
    sec_ask(doc, facts, prs, fetched_at)
    return doc


# ---------------------------------------------------------------- renderers

def md_cell(c):
    return str(c).replace("|", "\\|").replace("\n", " ")


def to_md(doc):
    out = []
    for b in doc.blocks:
        k = b[0]
        if k == "h1": out.append("# " + b[1])
        elif k == "h2": out.append("## " + b[1])
        elif k == "h3": out.append("### " + b[1])
        elif k == "p": out.append(b[1])
        elif k == "na": out.append("*" + b[1] + "*")
        elif k == "quote": out.append("\n".join("> " + l for l in b[1].splitlines()))
        elif k == "ul": out.append("\n".join("- " + i for i in b[1]))
        elif k == "table":
            out.append("| " + " | ".join(md_cell(h) for h in b[1]) + " |\n|" + "---|" * len(b[1]) + "\n" +
                       "\n".join("| " + " | ".join(md_cell(c) for c in r) + " |" for r in b[2]))
        elif k == "bars":
            out.append("\n".join("- %s: %s%s" % (l, num(v, 2), b[3]) for l, v in b[2]) if b[2] else "")
    return "\n\n".join(x for x in out if x) + "\n"


CSS = """:root{--bg:#fff;--fg:#1d2129;--mut:#5b6573;--line:#d9dee5;--bar:#2b6cb0;--bgq:#f3f5f8}
@media(prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ee;--mut:#9aa4b2;--line:#2c333d;--bar:#6aa7e6;--bgq:#1c2128}}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;max-width:60rem;margin:0 auto;padding:1rem 16px 4rem}
h1{font-size:1.6rem}h2{margin-top:2.5rem;border-bottom:1px solid var(--line);padding-bottom:.2rem}h3{margin-top:1.6rem}
table{border-collapse:collapse;display:block;overflow-x:auto;font-size:.9rem}th,td{border:1px solid var(--line);padding:.25rem .5rem;text-align:left}
th{background:var(--bgq)}blockquote{background:var(--bgq);margin:1rem 0;padding:.5rem 1rem;white-space:pre-wrap;border-left:3px solid var(--line)}
.na{color:var(--mut);font-style:italic}svg text{fill:var(--fg);font-size:11px}.bar{fill:var(--bar)}"""


def svg_bars(items):
    if not items:
        return ""
    mx = max(v for _l, v in items) or 1.0
    w, lab, h = 560, 280, 18
    rows = []
    for i, (l, v) in enumerate(items):
        y = i * h
        bw = max(1.0, (w - lab - 60) * v / mx)
        rows.append('<text x="0" y="%d">%s</text><rect class="bar" x="%d" y="%d" width="%.1f" height="12"/>'
                    '<text x="%.1f" y="%d">%s</text>' % (y + 11, html.escape(l), lab, y, bw, lab + bw + 4, y + 11, num(v, 2)))
    return '<svg role="img" width="100%%" viewBox="0 0 %d %d" aria-label="bars">%s</svg>' % (w, h * len(items), "".join(rows))


def to_html(doc):
    e = html.escape
    out = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>Zynthian acceptance report</title><style>%s</style></head><body>" % CSS]
    for b in doc.blocks:
        k = b[0]
        if k in ("h1", "h2", "h3"): out.append("<%s>%s</%s>" % (k, e(b[1]), k))
        elif k == "p": out.append("<p>%s</p>" % e(b[1]))
        elif k == "na": out.append('<p class="na">%s</p>' % e(b[1]))
        elif k == "quote": out.append("<blockquote>%s</blockquote>" % e(b[1]))
        elif k == "ul": out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % e(i) for i in b[1]))
        elif k == "table":
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                "".join("<th>%s</th>" % e(h) for h in b[1]),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % e(str(c)) for c in r) for r in b[2])))
        elif k == "bars":
            out.append("<p>%s (%s)</p>%s" % (e(b[1]), e(b[3]), svg_bars(b[2])))
    out.append("</body></html>")
    return "\n".join(out)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="No input has a default location: every path is an argument, or (--facts) a file of this "
                                        "directory. An input that is not given is a section reported as not measured yet; one "
                                        "that is given and does not exist is an error.")
    ap.add_argument("--bench", nargs="+", metavar="PATH", help="omx-bench/1 documents, files or directories (required)")
    ap.add_argument("--results", metavar="DIR", help="directory holding grouped-vs-processes.md, quoted as written")
    ap.add_argument("--earlier", metavar="DIR", help="directory of the Pi 5 hand-run outputs")
    ap.add_argument("--qualification", metavar="DIR", help="directory of plugin-qualify interchange documents")
    ap.add_argument("--coverage", metavar="FILE", help="LV2 coverage summary.txt")
    ap.add_argument("--prs", metavar="FILE", help="pull request states: read by the report, written by --fetch-prs")
    ap.add_argument("--facts", default=os.path.join(here, "facts.json"), metavar="FILE",
                    help="the statements and their public sources (default: facts.json beside this script)")
    ap.add_argument("--out", metavar="DIR", help="directory report.md and report.html are written to (required)")
    ap.add_argument("--strict", action="store_true", help="validate first: when any section lacks data, print the reasons on stderr, write nothing and exit 1")
    ap.add_argument("--fetch-prs", action="store_true", help="refresh --prs with gh and exit")
    a = ap.parse_args(argv)
    if a.fetch_prs:
        if not a.prs:
            ap.error("--fetch-prs needs --prs FILE to write")
        with open(a.facts) as fh:
            fetch_prs(json.load(fh), a.prs)
        print("wrote", a.prs)
        return 0
    if not a.bench or not a.out:
        ap.error("--bench and --out are required")
    bad = ["--%s %s: no such %s" % (n, p, "directory" if d else "file") for n, p, d in
           (("results", a.results, True), ("earlier", a.earlier, True), ("qualification", a.qualification, True),
            ("coverage", a.coverage, False), ("prs", a.prs, False)) if p and not (os.path.isdir(p) if d else os.path.isfile(p))]
    if bad:
        for e in bad:
            print("invalid input:", e, file=sys.stderr)
        return 1
    doc = build(a)
    if doc.errors:
        for e in doc.errors:
            print("invalid input:", e, file=sys.stderr)
        return 1
    if a.strict and doc.missing:
        for x in doc.missing:
            print("strict: missing:", x, file=sys.stderr)
        print("strict: %d missing, nothing written" % len(doc.missing), file=sys.stderr)
        return 1
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "report.md"), "w") as fh:
        fh.write(to_md(doc))
    with open(os.path.join(a.out, "report.html"), "w") as fh:
        fh.write(to_html(doc))
    for m in doc.missing:
        print("missing:", m, file=sys.stderr)
    print("wrote %s/report.md and report.html; %d missing" % (a.out, len(doc.missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

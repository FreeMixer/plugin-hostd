"""The soundness gate of omx-bench/1 documents: a figure is published only when the cells around it agree with it.

A cell is one row at one rate, frame count, JACK period count and stress. The checks compare cells with each other,
because a cell disturbed as a whole (a throttled core, a stray interrupt, a busy neighbour) looks fine from inside:
its repeats were taken back to back on the same machine state.

  spread    the repeats of one cell differ by more than SPREAD_REL of their median
  twin      the same cell at another period count (the work of a cycle does not depend on it) or in another document
            differs from its twins by more than CELL_REL
  stress    the cell without stress reads higher than the same cell with it (stress can only add load)
  scaling   the cell reads higher than the same cell at fewer frames (a fixed set costs less a second the larger the
            cycle, the per-cycle overhead is shared)
  state     a repeat ran throttled or under-voltage, or the CPU frequency moved between repeats
  output    a cell that should make sound is silent, or its level differs from the same set run one process per plugin

A cell that breaks one is `unstable`: it is rerun alone, and one that still breaks is published as unstable and no
ratio is made from it. Everything here is a pure function of the documents."""

import statistics

SPREAD_REL = 0.10   # (max - min) / median of one cell
CELL_REL = 0.08     # distance of a cell from its twins, scaling and stress neighbours
FLOOR = 0.30        # DSP-load points below which a difference is noise, not disturbance
FREQ_REL = 0.05     # frequency range across the repeats of one cell
OUTPUT_DB = 1.0     # level difference of the output against the same set run one process per plugin
SILENT_DB = -90.0
THROTTLE_NOW = 0x7  # vcgencmd get_throttled: under-voltage, frequency capped, throttled, right now
OUTPUT_HOSTS = ("H1", "H2")  # same plugin builds: H3 and H4 run other builds of the effects, their level may differ


def cell(row, doc):
    jack = doc.get("jack") or {}
    return (row.get("id"), row.get("host"), row.get("mode"), row.get("rate"), row.get("frames"),
            jack.get("periods"), row.get("stress", "none"))


def usable(row):
    return row.get("status") == "ok" and isinstance(row.get("dsp_load_avg"), (int, float))


def entries(docs):
    out = []
    for d, doc in enumerate(docs):
        for n, row in enumerate(doc.get("scenarios", [])):
            if isinstance(row, dict) and usable(row):
                out.append(((d, n), row, cell(row, doc)))
    return out


def over(value, base, rel):
    """value is above base by more than rel of base, and by more than the noise floor"""
    return value - base > max(rel * base, FLOOR)


def spread_reasons(row):
    span = (row.get("spread") or {}).get("dsp_load_avg")
    avg = row["dsp_load_avg"]
    if span and avg > 0 and span[1] - span[0] > max(SPREAD_REL * avg, FLOOR):
        return ["spread: %.2f..%.2f is %.0f%% of the median %.2f, over %.0f%%" % (
            span[0], span[1], 100.0 * (span[1] - span[0]) / avg, avg, 100 * SPREAD_REL)]
    return []


def state_reasons(row):
    out = []
    freqs = []
    for n, st in enumerate(row.get("repeat_state") or [], 1):
        for phase in ("before", "after"):
            s = st.get(phase) or {}
            t = s.get("throttled")
            if isinstance(t, str):
                try:
                    bits = int(t, 16)
                except ValueError:
                    continue
                if bits & THROTTLE_NOW:
                    out.append("state: throttled %s (%s of repeat %d)" % (t, phase, n))
            f = s.get("freq_mhz")
            if f:
                freqs.extend(f)
    if freqs and min(freqs) < (1 - FREQ_REL) * max(freqs):
        out.append("state: CPU frequency %d..%d MHz across the repeats" % (min(freqs), max(freqs)))
    return list(dict.fromkeys(out))


def advisories(row):
    """not a verdict: what the machine state names as a candidate cause"""
    notes = []
    for st in row.get("repeat_state") or []:
        s = st.get("after") or {}
        irq = s.get("usb_irq_core")
        if irq is not None and irq in (s.get("host_cores") or []):
            notes.append("a thread of the host ran on core %d, the one that takes the USB interrupt" % irq)
    return list(dict.fromkeys(notes))


def check_row(row):
    """what one row says against itself: its spread and the machine state of its repeats"""
    return spread_reasons(row) + state_reasons(row) if usable(row) else []


def check(docs):
    """{(document, row): [reasons]} for every cell that breaks a check; docs is a list of parsed documents"""
    es = entries(docs)
    bad = {}

    def flag(ref, why):
        bad.setdefault(ref, [])
        if why not in bad[ref]:
            bad[ref].append(why)

    for ref, row, _ in es:
        for why in spread_reasons(row) + state_reasons(row):
            flag(ref, why)

    # twins: the same cell, whatever the period count
    groups = {}
    for ref, row, c in es:
        groups.setdefault(c[:5] + c[6:], []).append((ref, row))
    for members in groups.values():
        if len(members) < 2:
            continue
        vals = [r["dsp_load_avg"] for _, r in members]
        if len(members) == 2:
            (ra, a), (rb, b) = sorted(members, key=lambda m: m[1]["dsp_load_avg"])
            if over(b["dsp_load_avg"], a["dsp_load_avg"], CELL_REL):
                flag(rb, "twin: %.2f against its twin at %.2f (+%.1f%%)" % (
                    b["dsp_load_avg"], a["dsp_load_avg"], 100.0 * (b["dsp_load_avg"] / a["dsp_load_avg"] - 1)))
            continue
        med = statistics.median(vals)
        for ref, r in members:
            v = r["dsp_load_avg"]
            if abs(v - med) > max(CELL_REL * med, FLOOR):
                flag(ref, "twin: %.2f against %.2f, the median of %d twins (%+.1f%%)" % (
                    v, med, len(members), 100.0 * (v / med - 1)))

    # stress adds load: the unstressed cell cannot read higher than the stressed one at the same period count
    by = {}
    for ref, row, c in es:
        by.setdefault(c[:6], {}).setdefault(c[6] != "none", []).append((ref, row))
    for sides in by.values():
        if True in sides and False in sides:
            low = min(r["dsp_load_avg"] for _, r in sides[True])
            for ref, r in sides[False]:
                if over(r["dsp_load_avg"], low, CELL_REL):
                    flag(ref, "stress: %.2f without stress, %.2f with it" % (r["dsp_load_avg"], low))

    # scaling: more frames to a cycle, no more cost
    ladders = {}
    for ref, row, c in es:
        ladders.setdefault(c[:4] + c[5:], []).append((c[4], ref, row))
    for rungs in ladders.values():
        rungs.sort(key=lambda x: x[0])
        for (fa, _, a), (fb, rb, b) in zip(rungs, rungs[1:]):
            if fb > fa and over(b["dsp_load_avg"], a["dsp_load_avg"], CELL_REL):
                flag(rb, "scaling: %.2f at %d frames, above %.2f at %d" % (
                    b["dsp_load_avg"], fb, a["dsp_load_avg"], fa))

    # output
    ref_level = {}
    for ref, row, c in es:
        if c[1] == "H2" and c[2] == "individual" and isinstance((row.get("output") or {}).get("rms_db"), (int, float)):
            ref_level[(c[0], c[3], c[4], c[5], c[6])] = row["output"]["rms_db"]
    for ref, row, c in es:
        out = row.get("output")
        if not isinstance(out, dict) or not row.get("plugins"):
            continue
        db = out.get("rms_db")
        if not isinstance(db, (int, float)) or db < SILENT_DB:
            flag(ref, "output: silent")
            continue
        want = ref_level.get((c[0], c[3], c[4], c[5], c[6]))
        if c[1] in OUTPUT_HOSTS and want is not None and abs(db - want) > OUTPUT_DB:
            flag(ref, "output: %.1f dB against %.1f dB of the same set, one process per plugin" % (db, want))
    return bad


def annotate(doc, others=()):
    """set row["gate"] on every row of doc from check([doc, *others]); returns the number of unstable rows"""
    docs = [doc] + list(others)
    bad = check(docs)
    n = 0
    for i, row in enumerate(doc.get("scenarios", [])):
        if not isinstance(row, dict) or row.get("status") != "ok":
            continue
        gate = {"verdict": "pass", "reasons": []}
        if (0, i) in bad:
            gate = {"verdict": "unstable", "reasons": bad[(0, i)]}
            n += 1
        notes = advisories(row)
        if notes:
            gate["notes"] = notes
        if (row.get("gate") or {}).get("rerun"):
            gate["rerun"] = True
            if "first_dsp_load_avg" in row["gate"]:
                gate["first_dsp_load_avg"] = row["gate"]["first_dsp_load_avg"]
        row["gate"] = gate
    return n


def unstable(docs):
    """{(document, row)} the figure of which is not to be published: marked unstable, or breaking a check"""
    refs = set(check(docs))
    for d, doc in enumerate(docs):
        for n, row in enumerate(doc.get("scenarios", [])):
            if isinstance(row, dict) and (row.get("gate") or {}).get("verdict") == "unstable":
                refs.add((d, n))
    return refs


def rerun_hint(row, doc):
    """the run.sh arguments that measure this cell alone"""
    jack = doc.get("jack") or {}
    args = ["--class", doc["machine"]["class"], "--rates", str(row["rate"]), "--frames", str(row["frames"]),
            "--scenarios", row["id"], "--hosts", row["host"],
            "--stress", "none" if row.get("stress", "none") == "none" else "on"]
    if jack.get("driver") == "alsa":
        args += ["--alsa", jack.get("device", "hw:X")]
        if jack.get("periods"):
            args += ["--periods", str(jack["periods"])]
    return "bench/run.sh --out DIR " + " ".join(args)

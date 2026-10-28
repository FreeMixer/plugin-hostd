import contextlib
import io
import json
import os
import tempfile
import unittest

import make_report as m

FACTS = os.path.join(os.path.dirname(os.path.abspath(m.__file__)), "facts.json")


def scen(sid, host, rate=48000, frames=256, **kw):
    d = dict(id=sid, title=sid, host=host, rate=rate, frames=frames, plugins=[], dsp_load_avg=1.5, dsp_load_max=2.0,
             samples=10, rss_mb=10.0, add_ms=5.0, recover_ms=None, status="ok", note="")
    d.update(kw)
    return d


def bench(cls, scens, id="rpi5-20261027-1"):
    return {"schema": "omx-bench/1", "id": id, "machine": {"class": cls, "model": "x", "cpu": "c", "cores": 4, "ram_mb": 4096, "os": "o", "kernel": "k",
                                                  "governor": "performance"},
            "software": {"plugin-hostd": "0.12.0", "omx-clap-host": "0.22.1", "mod-host": None, "jalv": "1.6.8", "jack": "1.9.22"}, "scenarios": scens}


class Case(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = self.t.name
        self.empty = os.path.join(self.d, "empty")
        os.makedirs(self.empty)
        os.makedirs(os.path.join(self.d, "b"))

    def tearDown(self):
        self.t.cleanup()

    def write(self, name, text):
        p = os.path.join(self.d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text))
        return p

    def report(self, name="report.md"):
        with open(os.path.join(self.d, "o", name)) as fh:
            return fh.read()

    def run_main(self, *extra, results=None):
        return m.main(["--bench", os.path.join(self.d, "b"), "--results", results or self.empty, "--earlier", self.empty,
                       "--qualification", self.empty, "--facts", FACTS, "--out", os.path.join(self.d, "o")] + list(extra))

    def test_no_default_location_under_home(self):
        src = open(m.__file__).read()
        for bad in ("expanduser", "HOME", "zynthian-results", "~/"):
            self.assertNotIn(bad, src)
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            m.main([])
        self.assertIn("--bench and --out are required", err.getvalue())

    def test_help_documents_every_input(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            m.main(["--help"])
        for flag in ("--bench", "--results", "--earlier", "--qualification", "--coverage", "--prs", "--facts", "--out", "--strict"):
            self.assertIn(flag, out.getvalue())
        self.assertIn("No input has a default location", out.getvalue())

    def test_an_input_that_is_given_and_missing_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = self.run_main("--coverage", os.path.join(self.d, "none"))
        self.assertEqual(rc, 1)
        self.assertIn("--coverage", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_strict_fails_with_no_data_and_says_not_measured(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_main("--strict"), 1)
        self.assertEqual(self.run_main(), 0)
        self.assertIn("not measured yet", self.report())

    def test_prose_is_sourced_and_claims_nothing_unmeasured(self):
        self.run_main()
        md = self.report()
        for gone in ("respawn", "takes only its own plugins", "Fedora", "57 CLAP", "None is open on the zynthian"):
            self.assertNotIn(gone, md)
        facts = json.load(open(FACTS))
        for key, items in facts["statements"].items():
            for s in items:
                self.assertRegex(s["source"], r"^FreeMixer/zynthian-(ui|sys)#[0-9]+$", key)
                self.assertIn("%s (%s)" % (s["text"], s["source"]), md)

    def test_facts_cite_only_public_sources(self):
        facts = json.load(open(FACTS))
        self.assertEqual(sorted(k for k in facts if not k.startswith("_")), ["prs", "statements"])
        public = r"^FreeMixer/(zynthian-ui|zynthian-sys|plugin-hostd)#[0-9]+$"
        sources = [s["source"] for items in facts["statements"].values() for s in items]
        sources += ["%s#%d" % (p["repo"], p["number"]) for p in facts["prs"]]
        self.assertTrue(sources)
        for src in sources:
            self.assertRegex(src, public)
        text = open(FACTS).read().lower()
        for private in ("memory", "brief", "reference_", "notes"):
            self.assertNotIn(private, text)

    def test_machine_line_is_read_from_the_document(self):
        self.write("b/rpi.json", bench("rpi5", [scen("idle", "H1")]))
        self.run_main()
        self.assertIn("Run rpi5-20261027-1 on x (c, 4 cores, 4096 MB RAM, o, kernel k)", self.report())

    def test_pr_states_carry_their_fetch_time(self):
        self.write("p.json", {"fetched_at": "2026-10-28T10:00:00Z", "prs": [
            {"repo": "FreeMixer/zynthian-ui", "number": 1, "title": "t", "state": "MERGED", "baseRefName": "main"}]})
        m.main(["--bench", self.empty, "--results", self.empty, "--earlier", self.empty, "--qualification", self.empty,
                "--prs", os.path.join(self.d, "p.json"), "--facts", FACTS,
                "--out", os.path.join(self.d, "o")])
        self.assertIn("States as fetched at 2026-10-28T10:00:00Z.", self.report())

    def test_missing_key_is_an_error_naming_key_and_file(self):
        row = scen("idle", "H1")
        del row["rss_mb"]
        f = self.write("b/rpi.json", bench("rpi5", [row]))
        for flags in ((), ("--strict",)):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                rc = self.run_main(*flags)
            self.assertEqual(rc, 1)
            self.assertIn("%s: scenarios[0] (idle H1): missing key 'rss_mb'" % f, err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.d, "o", "report.md")))

    def test_each_required_key_of_the_row_is_checked(self):
        for key in ("dsp_load_avg", "title", "status", "note", "rate", "frames"):
            row = scen("idle", "H1")
            del row[key]
            self.write("b/rpi.json", bench("rpi5", [row]))
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(self.run_main(), 1)
            self.assertIn("missing key '%s'" % key, err.getvalue())

    def test_missing_machine_key_and_unreadable_json(self):
        d = bench("rpi5", [scen("idle", "H1")])
        del d["machine"]["cpu"]
        self.write("b/rpi.json", d)
        self.write("b/bad.json", "{not json")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.run_main(), 1)
        self.assertIn("machine: missing key 'cpu'", err.getvalue())
        self.assertIn("bad.json: not readable JSON", err.getvalue())

    def test_qualification_verdict_without_rating_or_reason(self):
        self.write("q/a.json", {"verdicts": [{"deciding": "x"}, {"rating": "unsuitable"}]})
        errs = []
        m.parse_qdocs(os.path.join(self.d, "q"), errs)
        self.assertEqual(len(errs), 2)
        self.assertIn("missing key 'rating'", errs[0])
        self.assertIn("missing key 'deciding'", errs[1])

    def test_strict_failure_writes_nothing_and_keeps_the_earlier_report(self):
        out = os.path.join(self.d, "o")
        os.makedirs(out)
        for n in ("report.md", "report.html"):
            self.write("o/" + n, "earlier complete report")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.run_main("--strict"), 1)
        for n in ("report.md", "report.html"):
            self.assertEqual(open(os.path.join(out, n)).read(), "earlier complete report")
        self.assertIn("strict: missing: 3. Measurements", err.getvalue())

    def test_strict_failure_creates_no_output_directory(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.run_main("--strict")
        self.assertFalse(os.path.exists(os.path.join(self.d, "o")))

    def test_shipped_example_document_fills_the_tables(self):
        """a document written by the bench itself (bench/examples), read as class rpi5"""
        doc = json.load(open(os.path.join(os.path.dirname(FACTS), "..", "examples", "ci-20261026-1.json")))
        doc["id"], doc["machine"]["class"] = "rpi5-20261026-1", "rpi5"
        calm = next(r for r in doc["scenarios"] if r["id"] == "cvp3" and r["host"] == "H2" and r["mode"] == "individual" and r["status"] == "ok")
        calm = dict(calm, stress="none", latency_frames=256)
        loaded = dict(calm, stress="busy4+mem64", xruns=2, dsp_load_avg=9.99)
        chain = dict(next(r for r in doc["scenarios"] if r["id"] == "cvp3" and r["host"] == "H2" and r["mode"] == "chain"), stress="busy4+mem64")
        doc["scenarios"] += [calm, loaded, chain]
        self.write("b/rpi.json", doc)
        self.assertEqual(self.run_main(), 0)
        md = self.report()
        self.assertIn("| 256 | 5.33 |", md)  # 256 frames at 48000 Hz, from the row
        self.assertIn("busy4+mem64", md)
        self.assertIn("9.99", md)
        self.assertIn("stress busy4+mem64: the chain runs in", md)
        self.assertIn("Micro-Star International Co., Ltd. MS-7E41 (Intel(R) Core(TM) Ultra 9 285K, 24 cores", md)

    def test_newest_run_orders_the_number_as_a_number(self):
        self.write("b/a.json", bench("rpi5", [scen("idle", "H1", dsp_load_avg=1.11)], "rpi5-20261027-9"))
        self.write("b/b.json", bench("rpi5", [scen("idle", "H1", dsp_load_avg=2.22)], "rpi5-20261027-10"))
        self.run_main()
        self.assertIn("Run rpi5-20261027-10", self.report())

    def test_non_strict_exits_zero(self):
        self.assertEqual(self.run_main(), 0)

    def test_ci_run_is_never_shown_as_pi_numbers(self):
        self.write("b/ci.json", bench("ci", [scen("chain3", "H2", dsp_load_avg=77.77)], "ci-1"))
        self.run_main()
        self.assertNotIn("77.77", self.report())

    def test_host_table_and_ratio_values(self):
        sc = [scen("chain3", h, dsp_load_avg=v) for h, v in (("H1", 1.11), ("H2", 2.22))]
        sc.append(scen("chain3", "H3", status="unsupported", note="no mod-host", dsp_load_avg=None,
                       dsp_load_max=None, rss_mb=None, samples=0))
        sc += [scen("cvp3", "H2", mode="individual", processes=3, pss_mb_total=30.0, rss_mb_total=60.0, cpu_pct=1.0),
               scen("cvp3", "H2", mode="chain", processes=1, pss_mb_total=15.0, rss_mb_total=30.0, cpu_pct=0.5)]
        self.write("b/rpi.json", bench("rpi5", sc))
        self.run_main()
        md = self.report()
        self.assertIn("1.11 (2.00)", md)
        self.assertIn("unsupported (no mod-host)", md)
        self.assertIn("stress not recorded: the chain runs in 1 process against 3, and uses 0.50 times the proportional memory", md)
        self.assertIn("<svg", self.report("report.html"))

    def test_failed_pianoteq_add_is_not_a_measurement(self):
        self.write("e/zy-96test.out", "pianoteq lv2 uri: x\n=== 48000 Hz, 256 frames: a\n"
                   "3-plugin chain + sine:  avg 0.4% max 0.5% (10 samples)\nadd PIANOTEQ lv2 (3): resp -101\n\n"
                   "+ Pianoteq 5-note chords: avg 0.4% max 0.4% (12 samples)\n")
        r = m.parse_earlier(os.path.join(self.d, "e"))
        self.assertNotIn("pianoteq", r["runs"][48000])
        self.assertEqual(r["runs"][48000]["chain3"]["avg"], 0.4)

    def test_earlier_good_pianoteq(self):
        self.write("e/zy-96test2.out", "pianoteq lv2 uri: u\n=== 96000 Hz, 256 frames: a\nadd PIANOTEQ lv2 (3): resp 3\n"
                   "+ Pianoteq 5-note chords: avg 20.5% max 24.0% (12 samples)\n")
        self.assertEqual(m.parse_earlier(os.path.join(self.d, "e"))["runs"][96000]["pianoteq"]["avg"], 20.5)

    def test_qpilot_counts(self):
        self.write("e/zy-qpilot.out", "exit=1 seconds=271\n-- verdict summary\n    125 unsuitable\n    122 suitable\n"
                   "      1 verdict\n-- sample\nplugin verdict reason host\nurn:a  unsuitable   hosting.x  h\n-- stderr\n")
        q = m.parse_qpilot(os.path.join(self.d, "e"))
        self.assertEqual((q["seconds"], q["counts"]), (271, {"unsuitable": 125, "suitable": 122}))
        self.assertEqual(q["sample_reasons"], {"hosting.x": 1})

    def test_qdocs_reasons(self):
        self.write("q/a.json", {"verdicts": [{"rating": "suitable"}, {"rating": "unsuitable", "deciding": "r1"},
                                              {"rating": "unsuitable", "deciding": "r1"}]})
        r = m.parse_qdocs(os.path.join(self.d, "q"), [])
        self.assertEqual(r["reasons"], {"r1": 2})
        self.assertEqual(r["counts"], {"suitable": 1, "unsuitable": 2})

    def test_coverage(self):
        t = "jalv 1.8.0 (x):\n  hosted 977 of 979 (a)\nmod-host 0.10.6 f:\n  hosted 975 of 979\nomx-clap-core: 979 of 979 on main\n"
        self.assertEqual(m.parse_coverage(self.write("c.txt", t)),
                         {"jalv": (977, 979), "mod-host": (975, 979), "omx-clap-core": (979, 979)})
        self.assertIsNone(m.parse_coverage(self.write("c2.txt", "nothing")))

    def test_grouped_notes_are_quoted_not_modified(self):
        self.write("r/grouped-vs-processes.md", "device says 42")
        self.run_main(results=os.path.join(self.d, "r"))
        self.assertIn("> device says 42", self.report())
        with open(os.path.join(self.d, "r", "grouped-vs-processes.md")) as fh:
            self.assertEqual(fh.read(), "device says 42")

    def test_fetch_prs_uses_gh_and_fails_loudly(self):
        class R:
            def __init__(s, rc, out):
                s.returncode, s.stdout, s.stderr = rc, out, "boom"
        facts = {"prs": [{"repo": "o/r", "number": 1, "role": "x"}]}
        out = os.path.join(self.d, "prs.json")
        m.fetch_prs(facts, out, run=lambda *a, **k: R(0, json.dumps({"number": 1, "title": "t", "state": "OPEN", "baseRefName": "b"})))
        with open(out) as fh:
            self.assertEqual(json.load(fh)["prs"][0]["repo"], "o/r")
        with self.assertRaises(SystemExit):
            m.fetch_prs(facts, out, run=lambda *a, **k: R(1, ""))


if __name__ == "__main__":
    unittest.main()

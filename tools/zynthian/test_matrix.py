"""Unit tests of the Zynthian benchmark matrix: run with `python3 -I tools/zynthian/test_matrix.py`. They run no bench."""

import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("matrix", os.path.join(HERE, "matrix.py"))
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)
TBL = matrix.table(json.load(open(os.path.join(HERE, "matrix", "plugins.json"))))
BY_ID = {s["id"]: s for s in TBL["scenarios"]}


class BenchCopy(unittest.TestCase):
    def test_the_copy_finds_the_search_lists_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as work:
            dst = matrix.bench_copy(work, TBL)
            code = "import sys; sys.path.insert(0, sys.argv[1]); import bench; print(bench.clap_dirs())"
            p = subprocess.run([sys.executable, "-I", "-c", code, os.path.join(dst, "lib")], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=dict(os.environ, **matrix.bench_env()))
            self.assertEqual(p.returncode, 0, p.stdout)


class FiveHosts(unittest.TestCase):
    def test_every_scenario_runs_under_omx_clap_host(self):
        for s in TBL["scenarios"]:
            self.assertIn("H1", matrix.hosts_of(s, TBL), s["id"])

    def test_the_lv2_forms_run_under_all_four_programs(self):
        self.assertEqual(matrix.hosts_of(BY_ID["one-omx-delay-lv2"], TBL), ["H1", "H2", "H3", "H4"])
        self.assertEqual(matrix.hosts_of(BY_ID["one-zam-comp"], TBL), ["H1", "H2", "H3", "H4"])
        self.assertEqual(matrix.hosts_of(BY_ID["one-omx-delay-clap"], TBL), ["H1", "H2"])
        self.assertEqual(matrix.hosts_of(BY_ID["chain-omx"], TBL), ["H1", "H2", "H3", "H4"])

    def test_omx_clap_host_names_its_lv2_adapter_rows(self):
        cat = TBL["plugins"]
        self.assertEqual(matrix.host_mode("H1", "shared-process", BY_ID["one-omx-delay-clap"], cat), "omx-clap-host")
        self.assertEqual(matrix.host_mode("H1", "shared-process", BY_ID["one-omx-delay-lv2"], cat), "omx-clap-host LV2")
        self.assertEqual(matrix.host_mode("H1", "shared-process", BY_ID["one-zam-comp"], cat), "omx-clap-host LV2")
        self.assertEqual(matrix.host_mode("H1", "shared-process", BY_ID["chain-omx"], cat), "omx-clap-host")
        self.assertEqual(matrix.host_mode("H1", "shared-process", BY_ID["chain-tp"], cat), "omx-clap-host LV2")
        self.assertEqual(matrix.host_mode("H3", "shared-process", BY_ID["one-zam-comp"], cat), "mod-host")


class ResumePerHost(unittest.TestCase):
    def write(self, rows):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "matrix.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=matrix.COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    def test_a_cell_measured_before_omx_clap_host_joined_runs_under_it_alone(self):
        cell = "one-zam-comp@48000/512"
        path = self.write([{"cell": cell, "host": h, "doc": "x.json"} for h in ("H2", "H3", "H4")])
        todo = matrix.left(TBL, [48000], [512], "singles", matrix.done_hosts(path))
        mine = [t for t in todo if matrix.cell_id(*t[:3]) == cell]
        self.assertEqual(mine[0][3], ["H1"])

    def test_a_cell_with_every_host_measured_is_not_run_again(self):
        cell = "one-zam-comp@48000/512"
        path = self.write([{"cell": cell, "host": h, "doc": "x.json"} for h in ("H1", "H2", "H3", "H4")])
        todo = matrix.left(TBL, [48000], [512], "singles", matrix.done_hosts(path))
        self.assertNotIn(cell, [matrix.cell_id(*t[:3]) for t in todo])

    def test_a_row_without_a_document_did_not_measure(self):
        cell = "one-zam-comp@48000/512"
        path = self.write([{"cell": cell, "status": "failed", "note": "no document"}])
        todo = matrix.left(TBL, [48000], [512], "singles", matrix.done_hosts(path))
        mine = [t for t in todo if matrix.cell_id(*t[:3]) == cell]
        self.assertEqual(mine[0][3], ["H1", "H2", "H3", "H4"])

    def test_a_partial_run_never_replaces_the_cell_s_first_document(self):
        s = BY_ID["one-zam-comp"]
        full = matrix.doc_name(s, 48000, 512, ["H1", "H2", "H3", "H4"], ["H1", "H2", "H3", "H4"])
        part = matrix.doc_name(s, 48000, 512, ["H1"], ["H1", "H2", "H3", "H4"])
        self.assertEqual(full, "one-zam-comp-48000-512.json")
        self.assertNotEqual(part, full)


if __name__ == "__main__":
    unittest.main()

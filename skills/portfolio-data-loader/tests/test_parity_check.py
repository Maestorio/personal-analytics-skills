#!/usr/bin/env python3
"""API-1b PR-4: parity_check — сверка снапшота скилла и снапшота build_snapshot.py.

Контракт (критерий переключения скилла на скрипт держится на нём):
  • перестановка элементов списков (holdings, флаги) — «совпало»;
  • generated_at не сравнивается;
  • float в допуске (порядок операций) — «в допуске», не «расходится»;
  • другое количество, статус, лишняя/пропавшая позиция — «расходится», код выхода 1;
  • поле из known-diffs — «известное» с причиной, код выхода 0.
Запуск: python3 skills/portfolio-data-loader/tests/test_parity_check.py
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import parity_check as pc  # noqa: E402

BASE = {
    "schema_version": "2.0", "as_of_date": "2026-10-16", "generated_at": "2026-10-16T18:21:16",
    "holdings": [
        {"ticker": "SBER", "account": "main", "qty": 10, "value_rub": 3000.12, "status": "normal"},
        {"ticker": "RU000A1038V6", "account": "main", "qty": 80, "value_rub": 70000.0, "status": "normal"},
        {"ticker": "RU000A1038V6", "account": "iis_3", "qty": 130, "value_rub": 113750.0, "status": "normal"},
    ],
    "data_quality_flags": [{"step": "a", "severity": "info", "code": "x", "message": "m1"},
                           {"step": "b", "severity": "warn", "code": "y", "message": "m2"}],
    "returns": {"restricted": {"xirr": 0.0827}},
}


class ParityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.known = self.tmp / "known.yaml"
        self.known.write_text("known: []\n", encoding="utf-8")

    def _run(self, a, b, known=None):
        pa, pb = self.tmp / "a.json", self.tmp / "b.json"
        pa.write_text(json.dumps(a), encoding="utf-8")
        pb.write_text(json.dumps(b), encoding="utf-8")
        res, _ = pc.check_files(pa, pb, known or self.known)
        rc = pc.main([str(pa), str(pb), "--known", str(known or self.known), "--json"])
        return res, rc

    def test_identical_after_reorder_and_generated_at(self):
        b = copy.deepcopy(BASE)
        b["holdings"].reverse()
        b["data_quality_flags"].reverse()
        b["generated_at"] = "2026-10-20T10:00:00"
        res, rc = self._run(BASE, b)
        self.assertEqual((res["differs"], res["tolerated"], rc), ([], [], 0))

    def test_float_noise_is_tolerated(self):
        b = copy.deepcopy(BASE)
        b["holdings"][0]["value_rub"] = 3000.12 + 1e-9
        b["returns"]["restricted"]["xirr"] = 0.0827 + 1e-12
        res, rc = self._run(BASE, b)
        self.assertEqual(len(res["tolerated"]), 2)
        self.assertEqual((res["differs"], rc), ([], 0))

    def test_money_beyond_kopeck_differs(self):
        b = copy.deepcopy(BASE)
        b["holdings"][0]["value_rub"] = 3000.14
        res, rc = self._run(BASE, b)
        self.assertEqual([d[0] for d in res["differs"]], ["$.holdings[SBER|main].value_rub"])
        self.assertEqual(rc, 1)

    def test_qty_status_and_missing_holding_differ(self):
        b = copy.deepcopy(BASE)
        b["holdings"][1]["qty"] = 81
        b["holdings"][0]["status"] = "blocked"
        del b["holdings"][2]
        res, rc = self._run(BASE, b)
        paths = sorted(d[0] for d in res["differs"])
        self.assertEqual(paths, ["$.holdings[RU000A1038V6|iis_3]",
                                 "$.holdings[RU000A1038V6|main].qty",
                                 "$.holdings[SBER|main].status"])
        self.assertEqual(rc, 1)

    def test_int_vs_float_equal_value_is_equal(self):
        b = copy.deepcopy(BASE)
        b["holdings"][1]["value_rub"] = 70000          # 70000.0 → 70000
        res, _ = self._run(BASE, b)
        self.assertEqual(res["differs"], [])

    def test_known_diff_is_reported_not_failed(self):
        known = self.tmp / "k2.yaml"
        known.write_text('known:\n  - path: "$.holdings[*].qty"\n    reason: "тест: известная причина"\n'
                         '    since: "2026-10-20"\n', encoding="utf-8")
        b = copy.deepcopy(BASE)
        b["holdings"][1]["qty"] = 81
        res, rc = self._run(BASE, b, known)
        self.assertEqual(res["differs"], [])
        self.assertEqual(res["known"][0][3], "тест: известная причина")
        self.assertEqual(rc, 0)

    def test_new_key_differs(self):
        b = copy.deepcopy(BASE)
        b["extra"] = 1
        res, _ = self._run(BASE, b)
        self.assertEqual([d[0] for d in res["differs"]], ["$.extra"])

    def test_render_mentions_status(self):
        res = {"tolerated": [], "known": [], "differs": [("$.x", 1, 2)]}
        self.assertIn("расходится: 1", pc.render(res, "a", "b", 10))
        self.assertIn("совпадает", pc.render({"tolerated": [], "known": [], "differs": []}, "a", "b", 1))

    def test_repo_known_diffs_file_parses(self):
        self.assertIsInstance(pc.load_known(pc.DEFAULT_KNOWN), list)


if __name__ == "__main__":
    unittest.main(verbosity=1)

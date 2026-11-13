#!/usr/bin/env python3
"""Тесты sweep_collect.py (RPA-25): результаты sweep из файлов, проверка формата и провенанса.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_sweep_collect.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sweep_collect import collect, to_md, _same_company  # noqa: E402

ROWS = [
    {"key": "RU000A107795", "name": "МФК «Лайм-Займ» (ООО)"},
    {"key": "RU000A10ERE6", "name": "АО «АВТОБАН-Финанс»"},
    {"key": "BTBR", "name": "iВ2В-РТС"},
    {"key": "RU000A105146", "name": "ПИК-Корпорация"},
    {"key": "RU000A10DZU7", "name": "А101"},
]
TODAY = date(2026, 10, 16)


def _files(batches):
    d = tempfile.mkdtemp()
    paths = []
    for i, b in enumerate(batches):
        p = os.path.join(d, f"sweep-{i}.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(b if isinstance(b, str) else json.dumps(b, ensure_ascii=False))
        paths.append(p)
    return paths


class TestSweepCollect(unittest.TestCase):
    def setUp(self):
        b1 = [
            {"key": "RU000A107795", "searched_as": "Лайм-Займ", "status": "events", "accessed": "2026-10-16",
             "events": [{"kind": "rating", "event_date": "2026-10-08", "fact": "Эксперт РА: статус «под наблюдением»",
                         "url": "https://raexpert.ru/releases/2026/oct08e"}],
             "ratings": [{"agency": "Эксперт РА", "rating": "ruBB+", "outlook_or_status": "под наблюдением",
                          "action_date": "2026-10-08", "action": "под наблюдением", "url": "https://raexpert.ru"}]},
            {"key": "BTBR", "searched_as": "BitRiver", "status": "quiet", "accessed": "2026-10-16"},
        ]
        b2 = [
            {"key": "RU000A10ERE6", "searched_as": "АВТОБАН-Финанс", "status": "quiet", "accessed": "2026-10-16"},
            {"key": "RU000A105146", "searched_as": "ПИК", "status": "budget_exhausted", "accessed": "2026-10-16"},
        ]
        self.res = collect(ROWS, _files([b1, b2, "{битый"]), "2", TODAY)

    def test_coverage(self):
        c = self.res["coverage"]
        self.assertEqual(c["method"], "sweep_collect")  # RPA-34: валидатор сохранения требует его
        self.assertEqual(c["checked_this_run"], ["RU000A107795", "RU000A10ERE6"])
        # BTBR отброшен, ПИК — бюджет, А101 не вернулся — всё «не проверено»
        self.assertEqual(c["not_checked"], ["BTBR", "RU000A105146", "RU000A10DZU7"])
        self.assertEqual(self.res["missing"], ["RU000A10DZU7"])

    def test_checked_dates_only_for_checked(self):
        d = self.res["coverage"]["checked_dates"]
        self.assertEqual(d, {"RU000A107795": "2026-10-16", "RU000A10ERE6": "2026-10-16"})
        self.assertEqual(set(d), set(self.res["coverage"]["checked_this_run"]))  # не проверенных (BTBR, ПИК) нет

    def test_wrong_company_rejected(self):
        self.assertEqual([r["key"] for r in self.res["rejected"]], ["BTBR"])
        self.assertIn("BitRiver", self.res["rejected"][0]["reasons"][0])

    def test_escalation_and_ratings(self):
        self.assertEqual(self.res["escalate"], [{"key": "RU000A107795", "name": "МФК «Лайм-Займ» (ООО)", "kinds": ["rating"]}])
        self.assertIn("RU000A107795", self.res["ratings"])

    def test_broken_file_reported(self):
        self.assertEqual(len(self.res["file_errors"]), 1)

    def test_bad_event_and_future_accessed_rejected(self):
        b = [{"key": "RU000A10DZU7", "searched_as": "А101", "status": "events", "accessed": "2026-10-17",
              "events": [{"kind": "rumor", "event_date": "вчера", "fact": "x"}]}]
        r = collect(ROWS, _files([b]), "2", TODAY)
        reasons = " ".join(r["rejected"][0]["reasons"])
        self.assertIn("accessed", reasons)
        self.assertIn("событие без", reasons)

    def test_duplicate_keeps_latest(self):
        a = [{"key": "RU000A10DZU7", "searched_as": "А101", "status": "quiet", "accessed": "2026-10-14"}]
        b = [{"key": "RU000A10DZU7", "searched_as": "ПАО «А101»", "status": "events", "accessed": "2026-10-16",
              "events": [{"kind": "report", "event_date": "2026-10-15", "fact": "МСФО", "url": "https://e-disclosure.ru/x"}]}]
        r = collect(ROWS, _files([a, b]), "1", TODAY)
        self.assertEqual(r["accessed_by_key"]["RU000A10DZU7"], "2026-10-16")
        self.assertEqual(r["escalate"], [])  # mode 1: report не эскалируется

    def test_name_normalization(self):
        self.assertTrue(_same_company("МФК «Лайм-Займ» (ООО)", "Лайм Займ"))
        self.assertFalse(_same_company("iВ2В-РТС", "BitRiver"))

    def test_md(self):
        md = to_md(self.res)
        self.assertIn("Sweep: проверено 2 из 5", md)
        self.assertIn("**НЕ проверены (3):**", md)
        self.assertIn("Эксперт РА ruBB+", md)


if __name__ == "__main__":
    unittest.main(verbosity=1)

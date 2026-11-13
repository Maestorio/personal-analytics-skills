#!/usr/bin/env python3
"""
Тесты `check_position_freshness.py` + drift-контракт «YAML значений ↔ разбор в
markdown».

Смысл проверки свежести: устаревшие позиции не выглядят устаревшими — числа
остаются правдоподобными. Поэтому вердикт должен быть детерминированным и не
зависеть от того, помнит ли кто-то дату последнего пересмотра.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \\
        skills/portfolio-scenario-stress/tests/test_check_position_freshness.py
Требует PyYAML.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

HAS_YAML = True
try:
    import yaml  # noqa: F401
except ImportError:
    HAS_YAML = False

import check_position_freshness as m  # noqa: E402

POSITIONS = REPO / "skills/portfolio-scenario-stress/references/sanctions-positions.yaml"
DRAFT = REPO / "docs/investment/portfolio/sanctions-position-draft.md"

DOC = {
    "as_of": date(2026, 8, 4),
    "stale_after_days": 30,
    "positions": {
        "SBER": {"position": 0.9, "confidence": "high"},
        "MBNK": {"position": 0.85, "confidence": "medium"},
        "FINAMAR": {"position": 0.15, "confidence": "low"},
    },
}


class TestVerdict(unittest.TestCase):
    def test_fresh_within_threshold(self):
        r = m.check(DOC, date(2026, 8, 20))
        self.assertFalse(r["needs_check"])
        self.assertEqual(r["days_stale"], 16)
        self.assertEqual(r["search_plan"], [], "план строится только при необходимости")

    def test_stale_past_threshold(self):
        r = m.check(DOC, date(2026, 9, 20))
        self.assertTrue(r["needs_check"])
        self.assertIn("47", r["reason"])
        self.assertTrue(r["search_plan"])

    def test_boundary_day_is_not_stale(self):
        """Ровно порог — ещё свежо; устаревание начинается со следующего дня."""
        self.assertFalse(m.check(DOC, date(2026, 9, 3))["needs_check"])   # 30 дн
        self.assertTrue(m.check(DOC, date(2026, 9, 4))["needs_check"])    # 31 дн

    def test_force_overrides_freshness(self):
        r = m.check(DOC, date(2026, 8, 5), force=True)
        self.assertTrue(r["needs_check"])
        self.assertIn("принудительно", r["reason"])

    def test_future_as_of_flagged(self):
        """Дата значений в будущем — признак правки задним числом, а не свежести."""
        r = m.check(DOC, date(2026, 7, 1))
        self.assertTrue(r["needs_check"])
        self.assertIn("будущем", r["reason"])

    def test_low_and_medium_confidence_go_first(self):
        r = m.check(DOC, date(2026, 9, 20))
        self.assertEqual(r["priority_tickers"], ["FINAMAR", "MBNK"])
        self.assertNotIn("SBER", r["priority_tickers"])

    def test_missing_stale_after_uses_default(self):
        doc = {k: v for k, v in DOC.items() if k != "stale_after_days"}
        self.assertEqual(m.check(doc, date(2026, 8, 5))["stale_after_days"],
                         m.DEFAULT_STALE_AFTER_DAYS)

    def test_broken_positions_block_refused(self):
        for bad in ({}, {"positions": []}, {"positions": {}}):
            with self.subTest(doc=bad):
                with self.assertRaises(SystemExit):
                    m.check({"as_of": date(2026, 8, 4), **bad}, date(2026, 9, 20))

    def test_bad_as_of_refused(self):
        with self.assertRaises(SystemExit):
            m.check({"as_of": "вчера", "positions": DOC["positions"]}, date(2026, 9, 1))


class TestSearchPlan(unittest.TestCase):
    def test_deterministic_order_and_chunking(self):
        tickers = ["ZZZ", "AAA", "MMM", "BBB", "CCC", "DDD", "EEE"]
        p1 = m.build_search_plan(tickers, date(2026, 8, 4), date(2026, 9, 20))
        p2 = m.build_search_plan(list(reversed(tickers)), date(2026, 8, 4),
                                 date(2026, 9, 20))
        self.assertEqual(p1, p2, "порядок входа не должен менять план")
        self.assertEqual(p1[0]["tickers"][0], "AAA")
        self.assertEqual(len(p1), 2)   # 7 тикеров при 6 в пачке

    def test_window_named_in_query(self):
        p = m.build_search_plan(["SBER"], date(2026, 8, 4), date(2026, 9, 20))
        self.assertIn("2026-08-04", p[0]["query_ru"])
        self.assertIn("2026-09-20", p[0]["query_ru"])
        self.assertIn("SBER", p[0]["query_en"])

    def test_every_ticker_covered_exactly_once(self):
        tickers = [f"T{i}" for i in range(13)]
        plan = m.build_search_plan(tickers, date(2026, 8, 4), date(2026, 9, 20))
        flat = [t for chunk in plan for t in chunk["tickers"]]
        self.assertEqual(sorted(flat), sorted(tickers))
        self.assertEqual(len(flat), len(set(flat)))


@unittest.skipUnless(HAS_YAML and POSITIONS.exists(), "нужен PyYAML и файл значений")
class TestLivePositionsFile(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(POSITIONS.read_text(encoding="utf-8"))

    def test_schema(self):
        self.assertIn("as_of", self.doc)
        self.assertIsInstance(self.doc["positions"], dict)
        for t, v in self.doc["positions"].items():
            with self.subTest(ticker=t):
                self.assertIsInstance(v, dict)
                self.assertIsInstance(v["position"], (int, float))
                self.assertTrue(0.0 <= float(v["position"]) <= 1.0)
                self.assertIn(v["confidence"], ("high", "medium", "low"))
                self.assertTrue(str(v.get("basis", "")).strip(),
                                "значение без обоснования нельзя пересмотреть по рубрике")

    def test_no_position_equals_one(self):
        """Единица означала бы «ужесточать больше нечем» — такого не бывает."""
        for t, v in self.doc["positions"].items():
            self.assertLess(float(v["position"]), 1.0, t)

    def test_changelog_present(self):
        self.assertTrue(self.doc.get("changelog"))

    @unittest.skipUnless(DRAFT.exists(), "нет markdown-разбора")
    def test_no_drift_with_markdown(self):
        """
        Значения живут в YAML, разбор — в markdown. Две копии числа разъезжаются
        молча: контракт ловит это, а не читатель через месяц.
        """
        text = DRAFT.read_text(encoding="utf-8")
        rows = re.findall(r"^\|\s*([A-Z][A-Z0-9]*)\s*(?:\([^)]*\))?\s*\|.*?\|.*?\|\s*\**([01]\.\d+)\**",
                          text, flags=re.M)
        found = {t: float(v) for t, v in rows}
        self.assertTrue(found, "в markdown не нашлось ни одной строки со значением")
        for t, v in found.items():
            if t in self.doc["positions"]:
                self.assertAlmostEqual(
                    float(self.doc["positions"][t]["position"]), v, places=4,
                    msg=f"{t}: YAML и markdown разошлись")


class TestCLI(unittest.TestCase):
    SCRIPT = REPO / "skills/portfolio-scenario-stress/scripts/check_position_freshness.py"

    def _run(self, *extra):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), "--positions", str(POSITIONS), *extra],
            capture_output=True, text=True, encoding="utf-8", env=env)

    @unittest.skipUnless(HAS_YAML and POSITIONS.exists(), "нужен PyYAML и файл значений")
    def test_exit_code_distinguishes_verdict_from_failure(self):
        # даты считаются от as_of файла: жёсткие даты ломали тест при каждом пересмотре значений
        import datetime as _dt
        import yaml as _yaml
        doc = _yaml.safe_load(POSITIONS.read_text(encoding="utf-8"))
        as_of = doc["as_of"] if isinstance(doc["as_of"], _dt.date) else _dt.date.fromisoformat(str(doc["as_of"]))
        limit = int(doc.get("stale_after_days", 30))
        fresh = self._run("--today", (as_of + _dt.timedelta(days=4)).isoformat())
        self.assertEqual(fresh.returncode, 0)
        self.assertFalse(json.loads(fresh.stdout)["needs_check"])

        stale = self._run("--today", (as_of + _dt.timedelta(days=limit + 60)).isoformat())
        self.assertEqual(stale.returncode, 3, "вердикт «нужна проверка» — код 3")
        self.assertTrue(json.loads(stale.stdout)["needs_check"])

    def test_missing_file_is_code_2(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, str(self.SCRIPT), "--positions", "/nope/none.yaml"],
            capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()

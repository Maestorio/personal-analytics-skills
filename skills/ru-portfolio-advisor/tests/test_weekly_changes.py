#!/usr/bin/env python3
"""Тесты weekly_changes.py (RPA-28) — без сети, ISS подменён фикстурой.

Кейс аудита 20.10.2026: YDEX за неделю считался от утренней цены снапшота 08.10 (−4,1%), по
закрытиям 07.10→15.10 — −7,2%; ОФЗ в истории ISS живут под SU…, а не под ISIN.
Запуск: python3 skills/ru-portfolio-advisor/tests/test_weekly_changes.py
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from weekly_changes import compute, security_change  # noqa: E402

HIST = {
    # акции: TQBR + шумная доска, которую надо игнорировать
    ("shares", "YDEX"): [["2026-10-07", "TQBR", 3693.5], ["2026-10-08", "TQBR", 3577],
                         ["2026-10-15", "TQBR", 3427], ["2026-10-15", "SMAL", 1.0]],
    ("shares", "SBER"): [["2026-10-03", "TQBR", 270.0], ["2026-10-15", "TQBR", 283.63]],
    # индекс: окно с максимумом в середине
    ("index", "IMOEX"): [["2026-10-07", "SNDX", 2338.21], ["2026-10-13", "SNDX", 2426.53],
                         ["2026-10-15", "SNDX", 2391.72]],
    ("index", "RGBI"): [["2026-10-07", "SNDX", 111.11], ["2026-10-15", "SNDX", 111.68]],
    # корп-облигация по ISIN, две доски — берётся TQCB
    ("bonds", "RU000A105146"): [["2026-10-07", "TQCB", 98.4697, 20.45], ["2026-10-07", "SPEQ", 50, 1],
                                ["2026-10-15", "TQCB", 98.6622, 21.67]],
    # ОФЗ: по ISIN пусто, по SU-коду есть
    ("bonds", "RU000A108EH4"): [],
    ("bonds", "SU26248RMFS3"): [["2026-10-07", "TQOB", 78.797, 16.78], ["2026-10-15", "TQOB", 79.1, 16.70]],
}


def fake_fetch(url):
    if "/iss/securities.json?q=" in url:
        isin = url.split("q=")[1].split("&")[0]
        return {"securities": {"data": [["SU26248RMFS3", "RU000A108EH4"]] if isin == "RU000A108EH4" else []}}
    market = url.split("/markets/")[1].split("/")[0]
    secid = url.split("/securities/")[1].split(".json")[0]
    if "&start=" in url and not url.endswith("&start=0"):
        return {"history": {"data": []}}
    return {"history": {"data": HIST.get((market, secid), [])}}


SNAP = {"holdings": [
    {"asset_type": "stock", "ticker": "YDEX", "qty": 10, "status": "normal"},
    {"asset_type": "stock", "ticker": "SBER", "qty": 100, "status": "normal"},
    {"asset_type": "stock", "ticker": "KO", "qty": 5, "status": "blocked"},
    {"asset_type": "bond", "ticker": "RU000A105146", "isin": "RU000A105146", "name": "ПИК К 1P5", "status": "normal"},
    {"asset_type": "bond", "ticker": "RU000A108EH4", "isin": "RU000A108EH4", "name": "ОФЗ 26248", "status": "normal"},
    {"asset_type": "bond", "ticker": "RU000A108EH4", "isin": "RU000A108EH4", "name": "ОФЗ 26248", "status": "normal"},
]}
D0, D1 = date(2026, 10, 7), date(2026, 10, 15)


class TestWeeklyChanges(unittest.TestCase):
    def setUp(self):
        self.r = compute(SNAP, D0, D1, "all", fetch=fake_fetch)

    def test_ydex_from_close_not_morning(self):
        y = self.r["per_stock"]["YDEX"]
        self.assertEqual((y["start"]["date"], y["end"]["date"]), ("2026-10-07", "2026-10-15"))
        self.assertEqual(y["change_pct"], -7.22)

    def test_base_falls_back_to_last_trading_day(self):
        s = self.r["per_stock"]["SBER"]
        self.assertEqual(s["start"]["date"], "2026-10-03")  # 07.10 торгов нет в фикстуре

    def test_label_reports_actual_dates(self):
        self.assertEqual(self.r["window"]["start_dates"], ["2026-10-03", "2026-10-07"])
        self.assertIn("закрытие 15.10", self.r["window"]["label"])

    def test_book_and_vs_imoex(self):
        b = self.r["book_stocks"]
        v0 = 10 * 3693.5 + 100 * 270.0
        v1 = 10 * 3427 + 100 * 283.63
        self.assertEqual(b["change_pct"], round((v1 / v0 - 1) * 100, 2))
        self.assertEqual(b["vs_imoex_pp"], round(b["change_pct"] - 2.29, 2))
        self.assertNotIn("KO", self.r["per_stock"])  # blocked мимо

    def test_index_window_max(self):
        self.assertEqual(self.r["indices"]["IMOEX"]["change_pct"], 2.29)
        self.assertEqual(self.r["indices"]["IMOEX"]["window_max"], {"date": "2026-10-13", "close": 2426.53})

    def test_corp_bond_board_and_yield(self):
        p = self.r["per_bond"]["RU000A105146"]
        self.assertEqual(p["board"], "TQCB")
        self.assertEqual(p["yield_change_bp"], 122)

    def test_ofz_resolved_via_secid_and_deduplicated(self):
        o = self.r["per_bond"]["RU000A108EH4"]
        self.assertEqual(o["board"], "TQOB")
        self.assertEqual(o["yield_change_bp"], -8)
        self.assertEqual(len(self.r["per_bond"]), 2)

    def test_errors_are_per_security(self):
        r = security_change("shares", "NOPE", D0, D1, fetch=fake_fetch)
        self.assertEqual(r["error"], "no_close_in_window")

        def broken(url):
            raise IOError("reset")
        r = security_change("shares", "YDEX", D0, D1, fetch=broken)
        self.assertTrue(r["error"].startswith("fetch_failed"))

    def test_kind_stock_only(self):
        r = compute(SNAP, D0, D1, "stock", fetch=fake_fetch)
        self.assertEqual(r["per_bond"], {})
        self.assertEqual(list(r["indices"]), ["IMOEX"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
"""Тесты snapshot-based загрузки состояния ИИС-3 в iis_shortlist.py.

После рефакторинга (single-ownership загрузки файлов) iis_shortlist читает
готовый снапшот portfolio-data-loader, а не парсит Numbers сам. Проверяем
load_iis_state на синтетическом снапшоте v2 — без сети и MOEX.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_iis_shortlist.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.iis_shortlist import load_iis_state, _bond_type, _is_iis_account


def _snapshot():
    return {
        "schema_version": "2.0",
        "as_of_date": "2026-06-28",
        "balance_summary": {
            "iis_balance_rub": 1179900.0,
            "total_current_rub_excl_iis": 37866000.0,
            "total_current_rub_incl_iis": 39045900.0,
            "by_account": {
                "main": {"total_rub": 37866000.0, "bonds_rub": 17216604.03},
                "iis_3": {"total_rub": 1179900.0, "bonds_rub": 933515.7},
            },
        },
        "holdings": [
            # ОФЗ 26238 разделена main(80) + iis_3(130) → split-бумага
            {"ticker": "RU000A1038V6", "name": "ОФЗ 26238", "asset_type": "bond",
             "account": "main", "qty": 80, "value_rub": 42470.4},
            {"ticker": "RU000A1038V6", "name": "ОФЗ 26238", "asset_type": "bond",
             "account": "iis_3", "qty": 130, "value_rub": 69014.4},
            # Только на ИИС-3
            {"ticker": "RU000A1074G2", "name": "ОФЗ 26244", "asset_type": "bond",
             "account": "iis_3", "qty": 100, "value_rub": 86012.0},
            # Фонд на ИИС-3 (вариант написания account)
            {"ticker": "SBGB", "name": "Сбер ОФЗ ETF", "asset_type": "fund",
             "account": "iis-3", "qty": 10, "value_rub": 5000.0},
            # Акция на основном счёте — НЕ должна попасть в ИИС-списки
            {"ticker": "SBER", "name": "Сбербанк", "asset_type": "stock",
             "account": "main", "qty": 1000, "value_rub": 900000.0},
        ],
    }


class TestLoadIisState(unittest.TestCase):
    def setUp(self):
        self.st = load_iis_state(_snapshot())

    def test_scalars(self):
        self.assertEqual(self.st["iis_balance_rub"], 1179900.0)
        self.assertEqual(self.st["total_current_rub_excl_iis"], 37866000.0)
        self.assertEqual(self.st["total_current_rub_incl_iis"], 39045900.0)
        self.assertEqual(self.st["total_bonds_iis_rub"], 933515.7)

    def test_only_iis_bonds_listed(self):
        tickers = {b["ticker"] for b in self.st["iis_bonds"]}
        self.assertEqual(tickers, {"RU000A1038V6", "RU000A1074G2"})
        # акция на main не просочилась
        self.assertNotIn("SBER", tickers)

    def test_split_bond_reconstruction(self):
        ofz = next(b for b in self.st["iis_bonds"] if b["ticker"] == "RU000A1038V6")
        self.assertEqual(ofz["qty_iis"], 130)
        self.assertEqual(ofz["qty_total"], 210)              # 130 (iis) + 80 (main)
        self.assertEqual(ofz["value_iis_rub"], 69014.4)
        self.assertEqual(ofz["value_main_rub"], 42470.4)     # из main-записи

    def test_non_split_bond_has_no_main(self):
        ofz = next(b for b in self.st["iis_bonds"] if b["ticker"] == "RU000A1074G2")
        self.assertEqual(ofz["qty_total"], 100)
        self.assertIsNone(ofz["value_main_rub"])

    def test_funds_go_to_iis_other(self):
        self.assertEqual(len(self.st["iis_other"]), 1)
        self.assertEqual(self.st["iis_other"][0]["ticker"], "SBGB")
        self.assertEqual(self.st["iis_other"][0]["value_rub"], 5000.0)

    def test_value_sum_matches_total(self):
        s = sum(b["value_iis_rub"] for b in self.st["iis_bonds"])
        self.assertAlmostEqual(s, 69014.4 + 86012.0, places=2)


class TestHelpers(unittest.TestCase):
    def test_bond_type_ofz(self):
        self.assertEqual(_bond_type({"name": "ОФЗ 26238"}), "ОФЗ")

    def test_bond_type_corp(self):
        self.assertEqual(_bond_type({"name": "РусГидро БО-002Р"}), "КОРП")

    def test_account_variants(self):
        for acc in ("iis_3", "iis-3", "IIS3", "iis3"):
            self.assertTrue(_is_iis_account({"account": acc}), acc)
        self.assertFalse(_is_iis_account({"account": "main"}))
        self.assertFalse(_is_iis_account({}))


class TestEmptyIis(unittest.TestCase):
    def test_no_iis_holdings(self):
        snap = {"balance_summary": {"by_account": {"iis_3": {}}},
                "holdings": [{"ticker": "SBER", "asset_type": "stock",
                              "account": "main", "qty": 1, "value_rub": 100.0}]}
        st = load_iis_state(snap)
        self.assertEqual(st["iis_bonds"], [])
        self.assertEqual(st["iis_other"], [])

    def test_missing_balance_summary(self):
        # graceful: пустой снапшот не должен падать
        st = load_iis_state({})
        self.assertEqual(st["iis_bonds"], [])
        self.assertIsNone(st["iis_balance_rub"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

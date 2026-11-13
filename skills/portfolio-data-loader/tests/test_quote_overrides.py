#!/usr/bin/env python3
"""Тесты двух фиксов 2026-06:

1. moex_quotes.secids_from_portfolio — ЗПИФ из «Другое» (ключ «Бумага», без
   «Тикер») попадает в запрос по ISIN через NAME_ISIN_OVERRIDES. Раньше такие
   позиции (Рентал ПРО) выпадали из MOEX-запроса → цена застывала на avg_cost.

2. per_security_xirr.load_market_values_from_common — флаг --common принимает
   portfolio.json (а не только common_portfolio_*.xlsx), как написано в SKILL.md.

Без сети: оба пути проверяются на синтетических JSON. Запуск:
  python3 skills/portfolio-data-loader/tests/test_quote_overrides.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "_shared-references"))  # канон moex_quotes
from moex_quotes import secids_from_portfolio, NAME_ISIN_OVERRIDES, _norm_name
from per_security_xirr import load_market_values_from_common


def _write_json(payload) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, f, ensure_ascii=False)
    f.close()
    return f.name


class TestSecidsOverride(unittest.TestCase):
    def test_zpif_in_other_resolved_by_isin(self):
        path = _write_json({
            "stocks": [{"Тикер": "SBER", "Стоимость": 1000.0}],
            "bonds": [],
            "other_positions": [
                {"Тип": "RUB - Другое", "Бумага": "Ренат ПРО", "Стоимость": 228504.0},
                {"Тип": "БПИФ", "Название": "TGLD ETF", "Стоимость": 5000.0},
            ],
        })
        g = secids_from_portfolio(path)
        os.unlink(path)
        self.assertIn("RU000A108157", g["other"])   # фонд теперь в запросе
        self.assertIn("TGLD", g["other"])            # обычные «Другое» — как раньше
        self.assertEqual(g["shares"], ["SBER"])

    def test_correct_spelling_also_mapped(self):
        path = _write_json({
            "other_positions": [{"Бумага": "Рентал ПРО", "Стоимость": 1.0}],
        })
        g = secids_from_portfolio(path)
        os.unlink(path)
        self.assertIn("RU000A108157", g["other"])

    def test_normalization_case_and_spaces(self):
        self.assertEqual(_norm_name("  Рентал   ПРО "), "рентал про")
        self.assertEqual(NAME_ISIN_OVERRIDES["ренат про"], "RU000A108157")

    def test_unknown_other_passes_through(self):
        path = _write_json({"other_positions": [{"Бумага": "Нечто Иное"}]})
        g = secids_from_portfolio(path)
        os.unlink(path)
        self.assertEqual(g["other"], ["Нечто"])      # первый токен, без подмены


class TestSecidsSnapshotV2(unittest.TestCase):
    """RPA-22: советник подаёт снапшот v2, а не portfolio.json — раньше список был пуст."""

    def test_holdings_grouped_and_blocked_skipped(self):
        path = _write_json({
            "schema_version": "2.0",
            "holdings": [
                {"asset_type": "stock", "ticker": "SBER", "isin": "RU0009029540", "status": "normal"},
                {"asset_type": "stock", "ticker": "KO", "isin": None, "status": "blocked"},
                {"asset_type": "bond", "ticker": "RU000A107795", "isin": "RU000A107795", "status": "normal"},
                {"asset_type": "fund", "ticker": "TMON", "isin": None, "status": "normal"},
                {"asset_type": "fund", "ticker": "FXIT", "isin": None, "status": "blocked"},
            ],
        })
        g = secids_from_portfolio(path)
        os.unlink(path)
        self.assertEqual(g, {"shares": ["SBER"], "bonds": ["RU000A107795"], "other": ["TMON"]})

    def test_bond_without_isin_falls_back_to_ticker(self):
        path = _write_json({"holdings": [{"asset_type": "bond", "ticker": "SU26238RMFS4", "status": "normal"}]})
        g = secids_from_portfolio(path)
        os.unlink(path)
        self.assertEqual(g["bonds"], ["SU26238RMFS4"])


class TestMarketValuesJson(unittest.TestCase):
    def test_reads_market_values_from_portfolio_json(self):
        path = _write_json({
            "stocks": [
                {"Тикер": "GMKN", "Стоимость": 135824.0},
                {"Тикер": "LENT", "Стоимость": 45962.5},
                {"Тикер": "ZERO", "Стоимость": 0.0},
            ],
            "bonds": [
                {"Тикер": "RU000A105JH9", "Текущая стоимость": 603686.79},
            ],
        })
        mv = load_market_values_from_common(path, {"GMKN", "RU000A105JH9", "ABSENT"})
        os.unlink(path)
        self.assertEqual(mv["GMKN"], 135824.0)
        self.assertEqual(mv["RU000A105JH9"], 603686.79)
        self.assertNotIn("ABSENT", mv)               # не запрошенный — не возвращается
        self.assertNotIn("LENT", mv)                 # не в наборе tickers

    def test_zero_value_skipped_filter(self):
        path = _write_json({"stocks": [{"Тикер": "ZERO", "Стоимость": 0.0}]})
        # 0.0 — валидное число, попадёт (фильтр >0 живёт в secids, не здесь);
        # проверяем лишь что .json-ветка не падает и тип корректен
        mv = load_market_values_from_common(path, {"ZERO"})
        os.unlink(path)
        self.assertEqual(mv.get("ZERO"), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

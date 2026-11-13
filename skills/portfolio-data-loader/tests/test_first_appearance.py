#!/usr/bin/env python3
"""Тесты для _apply_first_appearance и _apply_sector_overrides в assemble_snapshot.py.

PDL-I (2026-08-27): sector (машинный ключ) и sector_ru (отображаемый ярлык) —
раздельные поля, overrides-словарь теперь {ticker: {"sector":..., "sector_ru":...}}.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.assemble_snapshot import _apply_first_appearance, _apply_sector_overrides, _load_sector_overrides


class TestFirstAppearance(unittest.TestCase):
    def test_no_prev_snapshot_sets_today(self):
        holdings = [{"ticker": "SBER"}, {"ticker": "OZON"}]
        _apply_first_appearance(holdings, None, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2026-05-13")
        self.assertEqual(holdings[1]["first_appearance_date"], "2026-05-13")

    def test_carryover_from_prev_snapshot(self):
        holdings = [{"ticker": "SBER"}, {"ticker": "OZON"}]
        prev = {"holdings": [
            {"ticker": "SBER", "first_appearance_date": "2020-03-15"},
            {"ticker": "OZON", "first_appearance_date": "2023-10-17"},
        ]}
        _apply_first_appearance(holdings, prev, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2020-03-15")
        self.assertEqual(holdings[1]["first_appearance_date"], "2023-10-17")

    def test_new_ticker_gets_today(self):
        holdings = [
            {"ticker": "SBER"},  # был в prev
            {"ticker": "BTBR"},  # новый
        ]
        prev = {"holdings": [{"ticker": "SBER", "first_appearance_date": "2020-03-15"}]}
        _apply_first_appearance(holdings, prev, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2020-03-15")
        self.assertEqual(holdings[1]["first_appearance_date"], "2026-05-13")

    def test_reentry_treated_as_new(self):
        # Тикер был, исчез, появился снова — first_appearance_date = today.
        # prev_snapshot не содержит этого тикера → carry-over невозможен.
        holdings = [{"ticker": "OZON"}]
        prev = {"holdings": [
            # OZON отсутствует в prev (был divested ранее)
            {"ticker": "SBER", "first_appearance_date": "2020-03-15"},
        ]}
        _apply_first_appearance(holdings, prev, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2026-05-13")

    def test_supports_positions_key(self):
        # auto_maintain поддерживает оба ключа — holdings и positions
        holdings = [{"ticker": "SBER"}]
        prev = {"positions": [{"ticker": "SBER", "first_appearance_date": "2020-03-15"}]}
        _apply_first_appearance(holdings, prev, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2020-03-15")

    def test_empty_holdings_safe(self):
        # Не должно падать на пустом списке
        _apply_first_appearance([], None, "2026-05-13")
        _apply_first_appearance(None, None, "2026-05-13")

    def test_skip_invalid_entries(self):
        # Записи без ticker или не dict — пропускаем без падения
        holdings = [{"ticker": "SBER"}, {}, "string"]
        _apply_first_appearance(holdings, None, "2026-05-13")
        self.assertEqual(holdings[0]["first_appearance_date"], "2026-05-13")
        # holdings[1] остался без поля — это OK
        self.assertNotIn("first_appearance_date", holdings[1])


_OVERRIDES_YAML = """\
version: 1
last_updated: '2026-06-11'
overrides:
  - ticker: SBER
    sector: banks_finance
    note: test
  - ticker: RU000A105KU0
    sector: bonds_rub
    note: test isin
  - ticker: NVTK
    sector: oil_gas
    sector_ru: "Энергетический"
    note: test sector_ru display label
  - ticker: LSNGP
    sector: utilities
    sector_ru: "Электроэнергетика"
    note: test sector_ru with space-free label
"""


class TestSectorOverrides(unittest.TestCase):
    def test_sets_sector_from_overrides(self):
        overrides = {"SBER": {"sector": "banks_finance"}, "NVTK": {"sector": "oil_gas"}}
        holdings = [{"ticker": "SBER"}, {"ticker": "NVTK"}]
        _apply_sector_overrides(holdings, overrides)
        self.assertEqual(holdings[0]["sector"], "banks_finance")
        self.assertEqual(holdings[1]["sector"], "oil_gas")

    def test_unknown_ticker_stays_none(self):
        overrides = {"SBER": {"sector": "banks_finance"}}
        holdings = [{"ticker": "UNKNOWN"}]
        _apply_sector_overrides(holdings, overrides)
        self.assertIsNone(holdings[0].get("sector"))

    def test_existing_sector_not_overwritten(self):
        overrides = {"SBER": {"sector": "wrong"}}
        holdings = [{"ticker": "SBER", "sector": "it_telecom"}]
        _apply_sector_overrides(holdings, overrides)
        self.assertEqual(holdings[0]["sector"], "it_telecom")

    def test_empty_overrides_safe(self):
        holdings = [{"ticker": "SBER"}]
        _apply_sector_overrides(holdings, {})
        self.assertIsNone(holdings[0].get("sector"))

    def test_none_holdings_safe(self):
        _apply_sector_overrides(None, {"SBER": {"sector": "banks_finance"}})

    def test_apply_sector_overrides_sets_sector_ru_separately(self):
        """PDL-I: sector (машинный ключ) и sector_ru (ярлык) заполняются из РАЗНЫХ
        полей записи override и никогда не подменяют друг друга."""
        overrides = {
            "NVTK": {"sector": "oil_gas", "sector_ru": "Энергетический"},
            "T": {"sector": "banks_finance", "sector_ru": None},
        }
        holdings = [{"ticker": "NVTK"}, {"ticker": "T"}]
        _apply_sector_overrides(holdings, overrides)
        self.assertEqual(holdings[0]["sector"], "oil_gas")
        self.assertEqual(holdings[0]["sector_ru"], "Энергетический")
        self.assertEqual(holdings[1]["sector"], "banks_finance")
        self.assertIsNone(holdings[1].get("sector_ru"))  # нет ярлыка в overrides — не выдумываем

    def test_apply_sector_overrides_existing_sector_ru_not_overwritten(self):
        overrides = {"SBER": {"sector": "banks_finance", "sector_ru": "Финансовый"}}
        holdings = [{"ticker": "SBER", "sector_ru": "уже задано"}]
        _apply_sector_overrides(holdings, overrides)
        self.assertEqual(holdings[0]["sector_ru"], "уже задано")

    def test_no_mixed_dictionaries_no_cyrillic_in_sector(self):
        """Сторож PDL-I: в одном прогоне через overrides значения sector[] —
        только машинные ключи, ни один ярлык из sector_ru не просочился в sector."""
        overrides = _load_sector_overrides_from_text(_OVERRIDES_YAML)
        holdings = [{"ticker": t} for t in ("SBER", "RU000A105KU0", "NVTK", "LSNGP")]
        _apply_sector_overrides(holdings, overrides)
        sectors = {h["sector"] for h in holdings if h.get("sector")}
        self.assertTrue(
            all(not any("а" <= ch.lower() <= "я" for ch in s) for s in sectors),
            f"кириллица просочилась в sector: {sectors}",
        )

    def test_load_sector_overrides_from_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sector-overrides.yaml"
            path.write_text(_OVERRIDES_YAML, encoding="utf-8")
            result = _load_sector_overrides(str(path))
        self.assertEqual(result.get("SBER"), {"sector": "banks_finance", "sector_ru": None})
        self.assertEqual(result.get("RU000A105KU0"), {"sector": "bonds_rub", "sector_ru": None})

    def test_load_sector_overrides_keeps_sector_and_sector_ru_separate(self):
        """PDL-I: sector остаётся машинным ключом ДАЖЕ когда sector_ru задан."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sector-overrides.yaml"
            path.write_text(_OVERRIDES_YAML, encoding="utf-8")
            result = _load_sector_overrides(str(path))
        self.assertEqual(result.get("NVTK"), {"sector": "oil_gas", "sector_ru": "Энергетический"})
        self.assertEqual(result.get("LSNGP"), {"sector": "utilities", "sector_ru": "Электроэнергетика"})
        # запись без sector_ru — ярлык None, canon-ключ как обычно
        self.assertEqual(result.get("SBER"), {"sector": "banks_finance", "sector_ru": None})

    def test_load_sector_overrides_dirty_input_robustness(self):
        """Аудит 2026-08-03: инлайн-комментарии и хвостовые секции не портят разбор."""
        yaml_text = (
            "version: 1\noverrides:\n"
            "  - ticker: AAA\n"
            "    sector: banks_finance  # инлайн-комментарий у значения\n"
            "  - ticker: BBB  # инлайн-комментарий у тикера\n"
            "    sector: oil_gas\n"
            "  - ticker: CCC\n"
            '    sector_ru: "Рус"\n'          # запись без canon-sector — должна выпасть
            "fund_classification:\n"
            "  cash_equivalent:\n"
            "    sector: leaked\n"            # хвостовая секция не должна дозаполнить CCC
            "    tickers: [TMON]\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sector-overrides.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            result = _load_sector_overrides(str(path))
        self.assertEqual(result.get("AAA"), {"sector": "banks_finance", "sector_ru": None})  # комментарий отрезан
        self.assertEqual(result.get("BBB"), {"sector": "oil_gas", "sector_ru": None})        # запись не потеряна
        self.assertNotIn("CCC", result)                       # leaked-sector не просочился
        self.assertEqual(set(result), {"AAA", "BBB"})

    def test_load_sector_overrides_multiword_label(self):
        """Ярлык с пробелами («Потребительский цикличный») не режется на первом слове."""
        yaml_text = (
            "version: 1\noverrides:\n"
            "  - ticker: LENT\n"
            "    sector: consumer\n"
            '    sector_ru: "Потребительский защитный"\n'
            "    note: test\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sector-overrides.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            result = _load_sector_overrides(str(path))
        self.assertEqual(result.get("LENT"), {"sector": "consumer", "sector_ru": "Потребительский защитный"})

    def test_load_sector_overrides_missing_file(self):
        result = _load_sector_overrides("/nonexistent/path.yaml")
        self.assertEqual(result, {})

    def test_load_sector_overrides_none_path(self):
        result = _load_sector_overrides(None)
        self.assertEqual(result, {})


def _load_sector_overrides_from_text(text: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sector-overrides.yaml"
        path.write_text(text, encoding="utf-8")
        return _load_sector_overrides(str(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)

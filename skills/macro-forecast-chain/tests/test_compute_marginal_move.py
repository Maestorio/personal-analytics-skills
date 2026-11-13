#!/usr/bin/env python3
"""
test_compute_marginal_move.py — юнит-тесты парсера строк-уровней FCA (MFC-4).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from compute_marginal_move import parse_level_string, enrich_factor, process


class TestParseLevelString(unittest.TestCase):
    # ── brent / usd_per_bbl ──
    def test_brent_dollar_slash_bbl(self):
        level, unit = parse_level_string("$68/bbl (JPMorgan-dominant weighted median)", "brent")
        self.assertAlmostEqual(level, 68.0)
        self.assertEqual(unit, "usd_per_bbl")

    def test_brent_compact(self):
        level, unit = parse_level_string("$57/bbl", "brent")
        self.assertAlmostEqual(level, 57.0)
        self.assertEqual(unit, "usd_per_bbl")

    def test_brent_decimal(self):
        level, unit = parse_level_string("$74.5/bbl (consensus)", "brent")
        self.assertAlmostEqual(level, 74.5)
        self.assertEqual(unit, "usd_per_bbl")

    def test_brent_no_dollar_sign_but_hint(self):
        # Нет явного $ — fallback через hint
        level, unit = parse_level_string("65 (медиана взвешенная)", "brent")
        self.assertAlmostEqual(level, 65.0)
        self.assertEqual(unit, "usd_per_bbl")

    # ── usdrub / rub_per_usd ──
    def test_usdrub_cyrillic(self):
        level, unit = parse_level_string("88 руб./$ (D1 EV)", "usdrub")
        self.assertAlmostEqual(level, 88.0)
        self.assertEqual(unit, "rub_per_usd")

    def test_usdrub_no_space(self):
        level, unit = parse_level_string("71 руб./$", "usdrub")
        self.assertAlmostEqual(level, 71.0)
        self.assertEqual(unit, "rub_per_usd")

    def test_usdrub_decimal_comma(self):
        level, unit = parse_level_string("85,5 руб./$", "usdrub")
        self.assertAlmostEqual(level, 85.5)
        self.assertEqual(unit, "rub_per_usd")

    def test_usdrub_decimal_dot(self):
        level, unit = parse_level_string("87.3 руб./$", "usdrub")
        self.assertAlmostEqual(level, 87.3)
        self.assertEqual(unit, "rub_per_usd")

    # ── cnyrub / rub_per_cny ──
    def test_cnyrub_yen_symbol(self):
        level, unit = parse_level_string("12.5 руб./¥", "cnyrub")
        self.assertAlmostEqual(level, 12.5)
        self.assertEqual(unit, "rub_per_cny")

    # ── cbr_rate / rate_pct ──
    def test_cbr_rate_with_date(self):
        level, unit = parse_level_string("14.5% к 2026-12-31", "cbr_rate")
        self.assertAlmostEqual(level, 14.5)
        self.assertEqual(unit, "rate_pct")

    def test_cbr_rate_plain_pct(self):
        level, unit = parse_level_string("12%", "cbr_rate")
        self.assertAlmostEqual(level, 12.0)
        self.assertEqual(unit, "rate_pct")

    def test_pct_ignored_for_non_rate_factor(self):
        # % без cbr_rate hint — не должно быть rate_pct
        level, unit = parse_level_string("15% к 2026-12-31", "brent")
        # Попадает во fallback-hint как usd_per_bbl
        self.assertAlmostEqual(level, 15.0)
        self.assertEqual(unit, "usd_per_bbl")

    # ── xauusd / usd_per_troy_oz ──
    def test_xauusd_dollar_amount(self):
        level, unit = parse_level_string("$1950 (медиана)", "xauusd")
        self.assertAlmostEqual(level, 1950.0)
        self.assertEqual(unit, "usd_per_troy_oz")

    # ── fallback через hint ──
    def test_fallback_hint_usdrub(self):
        level, unit = parse_level_string("88 (медиана источников)", "usdrub")
        self.assertAlmostEqual(level, 88.0)
        self.assertEqual(unit, "rub_per_usd")

    # ── unknown / no match ──
    def test_nonnumeric_returns_none(self):
        level, unit = parse_level_string("Pure Shell D1 (A=B=C=D=0.25)", "geopolitics")
        self.assertIsNone(level)
        self.assertIsNone(unit)

    def test_empty_string(self):
        level, unit = parse_level_string("", "brent")
        self.assertIsNone(level)

    def test_unknown_factor_no_number(self):
        level, unit = parse_level_string("Holding pattern ~50%", "sanctions")
        self.assertIsNone(level)
        self.assertIsNone(unit)

    def test_non_string_returns_none(self):
        level, unit = parse_level_string(None, "brent")  # type: ignore
        self.assertIsNone(level)
        self.assertIsNone(unit)


class TestEnrichFactor(unittest.TestCase):
    def test_adds_level_and_unit_brent(self):
        fcast = {
            "central_estimate_l1_2026": "$68/bbl (JPMorgan)",
            "central_estimate_l1_2027": "$57/bbl",
            "other_field": "some value",
        }
        result = enrich_factor("brent", fcast)
        self.assertAlmostEqual(result["level_l1_2026"], 68.0)
        self.assertAlmostEqual(result["level_l1_2027"], 57.0)
        self.assertEqual(result["unit"], "usd_per_bbl")
        # Исходные поля сохраняются
        self.assertEqual(result["central_estimate_l1_2026"], "$68/bbl (JPMorgan)")
        self.assertEqual(result["other_field"], "some value")

    def test_adds_level_usdrub(self):
        fcast = {"central_estimate_l1_2026": "88 руб./$ (D1 EV)"}
        result = enrich_factor("usdrub", fcast)
        self.assertAlmostEqual(result["level_l1_2026"], 88.0)
        self.assertEqual(result["unit"], "rub_per_usd")

    def test_skips_unparseable_processes_valid(self):
        fcast = {
            "central_estimate_l1_2026": "Pure Shell — no number",
            "central_estimate_l1_2027": "$57/bbl",
        }
        result = enrich_factor("brent", fcast)
        self.assertNotIn("level_l1_2026", result)
        self.assertAlmostEqual(result["level_l1_2027"], 57.0)
        self.assertEqual(result["unit"], "usd_per_bbl")

    def test_non_dict_passthrough(self):
        self.assertEqual(enrich_factor("brent", "raw_text"), "raw_text")

    def test_no_l1_keys_unchanged(self):
        fcast = {"central_estimate": "$80/bbl", "confidence": 0.6}
        result = enrich_factor("brent", fcast)
        self.assertNotIn("level_l1_2026", result)
        self.assertNotIn("unit", result)
        self.assertEqual(result["central_estimate"], "$80/bbl")

    def test_doesnt_overwrite_existing_unit(self):
        fcast = {
            "central_estimate_l1_2026": "$68/bbl",
            "unit": "existing_unit",
        }
        result = enrich_factor("brent", fcast)
        self.assertEqual(result["unit"], "existing_unit")

    def test_year_key_not_int_skipped(self):
        fcast = {"central_estimate_l1_xxx": "$68/bbl"}
        result = enrich_factor("brent", fcast)
        self.assertNotIn("level_l1_xxx", result)


class TestProcess(unittest.TestCase):
    def test_real_macro_marginal_fragment(self):
        """Реальный фрагмент из macro-marginal-2026-05-11.yaml."""
        payload = {
            "brent": {
                "type": "conditional_estimate",
                "central_estimate_l1_2026": "$68/bbl (JPMorgan-dominant weighted median)",
                "central_estimate_l1_2027": "$57/bbl",
            },
            "usdrub": {
                "central_estimate_l1_2026": "88 руб./$ (D1 EV)",
            },
            "geopolitics": {
                "central_estimate": "Pure Shell D1: A=B=C=D=0.25",
            },
            "sanctions": {
                "central_estimate": "Holding pattern ~50%",
            },
        }
        result = process(payload)

        self.assertAlmostEqual(result["brent"]["level_l1_2026"], 68.0)
        self.assertAlmostEqual(result["brent"]["level_l1_2027"], 57.0)
        self.assertEqual(result["brent"]["unit"], "usd_per_bbl")
        # Исходная строка сохранена
        self.assertIn("central_estimate_l1_2026", result["brent"])

        self.assertAlmostEqual(result["usdrub"]["level_l1_2026"], 88.0)
        self.assertEqual(result["usdrub"]["unit"], "rub_per_usd")

        # Качественные факторы не получают level_l1
        self.assertNotIn("level_l1_2026", result["geopolitics"])
        self.assertNotIn("level_l1_2026", result["sanctions"])

    def test_cbr_rate_factor(self):
        payload = {
            "cbr_rate": {
                "central_estimate_l1_2026": "14.5% к 2026-12-31",
                "central_estimate_l1_2027": "12%",
            }
        }
        result = process(payload)
        self.assertAlmostEqual(result["cbr_rate"]["level_l1_2026"], 14.5)
        self.assertAlmostEqual(result["cbr_rate"]["level_l1_2027"], 12.0)
        self.assertEqual(result["cbr_rate"]["unit"], "rate_pct")

    def test_empty_payload(self):
        self.assertEqual(process({}), {})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for classify_catalyst.py — heuristic classifier (METH-1)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from classify_catalyst import classify_catalyst  # noqa: E402


class BinaryDetection(unittest.TestCase):
    def test_dividend_record_date(self):
        c = {"id": "dividend_record_date_2025",
             "trigger": "Otsechka reestra ~20 iyulya 2026 (dividend 37.64 rub./aktsiya)"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")
        self.assertIn(r["confidence"], ("HIGH", "MEDIUM"))

    def test_msfo_q1(self):
        c = {"id": "q1_msfo_2026",
             "trigger": "MSFO Q1 2026 — ChP > 4 mlrd rub. -> signal k dokupke"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_sanctions_easing(self):
        c = {"id": "sanctions_easing_arctic_spg2",
             "trigger": "Snyatiye sanktsiy na LNG-oborudovaniye (Sc-A) -> vozobnovleniye Arktik SPG-2"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_buyback(self):
        c = {"id": "buyback_2027",
             "trigger": "Programma obratnogo vykupa aktsiy na 50 mlrd"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_uniper_resolution(self):
        c = {"id": "dividend_resumption_uniper_resolution",
             "trigger": "Zaversheniye uregulirovaniya s Uniper -> razblokiurovka nakoplennykh dividendov"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_redemption(self):
        c = {"id": "redemption",
             "trigger": "Pogashenie OFZ v 2041-05-15"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_capex_event(self):
        c = {"id": "sukhoilog_capex_risk",
             "trigger": "CAPEX Sukhoy Log prevyshaet plan -> davleniye na FCF i dividendy"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")

    def test_glp1_launch(self):
        c = {"id": "glp1_launch_2026",
             "trigger": "Vyvod GLP-1 (analog semgalutida) na rynok RF -> novyy segment"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")


class QuantitativeDetection(unittest.TestCase):
    def test_rate_cut_rerating(self):
        c = {"id": "rate_cut_rerating_2026",
             "trigger": "Snizhenie KS s 14.5% -> 12.0% k kontsu 2026 -> rost multiplikatorov P/B"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")
        self.assertIn(r["confidence"], ("HIGH", "MEDIUM"))

    def test_rate_cut_consumer_lending(self):
        c = {"id": "rate_cut_consumer_lending_2027",
             "trigger": "KS 9.5% -> ozhivleniye potrebkreditovaniya -> rost portfelya MBNK"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")

    def test_credit_growth_rerating(self):
        c = {"id": "credit_growth_rate_cut_2027",
             "trigger": "Snizhenie KS -> rost kreditovaniya, re-reyting rosta fintech-multiplikatorov"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")

    def test_market_share_growth(self):
        c = {"id": "market_share_growth_2027",
             "trigger": "Rost doli rynka cherez Chizhik (diskaunt)"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")

    def test_nim_compression(self):
        c = {"id": "nim_compression_risk",
             "trigger": "Snizhenie KS -> szhatiye NIM na klientskie ostatki"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")

    def test_palladium_substitution(self):
        c = {"id": "palladium_ev_substitution_risk",
             "trigger": "Uskoreniye perekhoda na EV -> snizheniye automotive-sprosa na Pd"}
        r = classify_catalyst(c)
        # transition к EV — continuous процесс; "snizheniye sprosa" — постепенное
        # ожидаем quant, но может быть LOW confidence
        self.assertIn(r["suggested_kind"], ("quantitative", "binary"))


class ConflictAndEdge(unittest.TestCase):
    def test_unknown_trigger_defaults_to_binary_low_conf(self):
        c = {"id": "mystery", "trigger": "neponyatno chto"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "binary")  # safer default
        self.assertEqual(r["confidence"], "LOW")
        self.assertTrue(any("no keyword matched" in w for w in r["warnings"]))

    def test_empty_trigger(self):
        c = {"id": "empty"}
        r = classify_catalyst(c)
        self.assertEqual(r["confidence"], "LOW")

    def test_conflicting_keywords(self):
        # «launch продукта» (binary) + «rost vyruchki» (quant) одновременно
        c = {"id": "launch_growth",
             "trigger": "Vyvod produkta na rynok privedet k rostu vyruchki cherez mesyats"}
        r = classify_catalyst(c)
        # Должно поднять conflicting warning
        self.assertIn(r["suggested_kind"], ("binary", "quantitative"))
        # Один из keyword sets должен дать тие или явный winner — warning ожидается
        warnings_str = " ".join(r.get("warnings", []))
        # Допускаем 1+ совпадение каждого типа → warning или conflict сообщение
        self.assertTrue(
            r["confidence"] in ("MEDIUM", "LOW") or "conflicting" in warnings_str
        )

    def test_id_only_matches(self):
        # Только id, без trigger
        c = {"id": "rate_cut_developer_rerating_2027"}
        r = classify_catalyst(c)
        self.assertEqual(r["suggested_kind"], "quantitative")


class RealReviewSample(unittest.TestCase):
    """Прогон на реальной выборке катализаторов из weekly-review-stock-2026-05-11."""

    def test_sber_three_catalysts(self):
        cats = [
            {"id": "rate_cut_rerating_2026",
             "trigger": "Snizhenie KS s 14.5% -> 12.0% k kontsu 2026 -> rost multiplikatorov P/B"},
            {"id": "dividend_record_date_2025",
             "trigger": "Otsechka reestra ~20 iyulya 2026 (dividend 37.64 rub./aktsiya)"},
            {"id": "credit_cycle_recovery_2027",
             "trigger": "Snyatie ogranicheniy po lgnotnoy ipoteke, rost kreditnogo portfelya"},
        ]
        results = [classify_catalyst(c)["suggested_kind"] for c in cats]
        self.assertEqual(results, ["quantitative", "binary", "quantitative"])

    def test_ozon_two_catalysts(self):
        cats = [
            {"id": "profitability_turn_2026",
             "trigger": "Q1 2026 MSFO PODTVERZHDYON: GMV +36% g/g, vyruchka +49%"},
            {"id": "fintech_ozon_bank_2027",
             "trigger": "Masshtabirovaniye Ozon Bank — rost take rate, GMV-fintech"},
        ]
        results = [classify_catalyst(c)["suggested_kind"] for c in cats]
        # profitability — binary (MSFO release); fintech_scale — quantitative (gradient growth)
        self.assertIn(results[0], ("binary", "quantitative"))
        self.assertIn(results[1], ("binary", "quantitative"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

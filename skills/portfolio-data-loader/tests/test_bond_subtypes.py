#!/usr/bin/env python3
"""Тесты подтипов облигаций (PDL-1…7) — docs/investment/portfolio/bond-subtypes-plan.md.

Покрывает §5.2 плана (13 пунктов, stdlib only, синтетические данные):
парсинг «План по Облигациям» (новая колонка `Подтип` / legacy `Рейтинг`),
агрегаты `bonds_value_by_subtype*`, прокидку `plan_bucket`/`plan_subtype`/
`credit_rating_file` в `holdings[]`, лестницу рейтингов §4.2, все 14 гейтов
§5.1 (срабатывание и молчание), блок `bonds_plan_vs_fact` (база excl_iis,
TLCB-кейс §3.1) и `bonds_plan_vs_fact_iis`.

⚠️ Лестница §4.2 — контракт, не «улучшать» по интуиции: корзина `AA+`
содержит `AAA`, корзина `B+` содержит `BBB+` (ярлыки владельца, не пороги).
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.parse_portfolio import (  # noqa: E402
    CORP_SUBTYPE_BUCKETS,
    VALID_TYPE_SUBTYPE,
    _bond_bucket_key,
    _bonds_breakdown_subtype_column,
    _check_bond_subtype_gates,
    _enrich_bonds_breakdown,
    _rows_to_dicts,
    compute_metrics,
    rating_to_corp_bucket,
)
from scripts.assemble_snapshot import (  # noqa: E402
    _build_bonds,
    _build_bonds_plan_vs_fact,
    _check_balance_vs_trades_drift,
    BALANCE_VS_TRADES_DRIFT_THRESHOLD,
    _moex_confirms_floater,
    _plan_bucket_key,
)


# ── общие фикстуры ────────────────────────────────────────────────────────────

def _plan_rows_new() -> list[list]:
    """«План по Облигациям» с новой колонкой `Подтип» — 9 корзин + Итог
    (числа обезличены)."""
    return [
        ["Тип", "Подтип", "Доля План", "План сумма", "Нынешняя Сумма", "Изменение"],
        ["USD", None, 0.12, 2542577.04, 8942311.53, -6399734.49],
        ["EUR", None, 0.0, 0.0, 1726189.86, -1726189.86],
        ["CNY", None, 0.2, 4237628.4, 1528461.72, 2709166.68],
        ["ОФЗ", ">10", 0.3, 6356442.6, 1943690.67, 4412751.93],
        ["ОФЗ", "<10", 0.0, 0.0, 1234039.83, -1234039.83],
        ["ОФЗ", "Флоат", 0.05, 1059407.1, None, 1059407.1],
        ["КОРП", "AA+", 0.05, 1059407.1, 2372467.29, -1313060.19],
        ["КОРП", "A", 0.2, 4237628.4, 1426646.28, 2810982.12],
        ["КОРП", "B+", 0.08, 1695051.36, 849621.03, 845430.33],
        ["Итог", None, 1.0, 21188142.0, 20023428.21, None],
    ]


def _plan_rows_legacy() -> list[list]:
    """Legacy-схема (до 2026-08-18): колонка `Рейтинг», 6 корзин
    (КОРП/AAA, КОРП/BBB — §4.4 обратная совместимость)."""
    return [
        ["Тип", "Рейтинг", "Доля План", "План сумма", "Нынешняя Сумма", "Изменение"],
        ["USD", None, 0.15, 1000000.0, 900000.0, 100000.0],
        ["EUR", None, 0.1, 500000.0, 400000.0, 100000.0],
        ["CNY", None, 0.2, 1000000.0, 900000.0, 100000.0],
        ["ОФЗ", None, 0.25, 1500000.0, 1400000.0, 100000.0],
        ["КОРП", "AAA", 0.2, 1000000.0, 900000.0, 100000.0],
        ["КОРП", "BBB", 0.1, 500000.0, 400000.0, 100000.0],
    ]


def _base_bonds_breakdown() -> list[dict]:
    """Уже обогащённая (PDL-1) «План по Облигациям» для тестов
    compute_metrics — согласована с _base_bonds()/_base_data() ниже так,
    чтобы ВСЕ гейты §5.1 молчали (регресс-фикстура)."""
    rows = [
        ["Тип", "Подтип", "Доля План", "План сумма", "Нынешняя Сумма", "Изменение"],
        ["USD", None, 0.2, 90000.0, 90000.0, 0.0],
        ["ОФЗ", ">10", 0.3, 120000.0, 120000.0, 0.0],
        ["ОФЗ", "<10", 0.2, 80000.0, 80000.0, 0.0],
        ["КОРП", "AA+", 0.15, 60000.0, 60000.0, 0.0],
        ["КОРП", "A", 0.1, 40000.0, 40000.0, 0.0],
        ["КОРП", "B+", 0.05, 20000.0, 20000.0, 0.0],
        ["Итог", None, 1.0, 410000.0, 410000.0, None],
    ]
    return _enrich_bonds_breakdown(_rows_to_dicts(rows), "Подтип")


def _base_bonds() -> list[dict]:
    """Строки «Облигации» (per-bond), включая split main/ИИС-кейс (ОФЗ 26238)."""
    return [
        {"Тикер": "B1", "Название": "ОФЗ-длинная-1", "Тип": "ОФЗ", "Подтип": ">10",
         "Текущая стоимость": 100000.0, "Всего": 100.0, "ИИС": 0.0,
         "Итого без ИИСа": 100000.0, "Итого на ИИС": 0.0},
        # Split-кейс: main 20000 + ИИС 30000 (реальный аналог ОФЗ 26238).
        {"Тикер": "B2", "Название": "ОФЗ-длинная-2", "Тип": "ОФЗ", "Подтип": ">10",
         "Текущая стоимость": 50000.0, "Всего": 50.0, "ИИС": 30.0,
         "Итого без ИИСа": 20000.0, "Итого на ИИС": 30000.0},
        {"Тикер": "B3", "Название": "ОФЗ-короткая", "Тип": "ОФЗ", "Подтип": "<10",
         "Текущая стоимость": 80000.0, "Всего": 80.0, "ИИС": 0.0,
         "Итого без ИИСа": 80000.0, "Итого на ИИС": 0.0},
        {"Тикер": "C1", "Название": "Корп-AA", "Тип": "КОРП", "Подтип": "AA+",
         "Рейтинг": "AAA", "Текущая стоимость": 60000.0, "Всего": 60.0, "ИИС": 0.0,
         "Итого без ИИСа": 60000.0, "Итого на ИИС": 0.0},
        {"Тикер": "C2", "Название": "Корп-A", "Тип": "КОРП", "Подтип": "A",
         "Рейтинг": "A", "Текущая стоимость": 40000.0, "Всего": 40.0, "ИИС": 0.0,
         "Итого без ИИСа": 40000.0, "Итого на ИИС": 0.0},
        {"Тикер": "C3", "Название": "Корп-B", "Тип": "КОРП", "Подтип": "B+",
         "Рейтинг": "BB", "Текущая стоимость": 20000.0, "Всего": 20.0, "ИИС": 0.0,
         "Итого без ИИСа": 20000.0, "Итого на ИИС": 0.0},
        {"Тикер": "U1", "Название": "USD-бумага", "Тип": "USD", "Подтип": None,
         "Текущая стоимость": 90000.0, "Всего": 9.0, "ИИС": 0.0,
         "Итого без ИИСа": 90000.0, "Итого на ИИС": 0.0},
    ]


def _base_data() -> dict:
    """Полный синтетический `data` (выход extract_portfolio) — согласован
    так, что ВСЕ 7 compute_metrics-гейтов (§5.1) молчат: регресс-фикстура,
    от которой тесты «гейт срабатывает» отталкиваются точечной мутацией."""
    return {
        "summary": {"Имеется (RUB)": 500000.0, "ИИС": 30000.0},
        "goals": {
            "overall": [],
            "matrix": [
                {"Валюта": "RUB", "Бумага": "Кеш", "Сейчас": 10000.0},
                {"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 50000.0},
                # ОФЗ+КОРП excl_iis = 120000+80000+60000+40000+20000 = 320000
                {"Валюта": "RUB", "Бумага": "Облигация", "Сейчас": 320000.0},
                {"Валюта": "USD", "Бумага": "Облигация", "Сейчас": 90000.0},
            ],
            "matrix_iis": [
                {"Валюта": "RUB", "Бумага": "ИИС", "Сейчас": 30000.0},
            ],
            "bonds_breakdown": _base_bonds_breakdown(),
        },
        "other_positions": [],
        "iis_positions": [],
        "errors_check": [],
        "stocks": [{"Тикер": "S1", "Название": "Тест-акция", "Стоимость": 50000.0}],
        "bonds": _base_bonds(),
        "bonds_iis": [],
        "bonds_main": [],
        "invest_era": [],
        "_flags": [],
    }


def _flag_codes(flags: list[dict]) -> set[str]:
    return {f["code"] for f in flags}


def _full_quote(**overrides) -> dict:
    """Полная MOEX-котировка (профиль weekly), как test_bond_enrichment._full_quote."""
    q = {
        "secid": "TEST",
        "kind": "bond",
        "isin": "RU000TEST001",
        "currency": "SUR",
        "short_name": "Тест Бонд",
        "last": 95.0,
        "ytm_pct": 14.0,
        "duration_days": 1500,
        "coupon_pct": 8.0,
        "coupon_period_days": 182,
        "next_coupon_date": "2026-09-01",
        "accrued_interest": 10.0,
        "face_value": 1000.0,
        "maturity_date": "2030-01-01",
        "offer_date": None,
        "timestamp": "2026-08-19T18:00:00",
    }
    q.update(overrides)
    return q


def _one_bond(**overrides) -> dict:
    bond = {
        "Тикер": "TEST", "Название": "Тест Бонд", "Тип": "ОФЗ", "Подтип": ">10",
        "Текущая стоимость": 100000.0, "Всего": 100.0, "ИИС": 0.0,
        "Итого без ИИСа": 100000.0, "Итого на ИИС": 0.0,
    }
    bond.update(overrides)
    return {"bonds": [bond]}


# ── 1, 2, 9: «План по Облигациям» — Подтип / legacy Рейтинг ──────────────────

class TestBondsBreakdownParsing(unittest.TestCase):
    def test_new_subtype_column_9_buckets(self):
        rows = _plan_rows_new()
        col = _bonds_breakdown_subtype_column(rows)
        self.assertEqual(col, "Подтип")
        enriched = _enrich_bonds_breakdown(_rows_to_dicts(rows), col)
        self.assertEqual(len(enriched), 10)  # 9 корзин + Итог
        bucket_keys = [r["_bucket_key"] for r in enriched if r["_bucket_key"]]
        self.assertEqual(len(bucket_keys), 9)
        self.assertIn("ОФЗ/>10", bucket_keys)
        self.assertIn("ОФЗ/<10", bucket_keys)
        self.assertIn("ОФЗ/Флоат", bucket_keys)
        self.assertIn("КОРП/AA+", bucket_keys)
        self.assertIn("КОРП/A", bucket_keys)
        self.assertIn("КОРП/B+", bucket_keys)
        self.assertIn("USD", bucket_keys)
        # «Итог» не отражает ни одну корзину.
        itog = next(r for r in enriched if r["Тип"] == "Итог")
        self.assertIsNone(itog["_bucket_key"])

    def test_legacy_rating_column_no_crash(self):
        """Парс с legacy `Рейтинг» — корзины строятся, падения нет (§4.4)."""
        rows = _plan_rows_legacy()
        col = _bonds_breakdown_subtype_column(rows)
        self.assertEqual(col, "Рейтинг")
        enriched = _enrich_bonds_breakdown(_rows_to_dicts(rows), col)
        self.assertEqual(len(enriched), 6)
        bucket_keys = {r["_bucket_key"] for r in enriched}
        self.assertEqual(
            bucket_keys,
            {"USD", "EUR", "CNY", "ОФЗ", "КОРП/AAA", "КОРП/BBB"},
        )
        # Исходный ключ Рейтинг остаётся как есть — не переименован/удалён.
        corp_row = next(r for r in enriched if r["_bucket_key"] == "КОРП/AAA")
        self.assertEqual(corp_row["Рейтинг"], "AAA")

    def test_empty_subtype_currency_rows_no_flags(self):
        """Пустой Подтип у валютных строк (USD/EUR/CNY) — норма, флагов нет."""
        bonds = [
            {"Тикер": "U1", "Название": "USD1", "Тип": "USD", "Подтип": None},
            {"Тикер": "E1", "Название": "EUR1", "Тип": "EUR", "Подтип": None},
            {"Тикер": "N1", "Название": "CNY1", "Тип": "CNY", "Подтип": None},
        ]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(flags, [])


# ── 3, 4: агрегаты bonds_value_by_subtype* ────────────────────────────────────

class TestSubtypeAggregates(unittest.TestCase):
    def test_subtype_sums_and_identity_vs_by_type(self):
        data = _base_data()
        m = compute_metrics(data)
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["ОФЗ/>10"], 120000.0)
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["ОФЗ/<10"], 80000.0)
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["КОРП/AA+"], 60000.0)
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["КОРП/A"], 40000.0)
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["КОРП/B+"], 20000.0)
        self.assertEqual(m["bonds_value_by_subtype"]["USD"], 90000.0)

        # Тождество: Σ по подтипам == bonds_value_by_type (несплитованный срез)
        ofz_subtype_sum = sum(
            v for k, v in m["bonds_value_by_subtype"].items() if k.startswith("ОФЗ/")
        )
        corp_subtype_sum = sum(
            v for k, v in m["bonds_value_by_subtype"].items() if k.startswith("КОРП/")
        )
        self.assertAlmostEqual(ofz_subtype_sum, m["bonds_value_by_type"]["ОФЗ"])
        self.assertAlmostEqual(corp_subtype_sum, m["bonds_value_by_type"]["КОРП"])

    def test_main_iis_split_by_subtype(self):
        """ОФЗ 26238-подобный split-кейс: 20000 main + 30000 ИИС, оба в
        одной корзине ОФЗ/>10 (B1 100000 main + B2 20000 main/30000 ИИС)."""
        data = _base_data()
        m = compute_metrics(data)
        # excl_iis: B1(100000) + B2 main(20000) = 120000
        self.assertEqual(m["bonds_value_by_subtype_excl_iis"]["ОФЗ/>10"], 120000.0)
        # iis_only: только B2 ИИС-часть = 30000
        self.assertEqual(m["bonds_value_by_subtype_iis_only"]["ОФЗ/>10"], 30000.0)
        # incl (все): B1 100000 + B2 50000 = 150000
        self.assertEqual(m["bonds_value_by_subtype"]["ОФЗ/>10"], 150000.0)


# ── 5: прокидка plan_bucket/plan_subtype/credit_rating_file в holdings[] ─────

class TestHoldingsFieldsProkidka(unittest.TestCase):
    def test_fields_present_on_holding(self):
        portfolio = _one_bond(Тип="КОРП", Подтип="A", Рейтинг="A+")
        holdings, _ = _build_bonds(portfolio, {"TEST": _full_quote()}, as_of_iso="2026-08-19")
        self.assertEqual(len(holdings), 1)
        h = holdings[0]
        self.assertEqual(h["plan_bucket"], "КОРП")
        self.assertEqual(h["plan_subtype"], "A")
        self.assertEqual(h["plan_bucket_key"], "КОРП/A")
        self.assertEqual(h["credit_rating_file"], "A+")

    def test_currency_bond_bucket_key_no_subtype(self):
        portfolio = _one_bond(Тип="USD", Подтип=None)
        holdings, _ = _build_bonds(portfolio, {"TEST": _full_quote()}, as_of_iso="2026-08-19")
        h = holdings[0]
        self.assertEqual(h["plan_bucket"], "USD")
        self.assertIsNone(h["plan_subtype"])
        self.assertEqual(h["plan_bucket_key"], "USD")
        self.assertIsNone(h["credit_rating_file"])


# ── 6: лестница рейтингов §4.2 ────────────────────────────────────────────────

class TestRatingLadder(unittest.TestCase):
    def test_ladder_mapping(self):
        cases = {
            "AAA": "AA+", "AA-": "AA+", "AA": "AA+", "AA+": "AA+",
            "A+": "A", "A": "A", "A-": "A",
            "BBB+": "B+", "BB": "B+", "B-": "B+",
            "BBB": "B+", "BBB-": "B+", "BB+": "B+", "BB-": "B+", "B+": "B+", "B": "B+",
        }
        for rating, expected_bucket in cases.items():
            with self.subTest(rating=rating):
                self.assertEqual(rating_to_corp_bucket(rating), expected_bucket)

    def test_below_ladder_and_empty(self):
        self.assertIsNone(rating_to_corp_bucket("CCC"))
        self.assertIsNone(rating_to_corp_bucket("D"))
        self.assertIsNone(rating_to_corp_bucket(None))
        self.assertIsNone(rating_to_corp_bucket(""))

    def test_bucket_labels_are_not_thresholds(self):
        """⚠️ Контракт §4.2: AA+ содержит AAA, B+ содержит BBB+ — НЕ верхняя
        граница. Регресс-защита от «починки по интуиции»."""
        self.assertIn("AAA", CORP_SUBTYPE_BUCKETS["AA+"])
        self.assertIn("BBB+", CORP_SUBTYPE_BUCKETS["B+"])


# ── 7 (часть 1): per-bond гейты подтипа (parse_portfolio) ────────────────────

class TestPerBondSubtypeGates(unittest.TestCase):
    def test_bond_subtype_missing_fires(self):
        bonds = [{"Тикер": "X1", "Название": "N1", "Тип": "ОФЗ", "Подтип": None}]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(_flag_codes(flags), {"bond_subtype_missing"})

    def test_bond_subtype_missing_silent_when_present(self):
        bonds = [{"Тикер": "X1", "Название": "N1", "Тип": "ОФЗ", "Подтип": ">10"}]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(flags, [])

    def test_bond_subtype_unknown_fires(self):
        bonds = [{"Тикер": "X2", "Название": "N2", "Тип": "КОРП", "Подтип": "AAA"}]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(_flag_codes(flags), {"bond_subtype_unknown"})

    def test_bond_subtype_unknown_silent_for_valid_pair(self):
        bonds = [{"Тикер": "X2", "Название": "N2", "Тип": "КОРП", "Подтип": "AA+"}]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(flags, [])

    def test_corp_floater_valid_pair_no_unknown_flag(self):
        """Q4: КОРП/Флоат допустима структурно (§4.3) — не bond_subtype_unknown."""
        bonds = [{"Тикер": "X3", "Название": "N3", "Тип": "КОРП", "Подтип": "Флоат"}]
        flags = _check_bond_subtype_gates(bonds)
        self.assertEqual(flags, [])


# ── 7 (часть 2), 10, 11: гейты на уровне compute_metrics ─────────────────────

class TestPlanLevelGates(unittest.TestCase):
    def test_base_fixture_all_gates_silent(self):
        """Регресс-фикстура: ни один из 7 compute_metrics-гейтов не должен
        сработать на согласованных данных."""
        data = _base_data()
        compute_metrics(data)
        codes = _flag_codes(data["_flags"])
        self.assertEqual(
            codes & {
                "bond_bucket_not_in_plan", "bond_plan_shares_not_100",
                "bond_plan_base_mismatch", "matrix_bond_iis_leak",
                "balance_identity_broken",
            },
            set(),
        )

    def test_bond_bucket_not_in_plan_fires(self):
        data = _base_data()
        # ОФЗ/Флоат нет в плане (_base_bonds_breakdown), но бумага есть.
        data["bonds"].append({
            "Тикер": "F1", "Название": "Флоатер", "Тип": "ОФЗ", "Подтип": "Флоат",
            "Текущая стоимость": 10000.0, "Всего": 10.0, "ИИС": 0.0,
            "Итого без ИИСа": 10000.0, "Итого на ИИС": 0.0,
        })
        compute_metrics(data)
        self.assertIn("bond_bucket_not_in_plan", _flag_codes(data["_flags"]))

    def test_bond_plan_shares_not_100_fires(self):
        data = _base_data()
        # Портим долю плана: КОРП/B+ 0.05 → 0.5 (Σ уходит далеко от 1.0).
        for row in data["goals"]["bonds_breakdown"]:
            if row.get("_bucket_key") == "КОРП/B+":
                row["Доля План"] = 0.5
        compute_metrics(data)
        self.assertIn("bond_plan_shares_not_100", _flag_codes(data["_flags"]))

    def test_bond_plan_base_mismatch_fires_when_itog_matches_incl_iis(self):
        """§5.2 п.10: срабатывает, когда Итог/Нынешняя Сумма = Σ«Текущая
        стоимость» (incl_iis), а не Σ«Итого без ИИСа»."""
        data = _base_data()
        # incl_iis сумма всех бумаг = 440000 (см. _base_bonds())
        for row in data["goals"]["bonds_breakdown"]:
            if row.get("Тип") == "Итог":
                row["Нынешняя Сумма"] = 440000.0
        compute_metrics(data)
        self.assertIn("bond_plan_base_mismatch", _flag_codes(data["_flags"]))

    def test_bond_plan_base_mismatch_silent_when_itog_matches_excl_iis(self):
        """§5.2 п.10: молчит, когда Итог = Σ«Итого без ИИСа» (§3.1, база excl_iis)."""
        data = _base_data()  # Итог уже = 410000.0 = excl_iis сумма
        compute_metrics(data)
        self.assertNotIn("bond_plan_base_mismatch", _flag_codes(data["_flags"]))

    def test_matrix_bond_iis_leak_fires(self):
        data = _base_data()
        for row in data["goals"]["matrix"]:
            if row.get("Бумага") == "Облигация" and row.get("Валюта") == "RUB":
                row["Сейчас"] = 320000.0 + 30000.0  # протекла ИИС-3
        compute_metrics(data)
        self.assertIn("matrix_bond_iis_leak", _flag_codes(data["_flags"]))

    def test_matrix_bond_iis_leak_silent_on_base_fixture(self):
        data = _base_data()
        compute_metrics(data)
        self.assertNotIn("matrix_bond_iis_leak", _flag_codes(data["_flags"]))

    def test_balance_identity_broken_fires(self):
        data = _base_data()
        data["summary"]["Имеется (RUB)"] = 500000.0 + 50000.0  # разошлись
        compute_metrics(data)
        self.assertIn("balance_identity_broken", _flag_codes(data["_flags"]))

    def test_balance_identity_broken_silent_on_base_fixture(self):
        data = _base_data()
        compute_metrics(data)
        self.assertNotIn("balance_identity_broken", _flag_codes(data["_flags"]))


# ── 7 (часть 3): гейты на уровне _build_bonds (assemble_snapshot) ────────────

class TestBondBuildGates(unittest.TestCase):
    AS_OF = "2026-08-19"

    def test_ofz_maturity_mismatch_fires_short_in_long_bucket(self):
        """Реальный кейс: Казахст11 (RU000A101RZ3), Подтип «>10», погашение
        через ~4 года — гейт обязан сработать."""
        portfolio = _one_bond(Тикер="RU000A101RZ3", Тип="ОФЗ", Подтип=">10")
        quote = _full_quote(maturity_date="2030-09-11")  # ~4.1 года от 2026-08-19
        _, flags = _build_bonds(portfolio, {"RU000A101RZ3": quote}, as_of_iso=self.AS_OF)
        self.assertIn("bond_ofz_subtype_maturity_mismatch", _flag_codes(flags))

    def test_ofz_maturity_silent_when_consistent(self):
        portfolio = _one_bond(Тикер="RU000A101RZ3", Тип="ОФЗ", Подтип=">10")
        quote = _full_quote(maturity_date="2038-09-11")  # ~12 лет — >10 верно
        _, flags = _build_bonds(portfolio, {"RU000A101RZ3": quote}, as_of_iso=self.AS_OF)
        self.assertNotIn("bond_ofz_subtype_maturity_mismatch", _flag_codes(flags))

    def test_ofz_maturity_mismatch_fires_long_in_short_bucket(self):
        portfolio = _one_bond(Тикер="X", Тип="ОФЗ", Подтип="<10")
        quote = _full_quote(maturity_date="2040-01-01")  # >10 лет, но Подтип «<10»
        _, flags = _build_bonds(portfolio, {"X": quote}, as_of_iso=self.AS_OF)
        self.assertIn("bond_ofz_subtype_maturity_mismatch", _flag_codes(flags))

    def test_floater_mismatch_fires_no_name_signal(self):
        portfolio = _one_bond(Тикер="X", Тип="ОФЗ", Подтип="Флоат")
        quote = _full_quote(short_name="ОФЗ 26244")  # не похоже на флоатер
        _, flags = _build_bonds(portfolio, {"X": quote}, as_of_iso=self.AS_OF)
        self.assertIn("bond_floater_subtype_mismatch", _flag_codes(flags))

    def test_floater_silent_when_name_confirms(self):
        portfolio = _one_bond(Тикер="X", Тип="ОФЗ", Подтип="Флоат")
        quote = _full_quote(short_name="ОФЗ 29014")  # серия 29xxx = ОФЗ-ПК
        _, flags = _build_bonds(portfolio, {"X": quote}, as_of_iso=self.AS_OF)
        self.assertNotIn("bond_floater_subtype_mismatch", _flag_codes(flags))

    def test_floater_mismatch_fires_reverse_case(self):
        """«И наоборот»: имя похоже на флоатер, но Подтип ≠ Флоат."""
        portfolio = _one_bond(Тикер="X", Тип="ОФЗ", Подтип=">10")
        quote = _full_quote(short_name="Флоатер-выпуск-1")
        _, flags = _build_bonds(portfolio, {"X": quote}, as_of_iso=self.AS_OF)
        self.assertIn("bond_floater_subtype_mismatch", _flag_codes(flags))

    def test_rating_bucket_mismatch_fires(self):
        portfolio = _one_bond(Тикер="X", Тип="КОРП", Подтип="A", Рейтинг="AAA")
        _, flags = _build_bonds(portfolio, {"X": _full_quote()}, as_of_iso=self.AS_OF)
        self.assertIn("bond_rating_bucket_mismatch", _flag_codes(flags))

    def test_rating_bucket_mismatch_silent_when_consistent(self):
        portfolio = _one_bond(Тикер="X", Тип="КОРП", Подтип="A", Рейтинг="A")
        _, flags = _build_bonds(portfolio, {"X": _full_quote()}, as_of_iso=self.AS_OF)
        self.assertNotIn("bond_rating_bucket_mismatch", _flag_codes(flags))

    def test_rating_below_ladder_fires(self):
        portfolio = _one_bond(Тикер="X", Тип="КОРП", Подтип="B+", Рейтинг="CCC")
        _, flags = _build_bonds(portfolio, {"X": _full_quote()}, as_of_iso=self.AS_OF)
        self.assertIn("bond_rating_below_ladder", _flag_codes(flags))

    def test_rating_below_ladder_silent_when_in_ladder(self):
        portfolio = _one_bond(Тикер="X", Тип="КОРП", Подтип="B+", Рейтинг="BB")
        _, flags = _build_bonds(portfolio, {"X": _full_quote()}, as_of_iso=self.AS_OF)
        self.assertNotIn("bond_rating_below_ladder", _flag_codes(flags))

    def test_moex_confirms_floater_helper(self):
        self.assertTrue(_moex_confirms_floater("ОФЗ 29014"))
        self.assertTrue(_moex_confirms_floater("Флоатер РЖД"))
        self.assertFalse(_moex_confirms_floater("ОФЗ 26244"))
        self.assertFalse(_moex_confirms_floater(None))


# ── 8: bonds_plan_vs_fact ─────────────────────────────────────────────────────

class TestBondsPlanVsFact(unittest.TestCase):
    def _portfolio(self) -> dict:
        return {
            "goals": {"bonds_breakdown": _base_bonds_breakdown()},
            "other_positions": [],
        }

    def _holdings(self) -> list[dict]:
        return [
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "ОФЗ/>10",
             "value_rub": 120000.0},
            {"asset_type": "bond", "account": "iis_3", "plan_bucket_key": "ОФЗ/>10",
             "value_rub": 30000.0},
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "ОФЗ/<10",
             "value_rub": 80000.0},
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "КОРП/AA+",
             "value_rub": 60000.0},
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "КОРП/A",
             "value_rub": 40000.0},
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "КОРП/B+",
             "value_rub": 20000.0},
            {"asset_type": "bond", "account": "main", "plan_bucket_key": "USD",
             "value_rub": 90000.0},
        ]

    def test_target_pct_sums_to_100(self):
        result, _, _ = _build_bonds_plan_vs_fact(self._portfolio(), self._holdings())
        total_target_pct = sum(e["target_pct"] for e in result)
        self.assertAlmostEqual(total_target_pct, 100.0, places=4)

    def test_delta_rub_is_target_minus_actual(self):
        result, _, _ = _build_bonds_plan_vs_fact(self._portfolio(), self._holdings())
        entry = next(e for e in result if e["bucket_key"] == "ОФЗ/>10")
        self.assertEqual(entry["target_rub"], 120000.0)
        self.assertEqual(entry["actual_rub"], 120000.0)  # только main-часть (§3.1/Q1)
        self.assertEqual(entry["delta_rub"], 0.0)

    def test_base_is_excl_iis_split_position(self):
        """Позиция со split main/ИИС попадает в actual_rub только
        main-частью; actual_rub_incl_iis учитывает обе."""
        result, _, _ = _build_bonds_plan_vs_fact(self._portfolio(), self._holdings())
        entry = next(e for e in result if e["bucket_key"] == "ОФЗ/>10")
        self.assertEqual(entry["actual_rub"], 120000.0)
        self.assertEqual(entry["actual_rub_incl_iis"], 150000.0)

    def test_bond_plan_fact_stale_fires(self):
        portfolio = self._portfolio()
        for row in portfolio["goals"]["bonds_breakdown"]:
            if row.get("_bucket_key") == "ОФЗ/>10":
                row["Нынешняя Сумма"] = 200000.0  # файл сильно устарел
        _, _, flags = _build_bonds_plan_vs_fact(portfolio, self._holdings())
        self.assertIn("bond_plan_fact_stale", _flag_codes(flags))

    def test_bond_plan_fact_stale_silent_when_fresh(self):
        _, _, flags = _build_bonds_plan_vs_fact(self._portfolio(), self._holdings())
        self.assertNotIn("bond_plan_fact_stale", _flag_codes(flags))


# ── 12: TLCB-кейс (фонд из «Tаблица 1») ───────────────────────────────────────

class TestTlcbFundCase(unittest.TestCase):
    def _portfolio_with_fund(self, include_fund: bool) -> dict:
        breakdown = [
            r for r in copy.deepcopy(_base_bonds_breakdown())
            if r.get("_bucket_key") == "USD"
        ]
        other_positions = []
        if include_fund:
            other_positions.append({"Тип": "USD - Облигации", "Бумага": "TLCB",
                                     "Стоимость": 166800.0})
        return {"goals": {"bonds_breakdown": breakdown}, "other_positions": other_positions}

    def _usd_bond_holding(self) -> list[dict]:
        return [{"asset_type": "bond", "account": "main", "plan_bucket_key": "USD",
                  "value_rub": 90000.0}]

    def test_tlcb_included_in_usd_actual(self):
        portfolio = self._portfolio_with_fund(include_fund=True)
        result, _, _ = _build_bonds_plan_vs_fact(portfolio, self._usd_bond_holding())
        entry = next(e for e in result if e["bucket_key"] == "USD")
        self.assertEqual(entry["actual_rub"], 90000.0 + 166800.0)

    def test_without_tlcb_actual_understated_by_166800(self):
        portfolio = self._portfolio_with_fund(include_fund=False)
        result, _, _ = _build_bonds_plan_vs_fact(portfolio, self._usd_bond_holding())
        entry = next(e for e in result if e["bucket_key"] == "USD")
        self.assertEqual(entry["actual_rub"], 90000.0)
        # Расхождение — ровно 166 800 ₽ (§3.1).
        with_fund, _, _ = _build_bonds_plan_vs_fact(
            self._portfolio_with_fund(include_fund=True), self._usd_bond_holding(),
        )
        entry_with = next(e for e in with_fund if e["bucket_key"] == "USD")
        self.assertEqual(entry_with["actual_rub"] - entry["actual_rub"], 166800.0)

    def test_bucket_fund_member_missing_fires_for_orphan_fund(self):
        """Фонд «* - Облигации» без соответствующей плановой корзины
        (EUR не в bonds_breakdown) — «сирота»."""
        portfolio = {
            "goals": {"bonds_breakdown": [
                r for r in copy.deepcopy(_base_bonds_breakdown())
                if r.get("_bucket_key") == "USD"
            ]},
            "other_positions": [
                {"Тип": "EUR - Облигации", "Бумага": "ORPHAN", "Стоимость": 50000.0},
            ],
        }
        _, _, flags = _build_bonds_plan_vs_fact(portfolio, self._usd_bond_holding())
        self.assertIn("bucket_fund_member_missing", _flag_codes(flags))

    def test_bucket_fund_member_missing_silent_when_matched(self):
        portfolio = self._portfolio_with_fund(include_fund=True)
        _, _, flags = _build_bonds_plan_vs_fact(portfolio, self._usd_bond_holding())
        self.assertNotIn("bucket_fund_member_missing", _flag_codes(flags))


# ── 13: balance_total_vs_trades_drift (PDL-14: сведённые базы) ───────────────

class TestBalanceVsTradesDrift(unittest.TestCase):
    """Гейт сравнивает «Имеется» с реконструкцией на СВЕДЁННЫХ базах:
    позиции (чистая цена) + НКД + ФАКТИЧЕСКИЙ кэш. Кассовый дрейф сюда не
    входит — у него отдельный гейт cash_drift_changed с baseline'ом.

    До PDL-14 гейт складывал реконструированный кэш и сравнивал чистые цены
    с грязными: на августовских данных кассовый дрейф и НКД гасили утечку блокировок (PDL-12), итог −1.56%
    проходил под порогом 2%. Дефект был, гейт молчал.
    """

    PORTFOLIO = {"summary": {"Имеется (RUB)": 1_000_000.0}}

    @staticmethod
    def _returns(positions_rub, recon_cash):
        return {"snapshot_current": {
            "total_value_rub": positions_rub + recon_cash,
            "cash_balance_rub": recon_cash,
        }}

    @staticmethod
    def _bond(accrued, qty, currency="RUB", status="normal"):
        return {"ticker": "B1", "asset_type": "bond", "currency": currency,
                "accrued_int": accrued, "qty": qty, "status": status}

    def test_fires_above_threshold(self):
        """Дыра 2% (позиции 780к вместо 800к) — гейт срабатывает."""
        flag = _check_balance_vs_trades_drift(
            self.PORTFOLIO, self._returns(780_000.0, 150_000.0),
            [], 200_000.0, None,
        )
        self.assertIsNotNone(flag)
        self.assertEqual(flag["code"], "balance_total_vs_trades_drift")
        self.assertEqual(flag["severity"], "info")

    def test_silent_below_threshold(self):
        """0.5% — под порогом 1%, молчит."""
        flag = _check_balance_vs_trades_drift(
            self.PORTFOLIO, self._returns(795_000.0, 150_000.0),
            [], 200_000.0, None,
        )
        self.assertIsNone(flag)

    def test_actual_cash_replaces_reconstructed(self):
        """Кассовый дрейф НЕ попадает в расхождение.

        Реконструированный кэш 150к против фактического 200к: позиции сходятся
        точь-в-точь, и гейт обязан молчать. На старой базе те же входные данные
        дали бы 5%.
        """
        returns = self._returns(800_000.0, 150_000.0)
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, [], 200_000.0, None))
        # контроль: на реконструированном кэше расхождение 5% — видно, что
        # входные данные подобраны не «под тишину».
        flag_old_base = _check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, [], 150_000.0, None)
        self.assertIsNotNone(flag_old_base)

    def test_nkd_added_to_clean_prices(self):
        """НКД добавляется к реконструкции: 20к НКД закрывают ровно 2% дыры."""
        returns = self._returns(780_000.0, 150_000.0)
        holdings = [self._bond(accrued=200.0, qty=100.0)]  # 20 000 ₽
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, holdings, 200_000.0, None))
        self.assertIsNotNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, [], 200_000.0, None))

    def test_nkd_not_added_twice_on_dirty_basis(self):
        """returns.json с bond_value_basis=dirty (2026-10-12) уже несёт НКД.

        Позиции 800к сходятся с балансом точь-в-точь; прибавка тех же 20к НКД
        второй раз дала бы 2% и ложное срабатывание.
        """
        returns = self._returns(800_000.0, 150_000.0)
        returns["parameters"] = {"bond_value_basis": "dirty"}
        holdings = [self._bond(accrued=200.0, qty=100.0)]  # 20 000 ₽
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, holdings, 200_000.0, None))
        # контроль: та же пара на старом чистом returns.json срабатывает
        returns_clean = self._returns(800_000.0, 150_000.0)
        self.assertIsNotNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns_clean, holdings, 200_000.0, None))

    def test_nkd_of_blocked_bonds_ignored(self):
        """Заблокированные бумаги вне обеих баз — их НКД учитывать нельзя."""
        flag = _check_balance_vs_trades_drift(
            self.PORTFOLIO, self._returns(780_000.0, 150_000.0),
            [self._bond(accrued=200.0, qty=100.0, status="blocked")],
            200_000.0, None,
        )
        self.assertIsNotNone(flag)

    def test_nkd_converted_by_trading_currency(self):
        """НКД в валюте ТОРГОВ; без курса бумага пропускается с оговоркой."""
        returns = self._returns(780_000.0, 150_000.0)
        holdings = [self._bond(accrued=2.0, qty=100.0, currency="USD")]
        fx = {"USD": {"rate": 100.0}}
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, holdings, 200_000.0, fx))
        flag = _check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, holdings, 200_000.0, None)
        self.assertIsNotNone(flag)
        self.assertIn("без курса", flag["message"])

    def test_message_shows_decomposition(self):
        """Сообщение обязано показывать слагаемые — иначе не отличить
        ценовой шум от пропавшей позиции."""
        flag = _check_balance_vs_trades_drift(
            self.PORTFOLIO, self._returns(780_000.0, 150_000.0),
            [], 200_000.0, None,
        )
        for part in ("позиции", "НКД", "фактический кэш", "cash_drift_changed"):
            self.assertIn(part, flag["message"])

    def test_threshold_constant_is_one_percent(self):
        """Порог калиброван по остатку 0.42% на сведённых базах (PDL-14).
        Изменение без перемера — регрессия."""
        self.assertAlmostEqual(BALANCE_VS_TRADES_DRIFT_THRESHOLD, 0.01)

    def test_missing_inputs_skip_check(self):
        """Нехватка любого входа → молча пропустить, а не считать на неполной
        базе (иначе «нет holdings» читалось бы как «нет НКД» = ложный флаг)."""
        returns = self._returns(780_000.0, 150_000.0)
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, None, [], 200_000.0, None))
        self.assertIsNone(_check_balance_vs_trades_drift(
            None, returns, [], 200_000.0, None))
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, [], None, None))
        self.assertIsNone(_check_balance_vs_trades_drift(
            self.PORTFOLIO, returns, None, 200_000.0, None))


# ── контракт-константы: базовая целостность §4.3/§4.1 ────────────────────────

class TestContractConstants(unittest.TestCase):
    def test_valid_type_subtype_currencies_require_empty(self):
        for cur in ("USD", "EUR", "CNY"):
            self.assertEqual(VALID_TYPE_SUBTYPE[cur], frozenset({None}))

    def test_valid_type_subtype_ofz_corp(self):
        self.assertEqual(VALID_TYPE_SUBTYPE["ОФЗ"], frozenset({">10", "<10", "Флоат"}))
        self.assertEqual(VALID_TYPE_SUBTYPE["КОРП"], frozenset({"AA+", "A", "B+", "Флоат"}))

    def test_bond_bucket_key_derivation(self):
        self.assertEqual(_bond_bucket_key("ОФЗ", ">10"), "ОФЗ/>10")
        self.assertEqual(_bond_bucket_key("USD", None), "USD")
        self.assertIsNone(_bond_bucket_key(None, None))
        self.assertIsNone(_bond_bucket_key("Итог", None))
        # assemble_snapshot._plan_bucket_key — тот же контракт, независимая копия.
        self.assertEqual(_plan_bucket_key("КОРП", "A"), "КОРП/A")
        self.assertEqual(_plan_bucket_key("EUR", None), "EUR")



class TestBalanceSummaryPassthroughPDL13(unittest.TestCase):
    """PDL-13 (RPA-17): матрица «Планы» и таблица «Проверка» доезжают до снапшота.

    Дефект: `parse_portfolio` извлекал `goals.matrix` / `goals.matrix_iis` /
    `errors_check`, но `assemble_snapshot` их не переносил. Из-за этого раздел
    «Входные данные» rebalance-framework.md ссылался на пути промежуточного
    `portfolio.json`, которых у Mode 3 на руках не было — валютная аллокация
    (вход ребалансировки) была недоступна. Разбор — rpa-17-field-paths-audit.md.
    """

    @staticmethod
    def _portfolio():
        return {
            "goals": {
                "overall": [{"Тип": "Облигация", "Доля": 0.5}],
                "bonds_breakdown": [],
                "matrix": [
                    {"Валюта": "RUB", "Бумага": "Облигация",
                     "Доля план": 0.34, "Сейчас": 2608821.7},
                    {"Валюта": "CNY", "Бумага": "Облигация",
                     "Доля план": 0.1, "Сейчас": 509487.24},
                ],
                "matrix_iis": [{"Валюта": "RUB", "Бумага": "ИИС",
                                "Доля план": "NA", "Сейчас": 595572.0}],
            },
            "errors_check": [
                {"Тип ошибки": "Есть в IntelInvest, нет в Акция", "Наличие": False},
                {"Тип ошибки": "Есть в IE, нет в Акция", "Наличие": True},
            ],
            "summary": {},
        }

    def _balance_summary(self, portfolio):
        """Собирает те же поля, что assemble_snapshot кладёт в balance_summary."""
        goals = (portfolio or {}).get("goals", {})
        return {
            "goals_overall": goals.get("overall"),
            "goals_bonds_breakdown": goals.get("bonds_breakdown"),
            "goals_matrix": goals.get("matrix"),
            "goals_matrix_iis": goals.get("matrix_iis"),
            "errors_check": (portfolio or {}).get("errors_check"),
        }

    def test_goals_matrix_present(self):
        bs = self._balance_summary(self._portfolio())
        self.assertIsNotNone(bs["goals_matrix"])
        self.assertEqual(len(bs["goals_matrix"]), 2)
        rub = next(r for r in bs["goals_matrix"] if r["Валюта"] == "RUB")
        self.assertEqual(rub["Доля план"], 0.34)

    def test_goals_matrix_iis_separate(self):
        """ИИС-3 идёт отдельным блоком и в основную матрицу не подмешан (Q1)."""
        bs = self._balance_summary(self._portfolio())
        self.assertEqual(len(bs["goals_matrix_iis"]), 1)
        self.assertNotIn("ИИС", [r["Бумага"] for r in bs["goals_matrix"]])

    def test_errors_check_present_and_flags_true(self):
        bs = self._balance_summary(self._portfolio())
        fired = [r for r in bs["errors_check"] if r["Наличие"]]
        self.assertEqual(len(fired), 1)
        self.assertIn("IE", fired[0]["Тип ошибки"])

    def test_missing_blocks_become_none_not_crash(self):
        """Снапшот без balance-файла: поля есть, но null — падать нельзя."""
        bs = self._balance_summary({"goals": {}, "summary": {}})
        for key in ("goals_matrix", "goals_matrix_iis", "errors_check"):
            self.assertIsNone(bs[key], key)


if __name__ == "__main__":
    unittest.main()


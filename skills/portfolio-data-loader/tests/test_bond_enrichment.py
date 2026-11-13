#!/usr/bin/env python3
"""Тесты обогащения облигаций bond-полями MOEX ISS в assemble_snapshot.py (I-1).

Проверяют, что _build_bonds переносит в holding полный набор bond-полей из
quote (купон, частота купона, номинал, НКД, дата след. купона, YTM, дюрация,
оферта, погашение) и gracefully ставит null при их отсутствии.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "_shared-references"))  # канон moex_quotes
from scripts.assemble_snapshot import _build_bonds, _coupon_freq
from moex_quotes import _normalize, YIELD_TO_OFFER_SANITY_PCT


def _full_quote():
    """Имитация q.to_dict() из moex_quotes.py, weekly-профиль, облигация."""
    return {
        "secid": "SU26243RMFS4",
        "kind": "bond",
        "isin": "RU000A106E90",
        "currency": "SUR",
        "last": 78.5,
        "ytm_pct": 14.82,
        "duration_days": 3200,
        "coupon_pct": 9.8,
        "coupon_period_days": 182,
        "next_coupon_date": "2026-07-15",
        "accrued_interest": 12.34,
        "face_value": 1000.0,
        "maturity_date": "2043-05-19",
        "offer_date": None,
        "timestamp": "2026-06-09T18:00:00",
    }


def _portfolio_one_bond(ticker="SU26243RMFS4"):
    return {"bonds": [{
        "Тикер": ticker,
        "Название": "ОФЗ 26243",
        "Текущая стоимость": 78500.0,
        "Всего": 100,
        "ИИС": 0,
        "Итого без ИИСа": 78500.0,
        "Итого на ИИС": 0,
    }]}


class TestBondEnrichment(unittest.TestCase):
    def test_full_quote_populates_all_fields(self):
        bonds, _ = _build_bonds(
            _portfolio_one_bond(), {"SU26243RMFS4": _full_quote()}
        )
        self.assertEqual(len(bonds), 1)
        b = bonds[0]
        self.assertEqual(b["ytm_pct"], 14.82)
        self.assertEqual(b["ytm_source"], "moex_iss")
        self.assertEqual(b["coupon_pct"], 9.8)
        self.assertEqual(b["coupon_freq_per_year"], 2)   # 365/182 → 2
        self.assertEqual(b["next_coupon_date"], "2026-07-15")
        self.assertEqual(b["accrued_int"], 12.34)
        self.assertEqual(b["nominal"], 1000.0)
        self.assertEqual(b["nominal_currency"], "SUR")
        self.assertEqual(b["duration_days"], 3200)
        self.assertEqual(b["maturity_date"], "2043-05-19")

    def test_missing_quote_graceful_nulls(self):
        # Нет quote вообще → bond-поля null, скрипт не падает, цена last_trade.
        bonds, _ = _build_bonds(_portfolio_one_bond(), {})
        self.assertEqual(len(bonds), 1)
        b = bonds[0]
        self.assertIsNone(b["coupon_pct"])
        self.assertIsNone(b["coupon_freq_per_year"])
        self.assertIsNone(b["accrued_int"])
        self.assertIsNone(b["ytm_pct"])
        self.assertIsNone(b["ytm_source"])
        self.assertEqual(b["current_price_source"], "last_trade")

    def test_prev_close_when_no_trades_today(self):
        # 2026-10-21, прогон в 08:13 МСК: у 11 облигаций TQCB нет last до открытия торгов —
        # раньше уходили в implied из баланса. Теперь prev_close, источник moex_iss.
        q = _full_quote()
        q.pop("last")
        q["prev_close"] = 78.1
        b = _build_bonds(_portfolio_one_bond(), {"SU26243RMFS4": q})[0][0]
        self.assertEqual(b["current_price"], 78.1)
        self.assertEqual(b["current_price_source"], "moex_iss")
        self.assertEqual(b["current_price_basis"], "prev_close")
        b = _build_bonds(_portfolio_one_bond(), {"SU26243RMFS4": _full_quote()})[0][0]
        self.assertEqual(b["current_price_basis"], "last")

    def test_partial_quote_no_coupon_period(self):
        q = _full_quote()
        q.pop("coupon_period_days")  # MOEX не вернул период
        bonds, _ = _build_bonds(_portfolio_one_bond(), {"SU26243RMFS4": q})
        b = bonds[0]
        self.assertEqual(b["coupon_pct"], 9.8)          # купон есть
        self.assertIsNone(b["coupon_freq_per_year"])    # частоту не угадываем

    def test_nominal_fallback_to_balance(self):
        q = _full_quote()
        q.pop("face_value")
        pf = _portfolio_one_bond()
        pf["bonds"][0]["Номинал"] = 1000.0
        bonds, _ = _build_bonds(pf, {"SU26243RMFS4": q})
        self.assertEqual(bonds[0]["nominal"], 1000.0)

    def test_fx_replacement_bond_currency(self):
        q = _full_quote()
        q["currency"] = "USD"
        pf = _portfolio_one_bond("RU000A105JH9")
        pf["bonds"][0]["Валюта номинала"] = "USD"
        bonds, _ = _build_bonds(pf, {"RU000A105JH9": q})
        self.assertEqual(bonds[0]["nominal_currency"], "USD")

    def test_iis_split_carries_bond_fields(self):
        # Облигация на двух счетах — оба holding должны нести bond-поля.
        pf = {"bonds": [{
            "Тикер": "SU26243RMFS4", "Название": "ОФЗ 26243",
            "Текущая стоимость": 128931.6, "Всего": 210, "ИИС": 130,
            "Итого без ИИСа": 49116.8, "Итого на ИИС": 79814.8,
        }]}
        bonds, _ = _build_bonds(pf, {"SU26243RMFS4": _full_quote()})
        self.assertEqual(len(bonds), 2)
        for b in bonds:
            self.assertEqual(b["coupon_pct"], 9.8)
            self.assertEqual(b["coupon_freq_per_year"], 2)
        self.assertEqual({b["account"] for b in bonds}, {"main", "iis_3"})

    def test_snapshot_carries_ytm_to_offer(self):
        # ytm_to_offer_pct из quote должен проброситься в holding (Баг #1B).
        q = _full_quote()
        q["ytm_to_offer_pct"] = 414.11
        q["offer_date"] = "2026-06-15"
        bonds, _ = _build_bonds(_portfolio_one_bond(), {"SU26243RMFS4": q})
        self.assertEqual(bonds[0]["ytm_to_offer_pct"], 414.11)
        self.assertEqual(bonds[0]["offer_date"], "2026-06-15")


def _bond_md_sec(yield_pct=None, yield_to_offer=None, offer_date=None, coupon=18.0):
    """Минимальные md/sec для _normalize (market='bonds')."""
    md = {"LAST": 97.63, "YIELD": yield_pct, "YIELDTOOFFER": yield_to_offer,
          "DURATION": 6}
    sec = {"SHORTNAME": "ПР-Лиз 2P2", "ISIN": "RU000A106EP1",
           "COUPONPERCENT": coupon, "MATDATE": "2032-05-06",
           "OFFERDATE": offer_date, "FACEVALUE": 1000.0}
    return md, sec


class TestYieldToOfferSeparation(unittest.TestCase):
    """Баг #1B: MOEX YIELD для бумаги с офертой = yield-to-offer, не YTM-к-погашению."""

    def test_offer_extreme_yield_routed_to_ytm_to_offer(self):
        # Оферта + неправдоподобный YIELD (414%) → ytm_pct=None, ytm_to_offer_pct=414.
        md, sec = _bond_md_sec(yield_pct=414.11, offer_date="2026-06-15")
        q = _normalize("RU000A106EP1", "bonds", sec, md, "weekly")
        self.assertIsNone(q.ytm_pct)
        self.assertAlmostEqual(q.ytm_to_offer_pct, 414.11)
        self.assertEqual(q.offer_date, "2026-06-15")

    def test_offer_sane_yield_kept_as_ytm(self):
        # Оферта, но YIELD правдоподобен (18%) → остаётся в ytm_pct.
        md, sec = _bond_md_sec(yield_pct=18.0, offer_date="2028-06-15")
        q = _normalize("X", "bonds", sec, md, "weekly")
        self.assertAlmostEqual(q.ytm_pct, 18.0)

    def test_no_offer_high_yield_kept(self):
        # Без оферты высокий YIELD не реклассифицируется (gate на offer_date).
        md, sec = _bond_md_sec(yield_pct=120.0, offer_date=None)
        q = _normalize("X", "bonds", sec, md, "weekly")
        self.assertAlmostEqual(q.ytm_pct, 120.0)
        self.assertIsNone(q.ytm_to_offer_pct)

    def test_explicit_yieldtooffer_preserved(self):
        # Если MOEX отдал YIELDTOOFFER явно — он сохраняется, ytm_pct=None.
        md, sec = _bond_md_sec(yield_pct=414.11, yield_to_offer=410.0,
                               offer_date="2026-06-15")
        q = _normalize("X", "bonds", sec, md, "weekly")
        self.assertIsNone(q.ytm_pct)
        self.assertAlmostEqual(q.ytm_to_offer_pct, 410.0)

    def test_threshold_boundary(self):
        # На пороге (== sanity) не реклассифицируем (строго >).
        md, sec = _bond_md_sec(yield_pct=YIELD_TO_OFFER_SANITY_PCT, offer_date="2026-06-15")
        q = _normalize("X", "bonds", sec, md, "weekly")
        self.assertAlmostEqual(q.ytm_pct, YIELD_TO_OFFER_SANITY_PCT)


class TestCouponFreq(unittest.TestCase):
    def test_semiannual(self):
        self.assertEqual(_coupon_freq(182), 2)
        self.assertEqual(_coupon_freq(181), 2)

    def test_quarterly(self):
        self.assertEqual(_coupon_freq(91), 4)

    def test_annual(self):
        self.assertEqual(_coupon_freq(365), 1)

    def test_monthly(self):
        self.assertEqual(_coupon_freq(30), 12)
        self.assertEqual(_coupon_freq(31), 12)

    def test_none_and_zero(self):
        self.assertIsNone(_coupon_freq(None))
        self.assertIsNone(_coupon_freq(0))
        self.assertIsNone(_coupon_freq(""))


class TestRedeemedBondGuard(unittest.TestCase):
    """PDL-H: погашенный/делистингованный выпуск не проходит в снапшот тихо.

    Кейс РУСАЛ 1Р6 (RU000A107RH8), погашен 05.08.2026: MOEX перестал отдавать
    weekly-поля, позиция в выгрузке ещё висела — снапшот 08-06 пронёс её как
    живую облигацию на 359 тыс. ₽, поймал только внешний чек integrated-view.
    """

    def test_value_without_maturity_and_moex_flags(self):
        pf = {"bonds": [{
            "Тикер": "RU000A107RH8", "Название": "РУСАЛ 1Р6",
            "Текущая стоимость": 359232.74, "Всего": 30, "ИИС": 0,
            "Итого без ИИСа": 359232.74, "Итого на ИИС": 0,
        }]}
        _, flags = _build_bonds(pf, {}, as_of_iso="2026-08-06")
        codes = [f["code"] for f in flags]
        self.assertIn("bond_possibly_redeemed", codes)
        msg = next(f["message"] for f in flags
                   if f["code"] == "bond_possibly_redeemed")
        self.assertIn("RU000A107RH8", msg)
        self.assertEqual(
            "warn",
            next(f["severity"] for f in flags
                 if f["code"] == "bond_possibly_redeemed"))

    def test_past_maturity_with_value_flags(self):
        pf = _portfolio_one_bond()
        pf["bonds"][0]["Дата погашения"] = "2026-08-01"
        _, flags = _build_bonds(pf, {}, as_of_iso="2026-08-06")
        codes = [f["code"] for f in flags]
        self.assertIn("bond_matured_but_valued", codes)
        self.assertNotIn("bond_possibly_redeemed", codes)

    def test_live_bond_with_quote_silent(self):
        _, flags = _build_bonds(_portfolio_one_bond(),
                                {"SU26243RMFS4": _full_quote()},
                                as_of_iso="2026-08-06")
        codes = [f["code"] for f in flags]
        self.assertNotIn("bond_possibly_redeemed", codes)
        self.assertNotIn("bond_matured_but_valued", codes)

    def test_future_maturity_from_vygruzka_silent(self):
        """Дата погашения из выгрузки в будущем при пустых котировках —
        не повод кричать (замещайки без MOEX-профиля живут так постоянно)."""
        pf = _portfolio_one_bond()
        pf["bonds"][0]["Дата погашения"] = "2027-05-19"
        _, flags = _build_bonds(pf, {}, as_of_iso="2026-08-06")
        codes = [f["code"] for f in flags]
        self.assertNotIn("bond_possibly_redeemed", codes)
        self.assertNotIn("bond_matured_but_valued", codes)

    def test_no_as_of_no_matured_flag(self):
        pf = _portfolio_one_bond()
        pf["bonds"][0]["Дата погашения"] = "2020-01-01"
        _, flags = _build_bonds(pf, {})
        self.assertNotIn("bond_matured_but_valued",
                         [f["code"] for f in flags])


if __name__ == "__main__":
    unittest.main(verbosity=2)

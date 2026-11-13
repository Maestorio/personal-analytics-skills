#!/usr/bin/env python3
"""Тесты implied-цены облигаций, fx_rates_used и bond_cashflow_calendar
в assemble_snapshot.py + current_fx_rates в portfolio_returns.py (стадия 2
total-return, 2026-07).

Формула implied-цены верифицирована на реальном portfolio-2026-07-02:
value_rub/qty = price/100 × nominal × fx + НКД(RUB); НКД в снапшоте всегда
в рублях за бумагу (для замещаек — валюта расчётов MOEX).
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.assemble_snapshot import (  # noqa: E402
    _build_bond_cashflow,
    _build_bonds,
    _fx_rate_of,
    _implied_bond_price,
)
from scripts.portfolio_returns import current_fx_rates  # noqa: E402

FX_RATES = {
    "USD": {"rate": 78.27, "rate_date": "2026-07-02", "source": "cbr"},
    "CNY": {"rate": 10.9, "rate_date": "2026-07-02", "source": "cbr"},
    "EUR": None,  # сбой по валюте — потребитель обязан флагом отметить
}


class TestImpliedPrice(unittest.TestCase):
    def test_real_data_case_gazkz(self):
        """ГазКЗ-27Д2 (реальные числа снапшота 2026-07-02): implied ≈ 97.0."""
        # value_rub/qty = 607575.25/8 = 75946.9; НКД(RUB) 25.83; nominal 1000 USD
        price, dirty = _implied_bond_price(607575.25, 8, 1000.0, 25.827516, 78.27)
        self.assertIsNotNone(price)
        self.assertFalse(dirty)
        self.assertAlmostEqual(price, 97.0, delta=0.15)

    def test_rub_bond_clean(self):
        """RUB-бумага: value = qty×(price/100×nominal + НКД) → точный round-trip."""
        qty, nominal, true_price, nkd = 50, 500.0, 98.8, 6.0
        value = qty * (true_price / 100 * nominal + nkd)
        price, dirty = _implied_bond_price(value, qty, nominal, nkd, 1.0)
        self.assertFalse(dirty)
        self.assertAlmostEqual(price, true_price, delta=0.01)

    def test_dirty_when_accrued_unknown(self):
        """НКД неизвестен → цена «грязная», dirty=True (завышение ≤ coupon/freq)."""
        price, dirty = _implied_bond_price(100000.0, 100, 1000.0, None, 1.0)
        self.assertTrue(dirty)
        self.assertAlmostEqual(price, 100.0, delta=0.01)

    def test_none_on_missing_inputs(self):
        for args in [(None, 8, 1000.0, 0, 78.0), (1000.0, None, 1000.0, 0, 78.0),
                     (1000.0, 8, None, 0, 78.0), (1000.0, 8, 1000.0, 0, None)]:
            price, _ = _implied_bond_price(*args)
            self.assertIsNone(price)

    def test_fx_rate_of(self):
        self.assertEqual(_fx_rate_of(FX_RATES, "SUR"), 1.0)
        self.assertEqual(_fx_rate_of(FX_RATES, "RUB"), 1.0)
        self.assertEqual(_fx_rate_of(FX_RATES, None), 1.0)
        self.assertEqual(_fx_rate_of(FX_RATES, "USD"), 78.27)
        self.assertIsNone(_fx_rate_of(FX_RATES, "EUR"))   # сбой по валюте
        self.assertIsNone(_fx_rate_of(None, "USD"))


class TestBuildBondsImplied(unittest.TestCase):
    def _portfolio(self, ticker="RU000A105KU0", cur="USD"):
        return {"bonds": [{
            "Тикер": ticker,
            "Название": "Тест-замещайка",
            "Валюта номинала": cur,
            "Номинал": 1000.0,
            "Текущая стоимость": 636913.0,   # 9 × (price×10×fx + НКД)
            "Всего": 9, "ИИС": 0,
            "Итого без ИИСа": 636913.0, "Итого на ИИС": 0,
        }]}

    def test_implied_fill_when_no_quote(self):
        """Нет котировки MOEX + есть курс → current_price = implied_from_value."""
        holdings, flags = _build_bonds(self._portfolio(), {}, FX_RATES)
        h = holdings[0]
        self.assertIsNotNone(h["current_price"])
        self.assertEqual(h["current_price_source"], "implied_from_value")
        # НКД неизвестен (quote нет) → dirty
        self.assertTrue(h.get("current_price_implied_dirty"))
        # 636913 / (9 × 1000 × 78.27) × 100 ≈ 90.41 (dirty)
        self.assertAlmostEqual(h["current_price"], 90.41, delta=0.05)
        self.assertTrue(any(f["code"] == "implied_bond_price" for f in flags))

    def test_no_fx_no_implied(self):
        """FX-бумага без курса (EUR: None) → цена null + warn-флаг."""
        holdings, flags = _build_bonds(self._portfolio(cur="EUR"), {}, FX_RATES)
        self.assertIsNone(holdings[0]["current_price"])
        self.assertTrue(any(f["code"] == "no_fx_for_implied_price" for f in flags))

    def test_quote_price_untouched(self):
        """Есть котировка MOEX → implied не вмешивается."""
        quotes = {"RU000A105KU0": {"last": 97.5, "currency": "USD",
                                   "face_value": 1000.0}}
        holdings, _ = _build_bonds(self._portfolio(), quotes, FX_RATES)
        self.assertEqual(holdings[0]["current_price"], 97.5)
        self.assertEqual(holdings[0]["current_price_source"], "moex_iss")

    def test_backward_compat_no_fx_arg(self):
        """Старый вызов _build_bonds(portfolio, quotes) работает (fx_rates=None)."""
        holdings, _ = _build_bonds(self._portfolio(cur="SUR"), {})
        # SUR: fx=1 и без fx_rates → implied считается
        self.assertEqual(holdings[0]["current_price_source"], "implied_from_value")


def _bond_holding(**kw):
    base = {
        "ticker": "RUBOND", "name": "Тест", "asset_type": "bond",
        "is_blocked": False, "account": "main", "qty": 10, "value_rub": 10000.0,
        "nominal": 1000.0, "nominal_currency": "SUR", "coupon_pct": 12.0,
        "coupon_freq_per_year": 2, "next_coupon_date": "2026-10-01",
        "maturity_date": "2029-04-01", "offer_date": None,
    }
    base.update(kw)
    return base


class TestBondCashflow(unittest.TestCase):
    AS_OF = "2026-07-02"

    def test_rub_coupons_and_amounts(self):
        """RUB-бумага: купоны 2026-10-01 и 2027-04-01 в 12-мес окне,
        сумма = qty × nominal × coupon/freq."""
        cal = _build_bond_cashflow([_bond_holding()], FX_RATES, self.AS_OF)
        coupons = [e for e in cal["detail"] if e["kind"] == "coupon"]
        self.assertEqual([e["date"] for e in coupons], ["2026-10-01", "2027-04-01"])
        # 10 × 1000 × 12%/2 = 600 ₽ за купон
        self.assertTrue(all(e["amount_rub"] == 600.0 for e in coupons))
        self.assertIsNone(coupons[0]["fx_rate_used"])   # RUB — курс не применялся
        self.assertEqual(cal["totals"]["coupons_rub"], 1200.0)
        self.assertEqual(cal["totals"]["redemptions_rub"], 0.0)
        self.assertEqual(cal["by_month"]["2026-10"]["coupons_rub"], 600.0)

    def test_redemption_within_window(self):
        """Погашение внутри окна: redemption по номиналу, купоны обрезаны maturity."""
        h = _bond_holding(maturity_date="2027-04-01")
        cal = _build_bond_cashflow([h], FX_RATES, self.AS_OF)
        red = [e for e in cal["detail"] if e["kind"] == "redemption"]
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0]["date"], "2027-04-01")
        self.assertEqual(red[0]["amount_rub"], 10 * 1000.0)
        # финальный купон на дату погашения включён
        self.assertEqual(cal["totals"]["coupons_rub"], 1200.0)
        self.assertEqual(cal["by_month"]["2027-04"]["redemptions_rub"], 10000.0)

    def test_offer_separate_from_redemption(self):
        """Оферта — отдельный kind=offer с флагом optional_put, не redemption."""
        h = _bond_holding(offer_date="2026-12-15")
        cal = _build_bond_cashflow([h], FX_RATES, self.AS_OF)
        offers = [e for e in cal["detail"] if e["kind"] == "offer"]
        self.assertEqual(len(offers), 1)
        self.assertIn("optional_put", offers[0]["flags"])
        self.assertEqual(cal["totals"]["offers_rub"], 10000.0)
        self.assertEqual(cal["totals"]["redemptions_rub"], 0.0)
        self.assertTrue(any("потенциальный" in n for n in cal["notes"]))

    def test_fx_bond_uses_cbr_rate(self):
        """USD-бумага: суммы × курс ЦБ, fx_rate_used заполнен."""
        h = _bond_holding(ticker="USDB", nominal_currency="USD", coupon_pct=3.0,
                          next_coupon_date="2026-12-29", maturity_date="2027-06-29")
        cal = _build_bond_cashflow([h], FX_RATES, self.AS_OF)
        coupons = [e for e in cal["detail"] if e["kind"] == "coupon"]
        # 10 × 1000 × 3%/2 × 78.27 = 11740.5
        self.assertEqual(len(coupons), 2)
        self.assertAlmostEqual(coupons[0]["amount_rub"], 11740.5, delta=0.01)
        self.assertEqual(coupons[0]["fx_rate_used"], 78.27)
        red = [e for e in cal["detail"] if e["kind"] == "redemption"]
        self.assertAlmostEqual(red[0]["amount_rub"], 782700.0, delta=0.01)

    def test_missing_fx_flagged_not_silent(self):
        """EUR без курса → потоки не посчитаны, но это ФЛАГ, не тихий ноль."""
        h = _bond_holding(ticker="EURB", nominal_currency="EUR")
        cal = _build_bond_cashflow([h], FX_RATES, self.AS_OF)
        self.assertEqual(cal["detail"], [])
        self.assertTrue(any("EURB" in f and "курса" in f for f in cal["flags"]))

    def test_qty_aggregated_main_plus_iis(self):
        """main + iis_3 одного тикера: qty суммируется."""
        rows = [_bond_holding(qty=6, account="main"),
                _bond_holding(qty=4, account="iis_3")]
        cal = _build_bond_cashflow(rows, FX_RATES, self.AS_OF)
        coupons = [e for e in cal["detail"] if e["kind"] == "coupon"]
        self.assertEqual(coupons[0]["amount_rub"], 600.0)  # 10 × 1000 × 6%

    def test_blocked_and_unknown_schedule(self):
        """Blocked пропускается; нет next_coupon_date → schedule_estimated;
        нет частоты → флаг, купоны не выдуманы."""
        blocked = _bond_holding(ticker="BLK", is_blocked=True)
        nosched = _bond_holding(ticker="NOSCHED", next_coupon_date=None)
        nofreq = _bond_holding(ticker="NOFREQ", coupon_freq_per_year=None)
        cal = _build_bond_cashflow([blocked, nosched, nofreq], FX_RATES, self.AS_OF)
        self.assertFalse(any(e["ticker"] == "BLK" for e in cal["detail"]))
        ns = [e for e in cal["detail"] if e["ticker"] == "NOSCHED"]
        self.assertTrue(ns and all("schedule_estimated" in e["flags"] for e in ns))
        self.assertFalse(any(e["ticker"] == "NOFREQ" for e in cal["detail"]))
        self.assertTrue(any("NOFREQ" in f and "частота" in f for f in cal["flags"]))

    def test_24m_window_slicing(self):
        """Окно 24 мес (боевой default assemble): купоны на весь горизонт,
        by_month режется потребителем (viewer) по выбранному горизонту."""
        cal = _build_bond_cashflow([_bond_holding()], FX_RATES, self.AS_OF, months=24)
        self.assertEqual(cal["horizon_months"], 24)
        dates = [e["date"] for e in cal["detail"] if e["kind"] == "coupon"]
        self.assertEqual(dates, ["2026-10-01", "2027-04-01", "2027-10-01", "2028-04-01"])
        # срез «первые 12 мес» по ключам месяцев == прежнему 12-мес окну
        upto = [m for m in cal["by_month"] if m <= "2027-07"]
        c12 = sum(cal["by_month"][m]["coupons_rub"] for m in upto)
        self.assertEqual(c12, 1200.0)

    def test_past_next_coupon_advanced(self):
        """next_coupon_date в прошлом (устаревший снапшот) → расписание
        догоняется вперёд, прошлые купоны не попадают."""
        h = _bond_holding(next_coupon_date="2026-04-01")
        cal = _build_bond_cashflow([h], FX_RATES, self.AS_OF)
        dates = [e["date"] for e in cal["detail"] if e["kind"] == "coupon"]
        self.assertTrue(all(d > self.AS_OF for d in dates))
        self.assertEqual(dates, ["2026-10-01", "2027-04-01"])


class TestClassifyInstrumentType(unittest.TestCase):
    """Регрессия боевого кейса 2026-07-02: линкер SU52004RMFS7 без полученных
    купонов классифицировался как stock (узкий признак `SU26`) и попадал
    в акционный обзор. Госбумага — любая серия ОФЗ SU#####RMFS#."""

    @staticmethod
    def _trades(ticker, *ops):
        from types import SimpleNamespace
        return [SimpleNamespace(ticker=ticker, operation=op) for op in (ops or ("Покупка",))]

    def test_ofz_all_series_are_bonds(self):
        from scripts.portfolio_returns import classify_instrument_type as cls
        for t in ("SU52004RMFS7",   # ИН-линкер (боевой кейс)
                  "SU26243RMFS4",   # ПД
                  "SU29014RMFS6",   # ПК-флоатер
                  "SU46020RMFS2"):  # амортизационная
            self.assertEqual(cls(self._trades(t)), "bond", t)

    def test_non_ofz_unaffected(self):
        from scripts.portfolio_returns import classify_instrument_type as cls
        self.assertEqual(cls(self._trades("SBER")), "stock")
        self.assertEqual(cls(self._trades("SBER", "Дивиденд")), "stock")
        self.assertEqual(cls(self._trades("RU000A105JH9")), "bond")
        self.assertEqual(cls(self._trades("SUPER")), "stock")   # SU-префикс ≠ ОФЗ
        self.assertEqual(cls(self._trades("TGLD")), "fund")


class TestCurrentFxRates(unittest.TestCase):
    def test_offline_with_injected_cache(self):
        cache = {
            "USD": {"2026-07-02": 78.27, "2026-06-30": 78.10},
            "CNY": {"2026-06-28": 10.9},   # ближайший назад (выходные)
            "EUR": {},                      # пусто → None
        }
        out = current_fx_rates(dt.date(2026, 7, 2), cache=cache, cbr_offline=True,
                               currencies=["USD", "CNY", "EUR"])
        self.assertEqual(out["USD"], {"rate": 78.27, "rate_date": "2026-07-02",
                                      "source": "cbr"})
        self.assertEqual(out["CNY"]["rate"], 10.9)
        self.assertEqual(out["CNY"]["rate_date"], "2026-06-28")
        self.assertIsNone(out["EUR"])

    def test_forward_fallback(self):
        """Курса назад нет — берётся ближайший вперёд (границы bundled-кэша)."""
        cache = {"USD": {"2026-07-05": 79.0}, "CNY": {}, "EUR": {}}
        out = current_fx_rates(dt.date(2026, 7, 2), cache=cache, cbr_offline=True, currencies=["USD"])
        self.assertEqual(out["USD"]["rate_date"], "2026-07-05")


if __name__ == "__main__":
    unittest.main(verbosity=2)

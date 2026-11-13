#!/usr/bin/env python3
"""Сплиты, «Корректировки» и реконструкция позиций.

Зачем: reconstruct_positions / split_factor / merge_cross_currency_positions /
apply_corrections / last_known_trade_price определяют qty и себестоимость каждой позиции,
а от них зависят XIRR и оценка портфеля. Правило: количество каждой сделки приводится к
постсплитовым единицам на as_of (split_factor) до расчёта себестоимости, поэтому продажа
после сплита списывает себестоимость по средней в тех же единицах, а сплиты подряд
перемножаются (PDL-18, PDL-19).

Сеть не нужна. Реестр сплитов для синтетики подменяется через mock.patch.object(pr, "KNOWN_SPLITS").
"""

import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts import portfolio_returns as pr

D = dt.date
SPLIT_DATE = D(2025, 6, 1)
REG = {"XSPL": [{"date": SPLIT_DATE, "ratio": 10.0}]}


def T(op, qty, price, date, ticker="XSPL", cur="RUB", name="Сплит-тест", amount=None):
    amt = amount if amount is not None else qty * price * (-1 if op == "Продажа" else 1)
    t = pr.Trade(ticker=ticker, name=name, operation=op, date=date, qty=qty, price=price,
                 nominal=None, nkd=None, commission=0.0, amount=amt, amount_no_comm=amt,
                 currency=cur, note="")
    t.rub_amount = amt
    return t


def recon(trades, as_of, registry=REG):
    with mock.patch.object(pr, "KNOWN_SPLITS", registry):
        return pr.reconstruct_positions(trades, as_of)


BUY = lambda: T("Покупка", 10, 3000, D(2025, 1, 10))  # noqa: E731


class TestSplits(unittest.TestCase):
    def test_after_split(self):
        p = recon([BUY()], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 100)
        self.assertAlmostEqual(p.total_cost_rub, 30000)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_before_split(self):
        p = recon([BUY()], D(2025, 5, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 10)
        self.assertAlmostEqual(p.avg_cost_rub, 3000)

    def test_as_of_equals_split_date(self):
        p = recon([BUY()], SPLIT_DATE)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 100)

    def test_buy_after_split_added_as_is(self):
        tr = [BUY(), T("Покупка", 5, 300, D(2025, 6, 10))]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 105)
        self.assertAlmostEqual(p.total_cost_rub, 31500)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_sell_before_split(self):
        tr = [BUY(), T("Продажа", 4, 3100, D(2025, 2, 10))]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 60)
        self.assertAlmostEqual(p.total_cost_rub, 18000)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_all_sold_before_split_not_multiplied(self):
        tr = [BUY(), T("Продажа", 10, 3100, D(2025, 2, 10)), T("Покупка", 7, 300, D(2025, 6, 10))]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 7)
        self.assertAlmostEqual(p.total_cost_rub, 2100)

    def test_buy_on_split_day_not_multiplied(self):
        p = recon([T("Покупка", 10, 300, SPLIT_DATE)], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 10)

    def test_homonym_usd_untouched(self):
        tr = [BUY(), T("Покупка", 10, 50, D(2025, 1, 11), cur="USD", name="AT&T Inc")]
        pos = recon(tr, D(2025, 7, 1))
        self.assertAlmostEqual(pos[("XSPL", "USD")].qty, 10)
        self.assertAlmostEqual(pos[("XSPL", "RUB")].qty, 100)

    def test_correction_before_split_positive_multiplied(self):
        tr = [BUY(), T("Корректировка", 2, 0, D(2025, 2, 1), amount=6000)]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 120)
        self.assertAlmostEqual(p.total_cost_rub, 36000)

    def test_correction_before_split_negative_subtracted(self):
        tr = [BUY(), T("Корректировка", 2, 0, D(2025, 2, 1), amount=-6000)]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 80)
        self.assertAlmostEqual(p.total_cost_rub, 24000)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_sell_after_split_quantity_is_right(self):
        # Количество при продаже после сплита верное (себестоимость — тесты PDL-18 ниже).
        p5 = recon([BUY(), T("Продажа", 5, 310, D(2025, 6, 10))], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p5.qty, 95)
        p30 = recon([BUY(), T("Продажа", 30, 310, D(2025, 6, 10))], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p30.qty, 70)

    def test_pdl18_cost_after_sell_post_split_5(self):
        """PDL-18: покупка 10×3000 до сплита ×10, продажа 5 после → cost 28500, avg 300
        (средняя 300 в постсплитовых единицах × 95 оставшихся)."""
        p = recon([BUY(), T("Продажа", 5, 310, D(2025, 6, 10))], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.total_cost_rub, 28500)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_pdl18_cost_after_sell_post_split_30(self):
        """PDL-18: продажа 30 после сплита → qty 70, cost 21000, avg 300."""
        p = recon([BUY(), T("Продажа", 30, 310, D(2025, 6, 10))], D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 70)
        self.assertAlmostEqual(p.total_cost_rub, 21000)
        self.assertAlmostEqual(p.avg_cost_rub, 300)

    def test_pdl19_two_consecutive_splits(self):
        """PDL-19: два сплита подряд (×10, затем ×2): 1 бумага до обоих → qty 20."""
        reg = {"XSPL": [{"date": D(2025, 6, 1), "ratio": 10.0}, {"date": D(2025, 9, 1), "ratio": 2.0}]}
        p = recon([T("Покупка", 1, 3000, D(2025, 1, 10))], D(2025, 10, 1), reg)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 20)


class TestSplitFactor(unittest.TestCase):
    def f(self, trade_date, as_of, ticker="XSPL", cur="RUB", reg=REG):
        return pr.split_factor(ticker, cur, trade_date, as_of, reg)

    def test_before_split(self):
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 7, 1)), 10.0)

    def test_trade_on_split_day_is_post_split(self):
        self.assertEqual(self.f(SPLIT_DATE, D(2025, 7, 1)), 1.0)

    def test_trade_after_split(self):
        self.assertEqual(self.f(D(2025, 6, 2), D(2025, 7, 1)), 1.0)

    def test_as_of_before_split(self):
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 5, 1)), 1.0)

    def test_as_of_equals_split_day(self):
        self.assertEqual(self.f(D(2025, 1, 1), SPLIT_DATE), 10.0)

    def test_usd_is_one(self):
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 7, 1), cur="USD"), 1.0)

    def test_unknown_ticker_is_one(self):
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 7, 1), ticker="NOPE"), 1.0)

    def test_two_splits_product_and_partial(self):
        reg = {"XSPL": [{"date": D(2025, 6, 1), "ratio": 10.0}, {"date": D(2025, 9, 1), "ratio": 2.0}]}
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 10, 1), reg=reg), 20.0)
        self.assertEqual(self.f(D(2025, 1, 1), D(2025, 7, 1), reg=reg), 10.0)
        self.assertEqual(self.f(D(2025, 7, 1), D(2025, 10, 1), reg=reg), 2.0)

    def test_default_registry_read_at_call_time(self):
        with mock.patch.object(pr, "KNOWN_SPLITS", REG):
            self.assertEqual(pr.split_factor("XSPL", "RUB", D(2025, 1, 1), D(2025, 7, 1)), 10.0)

    def test_reverse_split(self):
        reg = {"XSPL": [{"date": SPLIT_DATE, "ratio": 0.1}]}
        self.assertAlmostEqual(self.f(D(2025, 1, 1), D(2025, 7, 1), reg=reg), 0.1)


class TestCostAfterSplitScenarios(unittest.TestCase):
    def test_plzl_like_mixed_buys_and_sells(self):
        # Покупки: 10×3000 и 5×3200 до сплита ×10; 20×330 после. Продажи после: 40×340 и 30×350.
        tr = [T("Покупка", 10, 3000, D(2025, 1, 10)), T("Покупка", 5, 3200, D(2025, 2, 10)),
              T("Покупка", 20, 330, D(2025, 6, 10)), T("Продажа", 40, 340, D(2025, 6, 20)),
              T("Продажа", 30, 350, D(2025, 6, 25))]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        # после покупок: qty 150+20=170, cost 30000+16000+6600=52600, avg 52600/170
        avg = 52600 / 170
        cost1 = 52600 - avg * 40          # после первой продажи, qty 130
        cost2 = cost1 - (cost1 / 130) * 30  # после второй, qty 100
        self.assertAlmostEqual(p.qty, 100)
        self.assertAlmostEqual(p.total_cost_rub, cost2)
        self.assertAlmostEqual(p.total_cost_rub / p.qty, avg)  # средняя при продажах не «прыгает»
        self.assertAlmostEqual(p.total_sold_rub, 40 * 340 + 30 * 350)

    def test_sell_before_and_after_split_average_stable(self):
        tr = [BUY(), T("Продажа", 4, 3100, D(2025, 2, 10)), T("Продажа", 10, 310, D(2025, 6, 10))]
        p = recon(tr, D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 50)
        self.assertAlmostEqual(p.total_cost_rub, 15000)
        self.assertAlmostEqual(p.total_cost_rub / p.qty, 300)

    def test_corrections_before_split_in_post_split_units(self):
        plus = recon([BUY(), T("Корректировка", 2, 0, D(2025, 2, 1), amount=6000)],
                     D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(plus.qty, 120)
        self.assertAlmostEqual(plus.total_cost_rub, 36000)
        self.assertAlmostEqual(plus.avg_cost_rub, 300)
        minus = recon([BUY(), T("Корректировка", 2, 0, D(2025, 2, 1), amount=-6000)],
                      D(2025, 7, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(minus.qty, 80)
        self.assertAlmostEqual(minus.total_cost_rub, 24000)
        self.assertAlmostEqual(minus.total_sold_rub, 6000)

    def test_as_of_before_split_raw_units(self):
        tr = [BUY(), T("Продажа", 4, 3100, D(2025, 2, 10)), T("Корректировка", 1, 0, D(2025, 3, 1), amount=3000)]
        p = recon(tr, D(2025, 5, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 7)
        self.assertAlmostEqual(p.total_cost_rub, 21000)
        self.assertAlmostEqual(p.total_cost_rub / p.qty, 3000)


class TestLastKnownTradePrice(unittest.TestCase):
    def test_pre_split_price_divided_after_split(self):
        tr = [T("Покупка", 10, 3000, D(2025, 1, 10))]
        self.assertAlmostEqual(pr.last_known_trade_price("XSPL", "RUB", tr, D(2025, 7, 1), REG), 300.0)

    def test_as_of_before_split_not_divided(self):
        tr = [T("Покупка", 10, 3000, D(2025, 1, 10))]
        self.assertAlmostEqual(pr.last_known_trade_price("XSPL", "RUB", tr, D(2025, 5, 1), REG), 3000)

    def test_usd_not_adjusted(self):
        tr = [T("Покупка", 10, 50, D(2025, 1, 10), cur="USD")]
        self.assertAlmostEqual(pr.last_known_trade_price("XSPL", "USD", tr, D(2025, 7, 1), REG), 50)

    def test_post_split_trade_price_not_divided(self):
        tr = [T("Покупка", 10, 3000, D(2025, 1, 10)), T("Покупка", 5, 310, D(2025, 6, 10))]
        self.assertAlmostEqual(pr.last_known_trade_price("XSPL", "RUB", tr, D(2025, 7, 1), REG), 310)

    def test_synthetic_ignored(self):
        real = T("Покупка", 10, 3000, D(2025, 1, 10))
        syn = T("Продажа", 1, 999, D(2025, 3, 1))
        syn.is_synthetic = True
        self.assertAlmostEqual(
            pr.last_known_trade_price("XSPL", "RUB", [real, syn], D(2025, 5, 1), REG), 3000)

    def test_no_trades_none(self):
        self.assertIsNone(pr.last_known_trade_price("XSPL", "RUB", [], D(2025, 5, 1), REG))


class TestRegistry(unittest.TestCase):
    def test_known_splits_pinned(self):
        got = {k: [(s["date"], s["ratio"]) for s in v] for k, v in pr.KNOWN_SPLITS.items()}
        self.assertEqual(got, {
            "T": [(D(2026, 4, 17), 10.0)],
            "PLZL": [(D(2025, 3, 27), 10.0)],
            "GMKN": [(D(2024, 4, 4), 100.0)],
            "TRNFP": [(D(2024, 2, 21), 100.0)],
        })


class TestReconstruct(unittest.TestCase):
    A = D(2025, 12, 31)

    def rec(self, trades, as_of=None):
        return recon(trades, as_of or self.A, {})

    def test_correction_positive(self):
        tr = [T("Покупка", 10, 100, D(2025, 1, 1)), T("Корректировка", 5, 0, D(2025, 2, 1), amount=5000)]
        p = self.rec(tr)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 15)
        self.assertAlmostEqual(p.total_cost_rub, 6000)
        self.assertAlmostEqual(p.avg_cost_rub, 400)

    def test_correction_negative(self):
        tr = [T("Покупка", 10, 100, D(2025, 1, 1)), T("Корректировка", 4, 0, D(2025, 2, 1), amount=-700)]
        p = self.rec(tr)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 6)
        self.assertAlmostEqual(p.total_cost_rub, 600)
        self.assertAlmostEqual(p.total_sold_rub, 700)

    def test_correction_noop(self):
        base = T("Покупка", 10, 100, D(2025, 1, 1))
        for qty, amt in ((5, 0), (None, 500), (0, 500)):
            c = T("Корректировка", qty, 0, D(2025, 2, 1), amount=amt)
            p = self.rec([base, c])[("XSPL", "RUB")]
            self.assertAlmostEqual(p.qty, 10)
            self.assertAlmostEqual(p.total_cost_rub, 1000)

    def test_cash_and_point_skipped(self):
        tr = [T("Покупка", 1, 100, D(2025, 1, 1), ticker="Деньги (RUB)"),
              T("Покупка", 1, 100, D(2025, 1, 1), ticker="SI-3.25", cur="POINT")]
        self.assertEqual(self.rec(tr), {})

    def test_as_of_cutoff(self):
        tr = [T("Покупка", 10, 100, D(2025, 1, 1)), T("Покупка", 5, 100, D(2025, 6, 1))]
        p = self.rec(tr, D(2025, 3, 1))[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 10)

    def test_income_accumulates_without_qty(self):
        tr = [T("Покупка", 10, 100, D(2025, 1, 1)),
              T("Купон", 0, 0, D(2025, 2, 1), amount=30),
              T("Дивиденд", 0, 0, D(2025, 3, 1), amount=40),
              T("Амортизация", 0, 0, D(2025, 4, 1), amount=50)]
        p = self.rec(tr)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 10)
        self.assertAlmostEqual(p.coupons_rub, 30)
        self.assertAlmostEqual(p.dividends_rub, 40)
        self.assertAlmostEqual(p.amortization_rub, 50)

    def test_sell_writes_off_average_cost(self):
        tr = [T("Покупка", 10, 100, D(2025, 1, 1)), T("Продажа", 4, 130, D(2025, 2, 1))]
        p = self.rec(tr)[("XSPL", "RUB")]
        self.assertAlmostEqual(p.qty, 6)
        self.assertAlmostEqual(p.total_cost_rub, 600)
        self.assertAlmostEqual(p.total_sold_rub, 520)


class TestMerge(unittest.TestCase):
    @staticmethod
    def P(cur, name, qty, cost):
        return pr.Position(ticker="TGLD", currency=cur, name=name, qty=qty, total_cost_rub=cost,
                           total_sold_rub=1.0)

    def test_same_name_merged_to_rub(self):
        res = pr.merge_cross_currency_positions({
            ("TGLD", "USD"): self.P("USD", "Тинькофф Золото", 10, 1000),
            ("TGLD", "RUB"): self.P("RUB", "Тинькофф Золото", 5, 600)})
        self.assertEqual(list(res), [("TGLD", "RUB")])
        self.assertAlmostEqual(res[("TGLD", "RUB")].qty, 15)
        self.assertAlmostEqual(res[("TGLD", "RUB")].total_cost_rub, 1600)
        self.assertAlmostEqual(res[("TGLD", "RUB")].total_sold_rub, 2.0)

    def test_different_names_not_merged(self):
        res = pr.merge_cross_currency_positions({
            ("TGLD", "USD"): self.P("USD", "AT&T Inc", 10, 1000),
            ("TGLD", "RUB"): self.P("RUB", "Т-Технологии", 5, 600)})
        self.assertEqual(set(res), {("TGLD", "USD"), ("TGLD", "RUB")})

    def test_currency_priority(self):
        res = pr.merge_cross_currency_positions({
            ("TGLD", "CNY"): self.P("CNY", "Золото", 1, 10),
            ("TGLD", "USD"): self.P("USD", "Золото", 2, 20)})
        self.assertEqual(list(res), [("TGLD", "USD")])


class TestTmfForcedClose(unittest.TestCase):
    def tmf(self, op, qty, price, date):
        return T(op, qty, price, date, ticker="TMF", cur="USD", name="Direxion Daily")

    def test_remainder_closed_at_last_sell_price(self):
        tr = [self.tmf("Покупка", 100, 70, D(2024, 1, 10)), self.tmf("Продажа", 60, 65.5, D(2024, 3, 1))]
        out, log = pr.apply_corrections(list(tr))
        syn = [t for t in out if t.is_synthetic]
        self.assertEqual(len(syn), 1)
        self.assertEqual(syn[0].operation, "Продажа")
        self.assertEqual(syn[0].date, pr.TMF_FORCED_CLOSE_DATE)
        self.assertAlmostEqual(syn[0].qty, 40)
        self.assertAlmostEqual(syn[0].price, 65.5)
        rec = [r for r in log if r["type"] == "tmf_forced_close"]
        self.assertEqual(len(rec), 1)
        self.assertAlmostEqual(rec[0]["qty_closed"], 40)

    def test_zero_net_no_synthetic(self):
        tr = [self.tmf("Покупка", 100, 70, D(2024, 1, 10)), self.tmf("Продажа", 100, 65.5, D(2024, 3, 1))]
        out, log = pr.apply_corrections(list(tr))
        self.assertFalse([t for t in out if t.is_synthetic])
        self.assertFalse([r for r in log if r["type"] == "tmf_forced_close"])

    def test_no_sells_default_price(self):
        out, _ = pr.apply_corrections([self.tmf("Покупка", 100, 70, D(2024, 1, 10))])
        syn = [t for t in out if t.is_synthetic][0]
        self.assertAlmostEqual(syn.price, 61.09)

    def test_synthetic_works_with_classify_blocked(self):
        out, _ = pr.apply_corrections([self.tmf("Покупка", 100, 70, D(2024, 1, 10))])
        pr.classify_blocked(out)  # не должно падать на синтетике


if __name__ == "__main__":
    unittest.main()

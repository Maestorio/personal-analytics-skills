#!/usr/bin/env python3
"""Регрессионные тесты per_security_xirr.py.

Сценарий: Korrektirovka в trades должна попадать в cashflow XIRR симметрично
тому, как её учитывает reconstruct_positions. Иначе terminal market value
посчитан на одной qty, а cashflow-стрим — на другой, и XIRR взрывается.

Кейс MDMG (trades_portfolio_707160-12.xlsx, as_of 2026-05-14):
  • 8 buys на 275 785 ₽, 1 dividend, qty_now=133
  • 2 Korrektirovka со знаком amt<0: −82 842 ₽ и −25 856 ₽
  • Без учёта Korrektirovka: pnl = −102 590 ₽, XIRR ≈ −99% (артефакт)
  • С учётом Korrektirovka: pnl ≈ +6 100 ₽, XIRR ≈ +12.5% (last_trade_price);
    IntelInvest на той же дате показывает +17.07% (отличие — точка price-fix).
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from per_security_xirr import per_security_xirr

EXAMPLES = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "examples"
)
TRADES_XLSX = os.path.join(EXAMPLES, "trades_portfolio_707160-12.xlsx")


@unittest.skipUnless(
    os.path.exists(TRADES_XLSX),
    f"trades file not available: {TRADES_XLSX}",
)
class TestKorrektirovkaInCashflow(unittest.TestCase):
    """MDMG регрессия: Korrektirovka должна быть в cashflow стриме."""

    @classmethod
    def setUpClass(cls):
        cls.results = per_security_xirr(
            tickers=["MDMG"],
            trades_path=TRADES_XLSX,
            as_of=dt.date(2026, 5, 14),
            use_moex=False,
            cbr_offline=True,
        )
        cls.mdmg = cls.results["MDMG"]

    def test_corrections_counted(self):
        # 2 Korrektirovka в файле, обе с amt<0 → quasi-sell
        self.assertEqual(self.mdmg["n_corrections"], 2)
        self.assertAlmostEqual(self.mdmg["corr_sell_rub"], 108698.0, places=1)
        self.assertEqual(self.mdmg["corr_buy_rub"], 0.0)

    def test_qty_consistent_with_reconstruction(self):
        # 39 + 34 + 60 + 80 buys − (60+20) corrections = 133
        self.assertEqual(self.mdmg["qty_now"], 133.0)

    def test_buy_total_unchanged(self):
        # buy_total_rub считает только Покупки, не Korrektirovka
        self.assertAlmostEqual(
            self.mdmg["buy_total_rub"], 275785.19, places=1
        )

    def test_xirr_not_pathological(self):
        # До фикса было ≈ −99%. С фиксом должно быть в разумном диапазоне.
        # IntelInvest показывает +17.07% (на MOEX close), нам с last_trade_price
        # выпадает ~+12.5%. Берём широкий диапазон [−25%, +50%], чтобы тест
        # был устойчив к смене last_trade_price в свежих выгрузках.
        xirr_pct = self.mdmg["xirr_frac"] * 100
        self.assertIsNotNone(xirr_pct)
        self.assertGreater(xirr_pct, -25.0,
                           f"XIRR={xirr_pct}% — Korrektirovka не учтена в cashflow")
        self.assertLess(xirr_pct, 50.0,
                        f"XIRR={xirr_pct}% — подозрительно высокий, проверь cashflow")

    def test_pnl_includes_corrections(self):
        # pnl = sell + cpn + div + amort + corr_sell + MV − buy − corr_buy
        # corr_sell входит как proceed, поэтому pnl_rub > 0 при квази-flat позиции.
        m = self.mdmg
        expected_pnl = (
            m["sell_total_rub"] + m["coupons_rub"] + m["dividends_rub"]
            + m["amortization_rub"] + m["corr_sell_rub"] + m["market_value_rub"]
        ) - (m["buy_total_rub"] + m["corr_buy_rub"])
        self.assertAlmostEqual(m["pnl_rub"], expected_pnl, places=1)
        self.assertGreater(m["pnl_rub"], -50000,
                           "pnl_rub до фикса был −102590; должен подняться")

    def test_korrektirovka_cashflow_signs(self):
        # В cashflow стриме Korrektirovka (amt<0) появляется как +inflow
        # на тех же датах, что в trades: 2026-04-23 (+82842) и 2026-05-06 (+25856)
        cfs_by_date = {}
        for d, amt in self.mdmg["cashflows"]:
            cfs_by_date.setdefault(d, []).append(amt)
        self.assertIn("2026-04-23", cfs_by_date)
        self.assertIn(82842.0, cfs_by_date["2026-04-23"])
        self.assertIn("2026-05-06", cfs_by_date)
        self.assertIn(25856.0, cfs_by_date["2026-05-06"])


@unittest.skipUnless(
    os.path.exists(TRADES_XLSX),
    f"trades file not available: {TRADES_XLSX}",
)
class TestHomonymsAndSplit(unittest.TestCase):
    """T регрессия: тикер T держится двумя инструментами.

      ('T', 'USD') = AT&T INC.  — 3 шт, замороженные US, последняя сделка 2024
      ('T', 'RUB') = Т-Техно ао — 1010 шт (post-split ×10 от 101 pre-split)

    До фикса cashflow стрим включал ОБА → XIRR=None (не сходится).
    После фикса берётся primary position (RUB-priority среди активных) и её
    cashflow стрим. Плюс last_known_trade_price split-корректируется, иначе
    fallback MV = 3342.80 × 1010 = 3.37M вместо ~340k.
    """

    @classmethod
    def setUpClass(cls):
        cls.results = per_security_xirr(
            tickers=["T"],
            trades_path=TRADES_XLSX,
            as_of=dt.date(2026, 5, 14),
            use_moex=False,
            cbr_offline=True,
        )
        cls.t = cls.results["T"]

    def test_primary_is_t_techno_not_att(self):
        # primary = RUB-приоритет среди активных → Т-Техно (qty=1010), не AT&T (qty=3)
        self.assertEqual(self.t["qty_now"], 1010.0)
        # Первая сделка Т-Техно: 2023-02-16, не AT&T 2020-06-16
        self.assertEqual(self.t["first_trade_date"], "2023-02-16")

    def test_json_has_xirr_frac_not_percent_key(self):
        self.assertNotIn("xirr", self.t)
        self.assertGreater(self.t["xirr_frac"], -1.0)
        self.assertLess(self.t["xirr_frac"], 1.0)
        self.assertEqual(self.t["xirr_frac"], round(self.t["xirr_frac"], 4))

    def test_xirr_converges(self):
        # До фикса было None. После — конкретное число.
        self.assertIsNotNone(self.t["xirr_frac"])

    def test_xirr_in_sane_range_after_split_adjustment(self):
        # Split-adjusted last_trade (3342.80 / 10 = 334.28) даёт MV ≈ 337k →
        # XIRR в диапазоне 15–30%. IntelInvest с live MOEX (~309) показывает
        # 4.93%; разница в том, что последняя сделка была выше текущей цены.
        # Сам факт «XIRR в осмысленном диапазоне, не +1000%» — основной чек.
        xirr_pct = self.t["xirr_frac"] * 100
        self.assertGreater(xirr_pct, -10.0,
                           f"XIRR={xirr_pct}% — слишком низко для активной позиции")
        self.assertLess(xirr_pct, 100.0,
                        f"XIRR={xirr_pct}% — слишком высоко, last_trade_price не split-adjusted?")

    def test_market_value_split_adjusted(self):
        # 1010 × ~334.28 ≈ 337k. Если бы фикс split-adjust не сработал:
        # 1010 × 3342.80 = 3.37M — на порядок больше.
        mv = self.t["market_value_rub"]
        self.assertLess(mv, 1_000_000,
                        f"MV={mv} — похоже, last_trade не split-adjusted (ожидалось <1M)")
        self.assertGreater(mv, 100_000,
                           f"MV={mv} — подозрительно мало для 1010 шт")

    def test_cashflows_exclude_att_trades(self):
        # AT&T сделки 2020-2022 не должны попадать в cashflow стрим Т-Техно.
        cf_dates = {d for d, _ in self.t["cashflows"]}
        # AT&T trades датируются 2020-06-16 до 2022-02-08
        for d in cf_dates:
            self.assertGreater(d, "2022-12-31",
                               f"Cashflow {d} похож на AT&T (USD-инструмент)")


class TestXirrFracReader(unittest.TestCase):
    """Чтение ставки из per_security.json: xirr_frac — доля; старый xirr — проценты."""

    def test_new_format_passthrough(self):
        from assemble_snapshot import _read_xirr_frac
        self.assertEqual(_read_xirr_frac({"xirr_frac": 0.2337}), 0.2337)

    def test_old_format_percent_divided(self):
        from assemble_snapshot import _read_xirr_frac
        self.assertAlmostEqual(_read_xirr_frac({"xirr": 23.37}), 0.2337, places=9)

    def test_frac_wins_over_old(self):
        from assemble_snapshot import _read_xirr_frac
        self.assertEqual(_read_xirr_frac({"xirr_frac": 0.1, "xirr": 99.0}), 0.1)

    def test_missing_is_none(self):
        from assemble_snapshot import _read_xirr_frac
        self.assertIsNone(_read_xirr_frac({}))
        self.assertIsNone(_read_xirr_frac({"xirr_frac": None, "xirr": None}))

    def test_snapshot_entry_same_for_both_formats(self):
        from assemble_snapshot import _build_per_instrument_xirr
        new = _build_per_instrument_xirr({"SBER": {"ticker": "SBER", "xirr_frac": 0.2337}}, None)
        old = _build_per_instrument_xirr({"SBER": {"ticker": "SBER", "xirr": 23.37}}, None)
        self.assertEqual(new["SBER"]["xirr"], 0.2337)
        self.assertEqual(new["SBER"]["xirr"], old["SBER"]["xirr"])

    def test_by_account_split_old_and_new_same(self):
        # by_account считается из потоков, а не из xirr записи: формат ключа на него не влияет
        from assemble_snapshot import _read_xirr_frac
        self.assertEqual(_read_xirr_frac({"xirr_frac": 0.1, "by_account": {"main": {"xirr": 0.1}}}), 0.1)


if __name__ == "__main__":
    unittest.main()

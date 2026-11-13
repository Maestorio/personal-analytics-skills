#!/usr/bin/env python3
"""Инцидент 2026-10-13: «Общий баланс» vs расчёт по сделкам.

A) avg_cost акций: имена колонок сравниваются нормализованно. Реальная колонка
   листа «Акции» — «Ср, Цена» (запятая+пробел), точные имена её не ловили, и во
   ВСЕХ снапшотах с июня 2026 avg_cost_rub = value/qty (текущая цена; CNRU 671,4
   вместо 580,90). «Точка Входа» (цена входа модели IE) и «Цена» (текущая) — не
   средняя. Fallback value/qty остаётся, но громкий: флаг + avg_cost_source.
B) per_security_xirr: MOEX first. Override из баланса — только запасной вариант
   (нет котировки), значение баланса пишется в balance_value_rub (CNRU: баланс
   671,4 против MOEX 661,8 → pnl/xirr считались по устаревшей цене).
C) reconciliation.balance_vs_trades: avg_cost и value баланса против сделок и
   qty×MOEX, mismatch при |Δ| > 1 %, известные причины (KNOWN_SPLITS), сводка.

Без сети и без внешних файлов. Запуск:
  python3 skills/portfolio-data-loader/tests/test_balance_reconciliation.py
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "_shared-references"))

import assemble_snapshot as A  # noqa: E402
import per_security_xirr as P  # noqa: E402
from portfolio_returns import Position, Trade  # noqa: E402

# Реальные колонки листа «Акции» «Общего баланса» (2026-10-13)
REAL_COLS = ['Тикер', 'Название', 'Стоимость', 'Ср, Цена', 'Цена', 'Точка Входа',
             'IE New', 'IE Old', 'Доля актуальная', 'Доля Планируемая',
             'Доля Реальная', 'План', 'Статус', 'IE', 'AI']


def _row(**over):
    row = {c: None for c in REAL_COLS}
    row.update({'Тикер': 'CNRU', 'Название': 'Циан', 'Стоимость': 6714.0,
                'Ср, Цена': 580.9, 'Цена': 671.4, 'Точка Входа': 540.0})
    row.update(over)
    return row


class TestAvgCostColumns(unittest.TestCase):
    def test_real_column_name_matched(self):
        self.assertEqual(A._avg_cost_from_row(_row()), 580.9)

    def test_name_variants_normalized(self):
        for name in ("Ср. Цена", "Ср,Цена", "ср цена", "СР.ЦЕНА", "Средняя цена",
                     "Ср, Цена", "avg_cost"):
            row = {"Тикер": "X", "Цена": 999.0, name: 123.4}
            self.assertEqual(A._avg_cost_from_row(row), 123.4, name)

    def test_entry_point_and_current_price_not_matched(self):
        row = _row()
        del row['Ср, Цена']
        self.assertIsNone(A._avg_cost_from_row(row))  # «Точка Входа»/«Цена» не средняя


def _returns(qty=10.0, avg=580.9, ticker="CNRU", typ="stock"):
    return {"snapshot_current": {"positions": [
        {"ticker": ticker, "type": typ, "qty": qty, "value_rub": qty * 661.8,
         "avg_cost_rub": avg, "currency": "RUB", "is_blocked": False,
         "price_source": "moex"}]}}


class TestBuildStocks(unittest.TestCase):
    def test_balance_source(self):
        res, flags = A._build_stocks({"stocks": [_row()]}, _returns(), {"CNRU": {"last": 661.8}})
        self.assertEqual(res[0]["avg_cost_rub"], 580.9)
        self.assertEqual(res[0]["avg_cost_source"], "balance")
        self.assertFalse([f for f in flags if f["code"] == "avg_cost_fallback_value_over_qty"])

    def test_fallback_flag_and_source(self):
        row = _row()
        del row['Ср, Цена']
        res, flags = A._build_stocks({"stocks": [row]}, _returns(), {"CNRU": {"last": 661.8}})
        self.assertEqual(res[0]["avg_cost_rub"], 671.4)  # value/qty
        self.assertEqual(res[0]["avg_cost_source"], "value_over_qty")
        fl = [f for f in flags if f["code"] == "avg_cost_fallback_value_over_qty"]
        self.assertEqual(len(fl), 1)
        self.assertIn("CNRU", fl[0]["message"])
        self.assertEqual(fl[0]["severity"], "warning")


def _holding(ticker="CNRU", qty=10.0, avg=580.9, price=661.8, value=6618.0,
             avg_src="balance", typ="stock", src="moex_iss"):
    return {"ticker": ticker, "asset_type": typ, "qty": qty, "avg_cost_rub": avg,
            "avg_cost_source": avg_src, "current_price": price,
            "current_price_source": src, "value_rub": value, "is_blocked": False,
            "status": "normal"}


class TestReconciliation(unittest.TestCase):
    def test_match(self):
        blk, flags = A._build_balance_vs_trades([_holding()], _returns(), frozenset())
        r = blk["positions"][0]
        self.assertFalse(r["mismatch"])
        self.assertEqual(blk["summary"]["n_checked"], 1)
        self.assertEqual(blk["summary"]["n_mismatch"], 0)
        self.assertEqual(flags, [])

    def test_avg_mismatch_over_1pct(self):
        blk, flags = A._build_balance_vs_trades(
            [_holding(avg=600.0)], _returns(avg=580.9), frozenset())
        r = blk["positions"][0]
        self.assertTrue(r["mismatch"])
        self.assertEqual(r["mismatch_fields"], ["avg_cost"])
        self.assertAlmostEqual(r["avg_cost_diff_pct"], 3.29, places=2)
        self.assertEqual(blk["summary"]["unexplained_tickers"], ["CNRU"])
        self.assertEqual(flags[0]["code"], "balance_vs_trades_mismatch")
        self.assertEqual(flags[0]["severity"], "info")

    def test_value_mismatch_stale_balance_price(self):
        # баланс 671,4 vs MOEX 661,8: +1,45 %
        blk, _ = A._build_balance_vs_trades(
            [_holding(value=6714.0)], _returns(), frozenset())
        r = blk["positions"][0]
        self.assertEqual(r["mismatch_fields"], ["value"])
        self.assertAlmostEqual(r["value_diff_pct"], 1.45, places=2)

    def test_within_threshold_not_flagged(self):
        blk, _ = A._build_balance_vs_trades(
            [_holding(avg=585.0, value=6650.0)], _returns(avg=580.9), frozenset())
        self.assertFalse(blk["positions"][0]["mismatch"])  # 0,7 % и 0,5 %

    def test_known_split_marked_not_unexplained(self):
        blk, _ = A._build_balance_vs_trades(
            [_holding(ticker="PLZL", avg=100.0)], _returns(ticker="PLZL", avg=50.0),
            frozenset({"PLZL"}))
        r = blk["positions"][0]
        self.assertTrue(r["mismatch"])
        self.assertEqual(r["known_reasons"], ["known_split"])
        self.assertEqual(blk["summary"]["n_mismatch"], 1)
        self.assertEqual(blk["summary"]["n_mismatch_unexplained"], 0)

    def test_fallback_avg_not_compared(self):
        # avg из value/qty — не данные баланса, сверять нечего; value сверяется
        blk, _ = A._build_balance_vs_trades(
            [_holding(avg=671.4, avg_src="value_over_qty")], _returns(), frozenset())
        r = blk["positions"][0]
        self.assertIsNone(r["avg_cost_balance"])
        self.assertIsNone(r["avg_cost_diff_pct"])

    def test_skips_no_quote_blocked_and_bonds(self):
        hs = [_holding(src="last_trade"), _holding(ticker="B", typ="bond"),
              {**_holding(ticker="Z"), "is_blocked": True}]
        blk, _ = A._build_balance_vs_trades(hs, _returns(), frozenset())
        self.assertEqual(blk["summary"]["n_checked"], 0)

    def test_fund_value_only(self):
        h = _holding(ticker="TGLD", typ="fund", avg=None, avg_src=None, value=6700.0)
        blk, _ = A._build_balance_vs_trades(
            [h], _returns(ticker="TGLD", typ="fund"), frozenset())
        r = blk["positions"][0]
        self.assertEqual(r["mismatch_fields"], ["value"])

    def test_no_holdings(self):
        self.assertEqual(A._build_balance_vs_trades(None, None), (None, []))


class TestPerSecurityMoexFirst(unittest.TestCase):
    """Синтетика: 10 CNRU куплено по 580,9; баланс 671,4/шт, MOEX 661,8/шт."""

    def setUp(self):
        self._saved = {k: getattr(P, k) for k in (
            "parse_trades", "apply_corrections", "convert_trades_to_rub",
            "fetch_moex_prices", "load_cbr_cache", "reconstruct_positions",
            "last_known_trade_price")}
        d = dt.date(2025, 1, 10)
        tr = Trade(ticker="CNRU", name="Циан", operation="Покупка", date=d, qty=10.0,
                   price=580.9, nominal=None, nkd=None, commission=0.0, amount=5809.0,
                   amount_no_comm=5809.0, currency="RUB", note="", rub_amount=5809.0)
        pos = Position(ticker="CNRU", currency="RUB", name="Циан", qty=10.0,
                       total_cost_rub=5809.0, avg_cost_rub=580.9)
        P.parse_trades = lambda path: [tr]
        P.apply_corrections = lambda t: (t, [])
        P.convert_trades_to_rub = lambda t, verbose=False, cbr_offline=False: t
        P.reconstruct_positions = lambda t, as_of: {("CNRU", "RUB"): pos}
        P.load_cbr_cache = lambda: {}
        P.last_known_trade_price = lambda *a, **k: 580.9
        self.moex = {"CNRU": 661.8}
        P.fetch_moex_prices = lambda secids, verbose=False, accrued_out=None: (
            {k: v for k, v in self.moex.items() if k in secids}, {}, {}, [])

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(P, k, v)

    def _run(self, **kw):
        return P.per_security_xirr(
            ["CNRU"], "x.xlsx", dt.date(2026, 10, 13), cbr_offline=True,
            market_values_override={"CNRU": 6714.0}, **kw)["CNRU"]

    def test_moex_beats_stale_balance(self):
        r = self._run(use_moex=True)
        self.assertAlmostEqual(r["market_value_rub"], 6618.0, places=2)
        self.assertEqual(r["price_source"], "moex")
        self.assertAlmostEqual(r["pnl_rub"], 6618.0 - 5809.0, places=2)
        self.assertEqual(r["balance_value_rub"], 6714.0)

    def test_override_is_fallback_without_quote(self):
        self.moex = {}
        r = self._run(use_moex=True)
        self.assertAlmostEqual(r["market_value_rub"], 6714.0, places=2)
        self.assertEqual(r["price_source"], "override")
        self.assertEqual(r["balance_value_rub"], 6714.0)

    def test_no_moex_mode_uses_override(self):
        r = self._run(use_moex=False)
        self.assertEqual(r["price_source"], "override")


class TestBondQtyVsTrades(unittest.TestCase):
    """PDL-RECON (2026-10-20): количество облигаций баланса против сделок — НорНик1P17 24 против 34."""

    H = [
        {"asset_type": "bond", "isin": "RU000A10FC62", "name": "НорНик1P17", "qty": 24, "account": "main", "status": "normal"},
        {"asset_type": "bond", "isin": "RU000A1038V6", "name": "ОФЗ 26238", "qty": 80, "account": "main", "status": "normal"},
        {"asset_type": "bond", "isin": "RU000A1038V6", "name": "ОФЗ 26238", "qty": 130, "account": "iis_3", "status": "normal"},
        {"asset_type": "bond", "isin": "RU000A10EST2", "name": "ЭталонФин5", "qty": 26, "account": "main", "status": "normal"},
        {"asset_type": "stock", "ticker": "SBER", "qty": 10, "account": "main", "status": "normal"},
    ]
    X = {
        "RU000A10FC62": {"isin": "RU000A10FC62", "qty_now": 34.0},
        "SU26238RMFS4": {"isin": "RU000A1038V6", "qty_now": 210.0},   # дубль под SU-ключом,
        "RU000A1038V6": {"isin": "RU000A1038V6", "qty_now": 210.0},   # сумма main+ИИС — не расхождение
        "SBER": {"isin": "RU0009029540", "qty_now": 10.0},
    }

    def test_mismatch_only_nornickel(self):
        block, flags = A._build_bond_qty_vs_trades(self.H, self.X)
        self.assertEqual(block["summary"]["mismatch_isins"], ["RU000A10FC62"])
        self.assertEqual(block["summary"]["n_checked"], 2)  # ЭталонФин5 в сделках нет — не сверяется
        self.assertEqual(flags[0]["code"], "bond_qty_vs_trades_mismatch")
        self.assertEqual(flags[0]["severity"], "warning")
        self.assertIn("баланс 24, сделки 34", flags[0]["message"])

    def test_clean_and_missing_inputs(self):
        x = dict(self.X, RU000A10FC62={"isin": "RU000A10FC62", "qty_now": 24.0})
        self.assertEqual(A._build_bond_qty_vs_trades(self.H, x)[1], [])
        self.assertEqual(A._build_bond_qty_vs_trades(None, self.X), (None, []))
        self.assertEqual(A._build_bond_qty_vs_trades(self.H, None), (None, []))


if __name__ == "__main__":
    unittest.main(verbosity=1)

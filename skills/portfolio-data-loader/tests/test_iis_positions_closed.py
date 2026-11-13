#!/usr/bin/env python3
"""Позиции ИИС-3 по сделкам его выгрузки и результат по проданным бумагам (решения владельца 30.10.2026).

Позиции ИИС-3 (assemble._portfolio_from_trades, iis_returns):
  • выгрузка ИИС-3 есть → позиции счёта и их количество — по её сделкам (покупка после прошлого снапшота
    поднимает qty, частичная продажа снижает, погашение/полная продажа убирает позицию); основной счёт у
    облигации на двух счетах = выгрузка основного − ИИС-3 (сумма двух счетов, без угадывания по прошлому
    снапшоту); из прошлого снапшота берутся только атрибуты (название, корзина);
  • snapshot.iis_positions_source: trades_export | balance | carried | none; balance_summary.carried не
    содержит iis_positions, когда позиции построены по сделкам;
  • выгрузки нет → перенос из прошлого снапшота (carried), как прежде;
  • баланс приложен → позиции ИИС-3 баланса не перетираются, расхождение с выгрузкой — iis_returns_mismatch;
  • акция на ИИС-3 или фонд на двух счетах → флаг iis_positions_not_split; qty ИИС-3 больше всей выгрузки
    основного → iis_qty_exceeds_total.
Результат по проданным (assemble._build_closed_instrument_xirr + per_security_xirr.last_sell_date/name,
build_snapshot.closed_tickers): отдельный блок per_instrument_xirr_closed — per_instrument_xirr читают как
«то, что держу» (доли, сортировка по XIRR, recent_* неразворота); запись: closed, close_date (последняя
продажа/погашение, не последний дивиденд), holding_days, разбивка потоков, pnl_rub и xirr из потоков; проданная
и купленная снова бумага — одна запись в per_instrument_xirr, в закрытых её нет; фьючерсы не входят.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_iis_positions_closed.py
"""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import assemble_snapshot as asm  # noqa: E402
import build_snapshot as bs  # noqa: E402
import per_security_xirr as psx  # noqa: E402
from portfolio_returns import Trade, xirr  # noqa: E402

D = dt.date

# ── ИИС-3 по сделкам ─────────────────────────────────────────────────────────────

RETURNS = {"snapshot_current": {
    "cash_balance_rub": 0.0, "cash_by_currency": {"RUB": 0.0},
    "positions": [
        {"ticker": "SU26238RMFS4", "type": "bond", "qty": 210, "value_rub": 126000.0, "avg_cost_rub": 590.0,
         "currency": "RUB", "nominal_currency": "RUB", "name": "ОФЗ 26238", "price_source": "moex_last",
         "is_blocked": False},
        {"ticker": "SU26247RMFS5", "type": "bond", "qty": 90, "value_rub": 90000.0, "avg_cost_rub": 1000.0,
         "currency": "RUB", "nominal_currency": "RUB", "name": "ОФЗ 26247", "price_source": "moex_last",
         "is_blocked": False},
        {"ticker": "SBGB", "type": "fund", "qty": 100, "value_rub": 1500.0, "avg_cost_rub": 14.0,
         "currency": "RUB", "name": "SBGB", "price_source": "moex_last", "is_blocked": False},
    ]}}

PREV = {
    "as_of_date": "2026-10-16",
    "holdings": [
        {"ticker": "SU26238RMFS4", "name": "ОФЗ 26238", "asset_type": "bond", "account": "main", "qty": 80,
         "value_rub": 47000.0, "plan_bucket": "ОФЗ", "plan_subtype": ">10", "isin": "RU000A1038V6"},
        {"ticker": "SU26238RMFS4", "name": "ОФЗ 26238", "asset_type": "bond", "account": "iis_3", "qty": 130,
         "value_rub": 76000.0, "plan_bucket": "ОФЗ", "plan_subtype": ">10", "isin": "RU000A1038V6"},
        {"ticker": "SU26247RMFS5", "name": "ОФЗ 26247", "asset_type": "bond", "account": "iis_3", "qty": 50,
         "value_rub": 48000.0, "plan_bucket": "ОФЗ", "plan_subtype": "<10", "isin": "RU000A108EF8"},
        {"ticker": "SU52004RMFS7", "name": "ОФЗ 52004", "asset_type": "bond", "account": "iis_3", "qty": 180,
         "value_rub": 227000.0, "plan_bucket": "ОФЗ", "plan_subtype": "Линкер", "isin": "RU000A103MX5"},
        {"ticker": "SBGB", "name": "SBGB", "asset_type": "fund", "account": "iis_3", "qty": 100, "value_rub": 1450.0},
    ],
    "cash": {"total_rub": 290000.0, "by_account": {"main": 270000.0, "iis_3": 20000.0}},
    "cash_reconciliation": {"current_drift_rub": 0.0, "baseline_drift_rub": 0.0},
}


def iis_export(positions, **kw):
    """Выход iis_returns.py: positions [(secid, isin, qty, kind, value)]."""
    out = {"positions": [{"secid": s, "isin": i, "qty": q} for s, i, q, _k, _v in positions],
           "per_bond": [{"secid": s, "isin": i, "name": f"ОФЗ {s[2:7]}", "qty": q, "value_rub": v}
                        for s, i, q, k, v in positions if k == "bond"],
           "other_positions": [{"secid": s, "kind": k, "qty": q, "value_rub": v}
                               for s, i, q, k, v in positions if k != "bond"],
           "account_flows": {}, "file_last_operation": "2026-10-21"}
    out.update(kw)
    return out


# покупка 26247 до 90, частичная продажа 26238 до 100, 52004 погашена (позиции нет)
EXPORT = iis_export([("SU26238RMFS4", "RU000A1038V6", 100.0, "bond", 60000.0),
                     ("SU26247RMFS5", "RU000A108EF8", 90.0, "bond", 90000.0),
                     ("SBGB", None, 100.0, "fund", 1500.0)])


def build(iis=EXPORT, prev=PREV, returns=RETURNS):
    return asm.assemble(None, returns, None, {}, prev_snapshot=prev, holdings_from_trades=True,
                        as_of="2026-10-30", iis_returns=iis)


class IisFromTrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = build()
        cls.h = {(h["ticker"], h["account"]): h for h in cls.s["holdings"]}
        cls.codes = [f["code"] for f in cls.s["data_quality_flags"]]

    def test_quantities_follow_trades_not_prev(self):
        self.assertEqual(self.h[("SU26238RMFS4", "iis_3")]["qty"], 100)        # частичная продажа 130 → 100
        self.assertEqual(self.h[("SU26247RMFS5", "iis_3")]["qty"], 90)         # покупка 50 → 90

    def test_redeemed_position_gone(self):
        self.assertNotIn(("SU52004RMFS7", "iis_3"), self.h)                    # в прошлом снапшоте была, сделок-остатка нет

    def test_main_is_export_minus_iis(self):
        m = self.h[("SU26238RMFS4", "main")]
        self.assertEqual(m["qty"], 110)                                        # 210 − 100, а не 80 из прошлого снапшота
        self.assertAlmostEqual(m["value_rub"], 126000 / 210 * 110, places=1)
        self.assertAlmostEqual(self.h[("SU26238RMFS4", "iis_3")]["value_rub"], 126000 / 210 * 100, places=1)

    def test_iis_only_bond_not_on_main(self):
        self.assertNotIn(("SU26247RMFS5", "main"), self.h)                     # 90 из 90 — вся на ИИС-3, не задваивается

    def test_attributes_from_prev(self):
        h = self.h[("SU26247RMFS5", "iis_3")]
        self.assertEqual((h["plan_bucket"], h["plan_subtype"]), ("ОФЗ", "<10"))

    def test_fund_on_iis(self):
        self.assertEqual(self.h[("SBGB", "iis_3")]["qty"], 100)
        self.assertNotIn(("SBGB", "main"), self.h)

    def test_provenance(self):
        self.assertEqual(self.s["iis_positions_source"], "trades_export")
        self.assertNotIn("iis_positions", self.s["balance_summary"]["carried"])
        msg = next(f["message"] for f in self.s["data_quality_flags"]
                   if f["code"] == "balance_absent_holdings_from_trades")
        self.assertIn("по сделкам выгрузки счёта", msg)
        self.assertNotIn("позиции снапшота", msg)

    def test_no_unrepresented_flags(self):
        self.assertNotIn("iis_positions_not_split", self.codes)
        self.assertNotIn("iis_qty_exceeds_total", self.codes)

    def test_no_export_carries_prev(self):
        s = build(iis=None)
        h = {(x["ticker"], x["account"]): x for x in s["holdings"]}
        self.assertEqual(h[("SU26247RMFS5", "iis_3")]["qty"], 50)              # как в прошлом снапшоте
        self.assertEqual(h[("SU52004RMFS7", "iis_3")]["qty"], 180)
        self.assertEqual(s["iis_positions_source"], "carried")
        self.assertIn("iis_positions", s["balance_summary"]["carried"])

    def test_no_export_no_prev_iis(self):
        prev = dict(PREV, holdings=[x for x in PREV["holdings"] if x["account"] != "iis_3"])
        self.assertEqual(build(iis=None, prev=prev)["iis_positions_source"], "none")

    def test_iis_exceeds_total_flagged(self):
        exp = iis_export([("SU26238RMFS4", "RU000A1038V6", 250.0, "bond", 150000.0)])
        s = build(iis=exp)
        h = {(x["ticker"], x["account"]): x for x in s["holdings"]}
        self.assertNotIn(("SU26238RMFS4", "main"), h)                          # основной не уходит в минус
        self.assertIn("iis_qty_exceeds_total", [f["code"] for f in s["data_quality_flags"]])

    def test_stock_on_iis_flagged(self):
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": RETURNS["snapshot_current"]["positions"] + [
            {"ticker": "SBER", "type": "stock", "qty": 10, "value_rub": 3000.0, "avg_cost_rub": 280.0,
             "currency": "RUB", "name": "Сбер", "price_source": "moex_last", "is_blocked": False}]}}
        exp = iis_export([("SBER", None, 10.0, "stock", 3000.0)])
        s = build(iis=exp, returns=ret)
        self.assertIn("iis_positions_not_split", [f["code"] for f in s["data_quality_flags"]])

    def test_fund_on_both_accounts_flagged(self):
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            dict(RETURNS["snapshot_current"]["positions"][2], qty=150, value_rub=2250.0)]}}
        s = build(iis=iis_export([("SBGB", None, 100.0, "fund", 1500.0)]), returns=ret)
        self.assertIn("iis_positions_not_split", [f["code"] for f in s["data_quality_flags"]])


class IisWithBalance(unittest.TestCase):
    """Баланс приложен: его позиции ИИС-3 сверяются с выгрузкой, а не заменяются ею."""

    def test_provenance_balance(self):
        ret = {"snapshot_current": {"positions": []}, "fx_rates_asof": {}}
        s = asm.assemble({"stocks": [], "bonds": [], "other_positions": []}, ret, None, {})
        self.assertEqual(s["iis_positions_source"], "balance")

    def test_mismatch_flag_and_no_overwrite(self):
        holdings = [{"ticker": "RU000A1038V6", "isin": "RU000A1038V6", "account": "iis_3", "qty": 130.0,
                     "value_rub": 70000.0, "status": "normal"}]
        exp = iis_export([("SU26238RMFS4", "RU000A1038V6", 100.0, "bond", 60000.0)])
        block, flags = asm._build_iis_account_returns(exp, holdings, {})
        self.assertEqual(block["status"], "mismatch")
        self.assertIn("iis_returns_mismatch", [f["code"] for f in flags])
        self.assertEqual(holdings[0]["qty"], 130.0)                            # баланс не перетёрт

    def test_match_no_flag(self):
        holdings = [{"ticker": "RU000A1038V6", "isin": "RU000A1038V6", "account": "iis_3", "qty": 100.0,
                     "value_rub": 60000.0, "status": "normal"}]
        exp = iis_export([("SU26238RMFS4", "RU000A1038V6", 100.0, "bond", 60000.0)])
        block, flags = asm._build_iis_account_returns(exp, holdings, {})
        self.assertEqual(block["status"], "ok")
        self.assertNotIn("iis_returns_mismatch", [f["code"] for f in flags])


# ── проданные бумаги ──────────────────────────────────────────────────────────────

def T(ticker, op, day, amount, qty=None, name="Бумага"):
    return Trade(ticker=ticker, name=name, operation=op, date=day, qty=qty, price=None, nominal=None, nkd=None,
                 commission=0.0, amount=amount, amount_no_comm=amount, currency="RUB", note="")


AS_OF = D(2026, 10, 30)


def run_psx(trades, tickers):
    with mock.patch.object(psx, "parse_trades", return_value=trades):
        return psx.per_security_xirr(tickers, "x.xlsx", AS_OF, use_moex=False, cbr_offline=True)


def _xirr(flows):
    return xirr(sorted(flows, key=lambda f: f[0]))


STOCK = [T("ZZZ", "Покупка", D(2025, 1, 10), -10000.0, 100, "Зет"),
         T("ZZZ", "Дивиденд", D(2025, 6, 1), 500.0, name="Зет"),
         T("ZZZ", "Продажа", D(2025, 12, 10), 12000.0, 100, "Зет"),
         T("ZZZ", "Дивиденд", D(2026, 3, 1), 40.0, name="Зет")]            # выплата уже после продажи

BOND = [T("RU000TESTBND1", "Покупка", D(2024, 1, 10), -10000.0, 10, "ТестБонд"),
        T("RU000TESTBND1", "Купон", D(2024, 7, 10), 600.0, name="ТестБонд"),
        T("RU000TESTBND1", "Амортизация", D(2025, 1, 10), 3000.0, name="ТестБонд"),
        T("RU000TESTBND1", "Купон", D(2025, 1, 10), 500.0, name="ТестБонд"),
        T("RU000TESTBND1", "Продажа", D(2025, 7, 10), 7000.0, 10, "ТестБонд")]   # погашение в выгрузке — «Продажа»

FUND = [T("SBGB", "Покупка", D(2026, 1, 12), -20000.0, 1000, "SBGB ETF"),
        T("SBGB", "Продажа", D(2026, 9, 12), 21000.0, 1000, "SBGB ETF")]


class ClosedInstruments(unittest.TestCase):
    def closed(self, trades, tickers, per_instrument=None, holdings=None):
        res = run_psx(trades, tickers)
        return asm._build_closed_instrument_xirr(res, per_instrument, holdings, None, "2026-10-30"), res

    def test_stock_with_dividends(self):
        c, res = self.closed(STOCK, ["ZZZ"])
        r = c["ZZZ"]
        self.assertTrue(r["closed"])
        self.assertEqual((r["qty_now"], r["market_value_rub"], r["price_source"]), (0.0, 0.0, "closed"))
        self.assertEqual(r["close_date"], "2025-12-10")                          # последняя продажа, не дивиденд 2026-03
        self.assertEqual(r["last_trade_date"], "2026-03-01")
        self.assertEqual(r["holding_days"], (D(2025, 12, 10) - D(2025, 1, 10)).days)
        self.assertEqual((r["buy_total_rub"], r["sell_total_rub"], r["dividends_rub"]), (10000.0, 12000.0, 540.0))
        self.assertEqual(r["pnl_rub"], 2540.0)
        self.assertEqual((r["name"], r["asset_type"], r["n_sells"]), ("Зет", "stock", 1))
        want = _xirr([(D(2025, 1, 10), -10000.0), (D(2025, 6, 1), 500.0), (D(2025, 12, 10), 12000.0),
                      (D(2026, 3, 1), 40.0)])
        self.assertAlmostEqual(r["xirr"], want, places=4)                        # доля, не процент

    def test_matured_bond_with_coupons_and_amortization(self):
        c, _ = self.closed(BOND, ["RU000TESTBND1"])
        r = c["RU000TESTBND1"]
        self.assertEqual(r["asset_type"], "bond")
        self.assertEqual((r["coupons_rub"], r["amortization_rub"], r["sell_total_rub"]), (1100.0, 3000.0, 7000.0))
        self.assertEqual(r["pnl_rub"], 1100.0 + 3000.0 + 7000.0 - 10000.0)
        self.assertEqual(r["close_date"], "2025-07-10")
        self.assertGreater(r["xirr"], 0)

    def test_sold_fund(self):
        c, _ = self.closed(FUND, ["SBGB"])
        r = c["SBGB"]
        self.assertEqual((r["asset_type"], r["pnl_rub"], r["close_date"]), ("fund", 1000.0, "2026-09-12"))
        self.assertEqual(r["holding_days"], (D(2026, 9, 12) - D(2026, 1, 12)).days)

    def test_sold_and_bought_again_is_held_not_closed(self):
        trades = STOCK + [T("ZZZ", "Покупка", D(2026, 5, 1), -5000.0, 40, "Зет")]
        res = run_psx(trades, ["ZZZ"])
        self.assertEqual(res["ZZZ"]["qty_now"], 40.0)                            # держится: per_security кладёт её в основной блок
        held = {"ZZZ": {"qty_now": 40.0}}
        self.assertEqual(asm._build_closed_instrument_xirr(res, held, [], None, "2026-10-30"), {})
        self.assertEqual(asm._build_closed_instrument_xirr(res, {}, [{"ticker": "ZZZ"}], None, "2026-10-30"), {})
        # запись закрыта (омоним: AT&T закрыта, Т-Техно под тем же тикером держится) — держимый тикер выигрывает
        shut = {"ZZZ": dict(res["ZZZ"], qty_now=0.0)}
        self.assertEqual(asm._build_closed_instrument_xirr(shut, held, [], None, "2026-10-30"), {})
        self.assertEqual(asm._build_closed_instrument_xirr(shut, {}, [{"ticker": "ZZZ"}], None, "2026-10-30"), {})
        self.assertIn("ZZZ", asm._build_closed_instrument_xirr(shut, {}, [], None, "2026-10-30"))
        # и по тикерам для запуска: ZZZ с покупкой, но позиция есть → не закрытая
        returns = {"snapshot_current": {"positions": [{"ticker": "ZZZ", "qty": 40.0}]}}
        self.assertEqual(bs.closed_tickers(returns, {"ZZZ": trades}), [])

    def test_closed_tickers_selection(self):
        trades = {"ZZZ": STOCK, "SBGB": FUND,
                  "HELD": [T("HELD", "Покупка", D(2025, 1, 1), -1.0, 1)],
                  "DIVONLY": [T("DIVONLY", "Дивиденд", D(2025, 1, 1), 5.0)],
                  "Деньги (RUB)": [T("Деньги (RUB)", "Внесение", D(2025, 1, 1), 5.0)],
                  "SI-3.23": [T("SI-3.23", "Покупка", D(2025, 1, 1), -1.0, 1),
                              T("SI-3.23", "Списание вариационной маржи", D(2025, 1, 2), -1.0)],
                  "BLK": [T("BLK", "Покупка", D(2025, 1, 1), -1.0, 1)]}
        returns = {"snapshot_current": {"positions": [{"ticker": "HELD", "qty": 3.0},
                                                      {"ticker": "BLK", "qty": 2.0, "is_blocked": True}]}}
        self.assertEqual(bs.closed_tickers(returns, trades), ["SBGB", "ZZZ"])    # заблокированная — не закрытая

    def test_future_excluded(self):
        res = {"SI-3.23": {"inst_type": "future", "qty_now": 0.0, "xirr_frac": 0.01, "pnl_rub": 5.0,
                           "first_trade_date": "2025-01-01", "last_trade_date": "2025-02-01"}}
        self.assertEqual(asm._build_closed_instrument_xirr(res, {}, [], None, "2026-10-30"), {})

    def test_assemble_keeps_blocks_apart(self):
        res = run_psx(STOCK + FUND, ["ZZZ", "SBGB"])
        ret = {"snapshot_current": {"positions": []}, "fx_rates_asof": {}}
        s = asm.assemble({"stocks": [], "bonds": [], "other_positions": []}, ret, {}, {},
                         per_security_closed=res)
        self.assertEqual(sorted(s["per_instrument_xirr_closed"]), ["SBGB", "ZZZ"])
        self.assertFalse(s["per_instrument_xirr"])                                # «что держу» не тронуто
        s2 = asm.assemble({"stocks": [], "bonds": [], "other_positions": []}, ret, {}, {})
        self.assertIsNone(s2["per_instrument_xirr_closed"])                       # прогон без закрытых — поля нет в смысле «не считали»


if __name__ == "__main__":
    unittest.main(verbosity=1)

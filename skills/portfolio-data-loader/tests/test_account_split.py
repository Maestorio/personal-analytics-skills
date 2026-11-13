#!/usr/bin/env python3
"""Доходность бумаги по счетам: per_instrument_xirr[KEY].by_account {main, iis_3}.

Основная выгрузка IntelInvest — сводная по обоим счетам (колонки счёта нет), поэтому часть «основной» =
суммарные потоки минус потоки ИИС-3 (iis_returns.account_flows). Выгрузки ИИС-3 к сборке нет → потоки
берутся из прошлого снапшота (carried); остаток ИИС-3 по балансу разошёлся с ними → бумага пропускается,
флаг iis_trades_stale. Фикстура — ОФЗ как 26247: ИИС-3 купил 90 шт по 89,363 % и получил купон;
основной докупил 149 шт позже. Сеть не нужна.
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scripts import iis_returns as ir
from scripts.assemble_snapshot import _build_per_instrument_xirr, _resolve_iis_flows
from scripts.portfolio_returns import Trade, reconstruct_positions

D = dt.date
AS_OF = D(2026, 10, 28)


def _t(op, day, amount, qty, ticker="SU26247RMFS5"):
    return Trade(ticker=ticker, name="ОФЗ 26247", operation=op, date=day, qty=qty, price=None, nominal=None,
                 nkd=None, commission=0.0, amount=amount, amount_no_comm=amount, currency="RUB", note="",
                 rub_amount=amount, rub_rate=1.0)


IIS = [_t("Покупка", D(2026, 4, 20), -84836.7, 90), _t("Купон", D(2026, 5, 27), 5497.2, 90)]
MAIN = [_t("Покупка", D(2026, 10, 26), -126761.75, 149)]
MV = 100000.0 * 0 + 239 * 800.0           # 239 шт по 800 ₽ (грязная)


def _per_security(trades, qty, mv):
    """Запись per_security для суммарных сделок (как per_security_xirr: потоки + терминал)."""
    cfs = []
    buy = coupons = 0.0
    for t in trades:
        if t.operation == "Покупка":
            cfs.append((t.date.isoformat(), t.rub_amount)); buy += -t.rub_amount
        elif t.operation == "Купон":
            cfs.append((t.date.isoformat(), t.rub_amount)); coupons += t.rub_amount
    cfs.append((AS_OF.isoformat(), mv))
    return {"SU26247RMFS5": {"xirr_frac": 0.10, "qty_now": qty, "market_value_rub": mv, "buy_total_rub": buy,
                             "coupons_rub": coupons, "sell_total_rub": 0.0, "dividends_rub": 0.0,
                             "pnl_rub": round(mv + coupons - buy, 2), "cashflows": cfs,
                             "first_trade_date": "2026-04-20"}}


def _flows(trades):
    pos = reconstruct_positions(trades, AS_OF)
    return ir.account_flows(trades, pos, AS_OF)


class AccountSplit(unittest.TestCase):
    def setUp(self):
        self.ps = _per_security(sorted(IIS + MAIN, key=lambda t: t.date), 239, MV)
        self.flows = _flows(IIS)

    def _build(self, flows, **kw):
        return _build_per_instrument_xirr(self.ps, None, [], None, flows, AS_OF.isoformat(), **kw)["SU26247RMFS5"]

    def test_two_accounts_sum_to_total(self):
        rec = self._build(self.flows)
        ba = rec["by_account"]
        self.assertAlmostEqual(ba["main"]["pnl_rub"] + ba["iis_3"]["pnl_rub"], rec["pnl_rub"], delta=1.0)
        self.assertEqual(ba["iis_3"]["qty_now"], 90)
        self.assertEqual(ba["main"]["qty_now"], 149)
        self.assertAlmostEqual(ba["main"]["buy_total_rub"], 126761.75, places=2)
        self.assertAlmostEqual(ba["iis_3"]["coupons_rub"], 5497.2, places=2)
        self.assertEqual(ba["main"]["coupons_rub"], 0.0)       # купон — весь ИИС-3: на основном тогда 0 шт
        self.assertAlmostEqual(ba["main"]["market_value_rub"] + ba["iis_3"]["market_value_rub"], MV, delta=0.01)
        self.assertEqual(ba["main"]["first_trade_date"], "2026-10-26")
        self.assertEqual(rec["pnl_rub"], self.ps["SU26247RMFS5"]["pnl_rub"])       # верхний уровень — объединение
        self.assertAlmostEqual(rec["xirr"], 0.10, places=6)

    def test_main_result_follows_own_flows(self):
        ba = self._build(self.flows)["by_account"]
        main_pnl = 149 * 800.0 - 126761.75                  # только покупка 26.10 и своя доля терминала
        self.assertAlmostEqual(ba["main"]["pnl_rub"], main_pnl, delta=0.01)

    def test_partial_sell_on_main_and_coupon_between_buys(self):
        main = MAIN + [_t("Продажа", D(2026, 10, 27), 40000.0, 50)]
        iis = IIS + [_t("Покупка", D(2026, 6, 1), -10000.0, 10), _t("Купон", D(2026, 8, 1), 700.0, 100)]
        allt = sorted(iis + main, key=lambda t: t.date)
        pos = reconstruct_positions(allt, AS_OF)
        qty = sum(p.qty for p in pos.values())
        mv = qty * 800.0
        buy = 84836.7 + 126761.75 + 10000
        cp = 5497.2 + 700
        ps = {"SU26247RMFS5": {"qty_now": qty, "market_value_rub": mv, "buy_total_rub": buy, "sell_total_rub": 40000.0,
                               "coupons_rub": cp, "dividends_rub": 0.0, "pnl_rub": round(mv + 40000 + cp - buy, 2),
                               "cashflows": [(t.date.isoformat(), t.rub_amount) for t in allt] + [(AS_OF.isoformat(), mv)]}}
        rec = _build_per_instrument_xirr(ps, None, [], None, _flows(iis), AS_OF.isoformat())["SU26247RMFS5"]
        ba = rec["by_account"]
        self.assertEqual(ba["main"]["sell_total_rub"], 40000.0)
        self.assertEqual(ba["iis_3"]["sell_total_rub"], 0.0)
        self.assertEqual(ba["main"]["qty_now"], 99)
        self.assertEqual(ba["iis_3"]["qty_now"], 100)
        self.assertAlmostEqual(ba["main"]["pnl_rub"] + ba["iis_3"]["pnl_rub"], rec["pnl_rub"], delta=1.0)

    def test_only_on_one_account_has_no_by_account(self):
        ps = _per_security(IIS, 90, 90 * 800.0)
        rec = _build_per_instrument_xirr(ps, None, [], None, _flows(IIS), AS_OF.isoformat())["SU26247RMFS5"]
        self.assertNotIn("by_account", rec)

    def test_iis_flow_missing_from_total_is_skipped(self):
        ps = _per_security(MAIN, 149, 149 * 800.0)          # в сводной нет сделок ИИС-3
        rec = _build_per_instrument_xirr(ps, None, [], None, _flows(IIS), AS_OF.isoformat())["SU26247RMFS5"]
        self.assertNotIn("by_account", rec)

    def test_no_cashflows_in_per_security_degrades(self):
        self.ps["SU26247RMFS5"].pop("cashflows")
        self.assertNotIn("by_account", self._build(self.flows))


class CarriedFlows(unittest.TestCase):
    def setUp(self):
        self.ps = _per_security(sorted(IIS + MAIN, key=lambda t: t.date), 239, MV)
        self.flows = _flows(IIS)
        self.prev = {"iis_account_flows": {"file_last_operation": "2026-10-21", "flows": self.flows}}

    def test_resolve_sources(self):
        self.assertEqual(_resolve_iis_flows({"account_flows": self.flows, "file_last_operation": "2026-10-21"}, [])["source"], "export")
        r = _resolve_iis_flows(None, [{}, self.prev])
        self.assertEqual((r["source"], r["file_last_operation"]), ("carried", "2026-10-21"))
        self.assertEqual(_resolve_iis_flows(None, [{}])["source"], "none")

    def test_carried_with_matching_balance(self):
        holdings = [{"ticker": "SU26247RMFS5", "account": "iis_3", "qty": 90},
                    {"ticker": "SU26247RMFS5", "account": "main", "qty": 149}]
        stale = []
        rec = _build_per_instrument_xirr(self.ps, None, holdings, None, self.flows, AS_OF.isoformat(),
                                         iis_carried=True, stale_out=stale)["SU26247RMFS5"]
        self.assertEqual(stale, [])
        self.assertEqual(rec["by_account"]["iis_3"]["qty_now"], 90)

    def test_carried_new_iis_trade_after_transfer_date_flags_stale(self):
        holdings = [{"ticker": "SU26247RMFS5", "account": "iis_3", "qty": 110},     # ИИС-3 докупил после выгрузки
                    {"ticker": "SU26247RMFS5", "account": "main", "qty": 129}]
        stale = []
        rec = _build_per_instrument_xirr(self.ps, None, holdings, None, self.flows, AS_OF.isoformat(),
                                         iis_carried=True, stale_out=stale)["SU26247RMFS5"]
        self.assertEqual(stale, ["SU26247RMFS5"])
        self.assertNotIn("by_account", rec)


if __name__ == "__main__":
    unittest.main()

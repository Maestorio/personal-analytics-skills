#!/usr/bin/env python3
"""API-1b PR-3: checks.py — проверки целостности снапшота (блок / предупреждение / инфо).

Каждая проверка — срабатывание и несрабатывание на синтетике. Пороги откалиброваны
на реальной паре снапшотов 2026-10-13 → 2026-10-16 (120 позиций, 10 286 сделок):
на ней нет ни одного block и ни одного ложного warning. Живые случаи, ради которых
проверки устроены именно так:
  • ОФЗ 29027 (флоатер): MOEX не отдаёт ставку купона до фиксации, НКД есть →
    отсутствие ставки — info, а не warning; отсутствие НКД — warning;
  • RU000A10EST2: продана 28.09, а снапшот 13.10 её ещё держал → «пропала, продана
    раньше» — info, а не «пропала без сделки»;
  • точные дубли сделок законны (2020-03-06 ALRS: две одинаковые покупки) →
    дубликаты только среди операций ПОСЛЕ прошлого снапшота и только warning;
  • FINAMAR — ручная оценка владельца: без котировки MOEX законно, но в фонды
    ликвидности попасть не может (block).
Запуск: python3 skills/portfolio-data-loader/tests/test_snapshot_checks.py
"""
import copy
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import checks as ch  # noqa: E402


def H(ticker, qty=10, value=1000.0, account="main", asset="stock", status="normal", **kw):
    h = {"ticker": ticker, "account": account, "qty": qty, "value_rub": value, "asset_type": asset,
         "status": status, "sector": "banks_finance" if asset == "stock" else None,
         "current_price_source": "moex_iss", "current_price_ts": "2026-10-16 18:20:00"}
    if asset == "bond":
        h.update(accrued_int=10.0, coupon_pct=8.0)
    h.update(kw)
    return h


def SNAP(holdings=None, cash=500.0, have=None, as_of="2026-10-16", xirr=0.08):
    holdings = holdings if holdings is not None else [H("SBER"), H("OFZ1", asset="bond")]
    total = sum(h["value_rub"] or 0 for h in holdings if h["status"] != "blocked")
    return {
        "schema_version": "2.0", "as_of_date": as_of, "generated_at": f"{as_of}T18:00:00",
        "holdings": holdings, "data_quality_flags": [],
        "cash": {"total_rub": cash, "by_account": {"main": cash}, "cash_equiv_rub": 100.0,
                 "liquid_rub": cash + 100.0, "cash_equiv_tickers": {"TMON": 100.0}},
        "returns": {"restricted": {"xirr": xirr}},
        "balance_summary": {"summary": {"Имеется (RUB)": total + cash if have is None else have}},
        "status_summary": {"by_status": {"normal": {"pct": 100.0}, "blocked": {"pct": 0.0}}},
        "fx_rates_used": {"USD": {"rate": 83.76, "rate_date": as_of}},
    }


def TR(rows, last=None):
    t = ch.TradesInfo(n_rows=len(rows))
    t.rows = rows
    t.operations = Counter(r[2] for r in rows)
    t.currencies = Counter(r[5] if len(r) > 5 else "RUB" for r in rows)
    t.rows = [r[:5] for r in rows]
    if rows:
        t.first_date, t.last_date = min(r[0] for r in rows), last or max(r[0] for r in rows)
    return t


def ids(res, level=None):
    return sorted(r["id"] for r in res if level is None or r["level"] == level)


class Clean(unittest.TestCase):
    def test_clean_snapshot_has_no_block_or_warning(self):
        prev = SNAP(as_of="2026-10-13")
        res = ch.run_all(SNAP(), prev, trades_info=TR([("2026-01-10", "SBER", "Покупка", 10, 3000.0),
                                                        ("2026-10-15", "SBER", "Дивиденд", 10, 50.0)]),
                         as_of="2026-10-16")
        self.assertEqual(ids(res, "block") + ids(res, "warning"), [])


class Trades(unittest.TestCase):
    def run_t(self, rows, prev=True, **kw):
        return ch.run_all(SNAP(), SNAP(as_of="2026-10-13") if prev else None, trades_info=TR(rows, **kw),
                          as_of="2026-10-16")

    def test_unknown_operation_blocks(self):
        self.assertIn("trades_unknown_operation",
                      ids(self.run_t([("2026-10-15", "SBER", "Сплит", 10, 0.0)]), "block"))

    def test_unknown_currency_blocks(self):
        self.assertIn("trades_unknown_currency",
                      ids(self.run_t([("2026-10-15", "SBER", "Покупка", 1, 1.0, "KZT")]), "block"))

    def test_future_trade_blocks(self):
        self.assertIn("trades_future_date",
                      ids(self.run_t([("2026-10-17", "SBER", "Покупка", 1, 1.0)]), "block"))

    def test_empty_blocks(self):
        self.assertEqual(ids(self.run_t([]), "block"), ["trades_empty"])

    def test_stale_export_warns(self):
        self.assertIn("trades_stale", ids(self.run_t([("2026-09-30", "SBER", "Купон", 1, 1.0)]), "warning"))
        self.assertNotIn("trades_stale", ids(self.run_t([("2026-10-10", "SBER", "Купон", 1, 1.0)])))

    def test_duplicates_only_after_prev_snapshot(self):
        old = ("2020-03-06", "ALRS", "Покупка", 10.0, 702.36)
        new = ("2026-10-14", "SBER", "Покупка", 1.0, 300.0)
        self.assertNotIn("trades_duplicates_recent", ids(self.run_t([old, old, ("2026-10-15", "X", "Купон", 1, 1.0)])))
        self.assertIn("trades_duplicates_recent", ids(self.run_t([new, new]), "warning"))


class Positions(unittest.TestCase):
    def test_negative_qty_blocks(self):
        self.assertIn("holdings_negative_qty", ids(ch.run_all(SNAP([H("SBER", qty=-1)]), None), "block"))

    def test_stock_without_sector_warns_bond_does_not(self):
        res = ch.run_all(SNAP([H("NEWCO", sector=None), H("OFZ1", asset="bond")]), None)
        self.assertEqual(next(r for r in res if r["id"] == "stock_no_sector")["details"]["tickers"], ["NEWCO"])

    def test_gone_sold_after_prev_is_info(self):
        prev = SNAP([H("SBER"), H("GAZP")], as_of="2026-10-13")
        res = ch.run_all(SNAP([H("SBER")]), prev, as_of="2026-10-16",
                         trades_info=TR([("2026-10-14", "GAZP", "Продажа", 10, -1000.0)]))
        self.assertIn("holding_gone_sold", ids(res, "info"))
        self.assertNotIn("holding_gone_without_trade", ids(res))

    def test_gone_sold_before_prev_warns_backdated(self):   # ЭталонФин5 RU000A10EST2, inc-2026-10-21-1
        prev = SNAP([H("SBER"), H("RU000A10EST2", asset="bond")], as_of="2026-10-13")
        res = ch.run_all(SNAP([H("SBER")]), prev, as_of="2026-10-16",
                         trades_info=TR([("2026-09-28", "RU000A10EST2", "Продажа", 26, -23141.14),
                                         ("2026-10-15", "SBER", "Купон", 1, 1.0)]))
        self.assertIn("holding_gone_sold_earlier", ids(res, "warning"))

    def test_gone_without_trade_warns(self):
        prev = SNAP([H("SBER"), H("GAZP")], as_of="2026-10-13")
        res = ch.run_all(SNAP([H("SBER")]), prev, as_of="2026-10-16",
                         trades_info=TR([("2026-10-15", "SBER", "Купон", 1, 1.0)]))
        self.assertIn("holding_gone_without_trade", ids(res, "warning"))

    def test_split_like_and_qty_change(self):
        prev = SNAP([H("GMKN", qty=10), H("SBER", qty=10)], as_of="2026-10-13")
        cur = SNAP([H("GMKN", qty=1000, value=1000.0), H("SBER", qty=12, value=1200.0)])
        res = ch.run_all(cur, prev, as_of="2026-10-16", trades_info=TR([("2026-10-15", "X", "Купон", 1, 1.0)]))
        self.assertIn("qty_split_like", ids(res, "warning"))
        self.assertIn("qty_changed_without_trade", ids(res, "warning"))
        res2 = ch.run_all(cur, prev, as_of="2026-10-16",
                          trades_info=TR([("2026-10-15", "SBER", "Покупка", 2, 200.0),
                                          ("2026-10-15", "GMKN", "Корректировка", 990, 0.0)]))
        self.assertNotIn("qty_changed_without_trade", ids(res2))
        self.assertNotIn("qty_split_like", ids(res2))

    def test_trade_on_prev_snapshot_day_after_build_counts_as_trade(self):   # OZON 03.11: 87 → 58
        import trades_digest as td
        old = [("2026-10-01", "SBER", "Покупка", 10, 3000.0), ("2026-10-01", "GAZP", "Покупка", 10, 1500.0)]
        new = old + [("2026-10-13", "SBER", "Продажа", 4, -1200.0), ("2026-10-13", "GAZP", "Продажа", 10, -1500.0)]
        prev = SNAP([H("SBER", qty=10), H("GAZP")], as_of="2026-10-13")
        prev["trades_digest"] = td.from_rows(old, "2026-10-13")
        cur = SNAP([H("SBER", qty=6, value=600.0)])
        res = ch.run_all(cur, prev, as_of="2026-10-16", trades_info=TR(new))
        self.assertNotIn("qty_changed_without_trade", ids(res))
        self.assertNotIn("holding_gone_sold_earlier", ids(res))
        self.assertIn("holding_gone_sold", ids(res, "info"))
        self.assertIn("trades_on_prev_snapshot_day", ids(res, "info"))
        late = copy.deepcopy(prev)                                           # снапшот собран не в свой день
        late["generated_at"] = "2026-10-14T09:00:00"
        res2 = ch.run_all(cur, late, as_of="2026-10-16", trades_info=TR(new))
        self.assertIn("qty_changed_without_trade", ids(res2, "warning"))
        self.assertIn("holding_gone_sold_earlier", ids(res2, "warning"))

    def test_value_jump_without_trades(self):
        prev = SNAP([H("SBER", value=1000.0)], as_of="2026-10-13")
        res = ch.run_all(SNAP([H("SBER", value=1300.0)]), prev, as_of="2026-10-16")
        self.assertIn("value_jump", ids(res, "warning"))
        res = ch.run_all(SNAP([H("SBER", value=1200.0)]), prev, as_of="2026-10-16")
        self.assertNotIn("value_jump", ids(res))


class TradeIntegrity(unittest.TestCase):
    """Ошибки данных IntelInvest из разбора кэш-дрейфа 13→16.10 (PDL-RECON)."""
    BASE = [("2026-01-10", "RU000A105GN3", "Покупка", 2, 2000.0), ("2026-01-10", "SBER", "Покупка", 100, 30000.0)]

    def run_t(self, rows):
        return ch.run_all(SNAP(), None, trades_info=TR(self.BASE + rows), as_of="2026-10-16")

    def test_fractional_bond_trade_blocks(self):              # фантом Борца 18.09
        res = self.run_t([("2026-09-18", "RU000A105GN3", "Продажа", 1.992045846, -168346.4)])
        self.assertIn("bond_fractional_qty", ids(res, "block"))

    def test_fractional_coupon_of_replacement_bond_is_fine(self):   # RU000A10A869
        res = self.run_t([("2026-06-24", "RU000A10A869", "Купон", 74.620078431, 4757.03)])
        self.assertNotIn("bond_fractional_qty", ids(res))
        self.assertNotIn("payout_exceeds_holding", ids(res))

    def test_recent_money_correction_warns_old_or_small_not(self):
        self.assertIn("money_correction_recent",
                      ids(self.run_t([("2026-10-01", "Деньги (RUB)", "Корректировка", None, -183510.39)]), "warning"))
        self.assertNotIn("money_correction_recent",
                         ids(self.run_t([("2026-10-01", "Деньги (RUB)", "Корректировка", None, -8571.02)])))
        self.assertNotIn("money_correction_recent",
                         ids(self.run_t([("2026-06-29", "Деньги (RUB)", "Корректировка", None, 102072.0)])))
        self.assertNotIn("money_correction_recent",            # корректировка количества акций — не деньги
                         ids(self.run_t([("2026-10-01", "MDMG", "Корректировка", 10, 102072.0)])))

    def test_payout_exceeds_holding(self):                    # дубль TPAY 08.10
        dup = [("2026-10-08", "SBER", "Дивиденд", 100, 3300.0)] * 2
        r = [x for x in self.run_t(dup) if x["id"] == "payout_exceeds_holding"]
        self.assertEqual(r[0]["level"], "warning")
        self.assertTrue(r[0]["message_ru"].startswith("Похоже на дубли выплат"))
        self.assertIn("SBER · 08.10 · дивиденд · на руках 100 шт, выплачено на 200 шт: "
                      "3 300 ₽ × 100 шт; 3 300 ₽ × 100 шт", r[0]["message_ru"])
        self.assertIn("Что сделать: в IntelInvest оставить одну строку на дату", r[0]["message_ru"])
        it = r[0]["details"]["items"][0]
        self.assertEqual((it["ticker"], it["date"], it["held"], it["paid_qty"], it["kind"]),
                         ("SBER", "2026-10-08", 100, 200, "same_rows"))
        self.assertEqual([x["new"] for x in it["rows"]], [None, None])   # нет отпечатка прошлого снапшота

    def test_payout_in_parts_is_hinted(self):                 # DATA 24.06: 1200 + 1200 при 1200
        rows = [("2026-10-08", "SBER", "Дивиденд", 100, 2488.0), ("2026-10-08", "SBER", "Дивиденд", 100, 309.0)]
        r = [x for x in self.run_t(rows) if x["id"] == "payout_exceeds_holding"]
        self.assertEqual(r[0]["level"], "warning")              # подозрение, не блок
        self.assertNotIn("возможно, выплата частями", r[0]["message_ru"])   # не повторяется у каждой бумаги
        self.assertEqual(r[0]["message_ru"].count("Если брокер платил частями"), 1)
        self.assertEqual(r[0]["details"]["items"][0]["kind"], "parts_possible")
        self.assertIn("2 488 ₽ × 100 шт; 309 ₽ × 100 шт", r[0]["message_ru"])

    def test_two_accounts_same_day_is_fine(self):             # ПГК 80 + 30 на двух счетах
        rows = [("2026-07-13", "SBER", "Дивиденд", 80, 100.0), ("2026-07-13", "SBER", "Дивиденд", 20, 25.0)]
        self.assertNotIn("payout_exceeds_holding", ids(self.run_t(rows)))


class Cash(unittest.TestCase):
    def test_negative_cash_blocks(self):
        self.assertIn("cash_negative", ids(ch.run_all(SNAP(cash=-1.0), None), "block"))

    def test_liquid_mismatch_warns(self):
        s = SNAP()
        s["cash"]["liquid_rub"] += 50
        self.assertIn("cash_liquid_mismatch", ids(ch.run_all(s, None), "warning"))

    def test_finamar_in_cash_equiv_blocks(self):
        s = SNAP()
        s["cash"]["cash_equiv_tickers"]["FINAMAR"] = 1.0
        self.assertIn("cash_equiv_wrong_ticker", ids(ch.run_all(s, None), "block"))


class Quotes(unittest.TestCase):
    def test_non_moex_share_and_manual_valuation(self):
        hs = [H(f"S{i}") for i in range(9)] + [H("FINAMAR", asset="fund", current_price_source="cost_basis")]
        self.assertNotIn("quotes_non_moex", ids(ch.run_all(SNAP(hs), None)))
        hs[0]["current_price_source"] = "last_trade_price"
        hs[1]["current_price_source"] = "last_trade_price"
        self.assertIn("quotes_non_moex", ids(ch.run_all(SNAP(hs), None), "warning"))

    def test_stale_quote_and_fx(self):
        s = SNAP([H("SBER", current_price_ts="2026-10-09 18:00:00")])
        s["fx_rates_used"]["USD"]["rate_date"] = "2026-10-01"
        res = ids(ch.run_all(s, None), "warning")
        self.assertIn("quotes_stale", res)
        self.assertIn("fx_stale", res)

    def test_floater_without_coupon_is_info_without_accrued_warns(self):   # ОФЗ 29027
        s = SNAP([H("RU000A10AA93", asset="bond", coupon_pct=None, plan_subtype="Флоат")])
        res = ch.run_all(s, None)
        self.assertIn("bonds_missing_coupon_pct", ids(res, "info"))
        self.assertNotIn("bonds_missing_accrued", ids(res))
        s = SNAP([H("OFZ1", asset="bond", accrued_int=None)])
        self.assertIn("bonds_missing_accrued", ids(ch.run_all(s, None), "warning"))


class Snapshot(unittest.TestCase):
    def test_schema_and_as_of(self):
        s = SNAP()
        s["schema_version"] = "1.0"
        self.assertIn("schema", ids(ch.run_all(s, None), "block"))
        self.assertIn("as_of_mismatch", ids(ch.run_all(SNAP(), None, as_of="2026-10-17"), "block"))

    def test_non_finite_blocks(self):
        s = SNAP()
        s["returns"]["restricted"]["xirr"] = float("nan")
        self.assertIn("non_finite", ids(ch.run_all(s, None), "block"))

    def test_balance_invariant(self):
        self.assertNotIn("balance_invariant", ids(ch.run_all(SNAP(), None)))
        self.assertIn("balance_invariant", ids(ch.run_all(SNAP(have=99999.0), None), "block"))

    def test_blocked_holdings_excluded_from_invariant(self):
        hs = [H("SBER"), H("FXUS", value=0.0, status="blocked")]
        self.assertNotIn("balance_invariant", ids(ch.run_all(SNAP(hs), None)))

    def test_xirr_range(self):
        self.assertIn("xirr_out_of_range", ids(ch.run_all(SNAP(xirr=5.0), None), "warning"))

    def test_plan_check_warnings(self):                       # этап 1 ухода от Numbers
        s = SNAP()
        self.assertNotIn("plan_mismatch", ids(ch.run_all(s, None)))
        s["plan_check"] = {"source": "both", "n_diff": 2,
                           "diff": [{"path": "stocks.A.plan_pct"}, {"path": "classes.Акции.share"}]}
        res = ch.run_all(s, None)
        self.assertIn("plan_mismatch", ids(res, "warning"))
        self.assertIn("stocks.A.plan_pct", [r for r in res if r["id"] == "plan_mismatch"][0]["message_ru"])
        s["plan_check"] = {"source": "plan_primary", "n_diff": 2,
                           "diff": [{"path": "stocks.A.plan_pct"}, {"path": "classes.Акции.share"}]}
        res = ch.run_all(s, None)
        self.assertNotIn("plan_mismatch", ids(res))
        self.assertIn("numbers_stale", ids(res, "warning"))
        self.assertIn("Numbers отстаёт от плана на сайте по 2 полям: stocks.A.plan_pct",
                      [r for r in res if r["id"] == "numbers_stale"][0]["message_ru"])
        s["plan_check"] = {"source": "plan_primary", "n_diff": 0, "diff": []}
        self.assertNotIn("numbers_stale", ids(ch.run_all(s, None)))
        s["plan_check"] = {"source": "error", "error": "битый"}
        self.assertIn("plan_unreadable", ids(ch.run_all(s, None), "warning"))

    def test_results_sorted_block_first(self):
        res = ch.run_all(SNAP(cash=-1.0, xirr=5.0), None)
        self.assertEqual(res[0]["level"], "block")


if __name__ == "__main__":
    unittest.main(verbosity=1)

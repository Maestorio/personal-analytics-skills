#!/usr/bin/env python3
"""Доходность по цене MOEX, а не по последней сделке (2026-10-23).

Случай 2026-10-22: скилл в окружении Claude — MOEX ISS отвечал не на всё, portfolio_returns оценил
TGLD по 14,58 ₽ (последняя покупка 20.08) вместо 12,96 ₽ MOEX: стоимость +47,8 тыс. ₽, XIRR завышен
на 0,26–0,31 п.п., кэш занижен — без единого предупреждения. Контракт:
  • _returns_price_fallbacks находит акцию/фонд, оценённые в доходности НЕ по MOEX, когда в holdings
    у той же бумаги котировка MOEX есть; внебиржевой FINAMAR, заблокированные и бумаги без котировки
    MOEX — не ошибка;
  • облигация с котировкой MOEX в holdings (любой счёт), оценённая в доходности не по MOEX, — тоже
    ошибка (PDL-16, 27.10: юаневые облигации не запрашивались — сделки в CNY), цена MOEX не сравнивается;
  • assemble ставит флаг error returns_price_not_moex с бумагой, ценами и разницей в рублях;
  • checks превращает его в блок записи (сайт не даст сохранить, скилл — Шаг 7 «любой error»).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import assemble_snapshot as asm  # noqa: E402
import checks as ch  # noqa: E402


def pos(t, typ, qty, value, src, blocked=False):
    return {"ticker": t, "type": typ, "qty": qty, "value_rub": value, "price_source": src, "is_blocked": blocked}


def hold(t, typ, price, src="moex_iss", account="main"):
    return {"ticker": t, "asset_type": typ, "current_price": price, "current_price_source": src, "account": account}


RETURNS = {"snapshot_current": {"positions": [
    pos("TGLD", "fund", 29500, 430110.0, "last_trade_price"),      # ошибка: MOEX есть
    pos("SBER", "stock", 100, 29000.0, "moex"),                    # норма
    pos("FINAMAR", "fund", 1, 150000.0, "cost_basis"),             # внебиржевой — норма
    pos("JPM", "stock", 2, 0.0, "blocked_zero", blocked=True),     # заблокированная — норма
    pos("RU000A10F108", "bond", 12, 11790.0, "last_trade_price"),  # облигации — вне проверки
    pos("NEWCO", "stock", 10, 1000.0, "last_trade_price"),         # нет котировки MOEX в holdings
]}}
HOLDINGS = [hold("TGLD", "fund", 12.96), hold("SBER", "stock", 290.0), hold("FINAMAR", "fund", 150000.0, "manual"),
            hold("NEWCO", "stock", 100.0, "last_trade")]


class Fallbacks(unittest.TestCase):
    def test_only_tgld_case(self):
        fb = asm._returns_price_fallbacks(RETURNS, HOLDINGS)
        self.assertEqual([x["ticker"] for x in fb], ["TGLD"])
        self.assertEqual((fb[0]["used_price"], fb[0]["moex_price"], fb[0]["diff_rub"]), (14.58, 12.96, 47790.0))

    def test_iis_quote_not_used_for_main(self):
        self.assertEqual(asm._returns_price_fallbacks(RETURNS, [hold("TGLD", "fund", 12.96, account="iis_3")]), [])

    def test_bond_with_moex_quote(self):
        # PDL-16: облигация в holdings с котировкой MOEX (в % номинала), в доходности — последняя сделка
        bond = {"ticker": "RU000A108FX8", "isin": "RU000A108FX8", "asset_type": "bond", "current_price": 99.9999,
                "current_price_source": "moex_iss", "account": "main"}
        rets = {"snapshot_current": {"positions": [
            pos("RU000A108FX8", "bond", 13, 153118.63, "last_trade_price+fx_registry"),
            pos("RU000A10F108", "bond", 12, 142281.72, "moex"),
        ]}}
        fb = asm._returns_price_fallbacks(rets, HOLDINGS + [bond])
        self.assertEqual([(x["ticker"], x["moex_price"]) for x in fb], [("RU000A108FX8", None)])
        snap = {"returns": rets}
        orig = asm._returns_price_fallbacks
        try:
            asm._returns_price_fallbacks = lambda r, h: orig(rets, HOLDINGS + [bond])
            snap = asm.assemble(None, {"snapshot_current": rets["snapshot_current"]}, None, {}, as_of="2026-10-27")
        finally:
            asm._returns_price_fallbacks = orig
        msg = [f["message"] for f in snap["data_quality_flags"] if f["code"] == "returns_price_not_moex"]
        self.assertTrue(msg and "RU000A108FX8 (облигация) — цена последней сделки, 11 778.36 ₽ за бумагу" in msg[0], msg)

    def test_no_returns_or_holdings(self):
        self.assertEqual(asm._returns_price_fallbacks(None, HOLDINGS), [])
        self.assertEqual(asm._returns_price_fallbacks(RETURNS, None), [])


class FlagAndBlock(unittest.TestCase):
    def test_error_flag_blocks_write(self):
        flag = asm._flag("returns_prices", "error", "returns_price_not_moex", "TGLD — цена последней сделки")
        snap = {"data_quality_flags": [flag]}
        res = ch.check_snapshot(ch.Ctx(snap=snap, prev=None, trades=None, as_of="2026-10-22"))
        self.assertIn("returns_price_not_moex", [r["id"] for r in res if r["level"] == "block"])

    def test_assemble_message(self):
        # assemble ставит флаг по returns + holdings: подменяем сборку позиций готовыми holdings
        orig = asm._returns_price_fallbacks
        try:
            seen = {}

            def spy(returns, holdings):
                seen["called"] = True
                return orig(RETURNS, HOLDINGS)
            asm._returns_price_fallbacks = spy
            snap = asm.assemble(None, {"snapshot_current": RETURNS["snapshot_current"]}, None, {}, as_of="2026-10-22")
        finally:
            asm._returns_price_fallbacks = orig
        msg = [f for f in snap["data_quality_flags"] if f["code"] == "returns_price_not_moex"]
        self.assertTrue(seen.get("called") and msg and msg[0]["severity"] == "error")
        self.assertIn("TGLD — цена последней сделки 14.58 ₽ вместо 12.96 ₽ MOEX (+47 790 ₽)", msg[0]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

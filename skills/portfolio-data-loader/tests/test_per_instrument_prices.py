#!/usr/bin/env python3
"""Одна цена в holdings и per_instrument_xirr (2026-10-27).

Случай 2026-10-27: снапшот собран скиллом в облачной среде без «Общего баланса». Шаг per_security_xirr
сам ходил в MOEX одной попыткой (health_check без повторов), при сбое молча взял цену последней сделки
по всем 80 бумагам, а holdings шли по котировкам moex_quotes.py (две попытки): NVTK 342 899,4 ₽ вместо
296 676 ₽ (82 шт × 3621), XIRR 26,1% вместо 22,7%. Контракт:
  • _per_instrument_price_check: акция/фонд в per_instrument_xirr с price_source не moex при MOEX-цене в
    holdings → fallbacks (шесть тикеров 27.10 — все); источник moex, но цена расходится с holdings > 0,5% →
    mismatches; FINAMAR, облигации, alias_of, qty_now 0, бумаги без MOEX в holdings и котировка только
    ИИС-3 — вне проверки;
  • assemble ставит флаг error per_instrument_price_not_moex, checks.check_snapshot блокирует запись;
  • per_security_xirr(quotes=…) берёт цены из quotes.json без сети, в MOEX ISS идёт только за бумагами
    вне quotes; use_moex=False игнорирует quotes (фолбэк last_trade_price);
  • moex_prices_from_quotes разбирает котировку как fetch_moex_prices: SUR→RUB, prev_close при пустом last,
    НКД только при расчётах в SUR/RUB.
"""
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import assemble_snapshot as asm  # noqa: E402
import checks as ch  # noqa: E402
import per_security_xirr as psx  # noqa: E402
import portfolio_returns as pr  # noqa: E402


def pi(qty, mv, src="last_trade", **kw):
    return {"qty_now": qty, "market_value_rub": mv, "price_source": src, **kw}


def hold(t, typ, price, src="moex_iss", account="main"):
    return {"ticker": t, "asset_type": typ, "current_price": price, "current_price_source": src, "account": account}


# Реальные числа 27.10: (qty, market_value при last_trade, цена MOEX в holdings)
CASE = {"NVTK": (82, 342899.4, 3621.0), "YDEX": (129, 1679773.5, 10536.0), "GMKN": (3120, 477360.0, 116.18),
        "GLRX": (4650, 285696.0, 39.38), "X5": (133, 781840.5, 7026.0), "OZON": (87, 812754.0, 10761.0)}
PI_1027 = {t: pi(q, mv) for t, (q, mv, _p) in CASE.items()}
HOLD_1027 = [hold(t, "stock", p) for t, (_q, _mv, p) in CASE.items()]


class Check(unittest.TestCase):
    def test_all_six_cases_are_fallbacks(self):
        fb, mm = asm._per_instrument_price_check(PI_1027, HOLD_1027)
        self.assertEqual(sorted(x["ticker"] for x in fb), sorted(CASE))
        self.assertEqual(mm, [])
        nvtk = next(x for x in fb if x["ticker"] == "NVTK")
        self.assertAlmostEqual(nvtk["diff_rub"], 342899.4 - 82 * 3621.0, places=2)   # +45 977.4
        self.assertEqual((nvtk["used_price"], nvtk["moex_price"]), (4181.7, 3621.0))

    def test_moex_source_is_clean(self):
        per = {t: pi(q, q * p, "moex_iss") for t, (q, _mv, p) in CASE.items()}
        self.assertEqual(asm._per_instrument_price_check(per, HOLD_1027), ([], []))

    def test_mismatch_threshold(self):
        h = [hold("NVTK", "stock", 3621.0)]
        fb, mm = asm._per_instrument_price_check({"NVTK": pi(82, 82 * 3621.0 * 1.01, "moex_iss")}, h)
        self.assertEqual(fb, [])
        self.assertEqual([x["ticker"] for x in mm], ["NVTK"])
        self.assertAlmostEqual(mm[0]["diff_pct"], 1.0, places=2)
        self.assertEqual(asm._per_instrument_price_check({"NVTK": pi(82, 82 * 3621.0 * 1.003, "moex_iss")}, h),
                         ([], []))

    def test_exclusions(self):
        per = {
            "FINAMAR": pi(1, 450000.0, "cost_basis"),
            "RU000A10F108": pi(12, 35370.0),                     # облигация без qty/value в holdings — не сверяется
            "ALIAS": pi(10, 15000.0, alias_of="SBER"),
            "ZERO": pi(0, 0.0),
            "NOMOEX": pi(10, 3000.0),
            "IISONLY": pi(10, 3000.0),
        }
        holdings = [hold("FINAMAR", "fund", 450000.0), hold("RU000A10F108", "bond", 98.2),
                    hold("ALIAS", "stock", 100.0), hold("ZERO", "stock", 100.0),
                    hold("NOMOEX", "stock", 100.0, "last_trade"), hold("IISONLY", "stock", 50.0, account="iis_3")]
        self.assertEqual(asm._per_instrument_price_check(per, holdings), ([], []))

    def test_bond_unit_value(self):
        # PDL-16 (27.10): ЕСЭГ1PC5 — per_instrument по MOEX 478 068 ₽, holdings (последняя сделка) 459 357 ₽
        bond = {**hold("RU000A108FX8", "bond", 99.9999), "qty": 13, "value_rub": 459355.89}
        per = {"RU000A108FX8": pi(13, 478068.99, "moex_iss", isin="RU000A108FX8"),
               "SU26238RMFS4": pi(210, 630000.0, "moex_iss", isin="RU000A1038V6"),   # ключ SECID, сверка по ISIN
               "RU000A1038V6": pi(210, 630000.0, "moex_iss", alias_of="SU26238RMFS4")}
        ofz = {**hold("RU000A1038V6", "bond", 70.0), "qty": 80, "value_rub": 240000.0}   # основной счёт из двух
        fb, mm = asm._per_instrument_price_check(per, [bond, ofz])
        self.assertEqual(fb, [])
        self.assertEqual([(x["ticker"], x["diff_pct"]) for x in mm], [("RU000A108FX8", 4.07)])
        ofz_off = {**ofz, "value_rub": 246000.0}                                            # +2,5 % на бумагу
        self.assertEqual([x["ticker"] for x in asm._per_instrument_price_check(per, [ofz_off])[1]], ["SU26238RMFS4"])

    def test_empty_inputs(self):
        self.assertEqual(asm._per_instrument_price_check(None, HOLD_1027), ([], []))
        self.assertEqual(asm._per_instrument_price_check(PI_1027, None), ([], []))


def _write_trades(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(("intelinvest.ru",) + (None,) * 12)
    ws.append(("Тикер", "Название", "Операция", "Дата", "Кол-во", "Цена", "Номинал", "НКД", "Комиссия",
               "Сумма", "Сумма без комиссии", "Валюта", "Заметка"))
    ws.append(("Деньги (RUB)", "Российский рубль", "Внесение", "2026-01-12", None, None, None, None, 0.0,
               1500000.0, 1500000.0, "RUB", "зачисление"))
    for tk, nm, q, pr_ in (("NVTK", "Новатэк", 82, 3000.0), ("SBER", "Сбербанк", 100, 280.0)):
        ws.append((tk, nm, "Покупка", "2026-01-13", float(q), pr_, None, None, 0.0, q * pr_, q * pr_, "RUB", None))
        ws.append(("Деньги (RUB)", "Российский рубль", "Списание", "2026-01-13", None, None, None, None, 0.0,
                   -q * pr_, -q * pr_, "RUB", "за сделку"))
    wb.save(path)


class PerSecurityQuotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.trades = str(Path(cls.tmp) / "trades.xlsx")
        _write_trades(cls.trades)
        cls.orig = psx.fetch_moex_prices

    def tearDown(self):
        psx.fetch_moex_prices = self.orig

    def run_psx(self, **kw):
        return psx.per_security_xirr(["NVTK", "SBER"], self.trades, dt.date(2026, 10, 27),
                                     cbr_offline=True, **kw)

    def test_no_moex_gives_last_trade_and_blocks(self):
        # «--no-moex» / сбой ISS: цена последней сделки; assemble при holdings по MOEX — error и блок записи
        def boom(*a, **k):
            raise AssertionError("сеть при use_moex=False")
        psx.fetch_moex_prices = boom
        res = self.run_psx(use_moex=False, quotes={"NVTK": {"last": 3621.0}})
        self.assertEqual(res["NVTK"]["price_source"], "last_trade_price")
        self.assertEqual(res["NVTK"]["market_value_rub"], 82 * 3000.0)       # quotes проигнорирован
        holdings = [hold("NVTK", "stock", 3621.0), hold("SBER", "stock", 290.0)]
        # assemble берёт holdings из баланса; подменяем сверку на ту же функцию с готовыми holdings
        orig = asm._per_instrument_price_check
        try:
            asm._per_instrument_price_check = lambda per_instr, _h: orig(per_instr, holdings)
            snap = asm.assemble(None, {}, res, {}, as_of="2026-10-27")
        finally:
            asm._per_instrument_price_check = orig
        flags = [f for f in snap["data_quality_flags"] if f["code"] == "per_instrument_price_not_moex"]
        self.assertTrue(flags and flags[0]["severity"] == "error")
        self.assertIn("NVTK — цена последней сделки 3000 ₽ вместо 3621 ₽ MOEX", flags[0]["message"])
        out = ch.check_snapshot(ch.Ctx(snap=snap, prev=None, trades=None, as_of="2026-10-27"))
        self.assertIn("per_instrument_price_not_moex", [r["id"] for r in out if r["level"] == "block"])

    def test_quotes_used_without_network(self):
        def boom(*a, **k):
            raise AssertionError("сеть вызвана, хотя все бумаги в quotes")
        psx.fetch_moex_prices = boom
        res = self.run_psx(use_moex=True, quotes={"NVTK": {"last": 3621.0}, "SBER": {"last": 290.0}})
        self.assertEqual(res["NVTK"]["market_value_rub"], 82 * 3621.0)
        self.assertEqual(res["NVTK"]["price_source"], "moex")
        self.assertEqual(res["SBER"]["market_value_rub"], 100 * 290.0)

    def test_network_only_for_missing(self):
        calls = []

        def fake(secids, verbose=False, accrued_out=None):
            calls.append(list(secids))
            return {"SBER": 291.0}, {}, {}, set()
        psx.fetch_moex_prices = fake
        res = self.run_psx(use_moex=True, quotes={"NVTK": {"last": 3621.0}})
        self.assertEqual(calls, [["SBER"]])
        self.assertEqual(res["NVTK"]["market_value_rub"], 82 * 3621.0)
        self.assertEqual(res["SBER"]["market_value_rub"], 100 * 291.0)
        self.assertEqual(res["SBER"]["price_source"], "moex")

    def test_cli_accepts_bare_dict_and_wrapped(self):
        import json
        import subprocess
        for name, body in (("wrapped", {"quotes": {"NVTK": {"last": 3621.0}, "SBER": {"last": 290.0}}}),
                           ("bare", {"NVTK": {"last": 3621.0}, "SBER": {"last": 290.0}})):
            q = Path(self.tmp) / f"{name}.json"
            q.write_text(json.dumps(body), encoding="utf-8")
            p = subprocess.run([sys.executable, str(Path(psx.__file__)), "--trades", self.trades, "--tickers",
                                "NVTK", "--as-of", "2026-10-27", "--cbr-offline", "--format", "json",
                                "--no-cashflows", "--quotes", str(q)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)["NVTK"]["market_value_rub"], 82 * 3621.0, name)


class FromQuotes(unittest.TestCase):
    def test_parse(self):
        q = {
            "SU1": {"last": None, "prev_close": 97.5, "face_value": 3000, "currency": "SUR",
                    "settle_currency": "SUR", "accrued_interest": 12.3},
            "USDB": {"last": 99.0, "face_value": 3000, "currency": "USD", "settle_currency": "USD",
                     "accrued_interest": 5.0},
            "EMPTY": {"last": None, "prev_close": None, "currency": "SUR"},
        }
        acc = {}
        lp, fv, fc, failed = pr.moex_prices_from_quotes(q, ["SU1", "USDB", "EMPTY", "ABSENT"], accrued_out=acc)
        self.assertEqual(lp, {"SU1": 97.5, "USDB": 99.0})
        self.assertEqual(fc["SU1"], "RUB")           # SUR → RUB
        self.assertEqual(fc["USDB"], "USD")
        self.assertEqual(fv, {"SU1": 3000.0, "USDB": 3000.0})
        self.assertEqual(acc, {"SU1": 12.3})         # НКД только при расчётах в SUR/RUB
        self.assertEqual(failed, {"EMPTY", "ABSENT"})


if __name__ == "__main__":
    unittest.main()

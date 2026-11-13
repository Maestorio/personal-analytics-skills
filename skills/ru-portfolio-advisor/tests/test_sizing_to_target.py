#!/usr/bin/env python3
"""
test_sizing_to_target.py — тесты scripts/sizing_to_target.py («довести долю бумаги до N %»).

Синтетический снапшот: фонд на основном счёте, бумага на двух счетах (main + iis_3), акция с лотом 10,
облигация, заблокированная позиция. Проверяются базы (nav / all / class), знак и округление до лота
(покупка вниз, продажа вверх), цена из --quotes, ошибки входа (exit 2 без traceback).

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_sizing_to_target.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
SCRIPT = os.path.join(SCRIPTS, "sizing_to_target.py")
sys.path.insert(0, SCRIPTS)
import sizing_to_target as stt  # noqa: E402


def _h(ticker, atype, value, qty, price, account="main", lot=None, blocked=False):
    return {"ticker": ticker, "asset_type": atype, "value_rub": value, "qty": qty, "current_price": price,
            "account": account, "lot_size": lot, "is_blocked": blocked, "current_price_source": "moex_iss"}


def snap():
    # main: FUND 100 000 (1000 шт × 100), SHR 200 000 (20 × 10 000, лот 10) + IIS 50 000 (5 шт),
    # BND 300 000, STK 150 000 (лот 10), BLK заблокирована; кэш main 250 000 -> NAV без ИИС-3 = 1 000 000
    return {
        "as_of_date": "2026-01-01",
        "balance_summary": {"total_current_rub_excl_iis": 1_000_000.0, "total_current_rub_incl_iis": 1_100_000.0},
        "holdings": [
            _h("FUND", "fund", 100_000.0, 1000.0, 100.0),
            _h("SHR", "fund", 200_000.0, 20.0, 10_000.0),
            _h("SHR", "fund", 50_000.0, 5.0, 10_000.0, account="iis_3"),
            _h("BND", "bond", 300_000.0, 300.0, 1000.0),
            _h("STK", "stock", 150_000.0, 150.0, 1000.0, lot=10),
            _h("BLK", "stock", 999_999.0, 1.0, 999_999.0, blocked=True),
        ],
    }


def run_cli(args, snapshot=None):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot or snap(), f)
        full = [sys.executable, SCRIPT, "--snapshot", path] + [a.replace("<S>", path) for a in args]
        return subprocess.run(full, capture_output=True, text=True)


class TestTargets(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(stt.parse_targets(["A=4,B=2"]), [("A", 4.0), ("B", 2.0)])
        self.assertEqual(stt.parse_targets(["A=2.5", "B=1"]), [("A", 2.5), ("B", 1.0)])

    def test_bad(self):
        for raw in (["A"], ["A=x"], ["A=100"], ["A=-1"], []):
            with self.assertRaises(stt.SizingError):
                stt.parse_targets(raw)


class TestNavBase(unittest.TestCase):
    def test_buy_fund_to_pct(self):
        r = stt.compute_one(snap(), "FUND", 15.0, "nav", {})
        self.assertEqual(r["base_rub"], 1_000_000.0)
        self.assertEqual(r["current_pct"], 10.0)
        self.assertEqual(r["delta_rub"], 50_000.0)
        self.assertEqual(r["direction"], "buy")
        self.assertEqual((r["lots"], r["units"]), (500, 500))
        self.assertEqual(r["qty_after"], 1500.0)
        self.assertFalse(r["lot_known"])

    def test_lot_rounding_buy_down(self):
        # SHR на main 200 000 = 20 %; цель 21,5 % -> +15 000 ₽ при цене 10 000 -> 1 шт (вниз), остаток 5 000
        r = stt.compute_one(snap(), "SHR", 21.5, "nav", {})
        self.assertEqual(r["delta_rub"], 15_000.0)
        self.assertEqual((r["lots"], r["remainder_rub"]), (1, 5_000.0))

    def test_sell_rounds_up(self):
        r = stt.compute_one(snap(), "SHR", 18.5, "nav", {})
        self.assertEqual(r["delta_rub"], -15_000.0)
        self.assertEqual(r["direction"], "sell")
        self.assertEqual((r["lots"], r["remainder_rub"]), (2, -5_000.0))
        self.assertEqual(r["qty_after"], 18.0)

    def test_stock_lot_size(self):
        # STK 15 %, цель 20 % -> +50 000; лот = 10 × 1000 = 10 000 ₽ -> 5 лотов = 50 шт
        r = stt.compute_one(snap(), "STK", 20.0, "nav", {})
        self.assertEqual((r["lots"], r["units"], r["lot_known"]), (5, 50, True))

    def test_two_accounts(self):
        main = stt.compute_one(snap(), "SHR", 20.0, "nav", {})
        self.assertEqual(main["current_rub"], 200_000.0)
        self.assertEqual(main["other_accounts_rub"], 50_000.0)
        self.assertEqual(main["accounts"], ["main"])
        allb = stt.compute_one(snap(), "SHR", 20.0, "all", {})
        self.assertEqual(allb["current_rub"], 250_000.0)
        self.assertEqual(allb["base_rub"], 1_100_000.0)
        self.assertEqual(allb["accounts"], ["iis_3", "main"])
        self.assertEqual(allb["other_accounts_rub"], 0.0)

    def test_zero_delta(self):
        r = stt.compute_one(snap(), "FUND", 10.0, "nav", {})
        self.assertEqual(r["direction"], "none")
        self.assertIsNone(r["lots"])

    def test_quotes_override(self):
        with tempfile.TemporaryDirectory() as d:
            q = os.path.join(d, "q.json")
            json.dump({"items": {"FUND": {"price": 200.0, "lot_size": 5}}}, open(q, "w"))
            quotes = stt.load_quotes(q)
        r = stt.compute_one(snap(), "FUND", 15.0, "nav", quotes)
        # +50 000 при лоте 5 × 200 = 1000 ₽ -> 50 лотов = 250 шт
        self.assertEqual((r["lots"], r["units"], r["price"], r["lot_known"]), (50, 250, 200.0, True))


class TestClassBase(unittest.TestCase):
    def test_class_base_stock_excludes_blocked(self):
        r = stt.compute_one(snap(), "STK", 50.0, "class", {})
        self.assertEqual(r["base_rub"], 150_000.0)  # заблокированная BLK не входит
        self.assertEqual(r["direction"], "sell")    # единственная акция класса: 100 % -> срез в ноль
        self.assertEqual(r["share_after_pct"], 0.0)  # без деления на ноль

    def test_class_formula_buy_grows_base(self):
        # FUND 100 000 из класса 300 000; цель 50 %: (0,5·300 000 − 100 000)/0,5 = +100 000; после 200 000/400 000
        r = stt.compute_one(snap(), "FUND", 50.0, "class", {})
        self.assertEqual(r["delta_rub"], 100_000.0)
        self.assertEqual((r["lots"], r["share_after_pct"]), (1000, 50.0))

    def test_class_bond(self):
        r = stt.compute_one(snap(), "BND", 50.0, "class", {})
        self.assertEqual(r["base_rub"], 300_000.0)
        self.assertEqual(r["current_pct"], 100.0)

    def test_class_fund_excludes_iis(self):
        r = stt.compute_one(snap(), "FUND", 50.0, "class", {})
        self.assertEqual(r["base_rub"], 300_000.0)  # FUND 100 000 + SHR(main) 200 000


class TestCli(unittest.TestCase):
    def test_text_has_base_line(self):
        p = run_cli(["--ticker", "FUND=15"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("База: NAV без ИИС-3"))
        self.assertIn("1 000 000 ₽", p.stdout)
        self.assertIn("Докупить на 50 000 ₽", p.stdout)

    def test_stock_reminder(self):
        p = run_cli(["--ticker", "STK=20"])
        self.assertIn("gate_aware_sizing.py", p.stdout)
        self.assertNotIn("gate_aware_sizing.py", run_cli(["--ticker", "FUND=15"]).stdout)

    def test_json_and_multiple_targets(self):
        p = run_cli(["--ticker", "FUND=15,FUND=5", "--json"])
        d = json.loads(p.stdout)
        self.assertEqual([i["direction"] for i in d["items"]], ["buy", "sell"])
        self.assertEqual(d["base"], "nav")

    def test_errors_exit_2_no_traceback(self):
        cases = [["--ticker", "NOPE=4"], ["--ticker", "FUND"], ["--ticker", "BLK=4"],
                 ["--ticker", "FUND=4", "--quotes", "/no/such.json"], ["--ticker", "FUND=150"]]
        for args in cases:
            p = run_cli(args)
            self.assertEqual(p.returncode, 2, args)
            self.assertNotIn("Traceback", p.stderr)
            self.assertIn("Ошибка", p.stderr)

    def test_missing_snapshot(self):
        p = subprocess.run([sys.executable, SCRIPT, "--snapshot", "/no/such.json", "--ticker", "A=1"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)

    def test_snapshot_without_nav(self):
        s = snap()
        del s["balance_summary"]["total_current_rub_excl_iis"]
        p = run_cli(["--ticker", "FUND=15"], snapshot=s)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)

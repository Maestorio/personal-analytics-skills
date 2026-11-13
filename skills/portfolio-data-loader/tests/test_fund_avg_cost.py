#!/usr/bin/env python3
"""Средняя цена фондов в holdings (2026-10-28): _build_funds пишет avg_cost_rub/avg_cost_source.

Контракт: колонка баланса «Ср, Цена» → "balance"; иначе средняя из сделок (returns.snapshot_current
positions[type=fund].avg_cost_rub) → "trades"; нет ни того ни другого → None/None — подмены
value/qty (текущей цены) у фондов нет. Дефект: до правки поле фондам не писалось вовсе
(снапшот 27.10: TPAY/TGLD/TLCB без средней при наличии сделок), карточка фонда во вьюере
показывала «по покупкам» вместо точной средней.
Запуск: python3 skills/portfolio-data-loader/tests/test_fund_avg_cost.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from assemble_snapshot import _build_funds, _fund_avg_cost  # noqa: E402


def _returns(**funds):
    return {"snapshot_current": {"positions": [
        {"ticker": t, "type": "fund", "qty": q, "value_rub": v, "avg_cost_rub": a, "name": t}
        for t, (q, v, a) in funds.items()]}}


class TestFundAvgCost(unittest.TestCase):
    def test_balance_column_wins(self):
        avg, src = _fund_avg_cost({"Тикер": "TPAY", "Ср, Цена": 97.5}, {"avg_cost_rub": 90.0})
        self.assertEqual((avg, src), (97.5, "balance"))

    def test_trades_when_no_balance_column(self):
        avg, src = _fund_avg_cost({"Тикер": "TPAY", "Стоимость": 511500}, {"avg_cost_rub": 97.155})
        self.assertEqual((avg, src), (97.155, "trades"))

    def test_none_without_sources(self):
        self.assertEqual(_fund_avg_cost({"Тикер": "X"}, None), (None, None))
        self.assertEqual(_fund_avg_cost(None, {"avg_cost_rub": 0}), (None, None))

    def test_build_funds_balance_row_gets_trades_avg(self):
        portfolio = {"other_positions": [{"Тип": "Фонды", "Тикер": "TPAY", "Название": "TPAY ETF",
                                          "Стоимость": 511500, "Кол-во": 5000}]}
        hs = _build_funds(portfolio, {}, _returns(TPAY=(5000, 511500, 97.155)))
        h = next(x for x in hs if x["ticker"] == "TPAY")
        self.assertEqual(h["avg_cost_rub"], 97.155)
        self.assertEqual(h["avg_cost_source"], "trades")
        self.assertEqual(h["asset_type"], "fund")

    def test_build_funds_returns_only_fund(self):
        hs = _build_funds({"other_positions": []}, {}, _returns(TGLD=(29500, 378190, 11.2)))
        h = next(x for x in hs if x["ticker"] == "TGLD")
        self.assertEqual((h["avg_cost_rub"], h["avg_cost_source"]), (11.2, "trades"))

    def test_build_funds_no_avg_anywhere(self):
        portfolio = {"other_positions": [{"Тип": "Фонды", "Тикер": "FINAMAR", "Стоимость": 150000, "Кол-во": 0.88}]}
        hs = _build_funds(portfolio, {}, {"snapshot_current": {"positions": []}})
        h = next(x for x in hs if x["ticker"] == "FINAMAR")
        self.assertIsNone(h["avg_cost_rub"])
        self.assertIsNone(h["avg_cost_source"])


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=1).result
    n = r.testsRun
    print(f"Итого: {n - len(r.failures) - len(r.errors)} из {n}")
    sys.exit(0 if r.wasSuccessful() else 1)

#!/usr/bin/env python3
"""Валютная облигация с основной доской не в рублях: цена и НКД — с рублёвой доски.

Дефект (снапшот 06.11.2026): RU000A10FAK6 (номинал 10 000 CNY) имеет основную доску TQOY
(CURRENCYID CNY, ACCRUEDINT 339,53 ¥), а _accrued_rub_of принимает НКД только при SUR — НКД
пропал, позиция занижена на 4 205 ₽ (3,6 %). Контракт: fetch_quotes переводит такую бумагу
на TQOB/TQCB (CURRENCYID SUR), цена и НКД — одной доски; value_rub с НКД в рублях.
Сеть подменена.
"""
import datetime as dt
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
from scripts import portfolio_returns as pr
from scripts.portfolio_returns import Position, estimate_position_value_rub, moex_prices_from_quotes

_spec = importlib.util.spec_from_file_location("moex_quotes_t", str(HERE.parents[3] / "_shared-references" / "moex_quotes.py"))
mq = importlib.util.module_from_spec(_spec)
sys.modules["moex_quotes_t"] = mq
_spec.loader.exec_module(mq)

SID = "RU000A10FAK6"
SEC = {
    "TQOY": {"SECID": SID, "BOARDID": "TQOY", "CURRENCYID": "CNY", "FACEUNIT": "CNY", "FACEVALUE": 10000,
             "PREVPRICE": 95.66, "ACCRUEDINT": 339.53},
    "TQOB": {"SECID": SID, "BOARDID": "TQOB", "CURRENCYID": "SUR", "FACEUNIT": "CNY", "FACEVALUE": 10000,
             "PREVPRICE": 96.65, "ACCRUEDINT": 4204.909285},
}
AS_OF = dt.date(2026, 11, 6)


def _batch(engine, market, board, secids, profile, timeout=0):
    if board in SEC and SID in secids:
        return {SID: SEC[board]}, {SID: {}}
    return {}, {}


class TestRubleBoard(unittest.TestCase):
    def _quotes(self, boards):
        info = {"secid": SID, "engine": "stock", "market": "bonds", "boardid": "TQOY"}
        with mock.patch.object(mq, "discover_board", return_value=info), \
             mock.patch.object(mq, "_fetch_board_batch", side_effect=lambda *a, **k: _batch(*a, **k) if a[2] in boards else ({}, {})):
            return mq.fetch_quotes([SID], parallel=False)[0]

    def test_moves_to_tqob_accrued_in_rub(self):
        q = self._quotes({"TQOY", "TQOB"})[SID]
        self.assertEqual(q.board, "TQOB")
        self.assertEqual(q.settle_currency, "SUR")
        self.assertAlmostEqual(q.accrued_interest, 4204.909285)
        self.assertAlmostEqual(q.prev_close, 96.65)       # цена той же доски, что и НКД

    def test_value_rub_includes_rub_accrued(self):
        q = self._quotes({"TQOY", "TQOB"})[SID]
        acc = {}
        lp, fv, fc, _ = moex_prices_from_quotes({SID: q.to_dict()}, [SID], accrued_out=acc)
        self.assertAlmostEqual(acc[SID], 4204.909285)
        pos = Position(ticker=SID, currency="RUB", qty=1, total_cost_rub=1.0)
        with mock.patch.object(pr, "rate_for", return_value=12.257):
            v, _ = estimate_position_value_rub(pos, "bond", None, lp[SID], fv[SID], fc[SID], AS_OF, {},
                                               moex_accrued=acc[SID])
        self.assertAlmostEqual(v, 96.65 / 100 * 10000 * 12.257 + 4204.909285, places=4)

    def test_without_ruble_board_stays_as_before(self):
        # рублёвой доски нет — остаёмся на TQOY, НКД не берётся (без догадок о курсе)
        q = self._quotes({"TQOY"})[SID]
        self.assertEqual(q.board, "TQOY")
        acc = {}
        moex_prices_from_quotes({SID: q.to_dict()}, [SID], accrued_out=acc)
        self.assertNotIn(SID, acc)

    def test_live_formula_equals_loader_formula(self):
        # паритет: живая оценка советника/вьюера (apply_quotes) = оценка загрузчика на тех же цене, номинале, НКД, курсе
        spec = importlib.util.spec_from_file_location(
            "gas_t", str(HERE.parents[3] / "skills" / "ru-portfolio-advisor" / "scripts" / "gate_aware_sizing.py"))
        gas = importlib.util.module_from_spec(spec)
        sys.modules["gas_t"] = gas
        spec.loader.exec_module(gas)
        rate = 12.257
        snap = {"holdings": [{"ticker": SID, "isin": SID, "asset_type": "bond", "account": "main", "qty": 3.0,
                              "nominal_currency": "CNY", "current_price_source": "moex_iss", "value_rub": 1.0}]}
        quotes = {"items": {SID: {"price": 96.65, "isin": SID, "accrued_int": 4204.909285, "face_value": 10000,
                                  "face_unit": "CNY", "currency_id": "SUR"}},
                  "fx": {"CNY": rate, "date": "2026-11-06"}}
        live = gas.apply_quotes(snap, quotes)["holdings"][0]["value_rub"]
        pos = Position(ticker=SID, currency="RUB", qty=3, total_cost_rub=1.0)
        with mock.patch.object(pr, "rate_for", return_value=rate):
            loader, _ = estimate_position_value_rub(pos, "bond", None, 96.65, 10000.0, "CNY", AS_OF, {},
                                                    moex_accrued=4204.909285)
        self.assertAlmostEqual(live, loader, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

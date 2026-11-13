#!/usr/bin/env python3
"""Облигации оцениваются ГРЯЗНОЙ стоимостью (цена + НКД) — регресс 2026-10-12.

Дефект: estimate_position_value_rub брал qty × цена% × номинал без НКД, а
покупки в trades IntelInvest записаны с уплаченным НКД («Сумма»). Деньги на
входе грязные, стоимость на выходе чистая → XIRR облигаций систематически
занижен. На БКС-ИИС-3 (полгода, только ОФЗ) это перевернуло знак:
−4,74% вместо +0,7%; на всём портфеле XIRR облигаций с 2022 — 11,7% → 12,3%.

Вторая грабля, пойманная при починке: MOEX ACCRUEDINT номинирован в валюте
ТОРГОВ (CURRENCYID), а не номинала (FACEUNIT). У замещаек на TQCB номинал USD,
а НКД уже в рублях (RU000A105146: 1923.09 при купоне 28.36 USD). Домножение
НКД на курс номинала дало +2,8 млн ₽ фантомной стоимости. Поэтому НКД
прибавляется ПОСЛЕ пересчёта по курсу и только при рублёвых торгах.

Сеть не нужна: Quote подменяется SimpleNamespace.
"""

import datetime as dt
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts import portfolio_returns as pr
from scripts.portfolio_returns import Position, _accrued_rub_of, estimate_position_value_rub

AS_OF = dt.date(2026, 10, 12)


def _pos(qty: float) -> Position:
    return Position(ticker="X", currency="RUB", qty=qty, total_cost_rub=1.0)


class TestDirtyValue(unittest.TestCase):
    def test_rub_bond_adds_accrued(self):
        # ОФЗ 26253 на БКС-ИИС: 90 шт, 83.655%, НКД 61.97 ₽
        v, src = estimate_position_value_rub(
            _pos(90), "bond", None, 83.655, 1000.0, "RUB", AS_OF, {},
            moex_accrued=61.97,
        )
        self.assertAlmostEqual(v, 90 * 836.55 + 90 * 61.97, places=6)
        self.assertEqual(src, "moex")

    def test_without_accrued_is_clean_as_before(self):
        v, _ = estimate_position_value_rub(
            _pos(90), "bond", None, 83.655, 1000.0, "RUB", AS_OF, {},
        )
        self.assertAlmostEqual(v, 90 * 836.55, places=6)

    def test_fx_bond_accrued_not_scaled_by_rate(self):
        # Различитель второй грабли: курс применяется к чистой части, НКД (уже ₽) — нет.
        cache = {"USD": {AS_OF.isoformat(): 80.0}}
        with mock.patch.object(pr, "rate_for", return_value=80.0):
            v, _ = estimate_position_value_rub(
                _pos(5), "bond", None, 98.19, 1000.0, "USD", AS_OF, cache,
                moex_accrued=1923.09,
            )
        self.assertAlmostEqual(v, 5 * 981.9 * 80.0 + 5 * 1923.09, places=4)

    def test_accrued_ignored_for_non_bonds(self):
        v, _ = estimate_position_value_rub(
            _pos(10), "fund", None, 15.0, None, "RUB", AS_OF, {},
            moex_accrued=5.0,
        )
        self.assertAlmostEqual(v, 150.0, places=6)

    def test_last_trade_fallback_stays_clean(self):
        # Без цены MOEX НКД неизвестен — оценка чистая, видно по price_source.
        v, src = estimate_position_value_rub(
            _pos(10), "bond", 90.0, None, 1000.0, "RUB", AS_OF, {},
            moex_accrued=30.0,
        )
        self.assertAlmostEqual(v, 9000.0, places=6)
        self.assertEqual(src, "last_trade_price")


class TestAccruedCurrency(unittest.TestCase):
    def test_rub_settlement_taken(self):
        for cur in ("SUR", "RUB"):
            q = SimpleNamespace(accrued_interest=35.44, settle_currency=cur)
            self.assertEqual(_accrued_rub_of(q), 35.44)

    def test_foreign_settlement_rejected(self):
        q = SimpleNamespace(accrued_interest=12.5, settle_currency="USD")
        self.assertIsNone(_accrued_rub_of(q))

    def test_unknown_settlement_rejected(self):
        # Старый профиль без CURRENCYID — не гадаем, оценка остаётся чистой.
        q = SimpleNamespace(accrued_interest=12.5, settle_currency=None)
        self.assertIsNone(_accrued_rub_of(q))
        self.assertIsNone(_accrued_rub_of(SimpleNamespace()))

    def test_weekly_profile_requests_currencyid(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                        "_shared-references"))
        import moex_quotes as mq
        self.assertIn("CURRENCYID", mq.BOND_STATIC_WEEKLY)
        self.assertIn("ACCRUEDINT", mq.BOND_STATIC_WEEKLY)


class TestFetchEarlyReturnShape(unittest.TestCase):
    def test_missing_module_returns_four_tuple(self):
        # Ранние return'ы отдавали 3 элемента при сигнатуре из 4 — распаковка
        # у вызывающих падала бы ровно тогда, когда MOEX недоступен.
        with mock.patch.object(pr.Path, "exists", return_value=False):
            out = pr.fetch_moex_prices(["SU26253RMFS3"], accrued_out={})
        self.assertEqual(len(out), 4)
        self.assertEqual(out[3], {"SU26253RMFS3"})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""PDL-12: заблокированные позиции переживают приведение к рублю.

Дефект (найден 2026-08-19 сверкой с IntelInvest по каждой бумаге):
`classify_blocked` ключует позицию как `(ticker, currency)` по валюте СДЕЛКИ и
помечает `(BAC, USD)`. Но `reconstruct_positions` приводит позиции к рублю
(`merge_cross_currency_positions`), и живой ключ той же бумаги — `(BAC, RUB)`.
Ключевые пространства расходились, `is_blocked` давал False, и 17 замороженных
американских бумаг оценивались по `cost_basis`/`last_trade_price` вместо нуля —
239 211 ₽ утекали в `breakdown_by_type.stock` и `total_value_rub`. При этом
`blocked_value_rub` честно показывал 0, а `total_value_rub_excl_blocked`
совпадал с `total_value_rub`, то есть «excl_blocked» ничего не исключал.

Ключевая тонкость, ради которой нельзя сопоставлять просто по тикеру:
`T/USD` — AT&T (заморожен), `T/RUB` — Т-Технологии (живая российская бумага,
12 сделок вплоть до 2026-08). Сопоставление по одному тикеру обнулило бы живую
позицию, поэтому в набор попадают только тикеры БЕЗ незаблокированного
валютного варианта. RTX и Z эвристикой не отделяются от T (у них тоже смешанные
валюты, но рублёвая сделка — одна, корректировка брокера 2024-08-12), поэтому
они внесены в ручной реестр `BLOCKED_EXACT`.

Запуск: python3 skills/portfolio-data-loader/tests/test_blocked_positions.py
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.portfolio_returns import (  # noqa: E402
    BLOCKED_EXACT,
    classify_blocked,
    unambiguous_blocked_tickers,
)


def _trade(ticker, currency, date, name="", operation="Покупка"):
    from scripts.portfolio_returns import Trade
    return Trade(
        ticker=ticker, name=name or ticker, operation=operation,
        date=date, qty=1.0, price=1.0, nominal=None, nkd=None,
        commission=0.0, amount=1.0, amount_no_comm=1.0,
        currency=currency, note="",
    )


class TestUnambiguousBlockedTickers(unittest.TestCase):

    def test_single_currency_blocked_ticker_included(self):
        """BAC: только USD-сделки до отсечки → тикер попадает в набор."""
        trades = [_trade("BAC", "USD", dt.date(2022, 2, 18), "Bank of America")]
        blocked = set().union(*classify_blocked(trades).values())
        self.assertIn(("BAC", "USD"), blocked)
        self.assertIn("BAC", unambiguous_blocked_tickers(trades, blocked))

    def test_live_rub_variant_excludes_ticker(self):
        """T: USD-вариант заблокирован, RUB-вариант живой → тикер НЕ в наборе.

        Регрессия на живую бумагу: обнуление Т-Технологий недопустимо.
        """
        trades = [
            _trade("T", "USD", dt.date(2022, 1, 18), "AT&T INC."),
            _trade("T", "RUB", dt.date(2026, 8, 4), "Т-Технологии"),
        ]
        blocked = set().union(*classify_blocked(trades).values())
        self.assertIn(("T", "USD"), blocked)
        self.assertNotIn(("T", "RUB"), blocked)
        self.assertNotIn("T", unambiguous_blocked_tickers(trades, blocked))

    def test_explicit_blocklist_covers_all_currencies(self):
        """RTX/Z: ручной реестр блокирует ВСЕ валютные варианты сразу."""
        for ticker in ("RTX", "Z"):
            with self.subTest(ticker=ticker):
                self.assertIn(ticker, BLOCKED_EXACT)
                trades = [
                    _trade(ticker, "USD", dt.date(2020, 7, 27)),
                    _trade(ticker, "RUB", dt.date(2024, 8, 12)),
                ]
                blocked = set().union(*classify_blocked(trades).values())
                self.assertIn((ticker, "USD"), blocked)
                self.assertIn((ticker, "RUB"), blocked)
                self.assertIn(ticker,
                              unambiguous_blocked_tickers(trades, blocked))

    def test_russian_ticker_never_blocked(self):
        """Обычная российская бумага не должна попадать в набор."""
        trades = [_trade("SBER", "RUB", dt.date(2026, 8, 1), "Сбербанк")]
        blocked = set().union(*classify_blocked(trades).values())
        self.assertEqual(blocked, set())
        self.assertEqual(unambiguous_blocked_tickers(trades, blocked), set())

    def test_empty_inputs_do_not_crash(self):
        self.assertEqual(unambiguous_blocked_tickers([], set()), set())

    def test_non_trade_operations_ignored(self):
        """Дивиденды/купоны не создают валютный вариант ключа."""
        trades = [
            _trade("BAC", "USD", dt.date(2022, 2, 18)),
            _trade("BAC", "RUB", dt.date(2026, 1, 1), operation="Дивиденды"),
        ]
        blocked = set().union(*classify_blocked(trades).values())
        self.assertIn("BAC", unambiguous_blocked_tickers(trades, blocked))

    def test_cash_and_point_rows_skipped(self):
        trades = [
            _trade("Деньги RUB", "RUB", dt.date(2026, 1, 1)),
            _trade("BONUS", "POINT", dt.date(2026, 1, 1)),
            _trade("BAC", "USD", dt.date(2022, 2, 18)),
        ]
        blocked = set().union(*classify_blocked(trades).values())
        result = unambiguous_blocked_tickers(trades, blocked)
        self.assertIn("BAC", result)
        self.assertNotIn("Деньги RUB", result)
        self.assertNotIn("BONUS", result)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Тесты свёртки недавних сделок (recent_* поля per_instrument_xirr).

Контекст: правило неразворота ru-portfolio-advisor (Rule 3) запрещает
рекомендовать движение по бумаге в сторону, ОБРАТНУЮ недавнему движению —
для этого потребителю нужны направление и размер сделок за скользящее окно.
Эта фича реализована в двух местах (см. каждое соответствующим классом
тестов ниже):

  • per_security_xirr.py :: _compute_recent_window — сырая свёртка
    buy/sell-сделок в окне [as_of − window_days; as_of] из объектов Trade
    (только Покупка/Продажа; дивиденды/купоны/амортизации/корректировки
    исключены — см. docstring функции). НЕ классифицирует направление.

  • assemble_snapshot.py :: _derive_recent_net_threshold — считает порог
    (₽) из «акционной книги» (goals_matrix RUB/Акция «Сейчас») или fallback;
    :: _build_per_instrument_xirr — классифицирует recent_direction
    (buy/trim/null) против этого порога и собирает per_instrument_xirr;
    :: _recent_window_days_from_per_security — читает фактически применённое
    окно из per_security.json (не пере-декларирует отдельным параметром).

Синтетические Trade строятся напрямую (без xlsx-фикстур) — нужен точный
контроль дат для граничных проверок окна. Единственный тест на реальных
данных (TestLiveSanityCheck) skipTest'ится, если файла-фикстуры нет.
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.portfolio_returns import Trade
from scripts.per_security_xirr import _compute_recent_window, per_security_xirr
from scripts.assemble_snapshot import (
    _build_per_instrument_xirr,
    _derive_recent_net_threshold,
    _recent_window_days_from_per_security,
)

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples")
TRADES_XLSX = os.path.join(EXAMPLES, "trades_portfolio_707160-32.xlsx")


def _trade(operation: str, date: dt.date, rub_amount: float) -> Trade:
    """Синтетическая сделка — заполняет только поля, нужные _compute_recent_window
    (operation, date, rub_amount); остальное — нейтральные заглушки."""
    return Trade(
        ticker="TEST", name="Тестовая бумага", operation=operation, date=date,
        qty=1.0, price=abs(rub_amount), nominal=None, nkd=None, commission=0.0,
        amount=rub_amount, amount_no_comm=rub_amount, currency="RUB", note="",
        rub_amount=rub_amount,
    )


AS_OF = dt.date(2026, 8, 21)


class TestComputeRecentWindow(unittest.TestCase):
    """per_security_xirr.py :: _compute_recent_window — сырая свёртка из Trade."""

    def test_only_buy_sell_counted_dividends_excluded(self):
        # По решению владельца: дивиденды/купоны/амортизации — приток без
        # изменения экспозиции, в net/n_buys/n_sells не входят.
        trades = [
            _trade("Покупка", dt.date(2026, 8, 1), 30_000.0),
            _trade("Продажа", dt.date(2026, 8, 5), 9_000.0),
            _trade("Дивиденд", dt.date(2026, 8, 10), 500.0),
            _trade("Купон", dt.date(2026, 8, 12), 200.0),
            _trade("Амортизация", dt.date(2026, 8, 15), 3_000.0),
        ]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertAlmostEqual(r["recent_net_rub"], 30_000.0 - 9_000.0)
        self.assertEqual(r["recent_n_buys"], 1)
        self.assertEqual(r["recent_n_sells"], 1)
        self.assertEqual(r["recent_last_trade_date"], "2026-08-05")
        self.assertTrue(r["recent_round_trip"])  # была и покупка, и продажа

    def test_corrections_excluded(self):
        # Korrektirovka — синтетическая реконсиляция IntelInvest↔брокер, не
        # решение владельца двигать позицию (решение из отчёта: осознанно вне).
        trades = [
            _trade("Покупка", dt.date(2026, 8, 1), 30_000.0),
            _trade("Корректировка", dt.date(2026, 8, 3), 150_000.0),
            _trade("Корректировка", dt.date(2026, 8, 4), -60_000.0),
        ]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertAlmostEqual(r["recent_net_rub"], 30_000.0)
        self.assertEqual(r["recent_n_buys"], 1)
        self.assertEqual(r["recent_n_sells"], 0)
        self.assertFalse(r["recent_round_trip"])

    def test_net_is_signed_purchases_minus_sales(self):
        trades = [
            _trade("Продажа", dt.date(2026, 8, 1), 90_000.0),
            _trade("Покупка", dt.date(2026, 8, 2), 15_000.0),
        ]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertAlmostEqual(r["recent_net_rub"], 15_000.0 - 90_000.0)
        self.assertTrue(r["recent_net_rub"] < 0)

    def test_round_trip_false_when_only_buys(self):
        trades = [
            _trade("Покупка", dt.date(2026, 8, 1), 60_000.0),
            _trade("Покупка", dt.date(2026, 8, 5), 60_000.0),
        ]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertFalse(r["recent_round_trip"])
        # PDL-контракт §4: три добора по 20 тыс — нетто 60 тыс, а не средняя
        # сделка. Считаем по НЕТТО за окно, не по отдельной сделке.
        self.assertAlmostEqual(r["recent_net_rub"], 120_000.0)

    def test_net_threshold_is_over_window_not_per_trade(self):
        # Три добора по 20 тыс = 60 тыс нетто (порог должен видеть сумму,
        # а не разрешать обходить его дроблением на мелкие сделки).
        trades = [
            _trade("Покупка", dt.date(2026, 8, 1), 60_000.0),
            _trade("Покупка", dt.date(2026, 8, 8), 60_000.0),
            _trade("Покупка", dt.date(2026, 8, 15), 60_000.0),
        ]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertAlmostEqual(r["recent_net_rub"], 180_000.0)
        self.assertEqual(r["recent_n_buys"], 3)

    def test_window_boundary_exact_cutoff_included(self):
        # cutoff = as_of − 60 дней = 2026-06-22 (включительно).
        cutoff = AS_OF - dt.timedelta(days=60)
        self.assertEqual(cutoff, dt.date(2026, 6, 22))
        trades = [_trade("Покупка", cutoff, 45_000.0)]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertEqual(r["recent_n_buys"], 1)
        self.assertAlmostEqual(r["recent_net_rub"], 45_000.0)
        self.assertEqual(r["recent_last_trade_date"], cutoff.isoformat())

    def test_window_boundary_one_day_before_cutoff_excluded(self):
        cutoff = AS_OF - dt.timedelta(days=60)
        one_day_older = cutoff - dt.timedelta(days=1)
        trades = [_trade("Покупка", one_day_older, 45_000.0)]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertEqual(r["recent_n_buys"], 0)
        self.assertEqual(r["recent_net_rub"], 0.0)
        self.assertIsNone(r["recent_last_trade_date"])
        self.assertFalse(r["recent_round_trip"])

    def test_trade_on_as_of_included(self):
        trades = [_trade("Продажа", AS_OF, 21_000.0)]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertEqual(r["recent_n_sells"], 1)

    def test_trade_after_as_of_excluded(self):
        trades = [_trade("Покупка", AS_OF + dt.timedelta(days=1), 21_000.0)]
        r = _compute_recent_window(trades, AS_OF, 60)
        self.assertEqual(r["recent_n_buys"], 0)

    def test_window_days_parameter_changes_result(self):
        # Сделка через 45 дней после cutoff-30, но внутри cutoff-90 — окно
        # реально влияет на результат, это не константа в коде.
        trade_date = AS_OF - dt.timedelta(days=45)
        trades = [_trade("Покупка", trade_date, 75_000.0)]
        r_30 = _compute_recent_window(trades, AS_OF, 30)
        r_90 = _compute_recent_window(trades, AS_OF, 90)
        self.assertEqual(r_30["recent_n_buys"], 0)
        self.assertAlmostEqual(r_30["recent_net_rub"], 0.0)
        self.assertEqual(r_90["recent_n_buys"], 1)
        self.assertAlmostEqual(r_90["recent_net_rub"], 75_000.0)

    def test_recent_window_days_echoed(self):
        r = _compute_recent_window([], AS_OF, 37)
        self.assertEqual(r["recent_window_days"], 37)

    def test_no_trades_defaults(self):
        r = _compute_recent_window([], AS_OF, 60)
        self.assertEqual(r["recent_net_rub"], 0.0)
        self.assertEqual(r["recent_n_buys"], 0)
        self.assertEqual(r["recent_n_sells"], 0)
        self.assertIsNone(r["recent_last_trade_date"])
        self.assertFalse(r["recent_round_trip"])


class TestDeriveRecentNetThreshold(unittest.TestCase):
    """assemble_snapshot.py :: _derive_recent_net_threshold — база порога."""

    def test_explicit_override_wins(self):
        portfolio = {"goals": {"matrix": [
            {"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 14_232_340.5},
        ]}}
        thr, basis = _derive_recent_net_threshold(portfolio, 1.0, 37_035.0)
        self.assertEqual(thr, 37_035.0)
        self.assertIn("override", basis)

    def test_book_value_from_goals_matrix(self):
        # Ровно кейс владельца из отчёта: 2026-08-21, книга 14 232 340.5 ₽.
        portfolio = {"goals": {"matrix": [
            {"Валюта": "USD", "Бумага": "Акция", "Сейчас": 2_999_997.0},
            {"Валюта": "RUB", "Бумага": "Облигация", "Сейчас": 3_000.0},
            {"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 14_232_340.5},
        ]}}
        thr, basis = _derive_recent_net_threshold(portfolio, 1.0, None)
        self.assertAlmostEqual(thr, 142_323.42, places=1)
        self.assertIn("акционной книги", basis)

    def test_threshold_pct_is_a_real_parameter(self):
        portfolio = {"goals": {"matrix": [
            {"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 3_000_000.0},
        ]}}
        thr_1pp, _ = _derive_recent_net_threshold(portfolio, 1.0, None)
        thr_2pp, _ = _derive_recent_net_threshold(portfolio, 2.0, None)
        self.assertAlmostEqual(thr_1pp, 30_000.0)
        self.assertAlmostEqual(thr_2pp, 60_000.0)
        self.assertNotEqual(thr_1pp, thr_2pp)

    def test_fallback_to_nav_when_goals_matrix_missing(self):
        portfolio = {"metrics": {"total_current_rub_excl_iis": 42_839_550.0}}
        thr, basis = _derive_recent_net_threshold(portfolio, 1.0, None)
        self.assertAlmostEqual(thr, 428_395.5, places=2)
        self.assertIn("NAV", basis)

    def test_fallback_to_nav_when_matrix_has_no_matching_row(self):
        portfolio = {
            "goals": {"matrix": [{"Валюта": "USD", "Бумага": "Акция", "Сейчас": 1.0}]},
            "metrics": {"total_current_rub_excl_iis": 30_000_000.0},
        }
        thr, basis = _derive_recent_net_threshold(portfolio, 1.0, None)
        self.assertAlmostEqual(thr, 300_000.0)
        self.assertIn("NAV", basis)

    def test_none_when_nothing_available(self):
        thr, basis = _derive_recent_net_threshold(None, 1.0, None)
        self.assertIsNone(thr)
        self.assertIn("не рассчитан", basis)


class TestIsinAlias(unittest.TestCase):
    """_build_per_instrument_xirr: ОФЗ (SECID != ISIN) находятся и по ISIN."""

    PS = {
        "SU26243RMFS4": {"ticker": "SU26243RMFS4", "xirr_frac": 0.10, "qty_now": 5.0},
        "RU000A10AAA1": {"ticker": "RU000A10AAA1", "xirr_frac": 0.08, "qty_now": 1.0},
        "SBER": {"ticker": "SBER", "xirr_frac": 0.12, "qty_now": 1.0},
    }
    HOLD = [
        {"ticker": "RU000A106E90", "isin": "RU000A106E90", "name": "ОФЗ 78729",
         "asset_type": "bond", "account": "main"},
        {"ticker": "RU000A106E90", "isin": "RU000A106E90", "name": "ОФЗ 78729",
         "asset_type": "bond", "account": "iis_3"},
        {"ticker": "RU000A10AAA1", "isin": "RU000A10AAA1", "name": "Корп 1",
         "asset_type": "bond"},
        {"ticker": "SBER", "isin": "RU0009029540", "name": "Сбер", "asset_type": "stock"},
    ]
    RET = {"snapshot_current": {"positions": [
        {"ticker": "SU26243RMFS4", "name": "ОФЗ 78729", "type": "bond"},
        {"ticker": "RU000A10AAA1", "name": "Корп 1", "type": "bond"},
    ]}}

    def test_alias_by_isin(self):
        out = _build_per_instrument_xirr(self.PS, None, self.HOLD, self.RET)
        self.assertEqual(out["SU26243RMFS4"]["isin"], "RU000A106E90")
        self.assertNotIn("alias_of", out["SU26243RMFS4"])
        al = out["RU000A106E90"]
        self.assertEqual(al["alias_of"], "SU26243RMFS4")
        self.assertEqual(al["xirr"], out["SU26243RMFS4"]["xirr"])

    def test_secid_equal_isin_no_alias(self):
        out = _build_per_instrument_xirr(self.PS, None, self.HOLD, self.RET)
        self.assertNotIn("alias_of", out["RU000A10AAA1"])
        self.assertEqual(out["SBER"]["isin"], "RU0009029540")
        self.assertEqual(len(out), 4)  # 3 исходных + 1 алиас

    def test_ambiguous_name_not_aliased(self):
        hold = self.HOLD + [{"ticker": "RU000A999999", "isin": "RU000A999999",
                             "name": "ОФЗ 78729", "asset_type": "bond"}]
        out = _build_per_instrument_xirr(self.PS, None, hold, self.RET)
        self.assertNotIn("isin", out["SU26243RMFS4"])
        self.assertEqual(len(out), 3)

    def test_without_holdings_unchanged(self):
        out = _build_per_instrument_xirr(self.PS, None)
        self.assertEqual(set(out), set(self.PS))


class TestBuildPerInstrumentXirr(unittest.TestCase):
    """assemble_snapshot.py :: _build_per_instrument_xirr — recent_direction + аддитивность."""

    BASE_ENTRY = {
        "ticker": "SBER", "xirr_frac": 0.1234, "qty_now": 100.0, "pnl_rub": 15_000.0,
        "buy_total_rub": 150_000.0, "sell_total_rub": 0.0, "dividends_rub": 3_600.0,
        "market_value_rub": 165_000.0, "price_source": "moex_iss",
        "first_trade_date": "2024-01-10", "last_trade_date": "2026-08-04",
    }

    def test_breakdown_fields_carried_and_absent_in_old(self):
        new = {"SBER": {
            **self.BASE_ENTRY, "coupons_rub": 10.0, "amortization_rub": 5.0,
            "corr_buy_rub": 1.0, "corr_sell_rub": 2.0, "n_sells": 3,
            "sell_total_rub": 21_000.0,
        }}
        e = _build_per_instrument_xirr(new, net_threshold_rub=None)["SBER"]
        for k, v in (("sell_total_rub", 21_000.0), ("coupons_rub", 10.0),
                     ("amortization_rub", 5.0), ("corr_buy_rub", 1.0),
                     ("corr_sell_rub", 2.0), ("n_sells", 3)):
            self.assertEqual(e[k], v)
        old = {"SBER": {k: v for k, v in self.BASE_ENTRY.items()
                        if k != "sell_total_rub"}}
        e = _build_per_instrument_xirr(old, net_threshold_rub=None)["SBER"]
        for k in ("sell_total_rub", "coupons_rub", "amortization_rub",
                  "corr_buy_rub", "corr_sell_rub", "n_sells"):
            self.assertNotIn(k, e)

    def test_direction_buy_above_threshold(self):
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 180_000.0, "recent_n_buys": 2, "recent_n_sells": 0,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        self.assertEqual(out["SBER"]["recent_direction"], "buy")

    def test_direction_trim_below_negative_threshold(self):
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": -180_000.0, "recent_n_buys": 0, "recent_n_sells": 2,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        self.assertEqual(out["SBER"]["recent_direction"], "trim")

    def test_direction_null_below_threshold_but_counts_and_date_present(self):
        # |нетто| ниже порога → recent_direction отсутствует (= null), НО
        # счётчики и дата последней сделки остаются в записи.
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 30_000.0, "recent_n_buys": 1, "recent_n_sells": 0,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        entry = out["SBER"]
        self.assertNotIn("recent_direction", entry)
        self.assertEqual(entry["recent_n_buys"], 1)
        self.assertEqual(entry["recent_n_sells"], 0)
        self.assertEqual(entry["recent_last_trade_date"], "2026-08-04")
        self.assertEqual(entry["recent_net_rub"], 30_000.0)

    def test_round_trip_field_carried_through(self):
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 15_000.0, "recent_n_buys": 3, "recent_n_sells": 2,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": True,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        self.assertTrue(out["SBER"]["recent_round_trip"])

    def test_no_direction_without_threshold(self):
        # net_threshold_rub=None (книгу посчитать не удалось) → direction
        # всегда null, даже если |нетто| огромный.
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 1_500_000.0, "recent_n_buys": 5, "recent_n_sells": 0,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=None)
        self.assertNotIn("recent_direction", out["SBER"])

    def test_no_direction_when_no_trades_in_window(self):
        # net=0.0 и n_buys=n_sells=0 — не должно ложно классифицироваться
        # как "trim"/"buy" даже с крошечным порогом (guard n_buys>0 or n_sells>0).
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 0.0, "recent_n_buys": 0, "recent_n_sells": 0,
            "recent_last_trade_date": None, "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=0.01)
        self.assertNotIn("recent_direction", out["SBER"])
        self.assertNotIn("recent_last_trade_date", out["SBER"])

    def test_backward_compat_missing_recent_fields(self):
        # Старый per_security.json (до этой фичи) — без recent_*-полей вовсе.
        per_security = {"SBER": dict(self.BASE_ENTRY)}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        entry = out["SBER"]
        for key in (
            "recent_net_rub", "recent_n_buys", "recent_n_sells",
            "recent_last_trade_date", "recent_round_trip", "recent_direction",
        ):
            self.assertNotIn(key, entry)
        # Старые поля обязаны остаться как есть.
        self.assertEqual(entry["xirr"], round(12.34 / 100.0, 6))
        self.assertEqual(entry["qty_now"], 100.0)
        self.assertEqual(entry["pnl_rub"], 15_000.0)
        self.assertEqual(entry["buy_total_rub"], 150_000.0)
        self.assertEqual(entry["dividends_rub"], 3_600.0)
        self.assertEqual(entry["market_value_rub"], 165_000.0)
        self.assertEqual(entry["first_trade_date"], "2024-01-10")
        self.assertEqual(entry["last_trade_date"], "2026-08-04")

    def test_additivity_old_fields_unchanged_when_recent_present(self):
        per_security = {"SBER": {
            **self.BASE_ENTRY,
            "recent_net_rub": 180_000.0, "recent_n_buys": 2, "recent_n_sells": 0,
            "recent_last_trade_date": "2026-08-04", "recent_round_trip": False,
        }}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        entry = out["SBER"]
        self.assertEqual(entry["xirr"], round(12.34 / 100.0, 6))
        self.assertEqual(entry["qty_now"], 100.0)
        self.assertEqual(entry["pnl_rub"], 15_000.0)
        self.assertEqual(entry["buy_total_rub"], 150_000.0)
        self.assertEqual(entry["dividends_rub"], 3_600.0)
        self.assertEqual(entry["market_value_rub"], 165_000.0)
        self.assertEqual(entry["price_source"], "moex_iss")
        self.assertEqual(entry["first_trade_date"], "2024-01-10")
        self.assertEqual(entry["last_trade_date"], "2026-08-04")

    def test_error_entries_skipped(self):
        per_security = {"XXXX": {"error": "no trades found", "ticker": "XXXX"}}
        out = _build_per_instrument_xirr(per_security, net_threshold_rub=142_323.42)
        self.assertNotIn("XXXX", out)


class TestRecentWindowDaysFromPerSecurity(unittest.TestCase):
    """assemble_snapshot.py :: _recent_window_days_from_per_security."""

    def test_reads_from_valid_entry(self):
        per_security = {"SBER": {"recent_window_days": 60, "ticker": "SBER"}}
        self.assertEqual(_recent_window_days_from_per_security(per_security), 60)

    def test_skips_error_entries(self):
        per_security = {
            "XXXX": {"error": "no trades found"},
            "SBER": {"recent_window_days": 45, "ticker": "SBER"},
        }
        self.assertEqual(_recent_window_days_from_per_security(per_security), 45)

    def test_none_when_field_missing_old_format(self):
        # Старый per_security.json (до этой фичи) — нет recent_window_days
        # ни у одного тикера.
        per_security = {"SBER": {"ticker": "SBER", "xirr_frac": 0.1234}}
        self.assertIsNone(_recent_window_days_from_per_security(per_security))

    def test_none_on_empty_or_none_input(self):
        self.assertIsNone(_recent_window_days_from_per_security(None))
        self.assertIsNone(_recent_window_days_from_per_security({}))


@unittest.skipUnless(
    os.path.exists(TRADES_XLSX),
    f"trades file not available: {TRADES_XLSX}",
)
class TestLiveSanityCheck(unittest.TestCase):
    """Сверка с реальными данными (см. отчёт агента): на снапшоте
    2026-08-21 SBERP/SBER/LSNGP имеют last_trade_date=2026-08-04, RENI/MBNK
    2026-08-19, MOEX 2026-07-23 — все внутри окна 60 дней от 2026-08-21,
    поэтому recent_n_buys+recent_n_sells не должны быть нулевыми только
    из-за окна (порог/направление здесь не проверяем — это отдельный слой).

    Фикстура trades_portfolio_707160-32.xlsx экспортирована 19.08.2026 и
    может не содержать сделок за 20–21.08 — поэтому здесь только тикеры,
    чья последняя сделка по фикстуре ≤ 19.08 (X5/MBNK по этой фикстуре
    старее, чем в реальном снапшоте, — сознательно не проверяем)."""

    @classmethod
    def setUpClass(cls):
        cls.results = per_security_xirr(
            tickers=["SBERP", "SBER", "LSNGP", "RENI", "MOEX"],
            trades_path=TRADES_XLSX,
            as_of=dt.date(2026, 8, 21),
            use_moex=False,
            cbr_offline=True,
        )

    def test_recent_activity_seen_within_window(self):
        for ticker in ("SBERP", "SBER", "LSNGP", "RENI", "MOEX"):
            with self.subTest(ticker=ticker):
                r = self.results[ticker]
                self.assertNotIn("error", r)
                n_total = r["recent_n_buys"] + r["recent_n_sells"]
                self.assertGreater(
                    n_total, 0,
                    f"{ticker}: recent_n_buys+recent_n_sells=0 — сделка должна "
                    f"попадать в 60-дневное окно от 2026-08-21",
                )
                self.assertIsNotNone(r["recent_last_trade_date"])


if __name__ == "__main__":
    unittest.main()

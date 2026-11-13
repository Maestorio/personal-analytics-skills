#!/usr/bin/env python3
"""--cbr-offline без обходов (2026-10-21).

Дефект: флаг доходил до пересчёта сделок и текущих курсов, но не до build_report —
там два запроса в ЦБ шли в обход: курсы валют номинала замещаек на as_of ±5 дней
(ensure_cbr_rates) и история КС для бенчмарка (fetch_key_rate_history); ещё
iis_returns.py звал build_report без флага. При недоступном cbr.ru (VPN, выход через
KZ) шаг доходностей ждал таймауты ≈5 минут даже в «офлайне».

Контракт:
  • офлайн + курс есть в кэше (rate_for ±30 дней) → ни одного запроса в ЦБ;
  • офлайн + курса нет → запрос всё же делается: иначе замещайка тихо уходит в
    rate=1.0 (оценка как рублёвой) — лучше ждать, чем молча ошибиться;
  • офлайн → история КС не запрашивается, бенчмарк вклада = null (блок best-effort);
  • _cached_rate_ok повторяет окно rate_for (±30 дней);
  • провал курса громкий: fx_gaps → флаг fx_rates_missing → блок записи.
Сеть не нужна (запросы подменены). Запуск:
  python3 skills/portfolio-data-loader/tests/test_cbr_offline.py
"""
import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import portfolio_returns as pr  # noqa: E402

AS_OF = dt.date(2026, 10, 16)


def _trades():
    T = pr.Trade
    rows = [
        T("Деньги (RUB)", "Рубль", "Внесение", dt.date(2026, 1, 12), None, None, None, None, 0.0,
          10000.0, 10000.0, "RUB", ""),
        T("SBER", "Сбербанк", "Покупка", dt.date(2026, 1, 13), 10.0, 300.0, None, None, 0.0,
          3000.0, 3000.0, "RUB", ""),
        T("Деньги (RUB)", "Рубль", "Списание", dt.date(2026, 1, 13), None, None, None, None, 0.0,
          -3000.0, -3000.0, "RUB", ""),
    ]
    for t in rows:
        t.rub_rate = 1.0
        t.amount_rub = t.amount
    return rows


class CachedRateOk(unittest.TestCase):
    def test_window_matches_rate_for(self):
        cache = {"USD": {"2026-09-20": 90.0}}
        self.assertTrue(pr._cached_rate_ok("USD", AS_OF, cache))          # 26 дней назад
        self.assertFalse(pr._cached_rate_ok("USD", dt.date(2026, 11, 1), cache))  # 42 дня
        self.assertFalse(pr._cached_rate_ok("EUR", AS_OF, cache))


class OfflineBuildReport(unittest.TestCase):
    def _run(self, cbr_offline, with_benchmarks=True):
        with mock.patch.object(pr, "fetch_key_rate_history", return_value=None) as kr, \
             mock.patch.object(pr, "fetch_index_history", return_value=None), \
             mock.patch.object(pr, "ensure_cbr_rates", side_effect=lambda cd, c, **k: c) as ens:
            try:
                pr.build_report(_trades(), [], as_of=AS_OF, start_date=dt.date(2026, 1, 1),
                                use_moex=False, with_benchmarks=with_benchmarks,
                                cbr_offline=cbr_offline)
            except Exception as e:  # noqa: BLE001 — нас интересуют только вызовы сети
                if not isinstance(e, (KeyError, ZeroDivisionError, ValueError, TypeError)):
                    raise
        return kr, ens

    def test_offline_skips_key_rate_history(self):
        kr, _ = self._run(cbr_offline=True)
        kr.assert_not_called()

    def test_online_fetches_key_rate_history(self):
        kr, _ = self._run(cbr_offline=False)
        kr.assert_called_once()


class OfflineNominalRates(unittest.TestCase):
    """Фрагмент build_report про валюты номинала — через его входы: KNOWN_FX_BONDS и кэш."""

    def test_offline_filters_only_cached(self):
        cache = {"USD": {"2026-10-10": 83.0}}
        needed = {"USD", "EUR"}
        kept = {c for c in needed if not pr._cached_rate_ok(c, AS_OF, cache)}
        self.assertEqual(kept, {"EUR"})          # USD из кэша, за EUR — всё же в ЦБ


class FxGapsAreLoud(unittest.TestCase):
    """Провал курса больше не молчит (2026-10-21): на Mac через VPN кэш ЦБ кончался 21.04,
    44 сделки в CNY стали 0 ₽, 13 валютных облигаций — по курсу 1.0, XIRR −2,82% вместо 8,27%
    при единственном флаге «ЦБ офлайн». Теперь: fx_gaps в отчёте → флаг error
    fx_rates_missing в снапшоте (видит и скилл) → блок записи в checks."""

    def setUp(self):
        pr.FX_GAPS.clear()

    def test_missing_rate_recorded(self):
        T = pr.Trade
        t = T("RU000A107RH8", "x", "Купон", dt.date(2026, 9, 1), 10.0, None, None, None, 0.0,
              100.0, 100.0, "CNY", "")
        with mock.patch.object(pr, "load_cbr_cache", return_value={"CNY": {"2026-04-21": 11.0}}):
            pr.convert_trades_to_rub([t], cbr_offline=True)
        self.assertEqual(t.rub_amount, 0.0)
        gaps = list(pr.FX_GAPS.values())
        self.assertEqual((gaps[0]["kind"], gaps[0]["currency"], gaps[0]["n"]), ("trade_zeroed", "CNY", 1))

    def test_assemble_flags_and_checks_block(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import assemble_snapshot as asm
        import checks as ch
        returns = {"fx_gaps": [{"kind": "trade_zeroed", "currency": "CNY", "n": 44,
                                "first": "2026-08-06", "last": "2026-10-15"}]}
        snap = asm.assemble(None, returns, None, {}, as_of="2026-10-16")
        codes = [f["code"] for f in snap["data_quality_flags"]]
        self.assertIn("fx_rates_missing", codes)
        res = ch.check_snapshot(ch.Ctx(snap=snap, prev=None, trades=None, as_of="2026-10-16"))
        self.assertIn("fx_rates_missing", [r["id"] for r in res if r["level"] == "block"])

    def test_no_rate_bond_names_currency_and_ticker_and_blocks(self):
        """Валюта без курса ЦБ → блок-проверка с текстом «нет курса ЦБ для KZT — бумага X» (не курс 1.0)."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import assemble_snapshot as asm
        import checks as ch
        pos = pr.Position(ticker="RU000AKZT01", currency="RUB", name="n", qty=3.0, total_cost_rub=2500.0)
        with mock.patch.object(sys, "stderr"):
            v, src = pr.estimate_position_value_rub(pos, "bond", None, 99.0, 1000.0, "KZT",
                                                    dt.date(2026, 11, 11), {})
        self.assertEqual((v, src), (2500.0, "fx_missing"))
        returns = {"fx_gaps": list(pr.FX_GAPS.values())}
        snap = asm.assemble(None, returns, None, {}, as_of="2026-11-11")
        msg = [f["message"] for f in snap["data_quality_flags"] if f["code"] == "fx_rates_missing"][0]
        self.assertIn("нет курса ЦБ для KZT — бумага RU000AKZT01", msg)
        res = ch.check_snapshot(ch.Ctx(snap=snap, prev=None, trades=None, as_of="2026-11-11"))
        self.assertIn("fx_rates_missing", [r["id"] for r in res if r["level"] == "block"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

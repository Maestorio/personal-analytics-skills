#!/usr/bin/env python3
"""Оценка валютных облигаций (замещаек) и build_market_values — регресс-тест (PDL-G).

Зачем: у замещаек pos.currency = "RUB" (платим рублями), а номинал в USD/EUR/CNY. Если курс
номинала не подтянут (в кэше после convert_trades_to_rub лежат лишь даты сделок), rate_for
падает, оценка уходит на курс 1.0 и бумага считается как рублёвая. Тест закрепляет: курс
номинала применяется к чистой части, НКД (уже в рублях) прибавляется после; MOEX без FACEUNIT
добирается из KNOWN_FX_BONDS; курсы ЦБ запрашиваются вокруг as_of; блокировки и PDL-16.

Сеть не нужна: подменены pr.fetch_moex_prices и pr.ensure_cbr_rates. Тип инструмента
определяет настоящий classify_instrument_type: ISIN RU000… без купонов/дивидендов → bond.
"""

import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts import portfolio_returns as pr

AS_OF = dt.date(2026, 10, 12)
RATE = 80.0
CACHE = {"USD": {AS_OF.isoformat(): RATE}, "CNY": {AS_OF.isoformat(): 11.0}}


def P(qty=10.0, cur="RUB", ticker="X", cost=1234.0):
    return pr.Position(ticker=ticker, currency=cur, name="n", qty=qty, total_cost_rub=cost)


def est(pos, typ, ltp, mlast, mface, ncur, cache=CACHE, accrued=None):
    return pr.estimate_position_value_rub(pos, typ, ltp, mlast, mface, ncur, AS_OF, cache,
                                          moex_accrued=accrued)


class TestEstimate(unittest.TestCase):
    def test_a_fx_bond_rate_applied(self):
        v, src = est(P(7), "bond", None, 95.0, 1000, "USD")
        self.assertAlmostEqual(v, 7 * 0.95 * 1000 * RATE)
        self.assertEqual(src, "moex")

    def test_b_accrued_after_rate(self):
        v, _ = est(P(7), "bond", None, 95.0, 1000, "USD", accrued=1923.09)
        self.assertAlmostEqual(v, 7 * 0.95 * 1000 * RATE + 7 * 1923.09)

    def test_c_rub_and_sur_rate_one(self):
        for ncur in (None, "SUR", "RUB"):
            v, _ = est(P(3), "bond", None, 90.0, 1000, ncur, cache={})
            self.assertAlmostEqual(v, 3 * 900.0)

    def test_d_stock_ignores_nominal_currency(self):
        v, _ = est(P(4), "stock", None, 250.0, None, "USD")
        self.assertAlmostEqual(v, 1000.0)

    def test_e_missing_rate_not_one_gap_flagged_with_ticker(self):
        """Курса нет → НЕ 1.0 (стоимость в валюте как в рублях), а стоимость покупки + провал в FX_GAPS
        (потребитель — блок-проверка сборки fx_rates_missing)."""
        with mock.patch.object(pr, "_fx_gap") as gap, mock.patch.object(sys, "stderr"):
            v, src = est(P(2, ticker="RU000AKZT", cost=777.0), "bond", None, 100.0, 1000, "USD", cache={})
        self.assertEqual((v, src), (777.0, "fx_missing"))
        self.assertNotAlmostEqual(v, 2000.0)
        gap.assert_called_once()
        self.assertEqual(gap.call_args[0][:2], ("no_rate", "USD"))
        self.assertEqual(gap.call_args[0][3], "RU000AKZT")

    def test_e2_kzt_bond_valued_by_cbr_rate(self):
        """Облигация в тенге: номинал 1000 KZT, ЦБ 15,9 за 100 → 0,159 ₽ за тенге."""
        cache = {"KZT": {AS_OF.isoformat(): 15.9 / 100}}
        v, src = est(P(10), "bond", None, 98.0, 1000, "KZT", cache=cache)
        self.assertAlmostEqual(v, 10 * 0.98 * 1000 * 0.159)
        self.assertEqual(src, "moex")

    def test_f_last_trade_price_path(self):
        v, src = est(P(2), "bond", 90.0, None, 100, "USD")          # face из moex
        self.assertAlmostEqual(v, 2 * 0.9 * 100 * RATE)
        self.assertEqual(src, "last_trade_price")
        v, _ = est(P(2), "bond", 90.0, None, None, "USD")           # face 1000
        self.assertAlmostEqual(v, 2 * 0.9 * 1000 * RATE)
        v, _ = est(P(2), "bond", 5.0, None, None, "USD")            # цена < 10 → face 100
        self.assertAlmostEqual(v, 2 * 0.05 * 100 * RATE)

    def test_g_no_price_and_zero_qty(self):
        self.assertEqual(est(P(2, cost=777.0), "bond", None, None, None, "USD"), (777.0, "cost_basis"))
        self.assertEqual(est(P(0), "bond", None, 95.0, 1000, "USD"), (0.0, "zero_qty"))

    def test_h_face_100(self):
        v, _ = est(P(5), "bond", None, 98.0, 100, "RUB")
        self.assertAlmostEqual(v, 5 * 0.98 * 100)


def trades_for(ticker, with_coupon=True):
    """Минимальная история: покупка (+ купон, чтобы бумага гарантированно была bond)."""
    mk = lambda op: pr.Trade(ticker=ticker, name="n", operation=op, date=dt.date(2026, 1, 1), qty=1,  # noqa: E731
                             price=100.0, nominal=None, nkd=None, commission=0.0, amount=1.0,
                             amount_no_comm=1.0, currency="RUB", note="")
    return [mk("Покупка")] + ([mk("Купон")] if with_coupon else [])


def build(positions, moex=None, cache=None, **kw):
    """moex = (last, face, face_curr, accrued) словари; возвращает (result, fetch_mock, cbr_mock)."""
    last, face, fcur, acc = moex or ({}, {}, {}, {})
    tbt = {pos.ticker: trades_for(pos.ticker) for pos in positions.values()}
    trades = [t for v in tbt.values() for t in v]

    def fake_fetch(cands, verbose=False, accrued_out=None):
        if accrued_out is not None:
            accrued_out.update(acc)
        return dict(last), dict(face), dict(fcur), set()

    with mock.patch.object(pr, "fetch_moex_prices", side_effect=fake_fetch) as f, \
            mock.patch.object(pr, "ensure_cbr_rates") as c:
        res = pr.build_market_values(positions, trades, tbt, AS_OF,
                                     CACHE if cache is None else cache, **kw)
    return res, f, c


class TestBuild(unittest.TestCase):
    def setUp(self):
        pr.HELD_FX_CURRENCIES.clear()
        pr.FX_GAPS.clear()

    def test_n_held_fx_currencies_only_held(self):
        """Список валют снапшота — только держимые (номинал облигаций + валюта позиций), без RUB/SUR."""
        kz, us = ("RU000AKZT01", "RUB"), ("AAPL", "USD")
        res, _, c = build({kz: P(5, ticker=kz[0]), us: P(1, "USD", "AAPL"), ("SBER", "RUB"): P(1, ticker="SBER")},
                          ({kz[0]: 98.0}, {kz[0]: 1000.0}, {kz[0]: "KZT"}, {}),
                          cache={"KZT": {AS_OF.isoformat(): 0.159}, "USD": {AS_OF.isoformat(): RATE}})
        self.assertEqual(pr.HELD_FX_CURRENCIES, {"KZT", "USD"})
        self.assertNotIn("EUR", pr.HELD_FX_CURRENCIES)
        self.assertEqual(set(c.call_args[0][0]), {"KZT"})
        self.assertAlmostEqual(res[kz]["value_rub"], 5 * 0.98 * 1000 * 0.159)
        self.assertEqual(res[kz]["nominal_currency"], "KZT")
        self.assertEqual(pr.FX_GAPS, {})

    def test_o_current_fx_rates_follow_held(self):
        pr.HELD_FX_CURRENCIES.update({"KZT"})
        cache = {"KZT": {"2026-10-12": 0.159}, "USD": {"2026-10-12": 80.0}}
        out = pr.current_fx_rates(AS_OF, cache=cache, cbr_offline=True)
        self.assertEqual(list(out), ["KZT"])
        self.assertEqual(out["KZT"]["rate"], 0.159)
        out = pr.current_fx_rates(AS_OF, cache=cache, cbr_offline=True, currencies=["USD", "GBP"])
        self.assertEqual(out["USD"]["rate"], 80.0)
        self.assertIsNone(out["GBP"])      # нет курса — None, не 1.0
        pr.HELD_FX_CURRENCIES.clear()
        self.assertEqual(pr.current_fx_rates(AS_OF, cache=cache, cbr_offline=True), {})

    def test_p_cbr_id_and_nominal(self):
        """KZT — в реестре ID; прочая валюта — по CharCode из XML_daily; нет у ЦБ → ValueError;
        Nominal 100 делится при разборе XML_dynamic."""
        self.assertEqual(pr.cbr_val_id("KZT"), "R01335")
        daily = ('<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="11.11.2026"><Valute ID="R01035">'
                 '<CharCode>GBP</CharCode><Nominal>1</Nominal><Value>100,0</Value></Valute></ValCurs>').encode("cp1251")
        dyn = ('<?xml version="1.0" encoding="windows-1251"?><ValCurs ID="R01335"><Record Date="11.11.2026" Id="R01335">'
               '<Nominal>100</Nominal><Value>15,9000</Value></Record></ValCurs>').encode("cp1251")

        class R:
            def __init__(self, b): self.b = b
            def read(self): return self.b
            def __enter__(self): return self
            def __exit__(self, *a): return False
        seen = []

        def fake_open(req, timeout=0):
            seen.append(req.full_url)
            return R(daily if "XML_daily" in req.full_url else dyn)
        pr._CBR_ID_CACHE.clear()
        with mock.patch.object(pr.urllib.request, "urlopen", fake_open):
            self.assertEqual(pr.cbr_val_id("GBP"), "R01035")
            with self.assertRaises(ValueError):
                pr.cbr_val_id("XXX")
            got = pr.fetch_cbr_range("KZT", dt.date(2026, 11, 11), dt.date(2026, 11, 11))
        self.assertAlmostEqual(got[dt.date(2026, 11, 11)], 0.159)
        self.assertTrue(any("VAL_NM_RQ=R01335" in u for u in seen))
        pr._CBR_ID_CACHE.clear()

    def test_i_faceunit_from_moex(self):
        key = ("RU000A1ZZZZ9", "RUB")
        res, _, c = build({key: P(5, ticker=key[0])},
                          ({key[0]: 95.0}, {key[0]: 1000.0}, {key[0]: "USD"}, {}))
        self.assertEqual(res[key]["nominal_currency"], "USD")
        self.assertAlmostEqual(res[key]["value_rub"], 5 * 0.95 * 1000 * RATE)
        c.assert_called_once()
        cd = c.call_args[0][0]
        self.assertEqual(set(cd), {"USD"})
        self.assertEqual(cd["USD"], {AS_OF + dt.timedelta(days=d) for d in range(-5, 3)})

    def test_j_known_fx_registry_fallback(self):
        tk = "RU000A105146"
        key = (tk, "RUB")
        res, _, c = build({key: P(5, ticker=tk)}, ({tk: 95.0}, {}, {}, {}))
        r = res[key]
        self.assertEqual(r["nominal_currency"], "USD")
        self.assertTrue(r["price_source"].endswith("+fx_registry"))
        self.assertAlmostEqual(r["value_rub"], 5 * 0.95 * 1000 * RATE)
        self.assertIn("USD", c.call_args[0][0])

    def test_k_offline_cached_rate_no_cbr_call(self):
        tk = "RU000A105146"
        res, _, c = build({(tk, "RUB"): P(5, ticker=tk)}, ({tk: 95.0}, {}, {}, {}), cbr_offline=True)
        c.assert_not_called()
        self.assertAlmostEqual(res[(tk, "RUB")]["value_rub"], 5 * 0.95 * 1000 * RATE)

    def test_l_moex_candidates(self):
        pos = {("RU000A108FX8", "CNY"): P(1, "CNY", "RU000A108FX8"),
               ("AAPL", "USD"): P(1, "USD", "AAPL"),
               ("SI-3.27", "RUB"): P(1, "RUB", "SI-3.27")}
        _, f, _ = build(pos)
        asked = set(f.call_args[0][0])
        self.assertIn(("RU000A108FX8"), {k[0] if isinstance(k, tuple) else k for k in asked})
        self.assertNotIn("AAPL", {k[0] if isinstance(k, tuple) else k for k in asked})
        self.assertNotIn("SI-3.27", {k[0] if isinstance(k, tuple) else k for k in asked})

    def test_m_blocked_not_requested_and_zero(self):
        key = ("RU000A1ZZZZ9", "RUB")
        res, f, _ = build({key: P(5, ticker=key[0])}, blocked_keys={key}, blocked_value="zero")
        self.assertEqual(res[key]["value_rub"], 0.0)
        self.assertEqual(res[key]["price_source"], "blocked_zero")
        f.assert_not_called()   # единственный кандидат заблокирован — запроса нет


if __name__ == "__main__":
    unittest.main()

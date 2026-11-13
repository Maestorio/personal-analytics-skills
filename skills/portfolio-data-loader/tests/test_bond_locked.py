#!/usr/bin/env python3
"""«При покупке» (locked_pct) облигаций обоих счетов: bond_locked.apply_locked + общий помощник iis_returns.locked_for.

Основной счёт: потоки счёта = суммарные потоки бумаги (per_security.cashflows без терминала) минус потоки ИИС-3,
будущие — по графику на количество основного счёта. Эталон — независимый IRR (бисекция по XNPV, act/365).
Сеть не нужна: график подставляется fetch-заглушкой.
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scripts import bond_locked as bl
from scripts import iis_returns as ir

D = dt.date
AS_OF = "2026-10-29"
SCHED = {
    "coupons": [
        {"coupondate": "2026-09-23", "startdate": "2026-03-25", "facevalue": 1000, "value_rub": 56.1, "valueprc": 11.25},
        {"coupondate": "2027-03-24", "startdate": "2026-09-23", "facevalue": 1000, "value_rub": 56.1, "valueprc": 11.25},
    ],
    "amortizations": [{"amortdate": "2027-09-22", "value_rub": 1000, "initialfacevalue": 1000}],
}
INFL = {"source": "fallback", "path": [], "flat_pct": 4.0}


def _irr(flows):
    """Независимый эталон: корень XNPV бисекцией, act/365 от первой даты."""
    t0 = min(d for d, _ in flows)

    def npv(r):
        return sum(a / (1 + r) ** ((d - t0).days / 365.0) for d, a in flows)
    lo, hi = -0.9, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2 * 100


def _fetch(secid):
    return SCHED


def _holding(account, qty, ticker="SU26244RMFS2", name="ОФЗ 26244", isin="RU000A10BWV0"):
    return {"asset_type": "bond", "account": account, "ticker": ticker, "isin": isin, "name": name,
            "qty": qty, "status": "normal"}


class TestMainLocked(unittest.TestCase):
    def test_two_buys_and_coupon_match_manual_irr(self):
        # две покупки на основном + купон 23.09 (100 шт × 56.10)
        cfs = [["2026-04-20", -87882.0], ["2026-06-10", -88500.0], ["2026-09-23", 5610.0 * 2 / 2 * 1.0],
               [AS_OF, 190000.0]]
        data = {"cashflows": cfs, "market_value_rub": 190000.0}
        hs = [_holding("main", 200)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data}, per_instrument={},
                        iis_flows={}, iis_per_bond=[], fetch=_fetch, infl=INFL)
        hist = [(D(2026, 4, 20), -87882.0), (D(2026, 6, 10), -88500.0), (D(2026, 9, 23), 5610.0)]
        fut = [(D(2027, 3, 24), 56.1 * 200), (D(2027, 9, 22), 1000 * 200)]
        self.assertAlmostEqual(hs[0]["locked_pct"], _irr(hist + fut), delta=0.01)
        self.assertNotIn("locked_real_pct", hs[0])

    def test_bond_on_both_accounts_each_holding_own_locked(self):
        # суммарно 300 шт: основной 200 (две покупки), ИИС-3 100 (одна покупка по другой цене)
        iis_cf = [["2026-05-05", -91000.0], ["2026-09-23", 5610.0]]
        main_cf = [["2026-04-20", -87882.0], ["2026-06-10", -88500.0], ["2026-09-23", 11220.0]]
        total = sorted(main_cf + iis_cf, key=lambda x: x[0]) + [[AS_OF, 285000.0]]
        data = {"cashflows": total, "market_value_rub": 285000.0}
        iis_flows = {"SU26244RMFS2": {"cashflows": iis_cf, "qty_now": 100.0}}
        iis_row = {"secid": "SU26244RMFS2", "isin": "RU000A10BWV0", "locked_pct": 11.11, "linker": False}
        hs = [_holding("main", 200), _holding("iis_3", 100)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data}, per_instrument={},
                        iis_flows=iis_flows, iis_per_bond=[iis_row], fetch=_fetch, infl=INFL)
        hist = [(D(2026, 4, 20), -87882.0), (D(2026, 6, 10), -88500.0), (D(2026, 9, 23), 11220.0)]
        fut = [(D(2027, 3, 24), 56.1 * 200), (D(2027, 9, 22), 1000 * 200)]
        self.assertAlmostEqual(hs[0]["locked_pct"], _irr(hist + fut), delta=0.01)
        self.assertEqual(hs[1]["locked_pct"], 11.11)
        self.assertNotEqual(hs[0]["locked_pct"], hs[1]["locked_pct"])

    def test_no_schedule_gives_null(self):
        data = {"cashflows": [["2026-04-20", -90000.0], [AS_OF, 95000.0]], "market_value_rub": 95000.0}
        hs = [_holding("main", 100)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data}, per_instrument={},
                        iis_flows={}, iis_per_bond=[], fetch=lambda s: {}, infl=INFL)
        self.assertIsNone(hs[0]["locked_pct"])

    def test_network_error_gives_null(self):
        def boom(_):
            raise RuntimeError("MOEX ISS недоступен")
        data = {"cashflows": [["2026-04-20", -90000.0], [AS_OF, 95000.0]], "market_value_rub": 95000.0}
        hs = [_holding("main", 100)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data}, per_instrument={},
                        iis_flows={}, iis_per_bond=[], fetch=boom, infl=INFL)
        self.assertIsNone(hs[0]["locked_pct"])

    def test_no_fetch_leaves_main_untouched_but_iis_copied(self):
        hs = [_holding("main", 100), _holding("iis_3", 100)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={}, per_instrument={}, iis_flows={},
                        iis_per_bond=[{"secid": "SU26244RMFS2", "locked_pct": 9.5, "linker": False}],
                        fetch=None, infl=None)
        self.assertNotIn("locked_pct", hs[0])
        self.assertEqual(hs[1]["locked_pct"], 9.5)

    def test_both_accounts_without_iis_flows_is_null(self):
        data = {"cashflows": [["2026-04-20", -90000.0], [AS_OF, 95000.0]], "market_value_rub": 95000.0}
        hs = [_holding("main", 100), _holding("iis_3", 50)]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data}, per_instrument={},
                        iis_flows={}, iis_per_bond=[], fetch=_fetch, infl=INFL)
        self.assertIsNone(hs[0]["locked_pct"])

    def test_isin_alias_resolves_secid(self):
        data = {"cashflows": [["2026-04-20", -90000.0], [AS_OF, 95000.0]], "market_value_rub": 95000.0}
        hs = [_holding("main", 100, ticker="RU000A10BWV0")]
        bl.apply_locked(hs, as_of=AS_OF, per_security={"SU26244RMFS2": data},
                        per_instrument={"RU000A10BWV0": {"alias_of": "SU26244RMFS2"}},
                        iis_flows={}, iis_per_bond=[], fetch=_fetch, infl=INFL)
        self.assertIsNotNone(hs[0]["locked_pct"])


class TestLockedFor(unittest.TestCase):
    def test_linker_has_real_and_shared_helper_matches_compute_formula(self):
        sched = {"coupons": [{"coupondate": "2027-03-24", "startdate": "2026-09-23", "facevalue": 1500,
                              "valueprc": 2.5, "name": "ОФЗ-ИН 52004"}],
                 "amortizations": [{"amortdate": "2027-09-22", "value_rub": 1500, "initialfacevalue": 1500}]}
        hist = [(D(2026, 4, 20), -150000.0)]
        out = ir.locked_for(sched, "ОФЗ-ИН 52004", 100, D(2026, 10, 29), INFL, hist)
        self.assertTrue(out["linker"])
        self.assertIn("locked_real_pct", out)
        self.assertGreater(out["locked_pct"], out["locked_real_pct"])


if __name__ == "__main__":
    unittest.main()

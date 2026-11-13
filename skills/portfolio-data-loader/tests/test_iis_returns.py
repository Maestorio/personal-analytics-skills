#!/usr/bin/env python3
"""Доходность БКС-ИИС-3 из отдельной выгрузки (iis_returns.py + сборка в снапшот).

Контракт владельца (2026-10-12): покупка/продажа/взнос на счёт сразу влекут
свежую выгрузку; нет файла — операций не было. Между выгрузками на счёте
случаются только купоны → достраиваются по графику MOEX и заменяются
реальными, как только они приходят в файле (±10 дней от даты графика; реально
зачисление идёт ±1 день). Состояние между прогонами не хранится.

Числа фикстур — живые (ОФЗ 26244: купон 56.10, 100 шт → 5 610 ₽ брутто, как в
выписке; ОФЗ-ИН 52004: 2.5%, номинал 1518.02). Сеть не нужна.
"""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scripts import iis_returns as ir
from scripts.portfolio_returns import Trade, build_report, extract_cashflows_by_invariant
from scripts.assemble_snapshot import _build_iis_account_returns

D = dt.date


def _t(ticker, op, day, amount, qty=None, name="ОФЗ 26244", note=""):
    return Trade(ticker=ticker, name=name, operation=op, date=day, qty=qty,
                 price=None, nominal=None, nkd=None, commission=0.0, amount=amount,
                 amount_no_comm=amount, currency="RUB", note=note,
                 rub_amount=amount, rub_rate=1.0)


def _cash(day, amount, note=""):
    return _t("Деньги (RUB)", "Внесение" if amount > 0 else "Списание", day, amount,
              name="Российский рубль", note=note)


SCHED_26244 = {
    "coupons": [
        {"coupondate": "2026-09-23", "recorddate": "2026-09-22", "startdate": "2026-03-25",
         "facevalue": 1000, "value_rub": 56.1, "valueprc": 11.25},
        {"coupondate": "2027-03-24", "recorddate": "2027-03-23", "startdate": "2026-09-23",
         "facevalue": 1000, "value_rub": 56.1, "valueprc": 11.25},
    ],
    "amortizations": [{"amortdate": "2027-09-22", "value_rub": 1000, "initialfacevalue": 1000}],
}


def _base_trades():
    """Взнос + покупка 100 шт 26244 в апреле; файл выгружен 20.04."""
    return [
        _cash(D(2026, 4, 17), 90_000.0),
        _t("SU26244RMFS2", "Покупка", D(2026, 4, 20), 87_882.0, qty=100),
        _cash(D(2026, 4, 20), -87_882.0),
    ]


class TestSynthesizeCoupons(unittest.TestCase):
    def test_coupon_after_file_is_synthesized(self):
        trades = _base_trades()
        synth, info, flags = ir.synthesize_coupons(
            trades, {"SU26244RMFS2": SCHED_26244}, D(2026, 10, 12))
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["amount_rub"], 5610.0)       # 56.10 × 100, брутто
        self.assertEqual({t.operation for t in synth}, {"Купон", "Внесение"})
        self.assertTrue(all(t.is_synthetic for t in synth))
        self.assertEqual(flags, [])

    def test_synthetic_pair_is_not_external_flow(self):
        # Купон + зачисление в один день — внутреннее движение, не взнос.
        trades = _base_trades()
        synth, _, _ = ir.synthesize_coupons(trades, {"SU26244RMFS2": SCHED_26244},
                                            D(2026, 10, 12))
        cfs = extract_cashflows_by_invariant(sorted(trades + synth, key=lambda t: t.date))
        self.assertEqual([c.date for c in cfs], [D(2026, 4, 17)])

    def test_real_coupon_one_day_late_replaces_synthetic(self):
        trades = _base_trades() + [
            _t("SU26244RMFS2", "Купон", D(2026, 9, 24), 5610.0, qty=100),
            _cash(D(2026, 9, 24), 5610.0),
        ]
        synth, info, flags = ir.synthesize_coupons(
            trades, {"SU26244RMFS2": SCHED_26244}, D(2026, 10, 12))
        self.assertEqual((synth, info, flags), ([], [], []))

    def test_replacement_barely_moves_xirr(self):
        # Синтетика 23.09 против реального купона 24.09 — разница XIRR < 0.01 п.п.
        as_of = D(2026, 10, 12)
        stale = _base_trades()
        synth, _, _ = ir.synthesize_coupons(stale, {"SU26244RMFS2": SCHED_26244}, as_of)
        fresh = _base_trades() + [
            _t("SU26244RMFS2", "Купон", D(2026, 9, 24), 5610.0, qty=100),
            _cash(D(2026, 9, 24), 5610.0),
        ]
        x1 = build_report(sorted(stale + synth, key=lambda t: t.date), [], as_of=as_of,
                          use_moex=False, with_benchmarks=False)["returns_total"]["xirr"]
        x2 = build_report(fresh, [], as_of=as_of, use_moex=False,
                          with_benchmarks=False)["returns_total"]["xirr"]
        self.assertIsNotNone(x1)
        self.assertLess(abs(x1 - x2), 0.0001)

    def test_missing_coupon_inside_file_period_is_flag_not_synthetic(self):
        # Файл тянется до декабря, а сентябрьского купона в нём нет: файл
        # авторитетен — не достраиваем, а сигналим.
        trades = _base_trades() + [_cash(D(2026, 12, 1), 1000.0)]
        synth, info, flags = ir.synthesize_coupons(
            trades, {"SU26244RMFS2": SCHED_26244}, D(2026, 12, 5))
        self.assertEqual(info, [])
        self.assertEqual(flags[0]["code"], "iis_coupon_missing_in_file")

    def test_bought_on_record_date_not_entitled(self):
        # T+1: покупка В день отсечки на купон не даёт права.
        trades = [_cash(D(2026, 9, 22), 90_000.0),
                  _t("SU26244RMFS2", "Покупка", D(2026, 9, 22), 87_000.0, qty=100),
                  _cash(D(2026, 9, 22), -87_000.0)]
        _, info, _ = ir.synthesize_coupons(trades, {"SU26244RMFS2": SCHED_26244},
                                           D(2026, 10, 12))
        self.assertEqual(info, [])

    def test_redemption_after_file_is_flagged(self):
        _, _, flags = ir.synthesize_coupons(
            _base_trades(), {"SU26244RMFS2": SCHED_26244}, D(2027, 10, 1))
        self.assertIn("iis_redemption_not_in_file", [f["code"] for f in flags])


class TestInflation(unittest.TestCase):
    FC = {"fca_stats": {
        "2026-12-31": {"kind": "level", "l1_weighted": 6.5},
        "2027-12-31": {"kind": "level", "l1_weighted": 4.0},
        "2026-11-10": {"kind": "event", "predicted_p": 1.0},
    }}

    def test_path_takes_levels_only(self):
        self.assertEqual(ir.inflation_path_from_forecast(self.FC),
                         [(D(2026, 12, 31), 6.5), (D(2027, 12, 31), 4.0)])

    def test_flat_fallback_is_four_percent(self):
        infl = ir.load_inflation(None)
        self.assertEqual(infl["flat_pct"], 4.0)
        self.assertAlmostEqual(ir.cpi_factor(infl, D(2027, 1, 1), D(2028, 1, 1)), 1.04, 3)

    def test_piecewise_path(self):
        infl = {"path": [("2026-12-31", 6.5), ("2027-12-31", 4.0)], "flat_pct": None}
        f = ir.cpi_factor(infl, D(2026, 1, 1), D(2028, 12, 31))
        expected = 1.065 ** (364 / 365) * 1.04 * 1.04
        self.assertAlmostEqual(f, expected, 3)   # после горизонта — последнее значение


class TestFutureFlows(unittest.TestCase):
    LINKER = {
        "coupons": [{"name": "ОФЗ-ИН 52004 17/03/32", "coupondate": "2027-03-24",
                     "startdate": "2026-09-23", "facevalue": 1518.02, "valueprc": 2.5,
                     "value_rub": 18.99}],
        "amortizations": [{"amortdate": "2032-03-17", "value_rub": 1518.02,
                           "initialfacevalue": 1000}],
    }

    def test_fixed_uses_moex_values(self):
        flows, notes = ir.future_flows(SCHED_26244, 100, D(2026, 10, 12), {}, False)
        self.assertEqual(flows, [(D(2027, 3, 24), 5610.0), (D(2027, 9, 22), 100000.0)])
        self.assertEqual(notes, [])

    def test_fixed_unknown_coupon_takes_last_known_with_note(self):
        sched = {"coupons": SCHED_26244["coupons"][:1] + [
            {"coupondate": "2027-03-24", "value_rub": None}], "amortizations": []}
        flows, notes = ir.future_flows(sched, 1, D(2026, 10, 12), {}, False)
        self.assertEqual(flows, [(D(2027, 3, 24), 56.1)])
        self.assertTrue(notes)

    def test_linker_indexes_coupon_and_redemption(self):
        infl = {"path": [], "flat_pct": 4.0}
        flows, _ = ir.future_flows(self.LINKER, 1, D(2026, 10, 12), infl, True)
        (cd, c), (rd, r) = flows
        base_c = 0.025 * 1518.02 * 182 / 365
        self.assertGreater(c, base_c)
        self.assertAlmostEqual(r, 1518.02 * ir.cpi_factor(infl, D(2026, 10, 12), rd), 6)

    def test_linker_zero_inflation_is_real(self):
        zero = {"path": [], "flat_pct": 0.0}
        flows, _ = ir.future_flows(self.LINKER, 1, D(2026, 10, 12), zero, True)
        self.assertAlmostEqual(flows[-1][1], 1518.02, 6)

    def test_linker_redemption_floor_at_initial_face(self):
        sched = {"coupons": [], "amortizations": [
            {"amortdate": "2032-03-17", "value_rub": 900.0, "initialfacevalue": 1000}]}
        flows, _ = ir.future_flows(sched, 1, D(2026, 10, 12),
                                   {"path": [], "flat_pct": 0.0}, True)
        self.assertEqual(flows[-1][1], 1000.0)


class TestFundProxy(unittest.TestCase):
    def test_weighted_and_coverage(self):
        y, cov = ir.fund_proxy_ytm({"A": 60, "B": 30, "C": 10}, {"A": 16.0, "B": 15.0})
        self.assertAlmostEqual(y, round((60 * 16 + 30 * 15) / 90, 2))
        self.assertAlmostEqual(cov, 0.9)


class TestCompute(unittest.TestCase):
    def _run(self, fund_value=None, proxy=(16.0, 1.0)):
        as_of = D(2026, 10, 12)
        trades = _base_trades() + [
            _t("SU26244RMFS2", "Купон", D(2026, 9, 23), 5610.0, qty=100),
            _cash(D(2026, 9, 23), 5610.0),
        ]
        dirty = {"SU26244RMFS2": 80_330.0}
        if fund_value:
            trades += [_t("SBGB", "Покупка", D(2026, 4, 20), 1000.0, qty=100, name="SBGB ETF"),
                       _cash(D(2026, 4, 20), -1000.0)]
            dirty["SBGB"] = fund_value
        rep = build_report(sorted(trades, key=lambda t: t.date), [], as_of=as_of,
                           use_moex=False, with_benchmarks=False)
        return ir.compute(
            sorted(trades, key=lambda t: t.date), as_of=as_of,
            schedules={"SU26244RMFS2": SCHED_26244}, dirty_now=dirty,
            moex_ytm={}, isin_of={"SU26244RMFS2": "RU000A1074G2"},
            infl=ir.load_inflation(None), fund_proxy=proxy, fact_report=rep,
            synth_info=[], flags=[], source_file="t.xlsx")

    def test_forward_and_locked_present(self):
        out = self._run()
        b = out["per_bond"][0]
        self.assertIsNotNone(b["forward_pct"])
        self.assertIsNotNone(b["locked_pct"])
        # Купили дороже, чем стоит сейчас (цена покупки выше текущей + купон) —
        # зафиксированная ниже текущей к погашению.
        self.assertLess(b["locked_pct"], b["forward_pct"])
        self.assertEqual(out["positions"][0]["isin"], "RU000A1074G2")

    def test_account_forward_weights_cash_at_zero_and_fund_by_proxy(self):
        out = self._run(fund_value=1_000.0)
        fw = out["forward"]
        cash = out["cash_rub"]
        exp = (80_330.0 * fw["bonds_irr_pct"] + 1_000.0 * 16.0) / (80_330.0 + 1_000.0 + cash)
        self.assertAlmostEqual(fw["account_pct"], round(exp, 2), 1)

    def test_no_proxy_means_no_account_forward(self):
        out = self._run(fund_value=1_000.0, proxy=(None, 0.0))
        self.assertIsNone(out["forward"]["account_pct"])
        self.assertIn("iis_fund_proxy_unavailable", [f["code"] for f in out["flags"]])


class TestAssembleBlock(unittest.TestCase):
    IIS = {"broker": "БКС", "source_file": "t.xlsx", "file_last_operation": "2026-09-23",
           "as_of": "2026-10-12", "positions": [
               {"secid": "SU26244RMFS2", "isin": "RU000A1074G2", "qty": 100},
               {"secid": "SBGB", "isin": None, "qty": 3520}],
           "cash_rub": 20000.06, "fact": {"xirr": 0.0077}, "forward": {}, "locked": {},
           "flags": [], "synthetic_coupons": []}
    HOLD = [{"ticker": "RU000A1074G2", "account": "iis_3", "qty": 100, "value_rub": 80_000},
            {"ticker": "RU000A1074G2", "account": "main", "qty": 7, "value_rub": 5_600},
            {"ticker": "SBGB", "account": "iis_3", "qty": 3520.0, "value_rub": 53_000}]
    PORT = {"metrics": {"by_account": {"iis_3": {"cash_rub": 20000.53}}}}

    def test_ok_when_file_matches_balance(self):
        b, f = _build_iis_account_returns(self.IIS, self.HOLD, self.PORT)
        self.assertEqual(b["status"], "ok")
        self.assertEqual(b["fact"]["xirr"], 0.0077)
        self.assertEqual(f, [])

    def test_mismatch_drops_numbers(self):
        hold = [dict(h) for h in self.HOLD]
        hold[0]["qty"] = 110        # купили без новой выгрузки
        b, f = _build_iis_account_returns(self.IIS, hold, self.PORT)
        self.assertEqual(b["status"], "mismatch")
        self.assertNotIn("fact", b)
        self.assertEqual(f[-1]["code"], "iis_returns_mismatch")
        self.assertEqual(f[-1]["severity"], "warn")

    def test_deposit_without_purchase_caught_by_cash(self):
        port = {"metrics": {"by_account": {"iis_3": {"cash_rub": 66_654.53}}}}
        b, _ = _build_iis_account_returns(self.IIS, self.HOLD, port)
        self.assertEqual(b["status"], "mismatch")
        self.assertEqual(b["reconciliation"][0]["ticker"], "cash_rub")

    def test_no_balance_is_unverified_not_mismatch(self):
        b, f = _build_iis_account_returns(self.IIS, None, None)
        self.assertEqual(b["status"], "unverified")
        self.assertIn("fact", b)

    def test_synthetic_coupons_surface_as_info(self):
        iis = {**self.IIS, "synthetic_coupons": [{"amount_rub": 5610.0}]}
        _, f = _build_iis_account_returns(iis, self.HOLD, self.PORT)
        self.assertEqual([x["code"] for x in f], ["iis_synthetic_coupons"])

    def test_absent_input_no_block(self):
        self.assertEqual(_build_iis_account_returns(None, self.HOLD, self.PORT), (None, []))


if __name__ == "__main__":
    unittest.main()

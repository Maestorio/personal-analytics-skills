#!/usr/bin/env python3
"""returns.live_basis — вход живой доходности вьюера (2026-10-23).

portfolio_returns кладёт в отчёт потоки XIRR без конечной стоимости (по дням) и позиции, из которых
сложена конечная стоимость; assemble переносит блок в снапшот (returns.live_basis). Контракт:
  • потоки сгруппированы по дням, нулевые дни отброшены, даты — ISO по возрастанию;
  • XIRR, решённый по live_basis на ценах снапшота, = returns_total/returns_restricted.xirr
    (вьюер решает то же уравнение — tools/tests/test_viewer_live_xirr.py);
  • заблокированные помечены blocked (в restricted не входят), позиции с нулём и без стоимости отброшены;
  • assemble: returns.live_basis — как есть; нет в returns.json — null.
Строки доходности на живых ценах (вьюер пересчитывает каждую тем же XIRR, тесты — tools/tests/test_viewer_live_xirr.py):
  • flows_by_type: потоки подпортфеля типа (с первым — стоимостью начала окна), XIRR = returns_by_type_restricted;
  • bond_meta: у облигации с ценой MOEX в positions — face, face_ccy, accrued_rub (qty × (цена/100 × face + accrued_rub) = value_rub);
  • flows_by_ticker (assemble): cashflows записи per_security без терминала, XIRR = xirr_frac записи; by_account — потоки счетов;
  • iis_3.live_basis: потоки и позиции расчёта счёта, XIRR = fact.xirr.
Проверка на реальной выгрузке (2026-10-23, -52, ЦБ офлайн): 366 / 355 дней потоков, 120 позиций, 31 КБ;
XIRR по live_basis совпал с отчётом до округления.
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import assemble_snapshot as asm  # noqa: E402
import iis_returns as iis  # noqa: E402
import portfolio_returns as pr  # noqa: E402

D = dt.date
FT = [(D(2020, 1, 10), -100000.0), (D(2020, 1, 10), -50000.0), (D(2021, 3, 1), -200000.0),
      (D(2022, 2, 1), 30000.0), (D(2022, 2, 1), -30000.0)]          # последний день в сумме 0
FR = [(D(2022, 3, 1), -400000.0), (D(2023, 6, 1), -50000.0)]
MV = {("SBER", "RUB"): {"ticker": "SBER", "type": "stock", "qty": 100.0, "value_rub": 29000.0, "price_source": "moex"},
      ("JPM", "USD"): {"ticker": "JPM", "type": "stock", "qty": 2.0, "value_rub": 0.0, "price_source": "blocked_zero"},
      ("OLD", "RUB"): {"ticker": "OLD", "type": "stock", "qty": 0.0, "value_rub": 0.0, "price_source": "zero_qty"},
      ("RU000A1", "RUB"): {"ticker": "RU000A1", "type": "bond", "qty": 300.0, "value_rub": 310000.0,
                           "price_source": "moex"}}
TODAY = D(2026, 10, 22)
CASH = 20000.0


class LiveBasis(unittest.TestCase):
    def setUp(self):
        self.lb = pr._live_basis(FT, FR, MV, {("JPM", "USD")}, set(), CASH, TODAY)

    def test_flows_by_day(self):
        self.assertEqual(self.lb["flows_total"], [["2020-01-10", -150000.0], ["2021-03-01", -200000.0]])
        self.assertEqual(self.lb["flows_restricted"], [["2022-03-01", -400000.0], ["2023-06-01", -50000.0]])
        self.assertEqual((self.lb["terminal_date"], self.lb["cash_rub"]), ("2026-10-22", 20000.0))

    def test_positions(self):
        self.assertEqual([p["ticker"] for p in self.lb["positions"]], ["JPM", "RU000A1", "SBER"])
        self.assertEqual([p["blocked"] for p in self.lb["positions"]], [True, False, False])

    def test_xirr_identity(self):
        total = CASH + sum(m["value_rub"] for m in MV.values())
        active = CASH + sum(m["value_rub"] for k, m in MV.items() if k != ("JPM", "USD"))
        want_t = pr.xirr(FT + [(TODAY, total)])
        want_r = pr.xirr(FR + [(TODAY, active)])
        lb, d = self.lb, dt.date.fromisoformat
        got_t = pr.xirr([(d(x), a) for x, a in lb["flows_total"]]
                        + [(TODAY, lb["cash_rub"] + sum(p["value_rub"] for p in lb["positions"]))])
        got_r = pr.xirr([(d(x), a) for x, a in lb["flows_restricted"]]
                        + [(TODAY, lb["cash_rub"] + sum(p["value_rub"] for p in lb["positions"] if not p["blocked"]))])
        self.assertAlmostEqual(got_t, want_t, places=8)
        self.assertAlmostEqual(got_r, want_r, places=8)

    def test_assemble_carries_block(self):
        snap = asm.assemble(None, {"live_basis": self.lb}, None, {}, as_of="2026-10-22")
        self.assertEqual(snap["returns"]["live_basis"], self.lb)
        snap0 = asm.assemble(None, {"returns_total": {}}, None, {}, as_of="2026-10-22")
        self.assertIsNone(snap0["returns"]["live_basis"])


class LiveBasisRows(unittest.TestCase):
    """Поля для живой доходности строк: типы, облигации, бумаги, ИИС-3."""

    def test_flows_by_type_and_bond_meta(self):
        meta = {("RU000A1", "RUB"): {"face": 1000.0, "face_ccy": "RUB", "accrued_rub": 42.69}}
        ft = {"stock": FR[:1], "bond": FR, "fund": [], "other": [(D(2022, 3, 1), 0.0)]}
        lb = pr._live_basis(FT, FR, MV, {("JPM", "USD")}, set(), CASH, TODAY, flows_by_type=ft, bond_meta=meta)
        self.assertEqual(sorted(lb["flows_by_type"]), ["bond", "stock"])           # пустой тип и other не нужны
        self.assertEqual(lb["flows_by_type"]["bond"], [["2022-03-01", -400000.0], ["2023-06-01", -50000.0]])
        bond = next(p for p in lb["positions"] if p["ticker"] == "RU000A1")
        self.assertEqual((bond["face"], bond["face_ccy"], bond["accrued_rub"]), (1000.0, "RUB", 42.69))
        self.assertFalse(any("face" in p for p in lb["positions"] if p["type"] != "bond"))
        old = pr._live_basis(FT, FR, MV, {("JPM", "USD")}, set(), CASH, TODAY)      # без новых аргументов — как раньше
        self.assertNotIn("flows_by_type", old)
        self.assertFalse(any("face" in p for p in old["positions"]))

    def test_type_flows_identity(self):
        """XIRR типа = XIRR по _live_flows подпортфеля + терминал Σ value его позиций."""
        def tr(op, day, amt):
            return pr.Trade(ticker="RU000A1ZZZ1", name="Бонд", operation=op, date=day, qty=1, price=100.0, nominal=None,
                            nkd=None, commission=0.0, amount=amt, amount_no_comm=amt, currency="RUB", note="",
                            rub_amount=amt)
        trades = [tr("Покупка", D(2023, 1, 10), -100000.0), tr("Купон", D(2023, 7, 10), 5000.0),
                  tr("Покупка", D(2024, 2, 1), -50000.0), tr("Купон", D(2024, 7, 10), 7000.0)]
        tbt = {"RU000A1ZZZ1": trades}
        mv = {("RU000A1ZZZ1", "RUB"): {"ticker": "RU000A1ZZZ1", "type": "bond", "value_rub": 160000.0}}
        res = pr.subportfolio_metrics(trades, tbt, {"bond"}, D(2022, 3, 1), D(2026, 10, 22), {}, mv)
        flows = res.pop("_live_flows")
        got = pr.xirr(flows + [(D(2026, 10, 22), 160000.0)])
        self.assertIsNotNone(res["xirr"])
        self.assertAlmostEqual(round(got, 4), res["xirr"], places=4)

    def test_bond_meta_from_build_market_values(self):
        tk = "RU000A1ZZZ1"
        key = (tk, "RUB")
        pos = {key: pr.Position(ticker=tk, currency="RUB", name="n", qty=10.0, total_cost_rub=1.0)}
        mk = lambda op: pr.Trade(ticker=tk, name="n", operation=op, date=D(2026, 1, 1), qty=1, price=100.0,  # noqa: E731
                                 nominal=None, nkd=None, commission=0.0, amount=1.0, amount_no_comm=1.0,
                                 currency="RUB", note="")
        tbt = {tk: [mk("Покупка"), mk("Купон")]}

        def fake(cands, verbose=False, accrued_out=None):
            accrued_out.update({tk: 12.5})
            return {tk: 95.0}, {tk: 1000.0}, {tk: "SUR"}, set()
        meta: dict = {}
        from unittest import mock
        with mock.patch.object(pr, "fetch_moex_prices", side_effect=fake), mock.patch.object(pr, "ensure_cbr_rates"):
            res = pr.build_market_values(pos, tbt[tk], tbt, D(2026, 10, 22), {}, bond_meta_out=meta)
        self.assertEqual(meta[key], {"face": 1000.0, "face_ccy": "RUB", "accrued_rub": 12.5})
        m = meta[key]
        self.assertAlmostEqual(res[key]["value_rub"], 10 * (95.0 / 100 * m["face"] + m["accrued_rub"]), places=6)

    def test_flows_by_ticker_identity(self):
        cfs = [("2024-01-10", -100000.0), ("2024-01-10", -5000.0), ("2024-07-10", 4000.0), ("2025-01-10", 4000.0)]
        mv = 110000.0
        full = [(dt.date.fromisoformat(d), a) for d, a in cfs] + [(D(2026, 10, 22), mv)]
        rate = pr.xirr(full)
        per_sec = {"BONDA": {"cashflows": cfs + [("2026-10-22", mv)], "market_value_rub": mv, "xirr_frac": round(rate, 4)},
                   "OLD": {"cashflows": [("2020-01-01", -1000.0), ("2021-01-01", 1500.0)], "market_value_rub": 0.0},
                   "BONDB": {"cashflows": [("2024-01-01", -1.0)], "market_value_rub": 1.0}}
        per_inst = {"BONDA": {"xirr": round(rate, 6)}, "RU000A1AAAA": {"xirr": round(rate, 6), "alias_of": "BONDA"},
                    "OLD": {}, "NOCF": {}}
        out, acc = asm._live_flows_by_ticker(per_sec, per_inst)
        self.assertEqual(sorted(out), ["BONDA", "OLD"])                            # алиас и бумага без потоков — без записи
        self.assertEqual(out["BONDA"][0], ["2024-01-10", -105000.0])               # потоки дня сложены
        self.assertEqual(out["OLD"], [["2020-01-01", -1000.0], ["2021-01-01", 1500.0]])   # терминала нет (стоимость 0) — не отрезается
        self.assertEqual(acc, {})
        got = pr.xirr([(dt.date.fromisoformat(d), a) for d, a in out["BONDA"]] + [(D(2026, 10, 22), mv)])
        self.assertAlmostEqual(got, rate, places=8)

    def test_flows_by_ticker_account(self):
        main = [("2024-01-10", -100000.0)]
        iis_cf = [("2025-03-01", -50000.0), ("2025-09-01", 2000.0)]
        cfs = sorted(main + iis_cf) + [("2026-10-22", 160000.0)]
        per_sec = {"BONDA": {"cashflows": cfs, "market_value_rub": 160000.0}}
        per_inst = {"BONDA": {"by_account": {"main": {}, "iis_3": {}}}}
        out, acc = asm._live_flows_by_ticker(per_sec, per_inst, {"BONDA": {"cashflows": [list(x) for x in iis_cf]}}, "2026-10-22")
        self.assertEqual(acc["BONDA"]["main"], [["2024-01-10", -100000.0]])
        self.assertEqual(acc["BONDA"]["iis_3"], [["2025-03-01", -50000.0], ["2025-09-01", 2000.0]])
        self.assertEqual(len(out["BONDA"]), 3)

    def test_assemble_adds_ticker_flows_only_with_per_security(self):
        lb = {"terminal_date": "2026-10-22", "cash_rub": 0.0, "flows_total": [], "flows_restricted": [], "positions": []}
        per_sec = {"BONDA": {"cashflows": [("2024-01-10", -1000.0), ("2026-10-22", 1100.0)], "market_value_rub": 1100.0,
                             "xirr_frac": 0.04, "qty_now": 1.0}}
        snap = asm.assemble(None, {"live_basis": lb}, per_sec, {}, as_of="2026-10-22")
        self.assertEqual(snap["returns"]["live_basis"]["flows_by_ticker"], {"BONDA": [["2024-01-10", -1000.0]]})
        self.assertNotIn("flows_by_ticker", lb)                                    # вход не мутирован
        snap0 = asm.assemble(None, {"live_basis": lb}, None, {}, as_of="2026-10-22")
        self.assertNotIn("flows_by_ticker", snap0["returns"]["live_basis"])

    def test_iis_live_basis_trim_and_carry(self):
        full = {"terminal_date": "2026-10-22", "cash_rub": 5.0, "flows_total": [["2026-04-17", -1.0]],
                "flows_restricted": [["2026-04-17", -1.0]], "flows_by_type": {"bond": []},
                "positions": [{"ticker": "X", "type": "bond", "qty": 1.0, "value_rub": 1.0}]}
        trimmed = iis._iis_live_basis(full)
        self.assertEqual(sorted(trimmed), ["cash_rub", "flows_total", "positions", "terminal_date"])
        self.assertIsNone(iis._iis_live_basis(None))
        block, _ = asm._build_iis_account_returns({"source_file": "f", "fact": {"xirr": 0.04}, "live_basis": trimmed}, None, None)
        self.assertEqual(block["live_basis"], trimmed)


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
"""Фактический кэш из IntelInvest вместо «Общего баланса» (решение владельца 2026-10-27).

Numbers уходит; в режиме без баланса (assemble --holdings-from-trades) кэш — оценка
(реконструкция по сделкам + прошлое расхождение). Когда оценка устарела, владелец смотрит
свободные деньги ОСНОВНОГО портфеля в IntelInvest (все валюты в рублях) и вносит число —
оно становится фактом и новой опорой расхождения. Контракты:
  • --cash-fact (assemble.cash_fact): cash.total_rub = факт + кэш ИИС-3 (из прошлого снапшота),
    cash.source = owner_intelinvest, cash.fact_date = as_of, cash_reconciliation строится как у
    балансового снапшота (actual = total, current_drift_rub = total − реконструкция);
  • без cash_fact: опора старше CASH_FACT_MAX_AGE_DAYS (14) дн. или неизвестна → warning
    cash_fact_stale; ровно 14 дн. — флага нет; fact_date едет из prev.cash.fact_date (у баланса —
    as_of_date), у trades-prev с внесённым кэшем — его fact_date;
  • balance_carried_from / balance_summary.carried_from — день БАЛАНСА, а не prev, если prev сам
    trades-снапшот (prev.balance_carried_from);
  • с балансом cash_fact игнорируется (info cash_fact_ignored), fact_date балансового = as_of;
  • отрицательный/нечисловой cash_fact — ошибка ввода, снапшот не строится;
  • --cash-fact-iis (assemble.cash_fact_iis, вьюер 3.80.0): факт кеша ИИС-3 подменяет перенос из прошлого
    снапшота; total = ценные бумаги + основной + ИИС-3; fact_date — as_of при любом внесённом факте,
    cash.iis_source = owner_intelinvest (иначе carried_from_prev); возраст оценки основного счёта
    (cash_fact_stale) факт ИИС-3 не освежает; отрицательное — ошибка ввода; с балансом игнорируется;
  • build_snapshot: --cash-fact → аргумент assemble и manifest пакета (replay повторяет);
    find_prev_snapshot берёт trades-снапшот с cash_reconciliation.current_drift_rub, прочие
    trades_holdings пропускает; решение cash_fact_stale — в DECISIONS.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_cash_fact.py
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import assemble_snapshot as asm  # noqa: E402
import build_snapshot as bs  # noqa: E402
from test_trades_mode import PREV, RETURNS  # noqa: E402


def build(prev=PREV, as_of="2026-10-21", **kw):
    return asm.assemble(None, RETURNS, None, {}, prev_snapshot=prev, holdings_from_trades=True,
                        as_of=as_of, **kw)


def codes(s):
    return [f["code"] for f in s["data_quality_flags"]]


class CashFact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = build(cash_fact=330000.0)

    def test_total_is_fact_plus_iis(self):
        self.assertEqual(self.s["cash"]["by_account"]["iis_3"], 20000.0)
        self.assertEqual(self.s["cash"]["by_account"]["main"], 330000.0)
        self.assertEqual(self.s["cash"]["total_rub"], 350000.0)
        self.assertEqual(self.s["cash"]["source"], "owner_intelinvest")
        self.assertEqual(self.s["cash"]["fact_date"], "2026-10-21")
        self.assertIn("330", self.s["cash"]["note"].replace(" ", "").replace("\xa0", ""))

    def test_reconciliation_is_balance_like(self):
        r = self.s["cash_reconciliation"]
        self.assertEqual(r["actual_cash_rub"], 350000.0)
        self.assertEqual(r["reconstructed_cash_rub"], -100000.0)
        self.assertEqual(r["current_drift_rub"], 450000.0)       # total − реконструкция
        self.assertNotIn("cash_fact_stale", codes(self.s))

    def test_stale_flag_absent_and_calc_unchanged_without_fact(self):
        s = build()
        self.assertEqual(s["cash"]["total_rub"], 280000.0)
        self.assertIsNone(s["cash_reconciliation"])
        self.assertEqual(s["cash"]["fact_date"], "2026-10-16")

    def test_negative_or_nan_refused(self):
        for bad in (-1.0, float("nan"), float("inf"), "abc"):
            with self.assertRaises(ValueError):
                build(cash_fact=bad)


class CashFactIis(unittest.TestCase):
    def test_iis_fact_replaces_carry_main_estimate_kept(self):
        base = build()
        s = build(cash_fact_iis=5000.0)
        self.assertEqual(s["cash"]["by_account"]["iis_3"], 5000.0)
        self.assertEqual(s["cash"]["by_account"]["main"], base["cash"]["by_account"]["main"])   # оценка основного та же
        self.assertEqual(s["cash"]["total_rub"], base["cash"]["total_rub"] - 20000.0 + 5000.0)
        self.assertEqual(s["cash"]["fact_date"], "2026-10-21")
        self.assertEqual(s["cash"]["iis_source"], "owner_intelinvest")
        self.assertEqual(s["cash"]["source"], "trades_plus_prev_drift")      # основной счёт всё ещё оценка
        self.assertIsNone(s["cash_reconciliation"])

    def test_both_facts_total_is_securities_plus_main_plus_iis(self):
        s = build(cash_fact=330000.0, cash_fact_iis=7000.0)
        ba = s["cash"]["by_account"]
        self.assertEqual((ba["main"], ba["iis_3"]), (330000.0, 7000.0))
        self.assertEqual(s["cash"]["total_rub"], 337000.0)
        sec = sum(h["value_rub"] for h in s["holdings"] if h.get("status") != "blocked" and isinstance(h.get("value_rub"), (int, float)))
        self.assertAlmostEqual(s["balance_summary"]["total_current_rub_incl_iis"], sec + 337000.0, places=1)
        self.assertEqual(s["cash"]["source"], "owner_intelinvest")

    def test_without_iis_fact_as_before(self):
        s = build(cash_fact=330000.0)
        self.assertEqual(s["cash"]["by_account"]["iis_3"], 20000.0)
        self.assertEqual(s["cash"]["iis_source"], "carried_from_prev")
        self.assertEqual(build()["cash"]["fact_date"], "2026-10-16")        # факта нет — дата прежняя

    def test_zero_is_a_fact(self):
        self.assertEqual(build(cash_fact_iis=0.0)["cash"]["by_account"]["iis_3"], 0.0)

    def test_negative_or_nan_refused(self):
        for bad in (-1.0, float("nan"), float("inf"), "abc"):
            with self.assertRaises(ValueError):
                build(cash_fact_iis=bad)

    def test_iis_fact_does_not_refresh_main_staleness(self):
        s = build(as_of="2026-11-01", cash_fact_iis=5000.0)                 # опора основного — 16.10, 16 дн.
        self.assertIn("cash_fact_stale", codes(s))
        self.assertEqual(s["cash"]["fact_date"], "2026-11-01")

    def test_ignored_with_balance(self):
        portfolio = {"stocks": [], "bonds": [], "funds": [], "other_positions": [], "metrics": {}}
        s = asm.assemble(portfolio, RETURNS, None, {}, prev_snapshot=PREV, as_of="2026-10-21", cash_fact_iis=1.0)
        self.assertIn("cash_fact_ignored", codes(s))

    def test_build_snapshot_manifest_and_replay_argument(self):
        src = (SCRIPTS / "build_snapshot.py").read_text(encoding="utf-8")
        for needle in ('"--cash-fact-iis"', 'manifest.get(key)', '"cash_fact_iis": cash_fact_iis', "cash_fact_iis"):
            self.assertIn(needle, src)


class Staleness(unittest.TestCase):
    def test_older_than_14_days_flags(self):
        s = build(as_of="2026-11-01")                            # 16.10 → 16 дн.
        self.assertIn("cash_fact_stale", codes(s))
        f = next(f for f in s["data_quality_flags"] if f["code"] == "cash_fact_stale")
        self.assertEqual(f["severity"], "warning")
        self.assertIn("2026-10-16", f["message"])
        self.assertIn("16 дн.", f["message"])

    def test_exactly_14_days_no_flag(self):
        self.assertNotIn("cash_fact_stale", codes(build(as_of="2026-10-30")))

    def test_unknown_fact_date_flags(self):
        prev = copy.deepcopy(PREV)
        prev["snapshot_type"] = "trades_holdings"                 # trades-prev без fact_date
        prev["balance_carried_from"] = "2026-10-10"
        self.assertIn("cash_fact_stale", codes(build(prev=prev)))

    def test_fact_date_carried_from_trades_prev(self):
        prev = copy.deepcopy(PREV)
        prev.update(snapshot_type="trades_holdings", as_of_date="2026-10-24", balance_carried_from="2026-10-16")
        prev["cash"]["fact_date"] = "2026-10-24"
        s = build(prev=prev, as_of="2026-11-07")                  # ровно 14 дн. от факта 24.10
        self.assertEqual(s["cash"]["fact_date"], "2026-10-24")
        self.assertNotIn("cash_fact_stale", codes(s))
        self.assertIn("cash_fact_stale", codes(build(prev=prev, as_of="2026-11-08")))


class CarriedDates(unittest.TestCase):
    def test_balance_date_through_trades_prev(self):
        prev = copy.deepcopy(PREV)
        prev.update(snapshot_type="trades_holdings", as_of_date="2026-10-24", balance_carried_from="2026-10-16")
        prev["cash"]["fact_date"] = "2026-10-24"
        s = build(prev=prev, as_of="2026-10-27")
        self.assertEqual(s["balance_carried_from"], "2026-10-16")
        self.assertEqual(s["balance_summary"]["carried_from"], "2026-10-16")
        self.assertIn("2026-10-24", s["cash"]["note"])            # расхождение — из снапшота 24.10

    def test_balance_prev_unchanged(self):
        s = build()
        self.assertEqual(s["balance_carried_from"], "2026-10-16")


class IgnoredWithBalance(unittest.TestCase):
    def test_info_flag_and_balance_cash(self):
        portfolio = {"stocks": [], "bonds": [], "funds": [], "other_positions": [], "metrics": {}}
        s = asm.assemble(portfolio, RETURNS, None, {}, prev_snapshot=PREV, as_of="2026-10-21", cash_fact=1.0)
        self.assertIn("cash_fact_ignored", codes(s))
        self.assertNotEqual(s["cash"].get("source"), "owner_intelinvest")


class BuildSnapshot(unittest.TestCase):
    def test_find_prev_accepts_trades_with_cash_anchor(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "portfolio-2026-10-23.json").write_text(json.dumps({"snapshot_type": None}))
        (tmp / "portfolio-2026-10-24.json").write_text(json.dumps(
            {"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": 1.0}}))
        (tmp / "portfolio-2026-10-25.json").write_text(json.dumps(
            {"snapshot_type": "trades_holdings", "cash_reconciliation": None}))
        (tmp / "portfolio-2026-10-26.json").write_text(json.dumps(
            {"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": None}}))
        self.assertEqual(bs.find_prev_snapshot(tmp, "2026-10-27").name, "portfolio-2026-10-24.json")

    def test_decision_exists(self):
        self.assertIn("cash_fact_stale", bs.DECISIONS)
        self.assertIn("--cash-fact", bs.DECISIONS["cash_fact_stale"])

    def _run(self, argv, manifest_extra=None):
        from test_build_snapshot import make_bundle
        tmp = Path(tempfile.mkdtemp())
        b = make_bundle(tmp)
        if manifest_extra:
            m = json.loads((b / "manifest.json").read_text())
            m.update(manifest_extra)
            (b / "manifest.json").write_text(json.dumps(m))
        return bs.build(bs.parse_args(["--replay", str(b), "--out", str(tmp / "w")] + argv)), tmp

    def test_cli_passes_to_assemble(self):
        s, tmp = self._run(["--cash-fact", "330000"])
        a = next(x for x in s["steps"] if x["step"] == "assemble_snapshot")["args"]
        self.assertEqual(a[a.index("--cash-fact") + 1], "330000.0")
        snap = json.loads(Path(s["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(snap["cash"]["source"], "owner_intelinvest")

    def test_replay_repeats_from_manifest(self):
        s, _ = self._run([], {"cash_fact": 123456.0})
        a = next(x for x in s["steps"] if x["step"] == "assemble_snapshot")["args"]
        self.assertEqual(a[a.index("--cash-fact") + 1], "123456.0")

    def test_manifest_records_cash_fact(self):
        src = Path(bs.__file__).read_text(encoding="utf-8")
        self.assertIn('"cash_fact": cash_fact', src)

    def test_invalid_refused(self):
        for bad in ("-5", "nan", "inf"):
            with self.assertRaises(bs.StepError):
                self._run(["--cash-fact", bad])


if __name__ == "__main__":
    unittest.main()

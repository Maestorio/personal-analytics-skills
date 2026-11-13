#!/usr/bin/env python3
"""Этап 6 ухода от Numbers: паритет «сборка с балансом ↔ сборка без баланса» одного дня.

Контракты (docs/investment/portfolio/numbers-exit-plan.md §4 строка 6, SKILL.md Шаг 7г):
  • одни и те же сделки + «Общий баланс» (синтетический portfolio.json) + plan.json ↔ те же сделки без
    баланса + plan.json: после references/parity-known-diffs-nobalance.yaml расхождений нет (diverged == 0),
    а известные расхождения — только из этого файла (каждая запись с причиной);
  • стоимость FINAMAR в плане, не равная стоимости в балансе, — расхождение (known-diffs его не глотает:
    план и баланс обязаны совпадать, иначе это находка), как и подмена количества акции;
  • build_snapshot.run_parity: явный снапшот (--parity-against) и авто-сверка с portfolio-{as_of}.json,
    если там есть баланс; снапшот того же дня без баланса и сборка с балансом — parity None; нечитаемый
    файл — поле error; в сводке отчёт parity-report.md; копейка float не расхождение.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_parity_nobalance.py
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import assemble_snapshot as asm  # noqa: E402
import build_snapshot as bs  # noqa: E402
import numbers_to_plan as n2p  # noqa: E402
import parity_check as pc  # noqa: E402
import parse_portfolio as pp  # noqa: E402
import test_trades_mode as tm  # noqa: E402

AS_OF = "2026-10-21"
CASH_FACT, CASH_FACT_IIS = 250000.0, 20000.0
KNOWN = bs.PARITY_KNOWN_NOBALANCE


def numbers_portfolio() -> dict:
    """«Общий баланс», разобранный parse_portfolio: те же позиции, что дают сделки, плюс листы целей и IE."""
    port, _ = asm._portfolio_from_trades(tm.RETURNS, tm.PREV, AS_OF, {}, cash_fact=CASH_FACT, cash_fact_iis=CASH_FACT_IIS)
    port.pop("_from_trades", None)
    for o in port["other_positions"]:
        o["Бумага"] = o["Тикер"]
    # by_account — как у parse_portfolio: во «Таблице 1» нет внебиржевого FINAMAR (он в «грязном» остатке кэша),
    # у ИИС-3 funds_rub = 0, а фонд счёта (SBGB) вычтен из его cash_rub
    m = port["metrics"]
    main_other = sum(o["Стоимость"] for o in port["other_positions"] if "ИИС" not in o["Тип"] and o["Тикер"] != "FINAMAR")
    iis_other = sum(o["Стоимость"] for o in port["other_positions"] if "ИИС" in o["Тип"])
    st = sum(x["Стоимость"] for x in port["stocks"])
    bm = sum((b.get("Итого без ИИСа") or 0.0) for b in port["bonds"])
    bi = sum((b.get("Итого на ИИС") or 0.0) for b in port["bonds"])
    m["by_account"] = {
        "main": {"total_rub": m["total_current_rub_excl_iis"], "stocks_rub": round(st, 2), "bonds_rub": round(bm, 2),
                 "funds_rub": round(main_other, 2),
                 "cash_rub": round(m["total_current_rub_excl_iis"] - st - bm - main_other, 2)},
        "iis_3": {"total_rub": m["iis_balance_rub"], "stocks_rub": 0.0, "bonds_rub": round(bi, 2), "funds_rub": 0.0,
                  "cash_rub": round(m["iis_balance_rub"] - bi - iis_other, 2)}}
    port["goals"] = {
        "overall": [{"Тип": "Акции", "Доля": 0.4}, {"Тип": "Облигация", "Доля": 0.5},
                    {"Тип": "Другое", "Доля": 0.05}, {"Тип": "Кеш", "Доля": 0.05}],
        "matrix": [{"Валюта": "RUB", "Бумага": "Акция", "Доля план": 0.4, "Сейчас": 1.0, "Планы": 1.0, "Изменение": 0.0},
                   {"Валюта": "RUB", "Бумага": "Облигация", "Доля план": 0.5, "Сейчас": 1.0},
                   {"Валюта": "RUB", "Бумага": "Кеш", "Доля план": 0.05, "Сейчас": 1.0},
                   {"Валюта": "RUB", "Бумага": "Другое", "Доля план": 0.05, "Сейчас": 1.0}],
        "matrix_iis": [{"Валюта": "RUB", "Бумага": "ИИС", "Доля план": "NA", "Сейчас": 1.0}],
        "bonds_breakdown": [
            {"Тип": "ОФЗ", "Подтип": ">10", "Доля План": 0.6, "_subtype": ">10", "_bucket_key": "ОФЗ/>10",
             "План сумма": 1.0, "Нынешняя Сумма": 1.0, "Изменение": 0.0},
            {"Тип": "ОФЗ", "Подтип": "<10", "Доля План": 0.4, "_subtype": "<10", "_bucket_key": "ОФЗ/<10",
             "План сумма": 1.0, "Нынешняя Сумма": 1.0, "Изменение": 0.0},
            {"Тип": "Итог", "Подтип": None, "Доля План": 1.0, "_subtype": None, "_bucket_key": None}]}
    port["ie_model"] = {"source_sheet": "Invest Era", "extraction_date": AS_OF, "model_total_pct": 5.0,
                        "positions": [{"ticker": "SBER", "target_share_pct": 5.0, "active_in_model": True}]}
    port["ie_actual"] = {"source_sheet": "Акции", "extraction_date": AS_OF, "per_ticker": {"SBER": {
        "ie_new_pct": 5.0, "ie_old_pct": 4.0, "ie_delta_pct": 1.0, "real_share_pct": 100.0, "planned_share_pct": 6.0,
        "user_plan": "KEEP", "user_status": None, "user_note_ie": None, "user_note_ai": None}}}
    port["ie_summary"] = pp.compute_ie_summary(port["ie_model"], port["ie_actual"], ["SBER"])
    return port


class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.port = numbers_portfolio()
        cls.plan = n2p.build_plan(cls.port, source_file=None)
        cls.plan_path = cls.dir / "plan.json"
        cls.plan_path.write_text(json.dumps(cls.plan, ensure_ascii=False), encoding="utf-8")
        cls.with_balance = cls.assemble_balance(cls)
        cls.a_path = cls.dir / f"portfolio-{AS_OF}.json"
        cls.a_path.write_text(json.dumps(cls.with_balance, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assemble_balance(self, port=None, returns=None):
        return asm.assemble(copy.deepcopy(port or self.port), returns or tm.RETURNS, None, {}, balance_path="b.numbers",
                            prev_snapshot=tm.PREV, plan_path=str(self.plan_path), as_of=AS_OF)

    def assemble_nobalance(self, plan_path=None, returns=None):
        return asm.assemble(None, returns or tm.RETURNS, None, {}, prev_snapshot=tm.PREV, holdings_from_trades=True,
                            plan_path=str(plan_path or self.plan_path), as_of=AS_OF,
                            cash_fact=CASH_FACT, cash_fact_iis=CASH_FACT_IIS)

    def diff(self, b):
        a = pc.canon(json.loads(json.dumps(self.with_balance)))
        res = pc.classify(pc.compare(a, pc.canon(json.loads(json.dumps(b)))), pc.load_known(KNOWN))
        return res

    def test_known_file_every_entry_has_reason(self):
        known = pc.load_known(KNOWN)
        self.assertGreater(len(known), 20)
        for k in known:
            self.assertTrue(k.get("reason"), k)
        self.assertTrue(all(k.get("since") for k in known))

    def test_same_day_builds_do_not_diverge(self):
        res = self.diff(self.assemble_nobalance())
        self.assertEqual([p for p, *_ in res["differs"]], [])
        self.assertGreater(len(res["known"]), 5)               # законные различия видны, а не спрятаны

    def test_finamar_value_in_plan_differs_from_balance_is_a_finding(self):
        plan = copy.deepcopy(self.plan)
        for m in plan["manual_positions"]:
            if m["name"] == "FINAMAR":
                m["value_rub"] = 16000.0
        p = self.dir / "plan-finamar.json"
        p.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        res = self.diff(self.assemble_nobalance(plan_path=p))
        paths = [x for x, *_ in res["differs"]]
        self.assertIn("$.holdings[FINAMAR|main].value_rub", paths)
        self.assertFalse([x for x in paths if "known" in x])

    def test_position_qty_change_diverges(self):
        returns = copy.deepcopy(tm.RETURNS)
        returns["snapshot_current"]["positions"][0]["qty"] = 90
        b = self.assemble_nobalance(returns=returns)
        paths = [x for x, *_ in self.diff(b)["differs"]]
        self.assertIn("$.holdings[SBER|main].qty", paths)

    def test_penny_float_noise_is_tolerated(self):
        a, b = {"v": 149999.99}, {"v": 150000.0}
        self.assertEqual([k for _, k, *_ in pc.compare(a, b)], ["tolerated"])
        self.assertEqual([k for _, k, *_ in pc.compare({"v": 1.0}, {"v": 1.02})], ["differs"])


class RunParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Parity
        Parity.setUpClass()
        cls.snap = Parity.assemble_nobalance(Parity)
        cls.snapshots = Parity.dir / "mem" / "Portfolio" / "snapshots"
        cls.snapshots.mkdir(parents=True)
        (cls.snapshots / f"portfolio-{AS_OF}.json").write_text(Parity.a_path.read_text(encoding="utf-8"), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        Parity.tearDownClass()

    def test_explicit_against(self):
        rep = Parity.dir / "r1.md"
        r = bs.run_parity(self.snap, Parity.a_path, None, AS_OF, rep)
        self.assertEqual((r["diverged"], r["same_day"], r["auto"], r["against_date"]), (0, True, False, AS_OF))
        self.assertGreater(r["known"], 0)
        self.assertEqual(r["diverged_paths"], [])
        self.assertTrue(rep.is_file())
        self.assertEqual(r["report_path"], str(rep))
        self.assertGreater(r["matched"], 100)

    def test_auto_with_balance_snapshot_of_same_day(self):
        r = bs.run_parity(self.snap, None, self.snapshots, AS_OF, Parity.dir / "r2.md")
        self.assertTrue(r["auto"])
        self.assertEqual(r["diverged"], 0)

    def test_divergence_lists_paths_up_to_50(self):
        bad = copy.deepcopy(self.snap)
        for h in bad["holdings"]:
            h["qty"] = (h.get("qty") or 0) + 1
        r = bs.run_parity(bad, Parity.a_path, None, AS_OF, Parity.dir / "r3.md")
        self.assertGreater(r["diverged"], 0)
        self.assertLessEqual(len(r["diverged_paths"]), 50)
        self.assertTrue(all(p.startswith("$.") for p in r["diverged_paths"]))

    def test_none_when_no_balance_snapshot_of_that_day(self):
        self.assertIsNone(bs.run_parity(self.snap, None, Parity.dir / "empty", AS_OF, Parity.dir / "r4.md"))
        nb = Parity.dir / "nb" / "Portfolio" / "snapshots"
        nb.mkdir(parents=True)
        (nb / f"portfolio-{AS_OF}.json").write_text(json.dumps(self.snap, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(bs.run_parity(self.snap, None, nb, AS_OF, Parity.dir / "r5.md"))   # там тоже без баланса

    def test_none_when_this_build_has_balance(self):
        self.assertIsNone(bs.run_parity(Parity.with_balance, None, self.snapshots, AS_OF, Parity.dir / "r6.md"))

    def test_unreadable_reference_is_error_field(self):
        bad = Parity.dir / "bad.json"
        bad.write_text("не json", encoding="utf-8")
        r = bs.run_parity(self.snap, bad, None, AS_OF, Parity.dir / "r7.md")
        self.assertIn("error", r)
        self.assertNotIn("diverged", r)

    def test_other_day_is_marked(self):
        other = json.loads(Parity.a_path.read_text(encoding="utf-8"))
        other["as_of_date"] = "2026-10-20"
        p = Parity.dir / "other.json"
        p.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
        r = bs.run_parity(self.snap, p, None, AS_OF, Parity.dir / "r8.md")
        self.assertFalse(r["same_day"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

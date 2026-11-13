#!/usr/bin/env python3
"""Этап 1 ухода от Numbers: numbers_to_plan.py (portfolio.json ↔ plan.json), сверка и plan_check снапшота.

Контракты (docs/investment/portfolio/numbers-exit-plan.md §3.1):
  • build_plan — чистое переложение: 5 классов, матрица только «Доля план» (строки ИИС «NA» не входят),
    9 корзин без итоговой строки (Тип «Итог», _bucket_key null), акции — только с чем-то заданным (проценты как у парсера),
    облигации — активные или с заполненными полями, ручные позиции, пустые строки → null;
  • plan_to_portfolio_fragments возвращает куски в форме portfolio.json; round-trip build_plan → фрагменты → build_plan
    даёт тот же plan;
  • plan_diff: одинаковые → []; одно поле изменено → одно расхождение с верным path; отсутствующий ключ — null;
    CLI --diff печатает и выходит кодом 0;
  • assemble(plan_path=…): plan_check both / plan_only / error; checks: plan_mismatch и plan_unreadable;
  • сквозной тест на реальном разобранном балансе — только если файл есть.
Запуск: python3 skills/portfolio-data-loader/tests/test_numbers_to_plan.py
"""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import checks as ch  # noqa: E402
import numbers_to_plan as n2p  # noqa: E402
from assemble_snapshot import assemble  # noqa: E402

REAL = Path("/private/tmp/claude-501/-Users-alexey-Documents-----------claude-skills/"
            "589fde49-1d53-4681-9481-a7600fa59eb0/scratchpad/balance.json")


def portfolio() -> dict:
    def pt(**kw):
        base = {"ie_new_pct": None, "ie_old_pct": None, "ie_delta_pct": None, "real_share_pct": 1.0,
                "planned_share_pct": None, "user_plan": None, "user_status": None,
                "user_note_ie": None, "user_note_ai": None}
        base.update(kw)
        return base

    def bond(isin, name, typ, sub=None, rating=None, action=None, iis=None, total=0.0):
        return {"Тикер": isin, "Название": name, "Тип": typ, "Подтип": sub, "Рейтинг": rating,
                "Действие": action, "ИИС": iis, "Всего": total}

    return {
        "goals": {
            "overall": [{"Тип": "Акции", "Доля": 0.4}, {"Тип": "Облигация", "Доля": 0.6}],
            "matrix": [{"Валюта": "RUB", "Бумага": "Акция", "Доля план": 0.4, "Сейчас": 123.0},
                       {"Валюта": "RUB", "Бумага": "Облигация", "Доля план": 0.6, "Сейчас": 5.0}],
            "matrix_iis": [{"Валюта": "RUB", "Бумага": "ИИС", "Доля план": "NA", "Сейчас": 1.0}],
            "bonds_breakdown": [
                {"Тип": "USD", "Подтип": None, "Доля План": 0.5, "_subtype": None, "_bucket_key": "USD"},
                {"Тип": "ОФЗ", "Подтип": ">10", "Доля План": 0.5, "_subtype": ">10", "_bucket_key": "ОФЗ/>10"},
                {"Тип": "Итог", "Подтип": None, "Доля План": 1.0, "_subtype": None, "_bucket_key": None},
            ],
        },
        "ie_model": {"source_sheet": "Invest Era", "extraction_date": "2026-10-27", "model_total_pct": 6.0,
                     "positions": [{"ticker": "SBER", "target_share_pct": 6.0, "active_in_model": True}]},
        "ie_actual": {"source_sheet": "Акции", "extraction_date": "2026-10-27", "per_ticker": {
            "SBER": pt(planned_share_pct=10.0, ie_new_pct=6.0, ie_old_pct=5.0, user_plan="KEEP"),
            "YDEX": pt(planned_share_pct=0.0, user_status="WAIT", user_note_ai="  заметка  "),
            "LENT": pt(),
        }},
        "stocks": [],
        "bonds": [
            bond("RU000A0000A1", "ОФЗ А", "ОФЗ", ">10", total=10.0, iis=4.0),
            bond("RU000A0000B2", "Корп Б", "КОРП", "A", rating="A", action="BUY", total=0.0),
            bond("RU000A0000C3", "Пустая", "USD", total=0.0),
        ],
        "other_positions": [{"Тип": "USD - Другое", "Бумага": "TGLD", "Стоимость": 382320.0},
                            {"Тип": "RUB - Другое", "Бумага": "FINAMAR", "Стоимость": 270000.0}],
    }


class Build(unittest.TestCase):
    def setUp(self):
        self.p = portfolio()
        self.plan = n2p.build_plan(self.p, source_file="/x/Общий баланс.numbers")

    def test_header(self):
        pl = self.plan
        self.assertEqual(pl["schema_version"], "plan@1.0")
        self.assertEqual((pl["generated_at"], pl["updated_at"]), ("2026-10-27", "2026-10-27"))
        self.assertEqual(pl["updated_by"], "numbers_to_plan.py")
        self.assertEqual(pl["source"], {"kind": "numbers", "file": "Общий баланс.numbers",
                                        "extraction_date": "2026-10-27"})

    def test_date_fallback_to_now(self):
        p = portfolio()
        p["ie_actual"].pop("extraction_date")
        p["ie_model"].pop("extraction_date")
        self.assertEqual(n2p.build_plan(p, source_file=None, now="2026-01-02")["updated_at"], "2026-01-02")

    def test_classes_and_matrix(self):
        self.assertEqual(self.plan["classes"], [{"class": "Акции", "share": 0.4}, {"class": "Облигация", "share": 0.6}])
        self.assertEqual([m["class"] for m in self.plan["matrix"]], ["Акция", "Облигация"])   # без строки ИИС
        self.assertEqual(self.plan["matrix"][0], {"class": "Акция", "currency": "RUB", "share": 0.4})

    def test_total_row_not_in_buckets(self):
        self.assertEqual([b["key"] for b in self.plan["bond_buckets"]], ["USD", "ОФЗ/>10"])
        self.assertEqual(self.plan["bond_buckets"][1], {"key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10", "share": 0.5})

    def test_stocks_only_with_something_set(self):
        self.assertEqual(sorted(self.plan["stocks"]), ["SBER", "YDEX"])      # LENT пуст — нет
        s = self.plan["stocks"]["SBER"]
        self.assertEqual((s["plan_pct"], s["ie_new_pct"], s["ie_old_pct"], s["user_plan"]), (10.0, 6.0, 5.0, "KEEP"))
        self.assertEqual(self.plan["stocks"]["YDEX"]["plan_pct"], 0.0)       # 0 — это задано
        self.assertEqual(self.plan["stocks"]["YDEX"]["note_ai"], "заметка")  # пробелы срезаны
        self.assertIsNone(s["note_ie"])

    def test_ie_model_without_source_sheet(self):
        self.assertNotIn("source_sheet", self.plan["ie_model"])
        self.assertEqual(self.plan["ie_model"]["positions"][0]["ticker"], "SBER")

    def test_bonds_active_or_filled(self):
        self.assertEqual(sorted(self.plan["bonds"]), ["RU000A0000A1", "RU000A0000B2"])
        self.assertEqual(self.plan["bonds"]["RU000A0000A1"],
                         {"action": None, "iis_qty": 4.0, "name": "ОФЗ А", "rating": None, "subtype": ">10", "type": "ОФЗ"})
        self.assertEqual(self.plan["bonds"]["RU000A0000B2"]["action"], "BUY")

    def test_manual_positions(self):
        self.assertEqual(self.plan["manual_positions"][1], {"name": "FINAMAR", "type": "RUB - Другое", "value_rub": 270000.0})

    def test_keys_sorted(self):
        txt = json.dumps(self.plan, ensure_ascii=False)
        self.assertLess(txt.index('"bond_buckets"'), txt.index('"stocks"'))
        self.assertEqual(list(self.plan["stocks"]["SBER"]), sorted(self.plan["stocks"]["SBER"]))


class RoundTrip(unittest.TestCase):
    def test_fragments_shape_and_roundtrip(self):
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        fr = n2p.plan_to_portfolio_fragments(plan)
        self.assertEqual(fr["goals"]["overall"], p["goals"]["overall"])
        self.assertEqual([r["_bucket_key"] for r in fr["goals"]["bonds_breakdown"]], ["USD", "ОФЗ/>10"])
        self.assertEqual(fr["goals"]["matrix"][0], {"Валюта": "RUB", "Бумага": "Акция", "Доля план": 0.4})
        self.assertEqual(fr["other_positions"], p["other_positions"])
        self.assertEqual(fr["ie_model"], p["ie_model"])
        self.assertEqual(fr["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"], 10.0)
        self.assertEqual(fr["bonds_typing"]["RU000A0000A1"]["ИИС"], 4.0)
        self.assertEqual(fr["bonds_typing"]["RU000A0000B2"]["Действие"], "BUY")
        # собрать portfolio из фрагментов → тот же plan
        q = {"goals": fr["goals"], "ie_model": fr["ie_model"], "ie_actual": fr["ie_actual"],
             "other_positions": fr["other_positions"],
             "bonds": [{"Тикер": k, "Название": plan["bonds"][k]["name"], "Всего": 1, **v}
                       for k, v in fr["bonds_typing"].items()]}
        self.assertEqual(n2p.build_plan(q, source_file=None), plan)


class Diff(unittest.TestCase):
    def test_same_is_empty(self):
        p = portfolio()
        self.assertEqual(n2p.plan_diff(p, n2p.build_plan(p, source_file="a")), [])

    def test_one_field_changed(self):
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        plan["stocks"]["SBER"]["plan_pct"] = 8.0
        plan["updated_at"] = "2030-01-01"                    # метаданные не считаются
        self.assertEqual(n2p.plan_diff(p, plan), [{"path": "stocks.SBER.plan_pct", "numbers": 10.0, "plan": 8.0}])

    def test_float_tolerance(self):
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        plan["classes"][0]["share"] += 1e-12
        self.assertEqual(n2p.plan_diff(p, plan), [])

    def test_missing_key_is_null_and_sorted(self):
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        del plan["stocks"]["YDEX"]
        plan["bond_buckets"][1]["share"] = 0.4
        d = n2p.plan_diff(p, plan)
        self.assertEqual([x["path"] for x in d], sorted(x["path"] for x in d))
        self.assertIn({"path": "stocks.YDEX.plan_pct", "numbers": 0.0, "plan": None}, d)
        self.assertIn({"path": "bond_buckets.ОФЗ/>10.share", "numbers": 0.5, "plan": 0.4}, d)

    def test_extraction_date_of_model_ignored(self):
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        plan["ie_model"]["extraction_date"] = "2026-11-01"
        self.assertEqual(n2p.plan_diff(p, plan), [])

    def test_ie_import_additions_ignored(self):
        """Неактивные позиции (общий портфель IE), cash_pct, industry/target_price_*, ie_history — не расхождения."""
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        pos = plan["ie_model"]["positions"]
        pos[0].update({"industry": "Банки", "target_price_rub": 400.0, "target_price_lt_rub": 500.0})
        pos.append({"ticker": "ENPG", "name": "En+", "target_share_pct": None, "active_in_model": False,
                    "target_price_rub": 10.0})
        plan["ie_model"].update({"cash_pct": 7.0, "cash_ticker": "LQDT"})
        plan["ie_history"] = [{"ts": "2026-10-27T10:00:00Z", "date": "2026-10-27", "ticker": "SBER",
                               "was": 5.0, "now": 6.0, "reason": None, "source": "site"}]
        before = copy.deepcopy(plan)
        self.assertEqual(n2p.plan_diff(p, plan), [])
        self.assertEqual(plan, before)                       # файл плана не изменён
        pos[0]["target_share_pct"] = 99.0                    # активная позиция с другой долей — расхождение
        self.assertEqual([d["path"] for d in n2p.plan_diff(p, plan)], ["ie_model.positions.SBER.target_share_pct"])


class Cli(unittest.TestCase):
    def test_out_and_diff_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "portfolio.json").write_text(json.dumps(portfolio()), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = n2p.main(["--portfolio", str(d / "portfolio.json"), "--out", str(d / "plan.json")])
            self.assertEqual(rc, 0)
            plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
            plan["stocks"]["SBER"]["plan_pct"] = 1.0
            (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = n2p.main(["--portfolio", str(d / "portfolio.json"), "--diff", str(d / "plan.json")])
            self.assertEqual(rc, 0)
            self.assertIn("stocks.SBER.plan_pct", buf.getvalue())
            self.assertIn("Расхождений: 1", buf.getvalue())

    def test_stdout_without_out(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.json").write_text(json.dumps(portfolio()), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                n2p.main(["--portfolio", str(Path(d) / "p.json")])
            self.assertEqual(json.loads(buf.getvalue())["schema_version"], "plan@1.0")


class CliGuard(unittest.TestCase):
    """--out не затирает правки сайта (этап 2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "portfolio.json").write_text(json.dumps(portfolio()), encoding="utf-8")
        self.out = self.d / "plan.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _site_plan(self, **kw):
        plan = n2p.build_plan(portfolio(), source_file="Общий баланс.numbers")
        plan.update(updated_by="hub-api", updated_at="2026-11-02T10:00:00")
        plan["stocks"]["SBER"]["plan_pct"] = 7.0
        plan.update(kw)
        self.out.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return self.out.read_text(encoding="utf-8")

    def _run(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = n2p.main(["--portfolio", str(self.d / "portfolio.json"), "--out", str(self.out), *extra])
        return rc, buf.getvalue()

    def test_site_file_not_overwritten(self):
        before = self._site_plan()
        rc, out = self._run()
        self.assertEqual(rc, 3)
        self.assertEqual(self.out.read_text(encoding="utf-8"), before)
        self.assertIn("plan.json правился на сайте (hub-api, 2026-11-02T10:00:00) — не перезаписываю; расхождения:", out)
        self.assertIn("stocks.SBER.plan_pct", out)
        self.assertEqual(list(self.d.glob("plan.json.bak-*")), [])

    def test_force_overwrites_with_backup(self):
        before = self._site_plan()
        rc, _ = self._run("--force")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["updated_by"], "numbers_to_plan.py")
        baks = list(self.d.glob("plan.json.bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(encoding="utf-8"), before)

    def test_own_file_overwritten_silently(self):
        self._run()
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertNotIn("не перезаписываю", out)
        self.assertEqual(list(self.d.glob("plan.json.bak-*")), [])

    def test_source_file_inherited_and_overridable(self):
        self._site_plan()
        self._run("--force")
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["source"]["file"], "Общий баланс.numbers")
        self._run("--source-file", "Другой.numbers")
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["source"]["file"], "Другой.numbers")


class AssemblePlanPrimary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.p = portfolio()
        plan = n2p.build_plan(self.p, source_file=None)
        plan["stocks"]["SBER"]["plan_pct"] = 8.0
        plan["bonds"]["RU000A0000A1"]["action"] = "SELL"
        plan["classes"][0]["share"] = 0.5
        self.f = self.d / "plan.json"
        self.f.write_text(json.dumps(plan), encoding="utf-8")
        self.numbers_copy = copy.deepcopy(self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_pieces_replace_numbers(self):
        snap = assemble(self.p, None, None, None, plan_path=str(self.f), plan_primary=True, as_of="2026-10-27")
        self.assertEqual(snap["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"], 8.0)
        self.assertEqual(snap["ie_actual"]["per_ticker"]["SBER"]["real_share_pct"], 1.0)   # факт Numbers цел
        self.assertEqual(snap["balance_summary"]["goals_overall"][0]["Доля"], 0.5)
        pc = snap["plan_check"]
        self.assertEqual((pc["source"], pc["n_diff"]), ("plan_primary", 3))
        self.assertEqual(self.p, self.numbers_copy)                                        # вход не мутирован

    def test_single_diff_and_without_flag_numbers_win(self):
        plan = n2p.build_plan(self.p, source_file=None)
        plan["stocks"]["SBER"]["plan_pct"] = 8.0
        self.f.write_text(json.dumps(plan), encoding="utf-8")
        snap = assemble(self.p, None, None, None, plan_path=str(self.f), plan_primary=True, as_of="2026-10-27")
        self.assertEqual(snap["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"], 8.0)
        self.assertEqual((snap["plan_check"]["source"], snap["plan_check"]["n_diff"]), ("plan_primary", 1))
        snap = assemble(self.p, None, None, None, plan_path=str(self.f), as_of="2026-10-27")
        self.assertEqual(snap["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"], 10.0)
        self.assertEqual(snap["plan_check"]["source"], "both")

    def test_bonds_typing_by_isin_and_missing_stay(self):
        out = n2p.apply_plan_primary(self.p, json.loads(self.f.read_text(encoding="utf-8")))
        by = {b["Тикер"]: b for b in out["bonds"]}
        self.assertEqual(by["RU000A0000A1"]["Действие"], "SELL")
        self.assertEqual(by["RU000A0000B2"]["Действие"], "BUY")        # нет в плане (неактивная, но заполнена — есть)
        self.assertEqual(by["RU000A0000C3"]["Тип"], "USD")             # нет в плане → как в Numbers
        self.assertEqual(out["goals"]["matrix"][0]["Сейчас"], 123.0)   # факт-поле матрицы сохранено

    def test_no_numbers_takes_plan_pieces(self):
        returns = {"fx_rates_asof": {}, "by_account": {}}
        snap = assemble(None, returns, None, None, plan_path=str(self.f), plan_primary=True, as_of="2026-10-27")
        self.assertEqual(snap["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"], 8.0)
        self.assertIsNone(snap["balance_summary"])        # без portfolio балансовая сводка не строится (этап 6)
        self.assertEqual(snap["plan_check"]["source"], "plan_only")


class AssemblePlanCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.p = portfolio()
        self.plan = n2p.build_plan(self.p, source_file=None)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan_file(self, plan) -> str:
        f = self.d / "plan.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        return str(f)

    def test_both_with_diff(self):
        self.plan["stocks"]["SBER"]["plan_pct"] = 8.0
        snap = assemble(self.p, None, None, None, plan_path=self._plan_file(self.plan), as_of="2026-10-27")
        pc = snap["plan_check"]
        self.assertEqual((pc["source"], pc["plan_file"], pc["n_diff"]), ("both", "plan.json", 1))
        self.assertEqual(pc["plan_updated_at"], "2026-10-27")
        self.assertEqual(pc["diff"][0]["path"], "stocks.SBER.plan_pct")

    def test_both_clean(self):
        snap = assemble(self.p, None, None, None, plan_path=self._plan_file(self.plan), as_of="2026-10-27")
        self.assertEqual((snap["plan_check"]["source"], snap["plan_check"]["n_diff"]), ("both", 0))

    def test_no_plan_no_block(self):
        self.assertNotIn("plan_check", assemble(self.p, None, None, None, as_of="2026-10-27"))

    def test_plan_only_without_numbers(self):
        returns = {"fx_rates_asof": {}, "by_account": {}}
        snap = assemble(None, returns, None, None, plan_path=self._plan_file(self.plan), as_of="2026-10-27")
        pc = snap["plan_check"]
        self.assertEqual((pc["source"], pc["n_diff"], pc["diff"]), ("plan_only", 0, []))

    def test_unreadable_does_not_fail(self):
        bad = self.d / "plan.json"
        bad.write_text("{не json", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            snap = assemble(self.p, None, None, None, plan_path=str(bad), as_of="2026-10-27")
        self.assertEqual(snap["plan_check"]["source"], "error")
        self.assertIn("error", snap["plan_check"])
        self.assertIn("plan.json", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            snap2 = assemble(self.p, None, None, None, plan_path=str(self.d / "нет.json"), as_of="2026-10-27")
        self.assertEqual(snap2["plan_check"]["source"], "error")


def _snap(plan_check):
    return {"schema_version": "2.0", "as_of_date": "2026-10-16", "holdings": [], "data_quality_flags": [],
            "plan_check": plan_check}


class ChecksPlan(unittest.TestCase):
    def _ids(self, pc):
        ctx = ch.Ctx(snap=_snap(pc), prev=None, trades=None, as_of="2026-10-16")
        return [(r["id"], r["level"], r["message_ru"]) for r in ch.check_snapshot(ctx)
                if r["id"].startswith("plan_")]

    def test_mismatch_warns_with_first_8_paths(self):
        diff = [{"path": f"stocks.T{i}.plan_pct", "numbers": 1, "plan": 2} for i in range(10)]
        res = self._ids({"source": "both", "n_diff": 10, "diff": diff})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][:2], ("plan_mismatch", "warning"))
        self.assertIn("10 полям", res[0][2])
        self.assertIn("stocks.T7.plan_pct", res[0][2])
        self.assertNotIn("stocks.T8.plan_pct", res[0][2])

    def test_clean_and_absent_are_silent(self):
        self.assertEqual(self._ids({"source": "both", "n_diff": 0, "diff": []}), [])
        self.assertEqual(self._ids(None), [])
        self.assertEqual(self._ids({"source": "plan_only", "n_diff": 0, "diff": []}), [])

    def test_unreadable_warns(self):
        res = self._ids({"source": "error", "error": "битый"})
        self.assertEqual([r[:2] for r in res], [("plan_unreadable", "warning")])


class TradesModeApply(unittest.TestCase):
    """apply_plan_primary(trades_mode=True): «баланс» из сделок (этап 6) — типизация по Тикер или ISIN,
    количество на ИИС-3 и пустые поля плана не затираются, ручные позиции плана в other_positions не вливаются."""

    def test_trades_mode(self):
        plan = n2p.build_plan(portfolio(), source_file=None)
        synthetic = {"bonds": [{"Тикер": "SU26238RMFS4", "ISIN": "RU000A0000A1", "Тип": "КОРП", "Подтип": None,
                                "Рейтинг": "BB", "Действие": None, "ИИС": 130.0, "Всего": 210.0},
                               {"Тикер": "RU000A0000B2", "Тип": "ОФЗ", "ИИС": 7.0, "Всего": 5.0}],
                     "other_positions": [{"Тикер": "TGLD", "Название": "TGLD", "Стоимость": 5000.0, "Тип": ""}]}
        out = n2p.apply_plan_primary(synthetic, plan, trades_mode=True)
        b1, b2 = out["bonds"]
        self.assertEqual((b1["Тип"], b1["Подтип"], b1["ИИС"], b1["Рейтинг"]), ("ОФЗ", ">10", 130.0, "BB"))   # по ISIN; ИИС цел
        self.assertEqual((b2["Тип"], b2["ИИС"], b2["Действие"]), ("КОРП", 7.0, "BUY"))                                              # по Тикер
        self.assertEqual(out["other_positions"], synthetic["other_positions"])                              # без дублей TGLD/FINAMAR
        self.assertEqual(out["ie_model"]["positions"][0]["ticker"], "SBER")
        full = n2p.apply_plan_primary(copy.deepcopy(synthetic), plan)
        self.assertEqual(len(full["other_positions"]), 3)                                                   # балансный режим как раньше


class TradesModePlanBucket(unittest.TestCase):
    """Корзина облигации — пара (Тип, Подтип) из одного источника: если в плане у бумаги задан тип, подтип берётся из плана
    тоже (в т.ч. пустой), а не из прошлого снапшота (Акрон: тип CNY из плана + подтип AA+ из переноса → «CNY/AA+»)."""

    @staticmethod
    def _apply(plan_bonds, bond):
        plan = n2p.build_plan(portfolio(), source_file=None)
        plan["bonds"] = plan_bonds
        return n2p.apply_plan_primary({"bonds": [bond]}, plan, trades_mode=True)["bonds"][0]

    def test_plan_type_without_subtype_overrides_carried_subtype(self):
        b = self._apply({"RU000A10F108": {"type": "CNY", "subtype": None}},
                        {"Тикер": "AKRON", "ISIN": "RU000A10F108", "Тип": "КОРП", "Подтип": "AA+", "Рейтинг": "AA+"})
        self.assertEqual((b["Тип"], b["Подтип"]), ("CNY", None))
        self.assertEqual(b["Рейтинг"], "AA+")                       # None плана остальные поля не затирает

    def test_plan_type_and_subtype_both_from_plan(self):
        b = self._apply({"X1": {"type": "КОРП", "subtype": "A"}},
                        {"Тикер": "X1", "Тип": "КОРП", "Подтип": "AA+"})
        self.assertEqual((b["Тип"], b["Подтип"]), ("КОРП", "A"))

    def test_not_in_plan_keeps_carried(self):
        b = self._apply({"OTHER": {"type": "CNY", "subtype": None}},
                        {"Тикер": "X2", "ISIN": "RU0002", "Тип": "КОРП", "Подтип": "AA+"})
        self.assertEqual((b["Тип"], b["Подтип"]), ("КОРП", "AA+"))


@unittest.skipUnless(REAL.exists(), "нет реального balance.json")
class RealBalance(unittest.TestCase):
    def test_real(self):
        p = json.loads(REAL.read_text(encoding="utf-8"))
        plan = n2p.build_plan(p, source_file="Общий баланс.numbers")
        self.assertEqual(len(plan["classes"]), 5)
        self.assertEqual(len(plan["bond_buckets"]), 9)
        self.assertGreaterEqual(sum(1 for s in plan["stocks"].values() if s["plan_pct"] is not None), 20)
        self.assertEqual(n2p.plan_diff(p, plan), [])
        self.assertEqual(n2p.plan_diff(p, json.loads(json.dumps(plan))), [])
        q = copy.deepcopy(p)
        q["ie_actual"]["per_ticker"]["SBER"]["planned_share_pct"] = 99.0
        self.assertEqual([d["path"] for d in n2p.plan_diff(q, plan)], ["stocks.SBER.plan_pct"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

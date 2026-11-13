#!/usr/bin/env python3
"""
test_carry_over_weekly.py — тесты для scripts/carry_over_weekly.py (RPA-23).

Скрипт переносит неизменённый анализ из прошлого weekly-review в свежий стаб и применяет
маленький delta.json недели. Тесты работают на синтетических YAML: без сети и без Claude-Memory.

Покрывает: заполнение TODO_LLM из прошлого (скаляры, вложенные словари, списки-плейсхолдеры),
приоритет стаба над прошлым, новые и выбывшие бумаги, операции delta (set/append/unset/
catalyst_add/remove/update/drop_items/all_items), ошибки на опечатку в поле и на правку
посчитанного стабом, предупреждения (катализатор с окном до review_date, число прошлой
недели в *_basis), carried_over по правилу R-COV, prior_verdict, сброс недельных журналов,
порядок ключей и формат выходного YAML, коды выхода CLI.

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_carry_over_weekly.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

import yaml

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "skills", "ru-portfolio-advisor", "scripts", "carry_over_weekly.py")

_spec = importlib.util.spec_from_file_location("carry_over_weekly", SCRIPT)
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)

T = "TODO_LLM_x"


def cat(cid="c1", p=0.5, window="2027-Q1"):
    return {"id": cid, "kind": "binary", "trigger": f"событие {cid}", "date_window": window, "p": p,
            "upside_pct": None, "downside_pct": None, "source": "advisor_estimate",
            "source_quality": "MEDIUM", "macro_dependency": "A"}


def bond_stub(price=101.5, ytm=12.0, extra_items=()):
    items = {}
    for isin, name in (("RU1", "Бонд-1"), ("RU2", "Бонд-2")) + tuple(extra_items):
        items[isin] = {
            "name": name, "value_rub": 1000.0, "current_price": price, "ytm_pct": ytm,
            "issuer": T, "credit_quality": T, "verification_priority": T,
            "fundamental_sources": [{"url": T, "label": T, "accessed_date": "2026-10-16"}],
            "catalyst": [{"id": T, "trigger": T, "date_window": T, "p": T, "source": T}],
            "advisor_verdict": T, "advisor_verdict_confidence": T, "advisor_verdict_basis": T,
        }
    return {
        "schema_version": 2, "type": "weekly-bonds-review", "review_date": "2026-10-16",
        "snapshot_id": "portfolio-2026-10-16.json", "producer": T, "macro_source": T,
        "summary": {"bonds_total_rub": 2000.0, "weighted_ytm_pct": {"value": ytm, "ci_pct": T}},
        "per_bond": items,
        "key_risks": [{"id": T, "severity": T, "note": T}],
        "caveats": [{"severity": T, "message": T}],
        "sources": {"moex_iss": "MOEX 2026-10-16", "macro_input": T},
    }


def bond_prior(price=100.0, ytm=11.0):
    items = {}
    for isin, name, verdict in (("RU1", "Бонд-1", "HOLD"), ("RU2", "Бонд-2", "ADD"), ("RU3", "Бонд-3", "SELL")):
        items[isin] = {
            "name": name, "value_rub": 900.0, "current_price": price, "ytm_pct": ytm,
            "issuer": f"Эмитент {isin}", "credit_quality": "HIGH", "verification_priority": "LOW",
            "fundamental_sources": [{"url": f"https://e/{isin}", "label": "отчёт", "accessed_date": "2026-10-08"}],
            "catalyst": [cat("c1", 0.4, "2027-Q2"), cat("c2", 0.2, "2026-Q4")],
            "advisor_verdict": verdict, "advisor_verdict_confidence": 0.7,
            "advisor_verdict_basis": f"Цена {price:.2f}, YTM {ytm:.1f}%".replace(".", ",") + ". Тезис жив.",
            "prior_verdict": "BUY", "user_constraints": [{"id": "u1", "active": True}],
        }
    return {
        "schema_version": 2, "type": "weekly-bonds-review", "review_date": "2026-10-08",
        "snapshot_id": "portfolio-2026-10-08.json", "producer": "claude-sonnet-5-5", "macro_source": "ЦБ 11.09",
        "summary": {"bonds_total_rub": 2700.0, "weighted_ytm_pct": {"value": ytm, "ci_pct": [6.0, 20.0], "basis": "срез main"},
                    "red_flag_count": 0},
        "per_bond": items,
        "trades_since_prior": [{"isin": "RU9", "action": "matured"}],
        "closed_positions": [{"isin": "RU9"}],
        "carried_over_from": "weekly-review-bond-2026-10-01.yaml",
        "key_risks": [{"id": "r1", "severity": "HIGH", "note": "кредитный цикл"}],
        "caveats": [{"severity": "LOW", "message": "оговорка"}],
        "sources": {"moex_iss": "MOEX 2026-10-08", "macro_input": "macro-2026-09-17.yaml", "web": [{"url": "https://w"}]},
        "revision": {"number": 1, "date": "2026-10-08", "note": "первая"},
    }


def stock_stub():
    return {
        "schema_version": 2, "type": "weekly-stocks-review", "review_date": "2026-10-16",
        "producer": T,
        "portfolio_summary": {"total_stocks_value_rub": 5000.0},
        "per_stock": {"SBER": {"price_rub": 300.0, "weight_real_pct": 10.0, "fundamental_score": T,
                               "fundamental_score_sources": [{"url": T, "label": T, "accessed_date": "2026-10-16"}],
                               "div_sources": [{"url": T, "label": T, "accessed_date": "2026-10-16"}],
                               "catalyst": [{"id": T, "trigger": T}], "advisor_verdict": T,
                               "advisor_verdict_basis": T}},
        "key_risks": [{"id": T}], "caveats": [{"message": T}], "sources": {"macro_input": T},
    }


def stock_prior():
    return {
        "schema_version": 2, "type": "weekly-stocks-review", "review_date": "2026-10-08", "producer": "m",
        "portfolio_summary": {"total_stocks_value_rub": 4900.0},
        "key_risks": [{"id": "k"}], "caveats": [{"message": "m"}], "sources": {"macro_input": "x.yaml"},
        "period": {"from": "2026-10-01", "to": "2026-10-08"},
        "coverage": {"checked_this_run": ["SBER"]},
        "amendments": [{"date": "2026-10-08", "version": 2}],
        "per_stock": {"SBER": {"price_rub": 290.0, "weight_real_pct": 9.5, "fundamental_score": "HIGH",
                               "fundamental_score_sources": [{"url": "https://s", "label": "МСФО", "accessed_date": "2026-10-08"}],
                               "div_sources": [{"url": "https://d", "label": "див", "accessed_date": "2026-10-08"}],
                               "catalyst": [cat("buyback")], "advisor_verdict": "HOLD",
                               "advisor_verdict_basis": "Цена 290,00 пока без изменений.",
                               "p_outperform_3m": 0.55, "carried_over": True}},
    }


def run(kind, stub, prior, delta=None):
    return co.carry_over(kind, copy.deepcopy(stub), copy.deepcopy(prior), delta, "prior.yaml")


class TestFill(unittest.TestCase):

    def test_todo_scalars_and_nested_filled_from_prior(self):
        doc, rep = run("bond", bond_stub(), bond_prior())
        it = doc["per_bond"]["RU1"]
        self.assertEqual(it["issuer"], "Эмитент RU1")
        self.assertEqual(it["advisor_verdict"], "HOLD")
        self.assertEqual(it["advisor_verdict_confidence"], 0.7)
        self.assertEqual(doc["summary"]["weighted_ytm_pct"]["ci_pct"], [6.0, 20.0])
        self.assertGreater(rep["filled_from_prior_leaves"], 20)

    def test_placeholder_lists_carried_whole_with_prior_dates(self):
        doc, _ = run("bond", bond_stub(), bond_prior())
        it = doc["per_bond"]["RU1"]
        self.assertEqual([c["id"] for c in it["catalyst"]], ["c1", "c2"])
        # accessed_date берётся прошлый: «сегодняшняя» дата заготовки стаба не штампует перенесённый источник
        self.assertEqual(it["fundamental_sources"][0]["accessed_date"], "2026-10-08")
        self.assertEqual(it["fundamental_sources"][0]["url"], "https://e/RU1")
        self.assertEqual(doc["key_risks"][0]["id"], "r1")
        self.assertEqual(doc["caveats"][0]["message"], "оговорка")

    def test_stub_numbers_win_over_prior(self):
        doc, _ = run("bond", bond_stub(price=101.5, ytm=12.0), bond_prior(price=100.0, ytm=11.0))
        it = doc["per_bond"]["RU1"]
        self.assertEqual(it["current_price"], 101.5)
        self.assertEqual(it["ytm_pct"], 12.0)
        self.assertEqual(it["value_rub"], 1000.0)
        self.assertEqual(doc["summary"]["bonds_total_rub"], 2000.0)
        self.assertEqual(doc["sources"]["moex_iss"], "MOEX 2026-10-16")
        self.assertEqual(doc["review_date"], "2026-10-16")

    def test_prior_only_item_fields_carried_and_prior_verdict_rolls(self):
        doc, rep = run("bond", bond_stub(), bond_prior())
        it = doc["per_bond"]["RU2"]
        self.assertNotIn("user_constraints", it)  # срез производный — не переносится (schema.md §4.2)
        self.assertEqual(it["prior_verdict"], "ADD")  # вердикт прошлого обзора, а не прошлый prior_verdict
        self.assertIn("RU1", {x["item"] for x in rep["need_reconcile_or_recheck"]})

    def test_nested_prior_only_fields_carried_and_reported(self):
        doc, rep = run("bond", bond_stub(), bond_prior())
        self.assertEqual(doc["summary"]["weighted_ytm_pct"]["basis"], "срез main")
        self.assertIn("summary.weighted_ytm_pct.basis", rep["nested_prior_only_fields_carried"])
        self.assertEqual(doc["sources"]["web"], [{"url": "https://w"}])

    def test_identity_fields_not_carried(self):
        doc, rep = run("bond", bond_stub(), bond_prior())
        self.assertTrue(doc["producer"].startswith("TODO_LLM"))
        self.assertTrue(doc["macro_source"].startswith("TODO_LLM"))
        self.assertTrue(doc["sources"]["macro_input"].startswith("TODO_LLM"))
        self.assertEqual(sorted(rep["todo_remaining_paths"]), ["macro_source", "producer", "sources.macro_input"])
        self.assertTrue(any(w["type"] == "todo_identity" for w in rep["warnings"]))

    def test_stock_kind_end_to_end(self):
        doc, rep = run("stock", stock_stub(), stock_prior())
        s = doc["per_stock"]["SBER"]
        self.assertEqual(s["price_rub"], 300.0)
        self.assertEqual(s["fundamental_score"], "HIGH")
        self.assertEqual(s["p_outperform_3m"], 0.55)
        self.assertNotIn("prior_verdict", s)  # у акций ключа не было — не придумываем
        self.assertEqual(doc["period"], {"from": "2026-10-08", "to": "2026-10-16"})
        self.assertEqual(doc["amendments"], [])
        self.assertIn("amendments", rep["top_blocks_reset_to_empty"])

    def test_wrong_type_is_error(self):
        with self.assertRaises(co.DeltaError):
            co.carry_over("stock", bond_stub(), bond_prior(), None, "p.yaml")


class TestNewAndDropped(unittest.TestCase):

    def test_new_item_keeps_todo_and_is_reported(self):
        doc, rep = run("bond", bond_stub(extra_items=(("RU7", "Новый"),)), bond_prior())
        self.assertTrue(doc["per_bond"]["RU7"]["advisor_verdict"].startswith("TODO_LLM"))
        self.assertEqual(rep["new_items_need_analysis"], [{"key": "RU7", "name": "Новый"}])
        self.assertGreater(rep["todo_remaining_by_item"]["RU7"], 5)

    def test_dropped_item_goes_to_report_only(self):
        doc, rep = run("bond", bond_stub(), bond_prior())
        self.assertNotIn("RU3", doc["per_bond"])
        self.assertEqual([d["key"] for d in rep["dropped_items"]], ["RU3"])
        self.assertEqual(rep["dropped_items"][0]["advisor_verdict"], "SELL")
        # причину скрипт не выдумывает: журналы недели пустые, пока их не задаст модель
        self.assertEqual(doc["closed_positions"], [])
        self.assertEqual(doc["trades_since_prior"], [])

    def test_drop_items_by_delta(self):
        stub = bond_stub(extra_items=(("RU7", "Фонд"),))
        doc, rep = run("bond", stub, bond_prior(), {"drop_items": ["RU7"]})
        self.assertNotIn("RU7", doc["per_bond"])
        self.assertEqual(rep["dropped_by_delta"], ["RU7"])
        self.assertEqual(rep["new_items_need_analysis"], [])
        with self.assertRaises(co.DeltaError):
            run("bond", stub, bond_prior(), {"drop_items": ["ZZZ"]})


class TestDelta(unittest.TestCase):

    def test_set_append_unset(self):
        delta = {"per_item": {"RU1": {
            "set": {"advisor_verdict": "TRIM", "advisor_verdict_basis": "новое обоснование"},
            "append": {"fundamental_sources": [{"url": "https://new", "label": "н", "accessed_date": "2026-10-16"}]},
            "unset": ["prior_verdict"]}}}
        doc, rep = run("bond", bond_stub(), bond_prior(), delta)
        it = doc["per_bond"]["RU1"]
        self.assertEqual(it["advisor_verdict"], "TRIM")
        self.assertEqual(it["advisor_verdict_basis"], "новое обоснование")
        self.assertEqual([s["url"] for s in it["fundamental_sources"]], ["https://e/RU1", "https://new"])
        self.assertNotIn("prior_verdict", it)
        self.assertEqual(doc["per_bond"]["RU2"]["advisor_verdict"], "ADD")  # соседа не тронули
        self.assertEqual(rep["delta_applied"]["item_set"], 2)

    def test_catalyst_ops(self):
        delta = {"per_item": {"RU1": {
            "catalyst_remove": ["c2"],
            "catalyst_update": {"c1": {"p": 0.9, "date_window": "2027-Q3"}},
            "catalyst_add": [cat("c3", 0.1, "2028")]}}}
        doc, rep = run("bond", bond_stub(), bond_prior(), delta)
        cats = {c["id"]: c for c in doc["per_bond"]["RU1"]["catalyst"]}
        self.assertEqual(sorted(cats), ["c1", "c3"])
        self.assertEqual(cats["c1"]["p"], 0.9)
        self.assertEqual(cats["c1"]["trigger"], "событие c1")  # остальные поля сохранены
        self.assertEqual([c["id"] for c in doc["per_bond"]["RU2"]["catalyst"]], ["c1", "c2"])

    def test_catalyst_add_replaces_placeholder_on_new_item(self):
        delta = {"per_item": {"RU7": {"catalyst_add": [cat("n1")]}}}
        doc, _ = run("bond", bond_stub(extra_items=(("RU7", "Новый"),)), bond_prior(), delta)
        self.assertEqual([c["id"] for c in doc["per_bond"]["RU7"]["catalyst"]], ["n1"])

    def test_all_items_append(self):
        src = {"url": "https://common", "label": "общий", "accessed_date": "2026-10-16"}
        doc, _ = run("bond", bond_stub(), bond_prior(), {"all_items": {"append": {"fundamental_sources": [src]}}})
        for k in ("RU1", "RU2"):
            self.assertEqual(doc["per_bond"][k]["fundamental_sources"][-1], src)

    def test_top_set_and_append(self):
        delta = {"top": {"set": {"producer": "claude-x", "summary.weighted_ytm_pct.ci_pct": [7.0, 30.0],
                                 "sources.macro_input": "macro.yaml"},
                         "append": {"caveats": [{"severity": "LOW", "message": "новая"}]}}}
        doc, rep = run("bond", bond_stub(), bond_prior(), delta)
        self.assertEqual(doc["producer"], "claude-x")
        self.assertEqual(doc["summary"]["weighted_ytm_pct"]["ci_pct"], [7.0, 30.0])
        self.assertEqual([c["message"] for c in doc["caveats"]], ["оговорка", "новая"])
        self.assertEqual(doc["sources"]["macro_input"], "macro.yaml")
        self.assertEqual(rep["todo_remaining_paths"], ["macro_source"])

    def test_typo_in_item_field_is_error(self):
        with self.assertRaises(co.DeltaError) as cm:
            run("bond", bond_stub(), bond_prior(), {"per_item": {"RU1": {"set": {"advisor_verdit_basis": "x"}}}})
        self.assertIn("advisor_verdit_basis", str(cm.exception))
        self.assertIn("advisor_verdict_basis", str(cm.exception))  # перечень допустимых помогает найти опечатку

    def test_typo_in_top_path_is_error(self):
        for path in ("producr", "summary.weighted_ytm_pct.cii_pct", "summery.bonds_total_rub"):
            with self.assertRaises(co.DeltaError, msg=path):
                run("bond", bond_stub(), bond_prior(), {"top": {"set": {path: 1}}})

    def test_unknown_operation_and_section_are_errors(self):
        for delta in ({"per_item": {"RU1": {"sett": {}}}}, {"top": {"replace": {}}}, {"items": {}}):
            with self.assertRaises(co.DeltaError, msg=str(delta)):
                run("bond", bond_stub(), bond_prior(), delta)

    def test_unknown_item_and_dropped_item_are_errors(self):
        with self.assertRaises(co.DeltaError):
            run("bond", bond_stub(), bond_prior(), {"per_item": {"NOPE": {"set": {"advisor_verdict": "HOLD"}}}})
        with self.assertRaises(co.DeltaError) as cm:
            run("bond", bond_stub(), bond_prior(), {"per_item": {"RU3": {"set": {"advisor_verdict": "HOLD"}}}})
        self.assertIn("выбыла", str(cm.exception))

    def test_stub_owned_field_protected_unless_override(self):
        with self.assertRaises(co.DeltaError):
            run("bond", bond_stub(), bond_prior(), {"per_item": {"RU1": {"set": {"ytm_pct": 5.0}}}})
        with self.assertRaises(co.DeltaError):
            run("bond", bond_stub(), bond_prior(), {"top": {"set": {"summary.bonds_total_rub": 1.0}}})
        doc, _ = run("bond", bond_stub(), bond_prior(),
                     {"per_item": {"RU1": {"set": {"ytm_pct": 5.0}, "override_stub": ["ytm_pct"]}}})
        self.assertEqual(doc["per_bond"]["RU1"]["ytm_pct"], 5.0)

    def test_catalyst_op_errors(self):
        for ops in ({"catalyst_remove": ["zzz"]}, {"catalyst_update": {"zzz": {"p": 1}}},
                    {"catalyst_update": {"c1": {"pp": 1}}}, {"catalyst_add": [cat("c1")]},
                    {"catalyst_add": [{"trigger": "без id"}]}):
            with self.assertRaises(co.DeltaError, msg=str(ops)):
                run("bond", bond_stub(), bond_prior(), {"per_item": {"RU1": ops}})

    def test_append_to_non_list_is_error(self):
        with self.assertRaises(co.DeltaError):
            run("bond", bond_stub(), bond_prior(), {"top": {"append": {"producer": ["x"]}}})


class TestWarningsAndFlags(unittest.TestCase):

    def test_window_end_parsing(self):
        self.assertEqual(co.window_end("2026-Q4 to 2027-Q2"), date(2027, 6, 30))
        self.assertEqual(co.window_end("2026-10..2026-12"), date(2026, 12, 31))
        self.assertEqual(co.window_end("2026-10 .. 2026-11"), date(2026, 11, 30))
        self.assertEqual(co.window_end("2026-11-19..2026-11-30"), date(2026, 11, 30))
        self.assertEqual(co.window_end("2026-Q1"), date(2026, 3, 31))
        self.assertEqual(co.window_end("2027"), date(2027, 12, 31))
        self.assertEqual(co.window_end("2028-02"), date(2028, 2, 29))
        self.assertIsNone(co.window_end("когда-нибудь"))
        self.assertIsNone(co.window_end(None))

    def test_past_catalyst_warned_not_changed(self):
        prior = bond_prior()
        prior["per_bond"]["RU1"]["catalyst"] = [cat("old", 0.5, "2026-09"), cat("ok", 0.5, "2026-Q4")]
        doc, rep = run("bond", bond_stub(), prior)
        past = [w for w in rep["warnings"] if w["type"] == "catalyst_in_past"]
        self.assertEqual([(w["item"], w["catalyst"]) for w in past], [("RU1", "old")])
        self.assertEqual(len(doc["per_bond"]["RU1"]["catalyst"]), 2)  # скрипт ничего не удаляет сам

    def test_event_date_takes_precedence(self):
        prior = bond_prior()
        c = cat("ev", 0.5, "2027-Q4")
        c["event_date"] = "2026-10-10"
        prior["per_bond"]["RU1"]["catalyst"] = [c]
        _, rep = run("bond", bond_stub(), prior)
        self.assertEqual([w["catalyst"] for w in rep["warnings"] if w["type"] == "catalyst_in_past"], ["ev"])

    def test_basis_with_stale_number_flagged_text_untouched(self):
        doc, rep = run("bond", bond_stub(price=101.5, ytm=12.0), bond_prior(price=100.0, ytm=11.0))
        w = [x for x in rep["warnings"] if x["type"] == "basis_stale_number" and x["item"] == "RU1"]
        self.assertEqual({x["numeric_field"] for x in w}, {"current_price", "ytm_pct"})
        self.assertEqual(doc["per_bond"]["RU1"]["advisor_verdict_basis"], "Цена 100,00, YTM 11,0%. Тезис жив.")

    def test_basis_not_flagged_when_model_rewrote_it_or_numbers_equal(self):
        delta = {"per_item": {"RU1": {"set": {"advisor_verdict_basis": "Цена 101,50, YTM 12,0%."}}}}
        _, rep = run("bond", bond_stub(price=101.5, ytm=12.0), bond_prior(price=100.0, ytm=11.0), delta)
        self.assertFalse([w for w in rep["warnings"] if w.get("item") == "RU1" and w["type"] == "basis_stale_number"])
        _, rep2 = run("bond", bond_stub(price=100.0, ytm=11.0), bond_prior(price=100.0, ytm=11.0))
        self.assertFalse([w for w in rep2["warnings"] if w["type"] == "basis_stale_number"])

    def test_number_in_text_matches_fractional_tokens_only(self):
        self.assertTrue(co.number_in_text(67.25, "Цена 67,25 → 67,95"))
        self.assertTrue(co.number_in_text(9.2359, "9,24% облигаций"))
        self.assertFalse(co.number_in_text(10.0, "куплено 10 штук"))   # целые токены — шум
        self.assertFalse(co.number_in_text(67.25, "Цена 167,25"))
        self.assertFalse(co.number_in_text(None, "67,25"))

    def test_carried_over_marked_without_fresh_source_and_cleared_with_one(self):
        stub_prior = stock_prior()
        doc, rep = run("stock", stock_stub(), stub_prior)
        self.assertIs(doc["per_stock"]["SBER"]["carried_over"], True)
        self.assertEqual(rep["carried_over_marked"], ["SBER"])
        fresh = {"per_item": {"SBER": {"append": {"fundamental_score_sources": [
            {"url": "https://n", "label": "н", "accessed_date": "2026-10-15"}]}}}}
        doc2, rep2 = run("stock", stock_stub(), stub_prior, fresh)
        self.assertNotIn("carried_over", doc2["per_stock"]["SBER"])
        self.assertEqual(rep2["carried_over_cleared"], ["SBER"])
        old_edge = {"per_item": {"SBER": {"append": {"div_sources": [
            {"url": "https://n", "label": "н", "accessed_date": "2026-10-08"}]}}}}
        doc3, _ = run("stock", stock_stub(), stub_prior, old_edge)  # 8 окт < 9 окт: вне окна 7 дней
        self.assertIs(doc3["per_stock"]["SBER"]["carried_over"], True)

    def test_explicit_carried_over_in_delta_respected(self):
        delta = {"per_item": {"SBER": {"set": {"carried_over": False}}}}
        doc, _ = run("stock", stock_stub(), stock_prior(), delta)
        self.assertIs(doc["per_stock"]["SBER"]["carried_over"], False)

    def test_week_bound_blocks_warned_until_set(self):
        # coverage с 2026-10-26 не переносится вовсе (RUN_ONLY_BLOCKS) — задаётся только через delta
        doc, rep = run("stock", stock_stub(), stock_prior())
        self.assertNotIn("coverage", doc)
        self.assertIn("coverage", rep["top_blocks_reset_to_empty"])
        doc2, _ = run("stock", stock_stub(), stock_prior(), {"top": {"set": {"coverage": {"checked_this_run": []}}}})
        self.assertEqual(doc2["coverage"], {"checked_this_run": []})

    def test_carried_over_from_points_to_prior_file(self):
        doc, _ = run("bond", bond_stub(), bond_prior())
        self.assertEqual(doc["carried_over_from"], "prior.yaml")


class TestOutputFormat(unittest.TestCase):

    def test_key_order_follows_prior_and_stub_only_keys_inserted(self):
        prior = bond_prior()
        stub = bond_stub()
        stub["per_bond"]["RU1"]["asset_extra"] = 1
        doc, _ = run("bond", stub, prior)
        top = list(doc)
        self.assertLess(top.index("per_bond"), top.index("trades_since_prior"))
        self.assertLess(top.index("caveats"), top.index("sources"))
        self.assertEqual(top.index("snapshot_id"), list(prior).index("snapshot_id"))
        keys = list(doc["per_bond"]["RU1"])
        self.assertEqual(keys[:3], ["name", "value_rub", "current_price"])
        self.assertIn("asset_extra", keys)

    def test_yaml_text_format(self):
        doc, _ = run("bond", bond_stub(), bond_prior())
        text = co.dump_yaml(doc)
        self.assertIn("schema_version: 2\n", text)          # число, не строка
        self.assertIn("review_date: '2026-10-16'", text)    # дата строкой в кавычках
        self.assertNotIn("&id", text)                       # без якорей
        self.assertNotIn("*id", text)
        back = yaml.safe_load(text)
        self.assertEqual(back, doc)
        self.assertIn("Бонд-1", text)                       # кириллица как есть, без \u-экранирования


class TestCli(unittest.TestCase):

    def _write(self, d, name, data):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(co.dump_yaml(data) if name.endswith(".yaml") else json.dumps(data, ensure_ascii=False))
        return path

    @staticmethod
    def _load_yaml(path):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _cli(self, *args):
        return subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)

    def test_cli_roundtrip_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            stub = self._write(d, "stub.yaml", bond_stub())
            prior = self._write(d, "prior.yaml", bond_prior())
            out = os.path.join(d, "out.yaml")
            rep = os.path.join(d, "rep.json")
            r = self._cli("--kind", "bond", "--stub", stub, "--prior", prior, "--output", out, "--report", rep)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._load_yaml(out)["per_bond"]["RU1"]["advisor_verdict"], "HOLD")
            with open(rep, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["todo_remaining"], 3)
            # --strict: остались TODO_LLM (producer…) -> 1
            r = self._cli("--kind", "bond", "--stub", stub, "--prior", prior, "--output", out, "--strict")
            self.assertEqual(r.returncode, 1)
            # опечатка в delta -> 2 и вывод не пишется
            os.remove(out)
            bad = self._write(d, "bad.json", {"per_item": {"RU1": {"set": {"advisor_verdit": "x"}}}})
            r = self._cli("--kind", "bond", "--stub", stub, "--prior", prior, "--delta", bad, "--output", out)
            self.assertEqual(r.returncode, 2)
            self.assertIn("advisor_verdit", r.stderr)
            self.assertFalse(os.path.exists(out))
            # битый JSON -> 2
            broken = os.path.join(d, "broken.json")
            with open(broken, "w") as f:
                f.write("{не json")
            r = self._cli("--kind", "bond", "--stub", stub, "--prior", prior, "--delta", broken, "--output", out)
            self.assertEqual(r.returncode, 2)
            # нет файла -> 2
            r = self._cli("--kind", "bond", "--stub", os.path.join(d, "none.yaml"), "--prior", prior, "--output", out)
            self.assertEqual(r.returncode, 2)

    def test_cli_full_delta_gives_zero_todo(self):
        with tempfile.TemporaryDirectory() as d:
            stub = self._write(d, "stub.yaml", stock_stub())
            prior = self._write(d, "prior.yaml", stock_prior())
            delta = self._write(d, "delta.json", {"top": {"set": {"producer": "m2", "sources.macro_input": "x"}}})
            out = os.path.join(d, "out.yaml")
            r = self._cli("--kind", "stock", "--stub", stub, "--prior", prior, "--delta", delta,
                          "--output", out, "--strict")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertNotIn("TODO_LLM", f.read())


class TestConstraintSliceNotCarried(unittest.TestCase):
    """Срез ограничений не переносится из прошлого обзора: его строит reconcile_constraints.py и кладёт delta."""

    def test_slice_fields_dropped_from_prior(self):
        prior = bond_prior()
        prior["per_bond"]["RU1"].update(unconstrained_verdict="BUY", unconstrained_verdict_confidence=0.7,
                                       advisor_verdict_constraints=["условие u1"])
        doc, _ = run("bond", bond_stub(), prior)
        for f in ("user_constraints", "unconstrained_verdict", "unconstrained_verdict_confidence",
                  "advisor_verdict_constraints"):
            self.assertNotIn(f, doc["per_bond"]["RU1"], f)

    def test_gate_copy_and_priority_not_carried(self):
        """R28 (03.11): копия статуса гейта из прошлого обзора не переносится и через delta не задаётся; пустой
        приоритет стаба (null — его ставит stamp-report) прошлым значением не заполняется."""
        prior = bond_prior()
        prior["per_bond"]["RU1"]["gate_status_snapshot"] = {"status": "new_position", "as_of": "2026-08-06"}
        stub = bond_stub()
        for it in stub["per_bond"].values():
            it["verification_priority"] = None
        doc, _ = run("bond", stub, prior)
        self.assertNotIn("gate_status_snapshot", doc["per_bond"]["RU1"])
        self.assertIsNone(doc["per_bond"]["RU1"]["verification_priority"])
        with self.assertRaises(co.DeltaError):
            run("bond", stub, prior, {"per_item": {"RU1": {"set": {"gate_status_snapshot": {"status": "x"}}}}})

    def test_obsolete_top_blocks_not_carried_nor_accepted(self):
        """03.11: упразднённые блоки старого формата (состояние условий пишет только сайт) не переносятся из прошлого
        обзора и через delta не принимаются; в отчёте — top_blocks_dropped_obsolete."""
        prior = stock_prior()
        blocks = {"conditions_evaluated": {"written_back": True, "fired": []}, "gate_review_directives": [{"t": 1}],
                  "proposed_gate_review_directives": [{"t": 2}], "conditions_state": [{"id": "x"}],
                  "conditions_mutations_applied": ["m"]}
        prior.update(blocks)
        doc, rep = run("stock", stock_stub(), prior)
        self.assertFalse(set(blocks) & set(doc), set(blocks) & set(doc))
        self.assertEqual(rep["top_blocks_dropped_obsolete"], sorted(blocks))
        self.assertFalse(set(blocks) & set(rep["top_blocks_carried_unchanged"]))
        for k in blocks:
            for op in ("set", "append"):
                with self.assertRaises(co.DeltaError) as cm:
                    run("stock", stock_stub(), stock_prior(), {"top": {op: {k: [] if op == "append" else {}}}})
                self.assertIn("упразднённый блок", str(cm.exception))

    def test_delta_sets_fresh_slice(self):
        rec = {"derived": True, "as_of": "2026-10-16", "condition_id": "u1", "summary": "условие u1"}
        doc, _ = run("bond", bond_stub(), bond_prior(), {"per_item": {"RU1": {"set": {"user_constraints": [rec]}}}})
        self.assertEqual(doc["per_bond"]["RU1"]["user_constraints"], [rec])


class TestPruneSources(unittest.TestCase):
    """RPA-37: перенесённые источники копились (обзор акций 136 → 214 КБ за три месяца)."""

    def item(self):
        old = [{"url": f"https://old/{i}", "label": str(i), "accessed_date": f"2026-09-{10 + i:02d}"} for i in range(6)]
        return {"fundamental_sources": old + [{"url": "https://fresh", "label": "f", "accessed_date": "2026-10-15"}],
                "catalyst": [{"id": "c", "source": "https://old/0 — первоисточник"}],
                "advisor_verdict_basis": "см. https://old/1."}

    def test_keeps_fresh_referenced_and_newest(self):
        it = self.item()
        n = co.prune_sources(it, ["fundamental_sources"], "2026-10-09", 2)
        urls = [s["url"] for s in it["fundamental_sources"]]
        # 0 — из катализатора, 1 — из basis, 5 и 4 — два самых новых без ссылок, fresh — свежий
        self.assertEqual(urls, ["https://old/0", "https://old/1", "https://old/4", "https://old/5", "https://fresh"])
        self.assertEqual(n, 2)

    def test_keep_zero_leaves_only_fresh_and_referenced(self):
        it = self.item()
        co.prune_sources(it, ["fundamental_sources"], "2026-10-09", 0)
        self.assertEqual(len(it["fundamental_sources"]), 3)

    def test_carry_over_reports_and_no_prune(self):
        prior = bond_prior()
        prior["per_bond"]["RU1"]["fundamental_sources"] = self.item()["fundamental_sources"][:6]
        _, rep = run("bond", bond_stub(), prior)
        self.assertEqual(rep["sources_pruned"]["by_item"].get("RU1"), 3)
        doc, rep = co.carry_over("bond", copy.deepcopy(bond_stub()), copy.deepcopy(prior), None, "p.yaml",
                                 keep_old_sources=None)
        self.assertEqual(rep["sources_pruned"]["total"], 0)
        self.assertEqual(len(doc["per_bond"]["RU1"]["fundamental_sources"]), 6)


class TestCoverageAlwaysSettable(unittest.TestCase):
    """Сухой прогон 26.10: у облигаций coverage нет ни в стабе, ни в прошлом обзоре — delta его отвергала,
    а валидатор с 27.10 его требует (RPA-34)."""

    def test_top_set_coverage_without_prior_block(self):
        prior = bond_prior(); prior.pop("coverage", None)
        cov = {"method": "sweep_collect", "tickers_total": 2, "checked_this_run": ["RU1", "RU2"]}
        doc, _ = run("bond", bond_stub(), prior, {"top": {"set": {"coverage": cov}}})
        self.assertEqual(doc["coverage"]["method"], "sweep_collect")


class TestCoverageNotCarried(unittest.TestCase):
    """Прошлое coverage.method: sweep_collect пропустило бы обзор без свежего сбора мимо валидатора."""

    def test_prior_coverage_dropped(self):
        prior = bond_prior(); prior["coverage"] = {"method": "sweep_collect", "checked_this_run": ["RU1"]}
        doc, rep = run("bond", bond_stub(), prior)
        self.assertNotIn("coverage", doc)
        self.assertIn("coverage", rep["top_blocks_reset_to_empty"])


class TestRatingCheckedAt(unittest.TestCase):
    """credit_rating_checked_at: стаб пишет null, дата прошлого обзора переносится без изменения, delta обновляет."""

    def _pair(self):
        stub = bond_stub(); prior = bond_prior()
        for it in stub["per_bond"].values():
            it["credit_rating_checked_at"] = None
        prior["per_bond"]["RU1"]["credit_rating_checked_at"] = "2026-10-01"
        return stub, prior

    def test_carried_unchanged(self):
        stub, prior = self._pair()
        doc, _ = run("bond", stub, prior)
        self.assertEqual(doc["per_bond"]["RU1"]["credit_rating_checked_at"], "2026-10-01")
        self.assertIsNone(doc["per_bond"]["RU2"]["credit_rating_checked_at"])   # в прошлом не было — остаётся null

    def test_carried_when_stub_lacks_field(self):
        stub, prior = self._pair()
        for it in stub["per_bond"].values():
            del it["credit_rating_checked_at"]
        doc, _ = run("bond", stub, prior)
        self.assertEqual(doc["per_bond"]["RU1"]["credit_rating_checked_at"], "2026-10-01")

    def test_delta_updates(self):
        stub, prior = self._pair()
        doc, _ = run("bond", stub, prior, {"per_item": {"RU1": {"set": {"credit_rating_checked_at": "2026-11-03"}},
                                                        "RU2": {"set": {"credit_rating_checked_at": "2026-11-03"}}}})
        self.assertEqual(doc["per_bond"]["RU1"]["credit_rating_checked_at"], "2026-11-03")
        self.assertEqual(doc["per_bond"]["RU2"]["credit_rating_checked_at"], "2026-11-03")

    def test_example_delta_mentions_field_for_bond(self):
        stub, _ = self._pair()
        self.assertIn('"credit_rating_checked_at":', co.example_delta("bond", stub))
        self.assertNotIn('"credit_rating_checked_at":', co.example_delta("stock", stock_stub()))


class TestStubNullField(unittest.TestCase):
    """Сухой прогон 26.10: YTM ОФЗ 29008 (флоатер) стаб не считает, валидатор требует непустое значение."""

    def test_warns_with_prior_value(self):
        stub = bond_stub(); stub["per_bond"]["RU1"]["ytm_pct"] = None
        prior = bond_prior(); prior["per_bond"]["RU1"]["ytm_pct"] = 13.2
        _, rep = run("bond", stub, prior)
        w = [x for x in rep["warnings"] if x["type"] == "stub_null_field"]
        self.assertEqual([(x["item"], x["field"], x["prior_value"]) for x in w], [("RU1", "ytm_pct", 13.2)])
        _, rep = run("bond", stub, prior, {"per_item": {"RU1": {"set": {"ytm_pct": 13.0}}}})
        self.assertFalse([x for x in rep["warnings"] if x["type"] == "stub_null_field"])


class TestExampleDelta(unittest.TestCase):
    """RPA-40: 26.10.2026 ~15 команд ушло на выяснение формата delta по шапке скрипта."""

    def test_example_uses_stub_key_and_is_valid_delta(self):
        txt = co.example_delta("bond", bond_stub())
        self.assertIn("бумага RU1 — из стаба", txt)
        delta = json.loads(txt[txt.index("\n{") + 1:])
        self.assertEqual(set(delta), {"top", "per_item", "all_items", "drop_items"})
        self.assertIn("RU1", delta["per_item"])
        self.assertIn("fundamental_sources", delta["per_item"]["RU1"]["append"])
        self.assertIn("Поля стаба", txt)

    def test_example_without_stub_and_cli(self):
        self.assertIn("TICKER", co.example_delta("stock", None))
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(co.main(["--kind", "stock", "--example"]), 0)
        self.assertIn("Образец delta.json", buf.getvalue())
        with self.assertRaises(SystemExit):  # без --example нужны stub/prior/output
            with contextlib.redirect_stderr(io.StringIO()):
                co.main(["--kind", "stock"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

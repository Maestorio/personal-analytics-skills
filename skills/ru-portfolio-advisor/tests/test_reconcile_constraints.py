#!/usr/bin/env python3
"""Тесты reconcile_constraints.py — срез ограничений обзора из условий (модуль (а)) и плана владельца.

Срез производный (schema.md §4.2): из прошлого обзора ничего не переносится, новое ограничение не заводится.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_reconcile_constraints.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "reconcile_constraints.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "_shared-references"))

import constraint_engine as ce  # noqa: E402
from reconcile_constraints import PLAN_BLOCKS_BUY, build, slice_for_key  # noqa: E402

TODAY = "2026-11-02"


def row(cid, key, status="pending", verdict_now="HOLD", on_trigger="TRIM", waits_owner=False, active=True,
        trigger=None, valid_until=None, text="срезать до плана"):
    return {"id": cid, "key": key, "status": status, "active": active, "waits_owner": waits_owner,
            "verdict_now": verdict_now, "verdict_on_trigger": on_trigger, "text": text, "note": None,
            "trigger": trigger or {"type": "price_above", "value": 100}, "valid_until": valid_until}


class SliceRules(unittest.TestCase):
    def test_pending_condition_pins_verdict_and_records_slice(self):
        r = slice_for_key("AAAA", {"verdict": "BUY", "confidence": 0.7},
                          [row("c1", "AAAA", trigger={"type": "date", "value": "2026-11-20"})], None, TODAY)
        self.assertEqual(r["advisor_verdict"], "HOLD")
        self.assertEqual((r["unconstrained_verdict"], r["unconstrained_verdict_confidence"]), ("BUY", 0.7))
        c = r["user_constraints"][0]
        self.assertEqual((c["derived"], c["as_of"], c["condition_id"], c["reason"], c["until"]),
                         (True, TODAY, "c1", "sell_condition", "2026-11-20"))
        self.assertEqual(r["advisor_verdict_constraints"], [c["summary"]])
        self.assertEqual(ce.slice_form_errors(r["user_constraints"]), [])

    def test_same_verdict_no_unconstrained(self):
        r = slice_for_key("AAAA", {"verdict": "HOLD", "confidence": 0.7}, [row("c1", "AAAA")], None, TODAY)
        self.assertEqual(r["advisor_verdict"], "HOLD")
        self.assertIsNone(r["unconstrained_verdict"])
        self.assertEqual(len(r["user_constraints"]), 1)

    def test_reason_by_trigger_direction(self):
        rs = slice_for_key("A", {"verdict": "HOLD"}, [row("b", "A", on_trigger="BUY"), row("h", "A", on_trigger="HOLD")],
                           None, TODAY)["user_constraints"]
        self.assertEqual({c["condition_id"]: c["reason"] for c in rs}, {"b": "pending_buy_condition", "h": "condition_hold"})

    def test_conflicting_verdict_now_first_wins_with_diagnostic(self):
        r = slice_for_key("A", {"verdict": "BUY"}, [row("b2", "A", verdict_now="SELL"), row("a1", "A", verdict_now="HOLD")],
                          None, TODAY)
        self.assertEqual(r["advisor_verdict"], "HOLD")
        self.assertEqual(r["diagnostics"], ["conflicting_verdict_now:b2"])

    def test_fired_waits_owner_recorded_verdict_unchanged(self):
        r = slice_for_key("A", {"verdict": "BUY"}, [row("f", "A", status="fired", waits_owner=True)], None, TODAY)
        self.assertEqual(r["advisor_verdict"], "BUY")
        self.assertEqual(r["waits_owner"], ["f"])
        self.assertEqual(r["user_constraints"][0]["status"], "fired")
        self.assertIsNone(r["unconstrained_verdict"])

    def test_inactive_other_key_and_no_verdict_now_skipped(self):
        rows = [row("x", "A", active=False), row("y", "B"), row("z", "A", verdict_now=None),
                row("w", "A", status="fired", waits_owner=False)]
        r = slice_for_key("A", {"verdict": "BUY"}, rows, None, TODAY)
        self.assertEqual((r["user_constraints"], r["advisor_verdict"]), ([], "BUY"))

    def test_plan_blocks_buy_recorded_verdict_unchanged(self):
        self.assertEqual(PLAN_BLOCKS_BUY, {"KEEP", "WAIT", "SELL"})
        r = slice_for_key("A", {"verdict": "ADD"}, [], "WAIT", TODAY)
        c = r["user_constraints"][0]
        self.assertEqual((c["plan_field"], c["plan_value"], c["reason"]), ("user_plan", "WAIT", "user_plan"))
        self.assertNotIn("condition_id", c)
        self.assertEqual(r["advisor_verdict"], "ADD")
        self.assertEqual(slice_for_key("A", {"verdict": "HOLD"}, [], "WAIT", TODAY)["user_constraints"], [])
        self.assertEqual(slice_for_key("A", {"verdict": "BUY"}, [], "BALANCE", TODAY)["user_constraints"], [])

    def test_no_prior_review_input(self):
        # Перенос из прошлого обзора упразднён: вход prior_review игнорируется
        out = build({"analytical_verdicts": {"A": {"verdict": "BUY"}},
                     "prior_review": {"per_stock": {"A": {"user_constraints": [{"type": "no_buy", "active": True}]}}}},
                    [], {}, TODAY)
        self.assertEqual(out["tickers"]["A"]["user_constraints"], [])
        self.assertEqual(out["summary"]["with_slice"], [])


class Cli(unittest.TestCase):
    def run_cli(self, stdin, *args):
        return subprocess.run([sys.executable, SCRIPT, "--today", TODAY, *args], input=stdin,
                              capture_output=True, text=True)

    def test_root_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = os.path.join(tmp, "Portfolio")
            os.makedirs(port)
            cond = {"id": "c1", "version": 1, "key": "AAAA", "kind": "trade",
                    "trigger": {"type": "price_above", "value": 100}, "event_text": None,
                    "while_pending": {"verdict": "HOLD", "text": "ждём"},
                    "on_trigger": {"action": "set_verdict", "verdict": "TRIM", "text": "срезать"},
                    "on_expiry": None, "not_before": None, "valid_until": "2026-12-31", "note": "почему",
                    "context": None, "source": {"kind": "owner", "doc": None},
                    "created_at": "2026-10-01T10:00:00+03:00", "created_by": "owner", "withdrawn": None,
                    "superseded_by": None}
            with open(os.path.join(port, "conditions.yaml"), "w", encoding="utf-8") as f:
                json.dump({"schema_version": "conditions@2", "conditions": [cond]}, f, ensure_ascii=False)
            snap = os.path.join(tmp, "snap.json")
            with open(snap, "w", encoding="utf-8") as f:
                json.dump({"ie_actual": {"per_ticker": {"BBBB": {"user_plan": "KEEP"}}}}, f)
            p = self.run_cli(json.dumps({"analytical_verdicts": {"AAAA": {"verdict": "BUY"}, "BBBB": {"verdict": "BUY"}}}),
                             "--root", tmp, "--snapshot", snap)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)
            self.assertEqual(out["tickers"]["AAAA"]["advisor_verdict"], "HOLD")
            self.assertEqual(out["tickers"]["AAAA"]["user_constraints"][0]["until"], "2026-12-31")
            self.assertEqual(out["tickers"]["BBBB"]["user_constraints"][0]["plan_value"], "KEEP")
            self.assertEqual(out["summary"]["verdict_changed"], ["AAAA"])

    def test_bad_json_no_traceback(self):
        p = self.run_cli("per_stock:\n  A: {}\n")
        self.assertEqual(p.returncode, 2)
        self.assertIn("ERROR", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

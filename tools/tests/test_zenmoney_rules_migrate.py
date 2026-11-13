#!/usr/bin/env python3
"""tools/zenmoney_rules_migrate.py — тройка операции и названия места из rule-ops.json переезжают в
spending-rules.json. Контракты: сухой прогон ничего не пишет; запись делает копию *.before-rules-op-<дата> и
проходит validate_rules; правило без записи в rule-ops ищется по записи месяца (ровно одно совпадение);
ненайденное попадает в сводку; уже заполненное не трогается; повторный запуск ничего не меняет.
Данные синтетические. Запуск: python3 tools/tests/test_zenmoney_rules_migrate.py"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import zenmoney_rules_migrate as M  # noqa: E402

RULES = {"schema": "zenmoney-spending-rules@1", "updated": "2026-11-01", "regular_big": [],
         "one_off": [
             {"id": "a", "month": "2026-07", "note": "из rule-ops", "date": "2026-07-31"},
             {"id": "b", "month": "2026-07", "note": "по записи месяца", "date": "2026-07-31"},
             {"id": "c", "month": "2026-07", "note": "нигде", "date": "2026-07-31"},
             {"id": "d", "month": "2026-07", "note": "уже есть", "date": "2026-07-31",
              "op": {"date": "2026-07-09", "account": "Карта", "amount": 7}}],
         "one_off_merchants": [{"merchant_id": "m1", "note": "место", "date": "2026-07-31"},
                               {"merchant_id": "m2", "note": "место без имени", "date": "2026-07-31"}]}
RULE_OPS = {"ops": {"a": ["2026-07-03", "Карта", 1000]}, "merchants": {"m1": ["Имя А", "Имя Б"]}}
WRITTEN = {"2026-07": {"one_off": [{"name": "Лавка", "rub": 250, "note": "по записи месяца"}]}}
OPS = [{"id": "x1", "date": "2026-07-12", "expense": {"amount": 250.0}, "merchantId": "p:Лавка",
        "_key": ("2026-07-12", "Карта", 250.0)}]


class Migrate(unittest.TestCase):
    def test_migrate_fills_and_reports(self):
        new, st = M.migrate(RULES, RULE_OPS, WRITTEN, OPS)
        by = {x["id"]: x for x in new["one_off"]}
        self.assertEqual(by["a"]["op"], {"date": "2026-07-03", "account": "Карта", "amount": 1000})
        self.assertEqual(by["b"]["op"], {"date": "2026-07-12", "account": "Карта", "amount": 250})
        self.assertNotIn("op", by["c"])
        self.assertEqual(by["d"]["op"]["amount"], 7)
        self.assertEqual(new["one_off_merchants"][0]["names"], ["Имя А", "Имя Б"])
        self.assertEqual((st["filled_op"], st["filled_by_record"], st["filled_names"], st["kept"]), (2, 1, 1, 1))
        self.assertEqual(st["missing"], [("нигде", "2026-07"), ("место без имени", None)])
        self.assertNotIn("op", RULES["one_off"][0])                       # вход не мутируется

    def test_without_csv_only_rule_ops(self):
        _, st = M.migrate(RULES, RULE_OPS)
        self.assertEqual((st["filled_op"], st["filled_by_record"]), (1, 0))
        self.assertEqual(len(st["missing"]), 3)

    def test_cli_dry_run_then_write_with_backup_and_idempotent(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            rp, ro = t / "spending-rules.json", t / "rule-ops.json"
            rp.write_text(json.dumps(RULES, ensure_ascii=False), encoding="utf-8")
            ro.write_text(json.dumps(RULE_OPS, ensure_ascii=False), encoding="utf-8")
            before = rp.read_text(encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(M.main(["--rules", str(rp), "--rule-ops", str(ro)]), 0)
            self.assertEqual(rp.read_text(encoding="utf-8"), before)
            self.assertIn("сухой прогон", out.getvalue())
            self.assertEqual(list(t.glob("*.before-rules-op-*")), [])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(["--rules", str(rp), "--rule-ops", str(ro), "--write"]), 0)
            baks = list(t.glob("spending-rules.json.before-rules-op-*"))
            self.assertEqual(len(baks), 1)
            self.assertEqual(baks[0].read_text(encoding="utf-8"), before)
            written = json.loads(rp.read_text(encoding="utf-8"))
            self.assertEqual(written["one_off"][0]["op"]["account"], "Карта")
            after = rp.read_text(encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                M.main(["--rules", str(rp), "--rule-ops", str(ro), "--write"])
            self.assertEqual(rp.read_text(encoding="utf-8"), after)       # второй запуск ничего не меняет

    def test_missing_rule_ops_file_is_ok(self):
        with tempfile.TemporaryDirectory() as t:
            rp = Path(t) / "r.json"
            rp.write_text(json.dumps(RULES, ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(["--rules", str(rp), "--rule-ops", str(Path(t) / "нет.json")]), 0)


if __name__ == "__main__":
    unittest.main()

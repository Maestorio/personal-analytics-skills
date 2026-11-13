#!/usr/bin/env python3
"""
test_security_attrs.py — писатель справочника бумаг security-attrs@1 (schema.md §4.8) и команда stamp-report
сохранения отчёта (assemble_artifact.py, schema.md §4.3) на временном корне; живой mount не трогается.

Запуск:
    python3 skills/save-to-library/tests/test_security_attrs.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = os.path.join(REPO, "skills", "save-to-library", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(REPO, "_shared-references"))

import ds_schemas as ds  # noqa: E402
import security_attrs as SA  # noqa: E402

NOW = "2026-11-02T10:15:00+03:00"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
DOC0 = {"schema_version": "security-attrs@1", "by_key": {
    "MDMG": {"ticker_class": "ipo", "listed_at": "2024-12-18", "note": "переезд, не IPO?", "updated_at":
             "2026-10-31T12:00:00+03:00", "updated_by": "script"},
    "SBER": {"ticker_class": "bluechip", "listed_at": None, "note": None, "updated_at": "2026-10-31T12:00:00+03:00",
             "updated_by": "script"},
}}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="security-attrs-")
        os.makedirs(os.path.join(self.root, "Portfolio"))
        self.path = os.path.join(self.root, "Portfolio", "security-attrs.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(DOC0, f, ensure_ascii=False, indent=2)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_cmd(self, *argv, now=NOW):
        args = list(argv) + ["--root", self.root] + (["--now", now] if now else [])
        return SA.run(args)

    def doc(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)


class TestSet(Base):
    def test_change_class_keeps_other_fields(self):
        code, out = self.run_cmd("set", "--key", "MDMG", "--class", "mid_cap", "--by", "owner")
        self.assertEqual(code, 0, out)
        rec = self.doc()["by_key"]["MDMG"]
        self.assertEqual((rec["ticker_class"], rec["listed_at"], rec["note"]), ("mid_cap", "2024-12-18", "переезд, не IPO?"))
        self.assertEqual((rec["updated_at"], rec["updated_by"]), (NOW, "owner"))
        self.assertEqual(out["changed"], ["ticker_class"])
        self.assertEqual(out["before"]["ticker_class"], "ipo")
        self.assertEqual(ds.validate_security_attrs(self.doc()), [])
        self.assertEqual(self.doc()["by_key"]["SBER"], DOC0["by_key"]["SBER"])     # чужая запись не тронута

    def test_none_clears_and_new_key_created(self):
        code, out = self.run_cmd("set", "--key", "MDMG", "--note", "none", "--listed-at", "none", "--by", "owner")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.doc()["by_key"]["MDMG"]["note"])
        self.assertIsNone(self.doc()["by_key"]["MDMG"]["listed_at"])
        code, out = self.run_cmd("set", "--key", "X5", "--class", "ipo", "--listed-at", "2025-01-09", "--by", "owner")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["created"])
        self.assertEqual(self.doc()["by_key"]["X5"]["note"], None)
        self.assertEqual(list(self.doc()["by_key"]), ["MDMG", "SBER", "X5"])          # ключи по порядку

    def test_unchanged_does_not_write(self):
        before = _read(self.path)
        code, out = self.run_cmd("set", "--key", "MDMG", "--class", "ipo", "--by", "owner")
        self.assertEqual((code, out.get("unchanged")), (0, True))
        self.assertEqual(_read(self.path), before)

    def test_errors_leave_file(self):
        before = _read(self.path)
        cases = [
            ("set", "--key", "MDMG", "--class", "small_cap", "--by", "owner"),     # нет в кодлисте
            ("set", "--key", "MDMG", "--listed-at", "18.12.2024", "--by", "owner"),
            ("set", "--key", "MDMG", "--class", "ipo"),                             # нет --by
            ("set", "--key", "MDMG", "--class", "ipo", "--by", "model"),            # нет в кодлисте actor
            ("set", "--key", "MDMG", "--by", "owner"),                              # нечего менять
            ("set", "--key", "MDMG", "--note", "x" * 201, "--by", "owner"),         # note ≤ 200
        ]
        for argv in cases:
            code, out = self.run_cmd(*argv)
            self.assertEqual(code, 1, (argv, out))
            self.assertFalse(out["ok"])
        self.assertEqual(_read(self.path), before)
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.path)) if ".tmp-" in f], [])

    def test_missing_file_is_error(self):
        os.remove(self.path)
        code, out = self.run_cmd("set", "--key", "MDMG", "--class", "ipo", "--by", "owner")
        self.assertEqual(code, 1)
        self.assertIn("справочник не заполнен", out["error"])
        self.assertFalse(os.path.exists(self.path))
        self.assertIn("справочник не заполнен", self.run_cmd("get", "--key", "MDMG", now=None)[1]["error"])


class TestAddMissing(Base):
    """add-missing / add_missing: только новые ключи держаний снапшота; существующие записи не трогаются."""
    HOLD = [{"ticker": "SBER", "qty": 10, "listing_date": "2000-01-01"},       # есть в справочнике — не трогать
            {"ticker": "NEWS", "qty": 5, "listing_date": "2025-03-04"},        # акция с датой
            {"ticker": "NEWF", "qty": 1},                                      # без listing_date -> null
            {"ticker": None, "isin": "RU000A0ZZZZ9", "qty": 3},               # ключ — isin
            {"ticker": "SOLD", "qty": 0, "listing_date": "2020-01-01"},        # продана — не ключ
            {"ticker": "BAD", "qty": 2, "listing_date": "не дата"}]

    def test_adds_only_missing_and_keeps_existing(self):
        before = self.doc()
        doc, added = SA.add_missing(self.doc(), self.HOLD, NOW)
        self.assertEqual(added, ["NEWS", "NEWF", "RU000A0ZZZZ9", "BAD"])
        for k in before["by_key"]:
            self.assertEqual(doc["by_key"][k], before["by_key"][k])
        self.assertEqual(doc["by_key"]["NEWS"], {"ticker_class": None, "listed_at": "2025-03-04", "note": None,
                                                 "updated_at": NOW, "updated_by": "script"})
        self.assertIsNone(doc["by_key"]["NEWF"]["listed_at"])
        self.assertIsNone(doc["by_key"]["BAD"]["listed_at"])
        self.assertNotIn("SOLD", doc["by_key"])
        self.assertEqual(ds.validate_security_attrs(doc), [])

    def test_no_new_keys_no_change(self):
        doc, added = SA.add_missing(self.doc(), [{"ticker": "SBER", "qty": 1}], NOW)
        self.assertEqual((added, doc), ([], self.doc()))

    def test_cli_writes_once(self):
        snap = os.path.join(self.root, "snap.json")
        with open(snap, "w", encoding="utf-8") as f:
            json.dump({"holdings": self.HOLD}, f)
        code, out = self.run_cmd("add-missing", "--snapshot", snap)
        self.assertEqual((code, out["added"]), (0, ["NEWS", "NEWF", "RU000A0ZZZZ9", "BAD"]))
        self.assertEqual(self.doc()["by_key"]["MDMG"]["note"], "переезд, не IPO?")
        code, out = self.run_cmd("add-missing", "--snapshot", snap)
        self.assertEqual((code, out["unchanged"]), (0, True))


class TestRead(Base):
    def test_get_and_list(self):
        code, out = self.run_cmd("get", "--key", "MDMG", now=None)
        self.assertEqual((code, out["found"], out["record"]["ticker_class_ru"]), (0, True, "недавнее IPO"))
        self.assertFalse(self.run_cmd("get", "--key", "ZZZZ", now=None)[1]["found"])
        code, out = self.run_cmd("list", "--class", "ipo", now=None)
        self.assertEqual([i["key"] for i in out["items"]], ["MDMG"])
        self.assertEqual(self.run_cmd("list", now=None)[1]["count"], 2)
        self.assertEqual(self.run_cmd("list", "--class", "nope", now=None)[0], 1)

    def test_invalid_file_refuses_edit(self):
        bad = json.loads(json.dumps(DOC0))
        bad["by_key"]["MDMG"]["ticker_class"] = "weird"
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        code, out = self.run_cmd("set", "--key", "SBER", "--note", "x", "--by", "owner")
        self.assertEqual(code, 1)
        self.assertTrue(out["errors"])

    def test_cli_subprocess(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "security_attrs.py"), "get", "--root", self.root,
                            "--key", "SBER"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["record"]["ticker_class"], "bluechip")


REPORT = """---
title: "Разбор AAAA"
date: "2026-11-02"
kind: single_analysis
mode_codes: ["4a"]
tickers: ["AAAA"]
decisions:
  - key: AAAA
    verdict: HOLD
    target_pct: null
    review_by: null
    note: "тезис жив"
---

# Разбор AAAA

Тело.
"""
DOC = "Portfolio/reports/2026-11-02-single-analysis-aaaa.md"


class TestStampReport(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="stamp-report-")
        os.makedirs(os.path.join(self.root, "Portfolio", "reports"))
        self.path = os.path.join(self.root, *DOC.split("/"))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(REPORT)
        import assemble_artifact as AA
        self.AA = AA

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def stamp(self, now=NOW, doc=DOC):
        return self.AA.stamp_report(["--root", self.root, "--doc", doc, "--now", now])

    def test_stamps_once_and_validates(self):
        code, out = self.stamp()
        self.assertEqual((code, out["stamped"], out["recorded_at"]), (0, ["schema_version", "recorded_at"], NOW))
        text = _read(self.path)
        fm = ds.report_frontmatter(text)
        self.assertEqual(ds.validate_report(fm), [])
        self.assertEqual((fm["schema_version"], fm["recorded_at"]), ("report@1", NOW))
        self.assertTrue(text.endswith("# Разбор AAAA\n\nТело.\n"))                   # тело не тронуто
        code, out = self.stamp(now="2026-11-03T09:00:00+03:00")                      # повтор — без изменений
        self.assertEqual((code, out["stamped"], out["recorded_at"]), (0, [], NOW))
        self.assertEqual(_read(self.path), text)

    def test_keeps_existing_recorded_at(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(REPORT.replace('kind: single_analysis', 'kind: single_analysis\nrecorded_at: "2026-11-01T08:00:00+03:00"'))
        code, out = self.stamp()
        self.assertEqual((code, out["stamped"], out["recorded_at"]), (0, ["schema_version"], "2026-11-01T08:00:00+03:00"))

    def test_errors(self):
        self.assertEqual(self.stamp(doc="Portfolio/reports/none.md")[0], 1)
        self.assertEqual(self.stamp(doc="../x.md")[0], 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(REPORT.replace("kind: single_analysis", "kind: single_analysis\nschema_version: report@0"))
        self.assertEqual(self.stamp()[0], 1)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# без шапки\n")
        self.assertEqual(self.stamp()[0], 1)

    def test_cli_subprocess(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "assemble_artifact.py"), "stamp-report",
                            "--root", self.root, "--doc", DOC], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(ds.is_time(out["recorded_at"]))


class TestPriorityContextFromRoot(unittest.TestCase):
    """assemble_artifact --root: контекст verification_priority из последнего решения и действующих условий."""

    def test_context_built(self):
        import assemble_artifact as AA
        root = tempfile.mkdtemp(prefix="prio-ctx-")
        try:
            ddir = os.path.join(root, "Portfolio", "decisions")
            os.makedirs(ddir)
            rec = "2026-10-20T10:00:00+03:00"
            d = {"schema_version": "decision@1", "id": "2026-10-20T1000-AAAA", "key": "AAAA", "verdict": "WATCH",
                 "target_pct": None, "review_by": None, "note": "x", "conditions_created": [],
                 "conditions_resolved": [], "source": {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None},
                 "author": "owner", "recorded_at": rec}
            with open(os.path.join(ddir, "2026-10-20T1000-AAAA.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
            data = {"review_date": "2026-10-26", "per_stock": {"AAAA": {}, "BBBB": {}}}
            AA._priority_context_from_root(data, root)
            self.assertEqual(data["_priority_context"]["AAAA"],
                             {"gate_status": "reviewed_under_review", "active_condition_verdicts": []})
            self.assertIsNone(data["_priority_context"]["BBBB"]["gate_status"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)

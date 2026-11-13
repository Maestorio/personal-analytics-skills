#!/usr/bin/env python3
"""
test_decision_write.py — писатель решений по бумаге decision@1 (schema.md §3.1, шаг 8 цикла машиночитаемости).

Каждая команда — на временном корне Claude-Memory: отчёт-фикстура с шапкой report@1 и блоком `decisions:`,
условия — пара defs+state, которую даёт миграция `migrate_conditions_v2.py` на синтетической фикстуре
`tools/data-structures/tests/fixtures/conditions_v12.yaml` (на 2026-12-31 у AAAA сработали два условия:
`aaaa-below-100` и `aaaa-branches`). Живой mount не трогается.

Запуск:
    python3 skills/save-to-library/tests/test_decision_write.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SCRIPT = os.path.join(REPO, "skills", "save-to-library", "scripts", "decision_write.py")
FIXTURE = os.path.join(REPO, "tools", "data-structures", "tests", "fixtures", "conditions_v12.yaml")
sys.path.insert(0, os.path.dirname(SCRIPT))
sys.path.insert(0, os.path.join(REPO, "_shared-references"))
sys.path.insert(0, os.path.join(REPO, "tools", "data-structures", "migrations"))

import decision_write as DW  # noqa: E402
import ds_schemas as ds  # noqa: E402
import migrate_conditions_v2 as mg  # noqa: E402

NOW = "2026-12-31T17:40:00+03:00"
TODAY = "2026-12-31"
DOC = "Portfolio/reports/2026-12-31-single-analysis-aaaa.md"

HEADER = """---
title: "Разбор AAAA и BBBB"
date: "2026-12-31"
created_at: "2026-12-31T17:30"
author: "ru-portfolio-advisor"
kind: "single_analysis"
summary: "Держать AAAA, BBBB — наблюдать."
mode: "4 (single)"
tickers: ["AAAA", "BBBB"]
mode_codes: ["4a", "3"]
schema_version: report@1
recorded_at: "2026-12-31T17:35:00+03:00"
decisions:
{decisions}
---

# Разбор AAAA и BBBB

Тело отчёта.
"""

BLOCK_TWO = """  - key: AAAA
    verdict: HOLD
    target_pct: 4.5
    review_by: "2027-02-15"
    note: "отчёт вышел, тезис жив"
    confidence: 0.7
  - key: BBBB
    verdict: WATCH
    target_pct: null
    review_by: null
    note: "ждём дивидендную политику\""""


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="decision-write-")
        port = os.path.join(self.root, "Portfolio")
        os.makedirs(os.path.join(port, "reports"))
        defs, state, _, _ = mg.migrate(ds.load_yaml(FIXTURE))
        with open(os.path.join(port, "conditions.yaml"), "w", encoding="utf-8") as f:
            f.write(mg._dump_yaml(defs))
        with open(os.path.join(port, "conditions-state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        self.ddir = os.path.join(port, "decisions")
        self.report(BLOCK_TWO)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def report(self, block, doc=DOC, header=HEADER):
        with open(os.path.join(self.root, *doc.split("/")), "w", encoding="utf-8") as f:
            f.write(header.replace("{decisions}", block))

    def run_cmd(self, *argv, now=NOW):
        args = list(argv) + ["--root", self.root]
        if now:
            args += ["--now", now]
        return DW.run(args)

    def files(self):
        return sorted(os.listdir(self.ddir)) if os.path.isdir(self.ddir) else []


class TestFromReport(Base):
    def test_two_papers_two_files_same_minute(self):
        code, out = self.run_cmd("from-report", "--doc", DOC, "--stress", "stress-2026-12-01-x")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.files(), ["2026-12-31T1740-AAAA.json", "2026-12-31T1740-BBBB.json"])
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(ds.validate_decision(a), [])
        self.assertEqual(list(a), ["schema_version", "id", "key", "verdict", "target_pct", "review_by", "note",
                                   "confidence", "conditions_created", "conditions_resolved", "source", "author",
                                   "recorded_at"])
        self.assertEqual(a["id"], "2026-12-31T1740-AAAA")
        self.assertEqual(a["recorded_at"], NOW)
        self.assertEqual(a["source"], {"kind": "report", "doc": DOC, "mode_codes": ["4a", "3"],
                                       "stress_id": "stress-2026-12-01-x"})
        self.assertEqual(a["author"], "model")
        self.assertEqual((a["verdict"], a["target_pct"], a["review_by"], a["confidence"]), ("HOLD", 4.5, "2027-02-15", 0.7))
        b = _read_json(os.path.join(self.ddir, "2026-12-31T1740-BBBB.json"))
        self.assertNotIn("confidence", b)                      # не дано моделью — поля нет
        self.assertIsNone(b["review_by"])
        self.assertEqual(out["written"], ["Portfolio/decisions/2026-12-31T1740-AAAA.json",
                                          "Portfolio/decisions/2026-12-31T1740-BBBB.json"])

    def test_conditions_resolved_is_fired_of_key(self):
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 0, out)
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(sorted(a["conditions_resolved"]), ["aaaa-below-100", "aaaa-branches"])
        b = _read_json(os.path.join(self.ddir, "2026-12-31T1740-BBBB.json"))
        self.assertEqual(b["conditions_resolved"], ["bbbb-trade-review-status"])  # bbbb-fired уже done
        self.assertIsNone(a["source"]["stress_id"])

    def test_today_changes_what_fired(self):
        code, out = self.run_cmd("from-report", "--doc", DOC, "--today", "2026-10-31")
        self.assertEqual(code, 0, out)
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(a["conditions_resolved"], ["aaaa-below-100"])   # окно отчёта ещё не вышло
        b = _read_json(os.path.join(self.ddir, "2026-12-31T1740-BBBB.json"))
        self.assertEqual(b["conditions_resolved"], [])

    def test_keep_open_excludes(self):
        self.report(BLOCK_TWO.replace('    confidence: 0.7', '    confidence: 0.7\n    keep_open: [aaaa-branches]'))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 0, out)
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(a["conditions_resolved"], ["aaaa-below-100"])

    def test_keep_open_not_fired_is_error(self):
        self.report(BLOCK_TWO.replace('    confidence: 0.7', '    confidence: 0.7\n    keep_open: [ffff-trade-notify]'))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("keep_open", out["error"])
        self.assertEqual(self.files(), [])

    def _defer_aaaa_below_100(self):
        sp = os.path.join(self.root, "Portfolio", "conditions-state.json")
        st = _read_json(sp)
        st["events"].append({"condition_id": "aaaa-below-100", "version": 1, "event": "owner_mark",
                             "at": "2026-12-30T10:00:00+03:00", "by": "owner",
                             "data": {"mark": "deferred", "until": "2027-01-15"}})
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

    def test_deferred_by_owner_not_resolved(self):
        self._defer_aaaa_below_100()
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 0, out)
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(a["conditions_resolved"], ["aaaa-branches"])   # отложенное владельцем решение не закрывает

    def test_keep_open_deferred_is_error(self):
        self._defer_aaaa_below_100()
        self.report(BLOCK_TWO.replace('    confidence: 0.7', '    confidence: 0.7\n    keep_open: [aaaa-below-100]'))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("keep_open", out["error"])
        self.assertEqual(self.files(), [])

    def test_created_ids(self):
        code, out = self.run_cmd("from-report", "--doc", DOC, "--created", "ffff-trade-notify")
        self.assertEqual(code, 0, out)
        a = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(a["conditions_created"], ["ffff-trade-notify"])
        shutil.rmtree(self.ddir)
        code, out = self.run_cmd("from-report", "--doc", DOC, "--created", "no-such-id")
        self.assertEqual(code, 1)
        self.assertIn("no-such-id", out["error"])

    def test_repeat_write_is_error_not_overwrite(self):
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 0)
        path = os.path.join(self.ddir, "2026-12-31T1740-AAAA.json")
        before = _text(path)
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("уже есть", out["error"])
        self.assertEqual(_text(path), before)
        # через минуту — новые файлы, старые не тронуты
        code, out = self.run_cmd("from-report", "--doc", DOC, now="2026-12-31T17:41:00+03:00")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.files()), 4)

    def test_review_by_out_of_window_is_validator_error(self):
        self.report(BLOCK_TWO.replace('review_by: "2027-02-15"', 'review_by: "2027-01-02"'))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("AAAA", out["errors"])
        self.assertTrue(any("review_by" in e for e in out["errors"]["AAAA"]))
        self.assertEqual(self.files(), [])                      # ни одного файла: BBBB тоже не записан
        self.report(BLOCK_TWO.replace('review_by: "2027-02-15"', 'review_by: "2027-07-15"'))
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 1)   # > 180 дней

    def test_legacy_verdict_is_error(self):
        self.report(BLOCK_TWO.replace("verdict: WATCH", "verdict: RED_FLAG"))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("validate-report", out["error"])
        self.assertTrue(any("verdict" in e for e in out["errors"]))
        self.assertEqual(self.files(), [])

    def test_header_errors_block(self):
        self.report(BLOCK_TWO.replace("key: BBBB", "key: CCCC"))         # ключа нет в tickers[]
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertTrue(any("tickers" in e for e in out["errors"]))
        self.report(BLOCK_TWO.replace("    target_pct: 4.5\n", ""))       # поле модели пропущено
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 1)
        self.report(BLOCK_TWO.replace("    confidence: 0.7", "    gate: reviewed_keep"))  # поле не из блока
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 1)
        self.assertEqual(self.files(), [])

    def test_no_block_is_error(self):
        self.report("", header=HEADER.replace("decisions:\n{decisions}\n", ""))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("decisions", out["error"])

    def test_bad_doc_paths(self):
        for doc in ("Portfolio/weekly-reviews/x.yaml", "Portfolio/reports/../x.md", "/abs/x.md",
                    "Portfolio/reports/missing.md"):
            code, out = self.run_cmd("from-report", "--doc", doc)
            self.assertEqual(code, 1, doc)
        self.assertEqual(self.run_cmd("from-report")[0], 1)              # без --doc

    def test_by_owner_and_bad_by(self):
        code, out = self.run_cmd("from-report", "--doc", DOC, "--by", "owner")
        self.assertEqual(code, 0, out)
        self.assertEqual(_read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))["author"], "owner")
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC, "--by", "mode_4")[0], 1)

    def test_old_conditions_format_rejected(self):
        shutil.copy(FIXTURE, os.path.join(self.root, "Portfolio", "conditions.yaml"))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 1)
        self.assertIn("conditions@2", out["error"])

    def test_without_conditions_file(self):
        os.remove(os.path.join(self.root, "Portfolio", "conditions.yaml"))
        os.remove(os.path.join(self.root, "Portfolio", "conditions-state.json"))
        code, out = self.run_cmd("from-report", "--doc", DOC)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["conditions_missing"])
        self.assertEqual(out["decisions"][0]["conditions_resolved"], [])

    def test_root_checked_and_no_temp_left(self):
        code, out = DW.run(["from-report", "--doc", DOC, "--root", os.path.join(self.root, "nope"), "--now", NOW])
        self.assertEqual(code, 1)
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 0)
        self.assertFalse([f for f in self.files() if ".tmp-" in f])

    def test_bad_now_and_today(self):
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC, now="2026-12-31T17:40:00Z")[0], 1)
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC, "--today", "31.12.2026")[0], 1)


class TestOwner(Base):
    def test_owner_decision(self):
        code, out = self.run_cmd("owner", "--key", "AAAA", "--verdict", "BUY", "--target-pct", "5",
                                 "--review-by", "2027-03-01", "--note", "владелец решил докупить",
                                 "--keep-open", "aaaa-branches")
        self.assertEqual(code, 0, out)
        d = _read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json"))
        self.assertEqual(ds.validate_decision(d), [])
        self.assertEqual(d["source"], {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None})
        self.assertEqual(d["author"], "owner")
        self.assertEqual(d["conditions_resolved"], ["aaaa-below-100"])
        self.assertNotIn("confidence", d)

    def test_owner_errors(self):
        self.assertEqual(self.run_cmd("owner", "--key", "AAAA", "--verdict", "BUY")[0], 1)          # без --note
        self.assertEqual(self.run_cmd("owner", "--key", "AAAA", "--verdict", "HOLD_ADD", "--note", "x")[0], 1)
        self.assertEqual(self.run_cmd("owner", "--key", "AA/AA", "--verdict", "BUY", "--note", "x")[0], 1)
        self.assertEqual(self.run_cmd("owner", "--key", "AAAA", "--verdict", "BUY", "--note", "x",
                                      "--confidence", "1.5")[0], 1)
        self.assertEqual(self.run_cmd("owner", "--key", "AAAA", "--verdict", "BUY", "--note", "x",
                                      "--review-by", "2027-12-31")[0], 1)                       # > 180 дней
        self.assertEqual(self.files(), [])


class TestBuildOwner(Base):
    """Общая сборка решения владельца (CLI `owner` и сайт, hub-notify decision_job): чистая функция, файлов не пишет."""

    ENTRY = {"key": "AAAA", "verdict": "BUY", "target_pct": 5.0, "review_by": "2027-03-01",
             "note": "владелец решил докупить", "confidence": None}

    def test_pure_and_equal_to_cli_file(self):
        d, missing = DW.build_owner(self.root, dict(self.ENTRY, keep_open=["aaaa-branches"]), NOW)
        self.assertFalse(missing)
        self.assertEqual(self.files(), [])                                    # сборка ничего не пишет
        code, out = self.run_cmd("owner", "--key", "AAAA", "--verdict", "BUY", "--target-pct", "5",
                                 "--review-by", "2027-03-01", "--note", "владелец решил докупить",
                                 "--keep-open", "aaaa-branches")
        self.assertEqual(code, 0, out)
        self.assertEqual(_read_json(os.path.join(self.ddir, "2026-12-31T1740-AAAA.json")), d)   # CLI = та же запись
        self.assertEqual(d["author"], "owner")
        self.assertEqual(d["source"], {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None})
        self.assertEqual(d["id"], "2026-12-31T1740-AAAA")
        self.assertEqual(d["recorded_at"], NOW)

    def test_resolved_only_waits_owner(self):
        d, _ = DW.build_owner(self.root, dict(self.ENTRY), NOW)
        rows, _, _ = DW._conditions(self.root, TODAY)
        waits = [r["id"] for r in DW.cm.select(rows, keys=["AAAA"]) if r["waits_owner"]]
        self.assertEqual(d["conditions_resolved"], waits)                     # ровно ждущие владельца, ничего лишнего
        self.assertTrue(set(d["conditions_resolved"]).issubset({r["id"] for r in rows}))

    def test_errors_raise_cmderror(self):
        for bad in (dict(self.ENTRY, verdict="HOLD_ADD"), dict(self.ENTRY, key="AA/AA"),
                    dict(self.ENTRY, confidence=1.5), dict(self.ENTRY, review_by="2027-12-31"),
                    dict(self.ENTRY, keep_open=["нет-такого"])):
            with self.assertRaises(DW.CmdError, msg=str(bad)):
                DW.build_owner(self.root, bad, NOW)
        self.assertEqual(self.files(), [])


class TestDigest(Base):
    def test_digest_newest_first_and_limit(self):
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 0)
        self.assertEqual(self.run_cmd("owner", "--key", "AAAA", "--verdict", "TRIM", "--note", "перевес",
                                      "--today", "2027-01-10", now="2027-01-10T09:05:00+03:00")[0], 0)
        code, out = self.run_cmd("digest", "--key", "AAAA", now=None)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["count"], 2)
        self.assertEqual([i["id"] for i in out["items"]], ["2027-01-10T0905-AAAA", "2026-12-31T1740-AAAA"])
        self.assertEqual(out["items"][0]["verdict_ru"], "Сократить")
        self.assertEqual(out["items"][1]["doc"], DOC)
        code, out = self.run_cmd("digest", "--key", "AAAA", "--limit", "1", now=None)
        self.assertEqual((out["count"], out["shown"], len(out["items"])), (2, 1, 1))
        code, out = self.run_cmd("digest", "--key", "ZZZZ", now=None)
        self.assertEqual((code, out["count"]), (0, 0))

    def test_digest_latest_gate_and_condition_statuses(self):
        """latest: последнее решение, гейт по нему (только акции) и статусы его условий по модулю (а)."""
        with open(os.path.join(self.root, "Portfolio", "security-types.json"), "w", encoding="utf-8") as f:
            json.dump({"schema_version": "security-types@1.0",
                       "by_ticker": {"AAAA": {"type": "stock"}, "BBBB": {"type": "fund"}}}, f)
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 0)
        code, out = self.run_cmd("digest", "--key", "AAAA", "--today", TODAY, now=None)
        self.assertEqual(code, 0, out)
        lt = out["latest"]
        self.assertEqual((lt["id"], lt["verdict"], lt["key_type"]), ("2026-12-31T1740-AAAA", "HOLD", "stock"))
        self.assertEqual(lt["gate"]["status"], "reviewed_keep")
        self.assertEqual((lt["gate"]["expires_on"], lt["gate"]["expired"]), ("2027-02-15", False))
        self.assertEqual({c["id"]: c["status"] for c in lt["conditions_resolved"]},
                         {"aaaa-below-100": "fired", "aaaa-branches": "fired"})
        code, out = self.run_cmd("digest", "--key", "AAAA", "--today", "2027-03-01", now=None)
        self.assertEqual(out["latest"]["gate"]["status"], "review_aging")     # срок review_by прошёл
        code, out = self.run_cmd("digest", "--key", "BBBB", "--today", TODAY, now=None)
        self.assertIsNone(out["latest"]["gate"])                              # фонд — без гейта
        code, out = self.run_cmd("digest", "--key", "ZZZZ", now=None)
        self.assertIsNone(out["latest"])

    def test_digest_reports_invalid_files(self):
        os.makedirs(self.ddir)
        with open(os.path.join(self.ddir, "2026-12-30T1000-AAAA.json"), "w", encoding="utf-8") as f:
            json.dump({"key": "AAAA"}, f)
        code, out = self.run_cmd("digest", "--key", "AAAA", now=None)
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["invalid_files"][0]["file"], "2026-12-30T1000-AAAA.json")

    def test_digest_does_not_write(self):
        self.assertEqual(self.run_cmd("from-report", "--doc", DOC)[0], 0)
        before = {f: _text(os.path.join(self.ddir, f)) for f in self.files()}
        self.run_cmd("digest", "--key", "AAAA", now=None)
        self.assertEqual({f: _text(os.path.join(self.ddir, f)) for f in self.files()}, before)


class TestCli(Base):
    def test_subprocess_json_and_exit_codes(self):
        py = sys.executable
        r = subprocess.run([py, SCRIPT, "from-report", "--root", self.root, "--doc", DOC, "--now", NOW],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])
        r = subprocess.run([py, SCRIPT, "apply", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])


class TestGuards(unittest.TestCase):
    """Сторожа по исходнику: одна точка записи, удалений нет; блок `decisions:` шапки читают только эта команда
    и валидатор шапки (срез, правило 2 схемы)."""

    @classmethod
    def setUpClass(cls):
        with open(SCRIPT, encoding="utf-8") as f:
            cls.src = f.read()

    def test_single_write_point_no_deletions(self):
        writes = re.findall(r"open\(([^,)]+),\s*[\"'](?:w|a|x|r\+|wb|ab)[\"']", self.src)
        self.assertEqual(writes, ["tmp"], writes)
        self.assertEqual(re.findall(r"os\.replace\(([^)]*)\)", self.src), ["tmp, path"])
        self.assertNotRegex(self.src, r"os\.(remove|unlink|rmdir|removedirs)\(|shutil\.|\.unlink\(")

    def test_shared_imports(self):
        for mod in ("codelists", "conditions_merge", "ds_schemas", "time_msk"):
            self.assertRegex(self.src, rf"(?m)^import {mod}\b")

    def test_commands(self):
        self.assertEqual(set(DW.COMMANDS), {"from-report", "owner", "digest"})

    def test_decisions_block_read_only_by_writer_and_validator(self):
        """Обращение к ключу `decisions` в коде — только у писателя (from-report) и валидатора шапки; прочие
        вхождения — не шапка отчёта (сводка сборки снапшота и её показ во вьюере) и перечислены поимённо."""
        rx = re.compile(r"""\[\s*["']decisions["']\s*\]|\.get\(\s*["']decisions["']|\.decisions\b""")
        allowed = {
            "skills/save-to-library/scripts/decision_write.py": ['.get("decisions"'],
            "_shared-references/ds_schemas.py": ['["decisions"]'],
            # не шапка отчёта: decisions сборки снапшота (build-summary) и манифеста
            "skills/portfolio-data-loader/scripts/build_snapshot.py": ['.get("decisions"', '["decisions"]'],
            "tools/hosting/notify/pf_build.py": ['.get("decisions"'],
            "skills/portfolio-data-loader/scripts/checks.py": [".decisions"],   # докстринг: build-summary.decisions
            "tools/assets/viewer.js": [".decisions"],
            # не шапка отчёта: контекст модуля (б) — список файлов решений decision@1
            "_shared-references/last_word.py": ['.get("decisions"'],
            # не шапка отчёта: входы движка «Сейчас» (решения для модуля (б)) и аргумент CLI --decisions
            "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py": [".decisions", '.get("decisions"'],
            "tools/assets/rebalance-engine.js": [".decisions"],
            # не шапка отчёта: журнал решений (шаг 13) — контекст файлов решений decision@1 и сводка journal.json
            "skills/portfolio-data-loader/scripts/decision_journal.py": ['.get("decisions"', '["decisions"]'],
            "skills/portfolio-data-loader/scripts/decision_journal_update.py": ['.get("decisions"'],
            # не шапка отчёта: payload ревизии библиотеки — распарсенные файлы decisions/*.json (слой portfolio_carriers)
            "skills/revise-memory-remote/scripts/validate_library.py": ['.get("decisions"'],
        }
        found = {}
        for top in ("skills", "tools", "_shared-references"):
            for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, top)):
                dirnames[:] = [d for d in dirnames if d not in ("tests", "node_modules", "__pycache__", "fixtures")]
                for fn in filenames:
                    if not fn.endswith((".py", ".js", ".html")):
                        continue
                    path = os.path.join(dirpath, fn)
                    with open(path, encoding="utf-8", errors="replace") as f:
                        hits = rx.findall(f.read())
                    if hits:
                        found[os.path.relpath(path, REPO).replace(os.sep, "/")] = sorted(
                            {re.sub(r"\s+", "", h).replace("'", '"') for h in hits})
        self.assertEqual(set(found), set(allowed), found)
        for f, hits in found.items():
            self.assertEqual(hits, sorted(set(allowed[f])), f)
        # в viewer.js `.decisions` — сводка сборки (b.decisions) и, с шага 12 (счётчик cn./cnt.decisions снят пачкой 3 читаемости, 4.2.0),
        # файлы решений decision@1 из sync (state.data.decisions: data./d.; контекст модуля (б): c.decisions) — не шапка отчёта
        with open(os.path.join(REPO, "tools", "assets", "viewer.js"), encoding="utf-8") as f:
            vjs = f.read()
        self.assertEqual(sorted(set(re.findall(r"(\w+)\.decisions\b", vjs))), ["b", "c", "d", "data"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

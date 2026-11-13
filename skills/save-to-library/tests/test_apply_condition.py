#!/usr/bin/env python3
"""
test_apply_condition.py — писатель определений условий conditions@2 (schema.md §3.2, шаг 6 цикла машиночитаемости).

Каждая команда — на временном корне Claude-Memory с парой defs+state, которую даёт миграция
`migrate_conditions_v2.py` на синтетической фикстуре `tools/data-structures/tests/fixtures/conditions_v12.yaml`.
Живой mount не трогается.

Запуск:
    python3 skills/save-to-library/tests/test_apply_condition.py
"""
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SCRIPT = os.path.join(REPO, "skills", "save-to-library", "scripts", "apply_condition.py")
FIXTURE = os.path.join(REPO, "tools", "data-structures", "tests", "fixtures", "conditions_v12.yaml")
sys.path.insert(0, os.path.dirname(SCRIPT))
sys.path.insert(0, os.path.join(REPO, "_shared-references"))
sys.path.insert(0, os.path.join(REPO, "tools", "data-structures", "migrations"))

import apply_condition as AC  # noqa: E402
import conditions_merge as cm  # noqa: E402
import ds_schemas as ds  # noqa: E402
import migrate_conditions_v2 as mg  # noqa: E402

TODAY = "2026-10-31"
NOW = "2026-10-31T12:00:00+03:00"   # --now: подмена time_msk.now_iso() (created_at, withdrawn.at, дата в id)

REPORT_ADD = {
    "key": "GGGG", "kind": "review",
    "trigger": {"type": "report_published", "value": "МСФО 9М GGGG"},
    "expected": "2026-11-20", "valid_until": "2026-11-21",
    "event_text": "МСФО 9М GGGG",
    "while_pending": {"verdict": "HOLD", "text": "ждём отчёт"},
    "on_trigger": {"action": "run_analysis", "text": "разобрать отчёт"},
    "source": {"kind": "report", "doc": "Portfolio/reports/r.md"},
}
PRICE_ADD = {
    "key": "GGGG", "kind": "trade",
    "trigger": {"type": "price_below", "value": 100},
    "while_pending": {"verdict": "HOLD"},
    "on_trigger": {"action": "set_target_pct", "verdict": "BUY", "target_pct": 4, "text": "докупить до плана"},
    "source": {"kind": "report", "doc": "Portfolio/reports/r.md", "decision_id": "2026-10-31T1200-GGGG"},
}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="apply-cond-")
        port = os.path.join(self.root, "Portfolio")
        os.makedirs(port)
        defs, state, _, _ = mg.migrate(ds.load_yaml(FIXTURE))
        with open(os.path.join(port, "conditions.yaml"), "w", encoding="utf-8") as f:
            f.write(mg._dump_yaml(defs))
        with open(os.path.join(port, "conditions-state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        self.defs = os.path.join(port, "conditions.yaml")
        self.state = os.path.join(port, "conditions-state.json")
        self.state_sha = _sha(self.state)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_cmd(self, command, payload=None, *extra, by="mode_1", today=TODAY, now=NOW):
        argv = ([command, "--root", self.root, "--today", today] + (["--by", by] if by else [])
                + (["--now", now] if now else []) + list(extra))
        return AC.run(argv, "" if payload is None else json.dumps(payload, ensure_ascii=False))

    def ok(self, command, payload=None, *extra, **kw):
        code, out = self.run_cmd(command, payload, *extra, **kw)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        return out

    def fail(self, command, payload=None, *extra, **kw):
        code, out = self.run_cmd(command, payload, *extra, **kw)
        self.assertEqual(code, 1, out)
        self.assertFalse(out["ok"])
        self.assertIn("error", out)
        return out

    def doc(self):
        return ds.load_yaml(self.defs)

    def versions(self, cid):
        return sorted((c for c in self.doc()["conditions"] if c["id"] == cid), key=lambda c: c["version"])

    def assert_state_untouched(self):
        self.assertEqual(_sha(self.state), self.state_sha, "conditions-state.json изменён")


class TestAdd(Base):
    def test_report_published_window_and_valid_until_raised(self):
        out = self.ok("add", REPORT_ADD)
        c = out["condition"]
        self.assertEqual(c["trigger"]["window_end"], "2026-11-23")          # 20.11 + 3 дня
        self.assertEqual(out["window_end_computed"]["days"], ds.DEFAULTS["report_window_days"])
        self.assertEqual(c["valid_until"], "2026-11-23")
        self.assertEqual(out["valid_until_raised"], {"from": "2026-11-21", "to": "2026-11-23"})
        self.assertNotIn("expected", c)
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])
        self.assert_state_untouched()

    def test_script_fields(self):
        out = self.ok("add", PRICE_ADD, "--plan", "4.5", "--snapshot", "portfolio-2026-10-31.json", by="mode_4")
        c = out["condition"]
        self.assertEqual(c["id"], "c-2026-10-31-gggg-1")
        self.assertEqual(c["version"], 1)
        self.assertEqual(c["created_by"], "mode_4")
        self.assertEqual(c["created_at"], NOW)
        self.assertEqual(c["context"], {"plan_pct": 4.5, "snapshot_id": "portfolio-2026-10-31.json",
                                        "as_of": c["created_at"]})
        self.assertNotIn("context_missing", out)
        self.assertEqual(c["source"]["decision_id"], "2026-10-31T1200-GGGG")
        self.assertIsNone(c["withdrawn"])
        self.assertIsNone(c["superseded_by"])
        self.assertEqual(list(c), [k for k in ds.COND_FIELDS if k in c])  # порядок полей — как в схеме

    def test_id_date_and_created_at_from_one_moment(self):
        # дата в id — из created_at, а не из --today; --today влияет только на оценку модуля (а)
        out = self.ok("add", PRICE_ADD, today="2026-10-31", now="2026-11-02T00:30:00+03:00")
        self.assertEqual(out["id"], "c-2026-11-02-gggg-1")
        self.assertEqual(out["condition"]["created_at"], "2026-11-02T00:30:00+03:00")
        self.assertEqual(out["condition"]["created_at"][:10], out["id"][2:12])
        # без --now — реальные часы: дата в id = дата created_at
        out = self.ok("add", PRICE_ADD, now=None)
        self.assertTrue(ds.is_time(out["condition"]["created_at"]))
        self.assertEqual(out["id"][2:12], out["condition"]["created_at"][:10])
        self.assertIn("--now", self.fail("add", PRICE_ADD, now="2026-11-02")["error"])

    def test_note(self):
        out = self.ok("add", dict(PRICE_ADD, note="докупка до плана после разбора"))
        self.assertEqual(out["condition"]["note"], "докупка до плана после разбора")
        self.assertEqual(self.ok("digest", None, "--key", "GGGG")["items"][0]["note"], "докупка до плана после разбора")
        out = self.fail("add", dict(PRICE_ADD, note="x" * 201))
        self.assertTrue(any("note" in e for e in out["errors"]))

    def test_context_missing(self):
        out = self.ok("add", PRICE_ADD)
        self.assertIsNone(out["condition"]["context"])
        self.assertTrue(out["context_missing"])

    def test_id_unique_two_adds_same_day(self):
        a = self.ok("add", PRICE_ADD)["id"]
        b = self.ok("add", PRICE_ADD)["id"]
        self.assertEqual((a, b), ("c-2026-10-31-gggg-1", "c-2026-10-31-gggg-2"))
        isin = dict(PRICE_ADD, key="RU000A000AA0")
        self.assertEqual(self.ok("add", isin)["id"], "c-2026-10-31-ru000a000aa0-1")
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])

    def test_explicit_window_end_kept(self):
        p = copy.deepcopy(REPORT_ADD)
        p.pop("expected")
        p["trigger"]["window_end"] = "2026-11-10"
        out = self.ok("add", p)
        self.assertEqual(out["condition"]["trigger"]["window_end"], "2026-11-10")
        self.assertNotIn("valid_until_raised", out)

    def test_report_without_window_or_expected(self):
        p = dict(REPORT_ADD)
        p.pop("expected")
        self.assertIn("expected", self.fail("add", p)["error"])

    def test_bad_inputs(self):
        self.assertIn("ставит скрипт", self.fail("add", dict(PRICE_ADD, id="x"))["error"])
        self.assertIn("неизвестные", self.fail("add", dict(PRICE_ADD, ticker="GGGG"))["error"])
        p = dict(PRICE_ADD)
        p.pop("source")
        self.assertIn("source", self.fail("add", p)["error"])
        self.assertIn("--by", self.fail("add", PRICE_ADD, by=None)["error"])
        self.assertIn("actor", self.fail("add", PRICE_ADD, by="user")["error"])
        self.assertIn("expected", self.fail("add", dict(PRICE_ADD, expected="2026-11-01"))["error"])

    def test_root_required_and_checked(self):
        code, out = AC.run(["digest"], "")
        self.assertEqual(code, 1)
        self.assertIn("--root", out["error"])
        code, out = AC.run(["digest", "--root", os.path.join(self.root, "nope")], "")
        self.assertEqual(code, 1)
        self.assertIn("Portfolio", out["error"])

    def test_old_format_rejected(self):
        shutil.copy(FIXTURE, self.defs)
        before = _sha(self.defs)
        self.assertIn("conditions@1.2", self.fail("add", PRICE_ADD)["error"])
        self.assertIn("conditions@1.2", self.fail("digest", None)["error"])
        self.assertEqual(_sha(self.defs), before)


class TestAtomic(Base):
    def test_validation_failure_leaves_file_byte_identical(self):
        before = _sha(self.defs)
        bad = dict(PRICE_ADD, kind="bogus")
        out = self.fail("add", bad)
        self.assertIn("валидация", out["error"])
        self.assertTrue(any("kind" in e for e in out["errors"]))
        self.assertEqual(_sha(self.defs), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.defs))), ["conditions-state.json", "conditions.yaml"])
        # правка с невалидным полем — тоже без следа
        out = self.fail("edit", {"id": "ffff-trade-notify", "while_pending": {"verdict": "NOPE"}})
        self.assertEqual(_sha(self.defs), before)
        self.assertEqual(len(os.listdir(os.path.dirname(self.defs))), 2)

    def test_success_leaves_no_temp(self):
        self.ok("add", PRICE_ADD)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.defs))), ["conditions-state.json", "conditions.yaml"])

    def test_concurrent_change_detected(self):
        doc, digest = AC._read_defs(self.defs)
        with open(self.defs, "a", encoding="utf-8") as f:
            f.write("# чужая правка\n")
        after = _sha(self.defs)
        with self.assertRaises(AC.CmdError):
            AC._write_defs(self.defs, doc, digest)
        self.assertEqual(_sha(self.defs), after)

    def test_never_deletes_records(self):
        n0 = len(self.doc()["conditions"])
        cid = self.ok("add", PRICE_ADD)["id"]
        self.ok("edit", {"id": cid, "on_trigger": dict(PRICE_ADD["on_trigger"], target_pct=5)})
        self.ok("withdraw", {"id": cid, "reason": "не актуально"})
        self.assertEqual(len(self.doc()["conditions"]), n0 + 2)


class TestEdit(Base):
    def test_new_version_and_superseded_by(self):
        old = copy.deepcopy(self.versions("ffff-trade-notify")[0])
        out = self.ok("edit", {"id": "ffff-trade-notify", "trigger": {"type": "price_above", "value": 13}},
                      by="mode_9")
        self.assertEqual(out["version"], 2)
        self.assertEqual(out["changed"], ["trigger"])
        v1, v2 = self.versions("ffff-trade-notify")
        self.assertEqual(v1["superseded_by"], "ffff-trade-notify@2")
        old["superseded_by"] = "ffff-trade-notify@2"
        self.assertEqual(v1, old)                                 # прежняя запись — только superseded_by
        self.assertEqual(v2["trigger"]["value"], 13)
        self.assertEqual(v2["created_by"], "mode_9")
        self.assertNotEqual(v2["created_at"], v1["created_at"])
        self.assertNotIn("time_estimated", v2)
        self.assertEqual(v2.get("context"), v1.get("context"))  # без --plan/--snapshot — прежний
        self.assertIsNone(v2["superseded_by"])
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])
        self.assert_state_untouched()

    def test_second_edit_from_last_version(self):
        self.ok("edit", {"id": "ffff-trade-notify", "trigger": {"type": "price_above", "value": 13}})
        out = self.ok("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"})
        self.assertEqual(out["version"], 3)
        v1, v2, v3 = self.versions("ffff-trade-notify")
        self.assertEqual(v1["superseded_by"], "ffff-trade-notify@2")
        self.assertEqual(v2["superseded_by"], "ffff-trade-notify@3")
        self.assertEqual(v3["trigger"]["value"], 13)               # правка первой версии сохранилась
        self.assertEqual(v3["valid_until"], "2026-12-31")
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])

    def test_merge_sees_last_version(self):
        self.ok("edit", {"id": "ffff-trade-notify", "trigger": {"type": "price_above", "value": 13}})
        rows = self.ok("digest", None, "--key", "FFFF", "--all")["items"]
        self.assertEqual([(r["version"], r["trigger"]["value"]) for r in rows], [(2, 13)])

    def test_edit_context_refresh(self):
        out = self.ok("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"}, "--plan", "3")
        self.assertIn("context", out["changed"])
        self.assertEqual(out["condition"]["context"]["plan_pct"], 3)

    def test_edit_report_window_rules(self):
        # перевод в report_published по ожидаемой дате: окно +3 дня, valid_until поднимается
        out = self.ok("edit", {"id": "ffff-trade-notify", "kind": "review", "valid_until": "2026-11-01",
                               "trigger": {"type": "report_published", "value": "отчёт FFFF"},
                               "on_trigger": {"action": "run_analysis", "text": "разобрать"},
                               "expected": "2026-11-05"})
        self.assertEqual(out["condition"]["trigger"]["window_end"], "2026-11-08")
        self.assertEqual(out["valid_until_raised"], {"from": "2026-11-01", "to": "2026-11-08"})

    def test_edit_errors(self):
        self.assertIn("нет условия", self.fail("edit", {"id": "nope", "valid_until": "2026-12-31"})["error"])
        self.assertIn("key", self.fail("edit", {"id": "ffff-trade-notify", "key": "ZZZZ"})["error"])
        v = self.versions("ffff-trade-notify")[0]
        self.assertIn("ничего не меняет",
                      self.fail("edit", {"id": "ffff-trade-notify", "trigger": v["trigger"]})["error"])
        self.assertIn("ставит скрипт", self.fail("edit", {"id": "ffff-trade-notify", "version": 5})["error"])
        self.assertEqual(len(self.versions("ffff-trade-notify")), 1)

    def test_edit_optional_null_removes(self):
        self.ok("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"})
        self.ok("edit", {"id": "ffff-trade-notify", "valid_until": None})
        self.assertNotIn("valid_until", self.versions("ffff-trade-notify")[-1])

    def test_edit_fired_resets_state(self):
        before = [r for r in self.ok("digest", None, "--key", "AAAA")["items"] if r["id"] == "aaaa-below-100"][0]
        self.assertEqual(before["status"], "fired")
        out = self.ok("edit", {"id": "aaaa-below-100", "trigger": {"type": "price_below", "value": 90},
                               "note": "порог ниже после разбора"}, "--state-reset")
        self.assertTrue(out["state_reset"])
        self.assertEqual(out["condition"]["note"], "порог ниже после разбора")
        after = [r for r in self.ok("digest", None, "--key", "AAAA")["items"] if r["id"] == "aaaa-below-100"][0]
        self.assertEqual((after["version"], after["status"], after["last_event"]), (2, "pending", None))
        self.assert_state_untouched()
        out = self.ok("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"})
        self.assertFalse(out["state_reset"])                       # ждало — сбрасывать нечего
    def test_edit_fired_without_flag_rejected(self):
        before = _sha(self.defs)
        out = self.fail("edit", {"id": "aaaa-below-100", "valid_until": "2026-12-31"})
        self.assertIn("--state-reset", out["error"])
        self.assertEqual(out["status"], "fired")
        self.assertEqual(_sha(self.defs), before)
        self.assert_state_untouched()

    def test_edit_fired_deferred_without_flag_rejected(self):
        with open(self.state, encoding="utf-8") as f:
            st = json.load(f)
        st["events"].append({"condition_id": "aaaa-below-100", "version": 1, "event": "owner_mark",
                             "at": "2026-10-30T10:00:00+03:00", "by": "owner",
                             "data": {"mark": "deferred", "until": "2026-11-20"}})
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        self.state_sha = _sha(self.state)
        before = _sha(self.defs)
        out = self.fail("edit", {"id": "aaaa-below-100", "valid_until": "2026-12-31"})
        self.assertIn("--state-reset", out["error"])
        self.assertEqual(out["status"], "fired")
        self.assertEqual(out["deferred_until"], "2026-11-20")
        self.assertEqual(_sha(self.defs), before)

    def test_edit_pending_without_flag_passes(self):
        out = self.ok("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"})
        self.assertFalse(out["state_reset"])

    def test_edit_closed_rejected(self):
        before = _sha(self.defs)
        out = self.fail("edit", {"id": "bbbb-fired", "valid_until": "2026-12-31"})      # done по closed_manual
        self.assertIn("закрыто", out["error"])
        self.assertIn("add", out["error"])
        self.assertEqual(out["status"], "done")
        self.assertEqual(_sha(self.defs), before)
        # истёкшее по valid_until (вычислено модулем на --today) — тоже закрыто
        cid = self.ok("add", dict(PRICE_ADD, valid_until="2026-11-01"))["id"]
        self.ok("edit", {"id": cid, "note": "пока ждёт — правка проходит"}, today="2026-11-01")
        before = _sha(self.defs)
        out = self.fail("edit", {"id": cid, "valid_until": "2026-12-31"}, today="2026-11-05")
        self.assertEqual(out["status"], "expired")
        self.assertEqual(_sha(self.defs), before)

    def test_edit_withdrawn_rejected(self):
        self.ok("withdraw", {"id": "ffff-trade-notify", "reason": "снято"})
        self.assertIn("снято", self.fail("edit", {"id": "ffff-trade-notify", "valid_until": "2026-12-31"})["error"])


class TestWithdraw(Base):
    def test_withdraw_keeps_live_state(self):
        self.ok("withdraw", {"id": "aaaa-below-100", "reason": "план изменился"}, by="owner")
        row = [r for r in self.ok("digest", None, "--key", "AAAA", "--all")["items"] if r["id"] == "aaaa-below-100"][0]
        self.assertEqual((row["status"], row["state_status"], row["version"]), ("withdrawn", "fired", 1))  # снято, было fired
        self.assert_state_untouched()

    def test_withdraw_marks_last_version_only(self):
        self.ok("edit", {"id": "aaaa-below-100", "valid_until": "2026-12-31"}, "--state-reset")
        out = self.ok("withdraw", {"id": "aaaa-below-100", "reason": "план изменился"}, by="owner")
        self.assertEqual(out["version"], 2)
        v1, v2 = self.versions("aaaa-below-100")
        self.assertIsNone(v1["withdrawn"])
        self.assertEqual(v2["withdrawn"]["by"], "owner")
        self.assertEqual(v2["withdrawn"]["reason"], "план изменился")
        self.assertTrue(ds.is_time(v2["withdrawn"]["at"]))
        self.assert_state_untouched()
        row = self.ok("digest", None, "--key", "AAAA", "--all")["items"]
        row = [r for r in row if r["id"] == "aaaa-below-100"][0]
        self.assertEqual((row["status"], row["state_status"]), ("withdrawn", "pending"))  # правка сбросила fired (правило 14)

    def test_repeat_withdraw_is_error(self):
        self.ok("withdraw", {"id": "aaaa-below-100", "reason": "x"})
        before = _sha(self.defs)
        self.assertIn("уже снято", self.fail("withdraw", {"id": "aaaa-below-100", "reason": "y"})["error"])
        self.assertEqual(_sha(self.defs), before)

    def test_reason_required(self):
        self.fail("withdraw", {"id": "aaaa-below-100"})
        self.fail("withdraw", {"id": "aaaa-below-100", "reason": "  "})


class TestDigest(Base):
    def _expected(self, keys=None, only_active=True, today=TODAY):
        with open(self.state, encoding="utf-8") as f:
            state = json.load(f)
        return cm.select(cm.merge(self.doc()["conditions"], state, today), keys=keys, only_active=only_active)

    def test_digest_key_equals_select(self):
        out = self.ok("digest", None, "--key", "AAAA", by=None)
        self.assertEqual(out["items"], self._expected(["AAAA"]))
        self.assertEqual(out["count"], len(out["items"]))
        self.assertTrue(out["items"])

    def test_digest_all_and_list_alias(self):
        a = self.ok("digest", None, "--all", by=None)
        b = self.ok("list", None, "--all", by=None)
        self.assertEqual(a["items"], self._expected(None, only_active=False))
        self.assertEqual(a["items"], b["items"])
        self.assertGreater(len(a["items"]), len(self.ok("digest", None, by=None)["items"]))

    def test_digest_several_keys_and_today(self):
        out = self.ok("digest", None, "--key", "AAAA,RU000A000AA0", "--all", today="2026-12-05", by=None)
        self.assertEqual(out["items"], self._expected(["AAAA", "RU000A000AA0"], False, "2026-12-05"))

    def test_digest_without_state_file(self):
        os.rename(self.state, self.state + ".off")
        out = self.ok("digest", None, "--all", by=None)
        self.assertTrue(out["state_missing"])
        self.assertTrue(all(r["last_event"] is None for r in out["items"]))

    def test_read_commands_do_not_write(self):
        before = _sha(self.defs)
        self.ok("digest", None, "--all")
        self.ok("validate", None)
        self.ok("crosscheck", {"verdicts": {"AAAA": "HOLD"}})
        self.assertEqual(_sha(self.defs), before)
        self.assert_state_untouched()


class TestCrosscheck(Base):
    def setUp(self):
        super().setUp()
        # условие по CCCC через 5 дней велит продать DDDD и купить EEEE
        self.ok("add", {
            "key": "CCCC", "kind": "trade", "trigger": {"type": "date", "value": "2026-11-05"},
            "while_pending": {"verdict": "HOLD"},
            "on_trigger": {"action": "notify_only", "text": "продать DDDD, затем купить EEEE и CCCC"},
            "source": {"kind": "owner", "doc": None},
        })

    def test_conflicts(self):
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "HOLD", "EEEE": "TRIM", "CCCC": "SELL"}})
        got = {(c["security"], c["intent"], c["verdict"]) for c in out["conflicts"]}
        self.assertEqual(got, {("DDDD", "sell", "HOLD"), ("EEEE", "buy", "TRIM")})  # своя бумага не конфликт
        self.assertIn("c-2026-10-31-cccc-1", out["checked"])
        self.assertEqual(out["conflicts"][0]["days_left"], 5)

    def test_no_conflict_when_aligned_and_horizon(self):
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "SELL", "EEEE": "BUY"}})
        self.assertEqual(out["conflicts"], [])
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "HOLD"}, "horizon_days": 3})
        self.assertNotIn("c-2026-10-31-cccc-1", out["checked"])
        self.assertEqual(out["conflicts"], [])

    def test_aliases_word_boundary_and_codes(self):
        out = self.ok("crosscheck", {"verdicts": {"XDDD": "WATCH"}, "aliases": {"XDDD": ["DDDD"]}})
        self.assertEqual([(c["security"], c["mentioned_as"]) for c in out["conflicts"]], [("XDDD", "DDDD")])
        out = self.ok("crosscheck", {"verdicts": {"DDD": "HOLD"}})          # «DDD» внутри «DDDD» — не упоминание
        self.assertEqual(out["conflicts"], [])
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "bogus"}})
        self.assertEqual(out["unknown_verdicts"], ["BOGUS"])

    def test_report_window_and_withdrawn(self):
        self.ok("add", {
            "key": "HHHH", "kind": "review", "trigger": {"type": "report_published", "value": "отчёт"},
            "expected": "2026-11-01", "while_pending": {"verdict": "HOLD"},
            "on_trigger": {"action": "run_analysis", "text": "после отчёта продать DDDD"},
            "source": {"kind": "owner", "doc": None},
        })
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "ADD"}})
        self.assertEqual({c["condition_id"] for c in out["conflicts"]},
                         {"c-2026-10-31-cccc-1", "c-2026-10-31-hhhh-1"})
        self.ok("withdraw", {"id": "c-2026-10-31-cccc-1", "reason": "снято"})
        out = self.ok("crosscheck", {"verdicts": {"DDDD": "ADD"}})
        self.assertEqual({c["condition_id"] for c in out["conflicts"]}, {"c-2026-10-31-hhhh-1"})

    def test_directions_from_codelists(self):
        import codelists
        vd = codelists.map_("verdict_direction")
        self.assertEqual(AC._CONFLICT_IF_BUY, {v for v in codelists.codes("verdict") if vd[v] == "down"})
        self.assertEqual(AC._CONFLICT_IF_SELL, {v for v in codelists.codes("verdict") if vd[v] in ("up", "flat")})


class TestValidate(Base):
    def test_valid(self):
        out = self.ok("validate", None, by=None)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["state_warnings"], [])

    def test_invalid_exit_1(self):
        with open(self.defs, encoding="utf-8") as f:
            text = f.read()
        with open(self.defs, "w", encoding="utf-8") as f:
            f.write(text.replace("kind: trade", "kind: bogus", 1))
        out = self.fail("validate", None, by=None)
        self.assertTrue(any("kind" in e for e in out["errors"]))

    def test_cli_exit_codes(self):
        py = sys.executable
        r = subprocess.run([py, SCRIPT, "validate", "--root", self.root], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])
        r = subprocess.run([py, SCRIPT, "add", "--root", self.root, "--today", TODAY, "--by", "mode_1"],
                           input="{не json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("JSON", json.loads(r.stdout)["error"])
        r = subprocess.run([py, SCRIPT, "close", "--root", self.root], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)                            # удалённые команды — ошибка

    def test_optional_input_does_not_wait_for_stdin(self):
        """list / digest / validate под subprocess с открытым, но пустым входом (stdin=PIPE без записи и без закрытия —
        как у агента без </dev/null) завершаются за ≤ 2 с; add с обязательным входом по-прежнему читает stdin."""
        import tempfile
        import time
        py = sys.executable
        for cmd in ("list", "digest", "validate"):
            with tempfile.TemporaryFile("w+", encoding="utf-8") as fo:
                p = subprocess.Popen([py, SCRIPT, cmd, "--root", self.root, "--today", TODAY], stdin=subprocess.PIPE,
                                     stdout=fo, stderr=subprocess.STDOUT, text=True)
                t0 = time.monotonic()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                    self.fail(f"{cmd}: ждёт stdin дольше 2 с")
                finally:
                    p.stdin.close()
                self.assertLess(time.monotonic() - t0, 2.0)
                fo.seek(0)
                out = fo.read()
            self.assertEqual(p.returncode, 0, f"{cmd}: {out}")
            self.assertTrue(json.loads(out)["ok"])
        r = subprocess.run([py, SCRIPT, "add", "--root", self.root, "--today", TODAY, "--by", "mode_1"],
                           input="{не json", capture_output=True, text=True, timeout=10)
        self.assertIn("JSON", json.loads(r.stdout)["error"])      # обязательный вход читается, как раньше


class TestReinvest(Base):
    """R30 (03.11): исход «реинвестировать» и запрет вердикта «держать/докупать» после погашения облигации."""
    BOND = "RU000A105146"
    SET_BUY = {"key": BOND, "kind": "trade", "trigger": {"type": "date", "value": "2026-11-19"},
               "while_pending": {"verdict": "HOLD_TO_MAT", "text": "держим до погашения"},
               "on_trigger": {"action": "set_verdict", "verdict": "BUY", "text": "погашение → реинвест в ОФЗ"},
               "source": {"kind": "owner", "doc": None}}
    REINVEST = {"action": "reinvest", "target": "ОФЗ/>10", "amount_source": "redemption",
                "text": "погашение → реинвест в ОФЗ длиннее 10 лет, в USD не возвращать"}

    def snap(self, maturity="2026-11-19"):
        d = os.path.join(self.root, "Portfolio", "snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "portfolio-2026-10-30.json"), "w", encoding="utf-8") as f:
            json.dump({"holdings": [{"ticker": self.BOND, "isin": self.BOND, "asset_type": "bond", "qty": 5,
                                     "maturity_date": maturity}]}, f)

    def test_add_reinvest(self):
        self.snap()
        out = self.ok("add", dict(self.SET_BUY, on_trigger=self.REINVEST))
        self.assertEqual(out["maturity"], "2026-11-19")
        row = [r for r in cm.merge(ds.load_yaml(self.defs)["conditions"], {"events": []}, TODAY) if r["id"] == out["id"]][0]
        self.assertEqual((row["action_code"], row["target"], row["amount_source"], row["verdict_on_trigger"]),
                         ("reinvest", "ОФЗ/>10", "redemption", None))

    def test_add_verdict_after_maturity_rejected(self):
        self.snap()
        before = _sha(self.defs)
        out = self.fail("add", self.SET_BUY)
        self.assertTrue(any("после погашения 2026-11-19" in e for e in out["errors"]), out)
        self.assertEqual(_sha(self.defs), before)
        self.snap("2026-12-01")                                      # триггер раньше погашения — можно
        self.assertIsNone(self.ok("add", self.SET_BUY).get("errors"))

    def test_no_maturity_known_skips(self):
        out = self.ok("add", self.SET_BUY)                           # снапшотов нет — проверка пропущена
        self.assertIsNone(out["maturity"])

    def test_edit_set_verdict_to_reinvest_and_validate(self):
        out = self.ok("add", self.SET_BUY)                           # записано до того, как дата стала известна
        self.snap()
        val = self.fail("validate", None, by=None)
        self.assertTrue(any(e.startswith(f"{out['id']}@1: on_trigger.verdict: после погашения") for e in val["errors"]), val)
        bad = self.fail("edit", {"id": out["id"], "on_trigger": dict(self.REINVEST, verdict="BUY")})
        self.assertTrue(any("action=reinvest вердикта нет" in e for e in bad["errors"]), bad)
        ed = self.ok("edit", {"id": out["id"], "on_trigger": self.REINVEST, "note": "R30: деньги в другую корзину"})
        self.assertEqual((ed["version"], ed["maturity"]), (2, "2026-11-19"))
        self.assertEqual(self.ok("validate", None, by=None)["errors"], [])

    def test_withdrawn_not_checked_by_validate(self):
        out = self.ok("add", self.SET_BUY)
        self.snap()
        self.ok("withdraw", {"id": out["id"], "reason": "бумаги нет"})
        self.assertEqual(self.ok("validate", None, by=None)["errors"], [])

    def plan(self, keys):
        with open(os.path.join(self.root, "Portfolio", "plan.json"), "w", encoding="utf-8") as f:
            json.dump({"bond_buckets": [{"key": k, "share": 0.1} for k in keys]}, f, ensure_ascii=False)

    def test_reinvest_target_checked_against_live_plan(self):
        """Правило 20: при плане в корне корзина-цель обязана в нём быть; ключ бумаги не проверяется."""
        self.plan(["ОФЗ/<10", "КОРП/AA+"])
        before = _sha(self.defs)
        bad = self.fail("add", dict(self.SET_BUY, on_trigger=self.REINVEST))           # ОФЗ/>10 вне плана
        self.assertTrue(any("on_trigger.target: корзины ОФЗ/>10 нет в плане (есть: ОФЗ/<10, КОРП/AA+)" in e
                            for e in bad["errors"]), bad)
        self.assertEqual(_sha(self.defs), before)
        self.ok("add", dict(self.SET_BUY, on_trigger=dict(self.REINVEST, target="ОФЗ/<10")))
        self.ok("add", dict(self.SET_BUY, on_trigger=dict(self.REINVEST, target="SU26248RMFS3")))  # бумага
        self.plan(["ОФЗ/<10"])
        self.assertEqual(self.ok("validate", None, by=None)["errors"], [])
        self.plan(["КОРП/AA+"])                                      # корзину убрали из плана — validate видит
        val = self.fail("validate", None, by=None)
        self.assertTrue(any(": on_trigger.target: корзины ОФЗ/<10 нет в плане (есть: КОРП/AA+)" in e
                            for e in val["errors"]), val)

    def test_no_plan_falls_back_to_codelist(self):
        out = self.ok("add", dict(self.SET_BUY, on_trigger=self.REINVEST))           # плана нет — кодлист
        self.assertEqual(out["condition"]["on_trigger"]["target"], "ОФЗ/>10")
        self.assertEqual(ds.plan_bucket_errors(out["condition"], None), [])


class TestRestamp(Base):
    """R33: правка условий сама перештамповывает обзор недели того же дня, где есть бумага (приоритет по новым условиям)."""
    REVIEW = ("review_date: '2026-10-31'\nrecorded_at: '2026-10-31T11:00:00+03:00'\nper_stock:\n"
              "  ZZZZ:\n    advisor_verdict: HOLD\n    unconstrained_verdict: HOLD\n    advisor_verdict_confidence: 0.7\n"
              "    verification_priority: LOW\n  YYYY:\n    advisor_verdict: HOLD\n    unconstrained_verdict: HOLD\n"
              "    advisor_verdict_confidence: 0.7\n    verification_priority: LOW\n")
    DOC = "Portfolio/weekly-reviews/weekly-review-stock-2026-10-31.yaml"

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, "Portfolio", "weekly-reviews"))
        self.rev = os.path.join(self.root, *self.DOC.split("/"))
        with open(self.rev, "w", encoding="utf-8") as f:
            f.write(self.REVIEW)

    def prio(self):
        return {k: v["verification_priority"] for k, v in ds.load_yaml(self.rev)["per_stock"].items()}

    def test_add_withdraw_restamp_and_idempotent(self):
        out = self.ok("add", dict(PRICE_ADD, key="ZZZZ"))
        self.assertEqual(out["restamped"], [{"doc": self.DOC, "priority_changed": ["ZZZZ: LOW → MEDIUM"],
                                             "stamped": ["verification_priority"]}])
        self.assertEqual(self.prio(), {"ZZZZ": "MEDIUM", "YYYY": "LOW"})
        # повтор штампа без новой правки — ничего не меняется (идемпотентность), файл байт в байт
        before = _sha(self.rev)
        again, warns = AC._restamp(AC._parser().parse_args(["add", "--root", self.root, "--now", NOW]), "ZZZZ", NOW)
        self.assertEqual((again, warns), ([{"doc": self.DOC, "priority_changed": [], "stamped": []}], []))
        self.assertEqual(_sha(self.rev), before)
        wd = self.ok("withdraw", {"id": out["id"], "reason": "бумаги нет в портфеле"}, by="owner")
        self.assertEqual(wd["restamped"][0]["priority_changed"], ["ZZZZ: MEDIUM → LOW"])
        self.assertEqual(self.prio()["ZZZZ"], "LOW")
        self.assert_state_untouched()

    def test_no_review_today_or_key_absent(self):
        self.assertEqual(self.ok("add", dict(PRICE_ADD, key="GGGG"))["restamped"], [])      # бумаги в обзоре нет
        out = self.ok("add", dict(PRICE_ADD, key="ZZZZ"), now="2026-11-01T09:00:00+03:00")  # обзор вчерашний
        self.assertEqual(out["restamped"], [])
        self.assertEqual(self.prio()["ZZZZ"], "LOW")

    def test_stamp_error_is_warning_not_rollback(self):
        with open(self.rev, "w", encoding="utf-8") as f:
            f.write("review_date: '2026-10-31'\nper_stock: [\n")
        out = self.ok("add", dict(PRICE_ADD, key="ZZZZ"))
        self.assertEqual(out["restamped"], [])
        self.assertTrue(out["restamp_warnings"] and "перештамповка не удалась" in out["restamp_warnings"][0], out)
        self.assertEqual(len(self.versions(out["id"])), 1)                                # условие записано


class TestEditSource(Base):
    """R33: source новой версии — по автору правки, а не копия прежней (у мигрированных было migration)."""

    def edit(self, by, **extra):
        cid = "ffff-trade-notify"
        self.assertEqual(self.versions(cid)[-1]["source"]["kind"], "migration")
        n = len(self.versions(cid)) + 12
        self.ok("edit", dict({"id": cid, "trigger": {"type": "price_above", "value": n}}, **extra), by=by)
        return self.versions(cid)[-1]["source"]

    def test_owner(self):
        self.assertEqual(self.edit("owner"), {"kind": "owner", "doc": None})

    def test_advisor_mode(self):
        self.assertEqual(self.edit("mode_9"), {"kind": "report", "doc": None})

    def test_script_keeps_previous(self):
        self.assertEqual(self.edit("script")["kind"], "migration")

    def test_payload_source_wins(self):
        src = {"kind": "report", "doc": "Portfolio/reports/r.md"}
        self.assertEqual(self.edit("owner", source=src), src)


class TestGuards(unittest.TestCase):
    """Сторожа по исходнику: состояние только читается, удалений нет, одна точка записи."""

    @classmethod
    def setUpClass(cls):
        with open(SCRIPT, encoding="utf-8") as f:
            cls.src = f.read()

    def test_state_never_opened_for_write(self):
        self.assertEqual(self.src.count("conditions-state.json"), 2)  # докстринг + STATE_REL
        self.assertIn('STATE_REL = ("Portfolio", "conditions-state.json")', self.src)
        writes = re.findall(r"open\(([^,)]+),\s*[\"'](?:w|a|x|r\+|wb|ab)[\"']", self.src)
        self.assertEqual(writes, ["tmp"], writes)                     # пишется только временный файл
        self.assertEqual(re.findall(r"os\.replace\(([^)]*)\)", self.src), ["tmp, path"])
        self.assertEqual(self.src.count("_write_defs(defs_path"), 3)  # add, edit, withdraw — только файл определений
        self.assertNotRegex(self.src, r"_write_defs\(\s*state")

    def test_no_deletions(self):
        self.assertNotRegex(self.src, r"os\.(remove|unlink|rmdir|removedirs)\(|shutil\.|\.unlink\(")

    def test_removed_commands(self):
        for c in ("close", "open", "remove", "fire", "touch", "evaluate", "prune"):
            self.assertNotIn(c, AC.COMMANDS)
        self.assertEqual(set(AC.COMMANDS), {"add", "edit", "withdraw", "list", "digest", "crosscheck", "validate"})

    def test_shared_imports(self):
        for mod in ("codelists", "conditions_merge", "ds_schemas", "time_msk"):
            self.assertRegex(self.src, rf"(?m)^import {mod}\b")
        self.assertFalse(os.path.exists(os.path.join(REPO, "tools", "data-structures", "validators", "ds_schemas.py")))


class TestSiteFlags(Base):
    """Флаги сайта (задача 2.4 «без ИИ»): --emit, --no-restamp, --owner-only; условие владельца kind: watch без вердикта."""
    OWNER_ADD = {
        "key": "ZZZZ", "kind": "watch", "trigger": {"type": "price_below", "value": 250.5},
        "while_pending": {"verdict": None, "text": ""},
        "on_trigger": {"action": "notify_only", "text": "посмотреть, пора ли покупать"},
        "source": {"kind": "owner", "doc": None},
    }

    def test_emit_writes_nothing_and_returns_text_and_digest(self):
        import yaml
        before = _sha(self.defs)
        out = self.ok("add", self.OWNER_ADD, "--emit", "--no-restamp", by="owner")
        self.assertEqual(_sha(self.defs), before)                       # на mount ничего не записано
        em = out["emitted"]
        self.assertEqual((em["path"], em["base_digest"]), ("Portfolio/conditions.yaml", before))
        doc = yaml.safe_load(em["text"])
        self.assertEqual(ds.validate_conditions_file(doc), [])
        new = [c for c in doc["conditions"] if c["id"] == out["id"]]
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0]["created_by"], new[0]["source"]["kind"], new[0]["kind"]), ("owner", "owner", "watch"))
        self.assertNotIn("restamped", out)
        self.assert_state_untouched()

    def test_emit_validation_error_is_error(self):
        bad = dict(self.OWNER_ADD, trigger={"type": "price_below", "value": -1})
        self.assertIn("валидация", self.fail("add", bad, "--emit", by="owner")["error"])

    def test_no_restamp_skips_restamp_without_emit(self):
        out = self.ok("add", self.OWNER_ADD, "--no-restamp", by="owner")
        self.assertNotIn("restamped", out)
        self.assertNotIn("restamp_warnings", out)
        self.assertTrue(any(c["id"] == out["id"] for c in self.doc()["conditions"]))   # файл записан
        out2 = self.ok("add", dict(self.OWNER_ADD, key="YYYY"), by="owner")
        self.assertIn("restamped", out2)                                 # без флага штамп по-прежнему

    def test_watch_allows_null_verdict_others_do_not(self):
        bad = dict(self.OWNER_ADD, kind="trade")
        self.assertIn("валидация", self.fail("add", bad, "--emit", by="owner")["error"])
        self.ok("add", self.OWNER_ADD, "--emit", by="owner")

    def test_verdict_now_none_for_watch_row(self):
        out = self.ok("add", self.OWNER_ADD, by="owner")
        rows = cm.merge(self.doc()["conditions"], {"events": []}, TODAY)
        row = [r for r in rows if r["id"] == out["id"]][0]
        self.assertIsNone(row["verdict_now"])                            # наблюдение не закрепляет вердикт бумаги
        self.assertEqual(row["action_code"], "notify_only")

    def test_owner_only_withdraws_own_refuses_foreign(self):
        own = self.ok("add", self.OWNER_ADD, by="owner")["id"]
        err = self.fail("withdraw", {"id": "aaaa-below-100", "reason": "x"}, "--owner-only", by="owner")["error"]
        self.assertIn("поставил не ты", err)
        self.assertIsNone(self.versions("aaaa-below-100")[-1]["withdrawn"])
        out = self.ok("withdraw", {"id": own, "reason": "не нужно"}, "--owner-only", "--emit", by="owner")
        self.assertIsNone(self.versions(own)[-1]["withdrawn"])           # --emit: пока не записано
        self.assertEqual(out["emitted"]["base_digest"], _sha(self.defs))
        self.ok("withdraw", {"id": own, "reason": "не нужно"}, "--owner-only", by="owner")
        self.assertEqual(self.versions(own)[-1]["withdrawn"]["by"], "owner")
        # без флага чужое условие по-прежнему снимается (советник и CLI)
        self.ok("withdraw", {"id": "aaaa-below-100", "reason": "x"}, by="owner")


if __name__ == "__main__":
    unittest.main(verbosity=2)

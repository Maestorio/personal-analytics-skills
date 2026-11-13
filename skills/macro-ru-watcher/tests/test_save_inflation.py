#!/usr/bin/env python3
"""save_inflation.py — запись недельной инфляции в macro-snapshots/inflation/model.jsonl (решение владельца 11.11).

Контракты:
  • validate(): все поля по границам (week_pct −3…5, yoy_pct −5…100, даты ГГГГ-ММ-ДД не из будущего и не старше года,
    week_period 3–40, source_name 2–80, source_url только http/https); лишние поля отбрасываются;
    author и recorded_at ставит писатель; порядок ключей фиксирован;
  • без --apply файл не создаётся; с --apply — одна строка jsonl, повтор той же записи — «уже записано» без дубля,
    другая — дописывается; чужая нескончаемая строка (нет \\n в конце) не склеивается;
  • гейт require_ai: режим «без ИИ» (_hub/settings.json) — код 3, файл не создан; плохой вход — код 1, файла нет;
  • файл владельца owner.jsonl скрипт не трогает.
Сеть не нужна. Запуск: python3 skills/macro-ru-watcher/tests/test_save_inflation.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "save_inflation.py"
sys.path.insert(0, str(HERE.parent / "scripts"))
import save_inflation as si  # noqa: E402

TODAY = date(2026, 11, 12)
GOOD = {"date": "2026-11-12", "week_pct": 0.11, "week_period": "03–09.11", "yoy_pct": 6.4, "yoy_as_of": "2026-11-09",
        "source_url": "https://rosstat.gov.ru/x", "source_name": "Росстат"}
ARGS = ["--date", "2026-11-12", "--week-pct", "0.11", "--week-period", "03–09.11", "--yoy-pct", "6.4",
        "--yoy-as-of", "2026-11-09", "--source-name", "Росстат", "--source-url", "https://rosstat.gov.ru/x", "--today", "2026-11-12"]


def run(root, *extra, args=ARGS):
    env = {**os.environ, "HUB_URL": "", "HUB_AUTH": ""}
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args, *extra],
                          capture_output=True, text=True, env=env, timeout=60)


def mkroot():
    t = Path(tempfile.mkdtemp(prefix="infl-"))
    (t / "_hub").mkdir()
    return t


class Validate(unittest.TestCase):
    def v(self, **ch):
        rec = {**GOOD, **ch}
        return si.validate(rec, TODAY, "model", "2026-11-12T10:00:00+03:00")

    def test_good_and_key_order(self):
        r, e = self.v()
        self.assertEqual(e, [])
        self.assertEqual(list(r), list(si.FIELDS))
        self.assertEqual((r["author"], r["recorded_at"]), ("model", "2026-11-12T10:00:00+03:00"))

    def test_extra_fields_dropped(self):
        r, _ = self.v(author="owner", junk=1)
        self.assertEqual(r["author"], "model")
        self.assertNotIn("junk", r)

    def test_bounds(self):
        for ch in ({"week_pct": 5.1}, {"week_pct": -3.1}, {"week_pct": "0.1"}, {"week_pct": True}, {"yoy_pct": 101},
                   {"yoy_pct": None}, {"date": "2026-11-13"}, {"date": "2025-10-01"}, {"date": "12.11.2026"},
                   {"yoy_as_of": "2026-12-01"}, {"week_period": "ab"}, {"week_period": "x" * 41}, {"source_name": "R"},
                   {"source_name": ""}, {"source_url": "ftp://x"}, {"source_url": "http://a b"}):
            r, e = self.v(**ch)
            self.assertIsNone(r, ch)
            self.assertTrue(e, ch)

    def test_optional_url_and_default_asof(self):
        r, e = self.v(source_url=None, yoy_as_of=None)
        self.assertEqual(e, [])
        self.assertIsNone(r["source_url"])
        self.assertEqual(r["yoy_as_of"], "2026-11-12")

    def test_not_object(self):
        self.assertEqual(si.validate([], TODAY, "model", "x")[0], None)


class Cli(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        t = mkroot()
        r = run(t)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((t / "macro-snapshots").exists())

    def test_apply_idempotent_and_append(self):
        t = mkroot()
        f = t / "macro-snapshots/inflation/model.jsonl"
        self.assertEqual(run(t, "--apply").returncode, 0)
        rows = f.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["author"], "model")
        r = run(t, "--apply")                                   # тот же вход — без дубля
        self.assertIn("уже записано", r.stdout)
        self.assertEqual(len(f.read_text(encoding="utf-8").splitlines()), 1)
        a2 = [x if x != "0.11" else "0.2" for x in ARGS]
        self.assertEqual(run(t, "--apply", args=a2).returncode, 0)
        self.assertEqual(len(f.read_text(encoding="utf-8").splitlines()), 2)
        self.assertFalse((t / "macro-snapshots/inflation/owner.jsonl").exists())

    def test_no_trailing_newline_not_glued(self):
        t = mkroot()
        f = t / "macro-snapshots/inflation/model.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text('{"date": "2026-11-05"}', encoding="utf-8")
        self.assertEqual(run(t, "--apply").returncode, 0)
        lines = f.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["date"], "2026-11-12")

    def test_bad_input_code_1(self):
        t = mkroot()
        r = run(t, "--apply", args=[x if x != "0.11" else "9" for x in ARGS])
        self.assertEqual(r.returncode, 1)
        self.assertIn("week_pct", r.stderr)
        self.assertFalse((t / "macro-snapshots").exists())

    def test_gate_off_code_3(self):
        t = mkroot()
        (t / "_hub/settings.json").write_text(json.dumps(
            {"schema": "hub-settings@1", "ai_mode": "off", "off_since": "2026-11-01T10:00:00+03:00", "returned_at": None,
             "by": "site", "note": None, "updated_at": "2026-11-12T09:00:00+03:00"}), encoding="utf-8")
        r = run(t, "--apply")
        self.assertEqual(r.returncode, 3)
        self.assertIn("сайт в режиме «без ИИ»", r.stderr)
        self.assertFalse((t / "macro-snapshots").exists())
        self.assertEqual(run(t).returncode, 0)                  # проверка без записи гейтом не закрыта


if __name__ == "__main__":
    unittest.main(verbosity=1)

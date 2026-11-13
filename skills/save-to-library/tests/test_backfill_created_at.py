#!/usr/bin/env python3
"""backfill_created_at.py: проставление created_at из mtime — только при совпадении дня, атомарно, mtime сохранён."""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.backfill_created_at import run, plan_file  # noqa: E402

FM = '---\ntitle: "T"\ndate: "{d}"\nkind: "general"\n---\n# T\nтело\n'


def _mk(dirp: Path, name: str, date: str, mtime: datetime, extra: str = "") -> Path:
    p = dirp / name
    txt = FM.format(d=date)
    if extra:
        txt = txt.replace('kind: "general"\n', 'kind: "general"\n' + extra)
    p.write_text(txt, encoding="utf-8")
    ts = time.mktime(mtime.timetuple())
    os.utime(p, (ts, ts))
    return p


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name)
        self.rdir = self.mem / "Portfolio" / "reports"
        self.rdir.mkdir(parents=True)
        self.same = _mk(self.rdir, "2026-10-28-a.md", "2026-10-28", datetime(2026, 10, 28, 15, 14))
        self.next = _mk(self.rdir, "2026-08-15-b.md", "2026-08-15", datetime(2026, 8, 16, 0, 50))
        self.has = _mk(self.rdir, "2026-10-27-c.md", "2026-10-27", datetime(2026, 10, 27, 9, 0), 'created_at: "2026-10-27T08:59"\n')
        (self.rdir / "nofm.md").write_text("# без шапки\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan(self):
        by = {p["file"]: p for p in run(self.mem, apply=False)}
        self.assertEqual(by["2026-10-28-a.md"], {"file": "2026-10-28-a.md", "action": "stamp", "created_at": "2026-10-28T15:14"})
        self.assertEqual(by["2026-08-15-b.md"]["action"], "skip")
        self.assertIn("≠ date", by["2026-08-15-b.md"]["reason"])
        self.assertEqual(by["2026-10-27-c.md"]["reason"], "created_at уже есть")
        self.assertEqual(by["nofm.md"]["reason"], "нет frontmatter")
        self.assertNotIn("created_at", self.same.read_text(encoding="utf-8"))   # без --apply ничего не пишется

    def test_apply(self):
        mt = self.same.stat().st_mtime
        run(self.mem, apply=True)
        txt = self.same.read_text(encoding="utf-8")
        self.assertIn('date: "2026-10-28"\ncreated_at: "2026-10-28T15:14"\nkind: "general"\n', txt)
        self.assertTrue(txt.startswith("---\n") and txt.endswith("# T\nтело\n"))
        self.assertEqual(self.same.stat().st_mtime, mt)                        # mtime восстановлен
        self.assertNotIn("created_at", self.next.read_text(encoding="utf-8"))   # следующий день — не тронут
        self.assertEqual(self.has.read_text(encoding="utf-8").count("created_at"), 1)
        self.assertEqual(plan_file(self.same)["reason"], "created_at уже есть")   # идемпотентно
        self.assertFalse(list(self.rdir.glob("*.tmp")))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=0).result
    n = r.testsRun
    print(f"Итого: {n - len(r.failures) - len(r.errors)} из {n} прошли")
    sys.exit(1 if (r.failures or r.errors) else 0)

"""Тесты сторожа «нет файлов вне схемы» (tools/data-structures/schema_guard.py). Синтетика, mount не читается.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/tests/test_schema_guard.py
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import schema_guard as sg  # noqa: E402

GOOD = [
    "Portfolio/INDEX.md", "Portfolio/plan.json", "Portfolio/plan-journal.jsonl", "Portfolio/conditions.yaml",
    "Portfolio/conditions-state.json", "Portfolio/conditions-archive-2026.yaml", "Portfolio/security-attrs.json",
    "Portfolio/security-types.json",
    "Portfolio/decisions/2026-10-30T1015-GMKN.json",
    "Portfolio/weekly-reviews/weekly-review-stock-2026-10-28.yaml",
    "Portfolio/weekly-reviews/weekly-review-bond-2026-10-28.md",
    "Portfolio/weekly-reviews/weekly-review-2026-05-06.yaml",
    "Portfolio/reports/2026-10-29-single-analysis-gmkn.md", "Portfolio/reports/portfolio-candidates-outside-ie-2026-05-13.md",
    "Portfolio/snapshots/portfolio-2026-10-30.json", "Portfolio/snapshots/auto/portfolio-2026-10-28-1042-trades.json",
    "Portfolio/snapshots/auto/build-summary-2026-10-21.json", "Portfolio/snapshots/.versions/portfolio-2026-10-28.20261028T0010.json",
    "Portfolio/decision-journal/journal.json", "Portfolio/decision-journal/report-2026-10-30.md",
    "Portfolio/.backups/INDEX-2026-10-31-1200.md",
    "Portfolio/decision-journal/refusals.yaml",
    "Portfolio/stress/stress-2026-05-11-mfc-shell-d1.yaml", "Portfolio/stress/stress-2026-05-11-mfc-shell-d1.md",
    "Portfolio/integrated-views/integrated-view-2026-08-06.md", "Portfolio/coherence-audits/coherence-audit-2026-08-07.md",
    "Portfolio/sensitivity/macro-scenarios-2026-07-02-Esens.yaml",
    "Portfolio/_bak-cutover-2026-08-03/stress/stress-2026-05-11-mfc-shell-d1.yaml",
    "forecasts/brent-price-2026-09-17.yaml", "forecasts/INDEX.md", "scenarios/scenario-brent-dec-2026-2026-05-01.md",
    "macro-chain/macro-scenarios-2026-07-05.yaml", "macro-chain/macro-marginal-2026-07-05.yaml",
    "monitor-reports/monitor-report-2026-10-26-v2.yaml",
    "macro-snapshots/ru-2026-10-30.md", "macro-snapshots/auto/ru-2026-10-30.json",
]
BAD = {
    "Portfolio/gate-reviews.yaml": sg.R_ABOLISHED,
    "Portfolio/gate-reviews-archive-2026.yaml": sg.R_ABOLISHED,
    "Portfolio/securities/AAA.json": sg.R_ABOLISHED,
    "Portfolio/.backups/old.md": sg.R_ABOLISHED,
    "Portfolio/.backups/conditions-2026-10-20-0054.yaml": sg.R_ABOLISHED,
    "Portfolio/.backups/INDEX-2026-10-31.md": sg.R_ABOLISHED,
    "Portfolio/checkpoints.yaml": sg.R_ABOLISHED,
    "stale_flags.yaml": sg.R_ABOLISHED,
    "Portfolio/reports/a.md.pre-ds.bak": sg.R_BACKUP,
    "Portfolio/weekly-reviews/weekly-review-stock-2026-05-11.yaml.bak": sg.R_BACKUP,
    "Portfolio/snapshots/portfolio-2026-08-02.json.bak-sector-fix": sg.R_BACKUP,
    "Portfolio/snapshots/_to_delete/write_test_tmp": sg.R_BACKUP,
    "Portfolio/.DS_Store": sg.R_SERVICE,
    "Portfolio/stress/notes.txt": sg.R_MASK,
    "Portfolio/decisions/not-a-decision.json": sg.R_MASK,
    "forecasts/russia-war.docx": sg.R_MASK,
    "macro-chain/mfc-20260504-prompts.md": sg.R_MASK,
    "monitor-reports/monitor-report-2026-10-26.json": sg.R_MASK,
    "macro-snapshots/random.md": sg.R_MASK,
    "scenarios/scenario-x-2026-05-01.yaml.bak-w": sg.R_BACKUP,
}


class SchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def put(self, rels, body="x"):
        for rel in rels:
            p = self.tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sg.main(["--root", str(self.tmp), *args])
        return code, out.getvalue(), err.getvalue()

    def test_clean_tree_exit_0(self):
        self.put(GOOD)
        res = sg.scan(self.tmp)
        self.assertEqual(res["outside"], [])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Вне схемы: ничего", out)

    def test_each_foreign_file_found_with_reason(self):
        self.put(GOOD)
        self.put(BAD)
        res = sg.scan(self.tmp)
        got = {e["path"]: e["reason"].split(":")[0] for e in res["outside"]}
        self.assertEqual(got, BAD)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 1)
        for rel in BAD:
            self.assertIn(rel, out)

    def test_backups_only_index_copies(self):
        """DS-BAK: в .backups/ живут только копии INDEX.md от update_index.py; копия условий — вне схемы."""
        self.put(["Portfolio/.backups/INDEX-2026-10-31-1200.md", "Portfolio/.backups/conditions-2026-10-20-0054.yaml"])
        got = {e["path"]: e["reason"] for e in sg.scan(self.tmp)["outside"]}
        self.assertEqual(list(got), ["Portfolio/.backups/conditions-2026-10-20-0054.yaml"])
        self.assertTrue(got["Portfolio/.backups/conditions-2026-10-20-0054.yaml"].startswith(sg.R_ABOLISHED))

    def test_size_and_json_output(self):
        self.put(GOOD)
        self.put(["Portfolio/gate-reviews.yaml"], body="12345")
        code, out, _ = self.run_cli("--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual([(e["path"], e["size"]) for e in data["outside"]], [("Portfolio/gate-reviews.yaml", 5)])

    def test_empty_schema_dirs_reported_not_failing(self):
        self.put(["Portfolio/INDEX.md", "forecasts/brent-price-2026-09-17.yaml"])
        res = sg.scan(self.tmp)
        self.assertEqual(res["outside"], [])
        self.assertIn("Portfolio/decisions", res["empty"])
        self.assertIn("macro-chain", res["empty"])
        self.assertNotIn("forecasts", res["empty"])
        self.assertEqual(self.run_cli()[0], 0)

    def test_does_not_delete_and_ignores_other_top_dirs(self):
        self.put(GOOD + list(BAD) + ["Food/anything.bin", "Gaming/x.tmp"])
        before = sorted(p.relative_to(self.tmp).as_posix() for p in self.tmp.rglob("*") if p.is_file())
        self.run_cli()
        after = sorted(p.relative_to(self.tmp).as_posix() for p in self.tmp.rglob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertFalse(any(e["path"].startswith(("Food", "Gaming")) for e in sg.scan(self.tmp)["outside"]))

    def test_missing_root_exit_2(self):
        shutil.rmtree(self.tmp)
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("Корень не найден", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)

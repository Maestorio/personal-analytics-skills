#!/usr/bin/env python3
"""Тесты update_index.py — детерминированная вставка в INDEX.md / _sync_log.md.

Контекст: шаг F4 выполнялся моделью и стоил чтения INDEX.md (138 КБ) и
_sync_log.md (327 КБ) целиком на каждое сохранение. Скрипт делает механическую
часть (размещение строки, порядок newest-first, бэкап, идемпотентность),
модель по-прежнему пишет текст записи.

Тесты покрывают: попадание строки под шапку таблицы нужной секции, порядок,
идемпотентность по имени файла, режим replace, бэкап, dry-run, поиск секции,
дописывание в «## Метаданные» и в конец _sync_log.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "update_index.py")

INDEX_FIXTURE = """# Claude-Memory · Portfolio · INDEX

## Активные артефакты

### snapshots/

| Файл | Тип | Дата |
|---|---|---|
| portfolio-2026-08-06.json | snapshot | 2026-08-06 |

### weekly-reviews/

| Файл | Тип | Дата | Snapshot |
|---|---|---|---|
| weekly-review-bond-2026-08-06.yaml | weekly-bonds-review | 2026-08-06 | portfolio-2026-08-06 |
| weekly-review-stock-2026-08-06.yaml | weekly-stocks-review | 2026-08-06 | portfolio-2026-08-06 |

### Gate Reviews (METH-2)

Текст без таблицы.

## Метаданные

- Создано: 2026-05-04
- Обновлено: 2026-08-06 (weekly-review-bond-2026-08-06)
"""

SYNC_FIXTURE = "2026-08-06 | save-to-library | Workflow F | старая запись\n"


def run(cmd, payload):
    p = subprocess.run([sys.executable, SCRIPT, cmd],
                       input=json.dumps(payload), capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout) if p.stdout.strip() else {}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = os.path.join(self.tmp.name, "INDEX.md")
        self.log = os.path.join(self.tmp.name, "_sync_log.md")
        with open(self.index, "w", encoding="utf-8") as fh:
            fh.write(INDEX_FIXTURE)
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write(SYNC_FIXTURE)

    def tearDown(self):
        self.tmp.cleanup()

    def index_text(self):
        with open(self.index, encoding="utf-8") as fh:
            return fh.read()


class TestAddRows(_Base):
    ROW = "| weekly-review-stock-2026-08-15.yaml | weekly-stocks-review | 2026-08-15 | portfolio-2026-08-15 |"

    def test_row_inserted_under_table_header(self):
        rc, out = run("add-rows", {"index_path": self.index,
                                   "section": "### weekly-reviews/", "rows": [self.ROW]})
        self.assertEqual(rc, 0)
        self.assertTrue(out["ok"])
        lines = self.index_text().split("\n")
        sep = next(i for i, l in enumerate(lines) if l.startswith("|---|---|---|---|"))
        self.assertEqual(lines[sep + 1], self.ROW)

    def test_newest_first_order_preserved(self):
        run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                         "rows": [self.ROW]})
        txt = self.index_text()
        self.assertLess(txt.index("weekly-review-stock-2026-08-15.yaml"),
                        txt.index("weekly-review-bond-2026-08-06.yaml"))

    def test_multiple_rows_keep_given_order(self):
        r2 = "| weekly-review-bond-2026-08-15.yaml | weekly-bonds-review | 2026-08-15 | x |"
        run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                         "rows": [self.ROW, r2]})
        txt = self.index_text()
        self.assertLess(txt.index("stock-2026-08-15"), txt.index("bond-2026-08-15"))

    def test_wrong_section_not_touched(self):
        run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                         "rows": [self.ROW]})
        lines = self.index_text().split("\n")
        snap_hdr = lines.index("### snapshots/")
        wr_hdr = lines.index("### weekly-reviews/")
        self.assertNotIn("2026-08-15", "\n".join(lines[snap_hdr:wr_hdr]))

    def test_idempotent_same_file_skipped(self):
        run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                         "rows": [self.ROW]})
        rc, out = run("add-rows", {"index_path": self.index,
                                   "section": "### weekly-reviews/", "rows": [self.ROW]})
        self.assertEqual(out["skipped_existing"], ["weekly-review-stock-2026-08-15.yaml"])
        self.assertEqual(self.index_text().count("weekly-review-stock-2026-08-15.yaml"), 1)

    def test_replace_updates_in_place(self):
        run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                         "rows": [self.ROW]})
        upd = self.ROW.replace("portfolio-2026-08-15 |", "portfolio-2026-08-15 (исправлено) |")
        rc, out = run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                                   "rows": [upd], "replace": True})
        self.assertEqual(out["replaced"], ["weekly-review-stock-2026-08-15.yaml"])
        self.assertIn("(исправлено)", self.index_text())
        self.assertEqual(self.index_text().count("weekly-review-stock-2026-08-15.yaml"), 1)

    def test_backup_created(self):
        bdir = os.path.join(self.tmp.name, ".backups")
        rc, out = run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                                   "rows": [self.ROW], "backup_dir": bdir})
        self.assertTrue(os.path.isfile(out["backup"]))
        with open(out["backup"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), INDEX_FIXTURE)

    def test_dry_run_writes_nothing(self):
        rc, out = run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                                   "rows": [self.ROW], "dry_run": True})
        self.assertTrue(out["ok"])
        self.assertGreater(out["bytes_after"], out["bytes_before"])
        self.assertEqual(self.index_text(), INDEX_FIXTURE)

    def test_section_without_table_errors(self):
        rc, out = run("add-rows", {"index_path": self.index,
                                   "section": "### Gate Reviews (METH-2)", "rows": [self.ROW]})
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])

    def test_missing_section_errors(self):
        rc, out = run("add-rows", {"index_path": self.index,
                                   "section": "### нет-такой/", "rows": [self.ROW]})
        self.assertEqual(rc, 1)
        self.assertIn("секция не найдена", out["error"])

    def test_non_table_row_rejected(self):
        rc, out = run("add-rows", {"index_path": self.index,
                                   "section": "### weekly-reviews/", "rows": ["просто текст"]})
        self.assertEqual(rc, 1)

    def test_position_end_appends_after_last_row(self):
        row = "| weekly-review-stock-2026-08-20.yaml | weekly-stocks-review | 2026-08-20 | portfolio-2026-08-20 |"
        code, out = run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/", "rows": [row],
                                     "position": "end"})
        self.assertEqual(code, 0, out)
        lines = self.index_text().split("\n")
        i = lines.index(row)
        self.assertTrue(lines[i - 1].startswith("| weekly-review-stock-2026-08-06.yaml"))
        self.assertFalse(lines[i + 1].startswith("|"))

    def test_position_auto_follows_dates(self):
        sec = {"index_path": self.index, "section": "### weekly-reviews/"}
        # одинаковые даты — направления нет — сверху
        r1 = "| weekly-review-stock-2026-08-20.yaml | x | 2026-08-20 | p |"
        run("add-rows", {**sec, "rows": [r1], "position": "auto"})
        lines = self.index_text().split("\n")
        self.assertTrue(lines[lines.index(r1) - 1].startswith("|---"))
        # теперь сверху 20, ниже 06 — даты убывают вниз — снова сверху
        r2 = "| weekly-review-stock-2026-08-25.yaml | x | 2026-08-25 | p |"
        run("add-rows", {**sec, "rows": [r2], "position": "auto"})
        lines = self.index_text().split("\n")
        self.assertTrue(lines[lines.index(r2) - 1].startswith("|---"))

    def test_position_auto_ascending_appends(self):
        sec = {"index_path": self.index, "section": "### weekly-reviews/"}
        r1 = "| weekly-review-stock-2026-08-20.yaml | x | 2026-08-20 | p |"
        run("add-rows", {**sec, "rows": [r1], "position": "end"})      # 06, 06, 20 — растут вниз
        r2 = "| weekly-review-stock-2026-08-25.yaml | x | 2026-08-25 | p |"
        code, out = run("add-rows", {**sec, "rows": [r2], "position": "auto"})
        self.assertEqual(out["position"], "auto")
        lines = self.index_text().split("\n")
        self.assertEqual(lines[lines.index(r2) - 1], r1)

    def test_position_invalid_errors(self):
        code, out = run("add-rows", {"index_path": self.index, "section": "### weekly-reviews/",
                                     "rows": ["| a | b |"], "position": "middle"})
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])

    def test_missing_file_errors(self):
        rc, out = run("add-rows", {"index_path": self.index + ".нет",
                                   "section": "### weekly-reviews/", "rows": [self.ROW]})
        self.assertEqual(rc, 1)
        self.assertIn("не найден", out["error"])


class TestAddMeta(_Base):
    def test_appended_to_metadata_section(self):
        rc, out = run("add-meta", {"index_path": self.index,
                                   "line": "2026-08-15 (weekly-review-stock — тест)"})
        self.assertTrue(out["appended"])
        txt = self.index_text()
        self.assertIn("- Обновлено: 2026-08-15 (weekly-review-stock — тест)", txt)
        self.assertGreater(txt.index("2026-08-15 (weekly"), txt.index("## Метаданные"))

    def test_prefix_not_duplicated(self):
        run("add-meta", {"index_path": self.index, "line": "- Обновлено: 2026-08-15 (x)"})
        self.assertNotIn("- Обновлено: - Обновлено:", self.index_text())

    def test_identical_entry_not_duplicated(self):
        payload = {"index_path": self.index, "line": "2026-08-15 (x)"}
        run("add-meta", payload)
        rc, out = run("add-meta", payload)
        self.assertFalse(out["appended"])
        self.assertEqual(self.index_text().count("2026-08-15 (x)"), 1)

    def test_dry_run_writes_nothing(self):
        rc, out = run("add-meta", {"index_path": self.index, "line": "2026-08-15 (x)",
                                   "dry_run": True})
        self.assertTrue(out["appended"])
        self.assertEqual(self.index_text(), INDEX_FIXTURE)


class TestSyncLog(_Base):
    def log_text(self):
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()

    def test_entry_appended_at_end(self):
        rc, out = run("sync-log", {"log_path": self.log,
                                   "entries": ["2026-08-15 | save-to-library | Workflow F | новое"]})
        self.assertEqual(out["appended"], 1)
        self.assertTrue(self.log_text().endswith("новое\n"))
        self.assertIn("старая запись", self.log_text())

    def test_multiple_entries(self):
        rc, out = run("sync-log", {"log_path": self.log, "entries": ["a | b", "c | d"]})
        self.assertEqual(out["appended"], 2)
        self.assertEqual(self.log_text().count("\n"), 3)

    def test_missing_trailing_newline_handled(self):
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write("без перевода строки")
        run("sync-log", {"log_path": self.log, "entries": ["новая"]})
        self.assertEqual(self.log_text(), "без перевода строки\nновая\n")

    def test_dry_run_writes_nothing(self):
        rc, out = run("sync-log", {"log_path": self.log, "entries": ["x"], "dry_run": True})
        self.assertTrue(out["ok"])
        self.assertEqual(self.log_text(), SYNC_FIXTURE)

    def test_empty_entries_rejected(self):
        rc, out = run("sync-log", {"log_path": self.log, "entries": []})
        self.assertEqual(rc, 1)


class TestCli(_Base):
    def test_bad_json_rejected(self):
        p = subprocess.run([sys.executable, SCRIPT, "add-meta"],
                           input="не json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("не разобран как JSON", p.stdout)

    def test_non_object_payload_rejected(self):
        p = subprocess.run([sys.executable, SCRIPT, "add-meta"],
                           input="[1,2]", capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_unknown_command_rejected(self):
        p = subprocess.run([sys.executable, SCRIPT, "нет-команды"],
                           input="{}", capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

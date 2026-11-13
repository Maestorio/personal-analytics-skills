#!/usr/bin/env python3
"""Тесты archive_snapshot.py (PDL-SNAPV): старая версия снапшота дня откладывается перед перезаписью.

Запуск: python3 skills/portfolio-data-loader/tests/test_archive_snapshot.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from archive_snapshot import archive  # noqa: E402


class TestArchiveSnapshot(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def _write(self, gen, day="2026-10-16"):
        with open(os.path.join(self.d, f"portfolio-{day}.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": gen, "holdings": []}, f)

    def test_nothing_to_archive(self):
        r = archive(self.d, "2026-10-16")
        self.assertFalse(r["archived"])

    def test_archives_by_generated_at(self):
        self._write("2026-10-16T00:45:47")
        r = archive(self.d, "2026-10-16")
        self.assertTrue(r["archived"])
        self.assertTrue(r["to"].endswith(".versions/portfolio-2026-10-16.20261016T0045.json"))
        self.assertTrue(os.path.exists(os.path.join(self.d, "portfolio-2026-10-16.json")))  # оригинал на месте

    def test_second_call_same_version_skipped_new_version_kept(self):
        self._write("2026-10-16T00:45:47")
        archive(self.d, "2026-10-16")
        self.assertFalse(archive(self.d, "2026-10-16")["archived"])
        self._write("2026-10-16T18:21:16")
        self.assertTrue(archive(self.d, "2026-10-16")["archived"])
        self.assertEqual(len(os.listdir(os.path.join(self.d, ".versions"))), 2)

    def test_versions_dir_not_matched_by_top_level_glob(self):
        import glob
        self._write("2026-10-16T00:45:47")
        archive(self.d, "2026-10-16")
        self.assertEqual([os.path.basename(p) for p in glob.glob(os.path.join(self.d, "portfolio-*.json"))],
                         ["portfolio-2026-10-16.json"])

    def test_bad_date(self):
        self.assertFalse(archive(self.d, "16.10.2026")["archived"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

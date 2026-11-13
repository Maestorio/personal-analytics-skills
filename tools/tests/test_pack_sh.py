#!/usr/bin/env python3
"""pack.sh: «изменившийся скилл» решается по содержимому пакета, а не по времени файлов.

Держит: время файлов — только фильтр; git checkout/pull, переписавшие файлы без смены содержимого,
пакет не меняют (байты прежние, ему обновляется только время); правка файла скилла, канона
shared_refs или общего модуля по импорту — пакет пересобирается и называет расхождение; `--check`
ничего не пишет; битый description — код 1, пакета нет; явный вызов без изменений пакет не трогает.
Стенд — временная копия pack.sh с мини-деревом skills/ + _shared-references/.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/tests/test_pack_sh.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


class PackStand(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        shutil.copy(REPO / "pack.sh", self.root / "pack.sh")
        sh = self.root / "_shared-references"
        sh.mkdir()
        (sh / "canon.md").write_text("канон\n", encoding="utf-8")
        (sh / "helper.py").write_text("X = 1\n", encoding="utf-8")
        for name in ("alpha", "beta"):
            d = self.root / "skills" / name
            (d / "scripts").mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: тестовый скилл {name}\nshared_refs: [canon]\n---\nтекст\n",
                encoding="utf-8")
        (self.root / "skills/alpha/scripts/run.py").write_text("import helper\n", encoding="utf-8")
        self.env = dict(os.environ, PACK_PYTHON=sys.executable)
        r = self.pack()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.out = self.root / "outputs"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def pack(self, *args):
        return subprocess.run(["zsh", str(self.root / "pack.sh"), *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def later(self, *paths):
        """Файлы новее пакетов — как после git checkout, переписавшего их: файлам время «сейчас»,
        пакетам — на 10 с раньше (время из будущего у файлов git не ставит)."""
        now, past = time.time(), time.time() - 10
        for p in paths:
            os.utime(self.root / p, (now, now))
        for pkg in self.out.glob("*.skill") if hasattr(self, "out") else ():
            os.utime(pkg, (past, past))

    def test_first_pack_bundles_canon_and_imports(self):
        with zipfile.ZipFile(self.out / "alpha.skill") as z:
            names = set(z.namelist())
        self.assertIn("references/canon.md", names)
        self.assertIn("scripts/helper.py", names)

    def test_rewrite_same_content_keeps_package(self):
        before = {n: md5(self.out / f"{n}.skill") for n in ("alpha", "beta")}
        self.later("skills/alpha/SKILL.md", "_shared-references/canon.md")
        r = self.pack("--check")
        self.assertIn("упаковывать нечего", r.stdout)
        self.assertNotIn("↺", r.stdout)
        r = self.pack()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("✓ /", r.stdout)
        self.assertIn("пакет оставлен прежним", r.stdout)
        self.assertEqual(before, {n: md5(self.out / f"{n}.skill") for n in ("alpha", "beta")})
        # пакет освежён по времени — следующий запуск отсеивает его фильтром, без сборки
        self.assertNotIn("оставлен", self.pack().stdout)

    def test_real_skill_edit_repacks(self):
        p = self.root / "skills/beta/SKILL.md"
        p.write_text(p.read_text(encoding="utf-8") + "ещё\n", encoding="utf-8")
        self.later("skills/beta/SKILL.md")
        a_before = md5(self.out / "alpha.skill")
        r = self.pack("--check")
        self.assertIn("↺ beta: ≠ SKILL.md", r.stdout)
        self.assertIn("изменились: beta", r.stdout)
        r = self.pack()
        self.assertIn("beta.skill (≠ SKILL.md)", r.stdout)
        with zipfile.ZipFile(self.out / "beta.skill") as z:
            self.assertTrue(z.read("SKILL.md").decode().endswith("ещё\n"))
        self.assertEqual(a_before, md5(self.out / "alpha.skill"))

    def test_canon_and_import_edits_repack_consumers(self):
        (self.root / "_shared-references/helper.py").write_text("X = 2\n", encoding="utf-8")
        self.later("_shared-references/helper.py")
        r = self.pack()
        self.assertIn("alpha.skill (≠ scripts/helper.py)", r.stdout)
        self.assertNotIn("beta.skill", r.stdout)
        (self.root / "_shared-references/canon.md").write_text("новый канон\n", encoding="utf-8")
        self.later("_shared-references/canon.md")
        r = self.pack()
        self.assertIn("alpha.skill (≠ references/canon.md)", r.stdout)
        self.assertIn("beta.skill (≠ references/canon.md)", r.stdout)

    def test_new_and_removed_files(self):
        (self.root / "skills/beta/references").mkdir(exist_ok=True)
        (self.root / "skills/beta/references/own.md").write_text("своё\n", encoding="utf-8")
        self.later("skills/beta/references/own.md")
        self.assertIn("(+ references/own.md)", self.pack().stdout)
        (self.root / "skills/beta/references/own.md").unlink()
        self.later("skills/beta/SKILL.md")
        self.assertIn("(- references/own.md)", self.pack().stdout)

    def test_check_writes_nothing(self):
        p = self.root / "skills/beta/SKILL.md"
        p.write_text(p.read_text(encoding="utf-8") + "ещё\n", encoding="utf-8")
        self.later("skills/beta/SKILL.md")
        before = md5(self.out / "beta.skill")
        mtime = (self.out / "beta.skill").stat().st_mtime
        self.pack("--check")
        self.assertEqual(before, md5(self.out / "beta.skill"))
        self.assertEqual(mtime, (self.out / "beta.skill").stat().st_mtime)

    def test_tests_dir_ignored(self):
        (self.root / "skills/beta/tests").mkdir()
        (self.root / "skills/beta/tests/test_x.py").write_text("pass\n", encoding="utf-8")
        before = md5(self.out / "beta.skill")
        self.pack()
        self.assertEqual(before, md5(self.out / "beta.skill"))

    def test_bad_description_fails_without_package(self):
        d = self.root / "skills/gamma"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: gamma\ndescription: тема <x>\n---\n", encoding="utf-8")
        r = self.pack()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("угловые скобки", r.stdout)
        self.assertFalse((self.out / "gamma.skill").exists())

    def test_explicit_call_unchanged_keeps_bytes(self):
        before = md5(self.out / "alpha.skill")
        r = self.pack("alpha")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("пакет оставлен прежним: alpha", r.stdout)
        self.assertEqual(before, md5(self.out / "alpha.skill"))

    def test_broken_old_package_repacks(self):
        (self.out / "beta.skill").write_bytes(b"not a zip")
        self.later("skills/beta/SKILL.md")
        r = self.pack()
        self.assertIn("beta.skill (прежний пакет не читается как zip)", r.stdout)
        self.assertTrue(zipfile.is_zipfile(self.out / "beta.skill"))


if __name__ == "__main__":
    res = unittest.main(exit=False, verbosity=1).result
    n = res.testsRun
    ok = n - len(res.failures) - len(res.errors)
    print(f"Итого: {ok} из {n}")
    sys.exit(0 if ok == n else 1)

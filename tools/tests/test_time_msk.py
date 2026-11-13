#!/usr/bin/env python3
"""Время записываемых полей — МСК с поясом (шаг 3 цикла машиночитаемости, schema.md §1 п.4).

Держит: помощник `_shared-references/time_msk.py` (формат, пересчёт из UTC/`Z`, MOEX-время без пояса = МСК);
нормализацию `current_price_ts` в одном месте сборки (`assemble_snapshot._price_ts`: «2026-10-30 15:05:29» →
«2026-10-30T15:05:29+03:00»); единственную функцию времени в `jobs.py` / `pf_build.py`; сторож: в записываемых
полях server.py, notifier.py, jobs.py, pf_build.py, assemble_snapshot.py, security_types.py, build_snapshot.py нет
наивного `datetime.now()`/`.isoformat(timespec=…)` и UTC с `Z`; `pack.sh` кладёт `time_msk.py` рядом со скриптом;
сортировка отчётов монитора переживает смесь `Z` и `+03:00`; валидаторы обзора недели не придираются к новым ключам
`recorded_at`, `recorded_at_estimated`.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/tests/test_time_msk.py
"""
import re
import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))
sys.path.insert(0, str(REPO / "skills/save-to-library/scripts"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))

import time_msk  # noqa: E402

MSK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$")


class Helper(unittest.TestCase):
    def test_now_and_day_start(self):
        self.assertRegex(time_msk.now_iso(), MSK_RE)
        self.assertEqual(time_msk.day_start_iso("2026-10-31"), "2026-10-31T00:00:00+03:00")
        self.assertEqual(time_msk.day_start_iso(date(2026, 1, 2)), "2026-01-02T00:00:00+03:00")
        self.assertEqual(time_msk.day_end_iso("2026-10-31"), "2026-10-31T23:59:59+03:00")
        self.assertEqual(time_msk.today_iso(), time_msk.now_iso()[:10])

    def test_to_msk_recounts_not_relabels(self):
        self.assertEqual(time_msk.to_msk_iso("2026-10-30T21:40:00Z"), "2026-10-31T00:40:00+03:00")
        self.assertEqual(time_msk.to_msk_iso("2026-10-31T10:00:05"), "2026-10-31T13:00:05+03:00")       # без пояса = UTC
        self.assertEqual(time_msk.to_msk_iso("2026-10-31T10:00:05+00:00"), "2026-10-31T13:00:05+03:00")
        self.assertEqual(time_msk.to_msk_iso("2026-10-31T10:00:05+05:00"), "2026-10-31T08:00:05+03:00")
        self.assertEqual(time_msk.to_msk_iso("2026-10-31T12:00:00+03:00"), "2026-10-31T12:00:00+03:00")
        self.assertEqual(time_msk.to_msk_iso("2026-10-30 15:05:29", naive_is_msk=True), "2026-10-30T15:05:29+03:00")

    def test_is_msk_iso(self):
        self.assertTrue(time_msk.is_msk_iso("2026-10-31T12:00:00+03:00"))
        for bad in ("2026-10-31T12:00:00Z", "2026-10-31T12:00:00", "2026-10-31", "2026-10-31 12:00:00+03:00", None):
            self.assertFalse(time_msk.is_msk_iso(bad), bad)


class Readers(unittest.TestCase):
    def test_current_price_ts_normalised_in_one_place(self):
        import assemble_snapshot as a
        self.assertEqual(a._price_ts({"timestamp": "2026-10-30 15:05:29"}), "2026-10-30T15:05:29+03:00")
        self.assertIsNone(a._price_ts({}))
        self.assertIsNone(a._price_ts({"timestamp": None}))
        src = (REPO / "skills/portfolio-data-loader/scripts/assemble_snapshot.py").read_text(encoding="utf-8")
        self.assertNotIn('q.get("timestamp")', src.replace('v = q.get("timestamp")', ""))   # сырых чтений не осталось

    def test_jobs_and_pf_build_have_one_time_function(self):
        import jobs
        import pf_build
        self.assertRegex(jobs.now_iso(), MSK_RE)
        self.assertRegex(pf_build._iso(), MSK_RE)
        from datetime import datetime, timezone
        utc = datetime(2026, 10, 30, 21, 40, tzinfo=timezone.utc)
        self.assertEqual(jobs.now_iso(utc), "2026-10-31T00:40:00+03:00")
        self.assertEqual(pf_build._iso(utc), "2026-10-31T00:40:00+03:00")

    def test_monitor_sort_survives_mixed_formats(self):
        import notifier
        z = notifier._gen_key({"generated_at": "2026-10-25T21:40:00Z"})
        msk = notifier._gen_key({"generated_at": "2026-10-26T00:50:00+03:00"})
        self.assertLess(z, msk)                       # 00:40 МСК раньше 00:50 МСК, хотя строка с Z «больше» как текст
        self.assertEqual(notifier._gen_key({}), 0.0)

    def test_weekly_validators_accept_new_keys(self):
        import assemble_artifact as aa
        base = {"schema_version": 2, "type": "weekly-stocks-review", "review_date": "2026-10-31", "snapshot_id": "s"}
        extra = {**base, "recorded_at": "2026-10-31T12:00:00+03:00", "recorded_at_estimated": True}
        for fn in (aa.validate_weekly_review_stock_detailed, ):
            self.assertEqual(fn(base), fn(extra))
        bbase = {**base, "type": "weekly-bonds-review"}
        self.assertEqual(aa.validate_weekly_review_bond_detailed(bbase),
                         aa.validate_weekly_review_bond_detailed({**bbase, **{k: extra[k] for k in ("recorded_at", "recorded_at_estimated")}}))


class Guards(unittest.TestCase):
    FILES = {
        "tools/hosting/api/server.py": [r"timespec=\"seconds\"", r"%SZ", r"timezone\.utc\)\.isoformat"],
        "tools/hosting/notify/notifier.py": [r"\.isoformat\(timespec=", r"%SZ"],
        "tools/hosting/notify/jobs.py": [r"\.isoformat\(timespec="],
        "tools/hosting/notify/pf_build.py": [r"\.isoformat\(timespec=", r"datetime\.now\(\)"],
        "skills/portfolio-data-loader/scripts/assemble_snapshot.py": [r"datetime\.now\(\)\.strftime\(\"%Y-%m-%dT"],
        "skills/portfolio-data-loader/scripts/security_types.py": [r"datetime\.now\(\)"],
        "skills/portfolio-data-loader/scripts/build_snapshot.py": [r"\"created_at\": dt\.datetime\.now"],
    }

    def test_no_naive_or_utc_z_in_written_fields(self):
        for rel, pats in self.FILES.items():
            src = (REPO / rel).read_text(encoding="utf-8")
            for p in pats:
                self.assertIsNone(re.search(p, src), f"{rel}: {p}")

    def test_pack_sh_bundles_time_msk(self):
        sh = (REPO / "pack.sh").read_text(encoding="utf-8")
        # обобщённый перенос: `import <имя>` с файлом _shared-references/<имя>.py — модуль едет в scripts/
        self.assertIn("(import|from)[[:space:]]+", sh)
        self.assertIn('echo "$SHARED_DIR/$name.py"', sh)
        self.assertIn('cp "$src" "$SCRIPTS_DIR/${src:t}"', sh)

    def test_deploy_ships_time_msk_to_container_layout(self):
        self.assertIn("time_msk.py", (REPO / "tools/deploy.zsh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=1)

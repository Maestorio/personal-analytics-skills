#!/usr/bin/env python3
"""Тесты migrate_v1_to_v2.py (V2-CUTOVER, wrap-as-single-horizon).

Запуск из корня репозитория:
    python3 skills/portfolio-scenario-stress/tests/test_migrate_v1_to_v2.py
Требует PyYAML (как и сам мигратор).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "skills" / "portfolio-scenario-stress" / "scripts"))

import yaml  # noqa: E402

from migrate_v1_to_v2 import (  # noqa: E402
    MigrationRefused,
    add_months_iso,
    migrate_file,
    migrate_stress_doc,
    migrate_weekly_text,
    months_between,
)

WEEKLY_V1 = """\
schema_version: 1
type: weekly-stocks-review
review_date: '2026-05-28'
snapshot_id: portfolio-2026-05-24.json
horizon_months: 20
# комментарий, который обязан пережить миграцию
horizon_end: "2027-12-31"
per_stock:
  SBER:
    sector: Финансовый
    advisor_verdict: HOLD
    catalyst:
      - id: div_2026
        p: 0.7
        in_horizon: true
        date_window: '2026-06-01..2026-07-15'
      - id: buyback_2027
        p: 0.3
        in_horizon: false
"""

STRESS_V1 = {
    "schema_version": 1,
    "type": "portfolio-stress-test",
    "date": "2026-05-11",
    "horizon": "2027-12-31",
    "scenarios": {
        "A": {
            "name": "Эскалация",
            "p": 0.25,
            "probability": 0.25,
            "factors": {"brent": -20.0, "usdrub": 15.0},
            "portfolio_level": {"delta_pct": -8.1},
        },
    },
    "per_position": {
        "SBER": {
            "weight_pct": 10.0,
            "factor_betas": {"brent": 0.1},
            "delta_pct_by_scenario": {"A": -5.0},
            "expected_pct_pweighted": -1.25,
            "tail_var_pct": -5.0,
            "tail_var_scenario_id": "A",
        },
    },
}


class TestWeeklyText(unittest.TestCase):
    def test_basic_migration(self):
        text, report = migrate_weekly_text(WEEKLY_V1)
        doc = yaml.safe_load(text)
        self.assertEqual(doc["schema_version"], 2)
        self.assertEqual(doc["horizons"], [20])
        self.assertEqual(doc["primary_horizon"], 20)
        self.assertEqual(doc["horizon_ends"], {"h20": "2027-12-31"})
        self.assertNotIn("horizon_months", doc)
        self.assertNotIn("horizon_end", doc)
        self.assertEqual(report["wrapped_horizon"], 20)
        self.assertEqual(report["derived_fields"], [])

    def test_comments_preserved(self):
        text, _ = migrate_weekly_text(WEEKLY_V1)
        self.assertIn("# комментарий, который обязан пережить миграцию", text)

    def test_in_horizon_lines_removed_data_intact(self):
        text, report = migrate_weekly_text(WEEKLY_V1)
        self.assertNotIn("in_horizon", text)
        self.assertEqual(report["in_horizon_removed"], 2)
        doc = yaml.safe_load(text)
        cats = doc["per_stock"]["SBER"]["catalyst"]
        self.assertEqual([c["id"] for c in cats], ["div_2026", "buyback_2027"])
        self.assertEqual(cats[0]["date_window"], "2026-06-01..2026-07-15")

    def test_derived_horizon_end(self):
        """Ранний формат: только horizon_months → дата выводится review_date + N."""
        v1 = WEEKLY_V1.replace('horizon_end: "2027-12-31"\n', "")
        text, report = migrate_weekly_text(v1)
        doc = yaml.safe_load(text)
        self.assertEqual(report["derived_fields"], ["horizon_end"])
        self.assertEqual(doc["horizon_ends"], {"h20": "2028-01-28"})  # 2026-05-28 + 20 мес

    def test_derived_horizon_months_from_date(self):
        """Ранний bond-формат: только horizon-дата → N из review_date."""
        v1 = WEEKLY_V1.replace("horizon_months: 20\n", "").replace(
            'horizon_end: "2027-12-31"', "horizon: '2027-12-31'"
        ).replace("weekly-stocks-review", "weekly-bonds-review")
        text, report = migrate_weekly_text(v1)
        doc = yaml.safe_load(text)
        self.assertEqual(report["derived_fields"], ["horizon_months"])
        self.assertEqual(doc["horizons"], [19])  # 2026-05-28 → 2027-12-31 ≈ 19.1 мес
        self.assertNotIn("horizon", doc)

    def test_v2_refused(self):
        with self.assertRaises(MigrationRefused):
            migrate_weekly_text(WEEKLY_V1.replace("schema_version: 1", "schema_version: 2"))

    def test_no_horizon_at_all_refused(self):
        v1 = WEEKLY_V1.replace("horizon_months: 20\n", "").replace(
            'horizon_end: "2027-12-31"\n', ""
        )
        with self.assertRaises(MigrationRefused):
            migrate_weekly_text(v1)


class TestStressDoc(unittest.TestCase):
    def test_basic_migration_faithful(self):
        import copy
        doc, report = migrate_stress_doc(copy.deepcopy(STRESS_V1))
        self.assertEqual(doc["schema_version"], 2)
        self.assertEqual(doc["horizons"], [20])  # 2026-05-11 → 2027-12-31 ≈ 19.7 → 20
        self.assertEqual(doc["horizon_ends"], {"h20": "2027-12-31"})
        self.assertNotIn("horizon", doc)
        sc = doc["scenarios"]["A"]
        self.assertNotIn("factors", sc)
        self.assertEqual(sc["factors_by_horizon"]["h20"], {"brent": -20.0, "usdrub": 15.0})
        self.assertEqual(sc["portfolio_level_by_horizon"]["h20"], {"delta_pct": -8.1})
        pp = doc["per_position"]["SBER"]
        self.assertNotIn("delta_pct_by_scenario", pp)
        self.assertEqual(pp["by_horizon"]["h20"]["delta_pct_by_scenario"], {"A": -5.0})
        self.assertEqual(pp["by_horizon"]["h20"]["expected_pct_pweighted"], -1.25)
        self.assertEqual(pp["factor_betas"], {"brent": 0.1})  # беты остаются плоскими
        self.assertEqual(report["scenarios_wrapped"], 1)
        self.assertEqual(report["positions_wrapped"], 1)

    def test_scenario_stress_type_normalized(self):
        import copy
        v1 = copy.deepcopy(STRESS_V1)
        v1["type"] = "portfolio-scenario-stress"
        doc, _ = migrate_stress_doc(v1)
        self.assertEqual(doc["type"], "portfolio-stress-test")

    def test_no_horizon_refused(self):
        import copy
        v1 = copy.deepcopy(STRESS_V1)
        del v1["horizon"]
        with self.assertRaises(MigrationRefused):
            migrate_stress_doc(v1)

    def test_v2_refused(self):
        import copy
        v1 = copy.deepcopy(STRESS_V1)
        v1["schema_version"] = 2
        with self.assertRaises(MigrationRefused):
            migrate_stress_doc(v1)


class TestHelpers(unittest.TestCase):
    def test_months_between(self):
        self.assertEqual(months_between("2026-05-11", "2027-12-31"), 20)
        self.assertEqual(months_between("2026-05-29", "2026-12-31"), 7)
        self.assertEqual(months_between("2026-05-29", "2027-12-31"), 19)
        self.assertIsNone(months_between("2027-01-01", "2026-01-01"))
        self.assertIsNone(months_between("мусор", "2026-01-01"))

    def test_add_months_iso(self):
        self.assertEqual(add_months_iso("2026-05-28", 20), "2028-01-28")
        self.assertEqual(add_months_iso("2026-01-31", 1), "2026-02-28")  # клампинг к длине месяца
        self.assertEqual(add_months_iso("2028-01-31", 1), "2028-02-29")  # високосный 2028
        self.assertIsNone(add_months_iso("мусор", 6))


class TestMigrateFile(unittest.TestCase):
    def test_weekly_roundtrip_file(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "weekly-review-stock-2026-05-28.yaml"
            dst = Path(td) / "out.yaml"
            src.write_text(WEEKLY_V1, encoding="utf-8")
            report = migrate_file(str(src), str(dst))
            self.assertEqual(report["kind"], "weekly")
            self.assertEqual(yaml.safe_load(dst.read_text())["schema_version"], 2)

    def test_stress_leading_comments_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "stress-x.yaml"
            dst = Path(td) / "out.yaml"
            src.write_text("# шапка файла\n# вторая строка\n" + yaml.safe_dump(STRESS_V1, sort_keys=False, allow_unicode=True), encoding="utf-8")
            migrate_file(str(src), str(dst))
            text = dst.read_text()
            self.assertTrue(text.startswith("# шапка файла\n# вторая строка\n"))
            self.assertEqual(yaml.safe_load(text)["schema_version"], 2)

    def test_multidoc_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "multi.yaml"
            src.write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
            with self.assertRaises(MigrationRefused):
                migrate_file(str(src), str(Path(td) / "out.yaml"))

    def test_unknown_type_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.yaml"
            src.write_text("schema_version: 1\ntype: something-else\n", encoding="utf-8")
            with self.assertRaises(MigrationRefused):
                migrate_file(str(src), str(Path(td) / "out.yaml"))


if __name__ == "__main__":
    unittest.main(verbosity=1)

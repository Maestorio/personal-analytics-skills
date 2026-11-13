#!/usr/bin/env python3
"""validate-macro-scenarios (Workflow J): проверка сетки дат файла макро-цепочки при сохранении."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import assemble_artifact as aa  # noqa: E402

SCRIPT = HERE.parent / "scripts/assemble_artifact.py"


def _g(v):
    return {"2026-12-31": {"value": v}, "2027-12-31": {"value": v}}


def good():
    return {
        "baseline_spot": {"brent_price": 100.0, "usdrub_rate": 80.0, "cnyrub_rate": 12.0, "cbr_rate": 14.0,
                          "xauusd_price": 4000},
        "scenario_matrix": {"scenarios": [{"id": "A"}, {"id": "B"}]},
        "factors": {
            "brent_price": {"by_scenario": {"A": _g(90), "B": _g(95)}},
            "usdrub_rate": {"by_scenario": {"A": _g(82), "B": _g(85)}},
            "cnyrub_rate": {"by_scenario": {"A": _g(12.1), "B": _g(12.5)}},
            "cbr_rate": {"by_scenario": {"A": _g(15), "B": _g(13)}},
            "xauusd_price": {"level_all_scenarios": _g(4500)},
        },
    }


class T(unittest.TestCase):
    def test_good(self):
        r = aa.validate_macro_scenarios(good())
        self.assertTrue(r["valid"])
        self.assertEqual(r["issues"], [])

    def test_blocking(self):
        m = good(); del m["baseline_spot"]["brent_price"]
        r = aa.validate_macro_scenarios(m)
        self.assertFalse(r["valid"])
        self.assertTrue(all(i["severity"] == "blocking" for i in r["issues"]))

    def test_warning_only(self):
        m = good(); m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = -2.0
        r = aa.validate_macro_scenarios(m)
        self.assertTrue(r["valid"])
        self.assertEqual([i["severity"] for i in r["issues"]], ["warning"])

    def test_scenario_from_matrix(self):
        m = good(); m["scenario_matrix"]["scenarios"].append({"id": "C"})
        r = aa.validate_macro_scenarios(m)
        self.assertFalse(r["valid"])
        self.assertTrue(any("сценарий C" in i["actual"] for i in r["issues"]))

    def test_sets_differ_without_matrix(self):
        m = good(); del m["scenario_matrix"]; del m["factors"]["cbr_rate"]["by_scenario"]["B"]
        r = aa.validate_macro_scenarios(m)
        self.assertFalse(r["valid"])
        self.assertTrue(any("набор сценариев" in i["actual"] for i in r["issues"]))

    def test_cli_command(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "validate-macro-scenarios"], input=json.dumps(good()),
                           capture_output=True, text=True)
        self.assertEqual(json.loads(p.stdout)["valid"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

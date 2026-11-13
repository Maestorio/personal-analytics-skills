#!/usr/bin/env python3
"""Тесты pre-save гейта FCA (FCA-2/FCA-3): fca_output_checks + drift-контракт.

Запуск из корня репозитория:
    python3 skills/forecast-confidence-applier/tests/test_validate_fca_output.py

Drift-контракт: вердикты канона `_shared-references/fca_output_checks.py`
сверяются с `validate_forecast_events({"_strict": true})` save-to-library на
общих фикстурах — оба слоя обязаны сходиться в «есть blocking / нет blocking»
по формам FCA-2. Разъехались — тест падает, а не molча живут два валидатора.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(REPO / "skills" / "save-to-library"))

from fca_output_checks import check_fca_output  # noqa: E402
from scripts.assemble_artifact import validate_forecast_events  # noqa: E402

CLI = REPO / "skills" / "forecast-confidence-applier" / "scripts" / "validate_fca_output.py"


def ok_conditional() -> dict:
    """Каноничный валидный Type 2 (зеркало _ok_conditional save-to-library)."""
    return {
        "forecast": {
            "central_estimate": "Test: 11.5% к 2026-12-31 (weighted FCA)",
        },
        "conditional_on_scenarios": {
            "source_matrix": "scenarios/scenario-test-2026-05-04.yaml",
            "scenario_id_format": "short",
            "unit": "%",
            "by_scenario": {
                "A": {
                    "values": {"2026-12-31": {"central": 10.0, "range": [9.0, 11.0]}},
                    "provenance": "derived_from_marginal",
                    "sources_used": [],
                    "coverage_quality": "DERIVED",
                },
                "B": {
                    "values": {"2026-12-31": {"central": 12.0, "range": [11.0, 13.0]}},
                    "provenance": "native_fca",
                    "sources_used": ["src1", "src2"],
                    "coverage_quality": "MEDIUM",
                },
                "C": {
                    "values": {"2026-12-31": {"central": 11.0, "range": [10.0, 12.0]}},
                    "provenance": "single_native",
                    "sources_used": ["src3"],
                    "coverage_quality": "LOW",
                },
                "D": {
                    "values": {"2026-12-31": {"central": 13.0, "range": [12.0, 14.0]}},
                    "provenance": "native_fca",
                    "sources_used": ["src1", "src2", "src3", "src4", "src5"],
                    "coverage_quality": "HIGH",
                },
            },
            "marginal": {
                "method": "linear",
                "modal_scenario_id": "none",
                "values": {"2026-12-31": {"central": 11.5, "range": [9.0, 14.0]}},
                "aggregation_formula": "weighted_mean",
            },
        },
        "coherence_diagnostic": {
            "layer1_marginal": 11.7,
            "layer2_marginal": 11.5,
            "divergence_pct": 1.7,
            "severity": "LOW",
            "warning": None,
        },
    }


def _mut(path_mutator) -> dict:
    d = ok_conditional()
    path_mutator(d)
    return d


class TestCheckFcaOutput(unittest.TestCase):
    def test_clean_spec_form_valid(self):
        r = check_fca_output(ok_conditional())
        self.assertTrue(r["valid"], r["issues"])

    def test_isolated_passes_silently(self):
        r = check_fca_output({"isolated": True, "isolated_reason": "binary event"})
        self.assertTrue(r["valid"])

    def test_horizon_yyyy_keys_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["A"].update(
            {"horizon_2026": {"central_estimate": 10.0}}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertIn("nonstandard_structure", {i["category"] for i in r["issues"]})

    def test_central_estimate_p10_p90_inside_values_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]["values"].update(
            {"2027-12-31": {"central_estimate": 12.5, "p10": 11.0, "p90": 14.0}}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertIn("nonstandard_field_names", {i["category"] for i in r["issues"]})

    def test_unit_inside_horizon_value_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]["values"]
                 ["2026-12-31"].update({"unit": "%"}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any(i["field"].endswith(".unit") for i in r["issues"]))

    def test_sources_used_as_int_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"].update(
            {"sources_used": 3}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any(
            i["category"] in {"nonstandard_field_names", "cross_validation"}
            and i["field"].endswith("B.sources_used")
            for i in r["issues"]
        ))

    def test_coherence_inside_conditional_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"].update(
            {"coherence_diagnostic": d.pop("coherence_diagnostic")}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertIn("coherence_misplaced", {i["category"] for i in r["issues"]})

    def test_legacy_provenance_flagged_with_mapping(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"].update(
            {"provenance": "structural_derivation"}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        prov = [i for i in r["issues"] if i["field"].endswith("C.provenance")]
        self.assertEqual(len(prov), 1)
        self.assertIn("derived_from_upstream", prov[0]["actual"])

    def test_derived_from_upstream_requires_upstream_used(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"].update(
            {"provenance": "derived_from_upstream", "sources_used": []}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertIn("cross_validation", {i["category"] for i in r["issues"]})

    def test_derived_from_upstream_with_upstream_used_clean(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"].update({
            "provenance": "derived_from_upstream",
            "sources_used": [],
            "upstream_used": [
                {"factor": "brent", "value": 62, "unit": "USD/bbl",
                 "source_file": "forecasts/brent-oil-price-2026-05-11.yaml"},
            ],
        }))
        r = check_fca_output(d)
        self.assertTrue(r["valid"], r["issues"])

    def test_upstream_used_bad_shapes_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"].update({
            "provenance": "derived_from_upstream",
            "upstream_used": [{"factor": "", "value": "62"}],
        }))
        r = check_fca_output(d)
        fields = {i["field"] for i in r["issues"]}
        self.assertTrue(any(f.endswith("[0].factor") for f in fields), fields)
        self.assertTrue(any(f.endswith("[0].value") for f in fields), fields)

    def test_native_fca_empty_sources_cross_flagged(self):
        d = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"].update(
            {"sources_used": []}))
        r = check_fca_output(d)
        self.assertFalse(r["valid"])
        self.assertIn("cross_validation", {i["category"] for i in r["issues"]})

    def test_non_dict_input(self):
        self.assertFalse(check_fca_output([1, 2])["valid"])


class TestDriftContract(unittest.TestCase):
    """Оба валидатора обязаны сходиться в blocking-вердикте на общих фикстурах."""

    def _strict_blocking(self, doc: dict) -> bool:
        payload = copy.deepcopy(doc)
        payload["_strict"] = True
        r = validate_forecast_events(payload)
        return any(i["severity"] == "blocking" for i in r["issues"])

    def _fca_blocking(self, doc: dict) -> bool:
        return not check_fca_output(doc)["valid"]

    def test_agreement_on_shared_fixtures(self):
        fixtures = {
            "clean": ok_conditional(),
            "horizon_keys": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["A"]
                                 .update({"horizon_2026": {"central_estimate": 10.0}})),
            "values_nonspec": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]
                                   ["values"].update({"2027-12-31": {"central_estimate": 1,
                                                                     "p10": 0, "p90": 2}})),
            "sources_int": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]
                                .update({"sources_used": 3})),
            "coherence_misplaced": _mut(lambda d: d["conditional_on_scenarios"].update(
                {"coherence_diagnostic": d.pop("coherence_diagnostic")})),
            "legacy_provenance": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"]
                                      .update({"provenance": "source_native"})),
            "upstream_missing": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"]
                                     .update({"provenance": "derived_from_upstream"})),
            "upstream_ok": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["C"]
                                .update({"provenance": "derived_from_upstream",
                                         "sources_used": [],
                                         "upstream_used": [{"factor": "brent", "value": 62}]})),
            # аудит 2026-08-03: две формы, на которых валидаторы расходились
            "sources_bool_derived": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["A"]
                                         .update({"sources_used": True})),
            "unit_in_value": _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]
                                  ["values"]["2026-12-31"].update({"unit": "%"})),
        }
        for name, doc in fixtures.items():
            with self.subTest(fixture=name):
                self.assertEqual(
                    self._fca_blocking(doc), self._strict_blocking(doc),
                    f"drift: fca={self._fca_blocking(doc)} strict={self._strict_blocking(doc)}",
                )


class TestCli(unittest.TestCase):
    def test_cli_clean_exit_0(self):
        p = subprocess.run(
            [sys.executable, str(CLI)],
            input=json.dumps(ok_conditional()),
            capture_output=True, text=True,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(json.loads(p.stdout)["valid"])

    def test_cli_broken_exit_1(self):
        doc = _mut(lambda d: d["conditional_on_scenarios"]["by_scenario"]["B"]
                   .update({"sources_used": 3}))
        p = subprocess.run(
            [sys.executable, str(CLI)],
            input=json.dumps(doc),
            capture_output=True, text=True,
        )
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["valid"])

    def test_cli_bad_json_exit_1(self):
        p = subprocess.run(
            [sys.executable, str(CLI)],
            input="{not json",
            capture_output=True, text=True,
        )
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)

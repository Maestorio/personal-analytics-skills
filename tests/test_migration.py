#!/usr/bin/env python3
"""
Тесты для scripts/migrate_to_conditional.py (Phase 3).

Запуск:
    pytest tests/test_migration.py -v
    # или
    python3 tests/test_migration.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    import pytest as _pytest
    _PYTEST_AVAILABLE = True
except ImportError:
    _pytest = None
    _PYTEST_AVAILABLE = False

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from migrate_to_conditional import (
    MigrationResult,
    _extract_from_alternatives,
    _extract_from_markdown,
    _extract_from_scenario_rates,
    _extract_layer1_value,
    _normalize_scenario_id,
    _parse_scenario_value,
    _repair_encoding,
    migrate_file,
    migrate_forecast,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO_EQ = str(FIXTURES / "scenario-equal-weights.yaml")

RU_RATES_YAML = FIXTURES / "ru-rates-2026-2027-2026-05-04.yaml"
CNY_RUB_YAML = FIXTURES / "cny-rub-dec2026-dec2027-2026-05-04.yaml"
RU_CPI_YAML = FIXTURES / "ru-cpi-2026-2027-2026-05-04.yaml"
RU_CPI_MD = FIXTURES / "ru-cpi-2026-2027-2026-05-04.md"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_normalize_scenario_id_sc_prefix():
    assert _normalize_scenario_id("Sc-A") == "A"
    assert _normalize_scenario_id("Sc-B") == "B"
    assert _normalize_scenario_id("Sc-D") == "D"


def test_normalize_scenario_id_bare():
    assert _normalize_scenario_id("A") == "A"
    assert _normalize_scenario_id("D") == "D"


def test_parse_scenario_value_percent():
    c, r, u = _parse_scenario_value("10.5%")
    assert abs(c - 10.5) < 1e-6
    assert r is None
    assert u == "%"


def test_parse_scenario_value_range_unicode_dash():
    c, r, u = _parse_scenario_value("10.8–12.6")
    assert abs(c - 11.7) < 1e-6
    assert r == [10.8, 12.6]
    assert u is None


def test_parse_scenario_value_bold_markdown():
    # EC3: "**4.4%**" strips bold markers
    c, r, u = _parse_scenario_value("**4.4%**")
    assert abs(c - 4.4) < 1e-6
    assert u == "%"


def test_parse_scenario_value_range_percent():
    c, r, u = _parse_scenario_value("12.5–15.1")
    assert abs(c - 13.8) < 1e-6
    assert r == [12.5, 15.1]


def test_parse_scenario_value_bare_number():
    c, r, u = _parse_scenario_value("13.5")
    assert abs(c - 13.5) < 1e-6
    assert r is None
    assert u is None


def test_extract_layer1_value_complex_string():
    # ru-rates style: "... 12.5–13.0% к 2026-12-31 (weighted median 12.7%) ..."
    forecast = {"central_estimate": "Ставка ЦБ: 12.5–13.0% к 2026-12-31 (weighted median 12.7%);"}
    val = _extract_layer1_value(forecast, ["2026-12-31"])
    assert val is not None
    # Should extract midpoint 12.75 from "12.5–13.0" near 2026, or 12.7 from "weighted median"
    assert 12.0 <= val <= 13.5


def test_extract_layer1_value_simple():
    forecast = {"central_estimate": "CPI YoY: 6.5–7.5% к 2026-12-31; 5.0–6.5% к 2027-12-31"}
    val = _extract_layer1_value(forecast, ["2026-12-31"])
    assert val is not None
    assert abs(val - 7.0) < 0.5  # midpoint of 6.5–7.5


# ── Integration: migrate_forecast() ──────────────────────────────────────────

def test_migrate_ru_rates_linear():
    """ru-rates: linear method with scenario_rates_2026/2027 YAML keys."""
    data = _load(RU_RATES_YAML)
    updated, result = migrate_forecast(data, SCENARIO_EQ)

    # New block present
    assert "conditional_on_scenarios" in updated
    cond = updated["conditional_on_scenarios"]

    # All 4 scenarios present
    by_sc = cond["by_scenario"]
    assert set(by_sc.keys()) == {"A", "B", "C", "D"}

    # 2026-12-31 values from YAML: Sc-A=10.5%, Sc-B=12.5%, Sc-C=11.5%, Sc-D=13.5%
    assert "2026-12-31" in by_sc["A"]["values"]
    assert abs(by_sc["A"]["values"]["2026-12-31"]["central"] - 10.5) < 0.01
    assert abs(by_sc["B"]["values"]["2026-12-31"]["central"] - 12.5) < 0.01
    assert abs(by_sc["C"]["values"]["2026-12-31"]["central"] - 11.5) < 0.01
    assert abs(by_sc["D"]["values"]["2026-12-31"]["central"] - 13.5) < 0.01

    # 2027-12-31 values: Sc-A=8.0%, Sc-D=11.5%
    assert "2027-12-31" in by_sc["A"]["values"]
    assert abs(by_sc["A"]["values"]["2027-12-31"]["central"] - 8.0) < 0.01
    assert abs(by_sc["D"]["values"]["2027-12-31"]["central"] - 11.5) < 0.01

    # Layer 2 marginal for 2026-12-31: equal weights → (10.5+12.5+11.5+13.5)/4 = 12.0
    assert "2026-12-31" in cond["marginal"]["values"]
    expected = (10.5 + 12.5 + 11.5 + 13.5) / 4
    assert abs(cond["marginal"]["values"]["2026-12-31"]["central"] - expected) < 0.01

    # modal_scenario_id: equal weights (0.25 each) → none
    assert cond["marginal"]["modal_scenario_id"] == "none"
    assert cond["marginal"]["method"] == "linear"
    assert cond["unit"] == "%"

    # geopolitics_translation removed
    assert "geopolitics_translation" not in updated.get("forecast", {})

    # coherence_diagnostic present
    assert "coherence_diagnostic" in updated
    assert updated["coherence_diagnostic"]["severity"] in ("LOW", "MEDIUM", "HIGH", "UNKNOWN")


def test_migrate_cny_rub_nonlinear_partial():
    """cny-rub: nonlinear with alternatives; EC1: Sc-D from central_estimate."""
    data = _load(CNY_RUB_YAML)
    updated, result = migrate_forecast(data, SCENARIO_EQ)

    assert "conditional_on_scenarios" in updated
    cond = updated["conditional_on_scenarios"]
    by_sc = cond["by_scenario"]

    # All 4 scenarios present
    assert set(by_sc.keys()) == {"A", "B", "C", "D"}

    # Sc-A: "10.8–12.6" → central=11.7, range=[10.8, 12.6]
    assert "2026-12-31" in by_sc["A"]["values"]
    assert abs(by_sc["A"]["values"]["2026-12-31"]["central"] - 11.7) < 0.1
    assert by_sc["A"]["values"]["2026-12-31"].get("range") == [10.8, 12.6]

    # Sc-B: "12.5–15.1" → central=13.8
    assert abs(by_sc["B"]["values"]["2026-12-31"]["central"] - 13.8) < 0.1

    # Sc-C: "11.8–13.3" → central=12.55
    assert abs(by_sc["C"]["values"]["2026-12-31"]["central"] - 12.55) < 0.1

    # EC1: Sc-D from central_estimate "CNY/RUB: 12.8–13.5 к 2026-12-31"
    assert "2026-12-31" in by_sc["D"]["values"]
    d_central = by_sc["D"]["values"]["2026-12-31"]["central"]
    assert abs(d_central - 13.15) < 0.2  # midpoint of 12.8–13.5

    # marginal.method is always linear (weighted_mean aggregation, not translation method)
    assert cond["marginal"]["method"] == "linear"

    # marginal.central must be weighted mean of all 4 scenarios, NOT Sc-A central
    # equal weights 0.25: (11.7 + 13.8 + 12.55 + 13.15) / 4 = 12.8
    assert "2026-12-31" in cond["marginal"]["values"]
    m_central = cond["marginal"]["values"]["2026-12-31"]["central"]
    assert abs(m_central - 12.8) < 0.1, f"Expected ~12.8, got {m_central}"
    assert abs(m_central - 11.7) > 0.5, f"marginal.central aliased to Sc-A: {m_central}"

    # geopolitics_translation removed
    assert "geopolitics_translation" not in updated.get("forecast", {})

    # coherence_diagnostic present
    assert "coherence_diagnostic" in updated


def test_migrate_ru_cpi_markdown_only():
    """ru-cpi: markdown-only (distribution_used=true, no YAML scenario values)."""
    data = _load(RU_CPI_YAML)
    updated, result = migrate_forecast(data, SCENARIO_EQ, md_path=RU_CPI_MD)

    assert "conditional_on_scenarios" in updated
    cond = updated["conditional_on_scenarios"]
    by_sc = cond["by_scenario"]

    # All 4 scenarios present
    assert set(by_sc.keys()) == {"A", "B", "C", "D"}

    # Values from markdown table:
    # A: 4.4%, B: 7.0%, C: 6.0%, D: 7.75%
    hz = "2026-12-31"
    assert hz in by_sc["A"]["values"]
    assert abs(by_sc["A"]["values"][hz]["central"] - 4.4) < 0.01
    assert abs(by_sc["B"]["values"][hz]["central"] - 7.0) < 0.01
    assert abs(by_sc["C"]["values"][hz]["central"] - 6.0) < 0.01
    assert abs(by_sc["D"]["values"][hz]["central"] - 7.75) < 0.01

    # Marginal for 2026-12-31 with equal weights: (4.4+7.0+6.0+7.75)/4 = 6.2875
    assert hz in cond["marginal"]["values"]
    expected = (4.4 + 7.0 + 6.0 + 7.75) / 4
    assert abs(cond["marginal"]["values"][hz]["central"] - expected) < 0.01

    assert cond["marginal"]["method"] == "linear"
    assert cond["unit"] == "%"

    # geopolitics_translation removed
    assert "geopolitics_translation" not in updated.get("forecast", {})

    # coherence_diagnostic present
    assert "coherence_diagnostic" in updated


def test_ec5_not_triggered_for_top_level_geo_trans():
    """Bug 5: geopolitics_translation at top level (no schema_version) must not trigger EC5."""
    data = {
        "forecast": {
            "horizons": ["2026-12-31"],
            "central_estimate": "7.0%",
        },
        "geopolitics_translation": {
            "method": "linear",
            "scenario_rates_2026": {
                "Sc-A": "5.0%", "Sc-B": "8.0%", "Sc-C": "7.0%", "Sc-D": "9.0%",
            },
        },
    }
    updated, result = migrate_forecast(data, SCENARIO_EQ)
    assert "conditional_on_scenarios" in updated
    by_sc = updated["conditional_on_scenarios"]["by_scenario"]
    assert abs(by_sc["A"]["values"]["2026-12-31"]["central"] - 5.0) < 0.01
    assert abs(by_sc["D"]["values"]["2026-12-31"]["central"] - 9.0) < 0.01
    # EC5 must NOT have fired
    assert not any("EC5" in e for e in result.log), f"EC5 should not fire: {result.log}"
    # top-level geopolitics_translation removed from output
    assert "geopolitics_translation" not in updated


def test_migrate_isolated_type1():
    """EC5a: --isolated → write isolated:true, no conditional_on_scenarios."""
    data = {
        "forecast": {
            "horizons": ["2030-12-31"],
            "central_estimate": "Война РФ–НАТО: вероятность <15% к 2030-12-31",
        },
    }
    updated, result = migrate_forecast(data, SCENARIO_EQ, isolated=True)

    assert updated.get("isolated") is True, f"Expected isolated:true, got {updated.get('isolated')}"
    assert "isolated_reason" in updated
    assert "conditional_on_scenarios" not in updated, "Type 1 must not have conditional block"
    assert "coherence_diagnostic" not in updated, "Type 1 must not have coherence block"
    assert any("EC5a" in e for e in result.log), f"Expected EC5a log entry, got {result.log}"


def test_migrate_isolated_with_custom_reason():
    """isolated_reason override works."""
    data = {"forecast": {"central_estimate": "x", "horizons": ["2026-12-31"]}}
    custom = "Single binary event: US-Iran deal by 2026-08"
    updated, _ = migrate_forecast(data, SCENARIO_EQ, isolated=True, isolated_reason=custom)
    assert updated["isolated_reason"] == custom


def test_migrate_isolated_drops_legacy_geo_translation():
    """EC5a: если у forecast был geopolitics_translation — он должен быть удалён."""
    data = {
        "forecast": {
            "horizons": ["2030-12-31"],
            "central_estimate": "x",
            "geopolitics_translation": {"method": "linear", "scenario_rates_2030": {}},
        },
    }
    updated, result = migrate_forecast(data, SCENARIO_EQ, isolated=True)
    assert "geopolitics_translation" not in updated.get("forecast", {})
    assert any("REMOVED" in e for e in result.log)


def test_migrate_axis_dependent_resolved():
    """EC5c (SB-1): axis_dependent resolved via weighted_mean — no _todo, aggregation_formula=weighted_mean."""
    data = {
        "forecast": {
            "horizons": ["2026-12-31"],
            "central_estimate": "20%",
        },
        "geopolitics_translation": {
            "method": "axis_dependent",
            "scenario_rates_2026": {
                "Sc-A": "10%", "Sc-B": "15%", "Sc-C": "25%", "Sc-D": "30%",
            },
        },
    }
    updated, result = migrate_forecast(data, SCENARIO_EQ)
    cond = updated.get("conditional_on_scenarios", {})
    marg = cond.get("marginal", {})

    assert marg.get("method") == "axis_dependent", f"Expected method preserved as diagnostic tag, got {marg.get('method')}"
    assert "_todo" not in marg, f"_todo must be absent (SB-1 resolved): {marg}"
    assert marg.get("aggregation_formula") == "weighted_mean", f"Expected weighted_mean, got {marg.get('aggregation_formula')}"
    assert any("EC5c" in e for e in result.log), f"Expected EC5c log, got {result.log}"
    # central = probability-weighted mean (equal weights 0.25): (10+15+25+30)/4 = 20.0
    hz = "2026-12-31"
    central = marg.get("values", {}).get(hz, {}).get("central")
    assert central is not None, f"Expected central value, got {marg.get('values')}"
    assert abs(central - 20.0) < 0.1, f"Expected 20.0 (weighted_mean), got {central}"


def test_migrate_axis_dependent_no_todo_for_other_methods():
    """Linear/nonlinear/indifferent → method: linear (weighted_mean). No _todo for any method after SB-1."""
    data = {
        "forecast": {"horizons": ["2026-12-31"], "central_estimate": "13.5"},
        "geopolitics_translation": {
            "method": "nonlinear",
            "alternatives": [
                {"scenario": "Sc-A", "value": "10%"},
                {"scenario": "Sc-B", "value": "12%"},
                {"scenario": "Sc-C", "value": "14%"},
                {"scenario": "Sc-D", "value": "16%"},
            ],
        },
    }
    updated, _ = migrate_forecast(data, SCENARIO_EQ)
    marg = updated["conditional_on_scenarios"]["marginal"]
    assert marg["method"] == "linear", f"Expected linear (weighted_mean), got {marg['method']}"
    assert "_todo" not in marg, f"_todo не должен быть для не-axis_dependent: {marg}"


def test_parse_scenario_value_dollar_thousands():
    """Bug 6: $5,400 → (5400, None, 'USD'); not 400."""
    c, r, u = _parse_scenario_value("$5,400")
    assert abs(c - 5400) < 1, f"Expected 5400, got {c}"
    assert u == "USD"
    assert r is None


def test_parse_central_dollar_thousands():
    """Bug 6: parse_central must handle thousands-separator commas."""
    import importlib, sys
    sys.path.insert(0, str(REPO_ROOT / "skills" / "forecast-confidence-applier" / "scripts"))
    from weighted_consensus import parse_central as _pc
    assert abs(_pc("$5,400") - 5400) < 1
    assert abs(_pc("$1,234.56") - 1234.56) < 0.01
    assert abs(_pc("5,400") - 5400) < 1


def test_migration_chardet_mojibake():
    """EC4: detect and repair Cyrillic mojibake (UTF-8 content double-encoded as UTF-8→latin-1→UTF-8)."""
    # Build mojibake bytes: UTF-8 Cyrillic → decode as latin-1 → encode as UTF-8
    original_text = "Ставка 12%"
    utf8_bytes = original_text.encode("utf-8")

    try:
        garbled_str = utf8_bytes.decode("latin-1")   # treat UTF-8 bytes as latin-1 chars
        mojibake_bytes = garbled_str.encode("utf-8")  # re-encode as UTF-8 → mojibake
    except (UnicodeDecodeError, UnicodeEncodeError):
        if _PYTEST_AVAILABLE:
            _pytest.skip("Cannot create mojibake fixture on this platform")
        return  # пропускаем тест в standalone-режиме

    # Mojibake bytes are NOT the same as original UTF-8
    assert mojibake_bytes != utf8_bytes, "Mojibake bytes should differ from original"

    # _repair_encoding should recover the original
    cleaned, repaired = _repair_encoding(mojibake_bytes)
    assert repaired, "Should have detected and repaired mojibake"
    recovered = cleaned.decode("utf-8")
    assert original_text in recovered, f"Expected '{original_text}' in recovered text, got: {recovered!r}"


def test_migration_creates_backup(tmp_path):
    """migrate_file() creates .pre-migration backup, updates YAML, and writes diff log."""
    # Copy fixture to tmp dir
    src = RU_RATES_YAML
    dst = tmp_path / "test_forecast.yaml"
    shutil.copy2(src, dst)
    shutil.copy2(FIXTURES / "scenario-equal-weights.yaml",
                 tmp_path / "scenario-equal-weights.yaml")

    result = migrate_file(
        input_path=dst,
        scenario_yaml_path=str(tmp_path / "scenario-equal-weights.yaml"),
    )

    # Backup exists
    backup = Path(str(dst) + ".pre-migration")
    assert backup.exists(), f"Backup not found: {backup}"

    # Backup is unchanged original
    orig = yaml.safe_load(src.read_text(encoding="utf-8"))
    backed_up = yaml.safe_load(backup.read_text(encoding="utf-8"))
    assert orig == backed_up, "Backup content should match original"

    # Updated file has conditional_on_scenarios
    updated = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert "conditional_on_scenarios" in updated

    # geopolitics_translation removed from forecast
    assert "geopolitics_translation" not in updated.get("forecast", {})

    # Diff log created
    diff_log = tmp_path / "test_forecast.migration-diff.md"
    assert diff_log.exists(), f"Diff log not found: {diff_log}"
    diff_content = diff_log.read_text(encoding="utf-8")
    assert "BACKUP" in diff_content or "WRITTEN" in diff_content


# ── Standalone runner (same pattern as other skill tests) ─────────────────────

if __name__ == "__main__":
    import sys as _sys

    checks_run = 0
    checks_failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        global checks_run, checks_failed
        checks_run += 1
        status = "OK" if condition else "FAIL"
        if not condition:
            checks_failed += 1
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

    # Run all test_ functions
    import traceback
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            try:
                if "tmp_path" in fn.__code__.co_varnames:
                    import tempfile
                    with tempfile.TemporaryDirectory() as td:
                        fn(Path(td))
                else:
                    fn()
                check(name, True)
            except Exception as exc:
                check(name, False, str(exc))
                traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Результат: {checks_run - checks_failed}/{checks_run} прошли")
    if checks_failed:
        _sys.exit(1)

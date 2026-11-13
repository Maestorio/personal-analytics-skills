#!/usr/bin/env python3
"""
Регрессионные тесты для coverage_report.py.

Запуск из корня репозитория:
    python3 skills/macro-forecast-chain/tests/test_coverage_report.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "macro-forecast-chain" / "scripts" / "coverage_report.py"

sys.path.insert(0, str(SCRIPT.parent))
from coverage_report import (  # noqa: E402
    age_status,
    check_consistency,
    check_consistency_pair,
    compute,
    evaluate_factor,
    horizon_status,
    load_spot,
    matrix_check,
    merged_monitor_alerts,
    parse_spot_number,
    recommend_mode,
    threshold_for,
)


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Шаг 2.3 — статусы
# --------------------------------------------------------------------------

def test_thresholds():
    print("test_thresholds")
    check("brent → 45", threshold_for("brent") == 45)
    check("urals_discount → 60", threshold_for("urals_discount") == 60)
    check("budget_deficit → 90", threshold_for("budget_deficit") == 90)
    check("sector_oil_gas → 90", threshold_for("sector_oil_gas") == 90)
    check("override применяется", threshold_for("brent", {"brent": 30}) == 30)


def test_age_status():
    print("test_age_status")
    # threshold=45: 0.75*45 = 33.75
    check("age=10, t=45 → FRESH", age_status(10, 45) == "FRESH")
    check("age=33, t=45 → FRESH (на границе ×0.75)", age_status(33, 45) == "FRESH")
    check("age=40, t=45 → AGING", age_status(40, 45) == "AGING")
    check("age=46, t=45 → STALE", age_status(46, 45) == "STALE")
    check("age=91, t=45 → VERY_STALE (>2×порог)", age_status(91, 45) == "VERY_STALE")


def test_horizon_status():
    print("test_horizon_status")
    targets = [date(2026, 12, 31), date(2027, 12, 31)]
    check("max horizon ≥ max target → COVERS",
          horizon_status(["2027-12-31"], targets) == "COVERS")
    check("max horizon < max target → INSUFFICIENT",
          horizon_status(["2026-09-01"], targets) == "INSUFFICIENT_HORIZON")
    check("пустой список → INSUFFICIENT",
          horizon_status([], targets) == "INSUFFICIENT_HORIZON")
    check("несколько горизонтов, max покрывает → COVERS",
          horizon_status(["2026-06-01", "2027-12-31"], targets) == "COVERS")


def test_evaluate_factor_fresh():
    """Свежий прогноз с правильным горизонтом → ✓ FRESH."""
    print("test_evaluate_factor_fresh")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31), date(2027, 12, 31)]
    f = {
        "name": "brent", "needed": True,
        "forecast_date": "2026-04-28",
        "horizon_dates": ["2027-12-31"],
        "method": "fca", "confidence": 0.72,
    }
    row = evaluate_factor(f, today, targets, {})
    check("overall = ✓ FRESH", row["overall_status"] == "✓ FRESH",
          f"got {row['overall_status']}")
    check("is_blocking = False", row["is_blocking"] is False)
    check("age_days = 7", row["age_days"] == 7)


def test_evaluate_factor_missing():
    print("test_evaluate_factor_missing")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {"name": "sanctions", "needed": True, "forecast_date": None}
    row = evaluate_factor(f, today, targets, {})
    check("overall = ✗ MISSING", row["overall_status"] == "✗ MISSING")
    check("is_blocking = True", row["is_blocking"] is True)


def test_evaluate_factor_fresh_but_short():
    """Реальный кейс из SKILL.md: usdrub свежий но горизонт короткий."""
    print("test_evaluate_factor_fresh_but_short")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31), date(2027, 12, 31)]
    f = {
        "name": "usdrub", "needed": True,
        "forecast_date": "2026-04-28",
        "horizon_dates": ["2026-09-01"],
        "method": "fca", "confidence": 0.61,
    }
    row = evaluate_factor(f, today, targets, {})
    check("overall = ⚠ FRESH-but-short",
          row["overall_status"] == "⚠ FRESH-but-short",
          f"got {row['overall_status']}")
    check("is_blocking = True", row["is_blocking"] is True)
    check("caveat про INSUFFICIENT_HORIZON",
          any("INSUFFICIENT_HORIZON" in c for c in row["caveats"]))


def test_evaluate_factor_broken():
    """fca-прогноз без confidence → ⚠ BROKEN."""
    print("test_evaluate_factor_broken")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "cbr_rate", "needed": True,
        "forecast_date": "2026-04-28",
        "horizon_dates": ["2027-12-31"],
        "method": "fca", "confidence": None,
    }
    row = evaluate_factor(f, today, targets, {})
    check("overall = ⚠ BROKEN", row["overall_status"] == "⚠ BROKEN")
    check("is_blocking = True", row["is_blocking"] is True)
    check("caveat про BROKEN_RECORD",
          any("BROKEN_RECORD" in c for c in row["caveats"]))


def test_evaluate_factor_stale():
    print("test_evaluate_factor_stale")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "brent", "needed": True,
        "forecast_date": "2026-02-01",   # 93 дня (>2×45)
        "horizon_dates": ["2027-12-31"],
        "method": "fca", "confidence": 0.6,
    }
    row = evaluate_factor(f, today, targets, {})
    check("STALE/VERY_STALE → blocking",
          row["is_blocking"] is True and "STALE" in row["overall_status"])


def test_evaluate_factor_monitor_flag_ignored():
    """stale_flags.yaml упразднён (R15): monitor_flag во входе не влияет — свежесть только по датам прогноза."""
    print("test_evaluate_factor_monitor_flag_ignored")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "brent", "needed": True,
        "forecast_date": "2026-04-28",  # FRESH
        "horizon_dates": ["2027-12-31"],
        "method": "fca", "confidence": 0.7,
        "monitor_flag": "critical",
    }
    row = evaluate_factor(f, today, targets, {})
    check("FRESH по дате, флаг монитора не читается", row["overall_status"] == "✓ FRESH")
    check("blocking = False", row["is_blocking"] is False)
    check("monitor_flag нет в строке", "monitor_flag" not in row)


def test_evaluate_factor_no_confidence_caveat():
    """method=manual + confidence=null → caveat NO_CONFIDENCE, не блокирует."""
    print("test_evaluate_factor_no_confidence_caveat")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "geopolitics", "needed": True,
        "forecast_date": "2026-04-15",
        "horizon_dates": ["2027-12-31"],
        "method": "manual", "confidence": None,
    }
    row = evaluate_factor(f, today, targets, {})
    check("FRESH (не блокирует)", row["overall_status"] == "✓ FRESH")
    check("caveat NO_CONFIDENCE",
          any("NO_CONFIDENCE" in c for c in row["caveats"]))


def test_not_needed():
    print("test_not_needed")
    today = date(2026, 5, 5)
    f = {"name": "xauusd", "needed": False}
    row = evaluate_factor(f, today, [], {})
    check("NOT NEEDED → не блокирует",
          row["overall_status"] == "— NOT NEEDED" and row["is_blocking"] is False)


def test_evaluate_factor_legacy_no_method():
    """method=None (legacy YAML) → treat as manual + LEGACY_FORMAT_NO_METHOD caveat, не BROKEN."""
    print("test_evaluate_factor_legacy_no_method")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "brent", "needed": True,
        "forecast_date": "2026-04-28",
        "horizon_dates": ["2027-12-31"],
        # method отсутствует, confidence отсутствует
    }
    row = evaluate_factor(f, today, targets, {})
    check("FRESH (не BROKEN)", row["overall_status"] == "✓ FRESH",
          f"got {row['overall_status']}")
    check("не блокирует", row["is_blocking"] is False)
    check("caveat LEGACY_FORMAT_NO_METHOD",
          any("LEGACY_FORMAT_NO_METHOD" in c for c in row["caveats"]),
          f"caveats: {row['caveats']}")
    # treat as manual → confidence=None даёт NO_CONFIDENCE
    check("caveat NO_CONFIDENCE добавлен (legacy → manual)",
          any("NO_CONFIDENCE" in c for c in row["caveats"]))


def test_evaluate_factor_legacy_empty_method():
    """method='' (пустая строка) → тоже trakt as manual."""
    print("test_evaluate_factor_legacy_empty_method")
    today = date(2026, 5, 5)
    targets = [date(2026, 12, 31)]
    f = {
        "name": "usdrub", "needed": True,
        "forecast_date": "2026-04-28",
        "horizon_dates": ["2027-12-31"],
        "method": "",
        "confidence": 0.6,
    }
    row = evaluate_factor(f, today, targets, {})
    check("FRESH", row["overall_status"] == "✓ FRESH")
    check("caveat LEGACY_FORMAT_NO_METHOD",
          any("LEGACY_FORMAT_NO_METHOD" in c for c in row["caveats"]))


# --------------------------------------------------------------------------
# Шаг 3.5 — рекомендация режима
# --------------------------------------------------------------------------

def test_recommend_mode_partial():
    print("test_recommend_mode_partial")
    rows = [{"overall_status": "✓ FRESH"}, {"overall_status": "✓ FRESH"}]
    rec = recommend_mode(rows)
    check("PARTIAL", rec["mode"] == "PARTIAL")


def test_recommend_mode_quick():
    print("test_recommend_mode_quick")
    rows = [
        {"overall_status": "✓ FRESH"},
        {"overall_status": "⚠ STALE"},
        {"overall_status": "⚠ STALE"},
    ]
    rec = recommend_mode(rows)
    check("QUICK-REFRESH", rec["mode"] == "QUICK-REFRESH",
          f"got {rec['mode']}")
    check("stale = 2", rec["stale"] == 2)


def test_recommend_mode_full_missing():
    print("test_recommend_mode_full_missing")
    rows = [
        {"overall_status": "✓ FRESH"},
        {"overall_status": "✗ MISSING"},
    ]
    rec = recommend_mode(rows)
    check("FULL (есть MISSING)", rec["mode"] == "FULL")


def test_recommend_mode_full_many_stale():
    print("test_recommend_mode_full_many_stale")
    rows = [{"overall_status": "⚠ STALE"} for _ in range(4)]
    rec = recommend_mode(rows)
    check("FULL (≥4 STALE)", rec["mode"] == "FULL")


def test_recommend_mode_full_critical():
    print("test_recommend_mode_full_critical")
    rows = [
        {"overall_status": "✓ FRESH"},
        {"overall_status": "⚠ BROKEN"},
    ]
    rec = recommend_mode(rows)
    check("FULL (есть BROKEN/critical)", rec["mode"] == "FULL")


# --------------------------------------------------------------------------
# Шаг 6 — consistency check
# --------------------------------------------------------------------------

def test_consistency_oil_rub_medium():
    print("test_consistency_oil_rub_medium")
    sc = {"brent_pct_change": 12, "usdrub_pct_change": 6}
    v = check_consistency_pair(sc)
    rules = [it["rule"] for it in v]
    check("oil_rub_divergence detected", "oil_rub_divergence" in rules)
    check("severity = medium",
          next(it for it in v if it["rule"] == "oil_rub_divergence")["severity"] == "medium")


def test_consistency_oil_rub_critical():
    print("test_consistency_oil_rub_critical")
    sc = {"brent_pct_change": 25, "usdrub_pct_change": 15}
    v = check_consistency_pair(sc)
    rules = [it["rule"] for it in v]
    check("extreme divergence → critical", "oil_rub_extreme_divergence" in rules)


def test_consistency_extreme_rate_cut():
    print("test_consistency_extreme_rate_cut")
    sc = {"rate_bps_change": -600}
    v = check_consistency_pair(sc)
    check("extreme_rate_cut → critical",
          any(it["rule"] == "extreme_rate_cut" and it["severity"] == "critical"
              for it in v))


def test_consistency_2022_pattern():
    print("test_consistency_2022_pattern")
    sc = {"brent_pct_change": -25, "usdrub_pct_change": 25, "inflation_ru_pct": 12}
    v = check_consistency_pair(sc)
    check("stress_2022_pattern → critical",
          any(it["rule"] == "stress_2022_pattern" and it["severity"] == "critical"
              for it in v))


def test_consistency_clean_scenario():
    """Сбалансированный сценарий — нет нарушений."""
    print("test_consistency_clean_scenario")
    sc = {
        "brent_pct_change": 5, "usdrub_pct_change": -2,
        "rate_bps_change": -100, "inflation_ru_pct": 6,
    }
    v = check_consistency_pair(sc)
    check("0 violations", len(v) == 0, f"got {[it['rule'] for it in v]}")


def test_check_consistency_full():
    print("test_check_consistency_full")
    scenarios = {
        "Sc-A": {"brent_pct_change": 5, "usdrub_pct_change": -2},
        "Sc-B": {"brent_pct_change": 25, "usdrub_pct_change": 15},  # critical
        "Sc-C": {"brent_pct_change": 12, "usdrub_pct_change": 6},   # medium
    }
    res = check_consistency(scenarios)
    check("counts.critical = 1", res["counts"]["critical"] == 1)
    check("counts.medium = 1", res["counts"]["medium"] == 1)
    check("compatible = False (есть critical)", res["compatible"] is False)


# --------------------------------------------------------------------------
# Полный пайплайн
# --------------------------------------------------------------------------

def test_compute_pipeline():
    print("test_compute_pipeline")
    payload = {
        "today": "2026-05-05",
        "chain_target_horizons": ["2026-12-31", "2027-12-31"],
        "factors": [
            {"name": "brent", "needed": True,
             "forecast_date": "2026-04-28",
             "horizon_dates": ["2027-12-31"],
             "method": "fca", "confidence": 0.72},
            {"name": "sanctions", "needed": True,
             "forecast_date": None},
            {"name": "usdrub", "needed": True,
             "forecast_date": "2026-04-20",
             "horizon_dates": ["2026-09-01"],
             "method": "fca", "confidence": 0.61},
            {"name": "cbr_rate", "needed": True,
             "forecast_date": "2026-04-28",
             "horizon_dates": ["2027-12-31"],
             "method": "fca", "confidence": None},
            {"name": "xauusd", "needed": False},
        ],
        "scenarios_to_check": {
            "Sc-A": {"brent_pct_change": 25, "usdrub_pct_change": 15},
        },
    }
    res = compute(payload)
    summary = res["summary"]
    check("missing = 1 (sanctions)", summary["missing"] == 1)
    check("broken = 1 (cbr_rate)", summary["broken"] == 1)
    check("insufficient = 1 (usdrub)", summary["insufficient_horizon"] == 1)
    check("ready_for_stress_test = False", summary["ready_for_stress_test"] is False)
    check("mode = FULL", res["mode_recommendation"]["mode"] == "FULL")
    check("consistency: critical detected",
          res["consistency"]["counts"]["critical"] >= 1)


def test_compute_recalibrate_mode():
    print("test_compute_recalibrate_mode")
    payload = {
        "today": "2026-05-05",
        "mode": "RECALIBRATE",
        # Coverage payload игнорируется в RECALIBRATE-mode
        "factors": [{"name": "brent", "needed": True, "forecast_date": None}],
    }
    res = compute(payload)
    check("RECALIBRATE → ready_for_stress_test=True",
          res["summary"]["ready_for_stress_test"] is True)
    check("RECALIBRATE → mode_recommendation=RECALIBRATE",
          res["mode_recommendation"]["recommended_mode"] == "RECALIBRATE")
    check("RECALIBRATE → coverage_score N/A",
          res["summary"]["coverage_score"] == "N/A (RECALIBRATE)")
    check("RECALIBRATE → blocking_issues empty",
          res["summary"]["blocking_issues"] == [])


def test_cli_stdin():
    print("test_cli_stdin")
    payload = {
        "today": "2026-05-05",
        "factors": [{"name": "brent", "needed": True,
                     "forecast_date": "2026-04-28",
                     "horizon_dates": ["2027-12-31"],
                     "method": "fca", "confidence": 0.7}],
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("brent FRESH",
          out["rows"][0]["overall_status"] == "✓ FRESH")


# --------------------------------------------------------------------------
# Пробой по монитору (довесок шага 14): factor_breach последнего отчёта → STALE
# --------------------------------------------------------------------------

_MR_FULL_OLD = """schema_version: 1
type: monitor-report
generated_at: "2026-10-08T06:22:00Z"
alerts:
  - severity: HIGH
    category: factor_breach
    target: "brent-price"
    target_file: "forecasts/brent-price-2026-09-17.yaml"
    target_kind: forecast
    message: "старый пробой"
caveats: []
"""
_MR_FULL = """schema_version: 1
type: monitor-report
generated_at: "2026-10-26T11:25:00Z"
alerts:
  - severity: HIGH
    category: factor_breach
    target: "cbr-rate-2026-2027"
    target_file: "forecasts/cbr-rate-2026-2027-2026-09-17.yaml"
    target_kind: forecast
    message: "пробит"
  - severity: HIGH
    category: factor_breach
    target: "usdrub-rate"
    target_file: "forecasts/usdrub-rate-2026-09-17.yaml"
    target_kind: forecast
    message: "пробит"
  - severity: MEDIUM
    category: stale
    target: "inflation-ru"
    target_file: "forecasts/inflation-ru-2026-09-17.yaml"
    target_kind: forecast
    message: "ревью просрочено"
caveats: []
"""
# тот же день, создан раньше v2: база выбирается по generated_at, не по имени файла
_MR_FULL_EARLIER_SAME_DAY = """schema_version: 1
type: monitor-report
generated_at: "2026-10-25T21:40:00Z"
alerts:
  - severity: HIGH
    category: factor_breach
    target: "inflation-ru"
    target_file: "forecasts/inflation-ru-2026-09-17.yaml"
    target_kind: forecast
    message: "перекрыт v2"
caveats: []
"""
_MR_PARTIAL = """schema_version: 1
type: monitor-report
generated_at: "2026-10-29T15:50:00+03:00"
scope: partial
checked: ["forecasts/usdrub-rate-2026-09-17.yaml"]
alerts: []
caveats: []
"""
_MR_PARTIAL_LEGACY = """schema_version: 1
type: monitor-report
generated_at: "2026-10-30T10:00:00+03:00"
alerts:
  - severity: HIGH
    category: factor_breach
    target: "brent-price"
    target_file: "forecasts/brent-price-2026-10-08.yaml"
    target_kind: forecast
    message: "пробит"
caveats:
  - { severity: INFO, message: "Запуск по одному файлу (brent-price): остальные не проверялись" }
"""


def _mr_dir(files: dict) -> str:
    d = tempfile.mkdtemp(prefix="mr-")
    for name, text in files.items():
        with open(f"{d}/{name}", "w", encoding="utf-8") as fh:
            fh.write(text)
    return d


def _fac(name, ff, fdate, horizon="2027-12-31"):
    return {"name": name, "needed": True, "forecast_file": ff, "forecast_date": fdate,
            "horizon_dates": [horizon], "method": "fca", "confidence": 0.6}


def test_monitor_breach_merge():
    print("test_monitor_breach_merge")
    d = _mr_dir({
        "monitor-report-2026-10-08.yaml": _MR_FULL_OLD,
        "monitor-report-2026-10-26.yaml": _MR_FULL_EARLIER_SAME_DAY,
        "monitor-report-2026-10-26-v2.yaml": _MR_FULL,
        "monitor-report-2026-10-29.yaml": _MR_PARTIAL,
        "monitor-report-2026-10-30.yaml": _MR_PARTIAL_LEGACY,
    })
    m = merged_monitor_alerts(d)
    check("база — последний полный по generated_at (v2, не …-10-26)",
          m["base"] == "monitor-report-2026-10-26-v2.yaml", m["base"])
    check("частичные новее базы — по порядку", m["partials"] == [
        "monitor-report-2026-10-29.yaml", "monitor-report-2026-10-30.yaml"], str(m["partials"]))
    targets = {(a["target"], a["category"]) for a in m["alerts"]}
    check("пробой cbr из полного остаётся", ("cbr-rate-2026-2027", "factor_breach") in targets)
    check("usdrub проверен частичным с пустыми алертами — пробоя нет",
          not any(a["target"] == "usdrub-rate" for a in m["alerts"]))
    check("старый полный отчёт (10-08) не читается — пробой brent-09-17 не в картине",
          not any(a.get("target_file") == "forecasts/brent-price-2026-09-17.yaml" for a in m["alerts"]))
    check("частичный без scope по оговорке «Запуск по одному файлу» добавляет свой пробой",
          any(a.get("target_file") == "forecasts/brent-price-2026-10-08.yaml" for a in m["alerts"]))
    cbr = next(a for a in m["alerts"] if a["target"] == "cbr-rate-2026-2027")
    check("дата отчёта — из имени файла", cbr["_report_date"] == "2026-10-26", cbr["_report_date"])

    payload = {"today": "2026-10-31", "factors": [
        _fac("cbr_rate", "forecasts/cbr-rate-2026-2027-2026-09-17.yaml", "2026-10-20"),
        _fac("usdrub", "forecasts/usdrub-rate-2026-09-17.yaml", "2026-10-20"),
        _fac("brent", "forecasts/brent-price-2026-10-28.yaml", "2026-10-28"),
        _fac("inflation_ru", "forecasts/inflation-ru-2026-09-17.yaml", "2026-10-20", horizon="2026-09-30"),
        {"name": "xauusd", "needed": True},
    ]}
    out = compute(payload, m)
    rows = {r["factor"]: r for r in out["rows"]}
    cbr = rows["cbr_rate"]
    check("пробой → STALE при свежей дате", cbr["overall_status"] == "⚠ STALE" and cbr["age_status"] == "FRESH",
          cbr["overall_status"])
    check("причина «пробой по монитору от <дата>»", cbr.get("stale_reason") == "пробой по монитору от 2026-10-26")
    check("caveat MONITOR_BREACH первым, blocking", cbr["caveats"][0].startswith("MONITOR_BREACH:") and cbr["is_blocking"])
    check("monitor_breach несёт файл и отчёт", cbr["monitor_breach"]["target_file"]
          == "forecasts/cbr-rate-2026-2027-2026-09-17.yaml"
          and cbr["monitor_breach"]["report_file"] == "monitor-report-2026-10-26-v2.yaml")
    check("usdrub FRESH: частичный снял пробой", rows["usdrub"]["overall_status"] == "✓ FRESH")
    check("brent: пробой по старому файлу темы не действует на новый прогноз",
          rows["brent"]["overall_status"] == "✓ FRESH" and "stale_reason" not in rows["brent"])
    check("stale (не пробой) монитора статус не меняет; FRESH-but-short остаётся",
          rows["inflation_ru"]["overall_status"] == "⚠ FRESH-but-short")
    check("MISSING не трогается", rows["xauusd"]["overall_status"] == "✗ MISSING")
    check("сводка: stale=1, coverage 2/5", out["summary"]["stale"] == 1
          and out["summary"]["coverage_score"] == "2/5", str(out["summary"]))
    check("unmatched — пробой brent-10-08 без фактора",
          [u["target_file"] for u in out["monitor"]["unmatched_breaches"]]
          == ["forecasts/brent-price-2026-10-08.yaml"], str(out["monitor"]))
    check("без monitor — поля monitor нет, cbr FRESH", "monitor" not in compute(payload)
          and compute(payload)["rows"][0]["overall_status"] == "✓ FRESH")


def test_monitor_breach_short_and_no_file():
    print("test_monitor_breach_short_and_no_file")
    m = {"alerts": [
        {"category": "factor_breach", "target": "cbr-rate-2026-2027",
         "target_file": "forecasts/cbr-rate-2026-2027-2026-09-17.yaml", "_report_date": "2026-10-26",
         "_report_file": "x"},
        {"category": "factor_breach", "target": "inflation-ru", "_report_date": "2026-10-26",
         "_report_file": "x"},
    ], "base": "x", "partials": []}
    payload = {"today": "2026-10-31", "factors": [
        _fac("cbr_rate", "forecasts/cbr-rate-2026-2027-2026-09-17.yaml", "2026-10-20", horizon="2026-09-30"),
        _fac("inflation_ru", "forecasts/inflation-ru-2026-10-20.yaml", "2026-10-20"),
        _fac("usdrub", "forecasts/usdrub-rate-2026-10-30.yaml", "2026-10-30"),
        {"name": "brent", "needed": True, "forecast_date": "2026-10-20",
         "horizon_dates": ["2027-12-31"], "method": "fca", "confidence": 0.6},
    ]}
    out = compute(payload, m)
    rows = {r["factor"]: r for r in out["rows"]}
    check("FRESH-but-short + пробой → STALE+SHORT", rows["cbr_rate"]["overall_status"] == "⚠ STALE+SHORT")
    check("алерт без target_file — по теме, прогноз не новее отчёта → STALE",
          rows["inflation_ru"]["overall_status"] == "⚠ STALE")
    m["alerts"][1]["_report_date"] = "2026-10-19"
    out2 = compute(payload, m)
    check("алерт без target_file, прогноз новее отчёта → не пробит",
          {r["factor"]: r for r in out2["rows"]}["inflation_ru"]["overall_status"] == "✓ FRESH")
    check("фактор без forecast_file не сверяется и перечислен",
          rows["brent"]["overall_status"] == "✓ FRESH"
          and out["monitor"]["factors_without_forecast_file"] == ["brent"])


def test_cli_monitor_report():
    print("test_cli_monitor_report")
    d = _mr_dir({"monitor-report-2026-10-26-v2.yaml": _MR_FULL})
    payload = {"today": "2026-10-31", "factors": [
        _fac("cbr_rate", "forecasts/cbr-rate-2026-2027-2026-09-17.yaml", "2026-10-20")]}
    for arg, label in ((d, "папка"), (f"{d}/monitor-report-2026-10-26-v2.yaml", "файл")):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--monitor-report", arg],
                              input=json.dumps(payload), capture_output=True, text=True, check=False)
        ok = proc.returncode == 0 and json.loads(proc.stdout)["rows"][0]["overall_status"] == "⚠ STALE"
        check(f"CLI --monitor-report ({label}) → STALE", ok, proc.stderr)
    bad = _mr_dir({"monitor-report-2026-10-26.yaml": "- просто список\n"})
    proc = subprocess.run([sys.executable, str(SCRIPT), "--monitor-report", bad],
                          input=json.dumps(payload), capture_output=True, text=True, check=False)
    check("нечитаемый отчёт → код 2, не тихий FRESH", proc.returncode == 2 and not proc.stdout, proc.stderr)


# --------------------------------------------------------------------------
# Расхождение центра прогноза со спотом макроснимка (STALE_VS_SPOT)
# --------------------------------------------------------------------------

_SNAP_MD = """# Макропанель РФ · 29.10.2026

## Snapshot

| Индикатор | Текущее | Прошлый snapshot (21.10) | Δ | Источник |
|---|---|---|---|---|
| Ключевая ставка ЦБ | 14.00% (на 29.10) | 14.00% | — | cbr |
| Инфляция (г/г) | 7.11% (на 26.10) | 7.15% | −0.04 п.п. | pnp |
| USD/RUB | 80.665 (MOEX, до открытия) | 81.915 | −1.53% | moex |
| CNY/RUB | 12.029 (MOEX) | 12.2255 | −1.61% | moex |
| Brent | $115.46 (ICE, дек. фьючерс, 28.10) | $107.97 | +6.94% | report.az |
| IMOEX | 2527.53 | 2447.06 | +3.29% | moex |

## Аномалии (|z| ≥ 1.0)

| Индикатор | Текущее |
|---|---|
| Brent | $1.00 |
"""
_SNAP_JSON = {"kind": "macro-ru@1", "date": "2026-11-03", "rows": [
    {"key": "cbr_key", "label": "Ключевая ставка ЦБ", "value": 14.0, "as_of": "2026-11-03"},
    {"key": "infl_yoy", "label": "Инфляция (г/г)", "value": 6.35, "as_of": "за 09.2026"},
    {"key": "usd_rub", "label": "USD/RUB", "value": 81.81, "as_of": "2026-11-03 06:30:06"},
    {"key": "brent", "label": "Brent", "value": 106.46, "as_of": "2026-11-02"},
]}
_BRENT_YAML = """schema_version: 1
forecast:
  date: 2026-10-08
fca_stats:
  "2026-10-31":
    kind: level
    l1_weighted: 70
  "2026-12-31":
    kind: level
    unit: "USD/bbl"
    l1_weighted: 90
  "2027-06-30":
    kind: level
    l1_weighted: 87.0
"""


def _snap_dir(md=True, js=True) -> str:
    d = tempfile.mkdtemp(prefix="ms-")
    Path(d, "auto").mkdir()
    Path(d, "ru-2026-10-21.md").write_text(_SNAP_MD.replace("115.46", "99.00"), encoding="utf-8")
    if md:
        Path(d, "ru-2026-10-29.md").write_text(_SNAP_MD, encoding="utf-8")
    if js:
        Path(d, "auto", "ru-2026-11-03.json").write_text(json.dumps(_SNAP_JSON), encoding="utf-8")
    return d


def _lvl(center, horizon="2026-12-31", field="l1_weighted"):
    return {horizon: {"kind": "level", field: center}}


def _spot_fac(name, stats, fdate="2026-10-08", horizon="2027-12-31"):
    f = _fac(name, f"forecasts/{name}-x-{fdate}.yaml", fdate, horizon)
    if stats is not None:
        f["fca_stats"] = stats
    return f


def _spot_rows(spot, factors, today="2026-11-04", **kw):
    out = compute({"today": today, "factors": factors, **kw}, None, spot)
    return out, {r["factor"]: r for r in out["rows"]}


def assert_spot_signal(load=load_spot, comp=compute) -> list[str]:
    """Сценарий FM-22; возвращает список нарушений (пусто — сигнал работает)."""
    bad = []
    spot = load(_snap_dir(js=False))
    out = comp({"today": "2026-11-04", "factors": [
        _spot_fac("brent", {**_lvl(70, "2026-10-31"), **_lvl(90), **_lvl(87, "2027-06-30")}),
        _spot_fac("usdrub", _lvl(83.0)),
    ]}, None, spot)
    rows = {r["factor"]: r for r in out["rows"]}
    b = rows["brent"]
    sc = b.get("spot_check") or {}
    if sc.get("status") != "stale_vs_spot":
        bad.append(f"brent: status {sc.get('status')}")
    if b["overall_status"] != "⚠ STALE" or b["age_status"] != "FRESH":
        bad.append(f"brent: overall {b['overall_status']}")
    if out["summary"].get("stale_vs_spot") != ["brent"]:
        bad.append(f"сводка {out['summary'].get('stale_vs_spot')}")
    if (rows["usdrub"].get("spot_check") or {}).get("status") != "ok":
        bad.append("usdrub не ok")
    return bad


def test_spot_parse_and_load():
    print("test_spot_parse_and_load")
    check("$115.46 (ICE…) → 115.46", parse_spot_number("$115.46 (ICE, дек. фьючерс, 28.10)") == 115.46)
    check("14.00% (на 29.10) → 14.0", parse_spot_number("14.00% (на 29.10)") == 14.0)
    check("пусто → None", parse_spot_number("—") is None)
    md = load_spot(_snap_dir(js=False))
    v = md["values"]
    check("папка без JSON — последний ru-*.md (29.10)", md["date"] == "2026-10-29", md["date"])
    check("md: пять индикаторов панели по подписи, IMOEX не фактор",
          set(v) == {"cbr_rate", "inflation_ru", "usdrub", "cnyrub", "brent"}, str(v))
    check("md: значения из колонки «Текущее», таблица аномалий не читается",
          v["brent"]["value"] == 115.46 and v["usdrub"]["value"] == 80.665
          and v["inflation_ru"]["value"] == 7.11, str(v))
    js = load_spot(_snap_dir())
    check("JSON сайта свежее среза — берётся он", js["date"] == "2026-11-03"
          and js["source"].endswith("auto/ru-2026-11-03.json"), js["source"])
    check("JSON: дата значения — as_of (Brent 02.11), неразборный as_of — дата снимка",
          js["values"]["brent"]["date"] == "2026-11-02"
          and js["values"]["inflation_ru"]["date"] == "2026-11-03", str(js["values"]))
    d = _snap_dir(js=False)
    Path(d, "auto", "ru-2026-10-29.json").write_text(json.dumps({**_SNAP_JSON, "date": "2026-10-29"}),
                                                     encoding="utf-8")
    check("равная дата — JSON", load_spot(d)["source"].endswith(".json"))


def test_spot_gap_signal():
    print("test_spot_gap_signal")
    bad = assert_spot_signal()
    check("выше порога → stale_vs_spot и STALE; ниже → ok", not bad, "; ".join(bad))
    spot = load_spot(_snap_dir(js=False))
    out, rows = _spot_rows(spot, [
        _spot_fac("brent", {**_lvl(70, "2026-10-31"), **_lvl(90)}),
        _spot_fac("cbr_rate", _lvl(12.0)),
        _spot_fac("inflation_ru", _lvl(6.8)),
        _spot_fac("cnyrub", _lvl(12.5, field="l1_unweighted") | {"2026-12-31": {
            "kind": "level", "l1_weighted": None, "l1_unweighted": 12.5}}),
        _spot_fac("xauusd", _lvl(4500)),
        _spot_fac("usdrub", {"2026-12-18": {"kind": "event", "predicted_p": 0.3}}),
        _spot_fac("budget_deficit", None),
    ])
    sc = rows["brent"]["spot_check"]
    check("центр — ближайший НЕИСТЁКШИЙ горизонт (2026-10-31 истёк)",
          sc["horizon"] == "2026-12-31" and sc["center"] == 90.0, str(sc))
    check("gap в % от спота: |90−115.46|/115.46 = 22.05 %", sc["gap"] == 22.05, str(sc["gap"]))
    check("причина «центр <x> против спота <y> (<дата>), расхождение <gap> > <порог>»",
          rows["brent"]["stale_reason"] == "центр 90 против спота 115.46 (2026-10-29), расхождение 22.05 % > 15 %",
          rows["brent"].get("stale_reason"))
    check("caveat STALE_VS_SPOT первым, blocking",
          rows["brent"]["caveats"][0].startswith("STALE_VS_SPOT:") and rows["brent"]["is_blocking"])
    check("cbr_rate: |12−14| = 2 п.п. > 1.5 → stale_vs_spot",
          rows["cbr_rate"]["spot_check"]["status"] == "stale_vs_spot"
          and rows["cbr_rate"]["overall_status"] == "⚠ STALE")
    check("inflation_ru: |6.8−7.11| = 0.31 п.п. → ok, FRESH",
          rows["inflation_ru"]["spot_check"]["status"] == "ok"
          and rows["inflation_ru"]["overall_status"] == "✓ FRESH")
    c = rows["cnyrub"]["spot_check"]
    check("пустой l1_weighted → центр l1_unweighted с пометкой",
          c["center"] == 12.5 and c["center_field"] == "l1_unweighted" and c["notes"], str(c))
    x = rows["xauusd"]["spot_check"]
    check("фактор без спота в панели → n/a, причина в notes",
          x["status"] == "n/a" and x["notes"] == ["спота фактора в макропанели нет"]
          and rows["xauusd"]["overall_status"] == "✓ FRESH", str(x))
    u = rows["usdrub"]["spot_check"]
    check("событийный прогноз → n/a", u["status"] == "n/a" and "событийный" in u["notes"][0], str(u))
    check("без fca_stats и без файла → n/a", rows["budget_deficit"]["spot_check"]["status"] == "n/a")
    check("сводка: stale_vs_spot = [brent, cbr_rate]",
          out["summary"]["stale_vs_spot"] == ["brent", "cbr_rate"], str(out["summary"]["stale_vs_spot"]))
    check("QUICK-REFRESH видит расхождение (2 протухших)",
          out["mode_recommendation"]["mode"] == "QUICK-REFRESH" and out["mode_recommendation"]["stale"] == 2)


def test_spot_gap_edges():
    print("test_spot_gap_edges")
    spot = load_spot(_snap_dir(js=False))
    _, rows = _spot_rows(spot, [_spot_fac("brent", _lvl(90))], today="2026-11-20")
    n = rows["brent"]["spot_check"]["notes"]
    check("спот старше 10 дней — сигнал считается, пометка «спот от <дата>»",
          rows["brent"]["spot_check"]["status"] == "stale_vs_spot" and "спот от 2026-10-29" in n, str(n))
    _, rows = _spot_rows(spot, [_spot_fac("brent", _lvl(90))], spot_gap_overrides={"brent": 25})
    check("spot_gap_overrides: порог 25 % → ok", rows["brent"]["spot_check"]["status"] == "ok"
          and rows["brent"]["spot_check"]["threshold"] == {"kind": "pct", "value": 25.0})
    short = _spot_fac("brent", _lvl(90), horizon="2026-09-30")
    _, rows = _spot_rows(spot, [short])
    check("FRESH-but-short + расхождение → STALE+SHORT", rows["brent"]["overall_status"] == "⚠ STALE+SHORT")
    out = compute({"today": "2026-11-04", "factors": [_spot_fac("brent", _lvl(90))]})
    check("без спота — spot_check нет, статус по дате", "spot_check" not in out["rows"][0]
          and out["rows"][0]["overall_status"] == "✓ FRESH" and "spot" not in out)
    out = compute({"today": "2026-11-04", "factors": [_spot_fac("brent", _lvl(90))], "spot": spot})
    check("спот во входе (`spot`) работает как --spot", out["rows"][0]["spot_check"]["status"] == "stale_vs_spot")
    m = {"alerts": [{"category": "factor_breach", "target": "brent-x",
                     "target_file": "forecasts/brent-x-2026-10-08.yaml", "_report_date": "2026-10-26",
                     "_report_file": "x"}], "base": "x", "partials": []}
    out = compute({"today": "2026-11-04", "factors": [_spot_fac("brent", _lvl(90))]}, m, spot)
    r = out["rows"][0]
    check("пробой и расхождение — обе причины через «; »",
          r["stale_reason"].startswith("пробой по монитору от 2026-10-26; центр 90"), r["stale_reason"])


def test_spot_mutant_must_fail():
    print("test_spot_mutant_must_fail")
    import coverage_report as cr
    orig = cr.spot_check

    def mutant(factor, spot, today, overrides, root):
        sc = orig(factor, spot, today, overrides, root)
        if sc["status"] == "stale_vs_spot":
            sc["status"] = "ok"
        return sc
    cr.spot_check = mutant
    try:
        bad = assert_spot_signal(cr.load_spot, cr.compute)
    finally:
        cr.spot_check = orig
    check("мутант «сигнал не считается» ловится", bool(bad), "; ".join(bad))
    cr.DEFAULT_SPOT_GAP_THRESHOLDS["brent"]["value"] = 1e9
    try:
        bad = assert_spot_signal(cr.load_spot, cr.compute)
    finally:
        cr.DEFAULT_SPOT_GAP_THRESHOLDS["brent"]["value"] = 15.0
    check("мутант «порог brent бесконечный» ловится", bool(bad), "; ".join(bad))


def test_cli_spot():
    print("test_cli_spot")
    mem = tempfile.mkdtemp(prefix="cm-")
    Path(mem, "forecasts").mkdir()
    Path(mem, "forecasts", "brent-price-2026-10-08.yaml").write_text(_BRENT_YAML, encoding="utf-8")
    snaps = _snap_dir(js=False)
    payload = {"today": "2026-11-04", "factors": [
        _fac("brent", "forecasts/brent-price-2026-10-08.yaml", "2026-10-08")]}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--spot", snaps, "--root", mem],
                          input=json.dumps(payload), capture_output=True, text=True, check=False)
    ok = proc.returncode == 0
    row = json.loads(proc.stdout)["rows"][0] if ok else {}
    check("CLI --spot --root: fca_stats из файла прогноза → STALE",
          ok and row["overall_status"] == "⚠ STALE" and row["spot_check"]["center"] == 90.0, proc.stderr)
    proc = subprocess.run([sys.executable, str(SCRIPT), "--spot", snaps],
                          input=json.dumps(payload), capture_output=True, text=True, check=False)
    row = json.loads(proc.stdout)["rows"][0]
    check("без --root файл не найден → n/a с причиной, статус по дате",
          row["spot_check"]["status"] == "n/a" and "не найден" in row["spot_check"]["notes"][0]
          and row["overall_status"] == "✓ FRESH", str(row["spot_check"]))
    proc = subprocess.run([sys.executable, str(SCRIPT), "--spot", tempfile.mkdtemp(prefix="empty-")],
                          input=json.dumps(payload), capture_output=True, text=True, check=False)
    check("пустая папка снимков → код 2 без вывода", proc.returncode == 2 and not proc.stdout, proc.stderr)


_OLD_M = "scenario-geopolitics-ru-west-2026-07-01"
_MID_M = "scenario-geopolitics-ru-west-2026-09-01"
_NEW_M = "scenario-geopolitics-ru-west-2026-11-06"


def _fc_yaml(src):
    body = "conditional_on_scenarios:\n  source_matrix: \"scenarios/%s.yaml\"\n" % src if src else "forecast: {}\n"
    return body


def _lib(matrices: dict, forecasts: dict) -> str:
    d = tempfile.mkdtemp(prefix="lib-")
    for sub, files in (("scenarios", matrices), ("forecasts", forecasts)):
        Path(d, sub).mkdir()
        for n, t in files.items():
            Path(d, sub, n).write_text(t, encoding="utf-8")
    return d


def _mfac(name="brent", ff="forecasts/f.yaml", fdate="2026-11-01", **kw):
    f = _fac(name, ff, fdate)
    f.update(kw)
    return f


def test_matrix_check():
    print("test_matrix_check")
    lib = _lib(
        {f"{_OLD_M}.yaml": f"status: superseded\nsuperseded_by: {_NEW_M}.yaml\n",
         f"{_NEW_M}.yaml": "status: active\n",
         "loop-a.yaml": "superseded_by: loop-b.yaml\n", "loop-b.yaml": "superseded_by: loop-a.yaml\n",
         "chain-1.yaml": "superseded_by: chain-2.yaml\n", "chain-2.yaml": "superseded_by: chain-3.yaml\n",
         "chain-3.yaml": "status: active\n", "plain.yaml": "status: active\n",
         "dead.yaml": "status: superseded\n"},
        {"old.yaml": _fc_yaml(_OLD_M), "new.yaml": _fc_yaml(_NEW_M), "none.yaml": _fc_yaml(None)})
    today = {"today": "2026-11-06"}

    # (а) заменённая матрица
    res = compute({**today, "factors": [_mfac(ff="forecasts/old.yaml")]}, root=lib)
    row = res["rows"][0]
    check("(а) прогноз на заменённой матрице → ⚠ STALE", row["overall_status"] == "⚠ STALE" and row["is_blocking"])
    check("(а) причина с действующей матрицей",
          f"заменённой матрице {_OLD_M}, действует {_NEW_M}" in row["stale_reason"], row["stale_reason"])
    check("(а) caveat MATRIX_REPLACED первым", row["caveats"][0].startswith("MATRIX_REPLACED:")
          and "RECALIBRATE" in row["caveats"][0])
    check("(а) summary.matrix_replaced и out.matrix",
          res["summary"]["matrix_replaced"] == ["brent"] and res["matrix"]["active"] == _NEW_M
          and res["matrix"]["replaced"] == ["brent"], str(res.get("matrix")))
    mr = res["mode_recommendation"]
    check("(а) режим FULL, recalibrate_applicable False при одном факторе",
          mr["mode"] == "FULL" and mr["recalibrate_applicable"] is False and mr["matrix_replaced"] == 1
          and mr["reason"].startswith("матрица сценариев заменена: пересобрать 1 прогноз(ов)"), str(mr))
    check("(а) счётчики после блока", res["summary"]["stale"] == 1 and res["summary"]["fresh"] == 0)

    # (б) действующая
    res = compute({**today, "factors": [_mfac(ff="forecasts/new.yaml")]}, root=lib)
    row = res["rows"][0]
    check("(б) на действующей: статус не меняется, matrix_check ok",
          row["overall_status"] == "✓ FRESH" and row["matrix_check"]["status"] == "ok"
          and res["summary"]["matrix_replaced"] == [] and res["mode_recommendation"]["mode"] == "PARTIAL"
          and "recalibrate_applicable" not in res["mode_recommendation"], str(row["matrix_check"]))

    # (в) без source_matrix
    res = compute({**today, "factors": [_mfac(ff="forecasts/none.yaml")]}, root=lib)
    check("(в) прогноз без source_matrix → нет ключа matrix_check",
          "matrix_check" not in res["rows"][0] and res["rows"][0]["overall_status"] == "✓ FRESH")

    # (г) цепочка и цикл
    mc = matrix_check({"source_matrix": "scenarios/chain-1.yaml"}, lib)
    check("(г) цепочка из двух замен → active = последняя",
          mc["status"] == "replaced" and mc["active"] == "chain-3", str(mc))
    mc = matrix_check({"source_matrix": "loop-a"}, lib)
    check("(г) цикл superseded_by не зависает", mc["status"] == "replaced" and "цикл" in " ".join(mc["notes"]), str(mc))
    mc = matrix_check({"source_matrix": "dead.yaml"}, lib)
    check("superseded без superseded_by → replaced, active None", mc["status"] == "replaced" and mc["active"] is None)
    mc = matrix_check({"source_matrix": "plain"}, lib)
    check("расширение .yaml дописывается", mc["status"] == "ok" and mc["active"] == "plain", str(mc))

    # (д) без root и полей
    res = compute({**today, "factors": [_mfac()]})
    check("(д) без root и полей → ключа matrix нет", "matrix" not in res and "matrix_check" not in res["rows"][0]
          and res["summary"]["matrix_replaced"] == [])

    # (е) payload scenario_matrix при файле без пометки
    res = compute({**today, "scenario_matrix": f"scenarios/{_NEW_M}.yaml",
                   "factors": [_mfac(source_matrix="scenarios/chain-3.yaml")]}, root=lib)
    row = res["rows"][0]
    check("(е) scenario_matrix ≠ матрица прогноза → replaced",
          row["matrix_check"]["status"] == "replaced" and row["matrix_check"]["active"] == _NEW_M
          and row["overall_status"] == "⚠ STALE" and res["matrix"]["active"] == _NEW_M, str(row["matrix_check"]))

    # (ж) FRESH-but-short
    short = _mfac(ff="forecasts/old.yaml")
    short["horizon_dates"] = ["2026-12-31"]
    res = compute({**today, "factors": [short]}, root=lib)
    check("(ж) FRESH-but-short → STALE+SHORT", res["rows"][0]["overall_status"] == "⚠ STALE+SHORT",
          res["rows"][0]["overall_status"])

    # (з) файл матрицы не найден
    res = compute({**today, "factors": [_mfac(source_matrix="scenarios/нет-такой.yaml")]}, root=lib)
    row = res["rows"][0]
    check("(з) файл матрицы не найден → unchecked, статус не меняется",
          row["matrix_check"]["status"] == "unchecked" and row["overall_status"] == "✓ FRESH"
          and res["matrix"]["unchecked"] == ["brent"], str(row["matrix_check"]))
    mc = matrix_check(_mfac(ff="forecasts/нет.yaml"), lib)
    check("нет файла прогноза → unchecked", mc["status"] == "unchecked" and "не найден" in mc["notes"][0])
    mc = matrix_check({"name": "x"}, lib)
    check("нет forecast_file → unchecked", mc["status"] == "unchecked" and "нет forecast_file" in mc["notes"][0])

    # MISSING / NOT NEEDED не проверяются
    res = compute({**today, "factors": [{"name": "m", "needed": True, "forecast_file": None,
                                         "source_matrix": "x"}]}, root=lib)
    check("MISSING не сверяется", "matrix_check" not in res["rows"][0])

    # CLI
    payload = {**today, "scenario_matrix": f"{_NEW_M}.yaml", "factors": [_mfac(ff="forecasts/old.yaml")]}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", lib], input=json.dumps(payload),
                          capture_output=True, text=True, check=False)
    out = json.loads(proc.stdout) if proc.returncode == 0 else {}
    check("CLI --root: replaced, FULL, matrix.active",
          proc.returncode == 0 and out["rows"][0]["matrix_check"]["status"] == "replaced"
          and out["mode_recommendation"]["mode"] == "FULL" and out["matrix"]["active"] == _NEW_M, proc.stderr)


def main() -> int:
    print("=" * 60)
    print("macro-forecast-chain / coverage_report.py")
    print("=" * 60)

    test_thresholds()
    test_age_status()
    test_horizon_status()
    test_evaluate_factor_fresh()
    test_evaluate_factor_missing()
    test_evaluate_factor_fresh_but_short()
    test_evaluate_factor_broken()
    test_evaluate_factor_stale()
    test_evaluate_factor_monitor_flag_ignored()
    test_evaluate_factor_no_confidence_caveat()
    test_not_needed()
    test_recommend_mode_partial()
    test_recommend_mode_quick()
    test_recommend_mode_full_missing()
    test_recommend_mode_full_many_stale()
    test_recommend_mode_full_critical()
    test_consistency_oil_rub_medium()
    test_consistency_oil_rub_critical()
    test_consistency_extreme_rate_cut()
    test_consistency_2022_pattern()
    test_consistency_clean_scenario()
    test_check_consistency_full()
    test_compute_pipeline()
    test_compute_recalibrate_mode()
    test_cli_stdin()
    test_monitor_breach_merge()
    test_monitor_breach_short_and_no_file()
    test_cli_monitor_report()
    test_spot_parse_and_load()
    test_spot_gap_signal()
    test_spot_gap_edges()
    test_spot_mutant_must_fail()
    test_cli_spot()
    test_matrix_check()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

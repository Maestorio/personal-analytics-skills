#!/usr/bin/env python3
"""
Регрессионные тесты для validate_library.py (revise-memory-remote).

Запуск из корня репозитория:
    python3 skills/revise-memory-remote/tests/test_validate_library.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "revise-memory-remote" / "scripts" / "validate_library.py"

sys.path.insert(0, str(SCRIPT.parent))
from validate_library import (  # noqa: E402
    check_pairs,
    check_status_links,
    check_triggers,
    compute,
    extract_scenario_triggers,
    find_yaml_top_level_duplicates,
    validate_audit_frontmatter,
    validate_catalyst_schema,
    validate_forecast_yaml,
    validate_index_consistency,
    validate_library_layout,
    validate_portfolio_carriers_layer,
    validate_scenario_yaml,
    validate_weekly_reviews_layer,
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


def find_issue(issues, *, category: str | None = None, file: str | None = None) -> dict | None:
    for it in issues:
        if category and it.get("category") != category:
            continue
        if file and it.get("file") != file:
            continue
        return it
    return None


# --------------------------------------------------------------------------
# Слой 1 — аудиты
# --------------------------------------------------------------------------

def test_audit_frontmatter():
    print("test_audit_frontmatter")
    # Все обязательные есть, рекомендуемые тоже.
    fm = {"source": "Stratfor", "audit_date": "2024-09-15",
          "trust": {"long-term-russia": "HIGH"},
          "period": "2010-2025", "last_updated": "2024-09-15"}
    issues = validate_audit_frontmatter("geopolitics/x.md", fm)
    check("полный frontmatter → 0 issues", len(issues) == 0,
          f"got {[i['category'] for i in issues]}")

    # Нет audit_date.
    fm2 = {"source": "Stratfor", "trust": {}}
    issues = validate_audit_frontmatter("geopolitics/x.md", fm2)
    miss = find_issue(issues, category="audit_missing_required")
    check("missing audit_date → red", miss and miss["level"] == "red",
          f"got {issues}")
    check("detail.missing содержит audit_date",
          miss and "audit_date" in (miss.get("detail") or {}).get("missing", []))

    # Нет frontmatter вообще.
    issues = validate_audit_frontmatter("geopolitics/x.md", None)
    no_fm = find_issue(issues, category="audit_no_frontmatter")
    check("no frontmatter → yellow", no_fm and no_fm["level"] == "yellow")

    # Все обязательные, но нет period.
    fm3 = {"source": "X", "audit_date": "2024-01-01", "trust": {}}
    issues = validate_audit_frontmatter("ru-macro/x.md", fm3)
    rec = find_issue(issues, category="audit_missing_recommended")
    check("missing recommended → yellow", rec and rec["level"] == "yellow")

    # source: null — ключ есть, значение null.
    fm_null = {"source": None, "audit_date": "2024-01-01", "trust": {}}
    issues = validate_audit_frontmatter("geopolitics/x.md", fm_null)
    null_issue = find_issue(issues, category="audit_missing_required")
    check("source=null → red audit_missing_required",
          null_issue and null_issue["level"] == "red")
    check("detail.missing содержит source",
          null_issue and "source" in (null_issue.get("detail") or {}).get("missing", []))


def test_index_consistency():
    print("test_index_consistency")
    real = ["a.md", "b.md", "c.md"]
    indexed = ["a.md", "c.md", "ghost.md"]
    issues = validate_index_consistency("audits", "geopolitics", real, indexed)
    dead = find_issue(issues, category="index_dead_link")
    missing = find_issue(issues, category="index_missing_entry")
    check("dead link на ghost.md", dead and "ghost.md" in dead["human_message"])
    check("b.md not in INDEX → missing entry", missing and "b.md" in missing["file"])

    # index_entries=None → пропуск проверки
    issues = validate_index_consistency("audits", "geopolitics", real, None)
    skipped = find_issue(issues, category="index_check_skipped")
    check("index_entries=None → жёлтый index_check_skipped, без dead/missing",
          skipped and skipped["level"] == "yellow"
          and not find_issue(issues, category="index_dead_link")
          and not find_issue(issues, category="index_missing_entry"))
    check("index_entries=[] → проверка выполнена, skipped нет",
          not find_issue(validate_index_consistency("audits", "g", [], []), category="index_check_skipped"))


# --------------------------------------------------------------------------
# Слой 2 — forecasts
# --------------------------------------------------------------------------

def test_pairs_md_yaml():
    print("test_pairs_md_yaml")
    md = ["a.md", "b.md", "c.md"]
    yaml = ["a.yaml", "c.yaml", "ghost.yaml"]
    issues = check_pairs("forecasts", md, yaml)
    no_yaml = find_issue(issues, category="md_without_yaml")
    orphan = find_issue(issues, category="orphan_yaml")
    check("b.md без yaml → md_without_yaml",
          no_yaml and no_yaml["file"] == "b.md")
    check("ghost.yaml orphan → red",
          orphan and orphan["level"] == "red" and orphan["file"] == "ghost.yaml")


def test_validate_forecast_yaml_full():
    print("test_validate_forecast_yaml_full")
    # Полный валидный YAML (Type 1 isolated — самый простой случай).
    good = {
        "schema_version": 1,
        "type": "forecast-events",
        "forecast_ref": "russia-2026.md",
        "status": "active",
        "forecast": {
            "date": "2026-01-30", "horizon": "2026-12-31",
            "domain": "ru-macro", "topic": "russia-2026",
        },
        "isolated": True,
        "isolated_reason": "Single-domain forecast outside of scenario matrix",
        "reviews": {"interval_months": 3, "next_due": "2026-04-30"},
        "final_audit": {"due": "2026-12-31", "status": "pending"},
        "monitoring": [{"description": "x", "auto_checkable": True}],
    }
    issues = validate_forecast_yaml("forecasts/russia-2026.yaml", good)
    check("полный YAML → 0 issues", len(issues) == 0,
          f"got {[i['category'] for i in issues]}")

    # horizon < date → red.
    bad_h = dict(good)
    bad_h["forecast"] = {**good["forecast"], "horizon": "2025-01-01"}
    issues = validate_forecast_yaml("forecasts/x.yaml", bad_h)
    h = find_issue(issues, category="horizon_before_date")
    check("horizon раньше date → red", h and h["level"] == "red")

    # forecast_ref не совпадает.
    wrong_ref = {**good, "forecast_ref": "wrong.md"}
    issues = validate_forecast_yaml("forecasts/russia-2026.yaml", wrong_ref)
    r = find_issue(issues, category="yaml_wrong_forecast_ref")
    check("forecast_ref mismatch → red", r and r["level"] == "red")

    # interval_months нестандартный.
    bad_int = {**good, "reviews": {"interval_months": 5}}
    issues = validate_forecast_yaml("forecasts/x.yaml", bad_int)
    i = find_issue(issues, category="nonstandard_interval_months")
    check("interval_months=5 → yellow", i and i["level"] == "yellow")

    # final_audit.due ≠ horizon.
    bad_fa = {**good, "final_audit": {"due": "2027-06-30", "status": "pending"}}
    issues = validate_forecast_yaml("forecasts/x.yaml", bad_fa)
    fa = find_issue(issues, category="final_audit_due_mismatch")
    check("final_audit.due mismatch → yellow", fa and fa["level"] == "yellow")

    # Нет schema_version.
    no_sv = {k: v for k, v in good.items() if k != "schema_version"}
    issues = validate_forecast_yaml("forecasts/x.yaml", no_sv)
    s = find_issue(issues, category="yaml_no_schema_version")
    check("no schema_version → yellow", s is not None)

    # Нет обязательного поля forecast.domain.
    no_dom = {**good, "forecast": {"date": "2026-01-30", "horizon": "2026-12-31",
                                    "topic": "x"}}
    issues = validate_forecast_yaml("forecasts/x.yaml", no_dom)
    f = find_issue(issues, category="yaml_missing_forecast_field")
    check("missing forecast.domain → red", f and f["level"] == "red")

    # forecast.date: null — ключ есть, значение null.
    null_date = {**good, "forecast": {**good["forecast"], "date": None}}
    issues = validate_forecast_yaml("forecasts/x.yaml", null_date)
    fn = find_issue(issues, category="yaml_missing_forecast_field")
    check("forecast.date=null → red yaml_missing_forecast_field",
          fn and fn["level"] == "red")
    check("detail.missing содержит date",
          fn and "date" in (fn.get("detail") or {}).get("missing", []))


def test_validate_forecast_type_completeness():
    """events-yaml-spec.md §5: Type 1 (isolated) vs Type 2 (conditional_on_scenarios)."""
    print("test_validate_forecast_type_completeness")
    base = {
        "schema_version": 1,
        "type": "forecast-events",
        "forecast_ref": "x.md",
        "status": "active",
        "forecast": {
            "date": "2026-01-30", "horizon": "2026-12-31",
            "domain": "ru-macro", "topic": "x",
        },
        "reviews": {"interval_months": 3, "next_due": "2026-04-30"},
        "final_audit": {"due": "2026-12-31", "status": "pending"},
    }

    # Ни isolated, ни conditional → red missing_scenario_attribution
    issues = validate_forecast_yaml("forecasts/x.yaml", base)
    miss = find_issue(issues, category="missing_scenario_attribution")
    check("ни isolated ни conditional → red", miss and miss["level"] == "red")

    # Оба сразу → red mixed_isolated_with_conditional
    both = {**base, "isolated": True, "isolated_reason": "test",
            "conditional_on_scenarios": {"by_scenario": {"A": {}, "B": {}, "C": {}, "D": {}}}}
    issues = validate_forecast_yaml("forecasts/x.yaml", both)
    mixed = find_issue(issues, category="mixed_isolated_with_conditional")
    check("оба сразу → red mixed", mixed and mixed["level"] == "red")

    # by_scenario неполный (нет C, D) → red incomplete_by_scenario
    incomplete = {**base, "conditional_on_scenarios": {
        "source_matrix": "scenarios/test-2026-05.yaml",
        "by_scenario": {"A": {}, "B": {}},
    }}
    issues = validate_forecast_yaml("forecasts/x.yaml", incomplete)
    inc = find_issue(issues, category="incomplete_by_scenario")
    check("неполный by_scenario → red", inc and inc["level"] == "red")
    check("missing содержит C и D",
          set((inc.get("detail") or {}).get("missing") or []) == {"C", "D"})

    # source_matrix без префикса scenarios/ → red invalid_source_matrix_path
    bad_path = {**base, "conditional_on_scenarios": {
        "source_matrix": "Claude-Memory/scenarios/x.yaml",
        "by_scenario": {"A": {}, "B": {}, "C": {}, "D": {}},
    }}
    issues = validate_forecast_yaml("forecasts/x.yaml", bad_path)
    bp = find_issue(issues, category="invalid_source_matrix_path")
    check("source_matrix wrong prefix → red", bp and bp["level"] == "red")

    # source_matrix указывает на несуществующий scenario → red dangling_source_matrix
    dangling = {**base, "conditional_on_scenarios": {
        "source_matrix": "scenarios/missing-2026-01-01.yaml",
        "by_scenario": {"A": {}, "B": {}, "C": {}, "D": {}},
    }}
    issues = validate_forecast_yaml(
        "forecasts/x.yaml", dangling,
        scenario_files={"existing-2026-01-01.yaml"},
    )
    d = find_issue(issues, category="dangling_source_matrix")
    check("dangling source_matrix → red", d and d["level"] == "red")

    # source_matrix существует → нет issue
    ok = {**base, "conditional_on_scenarios": {
        "source_matrix": "scenarios/existing-2026-01-01.yaml",
        "by_scenario": {"A": {}, "B": {}, "C": {}, "D": {}},
    }}
    issues = validate_forecast_yaml(
        "forecasts/x.yaml", ok,
        scenario_files={"existing-2026-01-01.yaml"},
    )
    d2 = find_issue(issues, category="dangling_source_matrix")
    check("существующий source_matrix → нет issue", d2 is None)


def test_check_triggers_dates():
    print("test_check_triggers_dates")
    today = date(2026, 5, 5)
    # final_audit.due прошёл сегодня, status pending → red, "due"
    yaml1 = {"status": "active",
             "final_audit": {"due": "2026-05-05", "status": "pending"}}
    issues = check_triggers("forecasts", "x.yaml", yaml1, today)
    f_due = find_issue(issues, category="final_audit_due")
    check("final_audit due today → red", f_due and f_due["level"] == "red")

    # final_audit.due прошёл 31 день назад → red, "overdue"
    yaml2 = {"status": "active",
             "final_audit": {"due": "2026-04-04", "status": "pending"}}
    issues = check_triggers("forecasts", "x.yaml", yaml2, today)
    f_over = find_issue(issues, category="final_audit_overdue")
    check("final_audit overdue 31 day → red", f_over and f_over["level"] == "red")
    check("days_overdue = 31",
          (f_over.get("detail") or {}).get("days_overdue") == 31)

    # final_audit.due через год → нет триггера
    yaml3 = {"status": "active",
             "final_audit": {"due": "2027-05-05", "status": "pending"}}
    issues = check_triggers("forecasts", "x.yaml", yaml3, today)
    check("final_audit в будущем → пусто", not any(
        i["category"].startswith("final_audit") for i in issues))

    # status=resolved → пропустить триггеры
    yaml_res = {"status": "resolved",
                "final_audit": {"due": "2026-04-04", "status": "pending"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_res, today)
    check("status!=active → пусто", issues == [])

    # §19 deferred: scheduled_for в будущем → НЕ предлагать expired (уважаем план)
    yaml_def_future = {"status": "active",
                       "final_audit": {"due": "2026-04-04", "status": "deferred",
                                       "scheduled_for": "2026-11-15"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_def_future, today)
    check("deferred future → нет expired-триггера", not any(
        i["category"].startswith(("final_audit", "deferred_schedule")) for i in issues))

    # deferred scheduled_for прошёл → red deferred_schedule_passed
    yaml_def_passed = {"status": "active",
                       "final_audit": {"due": "2026-04-04", "status": "deferred",
                                       "scheduled_for": "2026-04-20"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_def_passed, today)
    dp = find_issue(issues, category="deferred_schedule_passed")
    check("deferred scheduled прошёл → red", dp and dp["level"] == "red")

    # deferred без scheduled_for → yellow deferred_without_schedule
    yaml_def_nodate = {"status": "active",
                       "final_audit": {"due": "2026-04-04", "status": "deferred"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_def_nodate, today)
    dn = find_issue(issues, category="deferred_without_schedule")
    check("deferred без даты → yellow", dn and dn["level"] == "yellow")

    # next_due прошёл → yellow
    yaml_rd = {"status": "active", "reviews": {"next_due": "2026-04-30"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_rd, today)
    r = find_issue(issues, category="review_due")
    check("next_due прошёл → yellow", r and r["level"] == "yellow")

    # next_due через 5 дней → green
    yaml_soon = {"status": "active", "reviews": {"next_due": "2026-05-10"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_soon, today)
    r = find_issue(issues, category="review_due_soon")
    check("next_due через 5д → green", r and r["level"] == "green")

    # next_due через 30 дней → нет триггера
    yaml_far = {"status": "active", "reviews": {"next_due": "2026-06-04"}}
    issues = check_triggers("forecasts", "x.yaml", yaml_far, today)
    check("next_due через 30д → пусто", issues == [])


def test_check_status_links():
    print("test_check_status_links")
    files = {"a.md", "a.yaml", "audit-x.md"}

    # superseded_by на существующий
    yaml_ok = {"status": "superseded", "superseded_by": "a.md"}
    issues = check_status_links("forecasts", "x.yaml", yaml_ok, files)
    check("superseded_by → существует, нет issues", issues == [])

    # superseded_by на несуществующий
    yaml_bad = {"status": "superseded", "superseded_by": "ghost.md"}
    issues = check_status_links("forecasts", "x.yaml", yaml_bad, files)
    s = find_issue(issues, category="broken_superseded_by")
    check("battle superseded_by → red", s and s["level"] == "red")

    # resolved + audit_file отсутствует
    yaml_r = {"status": "resolved",
              "final_audit": {"audit_file": "ghost-audit.md"}}
    issues = check_status_links("forecasts", "x.yaml", yaml_r, files)
    a = find_issue(issues, category="missing_audit_file")
    check("missing audit_file → yellow", a and a["level"] == "yellow")


# --------------------------------------------------------------------------
# Слой 3 — scenarios
# --------------------------------------------------------------------------

def test_validate_scenario_yaml():
    print("test_validate_scenario_yaml")
    good = {
        "schema_version": 1,
        "type": "scenario-events",
        "scenario_ref": "iran-2027.md",
        "status": "active",
        "matrix": {
            "date": "2026-04-30", "horizon": "2027-12-31",
            "domain": "geopolitics", "topic": "iran-2027",
            "axis_x": "X", "axis_y": "Y",
        },
        "scenario_triggers": [
            {"label": "A", "probability": 0.30},
            {"label": "B", "probability": 0.25},
            {"label": "C", "probability": 0.25},
            {"label": "D", "probability": 0.20},
        ],
        "final_audit": {"due": "2027-12-31", "status": "pending"},
    }
    issues = validate_scenario_yaml("scenarios/iran-2027.yaml", good)
    check("валидный сценарий → 0 issues", len(issues) == 0,
          f"got {[i['category'] for i in issues]}")

    # Сумма probability = 0.85 (≠ 1.0)
    bad_prob = {**good, "scenario_triggers": [
        {"probability": 0.30}, {"probability": 0.25},
        {"probability": 0.20}, {"probability": 0.10},
    ]}
    issues = validate_scenario_yaml("scenarios/iran-2027.yaml", bad_prob)
    p = find_issue(issues, category="probability_sum_off")
    check("probability sum 0.85 → yellow", p and p["level"] == "yellow")
    check("detail.sum = 0.85", (p.get("detail") or {}).get("sum") == 0.85,
          f"got {p}")

    # Сумма 0.96 (в пределах ±0.05) → ОК
    near = {**good, "scenario_triggers": [
        {"probability": 0.26}, {"probability": 0.25},
        {"probability": 0.25}, {"probability": 0.20},
    ]}
    issues = validate_scenario_yaml("scenarios/iran-2027.yaml", near)
    p2 = find_issue(issues, category="probability_sum_off")
    check("probability sum 0.96 (в tolerance) → нет issue", p2 is None)

    # Только 3 сценария
    short = {**good, "scenario_triggers": [
        {"probability": 0.5}, {"probability": 0.3}, {"probability": 0.2},
    ]}
    issues = validate_scenario_yaml("scenarios/iran-2027.yaml", short)
    cnt = find_issue(issues, category="scenario_triggers_count")
    check("3 сценария вместо 4 → yellow", cnt and cnt["level"] == "yellow")

    # matrix.domain: null — ключ есть, значение null.
    null_dom = {**good, "matrix": {**good["matrix"], "domain": None}}
    issues = validate_scenario_yaml("scenarios/iran-2027.yaml", null_dom)
    mn = find_issue(issues, category="yaml_missing_matrix_field")
    check("matrix.domain=null → red yaml_missing_matrix_field",
          mn and mn["level"] == "red")
    check("detail.missing содержит domain",
          mn and "domain" in (mn.get("detail") or {}).get("missing", []))


# --------------------------------------------------------------------------
# Полный пайплайн
# --------------------------------------------------------------------------

def test_compute_pipeline():
    print("test_compute_pipeline")
    payload = {
        "today": "2026-05-05",
        "audits": {
            "geopolitics": {
                "files": [
                    {"basename": "isw-2024.md",
                     "frontmatter": {"source": "ISW", "audit_date": "2024-09-15",
                                      "trust": {}, "period": "2024",
                                      "last_updated": "2024-09-15"}},
                    {"basename": "broken.md",
                     "frontmatter": {"source": "Y"}},  # missing audit_date+trust
                ],
                "index_entries": ["isw-2024.md", "ghost.md"],
            },
        },
        "forecasts": {
            "files_md": ["russia-2026.md", "no-yaml.md"],
            "files_yaml": ["russia-2026.yaml", "orphan.yaml"],
            "files_docx": ["legacy.docx"],
            "yaml_data": {
                "russia-2026.yaml": {
                    "schema_version": 1, "type": "forecast-events",
                    "forecast_ref": "russia-2026.md", "status": "active",
                    "forecast": {"date": "2026-01-01", "horizon": "2026-12-31",
                                  "domain": "ru-macro", "topic": "russia-2026"},
                    "reviews": {"interval_months": 3, "next_due": "2026-04-01"},
                    "final_audit": {"due": "2026-12-31", "status": "pending"},
                },
                "orphan.yaml": {  # будет flagged как orphan через парность
                    "schema_version": 1, "type": "forecast-events",
                    "forecast_ref": "orphan.md", "status": "active",
                    "forecast": {"date": "2026-01-01", "horizon": "2026-06-30",
                                  "domain": "x", "topic": "y"},
                },
            },
        },
        "scenarios": {
            "files_md": ["iran-2027.md"],
            "files_yaml": ["iran-2027.yaml"],
            "yaml_data": {
                "iran-2027.yaml": {
                    "schema_version": 1, "type": "scenario-events",
                    "scenario_ref": "iran-2027.md", "status": "active",
                    "matrix": {"date": "2026-01-01", "horizon": "2027-12-31",
                               "domain": "geopolitics", "topic": "iran-2027",
                               "axis_x": "X", "axis_y": "Y"},
                    "scenario_triggers": [
                        {"probability": 0.10}, {"probability": 0.20},
                        {"probability": 0.30}, {"probability": 0.10},
                    ],
                    "final_audit": {"due": "2027-12-31", "status": "pending"},
                },
            },
        },
    }
    result = compute(payload)
    issues = result["issues"]

    # Слой 1
    check("audits_checked = 2", result["summary"]["audits_checked"] == 2)
    check("есть broken.md → audit_missing_required",
          find_issue(issues, category="audit_missing_required",
                     file="geopolitics/broken.md"))
    check("ghost.md → dead link",
          find_issue(issues, category="index_dead_link"))

    # Слой 2
    check("orphan.yaml → red",
          find_issue(issues, category="orphan_yaml", file="orphan.yaml"))
    check("no-yaml.md → md_without_yaml",
          find_issue(issues, category="md_without_yaml"))
    check("legacy.docx → docx_without_md",
          find_issue(issues, category="docx_without_md"))
    check("russia-2026 next_due прошёл → review_due",
          find_issue(issues, category="review_due", file="russia-2026.yaml"))

    # Слой 3
    check("iran probability sum 0.7 → off",
          find_issue(issues, category="probability_sum_off"))

    # Summary
    check("summary имеет red > 0", result["summary"]["red"] > 0)
    check("summary имеет yellow > 0", result["summary"]["yellow"] > 0)


def test_cli_stdin():
    print("test_cli_stdin")
    payload = {
        "today": "2026-05-05",
        "audits": {},
        "forecasts": {"files_md": ["a.md"], "files_yaml": []},
        "scenarios": {},
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("есть md_without_yaml для a.md",
          any(i["category"] == "md_without_yaml" for i in out["issues"]))


def test_duplicate_yaml_key_detection():
    """Top-level дубли YAML — issue category duplicate_yaml_key с level=red."""
    # standalone helper
    clean = "monitoring:\n  - id: a\nfalsifiers:\n  - id: b\n"
    check("clean YAML — нет дубликатов", find_yaml_top_level_duplicates(clean) == [])

    dirty = "monitoring:\n  - id: a\nmonitoring:\n  - id: b\n"
    dups = find_yaml_top_level_duplicates(dirty)
    check("два monitoring — дубликат найден", len(dups) == 1 and dups[0]["key"] == "monitoring")
    check("first_line=1", dups[0]["first_line"] == 1)
    check("duplicate_line=3", dups[0]["duplicate_line"] == 3)

    # nested duplicates (same name внутри разных контейнеров) — НЕ должны срабатывать
    nested = (
        "forecast:\n"
        "  central_estimate:\n"
        "    value: 1\n"
        "conditional_on_scenarios:\n"
        "  by_scenario:\n"
        "    A:\n"
        "      central_estimate:\n"
        "        value: 2\n"
    )
    check("nested same-name keys — не дубликат", find_yaml_top_level_duplicates(nested) == [])

    # block scalar body не путает сканер
    scalar = (
        "description: |\n"
        "  monitoring: just text\n"
        "monitoring:\n"
        "  - id: real\n"
    )
    check("block scalar body игнорируется", find_yaml_top_level_duplicates(scalar) == [])

    # Интеграция с compute() через raw_yaml в payload
    payload = {
        "today": "2026-05-11",
        "audits": {"files": {}, "frontmatters": {}},
        "forecasts": {
            "files_md": ["x.md"],
            "files_yaml": ["x.yaml"],
            "yaml_data": {
                "x.yaml": {
                    "schema_version": 1,
                    "type": "forecast-events",
                    "forecast_ref": "x.md",
                    "isolated": True,
                    "monitoring": [{"id": "z"}],
                },
            },
            "raw_yaml": {
                "x.yaml": (
                    "monitoring:\n"
                    "  - id: a\n"
                    "falsifiers:\n"
                    "  - id: b\n"
                    "monitoring:\n"
                    "  - id: c\n"
                ),
            },
            "index_entries": None,
        },
        "scenarios": {},
    }
    result = compute(payload)
    dup_issues = [i for i in result["issues"] if i["category"] == "duplicate_yaml_key"]
    check("compute() возвращает duplicate_yaml_key issue", len(dup_issues) == 1)
    check("level=red", dup_issues and dup_issues[0]["level"] == "red")
    check("layer=forecasts", dup_issues and dup_issues[0]["layer"] == "forecasts")
    check("detail содержит key и строки",
          dup_issues
          and dup_issues[0]["detail"]["key"] == "monitoring"
          and dup_issues[0]["detail"]["first_line"] == 1
          and dup_issues[0]["detail"]["duplicate_line"] == 5)

    # Scenarios layer тоже подключён к raw_yaml.
    sc_payload = {
        "today": "2026-05-11",
        "audits": {"files": {}, "frontmatters": {}},
        "forecasts": {},
        "scenarios": {
            "files_md": ["s.md"],
            "files_yaml": ["s.yaml"],
            "yaml_data": {
                "s.yaml": {
                    "schema_version": 1,
                    "type": "scenario-events",
                    "scenario_ref": "s.md",
                    "matrix": {
                        "date": "2026-05-01", "horizon": "2027-12-31",
                        "domain": "geopolitics", "topic": "x",
                        "axis_x": "y", "axis_y": "z",
                    },
                },
            },
            "raw_yaml": {
                "s.yaml": "monitoring:\n  - id: a\nmonitoring:\n  - id: b\n",
            },
            "index_entries": None,
        },
    }
    sc_result = compute(sc_payload)
    sc_dup = [i for i in sc_result["issues"]
              if i["category"] == "duplicate_yaml_key" and i["layer"] == "scenarios"]
    check("scenarios layer ловит duplicate_yaml_key", len(sc_dup) == 1)


# --------------------------------------------------------------------------
# Слой 4 — weekly-reviews catalyst kind (METH-1, 2026-05-13)
# --------------------------------------------------------------------------

SC_IDS = {"Sc-A", "Sc-B", "Sc-C", "Sc-D"}


def test_catalyst_schema_validation():
    print("\n[Слой 4] catalyst kind schema (METH-1)")

    # 1. Legacy без kind — yellow
    items = validate_catalyst_schema(
        {"id": "c1", "p": 0.5, "upside_pct": 10, "macro_dependency": "Sc-A"},
        SC_IDS, "per_stock.X.catalyst[0]"
    )
    check("legacy без kind → catalyst_missing_kind (yellow)",
          any(i["category"] == "catalyst_missing_kind" and i["level"] == "yellow" for i in items))

    # 2. Invalid kind — red
    items = validate_catalyst_schema(
        {"id": "c2", "kind": "weird", "p": 0.5, "upside_pct": 10},
        SC_IDS, "per_stock.X.catalyst[0]"
    )
    check("invalid kind → catalyst_invalid_kind (red)",
          any(i["category"] == "catalyst_invalid_kind" and i["level"] == "red" for i in items))

    # 3. Binary без p — red
    items = validate_catalyst_schema(
        {"id": "c3", "kind": "binary", "upside_pct": 10}, SC_IDS, "p.X.c[0]"
    )
    check("binary без p → catalyst_binary_missing_p",
          any(i["category"] == "catalyst_binary_missing_p" for i in items))

    # 4. Binary с p вне диапазона — red
    items = validate_catalyst_schema(
        {"id": "c4", "kind": "binary", "p": 0.99, "upside_pct": 10},
        SC_IDS, "p.X.c[0]"
    )
    check("binary с p=0.99 → catalyst_binary_p_out_of_range",
          any(i["category"] == "catalyst_binary_p_out_of_range" for i in items))

    # 5. Quantitative без upside_by_scenario — red
    items = validate_catalyst_schema(
        {"id": "c5", "kind": "quantitative"}, SC_IDS, "p.X.c[0]"
    )
    check("quant без upside_by_scenario → catalyst_quantitative_missing_scenarios",
          any(i["category"] == "catalyst_quantitative_missing_scenarios" for i in items))

    # 6. Quantitative c p — yellow warning
    items = validate_catalyst_schema(
        {"id": "c6", "kind": "quantitative", "p": 0.5,
         "upside_by_scenario": {"Sc-A": 1, "Sc-B": 1, "Sc-C": 1, "Sc-D": 1}},
        SC_IDS, "p.X.c[0]"
    )
    check("quant с p → catalyst_quantitative_has_p (yellow)",
          any(i["category"] == "catalyst_quantitative_has_p" and i["level"] == "yellow" for i in items))

    # 7. Quantitative с unknown scenario_id — red
    items = validate_catalyst_schema(
        {"id": "c7", "kind": "quantitative",
         "upside_by_scenario": {"Sc-A": 1, "Sc-X_unknown": 5}},
        SC_IDS, "p.X.c[0]"
    )
    check("quant с unknown ID → catalyst_scenario_id_unknown",
          any(i["category"] == "catalyst_scenario_id_unknown" for i in items))

    # 8. Quantitative с пропущенными сценариями — yellow
    items = validate_catalyst_schema(
        {"id": "c8", "kind": "quantitative",
         "upside_by_scenario": {"Sc-A": 10, "Sc-B": 5}},
        SC_IDS, "p.X.c[0]"
    )
    check("quant с пропущ. сценариями → catalyst_quantitative_incomplete_scenarios",
          any(i["category"] == "catalyst_quantitative_incomplete_scenarios" for i in items))

    # 9. Binary с активными сценариями — unknown ID
    items = validate_catalyst_schema(
        {"id": "c9", "kind": "binary", "p": 0.5, "upside_pct": 10,
         "active_scenarios": ["Sc-A", "Sc-Z_legacy"]},
        SC_IDS, "p.X.c[0]"
    )
    check("binary с unknown active_scenarios → catalyst_scenario_id_unknown",
          any(i["category"] == "catalyst_scenario_id_unknown" for i in items))

    # 10. Чистый binary без проблем — no issues
    items = validate_catalyst_schema(
        {"id": "ok_bin", "kind": "binary", "p": 0.8, "upside_pct": 5,
         "upside_ci_pct": [2, 8], "macro_dependency": None},
        SC_IDS, "p.X.c[0]"
    )
    check("чистый binary → no issues", len(items) == 0,
          detail=f"got {len(items)} issues" if items else "")

    # 11. Чистый quantitative без проблем
    items = validate_catalyst_schema(
        {"id": "ok_quant", "kind": "quantitative",
         "upside_by_scenario": {"Sc-A": 18, "Sc-B": 10, "Sc-C": 10, "Sc-D": 0}},
        SC_IDS, "p.X.c[0]"
    )
    check("чистый quantitative → no issues", len(items) == 0,
          detail=f"got {len(items)} issues" if items else "")

    # 12. Integration: validate_weekly_reviews_layer на полном payload
    payload = {
        "weekly_reviews": {
            "files_yaml": ["wr.yaml"],
            "yaml_data": {
                "wr.yaml": {
                    "per_stock": {
                        "SBER": {
                            "catalyst": [
                                {"id": "rc", "kind": "quantitative",
                                 "upside_by_scenario": {"Sc-A": 18, "Sc-B": 10, "Sc-C": 10, "Sc-D": 0}},
                                {"id": "div", "kind": "binary", "p": 0.88, "upside_pct": 3,
                                 "macro_dependency": None},
                            ]
                        }
                    }
                }
            }
        },
        # Форма РЕАЛЬНОГО SSOT: список со `scenario_id` на верхнем уровне (все
        # шесть живых матриц) либо под `matrix` (спека §1.1). До 2026-08-05 здесь
        # стоял mapping `{"Sc-A": {}}` — формы, которой нет ни там, ни там: тест
        # обслуживал реализацию, а та на живых файлах не извлекала НИ ОДНОГО id
        # и молча отключала кросс-проверку macro_dependency.
        "scenarios": {
            "yaml_data": {
                "sc.yaml": {
                    "matrix": {
                        "scenario_triggers": [
                            {"scenario_id": "Sc-A"}, {"scenario_id": "Sc-B"},
                            {"scenario_id": "Sc-C"}, {"scenario_id": "Sc-D"},
                        ]
                    }
                }
            }
        }
    }
    issues, summary = validate_weekly_reviews_layer(payload)
    check("integration: clean SBER catalysts → 0 issues",
          len(issues) == 0,
          detail=f"got {[i['category'] for i in issues]}" if issues else "")
    check("integration: summary contains weekly_reviews_yaml=1",
          summary["weekly_reviews_yaml"] == 1)

    # 13. Compute() integration — пайплайн целиком
    full = {
        "today": "2026-05-13",
        "audits": {"files": {}, "frontmatters": {}},
        "forecasts": {},
        "scenarios": payload["scenarios"],
        "weekly_reviews": payload["weekly_reviews"],
    }
    result = compute(full)
    check("compute() pipeline включает weekly_reviews_yaml",
          result["summary"].get("weekly_reviews_yaml") == 1)

    # 14. Bond ytm-санити (Баг #1B): ytm_pct > 100 → yellow bond_ytm_implausible
    bond_payload = {
        "weekly_reviews": {
            "files_yaml": ["wrb.yaml"],
            "yaml_data": {
                "wrb.yaml": {
                    "per_bond": {
                        "RU000A106EP1": {"ytm_pct": 414.11, "coupon_pct": 18.0,
                                         "offer_date": "2026-06-15", "catalyst": []},
                        "RU000GOOD": {"ytm_pct": 18.0, "catalyst": []},
                    }
                }
            }
        }
    }
    b_issues, _ = validate_weekly_reviews_layer(bond_payload)
    ytm_flags = [i for i in b_issues if i["category"] == "bond_ytm_implausible"]
    check("bond ytm 414% → ровно 1 bond_ytm_implausible (yellow)",
          len(ytm_flags) == 1 and ytm_flags[0]["level"] == "yellow",
          detail=f"got {[(i['category'], i['level']) for i in b_issues]}")
    check("bond ytm 18% (правдоподобный) не флагается",
          all("RU000GOOD" not in (i.get("human_message") or "") for i in ytm_flags))

    # 15. v2-формат weekly-review (Phase 4): horizon-поля + catalyst без in_horizon.
    #     validate_library горизонт/версию для weekly не читает → валидирует как раньше.
    v2_payload = {
        "weekly_reviews": {
            "files_yaml": ["wr-v2.yaml"],
            "yaml_data": {
                "wr-v2.yaml": {
                    "schema_version": 2,
                    "horizons": [12, 20, 36],
                    "horizon_ends": {"h12": "2027-05-31", "h20": "2028-01-31", "h36": "2029-05-31"},
                    "primary_horizon": 20,
                    "per_stock": {
                        "SBER": {"catalyst": [
                            {"id": "div", "kind": "binary", "p": 0.88, "upside_pct": 3,
                             "date_window": "2026-07", "macro_dependency": None},
                        ]}
                    },
                }
            }
        },
        "scenarios": payload["scenarios"],
    }
    v2_issues, v2_summary = validate_weekly_reviews_layer(v2_payload)
    check("v2 weekly-review (horizons + нет in_horizon) → 0 issues (формат-агностично)",
          len(v2_issues) == 0,
          detail=f"got {[i['category'] for i in v2_issues]}" if v2_issues else "")


# --------------------------------------------------------------------------
# Слой 5 — Носители портфельной схемы (решения, условия + состояние, справочник бумаг)
# --------------------------------------------------------------------------

def _dec(key, rec, review_by=None, verdict="HOLD"):
    did = f"{rec[:10]}T{rec[11:13]}{rec[14:16]}-{key}"
    return f"{did}.json", {
        "schema_version": "decision@1", "id": did, "key": key, "verdict": verdict, "target_pct": 5.0,
        "review_by": review_by, "note": "одна фраза почему", "conditions_created": [], "conditions_resolved": [],
        "source": {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None},
        "author": "owner", "recorded_at": rec}


def _cond(cid, key="AAAA"):
    return {"id": cid, "version": 1, "key": key, "kind": "trade", "trigger": {"type": "price_below", "value": 100},
            "event_text": None, "while_pending": {"verdict": "HOLD", "text": "ждём"},
            "on_trigger": {"action": "set_verdict", "verdict": "TRIM", "text": "срезать до плана"},
            "on_expiry": None, "not_before": None, "valid_until": None, "note": "почему создано",
            "context": None, "source": {"kind": "owner", "doc": None}, "created_at": "2026-10-01T10:00:00+03:00",
            "created_by": "owner", "withdrawn": None, "superseded_by": None}


def _attr(cls="bluechip"):
    return {"ticker_class": cls, "listed_at": None, "note": None,
            "updated_at": "2026-10-31T12:00:00+03:00", "updated_by": "script"}


def _carriers_ok():
    n1, d1 = _dec("AAAA", "2026-10-01T10:00:00+03:00", review_by="2026-10-20")  # старое — срок не важен
    n2, d2 = _dec("AAAA", "2026-10-25T09:30:00+03:00", review_by="2026-12-01")
    return {
        "decisions": {n1: d1, n2: d2},
        "conditions": {"schema_version": "conditions@2", "conditions": [_cond("px-a")]},
        "conditions_archive": [{"schema_version": "conditions@2", "conditions": [_cond("c-old", "BBBB")]}],
        "conditions_state": {"schema_version": "conditions-state@1", "events": [
            {"condition_id": "px-a", "event": "fired", "at": "2026-10-27T11:00:00+03:00", "by": "notifier", "data": {}},
            {"condition_id": "c-old", "event": "done", "at": "2026-10-05T12:01:00+03:00", "by": "owner",
             "data": {"note": "сделано"}}]},
        "security_attrs": {"schema_version": "security-attrs@1", "by_key": {"AAAA": _attr(), "BBBB": _attr(None)}},
        "snapshot_keys": ["AAAA", "BBBB", "JPM"],
        "blocked_keys": ["JPM"],
    }


def test_portfolio_carriers_clean_and_empty():
    print()
    print("Слой 5 — носители схемы / чистый набор и пустой payload")
    today = date(2026, 10, 31)
    issues, summary = validate_portfolio_carriers_layer({}, today)
    check("пустой payload → 0 issues", issues == [])
    check("пустой payload → нулевая сводка", summary["carriers_decisions"] == 0 and summary["carriers_with_issues"] == 0)

    issues, summary = validate_portfolio_carriers_layer({"portfolio_carriers": _carriers_ok()}, today)
    check("валидный набор → 0 issues (старое решение с прошедшим сроком не текущее; событие архивного условия"
          " находит определение; замороженная бумага не требует записи)", issues == [],
          detail=str([i["category"] for i in issues]))
    check("сводка: 2 решения, 1 ключ, 1 условие, 2 события, 2 записи справочника",
          (summary["carriers_decisions"], summary["carriers_decision_keys"], summary["carriers_conditions"],
           summary["carriers_state_events"], summary["carriers_security_attrs"]) == (2, 1, 1, 2, 2),
          detail=str(summary))

    full = compute({"today": "2026-10-31", "portfolio_carriers": _carriers_ok()})
    check("compute() несёт сводку слоя и не несёт gate_reviews",
          full["summary"].get("carriers_decisions") == 2 and "gate_reviews_tickers" not in full["summary"])
    legacy = compute({"today": "2026-10-31", "gate_reviews": {"ssot_data": {"tickers": {}}}})
    check("старый ключ gate_reviews в payload игнорируется", legacy["summary"]["total_issues"] == 0)


def test_portfolio_carriers_findings():
    print()
    print("Слой 5 — носители схемы / находки")
    today = date(2026, 10, 31)
    pc = _carriers_ok()
    # 1. Текущее решение с прошедшим review_by → жёлтый.
    n3, d3 = _dec("BBBB", "2026-08-01T12:00:00+03:00", review_by="2026-10-30")
    pc["decisions"][n3] = d3
    # 2. Невалидное решение (вердикт не из кодлиста) → красный; имя ≠ id → красный.
    nb, db = _dec("CCCC", "2026-10-02T10:00:00+03:00")
    db["verdict"] = "MAYBE"
    pc["decisions"][nb] = db
    nm, dm = _dec("DDDD", "2026-10-03T10:00:00+03:00")
    pc["decisions"]["wrong-name.json"] = dm
    # 3. Событие без определения → красный.
    pc["conditions_state"]["events"].append(
        {"condition_id": "ghost", "event": "fired", "at": "2026-10-28T11:00:00+03:00", "by": "notifier", "data": {}})
    # 4. Бумага снапшота без записи справочника → жёлтый.
    pc["snapshot_keys"].append("RU000A105XX1")
    issues, summary = validate_portfolio_carriers_layer({"portfolio_carriers": pc}, today)
    cats = {(i["category"], i["level"]) for i in issues}

    it = find_issue(issues, category="ds_decision_review_overdue")
    check("прошедший review_by у текущего решения → yellow", it is not None and it["level"] == "yellow"
          and it["detail"]["key"] == "BBBB" and it["file"] == f"decisions/{n3}")
    check("срок прошёл только у одного ключа", sum(1 for i in issues if i["category"] == "ds_decision_review_overdue") == 1)
    it = find_issue(issues, category="ds_decision_invalid")
    check("невалидное решение → red с ошибкой verdict", it is not None and it["level"] == "red"
          and any(e.startswith("verdict") for e in it["detail"]["errors"]))
    check("имя файла ≠ id → red", ("ds_decision_name_mismatch", "red") in cats
          and find_issue(issues, category="ds_decision_name_mismatch")["file"] == "decisions/wrong-name.json")
    it = find_issue(issues, category="ds_state_orphan_event")
    check("событие без определения → red", it is not None and it["level"] == "red" and "ghost" in it["human_message"])
    it = find_issue(issues, category="ds_security_attrs_missing")
    check("бумага снапшота без записи → yellow (замороженная JPM не в счёт)", it is not None and it["level"] == "yellow"
          and it["detail"]["key"] == "RU000A105XX1"
          and sum(1 for i in issues if i["category"] == "ds_security_attrs_missing") == 1)
    check("все issues слоя — portfolio_carriers", all(i["layer"] == "portfolio_carriers" for i in issues))

    # 5. Неверный формат файлов → red по каждому носителю.
    bad = {"decisions": {}, "conditions": {"schema_version": "conditions@1", "conditions": []},
           "conditions_state": {"schema_version": "conditions-state@1", "events": [], "last_checked_at": "x"},
           "security_attrs": {"schema_version": "security-attrs@1",
                              "by_key": {"AAAA": dict(_attr(), ticker_class="giant")}}}
    issues, _ = validate_portfolio_carriers_layer({"portfolio_carriers": bad}, today)
    for cat in ("ds_conditions_invalid", "ds_state_invalid", "ds_security_attrs_invalid"):
        it = find_issue(issues, category=cat)
        check(f"{cat} → red", it is not None and it["level"] == "red", detail=str([i["category"] for i in issues]))
    check("conditions формата 1 ловится по schema_version",
          any("conditions@2" in e for e in find_issue(issues, category="ds_conditions_invalid")["detail"]["errors"]))


# ---------------------------------------------------------------------------
# Слой 6 — Library layout (deprecated dirs / dup markers / profile suffix)
# ---------------------------------------------------------------------------

def test_library_layout_deprecated_dirs():
    print("test_library_layout_deprecated_dirs")
    payload = {
        "library_layout": {
            "deprecated_dirs": {
                "_audits": ["fursov-2020-2024-audit", "rebuild-plan-2026-05-11.md"],
                "audits": ["2026-05-15-izborsk-2022-2023.md"],
            },
        },
    }
    issues, summary = validate_library_layout(payload)
    check("3 файла в deprecated → 3 issue",
          summary["library_layout_deprecated_files"] == 3)
    check("_audits/fursov flagged",
          find_issue(issues, category="deprecated_directory_file",
                     file="_audits/fursov-2020-2024-audit") is not None)
    check("audits/izborsk flagged",
          find_issue(issues, category="deprecated_directory_file",
                     file="audits/2026-05-15-izborsk-2022-2023.md") is not None)
    check("все deprecated → red",
          all(i["level"] == "red" for i in issues
              if i["category"] == "deprecated_directory_file"))


def test_library_layout_dup_markers():
    print("test_library_layout_dup_markers")
    payload = {
        "library_layout": {
            "dup_marker_files": [
                "_sync_log (1).md",
                "_sync_log (2).md",
                "_sync_log_append_2026-05-15-zhirinovsky.md",
                {"path": "domains/geopolitics/INDEX (1).md"},
                "_sync_log.md",  # clean — must be ignored
                "INDEX.md",       # clean — must be ignored
            ],
        },
    }
    issues, summary = validate_library_layout(payload)
    check("4 dup-markers → 4 issue", summary["library_layout_dup_markers"] == 4)
    check("_sync_log (1).md flagged",
          find_issue(issues, category="dup_marker_file", file="_sync_log (1).md") is not None)
    check("_sync_log_append-* flagged",
          find_issue(issues, category="dup_marker_file",
                     file="_sync_log_append_2026-05-15-zhirinovsky.md") is not None)
    check("INDEX (1).md flagged",
          find_issue(issues, category="dup_marker_file",
                     file="domains/geopolitics/INDEX (1).md") is not None)
    check("чистый _sync_log.md НЕ flagged",
          find_issue(issues, file="_sync_log.md") is None)
    check("все dup-markers → red",
          all(i["level"] == "red" for i in issues
              if i["category"] == "dup_marker_file"))


def test_library_layout_profile_audit_suffix():
    print("test_library_layout_profile_audit_suffix")
    payload = {
        "library_layout": {
            "domains": {
                "geopolitics": [
                    "fursov-2020-2024-audit.md",     # bad
                    "zhirinovsky-1991-2022.md",      # OK
                    "carnegie-2010-2016.md",         # OK
                    "stratfor-2015-2025-audit.md",   # bad
                ],
                "ru-macro": [
                    "vtb-2024.md",                   # OK
                ],
            },
        },
    }
    issues, summary = validate_library_layout(payload)
    check("2 файла с -audit → 2 issue",
          summary["library_layout_profile_suffix"] == 2)
    check("fursov-...-audit flagged",
          find_issue(issues, category="profile_audit_suffix",
                     file="domains/geopolitics/fursov-2020-2024-audit.md") is not None)
    check("stratfor-...-audit flagged",
          find_issue(issues, category="profile_audit_suffix",
                     file="domains/geopolitics/stratfor-2015-2025-audit.md") is not None)
    check("zhirinovsky НЕ flagged",
          find_issue(issues, file="domains/geopolitics/zhirinovsky-1991-2022.md") is None)
    check("все -audit → yellow",
          all(i["level"] == "yellow" for i in issues
              if i["category"] == "profile_audit_suffix"))


def test_library_layout_clean_payload():
    print("test_library_layout_clean_payload")
    payload = {
        "library_layout": {
            "deprecated_dirs": {"_audits": [], "audits": []},
            "dup_marker_files": ["_sync_log.md", "INDEX.md"],
            "domains": {"geopolitics": ["carnegie-2010-2016.md"]},
        },
    }
    issues, summary = validate_library_layout(payload)
    check("чистый payload → 0 issues", len(issues) == 0)
    check("чистый payload → все summary = 0",
          summary["library_layout_deprecated_files"] == 0
          and summary["library_layout_dup_markers"] == 0
          and summary["library_layout_profile_suffix"] == 0)


def test_library_layout_compute_integration():
    print("test_library_layout_compute_integration")
    payload = {
        "today": "2026-05-16",
        "audits": {},
        "library_layout": {
            "deprecated_dirs": {"_audits": ["x.md"]},
            "dup_marker_files": ["_sync_log (1).md"],
            "domains": {"geopolitics": ["foo-2020-2024-audit.md"]},
        },
    }
    result = compute(payload)
    check("compute() включает library_layout_deprecated_files в summary",
          result["summary"].get("library_layout_deprecated_files") == 1)
    check("compute() включает library_layout_dup_markers в summary",
          result["summary"].get("library_layout_dup_markers") == 1)
    check("compute() включает library_layout_profile_suffix в summary",
          result["summary"].get("library_layout_profile_suffix") == 1)
    check("compute() прибавляет library_layout issues в общий список",
          any(i["layer"] == "library_layout" for i in result["issues"]))
    check("compute() red counter учитывает library_layout",
          result["summary"]["red"] >= 2)


def test_outcome_capture_sweep():
    print("test_outcome_capture_sweep")
    today = date(2026, 7, 6)

    def cats(y):
        return [i["category"] for i in check_triggers("forecasts", "f.yaml", y, today)]

    # superseded, горизонт прошёл, НЕТ outcome_log → outcome_uncaptured
    check("superseded passed no-log → outcome_uncaptured",
          cats({"status": "superseded", "forecast": {"horizon": "2026-05-31"}}) == ["outcome_uncaptured"])

    # superseded, горизонт будущий → пусто
    check("superseded future horizon → пусто",
          cats({"status": "superseded", "forecast": {"horizon": "2028-06-30"}}) == [])

    # superseded, outcome_log зафиксирован → пусто
    check("superseded filled → пусто",
          cats({"status": "superseded", "forecast": {"horizon": "2026-05-31"},
                "outcome_log": [{"resolve_date": "2026-05-31", "kind": "event", "resolved": 1}]}) == [])

    # expired с прошедшей fca_stats-точкой → outcome_uncaptured
    check("expired fca_stats passed → outcome_uncaptured",
          cats({"status": "expired", "fca_stats": {"2026-06-19": {"kind": "event"}}}) == ["outcome_uncaptured"])

    # resolved → пусто (уже отаудирован)
    check("resolved → пусто (skip)",
          cats({"status": "resolved", "forecast": {"horizon": "2026-05-31"}}) == [])

    # уровневый стаб не заполнен (actual=null) → capture
    check("superseded level-стаб actual=null → capture",
          cats({"status": "superseded",
                "outcome_log": [{"resolve_date": "2026-05-31", "kind": "level", "actual": None}]}) == ["outcome_uncaptured"])

    # свип — yellow (не блокирует; revise предлагает, save-to-library пишет)
    issues = check_triggers("forecasts", "f.yaml",
                            {"status": "superseded", "forecast": {"horizon": "2026-05-31"}}, today)
    check("outcome_uncaptured уровень yellow", issues and issues[0]["level"] == "yellow")
    check("detail несёт resolve_dates_unfilled",
          issues and "2026-05-31" in (issues[0].get("detail") or {}).get("resolve_dates_unfilled", []))

    # legacy fca_stats-ключ ('horizon_2026_12_31') не роняет свип (безопасный parse)
    check("legacy fca_stats-ключ не падает",
          cats({"status": "superseded", "fca_stats": {"horizon_2026_12_31": {"kind": "level"}}}) == [])


def test_scenario_triggers_extraction() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Единая точка чтения `scenario_triggers` — и она обязана читать
    РЕАЛЬНЫЙ формат.

    Две половины валидатора разошлись: проверка полноты матрицы читала верхний
    уровень и работала, а сборщик scenario_ids смотрел только под `matrix` и
    обходил блок как mapping — на каждой живой матрице получал пусто и МОЛЧА
    отключал кросс-проверку macro_dependency у weekly-обзоров. Реализация,
    читающая только `matrix`, падает на первой же проверке ниже.
    """
    print("\ntest_scenario_triggers_extraction")
    top = {"scenario_triggers": [{"scenario_id": "A", "probability": 0.25}]}
    check("верхний уровень (форма живых файлов)",
          [t["scenario_id"] for t in extract_scenario_triggers(top)] == ["A"])
    inm = {"matrix": {"scenario_triggers": [{"scenario_id": "B"}]}}
    check("под `matrix` (форма спеки §1.1)",
          [t["scenario_id"] for t in extract_scenario_triggers(inm)] == ["B"])
    check("верхний приоритетнее",
          [t["scenario_id"] for t in extract_scenario_triggers(
              {**top, **inm})] == ["A"])
    check("нет блока → пусто, без падения", extract_scenario_triggers({}) == [])
    check("не-dict → пусто", extract_scenario_triggers(None) == [])

    # Отключённая кросс-проверка обязана быть слышна.
    payload = {
        "weekly_reviews": {"files_yaml": ["wr.yaml"], "yaml_data": {
            "wr.yaml": {"per_stock": {"SBER": {"catalyst": [
                {"id": "c", "kind": "binary", "p": 0.5, "upside_pct": 3,
                 "macro_dependency": "Sc-A"}]}}}}},
        "scenarios": {"yaml_data": {"sc.yaml": {"matrix": {"axes": []}}}},
    }
    issues, _ = validate_weekly_reviews_layer(payload)
    check("scenario-файлы есть, id не извлеклись → предупреждение, а не тишина",
          any(i["category"] == "scenario_ids_not_extracted" for i in issues),
          str([i["category"] for i in issues]))
    # Совсем без scenarios-слоя молчим: кросс-чек не заказывали.
    quiet, _ = validate_weekly_reviews_layer(
        {k: v for k, v in payload.items() if k != "scenarios"})
    check("без scenarios-слоя предупреждения нет",
          not any(i["category"] == "scenario_ids_not_extracted" for i in quiet))

    # Живые матрицы: id обязаны извлечься из каждой. PyYAML импортируется здесь,
    # а не в шапке: сам валидатор stdlib-only (YAML ему подаёт LLM), и тест не
    # должен превращать это в зависимость.
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        print("  [SKIP] PyYAML недоступен — проверка на живых матрицах пропущена")
        return
    scen_dir = (Path.home() / "Library/CloudStorage/SynologyDrive-home"
                / "Claude-Memory/scenarios")
    files = sorted(scen_dir.glob("*.yaml")) if scen_dir.exists() else []
    if not files:
        print("  [SKIP] живые матрицы недоступны (нет Claude-Memory)")
        return
    bad = []
    top_level = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        ids = [t.get("scenario_id") for t in extract_scenario_triggers(data)]
        if sorted(x for x in ids if x) != ["A", "B", "C", "D"]:
            bad.append((f.name, ids))
        if isinstance(data, dict) and isinstance(data.get("scenario_triggers"), list):
            top_level.append(f.name)
    check(f"все {len(files)} живых матриц дают A/B/C/D", not bad, str(bad))
    check(f"все {len(files)} живых матриц кладут блок на ВЕРХНИЙ уровень",
          len(top_level) == len(files), str(sorted(set(f.name for f in files) - set(top_level))))

    # ── Дрейф спеки против реальности ────────────────────────────────────
    # Источник трёх молчаливых дефектов (recalibrate.load_weights,
    # validate_library scenario_ids и фикстуры обоих) — не код, а СПЕКА:
    # до 2026-08-05 §1.1 показывала блок под `matrix`, где его нет ни в одном
    # артефакте и куда его не кладёт генератор. Каждый новый читатель имел
    # шанс написать неверно и не заметить. Тест пришпиливает три стороны:
    # спека ↔ шаблон генератора ↔ живые файлы.
    spec = REPO_ROOT / "_shared-references" / "scenario-yaml-spec.md"
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        sect = text.split("### 1.1")[1].split("\n## ")[0] if "### 1.1" in text else ""
        blocks = re.findall(r"```yaml\n(.*?)```", sect, re.S)
        parsed = yaml.safe_load(blocks[0]) if blocks else None
        check("спека §1.1: блок на верхнем уровне, списком",
              isinstance(parsed, dict) and isinstance(parsed.get("scenario_triggers"), list),
              f"got {sorted(parsed) if isinstance(parsed, dict) else parsed}")
        ids = [t.get("scenario_id") for t in (parsed or {}).get("scenario_triggers", [])]
        check("спека §1.1: пример даёт A/B/C/D",
              sorted(x for x in ids if x) == ["A", "B", "C", "D"], str(ids))
    sb = REPO_ROOT / "skills" / "scenario-builder" / "SKILL.md"
    if sb.exists():
        check("шаблон scenario-builder пишет блок на верхний уровень",
              re.search(r"^scenario_triggers:$", sb.read_text(encoding="utf-8"), re.M)
              is not None)


def main() -> int:
    print("=" * 60)
    print("revise-memory-remote / validate_library.py")
    print("=" * 60)

    test_audit_frontmatter()
    test_index_consistency()
    test_pairs_md_yaml()
    test_validate_forecast_yaml_full()
    test_validate_forecast_type_completeness()
    test_check_triggers_dates()
    test_check_status_links()
    test_validate_scenario_yaml()
    test_compute_pipeline()
    test_cli_stdin()
    test_duplicate_yaml_key_detection()
    test_catalyst_schema_validation()
    test_portfolio_carriers_clean_and_empty()
    test_portfolio_carriers_findings()
    test_library_layout_deprecated_dirs()
    test_library_layout_dup_markers()
    test_library_layout_profile_audit_suffix()
    test_library_layout_clean_payload()
    test_library_layout_compute_integration()
    test_outcome_capture_sweep()
    test_scenario_triggers_extraction()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

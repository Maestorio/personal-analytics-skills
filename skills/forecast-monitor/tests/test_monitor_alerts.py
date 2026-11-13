#!/usr/bin/env python3
"""
Регрессионные тесты для monitor_alerts.py.

Запуск из корня репозитория:
    python3 skills/forecast-monitor/tests/test_monitor_alerts.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "forecast-monitor" / "scripts" / "monitor_alerts.py"

sys.path.insert(0, str(SCRIPT.parent))
from monitor_alerts import (  # noqa: E402
    assign_priority,
    build_search_query,
    build_web_search_plan,
    catalyst_to_monitoring,
    classify_by_date,
    compute,
    compute_search_from_date,
    parse_window_end,
    portfolio_position_watch,
    post_filter_event,
    process_forecast,
    review_window_days,
    _process_weekly_review_catalysts,
    _process_condition_events,
    condition_findings_template,
    _alerts_outcome_capture,
    compute_calibration_milestones,
    CAL_M1_MIN_CLEAN,
    CAL_M2_MIN_ADHOC,
    CAL_M3_MIN_CLEAN,
    CAL_M4_MIN_CATALYST,
    CAL_REPEAT_DAYS,
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


def test_classify_by_date():
    print("test_classify_by_date")
    today = date(2026, 5, 5)
    # Просрочено на 5 дней — всегда red, независимо от окна.
    cls = classify_by_date(date(2026, 4, 30), today, 7)
    check("overdue → red", cls["severity"] == "red", f"got {cls}")
    check("overdue label содержит 5 дней", "5" in cls["label"], f"got {cls['label']}")
    check("days_delta = -5", cls["days_delta"] == -5)

    # delta=7 — на границе окна, попадает в red
    cls = classify_by_date(date(2026, 5, 12), today, 7)
    check("delta=7 → red (граница окна включительно)", cls["severity"] == "red")

    # delta=8 — за окном → none (никаких yellow «приближается»)
    cls = classify_by_date(date(2026, 5, 13), today, 7)
    check("delta=8 → none (yellow upcoming убран)", cls["severity"] == "none",
          f"got {cls}")

    # delta=14 — далеко → none
    cls = classify_by_date(date(2026, 5, 19), today, 7)
    check("delta=14 → none", cls["severity"] == "none")

    # Узкое окно: delta=5, n_window=5 → red; delta=6 с n_window=5 → none
    cls = classify_by_date(date(2026, 5, 10), today, 5)
    check("узкое окно: delta=5, n=5 → red", cls["severity"] == "red")
    cls = classify_by_date(date(2026, 5, 11), today, 5)
    check("узкое окно: delta=6, n=5 → none", cls["severity"] == "none")

    # None → none
    cls = classify_by_date(None, today, 7)
    check("None target → none", cls["severity"] == "none")


def test_review_window_days():
    print("test_review_window_days")
    check("interval_months=1 → ±5", review_window_days(1) == 5)
    check("interval_months=3 → ±7", review_window_days(3) == 7)
    check("interval_months=12 → ±7", review_window_days(12) == 7)
    check("interval_months=None → ±7 (default)", review_window_days(None) == 7)
    check("interval_months=2 → ±7", review_window_days(2) == 7)


def test_compute_search_from_date():
    print("test_compute_search_from_date")
    fd = date(2026, 4, 30)
    check("без last_completed → forecast_date",
          compute_search_from_date(fd, None) == fd)
    check("last_completed раньше → forecast_date",
          compute_search_from_date(fd, date(2026, 4, 1)) == fd)
    check("last_completed позже → last_completed",
          compute_search_from_date(fd, date(2026, 5, 2)) == date(2026, 5, 2))


def test_post_filter_event():
    print("test_post_filter_event")
    sf = date(2026, 4, 30)
    check("event раньше → drop",
          post_filter_event(date(2026, 4, 15), sf) == "drop")
    check("event ровно равен → keep",
          post_filter_event(date(2026, 4, 30), sf) == "keep")
    check("event позже → keep",
          post_filter_event(date(2026, 5, 3), sf) == "keep")
    check("None → undefined",
          post_filter_event(None, sf) == "undefined")


def test_process_forecast_review_overdue():
    print("test_process_forecast_review_overdue")
    f = {
        "basename": "brent.yaml",
        "type": "forecast-events",
        "status": "active",
        "topic": "brent-price",
        "forecast_date": "2026-01-30",
        "reviews": {"interval_months": 3, "next_due": "2026-04-30",
                    "last_completed": None},
    }
    today = date(2026, 5, 10)
    res = process_forecast(f, today, 7)
    check("выбран search_from = forecast_date",
          res["search_from_date"] == "2026-01-30")
    check("есть review-алерт", any(a["kind"] == "review" for a in res["alerts"]))
    review_alert = next(a for a in res["alerts"] if a["kind"] == "review")
    check("review просрочен → red", review_alert["severity"] == "red")
    check("days_delta = -10", review_alert["days_delta"] == -10)
    check("review_window_days = 7 (interval_months=3)",
          review_alert["review_window_days"] == 7)


def test_horizon_passed_beats_review():
    print("test_horizon_passed_beats_review")
    base = {"basename": "usd.yaml", "type": "forecast-events", "status": "active",
            "forecast_date": "2026-04-30",
            "reviews": {"interval_months": 3, "next_due": "2026-07-30", "last_completed": None}}
    today = date(2026, 10, 29)
    res = process_forecast({**base, "horizon": "2026-09-01"}, today, 7)
    kinds = [a["kind"] for a in res["alerts"]]
    check("horizon_passed есть", "horizon_passed" in kinds)
    check("review подавлен", "review" not in kinds)
    hp = next(a for a in res["alerts"] if a["kind"] == "horizon_passed")
    check("метка ГОРИЗОНТ, 58 дн.", hp["type_label"] == "ГОРИЗОНТ" and hp["days_delta"] == -58)
    res = process_forecast({**base, "horizons": ["2026-09-01", "2026-12-31"]}, today, 7)
    check("сетка: последний горизонт впереди → review остаётся",
          [a["kind"] for a in res["alerts"] if a["kind"] in ("review", "horizon_passed")] == ["review"])
    res = process_forecast({**base, "horizons": ["2026-03-31", "2026-09-01"]}, today, 7)
    check("сетка: последний прошёл → horizon_passed",
          any(a["kind"] == "horizon_passed" for a in res["alerts"]))
    res = process_forecast({**base, "horizon": "2026-12-31"}, today, 7)
    check("горизонт впереди → review", any(a["kind"] == "review" for a in res["alerts"])
          and not any(a["kind"] == "horizon_passed" for a in res["alerts"]))


def test_review_monthly_narrow_window():
    """interval_months=1 → окно ±5 дней."""
    print("test_review_monthly_narrow_window")
    today = date(2026, 5, 5)
    base = {
        "basename": "x.yaml", "type": "forecast-events", "status": "active",
        "forecast_date": "2026-04-01",
        "reviews": {"interval_months": 1, "next_due": "2026-05-10"},  # delta=5
    }
    res = process_forecast(base, today, 7)
    review = next((a for a in res["alerts"] if a["kind"] == "review"), None)
    check("interval=1, delta=5 → red (на границе ±5)",
          review and review["severity"] == "red")
    check("review_window_days = 5", review and review["review_window_days"] == 5)

    # delta=6 при interval=1 → за окном → нет алерта
    f = {**base, "reviews": {"interval_months": 1, "next_due": "2026-05-11"}}
    res = process_forecast(f, today, 7)
    check("interval=1, delta=6 → нет review-алерта (за окном ±5)",
          not any(a["kind"] == "review" for a in res["alerts"]))


def test_process_forecast_full():
    """Новая логика: симметричные окна, без 'yellow upcoming'."""
    print("test_process_forecast_full")
    today = date(2026, 5, 5)
    f = {
        "basename": "brent-oil-dec-2026-2026-04-30.yaml",
        "type": "forecast-events",
        "status": "active",
        "topic": "brent-price",
        "domain": "global-banks",
        "horizon": "2026-12-31",
        "forecast_date": "2026-04-30",
        "reviews": {"next_due": "2026-07-30", "last_completed": None},
        "deadlines": [
            {"description": "OPEC meeting", "date": "2026-05-12",
             "action": "review impact"},   # delta=7, в окне
            {"description": "Conf far", "date": "2026-05-20",
             "action": "noop"},            # delta=15, за окном — молчим
        ],
        "monitoring": [
            {"description": "Brent below trigger", "threshold": "Brent < $60",
             "check_date": "2026-05-15", "auto_checkable": True,
             "severity": "critical", "impact": "invalidates"},   # delta=10, за окном
            {"description": "manual indicator", "threshold": "indirect signal",
             "check_date": "2026-05-12", "auto_checkable": False,
             "severity": "medium"},                              # delta=7, в окне
        ],
        "thresholds": [
            {"variable": "Urals discount", "condition": ">$15",
             "auto_checkable": True, "flips_to": "Sc-B"},
        ],
        "falsifiers": [
            {"description": "OPEC коллапс", "auto_checkable": True,
             "would_resolve": True},
            {"description": "manual falsifier", "auto_checkable": False},
        ],
    }
    res = process_forecast(f, today, 7)
    kinds = [a["kind"] for a in res["alerts"]]

    check("review NOT in alerts (next_due далеко)", "review" not in kinds)

    deadline_alerts = [a for a in res["alerts"] if a["kind"] == "deadline"]
    check("есть 1 deadline в окне (через 7 дней)", len(deadline_alerts) == 1,
          f"got {len(deadline_alerts)}")
    check("дальний deadline (15 дней) НЕ алертится",
          all("Conf far" not in (a.get("description") or "") for a in deadline_alerts))
    check("deadline severity = red", deadline_alerts[0]["severity"] == "red")

    monitoring_alerts = [a for a in res["alerts"] if a["kind"] == "monitoring"]
    check("monitoring critical через 10 дней (за окном) — молчит",
          all("Brent below" not in (a.get("description") or "")
              for a in monitoring_alerts),
          f"got {[a.get('description') for a in monitoring_alerts]}")
    check("manual monitoring через 7 дней (в окне) — алерт",
          any("manual indicator" in (a.get("description") or "")
              for a in monitoring_alerts))

    check("threshold (auto_checkable) есть",
          any(a["kind"] == "threshold" for a in res["alerts"]))
    check("falsifier (auto_checkable) есть",
          any(a["kind"] == "falsifier" for a in res["alerts"]))
    falsifier_count = sum(1 for a in res["alerts"] if a["kind"] == "falsifier")
    check("falsifier (manual, auto_checkable=false) пропущен",
          falsifier_count == 1, f"got {falsifier_count}")


def test_monitoring_overdue_severity():
    """Просроченный monitoring: critical → red, иначе → yellow."""
    print("test_monitoring_overdue_severity")
    today = date(2026, 5, 5)
    f = {
        "basename": "x.yaml", "type": "forecast-events", "status": "active",
        "forecast_date": "2026-04-01",
        "monitoring": [
            {"description": "crit", "check_date": "2026-04-25",
             "auto_checkable": True, "severity": "critical"},
            {"description": "med", "check_date": "2026-04-25",
             "auto_checkable": True, "severity": "medium"},
        ],
    }
    res = process_forecast(f, today, 7)
    crit = next(a for a in res["alerts"] if "crit" in (a.get("description") or ""))
    med = next(a for a in res["alerts"] if "med" in (a.get("description") or ""))
    check("просроченный critical → red", crit["severity"] == "red")
    check("просроченный medium → yellow", med["severity"] == "yellow")


def test_monitoring_checked_template():
    """FM-20: у алерта monitoring — monitoring_id из файла; заготовка monitoring_checked — каждый пункт с прошедшей
    датой (и ручной auto_checkable: false), без будущих и без неактивных файлов."""
    print("test_monitoring_checked_template")
    payload = {
        "today": "2026-11-03",
        "forecasts": [
            {"basename": "cbr-2026-10-20.yaml", "type": "forecast-events", "status": "active",
             "topic": "cbr", "forecast_date": "2026-10-20",
             "monitoring": [
                 {"id": "auto-past", "check_date": "2026-10-23", "auto_checkable": True},
                 {"id": "manual-past", "check_date": "2026-10-22", "auto_checkable": False},
                 {"id": "today", "check_date": "2026-11-03", "auto_checkable": True},
                 {"id": "soon", "check_date": "2026-11-06", "auto_checkable": True},
             ]},
            {"basename": "sc-2026-05-01.yaml", "type": "scenario-events", "status": "active",
             "topic": "sc", "forecast_date": "2026-05-01",
             "monitoring": [{"id": "sc-past", "check_date": "2026-09-30", "auto_checkable": False}]},
            {"basename": "old-2026-04-01.yaml", "type": "forecast-events", "status": "superseded",
             "topic": "old", "forecast_date": "2026-04-01",
             "monitoring": [{"id": "old-past", "check_date": "2026-05-01", "auto_checkable": True}]},
        ],
    }
    out = compute(payload)
    mons = [a for f in out["active_files"] for a in f["alerts"] if a["kind"] == "monitoring"]
    check("у каждого алерта monitoring есть monitoring_id из файла",
          sorted(a.get("monitoring_id") for a in mons) == ["auto-past", "manual-past", "sc-past", "soon", "today"],
          str([a.get("monitoring_id") for a in mons]))
    tpl = out.get("monitoring_checked") or []
    ids = [(r["target_file"], r["monitoring_id"]) for r in tpl]
    check("заготовка: прошедшие и сегодняшние пункты активных файлов, ручной — тоже",
          ids == [("forecasts/cbr-2026-10-20.yaml", "auto-past"), ("forecasts/cbr-2026-10-20.yaml", "manual-past"),
                  ("forecasts/cbr-2026-10-20.yaml", "today"), ("scenarios/sc-2026-05-01.yaml", "sc-past")], str(ids))
    manual = next(r for r in tpl if r["monitoring_id"] == "manual-past")
    check("строка заготовки — поля схемы monitoring_checked, result пуст",
          set(manual) == {"target", "target_file", "monitoring_id", "check_date", "result", "note"}
          and manual["target"] == "cbr" and manual["check_date"] == "2026-10-22" and manual["result"] is None,
          str(manual))
    malert = next(a for a in mons if a["monitoring_id"] == "manual-past")
    check("ручной пункт с прошедшей датой — в выводе, без web_search",
          malert["auto_checkable"] is False and malert["needs_web_search"] is False)
    # прогноз с прошедшим горизонтом: пункты покрывает алерт horizon_passed отчёта — в заготовку они не идут
    payload["forecasts"].append(
        {"basename": "closed-2026-10-01.yaml", "type": "forecast-events", "status": "active",
         "topic": "closed", "forecast_date": "2026-10-01", "horizon": "2026-10-23",
         "monitoring": [{"id": "c-past", "check_date": "2026-10-20", "auto_checkable": True}]})
    out = compute(payload)
    closed = next(f for f in out["active_files"] if f["basename"] == "closed-2026-10-01.yaml")
    check("горизонт прошёл: алерт horizon_passed есть, пункт мониторинга — алертом",
          closed["horizon_passed"] and any(a["kind"] == "horizon_passed" for a in closed["alerts"])
          and any(a.get("monitoring_id") == "c-past" for a in closed["alerts"]))
    check("горизонт прошёл: пункты прогноза в заготовку monitoring_checked не идут",
          all(r["target_file"] != "forecasts/closed-2026-10-01.yaml" for r in out["monitoring_checked"])
          and len(out["monitoring_checked"]) == 4, str(out["monitoring_checked"]))


def test_assign_priority():
    print("test_assign_priority")
    processed = [
        {"basename": "a.yaml", "alerts": [{"severity": "red"}, {"severity": "yellow"}]},
        {"basename": "b.yaml", "alerts": [{"severity": "yellow"}]},
        {"basename": "c.yaml", "alerts": []},
        {"basename": "d.yaml", "skipped": "status=resolved"},
    ]
    p = assign_priority(processed)
    check("a → red", p["red"] == ["a.yaml"], f"got {p['red']}")
    check("b → yellow", p["yellow"] == ["b.yaml"], f"got {p['yellow']}")
    check("c → white", p["white"] == ["c.yaml"], f"got {p['white']}")
    check("d пропущен (skipped)",
          "d.yaml" not in p["red"] + p["yellow"] + p["white"])


def test_build_search_query():
    print("test_build_search_query")
    sf = "2026-04-30"
    q = build_search_query({"kind": "monitoring", "description": "Brent below",
                            "threshold": "<$60"}, sf)
    check("monitoring query содержит after:date", f"after:{sf}" in q)
    check("monitoring query содержит описание", "Brent below" in q)

    q = build_search_query({"kind": "threshold", "variable": "Urals",
                            "condition": ">$15"}, sf)
    check("threshold query содержит variable+condition",
          "Urals" in q and "$15" in q and f"after:{sf}" in q)

    q = build_search_query({"kind": "falsifier", "description": "OPEC коллапс"}, sf)
    check("falsifier query содержит описание", "OPEC коллапс" in q)


def test_build_web_search_plan_limit():
    print("test_build_web_search_plan_limit")
    processed = [
        {
            "basename": f"f{i}.yaml",
            "search_from_date": "2026-04-30",
            "alerts": [
                {"kind": "monitoring", "severity": "red",
                 "severity_tier": "critical", "needs_web_search": True,
                 "description": f"event {i}", "threshold": "X"},
                {"kind": "monitoring", "severity": "yellow",
                 "severity_tier": "medium", "needs_web_search": True,
                 "description": f"low priority {i}", "threshold": "Y"},
            ],
        }
        for i in range(8)
    ]
    plan = build_web_search_plan(processed, max_searches=10)
    check("scheduled = 10", len(plan["scheduled"]) == 10, f"got {len(plan['scheduled'])}")
    check("deferred = 6", len(plan["deferred"]) == 6, f"got {len(plan['deferred'])}")
    check("total candidates = 16", plan["total_candidates"] == 16)
    # Все red+critical должны попасть в scheduled (8 штук)
    red_in_scheduled = sum(1 for c in plan["scheduled"] if c["severity"] == "red")
    check("все red попали в scheduled", red_in_scheduled == 8,
          f"got {red_in_scheduled}")


def test_no_stale_flags_freshness_by_dates():
    """R15 (шаг 14): файла флагов устаревания нет — свежесть по датам самого прогноза, горизонт ставит скрипт."""
    print("test_no_stale_flags_freshness_by_dates")
    import monitor_alerts as ma
    check("каскада stale_flags в модуле нет", not hasattr(ma, "compute_stale_flags"))
    base = {"basename": "f.yaml", "type": "forecast-events", "status": "active",
            "forecast_date": "2026-04-30"}
    res = compute({"today": "2026-05-05", "forecasts": [dict(base, horizon="2026-05-01")],
                   "pierced_events": [{"topic": "brent-price", "severity": "critical"}],
                   "dependency_map": {"downstream": {"brent-price": ["usdrub-rate"]}}})
    check("в выходе нет stale_flags (входы пробоя игнорируются)", "stale_flags" not in res)
    row = res["active_files"][0]
    check("строка файла: horizon_date из прогноза", row["horizon_date"] == "2026-05-01")
    check("строка файла: horizon_passed = true", row["horizon_passed"] is True)
    check("алерт horizon_passed — тот же признак",
          [a["kind"] for a in row["alerts"]].count("horizon_passed") == 1)
    fut = compute({"today": "2026-05-05", "forecasts": [dict(base, horizons=["2026-12-31", "2027-12-31"])]})
    r2 = fut["active_files"][0]
    check("сетка horizons[] → последняя дата", r2["horizon_date"] == "2027-12-31" and r2["horizon_passed"] is False)
    nohz = compute({"today": "2026-05-05", "forecasts": [base]})["active_files"][0]
    check("без горизонта — None/false", nohz["horizon_date"] is None and nohz["horizon_passed"] is False)


def test_compute_full_pipeline():
    print("test_compute_full_pipeline")
    payload = {
        "today": "2026-05-05",
        "n_red_days": 7,
        "n_yellow_days": 14,
        "max_web_searches": 3,
        "forecasts": [
            {
                "basename": "active.yaml",
                "type": "forecast-events",
                "status": "active",
                "topic": "brent-price",
                "forecast_date": "2026-04-30",
                "reviews": {"next_due": "2026-05-10"},
                "monitoring": [
                    {"description": "trigger", "threshold": "<$60",
                     "check_date": "2026-05-08", "auto_checkable": True,
                     "severity": "critical", "impact": "invalidates"},
                ],
            },
            {
                "basename": "resolved.yaml",
                "type": "forecast-events",
                "status": "resolved",
                "forecast_date": "2026-01-01",
            },
            {
                "basename": "wrong.yaml",
                "type": "audit-events",
                "forecast_date": "2026-04-01",
            },
        ],
        "pierced_events": [
            {"topic": "brent-price", "severity": "critical",
             "reason": "test"}
        ],
        "dependency_map": {
            "downstream": {"brent-price": ["usdrub-rate"]}
        },
    }
    res = compute(payload)
    check("active.yaml processed", res["files_processed"] == 1)
    check("resolved + wrong skipped", len(res["files_skipped"]) == 2)
    check("active в red bucket",
          "active.yaml" in res["priority_buckets"]["red"])
    check("web_search plan не пустой",
          len(res["web_search_plan"]["scheduled"]) >= 1)
    check("stale_flags в выходе нет (упразднён, R15)", "stale_flags" not in res)


def test_cli_compute_stdin():
    print("test_cli_compute_stdin")
    payload = {
        "today": "2026-05-05",
        "forecasts": [{
            "basename": "x.yaml",
            "type": "forecast-events",
            "status": "active",
            "forecast_date": "2026-04-30",
            "reviews": {"next_due": "2026-05-09"},
        }],
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("active_files len = 1", len(out["active_files"]) == 1)


def test_cli_post_filter():
    print("test_cli_post_filter")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "post-filter",
         "--search-from", "2026-04-30", "--event-date", "2026-04-15"],
        capture_output=True, text=True, check=False,
    )
    check("drop → exit 1", proc.returncode == 1)
    check("stdout содержит 'drop'", proc.stdout.strip() == "drop")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "post-filter",
         "--search-from", "2026-04-30", "--event-date", "2026-05-01"],
        capture_output=True, text=True, check=False,
    )
    check("keep → exit 0", proc.returncode == 0)
    check("stdout содержит 'keep'", proc.stdout.strip() == "keep")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "post-filter",
         "--search-from", "2026-04-30"],
        capture_output=True, text=True, check=False,
    )
    check("без event-date → undefined", proc.stdout.strip() == "undefined")
    check("undefined → exit 1", proc.returncode == 1)


def test_parse_window_end():
    print("test_parse_window_end")
    from datetime import date as d
    # "X to Y" — берём правую часть
    check("Q range → конец Q2", parse_window_end("2026-Q4 to 2027-Q2") == d(2027, 6, 30))
    # Одиночный квартал
    check("Q4 → Dec31", parse_window_end("2026-Q4") == d(2026, 12, 31))
    check("Q1 → Mar31", parse_window_end("2027-Q1") == d(2027, 3, 31))
    check("Q3 → Sep30", parse_window_end("2026-Q3") == d(2026, 9, 30))
    # Месяц
    check("2026-06 → Jun30", parse_window_end("2026-06") == d(2026, 6, 30))
    check("2027-02 → Feb28", parse_window_end("2027-02") == d(2027, 2, 28))
    # Год
    check("2026 → Dec31", parse_window_end("2026") == d(2026, 12, 31))
    # any → review_date + 6 мес
    rd = d(2026, 6, 9)
    result = parse_window_end("any", rd)
    check("any → review_date + 6 мес", result == d(2026, 12, 9))
    check("any без review_date → None", parse_window_end("any") is None)
    # Мусор / None
    check("мусор → None", parse_window_end("неизвестно") is None)
    check("None → None", parse_window_end(None) is None)
    check("пусто → None", parse_window_end("") is None)
    # Нижний регистр "q"
    check("строчный q4 → Dec31", parse_window_end("2026-q4") == d(2026, 12, 31))


def test_catalyst_to_monitoring():
    print("test_catalyst_to_monitoring")
    from datetime import date as d
    rd = d(2026, 5, 1)
    base = {
        "auto_checkable": True,
        "in_horizon": True,
        "date_window": "2027-Q1",
        "trigger": "ROE восстановление",
        "p": 0.6,
        "upside_pct": 20,
        "source_quality": "HIGH",
    }
    m = catalyst_to_monitoring(base, "SBER", rd)
    check("check_date вычислен", m is not None and m["check_date"] == d(2027, 3, 31))
    check("impact=supports для upside", m["impact"] == "supports")
    check("severity=high (HIGH + p≥0.5)", m["severity"] == "high")
    check("description = trigger", m["description"] == "ROE восстановление")

    # auto_checkable=False → None
    c2 = {**base, "auto_checkable": False}
    check("auto_checkable=False → None", catalyst_to_monitoring(c2, "SBER", rd) is None)

    # in_horizon=False → None
    c3 = {**base, "in_horizon": False}
    check("in_horizon=False → None", catalyst_to_monitoring(c3, "SBER", rd) is None)

    # downside + малый p → critical + invalidates
    c4 = {**base, "downside_pct": 40, "upside_pct": None, "p": 0.15}
    m4 = catalyst_to_monitoring(c4, "SBER", rd)
    check("downside small p → critical", m4 is not None and m4["severity"] == "critical")
    check("downside → invalidates", m4["impact"] == "invalidates")

    # Нет check_date (date_window=мусор) → None
    c5 = {**base, "date_window": "неизвестно"}
    check("нет check_date → None", catalyst_to_monitoring(c5, "SBER", rd) is None)

    # check_what используется как threshold
    c6 = {**base, "check_what": "Q3 МСФО ROE ≥ 12%"}
    m6 = catalyst_to_monitoring(c6, "SBER", rd)
    check("check_what → threshold", m6 is not None and m6["threshold"] == "Q3 МСФО ROE ≥ 12%")

    # medium: LOW quality + p<0.5
    c7 = {**base, "source_quality": "LOW", "p": 0.4}
    m7 = catalyst_to_monitoring(c7, "SBER", rd)
    check("LOW + p<0.5 → medium", m7 is not None and m7["severity"] == "medium")


def test_process_weekly_review_catalysts():
    print("test_process_weekly_review_catalysts")
    from datetime import date as d
    today = d(2026, 6, 9)
    items = [
        {
            "ticker": "SBER",
            "review_date": "2026-06-01",
            "catalyst": {
                "auto_checkable": True,
                "in_horizon": True,
                "date_window": "2026-Q1",  # Q1 ends Mar31, уже просрочен при today=Jun9
                "trigger": "ROE восстановление",
                "p": 0.6,
                "upside_pct": 20,
                "source_quality": "HIGH",
            },
        },
        {
            "ticker": "SBER",
            "review_date": "2026-06-01",
            "catalyst": {
                "auto_checkable": True,
                "in_horizon": True,
                "date_window": "2030-Q4",  # далеко вперёд — вне окна
                "trigger": "Дальний катализатор",
                "p": 0.5,
                "upside_pct": 10,
                "source_quality": "MEDIUM",
            },
        },
    ]
    result = _process_weekly_review_catalysts(items, today, n_red=7)
    check("одна синтетическая запись для SBER", len(result) == 1)
    entry = result[0]
    check("basename содержит sber", "sber" in entry["basename"])
    check("один алерт (дальний вне окна)", len(entry["alerts"]) == 1)
    alert = entry["alerts"][0]
    check("kind=catalyst", alert["kind"] == "catalyst")
    check("severity=red (просрочен)", alert["severity"] == "red")
    check("ticker пробрасывается", alert["ticker"] == "SBER")
    check("needs_web_search=True", alert["needs_web_search"] is True)

    # auto_checkable=False → алерт без web_search
    items2 = [{
        "ticker": "LKOH",
        "review_date": "2026-06-01",
        "catalyst": {
            "auto_checkable": False,
            "in_horizon": True,
            "date_window": "2026-Q2",
            "trigger": "Нечекируемый",
            "p": 0.5,
            "upside_pct": 15,
            "source_quality": "LOW",
        },
    }]
    result2 = _process_weekly_review_catalysts(items2, today, n_red=7)
    check("auto_checkable=False → нет записей", len(result2) == 0)


def test_compute_with_catalysts():
    print("test_compute_with_catalysts")
    from datetime import date as d
    today = d(2026, 6, 9)
    payload = {
        "today": "2026-06-09",
        "n_red_days": 7,
        "forecasts": [],
        "weekly_review_catalysts": [
            {
                "ticker": "SBER",
                "review_date": "2026-06-01",
                "catalyst": {
                    "auto_checkable": True,
                    "in_horizon": True,
                    "date_window": "2026-Q1",  # Q1 ends Mar31, просрочен → red
                    "trigger": "ROE восстановление",
                    "p": 0.6,
                    "upside_pct": 20,
                    "source_quality": "HIGH",
                },
            }
        ],
    }
    result = compute(payload)
    active = result["active_files"]
    check("синтетическая запись попала в active_files", len(active) == 1)
    check("basename содержит sber", "sber" in active[0]["basename"])
    check("red-алерт в результате", any(
        a["severity"] == "red" for a in active[0]["alerts"]
    ))
    check("SBER в priority red", any(
        "sber" in b for b in result["priority_buckets"]["red"]
    ))
    # Катализатор вне окна → нет алертов → нет в active_files
    payload2 = {
        "today": "2026-06-09",
        "forecasts": [],
        "weekly_review_catalysts": [
            {
                "ticker": "LKOH",
                "review_date": "2026-06-01",
                "catalyst": {
                    "auto_checkable": True,
                    "in_horizon": True,
                    "date_window": "2030-Q4",  # далеко — вне окна
                    "trigger": "Дальний",
                    "p": 0.5,
                    "upside_pct": 10,
                    "source_quality": "MEDIUM",
                },
            }
        ],
    }
    result2 = compute(payload2)
    check("дальний катализатор не даёт записей", len(result2["active_files"]) == 0)


def test_build_search_query_catalyst():
    print("test_build_search_query_catalyst")
    alert = {
        "kind": "catalyst",
        "ticker": "SBER",
        "description": "ROE recovery",
        "threshold": "Q3 ROE ≥ 12%",
    }
    q = build_search_query(alert, "2026-05-01")
    check("query содержит тикер", "SBER" in q)
    check("query содержит описание", "ROE recovery" in q)
    check("query содержит after:", "after:2026-05-01" in q)


def test_outcome_capture():
    """F7 — детерминированный outcome_capture (self-audit gap: монитор детектил резолв,
    но факт в outcome_log не клал)."""
    TODAY = date(2026, 7, 6)

    def oc(fc):
        return _alerts_outcome_capture(fc, TODAY)

    # iran-like: horizon прошёл, НЕТ outcome_log → 1 capture, red, 36 дн.
    a = oc({"horizon": "2026-05-31", "central_estimate": "перемирие"})
    check("F7 horizon прошёл без outcome_log → capture", len(a) == 1)
    check("F7 severity red", a and a[0]["severity"] == "red")
    check("F7 days_delta = 36", a and a[0]["days_delta"] == 36)
    check("F7 needs_web_search", a and a[0]["needs_web_search"] is True)
    check("F7 resolve_date проброшен", a and a[0]["resolve_date"] == "2026-05-31")

    # filled outcome_log (event resolved) → 0
    a = oc({"horizon": "2026-05-31",
            "outcome_log": [{"resolve_date": "2026-05-31", "kind": "event", "resolved": 1}]})
    check("F7 filled event → нет capture", a == [])

    # filled level (actual) → 0
    a = oc({"horizon": "2026-05-31",
            "outcome_log": [{"resolve_date": "2026-05-31", "kind": "level", "actual": 13.0}]})
    check("F7 filled level → нет capture", a == [])

    # будущий horizon → 0
    check("F7 будущий horizon → нет capture", oc({"horizon": "2028-06-30"}) == [])

    # незаполненный стаб (actual=null) при будущем horizon → capture по стабу
    a = oc({"horizon": "2028-06-30",
            "outcome_log": [{"resolve_date": "2026-05-31", "kind": "level", "actual": None}]})
    check("F7 незаполненный стаб → capture", len(a) == 1 and a[0]["resolve_date"] == "2026-05-31")

    # fca_stats event-дата прошла, нет filled → capture с outcome_kind=event
    a = oc({"horizon": "2028-06-30",
            "fca_stats": {"2026-06-19": {"kind": "event", "predicted_p": 0.6}}})
    check("F7 fca_stats event-дата → capture event", len(a) == 1 and a[0]["outcome_kind"] == "event")

    # несколько резолв-точек, часть заполнена → capture только по незаполненным
    a = oc({"horizon": "2028-06-30",
            "outcome_log": [
                {"resolve_date": "2026-05-31", "kind": "event", "resolved": 1},   # filled
                {"resolve_date": "2026-06-30", "kind": "level", "actual": None},  # unfilled
            ]})
    check("F7 частичное заполнение → 1 capture", len(a) == 1 and a[0]["resolve_date"] == "2026-06-30")

    # через process_forecast → попадает в alerts + red bucket + web_search_plan
    payload = {"today": "2026-07-06", "n_red_days": 7, "n_yellow_days": 14, "max_web_searches": 10,
               "forecasts": [{"basename": "iran.yaml", "type": "forecast-events", "status": "active",
                              "forecast_date": "2026-04-30", "horizon": "2026-05-31",
                              "central_estimate": "перемирие удержится"}]}
    r = compute(payload)
    kinds = [al["kind"] for al in r["active_files"][0]["alerts"]]
    check("F7 в process_forecast alerts", "outcome_capture" in kinds)
    check("F7 в red bucket", "iran.yaml" in r["priority_buckets"]["red"])
    plan_kinds = [p["kind"] for p in r["web_search_plan"]["scheduled"]]
    check("F7 в web_search_plan", "outcome_capture" in plan_kinds)

    # build_search_query для outcome_capture
    q = build_search_query({"kind": "outcome_capture", "description": "перемирие",
                            "resolve_date": "2026-05-31"}, "2026-04-30")
    check("F7 query содержит resolve_date + факт", q is not None and "2026-05-31" in q and "факт" in q)

    # legacy fca_stats-ключ ('horizon_2026_12_31') не роняет захват (безопасный parse)
    check("F7 legacy fca_stats-ключ не падает",
          oc({"horizon": "2028-06-30", "fca_stats": {"horizon_2026_12_31": {"kind": "level"}}}) == [])


def _cal_forecast(entries: list[dict], ftype: str = "forecast-events",
                  status: str = "superseded") -> dict:
    return {"basename": "f.yaml", "type": ftype, "status": status,
            "forecast_date": "2026-01-01", "outcome_log": entries}


def _clean_entry(**over) -> dict:
    e = {"resolve_date": "2026-05-31", "record_type": "horizon_resolve",
         "kind": "level", "actual": 80.0, "shock_flag": "none"}
    e.update(over)
    return e


def test_portfolio_position_watch():
    """
    Санкционное событие должно само напоминать о пересборке `sanctions_position`:
    таблица позиций — слепок статуса эмитентов на дату, и её устаревание незаметно,
    потому что числа остаются правдоподобными.
    """
    print("test_portfolio_position_watch")
    fired = {"basename": "sanctions-russia-2026-28-2026-07-01.yaml",
             "domain": "geopolitics", "topic": "sanctions-russia-2026-28",
             "alerts": [{"kind": "monitoring", "severity": "red"}]}
    quiet = {"basename": "sanctions-russia-2026-28-2026-07-01.yaml",
             "domain": "geopolitics", "topic": "sanctions-russia-2026-28",
             "alerts": [{"kind": "review", "severity": "white"}]}
    other = {"basename": "brent-price-2026.yaml", "domain": "commodities",
             "topic": "brent-2026", "alerts": [{"kind": "deadline", "severity": "red"}]}

    w = portfolio_position_watch([fired])
    check("санкционный алерт → сторож сработал", w is not None)
    check("назван источник", bool(w and w["sources"][0]["basename"].startswith("sanctions")))
    check("указана рубрика, а не просто «подумать»",
          bool(w and w["rubric"].endswith("sanctions-position-rubric.md")))
    check("белый алерт не будит", portfolio_position_watch([quiet]) is None)
    check("чужой домен не будит", portfolio_position_watch([other]) is None)
    check("пропущенный файл не ломает",
          portfolio_position_watch([{"skipped": "no_forecast_date"}]) is None)
    # распознавание по теме, когда домен назван иначе
    by_topic = {"basename": "geopolitics-ru-west.yaml", "domain": "macro",
                "topic": "санкционный режим", "alerts": [{"kind": "threshold",
                                                          "severity": "yellow"}]}
    check("распознаётся по теме, не только по домену",
          portfolio_position_watch([by_topic]) is not None)
    check("в compute-выводе поле есть",
          "portfolio_watch" in compute({"today": "2026-08-04", "forecasts": []}))


def test_calibration_milestones():
    print("test_calibration_milestones (сторож M1–M4)")
    today = date(2026, 7, 6)
    cal = compute_calibration_milestones

    # Пустая библиотека → нулевые счётчики, ничего не сработало, progress_line есть
    r = cal([], [], today)
    check("пусто: n_clean=0", r["counts"]["n_clean"] == 0)
    check("пусто: alerts пустые", r["alerts"] == [])
    check("пусто: progress_line содержит пороги",
          f"0/{CAL_M1_MIN_CLEAN}" in r["progress_line"] and f"0/{CAL_M2_MIN_ADHOC}" in r["progress_line"])
    check("пусто: M4 н/д без catalyst_resolved", "н/д" in r["progress_line"])
    check("пусто: 4 milestone-записи", [m["id"] for m in r["milestones"]] == ["M1", "M2", "M3", "M4"])

    # Правила зачёта clean: interim / shock / незаполненные — вне зачёта
    entries = [
        _clean_entry(),                                                    # clean level
        _clean_entry(kind="event", actual=None, resolved=1,
                     predicted_p=0.45),                                    # clean event
        _clean_entry(record_type="interim_supersession"),                  # interim
        _clean_entry(shock_flag="exogenous_shock"),                        # shock
        _clean_entry(actual=None),                                         # незаполненный стаб
        _clean_entry(record_type=None),                                    # нет record_type → horizon_resolve
    ]
    r = cal([_cal_forecast(entries)], [], today)
    c = r["counts"]
    check("зачёт: n_clean=3 (level+event+без record_type)", c["n_clean"] == 3, f"got {c}")
    check("зачёт: level/event разрез", c["n_clean_level"] == 2 and c["n_clean_event"] == 1)
    check("зачёт: interim отдельно", c["n_interim"] == 1)
    check("зачёт: shock отдельно", c["n_shock_excluded"] == 1)
    check("зачёт: pending стаб отдельно", c["n_pending_stubs"] == 1)
    check("зачёт: вне зачёта в progress_line", "вне зачёта" in r["progress_line"])

    # scenario-events и не-dict записи не считаются
    r = cal([_cal_forecast([_clean_entry()], ftype="scenario-events"),
             _cal_forecast(["мусор", None])], [], today)
    check("scenario-events не считается", r["counts"]["n_clean"] == 0)

    # superseded/expired/active — все статусы считаются
    r = cal([_cal_forecast([_clean_entry()], status="expired"),
             _cal_forecast([_clean_entry()], status="active")], [], today)
    check("expired+active оба в зачёте", r["counts"]["n_clean"] == 2)

    # M1: порог достигнут, маркеров нет → fired с инструкцией и playbook
    many = [_cal_forecast([_clean_entry() for _ in range(CAL_M1_MIN_CLEAN)])]
    r = cal(many, [], today)
    fired = {a["id"] for a in r["alerts"]}
    check("M1 fired при n=15 без маркеров", "M1" in fired)
    m1 = next(a for a in r["alerts"] if a["id"] == "M1")
    check("M1 label про первую калибровку", "перв" in m1["label"])
    check("M1 instruction содержит имя файла-маркера",
          f"adhoc-{today.isoformat()}.md" in m1["instruction"])
    check("M1 playbook-путь с секцией", "calibration-playbook.md §M1" in m1["playbook"])
    check("M3 не fired при n=15", "M3" not in fired)

    # M1 гаснет при свежем маркере adhoc-*, перевзводится при старом
    fresh = f"adhoc-{(today - timedelta(days=10)).isoformat()}.md"
    stale = f"adhoc-{(today - timedelta(days=CAL_REPEAT_DAYS)).isoformat()}.md"
    r = cal(many, [fresh], today)
    check("M1 молчит при свежем adhoc-маркере", "M1" not in {a["id"] for a in r["alerts"]})
    r = cal(many, [stale], today)
    m1 = next((a for a in r["alerts"] if a["id"] == "M1"), None)
    check("M1 перевзводится при маркере старше 90 дн", m1 is not None)
    check("M1 повторный label содержит дату последнего отчёта",
          m1 is not None and stale[6:16] in m1["label"])

    # свежий calibration-*.md (отчёт скилла) тоже гасит M1
    r = cal(many, [f"calibration-{(today - timedelta(days=5)).isoformat()}.md"], today)
    check("M1 молчит при свежем calibration-маркере", "M1" not in {a["id"] for a in r["alerts"]})

    # M2: 2 adhoc и нет calibration-*.md → fired; появился calibration-*.md → гаснет
    two_adhoc = ["adhoc-2026-08-01.md", "adhoc-2026-09-01.md"]
    r = cal([], two_adhoc, today)
    check("M2 fired при 2 adhoc без skill-отчётов", "M2" in {a["id"] for a in r["alerts"]})
    r = cal([], two_adhoc + ["calibration-2026-10-01.md"], today)
    check("M2 гаснет при calibration-*.md", "M2" not in {a["id"] for a in r["alerts"]})

    # M3: n=30 → fired вместе с M1; свежий source-rerating гасит только M3
    many30 = [_cal_forecast([_clean_entry() for _ in range(CAL_M3_MIN_CLEAN)])]
    r = cal(many30, [], today)
    fired = {a["id"] for a in r["alerts"]}
    check("M3 fired при n=30", "M3" in fired and "M1" in fired)
    r = cal(many30, [f"source-rerating-{(today - timedelta(days=3)).isoformat()}.md"], today)
    fired = {a["id"] for a in r["alerts"]}
    check("свежий source-rerating гасит M3, не M1", "M3" not in fired and "M1" in fired)

    # M4: без счётчика молчит; со счётчиком ≥30 fired; свежий catalyst-calibration гасит
    r = cal([], [], today)
    check("M4 молчит при catalyst_resolved=None", "M4" not in {a["id"] for a in r["alerts"]})
    r = cal([], [], today, catalyst_resolved=CAL_M4_MIN_CATALYST)
    check("M4 fired при 30 catalyst-исходах", "M4" in {a["id"] for a in r["alerts"]})
    check("M4 в progress_line числом", f"{CAL_M4_MIN_CATALYST}/{CAL_M4_MIN_CATALYST}" in r["progress_line"])
    r = cal([], [f"catalyst-calibration-{(today - timedelta(days=1)).isoformat()}.md"],
            today, catalyst_resolved=40)
    check("свежий catalyst-calibration гасит M4", "M4" not in {a["id"] for a in r["alerts"]})

    # Маркеры: пути/регистр/чужие файлы; битая дата в имени не считается датой маркера
    r = cal(many, ["calibration/ADHOC-2026-03-01.md", "заметка.txt", "adhoc-без-даты.md"], today)
    m1 = next((a for a in r["alerts"] if a["id"] == "M1"), None)
    check("маркер: путь+регистр учтён (старый → повтор), битая дата игнорируется",
          m1 is not None and "2026-03-01" in m1["label"])
    check("маркер: посчитаны только валидные .md",
          r["counts"]["n_adhoc_reports"] == 2)  # ADHOC-… + adhoc-без-даты (count не требует даты)

    # Интеграция в compute(): superseded-файл даёт счёт, calibration в output
    payload = {"today": "2026-07-06",
               "forecasts": [dict(_cal_forecast([_clean_entry()]), basename="old.yaml")],
               "calibration_files": ["adhoc-2026-07-01.md"],
               "catalyst_resolved_count": 5}
    r = compute(payload)
    check("compute: calibration в output", "calibration" in r)
    check("compute: superseded в зачёте", r["calibration"]["counts"]["n_clean"] == 1)
    check("compute: adhoc-маркер посчитан", r["calibration"]["counts"]["n_adhoc_reports"] == 1)
    check("compute: catalyst счётчик проброшен",
          r["calibration"]["counts"]["catalyst_resolved"] == 5)
    check("compute: superseded по-прежнему в files_skipped для алертов",
          any(s["basename"] == "old.yaml" for s in r["files_skipped"]))


def _cdef(cid, key, ttype, value, version=1, **kw):
    """Определение conditions@2 (поля, которые читает монитор)."""
    d = {"id": cid, "version": version, "key": key, "kind": "review",
         "trigger": {"type": ttype, "value": value}, "created_at": kw.pop("created_at", "2026-10-09T00:00:00+03:00"),
         "withdrawn": None, "superseded_by": None}
    if "window_end" in kw:
        d["trigger"]["window_end"] = kw.pop("window_end")
    d.update(kw)
    return d


def test_condition_events():
    print("test_condition_events (conditions@2 → condition_findings[])")
    today = date(2026, 11, 3)
    defs = [
        _cdef("ru000a106ep1-ifrs9m-3011", "RU000A106EP1", "report_published", "МСФО 9М 2026 ПР-Лизинг",
              window_end="2026-11-30"),
        _cdef("x5-date-3110", "X5", "report_published", "отчёт", window_end="2026-10-31",
              event_text="отчёт X5 за 3К2026", created_at="2026-08-15T00:00:00+03:00"),
        _cdef("reni-9m2026-review", "RENI", "report_published", "МСФО 9М2026 Ренессанс", window_end="2026-11-30",
              version=1, created_at="2026-09-17T00:00:00+03:00"),
        _cdef("reni-9m2026-review", "RENI", "report_published", "МСФО 9М2026 Ренессанс", window_end="2026-11-30",
              version=2, created_at="2026-10-20T00:00:00+03:00"),
        _cdef("sber-event", "SBER", "event", "", event_text="ГОСА Сбера", valid_until="2026-12-31"),
        _cdef("price", "SBER", "price_below", 250),
        _cdef("date", "SBER", "date", "2026-11-30"),
        _cdef("gone", "GMKN", "report_published", "МСФО", window_end="2026-11-30",
              withdrawn={"at": "2026-10-30T10:00:00+03:00", "by": "owner", "reason": "не нужно"}),
        _cdef("late", "GMKN", "report_published", "МСФО", window_end="2026-10-20", valid_until="2026-10-31"),
        _cdef("empty", "LKOH", "event", ""),
    ]
    prior = [{"condition_id": "reni-9m2026-review", "version": 2, "doc": "https://example.ru/r", "found_at": "2026-10-29",
              "note": "вышла"},
             {"condition_id": "x5-date-3110", "version": 1, "doc": None, "found_at": None, "note": "не найдено"},
             {"condition_id": "sber-event", "version": 7, "doc": "https://example.ru/old", "found_at": "2026-01-01"}]
    res = _process_condition_events(defs, today, n_red=7, prior_findings=prior)
    by = {r["condition_id"]: r["alerts"][0] for r in res}
    check(f"ищутся report_published и event последней версии; цена, дата, снятое, просроченное, пустое — нет ({sorted(by)})",
          sorted(by) == ["reni-9m2026-review", "ru000a106ep1-ifrs9m-3011", "sber-event", "x5-date-3110"])
    check("версия — последняя (reni v2)", by["reni-9m2026-review"]["version"] == 2)
    check("далёкий window_end → yellow, ищем", by["ru000a106ep1-ifrs9m-3011"]["severity"] == "yellow"
          and by["ru000a106ep1-ifrs9m-3011"]["needs_web_search"])
    check("window_end прошёл → red", by["x5-date-3110"]["severity"] == "red" and "прошла 3 дн." in by["x5-date-3110"]["label"])
    check("что ищем: event_text, иначе trigger.value",
          by["x5-date-3110"]["description"] == "отчёт X5 за 3К2026"
          and by["ru000a106ep1-ifrs9m-3011"]["description"] == "МСФО 9М 2026 ПР-Лизинг")
    check("event без window_end: контрольная дата — valid_until", by["sber-event"]["check_date"] == "2026-12-31")
    check("найденное раньше (та же версия, doc и found_at) не ищем", by["reni-9m2026-review"]["needs_web_search"] is False)
    check("находка другой версии не переносится", by["sber-event"]["needs_web_search"] is True and not by["sber-event"]["found"])
    check("search_from = дата created_at условия",
          next(r for r in res if r["condition_id"] == "ru000a106ep1-ifrs9m-3011")["search_from_date"] == "2026-10-09")
    q = build_search_query(by["ru000a106ep1-ifrs9m-3011"], "2026-10-09")
    check(f"ISIN в запрос не идёт, событие в кавычках ({q})",
          q == '"МСФО 9М 2026 ПР-Лизинг" опубликован after:2026-10-09')
    q2 = build_search_query(by["x5-date-3110"], "2026-08-15")
    check(f"тикер акции в запросе ({q2})", q2.startswith('X5 "отчёт X5 за 3К2026"'))
    tpl = condition_findings_template(res)
    t = {x["condition_id"]: x for x in tpl}
    check("заготовка: ровно поля {condition_id, version, doc, found_at, note}",
          all(set(x) == {"condition_id", "version", "doc", "found_at", "note"} for x in tpl))
    check("заготовка: найденное перенесено с doc и found_at",
          t["reni-9m2026-review"] == {"condition_id": "reni-9m2026-review", "version": 2, "doc": "https://example.ru/r",
                                      "found_at": "2026-10-29", "note": "вышла"})
    check("заготовка: новое — doc и found_at пусты до поиска", t["x5-date-3110"]["doc"] is None
          and t["x5-date-3110"]["found_at"] is None and t["x5-date-3110"]["version"] == 1)
    r = compute({"today": "2026-11-03", "forecasts": [], "conditions": {"schema_version": "conditions@2", "conditions": defs},
                 "prior_condition_findings": prior})
    plan_ids = [c["basename"] for c in r["web_search_plan"]["scheduled"]]
    check(f"compute: в плане поиска 3 события, red первым ({plan_ids})",
          plan_ids[0] == "condition-x5-date-3110" and sorted(plan_ids) == sorted(
              ["condition-x5-date-3110", "condition-ru000a106ep1-ifrs9m-3011", "condition-sber-event"]))
    check("compute: condition_findings в выводе, condition_events нет",
          len(r["condition_findings"]) == 4 and "condition_events" not in r)
    check("compute: без условий — пустой список", compute({"today": "2026-11-03", "forecasts": []})["condition_findings"] == [])
    old = compute({"today": "2026-11-03", "forecasts": [],
                   "condition_events": [{"id": "a", "ticker": "X", "event": "МСФО", "deadline": "2026-11-30"}]})
    check("старое представление (payload condition_events) не читается", old["condition_findings"] == []
          and not any(c["basename"] == "condition-a" for c in old["web_search_plan"]["scheduled"]))


def test_condition_events_owner_not_held():
    print("test_condition_events_owner_not_held (условие владельца на бумагу вне портфеля)")
    import inspect
    today = date(2026, 11, 12)
    own = _cdef("c-2026-11-11-zzzz-1", "ZZZZ", "event", "выйдет отчёт МСФО за 9М ZZZZ", kind="watch",
                event_text="выйдет отчёт МСФО за 9М ZZZZ", valid_until="2027-01-31",
                source={"kind": "owner", "doc": None}, created_by="owner",
                while_pending={"verdict": None, "text": ""}, on_trigger={"action": "notify_only", "text": "посмотреть"})
    res = _process_condition_events([own], today, n_red=7)
    check("событие владельца на не держимую бумагу попадает в план (держимость не проверяется)",
          [r["condition_id"] for r in res] == ["c-2026-11-11-zzzz-1"] and res[0]["alerts"][0]["needs_web_search"])
    r = compute({"today": today.isoformat(), "forecasts": [], "conditions": [own], "holdings": []})
    check("compute: в web_search_plan есть запись по бумаге вне портфеля",
          [c["basename"] for c in r["web_search_plan"]["scheduled"]] == ["condition-c-2026-11-11-zzzz-1"])
    src = inspect.getsource(_process_condition_events)
    check("в _process_condition_events нет фильтра по портфелю (held/snapshot/holdings)",
          not any(w in src for w in ("held", "snapshot", "holdings")))


def main() -> int:
    print("=" * 60)
    print("forecast-monitor / monitor_alerts.py")
    print("=" * 60)

    test_classify_by_date()
    test_review_window_days()
    test_compute_search_from_date()
    test_post_filter_event()
    test_process_forecast_review_overdue()
    test_horizon_passed_beats_review()
    test_review_monthly_narrow_window()
    test_process_forecast_full()
    test_monitoring_overdue_severity()
    test_monitoring_checked_template()
    test_assign_priority()
    test_build_search_query()
    test_build_web_search_plan_limit()
    test_no_stale_flags_freshness_by_dates()
    test_compute_full_pipeline()
    test_cli_compute_stdin()
    test_cli_post_filter()
    test_parse_window_end()
    test_catalyst_to_monitoring()
    test_process_weekly_review_catalysts()
    test_compute_with_catalysts()
    test_build_search_query_catalyst()
    test_outcome_capture()
    test_calibration_milestones()
    test_portfolio_position_watch()
    test_condition_events()
    test_condition_events_owner_not_held()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

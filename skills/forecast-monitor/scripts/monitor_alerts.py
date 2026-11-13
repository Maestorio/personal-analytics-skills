#!/usr/bin/env python3
"""
monitor_alerts.py

Детерминированный планировщик алертов для forecast-monitor:
- фильтрация active-прогнозов и расчёт search_from_date (Шаг 2)
- классификация по дате next_due / deadlines / monitoring / thresholds / falsifiers (Шаги 3a-e)
- свод по приоритетам 🔴/🟡/⚪ (Шаг 5)
- web_search plan с лимитом и сортировкой по severity (Шаг 4)
- post-filter событий по search_from_date (Шаг 4.1)
- свежесть прогноза — по его собственным датам: `forecast_date`, горизонт (`horizon_date`/`horizon_passed`
  в строке файла, алерт `horizon_passed`); файла флагов устаревания нет (`stale_flags.yaml` упразднён, R15)

LLM остаётся только: сам web_search, извлечение даты события из сниппета,
формирование вердикта (✅/❌/⚠️), markdown-дайджест.

CLI:
    cat input.json | python3 monitor_alerts.py
    python3 monitor_alerts.py --input input.json --output result.json
    python3 monitor_alerts.py post-filter --search-from 2026-04-30 --event-date 2026-04-15

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from datetime import date, datetime, timedelta
from typing import Any

DEFAULT_N_RED = 7
DEFAULT_N_YELLOW = 14   # deprecated — оставлено для совместимости с payload, не используется
DEFAULT_MAX_SEARCHES = 10

# Окно проверки для review-триггера зависит от interval_months:
# при ежемесячной проверке окно ±5 дней (плотный график, мелкое окно),
# для всего более редкого — ±7 дней.
REVIEW_WINDOW_SHORT_INTERVAL = 5    # interval_months == 1
REVIEW_WINDOW_LONG_INTERVAL = 7     # interval_months >= 2

SEVERITY_ORDER = {"critical": 1, "high": 2, "medium": 3, "low": 4, None: 5}

# --- Калибровочный сторож (events-yaml-spec §14; пороги — PROJECT-HANDOFF-2026-07 §4) ---
# Все пороги provisional until outcome_log calibration — подкрутить по первым реальным резолвам.
CAL_M1_MIN_CLEAN = 15           # clean-исходов → доступна ad-hoc калибровка №1
CAL_M2_MIN_ADHOC = 2            # ad-hoc отчётов → пора кодировать calibration-скилл
CAL_M3_MIN_CLEAN = 30           # clean-исходов → доступен пере-рейтинг источников
CAL_M4_MIN_CATALYST = 30        # resolved catalyst-предсказаний → разблокирован v2-C
CAL_REPEAT_DAYS = 90            # повторный прогон шага, если последний отчёт-маркер старше
CAL_PLAYBOOK = "skills/forecast-monitor/references/calibration-playbook.md"


def review_window_days(interval_months: int | None) -> int:
    """Симметричное окно ±N вокруг next_due по правилу пользователя."""
    if interval_months == 1:
        return REVIEW_WINDOW_SHORT_INTERVAL
    return REVIEW_WINDOW_LONG_INTERVAL


def parse_date(s: str | date | None) -> date | None:
    if s is None:
        return None
    if isinstance(s, date):
        return s
    return datetime.strptime(s, "%Y-%m-%d").date()


def classify_by_date(
    target: date | None,
    today: date,
    n_window: int,
    *,
    label_overdue: str = "ПРОСРОЧЕНО на {n} дней",
    label_upcoming: str = "через {n} дней",
) -> dict[str, Any]:
    """
    Симметричное окно ±n_window вокруг даты:
    - target прошёл → red «ПРОСРОЧЕНО на N дней» (всегда сигнализируем,
      даже если давно — пользователь мог пропустить запуск)
    - target в окне (0..n_window дней вперёд) → red «через N дней»
    - target за окном (>n_window дней вперёд) → none (молчим, ждём
      следующего окна)
    target = None → severity none.
    """
    if target is None:
        return {"severity": "none", "label": "—", "days_delta": None}
    delta = (target - today).days
    if delta < 0:
        return {
            "severity": "red",
            "label": label_overdue.format(n=-delta),
            "days_delta": delta,
        }
    if delta <= n_window:
        return {
            "severity": "red",
            "label": label_upcoming.format(n=delta),
            "days_delta": delta,
        }
    return {"severity": "none", "label": label_upcoming.format(n=delta), "days_delta": delta}


def compute_search_from_date(forecast_date: date, last_completed: date | None) -> date:
    """search_from_date = max(forecast.date, reviews.last_completed)."""
    if last_completed is None:
        return forecast_date
    return max(forecast_date, last_completed)


def post_filter_event(event_date: date | None, search_from_date: date) -> str:
    """
    Шаг 4.1: фильтрация результата web_search по дате события.
    Возвращает один из:
      'keep'      — event_date >= search_from_date, можно использовать
      'drop'      — event_date < search_from_date, отбросить
      'undefined' — event_date не определена однозначно
    """
    if event_date is None:
        return "undefined"
    return "keep" if event_date >= search_from_date else "drop"


def _alert_review(forecast: dict, today: date) -> dict | None:
    """
    Шаг 3a — reviews.next_due. Окно ±N дней зависит от interval_months
    (interval_months==1 → ±5; иначе ±7). Просрочки сигнализируются
    независимо от окна; «приближается» (yellow upcoming) убран.
    """
    reviews = forecast.get("reviews") or {}
    next_due = parse_date(reviews.get("next_due"))
    if next_due is None:
        return None
    interval = reviews.get("interval_months")
    n_window = review_window_days(interval)
    cls = classify_by_date(next_due, today, n_window)
    if cls["severity"] == "none":
        return None
    return {
        "kind": "review",
        "type_label": "РЕВЬЮ",
        "severity": cls["severity"],
        "severity_tier": "high",
        "label": cls["label"],
        "days_delta": cls["days_delta"],
        "due_date": next_due.isoformat(),
        "review_window_days": n_window,
        "interval_months": interval,
        "auto_checkable": True,
        "needs_web_search": False,
        "action_hint": "запустить forecast-confidence-applier для пересборки прогноза",
    }


def forecast_horizon(forecast: dict) -> date | None:
    """Горизонт прогноза: `horizon` (скаляр) либо последняя дата сетки `horizons[]`."""
    def _sd(v):
        try:
            return parse_date(v)
        except (ValueError, TypeError):
            return None

    hz = _sd(forecast.get("horizon"))
    if hz is not None:
        return hz
    grid = [d for d in (_sd(v) for v in (forecast.get("horizons") or [])) if d is not None]
    return max(grid) if grid else None


def _alert_horizon_passed(forecast: dict, today: date) -> dict | None:
    """Горизонт прошёл: обновлять нечего — прогноз закрывают с исходом (приоритет над РЕВЬЮ)."""
    hz = forecast_horizon(forecast)
    if hz is None or hz >= today:
        return None
    days = (today - hz).days
    return {
        "kind": "horizon_passed",
        "type_label": "ГОРИЗОНТ",
        "severity": "red",
        "severity_tier": "high",
        "label": f"горизонт {hz.isoformat()} прошёл {days} дн. назад",
        "days_delta": -days,
        "horizon_date": hz.isoformat(),
        "auto_checkable": True,
        "needs_web_search": True,
        "action_hint": "web_search факт на дату горизонта → сравнить с центром/диапазоном → "
                       "«Закрой прогноз» (сбылся | не сбылся); обе записи пары «прогноз + сценарии» — одной фразой",
    }


def _alerts_deadlines(forecast: dict, today: date, n_red: int) -> list[dict]:
    """
    Шаг 3b — deadlines[]. Симметричное окно ±n_red вокруг даты дедлайна;
    просрочки сигнализируются всегда.
    """
    out = []
    for d in forecast.get("deadlines") or []:
        d_date = parse_date(d.get("date"))
        if d_date is None:
            continue
        cls = classify_by_date(
            d_date, today, n_red,
            label_overdue="ПРОШЛО {n} дней назад",
        )
        if cls["severity"] == "none":
            continue
        out.append({
            "kind": "deadline",
            "type_label": "ДЕДЛАЙН",
            "severity": cls["severity"],
            "severity_tier": "high",
            "label": cls["label"],
            "days_delta": cls["days_delta"],
            "date": d_date.isoformat(),
            "description": d.get("description"),
            "auto_checkable": True,
            "needs_web_search": False,
            "action_hint": d.get("action") or "выполнить действие из карточки прогноза",
        })
    return out


def _alerts_monitoring(forecast: dict, today: date, n_red: int) -> list[dict]:
    """
    Шаг 3c — monitoring[] (check_date + auto_checkable). Окно ±n_red.
    Если check_date просрочен — сигнализируем независимо от окна:
    critical → red, иначе → yellow. Будущие check_date вне окна — молчим.
    """
    out = []
    for m in forecast.get("monitoring") or []:
        check_date = parse_date(m.get("check_date"))
        if check_date is None:
            continue
        delta = (check_date - today).days
        severity_yaml = (m.get("severity") or "").lower()
        is_critical = severity_yaml == "critical"

        if delta < 0:
            severity = "red" if is_critical else "yellow"
            suffix = " (critical)" if is_critical else ""
            label = f"ПРОСРОЧЕНО на {-delta} дней{suffix}"
        elif delta <= n_red:
            severity = "red"
            label = f"через {delta} дней"
        else:
            continue   # ещё не пора — молчим, без yellow «приближается»

        auto_checkable = bool(m.get("auto_checkable", False))
        item = {
            "kind": "monitoring",
            "monitoring_id": m.get("id"),   # копируется в monitor-report: alerts[].monitoring_id / monitoring_checked[]
            "type_label": "МОНИТОРИНГ",
            "severity": severity,
            "severity_tier": severity_yaml or "medium",
            "label": label,
            "days_delta": delta,
            "check_date": check_date.isoformat(),
            "description": m.get("description"),
            "threshold": m.get("threshold"),
            "impact": m.get("impact"),
            "would_resolve": bool(m.get("would_resolve", False)),
            "auto_checkable": auto_checkable,
            "needs_web_search": auto_checkable,
            "action_hint": "проверить порог" if auto_checkable
                            else "ручная проверка — числового порога нет",
        }
        out.append(item)
    return out


def _alerts_thresholds(forecast: dict, today: date) -> list[dict]:
    """Шаг 3d — thresholds[] (плановая еженедельная проверка для auto_checkable)."""
    out = []
    for t in forecast.get("thresholds") or []:
        if not t.get("auto_checkable"):
            continue
        out.append({
            "kind": "threshold",
            "type_label": "ПОРОГ",
            "severity": "yellow",
            "severity_tier": "medium",
            "label": "плановая проверка",
            "days_delta": None,
            "variable": t.get("variable"),
            "condition": t.get("condition"),
            "flips_to": t.get("flips_to"),
            "auto_checkable": True,
            "needs_web_search": True,
            "action_hint": "если условие выполнено → запустить FCA для пересборки",
        })
    return out


def _alerts_falsifiers(forecast: dict, today: date) -> list[dict]:
    """Шаг 3e — falsifiers[] (плановая проверка для auto_checkable)."""
    out = []
    for f in forecast.get("falsifiers") or []:
        if not f.get("auto_checkable"):
            continue
        out.append({
            "kind": "falsifier",
            "type_label": "ФАЛЬСИФИКАТОР",
            "severity": "yellow",
            "severity_tier": "medium",
            "label": "плановая проверка",
            "days_delta": None,
            "description": f.get("description"),
            "would_resolve": bool(f.get("would_resolve", False)),
            "auto_checkable": True,
            "needs_web_search": True,
            "action_hint": "если событие произошло и would_resolve=true → save-to-library "
                           "для закрытия прогноза",
        })
    return out


def _alerts_outcome_capture(forecast: dict, today: date) -> list[dict]:
    """F7 — детерминированный захват исхода (events-yaml-spec.md §14.3).

    Сканирует резолв-точки прогноза (outcome_log.resolve_date + fca_stats-ключи + horizon)
    и на каждую наступившую (≤ today), для которой ещё НЕТ заполненного outcome_log-исхода,
    выдаёт alert `kind: outcome_capture` + web_search. Раньше захват жил только в прозе SKILL
    (§7.6) → монитор детектил резолв, но факт в outcome_log не клал (self-audit gap)."""
    log = forecast.get("outcome_log") or []

    def _filled(e: dict) -> bool:
        return (e.get("actual") is not None) if e.get("kind") == "level" else (e.get("resolved") is not None)

    def _sd(v):  # safe parse — legacy fca_stats-ключи вроде 'horizon_2026_12_31' не роняют шаг
        try:
            return parse_date(v)
        except (ValueError, TypeError):
            return None

    filled = {_sd(e.get("resolve_date")) for e in log
              if isinstance(e, dict) and _filled(e)}
    filled.discard(None)

    # Кандидат-резолвы: date -> hint по kind (level|event).
    points: dict = {}
    for e in log:
        if isinstance(e, dict):
            rd = _sd(e.get("resolve_date"))
            if rd is not None:
                points.setdefault(rd, e.get("kind"))
    for key, cell in (forecast.get("fca_stats") or {}).items():
        d = _sd(key)
        if d is not None:
            points.setdefault(d, (cell or {}).get("kind") if isinstance(cell, dict) else None)
    hz = _sd(forecast.get("horizon"))
    if hz is not None:
        points.setdefault(hz, "level")

    out = []
    for rd in sorted(p for p in points if p is not None and p <= today and p not in filled):
        days_overdue = (today - rd).days
        out.append({
            "kind": "outcome_capture",
            "type_label": "ИСХОД",
            "severity": "red",
            "severity_tier": "high",
            "label": f"резолв {rd.isoformat()} наступил {days_overdue} дн. назад — факт не зафиксирован",
            "days_delta": days_overdue,
            "resolve_date": rd.isoformat(),
            "outcome_kind": points[rd] or "level",
            "description": forecast.get("central_estimate"),
            "needs_web_search": True,
            "auto_checkable": True,
            "action_hint": "web_search факт на resolve_date → заполнить outcome_log_updates "
                           "(actual для level | resolved для event) → save-to-library Workflow L "
                           "пишет в forecast (монитор сам в forecasts/ не пишет — D3)",
        })
    return out


# ── Портфельный сторож: санкционное событие → пересборка sanctions_position ──
# Позиции бумаг на санкционной шкале (`sanctions_position` в стресс-тесте) — это
# слепок санкционного статуса эмитентов на дату. Новый пакет или снятие мер
# делают слепок устаревшим, а молчаливое устаревание незаметно: числа остаются
# правдоподобными. Поэтому монитор говорит об этом сам, а не полагается на память.
PORTFOLIO_WATCH_DOMAINS = ("geopolitics",)
PORTFOLIO_WATCH_TOPIC_MARKERS = ("sanction", "санкц", "geopolitic", "геополит")
PORTFOLIO_WATCH_RUBRIC = "docs/investment/portfolio/sanctions-position-rubric.md"


def portfolio_position_watch(processed: list[dict]) -> dict | None:
    """
    Нужна ли пересборка таблицы `sanctions_position`. Срабатывает, когда по
    санкционно-геополитическому прогнозу есть НЕ-белый алерт: значит статус
    эмитентов мог измениться. Возвращает None, если поводов нет.
    """
    hits: list[dict] = []
    for f in processed:
        if "skipped" in f:
            continue
        domain = str(f.get("domain") or "").lower()
        topic = str(f.get("topic") or "").lower()
        basename = str(f.get("basename") or "").lower()
        relevant = domain in PORTFOLIO_WATCH_DOMAINS or any(
            m in topic or m in basename for m in PORTFOLIO_WATCH_TOPIC_MARKERS
        )
        if not relevant:
            continue
        fired = [a for a in (f.get("alerts") or [])
                 if a.get("severity") in ("red", "yellow")]
        if fired:
            hits.append({
                "basename": f.get("basename"),
                "kinds": sorted({a.get("kind") for a in fired if a.get("kind")}),
                "severities": sorted({a.get("severity") for a in fired}),
            })
    if not hits:
        return None
    return {
        "id": "sanctions-position-restage",
        "label": "Санкционный статус мог измениться — пересобрать sanctions_position",
        "sources": hits,
        "instruction": (
            "Проверь, затрагивает ли событие эмитентов портфеля. Если да — пересобери "
            "таблицу позиций на санкционной шкале ПО РУБРИКЕ, не на глаз: полосы, "
            "поправки и якоря там заданы, чтобы значения не переопределялись каждый "
            "раз заново."
        ),
        "rubric": PORTFOLIO_WATCH_RUBRIC,
    }


def process_forecast(forecast: dict, today: date, n_red: int) -> dict:
    """Прогоняет один YAML-файл через все шаги 3a-e."""
    forecast_date = parse_date(forecast.get("forecast_date"))
    if forecast_date is None:
        return {"basename": forecast.get("basename"), "skipped": "no_forecast_date"}

    last_completed = parse_date((forecast.get("reviews") or {}).get("last_completed"))
    search_from = compute_search_from_date(forecast_date, last_completed)

    alerts: list[dict] = []
    hz = forecast_horizon(forecast)
    horizon_alert = _alert_horizon_passed(forecast, today)
    review_alert = None if horizon_alert is not None else _alert_review(forecast, today)
    if horizon_alert is not None:
        alerts.append(horizon_alert)
    if review_alert is not None:
        alerts.append(review_alert)
    alerts.extend(_alerts_deadlines(forecast, today, n_red))
    alerts.extend(_alerts_monitoring(forecast, today, n_red))
    alerts.extend(_alerts_thresholds(forecast, today))
    alerts.extend(_alerts_falsifiers(forecast, today))
    alerts.extend(_alerts_outcome_capture(forecast, today))

    return {
        "basename": forecast.get("basename"),
        "topic": forecast.get("topic") or (forecast.get("matrix") or {}).get("topic"),
        "domain": forecast.get("domain"),
        "horizon": forecast.get("horizon"),
        "central_estimate": forecast.get("central_estimate"),
        "confidence": forecast.get("confidence"),
        "forecast_date": forecast_date.isoformat(),
        "horizon_date": hz.isoformat() if hz else None,
        "horizon_passed": horizon_alert is not None,
        "search_from_date": search_from.isoformat(),
        "alerts": alerts,
    }


def assign_priority(processed: list[dict]) -> dict[str, list[str]]:
    """Шаг 5 — распределение по 🔴/🟡/⚪."""
    red, yellow, white = [], [], []
    for f in processed:
        if "skipped" in f:
            continue
        severities = {a["severity"] for a in f.get("alerts", [])}
        if "red" in severities:
            red.append(f["basename"])
        elif "yellow" in severities:
            yellow.append(f["basename"])
        else:
            white.append(f["basename"])
    return {"red": red, "yellow": yellow, "white": white}


# Последний день каждого квартала (месяц, день).
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def parse_window_end(date_window: str | None, review_date: date | None = None) -> date | None:
    """
    Детерминированный парсер верхней границы date_window катализатора.

    Примеры:
      "2026-Q4 to 2027-Q2" → 2027-06-30
      "2026-Q4"            → 2026-12-31
      "2026-06"            → 2026-06-30
      "2026"               → 2026-12-31
      "any"                → review_date + 6 мес (или None, если review_date is None)
      иначе                → None
    """
    if not date_window:
        return None
    s = str(date_window).strip().lower()

    if s == "any":
        if review_date is None:
            return None
        y, mo = review_date.year, review_date.month + 6
        y += (mo - 1) // 12
        mo = ((mo - 1) % 12) + 1
        day = min(review_date.day, calendar.monthrange(y, mo)[1])
        return date(y, mo, day)

    # "X to Y" → берём правую часть
    if " to " in s:
        s = s.split(" to ", 1)[1].strip()

    # Квартал: "2027-q2"
    q_m = re.match(r"^(\d{4})-q([1-4])$", s)
    if q_m:
        year, q = int(q_m.group(1)), int(q_m.group(2))
        end_month, end_day = _QUARTER_END[q]
        return date(year, end_month, end_day)

    # Месяц: "2026-06"
    mo_m = re.match(r"^(\d{4})-(\d{2})$", s)
    if mo_m:
        year, month = int(mo_m.group(1)), int(mo_m.group(2))
        if 1 <= month <= 12:
            return date(year, month, calendar.monthrange(year, month)[1])

    # Год: "2026"
    y_m = re.match(r"^(\d{4})$", s)
    if y_m:
        return date(int(y_m.group(1)), 12, 31)

    return None


def catalyst_to_monitoring(
    catalyst: dict, ticker: str, review_date: date | None
) -> dict | None:
    """
    Маппит один катализатор из weekly-review в monitoring-семантику.
    Возвращает None если:
    - auto_checkable != True
    - in_horizon == False
    - check_date не вычислен из date_window
    """
    if not catalyst.get("auto_checkable"):
        return None
    if catalyst.get("in_horizon") is False:
        return None

    check_date = parse_window_end(catalyst.get("date_window"), review_date)
    if check_date is None:
        return None

    # Severity: tail-risk downside с малым p → critical;
    # HIGH-quality + p≥0.5 → high; иначе medium.
    sq = (catalyst.get("source_quality") or "").upper()
    p = catalyst.get("p")
    has_downside = catalyst.get("downside_pct") is not None
    if has_downside and (p is None or p <= 0.3):
        severity = "critical"
    elif sq == "HIGH" and p is not None and float(p) >= 0.5:
        severity = "high"
    else:
        severity = "medium"

    impact = "invalidates" if has_downside else "supports"
    threshold = catalyst.get("check_what") or catalyst.get("trigger") or ""

    return {
        "check_date": check_date,
        "description": catalyst.get("trigger") or "",
        "threshold": threshold,
        "severity": severity,
        "impact": impact,
    }


def _process_weekly_review_catalysts(
    items: list[dict], today: date, n_red: int
) -> list[dict]:
    """
    Шаг 3f — catalyst[]. Преобразует weekly_review_catalysts в синтетические
    forecast-записи (одна на тикер) для интеграции в общий поток алертов.

    Каждый item: {ticker, review_date, catalyst: {...}}.
    Синтетические записи включаются в active_files, priority_buckets, web_search_plan
    на общих основаниях.
    """
    by_ticker: dict[str, list[dict]] = {}
    for item in items:
        t = item.get("ticker") or "unknown"
        by_ticker.setdefault(t, []).append(item)

    result: list[dict] = []
    for ticker, ticker_items in by_ticker.items():
        alerts: list[dict] = []
        review_dates: list[date] = []

        for item in ticker_items:
            review_date = parse_date(item.get("review_date"))
            catalyst = item.get("catalyst") or {}
            m = catalyst_to_monitoring(catalyst, ticker, review_date)
            if m is None:
                continue
            check_date = m["check_date"]
            delta = (check_date - today).days
            severity_yaml = m["severity"]
            is_critical = severity_yaml == "critical"

            if delta < 0:
                # Любой просроченный катализатор → red (портфельное событие, не macro forecast)
                severity = "red"
                suffix = " (critical)" if is_critical else ""
                label = f"ПРОСРОЧЕНО на {-delta} дней{suffix}"
            elif delta <= n_red:
                severity = "red"
                label = f"через {delta} дней"
            else:
                continue  # вне окна — молчим

            auto_checkable = bool(catalyst.get("auto_checkable", False))
            alerts.append({
                "kind": "catalyst",
                "type_label": "КАТАЛИЗАТОР",
                "ticker": ticker,
                "severity": severity,
                "severity_tier": severity_yaml,
                "label": label,
                "days_delta": delta,
                "check_date": check_date.isoformat(),
                "description": m["description"],
                "threshold": m["threshold"],
                "impact": m["impact"],
                "would_resolve": False,
                "auto_checkable": auto_checkable,
                "needs_web_search": auto_checkable,
                "action_hint": (
                    "проверить через web_search, сработал ли катализатор"
                    if auto_checkable else "ручная проверка катализатора"
                ),
            })
            if review_date:
                review_dates.append(review_date)

        if not alerts:
            continue

        earliest = min(review_dates).isoformat() if review_dates else today.isoformat()
        result.append({
            "basename": f"weekly-review-{ticker.lower()}-catalysts",
            "topic": f"{ticker} catalyst monitoring",
            "domain": "portfolio-catalysts",
            "horizon": None,
            "central_estimate": None,
            "confidence": None,
            "forecast_date": earliest,
            "search_from_date": earliest,
            "alerts": alerts,
        })
    return result


# Типы триггера, событие которых ищет монитор (conditions@2, schema.md §3.2): отчёт и событие словами.
CONDITION_SEARCH_TRIGGERS = ("report_published", "event")


def _latest_condition_defs(defs: list[dict]) -> list[dict]:
    """Последняя версия каждого id (наибольший `version`; при равной — первая в файле), порядок первого вхождения."""
    last: dict[str, dict] = {}
    order: list[str] = []
    for d in defs or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        cid = d["id"]
        if cid not in last:
            order.append(cid)
            last[cid] = d
        elif int(d.get("version") or 0) > int(last[cid].get("version") or 0):
            last[cid] = d
    return [last[c] for c in order]


def _process_condition_events(
    defs: list[dict], today: date, n_red: int, prior_findings: list[dict] | None = None
) -> list[dict]:
    """
    Шаг 3g — события условий (`conditions@2`, определения из `Portfolio/conditions.yaml`).
    Ищутся условия последней версии, не снятые (`withdrawn`), с триггером `report_published` или
    `event`; что ищем — `event_text`, иначе `trigger.value`; контрольная дата — `trigger.window_end`,
    иначе `valid_until`; условие с `valid_until` в прошлом не ищется (срок вышел).
    `prior_findings` — `condition_findings[]` прошлого отчёта: находка той же версии
    (`found_at` и `doc`) переносится, повторно не ищется.

    Одна синтетическая запись на условие (`basename: condition-<id>`) — только для плана поиска.
    В отчёт монитора находка идёт полем `condition_findings[]` (`condition_findings_template`);
    монитор состояние условий не пишет — находку переносит в него задача hub-notify.
    """
    found_by = {}
    for f in prior_findings or []:
        if isinstance(f, dict) and f.get("condition_id") and f.get("found_at") and f.get("doc"):
            found_by[(f["condition_id"], f.get("version"))] = f
    result: list[dict] = []
    for d in _latest_condition_defs(defs):
        trig = d.get("trigger") or {}
        if d.get("withdrawn") or trig.get("type") not in CONDITION_SEARCH_TRIGGERS:
            continue
        cid, version = d["id"], d.get("version")
        event = str(d.get("event_text") or trig.get("value") or "").strip()
        if not event:
            continue
        valid_until = parse_date(str(d["valid_until"])[:10]) if d.get("valid_until") else None
        if valid_until and valid_until < today:
            continue
        key = d.get("key") or ""
        dl = trig.get("window_end") or d.get("valid_until")
        deadline = parse_date(str(dl)[:10]) if dl else None
        created = parse_date(str(d.get("created_at") or "")[:10] or None) or today
        found = found_by.get((cid, version))
        delta = (deadline - today).days if deadline else None

        if found:
            severity, label, needs = "none", f"событие уже найдено ({found.get('found_at')})", False
        elif delta is not None and delta < 0:
            severity, label, needs = "red", f"контрольная дата прошла {-delta} дн. назад — вышло ли событие?", True
        elif delta is not None and delta <= n_red:
            severity, label, needs = "red", f"контрольная дата через {delta} дн.", True
        else:
            severity = "yellow"
            label = f"контрольная дата через {delta} дн." if delta is not None else "без контрольной даты"
            needs = True

        result.append({
            "basename": f"condition-{cid}",
            "topic": f"{key} condition event",
            "domain": "portfolio-conditions",
            "horizon": deadline.isoformat() if deadline else None,
            "central_estimate": None,
            "confidence": None,
            "forecast_date": created.isoformat(),
            "search_from_date": created.isoformat(),
            "condition_id": cid,
            "alerts": [{
                "kind": "condition_event",
                "type_label": "СОБЫТИЕ УСЛОВИЯ",
                "condition_id": cid,
                "version": version,
                "ticker": key,
                "description": event,
                "check_date": deadline.isoformat() if deadline else None,
                "days_delta": delta,
                "severity": severity,
                "severity_tier": "high" if severity == "red" else "medium",
                "label": label,
                "would_resolve": False,
                "auto_checkable": True,
                "needs_web_search": needs,
                "found": found,
                "action_hint": ("событие вышло — разбор условия можно начинать до даты"
                                if found else "найти через web_search, вышло ли событие"),
            }],
        })
    return result


def condition_findings_template(processed: list[dict]) -> list[dict]:
    """Заготовка поля monitor-report `condition_findings[]` — по строке на искомое условие:
    `{condition_id, version, doc, found_at, note}`. Найденное раньше переносится; новое LLM дозаполняет по
    итогам web_search: `doc` — ссылка на документ, `found_at` — дата публикации события (YYYY-MM-DD),
    только при keep пост-фильтра; не найдено — `doc`/`found_at` остаются null, `note` — по желанию."""
    out = []
    for f in processed:
        for a in f.get("alerts") or []:
            if a.get("kind") != "condition_event":
                continue
            found = a.get("found") or {}
            out.append({
                "condition_id": a["condition_id"],
                "version": a.get("version"),
                "doc": found.get("doc"),
                "found_at": found.get("found_at"),
                "note": found.get("note"),
            })
    return out


def monitoring_checked_template(active: list[dict], processed: list[dict]) -> list[dict]:
    """Заготовка поля monitor-report `monitoring_checked[]`: по строке на каждый пункт `monitoring[]` активного
    файла с `check_date` не позже today (auto_checkable и ручные). Пункт, по которому в отчёте есть алерт с тем же
    `monitoring_id`, из заготовки убирают; остальные остаются строкой с `result` (`met | not_met | unverified`;
    ручной пункт — `auto_checkable: false` в его алерте — без проверки владельцем: `unverified` с `note`;
    кодлист `monitoring_result`) — `validate-monitor-report --root` блокирует отчёт, где пункт с прошедшей датой
    не отражён ни алертом, ни строкой. Пункты прогноза с прошедшим горизонтом (`horizon_passed`) в заготовку не
    идут: их покрывает алерт `horizon_passed` отчёта — прогноз закрывают с исходом."""
    out = []
    for src, f in zip(active, processed):
        if f.get("horizon_passed"):
            continue
        folder = "scenarios" if src.get("type") == "scenario-events" else "forecasts"
        base = str(src.get("basename") or "")
        target_file = f"{folder}/{base}" if base.endswith(".yaml") else f"{folder}/{base}.yaml"
        for a in f.get("alerts") or []:
            if a.get("kind") != "monitoring" or (a.get("days_delta") or 0) > 0:
                continue
            out.append({
                "target": f.get("topic"),
                "target_file": target_file,
                "monitoring_id": a.get("monitoring_id"),
                "check_date": a.get("check_date"),
                "result": None,
                "note": None,
            })
    return out


def build_search_query(alert: dict, search_from_date: str) -> str | None:
    """Шаг 4 — формирует web_search query по типу алерта."""
    kind = alert["kind"]
    if kind == "monitoring":
        desc = alert.get("description") or ""
        threshold = alert.get("threshold") or ""
        return f'"{desc}" {threshold} after:{search_from_date}'.strip()
    if kind == "threshold":
        return f'"{alert.get("variable") or ""}" "{alert.get("condition") or ""}" ' \
               f'after:{search_from_date}'.strip()
    if kind == "falsifier":
        return f'"{alert.get("description") or ""}" after:{search_from_date}'.strip()
    if kind == "catalyst":
        ticker = alert.get("ticker") or ""
        desc = alert.get("description") or ""
        threshold = alert.get("threshold") or ""
        parts = " ".join(p for p in [ticker, f'"{desc}"', threshold] if p)
        return f'{parts} after:{search_from_date}'.strip()
    if kind == "condition_event":
        ticker = alert.get("ticker") or ""
        parts = " ".join(p for p in [ticker if not ticker.startswith("RU000") else "", f'"{alert.get("description") or ""}"'] if p)
        return f'{parts} опубликован after:{search_from_date}'.strip()
    if kind == "outcome_capture":
        # Ищем ФАКТ на дату резолва (не «после search_from»): нужен исход, а не свежесть.
        desc = alert.get("description") or ""
        rd = alert.get("resolve_date") or ""
        return f'"{desc}" факт итог {rd}'.strip()
    return None


def build_web_search_plan(processed: list[dict], max_searches: int) -> dict:
    """Шаг 4 — формирует приоритезированный план web_search с учётом лимита."""
    candidates = []
    for f in processed:
        if "skipped" in f:
            continue
        for idx, alert in enumerate(f.get("alerts", [])):
            if not alert.get("needs_web_search"):
                continue
            tier = alert.get("severity_tier", "medium")
            tier_priority = SEVERITY_ORDER.get(tier, SEVERITY_ORDER["medium"])
            severity_priority = 1 if alert["severity"] == "red" else 2
            candidates.append({
                "basename": f["basename"],
                "alert_index": idx,
                "kind": alert["kind"],
                "severity": alert["severity"],
                "severity_tier": tier,
                "query": build_search_query(alert, f["search_from_date"]),
                "_priority": (severity_priority, tier_priority),
            })
    candidates.sort(key=lambda c: c["_priority"])
    scheduled, deferred = [], []
    for c in candidates:
        c.pop("_priority", None)
        (scheduled if len(scheduled) < max_searches else deferred).append(c)
    return {
        "scheduled": scheduled,
        "deferred": deferred,
        "limit": max_searches,
        "total_candidates": len(candidates),
    }


# --- Калибровочный сторож (M1–M4) --------------------------------------------------

_CAL_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _cal_entry_filled(entry: dict) -> bool:
    """Заполнен ли исход записи outcome_log (level → actual, event → resolved)."""
    kind = entry.get("kind")
    if kind == "event":
        return entry.get("resolved") is not None
    if kind == "level":
        return entry.get("actual") is not None
    return entry.get("actual") is not None or entry.get("resolved") is not None


def _cal_latest_marker(calibration_files: list[str], prefix: str) -> date | None:
    """Самая свежая дата из имён файлов-маркеров calibration/ с данным префиксом."""
    best: date | None = None
    for name in calibration_files:
        base = str(name).rsplit("/", 1)[-1].lower()
        if not base.startswith(prefix) or not base.endswith(".md"):
            continue
        m = _CAL_DATE_RE.search(base)
        if not m:
            continue
        try:
            d = parse_date(m.group(1))
        except ValueError:
            continue
        if best is None or d > best:
            best = d
    return best


def _cal_count_markers(calibration_files: list[str], prefix: str) -> int:
    count = 0
    for name in calibration_files:
        base = str(name).rsplit("/", 1)[-1].lower()
        if base.startswith(prefix) and base.endswith(".md"):
            count += 1
    return count


def _cal_due(latest: date | None, today: date) -> bool:
    """Шаг «не сделан или устарел»: маркера нет либо он старше CAL_REPEAT_DAYS."""
    return latest is None or (today - latest).days >= CAL_REPEAT_DAYS


def compute_calibration_milestones(
    forecasts: list[dict],
    calibration_files: list[str],
    today: date,
    catalyst_resolved: int | None = None,
) -> dict:
    """Сторож калибровочных порогов (M1–M4).

    Считает по ВСЕМ forecast-events (включая superseded/expired — исходы живут в основном
    там), «сделанность» шага читает из файлов-маркеров Claude-Memory/calibration/ (без
    скрытого состояния между запусками). Пороги — handoff §4, provisional.

    Зачёт clean-исхода: record_type=horizon_resolve (interim шумнее — отдельно, анти-паттерн
    §14.4), shock_flag != exogenous_shock, исход заполнен (actual|resolved).
    """
    n_clean = n_clean_level = n_clean_event = 0
    n_interim = n_shock = n_pending = 0
    for f in forecasts:
        if f.get("type") != "forecast-events":
            continue
        for entry in (f.get("outcome_log") or []):
            if not isinstance(entry, dict):
                continue
            if not _cal_entry_filled(entry):
                n_pending += 1
                continue
            if (entry.get("record_type") or "horizon_resolve") == "interim_supersession":
                n_interim += 1
                continue
            if (entry.get("shock_flag") or "none") == "exogenous_shock":
                n_shock += 1
                continue
            n_clean += 1
            if entry.get("kind") == "event":
                n_clean_event += 1
            else:
                n_clean_level += 1

    n_adhoc = _cal_count_markers(calibration_files, "adhoc-")
    n_skill_reports = _cal_count_markers(calibration_files, "calibration-")
    latest_report = max(
        (d for d in (_cal_latest_marker(calibration_files, "adhoc-"),
                     _cal_latest_marker(calibration_files, "calibration-")) if d is not None),
        default=None,
    )
    latest_rerating = _cal_latest_marker(calibration_files, "source-rerating-")
    latest_catcal = _cal_latest_marker(calibration_files, "catalyst-calibration-")

    milestones: list[dict] = []
    alerts: list[dict] = []

    def _add(mid: str, fired: bool, current, threshold, label: str, instruction: str,
             playbook_section: str) -> None:
        milestones.append({
            "id": mid, "fired": fired, "current": current, "threshold": threshold,
        })
        if fired:
            alerts.append({
                "id": mid,
                "severity": "yellow",
                "label": label,
                "instruction": instruction,
                "playbook": f"{CAL_PLAYBOOK} {playbook_section}",
            })

    # M1 — ad-hoc калибровка (первая или плановый повтор раз в CAL_REPEAT_DAYS)
    m1_fired = n_clean >= CAL_M1_MIN_CLEAN and _cal_due(latest_report, today)
    m1_label = (
        f"Порог M1 достигнут: {n_clean} clean-исходов ≥ {CAL_M1_MIN_CLEAN} — доступна первая ad-hoc калибровка"
        if latest_report is None else
        f"Плановый повтор калибровки: последний отчёт {latest_report.isoformat()} старше {CAL_REPEAT_DAYS} дн. "
        f"(clean-исходов {n_clean})"
    )
    _add("M1", m1_fired, n_clean, CAL_M1_MIN_CLEAN, m1_label,
         "Запустить ad-hoc калибровку: собрать заполненные outcome_log из forecasts/*.yaml → "
         "Brier (kind:event) + coverage P10/P90 и знак ошибки (kind:level) + weighted-vs-unweighted "
         "(записи с непустым forecast_l1_unweighted). interim/shock — отдельными строками, не в зачёте. "
         f"Отчёт → Claude-Memory/calibration/adhoc-{today.isoformat()}.md (имя жёсткое — по нему сторож "
         "считает M2).",
         "§M1")

    # M2 — кодировать calibration-скилл; гаснет, когда скилл начинает писать calibration-*.md
    m2_fired = n_adhoc >= CAL_M2_MIN_ADHOC and n_skill_reports == 0
    _add("M2", m2_fired, n_adhoc, CAL_M2_MIN_ADHOC,
         f"Сделано {n_adhoc} ad-hoc прогонов ≥ {CAL_M2_MIN_ADHOC} — пороги обкатаны, пора кодировать calibration-скилл",
         "Спроектировать calibration-скилл: детерминированный скрипт-агрегатор outcome_log + LLM-стадия "
         "trust-дельт поверх гейтов (архитектура — handoff §4). Завести задачу в docs/investment/TODO.md. "
         "Сторож перестанет напоминать, когда скилл начнёт писать отчёты calibration-*.md.",
         "§M2")

    # M3 — пере-рейтинг источников
    m3_fired = n_clean >= CAL_M3_MIN_CLEAN and _cal_due(latest_rerating, today)
    _add("M3", m3_fired, n_clean, CAL_M3_MIN_CLEAN,
         f"Порог M3 достигнут: {n_clean} clean-исходов ≥ {CAL_M3_MIN_CLEAN} — доступен пере-рейтинг источников",
         "Проверить вручную ≥5 clean-резолвов на источник (outcome_log не несёт атрибуцию источников). "
         "Гейты: min-n на источник, материальность эффекта, консистентность (не один выброс), "
         "Bayesian-nudge — не binary-flip. Правки trust → domains/-профили. "
         f"Отчёт → Claude-Memory/calibration/source-rerating-{today.isoformat()}.md.",
         "§M3")

    # M4 — catalyst-калибровка (v2-C); счётчик опционален — пока catalyst-исходы не персистятся
    m4_fired = (catalyst_resolved is not None and catalyst_resolved >= CAL_M4_MIN_CATALYST
                and _cal_due(latest_catcal, today))
    _add("M4", m4_fired, catalyst_resolved, CAL_M4_MIN_CATALYST,
         f"Накоплено {catalyst_resolved} resolved catalyst-предсказаний ≥ {CAL_M4_MIN_CATALYST} — разблокирован v2-C",
         "Запустить backtested catalyst calibration по спеке v2-C (docs/investment/TODO.md → v2-C): "
         "calibration curve P(realized | predicted), Brier/log loss, multiplicative factor в synthesizer. "
         f"Отчёт → Claude-Memory/calibration/catalyst-calibration-{today.isoformat()}.md.",
         "§M4")

    catalyst_part = (f"{catalyst_resolved}/{CAL_M4_MIN_CATALYST}"
                     if catalyst_resolved is not None else f"н/д/{CAL_M4_MIN_CATALYST}")
    progress_line = (
        f"Калибровка: clean-исходов {n_clean}/{CAL_M1_MIN_CLEAN} (M1) · "
        f"ad-hoc отчётов {n_adhoc}/{CAL_M2_MIN_ADHOC} (M2) · "
        f"до пере-рейтинга источников {n_clean}/{CAL_M3_MIN_CLEAN} (M3) · "
        f"catalyst-исходов {catalyst_part} (M4)"
    )
    if n_interim or n_shock or n_pending:
        progress_line += (f" · вне зачёта: interim {n_interim}, shock {n_shock}, "
                          f"незаполненных стабов {n_pending}")

    return {
        "counts": {
            "n_clean": n_clean,
            "n_clean_level": n_clean_level,
            "n_clean_event": n_clean_event,
            "n_interim": n_interim,
            "n_shock_excluded": n_shock,
            "n_pending_stubs": n_pending,
            "n_adhoc_reports": n_adhoc,
            "n_skill_reports": n_skill_reports,
            "catalyst_resolved": catalyst_resolved,
        },
        "progress_line": progress_line,
        "milestones": milestones,
        "alerts": alerts,
    }


def compute(payload: dict) -> dict:
    today = parse_date(payload.get("today")) or date.today()
    n_red = int(payload.get("n_red_days", DEFAULT_N_RED))
    # n_yellow_days был использован для «приближается» (yellow upcoming).
    # Категория убрана — параметр игнорируется, оставлен только в output для аудита payload.
    n_yellow = int(payload.get("n_yellow_days", DEFAULT_N_YELLOW))
    max_searches = int(payload.get("max_web_searches", DEFAULT_MAX_SEARCHES))

    files = payload.get("forecasts") or []
    files_skipped: list[dict] = []
    active = []
    for f in files:
        f_type = f.get("type")
        if f_type not in ("forecast-events", "scenario-events"):
            files_skipped.append({
                "basename": f.get("basename"),
                "reason": f"unsupported_type:{f_type}",
            })
            continue
        if (f.get("status") or "active") != "active":
            files_skipped.append({
                "basename": f.get("basename"),
                "reason": f"status={f.get('status')}",
            })
            continue
        active.append(f)

    processed = [process_forecast(f, today, n_red) for f in active]

    # Шаг 3f — catalyst[]: синтетические записи из weekly_review_catalysts
    weekly_review_catalysts = payload.get("weekly_review_catalysts") or []
    if weekly_review_catalysts:
        processed.extend(_process_weekly_review_catalysts(weekly_review_catalysts, today, n_red))

    # Шаг 3g — события условий: определения conditions@2 (`conditions` — список записей или документ целиком)
    cdefs = payload.get("conditions") or []
    if isinstance(cdefs, dict):
        cdefs = cdefs.get("conditions") or []
    if cdefs:
        processed.extend(_process_condition_events(cdefs, today, n_red, payload.get("prior_condition_findings")))

    priority = assign_priority(processed)
    plan = build_web_search_plan(processed, max_searches)

    # Калибровочный сторож — по ВСЕМ файлам payload (до active-фильтра):
    # исходы живут в основном в superseded/expired.
    catalyst_resolved = payload.get("catalyst_resolved_count")
    calibration = compute_calibration_milestones(
        files,
        payload.get("calibration_files") or [],
        today,
        catalyst_resolved=int(catalyst_resolved) if catalyst_resolved is not None else None,
    )

    return {
        "today": today.isoformat(),
        "n_red_days": n_red,
        "n_yellow_days": n_yellow,
        "files_processed": len(processed),
        "files_skipped": files_skipped,
        "active_files": processed,
        "priority_buckets": priority,
        "web_search_plan": plan,
        "calibration": calibration,
        "portfolio_watch": portfolio_position_watch(processed),
        "condition_findings": condition_findings_template(processed),
        "monitoring_checked": monitoring_checked_template(active, processed),
    }


def cmd_compute(args: argparse.Namespace) -> int:
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    result = compute(payload)
    indent = 2 if args.pretty else None
    serialized = json.dumps(result, ensure_ascii=False, indent=indent)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        print(serialized)
    return 0


def cmd_post_filter(args: argparse.Namespace) -> int:
    search_from = parse_date(args.search_from)
    if search_from is None:
        print("error: --search-from is required", file=sys.stderr)
        return 2
    event_date = parse_date(args.event_date) if args.event_date else None
    verdict = post_filter_event(event_date, search_from)
    print(verdict)
    return 0 if verdict == "keep" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detеrministic alert planner for forecast-monitor."
    )
    sub = parser.add_subparsers(dest="cmd")

    p_compute = sub.add_parser("compute", help="Build alert plan (default).")
    p_compute.add_argument("--input", "-i")
    p_compute.add_argument("--output", "-o")
    p_compute.add_argument("--pretty", action="store_true")

    p_filter = sub.add_parser("post-filter", help="Step 4.1: filter web_search event by date.")
    p_filter.add_argument("--search-from", required=True, help="YYYY-MM-DD")
    p_filter.add_argument("--event-date", help="YYYY-MM-DD; omit/empty → 'undefined'")

    parser.add_argument("--input", "-i", help=argparse.SUPPRESS)
    parser.add_argument("--output", "-o", help=argparse.SUPPRESS)
    parser.add_argument("--pretty", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.cmd == "post-filter":
        return cmd_post_filter(args)
    return cmd_compute(args)


if __name__ == "__main__":
    sys.exit(main())

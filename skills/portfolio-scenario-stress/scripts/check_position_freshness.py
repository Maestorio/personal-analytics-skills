#!/usr/bin/env python3
"""
check_position_freshness.py — детерминированная проверка свежести `sanctions_position`.

Зачем. Позиции бумаг на санкционной шкале — слепок статуса эмитентов на дату.
Новый пакет или снятие мер делают слепок неверным, но числа остаются
правдоподобными, и устаревание НЕЗАМЕТНО. Поэтому прогон стресса спрашивает не
«помнит ли кто-нибудь», а «сколько дней прошло и что за это время случилось».

Что делает скрипт: читает дату `as_of` и список тикеров из файла значений,
считает устаревание, строит поисковые запросы. Что НЕ делает: не ищет в сети и
не решает, менять ли числа. Поиск — отдельные субагенты по построенному плану,
решение — владелец по рубрике (`/sanctions-positions`).

Запуск:
    python3 check_position_freshness.py \\
        --positions references/sanctions-positions.yaml \\
        [--today 2026-09-15] [--force] [--pretty]

Выход — JSON:
    {"as_of", "today", "days_stale", "stale_after_days", "needs_check",
     "reason", "tickers", "priority_tickers", "search_plan": [...]}

Код возврата: 0 — проверка не нужна; 3 — нужна (не 1/2: это не ошибка, а вердикт,
и его надо отличать от сбоя). 2 — файл не найден или битый.

stdlib + PyYAML.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_STALE_AFTER_DAYS = 30
# Сколько тикеров кладём в один запрос: длинный список размывает выдачу,
# короткий множит число запросов. Шесть — компромисс, подобранный под формат
# санкционных пресс-релизов (они перечисляют компании пачками).
TICKERS_PER_QUERY = 6


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        sys.stderr.write(
            "ERROR: модуль 'yaml' не установлен. "
            "Установить: pip install pyyaml --break-system-packages\n"
        )
        raise SystemExit(2)
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        sys.stderr.write(f"ERROR: {path} — ожидался YAML-объект\n")
        raise SystemExit(2)
    return doc


def _parse_date(v: Any, field: str) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        sys.stderr.write(f"ERROR: {field} = {v!r} — не дата ISO YYYY-MM-DD\n")
        raise SystemExit(2)


def build_search_plan(
    tickers: list[str], as_of: date, today: date,
    per_query: int = TICKERS_PER_QUERY,
) -> list[dict[str, Any]]:
    """
    Детерминированный план поиска: тикеры в стабильном порядке, разбиты пачками.
    Формулировка одна и та же от прогона к прогону — иначе результаты нельзя
    сравнивать между пересмотрами.
    """
    ordered = sorted(tickers)
    window = f"с {as_of.isoformat()} по {today.isoformat()}"
    plan: list[dict[str, Any]] = []
    for i in range(0, len(ordered), max(1, per_query)):
        chunk = ordered[i:i + max(1, per_query)]
        plan.append({
            "tickers": chunk,
            "query_ru": (
                f"новые санкции или снятие санкций {window} в отношении: "
                f"{', '.join(chunk)} — SDN OFAC, санкции ЕС, санкции Великобритании"
            ),
            "query_en": (
                f"Russia sanctions changes {as_of.isoformat()}..{today.isoformat()} "
                f"OFAC SDN designation OR delisting: {', '.join(chunk)}"
            ),
        })
    return plan


def check(doc: dict[str, Any], today: date, force: bool = False) -> dict[str, Any]:
    as_of = _parse_date(doc.get("as_of"), "as_of")
    positions = doc.get("positions")
    if not isinstance(positions, dict) or not positions:
        sys.stderr.write("ERROR: блок positions пуст или не dict\n")
        raise SystemExit(2)
    stale_after = doc.get("stale_after_days", DEFAULT_STALE_AFTER_DAYS)
    try:
        stale_after = int(stale_after)
    except (TypeError, ValueError):
        stale_after = DEFAULT_STALE_AFTER_DAYS

    days = (today - as_of).days
    tickers = sorted(str(t) for t in positions)
    # Низкая и средняя уверенность в юридическом статусе — вперёд очереди:
    # именно там ошибка вероятнее, а не там, где бумага крупнее.
    priority = sorted(
        str(t) for t, v in positions.items()
        if isinstance(v, dict) and str(v.get("confidence", "")).lower() in ("low", "medium")
    )

    if days < 0:
        needs, reason = True, f"as_of {as_of.isoformat()} в будущем относительно {today.isoformat()}"
    elif force:
        needs, reason = True, "запрошено принудительно (--force)"
    elif days > stale_after:
        needs, reason = True, f"с даты значений прошло {days} дн (порог {stale_after})"
    else:
        needs, reason = False, f"значения свежие: {days} дн из допустимых {stale_after}"

    return {
        "as_of": as_of.isoformat(),
        "today": today.isoformat(),
        "days_stale": days,
        "stale_after_days": stale_after,
        "needs_check": needs,
        "reason": reason,
        "tickers": tickers,
        "priority_tickers": priority,
        "search_plan": build_search_plan(tickers, as_of, today) if needs else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Проверка свежести sanctions_position перед прогоном стресса")
    ap.add_argument("--positions", required=True, type=Path,
                    help="YAML со значениями (references/sanctions-positions.yaml внутри скилла)")
    ap.add_argument("--today", default=None,
                    help="Дата отсчёта YYYY-MM-DD (по умолчанию системная)")
    ap.add_argument("--force", action="store_true",
                    help="Потребовать проверку независимо от возраста значений")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if not args.positions.exists():
        sys.stderr.write(f"ERROR: файл значений не найден: {args.positions}\n")
        return 2
    today = _parse_date(args.today, "--today") if args.today else date.today()
    result = check(_load_yaml(args.positions), today, force=args.force)

    kw: dict[str, Any] = {"ensure_ascii": False}
    if args.pretty:
        kw["indent"] = 2
    sys.stdout.write(json.dumps(result, **kw) + "\n")
    # 3 = «нужна проверка». Отдельный код, чтобы вердикт не путался со сбоем.
    return 3 if result["needs_check"] else 0


if __name__ == "__main__":
    sys.exit(main())

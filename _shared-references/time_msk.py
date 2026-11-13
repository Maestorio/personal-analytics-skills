#!/usr/bin/env python3
"""
time_msk.py — единый помощник времени записываемых полей (schema.md §1 п.4).

Формат: `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00` — московское время (без перехода на летнее), секунды, явный пояс.
Наивного `datetime.now()` и UTC с `Z` в записываемых полях быть не должно: строки такого формата
сравниваются лексикографически, поэтому порядок строк = порядок времени.

  now_iso()            — сейчас, МСК;
  day_start_iso(date)  — `…T00:00:00+03:00` для даты (строка ГГГГ-ММ-ДД или date) — оценка при миграциях;
  day_end_iso(date)    — `…T23:59:59+03:00` — последний миг дня (конец окна условия);
  today_iso()          — сегодняшняя дата МСК `ГГГГ-ММ-ДД`;
  to_msk_iso(value, naive_is_msk=False)
                       — перевод произвольной ISO-строки (с `Z` или поясом — пересчёт; без пояса — UTC, а при
                         naive_is_msk=True — уже МСК, как время сделки/котировки MOEX «ГГГГ-ММ-ДД ЧЧ:ММ:СС») в МСК;
  is_msk_iso(value)    — строка уже в каноническом формате.

В репозитории модуль лежит в `_shared-references/`, в упакованном скилле — в `scripts/` (pack.sh кладёт файл
рядом, если скрипт делает `import time_msk`). Зависимости: stdlib.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))
_RE_MSK = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$")


def now_iso() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def day_start_iso(d) -> str:
    if isinstance(d, (datetime, date)):
        d = d.strftime("%Y-%m-%d")
    return f"{str(d)[:10]}T00:00:00+03:00"


def day_end_iso(d) -> str:
    return day_start_iso(d)[:10] + "T23:59:59+03:00"


def today_iso() -> str:
    return now_iso()[:10]


def is_msk_iso(value) -> bool:
    return isinstance(value, str) and bool(_RE_MSK.match(value))


def to_msk_iso(value: str, naive_is_msk: bool = False) -> str:
    """ISO-строка → МСК. `Z` — UTC; строка без пояса — UTC (так писал сервер) или МСК (naive_is_msk); с поясом — пересчёт."""
    s = str(value).strip()
    if is_msk_iso(s):
        return s
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK if naive_is_msk else timezone.utc)
    return dt.astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")

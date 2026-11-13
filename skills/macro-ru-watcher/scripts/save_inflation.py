#!/usr/bin/env python3
"""
save_inflation.py — запись недельной инфляции в файл модели `macro-snapshots/inflation/model.jsonl`.

Вход — вывод модели (найденная публикация Росстата/МЭР), поэтому запись идёт через гейт `hub_settings.require_ai`:
при режиме сайта «без ИИ» — код 3, файл не меняется. Файл владельца `owner.jsonl` этот скрипт не трогает —
его пишет только форма сайта (один файл — один писатель); страница берёт самую свежую по `date` запись из двух файлов.

Строка файла (jsonl, дописывание):
  {"date", "week_pct", "week_period", "yoy_pct", "yoy_as_of", "source_url", "source_name", "recorded_at", "author": "model"}
  date         — дата публикации (ГГГГ-ММ-ДД, не позже сегодня, не старше года): по ней считается срок годности
  week_pct     — инфляция за неделю, % (−3…5)
  week_period  — период недели текстом, например «03–09.11»
  yoy_pct      — оценка г/г на дату, % (−5…100)
  yoy_as_of    — дата, на которую оценка г/г (по умолчанию — date)
  source_name  — название источника (обязательно); source_url — ссылка (необязательно, http/https)

Без --apply — только проверка и показ строки. Та же запись два раза подряд — «уже записано», без дублей.
Коды: 0 — ок, 1 — вход не прошёл проверку, 3 — сайт в режиме «без ИИ». Только stdlib.

    python3 save_inflation.py --root "$CM" --date 2026-11-12 --week-pct 0.11 --week-period "03–09.11" \
        --yoy-pct 6.4 --yoy-as-of 2026-11-09 --source-name "Росстат" --source-url https://rosstat.gov.ru/... --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

REL = Path("macro-snapshots") / "inflation" / "model.jsonl"
MSK = timezone(timedelta(hours=3))
FIELDS = ("date", "week_pct", "week_period", "yoy_pct", "yoy_as_of", "source_url", "source_name", "recorded_at", "author")


def _num(v, lo, hi, name, errs):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        errs.append(f"{name}: число от {lo} до {hi}")
        return None
    return round(float(v), 3)


def _day(v, name, today, errs, floor=None):
    try:
        d = date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        d = None
    if d is None:
        errs.append(f"{name}: дата ГГГГ-ММ-ДД")
        return None
    if d > today:
        errs.append(f"{name}: дата из будущего")
        return None
    if floor and d < floor:
        errs.append(f"{name}: старше года — опечатка?")
        return None
    return v


def validate(rec, today: date, author: str, recorded_at: str):
    """→ (строка | None, [ошибки]). Лишние поля отбрасываются; author и recorded_at ставит писатель."""
    errs: list[str] = []
    if not isinstance(rec, dict):
        return None, ["запись — объект"]
    out = {}
    out["date"] = _day(rec.get("date"), "date", today, errs, floor=today - timedelta(days=366))
    out["week_pct"] = _num(rec.get("week_pct"), -3, 5, "week_pct", errs)
    wp = rec.get("week_period")
    wp = wp.strip() if isinstance(wp, str) else ""
    if not 3 <= len(wp) <= 40:
        errs.append("week_period: строка 3–40 символов («03–09.11»)")
    out["week_period"] = wp
    out["yoy_pct"] = _num(rec.get("yoy_pct"), -5, 100, "yoy_pct", errs)
    ya = rec.get("yoy_as_of")
    out["yoy_as_of"] = _day(ya if ya else out["date"], "yoy_as_of", today, errs) if (ya or out["date"]) else None
    url = rec.get("source_url")
    if url in (None, ""):
        url = None
    elif not (isinstance(url, str) and url.startswith(("http://", "https://")) and " " not in url and len(url) <= 300):
        errs.append("source_url: http(s)-ссылка без пробелов, до 300 символов")
    out["source_url"] = url
    sn = rec.get("source_name")
    sn = sn.strip() if isinstance(sn, str) else ""
    if not 2 <= len(sn) <= 80:
        errs.append("source_name: строка 2–80 символов")
    out["source_name"] = sn
    out["recorded_at"] = recorded_at
    out["author"] = author
    return (None, errs) if errs else ({k: out[k] for k in FIELDS}, [])


def same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in FIELDS if k != "recorded_at")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="корень Claude-Memory")
    ap.add_argument("--date", required=True)
    ap.add_argument("--week-pct", type=float, required=True)
    ap.add_argument("--week-period", required=True)
    ap.add_argument("--yoy-pct", type=float, required=True)
    ap.add_argument("--yoy-as-of")
    ap.add_argument("--source-name", required=True)
    ap.add_argument("--source-url")
    ap.add_argument("--today", help="ГГГГ-ММ-ДД (тесты); по умолчанию — сегодня по МСК")
    ap.add_argument("--apply", action="store_true", help="записать (без флага — только проверка)")
    a = ap.parse_args(argv)
    now = datetime.now(MSK)
    today = date.fromisoformat(a.today) if a.today else now.date()
    rec, errs = validate({"date": a.date, "week_pct": a.week_pct, "week_period": a.week_period, "yoy_pct": a.yoy_pct,
                          "yoy_as_of": a.yoy_as_of, "source_url": a.source_url, "source_name": a.source_name},
                         today, "model", now.strftime("%Y-%m-%dT%H:%M:%S+03:00"))
    if errs:
        print("✗ запись не прошла проверку:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    path = Path(os.path.expanduser(a.root)) / REL
    print(json.dumps(rec, ensure_ascii=False))
    if not a.apply:
        print("✓ проверка зелёная. Запись: повторить с --apply")
        return 0
    hub_settings.require_ai(path, "save_inflation.py --apply", "запись недельной инфляции", zones=("macro-snapshots",))   # вход — вывод модели
    old = path.read_bytes() if path.is_file() else b""
    for ln in old.decode("utf-8", "replace").splitlines():
        try:
            if same(json.loads(ln), rec):
                print("✓ уже записано — без изменений")
                return 0
        except ValueError:
            continue
    if old and not old.endswith(b"\n"):
        old += b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(old + (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(tmp, path)
    print(f"✓ записано: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Точные даты поездки из финального плана (Stage 5) → строки `start`/`end`
для `trip.yaml`.

Ничего не пишет: печатает строки, которые пользователь вставляет в
`trip.yaml` сам (manual save). Нет дат — так и говорит: поездка остаётся без
точных дат, о ней известен только `season` — это нормальное состояние.

Правило чтения дат — то же, что у HTML-экспорта Stage 5:
  • дата дня — «(ДД.ММ» в заголовке «День N (ДД.ММ Дн). …»;
  • год — из `trip_id` (`…_ГГГГ-ММ`) во frontmatter, в имени папки или
    файла, иначе из `season`/`start_date` frontmatter;
  • переход через январь (28.12 → 03.01) переносит год на +1.

Запуск:
    python3 scripts/trip_dates.py trips/{trip_id}          # папка поездки
    python3 scripts/trip_dates.py trips/{trip_id}/5_….md   # конкретный файл
    python3 scripts/trip_dates.py … --json
Коды выхода: 0 — разобрано (с датами или без), 2 — нет файла Stage 5.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HEADING_RE = re.compile(r"^#{1,6}\s+\**\s*День\s+(\d+)\b(.*)$")
_DAY_DATE_RE = re.compile(r"\((\d{2})\.(\d{2})")
_TRIP_YM_RE = re.compile(r"(20\d{2})[-_](\d{2})")
_VERSION_RE = re.compile(r"_v(\d+)(?:[._](\d+))?")


def pick_stage5(path: Path) -> Path | None:
    """Файл Stage 5 в папке поездки: `5_*.md` старшей версии (лог стадии —
    не артефакт, пропускается). Передан файл — он и есть."""
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    cands = [p for p in path.glob("5_*.md") if not p.name.endswith("_stage_log.md")]
    if not cands:
        return None

    def ver(p: Path):
        m = _VERSION_RE.search(p.stem)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)
    return max(cands, key=lambda p: (ver(p), p.name))


def _frontmatter(text: str) -> dict:
    m = re.match(r"^﻿?-{3,}\s*\n(.*?)\n-{3,}\s*\n", text, re.S)
    out = {}
    if m:
        for ln in m.group(1).splitlines():
            kv = re.match(r"^([A-Za-z_]\w*):\s*(.*?)\s*(?:#.*)?$", ln)
            if kv:
                out[kv.group(1)] = kv.group(2).strip().strip("\"'")
    return out


def resolve_year(text: str, path: Path) -> int | None:
    fm = _frontmatter(text)
    probe = " ".join(x for x in (fm.get("trip_id"), path.parent.name, path.stem,
                                 fm.get("season"), fm.get("start_date")) if x)
    m = _TRIP_YM_RE.search(probe)
    return int(m.group(1)) if m else None


def day_pairs(text: str) -> list[tuple[int, str]]:
    """[(номер дня, 'ДД.ММ')] по заголовкам дней, в порядке документа."""
    out = []
    for ln in text.splitlines():
        h = _HEADING_RE.match(ln.strip())
        if not h:
            continue
        d = _DAY_DATE_RE.search(h.group(2))
        if d:
            out.append((int(h.group(1)), f"{d.group(1)}.{d.group(2)}"))
    return out


def iso_from_daydates(pairs, year: int) -> dict:
    """Копия правила экспорта (stages_html/stage5.iso_from_daydates): год +1
    при переходе через январь. Совпадение закреплено тестом."""
    out: dict[int, str] = {}
    prev_month = None
    for num, raw in pairs:
        day_s, mon_s = raw.split(".")
        month = int(mon_s)
        if prev_month is not None and month < prev_month:
            year += 1
        prev_month = month
        out[int(num)] = f"{year:04d}-{month:02d}-{int(day_s):02d}"
    return out


def trip_dates(path: Path) -> dict:
    """{'file', 'start', 'end', 'days', 'reason'} — start/end None, если дат нет."""
    f = pick_stage5(path)
    if f is None:
        return {"file": None, "start": None, "end": None, "days": 0,
                "reason": "нет файла Stage 5 (5_*.md)"}
    text = f.read_text(encoding="utf-8")
    pairs = day_pairs(text)
    res = {"file": str(f), "start": None, "end": None, "days": len(pairs), "reason": ""}
    if not pairs:
        res["reason"] = "в заголовках дней нет даты «(ДД.ММ …)»"
        return res
    year = resolve_year(text, f)
    if year is None:
        res["reason"] = "год не найден (нет …_ГГГГ-ММ в trip_id, имени папки/файла, season)"
        return res
    iso = sorted(iso_from_daydates(pairs, year).values())
    res["start"], res["end"] = iso[0], iso[-1]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="start/end для trip.yaml из файла Stage 5")
    ap.add_argument("path", help="папка поездки или файл 5_*.md")
    ap.add_argument("--json", action="store_true", help="вывод JSON")
    a = ap.parse_args(argv)
    r = trip_dates(Path(a.path))
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
        return 2 if r["file"] is None else 0
    if r["file"] is None:
        print(f"Не найдено: {r['reason']}", file=sys.stderr)
        return 2
    print(f"# из {Path(r['file']).name}")
    if r["start"]:
        print(f"start: {r['start']}")
        print(f"end: {r['end']}")
    else:
        print(f"# точных дат нет — {r['reason']}; в trip.yaml остаётся только season")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Миграция журнала плана `Portfolio/plan-journal.jsonl`: время в МСК и поле `decision_id` (schema.md §1 п.4, §4.1).

Что делает с каждой строкой:
  * `ts` из UTC `…Z` (или без пояса — так писал сервер, считается UTC) переводится в МСК `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00`
    (пересчёт, а не подмена суффикса: 21:40Z — это 00:40 следующего дня по Москве); `ts` уже в МСК не меняется;
  * строке без поля `decision_id` добавляется `decision_id: null` в конец; поле `who` и всё остальное — без изменений;
  * нечитаемые строки и пустые остаются как есть (в отчёте — «пропущено»); порядок строк сохраняется.
Идемпотентен: повторный прогон по результату ничего не меняет. После перевода самопроверка: у всех разобранных строк
`ts` в каноническом формате и есть `decision_id`; иначе код выхода 1 и файл не пишется.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 migrate_plan_journal_ts.py --in plan-journal.jsonl --out plan-journal.new.jsonl
        (--out совпадает с --in — правка на месте с копией `<имя>.pre-ds.bak`, существующую копию не перезаписывает)
ВНИМАНИЕ: на живом журнале — только после архивации (archive_pre_ds.py) и «да» владельца; сервер в это время не пишет.
Зависимости: stdlib (time_msk — из _shared-references/).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[3] / "_shared-references"
sys.path.insert(0, str(_SHARED))
import time_msk  # noqa: E402


def migrate_text(text: str):
    """→ (новый текст, счётчики). Строки без изменений сохраняются побайтно."""
    out, cnt = [], {"rows": 0, "ts_converted": 0, "decision_id_added": 0, "skipped": 0}
    for ln in text.splitlines(keepends=True):
        body = ln.rstrip("\r\n")
        if not body.strip():
            out.append(ln)
            continue
        try:
            row = json.loads(body)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            cnt["skipped"] += 1
            out.append(ln)
            continue
        cnt["rows"] += 1
        changed = False
        ts = row.get("ts")
        if isinstance(ts, str) and not time_msk.is_msk_iso(ts):
            try:
                row["ts"] = time_msk.to_msk_iso(ts)
                cnt["ts_converted"] += 1
                changed = True
            except ValueError:
                cnt["skipped"] += 1
        if "decision_id" not in row:
            row["decision_id"] = None
            cnt["decision_id_added"] += 1
            changed = True
        out.append(json.dumps(row, ensure_ascii=False) + ln[len(body):] if changed else ln)
    return "".join(out), cnt


def check_text(text: str) -> list[str]:
    """Самопроверка формата: список нарушений (пуст — всё в порядке)."""
    bad = []
    for i, ln in enumerate(text.splitlines(), 1):
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if not time_msk.is_msk_iso(row.get("ts")):
            bad.append(f"строка {i}: ts {row.get('ts')!r} не в формате …+03:00")
        if "decision_id" not in row:
            bad.append(f"строка {i}: нет decision_id")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="src", required=True, type=Path)
    ap.add_argument("--out", dest="dst", type=Path, help="куда писать; без --out — только отчёт")
    a = ap.parse_args(argv)
    text = a.src.read_text(encoding="utf-8")
    new, cnt = migrate_text(text)
    bad = check_text(new)
    print(f"строк с данными: {cnt['rows']}; ts переведено в МСК: {cnt['ts_converted']}; "
          f"decision_id добавлено: {cnt['decision_id_added']}; пропущено (нечитаемые): {cnt['skipped']}")
    if bad:
        print("САМОПРОВЕРКА НЕ ПРОЙДЕНА:\n  " + "\n  ".join(bad[:20]), file=sys.stderr)
        return 1
    print("самопроверка: все строки с ts …+03:00 и decision_id")
    if a.dst is None:
        print("(сухой прогон: файл не записан)")
        return 0
    if a.dst.resolve() == a.src.resolve():
        bak = a.src.with_name(a.src.name + ".pre-ds.bak")
        if bak.exists():
            print(f"копия {bak.name} уже есть — файл не тронут", file=sys.stderr)
            return 1
        shutil.copy2(a.src, bak)
    a.dst.write_text(new, encoding="utf-8", newline="")
    print(f"записано: {a.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Правка приватной карты `zenmoney-map.md` — единственный писатель карты (решение 2026-10-06).

Карта — правила для всех будущих итогов (роли счетов, исключения, поездки). Поэтому:
скрипт меняет только строки в названном разделе и никогда не пишет файл целиком из
модели; по умолчанию dry-run — печатает diff; запись — только с хешем файла, который
видел пользователь (`--expect`), с копией прежней версии и атомарной заменой.
Удаление строки — отдельная команда (`remove-row`), её подтверждают отдельно.

  hash        --map MAP
              sha256 текущей карты — передать в --expect при записи.
  add-row     --map MAP --section "Поездки" --row "| … |" [--row …] [--note "…"] [--expect H --write]
              Строки в конец первой таблицы раздела (число колонок = как у шапки).
  set-row     --map MAP --section S --match "#Сибирь'24" --row "| … |" [--note] [--expect H --write]
              Заменить строку таблицы, где первая ячейка содержит --match (ровно одну).
  remove-row  --map MAP --section S --match "…" [--note] [--expect H --write]
  add-line    --map MAP --section S --line "- …" [--line …] [--note] [--expect H --write]
              Пункт в конец раздела (списки «Известные странности» и т. п.).

С --write: файл перечитывается и сравнивается с --expect (изменился → стоп, ничего не
записано); копия — `zenmoney-map.backup-ГГГГ-ММ-ДД[буква].md` рядом (как делались
ручные копии); в «Мета» — «- Обновлено:» (дата и --note) и «- Предыдущая версия:» (эта копия).
Только stdlib, JSON-сводка + diff в stdout. Коды: 0 — ок, 2 — blocking.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import string
import sys
from datetime import date
from pathlib import Path

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402


class Blocking(Exception):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section_bounds(lines, name):
    """[начало, конец) раздела «## name» — до следующего «## » (без последнего «---»)."""
    starts = [i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip() == name]
    if len(starts) != 1:
        raise Blocking(f"раздел «{name}» найден {len(starts)} раз — нужен ровно один")
    s = starts[0]
    e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while e > s + 1 and lines[e - 1].strip() in ("", "---"):
        e -= 1
    return s, e


def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table(lines, s, e):
    """(шапка, первая строка данных, конец таблицы) первой таблицы раздела."""
    head = next((i for i in range(s, e) if lines[i].lstrip().startswith("|")), None)
    if head is None or head + 1 >= e or not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[head + 1]):
        raise Blocking("в разделе нет таблицы")
    end = head + 2
    while end < e and lines[end].lstrip().startswith("|"):
        end += 1
    return head, head + 2, end


def check_row(row, ncols):
    if not row.strip().startswith("|") or not row.strip().endswith("|"):
        raise Blocking(f"строка таблицы должна начинаться и кончаться «|»: {row!r}")
    if len(cells(row)) != ncols:
        raise Blocking(f"в строке {len(cells(row))} колонок, в таблице {ncols}: {row!r}")
    if "\n" in row:
        raise Blocking("строка таблицы — одна строка")


def edit(text, cmd, section, rows=(), match=None, add_lines=()):
    lines = text.split("\n")
    s, e = section_bounds(lines, section)
    if cmd == "add-line":
        for l in add_lines:
            if "\n" in l or not l.strip():
                raise Blocking("пункт — одна непустая строка")
        lines[e:e] = list(add_lines)
        return "\n".join(lines)
    head, first, end = table(lines, s, e)
    ncols = len(cells(lines[head]))
    if cmd == "add-row":
        for r in rows:
            check_row(r, ncols)
        lines[end:end] = list(rows)
        return "\n".join(lines)
    hits = [i for i in range(first, end) if match in cells(lines[i])[0]]
    if len(hits) != 1:
        raise Blocking(f"«{match}» в первой ячейке найдено {len(hits)} раз — нужна ровно одна строка")
    if cmd == "set-row":
        check_row(rows[0], ncols)
        lines[hits[0]] = rows[0]
    else:
        del lines[hits[0]]
    return "\n".join(lines)


def stamp(text, today, note):
    """«- Обновлено: …» в «Мета» — сегодня и что сделано."""
    new = f"- Обновлено: {today}" + (f" ({note})" if note else "")
    out, n = re.subn(r"(?m)^- Обновлено:.*$", new, text, count=1)
    return out if n else text


def backup_path(map_path: Path, today):
    for suf in [""] + list(string.ascii_lowercase):
        p = map_path.with_name(f"{map_path.stem}.backup-{today}{suf}.md")
        if not p.exists():
            return p
    raise Blocking("слишком много копий за день")


def run(a):
    mp = Path(a.map)
    if not mp.exists():
        raise Blocking(f"карты нет: {mp}")
    text = mp.read_text(encoding="utf-8")
    if a.cmd == "hash":
        return {"sha256": sha(text)}
    if a.cmd in ("add-row",) and not a.row:
        raise Blocking("нужен --row")
    if a.cmd == "set-row" and (not a.row or len(a.row) != 1 or not a.match):
        raise Blocking("set-row: ровно один --row и --match")
    if a.cmd == "remove-row" and not a.match:
        raise Blocking("remove-row: нужен --match")
    if a.cmd == "add-line" and not a.line:
        raise Blocking("нужен --line")
    today = a.date or date.today().isoformat()
    new = stamp(edit(text, a.cmd, a.section, a.row or [], a.match, a.line or []), today, a.note)
    diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), "карта", "карта после", n=1))
    out = {"section": a.section, "command": a.cmd, "sha256_before": sha(text), "written": False, "diff": diff}
    if a.write:
        if not a.expect:
            raise Blocking("запись только с --expect <sha256> — хеш карты, которую видел пользователь")
        current = mp.read_text(encoding="utf-8")
        if sha(current) != a.expect:
            raise Blocking("карта изменилась после чтения — перечитай, покажи diff заново; ничего не записано")
        bak = backup_path(mp, today)
        shutil.copy2(mp, bak)
        # «Предыдущая версия» в «Мета» — на только что сделанную копию
        new = re.sub(r"(?m)^- Предыдущая версия:.*$", f"- Предыдущая версия: `{bak.name}`", new, count=1)
        tmp = mp.with_suffix(".md.tmp")
        tmp.write_text(new, encoding="utf-8")
        os.replace(tmp, mp)
        out.update(written=True, backup=bak.name, sha256_after=sha(new))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["hash", "add-row", "set-row", "remove-row", "add-line"])
    p.add_argument("--map", required=True)
    p.add_argument("--section")
    p.add_argument("--row", action="append")
    p.add_argument("--line", action="append")
    p.add_argument("--match")
    p.add_argument("--note", help="что изменилось — в «Обновлено» раздела «Мета»")
    p.add_argument("--date", help="сегодня (YYYY-MM-DD), по умолчанию — системная дата")
    p.add_argument("--expect", help="sha256 карты, показанной пользователю (из hash / dry-run)")
    p.add_argument("--write", action="store_true")
    a = p.parse_args(argv)
    if a.write and a.cmd != "hash":
        hub_settings.require_ai(a.map, "map_edit.py --write", "правка карты ZenMoney", zones=("ZenMoney",))   # вход — вывод модели
    try:
        if a.cmd != "hash" and not a.section:
            raise Blocking("нужен --section")
        out = run(a)
    except Blocking as e:
        print(json.dumps({"blocking": str(e)}, ensure_ascii=False))
        return 2
    diff = out.pop("diff", "")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if diff:
        print(diff)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
update_index.py — детерминированное обновление INDEX.md и _sync_log.md.

Зачем: шаг F4 (и его аналоги в остальных workflow) требует дописать строку в
таблицу INDEX и запись в _sync_log. Выполняемый моделью, он стоит чтения
Portfolio/INDEX.md (138 КБ) и _sync_log.md (327 КБ) целиком — при том, что сама
операция чисто механическая: найти секцию, вставить строку после шапки таблицы,
дописать абзац в «## Метаданные», добавить строку в конец лога.

Модель формирует ТЕКСТ строки (прозу про содержание артефакта — её не
автоматизировать), скрипт отвечает за размещение, порядок, бэкап и идемпотентность.

Подкоманды (все читают JSON со stdin, печатают JSON-отчёт в stdout):

  add-rows    вставить строки в таблицу указанной секции; "position": "top" (по умолчанию, newest-first),
              "end" (в конец таблицы) или "auto" (по направлению дат таблицы: растут вниз — в конец, иначе сверху)
  add-meta    дописать «- Обновлено: ...» в секцию «## Метаданные»
  sync-log    дописать записи в конец _sync_log.md

Примеры:
  echo '{"index_path": ".../Portfolio/INDEX.md",
          "section": "### weekly-reviews/",
          "rows": ["| weekly-review-stock-2026-08-15.yaml | weekly-stocks-review | 2026-08-15 | ... |"],
          "backup_dir": ".../Portfolio/.backups"}' | python3 update_index.py add-rows

  echo '{"index_path": "...", "line": "2026-08-15 (weekly-review-stock — ...)"}' \
    | python3 update_index.py add-meta

  echo '{"log_path": ".../_sync_log.md",
          "entries": ["2026-08-15 | save-to-library | Workflow F | ..."]}' \
    | python3 update_index.py sync-log

Флаг "dry_run": true — ничего не пишет, отчёт формируется как при записи.
stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

META_HEADER = "## Метаданные"
META_PREFIX = "- Обновлено: "

# Разделительная строка markdown-таблицы: |---|---|...
_TABLE_SEP = re.compile(r"^\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*$")
# Имя файла в первой колонке строки таблицы — ключ идемпотентности
_FIRST_CELL = re.compile(r"^\s*\|\s*([^|]+?)\s*\|")


def _fail(msg: str, **extra) -> None:
    out = {"ok": False, "error": msg}
    out.update(extra)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(1)


def _read(path: str) -> str:
    if not os.path.isfile(path):
        _fail(f"файл не найден: {path}")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _backup(path: str, backup_dir: str | None, dry_run: bool) -> str | None:
    """Бэкап перед мутацией — тот же контракт, что у Workflow F/M вручную."""
    if not backup_dir:
        return None
    if not dry_run:
        hub_settings.require_ai(path, "update_index.py", "правка INDEX/_sync_log", zones=("Portfolio", "scenarios"))   # вход — вывод модели
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    dest = os.path.join(backup_dir, f"{stem}-{stamp}{ext}")
    if dry_run:
        return dest
    os.makedirs(backup_dir, exist_ok=True)
    with open(path, encoding="utf-8") as src, open(dest, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    return dest


def _write(path: str, content: str, dry_run: bool) -> None:
    if dry_run:
        return
    hub_settings.require_ai(path, "update_index.py", "правка INDEX/_sync_log", zones=("Portfolio", "scenarios"))   # вход — вывод модели
    tmp = f"{path}.tmp-update-index"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def _find_section(lines: list[str], section: str) -> int:
    """Индекс строки-заголовка секции. Сравнение по нормализованному тексту."""
    want = section.strip().lstrip("#").strip().casefold()
    for i, ln in enumerate(lines):
        if ln.startswith("#") and ln.strip().lstrip("#").strip().casefold() == want:
            return i
    return -1


def _section_bounds(lines: list[str], start: int) -> int:
    """Конец секции — следующий заголовок того же или более высокого уровня."""
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            if lvl <= level:
                return i
    return len(lines)


def _first_cell(row: str) -> str:
    m = _FIRST_CELL.match(row)
    return m.group(1).strip() if m else ""


_ROW_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def table_insert_pos(lines: list[str], sep: int, end: int, position: str) -> int:
    """Позиция вставки строк в таблицу с разделителем `sep` (секция кончается на `end`).

    top — сразу под шапкой; end — после последней строки таблицы; auto — по двум последним строкам с разными
    датами: дата растёт вниз → в конец, иначе сверху (у пар .md/.yaml дата одна — берётся предыдущая другая).
    """
    last = sep
    while last + 1 < end and lines[last + 1].strip().startswith("|"):
        last += 1
    if position == "end":
        return last + 1
    if position == "auto":
        dates = [m.group(0) for ln in lines[sep + 1:last + 1] if (m := _ROW_DATE.search(ln))]
        if dates:
            prev = next((d for d in reversed(dates) if d != dates[-1]), None)
            if prev is not None and prev < dates[-1]:
                return last + 1
    return sep + 1


def cmd_add_rows(payload: dict) -> dict:
    path = payload.get("index_path") or _fail("нужен index_path")
    section = payload.get("section") or _fail("нужен section")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        _fail("нужен непустой список rows")
    dry = bool(payload.get("dry_run"))
    replace = bool(payload.get("replace"))
    position = payload.get("position") or "top"
    if position not in ("top", "end", "auto"):
        _fail("position — top | end | auto")

    content = _read(path)
    lines = content.split("\n")
    sec = _find_section(lines, section)
    if sec < 0:
        _fail(f"секция не найдена: {section}",
              hint="заголовки файла — см. grep '^#' по INDEX.md")
    end = _section_bounds(lines, sec)

    sep = -1
    for i in range(sec + 1, end):
        if _TABLE_SEP.match(lines[i]):
            sep = i
            break
    if sep < 0:
        _fail(f"в секции {section} нет markdown-таблицы (строки |---|---|)")

    # Идемпотентность: файл из первой колонки уже присутствует в секции
    existing = {}
    for i in range(sep + 1, end):
        if lines[i].strip().startswith("|"):
            key = _first_cell(lines[i])
            if key:
                existing.setdefault(key, i)

    inserted, skipped, replaced = [], [], []
    fresh = []
    for row in rows:
        row = row.rstrip("\n")
        if not row.strip().startswith("|"):
            _fail(f"строка не выглядит строкой таблицы: {row[:60]}")
        key = _first_cell(row)
        if key and key in existing:
            if replace:
                lines[existing[key]] = row
                replaced.append(key)
            else:
                skipped.append(key)
            continue
        fresh.append(row)
        inserted.append(key or row[:40])

    pos = table_insert_pos(lines, sep, end, position)
    if fresh:
        lines[pos:pos] = fresh

    new_content = "\n".join(lines)
    backup = _backup(path, payload.get("backup_dir"), dry) if (fresh or replaced) else None
    if fresh or replaced:
        _write(path, new_content, dry)

    return {
        "ok": True,
        "command": "add-rows",
        "path": path,
        "section": section,
        "inserted": inserted,
        "replaced": replaced,
        "skipped_existing": skipped,
        "insert_line": pos + 1,
        "position": position,
        "bytes_before": len(content.encode("utf-8")),
        "bytes_after": len(new_content.encode("utf-8")),
        "backup": backup,
        "dry_run": dry,
    }


def cmd_add_meta(payload: dict) -> dict:
    path = payload.get("index_path") or _fail("нужен index_path")
    line = payload.get("line") or _fail("нужен line")
    dry = bool(payload.get("dry_run"))

    content = _read(path)
    lines = content.split("\n")
    sec = _find_section(lines, payload.get("section") or META_HEADER)
    if sec < 0:
        _fail(f"секция не найдена: {payload.get('section') or META_HEADER}")
    end = _section_bounds(lines, sec)

    entry = line if line.startswith(META_PREFIX) else META_PREFIX + line
    if entry in lines[sec:end]:
        return {"ok": True, "command": "add-meta", "path": path,
                "appended": False, "reason": "идентичная запись уже есть",
                "dry_run": dry}

    # вставка после последней непустой строки секции
    pos = end
    while pos - 1 > sec and not lines[pos - 1].strip():
        pos -= 1
    lines[pos:pos] = [entry]

    new_content = "\n".join(lines)
    backup = _backup(path, payload.get("backup_dir"), dry)
    _write(path, new_content, dry)
    return {
        "ok": True,
        "command": "add-meta",
        "path": path,
        "appended": True,
        "insert_line": pos + 1,
        "bytes_before": len(content.encode("utf-8")),
        "bytes_after": len(new_content.encode("utf-8")),
        "backup": backup,
        "dry_run": dry,
    }


def cmd_sync_log(payload: dict) -> dict:
    path = payload.get("log_path") or _fail("нужен log_path")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        _fail("нужен непустой список entries")
    dry = bool(payload.get("dry_run"))

    content = _read(path)
    tail = content if content.endswith("\n") else content + "\n"
    added = []
    for e in entries:
        e = str(e).rstrip("\n")
        if not e.strip():
            continue
        tail += e + "\n"
        added.append(e.split("|")[0].strip() + " …")

    _write(path, tail, dry)
    return {
        "ok": True,
        "command": "sync-log",
        "path": path,
        "appended": len(added),
        "bytes_before": len(content.encode("utf-8")),
        "bytes_after": len(tail.encode("utf-8")),
        "dry_run": dry,
    }


COMMANDS = {
    "add-rows": cmd_add_rows,
    "add-meta": cmd_add_meta,
    "sync-log": cmd_sync_log,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=sorted(COMMANDS))
    args = ap.parse_args()

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"stdin не разобран как JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("stdin должен быть JSON-объектом")

    print(json.dumps(COMMANDS[args.command](payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
validate_report.py

Проверка и раскладка отчёта `health-report@1` для скилла health-labs:
Markdown с шапкой (см. references/report-format.md). Скилл отчёт не пишет —
только проверяет формат и кладёт готовый файл в Health/reports/.

Грамматика шапки намеренно узкая: её же разбирает страница health.html
(parseReportHead), и два парсера обязаны видеть одно и то же.

CLI:
    python3 validate_report.py check REPORT.md [--labs labs.json] [--json]
    python3 validate_report.py save REPORT.md --health HEALTH_DIR --topic ТЕМА [--labs labs.json] [--apply]

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

SCHEMA = "health-report@1"
LEVELS = ("red", "warn", "info", "ok")
SCALARS = ("schema", "title", "date", "data_asof", "summary", "markers")
LISTS = ("flags", "todo")
LIMITS = {"title": 90, "summary": 300, "flag_title": 40, "flag_text": 220,
          "flags": 8, "todo": 10, "todo_item": 160, "markers": 12}
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_RE = re.compile(r"^([a-z_]+):(?:\s(.*))?$")
ITEM_RE = re.compile(r"^\s+-\s+(.*)$")
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-zа-яё0-9-]+\.md$")


def iso_ok(s: str) -> bool:
    if not ISO_RE.match(s or ""):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def parse(text: str):
    """-> (meta, body, errors). meta: скаляры строками, flags/todo — списки."""
    errors: list[str] = []
    text = text.lstrip("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text, ["нет шапки: первая строка файла должна быть «---»"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text, ["шапка не закрыта второй строкой «---»"]
    meta: dict = {}
    cur = None
    for n, ln in enumerate(lines[1:end], start=2):
        if not ln.strip():
            continue
        it = ITEM_RE.match(ln)
        if it:
            if cur is None:
                errors.append(f"строка {n}: пункт списка без ключа flags/todo над ним")
            else:
                meta[cur].append(it.group(1).strip())
            continue
        kv = KEY_RE.match(ln)
        if not kv:
            errors.append(f"строка {n}: ожидалось «ключ: значение» или «  - пункт»: {ln.strip()[:60]!r}")
            cur = None
            continue
        key, val = kv.group(1), (kv.group(2) or "").strip()
        if key in meta:
            errors.append(f"строка {n}: ключ {key} повторяется")
        if key in LISTS:
            if val:
                errors.append(f"строка {n}: {key} — список, значения идут пунктами «  - …» ниже")
            meta[key] = []
            cur = key
        elif key in SCALARS:
            meta[key] = val
            cur = None
        else:
            errors.append(f"строка {n}: неизвестный ключ {key!r} (допустимы: {', '.join(SCALARS + LISTS)})")
            cur = None
    body = "\n".join(lines[end + 1:])
    return meta, body, errors


def split_flag(item: str):
    parts = [p.strip() for p in item.split("|", 2)]
    return parts if len(parts) == 3 else None


def check(text: str, labs: dict | None = None, filename: str | None = None):
    """-> (errors, warnings, meta)."""
    meta, body, errors = parse(text)
    warnings: list[str] = []
    E, W = errors.append, warnings.append
    if not meta and errors:
        return errors, warnings, meta
    if meta.get("schema") != SCHEMA:
        E(f"schema: нужно {SCHEMA}, а не {meta.get('schema')!r}")
    for k in ("title", "summary"):
        v = meta.get(k, "")
        if not v:
            E(f"{k}: обязательно")
        elif len(v) > LIMITS[k]:
            E(f"{k}: {len(v)} символов > {LIMITS[k]}")
    if not iso_ok(meta.get("date", "")):
        E(f"date: нужно ГГГГ-ММ-ДД, а не {meta.get('date')!r}")
    if "data_asof" in meta:
        if not iso_ok(meta["data_asof"]):
            E(f"data_asof: нужно ГГГГ-ММ-ДД, а не {meta['data_asof']!r}")
        elif iso_ok(meta.get("date", "")) and meta["data_asof"] > meta["date"]:
            E(f"data_asof {meta['data_asof']} позже даты отчёта {meta['date']}")
    for k, v in meta.items():
        if k in SCALARS and len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            W(f"{k}: значение в кавычках — кавычки останутся в тексте")
    flags = meta.get("flags", [])
    if len(flags) > LIMITS["flags"]:
        E(f"flags: {len(flags)} > {LIMITS['flags']} — главное, а не всё подряд")
    for i, f in enumerate(flags, 1):
        p = split_flag(f)
        if not p:
            E(f"flags[{i}]: нужно «уровень | заголовок | пояснение»: {f[:60]!r}")
            continue
        lvl, title, txt = p
        if lvl not in LEVELS:
            E(f"flags[{i}]: уровень {lvl!r} — один из {', '.join(LEVELS)}")
        if not title or len(title) > LIMITS["flag_title"]:
            E(f"flags[{i}]: заголовок пуст или длиннее {LIMITS['flag_title']}")
        if not txt or len(txt) > LIMITS["flag_text"]:
            E(f"flags[{i}]: пояснение пусто или длиннее {LIMITS['flag_text']}")
    todo = meta.get("todo", [])
    if len(todo) > LIMITS["todo"]:
        E(f"todo: {len(todo)} > {LIMITS['todo']}")
    for i, t in enumerate(todo, 1):
        if len(t) > LIMITS["todo_item"]:
            E(f"todo[{i}]: {len(t)} символов > {LIMITS['todo_item']}")
    if "markers" in meta:
        ids = [x.strip() for x in meta["markers"].split(",") if x.strip()]
        if len(ids) > LIMITS["markers"]:
            E(f"markers: {len(ids)} > {LIMITS['markers']}")
        if len(set(ids)) != len(ids):
            E("markers: id повторяется")
        if labs is not None:
            known = {m["id"] for m in labs.get("biomarkers", [])}
            for x in ids:
                if x not in known:
                    E(f"markers: {x!r} нет в labs.json")
        else:
            W("markers не сверены с labs.json (нет --labs)")
    if not body.strip():
        E("тело отчёта пустое")
    if re.search(r"<(script|iframe|style|div|table|img)\b", body, re.I):
        W("в теле сырой HTML — страница покажет его текстом, не разметкой")
    if filename:
        m = NAME_RE.match(unicodedata.normalize("NFC", filename))
        if not m:
            W(f"имя {filename!r} не по образцу ГГГГ-ММ-ДД-тема.md")
        elif meta.get("date") and m.group(1) != meta["date"]:
            W(f"дата в имени {m.group(1)} ≠ date {meta['date']}")
    return errors, warnings, meta


def slug(topic: str) -> str:
    s = unicodedata.normalize("NFC", topic).strip().lower()
    s = re.sub(r"[^a-zа-яё0-9]+", "-", s).strip("-")
    return s


def load_labs(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def cmd_check(a) -> int:
    p = Path(a.report)
    errors, warnings, meta = check(p.read_text(encoding="utf-8"), load_labs(a.labs), p.name)
    if a.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "meta": meta}, ensure_ascii=False, indent=1))
    else:
        for e in errors:
            print("  ✗", e)
        for w in warnings:
            print("  ⚠", w)
        print(f"{p.name}: {'ОШИБКИ — ' + str(len(errors)) if errors else 'формат в порядке'}"
              + (f", предупреждений {len(warnings)}" if warnings else ""))
    return 1 if errors else 0


def cmd_save(a) -> int:
    src = Path(a.report)
    text = src.read_text(encoding="utf-8")
    errors, warnings, meta = check(text, load_labs(a.labs))
    for e in errors:
        print("  ✗", e)
    for w in warnings:
        print("  ⚠", w)
    if errors:
        print("не сохраняю: исправьте ошибки формата")
        return 1
    t = slug(a.topic)
    if not t:
        print("  ✗ --topic пуст после очистки")
        return 1
    dst = Path(a.health) / "reports" / f"{meta['date']}-{t}.md"
    if dst.exists():
        if dst.read_bytes() == text.encode("utf-8"):
            print(f"{dst.name}: уже лежит, содержимое то же — ничего не делаю")
            return 0
        print(f"  ✗ {dst.name} уже есть с другим содержимым — возьмите другую тему; "
              f"старый удаляет только владелец")
        return 1
    if not a.apply:
        print(f"dry-run: запишу reports/{dst.name} ({len(text.encode('utf-8'))} Б) — повторите с --apply")
        return 0
    hub_settings.require_ai(dst, "validate_report.py save --apply", "сохранение отчёта", zones=("Health",))   # вход — вывод модели
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    print(f"записано: reports/{dst.name}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("report")
    c.add_argument("--labs")
    c.add_argument("--json", action="store_true")
    s = sub.add_parser("save")
    s.add_argument("report")
    s.add_argument("--health", required=True)
    s.add_argument("--topic", required=True)
    s.add_argument("--labs")
    s.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    return cmd_check(a) if a.cmd == "check" else cmd_save(a)


if __name__ == "__main__":
    sys.exit(main())
